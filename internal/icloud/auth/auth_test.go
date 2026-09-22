package auth

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/laforcem/icloudpd/internal/icloud/srp"
)

// These tests exercise auth's HTTP wire-level plumbing — request shape,
// base64 framing, header extraction, status-code mapping — against a fake
// idmsa.apple.com. SRP's cryptographic correctness is proven independently
// in internal/icloud/srp against fixed reference vectors, so the fake server
// here only needs to hand back a structurally valid B (nonzero mod N); it
// doesn't need to be a full server-side SRP implementation to prove the
// transport is wired correctly.
func fixedServerB(t *testing.T) []byte {
	t.Helper()
	// Any client public key is a structurally valid stand-in for a server's
	// B here — both are "some nonzero value mod N" from this fake's point of
	// view, since it never actually verifies M1.
	c, err := srp.NewClient("server-stand-in", nil)
	if err != nil {
		t.Fatalf("generating fake server B: %v", err)
	}
	return c.PublicKey()
}

func TestSignIn_HappyPath(t *testing.T) {
	appleID := "test@example.com"
	password := "hunter2-but-longer"
	salt := []byte("0123456789abcdef")
	iterations := 1000
	protocol := "s2k"
	serverB := fixedServerB(t)

	mux := http.NewServeMux()
	var capturedInit map[string]any

	mux.HandleFunc("/appleauth/auth/signin/init", func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&capturedInit); err != nil {
			t.Errorf("server: decoding init body: %v", err)
		}
		if got := capturedInit["accountName"]; got != appleID {
			t.Errorf("init accountName = %v, want %v", got, appleID)
		}
		if _, ok := capturedInit["a"]; !ok {
			t.Error("init request missing client public key 'a'")
		}
		json.NewEncoder(w).Encode(map[string]any{
			"salt":      base64.StdEncoding.EncodeToString(salt),
			"iteration": iterations,
			"protocol":  protocol,
			"c":         "opaque-challenge-id",
			"b":         base64.StdEncoding.EncodeToString(serverB),
		})
	})

	mux.HandleFunc("/appleauth/auth/signin/complete", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("server: decoding complete body: %v", err)
		}
		if body["c"] != "opaque-challenge-id" {
			t.Errorf("complete c = %v, want opaque-challenge-id", body["c"])
		}
		for _, field := range []string{"m1", "m2", "accountName"} {
			if _, ok := body[field]; !ok {
				t.Errorf("complete request missing %q", field)
			}
		}
		w.Header().Set("X-Apple-Session-Token", "fake-session-token")
		w.Header().Set("X-Apple-ID-Session-Id", "fake-session-id")
		w.Header().Set("X-Apple-ID-Account-Country", "USA")
		w.WriteHeader(http.StatusOK)
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client := &Client{
		HTTP:     &http.Client{Transport: rewriteHost(server.URL)},
		AppleID:  appleID,
		ClientID: "test-client-id",
	}
	sess, err := client.SignIn(context.Background(), password)
	if err != nil {
		t.Fatalf("SignIn: %v", err)
	}
	if sess.SessionToken != "fake-session-token" {
		t.Errorf("SessionToken = %q, want fake-session-token", sess.SessionToken)
	}
	if sess.SessionID != "fake-session-id" {
		t.Errorf("SessionID = %q, want fake-session-id", sess.SessionID)
	}
	if sess.AccountCountry != "USA" {
		t.Errorf("AccountCountry = %q, want USA", sess.AccountCountry)
	}
}

func TestSignIn_TwoFactorRequired(t *testing.T) {
	serverB := fixedServerB(t)
	mux := http.NewServeMux()
	mux.HandleFunc("/appleauth/auth/signin/init", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{
			"salt":      base64.StdEncoding.EncodeToString([]byte("saltsaltsaltsalt")),
			"iteration": 1000,
			"protocol":  "s2k",
			"c":         "chal",
			"b":         base64.StdEncoding.EncodeToString(serverB),
		})
	})
	mux.HandleFunc("/appleauth/auth/signin/complete", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusConflict)
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	client := &Client{HTTP: &http.Client{Transport: rewriteHost(server.URL)}, AppleID: "u@example.com", ClientID: "cid"}
	_, err := client.SignIn(context.Background(), "pw")
	if err != ErrTwoFactorRequired {
		t.Fatalf("expected ErrTwoFactorRequired, got %v", err)
	}
}

func TestSignIn_RejectedBySever(t *testing.T) {
	serverB := fixedServerB(t)
	mux := http.NewServeMux()
	mux.HandleFunc("/appleauth/auth/signin/init", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{
			"salt":      base64.StdEncoding.EncodeToString([]byte("saltsaltsaltsalt")),
			"iteration": 1000,
			"protocol":  "s2k",
			"c":         "chal",
			"b":         base64.StdEncoding.EncodeToString(serverB),
		})
	})
	mux.HandleFunc("/appleauth/auth/signin/complete", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		w.Write([]byte(`{"error":"wrong password"}`))
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	client := &Client{HTTP: &http.Client{Transport: rewriteHost(server.URL)}, AppleID: "u@example.com", ClientID: "cid"}
	_, err := client.SignIn(context.Background(), "wrong-password")
	if err == nil {
		t.Fatal("expected an error for a server-rejected signin, got nil")
	}
	failedLogin, ok := err.(*ErrFailedLogin)
	if !ok {
		t.Fatalf("expected *ErrFailedLogin, got %T: %v", err, err)
	}
	if failedLogin.StatusCode != http.StatusUnauthorized {
		t.Errorf("StatusCode = %d, want 401", failedLogin.StatusCode)
	}
}

func TestSignIn_InitTransportError(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/appleauth/auth/signin/init", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte("server exploded"))
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	client := &Client{HTTP: &http.Client{Transport: rewriteHost(server.URL)}, AppleID: "u@example.com", ClientID: "cid"}
	_, err := client.SignIn(context.Background(), "pw")
	if err == nil {
		t.Fatal("expected an error, got nil")
	}
	if !strings.Contains(err.Error(), "signin/init") {
		t.Fatalf("expected a signin/init error, got %v", err)
	}
}

// rewriteHost redirects requests for the real idmsa.apple.com host to an
// httptest server, so production code (which hardcodes the real endpoint
// constants) can be exercised without parameterizing them for tests.
type rewriteHostTransport struct{ base string }

func rewriteHost(base string) http.RoundTripper {
	return &rewriteHostTransport{base: base}
}

func (t *rewriteHostTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	u := *req.URL
	u.Scheme = "http"
	u.Host = strings.TrimPrefix(strings.TrimPrefix(t.base, "http://"), "https://")
	req2 := req.Clone(req.Context())
	req2.URL = &u
	req2.Host = u.Host
	return http.DefaultTransport.RoundTrip(req2)
}
