// Package auth implements Apple's idmsa.apple.com SRP sign-in flow and
// session persistence, ported from src/pyicloud_ipd/base.py's
// _authenticate_srp/_authenticate_with_token. It owns HTTP transport for the
// auth phase only; internal/icloud/ckws owns the CloudKit transport that
// follows a successful sign-in.
package auth

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"

	"github.com/laforcem/icloudpd/internal/icloud/srp"
)

// Endpoints for the "com" domain. STORY-0031/config-schema work in a later
// iteration adds "cn" domain support; this walking skeleton only needs one.
const (
	AuthRootEndpoint = "https://idmsa.apple.com"
	AuthEndpoint     = "https://idmsa.apple.com/appleauth/auth"
	SetupEndpoint    = "https://setup.icloud.com/setup/ws/1"
)

// These header/param values are copied verbatim from base.py's
// _get_auth_headers — they identify this client to Apple's auth service and
// are not secrets.
const (
	oauthClientID = "d39ba9916b7251055b22c7f910e2ea796ee65e98b2ddecea8f5dde8d9d1a815d"
	userAgent     = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

// ErrTwoFactorRequired signals a 409 response from signin/complete: the
// account needs a 2FA code before the session is usable. Handling that
// escalation is out of scope for the walking skeleton (STORY-0026/EPIC-015,
// ITER-0001) — this iteration's proof-run account has no 2FA configured.
var ErrTwoFactorRequired = fmt.Errorf("auth: two-factor authentication required")

// ErrFailedLogin wraps a non-2xx signin/complete response that isn't the
// (expected, harmless) 2FA-required case.
type ErrFailedLogin struct {
	StatusCode int
	Body       string
}

func (e *ErrFailedLogin) Error() string {
	return fmt.Sprintf("auth: signin failed with status %d: %s", e.StatusCode, e.Body)
}

// Session holds what a successful SRP handshake yields: the values needed to
// request an account/web session token next, plus whatever cookies the HTTP
// client accumulated along the way (the caller's http.Client with a
// CookieJar carries those; Session only carries the header-derived fields
// base.py's HEADER_DATA table extracts).
type Session struct {
	AccountCountry string
	SessionID      string
	SessionToken   string
	TrustToken     string
	Scnt           string
}

// Client drives the SRP sign-in handshake over HTTP.
type Client struct {
	HTTP     *http.Client
	AppleID  string
	ClientID string // Apple's client_id/X-Apple-OAuth-State value

	// pendingScnt/pendingSessionID let a caller (see auth_2fa_assist.go's
	// TrustSession) carry a signin/complete response's scnt/session_id
	// forward into setAuthHeaders' full header set, matching base.py's
	// _get_auth_headers() reading self.session_data. Not set by the
	// committed SignIn path itself.
	pendingScnt      string
	pendingSessionID string
}

type srpInitRequest struct {
	A           string   `json:"a"`
	AccountName string   `json:"accountName"`
	Protocols   []string `json:"protocols"`
}

type srpInitResponse struct {
	Salt      string `json:"salt"`
	B         string `json:"b"`
	C         string `json:"c"`
	Iteration int    `json:"iteration"`
	Protocol  string `json:"protocol"`
}

type srpCompleteRequest struct {
	AccountName string   `json:"accountName"`
	C           string   `json:"c"`
	M1          string   `json:"m1"`
	M2          string   `json:"m2"`
	RememberMe  bool     `json:"rememberMe"`
	TrustTokens []string `json:"trustTokens"`
}

// SignIn runs the full SRP handshake: signin/init, then signin/complete.
// password is the plaintext account password; it is used only to derive the
// SRP key material in-process and is never itself transmitted.
func (c *Client) SignIn(ctx context.Context, password string) (*Session, error) {
	client, err := srp.NewClient(c.AppleID, nil)
	if err != nil {
		return nil, fmt.Errorf("auth: starting SRP client: %w", err)
	}

	initResp, err := c.signInInit(ctx, client)
	if err != nil {
		return nil, fmt.Errorf("auth: signin/init: %w", err)
	}

	salt, err := base64.StdEncoding.DecodeString(initResp.Salt)
	if err != nil {
		return nil, fmt.Errorf("auth: decoding salt: %w", err)
	}
	b, err := base64.StdEncoding.DecodeString(initResp.B)
	if err != nil {
		return nil, fmt.Errorf("auth: decoding B: %w", err)
	}

	derived, err := srp.DerivePassword(password, srp.Protocol(initResp.Protocol), salt, initResp.Iteration)
	if err != nil {
		return nil, fmt.Errorf("auth: deriving password key: %w", err)
	}

	challenge, err := client.ProcessChallenge(salt, b, derived)
	if err != nil {
		return nil, fmt.Errorf("auth: processing SRP challenge: %w", err)
	}

	return c.signInComplete(ctx, c.AppleID, initResp.C, challenge)
}

func (c *Client) signInInit(ctx context.Context, sc *srp.Client) (*srpInitResponse, error) {
	reqBody := srpInitRequest{
		A:           base64.StdEncoding.EncodeToString(sc.PublicKey()),
		AccountName: c.AppleID,
		Protocols:   []string{"s2k", "s2k_fo"},
	}
	body, err := json.Marshal(reqBody)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, AuthEndpoint+"/signin/init", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	c.setAuthHeaders(req, AuthRootEndpoint)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode == http.StatusUnauthorized {
		return nil, &ErrFailedLogin{StatusCode: resp.StatusCode, Body: string(respBody)}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &ErrFailedLogin{StatusCode: resp.StatusCode, Body: string(respBody)}
	}

	// base.py's session wrapper updates session_data from every response's
	// HEADER_DATA-listed headers, including signin/init's — and
	// signin/complete's own _get_auth_headers() call then reads those back.
	// Carry scnt/session_id forward the same way.
	if scnt := resp.Header.Get("scnt"); scnt != "" {
		c.pendingScnt = scnt
	}
	if sessionID := resp.Header.Get("X-Apple-ID-Session-Id"); sessionID != "" {
		c.pendingSessionID = sessionID
	}

	var initResp srpInitResponse
	if err := json.Unmarshal(respBody, &initResp); err != nil {
		return nil, fmt.Errorf("decoding signin/init response: %w", err)
	}
	return &initResp, nil
}

func (c *Client) signInComplete(ctx context.Context, accountName, cValue string, challenge *srp.ChallengeResult) (*Session, error) {
	reqBody := srpCompleteRequest{
		AccountName: accountName,
		C:           cValue,
		M1:          base64.StdEncoding.EncodeToString(challenge.M1),
		M2:          base64.StdEncoding.EncodeToString(challenge.ClientHAMK),
		RememberMe:  true,
		TrustTokens: []string{},
	}
	body, err := json.Marshal(reqBody)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, AuthEndpoint+"/signin/complete?isRememberMeEnabled=true", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	c.setAuthHeaders(req, AuthRootEndpoint)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(resp.Body)

	switch {
	case resp.StatusCode == http.StatusConflict: // 409: 2FA required
		// Apple still sets scnt/session_id on this response — the auth
		// session exists, it's just not yet elevated past 2FA. Callers
		// that need to complete 2FA (out of this iteration's committed
		// scope; see auth_2fa_assist.go) need those values, so return the
		// partial session alongside the sentinel error rather than
		// discarding it.
		return sessionFromHeaders(resp.Header), ErrTwoFactorRequired
	case resp.StatusCode >= 400 && resp.StatusCode < 600:
		return nil, &ErrFailedLogin{StatusCode: resp.StatusCode, Body: string(respBody)}
	}

	return sessionFromHeaders(resp.Header), nil
}

func sessionFromHeaders(h http.Header) *Session {
	return &Session{
		AccountCountry: h.Get("X-Apple-ID-Account-Country"),
		SessionID:      h.Get("X-Apple-ID-Session-Id"),
		SessionToken:   h.Get("X-Apple-Session-Token"),
		TrustToken:     h.Get("X-Apple-TwoSV-Trust-Token"),
		Scnt:           h.Get("scnt"),
	}
}

func (c *Client) setAuthHeaders(req *http.Request, originReferer string) {
	req.Header.Set("Accept", "application/json, text/javascript")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Apple-OAuth-Client-Id", oauthClientID)
	req.Header.Set("X-Apple-OAuth-Client-Type", "firstPartyAuth")
	req.Header.Set("X-Apple-OAuth-Redirect-URI", "https://www.icloud.com")
	req.Header.Set("X-Apple-OAuth-Require-Grant-Code", "true")
	req.Header.Set("X-Apple-OAuth-Response-Mode", "web_message")
	req.Header.Set("X-Apple-OAuth-Response-Type", "code")
	req.Header.Set("X-Apple-OAuth-State", c.ClientID)
	req.Header.Set("X-Apple-Widget-Key", oauthClientID)
	req.Header.Set("Origin", originReferer)
	req.Header.Set("Referer", originReferer+"/")
	req.Header.Set("User-Agent", userAgent)
	if c.pendingScnt != "" {
		req.Header.Set("scnt", c.pendingScnt)
	}
	if c.pendingSessionID != "" {
		req.Header.Set("X-Apple-ID-Session-Id", c.pendingSessionID)
	}
}

// AccountLogin exchanges a persisted session token for a fresh web session
// (base.py's _authenticate_with_token), used on subsequent runs so a
// previously-authenticated account doesn't need a fresh SRP handshake.
func (c *Client) AccountLogin(ctx context.Context, sess *Session) (map[string]any, error) {
	reqBody := map[string]any{
		"accountCountryCode": sess.AccountCountry,
		"dsWebAuthToken":     sess.SessionToken,
		"extended_login":     true,
		"trustToken":         sess.TrustToken,
	}
	body, err := json.Marshal(reqBody)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, SetupEndpoint+"/accountLogin", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Origin", "https://www.icloud.com")
	req.Header.Set("Referer", "https://www.icloud.com/")
	req.Header.Set("User-Agent", userAgent)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &ErrFailedLogin{StatusCode: resp.StatusCode, Body: string(respBody)}
	}

	var data map[string]any
	if err := json.Unmarshal(respBody, &data); err != nil {
		return nil, fmt.Errorf("decoding accountLogin response: %w", err)
	}
	return data, nil
}
