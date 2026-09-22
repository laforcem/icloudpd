# EPIC-013 — Secrets

**Summary:** Secrets
**Stories:** STORY-0021
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0021

**Epic:** EPIC-013 — Secrets
**Title:** Deliver secrets via watched files with live rotation, no vendor SDK

**As a** operator using external secret rotation (Bitwarden, Docker secrets, K8s volumes, Vault Agent)
**I want** each secret delivered as a single file, watched with fsnotify, picked up live without a restart
**So that** rotating a credential doesn't require restarting the service, and no vendor-specific SDK is required

**Acceptance criteria:**
- AC-1: internal/secret/watchfile detects a changed secret file's content via fsnotify and the new value is used on the next access without a process restart. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0014`
- AC-2: The secret source model supports exactly one value per file; no multi-secret file parsing format is implemented. · impact:`none` · seam:`unit`
- AC-3: No vendor secret-manager SDK is a dependency; secret retrieval is generic file-based. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:43`

**Status:** pending