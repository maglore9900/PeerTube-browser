# 42-ann-ids-b-readers-cutover

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/44-42-ann-ids-b-readers-cutover.record.md`._

## Requirements

### Asked for

Issue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2), the second of two builds. Plan 17 (`docs/project/plans/17-stable-ann-ids.md`) went through build 19 up to its Step 6. It was then split into plan A (`docs/project/plans/41-ann-ids-a-schema-writers.md`, built in record `docs/project/plans/43-41-ann-ids-a-schema-writers.record.md`) and this plan B (`docs/project/plans/42-ann-ids-b-readers-cutover.md`, built in record `docs/project/plans/44-42-ann-ids-b-readers-cutover.record.md`). ADR-0006 (`docs/project/adr/0006-derived-ann-ids.md`) records the id decision, and `CONTEXT.md` defines **ANN id**.

Plan B moves the FAISS index, and every reader that turns an id back into an embedded video, from `video_embeddings.rowid` to the `ann_id` that plan A stores. It also makes the Engine refuse a rowid index. This plan is the cutover: its readers, its index build and its gate merge together.

The operator confirmed in this Step 1 that plan A is complete in this worktree. Plan A's code is the base plan B builds on, and the single merge of this worktree carries both plans. Everything else was settled with the operator in build 19 (Steps 1-5; that record is now in `delete_me/`), narrowed to plan B. The operator approved these requirements in this Step 1.

### Purpose

Correctness. `video_embeddings` can change without an index rebuild following, or while the rebuild fails: a merge, a host purge, a whole-table reload, a `--force` re-embed, a migration. In every such case the index must never return the wrong video. At most it misses videos it has not indexed yet. The build must not block later incremental index add or remove (F3/F4-M2), and it does not build them.

### Current state (verified against the tree in this Step 1)

**Plan A as delivered in the worktree, which wins over the carried draft:**
- `engine/server/data/ann_ids.py` exports:
  - `ANN_ID_MASK`;
  - `compute_ann_id(video_id, instance_domain)`;
  - `create_video_embeddings_table(conn)`, which holds `ann_id INTEGER NOT NULL CHECK (ann_id > 0)`;
  - `create_ann_id_guards(conn)`, which creates the UNIQUE `idx_video_embeddings_ann_id` and the BEFORE INSERT trigger `video_embeddings_ann_id_collision`;
  - `assert_video_embeddings_has_ann_id(conn, schema="main")`, whose RuntimeError names `{schema}.video_embeddings`, `engine/server/db/jobs/migrate-whitelist.py` and `--resume-staging`;
  - `ensure_video_embeddings_schema(conn)`.
- **`ANN_ID_SOURCE` does not exist**, and there is no `register_ann_id_function`. `sync-whitelist.py` and `whitelist_migrations.py` each register `ann_id_of` inline.
- `engine/server/db/jobs/migrate-whitelist.py` exists, and the migration keeps rowids.
- Writers that store `ann_id`: `build-video-embeddings.py`, `sync-whitelist.py`, `merge-staging-db.py` (old-shape guard on `main` and `stage`), and `updater-worker.inject_replace_embedding_for_test`.
- `engine/server/db/jobs/tests/test-orchestrator-smoke.py` already imports `ensure_video_embeddings_schema` and calls it in `copy_and_prune_prod`, so mini-prod has the guards. `validate_outputs` checks `meta_total` (lines 766-772) and has no `id_source` check.
- `tests/active/conftest.py` does **not** re-export `compute_ann_id`. It puts only `client/backend` on `sys.path`. `tests/active/test_video.py` inserts `engine/server` and `engine/server/api` on `sys.path` itself and runs `from data.ann_ids import compute_ann_id` (line 60). Its inserts at lines 544-545 already carry `ann_id`. `similars_stack` still adds to the index by rowid.
- `tests/active/test_ann_ids.py` does **not** exist. Plan A's checkpoints remain in `tests/tmp/test_41_ann_ids_a_schema_writers_phase1..4.py`.
- None of the docs mention `ann_id` (`DATA_BUILD.md`, `DEPLOYMENT.md`, `engine/server/README.md`, `engine/server/db/jobs/docs/*.md`).
- The worktree has no `engine/server/db/whitelist.db`, index or sidecar. Engine-backed tests use the shared dataset.

**What plan B changes (still rowid-keyed today):**
- `engine/server/db/jobs/build-ann-index.py`:
  - `EmbeddingRow.rowid` (line 34) and `iter_embeddings` (line 52).
  - The add query `SELECT rowid, embedding, embedding_dim FROM video_embeddings` (line 250) and `ids = ... item.rowid` (line 252).
  - `meta["id_source"] = "video_embeddings.rowid"` (line 284).
  - There is no old-shape check. `main()` connects (line 212), then calls `resolve_embedding_space` (line 215).
  - `fetch_training_samples` samples by `rowid % step` (lines 73-81).
  - `server_dir` is on `sys.path`.
- `engine/server/data/embedding_space.py`: `assert_index_matches_embeddings(index_path, index, dim, model_name)` checks that the sidecar exists and is readable, then the model, the meta dimension and `index.d`. It does not check `id_source`. Its callers are `api/server.py` at Engine start and `precompute-similar-ann.py`.
- `engine/server/data/ann.py`:
  - `compute_similar_items` (lines 38-64): the `> 0` filter, the log key `ann_rowids`, and `seed["rowid"]`.
  - `search_similar_above` (lines 112-136): `seed.get("rowid")` and the `> 0` filter.
  - `search_index(index, vector, limit, exclude_rowid)` (lines 147-165).
  - The nprobe helpers do not change.
- `engine/server/data/embeddings.py`:
  - `resolve_seed` returns `exclude_rowid` (lines 73, 79, 86, 89) and `rowid` (line 91).
  - Four `e.rowid AS rowid` selects (lines 123, 151, 217, 241).
  - `_seed_from_row` returns `"rowid"` (line 181).
- `engine/server/data/metadata.py`: `fetch_metadata(conn, rowids, ...)`, `e.rowid AS rowid`, `WHERE e.rowid IN (...)`, `result[int(row["rowid"])]` (lines 16-77).
- `engine/server/data/search.py`: `vector_candidates` (lines 191-205). `VIDEO_ROW_SQL`'s `v.rowid` (line 52) and the `videos_fts` join (line 158) are the FTS link and do not change.
- `engine/server/api/handlers/similar.py`: `_handle_vector_search` uses `seed["exclude_rowid"]`.
- `engine/server/data/random_cache.py`:
  - `RANDOM_CACHE_CHECK_SQL` (line 19).
  - The table `random_rowids(position, video_rowid)` (lines 35-37).
  - `random_rowids_count` (lines 43-48).
  - `populate_random_cache` (lines 51-194). This covers the reuse path, the count and delete, and the source `MIN/MAX(rowid)` stats. The unfiltered window is `rowid >= ? ORDER BY rowid LIMIT ?` with wrap-around. The filtered `scan_range` uses `e.rowid` and advances with `current = rowid + 1`.
  - `build_random_cache` (line 208), `open_random_cache_if_usable` (lines 283-302), and `fetch_random_rowids` (lines 329-344), which reads `video_rowid`.
- `engine/server/data/random_videos.py`: imports `fetch_random_rowids` (line 10). `fetch_random_rows_from_cache` (lines 424-443) passes rowids to `fetch_metadata`.
- `engine/server/db/jobs/precompute-random-rowids.py`:
  - imports `random_rowids_count` (line 16);
  - description "Precompute random rowid cache." (line 23);
  - `--size` help "Rowids to sample." (line 34);
  - keep check `random_rowids_count(existing_db) or 0` (line 69).
- `engine/server/db/jobs/precompute-similar-ann.py`: `iter_embedding_rows_by_rowids`, `fetch_similarity_targets`, `fetch_similarity_targets_chunked`, the pending-selection queries (`SELECT e.rowid` ×2), the full-mode SELECT, and the main loop's self-exclusion. In all, 38 `rowid` mentions.
- `engine/server/api/server_config.py`: the comment above `DEFAULT_RANDOM_CACHE_SIZE` says "random rowids".
- `api/server.py:345` sets `random_cache_startup_build = random_cache_refresh or random_cache_db is None`, so a cache judged unusable always gets a background build. With refresh off (`--dev`), a stored non-empty cache is served as it is.
- **Unchanged.**
  - Rowid uses in `data/users.py` and `data/interaction_events.py` concern other tables.
  - The similarity cache is keyed by `(video_id, instance_domain)`.
  - `videos_fts` links through `videos.rowid`, which is not an ANN id.
  - The updater stops the service, merges, rebuilds the ANN, precomputes, and restarts in a `finally`, so a failed ANN build restarts the Engine on the old index.

### Acceptance criteria

- **AC4, the index build.**
  - `build-ann-index.py` calls `assert_video_embeddings_has_ann_id(conn)` right after connecting and before `resolve_embedding_space`. When the column is missing, it fails with plan A's message, which names `migrate-whitelist.py`.
  - It adds vectors with `ann_id` as their FAISS ids: the add query becomes `SELECT ann_id, embedding, embedding_dim FROM video_embeddings`, `EmbeddingRow.rowid` becomes `ann_id`, and the ids are built as `np.int64`.
  - It writes `id_source: "video_embeddings.ann_id"` (`ANN_ID_SOURCE`) to the sidecar.
  - `fetch_training_samples` keeps `rowid % step`. It is a sampling cursor, never an identity, and that is a named simplification.
- **AC5, the Engine gate.**
  - `assert_index_matches_embeddings` raises RuntimeError when the sidecar's `id_source` is not `video_embeddings.ann_id`, a missing `id_source` included. The check sits next to the model check, and it refuses the same way the model check does.
  - The message says what is wrong (the index's id source, or `<unset>`, against the `ann_id` source the readers resolve) and names `build-ann-index.py`.
  - The Engine therefore refuses to start on a rowid index, and `precompute-similar-ann.py` refuses one too.
  - The module docstring gains the id contract.
- **AC6, the readers.** These resolve embedded videos by `ann_id`:
  - **Similar.**
    - The seed keys `rowid` and `exclude_rowid` become `ann_id` and `exclude_ann_id` in all of `resolve_seed`'s return shapes and in `_seed_from_row`. The four `e.rowid AS rowid` selects in `embeddings.py` become `e.ann_id AS ann_id`.
    - The ANN results in `ann.py` move: `compute_similar_items` (the `> 0` filter stays, and its self check uses `seed["ann_id"]`), `search_similar_above` (`seed.get("ann_id")`, with the `> 0` filter kept), and `search_index`, whose fourth positional parameter becomes `exclude_ann_id`.
    - `similar._handle_vector_search` moves too.
    - Every consumer of the seed keys is renamed together: `ann.py`, `similar.py`, `similarity_candidates`, and the recommendation sources `ann_similar_from_likes.py` and `cached_similar_from_likes.py` that pass seeds through.
  - **Search.** The vector half of search (`search.vector_candidates`) moves.
  - **Metadata.** `fetch_metadata(conn, ann_ids, ...)` uses `e.ann_id AS ann_id ... WHERE e.ann_id IN (...)`, served by the UNIQUE index. Its output dicts still carry no id.
  - **Random cache.** `random_cache.py`, `random_videos.py` and `precompute-random-rowids.py` move. The table becomes `random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)`, and the helpers are renamed:
    - `random_rowids_count` becomes `random_ann_ids_count`;
    - `fetch_random_rowids` becomes `fetch_random_ann_ids`.
    `RANDOM_CACHE_CHECK_SQL` names the new table. The unfiltered build draws a random start in `[MIN(ann_id), MAX(ann_id)]`, then takes the next rows in `ann_id` order with wrap-around. The filtered `scan_range` ranges over `ann_id`.
  - **Old-shape random cache.** A stored cache in the old `random_rowids` shape is detected and repopulated, never read:
    - `random_ann_ids_count` returns None on it, so `open_random_cache_if_usable` returns None and the Engine starts a background build.
    - The precompute keep check counts 0, so the job rebuilds.
    - A swap can only install a file holding `random_ann_ids`.
    Detection is by table name, not by shape. That is a named simplification. Its ceiling: a future reshape under the same name would need a `PRAGMA table_info` check in `random_ann_ids_count`.
  - **End state.** Afterwards no reader resolves an embedded video by rowid.
- **AC7, the similarity precompute.**
  - `precompute-similar-ann.py` uses `ann_id` for its FAISS ids and its target lookup:
    - `iter_embedding_rows_by_rowids` becomes `iter_embedding_rows_by_ann_ids`;
    - `fetch_similarity_targets*` take `ann_ids` and return `{ann_id: row}`;
    - the pending-selection queries and the full-mode SELECT carry `ann_id`;
    - self-exclusion becomes `ann_id_int == row["ann_id"]`.
  - Its output keys and its incremental selection stay on `(video_id, instance_domain)` and the `video_keys` joins.
  - Its source connection stays `mode=ro` and registers nothing.
- **AC8, the purpose observed in a test.**
  - Build an index on `ann_id`. Then, with no index rebuild, run three cases: (A) delete every row and reinsert them in reverse order, (B) purge a host through `purge_host_data`, (C) insert a new, unindexed video.
  - After each case, every hit from similar (`ann.compute_similar_items`) and from search (`search.vector_candidates`) resolves to the video whose vector carries that id, or is dropped.
  - The purged host's videos are absent, and the new video is absent rather than substituted.
- **AC9, the cycle and docs (plan B's part).**
  - The updater's full cycle (merge, ANN build, precompute) runs on the new id source. That is observed through the orchestrator smoke test: `validate_outputs` asserts `meta.get("id_source") == ANN_ID_SOURCE` next to the `meta_total` check and records `checks["ann_id_source"]`.
  - The docs carry three things: the cutover (stop the Engine, run `build-ann-index.py`, start), the startup refusal, and the random cache's `random_ann_ids` shape.

### Scope

**In scope:**
- AC4-AC8 and plan B's part of AC9.
- Adding `ANN_ID_SOURCE = "video_embeddings.ann_id"` to `engine/server/data/ann_ids.py`, which is the one place the sidecar value is defined.
- Creating `tests/active/test_ann_ids.py` with plan B's AC4/AC5 cases.
- The issue closes with this plan.

**Out of scope:**
- Everything plan A delivered: the id, the schema, the migration, the writers and the mini-prod guards.
- Promoting plan A's `tests/tmp/test_41_*` checkpoints into `tests/active`, and plan A's doc changes. They remain plan A's.
- Incremental FAISS add or remove (F3/F4-M2).
- The similarity cache, `videos_fts` and the crawler.
- Backward compatibility with rowid indexes. A `rowid` sidecar is refused, not read.

### Consistency constraints

- Job CLIs keep their current arguments. `precompute-random-rowids.py` keeps its file name; only its description and `--size` help text change.
- Refusal messages follow `data/embedding_space.py`: say what is wrong, and name the command that fixes it.
- New code matches the style of the file it lands in.
- Every id comes from plan A's `compute_ann_id`, or from the stored `ann_id`. `ANN_ID_SOURCE` is the only spelling of the sidecar value, used by `build-ann-index.py`, `embedding_space.py` and the smoke test.
- `data/ann_ids.py` stays stdlib-only (plus `data.moderation`), so jobs and tests on the system interpreter (`test_precompute_random_rowids` runs the job under `sys.executable`) can import it.
- Ids up to 2^63 exceed JavaScript's safe integer range. No response puts an `ann_id` into JSON; if one ever does, it must be a string.
- Tests that need `compute_ann_id` use one pattern. Either they follow `test_video.py` (insert `engine/server` on `sys.path`, then `from data.ann_ids import compute_ann_id`), or Step 5 adds the `compute_ann_id` re-export to conftest that plan A planned. They are not mixed.
- Smallest thing that works: no new module beyond the tests, and no new dependency.

### Conflicts

- **One merge, not three.** Readers on `ann_id` against a rowid index return wrong videos, and so does an `ann_id` index against rowid readers. The three phases therefore land in one build and one merge, and no phase is merged alone. Readers come before the gate so that no earlier checkpoint goes red when a later phase lands.

### Tests

- **Locations.** Active tests live in `tests/active`, scratch work in `tests/tmp`, and job tests in `engine/server/db/jobs/tests/`. The record is `tests/last_test_validation.json`, which the test run regenerates; nobody edits it by hand. The output is `tests/last_test_output.txt`.
- **Baseline suite state.** The pre-build baseline taken at Step 0 exited 0 (`code: 0`, `variant: false`). Change-based selection ran 1 of 51 groups (`test_search_fusion.py`, 10 passed).
- **New `tests/active/test_ann_ids.py`** (AC4/AC5).
  - Run `build-ann-index.py` as a job subprocess under ENGINE_PY, on a tmp DB built through `ensure_video_embeddings_schema`. Then an ENGINE_PY child loads the written index.
  - The index's stored id set (`faiss.vector_to_array(index.id_map)`) must equal the DB's `ann_id` set exactly. Its sidecar `id_source` must equal `video_embeddings.ann_id`.
  - On an old six-column table, the job must exit non-zero naming `migrate-whitelist.py`.
  - `assert_index_matches_embeddings` must pass with the written sidecar. With `id_source: video_embeddings.rowid` it must raise naming `build-ann-index.py`, and with no `id_source` it must raise.
- **New `tests/active/test_stale_ann_index.py`** (AC8).
  - An ENGINE_PY child (the `_CHILD` precedent in `test_search.py` and `test_popular_videos.py`) builds a tmp DB: `videos`, `channels`, and `video_embeddings` via `ensure_video_embeddings_schema`. It builds an `IDMap2,IVF1,Flat` index on `ann_id` and records `ann_id -> (video_id, host)`.
  - After each of cases A, B and C, it calls `ann.compute_similar_items` and `search.vector_candidates` through a stub server. The stub carries `index`, `index_lock`, `db`, `db_lock`, `normalize_queries=False`, the `similarity_*` defaults, and a `query_encoder` with `enabled=True` returning a fixed vector.
  - Per case and per reader, every returned `(video_id, instance_domain)` equals the identity recorded for the id that produced it. That excludes a rowid join, which case A would expose.
  - In case B no purged-host video appears. In case C the new video is absent.
- **Existing harnesses extended.**
  - `test_precompute_similar_ann.py` (AC7). Every source's neighbour keys map to the videos whose vectors carry the hit ids, which excludes a rowid-keyed target lookup. No source lists itself.
  - `test_precompute_random_rowids.py` (AC6):
    - the `--out` holds `random_ann_ids` and no `random_rowids`;
    - every cached id is in the source's `ann_id` set, and the count equals `--size`;
    - an `--out` already holding an old `random_rowids` table with `--size` rows is rebuilt into `random_ann_ids`.
- **Fixture churn.**
  - `test_metadata.py`: the fixture DDL gains `ann_id`, inserts carry `compute_ann_id`, and `_nsfw_metadata` selects `ann_id`.
  - `test_random_videos.py`:
    - `NSFW_EMBEDDINGS_TABLE` gains `ann_id`, and `_video_db` maps labels to computed ids;
    - `_cache_owner` creates `random_ann_ids` and monkeypatches `fetch_random_ann_ids` on both modules;
    - the docstring changes;
    - CTAS copies from `whitelist.db` are unchanged.
  - `test_random_cache.py`:
    - `_source_db` gains `ann_id`, and `random_rowids` becomes `random_ann_ids` throughout;
    - order or rowid-window expectations become sets of computed ids;
    - Engine cases map rows back with `SELECT ann_id`;
    - the "no table" probe of `open_random_cache_if_usable` uses an old-format `random_rowids` file, which pins AC6's old-shape case.
  - `test_db.py`: the source gains `ann_id`, `_seed_cache` and `CHECK_SQL` use `random_ann_ids`, it imports `fetch_random_ann_ids`, and `SEEDED_ROWIDS` becomes computed ids.
  - `test_precompute_random_rowids.py`: the source gains `ann_id`, and assertions use the computed ids.
  - `test_precompute_similar_ann.py`: the fixture table gains `ann_id`, `INDEX_BUILDER` adds with `SELECT ann_id, embedding`, and the sidecar gains `"id_source": "video_embeddings.ann_id"`. Phase 1 makes this change, before phase 3's gate. `SHORT_ROWID` and `v{n}` stay as labels only.
  - `test_video.py`: only `similars_stack`, which selects `ann_id` for `add_with_ids`. The inserts are already plan A's.
- **No change needed.**
  - `test_internal_client_reads`, `test_search`, `test_similarity_candidates` and `test_videos` never reach `ann_id`.
  - `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles` and `test_frontend_reactions` are SELECT-only.
  - `test-moderation-integration.py` is unchanged.
  - Archived tests under `tests/archive/` stay as they are.
- **`tests/config.json`:**
  - add groups for `test_ann_ids.py` and `test_stale_ann_index.py`, mapped to the sources they exercise;
  - add `engine/server/data/ann_ids.py` to `test_metadata`, `test_random_cache`, `test_random_videos`, `test_db`, `test_precompute_random_rowids` and `test_precompute_similar_ann`;
  - add `engine/server/data/embedding_space.py` to `test_ann_ids` and `test_precompute_similar_ann`.
- **Engine-backed tests need the shared dataset cut over.** The session `engine` fixture starts the real Engine on the shared `whitelist.db` and its index. Once the gate lands, the Engine exits at start until that dataset is migrated and its index rebuilt on `ann_id`. The operator does this before the final full-suite run.

### Documentation to update

- **`DATA_BUILD.md`:**
  - line 13: "random rowid cache" becomes the random ANN-id cache;
  - the cutover: after the migration, stop the Engine, run `build-ann-index.py`, start the Engine; a stored `random-cache.db` rebuilds itself;
  - line 232: the index uses `video_embeddings.ann_id` as ids, with `id_source`, plus the `migrate-whitelist.py` refusal;
  - line 290: "random rowid pool" changes;
  - line 335: `random_rowids` becomes `random_ann_ids`.
- **`DEPLOYMENT.md`:**
  - line 42: the cutover (stop, build the index, start), and the startup refusal when the sidecar `id_source` is not `video_embeddings.ann_id`;
  - triage rows for that refusal (fixed by `build-ann-index.py`) and for `build-ann-index`'s `migrate-whitelist.py` message;
  - line 421: the first start rebuilds an old-shape random cache.
- **`engine/server/db/jobs/docs/UPDATER_WORKER.md`:**
  - line 61: the ANN rebuild writes `id_source: video_embeddings.ann_id`;
  - the index rebuild comes before the first updater run on the new code.
- **`engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`:** the validations list (around line 115) gains the `id_source` assertion.
- **`engine/server/api/recommendations/docs/LAYER_PARAMS.md`:**
  - line 130: `random_ann_ids`, and an old-format file counts as having no table;
  - line 140: the cache holds ANN ids (`random_ann_ids`), resolved by `ann_id`, drawn through a hash-uniform window.
- **`engine/server/api/recommendations/docs/OVERVIEW.md`:**
  - line 15: "rowids already seen" and "unseen rowid" become ANN ids;
  - line 69: the prebuilt list holds ANN ids (`random_ann_ids`).
- **`engine/server/README.md`:** the Engine refuses to start until the index is rebuilt on `ann_id`, with a pointer to DATA_BUILD.
- **Optional:** the comment at `scripts/run-reembed.sh` line 28 may also mention `id_source`.
- **`docs/project/issues/08-stable-ann-ids.md`:** at close, set `Status: enhancement, complete` and move the issue to `docs/project/issues/archive/`.

### Risks and limitations accepted

- **Hard cutover.** The Engine refuses a `rowid` sidecar, so the deploy is stop, `build-ann-index.py`, start. The similarity cache needs no rebuild, and the random cache rebuilds itself.
- **Purged or deleted videos** stay in the index until the next rebuild. They come back as misses (no metadata row), never as wrong videos.
- **A re-embedded video** keeps its old vector in the index until the next rebuild, but still resolves to the right video.
- **New videos** stay out of the index until a rebuild.
- **The unfiltered random draw** becomes a hash-uniform sample rather than a block of rows in insertion order.
- **Partial seed-key rename.** `seed.get("rowid")` silently stops self-exclusion, and `seed["rowid"]` raises KeyError. Every consumer is renamed together.
- **A missed `rowid` in `build-ann-index.py`** produces an index the gate accepts by its sidecar but with wrong ids. The AC4 test compares the stored id set with the DB's `ann_id` set.
- **ANN training** samples by `rowid % step`, which affects only which vectors train the quantizer.
- **Random-cache detection** is by table name.

### Coordination the operator does

- **Before the final full-suite run,** with the Engine stopped: run `engine/server/db/jobs/migrate-whitelist.py` on the shared dataset if it has not been run yet, then `build-ann-index.py`, then start the Engine.
- **The smoke test's `id_source` assertion** needs a migrated `--source-db`. The operator runs it manually.

### Phases proposed in build 19, for this build's Step 6 to re-derive

1. **Readers and similarity precompute on ann_id.**
   - Files: `data/embeddings.py`, `ann.py`, `metadata.py`, `search.py`, `api/handlers/similar.py`, `db/jobs/precompute-similar-ann.py`, `tests/active/test_stale_ann_index.py` (new), `test_precompute_similar_ann.py` (sidecar gains `id_source` here), `test_metadata.py`, `test_video.py` (`similars_stack`), `tests/config.json`.
   - Checkpoint: AC8 through the ENGINE_PY child, and AC7 through the precompute harness.
2. **Random cache on ann_id.**
   - Files: `data/random_cache.py`, `random_videos.py`, `db/jobs/precompute-random-rowids.py`, `api/server_config.py`, `test_random_cache.py`, `test_random_videos.py`, `test_db.py`, `test_precompute_random_rowids.py`, `tests/config.json`.
   - Checkpoint: the precompute job subprocess writes `random_ann_ids` with source ids and rebuilds an old `random_rowids` file.
3. **Index build and Engine gate.**
   - Files: `data/ann_ids.py` (`ANN_ID_SOURCE`), `db/jobs/build-ann-index.py`, `data/embedding_space.py`, `db/jobs/tests/test-orchestrator-smoke.py` (`id_source` assertion), `tests/active/test_ann_ids.py` (new), `tests/config.json`.
   - Checkpoint: the AC4 id-set and sidecar checks, and the AC5 refusals.


## High-level plan

### Approach

Plan B is a rename-and-rekey of every place that turns a FAISS id back into a video. It puts the readers, the index build and the Engine gate onto the `ann_id` that plan A already stores, and merges them as one unit. I read the tree to confirm the settled current state: `ann_ids.py` as delivered, `build-ann-index.py`, `embedding_space.py`, `ann.py`, `embeddings.py`, `metadata.py`, `search.vector_candidates`, `random_cache.py`, `random_videos.fetch_random_rows_from_cache`, `precompute-random-rowids.py` and the `precompute-similar-ann.py` selection and target code. Two findings narrow the work:

- The recommendation sources (`ann_similar_from_likes.py`, `cached_similar_from_likes.py`) and `similarity_candidates` never read an id key. They only pass the seed dict on to `compute_similar_items` or the handler. So "renaming every consumer together" means editing the producers (`embeddings.py`) and the readers of the key (`ann.py`, `similar.py`), plus a grep that proves no other `"rowid"` or `"exclude_rowid"` key reader is left under `engine/server/api` and `engine/server/data`.
- No response carries an id. The handler sends `seed["meta"]` as the JSON `seed` payload, and it holds only `video_id`, `instance_domain`, `channel_id` and `title`. `fetch_metadata`'s output dicts carry no id. The JS safe-integer constraint therefore holds with no extra work.

**AC4, the index build.** In `build-ann-index.py`:

- `main()` calls `assert_video_embeddings_has_ann_id(conn)` right after `sqlite3.connect`, before `resolve_embedding_space`. An old six-column table fails with plan A's message, which names `migrate-whitelist.py`.
- `EmbeddingRow.rowid` becomes `ann_id`, and `iter_embeddings` unpacks `ann_id`.
- The add query selects `ann_id, embedding, embedding_dim`. The ids array stays `np.int64`, and every `ann_id` fits there because it is masked to 63 bits and positive by CHECK.
- The sidecar's `id_source` is the new constant `ANN_ID_SOURCE` from `data/ann_ids.py`. That constant is one string, so the module stays stdlib-only.
- `fetch_training_samples` is left on `rowid % step`, a named simplification (see Tradeoffs).

**AC5, the Engine gate.** `assert_index_matches_embeddings` imports `ANN_ID_SOURCE` and checks `meta.get("id_source")` right after the model check:

- The check is written in the same style as the model check. The message names the index's source, or `<unset>` when the key is missing, says the readers resolve `video_embeddings.ann_id`, and tells the operator to rebuild the index with `build-ann-index.py`.
- The function's two callers (`api/server.py` at start and `precompute-similar-ann.py`) both get the refusal without being touched.
- The module docstring gains one paragraph on the id contract: FAISS ids are `video_embeddings.ann_id`, a stale index can only miss, and any other source is refused.

**AC6, the readers.**

- **`embeddings.py`.** The four `e.rowid AS rowid` selects become `e.ann_id AS ann_id`, and `_seed_from_row` returns `"ann_id"`. Every return shape of `resolve_seed` changes `exclude_rowid` to `exclude_ann_id` and `rowid` to `ann_id`: the zero vector, the parsed vector, the not-found case and the found seed.
- **`ann.py`.**
  - `compute_similar_items` keeps the `> 0` filter, renames its locals and the log key to `ann_ids`, and self-excludes on `seed["ann_id"]`.
  - `search_similar_above` uses `seed.get("ann_id")` and keeps `> 0`.
  - `search_index`'s fourth positional parameter becomes `exclude_ann_id`.
- **The vector search callers.** `similar._handle_vector_search` passes `seed["exclude_ann_id"]`, and `search.vector_candidates` renames its locals. Both already pass ids straight to `fetch_metadata`.
- **`fetch_metadata`.** It takes `ann_ids`, selects `e.ann_id AS ann_id`, filters `WHERE e.ann_id IN (...)` (served by plan A's UNIQUE `idx_video_embeddings_ann_id`) and keys its result by `ann_id`. The output dicts are unchanged.
- **The random cache.**
  - `ensure_random_cache_schema` creates `random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)`, and `RANDOM_CACHE_CHECK_SQL` counts that table.
  - `random_rowids_count` becomes `random_ann_ids_count`. It looks up `random_ann_ids` by name in `sqlite_master`, so an old file returns None.
  - `populate_random_cache` takes `MIN`/`MAX`/`COUNT` over `ann_id`. The unfiltered window is `ann_id >= start ORDER BY ann_id LIMIT n`, plus the wrap-around `ann_id < start`. The filtered `scan_range` ranges and orders over `e.ann_id` and advances with `ann_id + 1`. The scan is already a keyset cursor, not span arithmetic, so the sparse 63-bit id space costs nothing.
  - `fetch_random_rowids` becomes `fetch_random_ann_ids`, reading the `ann_id` column.
  - `random_videos.py` changes its import, its locals and its docstring.
  - `precompute-random-rowids.py` keeps its file name and arguments. It imports `random_ann_ids_count`, and only its description and its `--size` help text change.
  - The comment in `server_config.py` changes.
- **Old-shape random caches.** Each path is covered by code that already exists:
  - The Engine's `open_random_cache_if_usable` gets None, logs `no_table`, and `server.py:345` starts a background build. Random requests are served from the DB until the build lands.
  - The job's keep check counts `None or 0` and rebuilds into a fresh per-pid temp file, which then replaces `--out`. The result holds only `random_ann_ids`.
  - `swap_readonly_connection` validates with `RANDOM_CACHE_CHECK_SQL`, so it can install only the new shape.

**AC7, the similarity precompute.**

- `iter_embedding_rows_by_rowids` becomes `iter_embedding_rows_by_ann_ids` (`WHERE ann_id IN`).
- `fetch_similarity_targets` and `fetch_similarity_targets_chunked` take `ann_ids` and return `{ann_id: row}`.
- Both pending-selection queries select `e.ann_id`, and the full-mode SELECT reads `ann_id` instead of `rowid`.
- The main loop self-excludes on `ann_id_int == row["ann_id"]` and keeps `<= 0`.
- The `video_keys`/`similarity_sources` joins, the output keys and the `mode=ro` source connection are left alone.

**AC8, the purpose.** `tests/active/test_stale_ann_index.py` runs an ENGINE_PY `_CHILD`:

- It builds the tmp DB through `ensure_video_embeddings_schema` and an `IDMap2,IVF1,Flat` index on `ann_id`. With one list, the search is exact and deterministic.
- It records `ann_id -> (video_id, host)`, then runs cases A (delete all rows and reinsert them in reverse), B (`purge_host_data`) and C (insert one unindexed video).
- After each case it calls `compute_similar_items` and `vector_candidates` through a stub server.
- It asserts that every hit equals the recorded identity for the id that produced it. A rowid join would fail case A, because the reverse reinsert permutes the rowids.

**AC9, the smoke test and docs.**

- `validate_outputs` imports `ANN_ID_SOURCE` next to its existing `ensure_video_embeddings_schema` import. Beside the `meta_total` check it asserts `meta.get("id_source") == ANN_ID_SOURCE` and records `checks["ann_id_source"]`.
- The docs listed in the requirements gain the cutover sequence, the startup refusal and its triage row, the `migrate-whitelist.py` refusal of `build-ann-index`, and the `random_ann_ids` shape with its self-rebuild.
- The issue is set to `enhancement, complete` and archived.

**Test import pattern.** Every test that needs `compute_ann_id` follows `test_video.py`: it inserts `engine/server` on `sys.path`, then runs `from data.ann_ids import compute_ann_id`. `test_metadata`, `test_random_cache`, `test_random_videos`, `test_db` and `test_precompute_similar_ann` already insert `engine/server` and import from `data.*`, so for them this is a one-line import. A conftest re-export would put `engine/server` on the path for every test, and `test_video.py` notes that both trees hold a `server` module. That collision is avoided by not touching conftest.

**Phasing.** I keep the three phases from build 19 and the order readers, then random cache, then index build and gate, all in one merge:

- Phase 1 already writes `"id_source": "video_embeddings.ann_id"` into the `test_precompute_similar_ann` fixture sidecar, so phase 3's gate does not turn it red.
- The docs land with phase 3, since they describe the cutover that phase completes.

### Alternatives considered

- **Keep `rowid` as the FAISS id and add an id→key map table written at build time.** Rejected because ADR-0006 settles derived ids. A map also goes stale the same way rowids do, unless it is snapshotted with the index.
- **Store `(video_id, instance_domain)` in the random cache instead of ANN ids.** Rejected because it forks `fetch_metadata` into a second keyed path for one caller. The `ann_id` form reuses the single id→metadata path, and the UNIQUE index serves it.
- **Keep the table name `random_rowids` and rename only the column, detected via `PRAGMA table_info`.** Rejected in favour of a new table name. The existing sqlite_master name probe then handles detection, and an old file can never pass the swap check. The cost is the named ceiling below.
- **A content-based gate:** sample index ids at Engine start and check that they exist in `video_embeddings`. Rejected because a missing id is the accepted stale-index state, not an error. It cannot tell a rowid index from a stale `ann_id` index, and it adds startup I/O. The sidecar `id_source` is cheap and exact.
- **Put the id-source check in `server.py` only.** Rejected because `precompute-similar-ann.py` searches the same index. The shared `assert_index_matches_embeddings` covers both callers with one check.
- **Keep the seed key named `rowid` but fill it with `ann_id`.** Rejected because the name would lie. The rename's main risk, a partial rename, is closed by a grep over `engine/server` and by the AC8 and existing similar tests.
- **Sample training vectors by `ann_id % step` too.** That would work equally well, since hashes are uniform. It was not chosen only to keep the diff minimal and leave `fetch_training_samples` alone (see Tradeoffs).
- **The conftest `compute_ann_id` re-export.** Rejected for the reason given under Test import pattern above.
- **Gate first, then readers.** Rejected because every phase-1 and phase-2 checkpoint would then run against an Engine that refuses the shared dataset's index. With readers first, no earlier checkpoint goes red when a later phase lands.

### Gotchas, risks and limitations

- **The crash window inside the build.** `build-ann-index.py` writes the index before the sidecar. The one-time window is a cutover build that dies between the two writes: it leaves a new `ann_id` index under the old `rowid` sidecar, the gate refuses it, and the updater's `finally` restart fails loudly rather than serving wrong videos. After the cutover, every index and sidecar pairing on disk is `ann_id`-keyed, so a failed build leaves at worst a stale index, never a wrong one.
- **An old-shape DB under an `ann_id` sidecar.** One example is a pre-migration backup restored under a post-cutover index. The gate passes on the sidecar, and the readers then fail per query with `no such column: ann_id`. That is a loud error, not a wrong video. AC5 asks for no startup DB-shape check, so I add none. `assert_video_embeddings_has_ann_id(server.db)` at start would be the one-line upgrade if wanted.
- **Partial rename.** A forgotten `seed.get("rowid")` silently disables self-exclusion, and `seed["rowid"]` raises KeyError. The rename lands in one phase, a grep checks it, and AC8 plus the similar tests exercise both paths.
- **A missed `rowid` in the index build** would pass the gate with wrong ids. The AC4 test compares `vector_to_array(index.id_map)` exactly with the DB's `ann_id` set.
- **Old caches left in place.** An in-place `populate_random_cache` on a file that still holds `random_rowids` (only the in-place tests do this) leaves that dead table next to `random_ann_ids`. Nothing reads it.
- **AC4 test parameters.** The default `--nlist 4096`/`--m 32` cannot train on a fixture of a few dozen vectors. The test passes small `--nlist`/`--m`/`--train-sample` values, and the job's CLI is unchanged.
- **The engine-backed suite fails until the dataset is cut over.** Once phase 3 lands, the shared `whitelist.db` and its index must be migrated and rebuilt before the full-suite run (operator coordination). The orchestrator smoke test likewise needs a migrated `--source-db` and is run manually.
- **Archived tests stay as they are.** `tests/archive/random_cache_in_place/test_random_cache.py` still names `random_rowids` and is not run.

### Tradeoffs the operator is asked to accept

- **A hard cutover.** A `rowid` sidecar is refused, so the deploy is: stop the Engine, run `build-ann-index.py`, start it. The similarity cache is untouched. The random cache rebuilds itself in the background, and until it does the random feed comes from the DB path.
- **Stale index behaviour.**
  - Purged or deleted videos stay in the index until the next rebuild and come back as misses.
  - Re-embedded videos keep their old vector, but it resolves to the right video.
  - New videos are absent until a rebuild.
- **The unfiltered random draw.** It becomes a hash-uniform window instead of a block of rows in insertion order. Ids that follow a large gap are a little more likely to start a window, which is negligible at a window of thousands.
- **Named simplification: training samples.** ANN training keeps sampling by `rowid % step`. That is a cursor that picks quantizer training vectors, never an identity. Its ceiling: a heavily fragmented rowid space could skew which vectors train the quantizer, which affects recall only, never correctness. The upgrade is one token, `ann_id % step`.
- **Named simplification: random-cache detection.** An old cache is recognised by its table name. Its ceiling: a future reshape under the name `random_ann_ids` would go undetected. The upgrade is a `PRAGMA table_info` column check in `random_ann_ids_count`.

## Impacts


<impacts>
<impact path="engine/server/data/ann_ids.py" element="new constant ANN_ID_SOURCE">
**What changes:** add `ANN_ID_SOURCE = "video_embeddings.ann_id"`, a module-level string next to `ANN_ID_MASK` (line 10). Add a one-line comment, matching the file's comment style.

**What depends on it:**
- `build-ann-index.py` writes it to the sidecar.
- `embedding_space.assert_index_matches_embeddings` checks it.
- The smoke test's `validate_outputs` asserts it.
- `tests/active/test_ann_ids.py` (new) uses it.

**Regression risk:** low. The module must stay stdlib-only. Today it imports only `hashlib`, `sqlite3` and `data.moderation`, which imports `data.similarity_cache`. System-interpreter tests import it: `test_precompute_similar_ann.py`, `test_metadata.py`, `test_random_cache.py`, `test_db.py`, `test_random_videos.py` and `test_precompute_random_rowids.py`, the last of which runs the job through `sys.executable`. A numpy import here would break all of them. Nothing else in the module changes.
</impact>
<impact path="engine/server/db/jobs/build-ann-index.py" element="main(): old-shape refusal before resolve_embedding_space (line 212-215)">
**What changes:** add `from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id` next to the `data.embedding_space` import (line 20). Call `assert_video_embeddings_has_ann_id(conn)` right after `sqlite3.connect` and before `resolve_embedding_space(conn)` (line 215). `conn.row_factory = sqlite3.Row` is set at line 213, but the helper reads `row[1]` positionally, so it works with that factory.

**What depends on it:**
- `updater-worker.py:1388-1409` runs it through `run_with_cpu_fallback`. A GPU run that fails on the refusal is retried on CPU and fails again with the same message. That is harmless, but the message appears twice in the log.
- `scripts/run-dataset-build.sh:244` calls it.
- `engine/crawler/package.json:17` (`npm run build-ann-index`) calls it.
- The smoke test runs it through the updater.

**Regression risk:** low. A missing table passes the check and then fails as before in `resolve_embedding_space` with "No embeddings found". An old-shape table now fails with the `migrate-whitelist.py` message instead of building a rowid index. The refusal message also tells the operator about `--resume-staging`, which is irrelevant for this job. That is acceptable because the message is shared.
</impact>
<impact path="engine/server/db/jobs/build-ann-index.py" element="EmbeddingRow.rowid (line 34), iter_embeddings unpack (lines 52, 58), add query (line 250), ids array (line 252)">
**What changes:**
- The `EmbeddingRow` field `rowid` becomes `ann_id`.
- `iter_embeddings` unpacks `for ann_id, embedding_blob, embedding_dim in rows` and builds `EmbeddingRow(ann_id=ann_id, ...)`.
- The query becomes `"SELECT ann_id, embedding, embedding_dim FROM video_embeddings"`.
- The ids become `np.array([item.ann_id for item in batch], dtype=np.int64)`.

**What depends on it:** every reader that resolves FAISS hits (ann.py, search.py, similar.py, precompute-similar-ann.py) now expects these ids to be `ann_id`.

**Regression risk:** HIGH if one site is missed. A `rowid` left in the query while the sidecar says `ann_id` passes the AC5 gate and makes every hit resolve to nothing, because 1..890k never match 63-bit ids. AC4's exact `vector_to_array(index.id_map)` == DB `ann_id` set check closes this. Every masked id is ≤ 2^63-1, so int64 holds it and does not overflow.
</impact>
<impact path="engine/server/db/jobs/build-ann-index.py" element="fetch_training_samples (lines 63-92), deliberately unchanged">
**What changes:** nothing (named simplification). It still runs `SELECT rowid ... WHERE (rowid % ?) = 0`. On a table rebuilt by plan A's migration, rowids were copied, so they are still contiguous. On a fresh sync-whitelist table they are also contiguous.

**What depends on it:** the AC4 test. The test passes small `--train-sample`, `--nlist` and `--m`. The plan does not mention one constraint here: `IndexIVFPQ` with the default `--nbits 8` trains 256 centroids per sub-quantizer, and FAISS clustering raises when there are fewer training points than centroids. A fixture of "a few dozen vectors" therefore also needs a small `--nbits` (e.g. 4 gives 16 centroids, or ≥256 rows). It also needs `dim % m == 0` (line 107) and `nlist` ≤ the number of training vectors.

**Regression risk:** none to production. The test-parameter trap above is the risk to AC4.
</impact>
<impact path="engine/server/db/jobs/build-ann-index.py" element="sidecar meta id_source (line 284) and the index-then-sidecar write order (lines 271, 286)">
**What changes:** `"id_source": ANN_ID_SOURCE`. The write order stays as it is: the index first, then the JSON.

**What depends on it:**
- `embedding_space.assert_index_matches_embeddings`, which reads `<index_path>.json`, not `--meta-path`. A custom `--meta-path` that does not match `<index>.json` already produces a "metadata missing" refusal, and that is unchanged.
- `test-orchestrator-smoke.validate_outputs`.

**Regression risk:** this is the one-time crash window the plan names. A build that dies between line 271 and line 286 leaves an `ann_id` index under the old `rowid` sidecar, and the Engine refuses to start. That is loud, not wrong.

Note for the operator cutover: the default `--index-path`/`--meta-path` (lines 129-130) are `engine/server/db/video-embeddings.faiss[.json]`. The Engine reads `whitelist-video-embeddings.faiss` (`server_config.py:415`). A cutover run of `build-ann-index.py` with default paths therefore leaves the served sidecar on `rowid`, and the Engine keeps refusing. The docs must spell out the explicit paths, as `DATA_BUILD.md:237-241` already does.
</impact>
<impact path="engine/server/data/embedding_space.py" element="assert_index_matches_embeddings (lines 56-99): id_source check after the model check">
**What changes:** import `ANN_ID_SOURCE` from `data.ann_ids`. After the model check (lines 81-85), add `index_id_source = str(meta.get("id_source") or "")`. If it differs from `ANN_ID_SOURCE`, raise RuntimeError naming the source (or `<unset>`), saying readers resolve `video_embeddings.ann_id`, and pointing at `build-ann-index.py`. Use the same f-string style as lines 82-85. The success log (lines 94-99) could add `id_source=`, which is optional.

**What depends on it:**
- `engine/server/api/server.py:365`, the Engine start. The refusal exits the process. Under systemd that is a restart loop, and a blue/green deploy rolls back at readiness (`DEPLOYMENT.md:224`).
- `precompute-similar-ann.py:345`, and through it the updater's similarity stage (`run_similarity_stage`) and `scripts/run-dataset-build.sh:253`.
- `tests/active/test_precompute_similar_ann.py`, whose sidecar at line 74 is `{"model_name","embedding_dim"}` only and would be refused.
- `conftest.engine` (the session Engine) and every Engine-backed test. They start on the shared symlinked `whitelist-video-embeddings.faiss(.json)` (`scripts/worktree-setup.sh:27`), and its sidecar today says `video_embeddings.rowid` according to the requirements. I could not read it: the symlink resolves outside the sandbox.

**Regression risk:** HIGH operationally. Once this lands, every Engine start on a non-rebuilt index fails. That covers the worktree suite, main after merge, and prod until the cutover. The import adds `data.ann_ids` → `data.moderation` → `data.similarity_cache` to the Engine's and precompute's import closure. Both already import `data.moderation`/`similarity_cache`, so there is no cycle: `ann_ids` does not import `embedding_space`.
</impact>
<impact path="engine/server/data/embedding_space.py" element="module docstring (lines 1-12)">
**What changes:** one paragraph on the id contract: FAISS ids are `video_embeddings.ann_id`, a stale index can only miss, and any other `id_source` is refused.

**What depends on it:** nothing.

**Regression risk:** none.
</impact>
<impact path="engine/server/api/server.py" element="startup sequence lines 344-365 (open_random_cache_if_usable, random_cache_startup_build, resolve_embedding_space, assert_index_matches_embeddings): no code change">
**What changes:** nothing in code. Behaviour changes in two places:
- **Line 365.** It now refuses a `rowid` sidecar.
- **Line 344.** An old-shape `random-cache.db` (table `random_rowids`) makes `open_random_cache_if_usable` return None and log `reason=no_table`. Line 345 then forces a startup build, even with `--no-random-cache-refresh`/`--dev`.

The startup build runs in the background worker started around line 510. It is a full filtered scan of `whitelist.db` (890k rows) at `DEFAULT_RANDOM_CACHE_SIZE` = 500000, and until it swaps in, random requests are served from the DB (`_fetch_random_rows`).

The gate runs after `faiss.read_index` (line 350). The old-shape DB under an `ann_id` sidecar case (plan Gotcha 2) is still not caught at start. The one-line upgrade would be `assert_video_embeddings_has_ann_id(db)` next to line 346. The plan does not add it, and this inventory records that choice.

**What depends on it:** the test-harness Engines: conftest `engine`, `test_random_cache` `CACHE_VARIANT_RUNNER`, and `test_video`/`test_similar` children.

**Regression risk:** medium. The behaviour is correct, but the first start after merge does a full background random-cache build on every checkout and lane.
</impact>
<impact path="engine/server/data/embeddings.py" element="resolve_seed return shapes (lines 73, 78-81, 86, 87-101)">
**What changes:**
- Line 73: `exclude_rowid` becomes `exclude_ann_id` in the zero-vector shape.
- Line 79: the same in the parsed-vector shape.
- Line 86: the same in the not-found shape.
- Lines 89 and 91: in the found seed, `"exclude_ann_id": seed["ann_id"]` and `"ann_id": seed["ann_id"]`.

`meta` (lines 94-99) is unchanged and is the only part sent to clients (`seed_payload=seed["meta"]` in similar.py lines 958, 1021, 1138). No id leaks.

**What depends on it:**
- `similar._handle_similar` (line 1085) passes the seed to `_handle_vector_search` (`seed["exclude_rowid"]`, line 989), `_handle_seed_with_embedding` and `similarity_candidates`.
- `similarity_candidates._seed_with_embedding` (lines 473-479) spreads the seed, then `search_similar_above` (line 171) or `_compute_candidates` → `ann.compute_similar_items`.

**Regression risk:** HIGH for a partial rename. A leftover `seed["exclude_rowid"]` in similar.py:989 raises KeyError, which surfaces as a 500 on vector/seed search. A leftover `seed.get("rowid")` in ann.py:112 silently stops excluding the seed from its own up-next fallback.
</impact>
<impact path="engine/server/data/embeddings.py" element="_fetch_seed_by_uuid (line 123), _fetch_seed_by_id (line 151), fetch_seed_embeddings_for_likes two SELECTs (lines 217, 241), _seed_from_row (line 181)">
**What changes:** the four `e.rowid AS rowid` select lines become `e.ann_id AS ann_id`, and `_seed_from_row` returns `"ann_id": int(row["ann_id"])`.

**What depends on it:**
- `resolve_seed`.
- `fetch_seed_embedding`, also called by `handlers/internal_client_reads.handle_internal_video_resolve:107` (`/internal/videos/resolve`, whose response at lines 116-125 carries no id, so it is unchanged). It is also wired into `RecommendationBuilderDeps` (`server.py:397-398`, `builder.py:48-51,129-140`) and the like sources `ann_similar_from_likes.py:54` and `cached_similar_from_likes.py:57`. Those pass the seed dict on to `get_similar_candidates` and never read an id key (verified: no `rowid` under `api/recommendations` except docs).

**Regression risk:** medium. Every seed lookup now selects `e.ann_id`. On an unmigrated `whitelist.db` this raises `no such column: e.ann_id` per request, including `/internal/videos/resolve`, so the Client's like/block flows break, not just similar. `tests/active/test_internal_client_reads.py` creates `video_embeddings` without `ann_id` (line 133) but drives only the metadata and centroids handlers (line 75). `fetch_embeddings_by_ids` selects no id, so that test stays green. `test_server.py` stubs `/internal/videos/resolve` with a fake Engine and is unaffected.
</impact>
<impact path="engine/server/data/ann.py" element="compute_similar_items (lines 36-85)">
**What changes:**
- `rowids` → `ann_ids` (line 38), keeping `> 0`.
- The log key `ann_rowids=` → `ann_ids=` (line 40).
- `fetch_metadata(server.db, ann_ids, ...)`.
- The loop locals become `ann_id`/`ann_id_int`, and the self-exclusion is `if ann_id_int == seed["ann_id"]` (line 62).

**What depends on it:**
- `similarity_candidates._compute_candidates` (line 403), with `server.compute_similar_items` as an override hook.
- Engine-backed `test_similar.py`, `test_dislike_profile.py`, `test_frontend_upnext_pager.py` and `test_video.py`'s similars child.
- The new AC8 test.

**Regression risk:**
- A seed coming from a vector-only request has no `ann_id`. Today such seeds go to `_handle_vector_search` (similar.py:1142), never here, because `_handle_seed_with_embedding` needs `seed.get("embedding")`.
- `seed["ann_id"]` is a hard index, just like today's `seed["rowid"]`. A caller passing a seed built some other way would KeyError, as it does now.
- The log-key rename breaks any log-parsing test reading `ann_rowids=`. Grep found none.
</impact>
<impact path="engine/server/data/ann.py" element="search_similar_above (lines 112-140)">
**What changes:** `seed_ann_id = seed.get("ann_id")`. The comprehension filters `int(ann_id) > 0 and int(ann_id) != seed_ann_id and score >= min_score`. `fetch_metadata` gets ann ids, and `metadata.get(ann_id)` does the lookup.

**What depends on it:**
- `similarity_candidates` line 163-171 (the up-next tail fallback).
- `tests/active/test_similarity_candidates.py:90-96` stubs this function positionally `(server, seed, nprobe, search_limit, min_score)` with a seed that has no id. The signature is unchanged, so the stub stays valid.

**Regression risk:** silent if `seed.get("rowid")` is left in place. `.get` returns None, nothing is excluded, and the seed video appears in its own up-next. Only a test asserting self-exclusion catches this.
</impact>
<impact path="engine/server/data/ann.py" element="search_index (lines 143-169)">
**What changes:**
- The fourth positional parameter becomes `exclude_ann_id: int | None`.
- The docstring says "exclude an ANN id".
- The loop local becomes `ann_id`. The `< 0` filter stays: it keeps 0, but CHECK forbids 0.

**What depends on it:**
- `similar._handle_vector_search:988-990` (positional).
- `search.vector_candidates:191` (positional, passes None).
- The archived `tests/archive/short_similarity_cache/test_similar.py:85-97`, which is not run.

**Regression risk:** low. All callers are positional. The nprobe helpers (lines 172-208) and `_author_key` are untouched. `server.py` imports `set_nprobe` from here, and that import is unchanged.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_vector_search (lines 986-1015)">
**What changes:** `seed["exclude_rowid"]` becomes `seed["exclude_ann_id"]` (line 989), and the locals `rowids`/`rowid` become `ann_ids`/`ann_id` (lines 988, 998, 1011-1012). `fetch_metadata` gets ann ids.

**What depends on it:** the `?vector=` and `?id=` up-next paths that fall through to vector search. `seed_payload=seed["meta"]` is unchanged.

**Regression risk:** a KeyError (500) if the producer and this reader are renamed apart. Both must land in one phase.
</impact>
<impact path="engine/server/data/search.py" element="vector_candidates (lines 190-208)">
**What changes:** the locals `rowids`/`rowid` become `ann_ids`/`ann_id`. `fetch_metadata(conn, ann_ids, ...)` uses `search_connection(server)`, the dedicated read-only `search_db` when one is present (lines 32-43). That handle is on the same `whitelist.db`, so `e.ann_id` and the UNIQUE index are available.

**What depends on it:** `search_videos` (line 294) → `fuse_by_rank`, which keys on `(video_id, instance_domain)` (line 236) and not on an id, so it is unaffected.

**Regression risk:** low. DO NOT TOUCH `VIDEO_ROW_SQL`'s `v.rowid AS rowid` (line 52) or the FTS join `JOIN videos v ON v.rowid = f.rowid` (line 158). Those are `videos.rowid` ↔ `videos_fts` content rowid, unrelated to embeddings, and a blanket rowid→ann_id replace in this file would break lexical search. `tests/active/test_search.py` runs with `query_encoder=None` (line 68), so `vector_candidates` returns before `fetch_metadata`. Its fixture table without `ann_id` (line 40) stays valid.
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata (lines 14-108)">
**What changes:**
- The parameter `rowids` → `ann_ids`, and the docstring "for embedding ANN ids".
- `e.rowid AS rowid` → `e.ann_id AS ann_id` (line 35).
- `WHERE e.ann_id IN (...)` (line 70), served by `idx_video_embeddings_ann_id`.
- `result[int(row["ann_id"])]` (line 77).

The output dict (29 keys, lines 77-107) is unchanged.

**What depends on it:**
- `ann.compute_similar_items`, `ann.search_similar_above`, `similar._handle_vector_search`, `search.vector_candidates` and `random_videos.fetch_random_rows_from_cache:441`.
- `tests/active/test_metadata.py` (`ROW_KEYS`, line 39, pins the 29-key shape).

`fetch_metadata_by_ids` and `fetch_metadata_by_uuids` (lines 116+) key on text pairs and must stay unchanged.

**Regression risk:**
- Batches of 900 ids per IN. That is unchanged and stays under SQLite's variable limit.
- An unmigrated DB raises `no such column: e.ann_id` per call.
- The data/videos.py drop list (`idx_videos_id_instance`, `idx_video_embeddings_id_instance`, lines 23-28) does not include `idx_video_embeddings_ann_id`, so Engine start keeps the index (verified).
</impact>
<impact path="engine/server/data/random_cache.py" element="RANDOM_CACHE_CHECK_SQL (line 19), ensure_random_cache_schema (lines 31-40), random_rowids_count (lines 43-48)">
**What changes:**
- `RANDOM_CACHE_CHECK_SQL = "SELECT COUNT(*) FROM random_ann_ids"`.
- The DDL becomes `random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)`.
- `random_rowids_count` → `random_ann_ids_count`, probing `name = 'random_ann_ids'` in sqlite_master. Keep `fetchall()` so no statement holds SHARED (line 45 comment).

**What depends on it:**
- `open_random_cache_if_usable:292`.
- `populate_random_cache:67` (`reuse_non_empty`).
- `refresh_random_cache:274` → `data/db.swap_readonly_connection(..., RANDOM_CACHE_CHECK_SQL)`. That function is unchanged and only runs the given SQL.
- `precompute-random-rowids.py:16,69`.
- Tests: `test_db.py:155` (its own `CHECK_SQL` copy), `test_random_cache.py`, `test_precompute_random_rowids.py`, `test_random_videos.py`.

**Regression risk:** medium. An old file is treated as having no table, by design. A build in place on an existing file (only the in-place tests do this) leaves the dead `random_rowids` table beside it.
</impact>
<impact path="engine/server/data/random_cache.py" element="populate_random_cache (lines 51-194)">
**What changes:**
- Lines 71 and 74: `random_ann_ids`.
- The source aggregate becomes `MIN(ann_id)`/`MAX(ann_id)`/`COUNT(*)` (line 76).
- `random.randint(min_id, max_id)` (line 89) now spans 63-bit ints, which Python handles.
- Unfiltered (lines 91-104): `SELECT ann_id FROM video_embeddings WHERE ann_id >= ? ORDER BY ann_id LIMIT ?`, plus the `< ?` wrap, and the INSERT into `random_ann_ids (position, ann_id)` with `row["ann_id"]`.
- Filtered: `try_add` reads `entry["ann_id"]` (line 117). `scan_range` selects `e.ann_id AS ann_id`, `WHERE e.ann_id >= ? AND e.ann_id <= ? ORDER BY e.ann_id` (lines 148-155), and advances with `int(rows[-1]["ann_id"]) + 1` (line 163).
- The locals `rowids` become `ann_ids`, and the log lines (lines 174-187) are unchanged in format.
- `build_random_cache`'s docstring ":returns: (temp path, rowids written...)" (line 220) and `open_random_cache_if_usable`'s docstring "at least one rowid" (line 284) need wording changes.

**What depends on it:**
- `build_random_cache` → `refresh_random_cache` → `run_random_cache_worker` (the Engine) and `precompute-random-rowids.py`.
- Tests: `test_random_cache.py` (populate under a held lock; lines 290-321 assert `video_rowid` == 1..20), `test_db.py`, `test_precompute_random_rowids.py` (sorted ids == range(1,21)), and the archived in-place test.

**Regression risk:** medium.
- The source must have `ann_id`. Every hand-rolled test source (`video_embeddings (video_id TEXT, instance_domain TEXT)` in `test_random_cache.py:134`, `test_db.py:165` and `test_precompute_random_rowids.py:31`) breaks with `no such column: ann_id` until it gains the column.
- The filtered scan's `ORDER BY e.ann_id` with the JOIN relies on the UNIQUE index for speed on 890k rows. Fixtures without the index are just a full scan.
- `ann_id + 1` cannot overflow, because MAX ≤ 2^63-1 ends the loop via `current <= range_end` before any increment past the max. `rows[-1]["ann_id"] + 1` can still reach 2^63 as a Python int and is then bound as a parameter on the next loop test. That does not happen because the loop condition `current <= range_end` is checked first in Python. Flagged anyway: binding 2^63 to SQLite would raise OverflowError, so do not reorder the loop.
</impact>
<impact path="engine/server/data/random_cache.py" element="fetch_random_rowids (lines 329-344) → fetch_random_ann_ids">
**What changes:** the rename, `SELECT COUNT(*) FROM random_ann_ids`, `SELECT ann_id FROM random_ann_ids ORDER BY position LIMIT ? OFFSET ?`, and `row["ann_id"]`.

**What depends on it:**
- `random_videos.py:10,434`.
- `test_db.py:34,194`.
- `test_random_cache.py:186,470` (module attribute access).
- `test_random_videos.py:505,512`, which monkeypatches `random_videos.fetch_random_rowids` by name and wraps `random_cache.fetch_random_rowids`. Both names must change, or `monkeypatch.setattr` raises AttributeError (`raising=True` default).

**Regression risk:** medium (test churn). The function is a plain rename.
</impact>
<impact path="engine/server/data/random_videos.py" element="import (line 10), fetch_random_rows_from_cache (lines 421-448)">
**What changes:** `from data.random_cache import fetch_random_ann_ids`. The locals `rowids`/`rowid` become `ann_ids`/`ann_id`, and the docstring ("precomputed rowid cache", "unseen rowid") becomes ANN-id wording. `fetch_metadata` is called with ann ids. The DB-path readers (`fetch_random_rows`, `fetch_recent_videos`, `fetch_popular_videos`, `fetch_ordered_page`) select no embedding id and are unchanged.

**What depends on it:** the server's `fetch_random_rows_from_cache` dependency (`server.py`, builder), `similar._handle_random` and `test_random_videos.py`.

**Regression risk:** low.
</impact>
<impact path="engine/server/db/jobs/precompute-random-rowids.py" element="import and keep check (lines 14-18, 69), description (line 23), --size help (line 34), module docstring (line 2)">
**What changes:** it imports `random_ann_ids_count` and uses it at line 69. The description becomes "Precompute random ANN-id cache." and the `--size` help "ANN ids to sample.". The file name and arguments stay, because `scripts/run-dataset-build.sh:262`, `DATA_BUILD.md:292`, `DEPLOYMENT.md:218` and `tests/active/test_precompute_random_rowids.py:19` name the file.

**What depends on it:** the keep check `existing = random_ann_ids_count(...) or 0` turns an old-shape `--out` into 0, so the job rebuilds and `os.replace`s it.

**Regression risk:** low. The job runs under `sys.executable` in tests, and its import closure (`data.db`, `data.random_cache`) is stdlib-only. Keep it that way.
</impact>
<impact path="engine/server/api/server_config.py" element="comment above DEFAULT_RANDOM_CACHE_SIZE (line 352)">
**What changes:** "Precomputed random rowids" becomes "Precomputed random ANN ids".

**What depends on it:** nothing.

**Regression risk:** none. `test_server_config.py` imports the module but reads values, not comments.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="iter_embedding_rows_by_rowids (lines 52-67) → iter_embedding_rows_by_ann_ids">
**What changes:** the rename and its parameter. The select becomes `SELECT ann_id, video_id, instance_domain, embedding, embedding_dim FROM video_embeddings WHERE ann_id IN (...)`, and the docstring changes.

**What depends on it:** `main()` line 397 (the non-full modes).

**Regression risk:** low. Batches of 512 sit under the variable limit.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="fetch_similarity_targets (lines 131-149), fetch_similarity_targets_chunked (lines 152-166)">
**What changes:** the parameters `rowids` → `ann_ids`. The select becomes `ann_id, video_id, instance_domain ... WHERE ann_id IN`, the result is `{row["ann_id"]: dict(row)}`, and the docstrings change.

**What depends on it:** `main()` line 434. The returned dicts gain an `ann_id` key instead of `rowid`, and only `video_id`/`instance_domain` are read (lines 447-448).

**Regression risk:** low. The 5000-id chunk is unchanged.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="main(): both pending-selection queries (lines 371-391), pending list (392-398), full-mode SELECT (402-407), batch id set (426-434), self-exclusion (438-442), comment line 366">
**What changes:**
- The two `SELECT e.rowid` become `SELECT e.ann_id`.
- `pending_ann_ids = [int(row["ann_id"]) ...]` and `iter_embedding_rows_by_ann_ids`.
- The full-mode select becomes `SELECT ann_id, video_id, ...`.
- `batch_ann_ids`/`targets_by_ann_id` hold the renamed values.
- `if ann_id_int == row["ann_id"] or ann_id_int <= 0`.
- The line 366 comment "only rowids are materialized" changes.

Untouched: the `video_keys`/`similarity_sources` joins on text pairs, `write_similarities`, `set_nprobe` (its own local copy, lines 101-114), the `mode=ro` source and the gate call (line 345).

**What depends on it:**
- The updater's `run_similarity_stage` (`--refresh-existing`).
- `run-dataset-build.sh:253` (full).
- `tests/active/test_precompute_similar_ann.py`.
- The smoke test.

**Regression risk:** medium. If `row["rowid"]` is left at line 440, the full-mode row has no `rowid` key and sqlite3.Row raises IndexError, so it fails loudly. A source DB without `ann_id` is refused earlier by the gate only if its sidecar is still `rowid`. A migrated sidecar over an unmigrated DB fails at the selection with `no such column`.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="validate_outputs (lines 747-772) and import (line 31)">
**What changes:** add `ANN_ID_SOURCE` to the existing `from data.ann_ids import ensure_video_embeddings_schema` (line 31). After the `meta_total` check (lines 766-772), raise RuntimeError unless `meta.get("id_source") == ANN_ID_SOURCE`, and record `checks["ann_id_source"]`.

**What depends on it:** the report JSON `tmp/orchestrator-smoke/last-report.json` (a new check key). It is run manually and is not in the pytest suite.

**Regression risk:** low. It needs a migrated `--source-db`, because mini-prod copies its schema and `ensure_video_embeddings_schema` (line 271) refuses an unmigrated one. The `ORDER BY rowid DESC` sampling at lines 288 and 314 is on `videos`/`channels` sampling and stays.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="ANN stage (lines 1386-1409) and finally-restart (1414-1427): no code change">
**What changes:** nothing.

Behaviour changes:
- `build-ann-index.py` now writes the `ann_id` sidecar, and the restarted Engine and the following precompute accept it.
- If the build dies after writing the index but before the sidecar, during the first cutover run only, the `finally` restart brings up an Engine that refuses to start, and the updater's similarity stage then fails the gate.

**What depends on it:** `test_updater_worker.py` (stubs the jobs; not affected by ids) and the smoke test.

**Regression risk:** low. The first updater run after merge must follow the operator cutover (migrate + rebuild). Otherwise the stop/merge/ANN/start cycle itself performs the rebuild on a migrated prod DB, and if prod is unmigrated, merge refuses (plan A).
</impact>
<impact path="engine/server/db/jobs/whitelist_migrations.py" element="migrate video_embeddings docstring (line 401)">
**What changes:** optional wording only. The line reads "Rowids are copied, so a rowid-keyed index built before the migration still resolves the same videos." That stays true for the window between migrate and rebuild, so it can stay. It could add that after plan B the Engine refuses such an index.

**What depends on it:** nothing.

**Regression risk:** none.
</impact>
<impact path="scripts/run-dataset-build.sh" element="build-ann-index (line 244), precompute-similar-ann (253), precompute-random-rowids (262): no change">
**What changes:** nothing. The script syncs a fresh/migrated `whitelist.db` (plan A puts `ann_id` in via sync), then builds the index (now `ann_id` and the new sidecar), then precomputes (gate passes), then builds the random cache (`random_ann_ids`).

**What depends on it:** the operator's full rebuild path.

**Regression risk:** low. It is listed so the next step does not look for a change here.
</impact>
<impact path="scripts/worktree-setup.sh" element="shared symlinks (line 27) and copied random-cache.db (line 31)">
**What changes:** nothing in this build.

**What depends on it:** this worktree's `whitelist.db`, `whitelist-video-embeddings.faiss` and `.faiss.json` are symlinks to main's live files, and `random-cache.db` is a private copy of main's old-shape file.

**Regression risk:** HIGH (coordination).
- Running `build-ann-index.py` from this worktree against the default served paths rewrites main's live index and sidecar. Main's code has no `id_source` gate and resolves by rowid, so main would serve empty similar/search results until it also merges plan B.
- Without a rebuild, the AC5 gate makes every Engine-backed test in this worktree fail at start.
- The phase-3 checkpoint therefore needs either private copies of the dataset and index for the worktree, or a coordinated main cutover. The plan names this as operator coordination. This entry records the concrete mechanism.
</impact>
<impact path="tests/active/conftest.py" element="engine session fixture (lines 107-146), dataset fixture (188-193)">
**What changes:** nothing in code (the plan keeps conftest untouched, with no `compute_ann_id` re-export).

**What depends on it:** every Engine-backed test. After phase 3, `engine` fails "Engine exited on every start" (line 140) until the shared index is rebuilt on `ann_id`. With the checkout's old-shape `random-cache.db`, the session Engine, even with `--no-random-cache-refresh`, starts a background full build (500k target) that renames into the checkout's `engine/server/db/random-cache.db`.

**Regression risk:** HIGH for suite runs until cutover. See the `test_random_cache.py` engines entry for the knock-on effect.
</impact>
<impact path="tests/active/test_random_cache.py" element="test_engines_starting_at_once_all_become_healthy (lines 685-720+)">
**What changes:** the plan's churn list does not cover this test. It reads the checkout's `RANDOM_CACHE_DB` with `SELECT COUNT(*) FROM random_rowids` (line 691), and its lock control runs `DELETE FROM random_rowids WHERE 0` (line 706). Both must move to `random_ann_ids`.

**What depends on it:** the session `engine` fixture, which, per its docstring, is what leaves the checkout's cache non-empty.

**Regression risk:** HIGH, timing-dependent.
- The worktree's copied cache is old-shape. The session Engine sees `no_table` and starts a background build. Until that build swaps in, the file holds only `random_rowids`, and `SELECT ... FROM random_ann_ids` raises "no such table".
- Once the build lands, the cache may hold up to `DEFAULT_RANDOM_CACHE_SIZE` (500000) rows. The control `cached_rows < server_config.DEFAULT_RANDOM_CACHE_SIZE` (line 696) then fails whenever the filtered build reaches the full 500000, which is likely over 890k embeddings at `max_per_author` 100.
- Eight Engines started against an old-shape cache would each also start a build, contrary to the test's premise that refresh-off Engines never write. The test needs a fresh new-shape checkout cache before it runs, or a seeded short cache.
</impact>
<impact path="tests/active/test_random_cache.py" element="_source_db (129-139), _seed_cache/_cache_rows/_cache_rowids (147-168), _served_rowids (183-186), _seed_servable_cache (193-199), _feed_rowids (227-237), populate-under-lock test (290-321), STALE_ROWID/SEEDED_ROWS/SEEDED_ROWIDS (57-60), the missing/no_table/empty probe (586-607), read-only open test (610-637), worker test (640-682), module docstring (lines 1-19)">
**What changes:**
- `_source_db` gains `ann_id INTEGER`, filled with `compute_ann_id(f"v{i}", "a.example")`. The import is one line: `engine/server` is already on `sys.path` (lines 44-46).
- Every `random_rowids`/`video_rowid` becomes `random_ann_ids`/`ann_id`.
- The "positions 1..20 over source rowids 1..20" assertions (lines 321, 676 and docstring lines 4-9) become the set of the 20 computed ids.
- The Engine helpers `_seed_servable_cache`/`_feed_rowids` select `e.ann_id`/`ann_id` from the live `whitelist.db`, so they need the migrated dataset.
- The "no_table" probe should use an old-format `random_rowids` file, pinning AC6's old-shape case.
- `SEEDED_ROWS` values (7, 3, 11) and `STALE_ROWID` 999 are arbitrary ints and can stay, because `fetch_random_ann_ids` does not validate them.
- The read-only open test's `SELECT position, video_rowid` (line 629) and probes (lines 622, 631) change.
- `CACHE_VARIANT_RUNNER` (lines 101-126) is unaffected.

**What depends on it:** the CI suite.

**Regression risk:** medium. The churn is large, and a missed `random_rowids` string fails the test.
</impact>
<impact path="tests/active/test_db.py" element="import (line 34), SEEDED_ROWIDS (150), CHECK_SQL (155), _source_db (160-170), _seed_cache (173-180), _served_rowids (191-194), swap test (201-227), module docstring (line 8)">
**What changes:** import `fetch_random_ann_ids`. `CHECK_SQL`/`_seed_cache` move to `random_ann_ids(position, ann_id)`. `_source_db` gains `ann_id`, because `build_random_cache` at line 207 now reads it. `SEEDED_ROWIDS` can stay as arbitrary ints or become computed ids. The local `CHECK_SQL` copy must match `RANDOM_CACHE_CHECK_SQL`, or the "rename" stage's check fails.

**What depends on it:** `data/db.swap_readonly_connection` coverage.

**Regression risk:** medium. Without the `ann_id` column, the build raises before the swap is tested.
</impact>
<impact path="tests/active/test_precompute_random_rowids.py" element="_source_db (26-36), _seed_cache (39-46), _cache_rows (49-55), assertions (71-72, 104-105), docstring (lines 1-7); new old-shape case">
**What changes:**
- The source gains `ann_id` with computed values.
- The cache helpers move to `random_ann_ids`.
- `sorted(...) == range(1, 21)` becomes `sorted(computed ids)`.
- A new case: an `--out` holding an old `random_rowids` table at `--size` rows is rebuilt, not kept.

Unlike the plan's "one-line import" claim, this file does NOT put `engine/server` on `sys.path` (only `ROOT`, line 18). Importing `compute_ann_id` needs a `sys.path.insert` like `test_video.py:55-57`, or the ids must be computed in the subprocess.

**What depends on it:** `precompute-random-rowids.py`.

**Regression risk:** low-medium. The import-path detail is the trap.
</impact>
<impact path="tests/active/test_random_videos.py" element="NSFW_EMBEDDINGS_TABLE (372), nsfw_conn insert (389), _video_db (461-479), _cache_owner (482-513), docstring (lines 34-40)">
**What changes:**
- `NSFW_EMBEDDINGS_TABLE` gains `ann_id INTEGER`. The shared table string is used by both `nsfw_conn` (DB-path reads that never read `ann_id`) and `_video_db`. The positional `INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')` at lines 389 and 477 then fails with a column-count error unless both inserts add `compute_ann_id(label, NSFW_HOST)`.
- `_video_db` returns label→ann_id instead of `lastrowid`.
- `_cache_owner` creates `random_ann_ids(position, ann_id)` and monkeypatches `random_videos.fetch_random_ann_ids` and wraps `random_cache.fetch_random_ann_ids`.
- The docstring changes "unseen rowid".

The `_feed_db` CTAS copies from `whitelist.db` (lines 113-135) copy whatever columns the live table has, including `ann_id` once migrated. The T→T2 duplicate (lines 134-135) then carries T's `ann_id` under T2's domain, which is allowed in a CTAS table with no UNIQUE index. No ordered/random DB-path read touches `ann_id`, so this is harmless. It would matter only if a future test resolved T2 by `ann_id`.

**What depends on it:** the random-cache refill tests.

**Regression risk:** medium (churn). The monkeypatch name is the trap.
</impact>
<impact path="tests/active/test_metadata.py" element="nsfw fixture (around lines 194-206), _nsfw_metadata (212-213)">
**What changes:** the nsfw fixture's `video_embeddings` DDL (line 196) gains `ann_id INTEGER`. Its inserts (line 205) pass `compute_ann_id(label, HOST)`, and `_nsfw_metadata` selects `ann_id` instead of `rowid`. The other `conn` fixture (line 91) feeds only the by_ids/by_uuids reads and can stay. `engine/server` is already on `sys.path` (lines 27-29).

**What depends on it:** `fetch_metadata` coverage.

**Regression risk:** low. `ROW_KEYS` (line 39) also proves the output gains no id key.
</impact>
<impact path="tests/active/test_precompute_similar_ann.py" element="source fixture (59-75), INDEX_BUILDER (46-56), sidecar (line 74), _source_db (78-83), labels SHORT_ROWID/LIVE/TOP2 (35-43, 218-258)">
**What changes:**
- The fixture table gains `ann_id` (`compute_ann_id(f"v{n}", DOMAIN)`, via `data.ann_ids`; `engine/server` is already on `sys.path` at lines 25-26).
- The explicit `rowid` inserts can stay or go.
- `INDEX_BUILDER` selects `ann_id, embedding`.
- The sidecar writes `{"model_name", "embedding_dim", "id_source": "video_embeddings.ann_id"}`, so phase 3's gate does not refuse it (the plan puts this in phase 1).
- `SHORT_ROWID` and `v{n}` stay as labels. The `TOP2` expectations are keyed by label, so they survive.
- `_source_db` (argparse refusals) exits before reading and needs no `ann_id`.

**What depends on it:** AC7's checkpoint C2.

**Regression risk:** medium. If any of the three changes is missing, the whole module fails, either on the gate or on `no such column`.
</impact>
<impact path="tests/active/test_video.py" element="_CHILD similars_stack (lines 216-224)">
**What changes:** `SELECT ann_id, embedding FROM video_embeddings` and `add_with_ids(..., np.array([r["ann_id"] ...]))`. The embedded-video inserts at lines 544-545 already carry `ann_id` (plan A). The child builds its index in-process and never calls `assert_index_matches_embeddings`.

**What depends on it:** the "similars GET answers within 1 s during a blocked refresh" case (docstring line 30).

**Regression risk:** medium. If it is left on rowid, the ANN neighbour lookup by `ann_id` finds nothing and the test's neighbour assertion fails.
</impact>
<impact path="tests/active/test_stale_ann_index.py" element="NEW: AC8 ENGINE_PY child">
**What changes:** a new file, following the `_CHILD` pattern (`test_search.py`, `test_popular_videos.py`, `test_video.py`).

Points the implementer must cover:
- `fetch_metadata` joins `videos` (it selects about 25 `v.*` columns including `nsfw`, `preview_path`, `error_count`) and LEFT JOINs `channels`. The tmp DB needs those full tables, e.g. via `sync-whitelist.py`'s schema helpers as `test_video.py` does. `ensure_video_embeddings_schema` alone is not enough.
- `purge_host_data` (`data/moderation.py:194`) walks `_host_table_column_pairs()` and only deletes tables that exist.
- The stub server needs `index`, `index_lock`, `db`, `db_lock`, `normalize_queries`, `similarity_search_limit`, `similarity_exclude_source_author`, `similarity_max_per_author` and `video_error_threshold`. `vector_candidates` also needs `query_encoder` with `.enabled` and `.encode()` returning the probe vector, plus optionally `search_db`/`search_db_lock`.
- Case A must delete before reinserting: the collision trigger and UNIQUE index forbid two rows with one id.
- The seed for `compute_similar_items` needs `embedding` and `ann_id`.

**What depends on it:** AC8.

**Regression risk:** none to production. Register the new test group in `tests/config.json`.
</impact>
<impact path="tests/active/test_ann_ids.py" element="NEW: AC4 build-ann-index job test and AC5 gate cases">
**What changes:** a new file. It runs `build-ann-index.py --cpu` under `ENGINE_PY` on a tmp DB built through `ensure_video_embeddings_schema`, then loads the index in an `ENGINE_PY` child and compares `faiss.vector_to_array(index.id_map)` with the DB's `ann_id` set. It runs AC5 against the written sidecar, a `rowid` sidecar and one with no `id_source`, using a stub index with `.d`.

The parameters must satisfy:
- `dim % m == 0`;
- training count ≥ `nlist`;
- training count ≥ 2^`nbits` (pass a small `--nbits`, see the `fetch_training_samples` entry);
- `--train-sample` ≥ rows, so `step` = 1.

It must pass explicit `--index-path` and `--meta-path` in tmp, or it overwrites `engine/server/db/video-embeddings.faiss`.

**What depends on it:** AC4/AC5.

**Regression risk:** none to production. Register it in `tests/config.json`.
</impact>
<impact path="tests/config.json" element="test_groups">
**What changes:**
- Add groups for `test_stale_ann_index.py` (ann.py, search.py, metadata.py, embeddings.py, ann_ids.py) and `test_ann_ids.py` (build-ann-index.py, embedding_space.py, ann_ids.py).
- Optionally add `engine/server/data/ann_ids.py` to the groups that now import `compute_ann_id`: `test_metadata`, `test_random_cache`, `test_random_videos`, `test_db`, `test_precompute_random_rowids` and `test_precompute_similar_ann`.
- `test_db.py` currently maps only `data/db.py`, but it exercises `random_cache.py` too.

**What depends on it:** the validate_tests runner, which selects tests by changed file.

**Regression risk:** low. A missing mapping means a changed file does not trigger its test.
</impact>
<impact path="tests/last_test_validation.json" element="generated validation record">
**What changes:** it is regenerated by the test runner. Test ids it lists (e.g. `test_precompute_random_rowids.py`, `test_metadata` param ids) may change with the churn.

**What depends on it:** nothing reads it as input, as far as I can tell. I found no test asserting on its content.

**Regression risk:** none. Uncertain whether the runner compares against it.
</impact>
<impact path="tests/active/test_internal_client_reads.py" element="fixture video_embeddings without ann_id (line 133)">
**What changes:** nothing. It drives only `handle_internal_videos_metadata` and `handle_internal_dislike_centroids` (line 75), and `fetch_embeddings_by_ids` selects no id. `handle_internal_video_resolve` → `fetch_seed_embedding` (now `e.ann_id`) is not exercised here.

**What depends on it:** n/a.

**Regression risk:** none, verified by reading. Listed because its schema-less fixture would break if a future test drove `/internal/videos/resolve` through it.
</impact>
<impact path="tests/active/test_search.py" element="fixture video_embeddings without ann_id (line 40)">
**What changes:** nothing. The stub server has `query_encoder=None` (line 68), so `vector_candidates` returns before `fetch_metadata`.

**Regression risk:** none, verified. A test that armed an encoder here would need `ann_id` in the fixture.
</impact>
<impact path="tests/active/test_similarity_candidates.py" element="data.ann stub search_similar_above (lines 90-96)">
**What changes:** nothing. The stub is positional `(server, seed, nprobe, search_limit, min_score)` and its seed carries no id key. `fetch_metadata_by_ids` keys by text pair.

**Regression risk:** none.
</impact>
<impact path="tests/active/test_blocks.py" element="read-only dataset SELECTs joining video_embeddings">
**What changes:** nothing. The same holds for `test_dislike_profile.py`, `test_dislikes.py`, `test_profiles.py`, `test_frontend_reactions.py` and `test_similar.py`, whose helpers `ORDER BY v.rowid` on `videos`, not on embeddings.

**What depends on it:** all of them are Engine-backed, so they are red until the shared dataset and index are cut over (AC5 gate).

**Regression risk:** none from code. They are blocked operationally until cutover.
</impact>
<impact path="tests/archive/random_cache_in_place/test_random_cache.py" element="archived tests on random_rowids">
**What changes:** none. The file is archived and not run. The same applies to `tests/archive/37_local_signal/test_random_videos.py` and `tests/archive/short_similarity_cache/test_similar.py` (which calls `search_index`/`fetch_metadata` positionally by rowid).

**Regression risk:** none while they stay archived. Reviving any of them needs the rename.
</impact>
<impact path="engine/server/data/interaction_events.py" element="rowid in raw-event retention (lines 176-177), DO NOT TOUCH">
**What changes:** none. `interaction_raw_events.rowid` is unrelated.

The same goes for these other non-embedding rowids:
- `engine/server/data/users.py`;
- `client/backend/lib/blocks.py` and `client/backend/lib/users_store.py`;
- the `sync-whitelist.py` FTS triggers and `content_rowid='rowid'` (lines 277-288, 400);
- `test-moderation-integration.py:536,560` and `test-orchestrator-smoke.py:288,314`.

**Regression risk:** a blanket search-and-replace for `rowid` would break FTS, retention and Client tables. The closing grep must be scoped to embedding readers under `engine/server/api` and `engine/server/data`, plus the two jobs.
</impact>
<impact path="docs/project/issues/08-stable-ann-ids.md" element="Status line (3), Comments, location">
**What changes:** at close, set `Status: enhancement, complete`, add a dated closing comment, and `git mv` the file to `docs/project/issues/archive/`.

Plan A's own checklist (`43-41`, line 852) called for a dated "plan A delivered" comment. That comment is not in the file. The last entry is the 2026-10-02 split note. Either plan A's close skipped it, or it was meant for this close.

**What depends on it:**
- `DATA_BUILD.md:191` links `docs/project/issues/08-stable-ann-ids.md` by path, and that link breaks after the move.
- `roadmap.md:45` names the issue by slug only.
- Historical plans and records link the old path. Leave those as they are.

**Regression risk:** a broken doc link.
</impact>
</impacts>


## Documentation to update

- [x] `DATA_BUILD.md` - updated: I updated `DATA_BUILD.md` for the move to ANN ids: the index cutover steps, the Engine's startup refusal, and the `random_ann_ids` random cache.
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: I added the one-time `ann_id` index cutover to section 1, a triage row for the Engine refusing an index whose `id_source` is not `video_embeddings.ann_id`, and the old random cache's rebuild on first start.
- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - updated: I updated UPDATER_WORKER.md so it requires the one-time index rebuild on `ann_id` before the first run, and so it describes the ANN rebuild and the `id_source` startup refusal.
- [x] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - updated: Added the ANN sidecar `id_source` check to the Pass/Fail list.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: LAYER_PARAMS.md: the random cache section now says the cache holds ANN ids (`random_ann_ids`), treats an old `random_rowids` file as having no table, and describes how the unfiltered build draws its window.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md: the random cache and its NSFW redraw now say ANN ids (`random_ann_ids`) where they said rowids.
- [x] `engine/server/README.md` - updated: I extended the "Reads from DB and FAISS index" note in `engine/server/README.md` to say the Engine needs an index keyed on `ann_id` and refuses to start without one.
- [x] `docs/project/issues/08-stable-ann-ids.md` - updated: Closed issue 08 (`Status: enhancement, complete`) with a dated note on what plan B delivered, and copied it to `docs/project/issues/archive/08-stable-ann-ids.md`. **The old file at `docs/project/issues/08-stable-ann-ids.md` is still there and needs deleting by hand (`git mv` or `rm`), because I have no tool that can delete files.**
- [x] `docs/project/roadmap.md` - updated: Roadmap: I added an F1-M2 / issue `08` (stable ANN ids) entry under "Delivered", removed F1-M2 from the open M2 list and marked `08` delivered in the implementation order.
- [x] `docs/project/issues/plan.md` - updated: I marked wave 5 lane 5a (issue 08, stable ANN ids) as delivered by plans 41 and 42, and pointed the cutover note at `DATA_BUILD.md`. Only `docs/project/issues/plan.md` changed.
- [x] `engine/server/db/jobs/whitelist_migrations.py` - updated: Reworded the `migrate_video_embeddings_schema` docstring so it says the ANN index must be rebuilt on `ann_id` before the Engine starts.
- [x] `scripts/run-reembed.sh` - out of scope: The comment at lines 26-28 says the Engine refuses a half-rebuilt pair because `api/server.py` compares the sidecar's `model_name`. That is still true. The added `id_source` check does not make it false, and a re-embed through `run-dataset-build.sh` writes the `ann_id` sidecar, so the requirement's optional mention is not needed.
- [x] `CONTEXT.md` - out of scope: **ANN id** already defines the id as the one an embedded video carries in the FAISS index and the random cache. That is exactly what this build delivered. No other term changed.
- [x] `docs/project/adr/0006-derived-ann-ids.md` - out of scope: The build implements Decision 4 as written: the sidecar has `id_source: video_embeddings.ann_id` and the Engine refuses any other source. The consequences hold as well: a stale index only misses, no rebuild for the similarity cache, and a one-time outage cutover. The `DEPLOYMENT.md` exception the ADR promises is covered by that document's entry above.
- [x] `docs/project/adr/0007-nsfw-filter-default-at-request-edge.md` - out of scope: Line 27 says "The random cache stores only rowids and no flag". The id kind is now ANN ids, but the point of the consequence still holds: the cache has no NSFW flag, and the flag is read at draw time, so no cache rebuild follows from it. An ADR records the decision as made, and this decision is untouched. The current cache shape is documented in `LAYER_PARAMS.md`.
- [x] `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md` - out of scope: The one-time outage cutover is an exception that ADR-0006 already records against ADR-0009. Blue/green itself is unchanged, and nothing ADR-0009 claims is false.

## Implementation plan

## Draft: plan B, readers and cutover on `ann_id`

I read every production file the plan touches: `ann_ids.py`, `build-ann-index.py`, `embedding_space.py`, `ann.py`, `embeddings.py`, `metadata.py`, `search.vector_candidates`, `similar._handle_vector_search`, `random_cache.py`, `random_videos.fetch_random_rows_from_cache`, `precompute-random-rowids.py`, `precompute-similar-ann.py` and the smoke test's `validate_outputs`. I also read the test harnesses I extend: `test_precompute_similar_ann.py`, `test_precompute_random_rowids.py`, `test_random_cache.py`'s engines test, the `_CHILD` in `test_search.py`, and `sync_job` and `similars_stack` in `test_video.py`. A `rowid` count over `engine/server/**/*.py` matches the inventory file for file.

Ladder: no new module beyond the two tests and no new dependency. Every change is a rename or rekey of code that already exists. The gate reuses the model check's shape, and old-shape cache detection reuses the existing `sqlite_master` name probe (rung 2). Converged in one pass.

### What the build has to test

| Behaviour | Where it is observed |
|---|---|
| The index stores exactly the DB's `ann_id` set; the sidecar `id_source` is `ANN_ID_SOURCE`; an old six-column table is refused naming `migrate-whitelist.py` (AC4) | `tests/active/test_ann_ids.py`: job subprocess, then an ENGINE_PY reader child |
| The gate passes the written sidecar and refuses `video_embeddings.rowid` and a missing `id_source`, naming `build-ann-index.py` (AC5) | `test_ann_ids.py`, in-process (`embedding_space` is stdlib plus `data.ann_ids`) |
| Similar and vector search resolve each hit to the video its id was built from, after a reverse reinsert, a host purge and a new video, with no index rebuild (AC8) | `tests/active/test_stale_ann_index.py`, ENGINE_PY `_CHILD` |
| Similarity precompute neighbours resolve by `ann_id`; no source lists itself (AC7) | `test_precompute_similar_ann.py` |
| The random cache is `random_ann_ids`, ids come from the source, and an old `random_rowids` `--out` at size is rebuilt (AC6) | `test_precompute_random_rowids.py`, `test_random_cache.py`, `test_db.py`, `test_random_videos.py` |
| `fetch_metadata` resolves by `ann_id`, and its output keys are unchanged | `test_metadata.py` (`ROW_KEYS`) |
| The full cycle writes the `ann_id` sidecar (AC9) | `test-orchestrator-smoke.py`, run manually |

### Module map

#### `engine/server/data/ann_ids.py` (phase 3)
Add next to `ANN_ID_MASK`. The module stays stdlib-only.
```python
# The sidecar id_source of an index whose FAISS ids are ann_id; build-ann-index.py writes it, embedding_space and the smoke test check it.
ANN_ID_SOURCE = "video_embeddings.ann_id"
```

#### `engine/server/db/jobs/build-ann-index.py` (phase 3)
```python
from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id
from data.embedding_space import resolve_embedding_space

@dataclass
class EmbeddingRow:
    """Represent embedding row behavior."""
    ann_id: int
    embedding: np.ndarray

# iter_embeddings
        for ann_id, embedding_blob, embedding_dim in rows:
            ...
            batch.append(EmbeddingRow(ann_id=ann_id, embedding=embedding))

# main()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Refused before anything is built: a table without ann_id would give an index the readers cannot resolve.
    assert_video_embeddings_has_ann_id(conn)

    dim, model_name = resolve_embedding_space(conn)
    ...
    query = "SELECT ann_id, embedding, embedding_dim FROM video_embeddings"
    for batch in iter_embeddings(conn, query, (), dim, args.batch_size):
        ids = np.array([item.ann_id for item in batch], dtype=np.int64)
    ...
        "id_source": ANN_ID_SOURCE,
```
- Invariant: every id is in 1..2^63-1, because of the mask and the CHECK, so int64 holds it.
- The write order stays index first, then sidecar.
- `fetch_training_samples` is left untouched (named simplification).

#### `engine/server/data/embedding_space.py` (phase 3)
Docstring paragraph appended after "These helpers are the readers of that record.":
> FAISS ids are `video_embeddings.ann_id` (ADR-0006), derived from each video's key rather than its row position. An index the table has since moved on from can therefore only miss a video, never name the wrong one. The sidecar records this as `id_source`, and an index with any other id source, such as the earlier rowid ids, is refused rather than read.

Import `from data.ann_ids import ANN_ID_SOURCE`, then add after the model check:
```python
    index_id_source = str(meta.get("id_source") or "")
    if index_id_source != ANN_ID_SOURCE:
        raise RuntimeError(
            f"Index ids come from {index_id_source or '<unset>'} but the readers resolve "
            f"{ANN_ID_SOURCE}. Rebuild the index with build-ann-index.py."
        )
```
- The success log gains `id_source=%s`.
- Both callers, `server.py:365` and `precompute-similar-ann.py:345`, are unchanged.
- No import cycle: `ann_ids` does not import `embedding_space`.

#### `engine/server/data/embeddings.py` (phase 1)
- `resolve_seed`: lines 73, 79 and 86 become `"exclude_ann_id": None`. In the found seed, `"exclude_ann_id": seed["ann_id"]` and `"ann_id": seed["ann_id"]`.
- `meta` is unchanged, so no id reaches JSON.
- The four selects become `e.ann_id AS ann_id,` (lines 123, 151, 217, 241).
- `_seed_from_row` returns `"ann_id": int(row["ann_id"])`.

#### `engine/server/data/ann.py` (phase 1)
```python
    ann_ids = [int(item) for item in ids[0] if int(item) > 0]
    logging.info("[similar-server] ann_ids=%d search_limit=%d", len(ann_ids), search_limit)
    ... fetch_metadata(server.db, ann_ids, ...)
    for score, ann_id in zip(scores[0], ids[0]):
        ann_id_int = int(ann_id)
        if ann_id_int == seed["ann_id"]:
            continue
        meta = metadata.get(ann_id_int)

# search_similar_above
    seed_ann_id = seed.get("ann_id")
    kept = [
        (float(score), int(ann_id))
        for score, ann_id in zip(scores[0], ids[0])
        if int(ann_id) > 0 and int(ann_id) != seed_ann_id and float(score) >= min_score
    ]
    ... [ann_id for _, ann_id in kept] ... metadata.get(ann_id)

def search_index(index, vector, limit, exclude_ann_id: int | None) -> tuple[list[int], list[float]]:
    """Search the ANN index and optionally exclude an ANN id."""
    # loop local ann_id; `if ann_id < 0` and the dedup are kept
```

#### `engine/server/api/handlers/similar.py` (phase 1)
- `ann_ids, scores = search_index(self.server.index, vector, limit, seed["exclude_ann_id"])`.
- `fetch_metadata(self.server.db, ann_ids, ...)`.
- `for ann_id, score in zip(ann_ids, scores): meta = metadata.get(ann_id)`.

#### `engine/server/data/search.py` (phase 1)
- Only the locals in `vector_candidates` change, to `ann_ids` and `ann_id`.
- `VIDEO_ROW_SQL` (`v.rowid`) and the FTS join stay as they are.

#### `engine/server/data/metadata.py` (phase 1)
`fetch_metadata(conn, ann_ids: list[int], ...)`, with the docstring "Fetch video metadata for embedding ANN ids." The changes:
- `_chunk(ann_ids, 900)`;
- `e.ann_id AS ann_id`;
- `WHERE e.ann_id IN ({placeholders})`, served by `idx_video_embeddings_ann_id`;
- `result[int(row["ann_id"])]`.

The output dict is unchanged, and `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` are untouched.

#### `engine/server/db/jobs/precompute-similar-ann.py` (phase 1)
- `iter_embedding_rows_by_ann_ids(conn, ann_ids, batch_size=512)` selects `ann_id, video_id, instance_domain, embedding, embedding_dim ... WHERE ann_id IN (...)`.
- `fetch_similarity_targets(conn, ann_ids)` selects `ann_id, video_id, instance_domain ... WHERE ann_id IN` and returns `{row["ann_id"]: dict(row)}`. `fetch_similarity_targets_chunked(conn, ann_ids, chunk_size=5000)` only has its parameters renamed.
- The two selection queries use `SELECT e.ann_id`, giving `pending_ann_ids = [int(row["ann_id"]) ...]`, then `iter_embedding_rows_by_ann_ids(src_db, pending_ann_ids)`. The comment at line 366 becomes "only ANN ids are materialized".
- The full mode uses `SELECT ann_id, video_id, instance_domain, embedding, embedding_dim`.
- The batch uses `batch_ann_ids` and `targets_by_ann_id`, and the loop reads `ann_id_int = int(ann_id); if ann_id_int == row["ann_id"] or ann_id_int <= 0: continue`.
- The `video_keys`/`similarity_sources` joins, `write_similarities`, the `mode=ro` source and the gate call are untouched.

#### `engine/server/data/random_cache.py` (phase 2)
```python
RANDOM_CACHE_CHECK_SQL = "SELECT COUNT(*) FROM random_ann_ids"

def ensure_random_cache_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS random_ann_ids (
          position INTEGER PRIMARY KEY,
          ann_id INTEGER NOT NULL
        );
        """)

def random_ann_ids_count(conn: sqlite3.Connection) -> int | None:
    """Return the number of cached ANN ids, or None when the random_ann_ids table is missing, as in a cache written before the ANN-id cutover (random_rowids)."""
    # fetchall, so no statement is left holding SHARED on the file.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'random_ann_ids' LIMIT 1").fetchall():
        return None
    return int(conn.execute("SELECT COUNT(*) FROM random_ann_ids").fetchall()[0][0])
```
`populate_random_cache`:
- The reuse check uses `random_ann_ids_count`, and the count and delete run on `random_ann_ids`.
- The source stats query is `SELECT COUNT(*) AS total, MIN(ann_id) AS min_id, MAX(ann_id) AS max_id FROM video_embeddings`.
- The unfiltered window is `SELECT ann_id FROM video_embeddings WHERE ann_id >= ? ORDER BY ann_id LIMIT ?`, plus the `ann_id < ?` wrap.
- The insert is `INSERT INTO random_ann_ids (position, ann_id) VALUES (?, ?)` with `int(row["ann_id"])`.
- Filtered: the local list `rowids` becomes `ann_ids`, and `try_add` reads `entry["ann_id"]`. `scan_range` selects `e.ann_id AS ann_id`, uses `WHERE e.ann_id >= ? AND e.ann_id <= ? ORDER BY e.ann_id`, and advances with `current = int(rows[-1]["ann_id"]) + 1`.
- Overflow: the `while current <= range_end` test stays first, so 2^63 is never bound.
- Docstrings: `build_random_cache` ":returns: (temp path, ANN ids written, elapsed seconds)", and `open_random_cache_if_usable` "holds at least one ANN id". `open_random_cache_if_usable` calls `random_ann_ids_count`, so an old file logs `reason=no_table`.

```python
def fetch_random_ann_ids(cache_db: sqlite3.Connection, limit: int) -> list[int]:
    """Return a random window of cached ANN ids."""
    ...COUNT(*) FROM random_ann_ids ...
    "SELECT ann_id FROM random_ann_ids ORDER BY position LIMIT ? OFFSET ?"
    return [int(row["ann_id"]) for row in rows]
```

#### `engine/server/data/random_videos.py` (phase 2)
- `from data.random_cache import fetch_random_ann_ids`.
- In `fetch_random_rows_from_cache`, the locals become `ann_ids`/`ann_id`.
- The docstring becomes "...using the precomputed ANN-id cache; ... a draw adds no unseen ANN id."

#### `engine/server/db/jobs/precompute-random-rowids.py` (phase 2)
- Docstring: "Provide precompute-random-rowids runtime helpers; the cache holds ANN ids (random_ann_ids)."
- It imports `random_ann_ids_count`, and the keep check becomes `existing = random_ann_ids_count(existing_db) or 0`.
- `description="Precompute random ANN-id cache."` and `help="ANN ids to sample."`.
- The file name and CLI are unchanged.

#### `engine/server/api/server_config.py` (phase 2)
The comment changes to "Precomputed random ANN ids".

#### `engine/server/db/jobs/tests/test-orchestrator-smoke.py` (phase 3)
`from data.ann_ids import ANN_ID_SOURCE, ensure_video_embeddings_schema`. After `checks["ann_meta_total"] = meta_total`:
```python
    if meta.get("id_source") != ANN_ID_SOURCE:
        raise RuntimeError(
            "ANN meta id_source does not match the readers: "
            f"meta.id_source={meta.get('id_source')} expected={ANN_ID_SOURCE}"
        )
    checks["ann_id_source"] = ANN_ID_SOURCE
```

### New tests

#### `tests/active/test_ann_ids.py` (phase 3, AC4/AC5)
- It runs under the system pytest and inserts `ROOT/engine/server` on `sys.path`, then `from data.ann_ids import ANN_ID_SOURCE, compute_ann_id, ensure_video_embeddings_schema` and `from data.embedding_space import assert_index_matches_embeddings`.
- Fixture: a tmp `source.db` built through `ensure_video_embeddings_schema`, with N=64 rows `v{i}`@`a.example`, `DIM=8`, deterministic `struct.pack("<8f", ...)` vectors, one model, and `ann_id=compute_ann_id(...)`.
- Job: `ENGINE_PY build-ann-index.py --cpu --db-path <tmp> --index-path <tmp>/i.faiss --meta-path <tmp>/i.faiss.json --nlist 2 --m 2 --nbits 4 --train-sample 64`. The parameters are chosen so that 8 % 2 == 0, 64 ≥ nlist, 64 ≥ 2^4, and step is 1. The explicit paths avoid touching `engine/server/db/video-embeddings.faiss`.
- Assertions:
  - The exit code is 0.
  - An ENGINE_PY `-c` child prints `sorted(int(x) for x in faiss.vector_to_array(faiss.read_index(p).id_map))`, and that list equals `sorted(SELECT ann_id)`.
  - `meta["id_source"] == ANN_ID_SOURCE` and `meta["total"] == 64`.
- Old-shape case: a six-column `video_embeddings` with no `ann_id` and one row. The job exits non-zero, stderr contains `migrate-whitelist.py`, and no index file is written.
- Gate cases (in-process; stub `types.SimpleNamespace(d=8)`):
  - The written sidecar passes.
  - Rewriting it with `id_source: "video_embeddings.rowid"` raises a RuntimeError that matches `video_embeddings.rowid` and `build-ann-index.py`.
  - With the key removed, it raises and matches `<unset>`.
  - A control asserts that the model-mismatch refusal still fires first.

#### `tests/active/test_stale_ann_index.py` (phase 1, AC8)
- **The outer process builds the DB.** Like `test_video.py`, it loads `sync-whitelist.py` through `spec_from_file_location`, calls `ensure_whitelist_schema` and `ensure_content_schema` (which create `video_embeddings` with `ann_id` and its guards), and inserts 12 videos into `videos`, each with `last_checked_at`, a `channel_id` and `nsfw` 0. Hosts: v0..v7 on `keep.example` and v8..v11 on `purge.example`. Embeddings are `DIM=4`, with distinct vectors from a fixed `math.cos`/`sin` formula and `ann_id=compute_ann_id(...)`.
- **The ENGINE_PY child.** It sets `sys.path[:0] = [server, server/api]` and builds `IDMap2,IVF1,Flat`, `METRIC_INNER_PRODUCT`, from `SELECT ann_id, embedding`. That search is exact. It records `recorded = {ann_id: (video_id, host)}`. Then, per case, it copies the DB with `shutil.copy` and mutates the copy without rebuilding the index:
  - **A:** `rows = SELECT * FROM video_embeddings ORDER BY rowid`, then `DELETE`, then reinsert `reversed(rows)`. A control asserts that the rowid→key mapping changed.
  - **B:** `purge_host_data(conn, "purge.example")`.
  - **C:** insert video `new` on `keep.example` whose vector equals the probe, with its computed `ann_id`.
- **The stub server.** `SimpleNamespace(index, index_lock, db, db_lock, normalize_queries=False, similarity_search_limit=0, similarity_exclude_source_author=False, similarity_max_per_author=0, video_error_threshold=None, query_encoder=SimpleNamespace(enabled=True, encode=lambda text: probe))`.
- **The seed.** `embeddings.resolve_seed(conn, 4, None, "v0", "keep.example", None)`, which exercises the producer rename. The probe is v0's vector.
- **Expected results**, with `present = {SELECT ann_id}` and limit 50, which is greater than N:
  - similar: `[recorded[i] for i in index.search(probe, 51) ids if i > 0 and i != seed_ann_id and i in present]`;
  - search: the same list without the self-exclusion, over `search_index`'s first `limit` unique ids.
- **The child prints, per case,** the actual similar and search keys next to the expected ones. The outer test asserts:
  - actual == expected, and expected is non-empty (control);
  - in case B, no `purge.example` key appears, and a control shows the host had hits before the purge;
  - in case C, `("new", "keep.example")` appears in neither list.
- A reader still joining on rowid would return nothing for 63-bit ids, and a rowid-keyed index would be permuted by case A. The equality check fails either way.

### Edits to existing tests
- **`test_precompute_similar_ann.py` (phase 1):**
  - The DDL gains `ann_id INTEGER NOT NULL`, and rows carry `compute_ann_id(f"v{rowid}", DOMAIN)`. The explicit rowid inserts stay.
  - `INDEX_BUILDER` uses `SELECT ann_id, embedding`.
  - The sidecar adds `"id_source": "video_embeddings.ann_id"`.
  - The incremental test asserts that no source's items contain its own key. Its TOP2 expectations are keyed by label, so they already prove that targets resolve to the hit's video.
- **`test_metadata.py` (phase 1):** the nsfw fixture DDL gains `ann_id`, inserts pass `compute_ann_id(label, HOST)`, and `_nsfw_metadata` selects `ann_id`.
- **`test_video.py` (phase 1):** `similars_stack` uses `SELECT ann_id, embedding` and `r["ann_id"]`.
- **`test_precompute_random_rowids.py` (phase 2):**
  - Add `sys.path.insert(0, str(ROOT / "engine" / "server"))` and import `compute_ann_id`.
  - The source gains `ann_id`. `SOURCE_IDS = sorted(compute_ann_id(f"v{i}", "a.example") ...)` replaces `range(1, 21)`.
  - The helpers move to `random_ann_ids(position, ann_id)`.
  - New case `old_shape`: seed `random_rowids` with 20 rows. The job, without flags at `--size 20`, gives a new inode, `random_ann_ids` holding exactly `SOURCE_IDS`, and no `random_rowids` table.
- **`test_random_cache.py` (phase 2):**
  - The table, column and helper renames throughout. `_source_db` gains `ann_id`, and positional expectations become the computed id set.
  - The Engine helpers select `ann_id`.
  - The `no_table` probe writes a `random_rowids` file.
  - The engines test (lines 691 and 706) reads and locks `random_ann_ids`.
- **`test_db.py` (phase 2):** it imports `fetch_random_ann_ids`. `CHECK_SQL` and `_seed_cache` use `random_ann_ids`, and the source gains `ann_id`.
- **`test_random_videos.py` (phase 2):**
  - `NSFW_EMBEDDINGS_TABLE` gains `ann_id`, and both positional inserts (lines 389 and 477) add `compute_ann_id(label, NSFW_HOST)`.
  - `_video_db` returns label→ann_id.
  - `_cache_owner` creates `random_ann_ids` and monkeypatches `random_videos.fetch_random_ann_ids`, wrapping `random_cache.fetch_random_ann_ids`.
- **`tests/config.json`:**
  - new groups: `test_stale_ann_index.py` maps to ann.py, search.py, metadata.py, embeddings.py, ann_ids.py and handlers/similar.py; `test_ann_ids.py` maps to build-ann-index.py, embedding_space.py and ann_ids.py;
  - `engine/server/data/ann_ids.py` is added to the six importing groups;
  - `embedding_space.py` and `precompute-similar-ann.py` stay or are added on `test_precompute_similar_ann`;
  - `random_cache.py` is added to `test_db.py`.

### Docs (phase 3; the settled list)
- **`DATA_BUILD.md`:**
  - the cutover: stop, `migrate-whitelist.py`, then `build-ann-index.py` with the explicit served `--index-path`/`--meta-path` `whitelist-video-embeddings.faiss[.json]`, then start;
  - the line 166 wording;
  - line 191's link moves to `issues/archive/`;
  - line 232: `ann_id`, `id_source`, and the refusals;
  - lines 290 and 335: `random_ann_ids`.
- **`DEPLOYMENT.md`:** the line 42 cutover and refusal, two triage rows, and the first-start rebuild of an old-shape cache at line 421.
- The remaining files take the settled edits as listed: `UPDATER_WORKER.md`, `ORCHESTRATOR_SMOKE_TEST.md`, `LAYER_PARAMS.md`, `OVERVIEW.md` and `engine/server/README.md`.
- **The issue:** `Status: enhancement, complete`, one dated comment covering plans 41 and 42 (which folds in plan A's missing "delivered" note), and `git mv` to `docs/project/issues/archive/`.

### Closing grep (end of phase 3)
`rg -n 'rowid' engine/server/api engine/server/data engine/server/db/jobs/precompute-similar-ann.py engine/server/db/jobs/build-ann-index.py`. The only hits allowed:
- `search.py` `VIDEO_ROW_SQL` and the FTS join;
- `users.py` and `interaction_events.py`;
- `fetch_training_samples`.

### Phasing
All three phases merge together. Each checkpoint stays green when the next phase lands.
1. **Readers and similarity precompute.** Checkpoint: `test_stale_ann_index`, `test_precompute_similar_ann` (its sidecar already carries `id_source`), `test_metadata`, and `test_video` similars.
2. **Random cache.** Checkpoint: `test_precompute_random_rowids` including `old_shape`, `test_random_cache` in-process cases, `test_db`, `test_random_videos`.
3. **`ANN_ID_SOURCE`, index build, gate, smoke assertion, docs.** Checkpoint: `test_ann_ids`.

### Decisions and named simplifications
- **Training samples** keep `rowid % step`. Ceiling: recall only. Upgrade: one token, `ann_id % step`.
- **Old-cache detection** is by table name. Ceiling: a reshape under the same name. Upgrade: a `PRAGMA table_info` check in `random_ann_ids_count`.
- **No startup DB-shape check** (AC5 does not ask for one). Upgrade: `assert_video_embeddings_has_ann_id(db)` next to `server.py:346`.

### Operator coordination (from the inventory, made concrete)
- **Shared files.** The worktree's `whitelist.db` and `whitelist-video-embeddings.faiss[.json]` are symlinks to main's live files. Rebuilding them from here would switch main to `ann_id` ids before main has the readers. The full suite after phase 3 therefore needs either a coordinated main cutover or private copies in the worktree.
- **The engines test** (`test_engines_starting_at_once_all_become_healthy`) needs a short new-shape cache, or its premise does not hold. The old-shape copied `random-cache.db` makes the session Engine run a background build of up to 500k rows, which can fail its "short cache" control. Before the suite, run `precompute-random-rowids.py --refresh` (default `--size 5000`) on the worktree's own `engine/server/db/random-cache.db` copy, after the dataset migration.
- **The smoke test** needs a migrated `--source-db` and is run manually.

### Phases

#### Phase 1 - Readers and similarity precompute on ann_id [code]

**Files touched.** engine/server/data/embeddings.py (EDITED), engine/server/data/ann.py (EDITED), engine/server/api/handlers/similar.py (EDITED), engine/server/data/search.py (EDITED), engine/server/data/metadata.py (EDITED), engine/server/db/jobs/precompute-similar-ann.py (EDITED), tests/active/test_stale_ann_index.py (NEW), tests/active/test_precompute_similar_ann.py (EDITED), tests/active/test_metadata.py (EDITED), tests/active/test_video.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the Engine's in-process reader functions `ann.compute_similar_items` and `search.vector_candidates`, called on a stub server inside an ENGINE_PY child. This follows the `_CHILD` precedent in `tests/active/test_search.py` and the `spec_from_file_location` loading of `sync-whitelist.py` in `test_video.py`. New `tests/active/test_stale_ann_index.py` builds 12 videos through `ensure_whitelist_schema`/`ensure_content_schema` and an exact `IDMap2,IVF1,Flat` index on `ann_id`, and records `ann_id -> (video_id, host)`. It then runs three cases, each against an unrebuilt index: A, reverse reinsert, with a control showing that the rowid→key mapping changed; B, `purge_host_data`; C, an unindexed new video equal to the probe. Assertions per case: similar keys == expected and search keys == expected, and expected is non-empty. In B, no `purge.example` key appears, with a control showing that host had hits before the purge. In C, `("new","keep.example")` is in neither list. The seed comes from `embeddings.resolve_seed`, which exercises the producer rename. Clause 2 seam: the `precompute-similar-ann.py` job subprocess in the existing `tests/active/test_precompute_similar_ann.py` harness. Its fixture DDL gains `ann_id`, `INDEX_BUILDER` indexes `ann_id`, and the sidecar gains `"id_source": "video_embeddings.ann_id"` so that phase 4's gate leaves it green. The label-keyed TOP2 expectations are asserted, and a new assertion checks that no source's items contain its own key. The supporting edits `test_metadata.py` (ann_id fixture, `ROW_KEYS` unchanged) and `test_video.py` `similars_stack` (`SELECT ann_id`) must stay green.

**Intent.** The Engine's similar and vector-search readers (`embeddings.py` seeds, `ann.py`, `handlers/similar.py`, `search.vector_candidates`, `metadata.fetch_metadata`) and `precompute-similar-ann.py` resolve FAISS ids through `video_embeddings.ann_id`, so a hit names the video its id was built from even when the index is stale, and a precomputed source never lists itself.

- C1 - `compute_similar_items` and `vector_candidates` resolve every hit to the video its `ann_id` was built from, against an index not rebuilt after a reverse reinsert, a host purge or a new video.
- C2 - `precompute-similar-ann.py` writes each source's neighbours as the videos their `ann_id`s name, never the source itself.

**Outcome.** ### `engine/server/data/embeddings.py`
- `resolve_seed`: every return shape (zero vector, parsed vector, not found, found seed) uses `exclude_ann_id` where it had `exclude_rowid`. The found seed carries `"exclude_ann_id": seed["ann_id"]` and `"ann_id": seed["ann_id"]`. `meta` is unchanged, so no id reaches JSON.
- The four `e.rowid AS rowid` selects (`_fetch_seed_by_uuid`, `_fetch_seed_by_id`, both queries in `fetch_seed_embeddings_for_likes`) are now `e.ann_id AS ann_id`.
- `_seed_from_row` returns `"ann_id": int(row["ann_id"])`.

### `engine/server/data/ann.py`
- `compute_similar_items`: hits are `ann_ids`, still filtered `> 0`. The log key `ann_rowids=` is now `ann_ids=`. The loop excludes the seed with `ann_id_int == seed["ann_id"]` and looks up metadata by ANN id.
- `search_similar_above`: excludes `seed.get("ann_id")` and keeps the `> 0` and score-floor filters. Metadata is fetched and looked up by ANN id.
- `search_index`: the fourth positional parameter is now `exclude_ann_id`; the docstring and loop local follow. The `< 0` filter and the dedup are unchanged. The nprobe helpers are untouched.

### `engine/server/data/metadata.py`
`fetch_metadata(conn, ann_ids, ...)` selects `e.ann_id AS ann_id`, filters `WHERE e.ann_id IN (...)` (served by plan A's UNIQUE `idx_video_embeddings_ann_id`), and keys its result by `ann_id`. The docstring now says "embedding ANN ids". The 29-key output dict is unchanged. `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` are untouched.

### `engine/server/data/search.py`
`vector_candidates`: only the locals are renamed (`ann_ids` / `ann_id`). `VIDEO_ROW_SQL`'s `v.rowid` and the `videos_fts` join are left alone; they link to FTS, not to embeddings.

### `engine/server/api/handlers/similar.py`
`_handle_vector_search` passes `seed["exclude_ann_id"]` to `search_index` and resolves hits through `fetch_metadata` by ANN id.

### `engine/server/db/jobs/precompute-similar-ann.py`
- `iter_embedding_rows_by_rowids` is now `iter_embedding_rows_by_ann_ids`, selecting `ann_id, video_id, instance_domain, embedding, embedding_dim ... WHERE ann_id IN`.
- `fetch_similarity_targets` / `fetch_similarity_targets_chunked` take `ann_ids`, select `ann_id`, and return `{ann_id: row}`.
- Both pending-selection queries select `e.ann_id`, which feeds `pending_ann_ids`. The full-mode SELECT reads `ann_id`.
- The main loop uses `batch_ann_ids` / `targets_by_ann_id` and skips self with `ann_id_int == row["ann_id"] or ann_id_int <= 0`.
- The comment above the selection now says "only ANN ids are materialized".
- Untouched: the `video_keys` / `similarity_sources` joins, the output keys, `write_similarities`, the `mode=ro` source and the gate call.

### `tests/active/test_precompute_similar_ann.py` (fixture churn)
- Imports `compute_ann_id` from `data.ann_ids`; `engine/server` was already on `sys.path`.
- The source table gains `ann_id INTEGER NOT NULL`, and every row, the short v9 included, carries `compute_ann_id(f"v{rowid}", DOMAIN)`. The explicit rowids stay as labels.
- `INDEX_BUILDER` adds by `SELECT ann_id, embedding`.
- The sidecar gains `"id_source": "video_embeddings.ann_id"`, so phase 4's gate will accept it.
- The fixture docstring now says this.
- No expectation changed.

### `tests/active/test_metadata.py` (fixture churn)
Imports `compute_ann_id`. The `nsfw_conn` fixture's `video_embeddings` gains `ann_id INTEGER`, and its positional insert passes `compute_ann_id(label, HOST)`. `_nsfw_metadata` passes `SELECT ann_id` ids to `fetch_metadata`. `ROW_KEYS` and every expectation are unchanged. The `conn` fixture only feeds the by-ids and by-uuids lookups and is untouched.

### `tests/active/test_video.py` (fixture churn)
`similars_stack` builds its in-process index from `SELECT ann_id, embedding` and adds with `r["ann_id"]`. The inserts already carried `ann_id` from plan A.

### `tests/config.json`
`engine/server/data/ann_ids.py` is added to the `test_metadata.py` and `test_precompute_similar_ann.py` groups, since both now import it.

### Not created: `tests/active/test_stale_ann_index.py`
This file is where the checkpoint's C1 half gets promoted. Following plan A's precedent (records 43-41, steps 7:1/7:3/7:4), I did not write a parallel copy now; it would duplicate the checkpoint. For the same reason no `test_stale_ann_index.py` group was added to `tests/config.json`: it would name a file that does not exist yet. That group belongs with the promotion and should map to `ann.py`, `search.py`, `metadata.py`, `embeddings.py`, `ann_ids.py` and `handlers/similar.py`.

### Observed
I ran `tests/tmp/test_42_ann_ids_b_readers_cutover_phase1.py` once through ValidateTests: 7 passed (4 stale-index reader cases plus the 3 precompute modes). I did not run the durable tests I edited.

### Breaks until phase 2 lands
`random_videos.fetch_random_rows_from_cache` still passes random-cache **rowids** to `fetch_metadata`, which now resolves by `ann_id`. Until phase 2 moves the cache to `random_ann_ids`, cached random draws resolve to nothing, and the Engine falls back to the DB path when the page is empty. `tests/active/test_random_videos.py`'s cache cases will also fail, because their fixture `video_embeddings` has no `ann_id`. Phase 2's files list already covers both, and the plan merges all phases together.

#### Phase 2 - Random cache on ann_id [code]

**Files touched.** engine/server/data/random_cache.py (EDITED), engine/server/data/random_videos.py (EDITED), engine/server/db/jobs/precompute-random-rowids.py (EDITED), engine/server/api/server_config.py (EDITED), tests/active/test_precompute_random_rowids.py (EDITED), tests/active/test_random_cache.py (EDITED), tests/active/test_db.py (EDITED), tests/active/test_random_videos.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Clause 1 seam: the job subprocess `precompute-random-rowids.py` in the existing `tests/active/test_precompute_random_rowids.py` harness. Its source gains `ann_id`, and `SOURCE_IDS` is the computed `compute_ann_id` set. It asserts that `random_ann_ids(position, ann_id)` holds exactly `SOURCE_IDS`. Supporting this, at the Engine-side functions: the in-process cases in `test_random_cache.py` (unfiltered and filtered populate draw only source `ann_id`s, and `fetch_random_ann_ids` returns them), the `test_db.py` cache path through `fetch_random_ann_ids`, and `test_random_videos.py` (`fetch_random_rows_from_cache` resolves the cached `ann_id`s to their labelled videos through a `_cache_owner` that wraps `random_cache.fetch_random_ann_ids`). Clause 2 seam: the same job subprocess, new case `old_shape`. An existing `--out` holding 20 `random_rowids` rows, run without flags at `--size 20`, gives a new inode, `random_ann_ids` equal to `SOURCE_IDS`, and no `random_rowids` table. Engine side: the `test_random_cache.py` `no_table` probe writes a `random_rowids` file, and `open_random_cache_if_usable` returns None and logs `reason=no_table`.

**Intent.** The random cache (`random_cache.py`, `random_videos.py`, `precompute-random-rowids.py`) holds and serves `ann_id`s in a `random_ann_ids` table drawn from `video_embeddings.ann_id`. An old `random_rowids` cache is no longer usable and is rebuilt into the new shape.

- C1 - The random cache stores and serves `ann_id`s from a `random_ann_ids` table, drawn from the source's `ann_id` set.
- C2 - A cache holding only `random_rowids` is treated as having no table and is rebuilt into the `random_ann_ids` shape.

**Outcome.** ### `engine/server/data/random_cache.py`
- The cache table is now `random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)`. Before it was `random_rowids (position, video_rowid)`. `RANDOM_CACHE_CHECK_SQL` names the new table, so a swap can only install a file in the new shape.
- `random_rowids_count` is renamed `random_ann_ids_count` and looks for `random_ann_ids`. A file holding only `random_rowids` returns None. So `open_random_cache_if_usable` logs `reason=no_table` for it through its existing path, with no new code. A `rat-tail:` comment says the old cache is detected by table name, not by shape; if the table is ever reshaped under the same name, the upgrade is a `PRAGMA table_info` check.
- `populate_random_cache` now works on `video_embeddings.ann_id` instead of `rowid`:
  - the stats query takes `MIN/MAX(ann_id)`;
  - the unfiltered window runs from `ann_id >= start` and wraps to `ann_id < start`;
  - the filtered `scan_range` selects, filters, orders and advances on `e.ann_id`;
  - the local list is renamed `ann_ids`, and both inserts write `random_ann_ids (position, ann_id)`.
  
  A comment above the start draw says why the window is still a uniform sample: hashed ids are spread evenly across the range.
- `fetch_random_rowids` is renamed `fetch_random_ann_ids` and reads `SELECT ann_id FROM random_ann_ids ORDER BY position`. Docstrings for `build_random_cache`, `open_random_cache_if_usable` and the fetch now say ANN ids.

### `engine/server/data/random_videos.py`
- It imports `fetch_random_ann_ids`. In `fetch_random_rows_from_cache` the locals are now `ann_ids`, and they go straight to `fetch_metadata`, which already resolves by `ann_id` since Phase 1. The docstring says "ANN-id cache" and "unseen ANN id".

### `engine/server/db/jobs/precompute-random-rowids.py`
- The keep check now uses `random_ann_ids_count`. An old `random_rowids` `--out` counts as 0, so it is rebuilt by rename rather than kept.
- The description is now "Precompute random ANN-id cache." and the `--size` help "ANN ids to sample.".
- The file name and arguments are unchanged.

### `engine/server/api/server_config.py`
- The comment on `DEFAULT_RANDOM_CACHE_SIZE` now says "random ANN ids".

### `tests/active/test_precompute_random_rowids.py`
- These are the plan's fixture changes, done in place as Phase 1 did for its tests:
  - `engine/server` is added to `sys.path` and `compute_ann_id` is imported;
  - the source table gains `ann_id`, filled with computed ids;
  - `_seed_cache` and `_cache_rows` use `random_ann_ids(position, ann_id)`;
  - the "rowids 1..20" expectations become `SOURCE_IDS`, the sorted computed ids;
  - the docstrings are updated.
- I did not add the plan's new `old_shape` case. The checkpoint already pins it, and Phase 1 left that copy for when the checkpoint is promoted.

### `tests/active/test_db.py`
- Imports `compute_ann_id` and `fetch_random_ann_ids`.
- `SEEDED_ROWIDS` is now the computed ids of v7, v3 and v11, and `SEEDED_ROWS` is built from them.
- `CHECK_SQL` and `_seed_cache` use `random_ann_ids`, and the source gains `ann_id`.
- `_served_rowids` is renamed `_served_ann_ids`, and the docstring is updated.

### `tests/active/test_random_videos.py`
- `NSFW_EMBEDDINGS_TABLE` gains `ann_id INTEGER NOT NULL`. Both embedding inserts (`nsfw_conn` and `_video_db`) carry `compute_ann_id(label, NSFW_HOST)`.
- `_video_db` returns a map from label to ann_id.
- `_cache_owner` writes a `random_ann_ids` table, wraps `random_cache.fetch_random_ann_ids`, and monkeypatches `random_videos.fetch_random_ann_ids`.
- The docstring and one comment are updated. Test function names are unchanged, so test ids stay the same.

### `tests/active/test_random_cache.py`
- Imports `compute_ann_id` and adds `SOURCE_IDS`. `SEEDED_ROWIDS`/`SEEDED_ROWS` become computed ids, and `_source_db` gains `ann_id`.
- Every `random_rowids`/`video_rowid` read, write, delete and drop now uses `random_ann_ids`/`ann_id`. That includes the engines test's count and its lock probe.
- Expectations of "rowids 1..20" become `SOURCE_IDS`.
- Helpers renamed: `_cache_rowids` to `_cache_ann_ids`, `_served_rowids` to `_served_ann_ids`, `_feed_rowids` to `_feed_ann_ids`.
- The Engine helpers now select `ann_id`: `_feed_ann_ids` looks it up by `(video_id, instance_domain)`, and `_seed_servable_cache` selects `e.ann_id ORDER BY e.ann_id`.
- The `no_table` probe of `open_random_cache_if_usable` now writes an old-format `random_rowids` file with rows, replacing the unrelated `other` table.
- The module docstring is updated.

### `tests/config.json`
- `test_db.py` now maps `random_cache.py` and `ann_ids.py`.
- `test_random_videos.py` now maps `random_cache.py` and `ann_ids.py`.
- `test_random_cache.py` and `test_precompute_random_rowids.py` now map `ann_ids.py`.

#### Phase 3 - Index build keyed by ann_id [code]

**Files touched.** engine/server/data/ann_ids.py (EDITED), engine/server/db/jobs/build-ann-index.py (EDITED), tests/active/test_ann_ids.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the real job CLI `build-ann-index.py` as an ENGINE_PY subprocess (rung 2), following the job-subprocess precedent in `test_precompute_similar_ann.py`/`test_precompute_random_rowids.py`. New `tests/active/test_ann_ids.py` builds a 64-row tmp `source.db` through `ensure_video_embeddings_schema` (DIM=8, `ann_id=compute_ann_id`). It runs `--cpu --db-path --index-path --meta-path --nlist 2 --m 2 --nbits 4 --train-sample 64`, with explicit tmp paths so the served index is never touched. Clause 1 assertions: exit 0; an ENGINE_PY `-c` child's `sorted(faiss.vector_to_array(read_index(p).id_map))` == `sorted(SELECT ann_id)`; sidecar `id_source == ANN_ID_SOURCE` and `total == 64`. Clause 2 assertions on a six-column table with no `ann_id`: non-zero exit, stderr contains `migrate-whitelist.py`, and no index file exists at `--index-path`.

**Intent.** `build-ann-index.py` builds its FAISS index from `video_embeddings.ann_id` and records that in the sidecar as `id_source = ANN_ID_SOURCE` (new constant in `data/ann_ids.py`), and it refuses before building anything when the table has no `ann_id` column.

- C1 - `build-ann-index.py` writes an index whose FAISS ids are exactly the DB's `ann_id` set, with sidecar `id_source` equal to `ANN_ID_SOURCE`.
- C2 - `build-ann-index.py` refuses a `video_embeddings` table without `ann_id`, naming `migrate-whitelist.py`, and writes no index.

**Outcome.** ### `engine/server/data/ann_ids.py`
- Added the module constant `ANN_ID_SOURCE = "video_embeddings.ann_id"`. It is the value an index keyed by ann_id writes as the sidecar's `id_source`.

### `engine/server/db/jobs/build-ann-index.py`
- Imports `ANN_ID_SOURCE` and `assert_video_embeddings_has_ann_id` from `data.ann_ids`.
- `main()` calls `assert_video_embeddings_has_ann_id(conn)` straight after connecting, before `resolve_embedding_space`, training or any write. A `video_embeddings` table without `ann_id` therefore raises the existing RuntimeError, which names `engine/server/db/jobs/migrate-whitelist.py`. The job exits non-zero and writes no index file and no sidecar.
- Renamed the field `EmbeddingRow.rowid` to `ann_id`, and `iter_embeddings` now unpacks `ann_id`. Both are used only in this file.
- The add query is now `SELECT ann_id, embedding, embedding_dim FROM video_embeddings`, and `add_with_ids` gets the ann_ids as int64.
- The sidecar's `id_source` is now `ANN_ID_SOURCE`, where it used to be the literal `"video_embeddings.rowid"`.
- `fetch_training_samples` still samples with `rowid % step`. That only spreads the training sample out and is never used as an id. A `rat-tail:` comment there names the limit: a sparse rowid range under-fills the sample, and the fix would be `ORDER BY RANDOM()` or a stride over ann_id.

#### Phase 4 - Engine id-source gate [code]

**Files touched.** engine/server/data/embedding_space.py (EDITED), engine/server/db/jobs/tests/test-orchestrator-smoke.py (EDITED), tests/active/test_ann_ids.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: `embedding_space.assert_index_matches_embeddings`, called in-process (rung 1), which is the shared function both `api/server.py` startup and `precompute-similar-ann.py` call. The cases are added to `tests/active/test_ann_ids.py` and reuse phase 3's built sidecar with a stub index `SimpleNamespace(d=8)`. Assertions: the written sidecar passes (positive half). Rewritten with `id_source: "video_embeddings.rowid"`, it raises a RuntimeError whose message contains both `video_embeddings.rowid` and `build-ann-index.py`. With `id_source` removed, it raises with `<unset>`. A control with a model mismatch still raises the model refusal first. The smoke-test `validate_outputs` assertion on `id_source` cannot be entered in-process: it needs a full orchestrator cycle on a migrated source DB and is run manually (see needs_coordination).

**Intent.** `assert_index_matches_embeddings` in `embedding_space.py` refuses any index whose sidecar `id_source` is not `ANN_ID_SOURCE`, so the Engine and the similarity precompute serve only `ann_id`-keyed indexes, and the orchestrator smoke test checks the same sidecar field.

- C1 - `assert_index_matches_embeddings` accepts an index whose sidecar `id_source` is `ANN_ID_SOURCE` and refuses any other or missing `id_source` with a message naming `build-ann-index.py`.

**Outcome.** ### `engine/server/data/embedding_space.py`
- Imports `ANN_ID_SOURCE` from `data.ann_ids`. That module is stdlib only, and every importer (`api/server.py`, `build-ann-index.py`, `precompute-similar-ann.py`, the system-interpreter tests) already has the server dir on its path, so the import is safe for all of them.
- `assert_index_matches_embeddings` now checks `id_source` right after the model check and before the dimension checks. It reads `str(meta.get("id_source") or "")`. Anything other than `ANN_ID_SOURCE` raises `RuntimeError("Index ids come from <found or '<unset>'> but readers resolve video_embeddings.ann_id. Rebuild the index with build-ann-index.py.")`. The comparison is exact equality, so the near-miss `video_embeddings.ann_ids` is refused. Because the model check runs first, a model mismatch still gets the model message, which does not name the id source.
- The module docstring gains one paragraph saying why the id source is checked (ADR-0006: a rowid-keyed index would return the wrong videos). The same gate also protects `precompute-similar-ann.py`, which calls this function.

### `engine/server/db/jobs/tests/test-orchestrator-smoke.py`
- Imports `ANN_ID_SOURCE` next to `ensure_video_embeddings_schema`.
- In `validate_outputs`, after the `meta_total` check, it raises `RuntimeError` when the sidecar's `id_source` is not `ANN_ID_SOURCE`, and records it as `checks["ann_id_source"]`.

### `tests/active/test_ann_ids.py`, `tests/config.json`
Not touched. This phase only writes production code. Moving the checkpoint into `tests/active/test_ann_ids.py` and adding it to `tests/config.json` is test-promotion work for the workflow; nothing here needed either file to turn the checkpoint green.


