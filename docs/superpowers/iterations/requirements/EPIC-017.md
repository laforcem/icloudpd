# EPIC-017 — Delivery

**Summary:** Delivery
**Stories:** STORY-0030, STORY-0031, STORY-0138, STORY-0139
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 2/4 done

## STORY-0030

**Epic:** EPIC-017 — Delivery
**Title:** Ship a single binary defaulting to serve, with run-once and check-protocol available

**As a** operator deploying icloudpd in a container
**I want** one binary whose container default subcommand is `serve`, with `run-once` and `check-protocol` also available, and no `migrate` subcommand
**So that** the container runs unattended by default while still supporting a one-shot run and a manual protocol check

**Acceptance criteria:**
- AC-1: Running the container image with no explicit subcommand runs `serve`. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0021`
- AC-2: No `migrate` subcommand exists; there is no built-in path to convert the old Python YAML config. · impact:`none` · seam:`unit`

**Citation fix (ITER-0000 PAR scope review):** SCENARIO-0021 previously bundled STORY-0138's print-config/redaction observable with STORY-0030's serve-default/run-once observables, overclaiming coverage this iteration can't close (STORY-0138 is deferred to ITER-0002). SCENARIO-0021 is narrowed to only the serve-default and run-once-independent-lifecycle observables STORY-0030 delivers; the print-config observable is split into new scenario:`SCENARIO-0120`, owned by STORY-0138.

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:58-60`

**Status:** done:ITER-0000

## STORY-0031

**Epic:** EPIC-017 — Delivery
**Title:** Store session data under state_dir with no legacy porting

**As a** operator upgrading from the Python version
**I want** the Go rewrite to perform fresh auth and store session data under state_dir, with no separate configurable session path and no reading of Apple's old cookie format
**So that** no fragile cross-version session format needs to be ported

**Acceptance criteria:**
- AC-1: Session data is written under the configured state_dir; there is no separate configurable session path, and no pre-existing Python-version cookie file is read. · impact:`none` · seam:`integration`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:60-61`

**Status:** done:ITER-0000

## STORY-0138

**Epic:** EPIC-017 — Delivery
**Title:** Provide validate, print-config, and CLI-only diagnostic subcommands

**As a** operator deploying icloudpd
**I want** `validate` and `print-config` subcommands, plus CLI-only diagnostics `auth-only`/`list-albums`/`list-libraries`
**So that** I can check configuration correctness and run one-shot diagnostics without persisting config

**Acceptance criteria:**
- AC-1: `validate` and `print-config` are available as subcommands. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0021`
- AC-2: `auth-only`, `list-albums`, and `list-libraries` are CLI-only diagnostic actions that do not read or write persisted config. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0021`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:58-60`

**Split note:** split from STORY-0030 during ITER-0000 scope review — `validate`/`print-config` need config-schema validation logic not built until the config-schema iteration; `list-albums`/`list-libraries`/`auth-only` need the multi-zone discovery deferred alongside STORY-0137. Deferred to the config-schema iteration.

**Status:** pending

## STORY-0139

**Epic:** EPIC-017 — Delivery
**Title:** Rebuild the manifest by scanning existing files on disk

**As a** operator upgrading from the Python version or recovering state
**I want** the service to rebuild its manifest by scanning existing files on disk when no manifest exists
**So that** an existing library directory doesn't require re-downloading everything to populate the manifest

**Acceptance criteria:**
- AC-1: On first run against an existing library directory with no manifest, the service scans disk and rebuilds a manifest without requiring or reading any pre-existing Python-version manifest or cookie file. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0022`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:60-61`

**Split note:** split from STORY-0031 during ITER-0000 scope review — disk-rescan rebuild needs `internal/scan`, which isn't part of the walking skeleton, and the skeleton's journey (a fresh account with one asset) never exercises reconciling an existing library. Deferred to the core-sync iteration that introduces `internal/scan`.

**Status:** pending