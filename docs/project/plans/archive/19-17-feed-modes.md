# 17-feed-modes

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-17-feed-modes.record.md`._

## Requirements

### Purpose

Let a visitor switch the home feed between five named modes (recommendations, hot, recent, random, popular), so they can browse by freshness or engagement instead of only through the recommendation mix or a random draw. The mode is the first parameter of the single feed-parameter mechanism that the feed parameter panel (`docs/project/plans/archive/04-feed-parameter-panel.md`: language, saved channels) will later extend. This build must not create a second mechanism.

### What was asked

Issue `docs/project/issues/17-feed-modes.md` (roadmap F3-M3), building on the delivered issue 16 (similarity-weighted popular draw). It asks for a home-page mode switcher, a `mode` API parameter accepted by the gateway, and definitions for hot, recent, popular and random.

### Tree facts this build rests on

- `engine/server/data/popularity.py` `compute_popularity` stores `videos.popularity = (views + like_weight * likes) / (1 + age_days / 30)`, which is an age-decayed likes/views score. It is indexed as `idx_videos_popularity` (created in `engine/server/db/jobs/sync-whitelist.py` and `recompute-popularity.py`).
- `fetch_popular_videos` in `engine/server/data/random_videos.py` orders by `popularity + MIN(interaction signal_score, POPULAR_SIGNAL_CAP)`, then `likes + interaction likes_count`, then `views`, `published_at`, `video_id`. `fetch_recent_videos` in the same file orders by `published_at DESC, video_id DESC`. `idx_videos_published` exists.
- `client/backend/server.py` `PROXY_ALLOWED_QUERY_PARAMS` already lists `mode` for `/recommendations` and `/videos/similar`, and `PROXY_ALLOWED_BODY_KEYS` lists `mode` in the body. The Engine (`engine/server/api/handlers/similar.py` `_handle_similar`) currently ignores any client-sent `mode`. It derives its own internal `mode` (`"home"` when there is no seed video, `"upnext"` when there is one), which selects the scoring profile and is echoed in the response's `seed` payload.
- Random currently travels as the query parameter `random=1` and is served by `_handle_random`.
- The home page (`client/frontend/src/pages/videos/index.ts`) has two buttons, `#show-recommendations` and `#show-random`, in `client/frontend/index.html` and `client/frontend/videos.html`. It reads its own URL `?mode=random` through `resolveFeedMode`/`setFeedMode` and pages through `createFeedPager` in `client/frontend/src/data/videos.ts`, which sends the already-shown `(id, host)` pairs as `exclude`.

### Modes and their definitions

Every mode applies to the home feed only, meaning a request with no seed video.

- **recommendations**: the current home feed, unchanged. This is the default.
- **hot**: global order by the existing age-decayed score, which is today's `fetch_popular_videos` order: `popularity + MIN(signal_score, POPULAR_SIGNAL_CAP)` descending, with its existing tie-breaks. No new formula is introduced.
- **popular**: global all-time order by likes, where likes means crawled `likes` plus the interaction-signal `likes_count` (the same sum the rows already report). Ties break on `views` descending, then a stable key. No age decay.
- **recent**: global order newest-first by `published_at`. Rows with `published_at` NULL, or later than the current time, are left out. There is no time window.
- **random**: today's random feed, unchanged in behaviour.

Hot, popular and recent give the same order to every visitor. Likes do not re-rank or tilt them; likes shape only recommendations. The recommendation mix's internal `popular` and `fresh` layers keep their current names, orders and behaviour.

### Filtering and paging that apply to every mode

- Every per-visitor and operator filter that applies to today's `/recommendations` feed still applies in every mode: channel/account blocks, disliked videos, operator serving moderation (`apply_serving_moderation_filters`), and the video error threshold.
- Hot, popular and recent honour the request's `exclude` list. Page N+1 therefore returns the next rows of the order and never repeats rows already shown. When the order is exhausted the feed ends: the pager's existing "a batch with no new rows ends the feed" rule applies.
- Random keeps its current paging behaviour.
- The existing page-size limits, including the doubled limit that lets the Client refill a page after removing blocked rows, apply unchanged.

### API

- The feed mode is the query parameter `mode` on `POST /recommendations` (and the same route via GET, if supported today). Its values are exactly `recommendations`, `hot`, `recent`, `random` and `popular`.
- The Engine validates `mode`. An unknown value returns HTTP 400 with an error naming the allowed values. A missing or empty `mode` means `recommendations`.
- `random=1` (any value other than `0`) remains an accepted alias for `mode=random`, so existing callers keep working.
- The gateway allowlist in `client/backend/server.py` already contains `mode` for `/recommendations`. It must keep it, and a test must show the gateway forwards it. No new allowlist entry is added.
- The client feed mode is separate from the Engine's internal `home`/`upnext` profile selection. It must not drive, rename or overwrite that selection, and the response's existing `seed.mode` value keeps its current meaning. If the response reports the feed mode, it does so under a distinct key.
- Requests carrying a seed video (`id`/`host`, the video page and up-next) ignore `mode`, and their behaviour is unchanged.

### UI

- The home page shows a five-option mode switcher (Recommendations, Hot, Recent, Random, Popular) in place of the current Recommendations/Random button pair, with the active mode visibly marked and exposed to assistive technology (e.g. `aria-pressed`).
- The mode in effect on load comes from the page URL `?mode=` first. Failing that, it comes from the last choice stored in `localStorage` under a versioned key (following the `localLikes:v1` naming convention). Failing that, it is `recommendations`. An invalid stored or URL value falls back to `recommendations`.
- Choosing a mode writes it to both the URL and `localStorage` and reloads the feed from the first page. The existing `?mode=random` links keep working.
- One client module owns the feed parameters: reading them from URL and storage, persisting them, and turning them into the Engine request. The panel's language and saved-channel parameters will be added to this module later. The page code does not build feed query parameters itself.

### Out of scope

- A new hot or popularity formula, a configurable time window for recent, or any change to how `videos.popularity` is computed.
- Personalising or likes-weighting hot, recent or popular.
- The feed parameter panel's language filter, saved channels and panel UI.
- Feed modes on the video page or up-next.
- Server-side persistence of the chosen mode.

### Acceptance criteria

1. With no `mode` (or `mode=recommendations`), the home feed response is identical in behaviour to today's.
2. `mode=hot` returns rows in descending `popularity + capped signal` order, `mode=popular` in descending all-time likes then views, and `mode=recent` in descending `published_at`, with no NULL or future-dated rows. Each is the same for two visitors with different likes.
3. `mode=random` and `random=1` both return the random feed.
4. An unknown `mode` returns 400 from the Engine, and the gateway passes the 400 through.
5. In hot, popular and recent, a second request carrying the first page's rows as `exclude` returns the following rows of the same order with no overlap.
6. Blocked channels/accounts and disliked videos never appear in any mode, and moderated or over-threshold videos never appear.
7. A request with a seed video behaves as today regardless of `mode`.
8. On the home page the switcher shows five options with the active one marked. Choosing one updates the URL and reloads the feed in that mode. A bare visit to `/` after choosing a mode restores it from `localStorage`. `?mode=` in the URL overrides the stored choice.
9. The gateway accepts `mode` on `/recommendations` and still rejects unlisted parameters.

### Test trees for this build

- Active tests: `tests/active`
- Working tests: `tests/tmp`
- Plans: `docs/project/plans`
- To delete: `delete_me`
- Archive: `tests/archive`
- Project dir: `/home/enduser/code/PeerTube-browser`
- Validation record: `tests/last_test_validation.json`
- Test output: `tests/last_test_output.txt`

### Baseline suite state

The pre-build suite exited 0 (baseline variant: false). The selective run executed 1 of 28 test groups (`test_search_fusion.py`, 10 passed).

## High-level plan

### Approach

The Engine owns the mode, the gateway forwards it unchanged, and one new client module owns the feed parameters. No new route, allowlist entry or formula is added.

**Engine: parsing and dispatch (`engine/server/api/handlers/similar.py`).** `_handle_similar` reads the query parameter `mode` next to `random`. A request counts as seeded exactly as it does today: it carries `vector`, `id`/`video_id` or `uuid`, the same condition that gates `resolve_seed`. A seeded request ignores `mode` completely, invalid values included, so the video page and up-next are untouched (criterion 7). An unseeded request trims `mode` and maps missing or empty to `recommendations`. A value outside the five-value set (a module-level constant tuple) returns 400 with `{"error": "Unknown mode", "allowed": [...]}` (criterion 4). The random branch then runs when `random` is set to anything other than `0` (existing behaviour, kept first) or when `mode=random`. Both go to the unchanged `_handle_random` (criterion 3). `mode=recommendations` takes today's path, so `_handle_home` and its response are byte-for-byte the same (criterion 1). `hot`, `popular` and `recent` go to a new `_handle_ordered_feed`. The local variable that holds `"home"`/`"upnext"` keeps its name and its job. The feed mode goes into a separately named variable (`feed_mode`) and never touches `seed.mode`. The feed mode is not reported in the response: the requirements allow leaving it out, and nothing reads it yet. Only the query parameter is read. The body `mode` key stays allowlisted and is still only logged, as it is today.

**Engine: the three orders (`engine/server/data/random_videos.py`).** A new function `fetch_ordered_page(conn, order, limit, offset, error_threshold)` selects the same row shape as `fetch_random_rows`, where `likes` is reported as crawled likes plus `interaction_signals.likes_count`. It then applies one of three ORDER BY clauses kept as module constants:
- **hot**: the exact ORDER BY of `fetch_popular_videos`. That clause is lifted into a shared constant which `fetch_popular_videos` also uses, so the mix's `popular` layer and the hot feed have the same order by construction, with no second copy that could drift.
- **popular**: `(v.likes + COALESCE(sig.likes_count, 0)) DESC, v.views DESC, v.video_id DESC, v.instance_domain DESC`, with no age term.
- **recent**: `v.published_at DESC, v.video_id DESC`, with an added `v.published_at IS NOT NULL AND v.published_at <= ?` bound to the current epoch-ms (`published_at` is epoch ms, as `compute_popularity` reads it).

The error-threshold clause is the same one the other fetchers use. `fetch_recent_videos` and `fetch_popular_videos` otherwise keep their behaviour, so the mix's `fresh` and `popular` layers do not change. None of the orders reads the request's likes, so every visitor gets the same order (criterion 2).

**Engine: paging and filters.** `_handle_ordered_feed` walks the order in chunks with `LIMIT/OFFSET`. From each chunk it drops rows whose `like_key` is in `fetch_request_excluded_keys()` and rows that `apply_serving_moderation_filters` removes. It stops once `limit` rows survive or a chunk comes back short (order exhausted). It responds through `_respond_rows`, whose second moderation pass is a harmless no-op. The same `seed_payload` shape as random is used, without a `mode` key. `limit` has already been capped at twice `default_limit` in `_handle_similar`, so the gateway's over-fetch works as it does today. The result: page N+1 continues the order past what was shown (criterion 5), and moderated or over-threshold rows never appear (criterion 6).

**Gateway (`client/backend/server.py`).** No code change is needed. `mode` is already in `PROXY_ALLOWED_QUERY_PARAMS` for `/recommendations`. Per-visitor channel/account blocks and disliked videos are already stripped for every `FEED_ROUTES` response in `_filter_payload`, whatever the mode, after the doubled-limit over-fetch. Engine 4xx bodies are already passed through by the `HTTPError` branch of `_proxy_engine_request`. Tests pin all three: forwarding of `mode`, pass-through of the 400, and rejection of an unlisted parameter (criteria 4, 6, 9).

**Client feed-parameter module (new `client/frontend/src/data/feed-params.ts`).** This is the single mechanism the panel will extend. It exports:
- the mode list and type;
- `resolveFeedParams(searchParams)`: URL `?mode=` first, then `localStorage` key `feedParams:v1`, then `recommendations`, with any invalid value mapped to `recommendations`;
- `persistFeedParams(params)`: writes storage, and ignores storage failures the way `cache.ts` does;
- `feedParamsToQuery(params)`: the Engine query entries, `mode=<value>`, with random sent as `mode=random`.

Storage holds a small JSON object rather than a bare string, so language and saved channels can be added later without changing the key. `buildSimilarUrl` in `data/videos.ts` takes an optional feed-params argument and appends whatever `feedParamsToQuery` returns. The page never names `mode` or `random` itself.

**Home page.** In both `client/frontend/index.html` and `client/frontend/videos.html`, the two buttons become one group of five `ghost-button`s carrying `data-feed-mode`, in the order Recommendations, Hot, Recent, Random, Popular. `index.ts` replaces `resolveFeedMode`/`setFeedMode` with the module. On load it resolves the params, marks the active button with `aria-pressed="true"` plus an active class, and builds the request through the module. A click persists to storage, writes `?mode=<value>` to the URL (always explicit, `recommendations` included), drops `id`/`uuid` as today, and navigates. The page reloads, so the feed starts again from page one. Old `?mode=random` links still resolve to random (criterion 8). `state.mode` gains an ordered case so `pickSample` does not shuffle hot, recent or popular (it shuffles today for random). A `?id=` seeded home view ignores the mode, as the Engine does.

### Alternatives considered

- **Separate endpoints (`/feed/hot` and so on)**, which the issue offered. Rejected: each would need new gateway allowlist entries and would be a second mechanism next to `/recommendations`, which the requirements forbid.
- **Filtering exclusions in SQL** (`NOT IN json_each(?)`) instead of the OFFSET walk. Rejected for now: moderation (denylist hosts, blocked channels) is Python-side in any case, so a Python loop is needed anyway. Doing exclusion there too keeps a single filtering path.
- **Keyset cursor or raised exclude caps** to page beyond ~500 rows. The operator chose to accept the ceiling (see Limitations).
- **Reusing `fetch_popular_videos`/`fetch_recent_videos` directly.** Rejected: neither takes an offset, `fetch_popular_videos` reports un-summed likes, and adding the NULL/future filter to `fetch_recent_videos` would change the mix's `fresh` layer.
- **Reporting the feed mode in the response** under a distinct key. Deferred: allowed, but nothing uses it yet.
- **In-place feed reload via `history.pushState`.** Rejected: today's reload by navigation already restarts the pager cleanly and avoids resetting page state by hand.

### Risks and gotchas

- The hot and popular ORDER BY clauses are computed expressions over a join with `interaction_signals`, so they cannot use `idx_videos_popularity`. Every page is a full sort, and the OFFSET grows (up to ~550) as paging goes on. The `popular` layer already pays this cost per request today. If it proves too slow, the upgrade is a precomputed sort column.
- The orders shift between pages when signals arrive or `recompute-popularity` runs. The exclude list plus the pager's dedupe prevent visible repeats, but a row that moves across the page boundary can be skipped. `recent` is stable because `published_at` does not change.
- An unknown `mode` on a seeded request is ignored rather than rejected. This is intentional, to satisfy "seeded requests ignore mode".
- If a visitor's blocks fill a whole doubled page, the gateway returns zero rows and the pager ends the feed early. Recommendations already behave this way.
- The body `mode` key and the query `mode` could disagree. Only the query is read, and this is documented in the Engine README.

### Limitations and tradeoffs asked of the operator

- **~500-row ceiling (accepted by the operator):** hot, popular and recent page only until about 500 rows have been shown. The exclude list is capped at 500 in three places: the client pager's `shown.slice(-500)`, the gateway's `MAX_FEED_EXCLUDE` and the Engine's `DEFAULT_CLIENT_EXCLUDE_MAX`. Once the earliest rows fall off it, the Engine returns them again, the pager sees no new row and ends the feed. The upgrade path is a cursor parameter added through the same feed-params module when the panel lands.
- The feed mode is not echoed in the response.
- Choosing a mode reloads the whole page rather than only the feed.

### Tests

- **Engine**, against a small SQLite fixture: the three orders; NULL and future rows left out of recent; the same order with different likes; the exclude continuation with no overlap; moderation and threshold filtering; the 400 naming the allowed values; `random=1` equal to `mode=random`; unchanged `seed.mode` and seeded behaviour.
- **Gateway:** `mode` forwarded, a 400 passed through, an unlisted parameter rejected, blocks and dislikes stripped in the hot feed.
- **Client module:** the URL, then storage, then default precedence, and invalid values falling back to `recommendations`.

## Impacts

<impacts>
<impact path="engine/server/api/handlers/similar.py" element="_handle_similar() (lines 939-1058): mode parsing, validation, dispatch">
**What changes.**
- Read `mode` next to `random_param` (line 955) with `params.get("mode", [None])[0]`. `parse_qs` drops blank values by default, so `mode=` already arrives as missing.
- The seeded test must be exactly the condition at line 996, `vector_param or id_param or uuid_param`. It has to be computed before the random branch at line 982, because validation comes before dispatch.
- For an unseeded request: strip; empty or missing becomes `recommendations`; anything outside the new module tuple gets `respond_json(self, 400, {"error": "Unknown mode", "allowed": [...]})`.
- Line 982 becomes `(random_param and random_param != "0") or feed_mode == "random"`.
- `hot`/`popular`/`recent` branch to `_handle_ordered_feed` before the `resolve_seed` block (985-998), so no seed lookup runs for them.
- Line 1006 (`mode = "home" if seed is None else "upnext"`) keeps its name and its job. The new variable is `feed_mode`.

**Order of operations to keep.**
- The debug 403 (961-964) runs before the `try` and stays first.
- The child-process stubs in `tests/active/test_similar.py` build `SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=...)` (lines 402 and 514), stub only `_handle_random` (417, 527), and call `_handle_similar` with `{"random": ["1"]}` or `{"debug": ["1"], ...}` (440-443, 535). Mode parsing must touch no other `self.server` attribute on those paths, or they raise AttributeError.
- Send the 400 inside the `try` (or before it). The `finally: clear_request_context()` (1057-1058) runs either way.
- Behaviour change on an existing input: unseeded `random=1&mode=bogus` now gets 400 where it used to get random. No caller in the tree sends that. The frontend sends `random=1` with no `mode` (`pages/videos/index.ts:219`), and `test_similar.py:137,157` send bare `random=1`.
- A seeded request with `random=1` still takes the random branch first, as today.

**Also affected.**
- POST `/videos/similar` runs through the same function (`SIMILAR_POST_ROUTES`, line 99), so an unseeded POST `/videos/similar?mode=hot` also serves the hot feed.
- `GET /videos/{id}/similar` (line 520-521) always sets `id`, so it is always seeded and ignores `mode`.
- The Engine has no GET `/recommendations` route (`_dispatch_get` 455-524). A gateway GET `/recommendations` gets a 404 from the Engine whatever the mode.
- The start log line (971-978) has no mode. Appending one is safe, because `_FAILING_SIMILAR_CHILD` matches only the `] start limit=20` prefix.

**What depends on it.**
- Every feed request: home, random, up-next, vector.
- These `config.json` groups map this file and are reselected: test_similar, test_server, test_video, test_dislike_profile, test_frontend_upnext_pager.

**Regression risk: medium.**
- Criterion 1 needs no-mode and `mode=recommendations` to stay identical to today. `seed.mode == "home"` with no `random` is pinned at test_similar.py:181, :844, :870 and test_server.py:170.
- Criterion 7 needs seeded requests to skip validation entirely.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="new SimilarHandler._handle_ordered_feed() (sibling of _handle_random, lines 709-724)">
**What changes.** A new method. It walks `fetch_ordered_page` in LIMIT/OFFSET chunks, drops rows whose `like_key(row)` is in `fetch_request_excluded_keys()`, runs the rest through `apply_serving_moderation_filters(self.server, rows, request_id=request_id)`, and stops at `limit` survivors or on a short chunk. It answers through `_respond_rows` (675-707).

**Pitfalls checked in the tree.**
- **Lock re-entry deadlock.** `self.server.db_lock` is a plain `threading.Lock()` (api/server.py:268), and `apply_serving_moderation_filters` takes `server.db_lock` itself (serving_moderation.py:27). Each `fetch_ordered_page` call must run inside `with self.server.db_lock:` and the moderation call outside it, as `_fetch_random_rows` (668-673) does. Nesting the two hangs the thread and every later DB reader.
- **Seed payload.** Random's payload is `{"random": True}` (line 723), and tests read `seed.random` to spot the random fallback (test_similar.py:181). An ordered feed must not reuse it. Use `{}` or another payload with no `random` or `mode` key.
- **Dedupe inside the walk (step-4 finding).** Each chunk is a separate query. A signal ingest or a `recompute-popularity` run between two chunks can move a row across a chunk boundary within one request. The walk therefore needs a local seen-set of `like_key`, or the page can carry a duplicate. The pager would then drop it client-side and the page comes back short.
- **Statement deadline.** The budget is 5 s per request (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`, server_config.py:457), applied in `do_POST` (377-385) and covering every chunk. `_handle_similar`'s `except Exception` (1054) catches `sqlite3.OperationalError: interrupted` first, so a slow deep page answers 500 `Recommendations request failed`, not the 503 from `_respond_interrupted`. The gateway's `HTTPError` branch passes that 500 through without retrying.
- **Chunk size and termination.** An exclude of up to 500 plus moderated rows can push OFFSET past about 550. Chunks must be at least `limit` rows, and the loop needs an iteration or row bound so a heavily moderated dataset cannot spin until the deadline.
- **Double moderation.** `_respond_rows` moderates again (684). The result is the same, but it costs a second lock acquisition and a second query per page.
- **Projection.** `stable_video_rows` keeps only `STABLE_VIDEO_FIELDS` (110-130, plus `views`/`likes`/`dislikes` because `INCLUDE_DYNAMIC_STATS = True`, server_config.py:430). `popularity` and any sort key are not returned, which matches random.

**What depends on it.** Only the new dispatch branch. It needs `fetch_ordered_page` added to the import at line 38. `like_key` (45), `apply_serving_moderation_filters` (40) and `now_ms` (42) are already imported.

**Regression risk: medium-high.** The code is new. The deadlock, the random mislabel and the in-walk duplicates would each ship silently unless a test drives a real Engine through this path.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="new module constant: allowed feed modes tuple (near SIMILAR_POST_ROUTES, line 99)">
**What changes.** A tuple `("recommendations", "hot", "recent", "random", "popular")`. Its order is the order of the 400's `allowed` list.

**What depends on it.**
- The 400 body and the Engine tests.
- The client keeps its own list in `feed-params.ts`, and only tests tie the two together.
- The archived panel plan (`docs/project/plans/archive/04-feed-parameter-panel.md:28,51`) foresees a saved-channels feed mode. Adding it later means editing both lists, plus a Client-side input the Engine never sees (saved channels live in `localStorage`, line 26 of that plan).

**Risk: low.**
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_similar_request() body `mode` logging (lines 636-644) and exclude parsing (628-635, 654)">
**What changes.** Nothing. The body `mode` is still only logged. Excludes are set only for POST (654), are capped at `DEFAULT_CLIENT_EXCLUDE_MAX` with a 400 (629-635), and `_parse_excluded_keys` (173-189) builds `video_id::instance_domain` keys, matching `like_key` (`recommendations/keys.py:8-16`).

**Risk: none.** Listed so the next step can confirm it is untouched. The query/body mismatch belongs in the Engine README.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_popular_videos() (lines 198-306): ORDER BY lifted into a shared module constant">
**What changes.** The subquery ORDER BY (249-254) becomes a module constant that is interpolated back in. It carries a `?` for `POPULAR_SIGNAL_CAP`, so the params stay `[error_threshold?, POPULAR_SIGNAL_CAP, limit, limit]` exactly as today (203, 206).

**Step-4 findings.**
- **Not a total order.** The clause ends on `v.video_id DESC` without `v.instance_domain`, while the PK is `(video_id, instance_domain)`. The hot feed's separate OFFSET chunks can therefore break exact ties differently between queries and skip or repeat a row. Appending `v.instance_domain DESC` to the shared constant fixes it. For the mix's popular layer, that only reorders exact ties. It is a deviation from "exact ORDER BY of fetch_popular_videos" and needs the operator's nod.
- **No outer ORDER BY.** The outer query (241-265) has no ORDER BY, so the sequence the function returns is join order. "Same order by construction" holds for the subquery ranking and membership, not for the returned list, and a test comparing hot with this function must compare sets or re-sort.
- **Different membership.** The subquery ranks all `videos` and only then joins `video_embeddings`, whereas the hot feed ranks over the embedded set. Among embedded rows the relative order is the same.

**What depends on it.**
- The mix's popular layer: `builder.py` → `candidates/popular_videos.py`, wired at api/server.py:100 and 399.
- `tests/active/test_random_videos.py` 130-167, including the cap test at 147-167 on both threshold branches.
- `tests/active/test_video.py:219`, which builds deps from `server.fetch_popular_videos`.
- `test_popular_videos.py:40` stubs it, so it is unaffected.

**Regression risk: medium.** A misplaced `?` or a params reorder binds the threshold or the limit into the cap's slot and changes the home mix for every visitor. The cap test guards exactly this, and its group maps this file.
</impact>
<impact path="engine/server/data/random_videos.py" element="new fetch_ordered_page(conn, order, limit, offset, error_threshold) and the three ORDER BY constants">
**What changes.** A new function. It reuses `fetch_random_rows`' SELECT (26-63): the `video_embeddings` JOIN `videos`, LEFT JOIN `interaction_signals`, LEFT JOIN `channels`, with `likes` reported as `(v.likes + COALESCE(sig.likes_count, 0))` (line 48). It then applies one ORDER BY constant and `LIMIT ? OFFSET ?`.

**Details checked in the tree.**
- **WHERE composition.** `error_clause` begins with `WHERE` (22, 115, 205). Recent's `v.published_at IS NOT NULL AND v.published_at <= ?` must be combined with it by `AND`, not concatenated.
- **Params order.** Placeholder order is: threshold (if any), now_ms (recent only), cap (hot only, inside ORDER BY), limit, offset.
- **Recent bound.** `published_at` is epoch ms. Bind `data.time.now_ms()`.
- **Tie order.** Recent as written in the plan (`published_at DESC, video_id DESC`) is not total over the PK either. Append `v.instance_domain DESC` (step-4 finding, needs the operator's nod). Popular already ends on `instance_domain`.
- **Row shape.** Needs `video_id`, `instance_domain`, `channel_id` and `account_url` for `like_key`, moderation (`_row_host`/`_row_channel_id`, moderation.py:444-462) and the gateway block filter. The row-to-dict block would be the fourth copy in this file (72-103, 162-193, 271-304).
- **Cost.** Hot and popular are computed sorts over a LEFT JOIN, so `idx_videos_popularity` is unusable. Recent can use `idx_videos_published`.

**What depends on it.** `_handle_ordered_feed` and the new tests.

**Risk: low for existing code, medium for the new behaviour** (params order, WHERE composition, non-total ties).
</impact>
<impact path="engine/server/data/random_videos.py" element="popular order key: uncapped `v.likes + sig.likes_count` as the primary sort">
**What changes.** The popular mode ranks first by a term that `POPULAR_SIGNAL_CAP` (line 12) does not bound. Today that term is only a tiebreaker (line 251).

**What depends on it.** `docs/project/roadmap.md:33` already lists bounding this term as an open item.

**Risk: medium (abuse).** Minted profiles can each add one like per video. The build does not change ingest, but the operator should know this term now ranks a feed every visitor sees. Record it in the roadmap.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_recent_videos() (108-195), fetch_random_rows() (15-105), fetch_random_rows_from_cache() (309-327): unchanged">
**What changes.** Nothing. The mix's `fresh` layer keeps its order and gets no NULL/future filter.

**What depends on it.** The fresh layer (api/server.py:99 and 398), the random feed and `_fetch_random_rows` (similar.py:661-673).

**Risk: none if left alone.** Listed so the next step can verify they are untouched.
</impact>
<impact path="engine/server/api/request_context.py" element="fetch_request_excluded_keys() (line 30)">
**What changes.** Nothing. It gains a reader in `_handle_ordered_feed`. Excludes exist only for POST. GET has none, which is fine because the ordered feeds reach the Engine only by POST.

**Risk: low.**
</impact>
<impact path="engine/server/data/serving_moderation.py" element="apply_serving_moderation_filters() (lines 14-48)">
**What changes.** Nothing. It is called once per chunk from `_handle_ordered_feed`. It takes `server.db_lock` itself (27), so the caller must not hold that lock. When filtering is on, it logs a moderation line per call (40-46), so a long walk can add several log lines per request.

**Risk: see the `_handle_ordered_feed` entry.**
</impact>
<impact path="engine/server/api/server.py" element="imports from data.random_videos (lines 96-100), RecommendationBuilderDeps wiring (398-399), db_lock (268)">
**What changes.** Nothing, provided the handler imports `fetch_ordered_page` directly. Editing this file would reselect the test_server_config, test_internal_events and test_random_cache groups.

**Risk: low.**
</impact>
<impact path="engine/server/api/server_config.py" element="DEFAULT_CLIENT_EXCLUDE_MAX = 500 (441), DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0 (457), BATCH_SIZE (313), INCLUDE_DYNAMIC_STATS (430)">
**What changes.** Nothing, unless a chunk-size or walk-bound constant is placed here. These constants set the ~500-row ceiling and the 5 s budget. Editing the file reselects five groups: test_dislike_profile, test_similar, test_server, test_server_config, test_internal_events.

**Risk: low.**
</impact>
<impact path="client/backend/server.py" element="PROXY_ALLOWED_QUERY_PARAMS (88-90), PROXY_ALLOWED_BODY_KEYS (106-108), GET/POST proxy sanitising (421-440, 475-491), MAX_FEED_EXCLUDE (59), FEED_ROUTES (71), FEED_PAGE_SIZE/FEED_OVERFETCH_FACTOR (69-70), _proxy_engine_request HTTPError branch (653-699), timeouts (77-82)">
**What changes.** No code. Each claim in the plan holds in the tree:
- `mode` is allowlisted on both feed routes.
- An unlisted key gets 400 `Unknown query parameter` (481-483), and a repeated key gets 400 (486-488).
- Blank values are dropped (489-491).
- A 4xx with a body is passed through verbatim (653-684).

**Worth knowing.**
- The gateway caps `limit` at 48 (457) and asks for 96 only when the profile has blocks or dislikes (471-472). `_filter_payload` then cuts to 48 (1109-1110). In an ordered feed, the surviving rows 49-96 are never shown and never enter `exclude`, so the Engine returns them at the head of the next page. That is the correct continuation.
- The proxy timeout is 10 s with one retry on transport errors only (77-82). The Engine's 5 s deadline hits first.

**Risk: none in code.**
</impact>
<impact path="client/backend/server.py" element="_profile_filter (442-473) and _filter_payload (1094-1120), together with the pager's exclude list: per-profile removals pile up in fixed orders">
**What changes.** Nothing in code. This is a behaviour the plan understates (step-4 finding).

**Mechanism.** Rows the gateway removes for a profile (blocked channels or accounts via `filter_blocked`, disliked videos via `filter_disliked`, line 1108) never reach the browser, so they never enter the pager's `exclude`. In a fixed order the Engine returns them at the head of every later page. Once more than 48 of them sit before the paging frontier, the 96-row over-fetch yields fewer than 48 rows per page. At 96 or more it yields zero, and the pager ends the feed.

**Contrast with today.** Dislikes persist in users.db, so a profile that disliked many popular videos can get a short hot or popular feed from the first pages. Recommendations and random draw differently each page and do not accumulate this way.

**Options (step-4 recommendations):**
- (a) Accept it and document it next to the 500-row limit.
- (b) Have the gateway add the profile's disliked keys to the forwarded `exclude`. They share the 500 budget, and blocks are not covered.
- (c) Solve it with the planned cursor parameter.

**Risk: medium (behavioural, keyed visitors).** Needs an operator decision. At minimum, correct the plan's risk line and the docs.
</impact>
<impact path="client/frontend/src/data/feed-params.ts" element="new module: mode list/type, resolveFeedParams, persistFeedParams, feedParamsToQuery">
**What changes.** A new file.
- Storage key `feedParams:v1`, holding a JSON object. It must not collide with `localLikes:v1` (local-likes.ts) or `profileKey:v1` (profile.ts).
- Read and write with try/catch the way `local-likes.ts:113,124,175` does (`window.localStorage`, failures ignored).
- A JSON value that is valid but not an object (`"hot"`, `null`, an array) or an unknown mode falls back to `recommendations`.
- Read lazily, not at import. `data/videos.ts` is bundled by the node runners. They define `localStorage` on both `globalThis` and `window` (test_frontend_blocks.py:26-28, test_frontend_upnext_pager.py:25-27, test_frontend_video_page_similars.py:32-36), so a lazy read works there. The earlier claim that some runners lack `window.localStorage` was wrong.

**What depends on it.** `data/videos.ts`, `pages/videos/index.ts`, and the future panel (archived plan 04, which adds language and saved channels, and a saved-channels mode, to this module).

**Risk: low.** Its test needs a new config.json group.
</impact>
<impact path="client/frontend/src/data/videos.ts" element="buildSimilarUrl() (98-107), fetchSimilarVideosPayload() (130-157), SimilarQuery/parseSimilarQuery (11-18, 77-86)">
**What changes.** `buildSimilarUrl` takes an optional feed-params argument and appends `feedParamsToQuery(...)`. Its only caller is `fetchSimilarVideosPayload` (131), which must gain an optional trailing parameter after `exclude` and pass it through.

**Interaction to decide.** `SimilarQuery.random` is still parsed from the page URL (83) and sent as `random=` (104), and `pages/videos/index.ts` spreads `similarQuery` into the request (216-225). So `?random=1&mode=hot` sends both, and the Engine's random branch wins. That is consistent with the Engine, but it is a second way to name random that the one-mechanism requirement may want removed from the home page.

**Error display.** A non-OK response surfaces the body's `error` (146-154), so an Engine 400 would show "Unknown mode" in the page. The module never sends an invalid mode, so only a stale bundle could trigger it.

**What depends on it.**
- `pages/video-page/index.ts:331`: seeded, no feed params, must stay unchanged.
- `pages/videos/index.ts:213-226`.
- Two-argument test callers: test_frontend_blocks.py:37, test_frontend_upnext_pager.py:36, test_frontend_video_page_similars.py.

**Risk: low-medium.** The signature must stay backward compatible. Three groups map this file and are reselected.
</impact>
<impact path="client/frontend/src/data/videos.ts" element="createFeedPager() (37-70), MAX_FEED_EXCLUDE (28)">
**What changes.** Nothing. `shown.slice(-500)` (51) sets the ceiling. "No new row ends the feed" (66) stops paging, both at that ceiling and when per-profile removals pile up (see the gateway entry).

**Risk: none (unchanged).** The behaviour belongs in the documentation.
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="resolveFeedMode()/setFeedMode() (917-938), feedMode (77), button lookups and listeners (55-56, 128-138)">
**What changes.**
- Remove `resolveFeedMode`/`setFeedMode`.
- Replace the two `getElementById` lookups with a `[data-feed-mode]` query and one listener.
- A click persists the params, sets `?mode=<value>` explicitly, and deletes `id`/`uuid`. It still leaves `host`, `limit`, `api` and `debug` in place, as today (929-937). Then it navigates.
- On load, mark the active button with `aria-pressed="true"` and an active class.

**Coupling.** `debugMode` mutates `params` (71-75) before `parseSimilarQuery`, so `resolveFeedParams(params)` should read the same object.

**What depends on it.** Only this page. No active test bundles it and no group maps it.

**Risk: medium.** It is untested. Old `?mode=random` links must still work.
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="fetchVideosPayload() (211-227)">
**What changes.** The `feedMode === "random"` branch that injects `random: "1"` (215-221) goes away. Unseeded requests pass the resolved params. The `useSimilar` branch (212-214) passes none, so `?id=` views ignore the mode.

**What depends on it.** `createFeedPager(fetchVideosPayload)` at lines 94 and 181.

**Risk: low-medium.** On the wire, random moves from `random=1` to `mode=random`.
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="state.mode type (88) and assignment (187), pickSample() (258-272), renderSummary() (277-295)">
**What changes.** The union gains an ordered case. Line 187 maps hot/recent/popular to it. `pickSample` must not shuffle it: anything not `similar` or `personalized` falls through to `shuffle` (269). `renderSummary`'s default branch is harmless. `loadMoreVideos` (232-253) appends unshuffled, so only the first page is at risk.

**Risk: medium.** The failure is silent and untested.
</impact>
<impact path="client/frontend/index.html" element="summary-actions (37-41) inside `<section class=\"summary\" hidden>` (32), reset-feed link (38)">
**What changes.**
- `#show-recommendations`/`#show-random` (39-40) become five `ghost-button`s with `data-feed-mode`, in the order Recommendations, Hot, Recent, Random, Popular.
- The section is visible only because `.summary { display: flex }` (videos.css:112) overrides the UA `[hidden]` rule. A global `[hidden]{display:none}` would hide the switcher.
- "Back to recommended" (`href="/"`, line 38) will land on the stored mode once one is persisted. Step 4 recommends `/?mode=recommendations`. The Home nav (24) stays `/`.

**Risk: low-medium.** No test covers this HTML.
</impact>
<impact path="client/frontend/videos.html" element="summary-actions (37-41), reset-feed link (38)">
**What changes.** The same edits as index.html. These are hand-kept duplicates loading the same script, and the video page links here as `/videos.html?id=…` (video-page/index.ts:106, 324). Those views are seeded and ignore the mode.

**Risk: low.** The two files can drift.
</impact>
<impact path="client/frontend/src/videos.css" element=".ghost-button (136-150); no active-state rule">
**What changes.** Add a scoped `.summary-actions .ghost-button[aria-pressed="true"]` (or `.active`) rule. Only `video.css:365` has `.ghost-button.active`, and that file is not loaded on the home page. The profile modal's Close button (index.html:54) is also a `.ghost-button`, so an unscoped rule would restyle it.

**Risk: low.**
</impact>
<impact path="client/frontend/src/types/videos.ts" element="SimilarSeed / VideosPayload.seed">
**What changes.** Nothing, as long as the ordered seed payload adds no key the page reads. `state.seed` is assigned (index.ts:188-190) but never read.

**Risk: none.**
</impact>
<impact path="client/frontend/dist/index.html" element="built artifacts: dist/index.html, dist/videos.html (47-48), dist/assets/index-*.js">
**What changes.** They stay stale until `npm run build`. They still carry the two buttons and the `random=1` bundle, and no test reads them.

**Risk: low-medium, operational.** The rebuild must be part of delivery.
</impact>
<impact path="tests/active/test_random_videos.py" element="_two_video_db harness (43-66) and three tests (114-167)">
**What changes.** Extend it, or add a sibling file, for the three orders:
- recent excludes NULL and future rows;
- the order is the same under different likes;
- the error threshold applies;
- ties are total.

The harness attaches whitelist.db and copies two videos. Proving an order needs three or more rows, plus NULL and future `published_at` rows. Compare hot with `fetch_popular_videos` as a set or re-sorted sequence, never as the returned sequence.

**Risk: low.** The cap test (147-167) guards the lifted constant.
</impact>
<impact path="tests/active/test_similar.py" element="engine-fixture tests (134-201), stub children (392-539)">
**What changes.** New cases:
- the 400 with `allowed`;
- `random=1` equals `mode=random` (`/recommendations?random=1` at 137 and 157 is the pattern);
- `mode=recommendations` equals no mode;
- seeded requests with `mode=hot` or `mode=bogus` are unchanged;
- exclude continuation with no overlap for hot, popular and recent;
- the seed payload of an ordered feed carries no `random`.

The stub children must keep passing.

**Risk: medium.** These are slow integration tests on the real dataset, and timing against the 5 s deadline shows up here.
</impact>
<impact path="tests/active/test_server.py" element="gateway tests (home assertion line 170, exclude tests 188-231, stubbed-Engine harness ~994-1128)">
**What changes.** New cases:
- `mode` forwarded unchanged;
- the Engine 400 passed through with its body;
- an unlisted parameter rejected;
- blocks and dislikes stripped on a keyed hot page, with over-fetch.

**Risk: low.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups">
**What changes.**
- Add a group mapping `client/frontend/src/data/feed-params.ts` (and `data/videos.ts`) to the new client-module test.
- Consider mapping `engine/server/data/random_videos.py` into the `test_similar.py` group (48-59), which does not include it today.
- If a page test is added, map `pages/videos/index.ts`, `index.html` and `videos.html`, which no group maps.

**Risk: low.** A test missing from the map is never selected.
</impact>
<impact path="tests/active/conftest.py" element="engine / dataset fixtures">
**What changes.** Nothing. The new tests reuse the fixtures.

**Risk: none.**
</impact>
</impacts>

## Documentation to update

- [x] `engine/server/README.md` - updated: Added a Notes bullet on the `mode` feed-mode parameter, and added the statement-deadline case to the 500 bullet.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md now covers the hot, popular and recent ordered feeds: their orders, how they page with `exclude`, the shared `POPULAR_ORDER_BY` and their empty `seed`.
- [x] `client/README.md` - updated: client/README.md now has a gateway bullet on feed modes, and the `exclude` bullet lists the ordered feeds too.
- [x] `client/frontend/README.md` - updated: `client/frontend/README.md` now covers the home feed's five modes, how the mode is chosen and remembered, `src/data/feed-params.ts`, when paging ends in the ordered feeds, and when `dist/` needs a rebuild.
- [x] `CONTEXT.md` - updated: I added **Feed mode**, **Hot** and **Popular** to the glossary in `CONTEXT.md`, and changed the Interaction signal entry so the capped ordering it describes names the Hot feed.
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: the signal-cap note now names the hot feed as well as the mix's popular layer and says the cap does not apply to the popular feed mode. The over-fetch applies in every feed mode, and a new subsection covers what the ordered feeds cost.
- [x] `README.md` - updated: `README.md` now has a short "Home feed modes" section listing the five modes, and the Hot / Popular / Random / Fresh item is gone from Future ideas.
- [x] `docs/project/roadmap.md` - updated: Roadmap: added a Delivered entry for F3-M3 issue 17, marked F3-M3 and F9-M2 as delivered, sharpened the uncapped-likes follow-up and added an ordered-feed cursor follow-up.
- [x] `docs/project/issues/17-feed-modes.md` - updated: Issue 17 closed as delivered: status set to `enhancement, complete`, a Delivered comment added, the panel-plan path fixed, and the file written to `docs/project/issues/archive/17-feed-modes.md`.
- [x] `docs/project/issues/plan.md` - updated: Marked Wave 3 lane 3b (issue 17, feed modes) as delivered in `plan.md` and replaced its file list with the files the build actually changed.
- [x] `docs/project/adr/0001-derived-interaction-event-ids.md` - out of scope: An ADR records a decision and is not rewritten to follow the build. Decision 4's capped "popular ordering" is kept unchanged as the hot order. The tension between its intent and the new uncapped popular feed is raised in adr_conflicts for the operator to decide, not edited here.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - out of scope: It diagrams the recommendation builder pipeline, ending in "batch + seed mode". That remains true for the recommendations mode, which is unchanged. The ordered feeds bypass the builder, and the diagram makes no claim about them.
- [x] `docs/project/security-audit/run-1/architecture.md` - out of scope: A point-in-time audit record. Its line 53 already lists `mode` among the frontend URL parameters, and that is still accurate: `mode` is now parsed through `parseFeedMode` against a fixed list.

## Implementation plan

# Draft: feed modes (issue 17)

## Decisions recorded before drafting

- **Tie-break (operator, answered in this step):** `v.instance_domain DESC` goes at the end of the shared hot/popular-layer ORDER BY constant, so `fetch_popular_videos` changes too, and at the end of the recent order. The mix's `popular` layer changes only in how it orders exact ties. With this, all three ordered feeds are total orders over the primary key `(video_id, instance_domain)`.
- **Per-profile pile-up:** option (a), accept and document. The settled documentation list already carries this (client/README, frontend README, OVERVIEW). The cursor parameter in the roadmap is the follow-up.
- **Legacy `?random=1` on the home page (my call, named):** the home page stops sending `random=` itself. `resolveFeedParams` maps a URL with no `mode` and `random` other than `0` to `mode=random`, so old `/?random=1` links keep working through the one mechanism. `parseSimilarQuery` still parses `random` for other callers, and `index.ts` sets `random: null` on unseeded requests.
- **The URL mode is not persisted on load (named):** only a click writes `localStorage`. A shared `?mode=hot` link therefore does not overwrite the visitor's stored choice. That is consistent with "the URL overrides storage" and "choosing a mode persists it".
- **An empty `?mode=` in the URL is treated as absent (named):** it falls through to storage. A non-empty invalid value maps to `recommendations`, as the requirements say.

## Module map

| File | Change |
|---|---|
| `engine/server/data/random_videos.py` | `POPULAR_ORDER_BY` constant (lifted and made total), `ORDERED_FEED_ORDER_BY` table, `fetch_ordered_page`, private `_ordered_row` |
| `engine/server/api/handlers/similar.py` | `FEED_MODES`, `ORDERED_FEED_MODES`, walk constants, `mode` parsing/validation/dispatch in `_handle_similar`, new `_handle_ordered_feed` |
| `client/frontend/src/data/feed-params.ts` | new: the single feed-parameter module |
| `client/frontend/src/data/videos.ts` | `buildSimilarUrl`/`fetchSimilarVideosPayload` take an optional trailing `FeedParams` |
| `client/frontend/src/pages/videos/index.ts` | switcher wiring via the module, `ordered` sample mode, remove `resolveFeedMode`/`setFeedMode` |
| `client/frontend/index.html`, `client/frontend/videos.html` | five-button group, reset link to `/?mode=recommendations` |
| `client/frontend/src/videos.css` | scoped pressed-state rule |
| `client/backend/server.py` | no change |
| tests + `.un/skills/devsecops/config.json` | see Tests |

## Engine: `engine/server/data/random_videos.py`

Constants, placed under `POPULAR_SIGNAL_CAP`:

```python
# The popular order: capped-signal popularity first. It ranks the mix's popular layer and the hot feed, and ends on the full key so paging never skips or repeats a tie.
POPULAR_ORDER_BY = """
            (v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC,
            (v.likes + COALESCE(sig.likes_count, 0)) DESC,
            v.views DESC,
            v.published_at DESC,
            v.video_id DESC,
            v.instance_domain DESC"""

# The global order of each ordered feed; only hot binds a parameter (POPULAR_SIGNAL_CAP).
ORDERED_FEED_ORDER_BY = {
    "hot": POPULAR_ORDER_BY,
    "popular": """
            (v.likes + COALESCE(sig.likes_count, 0)) DESC,
            v.views DESC,
            v.video_id DESC,
            v.instance_domain DESC""",
    "recent": """
            v.published_at DESC,
            v.video_id DESC,
            v.instance_domain DESC""",
}
```

`fetch_popular_videos`: lines 249-254 become `ORDER BY{POPULAR_ORDER_BY}` inside the existing f-string. Params stay `[POPULAR_SIGNAL_CAP, limit, limit]` / `[error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`. The `?` sits in the same position (after the WHERE and before the inner LIMIT), so binding order does not change. Nothing else in the function changes. `fetch_random_rows`, `fetch_recent_videos` and `fetch_random_rows_from_cache` are untouched.

New function (after `fetch_popular_videos`):

```python
def fetch_ordered_page(
    conn: sqlite3.Connection,
    order: str,
    limit: int,
    offset: int,
    error_threshold: int | None = None,
) -> list[dict[str, Any]]:
    """Return one page of a global feed order (hot, popular or recent), starting `offset` rows in."""
    order_by = ORDERED_FEED_ORDER_BY[order]
    conditions: list[str] = []
    params: list[Any] = []
    if error_threshold is not None and error_threshold > 0:
        conditions.append("(v.error_count IS NULL OR v.error_count < ?)")
        params.append(error_threshold)
    if order == "recent":
        conditions.append("v.published_at IS NOT NULL AND v.published_at <= ?")
        params.append(now_ms())
    if order == "hot":
        params.append(POPULAR_SIGNAL_CAP)
    params.extend([limit, offset])
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = conn.execute(
        f"""
        SELECT
          <exactly the column list of fetch_random_rows, lines 27-56>
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN interaction_signals sig
          ON sig.video_uuid = v.video_uuid AND sig.instance_domain = v.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        {where_clause}
        ORDER BY{order_by}
        LIMIT ? OFFSET ?
        """,
        params,
    )
    return [_ordered_row(row) for row in query]
```

- Import `from data.time import now_ms` (the module the handler already uses).
- `_ordered_row(row)` is a private helper returning the same dict keys as `fetch_random_rows` (lines 73-103). It is new code only: the three existing copies stay inline, so the existing functions are byte-for-byte unchanged apart from the lifted ORDER BY.
- `likes` is reported as the sum `(v.likes + COALESCE(sig.likes_count, 0))`, which is also the popular sort key.

**Invariants.**
- `order` must be a key of `ORDERED_FEED_ORDER_BY`, and a `KeyError` otherwise is a programming error. The handler validates first.
- Placeholder order is threshold, then now_ms (recent), then cap (hot, which sits in ORDER BY after WHERE), then limit, then offset. That matches the SQL text order.
- The WHERE clauses are joined with `AND`. The "WHERE"-prefixed `error_clause` string is not reused here.
- No input from the request other than `order`, `limit` and `offset` reaches the query, so the order is identical for every visitor (criterion 2).

## Engine: `engine/server/api/handlers/similar.py`

Import at line 38: `from data.random_videos import fetch_ordered_page, fetch_random_rows, fetch_random_rows_from_cache`.

Constants, next to `SIMILAR_POST_ROUTES`:

```python
# The home feed modes a client may ask for with ?mode=; the order is the order of the 400's "allowed" list.
FEED_MODES = ("recommendations", "hot", "recent", "random", "popular")
# The modes served by one global order, paged past the request's exclude list.
ORDERED_FEED_MODES = frozenset({"hot", "popular", "recent"})
# Extra rows per chunk of an ordered feed, so moderated rows seldom force a second query.
ORDERED_FEED_CHUNK_SLACK = 32
# An ordered feed stops after this many chunks, so a heavily moderated order cannot run to the statement deadline.
ORDERED_FEED_MAX_CHUNKS = 4
```

`_handle_similar` changes:
- After line 955: `mode_param = params.get("mode", [None])[0]`.
- Inside the `try`, before the random branch:

```python
            seeded = bool(vector_param or id_param or uuid_param)
            # The feed mode picks the home feed only; seeded requests ignore it, invalid values included.
            feed_mode = "recommendations" if seeded else (mode_param or "").strip() or "recommendations"
            if feed_mode not in FEED_MODES:
                respond_json(self, 400, {"error": "Unknown mode", "allowed": list(FEED_MODES)})
                return
            if (random_param and random_param != "0") or feed_mode == "random":
                self._handle_random(limit, include_debug, request_id, started_at)
                return
            if feed_mode in ORDERED_FEED_MODES:
                self._handle_ordered_feed(feed_mode, limit, include_debug, request_id, started_at)
                return
```

- The `resolve_seed(...) if (vector_param or id_param or uuid_param) else None` condition becomes `if seeded else None`. It is the same expression, now in a single place.
- `mode = "home" if seed is None else "upnext"` and everything below it are unchanged.
- The start log line is left as it is (no mode appended), which keeps the edit minimal.

Order of operations: the debug 403 still runs first, outside the `try`. The 400 is sent inside the `try`, so the `finally: clear_request_context()` runs. The new lines touch only `params` and locals, with no `self.server` attribute, so the `SimpleNamespace` stub children in `test_similar.py` (`{"random": ["1"]}`, `{"debug": ["1"], ...}`) reach `_handle_random` or the 403 exactly as before.

New method, after `_handle_random`:

```python
    def _handle_ordered_feed(
        self,
        order: str,
        limit: int,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
    ) -> None:
        """Handle the hot, popular and recent feeds: the next rows of one global order past the request's exclude list."""
        excluded = fetch_request_excluded_keys()
        # Shown rows sit at the head of the order, so one chunk this size usually fills the page.
        chunk_size = limit + len(excluded) + ORDERED_FEED_CHUNK_SLACK
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        offset = 0
        for _ in range(ORDERED_FEED_MAX_CHUNKS):
            with self.server.db_lock:
                chunk = fetch_ordered_page(
                    self.server.db,
                    order,
                    chunk_size,
                    offset,
                    error_threshold=self.server.video_error_threshold,
                )
            offset += chunk_size
            fresh = []
            for row in chunk:
                key = like_key(row)
                # A signal landing between two chunks can move a row across the boundary; keep its first place.
                if key in excluded or key in seen:
                    continue
                seen.add(key)
                fresh.append(row)
            # Moderation takes db_lock itself, so it runs outside the lock held above.
            kept, _ = apply_serving_moderation_filters(self.server, fresh, request_id=request_id)
            rows.extend(kept)
            if len(rows) >= limit or len(chunk) < chunk_size:
                break
        self._respond_rows(
            rows[:limit],
            include_debug,
            request_id,
            started_at,
            seed_payload={},
        )
```

**Invariants.**
- `db_lock` is never held across `apply_serving_moderation_filters`, so there is no re-entry deadlock.
- `seed_payload={}` carries no `random` key (so the response is never labelled as the random fallback) and no `mode` key (`seed.mode` keeps its meaning, and the feed mode is not echoed).
- The returned rows keep the order's sequence. Excluded rows are skipped, so page N+1 starts at the first row not yet shown (criterion 5).
- Over-threshold rows never enter a chunk. Moderated rows are removed per chunk, and `_respond_rows` moderates again (a harmless no-op), which satisfies criterion 6 on the Engine side.
- Bounds: at most `ORDERED_FEED_MAX_CHUNKS` queries per request. The first chunk covers the whole exclude list plus the page, so a normal page is one query. With `limit=96` and `exclude=500` the chunk is 628 rows and the worst case scans 2512.
- The walk stops early on a short chunk, which means the order is exhausted. It can also return fewer than `limit` rows when 4 chunks are mostly moderated, and the pager treats that as usual.
- A statement-deadline interrupt inside the walk surfaces as the handler's existing 500 (`except Exception`), as documented.

## Gateway: `client/backend/server.py`

No code change. `mode` is already in `PROXY_ALLOWED_QUERY_PARAMS` for `/recommendations`. Blank values are dropped, and unlisted or repeated keys get a 400. Engine 4xx bodies pass through in the `HTTPError` branch. `_filter_payload` strips blocks and dislikes for every `FEED_ROUTES` response after the doubled over-fetch. The tests pin all of this.

## Client: `client/frontend/src/data/feed-params.ts` (new)

```ts
/**
 * Module `client/frontend/src/data/feed-params.ts`: the home feed's parameters - read from the URL and storage, persisted, and turned into the Engine request.
 */

export const FEED_MODES = ["recommendations", "hot", "recent", "random", "popular"] as const;

export type FeedMode = (typeof FEED_MODES)[number];

// The panel adds language and saved channels here; storage holds this object whole.
export type FeedParams = {
  mode: FeedMode;
};

const STORAGE_KEY = "feedParams:v1";

/**
 * Resolve the feed parameters in effect: the URL's `?mode=` first, then the stored choice, then recommendations.
 */
export function resolveFeedParams(searchParams: URLSearchParams): FeedParams {
  const fromUrl = searchParams.get("mode")?.trim();
  if (fromUrl) return { mode: parseFeedMode(fromUrl) };
  // Older links name the random feed as ?random=1.
  const legacyRandom = searchParams.get("random");
  if (legacyRandom && legacyRandom !== "0") return { mode: "random" };
  return readStoredFeedParams();
}

/**
 * Persist the feed parameters for the next bare visit.
 */
export function persistFeedParams(params: FeedParams) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(params));
  } catch {
    // Ignore storage errors.
  }
}

/**
 * Turn the feed parameters into the Engine's query entries.
 */
export function feedParamsToQuery(params: FeedParams): [string, string][] {
  return [["mode", params.mode]];
}

/**
 * Return a known feed mode, or recommendations for anything else.
 */
export function parseFeedMode(raw: unknown): FeedMode {
  return FEED_MODES.find((mode) => mode === raw) ?? "recommendations";
}

function readStoredFeedParams(): FeedParams {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null") as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { mode: parseFeedMode((parsed as { mode?: unknown }).mode) };
    }
  } catch {
    // Ignore storage and JSON errors.
  }
  return { mode: "recommendations" };
}
```

**Invariants.**
- Nothing is read at import time.
- A stored value that is `"hot"`, `null`, an array, invalid JSON or an unknown mode resolves to `recommendations`.
- The key `feedParams:v1` does not collide with `localLikes:v1` or `profileKey:v1`.
- `recommendations` is sent explicitly as `mode=recommendations`, which the Engine treats exactly like no mode (criterion 1).

## Client: `client/frontend/src/data/videos.ts`

```ts
import { feedParamsToQuery, type FeedParams } from "./feed-params";

export function buildSimilarUrl(query: SimilarQuery, feedParams?: FeedParams) {
  ... // existing lines 99-105 unchanged
  if (feedParams) {
    for (const [key, value] of feedParamsToQuery(feedParams)) url.searchParams.set(key, value);
  }
  return url.toString();
}

export async function fetchSimilarVideosPayload(query: SimilarQuery, exclude: ExcludedVideo[] = [], feedParams?: FeedParams) {
  const url = buildSimilarUrl(query, feedParams);
  ... // rest unchanged
}
```

The change is backward compatible. The video page (`video-page/index.ts:331`) and the two-argument test callers are unaffected. `createFeedPager` and `MAX_FEED_EXCLUDE` are unchanged.

## Client: `client/frontend/src/pages/videos/index.ts`

- Imports: add `import { persistFeedParams, resolveFeedParams, type FeedMode } from "../../data/feed-params";`.
- Lines 55-56 are replaced with `const feedModeButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-feed-mode]"));`.
- Line 77 becomes `const feedParams = resolveFeedParams(params);`, reading the same `params` object that `debugMode` mutated.
- Line 88 becomes `mode: "random" as "random" | "similar" | "personalized" | "ordered",`.
- The listeners at lines 128-138 are replaced with:

```ts
for (const button of feedModeButtons) {
  const pressed = button.dataset.feedMode === feedParams.mode;
  button.setAttribute("aria-pressed", String(pressed));
  button.classList.toggle("active", pressed);
  button.addEventListener("click", () => chooseFeedMode(button.dataset.feedMode));
}
```

- Line 187:

```ts
    state.mode = useSimilar ? "similar" : feedParams.mode === "random" ? "random" : feedParams.mode === "recommendations" ? "personalized" : "ordered";
```

- `fetchVideosPayload` becomes:

```ts
async function fetchVideosPayload(exclude: ExcludedVideo[] = []) {
  if (useSimilar) {
    return fetchSimilarVideosPayload(similarQuery, exclude);
  }
  // The feed-params module names the mode; the page's own ?random= is folded into it.
  return fetchSimilarVideosPayload({ ...similarQuery, apiBase, random: null }, exclude, feedParams);
}
```

- `pickSample`: the `personalized` branch becomes `if (state.mode === "personalized" || state.mode === "ordered")`, so hot, recent and popular are never shuffled. `random` still shuffles, as today.
- `resolveFeedMode`/`setFeedMode` (917-938) are replaced by:

```ts
/**
 * Persist the chosen feed mode, put it in the URL, and reload the feed from its first page.
 */
function chooseFeedMode(raw: string | undefined) {
  const mode = parseFeedMode(raw);
  persistFeedParams({ ...feedParams, mode });
  const next = new URLSearchParams(window.location.search);
  next.set("mode", mode);
  next.delete("random");
  next.delete("id");
  next.delete("uuid");
  window.location.search = next.toString();
}
```

`parseFeedMode` is added to the import. `host`, `limit`, `api` and `debug` stay in the URL, as today. `random` is deleted, so a stale `?random=1` cannot shadow the chosen mode. The page never names `mode` or `random` in a request. A `?id=` view marks the resolved mode's button but ignores the mode in the request.

## Client HTML: `index.html` and `videos.html` (identical edit)

```html
          <div class="summary-actions">
            <a id="reset-feed" class="ghost-link" href="/?mode=recommendations">Back to recommended</a>
            <div class="feed-modes" role="group" aria-label="Feed mode">
              <button class="ghost-button" type="button" data-feed-mode="recommendations" aria-pressed="false">Recommendations</button>
              <button class="ghost-button" type="button" data-feed-mode="hot" aria-pressed="false">Hot</button>
              <button class="ghost-button" type="button" data-feed-mode="recent" aria-pressed="false">Recent</button>
              <button class="ghost-button" type="button" data-feed-mode="random" aria-pressed="false">Random</button>
              <button class="ghost-button" type="button" data-feed-mode="popular" aria-pressed="false">Popular</button>
            </div>
          </div>
```

The Home nav link stays `/`, so a bare visit restores the stored mode (criterion 8). The section's `hidden` attribute and the `.summary { display: flex }` override stay as they are.

## Client CSS: `videos.css` (after `.ghost-button:hover`)

```css
.feed-modes {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.feed-modes .ghost-button[aria-pressed="true"] {
  border-style: solid;
  border-color: var(--accent);
  color: var(--accent);
}
```

The rule is scoped to `.feed-modes`, so the profile modal's Close button is not restyled.

## Tests

| Group / file | Cases |
|---|---|
| `tests/active/test_random_videos.py` (extend the harness with a ≥5-row fixture: distinct likes/views/popularity, one NULL and one future `published_at`, one signal row, one over-threshold row, one exact tie differing only in `instance_domain`) | hot order equals re-sorting by `popularity + min(signal, cap)` then the tie-breaks. The hot set equals `fetch_popular_videos` membership among embedded rows (set or re-sorted comparison). popular ranks by summed likes, then views. recent is newest-first and excludes NULL and future rows. The error threshold is applied on all three. `limit`/`offset` pages concatenate to the full order with no overlap. The tie pair is ordered by `instance_domain DESC`. The existing cap test (147-167) still passes on both threshold branches. |
| `tests/active/test_similar.py` (real Engine fixture) | Unknown mode gives 400 `{"error":"Unknown mode","allowed":[5 values in order]}`. Empty `mode` and `mode=recommendations` give `seed.mode == "home"` with no `random`, as without a mode. `mode=random` and `random=1` both give `seed.random is True`. Seeded `id=…&mode=hot` and `mode=bogus` give `seed.mode == "upnext"` (unchanged). For hot, popular and recent, page 1 then page 2 with page 1 as `exclude` shows no overlap, and page 2 continues the order. The ordered `seed` has no `random` and no `mode`. Ordered rows are the same with and without body `likes`. The stub children are unchanged and pass. |
| `tests/active/test_server.py` (stubbed-Engine harness) | `?mode=hot` reaches the Engine unchanged. An Engine 400 body is passed through verbatim. `?bogus=1` gives the gateway 400. On a keyed profile with a blocked channel and a disliked video on a hot page, those rows are absent and `limit` is doubled upstream. |
| new `tests/active/test_frontend_feed_params.py` (esbuild + node runner, in-memory `localStorage` on `globalThis` and `window`, like `test_frontend_blocks.py`) | The URL beats storage beats the default. An invalid URL value gives `recommendations`. An empty `?mode=` falls through to storage. Legacy `?random=1` gives random. Stored `"hot"`, `null`, `[]`, bad JSON or an unknown mode give `recommendations`. `persistFeedParams` round-trips. `feedParamsToQuery` gives `[["mode", m]]`. `buildSimilarUrl(q, {mode:"hot"})` carries `mode=hot`, and with no params carries none. |
| `.un/skills/devsecops/config.json` | New group `test_frontend_feed_params.py` → `client/frontend/src/data/feed-params.ts`, `client/frontend/src/data/videos.ts`. Add `engine/server/data/random_videos.py` to the `test_similar.py` group. |

The page wiring (`index.ts`, HTML, CSS) has no automated test. It is covered by a manual check of criterion 8 after `npm run build`, and the `dist/` rebuild is part of delivery.

## Check against the plan and requirements

**Pass 1 found three gaps:**
- the tie-break needed the operator's nod (asked: append to both);
- the legacy `?random=` on the home page was a second way to name random (folded into `resolveFeedParams`, and `random: null` on unseeded requests);
- the walk had no in-request dedupe or bound (seen-set plus `ORDERED_FEED_MAX_CHUNKS` added).

**Pass 2 walked each criterion:**
1. No mode, empty mode or `recommendations` goes to `_handle_home`, and the `seed` payload is unchanged.
2. The three ORDER BY constants read no request data; recent carries the NULL/future filter.
3. `mode=random` and `random=1` go to one branch, `_handle_random`.
4. The Engine answers 400 with `allowed`, and the gateway passes it through (pinned by a test).
5. The exclude-skipping walk over a total order.
6. The error threshold is in SQL, moderation runs per chunk and in `_respond_rows`, and the gateway strips blocks and dislikes.
7. `seeded` bypasses validation and dispatch.
8. The switcher, `aria-pressed`, URL plus storage precedence, and old `?mode=random` links.
9. The allowlist is unchanged and tested.

It also holds against the settled constraints: one module owns the feed params; no new allowlist entry or formula; `seed.mode` is untouched; the mix's `fresh` layer is unchanged and its `popular` layer changes only on exact ties (operator-approved); lock discipline; the stub children are untouched. This pass converged.

## Deliberate simplifications (ceiling → upgrade)

- **OFFSET walk:** paging stops after about 500 shown rows (the three 500 caps), and sooner for keyed visitors whose removed rows pile up. The upgrade is a cursor parameter added through `feedParamsToQuery`.
- **Full sort per chunk for hot and popular:** the ceiling is the 5 s statement budget on large datasets. The upgrade is a precomputed sort column.
- **Mode list duplicated in Engine and Client:** tied together only by tests. The panel's saved-channels mode will need both lists edited.
- **A mode change reloads the whole page** rather than only the feed.
- **Popular's primary key is the uncapped likes sum:** listed for the roadmap (line 33) as an abuse surface.


### Phases

#### Phase 1 - Ordered reads [code]

**Files touched.** engine/server/data/random_videos.py (EDITED), tests/active/test_random_videos.py (EDITED)

**Checkpoint.** Seam: `fetch_ordered_page(conn, order, limit, offset, error_threshold)` called directly on a temporary SQLite copy of real rows from `whitelist.db`. This follows the existing `_two_video_db` harness in `tests/active/test_random_videos.py`, extended to 5 or more embedded rows: distinct likes, views and popularity; one NULL and one future `published_at`; one `interaction_signals` row; one row over the error threshold; and one exact tie that differs only in `instance_domain`. The test is parametrized over the `ORDERED_FEED_ORDER_BY` keys, read from the module at run time. For each order, it concatenates pages fetched at a small `limit` with increasing `offset`. The result must contain no duplicate `(video_id, instance_domain)` and must equal the expected sort. The expected sort for hot is the order `fetch_popular_videos` returns, restricted to embedded rows. For popular it is summed likes desc, then views desc, then `video_id` desc, then `instance_domain` desc. For recent it is `published_at` desc, then `video_id` desc, then `instance_domain` desc. The tie pair must come out in `instance_domain DESC` order. Set assertion, for every order both with and without a threshold: the rows returned equal the embedded rows under the threshold, and for recent the NULL and future `published_at` rows are also left out. The existing cap test (`test_the_popular_order_caps_the_interaction_signal`) must still pass on both threshold branches.

**Intent.** `engine/server/data/random_videos.py` serves each of the three global feed orders one page at a time through `fetch_ordered_page`, and hot ranks by the same `POPULAR_ORDER_BY` constant that `fetch_popular_videos` now uses.

- C1 - For every order in `ORDERED_FEED_ORDER_BY`, consecutive `fetch_ordered_page` pages concatenate into that order's total sort with no row repeated.
- C2 - `fetch_ordered_page` returns exactly the embedded rows under the error threshold, and for recent only those whose `published_at` is neither NULL nor in the future.

**Outcome.** ### `engine/server/data/random_videos.py`
- New `POPULAR_ORDER_BY` constant holds the hot/popular ranking as SQL: popularity plus the interaction signal capped at `POPULAR_SIGNAL_CAP`, then crawled plus signal likes, views, `published_at` and `video_id`, all descending. It ends with a new key, `v.instance_domain DESC`, so two copies of one video on different instances always sort the same way. The cap is written into the SQL as a literal instead of being passed as a `?` parameter, so a parameter can no longer land in the wrong slot.
- `fetch_popular_videos` now ranks by `ORDER BY {POPULAR_ORDER_BY}`, and its params no longer include the cap. Otherwise it behaves as before, apart from the new `instance_domain` tie-break.
- New `ORDERED_FEED_ORDER_BY` dict maps each of the three feed orders to its ORDER BY. `hot` is `POPULAR_ORDER_BY` itself. `popular` is crawled plus signal likes DESC, views DESC, `video_id` DESC, `instance_domain` DESC. `recent` is `published_at` DESC, `video_id` DESC, `instance_domain` DESC. Every order ends on `video_id` then `instance_domain`, so the sort is total and OFFSET pages never repeat or skip a row.
- New `fetch_ordered_page(conn, order, limit, offset, error_threshold=None)` returns one page (`LIMIT ? OFFSET ?`) of embedded videos. It joins `video_embeddings` → `videos`, left-joins `interaction_signals` and `channels`, and sorts by `ORDERED_FEED_ORDER_BY[order]`. An unknown order raises `KeyError`.
  - A positive `error_threshold` keeps rows where `error_count` is NULL or below it, the same rule the other readers use.
  - For `recent` it also drops rows whose `published_at` is NULL or later than now, in epoch milliseconds. I checked the unit against `whitelist.db`: the column is an integer, with a maximum of 1790051327241.
  - Rows use the same columns as `fetch_popular_videos` (including `popularity` and `interaction_signal_score`), except that `likes` is crawled plus signal likes, as in `fetch_random_rows`, to match the key the popular order sorts on.
- New import: `time`.

### `tests/active/test_random_videos.py`
Unchanged, although the files list marks it EDITED. Its cap test runs inside the checkpoint through `test_the_popular_order_still_caps_the_interaction_signal`, and nothing in this phase conflicts with any test in it, so there was nothing to change.

### `tests/tmp/probe_published_units.py`
A throwaway probe I used to check the `published_at` unit. I don't have a delete tool, so I emptied it instead of deleting it; please remove it.

**Beyond the files named.** tests/tmp/probe_published_units.py — throwaway probe for the `published_at` unit; emptied rather than deleted because I have no delete tool, and it should be removed.

#### Phase 2 - Mode validation [code]

**Files touched.** engine/server/api/handlers/similar.py (EDITED), tests/active/test_similar.py (EDITED), tests/active/test_server.py (EDITED)

**Checkpoint.** Engine-side seam: HTTP GET/POST `/recommendations` against the session `engine` fixture (the real Engine on the repo dataset), as the existing `tests/active/test_similar.py` cases do. An unseeded request with `mode=bogus` gets a 400 whose body is exactly `{"error": "Unknown mode", "allowed": list(FEED_MODES)}`, with `FEED_MODES` imported from `api/handlers/similar.py` at run time. A seeded request (`id=<real video>&mode=hot` and `id=<real video>&mode=bogus`) gets a 200 with `seed.mode == "upnext"`, the same as that request without `mode`. Gateway-side seam: the stubbed-Engine harness in `tests/active/test_server.py` (the `_recording_engine`/`_failing_engine` pattern). `?mode=hot` reaches the stub unchanged. A stub 400 `Unknown mode` body is passed to the caller verbatim, with status 400. `?bogus=1` gets the gateway's own 400. The existing `SimpleNamespace` stub-child cases in `test_similar.py` still pass unchanged.

**Intent.** `_handle_similar` in `engine/server/api/handlers/similar.py` validates the `mode` query parameter on unseeded requests only.

- C1 - An unseeded request whose `mode` is outside `FEED_MODES` is answered 400 `{"error": "Unknown mode", "allowed": FEED_MODES}`.
- C2 - A seeded request is served the same up-next whatever its `mode`, including an invalid one.

**Outcome.** ### `engine/server/api/handlers/similar.py`
- New module constant `FEED_MODES = ("recommendations", "hot", "recent", "random", "popular")`, placed next to `SIMILAR_POST_ROUTES`. The 400's `allowed` list uses the tuple's order.
- `_handle_similar` now reads the query parameter `mode_param = params.get("mode", [None])[0]` next to `random_param`. `parse_qs` drops blank values, so an empty `mode=` arrives as missing.
- The first thing inside the `try` is `seeded = bool(vector_param or id_param or uuid_param)`, the same condition that already decides whether `resolve_seed` runs. The `resolve_seed(...)` conditional now uses `if seeded`, so that expression exists in one place only.
- `feed_mode` is `"recommendations"` on a seeded request. On an unseeded request it is the trimmed `mode`, or `"recommendations"` when `mode` is missing or empty. A `feed_mode` outside `FEED_MODES` is answered `400 {"error": "Unknown mode", "allowed": list(FEED_MODES)}` and nothing is served. A seeded request never checks `mode`, so an invalid value there still gets the unchanged up-next.
- The check runs before the random branch, so an unseeded `random=1&mode=bogus` now gets 400 where it used to get random. The plan names this change, and nothing in the tree sends that combination.
- The check sits inside the `try`, so `finally: clear_request_context()` still runs after a 400. The debug 403 still comes first.
- There is no dispatch on `feed_mode` yet: every valid mode takes today's path, and the random, home, up-next and vector branches and `seed.mode` (`home`/`upnext`) are untouched. Routing hot/recent/popular to their own feed is the next phase.

### `tests/active/test_similar.py`, `tests/active/test_server.py`
Not touched. The phase lists both files, but the checkpoint covers everything this phase does, and the existing tests only use parameters these lines don't change.

#### Phase 3 - Mode dispatch and ordered walk [code]

**Files touched.** engine/server/api/handlers/similar.py (EDITED), tests/active/test_similar.py (EDITED), tests/active/test_server.py (EDITED), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: HTTP `/recommendations` against the session `engine` fixture in `tests/active/test_similar.py`. First set: each value of `FEED_MODES` minus `ORDERED_FEED_MODES`, taken from the module at run time, compared with how the same request was spelled before the build. `mode=recommendations` and an empty `mode` both give `seed.mode == "home"` with no `random` key, as no mode does. `mode=random` gives `seed.random is True`, as `random=1` does. Second set, parametrized over `ORDERED_FEED_MODES` at run time: fetch page 1, then page 2 with page 1's rows as `exclude`. The two pages must not overlap. Page 1 followed by page 2 must be an ordered prefix of the `fetch_ordered_page` run for that order, read through a read-only connection on the same dataset with the same threshold, after skipping moderated rows. The ordered `seed` has neither a `random` key nor a `mode` key. The rows are identical with and without body `likes`. Gateway regression pin, in the `tests/active/test_server.py` stubbed-Engine harness: for a keyed profile with a blocked channel and a disliked video, those rows are absent from a `mode=hot` page, and the `limit` sent upstream is doubled.

**Intent.** Every valid unseeded `mode` reaches its feed, and hot, popular and recent are served by `_handle_ordered_feed` as the next rows of their global order after the request's exclude list.

- C1 - Each value in `FEED_MODES` that is not in `ORDERED_FEED_MODES` serves the same feed its pre-build spelling did: recommendations as no mode, random as `random=1`.
- C2 - For each value in `ORDERED_FEED_MODES`, the page requested with the previous page as `exclude` continues that order with no row repeated.

**Outcome.** ### `engine/server/api/handlers/similar.py`
- The import from `data.random_videos` now also brings in `fetch_ordered_page`.
- New module constants next to `FEED_MODES`:
  - `ORDERED_FEED_MODES = frozenset({"hot", "popular", "recent"})`.
  - `ORDERED_FEED_CHUNK_SLACK = 32`: extra rows per chunk, so a few moderated rows rarely force a second query.
  - `ORDERED_FEED_MAX_CHUNKS = 4`: caps the walk, so a heavily moderated order cannot run until the statement deadline.
- Dispatch in `_handle_similar`: after the `Unknown mode` 400, the random branch now also runs when `feed_mode == "random"`, which sends it to the unchanged `_handle_random` with seed `{"random": True}`, the same as `random=1`. Next, a `feed_mode` in `ORDERED_FEED_MODES` goes to `_handle_ordered_feed` before the `resolve_seed` block, so no seed lookup runs for it. `recommendations` (explicit, empty or missing) still takes the existing home path, so its seed is still `{"user_id", "mode": "home"}`. Seeded requests still get `feed_mode = "recommendations"` and are unaffected.
- New method `SimilarHandler._handle_ordered_feed(order, limit, include_debug, request_id, started_at)`, placed after `_handle_random`. It walks `fetch_ordered_page` from offset 0 in chunks of `limit + len(excluded) + ORDERED_FEED_CHUNK_SLACK`, at the server's `video_error_threshold`.
  - From each chunk it drops rows whose `like_key` is in `fetch_request_excluded_keys()`, plus any key already seen earlier in the walk. A row can cross a chunk boundary if a signal lands between two chunks; this keeps its first position.
  - It then runs the remaining rows through `apply_serving_moderation_filters`.
  - It stops once `limit` rows survive, when a chunk comes back short (the order is exhausted), or after `ORDERED_FEED_MAX_CHUNKS` chunks.
  - Each `fetch_ordered_page` call holds `self.server.db_lock`, and the moderation call runs outside it. `db_lock` is a plain `Lock` and moderation takes it itself, so holding it across both would deadlock.
  - The response goes through `_respond_rows` with `rows[:limit]` and `seed_payload={}`, which has no `random` key (so it is not labelled as the fallback) and no `mode` key (so `seed.mode` keeps its home/upnext meaning).
  - Because excluded rows are skipped counting from the head, page N+1 starts at the first row not yet shown, not `len(exclude)` rows ahead.

### `tests/active/test_similar.py`, `tests/active/test_server.py`, `.un/skills/devsecops/config.json`
Not touched. The checkpoint carries this phase. The gateway leg (a hot page with a key drops the blocked channel and the disliked video and doubles `limit` upstream) needs no Client code: `mode` is already allowlisted, and `_filter_payload` with the doubled over-fetch already applies to `/recommendations`. Moving the checkpoint into the durable files and its config group is left to the step that promotes it.

#### Phase 4 - Home feed modes (client) [code]

**Files touched.** client/frontend/src/data/feed-params.ts (NEW), client/frontend/src/data/videos.ts (EDITED), client/frontend/src/pages/videos/index.ts (EDITED), client/frontend/index.html (EDITED), client/frontend/videos.html (EDITED), client/frontend/src/videos.css (EDITED), tests/active/test_frontend_feed_params.py (NEW), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Two seams. Automated seam (clause 1): the new `tests/active/test_frontend_feed_params.py`, following the `tests/active/test_frontend_blocks.py` runner. It bundles `feed-params.ts` and `videos.ts` with esbuild and runs them in node, with an in-memory `localStorage` on `globalThis` and `window`. No Engine or Client server is needed. Given a URL search string and a stored value, it asserts the `mode` entries of `new URL(buildSimilarUrl(q, resolveFeedParams(new URLSearchParams(search))))`, parametrized over the bundle's exported `FEED_MODES` at run time. The cases: a URL mode beats a stored mode, and a stored mode beats the default `recommendations`. An invalid URL value gives `recommendations`. An empty `?mode=` falls through to storage. A legacy `?random=1` with no mode gives `random`. Stored `"hot"` (a bare string), `null`, `[]`, bad JSON and an unknown mode each give `recommendations`. `persistFeedParams` followed by a bare resolve round-trips. `buildSimilarUrl(q)` with no feed params carries no `mode`. A new devsecops config group maps the test to `feed-params.ts` and `videos.ts`. Manual seam (clause 2): the built page in a browser. The operator runs `npm run build` in `client/frontend`, which rebuilds `dist/` and must succeed as the type check of `index.ts`, then serves the Client. Clicking each of the five buttons must reload onto `?mode=<value>`, with `id`, `uuid` and `random` dropped. Only the clicked button may have `aria-pressed="true"` and the pressed style. Hot, recent and popular pages keep their order and are not shuffled. A bare `/` visit afterwards shows the last clicked mode pressed. The profile modal's Close button is not restyled.

**Intent.** The home page resolves its feed mode only through `client/frontend/src/data/feed-params.ts` into the Engine request built by `buildSimilarUrl`, and lets the visitor switch mode with a five-button pressed-state group in `index.html`/`videos.html` wired by `pages/videos/index.ts`.

- C1 - `buildSimilarUrl(q, resolveFeedParams(searchParams))` carries the URL mode, else the legacy `?random=1` mode, else the stored mode, else `recommendations`, with any invalid value mapped to `recommendations`.
- C2 - Clicking a mode button reloads the home page on `?mode=<value>` with only that button marked `aria-pressed="true"`.

**Outcome.** ### client/frontend/src/data/feed-params.ts (NEW)
The one module that handles the feed's parameters, written as the plan's reference code. It exports `FEED_MODES` (the Engine's five modes, in the Engine's order), `FeedMode`, `FeedParams` (`{mode}`), `resolveFeedParams`, `persistFeedParams`, `feedParamsToQuery` and `parseFeedMode`. `resolveFeedParams(searchParams)` checks, in order: a non-empty `?mode=`, which goes through `parseFeedMode`, so an invalid value gives `recommendations`; then legacy `?random=` with any value other than `0`, which gives `random`; then the JSON object stored under `localStorage` key `feedParams:v1`; then `recommendations`. A stored bare string, `null`, an array, bad JSON, an unknown mode or a missing or null mode all read as `recommendations`. `persistFeedParams` writes the object as JSON and ignores storage failures. That matches the existing `cache.ts`/`local-likes.ts` convention, and the URL still carries the choice for the current visit. Nothing is read when the module loads.

### client/frontend/src/data/videos.ts (EDITED)
`buildSimilarUrl(query, feedParams?)` adds whatever `feedParamsToQuery(feedParams)` returns (`mode=<value>`) when it is given params. With none it adds no `mode`, so it behaves exactly as before. `fetchSimilarVideosPayload(query, exclude, feedParams?)` gains an optional trailing parameter and passes it through. Existing callers (the video page, other tests) are unaffected.

### client/frontend/src/pages/videos/index.ts (EDITED)
- The `show-recommendations`/`show-random` lookups and listeners are replaced by `feedModeButtons`, which covers every `[data-feed-mode]` button.
- `feedParams = resolveFeedParams(params)` replaces the local `resolveFeedMode`.
- On load, each button gets `aria-pressed` (true only for the resolved mode) and an `active` class, plus a click handler that calls `chooseFeedMode`.
- `chooseFeedMode` replaces `setFeedMode`. It persists `{...feedParams, mode}`, sets `?mode=<value>` explicitly (`recommendations` included), deletes `random`, `id` and `uuid`, and navigates.
- `fetchVideosPayload` no longer builds `random: "1"` itself. Unseeded requests send `{...similarQuery, apiBase, random: null}` plus `feedParams`. The seeded `?id=` path is unchanged and sends no mode.
- `state.mode` gains `"ordered"` for hot, recent and popular. `pickSample` keeps that case in order like `personalized`, so only random is shuffled.

### client/frontend/index.html, client/frontend/videos.html (EDITED, same edit)
The two buttons become a `div.feed-modes` with `role="group"` and `aria-label="Feed mode"`, holding five `ghost-button`s with `data-feed-mode` and `aria-pressed="false"`, in the order Recommendations, Hot, Recent, Random, Popular. "Back to recommended" now points to `/?mode=recommendations`, so it no longer lands on the stored mode. The Home nav link stays `/`.

### client/frontend/src/videos.css (EDITED)
Added a `.feed-modes` flex layout and a pressed style, `.feed-modes .ghost-button[aria-pressed="true"]`: solid border in the accent colour, accent text. It is scoped to the group so the profile modal's Close button is not restyled.

### .un/skills/devsecops/config.json (EDITED)
Added a new group `test_frontend_feed_params.py` → `client/frontend/src/data/feed-params.ts`, `client/frontend/src/data/videos.ts`.

### tests/active/test_frontend_feed_params.py (NEW, not written this turn)
This is the promoted copy of the gated checkpoint `tests/tmp/test_17_feed_modes_phase4.py`. None of phases 1–3 put their checkpoint into `tests/active/` during implementation, so I left this one for the promotion step rather than duplicating the gated bytes.

### tests/tmp/probe_17_p4_impl.py (probe)
A throwaway probe that bundled both modules with esbuild and ran a few cases in node. Output: `FEED_MODES` = `["recommendations","hot","recent","random","popular"]`; `?mode=hot&random=1` → `mode=hot`; `?random=1` → `mode=random`; bare and `?mode=bogus` → `mode=recommendations`; after persisting `recent`, a bare search → `mode=recent`; `buildSimilarUrl(q)` with no params → no `mode`. It should be deleted, but I have no delete tool.


