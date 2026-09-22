# EPIC-032 — Sync Idempotency & Manifest Integrity

**Summary:** Sync Idempotency & Manifest Integrity
**Stories:** STORY-0116
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0116

**Epic:** EPIC-032 — Sync Idempotency & Manifest Integrity
**Title:** Make the manifest the sole source of truth for what has been downloaded

**As a** operator
**I want** reruns to skip everything already recorded in the manifest, including after a naming-setting change
**So that** reruns are cheap and reorganizing output layout never re-triggers iCloud downloads

**Acceptance criteria:**
- AC-1: `icloudpd run-once` against a real account downloads assets, writes manifest rows, and generates XMP sidecars. · impact:`journey` · seam:`e2e` · scenario:`JOURNEY-0002`
- AC-2: A second `run-once` against the same account downloads nothing. · impact:`journey` · seam:`e2e` · scenario:`JOURNEY-0002`
- AC-3: Renaming the folder-structure setting and re-running does not cause already-downloaded files to be re-downloaded. · impact:`journey` · seam:`e2e` · scenario:`JOURNEY-0002`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:382-383`

**Status:** pending