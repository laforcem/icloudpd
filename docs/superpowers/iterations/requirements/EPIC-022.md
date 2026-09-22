# EPIC-022 — Config schema

**Summary:** Config schema
**Stories:** STORY-0045, STORY-0046, STORY-0047, STORY-0048, STORY-0049, STORY-0050, STORY-0051, STORY-0052, STORY-0053, STORY-0054, STORY-0055, STORY-0056, STORY-0057, STORY-0058, STORY-0059
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/15 done

## STORY-0045

**Epic:** EPIC-022 — Config schema
**Title:** Structure config as one global block plus a list of accounts

**As a** operator
**I want** the YAML config to have a top-level `global` block (process-wide settings) and a top-level `accounts` list, each account grouped by function
**So that** process-wide and per-account settings are unambiguously separated

**Acceptance criteria:**
- AC-1: A valid config file has exactly one `global` key and one `accounts` key at the top level; `accounts` is a list where each element carries its own credentials, sync_scope, file_layout, deletion_sync, schedule, session_expiry, and dry_run settings. · impact:`local` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0046

**Epic:** EPIC-022 — Config schema
**Title:** Keep the health/metrics listener always on and network-reachable

**As a** operator
**I want** the health/metrics HTTP listener to bind 0.0.0.0:9090 by default and run independently of whether the dashboard is enabled
**So that** Prometheus scraping from another pod and K8s liveness/readiness probes both work, without exposing credentials, account names, or status data

**Acceptance criteria:**
- AC-1: The health/metrics listener starts and serves on global.health.bind:global.health.port regardless of the value of global.dashboard.enabled. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0032`
- AC-2: The default global.health.bind value is 0.0.0.0 (not loopback-only), unlike the dashboard's default bind. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0032`
- AC-3: Responses from the health/metrics listener contain only healthy/unhealthy status and counters — no credentials, account names, or other status data. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0032`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0047

**Epic:** EPIC-022 — Config schema
**Title:** Default the dashboard to disabled and loopback-only

**As a** operator
**I want** global.dashboard.enabled to default to false and global.dashboard.bind to default to 127.0.0.1
**So that** the dashboard is not exposed to the network by default and is not part of the MVP surface

**Acceptance criteria:**
- AC-1: With no dashboard config supplied, the dashboard does not start (enabled defaults to false). · impact:`local` · seam:`integration` · scenario:`SCENARIO-0032`
- AC-2: When the dashboard is enabled without an explicit bind override, it listens only on 127.0.0.1, not on 0.0.0.0. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0032`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0048

**Epic:** EPIC-022 — Config schema
**Title:** Reject Telegram configuration with an empty allowed_chat_ids list

**As a** operator
**I want** config validation to refuse to start when global.telegram is configured but allowed_chat_ids is empty
**So that** a misconfigured bot cannot be left open to accept commands from any chat

**Acceptance criteria:**
- AC-1: If global.telegram.bot_token_file is set and global.telegram.allowed_chat_ids is an empty list, validate refuses to start the process with a validation error. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0033`
- AC-2: allowed_chat_ids is plain config (not secret-backed), while bot_token_file is secret-backed via a file path. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0049

**Epic:** EPIC-022 — Config schema
**Title:** Treat the webhook URL as a secret and retry deliveries

**As a** operator
**I want** global.webhook_notifier.url_file to be a secret-backed file reference, and webhook deliveries to retry 3 times with exponential backoff
**So that** an auth token embedded in the webhook URL is never stored in plain config, and transient delivery failures are tolerated

**Acceptance criteria:**
- AC-1: The webhook notifier reads its URL from a file path (url_file), the same secret-backed mechanism used for other credentials, not from a plain inline config value. · impact:`local` · seam:`unit`
- AC-2: A failed webhook delivery is retried up to 3 times with exponential backoff before being abandoned. · impact:`cross-surface` · seam:`integration`
- AC-3: Webhook payloads use the {event, account, timestamp, data} envelope shape. · impact:`local` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0050

**Epic:** EPIC-022 — Config schema
**Title:** Address accounts by a required, unique, non-secret name

**As a** operator
**I want** each account to have a required unique `name` field used in Telegram commands, the manifest's account_id, and dashboard display
**So that** the secret-backed apple_id is never typed into Telegram or displayed

**Acceptance criteria:**
- AC-1: Config validation rejects an accounts list containing a missing name or a name that duplicates another account's name. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0034`
- AC-2: Telegram commands that target an account (e.g. /sync <account>) resolve by the account's `name` field; the apple_id is never accepted or displayed as an account identifier in Telegram or the dashboard. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0034`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0051

**Epic:** EPIC-022 — Config schema
**Title:** Resolve credentials through a file -> env -> cache chain, including apple_id

**As a** operator
**I want** each account's apple_id and password to be resolvable from a file, an env var, or a cache, in that order
**So that** the same credential model applies uniformly to apple_id as it already does to password

**Acceptance criteria:**
- AC-1: credentials.apple_id_env (e.g. ICLOUDPD_APPLE_ID) is accepted as a valid schema field and participates in the file->env->cache resolution chain for the apple_id, matching the existing password_file/password_env pattern. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0036`
- AC-2: When apple_id_file is absent but apple_id_env is set and present in the process environment, credential resolution succeeds using the env value. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0036`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0052

**Epic:** EPIC-022 — Config schema
**Title:** Select asset types via an opt-in array, not opt-out skip flags

**As a** operator
**I want** sync_scope.asset_types to be an opt-in array (e.g. [photos, live_photos, videos])
**So that** the set of synced asset types is explicit rather than expressed as negative skip_* flags

**Acceptance criteria:**
- AC-1: Only asset types listed in sync_scope.asset_types are synced for that account; omitting a type from the array excludes it. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0037`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0053

**Epic:** EPIC-022 — Config schema
**Title:** Do not offer date-scoped or early-stop sync flags

**As a** engine developer
**I want** the config schema to omit recent, until_found, skip_created_before, and skip_created_after entirely
**So that** no sync run can self-report Exhaustive:true while silently skipping in-scope photos, which would make real photos indistinguishable from deleted ones to deletion-sync's reconciliation logic

**Acceptance criteria:**
- AC-1: The account sync_scope schema has no recent, until_found, skip_created_before, or skip_created_after keys; a config file supplying any of these under sync_scope does not enable date-scoped or early-stop behavior. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0038`
- AC-2: Every v1 sync run is full-sweep-only with respect to date/time-range scoping: no combination of config keys causes a full sweep to skip assets by creation date while still reporting Exhaustive:true. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0038`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0054

**Epic:** EPIC-022 — Config schema
**Title:** Gate deletion mirroring on a master switch with an unbounded-by-default cumulative threshold

**As a** operator
**I want** deletion_sync.enabled to fully disable detection/action when false, and deletion_sync.threshold to use rclone --max-delete semantics (-1 = unbounded, N = withhold for review once cumulative unresolved missing count reaches N)
**So that** deletion mirroring is opt-in and, once on, does not silently run unbounded unless explicitly configured that way

**Acceptance criteria:**
- AC-1: When deletion_sync.enabled is false, no deletion candidates are detected or acted on, regardless of the threshold value. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0039`
- AC-2: When deletion_sync.enabled is true and threshold is -1, deletion mirroring proceeds with no cap on the number of deletions. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0039`
- AC-3: When deletion_sync.enabled is true and threshold is N (N >= 0), the batch is withheld for review once the CUMULATIVE unresolved missing count across runs reaches N — not merely the count within a single run. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0039`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0055

**Epic:** EPIC-022 — Config schema
**Title:** Require an explicit per-account schedule with no implicit default

**As a** operator
**I want** config validation to reject an account entry that omits `schedule`
**So that** no account silently runs on an unintended default cron schedule

**Acceptance criteria:**
- AC-1: An account entry with no `schedule` key fails config validation; validate does not substitute a default cron expression. · impact:`journey` · seam:`process-level` · scenario:`SCENARIO-0041`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0056

**Epic:** EPIC-022 — Config schema
**Title:** Merge only_print_filenames into dry_run

**As a** operator
**I want** a single dry_run boolean per account that also covers the old only_print_filenames behavior
**So that** there is one config surface for a no-op preview run instead of two overlapping flags

**Acceptance criteria:**
- AC-1: The config schema has no only_print_filenames key; setting dry_run:true is the sole mechanism to preview a run without downloading or mutating the manifest. · impact:`local` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0057

**Epic:** EPIC-022 — Config schema
**Title:** Keep one-shot diagnostics as CLI flags, not persistent config

**As a** operator
**I want** auth-only, list-albums, and list-libraries to be invoked as CLI flags rather than YAML config keys
**So that** one-shot diagnostic actions are not confused with persistent per-account configuration

**Acceptance criteria:**
- AC-1: The YAML config schema has no auth-only, list-albums, or list-libraries keys; these are only available as CLI invocation flags. · impact:`local` · seam:`process-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

**Status:** pending

## STORY-0058

**Epic:** EPIC-022 — Config schema
**Title:** Support China data-residency accounts via domain config

**As a** operator with an Apple ID registered in mainland China
**I want** an account-level domain field selecting com or cn
**So that** requests route to Apple's China data-residency endpoints instead of the default global endpoints

**Acceptance criteria:**
- AC-1: Each account's credentials.domain field accepts exactly com or cn; when set to cn, auth and CloudKit requests target Apple's China data-residency endpoints instead of the default. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0105`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:189`

**Status:** pending

## STORY-0059

**Epic:** EPIC-022 — Config schema
**Title:** Default the dashboard's listening port to 2011

**As a** operator
**I want** the optional dashboard to default to port 2011 when enabled
**So that** the documented sample config's port matches the service's actual default

**Acceptance criteria:**
- AC-1: When dashboard.enabled is true and dashboard.port is unset, the dashboard listens on port 2011. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0110`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:165`

**Status:** pending