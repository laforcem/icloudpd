# EPIC-017 — Delivery

**Summary:** Delivery
**Stories:** STORY-0030, STORY-0031
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/2 done

## STORY-0030

**Epic:** EPIC-017 — Delivery
**Title:** Ship a single binary with defined subcommands and container default

**As a** operator deploying icloudpd in a container
**I want** one binary whose container default subcommand is `serve`, plus `validate`, `print-config`, `run-once`, `check-protocol`, and CLI-only diagnostics `auth-only`/`list-albums`/`list-libraries`
**So that** operational and diagnostic tasks are clearly separated and the container runs unattended by default

**Acceptance criteria:**
- AC-1: Running the container image with no explicit subcommand runs `serve`. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0021`
- AC-2: `validate`, `print-config`, `run-once`, and `check-protocol` are available as subcommands. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0021`
- AC-3: `auth-only`, `list-albums`, and `list-libraries` are CLI-only diagnostic actions that do not read or write persisted config. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0021`
- AC-4: No `migrate` subcommand exists; there is no built-in path to convert the old Python YAML config. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:58-60`

**Status:** pending

## STORY-0031

**Epic:** EPIC-017 — Delivery
**Title:** Rebuild state from a clean break (no legacy session/manifest porting)

**As a** operator upgrading from the Python version
**I want** the Go rewrite to perform fresh auth and rebuild its manifest by scanning existing files on disk, storing session data under state_dir
**So that** no fragile cross-version state format (Apple's cookie format, old manifest format) needs to be ported

**Acceptance criteria:**
- AC-1: On first run against an existing library directory with no manifest, the service scans disk and rebuilds a manifest without requiring or reading any pre-existing Python-version manifest or cookie file. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0022`
- AC-2: Session data is written under the configured state_dir; there is no separate configurable session path. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0022`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:60-61`

**Status:** pending