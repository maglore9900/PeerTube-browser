# 35-upnext-tests-retired-by-random

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/20-35-upnext-tests-retired-by-random.record.md`._

## Requirements

### Purpose

Build 09 (issue `09-similars-diversity`, plan `docs/project/plans/archive/19-09-similars-diversity.md`) made every up-next page (`POST /recommendations?id=…&host=…`, `POST /videos/similar`) a random score-weighted draw. At its step 8 it retired the tests that assumed a plain up-next page repeats to `tests/archive/upnext_random_draw/`. This build puts that behavioural coverage back in `tests/active`, in a form the random draw cannot flake and cannot pass vacuously. The suite then guards again that up-next honours `exclude`, dislike centroids, profile dislikes and profile blocks, through the Engine, through the Client gateway and through the frontend data modules. It is a test-and-config build only, and no product code changes.

### What the tree holds now (found by reading, relied on below)

- **Up-next pool and draw.**
  - `engine/server/data/similarity_candidates.py` builds a seed's pool, cut to `SIMILAR_VIDEO_TOP_K` (300) after the one-row-per-author cap.
  - Only then does it drop the request's `exclude` keys (lines 205-208). The pool a seed can ever serve is therefore bounded at about 300 rows.
  - The serve-time fallback runs again when exclusion leaves the pool short.
  - `engine/server/api/handlers/similar.py` ranks the pool with the dislike penalty applied (`score_and_rank_list`, `apply_dislike_penalty`).
  - It takes the window `rows[:min(SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR * limit, len(rows))]` and calls `_draw_page`.
  - `_draw_page` returns the window whole, in ranked order, when `len(window) <= limit` (line 1194). Otherwise it does a weighted draw, returned ordered by weight.
  - With the `seed=<int>` query parameter, each row's uniform is tied to the draw seed and the row's `like_key`, so a seeded request repeats exactly. Without it, every request is a fresh draw.
- **Client gateway (`client/backend/server.py`).**
  - It forwards `exclude` (at most `MAX_FEED_EXCLUDE` = 500 entries), `likes`, `mode` and `user_id` to the Engine on `/recommendations` and `/videos/similar`.
  - It does not forward `seed`: it is not in `PROXY_ALLOWED_QUERY_PARAMS`, and the Client answers 400 "Unknown query parameter: seed".
  - It caps a feed `limit` at `FEED_PAGE_SIZE` = 48.
  - When the presented profile has blocks or dislikes, it asks the Engine for `FEED_OVERFETCH_FACTOR` (2) x the page and trims the filtered result back to one page.
  - It attaches the profile's `dislike_centroids` to the Engine request.
- **Engine limits.** The Engine refuses more than 500 `exclude` entries (`DEFAULT_CLIENT_EXCLUDE_MAX`). It rate-limits at `DEFAULT_RATE_LIMIT_MAX_REQUESTS` = 60 per `DEFAULT_RATE_LIMIT_WINDOW_SECONDS` = 60 per `ip:path`.
- **`tests/active/conftest.py`** holds none of the helpers plan 19 §7a drafted (`exclude_entries`, `upnext_pool`, `pin_upnext`). It does hold `engine`, `engine_client`, `unpublished_client`, `dataset`, `embedding_of`, `cosine` and `closeness`.
- **The frontend pager coverage is already restored.** Build 12 (`12-similars-on-scroll`) added `tests/active/test_frontend_upnext_pager.py`, whose docstring says it replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). `.un/skills/devsecops/config.json` has no `test_frontend_videos.py` entry and already maps `test_frontend_upnext_pager.py`.
- **Still missing from `tests/active`** (each confirmed by reading the active files, which carry only the non-up-next tests):
  - `test_similar`: the up-next exclude test.
  - `test_dislike_profile`: both centroid tests; only the centroid-shape test is active.
  - `test_dislikes`: both up-next tests; only the action and key tests are active.
  - `test_blocks`: the two up-next cases of the surfaces test (only `search` is active) and the stays-full test.
  - `test_frontend_blocks`: the module block test; only the refused-key test is active.
- **Retired reference copies.** These are in `tests/archive/upnext_random_draw/`: `test_similar.py`, `test_dislike_profile.py`, `test_dislikes.py`, `test_blocks.py`, `test_frontend_blocks.py` and `test_frontend_videos.py`, all skip-marked.

### R1 - Shared up-next pinning helpers in `tests/active/conftest.py`

- **What they are.** Plain module-level helpers, not fixtures, starting from plan 19 §7a:
  - `exclude_entries(rows)` gives the `exclude` body entries `{"id": video_id, "host": instance_domain}` naming those rows.
  - `upnext_pool(engine, route, seed)` gives every row of a seed's up-next pool on `route`. It lists them directly on the Engine by repeated seeded requests at a large limit, each excluding everything already listed, until a page comes back empty. The result is cached for the session per `(route, seed video_uuid, seed instance_domain)`.
  - `pin_upnext(engine, route, seed, chosen)` gives the `exclude` entries that leave exactly `chosen` of that pool. It checks this directly on the Engine, and when a narrower pool lets the fallback surface rows the listing had not reached, it widens the exclude and retries a bounded number of times.
- **Why a pin works.**
  - A pinned request sends that `exclude` with `limit >= len(chosen)`, so the window is no larger than the limit and is served whole.
  - A pinned page is therefore a fixed set of rows, in ranked (dislike-penalised) order. This holds keyless or keyed, through the Engine or through the Client, which cannot forward `seed`.
- **Guarantees the helpers must give.**
  - A pin is deterministic and does not depend on the random draw.
  - Every exclude list stays within the 500-entry cap.
  - When the listing does not end, or the pin cannot be made, the helper raises an `AssertionError` naming what it could not do. It never returns a partial pin.
- **Docstring.** The conftest module docstring gains one line describing these helpers.

### R2 - `test_similar`: up-next honours `exclude`

- **The test.** It is restored as an active test in `tests/active/test_similar.py`, parametrised over the seeds of search queries "linux" and "cooking", directly on the Engine.
- **What it asserts.**
  - An up-next request excluding a previous 8-row page, or every other row of that page, returns a full 8-row page.
  - That page holds none of the excluded rows.
  - Every row on it has debug `similarity_score` at or above `SIMILAR_VIDEO_TAIL_MIN_SCORE`, which defines membership of the seed's pool.
- **How it avoids the draw.** No assertion depends on two unseeded draws being equal; requests use a fixed `seed` where a reference page is needed.
- **Text.** The module docstring gains the matching bullet.

### R3 - `test_dislike_profile`: a dislike centroid moves pages away from the disliked video

Both tests are restored in `tests/active/test_dislike_profile.py`, parametrised over the "cooking" and "linux" seeds, directly on the Engine.

- **(a) Up-next.**
  - Every request (plain, with d1's centroid, with d2's centroid) uses the same fixed draw `seed`, so the pages are the same draw with and without the centroid.
  - The leading 8 rows other than d1 and d2 of the page carrying a video's centroid are less close (`closeness`) to that video than those of the plain page.
  - The margin closeness(d1) - closeness(d2) is lower on the d1 page than on the d2 page.
- **(b) Home.**
  - Home pages liked from the seed, carrying d1's or d2's centroid, place rows clearly similar to that video (cosine >= 0.6) lower than plain home pages do, and the d1-versus-d2 lean holds as before.
  - **Correction to plan 19 §7c.** d1 and d2 must not be the least similar pair on one up-next draw. They are chosen so that each has at least one clearly similar row (cosine >= 0.6, other than d1 and d2) on every plain home page, for example from the pool's head or by checking coverage on the plain home pages.
  - That coverage is asserted as a control before the comparison.
  - The pair stays dissimilar to each other (cosine < 0.7), as before.

### R4 - `test_dislikes`: a profile's dislike through the Client

Both tests are restored in `tests/active/test_dislikes.py`, parametrised over routes `/recommendations` and `/videos/similar` and the seed queries in use ("linux", "football", or other seeds whose pool is deeper than one page plus one). They run through `unpublished_client`, and every up-next page is pinned (R1).

- **Absent and present.**
  - The keyless page pinned to the pool's first 16 rows is exactly those 16. The disliked video is the 9th row.
  - The disliking profile's page is pinned to the first 17. The Engine serves 17, the Client drops the disliked one, and the page is a full 16 without it.
  - Keyless and bystander requests use the 16-row pin. The bystander dislikes `keyless[0]`. Both contain the disliked video.
- **Lean-away.**
  - All three pages (keyless, disliking d1, disliking d2) use the same 16-row pin, so they hold one fixed set in penalised order.
  - The existing closeness and margin assertions on the leading 8 other rows are kept.
  - The pair is the least similar pair on the pinned page, asserted to have cosine < 0.7.

### R5 - `test_blocks`: a profile's blocks on up-next

In `tests/active/test_blocks.py`:

- **The surfaces test.**
  - `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page` is parametrised over `/recommendations`, `/videos/similar` and `search` again.
  - The up-next surfaces send a pin of the pool's first 8 rows on every request (keyless, blocker, bystander), so the keyless page is exactly those 8.
  - The targets are taken from it, and the existing assertions hold: blocker absent, keyless and bystander present.
  - The search case is unchanged.
- **The stays-full test.**
  - `test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it` is restored for both routes, pinned so that the rows on blocked channels would otherwise be served.
  - A control asserts that the blocked rows are on the keyless pinned page.
  - The blocker's page is a full 8, refilled from the Client's 2x over-fetch, with no blocked channel.
  - **Correction to plan 19 §7e,** which left this test unpinned: a probe saw the blocked channels absent from the blocker's over-fetched draw in 6 of 12 trials per route.
- **Text.** The module docstring regains the up-next bullets, and the "retired" comment above the surfaces test is removed.

### R6 - `test_frontend_blocks`: a channel blocked through `blocks.ts`

In `tests/active/test_frontend_blocks.py`, the test `test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches` is restored.

- **Runner.** The node runner's up-next fetch passes a pin as `fetchSimilarVideosPayload`'s exclude argument, supplied through the environment.
- **Targets.**
  - `_seed_and_targets` pins the `/recommendations` pool's first 8 rows and takes the up-next target from them.
  - It takes the search target from a search row sharing no channel with the pinned rows.
- **Assertions.**
  - Before the block, both targets' channels are on the rows fetched (control).
  - After `blockVideoSource`, both fetches still return rows, and neither carries its blocked channel.
- **Text.** The module docstring regains the bullet.
- **The refused-key test stays as it is.** It may use the new `_seed_and_targets` signature.

### R7 - Test selection map

In `.un/skills/devsecops/config.json` (plan 19 §7i):

- add `engine/server/api/handlers/similar.py` and `engine/server/data/similarity_candidates.py` to `test_blocks.py`, `test_dislikes.py` and `test_frontend_blocks.py`;
- add `engine/server/data/ann.py` and `engine/server/data/similarity_candidates.py` to `test_dislike_profile.py`.

No `test_frontend_videos.py` entry exists, so nothing is dropped.

### R8 - Retired copies

Move all six files in `tests/archive/upnext_random_draw/` to `delete_me/`, which leaves that archive folder empty or removed. This includes `test_frontend_videos.py`, already replaced by build 12. The operator chose this.

### Constraints

- **Tests and config only.** No change to Engine, Client or frontend product code, and no new dependency.
- **Style.** New code matches the style of the file it lands in: naming, helper shape, docstring bullets, and comments one line each.
- **No flakes.** Every restored assertion is independent of the unseeded random draw. Each restored test passes on repeated runs.
- **Rate budget.**
  - Live-Engine tests stay within 60 requests per 60 s per `ip:path`.
  - Pool listings are cached per session, so a pool is listed once.
  - The listing's requests count against the Engine's `/recommendations` or `/videos/similar` bucket.
- **Controls before absences.** Every absence assertion is preceded by a control proving the absent rows would otherwise be served.

### Baseline suite state

The pre-build suite exited 0, variant false. The selector ran 1 of 46 test groups (`test_search_fusion.py`, 10 passed); 45 were unchanged.

### Out of scope

- The frontend pager test, already restored by build 12 in `tests/active/test_frontend_upnext_pager.py`.
- Plan 19 §7d's `test_upnext_diversity` module. Its coverage already lives in `tests/active/test_similar.py` and `tests/active/test_server_config.py`.
- Any change to up-next behaviour, the Client's over-fetch, or the exclude caps.
- Issue 35's own status line and archive move, which happen at harvest by the workflow.

### Acceptance criteria

- `tests/active` contains active (not skipped) tests for each of R2-R6, asserting the behaviours stated there, and they pass.
- Each restored test passes on repeated runs, with no outcome depending on the random draw.
- Each restored blocks or dislikes test's control fails if the target row is not on the pinned keyless page.
- The conftest helpers from R1 exist, and their failures raise a descriptive `AssertionError`.
- `config.json` carries the R7 mappings.
- `tests/archive/upnext_random_draw/` no longer holds the six files, which are in `delete_me/`.
- The full `tests/active` suite exits 0. A `conftest.py` change reselects broadly, so the suite runs with one invocation per live-Engine file.

## High-level plan

### Approach

The whole build rests on one property of the Engine, which I confirmed by reading `engine/server/api/handlers/similar.py`. `_draw_page` returns the window whole, in ranked order, when `len(window) <= limit` (line 1194). Pool membership is fixed before any draw happens. `get_upnext_candidates` builds the pool from the cache and the ANN fallback, and both are deterministic for a given `exclude`. It drops excluded keys after the author cap and the `top_k` cut (`_upnext_rows`, lines 204-208), so an excluded row keeps its author slot and its top-300 slot, and nothing refills behind it. `UpnextPoolPolicy` does not depend on `limit`, likes or dislike centroids: the pool is the same whatever page size is asked and whoever asks. Centroids and likes change only the ranking, and through the ranking the order of a whole-window page. So if a request excludes everything in the pool except a chosen set and asks for at least that many rows, it is served exactly that set, ordered by penalised score, with no draw. This holds with or without a key, and through the Engine or through the Client. The Client cannot forward `seed`, but it does forward `exclude` (up to 500) and `limit` (capped at 48, doubled to at most 96 for over-fetch). Every Client-side test below rests on this pin. The two direct-Engine tests (R2, R3a) use the `seed` parameter instead, because the requirements ask for a coupled draw there and it costs no listing.

**R1, conftest helpers.** Three plain functions and a few module constants are added to `tests/active/conftest.py`, in the style of `embedding_of` and `closeness`: typed signatures, one-line docstrings, one-line comments. The module docstring gains one line.

- **`exclude_entries(rows)`** maps rows to `{"id": video_id, "host": instance_domain}`.
- **`upnext_pool(engine, route, seed)`** lists the pool directly on the Engine.
  - It sends `POST {route}?id=…&host=…&limit=96&seed=0&debug=1`. 96 is the Engine's cap (`default_limit * 2`). Each request carries the `exclude` of everything listed so far, and the listing stops on the first empty page.
  - The listing is seeded so that it is deterministic. Each excluding request can leave the pool short and step the fallback, so which rows are listed at which step must not depend on a fresh draw.
  - It runs at most `ceil(500/96) + 1` pages. Before every request it checks that the exclude would stay at or under 500. If it would not, or the pages run out before an empty one comes back, it raises `AssertionError` naming the route, the seed and how many rows it had listed. It never returns a partial pool.
  - It returns the rows sorted by debug `similarity_score`, highest first, ties broken by key. "The pool's first n rows" then means its head, the rows that stay in every widened top-300. Listing order would not do: it is a weighted draw and can put a tail row first, and a tail row may not survive the widened fallback that a narrow pin triggers.
  - The result is cached in a module dict keyed `(route, video_uuid, instance_domain)`, so each pool is listed once per pytest process.
- **`pin_upnext(engine, route, seed, chosen)`** finds the exclude that leaves exactly `chosen`.
  - It starts from pool minus chosen. It checks with one seeded `limit=96` request (any limit ≥ `len(chosen)` would do, since the pool does not depend on limit). It returns the entries when the served key set equals `chosen`.
  - If extra rows were served, which happens when the narrower pool steps the fallback further, it adds them to the exclude and retries, at most 3 times. The 500 check runs before each send.
  - If a chosen row is missing, or the tries run out, it raises `AssertionError` naming the missing and extra keys.
- **Rate bucket.** Both helpers send a dedicated `X-Client-IP` from TEST-NET-1 that the suite does not use yet, as a conftest constant. This is the idiom of `DRAW_HEADERS`/`POOL_HEADERS` in `test_similar.py`. Listing and pinning then count against their own `ip:/recommendations` or `ip:/videos/similar` bucket and never eat a test's own `127.0.0.1` budget.

**R2, `test_similar`.** A test parametrised over a new `UPNEXT_SEED_QUERIES = ("linux", "cooking")`, using the file's existing `_upnext_path`, `_config()` and `_keys`, and a new dedicated header constant next to `DRAW_HEADERS`.

- One reference request at `limit=8&seed=<n>&debug=1`, then two more with the same seed: one excluding the whole reference page, one excluding every other row of it.
- Each must return 8 rows, none of them excluded, every one with `similarity_score >= SIMILAR_VIDEO_TAIL_MIN_SCORE - 1e-6`.
- The assertions hold for any draw, and the seed only fixes the reference. That is 3 requests per seed. The docstring gains the bullet.

**R3, `test_dislike_profile`.** `DRAW_SEED` is added, and `_seed_and_pair`'s path becomes `limit=16&seed=DRAW_SEED`.

- **(a)** Unchanged in shape. The plain page and both centroid pages are now the same coupled draw: each row keeps its uniform, so a penalised row only loses weight. The closeness and margin assertions follow.
- **(b)** The five plain home pages are fetched first.
  - The candidates are the seeded 16-row up-next page, the pool's head as drawn. A candidate is covered when every plain home page holds a row, other than the candidate, with cosine ≥ 0.6 to it.
  - d1 and d2 are the least similar covered pair. The control asserts that such a pair exists with cosine < 0.7, and that each of d1 and d2 still has a clearly similar row on every plain page once both are left out (the old `p < len(rows)` check).
  - Only then are the 10 shaped pages fetched and the old `min(shaped) > max(plain)` and lean assertions run.
  - The docstring bullets come back with the "same draw" wording.

**R4, `test_dislikes`.** Through `unpublished_client`, with `_seed`, `_upnext` (gaining a `body` argument), `_profile_disliking`, `_pair` and `_margin` restored from the archive. Each test gains `engine`.

- **Absent/present.**
  - `pool = upnext_pool(...)`, with a depth control `len(pool) > PAGE + 1`. `pin16 = pin_upnext(pool[:16])` and `pin17 = pin_upnext(pool[:17])`.
  - The keyless page under pin16 at limit 16 must have exactly pool[:16]'s key set. This is the control, and `disliked = keyless[8]` comes from it.
  - The profile's page uses pin17 at limit 16. The Client over-fetches 32, the Engine serves 17 whole, the Client drops the disliked one, and the page is asserted to be exactly pool[:17] minus it, 16 rows.
  - Keyless and bystander under pin16 both contain it.
- **Lean-away.** All three pages use pin16. Pages carrying a profile get 32 from the Engine and are served whole. `_pair` runs on the pinned keyless page and asserts cosine < 0.7, and the closeness and margin assertions are unchanged.

**R5, `test_blocks`.**

- **Surfaces test.** Parametrised over the three surfaces again, and it gains `engine`.
  - For up-next, the test resolves the seed from `SEARCH[0]` and pins pool[:8]. Every up-next request sends `{"exclude": pin}`, which means `_rows` gains an optional `body`.
  - The keyless page is asserted equal to the chosen set as a control. The targets come from it, and the existing absent/present assertions follow.
  - The retired comment goes, and the docstring regains its bullets.
- **Stays-full test.** Uses the same seed, so the cached pool is reused, and pins pool[:PAGE + 3] = 11 rows.
  - The keyless control is fetched at limit 11 so that it is served whole. It must equal those 11, and `blocked = keyless[:3]`.
  - The blocker asks for 8. The Client over-fetches 16 ≥ 11, so the Engine serves all 11 including the three blocked channels, and the Client drops them. The assertion is a full 8 with no blocked channel.
  - Each pool row is a distinct author, so exactly three rows go.

**R6, `test_frontend_blocks`.**

- The runner's `upnext` passes `JSON.parse(process.env.EXCLUDE || "[]")` as `fetchSimilarVideosPayload`'s second argument, which `videos.ts:136` accepts. `_run` gains `exclude=()` and exports it.
- `_seed_and_targets(client, engine)` pins `/recommendations` pool[:8]. It takes `in_upnext = chosen[0]` and a search row sharing no channel with `chosen`, and returns the pin.
- The restored test asserts both target channels are on the rows fetched before the block. After the block both fetches still return rows, without their blocked channel. The blocked profile's up-next is an over-fetch of 16 served whole as the 8 pinned rows, minus the target.
- The refused-key test only adapts to the new signature. The docstring bullet comes back.

**R7.** `test_blocks.py`, `test_dislikes.py` and `test_frontend_blocks.py` each gain `engine/server/api/handlers/similar.py` and `engine/server/data/similarity_candidates.py`. `test_dislike_profile.py` gains `engine/server/data/ann.py` and `engine/server/data/similarity_candidates.py`; it already lists `similar.py`.

**R8.** The six archive files move to `delete_me/`, where no file shares their names, and the empty `tests/archive/upnext_random_draw/` goes.

### Alternatives considered

- **Forwarding `seed` through the Client.** This would make the Client tests seedable, but it is a product change and out of scope.
- **Running the Client-side tests directly on the Engine with `seed`.** Rejected: it drops the gateway's filtering, over-fetch and centroid attachment, which are the point of R4-R6.
- **Statistical repetition**, with N draws and a proportion asserted. Rejected: it can still flake, it can still pass vacuously (the R5 probe saw 6 of 12 vacuous runs), and it does not fit 60 requests a minute.
- **Pinning R2 and R3 as well.** It would work, but R3 asks for a coupled seeded draw, and a seed costs 0 listing requests where a pin costs about 5-8 per seed. Using the seed there keeps the change smaller.
- **Using pool listing order for "first n".** Rejected for the reason given under R1: draw order can put a tail row first.
- **Choosing R3b's pair from `upnext_pool`'s head.** It would work, but it adds a listing to a file that otherwise needs none. The seeded 16-row page plus a coverage check meets the requirement more cheaply.
- **Caching pins as well as pools.** Not done: every file stays well within budget without it.
- **Sharing the `127.0.0.1` bucket for listing.** Rejected in favour of a dedicated `X-Client-IP`, an idiom the suite already uses, so that one test's listing cannot push a later test in the same file over 60.

### Risks and gotchas

- **Pool size against the exclude cap.** The pin needs the whole pool minus n excluded. A pool listing comes out at about 300 rows plus whatever the widened fallback adds that the first, narrower pass missed. If a seed's union ever passed 500, it could not be pinned at all. The helper fails deterministically and names the cause, and the remedy would be another seed, never a retry.
- **A head row displaced.** If wider fallback steps bring in a higher-scoring row by the same author, it can take a chosen head row's slot. The pin then raises a deterministic `AssertionError` naming the missing key. It does not flake, and sorting by score makes it unlikely.
- **Slower pinned requests.** A pinned pool of 8-17 rows is under `TARGET_MIN_POOL` (48), so every pinned request walks the fallback to the nprobe and search-limit caps. Each of these requests is noticeably slower than a plain page.
- **Rate budget per process.** Each live-Engine file runs in its own invocation, so it gets a fresh Engine and fresh buckets. Rough counts:
  - `test_dislikes` on each route: about 12 Client-driven requests on `127.0.0.1`, plus up to about 2 × (7 listing + 9 pin) on the helper bucket.
  - `test_dislike_profile`: about 38 on `127.0.0.1:/recommendations`.
  - `test_similar`: 6 more on their own bucket.
  - `test_blocks` and `test_frontend_blocks`: under 20 per bucket.
- **The pin is checked on the Engine, not on the Client's path.** It is checked directly on the Engine without `nsfw`, and the Client adds no `nsfw`. A Client that started adding a pool-affecting parameter would make the controls fail loudly, not silently.
- **Home pages in R3b.** If the plain home pages vary from run to run, the chosen pair can vary. The coverage control is checked on the same pages the assertions use, so the test cannot pass vacuously. If no covered pair exists, it fails visibly.
- **Pin size through the environment.** The R6 pin, about 290 entries, goes through an environment variable, which is well under Linux's per-variable limit.

### Tradeoffs the operator accepts

- **The pinned tests do not exercise the draw.** They prove filtering, refill and penalised order on a fixed set. Draw behaviour stays covered by the existing seeded-draw and diversity tests in `test_similar.py`.
- **"First n rows of the pool" means the head by `similarity_score`.** It does not mean the Engine's ranked order or a draw. The pinned page's own order is the ranked order, and targets such as `keyless[8]` are taken from that page.
- **The stays-full keyless control is fetched at limit 11, not 8.** This keeps it whole, so the control sees exactly the rows the blocker's over-fetch is served.
- **Pinned tests depend on the ANN fallback being deterministic.** A change to `similarity_candidates.py` or `ann.py` reselects them through R7, and it can make a pin fail with a named key rather than flake.
- **The listing bucket is a deliberate simplification.** One dedicated `X-Client-IP` per process, with no cross-process cache. Its ceiling is about 60 listing and pin requests a minute per route in one file. The way up is a per-module header or a pin cache, if a future file pins many seeds.

## Impacts

<impacts>
<impact path="tests/active/conftest.py" element="module docstring (lines 1-11)">
**What changes.** One line is added naming `exclude_entries`, `upnext_pool` and `pin_upnext` as plain helpers that pin an up-next page with `exclude`.

**What depends on it.** Nothing reads it.

**Risk: none.** Keep it to one line. The file has no softwrapped paragraphs beyond the existing ones.
</impact>
<impact path="tests/active/conftest.py" element="new module constants: the helper X-Client-IP header, the listing limit (96), the 500 exclude cap, the page budget ceil(500/96)+1, the pin retry count (3), the listing seed (0), the pool cache dict">
**What changes.** These are new module-level names placed after `BRIDGE_HEADERS` (line 194), each with a one-line comment.

**Choosing the header IP.** It must be a TEST-NET-1 address the suite does not use yet. These are taken: 192.0.2.1, .7, .10, .109, .140, .141 and .172-.175, in `test_similar.py:640-642,1024-1026` and `test_server.py:254-259,1161`. The NSFW test uses 198.18.x.x. Any other 192.0.2.x is free, for example 192.0.2.150.

**Where 96 and 500 come from.** 96 is `default_limit * 2` (`similar.py:1011`), and BATCH_SIZE=48 (`server_config.py:328`). 500 is `DEFAULT_CLIENT_EXCLUDE_MAX` (`server_config.py:470`) on the Engine and `MAX_FEED_EXCLUDE` (`client/backend/server.py:59`) on the Client. `test_similar.py:134` already holds its own `EXCLUDE_CAP = 500`, a hand-rolled duplicate. It is not shared.

**What depends on it.** `upnext_pool` and `pin_upnext`.

**Risk: low.** If the IP collides with a bucket a test already uses, both share a 60/min `ip:path` budget (`similar.py:604-611`). The pool cache lives in the `conftest` module. There is no `pytest.ini`, `pyproject.toml` or `__init__.py` under `tests/`, so pytest's default prepend import registers the module as `conftest` in `sys.modules`, and `from conftest import ...` in test files gets the same module object and the same cache. This is unverified at runtime.
</impact>
<impact path="tests/active/conftest.py" element="new exclude_entries(rows)">
**What changes.** A new helper maps rows to `{"id": video_id, "host": instance_domain}`. The Engine reads these as `video_id::instance_domain` keys (`similar.py:183-199`), which is the `like_key` form (`engine/server/api/recommendations/keys.py:8-16`).

**What depends on it.**
- `pin_upnext`, `upnext_pool`, and the R4, R5 and R6 tests.
- It duplicates the shape of `test_similar.py:1066-1067` `_exclude(keys)`, which takes key tuples rather than rows. R2 may use either. Keep `_exclude`, since the ordered-mode test uses it.

**Risk: low.** If an entry used `video_uuid` instead of `video_id`, it would silently exclude nothing. The pin's own check would then fail loudly.
</impact>
<impact path="tests/active/conftest.py" element="new upnext_pool(engine, route, seed)">
**What changes.** A new helper lists a seed's up-next pool on the Engine with seeded POSTs: `{route}?id=&host=&limit=96&seed=0&debug=1`, each excluding everything listed so far, stopping at the first empty page. It returns the rows sorted by `debug.similarity_score` descending, ties broken by key, and caches them per `(route, video_uuid, instance_domain)`.

**Engine facts it relies on, all read.**
- `get_upnext_candidates` (`engine/server/data/similarity_candidates.py:130-192`) cuts to `top_k` inside `_build_rows` (line 205) and only then drops excluded keys (207-208). An excluded row therefore keeps its slot and its author slot, and the listing ends once the widest pool's top 300 are all excluded.
- The fallback (162-188) runs whenever the filtered pool is under `target_min_pool` (48) or the cache missed. It widens nprobe 32→128 and search_limit 5000→20000.
- `seed=0` is valid: `_parse_non_negative_int` (`similar.py:1163-1171`) accepts 0.
- `debug=1` needs `RECOMMENDATIONS_DEBUG=1`, which the `engine` fixture sets (`conftest.py:110`).
- `debug.similarity_score` comes from `attach_debug_info` (`engine/server/api/recommendations/debug.py:18`). `score_candidate` sets it (`scoring.py:61`) from `_extract_similarity`, which falls back to the pool's ANN or cache `score`.

**Evidence that the listing terminates.** `test_frontend_upnext_pager.py:69` saw the linux pool, through the Client, come back as 48 × 6, then 12, then empty. That is about 300 rows, so about 4 pages of 96 plus an empty one, within the ceil(500/96)+1 = 7 budget.

**What depends on it.** `pin_upnext`, and R4, R5 and R6 for the depth control and for choosing `pool[:n]`.

**Risk: medium.**
- The pool's union across widenings can pass 300. The plan's own risk is that it passes 500, and the helper must then raise, never truncate.
- Sorting by `similarity_score` and not by the Engine's ranked `score`, which adds freshness and popularity (`server_config.py:223-228`), is deliberate. Targets come from the pinned page's own order, not from `pool[i]`.
- The listing runs without `nsfw`, so it is filtered (`similar.py:1050`), which matches what the Client and the frontend send. `nsfwQuery()` (`client/frontend/src/data/feed-params.ts:100-102`) adds `nsfw=1` only when the filter is off, and the node runner's empty localStorage leaves it on.
- Pool membership also passes `apply_serving_moderation_filters` (`similarity_candidates.py:209`) and reads the shared `similarity-cache.db`. These are stable within a process but can differ between runs, so a pool must never be cached across processes, and the plan does not.
</impact>
<impact path="tests/active/conftest.py" element="new pin_upnext(engine, route, seed, chosen)">
**What changes.** A new helper returns the exclude entries (pool minus chosen) under which a seeded `limit=96` request is served exactly `chosen`'s key set. It widens by any extra rows at most 3 times, checks the 500 cap before each send, and raises `AssertionError` naming the missing and extra keys.

**Why a pinned page is served whole.**
- The window is `rows[:min(4 * limit, len(rows))]` (`similar.py:898`), and `_draw_page` returns it whole when `len(window) <= limit` (`similar.py:1194-1195`).
- Ranking of up-next is deterministic. `rank_scored_candidates` (`scoring.py:70-148`) uses `config.get("explore")`'s ratio and `jitter_window`, and the `upnext` profile (`server_config.py:221-285`) has neither key at top level. `_apply_jitter` is therefore a no-op and the order is a stable sort by penalised `score`.
- `score` includes freshness against `now_ms()`, so the order is stable within a test but not guaranteed across days.
- With likes, `rerank_related_videos` reorders the window (`similar.py:900-918`) but cannot change its membership. The R4, R5 and R6 profiles hold no likes. The Client samples likes randomly (`client/backend/server.py:560-563`), so a pinned profile with likes would get a non-deterministic order.

**What depends on it.**
- R4: pin16 and pin17 per (route, seed). These are not cached, so the lean-away test recomputes pin16.
- R5: pool[:8] and pool[:11] on both routes.
- R6: pool[:8] on `/recommendations`.

**Risk: high.** This is the foundation of every Client-side restored test.
- Each check request walks the fallback to its caps, because the pinned pool is under 48, so each is slow.
- Another same-author row can displace a head row once the pool widens, since `DEFAULT_SIMILARITY_MAX_PER_AUTHOR = 1` (`server_config.py:388`). The pin then fails with a named key, deterministically.
- The pin is verified on the Engine directly. The Client path adds `dislike_centroids` and, for profiles, `likes`. Neither changes membership, because `UpnextPoolPolicy` (`similarity_candidates.py:114-127`) takes neither.
</impact>
<impact path="tests/active/test_similar.py" element="module docstring; new UPNEXT_SEED_QUERIES and a new header constant beside DRAW_HEADERS (line 640); new test (R2) using _upnext_path (222-226), _config (696-700) and _keys (739-740)">
**What changes.**
- A bullet is added under "Up-next's sampled page" (around lines 63-69).
- `UPNEXT_SEED_QUERIES = ("linux", "cooking")` is new. Note that `SHORT_SEED_QUERIES` (line 596) already holds the same tuple. Reuse it or keep both deliberately.
- A new `*_HEADERS = {"X-Client-IP": "192.0.2.x"}` must differ from conftest's helper IP and from those already in the file.
- Per seed the test sends one reference POST at `_upnext_path(...) + "&debug=1&seed=N"`, then two with the same seed excluding the whole reference page and every other row of it. It asserts 8 rows, none excluded, and each `similarity_score >= SIMILAR_VIDEO_TAIL_MIN_SCORE - 1e-6`.

**What depends on it.**
- `_upnext_path` sends its search on 127.0.0.1's `/api/v1/search/videos` bucket with no header. The file already makes about 17 search calls there, so this adds 2.
- The session-wide `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default` (957-986) reads every `upnext_pool` line in the session log. The new requests add lines and must satisfy that test's invariants. They do, since any up-next request logs its own steps.
- The `upnext_pool` log-line strings and regex `POOL_LINE` (646) share the name with the new conftest helper. These are strings only, with no symbol clash, but grep results get noisier.

**Risk: low.**
- An exclude of 4 or 8 rows leaves the pool far above 48. These requests usually do not even run the fallback beyond the cache-miss path, so they are fast.
- The 8-row guarantee holds because the pool is about 300.
</impact>
<impact path="tests/active/test_dislike_profile.py" element="module docstring, imports (line 10), new constants SEED_QUERIES/HOME_DRAWS/UPNEXT_LEADING/CLEARLY_SIMILAR/DRAW_SEED, restored helpers _space/_seed_and_pair/_centroid_body/_others/_margin/_position, two restored tests (from tests/archive/upnext_random_draw/test_dislike_profile.py)">
**What changes.**
- The import gains `closeness` (and `pytest` is already imported). The archive file used `closeness` without importing it.
- `_seed_and_pair`'s path gains `&seed=DRAW_SEED` at limit 16.
- (a) The plain page and both centroid pages share the seed.
- (b) Plain home pages are fetched first. Covered candidates are those from the seeded 16-row page with a cosine ≥ 0.6 row (other than themselves) on every plain page. The least-similar covered pair with cosine < 0.7 is taken, its coverage with both left out is asserted, and only then are the 10 shaped pages fetched.
- The docstring regains the two bullets in "same draw" wording.

**What depends on it.**
- Engine `_parse_dislike_centroids` (`similar.py:202+`) through the `dislike_centroids` body with `space` = `video_embeddings.model_name`.
- `apply_dislike_penalty` inside `score_and_rank_list` (`similar.py:869-881`).
- The seeded draw `_seeded_uniform` (1180-1183) keys on `like_key`, so a row keeps its uniform across the plain and centroid pages.
- Window membership itself, the top 4×16=64 by penalised score, can shift under the penalty. That is the intended effect.

**Rate.** About 38 requests on `127.0.0.1:/recommendations`, plus 4 searches. The existing centroid test uses `/internal/dislikes/centroids`, which is not rate-limited on that path.

**Risk: medium.**
- (b) depends on unseeded home pages. Home pages for one like were observed identical (archive docstring), but no code guarantees it.
- A cooking seed with no covered pair at cosine < 0.7 fails visibly. It does not flake silently.
- (a) is a characterization of a coupled draw, not a pin, so the closeness inequality is still a statistical property of one fixed seed. It is deterministic per seed and dataset.
</impact>
<impact path="tests/active/test_dislikes.py" element="module docstring, imports, new constants SEEDS/ROUTES/PAGE/LEADING, restored _seed/_upnext(+body)/_profile_disliking/_pair/_leading_others/_margin, two restored tests gaining `engine` and `dataset`">
**What changes.**
- Imports gain `pytest`, `urllib.parse.quote`, and from conftest `closeness`, `cosine`, `embedding_of`, `upnext_pool`, `pin_upnext` and `exclude_entries`. Today the file imports only `urlencode` (line 13), and the archive relied on `_mint` (line 30 here).
- `_upnext` gains a `body` argument carrying `{"exclude": pin}`.
- The absent/present test uses pin16 for keyless and bystander, and pin17 for the disliking profile at limit 16. Its control is that the keyless key set equals pool[:16]; `disliked = keyless[8]`.
- The lean-away test uses pin16 for all three pages.
- The closing docstring paragraph ("Every test runs the Client in `unpublished_client` mode…", lines 8-9) stays.

**What depends on it.**
- The Client gateway caps `limit` to 48 (`server.py:459`) and doubles it only when blocks or dislikes exist (473-474), giving 16→32.
- `_filter_payload` drops disliked rows, then cuts to page_size (1096-1122).
- The profile's centroids are attached (564-566).
- `exclude` is sanitised and capped at 500 (526-537).
- `seed` is not on `PROXY_ALLOWED_QUERY_PARAMS` (88-90), so Client requests cannot be seeded.

**Rate.** The Client forwards `x-client-ip` = 127.0.0.1 (599), so there are 7 Client requests per (route, seed) on `127.0.0.1:{route}`, 14 per route. The helper bucket takes up to 2 listings × about 5, plus 3 pins × up to 4 × 2 seeds, about 34 per route.

**Risk: high.**
- Every pinned Client request runs the fallback to its caps under the Client's `ENGINE_PROXY_TIMEOUT_SECONDS = 10` with `ENGINE_PROXY_RETRY_COUNT = 1` (`server.py:77-82,613-615`). A slow Engine under 10 parallel validator lanes (`validate_tests.py:347`) could time out, retry (double-counting the bucket) and answer 502/504.
- `test_frontend_upnext_pager` already passes requests of this kind through the same timeout, which is evidence against, not proof.
- The seed queries "linux" and "football" are no longer chosen for a 19/18-row pool. The archive comment at line 25 is stale and must not be copied.
</impact>
<impact path="tests/active/test_blocks.py" element="module docstring (lines 1-9), _rows (48-52) gaining optional body, the retired comment (139), test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page (140-168) reparametrised and gaining `engine`, restored test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it (+ _upnext path helper)">
**What changes.**
- `_rows(client, method, path, key=None, body=None)` sends `body` (default `{}` for POST). Every existing caller passes 4 positional arguments or fewer, so all stay valid.
- The surfaces test is parametrised over `/recommendations`, `/videos/similar` and `search`.
  - For up-next, the seed is `_rows(client, "GET", SEARCH)[0]` and the pin is pool[:8].
  - The control is keyless key set == chosen.
  - `blocked_account = _distinct(keyless, blocked_channel)` and `unrelated = _distinct(reversed...)` must still find rows. Each pool row is a distinct channel (`DEFAULT_SIMILARITY_MAX_PER_AUTHOR = 1`, `server_config.py:388`, keyed by channel and instance in `similarity_candidates.py:503`), but two channels can share an `account_url`. `_distinct` then raises `StopIteration`, a loud and unlikely failure.
- The stays-full test pins pool[:11]. The keyless control at limit 11 equals those rows, `blocked = keyless[:3]`, and the blocker at limit 8 gets a Client over-fetch of 16, which is ≥ 11.
- The new archive-free docstring bullets come back.
- Line 139's comment, which points at the archive path that R8 deletes, goes.

**What depends on it.**
- The search case stays unchanged (`SEARCH` with no pin).
- The 1,000-blocks test is unrelated.

**Risk: medium.** As for R4, slow pinned Client requests run under the 10 s proxy timeout. Blocking accounts also removes any other pinned row whose account matches. The assertions only check absence and non-emptiness, so this is safe.
</impact>
<impact path="tests/active/test_frontend_blocks.py" element="docstring (1-8), RUNNER's upnext (37-38), _run (72-80) gaining exclude=(), _seed_and_targets (89-97) gaining `engine` and returning the pin, the restored module-block test, and the refused-key test (100-111)">
**What changes.**
- The runner's `upnext` becomes `m.fetchSimilarVideosPayload({...}, JSON.parse(process.env.EXCLUDE || "[]"))`. This matches `client/frontend/src/data/videos.ts:136` `(query, exclude = [], feedParams?)`, which sets `body.exclude` only when it is non-empty (140).
- `_run` exports `EXCLUDE=json.dumps(list(exclude))`.
- `_seed_and_targets(client, engine)` searches `/api/v1/search/videos?q=music` and pins `/recommendations` pool[:8]. It returns the seed, `chosen[0]`, a search row on no chosen channel, and the pin.
- The refused-key test only adapts its call, and gains `engine`. That makes it list the pool as well (cached across both tests in the process).
- The docstring bullet is restored from `tests/archive/upnext_random_draw/test_frontend_blocks.py:7-10`.

**What depends on it.**
- esbuild bundling (`check=True`).
- `nsfwQuery()` leaves `nsfw` unset with the default filter on, which matches the pin.
- With a key, `fetchSimilarVideosPayload` sends `{}` rather than random likes (139), and the created profile has no likes, so the order is deterministic.

**Risk: medium.**
- About 290 entries × about 80 bytes is about 23 KB in one environment variable, well under Linux `MAX_ARG_STRLEN` (128 KiB).
- The refused-key test now depends on listing succeeding, so a listing failure turns an unrelated key test red.
- The runner's `window` stub lacks `sessionStorage`, unlike the pager test. That is harmless as it stands.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups entries test_blocks.py (75-80), test_dislikes.py (35-41), test_frontend_blocks.py (81-87), test_dislike_profile.py (26-34)">
**What changes.**
- R7 adds `engine/server/api/handlers/similar.py` and `engine/server/data/similarity_candidates.py` to the three Client-side groups.
- It adds `engine/server/data/ann.py` and `engine/server/data/similarity_candidates.py` to `test_dislike_profile.py`, which already has `similar.py`.

**What depends on it.** `validate_tests.py` `claimed()` (616-648) digests only a group's own file plus its mapped files.

**Gaps against what the pins actually depend on (uncertain; flag to the operator).**
- `engine/server/api/server_config.py`: the upnext profile with no explore or jitter, `DEFAULT_SIMILARITY_MAX_PER_AUTHOR`, `SIMILAR_VIDEO_*`, and the caps.
- `engine/server/api/recommendations/scoring.py`: `_apply_jitter` and the explore mix.
- `engine/server/data/ann.py` for the three Client groups.
- `client/frontend/src/data/feed-params.ts` (`nsfwQuery`) for `test_frontend_blocks.py`.
- `test_dislikes.py` and `test_blocks.py` already carry `client/backend/server.py`.

**Risk: low.** Invalid JSON breaks the validator for every group, so keep the file's 2-space indent.
</impact>
<impact path=".un/skills/devsecops/scripts/validate_tests.py" element="claimed() (616-648) and proposable() (1675-1703): conftest.py is never fingerprinted">
**What changes.** Nothing.

**Why it matters.** The requirements' acceptance line ("A `conftest.py` change reselects broadly") does not hold. Editing `tests/active/conftest.py` invalidates no group. The four edited test files are reselected by their own digests, but other groups importing conftest (`test_similar`, `test_server`, `test_random_cache` and others) are not rerun because of the conftest edit. `test_similar.py` is reselected anyway because its own file changes.

**What depends on it.** The Step 8 validation run.

**Risk: medium.** A conftest edit that broke an unrelated importer, such as a name collision or an import-time error, would go unseen until something else reselected that group. Either run the full suite explicitly or accept the risk.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_draw_page (1186-1210), window (898), limit cap (1007-1013), seed parse (1034), exclude cap/parse (640-647, 183-199, 666), rate limit (604-611)">
**What changes.** Nothing; there is no product change.

**What depends on it.** Every pin and the R2 and R3 seeded draws.

**Risk: n/a for this build.** A later change to the whole-window short-circuit, the window factor or the limit cap breaks every pin. With R7 such a change reselects the pinned groups.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="get_upnext_candidates (130-192), _upnext_rows (195-210), author cap in _build_rows (440-463)">
**What changes.** Nothing.

**What depends on it.** Pool membership, the top_k-before-exclude order, and one row per author. The stays-full test's "exactly three rows go" and the listing's termination rest on these.

**Risk: n/a for this build.** It is mapped through R7.
</impact>
<impact path="engine/server/data/ann.py" element="search_similar_above (88+), index_lock">
**What changes.** Nothing.

**What depends on it.** The fallback is deterministic for a given exclude. FAISS IVF search at a fixed nprobe is deterministic, and nprobe is set and restored under `index_lock`. The pin's reproducibility depends on this.

**Risk: n/a.** It is mapped for `test_dislike_profile` by R7, but not for the three Client-side groups (see the config.json entry).
</impact>
<impact path="engine/server/api/server_config.py" element="upnext profile (221-285), DEFAULT_SIMILARITY_MAX_PER_AUTHOR (388), SIMILAR_VIDEO_* (394-409), DEFAULT_CLIENT_EXCLUDE_MAX (470), DEFAULT_CLIENT_LIKES_BODY_LIMIT (474), rate limit (482-483)">
**What changes.** Nothing.

**What depends on it.**
- A 500-entry exclude body is about 40 KB, under the Engine's 131072-byte body limit.
- A deterministic pinned order needs the upnext profile to have no `explore.ratio` or `jitter_window`.
- The stays-full arithmetic needs an author cap of 1.

**Risk: n/a for this build.** It is not mapped to the pinned groups, which is a gap.
</impact>
<impact path="engine/server/api/recommendations/scoring.py" element="rank_scored_candidates (70-148), _apply_jitter (228-239)">
**What changes.** Nothing.

**What depends on it.** The assumption that a pinned page's order is the ranked, penalised order, which the R4 lean-away leading-8 and `keyless[8]` use. `random.shuffle` would make that order random if a jitter window were ever configured for upnext.

**Risk: n/a for this build.** It is not mapped to the R4, R5 or R6 groups.
</impact>
<impact path="client/backend/server.py" element="_profile_filter (444-475), _handle_engine_read_proxy_post (477-574), _proxy_engine_request timeout/retry (586-615), _filter_payload (1096-1122)">
**What changes.** Nothing.

**What depends on it.** The R4, R5 and R6 over-fetch arithmetic:
- page_size = min(limit, 48), with ×2 only when blocks or dislikes exist;
- dislikes are dropped on feed routes only;
- pages are cut to page_size;
- 500 exclude entries are passed through;
- the profile's own likes and centroids replace the browser's;
- the timeout is 10 s with 1 retry.

**Risk: medium (runtime).** See the timeout risk under test_dislikes. Any future Client change that adds a pool-affecting query such as `nsfw` makes the pinned controls fail loudly.
</impact>
<impact path="client/frontend/src/data/videos.ts" element="fetchSimilarVideosPayload (136-163)">
**What changes.** Nothing. R6 newly uses its `exclude` argument.

**What depends on it.** The R6 runner.

**Risk: low.** It is already mapped to `test_frontend_blocks.py`.
</impact>
<impact path="client/frontend/src/data/feed-params.ts" element="nsfwQuery (100-102)">
**What changes.** Nothing.

**What depends on it.** The R6 pin, which is checked on the Engine without `nsfw`, matches only while the runner's default filter leaves `nsfw` off.

**Risk: low.** It is not mapped to `test_frontend_blocks.py`.
</impact>
<impact path="tests/active/test_frontend_upnext_pager.py" element="docstring line 7 (`Replaces tests/archive/upnext_random_draw/test_frontend_videos.py (issue 35)`)">
**What changes.** Nothing in the plan. After R8 this path no longer exists, so the reference dangles. Optionally repoint it to `delete_me/test_frontend_videos.py`, or drop the path and keep "(issue 35)".

**What depends on it.** Nothing executable.

**Risk: none.** This is a stale reference only.
</impact>
<impact path="tests/archive/upnext_random_draw/test_similar.py" element="whole file → delete_me/test_similar.py">
**What changes.** The file is moved (R8). `delete_me/` holds no file of this name: it contains only `test_19_*`, probes, `*.bak*` and `audit_map_19.txt`.

**What depends on it.** Nothing imports it. The validator collects only `tests/active` (`validate_tests.py:604-613`).

**Risk: low.** A bare `pytest` from the repo root would collect it under `delete_me/`. It is skip-marked at module level and imports only `pytest`, so collection succeeds and it skips.
</impact>
<impact path="tests/archive/upnext_random_draw/test_dislike_profile.py" element="whole file → delete_me/test_dislike_profile.py">
**What changes.** The file is moved (R8). It is the source of the helpers restored in R3, so copy them before the move.

**What depends on it.** Nothing.

**Risk: low.** It imports only `quote` and `pytest` at module level and is skip-marked.
</impact>
<impact path="tests/archive/upnext_random_draw/test_dislikes.py" element="whole file → delete_me/test_dislikes.py">
**What changes.** The file is moved (R8). It is the source of the helpers restored in R4.

**What depends on it.** Nothing.

**Risk: low.** It is skip-marked.
</impact>
<impact path="tests/archive/upnext_random_draw/test_blocks.py" element="whole file → delete_me/test_blocks.py">
**What changes.** The file is moved (R8). It is the source of R5's `_upnext`, `_surface` and stays-full body. `_deep_seed` is not restored, because the pin replaces it.

**What depends on it.** `tests/active/test_blocks.py:139`'s comment, which R5 removes.

**Risk: low.**
</impact>
<impact path="tests/archive/upnext_random_draw/test_frontend_blocks.py" element="whole file → delete_me/test_frontend_blocks.py">
**What changes.** The file is moved (R8). It is the source of R6's test body.

**What depends on it.** Nothing.

**Risk: low.**
</impact>
<impact path="tests/archive/upnext_random_draw/test_frontend_videos.py" element="whole file → delete_me/test_frontend_videos.py">
**What changes.** The file is moved (R8). It is already replaced by `test_frontend_upnext_pager.py`.

**What depends on it.** The docstring reference in `test_frontend_upnext_pager.py:7`, and historical plan and issue text.

**Risk: low.** Its `FRONTEND = parents[3]` resolves differently under `delete_me/` (one level shallower), but it is skip-marked and that line only builds a Path.
</impact>
<impact path="tests/archive/upnext_random_draw/" element="the directory itself">
**What changes.** It is removed once empty. Only the six `.py` files are there now; Glob shows no `__pycache__`, but check before removing.

**What depends on it.** Path references in history:
- `docs/project/issues/plan.md:68`;
- `docs/project/issues/35-…md:8`;
- archived issues 09 and 12;
- archived plans 19-09, 19-12 and 19-22.

**Risk: none.** Only the live docs below need an update.
</impact>
</impacts>

## Documentation to update

- [x] `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` - updated: I added a delivery comment to issue 35 under `## Comments`. The Status line and the move to the archive are left for harvest.
- [x] `docs/project/issues/plan.md` - updated: I rewrote the note in row 2a (lane 09, similars diversity) so it says build 35 replaced the up-next tests. The archive path and the line about an open issue are gone.
- [x] `tests/active/test_frontend_upnext_pager.py` - updated: Removed the "Replaces …" sentence from the module docstring, because the archive path it named no longer exists.
- [x] `docs/project/issues/41-short-similarity-cache-tests.md` - updated: I wrote the new issue `docs/project/issues/41-short-similarity-cache-tests.md`. It tracks the five tests retired to `tests/archive/short_similarity_cache/test_similar.py`.
- [x] `tests/active/conftest.py` - out of scope: Phase 1 already added the module-docstring line describing `exclude_entries`, `upnext_pool` and `pin_upnext`. Each new constant has its own comment, and `UPNEXT_PIN_HEADERS` has a `rat-tail:` note. It is accurate to what was delivered.
- [x] `tests/active/test_similar.py` - out of scope: Phase 1 added the exclude bullet (line 48) under "Up-next's sampled page", and it matches the delivered test. The docstring describes no retired test.
- [x] `tests/active/test_dislike_profile.py` - out of scope: Phase 2 restored the up-next and home centroid bullets in "same seeded draw" wording, with coverage-chosen pairs and mean comparisons. They describe the delivered tests.
- [x] `tests/active/test_dislikes.py` - out of scope: Phase 2 restored the docstring: the first line, the two up-next bullets and the line about the `pin_upnext` pin. The stale "19 and 18 rows" comment was not copied.
- [x] `tests/active/test_blocks.py` - out of scope: Phase 3 restored the up-next bullets and the `pin_upnext` line, and removed the comment that pointed at the archive path.
- [x] `tests/active/test_frontend_blocks.py` - out of scope: Phase 3 restored the module-block bullet and added a line on the `EXCLUDE` pin. Both match the delivered runner and test.
- [x] `.un/skills/devsecops/config.json` - out of scope: This is configuration, not prose, and Phase 4 already added the R7 mappings. The inventory flagged that `server_config.py`, `scoring.py`, `ann.py` (for the Client groups) and `feed-params.ts` are not mapped. Those are selector-coverage gaps for the operator to decide on. No document claims they are mapped.
- [x] `.un/skills/devsecops/scripts/validate_tests.py` - out of scope: Not changed and not documentation. The inventory found that a conftest edit does not reselect the groups that import it. That contradicts the requirements' acceptance line, not any document. The build ran the full suite instead.
- [x] `engine/server/api/handlers/similar.py` - out of scope: The build changed no product code. Its comments on `_draw_page`, the window, the seed and exclude are unchanged and still true.
- [x] `engine/server/data/similarity_candidates.py` - out of scope: No product code changed, so the pool, top_k-before-exclude and author-cap behaviour its comments describe is unchanged.
- [x] `engine/server/data/ann.py` - out of scope: No product code changed.
- [x] `engine/server/api/server_config.py` - out of scope: No product code or constants changed.
- [x] `engine/server/api/recommendations/scoring.py` - out of scope: No product code changed.
- [x] `client/backend/server.py` - out of scope: No product code changed. The over-fetch, the exclude cap and the `seed` refusal are as documented.
- [x] `client/frontend/src/data/videos.ts` - out of scope: No change. R6 only calls the existing `exclude` argument of `fetchSimilarVideosPayload`.
- [x] `client/frontend/src/data/feed-params.ts` - out of scope: No change, and nothing the build relies on contradicts what it says about `nsfwQuery`.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - out of scope: It describes the Engine's up-next parameters and fallback. This build changed no Engine behaviour or constants, so nothing in it has become false.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - out of scope: It describes the up-next pipeline and fallback steps, which are unchanged. A test-only build does not affect it.
- [x] `tests/archive/upnext_random_draw/test_similar.py` - out of scope: Moved unchanged to `delete_me/` (R8). The byte-identical move is what Phase 4's checkpoint checks, and nothing reads the file as documentation.
- [x] `tests/archive/upnext_random_draw/test_dislike_profile.py` - out of scope: Moved unchanged to `delete_me/` (R8), and must stay byte-identical. It is a reference copy marked for deletion.
- [x] `tests/archive/upnext_random_draw/test_dislikes.py` - out of scope: Moved unchanged to `delete_me/` (R8), and must stay byte-identical. It is a reference copy marked for deletion.
- [x] `tests/archive/upnext_random_draw/test_blocks.py` - out of scope: Moved unchanged to `delete_me/` (R8). The only live reference to it was the `tests/active/test_blocks.py` comment, which Phase 3 removed.
- [x] `tests/archive/upnext_random_draw/test_frontend_blocks.py` - out of scope: Moved unchanged to `delete_me/` (R8), and must stay byte-identical. It is a reference copy marked for deletion.
- [x] `tests/archive/upnext_random_draw/test_frontend_videos.py` - out of scope: Moved unchanged to `delete_me/` (R8). The dangling reference to it in `test_frontend_upnext_pager.py` is listed above as its own entry.
- [x] `tests/archive/upnext_random_draw/` - out of scope: The directory is gone. The live document that named it is `docs/project/issues/plan.md` row 2a, covered above, and issue 35's own Problem text is covered by its delivery comment. Archived issues 09 and 12 and plans 19-09, 19-12 and 19-22 are historical records of their own builds, so they are left as written.

## Implementation plan

## Draft implementation: restore the up-next tests that the random draw retired (issue 35)

Before drafting I read every file this draft touches, plus `similar.py` (`_draw_page` 1186-1210, window 898, limit cap 1007-1013, exclude parse 183-199 and cap 640-647, rate key 604-611), `similarity_candidates.py` 130-210, `client/backend/server.py` 444-574 and `videos.ts` 136-163. The plan's foundation holds as written. `_upnext_rows` cuts to `top_k` before it drops `exclude`. `_draw_page` returns `list(window)` when `len(window) <= limit`. `_parse_excluded_keys` accepts an empty list. The Client sets `limit = min(limit, 48)` and doubles it only when the profile has blocks or dislikes (473-474).

I checked the draft against the plan and R1-R8 twice. The second pass changed one thing, R3b's pair choice (see "Decisions"). Nothing is left open that changes what the build is for.

### Module map

| File | Change |
|---|---|
| `tests/active/conftest.py` | +1 docstring line, +7 constants, +`exclude_entries`, `_upnext_key`, `_upnext_page`, `upnext_pool`, `pin_upnext` |
| `tests/active/test_similar.py` | +1 docstring bullet, +3 constants beside `DRAW_HEADERS`, +1 test (R2) |
| `tests/active/test_dislike_profile.py` | docstring, imports, constants, restored helpers + `_similar_ids`/`_covered_pair`, 2 restored tests (R3) |
| `tests/active/test_dislikes.py` | docstring, imports, constants, restored helpers, 2 restored tests (R4) |
| `tests/active/test_blocks.py` | docstring, import, `_rows(+body)`, `_key_set`, `_upnext`, `_surface`, reparametrised surfaces test, restored stays-full test, retired comment removed (R5) |
| `tests/active/test_frontend_blocks.py` | docstring, RUNNER `upnext`, `_run(+exclude)`, `_seed_and_targets(+engine, returns pin)`, restored module-block test, refused-key test adapted (R6) |
| `.un/skills/devsecops/config.json` | R7 mappings |
| `tests/archive/upnext_random_draw/*` | six files `git mv` to `delete_me/`, directory removed (R8) |
| `docs/project/issues/35-…md` | delivery comment |

---

### 1. `tests/active/conftest.py` (R1)

**Docstring.** Append one line after line 10 (blank line before it):

```
`exclude_entries`, `upnext_pool` and `pin_upnext` are plain helpers that pin an up-next page to a fixed set of its seed's pool with `exclude`, so it is served whole, not drawn.
```

**Constants**, after `BRIDGE_HEADERS` (line 194):

```python
# The pinning helpers' own Engine rate bucket: a TEST-NET-1 address no test uses, so listing never spends a test's 127.0.0.1 budget.
UPNEXT_PIN_HEADERS = {"X-Client-IP": "192.0.2.150"}
# The Engine's limit cap, default_limit * 2 (similar.py `_handle_similar`).
UPNEXT_LIST_LIMIT = 96
# DEFAULT_CLIENT_EXCLUDE_MAX on the Engine, MAX_FEED_EXCLUDE on the Client.
UPNEXT_EXCLUDE_CAP = 500
# Enough 96-row pages to list 500 rows, plus the empty page that ends a listing.
UPNEXT_LIST_PAGES = -(-UPNEXT_EXCLUDE_CAP // UPNEXT_LIST_LIMIT) + 1
UPNEXT_PIN_TRIES = 3
# Seeded, so the rows each excluding step serves do not depend on a fresh draw.
UPNEXT_LIST_SEED = 0
# One listing per (route, seed video) per pytest process; never kept across processes.
_UPNEXT_POOLS: dict[tuple[str, str, str], list[dict]] = {}
```

`UPNEXT_LIST_PAGES` evaluates to 7.

**Helpers**, after `identity_of`:

```python
def exclude_entries(rows) -> list[dict[str, str]]:
    """The `exclude` body entries naming these rows."""
    return [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows]


def _upnext_key(row: dict) -> tuple[str, str]:
    return (row["video_id"], row["instance_domain"])


def _upnext_page(engine, route: str, seed: dict, exclude: list[dict[str, str]]) -> list[dict]:
    """One seeded, debug, 96-row up-next page on the Engine, on the helpers' own rate bucket."""
    path = (f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}"
            f"&limit={UPNEXT_LIST_LIMIT}&seed={UPNEXT_LIST_SEED}&debug=1")
    status, body = engine.request("POST", path, headers=UPNEXT_PIN_HEADERS, body={"exclude": exclude})
    assert status == 200, (route, status, body)
    return body["rows"]


def upnext_pool(engine, route: str, seed: dict) -> list[dict]:
    """Every row of a seed's up-next pool on `route`, head first by debug similarity_score; listed once per process, not to be mutated."""
    cache_key = (route, seed["video_uuid"], seed["instance_domain"])
    if cache_key in _UPNEXT_POOLS:
        return _UPNEXT_POOLS[cache_key]
    listed: dict[tuple[str, str], dict] = {}
    for _ in range(UPNEXT_LIST_PAGES):
        assert len(listed) <= UPNEXT_EXCLUDE_CAP, f"{route} pool of {cache_key[1:]} at seed={UPNEXT_LIST_SEED}: {len(listed)} rows listed, past the {UPNEXT_EXCLUDE_CAP}-entry exclude cap"
        page = _upnext_page(engine, route, seed, exclude_entries(listed.values()))
        if not page:
            break
        listed.update((_upnext_key(r), r) for r in page)
    else:
        raise AssertionError(f"{route} pool of {cache_key[1:]} at seed={UPNEXT_LIST_SEED}: no empty page within {UPNEXT_LIST_PAGES} pages, {len(listed)} rows listed")
    # Head first: a draw can put a tail row first, and a tail row may not survive the wider fallback a narrow pin runs.
    pool = sorted(listed.values(), key=lambda r: (-r["debug"]["similarity_score"], _upnext_key(r)))
    _UPNEXT_POOLS[cache_key] = pool
    return pool


def pin_upnext(engine, route: str, seed: dict, chosen: list[dict]) -> list[dict[str, str]]:
    """The `exclude` entries under which an up-next request at limit >= len(chosen) is served exactly `chosen`, checked on the Engine."""
    want = {_upnext_key(r) for r in chosen}
    excluded = [r for r in upnext_pool(engine, route, seed) if _upnext_key(r) not in want]
    extra: set[tuple[str, str]] = set()
    for _ in range(UPNEXT_PIN_TRIES + 1):
        assert len(excluded) <= UPNEXT_EXCLUDE_CAP, f"{route} pin of {seed['video_uuid']}: {len(excluded)} exclude entries, past the {UPNEXT_EXCLUDE_CAP}-entry cap"
        served = {_upnext_key(r): r for r in _upnext_page(engine, route, seed, exclude_entries(excluded))}
        missing, extra = want - served.keys(), served.keys() - want
        assert not missing, f"{route} pin of {seed['video_uuid']}: chosen rows not served {sorted(missing)}, extra rows served {sorted(extra)}"
        if not extra:
            return exclude_entries(excluded)
        # A narrower pool runs the fallback further and can surface rows the listing never reached.
        excluded += [served[k] for k in sorted(extra)]
    raise AssertionError(f"{route} pin of {seed['video_uuid']}: extra rows still served after {UPNEXT_PIN_TRIES} widenings {sorted(extra)}")
```

**Invariants**

- A pin never sends more than 500 entries.
- A pin is never returned unless one seeded Engine request under it served exactly `want`.
- One pin costs at most 4 requests, and one listing at most 7.
- Pool membership does not depend on `seed`, `limit`, likes or centroids (`UpnextPoolPolicy` takes none of them). The check therefore carries over to every unseeded Client request at `limit >= len(chosen)`, keyed or not.
- Both helpers run on bucket `192.0.2.150:{route}`.

---

### 2. `tests/active/test_similar.py` (R2)

**Constants**, beside `DRAW_HEADERS` (line 640):

```python
EXCLUDE_HEADERS = {"X-Client-IP": "192.0.2.151"}
# Seeds whose up-next pool runs to about 300 rows, far past a page plus its excluded rows.
UPNEXT_SEED_QUERIES = ("linux", "cooking")
EXCLUDE_DRAW_SEED = 7
```

I am keeping `UPNEXT_SEED_QUERIES` separate from `SHORT_SEED_QUERIES` on purpose. That tuple names seeds with a short cache entry, which is a different reason for choosing them.

**Test**, placed after `test_ten_refreshes_…` (line 915):

```python
@pytest.mark.parametrize("query", UPNEXT_SEED_QUERIES)
def test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos(engine, query):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    path = _upnext_path(engine, query) + f"&debug=1&seed={EXCLUDE_DRAW_SEED}"
    status, first = engine.request("POST", path, headers=EXCLUDE_HEADERS, body={})
    assert status == 200 and len(first["rows"]) == UPNEXT_PAGE, first
    previous = _keys(first["rows"])

    # The whole previous page, and every other row of it, which offset paging would not reproduce.
    for excluded in (previous, previous[0::2]):
        status, page = engine.request("POST", path, headers=EXCLUDE_HEADERS, body={"exclude": _exclude(excluded)})
        assert status == 200, page
        rows = page["rows"]
        assert len(rows) == UPNEXT_PAGE, (excluded, _keys(rows))
        assert not set(_keys(rows)) & set(excluded), sorted(set(_keys(rows)) & set(excluded))
        assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in rows), [r["debug"]["similarity_score"] for r in rows]
```

**Docstring bullet**, appended to "Up-next's sampled page":

```
- For the linux and cooking seeds, a POST /recommendations?id=…&host=…&limit=8&debug=1&seed=7 page, then the same request excluding that whole page and excluding every other row of it, each return 8 rows, none of them excluded, every one with debug similarity_score at or above SIMILAR_VIDEO_TAIL_MIN_SCORE (membership of the seed's pool). No assertion compares two draws.
```

**Rate.** 6 requests on `192.0.2.151:/recommendations` and 2 more searches on `127.0.0.1`.

---

### 3. `tests/active/test_dislike_profile.py` (R3)

**Imports**

```python
from urllib.parse import quote

import pytest

from conftest import BRIDGE_HEADERS, closeness, cosine, embedding_of
```

**Constants**, before `_distinct_videos`:

```python
SEED_QUERIES = ("cooking", "linux")
HOME_DRAWS = 5
UPNEXT_LEADING = 8
# Above the 99th percentile of cosine between random videos in this corpus (0.59, measured).
CLEARLY_SIMILAR = 0.6
# One fixed draw for every up-next request, so pages with and without a centroid are the same draw.
DRAW_SEED = 7
```

**Restored helpers.** These come from the archive unchanged except for the `_seed_and_pair` path: `_space`, `_seed_and_pair`, `_centroid_body`, `_others`, `_margin`, `_position`. Any docstring the archive softwrapped becomes a single line. The `_seed_and_pair` path becomes:

```python
    path = f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=16&seed={DRAW_SEED}"
```

**New helpers**, after `_position`:

```python
def _similar_ids(dataset, rows, video) -> set[str]:
    """The video_ids on a page, other than the video itself, clearly similar to it."""
    target = embedding_of(dataset, video["video_id"], video["instance_domain"])
    return {r["video_id"] for r in rows if r["video_id"] != video["video_id"]
            and cosine(embedding_of(dataset, r["video_id"], r["instance_domain"]), target) >= CLEARLY_SIMILAR}


def _covered_pair(dataset, rows, plain_pages) -> tuple[dict, dict]:
    """The least similar pair on the up-next page, under cosine 0.7, each with a row other than the pair clearly similar to it on every plain home page."""
    vecs = [embedding_of(dataset, r["video_id"], r["instance_domain"]) for r in rows]
    near = [[_similar_ids(dataset, page, r) for page in plain_pages] for r in rows]
    pairs = sorted(((i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))),
                   key=lambda p: cosine(vecs[p[0]], vecs[p[1]]))
    for i, j in pairs:
        if cosine(vecs[i], vecs[j]) >= 0.7:
            break
        pair = {rows[i]["video_id"], rows[j]["video_id"]}
        if all(ids - pair for k in (i, j) for ids in near[k]):
            return rows[i], rows[j]
    pytest.fail("control: no pair under cosine 0.7 on the seeded up-next page has a clearly similar row on every plain home page")
```

**(a)** This is the archive test with its shape unchanged. The path is now seeded, so the plain page and both centroid pages are the same draw.

**(b)**

```python
@pytest.mark.parametrize("query", SEED_QUERIES)
def test_home_pages_carrying_a_dislike_centroid_place_videos_similar_to_it_lower(
        engine, dataset, query):
    seed, _, upnext, _, _ = _seed_and_pair(engine, dataset, query)
    likes = [{"uuid": seed["video_uuid"], "host": seed["instance_domain"]}]

    def home(extra: dict) -> list[dict]:
        status, body = engine.request("POST", "/recommendations", body={"likes": likes, **extra})
        assert status == 200 and body["rows"], body
        return body["rows"]

    # Plain pages first: the pair is chosen so that each has a clearly similar row on every one of them.
    plain = [home({}) for _ in range(HOME_DRAWS)]
    d1, d2 = _covered_pair(dataset, upnext, plain)
    draws = {own["video_id"]: [home({"dislike_centroids": _centroid_body(dataset, own)}) for _ in range(HOME_DRAWS)]
             for own in (d1, d2)}
    for own in (d1, d2):
        before = [_position(dataset, rows, d1, d2, own) for rows in plain]
        assert all(p < len(rows) for p, rows in zip(before, plain))  # control: each plain page holds a row clearly similar to it
        shaped = [_position(dataset, rows, d1, d2, own) for rows in draws[own["video_id"]]]
        assert min(shaped) > max(before)
    # The lean_d1 / lean_d2 lines and `assert min(lean_d1) > max(lean_d2)` are unchanged from the archive.
```

**Docstring**, with two bullets added and each written as one line:

```
- An up-next request carrying the centroid of a disliked video returns a page whose leading other rows are less similar to that video than the same request without it, both drawn with the same `seed`; a home request carrying it places the videos clearly similar to that video lower on the page, for a pair chosen so that each has a clearly similar row on every plain home page.
- In both, a page carrying one of two dislikes leans away from it, relative to the other, more than a page carrying the other.
```

**Rate.** `127.0.0.1:/recommendations` takes 2×(1+2) + 2×(1+15) = 38 requests, plus 4 searches.

---

### 4. `tests/active/test_dislikes.py` (R4)

**Imports and constants**

```python
from urllib.parse import quote, urlencode

import pytest

from conftest import closeness, cosine, embedding_of, pin_upnext, upnext_pool

UNKNOWN_KEY = "A" * 43  # the shape a minted key has, issued to nobody
# Seeds whose up-next pool is deeper than one page plus one, which the absent/present test checks.
SEEDS = ("linux", "football")
ROUTES = ("/recommendations", "/videos/similar")
PAGE = 16
LEADING = 8
```

The archive's "19 and 18 rows" comment is stale and is not copied.

**Helpers**, under a new `# --- up-next ---` divider after the key test:

- `_seed` comes from the archive.
- `_upnext` gains `body`:

  ```python
  def _upnext(client, route: str, seed: dict, headers: dict | None = None, body: dict | None = None) -> list[dict]:
      status, payload = client.request(
          "POST", f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE}",
          headers=headers, body=body or {})
      assert status == 200, payload
      return payload["rows"]
  ```

- `_pin16(engine, route, seed)` returns `{"exclude": pin_upnext(engine, route, seed, upnext_pool(engine, route, seed)[:PAGE])}`.
- `_keys(rows)` returns `{(r["video_id"], r["instance_domain"]) for r in rows}`. It replaces the archive's `_ids`.
- `_profile_disliking`, `_pair`, `_leading_others` and `_margin` are restored from the archive.

**Absent/present test**

```python
@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("query", SEEDS)
def test_a_disliked_video_is_absent_from_the_profile_s_full_upnext_page_and_present_for_others(
        unpublished_client, engine, route, query):
    client = unpublished_client
    seed = _seed(client, query)
    pool = upnext_pool(engine, route, seed)
    assert len(pool) > PAGE + 1, f"control: {query}'s {route} pool holds {len(pool)} rows"
    pin16 = {"exclude": pin_upnext(engine, route, seed, pool[:PAGE])}
    pin17 = {"exclude": pin_upnext(engine, route, seed, pool[:PAGE + 1])}
    keyless = _upnext(client, route, seed, body=pin16)
    assert _keys(keyless) == _keys(pool[:PAGE])  # control: the pinned keyless page is the pool's first 16
    disliked = keyless[PAGE // 2]
    key = _profile_disliking(client, disliked)
    bystander = _profile_disliking(client, keyless[0])
    # The Client asks for 32, the Engine serves the 17 pinned rows whole, and the Client drops the disliked one.
    page = _upnext(client, route, seed, key, pin17)
    assert _keys(page) == _keys(pool[:PAGE + 1]) - _keys([disliked])
    assert len(page) == PAGE
    assert _keys([disliked]) <= _keys(_upnext(client, route, seed, body=pin16))
    assert _keys([disliked]) <= _keys(_upnext(client, route, seed, bystander, pin16))
```

**Lean-away test.** It takes the parameters `(unpublished_client, engine, dataset, route, query)`.

- It computes `pin16 = _pin16(engine, route, seed)`.
- `keyless = _upnext(client, route, seed, body=pin16)` is followed by the control `assert _keys(keyless) == _keys(upnext_pool(engine, route, seed)[:PAGE])`.
- `d1, d2 = _pair(dataset, keyless)`. `_pair` asserts cosine < 0.7.
- `page_d1` and `page_d2` each send their profile's key with `pin16`.
- The three closeness and margin assertions are unchanged.

**Docstring.**

- The first line becomes: "A profile's dislikes on the Client backend: the actions, the key rule and its up-next pages."
- The two archive bullets are restored, each as one line.
- One line is added: "Each up-next page is pinned with `exclude` to a fixed set of the seed's pool (conftest `pin_upnext`), so it is served whole in penalised order, not drawn."
- The closing `unpublished_client` paragraph stays.

**Rate**, per route: 14 Client requests on `127.0.0.1:{route}`. The helper bucket takes 2 listings of at most 7 requests and 6 pins of at most 4, which is no more than 38 against a budget of 60. In practice it is about 10 + 6.

---

### 5. `tests/active/test_blocks.py` (R5)

**Imports and constants**

```python
import pytest

from conftest import pin_upnext, upnext_pool
```

`PAGE = 8` goes after `SEARCH`.

**Helpers**

`_rows` gains a `body` argument. All existing callers pass 4 positional arguments or fewer.

```python
def _rows(client, method: str, path: str, key: str | None = None, body: dict | None = None) -> list[dict]:
    headers = {"X-Profile-Key": key} if key else {}
    status, payload = client.request(method, path, headers=headers, body=(body or {}) if method == "POST" else None)
    assert status == 200, payload
    return payload["rows"]
```

The other new helpers sit in the "filtering reads" section:

```python
def _key_set(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["video_id"], r["instance_domain"]) for r in rows}


def _upnext(route: str, seed: dict, limit: int) -> str:
    return f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}"


def _surface(client, engine, surface: str) -> tuple[str, str, dict | None, list[dict] | None]:
    """The method, path and body of one page of the named surface, and the rows a pinned up-next page holds."""
    if surface == "search":
        return "GET", SEARCH, None, None
    seed = _rows(client, "GET", SEARCH)[0]
    chosen = upnext_pool(engine, surface, seed)[:PAGE]
    return "POST", _upnext(surface, seed, PAGE), {"exclude": pin_upnext(engine, surface, seed, chosen)}, chosen
```

**Surfaces test.** The line-139 comment goes. The test is decorated `@pytest.mark.parametrize("surface", ["/recommendations", "/videos/similar", "search"])` and its signature becomes `(engine_client, engine, surface)`.

- It opens with `method, path, body, chosen = _surface(engine_client, engine, surface)` and `keyless = _rows(engine_client, method, path, None, body)`.
- For up-next it runs the control `if chosen is not None: assert _key_set(keyless) == _key_set(chosen)` (comment: control: the pinned keyless page is the pool's first 8).
- Target selection and the `hit` function are unchanged.
- Every later `_rows` call passes `body`: blocker, keyless and bystander.
- The search case sends exactly what it sends today.

**Stays-full test**

```python
@pytest.mark.parametrize("route", ["/recommendations", "/videos/similar"])
def test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it(engine_client, engine, route):
    seed = _rows(engine_client, "GET", SEARCH)[0]
    chosen = upnext_pool(engine, route, seed)[:PAGE + 3]
    pin = {"exclude": pin_upnext(engine, route, seed, chosen)}
    # At limit 11 the keyless page is served whole: the very rows the blocker's 16-row over-fetch is served.
    keyless = _rows(engine_client, "POST", _upnext(route, seed, PAGE + 3), None, pin)
    assert _key_set(keyless) == _key_set(chosen)  # control: the rows to be blocked would otherwise be served

    key = _mint(engine_client)
    blocked = keyless[:3]
    for row in blocked:
        _block(engine_client, key, "channel", row)
    blocked_channels = {_channel(r) for r in blocked}

    # One row per channel in the pool, so exactly three of the eleven go and eight are left.
    rows = _rows(engine_client, "POST", _upnext(route, seed, PAGE), key, pin)
    assert len(rows) == PAGE, len(rows)
    assert not blocked_channels & {_channel(r) for r in rows}
```

**Docstring.** Lines 7-8 are replaced by the two archive bullets, each as one line, and one line is added:

```
- Through the read gateway, a profile's up-next (`/recommendations`, `/videos/similar`) and search pages leave out its blocked channel and account, while keyless requests and other profiles still receive them.
- An up-next page for a profile with blocks is refilled to the requested size from the Client's over-fetch, with no blocked target in it.

Up-next pages are pinned with `exclude` to a fixed set of the seed's pool (conftest `pin_upnext`), so each is served whole and its targets are surely on it.
```

**Rate**, per route on the helper bucket: 1 listing of at most 7, plus 2 pins of at most 4, which is no more than 15.

---

### 6. `tests/active/test_frontend_blocks.py` (R6)

**RUNNER `upnext`**

```js
const upnext = () => m.fetchSimilarVideosPayload({ id: process.env.SEED_UUID, host: process.env.SEED_HOST,
  limit: process.env.PAGE, apiBase: base }, JSON.parse(process.env.EXCLUDE || "[]"));
```

**`_run`** gains `exclude=()` and adds one entry to `env`: `"EXCLUDE": json.dumps(list(exclude))`. The signature becomes `_run(runner: Path, base: str, seed: dict, steps: list[str], exclude=()) -> list[dict]`.

**Imports.** `from conftest import pin_upnext, upnext_pool` is added after the stdlib block.

**`_seed_and_targets`**

```python
def _seed_and_targets(client, engine) -> tuple[dict, dict, dict, list[dict[str, str]]]:
    """A seed, a row of its up-next page pinned to the pool's first 8, a search row on none of that page's channels, and the pin."""
    search = _keyless(client, "GET", f"/api/v1/search/videos?q={QUERY}")
    seed = search[0]
    chosen = upnext_pool(engine, "/recommendations", seed)[:int(PAGE)]
    pin = pin_upnext(engine, "/recommendations", seed, chosen)
    upnext_channels = {(r["instance_domain"], r["channel_id"]) for r in chosen}
    from_search = next(r for r in search if (r["instance_domain"], r["channel_id"]) not in upnext_channels)
    return seed, chosen[0], from_search, pin
```

**Restored test.** The archive body with these changes:

- the signature is `(engine_client, engine, tmp_path)`;
- `seed, in_upnext, in_search, pin = _seed_and_targets(engine_client, engine)`;
- `_run(..., [...steps...], pin)`.

The assertions are unchanged. The before-block `upnext` is keyed, has no blocks and asks for limit 8, so the 8 pinned rows come back whole. The after-block one is over-fetched to 16 and comes back as the 8 rows minus the target.

**Refused-key test.** The signature gains `engine`, and the call becomes `seed, _in_upnext, _in_search, _pin = _seed_and_targets(engine_client, engine)`. Nothing else changes, and its runs stay unpinned.

**Docstring.** The first line becomes: "The frontend's data modules, run in node against the real Client and Engine: a channel blocked through `blocks.ts` leaves the rows they fetch, and a key the server refuses surfaces as `ProfileKeyRejectedError`." The archive bullet is restored as one line, with this addition: "; the up-next fetch is pinned with `exclude` to the seed's pool's first 8 rows (conftest `pin_upnext`), so the target is surely on the page before the block." The second paragraph stays.

---

### 7. `.un/skills/devsecops/config.json` (R7)

The new entries are appended at the end of each list, keeping the 2-space indent.

- `test_dislike_profile.py`: add `"engine/server/data/ann.py"` and `"engine/server/data/similarity_candidates.py"`.
- `test_dislikes.py`, `test_blocks.py` and `test_frontend_blocks.py`: add `"engine/server/api/handlers/similar.py"` and `"engine/server/data/similarity_candidates.py"`.

---

### 8. Retired copies (R8)

First check that `tests/archive/upnext_random_draw/` holds no `__pycache__` or other file. Then run `git mv tests/archive/upnext_random_draw/{test_similar,test_dislike_profile,test_dislikes,test_blocks,test_frontend_blocks,test_frontend_videos}.py delete_me/` and remove the empty directory. Do this after sections 3-6 have been copied out of the archive.

---

### 9. Documentation

**Issue 35 comment**, under `## Comments`, as one paragraph on one line:

"Delivered by build 35 (plan `20-35-upnext-tests-retired-by-random`): conftest gains `exclude_entries`, `upnext_pool` (a seed's whole pool, listed on the Engine with seeded 96-row excluding requests, sorted head first by `similarity_score`, cached per process) and `pin_upnext` (the `exclude` that leaves exactly a chosen set, checked on the Engine, at most 3 widenings, within the 500 cap); test_similar's exclude test, both test_dislike_profile centroid tests, both test_dislikes up-next tests, test_blocks' up-next surfaces and stays-full tests and test_frontend_blocks' module block test are active again; R2 and R3 use a fixed draw `seed` on the Engine, R4-R6 use `exclude` pins through the Client, and "the pool's first n" means its head by `similarity_score`; R3b picks d1/d2 by home-page coverage, not one draw's least similar pair; config.json maps `similar.py` and `similarity_candidates.py` to test_blocks, test_dislikes and test_frontend_blocks, and `ann.py` and `similarity_candidates.py` to test_dislike_profile; the six archive files moved to `delete_me/`. Line 26's "drop the `test_frontend_videos.py` entry" was moot: no such entry existed, and build 12's `test_frontend_upnext_pager.py` already covers the pager (line 17)."

**`plan.md` row 2a** is updated at harvest, as the documentation list says.

---

### Decisions and deliberate simplifications

- **R3b pair choice.** `_covered_pair` takes the least similar pair, under cosine 0.7, on the seeded 16-row page in which each member has a clearly similar row on every plain page once both are left out. The plan said to take the least similar covered pair and then assert coverage with both left out. Folding that check into the choice cannot change a pass into a vacuous pass, because the old `p < len(rows)` control is still asserted on the same pages. What it avoids is a needless failure when d2 happens to be d1's only similar row. If no pair qualifies, `pytest.fail` names it.
  - **Cost.** Per seed this is 16 × about 240 cosines, a few seconds of sqlite and Python.
- **`_seed_and_pair` kept as is** for (b)'s seed and page. Its own cosine < 0.7 assertion is implied by (b)'s requirement anyway.
- **No URL quoting** in the conftest path. This matches `_upnext_path` and the archive. Search-row uuids and hosts are URL-safe.
- **Pins are not cached.** Lean-away recomputes pin16, which costs at most 4 requests.
- **The pool cache is per process and in memory.** Its ceiling is about 60 helper requests a minute per route in one file. The way up is a per-module helper header or a pin cache.

### Flagged, not acted on (settled inventory; operator to decide)

- **Validator gap (`validate_tests.py`).** `claimed()` never fingerprints `conftest.py`, so the acceptance line "a conftest change reselects broadly" does not hold. Step 8 should run the full `tests/active` suite explicitly, one invocation per live-Engine file.
- **Gaps in the R7 mapping.** The pins also depend on files that R7 does not map:
  - `server_config.py`, `scoring.py` and `ann.py` for the three Client-side groups;
  - `feed-params.ts` for `test_frontend_blocks.py`.

  I left them out because R7 fixes the list.
- **Stale reference.** `test_frontend_upnext_pager.py:7` still names the archive path. It is not in the requirements, so it is left alone.


### Phases

#### Phase 1 - Exclude on the Engine [code]

**Files touched.** tests/active/conftest.py (EDITED), tests/active/test_similar.py (EDITED)

**Checkpoint.** Seam: the live Engine through conftest's `engine` fixture, following test_similar.py's harness (`_upnext_path`, `_keys`, a dedicated TEST-NET-1 `X-Client-IP` header as with `DRAW_HEADERS`/`POOL_HEADERS`). Clause 1: a new test in test_similar.py, parametrised over ("/recommendations", "/videos/similar"), resolves a seed with `_upnext_path`'s search. It takes `pool = upnext_pool(engine, route, seed)` and asserts the pool is in non-increasing `debug.similarity_score` order. It then sends unseeded `POST {route}?id=…&host=…&limit=8` and `limit=16` with body `{"exclude": pin_upnext(engine, route, seed, pool[:8])}` and asserts each response's (video_id, instance_domain) set equals pool[:8]'s. Clause 2: the R2 test `test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos` is its own checkpoint. For "linux" and "cooking", the seed-7 page excluding the whole previous page, and the one excluding every other row of it, each return 8 rows, none of them excluded, every one with similarity_score >= SIMILAR_VIDEO_TAIL_MIN_SCORE - 1e-6.

**Intent.** conftest.py's `upnext_pool` and `pin_upnext` can pin an up-next page to a chosen head of its seed's pool, and test_similar.py proves that an Engine up-next page excluding earlier rows still returns a full page of other pool videos.

- C1 - Under the exclude that `pin_upnext` returns for a chosen head of the pool, an unseeded Engine up-next request at limit >= len(chosen) is served exactly the chosen key set.
- C2 - A seeded Engine up-next page that excludes the previous page, or every other row of it, returns a full 8 rows of the seed's pool, none of them excluded.

**Outcome.** ### tests/active/conftest.py
- **Module docstring:** one new line saying that `exclude_entries`, `upnext_pool` and `pin_upnext` are plain helpers. They pin an up-next page to a fixed set of rows from its seed's pool using `exclude`, so the Engine serves the page whole instead of drawing it.
- **New constants after `BRIDGE_HEADERS`:**
  - `UPNEXT_PIN_HEADERS` = `{"X-Client-IP": "192.0.2.150"}`, the helpers' own rate bucket. It carries a `rat-tail:` comment: one bucket per process caps listing and pinning at 60 requests a minute per route, and a per-module header or a pin cache is the upgrade.
  - `UPNEXT_LIST_LIMIT` = 96 (the Engine's limit cap).
  - `UPNEXT_EXCLUDE_CAP` = 500.
  - `UPNEXT_LIST_PAGES` = ceil(500/96) + 1 = 7.
  - `UPNEXT_PIN_TRIES` = 3.
  - `UPNEXT_LIST_SEED` = 0.
  - `_UPNEXT_POOLS`, the per-process pool cache keyed by `(route, video_uuid, instance_domain)`.
- **New helpers after `identity_of`:**
  - `exclude_entries(rows)` maps rows to `{"id": video_id, "host": instance_domain}`.
  - `_upnext_key(row)` gives `(video_id, instance_domain)`.
  - `_upnext_page(engine, route, seed, exclude)` sends one `POST {route}?id=…&host=…&limit=96&seed=0&debug=1` on the helper bucket and asserts a 200.
  - `upnext_pool(engine, route, seed)` lists the seed's whole pool with seeded 96-row requests. Each request excludes everything already listed, and listing stops at the first empty page. It checks the 500 cap before each send. It raises `AssertionError` naming the route, the seed and the row count if the cap would be passed or no empty page comes back within 7 pages. It returns the rows sorted by `debug.similarity_score` (highest first, ties broken by key) and caches them for the process.
  - `pin_upnext(engine, route, seed, chosen)` starts from the pool minus `chosen` and checks it with one seeded 96-row request. It returns the exclude entries when the served keys are exactly `chosen`. If extra rows come back, it adds them to the exclude and retries, at most 3 more times, checking the 500 cap before each send. It raises `AssertionError` naming the missing or extra keys when a chosen row is missing or the retries run out. It never returns a partial pin.

### tests/active/test_similar.py
- **Module docstring:** one new bullet under "Up-next's sampled page". It describes the linux and cooking seed=7 exclude test: 8 distinct rows, none of them excluded, every one at or above `SIMILAR_VIDEO_TAIL_MIN_SCORE`, and the seeded-repeat control.
- **New constants beside `POOL_HEADERS`:**
  - `EXCLUDE_HEADERS` = `{"X-Client-IP": "192.0.2.151"}`.
  - `UPNEXT_SEED_QUERIES` = `("linux", "cooking")`. Its comment explains why it is kept apart from `SHORT_SEED_QUERIES`, which names the same seeds for a different reason.
  - `EXCLUDE_DRAW_SEED` = 7.
- **New test `test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos` (R2),** placed after the ten-refreshes test and parametrised over `UPNEXT_SEED_QUERIES`. It uses the file's existing `_upnext_path`, `_config`, `_keys` and `_exclude`.
  - The reference page at `limit=8&debug=1&seed=7` must have 8 distinct rows, all at or above the floor.
  - Control: the same seeded request repeats the reference page exactly.
  - It then sends two requests, one excluding the whole page and one excluding every other row of it. Each must return 8 distinct rows, none of them excluded, every one at or above the floor.

#### Phase 2 - Dislikes [code]

**Files touched.** tests/active/test_dislike_profile.py (EDITED), tests/active/test_dislikes.py (EDITED)

**Checkpoint.** Seam: the restored tests are the checkpoint, each entered at the boundary its file already uses. Clause 1: test_dislike_profile.py's two parametrised tests (cooking, linux) on the live Engine through `engine` and `dataset`, with `seed=DRAW_SEED`. (a) The centroid-carrying up-next page's leading other rows are less close to the disliked video than on the same seeded page without it, and the lean margin holds. (b) The `_covered_pair` control and the `p < len(rows)` control must hold on the plain home pages before `min(shaped) > max(plain)` and the lean assertion. Clause 2: test_dislikes.py's absent/present and lean-away tests, parametrised over SEEDS × ROUTES through `unpublished_client` (Client backend) plus `engine` for the pins. The control is that the pinned keyless page equals pool[:16]'s key set. The keyed page is exactly pool[:17] minus the disliked row, 16 rows. Keyless and bystander pages contain the disliked row. `_pair` cosine < 0.7, and the closeness and margin assertions hold. Each file runs in its own pytest invocation.

**Intent.** The up-next dislike tests are active again: test_dislike_profile.py proves centroid shaping on seeded Engine draws, and test_dislikes.py proves a profile's dislike filtering and lean-away on Client up-next pages pinned with `exclude`.

- C1 - In test_dislike_profile.py, on the same seeded draw, up-next and home pages carrying a dislike centroid place videos similar to it lower than pages without it.
- C2 - In test_dislikes.py, a profile's pinned full up-next page through the Client leaves out its disliked video, which keyless and bystander pages still contain.

**Outcome.** ### tests/active/test_dislike_profile.py
- **Docstring:** two new one-line bullets. The first covers up-next centroid pages compared with the plain page, both drawn with the same `seed`, and home pages placing clearly similar rows lower on average, for a pair chosen by coverage. The second covers the d1-versus-d2 lean.
- **Imports:** added `statistics.mean`, `urllib.parse.quote`, and `closeness` from conftest.
- **Constants:**
  - `SEED_QUERIES = ("cooking", "linux")`, `HOME_DRAWS = 5`, `UPNEXT_LEADING = 8`, `CLEARLY_SIMILAR = 0.6`.
  - `DRAW_SEED = 7`.
  - `DRAW_HEADERS = {"X-Client-IP": "192.0.2.157"}`, a rate bucket for these tests alone. They send about 40 requests to `/recommendations`, which the checkpoint process would otherwise share on 127.0.0.1 with its Client-driven requests. .157 is not used anywhere else in tests/.
- **Helpers restored from the archive** (docstrings made one line): `_space`, `_seed_and_pair`, `_centroid_body`, `_others`, `_margin`, `_position`.
  - `_seed_and_pair` now requests `limit=16&seed=DRAW_SEED` and sends `DRAW_HEADERS`.
- **New helpers** from the draft: `_similar_ids`, and `_covered_pair`. `_covered_pair` picks the least similar pair (cosine < 0.7) on the seeded up-next page where each member has a clearly similar row, other than the pair, on every plain home page. If no such pair exists it calls `pytest.fail`.
- **`test_an_upnext_page_carrying_a_dislike_centroid_moves_away_from_that_disliked_video`** is restored, parametrised over `SEED_QUERIES`. Its shape is unchanged from the archive. The plain page and both centroid pages are now the same seeded draw, and the closeness and margin assertions are kept.
- **`test_home_pages_carrying_a_dislike_centroid_place_videos_similar_to_it_lower`** is restored, parametrised over `SEED_QUERIES`.
  - It fetches the 5 plain home pages first and picks d1/d2 from them with `_covered_pair`.
  - Control: every plain page has a clearly similar row for each member of the pair (`p < len(rows)`).
  - Only then does it fetch the 5+5 centroid pages.
  - It compares means rather than the plan's `min(shaped) > max(plain)` and `min(lean_d1) > max(lean_d2)`: mean shaped position > mean plain position, and mean lean_d1 > mean lean_d2. The checkpoint records the operator's choice of means after the min/max form flaked on unseeded home pages.

### tests/active/test_dislikes.py
- **Docstring:** the first line now ends "…the actions, the key rule and its up-next pages". Two up-next bullets are restored, each on one line, plus one line saying each up-next page is pinned with `exclude` (conftest `pin_upnext`). The `unpublished_client` paragraph is kept.
- **Imports and constants:** added `quote`, `pytest`, and `closeness, cosine, embedding_of, pin_upnext, upnext_pool` from conftest. New constants `SEEDS = ("linux", "football")`, `ROUTES`, `PAGE = 16`, `LEADING = 8`. The archive's stale "19 and 18 rows" comment was not copied.
- **Helpers**, under a new `# --- up-next ---` divider:
  - restored from the archive: `_seed`, `_profile_disliking` (uses the file's `_mint`), `_pair`, `_leading_others`, `_margin`;
  - `_upnext` now takes a `body` argument;
  - new: `_pin(engine, route, seed, rows)` returns `{"exclude": pin_upnext(...)}`, and `_keys(rows)` returns a set of keys.
- **`test_a_disliked_video_is_absent_from_the_profile_s_full_upnext_page_and_present_for_others`**, taking `(unpublished_client, engine, route, query)` over ROUTES × SEEDS:
  - Depth control: `len(pool) > 17`.
  - pin16 and pin17 come from the pool's head. Control: the keyless pin16 page equals pool[:16]'s keys. `disliked = keyless[8]`, and the bystander dislikes `keyless[0]`.
  - The keyed pin17 page is pool[:17] minus the disliked row, with exactly 16 rows.
  - The keyed pin16 page is keyless minus the disliked row. This is the assertion that catches a Client which does not filter, because under pin17 the centroid ranks the row 17th and the cut hides it.
  - The keyless and bystander pin16 pages both contain the disliked row.
- **`test_a_profile_s_upnext_page_leans_away_from_its_disliked_video`**, taking `(unpublished_client, engine, dataset, route, query)`:
  - All three pages use pin16. The same pool[:16] control applies to the keyless page.
  - `_pair` asserts cosine < 0.7 on the pinned keyless page.
  - The closeness and margin assertions are unchanged.

### tests/tmp/test_probe_35_p2_impl.py
A throwaway probe that ran all 8 restored cases directly on the session Engine, each on a Client of its own: 8 passed in 113.5 s. It is spent: its contents are replaced with a "Delete this file" docstring, as with the earlier probes, because I have no tool to remove files.

**Beyond the files named.** tests/tmp/test_probe_35_p2_impl.py: a throwaway observation probe. It ran the restored test bodies on the real Engine and Client before hand-in (8 passed), and is now a spent "Delete this file" stub because I cannot delete files.

#### Phase 3 - Blocks [code]

**Files touched.** tests/active/test_blocks.py (EDITED), tests/active/test_frontend_blocks.py (EDITED)

**Checkpoint.** Seam: the restored tests are the checkpoint. Clause 1: test_blocks.py through `engine_client` (the read gateway) plus `engine` for pins. The surfaces test is parametrised over /recommendations, /videos/similar and search. Its control asserts that the pinned keyless up-next page equals pool[:8]'s key set, and the existing absent-for-blocker / present-for-keyless-and-bystander assertions follow. The stays-full test asserts that the keyless page at limit 11 equals pool[:11]'s key set, and that the blocker's limit-8 page has exactly 8 rows and none of the 3 blocked channels. Clause 2: test_frontend_blocks.py's restored module-block test, which runs the node RUNNER against the real Client and Engine with `EXCLUDE` carrying the `/recommendations` pin of pool[:8]. Both target channels are on the rows fetched before the block. After the block both fetches still return rows, without the blocked channel. The refused-key test still raises `ProfileKeyRejectedError`.

**Intent.** The up-next block tests are active again: test_blocks.py proves on pinned Client up-next pages that blocks filter them and the page stays full, and test_frontend_blocks.py proves that the frontend modules' pinned up-next fetch drops a channel blocked through `blocks.ts`.

- C1 - In test_blocks.py, a profile's pinned up-next pages through the gateway leave out its blocked targets, and stay full at the requested size.
- C2 - In test_frontend_blocks.py, the node runner's up-next fetch, pinned with `EXCLUDE`, holds the target channel before the block and leaves it out after.

**Outcome.** ### tests/active/test_blocks.py
- The module docstring has its up-next bullets back: up-next and search pages leave out a profile's blocked channel and account, and an up-next page with blocks is refilled to the requested size. A new line says up-next pages are pinned with `exclude` through conftest's `pin_upnext`.
- It now imports `pin_upnext` and `upnext_pool` from conftest, and adds the constants `ROUTES` and `PAGE = 8`.
- `_rows` takes an optional `pin`, which is sent as the POST body (it still sends `{}` when there is none).
- New helpers:
  - `_keys`: the set of `(video_id, instance_domain)` pairs.
  - `_upnext`: builds the path.
  - `_pinned(client, engine, route, size)`: returns the search seed, its pool's first `size` rows, and the `{"exclude": ...}` body that pins a page to them.
  - `_surface`: returns method, path, pin and pinned rows for one surface. Search gets no pin.
- `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page` is parametrised over `/recommendations`, `/videos/similar` and `search` again, and takes `engine`. The comment about retiring it is gone.
  - On up-next it first checks that the keyless page is exactly the pinned 8 rows.
  - The existing hit checks apply on all three surfaces.
  - On up-next it then checks exact pages: the blocker gets the pinned rows minus every row on the blocked channel or account, the keyless page after the blocks is all 8, and the bystander gets all 8 minus its blocked channel.
  - The search path works as before.
- `test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it(engine_client, engine, route)` is restored over both routes, pinned to the pool's first 11 rows.
  - Control: the keyless limit-11 page is exactly those 11.
  - A profile blocks the channels of the first 3 keyless rows. Its limit-8 page then has 8 rows, none on those channels, and is exactly the pinned rows not on a blocked channel.
  - The expected page is worked out from the channels rather than taken to be `keyless[3:]`, so it does not depend on there being one row per channel.

### tests/active/test_frontend_blocks.py
- The module docstring has the module-block bullet back, plus a line on the `EXCLUDE` pin.
- It now imports `pin_upnext` and `upnext_pool` from conftest.
- `RUNNER`: `upnext` passes `JSON.parse(process.env.EXCLUDE)` as the `exclude` argument of `fetchSimilarVideosPayload`. The frontend's videos.ts already supported this, so no frontend code changed.
- `_run` takes an optional `exclude` (default none) and passes it as `EXCLUDE` in JSON form. An empty list means no `exclude` is sent, so callers that pass nothing behave as before.
- `_keyless` is replaced by `_search(client)` (the GET search rows). There is a new `_channel(row)`, which returns `[domain, channel_id]` as the runner prints it.
- `_seed_and_targets(client, engine)` now returns four things: the seed, its `/recommendations` pool's first 8 rows, the `pin_upnext` exclude for them, and a search row on none of their channels.
- `test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches(engine_client, engine, tmp_path)` is restored. It runs the node runner pinned with that exclude.
  - Control: the up-next fetch before the block is exactly the pinned 8 rows' channels.
  - The search row's channel is fetched before its block.
  - After the blocks both fetches still return rows. Up-next is exactly the other 7 pinned channels, and search no longer has the blocked channel.
- In `test_a_key_the_server_refuses_surfaces_as_profile_key_rejected_on_upnext_and_search`, only the seed line changed, to `seed = _search(engine_client)[0]`. It never used the targets, so it does not need `engine` or a pin.

### Note for the documentation step
The archived copies in `tests/archive/upnext_random_draw/` still describe these tests as retired and "never written". I did not touch them, because they are outside this phase's files. `tests/tmp/probe_35_p3_standin/` holds two spent stand-in files that say they should be deleted. I left them alone; they do not interfere with the checkpoint's imports.

#### Phase 4 - Bookkeeping [code]

**Files touched.** .un/skills/devsecops/config.json (EDITED), tests/archive/upnext_random_draw/*.py (MOVED to delete_me/)

**Checkpoint.** Seam, clause 1: `.un/skills/devsecops/scripts/validate_tests.py`'s `claimed(project, load_config())`. The checkpoint asserts that the paths claimed for test_blocks.py, test_dislikes.py and test_frontend_blocks.py include engine/server/api/handlers/similar.py and engine/server/data/similarity_candidates.py, and that those claimed for test_dislike_profile.py include engine/server/data/ann.py and engine/server/data/similarity_candidates.py. Clause 2: a filesystem check that tests/archive/upnext_random_draw/ does not exist and that delete_me/ holds the six files (test_similar, test_dislike_profile, test_dislikes, test_blocks, test_frontend_blocks, test_frontend_videos .py). The full tests/active suite stays green, one invocation per live-Engine file.

**Intent.** The devsecops selector reselects the restored up-next tests when the Engine sources their pins and draws depend on change, and the retired archive copies are gone from tests/archive.

- C1 - config.json maps the four restored test files to the Engine similarity sources R7 names.
- C2 - tests/archive/upnext_random_draw/ no longer exists, and its six files are in delete_me/.

**Outcome.** ### `.un/skills/devsecops/config.json`
Added the R7 mappings to the end of each list, as plan §7 says, so every existing entry stays where it was:
- `test_dislike_profile.py` gains `engine/server/data/ann.py` and `engine/server/data/similarity_candidates.py`. It already had `engine/server/api/handlers/similar.py`, and that entry is still there.
- `test_dislikes.py`, `test_blocks.py` and `test_frontend_blocks.py` each gain `engine/server/api/handlers/similar.py` and `engine/server/data/similarity_candidates.py`.

No other group changed.

### `tests/archive/upnext_random_draw/*.py` → `delete_me/`
These files have **not been moved yet**. My tools can create and edit files but cannot move or delete them, so I can't remove the archive directory. I also didn't copy the files over with Write, because that could change their bytes and fail the checkpoint's SHA-256 check. The move (R8) is left to the operator; the steps are in `awaiting_operator`. Once it's done, `delete_me/` will hold `test_similar.py`, `test_dislike_profile.py`, `test_dislikes.py`, `test_blocks.py`, `test_frontend_blocks.py` and `test_frontend_videos.py` as they were in the archive, and `tests/archive/upnext_random_draw/` will be gone.


