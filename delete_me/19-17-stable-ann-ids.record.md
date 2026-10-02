# Build record - 17-stable-ann-ids

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/19-17-stable-ann-ids.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Stable ANN ids\n\n## Requirements\n\n### Asked for\n\nIssue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2). The FAISS index and every reader that turns an id back into an embedded video switch from `video_embeddings.rowid` to a deterministic `ann_id` derived from `(video_id, instance_domain)`. ADR-0006 records the decision. `CONTEXT.md` defines **ANN id**.\n\n### Purpose\n\nCorrectness. `video_embeddings` can change without an index rebuild following, or with the rebuild failing: a merge, a host purge, a whole-table reload, a `--force` re-embed, a migration. In every such case the index must never return the wrong video. At most it misses videos it has not indexed yet. The build must not block later incremental index add or remove (F3/F4-M2), and it does not build them.\n\n### What the current code does (checked against the tree and the live DB, read-only)\n\n- `build-ann-index.py:250-256` calls `add_with_ids` with `video_embeddings.rowid` and writes `id_source: \"video_embeddings.rowid\"` (line 284). The live sidecar `engine/server/db/whitelist-video-embeddings.faiss.json` reads the same.\n- The live `engine/server/db/whitelist.db` has 890,052 `video_embeddings` rows with rowids exactly 1..890,052. Its primary key is `(video_id, instance_domain)`, there are 1,548 hosts all already lowercase and trimmed, and every `video_id` is text.\n- A 63-bit blake2b of `video_id::instance_domain` over all 890,052 keys gave 0 collisions, and no key hashed to 0.\n- Rowid-keyed readers:\n  - `data/ann.py`: `compute_similar_items` (and its `ids > 0` filter), `search_index` (`exclude_rowid`), and `search_similar_above`, the up-next fallback search, which keeps rowid hits through the same `ids > 0` filter, excludes `seed[\"rowid\"]` and calls `fetch_metadata` by rowid. The Engine's nprobe helpers (`_extract_ivf`, `get_nprobe`, `apply_nprobe`, `set_nprobe`) live in this file too, and `server.py` imports `set_nprobe` from it; `precompute-similar-ann.py` keeps its own `set_nprobe` copy.\n  - `data/embeddings.py`: the seed's `rowid`/`exclude_rowid` in `resolve_seed` and in the three seed queries.\n  - `data/metadata.py`: `fetch_metadata`, which selects `WHERE e.rowid IN (...)`.\n  - `data/search.py`: `vector_candidates`.\n  - `api/handlers/similar.py`: `_handle_vector_search`.\n  - `data/random_cache.py` and `data/random_videos.py`: the `random_rowids` table.\n  - `db/jobs/precompute-random-rowids.py`.\n  - `db/jobs/precompute-similar-ann.py`: `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*` and the main loop.\n- Rowid-renumbering writers:\n  - `build-video-embeddings.py`: DELETE under `--force`, then `INSERT OR REPLACE`.\n  - `sync-whitelist.py`: `rebuild_content_tables` deletes the whole table, then does `INSERT ... SELECT`.\n  - `merge-staging-db.py`, through `merge_rules.json` `INSERT_OR_REPLACE` on `video_embeddings`, copying the columns prod and staging share.\n  - `whitelist_migrations.migrate_videos_schema`, which drops `video_embeddings`.\n- The updater (`updater-worker.py:1040-1150`) stops the service, merges, rebuilds the ANN, precomputes, and restarts in a `finally`. So a failed ANN build restarts the Engine on the old index against the renumbered rows.\n- The Engine never writes the random cache before listening. At start it opens `random-cache.db` read-only through `open_random_cache_if_usable` (`random_cache.py:283-302`), which accepts any non-empty `random_rowids` table without checking its shape. Every build runs through `build_random_cache` (`random_cache.py:208-245`) into a per-pid temp file, which the Engine's background worker renames over the cache and swaps in. For when builds run (`DEFAULT_RANDOM_CACHE_REFRESH`, `--dev`, `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`) see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`. Under refresh off (`--dev`, `server.py:316-319`) a stored non-empty cache is served as it is. `precompute-random-rowids.py` keeps an `--out` that already holds `--size` rows, counted through `random_rowids_count` without checking their shape.\n- The similarity cache (`similarity_items`) is keyed by `(video_id, instance_domain)` text and holds no rowids.\n- `videos_fts` joins `videos.rowid` as FTS5 external content. That link is not an ANN id.\n- The Engine verifies the index sidecar at start in `embedding_space.assert_index_matches_embeddings`, which checks model and dimension today.\n- Not checked: whether any deployed crawl DB that `sync-whitelist.py` reads from already holds `video_embeddings` rows. The requirement below covers both cases.\n\n### Acceptance criteria\n\n- **AC1:** One helper computes `ann_id` as blake2b with an 8-byte digest of `video_id + \"::\" + normalize_host(instance_domain)`, masked to 63 bits. The result is positive, non-zero and safe as a signed int64. The same key gives the same id in any process and any DB.\n- **AC2:** `video_embeddings` carries `ann_id INTEGER NOT NULL` with a UNIQUE index.\n  - A new `whitelist_migrations.migrate_video_embeddings_schema` rebuilds an existing table into that shape, filling the column from the helper through `create_function`. `migrate-whitelist.py` runs it.\n  - Every job that creates the table creates the same shape.\n  - A collision, including an id of 0, fails the write loudly. The write never probes for another id.\n- **AC3:** Every writer stores the helper's `ann_id`.\n  - `build-video-embeddings.py` computes it.\n  - `merge-staging-db.py` preserves it.\n  - `sync-whitelist.py` copies it when the source has the column and computes it when the source has embeddings without it, so an older crawl DB does not force a re-embed.\n  - Re-running a writer, or replacing a row through `INSERT OR REPLACE`, leaves the video's `ann_id` unchanged.\n- **AC4:** `build-ann-index.py` adds vectors with `ann_id` as their ids and writes `id_source: \"video_embeddings.ann_id\"`. It fails with a message naming `migrate-whitelist.py` when the column is missing.\n- **AC5:** The Engine refuses to start when the index sidecar's `id_source` is not `video_embeddings.ann_id`, the same way it refuses a model mismatch today.\n- **AC6:** These readers resolve embedded videos by `ann_id`:\n  - similar: the seed and its exclusion, the ANN results, and raw vector search;\n  - search's vector half;\n  - `fetch_metadata`;\n  - the random cache (`random_cache.py`, `random_videos.py`, `precompute-random-rowids.py`).\n\n  A stored random cache in the old `random_rowids` shape is detected and repopulated, not read. Afterwards no reader resolves an embedded video by rowid.\n- **AC7:** `precompute-similar-ann.py` uses `ann_id` for its index ids and its target lookup. Its output keys are unchanged, and its incremental selection stays keyed on `(video_id, instance_domain)`.\n- **AC8 (the purpose, observed):** build an index, then renumber the DB's rows (a delete-and-reinsert of every row, as `sync-whitelist.py` does) or purge a host, with no index rebuild. Similar and search then return only videos whose identity matches the vector indexed for them.\n- **AC9:** The updater's full cycle (merge \u2192 ANN build \u2192 precompute) runs on the new id source. `DATA_BUILD.md`, `DEPLOYMENT.md` and the updater docs carry the one-time migrate-then-rebuild step for existing DBs.\n\n### Scope\n\nIn scope: AC1-AC9, including the random cache, as the operator decided.\n\nOut of scope:\n- incremental FAISS add or remove (F3/F4-M2);\n- rebuilding or re-keying the similarity cache;\n- `videos_fts`;\n- backward compatibility with rowid indexes (a `rowid` sidecar is refused, not read);\n- the crawler.\n\nOne build, correctness only, as the operator decided.\n\n### Consistency constraints\n\n- Job CLIs keep their current arguments.\n- Refusal messages follow `data/embedding_space.py`: say what is wrong and name the command that fixes it.\n- The migration follows the existing `migrate_*_schema` table-rebuild pattern in `whitelist_migrations.py`.\n- Hosts go through the existing `data/moderation.normalize_host`.\n\n### Conflicts\n\n- The issue asks the updater to \"keep ANN id consistency before rebuild/precompute\". Under AC2 and AC3 the schema guarantees the column, so the updater needs no step of its own beyond the migration having run once. The operator accepted this reading by confirming AC2, AC3 and AC9.\n- Test fixtures in 9 `tests/active` files (`conftest.py`, `test_blocks.py`, `test_dislike_profile.py`, `test_dislikes.py`, `test_frontend_reactions.py`, `test_internal_client_reads.py`, `test_metadata.py`, `test_profiles.py`, `test_random_videos.py`) and 2 job tests (`test-moderation-integration.py`, `test-orchestrator-smoke.py`) insert into `video_embeddings` without `ann_id`. NOT NULL breaks them, so they change with the build.\n\n## High-level plan\n\n### Approach\n\nA small module holds the one helper (for example `engine/server/data/ann_ids.py`), and jobs import it the way they already import `data.*`. The build runs in four phases.\n\n- **P1: id, schema, writers (AC1-AC3).**\n  - `migrate_video_embeddings_schema` rebuilds the table with `ann_id INTEGER NOT NULL`, filled through `create_function`, then creates the UNIQUE index. `migrate-whitelist.py` calls it through `migrate_whitelist_schema`.\n  - `build-video-embeddings.init_schema` and `sync-whitelist`'s schema create the same shape.\n  - `build-video-embeddings` computes the id per row.\n  - `merge-staging-db` needs no code change, because it merges the columns prod and staging share, and staging (created by `build-video-embeddings`) now carries `ann_id`.\n  - `sync-whitelist` copies `ann_id` when the source has it and computes it through the registered function otherwise.\n- **P2: index build and gate (AC4, AC5).** `build-ann-index` reads and adds `ann_id` and writes the new `id_source`. `assert_index_matches_embeddings` also checks `id_source`.\n- **P3: runtime readers (AC6, AC8).**\n  - Seeds carry `ann_id` and `exclude_ann_id`.\n  - `fetch_metadata` is keyed by `ann_id`, and `ann.py`, `search.vector_candidates` and `similar._handle_vector_search` follow it.\n  - The random cache stores `ann_id`. `ensure_random_cache_schema` runs only on a build's fresh temp file, so it never sees a stored table. Old-shape detection goes in `open_random_cache_if_usable`, which treats an old `random_rowids` table as unusable so the Engine serves from the DB and runs a background build. `build_random_cache` never reads the stored file, so it cannot detect it. The precompute job's keep check also treats an old-shape `--out` as not kept, and `precompute-random-rowids.py` otherwise follows the cache.\n- **P4: precompute and cycle (AC7, AC9).** `precompute-similar-ann` uses `ann_id` for its FAISS ids and its target lookup. The orchestrator smoke test runs the updater's full cycle on the new id source. The documentation in AC9 is the build's close-out, not a phase.\n\n### Alternatives considered\n\n- **A separate `ann_ids` mapping table:** every reader gains a join, and the mapping must be kept in step with embeddings on purge and reload. A column on `video_embeddings` has neither cost.\n- **Pinning the rowid** (INTEGER PRIMARY KEY alias, UPSERT instead of INSERT OR REPLACE, `sync-whitelist` copying the source rowid): the cheapest option, but the id stays positional and differs between staging and prod, so it misses the purpose.\n- **An assigned counter:** stable within one DB, but staging and prod assign different numbers, so every merge needs a remap.\n- **Python `hash()`:** salted per process, so not deterministic.\n- **xxhash:** a new dependency. blake2b is in the stdlib.\n- **Full 64-bit ids:** negative ids clash with FAISS's `-1` empty result and the `ids > 0` filter in `ann.py`.\n- **Probing for a free id on collision:** the id would depend on insertion order, which is the coupling this build removes.\n- **ADD COLUMN plus backfill instead of a table rebuild:** it rewrites every row anyway, and it leaves the column nullable.\n- **No migration (rebuild the dataset):** the operator chose the table rebuild.\n\n### Risks\n\n- **R1: the one-time migration rewrites about 1.4 GB of embedding blobs.** It needs about that much free disk and must run with the Engine stopped.\n- **R2: hard cutover.** On deploy the order is `migrate-whitelist.py`, then `build-ann-index.py`, then start the Engine, which refuses a `rowid` sidecar. The similarity cache needs no rebuild.\n- **R3: a crawl DB whose embeddings lack `ann_id`, read by `sync-whitelist.py`.** P1 covers this by computing the id instead of skipping the copy. The source-column check at `sync-whitelist.py:492-498` must not route this case into skipping embeddings.\n- **R4: fixture churn across 11 test files** for NOT NULL. A shared fixture helper that computes `ann_id` keeps each file's change to its insert.\n- **R5: a collision stops a dataset build or merge loudly, and recovery is manual.** The odds are about 4e-8 at the current 890k keys, and 0 collisions were measured.\n- **R6: `fetch_metadata` and the precompute target lookup switch to `WHERE e.ann_id IN (...)`.** The UNIQUE index keeps these lookups indexed. A missing index would turn each into a full scan.\n- **R7: `whitelist_migrations.migrate_videos_schema` drops `video_embeddings` when it rebuilds `videos`.** The recreated table must come back in the new shape.\n\n### Limitations\n\n- Purged or deleted videos stay in the index until the next rebuild. They are misses (no metadata row), not wrong videos.\n- A re-embedded video keeps its old vector in the index until the next rebuild, but it still resolves to the right video.\n- New videos are absent from the index until a rebuild. Incremental add and remove is F3/F4-M2.\n\n### Tradeoffs accepted\n\n- No backward compatibility with rowid indexes: the Engine refuses them.\n- A one-time table rewrite of existing databases.\n- Fixture changes across the test suite for the NOT NULL column.",
  "request_source": "read from docs/project/plans/17-stable-ann-ids.md",
  "slug": "17-stable-ann-ids",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done"
  },
  "phases": [],
  "digests": {},
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/08",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261002T150606-d231-dev-flow"
  ],
  "snapshot": {
    "tree": "06726eb0377e283d8e7f5156de70bc5d7dfa5941",
    "at": "2026-10-02T15:06:17-04:00"
  },
  "plan": "docs/project/plans/19-17-stable-ann-ids.md",
  "record": "docs/project/plans/19-17-stable-ann-ids.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Asked for\n\nIssue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2, plan `docs/project/plans/17-stable-ann-ids.md`). Today the FAISS index, and every reader that turns an id back into an embedded video, use `video_embeddings.rowid`. They switch to a deterministic `ann_id` derived from `(video_id, instance_domain)`. ADR-0006 (`docs/project/adr/0006-derived-ann-ids.md`) records the decision, and `CONTEXT.md` defines **ANN id**.\n\n### Purpose\n\nCorrectness. `video_embeddings` can change while no index rebuild follows, or while the rebuild fails: a merge, a host purge, a whole-table reload, a `--force` re-embed, a migration. In every such case the index must never return the wrong video. At most it misses videos it has not indexed yet. The build must not block later incremental index add or remove (F3/F4-M2), and it does not build them.\n\n### Current state (checked against the tree and the live DB, read-only)\n\n- `engine/server/db/jobs/build-ann-index.py:250-256` calls `add_with_ids` with `video_embeddings.rowid` and writes `id_source: \"video_embeddings.rowid\"` (line 284). The live sidecar `engine/server/db/whitelist-video-embeddings.faiss.json` says the same.\n- The live `engine/server/db/whitelist.db`:\n  - 890,052 `video_embeddings` rows, rowids exactly 1..890,052.\n  - Primary key `(video_id, instance_domain)`.\n  - 1,548 hosts, all already lowercase and trimmed.\n  - Every `video_id` is text.\n- Hash check: a 63-bit blake2b of `video_id::instance_domain` over all 890,052 keys gave 0 collisions, and no key hashed to 0.\n- Rowid-keyed readers:\n  - `engine/server/data/ann.py`:\n    - `compute_similar_items`, and its `ids > 0` filter.\n    - `search_index` (`exclude_rowid`).\n    - `search_similar_above`, the up-next fallback search. It keeps rowid hits through the same `ids > 0` filter, excludes `seed[\"rowid\"]` and calls `fetch_metadata` by rowid.\n    - The nprobe helpers `_extract_ivf`, `get_nprobe`, `apply_nprobe` and `set_nprobe` also live in this file, and `server.py` imports `set_nprobe` from it. `precompute-similar-ann.py` keeps its own copy of `set_nprobe`.\n  - `engine/server/data/embeddings.py`: the seed's `rowid`/`exclude_rowid` in `resolve_seed` and in the three seed queries.\n  - `engine/server/data/metadata.py`: `fetch_metadata`, which selects `WHERE e.rowid IN (...)`.\n  - `engine/server/data/search.py`: `vector_candidates`.\n  - `engine/server/api/handlers/similar.py`: `_handle_vector_search`.\n  - `engine/server/data/random_cache.py` and `engine/server/data/random_videos.py`: the `random_rowids` table.\n  - `engine/server/db/jobs/precompute-random-rowids.py`.\n  - `engine/server/db/jobs/precompute-similar-ann.py`: `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*` and the main loop.\n  - The rowid uses in `data/users.py` (likes) and `data/interaction_events.py` are about other tables, are not ANN ids, and do not change.\n- Writers that renumber rowids, or write `video_embeddings` at all:\n  - `build-video-embeddings.py`: `init_schema` uses `CREATE TABLE IF NOT EXISTS` (line 66). Under `--force` it runs DELETE (line 177), then `INSERT OR REPLACE` (line 272).\n  - `sync-whitelist.py`: `rebuild_content_tables` runs `DELETE FROM video_embeddings` (line 458), then `INSERT ... SELECT` from the attached crawl DB (lines 493-510). That copy runs only when the source's columns are a superset of `EMBEDDING_COLUMNS`. The same `EMBEDDING_COLUMNS` list also drives the exact check on the target schema in `ensure_schema_compatibility` (line 194), and the schema created at line 385 has no `ann_id`.\n  - `merge-staging-db.py`: `merge_rules.json` gives `video_embeddings` the `INSERT_OR_REPLACE` strategy, run as `INSERT OR REPLACE INTO main.t (common cols) SELECT ... FROM stage.t` over the columns prod and staging share (lines 152-171). The script also supports an `UPSERT` strategy.\n  - `updater-worker.inject_replace_embedding_for_test` (lines 1018-1064): a test-only `INSERT OR REPLACE` of one mutated embedding into staging, without `ann_id`.\n  - `whitelist_migrations.migrate_videos_schema` drops `video_embeddings` (line 268) and does not recreate it. The next schema creation does that.\n- Staging: the updater creates staging from `engine/crawler/schema.sql` (`init_staging_db`). That schema does not create `video_embeddings`, so `build-video-embeddings.init_schema` creates the staging table. `--resume-staging` reuses an existing staging DB, whose table may be in the old shape.\n- The updater (`updater-worker.py:1040-1150`) stops the service, merges, rebuilds the ANN, precomputes, and restarts in a `finally`. So a failed ANN build restarts the Engine on the old index against renumbered rows.\n- Random cache:\n  - The Engine never writes the random cache before listening. At start it opens `random-cache.db` read-only through `open_random_cache_if_usable` (`random_cache.py:283-302`). That accepts any non-empty `random_rowids` table without checking its shape.\n  - `server.py:345` sets `random_cache_startup_build = random_cache_refresh or random_cache_db is None`, so a cache judged unusable always gets a background build.\n  - Every build runs through `build_random_cache` (`random_cache.py:208-245`) into a per-pid temp file, which is swapped in through `swap_readonly_connection(..., RANDOM_CACHE_CHECK_SQL)`.\n  - With refresh off (`--dev`, `server.py:317-320`), a stored non-empty cache is served as it is.\n  - `precompute-random-rowids.py` keeps an `--out` that already holds `--size` rows, counted through `random_rowids_count` without checking their shape.\n  - `engine/server/api/recommendations/docs/LAYER_PARAMS.md` and `OVERVIEW.md` describe the cache as `random_rowids`.\n- Already on logical keys:\n  - The similarity cache (`similarity_items`) is keyed by `(video_id, instance_domain)` text and holds no rowids.\n  - `videos_fts` joins `videos.rowid` as FTS5 external content. That link is not an ANN id.\n- The Engine checks the index sidecar at start in `data/embedding_space.assert_index_matches_embeddings`, which today checks the model and the dimension.\n- Not checked: whether any deployed crawl DB that `sync-whitelist.py` reads already holds `video_embeddings` rows, with or without `ann_id`. The requirements cover all three cases.\n\n### Acceptance criteria\n\n- **AC1, the id:** one helper (for example `engine/server/data/ann_ids.py`) computes `ann_id` as blake2b with an 8-byte digest of `video_id + \"::\" + normalize_host(instance_domain)`, masked to 63 bits. `normalize_host` is the existing `data/moderation.normalize_host`. The result is positive, non-zero and safe as a signed int64. The same key gives the same id in any process and any DB. Every writer and reader uses this one helper. Jobs import it the way they already import `data.*`.\n- **AC2, the schema:** `video_embeddings` carries `ann_id INTEGER NOT NULL` with a UNIQUE index.\n  - A new `whitelist_migrations.migrate_video_embeddings_schema` rebuilds an existing table into that shape and fills the column from the helper through `sqlite3` `create_function`. It follows the existing `migrate_*_schema` table-rebuild pattern, and it is idempotent: it does nothing once the column exists. `migrate_whitelist_schema` calls it, so `migrate-whitelist.py` runs it.\n  - Every job that creates the table creates the same shape: `build-video-embeddings.init_schema` and the `sync-whitelist.py` schema. So does any table recreated after `migrate_videos_schema` drops it.\n  - **Collision guard:** a collision fails the write loudly on every write path, including `INSERT OR REPLACE` paths. A collision means a different `(video_id, instance_domain)` producing an `ann_id` already in use, or an id of 0. SQLite's `OR REPLACE` resolves conflicts on every UNIQUE index, so a plain UNIQUE index under `INSERT OR REPLACE` would silently delete the other video. That must not happen. The mechanism is a design choice: for example, writers use UPSERT on `(video_id, instance_domain)` and the `merge_rules.json` strategy for `video_embeddings` becomes `UPSERT`, or a BEFORE INSERT trigger raises. A write never probes for another id.\n  - **Old-shape tables:** writing into a `video_embeddings` table that lacks `ann_id` fails loudly with a message naming `engine/server/db/jobs/migrate-whitelist.py`, or, for a resumed staging DB, saying to recreate staging. Examples are an unmigrated prod DB, or a staging DB reused by `--resume-staging`. No writer ever produces rows without `ann_id`.\n- **AC3, the writers:** every writer stores the helper's `ann_id`.\n  - `build-video-embeddings.py` computes it per row.\n  - `merge-staging-db.py` preserves it from staging. The only change allowed there is the rule or strategy change the collision guard needs.\n  - `sync-whitelist.py` copies `ann_id` when the source has the column, and computes it through the registered function when the source has embeddings without it, so an older crawl DB does not force a re-embed. The target-schema check requires `ann_id`. The source-column check must not require it, or embeddings would be silently skipped.\n  - `updater-worker.inject_replace_embedding_for_test` writes `ann_id`.\n  - Re-running a writer, or replacing a row, leaves the video's `ann_id` unchanged.\n- **AC4, the index build:** `build-ann-index.py` adds vectors with `ann_id` as their ids and writes `id_source: \"video_embeddings.ann_id\"` to the sidecar. When the column is missing, it fails with a message naming `migrate-whitelist.py`.\n- **AC5, the Engine gate:** the Engine refuses to start when the index sidecar's `id_source` is not `video_embeddings.ann_id`. It refuses the same way it refuses a model mismatch today, in `assert_index_matches_embeddings`, with a message naming `build-ann-index.py`.\n- **AC6, the readers:** these resolve embedded videos by `ann_id`:\n  - similar: the seed and its exclusion (`ann_id`/`exclude_ann_id` in `embeddings.py`), the ANN results (`ann.py`, including `search_similar_above` and the `ids > 0` filter), and raw vector search (`similar._handle_vector_search`);\n  - search's vector half (`search.vector_candidates`);\n  - `fetch_metadata`, as `WHERE e.ann_id IN (...)`, served by the UNIQUE index;\n  - the random cache (`random_cache.py`, `random_videos.py`, `precompute-random-rowids.py`).\n\n  A stored random cache in the old `random_rowids` shape is detected and repopulated, never read. `open_random_cache_if_usable` treats it as unusable, so the Engine serves from the DB and runs a background build. The keep check in `precompute-random-rowids.py` treats an old-shape `--out` as not kept. Afterwards, no reader resolves an embedded video by rowid.\n- **AC7, the similarity precompute:** `precompute-similar-ann.py` uses `ann_id` for its FAISS ids and its target lookup. Its output keys (`similarity_items`, `(video_id, instance_domain)`) are unchanged, and its incremental selection stays keyed on `(video_id, instance_domain)`.\n- **AC8, the purpose observed in a test:** build an index, then, with no index rebuild, either renumber the DB's rows (delete and reinsert every row, as `sync-whitelist.py` does) or purge a host. Similar and search then return only videos whose identity matches the vector indexed for them. Unindexed or purged videos may be missing, but no result is a different video.\n- **AC9, the cycle and docs:** the updater's full cycle (merge \u2192 ANN build \u2192 precompute) runs on the new id source, observed through the orchestrator smoke test (`engine/server/db/jobs/tests/test-orchestrator-smoke.py`). These docs carry the one-time migrate-then-rebuild step for existing DBs: `DATA_BUILD.md`, `DEPLOYMENT.md` and the updater docs (`engine/server/db/jobs/docs/UPDATER_WORKER.md`). The step is `migrate-whitelist.py`, then `build-ann-index.py`, then start the Engine. `LAYER_PARAMS.md` and `OVERVIEW.md` (under `engine/server/api/recommendations/docs/`) describe the random cache's new `ann_id` shape.\n\n### Scope\n\nIn scope: AC1-AC9, including the random cache, as the operator decided. One build, correctness only.\n\nOut of scope:\n- incremental FAISS add or remove (F3/F4-M2);\n- rebuilding or re-keying the similarity cache;\n- `videos_fts`;\n- backward compatibility with rowid indexes (a `rowid` sidecar is refused, not read);\n- the crawler (`engine/crawler`, including `schema.sql`).\n\n### Consistency constraints\n\n- Job CLIs keep their current arguments.\n- Refusal messages follow `data/embedding_space.py`: say what is wrong, and name the command that fixes it.\n- The migration follows the existing `migrate_*_schema` table-rebuild pattern in `whitelist_migrations.py`.\n- Hosts go through the existing `data/moderation.normalize_host`.\n- New code matches the style of the file it lands in.\n- Design to the smallest thing that works: stdlib `hashlib.blake2b`, no new dependency, one helper module.\n\n### Tests\n\n- Active tests live in `tests/active`, scratch work goes in `tests/tmp`, and job tests live in `engine/server/db/jobs/tests/`.\n- Pre-build baseline: the suite exits with code 0 (`variant: false`).\n- Fixture churn: these tests insert into `video_embeddings` without `ann_id`, and NOT NULL breaks them, so they change with the build.\n  - 9 files in `tests/active`: `conftest.py`, `test_blocks.py`, `test_dislike_profile.py`, `test_dislikes.py`, `test_frontend_reactions.py`, `test_internal_client_reads.py`, `test_metadata.py`, `test_profiles.py`, `test_random_videos.py`.\n  - 2 job tests: `test-moderation-integration.py`, `test-orchestrator-smoke.py`.\n  - A shared fixture helper that computes `ann_id` keeps each file's change to its insert.\n- New tests cover:\n  - AC1: determinism, range, and a fixed known value;\n  - AC2: migration backfill, idempotence, the UNIQUE index, and the collision guard, including under `INSERT OR REPLACE` and on the merge path;\n  - AC3: each writer, including `sync-whitelist` from a source with `ann_id` and from one without;\n  - AC4/AC5: the sidecar's `id_source` and the Engine's refusal;\n  - AC6: the old-shape random cache rejected and rebuilt;\n  - AC8: the stale index after a renumber and after a host purge.\n\n### Risks and limitations accepted\n\n- The one-time migration rewrites about 1.4 GB of embedding blobs. It needs about that much free disk, and the Engine must be stopped while it runs.\n- Hard cutover: the Engine refuses a `rowid` sidecar, so the deploy order is migrate, then index build, then start. The similarity cache needs no rebuild.\n- A collision stops a dataset build or a merge loudly, and recovery is manual. The odds are about 4e-8 at 890k keys, and 0 collisions were measured.\n- Purged or deleted videos stay in the index until the next rebuild. They show up as misses (no metadata row), never as wrong videos.\n- A re-embedded video keeps its old vector in the index until the next rebuild, but it still resolves to the right video.\n- New videos stay out of the index until a rebuild.\n- A staging DB resumed from before the cutover fails loudly. It is not migrated.\n</requirements>\n\n<conflicts>\nAC2 \"a collision fails the write loudly\" vs the tree's INSERT OR REPLACE writers (`build-video-embeddings.py:272`, `merge_rules.json` INSERT_OR_REPLACE run by `merge-staging-db.py:167-171`, `updater-worker.py:1046`): SQLite OR REPLACE clears UNIQUE(ann_id) conflicts by deleting the other row, so a collision would silently drop a video. Resolved by the operator: the collision guard must hold on those paths too, so the plan's \"merge-staging-db needs no code change\" may become a `merge_rules.json` strategy change.\nThe plan's \"merge-staging-db needs no code change, because staging now carries ann_id\" vs `updater-worker --resume-staging`, which reuses a staging DB that `build-video-embeddings` (CREATE TABLE IF NOT EXISTS) leaves in the old shape. Resolved: writing to an old-shape table fails loudly and names the fix.\nThe plan's single source-column check at `sync-whitelist.py:492-499` vs `EMBEDDING_COLUMNS`, which drives both the exact target check (line 194) and the source-superset check (line 499). Adding ann_id to that list would make older crawl DBs skip all embeddings. Resolved: the target check requires ann_id and the source check does not.\nThe issue says the updater must \"keep ANN id consistency before rebuild/precompute\" vs AC2/AC3, under which the schema guarantees the column, so the updater needs no step of its own beyond the migration having run once. The operator accepted this reading. The one updater code change is `inject_replace_embedding_for_test` writing ann_id.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nOne new module, `engine/server/data/ann_ids.py`, holds everything the id needs, the same way `data/moderation.py` holds `normalize_host` and `ensure_moderation_schema`. It has four parts:\n- the pure function that computes the id from `(video_id, instance_domain)`;\n- a registration that exposes that function to SQLite under one SQL name, through `create_function`;\n- the one definition of the `video_embeddings` table: its columns, `CHECK (ann_id > 0)`, the UNIQUE index on `ann_id`, and the collision trigger;\n- an old-shape check that raises the AC2 message.\n\nEvery writer, reader, migration and test fixture imports from this module. Jobs reach it through the `data.*` import path they already use. `whitelist_migrations.py` reaches it through the server dir that `migrate-whitelist.py` already puts on `sys.path`.\n\n**AC1, the id.** blake2b with an 8-byte digest of `video_id + \"::\" + normalize_host(instance_domain)`, read big-endian and masked to 63 bits, using stdlib `hashlib`. The result is between 0 and 2^63-1 and fits a SQLite INTEGER, a numpy int64 and a FAISS id. The function only computes; it never probes. An id of 0 is stopped by the schema, not by the function.\n\n**AC2, the schema and the collision guard.** `video_embeddings` gains `ann_id INTEGER NOT NULL CHECK (ann_id > 0)` and a UNIQUE index. The guard is a BEFORE INSERT trigger. It raises ABORT when another row with a different `(video_id, instance_domain)` already holds `NEW.ann_id`.\n\nThe trigger works on every path because SQLite fires BEFORE triggers ahead of constraint resolution. The new row is checked before `OR REPLACE` can delete the other video's row. That covers `build-video-embeddings`, the merge's `INSERT OR REPLACE`, the bulk `INSERT ... SELECT` in sync, the updater's test inject and any hand-run SQL. The trigger uses plain SQL, so it works on any connection, including the sqlite3 CLI.\n\nA same-key replace (a re-embed, or a merge of an updated row) does not match the trigger: same key and same id, so the row is replaced and its `ann_id` is unchanged. An id of 0 fails the CHECK, which `OR REPLACE` does not override. A plain UPDATE that collides fails on the UNIQUE index, and no code path uses UPDATE OR REPLACE. `merge_rules.json` keeps `INSERT_OR_REPLACE`, because the guard needs no strategy change.\n\n**AC2, the migration.** `migrate_video_embeddings_schema` returns at once when the table is missing or already has `ann_id`. Otherwise it follows the `migrate_*_schema` rebuild pattern:\n1. Register the SQL function on the connection.\n2. Create `video_embeddings_new` from the shared definition, with the CHECK.\n3. Copy every row, filling `ann_id` from the function.\n4. Drop the old table and rename the new one.\n5. Create the UNIQUE index and the trigger, both IF NOT EXISTS.\n\nThe index and trigger come after the rename, so their names refer to the final table. A collision during the backfill then surfaces loudly when the UNIQUE index is built.\n\n`migrate_whitelist_schema` calls it last. If `migrate_videos_schema` has just dropped the table, it does nothing, and the next schema creation builds the new shape. `build-video-embeddings.init_schema` and `sync-whitelist.ensure_content_schema` both create the table from the shared definition, so every recreation, including the one after `migrate_videos_schema`, has the same shape.\n\n**AC2, old-shape tables.** The helper's check reads `PRAGMA table_info` and raises RuntimeError in the `embedding_space.py` style. It says the table has no `ann_id` column, and that prod needs `engine/server/db/jobs/migrate-whitelist.py` while a staging DB reused through `--resume-staging` must be recreated by running the updater without it. These callers use it:\n- `build-video-embeddings.py`, right after creating the schema;\n- `build-ann-index.py`, before sampling;\n- `merge-staging-db.py`, on both `main` and `stage` before the merge transaction. This is the one change the operator approved there.\n- `sync-whitelist.py`, through its existing exact target check, whose error already names `migrate-whitelist.py`.\n\n**AC3, the writers.**\n- `build-video-embeddings.py` computes the id per row in Python and adds it to the existing `INSERT OR REPLACE` tuple. Under `--force` the DELETE-then-insert gives every video back the same id.\n- `merge-staging-db.py` already copies the columns prod and staging share, so `ann_id` comes across from staging unchanged. Its only edit is the guard call above.\n- In `sync-whitelist.py`, `EMBEDDING_COLUMNS` splits in two. The target list includes `ann_id` and feeds the exact check. The source superset check keeps today's six columns, so an older crawl DB still qualifies. In `rebuild_content_tables`, when the source has `ann_id` it is copied; otherwise the select computes it through the registered function. Either way the trigger guards every row.\n- `updater-worker.inject_replace_embedding_for_test` computes the id through the helper and writes it, so the replacement keeps the prod row's id.\n\n**AC4, the index build.** `build-ann-index.py` selects `ann_id` in place of `rowid` for `add_with_ids` and writes `id_source: \"video_embeddings.ann_id\"`. The training sample still uses `rowid % step` to spread its rows across the table. That is a sampling cursor, not an identity, and no vector is ever looked up by it.\n\n**AC5, the Engine gate.** `assert_index_matches_embeddings` gains an `id_source` check next to the model check, with a message naming `build-ann-index.py`. The function also guards `precompute-similar-ann.py`, which is correct: a precompute against a rowid index would map hits to the wrong videos.\n\n**AC6, the readers.** The rowid names become `ann_id` throughout:\n- the seed's `rowid`/`exclude_rowid` and its three queries in `embeddings.py`;\n- the filters and exclusions in `ann.py`, including `search_similar_above`. The `> 0` filter stays valid: real ids are \u2265 1 and FAISS fills empty slots with -1.\n- `similar._handle_vector_search`;\n- `search.vector_candidates`;\n- `fetch_metadata`, which selects and filters on `e.ann_id` through the UNIQUE index.\n\n`search.py`'s own `v.rowid` is the `videos_fts` link and does not change. The nprobe helpers do not change.\n\n**AC6, the random cache.** The cache table becomes `random_ann_ids (position, ann_id)`. Because the new shape has a new table name, old-shape detection needs no new code. Against an old file, the existing count helper (renamed to match) returns None, so:\n- `open_random_cache_if_usable` logs `no_table` and returns None, the Engine serves from the DB, and `server.py:345` starts a background build;\n- the precompute job's keep check counts 0 and rebuilds;\n- `RANDOM_CACHE_CHECK_SQL` names the new table, so a swap can only install a new-shape file.\n\nThe build samples by `ann_id` instead of by rowid: a random start between min and max `ann_id`, then the next rows in `ann_id` order, wrapping around. Both the unfiltered and the filtered scans use this. Hashed ids are spread evenly, so this window is a uniform sample, not a block of rows in insertion order.\n\n`precompute-random-rowids.py` keeps its file name and arguments; only its help text changes.\n\n**AC7, the similarity precompute.** In `precompute-similar-ann.py`, `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*`, the pending-selection query and the main loop move to `ann_id`. The self-exclusion becomes `ann_id == row[\"ann_id\"]`. Output keys and incremental selection stay on `(video_id, instance_domain)`.\n\n**AC8, the purpose in a test.** A job test builds a small FAISS index on the new ids. With no index rebuild, it then either deletes and reinserts every row in a different order, or deletes one host's rows. It asserts that every similar and search hit resolves, through `fetch_metadata`, to the video whose vector carries that id, and that the purged host's videos are missing rather than replaced.\n\nThis holds by construction. The id is a function of identity, so after any rewrite of the table a stale id finds either the same video or nothing.\n\n**AC9, the cycle and docs.**\n- The orchestrator smoke test runs merge, ANN build and precompute on fixtures that carry `ann_id`, and asserts the sidecar's `id_source`.\n- `DATA_BUILD.md`, `DEPLOYMENT.md` and `UPDATER_WORKER.md` get the one-time step: stop the Engine, run `migrate-whitelist.py`, run `build-ann-index.py`, start the Engine.\n- `LAYER_PARAMS.md` and `OVERVIEW.md` describe `random_ann_ids`.\n\n**Tests.** A shared fixture helper in `tests/active` computes `ann_id`, so each of the 9 churned files changes only its insert. The 2 job tests import the helper directly.\n\nNo real collision can be produced, so the collision tests insert an explicit doctored `ann_id` that matches another key's id:\n- directly;\n- under `INSERT OR REPLACE`, asserting that the other video still exists;\n- through merge, from a doctored staging row.\n\nAC1 pins one fixed known value.\n\n### Alternatives considered\n\n- **UPSERT on `(video_id, instance_domain)` in every writer, with the merge rule switched to `UPSERT`, instead of a trigger.** Rejected: the guarantee would depend on every writer, present and future, getting its SQL right. The test inject, any hand-run `INSERT OR REPLACE` and the bulk sync would each be a hole. The trigger lives in the schema and holds for all of them. It also leaves merge's strategy alone.\n- **A CHECK that `ann_id` equals the registered function of the key.** It would also catch a wrong id, not just a duplicate. Rejected: every connection that writes, including the sqlite3 CLI and the Engine's test fixtures, would fail with \"no such function\".\n- **Keeping the `random_rowids` table name and checking its column shape.** Rejected for the new table name, which makes the existing \"no table\" path do the detection with no new code in `open_random_cache_if_usable` or in the keep check.\n- **Random-cache sampling by a rowid window while storing `ann_id`.** It would work, but it keeps a rowid read in the reader. The `ann_id` range is already indexed and gives a better spread.\n- **Always recomputing `ann_id` in sync instead of copying it from the source.** It would be safer against a foreign id, but AC3 settles on copying.\n- **For the old-shape merge failure:** extending the rule's `keys` (a generic message that doesn't name `migrate-whitelist.py`) or guarding only in the updater (a standalone merge into an unmigrated prod would still write rows without `ann_id`). The operator chose the direct guard call in `merge-staging-db.py`.\n- **Already rejected in ADR-0006 and not revisited:** a mapping table, a pinned rowid, an assigned counter, and probing for a free id.\n\n### Risks and gotchas\n\n- **Trigger order.** The guard relies on SQLite firing BEFORE INSERT triggers ahead of `OR REPLACE` conflict resolution. The `INSERT OR REPLACE` collision test pins this, so a SQLite behaviour change would show up as a red test.\n- **Per-row trigger cost.** Each insert does one lookup on the UNIQUE index. That is negligible for batched embedding writes and adds one indexed probe per row to the 890k-row sync reload.\n- **Migration rename.** The UNIQUE index and the trigger are created after the rename, so nothing depends on how ALTER TABLE RENAME rewrites trigger bodies. Backfill collisions surface when the UNIQUE index is built, and id 0 fails the CHECK.\n- **JSON precision.** Ids up to 2^63 exceed JavaScript's 2^53 safe range. I checked that `fetch_metadata`'s output dicts, the similar and search handlers and the random feed never put the id into a response. If one is ever exposed, it must be a string.\n- **Copied source ids.** `sync-whitelist` trusts a source `ann_id` it copies. The trigger catches duplicates, not a wrong id. In practice only the helper ever writes the column.\n- **Random feed change.** The unfiltered draw becomes a hash-uniform sample, not a block of rows in insertion order. Random-cache tests that assert row order or rowid windows will need new expectations.\n- **The test inject** needs `updater-worker.py` to reach `data.ann_ids`. If it does not already have the server dir on `sys.path`, it gets the same two-line insert the other jobs use.\n\n### Tradeoffs the operator accepts\n\n- **`merge-staging-db.py` changes by one guard call,** a few lines beyond AC3's limit. The operator approved this so that an unmigrated prod fails with AC2's message.\n- **Accepted in the requirements:**\n  - the one-time migration needs about 1.4 GB free and a stopped Engine;\n  - hard cutover: migrate, build the index, then start;\n  - a collision stops the run loudly and recovery is manual;\n  - stale indexes miss new videos and keep purged ones, as misses only;\n  - a resumed pre-cutover staging DB fails loudly instead of being migrated.\n- **The deliberate simplifications:**\n  - **The random cache is detected by its table name, not its shape.** The ceiling is that a future change to the shape under the same name would need a real column check. The upgrade path is to compare `PRAGMA table_info` in the count helper.\n  - **ANN training samples by `rowid % step`.** This only affects which vectors train the quantizer, never identity.\n</initial_solution>\n\n<conflicts>\nAC3 (`merge-staging-db.py`: \"the only change allowed there is the rule or strategy change the collision guard needs\") collides with AC2 (writing into a `video_embeddings` table without `ann_id` fails loudly with a message naming `migrate-whitelist.py`). The merge copies only the columns prod and staging share, so an unmigrated prod would quietly receive rows without `ann_id`, and the chosen trigger guard needs no merge change. Asked through AskUser, the operator chose to allow a small guard call in `merge-staging-db.py`: the shared helper's column check on prod and staging before merging.\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n<impacts>\n<impact path=\"engine/server/data/ann_ids.py\" element=\"new module: id function, SQL registration, shared video_embeddings definition (CHECK, UNIQUE index, BEFORE INSERT collision trigger), old-shape check\">\nNew file, modelled on `data/moderation.py` (stdlib only, `from __future__ import annotations`, one-line docstrings).\n\nContents:\n- The pure id function.\n- A `register_*(conn)` wrapper over `conn.create_function(name, 2, fn, deterministic=True)`.\n- DDL constants or helpers for the table, the UNIQUE index and the trigger.\n- The old-shape check, which raises RuntimeError.\n\nDependencies:\n- It imports `normalize_host` from `data.moderation`. That module imports `data.similarity_cache`, which is also stdlib only (os, sqlite3, struct, pathlib), so importing `data.ann_ids` stays safe under the system interpreter that several tests and jobs use (`sys.executable` in `test_precompute_random_rowids.py`). If you add numpy or faiss here, those runs break.\n- Every writer, reader-side fixture, migration and job imports it.\n\nPoints the implementer must settle:\n1. **`normalize_host` can return None** (empty, whitespace or unparsable input). It also **strips ports**. The crawler's `normalize_host_token` keeps `host:port` for bare entries, so `instance_domain` can legitimately hold a port. Two videos with the same `video_id` on `h:8080` and `h:9090` would then hash the same key and collide loudly. The function must define what it hashes when the result is None: raise, or fall back to the raw lowercased domain.\n2. **The old-shape check needs a `schema` argument** (`PRAGMA {schema}.table_info(video_embeddings)`). `merge-staging-db.py` must check `main` and `stage` on one connection.\n3. **The DDL must be split.** `CREATE TABLE IF NOT EXISTS` is a no-op on an old table, but `CREATE UNIQUE INDEX ... ON video_embeddings(ann_id)` and `CREATE TRIGGER ... NEW.ann_id` fail with `no such column: ann_id`. Index and trigger creation must come after, or be guarded by, the old-shape check, or every caller gets a raw sqlite error instead of AC2's message.\n4. **Index and trigger names must not collide** with `idx_video_embeddings_id_instance`, which `data/videos.ensure_video_indexes` drops at every Engine start.\n5. **The trigger must use plain SQL** (no registered function) so that the sqlite3 CLI and the Engine's connections can still insert. Inside a trigger on `main`, unqualified table names resolve to `main`, which is correct for merge's attached `stage`.\n\nRegression risk: medium. A change to `normalize_host` silently changes every id, so the AC1 fixed-value test is the only thing that catches it.\n</impact>\n<impact path=\"engine/server/data/moderation.py\" element=\"normalize_host (dependency, no edit expected); purge_host_data / _host_table_column_pairs\">\n**`normalize_host`** becomes part of the id contract. Any future edit to it (port handling, IDNA, trimming) re-keys every `ann_id` and silently desynchronises the DB from the stored index and random cache. No code change is planned. Consider a comment at `normalize_host` pointing at `data/ann_ids.py`, or rely on the AC1 pinned-value test.\n\n**`purge_host_data`** deletes `video_embeddings` rows by host. The new BEFORE INSERT trigger does not fire on DELETE, so purges are unaffected. This is the AC8 \"purge one host\" path. Afterwards a stale index returns misses, not wrong videos, through `fetch_metadata`'s `ann_id` lookup.\n\nCallers:\n- `updater-worker.purge_hosts` and `purge_hosts_from_staging`\n- `instance-denylist-cli.py --purge-now`\n- the moderation integration test\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/db/jobs/whitelist_migrations.py\" element=\"new migrate_video_embeddings_schema(conn); migrate_whitelist_schema calls it last\">\nNew function, following the `migrate_*_schema` rebuild pattern:\n1. Return at once if the table is missing or already has `ann_id`.\n2. Register the SQL function.\n3. Create `video_embeddings_new` from the shared DDL.\n4. `INSERT ... SELECT` with `ann_id` filled by the function.\n5. DROP the old table and RENAME the new one.\n6. Create the UNIQUE index and the trigger, IF NOT EXISTS.\n\n`migrate_whitelist_schema` appends the call after `migrate_videos_language`. When `migrate_videos_schema` has just dropped `video_embeddings`, the new step does nothing.\n\nImport: module-level `from data.ann_ids import ...` requires `engine/server` on `sys.path`.\n- `migrate-whitelist.py` inserts `server_dir`.\n- `tests/active/test_whitelist_migrations.py` loads this file with `importlib` after loading `sync-whitelist.py`, which inserts `server_dir`. It works only by that side effect, so make the test, or the module, insert the path explicitly.\n\nRisks:\n- **Atomicity.** The existing pattern uses `executescript`, which COMMITs first and runs each statement in autocommit, so `with conn:` in `migrate-whitelist.py` gives no atomicity. If the UNIQUE index build fails on a backfill collision after the DROP and RENAME, the DB is left with `ann_id` but **no UNIQUE index and no trigger**. A re-run then takes the early return because `ann_id` exists, and the guard is never installed. Either run the whole rebuild in one explicit `BEGIN ... COMMIT`, or make the early-return path still `CREATE ... IF NOT EXISTS` the index and trigger.\n- **Size.** About 890k rows rewritten (around 1.4 GB). The Engine must be stopped.\n- **FK.** The table declares an FK to `videos`, but `migrate-whitelist`'s connection does not enable `foreign_keys`, so DROP and RENAME are unaffected.\n\nRegression risk: high.\n</impact>\n<impact path=\"engine/server/db/jobs/migrate-whitelist.py\" element=\"main(); backup_db\">\nNo logic change is needed beyond the new step running through `migrate_whitelist_schema`. `server_dir` is already on `sys.path` for `data.ann_ids`.\n\nOperational impact:\n- **Free space.** `backup_db` (the default) copies the whole `whitelist.db`, about 3.5 GB according to DATA_BUILD's VACUUM note, before the 1.4 GB rebuild. The \"about 1.4 GB free\" in the accepted tradeoffs understates this unless `--no-backup` is used.\n- **No longer additive.** The migration now rewrites a large table, so it must run with the Engine stopped.\n- **Help text.** The description, \"Migrate whitelist.db schema in-place\", stays accurate.\n\nRisk: low in code, medium operationally.\n</impact>\n<impact path=\"engine/server/db/jobs/build-video-embeddings.py\" element=\"init_schema(); main() insert tuple and INSERT OR REPLACE; --force path\">\nChanges:\n- `init_schema` creates the table from the shared definition, then calls the old-shape check. The index and trigger must be created only after that check passes (see `ann_ids` point 3), because `CREATE TABLE IF NOT EXISTS` is a no-op on an old staging or whitelist table.\n- The per-row tuple gains the id, computed in Python, and the INSERT column list gains `ann_id`.\n- New import: `from data.ann_ids import ...`. `server_dir` is already on `sys.path`.\n\nCallers:\n- `updater-worker` on staging (fresh from `crawler/schema.sql`, which has no `video_embeddings`, so the table is created in the new shape; a `--resume-staging` old staging fails with the AC2 message)\n- `run-dataset-build.sh` (`--force` on `whitelist.db`)\n- operators on `whitelist.db`\n\n`--force` does DELETE then reinsert, so every key gets back the same id. The trigger raises on a doctored collision. The IntegrityError aborts that batch; earlier batches are already committed (per-batch commit), which is acceptable as a loud stop.\n\n`scripts/run-reembed.sh` parses the `--model-name` default through the AST; it must remain an `add_argument` with a Constant default.\n\nRisk: medium.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"EMBEDDING_COLUMNS split; ensure_content_schema video_embeddings DDL; ensure_schema_compatibility; rebuild_content_tables embeddings copy\">\nChanges:\n- `EMBEDDING_COLUMNS` becomes two lists:\n  - the target list, with `ann_id`, for `_assert_columns_exact(conn, \"video_embeddings\", ...)`;\n  - the source superset, today's six columns.\n- `ensure_content_schema` replaces its inline `video_embeddings` DDL with the shared definition.\n- `rebuild_content_tables` reads the source `table_info`. If the source has `ann_id`, it copies it; otherwise it selects `<fn>(video_id, instance_domain)`, which needs the function registered on this connection before the INSERT. The trigger fires per row (around 890k indexed probes) inside the single `with conn:` transaction, so a collision rolls back the whole sync.\n\n**Ordering hazard.** `main()` calls `ensure_content_schema(conn)` **before** `ensure_schema_compatibility(conn)`. If the shared DDL creates the UNIQUE index or trigger unconditionally, an unmigrated `whitelist.db` fails with `no such column: ann_id` from the index DDL instead of the exact check's \"missing columns: ann_id ... Run migrate-whitelist.py\". Keep index and trigger creation conditional, or move the check first.\n\nOther consumers of `ensure_content_schema` and of the module:\n- `tests/active/test_video.py`, `test_whitelist_migrations.py`, `test_repair_video_channel_names.py` and `test_host_normalisation.py` (module load)\n- `repair-video-channel-names.py`, which loads this module for its FTS helpers\n\n`_load_schema_columns` and `videos_fts` are unaffected.\n\nRisk: high.\n</impact>\n<impact path=\"engine/server/db/jobs/merge-staging-db.py\" element=\"main(): old-shape guard on main and stage before BEGIN IMMEDIATE\">\nChange: one guard call per schema (`main`, `stage`) after ATTACH and before the transaction (approved). Needs `from data.ann_ids import ...`; `server_dir` is already inserted.\n\nThe rule loop is unchanged:\n- `merge_columns` includes `ann_id` once both sides have it.\n- `INSERT OR REPLACE INTO main.video_embeddings (... ann_id ...) SELECT ... FROM stage` hits the trigger per row. A same-key replace keeps the id; a doctored foreign id ABORTs, and the existing `except` rolls back.\n- The connection needs no registered function.\n\nWithout the guard, an old-shape `stage` would drop `ann_id` from `merge_columns` and fail NOT NULL with a generic error. An old-shape `main` would let rows through with no `ann_id`.\n\nCaller: `updater-worker` step \"merge\"; the smoke test exercises it.\n\nRisk: low to medium.\n</impact>\n<impact path=\"engine/server/db/jobs/merge_rules.json\" element=\"video_embeddings rule\">\nNo change: `INSERT_OR_REPLACE` with keys `video_id`, `instance_domain` stays. Listed because the plan relies on it staying unchanged. `test-orchestrator-smoke.validate_outputs` reads the rules and checks replace and mismatch behaviour per strategy.\n\nRisk: none.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"inject_replace_embedding_for_test; (no-change) count_staging_deltas, seed_staging_from_prod, init_staging_db, --resume-staging flow\">\n**`inject_replace_embedding_for_test`** must:\n- select `ann_id` from `prod.video_embeddings`, or compute it through the helper;\n- add `ann_id` to the `INSERT OR REPLACE` into staging.\n\nWithout that, NOT NULL fails on a new-shape staging. `server_dir` is already on `sys.path` (lines 24-27), so the \"two-line insert\" contingency in the plan is not needed. Its docstring may need wording.\n\nNo change:\n- `init_staging_db` (crawler `schema.sql` has no `video_embeddings`)\n- `seed_staging_from_prod` (instances and channels only)\n- `count_staging_deltas` (key-based)\n- `purge_hosts*`\n\nWith `--resume-staging`, a pre-cutover staging now fails loudly in `build-video-embeddings` (accepted).\n\n`tests/active/test_updater_worker.py` AST-scans this file for `build-ann-index.py` and `run_with_cpu_fallback` inside the `try`. A new import does not affect that.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/db/jobs/build-ann-index.py\" element=\"EmbeddingRow, iter_embeddings, fetch_training_samples, add loop query, meta id_source, old-shape guard\">\nChanges:\n- Old-shape guard before sampling, naming `migrate-whitelist.py` (AC4). It needs `from data.ann_ids import ...`; `server_dir` is already inserted.\n- The add query becomes `SELECT ann_id, embedding, embedding_dim`, and `EmbeddingRow.rowid` becomes `ann_id`. The `np.int64` cast fits the 63-bit ids.\n- `meta[\"id_source\"] = \"video_embeddings.ann_id\"`.\n- `fetch_training_samples` keeps `rowid % step` (sampling only).\n\nConsumers of the sidecar:\n- `assert_index_matches_embeddings` (Engine and precompute)\n- `test-orchestrator-smoke.validate_outputs`\n- `scripts/run-reembed.sh`, which logs it\n\nRisk: medium. A missed `rowid` here produces an index the AC5 gate accepts (by sidecar) but with wrong ids.\n</impact>\n<impact path=\"engine/server/data/embedding_space.py\" element=\"assert_index_matches_embeddings; module docstring\">\nAdd a check: `meta.get(\"id_source\") != \"video_embeddings.ann_id\"` raises RuntimeError with a message naming `build-ann-index.py`, next to the model check.\n\nCallers:\n- `api/server.py:365` (Engine start)\n- `precompute-similar-ann.py:345`\n\nEvery existing sidecar (`id_source: \"video_embeddings.rowid\"`) and every test sidecar without `id_source` is now refused:\n- `tests/active/test_precompute_similar_ann.py` writes `{\"model_name\", \"embedding_dim\"}` only and will fail until it adds `id_source`.\n- `test_video.py` builds its index in-process and never calls the gate.\n\nUpdate the docstring to mention the id contract.\n\nRisk: medium. It hard-stops every Engine whose DB and index were not cut over, including the dev or test dataset.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"startup: open_random_cache_if_usable, resolve_embedding_space, assert_index_matches_embeddings\">\nNo edit is expected.\n\nBehaviour changes through the callees:\n- **Random cache.** Against an old `random-cache.db`, `open_random_cache_if_usable` returns None (`no_table`). `random_cache_startup_build` becomes true (line 345), so a background build runs and the feed is served from the DB until it swaps in.\n- **Index gate.** `assert_index_matches_embeddings` now refuses a rowid index, so the Engine exits at start until the index is rebuilt.\n\nThe Engine has no `video_embeddings` old-shape check of its own. An Engine on an unmigrated DB with a new index is impossible in practice, because the index build requires `ann_id`.\n\nRisk: low in code, high in cutover ordering.\n</impact>\n<impact path=\"engine/server/data/embeddings.py\" element=\"resolve_seed (exclude_rowid/rowid keys), _fetch_seed_by_uuid, _fetch_seed_by_id, fetch_seed_embeddings_for_likes (e.rowid AS rowid \u00d72), _seed_from_row\">\n**Change.** Four `e.rowid AS rowid` selects become `e.ann_id`, and the seed keys `rowid` and `exclude_rowid` become `ann_id` and `exclude_ann_id`. That covers `resolve_seed`'s three return shapes and `_seed_from_row`.\n\n**Consumers of the seed keys:**\n- `ann.compute_similar_items` (`seed[\"rowid\"]`, a hard KeyError if only one side is renamed)\n- `ann.search_similar_above` (`seed.get(\"rowid\")`, which would silently stop self-exclusion)\n- `similar._handle_vector_search` (`seed[\"exclude_rowid\"]`)\n- recommendations sources that pass `fetch_seed_embeddings_for_likes` seeds into `get_similar_candidates` \u2192 `compute_similar_items` (`api/recommendations/sources/ann_similar_from_likes.py` and `cached_similar_from_likes.py`)\n\n**Other dependents:**\n- `handlers/internal_client_reads.handle_internal_video_resolve` calls `fetch_seed_embedding`, so its SQL now needs `e.ann_id`. The response does not expose the id.\n- `fetch_embeddings_by_ids` is unchanged.\n\n**Risk: medium.** A partial rename silently breaks self-exclusion; there is no error.\n</impact>\n<impact path=\"engine/server/data/ann.py\" element=\"compute_similar_items, search_similar_above, search_index (exclude_rowid param)\">\nRename the variables and keys to `ann_id`:\n- `seed[\"rowid\"]` becomes `seed[\"ann_id\"]`.\n- `search_index`'s `exclude_rowid` parameter becomes `exclude_ann_id`.\n\nThe `> 0` filters stay valid. `search_index` drops only `< 0`, which also stays valid because the CHECK forbids 0.\n\nCallers:\n- `similar._handle_vector_search`\n- `search.vector_candidates`\n- `similarity_candidates.get_upnext_candidates` \u2192 `search_similar_above`\n- `_compute_candidates` \u2192 `compute_similar_items`\n- the archived `tests/archive/short_similarity_cache/test_similar.py` (not run)\n\n`tests/active/test_similarity_candidates.py` stubs `search_similar_above` with the same signature, so a keyword rename of its parameters would not break the stub, which is positional. The nprobe helpers do not change.\n\nRisk: low to medium.\n</impact>\n<impact path=\"engine/server/data/metadata.py\" element=\"fetch_metadata\">\n`SELECT e.ann_id AS ann_id ... WHERE e.ann_id IN (...)`, keyed by `int(row[\"ann_id\"])`. This uses the UNIQUE index; today the lookup goes by the rowid primary key, so performance is comparable. The parameter name and docstring move from `rowids` to `ann_ids`. Output dicts do not include the id, which keeps it out of JSON (the 2^53 precision issue).\n\nCallers:\n- `ann.compute_similar_items` and `ann.search_similar_above`\n- `search.vector_candidates`\n- `similar._handle_vector_search`\n- `random_videos.fetch_random_rows_from_cache`\n- `tests/active/test_metadata.py` (`_nsfw_metadata` passes `SELECT rowid` ids against a fixture table without `ann_id`, so it must change)\n\n`fetch_metadata_by_ids`, `fetch_metadata_by_uuids` and `_select_metadata` are unchanged.\n\nRisk: medium. Every fixture DB lacking `ann_id` now raises `no such column: e.ann_id` on these paths.\n</impact>\n<impact path=\"engine/server/data/search.py\" element=\"vector_candidates\">\n`rowids` from `search_index` become `ann_ids`, passed to `fetch_metadata`. `VIDEO_ROW_SQL`'s `v.rowid AS rowid` (the `videos_fts` link) and `lexical_candidates` are unchanged.\n\n`tests/active/test_search.py` runs with `query_encoder=None`, so the vector half returns before `fetch_metadata`. Its fixture table (no `ann_id`) should need no change. This is unverified beyond reading the test's server stub.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._handle_vector_search\">\n`seed[\"exclude_rowid\"]` becomes `seed[\"exclude_ann_id\"]`, and local variables are renamed. Rows are `{**meta, \"score\"}`, and `meta` from `fetch_metadata` carries no id, so nothing reaches the JSON response. `_handle_seed_with_embedding` and `_fetch_random_rows` need no edit; they flow through `get_upnext_candidates` and `random_videos`.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/data/random_cache.py\" element=\"RANDOM_CACHE_CHECK_SQL, ensure_random_cache_schema, random_rowids_count (rename), populate_random_cache (both scans), fetch_random_rowids (rename), docstrings\">\n**Rename and reshape:**\n- The table `random_rowids(position, video_rowid)` becomes `random_ann_ids(position, ann_id)`.\n- `RANDOM_CACHE_CHECK_SQL` names the new table, and the count helper is renamed.\n\n**Build:**\n- The unfiltered build reads `MIN(ann_id)`/`MAX(ann_id)`. It runs `random.randint` over a 63-bit range (Python ints are fine), then `WHERE ann_id >= ? ORDER BY ann_id LIMIT ?` with wrap-around.\n- `scan_range` advances `current = last ann_id + 1`.\n- Both rely on the UNIQUE index for range scans. The source connection is read-only and needs no registered function.\n\n**Old files:** a file with only `random_rowids` reads as None (`no_table`) in `open_random_cache_if_usable` and in the precompute keep check.\n\n**Dependents:**\n- `random_videos.py` imports `fetch_random_rowids` by name, and tests monkeypatch `random_videos.fetch_random_rowids`. All names must move together.\n- `precompute-random-rowids.py` imports `random_rowids_count`.\n- `tests/active/test_db.py`, `test_random_cache.py`, `test_random_videos.py` and `test_precompute_random_rowids.py` create `random_rowids` directly and assert positions over \"rowids 1..20\". With hash ids those expectations become sets of computed ids, and windows are no longer insertion-ordered.\n\nThe `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` rat-tail comment is unaffected.\n\nRisk: medium, from test churn and the rename.\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"import of fetch_random_rowids; fetch_random_rows_from_cache\">\nFollows the rename. `seen` and `fresh` hold `ann_id`s, passed to `fetch_metadata`. `RANDOM_CACHE_NSFW_MAX_DRAWS` logic is unchanged. Update the docstring (\"precomputed rowid cache\").\n\n`fetch_random_rows`, `fetch_recent_videos`, `fetch_popular_videos` and `fetch_ordered_page` do not touch ids.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-random-rowids.py\" element=\"import random_rowids_count; keep check; argparse description and --size help\">\nChanges:\n- The keep check uses the renamed count helper. An old-shape `--out` counts 0, so it is rebuilt.\n- The description \"Precompute random rowid cache.\" and the help \"Rowids to sample.\" change.\n- The file name and arguments stay.\n\nCallers:\n- `scripts/run-dataset-build.sh:262`\n- `tests/active/test_precompute_random_rowids.py` (its fixture source needs `ann_id`, and it asserts sorted ids `== range(1, 21)`)\n- `tests/config.json` maps that test to this file\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"comment above DEFAULT_RANDOM_CACHE_SIZE (line 352)\">\nThe comment \"Precomputed random rowids stored for fast random feed responses.\" should say ANN ids. Comment only.\n\nRisk: none.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"iter_embedding_rows_by_rowids, fetch_similarity_targets, fetch_similarity_targets_chunked, pending selection queries (SELECT e.rowid \u00d72), full-mode SELECT, main loop self-exclusion\">\n**Change.** Every `rowid` select and filter becomes `ann_id`: the helper names, the dict keys, `pending_rowids`, `batch_rowids` and `targets_by_rowid`. The self-exclusion becomes `ann_id_int == row[\"ann_id\"]`, and the full-mode select gains `ann_id`. Output keys (`video_id`, `instance_domain`) and the incremental and refresh-existing join on `video_keys` stay. The source connection is read-only (`mode=ro`), so no function registration is possible or needed.\n\n**AC5 dependency.** The AC5 gate (`assert_index_matches_embeddings`) runs first. It refuses a rowid index before any `ann_id` SELECT can fail on an old DB.\n\n**Callers:**\n- `updater-worker.run_similarity_stage`\n- `run-dataset-build.sh`\n- `tests/active/test_precompute_similar_ann.py`, which must change: its fixture table and explicit-rowid inserts, the `INDEX_BUILDER` that adds by rowid, and its sidecar without `id_source`.\n\n**Risk: medium.** The neighbours are wrong and nothing fails if one id site is missed.\n</impact>\n<impact path=\"engine/server/db/jobs/inspect-embedding.py\" element=\"main()\">\nIt reads only `embedding`, `embedding_dim`, `model_name`, `video_id` and `instance_domain`. No change.\n\nRisk: none.\n</impact>\n<impact path=\"engine/server/db/jobs/instance-denylist-cli.py\" element=\"--purge-now (via purge_host_data)\">\nNo change. This is one of the three coupling breaks the issue names. After the change, a purge without an index rebuild yields misses only, which AC8 covers.\n\nRisk: none.\n</impact>\n<impact path=\"engine/server/data/videos.py\" element=\"ensure_video_indexes\">\nNo change. It drops only `idx_video_embeddings_id_instance`, so the new UNIQUE index's name must differ (see `ann_ids`). It runs at every Engine start against `whitelist.db`.\n\n`tests/active/test_videos.py` builds its own table and is unaffected.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/data/similarity_candidates.py\" element=\"get_upnext_candidates / _compute_candidates (callers of ann functions)\">\nNo code change is expected. It passes seeds through to `search_similar_above` and `compute_similar_items`, which read the renamed seed key. `_build_rows` uses `fetch_metadata_by_ids` (key-based) and is unaffected.\n\nRisk: low, contingent on the seed-key rename being complete.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"handle_internal_video_resolve (via fetch_seed_embedding)\">\nNo edit. Its SQL now selects `e.ann_id` through `fetch_seed_embedding`, so a DB without the column fails this route. The response exposes only `video_id`, `uuid`, `host`, `channel` and `title`, never the id.\n\n`tests/active/test_internal_client_reads.py` exercises only the metadata and centroids handlers, so its fixture without `ann_id` should keep passing. The plan's \"Conflicts\" list names it among the churned files, which looks over-inclusive.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/api/recommendations/sources/ann_similar_from_likes.py\" element=\"seed_map from fetch_seed_embeddings_for_likes \u2192 get_similar_candidates\">\nNo edit. The seeds it builds carry the renamed key into `compute_similar_items`. Listed so the rename is verified end to end. `cached_similar_from_likes.py` follows the same flow.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-orchestrator-smoke.py\" element=\"copy_and_prune_prod / create_table_and_indexes_from_source; validate_outputs\">\nChanges:\n- **Add an `id_source == \"video_embeddings.ann_id\"` assertion** in `validate_outputs` next to the `meta_total` check (AC9).\n- **Copy the triggers.** `create_table_and_indexes_from_source` copies only `type='table'` and `type='index'` DDL from the source, so **the collision trigger is not copied** into mini-prod. The smoke merge would then run without the guard. Extend it to copy `type='trigger'` for `tbl_name`, or build `video_embeddings` from the shared definition.\n\nDependencies:\n- `INSERT INTO video_embeddings SELECT e.*` relies on identical column order, which holds when the DDL is copied.\n- `--source-db` defaults to `DEFAULT_DB_PATH` (`whitelist.db`), which must already be migrated. Otherwise mini-prod is old-shape and the merge guard stops the run (arguably correct, but it fails the smoke test).\n- `--inject-replace-embedding-for-test` depends on the updater inject computing `ann_id`.\n- The replace and mismatch checks compare all columns, `ann_id` included, which is equal for same-key replaces.\n\nRisk: medium.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-moderation-integration.py\" element=\"synthetic schema and the two INSERT OR REPLACE INTO video_embeddings seeds\">\nIts own `CREATE TABLE IF NOT EXISTS video_embeddings` has no `ann_id`, and it never runs `fetch_metadata`, ANN or the merge. It exercises purge and serving moderation only, so as written it should keep passing without change.\n\nThe plan lists it as churned. Change it only if the fixture is switched to the shared definition, or if the prod-sample mode copies from a migrated DB into this narrower table (it uses explicit column lists, so that is fine).\n\nUncertain: I did not trace every prod-sample path past line 790.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"new shared ann_id fixture helper; engine fixture; embedding_of\">\nThe plan puts a shared helper here that computes `ann_id` for fixture inserts. It must put `engine/server` on `sys.path` to import `data.ann_ids`; conftest currently inserts only `client/backend`.\n\nThe existing `embedding_of`, `closeness` and `identity_of` only SELECT from `whitelist.db` and need no change.\n\n**The session `engine` fixture starts the real Engine on the repo's `whitelist.db` and `whitelist-video-embeddings.faiss`.** After AC5 it exits at start until that dataset is migrated and the index rebuilt. That fails every Engine-backed active test, including:\n- `test_similar`, `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles`, `test_frontend_reactions` and the `test_random_cache` Engine cases.\n\nThis worktree has no `engine/server/db/whitelist.db` (only `random-cache.db`), so these tests read a shared dataset. DATA_BUILD says shared DB migrations run on main after merge only, so pre-merge validation of the Engine-backed suite is constrained.\n\nRisk: high, for the test environment.\n</impact>\n<impact path=\"tests/active/test_metadata.py\" element=\"nsfw_conn fixture table/insert; _nsfw_metadata (SELECT rowid \u2192 fetch_metadata)\">\nThe fixture table needs an `ann_id` column, with inserts through the shared helper. `_nsfw_metadata` must pass `ann_id`s. The other tests in the file use `fetch_metadata_by_ids` and are unaffected.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_random_videos.py\" element=\"NSFW_EMBEDDINGS_TABLE, nsfw_conn, _video_db (lastrowid map), _cache_owner (random_rowids table, fetch_random_rowids monkeypatch), docstring\">\n**Changes:**\n- `_video_db` maps labels to `lastrowid`, and the cache stores those ids. Both must become `ann_id` from the helper.\n- The fixture table needs the column.\n- `_cache_owner` creates `random_rowids` and monkeypatches `random_videos.fetch_random_rowids` and `random_cache.fetch_random_rowids`. These must follow the renames.\n- The docstring mentions \"unseen rowid\".\n\n**No change:**\n- `_feed_db` copies `src.video_embeddings` from the real `whitelist.db` with CTAS (no constraints).\n- The T2 copy then duplicates T's `ann_id`, which is harmless because no ordered-feed read uses `ann_id`. If the fixture ever adopts the shared definition, the copy would hit UNIQUE and the trigger.\n\n**Risk:** medium churn.\n</impact>\n<impact path=\"tests/active/test_random_cache.py\" element=\"_source_db, _seed_cache/_cache_rows/_cache_rowids (random_rowids), _served_rowids, _seed_servable_cache and _feed_rowids (SELECT rowid from whitelist.db), docstring assertions about 'source rowids 1..20'\">\n**Fixtures:**\n- `_source_db` needs `ann_id` populated.\n- Every direct `random_rowids` DDL, insert and read moves to `random_ann_ids(position, ann_id)`.\n\n**Assertions:**\n- \"positions 1..20 over source rowids 1..20\" and the order-dependent expectations become the set of the 20 computed ids.\n- The window under hash order differs from insertion order (stated in the plan's risks).\n\n**Engine cases:** they map feed rows back through `SELECT rowid FROM video_embeddings` on the real `whitelist.db`, which must become `ann_id`. They also need the migrated dataset and index (see conftest).\n\n**Cache-file probe:** the \"file without random_rowids\" `open_random_cache_if_usable` case should use an old-shape `random_rowids` file. It then also pins AC6's old-shape detection.\n\n**Risk:** high churn.\n</impact>\n<impact path=\"tests/active/test_db.py\" element=\"_source_db, _seed_cache, CHECK_SQL, fetch_random_rowids import, SEEDED_ROWIDS\">\nThe swap tests build a random cache from a source with no `ann_id` (needs the column and values). They seed `random_rowids` and use `CHECK_SQL` on `random_rowids`; all of that follows the rename. The import `from data.random_cache import build_random_cache, fetch_random_rowids` breaks on rename.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_precompute_random_rowids.py\" element=\"_source_db, _seed_cache, _cache_rows, assertions sorted(...)==range(1,21)\">\nChanges:\n- The source needs `ann_id`.\n- The seeded old-format cache should use the new table, plus one case with the old `random_rowids` shape to pin \"old shape is rebuilt, not kept\".\n- Assertions compare against the computed ids.\n\nThe job runs under `sys.executable`, so `data.ann_ids` must stay stdlib only.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_precompute_similar_ann.py\" element=\"source fixture (CREATE TABLE, explicit rowid inserts), INDEX_BUILDER (add_with_ids by rowid), sidecar JSON, _source_db\">\nChanges:\n- The fixture needs `ann_id` (helper-computed) and an index built on `ann_id`.\n- The sidecar must add `\"id_source\": \"video_embeddings.ann_id\"`, or the AC5 gate refuses every run.\n- `SHORT_ROWID` and the `v{rowid}` naming can stay as labels, but the ids are no longer 1..9.\n- `_source_db` (the refusal tests) runs before any read and needs no change.\n\nRisk: medium, because every test in the file fails until the sidecar is updated.\n</impact>\n<impact path=\"tests/active/test_video.py\" element=\"similars_stack (SELECT rowid \u2192 add_with_ids); embedded-video inserts at lines 543-544\">\nThe DB comes from `sync-whitelist.ensure_content_schema`, so it takes the new shape. The positional `INSERT INTO video_embeddings VALUES (6 values)` then breaks, both on column count and on NOT NULL `ann_id`. `similars_stack` must add the index with `ann_id`. The similars case asserts `seed v1 \u2192 [\"v2\"]`, which keeps working once ids match.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_whitelist_migrations.py\" element=\"_load_job of whitelist_migrations.py; new migration test\">\nThis is the natural place for:\n- the AC2 migration tests: backfill values, the UNIQUE index and trigger present, idempotence, and the early return when the table is missing;\n- an old-shape fixture.\n\nThe existing test passes, because `ensure_content_schema` creates the new-shape table and the migration no-ops. The module import of `data.ann_ids` relies on `sync-whitelist.py` having been loaded first; see `whitelist_migrations`.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_similarity_candidates.py\" element=\"video_embeddings fixture; data.ann stub\">\nExpected unaffected. Its `data.ann` stub replaces `search_similar_above` positionally, and `_build_rows` uses key-based metadata. Re-check if the `search_similar_above` signature changes order.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_search.py\" element=\"video_embeddings fixture\">\nExpected unaffected (`query_encoder=None`, so `fetch_metadata` is never reached). Listed because `tests/config.json` maps it to `metadata.py`, so a metadata change selects it.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_blocks.py\" element=\"dataset SELECT joining video_embeddings\">\nRead-only queries against the live `whitelist.db`; no fixture insert. The plan's \"Conflicts\" names it, but it should need no change beyond the dataset being migrated. `test_dislikes.py`, `test_dislike_profile.py`, `test_profiles.py` and `test_frontend_reactions.py` are the same: SELECT only, and Engine-backed.\n\nRisk: low in code, high in environment (see conftest).\n</impact>\n<impact path=\"tests/config.json\" element=\"test \u2192 source file map\">\nAdd `engine/server/data/ann_ids.py` to the tests that exercise it: `test_metadata`, `test_random_cache`, `test_random_videos`, `test_precompute_*`, `test_whitelist_migrations`, `test_video` and the new AC8 test. Add `embedding_space.py` where the gate matters. If the build adds a new job test file for AC8, add its entry.\n\nRisk: low. A missed mapping only weakens change-based selection.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"recorded test ids\">\nA generated artifact that lists test ids such as `test_precompute_random_rowids::...`. It is regenerated by the test run and should not be hand-edited. Renamed or added tests show up there.\n\nRisk: none.\n</impact>\n<impact path=\"scripts/run-dataset-build.sh\" element=\"sync, embeddings, index, random cache stages\">\nNo code change is required:\n- `precompute-random-rowids.py` keeps its name.\n- The `--force` re-embed keeps ids.\n- The index stage writes the new `id_source`.\n\nAn existing unmigrated `whitelist.db` now fails at the sync stage on the exact check, or at `--from index` on the AC4 guard. DATA_BUILD already says this script does not migrate. Optionally add a migrate step or a log hint.\n\nRisk: low.\n</impact>\n<impact path=\"scripts/run-reembed.sh\" element=\"comment line 28; sidecar log\">\nThe comment \"api/server.py compares the index sidecar's model_name\" could also mention `id_source`. Optional.\n\nRisk: none.\n</impact>\n<impact path=\"tests/archive/random_cache_in_place/test_random_cache.py\" element=\"archived tests using random_rowids\">\nArchived and not run. Leave unchanged; they reference `random_rowids` and rowids. `tests/archive/37_local_signal/test_random_videos.py` and `tests/archive/short_similarity_cache/test_similar.py` are the same.\n\nRisk: none.\n</impact>\n<impact path=\"docs/project/plans/17-stable-ann-ids.md\" element=\"Impacts / Implementation / Close sections; Conflicts list of churned tests\">\nThe build fills this plan file. Its \"Conflicts\" list of 9 churned `tests/active` files does not match the code:\n- **Actually needing change:** `test_metadata`, `test_random_videos`, `test_random_cache`, `test_db`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_video` (and `conftest` for the new helper).\n- **SELECT-only, no fixture insert:** `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles`, `test_frontend_reactions`.\n- **Unaffected:** `test_internal_client_reads`, which tests only routes that don't read `ann_id`.\n\nCorrect the list when filling Impacts.\n</impact>\n</impacts>\n</impacts>\n\n<docs_checklist>\n<doc path=\"DATA_BUILD.md\">\n- **Line 13:** \"random rowid cache\" becomes the random ANN-id cache.\n- **Line 155:** say that embeddings are copied with their `ann_id`, or that `ann_id` is computed when the crawl DB lacks it.\n- **Line 159:** the exact check now includes `ann_id`.\n- **Lines 161-172:** \"The migration is additive ... without touching rows ... second run does nothing\" is no longer true for `video_embeddings`. Add the one-time cutover:\n  1. Stop the Engine.\n  2. Run `migrate-whitelist.py`, a table rebuild that needs about 1.4 GB free plus the default full-file backup.\n  3. Run `build-ann-index.py`.\n  4. Start the Engine.\n\n  Also note that a stored `random-cache.db` is rebuilt automatically.\n- **Line 191:** the \"schedule with the stable-ANN-ids cutover\" note can now point at the cutover steps.\n- **Line 232:** \"The index uses `video_embeddings.rowid` as ids\" becomes `video_embeddings.ann_id`; mention `id_source` and the AC4 refusal message.\n- **Line 290:** \"random rowid pool\" changes.\n- **Line 335:** `select count(*) from random_rowids` becomes `random_ann_ids`.\n</doc>\n<doc path=\"DEPLOYMENT.md\">\n- **Line 42:** add the one-time ANN-id cutover (stop, migrate, build index, start) and that the Engine refuses to start on an index whose sidecar `id_source` is not `video_embeddings.ann_id`.\n- **Triage table:** add a row for that startup refusal, with the fix `build-ann-index.py`. Add one for the `migrate-whitelist.py` message from `build-ann-index`, merge and `build-video-embeddings`.\n- **Line 421:** random-cache text is unaffected beyond a first start rebuilding an old-shape cache.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\">\n- **Cutover:** the prerequisite one-time migrate and index rebuild before the first updater run on new code.\n- **`--resume-staging` (lines 48, 149, 186):** a pre-cutover staging DB now fails with the AC2 message and must be recreated by running without the flag.\n- **Line 61:** the ANN rebuild writes `id_source: video_embeddings.ann_id`.\n- **Merge:** it refuses an unmigrated prod or staging.\n- **Line 197:** `--inject-replace-embedding-for-test` keeps the row's `ann_id`.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md\">\n- **Validations list (around line 115):** add the sidecar `id_source` assertion.\n- **Source DB:** note that it must be migrated, since mini-prod copies its schema.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/LAYER_PARAMS.md\">\n- **Line 130:** \"has no `random_rowids` table\" becomes `random_ann_ids`. An old-format file counts as having no table.\n- **Line 140:** \"The cache holds only rowids (`random_rowids`)\" becomes ANN ids (`random_ann_ids`), resolved to rows by `ann_id`. Mention the hash-uniform sampling window.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/OVERVIEW.md\">\n- **Line 15:** \"drops rowids already seen\" / \"unseen rowid\" becomes ANN ids.\n- **Line 69:** \"Holds a prebuilt list of rowids\" becomes ANN ids (`random_ann_ids`).\n</doc>\n<doc path=\"engine/server/README.md\">\nLine 9 explains the `migrate-whitelist.py` requirement for `videos.language`. Optionally add that the Engine also refuses to start until the ANN-id cutover (migrate plus index rebuild) has run, pointing at DATA_BUILD.\n</doc>\n<doc path=\"docs/project/issues/08-stable-ann-ids.md\">\nAt close: set `Status: enhancement, complete` and move to `docs/project/issues/archive/`, per the triage labels.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nengine/server/db/jobs/whitelist_migrations.py (migrate_video_embeddings_schema): `executescript` commits per statement. If the UNIQUE index build fails on a backfill collision after DROP and RENAME, the table keeps `ann_id` with no UNIQUE index and no trigger. A re-run then takes the \"already has ann_id\" early return and never installs the guard. It needs one explicit transaction, or IF NOT EXISTS index and trigger creation on the early-return path too.\nengine/server/db/jobs/sync-whitelist.py (ensure_content_schema runs before ensure_schema_compatibility; the same pattern applies in build-video-embeddings.init_schema): if the shared definition creates the `ann_id` UNIQUE index or trigger unconditionally, an unmigrated whitelist or staging table fails with a raw \"no such column: ann_id\" from the index DDL. AC2's message naming migrate-whitelist.py, or recreating staging, is never reached.\nengine/server/data/embedding_space.py plus tests/active/conftest.py (the AC5 gate): every existing sidecar, including the shared dev/test dataset's index and the test_precompute_similar_ann sidecar that has no id_source, is refused. The Engine-backed active suite cannot start until a shared whitelist.db is migrated and reindexed, and DATA_BUILD says shared DB migrations run only on main after merge.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI read the files behind the inventory's load-bearing claims. Checked: `whitelist_migrations.py` (whole file), `migrate-whitelist.py` (sys.path, `with conn`, `backup_db`), `sync-whitelist.py` (column lists, the exact and superset checks, `ensure_content_schema` DDL, `rebuild_content_tables`, main ordering, trigger drops), `random_cache.py` (whole file), `embedding_space.py` (whole file), `server.py` 330-365, the `merge-staging-db.py`/`build-ann-index.py`/`build-video-embeddings.py`/`updater-worker.py` structure, the import closure of `data/moderation.py` and `data/similarity_cache.py`/`data/db.py`/`data/__init__.py`, the rename sites in `embeddings.py`/`ann.py`/`similar.py`/`search.py`/`metadata.py`/`random_videos.py`, the smoke test's DDL copy, and the `test_video.py`/`test_precompute_similar_ann.py` fixtures. Every entry I opened held up line for line. Every `rowid` hit in the tree outside the inventory refers to an unrelated table: `interaction_events.py`, `users.py`, the client's `blocks.py` and `users_store.py`. The plan stands. It has two ordering hazards (unconditional guard DDL, and a non-atomic migration), both already in the inventory. They need a decision during implementation, not a change of plan.\n<question id=\"1\">\nYes, on two conditions. **The DDL split.** The index and trigger must be created only after the old-shape check passes. `CREATE TABLE IF NOT EXISTS` is a no-op on an old table, but the index and trigger DDL then fails with a raw `no such column: ann_id`. In sync that DDL runs before `ensure_schema_compatibility` (lines 598-599), so AC2's message would be lost. **Migration re-runs.** A re-run must still install the guard after a failed backfill. The `migrate_*_schema` pattern uses `executescript`, and `migrate-whitelist.py`'s `with conn:` (line 86) gives it no atomicity. The trigger mechanism itself is sound against the code. FTS triggers are dropped by name only (sync 288-290, migrations 264-266), so the new trigger survives every sync. `ensure_video_indexes` drops only `idx_video_embeddings_id_instance`. The merge's `INSERT OR REPLACE` on `main` fires `main`'s trigger. I checked one possible overflow in `scan_range`: advancing to `last + 1` can reach 2^63 only when `last == range_end`, and the loop exits before binding, so the 63-bit ids are safe there. `data/ann_ids.py` \u2192 `data.moderation` \u2192 `data.similarity_cache` is stdlib-only and `data/__init__.py` is empty, so the `sys.executable` job tests still import cleanly.\n</question>\n<question id=\"2\">\n**Cutover.** It becomes a hard, ordered operation. `assert_index_matches_embeddings` (`server.py:365`) will refuse every existing sidecar, which still carries `id_source: \"video_embeddings.rowid\"` (`build-ann-index.py:284`). So every Engine, including the shared dataset behind `tests/active/conftest.py`'s session `engine`, stops at start until both steps are done: `migrate-whitelist.py` and `build-ann-index.py`. **Sync.** `sync-whitelist` and `run-dataset-build.sh` fail on any unmigrated `whitelist.db`. **Migration size.** It is no longer additive: it rewrites about 890k rows. With the default backup, `backup_db` (line 60) also copies the whole file through `read_bytes()`. That needs about 3.5 GB of extra disk and the same amount of RAM, on top of the 1.4 GB rebuild. **Random cache.** Every existing `random-cache.db` is treated as `no_table` at the next start, and a background rebuild runs (`server.py:344-345`). **Test churn.** As the inventory lists: 7 active test files plus conftest, not the 9 the plan file names.\n</question>\n<question id=\"3\">\nThese are all in the inventory; I add nothing new.\n- **Conditional DDL:** `ann_ids` creates the index and trigger only after the shape check.\n- **Migration:** run it in one explicit transaction, or have its early-return path also run `CREATE ... IF NOT EXISTS` for the index and trigger.\n- **`normalize_host` returning None:** decide what the id function does with it.\n- **Old-shape check:** give it a `schema` parameter for merge's `main`/`stage`.\n- **Updater inject:** compute and write `ann_id` (lines 1044-1056 omit it today).\n- **Smoke test:** copy `type='trigger'` DDL in `create_table_and_indexes_from_source` (it copies only tables and indexes, lines 204/215), and assert `id_source`.\n- **Precompute test:** add `id_source` to its sidecar (line 74).\n- **`test_video.py`:** move its positional 6-value inserts (543-544) and the rowid index (217-218) to `ann_id`.\n- **conftest:** put `engine/server` on `sys.path` for the helper.\n- **Shared dataset:** migrate it and rebuild its index before the Engine-backed suite can pass.\n- **Docs:** write the cutover runbook.\n</question>\n<question id=\"4\">\n- **Identity.** FAISS ids are no longer table positions. They are a 63-bit hash of `(video_id, normalize_host(instance_domain))`. A stale index now misses videos instead of returning the wrong ones.\n- **Random feed.** The unfiltered draw is a uniform hash-order window instead of a block of rows in insertion order. The cache file's table and column names change.\n- **Engine start.** The Engine refuses indexes that are not built on `ann_id`.\n- **Migration.** `migrate-whitelist.py` becomes a heavy, Engine-stopped rewrite.\n- **Collisions.** A duplicate id now aborts every writer, CLI included, where `OR REPLACE` used to delete the other video's row silently.\n- **`normalize_host`.** It becomes part of the persistent id contract, so it can no longer change for free.\n- **No change:** the API responses, merge strategy, sync's source requirements and `precompute-random-rowids.py`'s interface.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone. Every entry I opened matched its file. I did not trace these line by line, so I did not confirm them independently. precompute-similar-ann.py: 38 rowid hits, consistent with the entry but not walked site by site. test-moderation-integration.py past line 790, which the inventory itself flags. The test_random_cache.py, test_random_videos.py, test_db.py and test_precompute_random_rowids.py fixture details. The recommendations sources: no rowid reference in them, consistent with \"no edit\".\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Make the migration's guard self-healing.** `migrate_video_embeddings_schema` should run `CREATE UNIQUE INDEX IF NOT EXISTS` and `CREATE TRIGGER IF NOT EXISTS` on every run in which `ann_id` is present, not only right after the rebuild. Without this, a failed backfill (the UNIQUE build fails after DROP and RENAME) leaves a table with `ann_id` and no guard, and every later re-run skips it at the early return. Cost: two idempotent statements, and the file's `executescript` pattern stays. The alternative is one explicit `BEGIN ... COMMIT` around the whole rebuild. It is fully atomic, but it departs from the file's pattern and roughly doubles the transient disk use through the rollback journal.\n2. **Expose the shared DDL as two calls,** table creation and guard creation, with each caller running the guard after its shape check: `build-video-embeddings.init_schema`, and `sync-whitelist` after `ensure_schema_compatibility`. Cost: one extra call per caller. Without it, unmigrated DBs fail with raw sqlite errors instead of AC2's message.\n3. **Define how the id function handles a None from `normalize_host`.** Recommended: raise ValueError naming the domain. A silent fallback would create a second normalisation rule inside the id contract. Cost: one branch, and one test.\n4. **Correct the free-space figure in the runbook docs.** With the default backup, the migration needs about 3.5 GB of extra disk and about 3.5 GB of RAM, because `backup_db` reads the whole file into memory. Alternatively, document `--no-backup` together with an operator-side copy. Cost: doc text only. The accepted \"about 1.4 GB\" holds only without a backup, so the requirement doesn't need reopening.\n5. **When filling the plan file's Impacts, record the doc edits the plan already names** (`DATA_BUILD.md`, `DEPLOYMENT.md`, `UPDATER_WORKER.md`, `LAYER_PARAMS.md`, `OVERVIEW.md`). Also replace the 9-file churn list with the inventory's corrected 7 files plus conftest. Cost: none beyond editing.\n6. **Plan for the Engine-backed suite.** It cannot pass before the shared dataset is migrated and its index rebuilt. Either validate with a migrated local copy of the dataset before merge, or accept that the Engine-backed tests go red until the post-merge migration on main. Cost: a local copy (about 3.5 GB plus a rebuilt index), or a known red window.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation: stable ANN ids (issue 08, plan 17)\n\nEvery file in the impact inventory was read before drafting: `moderation.py`, `whitelist_migrations.py`, `embedding_space.py`, `random_cache.py`, `random_videos.py`, `metadata.py`, `embeddings.py`, `ann.py`, `search.py`, `similar.py`, `build-video-embeddings.py`, `build-ann-index.py`, `merge-staging-db.py`, `sync-whitelist.py`, `updater-worker.py`, both precompute jobs, the smoke test and the churned `tests/active` fixtures. The new code is shown in full; existing files get exact edits.\n\n### What the build has to test\n\n- **AC1, the id function:** same input gives the same output; the result is between 1 and 2^63-1; one pinned value; host normalisation (`\"Host.Example.\"` and `\"host.example\"` give the same id).\n- **AC2, the schema:**\n  - the new table shape;\n  - the CHECK refuses an id of 0;\n  - a doctored id is refused by the trigger on a plain INSERT, on `INSERT OR REPLACE` (the other row must survive) and on merge;\n  - a same-key replace keeps the id;\n  - the migration fills `ann_id`, is idempotent, does nothing when the table is missing, and leaves an unchanged old-shape table when it fails;\n  - the old-shape refusal message, for `main` and for `stage`.\n- **AC3, the writers:** build-video-embeddings (including `--force`), sync from a source with `ann_id` and from one without, merge, and the test inject.\n- **AC4/AC5, the index:** the sidecar's `id_source`, and the Engine refusing a rowid sidecar.\n- **AC6, the readers:** the renamed seed keys, ANN and metadata reads by `ann_id`, and an old-shape random cache treated as unusable and rebuilt.\n- **AC7:** the similarity precompute on `ann_id`.\n- **AC8:** a stale index after the table is renumbered and after a host purge.\n- **AC9:** the orchestrator smoke test checks `id_source`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/ann_ids.py` | **new**: id function, SQL registration, table definition, guards, old-shape check, `ANN_ID_SOURCE` |\n| `engine/server/data/moderation.py` | one comment line above `normalize_host` |\n| `engine/server/db/jobs/whitelist_migrations.py` | `sys.path` insert, `migrate_video_embeddings_schema`, called last |\n| `engine/server/db/jobs/build-video-embeddings.py` | `init_schema` uses the helper; the insert tuple and column list gain `ann_id` |\n| `engine/server/db/jobs/sync-whitelist.py` | `TARGET_EMBEDDING_COLUMNS`; table from the helper; guards created only when the column exists; copy or compute `ann_id` |\n| `engine/server/db/jobs/merge-staging-db.py` | old-shape check on `main` and `stage` before `BEGIN IMMEDIATE` |\n| `engine/server/db/jobs/updater-worker.py` | the test inject writes `ann_id` |\n| `engine/server/db/jobs/build-ann-index.py` | old-shape check; `ann_id` ids; `id_source` |\n| `engine/server/data/embedding_space.py` | `id_source` check and docstring |\n| `engine/server/data/embeddings.py`, `ann.py`, `metadata.py`, `search.py`, `api/handlers/similar.py` | rowid \u2192 `ann_id` rename |\n| `engine/server/data/random_cache.py`, `random_videos.py`, `db/jobs/precompute-random-rowids.py`, `api/server_config.py` (comment) | `random_ann_ids` cache |\n| `engine/server/db/jobs/precompute-similar-ann.py` | rowid \u2192 `ann_id` rename |\n| `engine/server/db/jobs/tests/test-orchestrator-smoke.py` | guards in mini-prod; `id_source` assertion |\n| `tests/active/*`, `tests/config.json` | fixtures, new tests, map entries |\n\nNo change: `merge_rules.json` (stays `INSERT_OR_REPLACE`), `migrate-whitelist.py`, `server.py`, `similarity_candidates.py`, the recommendation sources, `inspect-embedding.py`, `instance-denylist-cli.py`, `videos.py`, `test-moderation-integration.py` (its own narrow table, which never reaches `ann_id` readers, per the impact), and the archived tests.\n\n---\n\n### 1. `engine/server/data/ann_ids.py` (new)\n\n```python\n\"\"\"Derive, store and guard the ANN id of an embedded video (ADR-0006).\"\"\"\n\nfrom __future__ import annotations\n\nimport hashlib\nimport sqlite3\n\nfrom data.moderation import normalize_host\n\n# The sidecar id_source every index must carry; the Engine refuses any other.\nANN_ID_SOURCE = \"video_embeddings.ann_id\"\n# SQL name of compute_ann_id once register_ann_id_function has run on a connection.\nANN_ID_SQL_FUNCTION = \"ann_id_of\"\nANN_ID_MASK = (1 << 63) - 1\n\nANN_ID_INDEX_SQL = \"CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)\"\n# Plain SQL so every connection (Engine, sqlite3 CLI) can insert; BEFORE triggers run ahead of OR REPLACE conflict resolution, so a foreign id aborts instead of deleting the row that holds it.\nANN_ID_TRIGGER_SQL = \"\"\"\nCREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision\nBEFORE INSERT ON video_embeddings\nWHEN EXISTS (\n  SELECT 1 FROM video_embeddings\n  WHERE ann_id = NEW.ann_id\n    AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)\n)\nBEGIN\n  SELECT RAISE(ABORT, 'video_embeddings ann_id collision: another (video_id, instance_domain) already holds this ann_id; see docs/project/adr/0006-derived-ann-ids.md');\nEND\n\"\"\"\n\n\ndef compute_ann_id(video_id: str, instance_domain: str) -> int:\n    \"\"\"Return the 63-bit blake2b ANN id of video_id::normalize_host(instance_domain); 0 is left to the table's CHECK.\"\"\"\n    # A domain normalize_host rejects hashes as its trimmed lowercase text, so every key still has one deterministic id.\n    host = normalize_host(instance_domain) or str(instance_domain).strip().lower()\n    digest = hashlib.blake2b(f\"{video_id}::{host}\".encode(\"utf-8\"), digest_size=8).digest()\n    return int.from_bytes(digest, \"big\") & ANN_ID_MASK\n\n\ndef register_ann_id_function(conn: sqlite3.Connection) -> None:\n    \"\"\"Expose compute_ann_id to SQL on this connection as ann_id_of(video_id, instance_domain).\"\"\"\n    conn.create_function(ANN_ID_SQL_FUNCTION, 2, compute_ann_id, deterministic=True)\n\n\ndef create_video_embeddings_table(conn: sqlite3.Connection, table: str = \"video_embeddings\") -> None:\n    \"\"\"Create the video_embeddings table (or a rebuild's `table`) if missing; a no-op on an existing table of any shape.\"\"\"\n    conn.execute(\n        f\"\"\"\n        CREATE TABLE IF NOT EXISTS {table} (\n          video_id TEXT NOT NULL,\n          instance_domain TEXT NOT NULL,\n          embedding BLOB NOT NULL,\n          embedding_dim INTEGER NOT NULL,\n          model_name TEXT NOT NULL,\n          created_at TEXT NOT NULL,\n          ann_id INTEGER NOT NULL CHECK (ann_id > 0),\n          PRIMARY KEY (video_id, instance_domain),\n          FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)\n        )\n        \"\"\"\n    )\n\n\ndef create_ann_id_guards(conn: sqlite3.Connection) -> None:\n    \"\"\"Create the UNIQUE ann_id index and the collision trigger; the table must already have ann_id.\"\"\"\n    conn.execute(ANN_ID_INDEX_SQL)\n    conn.execute(ANN_ID_TRIGGER_SQL)\n\n\ndef assert_video_embeddings_has_ann_id(conn: sqlite3.Connection, schema: str = \"main\") -> None:\n    \"\"\"Raise if {schema}.video_embeddings exists without ann_id; a missing table is left to the caller.\"\"\"\n    columns = [row[1] for row in conn.execute(f\"PRAGMA {schema}.table_info(video_embeddings)\")]\n    if columns and \"ann_id\" not in columns:\n        raise RuntimeError(\n            f\"{schema}.video_embeddings has no ann_id column. \"\n            \"Run `engine/server/db/jobs/migrate-whitelist.py` to migrate the whitelist DB; \"\n            \"a staging DB reused with --resume-staging must be recreated by running the updater without --resume-staging.\"\n        )\n\n\ndef ensure_video_embeddings_schema(conn: sqlite3.Connection) -> None:\n    \"\"\"Create video_embeddings and its guards, refusing an old-shape table with the migrate message.\"\"\"\n    create_video_embeddings_table(conn)\n    assert_video_embeddings_has_ann_id(conn)\n    create_ann_id_guards(conn)\n```\n\n**Invariants and decisions**\n\n- **Stdlib only.** The module imports `hashlib` and `sqlite3`, plus `data.moderation`, which itself only imports `data.similarity_cache`. Jobs and tests that run under `sys.executable` (such as `test_precompute_random_rowids`) can still import it.\n- **When `normalize_host` returns None** (impact point 1): the id falls back to the trimmed, lowercased domain and never raises. A raise inside the registered SQL function would abort a whole sync over one odd host. `normalize_host` never returns text containing whitespace, and it returns every live host unchanged, because they are all already lowercase and trimmed.\n- **Ports** (impact point 1): `normalize_host` strips them, as AC1 requires. So `(v, h:8080)` and `(v, h:9090)` share an id, and the trigger stops that write loudly, which falls under the accepted \"collision stops loudly\". The live 0-collision measurement hashed the raw domain, so **check before merge, read-only:** `SELECT COUNT(*) FROM video_embeddings WHERE instance_domain LIKE '%:%'` on the live DB. If it returns 0, ports cannot cause a collision today.\n- **The DDL is split** (impact point 3). The table is created first. The guards are created only by callers that have confirmed `ann_id` exists (`ensure_video_embeddings_schema`, the sync column check, the migration), so an old-shape table always gets the AC2 message and never a raw `no such column: ann_id`.\n- **Names** (impact point 4): `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision` do not clash with `idx_video_embeddings_id_instance`, which `ensure_video_indexes` drops at every Engine start.\n- **Single statements.** Every DDL goes through `conn.execute`, never `executescript`, so creating the table and guards inside sync's `with conn:` does not commit early.\n- **Collisions.** An id of 0 fails the CHECK, which `OR REPLACE` cannot override. A colliding UPDATE fails on the UNIQUE index. A same-key replace matches no other row, so it passes the trigger and keeps the same id.\n\n### 2. `engine/server/data/moderation.py`\n\nAdd one line above `def normalize_host`:\n\n```python\n# Part of the ANN id contract (data/ann_ids.py): any change here re-keys every video_embeddings.ann_id, stored index and random cache.\n```\n\n### 3. `engine/server/db/jobs/whitelist_migrations.py`\n\nHeader. The `sys.path` insert means the module no longer relies on `sync-whitelist.py` having been loaded first (as `test_whitelist_migrations.py` currently does):\n\n```python\nimport sqlite3\nimport sys\nfrom pathlib import Path\n\nserver_dir = Path(__file__).resolve().parents[2]\nif str(server_dir) not in sys.path:\n    sys.path.insert(0, str(server_dir))\n\nfrom data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function\n```\n\nNew function, placed before `migrate_whitelist_schema`:\n\n```python\ndef migrate_video_embeddings_schema(conn: sqlite3.Connection) -> None:\n    \"\"\"Rebuild video_embeddings with the derived ann_id column, its UNIQUE index and its collision trigger (ADR-0006).\n\n    The rebuild runs in one explicit transaction. A backfill collision or a zero id fails the UNIQUE index or the CHECK and rolls back to the old shape, so a re-run retries the whole rebuild instead of skipping a table left without its guards. Idempotent: a table that already has ann_id, or no table at all, is left alone.\n    \"\"\"\n    if not _table_exists(conn, \"video_embeddings\"):\n        return\n    if \"ann_id\" in _columns(conn, \"video_embeddings\"):\n        return\n    register_ann_id_function(conn)\n    # Close whatever the earlier steps left open, as their executescript calls do.\n    conn.commit()\n    conn.execute(\"BEGIN\")\n    try:\n        conn.execute(\"DROP TABLE IF EXISTS video_embeddings_new\")\n        create_video_embeddings_table(conn, \"video_embeddings_new\")\n        conn.execute(\n            f\"\"\"\n            INSERT INTO video_embeddings_new (\n              video_id,\n              instance_domain,\n              embedding,\n              embedding_dim,\n              model_name,\n              created_at,\n              ann_id\n            )\n            SELECT\n              video_id,\n              instance_domain,\n              embedding,\n              embedding_dim,\n              model_name,\n              created_at,\n              {ANN_ID_SQL_FUNCTION}(video_id, instance_domain)\n            FROM video_embeddings\n            \"\"\"\n        )\n        conn.execute(\"DROP TABLE video_embeddings\")\n        conn.execute(\"ALTER TABLE video_embeddings_new RENAME TO video_embeddings\")\n        # Created after the rename so their SQL names the final table.\n        create_ann_id_guards(conn)\n    except BaseException:\n        conn.rollback()\n        raise\n    conn.commit()\n```\n\n`migrate_whitelist_schema` gains a last line, `migrate_video_embeddings_schema(conn)`, after `migrate_videos_language`. When `migrate_videos_schema` has just dropped the table, the new step returns early.\n\n**Departure from the pattern, named.** The existing steps use `executescript`, which commits before it runs and then runs in autocommit. This step uses an explicit `BEGIN`/`COMMIT` instead, because of the atomicity risk the impact inventory names. Its shape (`_new` table, copy, drop, rename) is the existing pattern. The `with conn:` in `migrate-whitelist.py` stays harmless: nothing is left open for it to commit. The FK on `videos` does not affect the DROP or the RENAME, because `migrate-whitelist`'s connection does not enable `foreign_keys`.\n\n### 4. `engine/server/db/jobs/build-video-embeddings.py`\n\n- Import, after `CompactHelpFormatter`: `from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema`.\n- `init_schema` becomes:\n\n```python\ndef init_schema(conn: sqlite3.Connection) -> None:\n    \"\"\"Create video_embeddings in its ann_id shape, refusing an old-shape table.\"\"\"\n    ensure_video_embeddings_schema(conn)\n    conn.commit()\n```\n\n- The tuple in the batch loop gains `compute_ann_id(video_id, instance_domain)` as its last item. The insert becomes:\n\n```python\n            INSERT OR REPLACE INTO video_embeddings\n              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)\n            VALUES (?, ?, ?, ?, ?, ?, ?)\n```\n\n- `--force` (DELETE, then reinsert) gives every key back its old id. `--model-name` stays an `add_argument` with a constant default, which `run-reembed.sh` depends on.\n- An old-shape staging DB (`--resume-staging`) or `whitelist.db` stops in `init_schema` with the AC2 message, before the model loads.\n\n### 5. `engine/server/db/jobs/sync-whitelist.py`\n\n- Import: `from data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function`.\n- `EMBEDDING_COLUMNS` keeps its six names; it is now the source superset and the copied columns. Add, following the `WHITELIST_DERIVED_VIDEO_COLUMNS` precedent:\n\n```python\n# Derived in the whitelist DB from (video_id, instance_domain) (data/ann_ids.py). An older crawl DB lacks it, so it belongs in the exact check against `main.video_embeddings` but not in the source superset check.\nTARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + [\"ann_id\"]\n```\n\n- `ensure_schema_compatibility`: `_assert_columns_exact(conn, \"video_embeddings\", TARGET_EMBEDDING_COLUMNS)`. An unmigrated DB gets \"missing columns: ann_id ... Run `engine/server/db/jobs/migrate-whitelist.py`\".\n- `ensure_content_schema`: remove the inline `video_embeddings` DDL from the `executescript`. After it, and before `create_videos_fts_triggers(conn)`, add:\n\n```python\n    create_video_embeddings_table(conn)\n    # An old-shape table is left for ensure_schema_compatibility to refuse with the migrate message; creating guards on it would fail on the missing column first.\n    if \"ann_id\" in _table_columns(conn, \"video_embeddings\"):\n        create_ann_id_guards(conn)\n```\n\nThis resolves the ordering hazard without moving the check that `main()` runs afterwards. `repair-video-channel-names.py` and the tests that call `ensure_content_schema` on new DBs get the new shape with guards.\n\n- `rebuild_content_tables` embedding copy:\n\n```python\n    if source_embedding_columns.issuperset(EMBEDDING_COLUMNS):\n        embedding_columns = \", \".join(EMBEDDING_COLUMNS)\n        # A crawl DB that predates ann_id gets it derived here, so its embeddings are kept rather than re-embedded; the trigger guards every row either way.\n        register_ann_id_function(conn)\n        ann_id_expr = \"ann_id\" if \"ann_id\" in source_embedding_columns else f\"{ANN_ID_SQL_FUNCTION}(video_id, instance_domain)\"\n        conn.execute(\n            f\"\"\"\n            INSERT INTO video_embeddings ({embedding_columns}, ann_id)\n            SELECT {embedding_columns}, {ann_id_expr}\n            FROM {SOURCE_SCHEMA}.video_embeddings\n            WHERE (video_id, instance_domain) IN (\n              SELECT video_id, instance_domain FROM videos\n            );\n            \"\"\"\n        )\n```\n\n  A collision raises inside the `with conn:` in `main()`, so the whole sync rolls back. Each row costs one probe of the UNIQUE index (around 890k).\n\n### 6. `engine/server/db/jobs/merge-staging-db.py`\n\n- Import: `from data.ann_ids import assert_video_embeddings_has_ann_id`.\n- In `main()`, the first lines inside `try:`, before `conn.execute(\"BEGIN IMMEDIATE\")`:\n\n```python\n        # An old-shape stage would drop ann_id from merge_columns, and an old-shape main would take rows without one: refuse both with the migrate message.\n        assert_video_embeddings_has_ann_id(conn, \"main\")\n        assert_video_embeddings_has_ann_id(conn, \"stage\")\n```\n\n- They sit inside `try` so the existing `finally` still detaches and closes. The existing `except` calls `rollback()`, which does nothing when no transaction is open.\n- The rule loop is unchanged. `merge_columns` now includes `ann_id`, and `INSERT OR REPLACE INTO main.video_embeddings` fires `main`'s trigger on each row. Inside a trigger on `main`, the unqualified `video_embeddings` resolves to `main`, which is the intended table.\n\n### 7. `engine/server/db/jobs/updater-worker.py`\n\n- Import, next to `data.moderation`: `from data.ann_ids import compute_ann_id`. `server_dir` is already on `sys.path` (lines 24-27), so the plan's fallback `sys.path` insert is not needed.\n- `inject_replace_embedding_for_test`: docstring \"Insert one overlapping embedding row into staging with modified payload and the same ann_id.\" The insert becomes:\n\n```python\n            INSERT OR REPLACE INTO video_embeddings\n              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)\n            VALUES (?, ?, ?, ?, ?, datetime('now'), ?)\n```\n\n  with `compute_ann_id(video_id, instance_domain)` added to the parameters. The id is computed rather than read from prod, so the inject works whatever shape prod has, and an old-shape prod is still refused at merge.\n\n### 8. `engine/server/db/jobs/build-ann-index.py`\n\n- Import: `from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id`.\n- `EmbeddingRow.rowid` becomes `ann_id: int`. In `iter_embeddings`, `for ann_id, embedding_blob, embedding_dim in rows:` and `EmbeddingRow(ann_id=ann_id, ...)`.\n- In `main()`, right after connecting and before `resolve_embedding_space`: `assert_video_embeddings_has_ann_id(conn)`. This is the AC4 refusal, and it names `migrate-whitelist.py`.\n- Add query: `\"SELECT ann_id, embedding, embedding_dim FROM video_embeddings\"`. Ids: `np.array([item.ann_id for item in batch], dtype=np.int64)`; a 63-bit id fits.\n- `meta[\"id_source\"] = ANN_ID_SOURCE`.\n- `fetch_training_samples` is unchanged: `rowid % step` only spreads the training sample and is never an identity. This is a named simplification.\n\n### 9. `engine/server/data/embedding_space.py`\n\n- Import: `from data.ann_ids import ANN_ID_SOURCE`.\n- Docstring: one more paragraph: \"The sidecar also records `id_source`. Readers resolve hits by `video_embeddings.ann_id` (ADR-0006), so an index whose ids are rowids would return the wrong videos and is refused.\"\n- After the model check:\n\n```python\n    index_id_source = str(meta.get(\"id_source\") or \"\")\n    if index_id_source != ANN_ID_SOURCE:\n        raise RuntimeError(\n            f\"Index ids come from {index_id_source or '<unset>'} but readers resolve \"\n            f\"{ANN_ID_SOURCE}. Rebuild the index with build-ann-index.py.\"\n        )\n```\n\n  This also guards `precompute-similar-ann.py`.\n\n### 10. Readers: rowid \u2192 `ann_id` rename\n\n**`data/embeddings.py`**\n- The four `e.rowid AS rowid` selects become `e.ann_id AS ann_id`.\n- `_seed_from_row` returns `\"ann_id\": int(row[\"ann_id\"])`.\n- In `resolve_seed`, every `\"exclude_rowid\"` becomes `\"exclude_ann_id\"` (all three return shapes), and `\"rowid\": seed[\"rowid\"]` becomes `\"ann_id\": seed[\"ann_id\"]`.\n\n**`data/ann.py`**\n- `compute_similar_items`: `ann_ids = [int(item) for item in ids[0] if int(item) > 0]`. The log key becomes `ann_ids=%d`. The loop variable becomes `ann_id`/`ann_id_int`, and the self check `== seed[\"ann_id\"]`.\n- `search_similar_above`: `seed_ann_id = seed.get(\"ann_id\")`, with the `> 0` filter kept.\n- `search_index(index, vector, limit, exclude_ann_id)` keeps the same position. Its docstring becomes \"optionally exclude an ANN id\", and its loop variable `ann_id`.\n- The nprobe helpers are untouched.\n\n**`data/metadata.py`**\n- `fetch_metadata(conn, ann_ids: list[int], ...)`, docstring \"Fetch video metadata for embedding ANN ids.\"\n- `e.ann_id AS ann_id`, `WHERE e.ann_id IN (...)` (served by the UNIQUE index), `result[int(row[\"ann_id\"])]`. Every caller passes ids positionally (checked).\n- The output dicts still do not carry the id.\n\n**`data/search.py`**\n- In `vector_candidates`, `ann_ids, _scores = search_index(...)`, and the rest of the function follows.\n- `VIDEO_ROW_SQL` `v.rowid` (the `videos_fts` link) is unchanged.\n\n**`api/handlers/similar.py`**\n- `ann_ids, scores = search_index(self.server.index, vector, limit, seed[\"exclude_ann_id\"])`; the `fetch_metadata` call and the loop are renamed to match.\n\n### 11. Random cache\n\n**`data/random_cache.py`**\n- `RANDOM_CACHE_CHECK_SQL = \"SELECT COUNT(*) FROM random_ann_ids\"`.\n- Table: `random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)`.\n- `random_rowids_count` becomes `random_ann_ids_count`. It looks for `name = 'random_ann_ids'`, with the docstring \"Return the number of cached ANN ids, or None when the random_ann_ids table is missing (an old-format random_rowids file counts as missing).\"\n- `populate_random_cache`:\n  - the source stats become `COUNT(*) AS total, MIN(ann_id) AS min_id, MAX(ann_id) AS max_id`;\n  - the unfiltered scan becomes `SELECT ann_id FROM video_embeddings WHERE ann_id >= ? ORDER BY ann_id LIMIT ?`, with a wrap that uses `ann_id < ?`;\n  - the filtered `scan_range` selects `e.ann_id AS ann_id`, `WHERE e.ann_id >= ? AND e.ann_id <= ? ORDER BY e.ann_id`, and sets `current = int(rows[-1][\"ann_id\"]) + 1`;\n  - the locals become `ann_ids`, and the inserts become `INSERT INTO random_ann_ids (position, ann_id)`.\n  - Comment above the start draw: \"# Hashed ids are uniform over [min_id, max_id], so a window from a random start is a uniform sample, not a block of insertion order.\"\n- `build_random_cache` docstring: \"(temp path, ANN ids written, elapsed seconds)\".\n- `open_random_cache_if_usable` docstring: \"holds at least one ANN id\". The `no_table` path now also covers old `random_rowids` files. No new code is needed.\n- `fetch_random_rowids` becomes `fetch_random_ann_ids`, which reads `SELECT ann_id FROM random_ann_ids ORDER BY position ...`.\n\n**`data/random_videos.py`**\n- `from data.random_cache import fetch_random_ann_ids`. In `fetch_random_rows_from_cache`, the locals become `ann_ids`, and the docstring says \"precomputed ANN-id cache\" and \"unseen ANN id\".\n\n**`db/jobs/precompute-random-rowids.py`**\n- Imports `random_ann_ids_count`. An old-shape `--out` counts as 0 and is rebuilt.\n- `description=\"Precompute random ANN-id cache.\"` and `--size` help `\"ANN ids to sample.\"`. The file name and arguments are unchanged.\n\n**`api/server_config.py`**\n- The comment becomes \"Precomputed random ANN ids stored for fast random feed responses.\"\n\n**Named simplification.** An old cache is detected by its table name, not its shape. The ceiling: a future reshape under the same name would need a column check. The upgrade: compare `PRAGMA table_info` in `random_ann_ids_count`.\n\n### 12. `engine/server/db/jobs/precompute-similar-ann.py`\n\n- `iter_embedding_rows_by_rowids` becomes `iter_embedding_rows_by_ann_ids(conn, ann_ids, batch_size=512)`, which selects `ann_id, video_id, instance_domain, embedding, embedding_dim` with `WHERE ann_id IN (...)`.\n- `fetch_similarity_targets` and `fetch_similarity_targets_chunked` take `ann_ids`, select `ann_id, video_id, instance_domain` with `WHERE ann_id IN`, and return `{row[\"ann_id\"]: dict(row)}`. Their docstrings say \"ANN id\".\n- Both selection queries use `SELECT e.ann_id`, and `pending_ann_ids = [int(row[\"ann_id\"]) ...]`. The full mode selects `ann_id, video_id, instance_domain, embedding, embedding_dim`. The comment at line 366 says \"only ANN ids are materialized\".\n- In the loop: `batch_ann_ids`, `targets_by_ann_id`, and `if ann_id_int == row[\"ann_id\"] or ann_id_int <= 0: continue`.\n- The output keys and the `video_keys` joins are unchanged. The local `set_nprobe` is unchanged. The source stays `mode=ro`, so nothing is registered on it.\n\n### 13. `engine/server/db/jobs/tests/test-orchestrator-smoke.py`\n\n- Import: `from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id, create_ann_id_guards`.\n- In `copy_and_prune_prod`, right after `create_table_and_indexes_from_source(conn, table)` for `table == \"video_embeddings\"`:\n\n```python\n            if table == \"video_embeddings\":\n                # The copy brings tables and indexes only; mini-prod needs the collision trigger for the merge to run guarded, and an unmigrated source is refused here with the migrate message.\n                assert_video_embeddings_has_ann_id(conn)\n                create_ann_id_guards(conn)\n```\n\n  This is chosen over copying `type='trigger'` generally, which would also bring `videos_fts_*` triggers into a mini-prod that has no `videos_fts`.\n\n- In `validate_outputs`, after `meta_total`:\n\n```python\n    if meta.get(\"id_source\") != ANN_ID_SOURCE:\n        raise RuntimeError(f\"ANN meta id_source is {meta.get('id_source')!r}, expected {ANN_ID_SOURCE!r}\")\n    checks[\"ann_id_source\"] = meta[\"id_source\"]\n```\n\n- `INSERT INTO video_embeddings SELECT e.*` still works, because the DDL is copied with the same column order.\n\n### 14. Tests\n\n**Shared helper.** `tests/active/conftest.py` appends `ROOT / \"engine\" / \"server\"` to `sys.path` after the client imports. Appending rather than inserting keeps `client/backend`'s `server` and `lib` first. It then re-exports `from data.ann_ids import compute_ann_id  # noqa: E402`, and tests use `from conftest import compute_ann_id`.\n\n**New: `tests/active/test_ann_ids.py`.** Runs on the system interpreter, apart from the AC8 child.\n- AC1:\n  - the same call gives the same result;\n  - `1 <= id <= 2**63-1` over a few hundred keys;\n  - one literal pinned value for `(\"abc\", \"peertube.example\")`, computed once by an independent `hashlib` one-liner at implementation time and pasted in as a constant;\n  - `\"Peertube.Example.\"` gives the same id;\n  - an unparsable domain falls back deterministically.\n- AC2, schema: `ensure_video_embeddings_schema` on a DB that has `videos`, then:\n  - `INSERT` with `ann_id=0` raises IntegrityError (CHECK);\n  - a doctored `ann_id` equal to another key's id raises IntegrityError on a plain INSERT, and again on `INSERT OR REPLACE`; afterwards the other row still exists, unchanged;\n  - a same-key `INSERT OR REPLACE` keeps the count and the id;\n  - an UPDATE to a taken id raises (UNIQUE).\n- AC2, old shape:\n  - `assert_video_embeddings_has_ann_id` on a six-column table raises a message containing `migrate-whitelist.py` and `--resume-staging`;\n  - on an attached schema, it names `stage.`;\n  - on a missing table, it does nothing.\n- AC2, merge: run `merge-staging-db.py` as a subprocess on a tmp prod and staging pair.\n  - A doctored staging row (a new key carrying an existing prod id) exits non-zero; prod is unchanged and the other video is present.\n  - An old-shape stage exits non-zero with the message.\n  - A normal merge carries `ann_id` across.\n- AC3: `sync-whitelist.rebuild_content_tables`, loaded with `importlib` the way the existing tests do, on an attached source **with** `ann_id`, which is copied, and on one **without**, which is computed and equals `compute_ann_id`. In both cases `ensure_schema_compatibility` passes on the new shape and fails on an old target with \"missing columns: ann_id ... migrate-whitelist.py\".\n- AC5: `assert_index_matches_embeddings` with a stub index (`SimpleNamespace(d=4)`) and a sidecar:\n  - `id_source` `video_embeddings.rowid` raises naming `build-ann-index.py`;\n  - a missing `id_source` raises;\n  - `video_embeddings.ann_id` passes.\n\n**New: `tests/active/test_stale_ann_index.py` (AC8).** It runs a child under `ENGINE_PY`, the `test_precompute_similar_ann` pattern, because it needs faiss and numpy.\n- The child builds a small DB (`videos`, `channels`, `video_embeddings` via `ensure_video_embeddings_schema`) and an `IDMap2,IVF1,Flat` index on `ann_id`. It records `ann_id \u2192 (video_id, host)` from the vectors it indexed.\n- **Case A, renumber.** Delete every row and reinsert them in reversed order. The rowids change and the ids do not.\n- **Case B, purge.** Run `purge_host_data` for one host.\n- **Case C.** Insert a new video that the index does not hold.\n- After each case, the child calls `ann.compute_similar_items` and `search.vector_candidates`. It uses a stub server (`index`, `index_lock`, `db`, `db_lock`, `normalize_queries=False`, `similarity_*` defaults, and a `query_encoder` stub whose `enabled=True` and whose `encode` returns a fixed vector).\n- It prints JSON. The test asserts that every returned `(video_id, instance_domain)` equals the identity recorded for the vector whose hit produced it, that the purged host's videos are absent, and that the new video is absent rather than substituted.\n- This is a departure from the plan's word \"job test\": it lives in `tests/active`, where the gating suite runs and where the faiss-in-a-child precedent already exists.\n\n**Migration tests (in `tests/active/test_whitelist_migrations.py`).** An old six-column table with 3 rows, then `migrate_whitelist_schema`:\n- the columns include `ann_id`, and each value equals `compute_ann_id`;\n- `idx_video_embeddings_ann_id` and the trigger are in `sqlite_master`;\n- a second run changes nothing (same `sqlite_master` and the same rows);\n- a DB without the table is left alone;\n- an old table with a doctored duplicate cannot occur from the function, so failure atomicity is pinned by registering a stub `ann_id_of` that returns a constant. The migration raises, and the old table still has six columns and every row.\n\nThe test also inserts `engine/server` on `sys.path` itself; the module now does that too.\n\n**Fixture churn.**\n\n| File | Change |\n|---|---|\n| `test_metadata.py` | Fixture DDL gains `ann_id INTEGER`. Inserts pass `compute_ann_id(label, HOST)`. `_nsfw_metadata` selects `ann_id` instead of `rowid`. |\n| `test_random_videos.py` | `NSFW_EMBEDDINGS_TABLE` gains `ann_id`. `_video_db` maps labels to `compute_ann_id`. `_cache_owner` creates `random_ann_ids(position, ann_id)` and monkeypatches `fetch_random_ann_ids` on both modules. The docstring says \"unseen ANN id\". CTAS copies from `whitelist.db` are unchanged. |\n| `test_random_cache.py` | `_source_db` gains an `ann_id` column with computed values. Every `random_rowids` becomes `random_ann_ids`. \"positions 1..20 over rowids 1..20\" becomes the set of the 20 computed ids. Engine cases map rows back with `SELECT ann_id`. The \"no table\" probe uses an old-format `random_rowids` file, which pins AC6's old-shape case. |\n| `test_db.py` | Its source gains `ann_id`. `_seed_cache` and `CHECK_SQL` move to `random_ann_ids`. Imports `fetch_random_ann_ids`. `SEEDED_ROWIDS` becomes computed ids. |\n| `test_precompute_random_rowids.py` | Its source gains `ann_id`. Assertions use `sorted(computed ids)`. New case: an `--out` holding an old `random_rowids` table with `--size` rows is rebuilt into `random_ann_ids`, not kept. |\n| `test_precompute_similar_ann.py` | The fixture table gains `ann_id` (`compute_ann_id`). `INDEX_BUILDER` adds with `SELECT ann_id, embedding`. The sidecar adds `\"id_source\": \"video_embeddings.ann_id\"`. `SHORT_ROWID` and `v{n}` stay as labels only. |\n| `test_video.py` | The positional inserts at 543-544 become explicit column lists, with `ann_id`. `similars_stack` selects `ann_id` for `add_with_ids`. |\n\n`test_internal_client_reads`, `test_search`, `test_similarity_candidates` and `test_videos` are unchanged, because none of them reaches `ann_id`. `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles` and `test_frontend_reactions` are SELECT-only and need no code change. `test-moderation-integration.py` is unchanged, per its impact. The plan's \"Conflicts\" list is corrected when Impacts is filled.\n\n**`tests/config.json`.**\n- Add `engine/server/data/ann_ids.py` to `test_ann_ids`, `test_stale_ann_index`, `test_metadata`, `test_random_cache`, `test_random_videos`, `test_db`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_whitelist_migrations` and `test_video`.\n- Add `embedding_space.py` to `test_ann_ids` and `test_precompute_similar_ann`.\n- Map the two new files to the sources they exercise.\n\n`tests/last_test_validation.json` is regenerated by the test run, not edited by hand.\n\n### 15. Docs\n\nThese follow the settled documentation list:\n- `DATA_BUILD.md`, `DEPLOYMENT.md` and `UPDATER_WORKER.md` get the cutover: stop the Engine, run `migrate-whitelist.py` (a rebuild that needs about 1.4 GB free plus the default full-file backup, about 3.5 GB, unless `--no-backup` is used), run `build-ann-index.py`, then start the Engine. They also cover the refusal messages and the `--resume-staging` behaviour.\n- `ORCHESTRATOR_SMOKE_TEST.md`: the `id_source` check, and that the source must be migrated.\n- `LAYER_PARAMS.md` and `OVERVIEW.md`: `random_ann_ids`.\n- `engine/server/README.md`: the optional startup-refusal note.\n- At close, the issue gets `Status: enhancement, complete` and moves to the archive.\n\n### Seams and environment notes for the test steps\n\n- **Engine-backed tests and the shared dataset.** The session `engine` fixture starts the real Engine on the shared `whitelist.db` and index. After AC5 it exits at startup until that dataset is migrated and its index rebuilt. DATA_BUILD runs shared migrations on main only after merge. So the Engine-backed `tests/active` cases can only go green once the cutover has run on the dataset they read. The unit and job tests above do not depend on it. The gate step has to schedule this; the code cannot fix it.\n- **The smoke test's `--source-db`** must likewise be migrated. Otherwise it stops with the AC2 message, by design.\n\n### Pass check against the plan and the requirements\n\n**Pass 1** found these gaps; the draft above includes the fixes:\n1. The guards on old tables would fail with a raw sqlite error (sync's ordering hazard and `init_schema`). Fixed by the split DDL and the conditional guard creation.\n2. The migration was not atomic (a failed index build left a table with no guards). Fixed by the explicit transaction.\n3. `whitelist_migrations` depended on load order. Fixed by its own `sys.path` insert.\n4. Mini-prod would have no trigger. Fixed by creating the guards after the copy.\n5. `None` and ports from `normalize_host`. Settled: fall back to the raw domain, with a port pre-check query.\n6. The test sidecar had no `id_source`. Fixed.\n\n**Pass 2** found everything met:\n- **AC1:** the one helper, stdlib, 63-bit, pinned value.\n- **AC2:**\n  - the column, CHECK and UNIQUE index;\n  - the migration follows the rebuild shape, is idempotent and is called last;\n  - every creator uses the one definition;\n  - the trigger guards every path, including `OR REPLACE`;\n  - an old shape fails with a message naming `migrate-whitelist.py` or staging recreation.\n- **AC3:**\n  - every writer stores the helper's id;\n  - merge changes only by the approved guard;\n  - sync copies or computes the id, with the source check still the six columns;\n  - re-runs keep the same ids.\n- **AC4:** `ann_id` ids, `id_source`, and the refusal.\n- **AC5:** the gate, naming `build-ann-index.py`.\n- **AC6:** every listed reader uses `ann_id`, and an old cache is never read.\n- **AC7:** `ann_id` throughout, with output keys and selection unchanged.\n- **AC8:** the stale-index test.\n- **AC9:** the smoke test assertion and the docs.\n- **Consistency:** CLIs unchanged, the refusal style followed, `normalize_host` reused, each file's style kept.\n\nThe two departures (the transaction in the migration, and the AC8 test living in `tests/active`) are named above.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the public functions of `engine/server/data/ann_ids.py`, called directly (rung 1) against a tmp-path sqlite DB that already holds a `videos` table, in the new `tests/active/test_ann_ids.py`; system interpreter, `compute_ann_id` re-exported through `tests/active/conftest.py`. Clause 1 checks: one call returns the pinned literal for `(\"abc\", \"peertube.example\")`, a value computed independently with `hashlib` and pasted in; `\"Peertube.Example.\"` and `\"peertube.example\"` give the same id, which excludes hashing the raw domain; every id over a few hundred keys lies in `[0, 2**63-1]`, which excludes an unmasked 64-bit read. Clause 2 checks, after `ensure_video_embeddings_schema`: a plain INSERT carrying another key's ann_id raises IntegrityError; the same doctored row under `INSERT OR REPLACE` raises IntegrityError, and the holder's row is still present with its embedding and ann_id unchanged, which excludes a UNIQUE-only guard that OR REPLACE would satisfy by deleting the holder; a same-key `INSERT OR REPLACE` keeps the row count and the id, which excludes a trigger that also blocks re-embeds.</checkpoint>\n<name>Id function and schema guard</name>\n<intent>`data/ann_ids.py` derives each embedded video's ANN id from its `(video_id, normalised host)`, and a `video_embeddings` table created through it refuses any row whose ann_id another key already holds, whatever the insert verb.</intent>\n<clause_1>`compute_ann_id(video_id, instance_domain)` returns the big-endian 8-byte blake2b of `video_id::normalize_host(instance_domain)` masked to 63 bits.</clause_1>\n<clause_2>A table created by `ensure_video_embeddings_schema` refuses a row whose ann_id is held by a different `(video_id, instance_domain)`, under both plain INSERT and INSERT OR REPLACE, and the holder's row survives.</clause_2>\n<files>engine/server/data/ann_ids.py (NEW), engine/server/data/moderation.py (EDITED), tests/active/conftest.py (EDITED), tests/active/test_ann_ids.py (NEW), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: `migrate_whitelist_schema(conn)` called directly on a tmp DB holding an old six-column `video_embeddings` with 3 rows, using the existing `tests/active/test_whitelist_migrations.py` harness (fixture DB built from `sync-whitelist.py`'s schema helpers). Clause 1 checks: `PRAGMA table_info` includes `ann_id`; for each of the 3 rows, `ann_id == compute_ann_id(video_id, instance_domain)`, which excludes a constant or rowid backfill; `sqlite_master` holds both `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision`, which excludes a rebuild that skips the guards; the 3 rows keep their embedding bytes. Clause 2 checks: with a stub `ann_id_of` registered that returns a constant, `migrate_whitelist_schema` raises; afterwards the table has exactly the six old columns, which excludes a non-transactional rebuild that leaves the new shape without guards; all 3 rows are present and unchanged; no `video_embeddings_new` is left behind. Idempotence and the missing-table no-op are inner units.</checkpoint>\n<name>Whitelist migration</name>\n<intent>`migrate_whitelist_schema` turns an existing six-column `video_embeddings` into the ann_id shape in one transaction, so a migrated table carries derived ids with its guards and a failed rebuild leaves the old table as it was.</intent>\n<clause_1>After `migrate_whitelist_schema`, every pre-existing row has `ann_id` equal to `compute_ann_id` of its key, and the UNIQUE index and the collision trigger exist.</clause_1>\n<clause_2>A rebuild that fails partway leaves `video_embeddings` with its six original columns and every original row.</clause_2>\n<files>engine/server/db/jobs/whitelist_migrations.py (EDITED), tests/active/test_whitelist_migrations.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam, clause 1: `sync-whitelist.py` loaded with `_load_job` (the precedent in `test_host_normalisation.py` and `test_repair_video_channel_names.py`); `ensure_content_schema` on a tmp target, a source attached as SOURCE_SCHEMA, then `rebuild_content_tables`, in `tests/active/test_ann_ids.py`. It runs once against a source that has `ann_id` and once against a six-column source, and asserts per-row `ann_id == compute_ann_id(key)` in each run, which excludes copying only (the six-column case would fail) and computing only (the copy path would be untested). `ensure_schema_compatibility` passes on the new target. Seam, clause 2: `merge-staging-db.py` run as a subprocess on a tmp prod and staging pair. It runs once with an old-shape stage and once with an old-shape main; each run exits non-zero, stderr contains `migrate-whitelist.py` and `--resume-staging` and names the right schema (`stage.` or `main.`), and prod's rows are unchanged. The doctored-staging collision through merge, the normal merge carrying `ann_id`, sync's old-target refusal and the updater test inject are inner units. `build-video-embeddings.py` is not entered because it loads the embedding model; its schema creation is P1's `ensure_video_embeddings_schema`.</checkpoint>\n<name>Writers store the derived id</name>\n<intent>The whitelist writer jobs put the derived ann_id on every embedding they write, and a merge into or from an unmigrated table stops with the migrate message instead of writing rows without one.</intent>\n<clause_1>`sync-whitelist`'s rebuild gives every copied embedding the ann_id of its key, both from a source that has `ann_id` and from one that lacks it.</clause_1>\n<clause_2>`merge-staging-db.py` refuses an old-shape `main` and an old-shape `stage` with a message naming `migrate-whitelist.py`.</clause_2>\n<files>engine/server/db/jobs/sync-whitelist.py (EDITED), engine/server/db/jobs/merge-staging-db.py (EDITED), engine/server/db/jobs/build-video-embeddings.py (EDITED), engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_ann_ids.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>Seam, clause 1: an ENGINE_PY child (the `_CHILD` precedent in `test_search.py` and `test_popular_videos.py`) in the new `tests/active/test_stale_ann_index.py`. It builds a tmp DB through `ensure_video_embeddings_schema` and an `IDMap2,IVF1,Flat` index on `ann_id`, and records `ann_id \u2192 (video_id, host)`. It then calls `ann.compute_similar_items` and `search.vector_candidates` through a stub server after each case: A, every row deleted and reinserted in reverse order; B, `purge_host_data` on one host; C, a new unindexed video inserted. Per case, every returned `(video_id, instance_domain)` equals the identity recorded for the id that produced it, which excludes a rowid join (case A would substitute); per case B, none of the purged host's videos is returned; per case C, the new video is absent. Each case is asserted for both readers. Seam, clause 2: the existing `tests/active/test_precompute_similar_ann.py` job harness (`INDEX_BUILDER` moved to `SELECT ann_id, embedding`, sidecar gains `id_source`). In the output, every source's neighbour keys map to the videos whose vectors carry the hit ids, which excludes rowid-keyed target lookup; no source lists itself.</checkpoint>\n<name>Readers and similarity precompute on ann_id</name>\n<intent>The Engine's similar, search and metadata reads and `precompute-similar-ann.py` resolve every ANN hit through `video_embeddings.ann_id`, so a stale index yields the video it indexed or nothing.</intent>\n<clause_1>After the table is renumbered and after a host purge, with no index rebuild, every hit from `compute_similar_items` and from `vector_candidates` resolves to the video whose vector carries that id, or is dropped.</clause_1>\n<clause_2>`precompute-similar-ann.py` resolves each neighbour by `ann_id` and never lists a video as its own neighbour.</clause_2>\n<files>engine/server/data/embeddings.py (EDITED), engine/server/data/ann.py (EDITED), engine/server/data/metadata.py (EDITED), engine/server/data/search.py (EDITED), engine/server/api/handlers/similar.py (EDITED), engine/server/db/jobs/precompute-similar-ann.py (EDITED), tests/active/test_stale_ann_index.py (NEW), tests/active/test_precompute_similar_ann.py (EDITED), tests/active/test_metadata.py (EDITED), tests/active/test_video.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"5\" kind=\"code\">\n<checkpoint>Seam: `precompute-random-rowids.py` run as a subprocess against a tmp source DB that has `ann_id`, using the existing `tests/active/test_precompute_random_rowids.py` harness. Clause 1 checks: the `--out` file holds a `random_ann_ids` table, and no `random_rowids` table, which excludes a half-renamed writer; every cached id is in the source's `ann_id` set, and the cached count equals `--size`, which excludes storing rowids (they are small integers outside the hashed set). Clause 2 checks: an `--out` already holding an old `random_rowids` table with `--size` rows is rebuilt; afterwards `random_ann_ids` exists with ids from the source set, which excludes the keep check counting the old table as usable. Engine-side `open_random_cache_if_usable` returning None on an old file goes through the same count helper and is covered in `test_random_cache.py`'s churned \"no table\" probe.</checkpoint>\n<name>Random cache on ann_id</name>\n<intent>The random-feed cache stores ANN ids in a `random_ann_ids` table, so a cache file in the old `random_rowids` format is never read as current and is rebuilt.</intent>\n<clause_1>`precompute-random-rowids.py` writes a `random_ann_ids` table whose every id is a `video_embeddings.ann_id` of the source.</clause_1>\n<clause_2>An output file that holds an old `random_rowids` table is rebuilt into `random_ann_ids` rather than kept.</clause_2>\n<files>engine/server/data/random_cache.py (EDITED), engine/server/data/random_videos.py (EDITED), engine/server/db/jobs/precompute-random-rowids.py (EDITED), engine/server/api/server_config.py (EDITED), tests/active/test_random_cache.py (EDITED), tests/active/test_random_videos.py (EDITED), tests/active/test_db.py (EDITED), tests/active/test_precompute_random_rowids.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"6\" kind=\"code\">\n<checkpoint>Seam: `build-ann-index.py` run as a job subprocess under ENGINE_PY (the precedent in `test_migrate_similarity_cache.py` and `test_precompute_similar_ann.py`) on a tmp DB built through `ensure_video_embeddings_schema`, then an ENGINE_PY child that loads the written index, in `tests/active/test_ann_ids.py`. Clause 1 checks: the index's stored id set (`faiss.vector_to_array(index.id_map)`) equals the DB's `ann_id` set exactly, which excludes rowid ids and dropped rows. Clause 2 checks: `assert_index_matches_embeddings` with the index and the sidecar the build actually wrote passes, which proves the build writes `id_source: video_embeddings.ann_id`; the same sidecar with `id_source: video_embeddings.rowid` raises a message naming `build-ann-index.py`; a sidecar with no `id_source` raises, which excludes a check that only compares when the key is present. The smoke-test `id_source` assertion runs against a migrated `--source-db` outside the gated suite (see needs_coordination).</checkpoint>\n<name>Index build and Engine gate</name>\n<intent>`build-ann-index.py` builds indexes keyed by `video_embeddings.ann_id`, and the Engine and the similarity precompute refuse any index whose sidecar does not declare that id source.</intent>\n<clause_1>The index `build-ann-index.py` writes holds exactly the `ann_id` values of the embedded rows as its ids.</clause_1>\n<clause_2>`assert_index_matches_embeddings` refuses a sidecar whose `id_source` is not `video_embeddings.ann_id`, with a message naming `build-ann-index.py`.</clause_2>\n<files>engine/server/db/jobs/build-ann-index.py (EDITED), engine/server/data/embedding_space.py (EDITED), engine/server/db/jobs/tests/test-orchestrator-smoke.py (EDITED), tests/active/test_ann_ids.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nThe operator approved doing all three of these steps personally.\n\n(a) Shared test dataset, before the final full-suite run. The session `engine` fixture and the Engine-backed `tests/active` cases read the shared `whitelist.db` and its index. Those cases stay red after P4 (readers query `e.ann_id`) and P6 (the gate refuses a sidecar without `id_source`) until the operator, with the Engine stopped, does three things:\n1. Runs `engine/server/db/jobs/migrate-whitelist.py` on that dataset. It needs about 1.4 GB free, plus the default backup.\n2. Runs `build-ann-index.py`.\n3. Starts the Engine again.\n\n(b) P6. The orchestrator smoke test's `id_source` assertion needs a migrated `--source-db`, and the operator runs it manually.\n\n(c) Before merge. The operator runs a read-only port check on the live DB: `SELECT COUNT(*) FROM video_embeddings WHERE instance_domain LIKE '%:%'`. It is expected to return 0.\n</needs_coordination>\n\n<rationale>\nThe build has 6 phases, over the 4-phase limit, and the operator approved this. A hard cutover cannot be split across separately merged plans. A plan that shipped only the DB side (P1-P3) would leave writers on ann_id while readers resolve rowids, and that merged state would return wrong videos. One plan with 6 internal phases keeps every merged state correct.\n\nEach phase is one seam with two clauses:\n1. The id and its schema guard.\n2. The migration.\n3. The writers.\n4. The readers and the similarity precompute, with the AC8 stale-index test.\n5. The random cache.\n6. The index build and the Engine gate.\n\nAny merge of two of these would have needed three or four clauses.\n\nThe readers (P4) come before the gate (P6). The precompute harness's fixture sidecar gains `id_source` in P4, before the gate needs it, so no earlier phase's checkpoint goes red when a later phase lands. Every checkpoint builds its own tmp fixtures. The only shared-data dependency is the cutover named in needs_coordination.\n\nSome behaviours a checkpoint cannot express in two clauses are written as inner units, by exception:\n- the CHECK refusing id 0;\n- the UPDATE refused by the UNIQUE index;\n- migration idempotence and the missing-table no-op;\n- the doctored-staging collision through merge;\n- sync's old-target refusal;\n- the updater test inject.\n\n`build-video-embeddings.py` is not entered by any checkpoint, because it loads the model. Its only changes are P1's schema helper and one extra tuple item.\n\nThere is no prose phase. The docs (DATA_BUILD, DEPLOYMENT, UPDATER_WORKER, ORCHESTRATOR_SMOKE_TEST, LAYER_PARAMS, OVERVIEW, the README) are for human readers and are updated at Step 9.\n</rationale>"
  },
  "requirements": "### Asked for\n\nIssue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2, plan `docs/project/plans/17-stable-ann-ids.md`). Today the FAISS index, and every reader that turns an id back into an embedded video, use `video_embeddings.rowid`. They switch to a deterministic `ann_id` derived from `(video_id, instance_domain)`. ADR-0006 (`docs/project/adr/0006-derived-ann-ids.md`) records the decision, and `CONTEXT.md` defines **ANN id**.\n\n### Purpose\n\nCorrectness. `video_embeddings` can change while no index rebuild follows, or while the rebuild fails: a merge, a host purge, a whole-table reload, a `--force` re-embed, a migration. In every such case the index must never return the wrong video. At most it misses videos it has not indexed yet. The build must not block later incremental index add or remove (F3/F4-M2), and it does not build them.\n\n### Current state (checked against the tree and the live DB, read-only)\n\n- `engine/server/db/jobs/build-ann-index.py:250-256` calls `add_with_ids` with `video_embeddings.rowid` and writes `id_source: \"video_embeddings.rowid\"` (line 284). The live sidecar `engine/server/db/whitelist-video-embeddings.faiss.json` says the same.\n- The live `engine/server/db/whitelist.db`:\n  - 890,052 `video_embeddings` rows, rowids exactly 1..890,052.\n  - Primary key `(video_id, instance_domain)`.\n  - 1,548 hosts, all already lowercase and trimmed.\n  - Every `video_id` is text.\n- Hash check: a 63-bit blake2b of `video_id::instance_domain` over all 890,052 keys gave 0 collisions, and no key hashed to 0.\n- Rowid-keyed readers:\n  - `engine/server/data/ann.py`:\n    - `compute_similar_items`, and its `ids > 0` filter.\n    - `search_index` (`exclude_rowid`).\n    - `search_similar_above`, the up-next fallback search. It keeps rowid hits through the same `ids > 0` filter, excludes `seed[\"rowid\"]` and calls `fetch_metadata` by rowid.\n    - The nprobe helpers `_extract_ivf`, `get_nprobe`, `apply_nprobe` and `set_nprobe` also live in this file, and `server.py` imports `set_nprobe` from it. `precompute-similar-ann.py` keeps its own copy of `set_nprobe`.\n  - `engine/server/data/embeddings.py`: the seed's `rowid`/`exclude_rowid` in `resolve_seed` and in the three seed queries.\n  - `engine/server/data/metadata.py`: `fetch_metadata`, which selects `WHERE e.rowid IN (...)`.\n  - `engine/server/data/search.py`: `vector_candidates`.\n  - `engine/server/api/handlers/similar.py`: `_handle_vector_search`.\n  - `engine/server/data/random_cache.py` and `engine/server/data/random_videos.py`: the `random_rowids` table.\n  - `engine/server/db/jobs/precompute-random-rowids.py`.\n  - `engine/server/db/jobs/precompute-similar-ann.py`: `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*` and the main loop.\n  - The rowid uses in `data/users.py` (likes) and `data/interaction_events.py` are about other tables, are not ANN ids, and do not change.\n- Writers that renumber rowids, or write `video_embeddings` at all:\n  - `build-video-embeddings.py`: `init_schema` uses `CREATE TABLE IF NOT EXISTS` (line 66). Under `--force` it runs DELETE (line 177), then `INSERT OR REPLACE` (line 272).\n  - `sync-whitelist.py`: `rebuild_content_tables` runs `DELETE FROM video_embeddings` (line 458), then `INSERT ... SELECT` from the attached crawl DB (lines 493-510). That copy runs only when the source's columns are a superset of `EMBEDDING_COLUMNS`. The same `EMBEDDING_COLUMNS` list also drives the exact check on the target schema in `ensure_schema_compatibility` (line 194), and the schema created at line 385 has no `ann_id`.\n  - `merge-staging-db.py`: `merge_rules.json` gives `video_embeddings` the `INSERT_OR_REPLACE` strategy, run as `INSERT OR REPLACE INTO main.t (common cols) SELECT ... FROM stage.t` over the columns prod and staging share (lines 152-171). The script also supports an `UPSERT` strategy.\n  - `updater-worker.inject_replace_embedding_for_test` (lines 1018-1064): a test-only `INSERT OR REPLACE` of one mutated embedding into staging, without `ann_id`.\n  - `whitelist_migrations.migrate_videos_schema` drops `video_embeddings` (line 268) and does not recreate it. The next schema creation does that.\n- Staging: the updater creates staging from `engine/crawler/schema.sql` (`init_staging_db`). That schema does not create `video_embeddings`, so `build-video-embeddings.init_schema` creates the staging table. `--resume-staging` reuses an existing staging DB, whose table may be in the old shape.\n- The updater (`updater-worker.py:1040-1150`) stops the service, merges, rebuilds the ANN, precomputes, and restarts in a `finally`. So a failed ANN build restarts the Engine on the old index against renumbered rows.\n- Random cache:\n  - The Engine never writes the random cache before listening. At start it opens `random-cache.db` read-only through `open_random_cache_if_usable` (`random_cache.py:283-302`). That accepts any non-empty `random_rowids` table without checking its shape.\n  - `server.py:345` sets `random_cache_startup_build = random_cache_refresh or random_cache_db is None`, so a cache judged unusable always gets a background build.\n  - Every build runs through `build_random_cache` (`random_cache.py:208-245`) into a per-pid temp file, which is swapped in through `swap_readonly_connection(..., RANDOM_CACHE_CHECK_SQL)`.\n  - With refresh off (`--dev`, `server.py:317-320`), a stored non-empty cache is served as it is.\n  - `precompute-random-rowids.py` keeps an `--out` that already holds `--size` rows, counted through `random_rowids_count` without checking their shape.\n  - `engine/server/api/recommendations/docs/LAYER_PARAMS.md` and `OVERVIEW.md` describe the cache as `random_rowids`.\n- Already on logical keys:\n  - The similarity cache (`similarity_items`) is keyed by `(video_id, instance_domain)` text and holds no rowids.\n  - `videos_fts` joins `videos.rowid` as FTS5 external content. That link is not an ANN id.\n- The Engine checks the index sidecar at start in `data/embedding_space.assert_index_matches_embeddings`, which today checks the model and the dimension.\n- Not checked: whether any deployed crawl DB that `sync-whitelist.py` reads already holds `video_embeddings` rows, with or without `ann_id`. The requirements cover all three cases.\n\n### Acceptance criteria\n\n- **AC1, the id:** one helper (for example `engine/server/data/ann_ids.py`) computes `ann_id` as blake2b with an 8-byte digest of `video_id + \"::\" + normalize_host(instance_domain)`, masked to 63 bits. `normalize_host` is the existing `data/moderation.normalize_host`. The result is positive, non-zero and safe as a signed int64. The same key gives the same id in any process and any DB. Every writer and reader uses this one helper. Jobs import it the way they already import `data.*`.\n- **AC2, the schema:** `video_embeddings` carries `ann_id INTEGER NOT NULL` with a UNIQUE index.\n  - A new `whitelist_migrations.migrate_video_embeddings_schema` rebuilds an existing table into that shape and fills the column from the helper through `sqlite3` `create_function`. It follows the existing `migrate_*_schema` table-rebuild pattern, and it is idempotent: it does nothing once the column exists. `migrate_whitelist_schema` calls it, so `migrate-whitelist.py` runs it.\n  - Every job that creates the table creates the same shape: `build-video-embeddings.init_schema` and the `sync-whitelist.py` schema. So does any table recreated after `migrate_videos_schema` drops it.\n  - **Collision guard:** a collision fails the write loudly on every write path, including `INSERT OR REPLACE` paths. A collision means a different `(video_id, instance_domain)` producing an `ann_id` already in use, or an id of 0. SQLite's `OR REPLACE` resolves conflicts on every UNIQUE index, so a plain UNIQUE index under `INSERT OR REPLACE` would silently delete the other video. That must not happen. The mechanism is a design choice: for example, writers use UPSERT on `(video_id, instance_domain)` and the `merge_rules.json` strategy for `video_embeddings` becomes `UPSERT`, or a BEFORE INSERT trigger raises. A write never probes for another id.\n  - **Old-shape tables:** writing into a `video_embeddings` table that lacks `ann_id` fails loudly with a message naming `engine/server/db/jobs/migrate-whitelist.py`, or, for a resumed staging DB, saying to recreate staging. Examples are an unmigrated prod DB, or a staging DB reused by `--resume-staging`. No writer ever produces rows without `ann_id`.\n- **AC3, the writers:** every writer stores the helper's `ann_id`.\n  - `build-video-embeddings.py` computes it per row.\n  - `merge-staging-db.py` preserves it from staging. The only change allowed there is the rule or strategy change the collision guard needs.\n  - `sync-whitelist.py` copies `ann_id` when the source has the column, and computes it through the registered function when the source has embeddings without it, so an older crawl DB does not force a re-embed. The target-schema check requires `ann_id`. The source-column check must not require it, or embeddings would be silently skipped.\n  - `updater-worker.inject_replace_embedding_for_test` writes `ann_id`.\n  - Re-running a writer, or replacing a row, leaves the video's `ann_id` unchanged.\n- **AC4, the index build:** `build-ann-index.py` adds vectors with `ann_id` as their ids and writes `id_source: \"video_embeddings.ann_id\"` to the sidecar. When the column is missing, it fails with a message naming `migrate-whitelist.py`.\n- **AC5, the Engine gate:** the Engine refuses to start when the index sidecar's `id_source` is not `video_embeddings.ann_id`. It refuses the same way it refuses a model mismatch today, in `assert_index_matches_embeddings`, with a message naming `build-ann-index.py`.\n- **AC6, the readers:** these resolve embedded videos by `ann_id`:\n  - similar: the seed and its exclusion (`ann_id`/`exclude_ann_id` in `embeddings.py`), the ANN results (`ann.py`, including `search_similar_above` and the `ids > 0` filter), and raw vector search (`similar._handle_vector_search`);\n  - search's vector half (`search.vector_candidates`);\n  - `fetch_metadata`, as `WHERE e.ann_id IN (...)`, served by the UNIQUE index;\n  - the random cache (`random_cache.py`, `random_videos.py`, `precompute-random-rowids.py`).\n\n  A stored random cache in the old `random_rowids` shape is detected and repopulated, never read. `open_random_cache_if_usable` treats it as unusable, so the Engine serves from the DB and runs a background build. The keep check in `precompute-random-rowids.py` treats an old-shape `--out` as not kept. Afterwards, no reader resolves an embedded video by rowid.\n- **AC7, the similarity precompute:** `precompute-similar-ann.py` uses `ann_id` for its FAISS ids and its target lookup. Its output keys (`similarity_items`, `(video_id, instance_domain)`) are unchanged, and its incremental selection stays keyed on `(video_id, instance_domain)`.\n- **AC8, the purpose observed in a test:** build an index, then, with no index rebuild, either renumber the DB's rows (delete and reinsert every row, as `sync-whitelist.py` does) or purge a host. Similar and search then return only videos whose identity matches the vector indexed for them. Unindexed or purged videos may be missing, but no result is a different video.\n- **AC9, the cycle and docs:** the updater's full cycle (merge \u2192 ANN build \u2192 precompute) runs on the new id source, observed through the orchestrator smoke test (`engine/server/db/jobs/tests/test-orchestrator-smoke.py`). These docs carry the one-time migrate-then-rebuild step for existing DBs: `DATA_BUILD.md`, `DEPLOYMENT.md` and the updater docs (`engine/server/db/jobs/docs/UPDATER_WORKER.md`). The step is `migrate-whitelist.py`, then `build-ann-index.py`, then start the Engine. `LAYER_PARAMS.md` and `OVERVIEW.md` (under `engine/server/api/recommendations/docs/`) describe the random cache's new `ann_id` shape.\n\n### Scope\n\nIn scope: AC1-AC9, including the random cache, as the operator decided. One build, correctness only.\n\nOut of scope:\n- incremental FAISS add or remove (F3/F4-M2);\n- rebuilding or re-keying the similarity cache;\n- `videos_fts`;\n- backward compatibility with rowid indexes (a `rowid` sidecar is refused, not read);\n- the crawler (`engine/crawler`, including `schema.sql`).\n\n### Consistency constraints\n\n- Job CLIs keep their current arguments.\n- Refusal messages follow `data/embedding_space.py`: say what is wrong, and name the command that fixes it.\n- The migration follows the existing `migrate_*_schema` table-rebuild pattern in `whitelist_migrations.py`.\n- Hosts go through the existing `data/moderation.normalize_host`.\n- New code matches the style of the file it lands in.\n- Design to the smallest thing that works: stdlib `hashlib.blake2b`, no new dependency, one helper module.\n\n### Tests\n\n- Active tests live in `tests/active`, scratch work goes in `tests/tmp`, and job tests live in `engine/server/db/jobs/tests/`.\n- Pre-build baseline: the suite exits with code 0 (`variant: false`).\n- Fixture churn: these tests insert into `video_embeddings` without `ann_id`, and NOT NULL breaks them, so they change with the build.\n  - 9 files in `tests/active`: `conftest.py`, `test_blocks.py`, `test_dislike_profile.py`, `test_dislikes.py`, `test_frontend_reactions.py`, `test_internal_client_reads.py`, `test_metadata.py`, `test_profiles.py`, `test_random_videos.py`.\n  - 2 job tests: `test-moderation-integration.py`, `test-orchestrator-smoke.py`.\n  - A shared fixture helper that computes `ann_id` keeps each file's change to its insert.\n- New tests cover:\n  - AC1: determinism, range, and a fixed known value;\n  - AC2: migration backfill, idempotence, the UNIQUE index, and the collision guard, including under `INSERT OR REPLACE` and on the merge path;\n  - AC3: each writer, including `sync-whitelist` from a source with `ann_id` and from one without;\n  - AC4/AC5: the sidecar's `id_source` and the Engine's refusal;\n  - AC6: the old-shape random cache rejected and rebuilt;\n  - AC8: the stale index after a renumber and after a host purge.\n\n### Risks and limitations accepted\n\n- The one-time migration rewrites about 1.4 GB of embedding blobs. It needs about that much free disk, and the Engine must be stopped while it runs.\n- Hard cutover: the Engine refuses a `rowid` sidecar, so the deploy order is migrate, then index build, then start. The similarity cache needs no rebuild.\n- A collision stops a dataset build or a merge loudly, and recovery is manual. The odds are about 4e-8 at 890k keys, and 0 collisions were measured.\n- Purged or deleted videos stay in the index until the next rebuild. They show up as misses (no metadata row), never as wrong videos.\n- A re-embedded video keeps its old vector in the index until the next rebuild, but it still resolves to the right video.\n- New videos stay out of the index until a rebuild.\n- A staging DB resumed from before the cutover fails loudly. It is not migrated.",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "5"
  ],
  "initial_solution": "### Approach\n\nOne new module, `engine/server/data/ann_ids.py`, holds everything the id needs, the same way `data/moderation.py` holds `normalize_host` and `ensure_moderation_schema`. It has four parts:\n- the pure function that computes the id from `(video_id, instance_domain)`;\n- a registration that exposes that function to SQLite under one SQL name, through `create_function`;\n- the one definition of the `video_embeddings` table: its columns, `CHECK (ann_id > 0)`, the UNIQUE index on `ann_id`, and the collision trigger;\n- an old-shape check that raises the AC2 message.\n\nEvery writer, reader, migration and test fixture imports from this module. Jobs reach it through the `data.*` import path they already use. `whitelist_migrations.py` reaches it through the server dir that `migrate-whitelist.py` already puts on `sys.path`.\n\n**AC1, the id.** blake2b with an 8-byte digest of `video_id + \"::\" + normalize_host(instance_domain)`, read big-endian and masked to 63 bits, using stdlib `hashlib`. The result is between 0 and 2^63-1 and fits a SQLite INTEGER, a numpy int64 and a FAISS id. The function only computes; it never probes. An id of 0 is stopped by the schema, not by the function.\n\n**AC2, the schema and the collision guard.** `video_embeddings` gains `ann_id INTEGER NOT NULL CHECK (ann_id > 0)` and a UNIQUE index. The guard is a BEFORE INSERT trigger. It raises ABORT when another row with a different `(video_id, instance_domain)` already holds `NEW.ann_id`.\n\nThe trigger works on every path because SQLite fires BEFORE triggers ahead of constraint resolution. The new row is checked before `OR REPLACE` can delete the other video's row. That covers `build-video-embeddings`, the merge's `INSERT OR REPLACE`, the bulk `INSERT ... SELECT` in sync, the updater's test inject and any hand-run SQL. The trigger uses plain SQL, so it works on any connection, including the sqlite3 CLI.\n\nA same-key replace (a re-embed, or a merge of an updated row) does not match the trigger: same key and same id, so the row is replaced and its `ann_id` is unchanged. An id of 0 fails the CHECK, which `OR REPLACE` does not override. A plain UPDATE that collides fails on the UNIQUE index, and no code path uses UPDATE OR REPLACE. `merge_rules.json` keeps `INSERT_OR_REPLACE`, because the guard needs no strategy change.\n\n**AC2, the migration.** `migrate_video_embeddings_schema` returns at once when the table is missing or already has `ann_id`. Otherwise it follows the `migrate_*_schema` rebuild pattern:\n1. Register the SQL function on the connection.\n2. Create `video_embeddings_new` from the shared definition, with the CHECK.\n3. Copy every row, filling `ann_id` from the function.\n4. Drop the old table and rename the new one.\n5. Create the UNIQUE index and the trigger, both IF NOT EXISTS.\n\nThe index and trigger come after the rename, so their names refer to the final table. A collision during the backfill then surfaces loudly when the UNIQUE index is built.\n\n`migrate_whitelist_schema` calls it last. If `migrate_videos_schema` has just dropped the table, it does nothing, and the next schema creation builds the new shape. `build-video-embeddings.init_schema` and `sync-whitelist.ensure_content_schema` both create the table from the shared definition, so every recreation, including the one after `migrate_videos_schema`, has the same shape.\n\n**AC2, old-shape tables.** The helper's check reads `PRAGMA table_info` and raises RuntimeError in the `embedding_space.py` style. It says the table has no `ann_id` column, and that prod needs `engine/server/db/jobs/migrate-whitelist.py` while a staging DB reused through `--resume-staging` must be recreated by running the updater without it. These callers use it:\n- `build-video-embeddings.py`, right after creating the schema;\n- `build-ann-index.py`, before sampling;\n- `merge-staging-db.py`, on both `main` and `stage` before the merge transaction. This is the one change the operator approved there.\n- `sync-whitelist.py`, through its existing exact target check, whose error already names `migrate-whitelist.py`.\n\n**AC3, the writers.**\n- `build-video-embeddings.py` computes the id per row in Python and adds it to the existing `INSERT OR REPLACE` tuple. Under `--force` the DELETE-then-insert gives every video back the same id.\n- `merge-staging-db.py` already copies the columns prod and staging share, so `ann_id` comes across from staging unchanged. Its only edit is the guard call above.\n- In `sync-whitelist.py`, `EMBEDDING_COLUMNS` splits in two. The target list includes `ann_id` and feeds the exact check. The source superset check keeps today's six columns, so an older crawl DB still qualifies. In `rebuild_content_tables`, when the source has `ann_id` it is copied; otherwise the select computes it through the registered function. Either way the trigger guards every row.\n- `updater-worker.inject_replace_embedding_for_test` computes the id through the helper and writes it, so the replacement keeps the prod row's id.\n\n**AC4, the index build.** `build-ann-index.py` selects `ann_id` in place of `rowid` for `add_with_ids` and writes `id_source: \"video_embeddings.ann_id\"`. The training sample still uses `rowid % step` to spread its rows across the table. That is a sampling cursor, not an identity, and no vector is ever looked up by it.\n\n**AC5, the Engine gate.** `assert_index_matches_embeddings` gains an `id_source` check next to the model check, with a message naming `build-ann-index.py`. The function also guards `precompute-similar-ann.py`, which is correct: a precompute against a rowid index would map hits to the wrong videos.\n\n**AC6, the readers.** The rowid names become `ann_id` throughout:\n- the seed's `rowid`/`exclude_rowid` and its three queries in `embeddings.py`;\n- the filters and exclusions in `ann.py`, including `search_similar_above`. The `> 0` filter stays valid: real ids are \u2265 1 and FAISS fills empty slots with -1.\n- `similar._handle_vector_search`;\n- `search.vector_candidates`;\n- `fetch_metadata`, which selects and filters on `e.ann_id` through the UNIQUE index.\n\n`search.py`'s own `v.rowid` is the `videos_fts` link and does not change. The nprobe helpers do not change.\n\n**AC6, the random cache.** The cache table becomes `random_ann_ids (position, ann_id)`. Because the new shape has a new table name, old-shape detection needs no new code. Against an old file, the existing count helper (renamed to match) returns None, so:\n- `open_random_cache_if_usable` logs `no_table` and returns None, the Engine serves from the DB, and `server.py:345` starts a background build;\n- the precompute job's keep check counts 0 and rebuilds;\n- `RANDOM_CACHE_CHECK_SQL` names the new table, so a swap can only install a new-shape file.\n\nThe build samples by `ann_id` instead of by rowid: a random start between min and max `ann_id`, then the next rows in `ann_id` order, wrapping around. Both the unfiltered and the filtered scans use this. Hashed ids are spread evenly, so this window is a uniform sample, not a block of rows in insertion order.\n\n`precompute-random-rowids.py` keeps its file name and arguments; only its help text changes.\n\n**AC7, the similarity precompute.** In `precompute-similar-ann.py`, `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*`, the pending-selection query and the main loop move to `ann_id`. The self-exclusion becomes `ann_id == row[\"ann_id\"]`. Output keys and incremental selection stay on `(video_id, instance_domain)`.\n\n**AC8, the purpose in a test.** A job test builds a small FAISS index on the new ids. With no index rebuild, it then either deletes and reinserts every row in a different order, or deletes one host's rows. It asserts that every similar and search hit resolves, through `fetch_metadata`, to the video whose vector carries that id, and that the purged host's videos are missing rather than replaced.\n\nThis holds by construction. The id is a function of identity, so after any rewrite of the table a stale id finds either the same video or nothing.\n\n**AC9, the cycle and docs.**\n- The orchestrator smoke test runs merge, ANN build and precompute on fixtures that carry `ann_id`, and asserts the sidecar's `id_source`.\n- `DATA_BUILD.md`, `DEPLOYMENT.md` and `UPDATER_WORKER.md` get the one-time step: stop the Engine, run `migrate-whitelist.py`, run `build-ann-index.py`, start the Engine.\n- `LAYER_PARAMS.md` and `OVERVIEW.md` describe `random_ann_ids`.\n\n**Tests.** A shared fixture helper in `tests/active` computes `ann_id`, so each of the 9 churned files changes only its insert. The 2 job tests import the helper directly.\n\nNo real collision can be produced, so the collision tests insert an explicit doctored `ann_id` that matches another key's id:\n- directly;\n- under `INSERT OR REPLACE`, asserting that the other video still exists;\n- through merge, from a doctored staging row.\n\nAC1 pins one fixed known value.\n\n### Alternatives considered\n\n- **UPSERT on `(video_id, instance_domain)` in every writer, with the merge rule switched to `UPSERT`, instead of a trigger.** Rejected: the guarantee would depend on every writer, present and future, getting its SQL right. The test inject, any hand-run `INSERT OR REPLACE` and the bulk sync would each be a hole. The trigger lives in the schema and holds for all of them. It also leaves merge's strategy alone.\n- **A CHECK that `ann_id` equals the registered function of the key.** It would also catch a wrong id, not just a duplicate. Rejected: every connection that writes, including the sqlite3 CLI and the Engine's test fixtures, would fail with \"no such function\".\n- **Keeping the `random_rowids` table name and checking its column shape.** Rejected for the new table name, which makes the existing \"no table\" path do the detection with no new code in `open_random_cache_if_usable` or in the keep check.\n- **Random-cache sampling by a rowid window while storing `ann_id`.** It would work, but it keeps a rowid read in the reader. The `ann_id` range is already indexed and gives a better spread.\n- **Always recomputing `ann_id` in sync instead of copying it from the source.** It would be safer against a foreign id, but AC3 settles on copying.\n- **For the old-shape merge failure:** extending the rule's `keys` (a generic message that doesn't name `migrate-whitelist.py`) or guarding only in the updater (a standalone merge into an unmigrated prod would still write rows without `ann_id`). The operator chose the direct guard call in `merge-staging-db.py`.\n- **Already rejected in ADR-0006 and not revisited:** a mapping table, a pinned rowid, an assigned counter, and probing for a free id.\n\n### Risks and gotchas\n\n- **Trigger order.** The guard relies on SQLite firing BEFORE INSERT triggers ahead of `OR REPLACE` conflict resolution. The `INSERT OR REPLACE` collision test pins this, so a SQLite behaviour change would show up as a red test.\n- **Per-row trigger cost.** Each insert does one lookup on the UNIQUE index. That is negligible for batched embedding writes and adds one indexed probe per row to the 890k-row sync reload.\n- **Migration rename.** The UNIQUE index and the trigger are created after the rename, so nothing depends on how ALTER TABLE RENAME rewrites trigger bodies. Backfill collisions surface when the UNIQUE index is built, and id 0 fails the CHECK.\n- **JSON precision.** Ids up to 2^63 exceed JavaScript's 2^53 safe range. I checked that `fetch_metadata`'s output dicts, the similar and search handlers and the random feed never put the id into a response. If one is ever exposed, it must be a string.\n- **Copied source ids.** `sync-whitelist` trusts a source `ann_id` it copies. The trigger catches duplicates, not a wrong id. In practice only the helper ever writes the column.\n- **Random feed change.** The unfiltered draw becomes a hash-uniform sample, not a block of rows in insertion order. Random-cache tests that assert row order or rowid windows will need new expectations.\n- **The test inject** needs `updater-worker.py` to reach `data.ann_ids`. If it does not already have the server dir on `sys.path`, it gets the same two-line insert the other jobs use.\n\n### Tradeoffs the operator accepts\n\n- **`merge-staging-db.py` changes by one guard call,** a few lines beyond AC3's limit. The operator approved this so that an unmigrated prod fails with AC2's message.\n- **Accepted in the requirements:**\n  - the one-time migration needs about 1.4 GB free and a stopped Engine;\n  - hard cutover: migrate, build the index, then start;\n  - a collision stops the run loudly and recovery is manual;\n  - stale indexes miss new videos and keep purged ones, as misses only;\n  - a resumed pre-cutover staging DB fails loudly instead of being migrated.\n- **The deliberate simplifications:**\n  - **The random cache is detected by its table name, not its shape.** The ceiling is that a future change to the shape under the same name would need a real column check. The upgrade path is to compare `PRAGMA table_info` in the count helper.\n  - **ANN training samples by `rowid % step`.** This only affects which vectors train the quantizer, never identity.",
  "conflicts": "AC3 (`merge-staging-db.py`: \"the only change allowed there is the rule or strategy change the collision guard needs\") collides with AC2 (writing into a `video_embeddings` table without `ann_id` fails loudly with a message naming `migrate-whitelist.py`). The merge copies only the columns prod and staging share, so an unmigrated prod would quietly receive rows without `ann_id`, and the chosen trigger guard needs no merge change. Asked through AskUser, the operator chose to allow a small guard call in `merge-staging-db.py`: the shared helper's column check on prod and staging before merging.",
  "impacts": "<impacts>\n<impact path=\"engine/server/data/ann_ids.py\" element=\"new module: id function, SQL registration, shared video_embeddings definition (CHECK, UNIQUE index, BEFORE INSERT collision trigger), old-shape check\">\nNew file, modelled on `data/moderation.py` (stdlib only, `from __future__ import annotations`, one-line docstrings).\n\nContents:\n- The pure id function.\n- A `register_*(conn)` wrapper over `conn.create_function(name, 2, fn, deterministic=True)`.\n- DDL constants or helpers for the table, the UNIQUE index and the trigger.\n- The old-shape check, which raises RuntimeError.\n\nDependencies:\n- It imports `normalize_host` from `data.moderation`. That module imports `data.similarity_cache`, which is also stdlib only (os, sqlite3, struct, pathlib), so importing `data.ann_ids` stays safe under the system interpreter that several tests and jobs use (`sys.executable` in `test_precompute_random_rowids.py`). If you add numpy or faiss here, those runs break.\n- Every writer, reader-side fixture, migration and job imports it.\n\nPoints the implementer must settle:\n1. **`normalize_host` can return None** (empty, whitespace or unparsable input). It also **strips ports**. The crawler's `normalize_host_token` keeps `host:port` for bare entries, so `instance_domain` can legitimately hold a port. Two videos with the same `video_id` on `h:8080` and `h:9090` would then hash the same key and collide loudly. The function must define what it hashes when the result is None: raise, or fall back to the raw lowercased domain.\n2. **The old-shape check needs a `schema` argument** (`PRAGMA {schema}.table_info(video_embeddings)`). `merge-staging-db.py` must check `main` and `stage` on one connection.\n3. **The DDL must be split.** `CREATE TABLE IF NOT EXISTS` is a no-op on an old table, but `CREATE UNIQUE INDEX ... ON video_embeddings(ann_id)` and `CREATE TRIGGER ... NEW.ann_id` fail with `no such column: ann_id`. Index and trigger creation must come after, or be guarded by, the old-shape check, or every caller gets a raw sqlite error instead of AC2's message.\n4. **Index and trigger names must not collide** with `idx_video_embeddings_id_instance`, which `data/videos.ensure_video_indexes` drops at every Engine start.\n5. **The trigger must use plain SQL** (no registered function) so that the sqlite3 CLI and the Engine's connections can still insert. Inside a trigger on `main`, unqualified table names resolve to `main`, which is correct for merge's attached `stage`.\n\nRegression risk: medium. A change to `normalize_host` silently changes every id, so the AC1 fixed-value test is the only thing that catches it.\n</impact>\n<impact path=\"engine/server/data/moderation.py\" element=\"normalize_host (dependency, no edit expected); purge_host_data / _host_table_column_pairs\">\n**`normalize_host`** becomes part of the id contract. Any future edit to it (port handling, IDNA, trimming) re-keys every `ann_id` and silently desynchronises the DB from the stored index and random cache. No code change is planned. Consider a comment at `normalize_host` pointing at `data/ann_ids.py`, or rely on the AC1 pinned-value test.\n\n**`purge_host_data`** deletes `video_embeddings` rows by host. The new BEFORE INSERT trigger does not fire on DELETE, so purges are unaffected. This is the AC8 \"purge one host\" path. Afterwards a stale index returns misses, not wrong videos, through `fetch_metadata`'s `ann_id` lookup.\n\nCallers:\n- `updater-worker.purge_hosts` and `purge_hosts_from_staging`\n- `instance-denylist-cli.py --purge-now`\n- the moderation integration test\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/db/jobs/whitelist_migrations.py\" element=\"new migrate_video_embeddings_schema(conn); migrate_whitelist_schema calls it last\">\nNew function, following the `migrate_*_schema` rebuild pattern:\n1. Return at once if the table is missing or already has `ann_id`.\n2. Register the SQL function.\n3. Create `video_embeddings_new` from the shared DDL.\n4. `INSERT ... SELECT` with `ann_id` filled by the function.\n5. DROP the old table and RENAME the new one.\n6. Create the UNIQUE index and the trigger, IF NOT EXISTS.\n\n`migrate_whitelist_schema` appends the call after `migrate_videos_language`. When `migrate_videos_schema` has just dropped `video_embeddings`, the new step does nothing.\n\nImport: module-level `from data.ann_ids import ...` requires `engine/server` on `sys.path`.\n- `migrate-whitelist.py` inserts `server_dir`.\n- `tests/active/test_whitelist_migrations.py` loads this file with `importlib` after loading `sync-whitelist.py`, which inserts `server_dir`. It works only by that side effect, so make the test, or the module, insert the path explicitly.\n\nRisks:\n- **Atomicity.** The existing pattern uses `executescript`, which COMMITs first and runs each statement in autocommit, so `with conn:` in `migrate-whitelist.py` gives no atomicity. If the UNIQUE index build fails on a backfill collision after the DROP and RENAME, the DB is left with `ann_id` but **no UNIQUE index and no trigger**. A re-run then takes the early return because `ann_id` exists, and the guard is never installed. Either run the whole rebuild in one explicit `BEGIN ... COMMIT`, or make the early-return path still `CREATE ... IF NOT EXISTS` the index and trigger.\n- **Size.** About 890k rows rewritten (around 1.4 GB). The Engine must be stopped.\n- **FK.** The table declares an FK to `videos`, but `migrate-whitelist`'s connection does not enable `foreign_keys`, so DROP and RENAME are unaffected.\n\nRegression risk: high.\n</impact>\n<impact path=\"engine/server/db/jobs/migrate-whitelist.py\" element=\"main(); backup_db\">\nNo logic change is needed beyond the new step running through `migrate_whitelist_schema`. `server_dir` is already on `sys.path` for `data.ann_ids`.\n\nOperational impact:\n- **Free space.** `backup_db` (the default) copies the whole `whitelist.db`, about 3.5 GB according to DATA_BUILD's VACUUM note, before the 1.4 GB rebuild. The \"about 1.4 GB free\" in the accepted tradeoffs understates this unless `--no-backup` is used.\n- **No longer additive.** The migration now rewrites a large table, so it must run with the Engine stopped.\n- **Help text.** The description, \"Migrate whitelist.db schema in-place\", stays accurate.\n\nRisk: low in code, medium operationally.\n</impact>\n<impact path=\"engine/server/db/jobs/build-video-embeddings.py\" element=\"init_schema(); main() insert tuple and INSERT OR REPLACE; --force path\">\nChanges:\n- `init_schema` creates the table from the shared definition, then calls the old-shape check. The index and trigger must be created only after that check passes (see `ann_ids` point 3), because `CREATE TABLE IF NOT EXISTS` is a no-op on an old staging or whitelist table.\n- The per-row tuple gains the id, computed in Python, and the INSERT column list gains `ann_id`.\n- New import: `from data.ann_ids import ...`. `server_dir` is already on `sys.path`.\n\nCallers:\n- `updater-worker` on staging (fresh from `crawler/schema.sql`, which has no `video_embeddings`, so the table is created in the new shape; a `--resume-staging` old staging fails with the AC2 message)\n- `run-dataset-build.sh` (`--force` on `whitelist.db`)\n- operators on `whitelist.db`\n\n`--force` does DELETE then reinsert, so every key gets back the same id. The trigger raises on a doctored collision. The IntegrityError aborts that batch; earlier batches are already committed (per-batch commit), which is acceptable as a loud stop.\n\n`scripts/run-reembed.sh` parses the `--model-name` default through the AST; it must remain an `add_argument` with a Constant default.\n\nRisk: medium.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"EMBEDDING_COLUMNS split; ensure_content_schema video_embeddings DDL; ensure_schema_compatibility; rebuild_content_tables embeddings copy\">\nChanges:\n- `EMBEDDING_COLUMNS` becomes two lists:\n  - the target list, with `ann_id`, for `_assert_columns_exact(conn, \"video_embeddings\", ...)`;\n  - the source superset, today's six columns.\n- `ensure_content_schema` replaces its inline `video_embeddings` DDL with the shared definition.\n- `rebuild_content_tables` reads the source `table_info`. If the source has `ann_id`, it copies it; otherwise it selects `<fn>(video_id, instance_domain)`, which needs the function registered on this connection before the INSERT. The trigger fires per row (around 890k indexed probes) inside the single `with conn:` transaction, so a collision rolls back the whole sync.\n\n**Ordering hazard.** `main()` calls `ensure_content_schema(conn)` **before** `ensure_schema_compatibility(conn)`. If the shared DDL creates the UNIQUE index or trigger unconditionally, an unmigrated `whitelist.db` fails with `no such column: ann_id` from the index DDL instead of the exact check's \"missing columns: ann_id ... Run migrate-whitelist.py\". Keep index and trigger creation conditional, or move the check first.\n\nOther consumers of `ensure_content_schema` and of the module:\n- `tests/active/test_video.py`, `test_whitelist_migrations.py`, `test_repair_video_channel_names.py` and `test_host_normalisation.py` (module load)\n- `repair-video-channel-names.py`, which loads this module for its FTS helpers\n\n`_load_schema_columns` and `videos_fts` are unaffected.\n\nRisk: high.\n</impact>\n<impact path=\"engine/server/db/jobs/merge-staging-db.py\" element=\"main(): old-shape guard on main and stage before BEGIN IMMEDIATE\">\nChange: one guard call per schema (`main`, `stage`) after ATTACH and before the transaction (approved). Needs `from data.ann_ids import ...`; `server_dir` is already inserted.\n\nThe rule loop is unchanged:\n- `merge_columns` includes `ann_id` once both sides have it.\n- `INSERT OR REPLACE INTO main.video_embeddings (... ann_id ...) SELECT ... FROM stage` hits the trigger per row. A same-key replace keeps the id; a doctored foreign id ABORTs, and the existing `except` rolls back.\n- The connection needs no registered function.\n\nWithout the guard, an old-shape `stage` would drop `ann_id` from `merge_columns` and fail NOT NULL with a generic error. An old-shape `main` would let rows through with no `ann_id`.\n\nCaller: `updater-worker` step \"merge\"; the smoke test exercises it.\n\nRisk: low to medium.\n</impact>\n<impact path=\"engine/server/db/jobs/merge_rules.json\" element=\"video_embeddings rule\">\nNo change: `INSERT_OR_REPLACE` with keys `video_id`, `instance_domain` stays. Listed because the plan relies on it staying unchanged. `test-orchestrator-smoke.validate_outputs` reads the rules and checks replace and mismatch behaviour per strategy.\n\nRisk: none.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"inject_replace_embedding_for_test; (no-change) count_staging_deltas, seed_staging_from_prod, init_staging_db, --resume-staging flow\">\n**`inject_replace_embedding_for_test`** must:\n- select `ann_id` from `prod.video_embeddings`, or compute it through the helper;\n- add `ann_id` to the `INSERT OR REPLACE` into staging.\n\nWithout that, NOT NULL fails on a new-shape staging. `server_dir` is already on `sys.path` (lines 24-27), so the \"two-line insert\" contingency in the plan is not needed. Its docstring may need wording.\n\nNo change:\n- `init_staging_db` (crawler `schema.sql` has no `video_embeddings`)\n- `seed_staging_from_prod` (instances and channels only)\n- `count_staging_deltas` (key-based)\n- `purge_hosts*`\n\nWith `--resume-staging`, a pre-cutover staging now fails loudly in `build-video-embeddings` (accepted).\n\n`tests/active/test_updater_worker.py` AST-scans this file for `build-ann-index.py` and `run_with_cpu_fallback` inside the `try`. A new import does not affect that.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/db/jobs/build-ann-index.py\" element=\"EmbeddingRow, iter_embeddings, fetch_training_samples, add loop query, meta id_source, old-shape guard\">\nChanges:\n- Old-shape guard before sampling, naming `migrate-whitelist.py` (AC4). It needs `from data.ann_ids import ...`; `server_dir` is already inserted.\n- The add query becomes `SELECT ann_id, embedding, embedding_dim`, and `EmbeddingRow.rowid` becomes `ann_id`. The `np.int64` cast fits the 63-bit ids.\n- `meta[\"id_source\"] = \"video_embeddings.ann_id\"`.\n- `fetch_training_samples` keeps `rowid % step` (sampling only).\n\nConsumers of the sidecar:\n- `assert_index_matches_embeddings` (Engine and precompute)\n- `test-orchestrator-smoke.validate_outputs`\n- `scripts/run-reembed.sh`, which logs it\n\nRisk: medium. A missed `rowid` here produces an index the AC5 gate accepts (by sidecar) but with wrong ids.\n</impact>\n<impact path=\"engine/server/data/embedding_space.py\" element=\"assert_index_matches_embeddings; module docstring\">\nAdd a check: `meta.get(\"id_source\") != \"video_embeddings.ann_id\"` raises RuntimeError with a message naming `build-ann-index.py`, next to the model check.\n\nCallers:\n- `api/server.py:365` (Engine start)\n- `precompute-similar-ann.py:345`\n\nEvery existing sidecar (`id_source: \"video_embeddings.rowid\"`) and every test sidecar without `id_source` is now refused:\n- `tests/active/test_precompute_similar_ann.py` writes `{\"model_name\", \"embedding_dim\"}` only and will fail until it adds `id_source`.\n- `test_video.py` builds its index in-process and never calls the gate.\n\nUpdate the docstring to mention the id contract.\n\nRisk: medium. It hard-stops every Engine whose DB and index were not cut over, including the dev or test dataset.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"startup: open_random_cache_if_usable, resolve_embedding_space, assert_index_matches_embeddings\">\nNo edit is expected.\n\nBehaviour changes through the callees:\n- **Random cache.** Against an old `random-cache.db`, `open_random_cache_if_usable` returns None (`no_table`). `random_cache_startup_build` becomes true (line 345), so a background build runs and the feed is served from the DB until it swaps in.\n- **Index gate.** `assert_index_matches_embeddings` now refuses a rowid index, so the Engine exits at start until the index is rebuilt.\n\nThe Engine has no `video_embeddings` old-shape check of its own. An Engine on an unmigrated DB with a new index is impossible in practice, because the index build requires `ann_id`.\n\nRisk: low in code, high in cutover ordering.\n</impact>\n<impact path=\"engine/server/data/embeddings.py\" element=\"resolve_seed (exclude_rowid/rowid keys), _fetch_seed_by_uuid, _fetch_seed_by_id, fetch_seed_embeddings_for_likes (e.rowid AS rowid \u00d72), _seed_from_row\">\n**Change.** Four `e.rowid AS rowid` selects become `e.ann_id`, and the seed keys `rowid` and `exclude_rowid` become `ann_id` and `exclude_ann_id`. That covers `resolve_seed`'s three return shapes and `_seed_from_row`.\n\n**Consumers of the seed keys:**\n- `ann.compute_similar_items` (`seed[\"rowid\"]`, a hard KeyError if only one side is renamed)\n- `ann.search_similar_above` (`seed.get(\"rowid\")`, which would silently stop self-exclusion)\n- `similar._handle_vector_search` (`seed[\"exclude_rowid\"]`)\n- recommendations sources that pass `fetch_seed_embeddings_for_likes` seeds into `get_similar_candidates` \u2192 `compute_similar_items` (`api/recommendations/sources/ann_similar_from_likes.py` and `cached_similar_from_likes.py`)\n\n**Other dependents:**\n- `handlers/internal_client_reads.handle_internal_video_resolve` calls `fetch_seed_embedding`, so its SQL now needs `e.ann_id`. The response does not expose the id.\n- `fetch_embeddings_by_ids` is unchanged.\n\n**Risk: medium.** A partial rename silently breaks self-exclusion; there is no error.\n</impact>\n<impact path=\"engine/server/data/ann.py\" element=\"compute_similar_items, search_similar_above, search_index (exclude_rowid param)\">\nRename the variables and keys to `ann_id`:\n- `seed[\"rowid\"]` becomes `seed[\"ann_id\"]`.\n- `search_index`'s `exclude_rowid` parameter becomes `exclude_ann_id`.\n\nThe `> 0` filters stay valid. `search_index` drops only `< 0`, which also stays valid because the CHECK forbids 0.\n\nCallers:\n- `similar._handle_vector_search`\n- `search.vector_candidates`\n- `similarity_candidates.get_upnext_candidates` \u2192 `search_similar_above`\n- `_compute_candidates` \u2192 `compute_similar_items`\n- the archived `tests/archive/short_similarity_cache/test_similar.py` (not run)\n\n`tests/active/test_similarity_candidates.py` stubs `search_similar_above` with the same signature, so a keyword rename of its parameters would not break the stub, which is positional. The nprobe helpers do not change.\n\nRisk: low to medium.\n</impact>\n<impact path=\"engine/server/data/metadata.py\" element=\"fetch_metadata\">\n`SELECT e.ann_id AS ann_id ... WHERE e.ann_id IN (...)`, keyed by `int(row[\"ann_id\"])`. This uses the UNIQUE index; today the lookup goes by the rowid primary key, so performance is comparable. The parameter name and docstring move from `rowids` to `ann_ids`. Output dicts do not include the id, which keeps it out of JSON (the 2^53 precision issue).\n\nCallers:\n- `ann.compute_similar_items` and `ann.search_similar_above`\n- `search.vector_candidates`\n- `similar._handle_vector_search`\n- `random_videos.fetch_random_rows_from_cache`\n- `tests/active/test_metadata.py` (`_nsfw_metadata` passes `SELECT rowid` ids against a fixture table without `ann_id`, so it must change)\n\n`fetch_metadata_by_ids`, `fetch_metadata_by_uuids` and `_select_metadata` are unchanged.\n\nRisk: medium. Every fixture DB lacking `ann_id` now raises `no such column: e.ann_id` on these paths.\n</impact>\n<impact path=\"engine/server/data/search.py\" element=\"vector_candidates\">\n`rowids` from `search_index` become `ann_ids`, passed to `fetch_metadata`. `VIDEO_ROW_SQL`'s `v.rowid AS rowid` (the `videos_fts` link) and `lexical_candidates` are unchanged.\n\n`tests/active/test_search.py` runs with `query_encoder=None`, so the vector half returns before `fetch_metadata`. Its fixture table (no `ann_id`) should need no change. This is unverified beyond reading the test's server stub.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._handle_vector_search\">\n`seed[\"exclude_rowid\"]` becomes `seed[\"exclude_ann_id\"]`, and local variables are renamed. Rows are `{**meta, \"score\"}`, and `meta` from `fetch_metadata` carries no id, so nothing reaches the JSON response. `_handle_seed_with_embedding` and `_fetch_random_rows` need no edit; they flow through `get_upnext_candidates` and `random_videos`.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/data/random_cache.py\" element=\"RANDOM_CACHE_CHECK_SQL, ensure_random_cache_schema, random_rowids_count (rename), populate_random_cache (both scans), fetch_random_rowids (rename), docstrings\">\n**Rename and reshape:**\n- The table `random_rowids(position, video_rowid)` becomes `random_ann_ids(position, ann_id)`.\n- `RANDOM_CACHE_CHECK_SQL` names the new table, and the count helper is renamed.\n\n**Build:**\n- The unfiltered build reads `MIN(ann_id)`/`MAX(ann_id)`. It runs `random.randint` over a 63-bit range (Python ints are fine), then `WHERE ann_id >= ? ORDER BY ann_id LIMIT ?` with wrap-around.\n- `scan_range` advances `current = last ann_id + 1`.\n- Both rely on the UNIQUE index for range scans. The source connection is read-only and needs no registered function.\n\n**Old files:** a file with only `random_rowids` reads as None (`no_table`) in `open_random_cache_if_usable` and in the precompute keep check.\n\n**Dependents:**\n- `random_videos.py` imports `fetch_random_rowids` by name, and tests monkeypatch `random_videos.fetch_random_rowids`. All names must move together.\n- `precompute-random-rowids.py` imports `random_rowids_count`.\n- `tests/active/test_db.py`, `test_random_cache.py`, `test_random_videos.py` and `test_precompute_random_rowids.py` create `random_rowids` directly and assert positions over \"rowids 1..20\". With hash ids those expectations become sets of computed ids, and windows are no longer insertion-ordered.\n\nThe `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` rat-tail comment is unaffected.\n\nRisk: medium, from test churn and the rename.\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"import of fetch_random_rowids; fetch_random_rows_from_cache\">\nFollows the rename. `seen` and `fresh` hold `ann_id`s, passed to `fetch_metadata`. `RANDOM_CACHE_NSFW_MAX_DRAWS` logic is unchanged. Update the docstring (\"precomputed rowid cache\").\n\n`fetch_random_rows`, `fetch_recent_videos`, `fetch_popular_videos` and `fetch_ordered_page` do not touch ids.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-random-rowids.py\" element=\"import random_rowids_count; keep check; argparse description and --size help\">\nChanges:\n- The keep check uses the renamed count helper. An old-shape `--out` counts 0, so it is rebuilt.\n- The description \"Precompute random rowid cache.\" and the help \"Rowids to sample.\" change.\n- The file name and arguments stay.\n\nCallers:\n- `scripts/run-dataset-build.sh:262`\n- `tests/active/test_precompute_random_rowids.py` (its fixture source needs `ann_id`, and it asserts sorted ids `== range(1, 21)`)\n- `tests/config.json` maps that test to this file\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"comment above DEFAULT_RANDOM_CACHE_SIZE (line 352)\">\nThe comment \"Precomputed random rowids stored for fast random feed responses.\" should say ANN ids. Comment only.\n\nRisk: none.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"iter_embedding_rows_by_rowids, fetch_similarity_targets, fetch_similarity_targets_chunked, pending selection queries (SELECT e.rowid \u00d72), full-mode SELECT, main loop self-exclusion\">\n**Change.** Every `rowid` select and filter becomes `ann_id`: the helper names, the dict keys, `pending_rowids`, `batch_rowids` and `targets_by_rowid`. The self-exclusion becomes `ann_id_int == row[\"ann_id\"]`, and the full-mode select gains `ann_id`. Output keys (`video_id`, `instance_domain`) and the incremental and refresh-existing join on `video_keys` stay. The source connection is read-only (`mode=ro`), so no function registration is possible or needed.\n\n**AC5 dependency.** The AC5 gate (`assert_index_matches_embeddings`) runs first. It refuses a rowid index before any `ann_id` SELECT can fail on an old DB.\n\n**Callers:**\n- `updater-worker.run_similarity_stage`\n- `run-dataset-build.sh`\n- `tests/active/test_precompute_similar_ann.py`, which must change: its fixture table and explicit-rowid inserts, the `INDEX_BUILDER` that adds by rowid, and its sidecar without `id_source`.\n\n**Risk: medium.** The neighbours are wrong and nothing fails if one id site is missed.\n</impact>\n<impact path=\"engine/server/db/jobs/inspect-embedding.py\" element=\"main()\">\nIt reads only `embedding`, `embedding_dim`, `model_name`, `video_id` and `instance_domain`. No change.\n\nRisk: none.\n</impact>\n<impact path=\"engine/server/db/jobs/instance-denylist-cli.py\" element=\"--purge-now (via purge_host_data)\">\nNo change. This is one of the three coupling breaks the issue names. After the change, a purge without an index rebuild yields misses only, which AC8 covers.\n\nRisk: none.\n</impact>\n<impact path=\"engine/server/data/videos.py\" element=\"ensure_video_indexes\">\nNo change. It drops only `idx_video_embeddings_id_instance`, so the new UNIQUE index's name must differ (see `ann_ids`). It runs at every Engine start against `whitelist.db`.\n\n`tests/active/test_videos.py` builds its own table and is unaffected.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/data/similarity_candidates.py\" element=\"get_upnext_candidates / _compute_candidates (callers of ann functions)\">\nNo code change is expected. It passes seeds through to `search_similar_above` and `compute_similar_items`, which read the renamed seed key. `_build_rows` uses `fetch_metadata_by_ids` (key-based) and is unaffected.\n\nRisk: low, contingent on the seed-key rename being complete.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"handle_internal_video_resolve (via fetch_seed_embedding)\">\nNo edit. Its SQL now selects `e.ann_id` through `fetch_seed_embedding`, so a DB without the column fails this route. The response exposes only `video_id`, `uuid`, `host`, `channel` and `title`, never the id.\n\n`tests/active/test_internal_client_reads.py` exercises only the metadata and centroids handlers, so its fixture without `ann_id` should keep passing. The plan's \"Conflicts\" list names it among the churned files, which looks over-inclusive.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/api/recommendations/sources/ann_similar_from_likes.py\" element=\"seed_map from fetch_seed_embeddings_for_likes \u2192 get_similar_candidates\">\nNo edit. The seeds it builds carry the renamed key into `compute_similar_items`. Listed so the rename is verified end to end. `cached_similar_from_likes.py` follows the same flow.\n\nRisk: low.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-orchestrator-smoke.py\" element=\"copy_and_prune_prod / create_table_and_indexes_from_source; validate_outputs\">\nChanges:\n- **Add an `id_source == \"video_embeddings.ann_id\"` assertion** in `validate_outputs` next to the `meta_total` check (AC9).\n- **Copy the triggers.** `create_table_and_indexes_from_source` copies only `type='table'` and `type='index'` DDL from the source, so **the collision trigger is not copied** into mini-prod. The smoke merge would then run without the guard. Extend it to copy `type='trigger'` for `tbl_name`, or build `video_embeddings` from the shared definition.\n\nDependencies:\n- `INSERT INTO video_embeddings SELECT e.*` relies on identical column order, which holds when the DDL is copied.\n- `--source-db` defaults to `DEFAULT_DB_PATH` (`whitelist.db`), which must already be migrated. Otherwise mini-prod is old-shape and the merge guard stops the run (arguably correct, but it fails the smoke test).\n- `--inject-replace-embedding-for-test` depends on the updater inject computing `ann_id`.\n- The replace and mismatch checks compare all columns, `ann_id` included, which is equal for same-key replaces.\n\nRisk: medium.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-moderation-integration.py\" element=\"synthetic schema and the two INSERT OR REPLACE INTO video_embeddings seeds\">\nIts own `CREATE TABLE IF NOT EXISTS video_embeddings` has no `ann_id`, and it never runs `fetch_metadata`, ANN or the merge. It exercises purge and serving moderation only, so as written it should keep passing without change.\n\nThe plan lists it as churned. Change it only if the fixture is switched to the shared definition, or if the prod-sample mode copies from a migrated DB into this narrower table (it uses explicit column lists, so that is fine).\n\nUncertain: I did not trace every prod-sample path past line 790.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"new shared ann_id fixture helper; engine fixture; embedding_of\">\nThe plan puts a shared helper here that computes `ann_id` for fixture inserts. It must put `engine/server` on `sys.path` to import `data.ann_ids`; conftest currently inserts only `client/backend`.\n\nThe existing `embedding_of`, `closeness` and `identity_of` only SELECT from `whitelist.db` and need no change.\n\n**The session `engine` fixture starts the real Engine on the repo's `whitelist.db` and `whitelist-video-embeddings.faiss`.** After AC5 it exits at start until that dataset is migrated and the index rebuilt. That fails every Engine-backed active test, including:\n- `test_similar`, `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles`, `test_frontend_reactions` and the `test_random_cache` Engine cases.\n\nThis worktree has no `engine/server/db/whitelist.db` (only `random-cache.db`), so these tests read a shared dataset. DATA_BUILD says shared DB migrations run on main after merge only, so pre-merge validation of the Engine-backed suite is constrained.\n\nRisk: high, for the test environment.\n</impact>\n<impact path=\"tests/active/test_metadata.py\" element=\"nsfw_conn fixture table/insert; _nsfw_metadata (SELECT rowid \u2192 fetch_metadata)\">\nThe fixture table needs an `ann_id` column, with inserts through the shared helper. `_nsfw_metadata` must pass `ann_id`s. The other tests in the file use `fetch_metadata_by_ids` and are unaffected.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_random_videos.py\" element=\"NSFW_EMBEDDINGS_TABLE, nsfw_conn, _video_db (lastrowid map), _cache_owner (random_rowids table, fetch_random_rowids monkeypatch), docstring\">\n**Changes:**\n- `_video_db` maps labels to `lastrowid`, and the cache stores those ids. Both must become `ann_id` from the helper.\n- The fixture table needs the column.\n- `_cache_owner` creates `random_rowids` and monkeypatches `random_videos.fetch_random_rowids` and `random_cache.fetch_random_rowids`. These must follow the renames.\n- The docstring mentions \"unseen rowid\".\n\n**No change:**\n- `_feed_db` copies `src.video_embeddings` from the real `whitelist.db` with CTAS (no constraints).\n- The T2 copy then duplicates T's `ann_id`, which is harmless because no ordered-feed read uses `ann_id`. If the fixture ever adopts the shared definition, the copy would hit UNIQUE and the trigger.\n\n**Risk:** medium churn.\n</impact>\n<impact path=\"tests/active/test_random_cache.py\" element=\"_source_db, _seed_cache/_cache_rows/_cache_rowids (random_rowids), _served_rowids, _seed_servable_cache and _feed_rowids (SELECT rowid from whitelist.db), docstring assertions about 'source rowids 1..20'\">\n**Fixtures:**\n- `_source_db` needs `ann_id` populated.\n- Every direct `random_rowids` DDL, insert and read moves to `random_ann_ids(position, ann_id)`.\n\n**Assertions:**\n- \"positions 1..20 over source rowids 1..20\" and the order-dependent expectations become the set of the 20 computed ids.\n- The window under hash order differs from insertion order (stated in the plan's risks).\n\n**Engine cases:** they map feed rows back through `SELECT rowid FROM video_embeddings` on the real `whitelist.db`, which must become `ann_id`. They also need the migrated dataset and index (see conftest).\n\n**Cache-file probe:** the \"file without random_rowids\" `open_random_cache_if_usable` case should use an old-shape `random_rowids` file. It then also pins AC6's old-shape detection.\n\n**Risk:** high churn.\n</impact>\n<impact path=\"tests/active/test_db.py\" element=\"_source_db, _seed_cache, CHECK_SQL, fetch_random_rowids import, SEEDED_ROWIDS\">\nThe swap tests build a random cache from a source with no `ann_id` (needs the column and values). They seed `random_rowids` and use `CHECK_SQL` on `random_rowids`; all of that follows the rename. The import `from data.random_cache import build_random_cache, fetch_random_rowids` breaks on rename.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_precompute_random_rowids.py\" element=\"_source_db, _seed_cache, _cache_rows, assertions sorted(...)==range(1,21)\">\nChanges:\n- The source needs `ann_id`.\n- The seeded old-format cache should use the new table, plus one case with the old `random_rowids` shape to pin \"old shape is rebuilt, not kept\".\n- Assertions compare against the computed ids.\n\nThe job runs under `sys.executable`, so `data.ann_ids` must stay stdlib only.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_precompute_similar_ann.py\" element=\"source fixture (CREATE TABLE, explicit rowid inserts), INDEX_BUILDER (add_with_ids by rowid), sidecar JSON, _source_db\">\nChanges:\n- The fixture needs `ann_id` (helper-computed) and an index built on `ann_id`.\n- The sidecar must add `\"id_source\": \"video_embeddings.ann_id\"`, or the AC5 gate refuses every run.\n- `SHORT_ROWID` and the `v{rowid}` naming can stay as labels, but the ids are no longer 1..9.\n- `_source_db` (the refusal tests) runs before any read and needs no change.\n\nRisk: medium, because every test in the file fails until the sidecar is updated.\n</impact>\n<impact path=\"tests/active/test_video.py\" element=\"similars_stack (SELECT rowid \u2192 add_with_ids); embedded-video inserts at lines 543-544\">\nThe DB comes from `sync-whitelist.ensure_content_schema`, so it takes the new shape. The positional `INSERT INTO video_embeddings VALUES (6 values)` then breaks, both on column count and on NOT NULL `ann_id`. `similars_stack` must add the index with `ann_id`. The similars case asserts `seed v1 \u2192 [\"v2\"]`, which keeps working once ids match.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_whitelist_migrations.py\" element=\"_load_job of whitelist_migrations.py; new migration test\">\nThis is the natural place for:\n- the AC2 migration tests: backfill values, the UNIQUE index and trigger present, idempotence, and the early return when the table is missing;\n- an old-shape fixture.\n\nThe existing test passes, because `ensure_content_schema` creates the new-shape table and the migration no-ops. The module import of `data.ann_ids` relies on `sync-whitelist.py` having been loaded first; see `whitelist_migrations`.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_similarity_candidates.py\" element=\"video_embeddings fixture; data.ann stub\">\nExpected unaffected. Its `data.ann` stub replaces `search_similar_above` positionally, and `_build_rows` uses key-based metadata. Re-check if the `search_similar_above` signature changes order.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_search.py\" element=\"video_embeddings fixture\">\nExpected unaffected (`query_encoder=None`, so `fetch_metadata` is never reached). Listed because `tests/config.json` maps it to `metadata.py`, so a metadata change selects it.\n\nRisk: low.\n</impact>\n<impact path=\"tests/active/test_blocks.py\" element=\"dataset SELECT joining video_embeddings\">\nRead-only queries against the live `whitelist.db`; no fixture insert. The plan's \"Conflicts\" names it, but it should need no change beyond the dataset being migrated. `test_dislikes.py`, `test_dislike_profile.py`, `test_profiles.py` and `test_frontend_reactions.py` are the same: SELECT only, and Engine-backed.\n\nRisk: low in code, high in environment (see conftest).\n</impact>\n<impact path=\"tests/config.json\" element=\"test \u2192 source file map\">\nAdd `engine/server/data/ann_ids.py` to the tests that exercise it: `test_metadata`, `test_random_cache`, `test_random_videos`, `test_precompute_*`, `test_whitelist_migrations`, `test_video` and the new AC8 test. Add `embedding_space.py` where the gate matters. If the build adds a new job test file for AC8, add its entry.\n\nRisk: low. A missed mapping only weakens change-based selection.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"recorded test ids\">\nA generated artifact that lists test ids such as `test_precompute_random_rowids::...`. It is regenerated by the test run and should not be hand-edited. Renamed or added tests show up there.\n\nRisk: none.\n</impact>\n<impact path=\"scripts/run-dataset-build.sh\" element=\"sync, embeddings, index, random cache stages\">\nNo code change is required:\n- `precompute-random-rowids.py` keeps its name.\n- The `--force` re-embed keeps ids.\n- The index stage writes the new `id_source`.\n\nAn existing unmigrated `whitelist.db` now fails at the sync stage on the exact check, or at `--from index` on the AC4 guard. DATA_BUILD already says this script does not migrate. Optionally add a migrate step or a log hint.\n\nRisk: low.\n</impact>\n<impact path=\"scripts/run-reembed.sh\" element=\"comment line 28; sidecar log\">\nThe comment \"api/server.py compares the index sidecar's model_name\" could also mention `id_source`. Optional.\n\nRisk: none.\n</impact>\n<impact path=\"tests/archive/random_cache_in_place/test_random_cache.py\" element=\"archived tests using random_rowids\">\nArchived and not run. Leave unchanged; they reference `random_rowids` and rowids. `tests/archive/37_local_signal/test_random_videos.py` and `tests/archive/short_similarity_cache/test_similar.py` are the same.\n\nRisk: none.\n</impact>\n<impact path=\"docs/project/plans/17-stable-ann-ids.md\" element=\"Impacts / Implementation / Close sections; Conflicts list of churned tests\">\nThe build fills this plan file. Its \"Conflicts\" list of 9 churned `tests/active` files does not match the code:\n- **Actually needing change:** `test_metadata`, `test_random_videos`, `test_random_cache`, `test_db`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_video` (and `conftest` for the new helper).\n- **SELECT-only, no fixture insert:** `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles`, `test_frontend_reactions`.\n- **Unaffected:** `test_internal_client_reads`, which tests only routes that don't read `ann_id`.\n\nCorrect the list when filling Impacts.\n</impact>\n</impacts>",
  "docs_checklist": "- [ ] `DATA_BUILD.md` - - **Line 13:** \"random rowid cache\" becomes the random ANN-id cache.\n- **Line 155:** say that embeddings are copied with their `ann_id`, or that `ann_id` is computed when the crawl DB lacks it.\n- **Line 159:** the exact check now includes `ann_id`.\n- **Lines 161-172:** \"The migration is additive ... without touching rows ... second run does nothing\" is no longer true for `video_embeddings`. Add the one-time cutover:\n  1. Stop the Engine.\n  2. Run `migrate-whitelist.py`, a table rebuild that needs about 1.4 GB free plus the default full-file backup.\n  3. Run `build-ann-index.py`.\n  4. Start the Engine.\n\n  Also note that a stored `random-cache.db` is rebuilt automatically.\n- **Line 191:** the \"schedule with the stable-ANN-ids cutover\" note can now point at the cutover steps.\n- **Line 232:** \"The index uses `video_embeddings.rowid` as ids\" becomes `video_embeddings.ann_id`; mention `id_source` and the AC4 refusal message.\n- **Line 290:** \"random rowid pool\" changes.\n- **Line 335:** `select count(*) from random_rowids` becomes `random_ann_ids`.\n- [ ] `DEPLOYMENT.md` - - **Line 42:** add the one-time ANN-id cutover (stop, migrate, build index, start) and that the Engine refuses to start on an index whose sidecar `id_source` is not `video_embeddings.ann_id`.\n- **Triage table:** add a row for that startup refusal, with the fix `build-ann-index.py`. Add one for the `migrate-whitelist.py` message from `build-ann-index`, merge and `build-video-embeddings`.\n- **Line 421:** random-cache text is unaffected beyond a first start rebuilding an old-shape cache.\n- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - - **Cutover:** the prerequisite one-time migrate and index rebuild before the first updater run on new code.\n- **`--resume-staging` (lines 48, 149, 186):** a pre-cutover staging DB now fails with the AC2 message and must be recreated by running without the flag.\n- **Line 61:** the ANN rebuild writes `id_source: video_embeddings.ann_id`.\n- **Merge:** it refuses an unmigrated prod or staging.\n- **Line 197:** `--inject-replace-embedding-for-test` keeps the row's `ann_id`.\n- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - - **Validations list (around line 115):** add the sidecar `id_source` assertion.\n- **Source DB:** note that it must be migrated, since mini-prod copies its schema.\n- [ ] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - - **Line 130:** \"has no `random_rowids` table\" becomes `random_ann_ids`. An old-format file counts as having no table.\n- **Line 140:** \"The cache holds only rowids (`random_rowids`)\" becomes ANN ids (`random_ann_ids`), resolved to rows by `ann_id`. Mention the hash-uniform sampling window.\n- [ ] `engine/server/api/recommendations/docs/OVERVIEW.md` - - **Line 15:** \"drops rowids already seen\" / \"unseen rowid\" becomes ANN ids.\n- **Line 69:** \"Holds a prebuilt list of rowids\" becomes ANN ids (`random_ann_ids`).\n- [ ] `engine/server/README.md` - Line 9 explains the `migrate-whitelist.py` requirement for `videos.language`. Optionally add that the Engine also refuses to start until the ANN-id cutover (migrate plus index rebuild) has run, pointing at DATA_BUILD.\n- [ ] `docs/project/issues/08-stable-ann-ids.md` - At close: set `Status: enhancement, complete` and move to `docs/project/issues/archive/`, per the triage labels.",
  "docs": [
    {
      "path": "DATA_BUILD.md",
      "note": "- **Line 13:** \"random rowid cache\" becomes the random ANN-id cache.\n- **Line 155:** say that embeddings are copied with their `ann_id`, or that `ann_id` is computed when the crawl DB lacks it.\n- **Line 159:** the exact check now includes `ann_id`.\n- **Lines 161-172:** \"The migration is additive ... without touching rows ... second run does nothing\" is no longer true for `video_embeddings`. Add the one-time cutover:\n  1. Stop the Engine.\n  2. Run `migrate-whitelist.py`, a table rebuild that needs about 1.4 GB free plus the default full-file backup.\n  3. Run `build-ann-index.py`.\n  4. Start the Engine.\n\n  Also note that a stored `random-cache.db` is rebuilt automatically.\n- **Line 191:** the \"schedule with the stable-ANN-ids cutover\" note can now point at the cutover steps.\n- **Line 232:** \"The index uses `video_embeddings.rowid` as ids\" becomes `video_embeddings.ann_id`; mention `id_source` and the AC4 refusal message.\n- **Line 290:** \"random rowid pool\" changes.\n- **Line 335:** `select count(*) from random_rowids` becomes `random_ann_ids`."
    },
    {
      "path": "DEPLOYMENT.md",
      "note": "- **Line 42:** add the one-time ANN-id cutover (stop, migrate, build index, start) and that the Engine refuses to start on an index whose sidecar `id_source` is not `video_embeddings.ann_id`.\n- **Triage table:** add a row for that startup refusal, with the fix `build-ann-index.py`. Add one for the `migrate-whitelist.py` message from `build-ann-index`, merge and `build-video-embeddings`.\n- **Line 421:** random-cache text is unaffected beyond a first start rebuilding an old-shape cache."
    },
    {
      "path": "engine/server/db/jobs/docs/UPDATER_WORKER.md",
      "note": "- **Cutover:** the prerequisite one-time migrate and index rebuild before the first updater run on new code.\n- **`--resume-staging` (lines 48, 149, 186):** a pre-cutover staging DB now fails with the AC2 message and must be recreated by running without the flag.\n- **Line 61:** the ANN rebuild writes `id_source: video_embeddings.ann_id`.\n- **Merge:** it refuses an unmigrated prod or staging.\n- **Line 197:** `--inject-replace-embedding-for-test` keeps the row's `ann_id`."
    },
    {
      "path": "engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md",
      "note": "- **Validations list (around line 115):** add the sidecar `id_source` assertion.\n- **Source DB:** note that it must be migrated, since mini-prod copies its schema."
    },
    {
      "path": "engine/server/api/recommendations/docs/LAYER_PARAMS.md",
      "note": "- **Line 130:** \"has no `random_rowids` table\" becomes `random_ann_ids`. An old-format file counts as having no table.\n- **Line 140:** \"The cache holds only rowids (`random_rowids`)\" becomes ANN ids (`random_ann_ids`), resolved to rows by `ann_id`. Mention the hash-uniform sampling window."
    },
    {
      "path": "engine/server/api/recommendations/docs/OVERVIEW.md",
      "note": "- **Line 15:** \"drops rowids already seen\" / \"unseen rowid\" becomes ANN ids.\n- **Line 69:** \"Holds a prebuilt list of rowids\" becomes ANN ids (`random_ann_ids`)."
    },
    {
      "path": "engine/server/README.md",
      "note": "Line 9 explains the `migrate-whitelist.py` requirement for `videos.language`. Optionally add that the Engine also refuses to start until the ANN-id cutover (migrate plus index rebuild) has run, pointing at DATA_BUILD."
    },
    {
      "path": "docs/project/issues/08-stable-ann-ids.md",
      "note": "At close: set `Status: enhancement, complete` and move to `docs/project/issues/archive/`, per the triage labels."
    }
  ],
  "reassessments": 2,
  "draft": "## Draft implementation: stable ANN ids (issue 08, plan 17)\n\nEvery file in the impact inventory was read before drafting: `moderation.py`, `whitelist_migrations.py`, `embedding_space.py`, `random_cache.py`, `random_videos.py`, `metadata.py`, `embeddings.py`, `ann.py`, `search.py`, `similar.py`, `build-video-embeddings.py`, `build-ann-index.py`, `merge-staging-db.py`, `sync-whitelist.py`, `updater-worker.py`, both precompute jobs, the smoke test and the churned `tests/active` fixtures. The new code is shown in full; existing files get exact edits.\n\n### What the build has to test\n\n- **AC1, the id function:** same input gives the same output; the result is between 1 and 2^63-1; one pinned value; host normalisation (`\"Host.Example.\"` and `\"host.example\"` give the same id).\n- **AC2, the schema:**\n  - the new table shape;\n  - the CHECK refuses an id of 0;\n  - a doctored id is refused by the trigger on a plain INSERT, on `INSERT OR REPLACE` (the other row must survive) and on merge;\n  - a same-key replace keeps the id;\n  - the migration fills `ann_id`, is idempotent, does nothing when the table is missing, and leaves an unchanged old-shape table when it fails;\n  - the old-shape refusal message, for `main` and for `stage`.\n- **AC3, the writers:** build-video-embeddings (including `--force`), sync from a source with `ann_id` and from one without, merge, and the test inject.\n- **AC4/AC5, the index:** the sidecar's `id_source`, and the Engine refusing a rowid sidecar.\n- **AC6, the readers:** the renamed seed keys, ANN and metadata reads by `ann_id`, and an old-shape random cache treated as unusable and rebuilt.\n- **AC7:** the similarity precompute on `ann_id`.\n- **AC8:** a stale index after the table is renumbered and after a host purge.\n- **AC9:** the orchestrator smoke test checks `id_source`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/ann_ids.py` | **new**: id function, SQL registration, table definition, guards, old-shape check, `ANN_ID_SOURCE` |\n| `engine/server/data/moderation.py` | one comment line above `normalize_host` |\n| `engine/server/db/jobs/whitelist_migrations.py` | `sys.path` insert, `migrate_video_embeddings_schema`, called last |\n| `engine/server/db/jobs/build-video-embeddings.py` | `init_schema` uses the helper; the insert tuple and column list gain `ann_id` |\n| `engine/server/db/jobs/sync-whitelist.py` | `TARGET_EMBEDDING_COLUMNS`; table from the helper; guards created only when the column exists; copy or compute `ann_id` |\n| `engine/server/db/jobs/merge-staging-db.py` | old-shape check on `main` and `stage` before `BEGIN IMMEDIATE` |\n| `engine/server/db/jobs/updater-worker.py` | the test inject writes `ann_id` |\n| `engine/server/db/jobs/build-ann-index.py` | old-shape check; `ann_id` ids; `id_source` |\n| `engine/server/data/embedding_space.py` | `id_source` check and docstring |\n| `engine/server/data/embeddings.py`, `ann.py`, `metadata.py`, `search.py`, `api/handlers/similar.py` | rowid \u2192 `ann_id` rename |\n| `engine/server/data/random_cache.py`, `random_videos.py`, `db/jobs/precompute-random-rowids.py`, `api/server_config.py` (comment) | `random_ann_ids` cache |\n| `engine/server/db/jobs/precompute-similar-ann.py` | rowid \u2192 `ann_id` rename |\n| `engine/server/db/jobs/tests/test-orchestrator-smoke.py` | guards in mini-prod; `id_source` assertion |\n| `tests/active/*`, `tests/config.json` | fixtures, new tests, map entries |\n\nNo change: `merge_rules.json` (stays `INSERT_OR_REPLACE`), `migrate-whitelist.py`, `server.py`, `similarity_candidates.py`, the recommendation sources, `inspect-embedding.py`, `instance-denylist-cli.py`, `videos.py`, `test-moderation-integration.py` (its own narrow table, which never reaches `ann_id` readers, per the impact), and the archived tests.\n\n---\n\n### 1. `engine/server/data/ann_ids.py` (new)\n\n```python\n\"\"\"Derive, store and guard the ANN id of an embedded video (ADR-0006).\"\"\"\n\nfrom __future__ import annotations\n\nimport hashlib\nimport sqlite3\n\nfrom data.moderation import normalize_host\n\n# The sidecar id_source every index must carry; the Engine refuses any other.\nANN_ID_SOURCE = \"video_embeddings.ann_id\"\n# SQL name of compute_ann_id once register_ann_id_function has run on a connection.\nANN_ID_SQL_FUNCTION = \"ann_id_of\"\nANN_ID_MASK = (1 << 63) - 1\n\nANN_ID_INDEX_SQL = \"CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)\"\n# Plain SQL so every connection (Engine, sqlite3 CLI) can insert; BEFORE triggers run ahead of OR REPLACE conflict resolution, so a foreign id aborts instead of deleting the row that holds it.\nANN_ID_TRIGGER_SQL = \"\"\"\nCREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision\nBEFORE INSERT ON video_embeddings\nWHEN EXISTS (\n  SELECT 1 FROM video_embeddings\n  WHERE ann_id = NEW.ann_id\n    AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)\n)\nBEGIN\n  SELECT RAISE(ABORT, 'video_embeddings ann_id collision: another (video_id, instance_domain) already holds this ann_id; see docs/project/adr/0006-derived-ann-ids.md');\nEND\n\"\"\"\n\n\ndef compute_ann_id(video_id: str, instance_domain: str) -> int:\n    \"\"\"Return the 63-bit blake2b ANN id of video_id::normalize_host(instance_domain); 0 is left to the table's CHECK.\"\"\"\n    # A domain normalize_host rejects hashes as its trimmed lowercase text, so every key still has one deterministic id.\n    host = normalize_host(instance_domain) or str(instance_domain).strip().lower()\n    digest = hashlib.blake2b(f\"{video_id}::{host}\".encode(\"utf-8\"), digest_size=8).digest()\n    return int.from_bytes(digest, \"big\") & ANN_ID_MASK\n\n\ndef register_ann_id_function(conn: sqlite3.Connection) -> None:\n    \"\"\"Expose compute_ann_id to SQL on this connection as ann_id_of(video_id, instance_domain).\"\"\"\n    conn.create_function(ANN_ID_SQL_FUNCTION, 2, compute_ann_id, deterministic=True)\n\n\ndef create_video_embeddings_table(conn: sqlite3.Connection, table: str = \"video_embeddings\") -> None:\n    \"\"\"Create the video_embeddings table (or a rebuild's `table`) if missing; a no-op on an existing table of any shape.\"\"\"\n    conn.execute(\n        f\"\"\"\n        CREATE TABLE IF NOT EXISTS {table} (\n          video_id TEXT NOT NULL,\n          instance_domain TEXT NOT NULL,\n          embedding BLOB NOT NULL,\n          embedding_dim INTEGER NOT NULL,\n          model_name TEXT NOT NULL,\n          created_at TEXT NOT NULL,\n          ann_id INTEGER NOT NULL CHECK (ann_id > 0),\n          PRIMARY KEY (video_id, instance_domain),\n          FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)\n        )\n        \"\"\"\n    )\n\n\ndef create_ann_id_guards(conn: sqlite3.Connection) -> None:\n    \"\"\"Create the UNIQUE ann_id index and the collision trigger; the table must already have ann_id.\"\"\"\n    conn.execute(ANN_ID_INDEX_SQL)\n    conn.execute(ANN_ID_TRIGGER_SQL)\n\n\ndef assert_video_embeddings_has_ann_id(conn: sqlite3.Connection, schema: str = \"main\") -> None:\n    \"\"\"Raise if {schema}.video_embeddings exists without ann_id; a missing table is left to the caller.\"\"\"\n    columns = [row[1] for row in conn.execute(f\"PRAGMA {schema}.table_info(video_embeddings)\")]\n    if columns and \"ann_id\" not in columns:\n        raise RuntimeError(\n            f\"{schema}.video_embeddings has no ann_id column. \"\n            \"Run `engine/server/db/jobs/migrate-whitelist.py` to migrate the whitelist DB; \"\n            \"a staging DB reused with --resume-staging must be recreated by running the updater without --resume-staging.\"\n        )\n\n\ndef ensure_video_embeddings_schema(conn: sqlite3.Connection) -> None:\n    \"\"\"Create video_embeddings and its guards, refusing an old-shape table with the migrate message.\"\"\"\n    create_video_embeddings_table(conn)\n    assert_video_embeddings_has_ann_id(conn)\n    create_ann_id_guards(conn)\n```\n\n**Invariants and decisions**\n\n- **Stdlib only.** The module imports `hashlib` and `sqlite3`, plus `data.moderation`, which itself only imports `data.similarity_cache`. Jobs and tests that run under `sys.executable` (such as `test_precompute_random_rowids`) can still import it.\n- **When `normalize_host` returns None** (impact point 1): the id falls back to the trimmed, lowercased domain and never raises. A raise inside the registered SQL function would abort a whole sync over one odd host. `normalize_host` never returns text containing whitespace, and it returns every live host unchanged, because they are all already lowercase and trimmed.\n- **Ports** (impact point 1): `normalize_host` strips them, as AC1 requires. So `(v, h:8080)` and `(v, h:9090)` share an id, and the trigger stops that write loudly, which falls under the accepted \"collision stops loudly\". The live 0-collision measurement hashed the raw domain, so **check before merge, read-only:** `SELECT COUNT(*) FROM video_embeddings WHERE instance_domain LIKE '%:%'` on the live DB. If it returns 0, ports cannot cause a collision today.\n- **The DDL is split** (impact point 3). The table is created first. The guards are created only by callers that have confirmed `ann_id` exists (`ensure_video_embeddings_schema`, the sync column check, the migration), so an old-shape table always gets the AC2 message and never a raw `no such column: ann_id`.\n- **Names** (impact point 4): `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision` do not clash with `idx_video_embeddings_id_instance`, which `ensure_video_indexes` drops at every Engine start.\n- **Single statements.** Every DDL goes through `conn.execute`, never `executescript`, so creating the table and guards inside sync's `with conn:` does not commit early.\n- **Collisions.** An id of 0 fails the CHECK, which `OR REPLACE` cannot override. A colliding UPDATE fails on the UNIQUE index. A same-key replace matches no other row, so it passes the trigger and keeps the same id.\n\n### 2. `engine/server/data/moderation.py`\n\nAdd one line above `def normalize_host`:\n\n```python\n# Part of the ANN id contract (data/ann_ids.py): any change here re-keys every video_embeddings.ann_id, stored index and random cache.\n```\n\n### 3. `engine/server/db/jobs/whitelist_migrations.py`\n\nHeader. The `sys.path` insert means the module no longer relies on `sync-whitelist.py` having been loaded first (as `test_whitelist_migrations.py` currently does):\n\n```python\nimport sqlite3\nimport sys\nfrom pathlib import Path\n\nserver_dir = Path(__file__).resolve().parents[2]\nif str(server_dir) not in sys.path:\n    sys.path.insert(0, str(server_dir))\n\nfrom data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function\n```\n\nNew function, placed before `migrate_whitelist_schema`:\n\n```python\ndef migrate_video_embeddings_schema(conn: sqlite3.Connection) -> None:\n    \"\"\"Rebuild video_embeddings with the derived ann_id column, its UNIQUE index and its collision trigger (ADR-0006).\n\n    The rebuild runs in one explicit transaction. A backfill collision or a zero id fails the UNIQUE index or the CHECK and rolls back to the old shape, so a re-run retries the whole rebuild instead of skipping a table left without its guards. Idempotent: a table that already has ann_id, or no table at all, is left alone.\n    \"\"\"\n    if not _table_exists(conn, \"video_embeddings\"):\n        return\n    if \"ann_id\" in _columns(conn, \"video_embeddings\"):\n        return\n    register_ann_id_function(conn)\n    # Close whatever the earlier steps left open, as their executescript calls do.\n    conn.commit()\n    conn.execute(\"BEGIN\")\n    try:\n        conn.execute(\"DROP TABLE IF EXISTS video_embeddings_new\")\n        create_video_embeddings_table(conn, \"video_embeddings_new\")\n        conn.execute(\n            f\"\"\"\n            INSERT INTO video_embeddings_new (\n              video_id,\n              instance_domain,\n              embedding,\n              embedding_dim,\n              model_name,\n              created_at,\n              ann_id\n            )\n            SELECT\n              video_id,\n              instance_domain,\n              embedding,\n              embedding_dim,\n              model_name,\n              created_at,\n              {ANN_ID_SQL_FUNCTION}(video_id, instance_domain)\n            FROM video_embeddings\n            \"\"\"\n        )\n        conn.execute(\"DROP TABLE video_embeddings\")\n        conn.execute(\"ALTER TABLE video_embeddings_new RENAME TO video_embeddings\")\n        # Created after the rename so their SQL names the final table.\n        create_ann_id_guards(conn)\n    except BaseException:\n        conn.rollback()\n        raise\n    conn.commit()\n```\n\n`migrate_whitelist_schema` gains a last line, `migrate_video_embeddings_schema(conn)`, after `migrate_videos_language`. When `migrate_videos_schema` has just dropped the table, the new step returns early.\n\n**Departure from the pattern, named.** The existing steps use `executescript`, which commits before it runs and then runs in autocommit. This step uses an explicit `BEGIN`/`COMMIT` instead, because of the atomicity risk the impact inventory names. Its shape (`_new` table, copy, drop, rename) is the existing pattern. The `with conn:` in `migrate-whitelist.py` stays harmless: nothing is left open for it to commit. The FK on `videos` does not affect the DROP or the RENAME, because `migrate-whitelist`'s connection does not enable `foreign_keys`.\n\n### 4. `engine/server/db/jobs/build-video-embeddings.py`\n\n- Import, after `CompactHelpFormatter`: `from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema`.\n- `init_schema` becomes:\n\n```python\ndef init_schema(conn: sqlite3.Connection) -> None:\n    \"\"\"Create video_embeddings in its ann_id shape, refusing an old-shape table.\"\"\"\n    ensure_video_embeddings_schema(conn)\n    conn.commit()\n```\n\n- The tuple in the batch loop gains `compute_ann_id(video_id, instance_domain)` as its last item. The insert becomes:\n\n```python\n            INSERT OR REPLACE INTO video_embeddings\n              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)\n            VALUES (?, ?, ?, ?, ?, ?, ?)\n```\n\n- `--force` (DELETE, then reinsert) gives every key back its old id. `--model-name` stays an `add_argument` with a constant default, which `run-reembed.sh` depends on.\n- An old-shape staging DB (`--resume-staging`) or `whitelist.db` stops in `init_schema` with the AC2 message, before the model loads.\n\n### 5. `engine/server/db/jobs/sync-whitelist.py`\n\n- Import: `from data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function`.\n- `EMBEDDING_COLUMNS` keeps its six names; it is now the source superset and the copied columns. Add, following the `WHITELIST_DERIVED_VIDEO_COLUMNS` precedent:\n\n```python\n# Derived in the whitelist DB from (video_id, instance_domain) (data/ann_ids.py). An older crawl DB lacks it, so it belongs in the exact check against `main.video_embeddings` but not in the source superset check.\nTARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + [\"ann_id\"]\n```\n\n- `ensure_schema_compatibility`: `_assert_columns_exact(conn, \"video_embeddings\", TARGET_EMBEDDING_COLUMNS)`. An unmigrated DB gets \"missing columns: ann_id ... Run `engine/server/db/jobs/migrate-whitelist.py`\".\n- `ensure_content_schema`: remove the inline `video_embeddings` DDL from the `executescript`. After it, and before `create_videos_fts_triggers(conn)`, add:\n\n```python\n    create_video_embeddings_table(conn)\n    # An old-shape table is left for ensure_schema_compatibility to refuse with the migrate message; creating guards on it would fail on the missing column first.\n    if \"ann_id\" in _table_columns(conn, \"video_embeddings\"):\n        create_ann_id_guards(conn)\n```\n\nThis resolves the ordering hazard without moving the check that `main()` runs afterwards. `repair-video-channel-names.py` and the tests that call `ensure_content_schema` on new DBs get the new shape with guards.\n\n- `rebuild_content_tables` embedding copy:\n\n```python\n    if source_embedding_columns.issuperset(EMBEDDING_COLUMNS):\n        embedding_columns = \", \".join(EMBEDDING_COLUMNS)\n        # A crawl DB that predates ann_id gets it derived here, so its embeddings are kept rather than re-embedded; the trigger guards every row either way.\n        register_ann_id_function(conn)\n        ann_id_expr = \"ann_id\" if \"ann_id\" in source_embedding_columns else f\"{ANN_ID_SQL_FUNCTION}(video_id, instance_domain)\"\n        conn.execute(\n            f\"\"\"\n            INSERT INTO video_embeddings ({embedding_columns}, ann_id)\n            SELECT {embedding_columns}, {ann_id_expr}\n            FROM {SOURCE_SCHEMA}.video_embeddings\n            WHERE (video_id, instance_domain) IN (\n              SELECT video_id, instance_domain FROM videos\n            );\n            \"\"\"\n        )\n```\n\n  A collision raises inside the `with conn:` in `main()`, so the whole sync rolls back. Each row costs one probe of the UNIQUE index (around 890k).\n\n### 6. `engine/server/db/jobs/merge-staging-db.py`\n\n- Import: `from data.ann_ids import assert_video_embeddings_has_ann_id`.\n- In `main()`, the first lines inside `try:`, before `conn.execute(\"BEGIN IMMEDIATE\")`:\n\n```python\n        # An old-shape stage would drop ann_id from merge_columns, and an old-shape main would take rows without one: refuse both with the migrate message.\n        assert_video_embeddings_has_ann_id(conn, \"main\")\n        assert_video_embeddings_has_ann_id(conn, \"stage\")\n```\n\n- They sit inside `try` so the existing `finally` still detaches and closes. The existing `except` calls `rollback()`, which does nothing when no transaction is open.\n- The rule loop is unchanged. `merge_columns` now includes `ann_id`, and `INSERT OR REPLACE INTO main.video_embeddings` fires `main`'s trigger on each row. Inside a trigger on `main`, the unqualified `video_embeddings` resolves to `main`, which is the intended table.\n\n### 7. `engine/server/db/jobs/updater-worker.py`\n\n- Import, next to `data.moderation`: `from data.ann_ids import compute_ann_id`. `server_dir` is already on `sys.path` (lines 24-27), so the plan's fallback `sys.path` insert is not needed.\n- `inject_replace_embedding_for_test`: docstring \"Insert one overlapping embedding row into staging with modified payload and the same ann_id.\" The insert becomes:\n\n```python\n            INSERT OR REPLACE INTO video_embeddings\n              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)\n            VALUES (?, ?, ?, ?, ?, datetime('now'), ?)\n```\n\n  with `compute_ann_id(video_id, instance_domain)` added to the parameters. The id is computed rather than read from prod, so the inject works whatever shape prod has, and an old-shape prod is still refused at merge.\n\n### 8. `engine/server/db/jobs/build-ann-index.py`\n\n- Import: `from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id`.\n- `EmbeddingRow.rowid` becomes `ann_id: int`. In `iter_embeddings`, `for ann_id, embedding_blob, embedding_dim in rows:` and `EmbeddingRow(ann_id=ann_id, ...)`.\n- In `main()`, right after connecting and before `resolve_embedding_space`: `assert_video_embeddings_has_ann_id(conn)`. This is the AC4 refusal, and it names `migrate-whitelist.py`.\n- Add query: `\"SELECT ann_id, embedding, embedding_dim FROM video_embeddings\"`. Ids: `np.array([item.ann_id for item in batch], dtype=np.int64)`; a 63-bit id fits.\n- `meta[\"id_source\"] = ANN_ID_SOURCE`.\n- `fetch_training_samples` is unchanged: `rowid % step` only spreads the training sample and is never an identity. This is a named simplification.\n\n### 9. `engine/server/data/embedding_space.py`\n\n- Import: `from data.ann_ids import ANN_ID_SOURCE`.\n- Docstring: one more paragraph: \"The sidecar also records `id_source`. Readers resolve hits by `video_embeddings.ann_id` (ADR-0006), so an index whose ids are rowids would return the wrong videos and is refused.\"\n- After the model check:\n\n```python\n    index_id_source = str(meta.get(\"id_source\") or \"\")\n    if index_id_source != ANN_ID_SOURCE:\n        raise RuntimeError(\n            f\"Index ids come from {index_id_source or '<unset>'} but readers resolve \"\n            f\"{ANN_ID_SOURCE}. Rebuild the index with build-ann-index.py.\"\n        )\n```\n\n  This also guards `precompute-similar-ann.py`.\n\n### 10. Readers: rowid \u2192 `ann_id` rename\n\n**`data/embeddings.py`**\n- The four `e.rowid AS rowid` selects become `e.ann_id AS ann_id`.\n- `_seed_from_row` returns `\"ann_id\": int(row[\"ann_id\"])`.\n- In `resolve_seed`, every `\"exclude_rowid\"` becomes `\"exclude_ann_id\"` (all three return shapes), and `\"rowid\": seed[\"rowid\"]` becomes `\"ann_id\": seed[\"ann_id\"]`.\n\n**`data/ann.py`**\n- `compute_similar_items`: `ann_ids = [int(item) for item in ids[0] if int(item) > 0]`. The log key becomes `ann_ids=%d`. The loop variable becomes `ann_id`/`ann_id_int`, and the self check `== seed[\"ann_id\"]`.\n- `search_similar_above`: `seed_ann_id = seed.get(\"ann_id\")`, with the `> 0` filter kept.\n- `search_index(index, vector, limit, exclude_ann_id)` keeps the same position. Its docstring becomes \"optionally exclude an ANN id\", and its loop variable `ann_id`.\n- The nprobe helpers are untouched.\n\n**`data/metadata.py`**\n- `fetch_metadata(conn, ann_ids: list[int], ...)`, docstring \"Fetch video metadata for embedding ANN ids.\"\n- `e.ann_id AS ann_id`, `WHERE e.ann_id IN (...)` (served by the UNIQUE index), `result[int(row[\"ann_id\"])]`. Every caller passes ids positionally (checked).\n- The output dicts still do not carry the id.\n\n**`data/search.py`**\n- In `vector_candidates`, `ann_ids, _scores = search_index(...)`, and the rest of the function follows.\n- `VIDEO_ROW_SQL` `v.rowid` (the `videos_fts` link) is unchanged.\n\n**`api/handlers/similar.py`**\n- `ann_ids, scores = search_index(self.server.index, vector, limit, seed[\"exclude_ann_id\"])`; the `fetch_metadata` call and the loop are renamed to match.\n\n### 11. Random cache\n\n**`data/random_cache.py`**\n- `RANDOM_CACHE_CHECK_SQL = \"SELECT COUNT(*) FROM random_ann_ids\"`.\n- Table: `random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)`.\n- `random_rowids_count` becomes `random_ann_ids_count`. It looks for `name = 'random_ann_ids'`, with the docstring \"Return the number of cached ANN ids, or None when the random_ann_ids table is missing (an old-format random_rowids file counts as missing).\"\n- `populate_random_cache`:\n  - the source stats become `COUNT(*) AS total, MIN(ann_id) AS min_id, MAX(ann_id) AS max_id`;\n  - the unfiltered scan becomes `SELECT ann_id FROM video_embeddings WHERE ann_id >= ? ORDER BY ann_id LIMIT ?`, with a wrap that uses `ann_id < ?`;\n  - the filtered `scan_range` selects `e.ann_id AS ann_id`, `WHERE e.ann_id >= ? AND e.ann_id <= ? ORDER BY e.ann_id`, and sets `current = int(rows[-1][\"ann_id\"]) + 1`;\n  - the locals become `ann_ids`, and the inserts become `INSERT INTO random_ann_ids (position, ann_id)`.\n  - Comment above the start draw: \"# Hashed ids are uniform over [min_id, max_id], so a window from a random start is a uniform sample, not a block of insertion order.\"\n- `build_random_cache` docstring: \"(temp path, ANN ids written, elapsed seconds)\".\n- `open_random_cache_if_usable` docstring: \"holds at least one ANN id\". The `no_table` path now also covers old `random_rowids` files. No new code is needed.\n- `fetch_random_rowids` becomes `fetch_random_ann_ids`, which reads `SELECT ann_id FROM random_ann_ids ORDER BY position ...`.\n\n**`data/random_videos.py`**\n- `from data.random_cache import fetch_random_ann_ids`. In `fetch_random_rows_from_cache`, the locals become `ann_ids`, and the docstring says \"precomputed ANN-id cache\" and \"unseen ANN id\".\n\n**`db/jobs/precompute-random-rowids.py`**\n- Imports `random_ann_ids_count`. An old-shape `--out` counts as 0 and is rebuilt.\n- `description=\"Precompute random ANN-id cache.\"` and `--size` help `\"ANN ids to sample.\"`. The file name and arguments are unchanged.\n\n**`api/server_config.py`**\n- The comment becomes \"Precomputed random ANN ids stored for fast random feed responses.\"\n\n**Named simplification.** An old cache is detected by its table name, not its shape. The ceiling: a future reshape under the same name would need a column check. The upgrade: compare `PRAGMA table_info` in `random_ann_ids_count`.\n\n### 12. `engine/server/db/jobs/precompute-similar-ann.py`\n\n- `iter_embedding_rows_by_rowids` becomes `iter_embedding_rows_by_ann_ids(conn, ann_ids, batch_size=512)`, which selects `ann_id, video_id, instance_domain, embedding, embedding_dim` with `WHERE ann_id IN (...)`.\n- `fetch_similarity_targets` and `fetch_similarity_targets_chunked` take `ann_ids`, select `ann_id, video_id, instance_domain` with `WHERE ann_id IN`, and return `{row[\"ann_id\"]: dict(row)}`. Their docstrings say \"ANN id\".\n- Both selection queries use `SELECT e.ann_id`, and `pending_ann_ids = [int(row[\"ann_id\"]) ...]`. The full mode selects `ann_id, video_id, instance_domain, embedding, embedding_dim`. The comment at line 366 says \"only ANN ids are materialized\".\n- In the loop: `batch_ann_ids`, `targets_by_ann_id`, and `if ann_id_int == row[\"ann_id\"] or ann_id_int <= 0: continue`.\n- The output keys and the `video_keys` joins are unchanged. The local `set_nprobe` is unchanged. The source stays `mode=ro`, so nothing is registered on it.\n\n### 13. `engine/server/db/jobs/tests/test-orchestrator-smoke.py`\n\n- Import: `from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id, create_ann_id_guards`.\n- In `copy_and_prune_prod`, right after `create_table_and_indexes_from_source(conn, table)` for `table == \"video_embeddings\"`:\n\n```python\n            if table == \"video_embeddings\":\n                # The copy brings tables and indexes only; mini-prod needs the collision trigger for the merge to run guarded, and an unmigrated source is refused here with the migrate message.\n                assert_video_embeddings_has_ann_id(conn)\n                create_ann_id_guards(conn)\n```\n\n  This is chosen over copying `type='trigger'` generally, which would also bring `videos_fts_*` triggers into a mini-prod that has no `videos_fts`.\n\n- In `validate_outputs`, after `meta_total`:\n\n```python\n    if meta.get(\"id_source\") != ANN_ID_SOURCE:\n        raise RuntimeError(f\"ANN meta id_source is {meta.get('id_source')!r}, expected {ANN_ID_SOURCE!r}\")\n    checks[\"ann_id_source\"] = meta[\"id_source\"]\n```\n\n- `INSERT INTO video_embeddings SELECT e.*` still works, because the DDL is copied with the same column order.\n\n### 14. Tests\n\n**Shared helper.** `tests/active/conftest.py` appends `ROOT / \"engine\" / \"server\"` to `sys.path` after the client imports. Appending rather than inserting keeps `client/backend`'s `server` and `lib` first. It then re-exports `from data.ann_ids import compute_ann_id  # noqa: E402`, and tests use `from conftest import compute_ann_id`.\n\n**New: `tests/active/test_ann_ids.py`.** Runs on the system interpreter, apart from the AC8 child.\n- AC1:\n  - the same call gives the same result;\n  - `1 <= id <= 2**63-1` over a few hundred keys;\n  - one literal pinned value for `(\"abc\", \"peertube.example\")`, computed once by an independent `hashlib` one-liner at implementation time and pasted in as a constant;\n  - `\"Peertube.Example.\"` gives the same id;\n  - an unparsable domain falls back deterministically.\n- AC2, schema: `ensure_video_embeddings_schema` on a DB that has `videos`, then:\n  - `INSERT` with `ann_id=0` raises IntegrityError (CHECK);\n  - a doctored `ann_id` equal to another key's id raises IntegrityError on a plain INSERT, and again on `INSERT OR REPLACE`; afterwards the other row still exists, unchanged;\n  - a same-key `INSERT OR REPLACE` keeps the count and the id;\n  - an UPDATE to a taken id raises (UNIQUE).\n- AC2, old shape:\n  - `assert_video_embeddings_has_ann_id` on a six-column table raises a message containing `migrate-whitelist.py` and `--resume-staging`;\n  - on an attached schema, it names `stage.`;\n  - on a missing table, it does nothing.\n- AC2, merge: run `merge-staging-db.py` as a subprocess on a tmp prod and staging pair.\n  - A doctored staging row (a new key carrying an existing prod id) exits non-zero; prod is unchanged and the other video is present.\n  - An old-shape stage exits non-zero with the message.\n  - A normal merge carries `ann_id` across.\n- AC3: `sync-whitelist.rebuild_content_tables`, loaded with `importlib` the way the existing tests do, on an attached source **with** `ann_id`, which is copied, and on one **without**, which is computed and equals `compute_ann_id`. In both cases `ensure_schema_compatibility` passes on the new shape and fails on an old target with \"missing columns: ann_id ... migrate-whitelist.py\".\n- AC5: `assert_index_matches_embeddings` with a stub index (`SimpleNamespace(d=4)`) and a sidecar:\n  - `id_source` `video_embeddings.rowid` raises naming `build-ann-index.py`;\n  - a missing `id_source` raises;\n  - `video_embeddings.ann_id` passes.\n\n**New: `tests/active/test_stale_ann_index.py` (AC8).** It runs a child under `ENGINE_PY`, the `test_precompute_similar_ann` pattern, because it needs faiss and numpy.\n- The child builds a small DB (`videos`, `channels`, `video_embeddings` via `ensure_video_embeddings_schema`) and an `IDMap2,IVF1,Flat` index on `ann_id`. It records `ann_id \u2192 (video_id, host)` from the vectors it indexed.\n- **Case A, renumber.** Delete every row and reinsert them in reversed order. The rowids change and the ids do not.\n- **Case B, purge.** Run `purge_host_data` for one host.\n- **Case C.** Insert a new video that the index does not hold.\n- After each case, the child calls `ann.compute_similar_items` and `search.vector_candidates`. It uses a stub server (`index`, `index_lock`, `db`, `db_lock`, `normalize_queries=False`, `similarity_*` defaults, and a `query_encoder` stub whose `enabled=True` and whose `encode` returns a fixed vector).\n- It prints JSON. The test asserts that every returned `(video_id, instance_domain)` equals the identity recorded for the vector whose hit produced it, that the purged host's videos are absent, and that the new video is absent rather than substituted.\n- This is a departure from the plan's word \"job test\": it lives in `tests/active`, where the gating suite runs and where the faiss-in-a-child precedent already exists.\n\n**Migration tests (in `tests/active/test_whitelist_migrations.py`).** An old six-column table with 3 rows, then `migrate_whitelist_schema`:\n- the columns include `ann_id`, and each value equals `compute_ann_id`;\n- `idx_video_embeddings_ann_id` and the trigger are in `sqlite_master`;\n- a second run changes nothing (same `sqlite_master` and the same rows);\n- a DB without the table is left alone;\n- an old table with a doctored duplicate cannot occur from the function, so failure atomicity is pinned by registering a stub `ann_id_of` that returns a constant. The migration raises, and the old table still has six columns and every row.\n\nThe test also inserts `engine/server` on `sys.path` itself; the module now does that too.\n\n**Fixture churn.**\n\n| File | Change |\n|---|---|\n| `test_metadata.py` | Fixture DDL gains `ann_id INTEGER`. Inserts pass `compute_ann_id(label, HOST)`. `_nsfw_metadata` selects `ann_id` instead of `rowid`. |\n| `test_random_videos.py` | `NSFW_EMBEDDINGS_TABLE` gains `ann_id`. `_video_db` maps labels to `compute_ann_id`. `_cache_owner` creates `random_ann_ids(position, ann_id)` and monkeypatches `fetch_random_ann_ids` on both modules. The docstring says \"unseen ANN id\". CTAS copies from `whitelist.db` are unchanged. |\n| `test_random_cache.py` | `_source_db` gains an `ann_id` column with computed values. Every `random_rowids` becomes `random_ann_ids`. \"positions 1..20 over rowids 1..20\" becomes the set of the 20 computed ids. Engine cases map rows back with `SELECT ann_id`. The \"no table\" probe uses an old-format `random_rowids` file, which pins AC6's old-shape case. |\n| `test_db.py` | Its source gains `ann_id`. `_seed_cache` and `CHECK_SQL` move to `random_ann_ids`. Imports `fetch_random_ann_ids`. `SEEDED_ROWIDS` becomes computed ids. |\n| `test_precompute_random_rowids.py` | Its source gains `ann_id`. Assertions use `sorted(computed ids)`. New case: an `--out` holding an old `random_rowids` table with `--size` rows is rebuilt into `random_ann_ids`, not kept. |\n| `test_precompute_similar_ann.py` | The fixture table gains `ann_id` (`compute_ann_id`). `INDEX_BUILDER` adds with `SELECT ann_id, embedding`. The sidecar adds `\"id_source\": \"video_embeddings.ann_id\"`. `SHORT_ROWID` and `v{n}` stay as labels only. |\n| `test_video.py` | The positional inserts at 543-544 become explicit column lists, with `ann_id`. `similars_stack` selects `ann_id` for `add_with_ids`. |\n\n`test_internal_client_reads`, `test_search`, `test_similarity_candidates` and `test_videos` are unchanged, because none of them reaches `ann_id`. `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles` and `test_frontend_reactions` are SELECT-only and need no code change. `test-moderation-integration.py` is unchanged, per its impact. The plan's \"Conflicts\" list is corrected when Impacts is filled.\n\n**`tests/config.json`.**\n- Add `engine/server/data/ann_ids.py` to `test_ann_ids`, `test_stale_ann_index`, `test_metadata`, `test_random_cache`, `test_random_videos`, `test_db`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_whitelist_migrations` and `test_video`.\n- Add `embedding_space.py` to `test_ann_ids` and `test_precompute_similar_ann`.\n- Map the two new files to the sources they exercise.\n\n`tests/last_test_validation.json` is regenerated by the test run, not edited by hand.\n\n### 15. Docs\n\nThese follow the settled documentation list:\n- `DATA_BUILD.md`, `DEPLOYMENT.md` and `UPDATER_WORKER.md` get the cutover: stop the Engine, run `migrate-whitelist.py` (a rebuild that needs about 1.4 GB free plus the default full-file backup, about 3.5 GB, unless `--no-backup` is used), run `build-ann-index.py`, then start the Engine. They also cover the refusal messages and the `--resume-staging` behaviour.\n- `ORCHESTRATOR_SMOKE_TEST.md`: the `id_source` check, and that the source must be migrated.\n- `LAYER_PARAMS.md` and `OVERVIEW.md`: `random_ann_ids`.\n- `engine/server/README.md`: the optional startup-refusal note.\n- At close, the issue gets `Status: enhancement, complete` and moves to the archive.\n\n### Seams and environment notes for the test steps\n\n- **Engine-backed tests and the shared dataset.** The session `engine` fixture starts the real Engine on the shared `whitelist.db` and index. After AC5 it exits at startup until that dataset is migrated and its index rebuilt. DATA_BUILD runs shared migrations on main only after merge. So the Engine-backed `tests/active` cases can only go green once the cutover has run on the dataset they read. The unit and job tests above do not depend on it. The gate step has to schedule this; the code cannot fix it.\n- **The smoke test's `--source-db`** must likewise be migrated. Otherwise it stops with the AC2 message, by design.\n\n### Pass check against the plan and the requirements\n\n**Pass 1** found these gaps; the draft above includes the fixes:\n1. The guards on old tables would fail with a raw sqlite error (sync's ordering hazard and `init_schema`). Fixed by the split DDL and the conditional guard creation.\n2. The migration was not atomic (a failed index build left a table with no guards). Fixed by the explicit transaction.\n3. `whitelist_migrations` depended on load order. Fixed by its own `sys.path` insert.\n4. Mini-prod would have no trigger. Fixed by creating the guards after the copy.\n5. `None` and ports from `normalize_host`. Settled: fall back to the raw domain, with a port pre-check query.\n6. The test sidecar had no `id_source`. Fixed.\n\n**Pass 2** found everything met:\n- **AC1:** the one helper, stdlib, 63-bit, pinned value.\n- **AC2:**\n  - the column, CHECK and UNIQUE index;\n  - the migration follows the rebuild shape, is idempotent and is called last;\n  - every creator uses the one definition;\n  - the trigger guards every path, including `OR REPLACE`;\n  - an old shape fails with a message naming `migrate-whitelist.py` or staging recreation.\n- **AC3:**\n  - every writer stores the helper's id;\n  - merge changes only by the approved guard;\n  - sync copies or computes the id, with the source check still the six columns;\n  - re-runs keep the same ids.\n- **AC4:** `ann_id` ids, `id_source`, and the refusal.\n- **AC5:** the gate, naming `build-ann-index.py`.\n- **AC6:** every listed reader uses `ann_id`, and an old cache is never read.\n- **AC7:** `ann_id` throughout, with output keys and selection unchanged.\n- **AC8:** the stale-index test.\n- **AC9:** the smoke test assertion and the docs.\n- **Consistency:** CLIs unchanged, the refusal style followed, `normalize_host` reused, each file's style kept.\n\nThe two departures (the transaction in the migration, and the AC8 test living in `tests/active`) are named above."
}
```
dev-flow:state -->

## 2026-10-02 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/08",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Start snapshot: tree `06726eb0377e283d8e7f5156de70bc5d7dfa5941` at 2026-10-02T15:06:17-04:00.

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 51 test groups (50 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.5s
  ---------------------
  total                  10 passed                              2.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Asked for

Issue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2, plan `docs/project/plans/17-stable-ann-ids.md`). Today the FAISS index, and every reader that turns an id back into an embedded video, use `video_embeddings.rowid`. They switch to a deterministic `ann_id` derived from `(video_id, instance_domain)`. ADR-0006 (`docs/project/adr/0006-derived-ann-ids.md`) records the decision, and `CONTEXT.md` defines **ANN id**.

### Purpose

Correctness. `video_embeddings` can change while no index rebuild follows, or while the rebuild fails: a merge, a host purge, a whole-table reload, a `--force` re-embed, a migration. In every such case the index must never return the wrong video. At most it misses videos it has not indexed yet. The build must not block later incremental index add or remove (F3/F4-M2), and it does not build them.

### Current state (checked against the tree and the live DB, read-only)

- `engine/server/db/jobs/build-ann-index.py:250-256` calls `add_with_ids` with `video_embeddings.rowid` and writes `id_source: "video_embeddings.rowid"` (line 284). The live sidecar `engine/server/db/whitelist-video-embeddings.faiss.json` says the same.
- The live `engine/server/db/whitelist.db`:
  - 890,052 `video_embeddings` rows, rowids exactly 1..890,052.
  - Primary key `(video_id, instance_domain)`.
  - 1,548 hosts, all already lowercase and trimmed.
  - Every `video_id` is text.
- Hash check: a 63-bit blake2b of `video_id::instance_domain` over all 890,052 keys gave 0 collisions, and no key hashed to 0.
- Rowid-keyed readers:
  - `engine/server/data/ann.py`:
    - `compute_similar_items`, and its `ids > 0` filter.
    - `search_index` (`exclude_rowid`).
    - `search_similar_above`, the up-next fallback search. It keeps rowid hits through the same `ids > 0` filter, excludes `seed["rowid"]` and calls `fetch_metadata` by rowid.
    - The nprobe helpers `_extract_ivf`, `get_nprobe`, `apply_nprobe` and `set_nprobe` also live in this file, and `server.py` imports `set_nprobe` from it. `precompute-similar-ann.py` keeps its own copy of `set_nprobe`.
  - `engine/server/data/embeddings.py`: the seed's `rowid`/`exclude_rowid` in `resolve_seed` and in the three seed queries.
  - `engine/server/data/metadata.py`: `fetch_metadata`, which selects `WHERE e.rowid IN (...)`.
  - `engine/server/data/search.py`: `vector_candidates`.
  - `engine/server/api/handlers/similar.py`: `_handle_vector_search`.
  - `engine/server/data/random_cache.py` and `engine/server/data/random_videos.py`: the `random_rowids` table.
  - `engine/server/db/jobs/precompute-random-rowids.py`.
  - `engine/server/db/jobs/precompute-similar-ann.py`: `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*` and the main loop.
  - The rowid uses in `data/users.py` (likes) and `data/interaction_events.py` are about other tables, are not ANN ids, and do not change.
- Writers that renumber rowids, or write `video_embeddings` at all:
  - `build-video-embeddings.py`: `init_schema` uses `CREATE TABLE IF NOT EXISTS` (line 66). Under `--force` it runs DELETE (line 177), then `INSERT OR REPLACE` (line 272).
  - `sync-whitelist.py`: `rebuild_content_tables` runs `DELETE FROM video_embeddings` (line 458), then `INSERT ... SELECT` from the attached crawl DB (lines 493-510). That copy runs only when the source's columns are a superset of `EMBEDDING_COLUMNS`. The same `EMBEDDING_COLUMNS` list also drives the exact check on the target schema in `ensure_schema_compatibility` (line 194), and the schema created at line 385 has no `ann_id`.
  - `merge-staging-db.py`: `merge_rules.json` gives `video_embeddings` the `INSERT_OR_REPLACE` strategy, run as `INSERT OR REPLACE INTO main.t (common cols) SELECT ... FROM stage.t` over the columns prod and staging share (lines 152-171). The script also supports an `UPSERT` strategy.
  - `updater-worker.inject_replace_embedding_for_test` (lines 1018-1064): a test-only `INSERT OR REPLACE` of one mutated embedding into staging, without `ann_id`.
  - `whitelist_migrations.migrate_videos_schema` drops `video_embeddings` (line 268) and does not recreate it. The next schema creation does that.
- Staging: the updater creates staging from `engine/crawler/schema.sql` (`init_staging_db`). That schema does not create `video_embeddings`, so `build-video-embeddings.init_schema` creates the staging table. `--resume-staging` reuses an existing staging DB, whose table may be in the old shape.
- The updater (`updater-worker.py:1040-1150`) stops the service, merges, rebuilds the ANN, precomputes, and restarts in a `finally`. So a failed ANN build restarts the Engine on the old index against renumbered rows.
- Random cache:
  - The Engine never writes the random cache before listening. At start it opens `random-cache.db` read-only through `open_random_cache_if_usable` (`random_cache.py:283-302`). That accepts any non-empty `random_rowids` table without checking its shape.
  - `server.py:345` sets `random_cache_startup_build = random_cache_refresh or random_cache_db is None`, so a cache judged unusable always gets a background build.
  - Every build runs through `build_random_cache` (`random_cache.py:208-245`) into a per-pid temp file, which is swapped in through `swap_readonly_connection(..., RANDOM_CACHE_CHECK_SQL)`.
  - With refresh off (`--dev`, `server.py:317-320`), a stored non-empty cache is served as it is.
  - `precompute-random-rowids.py` keeps an `--out` that already holds `--size` rows, counted through `random_rowids_count` without checking their shape.
  - `engine/server/api/recommendations/docs/LAYER_PARAMS.md` and `OVERVIEW.md` describe the cache as `random_rowids`.
- Already on logical keys:
  - The similarity cache (`similarity_items`) is keyed by `(video_id, instance_domain)` text and holds no rowids.
  - `videos_fts` joins `videos.rowid` as FTS5 external content. That link is not an ANN id.
- The Engine checks the index sidecar at start in `data/embedding_space.assert_index_matches_embeddings`, which today checks the model and the dimension.
- Not checked: whether any deployed crawl DB that `sync-whitelist.py` reads already holds `video_embeddings` rows, with or without `ann_id`. The requirements cover all three cases.

### Acceptance criteria

- **AC1, the id:** one helper (for example `engine/server/data/ann_ids.py`) computes `ann_id` as blake2b with an 8-byte digest of `video_id + "::" + normalize_host(instance_domain)`, masked to 63 bits. `normalize_host` is the existing `data/moderation.normalize_host`. The result is positive, non-zero and safe as a signed int64. The same key gives the same id in any process and any DB. Every writer and reader uses this one helper. Jobs import it the way they already import `data.*`.
- **AC2, the schema:** `video_embeddings` carries `ann_id INTEGER NOT NULL` with a UNIQUE index.
  - A new `whitelist_migrations.migrate_video_embeddings_schema` rebuilds an existing table into that shape and fills the column from the helper through `sqlite3` `create_function`. It follows the existing `migrate_*_schema` table-rebuild pattern, and it is idempotent: it does nothing once the column exists. `migrate_whitelist_schema` calls it, so `migrate-whitelist.py` runs it.
  - Every job that creates the table creates the same shape: `build-video-embeddings.init_schema` and the `sync-whitelist.py` schema. So does any table recreated after `migrate_videos_schema` drops it.
  - **Collision guard:** a collision fails the write loudly on every write path, including `INSERT OR REPLACE` paths. A collision means a different `(video_id, instance_domain)` producing an `ann_id` already in use, or an id of 0. SQLite's `OR REPLACE` resolves conflicts on every UNIQUE index, so a plain UNIQUE index under `INSERT OR REPLACE` would silently delete the other video. That must not happen. The mechanism is a design choice: for example, writers use UPSERT on `(video_id, instance_domain)` and the `merge_rules.json` strategy for `video_embeddings` becomes `UPSERT`, or a BEFORE INSERT trigger raises. A write never probes for another id.
  - **Old-shape tables:** writing into a `video_embeddings` table that lacks `ann_id` fails loudly with a message naming `engine/server/db/jobs/migrate-whitelist.py`, or, for a resumed staging DB, saying to recreate staging. Examples are an unmigrated prod DB, or a staging DB reused by `--resume-staging`. No writer ever produces rows without `ann_id`.
- **AC3, the writers:** every writer stores the helper's `ann_id`.
  - `build-video-embeddings.py` computes it per row.
  - `merge-staging-db.py` preserves it from staging. The only change allowed there is the rule or strategy change the collision guard needs.
  - `sync-whitelist.py` copies `ann_id` when the source has the column, and computes it through the registered function when the source has embeddings without it, so an older crawl DB does not force a re-embed. The target-schema check requires `ann_id`. The source-column check must not require it, or embeddings would be silently skipped.
  - `updater-worker.inject_replace_embedding_for_test` writes `ann_id`.
  - Re-running a writer, or replacing a row, leaves the video's `ann_id` unchanged.
- **AC4, the index build:** `build-ann-index.py` adds vectors with `ann_id` as their ids and writes `id_source: "video_embeddings.ann_id"` to the sidecar. When the column is missing, it fails with a message naming `migrate-whitelist.py`.
- **AC5, the Engine gate:** the Engine refuses to start when the index sidecar's `id_source` is not `video_embeddings.ann_id`. It refuses the same way it refuses a model mismatch today, in `assert_index_matches_embeddings`, with a message naming `build-ann-index.py`.
- **AC6, the readers:** these resolve embedded videos by `ann_id`:
  - similar: the seed and its exclusion (`ann_id`/`exclude_ann_id` in `embeddings.py`), the ANN results (`ann.py`, including `search_similar_above` and the `ids > 0` filter), and raw vector search (`similar._handle_vector_search`);
  - search's vector half (`search.vector_candidates`);
  - `fetch_metadata`, as `WHERE e.ann_id IN (...)`, served by the UNIQUE index;
  - the random cache (`random_cache.py`, `random_videos.py`, `precompute-random-rowids.py`).

  A stored random cache in the old `random_rowids` shape is detected and repopulated, never read. `open_random_cache_if_usable` treats it as unusable, so the Engine serves from the DB and runs a background build. The keep check in `precompute-random-rowids.py` treats an old-shape `--out` as not kept. Afterwards, no reader resolves an embedded video by rowid.
- **AC7, the similarity precompute:** `precompute-similar-ann.py` uses `ann_id` for its FAISS ids and its target lookup. Its output keys (`similarity_items`, `(video_id, instance_domain)`) are unchanged, and its incremental selection stays keyed on `(video_id, instance_domain)`.
- **AC8, the purpose observed in a test:** build an index, then, with no index rebuild, either renumber the DB's rows (delete and reinsert every row, as `sync-whitelist.py` does) or purge a host. Similar and search then return only videos whose identity matches the vector indexed for them. Unindexed or purged videos may be missing, but no result is a different video.
- **AC9, the cycle and docs:** the updater's full cycle (merge → ANN build → precompute) runs on the new id source, observed through the orchestrator smoke test (`engine/server/db/jobs/tests/test-orchestrator-smoke.py`). These docs carry the one-time migrate-then-rebuild step for existing DBs: `DATA_BUILD.md`, `DEPLOYMENT.md` and the updater docs (`engine/server/db/jobs/docs/UPDATER_WORKER.md`). The step is `migrate-whitelist.py`, then `build-ann-index.py`, then start the Engine. `LAYER_PARAMS.md` and `OVERVIEW.md` (under `engine/server/api/recommendations/docs/`) describe the random cache's new `ann_id` shape.

### Scope

In scope: AC1-AC9, including the random cache, as the operator decided. One build, correctness only.

Out of scope:
- incremental FAISS add or remove (F3/F4-M2);
- rebuilding or re-keying the similarity cache;
- `videos_fts`;
- backward compatibility with rowid indexes (a `rowid` sidecar is refused, not read);
- the crawler (`engine/crawler`, including `schema.sql`).

### Consistency constraints

- Job CLIs keep their current arguments.
- Refusal messages follow `data/embedding_space.py`: say what is wrong, and name the command that fixes it.
- The migration follows the existing `migrate_*_schema` table-rebuild pattern in `whitelist_migrations.py`.
- Hosts go through the existing `data/moderation.normalize_host`.
- New code matches the style of the file it lands in.
- Design to the smallest thing that works: stdlib `hashlib.blake2b`, no new dependency, one helper module.

### Tests

- Active tests live in `tests/active`, scratch work goes in `tests/tmp`, and job tests live in `engine/server/db/jobs/tests/`.
- Pre-build baseline: the suite exits with code 0 (`variant: false`).
- Fixture churn: these tests insert into `video_embeddings` without `ann_id`, and NOT NULL breaks them, so they change with the build.
  - 9 files in `tests/active`: `conftest.py`, `test_blocks.py`, `test_dislike_profile.py`, `test_dislikes.py`, `test_frontend_reactions.py`, `test_internal_client_reads.py`, `test_metadata.py`, `test_profiles.py`, `test_random_videos.py`.
  - 2 job tests: `test-moderation-integration.py`, `test-orchestrator-smoke.py`.
  - A shared fixture helper that computes `ann_id` keeps each file's change to its insert.
- New tests cover:
  - AC1: determinism, range, and a fixed known value;
  - AC2: migration backfill, idempotence, the UNIQUE index, and the collision guard, including under `INSERT OR REPLACE` and on the merge path;
  - AC3: each writer, including `sync-whitelist` from a source with `ann_id` and from one without;
  - AC4/AC5: the sidecar's `id_source` and the Engine's refusal;
  - AC6: the old-shape random cache rejected and rebuilt;
  - AC8: the stale index after a renumber and after a host purge.

### Risks and limitations accepted

- The one-time migration rewrites about 1.4 GB of embedding blobs. It needs about that much free disk, and the Engine must be stopped while it runs.
- Hard cutover: the Engine refuses a `rowid` sidecar, so the deploy order is migrate, then index build, then start. The similarity cache needs no rebuild.
- A collision stops a dataset build or a merge loudly, and recovery is manual. The odds are about 4e-8 at 890k keys, and 0 collisions were measured.
- Purged or deleted videos stay in the index until the next rebuild. They show up as misses (no metadata row), never as wrong videos.
- A re-embedded video keeps its old vector in the index until the next rebuild, but it still resolves to the right video.
- New videos stay out of the index until a rebuild.
- A staging DB resumed from before the cutover fails loudly. It is not migrated.

### conflicts

AC2 "a collision fails the write loudly" vs the tree's INSERT OR REPLACE writers (`build-video-embeddings.py:272`, `merge_rules.json` INSERT_OR_REPLACE run by `merge-staging-db.py:167-171`, `updater-worker.py:1046`): SQLite OR REPLACE clears UNIQUE(ann_id) conflicts by deleting the other row, so a collision would silently drop a video. Resolved by the operator: the collision guard must hold on those paths too, so the plan's "merge-staging-db needs no code change" may become a `merge_rules.json` strategy change.
The plan's "merge-staging-db needs no code change, because staging now carries ann_id" vs `updater-worker --resume-staging`, which reuses a staging DB that `build-video-embeddings` (CREATE TABLE IF NOT EXISTS) leaves in the old shape. Resolved: writing to an old-shape table fails loudly and names the fix.
The plan's single source-column check at `sync-whitelist.py:492-499` vs `EMBEDDING_COLUMNS`, which drives both the exact target check (line 194) and the source-superset check (line 499). Adding ann_id to that list would make older crawl DBs skip all embeddings. Resolved: the target check requires ann_id and the source check does not.
The issue says the updater must "keep ANN id consistency before rebuild/precompute" vs AC2/AC3, under which the schema guarantees the column, so the updater needs no step of its own beyond the migration having run once. The operator accepted this reading. The one updater code change is `inject_replace_embedding_for_test` writing ann_id.

## 2026-10-02 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

One new module, `engine/server/data/ann_ids.py`, holds everything the id needs, the same way `data/moderation.py` holds `normalize_host` and `ensure_moderation_schema`. It has four parts:
- the pure function that computes the id from `(video_id, instance_domain)`;
- a registration that exposes that function to SQLite under one SQL name, through `create_function`;
- the one definition of the `video_embeddings` table: its columns, `CHECK (ann_id > 0)`, the UNIQUE index on `ann_id`, and the collision trigger;
- an old-shape check that raises the AC2 message.

Every writer, reader, migration and test fixture imports from this module. Jobs reach it through the `data.*` import path they already use. `whitelist_migrations.py` reaches it through the server dir that `migrate-whitelist.py` already puts on `sys.path`.

**AC1, the id.** blake2b with an 8-byte digest of `video_id + "::" + normalize_host(instance_domain)`, read big-endian and masked to 63 bits, using stdlib `hashlib`. The result is between 0 and 2^63-1 and fits a SQLite INTEGER, a numpy int64 and a FAISS id. The function only computes; it never probes. An id of 0 is stopped by the schema, not by the function.

**AC2, the schema and the collision guard.** `video_embeddings` gains `ann_id INTEGER NOT NULL CHECK (ann_id > 0)` and a UNIQUE index. The guard is a BEFORE INSERT trigger. It raises ABORT when another row with a different `(video_id, instance_domain)` already holds `NEW.ann_id`.

The trigger works on every path because SQLite fires BEFORE triggers ahead of constraint resolution. The new row is checked before `OR REPLACE` can delete the other video's row. That covers `build-video-embeddings`, the merge's `INSERT OR REPLACE`, the bulk `INSERT ... SELECT` in sync, the updater's test inject and any hand-run SQL. The trigger uses plain SQL, so it works on any connection, including the sqlite3 CLI.

A same-key replace (a re-embed, or a merge of an updated row) does not match the trigger: same key and same id, so the row is replaced and its `ann_id` is unchanged. An id of 0 fails the CHECK, which `OR REPLACE` does not override. A plain UPDATE that collides fails on the UNIQUE index, and no code path uses UPDATE OR REPLACE. `merge_rules.json` keeps `INSERT_OR_REPLACE`, because the guard needs no strategy change.

**AC2, the migration.** `migrate_video_embeddings_schema` returns at once when the table is missing or already has `ann_id`. Otherwise it follows the `migrate_*_schema` rebuild pattern:
1. Register the SQL function on the connection.
2. Create `video_embeddings_new` from the shared definition, with the CHECK.
3. Copy every row, filling `ann_id` from the function.
4. Drop the old table and rename the new one.
5. Create the UNIQUE index and the trigger, both IF NOT EXISTS.

The index and trigger come after the rename, so their names refer to the final table. A collision during the backfill then surfaces loudly when the UNIQUE index is built.

`migrate_whitelist_schema` calls it last. If `migrate_videos_schema` has just dropped the table, it does nothing, and the next schema creation builds the new shape. `build-video-embeddings.init_schema` and `sync-whitelist.ensure_content_schema` both create the table from the shared definition, so every recreation, including the one after `migrate_videos_schema`, has the same shape.

**AC2, old-shape tables.** The helper's check reads `PRAGMA table_info` and raises RuntimeError in the `embedding_space.py` style. It says the table has no `ann_id` column, and that prod needs `engine/server/db/jobs/migrate-whitelist.py` while a staging DB reused through `--resume-staging` must be recreated by running the updater without it. These callers use it:
- `build-video-embeddings.py`, right after creating the schema;
- `build-ann-index.py`, before sampling;
- `merge-staging-db.py`, on both `main` and `stage` before the merge transaction. This is the one change the operator approved there.
- `sync-whitelist.py`, through its existing exact target check, whose error already names `migrate-whitelist.py`.

**AC3, the writers.**
- `build-video-embeddings.py` computes the id per row in Python and adds it to the existing `INSERT OR REPLACE` tuple. Under `--force` the DELETE-then-insert gives every video back the same id.
- `merge-staging-db.py` already copies the columns prod and staging share, so `ann_id` comes across from staging unchanged. Its only edit is the guard call above.
- In `sync-whitelist.py`, `EMBEDDING_COLUMNS` splits in two. The target list includes `ann_id` and feeds the exact check. The source superset check keeps today's six columns, so an older crawl DB still qualifies. In `rebuild_content_tables`, when the source has `ann_id` it is copied; otherwise the select computes it through the registered function. Either way the trigger guards every row.
- `updater-worker.inject_replace_embedding_for_test` computes the id through the helper and writes it, so the replacement keeps the prod row's id.

**AC4, the index build.** `build-ann-index.py` selects `ann_id` in place of `rowid` for `add_with_ids` and writes `id_source: "video_embeddings.ann_id"`. The training sample still uses `rowid % step` to spread its rows across the table. That is a sampling cursor, not an identity, and no vector is ever looked up by it.

**AC5, the Engine gate.** `assert_index_matches_embeddings` gains an `id_source` check next to the model check, with a message naming `build-ann-index.py`. The function also guards `precompute-similar-ann.py`, which is correct: a precompute against a rowid index would map hits to the wrong videos.

**AC6, the readers.** The rowid names become `ann_id` throughout:
- the seed's `rowid`/`exclude_rowid` and its three queries in `embeddings.py`;
- the filters and exclusions in `ann.py`, including `search_similar_above`. The `> 0` filter stays valid: real ids are ≥ 1 and FAISS fills empty slots with -1.
- `similar._handle_vector_search`;
- `search.vector_candidates`;
- `fetch_metadata`, which selects and filters on `e.ann_id` through the UNIQUE index.

`search.py`'s own `v.rowid` is the `videos_fts` link and does not change. The nprobe helpers do not change.

**AC6, the random cache.** The cache table becomes `random_ann_ids (position, ann_id)`. Because the new shape has a new table name, old-shape detection needs no new code. Against an old file, the existing count helper (renamed to match) returns None, so:
- `open_random_cache_if_usable` logs `no_table` and returns None, the Engine serves from the DB, and `server.py:345` starts a background build;
- the precompute job's keep check counts 0 and rebuilds;
- `RANDOM_CACHE_CHECK_SQL` names the new table, so a swap can only install a new-shape file.

The build samples by `ann_id` instead of by rowid: a random start between min and max `ann_id`, then the next rows in `ann_id` order, wrapping around. Both the unfiltered and the filtered scans use this. Hashed ids are spread evenly, so this window is a uniform sample, not a block of rows in insertion order.

`precompute-random-rowids.py` keeps its file name and arguments; only its help text changes.

**AC7, the similarity precompute.** In `precompute-similar-ann.py`, `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*`, the pending-selection query and the main loop move to `ann_id`. The self-exclusion becomes `ann_id == row["ann_id"]`. Output keys and incremental selection stay on `(video_id, instance_domain)`.

**AC8, the purpose in a test.** A job test builds a small FAISS index on the new ids. With no index rebuild, it then either deletes and reinserts every row in a different order, or deletes one host's rows. It asserts that every similar and search hit resolves, through `fetch_metadata`, to the video whose vector carries that id, and that the purged host's videos are missing rather than replaced.

This holds by construction. The id is a function of identity, so after any rewrite of the table a stale id finds either the same video or nothing.

**AC9, the cycle and docs.**
- The orchestrator smoke test runs merge, ANN build and precompute on fixtures that carry `ann_id`, and asserts the sidecar's `id_source`.
- `DATA_BUILD.md`, `DEPLOYMENT.md` and `UPDATER_WORKER.md` get the one-time step: stop the Engine, run `migrate-whitelist.py`, run `build-ann-index.py`, start the Engine.
- `LAYER_PARAMS.md` and `OVERVIEW.md` describe `random_ann_ids`.

**Tests.** A shared fixture helper in `tests/active` computes `ann_id`, so each of the 9 churned files changes only its insert. The 2 job tests import the helper directly.

No real collision can be produced, so the collision tests insert an explicit doctored `ann_id` that matches another key's id:
- directly;
- under `INSERT OR REPLACE`, asserting that the other video still exists;
- through merge, from a doctored staging row.

AC1 pins one fixed known value.

### Alternatives considered

- **UPSERT on `(video_id, instance_domain)` in every writer, with the merge rule switched to `UPSERT`, instead of a trigger.** Rejected: the guarantee would depend on every writer, present and future, getting its SQL right. The test inject, any hand-run `INSERT OR REPLACE` and the bulk sync would each be a hole. The trigger lives in the schema and holds for all of them. It also leaves merge's strategy alone.
- **A CHECK that `ann_id` equals the registered function of the key.** It would also catch a wrong id, not just a duplicate. Rejected: every connection that writes, including the sqlite3 CLI and the Engine's test fixtures, would fail with "no such function".
- **Keeping the `random_rowids` table name and checking its column shape.** Rejected for the new table name, which makes the existing "no table" path do the detection with no new code in `open_random_cache_if_usable` or in the keep check.
- **Random-cache sampling by a rowid window while storing `ann_id`.** It would work, but it keeps a rowid read in the reader. The `ann_id` range is already indexed and gives a better spread.
- **Always recomputing `ann_id` in sync instead of copying it from the source.** It would be safer against a foreign id, but AC3 settles on copying.
- **For the old-shape merge failure:** extending the rule's `keys` (a generic message that doesn't name `migrate-whitelist.py`) or guarding only in the updater (a standalone merge into an unmigrated prod would still write rows without `ann_id`). The operator chose the direct guard call in `merge-staging-db.py`.
- **Already rejected in ADR-0006 and not revisited:** a mapping table, a pinned rowid, an assigned counter, and probing for a free id.

### Risks and gotchas

- **Trigger order.** The guard relies on SQLite firing BEFORE INSERT triggers ahead of `OR REPLACE` conflict resolution. The `INSERT OR REPLACE` collision test pins this, so a SQLite behaviour change would show up as a red test.
- **Per-row trigger cost.** Each insert does one lookup on the UNIQUE index. That is negligible for batched embedding writes and adds one indexed probe per row to the 890k-row sync reload.
- **Migration rename.** The UNIQUE index and the trigger are created after the rename, so nothing depends on how ALTER TABLE RENAME rewrites trigger bodies. Backfill collisions surface when the UNIQUE index is built, and id 0 fails the CHECK.
- **JSON precision.** Ids up to 2^63 exceed JavaScript's 2^53 safe range. I checked that `fetch_metadata`'s output dicts, the similar and search handlers and the random feed never put the id into a response. If one is ever exposed, it must be a string.
- **Copied source ids.** `sync-whitelist` trusts a source `ann_id` it copies. The trigger catches duplicates, not a wrong id. In practice only the helper ever writes the column.
- **Random feed change.** The unfiltered draw becomes a hash-uniform sample, not a block of rows in insertion order. Random-cache tests that assert row order or rowid windows will need new expectations.
- **The test inject** needs `updater-worker.py` to reach `data.ann_ids`. If it does not already have the server dir on `sys.path`, it gets the same two-line insert the other jobs use.

### Tradeoffs the operator accepts

- **`merge-staging-db.py` changes by one guard call,** a few lines beyond AC3's limit. The operator approved this so that an unmigrated prod fails with AC2's message.
- **Accepted in the requirements:**
  - the one-time migration needs about 1.4 GB free and a stopped Engine;
  - hard cutover: migrate, build the index, then start;
  - a collision stops the run loudly and recovery is manual;
  - stale indexes miss new videos and keep purged ones, as misses only;
  - a resumed pre-cutover staging DB fails loudly instead of being migrated.
- **The deliberate simplifications:**
  - **The random cache is detected by its table name, not its shape.** The ceiling is that a future change to the shape under the same name would need a real column check. The upgrade path is to compare `PRAGMA table_info` in the count helper.
  - **ANN training samples by `rowid % step`.** This only affects which vectors train the quantizer, never identity.

### conflicts

AC3 (`merge-staging-db.py`: "the only change allowed there is the rule or strategy change the collision guard needs") collides with AC2 (writing into a `video_embeddings` table without `ann_id` fails loudly with a message naming `migrate-whitelist.py`). The merge copies only the columns prod and staging share, so an unmigrated prod would quietly receive rows without `ann_id`, and the chosen trigger guard needs no merge change. Asked through AskUser, the operator chose to allow a small guard call in `merge-staging-db.py`: the shared helper's column check on prod and staging before merging.

## 2026-10-02 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impacts>
<impact path="engine/server/data/ann_ids.py" element="new module: ann_id function, SQL-function registration, shared video_embeddings DDL (CHECK, UNIQUE index, BEFORE INSERT collision trigger), old-shape check">
**What changes:** new file. It holds four things: the pure `ann_id(video_id, instance_domain)` (blake2b with an 8-byte digest, big-endian, masked to 63 bits), a `create_function` registration under one SQL name, the one `video_embeddings` definition, and an old-shape `PRAGMA table_info` check that raises RuntimeError.

**What depends on it:** every writer and reader below. It imports `data.moderation.normalize_host`, which pulls in `data.similarity_cache` at module level (stdlib only, checked). That is safe for jobs run with plain `python3`.

**Regression risks, from the code I read:**
- **Ports.** `normalize_host` (moderation.py:44-68) goes through `urlparse(...).hostname`, so it **drops ports**. But `instance_domain` is stored the crawler's way, by `normalize_host_token`, which keeps the port on a bare `host:port` (DATA_BUILD.md:151-153). So `v1@a.example:8443` and `v1@a.example` get the same id, and the trigger aborts the write as a "collision". The same goes for case and trailing-dot variants. AC1 mandates `normalize_host`, so this is a semantic choice, but it should be stated, and an AC1 test should pin it.
- **Empty or invalid hosts.** `normalize_host` returns None for "" or for whitespace hosts. Concatenating None raises TypeError, which inside a SQL function surfaces as an opaque "user-defined function raised exception". The helper needs an explicit policy: raise a named error, or fall back to the raw value.
- **Statement order.** The shared DDL must be split, or the table created first, then the old-shape check, then the index and trigger. `CREATE TABLE IF NOT EXISTS` is a no-op on an old table, and a following `CREATE UNIQUE INDEX ... (ann_id)` raises `OperationalError: no such column: ann_id` before any friendly message (see the sync-whitelist and build-video-embeddings entries).
- **Index name.** It must not be `idx_video_embeddings_id_instance`, which `ensure_video_indexes` drops on every Engine start (videos.py:28).
- **Check is schema-aware.** The check must take a schema argument (`PRAGMA stage.table_info(...)`) for merge's attached `stage`.
- **Trigger shape.** The trigger body must use unqualified table names, as SQLite requires for non-TEMP triggers. It must also compare `video_id`/`instance_domain` so a same-key replace passes.
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host (consumed, not changed)">
**What changes:** no code change. It becomes an input to every `ann_id`.

**What depends on it:**
- `ann_ids.py`;
- the existing purge, filter and CLI paths;
- `test_host_normalisation.py` (tests/config.json:108), which maps this file.

**Regression risk:** a future edit to `normalize_host` silently changes every derived id, and with it every stored `ann_id` and index id. Ids would then no longer match newly computed ones, so sync-computed ids and re-embeds would diverge from stored ones. Worth a comment or a pinned-value test (the AC1 fixed known value covers this). It strips ports, as noted under `ann_ids.py`.
</impact>
<impact path="engine/server/data/embedding_space.py" element="assert_index_matches_embeddings (AC5 id_source gate)">
**What changes:** add a check that `meta.get("id_source") == "video_embeddings.ann_id"`, next to the model check, with a message naming `build-ann-index.py`.

**What depends on it:**
- `server.py:365`, at Engine start;
- `precompute-similar-ann.py:345`;
- `tests/active/test_precompute_similar_ann.py:74`. It writes a sidecar of only `{"model_name","embedding_dim"}`, so after this change every precompute test in that file is refused. That file is not in the plan's churn list.

**Regression risk:** this is a hard cutover. Every environment's index must be rebuilt, including the worktree's symlinked shared index (see `scripts/worktree-setup.sh`).

**Message chain:** against an unmigrated DB with a rowid index, the Engine says "rebuild with `build-ann-index.py`". `build-ann-index` then says "run `migrate-whitelist.py`". Consider naming both in the Engine message.
</impact>
<impact path="engine/server/data/embeddings.py" element="resolve_seed, _fetch_seed_by_uuid, _fetch_seed_by_id, fetch_seed_embeddings_for_likes, _seed_from_row">
**What changes:**
- `e.rowid AS rowid` becomes `e.ann_id` in three SQL sites: lines 123, 151, and 217/241 (the likes batch has two queries, so four SELECTs in all).
- `_seed_from_row` sets the seed's `ann_id` key.
- `resolve_seed`'s `exclude_rowid`/`rowid` keys are renamed, in four return dicts (lines 73, 79, 86, 89-91).

**What depends on it:**
- `ann.compute_similar_items` (`seed["rowid"]`, a hard KeyError if only one side is renamed);
- `ann.search_similar_above` (`seed.get("rowid")`: a silent None if mismatched, so the seed is no longer excluded from its own up-next);
- `similar._handle_vector_search` (`seed["exclude_rowid"]`);
- `similarity_candidates._seed_with_embedding` (spreads the seed);
- `recommendations/sources/ann_similar_from_likes.py` and `cached_similar_from_likes.py` (`seed_map`);
- `internal_client_reads.py:107` (`fetch_seed_embedding`; it does not expose the id).

`fetch_embeddings_by_ids` is unaffected.

**Regression risk:**
- Every fixture that builds its own `video_embeddings` without `ann_id` and reaches these queries breaks with "no such column". `test_internal_client_reads.py:133` is one.
- A partial rename silently re-admits the seed into its own similar list.
</impact>
<impact path="engine/server/data/ann.py" element="compute_similar_items, search_similar_above, search_index (exclude_rowid)">
**What changes:**
- Variable and parameter names move from rowid to ann_id.
- `seed["rowid"]` becomes the new key, at lines 62 and 112.
- `search_index`'s `exclude_rowid` parameter is renamed. It is positional at both call sites, so a rename does not break callers.
- The `> 0` and `< 0` filters stay valid: real ids are ≥ 1, and FAISS uses -1.
- `fetch_metadata` is called with ann_ids.
- The nprobe helpers stay unchanged.

**What depends on it:**
- `similarity_candidates.py:163-171` (lazy import of `search_similar_above`) and `:403` (`compute_similar_items`);
- `search.py:191` and `similar.py:988` (`search_index`);
- `test_similarity_candidates.py`, which stubs `data.ann` in `sys.modules` (unaffected).

**Regression risk:** the ids are 63-bit numpy int64 values. `int()` conversion is fine, and no id reaches JSON (verified: items carry only `video_id`, `instance_domain` and `score`).
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata">
**What changes:**
- `e.rowid AS rowid` becomes `e.ann_id`.
- `WHERE e.ann_id IN (...)` uses the UNIQUE index.
- The result is keyed by `int(row["ann_id"])`.
- The parameter name and docstring are updated.

The output dicts never include the id, so the response shape is unchanged. `fetch_metadata_by_ids`/`_by_uuids`/`_select_pairs` are unchanged.

**What depends on it:**
- `ann.py` (2 calls);
- `random_videos.fetch_random_rows_from_cache` (line 441);
- `search.vector_candidates` (line 197);
- `similar._handle_vector_search` (line 996);
- `tests/active/test_metadata.py`: its own 5-column tables (lines 91 and 196) and line 212 `SELECT rowid FROM video_embeddings` feeding `fetch_metadata`. It must move to `ann_id`.

**Regression risk:** without the UNIQUE index (old DB) `IN (...)` becomes a full scan. A cheap gate or the migration guarantees the index. Every fixture DB used through this path needs an `ann_id` column.
</impact>
<impact path="engine/server/data/search.py" element="vector_candidates (search_index + fetch_metadata by ann_id); VIDEO_ROW_SQL v.rowid unchanged">
**What changes:**
- In `vector_candidates`, the local `rowids` becomes ann_ids (lines 191-205).
- `VIDEO_ROW_SQL`'s `v.rowid AS rowid` (line 52) and the `videos_fts` join (line 158) are the FTS external-content link and must NOT change.

**What depends on it:**
- the `fuse_by_rank` callers;
- `tests/active/test_search.py`. It runs with no query encoder, so the vector half returns early and its 5-column `video_embeddings` fixture keeps working (no churn needed, but it does not cover the ann_id path).

**Regression risk:** low. A careless global rename of "rowid" in this file would break FTS.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_vector_search (lines 963-1022)">
**What changes:**
- `seed["exclude_rowid"]` takes the new key name.
- Local `rowids` is renamed.
- `fetch_metadata` is called by ann_id.

`resolve_seed` is used at line 1085, and the seed's `meta` is what gets serialized (lines 940, 958, 1021), so the id stays out of JSON.

**What depends on it:** the raw-vector and seeded-vector search routes, and `tests/active/test_video.py`. That file's `similars_stack` (lines 216-218) builds a FAISS index from `SELECT rowid ... FROM video_embeddings`, and its fixture (lines 533-544) uses `sync_job.ensure_content_schema` plus positional `INSERT INTO video_embeddings VALUES (6 values)`. The new 7-column shape breaks that insert ("table has 7 columns but 6 values supplied"), and the index ids must become ann_ids. `test_video.py` is NOT in the plan's 9-file churn list.

**Regression risk:** a KeyError on a partial rename.
</impact>
<impact path="engine/server/data/random_cache.py" element="RANDOM_CACHE_CHECK_SQL, ensure_random_cache_schema, random_rowids_count, populate_random_cache (unfiltered and filtered scans), fetch_random_rowids, open_random_cache_if_usable">
**What changes:**
- The table becomes `random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)`.
- `RANDOM_CACHE_CHECK_SQL` (line 19) and the count helper's `sqlite_master` name check (line 46) are renamed, and the helper itself is renamed.
- `populate_random_cache` changes:
  - `MIN/MAX(rowid)` becomes `MIN/MAX(ann_id)`;
  - `random.randint` spans a 63-bit range (fine in Python);
  - both window queries (lines 92 and 97) become `WHERE ann_id >= ? ORDER BY ann_id`;
  - the filtered `scan_range` (lines 145-163) uses `e.ann_id` with `current = last + 1`;
  - inserts at lines 102 and 190 use the new table.
- `fetch_random_rowids` is renamed or returns ann_ids (line 341).
- The `open_random_cache_if_usable` logic is unchanged: an old file yields `no_table`.

**What depends on it:**
- `random_videos.py:10/434`;
- `precompute-random-rowids.py:16/69`;
- `server.py:106/344-345`;
- `tests/active/test_random_cache.py`: `_source_db` (lines 134-137) has no `ann_id`, and `_seed_cache`/`_cache_rows` and line 295 hard-code `random_rowids`/`video_rowid`. The Engine tests at lines 196 and 234 map rows through `SELECT e.rowid`, and their expectations assert "source rowids 1..20".
- `tests/active/test_db.py` (`CHECK_SQL` line 155, `_source_db` line 165, `_seed_cache` line 177, `fetch_random_rowids` line 34);
- `tests/active/test_random_videos.py` (lines 491-492, 505-512).
None of these is in the plan's churn list except `test_random_videos`.

**Regression risk:**
- With hashed ids, "positions 1..20 over source rowids 1..20" expectations no longer hold.
- The filtered scan over a 63-bit sparse range relies on the UNIQUE index for `ORDER BY ann_id`. Without it (an old DB opened by the random-cache worker) it is a full sort per chunk. The startup build reads `whitelist.db` read-only, so a missing index shows up as slowness, not as an error.
- During a blue/green overlap, the old instance's periodic build can rename a `random_rowids`-shaped file over the path. The new instance keeps its open handle, so the effect is only a rebuild on its next restart.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_random_rows_from_cache (lines 421-448) and its import of fetch_random_rowids">
**What changes:**
- Follow the random_cache rename: the import at line 10 and the call at line 434.
- `seen`/`fresh` hold ann_ids, and `metadata.get(ann_id)` is used.
- The docstring changes from "precomputed rowid cache" and "unseen rowid".
- The DB-draw functions (lines 91, 179, 277 and 371 join on `video_id`/`instance_domain`) are unaffected.

AC6 lists this file, but the plan's AC6 approach text names only `random_cache.py`.

**What depends on it:** the `random=1` feed, and `tests/active/test_random_videos.py`:
- lines 470-492 store `lastrowid` as the cache value;
- lines 505-512 monkeypatch `random_videos.fetch_random_rowids` by name, so a rename must be mirrored.

The `_feed_db` fixture (lines 113-135) copies real rows by `CREATE TABLE AS SELECT *` and then duplicates T as T2 under another host, which gives T2 T's `ann_id` (no constraint on a CTAS table). Harmless for the order tests, which never read `ann_id`, but stale if ever reused.

**Regression risk:** if the monkeypatch target name changes without the test, it raises AttributeError.
</impact>
<impact path="engine/server/api/server.py" element="startup: open_random_cache_if_usable (line 344), random_cache_startup_build (line 345), assert_index_matches_embeddings (line 365)">
**What changes:** probably none. It may need an import rename if `random_cache` names change (line 106 imports only `open_random_cache_if_usable` and `run_random_cache_worker`).

**What depends on it:** every Engine start, including the session `engine` fixture in `tests/active/conftest.py:107-146` and `test_random_cache.py`'s `CACHE_VARIANT_RUNNER`. Both start the real Engine on the repo's `engine/server/db/whitelist.db` and FAISS index.

**Regression risk (high):** after AC5 the Engine refuses to start until the index sidecar says `ann_id`. Every Engine-backed active test then fails at fixture setup unless the dataset is migrated and the index rebuilt (see `scripts/worktree-setup.sh`).
</impact>
<impact path="engine/server/api/server_config.py" element="comment on DEFAULT_RANDOM_CACHE_SIZE (line 352)">
**What changes:** the comment "Precomputed random rowids stored..." becomes ann_ids. It is cosmetic.

**What depends on it:** nothing functional. `test_server_config.py` and `test_random_cache.py` read constants, not comments.

**Regression risk:** none.
</impact>
<impact path="engine/server/data/videos.py" element="ensure_video_indexes (drops idx_video_embeddings_id_instance on every Engine start)">
**What changes:** none.

**What depends on it:** the new UNIQUE index's name. If it were ever named `idx_video_embeddings_id_instance`, every Engine start would drop it. That would disable the collision guarantee, since UPDATE collisions are caught by the index, and slow `fetch_metadata`. `tests/active/test_videos.py` asserts the exact `idx_%` set on its own fixture, so it is unaffected unless that fixture adopts the shared DDL.

**Regression risk:** name choice only.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="_compute_candidates, get_upnext_candidates → search_similar_above, _seed_with_embedding">
**What changes:** none expected. It passes seed dicts (from `resolve_seed` or `fetch_seed_embeddings_for_likes`) through to `ann.compute_similar_items` and `search_similar_above`.

**What depends on it:** the seed key rename must be consistent end to end. `tests/active/test_similarity_candidates.py` uses its own 5-column `video_embeddings` and stubs `data.ann`, so it is unaffected as long as no `fetch_metadata` call is added here.

**Regression risk:** a silent loss of self-exclusion if the seed key name diverges.
</impact>
<impact path="engine/server/api/recommendations/sources/ann_similar_from_likes.py" element="seed_map from fetch_seed_embeddings_for_likes → get_similar_candidates">
**What changes:** none in code. The same applies to `cached_similar_from_likes.py`, which has the same pattern.

**What depends on it:** the seed dicts now carry the renamed id key, consumed by `ann.compute_similar_items` (`seed["<key>"]`, a hard index).

**Regression risk:** a KeyError in the like-based recommendations path if producer and consumer are not renamed together.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="video-seed handler (fetch_seed_embedding at line 107)">
**What changes:** none in code. The query underneath now selects `e.ann_id`, and the response exposes only `video_id`, `uuid`, `host`, `channel` and `title` (lines 113-126).

**What depends on it:** `tests/active/test_internal_client_reads.py`. Its fixture (line 133) creates `video_embeddings` without `ann_id` and inserts positionally (line 110), so the handler would raise "no such column: e.ann_id". It is in the plan's churn list.

**Regression risk:** test churn only.
</impact>
<impact path="engine/server/db/jobs/build-video-embeddings.py" element="init_schema, the per-batch INSERT OR REPLACE tuple, the old-shape guard call">
**What changes:**
- `init_schema` (lines 62-78) creates the table from the shared DDL.
- The guard is called after table creation.
- Each row in `rows_to_insert` (lines 256-277) gains `ann_id` from the helper, and the column list is extended.
- `--force`'s DELETE (line 177) then reinserts with the same ids.

**What depends on it:**
- `updater-worker.py:1294-1308` creates the staging table through this script. `engine/crawler/schema.sql` has no `video_embeddings`.
- `scripts/run-dataset-build.sh:236`.
- `run-reembed.sh`.

**Regression risk (high):** on a resumed pre-cutover staging DB, or an unmigrated whitelist.db, `CREATE TABLE IF NOT EXISTS` is a no-op. If `init_schema` then runs the UNIQUE index or trigger DDL before the guard, it fails with a raw "no such column: ann_id" instead of the AC2 message. Order: table, then guard, then index and trigger.

`server_dir` is already on `sys.path` (lines 11-14), so `data.ann_ids` imports cleanly.
</impact>
<impact path="engine/server/db/jobs/merge-staging-db.py" element="main(): old-shape guard on main and stage before BEGIN IMMEDIATE (the one operator-approved change)">
**What changes:** call the helper's check for `main.video_embeddings` and `stage.video_embeddings` before line 124. This needs a schema-aware check. The import works because `server_dir` is on `sys.path` (lines 14-17). Merge logic is unchanged: `merge_columns` (line 152) is the shared columns, so `ann_id` is copied from staging, and `INSERT OR REPLACE` (lines 167-171) fires main's BEFORE INSERT trigger per row.

**What depends on it:**
- `updater-worker.py:1350-1362`;
- `test-orchestrator-smoke.py`;
- the new merge-path collision test.

**Regression risk:**
- If the guard is missed: when stage lacks `ann_id`, `merge_columns` silently omits it and the insert fails only on NOT NULL with a generic message. When prod lacks it, rows are written without `ann_id`.
- On a collision, the trigger ABORT raises inside the transaction; the except at line 203 rolls back, and `finally` detaches. Good. The updater's `finally` still restarts the Engine on the old index (a miss, not a wrong video).
- `PRAGMA foreign_keys = ON` is unchanged.
</impact>
<impact path="engine/server/db/jobs/merge_rules.json" element="video_embeddings rule (INSERT_OR_REPLACE, keys video_id/instance_domain)">
**What changes:** none; the plan keeps `INSERT_OR_REPLACE`.

**What depends on it:**
- merge;
- `test-orchestrator-smoke.validate_outputs` (lines 777-843), which checks duplicate key groups and replace mismatches over shared columns. `ann_id` is now among those columns, which is fine because same key gives same id.

**Regression risk:** none, provided nobody switches to UPSERT without re-reviewing the trigger.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="EMBEDDING_COLUMNS split, ensure_content_schema video_embeddings DDL, ensure_schema_compatibility exact check, rebuild_content_tables embedding copy">
**What changes:**
- `EMBEDDING_COLUMNS` (lines 104-111) splits: the target list (+`ann_id`) feeds the exact check at line 194, and the source superset list keeps the 6 columns (line 499).
- `ensure_content_schema` (lines 385-394) uses the shared DDL.
- `rebuild_content_tables` (lines 493-510) copies `ann_id` when the source has it, and otherwise computes it via the registered function. That needs `create_function` on this connection before the INSERT.
- Imports `data.ann_ids` (`server_dir` is already on `sys.path`, lines 16-19).

**What depends on it:**
- `scripts/run-dataset-build.sh:228`;
- `test_whitelist_migrations.py`, `test_repair_video_channel_names.py` and `test_video.py`, which load this module via `spec_from_file_location` and call `ensure_content_schema`;
- `repair-video-channel-names.py`, which loads it for its FTS helpers.

**Regression risks:**
- **(high) Order in main().** `ensure_content_schema` runs before `ensure_schema_compatibility` (lines 598-599). On an old-shape whitelist.db, a `CREATE UNIQUE INDEX ... ON video_embeddings(ann_id)` inside `ensure_content_schema` raises "no such column: ann_id" before the friendly migrate message. The index and trigger must come after the exact check, or be skipped when the column is absent.
- **Trigger cost.** Firing on the 890k-row reload adds one index probe per row.
- **Computed ids.** Computed ids go through `normalize_host`, which strips ports; see `ann_ids.py`.
- **Test fixture.** `test_video.py:543-544` positional inserts break on the 7-column shape.
</impact>
<impact path="engine/server/db/jobs/whitelist_migrations.py" element="new migrate_video_embeddings_schema; migrate_whitelist_schema calls it last; migrate_videos_schema drop (line 268) unchanged">
**What changes:**
- New function: returns when the table is missing or already has `ann_id`; otherwise registers the function, creates `video_embeddings_new`, copies with computed ids, drops and renames, then creates the index and trigger IF NOT EXISTS.
- `migrate_whitelist_schema` (lines 390-395) appends the call.
- New import of `data.ann_ids`. The module itself is imported as `server.db.jobs.whitelist_migrations` by `migrate-whitelist.py:21`, which puts both `server_dir` and `engine_dir` on `sys.path`.

**What depends on it:**
- `migrate-whitelist.py`;
- `tests/active/test_whitelist_migrations.py`. It loads `whitelist_migrations.py` by file path WITHOUT adding `server_dir`, and works only because it loads `sync-whitelist.py` first (line 79), which inserts `server_dir`. The order dependency should be kept, or the test should add the path. Its fixture now creates a new-shape table through `ensure_content_schema`, so the new migration is a no-op there; the new backfill test needs an old-shape table.

**Regression risks (high):**
- **Not atomic.** The existing pattern runs `executescript`, which COMMITs first and runs each statement in autocommit. If the UNIQUE index creation fails on a backfill collision or id 0 (the CHECK fails during the INSERT), the table may already be renamed with `ann_id` but without index and trigger. The early return ("already has `ann_id`") then never repairs it on rerun. Wrap the rebuild in an explicit BEGIN/COMMIT, or have the idempotent path still ensure the index and trigger IF NOT EXISTS.
- **Disk.** The rebuild writes about 1.4 GB of blobs. The freed pages are not returned without VACUUM.
</impact>
<impact path="engine/server/db/jobs/migrate-whitelist.py" element="main(): backup then migrate_whitelist_schema inside `with conn:`">
**What changes:** no code change is required. It now performs the `video_embeddings` table rebuild.

**What depends on it:** operators (the AC9 runbooks).

**Regression risk:**
- The default backup does `path.read_bytes()` (line 60), loading the whole whitelist.db (about 3.5 GB per DATA_BUILD.md:319) into RAM, and writes a full copy. Free space needed is therefore about 3.5 GB of backup plus about 1.4 GB of rebuild, more than the 1.4 GB the plan states.
- `with conn:` around `executescript` gives no atomicity (see `whitelist_migrations`).
- With symlinked worktree data, running it from a worktree migrates the shared main dataset.
</impact>
<impact path="engine/server/db/jobs/build-ann-index.py" element="EmbeddingRow.rowid, iter_embeddings, add query (line 250), add_with_ids ids (line 252), sidecar id_source (line 284), old-shape guard; fetch_training_samples keeps rowid % step">
**What changes:**
- Select `ann_id, embedding, embedding_dim`.
- The `EmbeddingRow` field is renamed and the positional unpacking at line 52 updated.
- `id_source` becomes `"video_embeddings.ann_id"`.
- The guard is called before sampling.
- `import data.ann_ids`; `server_dir` is on `sys.path` (lines 15-18).
- `fetch_training_samples` (lines 73-81) keeps `rowid % step`. That is fine as a sampling cursor, but it is the one deliberate rowid read left.

**What depends on it:**
- `updater-worker` step 11;
- `run-dataset-build.sh:244`;
- `test-orchestrator-smoke.validate_outputs` (meta total; it should also assert `id_source`);
- the Engine and precompute gates.

**Regression risk:** none functional. `--meta-path` is separate from `--index-path`, but `assert_index_matches_embeddings` reads `<index>.json`, so a custom `--meta-path` that does not match produces a "metadata missing" refusal. That is pre-existing.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="iter_embedding_rows_by_rowids, fetch_similarity_targets, fetch_similarity_targets_chunked, pending selection queries (lines 371-395), full scan (lines 402-407), main loop self-exclusion (lines 426-442)">
**What changes:** every `rowid` select, filter and key becomes `ann_id`, and `row["rowid"]` becomes `row["ann_id"]`. Function names change or keep their names. Output keys stay `(video_id, instance_domain)`. Its local `set_nprobe` copy is unchanged.

**What depends on it:**
- `updater-worker.run_similarity_stage`;
- `run-dataset-build.sh:253`;
- `tests/active/test_precompute_similar_ann.py`. Its source fixture (lines 65-68) has no `ann_id` column. `INDEX_BUILDER` (lines 50-54) adds vectors by rowid, and the sidecar (line 74) lacks `id_source`. After the change every test except the argparse refusals fails, both on the gate and on "no such column". Its hand-computed `TOP2` expectations are keyed by label, so they survive once the fixture carries real `ann_id`s. Not in the plan's churn list.

**Regression risk:**
- A partial rename makes the self-exclusion fail silently, so a video lists itself as its own top similar.
- There is no old-shape guard in this job. Against an unmigrated DB the AC5 gate fires first on the rowid sidecar, which is acceptable.
</impact>
<impact path="engine/server/db/jobs/precompute-random-rowids.py" element="help text and random_rowids_count import">
**What changes:**
- The argparse description (line 23) and the `--size` help "Rowids to sample." (line 34) are updated.
- The import and call at lines 16 and 69 follow the count-helper rename.
- The keep check now counts 0 on an old-shape `--out`, so it rebuilds. The file name and arguments are unchanged.

**What depends on it:**
- `scripts/run-dataset-build.sh:262`;
- DATA_BUILD.md §6;
- `tests/active/test_precompute_random_rowids.py`. Its `_source_db` (line 31) has no `ann_id`, and lines 43-53 hard-code `random_rowids`/`video_rowid`. Not in the plan's churn list.

**Regression risk:** test churn. This module also does `sys.path.append` rather than `insert` (line 11). That is pre-existing; no conflict found.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="inject_replace_embedding_for_test (lines 1018-1068); init_staging_db and --resume-staging (lines 838-856, 1166-1173); finally-restart semantics">
**What changes:** the inject reads `video_id`/`instance_domain` from prod and writes `ann_id` from the helper. It could also copy prod's `ann_id`, which gives the same value. `server_dir` is already on `sys.path` (lines 24-27), and `data.*` is already imported, so the plan's "two-line insert" risk does not apply.

**What depends on it:**
- `test-orchestrator-smoke.py:1010` (`--inject-replace-embedding-for-test`, `expect_replace_overlap`);
- `tests/active/test_updater_worker.py` (stubs commands; only checks the `build-ann-index.py` name).

**Regression risk:**
- A `--resume-staging` staging DB from before the cutover now fails in `build-video-embeddings` with the AC2 message, which is intended.
- After cutover, a failed ANN build restarts the Engine on the previous ann_id index: misses only.
- If prod is not migrated before the first updater run on new code, merge fails, and the `finally` restart brings the Engine up on whatever index exists. With an old rowid sidecar, the Engine then refuses to start, which is an outage until migrate plus rebuild. This belongs in the runbook.
- `count_staging_deltas` and `seed_staging_from_prod` are unaffected.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="copy_and_prune_prod / create_table_and_indexes_from_source (lines 199-341), validate_outputs (lines 744-845)">
**What changes:**
- Assert the sidecar's `id_source == "video_embeddings.ann_id"`.
- Seed fixtures must carry `ann_id`.

`create_table_and_indexes_from_source` copies the table DDL and its indexes from the source DB, but NOT its triggers (`type='index'` only, line 215). The mini prod therefore lacks the collision trigger unless the test also copies `type='trigger'` or calls the helper's DDL. `INSERT INTO video_embeddings SELECT e.*` (line 330) relies on identical column order, which holds when the source DDL is copied.

**What depends on it:** AC9 evidence.

**Regression risk:**
- The default `--source-db` is the repo's whitelist.db, the symlinked shared one. It must be migrated, or the mini prod is old-shape and the merge guard aborts the run.
- The mismatch checks compare all shared columns, now including `ann_id` (fine).
</impact>
<impact path="engine/server/db/jobs/tests/test-moderation-integration.py" element="ensure_main_schema video_embeddings (lines 166-174), seed inserts (lines 361-378, 774-787), prod-sample select (lines 583-595)">
**What changes:** possibly none. It defines its own minimal `video_embeddings` (no `ann_id`) and exercises only purge and serving moderation, none of the `ann_id` readers or writers. The plan lists it as churn and says it should "import the helper directly". I could not find a code path in it that needs `ann_id`. Uncertain: changing it would be for consistency only.

**Regression risk:** low. If it is switched to the shared DDL, its positional 6-tuple inserts must add `ann_id`.
</impact>
<impact path="tests/active/conftest.py" element="session `engine` fixture, `dataset` fixture, WHITELIST_DB, plus the new shared ann_id fixture helper">
**What changes:** a shared helper that computes `ann_id` for fixtures, re-exporting `data.ann_ids.ann_id`. The conftest itself only reads `video_embeddings` by key (line 218).

**What depends on it:** every Engine-backed active test:
- `test_blocks`, `test_dislike_profile`, `test_dislikes`, `test_frontend_reactions` and `test_profiles` only SELECT by `(video_id, instance_domain)` and `v.rowid` from the live dataset. They need no insert churn, despite being on the plan's list, but they need the session Engine to start;
- `test_random_cache`'s Engine variants.

**Regression risk (high):** the session Engine starts on `engine/server/db/whitelist.db` and the shared FAISS index. Under AC5 it refuses an un-rebuilt index, so the whole Engine-backed suite errors at setup unless the dataset in the worktree is migrated and re-indexed.
</impact>
<impact path="tests/active/test_metadata.py" element="fixtures at lines 72, 91, 196, 205; _nsfw_metadata at lines 212-213 (SELECT rowid → fetch_metadata)">
**What changes:** the fixture tables gain `ann_id`, the inserts write it through the helper, and line 212 selects `ann_id`.

**What depends on it:** the AC6 metadata contract.

**Regression risk:** none beyond churn. The `fetch_metadata_by_*` tests are unaffected.
</impact>
<impact path="tests/active/test_internal_client_reads.py" element="db_path fixture (line 133) and _add insert (line 110)">
**What changes:** add `ann_id` to the table and the insert.

**What depends on it:** the `/internal/*` seed and metadata handlers through `fetch_seed_embedding`.

**Regression risk:** none beyond churn.
</impact>
<impact path="tests/active/test_random_videos.py" element="_video_db NSFW cache fixture (lines 462-492), counting_fetch monkeypatch (lines 505-512), _feed_db CTAS copy (lines 113-135)">
**What changes:**
- The cache fixture stores `ann_id`s in `random_ann_ids` instead of `lastrowid` in `random_rowids`.
- The monkeypatch target follows any rename of `fetch_random_rowids`.
- `NSFW_EMBEDDINGS_TABLE` (line 372) gains `ann_id`.
- `_feed_db` is unaffected functionally (order tests).

**What depends on it:** the random-cache NSFW redraw tests.

**Regression risk:** a name mismatch gives AttributeError at monkeypatch.
</impact>
<impact path="tests/active/test_random_cache.py" element="_source_db, _seed_cache, _cache_rows, _seed_servable_cache (line 196), _feed_rowids (line 234), populate tests (lines 289-320+), docstring expectations">
**What changes:**
- The sources gain `ann_id`.
- The cache table and column names change.
- The Engine-variant tests map feed rows to `ann_id` instead of rowid.
- The "positions 1..20 over source rowids 1..20" expectations need ann_id-based expectations.

Not in the plan's 9-file list, though the plan's risks mention random-cache tests.

**What depends on it:** `RANDOM_CACHE_DB`, the worktree's private copy of `random-cache.db`, which is old-shape. After the change any Engine start treats it as `no_table` and rebuilds.

**Regression risk:** large churn. The Engine-variant tests depend on the migrated dataset.
</impact>
<impact path="tests/active/test_db.py" element="random cache fixtures (lines 155-194): CHECK_SQL, _source_db, _seed_cache, fetch_random_rowids">
**What changes:**
- `CHECK_SQL` names the new table.
- The source gains `ann_id`.
- The seeded cache uses the new shape.

Not in the plan's churn list.

**What depends on it:** `swap_readonly_connection` and `build_random_cache` tests.

**Regression risk:** test-only.
</impact>
<impact path="tests/active/test_precompute_random_rowids.py" element="_source_db (line 31), _seed_cache/_rows (lines 43-53), expectations">
**What changes:** the source gains `ann_id`, the cache table and column are renamed, and the expectations shift from rowids 1..20 to the sources' `ann_id`s. Not in the plan's churn list.

**What depends on it:** AC6 (the keep check treats an old-shape `--out` as not kept); this is a natural home for that new test.

**Regression risk:** test-only.
</impact>
<impact path="tests/active/test_precompute_similar_ann.py" element="source fixture (lines 59-75), INDEX_BUILDER (lines 46-56), sidecar JSON (line 74)">
**What changes:** add an `ann_id` column filled by the helper, build the FAISS index on `ann_id`, and write `id_source: "video_embeddings.ann_id"` in the sidecar. `_source_db` (line 81) is only for argparse refusals, which exit before reading. Not in the plan's churn list.

**What depends on it:** the AC7 regression coverage.

**Regression risk:** without it, the whole file fails under AC5.
</impact>
<impact path="tests/active/test_video.py" element="similars_stack (lines 215-223) and the fixture at lines 533-544">
**What changes:**
- The index is built from `ann_id`.
- The positional `INSERT INTO video_embeddings VALUES ('v1', ?, ?, 4, 'm', 'now')` against the `ensure_content_schema` table must name its columns and supply `ann_id`, or it fails on the 7-column shape.

Not in the plan's churn list.

**What depends on it:** `/api/video` and the similars tests.

**Regression risk:** a sure failure if missed.
</impact>
<impact path="tests/active/test_whitelist_migrations.py" element="_load_job order (lines 79-80) and new AC2 migration tests">
**What changes:** new tests:
- backfill on an old-shape table;
- idempotence;
- the UNIQUE index;
- the trigger;
- recovery when the table already has `ann_id` but no index.

The existing test stays valid: the new-shape table makes the new migration a no-op.

**What depends on it:** `whitelist_migrations` importing `data.ann_ids`, which needs `server_dir` on `sys.path`. Today that is satisfied only because `sync-whitelist.py` is loaded first.

**Regression risk:** a new test that loads `whitelist_migrations.py` alone gets ModuleNotFoundError: data.
</impact>
<impact path="tests/active/test_repair_video_channel_names.py" element="sync_job.ensure_content_schema fixtures (lines 70, 134)">
**What changes:** none expected. It creates the content tables, including the new `video_embeddings` shape, and never inserts embeddings.

**What depends on it:** `ensure_content_schema` must stay runnable on a fresh DB. A fresh table plus its index and trigger is fine.

**Regression risk:** low.
</impact>
<impact path="tests/active/test_search.py" element="_statements video_embeddings fixture (lines 40, 52)">
**What changes:** none needed. The vector half returns early with no encoder.

**Regression risk:** the AC6 `search.vector_candidates` change has no direct active coverage here. The AC8 job test is what exercises it.
</impact>
<impact path="tests/config.json" element="test_groups mapping">
**What changes:**
- Add `engine/server/data/ann_ids.py` to the groups of the tests that exercise it: metadata, internal_client_reads, random_cache, random_videos, precompute_*, whitelist_migrations, video, db.
- Add entries for any new test file (AC1/AC2/AC8).
- `test_whitelist_migrations.py` should also map to `migrate-whitelist.py`, and `test_precompute_similar_ann.py` already maps `embedding_space.py`.

**What depends on it:** test selection by `validate_tests.py`. `tests/last_test_validation.json` is a generated artifact and is regenerated.

**Regression risk:** stale mapping, so changed files skip their tests.
</impact>
<impact path="scripts/worktree-setup.sh" element="symlinks whitelist.db, similarity-cache.db, whitelist-video-embeddings.faiss(.json) to main; copies random-cache.db">
**What changes:** none planned.

**What depends on it:** this worktree. Its `engine/server/db/whitelist.db` and FAISS index are symlinks to main's shared files, which explains why they don't show in the Glob.

**Regression risk (highest):**
- Running `migrate-whitelist.py` or `build-ann-index.py` here rewrites MAIN's live dataset and index. Main's code would then serve an ann_id-built index: its `assert_index_matches_embeddings` does not check `id_source`, and it would look ids up as rowids. Ids of order 1e18 match no rowid, so main gets empty similar and search results. Other lanes break too.
- Not migrating leaves this worktree's Engine-backed tests unable to start.
- The build needs private copies of `whitelist.db` and the index for the worktree (replace the symlinks) before migrating. DATA_BUILD.md:179 already says shared-DB migrations run "on main after merge only, never from a worktree".
</impact>
<impact path="scripts/run-dataset-build.sh" element="sync, embeddings --force, index, random stages">
**What changes:** none required. Sync creates the new shape on a fresh DB, embeddings writes `ann_id`, the index records `ann_id`, and random builds the new table.

**What depends on it:** the full dataset build.

**Regression risk:** run against an EXISTING old-shape whitelist.db, the sync stage hits the `ensure_content_schema` order issue (raw "no such column") unless that is fixed. DATA_BUILD.md:166 already says to migrate before a scripted build. The `report_counts` and `check_tag_coverage` helpers are unaffected.
</impact>
<impact path="scripts/run-reembed.sh" element="model-space checks around the embeddings and index stages">
**What changes:** none. It reads only `model_name`/`embedding_dim` (lines 187-188) and calls the jobs.

**Regression risk:** none found. A re-embed (`--force`) now keeps ids, so a stale index during a re-embed returns old vectors for the right videos.
</impact>
<impact path="scripts/deploy-bluegreen.sh" element="readiness/rollback during the cutover">
**What changes:** none.

**What depends on it:** cutover sequencing.
- A deploy of the new code onto an un-migrated or un-reindexed prod fails readiness (the Engine refuses), and the deploy rolls back. That is safe.
- A rollback to old code AFTER migrate plus reindex starts an old Engine that accepts the ann_id sidecar (no `id_source` check) and resolves ids as rowids, so it returns empty similar and search results.
- During the overlap, both instances rebuild `random-cache.db` in different shapes.

**Regression risk:** operational only. It belongs in the DEPLOYMENT.md runbook.
</impact>
<impact path="engine/server/db/jobs/instance-denylist-cli.py" element="--purge-now (deletes host rows without ANN rebuild)">
**What changes:** none. It was one of the issue's three coupling-break sites (issue 08 triage). Purge is a DELETE, so the trigger (BEFORE INSERT) does not fire, and stale index ids for purged videos become misses.

**Regression risk:** none. It is covered by the AC8 host-purge test.
</impact>
<impact path="engine/server/db/jobs/inspect-embedding.py" element="SELECT ... FROM video_embeddings LIMIT ?">
**What changes:** none. It reads by explicit columns. It could optionally print `ann_id`.

**Regression risk:** none.
</impact>
</impacts>


### docs_checklist


<doc path="DATA_BUILD.md">
- Line 13: "random rowid cache" becomes "random ann_id cache".
- Line 166: the migration is no longer "additive... without touching rows". `migrate-whitelist.py` now rebuilds `video_embeddings` with `ann_id`. State the disk needs: about 1.4 GB for the rebuild plus the default backup, which copies the whole file (about 3.5 GB) and reads it into memory. Freed pages need VACUUM.
- Lines 168-172: the upgrade order gains the one-time cutover: stop the Engine, run `migrate-whitelist.py`, run `build-ann-index.py`, start the Engine. Run it on main or prod only, never from a worktree (symlinked shared DB, as line 179 already says for the repair job).
- Line 191: the repair follow-up can now point at this cutover.
- Line 232: "The index uses `video_embeddings.rowid` as ids" becomes `ann_id`, with the sidecar's `id_source` and the Engine's refusal of any other source. `build-ann-index.py` fails with a message naming `migrate-whitelist.py` on an old-shape DB.
- §3: `build-video-embeddings` writes `ann_id`, and refuses an old-shape table.
- §2: `sync-whitelist` copies or computes `ann_id`, and an old whitelist.db fails the exact check.
- §6 (line 290): "random rowid pool" becomes ann_id. A cache in the old `random_rowids` shape is rebuilt, not read.
- Line 335: `random_rowids` becomes `random_ann_ids`.
- Note that a collision aborts the write loudly, with manual recovery.
</doc>
<doc path="DEPLOYMENT.md">
- Line 42: extend the migrate note. Migration is now a hard cutover: stop the Engine, migrate, rebuild the index, then deploy or start.
- Triage table (around line 216): add rows for the Engine refusing an index whose `id_source` is not `video_embeddings.ann_id` (fix: `build-ann-index.py`), and for jobs failing with "no `ann_id` column" (fix: `migrate-whitelist.py`; for staging, rerun the updater without `--resume-staging`).
- Note that a rollback to pre-cutover code after reindex serves empty similars.
- Note that during the blue/green overlap, random-cache builds of two shapes may replace each other.
- Lines 66-67: file list unchanged.
</doc>
<doc path="engine/server/db/jobs/docs/UPDATER_WORKER.md">
- The one-time step before the first run on new code: migrate prod, then rebuild the index. Without it the merge fails with the `migrate-whitelist.py` message, and the `finally` restart refuses the rowid index.
- Lines 48 and 149-151: a `--resume-staging` DB from before the cutover fails loudly in `build-video-embeddings`; run once without `--resume-staging` to recreate it.
- Step 8: merge carries `ann_id` from staging, and a collision aborts the merge.
- Step 11: the index uses `ann_id`.
- Step 12: a failed ANN build now leaves an index that misses new videos but never returns wrong ones.
- Line 197: `--inject-replace-embedding-for-test` writes `ann_id`.
</doc>
<doc path="engine/server/api/recommendations/docs/LAYER_PARAMS.md">
- Line 130: "has no `random_rowids` table" becomes `random_ann_ids`. An old-shape file counts as having no table, so it is rebuilt.
- Line 140: "The cache holds only rowids (`random_rowids`)" becomes ann_ids (`random_ann_ids`); "a draw's rowids are resolved" becomes ann_ids.
- Mention that the unfiltered draw is now a hash-uniform window over `ann_id` order.
</doc>
<doc path="engine/server/api/recommendations/docs/OVERVIEW.md">
- Line 15: "drops rowids already seen ... unseen rowid" becomes ann_ids.
- Line 69: "prebuilt list of rowids" becomes ann_ids (`random_ann_ids`). Optionally note the build samples a window in `ann_id` order.
- Line 73: old-shape cache is treated as a missing table.
</doc>
<doc path="engine/server/README.md">
Line 9 and any start-up notes: the Engine needs a `whitelist.db` migrated by `migrate-whitelist.py` (now also `video_embeddings.ann_id`), and an index rebuilt by `build-ann-index.py`, or it refuses to start. Optional; only if the README lists start preconditions.
</doc>
<doc path="CONTEXT.md">
Line 12 already defines **ANN id** consistently. Check that it says the id is computed by `engine/server/data/ann_ids.py`. If ports are dropped by `normalize_host`, say so: "the normalised `instance_domain`" hides that two ports of one host share ids.
</doc>
<doc path="docs/project/adr/0006-derived-ann-ids.md">
- Optionally record the chosen collision mechanism: a BEFORE INSERT trigger plus `CHECK (ann_id > 0)` plus a UNIQUE index, rather than UPSERT.
- Record the consequence that `normalize_host` strips ports, so host:port variants of one host collide by construction.
- Decision 2 ("Readers never compute it") stays true; `sync-whitelist` computes it in SQL only as a writer.
</doc>
<doc path="docs/project/adr/0007-nsfw-filter-default-at-request-edge.md">
Line 27 says "The random cache stores only rowids and no flag". Under ADR conventions this historical record probably stays. If ADRs are kept current, it becomes "ann_ids". Low priority, uncertain.
</doc>
<doc path="docs/project/issues/08-stable-ann-ids.md">
At close: status becomes `enhancement, complete`, and the issue moves to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.
</doc>


### highest_risk


`scripts/worktree-setup.sh` / `tests/active/conftest.py` (with `engine/server/data/embedding_space.py`): this worktree's whitelist.db and FAISS index are symlinks to main's shared live files. AC5 makes every Engine start, including the session `engine` fixture and the `test_random_cache` Engine variants, refuse the current rowid index. Migrating or re-indexing from the worktree would rewrite main's dataset, and main's code (no `id_source` check) would then look 63-bit ids up as rowids and serve empty results. The build needs private worktree copies of the data before any migrate or reindex, or the Engine-backed suite cannot run.
`engine/server/db/jobs/whitelist_migrations.py` (`migrate_video_embeddings_schema`): the existing `executescript` rebuild pattern is not atomic. If the UNIQUE index or CHECK fails on a backfill collision or an id of 0 after the rename, the table is left with `ann_id` but no UNIQUE index or trigger. The planned early return ("already has `ann_id`") then never repairs it, so the collision guard is permanently missing on that DB.
`engine/server/db/jobs/sync-whitelist.py` + `engine/server/db/jobs/build-video-embeddings.py` (shared DDL order): `ensure_content_schema` and `init_schema` run before the old-shape checks. On an old table, `CREATE TABLE IF NOT EXISTS` is a no-op and the following `CREATE UNIQUE INDEX ... (ann_id)` or trigger raises a raw "no such column: ann_id". So AC2's required message naming `migrate-whitelist.py` (or "recreate staging") is never reached unless index and trigger creation come after the check. Also notable: `normalize_host` drops ports while stored hosts keep them, so host:port variants hash alike and trip the collision trigger.

## 2026-10-02 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

The plan holds. I opened the files behind the riskiest entries: `moderation.py`, `sync-whitelist.py`, `whitelist_migrations.py`, `migrate-whitelist.py`, `merge-staging-db.py`, `merge_rules.json`, `build-video-embeddings.py`, `build-ann-index.py`, `embedding_space.py`, `random_cache.py`, `server.py`, `videos.py`, `updater-worker.py`, the smoke test, the moderation integration test, `worktree-setup.sh`, `DATA_BUILD.md` and the active test fixtures. Every line-level claim I checked matched the file. The core mechanism is sound. The trigger is a plain-SQL BEFORE INSERT on `main.video_embeddings`, and `merge-staging-db.py:167-171` writes through `INSERT OR REPLACE INTO main.{table}`, so the trigger fires per row on every write path, including sync's bulk `INSERT ... SELECT` at `sync-whitelist.py:501-510` and the inject at `updater-worker.py:1044-1057`. The hard parts are already in the inventory: DDL order against old-shape tables, a migration that is not atomic, ports dropped by `normalize_host`, the shared data behind the worktree symlinks, and test churn well beyond the plan's 9 files. I found four things it does not carry. The Engine gate checks only the sidecar, never the DB. The runbook's bare `build-ann-index.py` writes to a path the Engine does not read. The merge guard would misreport a missing staging table. And `DATA_BUILD.md` states facts this change makes false.
<question id="1">Yes, provided the ordering fixes the inventory already lists are applied: table, then old-shape check, then index and trigger, in `init_schema`, in `ensure_content_schema` relative to `ensure_schema_compatibility`, and in the migration. I confirmed the ordering issue in the code. `sync-whitelist.py:598-599` runs `ensure_content_schema` before `ensure_schema_compatibility`, and `build-video-embeddings.py:62-78`'s `CREATE TABLE IF NOT EXISTS` does nothing on an old table. Two cases still fail in ways the plan does not intend. First, an old-shape `whitelist.db` paired with an `ann_id` sidecar passes AC5, because `assert_index_matches_embeddings` (`embedding_space.py:56-99`) reads only the sidecar. The Engine then starts, and every similar, search, seed and random-cache lookup raises "no such column: e.ann_id". This pairing is reachable: restoring the `.bak-` file that `migrate-whitelist.py:56-69` writes, after the index was rebuilt, produces it. Second, the one-time step "run `build-ann-index.py`" with default arguments writes `engine/server/db/video-embeddings.faiss` (`build-ann-index.py:129-130`). The Engine reads `whitelist-video-embeddings.faiss` (`server_config.py:415`), so it would still refuse to start on the old sidecar.</question>
<question id="2">Ramifications:
- Hard cutover in every environment: migrate the DB, rebuild the index, then start the Engine.
- The worktree's `whitelist.db` and index are symlinks to main's files (`worktree-setup.sh:27`). Migrating from the worktree would break main's serving: main does not check `id_source`, so it would look ann_ids up as rowids and return empty results.
- The random feed changes from a block of rows in insertion order to a sample that is uniform over the hash.
- The `random-cache.db` file is rebuilt on first start.
- The migration rewrites about 1.4 GB, and with the default backup needs about 3.5 GB more.
- `migrate-whitelist.py` stops being "additive, without touching rows", which `DATA_BUILD.md:166` currently promises.
- Rolling back to old code after the cutover serves empty similar and search results.
- Sync gains one indexed probe per row.</question>
<question id="3">Beyond what the inventory lists:
- The Engine must refuse an old-shape DB, not just an old sidecar.
- The runbook must pass the Engine's `--index-path` and `--meta-path` to `build-ann-index.py`.
- The schema-aware merge guard must report a missing table as missing, not as old-shape.
- `DATA_BUILD.md` lines 13, 166, 232, 290 and 335 must be corrected.

Already in the inventory, and required:
- split DDL order;
- a migration made atomic, or self-repairing on rerun;
- an explicit policy for hosts where `normalize_host` returns None;
- a UNIQUE index named anything other than `idx_video_embeddings_id_instance`;
- private worktree copies of the data before migrating;
- fixture updates in `test_precompute_similar_ann`, `test_video`, `test_random_cache`, `test_db`, `test_precompute_random_rowids` and `test_metadata`;
- `tests/config.json` mappings.</question>
<question id="4">Same video, same id:
- Ids survive merges, purges, sync reloads, `--force` re-embeds and migrations. A stale index can miss a video but never return the wrong one.
- A key that differs from another only by port, case or trailing dot now collides with it, and the write aborts. Before, both rows coexisted.

Index and caches:
- The index sidecar's `id_source` changes, and the Engine refuses an index built on rowids.
- The random cache table becomes `random_ann_ids`, and its draws are uniform over the hash, not blocks of rows in insertion order.

Unchanged:
- the API response shape (no id is exposed);
- the merge strategy;
- the similarity cache keys.</question>

New impacts:
engine/server/data/embedding_space.py: AC5 checks only the sidecar (lines 56-99, called at server.py:365). An old-shape whitelist.db paired with an ann_id sidecar passes, for example after the `.bak-` file from migrate-whitelist.py:56-69 is restored once the index has been rebuilt. The Engine then starts, and fetch_metadata, the seed queries and the random-cache build all raise "no such column: e.ann_id" at request time. The inventory's server.py and embedding_space.py entries cover only the sidecar direction.
engine/server/db/jobs/build-ann-index.py: the defaults at lines 129-130 write `engine/server/db/video-embeddings.faiss(.json)`, but the Engine reads `engine/server/db/whitelist-video-embeddings.faiss` (server_config.py:415). The plan's AC9 one-time step "run `build-ann-index.py`", if followed without arguments, leaves the old rowid sidecar in place and the Engine refuses to start. The runbook text must carry the `--index-path`/`--meta-path` flags shown at DATA_BUILD.md:237-241.
engine/server/db/jobs/merge-staging-db.py: on the updater's sync-join path with no new hosts but stale hosts (updater-worker.py:1189, 1320-1326), build-video-embeddings is skipped. The staging DB comes from the crawler schema, which has no video_embeddings (engine/crawler has no match), so staging lacks the table. Today the merge fails with "table missing in staging DB: video_embeddings" (line 139-140). A PRAGMA table_info check placed before BEGIN would find no columns and report "no ann_id column, run migrate-whitelist / recreate staging" instead, which sends the operator to the wrong fix for a failure that already exists today.
DATA_BUILD.md: line 166 says migrate-whitelist "is additive ... without touching rows ... a second run does nothing", which becomes false (it now rebuilds video_embeddings). Line 232 says "The index uses `video_embeddings.rowid` as ids". Lines 13 and 290 describe a "random rowid cache". Line 335's check command queries `random_rowids`, which will say "no such table" on a new cache. The plan's AC9 adds only the one-time step to DATA_BUILD.md, and the inventory has no entry for this file.
docs/project/adr/0007-nsfw-filter-default-at-request-edge.md: line 27 says "The random cache stores only rowids". This becomes stale wording in an accepted ADR. It is documentation only; leave it as historical or add a one-line note pointing to ADR-0006.

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Call the `ann_ids` old-shape check on `db` at Engine start in `server.py`, next to `resolve_embedding_space` (around line 346). It changes one line in `server.py` plus one test, adds one PRAGMA at start, and turns the restored-backup case from per-request errors into a refusal to start that names `migrate-whitelist.py`. It goes slightly beyond AC5's stated scope (a sidecar check) but does not contradict it. If the operator prefers not to touch `server.py`, the alternative is to document the pairing in the DEPLOYMENT.md rollback notes, which costs nothing but leaves the failure possible.
2. Write the AC9 one-time step with explicit paths: `build-ann-index.py --db-path engine/server/db/whitelist.db --index-path engine/server/db/whitelist-video-embeddings.faiss --meta-path engine/server/db/whitelist-video-embeddings.faiss.json --normalize --gpu|--cpu`. This is a documentation change only, and it prevents an outage during the cutover.
3. Make the old-shape check report a missing table distinctly: return without raising, or raise "table missing", and let merge's existing check speak. This adds about 2 lines to `ann_ids.py`. It keeps the stale-only sync-join failure that already exists correctly labelled and does not widen the operator-approved merge change.
4. Add `DATA_BUILD.md` lines 13, 166, 232, 290 and 335 to the AC9 doc edits, and note that the migration now rewrites video_embeddings and needs the stopped Engine and free space. This costs a few doc lines and keeps the runbook's verification command working.
5. From the inventory, and worth acting on, in priority order:
   - DDL split order: table, then check, then index and trigger.
   - Wrap `migrate_video_embeddings_schema` in an explicit BEGIN/COMMIT (not `executescript`), or have its early return still create the index and trigger IF NOT EXISTS.
   - A named-error policy when `normalize_host` returns None.
   - A pinned AC1 test that covers a port-bearing host.
   - Private worktree copies of `whitelist.db` and the index before migrating.
   - Widen the test plan to the 6 unlisted active test files and the `tests/config.json` mappings.
   The cost is mostly test churn, which is already implied.
6. Optional: `migrate-whitelist`'s backup reads the whole DB into RAM (`read_bytes`, about 3.5 GB). Telling operators to run with `--no-backup` after their own `sqlite3 .backup`, or stating the RAM and disk need in the runbook, costs one doc line. Changing the backup code would fall outside the plan.

## 2026-10-02 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impacts>
<impact path="engine/server/data/ann_ids.py" element="new module: id function, SQL registration, shared video_embeddings definition (CHECK, UNIQUE index, BEFORE INSERT collision trigger), old-shape check">
New file, modelled on `data/moderation.py` (stdlib only, `from __future__ import annotations`, one-line docstrings).

Contents:
- The pure id function.
- A `register_*(conn)` wrapper over `conn.create_function(name, 2, fn, deterministic=True)`.
- DDL constants or helpers for the table, the UNIQUE index and the trigger.
- The old-shape check, which raises RuntimeError.

Dependencies:
- It imports `normalize_host` from `data.moderation`. That module imports `data.similarity_cache`, which is also stdlib only (os, sqlite3, struct, pathlib), so importing `data.ann_ids` stays safe under the system interpreter that several tests and jobs use (`sys.executable` in `test_precompute_random_rowids.py`). If you add numpy or faiss here, those runs break.
- Every writer, reader-side fixture, migration and job imports it.

Points the implementer must settle:
1. **`normalize_host` can return None** (empty, whitespace or unparsable input). It also **strips ports**. The crawler's `normalize_host_token` keeps `host:port` for bare entries, so `instance_domain` can legitimately hold a port. Two videos with the same `video_id` on `h:8080` and `h:9090` would then hash the same key and collide loudly. The function must define what it hashes when the result is None: raise, or fall back to the raw lowercased domain.
2. **The old-shape check needs a `schema` argument** (`PRAGMA {schema}.table_info(video_embeddings)`). `merge-staging-db.py` must check `main` and `stage` on one connection.
3. **The DDL must be split.** `CREATE TABLE IF NOT EXISTS` is a no-op on an old table, but `CREATE UNIQUE INDEX ... ON video_embeddings(ann_id)` and `CREATE TRIGGER ... NEW.ann_id` fail with `no such column: ann_id`. Index and trigger creation must come after, or be guarded by, the old-shape check, or every caller gets a raw sqlite error instead of AC2's message.
4. **Index and trigger names must not collide** with `idx_video_embeddings_id_instance`, which `data/videos.ensure_video_indexes` drops at every Engine start.
5. **The trigger must use plain SQL** (no registered function) so that the sqlite3 CLI and the Engine's connections can still insert. Inside a trigger on `main`, unqualified table names resolve to `main`, which is correct for merge's attached `stage`.

Regression risk: medium. A change to `normalize_host` silently changes every id, so the AC1 fixed-value test is the only thing that catches it.
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host (dependency, no edit expected); purge_host_data / _host_table_column_pairs">
**`normalize_host`** becomes part of the id contract. Any future edit to it (port handling, IDNA, trimming) re-keys every `ann_id` and silently desynchronises the DB from the stored index and random cache. No code change is planned. Consider a comment at `normalize_host` pointing at `data/ann_ids.py`, or rely on the AC1 pinned-value test.

**`purge_host_data`** deletes `video_embeddings` rows by host. The new BEFORE INSERT trigger does not fire on DELETE, so purges are unaffected. This is the AC8 "purge one host" path. Afterwards a stale index returns misses, not wrong videos, through `fetch_metadata`'s `ann_id` lookup.

Callers:
- `updater-worker.purge_hosts` and `purge_hosts_from_staging`
- `instance-denylist-cli.py --purge-now`
- the moderation integration test

Risk: low.
</impact>
<impact path="engine/server/db/jobs/whitelist_migrations.py" element="new migrate_video_embeddings_schema(conn); migrate_whitelist_schema calls it last">
New function, following the `migrate_*_schema` rebuild pattern:
1. Return at once if the table is missing or already has `ann_id`.
2. Register the SQL function.
3. Create `video_embeddings_new` from the shared DDL.
4. `INSERT ... SELECT` with `ann_id` filled by the function.
5. DROP the old table and RENAME the new one.
6. Create the UNIQUE index and the trigger, IF NOT EXISTS.

`migrate_whitelist_schema` appends the call after `migrate_videos_language`. When `migrate_videos_schema` has just dropped `video_embeddings`, the new step does nothing.

Import: module-level `from data.ann_ids import ...` requires `engine/server` on `sys.path`.
- `migrate-whitelist.py` inserts `server_dir`.
- `tests/active/test_whitelist_migrations.py` loads this file with `importlib` after loading `sync-whitelist.py`, which inserts `server_dir`. It works only by that side effect, so make the test, or the module, insert the path explicitly.

Risks:
- **Atomicity.** The existing pattern uses `executescript`, which COMMITs first and runs each statement in autocommit, so `with conn:` in `migrate-whitelist.py` gives no atomicity. If the UNIQUE index build fails on a backfill collision after the DROP and RENAME, the DB is left with `ann_id` but **no UNIQUE index and no trigger**. A re-run then takes the early return because `ann_id` exists, and the guard is never installed. Either run the whole rebuild in one explicit `BEGIN ... COMMIT`, or make the early-return path still `CREATE ... IF NOT EXISTS` the index and trigger.
- **Size.** About 890k rows rewritten (around 1.4 GB). The Engine must be stopped.
- **FK.** The table declares an FK to `videos`, but `migrate-whitelist`'s connection does not enable `foreign_keys`, so DROP and RENAME are unaffected.

Regression risk: high.
</impact>
<impact path="engine/server/db/jobs/migrate-whitelist.py" element="main(); backup_db">
No logic change is needed beyond the new step running through `migrate_whitelist_schema`. `server_dir` is already on `sys.path` for `data.ann_ids`.

Operational impact:
- **Free space.** `backup_db` (the default) copies the whole `whitelist.db`, about 3.5 GB according to DATA_BUILD's VACUUM note, before the 1.4 GB rebuild. The "about 1.4 GB free" in the accepted tradeoffs understates this unless `--no-backup` is used.
- **No longer additive.** The migration now rewrites a large table, so it must run with the Engine stopped.
- **Help text.** The description, "Migrate whitelist.db schema in-place", stays accurate.

Risk: low in code, medium operationally.
</impact>
<impact path="engine/server/db/jobs/build-video-embeddings.py" element="init_schema(); main() insert tuple and INSERT OR REPLACE; --force path">
Changes:
- `init_schema` creates the table from the shared definition, then calls the old-shape check. The index and trigger must be created only after that check passes (see `ann_ids` point 3), because `CREATE TABLE IF NOT EXISTS` is a no-op on an old staging or whitelist table.
- The per-row tuple gains the id, computed in Python, and the INSERT column list gains `ann_id`.
- New import: `from data.ann_ids import ...`. `server_dir` is already on `sys.path`.

Callers:
- `updater-worker` on staging (fresh from `crawler/schema.sql`, which has no `video_embeddings`, so the table is created in the new shape; a `--resume-staging` old staging fails with the AC2 message)
- `run-dataset-build.sh` (`--force` on `whitelist.db`)
- operators on `whitelist.db`

`--force` does DELETE then reinsert, so every key gets back the same id. The trigger raises on a doctored collision. The IntegrityError aborts that batch; earlier batches are already committed (per-batch commit), which is acceptable as a loud stop.

`scripts/run-reembed.sh` parses the `--model-name` default through the AST; it must remain an `add_argument` with a Constant default.

Risk: medium.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="EMBEDDING_COLUMNS split; ensure_content_schema video_embeddings DDL; ensure_schema_compatibility; rebuild_content_tables embeddings copy">
Changes:
- `EMBEDDING_COLUMNS` becomes two lists:
  - the target list, with `ann_id`, for `_assert_columns_exact(conn, "video_embeddings", ...)`;
  - the source superset, today's six columns.
- `ensure_content_schema` replaces its inline `video_embeddings` DDL with the shared definition.
- `rebuild_content_tables` reads the source `table_info`. If the source has `ann_id`, it copies it; otherwise it selects `<fn>(video_id, instance_domain)`, which needs the function registered on this connection before the INSERT. The trigger fires per row (around 890k indexed probes) inside the single `with conn:` transaction, so a collision rolls back the whole sync.

**Ordering hazard.** `main()` calls `ensure_content_schema(conn)` **before** `ensure_schema_compatibility(conn)`. If the shared DDL creates the UNIQUE index or trigger unconditionally, an unmigrated `whitelist.db` fails with `no such column: ann_id` from the index DDL instead of the exact check's "missing columns: ann_id ... Run migrate-whitelist.py". Keep index and trigger creation conditional, or move the check first.

Other consumers of `ensure_content_schema` and of the module:
- `tests/active/test_video.py`, `test_whitelist_migrations.py`, `test_repair_video_channel_names.py` and `test_host_normalisation.py` (module load)
- `repair-video-channel-names.py`, which loads this module for its FTS helpers

`_load_schema_columns` and `videos_fts` are unaffected.

Risk: high.
</impact>
<impact path="engine/server/db/jobs/merge-staging-db.py" element="main(): old-shape guard on main and stage before BEGIN IMMEDIATE">
Change: one guard call per schema (`main`, `stage`) after ATTACH and before the transaction (approved). Needs `from data.ann_ids import ...`; `server_dir` is already inserted.

The rule loop is unchanged:
- `merge_columns` includes `ann_id` once both sides have it.
- `INSERT OR REPLACE INTO main.video_embeddings (... ann_id ...) SELECT ... FROM stage` hits the trigger per row. A same-key replace keeps the id; a doctored foreign id ABORTs, and the existing `except` rolls back.
- The connection needs no registered function.

Without the guard, an old-shape `stage` would drop `ann_id` from `merge_columns` and fail NOT NULL with a generic error. An old-shape `main` would let rows through with no `ann_id`.

Caller: `updater-worker` step "merge"; the smoke test exercises it.

Risk: low to medium.
</impact>
<impact path="engine/server/db/jobs/merge_rules.json" element="video_embeddings rule">
No change: `INSERT_OR_REPLACE` with keys `video_id`, `instance_domain` stays. Listed because the plan relies on it staying unchanged. `test-orchestrator-smoke.validate_outputs` reads the rules and checks replace and mismatch behaviour per strategy.

Risk: none.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="inject_replace_embedding_for_test; (no-change) count_staging_deltas, seed_staging_from_prod, init_staging_db, --resume-staging flow">
**`inject_replace_embedding_for_test`** must:
- select `ann_id` from `prod.video_embeddings`, or compute it through the helper;
- add `ann_id` to the `INSERT OR REPLACE` into staging.

Without that, NOT NULL fails on a new-shape staging. `server_dir` is already on `sys.path` (lines 24-27), so the "two-line insert" contingency in the plan is not needed. Its docstring may need wording.

No change:
- `init_staging_db` (crawler `schema.sql` has no `video_embeddings`)
- `seed_staging_from_prod` (instances and channels only)
- `count_staging_deltas` (key-based)
- `purge_hosts*`

With `--resume-staging`, a pre-cutover staging now fails loudly in `build-video-embeddings` (accepted).

`tests/active/test_updater_worker.py` AST-scans this file for `build-ann-index.py` and `run_with_cpu_fallback` inside the `try`. A new import does not affect that.

Risk: low.
</impact>
<impact path="engine/server/db/jobs/build-ann-index.py" element="EmbeddingRow, iter_embeddings, fetch_training_samples, add loop query, meta id_source, old-shape guard">
Changes:
- Old-shape guard before sampling, naming `migrate-whitelist.py` (AC4). It needs `from data.ann_ids import ...`; `server_dir` is already inserted.
- The add query becomes `SELECT ann_id, embedding, embedding_dim`, and `EmbeddingRow.rowid` becomes `ann_id`. The `np.int64` cast fits the 63-bit ids.
- `meta["id_source"] = "video_embeddings.ann_id"`.
- `fetch_training_samples` keeps `rowid % step` (sampling only).

Consumers of the sidecar:
- `assert_index_matches_embeddings` (Engine and precompute)
- `test-orchestrator-smoke.validate_outputs`
- `scripts/run-reembed.sh`, which logs it

Risk: medium. A missed `rowid` here produces an index the AC5 gate accepts (by sidecar) but with wrong ids.
</impact>
<impact path="engine/server/data/embedding_space.py" element="assert_index_matches_embeddings; module docstring">
Add a check: `meta.get("id_source") != "video_embeddings.ann_id"` raises RuntimeError with a message naming `build-ann-index.py`, next to the model check.

Callers:
- `api/server.py:365` (Engine start)
- `precompute-similar-ann.py:345`

Every existing sidecar (`id_source: "video_embeddings.rowid"`) and every test sidecar without `id_source` is now refused:
- `tests/active/test_precompute_similar_ann.py` writes `{"model_name", "embedding_dim"}` only and will fail until it adds `id_source`.
- `test_video.py` builds its index in-process and never calls the gate.

Update the docstring to mention the id contract.

Risk: medium. It hard-stops every Engine whose DB and index were not cut over, including the dev or test dataset.
</impact>
<impact path="engine/server/api/server.py" element="startup: open_random_cache_if_usable, resolve_embedding_space, assert_index_matches_embeddings">
No edit is expected.

Behaviour changes through the callees:
- **Random cache.** Against an old `random-cache.db`, `open_random_cache_if_usable` returns None (`no_table`). `random_cache_startup_build` becomes true (line 345), so a background build runs and the feed is served from the DB until it swaps in.
- **Index gate.** `assert_index_matches_embeddings` now refuses a rowid index, so the Engine exits at start until the index is rebuilt.

The Engine has no `video_embeddings` old-shape check of its own. An Engine on an unmigrated DB with a new index is impossible in practice, because the index build requires `ann_id`.

Risk: low in code, high in cutover ordering.
</impact>
<impact path="engine/server/data/embeddings.py" element="resolve_seed (exclude_rowid/rowid keys), _fetch_seed_by_uuid, _fetch_seed_by_id, fetch_seed_embeddings_for_likes (e.rowid AS rowid ×2), _seed_from_row">
**Change.** Four `e.rowid AS rowid` selects become `e.ann_id`, and the seed keys `rowid` and `exclude_rowid` become `ann_id` and `exclude_ann_id`. That covers `resolve_seed`'s three return shapes and `_seed_from_row`.

**Consumers of the seed keys:**
- `ann.compute_similar_items` (`seed["rowid"]`, a hard KeyError if only one side is renamed)
- `ann.search_similar_above` (`seed.get("rowid")`, which would silently stop self-exclusion)
- `similar._handle_vector_search` (`seed["exclude_rowid"]`)
- recommendations sources that pass `fetch_seed_embeddings_for_likes` seeds into `get_similar_candidates` → `compute_similar_items` (`api/recommendations/sources/ann_similar_from_likes.py` and `cached_similar_from_likes.py`)

**Other dependents:**
- `handlers/internal_client_reads.handle_internal_video_resolve` calls `fetch_seed_embedding`, so its SQL now needs `e.ann_id`. The response does not expose the id.
- `fetch_embeddings_by_ids` is unchanged.

**Risk: medium.** A partial rename silently breaks self-exclusion; there is no error.
</impact>
<impact path="engine/server/data/ann.py" element="compute_similar_items, search_similar_above, search_index (exclude_rowid param)">
Rename the variables and keys to `ann_id`:
- `seed["rowid"]` becomes `seed["ann_id"]`.
- `search_index`'s `exclude_rowid` parameter becomes `exclude_ann_id`.

The `> 0` filters stay valid. `search_index` drops only `< 0`, which also stays valid because the CHECK forbids 0.

Callers:
- `similar._handle_vector_search`
- `search.vector_candidates`
- `similarity_candidates.get_upnext_candidates` → `search_similar_above`
- `_compute_candidates` → `compute_similar_items`
- the archived `tests/archive/short_similarity_cache/test_similar.py` (not run)

`tests/active/test_similarity_candidates.py` stubs `search_similar_above` with the same signature, so a keyword rename of its parameters would not break the stub, which is positional. The nprobe helpers do not change.

Risk: low to medium.
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata">
`SELECT e.ann_id AS ann_id ... WHERE e.ann_id IN (...)`, keyed by `int(row["ann_id"])`. This uses the UNIQUE index; today the lookup goes by the rowid primary key, so performance is comparable. The parameter name and docstring move from `rowids` to `ann_ids`. Output dicts do not include the id, which keeps it out of JSON (the 2^53 precision issue).

Callers:
- `ann.compute_similar_items` and `ann.search_similar_above`
- `search.vector_candidates`
- `similar._handle_vector_search`
- `random_videos.fetch_random_rows_from_cache`
- `tests/active/test_metadata.py` (`_nsfw_metadata` passes `SELECT rowid` ids against a fixture table without `ann_id`, so it must change)

`fetch_metadata_by_ids`, `fetch_metadata_by_uuids` and `_select_metadata` are unchanged.

Risk: medium. Every fixture DB lacking `ann_id` now raises `no such column: e.ann_id` on these paths.
</impact>
<impact path="engine/server/data/search.py" element="vector_candidates">
`rowids` from `search_index` become `ann_ids`, passed to `fetch_metadata`. `VIDEO_ROW_SQL`'s `v.rowid AS rowid` (the `videos_fts` link) and `lexical_candidates` are unchanged.

`tests/active/test_search.py` runs with `query_encoder=None`, so the vector half returns before `fetch_metadata`. Its fixture table (no `ann_id`) should need no change. This is unverified beyond reading the test's server stub.

Risk: low.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._handle_vector_search">
`seed["exclude_rowid"]` becomes `seed["exclude_ann_id"]`, and local variables are renamed. Rows are `{**meta, "score"}`, and `meta` from `fetch_metadata` carries no id, so nothing reaches the JSON response. `_handle_seed_with_embedding` and `_fetch_random_rows` need no edit; they flow through `get_upnext_candidates` and `random_videos`.

Risk: low.
</impact>
<impact path="engine/server/data/random_cache.py" element="RANDOM_CACHE_CHECK_SQL, ensure_random_cache_schema, random_rowids_count (rename), populate_random_cache (both scans), fetch_random_rowids (rename), docstrings">
**Rename and reshape:**
- The table `random_rowids(position, video_rowid)` becomes `random_ann_ids(position, ann_id)`.
- `RANDOM_CACHE_CHECK_SQL` names the new table, and the count helper is renamed.

**Build:**
- The unfiltered build reads `MIN(ann_id)`/`MAX(ann_id)`. It runs `random.randint` over a 63-bit range (Python ints are fine), then `WHERE ann_id >= ? ORDER BY ann_id LIMIT ?` with wrap-around.
- `scan_range` advances `current = last ann_id + 1`.
- Both rely on the UNIQUE index for range scans. The source connection is read-only and needs no registered function.

**Old files:** a file with only `random_rowids` reads as None (`no_table`) in `open_random_cache_if_usable` and in the precompute keep check.

**Dependents:**
- `random_videos.py` imports `fetch_random_rowids` by name, and tests monkeypatch `random_videos.fetch_random_rowids`. All names must move together.
- `precompute-random-rowids.py` imports `random_rowids_count`.
- `tests/active/test_db.py`, `test_random_cache.py`, `test_random_videos.py` and `test_precompute_random_rowids.py` create `random_rowids` directly and assert positions over "rowids 1..20". With hash ids those expectations become sets of computed ids, and windows are no longer insertion-ordered.

The `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` rat-tail comment is unaffected.

Risk: medium, from test churn and the rename.
</impact>
<impact path="engine/server/data/random_videos.py" element="import of fetch_random_rowids; fetch_random_rows_from_cache">
Follows the rename. `seen` and `fresh` hold `ann_id`s, passed to `fetch_metadata`. `RANDOM_CACHE_NSFW_MAX_DRAWS` logic is unchanged. Update the docstring ("precomputed rowid cache").

`fetch_random_rows`, `fetch_recent_videos`, `fetch_popular_videos` and `fetch_ordered_page` do not touch ids.

Risk: low.
</impact>
<impact path="engine/server/db/jobs/precompute-random-rowids.py" element="import random_rowids_count; keep check; argparse description and --size help">
Changes:
- The keep check uses the renamed count helper. An old-shape `--out` counts 0, so it is rebuilt.
- The description "Precompute random rowid cache." and the help "Rowids to sample." change.
- The file name and arguments stay.

Callers:
- `scripts/run-dataset-build.sh:262`
- `tests/active/test_precompute_random_rowids.py` (its fixture source needs `ann_id`, and it asserts sorted ids `== range(1, 21)`)
- `tests/config.json` maps that test to this file

Risk: low.
</impact>
<impact path="engine/server/api/server_config.py" element="comment above DEFAULT_RANDOM_CACHE_SIZE (line 352)">
The comment "Precomputed random rowids stored for fast random feed responses." should say ANN ids. Comment only.

Risk: none.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="iter_embedding_rows_by_rowids, fetch_similarity_targets, fetch_similarity_targets_chunked, pending selection queries (SELECT e.rowid ×2), full-mode SELECT, main loop self-exclusion">
**Change.** Every `rowid` select and filter becomes `ann_id`: the helper names, the dict keys, `pending_rowids`, `batch_rowids` and `targets_by_rowid`. The self-exclusion becomes `ann_id_int == row["ann_id"]`, and the full-mode select gains `ann_id`. Output keys (`video_id`, `instance_domain`) and the incremental and refresh-existing join on `video_keys` stay. The source connection is read-only (`mode=ro`), so no function registration is possible or needed.

**AC5 dependency.** The AC5 gate (`assert_index_matches_embeddings`) runs first. It refuses a rowid index before any `ann_id` SELECT can fail on an old DB.

**Callers:**
- `updater-worker.run_similarity_stage`
- `run-dataset-build.sh`
- `tests/active/test_precompute_similar_ann.py`, which must change: its fixture table and explicit-rowid inserts, the `INDEX_BUILDER` that adds by rowid, and its sidecar without `id_source`.

**Risk: medium.** The neighbours are wrong and nothing fails if one id site is missed.
</impact>
<impact path="engine/server/db/jobs/inspect-embedding.py" element="main()">
It reads only `embedding`, `embedding_dim`, `model_name`, `video_id` and `instance_domain`. No change.

Risk: none.
</impact>
<impact path="engine/server/db/jobs/instance-denylist-cli.py" element="--purge-now (via purge_host_data)">
No change. This is one of the three coupling breaks the issue names. After the change, a purge without an index rebuild yields misses only, which AC8 covers.

Risk: none.
</impact>
<impact path="engine/server/data/videos.py" element="ensure_video_indexes">
No change. It drops only `idx_video_embeddings_id_instance`, so the new UNIQUE index's name must differ (see `ann_ids`). It runs at every Engine start against `whitelist.db`.

`tests/active/test_videos.py` builds its own table and is unaffected.

Risk: low.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="get_upnext_candidates / _compute_candidates (callers of ann functions)">
No code change is expected. It passes seeds through to `search_similar_above` and `compute_similar_items`, which read the renamed seed key. `_build_rows` uses `fetch_metadata_by_ids` (key-based) and is unaffected.

Risk: low, contingent on the seed-key rename being complete.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="handle_internal_video_resolve (via fetch_seed_embedding)">
No edit. Its SQL now selects `e.ann_id` through `fetch_seed_embedding`, so a DB without the column fails this route. The response exposes only `video_id`, `uuid`, `host`, `channel` and `title`, never the id.

`tests/active/test_internal_client_reads.py` exercises only the metadata and centroids handlers, so its fixture without `ann_id` should keep passing. The plan's "Conflicts" list names it among the churned files, which looks over-inclusive.

Risk: low.
</impact>
<impact path="engine/server/api/recommendations/sources/ann_similar_from_likes.py" element="seed_map from fetch_seed_embeddings_for_likes → get_similar_candidates">
No edit. The seeds it builds carry the renamed key into `compute_similar_items`. Listed so the rename is verified end to end. `cached_similar_from_likes.py` follows the same flow.

Risk: low.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="copy_and_prune_prod / create_table_and_indexes_from_source; validate_outputs">
Changes:
- **Add an `id_source == "video_embeddings.ann_id"` assertion** in `validate_outputs` next to the `meta_total` check (AC9).
- **Copy the triggers.** `create_table_and_indexes_from_source` copies only `type='table'` and `type='index'` DDL from the source, so **the collision trigger is not copied** into mini-prod. The smoke merge would then run without the guard. Extend it to copy `type='trigger'` for `tbl_name`, or build `video_embeddings` from the shared definition.

Dependencies:
- `INSERT INTO video_embeddings SELECT e.*` relies on identical column order, which holds when the DDL is copied.
- `--source-db` defaults to `DEFAULT_DB_PATH` (`whitelist.db`), which must already be migrated. Otherwise mini-prod is old-shape and the merge guard stops the run (arguably correct, but it fails the smoke test).
- `--inject-replace-embedding-for-test` depends on the updater inject computing `ann_id`.
- The replace and mismatch checks compare all columns, `ann_id` included, which is equal for same-key replaces.

Risk: medium.
</impact>
<impact path="engine/server/db/jobs/tests/test-moderation-integration.py" element="synthetic schema and the two INSERT OR REPLACE INTO video_embeddings seeds">
Its own `CREATE TABLE IF NOT EXISTS video_embeddings` has no `ann_id`, and it never runs `fetch_metadata`, ANN or the merge. It exercises purge and serving moderation only, so as written it should keep passing without change.

The plan lists it as churned. Change it only if the fixture is switched to the shared definition, or if the prod-sample mode copies from a migrated DB into this narrower table (it uses explicit column lists, so that is fine).

Uncertain: I did not trace every prod-sample path past line 790.

Risk: low.
</impact>
<impact path="tests/active/conftest.py" element="new shared ann_id fixture helper; engine fixture; embedding_of">
The plan puts a shared helper here that computes `ann_id` for fixture inserts. It must put `engine/server` on `sys.path` to import `data.ann_ids`; conftest currently inserts only `client/backend`.

The existing `embedding_of`, `closeness` and `identity_of` only SELECT from `whitelist.db` and need no change.

**The session `engine` fixture starts the real Engine on the repo's `whitelist.db` and `whitelist-video-embeddings.faiss`.** After AC5 it exits at start until that dataset is migrated and the index rebuilt. That fails every Engine-backed active test, including:
- `test_similar`, `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles`, `test_frontend_reactions` and the `test_random_cache` Engine cases.

This worktree has no `engine/server/db/whitelist.db` (only `random-cache.db`), so these tests read a shared dataset. DATA_BUILD says shared DB migrations run on main after merge only, so pre-merge validation of the Engine-backed suite is constrained.

Risk: high, for the test environment.
</impact>
<impact path="tests/active/test_metadata.py" element="nsfw_conn fixture table/insert; _nsfw_metadata (SELECT rowid → fetch_metadata)">
The fixture table needs an `ann_id` column, with inserts through the shared helper. `_nsfw_metadata` must pass `ann_id`s. The other tests in the file use `fetch_metadata_by_ids` and are unaffected.

Risk: low.
</impact>
<impact path="tests/active/test_random_videos.py" element="NSFW_EMBEDDINGS_TABLE, nsfw_conn, _video_db (lastrowid map), _cache_owner (random_rowids table, fetch_random_rowids monkeypatch), docstring">
**Changes:**
- `_video_db` maps labels to `lastrowid`, and the cache stores those ids. Both must become `ann_id` from the helper.
- The fixture table needs the column.
- `_cache_owner` creates `random_rowids` and monkeypatches `random_videos.fetch_random_rowids` and `random_cache.fetch_random_rowids`. These must follow the renames.
- The docstring mentions "unseen rowid".

**No change:**
- `_feed_db` copies `src.video_embeddings` from the real `whitelist.db` with CTAS (no constraints).
- The T2 copy then duplicates T's `ann_id`, which is harmless because no ordered-feed read uses `ann_id`. If the fixture ever adopts the shared definition, the copy would hit UNIQUE and the trigger.

**Risk:** medium churn.
</impact>
<impact path="tests/active/test_random_cache.py" element="_source_db, _seed_cache/_cache_rows/_cache_rowids (random_rowids), _served_rowids, _seed_servable_cache and _feed_rowids (SELECT rowid from whitelist.db), docstring assertions about 'source rowids 1..20'">
**Fixtures:**
- `_source_db` needs `ann_id` populated.
- Every direct `random_rowids` DDL, insert and read moves to `random_ann_ids(position, ann_id)`.

**Assertions:**
- "positions 1..20 over source rowids 1..20" and the order-dependent expectations become the set of the 20 computed ids.
- The window under hash order differs from insertion order (stated in the plan's risks).

**Engine cases:** they map feed rows back through `SELECT rowid FROM video_embeddings` on the real `whitelist.db`, which must become `ann_id`. They also need the migrated dataset and index (see conftest).

**Cache-file probe:** the "file without random_rowids" `open_random_cache_if_usable` case should use an old-shape `random_rowids` file. It then also pins AC6's old-shape detection.

**Risk:** high churn.
</impact>
<impact path="tests/active/test_db.py" element="_source_db, _seed_cache, CHECK_SQL, fetch_random_rowids import, SEEDED_ROWIDS">
The swap tests build a random cache from a source with no `ann_id` (needs the column and values). They seed `random_rowids` and use `CHECK_SQL` on `random_rowids`; all of that follows the rename. The import `from data.random_cache import build_random_cache, fetch_random_rowids` breaks on rename.

Risk: low.
</impact>
<impact path="tests/active/test_precompute_random_rowids.py" element="_source_db, _seed_cache, _cache_rows, assertions sorted(...)==range(1,21)">
Changes:
- The source needs `ann_id`.
- The seeded old-format cache should use the new table, plus one case with the old `random_rowids` shape to pin "old shape is rebuilt, not kept".
- Assertions compare against the computed ids.

The job runs under `sys.executable`, so `data.ann_ids` must stay stdlib only.

Risk: low.
</impact>
<impact path="tests/active/test_precompute_similar_ann.py" element="source fixture (CREATE TABLE, explicit rowid inserts), INDEX_BUILDER (add_with_ids by rowid), sidecar JSON, _source_db">
Changes:
- The fixture needs `ann_id` (helper-computed) and an index built on `ann_id`.
- The sidecar must add `"id_source": "video_embeddings.ann_id"`, or the AC5 gate refuses every run.
- `SHORT_ROWID` and the `v{rowid}` naming can stay as labels, but the ids are no longer 1..9.
- `_source_db` (the refusal tests) runs before any read and needs no change.

Risk: medium, because every test in the file fails until the sidecar is updated.
</impact>
<impact path="tests/active/test_video.py" element="similars_stack (SELECT rowid → add_with_ids); embedded-video inserts at lines 543-544">
The DB comes from `sync-whitelist.ensure_content_schema`, so it takes the new shape. The positional `INSERT INTO video_embeddings VALUES (6 values)` then breaks, both on column count and on NOT NULL `ann_id`. `similars_stack` must add the index with `ann_id`. The similars case asserts `seed v1 → ["v2"]`, which keeps working once ids match.

Risk: low.
</impact>
<impact path="tests/active/test_whitelist_migrations.py" element="_load_job of whitelist_migrations.py; new migration test">
This is the natural place for:
- the AC2 migration tests: backfill values, the UNIQUE index and trigger present, idempotence, and the early return when the table is missing;
- an old-shape fixture.

The existing test passes, because `ensure_content_schema` creates the new-shape table and the migration no-ops. The module import of `data.ann_ids` relies on `sync-whitelist.py` having been loaded first; see `whitelist_migrations`.

Risk: low.
</impact>
<impact path="tests/active/test_similarity_candidates.py" element="video_embeddings fixture; data.ann stub">
Expected unaffected. Its `data.ann` stub replaces `search_similar_above` positionally, and `_build_rows` uses key-based metadata. Re-check if the `search_similar_above` signature changes order.

Risk: low.
</impact>
<impact path="tests/active/test_search.py" element="video_embeddings fixture">
Expected unaffected (`query_encoder=None`, so `fetch_metadata` is never reached). Listed because `tests/config.json` maps it to `metadata.py`, so a metadata change selects it.

Risk: low.
</impact>
<impact path="tests/active/test_blocks.py" element="dataset SELECT joining video_embeddings">
Read-only queries against the live `whitelist.db`; no fixture insert. The plan's "Conflicts" names it, but it should need no change beyond the dataset being migrated. `test_dislikes.py`, `test_dislike_profile.py`, `test_profiles.py` and `test_frontend_reactions.py` are the same: SELECT only, and Engine-backed.

Risk: low in code, high in environment (see conftest).
</impact>
<impact path="tests/config.json" element="test → source file map">
Add `engine/server/data/ann_ids.py` to the tests that exercise it: `test_metadata`, `test_random_cache`, `test_random_videos`, `test_precompute_*`, `test_whitelist_migrations`, `test_video` and the new AC8 test. Add `embedding_space.py` where the gate matters. If the build adds a new job test file for AC8, add its entry.

Risk: low. A missed mapping only weakens change-based selection.
</impact>
<impact path="tests/last_test_validation.json" element="recorded test ids">
A generated artifact that lists test ids such as `test_precompute_random_rowids::...`. It is regenerated by the test run and should not be hand-edited. Renamed or added tests show up there.

Risk: none.
</impact>
<impact path="scripts/run-dataset-build.sh" element="sync, embeddings, index, random cache stages">
No code change is required:
- `precompute-random-rowids.py` keeps its name.
- The `--force` re-embed keeps ids.
- The index stage writes the new `id_source`.

An existing unmigrated `whitelist.db` now fails at the sync stage on the exact check, or at `--from index` on the AC4 guard. DATA_BUILD already says this script does not migrate. Optionally add a migrate step or a log hint.

Risk: low.
</impact>
<impact path="scripts/run-reembed.sh" element="comment line 28; sidecar log">
The comment "api/server.py compares the index sidecar's model_name" could also mention `id_source`. Optional.

Risk: none.
</impact>
<impact path="tests/archive/random_cache_in_place/test_random_cache.py" element="archived tests using random_rowids">
Archived and not run. Leave unchanged; they reference `random_rowids` and rowids. `tests/archive/37_local_signal/test_random_videos.py` and `tests/archive/short_similarity_cache/test_similar.py` are the same.

Risk: none.
</impact>
<impact path="docs/project/plans/17-stable-ann-ids.md" element="Impacts / Implementation / Close sections; Conflicts list of churned tests">
The build fills this plan file. Its "Conflicts" list of 9 churned `tests/active` files does not match the code:
- **Actually needing change:** `test_metadata`, `test_random_videos`, `test_random_cache`, `test_db`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_video` (and `conftest` for the new helper).
- **SELECT-only, no fixture insert:** `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles`, `test_frontend_reactions`.
- **Unaffected:** `test_internal_client_reads`, which tests only routes that don't read `ann_id`.

Correct the list when filling Impacts.
</impact>
</impacts>

### docs_checklist

<doc path="DATA_BUILD.md">
- **Line 13:** "random rowid cache" becomes the random ANN-id cache.
- **Line 155:** say that embeddings are copied with their `ann_id`, or that `ann_id` is computed when the crawl DB lacks it.
- **Line 159:** the exact check now includes `ann_id`.
- **Lines 161-172:** "The migration is additive ... without touching rows ... second run does nothing" is no longer true for `video_embeddings`. Add the one-time cutover:
  1. Stop the Engine.
  2. Run `migrate-whitelist.py`, a table rebuild that needs about 1.4 GB free plus the default full-file backup.
  3. Run `build-ann-index.py`.
  4. Start the Engine.

  Also note that a stored `random-cache.db` is rebuilt automatically.
- **Line 191:** the "schedule with the stable-ANN-ids cutover" note can now point at the cutover steps.
- **Line 232:** "The index uses `video_embeddings.rowid` as ids" becomes `video_embeddings.ann_id`; mention `id_source` and the AC4 refusal message.
- **Line 290:** "random rowid pool" changes.
- **Line 335:** `select count(*) from random_rowids` becomes `random_ann_ids`.
</doc>
<doc path="DEPLOYMENT.md">
- **Line 42:** add the one-time ANN-id cutover (stop, migrate, build index, start) and that the Engine refuses to start on an index whose sidecar `id_source` is not `video_embeddings.ann_id`.
- **Triage table:** add a row for that startup refusal, with the fix `build-ann-index.py`. Add one for the `migrate-whitelist.py` message from `build-ann-index`, merge and `build-video-embeddings`.
- **Line 421:** random-cache text is unaffected beyond a first start rebuilding an old-shape cache.
</doc>
<doc path="engine/server/db/jobs/docs/UPDATER_WORKER.md">
- **Cutover:** the prerequisite one-time migrate and index rebuild before the first updater run on new code.
- **`--resume-staging` (lines 48, 149, 186):** a pre-cutover staging DB now fails with the AC2 message and must be recreated by running without the flag.
- **Line 61:** the ANN rebuild writes `id_source: video_embeddings.ann_id`.
- **Merge:** it refuses an unmigrated prod or staging.
- **Line 197:** `--inject-replace-embedding-for-test` keeps the row's `ann_id`.
</doc>
<doc path="engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md">
- **Validations list (around line 115):** add the sidecar `id_source` assertion.
- **Source DB:** note that it must be migrated, since mini-prod copies its schema.
</doc>
<doc path="engine/server/api/recommendations/docs/LAYER_PARAMS.md">
- **Line 130:** "has no `random_rowids` table" becomes `random_ann_ids`. An old-format file counts as having no table.
- **Line 140:** "The cache holds only rowids (`random_rowids`)" becomes ANN ids (`random_ann_ids`), resolved to rows by `ann_id`. Mention the hash-uniform sampling window.
</doc>
<doc path="engine/server/api/recommendations/docs/OVERVIEW.md">
- **Line 15:** "drops rowids already seen" / "unseen rowid" becomes ANN ids.
- **Line 69:** "Holds a prebuilt list of rowids" becomes ANN ids (`random_ann_ids`).
</doc>
<doc path="engine/server/README.md">
Line 9 explains the `migrate-whitelist.py` requirement for `videos.language`. Optionally add that the Engine also refuses to start until the ANN-id cutover (migrate plus index rebuild) has run, pointing at DATA_BUILD.
</doc>
<doc path="docs/project/issues/08-stable-ann-ids.md">
At close: set `Status: enhancement, complete` and move to `docs/project/issues/archive/`, per the triage labels.
</doc>

### highest_risk

engine/server/db/jobs/whitelist_migrations.py (migrate_video_embeddings_schema): `executescript` commits per statement. If the UNIQUE index build fails on a backfill collision after DROP and RENAME, the table keeps `ann_id` with no UNIQUE index and no trigger. A re-run then takes the "already has ann_id" early return and never installs the guard. It needs one explicit transaction, or IF NOT EXISTS index and trigger creation on the early-return path too.
engine/server/db/jobs/sync-whitelist.py (ensure_content_schema runs before ensure_schema_compatibility; the same pattern applies in build-video-embeddings.init_schema): if the shared definition creates the `ann_id` UNIQUE index or trigger unconditionally, an unmigrated whitelist or staging table fails with a raw "no such column: ann_id" from the index DDL. AC2's message naming migrate-whitelist.py, or recreating staging, is never reached.
engine/server/data/embedding_space.py plus tests/active/conftest.py (the AC5 gate): every existing sidecar, including the shared dev/test dataset's index and the test_precompute_similar_ann sidecar that has no id_source, is refused. The Engine-backed active suite cannot start until a shared whitelist.db is migrated and reindexed, and DATA_BUILD says shared DB migrations run only on main after merge.

## 2026-10-02 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: none.

I read the files behind the inventory's load-bearing claims. Checked: `whitelist_migrations.py` (whole file), `migrate-whitelist.py` (sys.path, `with conn`, `backup_db`), `sync-whitelist.py` (column lists, the exact and superset checks, `ensure_content_schema` DDL, `rebuild_content_tables`, main ordering, trigger drops), `random_cache.py` (whole file), `embedding_space.py` (whole file), `server.py` 330-365, the `merge-staging-db.py`/`build-ann-index.py`/`build-video-embeddings.py`/`updater-worker.py` structure, the import closure of `data/moderation.py` and `data/similarity_cache.py`/`data/db.py`/`data/__init__.py`, the rename sites in `embeddings.py`/`ann.py`/`similar.py`/`search.py`/`metadata.py`/`random_videos.py`, the smoke test's DDL copy, and the `test_video.py`/`test_precompute_similar_ann.py` fixtures. Every entry I opened held up line for line. Every `rowid` hit in the tree outside the inventory refers to an unrelated table: `interaction_events.py`, `users.py`, the client's `blocks.py` and `users_store.py`. The plan stands. It has two ordering hazards (unconditional guard DDL, and a non-atomic migration), both already in the inventory. They need a decision during implementation, not a change of plan.
<question id="1">
Yes, on two conditions. **The DDL split.** The index and trigger must be created only after the old-shape check passes. `CREATE TABLE IF NOT EXISTS` is a no-op on an old table, but the index and trigger DDL then fails with a raw `no such column: ann_id`. In sync that DDL runs before `ensure_schema_compatibility` (lines 598-599), so AC2's message would be lost. **Migration re-runs.** A re-run must still install the guard after a failed backfill. The `migrate_*_schema` pattern uses `executescript`, and `migrate-whitelist.py`'s `with conn:` (line 86) gives it no atomicity. The trigger mechanism itself is sound against the code. FTS triggers are dropped by name only (sync 288-290, migrations 264-266), so the new trigger survives every sync. `ensure_video_indexes` drops only `idx_video_embeddings_id_instance`. The merge's `INSERT OR REPLACE` on `main` fires `main`'s trigger. I checked one possible overflow in `scan_range`: advancing to `last + 1` can reach 2^63 only when `last == range_end`, and the loop exits before binding, so the 63-bit ids are safe there. `data/ann_ids.py` → `data.moderation` → `data.similarity_cache` is stdlib-only and `data/__init__.py` is empty, so the `sys.executable` job tests still import cleanly.
</question>
<question id="2">
**Cutover.** It becomes a hard, ordered operation. `assert_index_matches_embeddings` (`server.py:365`) will refuse every existing sidecar, which still carries `id_source: "video_embeddings.rowid"` (`build-ann-index.py:284`). So every Engine, including the shared dataset behind `tests/active/conftest.py`'s session `engine`, stops at start until both steps are done: `migrate-whitelist.py` and `build-ann-index.py`. **Sync.** `sync-whitelist` and `run-dataset-build.sh` fail on any unmigrated `whitelist.db`. **Migration size.** It is no longer additive: it rewrites about 890k rows. With the default backup, `backup_db` (line 60) also copies the whole file through `read_bytes()`. That needs about 3.5 GB of extra disk and the same amount of RAM, on top of the 1.4 GB rebuild. **Random cache.** Every existing `random-cache.db` is treated as `no_table` at the next start, and a background rebuild runs (`server.py:344-345`). **Test churn.** As the inventory lists: 7 active test files plus conftest, not the 9 the plan file names.
</question>
<question id="3">
These are all in the inventory; I add nothing new.
- **Conditional DDL:** `ann_ids` creates the index and trigger only after the shape check.
- **Migration:** run it in one explicit transaction, or have its early-return path also run `CREATE ... IF NOT EXISTS` for the index and trigger.
- **`normalize_host` returning None:** decide what the id function does with it.
- **Old-shape check:** give it a `schema` parameter for merge's `main`/`stage`.
- **Updater inject:** compute and write `ann_id` (lines 1044-1056 omit it today).
- **Smoke test:** copy `type='trigger'` DDL in `create_table_and_indexes_from_source` (it copies only tables and indexes, lines 204/215), and assert `id_source`.
- **Precompute test:** add `id_source` to its sidecar (line 74).
- **`test_video.py`:** move its positional 6-value inserts (543-544) and the rowid index (217-218) to `ann_id`.
- **conftest:** put `engine/server` on `sys.path` for the helper.
- **Shared dataset:** migrate it and rebuild its index before the Engine-backed suite can pass.
- **Docs:** write the cutover runbook.
</question>
<question id="4">
- **Identity.** FAISS ids are no longer table positions. They are a 63-bit hash of `(video_id, normalize_host(instance_domain))`. A stale index now misses videos instead of returning the wrong ones.
- **Random feed.** The unfiltered draw is a uniform hash-order window instead of a block of rows in insertion order. The cache file's table and column names change.
- **Engine start.** The Engine refuses indexes that are not built on `ann_id`.
- **Migration.** `migrate-whitelist.py` becomes a heavy, Engine-stopped rewrite.
- **Collisions.** A duplicate id now aborts every writer, CLI included, where `OR REPLACE` used to delete the other video's row silently.
- **`normalize_host`.** It becomes part of the persistent id contract, so it can no longer change for free.
- **No change:** the API responses, merge strategy, sync's source requirements and `precompute-random-rowids.py`'s interface.
</question>

New impacts:
none

Inventory entries that did not hold up:
none. Every entry I opened matched its file. I did not trace these line by line, so I did not confirm them independently. precompute-similar-ann.py: 38 rowid hits, consistent with the entry but not walked site by site. test-moderation-integration.py past line 790, which the inventory itself flags. The test_random_cache.py, test_random_videos.py, test_db.py and test_precompute_random_rowids.py fixture details. The recommendations sources: no rowid reference in them, consistent with "no edit".

Conflicts: none

Recommendations: 1. **Make the migration's guard self-healing.** `migrate_video_embeddings_schema` should run `CREATE UNIQUE INDEX IF NOT EXISTS` and `CREATE TRIGGER IF NOT EXISTS` on every run in which `ann_id` is present, not only right after the rebuild. Without this, a failed backfill (the UNIQUE build fails after DROP and RENAME) leaves a table with `ann_id` and no guard, and every later re-run skips it at the early return. Cost: two idempotent statements, and the file's `executescript` pattern stays. The alternative is one explicit `BEGIN ... COMMIT` around the whole rebuild. It is fully atomic, but it departs from the file's pattern and roughly doubles the transient disk use through the rollback journal.
2. **Expose the shared DDL as two calls,** table creation and guard creation, with each caller running the guard after its shape check: `build-video-embeddings.init_schema`, and `sync-whitelist` after `ensure_schema_compatibility`. Cost: one extra call per caller. Without it, unmigrated DBs fail with raw sqlite errors instead of AC2's message.
3. **Define how the id function handles a None from `normalize_host`.** Recommended: raise ValueError naming the domain. A silent fallback would create a second normalisation rule inside the id contract. Cost: one branch, and one test.
4. **Correct the free-space figure in the runbook docs.** With the default backup, the migration needs about 3.5 GB of extra disk and about 3.5 GB of RAM, because `backup_db` reads the whole file into memory. Alternatively, document `--no-backup` together with an operator-side copy. Cost: doc text only. The accepted "about 1.4 GB" holds only without a backup, so the requirement doesn't need reopening.
5. **When filling the plan file's Impacts, record the doc edits the plan already names** (`DATA_BUILD.md`, `DEPLOYMENT.md`, `UPDATER_WORKER.md`, `LAYER_PARAMS.md`, `OVERVIEW.md`). Also replace the 9-file churn list with the inventory's corrected 7 files plus conftest. Cost: none beyond editing.
6. **Plan for the Engine-backed suite.** It cannot pass before the shared dataset is migrated and its index rebuilt. Either validate with a migrated local copy of the dataset before merge, or accept that the Engine-backed tests go red until the post-merge migration on main. Cost: a local copy (about 3.5 GB plus a rebuilt index), or a known red window.

## 2026-10-02 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Draft implementation: stable ANN ids (issue 08, plan 17)

Every file in the impact inventory was read before drafting: `moderation.py`, `whitelist_migrations.py`, `embedding_space.py`, `random_cache.py`, `random_videos.py`, `metadata.py`, `embeddings.py`, `ann.py`, `search.py`, `similar.py`, `build-video-embeddings.py`, `build-ann-index.py`, `merge-staging-db.py`, `sync-whitelist.py`, `updater-worker.py`, both precompute jobs, the smoke test and the churned `tests/active` fixtures. The new code is shown in full; existing files get exact edits.

### What the build has to test

- **AC1, the id function:** same input gives the same output; the result is between 1 and 2^63-1; one pinned value; host normalisation (`"Host.Example."` and `"host.example"` give the same id).
- **AC2, the schema:**
  - the new table shape;
  - the CHECK refuses an id of 0;
  - a doctored id is refused by the trigger on a plain INSERT, on `INSERT OR REPLACE` (the other row must survive) and on merge;
  - a same-key replace keeps the id;
  - the migration fills `ann_id`, is idempotent, does nothing when the table is missing, and leaves an unchanged old-shape table when it fails;
  - the old-shape refusal message, for `main` and for `stage`.
- **AC3, the writers:** build-video-embeddings (including `--force`), sync from a source with `ann_id` and from one without, merge, and the test inject.
- **AC4/AC5, the index:** the sidecar's `id_source`, and the Engine refusing a rowid sidecar.
- **AC6, the readers:** the renamed seed keys, ANN and metadata reads by `ann_id`, and an old-shape random cache treated as unusable and rebuilt.
- **AC7:** the similarity precompute on `ann_id`.
- **AC8:** a stale index after the table is renumbered and after a host purge.
- **AC9:** the orchestrator smoke test checks `id_source`.

### Module map

| File | Change |
|---|---|
| `engine/server/data/ann_ids.py` | **new**: id function, SQL registration, table definition, guards, old-shape check, `ANN_ID_SOURCE` |
| `engine/server/data/moderation.py` | one comment line above `normalize_host` |
| `engine/server/db/jobs/whitelist_migrations.py` | `sys.path` insert, `migrate_video_embeddings_schema`, called last |
| `engine/server/db/jobs/build-video-embeddings.py` | `init_schema` uses the helper; the insert tuple and column list gain `ann_id` |
| `engine/server/db/jobs/sync-whitelist.py` | `TARGET_EMBEDDING_COLUMNS`; table from the helper; guards created only when the column exists; copy or compute `ann_id` |
| `engine/server/db/jobs/merge-staging-db.py` | old-shape check on `main` and `stage` before `BEGIN IMMEDIATE` |
| `engine/server/db/jobs/updater-worker.py` | the test inject writes `ann_id` |
| `engine/server/db/jobs/build-ann-index.py` | old-shape check; `ann_id` ids; `id_source` |
| `engine/server/data/embedding_space.py` | `id_source` check and docstring |
| `engine/server/data/embeddings.py`, `ann.py`, `metadata.py`, `search.py`, `api/handlers/similar.py` | rowid → `ann_id` rename |
| `engine/server/data/random_cache.py`, `random_videos.py`, `db/jobs/precompute-random-rowids.py`, `api/server_config.py` (comment) | `random_ann_ids` cache |
| `engine/server/db/jobs/precompute-similar-ann.py` | rowid → `ann_id` rename |
| `engine/server/db/jobs/tests/test-orchestrator-smoke.py` | guards in mini-prod; `id_source` assertion |
| `tests/active/*`, `tests/config.json` | fixtures, new tests, map entries |

No change: `merge_rules.json` (stays `INSERT_OR_REPLACE`), `migrate-whitelist.py`, `server.py`, `similarity_candidates.py`, the recommendation sources, `inspect-embedding.py`, `instance-denylist-cli.py`, `videos.py`, `test-moderation-integration.py` (its own narrow table, which never reaches `ann_id` readers, per the impact), and the archived tests.

---

### 1. `engine/server/data/ann_ids.py` (new)

```python
"""Derive, store and guard the ANN id of an embedded video (ADR-0006)."""

from __future__ import annotations

import hashlib
import sqlite3

from data.moderation import normalize_host

# The sidecar id_source every index must carry; the Engine refuses any other.
ANN_ID_SOURCE = "video_embeddings.ann_id"
# SQL name of compute_ann_id once register_ann_id_function has run on a connection.
ANN_ID_SQL_FUNCTION = "ann_id_of"
ANN_ID_MASK = (1 << 63) - 1

ANN_ID_INDEX_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)"
# Plain SQL so every connection (Engine, sqlite3 CLI) can insert; BEFORE triggers run ahead of OR REPLACE conflict resolution, so a foreign id aborts instead of deleting the row that holds it.
ANN_ID_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision
BEFORE INSERT ON video_embeddings
WHEN EXISTS (
  SELECT 1 FROM video_embeddings
  WHERE ann_id = NEW.ann_id
    AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)
)
BEGIN
  SELECT RAISE(ABORT, 'video_embeddings ann_id collision: another (video_id, instance_domain) already holds this ann_id; see docs/project/adr/0006-derived-ann-ids.md');
END
"""


def compute_ann_id(video_id: str, instance_domain: str) -> int:
    """Return the 63-bit blake2b ANN id of video_id::normalize_host(instance_domain); 0 is left to the table's CHECK."""
    # A domain normalize_host rejects hashes as its trimmed lowercase text, so every key still has one deterministic id.
    host = normalize_host(instance_domain) or str(instance_domain).strip().lower()
    digest = hashlib.blake2b(f"{video_id}::{host}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ANN_ID_MASK


def register_ann_id_function(conn: sqlite3.Connection) -> None:
    """Expose compute_ann_id to SQL on this connection as ann_id_of(video_id, instance_domain)."""
    conn.create_function(ANN_ID_SQL_FUNCTION, 2, compute_ann_id, deterministic=True)


def create_video_embeddings_table(conn: sqlite3.Connection, table: str = "video_embeddings") -> None:
    """Create the video_embeddings table (or a rebuild's `table`) if missing; a no-op on an existing table of any shape."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB NOT NULL,
          embedding_dim INTEGER NOT NULL,
          model_name TEXT NOT NULL,
          created_at TEXT NOT NULL,
          ann_id INTEGER NOT NULL CHECK (ann_id > 0),
          PRIMARY KEY (video_id, instance_domain),
          FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
        )
        """
    )


def create_ann_id_guards(conn: sqlite3.Connection) -> None:
    """Create the UNIQUE ann_id index and the collision trigger; the table must already have ann_id."""
    conn.execute(ANN_ID_INDEX_SQL)
    conn.execute(ANN_ID_TRIGGER_SQL)


def assert_video_embeddings_has_ann_id(conn: sqlite3.Connection, schema: str = "main") -> None:
    """Raise if {schema}.video_embeddings exists without ann_id; a missing table is left to the caller."""
    columns = [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info(video_embeddings)")]
    if columns and "ann_id" not in columns:
        raise RuntimeError(
            f"{schema}.video_embeddings has no ann_id column. "
            "Run `engine/server/db/jobs/migrate-whitelist.py` to migrate the whitelist DB; "
            "a staging DB reused with --resume-staging must be recreated by running the updater without --resume-staging."
        )


def ensure_video_embeddings_schema(conn: sqlite3.Connection) -> None:
    """Create video_embeddings and its guards, refusing an old-shape table with the migrate message."""
    create_video_embeddings_table(conn)
    assert_video_embeddings_has_ann_id(conn)
    create_ann_id_guards(conn)
```

**Invariants and decisions**

- **Stdlib only.** The module imports `hashlib` and `sqlite3`, plus `data.moderation`, which itself only imports `data.similarity_cache`. Jobs and tests that run under `sys.executable` (such as `test_precompute_random_rowids`) can still import it.
- **When `normalize_host` returns None** (impact point 1): the id falls back to the trimmed, lowercased domain and never raises. A raise inside the registered SQL function would abort a whole sync over one odd host. `normalize_host` never returns text containing whitespace, and it returns every live host unchanged, because they are all already lowercase and trimmed.
- **Ports** (impact point 1): `normalize_host` strips them, as AC1 requires. So `(v, h:8080)` and `(v, h:9090)` share an id, and the trigger stops that write loudly, which falls under the accepted "collision stops loudly". The live 0-collision measurement hashed the raw domain, so **check before merge, read-only:** `SELECT COUNT(*) FROM video_embeddings WHERE instance_domain LIKE '%:%'` on the live DB. If it returns 0, ports cannot cause a collision today.
- **The DDL is split** (impact point 3). The table is created first. The guards are created only by callers that have confirmed `ann_id` exists (`ensure_video_embeddings_schema`, the sync column check, the migration), so an old-shape table always gets the AC2 message and never a raw `no such column: ann_id`.
- **Names** (impact point 4): `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision` do not clash with `idx_video_embeddings_id_instance`, which `ensure_video_indexes` drops at every Engine start.
- **Single statements.** Every DDL goes through `conn.execute`, never `executescript`, so creating the table and guards inside sync's `with conn:` does not commit early.
- **Collisions.** An id of 0 fails the CHECK, which `OR REPLACE` cannot override. A colliding UPDATE fails on the UNIQUE index. A same-key replace matches no other row, so it passes the trigger and keeps the same id.

### 2. `engine/server/data/moderation.py`

Add one line above `def normalize_host`:

```python
# Part of the ANN id contract (data/ann_ids.py): any change here re-keys every video_embeddings.ann_id, stored index and random cache.
```

### 3. `engine/server/db/jobs/whitelist_migrations.py`

Header. The `sys.path` insert means the module no longer relies on `sync-whitelist.py` having been loaded first (as `test_whitelist_migrations.py` currently does):

```python
import sqlite3
import sys
from pathlib import Path

server_dir = Path(__file__).resolve().parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function
```

New function, placed before `migrate_whitelist_schema`:

```python
def migrate_video_embeddings_schema(conn: sqlite3.Connection) -> None:
    """Rebuild video_embeddings with the derived ann_id column, its UNIQUE index and its collision trigger (ADR-0006).

    The rebuild runs in one explicit transaction. A backfill collision or a zero id fails the UNIQUE index or the CHECK and rolls back to the old shape, so a re-run retries the whole rebuild instead of skipping a table left without its guards. Idempotent: a table that already has ann_id, or no table at all, is left alone.
    """
    if not _table_exists(conn, "video_embeddings"):
        return
    if "ann_id" in _columns(conn, "video_embeddings"):
        return
    register_ann_id_function(conn)
    # Close whatever the earlier steps left open, as their executescript calls do.
    conn.commit()
    conn.execute("BEGIN")
    try:
        conn.execute("DROP TABLE IF EXISTS video_embeddings_new")
        create_video_embeddings_table(conn, "video_embeddings_new")
        conn.execute(
            f"""
            INSERT INTO video_embeddings_new (
              video_id,
              instance_domain,
              embedding,
              embedding_dim,
              model_name,
              created_at,
              ann_id
            )
            SELECT
              video_id,
              instance_domain,
              embedding,
              embedding_dim,
              model_name,
              created_at,
              {ANN_ID_SQL_FUNCTION}(video_id, instance_domain)
            FROM video_embeddings
            """
        )
        conn.execute("DROP TABLE video_embeddings")
        conn.execute("ALTER TABLE video_embeddings_new RENAME TO video_embeddings")
        # Created after the rename so their SQL names the final table.
        create_ann_id_guards(conn)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
```

`migrate_whitelist_schema` gains a last line, `migrate_video_embeddings_schema(conn)`, after `migrate_videos_language`. When `migrate_videos_schema` has just dropped the table, the new step returns early.

**Departure from the pattern, named.** The existing steps use `executescript`, which commits before it runs and then runs in autocommit. This step uses an explicit `BEGIN`/`COMMIT` instead, because of the atomicity risk the impact inventory names. Its shape (`_new` table, copy, drop, rename) is the existing pattern. The `with conn:` in `migrate-whitelist.py` stays harmless: nothing is left open for it to commit. The FK on `videos` does not affect the DROP or the RENAME, because `migrate-whitelist`'s connection does not enable `foreign_keys`.

### 4. `engine/server/db/jobs/build-video-embeddings.py`

- Import, after `CompactHelpFormatter`: `from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema`.
- `init_schema` becomes:

```python
def init_schema(conn: sqlite3.Connection) -> None:
    """Create video_embeddings in its ann_id shape, refusing an old-shape table."""
    ensure_video_embeddings_schema(conn)
    conn.commit()
```

- The tuple in the batch loop gains `compute_ann_id(video_id, instance_domain)` as its last item. The insert becomes:

```python
            INSERT OR REPLACE INTO video_embeddings
              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
```

- `--force` (DELETE, then reinsert) gives every key back its old id. `--model-name` stays an `add_argument` with a constant default, which `run-reembed.sh` depends on.
- An old-shape staging DB (`--resume-staging`) or `whitelist.db` stops in `init_schema` with the AC2 message, before the model loads.

### 5. `engine/server/db/jobs/sync-whitelist.py`

- Import: `from data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function`.
- `EMBEDDING_COLUMNS` keeps its six names; it is now the source superset and the copied columns. Add, following the `WHITELIST_DERIVED_VIDEO_COLUMNS` precedent:

```python
# Derived in the whitelist DB from (video_id, instance_domain) (data/ann_ids.py). An older crawl DB lacks it, so it belongs in the exact check against `main.video_embeddings` but not in the source superset check.
TARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + ["ann_id"]
```

- `ensure_schema_compatibility`: `_assert_columns_exact(conn, "video_embeddings", TARGET_EMBEDDING_COLUMNS)`. An unmigrated DB gets "missing columns: ann_id ... Run `engine/server/db/jobs/migrate-whitelist.py`".
- `ensure_content_schema`: remove the inline `video_embeddings` DDL from the `executescript`. After it, and before `create_videos_fts_triggers(conn)`, add:

```python
    create_video_embeddings_table(conn)
    # An old-shape table is left for ensure_schema_compatibility to refuse with the migrate message; creating guards on it would fail on the missing column first.
    if "ann_id" in _table_columns(conn, "video_embeddings"):
        create_ann_id_guards(conn)
```

This resolves the ordering hazard without moving the check that `main()` runs afterwards. `repair-video-channel-names.py` and the tests that call `ensure_content_schema` on new DBs get the new shape with guards.

- `rebuild_content_tables` embedding copy:

```python
    if source_embedding_columns.issuperset(EMBEDDING_COLUMNS):
        embedding_columns = ", ".join(EMBEDDING_COLUMNS)
        # A crawl DB that predates ann_id gets it derived here, so its embeddings are kept rather than re-embedded; the trigger guards every row either way.
        register_ann_id_function(conn)
        ann_id_expr = "ann_id" if "ann_id" in source_embedding_columns else f"{ANN_ID_SQL_FUNCTION}(video_id, instance_domain)"
        conn.execute(
            f"""
            INSERT INTO video_embeddings ({embedding_columns}, ann_id)
            SELECT {embedding_columns}, {ann_id_expr}
            FROM {SOURCE_SCHEMA}.video_embeddings
            WHERE (video_id, instance_domain) IN (
              SELECT video_id, instance_domain FROM videos
            );
            """
        )
```

  A collision raises inside the `with conn:` in `main()`, so the whole sync rolls back. Each row costs one probe of the UNIQUE index (around 890k).

### 6. `engine/server/db/jobs/merge-staging-db.py`

- Import: `from data.ann_ids import assert_video_embeddings_has_ann_id`.
- In `main()`, the first lines inside `try:`, before `conn.execute("BEGIN IMMEDIATE")`:

```python
        # An old-shape stage would drop ann_id from merge_columns, and an old-shape main would take rows without one: refuse both with the migrate message.
        assert_video_embeddings_has_ann_id(conn, "main")
        assert_video_embeddings_has_ann_id(conn, "stage")
```

- They sit inside `try` so the existing `finally` still detaches and closes. The existing `except` calls `rollback()`, which does nothing when no transaction is open.
- The rule loop is unchanged. `merge_columns` now includes `ann_id`, and `INSERT OR REPLACE INTO main.video_embeddings` fires `main`'s trigger on each row. Inside a trigger on `main`, the unqualified `video_embeddings` resolves to `main`, which is the intended table.

### 7. `engine/server/db/jobs/updater-worker.py`

- Import, next to `data.moderation`: `from data.ann_ids import compute_ann_id`. `server_dir` is already on `sys.path` (lines 24-27), so the plan's fallback `sys.path` insert is not needed.
- `inject_replace_embedding_for_test`: docstring "Insert one overlapping embedding row into staging with modified payload and the same ann_id." The insert becomes:

```python
            INSERT OR REPLACE INTO video_embeddings
              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)
            VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
```

  with `compute_ann_id(video_id, instance_domain)` added to the parameters. The id is computed rather than read from prod, so the inject works whatever shape prod has, and an old-shape prod is still refused at merge.

### 8. `engine/server/db/jobs/build-ann-index.py`

- Import: `from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id`.
- `EmbeddingRow.rowid` becomes `ann_id: int`. In `iter_embeddings`, `for ann_id, embedding_blob, embedding_dim in rows:` and `EmbeddingRow(ann_id=ann_id, ...)`.
- In `main()`, right after connecting and before `resolve_embedding_space`: `assert_video_embeddings_has_ann_id(conn)`. This is the AC4 refusal, and it names `migrate-whitelist.py`.
- Add query: `"SELECT ann_id, embedding, embedding_dim FROM video_embeddings"`. Ids: `np.array([item.ann_id for item in batch], dtype=np.int64)`; a 63-bit id fits.
- `meta["id_source"] = ANN_ID_SOURCE`.
- `fetch_training_samples` is unchanged: `rowid % step` only spreads the training sample and is never an identity. This is a named simplification.

### 9. `engine/server/data/embedding_space.py`

- Import: `from data.ann_ids import ANN_ID_SOURCE`.
- Docstring: one more paragraph: "The sidecar also records `id_source`. Readers resolve hits by `video_embeddings.ann_id` (ADR-0006), so an index whose ids are rowids would return the wrong videos and is refused."
- After the model check:

```python
    index_id_source = str(meta.get("id_source") or "")
    if index_id_source != ANN_ID_SOURCE:
        raise RuntimeError(
            f"Index ids come from {index_id_source or '<unset>'} but readers resolve "
            f"{ANN_ID_SOURCE}. Rebuild the index with build-ann-index.py."
        )
```

  This also guards `precompute-similar-ann.py`.

### 10. Readers: rowid → `ann_id` rename

**`data/embeddings.py`**
- The four `e.rowid AS rowid` selects become `e.ann_id AS ann_id`.
- `_seed_from_row` returns `"ann_id": int(row["ann_id"])`.
- In `resolve_seed`, every `"exclude_rowid"` becomes `"exclude_ann_id"` (all three return shapes), and `"rowid": seed["rowid"]` becomes `"ann_id": seed["ann_id"]`.

**`data/ann.py`**
- `compute_similar_items`: `ann_ids = [int(item) for item in ids[0] if int(item) > 0]`. The log key becomes `ann_ids=%d`. The loop variable becomes `ann_id`/`ann_id_int`, and the self check `== seed["ann_id"]`.
- `search_similar_above`: `seed_ann_id = seed.get("ann_id")`, with the `> 0` filter kept.
- `search_index(index, vector, limit, exclude_ann_id)` keeps the same position. Its docstring becomes "optionally exclude an ANN id", and its loop variable `ann_id`.
- The nprobe helpers are untouched.

**`data/metadata.py`**
- `fetch_metadata(conn, ann_ids: list[int], ...)`, docstring "Fetch video metadata for embedding ANN ids."
- `e.ann_id AS ann_id`, `WHERE e.ann_id IN (...)` (served by the UNIQUE index), `result[int(row["ann_id"])]`. Every caller passes ids positionally (checked).
- The output dicts still do not carry the id.

**`data/search.py`**
- In `vector_candidates`, `ann_ids, _scores = search_index(...)`, and the rest of the function follows.
- `VIDEO_ROW_SQL` `v.rowid` (the `videos_fts` link) is unchanged.

**`api/handlers/similar.py`**
- `ann_ids, scores = search_index(self.server.index, vector, limit, seed["exclude_ann_id"])`; the `fetch_metadata` call and the loop are renamed to match.

### 11. Random cache

**`data/random_cache.py`**
- `RANDOM_CACHE_CHECK_SQL = "SELECT COUNT(*) FROM random_ann_ids"`.
- Table: `random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)`.
- `random_rowids_count` becomes `random_ann_ids_count`. It looks for `name = 'random_ann_ids'`, with the docstring "Return the number of cached ANN ids, or None when the random_ann_ids table is missing (an old-format random_rowids file counts as missing)."
- `populate_random_cache`:
  - the source stats become `COUNT(*) AS total, MIN(ann_id) AS min_id, MAX(ann_id) AS max_id`;
  - the unfiltered scan becomes `SELECT ann_id FROM video_embeddings WHERE ann_id >= ? ORDER BY ann_id LIMIT ?`, with a wrap that uses `ann_id < ?`;
  - the filtered `scan_range` selects `e.ann_id AS ann_id`, `WHERE e.ann_id >= ? AND e.ann_id <= ? ORDER BY e.ann_id`, and sets `current = int(rows[-1]["ann_id"]) + 1`;
  - the locals become `ann_ids`, and the inserts become `INSERT INTO random_ann_ids (position, ann_id)`.
  - Comment above the start draw: "# Hashed ids are uniform over [min_id, max_id], so a window from a random start is a uniform sample, not a block of insertion order."
- `build_random_cache` docstring: "(temp path, ANN ids written, elapsed seconds)".
- `open_random_cache_if_usable` docstring: "holds at least one ANN id". The `no_table` path now also covers old `random_rowids` files. No new code is needed.
- `fetch_random_rowids` becomes `fetch_random_ann_ids`, which reads `SELECT ann_id FROM random_ann_ids ORDER BY position ...`.

**`data/random_videos.py`**
- `from data.random_cache import fetch_random_ann_ids`. In `fetch_random_rows_from_cache`, the locals become `ann_ids`, and the docstring says "precomputed ANN-id cache" and "unseen ANN id".

**`db/jobs/precompute-random-rowids.py`**
- Imports `random_ann_ids_count`. An old-shape `--out` counts as 0 and is rebuilt.
- `description="Precompute random ANN-id cache."` and `--size` help `"ANN ids to sample."`. The file name and arguments are unchanged.

**`api/server_config.py`**
- The comment becomes "Precomputed random ANN ids stored for fast random feed responses."

**Named simplification.** An old cache is detected by its table name, not its shape. The ceiling: a future reshape under the same name would need a column check. The upgrade: compare `PRAGMA table_info` in `random_ann_ids_count`.

### 12. `engine/server/db/jobs/precompute-similar-ann.py`

- `iter_embedding_rows_by_rowids` becomes `iter_embedding_rows_by_ann_ids(conn, ann_ids, batch_size=512)`, which selects `ann_id, video_id, instance_domain, embedding, embedding_dim` with `WHERE ann_id IN (...)`.
- `fetch_similarity_targets` and `fetch_similarity_targets_chunked` take `ann_ids`, select `ann_id, video_id, instance_domain` with `WHERE ann_id IN`, and return `{row["ann_id"]: dict(row)}`. Their docstrings say "ANN id".
- Both selection queries use `SELECT e.ann_id`, and `pending_ann_ids = [int(row["ann_id"]) ...]`. The full mode selects `ann_id, video_id, instance_domain, embedding, embedding_dim`. The comment at line 366 says "only ANN ids are materialized".
- In the loop: `batch_ann_ids`, `targets_by_ann_id`, and `if ann_id_int == row["ann_id"] or ann_id_int <= 0: continue`.
- The output keys and the `video_keys` joins are unchanged. The local `set_nprobe` is unchanged. The source stays `mode=ro`, so nothing is registered on it.

### 13. `engine/server/db/jobs/tests/test-orchestrator-smoke.py`

- Import: `from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id, create_ann_id_guards`.
- In `copy_and_prune_prod`, right after `create_table_and_indexes_from_source(conn, table)` for `table == "video_embeddings"`:

```python
            if table == "video_embeddings":
                # The copy brings tables and indexes only; mini-prod needs the collision trigger for the merge to run guarded, and an unmigrated source is refused here with the migrate message.
                assert_video_embeddings_has_ann_id(conn)
                create_ann_id_guards(conn)
```

  This is chosen over copying `type='trigger'` generally, which would also bring `videos_fts_*` triggers into a mini-prod that has no `videos_fts`.

- In `validate_outputs`, after `meta_total`:

```python
    if meta.get("id_source") != ANN_ID_SOURCE:
        raise RuntimeError(f"ANN meta id_source is {meta.get('id_source')!r}, expected {ANN_ID_SOURCE!r}")
    checks["ann_id_source"] = meta["id_source"]
```

- `INSERT INTO video_embeddings SELECT e.*` still works, because the DDL is copied with the same column order.

### 14. Tests

**Shared helper.** `tests/active/conftest.py` appends `ROOT / "engine" / "server"` to `sys.path` after the client imports. Appending rather than inserting keeps `client/backend`'s `server` and `lib` first. It then re-exports `from data.ann_ids import compute_ann_id  # noqa: E402`, and tests use `from conftest import compute_ann_id`.

**New: `tests/active/test_ann_ids.py`.** Runs on the system interpreter, apart from the AC8 child.
- AC1:
  - the same call gives the same result;
  - `1 <= id <= 2**63-1` over a few hundred keys;
  - one literal pinned value for `("abc", "peertube.example")`, computed once by an independent `hashlib` one-liner at implementation time and pasted in as a constant;
  - `"Peertube.Example."` gives the same id;
  - an unparsable domain falls back deterministically.
- AC2, schema: `ensure_video_embeddings_schema` on a DB that has `videos`, then:
  - `INSERT` with `ann_id=0` raises IntegrityError (CHECK);
  - a doctored `ann_id` equal to another key's id raises IntegrityError on a plain INSERT, and again on `INSERT OR REPLACE`; afterwards the other row still exists, unchanged;
  - a same-key `INSERT OR REPLACE` keeps the count and the id;
  - an UPDATE to a taken id raises (UNIQUE).
- AC2, old shape:
  - `assert_video_embeddings_has_ann_id` on a six-column table raises a message containing `migrate-whitelist.py` and `--resume-staging`;
  - on an attached schema, it names `stage.`;
  - on a missing table, it does nothing.
- AC2, merge: run `merge-staging-db.py` as a subprocess on a tmp prod and staging pair.
  - A doctored staging row (a new key carrying an existing prod id) exits non-zero; prod is unchanged and the other video is present.
  - An old-shape stage exits non-zero with the message.
  - A normal merge carries `ann_id` across.
- AC3: `sync-whitelist.rebuild_content_tables`, loaded with `importlib` the way the existing tests do, on an attached source **with** `ann_id`, which is copied, and on one **without**, which is computed and equals `compute_ann_id`. In both cases `ensure_schema_compatibility` passes on the new shape and fails on an old target with "missing columns: ann_id ... migrate-whitelist.py".
- AC5: `assert_index_matches_embeddings` with a stub index (`SimpleNamespace(d=4)`) and a sidecar:
  - `id_source` `video_embeddings.rowid` raises naming `build-ann-index.py`;
  - a missing `id_source` raises;
  - `video_embeddings.ann_id` passes.

**New: `tests/active/test_stale_ann_index.py` (AC8).** It runs a child under `ENGINE_PY`, the `test_precompute_similar_ann` pattern, because it needs faiss and numpy.
- The child builds a small DB (`videos`, `channels`, `video_embeddings` via `ensure_video_embeddings_schema`) and an `IDMap2,IVF1,Flat` index on `ann_id`. It records `ann_id → (video_id, host)` from the vectors it indexed.
- **Case A, renumber.** Delete every row and reinsert them in reversed order. The rowids change and the ids do not.
- **Case B, purge.** Run `purge_host_data` for one host.
- **Case C.** Insert a new video that the index does not hold.
- After each case, the child calls `ann.compute_similar_items` and `search.vector_candidates`. It uses a stub server (`index`, `index_lock`, `db`, `db_lock`, `normalize_queries=False`, `similarity_*` defaults, and a `query_encoder` stub whose `enabled=True` and whose `encode` returns a fixed vector).
- It prints JSON. The test asserts that every returned `(video_id, instance_domain)` equals the identity recorded for the vector whose hit produced it, that the purged host's videos are absent, and that the new video is absent rather than substituted.
- This is a departure from the plan's word "job test": it lives in `tests/active`, where the gating suite runs and where the faiss-in-a-child precedent already exists.

**Migration tests (in `tests/active/test_whitelist_migrations.py`).** An old six-column table with 3 rows, then `migrate_whitelist_schema`:
- the columns include `ann_id`, and each value equals `compute_ann_id`;
- `idx_video_embeddings_ann_id` and the trigger are in `sqlite_master`;
- a second run changes nothing (same `sqlite_master` and the same rows);
- a DB without the table is left alone;
- an old table with a doctored duplicate cannot occur from the function, so failure atomicity is pinned by registering a stub `ann_id_of` that returns a constant. The migration raises, and the old table still has six columns and every row.

The test also inserts `engine/server` on `sys.path` itself; the module now does that too.

**Fixture churn.**

| File | Change |
|---|---|
| `test_metadata.py` | Fixture DDL gains `ann_id INTEGER`. Inserts pass `compute_ann_id(label, HOST)`. `_nsfw_metadata` selects `ann_id` instead of `rowid`. |
| `test_random_videos.py` | `NSFW_EMBEDDINGS_TABLE` gains `ann_id`. `_video_db` maps labels to `compute_ann_id`. `_cache_owner` creates `random_ann_ids(position, ann_id)` and monkeypatches `fetch_random_ann_ids` on both modules. The docstring says "unseen ANN id". CTAS copies from `whitelist.db` are unchanged. |
| `test_random_cache.py` | `_source_db` gains an `ann_id` column with computed values. Every `random_rowids` becomes `random_ann_ids`. "positions 1..20 over rowids 1..20" becomes the set of the 20 computed ids. Engine cases map rows back with `SELECT ann_id`. The "no table" probe uses an old-format `random_rowids` file, which pins AC6's old-shape case. |
| `test_db.py` | Its source gains `ann_id`. `_seed_cache` and `CHECK_SQL` move to `random_ann_ids`. Imports `fetch_random_ann_ids`. `SEEDED_ROWIDS` becomes computed ids. |
| `test_precompute_random_rowids.py` | Its source gains `ann_id`. Assertions use `sorted(computed ids)`. New case: an `--out` holding an old `random_rowids` table with `--size` rows is rebuilt into `random_ann_ids`, not kept. |
| `test_precompute_similar_ann.py` | The fixture table gains `ann_id` (`compute_ann_id`). `INDEX_BUILDER` adds with `SELECT ann_id, embedding`. The sidecar adds `"id_source": "video_embeddings.ann_id"`. `SHORT_ROWID` and `v{n}` stay as labels only. |
| `test_video.py` | The positional inserts at 543-544 become explicit column lists, with `ann_id`. `similars_stack` selects `ann_id` for `add_with_ids`. |

`test_internal_client_reads`, `test_search`, `test_similarity_candidates` and `test_videos` are unchanged, because none of them reaches `ann_id`. `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles` and `test_frontend_reactions` are SELECT-only and need no code change. `test-moderation-integration.py` is unchanged, per its impact. The plan's "Conflicts" list is corrected when Impacts is filled.

**`tests/config.json`.**
- Add `engine/server/data/ann_ids.py` to `test_ann_ids`, `test_stale_ann_index`, `test_metadata`, `test_random_cache`, `test_random_videos`, `test_db`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_whitelist_migrations` and `test_video`.
- Add `embedding_space.py` to `test_ann_ids` and `test_precompute_similar_ann`.
- Map the two new files to the sources they exercise.

`tests/last_test_validation.json` is regenerated by the test run, not edited by hand.

### 15. Docs

These follow the settled documentation list:
- `DATA_BUILD.md`, `DEPLOYMENT.md` and `UPDATER_WORKER.md` get the cutover: stop the Engine, run `migrate-whitelist.py` (a rebuild that needs about 1.4 GB free plus the default full-file backup, about 3.5 GB, unless `--no-backup` is used), run `build-ann-index.py`, then start the Engine. They also cover the refusal messages and the `--resume-staging` behaviour.
- `ORCHESTRATOR_SMOKE_TEST.md`: the `id_source` check, and that the source must be migrated.
- `LAYER_PARAMS.md` and `OVERVIEW.md`: `random_ann_ids`.
- `engine/server/README.md`: the optional startup-refusal note.
- At close, the issue gets `Status: enhancement, complete` and moves to the archive.

### Seams and environment notes for the test steps

- **Engine-backed tests and the shared dataset.** The session `engine` fixture starts the real Engine on the shared `whitelist.db` and index. After AC5 it exits at startup until that dataset is migrated and its index rebuilt. DATA_BUILD runs shared migrations on main only after merge. So the Engine-backed `tests/active` cases can only go green once the cutover has run on the dataset they read. The unit and job tests above do not depend on it. The gate step has to schedule this; the code cannot fix it.
- **The smoke test's `--source-db`** must likewise be migrated. Otherwise it stops with the AC2 message, by design.

### Pass check against the plan and the requirements

**Pass 1** found these gaps; the draft above includes the fixes:
1. The guards on old tables would fail with a raw sqlite error (sync's ordering hazard and `init_schema`). Fixed by the split DDL and the conditional guard creation.
2. The migration was not atomic (a failed index build left a table with no guards). Fixed by the explicit transaction.
3. `whitelist_migrations` depended on load order. Fixed by its own `sys.path` insert.
4. Mini-prod would have no trigger. Fixed by creating the guards after the copy.
5. `None` and ports from `normalize_host`. Settled: fall back to the raw domain, with a port pre-check query.
6. The test sidecar had no `id_source`. Fixed.

**Pass 2** found everything met:
- **AC1:** the one helper, stdlib, 63-bit, pinned value.
- **AC2:**
  - the column, CHECK and UNIQUE index;
  - the migration follows the rebuild shape, is idempotent and is called last;
  - every creator uses the one definition;
  - the trigger guards every path, including `OR REPLACE`;
  - an old shape fails with a message naming `migrate-whitelist.py` or staging recreation.
- **AC3:**
  - every writer stores the helper's id;
  - merge changes only by the approved guard;
  - sync copies or computes the id, with the source check still the six columns;
  - re-runs keep the same ids.
- **AC4:** `ann_id` ids, `id_source`, and the refusal.
- **AC5:** the gate, naming `build-ann-index.py`.
- **AC6:** every listed reader uses `ann_id`, and an old cache is never read.
- **AC7:** `ann_id` throughout, with output keys and selection unchanged.
- **AC8:** the stale-index test.
- **AC9:** the smoke test assertion and the docs.
- **Consistency:** CLIs unchanged, the refusal style followed, `normalize_host` reused, each file's style kept.

The two departures (the transaction in the migration, and the AC8 test living in `tests/active`) are named above.

