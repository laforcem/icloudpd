// Package download fetches an asset version's bytes and writes them to
// their final path via a temp-file-then-rename sequence (STORY-0136), then
// checks the written size against Apple's reported size (STORY-0019,
// descoped from content-hash verification — see the package doc below).
package download

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
)

// ErrSizeMismatch is returned when the downloaded byte count does not match
// the size CloudKit reported for this asset version — treated as a failed
// download, not accepted (STORY-0019 AC-1 / SCENARIO-0013).
//
// This checks size, not a content hash, against Apple's fileChecksum. That
// field's algorithm was confirmed during this iteration's live proof-run
// (JOURNEY-0001) to NOT be a plain hash of the file: decoding a real
// checksum and comparing it against SHA-1/SHA-256 of the actual downloaded
// bytes failed, and structural analysis showed the CPLMaster recordName is
// literally `0x01 || fileChecksum` — the value is Apple's MMCS
// content-addressable identifier (chunked, aggregated), not a
// straightforward digest. Independent confirmation: steilerDev/
// icloud-photos-sync (a mature, actively-maintained TypeScript iCloud
// Photos client) has an unused, commented-out verifyChecksum method whose
// own comment reads "This is currently NOT implemented, as the checksum
// algorithm is unknown" — its dead code shows it brute-forced every
// standard hash (MD5, SHA1, SHA224/256/384/512, SHA3 family, BLAKE2, SM3)
// across multiple encodings, plus HMAC-keyed variants, with no match.
// Reproducing MMCS's exact algorithm is out of scope for this iteration;
// the raw fileChecksum value is still recorded in the manifest for
// possible future use, just not verified against downloaded content.
type ErrSizeMismatch struct {
	GotBytes     int64
	ExpectedSize int64
}

func (e *ErrSizeMismatch) Error() string {
	return fmt.Sprintf("download: size mismatch: got %d bytes, want %d", e.GotBytes, e.ExpectedSize)
}

// Fetch downloads url's bytes and writes them to finalPath via a temp file
// in the same directory, renamed into place only after the write and size
// check succeed. finalPath never exists as a partial file: on any failure
// (network error, size mismatch), the temp file is removed and finalPath is
// untouched (STORY-0136 AC-1, SCENARIO-0116).
func Fetch(ctx context.Context, httpClient *http.Client, url, finalPath string, expectedSize int64) error {
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

	written, err := io.Copy(tmp, resp.Body)
	closeErr := tmp.Close()
	if err != nil {
		return fmt.Errorf("download: writing %s: %w", tmpPath, err)
	}
	if closeErr != nil {
		return fmt.Errorf("download: closing %s: %w", tmpPath, closeErr)
	}

	if expectedSize > 0 && written != expectedSize {
		return &ErrSizeMismatch{GotBytes: written, ExpectedSize: expectedSize}
	}

	if err := os.Rename(tmpPath, finalPath); err != nil {
		return fmt.Errorf("download: renaming into place: %w", err)
	}
	succeeded = true
	return nil
}
