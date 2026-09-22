# EPIC-027 — Deletion-sync review surface

**Summary:** Deletion-sync review surface
**Stories:** STORY-0090, STORY-0091, STORY-0092, STORY-0093, STORY-0094, STORY-0095
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/6 done

## STORY-0090

**Epic:** EPIC-027 — Deletion-sync review surface
**Title:** Present deletion candidates as live photo messages

**As a** bot operator reviewing pending deletions
**I want** the bot to send batch items as real Telegram photo messages (THUMB-size JPEGs, up to 10 per album), fetched live and never stored on disk
**So that** I can visually verify exactly what will be deleted, not just read filenames

**Acceptance criteria:**
- AC-1: When a batch trips the circuit breaker or is updated, the bot sends up to 10 THUMB-size JPEGs per message as a real Telegram photo album, fetched live and not persisted to disk. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0073`
- AC-2: Video records display their JPEG poster-frame in the same photo field as image records, requiring no photo/video branching logic. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0073`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:312-315`

**Status:** pending

## STORY-0091

**Epic:** EPIC-027 — Deletion-sync review surface
**Title:** Paginate deletion review thumbnails without forcing full review

**As a** bot operator reviewing a large pending batch
**I want** inline 'next 10' / 'previous 10' buttons to walk the batch in either direction
**So that** I can review at my own pace without the bot forcing me through every item before I can approve

**Acceptance criteria:**
- AC-1: Inline pagination buttons ('next 10' / 'previous 10') walk the pending batch in either direction. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0073`
- AC-2: Approving a batch does not require having paged through every item first. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0073`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:316`

**Status:** pending

## STORY-0092

**Epic:** EPIC-027 — Deletion-sync review surface
**Title:** All-or-nothing approve/reject for deletion batches

**As a** bot operator
**I want** approve/reject to apply to the whole pending batch, with no per-item selection
**So that** the state machine stays simple, and a mistaken rejection just re-downloads and re-evaluates next run

**Acceptance criteria:**
- AC-1: Approve applies to every item in the pending batch at once; there is no per-item selection mechanism. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0068`
- AC-2: Reject discards the entire pending batch; a rejected item re-downloads and is re-evaluated on the next run if it is still actually gone. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0068`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:317`

**Status:** pending

## STORY-0093

**Epic:** EPIC-027 — Deletion-sync review surface
**Title:** Merge new deletion candidates into the single pending batch per account

**As a** bot operator
**I want** new candidates found on a later run to merge into the same pending batch
**So that** an account never has two competing pending batches open at once

**Acceptance criteria:**
- AC-1: At most one pending deletion-sync batch exists per account at a time; a later run's new candidates merge into that existing batch instead of opening a second one. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0074`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:318`

**Status:** pending

## STORY-0094

**Epic:** EPIC-027 — Deletion-sync review surface
**Title:** Dedup batch updates: silent re-confirmation vs. re-notify

**As a** bot operator
**I want** the bot to only re-notify me when genuinely new deletion candidates appear, not on every re-confirmation of already-known ones
**So that** I never approve against a stale count and am not spammed by redundant notifications

**Acceptance criteria:**
- AC-1: A run checks each candidate's record_name against the account's mirror_items rows already in the pending batch; an item still missing that is already present in mirror_items is a silent re-confirmation with no notification sent. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0074`
- AC-2: A candidate record_name not already present in the pending batch's mirror_items is genuinely new and triggers a re-notify message with the updated total count and a fresh page of thumbnails. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0074`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:318`

**Status:** pending

## STORY-0095

**Epic:** EPIC-027 — Deletion-sync review surface
**Title:** Re-verify recordChangeTag at approval time regardless of batch history

**As a** bot operator approving a deletion batch
**I want** each item's recordChangeTag to be re-verified against iCloud at approval time
**So that** deletions never execute against stale state, no matter how the batch grew to its current size

**Acceptance criteria:**
- AC-1: On approval, every item's recordChangeTag is re-verified against iCloud immediately before deletion executes, regardless of how many merge/re-notify cycles the batch went through. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0067`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:319`

**Status:** pending