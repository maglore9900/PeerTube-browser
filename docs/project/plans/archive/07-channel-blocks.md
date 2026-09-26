# Block a channel or account

Parent: `docs/project/plans/03-like-dislike.md` (S7; the block part of S8, I5, I6, I7, I8). Dislikes are the second build from plan 03.
Depends on: `docs/project/plans/archive/06-profile-key-identity.md` (delivered).

## Requirements

Confirmed by the operator at Step 1.

### What was asked

"lets build the dislike and block features now." Split at Step 1 into two builds; this one is blocks.

### Purpose

A visitor with a profile can remove a channel or an account from their own feeds and search results for good, without affecting any other visitor. It is the hard control beside dislike's soft one (plan 03 O2).

### Current state (read at Step 1)

- Identity exists: `client/backend/lib/profiles.py` resolves `X-Profile-Key` to a `profile_id` held in `client/backend/db/users.db`; `ClientBackendHandler._require_profile` (`client/backend/server.py:282`) sends the single 401.
- Feed and search requests reach the Engine only through the Client's read proxy (`PROXY_READ_GET_ROUTES`, `PROXY_READ_POST_ROUTES`, `client/backend/server.py:50-74`). The frontend sends no profile key on them today.
- The Engine holds no user state; `DEPLOYMENT.md:258` states the boundary as mandatory and `tests/run-arch-split-smoke.sh` enforces it.
- The Engine's operator moderation (`engine/server/data/moderation.py`, `serving_moderation.py`) filters rows after selection. This feature does not touch it.
- `whitelist.db`, measured with `tests/tmp/probe_account_identity.py`: 890,052 videos, every one with a `channel_id` and an `account_url`; 45,807 channels, 36,651 accounts, 4,067 of those accounts own more than one channel. There is no account id column, so an account is identified by its `account_url`.

### Decisions (Step 1)

- **Storage.** Blocks are stored by the Client backend in `users.db`, keyed by `profile_id`. Plan 03 O4 (an Engine-side profile database) is superseded.
- **Where the filter runs.** The Client filters the Engine's response before returning it to the browser. Nothing about blocks is sent to the Engine, and the Engine does not change. To keep pages full, the Client over-fetches from the Engine when the visitor has any blocks, filters, and truncates to the requested limit.
- **A profile is required.** Blocks exist only for a profile.
- **Bad key on a feed (Q6, O1).** A feed or search request carrying a key that does not resolve gets the same 401 as the profile routes. The frontend then says the key is no longer valid and offers to forget it.
- **Search is filtered (Q7).**
- **Controls on video cards and on the channels page (Q8)** are deferred to a follow-up feature, listed in `docs/project/roadmap.md` as F13-M2.
- **Two stateless Engine changes (Step 2, F1-F3).** The Engine's public row projection (`STABLE_VIDEO_FIELDS`, `engine/server/api/handlers/similar.py:79`) omits `channel_id` and `account_url`, so the Client could not match a row against a block. The Engine also caps a feed `limit` at `default_limit` (the home batch size, 48; `similar.py:824`), which would defeat the over-fetch. Accepted by the operator:
  - `channel_id` and `account_url` are added to the projection.
  - The Engine accepts a feed `limit` up to twice `default_limit`. The Client caps the browser's `limit` at the current value, so only the Client makes the larger request.
  - Search is filtered page by page, without over-fetch or refill. Its pages can come back short, and B4 covers the feeds only.

### Acceptance criteria

- **B1.** The Client has profile routes to list, add and remove blocks. A channel block is keyed by `instance_domain` + `channel_id`; an account block by `account_url`. The routes take the key only from `X-Profile-Key` and answer an absent, malformed or unknown key with the same 401 as the existing profile routes.
- **B2.** Once a channel is blocked, its videos are absent from the home, random and up-next feeds (`/recommendations`, `/videos/similar`) and from search (`/api/v1/search/videos`), immediately and on later visits, until it is unblocked.
- **B3.** Blocking an account removes the videos of every channel it owns, on the same routes as B2.
- **B4.** A filtered feed response (`/recommendations`, `/videos/similar`) is a full page unless more than half of the over-fetched rows are blocked; in that case it returns what remains and does not refill. A filtered search page returns the unblocked rows of that page and may be short.
- **B5.** The browser adds only the `X-Profile-Key` header to a feed or search request. Its request size does not depend on the number of blocks.
- **B6.** Blocks live in `users.db`, which no dataset build or updater touches.
- **B7.** One visitor's blocks never change another visitor's feed or search results.
- **B8.** Without a key, feeds and search behave exactly as today. The block controls prompt the visitor to create a profile.
- **B9.** A feed or search request carrying a key that does not resolve gets the same 401 as the profile routes, and the frontend offers to forget the key.
- **B10.** Deleting a profile deletes its blocks.
- **B11.** The video page offers "Block channel" and "Block account". The profile modal lists the profile's blocks, each with an unblock control.
- **B12.** Blocks are independent of dislikes. Nothing in this build blocks a channel implicitly.

### In scope

`engine/server/api/handlers/similar.py` (projection and feed limit cap), `client/backend/server.py`, `client/backend/lib/users_store.py`, `client/backend/lib/profiles.py` (profile deletion), a new block-store module under `client/backend/lib/`, the frontend feed and search data modules, `client/frontend/src/data/profile.ts`, the video page, the profile modal in `index.html` and `videos.html`, `DEPLOYMENT.md`.

### Out of scope

- Dislikes and any change to the like buttons (plan 03's second build).
- Block controls on video cards and on the channels page (follow-up feature).
- Any Engine change beyond the two in Decisions, including its operator moderation. The Engine holds no user state.
- Issue 02 (resolving the real client address behind nginx).
- Filtering `/api/video` (a single video page stays reachable, which is where a block is undone from).

### Consistency constraints

Backend matches `client/backend` style: stdlib `http.server`, `respond_json`, `sqlite3.Row`, module docstrings, `from __future__ import annotations`. Frontend matches `data/*.ts` (fetch through `resolveClientApiBase`, `readErrorMessage`) and the existing modal and `ghost-button` markup; every rendered value is escaped. Backwards compatibility is not required.

### Conflicts

- **Plan 03 O4 vs this build.** O4 put the filter profile in the Engine. Resolved by the operator: Client storage, Client-side filtering. Plan 03 records the supersession.
- **Plan 03 criterion 15 vs B4.** Criterion 15 asked for exclusion from the candidate pool so a page is always full. Resolved by the operator: B4's over-fetch, with a short page accepted when more than half the over-fetched rows are blocked.
- **"No Engine change" vs the Engine's projection and limit cap.** Found at Step 2. Resolved by the operator: the two stateless Engine changes in Decisions.

### Test trees for this build

- `active`: `tests/active`
- `working`: `tests/tmp`

### Baseline suite state

Step 0, `scripts/validate_tests.py` bare run: "unchanged since 2026-09-26T07:48:44-04:00 — every fingerprint still holds", 12 passed. Reused from the banked record. Green.

## High-level plan

Approved by the operator at Step 2, with the 1,000-block cap per profile ("for now").

### Approach

- **Engine projection and limit.** `STABLE_VIDEO_FIELDS` gains `channel_id` and `account_url`, so every feed and search row carries the identity a block matches on. `_handle_similar` accepts a `limit` up to twice `default_limit`. Nothing else in the Engine changes, and it holds no user state (B6, B7).
- **Block store (B1, B6, B10).** A `blocks` table in `users.db`: `profile_id`, `kind` (`channel` or `account`), `instance_domain`, `channel_id`, `account_url`, a display `label`, `created_at`. It is unique per profile and target. A new `client/backend/lib/blocks.py` holds `add_block`, `remove_block`, `list_blocks` and `load_block_keys`; the last returns the two key sets the filter needs. `delete_profile` removes the profile's blocks in the same transaction as its other rows. A profile holds at most 1,000 blocks; adding one more gets a 400 that says so.
- **Block routes (B1).** `GET /api/profile/blocks`, `POST /api/profile/blocks` and `POST /api/profile/blocks/remove`, following the existing `POST /api/profile/delete` style. All three go through `_require_profile` and the standard rate limiter. Input is validated at the boundary: a `kind` from the two allowed values, a host-shaped `instance_domain`, a non-empty length-capped `channel_id`, an http(s) `account_url`, and a length-capped `label`.
- **Filtering in the proxy (B2-B5, B7-B9).** For `/recommendations`, `/videos/similar` and `/api/v1/search/videos`:
  - No `X-Profile-Key`: the proxy passes the request through unchanged (B8).
  - A key that does not resolve: the fixed 401 before any Engine call (B9).
  - A resolved profile with no blocks: passed through unchanged.
  - A profile with blocks: the proxy loads the key sets and parses the Engine's JSON. It drops every row whose `instance_domain` + `channel_id` or `account_url` is blocked, rewrites `count`, and responds.
  - Feeds over-fetch: the Client asks the Engine for twice the page size and truncates to the page after filtering (B4). The page size is the browser's `limit`, or the Client's own copy of the home batch size, 48, when the browser sends none. Browser limits are capped at 48 either way.
  - Search is filtered page by page with no over-fetch.
  - The key is never forwarded to the Engine.
- **Frontend.**
  - `fetchSimilarVideosPayload` (every feed, including up next) and `fetchSearchResults` send `profileHeaders()`. With a key stored, search bypasses its two-minute `sessionStorage` cache, so a new block shows up at once.
  - A 401 on a feed or search shows "Your profile key is no longer valid" with a control to forget the key (B9).
  - The video page gets "Block channel" and "Block account" buttons, which without a key prompt for a profile (B8, B11).
  - The profile modal in `index.html` and `videos.html` lists blocks with an unblock control (B11). Every label is escaped.
- **Docs.** `DEPLOYMENT.md` gains the block routes and notes that the proxy filters per profile.

### Alternatives

- **Filter inside the Engine from an Engine-side profile store** (plan 03 O4). Rejected at Step 1: it gives the Engine user state.
- **Send the block lists to the Engine on each request.** Rejected at Step 1: the internal request grows with blocks, and the Engine still needs a filter.
- **Post-filter with no over-fetch.** Rejected: every blocked row shortens the page.
- **Re-request when a page comes back short.** Rejected at Step 2: a second home request returns many of the same rows, so it cannot guarantee a full page.
- **Match on `channel_url` alone, with no Engine change.** Rejected at Step 2: it cannot support account blocks (B3).

### Risks

- **R1. Duplicated default.** The Client's copy of the 48-row home batch size must match the Engine's `default_limit`. If it drifts, pages are sized wrongly for visitors with blocks.
- **R2. Rows without identity.** A row that reaches the projection without `channel_id` or `account_url` matches no block and is shown. Step 3 checks every candidate source and the similarity cache for those fields.
- **R3. Cost.** For a visitor with blocks, each feed request does twice the Engine work, plus one JSON parse and re-serialise in the Client. Their search requests skip the frontend cache.
- **R4. Account identity is `account_url`.** An instance that changes its URL form breaks existing account blocks silently.
- **R5. Block labels are visitor-supplied.** They are stored length-capped and escaped on render, and are never used as identity.
- **R6. The feed `limit` ceiling doubles on the Engine.** Only the Client can reach it, because the Client caps what the browser can ask for. The Engine is loopback-bound (`DEPLOYMENT.md`).

### Tradeoffs accepted

- Search pages can be short.
- A feed page can be short when more than half the over-fetched rows are blocked.
- Blocks require a profile.
- A 1,000-block cap per profile.
- Two stateless Engine changes.

## Impacts

### E1 Engine row projection
- **path:** `engine/server/api/handlers/similar.py` (`STABLE_VIDEO_FIELDS`, line 79)
- **Changes:** gains `channel_id` and `account_url`.
- **Depends on it:** every `/recommendations`, `/videos/similar` and `/api/v1/search/videos` response (`_respond_rows`, `_handle_search_videos`), and the frontend `VideoRow` readers.
- **Row sources checked (R2):** every row reaching the projection comes from `data/metadata.py` (`fetch_metadata`, `fetch_metadata_by_ids`, used by the random cache and by `similarity_candidates._build_rows`), `data/random_videos.py` (random, recent, popular) or `data/search.py` (`dict(row)` over a SELECT of `v.channel_id`, `v.account_url`). All of them carry both fields. `whitelist.db` has no null `channel_id` or `account_url`.
- **Regression risk:** low. Additive fields. `account_url` is a crawled URL; nothing renders it from feed rows today, and any future render must go through `safeExternalUrl` (security audit run 1, the URL-sink finding).

### E2 Engine feed limit cap
- **path:** `engine/server/api/handlers/similar.py` (`_handle_similar`, lines 821-825)
- **Changes:** the cap becomes twice `default_limit`.
- **Depends on it:** `_handle_random` (uses `limit` directly), `_handle_seed_with_embedding` (truncates `rows[:limit]` from `similar_per_like` = 1000 candidates, so a 16- or 96-row request is satisfiable), `_handle_home` → `MixingRecommendationStrategy.generate_recommendations`, `_handle_vector_search`.
- **Regression risk:** medium. See E3: the home path caps again below this one.

### E3 Engine mixer batch cap (found at Step 3)
- **path:** `engine/server/api/recommendations/mixer.py` (`generate_recommendations`, lines 69-76)
- **Changes:** `batch_size = min(request_limit or configured_batch, configured_batch)` caps the home feed at the profile's `batch_size` (48) whatever `_handle_similar` allows. To over-fetch the home feed, this cap must also accept up to twice `configured_batch`.
- **Depends on it:** every generator's fetch limit (`_resolve_fetch_limits` scales with `batch_size`), the mix ratios, `soft_caps` (`fresh` ≤ 12 is absolute, so at 96 rows fresh's share halves), and both `home` and `guest_home` profiles.
- **Regression risk:** high. It is the ranking pipeline. Whether the first 48 of a 96-row mix keep the configured ratios depends on the mixer's output order, which is not yet verified.

### E4 Engine video metadata response (found at Step 3; DROPPED at Step 5, superseded by blocking by video reference)
- **path:** `engine/server/api/handlers/video.py` (`response`, lines 271-290)
- **Changes:** `/api/video` returns `accountUrl` but not the channel id, so the video page cannot build a channel block. It gains `channelId` from `row["channel_id"]`.
- **Depends on it:** `client/frontend/src/pages/video-page/index.ts` `fetchVideoMetadataFromServer` (line 383).
- **Regression risk:** low. Additive field.

### E5 Client user schema
- **path:** `client/backend/lib/users_store.py` (`ensure_user_schema`)
- **Changes:** creates `blocks` (`profile_id`, `kind`, `instance_domain`, `channel_id`, `account_url`, `label`, `created_at`) with a uniqueness constraint per profile and target, and an index on `profile_id`.
- **Depends on it:** `server.py` `main`, the test fixture `tests/active/conftest.py` (calls `ensure_user_schema`).
- **Regression risk:** low. `CREATE TABLE IF NOT EXISTS`, idempotent.

### E6 Block store module (NEW)
- **path:** `client/backend/lib/blocks.py`
- **Changes:** `add_block` (enforces the 1,000 cap), `remove_block`, `list_blocks`, `load_block_keys`.
- **Depends on it:** the block routes (E8) and the proxy filter (E9).
- **Regression risk:** medium. It defines what a match is.

### E7 Profile deletion
- **path:** `client/backend/lib/profiles.py` (`delete_profile`, line 69)
- **Changes:** also deletes the profile's `blocks` rows in the same transaction.
- **Depends on it:** `POST /api/profile/delete`; `tests/active/test_profiles.py` deletion test (counts `profiles`, `users`, `likes` only, so it stays green).
- **Regression risk:** low.

### E8 Block routes
- **path:** `client/backend/server.py` (`do_GET`, `do_POST`)
- **Changes:** `GET /api/profile/blocks`, `POST /api/profile/blocks`, `POST /api/profile/blocks/remove`, each rate-limited and behind `_require_profile`; input validation.
- **Depends on it:** frontend block data module (E12).
- **Regression risk:** low. New routes only.

### E9 Read proxy filtering
- **path:** `client/backend/server.py` (`_handle_engine_read_proxy_get`, `_handle_engine_read_proxy_post`, `_proxy_engine_request`, lines 299-554; constants lines 40-74)
- **Changes:** resolves an optional key on the three filtered routes (401 when presented and unresolved); for a profile with blocks, rewrites `limit` for the over-fetch, buffers the Engine's 200 response, filters `rows`, truncates, rewrites `count`. `_proxy_engine_request` today writes the Engine's bytes straight to the browser in two branches (success and `HTTPError` with payload); the filtered success path needs the body first. Browser `limit` is capped at 48 on the feed routes. New constants: the feed page size (48), the over-fetch factor (2).
- **Depends on it:** every feed and search request; `tests/run-arch-split-smoke.sh` stage 3 and 4 (keyless feeds, which stay pass-through).
- **Regression risk:** high. Every read goes through it, and a fault here breaks the home page for everyone.

### E10 Frontend feed fetch
- **path:** `client/frontend/src/data/videos.ts` (`fetchSimilarVideosPayload`, line 77)
- **Changes:** sends `profileHeaders()`; a 401 throws a distinguishable key-rejected error.
- **Depends on it:** `pages/videos/index.ts` (lines 209-222, home, random and similar feeds) and `pages/video-page/index.ts` (line 235, up next).
- **Regression risk:** medium.

### E11 Frontend search fetch
- **path:** `client/frontend/src/data/search.ts` (`fetchSearchResults`, line 54); `client/frontend/src/data/cache.ts` (`fetchJsonWithCache` sends no headers)
- **Changes:** with a key stored, search fetches directly with the header and skips the `sessionStorage` cache; a 401 throws the key-rejected error. `cache.ts` stays unchanged.
- **Depends on it:** `pages/search/index.ts` (line 131).
- **Regression risk:** low.

### E12 Frontend profile and block data
- **path:** `client/frontend/src/data/profile.ts`; `client/frontend/src/data/blocks.ts` (NEW)
- **Changes:** `profile.ts` gains `forgetProfileKey` and the key-rejected error type. `blocks.ts` lists, adds and removes blocks through the Client API base with the header.
- **Depends on it:** E13-E15.
- **Regression risk:** low. `tests/check-frontend-client-gateway.sh` requires Client-base fetches only, which this follows.

### E13 Profile modal (home and videos pages)
- **path:** `client/frontend/src/pages/videos/index.ts` (`renderProfileSection`, lines 631-711; feed load lines 209-222)
- **Changes:** with a key, the modal lists blocks with unblock controls; the feed shows the key-rejected message with a "Forget key" control. The no-profile intro text (line 688) is updated.
- **Regression risk:** medium. Shared by `index.html` and `videos.html`.

### E14 Profile modal markup
- **path:** `client/frontend/index.html`, `client/frontend/videos.html` (`#profile-modal`, lines 50-61)
- **Changes:** a blocks container in the modal.
- **Regression risk:** low.

### E15 Video page
- **path:** `client/frontend/src/pages/video-page/index.ts`; `client/frontend/video-page.html` (channel row, lines 40-58); `client/frontend/src/video.css`
- **Changes:** "Block channel" and "Block account" buttons, enabled only when metadata carries `channelId` and `accountUrl` from `/api/video`; without a key they tell the visitor to create a profile from the Profile button. Up next handles the key-rejected error. The page has no profile modal of its own.
- **Regression risk:** medium. The page also falls back to instance metadata (`fetchVideoMetadataFromInstance`, line 426), whose channel id is the instance's own; blocks stay disabled on that path.

### E16 Search page
- **path:** `client/frontend/src/pages/search/index.ts` (line 138)
- **Changes:** shows the key-rejected message with a "Forget key" control.
- **Regression risk:** low.

### E17 Frontend row type
- **path:** `client/frontend/src/types/videos.ts`
- **Changes:** `VideoRow` gains optional `channel_id` and `account_url`.
- **Regression risk:** low.

### E18 Split smoke test
- **path:** `tests/run-arch-split-smoke.sh`
- **Changes:** none planned. It calls the feed routes without a key, which stay pass-through. Checked at Step 8.
- **Regression risk:** low.

### E20 Built frontend (found at Step 4)
- **path:** `client/frontend/dist/` (tracked in git; `index.html`, `videos.html`, `video-page.html`, `search.html` and their `assets/`)
- **Changes:** rebuilt with the project's build after the frontend changes, so the deployed bundle carries them.
- **Depends on it:** the deployment `rsync` of `dist/`.
- **Regression risk:** low. A stale `dist/` ships none of the frontend half.

### E19 Documentation
- **path:** `DEPLOYMENT.md` (line 256 profiles paragraph; line 258 boundary contract), `client/README.md` (route list, lines 11-27), `README.md` (boundary table, line 47), `CONTEXT.md` (empty glossary), `engine/server/api/recommendations/docs/LAYER_PARAMS.md` (if E3 changes how `batch_size` is read).

### Highest risk

- **E3 mixer batch cap.** It changes the ranking pipeline's sizing for the home feed, and the effect of truncating a 96-row mix on the mix ratios is unverified.
- **E9 read proxy filtering.** Every feed and search request passes through it; buffering and rewriting the body is new behaviour on the most-used path.
- **E6 block store.** A wrong match rule either leaks blocked videos or hides unblocked ones, silently.

### Reassessment

#### Pass 1

**1. Will it still work as intended?** Yes, but only with E3 and E4, which the approved plan did not name.
- Without E3 the home feed cannot over-fetch: the mixer re-caps at 48 below the handler's cap.
- Without E4 the video page has no channel id to block.
- E3 is viable. The mixer's `_build_layer_schedule` (`mixer.py:260`) interleaves layers by least-filled ratio, and each layer is sorted by score before mixing. So the first 48 rows of a 96-row mix keep the configured ratios and take each layer's top half, which is close to what a 48-row request selects. The `fresh` soft cap of 12 is not reached at 96 (target 9.6).

**2. Ramifications.**
- For a visitor with blocks, a home request runs the generators at twice their fetch limits.
- The Engine accepts `limit` up to 96 from any caller that can reach it. It is loopback-bound, and the Client caps browser limits at 48.
- The Engine's public response grows by two fields per row.

**3. What else must happen for existing functionality to keep working.**
- `dist/` is rebuilt (E20).
- `tests/run-arch-split-smoke.sh` keeps passing with keyless feeds (E18).
- `tests/active/test_profiles.py` keeps passing; its deletion test counts only the tables it knew about (E7).

**4. How the original functionality is altered.**
- A feed or search request carrying an unresolvable key now gets a 401. Before, the proxy ignored the header.
- Search results are not cached in the browser for a visitor holding a key.
- Keyless behaviour is unchanged.

**Entries the files did not bear out.** None. Every entry was opened at its path during Steps 3 and 4.

**New impacts this pass.** E20. E3 and E4 were added at Step 3, not in this pass.

**Recommendation put to the operator.** Accept E3 (mixer cap to twice `batch_size`) and E4 (`channelId` on `/api/video`) as part of the approved "stateless Engine changes". Both are stateless.
- **E3's cost:** a change in the ranking pipeline's sizing, reached only by the Client's over-fetch.
- **E4's cost:** one response field.

Approved by the operator ("accept proceed").

#### Pass 2

No new impact and no unconfirmed entry.
- CORS already allows `x-profile-key` (`client/backend/lib/http_utils.py:12`).
- The Engine's own tests (`engine/server/api/tests/`) assert on neither the projection nor the limit cap.
- `similar_per_like` = 1000 and `similarity_max_per_author` = 1 (`server_config.py:314,322`), so an up-next request for 16 rows is satisfiable.

Steps 3-4 converged.

### Documentation to update

- [ ] `DEPLOYMENT.md` — the block routes, per-profile filtering in the read proxy, and the key on feed and search requests.
- [ ] `client/README.md` — the three block routes and the filtered read gateway.
- [ ] `README.md` — the boundary table's Client write/profile row gains the block routes; the read gateway row notes per-profile filtering.
- [ ] `CONTEXT.md` — glossary terms: profile, block.
- [ ] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` — only if E3 changes how `batch_size` caps a request.

## Implementation plan

### Draft (Step 5)

#### Proposed adjustment: block by video reference (drops E4)

The Client already resolves a video through the Engine over the authenticated bridge: `resolve_video_seed` → `/internal/videos/resolve`, which returns `video_id`, `instance_domain` and `channel_id`; `fetch_metadata_for_entries` → `/internal/videos/metadata`, which returns the full row with `account_url`, `account_name` and the channel names (`client/backend/lib/engine_api_client.py:66,92`). So `POST /api/profile/blocks` takes `{kind, uuid, host}` for a video the visitor is looking at, and the Client derives the block target and its label from the Engine's own data.
- **What it saves:** E4 (`channelId` on `/api/video`) is no longer needed. The browser never supplies a channel id, an account URL or a label, so there is nothing to validate beyond `kind`, `uuid` and `host`. The label comes from crawled data, which is still escaped on render.
- **What it costs:** two Engine calls per block action, none per feed request.

This changes an approved impact and is put to the operator with the Step 5 draft.

**Accepted by the operator.** They confirmed the kinds stay channel and/or account ("i mean to say channel and/or account") and did not object to blocking by video reference. E4 is dropped: `engine/server/api/handlers/video.py` is not touched.

#### What this build must test

- **T1.** The match rule: a row is dropped exactly when its `(instance_domain, channel_id)` is a channel block or its `account_url` is an account block of this profile.
- **T2.** The block routes: add (from a video reference), list, remove; the 401 on each; the 1,000 cap; an unknown video.
- **T3.** The proxy: a keyless request is unchanged; an unresolvable key is refused with the fixed 401; a profile's blocked rows are absent from feeds and search; a feed page is refilled to its size from the over-fetch; one profile's blocks leave another's results alone.
- **T4.** Profile deletion removes blocks.
- **T5.** The Engine returns `channel_id` and `account_url` on each row and serves up to twice `default_limit` rows on the home, random and up-next paths.
- **T6.** The frontend data modules send the key on feed and search requests and surface a 401 as a key-rejected error; the block data module round-trips.

#### Engine

`engine/server/api/handlers/similar.py`
```python
STABLE_VIDEO_FIELDS = (
    "video_id", "video_uuid", "instance_domain", "channel_id", "account_url",
    ...  # existing fields unchanged
)

# The Client over-fetches for visitors with blocks, then trims to one page.
FEED_LIMIT_OVERFETCH = 2

# _handle_similar
limit = _parse_int(params.get("limit", [str(self.server.default_limit)])[0])
if limit == 0:
    limit = self.server.default_limit
max_limit = self.server.default_limit * FEED_LIMIT_OVERFETCH
if self.server.default_limit > 0 and limit > max_limit:
    limit = max_limit
```

`engine/server/api/recommendations/mixer.py` (`generate_recommendations`)
```python
if configured_batch > 0:
    # Twice the batch is the Client's over-fetch for visitors with blocks.
    batch_size = min(request_limit or configured_batch, configured_batch * 2)
```
Invariant: a request with no `limit`, or with `limit` ≤ `batch_size`, selects exactly as before.

#### Client store

`client/backend/lib/users_store.py` (`ensure_user_schema` gains):
```sql
CREATE TABLE IF NOT EXISTS blocks (
  profile_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('channel', 'account')),
  instance_domain TEXT NOT NULL DEFAULT '',
  channel_id TEXT NOT NULL DEFAULT '',
  account_url TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  PRIMARY KEY (profile_id, kind, instance_domain, channel_id, account_url)
);
```
Empty strings rather than NULLs, because SQLite treats NULLs as distinct in a key and would admit duplicate account blocks. A channel block has `account_url = ''`; an account block has `instance_domain = channel_id = ''`.

`client/backend/lib/blocks.py` (NEW)
```python
MAX_BLOCKS = 1000
KINDS = ("channel", "account")

class BlockLimitReached(Exception): ...

def block_target(kind: str, row: dict) -> dict | None
    # channel -> {kind, instance_domain, channel_id, account_url: "", label: channel display or name}
    # account -> {kind, instance_domain: "", channel_id: "", account_url, label: account_name}
    # None when the row lacks the identity for that kind.
def add_block(conn, profile_id: str, target: dict) -> None
    # One transaction: count, raise BlockLimitReached at MAX_BLOCKS unless the target
    # is already blocked, INSERT OR IGNORE.
def remove_block(conn, profile_id: str, target: dict) -> None
def list_blocks(conn, profile_id: str) -> list[dict]           # newest first
def load_block_keys(conn, profile_id: str) -> tuple[set[tuple[str, str]], set[str]]
def filter_blocked(rows: list[dict], keys) -> list[dict]
    # Drops a row when (instance_domain, channel_id) is in keys[0] or account_url is in keys[1].
```

`client/backend/lib/profiles.py` `delete_profile` gains `DELETE FROM blocks WHERE profile_id = ?` in its transaction.

#### Client server

`client/backend/server.py`
- **Constants.**
  - `FEED_PAGE_SIZE = 48`, marked with a `rat-tail:` comment saying it mirrors the Engine's home `batch_size`.
  - `FEED_OVERFETCH_FACTOR = 2`.
  - `FEED_ROUTES = frozenset(("/recommendations", "/videos/similar"))`.
  - `FILTERED_ROUTES = FEED_ROUTES | {"/api/v1/search/videos"}`.
- **`_block_filter(path, sanitized_query)`** returns `(proceed, keys, page_size)`. It runs in both proxy handlers after query sanitising and before `_proxy_engine_request`.
  - On a feed route, `limit` is capped at `FEED_PAGE_SIZE` for everyone; absent, it is treated as `FEED_PAGE_SIZE`.
  - The path is not filtered, or there is no `X-Profile-Key` header: pass through.
  - A header that `resolve_profile` rejects: the fixed 401 (`respond_json(self, 401, {"error": "Profile key required"})`), and `proceed` is False.
  - A profile with no blocks: pass through.
  - Otherwise it returns the key sets. On a feed route it also sets `limit` to `page_size * FEED_OVERFETCH_FACTOR`.
- **`_proxy_engine_request(..., block_keys=None, page_size=None)`.** In the 200 branch with `block_keys`, it JSON-decodes the payload, sets `rows = filter_blocked(rows, block_keys)[:page_size]` (search: no truncation), sets `count = len(rows)`, re-encodes and responds. A 200 body that is not a JSON object with a `rows` list is answered with 502 `ENGINE_PROXY_INVALID`, never passed through, so a blocked row cannot leak on a malformed response. Other branches are unchanged.
- **`GET /api/profile/blocks`** → `{"blocks": list_blocks(...)}`.
- **`POST /api/profile/blocks`**
  - Body `{kind, uuid, host}`: `kind` in `KINDS`; `uuid` and `host` non-empty strings of at most 200 characters; otherwise 400.
  - The Client calls `resolve_video_seed`, then `fetch_metadata_for_entries`, then `block_target`, then `add_block`, and answers 201 `{"block": target}`.
  - Unknown video → 404. `BlockLimitReached` → 400 `"Block limit reached (1000)"`. `EngineApiError` → 502.
- **`POST /api/profile/blocks/remove`**
  - Body `{kind, instance_domain, channel_id, account_url}`, as `list_blocks` returns it: strings, `kind` validated.
  - `remove_block` → 204.
- All three block routes go through `_rate_limit_check` and `_require_profile`.

#### Frontend

- **`data/profile.ts`**
  - `class ProfileKeyRejectedError extends Error`.
  - `forgetProfileKey()` removes the stored key.
- **`data/videos.ts` `fetchSimilarVideosPayload`**
  - Sends `{ "content-type": "application/json", ...profileHeaders() }`.
  - A 401 throws `ProfileKeyRejectedError`.
- **`data/search.ts` `fetchSearchResults`**
  - With a key stored, it calls `fetch(url, { headers: profileHeaders(), cache: "no-store" })`, with no `sessionStorage` cache.
  - A 401 throws `ProfileKeyRejectedError`; a 503 throws `SearchUnavailableError`.
  - Without a key, the current cached path is unchanged.
- **`data/blocks.ts` (NEW)**
  - `listBlocks(apiBase)`.
  - `blockVideoSource(apiBase, kind, uuid, host)`.
  - `unblock(apiBase, block)`.
  - All three send the header and throw the server's error message.
- **`pages/videos/index.ts`**
  - With a key, `renderProfileSection` appends a "Blocked" list from `listBlocks`: one row per block with its label, kind and an "Unblock" button, all built with `textContent`.
  - The no-profile intro drops "will attach to" and says blocks need a profile.
  - A feed `ProfileKeyRejectedError` shows "Your profile key is no longer valid" with a "Forget key" button, which calls `forgetProfileKey` and reloads the feed.
- **`index.html`, `videos.html`:** no markup change. The list renders inside the existing `#profile-section`, which reduces E14 to nothing.
- **`video-page.html`, `pages/video-page/index.ts`, `video.css`**
  - `#block-channel` and `#block-account` buttons in the channel row, plus a status line.
  - The buttons are enabled once the video's uuid and host are known: from `/api/video` metadata (`videoUuid`, `instanceName`), or from the `id`/`host` page parameters.
  - Without a key, a click sets the status to "Blocking needs a profile. Create one from the Profile button on the home page."
  - A successful block sets "Blocked <label>. Its videos no longer appear in your feeds."
  - Up next handles `ProfileKeyRejectedError` with the same message and "Forget key" control.
- **`pages/search/index.ts`:** handles `ProfileKeyRejectedError` the same way.
- **`types/videos.ts`:** `VideoRow` gains optional `channel_id` and `account_url`.
- **`dist/`:** rebuilt with `npm run build`.

#### Check against plan and requirements (pass 1)

- **Each B criterion is covered.**
  - B1: routes. B2, B3: `filter_blocked` on all three routes.
  - B4: over-fetch and truncation on the feed routes; search page by page.
  - B5: header only. B6: `users.db`. B7: keys loaded per profile.
  - B8: header-absent pass-through; video-page prompt. B9: 401 plus "Forget key". B10: `delete_profile`.
  - B11: video page buttons and the modal list. B12: nothing links blocks to dislikes.
- **Misses found and fixed in the draft.**
  - The keyless feed `limit` must also be capped at 48, because the Engine now accepts 96.
  - A malformed Engine 200 must not pass through unfiltered.
- **Converged in one pass**, pending the operator's answer on the proposed adjustment.

### Phases

Approved by the operator at Step 6 ("approve").

#### Common seam

- **Services.** Phases 1-4 run against a real Engine and a real Client backend, with no double for either.
  - A `tests/tmp/conftest.py` session fixture starts the Engine as a subprocess, the way `tests/run-arch-split-smoke.sh:524-526` does: `engine/.pixi/envs/default/bin/python engine/server/api/server.py --host 127.0.0.1 --port <free> --no-random-cache-refresh`, with `ENGINE_INGEST_MODE=bridge` and a test `ENGINE_BRIDGE_TOKEN`. It uses the repo's dataset and waits for `/api/health` = 200.
  - A function fixture starts the Client in-process, as `tests/active/conftest.py` does, but pointed at that Engine with the same bridge token, over a `users.db` under `tmp_path`.
- **Expected values.** Where a clause names what the dataset holds, the expected value is read independently from `engine/server/db/whitelist.db`, opened read-only with `sqlite3`. It never comes from a response.
- **Startup cost.** How long the Engine takes to start is measured by a probe at 7.1 before the fixture is written.

#### Phase 1 — The Engine returns row identity and serves an over-fetch

- **Kind:** code
- **Files:**
  - `engine/server/api/handlers/similar.py` (EDITED)
  - `engine/server/api/recommendations/mixer.py` (EDITED)
  - `tests/tmp/conftest.py` (NEW, common seam)
  - `tests/tmp/test_engine_row_identity.py` (NEW, checkpoint)
- **Intent (post-phase state):** A caller of the Engine's feed and search routes receives, with every row, the `channel_id` and `account_url` of the video it describes. A caller asking the home, random or up-next feed for twice `default_limit` rows receives more than `default_limit`.
- **Clauses:**
  - `C1` — Every row of an Engine home, random, up-next and search response carries the `channel_id` and `account_url` that `whitelist.db` holds for that row's `video_id` and `instance_domain`.
  - `C2` — An Engine home and random request with `limit` = twice `default_limit` returns more than `default_limit` rows.
  - _Amended at 7.1 with operator approval: "up-next" removed. The probe (`tests/tmp/probe_engine_start.py`) found up-next returns 8-18 rows for 12 seeds, the same at `limit` 48 and 96. Its depth is bounded by the similarity candidates (`similarity_max_per_author` = 1), not by the cap. The Client's up-next over-fetch is covered by P3C2._
- **Checkpoint and seam:** rung 1 over HTTP to the real Engine from the common seam.
  - C1 compares each response row's two fields against a read-only `whitelist.db` lookup keyed by that row's `(video_id, instance_domain)`, across the four routes.
  - C2 requests 96 rows (`default_limit` 48, read from `server_config.BATCH_SIZE`) on the home and random paths, and also requests 48 as a control.
  - **Red today:** the projection omits both fields, and the handler and mixer caps return 48.
- **Probe (7.1, observed):**
  - The Engine starts in 5.5 s.
  - A 48-row home request takes 0.6 s, random 0.0 s, and search for `music` 3.3 s.
  - With the Engine unchanged, home and random at `limit=96` return 48 rows, and no row carries `channel_id` or `account_url`.
  - Search and up-next return the same page on repeated requests. Three consecutive home feeds share no rows.

**Self-check (dispatch 1)** — `tests/tmp/test_engine_row_identity.py`, with seam `tests/tmp/conftest.py`

- `C1 — test_engine_row_identity.py:53-54, each row's channel_id and account_url on home, random, up-next and search — expected: equal to whitelist.db's values for that (video_id, instance_domain) — under the projection unchanged: None (observed: None == '1951', None == '8921'); under account_url filled from channel_url: a URL of a different path.`
- `C2 — test_engine_row_identity.py:68, row count of a limit=96 home and random request — expected: > 48 — under the caps unchanged: 48 (observed); under only the handler cap raised: home still 48, because the mixer re-caps.`

Supporting (no row): line 50, rows non-empty; line 64, a limit=48 request returns exactly 48, so the pool can fill a page.

1. **Whole claim** — C1 covers both fields on all four named routes. C2 covers home and random.
2. **Absence only** — no. Every assertion compares against a positive value.
3. **Echoed literal** — no. Expected values come from `whitelist.db`, never from a response or from the test's inputs.
4. **One value** — C1 checks every row across four routes, 8 to 48 rows each, with values varying per row. C2 reads 48 as a control and 96 as the claim.
5. **The double** — none. The real Engine process runs on the real dataset.
6. **It collects** — 6 node ids.
7. **Observed** — probe `tests/tmp/probe_engine_start.py`, plus this run.
8. **Red** — exit 1, 6 failed.
9. **Right reason**
   - C1 fails at line 53, `None == '<channel_id>'`, on all four routes.
   - C2 fails at line 68, `48 > 48`.
   - The controls at lines 50 and 64 passed, so the harness is sound.
10. **Observed expected output** — yes.

**Checkpoint audit**

- **Dispatch 1**
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 53 on all four routes (channel_id None, not projected); line 68 on both paths (48, handler cap).` Recommendation: a stored NULL would equal a missing key.
  - `AUDIT: devsecops-test-claim-auditor — PASS.` Ledger: 10 rows, one UNCARRIED, D2 (the docstring's "serve twice the default page").
- **Remediation**
  - D2 justified: the docstring is narrowed to "serve more than the default page when asked for twice it", which is C2's wording.
  - Recommendation taken (both auditors):
    - Line 55 now asserts both keys are present in the row.
    - Line 54 asserts the dataset's expected values are non-null, so a missing key cannot equal a stored NULL. The Step 1 probe found no NULLs in either column.
  - Not taken, recorded:
    - The limit bounds (0, negative, malformed) are the Engine's existing parsing, which this phase does not change.
    - A request above the new ceiling is clamped; the Client never sends one.
- **Rerun:** red, 6 failed. C1 now fails at line 55 (the key is absent) on all four routes, and C2 at line 71 (48 > 48).
- **Dispatch 2**
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 55 on all four routes (fields not in STABLE_VIDEO_FIELDS); line 71 on both paths (handler clamp).`
  - `AUDIT: devsecops-test-claim-auditor — PASS.` CLAUSE MAP: 8 rows, all CARRIED. D2 is recorded as closed by narrowing the docstring.

**Changes**

- `engine/server/api/handlers/similar.py`
  - `STABLE_VIDEO_FIELDS` gains `channel_id` and `account_url`, after `instance_domain`.
  - `_handle_similar` clamps `limit` at twice `default_limit`.
- `engine/server/api/recommendations/mixer.py` — `generate_recommendations` caps `batch_size` at twice the profile's `batch_size`.
- `tests/tmp/conftest.py` (NEW) — the common seam.

**Checkpoint outcome** — PASS: `test_engine_row_identity.py` 6 passed (11.1 s).

#### Phase 2 — A profile blocks a video's channel or account

- **Kind:** code
- **Files:**
  - `client/backend/lib/users_store.py` (EDITED)
  - `client/backend/lib/blocks.py` (NEW)
  - `client/backend/lib/profiles.py` (EDITED)
  - `client/backend/server.py` (EDITED)
  - `tests/tmp/test_block_routes.py` (NEW, checkpoint)
- **Intent (post-phase state):** A profile holder who names a video by uuid and host can block that video's channel or its account, sees the block in their own list and can remove it again. A profile holds at most 1,000 blocks.
- **Clauses:**
  - `C1` — After `POST /api/profile/blocks` with `kind` channel or account and a video's `uuid` and `host`, `GET /api/profile/blocks` for that profile lists the channel `(instance_domain, channel_id)` or the `account_url` that `whitelist.db` holds for that video. After `POST /api/profile/blocks/remove` with that entry, it no longer lists it.
  - `C2` — A profile already holding 1,000 blocks has a further block refused with 400, and its list still holds 1,000.
- **Checkpoint and seam:** rung 1 over HTTP to the real Client, which is wired to the real Engine (common seam).
  - C1 takes two videos from `whitelist.db`, one pair per kind. The two videos share an account but not a channel, so the channel and account targets differ.
  - C2 seeds the first 999 blocks through `blocks.add_block` directly, because 1,000 HTTP round trips through the Engine resolve would dominate the run. It then adds the 1,000th and the 1,001st over HTTP. Seeding through the module is a supporting step; the refusal and the list are read over HTTP.
  - **Red today:** the routes answer 404.
  - _Amended at 7.1: C2 seeds its 1,000 blocks over HTTP rather than through `blocks.add_block`._ The probe measured 1,001 resolve-and-metadata round trips at 1.3 s, so seeding stays at the seam and the checkpoint imports no Phase 2 module.

**Probe (7.1, observed)** — `PROBE=resolve tests/tmp/probe_engine_start.py`

- 1,001 videos, one per distinct `(instance_domain, channel_id)`, chosen as embedded and with `error_count = 0`. All 1,001 resolve through `/internal/videos/resolve`, and `/internal/videos/metadata` returns `channel_id` and `account_url` for each. Total time 1.3 s.
- The Engine resolves only embedded videos, so the checkpoint selects videos with embeddings. A visitor trying to block from a video the Engine cannot resolve gets a 404.

**Self-check (dispatch 1)** — `tests/tmp/test_block_routes.py`

- `C1 — test_block_routes.py:68-69, the listed targets after blocking a video's channel and another video's account (same account, different channels) — expected: ("channel", host, channel_id, "") and ("account", "", "", account_url) from whitelist.db — under a target taken from the wrong field (the account URL stored for a channel block): the channel tuple is absent; under no route: 404 at line 65 (observed).`
- `C1 — test_block_routes.py:76,82, the list after each removal — expected: [account_target], then [] — under a remove that is a no-op: both entries still listed; under a remove that clears every block: [] at line 76 instead of [account_target].`
- `C2 — test_block_routes.py:100-101, the status of the 1,001st block and the list size — expected: 400, 1000 — under no cap: 201 and 1001; under a cap that is off by one below (999): the precondition at line 96 fails on the 1,000th; off by one above: 201 at line 100.`

Supporting (no row): lines 65-66 and 96, each block call returns 201; line 70, exactly two blocks listed; lines 75 and 81, removal answers 204.

1. **Whole claim** — C1 covers both kinds, their listing, and their removal. C2 covers the refusal and the list staying at 1,000.
2. **Absence only** — the empty lists at lines 76 and 82 are armed by the positive listing at lines 68-69, and line 76 also requires the account block to survive.
3. **Echoed literal** — no. The test sends only `uuid` and `host`; the expected `channel_id` and `account_url` come from `whitelist.db`, and the server must derive them.
4. **One value** — two kinds with differing targets; C2 reads 1,000 accepted against the 1,001st refused.
5. **The double** — none. The real Client runs against the real Engine.
6. **It collects** — 2 node ids.
7. **Observed** — the resolve probe above.
8. **Red** — exit 1, 2 failed.
9. **Right reason** — both fail on the first block call. Line 65 gets `404 == 201`, and line 96 gets `{'error': 'Not found'}`, the Client's unknown-route response. The Engine's unresolvable-video 404 would read `"Video not found in Engine"`. The probe shows every chosen video resolves, so the red is the missing route.
10. **Observed expected output** — yes.

**Checkpoint audit**

- **Dispatch 1**
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 65 and line 96, 404 {"error": "Not found"}; no /api/profile/blocks route.`
  - `AUDIT: devsecops-test-claim-auditor — PASS.` Ledger: 17 rows, all CARRIED.
- **Recommendations taken**
  - The refused 1,001st block must not be stored: lines 106-107 check that the list is unchanged and that the 1,001st channel is absent. This excludes an insert-then-trim, the shape `record_like` uses.
  - A second profile's list is empty (line 71).
- **Recommendations not taken, recorded**
  - The 401 on the block routes is checked at Step 8. The routes use `_require_profile`, which `tests/active/test_profiles.py` covers.
  - Malformed bodies, an unresolvable video, and removing a block the profile does not hold: the routes validate `kind`, `uuid` and `host` at the boundary, and none of these is a phase clause.
- **Rerun:** red at lines 65 and 96, the same reason.
- **Dispatch 2**
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: lines 65 and 97 (404 != 201).`
  - `AUDIT: devsecops-test-claim-auditor — PASS.` CLAUSE MAP: 19 rows, all CARRIED.

**Changes**

- `client/backend/lib/blocks.py` (NEW)
  - `MAX_BLOCKS` = 1000, `KINDS`, `BlockLimitReached`.
  - `block_target` derives the target and its label from an Engine metadata row.
  - `add_block` is idempotent for an existing target and refuses a new one at the cap, in one transaction.
  - `remove_block`, and `list_blocks` (newest first).
- `client/backend/lib/users_store.py` — `ensure_user_schema` creates `blocks`. The key columns use empty strings rather than NULL, and `kind` has a CHECK constraint.
- `client/backend/lib/profiles.py` — `delete_profile` also deletes the profile's `blocks`.
- `client/backend/server.py`
  - `GET /api/profile/blocks`, `POST /api/profile/blocks` and `POST /api/profile/blocks/remove`, each rate-limited and behind `_require_profile`.
  - `_read_block_body` validates `kind`.
  - `_handle_block_add` validates `uuid` and `host` (non-empty, at most 200 characters), then resolves through `resolve_video_seed` and `fetch_metadata_for_entries`. It answers 404 when the Engine has no such video, 502 on an Engine failure, and 400 at the cap.

**Checkpoint outcome** — PASS: `test_block_routes.py` 2 passed (13.2 s).

#### Phase 3 — Feeds and search are filtered per profile

- **Kind:** code
- **Files:**
  - `client/backend/server.py` (EDITED)
  - `client/backend/lib/blocks.py` (EDITED)
  - `tests/tmp/test_block_filtering.py` (NEW, checkpoint)
- **Intent (post-phase state):** A visitor presenting a profile key receives feeds and search results without the videos of the channels and accounts that profile blocked. Their feed pages stay full while other visitors' results are unchanged.
- **Clauses:**
  - `C1` — Rows of a blocked channel and a blocked account are absent from that profile's up-next and search responses through the Client, while a keyless request and a second profile's request for the same page still contain them.
  - `C2` — A Client up-next response (`/recommendations` and `/videos/similar` with a seed) for a profile whose blocks remove rows from the Engine's page returns the requested number of rows, none from a blocked target.
  - _Amended at 7.1 with operator approval: home and random were removed from C2._ The Engine draws a fresh random page on every request, so a blocked target cannot be chosen that the page would otherwise have held. Against today's Client, a home or random page is already 48 rows without the blocked channels, so that half of the claim was green before the build. Home and random with blocks are checked live at Step 8, and listed under acceptance criteria without a clause.
- **Checkpoint and seam:** rung 1 over HTTP to the real Client and Engine.
  - C1 uses up-next (a fixed seed) and search (a fixed query), both of which return the same page for the same request. It blocks targets taken from a keyless response and keeps that keyless response as the positive control. How deterministic these two routes are is confirmed by a probe at 7.1.
  - C2 blocks the channels of rows the Engine returns. For up-next it asks for 8 rows and blocks three of the eight channels. On home and random the draw varies per request, so C2 asserts the page count and that no blocked target appears. Whether home offers a stable subset worth blocking is settled by the 7.1 probe.
  - **Red today:** the proxy passes rows through unfiltered, and caps pages at the Engine's 48.

**Self-check (dispatch 1)** — `tests/tmp/test_block_filtering.py`

- `C1 — test_block_filtering.py:74-76, the blocked channel in the blocker's up-next and the blocked account in its search — expected: absent — under no filtering: present (observed, line 74: not True); under a filter that matches channels only: the account is still in search at line 75.`
- `C1 — test_block_filtering.py:78-81, the same targets in keyless and second-profile responses — expected: present — under a filter applied to every caller, or keyed to the last profile that blocked: absent for the bystander at lines 80-81. The bystander holds a block of its own, so its request takes the filtering path.`
- `C2 — test_block_filtering.py:105, the row count of an up-next page of 8 after blocking 3 of its channels, on /recommendations and /videos/similar — expected: 8 — under filtering with no over-fetch: 5.`
- `C2 — test_block_filtering.py:106, blocked channels in that page — expected: none — under no filtering: all three present (observed).`

Supporting (no row):
- Line 73: the blocker still gets results, so an empty response cannot pass line 74.
- Line 93: the keyless page is full.
- `_deep_seed`: the pool holds at least 11 rows, so a correct over-fetch can refill the page.
- Lines 62-64: the bystander's block shares neither a channel nor an account with the blocker's targets.

1. **Whole claim** — C1: the channel on up-next, the account on search, the keyless request, and the second profile. C2: the count and the absence of blocked targets, on both seeded routes.
2. **Absence only** — the absence checks at lines 74-76 are armed by line 73 (non-empty results) and by lines 78-79 (the same page still holds the target for others). Line 106 is armed by line 105 (8 rows) and by line 93.
3. **Echoed literal** — no. Blocked targets are taken from Engine responses, and the Client must derive each target from a uuid and host.
4. **One value** — blocker against keyless against bystander on the same page; two block kinds; two routes.
5. **The double** — none.
6. **It collects** — 3 node ids.
7. **Observed** — the 7.1 probe established that up-next and search are deterministic. This run shows the keyless controls hold.
8. **Red** — exit 1, 3 failed.
9. **Right reason**
   - C1 fails at line 74: the blocked channel is present in the blocker's up-next, because nothing filters.
   - C2 fails at line 106: all three blocked channels are present.
   - The controls at lines 73 and 93 passed. The count at line 105 passes today only because nothing is removed.
10. **Observed expected output** — yes.

**Checkpoint audit**

- **Dispatch 1**
  - `AUDIT: devsecops-test-shape-auditor — BLOCK: single-value-pin, line 55. The account target was not required to differ from the channel target's account, so a filter that ignores channel blocks could pass line 74 through the account block.`
  - `AUDIT: devsecops-test-claim-auditor — BLOCK.`
    - (1) Whole claim: the channel was never shown on the search page, nor the account on the up-next page, so C1b and C1c were UNCARRIED.
    - (2) C1's keyless and second-profile half was asserted only on `/recommendations`, not on `/videos/similar` (C1g UNCARRIED).
    - The frozen ledger holds UNCARRIED rows C1b, C1c, C1g, D1, D4 and N1.
- **Remediation**
  - C1 is rewritten as one test parametrized over the three surfaces: `/recommendations` up-next, `/videos/similar` up-next, and search. Each surface takes both targets from its own keyless page, and `_distinct` requires them to share no channel and no account. The bystander's block is distinct from both. This fixes C1b, C1c, C1g, D1, N1 and the shape Critical.
  - `_deep_seed` checks the pool on the route under test. This fixes D4.
  - The module docstring now names both seeded routes.
  - Recommendations not taken, recorded:
    - A bad key on the filtered routes is P4C2's clause, and is exercised there through the Client.
    - `limit=1`, and a pool exhausted by blocks: B4 accepts a short page, and no clause claims more.

**Self-check (dispatch 2)**

- `C1 — test_block_filtering.py:87-88, the blocked channel and the blocked account in the blocker's page, on /recommendations, /videos/similar and search — expected: absent — under no filtering: present (observed at line 87 on all three surfaces); under a filter that matches only one kind: the other kind's target is present at line 87 or 88. Both targets come from that page and share no channel or account.`
- `C1 — test_block_filtering.py:90-91, both targets in the keyless and second-profile pages on each surface — expected: (True, True) — under a filter applied to every caller or keyed to the wrong profile: (False, False).`
- `C2 — test_block_filtering.py:115-116 — as dispatch 1, lines renumbered. Observed red at line 116 on both routes.`

Supporting (no row): line 86, the blocker still gets results; line 106, the keyless page is full; `_deep_seed` on the route under test; `_distinct`.

Answers 1-10 as dispatch 1, with these changes:
1. **Whole claim** — each target is now shown present on every surface where its absence is asserted.
2. **Absence only** — lines 87-88 are armed by lines 86 and 90.

**Red** — exit 1, 5 failed. C1 fails at line 87 on `/recommendations`, `/videos/similar` and search. C2 fails at line 116 on both routes.

- **Dispatch 2**
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 87 on every surface (Client relays the Engine page unchanged); line 116 on both routes, with line 115 passing because nothing is removed.`
  - `AUDIT: devsecops-test-claim-auditor — PASS.` Frozen ledger rows C1b, C1c, C1g, D1, D4 and N1 are all CARRIED.
  - Observation, not blocking: an account block implemented as a block on the originating video's channel would pass line 88 whenever the account has one channel on the page. P2C1 excludes that implementation, because it asserts that the stored account target is `account_url`.

**Changes**

- `client/backend/lib/blocks.py`
  - `load_block_keys` returns the profile's blocked `(instance_domain, channel_id)` pairs and `account_url`s.
  - `filter_blocked` drops the rows matching either.
- `client/backend/server.py`
  - **Constants.**
    - `FEED_PAGE_SIZE` = 48, with a `rat-tail:` comment naming the Engine's `batch_size` it mirrors.
    - `FEED_OVERFETCH_FACTOR` = 2, and the `FEED_ROUTES` and `FILTERED_ROUTES` sets.
  - **`_block_filter`**, called by both read-proxy handlers before the Engine call:
    - It caps a feed `limit` at 48 for every caller, and treats an absent `limit` as 48.
    - With no key, or on a route that is not filtered, the request passes through.
    - A presented key that does not resolve gets the fixed 401 through `_require_profile`.
    - A profile with no blocks passes through.
    - Otherwise it returns the key sets and, for feeds, doubles `limit`.
  - **`_proxy_engine_request`** takes `block_keys` and `page_size`. On an Engine 200 with blocks it passes the body through `_filter_payload`, which filters, cuts feeds to the page size and rewrites `count`. A body that is not a JSON page of row objects gets a 502 `ENGINE_PROXY_INVALID` and is never passed through.

**Checkpoint outcome** — PASS: `test_block_filtering.py` 5 passed (12.5 s). Phase 1-3 checkpoints together: 13 passed. The active suite: 10 passed (`test_profiles.py`, `test_frontend_profile.py`, re-run because `server.py`, `profiles.py` and `users_store.py` changed).

#### Phase 4 — The frontend sends the key and surfaces its rejection

- **Kind:** code
- **Files:**
  - `client/frontend/src/data/profile.ts` (EDITED)
  - `client/frontend/src/data/videos.ts` (EDITED)
  - `client/frontend/src/data/search.ts` (EDITED)
  - `client/frontend/src/data/blocks.ts` (NEW)
  - `client/frontend/src/types/videos.ts` (EDITED)
  - `client/frontend/src/pages/videos/index.ts` (EDITED)
  - `client/frontend/src/pages/video-page/index.ts` (EDITED)
  - `client/frontend/src/pages/search/index.ts` (EDITED)
  - `client/frontend/video-page.html` (EDITED)
  - `client/frontend/src/video.css` (EDITED)
  - `client/frontend/dist/` (rebuilt)
  - `tests/tmp/test_block_frontend.py` (NEW, checkpoint)
- **Intent (post-phase state):** In a browser holding a profile key, blocking through the frontend's block module removes that target from the feeds and search results the frontend fetches. A key the server no longer accepts reaches the page as a key-rejected error rather than a generic failure.
- **Clauses:**
  - `C1` — After `blockVideoSource` for a video's channel, the rows returned by `fetchSimilarVideosPayload` (up next) and `fetchSearchResults` omit that channel, where the same calls before the block included it.
  - `C2` — With a stored key the server does not accept, `fetchSimilarVideosPayload` and `fetchSearchResults` throw `ProfileKeyRejectedError`.
- **Checkpoint and seam:** rung 2, the Phase 4 harness of plan 06 (`tests/active/test_frontend_profile.py`).
  - The data modules are bundled with the installed `esbuild` and run in node against the real Client and Engine.
  - `window` and `localStorage` are the in-memory browser-platform stand-ins that harness already uses.
  - C2 also exercises the Client's 401 on the feed and search routes (B9): if the Client passed a bad key through, the Engine would answer 200 and no error would be thrown.
  - **Red today:** `blocks.ts` does not exist, and the fetches send no key.
  - The page wiring is outside this checkpoint (see below).

**Scaffolding (7.1)**

- `client/frontend/src/data/blocks.ts` exports `listBlocks`, `blockVideoSource` and `unblock`, each throwing `Error("not implemented")`, plus the `Block` and `BlockKind` types.
- `client/frontend/src/data/profile.ts` gains `export class ProfileKeyRejectedError extends Error {}`, so the checkpoint can name it and the red is behaviour, not a missing symbol.

**Self-check (dispatch 1)** — `tests/tmp/test_block_frontend.py`

- `C1 — test_block_frontend.py:109-110, a channel from the up-next page and a channel from the search page, after blockVideoSource for each — expected: absent from the rows fetchSimilarVideosPayload and fetchSearchResults return — under fetches that send no key: present (the Client passes keyless reads through); under a search that serves its two-minute sessionStorage cache: present, because the pre-block page is cached; under the scaffolding: node exits at the block step, "not implemented" (observed).`
- `C2 — test_block_frontend.py:138-139, the outcome of both fetches with a well-formed key that was never issued — expected: ProfileKeyRejectedError — under fetches that send no key: the rows come back (observed: {'ok': [...]} at line 138); under a fetch that throws a generic Error on 401: rejected is false.`

Supporting (no row):
- Lines 105-106: each target is on its page before the block.
- Line 108: the pages still have rows after the block.
- Line 135: with an issued key both fetches succeed, so the refusal at lines 138-139 is about the key.

1. **Whole claim** — C1 covers both fetches, each with before and after. C2 covers both fetches.
2. **Absence only** — the absences at lines 109-110 are armed by lines 105-106 and 108.
3. **Echoed literal** — no. The targets come from keyless Client responses, and the rows under test come from the bundled modules.
4. **One value** — before against after for the same call. C2 compares an issued key against an unknown key.
5. **The double** — `window`, `localStorage` and `sessionStorage` are in-memory browser-platform stand-ins. The modules under test are the real ones, bundled by the installed esbuild, running against the real Client and Engine.
6. **It collects** — 2 node ids.
7. **Observed** — C2's control and its red were observed in this run. C1's premise, that the targets are on the pages before the block, rests on the P3 probe (up-next and search are deterministic) and on `_seed_and_targets` reading the same pages keyless.
8. **Red** — exit 1, 2 failed.
9. **Right reason**
   - C1: node exits at the block step with `Error: not implemented`, thrown by the scaffolding's `blockVideoSource` (line 85, `returncode` 1).
   - C2: line 138, the up-next fetch returned rows for a key the server does not know. The fetch sent no key, so the Client passed it through.
   - The harness works: the bundle builds, node runs, `createProfile` succeeds, and line 135's control passes.
10. **Observed expected output** — yes.

**Checkpoint audit**

- **Dispatch 1**
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 85 (node exits on blockVideoSource's "not implemented"); line 138 after the line 135 control passes (no key sent, rows returned).`
  - `AUDIT: devsecops-test-claim-auditor — PASS.` CLAUSE MAP: 16 rows, all CARRIED.
- **Recommendations not taken, recorded**
  - Running the keyless path through the modules: covered by the unchanged keyless branch, the split smoke, and a Step 8 live request.
  - `blockVideoSource` failure paths, and asserting the `Block` it returns: no clause claims them. The page shows the server's error message.

**Changes**

- `client/frontend/src/data/profile.ts` — `ProfileKeyRejectedError` and `forgetProfileKey`.
- `client/frontend/src/data/blocks.ts` (NEW) — `listBlocks`, `blockVideoSource`, `unblock`, and the `Block` type. Each sends the key header and throws the server's error message.
- `client/frontend/src/data/videos.ts` — `fetchSimilarVideosPayload` sends `profileHeaders()`, and a 401 throws `ProfileKeyRejectedError`.
- `client/frontend/src/data/search.ts` — with a key stored, `fetchSearchResults` fetches directly with the header and `cache: "no-store"`, skipping the `sessionStorage` cache. A 401 throws `ProfileKeyRejectedError`, and a 503 still throws `SearchUnavailableError`. The keyless path is unchanged.
- `client/frontend/src/components/key-rejected.ts` (NEW, **inventory gap**: not in the Phase 4 files list) — `keyRejectedNotice`, the shared "no longer valid" notice with a "Forget key" button. It is used by three pages, so it lives in one place.
- `client/frontend/src/pages/videos/index.ts`
  - The feed shows `keyRejectedNotice` on `ProfileKeyRejectedError`, and reloads after the key is forgotten.
  - The profile section with a key renders a "Blocked" list through `renderBlocks`: each block's kind and label, set with `textContent`, and an Unblock button.
  - The no-profile text says a profile is needed to block channels and accounts.
- `client/frontend/src/pages/video-page/index.ts`, `client/frontend/video-page.html`
  - "Block channel" and "Block account" buttons plus a status line under the channel row.
  - `enableBlockButtons` enables the buttons once the uuid and host are known, taken from `/api/video`'s `videoUuid` or the page's `id`/`host`. Without a key, a click shows the profile prompt.
  - Up next shows `keyRejectedNotice`.
- `client/frontend/src/pages/search/index.ts` — shows `keyRejectedNotice` on `ProfileKeyRejectedError`.
- `client/frontend/src/video.css`, `client/frontend/src/videos.css` (the latter an **inventory gap**) — `.block-actions`, `.block-status`, `.key-rejected`, `.profile-blocks`, `.profile-block-list`.
- `client/frontend/src/types/videos.ts` — **no change**. `VideoRow` already declares `channel_id` and `account_url`, so E17 was not borne out.
- `client/frontend/dist/` — rebuilt by `npm run build`, not rsynced.
- `tsc --noEmit`: 41 lines, against 40 recorded in plan 06. The one new line is `pages/videos/index.ts:207`, `'cards' is possibly 'null'`, the same pre-existing pattern as line 203 beside it, where the error branch was split in two. Nothing else is in the new modules or the new code.
- `tests/check-frontend-client-gateway.sh` and `tests/check-client-engine-boundary.sh`: both PASS.

**Checkpoint outcome** — PASS: `test_block_frontend.py` 2 passed (10.7 s).

#### Acceptance criteria without a clause

- **B6** (blocks survive dataset rebuilds) — structural: `users.db` is a Client file that no dataset job opens. It is checked at Step 8 against `tests/check-client-engine-boundary.sh`, which forbids the reverse coupling.
- **B8's keyless half, and the keyless `limit` cap of 48** — checked at Step 8 by one keyless request with `limit=96` against the live Client, which must return 48 rows. `tests/run-arch-split-smoke.sh` then confirms keyless feeds still work.
- **B4 on home and random** (a full page for a profile with blocks) — checked at Step 8 with a live request. A profile with blocks must get a 48-row home page and a 48-row random page with no blocked target. Removed from P3C2 at 7.1.
- **B10** (deleting a profile deletes its blocks) — checked at Step 8 by one request pair against the live Client, then a read of `users.db`.
- **The 401 on the block routes** — these reuse `_require_profile`, which `tests/active/test_profiles.py` covers for the other profile routes. They are checked at Step 8 with one keyless request each.
- **B11 and the page halves of B8 and B9** — the video page's Block channel and Block account buttons, the no-profile prompt, the modal's blocks list with Unblock, and the "Forget key" control on the feed, search and video pages. These are verified by the operator in a browser after `npm run build`, from a recipe handed over at Phase 4.

#### Coordination

- **Phases 1-4:** the checkpoints start the Engine from the repo's pixi env (`engine/.pixi/envs/default`) against the repo's dataset. Up-next requests can write to the live `similarity-cache.db`, which is a cache, the same way the split smoke does.
- **After Phase 3:** restart the live Engine and Client (both change), then run `tests/run-arch-split-smoke.sh` through the Engine's pixi env, as plan 06 did.
- **After Phase 4:** `npm run build` in `client/frontend`, then the operator's browser check.

#### Rationale

- Four phases, two clauses each, one Intent each.
- The split follows the path a block travels:
  1. The Engine exposes the identity a block matches on, and the depth an over-fetch needs.
  2. A profile records blocks.
  3. The Client applies them.
  4. The browser carries the key and reacts to its refusal.
- Phases 1-3 share one real-service seam. Phase 4 reuses plan 06's frontend harness against it.
- Five acceptance items carry no clause and are verified outside a checkpoint, as listed above.

## Inner unit tests

None. Every phase's behaviour was expressible at its checkpoint.

## Close

### Refactors

None made.
- `FEED_PAGE_SIZE` in `client/backend/server.py` duplicates the Engine's home `batch_size`. It stays, marked `rat-tail:`, because reading it from the Engine would need a new contract (R1).
- `.key-rejected` is declared in both `video.css` and `videos.css`. The video page loads only `video.css`, so the duplicate is needed.
- Nothing needed new behaviour.

### Clause accounting

- `P1C1`, `P1C2` — carried, dispatch 2 of `test_engine_row_identity.py` (both PASS).
- `P2C1`, `P2C2` — carried, dispatch 2 of `test_block_routes.py` (both PASS).
- `P3C1`, `P3C2` — carried, dispatch 2 of `test_block_filtering.py` (both PASS).
- `P4C1`, `P4C2` — carried, dispatch 1 of `test_block_frontend.py` (both PASS).

### Acceptance items without a clause (checked at Step 8)

`tests/tmp/probe_step8_checks.py` ran against the checkpoint seam (a real Engine and Client, not the live services):
- **Keyless `limit` cap:** keyless `limit=96` on home and random returned 48 rows each.
- **B4, home and random:** a profile with 15 channel blocks (10 from a home page, 5 from search) and one account block got 48 rows on three home and three random requests, with 0 blocked channels and no blocked account.
- **401 on the block routes:** `GET /api/profile/blocks`, `POST /api/profile/blocks` and `POST /api/profile/blocks/remove` all return 401 with no key and with an unknown key.
- **Validation:** `kind` "video" → 400; empty `uuid` → 400; an unknown video → 404.
- **B10:** `POST /api/profile/delete` → 204, and the `blocks` rows go from 15 to 0.
- **B6:** `tests/check-client-engine-boundary.sh` PASS. No Engine or dataset job opens `users.db`.
- **Split smoke:** `tests/run-arch-split-smoke.sh` on ports 7182/7282, run through the Engine's pixi env: all 21 checks passed. As in plan 06, the smoke's test Like remains in the live Engine database.
- **B11 and the page halves of B8/B9:** not verified here, because no browser is available. They are handed to the operator.

### Suite

- `--compare`: the active suite is green. `test_db.py` 2 and `test_profiles.py` 8 passed on their earlier fingerprints in this build; `test_frontend_profile.py` re-ran with 2 passed. "Nothing moved against the previous record."
- Phase checkpoints together: 15 passed.
- Baseline was 12 passed; it is still 12 passed.

### Operator verification

The operator restarted the live Engine and Client with `scripts/run-services.sh restart`, deployed the rebuilt `dist/`, and reported "done, and all looked good". That closes the browser check of B11 and the page halves of B8 and B9.

### Harvest (Step 10)

- **Record:** `docs/project/plans/harvest-07-channel-blocks-plan.md`.
- **Moved:** all 8 checkpoint tests, into `tests/active/test_similar.py`, `test_blocks.py` and `test_frontend_blocks.py`, with the real-Engine fixtures added to `tests/active/conftest.py`.
- **Mutations:** each one felled its assertion.
- **Disposed:** `tests/tmp` went to `delete_me/plan07-tmp/`.
- **Suite:** 27 passed, and `--audit-map` exits 0.
- **Harvest fix:** the `engine` fixture now retries a start that exits on the `random-cache.db` lock. Concurrent Engine starts race on that file.

### Documentation (Step 9)

- `DEPLOYMENT.md` — **updated.**
  - The profile-routes sentence names `/api/profile/blocks*`.
  - A new paragraph covers the 1,000 cap, storage in `users.db`, per-profile filtering of feed and search, the over-fetch, the 401 on a bad key, and the 48/96 limits.
  - The boundary-contract list at line 259 omits the proxied public read routes. That omission predates this build and is left as found.
- `client/README.md` — **updated.** It adds the three block routes and notes that deletion covers blocks, adds the block routes to the 401 sentence, adds a per-profile filtering bullet, and adds `/api/v1/search/videos` to the read gateway list.
- `README.md` — **updated.** The boundary table's write/profile row names `/api/profile*` including blocks. The read-gateway row adds search and notes the filtering.
- `CONTEXT.md` — **written.** It was empty; it now defines Profile and Block.
- `engine/server/api/recommendations/docs/LAYER_PARAMS.md` — **updated.** `batch_size` is the default response size, and a request `limit` is honoured up to twice it.
- `docs/wiki/`, `docs/project/adr/` — do not exist; nothing to check.
- `engine/server/README.md`, `client/frontend/README.md` — **no update needed.** They list routes without their fields or filtering, and nothing they state became false.

## Close
