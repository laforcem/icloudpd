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

If `state_directory` is set and the database can't be opened there, that user's run fails rather than continuing without it.

**Migrating an existing install:**

1. Stop the container.
2. Copy `<directory>/.icloudpd/state.db` to `<state_directory>/state.db`.
3. Set `state_directory` and start the container.

If you skip the copy, icloudpd logs a warning on startup that points at the old file, then creates a fresh empty database. Nothing at runtime reads the old records back (the manifest is only written to while downloading), so no downloaded file is touched or re-downloaded. The new database fills in again on the next scan, including files already on disk; the only thing lost is the original first-downloaded timestamps.

### `require_mount_marker`

If the mount drops, `directory` becomes an empty local folder, and icloudpd would happily download into your host's own disk. With `require_mount_marker: true` (CLI: `--require-mount-marker`), icloudpd checks that the file `<directory>/.mounted` exists before each run, and skips that user if it doesn't. Create the marker once, on the mounted library: `touch /data/you/.mounted`.

When the marker is missing, icloudpd logs an error, writes nothing under `directory`, and in watch mode tries again on the next cycle. Without watch mode it exits non-zero. The check is skipped for `--auth-only` and the list commands, which don't touch the library.

Alerts go through your notification script (or the bundled Telegram bot): one `library_mount_missing` alert the first time the mount goes missing, and one `library_mount_restored` alert when it returns. With the Telegram bot, the missing-mount alert has a **Check again now** button that ends the current watch-mode wait early, so you can remount and re-check without waiting out the interval.
