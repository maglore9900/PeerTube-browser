# 45-trending-from-source-instances

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/46-45-trending-from-source-instances.record.md`._

## Requirements

### Source

- Issue: `docs/project/issues/38-hot-trending-by-growth.md`. Its triage comment records the decisions taken before planning. The build that delivers this plan closes it: set its `Status:` to `enhancement, complete` and move it to `docs/project/issues/archive/`.
- Plan: `docs/project/plans/45-trending-from-source-instances.md`.
- Decision record: ADR-0010, `docs/project/adr/0010-trending-from-source-instances.md`. Glossary: **Trending** in `CONTEXT.md`.

### What is being built

Hot is replaced by **Trending**. Trending is one global order built from each catalogue host's own PeerTube `sort=-trending` list, merged by rank. The home feed mode Hot becomes Trending. The Recommendations mix's popular layer draws from the Trending order instead of the popularity order.

### Purpose

Hot today ranks by `videos.popularity`, an age-decayed total, `(views + 2 × likes) / (1 + age_days / 30)`. That score mostly surfaces the largest videos in the catalogue, and it never decays between writes. Nothing in the pipeline re-reads counts for videos already in prod, so computing growth ourselves would need a new full count-refresh job and snapshot storage. The goal is a feed of what is being watched now, at a cost the pipeline can afford. PeerTube already ranks each instance's videos by views over its last 7 days (`trending.videos.intervalDays`). The order is therefore fetched, about one request per host per day, and not computed. Small instances get the same exposure per rank as large ones; this is intended.

### Fetch

- **Request:** `GET https://<host>/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both`, one page per host. `-hot` and the instance's configured default algorithm are not used (ADR-0010).
- **Hosts:** every host with at least one embedded video in `whitelist.db` (a distinct `instance_domain` in `video_embeddings`), minus the hosts in `instance_denylist`. `instances.health_status` is not consulted. (Operator decision. Rejected: healthy `instances` rows minus the denylist, which asks hosts that cannot contribute a row.)
- **NSFW:** `nsfw=both`, so flagged videos are ranked and the Engine's per-request NSFW filter decides who sees them. (Operator decision. Probed 2026-10-02: without it, instances drop flagged videos. tilvids.com `total` 3,053 → 3,070 with `nsfw=both`, peertube.tv 731 → 735, framatube.org and video.blender.org unchanged. v1-v3 hosts were not probed with `nsfw=both`; a host that rejects it simply counts as a failed host.)
- **Matching:** a listed video is identified the way the crawler identifies it: `video_id` is `uuid`, falling back to `id` (`engine/crawler/src/videos-worker.ts:666`), and `instance_domain` is the host asked. The fetch ingests nothing into `videos`, `channels` or `video_embeddings`.
- **Whole list stored:** the job stores every listed video, whether or not it is in the catalogue. The catalogue join (`videos` plus `video_embeddings`) happens at read time, so a video the crawl adds later appears without a refetch. A listed video that is not in the catalogue never enters the order.
- **HTTP:** stdlib `urllib`, as `sync-whitelist.py` and `updater-worker.py` do. Requests are concurrent, using the updater's `--concurrency`, `--timeout-ms` and `--max-retries` values (updater defaults are 4, 5000 ms and 3). All network fetching completes before the write transaction opens.

### Storage

- A new table in `whitelist.db` holds the ranks. Its columns are host (`instance_domain`), `video_id`, rank (1-100), the listed video's likes, the listed video's views, and the time the host's list was fetched. The key is (`instance_domain`, `video_id`). (Operator decision. Rejected: a separate file swapped in per ADR-0008, which needs its own handle, swap path and cross-DB lookup in the Engine.)
- **Schema creation (operator-approved correction of the request):** the table is created by an idempotent `ensure_*_schema(conn)` function (`CREATE TABLE IF NOT EXISTS`) in an `engine/server/data/` module, following `ensure_moderation_schema` and `ensure_interaction_event_schema`. It is called at Engine startup beside those (`engine/server/api/server.py:333-334`) and by the trending job before it writes. It is not added to `whitelist_migrations.py`, which holds only legacy table rebuilds run by the manual `migrate-whitelist.py`. Because the Engine creates the empty table on boot, Trending reads never fail with "no such table" before the first fill.
- **Partial failure, per host:** a host that answers has all its rows replaced by the new list. A host that fails (network error, timeout, non-2xx, unparseable body, after retries) keeps its previous rows. After that, any host's rows whose fetch time is more than 3 days old are deleted. One bad run never empties Trending, and a dead host ages out. (Operator decision. Rejected: all-or-nothing behind an answer-rate threshold, and keeping only the hosts that answered.)
- **One transaction:** all writes of a run (replacements, then the 3-day purge) happen in one short transaction after all fetching is done.
- **Host removal:** a host removed by the denylist or a stale-host purge loses its rank rows together with its videos. This is done by adding the ranks table to `_host_table_column_pairs()` in `engine/server/data/moderation.py:308`, which `purge_host_data` uses for the updater's denylist prune, the sync-join stale-host purge and `instance-denylist-cli.py`.

### Order

- Rows are interleaved by rank: every host's #1, then every #2, and so on, up to #100.
- Within a round (same rank), ties break on the listed likes, then the listed views, then `video_id`, then `instance_domain`, all descending. This is the direction the existing orders use for their closing keys, and it makes the order total, so `LIMIT/OFFSET` paging never repeats or skips a row.
- Only rows that join to the catalogue are in the order: a row in `videos` with a matching row in `video_embeddings`, with `channels` left-joined as the other ordered feeds do.
- The order is finite. The Trending feed ends when its rows run out, and it never falls back to the popularity order or any other order.
- The existing per-request filters still apply: error threshold, NSFW (`_listing_conditions`), the `exclude` list and serving moderation.

### Engine: home feed mode

- The Trending order is one more entry beside the existing ordered feeds in `engine/server/data/random_videos.py` (`ORDERED_FEED_ORDER_BY`), served by `fetch_ordered_page` and the unchanged `_handle_ordered_feed` path (`engine/server/api/handlers/similar.py:759`): `LIMIT/OFFSET` chunks skipping `exclude` keys, up to 4 chunks, then serving moderation. Because Trending needs a join to the ranks table and its own `ORDER BY` columns, `fetch_ordered_page` gains whatever minimal per-order join it needs. The other three orders' SQL and results stay as they are.
- `trending` replaces `hot` in `FEED_MODES` and `ORDERED_FEED_MODES` (`similar.py:105-107`). `mode=hot` gets the same 400 `{"error": "Unknown mode", "allowed": [...]}` as any unknown mode, with `trending` in `allowed`.
- The `hot` entry in `ORDERED_FEED_ORDER_BY` is removed. `POPULAR_ORDER_BY` stays only if something still reads it; the search sort `popularity` (`engine/server/data/search.py:86`) has its own order.
- The Client backend passes `mode` through unchanged (`client/backend/server.py:96`); no change there.

### Engine: Recommendations popular layer

- The popular layer's pool (`fetch_popular_videos`, called at `engine/server/api/recommendations/candidates/popular_videos.py:53`, wired in `builder.py:114` and `server.py:405`) becomes the first `pool_size` rows of the Trending order (`DEFAULT_POPULAR_POOL_SIZE = 5000`, `server_config.py:68`), joined to the catalogue as above. The function keeps its call signature and returned row shape, including the `popularity` field, so the generator is unchanged.
- Everything after the pool is unchanged: the author and instance caps, and the uniform or similarity-weighted draw.
- With an empty ranks table, the pool is empty and the layer returns `[]` (existing behaviour at `popular_videos.py:55`). The mix must still answer. The build confirms what the mixer does with an empty popular layer.

### Trending job

- A new script in `engine/server/db/jobs/` following the existing jobs: argparse, a `--db` path to `whitelist.db`, `logging`, stdlib `urllib`, and `--concurrency`, `--timeout-ms` and `--max-retries` options.
- It can be run alone, by hand or for the first fill after deploy, while the Engine is serving.
- It logs hosts asked, answered and failed, rows written, rows purged by age, and the write transaction's duration.
- It exits non-zero if the job itself fails (for example, the DB cannot be opened or the transaction fails). A host that fails is logged and is not a job failure.

### Updater stage

- The updater (`engine/server/db/jobs/updater-worker.py`) runs the trending job daily inside the existing run. It runs after the Engine is started again, after the `finally` block that starts the Engine and releases the deploy lock, and before `run_similarity_stage` (`:1438`). It passes the updater's `--concurrency`, `--timeout-ms`, `--max-retries` and prod DB path. (Operator decision.)
- A failure of the stage itself (the job exits non-zero or raises), as opposed to a host that fails, is logged. The similarity stage still runs, and the run exits non-zero at the end, after the similarity stage, whether or not similarity succeeded. A failing similarity stage cannot skip trending, because trending runs first. (Operator decision. Rejected: last in the run with a fatal failure.)
- Known and accepted: a `--sync-join-whitelist` run with no changes returns early (`:1328`) and skips the stage. The systemd timer's default run is not sync-join.

### Frontend

- `client/frontend/src/data/feed-params.ts`: `trending` replaces `hot` in `FEED_MODES`.
- `parseFeedMode` reads `hot` as `trending`, both from `?mode=` and from the stored `feedParams:v1` object, so a returning visitor who chose Hot lands on Trending. Any other unknown value still maps to `recommendations`. (Operator decision. Rejected: no alias, and an Engine-side synonym.)
- The Hot button in `client/frontend/index.html:41` and `client/frontend/videos.html:41` becomes a "Trending" button for mode `trending`.
- `client/frontend/dist/` is build output and is not edited by hand.

### Documents

- `OVERVIEW.md`, `LAYER_PARAMS.md`, `engine/server/db/jobs/docs/UPDATER_WORKER.md`, `DATA_BUILD.md`, the READMEs (`README.md`, `client/frontend/README.md`, `engine/server/README.md`) and `CONTEXT.md` describe Trending instead of Hot.
- `UPDATER_WORKER.md` describes the new stage, its place in the run, its failure handling, the by-hand first fill and the early-return skip.
- The `CONTEXT.md` **Popular** entry, which says the mix's popular layer "uses the Hot order", is updated to say it uses the Trending order.

### Acceptance criteria

- A1. After one run of the trending job against hosts that answer, the ranks table holds at most 100 rows per asked host. Each row carries the host's rank, the listed likes and views, and the fetch time.
- A2. A host that fails on a later run keeps its earlier rows. Rows of a host last fetched more than 3 days ago are gone after the next run. A denied host is never asked. A denylist or stale-host purge deletes that host's rank rows.
- A3. `mode=trending` on an unseeded `/recommendations` returns catalogue videos in rank-interleaved order, with the tie-breaks above. It pages through `exclude` like the other ordered feeds, and it ends when the ranked rows run out, with no fallback. `mode=hot` returns 400 with `trending` in `allowed`.
- A4. The Recommendations popular layer draws only from videos in the ranks table, taking the first `pool_size` rows of the Trending order.
- A5. The home page shows a "Trending" button instead of "Hot". `?mode=hot`, or a stored `hot`, opens Trending.
- A6. The updater run calls the trending stage between the Engine start and the similarity stage. A trending stage failure does not stop the similarity stage, and the run exits non-zero.
- A7. The documents listed under Documents describe Trending instead of Hot.

### Out of scope

- `videos.popularity`, `recompute-popularity.py` and its updater step (`updater-worker.py:1376`), the `/api/video` popularity write (`handlers/video.py:379-405`) and the search sort `popularity` (`data/search.py:86`) all stay as they are. They keep a reader in search. (Operator decision.)
- The Popular mode (all-time likes), the Recent mode and the Random mode are unchanged.
- No backwards compatibility beyond the frontend `hot` → `trending` read.
- No change to the crawler, staging or `merge_rules.json`.

### Consistency constraints

- The job follows the `engine/server/db/jobs/*.py` scripts' style (argparse, `--db`, `logging`, `urllib`) and matches the style of the file each change lands in.
- The table's schema function follows the `ensure_*_schema` pattern in `engine/server/data/`.
- The Trending order sits beside the existing ordered feeds in `random_videos.py` and is served through `_handle_ordered_feed`.
- Design to the smallest thing that works: stdlib only, no new dependency, no new abstraction for a single use.

### Risks the build must check

- R1. **Write while serving.** The job writes `whitelist.db` while the Engine reads it through one shared connection (`engine/server/data/db.py:77`, `sqlite3.connect` with the default 5 s busy timeout and no explicit journal mode, serialised by `db_lock`). The write is one transaction of up to about 176k rows (1,764 hosts × 100). The build checks the DB's journal mode and the Engine connection's busy timeout, and measures and logs the transaction's duration. No network I/O happens inside the transaction.
- R2. **Cold start.** The table is empty until the job first runs, so Trending is empty and the popular layer's pool is empty. The deploy runs the job once by hand. The build checks that the mix still answers with an empty popular layer.
- R3. **Popular pool depth.** With about 1,764 hosts, a 5,000-row pool covers roughly the first three rounds. The pool changes from "biggest videos" to "small and large instances equally". This is intended (ADR-0010), and `pool_size` stays the knob.
- R4. **Round width.** Each round holds up to about 1,764 rows, so a visitor pages through many small instances' #1 before any host's #2. This is intended. Paging through `exclude` still ends after about 500 shown rows (existing limit; roadmap "cursor parameter").
- R5. **Run time.** About 1,764 requests at the updater's concurrency and timeout; a slow tail of dead hosts can stretch the stage, and the similarity stage waits for it.
- R6. **Old hosts.** `nsfw=both` was not probed on v1-v3 (at most about 27 hosts). A host that rejects it fails and keeps, then ages out, its list.
- R7. **Early-returning runs.** A no-change `--sync-join-whitelist` run skips the stage (accepted).
- R8. **Overlap with issue 08.** Both touch `random_videos.py` and the updater docs. Issue 08 appears merged (`b423159 Merge branch '08'`); the build confirms.

### Limitations (accepted)

- Trending is at most a day old, on top of the instances' own 7-day windows, and up to 3 days old for a failing host.
- The order is per-instance relative: a 25-view #1 sits beside a 400-view #1.
- A video trending on a host not yet crawled appears only after the normal crawl adds it.

### Tests and directories

- Active tests: `tests/active`. Working directory: `tests/tmp`. Archive: `tests/archive`. Plans: `docs/project/plans`. Scratch for deletion: `delete_me`. Project dir: `/home/enduser/code/PeerTube-browser/`. Validation record: `tests/last_test_validation.json`. Test output: `tests/last_test_output.txt`.
- Existing active tests that reference `hot` and will need updating with the build: `tests/active/test_frontend_feed_params.py`, `tests/active/test_random_videos.py`, `tests/active/test_server.py`, `tests/active/test_similar.py`.
- Tests must not reach real PeerTube hosts. The job's HTTP is exercised against a local stub or injected fetcher.

### Baseline suite state

- Pre-build baseline: the suite exits with code 0 (all passing), not a variant run. Any failure after the build is introduced by the build.

## High-level plan

### Approach

The build adds one table, one schema function, one job script, one updater stage and one new entry in the ordered-feed machinery. The popular pool is moved onto that entry, and Hot is renamed on the frontend. No new abstraction is introduced. The work follows the requirements in order.

**Storage and schema.** A new module `engine/server/data/trending.py` holds `ensure_trending_schema(conn)`, following `ensure_moderation_schema`: an `executescript` of `CREATE TABLE IF NOT EXISTS trending_ranks` with `instance_domain`, `video_id`, `rank`, `likes`, `views` and `fetched_at` (epoch ms via `data.time.now_ms`, as other tables use). The primary key is (`instance_domain`, `video_id`). One `CREATE INDEX IF NOT EXISTS` matches the Trending `ORDER BY` exactly: `rank` ascending, then `likes`, `views`, `video_id` and `instance_domain` descending. A `LIMIT/OFFSET` walk can then read the index in order and stop early instead of sorting the whole table. The Engine calls it at startup next to `ensure_moderation_schema` and `ensure_interaction_event_schema` (`server.py:333-334`), so the table exists, empty, before the first fill. The job calls it before writing. `whitelist_migrations.py` is not touched.

**Host removal.** `("trending_ranks", "instance_domain")` is appended to `_host_table_column_pairs()` in `moderation.py:308`. `purge_host_data` already skips tables that do not exist (`_table_exists`), so staging DBs and old test fixtures without the table are unaffected. This covers the updater denylist prune, the sync-join stale-host purge and `instance-denylist-cli.py` in one line (A2).

**Trending job** (`engine/server/db/jobs/fetch-trending.py`). It follows `recompute-popularity.py` and `sync-whitelist.py`: `sys.path` setup to reach `data.*`, argparse with `CompactHelpFormatter`, `--db` (default the prod `DEFAULT_DB_PATH`), `--concurrency 4`, `--timeout-ms 5000`, `--max-retries 3`, `logging`, and stdlib `urllib`.
- **Phase 1, read.** It opens `whitelist.db` and runs `ensure_trending_schema`. It takes `SELECT DISTINCT instance_domain FROM video_embeddings`, minus `list_active_denied_hosts(conn)` (reused from `data.moderation`), so a denied host is never asked. `instances.health_status` is not read.
- **Phase 2, fetch, with no transaction open.** A `concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)` runs one function per host. That function GETs `https://<host>/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both` with the timeout, retries up to `max_retries`, and parses `data`. Rank is the 1-based position in the list. The key is `uuid`, falling back to `id` as `videos-worker.ts:666` does. Likes and views are read as ints, defaulting to 0. A repeated key keeps its first rank, so the primary key cannot abort the write. Entries with neither `uuid` nor `id` are skipped. A host is "answered" with a parsed list, which may be empty. It is "failed" on a network error, timeout, non-2xx or an unparseable body after the retries.
- **Phase 3, write.** In one `BEGIN IMMEDIATE … COMMIT`, for each answered host it deletes that host's rows and `executemany`-inserts the new list. Failed hosts are left alone. It then deletes rows whose `fetched_at` is older than now minus 3 days. The transaction's duration is timed.
- **Logs:** hosts asked, answered and failed (failed hosts are named at a debug/warning level), rows written, rows purged by age, and the transaction's ms.
- **Exit status:** a failure to open the DB, a schema error or a transaction failure propagates and the process exits non-zero. Host failures never do.

This satisfies Fetch, Storage, partial failure and A1/A2.

**Order.** In `random_videos.py`, `ORDERED_FEED_ORDER_BY` loses `hot` and gains `trending`: `t.rank ASC, t.likes DESC, t.views DESC, t.video_id DESC, t.instance_domain DESC`. A companion dict holds the minimal per-order join, which is the empty string for `popular`/`recent` and `JOIN trending_ranks t ON t.instance_domain = v.instance_domain AND t.video_id = v.video_id` for `trending`. `fetch_ordered_page` interpolates it after the `videos` join, so the other three orders' SQL is byte-identical. Because the join is an inner join, only listed rows that are in the catalogue (`videos` plus `video_embeddings`, with `channels` left-joined) take part, and the order ends when they run out. `_listing_conditions`, `exclude` skipping, the chunk walk and serving moderation are untouched because `_handle_ordered_feed` is unchanged apart from its docstring (A3). `POPULAR_ORDER_BY` loses its last reader and is deleted; search keeps its own order.

**Mode.** In `similar.py:105-107`, `trending` replaces `hot` in `FEED_MODES` and `ORDERED_FEED_MODES`. `mode=hot` then falls into the existing unknown-mode 400, with `trending` in `allowed`.

**Popular layer.** `fetch_popular_videos` keeps its signature. Its body becomes a call to `fetch_ordered_page(conn, "trending", limit, 0, error_threshold, include_nsfw)`. That function already returns the identical row shape, `popularity` included, so the pool is exactly the first `pool_size` rows of the Trending order with the same filters. This deletes a duplicated query instead of adding a second Trending SQL. `PopularVideosGenerator`, the builder and the server wiring are unchanged (A4). An empty table yields `[]` at `popular_videos.py:55`. In `mixer.py:112-125` an empty layer is stored as an empty list and `_soft_mix_candidates` fills by ratio from the other layers. The build confirms this with a test that the mix still answers a full batch from an empty ranks table (R2).

**Updater stage.** After the `finally` that starts the Engine and releases the deploy lock (`:1414-1427`) and before `run_similarity_stage` (`:1438`), the updater calls the job through `run_cmd` with `args.python_bin`, `--db prod_db`, `--concurrency`, `--timeout-ms` and `--max-retries`, the same way `recompute-popularity.py` is called. The call sits in a `try/except Exception` that logs the failure and sets a flag. The similarity stage then runs as before. After it returns, a set flag raises a `RuntimeError("trending stage failed")` inside the outer `try`. The temp-file `finally` still runs and the process exits non-zero, as every other stage failure does. If similarity itself raises, that exception already makes the run non-zero, and the trending failure was logged earlier (A6). The no-change sync-join early return at `:1328` precedes all of this and skips the stage, as accepted.

**Frontend.** In `feed-params.ts`, `trending` replaces `hot` in `FEED_MODES`, and `parseFeedMode` maps the literal `hot` to `trending` before the lookup. Both `?mode=` and the stored `feedParams:v1` go through `parseFeedMode`, so one line covers both. Any other unknown value still maps to `recommendations`. The two HTML buttons become `data-feed-mode="trending"` with the label "Trending". The stale comment at `pages/videos/index.ts:248` is updated. `dist/` is not edited (A5).

**Documents.** The listed documents and `CONTEXT.md` (the **Hot** entry is removed, **Trending** loses "not built yet", and the **Popular** entry says the layer uses the Trending order) describe Trending (A7). `UPDATER_WORKER.md` gains the stage, its place, its failure rule, the by-hand first fill command and the early-return skip. `engine/server/README.md` and `api/recommendations/docs/OVERVIEW.md` change their mode lists and ordered-feed sections. The issue gets `Status: enhancement, complete` and moves to `archive/`. `DEPLOYMENT.md` and `client/README.md` also name Hot. They are outside the listed set, but leaving them would contradict the build, so the build updates any line there that describes the Hot mode, and only those lines.

**Tests.** These live in `tests/active` and never reach real hosts:
- **Job:** loaded via importlib, as `test_host_normalisation._load_job` does. Its fetch is exercised through a monkeypatched `urlopen` (good body, non-2xx, timeout, garbage, retry count). The run is exercised through an injected per-host fetcher on a temp DB, covering replace, keep-on-fail, 3-day purge, denylist not asked, at most 100 rows per host and exit status.
- **Order:** rank interleave, the tie-break chain, catalogue-only rows, paging without repeat or skip, the end with no fallback, and `mode=hot` → 400.
- **Pool and mix:** the popular pool equals the Trending head, and the mix answers with an empty table.
- **Purge:** `purge_host_data` removes rank rows.
- **Updater:** the stage's position, and similarity still running before the run exits non-zero.
- **Frontend:** `hot` → `trending` from the URL and from storage.
- **Updated suites:** `test_frontend_feed_params.py`, `test_random_videos.py`, `test_server.py` and `test_similar.py` are updated. `test_random_videos.py` asserts that `fetch_popular_videos` ranks by popularity, which this build deliberately changes, so those assertions are rewritten to the Trending order. `test_popular_videos.py` uses a stub fetcher and should be unaffected. Tests that assert exact `purge_host_data` count dicts gain the new key.

### Alternatives considered

- **A separate `fetch_trending_videos` query for the pool and a second Trending SQL in `fetch_ordered_page`.** Rejected: two copies of one order drift apart. Reusing `fetch_ordered_page` at offset 0 makes A4's "first `pool_size` rows of the Trending order" true by construction.
- **Driving the Trending query from a subquery over `trending_ranks`,** as `fetch_popular_videos` does today. Rejected: it changes the shared query's shape. A per-order join fragment keeps the other three orders' SQL identical.
- **An `ORDERED_FEED` spec object or class per order** to hold join plus order. Rejected as an abstraction for one use. A second small dict beside `ORDERED_FEED_ORDER_BY` is enough.
- **Running the job in-process in the updater** by importing it, instead of `run_cmd`. Rejected: every other stage is a subprocess, the hyphenated filename is not importable, and a subprocess gives the clean "exits non-zero" failure signal the requirements describe.
- **asyncio or a dependency** (`requests`, `aiohttp`) for the concurrent fetch. Rejected: stdlib `ThreadPoolExecutor` plus `urllib` is enough for about 1,764 requests.
- **Upsert (`INSERT … ON CONFLICT`) instead of delete-then-insert per host.** Rejected: a host's list shrinks or shuffles, so stale entries would linger. Delete-then-insert per answered host is the "replace" the spec asks for.
- **Retrying only transient failures** (timeouts, 5xx, 429). Rejected for now as an extra rule. Every failure is retried up to `max_retries`. This deliberate simplification costs a few wasted requests on hosts that answer 4xx, for example a v1-v3 host rejecting `nsfw=both`. Its ceiling is R5's run time; the upgrade path is a status-code check in the one fetch function.
- **A CLI flag for a base URL** to point the job at a local stub. Rejected: tests inject at the fetch function and `urlopen`, so production gains no test-only surface.

### Gotchas and risks

- **R1, write while serving.** With no explicit journal mode the DB is in rollback mode, unless the file persisted WAL. The build checks this on a copy of prod with `PRAGMA journal_mode` and records it. In rollback mode, readers are blocked only while the writer holds EXCLUSIVE. That happens at commit, or earlier if the page cache spills. The job therefore:
  - opens its own connection with a busy timeout of about 10 s, as `merge-staging-db.py` does, so it waits out Engine reads;
  - raises `cache_size` for its connection so roughly 176k small rows do not spill and take EXCLUSIVE early;
  - does no I/O other than SQLite inside the transaction.

  Engine writes (interaction events, `/api/video` popularity writes) wait on the job's RESERVED lock with the Engine's default 5 s busy timeout, while holding `db_lock`. A transaction measured in seconds would therefore stall routes or produce a `database is locked` error on those writes. The duration is logged every run for this reason. If it measures above about a second, the fallback is one transaction per batch of hosts. That would break the "one transaction" requirement, so it would come back to the operator, not be done silently.
- **Query plan.** The Trending walk must drive from the `trending_ranks` index, or each chunk sorts the full join under `db_lock`. The build checks `EXPLAIN QUERY PLAN` for the absence of `USE TEMP B-TREE FOR ORDER BY` on a realistic fixture. If the planner prefers `video_embeddings`, the join fragment is reordered (SQLite's `CROSS JOIN` fixes the driving table), still for Trending only.
- **Host list query.** `SELECT DISTINCT instance_domain FROM video_embeddings` may scan the whole table once a day. It runs before the transaction, so it is acceptable.
- **R5, run time.** Assume 4 workers, a 5 s timeout and up to 4 attempts. Each dead host can cost about 20 s, so 200 dead hosts add about 17 minutes before similarity starts. Healthy hosts answer in well under a second, and the stage's duration is logged.
- **R6, old hosts.** A host that rejects `nsfw=both` or ignores `isLocal` is harmless. A rejection is a failed host, and an ignored `isLocal` lists remote videos under the asked host's domain. Those videos do not join the catalogue and silently consume rank positions.
- **R2, cold start.** Until the by-hand first fill, Trending is empty: the home Trending feed returns an empty page, and the mix runs without its popular layer. `UPDATER_WORKER.md` documents the fill command.
- **Orchestrator smoke script.** `engine/server/db/jobs/tests/test-orchestrator-smoke.py`, which is outside `tests/active`, runs the real updater. The new stage would try to fetch from whatever hosts its fixture DB holds. The build checks what those hosts are. If they are real domains, the per-host failures are harmless but slow, and the smoke run would only need the new log marker if it asserts on it.
- **R8.** The build confirms with `git log` that issue 08's merge (`b423159`) is in the base before editing `random_videos.py` and the updater docs.

### Tradeoffs the operator is asked to accept

- The popular pool now carries the Trending order's semantics. Its rows' `popularity` field is still returned for shape compatibility but no longer reflects why a row is in the pool.
- The Trending feed and the pool are empty until the first fill, and stay empty if the job never succeeds. There is no fallback, by design.
- Every failure is retried, including deterministic 4xx. This is simpler, at a bounded run-time cost.
- `POPULAR_ORDER_BY` is deleted, so the age-decayed order no longer serves any feed. `videos.popularity` keeps only its search reader, as decided.
- The trending stage lengthens every daily run by its fetch time before the similarity stage starts.
- Whether the single write transaction is short enough is measured, not guaranteed. If it is not, splitting it needs the operator's decision.

## Impacts


<impact path="engine/server/data/trending.py" element="NEW module: ensure_trending_schema(conn), the trending_ranks table and its ORDER BY index">
**What changes.** This is a new file. Outside `docs/project/` nothing named `trending_ranks`, `ensure_trending_schema` or `fetch-trending` exists in the tree yet. Model it on `ensure_moderation_schema` (`engine/server/data/moderation.py:106-134`): `from __future__ import annotations`, a one-line module docstring ("Provide ... runtime helpers." is the house form, see `interaction_events.py:1`), and one `conn.executescript(...)` holding:
- `CREATE TABLE IF NOT EXISTS trending_ranks (instance_domain TEXT NOT NULL, video_id TEXT NOT NULL, rank INTEGER NOT NULL, likes INTEGER NOT NULL, views INTEGER NOT NULL, fetched_at INTEGER NOT NULL, PRIMARY KEY (instance_domain, video_id))`;
- one `CREATE INDEX IF NOT EXISTS ... (rank ASC, likes DESC, views DESC, video_id DESC, instance_domain DESC)`.

`ensure_interaction_event_schema` (`interaction_events.py:19-54`) ends with an extra `conn.commit()` and `ensure_moderation_schema` does not. Either works, because `executescript` commits any pending transaction first. `fetched_at` comes from `data.time.now_ms` (`data/time.py:8`), not from the duplicate `moderation.now_ms` (`moderation.py:39`).

**What depends on it.**
- Engine startup (`api/server.py:333-334`).
- The new job.
- Every fixture DB that reaches `fetch_ordered_page(..., "trending")` or the new `fetch_popular_videos`. The hand-built fixtures in `tests/active/test_random_videos.py` (`_feed_db` :100, `_signal_db` :216, `_two_video_db` :291, the in-memory `nsfw_conn` :382) have no such table today.
- The session Engine in `tests/active/conftest.py:108` creates the table, empty, in the repo's live `whitelist.db` on its first start.

**Regression risk: low on its own.** `IF NOT EXISTS` is idempotent, and both blue/green Engines may run it concurrently. A `CREATE` on an existing object takes no write lock. Two traps:
- The job must call it before its `BEGIN IMMEDIATE`, never inside it, because `executescript` would commit the open transaction.
- The age purge `DELETE ... WHERE fetched_at < ?` has no index, so it scans all of the roughly 176k rows inside the write transaction. That adds to the R1 duration. An index on `fetched_at` is optional; measure first.
</impact>
<impact path="engine/server/api/server.py" element="data imports (lines 97-109) and startup schema calls (lines 331-336)">
**What changes.**
- Add `from data.trending import ensure_trending_schema` beside the other `ensure_*` imports (104-109).
- Call `ensure_trending_schema(db)` next to `ensure_moderation_schema(db)` and `ensure_interaction_event_schema(db)` (333-334). It must run on the read-write `db` from `connect_db` (331), not on `search_db`, which is `connect_readonly_db` (332) and would fail with "attempt to write a readonly database".
- The `fetch_popular_videos` import (101) and its wiring at 405 stay.

**What depends on it.** Every Engine start, prod and the test session Engine. Until the first fill, Trending reads see an empty table instead of "no such table".

**Regression risk: low.** If the job holds RESERVED or EXCLUSIVE at the moment an Engine first creates the table (first deploy only), the DDL waits on sqlite's default 5 s busy timeout (`data/db.py:79` sets none) and could fail startup. In practice the table exists after the first boot, and later starts take no write lock.
</impact>
<impact path="engine/server/data/moderation.py" element="_host_table_column_pairs() (lines 308-318); purge_host_data (194-228) and _count_host_rows (321-337) through it">
**What changes.** Append `("trending_ranks", "instance_domain")` to the list. `purge_host_data` and `_count_host_rows` skip absent tables (`_table_exists`, 214/222/329). Staging DBs (crawler `schema.sql`), the mini-prod of the smoke test and old fixtures therefore get no new key and no error. The DELETE is a primary-key prefix lookup, because the PK leads with `instance_domain`.

**What depends on it.**
- `updater-worker.py` `purge_hosts` (598-630): the sync-join stale purge at 1137/1156, and the post-merge denylist safety prune at 1367.
- `purge_hosts_from_staging` (633-647).
- `instance-denylist-cli.py` (190, 222, 227).
- `tests/active/test_ann.py:151`.
- `engine/server/db/jobs/tests/test-moderation-integration.py` (874, 907, 1022).

I found no test asserting an exact `purge_host_data` count dict. Every consumer reads keys with `.get` or sums them. The plan's "tests that assert exact count dicts gain the new key" therefore has no target today.

**Regression risk: low.** Summaries in the updater log and the CLI gain a `trending_ranks` key. One gap: `purge_host_data` matches `normalize_host(host)` exactly. The job takes its host list from `video_embeddings.instance_domain`, so rank rows carry the same spelling as the videos and are purged together. A host stored unnormalised (the `B.Example.` case in `test_updater_worker.py:728`) escapes the purge exactly as its videos already do.
</impact>
<impact path="engine/server/data/moderation.py" element="list_active_denied_hosts() (lines 137-145), reused by the job">
**What changes.** Nothing. The job reuses it.

**What depends on it.** The job's host-list subtraction. Two constraints:
- It reads `row["host"]` through `_row_value` (423-428), so the job's connection needs `conn.row_factory = sqlite3.Row`, as `load_denied_hosts` sets in `updater-worker.py:571`. Plain tuples raise TypeError.
- It returns lowercased hosts and an empty set when `instance_denylist` is missing, as in the smoke test's mini-prod.

**Regression risk: low.** The job's `SELECT DISTINCT instance_domain FROM video_embeddings` is compared raw against a lowercased set, so a mixed-case stored host would be asked even when it is denied. Serving moderation still filters its rows at read time.
</impact>
<impact path="engine/server/db/jobs/instance-denylist-cli.py" element="collect_post_check_counts (184-202) and run_purge (205-280) via purge_host_data">
**What changes.** Nothing in code. Its dry-run, precheck and finish logs gain `trending_ranks` counts, and a `--purge-now` removes the host's rank rows (A2). `precomputed_counts` (227-232) is keyed by table names from `_host_table_column_pairs`, so the new key flows through.

**What depends on it.** Operators reading its log blocks.

**Regression risk: none expected.** A host blocked without `--purge-now` keeps its rank rows. Serving moderation hides them, and the job no longer asks that host, so the rows age out after 3 days or go with the next updater safety prune.
</impact>
<impact path="engine/server/db/jobs/fetch-trending.py" element="NEW job script: argparse, phase 1 read, phase 2 concurrent fetch, phase 3 single write transaction, logging, exit status">
**What changes.** This is a new script. Style models:
- `recompute-popularity.py`: `sys.path` append of `script_dir.parents[1]`, `from data.time import now_ms`, `CompactHelpFormatter`, `DEFAULT_DB_PATH` imported from `server_config` after putting `api_dir` on `sys.path`, `--db` default `(repo_root / DEFAULT_DB_PATH).resolve()`, `logging.basicConfig(level=INFO, format="%(levelname)s %(message)s")`.
- `sync-whitelist.py:16-26` / `updater-worker.py:24-29`: `server_dir` inserted at `sys.path[0]`, stdlib `urllib.request.Request/urlopen` with `HTTPError`/`URLError`.

Flags: `--db`, `--concurrency 4`, `--timeout-ms 5000`, `--max-retries 3`. These match the updater defaults at `updater-worker.py:203-205`.

The hyphenated name cannot be imported, so tests load it through `importlib.util.spec_from_file_location`. That is the pattern of `_load_job` in `test_host_normalisation.py:78`, `test_updater_worker.py:61` and `test_sync_whitelist.py:70`.

Identity rule to mirror (`engine/crawler/src/videos-worker.ts:666`, `toStringId` at :836):
- `uuid ?? id` falls back to `id` only on null or undefined, not on an empty string.
- A string is kept only when it is non-empty, and a number becomes `String(n)`.

A naive Python `video.get("uuid") or video.get("id")` differs on `uuid == ""`. `str()` of a float or bool differs from JS. Reject `bool` explicitly, because `isinstance(True, int)`.

Connection setup:
- `PRAGMA busy_timeout` of about 10 s, as `merge-staging-db.py:121` sets.
- `row_factory = sqlite3.Row`, as `list_active_denied_hosts` needs.
- `ensure_trending_schema` before `BEGIN IMMEDIATE`.
- A raised `cache_size` (R1).
- The 3-day cutoff computed once from `now_ms()`.

**What depends on it.** The updater stage (new `run_cmd` call), the by-hand first fill (documented in `UPDATER_WORKER.md`), the new tests, and the smoke run.

**Regression risk: medium.**
- (a) Write-lock duration while the Engine serves (R1, see the `data/db.py` entry).
- (b) Run time under prod flags. `install-updater-service.sh:33` passes `--concurrency 5 --timeout-ms 15000 --max-retries 3`, not the 4/5000 the plan's R5 arithmetic assumes. One dead host can then cost about 60 s (4 × 15 s), so 200 dead hosts add about 40 min.
- (c) Exit status: per-host exceptions must be caught inside the worker function, so that a raise inside `ThreadPoolExecutor` cannot surface through `future.result()` as a job failure.
- (d) Repeated keys keep their first rank, as the plan states.
</impact>
<impact path="engine/server/db/jobs/merge-staging-db.py" element="connection setup (lines 118-128): busy_timeout 10000 + BEGIN IMMEDIATE, the model for the job's write">
**What changes.** Nothing. It is the precedent for the job's `PRAGMA busy_timeout = 10000` and its explicit `BEGIN IMMEDIATE` under Python's default isolation level.

**What depends on it.** Nothing new.

**Regression risk: none.** It is listed as a model only. `merge_rules.json` does not name `trending_ranks`, so the merge never touches the table.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="content reload (lines 460-462) and schema checks (ensure_schema_compatibility 189, ensure_whitelist_schema 257, ensure_content_schema 330)">
**What changes.** Nothing.
- A dataset rebuild deletes `videos`, `video_embeddings` and `channels` and reloads them. It does not touch `trending_ranks`, so the rank rows survive and simply re-join the catalogue at read time.
- Its column checks (154-160) are per named table, so an extra table in `whitelist.db` is not reported.

**What depends on it.** Nothing new.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/time.py" element="now_ms() (line 8)">
**What changes.** Nothing. It is the clock for `fetched_at` and for the 3-day cutoff.

**What depends on it.** The job, and tests that freeze time. To test the 3-day purge deterministically, monkeypatch the job module's imported `now_ms` name, not `data.time.now_ms`.

**Regression risk: none.**
</impact>
<impact path="engine/crawler/src/videos-worker.ts" element="video identity: toStringId(video.uuid ?? video.id) (lines 666, 836-840)">
**What changes.** Nothing. The job must reproduce this exactly so that rank rows join `videos.video_id`.

**What depends on it.** The Trending join `t.video_id = v.video_id AND t.instance_domain = v.instance_domain`.

**Regression risk: medium if copied loosely.** A mismatch (empty-string uuid, float or bool ids) silently drops rows from the join. The feed then shrinks with no error.
</impact>
<impact path="engine/server/data/random_videos.py" element="POPULAR_ORDER_BY (lines 15-22), ORDERED_FEED_ORDER_BY (23-36), new per-order join dict">
**What changes.**
- `ORDERED_FEED_ORDER_BY` drops `"hot": POPULAR_ORDER_BY` and gains `"trending": t.rank ASC, t.likes DESC, t.views DESC, t.video_id DESC, t.instance_domain DESC`, in the same triple-quoted style.
- A companion dict maps `popular`/`recent` to `""` and `trending` to the `JOIN trending_ranks t ON ...` fragment.
- `POPULAR_ORDER_BY` is deleted. Grep finds its only code readers at line 24 and `fetch_popular_videos` line 274. `search.py:86` has its own literal.
- The comment at line 14 ("video_id then instance_domain close every order") still holds for trending.

**What depends on it.**
- `fetch_ordered_page` (330).
- `tests/active/test_random_videos.py:97`, where `ORDERS` is read from `vars(random_videos)`. `EXPECTED` (91-95) must then hold a `trending` key and lose `hot`, otherwise `set(ORDERS) == set(EXPECTED)` at :159 fails.
- Docs that name `POPULAR_ORDER_BY`: `LAYER_PARAMS.md:144`, `OVERVIEW.md:18,103`, `roadmap.md:38`. The archived issues and ADR-0001 mention it as history.

**Regression risk: medium.** If a key exists in one dict and not the other, a missing join raises KeyError, or SQL names an undefined alias `t` ("no such column: t.rank"). Index both dicts by the same key set, or use `.get(order, "")` for the join.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_ordered_page() (lines 326-418)">
**What changes.** The join fragment is interpolated after the `JOIN videos v ... ON` lines (372-373) and before `LEFT JOIN channels c` (374). With an empty string, the popular and recent SQL is unchanged apart from whitespace. `_listing_conditions`, the recent-only predicate (332-335), the `LIMIT ? OFFSET ?` params order and the row dict (which already carries `popularity` at 412) are untouched.

**What depends on it.**
- `_handle_ordered_feed` (`similar.py:777`).
- The new `fetch_popular_videos`.
- `test_similar.py:756` (`_reference` on the read-only `dataset` connection).
- Every `test_random_videos.py` order test.

**Regression risk: medium (query plan).** For trending the planner must drive from the `trending_ranks` index, or each chunk sorts the whole join under `db_lock`. That happens up to 4 chunks per feed page, plus a 5000-row pool read on every mix request. Check `EXPLAIN QUERY PLAN` for `USE TEMP B-TREE FOR ORDER BY`, as the plan says. If the planner disagrees, use `CROSS JOIN` for trending only, which keeps the other orders' SQL unchanged.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_popular_videos() (lines 228-323)">
**What changes.** The body becomes `return fetch_ordered_page(conn, "trending", limit, 0, error_threshold, include_nsfw)`. Signature and row keys are identical, `popularity` included (317 vs 412). The docstring "Return most popular videos by likes/views" must change to say it is the head of the Trending order.

Behaviour changes:
- The rows now come out in rank order. The old outer query had no ORDER BY.
- The pool is empty while `trending_ranks` is empty.
- On a DB without the table it raises `no such table`.

**What depends on it.**
- `api/server.py:101,405` → `builder.py:114-118` (`fetch_popular_videos_filtered`) → `PopularVideosGenerator` (`candidates/popular_videos.py:53`).
- `tests/active/test_video.py:220`, which wires it into a strategy only the similars route uses, and that route does not run the layers.
- `tests/active/test_random_videos.py` lines 6, 13, 20-21, 27-28, 173-177, 268-274, 334, 404, 437, 440. These assert that the pool ranks by popularity, equals hot, or is led by X1 on a popularity fixture. All of them must be rewritten to the Trending head on fixtures that call `ensure_trending_schema` and seed ranks.

**Regression risk: medium.** Any caller passing a DB that never saw `ensure_trending_schema` now fails instead of returning rows. Among callers I found only test fixtures, and prod runs the schema at Engine start.
</impact>
<impact path="engine/server/data/search.py" element="sort map entry 'popularity' (line 86) and v.popularity select (79)">
**What changes.** Nothing. It is the one reader of `videos.popularity` left after `POPULAR_ORDER_BY` is deleted.

**What depends on it.** `sort=popularity` on search.

**Regression risk: none.** Listed so that the deletion is not mistaken for removing this order.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="FEED_MODES (105), ORDERED_FEED_MODES (107), _handle_ordered_feed docstring (767), unknown-mode 400 (1073-1075)">
**What changes.**
- `FEED_MODES = ("recommendations", "trending", "recent", "random", "popular")`. The tuple order is the 400's `allowed` order, per the comment at 104.
- `ORDERED_FEED_MODES = frozenset({"trending", "popular", "recent"})`.
- The docstring at 767 names trending.
- `mode=hot` falls into the existing 400. `_handle_ordered_feed` (759-806) is otherwise unchanged. With an empty table it returns an empty page with `seed_payload={}` after one chunk, because `len(chunk) < chunk_size` at 797.

**What depends on it.**
- `tests/active/test_frontend_feed_params.py:117-129`, which reads `FEED_MODES` from this file's AST.
- `tests/active/test_similar.py:711-738`, which reads both constants under the Engine interpreter.
- `client/frontend/src/data/feed-params.ts:5-6`, whose comment says it mirrors this tuple.

**Regression risk: low in code, high in tests** (see the `test_similar.py` entry). Old bookmarks or other clients sending `mode=hot` directly to the Engine get 400. The Client backend passes `mode` through unchanged.
</impact>
<impact path="engine/server/api/recommendations/builder.py" element="fetch_popular_videos_filtered (114-118) and PopularVideosDeps wiring (168-176)">
**What changes.** Nothing. It passes `error_threshold` and the per-request `include_nsfw` into `fetch_popular_videos`, which now forwards them to `fetch_ordered_page`. The positional order of `(conn, limit, error_threshold=, include_nsfw=)` matches.

**What depends on it.** The popular generator in every profile.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/candidates/popular_videos.py" element="PopularVideosGenerator.get_candidates (lines 34-136)">
**What changes.** Nothing.
- An empty pool returns `[]` at line 55.
- The pool is read under `db_lock` on every call (52-53). There is no cache, so a job commit shows on the next request.
- Caps (`max_per_instance` 5 in home) still apply.
- The scoring reads crawled `views`/`likes` (`scoring.py:53`), not the listed ones and not `popularity`. `popularity` in the row is carried but unread; grep finds no `row["popularity"]` reader in the api.

**What depends on it.** The mixer.

**Regression risk: low.** The pool composition changes deliberately, and the timing logs keep their shape. With up to about 1,764 hosts × rank, a `pool_size` of 5000 covers roughly the first three rank rounds of catalogued rows.
</impact>
<impact path="engine/server/api/recommendations/mixer.py" element="gather allocation _resolve_fetch_limits (156-213) and soft-mix fill (367-413)">
**What changes.** Nothing in code. The plan claims "an empty layer ... `_soft_mix_candidates` fills by ratio from the other layers" and plans a test that "the mix still answers a full batch from an empty ranks table". That claim holds only for some profiles.
- Gathering is allocated up front by `gather_ratio` × `batch_size × overfetch_factor` (176-211), and the fill at 405-412 can only reuse candidates already gathered.
- For the `home` profile with likes (`server_config.py:84-150`: batch 48, `overfetch_factor` 1, popular `gather_ratio` 0.1), popular gets 5 of the 48 slots after the remainder pass. With an empty popular layer, at most 43 candidates exist, so the page comes back short.
- For `guest_home` (overfetch 2, popular 0.2 of 96 ≈ 19), the other layers gather about 77, so the batch is full.

**What depends on it.** Every keyed home request with likes during cold start or after a failed fill.

**Regression risk: high for R2's claim and its planned test.** A test with likes on `home` would fail, and prod keyed users get short home pages until the first fill. The test must pick the profile it proves, or the operator must accept short pages, or the plan must add a fill step. This is not a code change in this file unless the operator chooses one.
</impact>
<impact path="engine/server/api/server_config.py" element="RECOMMENDATION_PIPELINE popular layers (105-115, 193-201, 241-250, 303-311), DEFAULT_POPULAR_POOL_SIZE (68), DEFAULT_DB_PATH (414)">
**What changes.** Nothing. `pool_size` 5000 now means "Trending head". `DEFAULT_DB_PATH` is the job's `--db` default.

**What depends on it.** The mixer arithmetic above, and the job's default path.

**Regression risk: none in code.** Its comments call the layer "popular", which stays accurate as the layer name.
</impact>
<impact path="engine/server/data/db.py" element="connect_db (77-82) and connect_readonly_db (85-94): no busy timeout set">
**What changes.** Nothing. The Engine's shared `db` and its read-only `search_db` use sqlite's default 5 s busy wait.

**What depends on it.** R1. While the job holds RESERVED:
- Engine writes (interaction-event ingest, `/api/video` refresh) wait up to 5 s while holding `db_lock`, which stalls every route behind that lock.
- At commit, or on a cache spill to EXCLUSIVE, every reader on both connections also waits. A wait longer than 5 s raises `database is locked`, and on the recommendations routes that surfaces as a 500.

The `statement_deadline` progress handler (`db.py:45-65`) bounds statement VM steps, and probably not time spent in the busy handler, so it does not cap this wait. This is unverified.

**Regression risk: medium.** The job's transaction length is the control. The plan's logging of the transaction ms and its fallback (escalate, do not split silently) cover it.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main(): new trending stage between the service-start finally (1414-1427) and run_similarity_stage (1438-1444)">
**What changes.**
1. After the outer `finally` that starts the Engine and releases the deploy lock, and before `precompute_cmd`/`run_similarity_stage`, add `run_cmd([args.python_bin, (script_dir / "fetch-trending.py").as_posix(), "--db", prod_db.as_posix(), "--concurrency", str(args.concurrency), "--timeout-ms", str(args.timeout_ms), "--max-retries", str(args.max_retries)], cwd=repo_root)`. This is the shape of the `recompute-popularity.py` call at 1376-1385.
2. Wrap the call in `try/except Exception`, which catches `CalledProcessError` from `run_cmd`'s `check=True` at :385. Log the failure and set a flag.
3. After `run_similarity_stage` returns, raise `RuntimeError("trending stage failed")` if the flag is set. This stays inside `with single_run_lock` and the outer `try`, so the temp-file `finally` (1445-1450) runs and "worker completed" (1453) is not logged.

**What depends on it.**
- The sync-join early return at 1328 precedes the stage, so a no-change sync-join run skips trending (R7, accepted).
- `--fail-after-merge-before-similarity` and the other injected failures raise inside the service `try`, before the stage, so it is skipped then. That matches today's similarity behaviour.
- `tests/active/test_updater_worker.py`:
  - `test_main_runs_similarity_stage_after_service_start` (323-342) scans the service `try` for constants and calls. The stage must stay outside that `try`.
  - `_run_main` (654-698) runs `main` with `--fail-after-merge-before-similarity`, so it never reaches the stage. Its assertion that the start is the last child call stays valid.
- `test-orchestrator-smoke.py` `parse_stage_durations` (507-532) pairs `run:`/`done:` lines, and a failed `run_cmd` logs `run:` with no `done:`. It pairs by FIFO `pending.pop(0)`, so a failed trending run with no `done:` could shift the next stage's duration onto the wrong key, unless trending is in `marker_to_stage`. This only affects that smoke script.

**Regression risk: medium.**
- The run gains the fetch time before similarity starts. With prod flags 5/15000/3, see the job entry.
- An exception raised by the similarity stage replaces the trending RuntimeError. The trending failure is then only in the log, which the plan accepts.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main(): required-files tuple (lines 1091-1106)">
**What changes.** The plan does not mention it. Adding `script_dir / "fetch-trending.py"` here would make a missing job fail the run at start rather than at the stage, as is done for `recompute-popularity.py` (1101).

**What depends on it.**
- `_run_main` in `tests/active/test_updater_worker.py:654` uses the real `script_dir`, so the new file exists and the check passes.
- `test-orchestrator-smoke.py` uses the real jobs dir.

**Regression risk: low.** If it is not added, a missing script surfaces as the stage failure, logged and non-zero after similarity, which is also acceptable. Either way, record the choice.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="purge_hosts (598-630), purge_hosts_from_staging (633-647), load_denied_hosts (568-576)">
**What changes.** Nothing in code. Their logged summaries ("sync-join stale purge", "post-merge denylist safety prune", "staging denylist prune") gain the `trending_ranks` key when it is non-zero.
- The safety prune runs before the trending stage, inside the stopped window. A host denied before the run therefore loses its ranks, and the job does not re-ask it, because the job re-reads the denylist itself.
- A host denied while the job is fetching can be written back in phase 3. Serving moderation hides those rows, and they age out or go at the next prune.

**What depends on it.** Operators reading the logs.

**Regression risk: low.**
</impact>
<impact path="engine/install-updater-service.sh" element="UPDATER_TIMER_ONCALENDAR default 'Fri *-*-* 20:00:00' (line 32), timer unit (361-374), UPDATER_FLAGS (line 33)">
**What changes.** Nothing in this build as planned. It contradicts the requirements' premise. The installed timer runs weekly (`OnCalendar=Fri *-*-* 20:00:00`, `Persistent=false`), not daily. The "daily (`OnUnitInactiveSec=1d`)" in `UPDATER_WORKER.md:222,227-230`, `DATA_BUILD.md:26` and plan 45 line 83 is stale. Consequences:
- With the 3-day age-out, a host that fails in a run already has rows about 7 days old. The same run's age purge deletes them, so "a host that fails keeps its previous list" and "one bad run never empties Trending" do not hold.
- Trending can be up to 7 days old on top of the instances' 7-day windows. ADR-0010 and CONTEXT.md say "at most a day".
- The prod flags `--concurrency 5 --timeout-ms 15000 --max-retries 3` are what the stage inherits.

**What depends on it.** The job's purge cutoff, the docs, and the operator's expectations. `tests/active/test_install_updater_service.py` pins this installer's dry-run output, so changing the cadence touches that test.

**Regression risk: high (requirements conflict).** This needs an operator decision: change the timer to daily, lengthen the age-out to more than 7 days, or accept weekly. It is not a silent build choice.
</impact>
<impact path="scripts/install-service.sh" element="UPDATER_TIMER_ONCALENDAR default (line 41) passed as --updater-oncalendar (line 231)">
**What changes.** Nothing unless the operator changes the cadence. The central installer carries the same weekly default and passes it to `install-updater-service.sh`.

**What depends on it.** `tests/active/test_install_service.py` and `test_install_updater_service.py` (the `via_central` case).

**Regression risk: none unless the cadence is changed.** If it is, both installers and their tests move together.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="run_orchestrator (418-483), assert_worker_log required_markers (486-504), parse_stage_durations marker_to_stage (507-532)">
**What changes.** The script is outside `tests/active` and runs the real updater on a mini-prod seeded from real hosts (`tests/test-instances.json`: videovortex.tv, diode.zone, …). The new stage will make real HTTP requests to those hosts. The crawl stages already do, so the network is already assumed.
- Add `"fetch-trending.py": "trending_fetch"` to `marker_to_stage`, so durations pair correctly.
- Optionally add it to `required_markers`.
- The mini-prod has no `instance_denylist`, which `list_active_denied_hosts` tolerates.
- The job's `ensure_trending_schema` creates the table there. The before/after checks use only the `merge_rules.json` tables and `PRAGMA integrity_check`, so the new table does not trip them.

**What depends on it.** `ORCHESTRATOR_SMOKE_TEST.md`.

**Regression risk: low.** A smoke run is slower by the fetch time. Host failures do not change the job's exit code, so the expected-success scenarios stay green.
</impact>
<impact path="engine/server/db/jobs/tests/test-moderation-integration.py" element="purge_host_data calls (874, 907, 1022) and its own schema (181)">
**What changes.** Nothing. It reads `counts.get("videos", 0)` and logs the dicts. Its DB does not create `trending_ranks`, so the new key is absent.

**What depends on it.** Nothing new.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/feed-params.ts" element="FEED_MODES (line 6) and parseFeedMode (50-52)">
**What changes.**
- `FEED_MODES = ["recommendations", "trending", "recent", "random", "popular"] as const`. `FeedMode` follows from it.
- `parseFeedMode` maps the literal `"hot"` to `"trending"` before the lookup.
- Both `resolveFeedParams`'s `?mode=` path (22) and `readStoredFeedParams` (58) call it, and so does `chooseFeedMode` (`pages/videos/index.ts:917`), so one line covers the URL, storage and a stale button.
- A stored `"hot"` is not rewritten in storage until the next click, so the alias must stay as long as old storage may exist.
- The comment at line 5 stays true.

**What depends on it.**
- `tests/active/test_frontend_feed_params.py`: the bundle's `FEED_MODES` must equal the Engine tuple at :145-150.
- The stored-hot and `?mode=hot` cases at 215-255, 270, 301 and 345 currently assert `["hot"]`.
- The committed `dist` bundle `client/frontend/dist/assets/key-rejected-*.js`, which embeds this module.

**Regression risk: low in code.** The tests must be rewritten (see their entry), and dist must be rebuilt (see the dist entry).
</impact>
<impact path="client/frontend/index.html" element="feed-mode switcher button (line 41)">
**What changes.** `data-feed-mode="hot"` becomes `data-feed-mode="trending"`, and the label `Hot` becomes `Trending`.

**What depends on it.**
- `pages/videos/index.ts:56,132` binds every `[data-feed-mode]` button.
- `client/frontend/dist/index.html:50` is generated from this file and must match a fresh build (`test_frontend_dist.py`).

**Regression risk: low.**
</impact>
<impact path="client/frontend/videos.html" element="feed-mode switcher button (line 41)">
**What changes.** Same edit as `index.html`.

**What depends on it.** `client/frontend/dist/videos.html:50` and `test_frontend_dist.py`.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="pickSample comment (line 248); chooseFeedMode (916-926)">
**What changes.** The comment "(hot, recent and popular included)" names trending. Code is unchanged: `chooseFeedMode` already goes through `parseFeedMode`, and only `random` is shuffled.

**What depends on it.** `test_frontend_videos_page.py`, which checks only `recommendations` and is unaffected. A comment-only edit still changes the content hash of the bundled asset, so `dist` must be rebuilt.

**Regression risk: none in behaviour.**
</impact>
<impact path="client/frontend/dist/index.html" element="committed build output: dist/index.html, dist/videos.html and dist/assets/* (feed-params is bundled into key-rejected-*.js; the page script into index-*.js)">
**What changes.** The plan says "`dist/` is not edited (A5)". `tests/active/test_frontend_dist.py:17-25` requires the committed dist to equal a fresh `vite build`: the same hashed asset names and byte-identical HTML pages. It fails with "client/frontend/dist is stale; run the frontend build and commit dist" after any source change. The rebuilt dist must therefore be generated and committed. It must not be hand-edited, and it must not be left alone. `client/frontend/README.md:38` already says dist reaches prod only after a rebuild.

**What depends on it.** Prod serving, which serves dist, so without a rebuild prod keeps the Hot button. `test_frontend_dist.py` depends on it too.

**Regression risk: medium if A5 is read literally.** The suite goes red, and prod keeps sending `mode=hot`, which the Engine now answers 400. The 400 reaches the browser as an error page for every visitor whose dist still says hot.
</impact>
<impact path="client/backend/server.py" element="query/body allowlists for /recommendations and /videos/similar (96-97, 116-117)">
**What changes.** Nothing. `mode` is allowlisted and forwarded unchanged, so the value is not validated here. The Engine's 400 for `mode=hot` passes through with its status and body.

**What depends on it.** `tests/active/test_server.py:1444-1470`.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_random_videos.py" element="module docstring (1-45), EXPECTED (91-95), ORDERS (97), _feed_db/_signal_db/_two_video_db fixtures, test_consecutive_pages... (156-177), test_a_page_holds... (180-187), SIGNAL_EXPECTED + test_hot_pages_and_the_popular_pool... (207-274), _reads (329-337), NSFW_READS/NSFW_ORDERED_READS (401-410), test_limits_count_only_allowed_rows (434-444), test_filtered_pages... (447-463)">
**What changes.**
- Every fixture that reaches trending or `fetch_popular_videos` must call `ensure_trending_schema` and seed `trending_ranks` rows. The tests are parametrised over `ORDERS`, so `trending` reaches `_feed_db` and `nsfw_conn` automatically.
- `EXPECTED["hot"]` is replaced by a hand-derived `trending` order: rank interleave, then listed likes, views, `video_id` and `instance_domain`.
- `test_a_page_holds_exactly...` assumes every embedded row is served (186). For trending only ranked, catalogued rows are served, so that test needs a trending-specific expected set, or rank rows for every label. Labels N (unembedded) and E (at threshold) still test the filters.
- Lines 173-177, 268-274, 334, 404 and 437-440 assert "hot is the order fetch_popular_videos ranks by". They become "the popular pool equals the Trending head".
- `"hot"` literals at 335, 405, 410 and 448 become `"trending"`.
- The docstring bullets at 5-6, 13, 20-21 and 27-28 are rewritten.
- Rank fixtures should include at least one ranked row absent from the catalogue (catalogue-only), a tie on rank broken by listed likes, then views, then `video_id`, then domain, and an end with no fallback.

**What depends on it.** `tests/config.json` `test_groups["test_random_videos.py"]` gains `engine/server/data/trending.py`.

**Regression risk: medium.** This is the largest test rewrite. A fixture that forgets the schema fails with "no such table". One that seeds ranks equal to the popularity order would pass by coincidence and prove nothing, so derive the trending order to differ from the popularity order.
</impact>
<impact path="tests/active/test_similar.py" element="REQUIRED_MODES/UNKNOWN_MODES/SEEDED_MODES (695-698), ordered paging test (819-850), NSFW_LISTINGS + listing test (864-921), PRE_BUILD comment (802)">
**What changes.**
- `REQUIRED_MODES` swaps `hot` for `trending`. `hot` should join `UNKNOWN_MODES`, so the 400 for it is proven (A3). It may also go into `SEEDED_MODES`, since a seeded request ignores mode.
- `NSFW_LISTINGS` `"mode=hot"` becomes `"mode=trending"`, and the comment at 802 changes.

These tests run against the session Engine (`conftest.py:108`) on the repo's live `engine/server/db/whitelist.db`, and `dataset` (`conftest.py:189`) reads the same file read-only.
- The Engine creates `trending_ranks` empty on boot.
- `test_an_ordered_mode_s_page...` for trending asserts `len(reference) >= 4 * FEED_PAGE` (825) and three full 12-row pages (845).
- The NSFW test asserts that `mode=trending&nsfw=1` serves at least one flagged row (917), and that unfiltered pages are non-empty (920).

All of these fail on an empty table. The plan names no seeding step, and the tests may not reach real hosts.

**What depends on it.** The live dev DB's content. These tests are also in `tests/config.json` `test_groups["test_similar.py"]`, which should gain `engine/server/data/trending.py`.

**Regression risk: high.** The build must decide how the dev DB gets ranks. Options:
- a by-hand dev fill with the job, which is a network run outside the tests, and which needs ranked NSFW rows among the first 96 for the control at 917;
- a deterministic seed the tests write into the live DB, which is a write to a shared file;
- moving the trending variants onto a fixture Engine.

Each option needs to be chosen, not improvised.
</impact>
<impact path="tests/active/test_frontend_feed_params.py" element="docstring (3-15), test_the_client_s_feed_modes_are_the_engine_s (145-150), stored/URL hot cases (215-255), NSFW read harness (270-345)">
**What changes.**
- The modes come from the Engine's AST (117-129), so the parametrised cases follow automatically. The control comment at 147 names the five modes and needs `trending`.
- The cases that store `"hot"` or pass `?mode=hot` and assert `["hot"]` (221-229, 250-255, 301, 345) become the alias proof: stored `hot` → `["trending"]` and `?mode=hot` → `["trending"]`. An unknown value still gives `["recommendations"]`.
- The control at 215 (a bare JSON string `"hot"` is not a stored choice) must still give `["recommendations"]`, which checks that the alias applies only inside the object.
- The `?random=1` precedence cases (11) keep their meaning.

**What depends on it.** `tests/config.json` entry 231-236, unchanged.

**Regression risk: medium.** Several literal `["hot"]` assertions flip to `["trending"]`. A careless rename could turn the alias proof into a plain-mode check.
</impact>
<impact path="tests/active/test_server.py" element="test_a_keyed_hot_page_drops_the_blocked_channel... (1444-1470) and docstring line 125">
**What changes.** Optional rename of `mode=hot` to `mode=trending` and of the test name and docstring. The stand-in Engine (`_hot_engine`) answers any mode and the gateway forwards `mode` verbatim, so the test passes either way.

**What depends on it.** Nothing else.

**Regression risk: none.** The plan lists it as "updated". Keep the rename for vocabulary only.
</impact>
<impact path="tests/active/test_updater_worker.py" element="test_main_runs_similarity_stage_after_service_start (323-342), _run_main (654-698), module docstring (1-23)">
**What changes.** The existing tests should pass unchanged as long as the stage sits after the service `try`'s `finally` and before `run_similarity_stage`. New tests:
- **Stage position.** An AST check that the `fetch-trending.py` `run_cmd` call is after `service_try.end_lineno` and before the `run_similarity_stage` call.
- **Failure behaviour.** With `subprocess.run` faked to fail only on `fetch-trending.py`, similarity still runs and `main` ends in RuntimeError. `_run_main` cannot be reused for this, because it injects `--fail-after-merge-before-similarity`. A variant is needed that reaches the stage: a sync-join with one stale host and no `--fail-*` flag, and a faked `run_similarity_stage` or precompute child.

**What depends on it.** `tests/config.json` `test_groups["test_updater_worker.py"]` gains the job file.

**Regression risk: low for existing tests.** The new harness has to avoid running a real precompute.
</impact>
<impact path="tests/active/test_popular_videos.py" element="stub fetch_popular_videos (line 40)">
**What changes.** Nothing. It injects a lambda pool, so the data source does not matter.

**What depends on it.** Nothing new.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_video.py" element="similars_stack wiring server.fetch_popular_videos (line 220)">
**What changes.** Nothing. The strategy it builds serves the similars route, which does not run the layer generators, so the fixture DB's lack of `trending_ranks` is never hit.

**What depends on it.** Nothing new.

**Regression risk: low.** If a future change routes up-next through the popular layer, this fixture needs the schema.
</impact>
<impact path="tests/active/test_frontend_dist.py" element="test_the_committed_dist_holds_exactly_the_assets_a_fresh_build_emits_and_no_about_override (17-25)">
**What changes.** Nothing in the test. It fails until `client/frontend/dist` is rebuilt and committed after the `feed-params.ts`, HTML and `index.ts` edits.

**What depends on it.** Plan A5's "dist is not edited". Read that as "not hand-edited", with a rebuild required.

**Regression risk: medium** (see the dist entry).
</impact>
<impact path="tests/active/conftest.py" element="engine session fixture (107-146) and dataset fixture (188-193) on the live WHITELIST_DB (line 36)">
**What changes.** Nothing in code. On its first start after this build, the session Engine runs `ensure_trending_schema` against the repo's live dev `whitelist.db`, which creates an empty table there. `dataset` is read-only and sees it.

**What depends on it.** Every session-Engine test. Only the trending listings (`test_similar.py`) and keyed home mixes with likes (short by popular's share) observe the empty table.

**Regression risk: medium.** It is the root of the `test_similar.py` entry.
</impact>
<impact path="tests/active/test_fetch_trending.py" element="NEW test module(s) for the job, order, pool/mix, purge and frontend alias (name suggested; the plan does not fix it)">
**What changes.** New tests under `tests/active` that never reach real hosts:
- **Job loading.** The job loaded by `importlib` the `_load_job` way.
- **Fetch through a monkeypatched `urlopen`.** Good body, non-2xx (`HTTPError`), timeout (`socket.timeout`/`URLError`), garbage body, and retry count equal to `max_retries + 1` attempts.
- **Run on a temp DB through an injected per-host fetcher.** Replace, keep-on-fail, 3-day purge with a patched `now_ms`, a denylisted host never asked, at most 100 rows per host, a duplicate key keeping its first rank, uuid/id fallback per `toStringId`, and non-zero exit on DB or transaction failure only.
- **Purge.** `purge_host_data` removes rank rows.
- **Mix with an empty ranks table.** State which profile the full-batch claim holds for (see the mixer entry).

**What depends on it.** `tests/config.json` needs a `test_groups` entry naming `engine/server/db/jobs/fetch-trending.py`, `engine/server/data/trending.py` and `engine/server/data/moderation.py`.

**Regression risk: low.** A test that sleeps through real timeouts would slow the suite, so inject the timeout.
</impact>
<impact path="tests/config.json" element="test_groups (lines 14-385): entries for test_random_videos.py (106-111), test_similar.py (54-70), test_updater_worker.py (278-284), new job test">
**What changes.**
- New source files join the groups of the tests that cover them: `data/trending.py` in `test_random_videos.py`, `test_similar.py` and the new tests; `fetch-trending.py` in the new job test and in `test_updater_worker.py`.
- A `test_groups` entry for each new test file.

**What depends on it.** The suite validation tooling that maps sources to tests (`tests/last_test_validation.json` is its output).

**Regression risk: low.** A missing mapping means a change to `trending.py` may not trigger the tests that cover it.
</impact>
<impact path="tests/last_test_validation.json" element="generated validation record (contains 'hot')">
**What changes.** It is regenerated by the test validation run. Do not hand-edit it.

**What depends on it.** Nothing in the build.

**Regression risk: none.**
</impact>
<impact path="tests/archive/37_local_signal/test_random_videos.py" element="archived suite asserting the popularity pool (line 156)">
**What changes.** Nothing. It is archived and not in the `tests/active` run (`tests/config.json` `"archive"`). It would fail if run, because it expects the old pool.

**What depends on it.** Nothing.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/handlers/video.py" element="/api/video popularity write (around 379-405)">
**What changes.** Nothing. It still writes `videos.popularity`, which only search reads now, as the operator decided.

**What depends on it.** Search.

**Regression risk: none.**
</impact>
<impact path="CONTEXT.md" element="glossary entries Feed mode (16), Hot (17), Trending (21), Popular (22)">
**What changes.**
- 16: "hot" becomes "trending".
- 17: the **Hot** entry is removed.
- 21: drop "decided in issue 38 and not built yet; it will replace **Hot**", and say the order is stored per host in `trending_ranks` and filled by the updater's trending stage.
- 22: "which uses the Hot order" becomes "the Trending order".
- The Trending entry's freshness must match the real cadence (see the `install-updater-service.sh` entry).

**What depends on it.** All docs that link to the glossary.

**Regression risk: none.**
</impact>
<impact path="docs/project/issues/38-hot-trending-by-growth.md" element="Status line and location">
**What changes.**
- The Status line becomes `Status: enhancement, complete`.
- The file moves to `docs/project/issues/archive/`. The tracker convention is in `docs/project/issue-tracker.md` and `triage-labels.md`.

**What depends on it.**
- `docs/project/issues/42-tags-on-cards-and-tag-search.md:58` cites this issue by name.
- ADR-0010 line 4 cites its path.

Both become archive paths.

**Regression risk: none.**
</impact>
<impact path="docs/project/adr/0010-trending-from-source-instances.md" element="Decision 1 'Once a day' (25), consequences 'at most a day old' (43)">
**What changes.** The text assumes a daily updater, but the installed timer is weekly. Either the operator moves the timer to daily, or a dated note records the real cadence. ADRs are records, so add a note rather than rewrite the decision.

**What depends on it.** CONTEXT.md **Trending**.

**Regression risk: none.**
</impact>
</impacts>


## Documentation to update

- [x] `CONTEXT.md` - - Line 16 (**Feed mode**): "hot" becomes "trending".
- Line 17: remove the **Hot** entry.
- Line 21 (**Trending**): drop "decided in issue 38 and not built yet; it will replace **Hot**". Say it is stored per host in `trending_ranks`, refreshed by the updater's trending stage, empty until the first fill, and as fresh as the last updater run (state the real cadence).
- Line 22 (**Popular**): "uses the Hot order" becomes "uses the Trending order".
- [x] `README.md` - Line 44: the five modes become Recommendations, Trending, Recent, Random and Popular, and "Hot, Recent and Popular are global orders" names Trending.
- [x] `client/README.md` - - Line 28: "home, up-next, hot, recent and popular pages" names trending.
- Line 29: "fixed-order feeds (hot, recent, popular)" names trending.
- [x] `client/frontend/README.md` - - Line 10: mode list and "Hot, Recent and Popular are shown in the Engine's order" name Trending. Add that a `?mode=hot` URL or a stored `hot` opens Trending.
- Line 14: "In Hot, Recent and Popular" names Trending.
- Line 38: note that the rebuilt `dist` must be committed (`tests/active/test_frontend_dist.py`).
- [x] `engine/server/README.md` - - Line 26: the `mode` value list, the 400 example `allowed` list (`["recommendations","trending","recent","random","popular"]`), "`random=1` wins over `mode=hot|recent|popular`" and "Hot, popular and recent are global orders" name trending. State that `mode=hot` now answers 400, and that Trending is empty until the first fill.
- Line 29: the NSFW filter's mode list.
- Line 31: "a slow hot or popular page".
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - - Line 7: "The `hot`, `popular` and `recent` feeds" names trending.
- Lines 17-18: the ordered-feeds bullet and the **hot** sub-bullet become **trending**: an inner join to `trending_ranks`, ordered by rank, then listed likes, listed views, `video_id` and `instance_domain`. It holds catalogue rows only, is finite with no fallback, and is empty until the first fill.
- Line 22: "All three rank embedded videos only" still holds; add that trending serves only ranked ones.
- Line 23: "For hot, recent and popular".
- Line 103: the popular layer's Source is the first `pool_size` rows of the Trending order (`fetch_popular_videos` → `fetch_ordered_page(conn, "trending", ...)`), not `POPULAR_ORDER_BY`. It is empty while `trending_ranks` is empty. With likes on the `home` profile, the batch is then short by the layer's gather share.
- Line 134: "popular pool: top by `popularity`...".
- Lines 173 and 177: "(hot, popular, recent)" and "In the hot, popular and recent feeds".
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - Line 144, popular layer **Source**: replace "top videos by `popularity` ... (`POPULAR_ORDER_BY` ...)" with the Trending order head. Say that the layer returns nothing until the ranks table is filled, and that `pool_size` 5000 covers roughly the first three rank rounds of catalogued rows.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - Line 29: the node `G3[popular<br/>popularity, then likes]` becomes the Trending order (for example `trending rank`).
- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - - Purpose list (10-16): add "refresh Trending ranks".
- Execution Order: add a stage between step 12 (start) and step 13 (similarity). It runs `fetch-trending.py --db <prod> --concurrency --timeout-ms --max-retries` with the Engine serving. Host failures are logged and are not fatal. A job failure is logged, similarity still runs, and the run exits non-zero afterwards.
- Note that the no-change `--sync-join-whitelist` early return skips the stage.
- Add the by-hand first-fill command.
- Logs section: the job's lines (hosts asked/answered/failed, rows written, rows purged by age, transaction ms).
- Systemd Run (222, 227-230): correct "daily schedule" and `OnUnitInactiveSec=1d` to the installed `OnCalendar` (weekly Friday 20:00), or to whatever the operator decides.
- Mention the write transaction's effect on serving.
- [x] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - Purpose list (8-17): add the trending stage between the service start and the similarity stage. Note that it contacts the test instances' real hosts and that host failures do not fail the run.
- [x] `DATA_BUILD.md` - - Line 24: the pipeline sequence gains "trending ranks" after the ANN rebuild and before the similarity precompute.
- Line 26: "Timer runs daily (`OnUnitInactiveSec=1d`)" is stale; state the installed cadence.
- Optionally add the first-fill command near §7.
- [x] `DEPLOYMENT.md` - - Line 87: "the popular ordering (the recommendation mix's popular layer and the hot feed mode) ... sort on crawled `popularity`" becomes: the mix's popular layer and the Trending mode use `trending_ranks`; the popular mode uses crawled likes and views.
- Line 191 (updater timer): add the trending stage after the Engine restart.
- Line 451: "The hot and popular feed modes sort every embedded video ... (hot leads with `popularity`...)" becomes Trending, driven by the ranks index. Note the first-fill step and the job's write lock in the deploy notes.
- [x] `docs/project/roadmap.md` - - Line 38: the item about `v.likes + sig.likes_count` in `POPULAR_ORDER_BY` (the mix's popular layer and the hot feed) is obsolete. `POPULAR_ORDER_BY` is deleted; drop or reword the item.
- Line 39: "ordered feeds (hot, recent, popular)" names trending.
- Lines 23 and 64 (delivered F3-M3 history): leave them, or note that Trending replaced Hot.
- Add a Delivered entry for issue 38, ADR-0010 and the plan.
- [x] `docs/project/issues/38-hot-trending-by-growth.md` (Status and move done by the operator; path references updated in this step) - Set `Status: enhancement, complete` and move the file to `docs/project/issues/archive/`. Update references to its path in issue 42 (line 58) and in ADR-0010 (line 4) if the tracker convention requires it.
- [x] `docs/project/adr/0010-trending-from-source-instances.md` - Line 25 "Once a day" and line 43 "at most a day old" assume a daily updater, but the installed timer is weekly. Add a dated note that records the operator's cadence decision. Do not rewrite the decision.
- no update — `peertube-browser-service-review.md`: a point-in-time external review pinned to a 105-commit snapshot that already omits the similarity stage, so it is not kept current; its line 42 lists what the updater runs and does not say "only", so it stays true as a snapshot. Optional. Line 42 describes what `updater-worker.py` does ("runs four Node crawler CLIs ... restarts the engine"). It now also fetches each catalogue host's trending page over HTTPS. Update the sentence if this review is kept current.

## Implementation plan

## Draft implementation: Trending from source instances (issue 38)

### Passes and decisions

I read `random_videos.py` in full, `recompute-popularity.py`, `moderation.py:100-339`, `feed-params.ts`, `updater-worker.py:1-60, 370-390, 1320-1457`, `similar.py:100-111`, `server.py:95-110, 326-339`, `mixer.py:17-151`, `conftest.py:20-199`, `test_similar.py:690-921` and `test_updater_worker.py:640-704`.

**Pass 1** checked the draft against the plan, the requirements and the settled impact inventory. Three conflicts were open, and the inventory marks each one as not a build choice. I put all three to the operator:
- **Cadence vs age-out.** The installed timer runs weekly (`Fri 20:00`). With a 3-day age-out, a host that fails in a run loses its rows in that same run.
  - **Decision:** keep the weekly timer and raise the age-out to **10 days**. A host that fails one weekly run keeps its list. A host that fails two runs loses it. The timer, the installers and their tests do not change. ADR-0010 gets a dated note, and CONTEXT.md, UPDATER_WORKER.md and DATA_BUILD.md state weekly freshness and the 10-day age-out. This replaces the requirements' "3 days" everywhere.
- **Live-DB trending tests.**
  - **Decision:** a session-scoped seed fixture in `conftest.py` writes deterministic `trending_ranks` rows into the live dev `whitelist.db` before the session Engine starts.
- **Empty popular layer on `home` with likes.**
  - **Decision:** accept short pages until the first fill. `mixer.py` does not change. The R2 test proves that `guest_home` returns a full batch and that `home` with likes returns a non-empty page, short by popular's gather share. The docs say so.

**Pass 2** re-checked against everything with those three decisions in place. It converged: every requirement and every impact entry has a home below.

Two choices differ from the plan's wording, and both stay inside what the plan allowed:
- **Join placement.** The Trending join is a per-order **FROM source** (`trending_ranks t CROSS JOIN video_embeddings e ON …`), not a fragment after the `videos` join. The plan named CROSS JOIN as its query-plan fallback. I adopted it up front because a fragment placed after `JOIN videos v` can never make `t` the driving table, and `CROSS JOIN` makes the index walk true by construction instead of leaving it to the planner. Popular and recent get the source string `video_embeddings e`, so their SQL is byte-identical to today.
- **dist.** "dist is not edited" is read as **not hand-edited**. `client/frontend/dist` is regenerated with the frontend build and committed, because `test_frontend_dist.py` requires it and prod serves dist.

### Module map

| File | Change | Req |
|---|---|---|
| `engine/server/data/trending.py` | NEW: `ensure_trending_schema` | Storage |
| `engine/server/api/server.py` | import and startup call | Storage |
| `engine/server/data/moderation.py` | one pair added to `_host_table_column_pairs` | A2 |
| `engine/server/db/jobs/fetch-trending.py` | NEW job | Fetch, A1, A2 |
| `engine/server/data/random_videos.py` | `trending` order and source; `POPULAR_ORDER_BY` deleted; `fetch_popular_videos` delegates | A3, A4 |
| `engine/server/api/handlers/similar.py` | `FEED_MODES`, `ORDERED_FEED_MODES`, docstring | A3 |
| `engine/server/db/jobs/updater-worker.py` | trending stage; required-files entry | A6 |
| `client/frontend/src/data/feed-params.ts` | mode list and `hot` alias | A5 |
| `client/frontend/index.html`, `videos.html` | button | A5 |
| `client/frontend/src/pages/videos/index.ts:248` | comment only | A5 |
| `client/frontend/dist/**` | regenerated by `vite build` and committed | A5 |
| `engine/server/db/jobs/tests/test-orchestrator-smoke.py` | `marker_to_stage` entry | smoke |
| tests and `tests/config.json` | see Tests | all |
| docs | see Documents | A7 |

Untouched, as the inventory says: `builder.py`, `popular_videos.py`, `mixer.py`, `server_config.py`, `db.py`, `search.py`, `handlers/video.py`, `client/backend/server.py`, `merge-staging-db.py`, `sync-whitelist.py`, both installers.

### `engine/server/data/trending.py` (new)

```python
"""Provide trending ranks runtime helpers."""

from __future__ import annotations

import sqlite3


def ensure_trending_schema(conn: sqlite3.Connection) -> None:
    """Create the table of each catalogue host's own trending list and the index the Trending order walks."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trending_ranks (
          instance_domain TEXT NOT NULL,
          video_id TEXT NOT NULL,
          rank INTEGER NOT NULL,
          likes INTEGER NOT NULL,
          views INTEGER NOT NULL,
          fetched_at INTEGER NOT NULL,
          PRIMARY KEY (instance_domain, video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_trending_ranks_order
          ON trending_ranks (rank ASC, likes DESC, views DESC, video_id DESC, instance_domain DESC);
        """
    )
```

- **Invariants.** The function is idempotent and takes no write lock when the objects already exist.
- **Ordering trap.** `executescript` commits any open transaction, so callers run it before `BEGIN IMMEDIATE`, never inside it.
- **No `fetched_at` index.** The age purge scans the table. The job measures and logs the transaction ms, and an index is added only if that measurement asks for one.

### `engine/server/api/server.py`

- Line 109 gains `from data.trending import ensure_trending_schema`.
- After `ensure_interaction_event_schema(db)` (334), add `ensure_trending_schema(db)`. It runs on the read-write `db`, never on `search_db`.

### `engine/server/data/moderation.py`

- `_host_table_column_pairs()` appends `("trending_ranks", "instance_domain")` as its last entry.
- Nothing else changes. Absent tables are already skipped by `_table_exists`.

### `engine/server/db/jobs/fetch-trending.py` (new)

```python
#!/usr/bin/env python3
"""Provide fetch-trending runtime helpers: store each catalogue host's own PeerTube trending list in trending_ranks."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.moderation import list_active_denied_hosts
from data.time import now_ms
from data.trending import ensure_trending_schema
from scripts.cli_format import CompactHelpFormatter

# One page per host; the order is PeerTube's own trending.videos.intervalDays window (ADR-0010).
TRENDING_PATH = "/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"
MAX_RANK = 100
# The updater runs weekly: a host failing one run keeps its list, a host failing two loses it (operator decision, issue 38).
AGE_OUT_MS = 10 * 24 * 60 * 60 * 1000
BUSY_TIMEOUT_MS = 10000
# Negative is KiB: room for a full write so the page cache does not spill and take EXCLUSIVE before commit.
CACHE_SIZE_KIB = -65536
INSERT_SQL = "INSERT INTO trending_ranks (instance_domain, video_id, rank, likes, views, fetched_at) VALUES (?, ?, ?, ?, ?, ?)"


def video_key(video: dict[str, Any]) -> str | None:
    """Return the crawler's video_id for a listed video, as toStringId(video.uuid ?? video.id): a non-empty string, or an integer as its decimal string."""
    raw = video.get("uuid")
    if raw is None:
        raw = video.get("id")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        return raw or None
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    return None


def _count(value: Any) -> int:
    """Return a listed count as an int, 0 for anything that is not one."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def rank_rows(host: str, videos: list[Any], fetched_at: int) -> list[tuple[str, str, int, int, int, int]]:
    """Return the rank rows of one host's list: rank is the 1-based list position, and a repeated key keeps its first rank."""
    rows = []
    seen: set[str] = set()
    for rank, video in enumerate(videos[:MAX_RANK], start=1):
        key = video_key(video) if isinstance(video, dict) else None
        if key is None or key in seen:
            continue
        seen.add(key)
        rows.append((host, key, rank, _count(video.get("likes")), _count(video.get("views")), fetched_at))
    return rows


def fetch_host_list(host: str, timeout_s: float, max_retries: int) -> list[Any] | None:
    """Return a host's trending list (possibly empty), or None when every one of max_retries + 1 attempts failed."""
    request = Request(f"https://{host}{TRENDING_PATH}", headers={"Accept": "application/json"})
    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout_s) as response:
                body = json.loads(response.read())
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, list):
                raise ValueError("no data list")
            return data
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            logging.debug("trending fetch host=%s attempt=%d failed: %s", host, attempt + 1, exc)
    return None


def _fetch_safely(fetch_list: Callable[[str], list[Any] | None], host: str) -> list[Any] | None:
    """Run one host's fetch; any exception is that host failing, never the job."""
    try:
        return fetch_list(host)
    except Exception as exc:
        logging.debug("trending fetch host=%s raised: %s", host, exc)
        return None


def run(conn: sqlite3.Connection, fetch_list: Callable[[str], list[Any] | None], concurrency: int) -> dict[str, int]:
    """Read the hosts, fetch every list with no transaction open, then replace answered hosts' rows and purge aged rows in one transaction."""
    ensure_trending_schema(conn)
    denied = list_active_denied_hosts(conn)
    hosts = sorted(row[0] for row in conn.execute("SELECT DISTINCT instance_domain FROM video_embeddings") if row[0] and row[0].lower() not in denied)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        lists = dict(zip(hosts, pool.map(partial(_fetch_safely, fetch_list), hosts)))
    run_ms = now_ms()
    answered = {host: rank_rows(host, videos, run_ms) for host, videos in lists.items() if videos is not None}
    failed = sorted(host for host, videos in lists.items() if videos is None)
    if failed:
        logging.warning("trending hosts failed: %s", " ".join(failed))
    start = time.monotonic()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for host, rows in answered.items():
            conn.execute("DELETE FROM trending_ranks WHERE instance_domain = ?", (host,))
            conn.executemany(INSERT_SQL, rows)
        purged = conn.execute("DELETE FROM trending_ranks WHERE fetched_at < ?", (run_ms - AGE_OUT_MS,)).rowcount
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"asked": len(hosts), "answered": len(answered), "failed": len(failed), "written": sum(len(rows) for rows in answered.values()), "purged": purged, "transaction_ms": int((time.monotonic() - start) * 1000)}


def main() -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(description="Store each catalogue host's own PeerTube trending list.", formatter_class=CompactHelpFormatter)
    repo_root = script_dir.parents[3]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    parser.add_argument("--db", default=str((repo_root / DEFAULT_DB_PATH).resolve()), metavar="PATH", help=f"Path to database (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--concurrency", type=int, default=4, help="Hosts fetched at once.")
    parser.add_argument("--timeout-ms", type=int, default=5000, help="HTTP timeout in ms.")
    parser.add_argument("--max-retries", type=int, default=3, help="HTTP retries per host.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # mode=rw: a missing DB is a job failure, not a new empty file.
    conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=rw", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute(f"PRAGMA cache_size = {CACHE_SIZE_KIB}")
        fetch_list = partial(fetch_host_list, timeout_s=args.timeout_ms / 1000, max_retries=args.max_retries)
        stats = run(conn, fetch_list, args.concurrency)
    finally:
        conn.close()
    logging.info("trending hosts asked=%d answered=%d failed=%d rows written=%d purged by age=%d transaction=%dms", stats["asked"], stats["answered"], stats["failed"], stats["written"], stats["purged"], stats["transaction_ms"])


if __name__ == "__main__":
    main()
```

**Invariants**
- No network I/O runs inside the transaction. Fetching completes before `BEGIN IMMEDIATE`.
- An answered host's rows are exactly its new list, at most 100 rows. A failed host's rows are untouched by the replace step and are removed only when older than 10 days.
- A denied host is never asked. The comparison is lowercased, so a mixed-case stored host is matched too.
- `fetched_at` and the age cutoff come from one `now_ms()` read. Rows just written are never purged in the same run. Tests freeze time by patching the job module's own `now_ms`.
- **Exit status.**
  - Non-zero comes from an uncaught exception: a missing DB (`mode=rw`), schema errors, the `video_embeddings` read, or a transaction error.
  - A host failure is always `None`. `_fetch_safely` catches everything, so nothing surfaces through `pool.map`.
- **Retries.**
  - Every failure is retried, with no backoff. This is a deliberate simplification. Its ceiling is the stage time at prod flags: with `5/15000/3`, a dead host costs about 60 s, so 200 dead hosts across 5 workers add about 40 min. The stage's run time is logged. The upgrade path is a status-code check in `fetch_host_list`.
  - The tests patch the timeout and never sleep through a real one.
- **Identity.** `video_key` mirrors `toStringId(uuid ?? id)`:
  - an empty-string uuid does not fall back to `id`;
  - bools are rejected;
  - a non-integral float is rejected. Such an id cannot match a crawled `video_id`, so the row would never join anyway.
- `executemany` on the primary key cannot conflict, because keys are deduplicated per host and the host's rows are deleted first.

### `engine/server/data/random_videos.py`

- `POPULAR_ORDER_BY` is deleted. The comment at line 14 stays, and it still holds for every order.
- `ORDERED_FEED_ORDER_BY` gets a new first entry, in the existing style:
  ```python
      "trending": """
      t.rank ASC,
      t.likes DESC,
      t.views DESC,
      t.video_id DESC,
      t.instance_domain DESC
  """,
  ```
  followed by the unchanged `popular` and `recent`.
- A new dict sits beside it, keyed by the same set:
  ```python
  # The rows an order walks before joining videos: trending drives from its ranks index (CROSS JOIN fixes the order), so only listed rows are read, in order, and an OFFSET walk stops early.
  ORDERED_FEED_SOURCE = {
      "trending": """trending_ranks t
          CROSS JOIN video_embeddings e
            ON e.video_id = t.video_id AND e.instance_domain = t.instance_domain""",
      "popular": "video_embeddings e",
      "recent": "video_embeddings e",
  }
  ```
- In `fetch_ordered_page`, add `source = ORDERED_FEED_SOURCE[order]` beside `order_by`, and `FROM video_embeddings e` becomes `FROM {source}`. Nothing else in the function changes. The inner join to `videos` and `video_embeddings` restricts Trending to catalogue rows, and the order is finite.
- `fetch_popular_videos` keeps its signature:
  ```python
  def fetch_popular_videos(
      conn: sqlite3.Connection, limit: int, error_threshold: int | None = None, include_nsfw: bool = True
  ) -> list[dict[str, Any]]:
      """Return the popular layer's pool: the head of the Trending order, in that order, with its filters."""
      return fetch_ordered_page(conn, "trending", limit, 0, error_threshold, include_nsfw)
  ```
  The row shape is identical, `popularity` included. With an empty table the pool is `[]`.
- **Build check (query plan).** `EXPLAIN QUERY PLAN` of the trending query on a realistic fixture must show `SCAN t USING INDEX idx_trending_ranks_order`, SEARCH lookups for `e` and `v`, and no `USE TEMP B-TREE FOR ORDER BY`. If `e` has no usable `(video_id, instance_domain)` index, the build comes back rather than adding one silently.

### `engine/server/api/handlers/similar.py`

- `FEED_MODES = ("recommendations", "trending", "recent", "random", "popular")`.
- `ORDERED_FEED_MODES = frozenset({"trending", "popular", "recent"})`.
- The `_handle_ordered_feed` docstring (767) names trending.
- `mode=hot` falls into the existing 400 with `allowed` equal to the tuple above.

### `engine/server/db/jobs/updater-worker.py`

- The required-files tuple (1091-1106) gains `script_dir / "fetch-trending.py"` next to `recompute-popularity.py`, so a missing job fails at start. This was recorded as a choice.
- Between the service `try/finally` (ends 1427) and the existing comment at 1429, add:
  ```python
              # The Engine serves again from here; the trending job's one write transaction runs beside it, and its failure is raised only after the similarity stage has run.
              trending_failed = False
              try:
                  run_cmd(
                      [
                          args.python_bin,
                          (script_dir / "fetch-trending.py").as_posix(),
                          "--db",
                          prod_db.as_posix(),
                          "--concurrency",
                          str(args.concurrency),
                          "--timeout-ms",
                          str(args.timeout_ms),
                          "--max-retries",
                          str(args.max_retries),
                      ],
                      cwd=repo_root,
                  )
              except Exception:
                  logging.exception("trending stage failed; similarity stage still runs")
                  trending_failed = True
  ```
- After `run_similarity_stage(...)`:
  ```python
              if trending_failed:
                  raise RuntimeError("trending stage failed")
  ```
  It stays inside the outer `try`, so the temp-file `finally` runs and "worker completed" is not logged.
- The stage sits outside the service `try`, which keeps `test_main_runs_similarity_stage_after_service_start` valid.
- **Skips.** The early return at 1328 and the injected `--fail-*` flags raise before the stage, so it is skipped then (R7, accepted).

### Frontend

`feed-params.ts`:
```ts
export const FEED_MODES = ["recommendations", "trending", "recent", "random", "popular"] as const;
...
/**
 * Return a known feed mode, or recommendations for anything else; hot, which Trending replaced, reads as trending.
 */
export function parseFeedMode(raw: unknown): FeedMode {
  // Old ?mode=hot links and stored feedParams:v1 choices outlive the Hot mode.
  const wanted = raw === "hot" ? "trending" : raw;
  return FEED_MODES.find((mode) => mode === wanted) ?? "recommendations";
}
```
- A bare stored JSON string `"hot"` still yields `recommendations`, because `readStoredFeedParams` only parses objects.
- `index.html:41` and `videos.html:41` become `data-feed-mode="trending"` with the label `Trending`.
- The comment at `index.ts:248` reads "(trending, recent and popular included)".
- `dist` is then rebuilt with `vite build` and committed. A stale dist would keep sending `mode=hot`, which the Engine now answers with a 400.

### Smoke script

- `test-orchestrator-smoke.py` `marker_to_stage` gains `"fetch-trending.py": "trending_fetch"`. `required_markers` is not changed, because a failed host never fails the run and the marker always appears.
- `ORCHESTRATOR_SMOKE_TEST.md` notes that the stage contacts the fixture's real hosts.

### Tests

These run in `tests/active` and never reach real hosts.

**`tests/active/test_fetch_trending.py`** (new). The job is loaded with `_load_job` via `importlib.util.spec_from_file_location`.

- **`fetch_host_list`** with `urlopen` patched on the module:
  - a good body returns `data`;
  - `HTTPError` 500, `URLError`, `TimeoutError`, a non-JSON body, and a JSON body without a `data` list each return `None`;
  - the attempt count is `max_retries + 1`, checked with a counter;
  - one failure followed by success returns the list;
  - the URL is exactly `https://h/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both`.
- **`video_key` / `rank_rows`:**
  - `uuid` wins; `id` is used only when `uuid` is None or missing; an empty `uuid` gives None and is skipped; int ids become decimal strings; bool ids are skipped;
  - a duplicate key keeps its first rank, and positions skipped by bad entries leave gaps;
  - a 120-entry list gives at most 100 rows;
  - non-int likes and views become 0.
- **`run`** on a temp DB built from the crawler `schema.sql` plus `ensure_moderation_schema`, with an injected `fetch_list`:
  - asked hosts are exactly the distinct embedded hosts minus active denylist hosts; the injected fetcher records each call, and a denied mixed-case host is not asked;
  - an answered host's rows are replaced, so old keys are gone;
  - a failed host (`None`, and also a fetcher that raises) keeps its rows and its `fetched_at`;
  - with the module's `now_ms` patched, a failed host's rows are purged after the cutoff; with 10 days + 1 ms they are gone, and with exactly 10 days they are kept;
  - the stats dict counts are right;
  - a second connection holding `BEGIN IMMEDIATE` with the job's busy timeout patched low makes `run` raise `sqlite3.OperationalError`, and the table is left unchanged.
- **Exit status:** a subprocess `fetch-trending.py --db <missing>` exits non-zero, and no file is created.
- **Purge:** `purge_host_data(conn, "h")` deletes h's `trending_ranks` rows, and its counts include the `trending_ranks` key.
- **Mix with an empty popular layer (R2):**
  - `MixingRecommendationStrategy` is built with the `RECOMMENDATION_PIPELINE` config, stub generators that return `limit` distinct rows per layer, and popular returning `[]`;
  - `guest_home` (no likes) returns a full `batch_size`;
  - `home` with likes returns a non-empty page shorter than the batch, by popular's share;
  - this runs under the Engine interpreter in a child process, as `_FEED_CONSTANTS_CHILD` does, if the mixer's imports need numpy.

**`tests/active/test_random_videos.py`:**
- New helper `_seed_ranks(conn, rows)` calls `ensure_trending_schema` and inserts rows. Every fixture that reaches trending or `fetch_popular_videos` calls it: `_feed_db`, `_signal_db`, `_two_video_db` and `nsfw_conn`.
- `EXPECTED` loses `hot` and gains `trending`. Its order is hand-derived from rank interleave, then listed likes, listed views, `video_id` and domain. The ranks deliberately differ from the popularity and likes orders, so a pass cannot be a coincidence.
- The fixtures include a ranked row absent from the catalogue (never served), a rank tie broken at each key in turn, and an end with no fallback: past the last ranked row, the page is `[]`.
- `test_a_page_holds_exactly…` gets a trending-specific expected set.
- The pool assertions become: `fetch_popular_videos(conn, n) == fetch_ordered_page(conn, "trending", n, 0)` for several `n` and filter combinations, and the pool is `[]` on an empty table.
- A new test asserts `set(ORDERED_FEED_SOURCE) == set(ORDERED_FEED_ORDER_BY)`.
- A new test runs `EXPLAIN QUERY PLAN` on a few-thousand-row fixture: no `TEMP B-TREE`, and `idx_trending_ranks_order` is used.
- `"hot"` literals become `"trending"`, and the docstring bullets are rewritten.

**`tests/active/conftest.py`.** New session fixture `trending_seed`, which `engine` takes as a parameter so that it runs first. It runs under `ENGINE_START_LOCK`:
- connect to `WHITELIST_DB` with `timeout=30`;
- call `ensure_trending_schema`;
- in one transaction, `DELETE FROM trending_ranks` and then `INSERT … SELECT` with `ROW_NUMBER() OVER (PARTITION BY v.instance_domain ORDER BY v.views DESC, v.likes DESC, v.video_id DESC)` over `videos JOIN video_embeddings`, keeping rank ≤ 100, with listed likes and views from the crawled counts and a fixed `fetched_at`.

The seed is deterministic and idempotent, so lanes that rerun it write identical content. A note in the fixture says it writes the shared dev DB by operator decision.

**Build check:**
- the head of 96 trending rows under `include_nsfw=True` must hold a flagged row, which is the control at `test_similar.py:917`;
- the order must hold at least 48 rows.

If the dev DB does not meet both, the build comes back rather than tuning the seed toward the test.

**`tests/active/test_similar.py`:**
- `REQUIRED_MODES` swaps `hot` for `trending`.
- `UNKNOWN_MODES` gains `"hot"`, which proves the 400 with `trending` in `allowed`.
- `SEEDED_MODES` gains `"hot"`.
- `NSFW_LISTINGS` uses `"mode=trending"`.
- The comment at 802 names trending.
- The ordered paging test then covers trending against the seeded table.

**`tests/active/test_frontend_feed_params.py`:**
- The control comment names trending.
- Stored `{"mode":"hot"}` gives `["trending"]`, and `?mode=hot` gives `["trending"]`; these are the alias proof.
- `?mode=bogus` and a stored unknown value still give `["recommendations"]`.
- The bare JSON string `"hot"` control still gives `["recommendations"]`.
- The NSFW harness cases at 301 and 345 use `trending`.

**`tests/active/test_server.py`:** rename `mode=hot` to `mode=trending`, along with the test name and the docstring line 125. This is a vocabulary change only.

**`tests/active/test_updater_worker.py`:**
- **Stage position (AST check):** the `run_cmd` call naming `fetch-trending.py` has `lineno > service_try.end_lineno` and lies before the `run_similarity_stage` call, outside every `Try` whose body holds the systemctl stop.
- **Failure behaviour.** `_run_main` gains `fail_flags=("--fail-after-merge-before-similarity",)` and `fail_child=None` parameters; the defaults keep the existing tests byte-for-byte. A new test runs with no fail flag:
  - `fake_run` raises `CalledProcessError` only for argv naming `fetch-trending.py`;
  - `updater.run_similarity_stage` is patched to a recorder;
  - `run_similarity_stage` was called once, after the trending child;
  - `main` raised `RuntimeError("trending stage failed")`;
  - the trending argv carries `--db <prod> --concurrency 4 --timeout-ms 5000 --max-retries 3`.

**`tests/config.json`:**
- `test_fetch_trending.py` → `fetch-trending.py`, `data/trending.py`, `data/moderation.py`, `recommendations/mixer.py`.
- `data/trending.py` is added to `test_random_videos.py` and `test_similar.py`.
- `fetch-trending.py` is added to `test_updater_worker.py`.
- `tests/active/conftest.py` is added to `test_similar.py` if the groups list conftest.

Unchanged: `test_popular_videos.py`, `test_video.py`, `test_install_*`, `test_frontend_dist.py` (green once dist is rebuilt), and `tests/archive/**`. `tests/last_test_validation.json` is regenerated, not edited.

### Documents (A7)

The inventory's checklist is applied as written, with the cadence decision in place:
- **CONTEXT.md.** Feed mode lists trending, and the Hot entry is removed. **Trending** says:
  - it is stored per host in `trending_ranks`;
  - it is refreshed by the updater's trending stage, which runs weekly;
  - a failing host keeps its list for up to 10 days;
  - it is empty until the first fill.

  **Popular** says it uses the Trending order.
- **ADR-0010.** A dated note says the updater runs weekly (Fri 20:00), so Trending is up to a week old, and the age-out is 10 days (operator decision, issue 38 build). The decision text itself is not rewritten.
- **UPDATER_WORKER.md.**
  - The purpose list gains the stage, with its place between start and similarity and its failure rule.
  - It notes the early-return skip.
  - It gives the first-fill command: `python engine/server/db/jobs/fetch-trending.py --db engine/server/db/whitelist.db --concurrency 5 --timeout-ms 15000 --max-retries 3`.
  - The log lines are listed.
  - It describes the write lock's effect on serving and the transaction ms to watch.
  - The stale "daily / `OnUnitInactiveSec=1d`" is corrected to the installed weekly `OnCalendar`.
- **DATA_BUILD.md:** the sequence gains "trending ranks" after the ANN rebuild, the timer line says weekly, and it gains the first-fill command.
- **Other docs.** `README.md`, `client/README.md`, `client/frontend/README.md` (with the `hot` alias and the dist rebuild-and-commit note), `engine/server/README.md` (`mode=hot` → 400; empty until the first fill), `OVERVIEW.md`, `LAYER_PARAMS.md`, `PIPELINE_DIAGRAM.md`, `ORCHESTRATOR_SMOKE_TEST.md`, `DEPLOYMENT.md` and `roadmap.md` get the edits the inventory lists. `OVERVIEW.md` and `LAYER_PARAMS.md` also state that `home` pages with likes are short by popular's share until the first fill.
- `peertube-browser-service-review.md` is updated with one sentence.
- **Issue.** Issue 38 gets `Status: enhancement, complete` and moves to `docs/project/issues/archive/`. Its path references in issue 42:58 and ADR-0010:4 are updated.

### Build-time checks recorded, not assumed

- **R1 journal mode.** Run `PRAGMA journal_mode` on a prod copy and record the result. Log the transaction ms of a full run on that copy. If it is above about 1 s, the build stops and brings the batching question to the operator.
- **Query plan.** Check the `EXPLAIN QUERY PLAN` output described above.
- **R8.** Confirm `git merge-base --is-ancestor b423159 HEAD` before editing `random_videos.py` and the updater docs.
- **Smoke fixture hosts.** The smoke fixture's hosts are real domains (`tests/test-instances.json`). The stage makes real requests there, as the crawl already does.

### Tradeoffs carried to the operator (unchanged from the plan, plus decisions taken)

- The popular pool now carries the Trending order's semantics. Its `popularity` field is kept for row shape but no longer explains why a row is in the pool.
- Trending is empty until the first fill, with no fallback. Keyed `home` pages with likes are short by about 5 of 48 rows until then (accepted).
- Every fetch failure is retried, with no backoff. The stage lengthens each weekly run, by up to about 40 min with 200 dead hosts at prod flags, before similarity starts.
- Trending is up to a week old, plus the instances' own 7-day windows. A failing host's list lasts up to 10 days (accepted).
- The test session rewrites `trending_ranks` in the live dev DB (accepted).
- `POPULAR_ORDER_BY` is deleted, so `videos.popularity` is read only by search.


### Phases

#### Phase 1 - Trending job and storage [code]

**Files touched.** engine/server/data/trending.py (NEW), engine/server/db/jobs/fetch-trending.py (NEW), engine/server/data/moderation.py (EDITED), tests/active/test_fetch_trending.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the job module's `run(conn, fetch_list, concurrency)` and `fetch_host_list`, entered in-process. The new `tests/active/test_fetch_trending.py` loads `fetch-trending.py` through `_load_job` (`importlib.util.spec_from_file_location`), following `test_host_normalisation._load_job` / `test_updater_worker._load_job`. The DB is a temp `whitelist.db` built from the crawler `schema.sql` plus `ensure_moderation_schema`. The far side of the boundary is shimmed in two places: an injected `fetch_list` that records calls and returns lists, `None` or raises, and `urlopen` patched on the module for `fetch_host_list`. Time is frozen by patching the module's own `now_ms`. Assertions for C1: rows already stored for an answered host are replaced, so its old keys are gone. Its new rows are exactly its list: at most 100 from a 120-entry list, rank is the 1-based list position with gaps where entries are bad, a repeated key keeps its first rank, `uuid` wins over `id`, an int id becomes its decimal string, and non-int likes and views become 0. Assertions for C2: a host whose fetcher returns `None`, and a host whose fetcher raises, each keep their rows with `fetched_at` unchanged. At exactly 10 days the rows are kept; at 10 days + 1 ms they are purged. Also covered by tests, though not clauses, as the operator chose when merging the denied-host phase into this one: the hosts asked are exactly the distinct embedded hosts minus the active denylist, and a mixed-case denied host is not asked. `purge_host_data(conn, "h")` deletes h's `trending_ranks` rows, and its counts include `trending_ranks`. The URL is exact, and the retry count is `max_retries + 1`. The stats dict is right. A competing `BEGIN IMMEDIATE` makes `run` raise with the table unchanged. A subprocess `--db <missing>` exits non-zero and creates no file.

**Intent.** `engine/server/db/jobs/fetch-trending.py` keeps the `trending_ranks` table (created by `data/trending.py`'s `ensure_trending_schema`) holding each answered host's own trending list, and leaves a failed host's earlier rows in place until they are more than 10 days old.

- C1 - After a run, an answered host's `trending_ranks` rows are exactly its newly fetched list: at most 100 rows, ranked by 1-based list position, with a repeated key keeping its first rank.
- C2 - A host that failed the run keeps its earlier rows until their `fetched_at` is more than 10 days before the run, and a run after that point purges them.

**Outcome.** ### `engine/server/data/trending.py` (new)
- `ensure_trending_schema(conn)` follows `ensure_moderation_schema`. It runs one `executescript` holding `CREATE TABLE IF NOT EXISTS trending_ranks` (`instance_domain`, `video_id`, `rank`, `likes`, `views`, `fetched_at`, all NOT NULL; primary key `(instance_domain, video_id)`) and `CREATE INDEX IF NOT EXISTS idx_trending_ranks_order ON trending_ranks (rank ASC, likes DESC, views DESC, video_id DESC, instance_domain DESC)`.
- A comment warns that `executescript` commits any open transaction, so callers run it before their `BEGIN IMMEDIATE`.

### `engine/server/data/moderation.py`
- `_host_table_column_pairs()` gains `("trending_ranks", "instance_domain")` as its last entry. `purge_host_data` therefore deletes a host's rank rows and counts them under `trending_ranks`, next to the existing tables.
- A DB without the table is still skipped through `_table_exists`.

### `engine/server/db/jobs/fetch-trending.py` (new)
Built from the plan's draft. It follows `recompute-popularity.py`, `updater-worker.py` and `repair-video-channel-names.py`: `server_dir` on `sys.path`, `CompactHelpFormatter`, `DEFAULT_DB_PATH` as the `--db` default, and `logging`.
- **Hosts.** `run(conn, fetch_list, concurrency)` first calls `ensure_trending_schema`. It then asks the distinct `video_embeddings.instance_domain` values whose lowercased form is not in `list_active_denied_hosts(conn)`, which is reused.
- **Fetch.** Lists are fetched through a `ThreadPoolExecutor(max_workers=concurrency)` before any transaction opens. `_fetch_safely` turns any exception from a host's fetcher into that host failing (`None`, logged as a warning), never a job failure.
- **Rows.** `rank_rows` reads at most the first 100 list positions. Rank is the 1-based position, an entry without a key leaves a gap, and a repeated key keeps its first rank. `video_key` mirrors the crawler's `toStringId(uuid ?? id)`: a non-empty string, or a non-bool int as its decimal string. `_count` gives 0 for any likes or views value that is not a non-bool int.
- **Write.** One `BEGIN IMMEDIATE … COMMIT` deletes and re-inserts each answered host's rows, then deletes rows with `fetched_at < run_ms - AGE_OUT_MS`, where `AGE_OUT_MS` is 10 days. Any error rolls back and re-raises. `fetched_at` and the cutoff come from one call to the module's own `now_ms` (`data.time`).
- **Counters.** `run` returns `asked`, `answered`, `failed`, `written`, `purged` and `transaction_ms`. `transaction_ms` is timed from after the lock is taken to the commit.
- **`fetch_host_list(host, timeout_s, max_retries)`.** It GETs `https://<host>/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both` with a User-Agent header, as the updater and sync jobs send, and returns the body's `data` list, `[]` included. On `OSError` (HTTPError, URLError, timeouts) or `ValueError` (a non-JSON body, or no `data` list) it makes `max_retries + 1` attempts, then returns `None`. A `rat-tail:` comment marks the retry-everything simplification: its ceiling is run time, and the upgrade path is a status-code check.
- **CLI.** `--db`, `--concurrency 4`, `--timeout-ms 5000`, `--max-retries 3`. A missing `--db` file is a `parser.error`, as in `repair-video-channel-names.py`: exit 2 and no file created. The connection uses a 10 s busy timeout, the `sqlite3.Row` row factory and a raised `cache_size` (R1). One summary line logs hosts asked, answered and failed, rows written, rows purged by age and the transaction ms. Failed hosts are named in a warning.
- **Differences from the draft.**
  - The missing-DB check is `is_file()` plus `parser.error` (house pattern) instead of a `mode=rw` URI, which would misparse paths containing `?` or `%`.
  - The busy timeout is set through `connect(timeout=)` instead of a PRAGMA.
  - Dropped: the float-id branch (PeerTube ids are ints) and the `max(1, concurrency)` clamp.

### `tests/active/test_fetch_trending.py`, `tests/config.json`
- These are named in the phase but not touched in this step. The checkpoint lives in `tests/tmp`, and this step asked for production code only.
- Promoting the checkpoint and adding its `test_groups` entry (`fetch-trending.py`, `data/trending.py`, `data/moderation.py`) is still to be done.

### `tests/tmp/probe_fetch_trending_cli.py` (throwaway probe, to delete)
- It showed that the job runs as a subprocess under the test interpreter (exit 0 on a ready DB) and that a missing `--db` exits 2 with no file created.
- It also showed that `ensure_trending_schema` does not error while another connection holds `BEGIN IMMEDIATE`, and that the job's own `BEGIN IMMEDIATE` then raises `database is locked`.
- I have no delete tool, so the file is still there. Please remove it.

**Beyond the files named.** tests/tmp/probe_fetch_trending_cli.py - throwaway probe written to observe the job's subprocess exit codes and the lock behaviour of the schema call; I could not delete it with my tools, so it should be removed.

#### Phase 2 - Trending order and popular pool [code]

**Files touched.** engine/server/data/random_videos.py (EDITED), engine/server/api/handlers/similar.py (EDITED), engine/server/api/server.py (EDITED), tests/active/conftest.py (EDITED), tests/active/test_random_videos.py (EDITED), tests/active/test_similar.py (EDITED), tests/active/test_server.py (EDITED), tests/active/test_fetch_trending.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam, in two layers. The lowest changed layer is `data.random_videos.fetch_ordered_page` / `fetch_popular_videos`, called directly on the temp-DB fixtures in `tests/active/test_random_videos.py` (`_feed_db`, `_signal_db`, `_two_video_db`, `nsfw_conn`, each gaining `_seed_ranks`). The highest reachable layer is the live Engine's `GET /api/similar?mode=trending` in `tests/active/test_similar.py`, through the session `engine` fixture. Its new `trending_seed` conftest fixture writes deterministic ranks into the dev DB before the Engine starts. Assertions for C1: the hand-derived `EXPECTED["trending"]` matches. Its ranks are chosen to differ from the popularity and likes orders, and the expected order interleaves ranks across hosts, with a rank tie broken at likes, views, `video_id` and domain in turn. A ranked row outside the catalogue is never served. Pages walked with offset neither repeat nor skip a row. The page past the last ranked row is `[]`, with no fallback. `EXPLAIN QUERY PLAN` on a few-thousand-row fixture uses `idx_trending_ranks_order` and has no `TEMP B-TREE`. `set(ORDERED_FEED_SOURCE) == set(ORDERED_FEED_ORDER_BY)`. Live: the ordered paging test covers trending, `mode=hot` → 400 with `trending` in `allowed`, and `mode=trending` passes the NSFW listing checks. Assertions for C2: `fetch_popular_videos(conn, n) == fetch_ordered_page(conn, "trending", n, 0)` for several `n` and filter combinations, and the pool is `[]` on an empty ranks table. For the R2 mix in `test_fetch_trending.py`, `MixingRecommendationStrategy` (the `RECOMMENDATION_PIPELINE` config, with stub generators and popular returning `[]`) gives a full batch for `guest_home`, and for `home` with likes a non-empty page short by popular's share. It runs in an Engine-interpreter child as `_FEED_CONSTANTS_CHILD` does if numpy is needed. `test_server.py` is renamed to `mode=trending`.

**Intent.** The Engine serves `mode=trending` as catalogue rows walked in `trending_ranks` order (`random_videos.ORDERED_FEED_SOURCE`/`ORDERED_FEED_ORDER_BY`, `similar.FEED_MODES`, schema ensured at `server.py` startup), and `fetch_popular_videos` returns the head of that same order as the popular layer's pool.

- C1 - `mode=trending` pages walk catalogue rows by rank, then listed likes, listed views, `video_id` and domain, never serve a ranked row outside the catalogue, and end with an empty page instead of a fallback.
- C2 - The popular layer's pool of size n equals the first n rows of the Trending order under the same filters, and is empty when `trending_ranks` is empty.

**Outcome.** ### `engine/server/data/random_videos.py`
- `ORDERED_FEED_ORDER_BY` no longer has `hot`. It now has `trending`: `t.rank ASC, t.likes DESC, t.views DESC, t.video_id DESC, t.instance_domain DESC`. `popular` and `recent` are unchanged.
- New dict `ORDERED_FEED_SOURCE`, with the same keys. It holds the table each order reads from:
  - `trending`: `trending_ranks t CROSS JOIN video_embeddings e ON e.video_id = t.video_id AND e.instance_domain = t.instance_domain`. The CROSS JOIN makes the ranks index the table the walk starts from, so the query needs no sort. The inner joins to `video_embeddings` and `videos` keep the order to ranked catalogue rows, and the order ends when they run out.
  - `popular` and `recent`: `video_embeddings e`, so their SQL is the same as before.
- `fetch_ordered_page` looks up `source = ORDERED_FEED_SOURCE[order]` and reads `FROM {source}`. Nothing else in it changed.
- `fetch_popular_videos` keeps its signature. It now just calls `fetch_ordered_page(conn, "trending", limit, 0, error_threshold=..., include_nsfw=...)`, so the pool is the head of the Trending order under the same filters, with the same row shape (`popularity` included). It is `[]` while `trending_ranks` is empty. The old separate popularity query is deleted.
- `POPULAR_ORDER_BY` is deleted; nothing reads it any more.

### `engine/server/api/handlers/similar.py`
- `FEED_MODES = ("recommendations", "trending", "recent", "random", "popular")`.
- `ORDERED_FEED_MODES = frozenset({"trending", "popular", "recent"})`.
- The `_handle_ordered_feed` docstring now names trending.
- `mode=hot` now gets the existing unknown-mode 400, whose `allowed` list names `trending`.

### `engine/server/api/server.py`
- Imports `ensure_trending_schema` from `data.trending` and calls it on the read-write `db` at startup, after `ensure_interaction_event_schema(db)`. The table therefore exists, empty, before the first fill.

### `tests/active/conftest.py`
- New session fixture `trending_seed`, which `engine` now takes so it runs before the Engine starts. It does four things:
  - It loads `engine/server/data/trending.py` through `importlib.util.spec_from_file_location`, so the conftest's `sys.path` stays as it is.
  - It takes `ENGINE_START_LOCK` and connects to `WHITELIST_DB` with `timeout=30`.
  - It runs `ensure_trending_schema`.
  - In one transaction it runs `DELETE FROM trending_ranks` and then the plan's `INSERT … SELECT`. That SELECT ranks each host's embedded catalogue rows with `ROW_NUMBER() OVER (PARTITION BY v.instance_domain ORDER BY v.views DESC, v.likes DESC, v.video_id DESC)` and keeps rank ≤ 100. Listed likes and views are the crawled counts, `COALESCE`d to 0 because the rank columns are NOT NULL, and `fetched_at` is fixed at 0.
- The seed is deterministic, so every lane writes the same rows.
- The module docstring mentions the seed.

### Not touched in this step
- The existing active tests that still name `hot` will fail against this code until the build updates them, as the plan says (Tests section): `tests/active/test_random_videos.py` (`EXPECTED["hot"]`, the popularity-pool assertions, and fixtures without `trending_ranks`), `tests/active/test_similar.py` (`REQUIRED_MODES` and the `NSFW_LISTINGS` `mode=hot`) and `tests/active/test_frontend_feed_params.py`. The same applies to the `tests/active/test_server.py` rename, the R2 mix test in `tests/active/test_fetch_trending.py` and the `tests/config.json` groups.
- They have already gated and this step asked for production code only, so I did not edit them. The same holds for promoting the checkpoint, as in phase 1.

#### Phase 3 - Updater trending stage [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED), engine/server/db/jobs/tests/test-orchestrator-smoke.py (EDITED), tests/active/test_updater_worker.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: `updater-worker.py`'s `main()`, entered in-process through the existing `tests/active/test_updater_worker.py` harness. That harness is `_load_job`, plus `_run_main` (extended with `fail_flags` and `fail_child` parameters whose defaults keep existing tests byte-identical), with a `fake_run` standing in for the child processes. The precedent for the position check is the AST check in `test_main_runs_similarity_stage_after_service_start`. Assertions for C1: the `run_cmd` call naming `fetch-trending.py` has `lineno` greater than the service `try`'s `end_lineno` and less than the `run_similarity_stage` call, outside every `Try` whose body holds the systemctl stop. The trending argv carries `--db <prod> --concurrency 4 --timeout-ms 5000 --max-retries 3`, and `fetch-trending.py` is in the required-files set. Assertions for C2: `fake_run` raises `CalledProcessError` only for the trending argv, and `run_similarity_stage` is patched to a recorder. Similarity is called exactly once, after the trending child. `main` raises `RuntimeError("trending stage failed")`, and "worker completed" is not logged. The smoke script's `marker_to_stage` entry is a one-line mapping. It is exercised only by the out-of-suite orchestrator smoke run, not by this checkpoint.

**Intent.** `updater-worker.py` runs `fetch-trending.py` against the prod DB once the Engine is serving again and before the similarity stage, and a trending failure fails the run only after similarity has still run.

- C1 - The trending child runs after the Engine-restart `try/finally` and before `run_similarity_stage`, with the prod DB and the run's concurrency, timeout and retry flags.
- C2 - When the trending child fails, the similarity stage still runs once, and then the run raises `RuntimeError("trending stage failed")`.

**Outcome.** ### `engine/server/db/jobs/updater-worker.py`
- **Required files:** `script_dir / "fetch-trending.py"` is now one of the required files `main` checks before it does anything else. If it is missing, the run raises `FileNotFoundError` naming it, before the lock is taken and before any child runs.
- **Trending stage (C1):** a new stage runs right after the Engine-restart `try/finally` (the one whose `finally` starts the service and releases the deploy lock) and before `similarity_precompute_cmd` / `run_similarity_stage`. It calls `run_cmd([args.python_bin, <jobs>/fetch-trending.py, "--db", prod_db, "--concurrency", args.concurrency, "--timeout-ms", args.timeout_ms, "--max-retries", args.max_retries], cwd=repo_root)`, which is the same inline-argv `run_cmd` shape the other Python jobs use. Because it sits outside that `try`, a failure inside the `try` (including `--fail-after-merge-before-similarity`) skips both the trending child and the similarity stage.
- **Trending failure (C2):** if the child exits non-zero, the `subprocess.CalledProcessError` is caught, logged at error level with its exit code, and held in `trending_error`. The similarity stage still runs once. After it, `main` raises `RuntimeError("trending stage failed") from trending_error`, so "worker completed" is never logged. If the similarity stage raises on its own, that exception goes up unchanged, and the earlier error log still records the trending failure.
- **Help text:** the argparse description now shows the pipeline as `... start service -> trending fetch -> similarity shadow build, gate and swap.`

### `engine/server/db/jobs/tests/test-orchestrator-smoke.py`, `tests/active/test_updater_worker.py`, `tests/config.json`
I did not change these. Nothing the checkpoint needs depends on them, and neither of the two tests is broken by the change:
- **`tests/active/test_updater_worker.py`:** its runs of `main` use the real jobs dir, which already contains `fetch-trending.py`. They also stop at `--fail-after-merge-before-similarity`, so they never reach the trending child.
- **The smoke's `parse_stage_durations`:** it ignores the unmatched `fetch-trending.py` "run:" line. The child's "done:" line comes when the pending queue is empty, so it is skipped too.
- **Durations and log checks:** the smoke still records no duration for the trending stage, and its log-marker check does not look for `fetch-trending.py`. Adding either is left for whichever phase asks for it.

#### Phase 4 - Frontend Trending mode [code]

**Files touched.** client/frontend/src/data/feed-params.ts (EDITED), client/frontend/index.html (EDITED), client/frontend/videos.html (EDITED), client/frontend/src/pages/videos/index.ts (EDITED), client/frontend/dist/** (REGENERATED), tests/active/test_frontend_feed_params.py (EDITED)

**Checkpoint.** Seam: the client's feed-param resolution as bundled code. The existing `tests/active/test_frontend_feed_params.py` harness bundles `feed-params.ts`/`videos.ts` with esbuild, runs it in node with an in-memory `localStorage` (`_run`, `_stored`, `_modes`), and reports the `mode` entries of the URL built. `_engine_feed_modes` reads the Engine's `FEED_MODES` tuple from `similar.py` by AST, so the mode set is taken from production at run time. Assertions for C1: `?mode=hot` gives `["trending"]`, and stored `{"mode":"hot"}` with no URL mode gives `["trending"]`. Controls: `?mode=bogus` and a stored unknown mode still give `["recommendations"]`, and the bare JSON string `"hot"` still gives `["recommendations"]`. Assertions for C2: `test_the_client_s_feed_modes_are_the_engine_s` passes with `trending` in place of `hot`, and every Engine mode round-trips. The NSFW harness cases use `trending`. `test_frontend_dist.py` stays green after dist is rebuilt with `vite build` and committed. The HTML button's `data-feed-mode` value is markup; it is covered by the dist rebuild, not by its own assertion.

**Intent.** The client's `feed-params.ts` offers `trending` in place of `hot`, and `parseFeedMode` reads a legacy `hot`, from the URL or from stored `feedParams:v1`, as `trending`, so the rebuilt client never sends a mode the Engine rejects.

- C1 - A legacy `hot`, given as `?mode=hot` or stored as `{"mode":"hot"}`, resolves to a request with `mode=trending`.
- C2 - The client's feed modes equal the Engine's `FEED_MODES`, which name `trending` and not `hot`.

**Outcome.** ### client/frontend/src/data/feed-params.ts
- `FEED_MODES` is now `["recommendations", "trending", "recent", "random", "popular"]`, the same set as the Engine's tuple in `similar.py`.
- `parseFeedMode` maps a raw `"hot"` to `"trending"` before it looks the mode up, with a one-line comment saying why. Both the `?mode=` path and the stored-object path in `resolveFeedParams` go through `parseFeedMode`, so this one check covers both. `readStoredFeedParams` still checks that the stored value is an object before it parses the mode, so a bare JSON string `"hot"` still falls back to recommendations. Any other unknown value, `bogus` included, still gives recommendations.

### client/frontend/index.html, client/frontend/videos.html
- In the feed-mode group, the Hot button is now `data-feed-mode="trending"` with the label "Trending". `pages/videos/index.ts` decides which button is pressed by comparing `data-feed-mode` with the resolved mode, so the button now matches the client's modes.

### client/frontend/src/pages/videos/index.ts
- Changed only the comment in `pickSample` ("trending, recent and popular" in place of "hot, …"). No logic changed. `chooseFeedMode` already goes through `parseFeedMode`.

### client/frontend/dist/**
- The operator regenerated it with the frontend build. I couldn't run vite because I have no shell. I checked afterwards: `dist/index.html` and `dist/videos.html` carry the Trending button, and the feed-params code is in a newly hashed asset, `assets/key-rejected-Bz9wLg_W.js` (it was `key-rejected-BIgz77-g.js`).

### tests/active/test_frontend_feed_params.py
- Wherever `hot` stood in as an arbitrary non-default mode, it is now `trending`: the stored mode in `test_the_legacy_random_flag_gives_random_over_a_stored_mode`, the params and stored mode in `test_build_similar_url_with_no_feed_params_carries_no_mode`, and the `?mode=` feed URL in the NSFW runner along with its control assertion. The module docstring, the five-mode control comment and the bare-string comment were updated to match. Each test asserts what it did before, with the same power to catch a wrong result. Without the swap they would read `["trending"]` where they expect `["hot"]`. The harness names the phase-4 checkpoint loads (`_modes`, `_run`, `_stored`, `ENGINE_FEED_MODES`, `VIDEOS`, `VIDEOS_ERROR`, `FEED_PARAMS_ERROR`) are unchanged.

**Beyond the files named.** none. Note: `client/frontend/README.md` still names the mode "Hot" in its feed description (lines 10 and 14). It is outside this phase's files and was left for the documentation step.

## Inner unit tests

None. Every clause is carried by a phase checkpoint.

## Close

_Step 8 was closed by hand on 2026-10-03: the `dev-flow` workflow stopped after three red-triage attempts (see the record's "Step 8 - stopped"), and the operator directed the build to continue under `dev_flow.md` without resuming the workflow. The `.record.md` is left as the workflow wrote it._

- **Refactors.** None made; the record's Step 8 refactor pass found nothing duplicated, dead or speculative. Left out: the `test-orchestrator-smoke.py` `marker_to_stage` entry (new behaviour, out-of-suite).
- **Clause accounting.** P1C1, P1C2, P2C1, P2C2, P3C1, P3C2, P4C1 and P4C2 are each carried by their phase's audited checkpoint, now promoted to `tests/active/test_fetch_trending.py`, `test_trending_feed.py`, `test_updater_trending_stage.py` and `test_frontend_trending_mode.py`.
- **Retired durable tests** (conflict with A3/A4, or a live-data premise, by operator decision): the `hot` order and popularity-pool tests of `test_random_videos.py`, the `mode=hot` feed-mode and NSFW cases of `test_similar.py`, and its `mode=recent` NSFW case. All are in `tests/archive/45_trending_from_source_instances/`, each with a header naming why and what still covers it.
- **`--compare`, attempt 4 (by hand).** One new red: `test_similar.py::test_a_mode_outside_the_ordered_set_answers_the_seed_its_pre_build_spelling_did[recommendations]`, an Engine 500 `Recommendations request failed` on an unseeded `/recommendations?limit=12`. The lane ran 135 s against a usual 48 s. The test passed alone, and the whole `test_similar.py` passed (75/75, 48 s) straight after. This matches the known intermittent Engine 500 (memory `upnext-pin-engine-500-intermittent`); the Engine log of the failing run was not retained, so the cause is not confirmed. The `mode=recent` cases disappeared as retired.
- **`--compare`, attempt 5 (by hand).** Exit 0, nothing moved: the suite is green.
- **Measured (R1-adjacent).** Dev `whitelist.db` is in `delete` (rollback) journal mode. The popular pool read (`fetch_popular_videos`, 5000 rows, threshold 3, NSFW off) takes 0.11 s, so the statement deadline is not a factor. The conftest `trending_seed` rewrite of 88,648 rows holds the write lock for 4.6 s (insert 4.4 s, commit 0.2 s). Each lane runs it once, under the Engine start lock but while other lanes' Engines are serving, so in a multi-lane run it is a candidate source of `database is locked` 500s near the Engines' 5 s busy timeout. Not observed as a cause; recorded as a risk.
- **Checkpoint gaps.** As the record's attempt 1 states: Phase 2's implement step skipped the durable tests its checkpoint named, so their reds surfaced only at the suite compare.

### Documentation (Step 9)

_Done by hand on 2026-10-03. Every claim was checked against the code. No `docs/wiki/` exists._

- `CONTEXT.md` — Feed mode lists trending; the **Hot** entry is removed; **Trending** gives the current state (`trending_ranks`, weekly stage, 10-day keep for a failing host, empty until the first fill, no fallback); **Popular** says the layer uses the Trending order.
- `README.md` — the home feed modes are Recommendations, Trending, Recent, Random and Popular.
- `client/README.md` — the `exclude` and fixed-order-feed lines name trending.
- `client/frontend/README.md` — the mode list and paging line name Trending; `hot` from the URL or storage reads as Trending; the rebuilt `dist/` must be committed (`test_frontend_dist.py`).
- `engine/server/README.md` — the `mode` values, the 400 `allowed` list and `mode=hot` → 400; Trending is empty until the first fill; the NSFW mode list; "a slow ordered-feed page" replaces the hot/popular example.
- `engine/server/api/recommendations/docs/OVERVIEW.md` — the ordered feeds are trending/popular/recent, with `ORDERED_FEED_SOURCE`; the trending order (CROSS JOIN from `idx_trending_ranks_order`, rank then listed likes/views/`video_id`/domain, catalogue rows only, no fallback, empty until filled); the popular layer's source is the Trending head, empty while `trending_ranks` is, and `home` with likes comes back short by popular's share until then.
- `engine/server/api/recommendations/docs/LAYER_PARAMS.md` — the popular layer's source is the first `pool_size` rows of the Trending order; the rank-round coverage of `pool_size` 5000; nothing returned until the first fill.
- `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` — node G3 reads "head of the Trending order".
- `engine/server/db/jobs/docs/UPDATER_WORKER.md` — the purpose and outputs include `trending_ranks`; new step 13 (trending stage, its failure rule and skips), with similarity renumbered to 14 and references updated; the no-change sync-join early return skips both stages; new "Trending Stage" section (hosts, fetch and retries, write and the 10-day age-out, exit status, effect on serving, first-fill command, log lines); the timer is weekly `OnCalendar=Fri *-*-* 20:00:00`, `Persistent=false`, replacing the stale daily `OnUnitInactiveSec`.
- `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` — the purpose list gains the trending stage (real HTTPS to the mini-prod's hosts; host failures do not fail the run). No `marker_to_stage` entry is documented.
- `DATA_BUILD.md` — the updater sequence gains trending ranks; the timer is weekly; §7 says `videos.popularity` is read by search's `sort=popularity`; new §8 points to the first-fill command.
- `DEPLOYMENT.md` — the ranking note names `trending_ranks`; the updater timer section names the trending stage, and a new paragraph covers its write lock and first fill; the ordered-feed load note says trending runs no sort.
- `docs/project/roadmap.md` — Delivered entry for issue 38; the obsolete `POPULAR_ORDER_BY` likes-term item is removed (the term and the constant are gone); the cursor item and F3-M3 name trending. The issue-17 Delivered entry is left as the record of that delivery.
- `docs/project/adr/0010-trending-from-source-instances.md` — the issue 38 path points at `archive/`; a dated note (2026-10-03) records the weekly cadence and the 10-day age-out, and the decision text is unchanged.
- `docs/project/issues/42-tags-on-cards-and-tag-search.md` — the issue 38 reference is marked `(archive)`, as its sibling lines are.
- Beyond the checklist: `docs/project/adr/0001-derived-interaction-event-ids.md` — the issue 38 path in the amendment points at `archive/`.
- Not changed: the security-audit runs (dated findings), archived issues and plans, `docs/project/plans/45-trending-from-source-instances.md` (its line 7 still names the pre-archive issue path), and `peertube-browser-service-review.md` (see the checklist).



### Harvest and issue (Step 10)

- Harvest record: `docs/project/plans/harvest-45-trending-from-source-instances-plan.md`. The checkpoints' tests now live in their subject files (`test_fetch_trending.py`, `test_moderation.py`, `test_random_videos.py`, `test_similar.py`, `test_popular_videos.py`, `test_updater_worker.py`, `test_frontend_feed_params.py`). Each moved test was verified by a mutation, and the closing `--compare` exited 0 with 269 passed.
- Source issue 38 was already archived by the operator with `Status: enhancement, superceded by 45-trending`, which is not `ready`, so it was left as it is.
