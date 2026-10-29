# icloudpd

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/laforcem/icloudpd)

A command-line tool to download media from iCloud Photos. This is a Docker-first fork of [icloud_photos_downloader](https://github.com/icloud-photos-downloader/icloud_photos_downloader).

> [!NOTE]
> Full docs are being rewritten from scratch, which effort is being tracked in #22. This README is a placeholder for the interim.

## Run it

For the full list of config options:

```sh
docker run -it --rm ghcr.io/laforcem/icloudpd:latest --help
```

### Normal Docker run

```sh
docker run -it --rm --name icloudpd -v $(pwd)/Photos:/data -e TZ=America/Los_Angeles ghcr.io/laforcem/icloudpd:latest --directory /data --username my@email.address --watch-with-interval 3600
```

### Docker Compose

It's recommended that you use a config file instead of passing CLI arguments into Compose. See [compose.example.yml](./compose.example.yaml) and [config.example.yaml](./config.example.yaml).

## Library on a network mount

If your photo library is on a network filesystem (NFS, SMB), two settings keep a flaky mount from hurting you. Both are per-user and optional; leave them unset and nothing changes.

```yaml
users:
  - username: you@icloud.com
    directory: /data/you             # the library, may be on NFS
    state_directory: /state/you      # local disk
    require_mount_marker: true
```

### `state_directory`

icloudpd keeps a small SQLite database (`state.db`) recording which assets it has downloaded. By default it lives inside the library, at `<directory>/.icloudpd/state.db`. SQLite's file locking is unreliable over NFS, so the database can corrupt. Set `state_directory` (CLI: `--state-directory`) to put it at `<state_directory>/state.db` on local disk instead. The directory is created if missing, and nothing is created under `<directory>/.icloudpd`.

Each user needs their own `state_directory`, so set it per user, not under `all_users`. icloudpd refuses to start if two users share one.

If `state_directory` is set and the database can't be opened there, that user's run fails rather than continuing without it.

**Migrating an existing install:**

1. Stop the container.
2. Copy `<directory>/.icloudpd/state.db` to `<state_directory>/state.db`.
3. Set `state_directory` and start the container.

If you skip the copy, icloudpd logs a warning on startup that points at the old file, then creates a fresh empty database. Nothing at runtime reads the old records back (the manifest is only written to while downloading), so no downloaded file is touched or re-downloaded. The new database fills in again on the next scan, including files already on disk; the only thing lost is the original first-downloaded timestamps.

### `require_mount_marker`

If the mount drops, `directory` becomes an empty local folder, and icloudpd would happily download into your host's own disk. With `require_mount_marker: true` (CLI: `--require-mount-marker`), icloudpd checks that the file `<directory>/.mounted` exists before each run, and skips that user if it doesn't. Create the marker once, on the mounted library: `touch /data/you/.mounted`.

When the marker is missing, icloudpd logs an error, writes nothing under `directory`, and in watch mode tries again on the next cycle. Without watch mode it moves on to the next user, then exits non-zero at the end. The check is skipped for `--auth-only` and the list commands, which don't touch the library.

Alerts go through your notification script (or the bundled Telegram bot): one `library_mount_missing` alert the first time the mount goes missing, and one `library_mount_restored` alert when it returns. With the Telegram bot, the missing-mount alert has a **Check again now** button that ends the current watch-mode wait early, so you can remount and re-check without waiting out the interval.

## Deletion sync

Off by default. With `sync_deletions: true`, a photo you delete from the local library is moved to iCloud's Recently Deleted. Without it, icloudpd re-downloads anything missing, as before.

```yaml
users:
  - username: you@icloud.com
    directory: /data/you
    state_directory: /state/you      # local disk
    require_mount_marker: true       # required
    sync_deletions: true             # CLI: --sync-deletions
    deletion_sync_threshold: 50      # CLI: --deletion-sync-threshold
```

**Immich.** If Immich manages the library, it removes the file from disk only when its trash is emptied, and only on a read-write mount. On a `:ro` mount nothing syncs. With Immich's default trash retention, the iCloud delete happens when Immich empties its trash, not when you delete the photo.

**What counts as deleted.** A photo whose local files are all gone, in two scans in a row. The first scan only marks it. The second makes it a candidate. If any file reappears in between, the mark is cleared. Marking uses the scan's own record of what it downloaded (`state.db`), so only photos icloudpd previously downloaded can be affected. Moving or renaming a file locally counts as deleting it: icloudpd only sees that the old path is gone. If a folder can't be read (for example after a permission change), the run stops with an error instead of treating its files as deleted, and if the `.mounted` marker disappears during a scan, that scan deletes and holds nothing and does not count; marks it set before the marker vanished are cleared when the next scan starts. With `sync_deletions`, `directory` must not start with `~` (icloudpd does not expand it there); `state_directory` may.

**Threshold.** `deletion_sync_threshold` caps how many deletions go out unreviewed.

- `-1` (default): no cap. icloudpd logs a warning at startup.
- `N >= 1`: new candidates are held, not deleted, when the held items, the new candidates, and the unreviewed deletions of the last 7 days add up to `N` or more. So `1` holds every deletion.
- `0` and values below `-1` are rejected at startup.

Only deletions that went out without review count toward the 7 days. Approved ones don't. Once a batch is held, every later candidate is held too, until you resolve the whole batch. Held photos are not re-downloaded while they wait. A held photo whose file reappears locally is dropped from the batch on its own; if that empties the batch, the hold ends. The check runs at the end of each completed scan; a scan that is cancelled partway deletes and holds nothing.

**Reviewing a held batch.** From the CLI, or from Telegram (next section). The CLI commands read `state.db` only: no iCloud login, and they work with or without a config file. Pick the entry with `--for-username` (required) and `--for-library` (default `PrimarySync`).

```sh
icloudpd --list-pending-deletions --for-username you@icloud.com
icloudpd --resolve-deletions approve --for-username you@icloud.com
icloudpd --resolve-deletions reject --for-username you@icloud.com
```

With a config file, add `--config /path/to/config.yaml`. Without one, repeat the entry on the command line: `--username`, `--directory`, `--state-directory`, and `--library` if it isn't `PrimarySync`. `--for-username` and `--for-library` only select among the entries built from those.

```sh
# Personal library, no config file
icloudpd --username you@icloud.com --directory /data/you --state-directory /state/you \
  --list-pending-deletions --for-username you@icloud.com

# Shared Library entry, no config file
icloudpd --username you@icloud.com --directory /data/shared --state-directory /state/shared \
  --library SharedSync-XXXXXXXX \
  --list-pending-deletions --for-username you@icloud.com --for-library SharedSync-XXXXXXXX
```

- `approve`: the held photos are deleted at the end of the next completed sync. Approved photos bypass the threshold. If iCloud doesn't confirm a delete, the photo stays approved and is retried on the next sync. An approved photo that is no longer in iCloud is skipped.
- `reject`: the photos re-download on the next sync.
- Approve and reject apply to the whole batch, and print what they changed. Run them while no sync is writing the database; if it is busy, they say so and exit 1. They need no iCloud login and no thumbnails.

**Reviewing in Telegram.** With the [Telegram bot](./integrations/telegram-bot/README.md) and the control channel set up, a held batch produces one review message per entry. Deletions under the threshold send nothing to Telegram; only a held batch does.

- The message shows numbered thumbnails, 10 per page, with Prev/Next. Each photo has a 🗑/💾 toggle (💾 = keep). `✅ Delete N, keep M` applies; `❌ Keep all` rejects the whole batch.
- Deletes go out at the end of the next completed sync, not immediately. A kept photo re-downloads to the local library on that sync.
- Apply covers the whole held batch: every photo not marked keep, on every page, not only the page on screen. The button shows the count. If the batch or the keep marks changed since the message was drawn, nothing is deleted and the message is redrawn.
- `/held` re-sends a review message for every entry that has a held batch. There are no `/approve` or `/reject` commands: approving by command would act on photos you never saw.
- If icloudpd's iCloud session can't be used when the review opens, the message is a numbered text list (filename and date) and the buttons still work. Thumbnails return after the next successful scan login.

**Control channel.** The bot talks to icloudpd over a separate HTTP port, not the web UI. It is off unless `control_token_file` is set to a file holding a bearer token. The bot reads the same token from `ICLOUDPD_CONTROL_TOKEN_FILE` (a raw `ICLOUDPD_CONTROL_TOKEN` is rejected); without it, review in the bot is disabled.

```yaml
control_token_file: /run/secrets/icloudpd_control_token   # CLI: --control-token-file
control_port: 2012                                        # CLI: --control-port (default)
```

It binds `0.0.0.0`. Do not publish the port outside the Docker network; the token is the only protection. The bot finds it at `ICLOUDPD_CONTROL_URL` (default `http://icloudpd:2012`).

**One entry per library.** Deletion sync compares one library against one `state.db`, so each library needs its own entry with its own `directory` and `state_directory`. icloudpd refuses to start if two entries share a `state.db` and either has `sync_deletions` on. It also refuses `sync_deletions` without `require_mount_marker`, or with `recent` or `until_found`. Without `state_directory` it warns, since the record of downloads then lives in the library.

**Shared Library.** The Shared Library is its own library in icloudpd, with a name like `SharedSync-…`. Find it with `--list-libraries`, then add an entry with `library: SharedSync-…`. Deleting a shared photo moves it to Recently Deleted for every participant, and the contributor is notified. A separate copy of the same picture in another library is a different record and is not deleted.

**Dry run.** With `--dry-run`, no deletion state is written, and nothing is deleted or notified. The log says which photos would become candidates after one more scan, and what would be deleted or held, judged against what earlier real scans have marked. As before, a dry run still refreshes `last_seen_utc` in `state.db` for files it finds on disk.

**With `auto_delete`.** Photos in iCloud's Recently Deleted are forgotten from `state.db` as well as removed locally, so restoring one in iCloud re-downloads it instead of deleting it again.

**Events.** Delivered to your notification script like the other events. `data` always carries `library` and `directory`. `items` holds up to 50 entries of `{record_name, filename, asset_date}`; `total` is the full count.

| Event | When | `data` |
|---|---|---|
| `deletion_sync_threshold_tripped` | A batch was held | `held_count`, `new_count`, `threshold`, `items` (all held photos), `total` |
| `deletion_sync_summary` | At least one delete succeeded or failed | `deleted_count`, `failed_count`, `items` (the deleted photos only), `total` |

The first deletion against live iCloud, and the Telegram review, are not yet verified against live services. See [docs/deletion-sync-live-test.md](./docs/deletion-sync-live-test.md) for the manual checks.
