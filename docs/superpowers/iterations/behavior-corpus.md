# Behavior Corpus

| Scenario ID | Title | Proof seam | Run cadence | Command | Owning stories |
|---|---|---|---|---|---|
| JOURNEY-0001 | ITER-0000 walking skeleton threads every layer at minimum depth | e2e | sentinel | verified live 2026-09-23 against a real account (20 assets downloaded, correct filenames, manifest rows recorded); no repeatable CI harness yet — that's ITER-0001's job (ckwstest fake server) | STORY-0135 |
| JOURNEY-0002 | run-once is idempotent against the manifest | e2e | sentinel | TBD | STORY-0116 |
| SCENARIO-0001 | Folder-structure change does not trigger re-download | integration | iteration | TBD | STORY-0003 |
| SCENARIO-0002 | Webhook notifier retries then drops on persistent failure | integration | iteration | TBD | STORY-0004 |
| SCENARIO-0003 | Deletion batch requires Telegram approval before submission to Apple | app-level | iteration | TBD | STORY-0006, STORY-0007 |
| SCENARIO-0004 | Routine 2FA expiry prompts only for a code, never a password | app-level | iteration | TBD | STORY-0008 |
| SCENARIO-0005 | Confirmed wrong password notifies without accepting a reply | app-level | iteration | TBD | STORY-0024 |
| SCENARIO-0006 | Two accounts request 2FA codes simultaneously in the same chat | app-level | iteration | TBD | STORY-0023 |
| SCENARIO-0007 | Validate refuses config missing schedule for an account | process-level | iteration | TBD | STORY-0015 |
| SCENARIO-0008 | Manual /sync trigger runs immediately outside the schedule | app-level | iteration | TBD | STORY-0015 |
| SCENARIO-0009 | One hung account does not starve others or flip readiness | app-level | iteration | TBD | STORY-0016, STORY-0017 |
| SCENARIO-0010 | All accounts failing flips readiness to not-ready | app-level | iteration | TBD | STORY-0017 |
| SCENARIO-0011 | Global rate limiter caps total request rate regardless of account count | integration | iteration | TBD | STORY-0016 |
| SCENARIO-0012 | Graceful shutdown allows a download to resume rather than restart | integration | iteration | TBD | STORY-0017, STORY-0019 |
| SCENARIO-0013 | Size mismatch is treated as a failed download | integration | iteration | go test ./internal/download/... -run TestFetch_SizeMismatch_LeavesNoFinalFile | STORY-0019 |
| SCENARIO-0014 | Rotated secret file is picked up live without restart | integration | iteration | TBD | STORY-0021 |
| SCENARIO-0015 | Credential source chain falls back from file to env to memory cache | integration | iteration | TBD | STORY-0022 |
| SCENARIO-0016 | Proactive 2FA refresh succeeds without an on-disk password within same process lifetime | integration | iteration | TBD | STORY-0026 |
| SCENARIO-0017 | Process restart between auth and refresh requires a fresh 2FA prompt | integration | iteration | TBD | STORY-0026 |
| SCENARIO-0018 | Validate refuses missing Telegram bot token | process-level | iteration | TBD | STORY-0025 |
| SCENARIO-0019 | Validate refuses Telegram configured with empty allowed_chat_ids | process-level | iteration | TBD | STORY-0029 |
| SCENARIO-0020 | Any allowed chat can control any account | app-level | iteration | TBD | STORY-0028 |
| SCENARIO-0021 | Container starts serve by default; run-once operates independently | process-level | iteration | go test ./internal/cli/... | STORY-0030 |
| SCENARIO-0022 | Fresh manifest is rebuilt by scanning disk on first run against existing library | integration | iteration | TBD | STORY-0139 |
| SCENARIO-0023 | Delta run cannot mass-prune the manifest when it lacks removal signal | integration | iteration | TBD | STORY-0034 |
| SCENARIO-0024 | Full sweep marks unseen assets removed only on clean completion | integration | iteration | TBD | STORY-0034 |
| SCENARIO-0025 | Composite enumerator runs delta and nightly full through the same engine path | integration | iteration | TBD | STORY-0035 |
| SCENARIO-0026 | Re-visiting assets after server index drift causes no duplicate manifest rows | integration | iteration | TBD | STORY-0036 |
| SCENARIO-0027 | A store write failure aborts the account run while telemetry failures do not | integration | iteration | go test ./internal/syncengine/... | STORY-0038 |
| SCENARIO-0028 | Switching an account from full to delta strategy preserves independent cursors | integration | iteration | TBD | STORY-0039 |
| SCENARIO-0029 | Manifest survives a download-root remount via relative paths | integration | iteration | TBD | STORY-0042 |
| SCENARIO-0030 | Live Photo companion missing does not trigger deletion while the primary file remains | integration | iteration | TBD | STORY-0043 |
| SCENARIO-0031 | An asset becomes a deletion candidate only after two consecutive missing runs | integration | iteration | TBD | STORY-0043 |
| SCENARIO-0032 | Health listener stays reachable while the dashboard is disabled | process-level | iteration | TBD | STORY-0046, STORY-0047 |
| SCENARIO-0033 | Startup fails fast when Telegram is configured without allowed chat IDs | process-level | iteration | TBD | STORY-0048 |
| SCENARIO-0034 | Config validation rejects duplicate or missing account names | process-level | iteration | TBD | STORY-0050 |
| SCENARIO-0035 | Telegram /sync command resolves by account name, never apple_id | integration | iteration | TBD | STORY-0050 |
| SCENARIO-0036 | Credential resolution falls back from file to env for apple_id | integration | iteration | TBD | STORY-0051 |
| SCENARIO-0037 | asset_types opt-in array excludes unlisted types from sync | integration | iteration | TBD | STORY-0052 |
| SCENARIO-0038 | A full sweep never self-reports Exhaustive while date-scoping is absent from config | integration | iteration | TBD | STORY-0053 |
| SCENARIO-0039 | Deletion mirroring is fully inert when disabled, regardless of threshold | integration | iteration | TBD | STORY-0054 |
| SCENARIO-0040 | Cumulative unresolved missing count across runs trips the threshold | integration | iteration | TBD | STORY-0054 |
| SCENARIO-0041 | Config validation rejects an account with no schedule | process-level | iteration | TBD | STORY-0055 |
| SCENARIO-0042 | Deletion detected in sync loop beats the auto-heal race | integration | iteration | TBD | STORY-0060 |
| SCENARIO-0043 | Only exhaustive runs produce deletion candidates | integration | iteration | TBD | STORY-0061 |
| SCENARIO-0044 | Dropped media mount surfaces as a loud manifest mismatch, not a silent reset | integration | iteration | TBD | STORY-0062 |
| SCENARIO-0045 | Liveness sentinel blocks an unmounted-source scan from being authoritative | integration | iteration | TBD | STORY-0063 |
| SCENARIO-0046 | enabled=false suppresses deletion detection regardless of threshold | integration | iteration | TBD | STORY-0064 |
| SCENARIO-0047 | enabled:true with threshold:-1 is uncapped, and validate warns on the unedited example pairing | app-level | iteration | TBD | STORY-0064 |
| SCENARIO-0048 | Slow leak across multiple runs still trips the cumulative threshold | integration | iteration | TBD | STORY-0065 |
| SCENARIO-0049 | Below-threshold deletions run automatically and emit a summary event | integration | iteration | TBD | STORY-0066 |
| SCENARIO-0050 | At-threshold trip withholds the batch and merges later candidates into it | integration | iteration | TBD | STORY-0067 |
| SCENARIO-0051 | Approving a withheld batch re-verifies each item remotely and locally before deleting | integration | iteration | TBD | STORY-0069, STORY-0068 |
| SCENARIO-0052 | Rejecting a withheld batch re-downloads files and pending items stay exempt from auto-redownload until resolved | integration | iteration | TBD | STORY-0068 |
| SCENARIO-0053 | One account's tripped threshold does not withhold another account's deletions | integration | iteration | TBD | STORY-0070 |
| SCENARIO-0054 | A 4,000-item threshold trip pages through Telegram thumbnails 10 at a time | e2e | iteration | TBD | STORY-0071, STORY-0072 |
| SCENARIO-0055 | One hung account does not starve sibling accounts | process-level | iteration | TBD | STORY-0074, STORY-0076, STORY-0075 |
| SCENARIO-0056 | A large file download is not killed by the flat phase timeout | integration | iteration | TBD | STORY-0076 |
| SCENARIO-0057 | Overlapping cron tick is skipped, not queued | process-level | iteration | TBD | STORY-0077 |
| SCENARIO-0058 | Concurrent store writes from multiple accounts queue at a single writer instead of erroring | integration | iteration | TBD | STORY-0078 |
| SCENARIO-0059 | kill -9 during shutdown loses at most one asset | process-level | iteration | TBD | STORY-0079 |
| SCENARIO-0060 | Web dashboard has no working mutation endpoint | integration | iteration | TBD | STORY-0012 |
| SCENARIO-0061 | TestDashboardImportGraph fails the build if a secret-capable package sneaks into the dashboard's dependency tree | unit | iteration | TBD | STORY-0013 |
| SCENARIO-0062 | Dashboard binds loopback by default and requires explicit config for LAN exposure | integration | iteration | TBD | STORY-0014 |
| SCENARIO-0063 | Health/metrics listener stays up and minimal even with the dashboard disabled | integration | iteration | TBD | STORY-0080 |
| SCENARIO-0064 | /readyz stays ready with one hung account and only flips on total failure | integration | iteration | TBD | STORY-0080 |
| SCENARIO-0065 | Health/metrics listener defaults to 0.0.0.0:9090, reachable from outside the pod | integration | iteration | TBD | STORY-0081 |
| SCENARIO-0066 | Operator forces an immediate sync outside the cron schedule | integration | iteration | TBD | STORY-0082 |
| SCENARIO-0067 | Operator approves a pending batch and deletions execute | integration | iteration | TBD | STORY-0083, STORY-0095 |
| SCENARIO-0068 | Operator rejects a pending batch and files re-download | integration | iteration | TBD | STORY-0084, STORY-0092 |
| SCENARIO-0069 | Operator cancels and then resumes an in-progress sync | integration | iteration | TBD | STORY-0085, STORY-0086 |
| SCENARIO-0070 | Operator forces re-authentication of a stuck account | integration | iteration | TBD | STORY-0087 |
| SCENARIO-0071 | Operator reads account status without side effects | integration | iteration | TBD | STORY-0088 |
| SCENARIO-0072 | Command targeting the wrong or missing account does not affect other accounts | integration | iteration | TBD | STORY-0089 |
| SCENARIO-0073 | Circuit breaker trip sends a paginated photo album of deletion candidates | integration | iteration | TBD | STORY-0090, STORY-0091 |
| SCENARIO-0074 | New run merges candidates into the existing pending batch and re-notifies only on genuinely new items | integration | iteration | TBD | STORY-0093, STORY-0094 |
| SCENARIO-0075 | Config rotation via atomic symlink swap is detected after debounce | integration | iteration | TBD | STORY-0098 |
| SCENARIO-0076 | Login succeeds against Apple's SRP variant using the hand-rolled implementation | integration | iteration | TBD | STORY-0100 |
| SCENARIO-0077 | Config file with an unknown field is rejected at load | unit | iteration | TBD | STORY-0101 |
| SCENARIO-0078 | print-config attributes each field to its source layer | integration | iteration | TBD | STORY-0103 |
| SCENARIO-0079 | Fixture older than 90 days fails the codec test suite | unit | iteration | TBD | STORY-0104 |
| SCENARIO-0080 | Reachability guard catches a record type replaced without new fixtures | unit | iteration | TBD | STORY-0105 |
| SCENARIO-0081 | Mirror/paging logic handles a 503 mid-pagination via ckwstest fault injection | integration | iteration | TBD | STORY-0106 |
| SCENARIO-0082 | Operator runs check-protocol by hand and gets a pass/fail with no CI involvement | integration | iteration | TBD | STORY-0107 |
| SCENARIO-0083 | Mirror refuses to submit when the entire library disappears in one run | integration | iteration | TBD | STORY-0109 |
| SCENARIO-0084 | Static build produces a minimal, working binary and image | process-level | iteration | TBD | STORY-0112 |
| SCENARIO-0085 | Test suite enforces dashboard import isolation and fixture health | integration | iteration | TBD | STORY-0113 |
| SCENARIO-0086 | check-protocol asserts real-account response structure | e2e | iteration | TBD | STORY-0114 |
| SCENARIO-0087 | Config validation rejects malformed config; print-config shows provenance | e2e | iteration | TBD | STORY-0115 |
| SCENARIO-0088 | Renaming the folder-structure setting does not trigger re-download | e2e | iteration | TBD | STORY-0116 |
| SCENARIO-0089 | docker stop mid-run exits clean within grace period | process-level | iteration | TBD | STORY-0117 |
| SCENARIO-0090 | Secret rotation is picked up without restart | process-level | iteration | TBD | STORY-0118 |
| SCENARIO-0091 | Dashboard port scan finds no credential form or mutating endpoint | e2e | iteration | TBD | STORY-0119 |
| SCENARIO-0092 | Wrong password and 2FA prompts escalate only through Telegram | e2e | iteration | TBD | STORY-0119 |
| SCENARIO-0093 | Deletion dry-run refuses on unreadable sentinel | e2e | iteration | TBD | STORY-0120 |
| SCENARIO-0094 | Grouped-asset deletion candidacy requires every sibling missing | integration | iteration | TBD | STORY-0121 |
| SCENARIO-0095 | Deletion candidacy requires a full enumeration sweep | integration | iteration | TBD | STORY-0122 |
| SCENARIO-0096 | Threshold breach withholds all deletions and trips a persistent circuit breaker | e2e | iteration | TBD | STORY-0123 |
| SCENARIO-0097 | New candidates merge into an existing pending batch | integration | iteration | TBD | STORY-0124 |
| SCENARIO-0098 | Reject restores files; pending items stay untouched | e2e | iteration | TBD | STORY-0125 |
| SCENARIO-0099 | Approval re-verifies remote state before executing | integration | iteration | TBD | STORY-0126 |
| SCENARIO-0100 | Threshold trips and command targeting are scoped per account | integration | iteration | TBD | STORY-0127 |
| SCENARIO-0101 | Large deletion batches page via Telegram and approve without full review | e2e | iteration | TBD | STORY-0128 |
| SCENARIO-0102 | Metrics and readiness probes reflect real per-account sync state | integration | iteration | TBD | STORY-0130 |
| SCENARIO-0103 | v1 syncs exclusively via full sweep on the cron interval | integration | iteration | TBD | STORY-0131 |
| SCENARIO-0104 | Deletion-sync threshold defaults to off | integration | iteration | TBD | STORY-0129 |
| SCENARIO-0105 | China domain account routes to China data-residency endpoints | integration | iteration | TBD | STORY-0058 |
| SCENARIO-0106 | Session-expiry warning fires in advance and repeats until resolved | integration | iteration | TBD | STORY-0009 |
| SCENARIO-0107 | Missing requested size falls back to original instead of skipping | integration | iteration | TBD | STORY-0020 |
| SCENARIO-0108 | Default folder_structure produces Y/m/d layout; none produces flat layout | unit | iteration | TBD | STORY-0133 |
| SCENARIO-0109 | Second reply to an already-resolved 2FA prompt is rejected | integration | iteration | TBD | STORY-0027 |
| SCENARIO-0110 | Dashboard listens on port 2011 by default when enabled | integration | iteration | TBD | STORY-0059 |
| SCENARIO-0111 | Configuring a Shared Photo Library zone syncs that zone instead of PrimarySync | integration | iteration | TBD | STORY-0037 |
| SCENARIO-0112 | File_layout knobs each control their respective per-file behavior | unit | iteration | TBD | STORY-0134 |
| SCENARIO-0113 | Retryable and fatal errors are classified distinctly in logs and metrics | unit | iteration | TBD | STORY-0018 |
| SCENARIO-0114 | SRP handshake verified against known test vectors without network access | unit | iteration | go test ./internal/icloud/srp/... | STORY-0001 |
| SCENARIO-0115 | Zone discovery enumerates every zone visible to the account | integration | iteration | TBD | STORY-0137 |
| SCENARIO-0116 | Asset bytes are fetched and atomically written to their final path | integration | iteration | go test ./internal/download/... -run TestFetch_HappyPath | STORY-0136 |
| SCENARIO-0117 | Enumerator Capabilities and Cursor contract holds for the full enumerator | unit | iteration | go test ./internal/enumerate/full/... | STORY-0033 |
| SCENARIO-0118 | Single shared SQLite DB opens regardless of configured account count | integration | iteration | go test ./internal/store/sqlite/... -run TestOneSharedDB | STORY-0040 |
| SCENARIO-0119 | Duplicate CPLAsset records collapse to one manifest row by CPLMaster recordName | integration | iteration | go test ./internal/store/sqlite/... -run TestSameCPLMasterKey | STORY-0041 |
| SCENARIO-0120 | print-config prints the effective config with secrets redacted | process-level | iteration | TBD | STORY-0138 |
| SCENARIO-0121 | Operator runs check-protocol against the walking-skeleton auth path | integration | iteration | go run ./cmd/icloudpd check-protocol (live, PASSED 2026-09-22) | STORY-0001 |
