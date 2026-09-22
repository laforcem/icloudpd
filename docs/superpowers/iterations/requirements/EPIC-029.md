# EPIC-029 — Testing infrastructure

**Summary:** Testing infrastructure
**Stories:** STORY-0104, STORY-0105, STORY-0106, STORY-0107, STORY-0108, STORY-0109, STORY-0110, STORY-0111
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/8 done

## STORY-0104

**Epic:** EPIC-029 — Testing infrastructure
**Title:** Enforce codec fixture freshness to catch stale-cassette drift

**As a** maintainer
**I want** codec fixtures older than 90 days to fail the test suite loudly, with a -tags=stale escape hatch
**So that** a protocol drift like the 2023 record-type replacement can't silently go untested for years

**Acceptance criteria:**
- AC-1: A codec fixture whose recorded_at metadata is more than 90 days old causes its test to fail, unless the test binary is built with -tags=stale. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0079`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:337-341`

**Status:** pending

## STORY-0105

**Epic:** EPIC-029 — Testing infrastructure
**Title:** Enforce codec fixture reachability to catch untested record types

**As a** maintainer
**I want** a guard verifying every record type the client can emit has at least one fixture, and every fixture corresponds to an emittable type
**So that** a new or replaced record type (like CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted in 2023) can never ship without codec coverage

**Acceptance criteria:**
- AC-1: The reachability guard fails when any record type the client can emit lacks a corresponding fixture, or when a fixture references a record type the client no longer emits. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0080`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:339-341`

**Status:** pending

## STORY-0106

**Epic:** EPIC-029 — Testing infrastructure
**Title:** Fake CloudKit server for pagination-under-mutation testing

**As a** maintainer
**I want** a programmable in-memory fake CloudKit server (ckwstest) with fault injectors for mid-pagination mutation, duplicate CPLAssets, stale syncToken, 503-on-page-three, and expired cookie
**So that** engine/paging/retry/mirror logic can be tested under conditions no recorded cassette can express

**Acceptance criteria:**
- AC-1: ckwstest supports injecting each of: assets mutated mid-pagination, duplicate CPLAssets per master, a stale syncToken, a 503 response on page three, and an expired cookie. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0081`
- AC-2: All engine, paging, retry, and mirror tests exercise these scenarios against ckwstest rather than recorded HTTP cassettes. · impact:`none` · seam:`process-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:342-343`

**Status:** pending

## STORY-0107

**Epic:** EPIC-029 — Testing infrastructure
**Title:** Manual live protocol check via check-protocol subcommand

**As a** maintainer
**I want** icloudpd check-protocol to authenticate through the normal credential flow (including Telegram 2FA) and assert only response structure, run manually rather than on a schedule
**So that** I can check for Apple protocol drift on demand without needing a second credentialed account or risking an unattended CI job stalling on a 2FA prompt

**Acceptance criteria:**
- AC-1: check-protocol authenticates using the same real-account credential flow as a normal run, including Telegram-based 2FA. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0082`
- AC-2: check-protocol asserts only response structure, never content, and prints a pass/fail result. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0082`
- AC-3: check-protocol is not invoked by any scheduled/nightly CI job; it exists only as a manually-run CLI subcommand. · impact:`none` · seam:`process-level`
- AC-4: A successful check-protocol run regenerates tier-1, shared-redaction fixtures as a side effect. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0082`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:344-346`

**Status:** pending

## STORY-0108

**Epic:** EPIC-029 — Testing infrastructure
**Title:** Exhaustive table-driven coverage for naming and xmp

**As a** maintainer
**I want** exhaustive table-driven tests for the naming and xmp modules
**So that** edge cases in filename generation and XMP handling are systematically covered

**Acceptance criteria:**
- AC-1: The naming and xmp packages each have exhaustive table-driven test suites covering their input space. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:347`

**Status:** pending

## STORY-0109

**Epic:** EPIC-029 — Testing infrastructure
**Title:** Mirror refuses to submit when all files vanish at once

**As a** operator relying on the deletion-sync mirror
**I want** the mirror to refuse to submit a deletion batch when every previously-known file disappears in a single run
**So that** a bug, outage, or misconfiguration can't be mistaken for a legitimate mass deletion and wipe the mirrored library

**Acceptance criteria:**
- AC-1: When a run finds that all previously-tracked files are absent, the mirror refuses to submit a deletion batch for that run rather than treating it as a bulk-delete candidate. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0083`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:347`

**Status:** pending

## STORY-0110

**Epic:** EPIC-029 — Testing infrastructure
**Title:** Import-graph tests enforce package architecture

**As a** maintainer
**I want** import-graph tests that verify package dependency structure
**So that** architectural boundaries between packages are enforced automatically

**Acceptance criteria:**
- AC-1: Import-graph tests fail the build when a package dependency violates the intended architectural layering. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:347`

**Status:** pending

## STORY-0111

**Epic:** EPIC-029 — Testing infrastructure
**Title:** Injected Clock removes real sleeps from schedule tests

**As a** maintainer
**I want** the schedule package to take an injected Clock
**So that** schedule tests never sleep in real wall-clock time

**Acceptance criteria:**
- AC-1: schedule package tests run to completion without any real-time sleep, using an injected Clock to advance simulated time. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:347`

**Status:** pending