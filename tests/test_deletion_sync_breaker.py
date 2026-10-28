"""Circuit breaker, execution and notification events (deletion_sync.finish_scan)."""

import datetime
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from icloudpd import deletion_sync, manifest
from icloudpd.deletion_sync import Verdict
from pyicloud_ipd.services.photos import PhotoAsset, PhotoLibrary

LOGGER = logging.getLogger("test_deletion_sync_breaker")
T0 = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.timezone.utc)


class FakeAsset:
    def __init__(self, record_name: str, tag: str = "tag1") -> None:
        self.id = record_name
        self.filename = f"{record_name}.JPG"
        self.created = datetime.datetime(2024, 1, 2, tzinfo=datetime.timezone.utc)
        self._asset_record = {"recordName": record_name, "recordChangeTag": tag}


class Deleter:
    def __init__(self, result: bool = True, raise_on: int | None = None) -> None:
        self.result = result
        self.raise_on = raise_on
        self.calls: list[str] = []

    def __call__(self, photo: PhotoAsset) -> bool:
        self.calls.append(photo.id)
        if self.raise_on is not None and len(self.calls) == self.raise_on:
            raise RuntimeError("boom")
        return self.result


class Notifier:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, event_type: str, message: str, data: dict[str, Any]) -> bool:
        self.events.append((event_type, message, data))
        return self.result

    def of(self, event_type: str) -> list[dict[str, Any]]:
        return [d for t, _, d in self.events if t == event_type]


class Library:
    """A manifest with assets whose local files are missing."""

    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path
        handle = manifest.open(LOGGER, str(tmp_path / "lib"))
        assert handle is not None
        self.handle = handle
        self.db = str(tmp_path / "lib" / ".icloudpd" / "state.db")
        self.assets: dict[str, tuple[PhotoAsset, str]] = {}

    def add(self, *names: str) -> None:
        for name in names:
            path = str(self.dir / f"{name}.JPG")
            manifest.record_seen(LOGGER, self.handle, name, path, 1)
            self.assets[name] = (cast(PhotoAsset, FakeAsset(name)), path)
        self.handle.connection.commit()

    def remove_from_icloud(self, *names: str) -> None:
        for name in names:
            del self.assets[name]

    def scan(
        self,
        *,
        threshold: int = 5,
        delete: Deleter | None = None,
        notify: Notifier | None = None,
        now: datetime.datetime = T0,
        dry_run: bool = False,
    ) -> dict[str, Verdict]:
        scan = deletion_sync.open_scan(LOGGER, self.handle, dry_run)
        verdicts = {
            name: deletion_sync.judge_asset(LOGGER, scan, photo, [(path, 1)])
            for name, (photo, path) in self.assets.items()
        }
        deletion_sync.finish_scan(
            LOGGER,
            scan,
            threshold=threshold,
            delete=delete if delete is not None else Deleter(),
            notify=notify if notify is not None else Notifier(),
            now=now,
        )
        if dry_run:
            scan.connection.close()
        return verdicts

    def candidates(self, *names: str, now: datetime.datetime = T0) -> None:
        """Add assets and run the debounce scan so the next scan sees them as candidates."""
        self.add(*names)
        verdicts = self.scan(now=now)
        assert all(verdicts[n] == Verdict.SUSPECT for n in names)

    def statuses(self) -> dict[str, str]:
        conn = sqlite3.connect(self.db)
        try:
            return dict(conn.execute("SELECT record_name, status FROM deletion_items"))
        finally:
            conn.close()

    def via_approval(self, name: str) -> int:
        row = self.handle.connection.execute(
            "SELECT via_approval FROM deletion_items WHERE record_name = ?", (name,)
        ).fetchone()
        return int(row[0])

    def manifest_rows(self, name: str) -> int:
        return len(manifest.get_all_for_asset(self.handle, name))

    def tripped(self) -> int:
        return int(
            self.handle.connection.execute("SELECT tripped FROM deletion_state").fetchone()[0]
        )

    def add_item(self, name: str, status: str, changed: str = "2026-10-01T00:00:00+00:00") -> None:
        self.handle.connection.execute(
            "INSERT INTO deletion_items (record_name, filename, asset_date_utc, detected_utc,"
            " status, status_changed_utc) VALUES (?, ?, 'd', 'd', ?, ?)",
            (name, f"{name}.JPG", status, changed),
        )
        self.handle.connection.commit()


@pytest.fixture
def lib(tmp_path: Path) -> Library:
    return Library(tmp_path)


def test_below_threshold_deletes_and_summarizes(lib: Library) -> None:
    lib.candidates("A", "B")
    delete, notify = Deleter(), Notifier()
    lib.scan(threshold=5, delete=delete, notify=notify)
    assert delete.calls == ["A", "B"]
    assert lib.statuses() == {"A": "deleted", "B": "deleted"}
    assert lib.manifest_rows("A") == 0 and lib.manifest_rows("B") == 0
    assert lib.via_approval("A") == 0
    summaries = notify.of("deletion_sync_summary")
    assert len(summaries) == 1
    assert summaries[0]["deleted_count"] == 2
    assert summaries[0]["failed_count"] == 0
    assert summaries[0]["total"] == 2
    assert summaries[0]["items"][0] == {
        "record_name": "A",
        "filename": "A.JPG",
        "asset_date": "2024-01-02T00:00:00+00:00",
    }
    assert notify.of("deletion_sync_threshold_tripped") == []


def test_unbounded_threshold_deletes(lib: Library) -> None:
    names = [f"R{i:03d}" for i in range(100)]
    lib.candidates(*names)
    delete = Deleter()
    lib.scan(threshold=-1, delete=delete)
    assert len(delete.calls) == 100
    assert set(lib.statuses().values()) == {"deleted"}
    assert len(lib.statuses()) == 100


def test_reaching_threshold_holds_all(lib: Library) -> None:
    lib.candidates("A", "B", "C")
    delete, notify = Deleter(), Notifier()
    lib.scan(threshold=3, delete=delete, notify=notify)
    assert delete.calls == []
    assert lib.statuses() == {"A": "held", "B": "held", "C": "held"}
    assert lib.tripped() == 1
    assert lib.manifest_rows("A") == 1
    tripped = notify.of("deletion_sync_threshold_tripped")
    assert len(tripped) == 1
    assert tripped[0]["held_count"] == 3
    assert tripped[0]["new_count"] == 3
    assert tripped[0]["threshold"] == 3
    assert tripped[0]["total"] == 3
    assert notify.of("deletion_sync_summary") == []


def test_trip_persists_and_merges(lib: Library) -> None:
    lib.candidates("A", "B", "C")
    lib.scan(threshold=3)
    assert lib.tripped() == 1
    lib.candidates("D")
    delete, notify = Deleter(), Notifier()
    verdicts = lib.scan(threshold=3, delete=delete, notify=notify)
    assert verdicts == {
        "A": Verdict.HELD,
        "B": Verdict.HELD,
        "C": Verdict.HELD,
        "D": Verdict.CANDIDATE,
    }
    assert delete.calls == []
    assert lib.statuses()["D"] == "held"
    tripped = notify.of("deletion_sync_threshold_tripped")
    assert len(tripped) == 1
    assert tripped[0]["new_count"] == 1
    assert tripped[0]["held_count"] == 4
    quiet = Notifier()
    lib.scan(threshold=3, delete=delete, notify=quiet)
    assert quiet.events == []
    assert delete.calls == []


def test_tripped_holds_even_below_threshold(lib: Library) -> None:
    lib.candidates("A", "B", "C")
    lib.scan(threshold=3)
    lib.candidates("D")
    delete = Deleter()
    lib.scan(threshold=100, delete=delete)
    assert delete.calls == []
    assert lib.statuses()["D"] == "held"


def test_slow_leak_trips(lib: Library) -> None:
    delete, notify = Deleter(), Notifier()
    for day, pair in enumerate([("A", "B"), ("C", "D"), ("E", "F")]):
        now = T0 + datetime.timedelta(days=day)
        lib.candidates(*pair, now=now)
        lib.scan(threshold=5, delete=delete, notify=notify, now=now)
        lib.remove_from_icloud(*[n for n in pair if lib.statuses()[n] == "deleted"])
    assert delete.calls == ["A", "B", "C", "D"]
    assert lib.statuses()["E"] == "held" and lib.statuses()["F"] == "held"
    tripped = notify.of("deletion_sync_threshold_tripped")
    assert len(tripped) == 1 and tripped[0]["held_count"] == 2


def test_window_expires(lib: Library) -> None:
    delete = Deleter()
    for i, pair in enumerate([("A", "B"), ("C", "D"), ("E", "F")]):
        now = T0 + datetime.timedelta(days=8 * i)
        lib.candidates(*pair, now=now)
        lib.scan(threshold=5, delete=delete, now=now)
        lib.remove_from_icloud(*pair)
    assert delete.calls == ["A", "B", "C", "D", "E", "F"]
    assert lib.tripped() == 0


def test_approved_bypasses_breaker_and_not_counted(lib: Library) -> None:
    names = [f"R{i}" for i in range(10)]
    lib.add(*names)
    deletion_sync.ensure_schema(lib.handle.connection)
    for name in names:
        lib.add_item(name, "approved")
    delete, notify = Deleter(), Notifier()
    lib.scan(threshold=3, delete=delete, notify=notify)
    assert sorted(delete.calls) == sorted(names)
    assert set(lib.statuses().values()) == {"deleted"}
    assert all(lib.via_approval(n) == 1 for n in names)
    assert all(lib.manifest_rows(n) == 0 for n in names)
    assert notify.of("deletion_sync_summary")[0]["deleted_count"] == 10
    lib.remove_from_icloud(*names)
    lib.candidates("NEW")
    delete2 = Deleter()
    lib.scan(threshold=3, delete=delete2)
    assert delete2.calls == ["NEW"]
    assert lib.statuses()["NEW"] == "deleted"


def test_approved_not_seen_is_skipped_gone(lib: Library) -> None:
    lib.add("A")
    deletion_sync.ensure_schema(lib.handle.connection)
    lib.add_item("A", "approved")
    lib.remove_from_icloud("A")
    delete = Deleter()
    lib.scan(delete=delete)
    assert delete.calls == []
    assert lib.statuses() == {"A": "skipped_gone"}


@pytest.mark.parametrize("approved", [False, True], ids=["candidate", "approved"])
def test_reappeared_before_delete_is_skipped(lib: Library, approved: bool) -> None:
    if approved:
        lib.add("A")
        deletion_sync.ensure_schema(lib.handle.connection)
        lib.add_item("A", "approved")
    else:
        lib.candidates("A")
    photo, path = lib.assets["A"]
    scan = deletion_sync.open_scan(LOGGER, lib.handle, False)
    deletion_sync.judge_asset(LOGGER, scan, photo, [(path, 1)])
    Path(path).write_bytes(b"x")  # restored between detection and execution
    delete = Deleter()
    deletion_sync.finish_scan(LOGGER, scan, threshold=5, delete=delete, notify=Notifier(), now=T0)
    assert delete.calls == []
    assert lib.statuses() == {"A": "skipped_reappeared"}
    assert lib.manifest_rows("A") == 1


def test_failed_delete_is_retried(lib: Library) -> None:
    lib.candidates("A")
    notify = Notifier()
    lib.scan(delete=Deleter(result=False), notify=notify)
    assert lib.statuses() == {"A": "failed"}
    assert lib.manifest_rows("A") == 1
    summary = notify.of("deletion_sync_summary")
    assert summary[0]["deleted_count"] == 0 and summary[0]["failed_count"] == 1
    delete = Deleter()
    verdicts = lib.scan(delete=delete)
    assert verdicts == {"A": Verdict.CANDIDATE}
    assert delete.calls == ["A"]
    assert lib.statuses() == {"A": "deleted"}


def test_failed_approved_delete_stays_approved(lib: Library) -> None:
    names = ["A", "B", "C"]
    lib.add(*names)
    deletion_sync.ensure_schema(lib.handle.connection)
    for name in names:
        lib.add_item(name, "approved")
    notify = Notifier()
    lib.scan(threshold=2, delete=Deleter(result=False), notify=notify)
    assert lib.statuses() == {n: "approved" for n in names}
    assert all(lib.manifest_rows(n) == 1 for n in names)
    summary = notify.of("deletion_sync_summary")[0]
    assert summary["failed_count"] == 3 and summary["deleted_count"] == 0
    delete = Deleter()
    verdicts = lib.scan(threshold=2, delete=delete)
    assert verdicts == {n: Verdict.HELD for n in names}
    assert sorted(delete.calls) == names
    assert lib.statuses() == {n: "deleted" for n in names}
    assert all(lib.via_approval(n) == 1 for n in names)
    lib.remove_from_icloud(*names)
    lib.candidates("NEW")
    delete2 = Deleter()
    lib.scan(threshold=2, delete=delete2)
    assert delete2.calls == ["NEW"]  # the approved retries did not count toward the window


def test_notify_failure_does_not_block(lib: Library) -> None:
    lib.candidates("A", "B")
    notify = Notifier(result=False)
    lib.scan(delete=Deleter(), notify=notify)
    assert len(notify.events) == 1
    assert lib.statuses() == {"A": "deleted", "B": "deleted"}


def test_notify_exception_does_not_block(lib: Library) -> None:
    lib.candidates("A")

    def broken(_t: str, _m: str, _d: dict[str, Any]) -> bool:
        raise RuntimeError("notifier down")

    scan = deletion_sync.open_scan(LOGGER, lib.handle, False)
    photo, path = lib.assets["A"]
    deletion_sync.judge_asset(LOGGER, scan, photo, [(path, 1)])
    deletion_sync.finish_scan(LOGGER, scan, threshold=5, delete=Deleter(), notify=broken, now=T0)
    assert lib.statuses() == {"A": "deleted"}


def test_exception_mid_execution_keeps_progress(lib: Library) -> None:
    lib.candidates("A", "B", "C")
    with pytest.raises(RuntimeError):
        lib.scan(delete=Deleter(raise_on=2))
    statuses = lib.statuses()  # fresh connection on the on-disk file
    assert statuses.get("A") == "deleted"
    assert statuses.get("B") != "deleted"
    assert statuses.get("C") != "deleted"
    conn = sqlite3.connect(lib.db)
    try:
        rows = {r[0] for r in conn.execute("SELECT record_name FROM downloaded_assets")}
    finally:
        conn.close()
    assert rows == {"B", "C"}


def test_items_capped_at_50(lib: Library) -> None:
    names = [f"R{i:03d}" for i in range(60)]
    lib.candidates(*names)
    notify = Notifier()
    lib.scan(threshold=-1, notify=notify)
    summary = notify.of("deletion_sync_summary")[0]
    assert len(summary["items"]) == 50
    assert summary["total"] == 60
    assert summary["deleted_count"] == 60


def test_tripped_items_capped_at_50(lib: Library) -> None:
    names = [f"R{i:03d}" for i in range(60)]
    lib.candidates(*names)
    notify = Notifier()
    lib.scan(threshold=10, notify=notify)
    tripped = notify.of("deletion_sync_threshold_tripped")[0]
    assert len(tripped["items"]) == 50
    assert tripped["total"] == 60


def test_prunes_terminal_rows_after_30_days(lib: Library) -> None:
    deletion_sync.ensure_schema(lib.handle.connection)
    old = (T0 - datetime.timedelta(days=31)).isoformat()
    recent = (T0 - datetime.timedelta(days=29)).isoformat()
    lib.add_item("OLD_DELETED", "deleted", old)
    lib.add_item("OLD_GONE", "skipped_gone", old)
    lib.add_item("OLD_REAPPEARED", "skipped_reappeared", old)
    lib.add_item("RECENT_DELETED", "deleted", recent)
    lib.add_item("OLD_FAILED", "failed", old)
    lib.add_item("OLD_REJECTED", "rejected", old)
    lib.scan()
    assert set(lib.statuses()) == {"RECENT_DELETED", "OLD_FAILED", "OLD_REJECTED"}


def test_scan_marked_completed(lib: Library) -> None:
    scan = deletion_sync.open_scan(LOGGER, lib.handle, False)
    deletion_sync.finish_scan(
        LOGGER, scan, threshold=5, delete=Deleter(), notify=Notifier(), now=T0
    )
    completed = lib.handle.connection.execute(
        "SELECT last_completed_scan_seq FROM deletion_state"
    ).fetchone()[0]
    assert completed == scan.scan_seq


def _dump(path: str) -> list[str]:
    c = sqlite3.connect(path)
    try:
        return list(c.iterdump())
    finally:
        c.close()


def test_dry_run_no_writes_no_calls(lib: Library, caplog: pytest.LogCaptureFixture) -> None:
    lib.candidates("A", "B", "C")
    lib.add("APPROVED")
    lib.add_item("APPROVED", "approved")
    before_bytes = Path(lib.db).read_bytes()
    before = _dump(lib.db)
    delete, notify = Deleter(), Notifier()
    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        lib.scan(threshold=3, delete=delete, notify=notify, dry_run=True)
    assert delete.calls == []
    assert notify.events == []
    assert "[DRY RUN] Would hold 3 items (threshold 3)" in caplog.text
    assert "[DRY RUN] Would delete APPROVED.JPG" in caplog.text
    assert Path(lib.db).read_bytes() == before_bytes
    assert _dump(lib.db) == before


def test_dry_run_below_threshold_logs_deletes(
    lib: Library, caplog: pytest.LogCaptureFixture
) -> None:
    lib.candidates("A")
    before = _dump(lib.db)
    delete, notify = Deleter(), Notifier()
    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        lib.scan(threshold=3, delete=delete, notify=notify, dry_run=True)
    assert delete.calls == [] and notify.events == []
    assert "[DRY RUN] Would delete A.JPG" in caplog.text
    assert _dump(lib.db) == before


# Observed records/modify response (tests/vcr_cassettes/download_autodelete_photos_part1.yml),
# with recordName set to the fake asset's.
REAL_MODIFY_RESPONSE: dict[str, Any] = {
    "records": [
        {
            "recordName": "A",
            "recordType": "CPLAsset",
            "fields": {"isDeleted": {"value": 1, "type": "INT64"}},
            "pluginFields": {},
            "recordChangeTag": "1s2k",
            "created": {
                "timestamp": 1686106171024,
                "userRecordName": "_cfcd54372a11173505ad48f023ba188d",
                "deviceID": "10D26FAEB98CF62382056A6813126093E3CC11C07B3DF3BDEBC4B50A7649973B",
            },
            "modified": {
                "timestamp": 1686106458410,
                "userRecordName": "_cfcd54372a11173505ad48f023ba188d",
                "deviceID": "2",
            },
            "deleted": False,
            "expirationTime": 1689562458,
        }
    ],
    "syncToken": "AQAAAAAAAURhf/////////+LxHA1AvhAx66JMCtmgB8J",
}


class FakeResponse:
    def __init__(self, ok: bool, body: dict[str, Any]) -> None:
        self.ok = ok
        self.status_code = 200 if ok else 400
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.posts: list[tuple[str, Any]] = []

    def post(self, url: str, data: Any = None, headers: Any = None) -> FakeResponse:
        self.posts.append((url, data))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeLibrary:
    def __init__(self, session: FakeSession) -> None:
        self.service_endpoint = (
            "https://example.invalid/database/1/com.apple.photos.cloud/production/private"
        )
        self.params = {"dsid": "1"}
        self.zone_id = {"zoneName": "PrimarySync"}
        self.session = session


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (FakeResponse(True, {"records": [{"recordName": "A", "fields": {}}]}), True),
        (
            FakeResponse(True, {"records": [{"recordName": "A", "serverErrorCode": "CONFLICT"}]}),
            False,
        ),
        (FakeResponse(True, REAL_MODIFY_RESPONSE), True),
        (FakeResponse(True, {}), False),
        (FakeResponse(True, {"records": [{"recordName": "OTHER"}]}), False),
        (FakeResponse(False, {"records": []}), False),
        (ConnectionError("network down"), False),
    ],
    ids=[
        "clean",
        "real-icloud-shape",
        "server-error-code",
        "no-records",
        "other-record",
        "not-ok",
        "raises",
    ],
)
def test_delete_asset_checks_response(response: FakeResponse | Exception, expected: bool) -> None:
    import json

    session = FakeSession(response)
    library = cast(PhotoLibrary, FakeLibrary(session))
    photo = cast(PhotoAsset, FakeAsset("A", tag="CHANGE_TAG"))
    assert deletion_sync.delete_asset(LOGGER, library, photo) is expected
    assert len(session.posts) == 1
    url, data = session.posts[0]
    assert url.startswith("https://example.invalid/") and "/records/modify?" in url
    body = json.loads(data)
    record = body["operations"][0]["record"]
    assert record["fields"]["isDeleted"]["value"] == 1
    assert record["recordChangeTag"] == "CHANGE_TAG"
    assert record["recordName"] == "A"
    assert body["zoneID"] == {"zoneName": "PrimarySync"}


def test_delete_asset_malformed_photo_returns_false() -> None:
    session = FakeSession(FakeResponse(True, REAL_MODIFY_RESPONSE))
    library = cast(PhotoLibrary, FakeLibrary(session))
    photo = FakeAsset("A")
    photo._asset_record = {"recordName": "A"}  # no recordChangeTag
    assert deletion_sync.delete_asset(LOGGER, library, cast(PhotoAsset, photo)) is False
    assert session.posts == []


def test_delete_request_matches_delete_photo() -> None:
    """base.delete_photo and delete_asset send the same request."""
    from icloudpd import base

    photo = cast(PhotoAsset, FakeAsset("A", tag="CHANGE_TAG"))
    old = FakeSession(FakeResponse(True, REAL_MODIFY_RESPONSE))
    base.delete_photo(LOGGER, cast(PhotoLibrary, FakeLibrary(old)), photo, lambda p: p.filename)
    new = FakeSession(FakeResponse(True, REAL_MODIFY_RESPONSE))
    assert deletion_sync.delete_asset(LOGGER, cast(PhotoLibrary, FakeLibrary(new)), photo)
    assert old.posts == new.posts


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions"
)
def test_unreadable_directory_at_execution_aborts(tmp_path: Path) -> None:
    handle = manifest.open(LOGGER, str(tmp_path / "lib"))
    assert handle is not None
    folder = tmp_path / "2024"
    folder.mkdir()
    path = str(folder / "X.JPG")
    photo = cast(PhotoAsset, FakeAsset("X"))
    manifest.record_seen(LOGGER, handle, "X", path, 1)
    handle.connection.commit()
    for seq in (1, 2):
        scan = deletion_sync.open_scan(LOGGER, handle, False)
        deletion_sync.judge_asset(LOGGER, scan, photo, [(path, 1)])
        if seq == 1:
            deletion_sync.finish_scan(
                LOGGER, scan, threshold=-1, delete=Deleter(), notify=Notifier(), now=T0
            )
    assert "X" in scan.candidates
    Path(path).write_bytes(b"x")  # back on disk, but the folder becomes unreadable
    folder.chmod(0)
    deleter = Deleter()
    try:
        with pytest.raises(deletion_sync.DeletionSyncError):
            deletion_sync.finish_scan(
                LOGGER, scan, threshold=-1, delete=deleter, notify=Notifier(), now=T0
            )
    finally:
        folder.chmod(0o755)
    assert deleter.calls == []


class MountedLibrary(Library):
    """A Library whose root carries the mount marker, checked during the scan."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        self.marker = tmp_path / ".mounted"
        self.marker.write_text("")

    def open(self) -> deletion_sync.DeletionScan:
        return deletion_sync.open_scan(LOGGER, self.handle, False, marker_dir=str(self.dir))

    def judge(self, scan: deletion_sync.DeletionScan) -> dict[str, Verdict]:
        return {
            name: deletion_sync.judge_asset(LOGGER, scan, photo, [(path, 1)])
            for name, (photo, path) in self.assets.items()
        }

    def finish(self, scan: deletion_sync.DeletionScan, deleter: Deleter, threshold: int) -> None:
        deletion_sync.finish_scan(
            LOGGER, scan, threshold=threshold, delete=deleter, notify=Notifier(), now=T0
        )

    def completed(self) -> int:
        return int(
            self.handle.connection.execute(
                "SELECT last_completed_scan_seq FROM deletion_state"
            ).fetchone()[0]
        )

    def marks(self) -> list[Any]:
        return [
            r[0]
            for r in self.handle.connection.execute(
                "SELECT missing_since_scan FROM downloaded_assets"
            )
        ]


def test_marker_gone_before_marking_writes_nothing(tmp_path: Path) -> None:
    mlib = MountedLibrary(tmp_path)
    mlib.add("A", "B")
    mlib.marker.unlink()  # the mount dropped: every file looks gone
    scan = mlib.open()
    assert set(mlib.judge(scan).values()) == {Verdict.UNVERIFIED}
    deleter = Deleter()
    mlib.finish(scan, deleter, -1)
    assert mlib.marks() == [None, None]
    assert mlib.completed() == 0
    assert deleter.calls == []


def test_marker_gone_before_candidate_is_not_candidate(tmp_path: Path) -> None:
    mlib = MountedLibrary(tmp_path)
    mlib.add("A")
    scan1 = mlib.open()
    assert mlib.judge(scan1) == {"A": Verdict.SUSPECT}
    mlib.finish(scan1, Deleter(), -1)
    assert mlib.completed() == 1
    mlib.marker.unlink()
    scan2 = mlib.open()
    assert mlib.judge(scan2) == {"A": Verdict.UNVERIFIED}
    assert not scan2.candidates
    deleter = Deleter()
    mlib.finish(scan2, deleter, -1)
    assert deleter.calls == []
    assert mlib.completed() == 1


@pytest.mark.parametrize("threshold", [-1, 1], ids=["would-delete", "would-hold"])
def test_marker_gone_before_finish_scan_executes_nothing(tmp_path: Path, threshold: int) -> None:
    mlib = MountedLibrary(tmp_path)
    mlib.add("A", "B")
    scan1 = mlib.open()
    mlib.judge(scan1)
    mlib.finish(scan1, Deleter(), threshold)
    mlib.add_item("B", "approved")
    scan2 = mlib.open()
    assert mlib.judge(scan2) == {"A": Verdict.CANDIDATE, "B": Verdict.HELD}
    mlib.marker.unlink()  # drops after judging, before the scan finishes
    deleter = Deleter()
    mlib.finish(scan2, deleter, threshold)
    assert deleter.calls == []
    assert mlib.statuses() == {"B": "approved"}
    assert mlib.tripped() == 0
    assert mlib.completed() == 1
