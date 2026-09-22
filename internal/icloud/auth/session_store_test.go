package auth

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSaveLoadSession_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	stateDir := filepath.Join(dir, "state")
	appleID := "user@example.com"

	got, err := LoadSession(stateDir, appleID)
	if err != nil {
		t.Fatalf("LoadSession on empty state_dir: %v", err)
	}
	if got != nil {
		t.Fatalf("expected nil session before any save, got %+v", got)
	}

	want := &Session{
		AccountCountry: "USA",
		SessionID:      "sid",
		SessionToken:   "tok",
		TrustToken:     "trust",
		Scnt:           "scnt-value",
	}
	if err := SaveSession(stateDir, appleID, want); err != nil {
		t.Fatalf("SaveSession: %v", err)
	}

	got, err = LoadSession(stateDir, appleID)
	if err != nil {
		t.Fatalf("LoadSession: %v", err)
	}
	if *got != *want {
		t.Fatalf("round trip mismatch:\n got %+v\nwant %+v", got, want)
	}
}

func TestSessionPath_NoSeparateConfigurablePath(t *testing.T) {
	// STORY-0031 AC-1: session data lives only under state_dir, keyed by a
	// sanitized apple_id, with no other configurable location.
	stateDir := "/var/lib/icloudpd/state"
	appleID := "weird+chars.user@example.com"
	got := SessionPath(stateDir, appleID)

	if filepath.Dir(got) != stateDir {
		t.Fatalf("session path %q is not under state_dir %q", got, stateDir)
	}
	if filepath.Base(got) == appleID+".session.json" {
		t.Fatalf("expected apple_id to be sanitized, got raw id in filename: %q", got)
	}
}

func TestSessionStore_NoLegacyCookieRead(t *testing.T) {
	dir := t.TempDir()
	appleID := "user@example.com"

	// Simulate a pre-existing Python-version cookie file sitting next to
	// where the Go session would live. LoadSession must ignore it entirely
	// (no cookie-format parsing exists in this package) and report "no
	// session" rather than attempting to interpret it.
	legacyCookiePath := filepath.Join(dir, sanitizeAppleID(appleID))
	if err := os.WriteFile(legacyCookiePath, []byte("not json, not our format"), 0o600); err != nil {
		t.Fatalf("writing fake legacy cookie: %v", err)
	}

	got, err := LoadSession(dir, appleID)
	if err != nil {
		t.Fatalf("LoadSession must not error on an unrelated legacy file: %v", err)
	}
	if got != nil {
		t.Fatalf("expected nil (no session found), got %+v", got)
	}
}
