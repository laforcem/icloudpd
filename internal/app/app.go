// Package app is the composition root: the only package that wires concrete
// types together from config (STORY-0132 AC-1 — internal/config never
// crosses into syncengine's API surface; app translates it into
// syncengine.Options and friends here, once, at the boundary).
package app

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/cookiejar"
	"net/url"

	"github.com/laforcem/icloudpd/internal/config"
	"github.com/laforcem/icloudpd/internal/enumerate/full"
	"github.com/laforcem/icloudpd/internal/icloud/auth"
	"github.com/laforcem/icloudpd/internal/icloud/ckws"
	"github.com/laforcem/icloudpd/internal/icloud/photos"
	"github.com/laforcem/icloudpd/internal/store/sqlite"
	"github.com/laforcem/icloudpd/internal/syncengine"
)

// clientBuildNumber/clientMasteringNumber are copied verbatim from base.py
// — Apple's setup endpoint expects some value here; these are the reference
// client's, unclear if they need to be exact but there's no reason to
// diverge from what's known to work.
const (
	clientBuildNumber     = "2522Project44"
	clientMasteringNumber = "2522B2"
)

// SignedInAccount holds everything a signed-in account needs to run a sync:
// the authenticated HTTP client (cookie jar populated by SRP auth) and the
// resolved CloudKit database endpoint + dsid.
type SignedInAccount struct {
	CKWSClient *ckws.Client
	AccountID  string
}

// SignIn runs (or resumes) one account's authentication: reuse a persisted
// session if valid, otherwise perform a fresh SRP handshake (STORY-0031 —
// session data lives only under state_dir, no legacy cookie read).
func SignIn(ctx context.Context, cfg *config.Config, acct config.Account, logger *slog.Logger) (*SignedInAccount, error) {
	jar, err := cookiejar.New(nil)
	if err != nil {
		return nil, fmt.Errorf("app: creating cookie jar: %w", err)
	}
	httpClient := &http.Client{Jar: jar}

	authClient := &auth.Client{HTTP: httpClient, AppleID: acct.AppleID, ClientID: newClientID()}

	sess, err := auth.LoadSession(cfg.StateDir, acct.AppleID)
	if err != nil {
		return nil, fmt.Errorf("app: loading session: %w", err)
	}

	if sess == nil {
		logger.Info("no persisted session, performing fresh SRP handshake", "account", acct.Name)
		password, err := config.ReadPassword(acct)
		if err != nil {
			return nil, err
		}
		sess, err = authClient.SignIn(ctx, password)
		if err != nil {
			return nil, fmt.Errorf("app: SRP sign-in for account %s: %w", acct.Name, err)
		}
		if err := auth.SaveSession(cfg.StateDir, acct.AppleID, sess); err != nil {
			return nil, fmt.Errorf("app: saving session: %w", err)
		}
	}

	loginData, err := authClient.AccountLogin(ctx, sess)
	if err != nil {
		return nil, fmt.Errorf("app: accountLogin for account %s: %w", acct.Name, err)
	}

	dsid, ckdatabaseURL, err := extractLoginFields(loginData)
	if err != nil {
		return nil, fmt.Errorf("app: parsing accountLogin response: %w", err)
	}

	ckwsClient := &ckws.Client{
		HTTP:         httpClient,
		ServiceRoot:  ckdatabaseURL,
		DatabaseType: "private",
		Params:       photosParams(authClient.ClientID, dsid),
	}

	return &SignedInAccount{CKWSClient: ckwsClient, AccountID: acct.Name}, nil
}

// RunOnce runs a single synchronous pass over every configured account,
// stopping at the first account whose run returns a fatal error (STORY-0038)
// — this walking skeleton's journey is single-account, so "stop at the
// first failure" and "collect all failures" aren't yet distinguishable;
// multi-account fault isolation is EPIC-010/ITER-0003.
func RunOnce(ctx context.Context, cfg *config.Config, logger *slog.Logger) (map[string]syncengine.Result, error) {
	if logger == nil {
		logger = slog.Default()
	}

	db, err := sqlite.Open(ctx, cfg.StateDir)
	if err != nil {
		return nil, fmt.Errorf("app: opening manifest store: %w", err)
	}
	defer db.Close()

	results := make(map[string]syncengine.Result)
	for _, acct := range cfg.Accounts {
		signedIn, err := SignIn(ctx, cfg, acct, logger)
		if err != nil {
			return results, fmt.Errorf("app: signing in account %s: %w", acct.Name, err)
		}

		enumerator := &full.Enumerator{
			Client:    signedIn.CKWSClient,
			AccountID: signedIn.AccountID,
			ZoneName:  photos.PrimarySyncZone,
		}

		opts := syncengine.Options{
			AccountID:    signedIn.AccountID,
			Enumerator:   enumerator,
			HTTPClient:   signedIn.CKWSClient.HTTP,
			Store:        db,
			DownloadRoot: acct.DownloadDir,
			Logger:       logger,
		}

		result, err := syncengine.Run(ctx, opts)
		results[acct.Name] = result
		if err != nil {
			return results, fmt.Errorf("app: run for account %s: %w", acct.Name, err)
		}
	}
	return results, nil
}

func photosParams(clientID, dsid string) url.Values {
	return url.Values{
		"clientBuildNumber":     {clientBuildNumber},
		"clientMasteringNumber": {clientMasteringNumber},
		"clientId":              {clientID},
		"dsid":                  {dsid},
		"remapEnums":            {"true"},
		"getCurrentSyncToken":   {"true"},
	}
}

func newClientID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return "auth-" + hex.EncodeToString(b)
}

// extractLoginFields pulls dsInfo.dsid and webservices.ckdatabasews.url out
// of accountLogin's loosely-typed JSON response.
func extractLoginFields(loginData map[string]any) (dsid, ckdatabaseURL string, err error) {
	dsInfo, ok := loginData["dsInfo"].(map[string]any)
	if !ok {
		return "", "", fmt.Errorf("missing or malformed dsInfo")
	}
	dsidVal, ok := dsInfo["dsid"]
	if !ok {
		return "", "", fmt.Errorf("dsInfo missing dsid")
	}
	dsid = fmt.Sprintf("%v", dsidVal)

	webservices, ok := loginData["webservices"].(map[string]any)
	if !ok {
		return "", "", fmt.Errorf("missing or malformed webservices")
	}
	ckdb, ok := webservices["ckdatabasews"].(map[string]any)
	if !ok {
		return "", "", fmt.Errorf("webservices missing ckdatabasews")
	}
	urlVal, ok := ckdb["url"].(string)
	if !ok {
		return "", "", fmt.Errorf("ckdatabasews missing url")
	}
	return dsid, urlVal, nil
}
