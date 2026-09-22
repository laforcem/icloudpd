# EPIC-030 — Build & Release Verification

**Summary:** Build & Release Verification
**Stories:** STORY-0112, STORY-0113, STORY-0114
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/3 done

## STORY-0112

**Epic:** EPIC-030 — Build & Release Verification
**Title:** Produce a statically linked, minimal-footprint binary

**As a** release engineer
**I want** the Go binary to build statically and ship in a minimal container image
**So that** deployment footprint is small and portable without requiring glibc or a full base image

**Acceptance criteria:**
- AC-1: `CGO_ENABLED=0 go build ./...` produces a static binary. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0084`
- AC-2: Container image builds `FROM scratch`/distroless and the build reports the resulting image size. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0084`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:378`

**Status:** pending

## STORY-0113

**Epic:** EPIC-030 — Build & Release Verification
**Title:** Enforce dashboard import isolation and fixture health via automated tests

**As a** maintainer
**I want** go test ./... to include import-graph checks and fixture guards
**So that** the dashboard's read-only security posture and fixture correctness are continuously enforced, not just asserted in docs

**Acceptance criteria:**
- AC-1: `go test ./...` passes, including import-graph tests that fail if the dashboard package imports `secret`, `config`, `auth`, `control`, or `sqlite`. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0085`
- AC-2: `go test ./...` passes fixture freshness and reachability guard tests. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0085`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:379`

**Status:** pending

## STORY-0114

**Epic:** EPIC-030 — Build & Release Verification
**Title:** Provide a manual protocol-inspection command

**As a** developer
**I want** an `icloudpd check-protocol` command runnable by hand against a real account
**So that** I can confirm the iCloud protocol response shape without a CI job or a dedicated test account

**Acceptance criteria:**
- AC-1: `icloudpd check-protocol`, run by hand against a real account, asserts response structure. · impact:`local` · seam:`e2e` · scenario:`SCENARIO-0086`
- AC-2: This check has no CI job and requires no dedicated test account. · impact:`none` · seam:`process-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:380`

**Status:** pending