# Manual E2E checklist (run before cutting a release that includes this)

Not part of CI. Requires a real, otherwise-unused Telegram bot token and your
own Telegram chat ID.

1. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_ALLOWED_CHAT_IDS` (your chat ID).
2. Run icloudpd against a fixture/account that will hit `requires_2fa`,
   with `--mfa-provider webui` and `--notification-script` pointed at
   `notification_script.py`. `tests/fixtures/test_2sa_required_notification_script`
   (root repo) shows the recorded-cassette shape used elsewhere in this repo
   if you want to avoid a real Apple account for this pass; a real, disposable
   test Apple ID also works if you'd rather exercise the real Apple API too.
3. `docker compose -f docker-compose.example.yml up --build`
4. Confirm the bot DMs you an informative message ("`<username>` needs 2FA")
   with a **Start 2FA** button, and that no push notification has arrived on
   your phone yet.
5. Tap **Start 2FA**. Confirm a push notification now arrives on your trusted
   device, and the bot replies asking for the code.
6. Type an incorrect 6-digit code as a plain message (no `/` prefix). Confirm
   the bot reports failure with **Try again** / **Exit** buttons, and that no
   second push fired automatically.
7. Tap **Try again**. Confirm a fresh push arrives, type the correct code as
   a plain message, and confirm the bot reports success.
8. Confirm icloudpd's own logs show authentication completed and the run
   proceeded.
9. Repeat steps 4-7 once using **Exit** instead of **Try again** after a
   failure, confirming the bot goes quiet and a later "Start 2FA" tap on the
   original message still works.

Record the outcome (pass/fail per step) in the PR description before merging.
