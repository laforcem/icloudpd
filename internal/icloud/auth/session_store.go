package auth

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
)

// sanitizeAppleID mirrors base.py's sanitize_apple_id: strip an Apple ID
// down to word characters only, for safe use as a filename component.
var wordChar = regexp.MustCompile(`\w`)

func sanitizeAppleID(appleID string) string {
	var b []byte
	for _, r := range appleID {
		if wordChar.MatchString(string(r)) {
			b = append(b, string(r)...)
		}
	}
	return string(b)
}

// SessionPath returns where an account's session data lives under stateDir.
// This is the only session location the Go rewrite ever reads or writes —
// there is no separate configurable session path, and no pre-existing
// Python-version cookie file is read (STORY-0031 AC-1).
func SessionPath(stateDir, appleID string) string {
	return filepath.Join(stateDir, sanitizeAppleID(appleID)+".session.json")
}

// SaveSession persists sess as JSON at SessionPath(stateDir, appleID),
// creating stateDir if needed.
func SaveSession(stateDir, appleID string, sess *Session) error {
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return fmt.Errorf("auth: creating state_dir %q: %w", stateDir, err)
	}
	data, err := json.MarshalIndent(sess, "", "  ")
	if err != nil {
		return fmt.Errorf("auth: marshalling session: %w", err)
	}
	path := SessionPath(stateDir, appleID)
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return fmt.Errorf("auth: writing session file: %w", err)
	}
	if err := os.Rename(tmp, path); err != nil {
		return fmt.Errorf("auth: renaming session file into place: %w", err)
	}
	return nil
}

// LoadSession reads a previously-saved session, if any. A missing file is
// not an error: it returns (nil, nil), signalling "no prior session, do a
// fresh SRP handshake."
func LoadSession(stateDir, appleID string) (*Session, error) {
	data, err := os.ReadFile(SessionPath(stateDir, appleID))
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("auth: reading session file: %w", err)
	}
	var sess Session
	if err := json.Unmarshal(data, &sess); err != nil {
		return nil, fmt.Errorf("auth: parsing session file: %w", err)
	}
	return &sess, nil
}
