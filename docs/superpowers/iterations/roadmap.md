# Roadmap

## Walking skeleton (ITER-0000)

**Intent:** Authenticate against iCloud with the hand-rolled SRP client, enumerate exactly one asset, download it with checksum verification, record it in the manifest, and exit cleanly — the thinnest possible slice that threads every architectural layer (protocol → engine → download → store → CLI) at once.

**Design rationale:** This is the highest-risk path in the whole rewrite. SRP has no usable Go reference implementation, so validating it end-to-end with working software (rather than a throwaway spike) retires the single biggest unknown before any other iteration depends on it. Every other layer in the skeleton (Enumerator interface, HTTP fetch + checksum-verified download, manifest write, run-once CLI) is the minimum needed to make that first real download observable and provable, and each is a foundational seam every later iteration builds on directly — nothing here is disposable scaffolding.

**Scope revisions from PAR review:** Two independent scope reviewers found the initial story selection carried avoidable weight and one real gap. Applied:
- Split STORY-0002 → kept AC-1 (desiredKeys) here; deferred AC-2 (enumerate *all* zones, not just PrimarySync) to STORY-0137 in ITER-0001 — the single-asset journey only needs PrimarySync.
- Split STORY-0030 → kept only the `serve`-by-default and no-`migrate` ACs here; deferred `validate`/`print-config`/`auth-only`/`list-albums`/`list-libraries` to STORY-0138 in ITER-0002, since `validate`/`print-config` need config-schema validation that doesn't exist yet.
- Split STORY-0031 → kept only "session data under state_dir, no legacy cookie read" here; deferred the disk-rescan-rebuild AC to STORY-0139 in ITER-0003, since it needs `internal/scan` and the skeleton's fresh-account journey never exercises reconciling an existing library.
- Split STORY-0041 → kept only "identify by CPLMaster recordName" here; deferred the addedDate-collision policy and last_seen_run/removed_remote_utc tracking to STORY-0140 in ITER-0003, since a single-asset run never produces a duplicate or a removal to prove those ACs against.
- Added STORY-0136 (new) — the actual HTTP fetch-and-atomic-write mechanism was a real gap: STORY-0019 only covered post-download checksum verification, and no story governed the fetch itself.
- Added STORY-0132 (EPIC-039, already extracted, previously unscheduled) — the composition-root/narrow-options-struct discipline (`internal/app` builds `syncengine.Options` etc., never passes the whole config struct into the engine) is exactly the failure mode the spec calls "most likely wrong," and is cheapest to establish in the very first iteration that does any wiring.

**Non-goals, stated explicitly so they aren't silently assumed proven:**
- This iteration proves the `Enumerator`/`Capabilities` *type contract* (STORY-0033) via a single, first-ever run. It does **not** exercise the capability-gated removal/reconciliation branching (an asset present in a prior manifest but absent from a new enumeration) — that requires a second run against a stale manifest, which ITER-0003's core-sync work will cover with a dedicated two-run scenario.
- JOURNEY-0001's initial proof-run requires a real iCloud account and live credentials (SRP/2FA cannot be faked). Repeatable CI verification of the protocol layer without live credentials — via `ckwstest`'s fake CloudKit server and codec fixtures — is ITER-0001's job, not this iteration's.

**Journey scenario:** JOURNEY-0001 — ITER-0000 walking skeleton threads every layer at minimum depth

**Stories committed:**
- STORY-0001 (EPIC-001 — Protocol client): Build hand-rolled Go iCloud protocol client
- STORY-0002 (EPIC-001 — Protocol client): Port CloudKit desiredKeys from the reference client (zone discovery narrowed — see STORY-0137)
- STORY-0033 (EPIC-019 — Enumeration seam): Model enumeration as a change stream with capability declaration
- STORY-0136 (EPIC-012 — Download integrity): Fetch an asset's bytes to a temp file and atomically rename into place
- STORY-0019 (EPIC-012 — Download integrity): Verify downloaded bytes against Apple's fileChecksum
- STORY-0040 (EPIC-021 — Manifest schema): Use one shared SQLite manifest DB for the whole service
- STORY-0041 (EPIC-021 — Manifest schema): Identify assets by CPLMaster recordName (collision policy narrowed — see STORY-0140)
- STORY-0038 (EPIC-020 — Store failure semantics): Treat store write failures as fatal run errors
- STORY-0030 (EPIC-017 — Delivery): Ship a single binary defaulting to serve, with run-once and check-protocol available
- STORY-0031 (EPIC-017 — Delivery): Store session data under state_dir with no legacy porting
- STORY-0132 (EPIC-039 — Architecture Discipline): Keep internal/config out of the sync engine's API surface
- STORY-0135 (EPIC-041 — Process model): Scope the walking skeleton as the first iteration

**Status:** pending

## Iteration list

### ITER-0001 — Protocol hardening and test infrastructure

**Stories:** STORY-0137 (deferred from ITER-0000: enumerate all zones, not just PrimarySync), plus all remaining stories in EPIC-006 (Credentials and session), EPIC-013 (Secrets), EPIC-014 (Credentials), EPIC-015 (Credentials escalation), EPIC-016 (Access control), EPIC-034 (Secret Management), EPIC-029 (Testing infrastructure), EPIC-028 (Libraries and build constraints), EPIC-018 (Architecture)
**Rationale:** Per the spec's own rough ordering, harden the protocol layer next: fixture freshness/reachability guards and the fake CloudKit server (`ckwstest`) must exist before `syncengine` is built on top of them, and this is also the natural home for the credential/secret/2FA machinery the skeleton's auth path stubbed past (watched-file secrets, 2FA escalation, access control on `allowed_chat_ids`). Architectural boundary enforcement (import-graph tests, package layout discipline) belongs here too since it's cheapest to lock in before more packages exist to violate it.
**Status:** pending
**Impacted scenarios:** SCENARIO IDs owned by the stories in these epics (see behavior-scenarios.md); no journey scenarios beyond JOURNEY-0001.
**Look-ahead check:** Blocks ITER-0002 (config schema needs the credential model finalized) and ITER-0004 (Telegram bot commands need the 2FA escalation and access-control stories done first).

### ITER-0002 — Config schema and CLI surface

**Stories:** STORY-0138 (deferred from ITER-0000: validate/print-config/auth-only/list-albums/list-libraries), plus all remaining stories in EPIC-022 (Config schema), EPIC-031 (Configuration Management)
**Rationale:** `validate`, `print-config`, and per-field provenance are needed before any account can be configured beyond the skeleton's minimal implicit setup, and the config schema is a dependency almost every later iteration reads from (deletion_sync keys, schedule, dashboard/health binds, telegram block). Getting this right early avoids config-shape churn later.
**Status:** pending
**Impacted scenarios:** Config-schema-sourced SCENARIOs (see behavior-scenarios.md).
**Look-ahead check:** Depends on ITER-0001's credential model being settled (apple_id_env, domain field). Blocks every later iteration that reads a config key not yet wired (deletion_sync, dashboard, telegram, health).

### ITER-0003 — Core sync engine

**Stories:** STORY-0139 (deferred from ITER-0000: rebuild manifest by scanning disk), STORY-0140 (deferred from ITER-0000: addedDate-collision policy + removal tracking), plus all remaining stories in EPIC-002 (Asset manifest), EPIC-019 (Enumeration seam remainder), EPIC-020 (Store failure semantics remainder), EPIC-021 (Manifest schema remainder), EPIC-024 (Concurrency), EPIC-009 (Scheduling), EPIC-010 (Multi-account concurrency), EPIC-012 (Download integrity remainder), EPIC-032 (Sync Idempotency & Manifest Integrity), EPIC-038 (Enumerator Strategy v1 scope), EPIC-040 (Naming), EPIC-018 remainder if any
**Rationale:** This is "core sync" in the spec's own ordering: `naming`, `store`, `enumerate/full`, `download`, `syncengine`, and the concurrency/scheduling model that makes multi-account sync real (goroutine-per-account, global rate limiter, cron scheduling, single-writer SQLite). This iteration also delivers the two-run reconciliation scenario deferred from ITER-0000's non-goals (a stale manifest asset absent from a new enumeration, correctly gated by `Exhaustive`/`ReportsRemovals`), since it's the first iteration where a second real sync run against an existing manifest actually occurs. This is the largest and most central iteration; expect it to be decomposed further once it starts, per the story-splitting rule if any AC here turns out to depend on a later iteration's service surface.
**Status:** pending
**Impacted scenarios:** Manifest-idempotency and concurrency-related SCENARIOs (see behavior-scenarios.md).
**Look-ahead check:** Depends on ITER-0002's config schema being final. Blocks ITER-0005 (deletion-mirroring detection lives inside syncengine) and ITER-0006 (XMP sidecar generation happens during download).

### ITER-0004 — Service surface: notify, control, status, dashboard

**Stories:** All remaining stories in EPIC-003 (Notifications), EPIC-008 (Web UI), EPIC-011 (Operability), EPIC-025 (Health/metrics), EPIC-026 (Telegram bot commands), EPIC-033 (Process Lifecycle & Reliability), EPIC-035 (Dashboard Security), EPIC-037 (Observability), EPIC-030 (Build & Release Verification, partial — the parts that need the dashboard/notify surfaces to exist)
**Rationale:** Per the spec's rough ordering, service surface comes after core sync: the Telegram bot commands (`/sync`, `/cancel`, `/status`, etc.) need a real `internal/control` command bus and a real sync engine to act on; the dashboard needs `internal/status` and real running accounts to display. Health/metrics and graceful shutdown are also natural here since they observe the sync engine built in ITER-0003.
**Status:** pending
**Impacted scenarios:** Telegram-command and dashboard/health SCENARIOs (see behavior-scenarios.md).
**Look-ahead check:** Depends on ITER-0001 (2FA/access-control) and ITER-0003 (a real syncengine to control). Blocks ITER-0005 (deletion-sync review surface reuses the Telegram bot command bus built here).

### ITER-0005 — Deletion mirroring

**Stories:** All remaining stories in EPIC-004 (Deletion mirroring), EPIC-005 (Deletion mirroring review surface), EPIC-023 (Deletion-mirroring), EPIC-027 (Deletion-sync review surface), EPIC-036 (Deletion-Sync Safety)
**Rationale:** The spec calls this "the most dangerous feature" and explicitly locks in its design as carried-forward, not open for re-derivation — but it structurally depends on syncengine's detection hook (ITER-0003) and the Telegram bot command bus (ITER-0004) for its review/approve/reject surface. Doing it last among functional epics matches the spec's own rough ordering and lets it build on a proven sync loop rather than co-evolving with one.
**Status:** pending
**Impacted scenarios:** Deletion-sync circuit-breaker, review-surface, and safety SCENARIOs (see behavior-scenarios.md) — the largest single cluster of scenarios in the corpus.
**Look-ahead check:** Depends on ITER-0003 (syncengine detection hook) and ITER-0004 (Telegram bot command bus, review-surface pagination). No known downstream blockers — this is the last functional epic per the spec's ordering.

### ITER-0006 — XMP sidecars

**Stories:** All remaining stories in EPIC-007 (XMP sidecars)
**Rationale:** Small, self-contained epic (the #32 fixture-driven typed-error decoding requirement) that the spec explicitly places last in its rough ordering, after mirror. It has no dependents and depends only on the download pipeline from ITER-0003.
**Status:** pending
**Impacted scenarios:** None beyond the story's own ACs (behavioral_impact: local, proof_seam: unit) — no dedicated scenario was extracted for this epic beyond unit-level fixture tests.
**Look-ahead check:** Depends on ITER-0003's download pipeline. No blockers downstream.

### ITER-0007 — Release verification and hardening

**Stories:** Remaining stories in EPIC-030 (Build & Release Verification) not already covered in ITER-0004
**Rationale:** Final cross-cutting pass: static-binary build verification, dashboard import-graph enforcement, and the manual `check-protocol` command all validate properties of the *whole* system, so they're revisited once every other iteration has landed rather than being a standalone feature iteration.
**Status:** pending
**Impacted scenarios:** Build/verification SCENARIOs (see behavior-scenarios.md).
**Look-ahead check:** Depends on every prior iteration being substantially complete. No downstream blockers.
