# Replace Hot with Trending from source instances

## Requirements

### Source

- Issue: `docs/project/issues/38-hot-trending-by-growth.md`. Its triage comment holds the decisions taken before planning. The build that delivers this plan closes it.
- Decision record: ADR-0010, `docs/project/adr/0010-trending-from-source-instances.md`. Glossary: **Trending** in `CONTEXT.md`.

### What was asked for

Hot is replaced by **Trending**: one global order built from each catalogue host's own PeerTube `sort=-trending` list, merged by rank. The home feed mode Hot becomes Trending, and the Recommendations mix's popular layer draws from the trending-ranked set.

### Purpose

Hot today ranks by `videos.popularity`, an age-decayed total that mostly surfaces the largest videos in the catalogue and never decays between writes. The goal is a feed of what is being watched now, at a cost the pipeline can afford. PeerTube already ranks each instance's videos by views over its last 7 days, so the order is fetched, not computed from our own count snapshots.

### Fetch

- **Request:** `GET https://<host>/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both`, one page per host. `-hot` and the instance's configured default algorithm are not used (ADR-0010).
- **Hosts:** every host with at least one embedded video in `whitelist.db`, minus `instance_denylist`. `health_status` is not consulted. (Operator. Rejected: healthy `instances` rows minus the denylist, which asks hosts that cannot contribute a row.)
- **NSFW:** `nsfw=both`, so flagged videos are ranked and the Engine's per-request NSFW filter decides who sees them. (Operator. Probed 2026-10-02: without it instances drop flagged videos. `total` for tilvids.com is 3,053 → 3,070 with `nsfw=both`, peertube.tv 731 → 735, framatube.org and video.blender.org unchanged. v1-v3 hosts were not probed with `nsfw=both`.)
- **Matching:** a listed video is identified as the crawler identifies it, `uuid` falling back to `id` (`engine/crawler/src/videos-worker.ts:666`), with the host as `instance_domain`. The fetch ingests nothing. A listed video not in the catalogue (in `videos` and `video_embeddings`) never enters the order.

### Storage

- A table in `whitelist.db` holds the ranks: host, video id, rank (1-100), the listed video's likes and views, and when the host's list was fetched. (Operator. Rejected: a separate file swapped in per ADR-0008, which keeps writers off the serving DB but needs its own handle, swap path and cross-DB lookup in the Engine.)
- **Partial failure, per host:** a host that answers has its rows replaced, and a host that fails keeps its previous list. A list fetched more than 3 days ago is dropped. One bad run never empties Trending, and a dead host ages out. (Operator. Rejected: all-or-nothing behind an answer-rate threshold, and keeping only the hosts that answered.)
- A host removed by the denylist or a stale-host purge loses its rows along with its videos.

### Order

- Rows are interleaved by rank: every host's #1, then every #2, and so on. Within a round, ties break on the listed likes, then the listed views, then `video_id`, then `instance_domain`. These are descending, the same direction the current orders use for their last keys (ADR-0010).
- The order is finite. The Trending feed ends when its rows run out, and it never falls back to the popularity order.
- The existing per-request filters still apply: error threshold, NSFW, the `exclude` list and serving moderation.

### Where Trending is used

- **Home feed mode:** `trending` replaces `hot` in the Engine's `FEED_MODES` and `ORDERED_FEED_MODES`, and in the frontend's `FEED_MODES`. The button is labelled "Trending". The Engine answers `mode=hot` with the 400 it gives any unknown mode.
- **Stored and linked `hot`:** the frontend reads `hot` from the URL or `localStorage` as `trending`, so a returning visitor who chose Hot lands on Trending. (Operator. Rejected: no alias, which drops them to Recommendations, and an Engine-side synonym.)
- **Recommendations popular layer:** the layer's pool is the first `pool_size` rows of the Trending order instead of the popularity order. Everything after the pool is unchanged: the caps and the uniform or similarity-weighted draw.

### Updater stage

- Daily, inside the existing updater run: after the Engine is started again and before the similarity stage. (Operator.)
- A failure of the stage itself, as opposed to a host that fails, is logged. The similarity stage still runs, and the run exits non-zero at the end. A failing similarity stage never skips the trending stage, because the trending stage runs first. (Operator. Rejected: last in the run with a fatal failure, where a similarity failure would skip trending for the day.)
- The stage is a job script that can also be run alone, by hand or for the first fill.

### Acceptance criteria

- A1. After one run of the trending job against hosts that answer, the ranks table holds at most 100 rows per asked host, each carrying the host's rank, listed likes and views, and the fetch time.
- A2. A host that fails on a later run keeps its earlier rows. Rows of a host last fetched more than 3 days ago are gone after the next run. A denied host is never asked.
- A3. `mode=trending` on an unseeded `/recommendations` returns catalogue videos in rank-interleaved order, with the tie-breaks above. It pages through `exclude` like the other ordered feeds and ends when the ranked rows run out. `mode=hot` returns 400 with `trending` in `allowed`.
- A4. The Recommendations popular layer draws only from videos in the ranks table.
- A5. The home page shows a "Trending" button instead of "Hot". `?mode=hot`, or a stored `hot`, opens Trending.
- A6. The updater run calls the trending stage between the Engine start and the similarity stage. A trending stage failure does not stop the similarity stage, and the run exits non-zero.
- A7. The documents describing Hot (`OVERVIEW.md`, `LAYER_PARAMS.md`, `UPDATER_WORKER.md`, `DATA_BUILD.md`, the READMEs, `CONTEXT.md`) describe Trending instead.

### Out of scope

- `videos.popularity`, `recompute-popularity.py` and its updater step, the `/api/video` popularity write, and the search sort `popularity` all stay as they are. They keep a reader in search. (Operator.)
- The Popular mode (all-time likes) is unchanged.
- No backwards compatibility beyond the frontend `hot` → `trending` read.

### Consistency constraints

- The job follows the existing `engine/server/db/jobs/*.py` scripts: argparse, a `--db` path, `logging`, and `urllib` for HTTP as `sync-whitelist.py` and `updater-worker.py` do. It takes the updater's existing `--concurrency`, `--timeout-ms` and `--max-retries` values.
- The table is created the way other `whitelist.db` tables are created (`whitelist_migrations.py`).
- The Trending order is one more entry beside the existing ordered feeds in `engine/server/data/random_videos.py`, served by the same `_handle_ordered_feed` path.

### Conflicts

- ADR-0010 says the stage runs "after the merge". That holds: it runs after the Engine restarts, which is after the merge.
- The `CONTEXT.md` **Popular** entry says the mix's popular layer "uses the Hot order". It will use the Trending order, so the entry is updated with the build.

### Checked against the tree (2026-10-02)

- `engine/server/data/random_videos.py:15-36`: `POPULAR_ORDER_BY` (`v.popularity DESC`, likes, views, published_at, video_id, instance_domain) is both `ORDERED_FEED_ORDER_BY["hot"]` and the order of `fetch_popular_videos`.
- `fetch_popular_videos` feeds the popular layer (`engine/server/api/recommendations/candidates/popular_videos.py:53`, wired in `builder.py:114` and `server.py:405`). The layer takes the top `pool_size` rows (`DEFAULT_POPULAR_POOL_SIZE = 5000`, `server_config.py:68`), caps per author and instance, then draws.
- `_handle_ordered_feed` (`engine/server/api/handlers/similar.py:759`) pages one global order through `fetch_ordered_page` with `LIMIT/OFFSET`, skipping `exclude` keys, in up to 4 chunks, then applies serving moderation.
- The modes are listed in two places. `FEED_MODES` and `ORDERED_FEED_MODES` are in `similar.py:105-107` (an unknown mode gets a 400 with `allowed`). The frontend's `FEED_MODES` is in `client/frontend/src/data/feed-params.ts:6`, where `parseFeedMode` maps unknown values to `recommendations`. The Hot button is at `client/frontend/index.html:41` and `videos.html:41`. The Client backend passes `mode` through (`client/backend/server.py:96`).
- `popularity` has other readers and writers: the search sort (`engine/server/data/search.py:86`), the `/api/video` refresh write (`handlers/video.py:379-405`), and `recompute-popularity.py --incremental` in the stopped window (`updater-worker.py:1376`).
- The updater runs in this order (`updater-worker.py:1115-1444`): crawl into staging, stop the Engine, merge, denylist prune, recompute popularity, ANN build, start the Engine, then the similarity stage. Denied hosts come from `load_denied_hosts(prod_db)`. A `--sync-join-whitelist` run with no changes returns early (`:1328`). The systemd timer runs daily (`OnUnitInactiveSec=1d`, `UPDATER_WORKER.md:227-230`).
- The Engine holds one shared read-write connection on `whitelist.db` (`engine/server/data/db.py:77`), serialised by `db_lock`.
- The crawler's `video_id` is `uuid ?? id` (`engine/crawler/src/videos-worker.ts:666`).

Not checked: live row counts in `whitelist.db`, because the sandbox refuses inline interpreter code. The 1,764 healthy-host figure comes from the triage probe.

## High-level plan

### Approach

1. **Ranks table.** Add a ranks table to `whitelist.db` through the existing migration path. Its key is (host, video id), and it carries the rank, the listed likes and views, and the fetch time. A stale-host or denylist purge deletes a host's rows together with its videos.
2. **Fetch job.** A new job script in `engine/server/db/jobs/` reads the host list (hosts with embedded videos, minus the denylist) and asks each host for its trending page concurrently, with the updater's timeout and retry settings. The writes go in one short transaction: replace the rows of every host that answered, keep the rows of every host that failed, and drop any host's rows older than 3 days. It logs hosts asked, answered and failed, and rows written. A host's whole list is stored, catalogue or not. The catalogue join happens at read time, so a video the crawl adds later appears without a refetch. → Fetch, Storage, A1, A2.
3. **Engine order.** A Trending entry beside the other ordered feeds selects only videos that have a rank row, joined to the catalogue as today, ordered by rank, then listed likes, listed views, `video_id` and `instance_domain`. `trending` replaces `hot` in the mode lists, and `_handle_ordered_feed` serves it unchanged. The popular layer's pool query uses the same order with its `pool_size` limit. → Order, A3, A4.
4. **Updater stage.** The updater calls the job after the Engine starts and before the similarity stage, catches the stage's failure, logs it, carries on, and fails the run at the end. → Updater stage, A6.
5. **Frontend.** Rename the mode and the button to Trending, and make `parseFeedMode` read `hot` as `trending`. → A5.
6. **Documents.** Update the documents listed in A7. → A7.

### Alternatives considered

- **Storage:** a separate swapped file (ADR-0008 pattern), rejected above. With the table, Trending is one join on the serving connection.
- **Storing only catalogue matches** at fetch time: this saves rows, but a video crawled after the fetch would stay invisible until the next fetch. It also needs the catalogue read inside the job. Storing the whole list and joining at read time is simpler. At most about 176,000 rows (1,764 × 100) is small.
- **Fetching inside the Node crawler**, which already has HTTP concurrency and retry code. Rejected: the crawler writes to staging, which only reaches prod through the stopped-window merge, and `merge_rules.json` merges `INSERT_ONLY`. That breaks the "outside the stopped window" decision and the replace-per-host rule.
- **Partial failure, host list, NSFW, `hot` alias, stage placement:** the rejected options are recorded under Requirements.

### Gotchas and risks

- R1. **Write while serving.** The job writes `whitelist.db` while the Engine reads it through one shared connection. The write is one transaction of up to about 176k rows. While it holds the write lock, Engine reads can wait or hit "database is locked". The build checks the DB's journal mode and the Engine connection's busy timeout, and measures the transaction's duration. The fetch itself (network) happens before the transaction opens.
- R2. **Cold start.** The table is empty until the job first runs, so the Trending feed is empty and the popular layer gets an empty pool. The deploy runs the job once by hand. The build checks what the mixer does with an empty popular layer.
- R3. **Popular layer pool depth.** With 1,764 hosts, a 5,000-row pool covers roughly the first three rounds (every host's #1-#3, fewer after the catalogue join). The pool changes character from "biggest videos" to "small and large instances equally". This is intended (ADR-0010), and `pool_size` stays the knob.
- R4. **Large hosts contribute few rows per round.** The feed holds about 1,764 rows per round, so a visitor pages through many small instances' #1 before any host's #2. This is intended. Paging through `exclude` still ends after about 500 shown rows (an existing limit, roadmap "cursor parameter").
- R5. **Run time.** About 1,764 requests at the updater's concurrency (e.g. 5) and timeout (e.g. 15 s). A slow tail of dead hosts can stretch the stage. The similarity stage waits for it.
- R6. **Old hosts.** `nsfw=both` was not probed on v1-v3, about 27 hosts at most. If one rejects it, that host simply fails and keeps or ages out its list.
- R7. **Early-returning runs.** A `--sync-join-whitelist` run with no changes returns before the stage, so it skips trending that day. The timer's default run is not sync-join.
- R8. **Overlap with issue 08.** Both touch `random_videos.py` and the updater docs. Issue 08 appears to be merged (`b423159 Merge branch '08'`), which was not confirmed.

### Limitations

- Trending is at most a day old, on top of the instances' own 7-day windows, and up to 3 days old for a failing host.
- The order is per-instance relative. A 25-view #1 sits beside a 400-view #1 (ADR-0010).
- A video trending on an instance we have not crawled yet appears only after the normal crawl adds it.

### Tradeoffs for the operator

- One daily write to the serving DB, in exchange for the simplest read path (R1).
- An empty Trending until the first fetch, accepted with a by-hand first fill (R2).
- Equal exposure per rank across instances, which reshapes both the feed and the popular layer (R3, R4).
