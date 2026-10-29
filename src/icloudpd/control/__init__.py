"""Authenticated HTTP control channel for reviewing held deletion batches.

The Telegram bot calls these /v1 routes. Every request needs
`Authorization: Bearer <token>`; the one `before_request` hook is where a later
scheme (browser session) would add a branch. Each request opens its own
connection to the entry's state.db and closes it; the listener holds nothing
between requests.
"""

import contextlib
import hmac
import os
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from logging import Logger
from typing import Any, Callable, Dict, Iterator, Sequence

import waitress
from flask import Flask, Response, jsonify, make_response, request

from icloudpd import deletion_review, deletion_sync, manifest
from icloudpd.config import UserConfig
from icloudpd.deletion_review import Busy, StaleBatch
from icloudpd.deletion_sync import DeletionSyncError, ItemStatus
from icloudpd.session_registry import SessionRegistry

_VIDEO_EXTENSIONS = (".mov", ".mp4", ".m4v")
# A page of thumbnails is fetched in parallel; spare threads keep the other routes answering.
CONTROL_THREADS = 8
# Waitress buffers a body before Flask's auth check runs; the request bodies are tiny JSON.
MAX_REQUEST_BODY_BYTES = 16384


class EntryKeyCollision(ValueError):
    """Two sync_deletions entries map to the same entry key."""


@dataclass(frozen=True)
class _Entry:
    key: str
    user_config: UserConfig
    db_path: str


def entry_keys(user_configs: Sequence[UserConfig]) -> Dict[str, UserConfig]:
    """Map entry key -> config for every entry with sync_deletions.

    Raises EntryKeyCollision when two such entries share a key.
    """
    keyed: Dict[str, UserConfig] = {}
    for user_config in user_configs:
        if not user_config.sync_deletions:
            continue
        key = deletion_review.entry_key(user_config.username, user_config.library)
        other = keyed.get(key)
        if other is not None:
            raise EntryKeyCollision(
                f"control channel entry key {key} is shared by {other.username}/{other.library}"
                f" and {user_config.username}/{user_config.library}"
            )
        keyed[key] = user_config
    return keyed


def _entries(user_configs: Sequence[UserConfig]) -> Dict[str, _Entry]:
    return {
        key: _Entry(
            key=key,
            user_config=uc,
            db_path=manifest.db_path(*manifest.library_paths(uc.directory, uc.state_directory)),
        )
        for key, uc in entry_keys(user_configs).items()
        if uc.directory
    }


@contextlib.contextmanager
def _connect(path: str) -> Iterator[sqlite3.Connection | None]:
    """A fresh connection to an existing state.db, or None when it has no deletion state.

    Never creates the file (mode=rw). A Part 1 database without the keep column is
    migrated the same way a scan's first step would.
    """
    if not os.path.isfile(path):
        yield None
        return
    uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=rw"
    connection = sqlite3.connect(uri, uri=True, timeout=deletion_sync._BUSY_TIMEOUT_SECONDS)
    try:
        tables = {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "deletion_items" not in tables or "deletion_state" not in tables:
            yield None
            return
        columns = {r[1] for r in connection.execute("PRAGMA table_info(deletion_items)")}
        if "keep_marked" not in columns:
            deletion_sync.ensure_schema(connection)
        yield connection
    finally:
        connection.close()


def _is_busy(ex: BaseException) -> bool:
    cause = ex.__cause__ if isinstance(ex.__cause__, sqlite3.Error) else ex
    return "locked" in str(cause) or "busy" in str(cause)


def _reason(status: int, reason: str) -> Response:
    return make_response(jsonify({"reason": reason}), status)


def build_control_app(
    logger: Logger,
    token: str,
    user_configs: Sequence[UserConfig],
    registry: SessionRegistry,
    clock: Callable[[], float] = time.time,
) -> Flask:
    app = Flask(__name__)
    app.logger = logger
    expected = f"Bearer {token}".encode()
    entries = _entries(user_configs)

    @app.before_request
    def authenticate() -> Response | None:
        supplied = request.headers.get("Authorization", "").encode()
        if hmac.compare_digest(supplied, expected):
            return None
        return _reason(401, "unauthorized")

    @app.errorhandler(404)
    def not_found(_error: Any) -> Response:
        return _reason(404, "not_found")

    @app.errorhandler(405)
    def not_allowed(_error: Any) -> Response:
        return _reason(405, "method_not_allowed")

    @app.errorhandler(DeletionSyncError)
    @app.errorhandler(sqlite3.Error)
    def state_error(ex: Exception) -> Response:
        if _is_busy(ex):
            return _reason(503, "syncing")
        logger.error("Control channel: state.db error: %s", ex)
        return _reason(500, "state_error")

    def entry(key: str) -> _Entry | None:
        return entries.get(key)

    @app.route("/v1/entries", methods=["GET"])
    def list_entries() -> Response:
        result = []
        for e in entries.values():
            held_count, tripped = 0, False
            with _connect(e.db_path) as conn:
                if conn is not None:
                    held_count = len(deletion_sync.list_items(conn, [ItemStatus.HELD]))
                    row = conn.execute("SELECT tripped FROM deletion_state WHERE id = 1").fetchone()
                    tripped = bool(row and row[0])
            result.append(
                {
                    "key": e.key,
                    "username": e.user_config.username,
                    "library": e.user_config.library,
                    "held_count": held_count,
                    "tripped": tripped,
                }
            )
        return jsonify({"entries": result})

    @app.route("/v1/entries/<key>/held", methods=["GET"])
    def held(key: str) -> Response:
        e = entry(key)
        if e is None:
            return _reason(404, "not_found")
        raw_page = request.args.get("page", "1")
        if not (raw_page.isascii() and raw_page.isdecimal()) or int(raw_page) < 1:
            return _reason(400, "bad_page")
        page_number = int(raw_page)
        with _connect(e.db_path) as conn:
            if conn is None:
                page = deletion_review.ReviewPage(
                    batch_token="",
                    page=page_number,
                    pages=0,
                    total=0,
                    kept_count=0,
                    items=[],
                )
            else:
                page = deletion_review.held_page(conn, page_number)
        return jsonify(
            {
                "batch_token": page.batch_token,
                "keep_token": page.keep_token,
                "page": page.page,
                "pages": page.pages,
                "total": page.total,
                "kept_count": page.kept_count,
                "items": [
                    {
                        "number": i.number,
                        "record_name": i.record_name,
                        "filename": i.filename,
                        "asset_date": i.asset_date_utc,
                        "is_video": i.filename.lower().endswith(_VIDEO_EXTENSIONS),
                        "keep": i.keep,
                    }
                    for i in page.items
                ],
            }
        )

    @app.route("/v1/entries/<key>/held/<record_name>/thumbnail", methods=["GET"])
    def thumbnail(key: str, record_name: str) -> Response:
        e = entry(key)
        if e is None:
            return _reason(404, "not_found")
        with _connect(e.db_path) as conn:
            is_held = conn is not None and (
                conn.execute(
                    "SELECT 1 FROM deletion_items WHERE record_name = ? AND status = ?",
                    (record_name, ItemStatus.HELD.value),
                ).fetchone()
                is not None
            )
        if not is_held:
            return _reason(404, "not_found")
        try:
            content = deletion_review.fetch_thumbnail(
                registry, e.user_config.username, e.user_config.library, record_name, clock()
            )
        except Exception as ex:  # any iCloud/network failure means "show a placeholder"
            logger.warning("Control channel: thumbnail fetch failed (%s)", type(ex).__name__)
            content = None
        if content is None:
            return _reason(503, "thumbnail_unavailable")
        response = make_response(content)
        response.mimetype = "image/jpeg"
        response.headers["Cache-Control"] = "no-store"
        return response

    def _stale(ex: StaleBatch) -> Response:
        return make_response(
            jsonify({"batch_token": ex.batch_token, "keep_token": ex.keep_token}), 409
        )

    def body() -> Dict[str, Any] | None:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else None

    @app.route("/v1/entries/<key>/held/<record_name>/keep", methods=["POST"])
    def keep(key: str, record_name: str) -> Response:
        e = entry(key)
        if e is None:
            return _reason(404, "not_found")
        data = body()
        if (
            data is None
            or not isinstance(data.get("keep"), bool)
            or not isinstance(data.get("batch_token"), str)
        ):
            return _reason(400, "bad_request")
        with _connect(e.db_path) as conn:
            if conn is None:
                return _reason(404, "not_found")
            try:
                total, kept, marks = deletion_review.set_keep(
                    conn, record_name, data["keep"], data["batch_token"]
                )
            except StaleBatch as ex:
                return _stale(ex)
            except Busy:
                return _reason(503, "syncing")
            except KeyError:
                return _reason(404, "not_found")
        return jsonify({"total": total, "kept_count": kept, "keep_token": marks})

    @app.route("/v1/entries/<key>/resolve", methods=["POST"])
    def resolve(key: str) -> Response:
        e = entry(key)
        if e is None:
            return _reason(404, "not_found")
        data = body()
        if (
            data is None
            or data.get("action") not in ("apply", "keep_all")
            or not isinstance(data.get("batch_token"), str)
            or (data["action"] == "apply" and not isinstance(data.get("keep_token"), str))
        ):
            return _reason(400, "bad_request")
        with _connect(e.db_path) as conn:
            if conn is None:
                if data["batch_token"] != "":
                    return make_response(jsonify({"batch_token": "", "keep_token": ""}), 409)
                return jsonify({"approved": 0, "rejected": 0})
            try:
                approved, rejected = deletion_review.apply_review(
                    conn, data["action"], data["batch_token"], data.get("keep_token")
                )
            except StaleBatch as ex:
                return _stale(ex)
            except Busy:
                return _reason(503, "syncing")
        logger.info(
            "Control channel: %s on %s/%s: %d approved, %d rejected",
            data["action"],
            e.user_config.username,
            e.user_config.library,
            approved,
            rejected,
        )
        return jsonify({"approved": approved, "rejected": rejected})

    return app


def serve_control(
    logger: Logger,
    token: str,
    user_configs: Sequence[UserConfig],
    registry: SessionRegistry,
    host: str = "0.0.0.0",
    port: int = 2012,
) -> None:
    logger.info("Deletion-review control channel listening on port %d", port)
    try:
        waitress.serve(
            build_control_app(logger, token, user_configs, registry),
            host=host,
            port=port,
            threads=CONTROL_THREADS,
            max_request_body_size=MAX_REQUEST_BODY_BYTES,
        )
    except Exception as ex:
        logger.error("Deletion-review control channel stopped: %s", ex)
