# EPIC-014 — Credentials

**Summary:** Credentials
**Stories:** STORY-0022
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0022

**Epic:** EPIC-014 — Credentials
**Title:** Resolve apple_id and password through a watched-file/env/memory-cache source chain

**As a** operator
**I want** apple_id and password each resolved via watched file, then env var, then an in-memory last-known-good cache
**So that** credentials keep working through transient issues without ever persisting a working credential to disk beyond the operator-provided file

**Acceptance criteria:**
- AC-1: Given a watched credential file is present and readable, its value is used in preference to an env var or the memory cache. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0015`
- AC-2: Given no watched file value is available, an env var is used if set. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0015`
- AC-3: Given neither file nor env var is available, the last known-good in-memory value is used; this cache is RAM-only and is never serialized to disk. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0015`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:44-45`

**Status:** pending