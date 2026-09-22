# EPIC-016 — Access control

**Summary:** Access control
**Stories:** STORY-0028, STORY-0029
**Primary sources:** `docs/superpowers/specs/2026-08-14-go-rewrite-design.md`
**Status:** 0/2 done

## STORY-0028

**Epic:** EPIC-016 — Access control
**Title:** Keep allowed_chat_ids global across all accounts

**As a** operator running a handful of accounts for one household
**I want** a single global allowed_chat_ids list that authorizes any allowed chat to act on any account's control commands
**So that** config stays simple in a deployment shape where everyone on the list is already trusted with every account

**Acceptance criteria:**
- AC-1: A chat ID present in the global allowed_chat_ids list can successfully issue /approve, /reject, /cancel, /resume, and /force_reauth against any configured account, not just one. · impact:`cross-surface` · seam:`app-level` · scenario:`SCENARIO-0020`
- AC-2: The config schema has no per-account allowed_chat_ids field; scoping is global only. · impact:`none` · seam:`unit`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:52`

**Status:** pending

## STORY-0029

**Epic:** EPIC-016 — Access control
**Title:** Refuse startup with Telegram configured but no allowed chats

**As a** operator
**I want** `icloudpd validate` to refuse a config where telegram.bot_token_file is set but allowed_chat_ids is empty
**So that** the mutation surface (approve/force_reauth/cancel/resume) can never end up either silently denying everyone or silently open to everyone

**Acceptance criteria:**
- AC-1: `icloudpd validate` fails when telegram.bot_token_file is set and allowed_chat_ids is an empty list. · impact:`local` · seam:`process-level` · scenario:`SCENARIO-0019`

**Sources:**
- `docs/superpowers/specs/2026-08-14-go-rewrite-design.md:56`

**Status:** pending