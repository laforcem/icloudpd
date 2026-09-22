// Package store defines the manifest Store interface. internal/store/sqlite
// is the one implementation this iteration ships (STORY-0040: one shared
// SQLite DB for the whole service).
package store

import (
	"context"

	"github.com/laforcem/icloudpd/internal/asset"
)

// AssetRow is what the manifest records about one downloaded asset. The
// walking skeleton keeps this flat (no separate files table — that's
// STORY-0042, not committed to this iteration); rel_path/downloaded_at
// describe the single original-size file this iteration ever writes.
type AssetRow struct {
	Key             asset.Key
	Filename        string
	ItemType        string
	AddedDateMillis int64
	OriginalSize    int64
	Checksum        string
	RelPath         string
	DownloadedAtUTC string // RFC 3339
}

// Store is the manifest write/read seam. A write failure must propagate to
// the caller honestly — STORY-0038's "abort the run on store failure"
// behavior is the syncengine's responsibility to enforce, not the store's,
// but the store must never swallow an error itself.
type Store interface {
	WriteAsset(ctx context.Context, row AssetRow) error
	GetAsset(ctx context.Context, key asset.Key) (*AssetRow, error)
	Close() error
}
