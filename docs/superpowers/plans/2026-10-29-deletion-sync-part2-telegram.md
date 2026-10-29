# Deletion Sync Part 2 (Telegram review) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A held deletion batch is reviewed from Telegram as one rich message (numbered thumbnail collage, per-photo keep toggles, paging, Delete/Keep all), backed by a new authenticated, multi-account control channel in icloudpd and a per-account iCloud session registry.

**Architecture:** icloudpd gains `session_registry.py` (one live `PyiCloudService` per account plus a per-account `RLock` taken around every iCloud HTTP request), `deletion_review.py` (entry keys, batch token, paging, keep marks, apply, thumbnails) and `control/` (a second Flask app on waitress, `/v1` routes, bearer-token hook). The Telegram bot gains a control client and renders/edits a rich message; it keeps no review state beyond the last message id per entry.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`/`hmac`/`hashlib`/`threading`, Flask 3.1.1 + waitress 3.0.2 (already deps), pytest; bot: aiogram **3.31.0** (rich messages), aiohttp 3.11.11, requests, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-29-deletion-sync-part2-telegram-design.md`. Part 1 background: `docs/superpowers/specs/2026-10-28-deletion-sync-design.md`. Read the Part 2 spec before any task.

## Global Constraints

- Control channel is absent unless global `control_token_file` is set; token read from that file only (never env var, never config value). Default `control_port` **2012**, bind `0.0.0.0`.
- Every control request: `Authorization: Bearer <token>`, compared with `hmac.compare_digest`; else **401**. Auth lives in one `before_request` hook.
- All routes under `/v1/`. Nothing assumes a "current user"; every entry is addressed by its key.
- Entry key = first **8** hex of `sha256(f"{username}\0{library}")`. Startup fails (exit 2) on a key collision.
- Batch token = first **8** hex of `sha256("\n".join(sorted(held record names)))`; `""` when nothing is held.
- Page size **10**; pages are **1-based**; order `detected_utc`, then `record_name`; item `number` is 1-based across the batch.
- Control channel never prompts for a password and never triggers MFA. Token-only refresh at most **once per 600 s** per account.
- `keep`/`resolve` while `state.db` is busy → **503** `{"reason": "syncing"}`, nothing changed.
- Status codes: 401 auth, 404 unknown key or entry without `sync_deletions`, 409 stale batch token (body carries current `batch_token`), 503 syncing / thumbnail unavailable, 400 malformed body.
- No thumbnail or iCloud URL is written to disk or sent to the bot; the bot receives JPEG bytes only.
- Bot: `deletion_sync_summary` sends nothing. Every new handler enforces `allowed_chat_ids`. `callback_data` ≤ **64** bytes.
- Raw env vars `ICLOUDPD_CONTROL_TOKEN` are rejected by the bot, like its other secrets.
- CLI resolver stays whole-batch and ignores `keep_marked`.
- Pre-existing mypy/ruff failures on master are not regressions. Every icloudpd task passes `uv run pytest -q` plus `uv run mypy` / `ruff check` / `ruff format --check` on the files it touches; bot tasks pass `cd integrations/telegram-bot && uv run --extra test pytest -q`.

## Review Focus

1. **Stale message tapped after a scan grew the batch**: Delete must not approve anything the message didn't show → 409 and redraw. Test in Task 2 (`apply_review` token check) and Task 5 (bot redraws on 409).
2. **Two entries for one account (PrimarySync + SharedSync)**: one registry slot and lock, two entry keys, two `state.db`s; acting on one never touches the other. Test in Task 4.
3. **Thumbnail request while that account is mid-scan**: waits for the in-flight request only, doesn't deadlock (RLock re-entry from the scan thread's own `authenticator` call). Test in Task 1.
4. **Session rejected by Apple at review time**: one token-only refresh, never a password provider; repeated failures within 600 s don't call Apple again. Test in Task 3.
5. **Bot restarted with a review message open**: callbacks still work because each carries entry key, page and token. Test in Task 5.

---

### Task 1: Session registry and per-request lock

**Files:**
- Create: `src/icloudpd/session_registry.py`
- Modify: `src/pyicloud_ipd/session.py` (`PyiCloudSession.request`), `src/pyicloud_ipd/base.py` (`PyiCloudService`), `src/icloudpd/base.py` (`run_with_configs`, `_process_all_users_once`, `core_single_run` around `authenticator()` at line ~1255)
- Test: `tests/test_session_registry.py`

**Interfaces:**
- Produces: `class SessionRegistry` with
  - `lock(username: str) -> threading.RLock` (created on first use, same object forever)
  - `publish(username: str, service: PyiCloudService | None) -> None` (sets `service.request_lock = self.lock(username)`)
  - `get(username: str) -> PyiCloudService | None`
  - `refresh(username: str, now: float) -> PyiCloudService | None` — token-only; returns the slot's service if `revalidate_token()` succeeds, clears the slot and returns `None` otherwise; returns `None` without calling Apple if the last attempt for that username was < 600 s before `now`, or if the slot is empty (there is no session to revalidate; every process start runs a scan that fills it).
- Produces: `PyiCloudService.request_lock: threading.RLock | None` (default `None`) and `PyiCloudService.revalidate_token() -> bool` (calls `_validate_token()`; on success updates `self.data`, `params["dsid"]`, `_webservices`, resets `_photos = None`; returns False on `PyiCloudAPIResponseException`; never calls `password_provider`).
- Produces: `core_single_run(..., registry: SessionRegistry | None = None)`; `_process_all_users_once(..., registry: SessionRegistry | None = None)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_session_registry.py`:
  - `test_lock_is_stable_per_username`: `r.lock("a") is r.lock("a")`, `r.lock("a") is not r.lock("b")`.
  - `test_publish_sets_request_lock_and_get_returns_it` (use a `MagicMock(spec=PyiCloudService)`).
  - `test_publish_none_clears_slot`.
  - `test_refresh_success_keeps_service`: `revalidate_token` returns True → returns the service.
  - `test_refresh_failure_clears_slot`: returns False → `None`, `get()` is `None`.
  - `test_refresh_rate_limited`: two calls at `now=1000` and `now=1599` → `revalidate_token` called once; a third at `now=1600` calls it again.
  - `test_refresh_never_uses_password_provider`: a real `PyiCloudService` built with a `password_provider` mock and `_validate_token` patched to raise `PyiCloudAPIResponseException` → `revalidate_token()` is False and the provider mock was never called.
  - `test_request_holds_lock`: a `PyiCloudSession` whose `super().request` is patched to assert `service.request_lock._is_owned()` → passes; with `request_lock=None` the request still works.
  - `test_reentrant_from_same_thread`: acquire `r.lock("a")` then issue a patched session request on the same thread → no deadlock.
  - `test_core_single_run_publishes`: with `authenticator` patched to return a mock service, `core_single_run(..., registry=r)` leaves `r.get(username)` as that service, and `authenticator` ran while `r.lock(username)` was held.

- [ ] **Step 2: Run** `uv run pytest tests/test_session_registry.py -q` — Expected: FAIL (`ModuleNotFoundError: icloudpd.session_registry`).

- [ ] **Step 3: Implement** the registry, `request_lock` wrapping the whole body of `PyiCloudSession.request` (including the session/cookie file writes) when set, `revalidate_token`, and the `core_single_run` change: wrap `authenticator(...)` in `with registry.lock(user_config.username):` and `registry.publish(...)` right after; publish `None` when authentication raises. `run_with_configs` creates one `SessionRegistry` and passes it down.

- [ ] **Step 4: Run** `uv run pytest -q` — Expected: all pass (existing auth tests unchanged).

- [ ] **Step 5: Commit** `feat(control): per-account session registry with request lock`

---

### Task 2: Review state in `state.db`

**Files:**
- Create: `src/icloudpd/deletion_review.py`
- Modify: `src/icloudpd/deletion_sync.py` (schema + migration for `keep_marked`; clear it wherever an item leaves `held`; split `resolve` so both sets run in one transaction)
- Test: `tests/test_deletion_review.py`

**Interfaces:**
- Consumes: `deletion_sync.list_items`, `ItemStatus`, `ensure_schema`, `_BUSY_TIMEOUT_SECONDS`.
- Produces in `deletion_sync.py`: `resolve_split(connection, approve: Sequence[str], reject: Sequence[str]) -> tuple[list[DeletionItem], list[DeletionItem]]` — one `BEGIN IMMEDIATE` transaction, same per-item semantics as `resolve`; `resolve` becomes a thin wrapper over it. Column `deletion_items.keep_marked INTEGER NOT NULL DEFAULT 0`; `DeletionItem.keep_marked: bool`.
- Produces in `deletion_review.py`:
  - `PAGE_SIZE = 10`
  - `entry_key(username: str, library: str) -> str`
  - `batch_token(connection) -> str`
  - `@dataclass(frozen=True) class ReviewItem: number: int; record_name: str; filename: str; asset_date_utc: str; keep: bool`
  - `@dataclass(frozen=True) class ReviewPage: batch_token: str; page: int; pages: int; total: int; kept_count: int; items: list[ReviewItem]`
  - `held_page(connection, page: int) -> ReviewPage` (page out of range → empty `items`, `pages` still correct)
  - `class StaleBatch(Exception)` with attribute `batch_token: str`; `class Busy(Exception)`
  - `set_keep(connection, record_name: str, keep: bool, token: str) -> tuple[int, int]` (total, kept_count); `KeyError` if the record isn't held
  - `apply_review(connection, action: Literal["apply", "keep_all"], token: str) -> tuple[int, int]` (approved count, rejected count)
  - Both writers raise `StaleBatch` on token mismatch (checked inside the write transaction) and `Busy` on `sqlite3.OperationalError` "database is locked".

- [ ] **Step 1: Write the failing tests** (seed `deletion_items` directly, as `tests/test_deletion_sync_resolve.py` does):
  - `test_entry_key_shape_and_stability`: 8 lowercase hex chars; same inputs → same key; `("a","PrimarySync") != ("a","SharedSync-x")`.
  - `test_batch_token_changes_when_batch_changes` and `test_batch_token_empty_is_blank`.
  - `test_held_page_numbers_and_order`: 23 held items → `pages == 3`; page 2 `items[0].number == 11`; ordering by `detected_utc` then `record_name`; non-held rows excluded.
  - `test_set_keep_marks_and_counts`; `test_set_keep_unknown_or_not_held_record` → `KeyError`.
  - `test_apply_marks_split`: 5 held, 2 marked → returns `(3, 2)`; marked rows `rejected` with `missing_since_scan` NULL; others `approved`; `tripped == 0`; `keep_marked` reset to 0 on all.
  - `test_keep_all_rejects_everything`.
  - `test_stale_token_changes_nothing`: add a held row after taking the token → `StaleBatch` with the new token; statuses unchanged.
  - `test_busy_raises_busy`: hold `BEGIN IMMEDIATE` on a second connection; with busy timeout patched to 0.1 s → `Busy`.
  - `test_migration_adds_keep_marked`: an old-schema db (no column) gains it via `ensure_schema`.
  - `test_cli_resolver_ignores_marks`: marked items are approved by `resolve(conn, "approve", all names)`.

- [ ] **Step 2: Run** `uv run pytest tests/test_deletion_review.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement** as specified above.

- [ ] **Step 4: Run** `uv run pytest -q` — Expected: all pass, including existing `test_deletion_sync_*`.

- [ ] **Step 5: Commit** `feat(deletion-sync): review state, batch token, per-photo keep`

---

### Task 3: Thumbnails through the registry

**Files:**
- Modify: `src/pyicloud_ipd/services/photos.py` (`PhotoLibrary`), `src/icloudpd/deletion_review.py`
- Test: `tests/test_deletion_review_thumbnails.py`

**Interfaces:**
- Consumes: `SessionRegistry` (Task 1).
- Produces: `PhotoLibrary.lookup_masters(record_names: Sequence[str]) -> dict[str, dict[str, Any]]` — one POST to `{service_endpoint}/records/lookup?{params}` with `{"records": [{"recordName": n} ...], "zoneID": zone_id}`; returns found records keyed by `recordName`, skipping entries carrying `serverErrorCode`.
- Produces: `thumbnail_field(master: dict[str, Any]) -> str | None` — first present of `resJPEGThumbRes`, then any other `resJPEG*Res` with smallest `size`; `None` if none (e.g. a video without a JPEG derivative → caller shows placeholder).
- Produces: `fetch_thumbnail(registry: SessionRegistry, username: str, library: str, record_name: str, now: float) -> bytes | None`.

Algorithm for `fetch_thumbnail` (not determined by the signature):
```
service = registry.get(username) or registry.refresh(username, now)
if service is None: return None
for attempt in (1, 2):
    try:
        lib = library object for `library` (private_libraries / shared_libraries, as core_single_run picks it)
        master = lib.lookup_masters([record_name]).get(record_name)
        field = master and thumbnail_field(master)
        if not field: return None
        return service.session.get(master["fields"][field]["value"]["downloadURL"]).content
    except PyiCloudAPIResponseException as e:
        if attempt == 2 or e.code not in {"401", "421", "450"}: return None
        service = registry.refresh(username, now)
        if service is None: return None
    except (requests.RequestException, KeyError): return None
```

- [ ] **Step 1: Write the failing tests** (patch the session's HTTP layer with `unittest.mock`; no network):
  - `test_lookup_masters_posts_record_names_and_zone` (assert URL path `records/lookup` and body).
  - `test_lookup_masters_skips_server_errors`.
  - `test_thumbnail_field_prefers_jpeg_thumb`, `test_thumbnail_field_none_for_video_only_record`.
  - `test_fetch_thumbnail_returns_bytes`.
  - `test_fetch_thumbnail_empty_slot_returns_none_without_calling_apple`.
  - `test_fetch_thumbnail_421_refreshes_and_retries`; `test_fetch_thumbnail_second_421_gives_up`.
  - `test_fetch_thumbnail_rate_limit_respected`: two failing calls within 600 s → `revalidate_token` called once.

- [ ] **Step 2: Run** `uv run pytest tests/test_deletion_review_thumbnails.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q` — Expected: pass.
- [ ] **Step 5: Commit** `feat(deletion-sync): on-demand thumbnails via session registry`

---

### Task 4: Control channel (config, startup, routes)

**Files:**
- Create: `src/icloudpd/control/__init__.py`
- Modify: `src/icloudpd/config.py` (`GlobalConfig.control_token_file: str | None`, `control_port: int`), `src/icloudpd/config_defaults.py` (`"control_port": 2012`, `"control_token_file": None`), `src/icloudpd/config_file.py` (app-section keys), `src/icloudpd/cli.py` (`--control-token-file`, `--control-port`, `map_to_config` like `webui_port` at line ~629), `src/icloudpd/base.py` (`run_with_configs`: read token, check key collisions, start thread next to the web UI one at line ~413)
- Test: `tests/test_control_channel.py`, `tests/test_config_defaults.py` (update if it snapshots defaults)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `build_control_app(logger: Logger, token: str, user_configs: Sequence[UserConfig], registry: SessionRegistry, clock: Callable[[], float] = time.time) -> Flask` and `serve_control(logger, token, user_configs, registry, host: str = "0.0.0.0", port: int = 2012) -> None`.
- Produces routes (JSON field names fixed here; the bot depends on them):
  - `GET /v1/entries` → `{"entries": [{"key", "username", "library", "held_count", "tripped"}]}` — only entries with `sync_deletions`.
  - `GET /v1/entries/<key>/held?page=N` → `{"batch_token","page","pages","total","kept_count","items":[{"number","record_name","filename","asset_date","is_video","keep"}]}`. `is_video` from the filename extension (`.mov`, `.mp4`, `.m4v`); default page 1.
  - `GET /v1/entries/<key>/held/<record_name>/thumbnail` → `image/jpeg` or 503 `{"reason":"thumbnail_unavailable"}`; 404 if the record isn't held in that entry.
  - `POST /v1/entries/<key>/held/<record_name>/keep` body `{"keep": bool, "batch_token": str}` → `{"total","kept_count"}`.
  - `POST /v1/entries/<key>/resolve` body `{"action": "apply"|"keep_all", "batch_token": str}` → `{"approved","rejected"}`.
  - 409 body `{"batch_token": <current>}`; 503 body `{"reason": "syncing"}` on `Busy`.
- Each request opens its own SQLite connection to the entry's `state.db` (path via `manifest.db_path(directory, state_directory)`) with Part 1's busy timeout, and closes it.

- [ ] **Step 1: Write the failing tests** (Flask `test_client()`, as `tests/test_server.py` does; seed temp `state.db`s; fake registry):
  - `test_no_token_401`, `test_wrong_token_401`, `test_auth_uses_compare_digest` (patch `hmac.compare_digest`, assert called).
  - `test_entries_lists_all_sync_entries_multi_account`: users `a` (PrimarySync, SharedSync-X) and `b` (PrimarySync) → 3 entries, distinct keys, correct `held_count`s; an entry without `sync_deletions` is absent.
  - `test_unknown_key_404`.
  - `test_held_page_shape_and_paging`: 12 held → page 2 has 2 items numbered 11–12, `pages == 2`.
  - `test_keep_then_apply_touches_only_that_entry`: apply on `a/SharedSync-X` leaves `a/PrimarySync` and `b` unchanged.
  - `test_stale_token_409_returns_current_token`.
  - `test_busy_returns_503_syncing`.
  - `test_thumbnail_ok_and_unavailable` (patch `fetch_thumbnail`).
  - `test_thumbnail_for_record_not_held_404`.
  - `test_run_with_configs_no_token_file_no_listener`; `test_run_with_configs_token_file_starts_listener_on_control_port` (patch `Thread`); `test_entry_key_collision_exits_2` (patch `entry_key`).
  - `test_cli_and_yaml_control_options` (flags and `app:` keys populate `GlobalConfig`; default port 2012).

- [ ] **Step 2: Run** `uv run pytest tests/test_control_channel.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.** Token file unreadable or empty → log error, exit 2.
- [ ] **Step 4: Run** `uv run pytest -q` — Expected: pass.
- [ ] **Step 5: Commit** `feat(control): authenticated multi-account control channel`

---

### Task 5: Bot review message

**Files:**
- Create: `integrations/telegram-bot/bot/control_client.py`, `integrations/telegram-bot/bot/review.py`
- Modify: `bot/config.py` (`control_url: str | None`, `control_token: str | None` from `ICLOUDPD_CONTROL_URL` default `http://icloudpd:2012` and `ICLOUDPD_CONTROL_TOKEN_FILE`; reject `ICLOUDPD_CONTROL_TOKEN`), `bot/notify_listener.py` (dispatch `deletion_sync_threshold_tripped`; `deletion_sync_summary` falls through to the ignore branch), `bot/app.py`, `bot/handlers.py` (callback prefix `ds:` and `/held`), `bot/main.py`, `pyproject.toml` (`aiogram==3.31.0`)
- Test: `integrations/telegram-bot/tests/test_review.py`, `tests/test_control_client.py`, update `tests/test_config.py`, `tests/test_notify_listener.py`

**Interfaces:**
- Consumes: Task 4 routes and field names.
- Produces: `ControlClient(base_url: str, token: str, timeout: float = 15.0)` with `entries() -> list[dict]`, `page(key: str, page: int) -> dict`, `thumbnail(key: str, record_name: str) -> bytes | None`, `set_keep(key, record_name, keep: bool, token: str) -> dict`, `resolve(key, action: str, token: str) -> dict`; raises `StaleBatchError(batch_token)` on 409, `SyncingError` on 503 syncing.
- Produces in `review.py`:
  - `pack(key: str, op: str, page: int, arg: int, token: str) -> str` / `unpack(data: str) -> Callback` (format `ds:<key>:<op>:<page>:<arg>:<token>`; ops `t` toggle (arg = item number), `p` page (arg = target page), `a` apply, `k` keep all; `ValueError` on anything else).
  - `render(entry: dict, page: dict, thumbs: dict[str, bytes | None]) -> tuple[InputRichMessage, InlineKeyboardMarkup]` — header paragraph (`⚠️ {total} photos held for deletion ({username} · {library}).`), collage of `InputRichBlockPhoto` with `BufferedInputFile` per item and `RichBlockCaption(text=str(number))` (`▶ {number}` for videos; placeholder JPEG bundled in the bot when bytes are `None`); if **all** thumbs are `None`, a numbered paragraph list (`{number}. {filename} · {date}`) plus the line "Thumbnails return after icloudpd's next successful login." Keyboard: two rows of five toggles (`🗑 n` / `💾 n`, only for items present), `◀ Prev`/`Next ▶` (omit at the ends), `✅ Delete {total-kept}, keep {kept}` / `❌ Keep all`.
  - `ReviewService(bot, client, allowed_chat_ids)` with `on_tripped(event)`, `on_callback(callback)`, `on_held_command(message)`; tracks `last_message[(chat_id, key)] -> message_id` in memory only.
- Copy (exact): 409 → answer "The batch changed, nothing was deleted. Here's the updated batch." and redraw; syncing → answer "icloudpd is syncing, try again in a minute."; after apply → edit to "{approved} will be deleted at the next sync. {rejected} kept, re-downloading." without buttons; after keep all → "Nothing deleted. {rejected} photos will re-download at the next sync."; superseded → "Superseded, see the newer message." without buttons; `/held` with nothing held → "No held deletions."

- [ ] **Step 1: Write the failing tests** (FakeControlClient + `tests/support/mocked_bot.py`):
  - `test_pack_unpack_roundtrip` and `test_callback_data_max_length` (key 8, page 999, arg 9999, token 8 → `len(pack(...).encode()) <= 64`).
  - `test_render_collage_numbers_and_keyboard` (page 2 of 23 with item 13 kept: captions `11`..`20`, `💾 13`, both nav buttons, `✅ Delete 22, keep 1`).
  - `test_render_text_fallback_when_no_thumbs`.
  - `test_render_video_caption_marker`.
  - `test_tripped_sends_one_rich_message_per_allowed_chat` (entry matched by `username` + `data.library`).
  - `test_tripped_again_marks_previous_superseded`.
  - `test_toggle_calls_set_keep_and_edits`; `test_page_edits_with_new_thumbs`.
  - `test_apply_edits_final_text_no_buttons`; `test_keep_all_final_text`.
  - `test_stale_token_redraws_and_answers`; `test_syncing_answers_retry_text_changes_nothing`.
  - `test_callback_from_disallowed_chat_ignored` (no client calls).
  - `test_callback_works_without_prior_state` (fresh `ReviewService`, i.e. after restart).
  - `test_held_command_resends_each_held_entry`; `test_held_command_nothing_held`.
  - `test_summary_event_sends_nothing`.
  - `test_config_rejects_raw_control_token_env`; `test_control_client_sends_bearer_and_maps_409_503` (use `responses`).

- [ ] **Step 2: Run** `cd integrations/telegram-bot && uv run --extra test pytest -q` — Expected: FAIL.
- [ ] **Step 3: Implement.** Thumbnails for a page are fetched concurrently with `asyncio.to_thread`. If `send_rich_message` rejects `BufferedInputFile` inside blocks, build the multipart `attach://` form manually (the 2026-10-29 spike proved the raw API accepts it).
- [ ] **Step 4: Run** the bot suite — Expected: pass.
- [ ] **Step 5: Commit** `feat(telegram-bot): rich-message review of held deletions`

---

### Task 6: Docs and live checklist

**Files:**
- Modify: `README.md` ("Deletion sync": Telegram review, `control_token_file`, `control_port`), `integrations/telegram-bot/README.md`, `integrations/telegram-bot/docker-compose.example.yml` (control token secret on both services, `ICLOUDPD_CONTROL_URL`, `--control-token-file`), `docs/deletion-sync-live-test.md` (Part 2 manual checks from the spec: photo and video thumbnails on the phone; batch > 10 paged both ways, 2 kept, next scan deletes the rest and re-downloads the 2; bot restart with an open message; review ~20 h after the last scan and record whether the session worked, refreshed, or fell back to text; record which JPEG field videos carry)
- Test: none beyond a docs review.

- [ ] **Step 1: Write the docs.** State plainly: under-threshold deletions send nothing; the CLI stays whole-batch; the control port is not the web UI and needs its own token.
- [ ] **Step 2: Run** `uv run pytest -q` and the bot suite — Expected: pass.
- [ ] **Step 3: Commit** `docs(deletion-sync): Telegram review, control channel, Part 2 live checks`
