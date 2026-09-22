# EPIC-001 — Protocol client

**Summary:** Protocol client
**Stories:** STORY-0001, STORY-0002, STORY-0137
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 2/3 done

## STORY-0001

**Epic:** EPIC-001 — Protocol client
**Title:** Build hand-rolled Go iCloud protocol client

**As a** maintainer of the rewrite
**I want** a from-scratch Go implementation of the iCloud SRP auth and CloudKit web-service protocol, with no dependency on an upstream Go library
**So that** the project is not blocked on a dead/incompatible third-party library and owns its own protocol drift

**Acceptance criteria:**
- AC-1: The binary contains a self-implemented SRP-6a + PBKDF2 s2k client and CloudKit web-service (ckws) transport; no import of chyroc/icloudgo, gophotocloud, or lukasmalkmus/icloud-go appears in go.mod. · impact:`none` · seam:`unit`
- AC-2: SRP handshake logic is implemented as pure functions with no HTTP dependency, verifiable against known SRP-6a test vectors independent of network access. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0114`
- AC-3: A manual `check-protocol` command exists to verify live Apple protocol structure against the reverse-engineered client without requiring CI or a dedicated test account. · impact:`process-level` · seam:`process-level` · scenario:`SCENARIO-0121`

**Citation fix (ITER-0000 PAR scope review):** AC-3 previously cited SCENARIO-0114, which is explicitly offline ("no network calls involved") — the opposite of AC-3's live-verification subject. SCENARIO-0082 ("Operator runs check-protocol by hand...") is the closer existing match by title, but its observables (Telegram-driven 2FA prompt, tier-1 fixture regeneration) assume infrastructure STORY-0107/ITER-0001 builds, not present yet in this iteration. Added scenario:`SCENARIO-0121` — a thin walking-skeleton version of the same check (auth via the SRP flow this iteration builds, pass/fail printed, no CI, no fixture regen, no Telegram 2FA loop since that infra is deferred to ITER-0001).

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:17-29`

**Status:** done:ITER-0000

## STORY-0002

**Epic:** EPIC-001 — Protocol client
**Title:** Port CloudKit desiredKeys and zone discovery from the reference client

**As a** engine developer
**I want** internal/icloud/ckws to request the same desiredKeys field set as the Python reference client
**So that** the Go client requests exactly the fields it needs from CloudKit

**Acceptance criteria:**
- AC-1: Records/query requests issued by internal/icloud/ckws include the same desiredKeys field set as src/pyicloud_ipd/services/photos.py's photos_request. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:415`

**Status:** done:ITER-0000

## STORY-0137

**Epic:** EPIC-001 — Protocol client
**Title:** Discover every zone visible to the account, not just PrimarySync

**As a** engine developer
**I want** zone discovery to enumerate all zones visible to the account, including Shared Photo Libraries
**So that** the Go client can sync shared zones the way the reference implementation does

**Acceptance criteria:**
- AC-1: Zone discovery enumerates all zones visible to the account, not just PrimarySync, matching the reference client's zone-discovery behavior. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0115`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:415`

**Split note:** split from STORY-0002 during ITER-0000 scope review — full multi-zone discovery is scope creep against the walking skeleton's single-asset-from-PrimarySync journey; deferred to the iteration that introduces shared-zone sync.

**Status:** pending