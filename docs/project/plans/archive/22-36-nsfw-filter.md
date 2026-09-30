# 36-nsfw-filter

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/22-36-nsfw-filter.record.md`._

## Requirements

### Purpose

Videos flagged NSFW are hidden wherever the site lists videos, unless the visitor opts in. Today every video has a nullable `nsfw` INTEGER column in `whitelist.db` (`videos.nsfw`). The crawler fills it, and `/api/video` refreshes it from the source instance (issue 10). The Engine selects the column and passes it through (`engine/server/data/random_videos.py`, `metadata.py`, `search.py`), but nothing filters on it, and `client/frontend` has no NSFW control. After this build a visitor who does nothing never sees an NSFW-flagged video in any list.

### The setting

- A single NSFW setting. Its only control is in the Profile modal (`#profile-section`, rendered by `renderProfileSection` in `client/frontend/src/pages/videos/index.ts`).
- The control appears in every state the modal renders: a keyless visitor, a visitor holding a key, and the just-issued-key view. It needs no profile key.
- Default: filter on (NSFW hidden). Turning it off shows NSFW videos.
- The setting applies everywhere listed under "Coverage". There is no other control.
- Changing the setting on the home page reloads the current feed, so the change shows immediately.

### No per-mode toggles

The request's toggle buttons on the Recommendations and Random feed modes are dropped at the operator's decision. The feed-mode switcher (`[data-feed-mode]` buttons) is unchanged.

### Storage

- The setting is stored in the browser's `localStorage` only, next to `feedParams:v1` (`client/frontend/src/data/feed-params.ts`). It persists across reloads.
- It is not stored server-side and does not follow a profile key to another browser.
- Missing, unreadable (quota or private mode) or corrupt storage means filter on. A storage write failure must not break the page; the choice still holds for the current page.

### Coverage

The filter applies to every video list the site requests from the Engine:
- All five home feed modes: Recommendations, Hot, Recent, Random and Popular (`/recommendations` with `mode=`).
- The up-next feed: `/videos/similar` and `/recommendations` with a seed `id`, as requested by the video page (`client/frontend/src/pages/video-page/index.ts`) and by the home page with `?id=`.
- Search (`/api/v1/search/videos`, `client/frontend/src/pages/search/index.ts`).

The channels page (`client/frontend/src/pages/channels`) lists channels only and fetches no video rows, so it is unaffected.

### Filtering happens in the Engine

- The Engine leaves NSFW rows out while it builds each pool or page, so a page is still filled to its requested size. This covers the home like-layer and mixer layer pools (layer slots filled by ratio), the up-next pool (about 17 rows deep, then the weighted draw), the ordered Hot/Recent/Popular pages (LIMIT/OFFSET paging must not skip or repeat rows under the filter), the random draw, and search results.
- The browser never drops rows from a page after it arrives, and the gateway (`client/backend/server.py`) does not filter NSFW rows out of the payload either.
- With the filter off, results are identical to today's.

### Request parameter

- One query parameter, `nsfw`. `nsfw=1` means include NSFW rows. A missing parameter, an empty value, or any other value means filtered. A request that omits it never receives an NSFW-flagged row.
- The frontend sends `nsfw=1` only when the visitor has turned the filter off, on every feed, up-next and search request.
- The gateway allowlist `PROXY_ALLOWED_QUERY_PARAMS` in `client/backend/server.py` gains `nsfw` for `/recommendations`, `/videos/similar` and `/api/v1/search/videos`, and the gateway forwards it to the Engine.

### Unknown flags

`nsfw` NULL counts as not NSFW: with the filter on, only rows with `nsfw = 1` are removed (`v.nsfw IS NULL OR v.nsfw = 0` passes). The operator chose this without a measurement, and no `whitelist.db` is in the tree to measure against.

### Random feed page size

`random-cache.db` is prebuilt and holds rowids (`data/random_cache.fetch_random_rowids`, then `data/metadata.fetch_metadata`). With the filter on, the Random feed must still return a full page. The design chooses and justifies one of two approaches: read each drawn video's flag at draw time and draw again or overdraw to refill, or store the flag in the cache. If the cache schema changes, the rebuild and upgrade path must be stated.

### Out of scope

- A warning or overlay on a video page opened directly (for example from a link) for an NSFW video. The video page plays whatever it is linked to.
- Server-side storage of the setting on the profile key (`user_db`).
- Toggle buttons on individual feed modes.

### Baseline suite state

The pre-build suite exited 0 (baseline variant: false). The run selected `test_search_fusion.py` (10 passed); the other 29 test groups were unchanged. The build must leave the suite green.

## High-level plan

### Approach

One request flag, `include_nsfw`, is parsed once at the Engine's edge. It travels explicitly wherever the call chain is short. Where the call chain runs through the recommendation strategy's generator protocol, it goes through the request context that already carries excluded keys, likes and dislike centroids. Filtering is a SQL predicate, `(v.nsfw IS NULL OR v.nsfw = 0)`, added to the queries that build each pool, so LIMITs count only rows that are allowed. Nothing drops rows after a page is assembled.

**Engine edge (`engine/server/api/handlers/similar.py`).** A parser treats only the exact value `1` as include. It deliberately does not use `_parse_bool`, which also accepts `true`, `yes` and `on`; the requirement says any other value means filtered. `_handle_similar` covers the POST `/recommendations` and `/videos/similar` routes and the GET `/videos/{id}/similar` alias. It parses `nsfw` from the query and stores it in the request context through a new setter and getter pair in `request_context.py`. The getter returns "filtered" when the value is unset, and `clear_request_context` clears it. `_handle_search` parses it the same way and passes it to `search_videos`. A request without the parameter is filtered on every route.

**Data layer: an explicit keyword whose default keeps today's behaviour.** `fetch_metadata`, `fetch_metadata_by_ids` / `_select_metadata`, `fetch_random_rows`, `fetch_recent_videos`, `fetch_popular_videos`, `fetch_ordered_page`, `fetch_random_rows_from_cache`, `lexical_candidates`, `vector_candidates` and `search_videos` each gain `include_nsfw: bool = True`. When it is False they add the predicate next to the existing `error_threshold` clause, which already uses the same WHERE/AND pattern. The default stays include because these helpers also serve non-listing callers that must not change: `/api/video` (the video page plays whatever it is linked to), `/internal/videos/*` (resolving likes and blocks), and the ANN compute that writes the similarity cache. "Filtered by default" is enforced at the request edge, not in the data layer.

**How each coverage item is met:**
- **Hot, Recent and Popular (ordered pages).** `_handle_ordered_feed` passes the flag to `fetch_ordered_page`, so the predicate sits inside the ordered query. OFFSET then counts over the filtered total order, and each chunk continues exactly where the last ended. Rows are neither skipped nor repeated, and NSFW rows no longer use up the `ORDERED_FEED_MAX_CHUNKS` budget.
- **Random feed, the home fallback and the random seed path.** `_fetch_random_rows` passes the flag to both the cache draw and the `ORDER BY RANDOM()` fallback. The cache refill is described under "Random feed page size" below.
- **Recommendations (mixer).** `RecommendationBuilderDeps` gains `fetch_include_nsfw`. It defaults to a callable that returns False, so the keyword construction in `tests/active/test_video.py` still builds, and `server.py` wires in the request-context getter. The builder's existing `*_filtered` closures pass the flag into the random, cache, recent and popular fetches, so those layers are filled at the SQL level. The builder also wraps `get_similar_candidates` so the like-layer sources run with a policy carrying the flag. `SimilarityCandidatesPolicy` gains `include_nsfw`, and the sources stay unchanged.
- **Like layer and up-next pools.** `_build_rows` in `data/similarity_candidates.py` passes the flag to `fetch_metadata_by_ids`. NSFW entries find no metadata and are skipped before the author cap and before the count toward `limit`. `UpnextPoolPolicy` gains `include_nsfw`, set by `_handle_seed_with_embedding`. `_upnext_rows` counts the filtered pool, so the existing floored ANN fallback widens nprobe and search_limit until `target_min_pool` (about 17) is reached, and only then does the weighted draw run. The refill this needs is the mechanism that already exists. `_handle_vector_search` passes the flag too.
- **Search.** `lexical_candidates` puts the predicate in the FTS query, so its `candidate_pool` LIMIT counts only allowed rows. `vector_candidates` passes the flag to `fetch_metadata`. The fused list, its `total` and page slicing are all computed after filtering, so pages stay consistent.
- **Filter off.** Every change is an added clause or an extra draw that runs only when the flag is False. With `nsfw=1` the SQL, the draws and the pools are byte-for-byte today's.

**Random feed page size: read the flag at draw time and redraw.** When the filter is on, `fetch_random_rows_from_cache` draws its usual contiguous window, resolves it with `fetch_metadata(include_nsfw=False)`, and draws further random windows while the page is short. It skips rowids already seen and appends in draw order until the page reaches `limit`. The number of draws is capped by a named constant (4, matching `ORDERED_FEED_MAX_CHUNKS`). With the filter off it makes exactly one draw, as today. That matters: always refilling would also start refilling pages that `error_threshold` drops short, which would change filter-off results. The cache schema does not change, so no rebuild or upgrade is needed.

**Gateway (`client/backend/server.py`).** `nsfw` is added to the `PROXY_ALLOWED_QUERY_PARAMS` sets for `/recommendations`, `/videos/similar` and `/api/v1/search/videos`. The existing sanitiser already forwards allowed parameters and drops empty values; an empty value correctly becomes "missing" and so "filtered". The gateway's row filter (blocks and dislikes) is not touched, and it does not look at `nsfw`.

**Frontend.**
- **Storage (`client/frontend/src/data/feed-params.ts`).** The setting lives here under its own key, `nsfwFilter:v1`. The module gains read, set and query-entry helpers. Only a stored value that explicitly means "off" turns the filter off; a missing, unreadable or corrupt value reads as on. A module-level in-memory value holds the choice when `setItem` throws, so it still applies on the current page. This is the same try/ignore pattern `persistFeedParams` uses.
- **Requests.** `buildSimilarUrl` in `data/videos.ts` appends `nsfw=1` when the filter is off. That one change covers the home feed modes, the home `?id=` up-next feed and the video page's up-next feed, since all three go through it. `fetchSearchResults` in `data/search.ts` does the same, and the comment there that names exactly four parameters gets updated. The keyless search cache is keyed by URL, so on and off results never share a cache entry.
- **Control (`renderProfileSection` in `pages/videos/index.ts`).** A small helper builds a "Hide NSFW videos" checkbox, checked by default. It is appended in all three branches: the issued-key view, the key-holding view and the keyless view. Its change handler saves the setting, then calls `loadVideos()`, which builds a fresh pager from the first page. The current feed (mode or `?id=`) reloads with the new flag, without navigating away. The profile modal exists only on the home page (`index.html` / `videos.html`), so the video and search pages pick up the setting on their next request.

**Files touched.** Engine:
- `handlers/similar.py`
- `request_context.py`
- `server.py`
- `recommendations/builder.py`
- `data/metadata.py`
- `data/random_videos.py`
- `data/similarity_candidates.py`
- `data/search.py`

Gateway:
- `client/backend/server.py`

Frontend:
- `data/feed-params.ts`
- `data/videos.ts`
- `data/search.ts`
- `pages/videos/index.ts`

No new files, and no new interfaces beyond the flag.

### Alternatives considered

- **Store the flag in `random-cache.db`.** Rejected. The cache is prebuilt and refreshed only on an interval, while `nsfw` in `whitelist.db` changes whenever the crawler or an `/api/video` refresh updates it. A cached flag would go stale and let a newly flagged video through until the next rebuild, breaking "never sees". The draw already joins `videos` in `fetch_metadata`, so reading the live flag costs nothing. Storing the flag would also need a schema change, a change to the `precompute-random-rowids` job, a forced rebuild of every deployed cache, and a reader for old caches.
- **A data-layer default of "filtered".** Rejected. It would hide NSFW videos from `/api/video`, from internal like and block resolution, and from the ANN compute that writes the shared similarity cache. That breaks "the video page plays whatever it is linked to" and poisons the cache for visitors who opt in.
- **Filtering inside the ANN compute, so cached similarity lists are NSFW-free.** Rejected. The cache is shared across requests, and with the filter off results must be identical to today's. Filtering has to happen after the cache is read (`_build_rows`), never before it is written.
- **Passing the flag as an argument through `generate_recommendations` and every generator's `get_candidates`.** Rejected. It changes the Protocol and five generators plus two sources. The request context exists for exactly this kind of per-request value, and the builder already reads excluded keys from it through a dep.
- **Folding the setting into the `feedParams:v1` object.** Rejected. `resolveFeedParams` skips storage when `?mode=` is present and returns only `{mode}`, and `chooseFeedMode` overwrites the object. The NSFW setting also applies to search and the video page, which never read feed params. A separate key keeps the two lifecycles apart.
- **Reusing `_parse_bool` for the parameter.** Rejected. It accepts `true`, `yes` and `on`, and the requirement says only `1` includes NSFW.

### Gotchas and risks

- **The include default is a footgun.** A future listing call site that forgets to pass the flag would leak NSFW rows. Tests should pin each listing path (the five modes, `?id=` up-next, the video page's up-next, search, the random fallback and the vector path) against a fixture with `nsfw=1`, `0` and NULL rows, requested without the parameter.
- **The existing suite relies on NULL flags.** `test_similar.py` compares the HTTP ordered feed, sent without `nsfw`, against `fetch_ordered_page` called at its default. That holds only because the fixtures leave `nsfw` NULL, which passes the filter. A fixture change adding `nsfw=1` rows would need the reference call to pass the flag.
- **`RecommendationBuilderDeps` is frozen and built by keyword in tests.** The new field needs a default (the "filtered" callable) and must come last.
- **Ordering and index cost.** The predicate makes the ordered and lexical queries walk further down their index to fill a page, in proportion to the NSFW share near the top of each order. The share was not measured, so the cost is unknown but bounded by the existing chunk and statement deadlines.
- **The home change handler reloads through `loadVideos()`.** An in-flight `loadMoreVideos` already drops its result when the pager has changed (`current !== pager`), so no stale rows are appended.

### Limitations (deliberate simplifications)

- **The random cache refill is bounded at 4 draws.** If NSFW rows make up a very large share of the cache, a Random page can still come back short after four windows. The SQL fallback runs only when the cache returns nothing at all, which matches today's rule. Upgrade path: raise the cap, top up the shortfall from `fetch_random_rows`, or store a flag column in the cache once staleness is handled.
- **The like layer can shrink per seed.** Each liked seed contributes up to `similar_per_like` rows (cache-limited), and NSFW rows among them are removed rather than replaced from that seed. The sources pool all seeds and truncate to the layer's fetch limit, so the layer usually stays full. A visitor whose likes sit in mostly NSFW neighbourhoods gets a smaller like layer, and the mixer's existing backfill fills those slots from other layers. The page is still full, but the layer ratio shifts for that visitor. Upgrade path: read deeper cache or ANN lists per seed when the filter is on.
- **The vector half of search is not refilled.** NSFW hits are removed from the ANN rowid list rather than replaced, so the vector half can hold fewer than `candidate_pool` rows. Pages are much smaller than the fused pool, so only the tail of a long result set gets shorter. Upgrade path: overfetch the ANN search when the filter is on.

### Tradeoffs the operator is asked to accept

- **NULL flags pass the filter** (already decided). Any NSFW video the crawler has not flagged is shown to a filtered visitor.
- **The data-layer default is include**, with the filtered default enforced at the request edge. This is safer for the video page and the shared cache, at the cost of the call-site discipline described under Gotchas.
- **The setting is per browser only**, and the video and search pages have no control of their own; they read the stored value.
- **Filter-on pages near the tail of a very NSFW-heavy pool** (random cache, like layer, search's vector half) can be shorter or differently mixed, within the bounds above. With the filter off, results are unchanged.

## Impacts


<impacts>
<impact path="engine/server/api/handlers/similar.py" element="new module-level nsfw parser, next to _parse_int / _parse_bool / _parse_non_negative_int (lines 1126-1150)">
**What changes.** Add a pure helper, e.g. `_parse_include_nsfw(value: str | None) -> bool`. It returns True only for the exact string `"1"`. It returns False for None, `"true"`, `"yes"`, `"on"`, `"01"`, `"0"` and anything else. It must not reuse `_parse_bool` (1135-1139), which accepts `{"1","true","yes","on"}` after `strip().lower()`.

**Whitespace.** The plan does not say whether to strip, so choose and document it:
- `parse_qs` (lines 479, 615) drops blank values, so `nsfw=` arrives as missing.
- The gateway strips every value before forwarding (`client/backend/server.py:434, 489`), so a proxied `nsfw= 1 ` arrives as `1`.
- Only a direct Engine call can present `" 1"`.

**Depends on it.** `_handle_similar` and `_handle_search` (entries below), plus the new tests for "only `1` includes".

**Regression risk: low.** It is new code. The trap is reusing `_parse_bool`, which would make `nsfw=true` leak NSFW rows.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_similar() (lines 994-1123): parse `nsfw` and store it in the request context">
**What changes.** Read `params.get("nsfw", [None])[0]`, parse it with the new parser, and call the new setter from `request_context.py`.

**Where to set it.** It must be set here, not in `_handle_similar_request`, because the GET alias `/videos/{id}/similar` reaches `_handle_similar` directly (`_dispatch_get`, lines 523-530) and never passes through `_handle_similar_request`.

**Placement.** Put it next to `set_request_id(request_id)` (line 1035), preferably inside the `try` at 1037, so the `finally: clear_request_context()` at 1122-1123 clears it. The debug 403 (1018-1020) returns before that `try`. Setting the flag earlier would leave it uncleared on that path. This is harmless in practice because `SimilarServer` is a `ThreadingHTTPServer` (`server.py:14, 204`) with one thread per request, but it breaks the file's clear-what-you-set pattern.

**Who reads it.** Every listing branch reached from here reads the flag:
- `_handle_random` → `_fetch_random_rows`
- `_handle_ordered_feed`
- `_handle_home` (the mixer, through the builder dep, and its random fallback)
- `_handle_seed_with_embedding`
- the `seed.get("random")` branch (1099-1108) → `_fetch_random_rows`
- `_handle_vector_search`

**Depends on it.** All the routes above. The `_DEBUG_CHILD` and `_FAILING_SIMILAR_CHILD` harnesses in `tests/active/test_similar.py` call `_handle_similar` on a `SimpleNamespace` server. The new setter only touches thread-local state, so those still run.

**Regression risk: medium.** The data-layer default is include. Any branch that does not pass the flag through leaks NSFW rows silently, and no existing test notices.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_fetch_random_rows() (lines 669-681) and its three callers: _handle_random (717-732), the empty-mix fallback in _handle_home (795-804), and the `seed.get('random')` branch of _handle_similar (1099-1108)">
**What changes.** Both draws get the flag:
- `fetch_random_rows_from_cache(..., include_nsfw=...)` at line 671;
- `fetch_random_rows(..., include_nsfw=...)` at line 677.

**Where the flag comes from.** The plan does not say. Reading it from the request-context getter inside `_fetch_random_rows` is the safe choice. Adding a parameter to `_handle_random` is not: both test_similar harnesses replace `_handle_random` with a stub of the fixed signature `(self, limit, include_debug, request_id, started_at)` (`tests/active/test_similar.py:431, 541`). A fifth argument raises TypeError, which the handler turns into a 500. That would fail `test_debug_request_is_refused_403_unless_the_flag_is_set` and `test_recommendations_failure_answers_a_fixed_500_and_logs_its_traceback`.

**Fallback rule.** The cache-then-DB rule (`if rows: return rows`) is unchanged. The SQL fallback runs only when the cache path returns nothing, which matches the plan.

**Regression risk: medium.** This is the Random mode, the home empty-mix fallback and the random-seed path, all in one place.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_ordered_feed() (lines 734-779)">
**What changes.** Add `include_nsfw=...` to the `fetch_ordered_page` call (lines 751-757). With the predicate in the SQL:
- `offset += chunk_size` (758) walks the filtered total order.
- `len(chunk) < chunk_size` (770) now means the filtered order has ended.
- NSFW rows no longer use up `ORDERED_FEED_MAX_CHUNKS` (107).

`chunk_size` (745), the `exclude` and `seen` dedupe (759-766) and moderation (768) are unchanged.

**Depends on it.** `tests/active/test_similar.py::_reference` (1062-1066) compares the HTTP pages against `fetch_ordered_page(..., error_threshold=threshold)` at the data-layer default (include). See the test_similar entry.

**Regression risk: medium.** Filter-on pages differ from the reference whenever the live `whitelist.db` has `nsfw=1` rows inside `REFERENCE_DEPTH`.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_seed_with_embedding() (lines 813-933): UpnextPoolPolicy construction">
**What changes.** Pass `include_nsfw=<flag>` into `UpnextPoolPolicy(...)` (838-849). The flag comes from the context getter, or from a parameter. Nothing else here changes. Scoring (870-872), the personalisation rerank (891-909) and `_draw_page` (910) work on the already-filtered pool.

**Depends on it.**
- The up-next feed on the home `?id=` page and on the video page.
- `test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged` (`test_similar.py:816-833`), which asserts `len(rows) == limit` for limits 48 and 30.
- `test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor` (887-897).

Both read the live dataset with the filter now on.

**Regression risk: medium.** See the `get_upnext_candidates` entry for the stop rule that can leave the pool short.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_vector_search() (lines 935-992)">
**What changes.** Add `include_nsfw=...` to the `fetch_metadata` call at 967-971. NSFW rowids then have no metadata and are skipped at 982-984.

**No refill.** `search_index` asks for exactly `limit` rowids (959-962), so a filter-on vector page is `limit` minus its NSFW hits. The plan's coverage list names `_handle_vector_search` but its limitations do not mention this shortfall.

**Depends on it.** In `tests/active/test_similar.py`, `ANN_CHILD` (606-630, which calls `fetch_metadata` at 626 at the default) and the assertion at line 849 (`len(vector_before) == VECTOR_LIMIT` and equality with the child's page).

**Regression risk: medium** for that test, **low** for users. The raw-vector route is not used by the frontend.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_search() (lines 534-598)">
**What changes.** Parse `nsfw` from `params` with the new parser and pass `include_nsfw=` to `search_videos` (563-575).

This route runs from `_dispatch_get` (511-513) and never enters `_handle_similar`, so no request context is set here. It must not read the context getter: that would return the default (filtered), which is safe but ignores `nsfw=1`.

**Depends on it.** The search page, and `test_similar.py:853-878`, which compares two filtered searches with each other (they stay consistent) and asserts 20 rows for `q=music` (855, 877).

**Regression risk: low.** Search for `music` has far more than 20 matches, so the row count holds.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_home() (lines 781-811) and _handle_similar_request() (609-667): no code change">
**What changes.** Nothing.
- `_handle_home` calls `recommendation_strategy.generate_recommendations` (792-794), which reaches the flag through the builder dep reading the request context. It calls `_fetch_random_rows` on an empty mix (796).
- `_handle_similar_request` sets likes, centroids and excluded keys (655-662) and clears the context in its `finally` (666-667). The NSFW flag is set later, inside `_handle_similar`.

**Depends on it.** `engine/server/api/tests/test_recommendations_likes_limit.py` and `test_similar.py`'s `_LIKES_CHILD` (290-325). Both stub `_handle_similar` and patch `clear_request_context` with fixed expected call counts (for example `clear_context_mock.assert_called_once()`). Setting the flag in `_handle_similar_request` instead would not break those counts, but would miss the GET alias.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/handlers/similar.py" element="import block (lines 33-47 data imports, 79-89 request_context imports)">
**What changes.** Import the new setter, and the getter if `_fetch_random_rows`, `_handle_ordered_feed`, `_handle_seed_with_embedding` or `_handle_vector_search` read the context. The data imports (37-41) already name every function that gains the keyword.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/request_context.py" element="new set/fetch pair for the include-nsfw flag, and clear_request_context() (lines 53-64)">
**What changes.**
- A setter, e.g. `set_request_include_nsfw(value: bool)`.
- A getter, e.g. `fetch_request_include_nsfw() -> bool`, that returns False (filtered) when unset. Follow the `getattr(_REQUEST_CONTEXT, ..., default)` pattern of `fetch_request_excluded_keys` (30-32).
- `clear_request_context` gains a `hasattr`/`delattr` pair like the others (55-64), and its docstring should mention the flag.

**Depends on it.**
- `handlers/similar.py`.
- `api/server.py` wiring into `RecommendationBuilderDeps`.
- `logging_profiles.py:12` imports only `fetch_request_id`, so it is unaffected.
- `engine/server/api/tests/test_logging_profiles.py:22-30` calls `clear_request_context()`, which must stay safe to call when the attribute was never set.

**Thread model.** `SimilarServer` is a `ThreadingHTTPServer` (`server.py:204`), and the recommendation path runs on the request thread. The only other Engine thread that touches data is the random-cache worker (`server.py:489-505`), which never reads the request context.

**Regression risk: low**, provided the unset default is "filtered". A default of include would leak NSFW rows on any path that forgets to set the flag.
</impact>
<impact path="engine/server/api/server.py" element="RecommendationBuilderDeps construction (lines 392-405) and the request_context import (122-126)">
**What changes.** Pass `fetch_include_nsfw=fetch_request_include_nsfw` (the new getter) and add it to the import at 122-126. `get_similar_candidates=get_similar_candidates` (396) stays; the builder wraps it.

**Depends on it.** The whole recommendation mix.

**Regression risk: low.** Forgetting the wiring silently falls back to the dep's default (filtered), which is safe but ignores `nsfw=1` for the mix.
</impact>
<impact path="engine/server/api/recommendations/builder.py" element="RecommendationBuilderDeps dataclass (lines 39-61)">
**What changes.** Add `fetch_include_nsfw: Callable[[], bool]` with a default that returns False, e.g. `= lambda: False`. It must come last. The dataclass is frozen and every existing field has no default, so a defaulted field placed earlier is a TypeError at import.

**Depends on it.**
- `api/server.py:392-405`.
- `tests/active/test_video.py:219`, which builds the deps by keyword without the new field and so relies on the default.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/builder.py" element="the four *_filtered closures (lines 91-113)">
**What changes.** Each closure adds `include_nsfw=deps.fetch_include_nsfw()` to its call:
- `fetch_random_rows_filtered` (93-95);
- `fetch_random_rows_from_cache_filtered` (99-101);
- `fetch_recent_videos_filtered` (105-107);
- `fetch_popular_videos_filtered` (111-113).

The getter must be called inside each closure, on every call, not once at build time. `build_recommendation_strategy` runs once at startup (`server.py:415`), outside any request.

**Depends on it.** The `random`, `explore` (both `fetch_random_rows*`), `popular` and `fresh` generators (lines 156-194).

**Regression risk: medium.** Reading the flag at build time would freeze it at the unset default for every request.
</impact>
<impact path="engine/server/api/recommendations/builder.py" element="new wrapper around deps.get_similar_candidates, handed to AnnSimilarFromLikesDeps (115-124) and CachedSimilarFromLikesDeps (125-134)">
**What changes.** A closure `(server, seed, limit, policy)` that calls `deps.get_similar_candidates(server, seed, limit, dataclasses.replace(policy, include_nsfw=deps.fetch_include_nsfw()))`. Notes on the wrapper:
- The sources always pass a `SimilarityCandidatesPolicy` positionally, but the underlying function accepts `policy=None` (`similarity_candidates.py:41, 51-52`), so guard against None.
- `builder.py` must import `dataclasses.replace` (it imports only `dataclass` today, line 16).
- Both `likes_source` and `likes_fallback` (140-145) are built from `ann_deps` and `cached_deps`, so both get the wrapper once both deps take it.

**Depends on it.** The exploit (like) layer via `ExploitFromLikesGenerator` (148-155).

**Regression risk: medium.** If only one of the two deps objects gets the wrapper, the cache-optimised or the ANN fallback source leaks NSFW rows.
</impact>
<impact path="engine/server/api/recommendations/sources/ann_similar_from_likes.py" element="AnnSimilarFromLikesSource.get_candidates() (lines 42-84): no code change">
**What changes.** No code change. The source builds a fresh `SimilarityCandidatesPolicy` per like (68-73) without `include_nsfw`, and the builder wrapper overrides the field. In behaviour, each like's result shrinks by its NSFW rows before pooling and truncation to `limit` (84).

**Oddity.** The annotation at 20-23 refers to `sqlite3.Connection` without importing `sqlite3`. `from __future__ import annotations` keeps that harmless.

**Regression risk: low.** A future direct call to `get_similar_candidates` from here, bypassing the dep, would be unfiltered.
</impact>
<impact path="engine/server/api/recommendations/sources/cached_similar_from_likes.py" element="CachedSimilarFromLikesSource.get_candidates() (lines 43-138): no code change">
**What changes.** Nothing. It builds one policy (76-84) and calls `self.deps.get_similar_candidates` (106-108), which is the builder wrapper.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/candidates/random_videos.py" element="RandomVideosGenerator._fetch_pool() (131-137) and _fetch_pool_with_caps() (139-177): no code change, cost and lock notes">
**What changes.** No code change. The generator calls the builder closures.

**Locks.** It holds `server.db_lock` only around the DB fallback (136-137), never around the cache call, which takes `random_cache_lock` and `db_lock` itself inside `fetch_random_rows_from_cache`. `threading.Lock` is not reentrant, so the new refill loop must keep taking the locks per draw, never while holding one.

**Cost.** `_fetch_pool_with_caps` loops up to `max_attempts = 5` (157). With the filter on, each attempt can make up to 4 cache windows, so up to 20 windows, 20 `COUNT(*)` reads and 20 `fetch_metadata` calls per layer fill.

**Regression risk: low** for correctness, **low-medium** for latency on the home feed.
</impact>
<impact path="engine/server/api/recommendations/candidates/explore_range.py" element="ExploreRangeGenerator._fetch_pool() (lines 152-158): no code change">
**What changes.** No code change. It calls the cache closure, then the DB closure, both of which now carry the flag and inherit the refill.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/candidates/popular_videos.py" element="PopularVideosGenerator pool fetch (line 53): no code change">
**What changes.** No code change. It calls `fetch_popular_videos(server.db, max(pool_size, limit))` under `db_lock` through the closure, which now carries the flag.

**Test impact.** `tests/active/test_popular_videos.py:40` builds its deps with `fetch_popular_videos=lambda db, count: ...`. It bypasses the builder, so it is unaffected.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/candidates/fresh_videos.py" element="FreshVideosGenerator pool fetch (line 58): no code change">
**What changes.** No code change. It inherits the flag through `fetch_recent_videos_filtered`.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/candidates/exploit_from_likes.py" element="ExploitFromLikesGenerator.get_candidates() (lines 33-112): no code change">
**What changes.** Nothing. It consumes the like sources (57-65). Rows arrive already filtered, so the pool it caps and samples (70-93) can be smaller for NSFW-dense likes, as the plan's limitations say.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/recommendations/candidates/similar_from_likes.py" element="SimilarFromLikesGenerator (lines 11-52): dead code, no change">
**What changes.** Nothing. It has random fallbacks (43-52), but nothing in `engine/server` constructs `SimilarFromLikesDeps` or `SimilarFromLikesGenerator`. The builder uses `ExploitFromLikesGenerator` instead.

**Regression risk: none today.** If it is ever wired, it must receive the builder's `*_filtered` closures.
</impact>
<impact path="engine/server/api/recommendations/mixer.py" element="MixingRecommendationStrategy.generate_recommendations() (line 60 on): no code change">
**What changes.** No code change. It reads likes and excluded keys through deps (69, 88-90, 121), filters and reorders the layer rows, and backfills short layers from other layers. It never fetches rows itself.

**Regression risk: low.** The layer ratio can shift for NSFW-heavy like neighbourhoods, which the plan accepts.
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata() (lines 11-102)">
**What changes.** Add `include_nsfw: bool = True`. When it is False, append `AND (v.nsfw IS NULL OR v.nsfw = 0)` next to `{error_clause}` (66). The WHERE already exists (`WHERE e.rowid IN (...)`, 65). The predicate takes no parameter, so `params` is unchanged.

**Callers to keep at the default (include).**
- `data/ann.py::compute_similar_items` (45-49): it writes the shared similarity cache.
- `data/ann.py::search_similar_above` (129-133): it feeds up-next entries that `_build_rows` filters later.

**Callers that pass the flag.**
- `random_videos.fetch_random_rows_from_cache` (line 428);
- `similar._handle_vector_search` (967);
- `search.vector_candidates` (192).

**Test impact.** `tests/active/test_similar.py` `ANN_CHILD` (626) calls it at the default.

**Regression risk: low.** It is additive, and the default path is byte-identical.
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata_by_ids() (110-116), _select_pairs() (139-157), _select_metadata() (160-215), and fetch_metadata_by_uuids() (124-136), which shares _select_pairs">
**What changes.** The flag must pass from `fetch_metadata_by_ids` through `_select_pairs`, which the plan does not name, into `_select_metadata`. There the predicate goes next to `{error_clause}` (210). `_select_pairs` already wraps each chunk's OR of pairs in parentheses (156, with its comment), so an appended AND clause binds to every pair. The new predicate relies on the same parentheses.

**Scope.** `fetch_metadata_by_uuids` also calls `_select_pairs` (131). Give the new `_select_pairs` and `_select_metadata` parameters a default of include, so the uuid path, which serves `/internal/videos/metadata`, is unchanged.

**Depends on it.**
- `similarity_candidates._build_rows` (299-308), which passes the flag.
- `handlers/internal_client_reads.py:157, 159`, which stays at the default.
- `tests/active/test_metadata.py` (104, 148, 158, 161), which asserts the 29-key row. The row shape does not change.

**Regression risk: low**, if the parentheses stay. Without them the predicate would bind to the last pair only, which is the bug fixed in issue 33.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_random_rows() (lines 37-125)">
**What changes.** Add `include_nsfw: bool = True`.

**The plan's premise does not hold here.** It says the predicate goes "next to the existing error_threshold clause, which already uses the same WHERE/AND pattern". That is true of `fetch_ordered_page`, `fetch_metadata` and `_select_metadata`, but not of this function. Here `error_clause` is either `""` or a string that itself starts with `WHERE` (44), and `params` switches between `[limit]` and `[error_threshold, limit]` (42-45).

The implementer must build the WHERE from a list of conditions, as `fetch_ordered_page` does (323-332). Otherwise filter-on with no threshold produces no WHERE, and filter-on with a threshold produces `WHERE ... WHERE`. The predicate takes no parameter.

**Depends on it.**
- `_fetch_random_rows` in `similar.py`.
- The builder's `fetch_random_rows_filtered`.
- `tests/active/test_random_videos.py:309`.
- `tests/archive/37_local_signal/test_random_videos.py`.

**Regression risk: medium.** Malformed SQL fails only on the path it is built for.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_recent_videos() (lines 128-215)">
**What changes.** Same keyword, and the same WHERE-composition trap as `fetch_random_rows`: `error_clause` is `"WHERE (...)"` or `""` (132-136).

**Depends on it.** The builder's `fetch_recent_videos_filtered`, which feeds the fresh layer.

**Regression risk: medium.** It is the same trap.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_popular_videos() (lines 218-315)">
**What changes.** Add the keyword. The predicate must go inside the `popular_ids` subquery, next to `{error_clause}` (265). That is the only place where the subquery's `LIMIT ?` (267) counts allowed rows. The same WHERE-string trap applies (224-226): `params` is `[limit, limit]` or `[error_threshold, limit, limit]`.

If the predicate goes on the outer query instead, the SQL stays valid, but the layer silently comes back short.

**Depends on it.**
- The builder's `fetch_popular_videos_filtered`, which feeds the popular layer.
- `tests/active/test_random_videos.py:150-153, 249, 310`, which call it at the default and assert that it ranks by the Hot order.

**Regression risk: medium.**
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_ordered_page() (lines 318-414)">
**What changes.** Add the keyword. When it is False, `conditions.append("(v.nsfw IS NULL OR v.nsfw = 0)")` goes next to the error and recent conditions (323-331). This is the only function in the file that already uses the condition-list pattern the plan describes.

**Depends on it.**
- `_handle_ordered_feed`.
- `tests/active/test_random_videos.py:142, 160, 238, 312`, which call it at the default.
- `tests/active/test_similar.py::_reference` (1066).

**Regression risk: low** in code, **medium** in test expectations.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_random_rows_from_cache() (lines 417-435), plus a new named draw-cap constant">
**What changes.** `include_nsfw: bool = True`. The True path stays exactly as today: one `fetch_random_rowids` window, then one `fetch_metadata`. The False path:
- draws a window and resolves it with `fetch_metadata(..., include_nsfw=False)`;
- keeps drawing windows while the page is short, up to the cap;
- skips rowids already seen;
- appends rows in draw order and truncates to `limit`.

**Constraints on the loop.**
- **Draw cap.** The plan says "4, matching `ORDERED_FEED_MAX_CHUNKS`". That constant lives in `handlers/similar.py:107`, and the data layer must not import from handlers. Define a separate named constant in `random_videos.py`, or in `server_config.py`.
- **Handle lifetime.** Each draw must read `server.random_cache_db` again inside `with server.random_cache_lock:`, and must never keep the handle in a local variable across draws. `data/db.py::swap_readonly_connection` closes the old handle after releasing the lock (127-131). Its docstring (109) says this is safe only when a reader holds the lock for its whole use.
- **Lock order.** Take `random_cache_lock`, then release it, then take `db_lock`, per draw. Never hold both. Callers do not hold either lock (see the random_videos generator entry).
- **Small caches.** When the cache holds `limit` rows or fewer, `fetch_random_rowids` always reads from offset 0 (`random_cache.py:339`), so every redraw returns the same window. Stopping once a window adds no unseen rowid avoids up to 3 wasted round-trips.
- **Empty result.** An all-NSFW draw still returns `[]`, which makes the caller fall back to `fetch_random_rows` (`similar.py:674-681`).

**Depends on it.**
- `_fetch_random_rows` in `similar.py`.
- The builder's `fetch_random_rows_from_cache_filtered`, which feeds the random and explore layers.
- `tests/active/test_random_cache.py`: its `SimpleNamespace` owner contract (line 19, 176) and the live-Engine feed assertions (778, 827-828, 879).

**Regression risk: medium-high.** A refresh swap landing mid-loop gives a closed-handle 500 intermittently, and no test that avoids a mid-request refresh catches it.
</impact>
<impact path="engine/server/data/random_cache.py" element="fetch_random_rowids() (lines 329-344) and the cache build: no code change">
**What changes.** Nothing. The schema stays `random_rowids(position, video_rowid)`, so no rebuild or migration is needed, and the precompute job (`db/jobs/precompute-random-rowids.py`) is unchanged.

The window it returns is contiguous, and its start is `random.randint(0, total - limit)` (339). Redraws can therefore overlap earlier windows, and the loop's seen-rowid set handles that.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/db.py" element="swap_readonly_connection() (lines 97-131): no code change, sets the refill loop's lifetime rule">
**What changes.** Nothing in this file, but it sets a lifetime rule for the new refill loop in `random_videos.fetch_random_rows_from_cache`:
- The handle swap happens under the lock (127-129).
- The old handle is closed after the lock is released (130-131).
- Readers must hold the lock for their whole use (109).

**Regression risk: none here.** The risk sits in the caller.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="SimilarityCandidatesPolicy (27-34), get_similar_candidates() (37-101) and _build_rows() (284-343)">
**What changes.**
- `SimilarityCandidatesPolicy` gains `include_nsfw: bool = True`. Every field already has a default, so any position works.
- `get_similar_candidates` passes `policy.include_nsfw` to `_build_rows` (89).
- `_build_rows` gains a keyword and passes it to both `fetch_metadata_by_ids` calls: without the lock (299-301) and with it (303-308). An NSFW entry then has no metadata and is skipped at 324-326, before the author count (332-336) and before `len(rows) >= limit` (338).

**What stays unfiltered.** The ANN compute (`_compute_candidates`, 84) and the cache write (`_write_cache`, 87) run before `_build_rows` and stay unfiltered, so the shared cache is not poisoned. That matches the plan.

**Regression risk: low.** The default path is unchanged. The only production caller of `get_similar_candidates` is the deps wiring in `server.py:396`.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="UpnextPoolPolicy (104-116), get_upnext_candidates() (119-179) and _upnext_rows() (182-197)">
**What changes.** `UpnextPoolPolicy` gains `include_nsfw: bool = True` (frozen, after `refresh_cache`), and `_upnext_rows` passes `policy.include_nsfw` to `_build_rows` (192). `search_similar_above` (`ann.py:88-140`) returns unfiltered entries, and those go through `_upnext_rows`, so fallback hits are filtered at the same point.

**The plan's claim that the ladder "widens until target_min_pool is reached" does not always hold.** The loop breaks when a step adds no visible row (`if len(rows) <= before: break`, 168-169). With the filter on, a step whose new hits are all NSFW ends the ladder below `target_min_pool`, even when the caps are not reached. The tail pass (172-175) then runs only if there were hits.

The realistic case is a filtered visitor opening an NSFW video directly: the video page plays it, and its neighbourhood is mostly NSFW. That page can come back short. Changing the stop rule is outside the plan, so either state this in the limitations or exempt the filter-on case.

**Depends on it.**
- `_handle_seed_with_embedding`.
- `_log_upnext_pool` stats (`initial`, `steps`, `final`, `tail`), which will record more fallback steps.
- `tests/active/test_similar.py:816-833` (a 48-row fill for the `linux` and `cooking` seeds, where `len(rows) == limit` is asserted) and 887-897.

**Regression risk: medium.**
</impact>
<impact path="engine/server/data/ann.py" element="compute_similar_items() (21-85) and search_similar_above() (88-140): must stay at the include default">
**What changes.** Nothing. Both call `fetch_metadata` at the default (45-49, 129-133).
- `compute_similar_items` output is written to the shared similarity cache (`similarity_candidates.py:87`). Filtering here would poison the cache for opted-in visitors.
- `search_similar_above` feeds `_upnext_rows`, which filters later.

**Regression risk: none** if left alone, **high** if someone "completes" the change by threading the flag into these.
</impact>
<impact path="engine/server/data/search.py" element="lexical_candidates() (134-164)">
**What changes.** Add `include_nsfw: bool = True`. When it is False, add `AND (v.nsfw IS NULL OR v.nsfw = 0)` after `WHERE videos_fts MATCH ?` (158), so `LIMIT ?` (160) counts only allowed rows. Unlike the plan's description, this function has no `error_threshold` clause today, so there is no clause to sit beside. The predicate takes no parameter, so the tuple `(match_expression, limit)` (162) is unchanged.

**Depends on it.** `search_videos`.

**Regression risk: low.** The index cost is bounded by the search statement deadline (`search_deadline`, 46-49).
</impact>
<impact path="engine/server/data/search.py" element="vector_candidates() (167-202)">
**What changes.** `include_nsfw: bool = True`, passed into `fetch_metadata` (192-196). NSFW rowids are dropped (198-201) and not replaced, so the vector half can hold fewer than `candidate_pool` rows (a limitation the plan names).

**Depends on it.** `search_videos`.

**Regression risk: low.**
</impact>
<impact path="engine/server/data/search.py" element="search_videos() (251-305)">
**What changes.** `include_nsfw: bool = True`, passed to:
- `lexical_candidates`, which is called positionally at 284, so add the flag as a keyword;
- `vector_candidates` at 287.

`fuse_by_rank`, `total` and the slice (304-305) then run over already-filtered lists. Moderation, applied later in the handler (580-584), still runs after `total`, as it does today.

**Test impact.** `tests/active/test_search_fusion.py` calls only `fuse_by_rank` and is unaffected.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="handle_internal_videos_metadata / resolve (fetch_metadata_by_ids and fetch_metadata_by_uuids at lines 157-159)">
**What changes.** Nothing. These must stay at the default (include). They resolve likes, blocks and imports for the Client backend (`client/backend/server.py:917, 976, 1035, 1050`, via `fetch_metadata_for_entries`).

**Depends on it.** `tests/active/test_internal_client_reads.py`.

**Regression risk: none** if left alone. Filtering here would drop NSFW likes from profiles.
</impact>
<impact path="engine/server/api/handlers/video.py" element="handle_video_request / handle_video_refresh_request: no code change">
**What changes.** Nothing. `/api/video` must still serve NSFW videos: the video page plays whatever it is linked to. It has its own SQL (`v.nsfw` at 58) and does not use the helpers above. The refresh writes `nsfw` (395, 409), and the filter reads the column live, so a newly flagged video is filtered on its next listing.

**Regression risk: none.**
</impact>
<impact path="client/backend/server.py" element="PROXY_ALLOWED_QUERY_PARAMS (lines 88-105)">
**What changes.** Add `"nsfw"` to the sets for `/recommendations` (89), `/videos/similar` (90) and `/api/v1/search/videos` (93). Without it the gateway answers 400 `Unknown query parameter: nsfw` (427, 482), and the frontend's `nsfw=1` would break every feed for opted-in visitors.

**Scope.** The gateway has no proxy route for `GET /videos/{id}/similar` (`PROXY_READ_GET_ROUTES`, 84-86), so that alias is reachable only directly on the Engine.

**Regression risk: low**, but high impact if it is forgotten. No test pins the allowlist today (a grep of `tests/` finds none), so add one.
</impact>
<impact path="client/backend/server.py" element="_handle_engine_read_proxy_get (421-440), _handle_engine_read_proxy_post (475-572), _profile_filter (442-473), _proxy_engine_request (574 on): no code change">
**What changes.** Nothing.
- The sanitisers strip values and drop empty ones (434-436, 489-491), so `nsfw=` or `nsfw=  ` is not forwarded, and the Engine treats it as missing (filtered).
- `urlencode(sanitized_query)` (587) forwards `nsfw=1` verbatim.
- The block and dislike row filter and the twice-the-page over-fetch (471-472) apply to the Engine's already NSFW-filtered rows. The Engine accepts up to `default_limit * 2` (`similar.py:1000-1002`), so the over-fetch still works.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/data/feed-params.ts" element="new NSFW setting helpers (read, set, query entry) under key `nsfwFilter:v1`, beside STORAGE_KEY (15), persistFeedParams (32-38) and readStoredFeedParams (54-64)">
**What changes.** Add:
- a separate storage key constant (`nsfwFilter:v1`);
- a module-level in-memory override that holds the choice when `setItem` throws;
- a reader that returns "filter on" unless a stored value explicitly means off, with missing, unreadable or corrupt values reading as on (the same try/catch pattern as `readStoredFeedParams`);
- a setter using `persistFeedParams`' try/ignore pattern (33-37);
- a query-entry helper returning `[["nsfw","1"]]` only when the filter is off.

**Unchanged.** `resolveFeedParams`, `persistFeedParams`, `FeedParams` and `feedParamsToQuery` stay as they are. The module docstring (1-3) and the comment "storage holds this object whole" (10) should say the NSFW setting lives here under its own key.

**Read order.** The reader must check the in-memory value first, so a failed `setItem` still applies on the current page.

**Depends on it.**
- `data/videos.ts`, `data/search.ts`, `pages/videos/index.ts`.
- `tests/active/test_frontend_feed_params.py`, which bundles this file with `FEED_MODES, resolveFeedParams, persistFeedParams` (124) and its in-memory `localStorage` (41-46).

**Regression risk: low.** If the reader defaults to off on corrupt storage, visitors are unfiltered.
</impact>
<impact path="client/frontend/src/data/videos.ts" element="buildSimilarUrl() (lines 99-111), used by fetchSimilarVideosPayload() (134-161)">
**What changes.** Append the feed-params NSFW query entry (`nsfw=1` only when the filter is off), independent of the `feedParams` argument. It must apply even when `feedParams` is undefined: the `?id=` up-next feed calls `fetchSimilarVideosPayload(similarQuery, exclude)` without feed params (`pages/videos/index.ts:208`), and so does the video page (`pages/video-page/index.ts:331`). The import at line 10 grows.

**Depends on it.**
- Home feed modes, the home `?id=` up-next feed, and the video page up-next feed.
- `tests/active/test_frontend_feed_params.py`: case (13) asserts that `buildSimilarUrl(q)` with no feed params carries no `mode`, and it reads only `path`, `limit` and `mode` (58). The default (filter on, empty storage) adds no parameter, so it still passes.
- `tests/active/test_frontend_blocks.py:37-39, 57`, `test_frontend_upnext_pager.py` and `test_frontend_video_page*.py` bundle `videos.ts` with empty storage, so they send no `nsfw`.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/data/search.ts" element="fetchSearchResults() (lines 55-87) and the module comment (lines 1-8)">
**What changes.** Set `nsfw=1` on `url` when the filter is off, before the keyed or keyless branch (after 62).

**Comment.** The module comment says the gateway allowlists "exactly four query parameters (`q`, `page`, `limit`, `sort`)" and that "this client sends those and nothing more". That becomes false and must be rewritten to name five.

**Cache.** The keyless cache key is `search:${url}` (76), so on and off results never share an entry. The keyed branch is `no-store` (67).

**Depends on it.**
- The search page (`pages/search/index.ts:159-165`).
- `tests/active/test_frontend_blocks.py` and `test_frontend_reactions.py` (87, 113), which bundle it with empty storage, so there is no change.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="renderProfileSection() (lines 718-809) and a new checkbox helper">
**What changes.** Add a helper that builds a "Hide NSFW videos" checkbox, checked unless the setting is off. Append it in all three branches:
- the issued-key view (`profileSection.append(...)` at 744, which then returns at 745);
- the key-holding view (779, returns at 781);
- the keyless view (807).

Because each branch returns early, the control must be appended inside each branch, or once before the branching.

Its change handler saves the setting, then calls `loadVideos()`. The profile modal stays open, and `renderProfileSection` rebuilds on every `openProfileModal` (691), so the checkbox always reflects storage when the modal opens.

**Styling.** Existing controls are built by `profileButton` (853-867) and `profileActions` (869-874) with `ghost-button` and `profile-actions` classes. There is no checkbox style in `videos.css` (`.profile-section` at 230-240), so a small style addition may be needed.

**Depends on it.**
- `index.html` and `videos.html` (`#profile-section` at line 61 in each).
- No test drives `renderProfileSection` today; a grep of `tests/` finds none.

**Regression risk: low-medium.** If the control is missing from one branch, the requirement "every state the modal renders" fails.
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="loadVideos() (166-201), fetchVideosPayload() (206-212), loadMoreVideos() (217-238)">
**What changes.** Nothing, if `buildSimilarUrl` reads the setting at request time. `fetchVideosPayload` goes through `fetchSimilarVideosPayload`, so both the `?id=` and feed-mode branches pick up the flag. `feedParams` is resolved once (77), but the NSFW setting must not be captured there. It must be read on every request, or a changed setting would not apply to later pages.

**Race the plan does not cover.** `loadMoreVideos` drops a stale result (`current !== pager`, 224), as the plan says. `loadVideos` itself does not: it assigns `pager` (176), awaits `pager.next()` (177), then writes `state.rows` unconditionally (180-189). If the checkbox fires while the initial `loadVideos` (113) or a `resetLikes` reload (125) is in flight, whichever request resolves last wins. The feed can then render rows fetched under the old setting. Guard it with a `pager` identity check after the await, as `video-page/index.ts:337` does (`if (current !== similarPager) return`).

**Regression risk: medium.** A toggle during the first load can show NSFW rows after the visitor turned the filter on.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadSimilarVideos() (lines 314-349): no code change">
**What changes.** Nothing. It calls `fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: "48", apiBase }, exclude)` (330-332), so it picks up the stored setting through `buildSimilarUrl`. The page has no control of its own, as the plan says.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="loadPage() (lines 147 on): no code change">
**What changes.** Nothing. It calls `fetchSearchResults` (159-165), which reads the setting per request. Paging uses the Engine's filtered `total`, so pages stay consistent.

**Regression risk: low.**
</impact>
<impact path="client/frontend/dist/index.html" element="the built frontend bundle (client/frontend/dist/*, tracked in the repo, not gitignored)">
**What changes.** The source changes do not reach the checked-in bundle until it is rebuilt. Examples of stale files: `dist/assets/index-C2Uv7NaS.js`, `dist/index.html:69`, `dist/videos.html:69`. Whether dist is regenerated as part of a build or a deploy step is not established here.

**Regression risk: low.** A stale dist would ship without the control. The Engine would still filter by default, so visitors would never see NSFW rows, but could not opt in.
</impact>
<impact path="tests/active/test_similar.py" element="_reference() (lines 1062-1066) in the ordered-feed paging test">
**What changes.** `_reference` calls `fetch_ordered_page(dataset, order, REFERENCE_DEPTH, 0, error_threshold=threshold)` at the data-layer default (include). The HTTP pages it is compared with carry no `nsfw`, so they are now filtered.

The comparison holds only while the live `whitelist.db` (read through `conftest.py`) has no `nsfw=1` row inside the reference depth. That is not a NULL-only fixture, contrary to the plan's "the fixtures leave nsfw NULL". Make `_reference` pass `include_nsfw=False` so the test pins the filtered production default.

**Regression risk: medium-high.** It depends on the data.
</impact>
<impact path="tests/active/test_similar.py" element="ANN_CHILD (606-630) and the assertion at line 849 in test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored">
**What changes.** The live raw-vector route is now filtered, but the child's `fetch_metadata(db, rowids, error_threshold=...)` (626) is not. The assertion `len(vector_before) == VECTOR_LIMIT (96)` and the page equality both fail if the seed's top-96 neighbours include an NSFW row. The child must pass `include_nsfw=False`, and the length check must allow fewer than 96 rows, because the vector path has no refill. Alternatively the request adds `&nsfw=1`.

The same test also asserts:
- `len(home["rows"]) == BATCH_SIZE` (858, 883): the filtered mix must still fill 48. `.un/memory` already records this assertion as intermittent (47 rows once).
- `len(search rows) == 20` (855, 877).

**Regression risk: medium-high.**
</impact>
<impact path="tests/active/test_similar.py" element="_DEBUG_CHILD (406-442) and _FAILING_SIMILAR_CHILD (514-553): stubs of _handle_random with a fixed 4-argument signature">
**What changes.** Nothing, as long as `_handle_similar` keeps calling `self._handle_random(limit, include_debug, request_id, started_at)`. Both harnesses build `self.server` as a `SimpleNamespace` with only `default_limit`, `refresh_similarity_cache` and `recommendations_debug_enabled`. The new parse and set code in `_handle_similar` must not read any other `server` attribute before the random branch.

**Regression risk: medium** if the flag is threaded through as an argument.
</impact>
<impact path="tests/active/test_similar.py" element="up-next fill tests (816-833 short-seed 48/30-row fill, 887-897 ten refreshes)">
**What changes.** No code change is needed, but they now run filtered on the live dataset. They assert full pages (`len(rows) == limit`, `== UPNEXT_PAGE`). For the `linux` and `cooking` seeds this holds unless their neighbourhoods contain NSFW rows and hit the stop rule described in the `get_upnext_candidates` entry.

**Regression risk: low-medium.**
</impact>
<impact path="tests/active/test_random_cache.py" element="_seed_servable_cache() (193-199), the live-Engine feed assertions (776-778, 815-828, 872-879) and the SimpleNamespace owner contract (line 19, 176)">
**What changes.**
- **Seeding.** `_seed_servable_cache` picks the first 20 rowids passing the error threshold. It does not check `nsfw`. The random feed (`/recommendations?random=1`, no `nsfw`) is now filtered, and with a 20-row cache every redraw returns the same window (offset 0). `set(rowids) <= set(seeded)` still holds unless all 20 are NSFW, in which case the SQL fallback returns rows outside the seed set and the assertion fails. Adding `AND (v.nsfw IS NULL OR v.nsfw = 0)` to the seeding query (196) makes this robust.
- **Refresh across a swap.** `test_positive_interval_swaps_...` (801-839) asserts `foreign == []`: after each swap, a feed page holds only the current file's rowids. A multi-draw refill that straddles a swap can mix old-file and new-file rowids. The test assumes that nothing swaps within one request (comment at 820).
- **Owner contract.** The in-process tests use a `SimpleNamespace(random_cache_db, random_cache_lock)` owner. The refill must not need more attributes than `fetch_random_rows_from_cache` already uses (`random_cache_db`, `random_cache_lock`, `db`, `db_lock`).

**Regression risk: low-medium.**
</impact>
<impact path="tests/active/test_random_videos.py" element="fetch_ordered_page / fetch_popular_videos / fetch_random_rows calls at the default (142-160, 238-249, 309-312)">
**What changes.** Nothing. The default is include, so the SQL is unchanged. This file is the natural place for the new data-layer tests, using a fixture with `nsfw = 1`, `0` and NULL rows:
- filter on with and without an error threshold, which catches the WHERE-composition trap;
- `fetch_popular_videos` subquery placement;
- ordered paging without gaps across the filtered order;
- the `fetch_random_rows_from_cache` refill and its cap.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_metadata.py" element="fetch_metadata_by_ids / fetch_metadata_by_uuids at the default; tests/active/test_internal_client_reads.py likewise">
**What changes.** Nothing. The 29-key row (`ROW_KEYS`, 34) is unchanged and the default is include. New tests for `fetch_metadata_by_ids(include_nsfw=False)` across a multi-pair chunk would pin the parentheses rule (the issue-33 class of bug).

**Regression risk: low.**
</impact>
<impact path="tests/active/test_video.py" element="similars_stack RecommendationBuilderDeps construction (line 219) and the similars GET case (SIMILAR at 79, seed at 529-552)">
**What changes.**
- The keyword construction at 219 omits `fetch_include_nsfw`, so it needs the default.
- The neighbour `v2` (542) has a NULL `nsfw` and the seed `v1` has `0` (538), so the filtered `/videos/v1/similar` still answers `v2`.
- The refresh case writes `nsfw = 1` to `v1` (SOURCE at 70). `v1` is the seed, not a listed row, so nothing changes.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/tests/test_recommendations_likes_limit.py" element="_DummySimilarHandler tests (22-126) patching clear_request_context with exact call counts">
**What changes.** Nothing, as long as the flag is set inside `_handle_similar`, which these tests stub (36-38), and not in `_handle_similar_request`. The tests assert `clear_context_mock.assert_not_called()` on 400 paths (71) and `assert_called_once()` on the pass path (96).

**Regression risk: low.**
</impact>
<impact path="tests/active/test_frontend_feed_params.py" element="RUNNER (40-63) and bundles (123-124)">
**What changes.** The existing cases pass: empty storage means filter on, so no `nsfw` parameter, and only `mode` entries are read (58). The bundle of `feed-params.ts` exports named symbols (124), so new helpers need no change there. This harness (in-memory `localStorage`, `STORAGE_KEY` injection) is the natural home for the new storage tests:
- missing, corrupt and "off" values;
- a `setItem` that throws, with the in-memory fallback;
- `buildSimilarUrl` carrying `nsfw=1` only when the filter is off, with and without feed params.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_frontend_blocks.py" element="keyless comparisons in _seed_and_targets (89-97) and the bundled upnext/search fetches (37-39); likewise test_frontend_reactions.py, test_frontend_upnext_pager.py, test_frontend_video_page.py, test_frontend_video_page_similars.py">
**What changes.** Nothing expected. Both the direct gateway calls and the bundled frontend fetches send no `nsfw`, so both sides are filtered alike.

**Not opened.** I did not open `tests/active/test_blocks.py`, `test_dislikes.py` or `test_profiles.py`. They exercise gateway filtering on feeds and search and would see filtered Engine pages. Any of them that compares against an unfiltered data-layer reference, or needs a specific (possibly NSFW) row to appear, would need checking.

**Regression risk: low (uncertain for the unopened files).**
</impact>
<impact path="client/frontend/src/pages/likes/index.ts" element="likes page listing (not in the plan's coverage)">
**What changes.** Nothing under the plan. The likes list resolves through the gateway and `/internal/videos/metadata`, which stays include. Liked NSFW videos therefore stay visible there. The plan's coverage lists feeds, up-next, search and the random fallback, but not this page.

I did not open this file. Whether the requirement "every video list the site requests from the Engine" covers it is a question for the plan owner.

**Regression risk: none (scope question).**
</impact>
</impacts>


## Documentation to update

- [x] `engine/server/README.md` - updated: Added an `nsfw` query-parameter bullet to the Notes section of `engine/server/README.md`, after the `seed` bullet.
- [x] `client/README.md` - updated: Added a gateway bullet in `client/README.md` for the `nsfw` query parameter: which routes allow it, that it is forwarded unstripped, and how it differs from block/dislike filtering.
- [x] `client/frontend/README.md` - updated: I added the NSFW setting to `client/frontend/README.md`, widened the `feed-params.ts` bullet to cover it, and added `/api/v1/search/videos` to the list of gateway routes.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md now covers the NSFW filter: section 1, the up-next pool and its ANN fallback, the similarity and random caches, and the layer sources and pools.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: LAYER_PARAMS.md now covers how the random cache and the up-next fallback work when the NSFW filter is on.
- [x] `CONTEXT.md` - updated: I added an **NSFW filter** term to the `CONTEXT.md` glossary and named it in the **Block** entry as one more thing a block is distinct from.
- [x] `docs/project/issues/36-nsfw-filter.md` - updated: Issue 36 is marked `complete`, written to `docs/project/issues/archive/36-nsfw-filter.md`, and has a "Delivered" comment. **You need to delete the old copy at `docs/project/issues/36-nsfw-filter.md` by hand, because I have no delete tool.**
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - updated: I added the NSFW filter to the pipeline diagram: a new request-context node after the request, and NSFW listed in the similarity candidate filters (node S) and the up-next pool filters (node U2).
- [x] `docs/project/adr/` - updated: Added ADR-0007 (`docs/project/adr/0007-nsfw-filter-default-at-request-edge.md`), which records that the NSFW filter's default is set at the request edge and that the data layer defaults to unfiltered.
- [x] `DEPLOYMENT.md` - out of scope: Nothing it says has become false. Line 288's "Without the header, reads pass through unfiltered" is about the Client backend's block and dislike filtering, which is still true: the gateway does no NSFW filtering. The NSFW contract belongs in client/README.md and engine/server/README.md. Line 263 ("up to three searches, from nprobe 32 / k 5000 up to nprobe 128 / k 20000") still holds, because the widened stop rule is bounded by the same caps. The random cache needs no rebuild and there is no new setting, unit or environment variable, so nothing operational changes. Line 258 already points to OVERVIEW.md for the up-next pool.
- [x] `client/frontend/src/data/search.ts` - out of scope: Phase 4 already rewrote the module comment (lines 4-8). It now names five gateway-allowed parameters (`q`, `page`, `limit`, `sort`, `nsfw`) and says `nsfw=1` goes only when the filter is off, which matches the delivered code.

## Implementation plan

## Draft: NSFW filter (issue 36)

**Note on the prompt.** The "ladder the draft is written against" slot arrived unfilled (a literal `{rat_tail_ladder}` placeholder). I drafted against the high-level plan and the requirements, and checked against both below. If a specific ladder was meant, the checks need re-running against it.

### 1. What has to be tested (drafted first, so the code is shaped to it)

| # | Behaviour | Where | Fixture |
|---|---|---|---|
| T1 | `_parse_include_nsfw` returns True only for `"1"`; False for `None`, `""`, `"0"`, `"01"`, `"true"`, `"yes"`, `"on"`, `" 1"` | new unit test beside `test_similar.py` | none |
| T2 | `fetch_random_rows`, `fetch_recent_videos`, `fetch_popular_videos` and `fetch_ordered_page` with `include_nsfw=False`, with and without `error_threshold`: no `nsfw = 1` row, NULL and 0 rows kept, and the SQL is valid in all four combinations (catches the `WHERE … WHERE` trap) | `tests/active/test_random_videos.py` | in-memory db with `nsfw` = 1 / 0 / NULL rows |
| T3 | `fetch_popular_videos(limit=n, include_nsfw=False)` returns n rows when at least n allowed rows exist (the predicate sits inside the `popular_ids` subquery) | same | NSFW rows at the top of the Hot order |
| T4 | Ordered paging: concatenating `fetch_ordered_page(..., offset=k*size, include_nsfw=False)` pages equals one filtered page of the whole order (no gap, no repeat) | same | same |
| T5 | `fetch_random_rows_from_cache(include_nsfw=False)` fills `limit` across redraws; makes at most `RANDOM_CACHE_NSFW_MAX_DRAWS` draws; stops after a draw adds no unseen rowid (small cache); returns `[]` on an all-NSFW cache; with `include_nsfw=True` makes exactly one draw and returns what it returns today | `tests/active/test_random_cache.py` style (`SimpleNamespace` owner with `random_cache_db`, `random_cache_lock`, `db`, `db_lock`) | cache of rowids mixing NSFW and allowed |
| T6 | `fetch_metadata` / `fetch_metadata_by_ids(include_nsfw=False)` over a multi-pair chunk drops every NSFW pair, not only the last (the issue-33 parentheses rule); `fetch_metadata_by_uuids` is unchanged | `tests/active/test_metadata.py` | multi-pair entries |
| T7 | `lexical_candidates(..., include_nsfw=False)` with `limit=n` returns n allowed rows when NSFW rows rank first; `search_videos` `total` counts only allowed rows | new search test | FTS fixture |
| T8 | `get_upnext_candidates` with `include_nsfw=False`: NSFW entries leave the pool before the author cap and the count; a ladder step whose new hits are all NSFW does not stop the ladder while the raw hit count still grows; with `include_nsfw=True` the step and stop sequence is today's | similarity-candidates test with a stub `search_similar_above` | stub hits |
| T9 | Builder: the four closures and the like-source wrapper read the getter on **every** call (flip the getter between two calls and see both values arrive); `RecommendationBuilderDeps` built without `fetch_include_nsfw` defaults to filtered | builder unit test | fake deps recording kwargs |
| T10 | Live Engine, no `nsfw` param: every listing path returns no `nsfw = 1` row. Paths: `mode=` recommendations, hot, recent, random, popular; `id=` up-next on POST `/recommendations`, `/videos/similar` and GET `/videos/{id}/similar`; `random=1`; the raw-vector path; search. With `nsfw=1` the same paths may include them | `tests/active/test_similar.py` | live `whitelist.db` via conftest |
| T11 | Gateway: `nsfw` is in the allowlist for the three routes; `nsfw=1` is forwarded verbatim, `nsfw=` is dropped; `nsfw` on `/api/video` is still a 400 | new gateway test | none |
| T12 | Frontend storage: missing, corrupt and `"on"` values read as filter on; only `"off"` reads as off; a throwing `setItem` still switches the in-page value; `buildSimilarUrl` carries `nsfw=1` only when off, with and without feed params; `fetchSearchResults` likewise | `tests/active/test_frontend_feed_params.py` harness | in-memory `localStorage` |
| T13 | Home: the checkbox appears in all three profile states (keyless, key-holding, issued-key); toggling it reloads the feed with the new flag; a toggle during an in-flight first load does not render the stale page | bundled DOM test like `test_frontend_video_page.py` | stub fetch |

**Existing tests that change (data-dependent, per the impact inventory).**
- `test_similar.py::_reference` calls `fetch_ordered_page(..., include_nsfw=False)`, pinning the filtered production default.
- `ANN_CHILD` passes `include_nsfw=False` to `fetch_metadata`. The line-849 check becomes `len(vector_before) <= VECTOR_LIMIT` plus equality with the child's page, because the vector path has no refill.
- `test_random_cache._seed_servable_cache` adds `AND (nsfw IS NULL OR nsfw = 0)` to its seeding query.

### 2. Module map

| Layer | File | Change |
|---|---|---|
| Engine edge | `api/handlers/similar.py` | parser; set the flag in `_handle_similar`; read it in `_fetch_random_rows`, `_handle_ordered_feed`, `_handle_seed_with_embedding`, `_handle_vector_search`; parse it in `_handle_search` |
| Engine edge | `api/request_context.py` | `set_request_include_nsfw` / `fetch_request_include_nsfw`; clear |
| Wiring | `api/server.py` | `fetch_include_nsfw=fetch_request_include_nsfw` |
| Mixer deps | `api/recommendations/builder.py` | new dep field (last, defaulted); closures pass the flag; like-source wrapper |
| Data | `data/metadata.py` | `NSFW_ALLOWED_SQL` constant; `include_nsfw` on `fetch_metadata`, `fetch_metadata_by_ids`, `_select_pairs`, `_select_metadata` |
| Data | `data/random_videos.py` | `include_nsfw` on the five fetches; condition-list WHERE for three of them; `RANDOM_CACHE_NSFW_MAX_DRAWS`; the redraw loop |
| Data | `data/similarity_candidates.py` | policy fields; `_build_rows` keyword; the filter-on ladder stop rule |
| Data | `data/search.py` | `include_nsfw` on `lexical_candidates`, `vector_candidates`, `search_videos` |
| Gateway | `client/backend/server.py` | `"nsfw"` added to three allowlist sets |
| Frontend | `data/feed-params.ts` | key `nsfwFilter:v1`, in-memory value, read, set and query-entry helpers |
| Frontend | `data/videos.ts`, `data/search.ts` | append `nsfw=1` when off; rewrite the search comment |
| Frontend | `pages/videos/index.ts`, `videos.css` | checkbox in all three branches; stale-load guard in `loadVideos`; one small CSS rule |

No new files. `ann.py`, `internal_client_reads.py`, `video.py`, the sources and the generators are untouched.

### 3. Engine edge

**`request_context.py`**, following the `excluded_keys` pattern:
```python
def set_request_include_nsfw(value: bool) -> None:
    """Store whether the request opted in to NSFW-flagged rows (nsfw=1)."""
    _REQUEST_CONTEXT.include_nsfw = bool(value)


def fetch_request_include_nsfw() -> bool:
    """Return whether the request includes NSFW-flagged rows; unset means filtered."""
    return bool(getattr(_REQUEST_CONTEXT, "include_nsfw", False))
```
- `clear_request_context` gains `if hasattr(_REQUEST_CONTEXT, "include_nsfw"): delattr(_REQUEST_CONTEXT, "include_nsfw")`.
- Its docstring becomes "Clear request-scoped likes, centroids, excluded keys, the NSFW flag and request id."
- **Invariant:** unset reads as False (filtered), so any path that forgets to set the flag fails safe.

**`handlers/similar.py` parser**, beside `_parse_bool`:
```python
def _parse_include_nsfw(value: str | None) -> bool:
    """Only the exact value "1" includes NSFW-flagged rows; missing, blank or anything else ("true", " 1", "01") filters them."""
    return value == "1"
```
**Whitespace decision: no strip.** `parse_qs` already drops blank values and the gateway strips before forwarding, so only a direct Engine call can present `" 1"`, and the strictest reading of "exactly `1`" treats that as filtered. `_parse_bool` is deliberately not reused.

**`_handle_similar`.** It is the first statement inside the existing `try:` (line 1037), so the `finally: clear_request_context()` clears it, and the debug 403 returns before it:
```python
        try:
            set_request_include_nsfw(_parse_include_nsfw(params.get("nsfw", [None])[0]))
            seeded = ...
```
It reads only `params`, not `self.server`, so the `_DEBUG_CHILD` and `_FAILING_SIMILAR_CHILD` `SimpleNamespace` harnesses are unaffected. `_handle_random`'s four-argument signature is unchanged.

**Readers.** Every branch reads the context rather than taking a parameter, so stubbed signatures stay valid:
- `_fetch_random_rows`: `include_nsfw = fetch_request_include_nsfw()` is passed to both `fetch_random_rows_from_cache(..., include_nsfw=include_nsfw)` and `fetch_random_rows(..., include_nsfw=include_nsfw)`. The `if rows: return rows` rule is unchanged. This covers `_handle_random`, the `_handle_home` empty-mix fallback and the `seed.get("random")` branch.
- `_handle_ordered_feed`: `include_nsfw = fetch_request_include_nsfw()` is read once before the loop and passed to `fetch_ordered_page`. The OFFSET then walks the filtered order.
- `_handle_seed_with_embedding`: `UpnextPoolPolicy(..., refresh_cache=refresh_cache, include_nsfw=fetch_request_include_nsfw())`.
- `_handle_vector_search`: `fetch_metadata(..., include_nsfw=fetch_request_include_nsfw())`.
- `_handle_search`: not under a request context, so it parses directly with `include_nsfw = _parse_include_nsfw(params.get("nsfw", [None])[0])` and passes `include_nsfw=include_nsfw` to `search_videos`.

The imports gain `set_request_include_nsfw` and `fetch_request_include_nsfw`.

**`server.py`.** Add `fetch_request_include_nsfw` to the `request_context` import and `fetch_include_nsfw=fetch_request_include_nsfw,` as the last keyword of `RecommendationBuilderDeps(...)`.

### 4. Mixer (`builder.py`)

```python
from dataclasses import dataclass, replace
...
from data.similarity_candidates import SimilarityCandidatesPolicy

@dataclass(frozen=True)
class RecommendationBuilderDeps:
    ...
    fetch_excluded_keys: Callable[[], set[str]]
    # Last and defaulted: frozen dataclass, keyword-built in tests; the default is the filtered production default.
    fetch_include_nsfw: Callable[[], bool] = lambda: False
```
The builder already imports the sources, which import `data.similarity_candidates`, so the new import adds no dependency edge.

Each closure reads the flag **per call**. Reading it at build time would freeze it at the startup value:
```python
    def fetch_random_rows_filtered(conn: Any, limit: int) -> list[dict[str, Any]]:
        """Handle fetch random rows filtered."""
        return deps.fetch_random_rows(
            conn, limit, error_threshold=settings.video_error_threshold, include_nsfw=deps.fetch_include_nsfw()
        )
```
The same change applies to `fetch_random_rows_from_cache_filtered`, `fetch_recent_videos_filtered` and `fetch_popular_videos_filtered`.

The like-source wrapper is handed to **both** `ann_deps` and `cached_deps`, so `likes_source` and `likes_fallback` are both covered:
```python
    def get_similar_candidates_filtered(
        server: Any, seed: dict[str, Any], limit: int, policy: Any = None
    ) -> list[dict[str, Any]]:
        """Run the like-layer similarity lookup with the request's NSFW flag on its policy."""
        policy = policy if policy is not None else SimilarityCandidatesPolicy()
        return deps.get_similar_candidates(server, seed, limit, replace(policy, include_nsfw=deps.fetch_include_nsfw()))
```

### 5. Data layer

**Shared predicate.** In `data/metadata.py`:
```python
# Unflagged (NULL) videos pass: only rows the crawler flagged nsfw = 1 are left out.
NSFW_ALLOWED_SQL = "(v.nsfw IS NULL OR v.nsfw = 0)"
```
`random_videos.py` and `search.py` import it, so there is one spelling of the rule. Every function below takes `include_nsfw: bool = True`, placed after `error_threshold`. **Invariant:** at the default, the parameter list is today's and the result rows are today's (only whitespace in the SQL text may differ).

**`metadata.py`.**
- `fetch_metadata`: `nsfw_clause = "" if include_nsfw else f"AND {NSFW_ALLOWED_SQL}"`, rendered on the line after `{error_clause}`.
- `fetch_metadata_by_ids(conn, entries, error_threshold=None, include_nsfw=True)` → `_select_pairs(conn, "video_id", entries, error_threshold, include_nsfw)` → `_select_metadata(conn, f"({conditions})", params, error_threshold, include_nsfw)`. The `_select_pairs` and `_select_metadata` parameters default to True, so `fetch_metadata_by_uuids` (for `/internal/*`) is untouched.
- The clause goes after `{error_clause}` and relies on the existing parentheses around the pair OR (comment at 155).

**`random_videos.py`.** `fetch_random_rows` and `fetch_recent_videos` switch to the condition list `fetch_ordered_page` already uses:
```python
    conditions: list[str] = []
    params: list[Any] = []
    if error_threshold is not None and error_threshold > 0:
        conditions.append("(v.error_count IS NULL OR v.error_count < ?)")
        params.append(error_threshold)
    if not include_nsfw:
        conditions.append(NSFW_ALLOWED_SQL)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
```
With the filter off this renders the same `WHERE (v.error_count …)` or nothing, with the same params `[threshold, limit]` or `[limit]`.

`fetch_popular_videos` uses the same list, and `{where_clause}` replaces `{error_clause}` **inside the `popular_ids` subquery**, so its `LIMIT ?` counts allowed rows. It ends with `params += [limit, limit]`.

`fetch_ordered_page` adds one line after the recent condition: `if not include_nsfw: conditions.append(NSFW_ALLOWED_SQL)`.

**Random cache redraw.** The flag is read live at draw time and the cache schema is unchanged:
```python
# Filter-on draws per request before a short Random page is returned as is; the cache holds no NSFW flag, so allowed rows are found by redrawing.
RANDOM_CACHE_NSFW_MAX_DRAWS = 4


def fetch_random_rows_from_cache(
    server: Any, limit: int, error_threshold: int | None = None, include_nsfw: bool = True
) -> list[dict[str, Any]]:
    """Return random videos using the precomputed rowid cache; with the filter on, redraw windows until the page is full or the draws run out."""
    if server.random_cache_db is None or limit <= 0:
        return []
    draws = 1 if include_nsfw else RANDOM_CACHE_NSFW_MAX_DRAWS
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    for _ in range(draws):
        # The handle is re-read under the lock on every draw: a refresh swap closes the old one once the lock is free.
        with server.random_cache_lock:
            rowids = fetch_random_rowids(server.random_cache_db, limit) if server.random_cache_db is not None else []
        fresh = [rowid for rowid in rowids if rowid not in seen]
        if not fresh:
            break
        seen.update(fresh)
        with server.db_lock:
            metadata = fetch_metadata(server.db, fresh, error_threshold=error_threshold, include_nsfw=include_nsfw)
        for rowid in fresh:
            meta = metadata.get(rowid)
            if meta:
                rows.append(meta)
        if len(rows) >= limit:
            break
    return rows[:limit]
```
**Invariants of the loop:**
- **Filter off equals today.** It makes one draw. `seen` is empty during the first draw, so a window is resolved exactly as today, duplicates included, and at most `limit` rows come back.
- **Lock discipline.** The two locks are taken in turn, never nested, and the handle never lives across draws. That respects `swap_readonly_connection` and the generator's lock use.
- **Early stop.** A draw that adds no unseen rowid ends the loop, which covers a cache no bigger than `limit`, where every draw is the offset-0 window.
- **Empty result.** An all-NSFW result is `[]`, so the caller's SQL fallback runs, as today.
- **Owner attributes.** The loop uses only `random_cache_db`, `random_cache_lock`, `db` and `db_lock`.
- **Cost.** Worst case per call is 4 windows, 4 `COUNT(*)` reads and 4 metadata reads. Inside the random generator's 5-attempt loop that is at most 20 of each per layer fill, and only for filter-on requests.

**`similarity_candidates.py`.**
- `SimilarityCandidatesPolicy.include_nsfw: bool = True`, added last.
- `UpnextPoolPolicy.include_nsfw: bool = True`, added after `refresh_cache`.
- `_build_rows(server, entries, seed, limit, include_nsfw: bool = True)` passes the flag to both `fetch_metadata_by_ids` calls. An NSFW entry then finds no metadata and is skipped before the author cap and before the `limit` count.
- `get_similar_candidates` calls `_build_rows(server, entries, seed, limit, policy.include_nsfw)`. `_compute_candidates` and `_write_cache` run before it and stay unfiltered, so the shared cache is never NSFW-filtered.
- `_upnext_rows` calls `_build_rows(server, floored, seed, policy.top_k, policy.include_nsfw)`.

**Ladder stop rule (decision; fixes the gap the inventory found).** With the filter on, a step whose new hits are all NSFW would stop the ladder below `target_min_pool` even though widening could still find allowed rows. The fix keeps going while the raw ANN hit count still grows:
```python
        hits: list[dict[str, Any]] = []
        while True:
            before = len(rows)
            hits_before = len(hits)
            hits, restored = search_similar_above(...)
            ...
            # Filter on: a step whose new hits were all filtered out still widens while the ANN keeps finding more; filter off stops exactly as before.
            if len(rows) <= before and (policy.include_nsfw or len(hits) <= hits_before):
                break
```
- **Filter off (`include_nsfw=True`):** the condition reduces to today's.
- **Filter on:** the ladder is still bounded by `max_nprobe` and `max_search_limit`. It stops when widening finds no new hit above the floor.
- **Side effect:** it also keeps widening past hits removed by exclude or moderation for filter-on requests. That is extra ANN work within the existing caps, visible in `_log_upnext_pool` steps.

**`search.py`.**
- `lexical_candidates(db, match_expression, limit, sort="relevance", include_nsfw=True)`: `nsfw_clause = "" if include_nsfw else f"AND {NSFW_ALLOWED_SQL}"` goes on the line after `WHERE videos_fts MATCH ?`. The params tuple is unchanged, and `LIMIT` counts allowed rows.
- `vector_candidates(server, text, limit, include_nsfw=True)` passes the flag to `fetch_metadata`.
- `search_videos(..., vector_weight=1.0, include_nsfw=True)` calls `lexical_candidates(conn, match_expression, candidate_pool, sort, include_nsfw=include_nsfw)` and `vector_candidates(server, plain_text, candidate_pool, include_nsfw=include_nsfw)`. Fusion, `total` and slicing run over filtered lists.

### 6. Gateway (`client/backend/server.py`)

```python
    "/recommendations": {"id", "host", "limit", "random", "debug", "mode", "user_id", "nsfw"},
    "/videos/similar": {"id", "host", "limit", "random", "debug", "mode", "user_id", "nsfw"},
    ...
    "/api/v1/search/videos": {"q", "page", "limit", "sort", "nsfw"},
```
Nothing else changes. The existing sanitiser strips values and drops blank ones, and forwards the rest with `urlencode`. The block and dislike row filter never looks at `nsfw`.

### 7. Frontend

**`data/feed-params.ts`**, appended after `readStoredFeedParams`. The module docstring changes to "…the home feed's parameters, and the NSFW setting every video list sends". The `FeedParams` comment stays true, because the NSFW setting has its own key.
```ts
// The NSFW setting, kept apart from feedParams:v1: it applies to search and the video page too, and a ?mode= visit must not reset it.
const NSFW_FILTER_KEY = "nsfwFilter:v1";

// Set on every change, so the choice holds on this page even when storage refuses the write.
let nsfwFilterInMemory: boolean | null = null;

/**
 * Whether NSFW-flagged videos are hidden: true unless the visitor turned it off; missing, unreadable or corrupt storage means on.
 */
export function readNsfwFilter(): boolean {
  if (nsfwFilterInMemory !== null) return nsfwFilterInMemory;
  try {
    return window.localStorage.getItem(NSFW_FILTER_KEY) !== "off";
  } catch {
    // Unreadable storage (private mode) keeps the filter on.
    return true;
  }
}

/**
 * Turn the NSFW filter on or off for this page and, when storage allows, for later visits.
 */
export function setNsfwFilter(on: boolean) {
  nsfwFilterInMemory = on;
  try {
    window.localStorage.setItem(NSFW_FILTER_KEY, on ? "on" : "off");
  } catch {
    // Ignore storage failures (quota/private mode): the in-memory value above still applies on this page.
  }
}

/**
 * The Engine's query entry for the NSFW setting: nsfw=1 only when the visitor turned the filter off.
 */
export function nsfwQuery(): [string, string][] {
  return readNsfwFilter() ? [] : [["nsfw", "1"]];
}
```
**Storage values.** Only the exact string `"off"` turns the filter off; anything else, including a corrupt value, reads as on.

**`data/videos.ts`.** The import becomes `import { feedParamsToQuery, nsfwQuery, type FeedParams } from "./feed-params";`. In `buildSimilarUrl`, after the `feedParams` block and outside it, so the `?id=` and video-page up-next calls without feed params are covered:
```ts
  for (const [key, value] of nsfwQuery()) url.searchParams.set(key, value);
```
The flag is read on every URL build and never captured at page load.

**`data/search.ts`.** It imports `nsfwQuery` and, after the `sort` line, adds `for (const [key, value] of nsfwQuery()) url.searchParams.set(key, value);`. The flag is on the URL before either branch, so the keyless cache key `search:${url}` separates on and off results.

The module comment is rewritten to: "The gateway allowlists the route and exactly five query parameters (`q`, `page`, `limit`, `sort`, `nsfw`) and answers 400 for anything else, so this client sends those and nothing more; `nsfw=1` goes only when the visitor turned the NSFW filter off. A new filter needs the gateway updated in the same change."

**`pages/videos/index.ts`.**
- The import becomes `import { parseFeedMode, persistFeedParams, readNsfwFilter, resolveFeedParams, setNsfwFilter } from "../../data/feed-params";`.
- New helper beside `profileActions`:
```ts
/**
 * The "Hide NSFW videos" checkbox, shown in every profile state; a change is saved in this browser and reloads the feed.
 */
function nsfwToggle(): HTMLLabelElement {
  const label = document.createElement("label");
  label.className = "profile-nsfw";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = readNsfwFilter();
  input.addEventListener("change", () => {
    setNsfwFilter(input.checked);
    void loadVideos();
  });
  label.append(input, " Hide NSFW videos");
  return label;
}
```
- `nsfwToggle()` is appended in each branch, just before `status`:
  - issued-key view: `profileSection.append(warning, field, profileActions(copy, done), nsfwToggle(), status);`
  - key-holding view: `profileSection.append(intro, profileActions(...), nsfwToggle(), status, blocks);`
  - keyless view: `profileSection.append(intro, profileActions(create, resetLikesButton(status)), pasted, profileActions(use), nsfwToggle(), status);`
- `renderProfileSection` rebuilds on every open, so the box always shows the current value.
- **Stale-load guard in `loadVideos`.** This is outside the plan and closes the race the inventory found. A toggle during the first load, or during a `resetLikes` reload, must not render the older request's page:
```ts
    await localLikesImported;
    const current = createFeedPager(fetchVideosPayload);
    pager = current;
    const payload = await current.next();
    // A newer load (an NSFW toggle, a likes reset) replaced this pager; its own result renders instead.
    if (current !== pager) return;
```
  The `catch` gets the same `if (current !== pager) return;` first, so the declaration moves above the `try`. Before the first await, `current` is the pager `loadVideos` created.
- **`videos.css`.** One rule next to `.profile-actions`: `.profile-nsfw { display: flex; align-items: center; gap: 0.5rem; margin: 0.75rem 0; }`.

### 8. Check against the plan and the requirements (pass 1 of 3)

| Requirement / plan item | Met by | Status |
|---|---|---|
| Visitor doing nothing never sees NSFW in any list | unset context reads as filtered; frontend sends nothing by default; every listing branch passes the flag (T10) | met |
| Only `nsfw=1` includes | `_parse_include_nsfw`, exact match, no strip (T1) | met |
| Filtering in the Engine, pages filled to size | SQL predicate inside the ordered, random, recent, popular and FTS queries; `_build_rows` skip before count; cache redraw; ladder keeps widening | met, with the limitations below |
| Ordered paging neither skips nor repeats | predicate inside the ordered query; OFFSET walks the filtered order (T4) | met |
| Up-next pool about 17 deep | `_build_rows` filter plus the filter-on stop rule (T8) | met up to the ANN caps |
| Random full page; approach chosen and justified; cache schema unchanged | draw-time redraw, capped at 4; no rebuild | met up to the cap |
| Filter off identical to today | every addition is gated on `include_nsfw=False`; the cache loop makes one draw; the ladder condition reduces to today's | met |
| Browser and gateway never drop rows | only the allowlist changes; the frontend only adds a param | met |
| Gateway allowlist on three routes | §6 (T11) | met |
| Setting in `localStorage` next to `feedParams:v1`; failures mean on; write failure keeps the choice for the page | §7 feed-params (T12) | met |
| Control only in the Profile modal, all three states, no key needed, reloads the home feed | `nsfwToggle` in three branches plus `loadVideos` (T13) | met |
| Coverage: five modes, up-next (video page and `?id=`), search | `buildSimilarUrl` covers all feed and up-next calls; `fetchSearchResults` covers search | met |
| Plan: data-layer default include; `/api/video`, `/internal/*` and the ANN compute untouched | defaults True; `ann.py` and `internal_client_reads.py` not edited | met |
| Suite green | the three data-dependent tests are adjusted (§1); `RecommendationBuilderDeps` default keeps `test_video.py` building; stubs keep their signatures | met in design; must be run |

It converged on this pass. Four places depart from, or add to, the plan text, and are named here:
- **(a) The up-next ladder stop rule** changes for filter-on requests only. The plan asserts the ladder widens to `target_min_pool`, but the code did not guarantee that under the filter. Without the change the requirement's "about 17 deep" fails for NSFW-dense neighbourhoods.
- **(b) The `loadVideos` stale-result guard.**
- **(c) The shared `NSFW_ALLOWED_SQL` constant** in `metadata.py`, used in place of three copies of the literal.
- **(d) The draw cap is its own constant, `RANDOM_CACHE_NSFW_MAX_DRAWS = 4`,** in the data layer. The plan said "matching `ORDERED_FEED_MAX_CHUNKS`", but that constant lives in a handler, and the data layer must not import from handlers.

### 9. Limitations (deliberate simplifications, each with its ceiling and upgrade path)

- **Random cache, 4 draws.** A cache that is mostly NSFW can still produce a short Random page. The SQL fallback runs only on an empty result. Upgrade: top up the shortfall from `fetch_random_rows`, or store a flag column once staleness is handled.
- **Like layer.** NSFW neighbours are removed, not replaced per seed. The mixer's backfill keeps the page full, but the layer ratio shifts for NSFW-dense likes. Upgrade: read deeper per-seed lists when the filter is on.
- **Search vector half.** No refill, so the tail of long result sets gets shorter. Upgrade: overfetch the ANN search when the filter is on.
- **Raw-vector route (not in the plan's limitations).** A filter-on page is `limit` minus its NSFW hits. The frontend does not use this route. Upgrade: the same overfetch.
- **Up-next ladder.** Under the filter it keeps widening only while ANN hits grow and stops at the caps. A seed whose whole reachable neighbourhood is NSFW (a filtered visitor opening an NSFW video by link) can still return a short page. This goes in `OVERVIEW.md` §2.3.
- **Refresh swap mid-refill.** A cache swap landing between two draws of one request can mix rowids from the old and the new file in one page. The rows are still valid, unfiltered-by-staleness videos. `test_random_cache` assumes no swap within a request.
- **Checked-in `client/frontend/dist`.** It stays stale until it is rebuilt. Visitors would still be filtered by the Engine, but could not opt in.
- **Likes page.** Liked NSFW videos stay visible there, through `/internal/videos/metadata`. It is outside the plan's coverage list; flagged as a scope question for the plan owner.


### Phases

#### Phase 1 - SQL NSFW predicate in the data queries [code]

**Files touched.** engine/server/data/metadata.py (EDITED), engine/server/data/random_videos.py (EDITED), engine/server/data/search.py (EDITED)

**Checkpoint.** Seam: direct calls into the data layer on an in-memory sqlite db seeded with `nsfw` = 1 / 0 / NULL rows. This follows the existing `tests/active/test_random_videos.py` and `tests/active/test_metadata.py` harnesses. c1 is parametrized over the named functions (fetch_metadata, fetch_metadata_by_ids, fetch_random_rows, fetch_recent_videos, fetch_popular_videos, fetch_ordered_page, lexical_candidates), each with error_threshold on and off. It asserts that no returned row has nsfw = 1, that every NULL and 0 row the unfiltered call returns is still returned, and that the SQL runs in all four flag × threshold combinations (this catches a `WHERE … WHERE`). fetch_metadata_by_ids is called on a multi-pair chunk with NSFW pairs in first, middle and last position, to cover the issue-33 parentheses rule, and fetch_metadata_by_uuids is shown to be unchanged. c2 puts NSFW rows at the top of the Hot, Recent and FTS-relevance orders and asserts three things: fetch_popular_videos(limit=n, include_nsfw=False) and lexical_candidates(limit=n, include_nsfw=False) each return n rows when at least n allowed rows exist; the concatenated fetch_ordered_page(offset=k*size, include_nsfw=False) pages equal one filtered page over the whole order, with no gap and no repeat; and search_videos `total` counts only allowed rows.

**Intent.** With include_nsfw=False, the listing queries in data/metadata.py, data/random_videos.py and data/search.py apply NSFW_ALLOWED_SQL inside their SQL. NSFW-flagged rows are therefore gone before LIMIT and OFFSET are counted.

- C1 - With include_nsfw=False, fetch_metadata, fetch_metadata_by_ids, fetch_random_rows, fetch_recent_videos, fetch_popular_videos, fetch_ordered_page and lexical_candidates return no nsfw = 1 row and keep the NULL and 0 rows.
- C2 - With include_nsfw=False, the LIMIT and OFFSET of those queries count only allowed rows.

**Outcome.** ### engine/server/data/metadata.py
- New module constant `NSFW_ALLOWED_SQL = "(v.nsfw IS NULL OR v.nsfw = 0)"`. Its comment says why NULL passes: only rows the crawler flagged `nsfw = 1` are left out. `random_videos.py` and `search.py` import it, so the rule is written in one place.
- `fetch_metadata` gains `include_nsfw: bool = True` after `error_threshold`. With the filter on, `AND NSFW_ALLOWED_SQL` goes on the line after `{error_clause}`, in every 900-rowid batch.
- `fetch_metadata_by_ids` gains `include_nsfw: bool = True` and passes it through `_select_pairs` to `_select_metadata`. Both helpers take `include_nsfw: bool = True` as their last parameter. `_select_metadata` puts the same `nsfw_clause` after `{error_clause}`. Because the pair OR is already in parentheses, the clause applies to every pair in the chunk. The comment there now names both clauses.
- `fetch_metadata_by_uuids` is unchanged. It gets the helpers' default of True, so `/internal/*` lookups still return NSFW videos.
- At the default, parameters and rows are the same as before; the SQL text gains only a blank line.

### engine/server/data/random_videos.py
- Imports `NSFW_ALLOWED_SQL` from `data.metadata`.
- `fetch_random_rows`, `fetch_recent_videos` and `fetch_popular_videos` each gain `include_nsfw: bool = True`. Each now builds its WHERE from the `conditions` list that `fetch_ordered_page` already used: the error condition, then `NSFW_ALLOWED_SQL` when the filter is on, joined with AND. This means the error and NSFW conditions can't produce two WHERE clauses.
- With the filter off, the rendered WHERE and the params are the same as before: `[threshold, limit]` or `[limit]`, and `[threshold, limit, limit]` or `[limit, limit]` for popular.
- In `fetch_popular_videos` the `{where_clause}` sits inside the `popular_ids` subquery, where `{error_clause}` was, so that subquery's `LIMIT` counts only allowed rows.
- `fetch_ordered_page` gains `include_nsfw: bool = True` and adds `NSFW_ALLOWED_SQL` to its conditions after the recent-order condition, so `LIMIT`/`OFFSET` walk the filtered order.
- `fetch_random_rows_from_cache` is untouched. The redraw loop belongs to a later phase.

### engine/server/data/search.py
- Imports `NSFW_ALLOWED_SQL` from `data.metadata`.
- `lexical_candidates` gains `include_nsfw: bool = True`, which is also documented in its docstring. With the filter on, `AND NSFW_ALLOWED_SQL` goes on the line after `WHERE videos_fts MATCH ?`, so the FTS `LIMIT` counts only allowed matches. The params tuple is unchanged.
- `vector_candidates` gains `include_nsfw: bool = True` and passes it to `fetch_metadata`, so the vector half drops NSFW rows too.
- `search_videos` gains `include_nsfw: bool = True` after `vector_weight` and passes it to both halves. Fusion, `total` and page slicing then work on lists that are already filtered.

#### Phase 2 - Refill past NSFW rows outside SQL [code]

**Files touched.** engine/server/data/random_videos.py (EDITED), engine/server/data/similarity_candidates.py (EDITED)

**Checkpoint.** c1 seam: fetch_random_rows_from_cache called on a SimpleNamespace owner (random_cache_db, random_cache_lock, db, db_lock), as `tests/active/test_random_cache.py` already does. The cache is built from rowids that mix NSFW and allowed videos, and the draws are counted by wrapping fetch_random_rowids. It asserts that include_nsfw=False fills `limit` across redraws, never makes more than RANDOM_CACHE_NSFW_MAX_DRAWS draws, stops after a draw adds no unseen rowid (a cache no bigger than `limit`), and returns [] on an all-NSFW cache. It also asserts that include_nsfw=True makes exactly one draw and returns that window's rows, duplicates included. c2 seam: a new unit test on get_upnext_candidates with a stub search_similar_above that records every (nprobe, search_limit) step and returns scripted hits, where one step's new hits are all NSFW. It asserts that under UpnextPoolPolicy(include_nsfw=False) NSFW entries do not reach the author cap or the count, that the ladder continues past the all-NSFW step while the raw hit count still grows, and that it stops at the caps. Under include_nsfw=True the recorded step and stop sequence must equal today's for the same script.

**Intent.** With the filter on, the random-cache draw in data/random_videos.py and the up-next pool in data/similarity_candidates.py refill past NSFW rows instead of returning short. With the filter off, both behave as they do today.

- C1 - fetch_random_rows_from_cache(include_nsfw=False) keeps redrawing until one of three things happens: the page reaches `limit`, RANDOM_CACHE_NSFW_MAX_DRAWS draws have been made, or a draw adds no unseen rowid. With include_nsfw=True it makes exactly one draw.
- C2 - With include_nsfw=False, get_upnext_candidates drops NSFW entries before the author cap and before the count, and keeps widening the ANN ladder while the raw hit count still grows.

**Outcome.** ### engine/server/data/random_videos.py
- New constant `RANDOM_CACHE_NSFW_MAX_DRAWS = 4`, placed after the imports. It caps the filter-on draws per request. It is kept separate from `ORDERED_FEED_MAX_CHUNKS` because the data layer must not import from handlers.
- `fetch_random_rows_from_cache` gains `include_nsfw: bool = True`. It now draws in a loop: `1` draw when `include_nsfw` is True, `RANDOM_CACHE_NSFW_MAX_DRAWS` when it is False.
  - On each draw, `server.random_cache_db` is read again under `random_cache_lock`, so the handle is never kept from one draw to the next (a refresh swap closes the old handle once the lock is free). The rowids already seen are dropped, and the loop stops at the first draw that adds none.
  - The new rowids are resolved with `fetch_metadata(..., include_nsfw=include_nsfw)` under `db_lock`. The two locks are never held together.
  - Rows are appended in draw order. The loop stops once the page reaches `limit`, and the result is cut to `limit`.
- With the filter off it makes one draw, and `seen` is empty during that draw. That draw's window resolves as it does today, duplicates and rows short from `error_threshold` included.

### engine/server/data/similarity_candidates.py
- `UpnextPoolPolicy` gains `include_nsfw: bool = True`, after `refresh_cache`.
- `_build_rows` gains `include_nsfw: bool = True` and passes it to both `fetch_metadata_by_ids` calls, with and without the lock. An NSFW entry then finds no metadata and is skipped before the author cap and before the `limit` count.
- `_upnext_rows` passes `policy.include_nsfw` to `_build_rows`. Cached entries and ANN fallback hits are filtered at the same point.
- The ladder in `get_upnext_candidates` records `hits_before` on each step. The stop rule is now `len(rows) <= before and (policy.include_nsfw or len(hits) <= hits_before)`: with the filter on, a step that adds no row still widens while the raw ANN hit count grows. With the filter off the condition is the same as today's. The ladder is still bounded by `max_nprobe`/`max_search_limit`.
- The `get_upnext_candidates` docstring now mentions the NSFW filter and the new widening rule.

### Not done in this phase
The plan's code sketch also adds `SimilarityCandidatesPolicy.include_nsfw` and passes `policy.include_nsfw` from `get_similar_candidates` to `_build_rows`. Neither this phase's intent nor its checkpoint covers that, so I left it out. Phase 3's builder wrapper (`replace(policy, include_nsfw=...)`) needs it, and Phase 3's files list does not name `similarity_candidates.py`. So Phase 3 will have to make that two-line change as an unanticipated file, or the change needs to be assigned to a phase.

#### Phase 3 - Request edge, mixer wiring and gateway [code]

**Files touched.** engine/server/api/handlers/similar.py (EDITED), engine/server/api/request_context.py (EDITED), engine/server/api/server.py (EDITED), engine/server/api/recommendations/builder.py (EDITED), client/backend/server.py (EDITED), tests/active/test_similar.py (EDITED), tests/active/test_random_cache.py (EDITED)

**Checkpoint.** Seam: the live `engine` and `client_backend` fixtures from `tests/active/conftest.py`, following the HTTP tests in `tests/active/test_similar.py` and `tests/active/test_server.py`. Rows are cross-checked against the set of keys that whitelist.db flags nsfw = 1, read through the `dataset` fixture. The test first asserts that this set is non-empty and that rows from it appear in the nsfw=1 responses, so the filter assertions cannot pass vacuously. c1 is parametrized over the listing paths: mode=recommendations, hot, recent, random and popular; id= up-next on POST /recommendations, POST /videos/similar and GET /videos/{id}/similar; random=1; the raw-vector path; and search. Each path is also parametrized over nsfw missing, empty, "0", "true" and " 1", and the test asserts that no returned key is in the flagged set. It sends mode=recommendations with nsfw=1 and then without it on the same Engine, which catches the builder freezing the flag at build time. c2 sends nsfw=1 through the gateway on /recommendations, /videos/similar and /api/v1/search/videos and asserts that the requests are forwarded (200, not 400) and that flagged rows can be returned. It also asserts that nsfw on /api/video is still a 400. The existing data-dependent tests are updated in the same phase, as the draft specifies: `_reference`, `ANN_CHILD` and `_seed_servable_cache`.

**Intent.** An Engine listing request is NSFW-filtered unless it carries exactly nsfw=1. handlers/similar.py and request_context.py enforce this, and builder.py and server.py carry the flag into the mixer. client/backend/server.py forwards that opt-in on the three listing routes.

- C1 - A request to any listing path whose nsfw is anything other than exactly "1" receives no row that whitelist.db flags nsfw = 1.
- C2 - A gateway request carrying nsfw=1 on /recommendations, /videos/similar or /api/v1/search/videos reaches the Engine with the opt-in intact.

**Outcome.** ### engine/server/api/request_context.py
- New `set_request_include_nsfw(value)` / `fetch_request_include_nsfw()` pair, following the `excluded_keys` pattern. When nothing was set, the getter returns False (filtered), so any path that never sets the flag stays filtered.
- `clear_request_context` also clears `include_nsfw`. Its docstring now lists everything it clears.

### engine/server/api/handlers/similar.py
- New `_parse_include_nsfw(value)`, placed beside `_parse_bool`. It returns True only for the exact string `"1"` and does not strip. It does not reuse `_parse_bool`, which also accepts `true`, `yes` and `on`.
- `_handle_similar` sets the flag as the first statement inside its existing `try`, so the `finally: clear_request_context()` clears it. It reads only `params`, so the SimpleNamespace test harnesses and the four-argument `_handle_random` stubs are unaffected.
- The listing branches read the flag from the request context:
  - `_fetch_random_rows` passes it to both `fetch_random_rows_from_cache` and `fetch_random_rows`. This covers Random, `random=1`, the home empty-mix fallback and the random-seed branch.
  - `_handle_ordered_feed` reads it once and passes it to `fetch_ordered_page`, so OFFSET walks the filtered order.
  - `_handle_seed_with_embedding` puts it on `UpnextPoolPolicy(include_nsfw=...)`.
  - `_handle_vector_search` passes it to `fetch_metadata`. A `rat-tail:` comment records that flagged hits are dropped, not refilled.
- `_handle_search` never enters `_handle_similar`, so it parses `nsfw` itself and passes `include_nsfw=` to `search_videos`.

### engine/server/api/recommendations/builder.py
- `RecommendationBuilderDeps` gains `fetch_include_nsfw: Callable[[], bool] = lambda: False`. It is the last field and has a default, so the keyword construction in `tests/active/test_video.py` still builds.
- The four `*_filtered` closures (random, random-cache, recent, popular) pass `include_nsfw=deps.fetch_include_nsfw()` on every call, not once at build time.
- New `get_similar_candidates_filtered` wrapper. It uses `replace(policy, include_nsfw=...)` and falls back to `SimilarityCandidatesPolicy()` when the policy is None. It is handed to both `AnnSimilarFromLikesDeps` and `CachedSimilarFromLikesDeps`, so both the like source and its fallback are filtered.
- Imports `replace` and `SimilarityCandidatesPolicy`.

### engine/server/api/server.py
- Imports `fetch_request_include_nsfw` and wires it in as `fetch_include_nsfw=` on `RecommendationBuilderDeps`.

### engine/server/data/similarity_candidates.py (unanticipated, see below)
- `SimilarityCandidatesPolicy` gains `include_nsfw: bool = True`.
- `get_similar_candidates` passes `policy.include_nsfw` to `_build_rows`, with a comment that the cache written before it stays unfiltered.

### client/backend/server.py
- `"nsfw"` is added to `PROXY_ALLOWED_QUERY_PARAMS` for `/recommendations`, `/videos/similar` and `/api/v1/search/videos`. `/api/video` still refuses it with a 400.
- New `PROXY_UNSTRIPPED_QUERY_PARAMS = frozenset(("nsfw",))`. Both proxy sanitisers (GET and POST) forward `nsfw` without stripping it; every other parameter is still stripped.
  - This departs from the plan, which said the existing sanitiser needed no change. Stripping would turn `" 1"` into the opt-in at the gateway, and the checkpoint's gateway ` 1` case forbids that.
  - Now the value is URL-encoded as-is (`+1`) and the Engine alone decides whether it is exactly `1`. Empty values are still dropped by `parse_qs`, so they reach the Engine as missing (filtered).

### tests/active/test_similar.py
- `_reference` calls `fetch_ordered_page(..., include_nsfw=False)`, because the HTTP pages it is compared with carry no `nsfw` and are now filtered (Recent's sixth row is flagged). The module docstring bullet and the helper docstring say so.
- `_vector_page` sends `&nsfw=1`, and the module docstring says so.
  - This departs from the draft, which had `ANN_CHILD` pass `include_nsfw=False` and loosened the check to `len <= VECTOR_LIMIT`. That would have weakened the nprobe control.
  - I observed that the filtered music-seed page is 95 rows (one flagged hit), while with `nsfw=1` it is 96. With the opt-in the route stays a pure ANN search, so `ANN_CHILD` and the strict `== VECTOR_LIMIT` check are unchanged.

### tests/active/test_random_cache.py
- The `_seed_servable_cache` seeding query also requires `(v.nsfw IS NULL OR v.nsfw = 0)`, so it keeps matching what the random feed serves to a request without `nsfw`. I checked the 20 rowids it currently picks: all have `nsfw = 0`, so the seeded set does not change.

### Observed with probes (not the checkpoint)
- `linux` and `cooking` up-next still fill 48, 30 and 8 rows with no flagged row.
- `q=music&limit=20` still returns 20 rows, and home `{}` still returns 48 rows in mode `home`.
- `mode=recommendations` with flagged likes serves flagged rows with `nsfw=1` and none without it or with `nsfw=true`, alternating on the same Engine.
- Gateway `mode=recent`: `nsfw=1` gives 1 flagged row. Missing, `%201` and `true` give none, each on a full 48-row page.

**Beyond the files named.** engine/server/data/similarity_candidates.py: `SimilarityCandidatesPolicy.include_nsfw` plus passing `policy.include_nsfw` into `_build_rows` in `get_similar_candidates`. Without it, the builder's like-layer wrapper (`replace(policy, include_nsfw=...)`) raises TypeError and the mix's like layer serves flagged rows. The Phase 2 outcome already recorded this gap. It is two lines.
tests/tmp/test_probe_36_p3_impl.py: my throwaway probe, which ends in a deliberate `assert False`. I have no delete tool, so it needs deleting by hand.

#### Phase 4 - Browser NSFW setting and Profile control [code]

**Files touched.** client/frontend/src/data/feed-params.ts (EDITED), client/frontend/src/data/videos.ts (EDITED), client/frontend/src/data/search.ts (EDITED), client/frontend/src/pages/videos/index.ts (EDITED), client/frontend/src/pages/videos/videos.css (EDITED)

**Checkpoint.** c1 seam: the bundled node harness of `tests/active/test_frontend_feed_params.py`, with in-memory localStorage. It asserts that storage values that are missing, "on", corrupt, or unreadable (getItem throws) read as filter on and add no nsfw param. Only "off" makes buildSimilarUrl (with and without feed params) and fetchSearchResults carry nsfw=1. When setItem throws, setNsfwFilter(false) still makes the next URL carry nsfw=1. c2 seam: a bundled DOM test like `tests/active/test_frontend_video_page.py` and `tests/active/test_frontend_profile.py`, with a stub fetch. The test is parametrized over the keyless, key-holding and issued-key profile states. It asserts that the checkbox is present and checked by default, and that changing it produces a feed request with the new nsfw value. The stub holds the first load's response and releases it after the toggle's response, and the test asserts that the rendered feed is the toggle's page.

**Intent.** The visitor's NSFW choice is held in the browser by data/feed-params.ts and decides whether the video-list requests in data/videos.ts and data/search.ts ask for NSFW rows. The home Profile modal in pages/videos/index.ts changes that choice and reloads the feed.

- C1 - buildSimilarUrl and fetchSearchResults add nsfw=1 only when the stored NSFW setting reads off.
- C2 - Changing the Profile-modal checkbox, in any of the three profile states, leaves the home feed showing the page fetched under the new setting.

**Outcome.** ### client/frontend/src/data/feed-params.ts
- Module docstring now also names the NSFW setting every video list sends.
- New key `NSFW_FILTER_KEY = "nsfwFilter:v1"`, stored apart from `feedParams:v1`, plus a module-level `nsfwFilterInMemory: boolean | null`.
- `readNsfwFilter()`: the in-memory choice if one was set this page; otherwise `true` unless storage holds exactly `"off"`. A missing, corrupt or unreadable value (getItem throws) reads as on.
- `setNsfwFilter(on)`: sets the in-memory value, then tries to store `"on"`/`"off"`, ignoring a storage failure the same way `persistFeedParams` does. So the choice still holds on the current page when setItem throws.
- `nsfwQuery()`: returns `[["nsfw", "1"]]` when the filter is off, `[]` otherwise.

### client/frontend/src/data/videos.ts
- Imports `nsfwQuery`. `buildSimilarUrl` adds its entries after the `feedParams` block and outside it, so the `?id=` up-next feed and the video page's up-next feed (both called without feed params) carry `nsfw=1` too. The value is read each time a URL is built, never captured at page load.

### client/frontend/src/data/search.ts
- Imports `nsfwQuery` and adds its entries after the `sort` line, before the keyed/keyless branch. Both branches send the flag, and the keyless cache key `search:${url}` keeps filtered and unfiltered results apart.
- The module comment now lists five gateway-allowed parameters (`q`, `page`, `limit`, `sort`, `nsfw`) and says `nsfw=1` goes only when the filter is off.

### client/frontend/src/pages/videos/index.ts
- Imports `readNsfwFilter` and `setNsfwFilter`.
- New helper `nsfwToggle()`, next to `profileActions`. It builds a `label.profile-nsfw` holding a checkbox, checked unless the filter is off, and the text " Hide NSFW videos". Its `change` handler calls `setNsfwFilter(input.checked)` then `loadVideos()`.
- `renderProfileSection` adds `nsfwToggle()` just before `status` in all three branches: issued-key, key-holding and keyless.
- Stale-load guard in `loadVideos`: the pager is created and assigned (`const current = …; pager = current;`) before the `try`. After `await current.next()`, and first thing in the `catch`, it returns if `current !== pager`. A newer load (an NSFW toggle or a likes reset) therefore wins over an older request that resolves later.

### client/frontend/src/videos.css
- One rule after `.profile-actions`: `.profile-nsfw { display: flex; align-items: center; gap: 0.5rem; margin: 0.75rem 0; }`.

**Beyond the files named.** client/frontend/src/videos.css - the phase lists `client/frontend/src/pages/videos/videos.css`, but that file doesn't exist. The home page imports `../../videos.css`, which is `client/frontend/src/videos.css`, so the plan's one `.profile-nsfw` rule went there.


