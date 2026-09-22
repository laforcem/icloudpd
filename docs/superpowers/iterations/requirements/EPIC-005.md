# EPIC-005 — Deletion mirroring review surface

**Summary:** Deletion mirroring review surface
**Stories:** STORY-0007
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0007

**Epic:** EPIC-005 — Deletion mirroring review surface
**Title:** Review and approve pending deletion batches via Telegram photo messages

**As a** operator on the allowed Telegram chat list
**I want** to review a pending deletion-mirror batch as live thumbnail photo messages, paginated, and approve or reject it
**So that** irreversible iCloud-side deletions never happen without a human review step, without needing a web thumbnail proxy

**Acceptance criteria:**
- AC-1: Pending batch thumbnails are fetched live at THUMB size (~46KB) on demand and sent as Telegram photo messages; they are never written to local disk. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0003`
- AC-2: Review pagination lets an operator page through all assets in a pending batch before deciding. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0003`
- AC-3: `/approve` and `/reject` commands from an allowed chat resolve the pending batch's approval state and are the only path that can trigger submission to Apple. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0003`
- AC-4: internal/web/thumbproxy does not exist in the package layout; no web endpoint serves deletion-review thumbnails. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:62,97-98,116`

**Status:** pending