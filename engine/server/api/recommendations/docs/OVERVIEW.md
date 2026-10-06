# Recommendations and Feeds — How Every Feed Mode and Up Next Are Built

Short version: the Engine prepares data (embeddings, ANN index, similarity and random
caches) and serves six kinds of page. The home feed (`recommendations` mode) gathers
candidates from `explore/exploit/popular/random/fresh`, assigns a unified `score`, mixes
layers by ratios with a fallback order and applies post-filters (dedup + soft caps).
Up Next draws a page from a scored pool of videos similar to a seed. The `trending`, `popular`
and `recent` feeds page through one global order, `following` pages by cursor through the
newest videos of the request's followed sources, and `random` draws from the random
cache. The Client backend then filters and marks the batch per profile, and the frontend
pages through it (section 8).

## 1) Requests and Modes
- **Home**: the home page calls `/recommendations` without a seed video, in the `recommendations` feed mode (the default).
  The server enables the recommendation strategy and uses the `home` profile.
- **Random**: the `random` feed mode, or `random=1`, serves a draw from the random cache instead of the recommendation mix. With the NSFW filter on, `fetch_random_rows_from_cache` draws up to `RANDOM_CACHE_NSFW_MAX_DRAWS` (4) cache windows, drops ANN ids already seen, and stops when the page is full or a window adds no unseen ANN id. The DB draw (also filtered) runs only when that result is empty.
- **Up Next**: POST `/recommendations?id=&host=`, POST `/videos/similar` or GET `/videos/{id}/similar` with a seed video. The server builds a pool of videos similar to the seed (see "Similarity cache" in section 2), scores it with the `upnext` profile and applies the dislike penalty. The top M rows form the window, where M is `SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR` × `limit`, capped at the pool size. `limit` rows are drawn from the window by score-weighted Efraimidis–Spirakis sampling without replacement, afresh on each request, so refreshing the same seed returns different pages from the same pool. A window of `limit` rows or fewer is returned whole. The page is ordered by the draw weight, descending. An integer `seed` query parameter makes the draw reproducible; only the Engine accepts it (see `engine/server/README.md`).
- **Ordered feeds (trending, popular, recent)**: an unseeded request whose feed mode is `trending`, `popular` or `recent` bypasses the recommendation pipeline. `_handle_ordered_feed` serves the next rows of one global order through `fetch_ordered_page` (`engine/server/data/random_videos.py`). Each order's sort keys are in `ORDERED_FEED_ORDER_BY` and the table its walk starts from in `ORDERED_FEED_SOURCE`:
  - **trending**: the Trending order (see `CONTEXT.md`), the same order as the popular layer. The walk starts from `trending_ranks` (`CROSS JOIN` makes its index `idx_trending_ranks_order` the driving table, so no sort runs) and orders by rank ascending, then the listed likes, listed views, `video_id` and `instance_domain`, all descending, so every host's #1 comes before any #2. Only ranked rows that join an embedded catalogue video are served, and the order ends when they run out, with no fallback. It is empty until `trending_ranks` is first filled (see `engine/server/db/jobs/docs/UPDATER_WORKER.md`).
  - **popular**: crawled likes, then views, `video_id`, `instance_domain`, all descending. It has no age decay.
  - **recent**: `published_at`, then `video_id`, `instance_domain`, all descending. Rows whose `published_at` is NULL or later than now are left out.

  All three rank embedded videos only (trending only the ranked ones among them) and give every visitor the same order. They drop rows at or above the video error threshold, and serving moderation runs over each chunk. The `mode` parameter, its validation and the `random=1` alias are documented in `engine/server/README.md`.
- **Following**: an unseeded request in the `following` feed mode serves the embedded videos of the body's `follows` (channels by `instance_domain` + `channel_id`, accounts by `account_url`, covering every channel the account owns) through `fetch_followed_page` (`engine/server/data/random_videos.py`), newest first by `published_at`, `video_id`, `instance_domain`, all descending. As in recent, undated and future-dated rows are left out; rows at or above the video error threshold and, unless `nsfw=1`, NSFW-flagged rows are dropped inside the query. The body contract (`follows`, `cursor`, their limits) is in `engine/server/README.md`.
  - Each source is one `UNION ALL` term that seeks `idx_videos_channel_published` or `idx_videos_account_published` and reads at most `limit` rows past the cursor, so a quiet source or the last page costs a few index steps. A statement holds at most 500 terms (`FOLLOWED_TERMS_PER_STATEMENT`, SQLite's compound-select cap); larger sets run in batches merged in Python and de-duplicated on (`video_id`, `instance_domain`), since a video can come from both its channel's and its account's term.
  - A full page carries `cursor`, the base64url JSON of its last row's (`published_at`, `video_id`, `instance_domain`); the next page starts strictly after it. A short page carries no cursor and ends the feed. A request with no follows gets an empty page with no cursor, never a fallback.
  - Serving moderation runs after selection, outside `db_lock`, so it can shorten a page but never moves the cursor.
- **NSFW filter**: unless the request opts in with `nsfw=1` (the parameter's contract is in `engine/server/README.md`), every mode and Up Next leave rows with `videos.nsfw = 1` out while the pool or page is built, so a page is still filled to `limit`. For trending, recent and popular the predicate (`NSFW_ALLOWED_SQL`) is inside the ordered query, so the paging walk below steps through the filtered order and flagged rows take no place in a chunk.

Profiles live in `RECOMMENDATION_PIPELINE` (see `engine/server/api/server_config.py`).
If the user has no likes, the profile auto-switches to `guest` (guest_home/guest_upnext),
where only `random/popular/fresh` are active.

### Likes Source
- The Engine ranks only with the likes carried in the request's POST body (`fetch_recent_likes_request` in `engine/server/api/request_context.py`). It stores no likes and has no stored-likes fallback.
- The request's likes come from the Client backend, which sends one of two sets:
  - **Keyless visitor**: a random five of the likes the browser holds in local storage, which the frontend puts in the body.
  - **Keyed visitor** (`X-Profile-Key`): a random five of the profile's 100 most recent stored likes, which the Client backend substitutes for any the browser sent. The browser sends none in this case. The same request carries the profile's dislike taste vectors (`dislike_centroids`, see section 5). A keyed Following request carries the profile's follows instead of either (see `client/README.md`).
- If the body carries no likes, the request is ranked with the guest profile (logged as `likes=no`).
- Client-supplied likes are on by default (`DEFAULT_USE_CLIENT_LIKES` in `server_config.py`). With it off, every request has no likes and gets the guest profile.
- On both POST routes, a `likes` list in the body holds at most 5 entries (`DEFAULT_CLIENT_LIKES_MAX`), each with a non-empty string `uuid` and `host`. A longer list is answered 400 `Too many likes in request body` (with `max_allowed` and `received`), and a malformed entry is answered 400 `Invalid likes payload` (with `reason` and `index`) instead of being skipped. Both checks run before ranking starts.

### Excluded Videos (Paging)
- A POST body may carry `exclude`: `{id, host}` entries naming videos by `video_id` and `instance_domain`, which a paging client has already shown. More than 500 entries (`DEFAULT_CLIENT_EXCLUDE_MAX`) is answered 400.
- **Home**: excluded candidates are dropped from each layer right after it is gathered, and the layers gather `min(len(exclude), batch_size)` extra candidates, so the mix still fills a batch.
- **Up Next**: excluded rows are removed while the pool is built, before scoring and the window, so the next page is drawn from rows not yet shown.
- **Ordered feeds**: the walk starts at offset 0 and reads chunks of `limit + len(exclude) + 32` rows (`ORDERED_FEED_CHUNK_SLACK`), at most 4 of them (`ORDERED_FEED_MAX_CHUNKS`). It skips excluded keys and keys already seen earlier in the walk, so page N+1 starts at the first row not yet shown. It stops once `limit` rows survive moderation, when a chunk comes back short, or at the chunk cap. The client's pager sends at most the last 500 shown rows as `exclude`, so the feed ends after about 500 shown rows. It ends sooner for a keyed visitor whose gateway-removed rows pile up at the head of the order (see `client/README.md`).
- **Random** does not apply `exclude`: a draw from the random cache almost never repeats, and the client drops any repeat.
- **Following** does not apply `exclude`; it pages by cursor (section 1).

## 2) Data Preparation: Embeddings, Index, Cache
1. **Video embeddings**
   Built offline from video text: title, description, tags, category, channel name, comments_count.
   Text is turned into a vector (SentenceTransformer), normalized, and stored in `video_embeddings`.
2. **ANN index**
   Built from embeddings for fast similarity search.
3. **Similarity cache**
   Stores similar lists per seed video (video_id + score + rank).
   Used as a fast candidate source and can refresh when needed.
   If the cache lacks `score`, it is treated as stale and recomputed (refresh).
   Home-layer cache writes are skipped while a live updater build marker exists, and while the handle is stale after a failed reopen: the miss is served but not stored.
   When the updater swaps a new cache file in, the Engine's next cache access under `similarity_db_lock` sees the changed inode and reopens the file without a restart. If the new file is not a valid cache, the Engine keeps reading through its old handle and retries on later accesses. The marker, the swap and the log lines are in `engine/server/db/jobs/docs/UPDATER_WORKER.md`.
   Up Next reads the cache but never writes it, so it does not warm the cache for seeds it has not seen:
   - Cached rows scoring below `SIMILAR_VIDEO_TAIL_MIN_SCORE` are dropped, then the seed, error, NSFW (unless `nsfw=1`), per-author, `exclude` and moderation filters apply. A flagged row is dropped before the author cap and before the pool is counted, so it takes no author slot.
   - If the pool holds fewer than `SIMILAR_VIDEO_TARGET_MIN_POOL` rows, or the cache has no entry for the seed, a live ANN fallback runs. It starts at `SIMILAR_VIDEO_NPROBE` / `SIMILAR_VIDEO_SEARCH_LIMIT` and doubles both on each step up to `SIMILAR_VIDEO_MAX_NPROBE` / `SIMILAR_VIDEO_MAX_SEARCH_LIMIT`. It stops at the target or at both caps. With `nsfw=1` it also stops when a step adds no row. With the NSFW filter on, a step that adds no row still widens while the raw ANN hit count grows, and the ladder stops early only when the hit count stops growing.
   - Hits scoring at least `SIMILAR_VIDEO_MIN_SCORE` are added first. Hits between `SIMILAR_VIDEO_TAIL_MIN_SCORE` and `SIMILAR_VIDEO_MIN_SCORE` are added as a tail only if the pool is still short. Hits pass the same filters as cached rows.
   - The pool is deduplicated by `(video_uuid, instance_domain)` and by `like_key`, with the cached row winning a clash, and capped at `SIMILAR_VIDEO_TOP_K`.
   - The fallback sets nprobe and restores it within one `index_lock` hold, so other routes keep the startup nprobe.
   - `refresh_cache` on Up Next skips the cache read and forces the fallback; it does not rewrite the entry.
   - The score floors compare against ANN scores, which are PQ-approximate.
   - The ANN compute and the cache write are unfiltered, so one cache entry serves both NSFW settings; flagged rows are removed only when entries are resolved into rows.

   The defaults of these constants are in `LAYER_PARAMS.md`.
4. **Random cache**
   Holds a prebuilt list of ANN ids (`random_ann_ids`) for quick random pools.
   Can run in **raw** mode (no filters) or **filtered** mode.
   In filtered mode, `max_per_instance` and `max_per_author` are applied during cache build.
   A build targets `DEFAULT_RANDOM_CACHE_SIZE` rows, counted after filtering in filtered mode.
   The Engine starts listening before any build. At start it opens a usable cache read-only, and a background worker builds a fresh one when refresh is on or no usable cache exists (missing file, missing or empty table, or unreadable). The same worker rebuilds every `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`.
   With refresh off, the Engine reuses any existing non-empty cache as it is, whatever its size.
   Each build is written to a temp file beside the cache and swapped in atomically; a failed build leaves the serving cache as it was.
   While no usable cache is open, random pools are drawn from the DB instead.
   How the cache relates to the NSFW filter is in `LAYER_PARAMS.md`, "Random Cache Params".
   The settings, their defaults and the build steps are in `LAYER_PARAMS.md`, "Random Cache Params".

## 3) Candidate Sources (Generators)
The pipeline uses five layers. Likes are a mechanism inside a layer, not a separate source.
In guest profiles (no likes), only `random/popular/fresh` are active.

- **exploit** — “most similar”.
  Source: ANN or cached similarity from user likes. Both sources drop NSFW-flagged rows unless the request carries `nsfw=1`.
  Filter: `similarity >= exploit_min` (fixed threshold).
  Caps: `max_per_author/max_per_instance` are applied inside the layer.
  Ranking: by `similarity_score`.
  Selection: random sample from the filtered pool up to the layer limit.
  Requires likes: if there are no likes, the layer is disabled.
  If there are no likes, the layer is empty (fallback goes to random/popular).

- **explore** — “moderately similar”.
  Source: random cache (or random from DB while the cache is missing, not yet built or empty).
  Filter: `similarity_min <= similarity < similarity_max` vs user likes.
  Caps: `max_per_author/max_per_instance` are applied inside the layer.
  Ranking: by `similarity_score`.
  Selection: random sample from the filtered pool up to the layer limit.
  Requires likes: if there are no likes, the layer is disabled.
  If there are no likes, the layer is empty (fallback goes to random/popular).

- **popular** — “popular videos”.
  Source: the head of the Trending order, `fetch_popular_videos` → `fetch_ordered_page(conn, "trending", pool_size, 0, …)` (`engine/server/data/random_videos.py`), with the same error and NSFW filters as the trending feed (see section 1).
  Pool is limited by `pool_size`.
  While `trending_ranks` is empty the pool is empty and the layer adds nothing. `guest_home` still fills its batch from the other layers; `home` with likes gathers the popular share up front, so its batch comes back short by that share (about 5 of 48) until the first fill.
  Caps: `max_per_author/max_per_instance` are applied inside the layer.
  If likes exist, each entry gets a `similarity_score` against the likes.
  Selection: with likes, a draw without replacement weighted by `similarity ** weighted_random_alpha`; otherwise a uniform random sample from the pool (see `LAYER_PARAMS.md`, "popular Layer").

- **random** — “random videos”.
  Source: random cache (or random from DB while the cache is missing, not yet built or empty). With the NSFW filter on, the cache draw redraws past flagged rows (see "Random" in section 1).
  Caps: `max_per_instance/max_per_author` are applied inside the layer.
  Optional: keep only items below `explore_min`.
  Selection: random sample from the pool.

- **fresh** — “recent videos”.
  Source: latest videos from DB.
  Pool is limited by `pool_size`.
  Caps: `max_per_author/max_per_instance` are applied inside the layer.
  If likes exist, similarity to likes influences `similarity_score`.
  Selection: random sample from the pool after sorting.

## 4) How Many Candidates to Fetch (Fetch Limits)
- `gather_ratio` (collection) and `mix_ratio` (output) are set per profile in `RECOMMENDATION_PIPELINE`.
- Candidate fetch limits are computed from batch size and multiplied by `overfetch_factor`.
- These are pool-building limits, not final output counts.
- Every layer's source leaves NSFW-flagged rows out unless the request carries `nsfw=1`; random and explore use the cache redraw described under "Random" in section 1. A like neighbourhood with many NSFW videos can leave the exploit pool short, and fallback (section 6) then fills its slots from other layers, shifting the layer ratio.

### What “Pools” Are and How They Are Built
A pool is a layer-local candidate list built before mixing.
Each layer builds its own pool from its own source:
- **exploit pool**: ANN or cache from likes, filtered by `similarity >= exploit_min`, then caps.
- **explore pool**: random cache or DB, filtered by `similarity_min <= similarity < similarity_max`, then caps.
- **random pool**: random cache; optionally filtered by `similarity < explore_min`, then caps.
- **popular pool**: the first `pool_size` rows of the Trending order; then caps; if likes exist, a similarity-weighted draw.
- **fresh pool**: latest videos; if likes exist, `similarity_score` is set; then caps.

Important: pool limits only affect candidate gathering.
Candidates are later scored and mixed by layer ratios to form the final batch.

## 5) Unified Scoring
Each candidate gets a unified `score` based on:
- **similarity** (when available; from ANN/cache or `similarity_score` for fresh).
- **freshness** (decay based on `published_at`, half-life is configured).
- **popularity** (log-normalized function of views/likes).
- **layer bonus** (optional source weights).

Formula:
`score = w_sim * similarity + w_fresh * freshness + w_pop * popularity + layer_bonus`

The final `score` is stored in the row and used for ordering.

**Dislike penalty.** A request may carry `dislike_centroids`: up to four taste vectors the Client backend obtained for a visitor's dislikes from `/internal/dislikes/centroids`. They are used only when their `space` names the embedding model the Engine serves. For each candidate whose cosine to its nearest centroid is at least `DISLIKE_SIMILARITY_FLOOR` (0.5), `w_sim * cosine` is subtracted from `score` and recorded as `dislike_penalty`. This applies on home (after scoring, before mixing) and on up-next (over the whole pool, before the window is taken). On up-next with likes, `rerank_related_videos` (`RELATED_VIDEOS_PERSONALIZATION`) then reranks the window before the draw, and its `personalized_score` is the draw weight and the page order; that score keeps the full penalty. The Engine stores nothing about the visitor.

## 6) Layer Mixing (mix_ratio + fallback)
- Final output is built by `mix_ratio` per layer, not by a shared exploit/explore bucket.
- If some layers are disabled/empty (e.g. no likes -> explore/exploit), `gather_ratio` and `mix_ratio`
  are normalized across active layers so the batch stays filled.
- If a layer cannot fill its quota, fallback follows: `explore -> exploit -> popular -> random -> fresh`.
- Within each layer, candidates are ordered by `score`, then mixed by a layer schedule.
- Candidates carrying a `dislike_penalty` are set aside while the schedule fills and are placed after
  every other candidate, so videos near a dislike sit below the rest of the batch rather than keeping
  their layer's slots.

## 7) Post-Filters
After mixing, post-processing applies:
- **Dedup**: remove already liked videos and duplicates across layers.
- **Soft caps**: optional per-layer min/max constraints.

The result is a mixed batch with controlled diversification.

## 8) What the Client Receives
### The Engine's batch
- The Engine answers with an ordered batch of videos, already mixed (home), drawn (Up Next, random) or ordered (trending, popular, recent, following).
- The response includes `seed` with the profile mode (`home` or `upnext`). The ordered feeds and Following answer with an empty `seed`, which has no `mode` and no `random` key.
- Only Following's answer carries a `cursor` key, and only when the page is full.

### The Client backend's read gateway
The browser never calls the Engine directly; `/recommendations` and `/videos/similar` pass through the Client backend, which caps a page at 48 rows. For a request carrying `X-Profile-Key`, the gateway removes the profile's blocked channels and accounts and its disliked videos from the Engine's rows. When the profile has blocks or dislikes, it asks the Engine for twice the page and trims the result back, so the page stays full; in Following it does neither, so a page can be short, or empty while still carrying the Engine's cursor. It marks each remaining row the profile likes with `reaction: "liked"`. In the trending, popular and recent feeds the removed rows are never shown, so they are never excluded and come back at the head of every later page; a profile with many of them near the top of an order gets short pages. A request without the header passes through unchanged. The full gateway contract is in `client/README.md`.

### How the frontend pages a feed
- The frontend pages every feed but Following through `createFeedPager` (`client/frontend/src/data/videos.ts`). Each batch request sends the rows already shown, at most the last 500, as `exclude`. The pager drops any row it has already shown, and a batch that adds no new row, or fails, ends the feed.
- **Home and the ordered feeds**: the page reveals fetched rows in small steps as the visitor scrolls and asks for the next batch when the revealed rows reach the end of those fetched. The Engine skips the excluded rows as section 1, "Excluded Videos (Paging)", describes.
- **Up Next**: the video page asks for batches of 48 similar videos and reveals them 8 at a time; the videos page opened with `?id=` pages the same seed the way home does. Each later batch is drawn from the pool rows not yet shown.
- **Random**: the pager sends `exclude` as for any feed, but the Engine ignores it; the pager drops the rare repeat.
- **Following**: `createCursorPager` sends the last cursor and no `exclude`. One fetch walks on through empty pages that carry a cursor, pausing 3 s after every 4 requests to stay under the Client's rate limit, and the feed ends only when a page comes back with no cursor. A failed fetch keeps the cursor, so the next attempt asks for the same page.
- The frontend renders every feed in the order received, except random, which it shuffles.
