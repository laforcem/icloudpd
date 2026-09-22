package sqlite

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/laforcem/icloudpd/internal/asset"
	"github.com/laforcem/icloudpd/internal/store"
)

func TestWriteAndGetAsset_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	db, err := Open(context.Background(), dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	key := asset.Key{AccountID: "acct1", ZoneKind: asset.ZoneKindPrimary, ZoneName: "PrimarySync", RecordName: "master-1"}
	row := store.AssetRow{
		Key: key, Filename: "photo.heic", ItemType: "public.heic",
		AddedDateMillis: 1000, OriginalSize: 12345, Checksum: "chk",
		RelPath: "2026/09/photo.heic", DownloadedAtUTC: "2026-09-22T00:00:00Z",
	}
	if err := db.WriteAsset(context.Background(), row); err != nil {
		t.Fatalf("WriteAsset: %v", err)
	}

	got, err := db.GetAsset(context.Background(), key)
	if err != nil {
		t.Fatalf("GetAsset: %v", err)
	}
	if got == nil {
		t.Fatal("expected a row, got nil")
	}
	if *got != row {
		t.Fatalf("round trip mismatch:\n got %+v\nwant %+v", got, row)
	}
}

func TestGetAsset_NotFound(t *testing.T) {
	dir := t.TempDir()
	db, err := Open(context.Background(), dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	got, err := db.GetAsset(context.Background(), asset.Key{AccountID: "acct1", ZoneKind: asset.ZoneKindPrimary, ZoneName: "PrimarySync", RecordName: "nope"})
	if err != nil {
		t.Fatalf("GetAsset: %v", err)
	}
	if got != nil {
		t.Fatalf("expected nil for a missing asset, got %+v", got)
	}
}

// TestSameCPLMasterKeyCollapsesToOneRow is STORY-0041 AC-1's storage-layer
// half: writing two rows under the same (account, zone_kind, zone_name,
// record_name) key — as photos.pairRecords already collapses duplicate
// CPLAsset records to before this ever calls WriteAsset — must leave exactly
// one row, keyed on that primary key.
func TestSameCPLMasterKeyCollapsesToOneRow(t *testing.T) {
	dir := t.TempDir()
	db, err := Open(context.Background(), dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	key := asset.Key{AccountID: "acct1", ZoneKind: asset.ZoneKindPrimary, ZoneName: "PrimarySync", RecordName: "master-1"}
	first := store.AssetRow{Key: key, Filename: "old.heic", ItemType: "public.heic", Checksum: "old-checksum", RelPath: "a", DownloadedAtUTC: "t1"}
	second := store.AssetRow{Key: key, Filename: "new.heic", ItemType: "public.heic", Checksum: "new-checksum", RelPath: "b", DownloadedAtUTC: "t2"}

	if err := db.WriteAsset(context.Background(), first); err != nil {
		t.Fatalf("WriteAsset(first): %v", err)
	}
	if err := db.WriteAsset(context.Background(), second); err != nil {
		t.Fatalf("WriteAsset(second): %v", err)
	}

	var count int
	if err := db.sql.QueryRow("SELECT COUNT(*) FROM assets").Scan(&count); err != nil {
		t.Fatalf("counting rows: %v", err)
	}
	if count != 1 {
		t.Fatalf("expected exactly 1 row for the same CPLMaster key, got %d", count)
	}

	got, err := db.GetAsset(context.Background(), key)
	if err != nil {
		t.Fatalf("GetAsset: %v", err)
	}
	if got.Checksum != "new-checksum" {
		t.Fatalf("checksum = %q, want new-checksum (latest write wins)", got.Checksum)
	}
}

// TestOneSharedDBRegardlessOfAccountCount is SCENARIO-0118's evidence
// (STORY-0040 AC-1): opening the store once and writing assets under
// several distinct account IDs still leaves exactly one database file at
// <state_dir>/icloudpd.db.
func TestOneSharedDBRegardlessOfAccountCount(t *testing.T) {
	dir := t.TempDir()
	db, err := Open(context.Background(), dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	accounts := []string{"account-a", "account-b", "account-c"}
	for i, acct := range accounts {
		row := store.AssetRow{
			Key:      asset.Key{AccountID: acct, ZoneKind: asset.ZoneKindPrimary, ZoneName: "PrimarySync", RecordName: "master"},
			Filename: "photo.heic", ItemType: "public.heic",
			AddedDateMillis: int64(i), OriginalSize: 1, Checksum: "chk", RelPath: "p", DownloadedAtUTC: "t",
		}
		if err := db.WriteAsset(context.Background(), row); err != nil {
			t.Fatalf("WriteAsset for %s: %v", acct, err)
		}
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("reading state_dir: %v", err)
	}

	dbFiles := 0
	for _, e := range entries {
		if filepath.Ext(e.Name()) == ".db" || e.Name() == "icloudpd.db" {
			dbFiles++
		}
	}
	if dbFiles != 1 {
		names := make([]string, len(entries))
		for i, e := range entries {
			names[i] = e.Name()
		}
		t.Fatalf("expected exactly 1 database file regardless of account count, found %d: %v", dbFiles, names)
	}

	for _, acct := range accounts {
		got, err := db.GetAsset(context.Background(), asset.Key{AccountID: acct, ZoneKind: asset.ZoneKindPrimary, ZoneName: "PrimarySync", RecordName: "master"})
		if err != nil {
			t.Fatalf("GetAsset for %s: %v", acct, err)
		}
		if got == nil {
			t.Fatalf("expected a row for account %s in the shared DB", acct)
		}
	}
}

func TestWriteAsset_FailsAfterClose(t *testing.T) {
	dir := t.TempDir()
	db, err := Open(context.Background(), dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if err := db.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	err = db.WriteAsset(context.Background(), store.AssetRow{
		Key: asset.Key{AccountID: "a", ZoneKind: asset.ZoneKindPrimary, ZoneName: "PrimarySync", RecordName: "m"},
	})
	if err == nil {
		t.Fatal("expected WriteAsset on a closed DB to return an error, not swallow it")
	}
}
