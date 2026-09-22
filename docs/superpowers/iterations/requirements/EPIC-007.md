# EPIC-007 — XMP sidecars

**Summary:** XMP sidecars
**Stories:** STORY-0010
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0010

**Epic:** EPIC-007 — XMP sidecars
**Title:** Enforce typed-error decoding for XMP orientation data

**As a** operator relying on XMP sidecars for HEIC orientation metadata
**I want** a decode failure on adjustmentSimpleDataEnc to surface as a typed error instead of being silently swallowed as a warning
**So that** issue #32's silent Orientation drop cannot recur unnoticed

**Acceptance criteria:**
- AC-1: When adjustmentSimpleDataEnc fails to decode for a given fixture, internal/xmp returns a typed error value distinguishable from success, rather than logging a warning and continuing with default orientation. · impact:`local` · seam:`unit`
- AC-2: A fixture-driven test case reproducing issue #32's failing HEIC asset is part of the xmp package's test suite. · impact:`local` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:38`

**Status:** pending
