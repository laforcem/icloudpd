# EPIC-028 — Libraries and build constraints

**Summary:** Libraries and build constraints
**Stories:** STORY-0096, STORY-0097, STORY-0098, STORY-0099, STORY-0100, STORY-0101, STORY-0102, STORY-0103
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/8 done

## STORY-0096

**Epic:** EPIC-028 — Libraries and build constraints
**Title:** Static CGO-free build with pure-Go SQLite driver

**As a** maintainer
**I want** the SQLite driver to be modernc.org/sqlite, never mattn/go-sqlite3
**So that** CGO_ENABLED=0 go build succeeds and the binary can ship as a distroless image

**Acceptance criteria:**
- AC-1: CGO_ENABLED=0 go build succeeds for the project. · impact:`none` · seam:`process-level`
- AC-2: mattn/go-sqlite3 is not present as a dependency anywhere in the module graph. · impact:`none` · seam:`process-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:321-324`

**Status:** pending

## STORY-0097

**Epic:** EPIC-028 — Libraries and build constraints
**Title:** Own the cron timer loop, use gronx only as parser

**As a** maintainer
**I want** adhocore/gronx used only for cron-expression parsing (Next(t)), with the application driving its own timer loop
**So that** the scheduler loop ownership problem the rewrite is fixing isn't reintroduced by adopting robfig's runner

**Acceptance criteria:**
- AC-1: robfig's cron runner (or any library that owns the scheduling loop) is not present as a dependency; scheduling is driven by an application-owned timer using gronx's Next(t) for expression parsing only. · impact:`none` · seam:`process-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:321-325`

**Status:** pending

## STORY-0098

**Epic:** EPIC-028 — Libraries and build constraints
**Title:** Config reload watches parent directory, not the file

**As a** operator running icloudpd under Kubernetes/Docker
**I want** fsnotify to watch the config file's parent directory rather than the file itself, debounced ~200ms
**So that** an atomic symlink-swap config rotation (ConfigMap/secret update) is still detected instead of the watch going deaf

**Acceptance criteria:**
- AC-1: The config watcher registers fsnotify on the parent directory of the config file, not the file path itself. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0075`
- AC-2: On a detected change, the watcher debounces ~200ms before re-reading and validating the config, and correctly picks up an atomic symlink-swap style rotation. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0075`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:321-327`

**Status:** pending

## STORY-0099

**Epic:** EPIC-028 — Libraries and build constraints
**Title:** Telegram integration built on go-telegram/bot

**As a** maintainer
**I want** the Telegram bot layer built on go-telegram/bot instead of the unmaintained go-telegram-bot-api v5
**So that** the bot has zero extraneous deps and a maintained, context-first API

**Acceptance criteria:**
- AC-1: The Telegram bot integration depends on go-telegram/bot; go-telegram-bot-api is not a dependency. · impact:`none` · seam:`process-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:321-329`

**Status:** pending

## STORY-0100

**Epic:** EPIC-028 — Libraries and build constraints
**Title:** Hand-rolled SRP matching Apple's protocol variant

**As a** maintainer implementing iCloud authentication
**I want** SRP hand-rolled with math/big, crypto/sha256, and x/crypto/pbkdf2
**So that** authentication works against Apple's non-standard SRP variant, which no off-the-shelf library matches

**Acceptance criteria:**
- AC-1: SRP authentication is implemented in-house (no third-party SRP library dependency) using math/big, crypto/sha256, and x/crypto/pbkdf2, and successfully completes login against Apple's SRP variant. · impact:`journey` · seam:`integration` · scenario:`SCENARIO-0076`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:321-331`

**Status:** pending

## STORY-0101

**Epic:** EPIC-028 — Libraries and build constraints
**Title:** Strict YAML config parsing rejects unknown fields

**As a** operator writing a config file
**I want** YAML config parsing to use KnownFields(true) instead of a framework like viper
**So that** typos or unsupported config keys are caught rather than silently ignored

**Acceptance criteria:**
- AC-1: Loading a YAML config file containing an unrecognized field fails with an error rather than silently ignoring the field. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0077`
- AC-2: viper and cobra are not present as dependencies; CLI flags use stdlib flag, HTTP uses net/http, logging uses log/slog, templates use html/template. · impact:`none` · seam:`process-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:321-333`

**Status:** pending

## STORY-0102

**Epic:** EPIC-028 — Libraries and build constraints
**Title:** Use x/time, x/sync, go-cmp; skip testify

**As a** maintainer
**I want** rate limiting, concurrency, and diffing built on x/time/rate, x/sync (errgroup, singleflight), and go-cmp, without testify
**So that** the dependency set stays minimal and earned

**Acceptance criteria:**
- AC-1: testify is not present as a test dependency anywhere in the module graph; rate/concurrency/diffing code depends on x/time/rate, x/sync, and go-cmp. · impact:`none` · seam:`process-level`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:321-334`

**Status:** pending

## STORY-0103

**Epic:** EPIC-028 — Libraries and build constraints
**Title:** print-config shows per-field configuration provenance

**As a** operator debugging a configuration value
**I want** print-config to show, for each field, whether it came from the YAML file, an environment variable, or a default
**So that** I can tell why a setting has the value it does across the YAML → env → defaults layering

**Acceptance criteria:**
- AC-1: For every config field, print-config reports which layer (YAML file, environment variable, or built-in default) supplied its effective value. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0078`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:321-335`

**Status:** pending