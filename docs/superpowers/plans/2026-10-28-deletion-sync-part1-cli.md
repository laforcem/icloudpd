# Deletion Sync Part 1 (CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Photos whose local files were deleted move to iCloud's Recently Deleted on a later sync, behind a two-scan debounce and a cumulative circuit breaker, with a CLI to approve or reject held batches.

**Architecture:** A new module `src/icloudpd/deletion_sync.py` owns all deletion state (tables in the entry's existing `state.db`), the per-asset verdict, the end-of-scan breaker and execution, and the resolver. `download_builder` asks it for a verdict before downloading each asset; `core_single_run` opens a scan before enumeration and finishes it only after an uncancelled, exception-free enumeration. Config and CLI plumbing follow the existing `USER_OPTION_DEFAULTS` / `map_to_config` pattern.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, argparse, pytest + vcrpy cassettes, mypy `--strict`, ruff.

**Spec:** `docs/superpowers/specs/2026-10-28-deletion-sync-design.md` (Part 1 only). Read it before starting any task.

## Global Constraints

- Feature is off unless `sync_deletions: true`; with it off, behavior and `state.db` writes are unchanged except the additive schema migration.
- `deletion_sync_threshold`: default `-1` = no cap; `N ≥ 1` = hold at cumulative count `N`; `0` and values `< -1` are rejected.
- Cumulative count = `held` items + this scan's new candidates + items auto-deleted (not via approval) in the last **7 days**.
- Terminal rows (`deleted`, `skipped_gone`, `skipped_reappeared`) are pruned after **30 days**.
- Events: `deletion_sync_summary`, `deletion_sync_threshold_tripped`; `items` lists capped at **50**, with `total` alongside; `data` always has `library` and `directory`.
- Deletion state failures are hard errors for that entry's run (never swallowed like manifest writes).
- `--dry-run` never writes deletion state and fires no deletion events.
- One `records/modify` request per asset (batching is out of scope until a live test proves it).
- No undo/restore code. No change to the web UI.
- Every task passes: `uv run pytest -q`, `uv run mypy src tests --strict --python-version 3.10`, `uv run ruff check`, `uv run ruff format --check`.

## Review Focus

1. **Resolver run while a watch-mode process holds a write transaction** (manifest batches up to 100 writes per commit): the resolver must fail with a clear "database is busy, retry" message and exit non-zero, never hang forever or corrupt. Test in Task 5.
2. **Same asset visited twice in one scan** (`--album A --album B`, asset in both): the debounce advances once, no duplicate candidate. Test in Task 2.
3. **Upgrading an existing `state.db`** (no new columns or tables): migration succeeds, and with `sync_deletions` off nothing else changes. Test in Task 2.
4. **Notification script fails or is missing**: deletions and state still commit; the run doesn't fail. Test in Task 4.
5. **Interruption mid-execution** (exception on the 2nd of 3 deletes): the 1st stays `deleted` in the db, the rest stay retryable. Test in Task 4.

---

### Task 1: Config fields, CLI flags, startup validation

**Files:**
- Modify: `src/icloudpd/config.py` (`_DefaultConfig`), `src/icloudpd/config_defaults.py` (`USER_OPTION_DEFAULTS`), `src/icloudpd/config_file.py` (`_USER_BOOL_FIELDS`), `src/icloudpd/cli.py` (`add_options_for_user`, `map_to_config`, validation chain in `cli()`), `src/icloudpd/manifest.py`, `src/icloudpd/base.py` (`run_with_configs`, `_has_shared_state_directory` neighbor)
- Test: `tests/test_deletion_sync_config.py`, `tests/test_config_defaults.py` (should pass unchanged once defaults exist)

**Interfaces:**
- Produces: `UserConfig.sync_deletions: bool`, `UserConfig.deletion_sync_threshold: int`
- Produces: `manifest.db_path(download_dir: str, state_directory: str | None) -> str` — the path `manifest.open` uses; `open` is refactored to call it.
- Produces: `base._has_shared_deletion_db(logger: logging.Logger, user_configs: Sequence[UserConfig]) -> bool`

- [ ] **Step 1: Write the failing tests** in `tests/test_deletion_sync_config.py`:
  - `test_defaults`: parsing `-u a -d /x` yields `sync_deletions is False`, `deletion_sync_threshold == -1`.
  - `test_cli_flags`: `--sync-deletions --deletion-sync-threshold 25` yields `True`, `25`.
  - `test_yaml_keys`: a config file with `sync_deletions: true`, `deletion_sync_threshold: 10` under `users[0]` loads (no unknown-key error, no Norway-bool error).
  - `test_rejects_recent`, `test_rejects_until_found`: `cli()` returns `2` and prints a message containing `--sync-deletions` and the offending flag.
  - `test_rejects_without_mount_marker`: `--sync-deletions` without `--require-mount-marker` → `2`, message mentions `require_mount_marker`.
  - `test_rejects_threshold_zero` and `test_rejects_threshold_minus_two` → `2`.
  - `test_shared_default_db_rejected`: two entries, same `directory`, no `state_directory`, one with `sync_deletions` → `_has_shared_deletion_db` returns `True` and logs an error naming both usernames; `run_with_configs` returns `2`.
  - `test_shared_db_allowed_when_sync_off`: same layout, neither entry has `sync_deletions` → `False`.
  - `test_warns_unbounded_threshold` and `test_warns_no_state_directory`: `run_with_configs` logs a WARNING containing `deletion_sync_threshold` / `state_directory` respectively (patch the per-user processing to a no-op).
  - `test_db_path`: `db_path("/d", None) == "/d/.icloudpd/state.db"`, `db_path("/d", "/s") == "/s/state.db"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deletion_sync_config.py -v`
Expected: FAIL (unknown argument / missing attribute).

- [ ] **Step 3: Implement**
  - Fields `sync_deletions: bool` and `deletion_sync_threshold: int` on `_DefaultConfig`; defaults `False` / `-1`; add `sync_deletions` to `_USER_BOOL_FIELDS`.
  - Flags `--sync-deletions` (`store_true`, `default=None`) and `--deletion-sync-threshold` (`type=int`, `default=None`) in `add_options_for_user`, help text in the style of `--require-mount-marker`.
  - Validation in the `cli()` `elif` chain, after the existing per-entry checks, same `print` + `return 2` style.
  - `_has_shared_deletion_db`: resolve `manifest.db_path(...)` (with `expanduser` + `abspath`) for every entry that has a `directory`; collision is an error when either colliding entry has `sync_deletions`. Message tells the user to give each entry its own `state_directory`. Called from `run_with_configs` right after `_has_shared_state_directory`.
  - Warnings in `run_with_configs`, once per entry with `sync_deletions`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deletion_sync_config.py tests/test_config_defaults.py tests/test_config_file.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd tests/test_deletion_sync_config.py
git commit -m "feat(deletion-sync): config fields, CLI flags and startup validation"
```

---

### Task 2: Deletion state and the per-asset verdict

**Files:**
- Create: `src/icloudpd/deletion_sync.py`
- Test: `tests/test_deletion_sync_state.py`

**Interfaces:**
- Consumes: `manifest.ManifestHandle`, `manifest.get_all_for_asset`, `manifest.record_seen`
- Produces:

```python
class DeletionSyncError(Exception): ...          # any sqlite failure in this module, re-raised as this

class Verdict(Enum):
    PROCEED = "proceed"      # download as today
    SUSPECT = "suspect"      # fully missing, first scan: skip download
    CANDIDATE = "candidate"  # fully missing, confirmed: skip download, collected for finish_scan
    HELD = "held"            # held/approved item: skip download

class ItemStatus(str, Enum):
    HELD = "held"; APPROVED = "approved"; REJECTED = "rejected"; DELETED = "deleted"
    SKIPPED_GONE = "skipped_gone"; SKIPPED_REAPPEARED = "skipped_reappeared"; FAILED = "failed"

@dataclass(frozen=True)
class DeletionItem:
    record_name: str; filename: str; asset_date_utc: str
    status: ItemStatus; detected_utc: str; status_changed_utc: str

@dataclass
class DeletionScan:
    connection: sqlite3.Connection
    scan_seq: int
    last_completed_scan_seq: int
    dry_run: bool
    candidates: dict[str, PhotoAsset]   # record_name -> asset, new this scan
    seen: dict[str, PhotoAsset]         # held/approved items visited this scan

def ensure_schema(connection: sqlite3.Connection) -> None
def open_scan(logger: logging.Logger, handle: manifest.ManifestHandle, dry_run: bool) -> DeletionScan
def judge_asset(logger: logging.Logger, scan: DeletionScan, photo: PhotoAsset,
                planned: Sequence[tuple[str, int]]) -> Verdict   # (path, version size in bytes)
def path_variants(path: str, size_bytes: int) -> list[str]
def list_items(connection: sqlite3.Connection, statuses: Sequence[ItemStatus]) -> list[DeletionItem]
```

Schema (spec "State"), with one deliberate refinement: the debounce uses a scan counter instead of a timestamp, because "marked by an earlier *completed* scan" is a comparison of scan numbers.
- `downloaded_assets` + `missing_since_scan INTEGER NULL` (added via `ALTER TABLE` only when `PRAGMA table_info` lacks it).
- `deletion_items(record_name TEXT PRIMARY KEY, filename TEXT NOT NULL, asset_date_utc TEXT NOT NULL, detected_utc TEXT NOT NULL, status TEXT NOT NULL, status_changed_utc TEXT NOT NULL, record_change_tag TEXT NULL, via_approval INTEGER NOT NULL DEFAULT 0)`.
- `deletion_state(id INTEGER PRIMARY KEY CHECK (id = 1), scan_seq INTEGER NOT NULL DEFAULT 0, last_completed_scan_seq INTEGER NOT NULL DEFAULT 0, tripped INTEGER NOT NULL DEFAULT 0, tripped_utc TEXT NULL)`, one row inserted if absent.

`judge_asset` algorithm (writes skipped entirely when `scan.dry_run`; every write is committed immediately):

```
rows = manifest rows for photo.id
item = deletion_items row for photo.id, if any
present = [r for r in rows if os.path.isfile(r.local_path)]
matches = any(r.local_path in path_variants(p, s) for r in rows for (p, s) in planned)
fully_missing = rows and matches and not present

if item.status in (held, approved):
    if present: delete item row; clear missing_since_scan; return PROCEED   # reappeared locally
    refresh item.record_change_tag from photo; seen[id] = photo; return HELD
if item.status == rejected:
    if present: delete item row
    return PROCEED                                    # human said keep it: re-download
if not fully_missing:
    clear missing_since_scan on photo's rows; delete item row if status == failed; return PROCEED
m = missing_since_scan (same for all the asset's rows)
if m is not None and m <= scan.last_completed_scan_seq:
    candidates[id] = photo; return CANDIDATE
if m != scan.scan_seq: set missing_since_scan = scan.scan_seq on all the asset's rows
return SUSPECT
```

`path_variants(path, size)` returns `[path, add_suffix_to_filename("-original", path), f"-{size}.".join(path.rsplit(".", 1))]` (reuse the helpers `base.py` already uses for these two variants).

`open_scan`: `ensure_schema`, then (unless dry-run) increment `scan_seq` and commit; returns the new seq and the current `last_completed_scan_seq`. In dry-run it returns `scan_seq + 1` without writing.

- [ ] **Step 1: Write the failing tests** in `tests/test_deletion_sync_state.py`, using a real `manifest.open` on `tmp_path`, real files, and a minimal fake asset (an object with `id`, `filename`, `created`, `_asset_record={"recordName": ..., "recordChangeTag": ...}`; cast to `PhotoAsset`):
  - `test_present_asset_proceeds`
  - `test_partial_live_photo_proceeds`: two rows, one file deleted → `PROCEED`, `missing_since_scan` stays null.
  - `test_fully_missing_is_suspect_then_candidate`: scan 1 `SUSPECT`; mark scan 1 complete (set `last_completed_scan_seq`); scan 2 `CANDIDATE` and in `scan.candidates`.
  - `test_incomplete_scan_does_not_advance`: scan 1 `SUSPECT`, not completed; scan 2 `SUSPECT` and `missing_since_scan == 2`; scan 2 completed; scan 3 `CANDIDATE`.
  - `test_path_change_never_candidate`: rows at old paths, all missing, `planned` holds only new paths → `PROCEED` on every scan.
  - `test_suffix_variant_matches`: row recorded at `IMG_1-123.JPG`, planned `("IMG_1.JPG", 123)`, file deleted → becomes `CANDIDATE` on the second completed scan.
  - `test_reappeared_clears_mark`: suspect, file restored → `PROCEED`, mark null.
  - `test_held_item_skips_and_records_seen`: item row `held` → `HELD`, `scan.seen` has it, change tag refreshed.
  - `test_held_item_reappeared_locally_is_dropped`: held, file restored → `PROCEED`, item row gone.
  - `test_rejected_item_proceeds`: `rejected` row, files missing → `PROCEED`; files present → `PROCEED` and row gone.
  - `test_same_asset_twice_in_one_scan` (Review Focus 2): judged twice in scan 1 → both `SUSPECT`, mark `== 1`; scan 2 judged twice → `CANDIDATE` both, `len(scan.candidates) == 1`.
  - `test_dry_run_writes_nothing`: dump `state.db` (`connection.iterdump()`) before and after `open_scan(dry_run=True)` + judging a fully missing asset → identical.
  - `test_migrates_old_db` (Review Focus 3): create a db with only the old `downloaded_assets` schema and a row, `ensure_schema` → new column, tables and state row exist, old row intact; calling it twice is a no-op.
  - `test_sqlite_failure_raises`: close the connection, `judge_asset` raises `DeletionSyncError`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deletion_sync_state.py -v`
Expected: FAIL (`ModuleNotFoundError: icloudpd.deletion_sync`).

- [ ] **Step 3: Implement** the interfaces above in `src/icloudpd/deletion_sync.py`. Module docstring states why this module is not best-effort, unlike `manifest.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deletion_sync_state.py tests/test_manifest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/deletion_sync.py tests/test_deletion_sync_state.py
git commit -m "feat(deletion-sync): deletion state schema and per-asset verdict"
```

---

### Task 3: Wire detection into the download loop

**Files:**
- Modify: `src/icloudpd/base.py` (`download_builder`, `_process_all_users_once`, `core_single_run`)
- Test: `tests/test_deletion_sync_wiring.py`

**Interfaces:**
- Consumes: `deletion_sync.open_scan`, `deletion_sync.judge_asset`, `deletion_sync.DeletionScan`, `deletion_sync.DeletionSyncError`, `deletion_sync.Verdict`
- Produces: `download_builder(..., manifest_handle, deletion_scan: deletion_sync.DeletionScan | None, icloud, counter, photo) -> bool` (new parameter right after `manifest_handle`); the `downloader` type in `core_single_run` becomes `Callable[[ManifestHandle | None, DeletionScan | None, PyiCloudService, Counter, PhotoAsset], bool]`, and the no-directory fallback lambda takes five arguments.
- Produces: `base._planned_paths(photo, versions, filename_overrides, primary_sizes, force_size, download_dir, filename_builder, lp_filename_generator, skip_live_photos, live_photo_size, raw_policy) -> list[tuple[str, int]]` — the plain path and version size for every file `download_builder` would write, computed with the same calls the loop uses (`calculate_version_filename`, `local_download_path`, the live-photo suffix logic).
- Produces: in `core_single_run`, a `deletion_scan` local that Task 4's `finish_scan` call uses.

Behavior:
- With `sync_deletions` on: `core_single_run` requires a manifest (`manifest_handle is None` → log error, return `USER_SKIPPED`), calls `open_scan` once before the album loop, and passes the scan into every `download_photo` call. With it off, `deletion_scan` is `None` and nothing else changes.
- In `download_builder`, after `versions` and `download_dir` are known and before the size loop: if `deletion_scan` is set and not `only_print_filenames`, compute `_planned_paths` and `judge_asset`; for any verdict other than `PROCEED`, log at debug (`"%s held for deletion sync (%s)"`) and `return False` without touching the filesystem or generating XMP.
- `DeletionSyncError` anywhere in the run: caught in `core_single_run`, logged as an error, returns `USER_SKIPPED`.
- Mark the scan completed (`last_completed_scan_seq = scan_seq`, not in dry-run) only when enumeration of all albums finished without cancellation. Leave a clearly named hook for Task 4 to call `finish_scan` at that same point; for this task, completion is a small `deletion_sync.mark_completed(scan: DeletionScan) -> None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_deletion_sync_wiring.py`. Run the real pipeline against `vcr_cassettes/listing_photos.yml` by calling `cli.parse([...])` then `base.run_with_configs(...)` inside `vcr.use_cassette` (bypassing `cli()` validation is deliberate: the cassette only supports `--recent 5`; use the same flags `tests/test_mount_guard.py` uses, plus `--sync-deletions --require-mount-marker` and a `.mounted` marker):
  - `test_deleted_file_not_redownloaded_and_becomes_candidate`: run 1 downloads; delete `2018/07/31/IMG_7409.JPG`; run 2 → file still absent, `missing_since_scan` set; run 3 → still absent, `deletion_sync.list_items` is empty (no execution yet) and the scan's candidate was collected (assert via a patched `mark_completed` capturing `scan.candidates`).
  - `test_sync_off_redownloads`: same deletion without `--sync-deletions` → run 2 re-downloads the file (today's behavior).
  - `test_cancelled_scan_not_completed`: set `status_exchange.get_progress().cancel` during enumeration (patch the passer to set it) → `last_completed_scan_seq` unchanged.
  - `test_missing_marker_detects_nothing`: `.mounted` absent → run skipped, `open_scan` never called (patch it to fail the test if called).
  - `test_manifest_unavailable_skips_user`: patch `manifest.open` to return `None` with `--sync-deletions` → run returns non-zero, nothing downloaded.
  - `test_planned_paths_match_download`: for a fresh run with `--size original --size medium` and live photos (use `download_live_photos.yml` with its existing test's flags), every path in the manifest after run 1 is one of `path_variants` of some `_planned_paths` entry.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deletion_sync_wiring.py -v`
Expected: FAIL (file re-downloaded / unexpected keyword).

- [ ] **Step 3: Implement** the behavior above. Keep `_planned_paths` next to `download_builder`.

- [ ] **Step 4: Run tests to verify they pass, plus the existing download suites**

Run: `uv run pytest tests/test_deletion_sync_wiring.py tests/test_download_photos.py tests/test_download_live_photos.py tests/test_manifest_integration.py tests/test_mount_guard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/base.py src/icloudpd/deletion_sync.py tests/test_deletion_sync_wiring.py
git commit -m "feat(deletion-sync): detect deletions in the download loop"
```

---

### Task 4: Circuit breaker, execution, events

**Files:**
- Modify: `src/icloudpd/deletion_sync.py`, `src/icloudpd/base.py` (`core_single_run`: replace the Task 3 `mark_completed` hook)
- Test: `tests/test_deletion_sync_breaker.py`

**Interfaces:**
- Consumes: `DeletionScan`, `ItemStatus`, `list_items`, `notifications.build_event`, `notifications.notify`
- Produces:

```python
NotifyFn = Callable[[str, str, dict[str, Any]], bool]   # (event_type, message, data) -> delivered
DeleteFn = Callable[[PhotoAsset], bool]                   # True only on confirmed success

def finish_scan(logger: logging.Logger, scan: DeletionScan, *, threshold: int,
                delete: DeleteFn, notify: NotifyFn, now: datetime.datetime | None = None) -> None
def delete_asset(logger: logging.Logger, library_object: PhotoLibrary, photo: PhotoAsset) -> bool
```

`finish_scan` order (each item's status change committed as it happens):
1. Mark the scan completed.
2. **Approved items** (bypass the breaker): seen this scan → re-check every manifest path absent (else `skipped_reappeared`) → `delete` → `deleted` with `via_approval=1`, or `failed`. Not seen → `skipped_gone`.
3. **New candidates** (`scan.candidates` not already `held`): count = held + new + auto-deleted in last 7 days (`status='deleted' AND via_approval=0 AND status_changed_utc >= now-7d`). If `threshold > 0` and (`tripped` or count ≥ threshold): insert/update all as `held`, set `tripped`, and emit `deletion_sync_threshold_tripped` if any record name wasn't already held. Otherwise re-check absence, `delete`, mark `deleted` (`via_approval=0`) or `failed`.
4. On `deleted`: remove the asset's `downloaded_assets` rows.
5. Prune terminal rows older than 30 days.
6. Emit `deletion_sync_summary` if anything was deleted or failed this scan.
- Dry run: steps 2–3 log what would happen (`"[DRY RUN] Would delete %s"`, `"[DRY RUN] Would hold %d items (threshold %d)"`), write nothing, call neither `delete` nor `notify`.

Event `data` (Global Constraints apply): summary → `deleted_count`, `failed_count`, `items`, `total`; tripped → `held_count`, `new_count`, `threshold`, `items`, `total`. `items` entries are `{"record_name", "filename", "asset_date"}`. `core_single_run` builds `notify` from `notifications.build_event(event_type, username, message, data | {"library": user_config.library, "directory": directory})`.

`delete_asset`: same request body as `base.delete_photo` (`isDeleted: 1`, current `recordChangeTag`, `zoneID` = `library_object.zone_id`). Returns `True` only if the response is OK and no entry in `response.json()["records"]` has `serverErrorCode`; any exception → log warning, `False`.

- [ ] **Step 1: Write the failing tests** in `tests/test_deletion_sync_breaker.py` (fake assets as in Task 2; `delete` and `notify` are recording fakes; `now` injected):
  - `test_below_threshold_deletes_and_summarizes`: 2 candidates, threshold 5 → both `deleted`, manifest rows gone, one `deletion_sync_summary` with `deleted_count == 2`.
  - `test_unbounded_threshold_deletes`: threshold `-1`, 100 candidates → all deleted.
  - `test_reaching_threshold_holds_all`: 3 candidates, threshold 3 → zero `delete` calls, all `held`, `tripped`, one tripped event with `held_count == 3`.
  - `test_trip_persists_and_merges`: tripped batch; next scan 1 new + 3 already held → new one `held`, re-notify with `new_count == 1`; following scan with no new names → no event.
  - `test_slow_leak_trips`: threshold 5; scans with 2 candidates each, `now` advancing 1 day → 3rd scan trips (2+2 auto-deleted + 2 new ≥ 5).
  - `test_window_expires`: same, but 8 days between scans → no trip.
  - `test_approved_bypasses_breaker_and_not_counted`: 10 approved, threshold 3 → all deleted with `via_approval=1`; next scan 1 new candidate → deleted, not held.
  - `test_approved_not_seen_is_skipped_gone`, `test_reappeared_before_delete_is_skipped`.
  - `test_failed_delete_is_retried`: `delete` returns `False` → `failed`, manifest rows kept; next scan judges it `CANDIDATE` again and deletes.
  - `test_notify_failure_does_not_block` (Review Focus 4): `notify` returns `False` → deletions committed anyway.
  - `test_exception_mid_execution_keeps_progress` (Review Focus 5): `delete` raises on the 2nd of 3 → exception propagates; reopening the db shows item 1 `deleted`, items 2–3 not `deleted`.
  - `test_items_capped_at_50`: 60 deleted → `len(items) == 50`, `total == 60`.
  - `test_prunes_terminal_rows_after_30_days`.
  - `test_dry_run_no_writes_no_calls`: db dump identical, no `delete`/`notify` calls, log contains `[DRY RUN] Would hold`.
  - `test_delete_asset_checks_response`: fake `library_object.session.post` returning (a) 200 with clean records → `True`, (b) 200 with `serverErrorCode` → `False`, (c) raising → `False`; assert the posted JSON has `isDeleted` 1 and the photo's `recordChangeTag`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deletion_sync_breaker.py -v`
Expected: FAIL (`finish_scan` not defined).

- [ ] **Step 3: Implement** `finish_scan` and `delete_asset`; in `core_single_run` call `finish_scan(..., threshold=user_config.deletion_sync_threshold, delete=partial(deletion_sync.delete_asset, logger, library_object), notify=...)` at the completion point from Task 3, and drop `mark_completed` if nothing else uses it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deletion_sync_breaker.py tests/test_deletion_sync_state.py tests/test_deletion_sync_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/deletion_sync.py src/icloudpd/base.py tests/test_deletion_sync_breaker.py
git commit -m "feat(deletion-sync): circuit breaker, execution and notification events"
```

---

### Task 5: Resolver CLI

**Files:**
- Modify: `src/icloudpd/deletion_sync.py`, `src/icloudpd/config.py` (`GlobalConfig`), `src/icloudpd/cli.py` (`add_global_options`, `map_to_global_config`, `cli()`), `tests/test_config_defaults.py` (exclusion list)
- Test: `tests/test_deletion_sync_resolve.py`

**Interfaces:**
- Consumes: `manifest.db_path`, `ensure_schema`, `list_items`, `ItemStatus`
- Produces:

```python
@dataclass(frozen=True)
class DeletionCommand:
    action: Literal["approve", "reject", "list"]
    username: str
    library: str            # default "PrimarySync"

def resolve(connection: sqlite3.Connection, decision: Literal["approve", "reject"]) -> list[DeletionItem]
def run_command(command: DeletionCommand, user_configs: Sequence[UserConfig]) -> int
```

- `GlobalConfig.deletion_command: DeletionCommand | None` — CLI-only like `help`/`version`, so it is excluded from `GLOBAL_OPTION_DEFAULTS` and can't be set from YAML; extend the exclusion in `test_global_option_defaults_cover_every_configurable_global_field`.
- Flags (global): `--resolve-deletions {approve,reject}`, `--list-pending-deletions`, and the selector `--for-username U` / `--for-library L`. **Deviation from the spec's `--username`/`--library` wording, on purpose:** `--config` + `-u` is rejected today and `--library` with `--config` overrides every entry; dedicated selector flags work identically with or without a config file and leave `parse()` untouched. The spec leaves flag spelling to the builder.
- `cli()`: right after `--help`/`--version` handling, if `deletion_command` is set, return `deletion_sync.run_command(...)` before any other validation. `--resolve-deletions` and `--list-pending-deletions` together, or either without `--for-username`, → `2`.
- `run_command`: exactly one entry with matching `username` and `library` (and a `directory`), else print the matching problem and return `2`. If its `db_path` doesn't exist → print "No held deletion batch" and return `0` without creating anything. Otherwise `sqlite3.connect(path, timeout=10)`, `ensure_schema`, print the held batch (`count`, then `filename  asset_date` per line). `list` stops there. `approve`: `held → approved`, clear `tripped`, print "Approved N; they will be deleted at the end of the next sync". `reject`: `held → rejected`, clear `missing_since_scan` on their manifest rows, clear `tripped`, print "Rejected N; they will re-download on the next sync". No held items → message, `0`. `sqlite3.OperationalError` "database is locked" → print "state.db is busy (is icloudpd syncing?); try again" and return `1`.

- [ ] **Step 1: Write the failing tests** in `tests/test_deletion_sync_resolve.py` (seed a `state.db` via `manifest.open` + `ensure_schema` + direct inserts):
  - `test_list_prints_batch_and_changes_nothing`
  - `test_approve_marks_approved_and_clears_trip`
  - `test_reject_makes_asset_redownload`: after reject, items are `rejected`, `tripped` cleared, `missing_since_scan` null, and `judge_asset` returns `PROCEED` for the still-missing asset.
  - `test_no_db_creates_nothing`: path absent → exit `0`, no file created.
  - `test_selector_no_match` and `test_selector_ambiguous` → `2`.
  - `test_works_with_config_file`: YAML with two entries (personal + `SharedSync-X`), `--for-username a --for-library SharedSync-X --list-pending-deletions` → reads the second entry's db.
  - `test_flags_mutually_exclusive` → `2`.
  - `test_busy_db_fails_cleanly` (Review Focus 1): another connection holds `BEGIN IMMEDIATE`; patch the timeout to `0.1`; `approve` returns `1` with the "busy" message; db unchanged after releasing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deletion_sync_resolve.py -v`
Expected: FAIL

- [ ] **Step 3: Implement** the interfaces and the `REJECTED` handling above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deletion_sync_resolve.py tests/test_deletion_sync_state.py tests/test_config_defaults.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd tests/test_deletion_sync_resolve.py tests/test_deletion_sync_state.py tests/test_config_defaults.py
git commit -m "feat(deletion-sync): --resolve-deletions and --list-pending-deletions"
```

---

### Task 6: Documentation and Shared Library live-test checklist

**Files:**
- Modify: `README.md` (new "Deletion sync" section after "Library on a network mount")
- Create: `docs/deletion-sync-live-test.md`

- [ ] **Step 1: Write the README section.** Covers, in this order: what it does and that it's off by default; the YAML example (`sync_deletions: true`, `deletion_sync_threshold: 50`, `require_mount_marker: true`, `state_directory`); **Immich only deletes the file when its trash is emptied, and only on a read-write mount — on `:ro` nothing syncs**; the two-scan delay; the threshold (`-1` no cap, cumulative over 7 days, held batches never re-download until resolved); `--list-pending-deletions` / `--resolve-deletions` with `--for-username` / `--for-library`; one entry per library (Shared Library = its own entry with its own `state_directory`, find the name with `--list-libraries`); Shared Library deletes go to Recently Deleted for every participant; separate copies in another library aren't deleted; the two events and their `data` fields; incompatible options (`--recent`, `--until-found`).

- [ ] **Step 2: Write `docs/deletion-sync-live-test.md`**: manual steps to confirm a delete in a `SharedSync` zone lands in Recently Deleted — add a throwaway photo to the Shared Library, configure a Shared Library entry with `--sync-deletions --deletion-sync-threshold 1`, sync twice after deleting the local file, `--resolve-deletions approve`, sync once more, check Recently Deleted on iCloud.com, record result and date in the file.

- [ ] **Step 3: Verify**

Run: `uv run pytest -q && uv run mypy src tests --strict --python-version 3.10 && uv run ruff check && uv run ruff format --check`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/deletion-sync-live-test.md
git commit -m "docs(deletion-sync): README section and Shared Library live-test checklist"
```
