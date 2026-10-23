# State Directory and Mount Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `state.db` live outside the photo library (#34) and refuse to download when the library's `.mounted` marker is missing (#35).

**Architecture:** `state_directory` is a new per-user key plumbed like `cookie_directory`; `manifest.open` takes it as an optional third argument. The mount guard is a new module `mount_guard.py` called at the top of `core_single_run` (before authentication). It keeps per-user "currently missing" state in memory so notifications fire on transitions only. The Telegram bot gains two handlers for the two new event types.

**Tech Stack:** Python, argparse, sqlite3, pytest (`unittest.TestCase` style plus plain pytest), aiohttp/aiogram in `integrations/telegram-bot`.

**Spec:** GitHub issues laforcem/icloudpd#34 and #35, plus the decisions recorded under Global Constraints (made in the brainstorming conversation, not in the issues).

## Global Constraints

- New per-user keys: `state_directory` (path string, default unset/`None`) and `require_mount_marker` (bool, default `False`). CLI flags: `--state-directory`, `--require-mount-marker`.
- Unset/false must leave current behaviour byte-for-byte unchanged (DB at `<directory>/.icloudpd/state.db`, no marker check).
- Marker path is fixed: `<directory>/.mounted`, and it must be a regular file.
- `state_directory` set: DB at `<state_directory>/state.db`; directory created if missing; nothing created under `<directory>/.icloudpd`.
- `state_directory` set and the DB cannot be opened: log an error and fail that user's run (return `1`). Unset keeps warn-and-continue.
- `state_directory` set, `<state_directory>/state.db` absent, `<directory>/.icloudpd/state.db` present: log a warning naming both paths and the migration step; run continues with a fresh DB.
- Marker missing: log an error, write nothing under `directory`, skip that user. Single-run mode exits non-zero; watch mode continues to the next user and retries next cycle.
- Notifications go through the existing `notification_script` JSON path. Event types: `library_mount_missing` (first failure only) and `library_mount_restored` (first success after a failure). No notification when the marker is present on the first check.
- The guard only applies when the run would touch `directory`: skip it when `auth_only`, `list_albums`, or `list_libraries` is set.
- Telegram alerts carry a button only when there is something to act on. `library_mount_missing` gets a "Check again now" button (the user remounts, then taps to skip the rest of the watch wait via icloudpd's existing `/resume` endpoint). `library_mount_restored` is informational: no button.
- Do not tag a release or push an image. Open a PR; the user tags.
- Commit trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`.

## Review Focus

- Marker present on the very first check: no notification, run proceeds.
- Marker missing for many consecutive cycles: exactly one `library_mount_missing` notification, an error log every cycle.
- Marker missing then restored then missing again: a second `library_mount_missing` fires.
- Two users, only one with a missing marker: the other still runs; state is tracked per username.
- `state_directory` contains `~`: expanded, same as `cookie_directory`.
- `state_directory` points at an unwritable path: run returns `1` and no download happens.
- `.mounted` exists as a directory, not a file: treated as missing.

## File Structure

- Create `src/icloudpd/mount_guard.py`: marker check, transition state, notifications.
- Create `tests/test_mount_guard.py`: unit tests for the module and the `core_single_run` wiring.
- Modify `src/icloudpd/manifest.py`: `open` takes `state_directory`.
- Modify `src/icloudpd/config.py`, `config_defaults.py`, `cli.py`, `config_file.py`: new keys.
- Modify `src/icloudpd/base.py`: call sites.
- Modify `tests/test_manifest.py`, `tests/test_cli.py`, `tests/test_server.py`, `tests/test_config_defaults.py` (as needed): coverage and `UserConfig(...)` constructor sites.
- Modify `integrations/telegram-bot/bot/{notify_listener,app,messages,handlers,icloudpd_client}.py` and its tests.
- Modify `config.example.yaml`, `README.md`: documentation.

---

### Task 1: Config plumbing for both keys

**Files:**
- Modify: `src/icloudpd/config.py`, `src/icloudpd/config_defaults.py`, `src/icloudpd/cli.py`, `src/icloudpd/config_file.py`
- Modify: `tests/test_cli.py`, `tests/test_server.py` (the four `UserConfig(... cookie_directory=...)` construction sites)
- Test: `tests/test_cli.py`, `tests/test_config_file.py`

**Interfaces:**
- Produces: `UserConfig.state_directory: str | None`, `UserConfig.require_mount_marker: bool`; `USER_OPTION_DEFAULTS["state_directory"] = None`, `USER_OPTION_DEFAULTS["require_mount_marker"] = False`.

- [ ] **Step 1: Write failing tests.** In `tests/test_cli.py`, follow the existing `map_to_config` test style: `test_state_directory_flag_maps_to_config` (`--state-directory /state/a` → `state_directory == "/state/a"`), `test_state_directory_defaults_to_none`, `test_require_mount_marker_flag_maps_to_config` (flag → `True`; absent → `False`). In `tests/test_config_file.py`: `test_require_mount_marker_accepts_bool_and_state_directory_accepts_string` (a YAML user entry with both keys is accepted and `state_directory: /state/a` is not flagged by the Norway-problem check).
- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py tests/test_config_file.py -q`. Expected: FAIL (unknown attribute/flag).
- [ ] **Step 3: Implement.** Add the two fields to `_DefaultConfig` (`config.py`), the two defaults to `USER_OPTION_DEFAULTS`, `--state-directory` (plain string, `default=None`) and `--require-mount-marker` (`store_true`, `default=None`, modelled on `--xmp-sidecar`) in `cli.py`, the two `get(...)` lines in `map_to_config`, and add `"require_mount_marker"` to `_USER_BOOL_FIELDS` in `config_file.py`.
- [ ] **Step 4: Fix every `UserConfig(...)` construction site** in `tests/test_cli.py` and `tests/test_server.py` by adding `state_directory=None, require_mount_marker=False`. Run `uv run pytest tests/test_cli.py tests/test_config_file.py tests/test_config_defaults.py tests/test_server.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add state_directory and require_mount_marker config keys`.

### Task 2: State directory in the manifest (#34)

**Files:**
- Modify: `src/icloudpd/manifest.py:55-75`, `src/icloudpd/base.py:1050-1054`
- Test: `tests/test_manifest.py`, `tests/test_manifest_integration.py`

**Interfaces:**
- Consumes: `UserConfig.state_directory` from Task 1.
- Produces: `manifest.open(logger: logging.Logger, download_dir: str, state_directory: str | None = None) -> ManifestHandle | None`.

- [ ] **Step 1: Write failing tests** in `tests/test_manifest.py`:
  - `test_open_with_state_directory_puts_db_there_and_creates_nothing_in_library` (assert `<state>/state.db` is a file and `<download_dir>/.icloudpd` does not exist).
  - `test_open_with_state_directory_creates_missing_state_directory` (nested missing path).
  - `test_open_without_state_directory_uses_dot_icloudpd` (existing behaviour, keep the current test).
  - `test_open_with_state_directory_warns_when_legacy_db_exists` (create `<download_dir>/.icloudpd/state.db` first; use `assertLogs` to assert a WARNING containing both paths; handle is not `None`).
  - `test_open_with_state_directory_does_not_warn_when_new_db_exists` (state DB already present alongside a legacy one: no warning).
  - `test_open_with_unwritable_state_directory_returns_none` (state path under a regular file).
- [ ] **Step 2: Write failing integration tests** in `tests/test_manifest_integration.py`, modelled on `test_newly_downloaded_photo_gets_manifest_row`: `test_state_directory_flag_puts_manifest_outside_library` (run with `--state-directory`, assert rows are in the state DB and `<data_dir>/.icloudpd` is absent) and `test_unwritable_state_directory_fails_the_run` (state path under a regular file → `result.exit_code == 1`, no photo files written).
- [ ] **Step 3: Run** `uv run pytest tests/test_manifest.py tests/test_manifest_integration.py -q`. Expected: FAIL.
- [ ] **Step 4: Implement** `manifest.open` with the new parameter. Directory is `state_directory` when given, else `<download_dir>/.icloudpd`. The legacy-DB check runs before connecting. Warning text must name the legacy path, the new path, and say to copy `state.db` over while the container is stopped. Update the module docstring's path sentence.
- [ ] **Step 5: Implement the call site** in `base.py`: expand the value with `os.path.expanduser(os.path.normpath(...))`, pass it to `manifest.open`; if `user_config.state_directory` is set, `manifest_handle` is `None`, and `only_print_filenames` is false, `logger.error(...)` and `return 1`.
- [ ] **Step 6: Run** `uv run pytest tests/test_manifest.py tests/test_manifest_integration.py -q`. Expected: PASS.
- [ ] **Step 7: Commit** `feat: configurable state_directory for the asset manifest (#34)`.

### Task 3: Mount guard module (#35)

**Files:**
- Create: `src/icloudpd/mount_guard.py`
- Test: `tests/test_mount_guard.py`

**Interfaces:**
- Consumes: `notifications.build_event`, `notifications.notify` (existing).
- Produces: `mount_guard.check(logger: logging.Logger, username: str, directory: str, notification_script: str | None) -> bool` (True = marker present, proceed) and `mount_guard.reset() -> None` (clears in-memory state, for tests).

- [ ] **Step 1: Write failing tests** in `tests/test_mount_guard.py` (use `tmp_path`; patch `icloudpd.mount_guard.notifications.notify` and capture events; call `mount_guard.reset()` in a fixture):
  - `test_marker_present_returns_true_and_does_not_notify`
  - `test_marker_missing_returns_false_logs_error_and_notifies_once` (event type `library_mount_missing`, `username` set, `data["directory"] == directory`)
  - `test_repeated_missing_notifies_only_on_first_failure` (three calls → one notify, error logged three times)
  - `test_restored_notifies_once_then_stays_quiet` (missing, present, present → `library_mount_missing` then one `library_mount_restored`)
  - `test_second_outage_notifies_again` (missing, present, missing → two `library_mount_missing`)
  - `test_state_is_tracked_per_username` (user A missing does not suppress user B's first failure)
  - `test_marker_that_is_a_directory_counts_as_missing`
  - `test_check_creates_nothing_under_directory` (point at a nonexistent `directory`; assert it still does not exist afterwards)
- [ ] **Step 2: Run** `uv run pytest tests/test_mount_guard.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `check` and `reset` in `src/icloudpd/mount_guard.py`. Use `os.path.isfile(os.path.join(directory, ".mounted"))` (read-only, no `makedirs`). Keep a module-level `set[str]` of usernames currently flagged missing. Messages: missing → `"{username}'s library at {directory} is not mounted (.mounted marker missing); skipping this run."`; restored → `"{username}'s library at {directory} is mounted again; resuming."`.
- [ ] **Step 4: Run** `uv run pytest tests/test_mount_guard.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: mount_guard module for .mounted marker checks (#35)`.

### Task 4: Wire the guard into core_single_run

**Files:**
- Modify: `src/icloudpd/base.py` (`core_single_run`, before the `authenticator(` call, ~line 971)
- Test: `tests/test_mount_guard.py` (add a second `TestCase`/section), using `run_cassette` as in `tests/test_session_expired_notification.py`

**Interfaces:**
- Consumes: `mount_guard.check` (Task 3), `UserConfig.require_mount_marker` (Task 1).

- [ ] **Step 1: Write failing integration tests** (reuse a download cassette already used in `tests/test_download_photos.py`; `recreate_path` the data and cookie dirs):
  - `test_marker_present_run_proceeds` (create `<data_dir>/.mounted`, pass `--require-mount-marker`; exit code 0 and a photo is downloaded).
  - `test_marker_missing_exits_nonzero_and_writes_nothing` (point `-d` at a nonexistent path; exit code 1; the path still does not exist; the notification script mock received one `library_mount_missing` event).
  - `test_flag_off_ignores_missing_marker` (no flag, no marker → current behaviour, run proceeds).
  - `test_auth_only_skips_the_guard` (`--auth-only --require-mount-marker`, no marker → not blocked by the guard).
  - `test_marker_returns_next_run_proceeds` (call `mount_guard.reset()` first; run once without marker → exit 1; create marker; run again → exit 0 and a `library_mount_restored` event is sent).
- [ ] **Step 2: Run** `uv run pytest tests/test_mount_guard.py -q`. Expected: the new integration tests FAIL.
- [ ] **Step 3: Implement** the call: at the top of `core_single_run`'s body (before the retry loop), when `user_config.require_mount_marker` and not (`auth_only` or `list_albums` or `list_libraries`) and `user_config.directory` is set, call `mount_guard.check(logger, user_config.username, os.path.normpath(user_config.directory), <notification_script str or None>)`; if it returns False, `return 1`.
- [ ] **Step 4: Run** `uv run pytest tests -q -x --ignore=integrations`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: skip runs when the library mount marker is missing (#35)`.

### Task 5: Telegram bot handlers for the new events

**Files:**
- Modify: `integrations/telegram-bot/bot/notify_listener.py`, `bot/app.py`, `bot/messages.py`, `bot/handlers.py`, `bot/icloudpd_client.py`
- Test: `integrations/telegram-bot/tests/test_notify_listener.py`, `tests/test_messages.py`, `tests/test_handlers.py`, `tests/test_icloudpd_client.py`, plus any test that calls `build_notify_app` or `build_application`

**Interfaces:**
- Produces: `build_notify_app(on_session_expired, on_session_expiring_soon, on_mfa_accepted, on_mfa_rejected, on_library_mount_missing, on_library_mount_restored) -> web.Application` (two new trailing `NotifyHandler` params).
- Produces: `messages.library_mount_missing_text(username: str, message: str) -> str`; `messages.library_mount_restored_text(username: str, message: str) -> str`; `messages.retry_mount_keyboard() -> InlineKeyboardMarkup` (one button, text `Check again now`, callback data `retry_mount`); `messages.retry_mount_requested_text() -> str`.
- Produces: `IcloudpdClient.resume() -> bool` (POST `{base_url}/resume`, True when status 200); `handlers.handle_retry_mount(callback: CallbackQuery, client: IcloudpdClient, allowed_chat_ids: frozenset[int]) -> None`.

- [ ] **Step 1: Write failing tests:**
  - `test_notify_listener.py`: `test_library_mount_missing_event_invokes_its_own_handler` and `test_library_mount_restored_event_invokes_its_own_handler` (follow the `session_expiring_soon` test: other handlers receive nothing, status 204). Update every existing `build_notify_app(...)` call in the bot tests to pass two extra `_noop` handlers.
  - `test_messages.py`: one test per text function (contains the username and message; missing text starts with `🚫`, restored with `✅`); `test_retry_mount_keyboard_has_one_button_with_retry_mount_callback`.
  - `test_icloudpd_client.py`: `test_resume_posts_to_resume_and_returns_true_on_200` and `test_resume_returns_false_on_other_status`, in the style of the existing `force_reauth` client tests.
  - `test_handlers.py`: `test_retry_mount_calls_resume_and_confirms` (disallowed chat is ignored; `RequestException` answers `connection_lost_text()` with `show_alert=True`; failure result answers with an alert; success sends `retry_mount_requested_text()`), mirroring the `handle_force_reauth` tests.
- [ ] **Step 2: Run** `cd integrations/telegram-bot && uv run pytest -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the dispatch branches in `notify_listener.py`; the text functions and keyboard in `messages.py`; `resume` in `icloudpd_client.py`; `handle_retry_mount` in `handlers.py` modelled on `handle_force_reauth`, registered in `build_router` with `F.data == "retry_mount"`; in `app.py`, `on_library_mount_missing` sends the text with `retry_mount_keyboard()` to every `config.allowed_chat_ids` chat, and `on_library_mount_restored` sends the text with no keyboard. Pass both to `build_notify_app`.
- [ ] **Step 4: Run** `cd integrations/telegram-bot && uv run pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(telegram-bot): alert on library mount missing and restored`.

### Task 6: Documentation and migration note

**Files:**
- Modify: `config.example.yaml`, `README.md`

- [ ] **Step 1: `config.example.yaml`:** add commented `state_directory` and `require_mount_marker: true` lines to the per-user entry, each with a one-line comment (state on local disk, not NFS; marker file is `<directory>/.mounted`).
- [ ] **Step 2: `README.md`:** add a short "Library on a network mount" section covering both keys, the alert behaviour (one alert on first failure, one on recovery, requires the notification forwarder or script), and the migration steps: stop the container, copy `<directory>/.icloudpd/state.db` to `<state_directory>/state.db`, set the key, start. State the result of the dependency check from Step 3.
- [ ] **Step 3: Dependency check (#34 acceptance).** Run `grep -rn "get_all_for_asset\|all_records\|prune" src/` and `grep -n "manifest\." src/icloudpd/base.py`. Record in the README what depends on the manifest and what happens if `state.db` is missing instead of copied. Expected finding to verify: only `record_seen`/`open`/`close` are called at runtime, so a missing DB is recreated empty and refilled on the next scan, with no downloaded files affected; if the readers are called anywhere, say so instead.
- [ ] **Step 4: Run the full suite** `uv run pytest tests -q` and `cd integrations/telegram-bot && uv run pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `docs: state_directory, require_mount_marker, and migration note`.

### Task 7: Open the PR

- [ ] **Step 1:** Push `feat/state-directory-and-mount-guard` and open one PR against `master` titled `Configurable state directory and mount marker guard (#34, #35)`, body starting `Closes #34, closes #35`, ending with the attribution line required by the session. Do not tag or publish an image.

---

## Self-review notes

- Spec coverage: #34 (key, path, create dir, unset default, tests, docs, migration + dependency note) → Tasks 1, 2, 6. #35 (opt-in, check each cycle, no writes, error log, notification, tests, docs) → Tasks 3, 4, 5, 6. "Released together" → single PR; tagging left to the user.
- Decision not in the issues, recorded for the reviewer: recovery event, transitions-only alerts, fail-hard on bad `state_directory`, legacy-DB warning, fixed `.mounted` name, non-zero single-run exit, guard skipped for `auth_only`/list modes (my call), in-memory transition state (a process restart re-alerts once if the mount is still down). Button rule from the user: buttons only on actionable alerts, so the missing-mount alert gets "Check again now" and the recovery alert does not. "Check again now" only shortens the watch-mode wait; it does nothing in single-run mode, where there is no wait.
