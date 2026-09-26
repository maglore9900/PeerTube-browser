# Feed parameter panel

Status: planned, not approved. Requirements and High-level plan migrated from the retired `dev/FEATURE_PLANS.md` (feature `F4-M4`, milestone M4, marked optional); a build re-confirms them at dev_flow Steps 1 and 2. Open decisions O1-O3 from the old tracker were referenced but never written down; re-derive them at Step 1.

## Requirements

### What was asked

A single surface for "what shows up in my feed". Three capabilities are planned together because they share one mechanism: client-held preferences, persisted locally and applied to the feed request.

### Purpose

Let a visitor control language, a saved-channel list and continuous paging from one panel, without server-side accounts.

### Scope

**C1 — Language capture and filtering**

- Add `language_id` (lowercase code, e.g. `en`) and `language_label` to the `videos` table in `engine/crawler/schema.sql` and to `ensure_content_schema` in `engine/server/db/jobs/sync-whitelist.py`.
- Capture `video.language` in `videos-worker.ts` (`toVideoRow`); PeerTube returns it as `{"id": "en", "label": "English"}` on both the channel-videos listing and the per-video endpoint.
- Accept a `language` parameter on the Engine feed/serving paths, parameterised like the existing channel filters, and add `language` to the response projection.
- Add `language` to the per-route query allowlists in `client/backend/server.py`; unlisted parameters are rejected by the gateway.
- Two independent persisted toggles: **on/off** (default off) and **strict/preference** (exclude other languages, or rank them lower).

**C2 — Saved channels**

- A client-held list of saved channels (`instance_domain` + `channel_id`) in `localStorage` beside `localLikes:v1`, following its shape and size-cap conventions.
- Save/unsave on channels page rows and on the video page channel line.
- A feed mode restricting or boosting results to saved channels, in the same panel.
- Engine filtering by a set of `(instance_domain, channel_id)` pairs, with a server-side cap on pairs per request.

**C3 — Feed paging**

- The feed reveals six already-fetched rows at a time (`CHUNK_SIZE` in `client/frontend/src/pages/videos/index.ts`) and never refetches, so scrolling stops when the first response is exhausted.
- Refetch with an increasing offset at the scroll sentinel.
- Requires stable ordering or a seed on the Engine side so page N+1 does not repeat page N.

### Out of scope

- **Backfilling `language` for existing rows.** ~887k videos have no language value; backfill is one HTTP request per video and is its own item (I3 below). C1 defaults to off so delivery does not depend on it.
- **Following in the ActivityPub sense.** C2 is a local list; real following is roadmap `F1-M5`/`F2-M5`.
- Server-side accounts or cross-device sync of preferences.
- Changes to the recommendation mixer's scoring beyond applying these filters.

### Acceptance criteria

1. A newly crawled video row carries a non-null `language_id` when the source reports one, and null when it does not.
2. `sync-whitelist.py` completes against a fresh crawl DB with the new columns on both sides.
3. With the language toggle off, feed results are identical to current behaviour, including rows with no language.
4. Toggle on, strict: every returned row matches a selected language.
5. Toggle on, preference: other languages still appear but rank below matching ones; rows with no language are not dropped.
6. Saving a channel and selecting the saved-channels mode returns only videos from saved channels; unsaving removes it without a reload.
7. Saved channels and language preferences survive a reload and a browser restart.
8. Scrolling past the first response loads further results without repeating rows already shown.
9. The gateway rejects an unlisted parameter and accepts `language` and the saved-channels parameter.

### Consistency constraints

- **Schema and capture land together.** `_assert_columns_exact` in `sync-whitelist.py` compares the whitelist DB against `engine/crawler/schema.sql`; one side gaining a column without the other fails the sync gate.
- C1's normalisation helper belongs in `engine/crawler/src/host-filters.ts` beside `toHttpUrlOrNull` and `MAX_TEXT_FIELD_LENGTH`, not a new module.
- One feed-parameter mechanism: `docs/project/issues/17-feed-modes.md` adds modes to the same surface. The search API may later take `language` as a filter; keep one parameter name and one validation path.

### Conflicts

- **R4 — track.** Recorded as a Client-track, optional feature, but C1 changes the crawler schema and the Engine. Either widen it or move C1's capture half to a crawler/Engine feature.
- **Order against like/dislike.** Saved channels are a positive per-visitor channel list and blocks a negative one; they should share the profile store of `docs/project/plans/03-like-dislike.md` (its I5) rather than invent a second mechanism. That contradicts "preferences are local" above; resolve at Step 1.

### Test trees for this build

_Filled at build Step 0._

### Baseline suite state

_Filled at build Step 0._

## High-level plan

### Approach

Draft decomposition from planning, in the order the old implementation sequence gave:

- **I1 Language capture in crawler and schema** — schema columns + `ensure_content_schema`; `toVideoRow` capture and normalisation. Capture only affects newly crawled rows, so landing it before a crawl avoids a second full re-crawl.
- **I2 Language serving and filtering** — Engine parameter + response projection; gateway allowlist entry.
- **I3 Language backfill** — job over `/api/v1/videos/<uuid>`, resumable, rate-limited per host. Whenever convenient; nothing blocks on it.
- **I4 Saved channels store and controls** — `localStorage` store; save/unsave on channels page and video page. After like/dislike I5.
- **I5 Saved channels feed filtering** — Engine filter by `(instance_domain, channel_id)` set with a server-side cap; gateway allowlist.
- **I6 Feed paging** — offset/seed on the Engine; sentinel-triggered refetch. After like/dislike I4, because down-ranking changes the ordering it pages through and the seed should be designed once.
- **I7 Feed parameter panel UI** — one panel binding the language toggles, saved-channels mode and feed modes; preferences persisted. Last: it binds every input above.

Seven items exceed the four phases one build allows; expect to split this into more than one plan file before building.

### Risks

- **R1 — Sparse language data.** Many instances leave `language` unset or wrong; strict mode may empty the feed. Default off, default preference over strict, never drop unknown-language rows in preference mode.
- **R2 — Backfill cost.** ~887k per-video requests is a multi-day job with the same rate-limit exposure as the tags stage. Keep it separate and resumable.
- **R3 — Paging stability.** The random feed has no stable ordering; naive offsets repeat and skip rows. Require a seed.
- **R4 — Track mismatch.** See Conflicts.
- **R5 — Saved-channel request size.** An unbounded pair set per request is audit finding F11's class. The server-side cap is required.

### Validation strategy (from planning)

- Language normalisation and the saved-channel store round-trip, as standalone harnesses in the style of `engine/crawler/test-url-safety.mjs`.
- Schema gate: `sync-whitelist.py` against a scratch crawl DB built from `engine/crawler/schema.sql`.
- Contract: `tests/check-frontend-client-gateway.sh`, `tests/check-client-engine-boundary.sh`.
- End to end: `tests/run-arch-split-smoke.sh` after the Engine parameter lands.
- Manual in the operator's browser: criteria 3-8.

### Rollback notes (from planning)

- C1 filtering, C2 and C3 are client-triggered; with the panel defaulting to off, rollback is not enabling the control.
- The schema columns are additive and nullable; leaving them with no writer is harmless.
- The backfill is resumable and writes only the new columns.

## Impacts

_Filled at build Step 3._

### Highest risk

### Reassessment

### Documentation to update

## Implementation plan

_Filled at build Steps 5-6._

### Phases

## Inner unit tests

## Close
