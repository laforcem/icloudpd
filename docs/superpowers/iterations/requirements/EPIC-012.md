# EPIC-012 — Download integrity

**Summary:** Download integrity
**Stories:** STORY-0019, STORY-0020
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/2 done

## STORY-0019

**Epic:** EPIC-012 — Download integrity
**Title:** Verify downloaded bytes against Apple's fileChecksum

**As a** operator relying on downloaded assets being correct
**I want** each downloaded asset's bytes checked against Apple's provided fileChecksum, not just its size
**So that** corrupted or truncated downloads are detected rather than silently accepted

**Acceptance criteria:**
- AC-1: internal/download computes a checksum over the fully downloaded (or resumed) file and compares it to the fileChecksum from asset-version metadata; a mismatch is treated as a download failure, not accepted. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0012`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:94`

**Status:** pending

## STORY-0020

**Epic:** EPIC-012 — Download integrity
**Title:** Fall back to original size when a requested size is unavailable

**As a** operator
**I want** a download to fall back to the original asset size when the configured size isn't available
**So that** the asset is still downloaded rather than silently skipped

**Acceptance criteria:**
- AC-1: When a requested version size in sync_scope.sizes is unavailable for an asset, the sync falls back to downloading original rather than skipping the asset. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0107`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:216`

**Status:** pending