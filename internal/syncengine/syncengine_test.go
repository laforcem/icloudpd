package syncengine

import (
	"context"
	"crypto/sha1" //nolint:gosec // matches Apple's fileChecksum format, confirmed live
	"encoding/base64"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/laforcem/icloudpd/internal/asset"
	"github.com/laforcem/icloudpd/internal/enumerate"
	"github.com/laforcem/icloudpd/internal/store"
)

func appleChecksum(data []byte) string {
	sum := sha1.Sum(data) //nolint:gosec // matches Apple's fileChecksum format, confirmed live
	return base64.StdEncoding.EncodeToString(append([]byte{0x01}, sum[:]...))
}

// fakeEnumerator yields a fixed list of assets, all Present.
type fakeEnumerator struct {
	assets []asset.Asset
}

func (f *fakeEnumerator) Capabilities() enumerate.Capabilities {
	return enumerate.Capabilities{Exhaustive: true, Resumable: true}
}

func (f *fakeEnumerator) Enumerate(ctx context.Context, from enumerate.Cursor, yield func(context.Context, enumerate.Change) error) (enumerate.Cursor, error) {
	for _, a := range f.assets {
		if err := yield(ctx, enumerate.Change{Kind: enumerate.Present, Asset: a}); err != nil {
			return nil, err
		}
	}
	return enumerate.Cursor("done"), nil
}

// fakeStore lets tests inject a write failure on a specific call.
type fakeStore struct {
	writes    []store.AssetRow
	failAfter int // fail the (failAfter+1)-th write; -1 means never fail
}

func (s *fakeStore) WriteAsset(ctx context.Context, row store.AssetRow) error {
	if s.failAfter >= 0 && len(s.writes) == s.failAfter {
		return errors.New("simulated disk error")
	}
	s.writes = append(s.writes, row)
	return nil
}

func (s *fakeStore) GetAsset(ctx context.Context, key asset.Key) (*store.AssetRow, error) {
	for _, w := range s.writes {
		if w.Key == key {
			return &w, nil
		}
	}
	return nil, nil
}

func (s *fakeStore) Close() error { return nil }

func testAsset(recordName string, content []byte, server *httptest.Server) asset.Asset {
	return asset.Asset{
		Key:      asset.Key{AccountID: "acct1", ZoneKind: asset.ZoneKindPrimary, ZoneName: "PrimarySync", RecordName: recordName},
		Filename: recordName + ".heic",
		ItemType: "public.heic",
		Original: asset.Version{
			Size:        int64(len(content)),
			DownloadURL: server.URL + "/" + recordName,
			FileType:    "public.heic",
			Checksum:    appleChecksum(content),
		},
	}
}

// TestRun_StoreWriteFailure_AbortsRunFatal is SCENARIO-0027's evidence
// (STORY-0038 AC-1): a store write failure aborts the account run
// immediately; the download loop does not continue past it.
func TestRun_StoreWriteFailure_AbortsRunFatal(t *testing.T) {
	contentA := []byte("photo-a-bytes")
	contentB := []byte("photo-b-bytes")

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/asset-a":
			w.Write(contentA)
		case "/asset-b":
			w.Write(contentB)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer server.Close()

	assets := []asset.Asset{
		testAsset("asset-a", contentA, server),
		testAsset("asset-b", contentB, server),
	}
	fs := &fakeStore{failAfter: 0} // fail on the very first write
	opts := Options{
		AccountID:    "acct1",
		Enumerator:   &fakeEnumerator{assets: assets},
		HTTPClient:   server.Client(),
		Store:        fs,
		DownloadRoot: t.TempDir(),
	}

	result, err := Run(context.Background(), opts)
	if err == nil {
		t.Fatal("expected a fatal error from the store write failure, got nil")
	}
	if result.AssetsDownloaded != 0 {
		t.Fatalf("AssetsDownloaded = %d, want 0 (the run must abort before counting a failed write)", result.AssetsDownloaded)
	}
	if len(fs.writes) != 0 {
		t.Fatalf("expected the second asset to never reach the store, got %d writes", len(fs.writes))
	}
}

// TestRun_HappyPath_RecordsEveryAsset proves the run loop completes and
// writes a manifest row for each asset when nothing fails — the baseline
// JOURNEY-0001 needs, with N=2 instead of 1 to also prove the loop doesn't
// stop after the first asset.
func TestRun_HappyPath_RecordsEveryAsset(t *testing.T) {
	contentA := []byte("photo-a-bytes")
	contentB := []byte("photo-b-bytes")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/asset-a":
			w.Write(contentA)
		case "/asset-b":
			w.Write(contentB)
		}
	}))
	defer server.Close()

	assets := []asset.Asset{
		testAsset("asset-a", contentA, server),
		testAsset("asset-b", contentB, server),
	}
	fs := &fakeStore{failAfter: -1}
	opts := Options{
		AccountID:    "acct1",
		Enumerator:   &fakeEnumerator{assets: assets},
		HTTPClient:   server.Client(),
		Store:        fs,
		DownloadRoot: t.TempDir(),
	}

	result, err := Run(context.Background(), opts)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if result.AssetsDownloaded != 2 {
		t.Fatalf("AssetsDownloaded = %d, want 2", result.AssetsDownloaded)
	}
	if len(fs.writes) != 2 {
		t.Fatalf("got %d manifest writes, want 2", len(fs.writes))
	}
}

// TestRun_TelemetryFailure_DoesNotAbortRun is SCENARIO-0027's other half
// (STORY-0038 AC-2): a logging/telemetry failure never aborts the run. Go's
// slog contract already guarantees this (Logger methods never surface a
// Handler's error to the caller); this test proves the engine relies on
// that guarantee rather than accidentally checking a logging result.
func TestRun_TelemetryFailure_DoesNotAbortRun(t *testing.T) {
	content := []byte("photo-bytes")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(content)
	}))
	defer server.Close()

	failingLogger := newFailingLogger()
	fs := &fakeStore{failAfter: -1}
	opts := Options{
		AccountID:    "acct1",
		Enumerator:   &fakeEnumerator{assets: []asset.Asset{testAsset("asset-a", content, server)}},
		HTTPClient:   server.Client(),
		Store:        fs,
		DownloadRoot: t.TempDir(),
		Logger:       failingLogger,
	}

	result, err := Run(context.Background(), opts)
	if err != nil {
		t.Fatalf("Run: %v (a telemetry/logging failure must not abort the run)", err)
	}
	if result.AssetsDownloaded != 1 {
		t.Fatalf("AssetsDownloaded = %d, want 1", result.AssetsDownloaded)
	}
	if len(fs.writes) != 1 {
		t.Fatalf("got %d manifest writes, want 1", len(fs.writes))
	}
}

// newFailingLogger builds an slog.Logger whose Handler always errors, to
// prove that failure is contained.
func newFailingLogger() *slog.Logger {
	return slog.New(&alwaysFailHandler{})
}

type alwaysFailHandler struct{}

func (h *alwaysFailHandler) Enabled(context.Context, slog.Level) bool { return true }
func (h *alwaysFailHandler) Handle(context.Context, slog.Record) error {
	return fmt.Errorf("simulated telemetry sink failure")
}
func (h *alwaysFailHandler) WithAttrs(attrs []slog.Attr) slog.Handler { return h }
func (h *alwaysFailHandler) WithGroup(name string) slog.Handler       { return h }
