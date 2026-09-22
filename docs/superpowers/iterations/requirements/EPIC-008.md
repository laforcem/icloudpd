# EPIC-008 — Web UI

**Summary:** Web UI
**Stories:** STORY-0011, STORY-0012, STORY-0013, STORY-0014
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/4 done

## STORY-0011

**Epic:** EPIC-008 — Web UI
**Title:** Provide read-only dashboard, off by default, with no mutating endpoints

**As a** operator
**I want** an optional read-only status dashboard that is disabled unless explicitly enabled, exposing no mutation, credential entry, or thumbnail proxying
**So that** the unauthenticated-mutation and password-leak vulnerabilities of the current web UI cannot exist by construction

**Acceptance criteria:**
- AC-1: The dashboard is disabled by default; it must be explicitly enabled via config to bind any listener. · impact:`local` · seam:`integration`
- AC-2: internal/web/dashboard exposes no POST/mutating routes, no credential-entry form, and no thumbnail-proxy route. · impact:`local` · seam:`integration`
- AC-3: internal/web/dashboard imports internal/status only; no secret-capable type is reachable from the dashboard's import graph. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:9,39,105-119`

**Status:** pending

## STORY-0012

**Epic:** EPIC-008 — Web UI
**Title:** Keep the web dashboard read-only with no mutating endpoints

**As a** security-conscious operator
**I want** all mutating actions and credential escalation routed only through Telegram/CLI, never through the web
**So that** the dashboard cannot expose an unauthenticated mutation path like the old POST /force-reauth

**Acceptance criteria:**
- AC-1: Mutating actions (Approve/RejectBatch, ForceReauth, Cancel, Resume, manual sync trigger) are available only via Telegram slash commands and the CLI; the web UI exposes none of them. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0060`
- AC-2: There is no mutating web endpoint at all in internal/web/dashboard. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0060`
- AC-3: Credential escalation (2FA code entry, wrong-password notification) happens only via Telegram inline replies/notifications, never via any web form. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0060`
- AC-4: Deletion-sync review thumbnails are delivered as Telegram-native photo messages; there is no web thumbnail proxy. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0060`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:278-284`

**Status:** pending

## STORY-0013

**Epic:** EPIC-008 — Web UI
**Title:** Restrict the dashboard's import graph to non-secret-capable packages

**As a** codebase maintainer
**I want** internal/web/dashboard's transitive dependencies structurally excluded from secret- or credential-capable packages
**So that** a mistake in the status projection can never leak a secret through the dashboard

**Acceptance criteria:**
- AC-1: internal/web/dashboard imports only internal/status; internal/status itself imports only stdlib plus internal/asset. · impact:`none` · seam:`unit`
- AC-2: The config + runtime → status.Snapshot projection is built explicitly, field by field, in internal/app (a whitelist by construction). · impact:`none` · seam:`unit`
- AC-3: TestDashboardImportGraph runs `go list -deps ./internal/web/dashboard` and asserts the transitive dependency set excludes internal/secret, internal/config, internal/icloud/auth, internal/control, and internal/store/sqlite. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0061`
- AC-4: secret.Value has no exported field and overrides String/GoString/MarshalJSON/MarshalText to render [redacted], so even a projection mistake cannot print a secret. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0061`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:285-286`

**Status:** pending

## STORY-0014

**Epic:** EPIC-008 — Web UI
**Title:** Bind the optional dashboard to loopback by default

**As a** operator
**I want** the dashboard to default to binding 127.0.0.1
**So that** account names, sync/error history, and pending-batch state don't leak to the LAN unless I explicitly opt in

**Acceptance criteria:**
- AC-1: When dashboard.enabled is true and dashboard.bind is unset, the listener binds to 127.0.0.1, not 0.0.0.0. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0062`
- AC-2: LAN/remote access to the dashboard requires the operator to explicitly set dashboard.bind; it is opt-in, not opt-out. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0062`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:287-288`

**Status:** pending