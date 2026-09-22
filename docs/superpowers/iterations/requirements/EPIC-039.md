# EPIC-039 — Architecture Discipline

**Summary:** Architecture Discipline
**Stories:** STORY-0132
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0132

**Epic:** EPIC-039 — Architecture Discipline
**Title:** Keep internal/config out of the sync engine's API surface

**As a** maintainer
**I want** the engine, naming, and mirror packages to accept narrow purpose-built option structs instead of the whole per-account config
**So that** internal/config does not become an all-importing god package the way base.py did

**Acceptance criteria:**
- AC-1: `internal/app` builds narrow structs (e.g. `syncengine.Options`, `naming.Policy`, `mirror.Policy`) and passes those into the engine, rather than passing the whole per-account config struct. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:407-409`

**Status:** pending
