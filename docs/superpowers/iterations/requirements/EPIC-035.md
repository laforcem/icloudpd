# EPIC-035 — Dashboard Security

**Summary:** Dashboard Security
**Stories:** STORY-0119
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0119

**Epic:** EPIC-035 — Dashboard Security
**Title:** Keep the dashboard read-only and route auth escalation through Telegram only

**As a** security-conscious operator
**I want** the dashboard to expose no credential form or mutating endpoint, with 2FA/password escalation only reachable via Telegram
**So that** scanning or hitting the dashboard port can never be used to submit credentials or trigger a mutation

**Acceptance criteria:**
- AC-1: Scanning the dashboard port shows status rendering, with no credential form and no mutating endpoint present anywhere in the binary. · impact:`cross-surface` · seam:`e2e` · scenario:`SCENARIO-0091`
- AC-2: A wrong password during auth produces a Telegram notify-only message with no reply path. · impact:`cross-surface` · seam:`e2e` · scenario:`SCENARIO-0091`
- AC-3: A 2FA prompt produces a Telegram message whose inline reply is accepted exactly once. · impact:`cross-surface` · seam:`e2e` · scenario:`SCENARIO-0091`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:386`

**Status:** pending