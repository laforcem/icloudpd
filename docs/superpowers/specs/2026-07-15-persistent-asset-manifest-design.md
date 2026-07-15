# Persistent Asset Manifest — Design

## Context

icloudpd is currently stateless across runs: for every iCloud asset it computes the expected local path (from `folder_structure` + the active `file_match_policy`) and checks `os.path.isfile()`. There is no stored mapping between an iCloud asset (`recordName`) and the local file it produced, and no memory of what a previous run downloaded.

This is sufficient for one-way copy/sync (iCloud → local) but blocks a class of features that need to know "have I seen this asset before, and where did it go":

- **Sync deletions back to iCloud** (the motivating sub-project — see `2026-07-15-sync-deletions-to-icloud-design.md`, to be written once this lands): detecting that a locally-downloaded asset has disappeared (e.g. deleted via Immich) requires comparing "downloaded last run" against "present now." Filesystem state alone can't distinguish "never downloaded" from "downloaded, now deleted."
- **`--until-found X` robustness**: today this is a heuristic — stop after N *consecutive* existing local files, assuming stable enumeration order. A gap (a prior transient error, a filter change) can produce a false early-stop. An identity lookup removes the guesswork.
- **`--auto-delete` identity matching**: Recently Deleted items are currently matched to local files by filename under the active `file_match_policy`. Changing `folder_structure` or `file_match_policy`, or a manual rename, can silently break the match. `recordName → path` lookup makes it exact.
- **Rename-on-policy-change**: changing `--folder-structure` or `--file-match-policy` today causes a full re-download under the new path/name scheme, leaving old copies as orphaned duplicates. A `recordName → path` lookup is the prerequisite for detecting "already have this, just move it" instead of re-fetching.

This sub-project builds only the manifest infrastructure. It is **additive-only**: the existing `isfile()`-based skip logic in the download loop is untouched. No behavior changes for existing features. The schema is chosen so all four consumers above can be built later without a migration, but only the manifest itself (write path + backfill) ships here.

## Scope

In scope:
- SQLite-backed manifest module (`src/icloudpd/manifest.py`)
- Write path: record a manifest row after each successful download, and refresh `last_seen_utc` for assets confirmed present via the existing `isfile()` check
- One-time backfill for pre-existing download directories
- Unit + integration tests for the manifest module and its write path

Out of scope (future sub-projects, not this design):
- Sync-deletions-to-iCloud (consumes this manifest)
- `--until-found` rewrite, `--auto-delete` identity matching, rename-on-policy-change (all future consumers of this manifest)
- Checksum population (column exists, stays `NULL` until a consumer needs it)

## Architecture

A new module, `src/icloudpd/manifest.py`, wraps a SQLite database stored at `<download_dir>/.icloudpd/state.db`.

**One manifest per download directory.** This matches icloudpd's existing per-`--directory` isolation for multi-account/multi-library setups (each `--username ... --directory ...` pair is already independent). Tradeoffs considered:

- *Per-directory (chosen)*: matches the existing model, no cross-account key collisions, portable (moving/copying the directory carries its state with it), trivial single-writer locking.
- *Centralized*: would enable cross-library queries later, but requires account/directory as part of the key, shared-file locking across concurrently-running instances, and is less portable. Rejected — no current requirement justifies the added complexity.

The module exposes a narrow interface; nothing outside `manifest.py` touches SQL directly:

```python
def open(download_dir: str) -> ManifestHandle: ...
def record_downloaded(handle, record_name: str, local_path: str, size_bytes: int) -> None: ...
def touch_seen(handle, record_name: str) -> None: ...
def get(handle, record_name: str) -> ManifestRow | None: ...
def all_records(handle) -> Iterator[ManifestRow]: ...
def prune(handle, record_name: str) -> None: ...
```

## Schema

```sql
CREATE TABLE downloaded_assets (
    record_name         TEXT PRIMARY KEY,
    local_path           TEXT NOT NULL,
    size_bytes            INTEGER NOT NULL,
    checksum              TEXT NULL,
    first_downloaded_utc TEXT NOT NULL,
    last_seen_utc        TEXT NOT NULL
);
```

`checksum` is nullable and left unpopulated by this sub-project — it exists so a future rename/corruption-detection consumer doesn't require a migration. It only matters once something needs to disambiguate a same-size-different-content match (e.g. rename detection after a `folder_structure` change); nothing in this sub-project needs it.

## Write path

- On successful download in `base.py` (after `download_media()` succeeds): call `record_downloaded(handle, recordName, path, size_bytes)`, which upserts the row and sets `first_downloaded_utc` (if new) and `last_seen_utc` to now.
- For assets that pass the existing `isfile()` skip check (i.e. already downloaded, no-op this run): call `touch_seen(handle, recordName)` to refresh `last_seen_utc`. This is what lets a future deletion-sync feature distinguish "seen last run, missing now" (deleted) from "never seen" (irrelevant).
- Manifest writes are **best-effort** and never block or fail a download. If a write fails (disk full, lock contention), log a warning and continue. A missing/stale manifest row is not data loss — it's corrected by the backfill logic on a subsequent run.

## Backfill

On first run after upgrading (detected via a `schema_version` marker row, so it only runs once): for each iCloud asset in the current listing, if `isfile(expected_path)` is true and no manifest row exists for its `recordName`, insert one with `first_downloaded_utc = last_seen_utc = now`. This ensures manifest-dependent features work against the full existing library immediately, not only against files downloaded after the upgrade.

## Error handling

- Manifest unavailable (can't open/create the sqlite file): log a warning once per run, continue with existing filesystem-only behavior. The manifest is infrastructure for *other* features — its absence must never break core download/sync behavior.
- Individual write/read failures: logged at debug/warning level, never raised into the download loop.

## Testing

- Unit tests for `manifest.py` in isolation: open/record/touch/get/prune against a temporary sqlite file, including the upsert and backfill-marker behavior.
- One integration test asserting that a successful download in the existing download-flow tests also produces a corresponding manifest row.
- Backfill test: pre-populate a download directory with files matching iCloud assets but no manifest, run once, assert rows are created with today's timestamp and the marker prevents a second backfill pass.

## Open questions for later sub-projects (not blocking this design)

- Whether Sync-deletions-to-iCloud detects "missing" via `last_seen_utc` staleness (skipped a run) vs. immediate absence (missing this run) — to be decided in that sub-project's design, informed by watch-interval cadence.
- Whether the two icloudpd instances currently run against Immich's two external libraries could be consolidated into one multi-`--username`/`--library` invocation — noted as a possible follow-up, unrelated to this design.
