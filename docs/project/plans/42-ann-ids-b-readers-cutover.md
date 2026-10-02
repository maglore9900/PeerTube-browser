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

## Impacts

_Carried from build 19's Step 3-4 inventory (line numbers as of that tree). Entries that span both plans are carried whole; the part outside this plan is for context._

<impacts>
<impact path="engine/server/data/moderation.py" element="normalize_host (dependency, no edit expected); purge_host_data / _host_table_column_pairs">
**`normalize_host`** becomes part of the id contract. Any future edit to it (port handling, IDNA, trimming) re-keys every `ann_id` and silently desynchronises the DB from the stored index and random cache. No code change is planned. Consider a comment at `normalize_host` pointing at `data/ann_ids.py`, or rely on the AC1 pinned-value test.

**`purge_host_data`** deletes `video_embeddings` rows by host. The new BEFORE INSERT trigger does not fire on DELETE, so purges are unaffected. This is the AC8 "purge one host" path. Afterwards a stale index returns misses, not wrong videos, through `fetch_metadata`'s `ann_id` lookup.

Callers:
- `updater-worker.purge_hosts` and `purge_hosts_from_staging`
- `instance-denylist-cli.py --purge-now`
- the moderation integration test

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
<impact path="scripts/run-reembed.sh" element="comment line 28; sidecar log">
The comment "api/server.py compares the index sidecar's model_name" could also mention `id_source`. Optional.

Risk: none.
</impact>
<impact path="tests/archive/random_cache_in_place/test_random_cache.py" element="archived tests using random_rowids">
Archived and not run. Leave unchanged; they reference `random_rowids` and rowids. `tests/archive/37_local_signal/test_random_videos.py` and `tests/archive/short_similarity_cache/test_similar.py` are the same.

Risk: none.
</impact>
</impacts>

### Documentation to update

- [ ] `DATA_BUILD.md`
  - **Line 13:** "random rowid cache" becomes the random ANN-id cache.
  - **Cutover:** after plan A's migration, stop the Engine, run `build-ann-index.py`, start the Engine. A stored `random-cache.db` is rebuilt automatically.
  - **Line 232:** "The index uses `video_embeddings.rowid` as ids" becomes `video_embeddings.ann_id`; mention `id_source` and the AC4 refusal message.
  - **Line 290:** "random rowid pool" changes.
  - **Line 335:** `select count(*) from random_rowids` becomes `random_ann_ids`.
- [ ] `DEPLOYMENT.md`
  - **Line 42:** the cutover (stop, build index, start), and that the Engine refuses to start on an index whose sidecar `id_source` is not `video_embeddings.ann_id`.
  - **Triage table:** a row for that startup refusal, fixed by `build-ann-index.py`, and one for the `migrate-whitelist.py` message from `build-ann-index`.
  - **Line 421:** a first start rebuilds an old-shape random cache.
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md`
  - **Line 61:** the ANN rebuild writes `id_source: video_embeddings.ann_id`.
  - **Cutover:** the index rebuild before the first updater run on the new code.
- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`
  - **Validations list (around line 115):** the sidecar `id_source` assertion.
- [ ] `engine/server/api/recommendations/docs/LAYER_PARAMS.md`
  - **Line 130:** "has no `random_rowids` table" becomes `random_ann_ids`; an old-format file counts as having no table.
  - **Line 140:** "The cache holds only rowids (`random_rowids`)" becomes ANN ids (`random_ann_ids`), resolved by `ann_id`, with the hash-uniform sampling window.
- [ ] `engine/server/api/recommendations/docs/OVERVIEW.md`
  - **Line 15:** "drops rowids already seen" / "unseen rowid" becomes ANN ids.
  - **Line 69:** "Holds a prebuilt list of rowids" becomes ANN ids (`random_ann_ids`).
- [ ] `engine/server/README.md` - the Engine refuses to start until the index is rebuilt on `ann_id`, pointing at DATA_BUILD.
- [ ] `docs/project/issues/08-stable-ann-ids.md` - at close: `Status: enhancement, complete`, moved to `docs/project/issues/archive/`.

## Changes to the carried draft for plan B

- Sections 1-7 (`ann_ids.py`, the migration and the writers) are delivered by plan A and are not carried. Read `engine/server/data/ann_ids.py` in the tree for the names this plan imports.
- **Section 13, the smoke test:** only the `validate_outputs` `id_source` assertion; the mini-prod guards are plan A's.
- **Section 14, tests:** the AC5 cases in `test_ann_ids.py`, `test_stale_ann_index.py`, and the fixture churn except `test_video.py`'s inserts (plan A). The shared helper and the AC1-AC3 and migration tests are plan A's.

## Draft implementation carried from build 19 (Step 5)

_The settled draft, sections for this plan only, numbered as in build 19. This build's Step 5 re-drafts against the tree; where the two differ, the tree wins._

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
