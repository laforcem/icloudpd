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
9a. Re-run steps 4-7 specifically with `--auth-only` (not a full download run)
    and confirm the bot reports success promptly, without timing out, even
    though icloudpd's `--auth-only` process exits within ~200ms of the code
    being accepted. This is the scenario that originally exposed the polling
    race in issue #15 (the bot's status poll could land after the port was
    already closed); the fix pushes the result instead of polling for it, so
    verify this specifically, not just a full download run.

## Proactive session-expiry warning (issue #9)

10. Run icloudpd against an account/fixture whose stored session is inside the
    configured `--session-expiry-warning-days` window (e.g. `--session-expiry-warning-days 9999`
    against any valid session, to avoid needing an actual near-expiry cookie).
11. Confirm the bot DMs you a warning message ("`<username>`'s iCloud session expires
    in N day(s)...") with a **Refresh session now** button, separate from the
    **Start 2FA** message used by the reactive flow.
12. Tap **Refresh session now**. Confirm the bot replies confirming the refresh was
    requested, and that icloudpd's own logs show a new login attempt starting shortly
    after (within one watch-loop wake, not waiting out the full `--watch-with-interval`).
13. Confirm this new login attempt actually challenges 2FA (since the stored session
    token was cleared) and that the existing **Start 2FA** flow (steps 4-9 above) takes
    over from there, completing normally.
14. Tap **Refresh session now** for a username not configured on this icloudpd instance
    (simulate via a stale/incorrect `TELEGRAM_ALLOWED_CHAT_IDS` setup or a manually
    crafted callback if needed). Confirm the bot shows an alert and does not crash.

Record the outcome (pass/fail per step) in the PR description before merging.
