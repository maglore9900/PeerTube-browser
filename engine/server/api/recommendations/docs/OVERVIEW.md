# Home Recommendations — How the Feed Is Built (Detailed)

Short version: the server prepares data (embeddings/index/cache), gathers candidates
from `explore/exploit/popular/random/fresh`, assigns a unified `score`, then mixes
layers by ratios with a fallback order and applies final post-filters (dedup + soft
caps) before returning a batch to the client.

## 1) Requests and Modes
- **Home**: the home page calls `/recommendations` without a seed video, in the `recommendations` feed mode (the default).
  The server enables the recommendation strategy and uses the `home` profile.
- **Random**: the `random` feed mode, or `random=1`, serves a draw from the random cache instead of the recommendation mix. With the NSFW filter on, `fetch_random_rows_from_cache` draws up to `RANDOM_CACHE_NSFW_MAX_DRAWS` (4) cache windows, drops rowids already seen, and stops when the page is full or a window adds no unseen rowid. The DB draw (also filtered) runs only when that result is empty.
- **Up Next**: POST `/recommendations?id=&host=`, POST `/videos/similar` or GET `/videos/{id}/similar` with a seed video. The server builds a pool of videos similar to the seed (see "Similarity cache" in section 2), scores it with the `upnext` profile and applies the dislike penalty. The top M rows form the window, where M is `SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR` × `limit`, capped at the pool size. `limit` rows are drawn from the window by score-weighted Efraimidis–Spirakis sampling without replacement, afresh on each request, so refreshing the same seed returns different pages from the same pool. A window of `limit` rows or fewer is returned whole. The page is ordered by the draw weight, descending. An integer `seed` query parameter makes the draw reproducible; only the Engine accepts it (see `engine/server/README.md`).
- **Ordered feeds (hot, popular, recent)**: an unseeded request whose feed mode is `hot`, `popular` or `recent` bypasses the recommendation pipeline. `_handle_ordered_feed` serves the next rows of one global order through `fetch_ordered_page` (`engine/server/data/random_videos.py`), and the orders are defined in `ORDERED_FEED_ORDER_BY`:
  - **hot**: `POPULAR_ORDER_BY`, the same order as the popular layer: `popularity`, then crawled likes, views, `published_at`, `video_id`, `instance_domain`, all descending.
  - **popular**: crawled likes, then views, `video_id`, `instance_domain`, all descending. It has no age decay.
  - **recent**: `published_at`, then `video_id`, `instance_domain`, all descending. Rows whose `published_at` is NULL or later than now are left out.

  All three rank embedded videos only and give every visitor the same order. They drop rows at or above the video error threshold, and serving moderation runs over each chunk. The `mode` parameter, its validation and the `random=1` alias are documented in `engine/server/README.md`.
- **NSFW filter**: unless the request opts in with `nsfw=1` (the parameter's contract is in `engine/server/README.md`), every mode and Up Next leave rows with `videos.nsfw = 1` out while the pool or page is built, so a page is still filled to `limit`. For hot, recent and popular the predicate (`NSFW_ALLOWED_SQL`) is inside the ordered query, so the paging walk below steps through the filtered order and flagged rows take no place in a chunk.

Profiles live in `RECOMMENDATION_PIPELINE` (see `engine/server/api/server_config.py`).
If the user has no likes, the profile auto-switches to `guest` (guest_home/guest_upnext),
where only `random/popular/fresh` are active.

### Likes Source (Temporary No-Auth Mode)
- By default the server can accept likes from client JSON (e.g. localStorage).
- If the JSON is empty or has no likes, `likes=no` and the guest profile is used.
- If this mode is disabled, likes are read from `users.db`.
- On both POST routes, a `likes` list in the body holds at most 5 entries (`DEFAULT_CLIENT_LIKES_MAX`), each with a non-empty string `uuid` and `host`. A longer list is answered 400 `Too many likes in request body` (with `max_allowed` and `received`), and a malformed entry is answered 400 `Invalid likes payload` (with `reason` and `index`) instead of being skipped. Both checks run before ranking starts.

### Excluded Videos (Paging)
- A POST body may carry `exclude`: `{id, host}` entries naming videos by `video_id` and `instance_domain`, which a paging client has already shown. More than 500 entries (`DEFAULT_CLIENT_EXCLUDE_MAX`) is answered 400.
- **Home**: excluded candidates are dropped from each layer right after it is gathered, and the layers gather `min(len(exclude), batch_size)` extra candidates, so the mix still fills a batch.
- **Up Next**: excluded rows are removed while the pool is built, before scoring and the window, so the next page is drawn from rows not yet shown.
- **Ordered feeds**: the walk starts at offset 0 and reads chunks of `limit + len(exclude) + 32` rows (`ORDERED_FEED_CHUNK_SLACK`), at most 4 of them (`ORDERED_FEED_MAX_CHUNKS`). It skips excluded keys and keys already seen earlier in the walk, so page N+1 starts at the first row not yet shown. It stops once `limit` rows survive moderation, when a chunk comes back short, or at the chunk cap. The client's pager sends at most the last 500 shown rows as `exclude`, so the feed ends after about 500 shown rows. It ends sooner for a keyed visitor whose gateway-removed rows pile up at the head of the order (see `client/README.md`).
- **Random** does not apply `exclude`: a draw from the random cache almost never repeats, and the client drops any repeat.

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
   Holds a prebuilt list of rowids for quick random pools.
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
  Source: top by `POPULAR_ORDER_BY` (`engine/server/data/random_videos.py`): `popularity`, then crawled likes, views, recency, video id and instance domain. The hot feed uses the same order (see section 1).
  Pool is limited by `pool_size`.
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
- **popular pool**: top by `popularity`, then crawled likes and views; then caps; if likes exist, a similarity-weighted draw.
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
- The client receives a ready-to-render list of videos (batch), already ordered/mixed on the server.
- The frontend does not re-sort recommendations; it renders as-is.
- The response includes `seed` with the profile mode (`home` or `upnext`). The ordered feeds answer with an empty `seed`, which has no `mode` and no `random` key.
