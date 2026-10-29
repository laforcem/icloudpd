# Deletion sync: live iCloud check

The first real delete against iCloud is unverified, for both the Shared Library and the personal library. Do this by hand once per library before relying on deletion sync. Use a throwaway photo.

Success is judged by the response naming the deleted record, so a failed request is not mistaken for success. See "What failure looks like" below.

## Shared Library (`SharedSync-…`)

1. In the Photos app, add one throwaway photo to the Shared Library. Wait for it to show on iCloud.com.
2. Find the library name: `icloudpd --username you@icloud.com --list-libraries`. It looks like `SharedSync-…`.
3. Add an entry for it in a scratch config file. Use a new `directory` and a new `state_directory`, shared with no other entry:

   ```yaml
   users:
     - username: you@icloud.com
       library: SharedSync-XXXXXXXX
       directory: /tmp/dsync-shared
       state_directory: /tmp/dsync-shared-state
       require_mount_marker: true
       sync_deletions: true
       deletion_sync_threshold: 1
       skip_created_before: 2d       # only recent photos: keeps the test download small
   ```

   Then `mkdir -p /tmp/dsync-shared && touch /tmp/dsync-shared/.mounted`.
4. Sync once: `icloudpd --config scratch.yaml`. Photos created in the last two days download, including the throwaway one. (If you added it to the library more than two days after taking it, raise `skip_created_before` to cover its creation date.)
5. Delete the throwaway photo's file from `/tmp/dsync-shared`.
6. Sync twice. The first scan marks the photo missing. The second makes it a candidate. Threshold 1 trips on one candidate, so expect the log line `Deletion sync is holding 1 items (threshold 1)` and a `deletion_sync_threshold_tripped` event. Nothing is deleted yet.
7. List it: `icloudpd --config scratch.yaml --list-pending-deletions --for-username you@icloud.com --for-library SharedSync-XXXXXXXX`. Expect the throwaway photo's filename.
8. Approve: `icloudpd --config scratch.yaml --resolve-deletions approve --for-username you@icloud.com --for-library SharedSync-XXXXXXXX`.
9. Sync once more. Expect `Deleted <filename> in iCloud (moved to Recently Deleted)` and a `deletion_sync_summary` event with `deleted_count: 1`, `failed_count: 0`, and the photo in `items`.
10. On iCloud.com, open Recently Deleted. The photo should be there. If someone else participates in the Shared Library, check theirs too; they should be notified.
11. Restore the photo, or let it expire, then delete the scratch directories.

Result:

- Date:
- Outcome (pass / fail):
- Notes:

## Personal library (`PrimarySync`)

Same steps, with these changes:

- Add the throwaway photo to your personal library, not the Shared Library.
- Omit `library:` from the entry (it defaults to `PrimarySync`), and use a different `directory` and `state_directory`, for example `/tmp/dsync-personal` and `/tmp/dsync-personal-state`.
- Omit `--for-library` from the commands in steps 7 and 8.

Result:

- Date:
- Outcome (pass / fail):
- Notes:

## What failure looks like

- A `deletion_sync_summary` event with `failed_count` greater than 0, and the photo missing from `items` (`items` lists only the deleted photos).
- A warning in the log: `Deleting <filename> in iCloud failed: …`, `…: no records in the response`, or `…: record not confirmed`, followed by `Could not delete <filename> in iCloud; will retry next scan`.
- The photo is not in Recently Deleted.
- The item stays `approved` (it was approved by hand) or becomes `failed` (it went out without review) in the `deletion_items` table of `state.db`, and is retried on the next sync. `--list-pending-deletions` lists only held items, so it will not show it.

On a failure, record the log lines and the date above, and do not enable `sync_deletions` on that library.

## Part 2: Telegram review

Nothing here is run against live Telegram or a live iCloud session in automated tests. Do these by hand before enabling review on the homelab. Setup: `control_token_file` on icloudpd, `ICLOUDPD_CONTROL_TOKEN_FILE` on the bot, a scratch entry with `deletion_sync_threshold: 1` or a small `N`, and a Bot API 10.1+ chat.

1. Thumbnails: hold a batch containing at least one photo and one video. Both render in the review message on your phone (videos show `▶ N`).
2. Paging and keep: hold more than 10 photos. Page forward and back. Mark 2 as 💾 keep. Tap `✅ Delete N, keep 2`. Run the next sync: the rest go to Recently Deleted and the 2 re-download to the local library.
3. Bot restart: open a review message, restart the bot container, then use the buttons on the old message. They still work.
4. Session age: open a held batch about 20 hours after the last scan. Record whether the existing session worked, needed the token-only refresh, or fell back to the text list.
5. Video JPEG field: record which JPEG field videos carry (the thumbnail source).
6. Two entries: hold a batch in two accounts or entries. Act on one (including `/held`). The other is untouched and the right one is deleted.

Result:

- Date: 2026-10-29, `malc` account, `PrimarySync`, `deletion_sync_threshold` 3 then 1, images built from `0a91702` and then the fixes below.
- Outcome per check (pass / fail):
  1. Thumbnails: pass after fixes. Photos, a live photo and a video rendered; the video's play icon showed. First run had 4 of 16 gray tiles (see notes).
  2. Paging and keep: pass. 16 held on two pages, two marked keep (one on each page, both with `/` in the record name), Apply: 14 went to Recently Deleted and the 2 re-downloaded. Paging back was not reported separately.
  3. Bot restart: pass. Buttons on the old message worked after the bot container restarted; the first tap was slower (empty thumbnail cache), later taps fast.
  4. Session age: not measured (see below).
  5. Video JPEG field: pass (see below).
  6. Two entries: not tested. The second account was unavailable, and its photos are not visible to the first account's session.
- Session age result (worked / refreshed / text): not measured. The session was only about 15 minutes old at the first review; a review opened about 20 hours after a scan still needs a try on the real stack. The fallbacks (token-only refresh on 401/421/450, then the numbered text list) are untested live.
- Video JPEG field: `resJPEGThumbRes` (also `resJPEGMedRes`) on all three videos checked, so `thumbnail_field` picks a real JPEG for videos.
- Notes:
  - Fixed during the test: record names are base64 and can contain `/`, which 404ed the thumbnail and keep routes (gray tiles, and those photos could not be marked keep); `/notify` waited for the whole review message and exceeded icloudpd's 5 s forwarder timeout (false "Could not deliver" warning); every tap re-fetched all thumbnails (4 to 6 s).
  - Telegram shows no per-photo caption inside a collage or slideshow (checked live on Bot API 10.2; only a collage-level caption and standalone photo blocks show theirs), so each thumbnail gets its number, and a play icon for videos, drawn on it. The badge is cut off in the grid for tall screenshots (Telegram crops them) and is visible in the full-size view. Cropping them first was tried and reverted: it made the message taller.
  - A kept (rejected) photo that is deleted again before the next scan is re-downloaded once, because rejected items fall through to normal download.
  - Not run: review while a login or 2FA is pending.
  - Setup trap: doco-cd redeploys stopped stack containers every 5 minutes. Stopping only `icloudpd` and the bot is not enough; the live v1.2.0 container restarted mid-test and re-downloaded the deleted files. Pause doco-cd for the test window.
  - Test containers need `TZ=America/Denver`, and a notify URL (`TELEGRAM_BOT_NOTIFY_URL`) when the bot's container name differs from `icloudpd-telegram-bot`.
