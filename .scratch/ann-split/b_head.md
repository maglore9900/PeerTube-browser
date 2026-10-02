# Stable ANN ids, plan B: readers, index and the cutover

## Requirements

### Asked for

Issue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2), second of two builds. Plan 17 (`docs/project/plans/17-stable-ann-ids.md`) was taken through build 19 as far as its Step 6, then split into `docs/project/plans/41-ann-ids-a-schema-writers.md` (A) and this plan (B). ADR-0006 (`docs/project/adr/0006-derived-ann-ids.md`) records the id decision, and `CONTEXT.md` defines **ANN id**.

Plan B moves the FAISS index and every reader that turns an id back into an embedded video from `video_embeddings.rowid` to the `ann_id` plan A stores, and makes the Engine refuse a rowid index. This plan is the cutover: its readers, its index build and its gate merge together.

**Prerequisite.** Plan A is merged, and the shared dataset has been migrated with `migrate-whitelist.py`. This plan imports `data/ann_ids.py` (`compute_ann_id`, `ANN_ID_SOURCE`, `ensure_video_embeddings_schema`, `assert_video_embeddings_has_ann_id`) as plan A delivers it. Re-check that module's names against the tree at Step 1; if plan A changed them, the tree wins.

Everything below was settled with the operator in build 19 (Steps 1-5, record `docs/project/plans/19-17-stable-ann-ids.record.md`, now in `delete_me/`), narrowed to plan B.

### Purpose

Correctness. `video_embeddings` can change while no index rebuild follows, or while the rebuild fails: a merge, a host purge, a whole-table reload, a `--force` re-embed, a migration. In every such case the index must never return the wrong video. At most it misses videos it has not indexed yet. The build must not block later incremental index add or remove (F3/F4-M2), and it does not build them.

### Current state (checked against the tree in build 19, read-only; re-check after plan A)

- `engine/server/db/jobs/build-ann-index.py:250-256` calls `add_with_ids` with `video_embeddings.rowid` and writes `id_source: "video_embeddings.rowid"` (line 284). The live sidecar says the same.
- Rowid-keyed readers:
  - `engine/server/data/ann.py`: `compute_similar_items` and its `ids > 0` filter; `search_index` (`exclude_rowid`); `search_similar_above`, the up-next fallback search, which keeps rowid hits through the same filter, excludes `seed["rowid"]` and calls `fetch_metadata` by rowid. The nprobe helpers in this file, and `precompute-similar-ann.py`'s own `set_nprobe`, do not change.
  - `engine/server/data/embeddings.py`: the seed's `rowid`/`exclude_rowid` in `resolve_seed` and in the three seed queries.
  - `engine/server/data/metadata.py`: `fetch_metadata`, `WHERE e.rowid IN (...)`.
  - `engine/server/data/search.py`: `vector_candidates`.
  - `engine/server/api/handlers/similar.py`: `_handle_vector_search`.
  - `engine/server/data/random_cache.py` and `random_videos.py`: the `random_rowids` table.
  - `engine/server/db/jobs/precompute-random-rowids.py`.
  - `engine/server/db/jobs/precompute-similar-ann.py`: `iter_embedding_rows_by_rowids`, `fetch_similarity_targets*` and the main loop.
  - The rowid uses in `data/users.py` and `data/interaction_events.py` concern other tables and do not change.
- Random cache:
  - The Engine opens `random-cache.db` read-only at start through `open_random_cache_if_usable` (`random_cache.py:283-302`), which accepts any non-empty `random_rowids` table without checking its shape.
  - `server.py:345` sets `random_cache_startup_build = random_cache_refresh or random_cache_db is None`, so a cache judged unusable always gets a background build.
  - Every build runs through `build_random_cache` (`random_cache.py:208-245`) into a per-pid temp file, swapped in through `swap_readonly_connection(..., RANDOM_CACHE_CHECK_SQL)`.
  - With refresh off (`--dev`), a stored non-empty cache is served as it is.
  - `precompute-random-rowids.py` keeps an `--out` that already holds `--size` rows, counted through `random_rowids_count` without checking their shape.
- Already on logical keys: the similarity cache (`similarity_items`, keyed by `(video_id, instance_domain)`), and `videos_fts`'s `videos.rowid` link, which is not an ANN id.
- The Engine checks the sidecar at start in `data/embedding_space.assert_index_matches_embeddings`, which checks the model and the dimension.
- The updater (`updater-worker.py:1040-1150`) stops the service, merges, rebuilds the ANN, precomputes, and restarts in a `finally`, so a failed ANN build restarts the Engine on the old index.

### Acceptance criteria

- **AC4, the index build:** `build-ann-index.py` adds vectors with `ann_id` as their ids and writes `id_source: "video_embeddings.ann_id"` to the sidecar. When the column is missing, it fails with a message naming `migrate-whitelist.py`.
- **AC5, the Engine gate:** the Engine refuses to start when the index sidecar's `id_source` is not `video_embeddings.ann_id`, in `assert_index_matches_embeddings`, the same way it refuses a model mismatch, with a message naming `build-ann-index.py`.
- **AC6, the readers:** these resolve embedded videos by `ann_id`:
  - similar: the seed and its exclusion (`ann_id`/`exclude_ann_id` in `embeddings.py`), the ANN results (`ann.py`, including `search_similar_above` and the `ids > 0` filter), and raw vector search (`similar._handle_vector_search`);
  - search's vector half (`search.vector_candidates`);
  - `fetch_metadata`, as `WHERE e.ann_id IN (...)`, served by the UNIQUE index;
  - the random cache (`random_cache.py`, `random_videos.py`, `precompute-random-rowids.py`).

  A stored random cache in the old `random_rowids` shape is detected and repopulated, never read. Afterwards, no reader resolves an embedded video by rowid.
- **AC7, the similarity precompute:** `precompute-similar-ann.py` uses `ann_id` for its FAISS ids and its target lookup. Its output keys and its incremental selection stay on `(video_id, instance_domain)`.
- **AC8, the purpose observed in a test:** build an index, then, with no index rebuild, either renumber the DB's rows (delete and reinsert every row) or purge a host. Similar and search then return only videos whose identity matches the vector indexed for them. Unindexed or purged videos may be missing, but no result is a different video.
- **AC9, the cycle and docs (plan B's part):** the updater's full cycle (merge, ANN build, precompute) runs on the new id source, observed through the orchestrator smoke test's `id_source` assertion. The docs carry the cutover (stop the Engine, `build-ann-index.py`, start), the startup refusal, and the random cache's `random_ann_ids` shape.

### Scope

In scope: AC4-AC8 and plan B's part of AC9. The issue closes with this plan.

Out of scope: everything plan A delivered (the id, the schema, the migration, the writers); incremental FAISS add or remove (F3/F4-M2); the similarity cache; `videos_fts`; backward compatibility with rowid indexes (a `rowid` sidecar is refused, not read); the crawler.

### Consistency constraints

- Job CLIs keep their current arguments; `precompute-random-rowids.py` keeps its file name.
- Refusal messages follow `data/embedding_space.py`: say what is wrong, and name the command that fixes it.
- New code matches the style of the file it lands in; every id comes from plan A's helper.

### Conflicts

- **One merge, not three.** Readers on `ann_id` against a rowid index, or an `ann_id` index against rowid readers, both return wrong videos. Phases 1-3 below therefore land in one build and one merge; no phase is merged alone.

### Tests

- Active tests in `tests/active`, scratch in `tests/tmp`, job tests in `engine/server/db/jobs/tests/`. Baseline re-taken at Step 0.
- Fixture churn: `test_metadata`, `test_random_videos`, `test_random_cache`, `test_db`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_video` (`similars_stack` only). `test_internal_client_reads`, `test_search`, `test_similarity_candidates` and `test_videos` need no change. `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles` and `test_frontend_reactions` are SELECT-only and need no code change.
- New tests cover AC4/AC5 (the index's ids, the sidecar and the refusal), AC6 (the old-shape random cache rejected and rebuilt), AC7, and AC8 (the stale index after a renumber and after a host purge).
- **Engine-backed tests need the shared dataset's index rebuilt.** The session `engine` fixture starts the real Engine on the shared `whitelist.db` and index. Once this plan's gate lands, it exits at start until `build-ann-index.py` has run on that (already migrated) dataset. The operator does that before the final full-suite run.

### Risks and limitations accepted

- Hard cutover: the Engine refuses a `rowid` sidecar, so the deploy is stop, `build-ann-index.py`, start. The similarity cache needs no rebuild; the random cache rebuilds itself.
- Purged or deleted videos stay in the index until the next rebuild, as misses (no metadata row), never as wrong videos.
- A re-embedded video keeps its old vector in the index until the next rebuild, but still resolves to the right video.
- New videos stay out of the index until a rebuild.
- The unfiltered random draw becomes a hash-uniform sample rather than a block of rows in insertion order.

## High-level plan

### Approach

**AC4, the index build.** `build-ann-index.py` checks the table's shape with plan A's `assert_video_embeddings_has_ann_id`, selects `ann_id` in place of `rowid` for `add_with_ids`, and writes `id_source: ANN_ID_SOURCE`. The training sample keeps `rowid % step`: a sampling cursor, never an identity.

**AC5, the gate.** `assert_index_matches_embeddings` gains an `id_source` check next to the model check, naming `build-ann-index.py`. It also guards `precompute-similar-ann.py`, which is correct: a precompute against a rowid index would map hits to the wrong videos.

**AC6, the readers.** The rowid names become `ann_id`: the seed's `rowid`/`exclude_rowid` and its queries in `embeddings.py`; the filters and exclusions in `ann.py`, including `search_similar_above` (the `> 0` filter stays valid: real ids are at least 1 and FAISS fills empty slots with -1); `similar._handle_vector_search`; `search.vector_candidates`; `fetch_metadata`, through the UNIQUE index. `search.py`'s own `v.rowid` is the `videos_fts` link and does not change.

**AC6, the random cache.** The table becomes `random_ann_ids (position, ann_id)`. Because the name is new, the existing "no table" path does the old-shape detection with no new code: against an old file the renamed count helper returns None, so `open_random_cache_if_usable` returns None and the Engine starts a background build; the precompute job's keep check counts 0 and rebuilds; `RANDOM_CACHE_CHECK_SQL` names the new table, so a swap can only install a new-shape file. The build samples a random start between min and max `ann_id`, then the next rows in `ann_id` order, wrapping around. Hashed ids are uniform, so this window is a uniform sample.

**AC7.** In `precompute-similar-ann.py`, the row iterator, `fetch_similarity_targets*`, the pending-selection query and the main loop move to `ann_id`; self-exclusion becomes `ann_id == row["ann_id"]`.

**AC8.** A test builds a small index on `ann_id`, then, without rebuilding it, renumbers every row, purges a host, and adds an unindexed video, and asserts every similar and search hit resolves to the video whose vector carries that id, or is dropped. It holds by construction: the id is a function of identity.

**AC9.** The smoke test asserts the sidecar's `id_source`. `DATA_BUILD.md`, `DEPLOYMENT.md`, `UPDATER_WORKER.md`, `ORCHESTRATOR_SMOKE_TEST.md`, `LAYER_PARAMS.md`, `OVERVIEW.md` and `engine/server/README.md` get the cutover and the new cache shape.

### Alternatives considered

- **Keeping the `random_rowids` name and checking the column shape:** rejected; the new name makes the existing "no table" path do the detection.
- **Random-cache sampling by a rowid window while storing `ann_id`:** keeps a rowid read in the reader; the `ann_id` range is indexed and spreads better.
- **Splitting the readers and the gate across merges:** every intermediate state returns wrong videos (see Conflicts).
- **Backward compatibility with rowid indexes:** out of scope; refused.

### Risks and gotchas

- **Partial seed-key rename** silently stops self-exclusion (`seed.get("rowid")` in `search_similar_above`) or raises KeyError (`seed["rowid"]` in `compute_similar_items`). Rename every consumer together, including the recommendation sources that feed `fetch_seed_embeddings_for_likes` seeds through.
- **A missed `rowid` in `build-ann-index.py`** produces an index the gate accepts by its sidecar but with wrong ids. Phase 3's checkpoint compares the stored id set to the DB's `ann_id` set.
- **JSON precision.** Ids up to 2^63 exceed JavaScript's safe range. `fetch_metadata`'s output, the similar and search handlers and the random feed never put the id into a response; if one ever does, it must be a string.
- **Random-cache test churn.** Tests asserting row order or rowid windows need new expectations.
- **Test sidecars without `id_source`** (`test_precompute_similar_ann.py`) are refused once the gate lands; phase 1 updates that fixture before phase 3 adds the gate.

### Tradeoffs the operator accepts

- Hard cutover with a refused rowid index.
- The random cache is detected by its table name, not its shape. A future reshape under the same name would need a column check in `random_ann_ids_count`.
- ANN training samples by `rowid % step`, which affects only which vectors train the quantizer.

### Phases proposed in build 19 (Step 6), for this build's Step 6 to re-derive

Build 19's phases 4-6, renumbered. Three phases. Readers come before the gate so that no earlier phase's checkpoint goes red when a later one lands; the build merges once, after phase 3.

#### Phase 1 - Readers and similarity precompute on ann_id

- **Intent:** The Engine's similar, search and metadata reads and `precompute-similar-ann.py` resolve every ANN hit through `video_embeddings.ann_id`, so a stale index yields the video it indexed or nothing.
- **C1:** After the table is renumbered and after a host purge, with no index rebuild, every hit from `compute_similar_items` and from `vector_candidates` resolves to the video whose vector carries that id, or is dropped.
- **C2:** `precompute-similar-ann.py` resolves each neighbour by `ann_id` and never lists a video as its own neighbour.
- **Checkpoint and seam:** C1: an ENGINE_PY child (the `_CHILD` precedent in `test_search.py` and `test_popular_videos.py`) in the new `tests/active/test_stale_ann_index.py`. It builds a tmp DB through `ensure_video_embeddings_schema` and an `IDMap2,IVF1,Flat` index on `ann_id`, records `ann_id -> (video_id, host)`, then calls `ann.compute_similar_items` and `search.vector_candidates` through a stub server after each case: A, every row deleted and reinserted in reverse order; B, `purge_host_data` on one host; C, a new unindexed video inserted. Per case, every returned `(video_id, instance_domain)` equals the identity recorded for the id that produced it, which excludes a rowid join (case A would substitute); in case B none of the purged host's videos is returned; in case C the new video is absent. Each case is asserted for both readers. C2: the existing `tests/active/test_precompute_similar_ann.py` job harness (`INDEX_BUILDER` moved to `SELECT ann_id, embedding`, sidecar gains `id_source`). Every source's neighbour keys map to the videos whose vectors carry the hit ids, which excludes a rowid-keyed target lookup; no source lists itself.
- **Files:** `engine/server/data/embeddings.py`, `ann.py`, `metadata.py`, `search.py`, `engine/server/api/handlers/similar.py`, `engine/server/db/jobs/precompute-similar-ann.py`, `tests/active/test_stale_ann_index.py` (NEW), `tests/active/test_precompute_similar_ann.py`, `tests/active/test_metadata.py`, `tests/active/test_video.py` (`similars_stack`), `tests/config.json`.

#### Phase 2 - Random cache on ann_id

- **Intent:** The random-feed cache stores ANN ids in a `random_ann_ids` table, so a cache file in the old `random_rowids` format is never read as current and is rebuilt.
- **C1:** `precompute-random-rowids.py` writes a `random_ann_ids` table whose every id is a `video_embeddings.ann_id` of the source.
- **C2:** An output file that holds an old `random_rowids` table is rebuilt into `random_ann_ids` rather than kept.
- **Checkpoint and seam:** `precompute-random-rowids.py` run as a subprocess against a tmp source DB that has `ann_id`, using the existing `tests/active/test_precompute_random_rowids.py` harness. C1: the `--out` file holds a `random_ann_ids` table and no `random_rowids` table; every cached id is in the source's `ann_id` set and the count equals `--size`, which excludes storing rowids. C2: an `--out` already holding an old `random_rowids` table with `--size` rows is rebuilt; afterwards `random_ann_ids` exists with ids from the source set. Engine-side `open_random_cache_if_usable` returning None on an old file goes through the same count helper and is covered by `test_random_cache.py`'s churned "no table" probe.
- **Files:** `engine/server/data/random_cache.py`, `random_videos.py`, `engine/server/db/jobs/precompute-random-rowids.py`, `engine/server/api/server_config.py`, `tests/active/test_random_cache.py`, `test_random_videos.py`, `test_db.py`, `test_precompute_random_rowids.py`, `tests/config.json`.

#### Phase 3 - Index build and Engine gate

- **Intent:** `build-ann-index.py` builds indexes keyed by `video_embeddings.ann_id`, and the Engine and the similarity precompute refuse any index whose sidecar does not declare that id source.
- **C1:** The index `build-ann-index.py` writes holds exactly the `ann_id` values of the embedded rows as its ids.
- **C2:** `assert_index_matches_embeddings` refuses a sidecar whose `id_source` is not `video_embeddings.ann_id`, with a message naming `build-ann-index.py`.
- **Checkpoint and seam:** `build-ann-index.py` run as a job subprocess under ENGINE_PY (the precedent in `test_migrate_similarity_cache.py` and `test_precompute_similar_ann.py`) on a tmp DB built through `ensure_video_embeddings_schema`, then an ENGINE_PY child that loads the written index, in `tests/active/test_ann_ids.py`. C1: the index's stored id set (`faiss.vector_to_array(index.id_map)`) equals the DB's `ann_id` set exactly, which excludes rowid ids and dropped rows. C2: `assert_index_matches_embeddings` with the index and the sidecar the build actually wrote passes; the same sidecar with `id_source: video_embeddings.rowid` raises a message naming `build-ann-index.py`; a sidecar with no `id_source` raises.
- **Files:** `engine/server/db/jobs/build-ann-index.py`, `engine/server/data/embedding_space.py`, `engine/server/db/jobs/tests/test-orchestrator-smoke.py` (`id_source` assertion), `tests/active/test_ann_ids.py`, `tests/config.json`.

### Coordination the operator does

- Before the final full-suite run: with the Engine stopped, run `build-ann-index.py` on the shared (already migrated) dataset, then start the Engine.
- The smoke test's `id_source` assertion needs a migrated `--source-db`; the operator runs it manually.

