package download

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

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

	err := Fetch(context.Background(), server.Client(), server.URL, finalPath, int64(len(content)))
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

// TestFetch_SizeMismatch_LeavesNoFinalFile is SCENARIO-0013's evidence
// (STORY-0019 AC-1, descoped to size verification — see download.go's
// package doc for why content-hash verification isn't implemented): a size
// mismatch is a failed download, and no partial or wrong file is ever left
// at the final path.
func TestFetch_SizeMismatch_LeavesNoFinalFile(t *testing.T) {
	content := []byte("real bytes")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(content)
	}))
	defer server.Close()

	dir := t.TempDir()
	finalPath := filepath.Join(dir, "photo.heic")

	err := Fetch(context.Background(), server.Client(), server.URL, finalPath, int64(len(content))+5)
	if err == nil {
		t.Fatal("expected a size mismatch error, got nil")
	}
	mismatch, ok := err.(*ErrSizeMismatch)
	if !ok {
		t.Fatalf("expected *ErrSizeMismatch, got %T: %v", err, err)
	}
	if mismatch.GotBytes != int64(len(content)) {
		t.Errorf("GotBytes = %d, want %d", mismatch.GotBytes, len(content))
	}

	if _, statErr := os.Stat(finalPath); !os.IsNotExist(statErr) {
		t.Fatalf("expected no file at finalPath after a size mismatch, stat err = %v", statErr)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 0 {
		t.Fatalf("expected no leftover temp files after a size mismatch, found %d", len(entries))
	}
}

func TestFetch_ZeroExpectedSizeSkipsCheck(t *testing.T) {
	content := []byte("some bytes of unknown expected length")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(content)
	}))
	defer server.Close()

	dir := t.TempDir()
	finalPath := filepath.Join(dir, "photo.heic")

	if err := Fetch(context.Background(), server.Client(), server.URL, finalPath, 0); err != nil {
		t.Fatalf("Fetch with expectedSize=0 should skip the size check: %v", err)
	}
	if _, err := os.Stat(finalPath); err != nil {
		t.Fatalf("expected the file to be written, stat err = %v", err)
	}
}

func TestFetch_HTTPErrorStatus_LeavesNoFinalFile(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	dir := t.TempDir()
	finalPath := filepath.Join(dir, "photo.heic")

	err := Fetch(context.Background(), server.Client(), server.URL, finalPath, 1)
	if err == nil {
		t.Fatal("expected an error for a 404 response, got nil")
	}
	if _, statErr := os.Stat(finalPath); !os.IsNotExist(statErr) {
		t.Fatalf("expected no file at finalPath after an HTTP error, stat err = %v", statErr)
	}
}
