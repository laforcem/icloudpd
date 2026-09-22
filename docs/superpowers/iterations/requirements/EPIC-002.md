# EPIC-002 — Asset manifest

**Summary:** Asset manifest
**Stories:** STORY-0003
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/1 done

## STORY-0003

**Epic:** EPIC-002 — Asset manifest
**Title:** Promote asset manifest to source of truth for dedup identity

**As a** operator running icloudpd unattended
**I want** download identity to be resolved by iCloud record name lookup in a persisted manifest rather than by guessing local file paths
**So that** changing the local folder structure does not trigger a full re-download of the library

**Acceptance criteria:**
- AC-1: Given an asset already recorded in the manifest by iCloud record name, changing `folder_structure` config and re-running does not re-download that asset. · impact:`cross-surface` · seam:`integration` · scenario:`SCENARIO-0001`
- AC-2: Dedup decisions no longer call `os.path.isfile()`-style path guessing; identity lookup goes through the store by record name/key. · impact:`local` · seam:`integration` · scenario:`SCENARIO-0001`
- AC-3: `file_match_policy` config option is removed/rejected since manifest-based identity supersedes filename-collision dedup. · impact:`local` · seam:`unit` · scenario:`SCENARIO-0001`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:10-13,33-38,73-75`

**Status:** pending