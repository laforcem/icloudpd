# Telegram bot (unsupported)

Optional sidecar that gives icloudpd remote, button-driven interaction over
Telegram — starting with 2FA, expandable to other notification events later.

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

## Running it

Secrets are files, not environment variables — see `TELEGRAM_BOT_TOKEN_FILE`/
`TELEGRAM_ALLOWED_CHAT_IDS_FILE` in `bot/config.py`; the raw
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_ALLOWED_CHAT_IDS` env vars are rejected outright.

```bash
mkdir -p secrets
echo -n "<your bot token>" > secrets/telegram_bot_token.txt
echo -n "<comma-separated chat IDs>" > secrets/telegram_allowed_chat_ids.txt
docker compose -f docker-compose.example.yml up
```

## Testing

```bash
pip install -e '.[test]'
pytest
```

Unit tests run without any real Telegram or icloudpd connection — everything
network-facing is faked. For a real end-to-end pass against the live
Telegram API, see `E2E_CHECKLIST.md`.
