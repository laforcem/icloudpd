# EPIC-031 — Configuration Management

**Summary:** Configuration Management
**Stories:** STORY-0115
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0115

**Epic:** EPIC-031 — Configuration Management
**Title:** Validate and introspect resolved configuration

**As a** operator
**I want** commands to validate config and show where each resolved value came from
**So that** I can catch misconfiguration before running and understand precedence between config sources

**Acceptance criteria:**
- AC-1: `icloudpd validate` rejects a malformed config with a clear error. · impact:`local` · seam:`e2e` · scenario:`SCENARIO-0087`
- AC-2: `icloudpd print-config` shows per-field provenance for the resolved configuration. · impact:`local` · seam:`e2e` · scenario:`SCENARIO-0087`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:381`

**Status:** pending