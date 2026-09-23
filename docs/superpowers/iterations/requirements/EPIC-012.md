# EPIC-012 — Download integrity

**Summary:** Download integrity
**Stories:** STORY-0019, STORY-0020, STORY-0136
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 2/3 done

## STORY-0019

**Epic:** EPIC-012 — Download integrity
**Title:** Verify downloaded bytes against Apple's fileChecksum

**As a** operator relying on downloaded assets being correct
**I want** each downloaded asset's bytes checked against Apple's provided fileChecksum, not just its size
**So that** corrupted or truncated downloads are detected rather than silently accepted

**Acceptance criteria:**
- AC-1 (narrowed during ITER-0000's live proof-run — see below): internal/download compares the fully downloaded file's byte count against the size reported in asset-version metadata; a mismatch is treated as a download failure, not accepted. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0013`

**Citation fix (ITER-0000 PAR scope review):** AC-1 previously cited SCENARIO-0012, which covers SIGTERM-triggered ranged-resume — out of scope for this iteration per STORY-0136's split note. SCENARIO-0013 ("Checksum mismatch is treated as a failed download") is the scenario that actually matches this AC.

**Scope narrowing (confirmed live during ITER-0000's JOURNEY-0001 proof-run, 2026-09-23):** AC-1 originally required comparing a computed content checksum against Apple's fileChecksum. Live testing showed this is infeasible with a standard hash function: decoding a real fileChecksum and comparing against SHA-1/SHA-256 of the actual downloaded bytes failed, and structural analysis showed the CPLMaster recordName is literally `0x01 || fileChecksum` — the field is Apple's MMCS content-addressable identifier (chunked, aggregated), not a plain digest. Independently confirmed: `steilerDev/icloud-photos-sync` (a mature, actively-maintained TypeScript iCloud Photos client) has an unused, commented-out `verifyChecksum` method whose own comment reads *"This is currently NOT implemented, as the checksum algorithm is unknown"* — its dead code shows it brute-forced every standard hash (MD5, SHA1, SHA224/256/384/512, SHA3 family, BLAKE2, SM3) across multiple encodings, plus HMAC-keyed variants, with no match. Reproducing MMCS's exact algorithm is out of scope for this iteration (and arguably for the project generally, absent a documented spec). AC-1 is narrowed to the size check `internal/download` can actually perform correctly; the raw fileChecksum value is still recorded in the manifest for possible future use. This is a real, evidence-based scope decision, not silent descoping — revisit if MMCS's algorithm is ever documented.

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:94`

**Status:** done:ITER-0000

## STORY-0020

**Epic:** EPIC-012 — Download integrity
**Title:** Fall back to original size when a requested size is unavailable

**As a** operator
**I want** a download to fall back to the original asset size when the configured size isn't available
**So that** the asset is still downloaded rather than silently skipped

**Acceptance criteria:**
- AC-1: When a requested version size in sync_scope.sizes is unavailable for an asset, the sync falls back to downloading original rather than skipping the asset. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0107`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:216`

**Status:** pending

## STORY-0136

**Epic:** EPIC-012 — Download integrity
**Title:** Fetch an asset's bytes to a temp file and atomically rename into place

**As a** engine developer
**I want** internal/download to fetch an asset's version bytes over HTTP and write them to their final path via a temp-file-then-rename sequence
**So that** the destination file only ever exists as a complete, correctly-named file — never a partial one

**Acceptance criteria:**
- AC-1: internal/download fetches the requested asset version's bytes from the URL provided by the CloudKit response and writes them to a temp file in the destination directory, then renames the temp file to its final path only after the write completes successfully. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0116`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:89-90`

**Split note:** added during ITER-0000 scope review — the design doc's package layout describes `internal/download` as owning "ranged resume, atomic temp+rename," but no extracted story governed the basic fetch-and-write mechanism itself (only its post-download checksum verification, STORY-0019). This story covers the non-resumable happy-path mechanism the walking skeleton needs; ranged resume is covered separately under graceful shutdown (EPIC-011).

**Status:** done:ITER-0000