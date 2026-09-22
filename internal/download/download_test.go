package download

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func appleChecksum(data []byte) string {
	sum := sha256.Sum256(data)
	return base64.StdEncoding.EncodeToString(append([]byte{0x01}, sum[:]...))
}

// TestFetch_HappyPath is SCENARIO-0116's evidence (STORY-0136 AC-1): bytes
// are fetched and written via temp-file-then-rename, and the final path only
// ever contains the complete file.
func TestFetch_HappyPath(t *testing.T) {
	content := []byte("this is definitely a photo, trust me")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(content)
	}))
	defer server.Close()

	dir := t.TempDir()
	finalPath := filepath.Join(dir, "sub", "photo.heic")

	err := Fetch(context.Background(), server.Client(), server.URL, finalPath, appleChecksum(content))
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}

	got, err := os.ReadFile(finalPath)
	if err != nil {
		t.Fatalf("reading final path: %v", err)
	}
	if string(got) != string(content) {
		t.Fatalf("content mismatch: got %q, want %q", got, content)
	}

	entries, err := os.ReadDir(filepath.Dir(finalPath))
	if err != nil {
		t.Fatalf("reading destination dir: %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("expected exactly 1 file in destination dir (no leftover temp file), got %d", len(entries))
	}
}

// TestFetch_ChecksumMismatch_LeavesNoFinalFile is SCENARIO-0013's evidence
// (STORY-0019 AC-1): a checksum mismatch is a failed download, and no
// partial or wrong file is ever left at the final path.
func TestFetch_ChecksumMismatch_LeavesNoFinalFile(t *testing.T) {
	content := []byte("real bytes")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(content)
	}))
	defer server.Close()

	dir := t.TempDir()
	finalPath := filepath.Join(dir, "photo.heic")

	wrongChecksum := appleChecksum([]byte("different bytes entirely"))
	err := Fetch(context.Background(), server.Client(), server.URL, finalPath, wrongChecksum)
	if err == nil {
		t.Fatal("expected a checksum mismatch error, got nil")
	}
	var mismatch *ErrChecksumMismatch
	if !asChecksumMismatch(err, &mismatch) {
		t.Fatalf("expected *ErrChecksumMismatch, got %T: %v", err, err)
	}

	if _, statErr := os.Stat(finalPath); !os.IsNotExist(statErr) {
		t.Fatalf("expected no file at finalPath after a checksum mismatch, stat err = %v", statErr)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 0 {
		t.Fatalf("expected no leftover temp files after a checksum mismatch, found %d", len(entries))
	}
}

func TestFetch_HTTPErrorStatus_LeavesNoFinalFile(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	dir := t.TempDir()
	finalPath := filepath.Join(dir, "photo.heic")

	err := Fetch(context.Background(), server.Client(), server.URL, finalPath, appleChecksum([]byte("x")))
	if err == nil {
		t.Fatal("expected an error for a 404 response, got nil")
	}
	if _, statErr := os.Stat(finalPath); !os.IsNotExist(statErr) {
		t.Fatalf("expected no file at finalPath after an HTTP error, stat err = %v", statErr)
	}
}

func TestVerifyChecksum_MalformedFileChecksum(t *testing.T) {
	err := VerifyChecksum([]byte("data"), "not-valid-base64!!!")
	if err == nil {
		t.Fatal("expected an error for malformed base64 fileChecksum")
	}
}

func asChecksumMismatch(err error, target **ErrChecksumMismatch) bool {
	if m, ok := err.(*ErrChecksumMismatch); ok {
		*target = m
		return true
	}
	return false
}
