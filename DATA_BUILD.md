# Data Build (Crawler + Jobs)

This document explains how to build the local SQLite dataset plus derived
artifacts (embeddings, ANN index, caches) used by the API.

All paths below are relative to the repository root.

## Outputs
- `engine/crawler/data/crawl.db` raw crawl database.
- `engine/server/db/whitelist.db` filtered dataset used by the API.
- `engine/server/db/whitelist-video-embeddings.faiss` and `engine/server/db/whitelist-video-embeddings.faiss.json` ANN index + metadata.
- `engine/server/db/similarity-cache.db` precomputed similar cache (optional).
- `engine/server/db/random-cache.db` random rowid cache (optional).

## Prerequisites
- Node.js + npm for the crawler (`engine/crawler/package.json`).
- Python 3.10+ for jobs (`engine/server/requirements.txt`).
- Optional CUDA if you plan to run embeddings with `--gpu`.

## Automatic background updater
You can run the same build/update flow automatically with the updater worker:

- Worker entrypoint: `engine/server/db/jobs/updater-worker.py`
- It runs: crawl to staging -> embeddings -> merge to prod -> popularity -> ANN rebuild -> similarity precompute.
- Systemd installation: `install-service.sh --with-updater-timer`
- Timer runs daily (`OnUnitInactiveSec=1d`).

Detailed behavior, flags, lock/resume logic, and systemd notes are documented in:

- `engine/server/db/jobs/UPDATER_WORKER.md`

## 1) Crawl data

### Build crawler
```bash
cd engine/crawler
npm install
npm run build
```

### Instance discovery
Default source is the JoinPeerTube whitelist JSON.
```bash
cd engine/crawler
npm run crawl:instances
```

Useful flags:
- `--whitelist-url <url>` change the source list.
- `--expand-beyond-whitelist` follow federation graph beyond the whitelist.
- `--graph` store follower/following edges between instances.
- `--resume` reuse progress stored in `instance_crawl_progress`.
- `--concurrency`, `--timeout`, `--max-retries`, `--max-errors` control crawl speed and retry policy.

Data source and limits:
- Uses `GET /api/v1/server/following` and `GET /api/v1/server/followers`.
- Page size is fixed at 50.
- Only public instance metadata is collected.

### Instance health checks
```bash
cd engine/crawler
npm run crawl:instances:health
```

Useful flags:
- `--errors-only` check only instances with `health_status=error`.
- `--min-age-days`, `--min-age-min`, `--min-age-sec` limit checks by last health timestamp.
- `--host <host>` check a single instance.

Data source and limits:
- Uses `GET /api/v1/video-channels?start=0&count=1`.

### Channel crawl
```bash
cd engine/crawler
npm run crawl:channels
```

Useful flags:
- `--check-health` only checks per-channel health and writes errors.
- `--resume` reuse progress stored in `channel_crawl_progress`.

Data source and limits:
- Uses `GET /api/v1/video-channels?start=<offset>&count=50`.
- Only channels hosted on the instance itself are stored.

### Channel video counts
```bash
cd engine/crawler
npm run crawl:channels:videos-count
```

Useful flags:
- `--resume` skips channels with existing counts or errors.
- `--errors` processes only channels with recorded errors.

### Video crawl
```bash
cd engine/crawler
npm run crawl:videos
```

Useful flags:
- `--new-videos` skip videos that already exist in `videos` (by id + instance).
- `--stop-after-full-pages <N>` stop after N pages that contain only existing videos.
- `--resume` reuse progress stored in `video_crawl_progress`.
- `--errors` process only channels with recorded errors.

Data source and limits:
- Uses `GET /api/v1/video-channels/<channel>/videos?start=<offset>&count=50`.
- Default host concurrency is limited to avoid rate limiting.

Each video's PeerTube language code (for example `en`) is stored in `videos.language`. A payload with no language, or with a null language id, stores NULL. Any crawler command that opens an existing `crawl.db` adds the `language` column to it (`migrateVideosLanguage` in `engine/crawler/src/db.ts`). Rows already in the table keep NULL until a video crawl without `--new-videos` revisits them.

### Tags and comments enrichment
These are slower because they hit per-video endpoints.
```bash
cd engine/crawler
npm run crawl:videos:tags
npm run crawl:videos:comments
```

Useful flags:
- `--host-delay <ms>` throttles requests per host (default 200ms).
- `--concurrency` limits number of hosts processed in parallel.

Data source and limits:
- Uses `GET /api/v1/videos/<uuid>` for tags and comment counts.

## 2) Filter to JoinPeerTube whitelist
This step builds the API dataset in `engine/server/db/whitelist.db`.

Run it only after the crawl stages in step 1 have **finished**. Against a partial crawl
it succeeds and copies whatever exists, which produces an empty or half-populated dataset
that only shows up several steps later as "No embeddings found in database".

```bash
python3 engine/server/db/jobs/sync-whitelist.py \
  --db engine/crawler/data/crawl.db \
  --output-db engine/server/db/whitelist.db
```

`unable to open database: engine/crawler/data/crawl.db` means the crawl has not run at
all — the file and its parent directory are created by the crawler, not by this job.

Notes:
- Default whitelist URL is JoinPeerTube and can be overridden with `--url`.
- `--mode include` keeps only whitelisted hosts (default).
- `--mode exclude` keeps hosts not in the whitelist.
- Each whitelist entry becomes a host through `data.moderation.normalize_host_token`, a port of the crawler's `normalizeHostToken`, so the job stores the same spelling the crawler does:
  - A URL-like entry (`http://…`, `https://…`, or anything containing `/`) keeps only its hostname, lowercased. Scheme, userinfo, port and path are dropped, IPv6 literals keep their brackets, and internationalised names become punycode.
  - A bare entry is lowercased and has only its leading and trailing dots trimmed, so a bare `host:port` keeps its port.
  - Entries that normalise to nothing (`""`, `.`, `https://`) are skipped. The job fails with "Whitelist contained no hosts." when no entry is left.
- If the source DB schema has `video_embeddings`, they are copied into whitelist.db.

The job checks both schemas before it copies anything:
- The `crawl.db` tables must hold every column in `engine/crawler/schema.sql`. A `crawl.db` that no crawler command has opened since `videos.language` was added fails with `missing columns: language`. Run any crawler command against it once.
- An existing `whitelist.db` must match that schema exactly, plus the whitelist-only `popularity` column. An outdated one fails with the missing columns and a pointer to `migrate-whitelist.py`. A new `whitelist.db` is created with the current schema.

If the whitelist DB schema is outdated, migrate it:
```bash
python3 engine/server/db/jobs/migrate-whitelist.py --db engine/server/db/whitelist.db
```

The migration is additive: it adds missing columns such as `videos.language` without touching rows, `videos_fts` or its triggers, and a second run does nothing. `scripts/run-dataset-build.sh` runs `sync-whitelist.py` without migrating, so migrate an existing `whitelist.db` before a scripted build too.

Upgrade order for a schema change such as `videos.language`:
1. Merge to main.
2. Run any crawler command against `crawl.db` once, so it gains the column.
3. Run `migrate-whitelist.py` against every copy of `whitelist.db`, the prod/server database included.
4. Restart the Engine. For what `/api/video` does against an unmigrated `whitelist.db`, see `engine/server/README.md`.

`/api/video` writes refreshed video metadata into `whitelist.db` (see `engine/server/README.md`). The next sync deletes `videos` and reloads it from `crawl.db` (`rebuild_content_tables`), so those refreshes are lost.

### Repair video channel names (one-time migration)
PeerTube channel ids are unique only per instance. Rows written before the video crawl keyed channel metadata by host plus id can hold the display name of a same-id channel on another instance. `repair-video-channel-names.py` sets each video's `channel_name` to the `display_name` of its own `(channel_id, instance_domain)` channel.

This is a migration of shared databases. Run it on main after merge only, never from a worktree. Run it outside an updater cycle, with the Engine idle or stopped: on `whitelist.db` it drops the `videos_fts` triggers, runs the update, recreates the triggers and rebuilds `videos_fts`, and the rebuild holds the write lock.

Order:
1. Merge to main.
2. Repair the crawl database:
   ```bash
   python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db
   ```
3. Run the same command with `--db` pointing at every copy of `whitelist.db`, the prod/server database included. `engine/server/db/jobs/merge_rules.json` merges `videos` as `INSERT_ONLY`, so the updater never corrects existing prod rows.
   ```bash
   python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/server/db/whitelist.db
   ```
4. Operator follow-up, because embeddings include `channel_name` (step 3): `build-video-embeddings.py --db-path engine/server/db/whitelist.db --force`, then `build-ann-index.py` (step 4) and `precompute-similar-ann.py` (step 5) with the flags shown there. Schedule this with the stable-ANN-ids cutover (`docs/project/issues/08-stable-ann-ids.md`) so the index is rebuilt only once.

Behaviour:
- `--db PATH` is required and has no default. A path that is not an existing file is rejected with exit code 2 and `database not found`.
- It changes only rows whose own channel exists with a non-empty `display_name` that differs from the stored `channel_name`. Rows with no channel row or an empty `display_name` keep their name. It never writes `channels`.
- It logs `channel names repaired rows=N`. It is idempotent: a second run logs `rows=0`.
- On a database with `videos_fts` it rebuilds the index on every run, even when no row changed, and raises `RuntimeError` if the `videos_fts` row count differs from `videos`. The update is already committed by then, so recover from a failed rebuild by running the job again.
- On `crawl.db`, which has no `videos_fts`, it skips the index steps.
- The index path loads `sync-whitelist.py` for its FTS helpers, and that module parses `engine/crawler/schema.sql` on load, so run the job from a full checkout.

## 3) Build embeddings
Embeddings use SentenceTransformers. The text payload is built from:
- `title`
- `description`
- `tags_json`
- `category`
- `channel_name`
- `comments_count`

Default model is `paraphrase-multilingual-MiniLM-L12-v2` (384-dim). It is multilingual
because the corpus is mostly non-English: an English-only model produces an English-only
semantic space, in which a query cannot reach content written in another language.
```bash
python3 engine/server/db/jobs/build-video-embeddings.py \
  --db-path engine/server/db/whitelist.db
```

Changing the model is not a local change. Every row in `video_embeddings` must come from
one model, so a change needs `--force`, a rebuilt ANN index, and the Engine's
`QUERY_ENCODER_MODEL` set to the same name; the Engine refuses to start against an index
built from a different model, and serves no vector search results when the query encoder
disagrees with the index. `run-dataset-build.sh --embed-model <name>` passes the choice
through the whole pipeline.

Useful flags:
- `--model-name <model>` choose a different SentenceTransformer.
- `--batch-size <N>` trades RAM for throughput.
- `--force` recompute all embeddings.
- `--gpu` uses CUDA and fails if it is unavailable.

## 4) Build FAISS ANN index
The index uses `video_embeddings.rowid` as ids.

One of `--gpu` or `--cpu` is required.

```bash
python3 engine/server/db/jobs/build-ann-index.py \
  --db-path engine/server/db/whitelist.db \
  --index-path engine/server/db/whitelist-video-embeddings.faiss \
  --meta-path engine/server/db/whitelist-video-embeddings.faiss.json \
  --normalize --gpu
```

"No embeddings found in database" means step 3 has not produced rows yet. Check
`select count(*) from video_embeddings` in `whitelist.db` before rebuilding the index.

Useful flags:
- `--nlist`, `--m`, `--nbits` tune IVFPQ.
- `--train-sample` controls training set size.
- `--batch-size` controls memory usage when adding vectors.

## 5) Precompute similarity cache (optional)
This speeds up similar video fetches for the video page. One of `--gpu` or `--cpu` is
required unless `--reset-only` is used.
```bash
python3 engine/server/db/jobs/precompute-similar-ann.py \
  --db engine/server/db/whitelist.db \
  --index engine/server/db/whitelist-video-embeddings.faiss \
  --out engine/server/db/similarity-cache.db \
  --top-k 20 \
  --nprobe 16 \
  --reset --gpu
```
This output is large — expect the cache to exceed the source database on a full dataset.

## 6) Precompute random cache (optional)
This prepares a random rowid pool for the random feed.
```bash
python3 engine/server/db/jobs/precompute-random-rowids.py \
  --db engine/server/db/whitelist.db \
  --out engine/server/db/random-cache.db \
  --size 5000 \
  --filtered \
  --max-per-author 100 \
  --max-per-instance 0 \
  --reset
```
An Engine started with refresh off (`--dev` or `--no-random-cache-refresh`) serves any non-empty cache it finds as it is, including this 5000-row one, and builds the cache only when the table is missing or empty; a refresh-on start (the default) rebuilds it towards `DEFAULT_RANDOM_CACHE_SIZE` (see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`). If a running Engine is rebuilding the cache, the job waits for that rebuild to finish, up to an hour, rather than failing with "database is locked".

## 7) Recompute popularity (one-time after dataset build)
Materialize a `videos.popularity` score for fast popular queries.
```bash
python3 engine/server/db/jobs/recompute-popularity.py \
  --db engine/server/db/whitelist.db \
  --like-weight 2.0 \
  --reset
```

## Logs and progress
All crawler and job commands log to stdout. Redirect if needed:
```bash
npm run crawl:channels -- --resume > /tmp/crawl-channels.log
```

Check progress directly in SQLite:
```bash
sqlite3 engine/crawler/data/crawl.db "select count(*) from instances;"
sqlite3 engine/crawler/data/crawl.db "select status, count(*) from channel_crawl_progress group by status;"
sqlite3 engine/crawler/data/crawl.db "select status, count(*) from video_crawl_progress group by status;"
sqlite3 engine/server/db/whitelist.db "select count(*) from videos;"
sqlite3 engine/server/db/whitelist.db "select count(*) from video_embeddings;"
sqlite3 engine/server/db/similarity-cache.db "select count(*) from similarity_sources;"
sqlite3 engine/server/db/random-cache.db "select count(*) from random_rowids;"
```
