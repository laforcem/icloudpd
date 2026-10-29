# Telegram bot (unsupported)

Optional sidecar that gives icloudpd remote, button-driven interaction over
Telegram: 2FA codes, and review of held deletion batches (deletion sync).

**No maintenance commitment.** This ships because it's useful to the
maintainer personally. If Telegram's API changes and breaks it, that's a
"fix it if there's time" problem, not a tracked bug. It is intentionally
excluded from the core test/release/CI surface — this directory has its own
`pyproject.toml` and is not referenced by the root project's `pyproject.toml`
or `scripts/test`.

## What it does

1. icloudpd fires a `session_expired` event through its normal
   `notification_script` hook (see `../../src/icloudpd/notifications.py`).
2. `notification_script.py` forwards that event, unmodified, to this bot's
   `/notify` endpoint and exits immediately.
3. The bot DMs every chat ID in `TELEGRAM_ALLOWED_CHAT_IDS` with a
   "Start 2FA" button. No push is sent to your phone yet.
4. Tapping the button calls icloudpd's `POST /trigger-push`, which is what
   actually triggers Apple's push to your trusted device, and puts that chat
   into code-expecting mode.
5. Paste the 6-digit code as a plain message (no `/` prefix). The bot submits
   it to icloudpd's `POST /code` and reports success or failure.
6. On failure you get "Try again" / "Exit" buttons — "Try again" re-triggers
   the push, "Exit" just stops the bot from treating your next message as a
   code (icloudpd itself keeps waiting either way, same as it always has with
   nobody watching the WebUI).

Requires icloudpd running with `--mfa-provider webui`. See
`docs/superpowers/specs/2026-07-15-telegram-2fa-sidecar-design.md` in the
repo root for the full design rationale.

### Proactive refresh (`session_expiring_soon`)

icloudpd also warns before a session actually expires (see
`docs/superpowers/specs/2026-07-16-proactive-session-expiry-warning-design.md`).
What the bot does with that warning depends on whether re-authenticating
would need a human at a password prompt:

- **A password is stored** (`parameter`/`keyring` in `password_providers`):
  the bot sends a "Refresh session now" button. Tapping it calls
  `POST /force-reauth`, which clears the session and lets icloudpd
  re-authenticate silently, landing on the same "Start 2FA" flow above.
- **`webui` is the only password provider** (nothing is ever persisted):
  clearing the session would instead block indefinitely at a password
  prompt with nobody watching. The bot detects this via icloudpd's
  `/status.json` (`password_requires_manual_entry`) and sends a plain
  text warning instead of a button that can't do anything — plus an
  "Open WebUI" deep-link button if `ICLOUDPD_WEBUI_EXTERNAL_URL_FILE` is set
  (see below).

### Deletion-sync review (held batches)

When deletion sync holds a batch (threshold reached), the bot sends a rich
message per entry: numbered thumbnails (10 per page), a 🗑/💾 toggle per
photo, Prev/Next, `✅ Delete N, keep M` and `❌ Keep all`. Deletions under the
threshold send nothing. Deletes go out at the end of icloudpd's next completed
sync; kept photos re-download then. `/held` re-sends a review message for every
entry with a held batch. There are no `/approve`/`/reject` commands.

If icloudpd's iCloud session can't be used when the review opens, the message
is a numbered text list and the buttons still work. If the batch or keep marks
changed since the message was drawn, Apply deletes nothing and redraws it.

Setup: icloudpd needs `--control-token-file` (a file holding a bearer token;
port 2012 by default, separate from the WebUI). The bot needs the same token
in a file at `ICLOUDPD_CONTROL_TOKEN_FILE` and, if the default doesn't fit,
`ICLOUDPD_CONTROL_URL` (default `http://icloudpd:2012`). A raw
`ICLOUDPD_CONTROL_TOKEN` is rejected. Without the token file the bot's review
is off. The port binds `0.0.0.0`: keep it on the Docker network, don't publish
it. Rich messages need Telegram Bot API 10.1+ (the bot pins aiogram 3.31.0).
See the repo README, "Deletion sync".

## Running it

Secrets are files, not environment variables — see `TELEGRAM_BOT_TOKEN_FILE`/
`TELEGRAM_ALLOWED_CHAT_IDS_FILE`/`ICLOUDPD_WEBUI_EXTERNAL_URL_FILE` in
`bot/config.py`; the raw `TELEGRAM_BOT_TOKEN`/`TELEGRAM_ALLOWED_CHAT_IDS`/
`ICLOUDPD_WEBUI_EXTERNAL_URL` env vars are rejected outright.

Optionally set `ICLOUDPD_WEBUI_EXTERNAL_URL_FILE` to a file containing a
browser-reachable URL for icloudpd's WebUI (e.g. `http://vm101.lan:2011`) —
distinct from `ICLOUDPD_BASE_URL`, which is the container-internal address
this bot talks to over the Docker network. Not auto-detected (a container
has no reliable way to know its own LAN-facing address); only used to add a
deep-link button when a session refresh needs a human at the password
prompt. Treated as a secret since it can point at an otherwise-unauthenticated
admin panel.

```bash
mkdir -p secrets
echo -n "<your bot token>" > secrets/telegram_bot_token.txt
echo -n "<comma-separated chat IDs>" > secrets/telegram_allowed_chat_ids.txt
# Optional, for deletion-sync review; the same file feeds both services:
openssl rand -hex 32 | tr -d '\n' > secrets/icloudpd_control_token.txt
docker compose -f docker-compose.example.yml up
```

## Testing

```bash
pip install -e '.[test]'
pytest
```

Unit tests run without any real Telegram or icloudpd connection — everything
network-facing is faked (the review message is not run against live Telegram;
see `docs/deletion-sync-live-test.md`, Part 2). For a real end-to-end pass against the live
Telegram API, see `E2E_CHECKLIST.md`.
