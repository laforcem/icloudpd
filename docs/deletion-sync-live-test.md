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
   ```

   Then `mkdir -p /tmp/dsync-shared && touch /tmp/dsync-shared/.mounted`.
4. Sync once: `icloudpd --config scratch.yaml`. The photos download.
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
