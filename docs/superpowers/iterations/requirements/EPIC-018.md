# EPIC-018 — Architecture

**Summary:** Architecture
**Stories:** STORY-0032
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0032

**Epic:** EPIC-018 — Architecture
**Title:** Enforce architectural boundaries via package layout and build constraints

**As a** maintainer
**I want** domain packages with no outward dependencies, only internal/app wiring concrete types, and a CGO-free static build
**So that** the layering the design specifies is actually enforced rather than eroding over time

**Acceptance criteria:**
- AC-1: The binary is built with CGO_ENABLED=0 and runs in a distroless image at roughly 20MB. · impact:`none` · seam:`process-level`
- AC-2: internal/asset, internal/naming, and internal/xmp (domain packages) import no other internal packages that depend on I/O, network, or storage. · impact:`none` · seam:`unit`
- AC-3: Only internal/app constructs and wires concrete implementations (store, notifiers, protocol client, etc.); other packages depend on interfaces they define or receive. · impact:`none` · seam:`unit`
- AC-4: internal/web/dashboard's import graph reaches internal/status only among internal packages, with no path to a secret-capable type. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:20-21,67-119`

**Status:** pending
