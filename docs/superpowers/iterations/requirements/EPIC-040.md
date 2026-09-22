# EPIC-040 — Naming

**Summary:** Naming
**Stories:** STORY-0133, STORY-0134
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/2 done

## STORY-0133

**Epic:** EPIC-040 — Naming
**Title:** Apply naming policy's default date format and flat-layout override

**As a** operator
**I want** folder_structure to default to a Y/m/d date-based layout, with the literal value none producing a flat layout
**So that** the Go naming package preserves the Python scheme's exact behavior and config shape

**Acceptance criteria:**
- AC-1: When folder_structure is unset, internal/naming applies the default format string {:%Y/%m/%d} (using Go's time-formatting verbs) to each asset's creation date. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0108`
- AC-2: When folder_structure is set to the literal value none, files are placed in a flat layout with no date-based subfolders. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0108`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:76`

**Status:** pending

## STORY-0134

**Epic:** EPIC-040 — Naming
**Title:** Honor file_layout knobs for Live Photo naming, RAW alignment, unicode filenames, and EXIF datetime

**As a** operator
**I want** the file_layout keys live_photo_mov_filename_policy, align_raw, keep_unicode_in_filenames, and set_exif_datetime to control their respective per-file behaviors
**So that** the Go naming/download pipeline matches the configured layout preferences exactly

**Acceptance criteria:**
- AC-1: With live_photo_mov_filename_policy: suffix, a Live Photo's companion video filename is derived by appending a suffix to the photo's base filename. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0112`
- AC-2: With align_raw: as-is, a RAW file is named using its own filename rather than being renamed to align with its JPEG counterpart. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0112`
- AC-3: With keep_unicode_in_filenames: false, non-ASCII characters in generated filenames are transliterated or stripped rather than preserved. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0112`
- AC-4: With set_exif_datetime: false, downloaded files' local mtime/EXIF datetime is left untouched rather than being set from asset metadata. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0112`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:202-206`

**Status:** pending