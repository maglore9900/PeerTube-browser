# Stable ANN ids

## Requirements

### Asked for

Issue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2). The FAISS index and every reader that turns an id back into an embedded video switch from `video_embeddings.rowid` to a deterministic `ann_id` derived from `(video_id, instance_domain)`. ADR-0006 records the decision. `CONTEXT.md` defines **ANN id**.

### Purpose

Correctness. `video_embeddings` can change without an index rebuild following, or with the rebuild failing: a merge, a host purge, a whole-table reload, a `--force` re-embed, a migration. In every such case the index must never return the wrong video. At most it misses videos it has not indexed yet. The build must not block later incremental index add or remove (F3/F4-M2), and it does not build them.

### What the current code does (checked against the tree and the live DB, read-only)

Re-checked against the tree when issue 08 was re-triaged after plans 19-23. Line numbers are from that check.

- `build-ann-index.py:250-256` calls `add_with_ids` with `video_embeddings.rowid` and writes `id_source: "video_embeddings.rowid"` (line 284). The live sidecar `engine/server/db/whitelist-video-embeddings.faiss.json` reads the same: 897,889 vectors, model `paraphrase-multilingual-MiniLM-L12-v2`, built 2026-10-01.
- Measured on the dataset before its rebuild (commit 57c8417): 890,052 `video_embeddings` rows with rowids exactly 1..890,052. The primary key is `(video_id, instance_domain)`, there were 1,548 hosts all already lowercase and trimmed, and every `video_id` is text.
- On that same pre-rebuild dataset, a 63-bit blake2b of `video_id::instance_domain` over all 890,052 keys gave 0 collisions, and no key hashed to 0. **Not re-measured on the rebuilt DB.** The build re-runs this measurement, and the host-normalisation check, before P1.
- Rowid-keyed readers:
  - `data/ann.py`: `compute_similar_items` (and its `ids > 0` filter), `search_index` (`exclude_rowid`), and `search_similar_above`, the up-next fallback search (issue 09) that `data/similarity_candidates.py` calls, which keeps rowid hits through the same `ids > 0` filter, excludes `seed["rowid"]` and calls `fetch_metadata` by rowid. The Engine's nprobe helpers (`_extract_ivf`, `get_nprobe`, `apply_nprobe`, `set_nprobe`) live in this file too, and `server.py` imports `set_nprobe` from it; `precompute-similar-ann.py` keeps its own `set_nprobe` copy.
  - `data/embeddings.py`: the seed's `rowid`/`exclude_rowid` in `resolve_seed` and in the three seed queries.
  - `data/metadata.py`: `fetch_metadata`, which selects `WHERE e.rowid IN (...)`.
  - `data/search.py`: `vector_candidates`.
  - `api/handlers/similar.py`: `_handle_vector_search`.
  - `data/random_cache.py` and `data/random_videos.py`: the `random_rowids` table.
  - `db/jobs/precompute-random-rowids.py`.
  - `db/jobs/precompute-similar-ann.py`: `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*` and the main loop.
- Not rowid-keyed, and outside this build: `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` (internal client reads, similarity candidates), and the remaining SQL reads in `random_videos.py` and `api/recommendations`, none of which read a rowid.
- Rowid-renumbering writers:
  - `build-video-embeddings.py`: DELETE under `--force`, then `INSERT OR REPLACE`.
  - `sync-whitelist.py`: `rebuild_content_tables` deletes the whole table, then does `INSERT ... SELECT`.
  - `merge-staging-db.py`, through `merge_rules.json` `INSERT_OR_REPLACE` on `video_embeddings`, copying the columns prod and staging share.
  - `whitelist_migrations.migrate_videos_schema`, which drops `video_embeddings`.
- `sync-whitelist.ensure_schema_compatibility` (line 194) requires the whitelist DB's `video_embeddings` columns to equal `EMBEDDING_COLUMNS` exactly. The copy from the source (lines 493-505) runs only when the source's columns are a superset of `EMBEDDING_COLUMNS`. Adding `ann_id` to that list without care therefore skips the embeddings of every source that lacks the column (R3).
- The updater (`updater-worker.py:1331-1425`) holds the blue/green deploy lock and stops the active Engine instance, the one named by the nginx upstream snippet (ADR-0009). It then merges, prunes denied hosts, recomputes popularity and builds the ANN, and restarts that instance in a `finally`. A failed ANN build therefore still restarts the Engine on the old index against the renumbered rows. The similarity precompute is no longer in that window: after the restart, `run_similarity_stage` builds a `.next.db` shadow from the prod DB and the new index, gates it and swaps it in (ADR-0008). A failed ANN build raises before that stage, so it is not reached.
- The Engine never writes the random cache before listening. At start it opens `random-cache.db` read-only through `open_random_cache_if_usable` (`random_cache.py:283-302`), which accepts any non-empty `random_rowids` table without checking its shape. Every build runs through `build_random_cache` (`random_cache.py:208-245`) into a per-pid temp file, which the Engine's background worker renames over the cache and swaps in. For when builds run (`DEFAULT_RANDOM_CACHE_REFRESH`, `--dev`, `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`) see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`. Under refresh off (`--dev`, `server.py:321`) a stored non-empty cache is served as it is. Under blue/green the two instances share `random-cache.db`, and during a deploy overlap both may build and rename over it. An instance running pre-build code can therefore open a cache written by post-build code, and the reverse. `precompute-random-rowids.py` keeps an `--out` that already holds `--size` rows, counted through `random_rowids_count` without checking their shape.
- The similarity cache uses the compact layout (`video_keys` + `similarity_sources`, CONTEXT **Video key**). Its int32 keys are local to one cache file and map to `(video_id, instance_domain)` text. It holds no rowids and no ANN ids.
- `videos_fts` joins `videos.rowid` as FTS5 external content. That link is not an ANN id.
- The Engine verifies the index sidecar at start in `embedding_space.assert_index_matches_embeddings`, which checks model and dimension today.
- Not checked: whether any deployed crawl DB that `sync-whitelist.py` reads from already holds `video_embeddings` rows. The requirement below covers both cases.

### Acceptance criteria

- **AC1:** One helper computes `ann_id` as blake2b with an 8-byte digest of `video_id + "::" + normalize_host(instance_domain)`, masked to 63 bits. The result is positive, non-zero and safe as a signed int64. The same key gives the same id in any process and any DB.
- **AC2:** `video_embeddings` carries `ann_id INTEGER NOT NULL` with a UNIQUE index.
  - A new `whitelist_migrations.migrate_video_embeddings_schema` rebuilds an existing table into that shape, filling the column from the helper through `create_function`. `migrate-whitelist.py` runs it.
  - Every job that creates the table creates the same shape.
  - A collision, including an id of 0, fails the write loudly. The write never probes for another id.
- **AC3:** Every writer stores the helper's `ann_id`.
  - `build-video-embeddings.py` computes it.
  - `merge-staging-db.py` preserves it.
  - `sync-whitelist.py` copies it when the source has the column and computes it when the source has embeddings without it, so an older crawl DB does not force a re-embed.
  - Re-running a writer, or replacing a row through `INSERT OR REPLACE`, leaves the video's `ann_id` unchanged.
- **AC4:** `build-ann-index.py` adds vectors with `ann_id` as their ids and writes `id_source: "video_embeddings.ann_id"`. It fails with a message naming `migrate-whitelist.py` when the column is missing.
- **AC5:** The Engine refuses to start when the index sidecar's `id_source` is not `video_embeddings.ann_id`, the same way it refuses a model mismatch today.
- **AC6:** These readers resolve embedded videos by `ann_id`:
  - similar: the seed and its exclusion, the ANN results, and raw vector search;
  - search's vector half;
  - `fetch_metadata`;
  - the random cache (`random_cache.py`, `random_videos.py`, `precompute-random-rowids.py`).

  A stored random cache in the old `random_rowids` shape is detected and repopulated, not read. Afterwards no reader resolves an embedded video by rowid.
- **AC7:** `precompute-similar-ann.py` uses `ann_id` for its index ids and its target lookup. Its output keys are unchanged, and its incremental selection stays keyed on `(video_id, instance_domain)`.
- **AC8 (the purpose, observed):** build an index, then renumber the DB's rows (a delete-and-reinsert of every row, as `sync-whitelist.py` does) or purge a host, with no index rebuild. Similar and search then return only videos whose identity matches the vector indexed for them.
- **AC9:** The updater's full cycle (merge → ANN build → precompute) runs on the new id source. `DATA_BUILD.md`, `DEPLOYMENT.md` and the updater docs carry the one-time migrate-then-rebuild step for existing DBs. `DEPLOYMENT.md` presents that step as a one-time outage and the one exception to blue/green: stop the active instance, run `migrate-whitelist.py`, run `build-ann-index.py`, start it (ADR-0006).

### Scope

In scope: AC1-AC9, including the random cache, as the operator decided.

Out of scope:
- incremental FAISS add or remove (F3/F4-M2);
- rebuilding or re-keying the similarity cache;
- `videos_fts`;
- backward compatibility with rowid indexes (a `rowid` sidecar is refused, not read);
- the crawler.

One build, correctness only, as the operator decided.

### Consistency constraints

- Job CLIs keep their current arguments.
- Refusal messages follow `data/embedding_space.py`: say what is wrong and name the command that fixes it.
- The migration follows the existing `migrate_*_schema` table-rebuild pattern in `whitelist_migrations.py`.
- Hosts go through the existing `data/moderation.normalize_host`.

### Conflicts

- The issue asks the updater to "keep ANN id consistency before rebuild/precompute". Under AC2 and AC3 the schema guarantees the column, so the updater needs no step of its own beyond the migration having run once. The operator accepted this reading by confirming AC2, AC3 and AC9.
- Test fixtures in 17 `tests/active` files reference `video_embeddings`: `conftest.py`, `test_blocks.py`, `test_db.py`, `test_dislike_profile.py`, `test_dislikes.py`, `test_frontend_reactions.py`, `test_internal_client_reads.py`, `test_metadata.py`, `test_precompute_random_rowids.py`, `test_precompute_similar_ann.py`, `test_profiles.py`, `test_random_cache.py`, `test_random_videos.py`, `test_search.py`, `test_similarity_candidates.py`, `test_video.py` and `test_videos.py`. Two job tests do too (`test-moderation-integration.py`, `test-orchestrator-smoke.py`). Those that insert rows without `ann_id` break under NOT NULL, and those that assert on rowids or `random_rowids` break with the readers. Both kinds change with the build. The build's impact inventory decides which file is which.
- ADR-0009 deploys blue/green with zero downtime, but this build's cutover stops the Engine. The operator decided this when issue 08 was re-triaged: the cutover is a one-time outage, recorded in ADR-0006, and no zero-downtime cutover is built.

## High-level plan

### Approach

A small module holds the one helper (for example `engine/server/data/ann_ids.py`), and jobs import it the way they already import `data.*`. The build runs in four phases.

- **P1: id, schema, writers (AC1-AC3).**
  - `migrate_video_embeddings_schema` rebuilds the table with `ann_id INTEGER NOT NULL`, filled through `create_function`, then creates the UNIQUE index. `migrate-whitelist.py` calls it through `migrate_whitelist_schema`.
  - `build-video-embeddings.init_schema` and `sync-whitelist`'s schema create the same shape.
  - `build-video-embeddings` computes the id per row.
  - `merge-staging-db` needs no code change, because it merges the columns prod and staging share, and staging (created by `build-video-embeddings`) now carries `ann_id`.
  - `sync-whitelist` copies `ann_id` when the source has it and computes it through the registered function otherwise.
- **P2: index build and gate (AC4, AC5).** `build-ann-index` reads and adds `ann_id` and writes the new `id_source`. `assert_index_matches_embeddings` also checks `id_source`.
- **P3: runtime readers (AC6, AC8).**
  - Seeds carry `ann_id` and `exclude_ann_id`.
  - `fetch_metadata` is keyed by `ann_id`, and `ann.py`, `search.vector_candidates` and `similar._handle_vector_search` follow it.
  - The random cache stores `ann_id` in a table with a new name, not in `random_rowids`. Pre-build code that opens a post-build cache during a blue/green overlap then sees `no_table` and serves from the DB, instead of accepting the file and failing on a missing `video_rowid` column. Whether the build scans by `ann_id` (hash order, a uniform sample) or keeps scanning a rowid window and only stores `ann_id` is left to the phase. `ensure_random_cache_schema` runs only on a build's fresh temp file, so it never sees a stored table. Old-shape detection goes in `open_random_cache_if_usable`, which treats a file holding only the old `random_rowids` table as unusable, so the Engine serves from the DB and runs a background build. `build_random_cache` never reads the stored file, so it cannot detect it. The precompute job's keep check also treats an old-shape `--out` as not kept, and `precompute-random-rowids.py` otherwise follows the cache.
- **P4: precompute and cycle (AC7, AC9).** `precompute-similar-ann` uses `ann_id` for its FAISS ids and its target lookup. The orchestrator smoke test runs the updater's full cycle on the new id source: merge and ANN build in the stopped window, then the similarity shadow build, gate and swap after the restart. The documentation in AC9 is the build's close-out, not a phase.

### Alternatives considered

- **A separate `ann_ids` mapping table:** every reader gains a join, and the mapping must be kept in step with embeddings on purge and reload. A column on `video_embeddings` has neither cost.
- **Pinning the rowid** (INTEGER PRIMARY KEY alias, UPSERT instead of INSERT OR REPLACE, `sync-whitelist` copying the source rowid): the cheapest option, but the id stays positional and differs between staging and prod, so it misses the purpose.
- **An assigned counter:** stable within one DB, but staging and prod assign different numbers, so every merge needs a remap.
- **Python `hash()`:** salted per process, so not deterministic.
- **xxhash:** a new dependency. blake2b is in the stdlib.
- **Full 64-bit ids:** negative ids clash with FAISS's `-1` empty result and the `ids > 0` filter in `ann.py`.
- **Probing for a free id on collision:** the id would depend on insertion order, which is the coupling this build removes.
- **ADD COLUMN plus backfill instead of a table rebuild:** it rewrites every row anyway, and it leaves the column nullable.
- **No migration (rebuild the dataset):** the operator chose the table rebuild.

### Risks

- **R1: the one-time migration rewrites about 1.4 GB of embedding blobs** (about 898k rows of 384 float32; `whitelist.db` is 3.5 GB in all). It needs about that much free disk and must run with the Engine stopped. Under blue/green this is an outage, which the operator accepted (ADR-0006).
- **R2: hard cutover.** On deploy, stop the active instance under the deploy lock and make sure the inactive one is stopped too. Then run `migrate-whitelist.py`, then `build-ann-index.py`, then start the active instance, which refuses a `rowid` sidecar. A blue/green deploy of post-build code against a `rowid` sidecar fails its health check and rolls back, so the migration and index rebuild must come first. Rolling back to pre-build code afterwards needs a `rowid` index rebuilt, because the new index overwrites the old file. The similarity cache needs no rebuild.
- **R3: a crawl DB whose embeddings lack `ann_id`, read by `sync-whitelist.py`.** P1 covers this by computing the id instead of skipping the copy. Both the exact check in `ensure_schema_compatibility` (line 194) and the source superset check at `sync-whitelist.py:493-499` read `EMBEDDING_COLUMNS`. Adding `ann_id` to it must not send a source without the column into skipping embeddings.
- **R4: fixture churn across up to 19 test files** (Conflicts). A shared fixture helper that computes `ann_id` keeps each file's change to its insert.
- **R5: a collision stops a dataset build or merge loudly, and recovery is manual.** The odds are about 4e-8 at about 900k keys. 0 collisions were measured on the pre-rebuild dataset, and the rebuilt one has not been measured yet.
- **R6: `fetch_metadata` and the precompute target lookup switch to `WHERE e.ann_id IN (...)`.** The UNIQUE index keeps these lookups indexed. A missing index would turn each into a full scan.
- **R7: `whitelist_migrations.migrate_videos_schema` drops `video_embeddings` when it rebuilds `videos`.** The recreated table must come back in the new shape.

### Limitations

- Purged or deleted videos stay in the index until the next rebuild. They are misses (no metadata row), not wrong videos.
- A re-embedded video keeps its old vector in the index until the next rebuild, but it still resolves to the right video.
- New videos are absent from the index until a rebuild. Incremental add and remove is F3/F4-M2.

### Tradeoffs accepted

- No backward compatibility with rowid indexes: the Engine refuses them.
- A one-time table rewrite of existing databases, done as a one-time Engine outage rather than a blue/green flip.
- Fixture changes across the test suite for the NOT NULL column.
