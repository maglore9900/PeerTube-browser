# Stable ANN ids

## Requirements

### Asked for

Issue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2). The FAISS index and every reader that turns an id back into an embedded video switch from `video_embeddings.rowid` to a deterministic `ann_id` derived from `(video_id, instance_domain)`. ADR-0006 records the decision. `CONTEXT.md` defines **ANN id**.

### Purpose

Correctness. `video_embeddings` can change without an index rebuild following, or with the rebuild failing: a merge, a host purge, a whole-table reload, a `--force` re-embed, a migration. In every such case the index must never return the wrong video. At most it misses videos it has not indexed yet. The build must not block later incremental index add or remove (F3/F4-M2), and it does not build them.

### What the current code does (checked against the tree and the live DB, read-only)

- `build-ann-index.py:250-256` calls `add_with_ids` with `video_embeddings.rowid` and writes `id_source: "video_embeddings.rowid"` (line 284). The live sidecar `engine/server/db/whitelist-video-embeddings.faiss.json` reads the same.
- The live `engine/server/db/whitelist.db` has 890,052 `video_embeddings` rows with rowids exactly 1..890,052. Its primary key is `(video_id, instance_domain)`, there are 1,548 hosts all already lowercase and trimmed, and every `video_id` is text.
- A 63-bit blake2b of `video_id::instance_domain` over all 890,052 keys gave 0 collisions, and no key hashed to 0.
- Rowid-keyed readers:
  - `data/ann.py`: `compute_similar_items` (and its `ids > 0` filter), `search_index` (`exclude_rowid`), and `search_similar_above`, the up-next fallback search, which keeps rowid hits through the same `ids > 0` filter, excludes `seed["rowid"]` and calls `fetch_metadata` by rowid. The Engine's nprobe helpers (`_extract_ivf`, `get_nprobe`, `apply_nprobe`, `set_nprobe`) live in this file too, and `server.py` imports `set_nprobe` from it; `precompute-similar-ann.py` keeps its own `set_nprobe` copy.
  - `data/embeddings.py`: the seed's `rowid`/`exclude_rowid` in `resolve_seed` and in the three seed queries.
  - `data/metadata.py`: `fetch_metadata`, which selects `WHERE e.rowid IN (...)`.
  - `data/search.py`: `vector_candidates`.
  - `api/handlers/similar.py`: `_handle_vector_search`.
  - `data/random_cache.py` and `data/random_videos.py`: the `random_rowids` table.
  - `db/jobs/precompute-random-rowids.py`.
  - `db/jobs/precompute-similar-ann.py`: `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*` and the main loop.
- Rowid-renumbering writers:
  - `build-video-embeddings.py`: DELETE under `--force`, then `INSERT OR REPLACE`.
  - `sync-whitelist.py`: `rebuild_content_tables` deletes the whole table, then does `INSERT ... SELECT`.
  - `merge-staging-db.py`, through `merge_rules.json` `INSERT_OR_REPLACE` on `video_embeddings`, copying the columns prod and staging share.
  - `whitelist_migrations.migrate_videos_schema`, which drops `video_embeddings`.
- The updater (`updater-worker.py:1040-1150`) stops the service, merges, rebuilds the ANN, precomputes, and restarts in a `finally`. So a failed ANN build restarts the Engine on the old index against the renumbered rows.
- The Engine never writes the random cache before listening. At start it opens `random-cache.db` read-only through `open_random_cache_if_usable` (`random_cache.py:283-302`), which accepts any non-empty `random_rowids` table without checking its shape. Every build runs through `build_random_cache` (`random_cache.py:208-245`) into a per-pid temp file, which the Engine's background worker renames over the cache and swaps in. For when builds run (`DEFAULT_RANDOM_CACHE_REFRESH`, `--dev`, `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`) see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`. Under refresh off (`--dev`, `server.py:316-319`) a stored non-empty cache is served as it is. `precompute-random-rowids.py` keeps an `--out` that already holds `--size` rows, counted through `random_rowids_count` without checking their shape.
- The similarity cache (`similarity_items`) is keyed by `(video_id, instance_domain)` text and holds no rowids.
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
- **AC9:** The updater's full cycle (merge → ANN build → precompute) runs on the new id source. `DATA_BUILD.md`, `DEPLOYMENT.md` and the updater docs carry the one-time migrate-then-rebuild step for existing DBs.

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
- Test fixtures in 9 `tests/active` files (`conftest.py`, `test_blocks.py`, `test_dislike_profile.py`, `test_dislikes.py`, `test_frontend_reactions.py`, `test_internal_client_reads.py`, `test_metadata.py`, `test_profiles.py`, `test_random_videos.py`) and 2 job tests (`test-moderation-integration.py`, `test-orchestrator-smoke.py`) insert into `video_embeddings` without `ann_id`. NOT NULL breaks them, so they change with the build.

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
  - The random cache stores `ann_id`. `ensure_random_cache_schema` runs only on a build's fresh temp file, so it never sees a stored table. Old-shape detection goes in `open_random_cache_if_usable`, which treats an old `random_rowids` table as unusable so the Engine serves from the DB and runs a background build. `build_random_cache` never reads the stored file, so it cannot detect it. The precompute job's keep check also treats an old-shape `--out` as not kept, and `precompute-random-rowids.py` otherwise follows the cache.
- **P4: precompute and cycle (AC7, AC9).** `precompute-similar-ann` uses `ann_id` for its FAISS ids and its target lookup. The orchestrator smoke test runs the updater's full cycle on the new id source. The documentation in AC9 is the build's close-out, not a phase.

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

- **R1: the one-time migration rewrites about 1.4 GB of embedding blobs.** It needs about that much free disk and must run with the Engine stopped.
- **R2: hard cutover.** On deploy the order is `migrate-whitelist.py`, then `build-ann-index.py`, then start the Engine, which refuses a `rowid` sidecar. The similarity cache needs no rebuild.
- **R3: a crawl DB whose embeddings lack `ann_id`, read by `sync-whitelist.py`.** P1 covers this by computing the id instead of skipping the copy. The source-column check at `sync-whitelist.py:492-498` must not route this case into skipping embeddings.
- **R4: fixture churn across 11 test files** for NOT NULL. A shared fixture helper that computes `ann_id` keeps each file's change to its insert.
- **R5: a collision stops a dataset build or merge loudly, and recovery is manual.** The odds are about 4e-8 at the current 890k keys, and 0 collisions were measured.
- **R6: `fetch_metadata` and the precompute target lookup switch to `WHERE e.ann_id IN (...)`.** The UNIQUE index keeps these lookups indexed. A missing index would turn each into a full scan.
- **R7: `whitelist_migrations.migrate_videos_schema` drops `video_embeddings` when it rebuilds `videos`.** The recreated table must come back in the new shape.

### Limitations

- Purged or deleted videos stay in the index until the next rebuild. They are misses (no metadata row), not wrong videos.
- A re-embedded video keeps its old vector in the index until the next rebuild, but it still resolves to the right video.
- New videos are absent from the index until a rebuild. Incremental add and remove is F3/F4-M2.

### Tradeoffs accepted

- No backward compatibility with rowid indexes: the Engine refuses them.
- A one-time table rewrite of existing databases.
- Fixture changes across the test suite for the NOT NULL column.
