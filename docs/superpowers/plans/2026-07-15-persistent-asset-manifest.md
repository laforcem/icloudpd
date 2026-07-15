# Persistent Asset Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give icloudpd a persistent SQLite manifest recording which iCloud assets have been downloaded to which local paths, as infrastructure for a later deletion-sync feature (and other future consumers), without changing any existing download behavior.

**Architecture:** A new standalone module `src/icloudpd/manifest.py` wraps a SQLite database at `<download_dir>/.icloudpd/state.db`, keyed by `(record_name, local_path)` since one iCloud asset can produce multiple local files (Live Photo video, multiple `--size` values, RAW+JPEG pairs). `base.py`'s existing download loop calls a single upsert function, `record_seen`, at every point where it already knows a file exists locally (both "just downloaded" and "already existed") — this makes backfill for pre-existing libraries an emergent property of normal operation, not a separate pass. All manifest operations are best-effort: failures are logged and swallowed, never propagated into the download loop.

**Tech Stack:** Python 3.10+ stdlib `sqlite3` (no new dependency), pytest + `unittest.TestCase` (matching existing test style), mypy `--strict`, ruff.

**Spec:** `docs/superpowers/specs/2026-07-15-persistent-asset-manifest-design.md`

---

## Task 1: Manifest module — schema, open, close

**Files:**
- Create: `src/icloudpd/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manifest.py
import os
import sqlite3
from unittest import TestCase

import pytest

from icloudpd import manifest
from tests.helpers import create_logger_for_test  # will fail until Step 2 note below


class OpenManifestTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, tmp_path) -> None:
        self.tmp_path = tmp_path
        self.logger = __import__("logging").getLogger("test_manifest")

    def test_open_creates_db_file_under_dot_icloudpd(self) -> None:
        download_dir = str(self.tmp_path)
        handle = manifest.open(self.logger, download_dir)
        self.assertIsNotNone(handle)
        db_path = os.path.join(download_dir, ".icloudpd", "state.db")
        self.assertTrue(os.path.isfile(db_path))
        manifest.close(handle)  # type: ignore[arg-type]

    def test_open_creates_downloaded_assets_table(self) -> None:
        download_dir = str(self.tmp_path)
        handle = manifest.open(self.logger, download_dir)
        assert handle is not None
        cursor = handle.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='downloaded_assets'"
        )
        self.assertEqual(cursor.fetchone()[0], "downloaded_assets")
        manifest.close(handle)

    def test_open_is_idempotent_across_processes(self) -> None:
        download_dir = str(self.tmp_path)
        handle1 = manifest.open(self.logger, download_dir)
        assert handle1 is not None
        manifest.close(handle1)
        # Re-opening an existing db must not fail or wipe data
        handle2 = manifest.open(self.logger, download_dir)
        assert handle2 is not None
        manifest.close(handle2)

    def test_open_returns_none_and_logs_on_unwritable_directory(self) -> None:
        # A file where a directory is expected forces os.makedirs to fail
        blocker_path = os.path.join(str(self.tmp_path), "blocked")
        with open(blocker_path, "w") as f:
            f.write("not a directory")
        download_dir = blocker_path
        handle = manifest.open(self.logger, download_dir)
        self.assertIsNone(handle)
```

Drop the bad `create_logger_for_test` import — it doesn't exist. Use the plain `logging.getLogger` shown in `inject_fixtures` instead:

```python
# tests/test_manifest.py (corrected imports)
import logging
import os
from unittest import TestCase

import pytest

from icloudpd import manifest


class OpenManifestTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, tmp_path) -> None:
        self.tmp_path = tmp_path
        self.logger = logging.getLogger("test_manifest")

    def test_open_creates_db_file_under_dot_icloudpd(self) -> None:
        download_dir = str(self.tmp_path)
        handle = manifest.open(self.logger, download_dir)
        self.assertIsNotNone(handle)
        db_path = os.path.join(download_dir, ".icloudpd", "state.db")
        self.assertTrue(os.path.isfile(db_path))
        assert handle is not None
        manifest.close(handle)

    def test_open_creates_downloaded_assets_table(self) -> None:
        download_dir = str(self.tmp_path)
        handle = manifest.open(self.logger, download_dir)
        assert handle is not None
        cursor = handle.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='downloaded_assets'"
        )
        self.assertEqual(cursor.fetchone()[0], "downloaded_assets")
        manifest.close(handle)

    def test_open_is_idempotent_across_processes(self) -> None:
        download_dir = str(self.tmp_path)
        handle1 = manifest.open(self.logger, download_dir)
        assert handle1 is not None
        manifest.close(handle1)
        handle2 = manifest.open(self.logger, download_dir)
        assert handle2 is not None
        manifest.close(handle2)

    def test_open_returns_none_and_logs_on_unwritable_directory(self) -> None:
        blocker_path = os.path.join(str(self.tmp_path), "blocked")
        with open(blocker_path, "w") as f:
            f.write("not a directory")
        handle = manifest.open(self.logger, blocker_path)
        self.assertIsNone(handle)
```

This is the version to save to `tests/test_manifest.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'icloudpd.manifest'` (or `ImportError`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/icloudpd/manifest.py
"""Persistent record of which iCloud assets have been downloaded to which local paths.

One manifest database lives per download directory, at
<download_dir>/.icloudpd/state.db. All operations here are best-effort:
failures are logged and swallowed rather than raised, because this module
is infrastructure for other features and its absence must never break
the core download loop.
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Iterator, Sequence

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloaded_assets (
    record_name           TEXT NOT NULL,
    local_path             TEXT NOT NULL,
    size_bytes              INTEGER NOT NULL,
    checksum                TEXT NULL,
    first_downloaded_utc   TEXT NOT NULL,
    last_seen_utc          TEXT NOT NULL,
    PRIMARY KEY (record_name, local_path)
);
"""


@dataclass(frozen=True)
class ManifestRow:
    record_name: str
    local_path: str
    size_bytes: int
    checksum: str | None
    first_downloaded_utc: str
    last_seen_utc: str


@dataclass
class ManifestHandle:
    connection: sqlite3.Connection


def open(logger: logging.Logger, download_dir: str) -> ManifestHandle | None:
    """Open (creating if needed) the manifest database for a download directory.

    Returns None if the database could not be opened or created, in which
    case callers should proceed without manifest tracking rather than fail.
    """
    manifest_dir = os.path.join(download_dir, ".icloudpd")
    try:
        os.makedirs(manifest_dir, exist_ok=True)
        db_path = os.path.join(manifest_dir, "state.db")
        connection = sqlite3.connect(db_path)
        connection.execute(_SCHEMA)
        connection.commit()
        return ManifestHandle(connection=connection)
    except OSError as ex:
        logger.warning("Could not open asset manifest in %s: %s", download_dir, ex)
        return None
    except sqlite3.Error as ex:
        logger.warning("Could not open asset manifest in %s: %s", download_dir, ex)
        return None


def close(handle: ManifestHandle) -> None:
    handle.connection.close()


def _now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/manifest.py tests/test_manifest.py
git commit -m "feat: add manifest module with schema and open/close"
```

---

## Task 2: `record_seen` upsert

**Files:**
- Modify: `src/icloudpd/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_manifest.py`:

```python
class RecordSeenTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, tmp_path) -> None:
        self.tmp_path = tmp_path
        self.logger = logging.getLogger("test_manifest")
        handle = manifest.open(self.logger, str(self.tmp_path))
        assert handle is not None
        self.handle = handle

    def test_record_seen_inserts_new_row(self) -> None:
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
        rows = manifest.get_all_for_asset(self.handle, "REC1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].record_name, "REC1")
        self.assertEqual(rows[0].local_path, "/data/IMG_1.JPG")
        self.assertEqual(rows[0].size_bytes, 12345)
        self.assertIsNone(rows[0].checksum)
        self.assertEqual(rows[0].first_downloaded_utc, rows[0].last_seen_utc)

    def test_record_seen_on_existing_row_updates_last_seen_only(self) -> None:
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
        first_seen = manifest.get_all_for_asset(self.handle, "REC1")[0].first_downloaded_utc

        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
        rows = manifest.get_all_for_asset(self.handle, "REC1")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].first_downloaded_utc, first_seen)

    def test_record_seen_different_local_path_same_record_name_adds_second_row(self) -> None:
        # e.g. a still photo and its Live Photo video component
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1_HEVC.MOV", 99999)

        rows = manifest.get_all_for_asset(self.handle, "REC1")
        self.assertEqual(len(rows), 2)
        paths = {row.local_path for row in rows}
        self.assertEqual(paths, {"/data/IMG_1.JPG", "/data/IMG_1_HEVC.MOV"})

    def test_record_seen_swallows_sqlite_errors(self) -> None:
        manifest.close(self.handle)  # closed connection -> sqlite3.ProgrammingError on use
        # Must not raise
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/IMG_1.JPG", 12345)
```

Note: `get_all_for_asset` doesn't exist yet either — it's needed to assert on `record_seen`, so it's implemented in this same task alongside `record_seen` (a test for behavior needs a way to observe it).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_manifest.py::RecordSeenTestCase -v`
Expected: FAIL with `AttributeError: module 'icloudpd.manifest' has no attribute 'record_seen'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/icloudpd/manifest.py`:

```python
def record_seen(
    logger: logging.Logger,
    handle: ManifestHandle,
    record_name: str,
    local_path: str,
    size_bytes: int,
) -> None:
    """Record that a file for this asset exists locally right now.

    Upserts on (record_name, local_path): inserts a fresh row on first
    sight, or refreshes last_seen_utc (and size_bytes) if the row already
    exists. Never raises - failures are logged and swallowed.
    """
    now = _now_utc_iso()
    try:
        handle.connection.execute(
            """
            INSERT INTO downloaded_assets
                (record_name, local_path, size_bytes, checksum,
                 first_downloaded_utc, last_seen_utc)
            VALUES (?, ?, ?, NULL, ?, ?)
            ON CONFLICT (record_name, local_path) DO UPDATE SET
                size_bytes = excluded.size_bytes,
                last_seen_utc = excluded.last_seen_utc
            """,
            (record_name, local_path, size_bytes, now, now),
        )
        handle.connection.commit()
    except sqlite3.Error as ex:
        logger.warning(
            "Could not record manifest entry for %s (%s): %s", record_name, local_path, ex
        )


def get_all_for_asset(handle: ManifestHandle, record_name: str) -> Sequence[ManifestRow]:
    cursor = handle.connection.execute(
        """
        SELECT record_name, local_path, size_bytes, checksum,
               first_downloaded_utc, last_seen_utc
        FROM downloaded_assets
        WHERE record_name = ?
        """,
        (record_name,),
    )
    return [ManifestRow(*row) for row in cursor.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/manifest.py tests/test_manifest.py
git commit -m "feat: add record_seen upsert and get_all_for_asset lookup"
```

---

## Task 3: `all_records` and `prune`

**Files:**
- Modify: `src/icloudpd/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_manifest.py`:

```python
class AllRecordsAndPruneTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, tmp_path) -> None:
        self.tmp_path = tmp_path
        self.logger = logging.getLogger("test_manifest")
        handle = manifest.open(self.logger, str(self.tmp_path))
        assert handle is not None
        self.handle = handle

    def test_all_records_returns_every_row(self) -> None:
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/a.jpg", 1)
        manifest.record_seen(self.logger, self.handle, "REC2", "/data/b.jpg", 2)

        rows = list(manifest.all_records(self.handle))
        self.assertEqual(len(rows), 2)
        record_names = {row.record_name for row in rows}
        self.assertEqual(record_names, {"REC1", "REC2"})

    def test_all_records_on_empty_manifest_returns_empty(self) -> None:
        rows = list(manifest.all_records(self.handle))
        self.assertEqual(rows, [])

    def test_prune_removes_only_matching_row(self) -> None:
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/a.jpg", 1)
        manifest.record_seen(self.logger, self.handle, "REC1", "/data/a_HEVC.MOV", 2)

        manifest.prune(self.logger, self.handle, "REC1", "/data/a.jpg")

        rows = manifest.get_all_for_asset(self.handle, "REC1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].local_path, "/data/a_HEVC.MOV")

    def test_prune_nonexistent_row_is_a_no_op(self) -> None:
        manifest.prune(self.logger, self.handle, "NOPE", "/data/nope.jpg")
        # Must not raise
        self.assertEqual(list(manifest.all_records(self.handle)), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_manifest.py::AllRecordsAndPruneTestCase -v`
Expected: FAIL with `AttributeError: module 'icloudpd.manifest' has no attribute 'all_records'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/icloudpd/manifest.py`:

```python
def all_records(handle: ManifestHandle) -> Iterator[ManifestRow]:
    cursor = handle.connection.execute(
        """
        SELECT record_name, local_path, size_bytes, checksum,
               first_downloaded_utc, last_seen_utc
        FROM downloaded_assets
        """
    )
    for row in cursor:
        yield ManifestRow(*row)


def prune(logger: logging.Logger, handle: ManifestHandle, record_name: str, local_path: str) -> None:
    try:
        handle.connection.execute(
            "DELETE FROM downloaded_assets WHERE record_name = ? AND local_path = ?",
            (record_name, local_path),
        )
        handle.connection.commit()
    except sqlite3.Error as ex:
        logger.warning(
            "Could not prune manifest entry for %s (%s): %s", record_name, local_path, ex
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/icloudpd/manifest.py tests/test_manifest.py
git commit -m "feat: add all_records and prune to manifest module"
```

---

## Task 4: Type-check and lint the manifest module in isolation

**Files:**
- No changes expected; this task is a checkpoint before wiring into `base.py`.

- [ ] **Step 1: Run mypy on the new module**

Run: `python3 -m mypy src/icloudpd/manifest.py tests/test_manifest.py --strict --python-version 3.10`
Expected: `Success: no issues found`

If there are errors, fix them in `src/icloudpd/manifest.py` (common ones at this point: missing `-> None` on `close`, or `Sequence`/`Iterator` needing the `from typing import` already present in Task 1's Step 3 — both already handled by the code above, so this should pass clean).

- [ ] **Step 2: Run ruff**

Run: `ruff check src/icloudpd/manifest.py tests/test_manifest.py --ignore "E402"`
Expected: no output (clean)

Run: `ruff format --check src/icloudpd/manifest.py tests/test_manifest.py`
Expected: no output (already formatted); if not, run `ruff format src/icloudpd/manifest.py tests/test_manifest.py` and re-check.

- [ ] **Step 3: Commit if formatting changed anything**

```bash
git add src/icloudpd/manifest.py tests/test_manifest.py
git diff --cached --quiet || git commit -m "style: ruff format manifest module"
```

---

## Task 5: Open/close the manifest per user config in `base.py`

**Files:**
- Modify: `src/icloudpd/base.py:43` (imports)
- Modify: `src/icloudpd/base.py:399-448` (`_process_all_users_once`, downloader partial + core_single_run call)
- Modify: `src/icloudpd/base.py:564-583` (`download_builder` signature)

This task only threads the handle through; it does not yet call `record_seen` anywhere (that's Tasks 6-7). After this task, all existing tests must still pass unchanged — the manifest is opened and closed but never written to yet.

- [ ] **Step 1: Add the import**

In `src/icloudpd/base.py`, find:

```python
from icloudpd.autodelete import autodelete_photos
```

Change to:

```python
from icloudpd import manifest
from icloudpd.autodelete import autodelete_photos
```

- [ ] **Step 2: Add `manifest_handle` parameter to `download_builder`**

Find (around line 564-583):

```python
def download_builder(
    logger: logging.Logger,
    folder_structure: str,
    directory: str,
    primary_sizes: Sequence[AssetVersionSize],
    force_size: bool,
    only_print_filenames: bool,
    set_exif_datetime: bool,
    skip_live_photos: bool,
    live_photo_size: LivePhotoVersionSize,
    dry_run: bool,
    file_match_policy: FileMatchPolicy,
    xmp_sidecar: bool,
    lp_filename_generator: Callable[[str], str],
    filename_builder: Callable[[PhotoAsset], str],
    raw_policy: RawTreatmentPolicy,
    icloud: PyiCloudService,
    counter: Counter,
    photo: PhotoAsset,
) -> bool:
```

Replace with:

```python
def download_builder(
    logger: logging.Logger,
    folder_structure: str,
    directory: str,
    primary_sizes: Sequence[AssetVersionSize],
    force_size: bool,
    only_print_filenames: bool,
    set_exif_datetime: bool,
    skip_live_photos: bool,
    live_photo_size: LivePhotoVersionSize,
    dry_run: bool,
    file_match_policy: FileMatchPolicy,
    xmp_sidecar: bool,
    lp_filename_generator: Callable[[str], str],
    filename_builder: Callable[[PhotoAsset], str],
    raw_policy: RawTreatmentPolicy,
    manifest_handle: manifest.ManifestHandle | None,
    icloud: PyiCloudService,
    counter: Counter,
    photo: PhotoAsset,
) -> bool:
```

- [ ] **Step 3 (revised during implementation): open the manifest inside `core_single_run`, not eagerly in `_process_all_users_once`**

The original plan called `manifest.open()` unconditionally in `_process_all_users_once`, before `core_single_run` (and therefore before authentication) even runs, and baked `manifest_handle` into the `downloader` partial at construction time. That broke two pre-existing tests: `test_cli.py::test_missing_directory` (asserts no directory gets created when auth fails) and `test_issue_1220_only_print_filenames_dedup_bug.py` (asserts `--only-print-filenames` never writes to the download directory) — because `manifest.open()` unconditionally does `os.makedirs` + `sqlite3.connect` + schema creation as soon as it's called, regardless of whether auth will succeed or whether the run is print-only.

The fix: leave `_process_all_users_once`'s `downloader` partial construction unchanged (do NOT add `manifest_handle` there — revert to the original code with no manifest involvement at all). Instead:

In `download_builder`'s signature, `manifest_handle: manifest.ManifestHandle | None,` still goes right after `raw_policy: RawTreatmentPolicy,` and before `icloud: PyiCloudService,` (unchanged from the original Step 2).

In `core_single_run`, find:

```python
                    directory = os.path.normpath(user_config.directory)

                    if user_config.skip_photos or user_config.skip_videos:
```

Replace with:

```python
                    directory = os.path.normpath(user_config.directory)

                    manifest_handle = (
                        manifest.open(logger, directory)
                        if not global_config.only_print_filenames
                        else None
                    )

                    try:
                        if user_config.skip_photos or user_config.skip_videos:
```

Then indent the entire rest of that `else:` branch (everything from the `if user_config.skip_photos` block down through the closing `if user_config.auto_delete: ... else: pass` block, i.e. up to but not including the `except PyiCloudFailedLoginException` line) one level deeper to sit inside the new `try:`, and close it with:

```python
                    finally:
                        if manifest_handle is not None:
                            manifest.close(manifest_handle)
        except PyiCloudFailedLoginException as error:
```

This mirrors the existing pattern already used for `icloud` in this same function — `icloud` is only known after authentication succeeds, so it's bound into `download_photo` at call time (`download_photo = partial(downloader, icloud)`), not baked into `downloader` at construction time before auth. `manifest_handle` follows the identical pattern:

Find:

```python
                            download_photo = partial(downloader, icloud)
```

Replace with:

```python
                            download_photo = partial(downloader, manifest_handle, icloud)
```

`core_single_run`'s `downloader` parameter type annotation must also change from `Callable[[PyiCloudService, Counter, PhotoAsset], bool]` to `Callable[[manifest.ManifestHandle | None, PyiCloudService, Counter, PhotoAsset], bool]`, and the `(lambda _s, _c, _p: False)` fallback (used when `user_config.directory is None`) in `_process_all_users_once` must become `(lambda _m, _s, _c, _p: False)` to match the new arity.

Gating `manifest.open()` on `not global_config.only_print_filenames` means `manifest_handle` is `None` in that mode — which also means Tasks 6-7's `if manifest_handle is not None: manifest.record_seen(...)` guards automatically skip all manifest writes under `--only-print-filenames`, with no separate guard needed there.

- [ ] **Step 4: Run the full existing test suite to confirm no regression**

Run: `.venv/bin/python -m pytest --numprocesses auto`
Expected: same 8 known-environmental failures as the pre-existing baseline (locale/timezone, unrelated to this change), all other tests PASS — including `test_missing_directory` and `test_issue_1220_only_print_filenames_dedup_bug` specifically, since those are what this revised approach fixes.

Also check for direct callers of `download_builder`:

Run: `grep -rn "download_builder" tests/ src/`

If any test constructs a `download_builder` call directly (not through the `downloader` partial built in `base.py`), add `None` as the `manifest_handle` argument at the correct position in that call. (As implemented, none exist.)

- [ ] **Step 5: Run mypy and ruff on the changed file**

Run: `.venv/bin/python -m mypy src/icloudpd/base.py --strict --python-version 3.10`
Run: `.venv/bin/python -m ruff check src/icloudpd/base.py --ignore "E402"`
Run: `.venv/bin/python -m ruff format --check src/icloudpd/base.py`

- [ ] **Step 6: Commit**

```bash
git add src/icloudpd/base.py
git commit -m "feat: thread manifest handle through download_builder (no writes yet)"
```

---

## Task 6: Record primary-download hits (already-exists and freshly-downloaded)

**Files:**
- Modify: `src/icloudpd/base.py` (inside `download_builder`'s primary-size download loop)

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_manifest_integration.py`:

```python
"""Integration tests: downloads produce manifest rows."""

import inspect
import os
import sqlite3
from unittest import TestCase

import pytest

from tests.helpers import path_from_project_root, run_icloudpd_test


class ManifestIntegrationTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self) -> None:
        self.root_path = path_from_project_root(__file__)
        self.fixtures_path = os.path.join(self.root_path, "fixtures")

    def _manifest_rows(self, data_dir: str) -> list[tuple[str, str, int]]:
        db_path = os.path.join(data_dir, ".icloudpd", "state.db")
        self.assertTrue(os.path.isfile(db_path), f"expected manifest db at {db_path}")
        connection = sqlite3.connect(db_path)
        try:
            cursor = connection.execute(
                "SELECT record_name, local_path, size_bytes FROM downloaded_assets"
            )
            return cursor.fetchall()
        finally:
            connection.close()

    def test_newly_downloaded_photo_gets_manifest_row(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])

        files_to_create = [
            ("2018/07/30", "IMG_7408.JPG", 1151066),
            ("2018/07/30", "IMG_7407.JPG", 656257),
        ]
        files_to_download = [("2018/07/31", "IMG_7409.JPG")]

        data_dir, _result = run_icloudpd_test(
            self.assertEqual,
            self.root_path,
            base_dir,
            "listing_photos.yml",
            files_to_create,
            files_to_download,
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "5",
                "--skip-videos",
                "--skip-live-photos",
                "--no-progress-bar",
                "--threads-num",
                "1",
            ],
        )

        rows = self._manifest_rows(data_dir)
        recorded_paths = {os.path.relpath(path, data_dir) for _rec, path, _size in rows}
        self.assertIn(os.path.normpath("2018/07/31/IMG_7409.JPG"), recorded_paths)
        # Pre-existing files matched via isfile() must also be recorded
        self.assertIn(os.path.normpath("2018/07/30/IMG_7408.JPG"), recorded_paths)
        self.assertIn(os.path.normpath("2018/07/30/IMG_7407.JPG"), recorded_paths)
```

This reuses the same fixtures and cassette (`listing_photos.yml`) as `tests/test_download_photos.py::test_download_and_skip_existing_photos`, so no new fixture/cassette files are needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_manifest_integration.py -v`
Expected: FAIL — the assertion on `2018/07/31/IMG_7409.JPG` (freshly downloaded) not being in `recorded_paths`, since `record_seen` isn't called yet.

- [ ] **Step 3: Write minimal implementation**

In `src/icloudpd/base.py`, inside `download_builder` (unaffected by Task 5's `core_single_run` reindentation — its own indentation is unchanged), find:

```python
        if file_exists:
            if file_match_policy == FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX:
                # for later: this crashes if download-size medium is specified
                file_size = os.stat(original_download_path or download_path).st_size
                photo_size = version.size
                if file_size != photo_size:
                    download_path = (f"-{photo_size}.").join(download_path.rsplit(".", 1))
                    logger.debug("%s deduplicated", truncate_middle(download_path, 96))
                    file_exists = os.path.isfile(download_path)
            if file_exists:
                counter.increment()
                logger.debug("%s already exists", truncate_middle(download_path, 96))
```

Replace with:

```python
        if file_exists:
            if file_match_policy == FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX:
                # for later: this crashes if download-size medium is specified
                file_size = os.stat(original_download_path or download_path).st_size
                photo_size = version.size
                if file_size != photo_size:
                    download_path = (f"-{photo_size}.").join(download_path.rsplit(".", 1))
                    logger.debug("%s deduplicated", truncate_middle(download_path, 96))
                    file_exists = os.path.isfile(download_path)
            if file_exists:
                counter.increment()
                logger.debug("%s already exists", truncate_middle(download_path, 96))
                if manifest_handle is not None:
                    manifest.record_seen(
                        logger, manifest_handle, photo.id, download_path, version.size
                    )
```

Then find:

```python
                if download_result:
                    from foundation.core import compose
                    from foundation.string_utils import endswith, lower

                    is_jpeg = compose(endswith((".jpg", ".jpeg")), lower)

                    if (
                        not dry_run
                        and set_exif_datetime
                        and is_jpeg(filename)
                        and not exif_datetime.get_photo_exif(logger, download_path)
                    ):
                        # %Y:%m:%d looks wrong, but it's the correct format
                        date_str = created_date.strftime("%Y-%m-%d %H:%M:%S%z")
                        logger.debug("Setting EXIF timestamp for %s: %s", download_path, date_str)
                        exif_datetime.set_photo_exif(
                            logger,
                            download_path,
                            created_date.strftime("%Y:%m:%d %H:%M:%S"),
                        )
                    if not dry_run:
                        download.set_utime(download_path, created_date)
                    logger.info("Downloaded %s", truncated_path)
```

Replace with:

```python
                if download_result:
                    from foundation.core import compose
                    from foundation.string_utils import endswith, lower

                    is_jpeg = compose(endswith((".jpg", ".jpeg")), lower)

                    if (
                        not dry_run
                        and set_exif_datetime
                        and is_jpeg(filename)
                        and not exif_datetime.get_photo_exif(logger, download_path)
                    ):
                        # %Y:%m:%d looks wrong, but it's the correct format
                        date_str = created_date.strftime("%Y-%m-%d %H:%M:%S%z")
                        logger.debug("Setting EXIF timestamp for %s: %s", download_path, date_str)
                        exif_datetime.set_photo_exif(
                            logger,
                            download_path,
                            created_date.strftime("%Y:%m:%d %H:%M:%S"),
                        )
                    if not dry_run:
                        download.set_utime(download_path, created_date)
                        if manifest_handle is not None:
                            manifest.record_seen(
                                logger, manifest_handle, photo.id, download_path, version.size
                            )
                    logger.info("Downloaded %s", truncated_path)
```

Note the `not dry_run` guard on the freshly-downloaded case: a dry run never actually writes the file, so recording it would misrepresent real filesystem state (see spec's Write path section). The already-exists case has no such guard because the file genuinely exists on disk regardless of `dry_run`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_manifest_integration.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing test suite**

Run: `python3 -m pytest --numprocesses auto`
Expected: all tests PASS, including all pre-existing `test_download_*.py` tests unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/icloudpd/base.py tests/test_manifest_integration.py
git commit -m "feat: record manifest rows for primary downloads and existing files"
```

---

## Task 7: Record Live Photo companion hits

**Files:**
- Modify: `src/icloudpd/base.py` (inside `download_builder`'s Live Photo download branch)
- Test: `tests/test_manifest_integration.py`

- [ ] **Step 1: Write the failing integration test**

Add to `tests/test_manifest_integration.py`:

```python
    def test_live_photo_video_component_gets_its_own_manifest_row(self) -> None:
        base_dir = os.path.join(self.fixtures_path, inspect.stack()[0][3])

        files_to_create: list = []
        files_to_download = [
            ("2020/09/28", "IMG_3148.HEIC"),
            ("2020/09/28", "IMG_3148_HEVC.MOV"),
        ]

        data_dir, _result = run_icloudpd_test(
            self.assertEqual,
            self.root_path,
            base_dir,
            "download_live_photos.yml",
            files_to_create,
            files_to_download,
            [
                "--username",
                "jdoe@gmail.com",
                "--password",
                "password1",
                "--recent",
                "1",
                "--no-progress-bar",
                "--threads-num",
                "1",
            ],
        )

        rows = self._manifest_rows(data_dir)
        by_record: dict[str, set[str]] = {}
        for record_name, path, _size in rows:
            by_record.setdefault(record_name, set()).add(os.path.relpath(path, data_dir))

        # Both the still image and its Live Photo video share one recordName
        # but must appear as two distinct manifest rows.
        matching = [paths for paths in by_record.values() if len(paths) >= 2]
        self.assertTrue(
            matching, f"expected one recordName with 2+ local paths, got: {by_record}"
        )
```

This reuses the `download_live_photos.yml` cassette already used by `tests/test_download_live_photos.py` — check its exact `files_to_download` values and CLI args there first:

Run: `sed -n '1,60p' tests/test_download_live_photos.py`

Adjust `files_to_download` and the CLI args above to match exactly what that existing test uses for the same cassette, since the cassette's recorded HTTP responses are fixed and must match the request the test makes.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_manifest_integration.py::ManifestIntegrationTestCase::test_live_photo_video_component_gets_its_own_manifest_row -v`
Expected: FAIL — no `recordName` has 2+ recorded paths, since the Live Photo branch doesn't call `record_seen` yet.

- [ ] **Step 3: Write minimal implementation**

In `src/icloudpd/base.py`, inside `download_builder`'s Live Photo branch, find:

```python
            else:
                if lp_file_exists:
                    if file_match_policy == FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX:
                        lp_file_size = os.stat(lp_download_path).st_size
                        lp_photo_size = version.size
                        if lp_file_size != lp_photo_size:
                            lp_download_path = (f"-{lp_photo_size}.").join(
                                lp_download_path.rsplit(".", 1)
                            )
                            logger.debug("%s deduplicated", truncate_middle(lp_download_path, 96))
                            lp_file_exists = os.path.isfile(lp_download_path)
                    if lp_file_exists:
                        logger.debug("%s already exists", truncate_middle(lp_download_path, 96))
                if not lp_file_exists:
```

Replace with:

```python
            else:
                if lp_file_exists:
                    if file_match_policy == FileMatchPolicy.NAME_SIZE_DEDUP_WITH_SUFFIX:
                        lp_file_size = os.stat(lp_download_path).st_size
                        lp_photo_size = version.size
                        if lp_file_size != lp_photo_size:
                            lp_download_path = (f"-{lp_photo_size}.").join(
                                lp_download_path.rsplit(".", 1)
                            )
                            logger.debug("%s deduplicated", truncate_middle(lp_download_path, 96))
                            lp_file_exists = os.path.isfile(lp_download_path)
                    if lp_file_exists:
                        logger.debug("%s already exists", truncate_middle(lp_download_path, 96))
                        if manifest_handle is not None:
                            manifest.record_seen(
                                logger, manifest_handle, photo.id, lp_download_path, version.size
                            )
                if not lp_file_exists:
```

Then find:

```python
                    truncated_path = truncate_middle(lp_download_path, 96)
                    logger.debug("Downloading %s...", truncated_path)
                    download_result = download.download_media(
                        logger,
                        dry_run,
                        icloud,
                        photo,
                        lp_download_path,
                        version,
                        lp_size,
                        filename_builder,
                    )
                    success = download_result and success
                    if download_result:
                        logger.info("Downloaded %s", truncated_path)
    return success
```

Replace with:

```python
                    truncated_path = truncate_middle(lp_download_path, 96)
                    logger.debug("Downloading %s...", truncated_path)
                    download_result = download.download_media(
                        logger,
                        dry_run,
                        icloud,
                        photo,
                        lp_download_path,
                        version,
                        lp_size,
                        filename_builder,
                    )
                    success = download_result and success
                    if download_result:
                        if not dry_run and manifest_handle is not None:
                            manifest.record_seen(
                                logger, manifest_handle, photo.id, lp_download_path, version.size
                            )
                        logger.info("Downloaded %s", truncated_path)
    return success
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_manifest_integration.py -v`
Expected: PASS (both integration tests)

- [ ] **Step 5: Run the full existing test suite**

Run: `python3 -m pytest --numprocesses auto`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/icloudpd/base.py tests/test_manifest_integration.py
git commit -m "feat: record manifest rows for Live Photo video components"
```

---

## Task 8: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite with coverage**

Run: `bash scripts/test`
Expected: all tests pass; check the coverage report includes `src/icloudpd/manifest.py` at or near 100% (every function is exercised directly by `tests/test_manifest.py` or indirectly by `tests/test_manifest_integration.py`).

- [ ] **Step 2: Type check**

Run: `bash scripts/type_check`
Expected: `Success: no issues found`

- [ ] **Step 3: Lint**

Run: `bash scripts/lint`
Expected: no output (clean)

- [ ] **Step 4: Manual smoke check against a throwaway directory**

```bash
mkdir -p /tmp/manifest-smoke
python3 -m icloudpd --directory /tmp/manifest-smoke --username someone@example.com --password x --auth-only 2>&1 | tail -5
```

This won't authenticate (fake credentials), but confirms `manifest.open()` doesn't crash the CLI's early startup path when `--directory` is set. If it errors before reaching authentication with anything other than an auth failure, investigate before proceeding.

```bash
rm -rf /tmp/manifest-smoke
```

- [ ] **Step 5: Confirm branch state**

```bash
git log --oneline feature/persistent-asset-manifest -8
git status
```

Expected: clean working tree, all commits from Tasks 1-7 present, still on `feature/persistent-asset-manifest` (not `master`).
