# syncToken delta spike — findings

**Date:** 2026-08-14
**Spike code:** `spike/synctoken_spike.py` (throwaway, do not merge)
**Raw evidence:** `spike/.state/artifacts/` (gitignored — contains unredacted tokens and photo metadata)
**Gate:** this result is an explicit human decision point. No architecture has been changed.

---

## Question

Does resending Apple's `syncToken` yield a true delta — only changed records, including removals?

## Verdict

**No. `syncToken` is a zone-version token, not a change log.** This is the spec's second branch ("cache-validity token"): the `Enumerator` seam survives but `delta` can never set `ReportsRemovals`.

One finding was not anticipated by the spec and is the useful part of the result: **the token advances when the zone changes, and is stable when it does not.** That makes it a viable cheap change detector — plausibly a better one than the count probe, though see the open question below before relying on that.

---

## Method

Account: a purpose-made test account, 20 assets. Python client (`PyiCloudService`) against the live API — this is a protocol question, so writing Go SRP first would have been backwards.

Two phases, with one photo deleted via iCloud.com between them:

1. `probe` — baseline listing, three resend variants, `continuationMarker` check, count probe, full-sweep control.
2. `delta` — the same resends using the stored token, plus the full-sweep control, token comparison, count probe, and a `recently_deleted` query.

Tokens are compared by truncated SHA-256, not by prefix: a 44-char base64 value that advances in the middle looks identical under head/tail redaction.

---

## Evidence

### Resending the token changes nothing

All requests below returned HTTP 200 with top-level keys `['records', 'syncToken']`.

| Request | Records | Identical to baseline | Returned token |
|---|---|---|---|
| baseline (no token) | 2 | — | `f8f0f6ab2b5e` |
| `syncToken` only | 2 | yes | `f8f0f6ab2b5e` |
| `syncToken` + `clientInstanceId` | 2 | yes | `f8f0f6ab2b5e` |
| `clientInstanceId` only | 2 | yes | `f8f0f6ab2b5e` |
| full sweep (no token) | 40 | — | `f8f0f6ab2b5e` |

**The decisive observation:** a token captured seconds earlier, resent with nothing changed in between, returned two *pre-existing* records. A change log must return zero changes there. It returned the same rows as the unfiltered query.

The `clientId` → `clientInstanceId` swap from the dead code at `photos.py:415-419` is also inert, both with and without the token. Five consecutive requests returned a byte-identical token.

### The token advances on mutation

After deleting one photo:

| | Before | After |
|---|---|---|
| Token | `f8f0f6ab2b5e` | `380d6e006589` |
| Full sweep | 40 records (20 assets) | 38 records (19 assets) |
| `itemCount` | 20 | 19 |

Stable across five requests while nothing changed, then changed exactly once when something did. That is the signature of a zone-version counter. The post-mutation resends still returned the same rows as the no-token control, confirming the token filters nothing even once it has advanced.

### Removals are observable — but not through the delta

The two records missing from the full sweep are exactly the two records returned by `recently_deleted` (overlap 2 of 2). They carry explicit `isDeleted` and `dateExpunged` fields.

So removals are identifiable, via the separate `CPLAssetAndMasterDeletedByExpungedDate` list type rather than via any delta mechanism.

### `continuationMarker` is not offered

With 20 assets and `resultsLimit=2` there are certainly further pages, and Apple returned no `continuationMarker` at all. The marker in `tests/vcr_cassettes/listing_photos.yml:11206` must come from a different query type. **`startRank` offset arithmetic stays**, along with its fragility against a mutating server index.

### Timings (20-asset library)

- Listing page: 342–380 ms
- Count probe: 285, 278, 292 ms
- Count probe correctly detected 20 → 19

---

## What this means for the design

1. **Drop `ReportsRemovals` from `Capabilities`** rather than keeping a dead flag, as the spec directed for this branch.
2. **A delta enumerator built on `syncToken` is not worth building.** It cannot filter anything.
3. **Near-real-time is still reachable, via change *detection* rather than change *transfer*.** Poll a cheap signal every 60s; run a full sweep only when it moves. Two candidate signals now exist — the token and the count — and the token is strictly more sensitive *if* the open question below resolves in its favour.
4. **Removal detection has a second possible source.** `recently_deleted` reports removals explicitly, which the spec's contract rule did not consider. It is not a general removal log — it is iCloud's 30-day Recently Deleted window, so an asset expunged more than 30 days ago appears nowhere. It cannot replace exhaustive-sweep reconciliation, but it could make removals visible far sooner than the nightly sweep.

---

## Open question — resolved 2026-09-08

**Does the token advance on a count-neutral change?** Yes. Follow-up run: fresh baseline (`probe`), one photo toggled favourite via iCloud.com (no add/delete), then `delta`.

| | Before | After favourite toggle |
|---|---|---|
| Token | `380d6e006589` | `9646130157a8` |
| `itemCount` | 19 | 19 |
| Record set (names) | — | unchanged |

The token advanced; the count probe did not (`detected_change: false`). This is the decisive case for preferring the token: it catches edits/favourites/add+delete pairs that leave `itemCount` unmoved, which the count probe by construction cannot. `full_sweep_control.mutation_is_visible: false` is expected here and not a contradiction — that control only diffs record *names* (add/remove), and a favourite toggle changes a field on an existing record, not the record set.

**Conclusion: the token is strictly more sensitive than the count probe and should be the preferred 60s poll signal**, with the same caveats as before (n=1 per case, test account, 20 assets).

## Addition case — resolved 2026-09-08

The earlier addition attempt was invalidated by the `DESCENDING`+`startRank=0` harness bug, so uploads were never validly exercised. Follow-up run: fresh baseline (`probe`), one new photo uploaded via iCloud.com, then `delta`.

| | Before | After upload |
|---|---|---|
| Token | `9646130157a8` | `9d665dd730f2` |
| `itemCount` | 19 | 20 |
| Full-sweep control | — | `mutation_is_visible: true` |

The token advanced, and this time so did the count probe (`detected_change: true`) — an add moves `itemCount`, so this case doesn't differentiate the two signals the way the favourite toggle did. The DESCENDING page-one window also picked up the new asset directly, since a new upload sorts to rank 0; that is a property of the sort order, not evidence the token itself filtered anything — same caveat as every other resend result in this document.

**What this closes:** the primary motivating case for near-real-time sync — a newly uploaded photo — is not blind to either candidate signal. Across all three tested mutation types (delete, count-neutral favourite toggle, upload), the token has advanced every time (n=1 each), and it remains the only signal that also caught the count-neutral case.

## Limits of this result

- **Test account, 20 assets, recently created.** The negative result is the one that most deserves suspicion on a fresh account, since a token with no sync history behind it is exactly where "ignored" and "empty" are hardest to tell apart. That said, the token demonstrably *does* carry state — it advanced — so it is not merely a stub.
- **Every token advance observed here is n=1** — one mutation, one observation, per case (delete, favourite, upload).
- **Not run against the 4,527-asset production library.** Protocol semantics should not vary with row count, but the timings certainly will.
- **No case has been tested where the token does NOT advance alongside a real change** (a false negative). Everything above shows the token moving when something changes; nothing yet rules out a change the token misses.

## Harness bugs found and fixed during the spike

Recorded because two of them produced confidently wrong intermediate readings:

- `startRank=0` with `DESCENDING` returns exactly one asset regardless of `resultsLimit` — descending enumeration must start at `len-1` (cf. `increment_offset(-1)`, `base.py:1238`). This silently invalidated the first mutation control.
- Head/tail token redaction hid whether the token advanced — the very thing that turned out to matter most.
- A nested `.gitignore` pattern written as `spike/.state/` resolves to `spike/spike/.state/` and matched nothing, leaving raw tokens committable.
