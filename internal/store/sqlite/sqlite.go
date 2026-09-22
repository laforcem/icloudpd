// Package sqlite is the one Store implementation this iteration ships: a
// single WAL-mode SQLite database at <state_dir>/icloudpd.db, shared across
// every configured account (STORY-0040) — no per-account or per-directory
// database file is ever created. modernc.org/sqlite is pure Go (no cgo), so
// it doesn't compromise the design's static-binary requirement.
package sqlite

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"

	_ "modernc.org/sqlite"

	"github.com/laforcem/icloudpd/internal/asset"
	"github.com/laforcem/icloudpd/internal/store"
)

const schema = `
CREATE TABLE IF NOT EXISTS assets (
	account_id              TEXT    NOT NULL,
	zone_kind               TEXT    NOT NULL,
	zone_name               TEXT    NOT NULL,
	record_name             TEXT    NOT NULL,
	filename                TEXT    NOT NULL,
	item_type               TEXT    NOT NULL,
	added_date_unix_millis  INTEGER NOT NULL,
	original_size           INTEGER NOT NULL,
	original_checksum       TEXT    NOT NULL,
	rel_path                TEXT    NOT NULL,
	downloaded_at_utc       TEXT    NOT NULL,
	PRIMARY KEY (account_id, zone_kind, zone_name, record_name)
);
`

// DB is a SQLite-backed Store.
type DB struct {
	sql *sql.DB
}

// DBPath is the one location this service ever opens a database at
// (STORY-0040 AC-1): <state_dir>/icloudpd.db, regardless of how many
// accounts or download directories are configured.
func DBPath(stateDir string) string {
	return filepath.Join(stateDir, "icloudpd.db")
}

// Open opens (creating if needed) the single shared WAL-mode database at
// DBPath(stateDir) and applies the schema.
func Open(ctx context.Context, stateDir string) (*DB, error) {
	dsn := DBPath(stateDir) + "?_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)"
	sqlDB, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("sqlite: opening %s: %w", DBPath(stateDir), err)
	}
	// A single shared DB with concurrent per-account writers (a later
	// iteration's concern, EPIC-024) needs one writer at a time; capping the
	// pool here costs nothing now and avoids "database is locked" errors
	// once concurrency lands.
	sqlDB.SetMaxOpenConns(1)

	if _, err := sqlDB.ExecContext(ctx, schema); err != nil {
		sqlDB.Close()
		return nil, fmt.Errorf("sqlite: applying schema: %w", err)
	}
	return &DB{sql: sqlDB}, nil
}

func (db *DB) WriteAsset(ctx context.Context, row store.AssetRow) error {
	_, err := db.sql.ExecContext(ctx, `
		INSERT INTO assets (
			account_id, zone_kind, zone_name, record_name,
			filename, item_type, added_date_unix_millis,
			original_size, original_checksum, rel_path, downloaded_at_utc
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT (account_id, zone_kind, zone_name, record_name) DO UPDATE SET
			filename = excluded.filename,
			item_type = excluded.item_type,
			added_date_unix_millis = excluded.added_date_unix_millis,
			original_size = excluded.original_size,
			original_checksum = excluded.original_checksum,
			rel_path = excluded.rel_path,
			downloaded_at_utc = excluded.downloaded_at_utc
	`,
		row.Key.AccountID, string(row.Key.ZoneKind), row.Key.ZoneName, row.Key.RecordName,
		row.Filename, row.ItemType, row.AddedDateMillis,
		row.OriginalSize, row.Checksum, row.RelPath, row.DownloadedAtUTC,
	)
	if err != nil {
		return fmt.Errorf("sqlite: writing asset %s: %w", row.Key.RecordName, err)
	}
	return nil
}

func (db *DB) GetAsset(ctx context.Context, key asset.Key) (*store.AssetRow, error) {
	row := db.sql.QueryRowContext(ctx, `
		SELECT filename, item_type, added_date_unix_millis, original_size, original_checksum, rel_path, downloaded_at_utc
		FROM assets
		WHERE account_id = ? AND zone_kind = ? AND zone_name = ? AND record_name = ?
	`, key.AccountID, string(key.ZoneKind), key.ZoneName, key.RecordName)

	var out store.AssetRow
	out.Key = key
	err := row.Scan(&out.Filename, &out.ItemType, &out.AddedDateMillis, &out.OriginalSize, &out.Checksum, &out.RelPath, &out.DownloadedAtUTC)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("sqlite: reading asset %s: %w", key.RecordName, err)
	}
	return &out, nil
}

func (db *DB) Close() error {
	return db.sql.Close()
}
