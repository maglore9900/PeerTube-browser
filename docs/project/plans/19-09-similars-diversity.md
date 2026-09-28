# 09-similars-diversity

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-09-similars-diversity.record.md`._

## Requirements

### Purpose

On the video page, up-next similars often repeat the same small set when the page is refreshed, and some seeds return only 1-5 similars. This build makes up-next pools large enough to fill a 48-row batch, which issue 12 (similars on scroll) will need. It also makes each refresh draw a different, similarity-weighted sample from that pool. That holds with and without likes, and source-video relevance stays dominant. It is the base that `11-fast-similars-response` and `12-similars-on-scroll` build on. The operator confirmed it does not need `08-stable-ann-ids` first. It proceeds on today's rowid ANN, and the ANN-search changes stay inside `engine/server/data/ann.py` so that plan 17 changes one place.

### Scope: which requests are "up-next"

The issue's `/api/similar` does not exist. Up-next means a seeded similarity request that reaches `SimilarHandler._handle_seed_with_embedding` (`engine/server/api/handlers/similar.py:742`):
- `POST /recommendations?id=…&host=…`: the frontend video page (`client/frontend/src/pages/video-page/index.ts:248`, `limit=8`, no exclude) and `videos.html` (paged with `exclude` by `createFeedPager`);
- `POST /videos/similar`;
- `GET /videos/{id}/similar`.

These are unchanged: the home feed (`_handle_home`, including the like-seeded layers `cached_similar_from_likes` and `ann_similar_from_likes`, which also call `get_similar_candidates`), the random feed, the raw-vector ANN path (`_handle_vector_search`) and search.

### Root cause found in the tree

- `get_similar_candidates` (`engine/server/data/similarity_candidates.py:37`) reads the similarity cache first. `DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE = False` (`server_config.py:350`), so any non-empty cache entry counts as a hit, and ANN never runs for that seed.
- The cache is filled by `precompute-similar-ann.py` with `--top-k 20` (`scripts/run-dataset-build.sh:257`, `engine/server/db/jobs/updater-worker.py:1123`, `DATA_BUILD.md:244`). So a precomputed seed has at most 20 candidates.
- `_build_rows` then keeps one row per author (`DEFAULT_SIMILARITY_MAX_PER_AUTHOR = 1`) and drops errored videos, which leaves pools like the 17 and 19 recorded in `tests/active/test_similar.py:65`, or 1-5 for single-channel clusters.
- The handler ranks with `score_and_rank_list` and cuts `rows[:limit]` (`similar.py:813`). The same seed therefore always returns the same page.
- ANN parameters today are `DEFAULT_SIMILARITY_SEARCH_LIMIT = 5000` and a global `DEFAULT_NPROBE = 24`, set once on the shared index at startup (`server.py:357`). The cache-miss ANN path (`data/ann.py:compute_similar_items`) runs only when the cache has no entry at all.

### R1 - Config-driven up-next ANN

Add these module-level constants to `engine/server/api/server_config.py`, each with a `#` comment in the file's style. They are starting tunables chosen by judgement, not measured values.
- `SIMILAR_VIDEO_SEARCH_LIMIT = 5000`: initial ANN `k` for the up-next fallback.
- `SIMILAR_VIDEO_TOP_K = 300`: the most candidates kept in the up-next pool after filters.
- `SIMILAR_VIDEO_NPROBE = 32`: initial FAISS nprobe for the up-next fallback.
- `SIMILAR_VIDEO_TARGET_MIN_POOL = 48`: the pool size below which the fallback runs. It equals `BATCH_SIZE`.
- `SIMILAR_VIDEO_MAX_NPROBE = 128` and `SIMILAR_VIDEO_MAX_SEARCH_LIMIT = 20000`: hard caps for the fallback's step-up.
- `SIMILAR_VIDEO_MIN_SCORE = 0.35`: the relevance floor for fallback candidates.
- `SIMILAR_VIDEO_TAIL_MIN_SCORE = 0.25`: the relaxed floor, used only for the tail fill.
- `SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR = 4`: the sampling window is top-M, where M = factor × limit, capped at the pool size.

Environment overrides are not required. The Engine logs every one of these values once at startup (`engine/server/api/server.py`, next to the existing startup log lines). `DEFAULT_NPROBE`, `DEFAULT_SIMILARITY_SEARCH_LIMIT` and `DEFAULT_SIMILAR_PER_LIKE` keep their values and still govern every other route.

### R2 - Low-candidate fallback (serve-time only)

- For an up-next request, the pool is built as today: cache read, filters, `_build_rows`. If the filtered pool holds fewer than `SIMILAR_VIDEO_TARGET_MIN_POOL` rows, or the cache has no entry for the seed, the fallback runs a live ANN search for the seed's embedding. It starts at `SIMILAR_VIDEO_NPROBE` and `SIMILAR_VIDEO_SEARCH_LIMIT`.
- Each step doubles nprobe and search_limit, clamped to `SIMILAR_VIDEO_MAX_NPROBE` and `SIMILAR_VIDEO_MAX_SEARCH_LIMIT`. Stepping stops when the pool reaches the target, when both caps are reached, or when a step adds no new row.
- Fallback candidates go through the same filters as cached rows (R3). Candidates scoring at least `SIMILAR_VIDEO_MIN_SCORE` are added first. Only if the pool is still below the target after the last step are candidates between `SIMILAR_VIDEO_TAIL_MIN_SCORE` and `SIMILAR_VIDEO_MIN_SCORE` added, as a tail. Nothing below `SIMILAR_VIDEO_TAIL_MIN_SCORE` is ever added by the fallback.
- Fallback rows are merged with the cached rows. The pool is capped at `SIMILAR_VIDEO_TOP_K`, keeping the highest scores.
- The fallback never writes or overwrites the similarity cache. The existing behaviour on a total cache miss (compute, then write the entry if absent) stays as it is for the home callers.
- The index is shared across threads and routes. The fallback sets nprobe for its search and restores the previous value inside the same `server.index_lock` hold, so home, search and raw-vector requests always see `DEFAULT_NPROBE`.
- The fallback is up-next-only. Home callers of `get_similar_candidates` behave exactly as today, whether through a parameter, a policy field, or a separate function. The mechanism is the design's choice.
- Deliberate simplification: the precompute's `--top-k 20` and the cache contents are left as they are. Its ceiling is that every short-pool seed pays a live ANN search (up to the caps) on each request. The upgrade path is raising the precompute top-k and rebuilding `similarity-cache.db` on main, a separate operator task.

### R3 - Dedup and quality

- The pool is strictly deduplicated by `(video_uuid, instance_domain)` and by `video_id::instance_domain` (`like_key`, the identity `exclude` uses). A row whose key is already present from the cache is not added again from the fallback.
- These filters still apply to every row, cached or fallback: seed exclusion, the per-author cap (`SIMILARITY_MAX_PER_AUTHOR`, unchanged at 1, counted across the merged pool), `similarity_exclude_source_author`, the video error threshold, the request's `exclude` keys, and serving moderation (`apply_serving_moderation_filters`: blocked instances and channels).
- The dislike penalty (`apply_dislike_penalty` via `score_and_rank_list`) still applies before sampling.

### R4 - Diversity per refresh

- After scoring, the dislike penalty and the `exclude` filter, the handler forms a window from the top M rows by final score. M is `SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR × limit`, capped at the pool size.
- From that window it draws `limit` rows by similarity-weighted random sampling without replacement. Higher-scoring rows are more likely to be drawn, and every row with a positive weight can be drawn. If the window holds `limit` rows or fewer, all of them are returned.
- By default every request draws afresh (server-side randomness), so repeated refreshes of one seed return different pages from the same relevant pool.
- An optional integer query parameter `seed` makes the draw reproducible: the same seed, pool and parameters return the same page. It exists for tests and debugging. The Client backend does not need to forward it.
- The served page is ordered by final score, descending.
- Paging with `exclude` still works: excluded rows are removed before the window is formed, so the next page is drawn from rows not yet shown.

### R5 - Likes vs no likes

- `RELATED_VIDEOS_PERSONALIZATION` in `server_config.py` changes from alpha 0.2 / beta 0.8 to alpha 0.7 / beta 0.3, so similarity to the source video dominates similarity to the user's likes.
- When personalization is enabled and likes are present, `rerank_related_videos` runs on the top-M window before the diversity draw, not on the page after it is cut (today it runs after `rows[:limit]`, `similar.py:813-824`). Likes therefore shape which rows are likely to be drawn.
- Without likes, the same window-and-draw runs on the source pool alone.
- The profile selection (`resolve_profile_config_with_guest`, `upnext` / `guest_upnext`) is unchanged.

### R6 - Observability

Each up-next request logs one line under its request id (`[similar-server][<id>]`) carrying:
- the initial pool size (after the cache read and filters);
- each fallback step's nprobe, search_limit and resulting pool size (or "none" when the fallback did not run);
- the final pool size and how many rows came from the tail fill;
- the sampling mode (`random` or `seeded`), the window size M and whether likes reranked it;
- the count of unique rows returned.

The existing timing and `done` log lines stay.

### R7 - Tests (in `tests/active`)

**Rewrites of existing tests that assume a deterministic ranked page:**
- In `tests/active/test_similar.py`, `test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos` (lines 167-189) asserts that a plain page repeats exactly and that the limit=16 page starts with the limit=8 page. Rewrite it to assert the exclude contract: a request excluding the previous page, or every other row of it, returns a full page containing none of the excluded rows, drawn from the seed's pool. The module docstring bullet is updated to match. `UPNEXT_SEED_QUERIES` and its "19 and 17 deep" comment are updated to the new pool depths.
- In `tests/active/test_dislike_profile.py`, the plain-versus-dislike comparisons (lines 65-113) pass the same `seed` on both requests, so the comparison is between the same draw with and without the centroid.

**New tests:**
- **Diversity.** 10 refreshes of one seed at limit=8, with no `seed`. The mean pairwise Jaccard overlap of the 10 pages is below 0.5. Every returned row belongs to the seed's pool at or above `SIMILAR_VIDEO_TAIL_MIN_SCORE`. The same request repeated with a fixed `seed` returns identical pages, which is the control.
- **Fallback.** A seed whose cached filtered pool is below `SIMILAR_VIDEO_TARGET_MIN_POOL` (the "linux" and "cooking" seeds are 17-19 today) returns at least 48 distinct rows at limit=48, with no duplicates by `(video_uuid, instance_domain)` or `video_id::instance_domain`. The fallback must not change the similarity cache entry for that seed. Use the `debug`/log evidence or a before/after cache read, whichever the design exposes.
- **Likes vs no likes.** The same seed with five likes and without likes both diversify across refreshes (overlap below the same threshold). With likes, every row's source similarity stays at or above `SIMILAR_VIDEO_TAIL_MIN_SCORE`.
- **Isolation.** A home request and a search request behave as before the change. The index's nprobe after an up-next request that ran the fallback equals `DEFAULT_NPROBE`.
- **Config.** The new constants exist with the stated defaults, and the Engine logs them at startup.

Live-Engine test files run each in their own `validate_tests.py` invocation, because of the shared per-IP rate limit. Other size-sensitive files must stay green: `tests/active/test_blocks.py` (`_deep_seed`, full 8-row pages) and `tests/active/test_profiles.py` (keyed up-next). Their pools only grow.

### Constraints

- Smallest change that works: no new dependency (numpy is already imported by the handler), no new module unless the design shows one is needed, and no new interface with a single implementation.
- New code matches the style of the file it lands in, with no softwrap.
- `engine/server/data/ann.py` is the single place that runs the ANN search for the fallback. It keeps today's rowid ids, so plan 17 can migrate it in one place.
- The home feed's candidate pools, ranking and caches are unchanged.

### Baseline suite state

The pre-build suite exited 0 (baseline variant: false). Only `test_search_fusion.py` was selected (10 passed); the other 22 groups were unchanged and not rerun.

### Out of scope

- Changing the precompute `--top-k`, the updater and dataset-build args, or rebuilding `similarity-cache.db`.
- Changing `DEFAULT_SIMILARITY_MAX_PER_AUTHOR` or adding an up-next-specific per-author cap.
- The home feed, the random feed, raw-vector search and search.
- Issue 08 (stable ANN ids).
- Client backend and frontend changes, including forwarding `seed`, and the video page's `limit=8`.
- Issues 11 (fast similars response) and 12 (similars on scroll).

### Acceptance criteria

- [ ] The new `SIMILAR_VIDEO_*` constants exist in `server_config.py` with the stated defaults and are logged once at Engine startup.
- [ ] An up-next seed whose cached pool is short gets a pool of at least `SIMILAR_VIDEO_TARGET_MIN_POOL` rows through bounded nprobe/search_limit steps, with a floor-then-tail fill. The cache is not rewritten, and the shared index's nprobe is restored.
- [ ] Pools are strictly deduplicated. Seed, per-author, error, exclude and moderation filters and the dislike penalty still apply.
- [ ] 10 refreshes of one seed have a mean pairwise Jaccard below 0.5, with every row at or above the tail floor. A fixed `seed` reproduces a page.
- [ ] With likes, personalization uses alpha 0.7 / beta 0.3 on the top-M window before sampling. Without likes, sampling runs on the source pool.
- [ ] Each up-next request logs its initial pool, fallback steps, final pool, sampling mode and unique rows returned.
- [ ] The rewritten and new tests pass, and the rest of `tests/active` stays green.
- [ ] Home, random, raw-vector and search behaviour is unchanged.

## High-level plan

### Approach

The change touches five existing files and adds no module: `server_config.py`, `server.py`, `data/ann.py`, `data/similarity_candidates.py` and `handlers/similar.py`. There is also a small stamp in `recommendations/related_personalization.py`. Home callers keep calling `get_similar_candidates` exactly as they do today. Up-next gets a separate function beside it, and the only thing the two share is private helpers.

**R1 config.** The nine `SIMILAR_VIDEO_*` constants go into `server_config.py` next to the other similarity knobs (`DEFAULT_SIMILARITY_SEARCH_LIMIT` and its neighbours), each with a one-line `#` comment. `SIMILAR_VIDEO_TARGET_MIN_POOL` is written as `BATCH_SIZE`, so the two cannot drift apart. Its value is 48 today. `RELATED_VIDEOS_PERSONALIZATION` changes to alpha 0.7 / beta 0.3 (R5). `server.py` logs all nine values in one line right after `set_nprobe(index, DEFAULT_NPROBE)`, with a stable prefix the config test can find in the Engine log that the `engine` fixture writes. `DEFAULT_NPROBE`, `DEFAULT_SIMILARITY_SEARCH_LIMIT` and `DEFAULT_SIMILAR_PER_LIKE` are not touched.

**R2 fallback, ANN half (`data/ann.py`).** `set_nprobe` moves from `server.py` into `ann.py`, and `server.py` imports it, so every nprobe write on the shared index lives in the one file plan 17 will migrate. It splits into a quiet setter, a reader (both through `faiss.extract_index_ivf`, as today) and the existing logged wrapper that startup uses. A new function next to `compute_similar_items` takes the server, the seed, an nprobe, a search_limit and a score floor. Under a single `server.index_lock` hold it:
- reads the current nprobe;
- sets the requested one;
- searches;
- restores the previous value in a `finally`.

Home, search and raw-vector searches take the same lock, so they can never see the raised value. The function then drops the seed's rowid, non-positive ids and every hit below the floor, before it fetches metadata. It fetches metadata only for the hits that survive and returns `{video_id, instance_domain, score}` entries in score order. It applies no per-author cap: the cap is applied once, over the merged pool, in `_build_rows`. The ids stay today's rowids.

**R2 fallback, pool half (`data/similarity_candidates.py`).** A new up-next function returns the rows plus a small stats dict for the log line. The steps:
1. Read the cache with the existing `_read_cache`. It never calls `_write_cache` or `_compute_candidates`.
2. Pass the entries through `_build_rows` with the pool cap `SIMILAR_VIDEO_TOP_K`. Then drop:
   - rows whose `similarity_score`/raw score is below `SIMILAR_VIDEO_TAIL_MIN_SCORE` (the operator chose to floor cached rows too, on up-next only);
   - the request's `exclude` keys, passed in by the handler;
   - rows removed by `apply_serving_moderation_filters`.
   The result is the initial pool.
3. If the initial pool is below target, or the cache had no entry (including `refresh_cache=1`, which skips the read), step through the fallback:
   - nprobe/search_limit go (32, 5000) → (64, 10000) → (128, 20000), each clamped to the caps. That is at most three searches.
   - Each search asks ann.py for hits at or above the tail floor, which is one search per step.
   - Only the hits at or above `SIMILAR_VIDEO_MIN_SCORE` are merged with the cached entries. Duplicates by `like_key` are dropped and the cached copy wins.
   - The merged entries are sorted by score and rebuilt through `_build_rows` and the same filters.
   - Stepping stops at target, when both caps are reached, or when a step does not grow the pool.
4. If the pool is still short after the last step, the same final search result supplies the tail rows (0.25 to 0.35), which are merged and rebuilt once more. Their count is recorded.
5. Rows are strictly deduplicated by both `(video_uuid, instance_domain)` and `like_key` in a final pass. With the author cap at 1 this should already hold, but rows with no `channel_id` escape the cap.
6. The pool is cut to `SIMILAR_VIDEO_TOP_K` by score.

Each step's record carries the nprobe read back from the index after the restore, which gives the isolation test its evidence. `get_similar_candidates`, its total-miss compute-and-write, and `compute_similar_items` are byte-for-byte unchanged.

**R3 dedup and quality.**
- Seed exclusion, the per-author cap counted across the merged pool, `similarity_exclude_source_author` and the error threshold all come from `_build_rows`, applied to the merged entry list. So cached and fallback rows face one set of rules.
- Exclude and moderation are applied before the pool is counted, so the target counts servable rows. Exclude is applied after the author cap, as today, so an excluded row does not free its channel's slot.
- The dislike penalty still runs through `score_and_rank_list` in the handler, before the window is formed.
- `_respond_rows` runs moderation again on the page. That pass is idempotent and now a no-op.

**R4 diversity (`handlers/similar.py`).**
1. `_handle_seed_with_embedding` calls the up-next function in place of `get_similar_candidates` and runs `score_and_rank_list` with the dislike penalty, as today.
2. It takes the top M rows, with M = `SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR` × limit, capped at the pool size.
3. If likes are present, it reranks that window (R5).
4. If the window holds `limit` rows or fewer, all of them are returned. Otherwise it draws `limit` rows by weighted sampling without replacement, using the Efraimidis–Spirakis key: each row gets `u^(1/w)` and the `limit` largest keys win. `w` is the row's final score, clamped at zero. Every row with a positive weight can be drawn. Zero-weight rows are used only if the positive-weight rows cannot fill the page, and then in rank order.
5. The page is sorted by final score, descending.

The draw uses numpy, which the handler already imports:
- Without a `seed` query parameter, `u` comes from a fresh `np.random.default_rng()` each request.
- With a `seed` (parsed by the existing `_parse_non_negative_int`, and ignored as random mode if invalid), each row's `u` is derived from a hash of the seed and the row's `like_key`, so it is tied to the row and not to its position.

As a result, the same seed with the same pool gives the same page. The same seed with a changed weight, such as a dislike centroid, gives a coupled draw: only the rows whose weight changed move. That is what `test_dislike_profile`'s paired comparison needs. Exclude paging works because excluded rows never reach the pool.

**R5 likes.** When personalization is enabled and likes are present, `rerank_related_videos` runs on the window. It already returns the list unchanged when there are no likes or no embeddings. To let likes shape the draw, it also stamps its computed final score on each candidate under a new key, which is additive: the pool and the order it already produces are unchanged. The handler uses that key as the weight and the page order when it is present, otherwise the ranked `score`. "Likes reranked" in the log means the key was present. Without likes, the same window-and-draw runs on the source pool. Profile selection is untouched.

**R6 log.** The handler writes one `[similar-server][<id>] upnext_pool …` line. It carries:
- the initial pool size;
- the steps as `nprobe/search_limit→pool` triples, or `none`;
- the restored nprobe;
- the final pool size and the tail count;
- `sampling=random|seeded`;
- `window=M` and `likes_rerank=yes|no`;
- `returned=<unique count>`.

The existing `related_entries`, timing and `done` lines stay.

**R7 tests.**
- In `test_similar.py`, the exclude test is rewritten to assert: full page, none of the excluded keys, and every row inside a deep reference pool (a `limit=96` request with a fixed `seed`). The docstring bullet and the `UPNEXT_SEED_QUERIES` comment are updated.
- `test_dislike_profile.py` sends the same `seed` on each pair of requests.
- New tests:
  - diversity: 10 draws with a Jaccard below 0.5, rows at or above the floor via the `debug` `similarity_score`, and a seeded control;
  - fallback: `limit=48` gets at least 48 unique rows, and a before/after read of the seed's entry in `similarity-cache.db` shows no change;
  - likes/no-likes;
  - isolation: home and search are unchanged, and the log line's restored nprobe equals `DEFAULT_NPROBE`;
  - config: constants read the way `_default_limit` reads `BATCH_SIZE`, and the startup line is found in the Engine log.
- Each live-Engine file runs in its own `validate_tests.py` invocation.

### Alternatives considered

- **Raising the precompute top-k and rebuilding the cache** would remove the live search. Rejected here because it is out of scope and is the named upgrade path.
- **Per-call FAISS search parameters (`SearchParametersIVF`)** would avoid mutating the shared index. Rejected because R2 prescribes set-and-restore under `index_lock`, and nested params through wrapper indexes (IDMap, PreTransform) are fragile across faiss builds. Set-and-restore inside the one lock hold gives the same isolation.
- **A policy flag on `get_similar_candidates`** would mean fewer functions. Rejected because it would thread up-next-only branches (floors, stepping, no write, stats) through the function every home layer calls. A separate function makes "home unchanged" true by construction.
- **Accumulating hits across steps** would save nothing. Each larger step is effectively a superset of the smaller one, so the latest step's hits replace the previous ones.
- **`numpy.Generator.choice(p=…, replace=False)`** would be simpler. Rejected because its draw depends on row position and cannot be coupled across a weight change, which breaks the seeded dislike comparison.
- **Top-M shuffle without weights** is not similarity-weighted, so it fails R4.
- **Rank-based weights from the rerank order** would avoid touching `related_personalization.py`. Rejected because they throw away the score gaps that likes create. The additive stamp is one line.
- **Leaving `set_nprobe` in `server.py` and duplicating it in `ann.py`** would leave two copies of the IVF-extraction logic. Moving it keeps plan 17's surface in one file.

### Gotchas and risks

- **Effectively every seed runs the fallback.** The cache holds at most 20 entries and the target is 48, so nearly every precomputed seed pays up to three live ANN searches, up to k=20000 at nprobe 128, on every up-next request. `index_lock` is held for each search, so concurrent home, search and raw-vector requests queue behind it. Issue 11 exists for this latency, and raising the precompute top-k removes it.
- **Two metadata fetches per step.** Fallback hits get two metadata fetches (rowid → meta in `ann.py`, then by id in `_build_rows`), the second under `db_lock`, as `compute_similar_items` already does. The floor filter before the first fetch keeps this bounded, but a dense cluster can still yield thousands of rows at or above 0.25.
- **Some pools stay short.** A seed in a single-channel or isolated cluster may still end below 48 after the tail. The fallback returns what it has and never goes under 0.25. The fallback test must use seeds known to fill: linux and cooking.
- **Score comparability.** Cached scores come from nprobe 16 and fallback scores from nprobe 32+. For a flat IVF index the pair score is identical. For a PQ index it would be approximate, and the cached copy wins on duplicates.
- **Merged author cap.** Because the per-author cap runs over the merged, score-sorted pool, a higher-scoring fallback row can displace a cached row from the same channel.
- **Weak weighting.** Linear weights on scores that sit around 0.5–0.9 make the draw close to uniform inside the window. Relevance is protected by the top-M cut and the floors, not by the weights.
- **Dislike test is statistical.** With seeded coupling and a score-ordered page, the penalized rows still sink on the page, but it now depends on a draw and not on a fixed order.
- **Double moderation.** Moderation now runs twice per up-next request. The second pass is on at most 96 rows.
- **Bad `seed` values.** A non-integer `seed` is silently treated as random mode, not answered with a 400.

### Tradeoffs the operator is asked to accept

- **Named simplification: live ANN on each short-pool request.** Ceiling: up-next latency and `index_lock` contention grow with index size, and today that means nearly every up-next request. Upgrade path: raise the precompute `--top-k` and rebuild `similarity-cache.db` on main.
- **Named simplification: linear score weights with no temperature constant.** Ceiling: only mild preference for the best rows inside the window. Upgrade path: a `SIMILAR_VIDEO_SAMPLE_TEMPERATURE` exponent on the weights.
- **Floored cache rows.** Up-next drops cached rows below 0.25, as the operator chose. A cached pool can shrink, and the fallback then refills it.
- **`refresh_cache=1` on up-next** no longer rewrites the cache. It forces the fallback path instead, because up-next never writes.
- **Non-deterministic pages.** Up-next pages are no longer stable for a given seed without `seed`. Anything that compared plain pages, such as tests or debugging habits, must pass `seed`.

## Impacts


<impacts>
<impact path="engine/server/api/server_config.py" element="new SIMILAR_VIDEO_* block (9 constants) beside DEFAULT_SIMILARITY_SEARCH_LIMIT (line 354) / DEFAULT_SIMILARITY_MAX_PER_AUTHOR (356)">
**What changes.** Nine module-level constants are added, each with a one-line `#` comment in the file's style: `SIMILAR_VIDEO_SEARCH_LIMIT = 5000`, `SIMILAR_VIDEO_TOP_K = 300`, `SIMILAR_VIDEO_NPROBE = 32`, `SIMILAR_VIDEO_TARGET_MIN_POOL = BATCH_SIZE`, `SIMILAR_VIDEO_MAX_NPROBE = 128`, `SIMILAR_VIDEO_MAX_SEARCH_LIMIT = 20000`, `SIMILAR_VIDEO_MIN_SCORE = 0.35`, `SIMILAR_VIDEO_TAIL_MIN_SCORE = 0.25` and `SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR = 4`.

**Ordering.** `BATCH_SIZE` is defined at line 310 (`RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"]` = 48). The planned spot near line 354 is below it, so it resolves. Placed above 310, it raises NameError on import.

**What depends on it.**
- `server.py`, for the startup line.
- `handlers/similar.py`, which already imports from `server_config` (lines 46-65). It is the natural reader, and it passes the values down.
- No module under `engine/server/data/` imports `server_config` today. `ann.py` and `similarity_candidates.py` read `server.*` attributes via `getattr`. Importing `server_config` from `data/` would add a new dependency direction, so pass the values as arguments.
- The new config test, which reads the file the way `_default_limit` does (`tests/active/test_similar.py:71-76`).

**Regression risk: low.** `tests/active/test_server_config.py:49` runs a bare `import server_config` under `sys.executable`, which has no numpy, so the block must stay pure Python. `.un/skills/devsecops/config.json` maps this file to test_dislike_profile, test_similar, test_server, test_server_config and test_internal_events, so editing it reselects all five.
</impact>
<impact path="engine/server/api/server_config.py" element="RELATED_VIDEOS_PERSONALIZATION (lines 312-322) and its comment block">
**What changes.**
- alpha goes from 0.2 to 0.7 and beta from 0.8 to 0.3.
- The comment at 313 ("toggles re-ranking within the existing similar-videos pool") goes stale, because the rerank now runs on the top-M window before the draw and its score becomes the draw weight. Reword it.

**What depends on it.**
- `server.py:416-425` builds `RelatedPersonalizationDeps` from `alpha`, `beta` and `max_likes`.
- `server.py:449` passes `enabled` as `related_personalization_enabled`.
- The only consumer is `rerank_related_videos`, via `handlers/similar.py:814-824`.

**Regression risk: medium, behavioural.** Liked up-next ordering moves from like-dominated to seed-dominated. The dislike arithmetic in `related_personalization.py:82-83` stays consistent: `score` already carries alpha × the penalty once scaled, and `(1 - alpha) * penalty` restores the rest.
</impact>
<impact path="engine/server/api/server.py" element="set_nprobe (lines 185-204) removed; import from data.ann; call at line 357">
**What changes.**
- The body moves to `data/ann.py`, and `server.py` imports the logged wrapper. The call at 357, `set_nprobe(index, DEFAULT_NPROBE)`, stays.
- The log text `[similar-server] ann_nprobe_configured=%d index_type=%s ivf_type=%s` should stay byte-identical. No test greps it.

**Still needed here.**
- `server.py` keeps its own `import faiss` (lines 117-122). It is still used by `faiss.read_index` (356) and by the `faiss.Index` annotation in `SimilarServer.__init__` (216), so that import must not be removed as "now unused".

**What depends on it.**
- Line 357 is the only call site (grep).
- `engine/server/db/jobs/precompute-similar-ann.py:110-131` holds a duplicate `set_nprobe`, called at 431. "Every nprobe write in one file" is therefore true only for the Engine process.

**Regression risk: low.** A broken import in `data.ann` fails `test_server_config.py:57` (`server.py --help` under ENGINE_PY) and every live-Engine fixture start.
</impact>
<impact path="engine/server/api/server.py" element="main(): from server_config import list (25-73) and a new startup log line right after line 357">
**What changes.**
- The nine `SIMILAR_VIDEO_*` names are added to the import.
- One `logging.info` line with a stable prefix follows `set_nprobe(index, DEFAULT_NPROBE)`.

**What depends on it.**
- The config test finds the line in the Engine log. The `engine` fixture writes stdout and stderr to `log_path` (`tests/active/conftest.py:107-108,123`) and exposes it only as `ClientBackend(..., log_path)`, the second constructor arg (line 125).
- Log records are JSON with `ensure_ascii=True` (`logging_profiles.py:226`), so the test must parse `message`. The line should use ASCII `key=value` tokens, which `_extract_fields` (108-124) then puts into `context`.
- An unmatched `[similar-server] ...` line gets `verbose` only, which is fine under the default profile.

**Regression risk: low.** Editing `server.py` reselects test_server_config, test_internal_events and test_random_cache.
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer.__init__ (209-283) and positional construction in main() (430-460)">
**What changes.** Nothing, if the handler reads the constants from `server_config` and passes them down.

**If the design hangs them on `SimilarServer` instead:** `main()` passes every argument positionally, so each new parameter needs care. The `server.embeddings_model = ...` post-construction pattern (line 463) is the least invasive.

**What depends on it.** `index_lock` (279) is the lock the fallback must hold for the whole set, search and restore.

**Regression risk: low.**
</impact>
<impact path="engine/server/data/ann.py" element="new nprobe helpers (quiet setter, reader, logged wrapper) moved from server.py">
**What changes.** Three functions are added, all going through `faiss.extract_index_ivf`.

**Index shape.**
- `engine/server/db/jobs/build-ann-index.py:110-113` builds `faiss.IndexIDMap2(faiss.IndexIVFPQ(...))`.
- The Engine opens it mmap read-only (`server.py:356`).
- `nprobe` lives on the IVF object returned by `extract_index_ivf`. The wrapper's `hasattr(index, "nprobe")` and `index.index.nprobe` branches (`server.py:195-198`) are probably no-ops for IndexIDMap2. I have not run this; it is inferred from the SWIG types.

**Constraints.**
- The reader must read `extract_index_ivf(index).nprobe`, and the restore must write that same object. Otherwise the restore can write None or leave 128 behind.
- `compute_similar_items` logs `getattr(server.index, "nprobe", None)` (ann.py:32), which is probably None for this wrapper. Do not reuse that expression for the restored-nprobe evidence.
- `ann.py` already imports `faiss` behind the same SystemExit guard (10-15), as well as `logging`.

**What depends on it.** `server.py:357` and the new fallback search.

**Regression risk: medium.** A reader and setter aimed at different objects pass a read-back check while the shared IVF stays at the raised nprobe, which slows home, search and raw-vector for good.
</impact>
<impact path="engine/server/data/ann.py" element="new fallback search function (server, seed, nprobe, search_limit, floor) beside compute_similar_items (21-85)">
**What changes.** Inside one `server.index_lock` hold it reads nprobe, sets the requested value, runs `server.index.search(vector.reshape(1, -1), search_limit)` and restores in `finally`. After the lock it:
- drops ids ≤ 0 (FAISS pads with -1), `seed["rowid"]` and scores below `floor`;
- runs `fetch_metadata` under `db_lock` with `error_threshold=getattr(server, "video_error_threshold", None)`;
- returns `{video_id, instance_domain, score}` in score order, with no author cap.

It must mirror `compute_similar_items` lines 23-25 by normalising the vector when `server.normalize_queries` is set (DEFAULT_NORMALIZE_QUERIES=False). The up-next seed carries `rowid`, `embedding`, top-level `instance_domain`/`channel_id` and `meta.video_id`, but no top-level `video_id` (`data/embeddings.py:87-99`).

**Hook to consider.** `similarity_candidates._compute_candidates` honours a `server.compute_similar_items` override (146-152). The new function has no such hook, so a test stub server cannot stub it the same way.

**Score semantics.** IVFPQ scores are approximate inner products, so the 0.35 and 0.25 floors apply to the PQ approximation. Cached scores come from the same index at nprobe 16 (`precompute-similar-ann.py:299`), which makes them comparable but not identical to a live nprobe-32+ score.

**What it runs beside.** Other `index_lock` users (grep): `ann.py:36` (compute_similar_items), `handlers/similar.py:877` (raw-vector) and `data/search.py:185` (search's vector half).

**Regression risk: high for latency and contention.**
- Up to three searches, reaching k=20000 at nprobe 128, all under the global `index_lock`.
- `fetch_metadata` chunks at 900 rowids (`metadata.py:20`) under `db_lock`.
- The request deadline covers only `server.db` statements. The FAISS search and the lock wait are not interruptible.
- A deadline trip in the later `server.db` work raises `sqlite3.OperationalError`, which `_handle_similar`'s `except Exception` (`handlers/similar.py:1024-1026`) turns into a 500. It does not become the 503 mapped in `do_POST` (365-373).
- Plan 17 (`docs/project/plans/17-stable-ann-ids.md:19`) must migrate this function too.
</impact>
<impact path="engine/server/data/ann.py" element="compute_similar_items (21-85) and search_index (88-114)">
**What changes.** Nothing; the plan keeps them byte-for-byte.

**What depends on them.**
- `similarity_candidates._compute_candidates` (home callers on a total miss).
- `search_index`: `handlers/similar.py:878` and `data/search.py:186`.

**Regression risk: low.** Both see `DEFAULT_NPROBE` = 24 only if the restore is correct.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="new up-next pool function (rows + stats) beside get_similar_candidates">
**What changes.** A new public function. It resolves the source with `_source_from_seed` (217-235), which falls back to `seed["meta"]["video_id"]`, then:
1. `_read_cache`;
2. `_build_rows` with limit `SIMILAR_VIDEO_TOP_K`;
3. the tail floor on the raw `score`;
4. the exclude keys, passed in;
5. `apply_serving_moderation_filters`, a new import from `data.serving_moderation`, which is fine inside `data/`;
6. the fallback steps via the new ann function;
7. merge by `like_key` (the cached copy wins), sort by score descending, then rebuild and re-filter;
8. the tail;
9. a final dedup on `(video_uuid, instance_domain)` and `like_key`;
10. a cut to TOP_K.

**Cache-read pitfalls.**
- **Policy.** `read_cached_similarities` (`similarity_cache_manager.py:42-70`) returns [] when `policy.refresh` is set, when any entry has a None score, and, under `require_full`, whenever `len(cached) != limit`. The function must build `SimilarityCachePolicy(refresh=refresh_cache, require_full=False, allow_write=False)` explicitly. The handler's `getattr(self.server, "similarity_require_full_cache", True)` (similar.py:767-769) defaults to True on stubs, and a precomputed 20-row entry would then read as a miss.
- **Read limit.** `fetch_cached_similarities` applies `LIMIT ?` (`similarity_cache.py:56-64`). Runtime-written entries (from `get_similar_candidates` via home, or from today's up-next) hold up to `SIMILAR_PER_LIKE` = 1000 rows. Reading with only 300 truncates them; still acceptable because `_build_rows` caps at 300 anyway, but the row-order author cap means fewer than 300 survive.
- **Server-wide refresh.** `refresh_cache` is also true when the server-wide `DEFAULT_SIMILARITY_CACHE_REFRESH` is set (handlers/similar.py:929-932). Every up-next request would then skip the cache and run the fallback.

**Order and logs.**
- `_build_rows` walks entries in the order given, applies the author cap in that order, and stops at `limit` (194-210). Merged lists must be score-sorted before each rebuild, or a lower-score cached row takes a channel's slot.
- `_build_rows` logs `[similar-server] candidates=` on every call, a focused event (`logging_profiles.py:60-64`), so it logs up to five times per request.

**Floor input.** `_build_rows` sets `row["score"]` to the raw cache/ANN score (line 208). `score_candidate` later copies it into `similarity_score` (clamped to [0,1]) and overwrites `score` (`scoring.py:51-62`), so the floor must run before scoring.

**Empty seed.** It must return empty rows and stats when the seed has no embedding, and keep the `vector`→`embedding` fallback of `get_similar_candidates` (54-60).

**Exclude.** It must accept the request's exclude set, since `fetch_request_excluded_keys` lives in `api/request_context.py:30` and `data/` must not import `api/`.

**What depends on it.** Only `handlers/similar.py::_handle_seed_with_embedding`.

**Regression risk: medium-high.** A wrong policy, limit or order silently shrinks every up-next pool and forces needless live searches.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="get_similar_candidates (37-105), private helpers _read_cache/_write_cache/_compute_candidates/_build_rows/_source_from_seed/_author_key, module comment (5-9)">
**What changes.** No behaviour change. The helpers gain a second caller, so any signature change to `_build_rows` must keep `get_similar_candidates` identical.

**Behaviour lost: up-next no longer warms the cache.** Today `_handle_seed_with_embedding` calls `get_similar_candidates` with `allow_cache_write=True` (default) and `similar_per_like` = 1000. On a total miss (78-91) that computes and writes up to 1000 rows. After the change, a seed first seen on up-next is never cached. The first home request that has it as a like pays the compute and write instead (`cached_similar_from_likes.py:76-84,106`).

**Module comment.** The comment at 5-9 ("a single entry point ... centralizes cache policy, ANN fallback") becomes inaccurate.

**What depends on it.**
- `recommendations/sources/cached_similar_from_likes.py:106`;
- `ann_similar_from_likes.py:74`;
- wiring at `server.py:92,393` and `builder.py:53,119,129`.

**Regression risk: low** while the helpers stay as they are.
</impact>
<impact path="engine/server/data/similarity_cache_manager.py" element="SimilarityCachePolicy, read_cached_similarities (26-70), should_write_cache/write_cache (73-96)">
**What changes.** Nothing. It decides what the up-next read sees.

**Constraints.**
- With `refresh=True`, `read_cached_similarities` returns [] (line 49). That is the "refresh_cache=1 forces fallback" path.
- `should_write_cache` returns True under `refresh` (81-82), so `write_cache` must not be reachable from up-next.

**Regression risk: none to the file.**
</impact>
<impact path="engine/server/data/similarity_cache.py" element="fetch_cached_similarities (49-76)">
**What changes.** Nothing.

**Why it matters.**
- It orders by `rank ASC` with `LIMIT`, and swallows `sqlite3.Error` into [], so a locked or broken cache silently reads as a miss and triggers the fallback.
- `similarity_items` is keyed by `(source_video_id, source_instance_domain)`. The fallback test's before/after read queries this table and should open the db read-only (`?mode=ro`), because `similarity-cache.db` is symlinked and shared across worktrees (`docs/project/issues/plan.md:147`).

**Regression risk: none.**
</impact>
<impact path="engine/server/data/serving_moderation.py" element="apply_serving_moderation_filters (14-48)">
**What changes.** Nothing in the file. It gains calls from `data/similarity_candidates.py`, once per pool build or rebuild, on top of `_respond_rows` (`handlers/similar.py:668-670`) and search (556-560).

**Why it matters.** Each call takes `server.db_lock` and queries `server.db`, so it counts against the deadline. It logs only when something was filtered, with `request_id`, so the data layer should receive the request id too if the log line is wanted.

**Regression risk: low-medium.** It adds four to five passes per up-next request under the global lock.
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata (rowids, chunks of 900) and fetch_metadata_by_ids (pairs)">
**What changes.** Nothing. Both now take much larger inputs on nearly every up-next request:
- rowids from up to 20000 floored hits;
- the merged entries on every `_build_rows` rebuild.

**Why it matters.** The error threshold applies on both paths. Both run under `db_lock` and the progress-handler deadline.

**Regression risk: medium for performance.**
</impact>
<impact path="engine/server/data/db.py" element="statement_deadline and connect_similarity_db">
**What changes.** Nothing.

**Why it matters.** Only `server.db` and `search_db` carry the progress-handler deadline. FAISS search, the `index_lock` wait and the `similarity_db` read are unbounded. A request that spends its budget in FAISS fails at its next `server.db` statement, after the work is done.

**Regression risk: none to the file.** It shapes the fallback's failure mode.
</impact>
<impact path="engine/server/data/search.py" element="vector_candidates: index_lock at line 185, search_index at 186">
**What changes.** Nothing.

**Why it matters.**
- Search now queues behind up-next fallbacks on `index_lock`.
- It relies on the IVF being at `DEFAULT_NPROBE`.
- The isolation test asserts that search is unchanged.

**Regression risk: low for correctness, medium for latency.**
</impact>
<impact path="engine/server/data/embeddings.py" element="resolve_seed (58-99)">
**What changes.** Nothing.

**Why it matters.** It fixes the up-next seed shape the new functions consume:
- `rowid` and `embedding` (used for the ANN search and for seed-rowid exclusion);
- `instance_domain` and `channel_id` at the top level;
- `meta.video_id`, and no top-level `video_id`, which is why `_source_from_seed`'s meta fallback matters.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_seed_with_embedding (742-851)">
**What changes.**
1. Line 774 calls the new up-next function in place of `get_similar_candidates(self.server, seed, similar_per_like, policy)`. The `SimilarityCandidatesPolicy` built at 764-770 and `similar_per_like` (771-772) no longer feed it.
2. The exclude filter at 793-796 moves into the data layer, via the passed-in `fetch_request_excluded_keys()`.
3. `score_and_rank_list` with the `penalise` adjust stays (780-792).
4. The top-M window is formed, with M = factor × limit capped at the pool size.
5. The rerank moves from after `rows[:limit]` (813-830) onto the window.
6. The E–S draw runs, then the page is sorted by final score.
7. The new `upnext_pool` line is logged.
8. `related_entries` (800-805), timing (806-812) and `done` (via `_respond_rows`) stay.

**Row stamp.** `debug_profile` (798-799) must still land on every served row: `tests/active/test_profiles.py:274-279` reads `rows[0].debug.profile`.

**Signature.** It needs a parameter for the parsed draw seed. The name `seed` is already the resolved seed dict, so use e.g. `draw_seed`.

**Seeded hash.** It must be stable across processes (hashlib or zlib.crc32 of seed + `like_key`). Python's `hash()` of a str is salted per process.

**Weights.**
- After scoring, `score` is the upnext blend: `similarity 1.0 + freshness 0.1 + popularity 0.1` (`server_config.py:208,270`), minus any dislike penalty. It can be ≤ 0, so it must be clamped.
- The rerank stamp can be negative too, through its `- (1 - alpha) * penalty` term.

**Likes gate.**
- `user_id` is always truthy (`http_utils.py:11-14`, default "local-user").
- `rerank_related_videos` returns early without likes, so "likes_rerank" must be read from the stamp's presence.
- Profile selection (`resolve_profile_config_with_guest`, 756-758) is unchanged.

**Seeded coupling limit.** The window is the top M after the penalty, so a centroid can move rows into or out of the window as well as reweight them. "Only rows whose weight changed move" is approximate.

**Short page.**
- The target is a fixed 48, while the Engine accepts limit up to 96 (918-920).
- A pool of 48-95 with limit 96 returns the whole pool, short and undrawn.
- A pool equal to the limit returns everything, so the page is deterministic.

**Empty pool.** When the floors leave nothing, the existing empty-200 branch (841-851) answers with `seed.get("meta")` and no `mode`.

**Cost.** `apply_dislike_penalty` fetches embeddings for up to 300 pool rows under `db_lock` (`dislike_profile.py:63-64`), up from about 20. `rerank_related_videos` fetches embeddings for up to M rows.

**What depends on it.**
- POST `/recommendations?id=`, POST `/videos/similar`, GET `/videos/{id}/similar`. The GET path sets no request-context likes or excludes.
- Through the gateway: the video page (`client/frontend/src/pages/video-page/index.ts:248-251`, limit 8) and `pages/videos/index.ts:211-226` (createFeedPager).

**Regression risk: high.** Unseeded pages become random, and the gateway cannot pass `seed`.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_similar (912-1028): new `seed` query parse and pass-through; imports (28-65)">
**What changes.**
- `params.get("seed")` is parsed with `_parse_non_negative_int` (1047-1055); None means random mode. It is passed to `_handle_seed_with_embedding`, whose only call site is line 992.
- Imports: add the new data function, the `SIMILAR_VIDEO_*` names (window factor at least) and possibly `hashlib`.
- `get_similar_candidates` and `SimilarityCandidatesPolicy` (line 38) become unused here and should be removed.

**What depends on it.**
- The child-process tests in `tests/active/test_similar.py` (206-554) run `_handle_similar` on `SimpleNamespace` stub servers with only a few attributes, along the random, debug and error branches. The parse must not touch new server attributes before the random branch (953-955).
- `engine/server/api/tests/test_recommendations_likes_limit.py:19` imports `handlers.similar` directly with a `SimpleNamespace(use_client_likes=True)` stub. It is outside `tests/active` and `config.json`, so any import breakage there goes unseen.

**Status codes.** The broad `except Exception` (1024) turns fallback deadline trips into a 500.

**Regression risk: medium.**
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_respond_rows (659-691), maybe_attach_debug (131-139), stable_video_rows (121-128)">
**What changes.** No code. Moderation re-runs on the page and is idempotent.

**Debug.** `attach_debug_info` aligns by index (`recommendations/debug.py:14-15`), so it must receive the final page, which `_respond_rows` passes (668-673). Debug exposes `score`, `similarity_score` (the clamped PQ score) and `profile`. The diversity and floor tests can use `similarity_score` as evidence (`RECOMMENDATIONS_DEBUG=1` in the fixture, `conftest.py:110`).

**Response shape.** `stable_video_rows` whitelists fields, so a rerank stamp cannot leak into the response.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_vector_search (853-910) and _handle_home (710-740)">
**What changes.** Nothing.

**Why it matters.** Raw-vector search takes `index_lock` (877). Home's like-seeded layers can reach `compute_similar_items` on a miss. Both inherit the contention and rely on the restore.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/related_personalization.py" element="rerank_related_videos (43-87) additive stamp; module comment (5-22)">
**What changes.**
- A new key (e.g. `personalized_score`) is written on each candidate in the loop (after the `final_score` computation at 83).
- The order and the pool are unchanged.
- The early returns (50-65) leave no stamp.
- The module comment ("post-processing", "only reorders the existing list", the formula) should mention the stamp and the window.

**Behaviour.** `base_score` is the post-scoring blended `score` (with freshness and popularity), not raw similarity. The stamp is therefore not a pure source similarity.

**What depends on it.** The handler uses the stamp as the draw weight and page order. `config.json:32` maps this file to test_dislike_profile.

**Regression risk: low.** It mutates per-request dicts only.
</impact>
<impact path="engine/server/api/recommendations/scoring.py" element="score_candidate (42-67), rank_scored_candidates (70-148), score_and_rank_list (151-177), _extract_similarity (180-195)">
**What changes.** Nothing.

**Why it matters.**
- `score_candidate` overwrites `score` and sets `similarity_score` (a clamped copy of the raw score). Any floor must run before it.
- `rank_scored_candidates` reads a top-level `explore` key, which the `upnext` and `guest_upnext` profiles lack (`server_config.py:204-305`, and `profile.py:42-43` returns the profile dict as-is). Ranking is therefore a plain score sort with no jitter.
- It stamps `debug_rank_*` and pool min/max over the whole pool.

**Regression risk: none.** The window and draw come after it.
</impact>
<impact path="engine/server/api/recommendations/debug.py" element="attach_debug_info (8-36)">
**What changes.** Optional additive keys, such as the rerank stamp and a cache/fallback/tail source tag. They would give the fallback and likes tests per-row evidence.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/dislike_profile.py" element="apply_dislike_penalty (47-77)">
**What changes.** Nothing.

**Why it matters.** It runs over the whole pool (up to 300), fetching embeddings under `db_lock`, and stamps `dislike_penalty`, which the rerank reads.

**Regression risk: low (performance).**
</impact>
<impact path="engine/server/api/logging_profiles.py" element="_EVENT_RULES (31-70), _extract_fields (108-124), JSON formatter (ensure_ascii at 226)">
**What changes.** Optional: a rule for `upnext_pool` if focused viewers should see it.

**Why it matters.**
- Tokens are split on whitespace and `=`. Step triples like `32/5000→40` are one token, and "→" becomes `\u2192` in the file. Prefer ASCII.
- The existing `[similar-server] candidates=` rule makes each `_build_rows` call a focused event.

**Regression risk: low.** Adding a rule reselects test_logging_profiles, test_similar and test_internal_events.
</impact>
<impact path="engine/server/api/recommendations/sources/cached_similar_from_likes.py" element="policy (76-84) and get_similar_candidates call (106-108)">
**What changes.** Nothing; it is a home caller.

**Why it matters.** It now pays the first compute and write for seeds that up-next used to warm, and it shares the helpers the new function reuses.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/sources/ann_similar_from_likes.py" element="get_similar_candidates call (74)">
**What changes.** Nothing.

**Why it matters.** On a miss it reaches `compute_similar_items` under `index_lock`, so it must never observe a raised nprobe.

**Regression risk: low.**
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="duplicate set_nprobe (110-131, call 431); --top-k 20 / --nprobe 16 defaults (298-299)">
**What changes.** Nothing; out of scope.

**Why it matters.**
- It is a second copy of the IVF setter, which plan 17 must still touch.
- Its top-k 20 is why cached pools are shallow and why the fallback runs for nearly every seed.
- Its nprobe 16 differs from the fallback's 32+, which bears on score comparability.

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/build-ann-index.py" element="index construction (110-113): IndexIDMap2(IndexIVFPQ)">
**What changes.** Nothing.

**Why it matters.**
- It fixes the object nprobe must be read from and written to (the IVF via `extract_index_ivf`).
- It makes every score a PQ approximation. A test that checks the floor with an exact cosine from `whitelist.db` (e.g. `conftest.cosine`) can disagree near 0.25/0.35, so use debug `similarity_score`.

**Regression risk: none to the file.** It matters for test design.
</impact>
<impact path="client/backend/server.py" element="PROXY_ALLOWED_QUERY_PARAMS (85-101), query-param rejection (419-423, 474-479), feed over-fetch FEED_PAGE_SIZE=48 / FEED_OVERFETCH_FACTOR=2 (69-70, 450-469)">
**What changes.** Nothing; Client changes are out of scope.

**Why it matters.**
- `/recommendations` and `/videos/similar` allow only `id, host, limit, random, debug, mode, user_id`. A gateway request carrying `seed` gets 400 "Unknown query parameter: seed", so no gateway-routed test or browser can reproduce a draw.
- A keyed request with blocks or dislikes asks the Engine for 2× the page (up to 96). The Engine then draws from a window of min(4×96, pool ≤ 300), and the Client trims.

**Regression risk: high for gateway-routed tests** (see below). The production contract holds.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="similar load (around 248-251): limit 8, no exclude, no seed">
**What changes.** Nothing in code.

**Behaviour.** Each load draws 8 of up to 32 and nearly always pays the fallback latency.

**Regression risk: low (intended).**
</impact>
<impact path="client/frontend/src/data/videos.ts" element="createFeedPager (37-70), MAX_FEED_EXCLUDE=500 (28), fetchSimilarVideosPayload (130+)">
**What changes.** Nothing.

**Why it matters.** The pager excludes the shown rows (the last 500, which covers a 300 pool) and stops on an empty batch. Up-next paging in `pages/videos/index.ts:211-226` now runs up to about 38 batches of 8 before it is exhausted, where today it runs about 3.

**Regression risk: low for production, high for `test_frontend_videos.py`.**
</impact>
<impact path="tests/active/test_similar.py" element="test_upnext_excluding_the_previous_page... (167-189), docstring bullet (13-15), UPNEXT_SEED_QUERIES comment (65-66)">
**What changes.** A rewrite that asserts:
- a full page;
- none of the excluded keys;
- rows from the seed's pool.

**What breaks today.** Line 174 (a plain page repeats) and line 179 (the limit=16 head equals the limit=8 page) break under random draws.

**Design note.** The planned `limit=96` seeded reference is itself a draw of 96 from a window of min(384, pool ≤ 300). Once the pool exceeds 96, a correctly drawn row can fall outside it, and the test goes flaky. 96 is the Engine maximum (918-920). Floor evidence via debug `similarity_score` is sounder. The docstring bullet and the "19 and 17 deep" comment must change.

**Regression risk: medium (test design).**
</impact>
<impact path="tests/active/test_similar.py" element="_rows('upnext') (79-94), identity test (97-107), 500-exclude test (192-203), child-process handler tests (206-554)">
**What changes.** No edit expected.
- The identity checks hold for drawn rows.
- The 500-exclude test needs non-empty rows only.
- The child stubs must survive the new `seed` parse, and fallback requests are slower.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_dislike_profile.py" element="_seed_and_pair (65-78), up-next test (101-113), home test (129-151), docstring (1-10)">
**What changes.** `_seed_and_pair`'s path gets a fixed `&seed=`, so the plain request and the dislike requests share a coupled draw. The home test (132) also calls `_seed_and_pair` and uses it only to pick d1 and d2 (cosine < 0.7 over 16 rows), which works with any draw.

**Statistical assertions.** They compare closeness over the leading 8 non-dislike rows (110-113). A centroid lowers penalised rows' scores, so they sink on the score-sorted page, and rows can also shift in or out of the M=64 window. Likely to hold, but no longer by construction.

**Regression risk: medium.**
</impact>
<impact path="tests/active/test_dislikes.py" element="test_a_disliked_video_is_absent... (130-145), test_a_profile_s_upnext_page_leans_away... (166-179), SEEDS comment (26-28)">
**What changes.** Not named by the plan, but it needs a rewrite. It goes through `unpublished_client` (the gateway), which refuses `seed`.

**What breaks.**
- `disliked = keyless[8]` is taken from one unseeded 16-row draw and asserted present on fresh keyless (144) and bystander (145) draws, 16 of a window of up to 64. It fails often.
- 175-179 compare closeness across independent unseeded draws, which is noise-dominated.
- The "19 and 18 rows" comment goes stale.

**Mapping gap.** `config.json:35-41` maps this file only to client files, so an Engine-only change does not reselect it.

**Regression risk: high.**
</impact>
<impact path="tests/active/test_blocks.py" element="_surface docstring (140-145), test_blocked_channel_and_account... (155-183), _deep_seed (186-191), test_an_upnext_page_stays_full... (194-208)">
**What changes.** The `/recommendations` and `/videos/similar` cases of `test_blocked_channel...` take targets from one unseeded 8-row keyless draw (162-164). They assert those targets reappear on fresh keyless (182) and bystander (183) draws, which fails or goes flaky. The `_surface` docstring "the same page on every call" becomes false.

**Still holds.** `_deep_seed` and the stays-full test (absence plus a full page) hold as pools grow.

**Mapping gap.** Not mapped to Engine files (`config.json:71-76`).

**Regression risk: high.**
</impact>
<impact path="tests/active/test_frontend_blocks.py" element="_seed_and_targets (94-102), test_a_channel_blocked_through_the_module... (105-124)">
**What changes.** Not in the plan; it needs a rewrite.

**What breaks.** `in_upnext = upnext[0]` comes from one keyless gateway draw of 8. The node runner fetches up-next again, and line 120 asserts that channel is on the fresh draw, which fails or goes flaky. Line 101's `from_search` (not on the first draw's channels) can also collide with the runner's later draw, which only matters for the search-side assertions if a channel coincides.

**Still holds.** The post-block assertions (122-124).

**Mapping gap.** Not mapped to Engine files (`config.json:77-83`).

**Regression risk: high.**
</impact>
<impact path="tests/active/test_frontend_videos.py" element="test_the_pager_s_batches_never_repeat... (82-104), _seed comment (75-76), docstring (1-12), MAX_BATCHES=6 (23)">
**What changes.** Not in the plan; it needs a rewrite.

**What breaks.**
- Line 87 asserts two plain fetches are equal, which fails under random draws.
- Line 101 needs an empty batch within 6 batches of 8. The linux pool becomes ≥ 48 (up to 300), so it fails deterministically.

**Still holds.** The no-repeat assertions.

**Mapping.** Mapped to `handlers/similar.py` (`config.json:66-70`), so it is reselected.

**Regression risk: high.**
</impact>
<impact path="tests/active/test_profiles.py" element="_upnext_profile (274-279), test_a_keyed_upnext_request... (282-300)">
**What changes.** No edit.

**Why it holds.** It asserts `rows[0].debug.profile` through the gateway, which allows `debug`. It holds while every served row carries `debug_profile` and the page is non-empty.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_server.py" element="EngineStub and live tests">
**What changes.** No edit expected. Grep finds no direct up-next request against the real Engine.

**Why listed.** It is reselected via `server_config.py` and `handlers/similar.py`.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_server_config.py" element="bare import of server_config (49) and server.py --help under ENGINE_PY (55-65)">
**What changes.** No edit.

**Why it matters.** It guards that both modules still import after the constants are added and `set_nprobe` moves.

**Regression risk: low.**
</impact>
<impact path="tests/active/conftest.py" element="engine fixture (105-145): log_path passed as ClientBackend's second arg; RECOMMENDATIONS_DEBUG=1">
**What changes.** Possibly an additive, clearly named accessor for the Engine log path, used by the config and isolation tests.

**Why it matters.**
- The fixture is session-scoped, so the startup line is present early.
- The subprocess writes buffered output, so poll briefly.
- Editing conftest reselects broadly.

**Rate limit.** 60 requests per 60 s per `ip:path` (`server_config.py:431-432`) is shared by every test in the session, so the new 10-draw tests eat that budget.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_upnext_diversity.py" element="new test module (working name): diversity, fallback, likes/no-likes, isolation, config">
**What changes.** New live-Engine tests, run in their own `validate_tests.py` invocation.

**Per test.**
- **Diversity:** 10 unseeded draws at limit 8 with Jaccard < 0.5, the floor checked through debug `similarity_score`, and a seeded control.
- **Fallback:** limit 48 gives ≥ 48 unique rows by both keys, plus a read-only before/after read of `similarity_items` for the seed.
- **Likes:** a body of `{"likes": [...]}` sent direct to the Engine, as in `test_similar.py:124-127`.
- **Isolation:** the restored nprobe from the `upnext_pool` line equals `DEFAULT_NPROBE` = 24. "Home and search unchanged" is checkable only as invariants.
- **Config:** constants via `spec_from_file_location`, and the startup line from the log.

**Unmapped.** Until `config.json` maps it, change-based selection will not pick it.

**Regression risk: medium (flakiness, rate-limit budget).**
</impact>
<impact path="engine/server/api/tests/test_recommendations_likes_limit.py" element="direct import of handlers.similar (19) with SimpleNamespace stub (29)">
**What changes.** Nothing, as long as the new imports in `handlers/similar.py` resolve.

**Why listed.** A second unittest tree, outside `tests/active` and `config.json`. Neither selection nor the full `tests/active` run will catch a break here.

**Regression risk: low.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (14-140)">
**What changes, at harvest.**
- Map the new test module to `data/ann.py`, `data/similarity_candidates.py`, `handlers/similar.py`, `server_config.py`, `server.py` and `related_personalization.py`.
- Add `data/ann.py` and `data/similarity_candidates.py` to test_similar and test_dislike_profile.

**Gap.** test_blocks, test_dislikes and test_frontend_blocks list no Engine file, yet break on Engine behaviour. Add `handlers/similar.py` to them, or run the full suite.

**Regression risk: low (config).** The gap hides regressions.
</impact>
</impacts>


## Documentation to update

- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md now describes how up-next is actually served: a pool that only reads the cache, the ANN fallback when the pool is short, a top-M window and a weighted random draw.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: I added an "Up-next Params" section to LAYER_PARAMS.md and a note that the Source Params govern only the home layers.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - updated: The diagram now shows up-next as its own branch, separate from the home layer pipeline, and the broken overview link is fixed.
- [x] `engine/server/README.md` - updated: Added a Notes bullet for the up-next `seed` query parameter, placed after the `debug=1` bullet.
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: added the up-next log lines, the fallback's load and timeout risk, and how `seed=<int>` reproduces a page.
- [x] `DATA_BUILD.md` - updated: Step 5 of DATA_BUILD.md now says that `--top-k 20` entries are too shallow for up-next, which fills the gap with a serve-time ANN fallback, and that raising `--top-k` and rebuilding the cache is the fix.
- [x] `docs/project/issues/09-similars-diversity.md` - updated: Issue 09 marked `Status: enhancement, complete` with a delivery comment. The move to `archive/` is still to do, because I have no tool that can move or delete files.
- [x] `docs/project/issues/11-fast-similars-response.md` - updated: Added a dated comment to issue 11 about the up-next latency that issue 09 introduced: live ANN fallback searches under `index_lock`, and larger per-request fetches.
- [x] `docs/project/issues/plan.md` - updated: Row 2a is now marked delivered with its full file list, and row 5a now names the `data/ann.py` functions that 08 must migrate.
- [x] `docs/project/plans/17-stable-ann-ids.md` - updated: Added `search_similar_above` and the relocated nprobe helpers to plan 17's list of rowid-keyed readers in `data/ann.py`.
- [x] `docs/project/issues/12-similars-on-scroll.md` - updated: Added a comment to issue 12: each up-next response is now a random draw, so paging on scroll has to exclude rows already shown, and no test covers the pager right now.
- [x] `docs/project/roadmap.md` - updated: Added a Delivered line for issue 09 and took `09` out of the open similarity sequence.
- [x] `docs/project/adr/0006-derived-ann-ids.md` - out of scope: The ADR decides the id scheme that plan 17 will introduce. This build keeps today's rowid ids, as the operator confirmed, and puts its one new ANN reader in `data/ann.py`, where plan 17 migrates it. `search_similar_above` drops ids ≤ 0, which matches decision 3. Nothing in the ADR is made false; the extra migration surface is recorded in plan 17.

## Implementation plan

## Draft 1: up-next pools, fallback and diversity (issue 09)

### Before the draft

- **The ladder placeholder was empty.** The step text holds a literal `{rat_tail_ladder}`, so no ladder was supplied. This draft is written against the high-level plan, the requirements and the impact inventory.
- **The plan's R7 is incomplete.** It does not name four gateway-routed tests that break under random draws: `test_blocks.py`, `test_dislikes.py`, `test_frontend_blocks.py` and `test_frontend_videos.py`. The gateway refuses `seed`, so they cannot be seeded. I asked the operator, who chose **pinning**: a test lists the seed's whole pool directly on the Engine, then sends gateway requests whose `exclude` leaves exactly the rows it chose. When the window is no larger than `limit`, every row is returned, so the page is deterministic and no Client change is needed. Section 7 drafts these four rewrites.
- **Where this draft departs from the settled plan (each is named where it happens):**
  - The floor runs on entries before `_build_rows`, not on rows after it. The result is the same, with fewer metadata lookups.
  - The cache is read with the handler's `similar_per_like`, which is today's read limit.
  - The `test_similar` exclude rewrite checks rows against the score floor (debug `similarity_score`), not against a `limit=96` seeded reference. The inventory flags that reference as flaky.
  - The empty-pool branch also writes the `upnext_pool` line.
  - Two shared test helpers are added to `conftest.py`.

### What has to be testable

| Behaviour | Evidence |
|---|---|
| Nine constants and their defaults; `TARGET_MIN_POOL == BATCH_SIZE` | Read `server_config.py` with `spec_from_file_location` |
| Constants logged at startup | The `[similar-server] upnext_config` line in the Engine log (`engine.db_path` holds the log path) |
| A short cached pool reaches ≥ 48 unique rows | `limit=48` returns 48 rows, distinct by `(video_uuid, instance_domain)` and by `like_key` |
| Cache not rewritten | Read-only before/after read of `similarity_sources` and `similarity_items` for the seed |
| nprobe restored | `restored_nprobe=24` on every `upnext_pool` line that has steps; search results identical before and after a fallback |
| Diversity | 10 unseeded draws with mean pairwise Jaccard < 0.5; every row's debug `similarity_score` ≥ 0.25 |
| Reproducible draw | The same `seed` gives the same ordered page |
| Likes | With and without likes, Jaccard < 0.5; with likes, `similarity_score` ≥ 0.25, and `likes_rerank=yes` appears in the log |
| Exclude contract | Full page, no excluded key, every row above the floor |
| Dislike comparison | The same `seed` on the plain and centroid requests |
| Home and search unchanged | Home is a full default page with `mode=home`; search results match across a fallback |

---

### 1. `engine/server/api/server_config.py`

**The new block** goes directly after `DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR = False` (line 358), below `BATCH_SIZE` (line 310), so the reference resolves. It is pure Python, because `test_server_config.py` imports this file without numpy.

```python
# Up-next (seeded similar) pool: serve-time ANN fallback bounds, relevance floors and the sampling window.
# These govern up-next only; DEFAULT_NPROBE / DEFAULT_SIMILARITY_SEARCH_LIMIT / DEFAULT_SIMILAR_PER_LIKE still govern every other route.
# Initial ANN k for the up-next fallback when the cached pool is short.
SIMILAR_VIDEO_SEARCH_LIMIT = 5000
# Most candidates kept in the up-next pool after filters.
SIMILAR_VIDEO_TOP_K = 300
# Initial FAISS nprobe for the up-next fallback (set and restored per search under index_lock).
SIMILAR_VIDEO_NPROBE = 32
# Pool size below which the up-next fallback runs: one feed batch.
SIMILAR_VIDEO_TARGET_MIN_POOL = BATCH_SIZE
# Hard caps for the fallback's doubling of nprobe and search limit.
SIMILAR_VIDEO_MAX_NPROBE = 128
SIMILAR_VIDEO_MAX_SEARCH_LIMIT = 20000
# Relevance floor for fallback candidates.
SIMILAR_VIDEO_MIN_SCORE = 0.35
# Relaxed floor for the tail fill; nothing below it reaches an up-next pool, cached rows included.
SIMILAR_VIDEO_TAIL_MIN_SCORE = 0.25
# The up-next draw samples from the top M rows, M = factor x limit, capped at the pool size.
SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR = 4
```

**`RELATED_VIDEOS_PERSONALIZATION`** (lines 312-322). The values change and the comment is reworded:

```python
# Related videos personalization configuration (watch page).
# enabled: re-ranks the top-M up-next window by likes before the draw; its score weights the draw.
# alpha: weight for the base similarity score (video-to-video).
# beta: weight for the user similarity score (candidate vs liked embeddings).
# max_likes: max recent likes considered when computing user similarity.
RELATED_VIDEOS_PERSONALIZATION = {
    "enabled": True,
    "alpha": 0.7,
    "beta": 0.3,
    "max_likes": 5,
}
```

### 2. `engine/server/data/ann.py`

**`compute_similar_items` and `search_index` are byte-for-byte unchanged.**

**The nprobe helpers** move here from `server.py:185-204`. They go after `search_index` and before `_author_key`. Reader, setter and restore all target the object that `faiss.extract_index_ivf` returns. The quiet setter keeps today's `hasattr` branches, so startup behaviour is identical.

```python
def _extract_ivf(index: faiss.Index) -> Any:
    """Return the IVF index holding nprobe, or None when the index has none."""
    if not hasattr(faiss, "extract_index_ivf"):
        return None
    try:
        return faiss.extract_index_ivf(index)
    except Exception:  # pragma: no cover
        return None


def get_nprobe(index: faiss.Index) -> int | None:
    """Read nprobe from the IVF index the setter writes, or None without one."""
    ivf_index = _extract_ivf(index)
    return int(ivf_index.nprobe) if ivf_index is not None else None


def apply_nprobe(index: faiss.Index, nprobe: int) -> None:
    """Set FAISS nprobe on a supported index, without logging."""
    ivf_index = _extract_ivf(index)
    if ivf_index is not None:
        ivf_index.nprobe = nprobe
    if hasattr(index, "nprobe"):
        index.nprobe = nprobe
    elif hasattr(index, "index") and hasattr(index.index, "nprobe"):
        index.index.nprobe = nprobe


def set_nprobe(index: faiss.Index, nprobe: int) -> None:
    """Set FAISS nprobe on a supported index and log it (startup)."""
    apply_nprobe(index, nprobe)
    ivf_index = _extract_ivf(index)
    logging.info(
        "[similar-server] ann_nprobe_configured=%d index_type=%s ivf_type=%s",
        nprobe,
        type(index).__name__,
        type(ivf_index).__name__ if ivf_index is not None else None,
    )
```

The log text is byte-identical to today's.

**The fallback search** goes directly after `compute_similar_items`. It applies no author cap; `similarity_candidates` applies that over the merged pool. Ids stay rowids, so plan 17 migrates the `ids > 0` filter, the seed-rowid exclusion and `fetch_metadata` here as well.

```python
def search_similar_above(
    server: Any,
    seed: dict[str, Any],
    nprobe: int,
    search_limit: int,
    min_score: float,
) -> tuple[list[dict[str, Any]], int | None]:
    """ANN-search the seed at a temporary nprobe; return hits scoring >= min_score and the restored nprobe.

    The nprobe is set, searched and restored inside one index_lock hold, so every other search on the
    shared index sees the startup value. Hits come back in score order with no per-author cap.
    """
    vector = seed["embedding"]
    if server.normalize_queries:
        vector = normalize_vector(vector)
    with server.index_lock:
        previous = get_nprobe(server.index)
        try:
            if previous is not None:
                apply_nprobe(server.index, nprobe)
            scores, ids = server.index.search(vector.reshape(1, -1), search_limit)
        finally:
            if previous is not None:
                apply_nprobe(server.index, previous)
        restored = get_nprobe(server.index)
    seed_rowid = seed.get("rowid")
    kept = [
        (float(score), int(rowid))
        for score, rowid in zip(scores[0], ids[0])
        if int(rowid) > 0 and int(rowid) != seed_rowid and float(score) >= min_score
    ]
    logging.info(
        "[similar-server] ann_fallback nprobe=%d search_limit=%d floor=%.2f hits=%d restored_nprobe=%s",
        nprobe,
        search_limit,
        min_score,
        len(kept),
        restored,
    )
    if not kept:
        return [], restored
    with server.db_lock:
        metadata = fetch_metadata(
            server.db,
            [rowid for _, rowid in kept],
            error_threshold=getattr(server, "video_error_threshold", None),
        )
    items: list[dict[str, Any]] = []
    for score, rowid in kept:
        meta = metadata.get(rowid)
        if not meta:
            continue
        items.append({"video_id": meta["video_id"], "instance_domain": meta["instance_domain"], "score": score})
    return items, restored
```

**Invariants:**
- The set and the restore happen in one lock hold, and the restore sits in `finally`, so a failed search cannot leave nprobe raised.
- `restored` is read back from the same IVF object after the restore.
- With no IVF (`previous is None`), the index is not touched and the search runs at whatever nprobe it has. This is a deliberate simplification; the production index is always IVF.

### 3. `engine/server/api/server.py`

- **Delete** `set_nprobe` (lines 185-204).
- **Import** it with `from data.ann import set_nprobe`, next to the other `data.*` imports. Keep `import faiss` (lines 117-122): `faiss.read_index` and the `faiss.Index` annotation still use it.
- **Add** the nine `SIMILAR_VIDEO_*` names to the `from server_config import (...)` list.
- **Log the constants.** Directly after `set_nprobe(index, DEFAULT_NPROBE)` (line 357):

```python
    logging.info(
        "[similar-server] upnext_config SIMILAR_VIDEO_SEARCH_LIMIT=%s SIMILAR_VIDEO_TOP_K=%s SIMILAR_VIDEO_NPROBE=%s SIMILAR_VIDEO_TARGET_MIN_POOL=%s SIMILAR_VIDEO_MAX_NPROBE=%s SIMILAR_VIDEO_MAX_SEARCH_LIMIT=%s SIMILAR_VIDEO_MIN_SCORE=%s SIMILAR_VIDEO_TAIL_MIN_SCORE=%s SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR=%s",
        SIMILAR_VIDEO_SEARCH_LIMIT,
        SIMILAR_VIDEO_TOP_K,
        SIMILAR_VIDEO_NPROBE,
        SIMILAR_VIDEO_TARGET_MIN_POOL,
        SIMILAR_VIDEO_MAX_NPROBE,
        SIMILAR_VIDEO_MAX_SEARCH_LIMIT,
        SIMILAR_VIDEO_MIN_SCORE,
        SIMILAR_VIDEO_TAIL_MIN_SCORE,
        SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR,
    )
```

The tokens are ASCII `NAME=value`, so `_extract_fields` places them in `context`, and the test compares `str(module.NAME)` with each value. The `StreamHandler` writes every INFO line to the log whatever the profile; `modes` is only a viewer hint.

`SimilarServer` is unchanged.

### 4. `engine/server/data/similarity_candidates.py`

**Unchanged:** `get_similar_candidates`, `_read_cache`, `_write_cache`, `_compute_candidates`, `_build_rows`, `_source_from_seed` and `_author_key`.

**New import:** `from data.serving_moderation import apply_serving_moderation_filters`. `data.ann` is imported lazily inside the function, as `_compute_candidates` does, so this module stays importable without faiss.

**Module comment** (lines 5-9). It is reworded to describe two entry points:
- `get_similar_candidates`, for home: cache, then compute and write on a miss;
- `get_upnext_candidates`, for up-next: cache read only, then a floored ANN fallback that never writes.

**New policy dataclass and function**, beside `SimilarityCandidatesPolicy`:

```python
@dataclass(frozen=True)
class UpnextPoolPolicy:
    """Pool size, relevance floors and ANN fallback bounds for up-next candidate selection."""
    top_k: int
    target_min_pool: int
    nprobe: int
    search_limit: int
    max_nprobe: int
    max_search_limit: int
    min_score: float
    tail_min_score: float
    cache_limit: int
    refresh_cache: bool = False


def get_upnext_candidates(
    server: Any,
    seed: dict[str, Any],
    policy: UpnextPoolPolicy,
    excluded: set[str] | None = None,
    request_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the up-next pool for a seed and the stats its log line reports.

    Reads the similarity cache but never writes it. When the filtered pool is short (or the cache has
    no entry) a live ANN fallback steps nprobe/search_limit up to the caps, adding hits >= min_score,
    then a tail of hits >= tail_min_score. Cached and fallback entries pass the same filters: seed,
    per-author cap over the merged pool, source author, error threshold, floor, exclude, moderation.
    """
    stats: dict[str, Any] = {"initial": 0, "steps": [], "restored_nprobe": None, "final": 0, "tail": 0}
    if policy.top_k <= 0:
        return [], stats
    embedding = seed.get("embedding")
    if embedding is None:
        embedding = seed.get("vector")
    if embedding is None:
        return [], stats
    if seed.get("embedding") is None:
        seed = {**seed, "embedding": embedding}
    excluded = excluded or set()

    source = _source_from_seed(seed)
    # require_full=False: a precomputed 20-row entry is a hit; allow_write=False: up-next never writes.
    cache_policy = SimilarityCachePolicy(
        refresh=policy.refresh_cache, require_full=False, allow_read=True, allow_write=False
    )
    cached: list[dict[str, Any]] = []
    if source:
        cached = _read_cache(server, source, max(policy.cache_limit, policy.top_k), cache_policy)
    cache_hit = bool(cached)
    cached = _sorted_by_score([entry for entry in cached if float(entry["score"]) >= policy.tail_min_score])
    rows = _upnext_rows(server, cached, seed, policy, excluded, request_id)
    stats["initial"] = len(rows)

    if len(rows) < policy.target_min_pool or not cache_hit:
        from data.ann import search_similar_above

        nprobe = policy.nprobe
        search_limit = policy.search_limit
        hits: list[dict[str, Any]] = []
        while True:
            before = len(rows)
            hits, restored = search_similar_above(server, seed, nprobe, search_limit, policy.tail_min_score)
            core = [hit for hit in hits if hit["score"] >= policy.min_score]
            rows = _upnext_rows(server, _merge_entries(cached, core), seed, policy, excluded, request_id)
            stats["steps"].append((nprobe, search_limit, len(rows)))
            stats["restored_nprobe"] = restored
            if len(rows) >= policy.target_min_pool:
                break
            if nprobe >= policy.max_nprobe and search_limit >= policy.max_search_limit:
                break
            if len(rows) <= before:
                break
            nprobe = min(nprobe * 2, policy.max_nprobe)
            search_limit = min(search_limit * 2, policy.max_search_limit)
        if len(rows) < policy.target_min_pool and hits:
            rows = _upnext_rows(server, _merge_entries(cached, hits), seed, policy, excluded, request_id)
            cached_keys = {like_key(entry) for entry in cached}
            stats["tail"] = sum(
                1
                for row in rows
                if like_key(row) not in cached_keys and float(row.get("score") or 0.0) < policy.min_score
            )

    rows = _dedup_rows(rows)[: policy.top_k]
    stats["final"] = len(rows)
    return rows, stats


def _upnext_rows(
    server: Any,
    entries: list[dict[str, Any]],
    seed: dict[str, Any],
    policy: UpnextPoolPolicy,
    excluded: set[str],
    request_id: str | None,
) -> list[dict[str, Any]]:
    """Resolve score-sorted entries into servable up-next rows: floor, _build_rows, exclude, moderation."""
    floored = [entry for entry in entries if float(entry["score"]) >= policy.tail_min_score]
    rows, _, _ = _build_rows(server, floored, seed, policy.top_k)
    # After the author cap, as before: an excluded row does not free its channel's slot.
    if excluded:
        rows = [row for row in rows if like_key(row) not in excluded]
    rows, _ = apply_serving_moderation_filters(server, rows, request_id=request_id)
    return rows


def _merge_entries(
    cached: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge fallback entries into cached ones by like_key (cached copy wins), sorted by score."""
    seen = {like_key(entry) for entry in cached}
    merged = list(cached)
    for entry in extra:
        key = like_key(entry)
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    return _sorted_by_score(merged)


def _sorted_by_score(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort entries by score descending; stable, so earlier (cached) entries win ties."""
    return sorted(entries, key=lambda entry: -float(entry["score"]))


def _dedup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop rows repeating a (video_uuid, instance_domain) or like_key already kept."""
    seen_uuids: set[tuple[str, str]] = set()
    seen_keys: set[str] = set()
    kept: list[dict[str, Any]] = []
    for row in rows:
        key = like_key(row)
        uuid_key = (row.get("video_uuid"), row.get("instance_domain") or "")
        if key in seen_keys or (uuid_key[0] and uuid_key in seen_uuids):
            continue
        seen_keys.add(key)
        if uuid_key[0]:
            seen_uuids.add(uuid_key)
        kept.append(row)
    return kept
```

**Decisions:**
- **Floor placement (departs from the plan).** The floor runs on entries before `_build_rows`. The plan filters rows after it. The entries are score-sorted, so a row below the floor can only hold a channel's slot when that channel has nothing above the floor. Removing it first therefore changes no surviving row, and it skips metadata lookups for rows that would be dropped.
- **The score being floored.** `_build_rows` copies the raw entry score into `row["score"]`, which is the raw PQ score from before `score_candidate`.
- **Cache read limit (plan left it open).** It is `max(cache_limit, top_k)`, and the handler passes `similar_per_like` (1000), today's up-next read. A runtime-written 1000-row entry is not truncated before the author cap, which would otherwise shrink the pool.
- **When the fallback runs.** `len(rows) < target or not cache_hit`. With `refresh_cache`, the read returns [], so the fallback always runs.
- **"Adds no new row"** is judged against the pool as it was before this step; the first step is judged against the initial pool. A step can only replace hits, never accumulate them (the plan's alternatives explain why).
- **The tail** reuses the last search's hits, which were already floored at 0.25 in `ann.py`. `stats["tail"]` counts fallback-only rows below 0.35.
- **What the caller receives.** Rows come back score-ordered and deduplicated, with at most `top_k`. `_write_cache` and `_compute_candidates` cannot be reached from here.

### 5. `engine/server/api/recommendations/related_personalization.py`

- **New key constant**, below the imports: `PERSONALIZED_SCORE_KEY = "personalized_score"`.
- **Stamp**, in the loop right after `final_score = ...` (line 83): `candidate[PERSONALIZED_SCORE_KEY] = final_score`. The order it returns and the list itself are unchanged. The early returns leave no stamp.
- **Module comment.**
  - "only reorders the existing list" gains ", and stamps each candidate's final score under `personalized_score`".
  - A line is added: "Up-next runs it on the top-M window before the weighted draw; the stamp is the draw weight and the page order."
  - The formula line stays.

### 6. `engine/server/api/handlers/similar.py`

**Imports:**
- Add `import hashlib` and `import math` to the stdlib block.
- Replace `from data.similarity_candidates import SimilarityCandidatesPolicy, get_similar_candidates` with `from data.similarity_candidates import UpnextPoolPolicy, get_upnext_candidates`.
- Add `from recommendations.related_personalization import PERSONALIZED_SCORE_KEY, rerank_related_videos`.
- Add the nine `SIMILAR_VIDEO_*` names to the `server_config` import. `fetch_request_excluded_keys` stays imported, now passed to the data layer.

**Changes to `_handle_similar`:**
- Next to the debug parse: `draw_seed = _parse_non_negative_int(params.get("seed", [None])[0])`. This is a pure parse that touches no server attribute, so the child-process stub tests are unaffected.
- The call at line 992 gains `draw_seed=draw_seed`.

**`_handle_seed_with_embedding`.** The signature gains `draw_seed: int | None = None`. The body from line 764 to the end of the rows branch becomes:

```python
        settings = getattr(self.server.recommendation_strategy, "settings", None)
        similar_per_like = int(getattr(settings, "similar_per_like", 0) or 0)
        pool_policy = UpnextPoolPolicy(
            top_k=SIMILAR_VIDEO_TOP_K,
            target_min_pool=SIMILAR_VIDEO_TARGET_MIN_POOL,
            nprobe=SIMILAR_VIDEO_NPROBE,
            search_limit=SIMILAR_VIDEO_SEARCH_LIMIT,
            max_nprobe=SIMILAR_VIDEO_MAX_NPROBE,
            max_search_limit=SIMILAR_VIDEO_MAX_SEARCH_LIMIT,
            min_score=SIMILAR_VIDEO_MIN_SCORE,
            tail_min_score=SIMILAR_VIDEO_TAIL_MIN_SCORE,
            cache_limit=similar_per_like,
            refresh_cache=refresh_cache,
        )
        related_start = perf_counter()
        # Excluded rows leave the pool before it is counted, so the next page is drawn from rows not yet shown.
        rows, pool_stats = get_upnext_candidates(
            self.server, seed, pool_policy, fetch_request_excluded_keys(), request_id
        )
        related_ms = int((perf_counter() - related_start) * 1000)
        if rows:
            score_start = perf_counter()
            centroids = fetch_request_dislike_centroids()

            def penalise(candidates: list[dict[str, Any]], settings: Any) -> None:
                ...  # unchanged

            rows = score_and_rank_list(
                rows, profile_config, layer_name=mode, now_ms_value=now_ms(), adjust=penalise
            )
            score_ms = int((perf_counter() - score_start) * 1000)
            for row in rows:
                row["debug_profile"] = profile_name
            # related_entries and timing log lines: unchanged
            window = rows[: min(SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR * limit, len(rows))]
            likes_reranked = False
            if (
                self.server.related_personalization_enabled
                and self.server.related_personalization_deps is not None
            ):
                personalize_start = perf_counter()
                window = rerank_related_videos(
                    self.server,
                    user_id,
                    window,
                    self.server.related_personalization_deps,
                )
                likes_reranked = any(PERSONALIZED_SCORE_KEY in row for row in window)
                # timing personalize log line: unchanged
            page = _draw_page(window, limit, draw_seed)
            _log_upnext_pool(request_id, pool_stats, draw_seed, len(window), likes_reranked, page)
            seed_payload = dict(seed.get("meta") or {})
            seed_payload["mode"] = mode
            self._respond_rows(page, include_debug, request_id, started_at, seed_payload=seed_payload)
            return
        _log_upnext_pool(request_id, pool_stats, draw_seed, 0, False, [])
        respond_json(...)  # the empty-200 branch, unchanged
```

**Removed from this method:**
- the `SimilarityCandidatesPolicy` construction;
- the exclude filter at lines 793-796, now inside the pool build;
- `rows = rows[:limit]`.

**New module-level helpers**, placed after `_parse_non_negative_int`:

```python
def _draw_weight(row: dict[str, Any]) -> float:
    """Final score a row is drawn and ordered by: the likes rerank stamp when present, else the ranked score."""
    value = row.get(PERSONALIZED_SCORE_KEY, row.get("score"))
    return float(value) if value is not None else 0.0


def _seeded_uniform(draw_seed: int, key: str) -> float:
    """A uniform in (0, 1] tied to the draw seed and the row, stable across processes."""
    digest = hashlib.blake2b(f"{draw_seed}:{key}".encode("utf-8"), digest_size=8).digest()
    return (int.from_bytes(digest, "big") + 1) / float(1 << 64)


def _draw_page(
    window: list[dict[str, Any]], limit: int, draw_seed: int | None
) -> list[dict[str, Any]]:
    """Draw `limit` rows from the window by score-weighted sampling without replacement (Efraimidis-Spirakis).

    Each positive-weight row gets key log(u) / w and the largest keys win; zero-weight rows fill only
    what positive ones cannot, in window order. The page is returned ordered by final score.
    """
    if len(window) <= limit:
        chosen = list(window)
    else:
        rng = np.random.default_rng() if draw_seed is None else None
        keyed: list[tuple[float, int, dict[str, Any]]] = []
        unweighted: list[dict[str, Any]] = []
        for index, row in enumerate(window):
            weight = _draw_weight(row)
            if weight <= 0:
                unweighted.append(row)
                continue
            u = _seeded_uniform(draw_seed, like_key(row)) if rng is None else 1.0 - float(rng.random())
            keyed.append((math.log(u) / weight, index, row))
        keyed.sort(key=lambda item: (-item[0], item[1]))
        chosen = [item[2] for item in keyed[:limit]]
        chosen.extend(unweighted[: limit - len(chosen)])
    return sorted(chosen, key=lambda row: -_draw_weight(row))


def _log_upnext_pool(
    request_id: str,
    stats: dict[str, Any],
    draw_seed: int | None,
    window_size: int,
    likes_reranked: bool,
    page: list[dict[str, Any]],
) -> None:
    """Log one up-next pool line: initial pool, fallback steps, final pool, sampling, rows returned."""
    steps = ",".join(f"{nprobe}/{search_limit}->{pool}" for nprobe, search_limit, pool in stats["steps"]) or "none"
    restored = stats.get("restored_nprobe")
    logging.info(
        "[similar-server][%s] upnext_pool initial=%d steps=%s restored_nprobe=%s final=%d tail=%d sampling=%s window=%d likes_rerank=%s returned=%d",
        request_id,
        stats["initial"],
        steps,
        restored if restored is not None else "none",
        stats["final"],
        stats["tail"],
        "random" if draw_seed is None else "seeded",
        window_size,
        "yes" if likes_reranked else "no",
        len({like_key(row) for row in page}),
    )
```

**Decisions:**
- **Keys and randomness.** `log(u)/w` is the log form of `u^(1/w)`: the same order, but numerically safe. `1 - rng.random()` keeps `u` in (0, 1], so `log` never sees 0.
- **Why the seeded draw is coupled.** A row's key depends only on the seed, its `like_key` and its own weight. A centroid therefore moves only the rows whose weight it changes, apart from rows it pushes into or out of the top-M window.
- **Log tokens are ASCII** (`->`, `,`), so the whole steps list stays one token.
- **Stamp and debug.** The rerank stamp cannot reach the response, because `stable_video_rows` whitelists fields. `debug_profile` is set on every pool row before the window, so the served rows keep it (`test_profiles`).
- **When the page is not a draw.** A window of `limit` rows or fewer is returned whole, so a pool of 48-95 at limit 96 comes back short and undrawn, as the inventory notes.

### 7. Tests

**Rate budget.** The limit is 60 requests / 60 s per `ip:path`. Each live-Engine file runs in its own `validate_tests.py` invocation. The pool listings are cached for the session in conftest.

#### 7a. `tests/active/conftest.py`: shared helpers (additive; not fixtures)

```python
UPNEXT_MAX_LIMIT = 96
UPNEXT_POOL_PAGES = 8
_UPNEXT_POOLS: dict[tuple[str, str, str], list[dict]] = {}


def exclude_entries(rows: list[dict]) -> list[dict]:
    """The `exclude` body entries naming these rows."""
    return [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows]


def _upnext_ref(route: str, seed: dict) -> str:
    return f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={UPNEXT_MAX_LIMIT}&seed=0"


def upnext_pool(engine, route: str, seed: dict) -> list[dict]:
    """Every row of a seed's up-next pool on `route`, listed direct on the Engine by seeded exclude paging."""
    key = (route, seed["video_uuid"], seed["instance_domain"])
    if key not in _UPNEXT_POOLS:
        pool: list[dict] = []
        for _ in range(UPNEXT_POOL_PAGES):
            status, body = engine.request("POST", _upnext_ref(route, seed),
                                          body={"exclude": exclude_entries(pool)} if pool else {})
            assert status == 200, body
            if not body["rows"]:
                break
            pool.extend(body["rows"])
        else:
            raise AssertionError("up-next pool listing did not end")
        _UPNEXT_POOLS[key] = pool
    return _UPNEXT_POOLS[key]


def pin_upnext(engine, route: str, seed: dict, chosen: list[dict]) -> list[dict]:
    """The `exclude` entries leaving exactly `chosen` of the seed's up-next pool, checked direct on the Engine.

    A window no larger than the limit is served whole, so a request with this exclude and a limit >=
    len(chosen) returns exactly `chosen`, keyless or keyed, through the Engine or the Client.
    """
    wanted = {(r["video_id"], r["instance_domain"]) for r in chosen}
    excluded = [r for r in upnext_pool(engine, route, seed) if (r["video_id"], r["instance_domain"]) not in wanted]
    for _ in range(3):
        status, body = engine.request("POST", _upnext_ref(route, seed), body={"exclude": exclude_entries(excluded)})
        assert status == 200, body
        got = {(r["video_id"], r["instance_domain"]) for r in body["rows"]}
        if got == wanted:
            return exclude_entries(excluded)
        # A narrower pool can step the fallback further and surface rows the listing did not reach.
        excluded.extend(r for r in body["rows"] if (r["video_id"], r["instance_domain"]) not in wanted)
    raise AssertionError(f"could not pin the up-next pool to {sorted(wanted)}")
```

The module docstring gains one line about these helpers. The pin is deterministic: ANN search and the pool build are deterministic for a given exclude, and no draw happens. So a failure repeats on every run; it does not flake.

#### 7b. `tests/active/test_similar.py`

- **`UPNEXT_SEED_QUERIES` comment:** "Seeds whose cached up-next pool was 19 and 17 deep; the fallback now fills them past a batch."
- **Docstring bullet (13-15):** "For a seed whose pool fills two 8-row pages, an up-next request excluding a previous 8-row page, or every other row of it, returns a full 8-row page with none of the excluded rows, every row at or above `SIMILAR_VIDEO_TAIL_MIN_SCORE` (debug `similarity_score`)."
- **The test body:**

```python
@pytest.mark.parametrize("query", UPNEXT_SEED_QUERIES)
def test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos(engine, query):
    path = _upnext_path(engine, query) + "&debug=1"
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    status, first = engine.request("POST", path, body={})
    assert status == 200 and len(first["rows"]) == UPNEXT_PAGE, first
    previous = _key_list(first["rows"])

    # The whole previous page, and every other row of it, which offset paging would not reproduce.
    for excluded in (previous, previous[0::2]):
        status, page = engine.request("POST", path, body={"exclude": [{"id": v, "host": h} for v, h in excluded]})
        assert status == 200, page
        keys = _key_list(page["rows"])
        assert len(keys) == UPNEXT_PAGE, keys
        assert not set(excluded) & set(keys), (excluded, keys)
        assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in page["rows"]), page["rows"]
```

- **`_config()`.** `_default_limit` is generalised into `_config()`, which returns the module, and `_default_limit()` becomes `int(_config().BATCH_SIZE)`.
- **Membership is checked by the floor (departs from the plan).** The plan checked rows against a seeded `limit=96` reference, which the inventory flags as flaky once the pool exceeds 96. The floor carries the same "from the seed's pool" meaning, because the pool is defined by that floor.

#### 7c. `tests/active/test_dislike_profile.py`

- **`DRAW_SEED = 7`.** `_seed_and_pair`'s path becomes `...&limit=16&seed={DRAW_SEED}`. The centroid requests reuse `path`, so both sides get the coupled draw.
- **Docstring:** "...than the same seeded request without it (the same draw, with and without the centroid)".
- **Home test** is unchanged; it only takes d1 and d2 from the pair.

#### 7d. `tests/active/test_upnext_diversity.py` (new module)

The docstring lists the bullets below. Shared pieces:
- `_config()` via `spec_from_file_location`;
- `_seed(engine, query)` from search;
- `_jaccard_mean(pages)`;
- `_log_messages(engine)`, which reads `engine.db_path` (the fixture passes the log path as `ClientBackend`'s second field), parses each JSON line, returns `message`, and polls up to 5 s for a wanted prefix.

The tests:

1. **`test_the_engine_holds_and_logs_the_upnext_constants_at_their_defaults`.**
   - Expected: `{SEARCH_LIMIT: 5000, TOP_K: 300, NPROBE: 32, MAX_NPROBE: 128, MAX_SEARCH_LIMIT: 20000, MIN_SCORE: 0.35, TAIL_MIN_SCORE: 0.25, SAMPLE_WINDOW_FACTOR: 4}`, plus `TARGET_MIN_POOL == BATCH_SIZE == 48`, and `RELATED_VIDEOS_PERSONALIZATION` alpha 0.7 / beta 0.3.
   - The `[similar-server] upnext_config` message's `NAME=value` tokens equal `str(getattr(module, NAME))` for all nine.
2. **`test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor`.**
   - Seed "linux"; 10 unseeded POSTs to `/recommendations?...&limit=8&debug=1` with body `{}`.
   - Each page has 8 rows and mean pairwise Jaccard < 0.5.
   - Every row has debug `similarity_score` ≥ 0.25 - 1e-6.
   - Control: the same path plus `&seed=11`, sent twice, gives equal ordered key lists.
3. **`test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged`** (parametrised linux/cooking).
   - Before: open `ROOT / DEFAULT_SIMILARITY_DB_PATH` with `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` and read `similarity_sources` and `SELECT similar_video_id, similar_instance_domain, score, rank FROM similarity_items WHERE source_video_id=? AND source_instance_domain=? ORDER BY rank` for the seed's `video_id` and `instance_domain`. Control: the cached rows are fewer than 48.
   - POST `limit=48`: 48 rows, 48 distinct `(video_uuid, instance_domain)` and 48 distinct `video_id::instance_domain`.
   - After: the same reads return equal results.
4. **`test_upnext_with_and_without_likes_both_diversify_and_liked_rows_stay_above_the_floor`.**
   - Likes: 5 "music" search rows as `{"uuid", "host"}`; seed "linux"; route `/videos/similar`, a separate rate bucket.
   - 10 draws with `{"likes": likes}` and 10 with `{}`, each at `limit=8&debug=1`. Each set has Jaccard < 0.5.
   - Every liked row has `similarity_score` ≥ 0.25.
   - At least one `upnext_pool` message after these requests has `likes_rerank=yes`.
5. **`test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`.**
   - Search `q=music&limit=20` before, then a linux up-next request (which runs the fallback), then search again: the ordered keys are equal and there are 20 rows.
   - Home POST `/recommendations` `{}` returns `len == BATCH_SIZE` with `seed.mode == "home"`.
   - Every `upnext_pool` message whose `steps` is not `none` has `restored_nprobe == str(DEFAULT_NPROBE)`, and at least one such message exists.

#### 7e. `tests/active/test_blocks.py`

- **`_surface` docstring:** "The method and path of one page of the named surface; up-next pages are pinned with `exclude` (see `pin_upnext`)."
- **`_rows`** gains an optional `body` argument, passed through for POST.
- **`test_blocked_channel_and_account_...`** gains the `engine` fixture. For the two up-next surfaces:
  - `pool = upnext_pool(engine, surface, seed)`, then `pin = pin_upnext(engine, surface, seed, pool[:PAGE])`.
  - Every up-next request (keyless, blocker, bystander) sends `{"exclude": pin}`.
  - Keyless returns exactly those 8 rows. The blocker's 2× Engine request returns the same 8, and the Client drops the blocked two. The bystander keeps both targets.
  - The assertions are unchanged. Search is untouched.
  - Returning the seed from `_surface` needs a small refactor.
- **`_deep_seed` and the stays-full test** are unchanged; they still hold as pools grow.

#### 7f. `tests/active/test_dislikes.py`

- **`SEEDS` comment:** "Seeds whose up-next pool is deeper than one page; pages are pinned with `exclude`, so a page is a fixed set."
- **`_upnext`** gains `body=None`.
- **`test_a_disliked_video_is_absent...`** gains `engine`:
  - `pool = upnext_pool(engine, route, seed)`.
  - `pin16 = pin_upnext(..., pool[:PAGE])` and `pin17 = pin_upnext(..., pool[:PAGE + 1])`.
  - `keyless = _upnext(..., body={"exclude": pin16})`, which is exactly those 16. `disliked = keyless[PAGE // 2]`.
  - The profile's page uses `pin17`: the Engine serves 17, the Client drops the disliked one, and 16 remain, full.
  - Keyless and bystander use `pin16`: the disliked row is present, and the bystander loses only `keyless[0]`.
- **`test_a_profile_s_upnext_page_leans_away...`:**
  - Every request uses `{"exclude": pin16}`, so all three pages hold the same set, ordered by penalised score.
  - The `_pair` and closeness assertions are unchanged. They compare the order of one fixed set, which is how they worked when the page covered nearly the whole 18-19-row pool.

#### 7g. `tests/active/test_frontend_blocks.py`

- **Runner:** `const upnext = () => m.fetchSimilarVideosPayload({...}, JSON.parse(process.env.EXCLUDE || "[]"));`. `_run` gains `exclude` and passes `EXCLUDE=json.dumps(exclude)`.
- **`_seed_and_targets`** gains `engine`:
  - `chosen = upnext_pool(engine, "/recommendations", seed)[:int(PAGE)]` and `pin = pin_upnext(...)`.
  - `in_upnext = chosen[0]`.
  - `from_search` must not share a channel with `chosen`.
  - It returns `pin`, which the test passes to `_run`.
- **Assertions** are unchanged. Before the block the runner's up-next is exactly `chosen`; after it, 7 rows without the blocked channel.

#### 7h. `tests/active/test_frontend_videos.py`

- **`PIN_DEPTH = 20`.** The runner reads `PIN = JSON.parse(process.env.PIN)`:
  - plain fetches become `fetchSimilarVideosPayload(query, PIN)`;
  - the pager becomes `createFeedPager((exclude) => { calls += 1; return m.fetchSimilarVideosPayload(query, [...PIN, ...exclude]); })`.
- **Test.** It gains `engine`, and sets `pin = pin_upnext(engine, "/recommendations", seed, upnext_pool(...)[:PIN_DEPTH])`.
  - Batches are 8, 8, 4, then empty at index 3, which is under `MAX_BATCHES = 6`.
  - Exclude stays within the caps: at most 280 + 20 = 300 entries, under 500.
- **Assertions changed:** the plain-equality control (line 87) is replaced by "each plain fetch has 8 rows, all among the 20 pinned". The no-repeat, empty-batch and call-count assertions are unchanged.
- **Text:** the docstring bullet and the `_seed` comment are updated to "pinned to a 20-row pool".

#### 7i. At harvest (`.un/skills/devsecops/config.json`)

- Map `test_upnext_diversity` to `data/ann.py`, `data/similarity_candidates.py`, `handlers/similar.py`, `server_config.py`, `server.py` and `related_personalization.py`.
- Add `data/ann.py` and `data/similarity_candidates.py` to `test_similar` and `test_dislike_profile`.
- Add `handlers/similar.py` and `data/similarity_candidates.py` to `test_blocks`, `test_dislikes` and `test_frontend_blocks`.
- Changing `conftest.py` reselects broadly; run the full `tests/active` suite, one invocation per live-Engine file.

### 8. Checked against the plan and requirements (two passes)

| Requirement | Where it is met |
|---|---|
| R1 | Constants and comments (§1); startup line (§3); `DEFAULT_*` untouched |
| R2 | Steps 32/5000 → 64/10000 → 128/20000 (§4); three stop rules; 0.35 floor then 0.25 tail from the last search; merge in which the cache wins; TOP_K cut; no write path; set, search and restore in one `index_lock` hold (§2); home path unchanged by construction |
| R3 | Dedup on both keys (`_merge_entries` and `_dedup_rows`); seed, author cap over the merged pool, source author, error threshold (`_build_rows`); exclude and moderation (`_upnext_rows`); dislike penalty before the window (§6) |
| R4 | Window M = min(4 × limit, pool); weighted E-S draw where every positive weight can be drawn; whole window when ≤ limit; fresh RNG by default; `seed` reproduces; page ordered by final score; exclude applied before the window |
| R5 | alpha 0.7 / beta 0.3; rerank on the window before the draw; stamp as the weight; source-pool draw without likes; profile selection untouched |
| R6 | One `upnext_pool` line (§6); `related_entries`, timing and `done` kept |
| R7 | §7b-§7d, plus the four pinned rewrites §7e-§7h (operator decision) |
| Constraints | No dependency, no new module (tests aside); `ann.py` is the only fallback search; rowids kept |

**Residual risks** are the ones already in the plan: latency and `index_lock` contention on almost every up-next request, a 500 on a deadline overrun, PQ-approximate floors, a statistical dislike comparison, and loss of up-next cache warming.

**Documentation.** The settled doc items (OVERVIEW, LAYER_PARAMS, PIPELINE_DIAGRAM, the server README `seed` bullet, DEPLOYMENT, DATA_BUILD, issues 09 and 11, plan.md and plan 17) are applied at harvest as listed. Plan 17's inventory gains `search_similar_above`, `get_nprobe`, `apply_nprobe` and `set_nprobe`.


### Phases

#### Phase 1 - Up-next config and startup line [code]

**Files touched.** engine/server/api/server_config.py (EDITED), engine/server/api/server.py (EDITED), tests/active/test_upnext_diversity.py (NEW)

**Checkpoint.** New module tests/active/test_upnext_diversity.py, test `test_the_engine_holds_and_logs_the_upnext_constants_at_their_defaults`. Seam 1 is the config module, loaded with `importlib.util.spec_from_file_location`. The precedent is `test_similar._default_limit` (test_similar.py:71). It asserts the nine SIMILAR_VIDEO_* defaults (SEARCH_LIMIT 5000, TOP_K 300, NPROBE 32, MAX_NPROBE 128, MAX_SEARCH_LIMIT 20000, MIN_SCORE 0.35, TAIL_MIN_SCORE 0.25, SAMPLE_WINDOW_FACTOR 4), that TARGET_MIN_POOL == BATCH_SIZE == 48, and that RELATED_VIDEOS_PERSONALIZATION has alpha 0.7 and beta 0.3. Seam 2 is the Engine log that the session `engine` fixture writes: conftest.py:106 passes the log path as ClientBackend's second field, `engine.db_path`. The test parses the JSON lines, polls up to 5 s for the `[similar-server] upnext_config` message, and asserts that each of the nine NAME=value tokens equals str(getattr(module, NAME)).

**Intent.** server_config.py defines the nine SIMILAR_VIDEO_* up-next constants at their defaults (TARGET_MIN_POOL written as BATCH_SIZE) and sets RELATED_VIDEOS_PERSONALIZATION to alpha 0.7 / beta 0.3. server.py logs all nine constants in one `upnext_config` line right after startup's set_nprobe.

- C1 - server_config.py holds the nine SIMILAR_VIDEO_* constants at their defaults, with TARGET_MIN_POOL equal to BATCH_SIZE, and RELATED_VIDEOS_PERSONALIZATION at alpha 0.7 / beta 0.3.
- C2 - The Engine's startup log carries one `[similar-server] upnext_config` line whose nine NAME=value tokens equal the module's values.

**Outcome.** ### `engine/server/api/server_config.py`
- Added the nine up-next constants in one block right after `DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR`, which puts them below `BATCH_SIZE` so the reference works. Each has a one-line `#` comment. The values are `SIMILAR_VIDEO_SEARCH_LIMIT = 5000`, `SIMILAR_VIDEO_TOP_K = 300`, `SIMILAR_VIDEO_NPROBE = 32`, `SIMILAR_VIDEO_TARGET_MIN_POOL = BATCH_SIZE` (48 today, and it changes whenever the home profile's `batch_size` changes), `SIMILAR_VIDEO_MAX_NPROBE = 128`, `SIMILAR_VIDEO_MAX_SEARCH_LIMIT = 20000`, `SIMILAR_VIDEO_MIN_SCORE = 0.35`, `SIMILAR_VIDEO_TAIL_MIN_SCORE = 0.25` and `SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR = 4`. A two-line header comment says they apply to up-next only. `DEFAULT_NPROBE`, `DEFAULT_SIMILARITY_SEARCH_LIMIT` and `DEFAULT_SIMILAR_PER_LIKE` still control every other route.
- `RELATED_VIDEOS_PERSONALIZATION`: `alpha` changed from 0.2 to 0.7 and `beta` from 0.8 to 0.3. `enabled` and `max_likes` are unchanged. I left the comment above it alone; the plan rewords it, but only once the top-M window exists, which is a later phase.

### `engine/server/api/server.py`
- Added the nine `SIMILAR_VIDEO_*` names to the `from server_config import (...)` list.
- Right after `set_nprobe(index, DEFAULT_NPROBE)` at startup, added one `logging.info` call. It logs `[similar-server] upnext_config` followed by nine `NAME=%s` tokens with the module's values: SEARCH_LIMIT, TOP_K, NPROBE, TARGET_MIN_POOL, MAX_NPROBE, MAX_SEARCH_LIMIT, MIN_SCORE, TAIL_MIN_SCORE and SAMPLE_WINDOW_FACTOR. Because the values come from the imported names, a config module with overridden values logs those values instead.
- I left `set_nprobe` where it is. The plan moves it to `data/ann.py`, but that file isn't in this phase's list, so the move belongs to a later phase.

### `tests/active/test_upnext_diversity.py`
- Not created. The phase lists it as NEW, but it is where the durable test goes when the checkpoint `tests/tmp/test_09_similars_diversity_phase1.py` is moved in, and this step is production code only.

#### Phase 2 - Up-next pool with floored ANN fallback [code]

**Files touched.** engine/server/data/ann.py (EDITED), engine/server/api/server.py (EDITED), engine/server/data/similarity_candidates.py (EDITED), engine/server/api/handlers/similar.py (EDITED), tests/active/conftest.py (EDITED), tests/active/test_upnext_diversity.py (EDITED), tests/active/test_similar.py (EDITED), tests/active/test_dislike_profile.py (EDITED), tests/active/test_blocks.py (EDITED), tests/active/test_dislikes.py (EDITED), tests/active/test_frontend_blocks.py (EDITED), tests/active/test_frontend_videos.py (EDITED)

**Checkpoint.** In test_upnext_diversity.py, `test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged` is parametrised over linux and cooking. It enters the live Engine's POST /recommendations through the session `engine` fixture, and enters similarity-cache.db through a read-only `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`. As a control, the cached rows are fewer than 48 before the request. The test asserts that limit=48 returns 48 rows, distinct by (video_uuid, instance_domain) and by video_id::instance_domain, and that the seed's rows in similarity_sources and similarity_items are equal before and after. `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored` runs `q=music&limit=20` search, then a linux up-next request, then the same search again, and asserts the two searches return equal ordered keys with 20 rows. It asserts that home POST /recommendations {} returns BATCH_SIZE rows with seed.mode == "home". It also asserts that at least one `[similar-server] ann_fallback` log message exists and that every one reports restored_nprobe == str(DEFAULT_NPROBE); the log is read from engine.db_path as in phase 1. The rewritten test_similar exclude test, the seeded test_dislike_profile pair and the four pinned rewrites (test_blocks, test_dislikes, test_frontend_blocks, test_frontend_videos, using conftest's `upnext_pool`/`pin_upnext`) land here and must pass. Each live-Engine file runs in its own validate_tests.py invocation because of the 60 requests / 60 s rate limit.

**Intent.** `get_upnext_candidates` in data/similarity_candidates.py replaces `get_similar_candidates` in the up-next handler. When the cache is short, it fills the pool past one batch with `search_similar_above` in data/ann.py, which floors the hits and restores nprobe under index_lock. The similarity cache is never written, and home and search on the shared index keep the startup nprobe.

- C1 - An up-next request for a seed whose cached entry holds fewer than 48 rows returns 48 unique rows, and the seed's similarity-cache.db entry is unchanged by the request.
- C2 - After an up-next fallback, search and home return what they returned before, and every fallback search reports the shared index's nprobe restored to DEFAULT_NPROBE.

**Outcome.** ### `engine/server/data/ann.py`
- Moved the nprobe code here from `server.py` and split it into four functions. `_extract_ivf` returns the object from `faiss.extract_index_ivf`, or None. `get_nprobe` reads nprobe from that object. `apply_nprobe` is the setter that writes without logging, keeping the old `hasattr` branches. `set_nprobe` is the startup wrapper, and its `ann_nprobe_configured=... index_type=... ivf_type=...` log line is byte-identical to before. The reader, the setter and the restore all use the same IVF object.
- Added `search_similar_above(server, seed, nprobe, search_limit, min_score)` right after `compute_similar_items`. It holds one `server.index_lock` for the whole search: it reads the current nprobe, sets the requested one, searches, and restores the old value in a `finally`. It then reads nprobe back from the index. After that it drops ids ≤ 0, the seed's rowid and any hit below `min_score`. It logs `[similar-server] ann_fallback nprobe= search_limit= floor= hits= restored_nprobe=` and fetches metadata only for the hits that are left. It returns `{video_id, instance_domain, score}` entries in score order, with no author cap, plus the restored nprobe. The IDs are still rowids, so plan 17 has one more function to migrate.
- `compute_similar_items` and `search_index` are unchanged.

### `engine/server/api/server.py`
- Deleted the local `set_nprobe` and imported it with `from data.ann import set_nprobe`. The startup call is unchanged. `import faiss` stays, because `faiss.read_index` and the `faiss.Index` annotation still use it.

### `engine/server/data/similarity_candidates.py`
- The module comment now describes the two entry points: `get_similar_candidates` for home, which can compute and write the cache, and `get_upnext_candidates` for up-next, which only reads the cache and never writes it.
- New `UpnextPoolPolicy` dataclass holding the pool size, the floors and the fallback caps.
- New `get_upnext_candidates(server, seed, policy, excluded, request_id)`, which returns `(rows, stats)`. Step by step:
  - It reads the cache with `require_full=False, allow_write=False`, using read limit `max(cache_limit, top_k)`.
  - It drops cached entries below the tail floor and sorts the rest by score.
  - `_upnext_rows` builds the pool: floor, then `_build_rows` capped at `top_k`, then the request's exclude keys, then `apply_serving_moderation_filters`.
  - If the pool is below target, or the cache had no entry, it steps nprobe and search_limit by doubling up to the caps. It stops at the target, when both caps are reached, or when a step adds nothing.
  - Hits at 0.35 or above are merged with the cached entries; on a `like_key` clash the cached copy wins. The tail (0.25 and up, from the last search) is added only if the pool is still short.
  - A final pass dedupes by `(video_uuid, instance_domain)` and `like_key`, then cuts to `top_k`.
  - `_write_cache` and `_compute_candidates` cannot be reached from this function.
- New private helpers: `_upnext_rows`, `_merge_entries`, `_sorted_by_score`, `_dedup_rows`. `get_similar_candidates` and the helpers it already had are unchanged.

### `engine/server/api/handlers/similar.py`
- `_handle_seed_with_embedding` builds an `UpnextPoolPolicy` from the `SIMILAR_VIDEO_*` constants, which are now imported, plus `similar_per_like` as the cache read limit and `refresh_cache`. It calls `get_upnext_candidates` with `fetch_request_excluded_keys()` and the request id, in place of `get_similar_candidates`.
- The exclude filter that ran after scoring is gone, because the pool build now applies it. Scoring, the dislike penalty, `rows[:limit]` and the personalization rerank are otherwise unchanged; the draw is phase 3.
- Removed the imports this left unused: `SimilarityCandidatesPolicy`, `get_similar_candidates` and `like_key`.

### Test files listed for this phase but not edited
- I did not touch `tests/active/conftest.py`, `test_upnext_diversity.py`, `test_similar.py`, `test_dislike_profile.py`, `test_blocks.py`, `test_dislikes.py`, `test_frontend_blocks.py` or `test_frontend_videos.py`. This step is production code only, as in phase 1, and these are durable tests that have already gated. They need their own step.
- One of them breaks as of this phase: `test_frontend_videos.py` expects an empty batch within 6 batches of 8, and the linux pool now holds at least 48 rows. The others are still deterministic until the phase 3 draw lands, so I expect them to hold for now.

### Observed with a probe (`tests/tmp/probe_09_phase2_pool.py`, live Engine)
- For both seeds, linux and cooking, each request returned 200 at limit 48, 30 and 8, with every row distinct on both keys. The lowest `similarity_score` on any page was 0.73 for linux and 0.51 for cooking. Each request took about 0.2 s.
- Each fallback logged `nprobe=32 search_limit=5000 floor=0.25 hits=4999 restored_nprobe=24`, and the startup line reads `ann_nprobe_configured=24 index_type=IndexIDMap2 ivf_type=IndexIVF`.
- I have no tool that deletes files, so the probe file is still on disk and needs removing.
- I did not run the checkpoint itself.

**Beyond the files named.** tests/tmp/probe_09_phase2_pool.py - a throwaway probe of the live up-next pool and fallback log. It is still on disk because I have no tool that deletes files, and it needs removing.

#### Phase 3 - Weighted draw from the top-M window [code]

**Files touched.** engine/server/api/handlers/similar.py (EDITED), tests/active/test_upnext_diversity.py (EDITED)

**Checkpoint.** In test_upnext_diversity.py, `test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor` enters the live Engine's POST /recommendations?id=…&amp;host=…&amp;limit=8&amp;debug=1 for the linux seed, through the session `engine` fixture, with body {}. It makes 10 unseeded requests and asserts each returns 8 rows, the mean pairwise Jaccard of the key sets is below 0.5, and every row's debug similarity_score is ≥ SIMILAR_VIDEO_TAIL_MIN_SCORE − 1e-6. As a control, the same path with &amp;seed=11 sent twice must return equal ordered key lists. The full suite, including the pinned rewrites from phase 2, must stay green now that the draws are random.

**Intent.** `_handle_seed_with_embedding` in handlers/similar.py serves an up-next page as a score-weighted Efraimidis–Spirakis sample of `limit` rows from the top SAMPLE_WINDOW_FACTOR×limit rows of the pool. The sample is random per request by default and reproducible when a `seed` query parameter is given.

- C1 - Ten unseeded requests for one seed return pages with mean pairwise Jaccard below 0.5, every row at or above the tail floor.
- C2 - Two requests carrying the same `seed` return the same ordered page.

**Outcome.** ### `engine/server/api/handlers/similar.py`
- **New `seed` query parameter.** `_handle_similar` reads it with the existing `_parse_non_negative_int` into `draw_seed`, next to the debug parse. If it is missing or not a valid integer, the draw is random, not a 400. The parse only reads the query string and touches no server attribute, so the child-process stub tests are unaffected. `draw_seed` is passed to `_handle_seed_with_embedding` as a new last parameter (`draw_seed: int | None = None`).
- **Page is now drawn, not cut.** In `_handle_seed_with_embedding`, `rows = rows[:limit]` is replaced. After `score_and_rank_list`, the handler takes the top `min(SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR × limit, len(rows))` ranked rows as the window and passes it to `_draw_page`. `SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR` is added to the `server_config` import.
- **New `_draw_page(window, limit, draw_seed)`.** It is an Efraimidis–Spirakis weighted sample without replacement:
  - Each row with a positive `score` gets the key `log(u) / score`, and the `limit` largest keys are chosen.
  - Rows whose score is zero or less are used only if the positive ones cannot fill the page, and then in window order.
  - If the window holds `limit` rows or fewer, all of it is returned.
  - The page is returned ordered by score, descending.
  - Without a seed, `u` comes from a fresh `np.random.default_rng()` on each request, taking `1 - random()` so `log` never sees 0.
- **New `_seeded_uniform(draw_seed, key)`.** It computes the seeded `u` from a blake2b hash of the seed and the row's `like_key`, mapped into (0, 1]. So the same seed and pool give the same page in every process, and a row keeps its draw when the rows around it change. Added imports: `hashlib`, `math` and `from recommendations.keys import like_key`.
- **Personalization is left where it was.** `rerank_related_videos` still runs on the served page, now after the draw. The plan moves it onto the window, with the `personalized_score` stamp as the draw weight, in phase 4. Moving it without the stamp would make likes have no effect on the page at all.
- **Deferred to phase 4:** the `upnext_pool` log line.

### `tests/active/test_upnext_diversity.py`
- Not touched. It is listed as EDITED but does not exist yet; phases 1 and 2 did not create it either. It is where the `tests/tmp` checkpoints move once they become durable tests, and this step is production code only.
- The pinned rewrites of `test_blocks`, `test_dislikes`, `test_frontend_blocks`, `test_frontend_videos`, `test_similar` and `test_dislike_profile`, planned for phase 2, are also still unwritten. From this phase on, those tests' comparisons across unseeded up-next requests (plain pages repeating, a target reappearing on a fresh draw, plain-versus-dislike comparisons) meet random draws and are expected to fail or flake until those rewrites land.

#### Phase 4 - Likes-weighted draw and upnext_pool line [code]

**Files touched.** engine/server/api/recommendations/related_personalization.py (EDITED), engine/server/api/handlers/similar.py (EDITED), tests/active/test_upnext_diversity.py (EDITED)

**Checkpoint.** In test_upnext_diversity.py, `test_upnext_with_and_without_likes_both_diversify_and_liked_rows_stay_above_the_floor` enters the live Engine's POST /videos/similar?…&amp;limit=8&amp;debug=1 (a separate rate bucket) for the linux seed. It sends 10 requests with body {"likes": five "music" search rows as {uuid, host}} and 10 with {}. It asserts that each set has mean Jaccard below 0.5 and that every row drawn with likes has similarity_score ≥ 0.25. It also asserts that at least one `upnext_pool` log message after these requests has likes_rerank=yes; the log is read from engine.db_path. `test_home_and_search_are_unchanged_…` gains a second assertion: at least one `upnext_pool` message has steps other than `none`, and every such message has restored_nprobe == str(DEFAULT_NPROBE).

**Intent.** rerank_related_videos stamps each candidate's final score under `personalized_score`. When likes are present, up-next uses that stamp as the draw weight and the page order. Every up-next request writes one `[similar-server][id] upnext_pool` line reporting the pool, the fallback steps, the restored nprobe, the sampling mode, the window, whether likes reranked it, and the rows returned.

- C1 - Up-next draws made with likes and draws made without likes each diversify across refreshes; rows drawn with likes stay at or above the tail floor, and the log reports likes_rerank=yes.
- C2 - Every upnext_pool line that records fallback steps reports restored_nprobe equal to DEFAULT_NPROBE.

**Outcome.** ### `engine/server/api/recommendations/related_personalization.py`
- New module constant `PERSONALIZED_SCORE_KEY = "personalized_score"`.
- `rerank_related_videos` now writes each candidate's `final_score` under that key, in the scoring loop. It still returns the same candidates in the same order. The early returns (no user, no likes, no embeddings) leave no stamp.
- Updated the module comment: the function now also stamps the score, up-next runs it on the top-M window before the draw, and the stamp is the draw weight and the page order.

### `engine/server/api/handlers/similar.py`
- `rerank_related_videos` now runs on the top-M window before `_draw_page`. It used to run on the page after the draw. `likes_reranked` is true only when a row in the window has the stamp. Likes that resolve to no videos therefore log `no`, even when the request body carried likes. The `timing personalize` line is unchanged.
- New `_draw_weight(row)` returns `personalized_score` if the row has one, else `score`. `_draw_page` uses it for both the Efraimidis–Spirakis key and the final page order. Before, both used `score` directly. A window of `limit` rows or fewer still comes back whole and in window order; the rerank has already sorted it by the stamp.
- `get_upnext_candidates`' stats are now kept (`pool_stats`); they used to be discarded.
- New `_log_upnext_pool(request_id, stats, draw_seed, window_size, likes_reranked, page)` writes one line per up-next request: `[similar-server][<id>] upnext_pool initial= steps= restored_nprobe= final= tail= sampling=random|seeded window= likes_rerank=yes|no returned=`.
  - `steps` lists each search that ran as `nprobe/search_limit->pool`, comma-joined, or `none` if no search ran.
  - `restored_nprobe` is `stats["restored_nprobe"]`, the value the last `search_similar_above` call read back from the index. It is `none` when no search ran. It is never filled from `DEFAULT_NPROBE`.
  - The line is written after the draw and before the response. The empty-pool branch writes it too, with window 0 and returned 0.
- Imports `PERSONALIZED_SCORE_KEY` next to `rerank_related_videos`.

### Probe of the implemented phase (`tests/tmp/probe_09_phase4_impl.py`)
One linux request to POST /videos/similar with five "music" likes, one with no likes, one whose likes name no known video, then one POST /recommendations. All four returned 200 with 8 rows, and every row's debug similarity_score was 0.725 or higher. Each request logged exactly one line, for example `[similar-server][37d4d1] upnext_pool initial=18 steps=32/5000->300 restored_nprobe=24 final=300 tail=0 sampling=random window=32 likes_rerank=yes returned=8`. `likes_rerank` read `yes` on the liked request and `no` on the other three, and each line came after its request's own `ann_fallback` line. I did not run the checkpoint itself.

### `tests/active/test_upnext_diversity.py`
- Not touched. It is listed as EDITED but still does not exist; phases 1–3 did not create it either. The gating checkpoint is `tests/tmp/test_09_similars_diversity_phase4.py`, and this step is production code only.

**Beyond the files named.** tests/tmp/probe_09_phase4_impl.py - a throwaway probe of the upnext_pool line on the implemented phase. I have no tool that deletes files, so it is still on disk and needs removing (as do the earlier probe_09_* files noted in previous steps).


