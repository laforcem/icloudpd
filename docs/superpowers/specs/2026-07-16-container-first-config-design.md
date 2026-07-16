# Container-First Configuration — Design

## Context

`icloudpd` today is pure `argparse` (`src/icloudpd/cli.py`), ~43 options, no env var support, no config-file support (`src/icloudpd/config.py` is plain dataclasses with no loader). Multi-account runs are expressed by repeating `-u`/`--username` boundaries in one flat argv list (`parse()` in `cli.py` splits on those boundaries and seeds each per-user `argparse.Namespace` from a shared "default" namespace parsed from the args before the first `-u`).

This is the only way to configure a Docker Compose deployment today, and it's the existing `integrations/telegram-bot/docker-compose.example.yml`'s shape:

```yaml
command:
  - "--mfa-provider"
  - "webui"
  - "--watch-with-interval"
  - "3600"
  - "--username"
  - "jdoe@icloud.com"
  - "--directory"
  - "/data"
```

A YAML list of argv strings is not a config format — it's argv with extra steps. There's no way to express "these two accounts share these settings" without repeating them, no way to distinguish process-wide settings from per-account ones except by convention, and no way to keep secrets out of it (there are none today only because auth happens to be WebUI-driven).

The goal of this design is to give `icloudpd` a real, native configuration file — not a Docker-only wrapper — so Compose (and any other deployment: bare metal, Kubernetes, etc.) has a sane, structured way to configure it. This is a change to the actual CLI/config layer of the tool, not something bolted onto the Docker image.

## Non-goals

- **Hot secret rotation.** `*_file` fields (see below) are read once at process startup. A rotated secret requires a process restart to take effect. Accepted as YAGNI: the primary auth path is WebUI (interactive), and the `parameter` password provider this would matter for isn't in active use. Revisit if/when non-interactive password auth is actually adopted.
- **Telegram bot token migration.** `integrations/telegram-bot/`'s `TELEGRAM_BOT_TOKEN` env var should eventually move to the same `*_file` convention (see Secrets below), but that's a separate codebase/PR, not part of this spec.
- **Per-account overrides of process-wide settings.** `watch_with_interval`, `mfa_provider`, `log_level`, etc. remain single values for the whole run, same as today's `GlobalConfig`. This design doesn't add per-account variants of them.
- **Multiple config file formats.** YAML only. TOML/JSON are not supported as input formats (see Format rationale).

## Config file structure

Three top-level sections, matching the existing `GlobalConfig` / `UserConfig` split in `config.py` — the YAML file is a direct serialization of that existing shape, not a new data model:

```yaml
app:                          # -> GlobalConfig. One value for the whole process, never per-account.
  log_level: info
  mfa_provider: webui
  watch_with_interval: 3600

all_users:                    # -> UserConfig defaults. Applies to every account unless a user overrides it.
  directory: /data
  size: [original, medium]
  skip_videos: true

users:                        # -> Sequence[UserConfig]. One list entry per account, self-contained.
  - username: you@icloud.com
    password_file: /run/secrets/icloud_password_you
  - username: partner@icloud.com
    password_file: /run/secrets/icloud_password_partner
    directory: /data/account2   # overrides all_users.directory for this account only
```

- `app` fields map onto `GlobalConfig` fields.
- `all_users` fields map onto `UserConfig` fields and become the defaults every entry in `users` starts from.
- Each `users` entry is one `UserConfig`, built by taking `all_users` and applying that entry's own keys on top — the same "seed from a default namespace, override per-user" logic `parse()` already does for CLI args, just expressed as a YAML merge instead of an argparse-copy-and-override.

Naming: `all_users` was chosen over shorter alternatives (`defaults`, `common`, `shared`) specifically because it directly answers "where do I set something for every account" — self-explanatory over terse.

### Format rationale

**YAML**, not TOML or JSON:

- Matches the rest of the project's config surface (Compose files, GitHub Actions) — no new format for operators to learn.
- Supports comments — the only inline documentation a user's own config file will have, since no example config file ships in the repo (see Documentation below).
- Naturally expresses the `all_users` + `users`-list-of-blocks shape.
- Known footgun (YAML 1.1 implicit-boolean coercion of unquoted `yes`/`no`/`on`/`off` — the "Norway problem") is neutralized by the loader validating every field against the `GlobalConfig`/`UserConfig` dataclass types it's building — a field YAML mis-parsed as a bool where a string was expected fails loudly at startup with a clear type error, not silently.

TOML was rejected for being an unfamiliar syntax (`[[users]]` array-of-tables) next to a YAML-only project; JSON was rejected for having no comment support at all, which matters more here given there's no separate example file.

## File location

- Default path: `/etc/icloudpd/config.yaml`. Checked automatically on startup — this is the conventional Linux location for a service's own config, and it means a fully config-driven Compose deployment needs **no `command:` args at all**, just a `configs:` mount to that path (see Compose section below).
- Override: `--config <path>` for anyone who wants a non-default location.
- Fallback: if neither the default path exists nor `--config` is given, behavior is unchanged from today (pure CLI args) — no regression for existing users.

**Code change required:** `cli.py`'s `parse()` currently special-cases zero args as `args = ["--help"]`. This must change to: zero args + config file present at the default path → load from config file, instead of showing help.

## Precedence: CLI args override the config file

Resolution order for any given setting:

1. CLI arg, if explicitly passed
2. Config file value (`users` entry, falling back to `all_users`), if present
3. Built-in default, if neither of the above set it

**Implementation cost, called out explicitly:** today's `argparse` bakes real defaults directly into `add_argument(default=...)` calls (e.g. `--library` defaults to `"PrimarySync"`). There is currently no way to distinguish "user explicitly passed `--library PrimarySync`" from "user passed nothing and got the built-in default" — both produce an identical `Namespace` value. Making CLI-overrides-config-file actually work requires:

- Moving every option's `add_argument()` to `default=None` (unset means "not passed").
- Moving the real built-in defaults out of argparse and into a separate resolution step that runs last, after config-file values have been layered in.

This touches every one of the ~43 options in `cli.py`/`config.py`. It's a genuine refactor, not a small addition — accepted because the alternative (config-file-exclusive, no CLI override) was explicitly rejected in favor of this flexibility.

## Secrets: universal `*_file` convention

**Hard rule, applies to all secrets present and future, not just these two examples:** a secret's value is never written into the config file, an env var, or a CLI arg. It is always delivered as a path to a file containing it, read once at process startup. Any future secret added to this project follows this same convention — there is no second pattern.

```yaml
users:
  - username: you@icloud.com
    password_file: /run/secrets/icloud_password_you
```

This is not a Docker-specific mechanism — it's the same convention behind `POSTGRES_PASSWORD_FILE`/`MYSQL_ROOT_PASSWORD_FILE` and Vault Agent's file injection, and it composes with whatever the deployment environment happens to be:

- **Docker Compose**: a `secrets:` block sourced from `file:` or `environment:`, mounted at `/run/secrets/<name>` by default.
- **Kubernetes**: a Secret mounted as a volume (backed by `tmpfs`, permission-controlled via `defaultMode`, and — unlike env-var-injected Secrets — updated on disk without a Pod restart when the underlying Secret changes; the app just won't see that update until *it* restarts, since it reads the file once at startup, per Non-goals above).
- **Bitwarden Secrets Manager** (if ever adopted, e.g. in a k3s setup): its Kubernetes Operator syncs into a normal K8s `Secret` object via a `BitwardenSecret` CRD — indistinguishable from any hand-created Secret once synced, so it plugs into the same volume-mount path with zero icloudpd-specific work.

**Security note for plain (non-Swarm) Compose, to document rather than gloss over:** Compose's `secrets:` block with a `file:` source is implemented as a plain bind-mount (per the Compose spec reference) — not `tmpfs`, not encrypted at rest. Real encryption-at-rest (secret stored encrypted in Raft logs, decrypted only into memory on the node running the task) is a Swarm-mode-only property. Plain Compose only gets you "not visible via `docker inspect`/process listing" — the secret file is plaintext on host disk the whole time. Hardening this is host/ops work, not something this design or Compose provides:
  - Host-side file permissions (`chmod 600` file, `chmod 700` directory), not Docker.
  - `.gitignore` the secrets directory outright.
  - Optional: encrypt the files at rest with SOPS + `age`/GPG, decrypting to plaintext only transiently, right before `docker compose up`, so nothing unencrypted ever lands in git or backups.
  - Full-disk encryption (LUKS) on the host as defense-in-depth, orthogonal to Docker.

## Debugging: `--print-config`

Prints the fully resolved configuration (CLI args + config file + built-in defaults, merged per the precedence rules above) as YAML, then exits. Lets you verify what a container actually resolved to without guessing at layered precedence by hand — particularly useful while this feature is new and config resolution bugs would otherwise only surface as confusing runtime behavior.

## Documentation

No example config file ships in the repo. All available keys are documented in the README (or a dedicated docs page); `--print-config` covers "what did this actually resolve to" at runtime, which a static example file can't show anyway (it can't reflect CLI-arg overrides).

## Example: two-account Compose deployment

```yaml
# compose.yaml
services:
  icloudpd:
    image: icloudpd/icloudpd:latest
    configs:
      - source: icloudpd_config
        target: /etc/icloudpd/config.yaml
    secrets:
      - icloud_password_you
      - icloud_password_partner
    volumes:
      - ./data:/data

configs:
  icloudpd_config:
    file: ./icloudpd-config.yaml

secrets:
  icloud_password_you:
    file: ./secrets/you.txt
  icloud_password_partner:
    file: ./secrets/partner.txt
```

```yaml
# icloudpd-config.yaml — not a secret, safe to commit
app:
  mfa_provider: webui
  watch_with_interval: 3600

all_users:
  directory: /data

users:
  - username: you@icloud.com
    password_file: /run/secrets/icloud_password_you
  - username: partner@icloud.com
    password_file: /run/secrets/icloud_password_partner
```

Only `./secrets/you.txt` and `./secrets/partner.txt` need host-level protection (permissions, `.gitignore`, optional SOPS encryption) — `compose.yaml` and `icloudpd-config.yaml` are ordinary, committable files.

## Testing

- `config.py`/`cli.py`: unit tests for YAML loading against the three-section structure, `all_users` → per-user override merging, `*_file` resolution (read-once-at-startup), and the CLI-args-override-config-file precedence chain (including the argparse `default=None` refactor not silently breaking existing CLI-only invocations).
- `--config` path resolution: explicit flag, default path found, neither present (fallback to pure CLI behavior) — three cases.
- `--print-config`: output reflects all three precedence layers correctly merged.
- Malformed config file (wrong type for a field, unknown key, missing required field like `username`): fails at startup with a clear error, not a silent misconfiguration.

## Open questions

None blocking. Telegram bot token migration to `*_file` (Non-goals) is a natural follow-on once this lands, tracked separately.
