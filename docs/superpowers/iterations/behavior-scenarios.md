# Behavior Scenarios

## Journey Scenarios

## JOURNEY-0001 — ITER-0000 walking skeleton threads every layer at minimum depth

**Kind:** journey
**Proof seam:** e2e
**Owning stories:** STORY-0135

**Preconditions:**
- A fresh checkout of the Go rewrite with a valid iCloud account credential available
- state_dir configured and empty

**Steps:**
1. Authenticate against iCloud using SRP auth
   → Authentication succeeds and a session is established
2. List exactly one asset via the Enumerator
   → Enumerator returns a single asset without error
3. Download that asset
   → The asset file is written to the download root
4. Record the download in the manifest
   → A manifest row exists for the asset
5. Exit the process
   → The process exits cleanly with a zero/success status

**Final observables:**
- One asset exists on disk
- One manifest row exists for that asset
- Process exited clean
- No component (auth, Enumerator, download, manifest, app) required stubbing to complete the run

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:365-368`

## JOURNEY-0002 — run-once is idempotent against the manifest

**Kind:** journey
**Proof seam:** e2e
**Owning stories:** STORY-0116

**Preconditions:**
- A real iCloud account with at least one asset
- Empty manifest and download root

**Steps:**
1. Run `icloudpd run-once`
   → Assets are downloaded
   → Manifest rows are written
   → XMP sidecars are generated
2. Run `icloudpd run-once` again with no changes on the iCloud side
   → No assets are downloaded

**Final observables:**
- Manifest contains one row per asset after the first run
- Second run performs zero downloads

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:382`

## Surface Scenarios

## SCENARIO-0001 — Folder-structure change does not trigger re-download

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0003

**Preconditions:**
- An account has already synced with a manifest recording assets by iCloud record name
- folder_structure config is changed to a different date-format pattern

**Action:**
- Re-run sync for the account with the new folder_structure

**Expected observables:**
- Manifest lookup by record name finds each existing asset
- No network download request is made for assets already present
- Files exist under the new folder layout without duplicate downloads
- Manifest entries reflect the new path while retaining original record-name identity

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:10-13,33`

## SCENARIO-0002 — Webhook notifier retries then drops on persistent failure

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0004

**Preconditions:**
- A webhook notifier is configured pointing at an endpoint that always returns 500

**Action:**
- An event is dispatched to the notifier
- All retries are exhausted

**Expected observables:**
- The notifier attempts delivery
- On failure it retries up to 3 times with exponential backoff
- The event is logged as dropped
- No further retry is attempted for this event
- Event delivery outcome is recorded in logs as dropped after 3 retries

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:112-113`

## SCENARIO-0003 — Deletion batch requires Telegram approval before submission to Apple

**Kind:** surface
**Proof seam:** app-level
**Owning stories:** STORY-0006, STORY-0007

**Preconditions:**
- Local deletions have been detected and exceed the configured threshold, forming a pending batch

**Action:**
- The bot posts paginated live thumbnail photo messages for the pending batch to an allowed chat
- An allowed chat sends /approve for the batch
- The mirror submits the approved batch

**Expected observables:**
- Thumbnails are fetched live and never written to local disk
- No submission to iCloud has occurred yet
- The batch's approval state transitions to approved
- Assets move to iCloud Recently Deleted
- The submission does not occur before approval was recorded
- Batch state is approved and submitted
- No thumbnail files exist on local disk from the review process

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:36,62,97-98`

## SCENARIO-0004 — Routine 2FA expiry prompts only for a code, never a password

**Kind:** surface
**Proof seam:** app-level
**Owning stories:** STORY-0008

**Preconditions:**
- An account's session has expired in a way Apple resolves via 2FA/2SA

**Action:**
- The sync engine attempts to refresh the session and receives a 2FA/2SA-required result

**Expected observables:**
- A Telegram prompt for a code is sent
- No password re-prompt notification is sent
- Only a code-request message exists in the chat for this event

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:37,44-47`

## SCENARIO-0005 — Confirmed wrong password notifies without accepting a reply

**Kind:** failure-recovery
**Proof seam:** app-level
**Owning stories:** STORY-0024

**Preconditions:**
- An account's watched password file contains an incorrect value
- Apple's auth API returns a confirmed failed-login result

**Action:**
- The sync engine attempts auth and receives the confirmed wrong-password result
- The next scheduled run occurs with the password file still uncorrected
- The operator corrects the watched password file out of band

**Expected observables:**
- A Telegram notification is sent stating the password file is wrong
- No inline-reply mechanism is offered or accepted for this notification
- Auth fails again identically
- No cached or alternate value allows the run to succeed
- The next auth attempt succeeds
- Account run fails until the file is corrected; succeeds immediately after correction

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:48-49`

## SCENARIO-0006 — Two accounts request 2FA codes simultaneously in the same chat

**Kind:** surface
**Proof seam:** app-level
**Owning stories:** STORY-0023

**Preconditions:**
- Accounts A and B both require a 2FA code at the same time
- Both are notified in the same allowed Telegram chat

**Action:**
- The bot sends separate prompt messages for account A and account B
- The operator replies to account A's prompt message with a code
- The operator replies to account B's prompt message with a different code

**Expected observables:**
- Two distinct prompt messages exist, one per account
- The code is applied to account A's pending auth, not account B's
- The code is applied to account B's pending auth
- Account A and account B each complete auth with their own correctly attributed code
- No account-name typing was required to disambiguate

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:47`

## SCENARIO-0007 — Validate refuses config missing schedule for an account

**Kind:** contract
**Proof seam:** process-level
**Owning stories:** STORY-0015

**Preconditions:**
- A config file defines an account with no `schedule` field

**Action:**
- Run `icloudpd validate` against the config

**Expected observables:**
- The command exits non-zero
- The error identifies the missing schedule field
- No default schedule was silently applied; validation failed

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:40`

## SCENARIO-0008 — Manual /sync trigger runs immediately outside the schedule

**Kind:** surface
**Proof seam:** app-level
**Owning stories:** STORY-0015

**Preconditions:**
- An account is configured with a nightly cron schedule and is not currently due to run

**Action:**
- An allowed chat sends `/sync <account>`

**Expected observables:**
- A sync run for that account starts immediately, independent of the cron schedule
- A sync run for the account completes outside its normal scheduled window

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:40`

## SCENARIO-0009 — One hung account does not starve others or flip readiness

**Kind:** failure-recovery
**Proof seam:** app-level
**Owning stories:** STORY-0016, STORY-0017

**Preconditions:**
- Three accounts are configured
- One account's upstream call hangs indefinitely

**Action:**
- All three accounts' scheduled runs fire
- Query /readyz while the one account is still hung

**Expected observables:**
- The two healthy accounts complete their sync runs normally
- The hung account remains in progress without blocking the others' goroutines
- /readyz reports ready, since not all accounts are failing
- Two accounts show successful completion
- /readyz remains ready with one account hung

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:14,42,101`

## SCENARIO-0010 — All accounts failing flips readiness to not-ready

**Kind:** failure-recovery
**Proof seam:** app-level
**Owning stories:** STORY-0017

**Preconditions:**
- Multiple accounts are configured
- Every account's auth or sync is currently failing

**Action:**
- Query /readyz

**Expected observables:**
- /readyz reports not-ready
- /readyz returns a not-ready status while total failure persists

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:42`

## SCENARIO-0011 — Global rate limiter caps total request rate regardless of account count

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0016

**Preconditions:**
- Rate limit configured at default 2 req/s
- Four accounts are running concurrently, each wanting to issue API calls

**Action:**
- All four accounts issue API calls concurrently

**Expected observables:**
- The combined observed request rate across all accounts does not exceed 2 req/s absent config override
- Aggregate API call rate stays at or below the configured global limit

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:41,101`

## SCENARIO-0012 — Graceful shutdown allows a download to resume rather than restart

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0017, STORY-0019

**Preconditions:**
- A large asset download is partway complete when a shutdown signal is received

**Action:**
- The process receives SIGTERM mid-download
- The service restarts and re-runs sync for that account

**Expected observables:**
- The download is cancelled cleanly via context, leaving a partial temp file
- The download resumes via ranged request from the partial byte offset rather than starting over
- The completed file's checksum matches Apple's fileChecksum
- Bytes already downloaded before shutdown were not re-fetched

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:42,94`

## SCENARIO-0013 — Checksum mismatch is treated as a failed download

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0019

**Preconditions:**
- A download completes but the resulting bytes' checksum does not match Apple's fileChecksum for that asset version

**Action:**
- The download integrity check runs after the file is fully written

**Expected observables:**
- The mismatch is detected
- The asset is marked failed/not recorded as successfully downloaded in the manifest
- The asset is retried on a subsequent run rather than being treated as complete

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:94`

## SCENARIO-0014 — Rotated secret file is picked up live without restart

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0021

**Preconditions:**
- A secret (e.g. apple password) is delivered via a watched file, and the service is running

**Action:**
- An external rotation process (Docker secrets/K8s volume update) replaces the watched file's content
- The next credential resolution occurs

**Expected observables:**
- fsnotify detects the change
- The new value is used without restarting the process
- Subsequent auth attempts use the rotated value

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:43`

## SCENARIO-0015 — Credential source chain falls back from file to env to memory cache

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0022

**Preconditions:**
- A prior successful auth has populated the in-memory last-known-good cache for an account's password

**Action:**
- The watched password file is temporarily missing and no env var is set
- Auth is attempted using the cached value

**Expected observables:**
- Credential resolution falls back to the in-memory cached value
- Auth succeeds using the cached credential
- No error is raised solely due to the missing file, given a valid cached value exists

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:44-45`

## SCENARIO-0016 — Proactive 2FA refresh succeeds without an on-disk password within same process lifetime

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0026

**Preconditions:**
- An account authenticated successfully earlier in this process's lifetime, populating the memory cache
- No password file is present on disk

**Action:**
- A proactive session/2FA refresh cycle runs

**Expected observables:**
- The refresh completes using the in-memory cached credential
- No read of a password file is required or attempted
- Session remains valid without any on-disk password ever having existed for this refresh

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:57`

## SCENARIO-0017 — Process restart between auth and refresh requires a fresh 2FA prompt

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0026

**Preconditions:**
- An account authenticated successfully, populating the memory cache
- The process is then restarted before the next 2FA refresh cycle

**Action:**
- The restarted process attempts a proactive 2FA refresh

**Expected observables:**
- The memory cache is empty
- A fresh 2FA prompt is sent via Telegram rather than the refresh completing silently
- A new 2FA code request is issued to the operator following the restart

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:57`

## SCENARIO-0018 — Validate refuses missing Telegram bot token

**Kind:** contract
**Proof seam:** process-level
**Owning stories:** STORY-0025

**Preconditions:**
- A config file has no telegram.bot_token_file set

**Action:**
- Run `icloudpd validate`

**Expected observables:**
- The command exits non-zero with an error naming the missing telegram.bot_token_file
- Startup is refused before any account processing begins

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:51`

## SCENARIO-0019 — Validate refuses Telegram configured with empty allowed_chat_ids

**Kind:** contract
**Proof seam:** process-level
**Owning stories:** STORY-0029

**Preconditions:**
- telegram.bot_token_file is set
- allowed_chat_ids is an empty list

**Action:**
- Run `icloudpd validate`

**Expected observables:**
- The command exits non-zero with an error naming the empty allowed_chat_ids
- Startup is refused; no ambiguous allow/deny-all state is left running

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:56`

## SCENARIO-0020 — Any allowed chat can control any account

**Kind:** surface
**Proof seam:** app-level
**Owning stories:** STORY-0028

**Preconditions:**
- allowed_chat_ids contains a chat ID
- Two accounts, X and Y, are configured

**Action:**
- The allowed chat sends /force_reauth for account X, then for account Y

**Expected observables:**
- Both commands are accepted and act on their respective account
- Neither is rejected for lacking account-specific authorization
- Both account X and account Y show a forced re-auth was triggered

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:52`

## SCENARIO-0021 — Container starts serve by default; validate/print-config/run-once operate independently

**Kind:** surface
**Proof seam:** process-level
**Owning stories:** STORY-0030

**Preconditions:**
- A valid config is present

**Action:**
- Start the container image with no explicit command
- Run the binary with `run-once` against an account
- Run the binary with `print-config`

**Expected observables:**
- The `serve` subcommand runs, starting the always-on scheduler and health listener
- A single sync pass executes and the process exits rather than staying resident
- The effective config is printed with secrets redacted, not in plaintext
- Each subcommand's process lifecycle matches its stated behavior (long-running vs one-shot)

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:58-60,102`

## SCENARIO-0022 — Fresh manifest is rebuilt by scanning disk on first run against existing library

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0031

**Preconditions:**
- A directory of previously downloaded photo files exists with no Go-version manifest or Python-version state present

**Action:**
- Run the Go service's first sync for that library path

**Expected observables:**
- internal/scan performs a filesystem backfill
- Existing files are reconciled into a newly built manifest without re-downloading unchanged assets that can be identified
- A manifest exists reflecting the scanned files
- No Python-version cookie or manifest file was read

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:60-61,103`

## SCENARIO-0023 — Delta run cannot mass-prune the manifest when it lacks removal signal

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0034

**Preconditions:**
- An account manifest contains N previously-seen assets from a prior full run.
- The configured enumerator for this run reports Capabilities{ReportsRemovals:false, Exhaustive:false, Resumable:true} (a delta run) and its change stream omits most of the previously-seen assets.

**Action:**
- Run the engine's enumeration + reconciliation cycle for the account using the delta enumerator

**Expected observables:**
- The run completes without error
- No Removed changes are emitted by the enumerator
- None of the previously-seen assets missing from this run's stream are marked removed_remote_utc in the manifest
- The manifest asset count for the account is unchanged by this run

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:121-143`

## SCENARIO-0024 — Full sweep marks unseen assets removed only on clean completion

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0034

**Preconditions:**
- An account manifest contains an asset X from a prior run.
- The configured enumerator reports Capabilities{ReportsRemovals:false, Exhaustive:true, Resumable:true} (a full run).

**Action:**
- Run a full enumeration that does not visit asset X and completes without error
- Run a second full enumeration that does not visit asset X but errors out partway through

**Expected observables:**
- Asset X is not present in this run's change stream
- The run reports an error and does not complete
- After the first (clean) run, asset X is marked removed in the manifest
- After the second (errored) run, asset X's removal status is unchanged from before that run — it is not marked removed

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:121-143`

## SCENARIO-0025 — Composite enumerator runs delta and nightly full through the same engine path

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0035

**Preconditions:**
- A composite enumerator is configured to run delta every 60s and a full sweep nightly for an account.

**Action:**
- Trigger a delta cycle at the 60s interval
- Trigger the nightly full sweep

**Expected observables:**
- The engine processes the resulting Change stream via the standard Enumerate/reconcile path
- The engine processes the resulting Change stream via the same standard path, with Exhaustive-based reconciliation applied
- No engine code path differs between the composite's delta phase and its full phase beyond what Capabilities() reports

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:121-143`

## SCENARIO-0026 — Re-visiting assets after server index drift causes no duplicate manifest rows

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0036

**Preconditions:**
- An enumeration is paged using {startRank, expected_count} state.
- The remote server-side index shifts (an insertion or reorder) between two page fetches, causing some assets to appear twice across pages.

**Action:**
- Continue enumeration across the drifted pages, yielding duplicate Change entries for the same asset.Key

**Expected observables:**
- The store receives multiple writes for the same asset.Key
- The assets table contains exactly one row for the re-visited asset.Key, not a duplicate
- No asset is skipped as a result of the index drift

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:121-143`

## SCENARIO-0027 — A store write failure aborts the account run while telemetry failures do not

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0038

**Preconditions:**
- An account run is in progress and has begun writing to the manifest store.

**Action:**
- Inject a store write failure (e.g. simulated disk error) during the run
- In a separate run, inject a telemetry write failure only

**Expected observables:**
- The run terminates immediately with a fatal error for that account
- The download loop for that account does not continue past the failure
- The run continues and completes normally
- The first run's status is recorded as failed/fatal for the account
- The second run's status is recorded as successful despite the telemetry failure

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:145-147`

## SCENARIO-0028 — Switching an account from full to delta strategy preserves independent cursors

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0039

**Preconditions:**
- An account has been running with the `full` enumerator and has an existing cursor row keyed (account, 'full').

**Action:**
- Reconfigure the account to use the `delta` enumerator and run it
- Switch the account back to `full`

**Expected observables:**
- The delta run finds no existing cursor for (account, 'delta') and starts from scratch
- The full enumerator resumes from its previously stored (account, 'full') cursor
- The (account, 'full') cursor row is unmodified by the delta run
- A new (account, 'delta') cursor row exists independently

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:145-147`

## SCENARIO-0029 — Manifest survives a download-root remount via relative paths

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0042

**Preconditions:**
- An account's files table has rows with rel_path values relative to an original download root mounted at /data.
- The download volume is remounted at a new absolute path, e.g. /data2, with the same directory contents.

**Action:**
- Run a sync cycle after the remount

**Expected observables:**
- The engine resolves each files row's on-disk location as account_download_root + rel_path using the new root
- No files rows are treated as missing solely because of the remount
- No manifest rows are orphaned by the change in absolute mount path

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:149-157`

## SCENARIO-0030 — Live Photo companion missing does not trigger deletion while the primary file remains

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0043

**Preconditions:**
- An asset has two files rows: role=primary (present on disk) and role=live_photo_video (missing on disk since the previous run).

**Action:**
- Run the deletion-candidate query for this run

**Expected observables:**
- The query evaluates all non-sidecar files rows for the asset
- The asset is NOT flagged as a deletion candidate, because the primary file is still present

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:149-157`

## SCENARIO-0031 — An asset becomes a deletion candidate only after two consecutive missing runs

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0043

**Preconditions:**
- An asset has a single files row (role=primary) present on disk at the start.

**Action:**
- Run 1: the primary file is now absent from disk
- Run 2: the primary file is still absent from disk

**Expected observables:**
- missing_since_utc is set on the files row
- The asset is NOT yet flagged as a deletion candidate
- The files row is reconfirmed missing
- Only after run 2 is the asset flagged as a deletion candidate

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:149-157`

## SCENARIO-0032 — Health listener stays reachable while the dashboard is disabled

**Kind:** surface
**Proof seam:** process-level
**Owning stories:** STORY-0046, STORY-0047

**Preconditions:**
- The service starts with global.dashboard.enabled: false and default global.health settings.

**Action:**
- Send an HTTP request to 0.0.0.0:9090 (or the pod's reachable IP) for the health endpoint
- Send an HTTP request to the dashboard's default port

**Expected observables:**
- The listener responds with health/metrics data
- No dashboard service is listening
- The health/metrics endpoint is reachable from another host/pod
- The health response contains no credentials, account names, or per-account status data — only healthy/unhealthy and counters
- The dashboard is not started

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0033 — Startup fails fast when Telegram is configured without allowed chat IDs

**Kind:** failure-recovery
**Proof seam:** process-level
**Owning stories:** STORY-0048

**Preconditions:**
- A config file sets global.telegram.bot_token_file to a valid secret path and leaves global.telegram.allowed_chat_ids as an empty list.

**Action:**
- Start the service (or run `validate`) with this config

**Expected observables:**
- Validation fails with an explicit error identifying the empty allowed_chat_ids under a configured telegram block
- The process exits non-zero / refuses to start
- No Telegram bot session is established

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0034 — Config validation rejects duplicate or missing account names

**Kind:** failure-recovery
**Proof seam:** process-level
**Owning stories:** STORY-0050

**Preconditions:**
- A config file defines two accounts both named 'main', or one account entry with no `name` field.

**Action:**
- Run `validate` against this config

**Expected observables:**
- Validation fails, citing the duplicate or missing name
- The process does not proceed to start syncing any account from this config

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0035 — Telegram /sync command resolves by account name, never apple_id

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0050

**Preconditions:**
- An account named 'main' is configured and running.
- An allowed Telegram chat sends /sync main.

**Action:**
- The bot receives and parses the /sync main command

**Expected observables:**
- The bot resolves 'main' against configured account names
- A sync is triggered for the account named 'main'
- No apple_id value ever appears in the Telegram command, bot reply, or logs of this exchange

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0036 — Credential resolution falls back from file to env for apple_id

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0051

**Preconditions:**
- An account config sets credentials.apple_id_env: ICLOUDPD_APPLE_ID and omits apple_id_file.
- The process environment has ICLOUDPD_APPLE_ID set to a valid Apple ID.

**Action:**
- Start a sync run for the account

**Expected observables:**
- Credential resolution checks apple_id_file (absent), then falls back to apple_id_env
- The run authenticates using the Apple ID from the ICLOUDPD_APPLE_ID environment variable

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0037 — asset_types opt-in array excludes unlisted types from sync

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0052

**Preconditions:**
- An account's sync_scope.asset_types is set to [photos] only.
- The library contains photos, live_photos, and videos.

**Action:**
- Run a sync cycle for the account

**Expected observables:**
- Only photo assets are enumerated/downloaded
- No live_photos or videos are downloaded or added to the manifest for this account
- Photos are downloaded/added as expected

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0038 — A full sweep never self-reports Exhaustive while date-scoping is absent from config

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0053

**Preconditions:**
- An account is configured for a full sweep with no date-scoping or early-stop keys available in the schema (none configured, since none exist).

**Action:**
- Run the full sweep to completion without error

**Expected observables:**
- Every live asset in the library is visited, none skipped by creation date
- The run reports Exhaustive:true and this is accurate — no asset was excluded from the sweep by a date range
- Deletion-sync reconciliation logic operating on this run's Exhaustive:true signal does not mis-flag any real, in-library photo as removed

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0039 — Deletion mirroring is fully inert when disabled, regardless of threshold

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0054

**Preconditions:**
- An account has deletion_sync.enabled: false and deletion_sync.threshold: 5.
- Several assets qualify as deletion candidates (all non-sidecar files rows missing for two runs).

**Action:**
- Run two consecutive sync cycles that would otherwise produce deletion candidates

**Expected observables:**
- No mirror_batches or mirror_items rows are created for this account
- No remote deletions occur
- No batch is withheld for review, since the feature performed no detection at all

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0040 — Cumulative unresolved missing count across runs trips the threshold

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0054

**Preconditions:**
- An account has deletion_sync.enabled: true and deletion_sync.threshold: 5.
- Run A produces 3 unresolved deletion candidates that are not approved.
- Run B produces 3 more deletion candidates for different assets.

**Action:**
- Complete run A
- Complete run B

**Expected observables:**
- 3 candidates recorded, cumulative unresolved count = 3, below threshold, batch proceeds or awaits approval per design but not yet capped
- Cumulative unresolved count reaches 6, exceeding threshold 5
- The batch from run B (or the cumulative batch) is withheld for review once the cumulative unresolved count reaches/exceeds the threshold of 5, even though no single run alone reached 5

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0041 — Config validation rejects an account with no schedule

**Kind:** failure-recovery
**Proof seam:** process-level
**Owning stories:** STORY-0055

**Preconditions:**
- A config file defines an account entry with all required fields except `schedule`.

**Action:**
- Run `validate` against this config

**Expected observables:**
- Validation fails, citing the missing schedule key for that account
- No default cron expression is substituted
- The process does not start a scheduled run for that account

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:159-234`

## SCENARIO-0042 — Deletion detected in sync loop beats the auto-heal race

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0060

**Preconditions:**
- Manifest holds a row for (record_name, rel_path) from a previous run
- Local file for that asset is missing
- The asset is still present in iCloud

**Action:**
- Sync loop processes the asset and finds local files missing
- Manifest row is found for this (record_name, rel_path)

**Expected observables:**
- Engine checks manifest for a prior-run row before attempting re-download
- Asset is classified as a deletion candidate, not re-downloaded
- No re-download occurs for the asset
- Asset is registered as a deletion candidate for internal/mirror policy

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-244`

## SCENARIO-0043 — Only exhaustive runs produce deletion candidates

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0061

**Preconditions:**
- Composite enumerator configured with a 60s delta tick and a nightly full sweep

**Action:**
- 60s delta tick runs and completes without error
- Nightly full sweep runs and completes without error

**Expected observables:**
- Capabilities.Exhaustive is false for this run
- No deletion candidates are produced even if local files are missing for unseen assets
- Capabilities.Exhaustive is true
- Deletion candidates are produced for assets missing locally but not re-seen
- Deletion candidates originate only from runs reporting Capabilities.Exhaustive

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:245-249`

## SCENARIO-0044 — Dropped media mount surfaces as a loud manifest mismatch, not a silent reset

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0062

**Preconditions:**
- Manifest at state_dir (separate RWO volume) records 4,527 asset rows
- NFS/SMB media mount at /data reverts to an empty local directory (mount drop)

**Action:**
- Sync engine runs a scan against the now-empty /data mount

**Expected observables:**
- Manifest is untouched and still reports 4,527 rows
- Filesystem scan shows 3 files
- A loud manifest-vs-filesystem mismatch signal is available (4,527 vs 3) instead of the manifest silently resetting to empty

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:250-252`

## SCENARIO-0045 — Liveness sentinel blocks an unmounted-source scan from being authoritative

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0063

**Preconditions:**
- Download root's source volume is unmounted, so it reads back as empty
- Sentinel file for that root is therefore unreadable

**Action:**
- Sync engine attempts a scan of the download root

**Expected observables:**
- Liveness check runs before detection and fails to read the sentinel
- Scan is not treated as authoritative
- No deletion candidates are produced from this scan

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:253-254`

## SCENARIO-0046 — enabled=false suppresses deletion detection regardless of threshold

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0064

**Preconditions:**
- deletion_sync.enabled = false
- deletion_sync.threshold = 5 (or any value)

**Action:**
- A run finds several assets missing locally that would otherwise be deletion candidates

**Expected observables:**
- No candidates are detected or acted on
- No deletion_sync_summary or deletion_sync_threshold_tripped events are emitted
- Deletion-sync feature has no observable effect while disabled

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:255-260`

## SCENARIO-0047 — enabled:true with threshold:-1 is uncapped, and validate warns on the unedited example pairing

**Kind:** contract
**Proof seam:** app-level
**Owning stories:** STORY-0064

**Preconditions:**
- Config has deletion_sync.enabled: true and deletion_sync.threshold: -1

**Action:**
- A run produces a large batch of deletion candidates
- Operator runs icloudpd validate against this config

**Expected observables:**
- All candidates are deleted with no cap applied
- A warning is printed about enabled:true paired with threshold:-1
- Validation does not fail/block
- Deletions proceed unbounded
- A warning was surfaced but did not block execution

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:255-260`

## SCENARIO-0048 — Slow leak across multiple runs still trips the cumulative threshold

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0065

**Preconditions:**
- deletion_sync.enabled = true, threshold = 10
- A flaky mount causes 3 new candidates to surface per night, each night's batch always under 10

**Action:**
- Run 1 finds 3 new candidates; cumulative outstanding count becomes 3
- Runs 2 and 3 each find 3-4 more candidates

**Expected observables:**
- Deletions proceed automatically (below threshold)
- Each individual run's batch stays under 10
- Cumulative outstanding count climbs past 10 by run 3 or 4
- Once cumulative count reaches/exceeds threshold, the breaker trips and the batch is withheld, even though no single run's batch exceeded threshold

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:260-262`

## SCENARIO-0049 — Below-threshold deletions run automatically and emit a summary event

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0066

**Preconditions:**
- deletion_sync.enabled = true, threshold = 20
- A run finds 5 deletion candidates, cumulative outstanding stays below 20

**Action:**
- Sync run completes with the 5 candidates

**Expected observables:**
- The 5 items are deleted without any per-item review step
- Deletions are logged
- A deletion_sync_summary event is emitted after the fact
- No pending/withheld batch exists

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:262-263`

## SCENARIO-0050 — At-threshold trip withholds the batch and merges later candidates into it

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0067

**Preconditions:**
- deletion_sync.enabled = true, threshold = 10
- Cumulative outstanding candidates reach 10 on run N

**Action:**
- Run N completes and the cumulative count hits threshold
- Run N+1 later finds 2 more candidates while still tripped and unresolved

**Expected observables:**
- Zero deletions execute for this batch
- A deletion_sync_threshold_tripped event is emitted
- The 2 new candidates merge into the same pending batch rather than starting a second batch
- Trip state persists across run N+1 and beyond until an operator resolves it
- No deletions have occurred for any item in the pending batch

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:263-266`

## SCENARIO-0051 — Approving a withheld batch re-verifies each item remotely and locally before deleting

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0069, STORY-0068

**Preconditions:**
- A batch has been withheld (threshold tripped) and sits pending for several days
- One item in the batch has since reappeared locally
- One item in the batch has since been deleted directly in iCloud

**Action:**
- Operator runs --resolve-deletions=approve (or /approve <account>)
- Engine evaluates the locally-reappeared item
- Engine evaluates the already-gone-remotely item

**Expected observables:**
- Each remaining item gets a remote recordChangeTag lookup and a local filesystem check at rel_path
- That item is dropped from the batch, not deleted
- That item is marked skipped_reappeared/gone, not treated as an error
- Only items confirmed still missing both locally and validly present remotely (or genuinely deletable) proceed to deletion
- Approval outcome is correct despite the batch's age

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-266`

## SCENARIO-0052 — Rejecting a withheld batch re-downloads files and pending items stay exempt from auto-redownload until resolved

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0068

**Preconditions:**
- A batch is withheld and pending, containing item X

**Action:**
- A normal sync pass runs while the batch is still pending/undecided
- Operator runs --resolve-deletions=reject (or /reject <account>)
- Next normal sync pass runs

**Expected observables:**
- Item X is not auto-redownloaded despite appearing missing locally
- Batch is marked rejected
- Item X is re-downloaded
- Item X's file exists locally again after rejection and the next pass
- Pending items never auto-redownloaded prior to explicit resolution

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:255-267`

## SCENARIO-0053 — One account's tripped threshold does not withhold another account's deletions

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0070

**Preconditions:**
- Account A has deletion_sync threshold tripped and a pending batch
- Account B has deletion_sync enabled with candidates below its own threshold

**Action:**
- Account B's sync run completes with candidates under its threshold

**Expected observables:**
- Account B's deletions proceed automatically, unaffected by Account A's tripped state
- Account A remains tripped/pending
- Account B's below-threshold deletions completed independently

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-266`

## SCENARIO-0054 — A 4,000-item threshold trip pages through Telegram thumbnails 10 at a time

**Kind:** surface
**Proof seam:** e2e
**Owning stories:** STORY-0071, STORY-0072

**Preconditions:**
- deletion_sync threshold trips with 4,000 pending candidate items

**Action:**
- deletion_sync_threshold_tripped event fires
- Operator taps 'next page'

**Expected observables:**
- Telegram receives the total count plus the first page of 10 real thumbnail photo messages
- Inline buttons are present to page through the remaining items
- The next 10 real thumbnails are fetched live (THUMB-size JPEGs) and sent
- No capability URL is ever sent
- Review is possible without a web page
- Nothing from the batch was written to disk as image data

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:236-266`

## SCENARIO-0055 — One hung account does not starve sibling accounts

**Kind:** failure-recovery
**Proof seam:** process-level
**Owning stories:** STORY-0074, STORY-0076, STORY-0075

**Preconditions:**
- Multiple account goroutines running concurrently
- One account's iCloud endpoint stops responding mid-enumeration-page

**Action:**
- The hung account's enumeration-page call exceeds the flat 30s timeout
- Other account goroutines continue their own work

**Expected observables:**
- That phase times out and the failure is logged/published to status for that account only
- Their API calls and downloads proceed unaffected, gated only by the shared rate limiter
- Sibling accounts complete their runs normally
- The hung account is marked failed/degraded in status without aborting others

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:268-272`

## SCENARIO-0056 — A large file download is not killed by the flat phase timeout

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0076

**Preconditions:**
- A file download is in progress and exceeds 30 seconds in duration but maintains throughput above the minimum-speed threshold

**Action:**
- Download continues past the 30s mark
- Download throughput later drops below the minimum-speed threshold

**Expected observables:**
- Download is not aborted by a flat deadline
- Download is aborted for insufficient speed, not for elapsed time
- Large-but-healthy downloads complete successfully; only genuinely stalled downloads are aborted

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:271-272`

## SCENARIO-0057 — Overlapping cron tick is skipped, not queued

**Kind:** surface
**Proof seam:** process-level
**Owning stories:** STORY-0077

**Preconditions:**
- Account's scheduled sync is still running past its next scheduled tick time

**Action:**
- The next scheduled tick fires while the previous run is still in progress

**Expected observables:**
- The tick is skipped; no second run is queued or started back-to-back
- Only one run is active for that account at a time
- The skip is visible via /status and /metrics
- The account's next run happens at its subsequent regularly scheduled time

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:273`

## SCENARIO-0058 — Concurrent store writes from multiple accounts queue at a single writer instead of erroring

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0078

**Preconditions:**
- Multiple account goroutines each need to write to the shared SQLite store at the same time

**Action:**
- Two or more account goroutines send writes concurrently over the writer channel

**Expected observables:**
- Writes are serialized through the single writer goroutine
- No SQLITE_BUSY error occurs and no busy-timeout retry logic runs
- Every write either succeeds or fails for a genuine data/constraint reason, never due to a lock race

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:274`

## SCENARIO-0059 — kill -9 during shutdown loses at most one asset

**Kind:** failure-recovery
**Proof seam:** process-level
**Owning stories:** STORY-0079

**Preconditions:**
- Service is mid-run downloading multiple assets across accounts
- Graceful shutdown sequence (root cancel → HTTP Shutdown) has begun

**Action:**
- Runners stop between assets as shutdown proceeds; a kill -9 arrives before natural completion

**Expected observables:**
- The asset actively being downloaded at the moment of kill is discarded via its temp+rename mechanism, never left as a corrupt final file
- All previously-completed assets in this run remain committed to the store
- At most the single in-flight asset is lost/incomplete
- No corrupted output file for the interrupted asset exists at its final path

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:275-276`

## SCENARIO-0060 — Web dashboard has no working mutation endpoint

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0012

**Preconditions:**
- Dashboard is enabled and reachable

**Action:**
- An HTTP client sends a POST (or any mutating verb) to any dashboard route attempting ForceReauth, Cancel, Resume, Approve, RejectBatch, or manual sync trigger
- Operator instead issues /approve via Telegram or --resolve-deletions via CLI

**Expected observables:**
- No route exists that performs the mutation; request is rejected or 404s
- The mutation is accepted and applied through that surface
- The old unauthenticated POST /force-reauth-class vulnerability class has no equivalent in the web dashboard
- All mutations only ever originate from Telegram/CLI

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:278-284`

## SCENARIO-0061 — TestDashboardImportGraph fails the build if a secret-capable package sneaks into the dashboard's dependency tree

**Kind:** contract
**Proof seam:** unit
**Owning stories:** STORY-0013

**Preconditions:**
- internal/web/dashboard currently imports only internal/status

**Action:**
- A hypothetical future change adds an import from internal/web/dashboard (or any package it depends on) to internal/config, internal/secret, internal/icloud/auth, internal/control, or internal/store/sqlite

**Expected observables:**
- TestDashboardImportGraph runs `go list -deps ./internal/web/dashboard` and detects the excluded package in the transitive set
- TestDashboardImportGraph fails, blocking the change from merging

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:285-286`

## SCENARIO-0062 — Dashboard binds loopback by default and requires explicit config for LAN exposure

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0014

**Preconditions:**
- dashboard.enabled = true
- dashboard.bind left unset in config

**Action:**
- Service starts
- A client on the LAN (not localhost) attempts to reach the dashboard port
- Operator sets dashboard.bind explicitly to 0.0.0.0 (or a LAN interface) and restarts

**Expected observables:**
- Dashboard listener binds to 127.0.0.1 only
- Connection is refused/unreachable
- Dashboard becomes reachable from the LAN
- Dashboard is loopback-only unless the operator explicitly opts into broader exposure

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:287-288`

## SCENARIO-0063 — Health/metrics listener stays up and minimal even with the dashboard disabled

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0080

**Preconditions:**
- dashboard.enabled = false

**Action:**
- Service starts
- Client requests /healthz, /readyz, and /metrics
- Client requests any status/account-detail-bearing path on this listener

**Expected observables:**
- Health/metrics listener starts on its default bind regardless of dashboard.enabled
- Each responds successfully
- No such path exists; no account names or status detail are exposed
- Health/metrics functionality is fully available independent of the dashboard feature flag, with no status leakage

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:290-292`

## SCENARIO-0064 — /readyz stays ready with one hung account and only flips on total failure

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0080

**Preconditions:**
- Multiple accounts configured
- One account's goroutine is hung/failing

**Action:**
- Client requests /readyz while only the one account is down and others are healthy
- All accounts subsequently go down (total failure)

**Expected observables:**
- /readyz reports ready
- /readyz flips to not-ready
- /readyz reflects total-failure state, not partial degradation

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:290-292`

## SCENARIO-0065 — Health/metrics listener defaults to 0.0.0.0:9090, reachable from outside the pod

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0081

**Preconditions:**
- Service started with no explicit bind override for the health/metrics listener
- A separate Prometheus pod attempts to scrape this service over the network

**Action:**
- Service starts with default configuration
- Prometheus pod scrapes the service's network address on port 9090

**Expected observables:**
- Health/metrics listener binds 0.0.0.0:9090
- Scrape succeeds, retrieving /metrics content
- Metrics are reachable from outside the pod's own network namespace without additional configuration

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:293-294`

## SCENARIO-0066 — Operator forces an immediate sync outside the cron schedule

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0082

**Preconditions:**
- An account is configured and its next cron-scheduled sync is not due for hours.

**Action:**
- Operator sends /sync <account> to the bot.

**Expected observables:**
- A full sweep for <account> begins immediately, not waiting for the next cron tick.
- The account's last-sync timestamp updates immediately, independent of the cron schedule.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-301`

## SCENARIO-0067 — Operator approves a pending batch and deletions execute

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0083, STORY-0095

**Preconditions:**
- Account has a pending deletion-sync batch awaiting review.

**Action:**
- Operator sends /approve <account>.

**Expected observables:**
- Each item's recordChangeTag is re-verified against iCloud.
- All items in the batch are deleted.
- The pending batch is cleared; the corresponding items no longer exist in the account's iCloud library.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-301, 319`

## SCENARIO-0068 — Operator rejects a pending batch and files re-download

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0084, STORY-0092

**Preconditions:**
- Account has a pending deletion-sync batch.

**Action:**
- Operator sends /reject <account>.
- The next normal sync run occurs.

**Expected observables:**
- The pending batch is discarded with no deletions executed.
- The previously-flagged files are re-downloaded and re-evaluated as new candidates if still missing.
- No files were deleted; files reappear locally after the next run.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-301, 317`

## SCENARIO-0069 — Operator cancels and then resumes an in-progress sync

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0085, STORY-0086

**Preconditions:**
- A sync run for <account> is currently in progress.

**Action:**
- Operator sends /cancel <account>.
- Operator sends /resume <account>.

**Expected observables:**
- The in-progress run for <account> stops.
- The cancellation is undone or the account's schedule restarts.
- Account returns to normal scheduled operation after /resume.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-304`

## SCENARIO-0070 — Operator forces re-authentication of a stuck account

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0087

**Preconditions:**
- Account has an existing (possibly stale) session.

**Action:**
- Operator sends /force_reauth <account>.
- The next login attempt for the account occurs.

**Expected observables:**
- The bot accepts the command as registered (/force_reauth, underscore form).
- The current session is discarded.
- A fresh login flow runs instead of reusing the old session.
- Account authenticates via a newly-established session, not the discarded one.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-305`

## SCENARIO-0071 — Operator reads account status without side effects

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0088

**Preconditions:**
- Account has sync history and possibly a pending batch.

**Action:**
- Operator sends /status <account>.

**Expected observables:**
- Bot replies with last sync time, error counts, and pending mirror batch state.
- No sync, approval, rejection, or session change is triggered.
- Account state (schedule, pending batch, session) is unchanged after the command.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:296-306`

## SCENARIO-0072 — Command targeting the wrong or missing account does not affect other accounts

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0089

**Preconditions:**
- Two accounts, A and B, are configured, each with its own independent pending deletion-sync batch.

**Action:**
- Operator sends /approve A.
- Check account B's state.

**Expected observables:**
- Only account A's pending batch is released.
- Account B's pending batch remains untouched and awaiting review.
- Account A's batch executed; account B's batch is unaffected, confirming no implicit shared 'current account' state exists.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:308-310`

## SCENARIO-0073 — Circuit breaker trip sends a paginated photo album of deletion candidates

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0090, STORY-0091

**Preconditions:**
- A sync run's deletion candidates trip the circuit breaker; the batch contains 25 items including at least one video.

**Action:**
- Bot sends the initial notification.
- Operator taps 'next 10'.
- Operator taps 'previous 10' before reaching the end.

**Expected observables:**
- A Telegram photo album of up to 10 THUMB-size JPEGs is sent.
- The video item appears via its JPEG poster-frame in the same photo field as image items, with no separate handling.
- No image bytes are written to disk by the bot.
- The next 10 items' thumbnails are shown.
- The prior page is shown again; the batch can be approved without having viewed all 25 items.
- Operator can approve or reject at any point in pagination without a forced full walkthrough.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:312-316`

## SCENARIO-0074 — New run merges candidates into the existing pending batch and re-notifies only on genuinely new items

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0093, STORY-0094

**Preconditions:**
- Account has a pending batch containing items X and Y already recorded in mirror_items.

**Action:**
- A later run finds X still missing and a new candidate Z (not in mirror_items).

**Expected observables:**
- No new pending batch is opened; X and Z are merged into the single existing pending batch.
- No notification is sent for X (silent re-confirmation).
- A re-notify message is sent for the updated batch, showing the new total count and a fresh page of thumbnails including Z.
- Exactly one pending batch exists for the account, now containing X, Y, and Z, and the operator was notified with an up-to-date count.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:318`

## SCENARIO-0075 — Config rotation via atomic symlink swap is detected after debounce

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0098

**Preconditions:**
- The process is running with fsnotify watching the config file's parent directory.
- A Kubernetes ConfigMap update triggers an atomic symlink swap of the config file.

**Action:**
- The symlink swap occurs.
- ~200ms debounce window elapses.

**Expected observables:**
- The parent-directory watch fires (a file-level watch would have gone deaf here).
- The new config is re-read and validated.
- The process is running with the new configuration values without a restart.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:327`

## SCENARIO-0076 — Login succeeds against Apple's SRP variant using the hand-rolled implementation

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0100

**Preconditions:**
- Valid iCloud credentials for a test/real account.

**Action:**
- Client performs SRP authentication using the hand-rolled math/big + crypto/sha256 + pbkdf2 implementation.

**Expected observables:**
- The SRP exchange completes and the server accepts the proof, matching Apple's variant.
- Login succeeds and a valid session is established.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:331`

## SCENARIO-0077 — Config file with an unknown field is rejected at load

**Kind:** contract
**Proof seam:** unit
**Owning stories:** STORY-0101

**Preconditions:**
- A YAML config file contains a field name not defined in the config schema (e.g. a typo).

**Action:**
- The application loads the config file at startup.

**Expected observables:**
- Loading fails with an error identifying the unrecognized field, rather than silently proceeding.
- The process does not start with a config that silently ignored an unknown key.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:332-333`

## SCENARIO-0078 — print-config attributes each field to its source layer

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0103

**Preconditions:**
- A YAML file sets field A; an environment variable sets field B; field C is left at its default.

**Action:**
- Operator runs print-config.

**Expected observables:**
- Field A is reported as sourced from the YAML file.
- Field B is reported as sourced from the environment variable.
- Field C is reported as sourced from the default.
- Every printed field carries an accurate provenance label.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:335`

## SCENARIO-0079 — Fixture older than 90 days fails the codec test suite

**Kind:** failure-recovery
**Proof seam:** unit
**Owning stories:** STORY-0104

**Preconditions:**
- A codec fixture's recorded_at metadata is 91 days old.
- Test binary is built without -tags=stale.

**Action:**
- Run the codec test suite.
- Re-run with -tags=stale.

**Expected observables:**
- The freshness guard fails loudly, naming the stale fixture.
- The freshness guard is bypassed and the test proceeds using the stale fixture.
- Without the escape hatch, CI fails on stale fixtures; with it, the suite still runs.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:339-341`

## SCENARIO-0080 — Reachability guard catches a record type replaced without new fixtures

**Kind:** failure-recovery
**Proof seam:** unit
**Owning stories:** STORY-0105

**Preconditions:**
- The client is updated to emit CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted instead of the old record type, but no fixture for the new type has been added.

**Action:**
- Run the reachability guard.

**Expected observables:**
- The guard fails, reporting the emittable record type with zero fixtures.
- The test suite blocks merging code for a record type with no fixture coverage, precisely the gap that let the 2023 drift go unnoticed.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:339-341`

## SCENARIO-0081 — Mirror/paging logic handles a 503 mid-pagination via ckwstest fault injection

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0106

**Preconditions:**
- ckwstest fake server is configured to return 503 on page three of a paginated listing.

**Action:**
- The paging/retry logic requests page three.

**Expected observables:**
- The client receives the injected 503.
- Retry logic engages and eventually recovers or fails per the retry policy.
- Test asserts the specific retry/backoff/error-surfacing behavior under this fault, something no recorded cassette could exercise.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:342-343`

## SCENARIO-0082 — Operator runs check-protocol by hand and gets a pass/fail with no CI involvement

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0107

**Preconditions:**
- Operator has valid real-account credentials and Telegram 2FA configured.
- No scheduled CI job exists for this check.

**Action:**
- Operator runs `icloudpd check-protocol` manually.
- The run succeeds.

**Expected observables:**
- Authentication proceeds via the normal credential flow, prompting 2FA over Telegram like any other run.
- The tool asserts only the structure of API responses, never their content.
- A pass/fail result is printed.
- Tier-1, shared-redaction fixtures are regenerated as a side effect of the successful run.
- No CI job triggered this check; fixtures on disk reflect the freshly-verified live protocol structure.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:344-346`

## SCENARIO-0083 — Mirror refuses to submit when the entire library disappears in one run

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0109

**Preconditions:**
- Mirror has previously tracked N > 0 files for an account.
- A run finds zero of those N files present (e.g. due to a bug, misconfigured path, or mass outage).

**Action:**
- Mirror evaluates the run's results.

**Expected observables:**
- Mirror detects that 100% of previously-known files are now absent.
- Mirror refuses to create or submit a deletion batch for this run instead of proposing to delete everything.
- No deletion batch is created; the mirror instead surfaces this as a refusal/error condition rather than a pending batch awaiting approval.

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:347`

## SCENARIO-0084 — Static build produces a minimal, working binary and image

**Kind:** contract
**Proof seam:** process-level
**Owning stories:** STORY-0112

**Preconditions:**
- Source tree builds with Go toolchain available

**Action:**
- Run `CGO_ENABLED=0 go build ./...`
- Build the container image from the produced binary

**Expected observables:**
- Build succeeds
- Resulting binary is statically linked (no dynamic libc dependency)
- Image builds FROM scratch or a distroless base
- Build output reports final image size
- A static binary exists
- A minimal-base container image exists with a reported size

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:378`

## SCENARIO-0085 — Test suite enforces dashboard import isolation and fixture health

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0113

**Preconditions:**
- Full test suite is runnable via `go test ./...`

**Action:**
- Run `go test ./...`
- Run the import-graph test that inspects the dashboard package's imports
- Run the fixture freshness and reachability guard tests

**Expected observables:**
- All tests pass
- Test fails if dashboard imports secret, config, auth, control, or sqlite; passes otherwise
- Tests fail if a fixture is stale or unreachable; pass otherwise
- go test ./... exits green
- Dashboard package has zero import edges to secret/config/auth/control/sqlite

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:379`

## SCENARIO-0086 — check-protocol asserts real-account response structure

**Kind:** surface
**Proof seam:** e2e
**Owning stories:** STORY-0114

**Preconditions:**
- A real iCloud account is available for manual use
- No CI job invokes this command

**Action:**
- Run `icloudpd check-protocol` by hand against the real account

**Expected observables:**
- Command completes and asserts on the response structure, failing loudly on mismatch
- Protocol response structure is confirmed to match expectations for that run

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:380`

## SCENARIO-0087 — Config validation rejects malformed config; print-config shows provenance

**Kind:** surface
**Proof seam:** e2e
**Owning stories:** STORY-0115

**Preconditions:**
- A malformed config file
- A valid config assembled from multiple sources (e.g. file + env + flag)

**Action:**
- Run `icloudpd validate` against the malformed config
- Run `icloudpd print-config` against the valid multi-source config

**Expected observables:**
- Command exits with a clear, specific error identifying the problem
- Output shows each field's resolved value alongside which source it came from
- Malformed config is rejected with a clear error
- print-config output includes per-field provenance

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:381`

## SCENARIO-0088 — Renaming the folder-structure setting does not trigger re-download

**Kind:** failure-recovery
**Proof seam:** e2e
**Owning stories:** STORY-0116

**Preconditions:**
- Assets already downloaded and recorded in the manifest under the original folder-structure setting

**Action:**
- Change the folder-structure setting and run `icloudpd run-once` again

**Expected observables:**
- No previously-downloaded asset is re-downloaded from iCloud
- Manifest still reflects prior downloads
- No redundant network fetch occurred solely due to the naming-setting change

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:383`

## SCENARIO-0089 — docker stop mid-run exits clean within grace period

**Kind:** failure-recovery
**Proof seam:** process-level
**Owning stories:** STORY-0117

**Preconditions:**
- A sync run is in progress mid-download

**Action:**
- Issue `docker stop` while the run is in progress

**Expected observables:**
- Process begins shutdown handling
- Process exits within the configured grace period
- No partial files remain on disk
- Manifest is left in a consistent state

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:384`

## SCENARIO-0090 — Secret rotation is picked up without restart

**Kind:** failure-recovery
**Proof seam:** process-level
**Owning stories:** STORY-0118

**Preconditions:**
- Container is running with a mounted secret file
- Secret is actively in use for auth

**Action:**
- Rotate the underlying secret file's contents while the container keeps running

**Expected observables:**
- No restart is triggered or required
- Subsequent operations use the new secret value
- Container never restarted

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:385`

## SCENARIO-0091 — Dashboard port scan finds no credential form or mutating endpoint

**Kind:** surface
**Proof seam:** e2e
**Owning stories:** STORY-0119

**Preconditions:**
- Dashboard is running and reachable on its port

**Action:**
- Scan/crawl the dashboard's exposed port and enumerate the compiled binary's routes

**Expected observables:**
- Status renders normally
- No credential-entry form is found
- No mutating endpoint is found anywhere in the binary
- Dashboard surface is read-only with no path to submit credentials or mutate state

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:386`

## SCENARIO-0092 — Wrong password and 2FA prompts escalate only through Telegram

**Kind:** surface
**Proof seam:** e2e
**Owning stories:** STORY-0119

**Preconditions:**
- An account authentication attempt is in progress
- Telegram bot is configured and reachable

**Action:**
- Trigger a wrong-password condition during auth
- Trigger a 2FA prompt during auth
- Reply to the 2FA inline prompt once, then attempt to reply again

**Expected observables:**
- A Telegram message is sent that is notify-only, with no reply path
- A Telegram message is sent with an inline reply option
- First reply is accepted
- Second reply is not accepted / has no further effect
- Wrong-password path never offers a reply mechanism
- 2FA reply is accepted exactly once

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:386`

## SCENARIO-0093 — Deletion dry-run refuses on unreadable sentinel

**Kind:** failure-recovery
**Proof seam:** e2e
**Owning stories:** STORY-0120

**Preconditions:**
- Download root's volume is unmounted
- Sentinel file is therefore unreadable

**Action:**
- Run deletion-sync in dry-run mode against that download root

**Expected observables:**
- Process detects the unreadable sentinel and refuses to proceed
- No deletion candidates are proposed
- A refusal/error is surfaced instead of a (false) empty result

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:388-389`

## SCENARIO-0094 — Grouped-asset deletion candidacy requires every sibling missing

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0121

**Preconditions:**
- A Live Photo pair, a multi-size set, and a RAW+JPEG set each exist locally and in the manifest

**Action:**
- Delete only one file of the Live Photo pair locally, then run deletion-sync
- Delete the remaining file of the same pair, then run deletion-sync
- Repeat the partial-then-full deletion for the multi-size set and the RAW+JPEG set

**Expected observables:**
- No candidate is produced for that pair
- A candidate is produced for that pair
- Same all-or-nothing pattern holds for each group type
- No group produces a candidate until every member file is missing locally

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:390`

## SCENARIO-0095 — Deletion candidacy requires a full enumeration sweep

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0122

**Preconditions:**
- An asset was previously downloaded and recorded in the manifest, then its local file was deleted

**Action:**
- Run deletion-sync with a truncated enumerator (Exhaustive: false)
- Run deletion-sync with a full sweep

**Expected observables:**
- No candidate is produced for the deleted asset
- A candidate is produced for the deleted asset
- Deletion candidacy is gated on enumeration exhaustiveness

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:391`

## SCENARIO-0096 — Threshold breach withholds all deletions and trips a persistent circuit breaker

**Kind:** failure-recovery
**Proof seam:** e2e
**Owning stories:** STORY-0123

**Preconditions:**
- An account's deletion-sync threshold is configured to a finite value
- A run produces candidates exceeding that threshold

**Action:**
- Run deletion-sync with candidates exceeding the threshold
- Run deletion-sync again on a subsequent pass without resolving the trip

**Expected observables:**
- Zero deletions execute
- The batch is withheld
- `deletion_sync_threshold_tripped` fires with real thumbnails delivered in Telegram
- Tripped state is still in effect
- No deletions occurred despite exceeding threshold
- Trip state persists across runs until explicitly resolved

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:392`

## SCENARIO-0097 — New candidates merge into an existing pending batch

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0124

**Preconditions:**
- A deletion batch is already pending approval for an account

**Action:**
- Run deletion-sync again and discover additional candidates for the same account

**Expected observables:**
- New candidates are added to the existing pending batch, not a new one
- Exactly one pending batch exists for the account, with the updated total candidate count
- A re-notify was sent reflecting the updated count

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:393`

## SCENARIO-0098 — Reject restores files; pending items stay untouched

**Kind:** surface
**Proof seam:** e2e
**Owning stories:** STORY-0125

**Preconditions:**
- A deletion batch is pending for an account

**Action:**
- While the batch is still pending, check whether its files were re-downloaded
- Send `/reject <account>` (or run with `--resolve-deletions=reject`)
- Run the next sync pass

**Expected observables:**
- Files remain absent locally and are not re-downloaded while undecided
- Batch is marked rejected
- The rejected files are re-downloaded
- Rejected files exist locally again after the next pass
- No file was re-downloaded while the batch was still pending/undecided

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:394`

## SCENARIO-0099 — Approval re-verifies remote state before executing

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0126

**Preconditions:**
- A deletion batch is pending approval
- One candidate asset is subsequently mutated in iCloud, another is deleted in iCloud

**Action:**
- Approve the batch

**Expected observables:**
- For the mutated asset: a fresh recordChangeTag is fetched and the deletion submits successfully
- For the already-deleted asset: it is marked skipped rather than raising an error
- Mutated-asset deletion succeeded using a freshly fetched recordChangeTag
- Already-deleted asset ends in a skipped state, no error surfaced

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:395`

## SCENARIO-0100 — Threshold trips and command targeting are scoped per account

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0127

**Preconditions:**
- Two accounts, A and B, both have pending or in-flight deletion-sync activity

**Action:**
- Trip account A's deletion threshold
- Send `/approve` or `/reject` without specifying an account

**Expected observables:**
- Account B's deletion-sync run still proceeds normally
- Command is rejected as ambiguous
- Account B unaffected by account A's trip
- No account-less approve/reject command was ever applied

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:396`

## SCENARIO-0101 — Large deletion batches page via Telegram and approve without full review

**Kind:** surface
**Proof seam:** e2e
**Owning stories:** STORY-0128

**Preconditions:**
- A pending deletion batch contains more than 10 items

**Action:**
- Open the batch review in Telegram and page forward, then backward, via inline buttons
- Send `/approve` after viewing only the first page

**Expected observables:**
- Paging works in both directions across the full batch
- Approval succeeds for the whole batch
- Batch is fully approved despite the operator not having paged through every item

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:397`

## SCENARIO-0102 — Metrics and readiness probes reflect real per-account sync state

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0130

**Preconditions:**
- Service is running with at least two configured accounts

**Action:**
- Query `/metrics` after a successful sync
- Query `/healthz` and `/readyz` before any run and after a failed run
- Fail sync for all-but-one account, then query `/readyz`
- Fail sync for every account, then query `/readyz`

**Expected observables:**
- Last-successful-sync timestamp and error counters are present and correct
- Both respond correctly for each state
- `/readyz` still reports ready
- `/readyz` flips to not-ready
- /readyz is ready iff at least one account can sync
- /metrics values track real sync outcomes

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:398-399`

## SCENARIO-0103 — v1 syncs exclusively via full sweep on the cron interval

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0131

**Preconditions:**
- v1 binary/configuration, no delta enumerator wired into syncengine

**Action:**
- Inspect the configured Enumerator used by syncengine at startup
- Observe sync timing across multiple cron intervals

**Expected observables:**
- Only the `full` enumerator is selectable/used; no `delta` or `composite` option is exposed or scheduled
- New/changed assets are only reflected after the next full sweep, not sooner
- No delta/composite code path executes in v1
- internal/enumerate/delta/ and count-probe code remain in the tree, unused

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:401-403`

## SCENARIO-0104 — Deletion-sync threshold defaults to off

**Kind:** contract
**Proof seam:** integration
**Owning stories:** STORY-0129

**Preconditions:**
- A fresh config with no explicit deletion_sync_threshold set

**Action:**
- Inspect the resolved deletion_sync_threshold value
- Run deletion-sync with candidates present and threshold still at default

**Expected observables:**
- Value resolves to -1
- Feature behaves as disabled (no deletions proposed/executed due to being off)
- Deletion-mirroring is inert unless an operator has explicitly set a non-default threshold

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:404-406`

## SCENARIO-0105 — China domain account routes to China data-residency endpoints

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0058

**Preconditions:**
- An account is configured with credentials.domain: cn

**Action:**
- The account authenticates and issues CloudKit requests

**Expected observables:**
- Requests target Apple's China data-residency endpoints, not the default global endpoints
- All auth and API traffic for the account is directed at the China-region endpoints

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:189`

## SCENARIO-0106 — Session-expiry warning fires in advance and repeats until resolved

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0009

**Preconditions:**
- An account's session is due to expire in exactly warning_days (7) days
- session_expiry.notification_interval_hours is 24

**Action:**
- The warning_days threshold is crossed
- 24 hours pass with the session still unresolved

**Expected observables:**
- A session-expiry warning notification is sent
- A repeat warning notification is sent
- Warnings continue at the configured interval until the session is renewed

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:187-189`

## SCENARIO-0107 — Missing requested size falls back to original instead of skipping

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0020

**Preconditions:**
- sync_scope.sizes requests a size not available for a given asset

**Action:**
- The engine attempts to download that asset at the requested size
- The engine falls back to the original size

**Expected observables:**
- The requested size is unavailable
- The asset is downloaded as original rather than skipped
- The asset exists locally at original size; it was not skipped

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:216`

## SCENARIO-0108 — Default folder_structure produces Y/m/d layout; none produces flat layout

**Kind:** surface
**Proof seam:** unit
**Owning stories:** STORY-0133

**Preconditions:**
- Account A has no folder_structure set (default)
- Account B has folder_structure: none

**Action:**
- Compute the destination path for an asset created on 2026-09-22 for account A
- Compute the destination path for the same asset for account B

**Expected observables:**
- Path includes a 2026/09/22-style subfolder
- Path has no date-based subfolder; file lands in the flat download root
- Account A's file is nested by date; account B's file is flat

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:76`

## SCENARIO-0109 — Second reply to an already-resolved 2FA prompt is rejected

**Kind:** failure-recovery
**Proof seam:** integration
**Owning stories:** STORY-0027

**Preconditions:**
- A 2FA prompt was sent and its inline reply was already accepted, completing auth

**Action:**
- A second reply is sent to the same prompt message

**Expected observables:**
- The reply is not accepted; no further auth action results from it
- Auth state is unaffected by the second reply

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:386`

## SCENARIO-0110 — Dashboard listens on port 2011 by default when enabled

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0059

**Preconditions:**
- dashboard.enabled: true
- dashboard.port unset

**Action:**
- The service starts

**Expected observables:**
- The dashboard listener binds to port 2011
- The dashboard is reachable at port 2011 without an explicit port override

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:165`

## SCENARIO-0111 — Configuring a Shared Photo Library zone syncs that zone instead of PrimarySync

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0037

**Preconditions:**
- An account's sync_scope.library is set to a Shared Photo Library zone name

**Action:**
- A sync run executes for the account

**Expected observables:**
- Enumeration targets the configured Shared Photo Library zone
- Assets from the Shared Photo Library zone are downloaded; PrimarySync is not synced for this account

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:191`

## SCENARIO-0112 — File_layout knobs each control their respective per-file behavior

**Kind:** surface
**Proof seam:** unit
**Owning stories:** STORY-0134

**Preconditions:**
- An account has live_photo_mov_filename_policy: suffix, align_raw: as-is, keep_unicode_in_filenames: false, set_exif_datetime: false

**Action:**
- Name a Live Photo's companion video file
- Name a RAW file paired with a JPEG
- Generate a filename containing non-ASCII characters
- Write a downloaded file to disk

**Expected observables:**
- Filename is the photo's base name plus a suffix
- RAW keeps its own filename, not aligned to the JPEG
- Non-ASCII characters are transliterated or stripped
- Local mtime/EXIF datetime is left as written by the OS, not overridden from asset metadata
- Each of the four file_layout behaviors matches its configured value

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:202-206`

## SCENARIO-0113 — Retryable and fatal errors are classified distinctly in logs and metrics

**Kind:** contract
**Proof seam:** unit
**Owning stories:** STORY-0018

**Preconditions:**
- A transient network error and a permanent auth failure both occur during a run

**Action:**
- internal/obs processes the transient network error
- internal/obs processes the permanent auth failure

**Expected observables:**
- It is classified as retryable
- It is classified as fatal
- Logs/metrics for the two errors carry distinct retryable-vs-fatal classification

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:109`

## SCENARIO-0114 — SRP handshake verified against known test vectors without network access

**Kind:** contract
**Proof seam:** unit
**Owning stories:** STORY-0001

**Preconditions:**
- A set of known SRP-6a + PBKDF2 s2k test vectors matching Apple's variant is available

**Action:**
- Run the SRP handshake implementation against each test vector, with no network calls involved

**Expected observables:**
- Each computed proof matches the vector's expected output
- SRP correctness is verified entirely offline via test vectors, independent of any live iCloud connection

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:27`

## SCENARIO-0115 — Zone discovery enumerates every zone visible to the account

**Kind:** surface
**Proof seam:** integration
**Owning stories:** STORY-0002

**Preconditions:**
- An account has both a PrimarySync zone and at least one Shared Photo Library zone

**Action:**
- Run zone discovery for the account

**Expected observables:**
- The discovery result includes PrimarySync and every Shared Photo Library zone the account can see
- No zone visible to the account is left undiscovered

**Automation status:** pending
**Execution command:** TBD

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:415`
