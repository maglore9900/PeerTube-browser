# 17-stable-ann-ids

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-17-stable-ann-ids.record.md`._

## Requirements

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

## High-level plan

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

## Impacts

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

## Documentation to update

- [ ] `DATA_BUILD.md` - - **Line 13:** "random rowid cache" becomes the random ANN-id cache.
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
- [ ] `DEPLOYMENT.md` - - **Line 42:** add the one-time ANN-id cutover (stop, migrate, build index, start) and that the Engine refuses to start on an index whose sidecar `id_source` is not `video_embeddings.ann_id`.
- **Triage table:** add a row for that startup refusal, with the fix `build-ann-index.py`. Add one for the `migrate-whitelist.py` message from `build-ann-index`, merge and `build-video-embeddings`.
- **Line 421:** random-cache text is unaffected beyond a first start rebuilding an old-shape cache.
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - - **Cutover:** the prerequisite one-time migrate and index rebuild before the first updater run on new code.
- **`--resume-staging` (lines 48, 149, 186):** a pre-cutover staging DB now fails with the AC2 message and must be recreated by running without the flag.
- **Line 61:** the ANN rebuild writes `id_source: video_embeddings.ann_id`.
- **Merge:** it refuses an unmigrated prod or staging.
- **Line 197:** `--inject-replace-embedding-for-test` keeps the row's `ann_id`.
- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - - **Validations list (around line 115):** add the sidecar `id_source` assertion.
- **Source DB:** note that it must be migrated, since mini-prod copies its schema.
- [ ] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - - **Line 130:** "has no `random_rowids` table" becomes `random_ann_ids`. An old-format file counts as having no table.
- **Line 140:** "The cache holds only rowids (`random_rowids`)" becomes ANN ids (`random_ann_ids`), resolved to rows by `ann_id`. Mention the hash-uniform sampling window.
- [ ] `engine/server/api/recommendations/docs/OVERVIEW.md` - - **Line 15:** "drops rowids already seen" / "unseen rowid" becomes ANN ids.
- **Line 69:** "Holds a prebuilt list of rowids" becomes ANN ids (`random_ann_ids`).
- [ ] `engine/server/README.md` - Line 9 explains the `migrate-whitelist.py` requirement for `videos.language`. Optionally add that the Engine also refuses to start until the ANN-id cutover (migrate plus index rebuild) has run, pointing at DATA_BUILD.
- [ ] `docs/project/issues/08-stable-ann-ids.md` - At close: set `Status: enhancement, complete` and move to `docs/project/issues/archive/`, per the triage labels.

## Implementation plan

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

### Phases

_Not yet written - Step 4 owns it._

