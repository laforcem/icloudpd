# This fork is a major work-in-progress.
I plan to add more robust documentation ASAP as fixes and functionality changes come in. The below README is pre-fork and may not reflect the state of the repo right now.

# iCloud Photos Downloader [![Quality Checks](https://github.com/icloud-photos-downloader/icloud_photos_downloader/workflows/Quality%20Checks/badge.svg)](https://github.com/icloud-photos-downloader/icloud_photos_downloader/actions/workflows/quality-checks.yml) [![Build and Package](https://github.com/icloud-photos-downloader/icloud_photos_downloader/workflows/Produce%20Artifacts/badge.svg)](https://github.com/icloud-photos-downloader/icloud_photos_downloader/actions/workflows/produce-artifacts.yml) [![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

- A command-line tool to download all your iCloud photos.
- Works on Linux, Windows, and macOS; laptop, desktop, and NAS
- Available as an executable for direct downloading and through package managers/ecosystems ([Docker](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html#docker), [PyPI](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html#pypi), [AUR](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html#aur), [npm](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html#npm))
- Developed and maintained by volunteers (we are always looking for [help](CONTRIBUTING.md)). 

See [Documentation](https://icloud-photos-downloader.github.io/icloud_photos_downloader/) for more details. Also, check [Issues](https://github.com/icloud-photos-downloader/icloud_photos_downloader/issues)

We aim to release new versions once a week (Friday), if there is something worth delivering.

## iCloud Prerequisites

To make iCloud Photo Downloader work, ensure the iCloud account is configured with the following settings, otherwise Apple Servers will return an ACCESS_DENIED error:

- **Enable Access iCloud Data on the Web:** On your iPhone / iPad, enable `Settings > Apple ID > iCloud > Access iCloud Data on the Web`
- **Disable Advanced Data Protection:** On your iPhone /iPad disable `Settings > Apple ID > iCloud > Advanced Data Protection`


## Install and Run

There are three ways to run `icloudpd`:
1. Download executable for your platform from the GitHub [Release](https://github.com/icloud-photos-downloader/icloud_photos_downloader/releases/tag/v1.32.3) and run it
1. Use package manager to install, update, and, in some cases, run ([Docker](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html#docker), [PyPI](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html#pypi), [AUR](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html#aur), [npm](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html#npm))
1. Build and run from the source

See [Documentation](https://icloud-photos-downloader.github.io/icloud_photos_downloader/install.html) for more details

## Features

<!-- start features -->

- Three modes of operation:
  - **Copy** - download new photos from iCloud (default mode)
  - **Sync** - download new photos from iCloud and delete local files that were removed in iCloud (`--auto-delete` option)
  - **Move** - download new photos from iCloud and delete photos in iCloud (`--keep-icloud-recent-days` option)
- Support for Live Photos (image and video as separate files) and RAW images (including RAW+JPEG)
- Automatic de-duplication of photos with the same name
- One time download and an option to monitor for iCloud changes continuously (`--watch-with-interval` option)
- Optimizations for incremental runs (`--until-found` and `--recent` options)
- Photo metadata (EXIF) updates (`--set-exif-datetime` option)
- ... and many more (use `--help` option to get full list)

<!-- end features -->

## Experimental Mode

Some changes are added to the experimental mode before they graduate into the main package. [Details](EXPERIMENTAL.md)

## Usage

To keep your iCloud photo collection synchronized to your local system:

```
icloudpd --directory /data --username my@email.address --watch-with-interval 3600
```

> [!IMPORTANT]
> It is `icloudpd`, not `icloud` executable

> [!TIP]
> Synchronization logic can be adjusted with command-line parameters. Run `icloudpd --help` to get full list.

To independently create and authorize a session (and complete 2SA/2FA validation if needed) on your local system:

```
icloudpd --username my@email.address --password my_password --auth-only
```
> [!TIP]
> This feature can also be used to check and verify that the session is still authenticated. 

## Configuration File

Instead of long command lines, `icloudpd` can be configured with a YAML file. By default it looks for `/etc/icloudpd/config.yaml`; use `--config <path>` to point at a different file. If neither is present, `icloudpd` behaves exactly as it does with plain CLI arguments.

```yaml
app:                          # process-wide settings — one value for the whole run
  mfa_provider: webui
  watch_with_interval: 3600

all_users:                    # applies to every account below, unless overridden
  directory: /data

users:                        # one block per account
  - username: you@icloud.com
  - username: partner@icloud.com
    directory: /data/account2   # overrides all_users.directory for this account only
    password_file: /run/secrets/icloud_password_partner
```

Any setting also given as a CLI arg overrides the config file for that run (e.g. `icloudpd --config /etc/icloudpd/config.yaml --dry-run`). When multiple accounts are defined in the file, a CLI override applies uniformly to all of them — there's no way to target just one account via a CLI flag; use the file's per-account block for that. If a config file is in use, per-account CLI arguments (`-u`/`--username`) are not supported — define accounts in the file's `users:` list instead.

**Secrets** are never written into this file directly. Any secret (currently: the account password, via `password_file`) is a path to a separate file containing the value, read once at startup — the same convention Docker/Kubernetes/Compose secrets and images like `postgres`'s `POSTGRES_PASSWORD_FILE` use. A literal `password:` key in the config file is rejected at startup.

Run `icloudpd --config <path> --print-config` to see the fully resolved configuration (config file + any CLI overrides + built-in defaults, merged) without guessing at precedence by hand.

See `docker-compose.example.yml` for a full Docker Compose deployment using this file, including how to source `password_file` from Compose's `secrets:` block.

## Contributing

Want to contribute to iCloud Photos Downloader? Awesome! Check out the [contributing guidelines](CONTRIBUTING.md) to get involved.
