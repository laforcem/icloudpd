# EPIC-041 — Process model

**Summary:** Process model
**Stories:** STORY-0135
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 1/1 done

## STORY-0135

**Epic:** EPIC-041 — Process model
**Title:** Scope the walking skeleton as the first iteration

**As a** maintainer
**I want** the roadmap's first iteration (ITER-0000) to be scoped exactly as authenticate → list one asset → download it → record it in the manifest → exit clean
**So that** the highest-risk component (SRP) is validated by working software in the first iteration rather than by a separate throwaway spike

**Acceptance criteria:**
- AC-1: The roadmap's first iteration is scoped as the walking-skeleton journey (auth → list one asset → download → record → exit clean), not a narrower or broader scope. · impact:`journey` · seam:`e2e` · scenario:`JOURNEY-0001`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:369`

**Status:** done:ITER-0000