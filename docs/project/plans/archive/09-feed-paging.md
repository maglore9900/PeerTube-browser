# Feed paging

Status: delivered and harvested (`docs/project/plans/harvest-09-feed-paging-plan.md`); the operator confirmed the videos page wiring in the browser ("it works"). Split out of `docs/project/plans/04-feed-parameter-panel.md` item I6 (capability C3) at Step 1.

## Requirements

Confirmed by the operator at Step 1 ("confirm").

### What was asked

Build plan 04 (`docs/project/plans/04-feed-parameter-panel.md`). At Step 1 the operator chose its feed-paging slice (I6, O2) as this build, and exclusion by a list of shown rows sent to the Engine (O6) over client-side dedupe only (O5) or seeded deterministic paging (O7).

### Purpose

Scrolling the videos page keeps loading videos past the first 48-row batch without repeating rows already shown.

### Current state (read at Step 1)

- `client/frontend/src/pages/videos/index.ts` fetches one batch (`fetchVideosPayload`), reveals it `CHUNK_SIZE` = 6 rows at a time at the `#feed-sentinel` observer and a scroll fallback (`loadNextChunk`), and never refetches: scrolling stops when the batch is exhausted.
- The Client backend caps a feed page at `FEED_PAGE_SIZE` = 48 (`client/backend/server.py`) and rejects any body key outside `PROXY_ALLOWED_BODY_KEYS` (`likes`, `user_id`, `mode`).
- The home feed is not an ordered list: every layer in `RECOMMENDATION_PIPELINE["profiles"]["home"]` (`engine/server/api/server_config.py`) is a shuffled sample from a large pool, and the mixer (`engine/server/api/recommendations/mixer.py`) already skips any candidate whose `like_key` (`video_id::instance_domain`) is in `seen_keys`. An offset has nothing stable to page through, which is why O7 was rejected.
- The Engine refuses a POST body over `DEFAULT_CLIENT_LIKES_BODY_LIMIT` = 65536 bytes.

### Requirements

- **R1.** Scope is the videos page, `client/frontend/src/pages/videos/index.ts`, in all three of its modes: recommendations (home), random (`?mode=random`) and similar (`?id=`).
- **R2.** When the revealed rows reach the end of the fetched batch and the scroll sentinel is reached, the page fetches another batch and appends it.
- **R3.** Every refetch carries `exclude` in the POST body: the identities (`video_id` + `instance_domain`, the key rows already carry) of rows shown in this page view, capped at the most recent 500.
- **R4.** The Client backend allowlists `exclude` on `/recommendations` and `/videos/similar`, validates its shape, rejects more than 500 entries with 400, and forwards it to the Engine, including when a profile key replaces the body's likes.
- **R5.** The Engine accepts `exclude` on the same routes and rejects more than 500 entries with 400, as it rejects too many likes. No returned row matches an excluded identity, on the home and up-next paths, and the page backfills from the rest of the pool. (Amended at Step 5, operator "drop": the random path has no Engine-side filter. A 500-entry exclude collides with a 48-row draw from the 500,000-row random cache about 0.05 times per page, and R6 drops any repeat.)
- **R6.** The frontend drops any returned row it has already shown in this page view. This covers rows older than the 500 cap and rows the Engine could not replace.
- **R7.** A refetch that adds no new row ends paging for that page view.
- **R8.** The shown set lives only in memory: a reload or a mode switch starts fresh.
- **R9.** With no `exclude`, every route behaves exactly as today.

### Acceptance criteria

1. Scrolling past the first response loads further rows without repeating rows already shown (plan 04 criterion 8).
2. The gateway accepts `exclude` on both feed routes and still rejects an unlisted body key (plan 04 criterion 9, paging half).
3. An `exclude` of more than 500 entries is rejected with 400 by the Client backend and by the Engine.
4. A feed request without `exclude` returns what it returns today.

### Out of scope

- Plan 04 items I1-I5 and I7: language capture and filtering, saved channels, the parameter panel. They stay in plan 04.
- Video-page up-next paging (`docs/project/issues/12-similars-on-scroll.md`).
- Search paging.
- A seed or offset on the Engine (O7).
- Persisting the shown set across reloads.

### Consistency constraints

- New code matches existing style: backend `client/backend` (stdlib `http.server`, `respond_json`, module docstrings), Engine `engine/server/api` handler and recommendations style, frontend `data/*.ts` and the page module's style. Every rendered value stays escaped.
- `exclude` is validated at both boundaries it crosses (Client from the browser, Engine from the Client), like `likes`.
- Backwards compatibility is not required.
- Issue 17 (feed modes) and plan 04 require one feed-parameter mechanism: `exclude` is a body field beside `likes`, validated on the same path.

### Conflicts

- **Plan 04 R3 ("require a seed") against the tree.** The home feed is a fresh stochastic mix per request, so a seed would mean seeding every generator and the random cache. Resolved by the operator choosing O6.
- **Plan 03's recorded preference against sending per-request client data, against O6.** The operator chose O6 knowing the browser request grows by up to 500 identities.

### Test trees for this build

- `active`: `tests/active`
- `working`: `tests/tmp`

### Baseline suite state

Step 0, `scripts/validate_tests.py` bare run: "unchanged since 2026-09-26T11:37:25-04:00 — every fingerprint still holds", 58 passed (29.2 s). Reused from the banked record `tests/last_test_validation.json`. Green.

## High-level plan

### Approach

- **A1. Frontend paging (R1, R2, R6, R7, R8).** The videos page keeps a set of identities it has shown in this page view (in memory only, R8). When `loadNextChunk` finds the batch exhausted at the sentinel or the scroll fallback, the page fetches another batch through the same `fetchVideosPayload` path for its mode, passing the most recent 500 shown identities as `exclude` (R3). It drops any returned row already in the shown set (R6), appends the rest to the sample and reveals them in the usual chunks. A refetch that adds no new row sets a flag that ends paging for the page view (R7). One refetch is in flight at a time. `data/videos.ts` `fetchSimilarVideosPayload` gains an optional `exclude` it puts in the body beside `likes`.
- **A2. Client gateway (R4).** `exclude` joins `PROXY_ALLOWED_BODY_KEYS` for `/recommendations` and `/videos/similar`. The proxy validates it as the likes are validated: a list of objects with non-empty string `id` and `host`, at most 500, with 400 over the cap. The profile branch replaces only `likes` and adds centroids, so `exclude` passes through to the Engine in both the keyed and the keyless case.
- **A3. Engine exclusion (R5, R9).** `_handle_similar_request` parses `exclude` beside the likes, rejects more than 500 with 400 in the same shape as the too-many-likes error, and stores the identities in the request context beside the dislike centroids, as `video_id::instance_domain` keys (the `like_key` format). The context is cleared per request, as it is today. Consumers:
  - **Home** (amended at Step 4, RC1, operator-approved): when the excluded set is non-empty, the mixer gathers `min(len(excluded), batch_size)` extra candidates, spread by `gather_ratio`, and drops excluded candidates from each layer before mixing, so the schedule and its fallback fill the page from the rest.
  - **Up-next** (`_handle_seed_with_embedding`): excluded rows are removed before `rows[:limit]`, so the ranked pool behind the page backfills.
  - **Random** (`_handle_random`, and the home fallback to random): excluded rows are removed from the drawn rows.
  With no `exclude`, the set is empty and every path runs as today (R9).
- **A4. Body limit.** 500 identities of about 80 bytes each come to about 40 KB. Added to a keyed profile's centroids (four 384-float vectors rounded to 6 places, about 17 KB) and its likes, the Client-to-Engine body gets close to `DEFAULT_CLIENT_LIKES_BODY_LIMIT` (65,536 bytes), and a long host name could tip it over. The Engine limit is raised to 131,072 bytes. The Engine is loopback-bound and fed only by the Client, which already caps a proxied body at 1 MB.

### Alternatives

- **O5, client-side dedupe only.** Rejected by the operator: like-based layers (about half of home) repeat on every refetch and would be dropped, so later pages come back short.
- **O7, seed and offset.** Rejected: the home feed is a fresh stochastic mix per request. Pageable offsets would need every generator and the random cache seeded, and pages 0..N regenerated on each request.
- **Filtering excluded rows after the mixer instead of seeding `seen_keys`.** Rejected for home: rows filtered after mixing are not replaced, so pages shrink. Seeding `seen_keys` reuses the backfill the mixer already does for likes.
- **Filtering `exclude` in the Client proxy instead of the Engine.** Rejected: the Client only sees the finished page, so it cannot backfill. It would be O5 with extra hops.
- **A compact string encoding for `exclude` (`"id::host"`) to stay under 64 KB.** Rejected: it adds a second identity shape beside the `{uuid, host}` objects `likes` uses. Raising a limit on a loopback hop is cheaper.

### Risks

- **K1. Short pages on shallow pools.** Up-next pools are about 15-19 deep, and the like-seeded home layers draw from similarity to 5 random likes. After a few pages, those layers run dry and pages fill from popular, random and fresh, or come back short. That is the intended degradation; R7 stops paging only when a refetch adds nothing.
- **K2. Request growth.** Each refetch sends up to 40 KB more from the browser. The operator accepted this with O6, against plan 03's preference.
- **K3. Rate limit.** Refetches count against the Engine's 60/min per-address limit and the Client's limiter. At one refetch per 48 rows, normal scrolling stays far under it. R7 and the single in-flight request keep a stuck page from looping.
- **K4. Rows older than the cap can repeat from the Engine.** The frontend drops them (R6), so they never render, but they cost page slots.
- **K5. The exclude list reveals browsing within a page view to the Client and the Engine.** It is the same information the requests already carried, from the same page view, and nothing stores it.

### Tradeoffs accepted

- **T1.** The browser request grows by up to 500 identities (O6).
- **T2.** Paging quality degrades to popular, random and fresh once personalised pools are exhausted (K1).
- **T3.** The Engine body limit doubles to 131,072 bytes (A4).

## Impacts

### E1 Videos page paging
- **path:** `client/frontend/src/pages/videos/index.ts`
- **Changes:** `state` gains the shown-identity set, an in-flight flag and an exhausted flag. `loadNextChunk` (called by the `#feed-sentinel` observer, `maybeLoadOnScroll` and `maybeFillViewport`) triggers a refetch when the sample is exhausted. A new refetch function calls `fetchVideosPayload` with `exclude`, drops rows already shown, appends the rest to `state.rows` and `state.sample`, and renders them through `renderCards`. `loadVideos` (initial load, reset-profile reload, key-rejected retry) resets the shown set and both flags. `pickSample` shuffles only the first batch in random mode; appended rows are not reshuffled.
- **Depends on it:** nothing imports it. It is the page entry for `client/frontend/videos.html` and `index.html`.
- **Regression risk:** medium. A refetch loop would burn the rate limit (K3), and a render path that appends twice would duplicate cards. `renderCards` appends by comparing the rendered card count with `visibleCount`, which stays correct as long as rows are only appended to the sample.

### E2 Feed fetch helper
- **path:** `client/frontend/src/data/videos.ts`
- **Changes:** `fetchSimilarVideosPayload(query)` gains an optional second argument, the exclude list, written into the POST body as `exclude` beside `likes` (or alone, with a key). `SimilarQuery` stays URL-shaped.
- **Depends on it:** `pages/videos/index.ts` (E1), `pages/video-page/index.ts:248` (up-next strip, E3), and `tests/active/test_frontend_blocks.py`, which bundles it and calls it with one argument.
- **Regression risk:** low. The argument is optional, and without it the body is exactly today's.

### E3 Video page up-next caller
- **path:** `client/frontend/src/pages/video-page/index.ts`
- **Changes:** none. It calls `fetchSimilarVideosPayload` with one argument (line 248); issue 12 owns paging there.
- **Depends on it:** —
- **Regression risk:** none if E2's argument stays optional.

### E4 Client gateway body allowlist
- **path:** `client/backend/server.py` (`PROXY_ALLOWED_BODY_KEYS`)
- **Changes:** `exclude` is added to the `/recommendations` and `/videos/similar` sets. A new constant for the 500 cap sits beside `MAX_CLIENT_LIKES` and `ENGINE_FEED_LIKES_MAX`.
- **Depends on it:** every browser feed request, and `tests/check-frontend-client-gateway.sh`, `tests/active/test_blocks.py`, `test_dislikes.py` and `test_profiles.py`, which drive the proxy.
- **Regression risk:** low. Unlisted keys are still refused.

### E5 Client proxy exclude validation
- **path:** `client/backend/server.py` (`_handle_engine_read_proxy_post`)
- **Changes:** beside the likes sanitising, `exclude` must be a list of at most 500 objects with non-empty string `id` and `host`; over the cap → 400. Entries are stripped and forwarded. The profile branch (`profile_id is not None`) replaces `likes` and adds `dislike_centroids`, leaving `exclude` in place.
- **Depends on it:** E1 via E2; the Engine (E6).
- **Regression risk:** medium. Every feed request passes through it, and the likes sanitising silently drops malformed entries, so it is not a precedent for the 400 over the cap.

### E6 Engine request parsing
- **path:** `engine/server/api/handlers/similar.py` (`_handle_similar_request`)
- **Changes:** parses `exclude` from the POST body. More than 500 → 400 before any context is set, in the shape of `_recommendations_likes_payload_error`, on both POST routes. Valid entries become `video_id::instance_domain` keys stored through E7.
- **Depends on it:** `engine/server/api/tests/test_recommendations_likes_limit.py` drives `_handle_similar_request` with a dummy handler and patched context setters. Bodies without `exclude` must take the same path, or those tests break.
- **Regression risk:** medium.

### E7 Engine request context
- **path:** `engine/server/api/request_context.py`
- **Changes:** `set_request_excluded_keys` / `fetch_request_excluded_keys`, and `clear_request_context` clears them, following the dislike-centroids pair.
- **Depends on it:** E6, E8, E9.
- **Regression risk:** low, but a missed clear would leak one request's exclusions into the next on the same thread.

### E8 Engine home mixer
- **path:** `engine/server/api/recommendations/mixer.py` (`MixerDeps`, `generate_recommendations`, `_soft_mix_candidates`, `_apply_post_filters`)
- **Changes:** `MixerDeps` gains `fetch_excluded_keys`. In `generate_recommendations`, a non-empty excluded set adds `min(len(excluded), batch_size)` to what `_resolve_fetch_limits` gathers, and excluded candidates are dropped from `candidates_by_layer` before `_soft_mix_candidates` (RC1, Step 4).
- **Depends on it:** every home request; `builder.py` (E10) constructs `MixerDeps`.
- **Regression risk:** high. It is the ranking path, and plan 03 had to add an explicit placement rule here.

### E9 Engine random and up-next paths
- **path:** `engine/server/api/handlers/similar.py` (`_handle_random`, `_handle_home` random fallback, `_handle_seed_with_embedding`, and the `seed.get("random")` branch of `_handle_similar`)
- **Changes:** remove rows whose key is excluded. Up-next removes them before `rows[:limit]`.
- **Depends on it:** random mode, similar mode, and the video page's up-next strip (E3), which sends no `exclude`.
- **Regression risk:** medium.

### E10 Engine recommendation builder
- **path:** `engine/server/api/recommendations/builder.py` (`RecommendationBuilderDeps`, `MixerDeps(...)` at line 195)
- **Changes:** carries `fetch_excluded_keys` from the builder deps to the mixer deps.
- **Depends on it:** `server.py` (E11).
- **Regression risk:** low. A missing field fails at Engine start, not silently.

### E11 Engine server wiring
- **path:** `engine/server/api/server.py` (`RecommendationBuilderDeps(...)` at line 380)
- **Changes:** passes `fetch_request_excluded_keys`.
- **Depends on it:** Engine start.
- **Regression risk:** low.

### E12 Engine limits
- **path:** `engine/server/api/server_config.py`
- **Changes:** `DEFAULT_CLIENT_LIKES_BODY_LIMIT` 65536 → 131072, and a new cap constant for `exclude` (500) beside `DEFAULT_CLIENT_LIKES_MAX`.
- **Depends on it:** `similar.py` (E6); the same limit guards `/videos/similar`.
- **Regression risk:** low. The Engine is loopback-bound behind the Client's 1 MB cap.

### E13 Engine likes-limit unit tests
- **path:** `engine/server/api/tests/test_recommendations_likes_limit.py`
- **Changes:** none. It is a regression net for E6.
- **Depends on it:** —
- **Regression risk:** see E6.

### E14 Active suite feed tests
- **path:** `tests/active/test_similar.py`, `tests/active/test_blocks.py`, `tests/active/test_dislike_profile.py`, `tests/active/test_frontend_blocks.py`
- **Changes:** none. They pin home, random and up-next rows, the proxy's filtering and over-fetch, the dislike placement, and `fetchSimilarVideosPayload` with one argument. The harness these checkpoints reuse is `conftest.py`'s `engine`, `engine_client` and `dataset` fixtures, and the node+esbuild runner in `test_frontend_blocks.py`.
- **Regression risk:** these tests are the net for E2, E5, E8 and E9.

### E15 Built frontend
- **path:** `client/frontend/dist/`
- **Changes:** rebuilt by `npm run build` once E1 and E2 land. It is tracked in git, and the operator rsyncs it to `/var/www/peertube-browser` for browser testing.
- **Depends on it:** the operator's manual browser check.
- **Regression risk:** low.

### E16 Contract and smoke scripts
- **path:** `tests/check-frontend-client-gateway.sh`, `tests/check-client-engine-boundary.sh`, `tests/run-arch-split-smoke.sh`
- **Changes:** none expected. They check that the frontend uses gateway routes only and that the Client does not import Engine code; neither changes.
- **Depends on it:** —
- **Regression risk:** low.

### E17 Client README
- **path:** `client/README.md` (read gateway paragraph, line 25-26)
- **Changes:** document that feed requests accept `exclude` (≤500 identities), forwarded to the Engine with or without a key.
- **Regression risk:** none (documentation).

### E18 Frontend README
- **path:** `client/frontend/README.md` (line 9, "Renders feeds")
- **Changes:** the videos page loads further batches as it is scrolled, excluding rows already shown.
- **Regression risk:** none (documentation).

### E19 Recommendations overview
- **path:** `engine/server/api/recommendations/docs/OVERVIEW.md` (§1 requests, §7 post-filters, §8 what the client receives)
- **Changes:** a request may carry `exclude`; excluded videos are never returned on home, up-next and random.
- **Regression risk:** none (documentation).

### E20 Root README gateway row
- **path:** `README.md` (line 48, browser-facing read gateway row)
- **Changes:** probably none: the row describes filtering per profile, not body fields. Checked at Step 9.
- **Regression risk:** none (documentation).

### E21 Roadmap
- **path:** `docs/project/roadmap.md` (line 134, "Feed paging — the next build")
- **Changes:** the item points at plan 09 and is marked delivered once the build closes.
- **Regression risk:** none (documentation).

### Highest risk

1. **E8 home mixer.** Exclusion has to keep home pages full, which is the whole point of O6 over O5, and the mixer builds pools sized to the batch. Plan 03 showed that ranking changes here behave differently from what reading the code suggests.
2. **E5 Client proxy.** Every feed request goes through it, and it rewrites the body for keyed profiles. `exclude` has to survive that rewrite in both the keyed and the keyless branch.
3. **E1 videos page.** The only untested surface: no DOM harness exists, and a refetch loop or double render shows up only in a browser.

### Reassessment

#### Pass 1

**Entry not borne out: E8.** The inventory says excluded keys joining `seen_keys` make the mixer backfill. The file shows they would not. `_resolve_fetch_limits` gathers `batch_size × overfetch_factor` candidates across layers (the home `overfetch_factor` is 1). Every generator returns at most its fetch limit (`exploit_from_likes.py:112`, `explore_range.py:150`, `fresh_videos.py:146`, `popular_videos.py:173`, `random_videos.py:113`). The mixing loop in `_soft_mix_candidates` stops at `batch_size` before `_apply_post_filters` runs. So `seen_keys` only skips rows from a pool that holds no spare: every excluded row it skips is one row short on the page. The same holds for today's liked-video dedup.

Every other entry was opened and matches: E2 (`videos.ts:78-89` body `{}` or `{likes}`), E3 (`video-page/index.ts:248` single argument), E4/E5 (`server.py:94-97`, `:437-453`, the profile branch at `:473-482` touches only `likes` and `dislike_centroids`), E6 (`similar.py:556-605`; the likes-count check applies to `/recommendations` only, so the exclude cap needs its own check to cover both routes), E7 (`request_context.py`), E9 (`similar.py:655-702`, `:771`, `:964-973`), E10 (`builder.py:195-202`), E11 (`server.py:380-392`), E12 (`server_config.py:377-379`), E13 (the dummy handler sends no `exclude`), E14 (`test_similar.py`, `test_frontend_blocks.py` one-argument call).

**No new element.** `_handle_vector_search` is not reachable through the gateway (`vector` is not an allowed query parameter) and is left unchanged.

1. **Will it still work as intended?** Up-next, random, the Client and the frontend: yes. Home: not as planned. Pages would come back short by the number of collisions. Collisions are concentrated in the like-seeded layers, which fill half the batch.
2. **Ramifications.** Without a fix, home paging under a profile with likes shrinks page by page, and R7 ends paging early, which is O5's failure mode.
3. **What else must happen.** Home has to gather spare candidates when a request excludes anything, and remove excluded candidates before mixing so the schedule and its fallback fill from the rest.
4. **How the original functionality is altered.** Requests without `exclude` are untouched (R9).

**Recommendation RC1 (changes A3's home bullet and E8).** In `generate_recommendations`, when the excluded set is non-empty, gather `min(len(excluded), batch_size)` extra candidates, spread by `gather_ratio` like the rest. Then drop excluded candidates from each layer's list before `_soft_mix_candidates`. Cost: a refetch gathers and scores up to twice the candidates of a first load, and only refetches pay it. First loads and every request without `exclude` are unchanged.
**Alternative RC2.** Pass the excluded set into the five generators so each skips excluded rows before sampling. Backfill is more exact, but it touches five candidate modules plus their deps instead of one mixer function. Not recommended.

**Operator: "RC1".** A3's home bullet and E8 are amended.

#### Pass 2

RC1 stays inside `mixer.py` `generate_recommendations` (E8): `_resolve_fetch_limits` already takes the batch size it spreads, so the extra is added to the value passed in, not inside the function. Re-read `builder.py` and `server.py`: nothing beyond E10 and E11. No entry is unconfirmed and there is no new impact. Converged.

### Documentation to update

Step 9 outcome (against the per-phase change records):

- [x] `client/README.md` — **updated**: a new bullet on the read gateway's `exclude` field, which carries up to 500 `{id, host}` entries; a non-list or more than 500 gets 400 `Invalid exclude payload`, malformed entries are dropped, and it is forwarded keyed or not. It points to OVERVIEW.md for the Engine side.
- [x] `client/frontend/README.md` — **updated**: the feeds line now names the similar mode, and a new bullet covers paging (next batch at the end of the fetched rows, the 500 most recent excluded, repeats dropped, ends after an empty or failed batch, reload starts over).
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` — **updated**: new §1 subsection "Excluded Videos (Paging)" (the 400 over 500, home drops excluded candidates per layer and gathers extra, up-next removes them before the cut, random is not filtered). §8's "does not re-sort" is still true.
- [x] `README.md` — **no update**: the gateway row (line 48) describes per-profile filtering and the keyed rewrite, and makes no claim about body fields.
- [x] `docs/project/roadmap.md` — **updated**: feed paging is removed from the implementation order and the steps renumbered; step 4 notes I6 is delivered by plan 09.
- [x] `docs/project/plans/04-feed-parameter-panel.md` — **updated**: the status line says I6 is delivered by plan 09.
- [x] `engine/server/README.md` — **updated, inventory gap found at 9.1**: its Notes said ranking reads likes and dislike centroids from request-scoped input; it now names the excluded videos as well.
- `CONTEXT.md` — **no update**: the glossary defines profile-level terms (Dislike, Taste vector, Block); `exclude` is a request field of one page view, not a domain term.
- ADRs `0001`-`0005` (event ids, trusted proxy address, metadata uuid entries, CORS, raw event retention): none covers feed requests or ranking. No conflict.

## Implementation plan

### What needs testing

- The Engine, home: a request excluding a previous page's rows returns none of them, and still a full 48-row page (RC1).
- The Engine, up-next: a request excluding a previous page's rows returns none of them, and backfills from the ranked pool.
- The Engine and the Client: more than 500 entries → 400.
- The Client: `exclude` survives the keyed rewrite, and a 500-entry exclude plus a profile's centroids fits the Engine's body limit (A4).
- The frontend: successive pages share no row, and paging stops after a refetch that adds nothing.

### Measured at Step 5 (probe `tests/tmp/probe_identity_sizes.py`)

`whitelist.db`: `video_id` is always 36 characters; `instance_domain` averages 19.9 characters, maximum 53. A 500-entry `exclude` body is 40,020 bytes typically and 56,513 bytes for the 500 longest hosts. Four centroids at 6 decimals are 16,931 bytes. So the worst dataset case plus centroids (~74 KB) exceeds today's 65,536-byte Engine limit, and 131,072 covers it.

### Module map and draft

**`engine/server/api/server_config.py`** (E12)
```python
# Client JSON body limit. rat-tail: sized for a 500-entry `exclude` of the dataset's longest
# hosts (53 chars) plus a profile's four centroids, ~74 KB; raise if hosts grow.
DEFAULT_CLIENT_LIKES_BODY_LIMIT = 131072
# Most `exclude` entries one feed request may carry.
DEFAULT_CLIENT_EXCLUDE_MAX = 500
```

**`engine/server/api/request_context.py`** (E7), following the centroids pair:
```python
def set_request_excluded_keys(keys: set[str]) -> None: ...
def fetch_request_excluded_keys() -> set[str]:   # empty set when unset
    return getattr(_REQUEST_CONTEXT, "excluded_keys", None) or set()
# clear_request_context also deletes "excluded_keys"
```

**`engine/server/api/handlers/similar.py`** (E6, E9)
```python
def _parse_excluded_keys(payload: dict[str, Any]) -> set[str]:
    """Return a request's `exclude` entries as `video_id::instance_domain` keys (the `like_key` form)."""
    # a list of {"id", "host"} with non-empty strings; malformed entries are skipped, as likes are

# _handle_similar_request, inside `if isinstance(body, dict):`, after the likes check, both routes:
raw_exclude = body.get("exclude")
if isinstance(raw_exclude, list) and len(raw_exclude) > DEFAULT_CLIENT_EXCLUDE_MAX:
    respond_json(self, 400, {"error": "Too many exclude entries in request body",
                             "max_allowed": DEFAULT_CLIENT_EXCLUDE_MAX, "received": len(raw_exclude)})
    return
...
set_request_excluded_keys(_parse_excluded_keys(body) if isinstance(body, dict) else set())

def _drop_excluded(rows):   # module-level
    excluded = fetch_request_excluded_keys()
    return [row for row in rows if like_key(row) not in excluded] if excluded else rows

# _handle_seed_with_embedding: rows = _drop_excluded(score_and_rank_list(...)) before rows[:limit]
```
Invariant: without `exclude` the context holds an empty set and every path is byte-for-byte today's.

**`engine/server/api/recommendations/mixer.py`** (E8, RC1)
```python
@dataclass(frozen=True)
class MixerDeps:
    ...
    fetch_excluded_keys: Callable[[], set[str]]

# generate_recommendations, after batch_size is resolved:
excluded = self.deps.fetch_excluded_keys()
# Exclusions come out of the gathered pool, so gather that many more, up to one extra batch.
gather_size = batch_size + min(len(excluded), batch_size)
generator_limits = self._resolve_fetch_limits(generator_configs, generator_order, gather_size, ...)
# per layer, before the shuffle:
candidates = [c for c in candidates if self.deps.like_key(c) not in excluded]
# _soft_mix_candidates still receives batch_size, so the output stays one batch.
```

**`engine/server/api/recommendations/builder.py`** (E10): `RecommendationBuilderDeps.fetch_excluded_keys`, passed to `MixerDeps(...)`.
**`engine/server/api/server.py`** (E11): `fetch_excluded_keys=fetch_request_excluded_keys`.

**`client/backend/server.py`** (E4, E5)
```python
MAX_FEED_EXCLUDE = 500   # mirrors the Engine's DEFAULT_CLIENT_EXCLUDE_MAX
PROXY_ALLOWED_BODY_KEYS = {"/recommendations": {"likes", "user_id", "mode", "exclude"},
                           "/videos/similar": {"likes", "user_id", "mode", "exclude"}}
# _handle_engine_read_proxy_post, beside the likes sanitising:
exclude = sanitized_body.get("exclude")
if exclude is not None:
    if not isinstance(exclude, list) or len(exclude) > MAX_FEED_EXCLUDE:
        respond_json(self, 400, {"error": "Invalid exclude payload"})
        return
    sanitized_body["exclude"] = [{"id": e["id"].strip(), "host": e["host"].strip()} for e in exclude
                                 if isinstance(e, dict) and isinstance(e.get("id"), str) and e["id"].strip()
                                 and isinstance(e.get("host"), str) and e["host"].strip()]
# the profile branch is unchanged: it replaces likes and adds dislike_centroids only.
```

**`client/frontend/src/data/videos.ts`** (E2): the paging core sits here, beside the fetch it drives, so it runs in node against the real Client and Engine. The page keeps only the DOM wiring.
```ts
export type ExcludedVideo = { id: string; host: string };
export const MAX_FEED_EXCLUDE = 500;   // the Client's cap

export async function fetchSimilarVideosPayload(query: SimilarQuery, exclude: ExcludedVideo[] = []) {
  const body: Record<string, unknown> = getProfileKey() ? {} : { likes: getRandomLikes() };
  if (exclude.length) body.exclude = exclude;
  ...unchanged
}

/** Page through a feed: each batch excludes the rows earlier batches returned, and drops any the
 *  Engine repeats. A batch that adds no new row, or fails, ends the feed. */
export function createFeedPager(fetchBatch: (exclude: ExcludedVideo[]) => Promise<VideosPayload>) {
  const shown: ExcludedVideo[] = [];
  const keys = new Set<string>();
  let exhausted = false;
  return {
    get exhausted() { return exhausted; },
    async next(): Promise<VideosPayload> {
      if (exhausted) return { rows: [] };
      let payload: VideosPayload;
      try { payload = await fetchBatch(shown.slice(-MAX_FEED_EXCLUDE)); }
      catch (error) { exhausted = true; throw error; }
      const fresh = [];
      for (const row of payload.rows ?? []) {
        const id = String(row.video_id ?? ""), host = String(row.instance_domain ?? "");
        const key = `${id}::${host}`;
        if (!id || !host || keys.has(key)) continue;
        keys.add(key); shown.push({ id, host }); fresh.push(row);
      }
      if (!fresh.length) exhausted = true;
      return { ...payload, rows: fresh };
    }
  };
}
```
The row's `video_id` is used, not `resolveVideoId`, because the Engine keys candidates as `video_id::instance_domain` and `resolveVideoId` prefers the UUID.

**`client/frontend/src/pages/videos/index.ts`** (E1)
```ts
let pager = createFeedPager(fetchVideosPayload);
let fetchingMore = false;
// loadVideos: pager = createFeedPager(fetchVideosPayload); const payload = await pager.next(); ...as today
// fetchVideosPayload(exclude: ExcludedVideo[] = []) passes exclude to fetchSimilarVideosPayload in all three branches
// loadNextChunk: when nextCount <= state.visibleCount, `void loadMoreVideos()` and return false
async function loadMoreVideos() {
  const current = pager;
  if (state.loading || fetchingMore || current.exhausted) return;
  fetchingMore = true;
  try {
    const payload = await current.next();
    if (current !== pager || !payload.rows?.length) return;   // a reload replaced the pager meanwhile
    state.rows.push(...payload.rows);
    state.sample.push(...payload.rows);
    loadNextChunk();
  } catch (error) {
    console.warn("[feed] loading more failed; paging stops for this page view", error);
  } finally {
    fetchingMore = false;
  }
}
```
Decisions: one pager per `loadVideos`, so a reset or a key retry starts with an empty shown set (R8), and a result from a replaced pager is dropped. A failed refetch ends paging, so a scroll fallback firing on every scroll event cannot repeat a failing request (K3).

### Draft check

- Pass 1 against the plan and requirements: R1 (all three modes route through `fetchVideosPayload`), R2 (`loadNextChunk` → `loadMoreVideos`), R3 (`shown.slice(-500)`), R4 (E4/E5, profile branch untouched), R5 (home via RC1, up-next via `_drop_excluded`, 400 cap in `_handle_similar_request` on both routes), R6 (pager `keys`), R7 (pager `exhausted`), R8 (pager per load, in memory), R9 (empty set → unchanged). **Miss:** R5 names random, and the draft has no random filter. It was dropped from the draft on purpose, and the question goes to the operator at Step 6: with a 500,000-row random cache, a 500-entry exclude collides with a 48-row draw about 0.05 times per page. No HTTP observable can show the filter working (plan 03 measured 0 repeats in 240 random rows), and R6 already drops any repeat in the browser.
- Operator on the random miss: "drop". R5 is amended to home and up-next; the draft now matches it.
- Pass 2: A4 is confirmed necessary by the measurement above. The pager's failure handling ("a failed batch ends the feed") is new behaviour beyond R7; it is recorded here as a design decision that serves K3. Converged.

### Phases

#### Phase 1 — Engine home exclusion

- **Kind:** code
- **Files:** `engine/server/api/request_context.py` EDITED, `engine/server/api/handlers/similar.py` EDITED (parse `exclude`, store it in the context), `engine/server/api/recommendations/mixer.py` EDITED, `engine/server/api/recommendations/builder.py` EDITED, `engine/server/api/server.py` EDITED; checkpoint `tests/tmp/test_feed_exclude_home.py` NEW.
- **Intent:** An Engine home request (`POST /recommendations` with no seed) that carries `exclude` gets back a page holding none of the excluded videos. When `exclude` holds the rows of a previous home page, the page it gets is as full as a plain home page, because `MixingRecommendationStrategy.generate_recommendations` gathers spare candidates and drops the excluded ones before mixing.
- **Clauses:**
  - `C1` A home response holds no row whose `video_id` and `instance_domain` match an entry of the request's `exclude`.
  - `C2` A home request whose `exclude` holds a previous home page's rows returns at least 45 rows, the fewest any plain home page returned in 24 observed draws.
- **Amended at 7.1 (operator: "floor45").** C2 first read "returns 48 rows". Probe `tests/tmp/probe_home_repeat.py` (three five-like sets × 8 plain draws) observed page sizes of 45-48 and a repeat of 11-21 rows of the first page on every draw. A post-mix skip of excluded rows would return about 27-37. The Intent's "still 48 rows" became "as full as a plain home page".
- **Checkpoint and seam:** the Engine's HTTP API, `POST /recommendations`, against the real Engine on the repo's dataset through `conftest.py`'s `engine` fixture. `test_similar.py` and `test_dislike_profile.py` are the precedent. Every request sends the same five `likes`, taken from the dataset, so the like-seeded exploit layer (half the batch) draws from the same shallow pool and repeats across requests. A control request without `exclude` must overlap the first page, which proves C1's absence is exclusion and not chance. Under no implementation, C1 reads a non-empty overlap. Under the Step 3 draft (excluded keys only in `seen_keys`), C2 reads fewer than 48.

- **Self-check (dispatch 1)**, `tests/tmp/test_feed_exclude_home.py`, seam `tests/tmp/conftest.py` (a copy of `tests/active/conftest.py`):
  - `C1 — test_feed_exclude_home.py:49, the previous page's keys intersected with the excluded request's page — expected: empty — under an Engine that ignores exclude (today): NON-EMPTY, observed on all three like-sets`
  - `C2 — test_feed_exclude_home.py:50, len(page) >= 45 — expected: 45-48 — under a skip of excluded rows after mixing with no spare gathered: about 48 − overlap (11-21 observed) = 27-37, below 45`
  - Supporting: `:43` control, a plain page overlaps the previous one (observed 11-21 rows in the probe), so C1's emptiness is exclusion and not chance.
  1. Whole claim: C1 at :49, C2 at :50; the name's "none of it" and "a full page" are those two, and the docstring's third paragraph is the fixture rationale, asserted by the :43 control.
  2. Absence only: C1 is negative; the :43 control proves repeats occur without `exclude`, and C2 is a positive count on the same page.
  3. Echoed literal: none. The previous page comes from the Engine, and deleting the mixer's exclusion turns :49 red, as observed today.
  4. One value: three like-sets (linux, cooking, music); C2's floor is an observed bound from 24 draws, not a shipped default.
  5. The double: none; real Engine on the real dataset.
  6. It collects: 3 node ids (`[linux]`, `[cooking]`, `[music]`).
  7. Observed, not predicted: the 45 floor and the 11-21 overlap come from `probe_home_repeat.py` runs; the row keys (`video_id`, `instance_domain`) from `probe_home_repeat.py`'s first run.
  8. Red: exit 1, 3 failed.
  9. Right reason: every parameter fails at `test_feed_exclude_home.py:49` (C1), `assert not _keys(previous) & _keys(page)` with a non-empty intersection. The Engine accepted the body (200) and ignored `exclude`. The :43 control passed.
  10. Observed expected output: C1's red matches the probe's "with exclude today: 200 48 overlap 14". C2 is not reached under today's code, and its wrong-implementation value is arithmetic from observed overlaps.
- **Checkpoint audit:**
  - `AUDIT: devsecops-test-shape-auditor — BLOCK: a stub returning no home rows under exclude falls back to a random draw (_handle_home), which passes C1 and C2 without being a home page. Fixed: _home asserts seed.mode == "home" and no seed.random on every response (:34). Re-audit: PASS. Predicted failure: line 51, C1, non-empty overlap, because nothing reads exclude.`
  - `AUDIT: devsecops-test-claim-auditor — PASS.` Frozen ledger: 11 rows, all CARRIED, none UNCARRIED. Recommendations (bounds: an `exclude` matching on `video_id` alone; malformed `exclude`) are not taken here. Host-scoped matching is Phase 2/3 surface, and malformed-entry handling is the Client's validation (Phase 3 C2).
- **Self-check (dispatch 2)**, after the fix: the rows are unchanged, and the lines move to C1 `:51` and C2 `:52`. The new supporting assertion is `:34`, every response is a home page (seed mode `home`, not `random`); a stub falling back to random reads `random: True` there. Questions 2-7 were walked again: `:34` is a positive control on the excluded response itself (question 2); it reads the Engine's own `seed` (question 3); it collects 3 ids (question 6). Still red for its own reason: exit 1, all three fail at `:51` (C1) with a non-empty overlap, and `:34` passed on every request.

- **Changes:**
  - `engine/server/api/request_context.py`: `set_request_excluded_keys` and `fetch_request_excluded_keys` (an empty set when unset), and `clear_request_context` clears `excluded_keys`.
  - `engine/server/api/handlers/similar.py`: `_parse_excluded_keys(payload)` turns `exclude` entries (`id`, `host`, non-empty strings, malformed ones skipped) into `video_id::instance_domain` keys. `_handle_similar_request` stores them for POST bodies (an empty set otherwise).
  - `engine/server/api/recommendations/mixer.py`: `MixerDeps.fetch_excluded_keys`. `generate_recommendations` gathers `batch_size + min(len(excluded), batch_size)` and drops excluded candidates from each layer right after generation.
  - `engine/server/api/recommendations/builder.py`: `RecommendationBuilderDeps.fetch_excluded_keys`, passed into `MixerDeps`.
  - `engine/server/api/server.py`: wires `fetch_request_excluded_keys`.
  - No file outside the phase's list.
- **Checkpoint outcome:** `validate_tests.py tests/tmp/test_feed_exclude_home.py`: 3 passed (16.5 s).

#### Phase 2 — Engine up-next exclusion and cap

- **Kind:** code
- **Files:** `engine/server/api/handlers/similar.py` EDITED (`_drop_excluded` in `_handle_seed_with_embedding`, the 400 cap), `engine/server/api/server_config.py` EDITED (`DEFAULT_CLIENT_EXCLUDE_MAX`); checkpoint `tests/tmp/test_feed_exclude_upnext.py` NEW.
- **Intent:** An Engine up-next request (`POST /recommendations?id=&host=`) whose `exclude` holds a previous up-next page's rows for the same seed gets a full page of other videos from that seed's ranked pool. An Engine feed request on `/recommendations` or `/videos/similar` whose `exclude` holds more than 500 entries is refused with 400, while one holding 500 is served.
- **Clauses:**
  - `C1` An up-next request whose `exclude` holds a previous 8-row up-next page of the same seed returns 8 rows, none of them in `exclude`.
  - `C2` The Engine answers 400 to a feed request with 501 `exclude` entries and 200 to one with 500, on `/recommendations` and on `/videos/similar`.
- **Checkpoint and seam:** the Engine's HTTP API through the `engine` fixture, as in `test_similar.py`'s up-next route (a search hit as the seed, `limit=8`). A control request without `exclude` returns the same page again, which proves the ranked pool repeats without exclusion. C2's 500-entry side uses real identities from `dataset`. Under no implementation, C1 reads the previous page again and C2's 501 reads 200.

- **Self-check (dispatch 1)**, `tests/tmp/test_feed_exclude_upnext.py`, seam `tests/tmp/conftest.py`:
  - `C1 — test_feed_exclude_upnext.py:46, len(page) == 8 — expected: 8 — under a filter applied after rows[:limit] (no backfill from the ranked pool): 0, since all 8 of the page are excluded`
  - `C1 — test_feed_exclude_upnext.py:47, previous page ∩ new page — expected: empty — under an Engine that ignores exclude (today): all 8 rows, observed on linux and cooking`
  - `C2 — test_feed_exclude_upnext.py:62, 500 real entries → 200 with rows — expected: 200 — under a cap check written as >= 500: 400`
  - `C2 — test_feed_exclude_upnext.py:65, 501 entries → 400 — expected: 400 — under no cap (today): 200, observed on both routes`
  - Supporting: `:40` control, a plain repeat returns the identical page (observed `a==b True` in `probe_upnext_repeat.py`).
  1. Whole claim: C1 is the length at :46 plus disjointness at :47, and C2 is 500 → 200 at :62 plus 501 → 400 at :65, on both routes by parametrize. The name and docstring say the same and no more.
  2. Absence only: :47 is negative, and :46 and :40 are positive controls on the same path. :65 is a positive status.
  3. Echoed literal: none. The previous page comes from the Engine, and the entries from `whitelist.db`.
  4. One value: C1 runs on two seeds, and C2 on two routes with both sides of the bound.
  5. The double: none.
  6. It collects: 4 node ids.
  7. Observed: pool depths of 19 and 17, the identical repeats, and today's 200 at 501 all come from `probe_upnext_repeat.py`.
  8. Red: exit 1, 4 failed.
  9. Right reason: the up-next pair fails at :47 with all 8 rows shared (:46 passed, because today returns the same 8). The cap pair fails at :65 with `assert 200 == 400` after :62 passed. No control failed.
  10. Observed expected output: as the probe showed. The :46 wrong-implementation value (0) is a prediction for a filter placed after the slice.
- **Checkpoint audit:**
  - `AUDIT: devsecops-test-shape-auditor — BLOCK: single-value-pin, because the only exclude equals the page's first 8 positions, so an offset-paging implementation (rows[len(exclude):]) passes. Fixed: a second exclude of every other row of the previous page, and the page asserted equal to the seed's ranked pool (a plain 16-row request) with the excluded rows removed. Re-audit: pending.`
  - `AUDIT: devsecops-test-claim-auditor — PASS.` Frozen ledger: 20 rows, one UNCARRIED, D3 ("ranked pool deeper than two 8-row pages", asserted only by a comment). **Fixed:** the :44 control asserts the plain 16-row page is 16 rows and its head is the previous page, and C1's equality at :53 ties the page to that pool. Recommendations: 2 (malformed `exclude` shapes) is not taken, because malformed-entry handling belongs to the Client's validation (Phase 3); 3 (rate-limit sharing) is handled by running each checkpoint in its own lane (memory `engine-rate-limit-single-lane-test-runs`); 4 (tie the 400 to its cause) is taken, and :71 asserts the error text.
- **Self-check (dispatch 2)**, after the fixes:
  - `C1 — test_feed_exclude_upnext.py:53, page == ranked pool minus excluded, first 8, for exclude = the whole previous page and exclude = rows 0,2,4,6 — expected: pool rows 8-15, and pool rows 1,3,5,7,8,9,10,11 — under exclude ignored (today): the previous page, observed; under offset paging: pool rows 4-11 for the second exclude, which hold the excluded rows 4 and 6; under a filter after rows[:limit]: 0 and 4 rows`
  - `C2 — :68, 500 → 200 with rows — as before`
  - `C2 — :71, 501 → (400, "Too many exclude entries in request body") — under no cap (today): (200, None), observed; under the body-size guard's 400: its "Invalid JSON body" text`
  - Supporting: `:40` plain repeat and `:44` 16-deep pool whose head is the previous page.
  - Questions 2-7 walked again: the expected list is derived from the Engine's own plain output, not by re-running the code's filter, since the plain request carries no exclude (question 3); two excludes × two seeds (question 4); collects 4 ids (question 6). Still red for its own reason: exit 1, the up-next pair at :53 with page == previous (index 0 differs from the expected pool row 8), the cap pair at :71 with `(200, None)`. No control failed.

- Audit outcome, after the fixes: `AUDIT: devsecops-test-shape-auditor — Re-audit: PASS. Predicted failure: line 53 on the first loop pass (the page equals previous), and line 71 with (200, None) on both routes.` `AUDIT: devsecops-test-claim-auditor — bounded re-audit: PASS, D3 CARRIED by :44 and :53.` Observation recorded: the `:16` comment still cites the probe's pool depths, and it is a comment, not a claim.
- **Changes:**
  - `engine/server/api/server_config.py`: `DEFAULT_CLIENT_EXCLUDE_MAX = 500`.
  - `engine/server/api/handlers/similar.py`: `_handle_similar_request` answers 400 `{"error": "Too many exclude entries in request body", "max_allowed", "received"}` when a POST body's `exclude` list is longer than the cap, on both POST routes. `_handle_seed_with_embedding` removes excluded rows (by `like_key`) after ranking and before `rows[:limit]`. It imports `like_key` from `recommendations.keys`.
  - No file outside the phase's list.
- **Checkpoint outcome:** `validate_tests.py tests/tmp/test_feed_exclude_upnext.py`: 4 passed (10.0 s).

#### Phase 3 — Client gateway forwarding and body capacity

- **Kind:** code
- **Files:** `client/backend/server.py` EDITED (`PROXY_ALLOWED_BODY_KEYS`, `MAX_FEED_EXCLUDE`, validation in `_handle_engine_read_proxy_post`), `engine/server/api/server_config.py` EDITED (`DEFAULT_CLIENT_LIKES_BODY_LIMIT`); checkpoint `tests/tmp/test_feed_exclude_gateway.py` NEW.
- **Intent:** The Client backend passes a browser's `exclude` on `/recommendations` and `/videos/similar` through to the Engine, including for a keyed profile whose body it rewrites with the profile's likes and taste vectors, and the Engine accepts that body at 500 entries of the dataset's longest hosts. The Client refuses an `exclude` of more than 500 entries with 400.
- **Clauses:**
  - `C1` A keyed home request through the Client, for a profile holding likes and four dislikes, whose `exclude` holds 500 entries (a previous keyed page's rows plus the longest-host videos in the dataset), returns 200 with no row in `exclude`.
  - `C2` The Client answers 400 to a feed request with 501 `exclude` entries, and passes one with 500 on to the Engine.
- **Checkpoint and seam:** the Client backend's HTTP API. C1 goes through `engine_client`, or `unpublished_client` if the likes must publish nothing, with profile likes and a dislike made through the Client's own routes as `test_dislikes.py` does. A control request without `exclude` overlaps the previous page. C2 goes through `client_backend` (Engine port closed): 501 → 400 `Invalid exclude payload`; 500 → 502 from the closed Engine, which proves validation let it through. Under no implementation, C1 reads 400 `Unknown body field`. With the allowlist but no body-limit raise, it reads the Engine's 400 (about 74 KB against 64 KB). With a profile branch that dropped `exclude`, it reads an overlap.

- **Seam detail (7.1):** C1 runs through `unpublished_client` (publish mode `activitypub`), so the likes write no `Like` rows to the live `whitelist.db`; each like is stored and then answered 502.
- **Self-check (dispatch 1)**, `tests/tmp/test_feed_exclude_gateway.py`:
  - `C1 — test_feed_exclude_gateway.py:79 (via _home :36-37), keyed request with 500 entries → 200 and a home page — expected: 200 — under no allowlist (today): 400 "Unknown body field: exclude", observed; under the allowlist without the body-limit raise: the Engine's 400 (body > 64 KB)`
  - `C1 — :83-84, page non-empty and disjoint from the 500 excluded — expected: disjoint — under a profile branch that drops exclude: the previous page's repeats (the :75 control shows plain keyed pages overlap)`
  - `C2 — :91, 500 entries → 502 (reached the closed Engine) — expected: 502 — under no allowlist (today): 400, observed; under a cap written as >= 500: 400`
  - `C2 — :94, 501 entries → (400, "Invalid exclude payload") — expected: that pair — under no cap: 502; under today: 400 with "Unknown body field", a different cause`
  - Supporting: the dislike returns 200 (:69), so taste vectors are stored; a plain keyed page overlaps the previous one (:75); the exclude alone is over 50 KB (:81).
  1. Whole claim: C1 is covered by :79 plus :83-84, and C2 by :91 plus :94. The docstring's "over 64 KB" is carried by the :81 control together with the stored taste vectors (:69).
  2. Absence only: :84 is paired with :83 non-empty, the :36-37 status and seed checks, and the :75 control.
  3. Echoed literal: the error string at :94 is the Client's own message, and it pins the cause. The previous page comes from the Engine.
  4. One value: C2 covers both sides of the bound, 500 and 501.
  5. The double: none. `client_backend`'s closed Engine port is the real Client with no Engine behind it, and C2's 500 side reads the Client's own 502 for it.
  6. It collects: 2 node ids.
  7. Observed: the sizes come from `probe_identity_sizes.py`, and the keyed overlap and the 400 text from this run.
  8. Red: exit 1, 2 failed.
  9. Right reason: C1 fails at :79 → :36 with `{'error': 'Unknown body field: exclude'}`, after the controls at :69, :75 and :81 passed. C2 fails at :91 with 400 instead of 502, for the same unknown field.
  10. Observed expected output: the 400 text is as observed. The 502 for a closed Engine is observed (`probe_closed_engine.py`): `(502, ENGINE_PROXY_UNAVAILABLE)`.
- **Checkpoint audit:**
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 79 via _home :36, 400 "Unknown body field: exclude"; line 91, the same 400 where 502 is expected.` That round read the file before the claim remediation, so it is re-dispatched.
  - `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim, C1b "for a profile holding likes" UNCARRIED, because the like statuses were discarded and nothing read the likes back. Fixed: GET /api/user-profile/likes with the key must return exactly the five liked (uuid, host) pairs. Re-audit: pending.`
  - Frozen ledger, UNCARRIED rows: C1b **fixed** (the likes read back, which excludes a like refused with 404 or 502 before storage); D3 **fixed** by the same assertion; D6 ("the body the Engine receives is over 64 KB") **justified**, narrowed to "over 50 KB of `exclude` alone", which is what :80 asserts; D11 ("no Like reaches whitelist.db") **justified**, narrowed to naming the fixture. Recommendations: 3 (a truncated forward) and 4 (malformed shapes) are recorded and not taken.
- **Self-check (dispatch 2)**: the rows are unchanged, and the lines move to C1 `:82` via `_home :36-37`, `:86-87`, and C2 `:94`, `:97`. The new supporting assertion is `:63-64`, the profile's likes read back as the five liked videos. Questions 2-7 walked again: the likes read-back is through the Client's own route (question 3), and 2 ids collect (question 6). Still red for its own reason: C1 fails at :82 → :36 with `Unknown body field: exclude` after the likes, dislike, overlap and size controls passed; C2 fails at :94 with the same 400.

- Audit outcome, after the fixes: `AUDIT: devsecops-test-shape-auditor — Re-audit: PASS. Predicted failure: :82 via _home :36, 400 Unknown body field; :94, the same 400.` `AUDIT: devsecops-test-claim-auditor — bounded re-audit: PASS; C1b and D3 CARRIED by :65; D6 and D11 carried by narrowing.` Observations recorded: D3 is carried at storage level, not in the forwarded body.
- **Changes:**
  - `client/backend/server.py`: `MAX_FEED_EXCLUDE = 500`, and `exclude` added to `PROXY_ALLOWED_BODY_KEYS` for both feed routes. `_handle_engine_read_proxy_post` answers 400 `Invalid exclude payload` for a non-list or more than 500 entries, and otherwise keeps the `{id, host}` entries with non-empty strings, stripped. The profile branch is untouched, so `exclude` rides along.
  - `engine/server/api/server_config.py`: `DEFAULT_CLIENT_LIKES_BODY_LIMIT` 65536 → 131072, with a rat-tail comment.
- **Checkpoint outcome:** 2 passed (12.4 s).
- **Checkpoint gap found after gating, fixed with operator approval ("amend").** With the body limit reverted to 65536, the checkpoint still passed. Probe `probe_forwarded_body.py` observed that one dislike stores one taste vector (3,993 bytes), so the forwarded body stayed near 61 KB. C1 now reads "…for a profile holding likes and four dislikes…" (four dislikes → four vectors, about 16 KB), and the test dislikes four search hits, each asserted 200. Verified by mutation: at 65536, C1 fails at `:83` via `:36` with the Engine's `400 Invalid JSON body`; at 131072, 2 passed (13.0 s). `AUDIT: devsecops-test-shape-auditor — Re-audit (amended): PASS. Predicted failure at 65536: :83 via _home :36, 400 "Invalid JSON body".` That matches the mutation run. Recommendation (the forwarded body size is not measured in-test) recorded and not taken: the mutation run is the observation that the body passes 64 KB.

#### Phase 4 — Frontend feed pager

- **Kind:** code
- **Files:** `client/frontend/src/data/videos.ts` EDITED (`ExcludedVideo`, `MAX_FEED_EXCLUDE`, `fetchSimilarVideosPayload(query, exclude)`, `createFeedPager`), `client/frontend/src/pages/videos/index.ts` EDITED (wiring); checkpoint `tests/tmp/test_frontend_feed_pager.py` NEW.
- **Intent:** `createFeedPager` in `client/frontend/src/data/videos.ts`, fetching through `fetchSimilarVideosPayload` and the real Client and Engine, returns successive batches that never repeat a row an earlier batch returned. Once a batch adds no new row, it makes no further request.
- **Clauses:**
  - `C1` A pager's second batch holds rows, none of which its first batch held.
  - `C2` After a batch that adds no row, the pager's next call makes no request.
- **Checkpoint and seam:** `data/videos.ts` bundled with esbuild and run in node against `engine_client`, keyless, the harness `test_frontend_blocks.py` uses. The pager runs in similar mode (seed from a search hit, `limit=8`), where the Engine's ranked pool repeats without exclusion. So a pager that sent no `exclude`, or a Client that dropped it, would get the first 8 rows back, dedupe them away, and fail C1. C2 counts calls to the fetch function the pager is given: a pass-through wrapper around `fetchSimilarVideosPayload`, which is the pager's injected network boundary. The pager is driven until a batch comes back empty, then called once more.
- **Scaffold before the checkpoint (`gates.md <red_for_the_right_reason>`):** `data/videos.ts` gained `ExcludedVideo`, `FeedPager` and a `createFeedPager` that throws `createFeedPager is not implemented`, so the red is absent behaviour rather than a missing export.
- **Self-check (dispatch 1)**, `tests/tmp/test_frontend_feed_pager.py`, seam: `data/videos.ts` bundled by esbuild and run in node against `engine_client` (keyless), as in `test_frontend_blocks.py`:
  - `C1 — test_frontend_feed_pager.py:88, second batch non-empty — expected: non-empty (up to 8 rows from a 19-deep pool) — under a pager that sends no exclude, or a fetchSimilarVideosPayload that drops it: EMPTY, because the Engine returns the same 8 (the :83 control shows plain fetches repeat) and the pager's dedupe removes them all`
  - `C1 — :89, first ∩ second — expected: empty — under a pager that neither excludes nor dedupes: all 8 rows`
  - `C2 — :93, calls after the empty batch == calls at it — expected: equal — under a pager that keeps fetching after an empty batch: one more`
  - Supporting: `:83` two plain fetches return the same non-empty page; `:84` no batch errored; `:87` the first batch is non-empty; `:92` an empty batch is reached with a call after it.
  1. Whole claim: C1 at :88-89, C2 at :93. The name's "never repeat a row" is claimed for the first two batches only; the docstring says "the second batch holds rows and none of the first batch's", which matches.
  2. Absence only: :89 is paired with :88 and :87 on the same batches.
  3. Echoed literal: none; rows come from the Engine through the Client.
  4. One value: a single seed. C1's discrimination rests on the observed repeat of plain fetches (:83), and C2 is read at the point the pager itself reached.
  5. The double: the counting wrapper passes straight through to the real `fetchSimilarVideosPayload`, and it is the pager's injected dependency, not an owned module replaced.
  6. It collects: 1 node id.
  7. Observed: the seed's 19-deep pool and repeating plain pages come from `probe_upnext_repeat.py`; the runner's output shape comes from this run.
  8. Red: exit 1, 1 failed.
  9. Right reason: it fails at `:84` with `Error: createFeedPager is not implemented`, the scaffold's absent behaviour. The `:83` control passed first.
  10. Observed expected output: the plain repeat is as observed. The batch sequence (8, 8, 3, 0) is a prediction from the 19-deep pool, and it cannot be observed until the pager exists.
- **Checkpoint audit:**
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 84, the runner reports "createFeedPager is not implemented".`
  - `AUDIT: devsecops-test-claim-auditor — PASS`, with four UNCARRIED rows in the frozen ledger:
    - D2 and N1 ("batches never repeat a row", checked only for batches 1-2): **fixed**. A loop asserts every batch is disjoint from all earlier ones, which excludes a pager that excludes only its previous batch.
    - D4a ("in up-next mode", never read): **fixed**. The runner reports the plain fetch's `seed.mode`, and `:86` asserts `upnext`, which excludes a seed that fails to resolve and falls to home.
    - D9 ("No key is stored"): **justified** by narrowing it to describe the harness ("stores no profile key").
    - Recommendation 4 is taken: C2 now asserts `calls` is constant for every batch after the empty one. Recommendations 5 (fetch rejection) and 6 (the 500 edge) are recorded and not taken: the pager's rejection path ends paging by design (Step 5 decision), and the 500 cap is gated at the Client (Phase 3 C2).
- **Self-check (dispatch 2):** rows as before, with lines moved to C1 `:91-92` and C2 `:101`. The new supporting assertions are `:86` (mode `upnext`) and `:93-96` (no batch repeats an earlier one). Questions 2-7 walked again, with no change to the answers. Still red for its own reason: exit 1, `:88` reports `createFeedPager is not implemented`, and `:86` and `:87` passed.
- **Round 2:** `AUDIT: devsecops-test-shape-auditor — Re-audit: PASS. Predicted failure: :88, stub error.` `AUDIT: devsecops-test-claim-auditor — BLOCK: D9 is still UNCARRIED; the narrowed harness sentence carries no assertion. Fixed: the sentence is withdrawn from the docstring.` D2, N1 and D4a are CARRIED. Observation 2 is taken: a control now asserts that `calls` is 1, 2, …, n up to the empty batch, so a pager that bypasses its injected fetch fails. Observations 1 (repeats within a batch) and 3 (the mode is read on plain fetches only) are recorded and not taken. Still red at `:88`, the stub error.
- **Round 3:** `AUDIT: devsecops-test-shape-auditor — Re-audit: PASS. Predicted failure: :88, "createFeedPager is not implemented".` `AUDIT: devsecops-test-claim-auditor — bounded re-audit: PASS; D9 withdrawn, C1 and C2 CARRIED at :92-93 and :101-104.` No UNCARRIED row remains.
- **Changes:**
  - `client/frontend/src/data/videos.ts`: `ExcludedVideo`, `FeedPager`, `MAX_FEED_EXCLUDE = 500`, and `createFeedPager(fetchBatch)`. The pager sends the most recent 500 shown `{id: video_id, host}` as the exclude, drops rows already shown (and rows missing either field), ends after a batch that adds nothing or fails, and returns the payload with only the new rows. `fetchSimilarVideosPayload(query, exclude = [])` puts a non-empty `exclude` in the body beside `likes`.
  - `client/frontend/src/pages/videos/index.ts`: one pager per `loadVideos`, whose first batch is the initial load. `fetchVideosPayload(exclude)` passes `exclude` in all three modes. `loadNextChunk` calls `loadMoreVideos` when the batch is exhausted. `loadMoreVideos` fetches one batch at a time, drops a replaced pager's result, appends to `rows` and `sample`, then reveals through `loadNextChunk` and `maybeFillViewport`, because the sentinel may still be in view and its observer will not fire again. A failure is logged with `console.warn` and ends paging.
  - `npx tsc --noEmit` reports 37 lines of errors in the frontend. None are in `data/videos.ts` or on lines this phase added. Those near the edits (`index.ts` :200-231, :308-309) are existing `possibly 'null'` checks in `loadVideos` and `renderSummary`.
- **Checkpoint outcome:** `validate_tests.py tests/tmp/test_frontend_feed_pager.py`: 1 passed (9.6 s).
- **Not covered by a clause:** the page wiring in `pages/videos/index.ts` (sentinel → `loadMoreVideos` → append). There is no DOM harness (no jsdom or similar in `client/frontend/node_modules`). It is verified by the operator in the browser against the rebuilt `dist/` at Step 8.

#### Rationale and coordination

- Four phases, split along the requirements' layers, each with the lowest changed layer first: Engine home (the riskiest, RC1), Engine up-next and cap, Client, frontend. Each later phase exercises the earlier ones end to end.
- Random mode has no Engine-side clause (R5 amended at Step 5). Its paging is covered by the pager's dedupe (C1 of Phase 4 exercises the same pager).
- The Engine-backed checkpoints run in separate `validate_tests.py` invocations: several Engine-backed files in one lane trip the Engine's 60/min rate limit.
- **Coordination:** at Step 8 the operator rebuilds and rsyncs `dist/` and checks the videos page in a browser, in home, `?mode=random` and `?id=` modes: scrolling past 48 rows loads more, no card repeats, and paging stops quietly when the feed runs out.

## Inner unit tests

None. Every behaviour was expressible at its phase's checkpoint.

## Close

- **Refactors:** none made. Two were considered and left:
  - The `exclude` entry validation exists in both the Client (`_handle_engine_read_proxy_post`) and the Engine (`_parse_excluded_keys`). Each is a trust boundary, and the requirements have both validate.
  - The `like_key` filter appears in `mixer.py` and `similar.py`, two lines each on different paths.
  Nothing turned out to need new behaviour.
- **Clause accounting:** P1C1 and P1C2 are carried (both PASS, test_feed_exclude_home.py :51, :52). P2C1 and P2C2 are carried (both PASS, test_feed_exclude_upnext.py :53, :68/:71). P3C1 (amended with approval to four dislikes) and P3C2 are carried (both PASS, test_feed_exclude_gateway.py :83-88, :94-97). P4C1 and P4C2 are carried (both PASS, test_frontend_feed_pager.py :92-93, :104). No exemptions.
- **Checkpoints:** all four green, each in its own lane.
- **`--compare`:** 8 changed groups ran, 54 passed; 2 unchanged groups (`test_db.py`, `test_random_videos.py`) hold the banked result. "nothing moved against the previous record". Green, and the baseline was 58 passed.
- **Engine unit tests** (`engine/server/api/tests`, outside `active`): 13 OK under `unittest`.
- **Checkpoint gap found:** Phase 3's first C1 did not gate A4, because one dislike makes one taste vector. It was found by reverting the limit and fixed with operator approval (see Phase 3).
- **Built frontend:** `npm run build` rebuilt `client/frontend/dist/`.
- **Coordination:** the operator checked the videos page wiring in the browser, after restarting the Engine and Client and rsyncing `dist/`: "it works".
- **Harvest (Step 10):** six tests are DURABLE. Three went into `tests/active/test_similar.py`, and two new groups were created: `tests/active/test_server.py` and `tests/active/test_frontend_videos.py`. Each moved test was verified by one mutation. `--audit-map` exits 0. The scratch is in `delete_me/plan09-tmp/`. `--compare` shows 10 appeared and nothing else. Detail in `docs/project/plans/harvest-09-feed-paging-plan.md`.
