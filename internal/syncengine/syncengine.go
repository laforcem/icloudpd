// Package syncengine drives one account's run loop: enumerate → download →
// record. It accepts a narrow Options struct built by internal/app
// (STORY-0132) rather than the whole per-account config, and treats a
// manifest store write failure as fatal for the run (STORY-0038) while
// telemetry stays best-effort.
package syncengine

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"path/filepath"
	"time"

	"github.com/laforcem/icloudpd/internal/asset"
	"github.com/laforcem/icloudpd/internal/download"
	"github.com/laforcem/icloudpd/internal/enumerate"
	"github.com/laforcem/icloudpd/internal/store"
)

// Options is the narrow, purpose-built struct internal/app assembles for
// one account's run — never the whole per-account config (STORY-0132 AC-1).
type Options struct {
	AccountID    string
	Enumerator   enumerate.Enumerator
	HTTPClient   *http.Client
	Store        store.Store
	DownloadRoot string
	Logger       *slog.Logger // best-effort telemetry; nil is valid (uses slog.Default())
	Now          func() time.Time
}

// Result summarizes one completed run, for the caller (CLI/service surface)
// to report or exit on.
type Result struct {
	AssetsDownloaded int
}

// Run executes one full account sync: enumerate every asset from a fresh
// cursor, download each one's original bytes with checksum verification,
// and record it in the manifest. It stops and returns a fatal error the
// moment a manifest write fails (STORY-0038 AC-1) — the download loop does
// not continue past that failure. Logging failures (telemetry) never abort
// the run (STORY-0038 AC-2): they go through Logger, which by design (Go's
// log/slog) never propagates a handler error back to the caller.
func Run(ctx context.Context, opts Options) (Result, error) {
	logger := opts.Logger
	if logger == nil {
		logger = slog.Default()
	}
	now := opts.Now
	if now == nil {
		now = time.Now
	}

	var result Result
	var runErr error

	_, err := opts.Enumerator.Enumerate(ctx, nil, func(ctx context.Context, change enumerate.Change) error {
		if change.Kind != enumerate.Present {
			return nil
		}
		a := change.Asset

		if err := downloadAndRecord(ctx, opts, a, now); err != nil {
			runErr = err
			return err // stop Enumerate's sweep; the loop does not continue past a store failure
		}
		result.AssetsDownloaded++

		logger.Info("asset synced", "record_name", a.Key.RecordName) // best-effort; Handle() errors never reach here
		return nil
	})
	if err != nil {
		if runErr != nil {
			return result, runErr
		}
		return result, fmt.Errorf("syncengine: enumerate: %w", err)
	}

	return result, nil
}

func downloadAndRecord(ctx context.Context, opts Options, a asset.Asset, now func() time.Time) error {
	relPath := a.Filename
	if relPath == "" {
		relPath = a.Key.RecordName
	}
	finalPath := filepath.Join(opts.DownloadRoot, relPath)

	if err := download.Fetch(ctx, opts.HTTPClient, a.Original.DownloadURL, finalPath, a.Original.Checksum); err != nil {
		return fmt.Errorf("syncengine: downloading %s: %w", a.Key.RecordName, err)
	}

	row := store.AssetRow{
		Key:             a.Key,
		Filename:        a.Filename,
		ItemType:        a.ItemType,
		AddedDateMillis: a.AddedDateUnixMillis,
		OriginalSize:    a.Original.Size,
		Checksum:        a.Original.Checksum,
		RelPath:         relPath,
		DownloadedAtUTC: now().UTC().Format(time.RFC3339),
	}
	if err := opts.Store.WriteAsset(ctx, row); err != nil {
		// STORY-0038 AC-1: a manifest write failure is fatal for this
		// account's run, not swallowed.
		return fmt.Errorf("syncengine: manifest write failed for %s (fatal): %w", a.Key.RecordName, err)
	}
	return nil
}
