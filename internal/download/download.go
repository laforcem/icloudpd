// Package download fetches an asset version's bytes and writes them to
// their final path via a temp-file-then-rename sequence (STORY-0136), then
// verifies the written bytes against Apple's fileChecksum (STORY-0019).
package download

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
)

// ErrChecksumMismatch is returned when the downloaded bytes' checksum does
// not match Apple's fileChecksum — treated as a failed download, not
// accepted (STORY-0019 AC-1 / SCENARIO-0013).
type ErrChecksumMismatch struct {
	Got  string
	Want string
}

func (e *ErrChecksumMismatch) Error() string {
	return fmt.Sprintf("download: checksum mismatch: got %s, want %s", e.Got, e.Want)
}

// VerifyChecksum computes a checksum over data and compares it to Apple's
// fileChecksum (base64-encoded, as provided in asset-version metadata).
//
// Working hypothesis (unconfirmed against Apple's server until this
// iteration's live proof-run, see JOURNEY-0001): fileChecksum decodes to a
// leading version byte (0x01, MMCS's "signature version" marker) followed by
// the SHA-256 digest of the complete file. This matches the community's
// long-standing pyicloud/icloud-photos-downloader observation, but the
// reference Python client itself has never verified it (only used it to
// build a temp-file name) — this Go implementation is the first in this
// codebase's lineage to actually check it. If ErrChecksumMismatch fires
// against real downloaded bytes from a live account, treat that as evidence
// the hypothesis is wrong, not that the download is corrupt — the mismatch
// error carries both checksums for that diagnosis.
func VerifyChecksum(data []byte, appleFileChecksum string) error {
	sum := sha256.Sum256(data)
	return verifyDigest(sum[:], appleFileChecksum)
}

// verifyDigest compares an already-computed SHA-256 digest against Apple's
// fileChecksum, so callers streaming a download don't need to buffer the
// whole file a second time just to re-hash it.
func verifyDigest(digest []byte, appleFileChecksum string) error {
	decoded, err := base64.StdEncoding.DecodeString(appleFileChecksum)
	if err != nil {
		return fmt.Errorf("download: decoding fileChecksum: %w", err)
	}
	if len(decoded) != 1+sha256.Size {
		return fmt.Errorf("download: fileChecksum has unexpected length %d (want %d = 1 version byte + sha256)", len(decoded), 1+sha256.Size)
	}
	wantDigest := decoded[1:]

	if string(digest) != string(wantDigest) {
		return &ErrChecksumMismatch{
			Got:  base64.StdEncoding.EncodeToString(digest),
			Want: base64.StdEncoding.EncodeToString(wantDigest),
		}
	}
	return nil
}

// Fetch downloads url's bytes and writes them to finalPath via a temp file
// in the same directory, renamed into place only after the write and
// checksum verification succeed. finalPath never exists as a partial file:
// on any failure (network error, checksum mismatch), the temp file is
// removed and finalPath is untouched (STORY-0136 AC-1, SCENARIO-0116).
func Fetch(ctx context.Context, httpClient *http.Client, url, finalPath, appleFileChecksum string) error {
	if err := os.MkdirAll(filepath.Dir(finalPath), 0o755); err != nil {
		return fmt.Errorf("download: creating destination directory: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return fmt.Errorf("download: building request: %w", err)
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("download: fetching %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("download: fetching %s: status %d", url, resp.StatusCode)
	}

	tmp, err := os.CreateTemp(filepath.Dir(finalPath), ".download-*.tmp")
	if err != nil {
		return fmt.Errorf("download: creating temp file: %w", err)
	}
	tmpPath := tmp.Name()
	// Removed on every path except the successful rename at the end.
	succeeded := false
	defer func() {
		if !succeeded {
			os.Remove(tmpPath)
		}
	}()

	hasher := sha256.New()
	_, err = io.Copy(io.MultiWriter(tmp, hasher), resp.Body)
	closeErr := tmp.Close()
	if err != nil {
		return fmt.Errorf("download: writing %s: %w", tmpPath, err)
	}
	if closeErr != nil {
		return fmt.Errorf("download: closing %s: %w", tmpPath, closeErr)
	}

	if err := verifyDigest(hasher.Sum(nil), appleFileChecksum); err != nil {
		return err
	}

	if err := os.Rename(tmpPath, finalPath); err != nil {
		return fmt.Errorf("download: renaming into place: %w", err)
	}
	succeeded = true
	return nil
}
