package auth

// This file is NOT part of ITER-0000's committed scope. The real 2FA
// escalation policy (Telegram-based, reply-to-message disambiguation,
// source-chain credentials) is EPIC-015/STORY-0026 et al., deferred to
// ITER-0001 per docs/superpowers/iterations/roadmap.md.
//
// It exists because JOURNEY-0001's non-goals explicitly acknowledge the
// walking skeleton's live proof-run needs a real account with live
// credentials, and "SRP/2FA cannot be faked" — closing that journey once,
// interactively, against a real 2FA-enabled account needed *some* way to
// submit a code. This is that minimal, unautomated escape hatch: no
// Telegram, no source chain, no persistence beyond one process's lifetime.
// It should be deleted once ITER-0001 lands the real thing, not extended.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
)

// TrustedPhoneNumber is one phone number Apple can send an SMS 2FA code to.
type TrustedPhoneNumber struct {
	ID               int
	ObfuscatedNumber string
}

var bootArgsPattern = regexp.MustCompile(`(?s)<script[^>]*class="boot_args"[^>]*>(.*?)</script>`)

// TrustedPhoneNumbers fetches the list of trusted phone numbers by scraping
// the JSON embedded in idmsa.apple.com/appleauth/auth's HTML response
// (there is no clean JSON API for this step — ported from sms.py's
// parse_trusted_phone_numbers_payload).
func (c *Client) TrustedPhoneNumbers(ctx context.Context, sess *Session) ([]TrustedPhoneNumber, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, AuthEndpoint, nil)
	if err != nil {
		return nil, err
	}
	c.set2FAHeaders(req, sess)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != 200 && resp.StatusCode != 204 {
		return nil, nil
	}

	m := bootArgsPattern.FindSubmatch(body)
	if m == nil {
		return nil, fmt.Errorf("auth: boot_args script not found in trusted-phone-numbers response")
	}

	var parsed struct {
		Direct struct {
			TwoSV struct {
				PhoneNumberVerification struct {
					TrustedPhoneNumbers []struct {
						ID               int    `json:"id"`
						ObfuscatedNumber string `json:"obfuscatedNumber"`
					} `json:"trustedPhoneNumbers"`
				} `json:"phoneNumberVerification"`
				BridgeInitiateData struct {
					PhoneNumberVerification struct {
						TrustedPhoneNumbers []struct {
							ID               int    `json:"id"`
							ObfuscatedNumber string `json:"obfuscatedNumber"`
						} `json:"trustedPhoneNumbers"`
					} `json:"phoneNumberVerification"`
				} `json:"bridgeInitiateData"`
			} `json:"twoSV"`
		} `json:"direct"`
	}
	if err := json.Unmarshal(m[1], &parsed); err != nil {
		return nil, fmt.Errorf("auth: parsing boot_args JSON: %w", err)
	}

	numbers := parsed.Direct.TwoSV.PhoneNumberVerification.TrustedPhoneNumbers
	if len(numbers) == 0 {
		numbers = parsed.Direct.TwoSV.BridgeInitiateData.PhoneNumberVerification.TrustedPhoneNumbers
	}

	out := make([]TrustedPhoneNumber, 0, len(numbers))
	for _, n := range numbers {
		out = append(out, TrustedPhoneNumber{ID: n.ID, ObfuscatedNumber: n.ObfuscatedNumber})
	}
	return out, nil
}

// SendSMSCode triggers Apple to text a 2FA code to deviceID.
func (c *Client) SendSMSCode(ctx context.Context, sess *Session, deviceID int) error {
	body, _ := json.Marshal(map[string]any{
		"phoneNumber": map[string]any{"id": deviceID},
		"mode":        "sms",
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, AuthEndpoint+"/verify/phone", bytes.NewReader(body))
	if err != nil {
		return err
	}
	c.set2FAHeaders(req, sess)
	req.Header.Set("Content-Type", "application/json; charset=utf-8")

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("auth: send SMS code: status %d: %s", resp.StatusCode, respBody)
	}
	return nil
}

// VerifySMSCode submits the code the user received by SMS.
func (c *Client) VerifySMSCode(ctx context.Context, sess *Session, deviceID int, code string) error {
	body, _ := json.Marshal(map[string]any{
		"phoneNumber":  map[string]any{"id": deviceID},
		"securityCode": map[string]any{"code": code},
		"mode":         "sms",
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, AuthEndpoint+"/verify/phone/securitycode", bytes.NewReader(body))
	if err != nil {
		return err
	}
	c.set2FAHeaders(req, sess)
	req.Header.Set("Content-Type", "application/json; charset=utf-8")
	req.Header.Set("Accept", "application/json; charset=utf-8")

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("auth: verify SMS code: status %d: %s", resp.StatusCode, respBody)
	}
	return nil
}

// TrustSession asks Apple to trust this session going forward, so a
// subsequent AccountLogin call succeeds without requiring 2FA again this
// process lifetime. Unlike VerifySMSCode/SendSMSCode/TrustedPhoneNumbers
// (which use sms.py's narrower OAuth-only headers), the reference client's
// trust_session() uses the FULL _get_auth_headers() set — matching
// setAuthHeaders here, not set2FAHeaders.
func (c *Client) TrustSession(ctx context.Context, sess *Session) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, AuthEndpoint+"/2sv/trust", nil)
	if err != nil {
		return err
	}
	c.pendingScnt = sess.Scnt
	c.pendingSessionID = sess.SessionID
	c.setAuthHeaders(req, AuthRootEndpoint)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("auth: trust session: status %d: %s", resp.StatusCode, respBody)
	}
	return nil
}

func (c *Client) set2FAHeaders(req *http.Request, sess *Session) {
	req.Header.Set("X-Apple-OAuth-Client-Id", oauthClientID)
	req.Header.Set("X-Apple-OAuth-Client-Type", "firstPartyAuth")
	req.Header.Set("X-Apple-OAuth-Require-Grant-Code", "true")
	req.Header.Set("X-Apple-Widget-Key", oauthClientID)
	req.Header.Set("X-Apple-OAuth-Redirect-URI", "https://www.icloud.com")
	req.Header.Set("X-Apple-OAuth-State", c.ClientID)
	req.Header.Set("scnt", sess.Scnt)
	req.Header.Set("X-Apple-ID-Session-Id", sess.SessionID)
}
