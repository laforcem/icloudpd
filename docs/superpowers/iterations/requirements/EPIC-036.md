# EPIC-036 — Deletion-Sync Safety

**Summary:** Deletion-Sync Safety
**Stories:** STORY-0120, STORY-0121, STORY-0122, STORY-0123, STORY-0124, STORY-0125, STORY-0126, STORY-0127, STORY-0128, STORY-0129
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/10 done

## STORY-0120

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Refuse deletion dry-runs when the download root is unreadable

**As a** operator
**I want** deletion-sync to refuse rather than propose deletions when its sentinel file cannot be read
**So that** an unmounted or unhealthy volume is never mistaken for mass user deletion

**Acceptance criteria:**
- AC-1: A dry-run against a download root whose volume is unmounted (sentinel unreadable) refuses, rather than proposing deletions. · impact:`journey` · seam:`e2e` · scenario:`SCENARIO-0093`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:388-389`

**Status:** pending

## STORY-0121

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Require every sibling of a grouped asset to be missing before proposing its deletion

**As a** operator
**I want** deletion candidacy for Live Photo pairs, multi-size sets, and RAW+JPEG sets to require all group members to be missing locally
**So that** a partial local deletion within a grouped asset never triggers an unwanted remote deletion

**Acceptance criteria:**
- AC-1: Deleting one local file of a Live Photo pair produces no deletion candidate. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0094`
- AC-2: Deleting both files of a Live Photo pair produces a deletion candidate. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0094`
- AC-3: The same all-or-nothing behavior holds for multi-size sets and RAW+JPEG sets. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0094`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:390`

**Status:** pending

## STORY-0122

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Require a full sweep before treating a missing asset as a deletion candidate

**As a** operator
**I want** a truncated enumeration pass to never produce deletion candidates
**So that** an incomplete listing of remote state can never be mistaken for confirmed absence

**Acceptance criteria:**
- AC-1: Deleting a file then running with a truncated enumerator (Exhaustive: false) produces no deletion candidate. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0095`
- AC-2: Running a full sweep after the same deletion produces a deletion candidate. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0095`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:391`

**Status:** pending

## STORY-0123

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Trip a circuit breaker when deletions exceed a threshold, and persist the trip

**As a** operator
**I want** a deletion batch exceeding the configured threshold to execute nothing and stay flagged until resolved
**So that** a mass-deletion scenario can never execute silently and always leaves a visible, persistent alarm

**Acceptance criteria:**
- AC-1: Exceeding the threshold executes zero deletions and withholds the batch. · impact:`journey` · seam:`e2e` · scenario:`SCENARIO-0096`
- AC-2: `deletion_sync_threshold_tripped` fires with real thumbnails delivered in Telegram. · impact:`cross-surface` · seam:`e2e` · scenario:`SCENARIO-0096`
- AC-3: The tripped state persists across a subsequent run. · impact:`journey` · seam:`e2e` · scenario:`SCENARIO-0096`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:392`

**Status:** pending

## STORY-0124

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Merge newly discovered deletion candidates into a still-pending batch

**As a** operator
**I want** additional candidates found while a batch is pending to merge into that batch rather than open a new one
**So that** I only ever have one pending decision per account instead of a queue of overlapping batches

**Acceptance criteria:**
- AC-1: When a second run finds more candidates while a batch is pending, they merge into the same batch rather than opening a second batch. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0097`
- AC-2: A re-notify fires reflecting the updated candidate count. · impact:`cross-surface` · seam:`e2e` · scenario:`SCENARIO-0097`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:393`

**Status:** pending

## STORY-0125

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Let an operator reject a pending deletion batch and hold undecided items untouched

**As a** operator
**I want** to reject a pending batch and have those files come back, while undecided items are neither deleted nor re-downloaded
**So that** I retain full control over ambiguous deletion decisions without accidental churn

**Acceptance criteria:**
- AC-1: `/reject <account>` (or `--resolve-deletions=reject`) causes the rejected files to re-download on the next pass. · impact:`journey` · seam:`e2e` · scenario:`SCENARIO-0098`
- AC-2: Pending items are not auto-re-downloaded while undecided. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0098`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:394`

**Status:** pending

## STORY-0126

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Re-verify each deletion candidate's remote state immediately before executing approval

**As a** operator
**I want** approval-time re-verification against iCloud before any deletion executes
**So that** a stale decision can't delete something that has since changed, and a since-deleted asset is never treated as an error

**Acceptance criteria:**
- AC-1: Approving a batch after the asset was mutated in iCloud triggers a fresh `recordChangeTag` fetch and submits successfully. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0099`
- AC-2: Approving a batch whose asset was deleted in iCloud in the meantime marks that item skipped, not an error. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0099`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:395`

**Status:** pending

## STORY-0127

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Scope deletion-sync thresholds and commands per account

**As a** operator running multiple accounts
**I want** one account's tripped threshold to not block another account's deletions, and approve/reject commands to require an explicit account
**So that** a problem in one account's library can't stall unrelated accounts, and ambiguous commands never silently apply to the wrong account

**Acceptance criteria:**
- AC-1: Tripping account A's threshold does not stop account B's deletions from proceeding. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0100`
- AC-2: `/approve` or `/reject` issued without an account argument is rejected as ambiguous. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0100`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:396`

**Status:** pending

## STORY-0128

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Allow paged review of large deletion batches via Telegram

**As a** operator
**I want** a batch over 10 items to page in both directions, and be able to approve without paging through everything
**So that** reviewing a large batch is practical inside Telegram's interface without forcing exhaustive review before acting

**Acceptance criteria:**
- AC-1: A batch over 10 items pages in both directions via inline buttons. · impact:`local` · seam:`e2e` · scenario:`SCENARIO-0101`
- AC-2: `/approve` succeeds without requiring the operator to have paged through the whole batch first. · impact:`local` · seam:`e2e` · scenario:`SCENARIO-0101`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:397`

**Status:** pending

## STORY-0129

**Epic:** EPIC-036 — Deletion-Sync Safety
**Title:** Keep deletion-mirroring opt-in by default

**As a** maintainer
**I want** the deletion-sync threshold to default to off
**So that** no operator is exposed to remote-deletion behavior without explicitly enabling it

**Acceptance criteria:**
- AC-1: The deletion-sync threshold defaults to `-1` (off), so deletion-mirroring is disabled unless an operator explicitly opts in. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0104`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:404-406`

**Status:** pending