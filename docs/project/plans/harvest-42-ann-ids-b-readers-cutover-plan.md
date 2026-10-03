# Harvest — 42 ann ids (b): readers cutover

## Step 1 — resolved paths and scope

Resolved from `./.un/skills/devsecops/scripts/validate_tests.py --show-config`, run from the project root. `defaulted: []` and `conflicts: []`, so the bootstrap gate is clear. `map_health` reports `test_search_fusion.py` as an unmapped group; that predates this harvest and is not in scope.

| Key | Value |
|---|---|
| project_dir | `/home/enduser/code/PeerTube-browser/` |
| source (group map) | `/home/enduser/code/PeerTube-browser/tests/config.json` |
| active | `tests/active` |
| working | `tests/tmp` |
| plans | `docs/project/plans` |
| delete_me | `delete_me` |
| archive | `tests/archive` |
| record | `tests/last_test_validation.json` |

Scope is the four tests build 42 wrote. The `probe_*` and `test_probe_*` scratch files in `tests/tmp` are out of scope:

- `tests/tmp/test_42_ann_ids_b_readers_cutover_phase1.py`
- `tests/tmp/test_42_ann_ids_b_readers_cutover_phase2.py`
- `tests/tmp/test_42_ann_ids_b_readers_cutover_phase3.py`
- `tests/tmp/test_42_ann_ids_b_readers_cutover_phase4.py`

Record snapshot: `tests/last_test_validation.json` existed. Before anything else ran, it was copied to `tests/last_test_validation.json.preharvest` (129229 bytes, the same size as the original).

## Step 2 — inventory

All four files collect. `pytest --collect-only` lists 24 items from 21 test functions, and nothing fails to import, so none is marked uncollectable.

### tests/tmp/test_42_ann_ids_b_readers_cutover_phase1.py

C1 drives `engine/server/data/ann.py` (`compute_similar_items`) and `engine/server/data/search.py` (`vector_candidates`). Both run in one ENGINE_PY child against a stub server. That child also runs `embeddings.resolve_seed` (`engine/server/data/embeddings.py`) and, through both readers, `metadata.fetch_metadata` (`engine/server/data/metadata.py`). The expected keys come from `compute_ann_id` (`engine/server/data/ann_ids.py`). Only the fixture uses `sync-whitelist.py`'s schema helpers and `moderation.purge_host_data`.

C2 drives `engine/server/db/jobs/precompute-similar-ann.py` as a job subprocess.

Module-level dependencies:

- paths and imports: `ROOT`, `SERVER_DIR` (sys.path insert), `JOBS_DIR`, `ENGINE_PY`, and imports from `data.ann_ids`, `data.moderation` and `data.similarity_cache`;
- C1: `KEEP`, `PURGE`, `HOSTS`, `RANK`, `ORDER`, `KEPT_ORDER`, `NEW`, `LIMIT`, `EMBEDDING_COLUMNS`, `_CHILD`, the helpers `_vector`, `_keys`, `_scores`, `_similar_keys`, `_search_keys`, `_rowids`, `_embedding_rows` and `_insert_video`, and the module fixture `stale`;
- C2: `SIMILAR_JOB`, `DOMAIN`, `MODEL`, `DIM`, `VECTORS`, `TOP2`, `TIED_TOP2`, `SENTINEL`, `INDEX_BUILDER`, the module fixture `source`, and the helpers `_run_job` and `_read`.

Tests:

- `test_on_the_unchanged_db_both_readers_name_the_video_each_ann_id_was_built_from`
- `test_after_a_reverse_reinsert_both_readers_name_the_video_each_ann_id_was_built_from`
- `test_after_a_host_purge_both_readers_drop_its_videos_and_name_the_rest_by_ann_id`
- `test_a_new_unindexed_video_is_absent_from_both_reads_not_substituted`
- `test_precompute_lists_each_sources_neighbours_by_ann_id_and_never_the_source`, with 3 params: `full`, `incremental`, `refresh-existing`

### tests/tmp/test_42_ann_ids_b_readers_cutover_phase2.py

It drives these production files:

- `engine/server/data/random_cache.py` in-process: `populate_random_cache`, `fetch_random_ann_ids`, `open_random_cache_if_usable` and `refresh_random_cache`;
- `engine/server/data/random_videos.py` in-process: `fetch_random_rows_from_cache`, which resolves through `metadata.fetch_metadata`;
- `engine/server/db/jobs/precompute-random-rowids.py` as a job subprocess through `sys.executable`.

Only one fixture, in the cached-rows test, uses `sync-whitelist.py`'s schema helpers.

Module-level dependencies:

- paths and imports: `ROOT`, `SERVER_DIR`, `JOBS_DIR`, `PRECOMPUTE_JOB`, sys.path inserts of `SERVER_DIR` and `SERVER_DIR/api`, and imports of `data.db`, `data.random_cache`, `data.random_videos` and `compute_ann_id`;
- constants: `HOST`, `SOURCE_ROWS`, `CHANNEL_OF`, `SOURCE_IDS`, `CHANNEL_BY_ID`, `STALE_ROWID`, `READ_ALL`, `WINDOW`, `PER_AUTHOR`, `LABELS`;
- helpers: `_source_db`, `_seed_cache`, `_seed_old_cache`, `_read_only`, `_tables`, `_cache_rows`, `_populate`, `_run_job`.

Tests:

- `test_populate_over_the_whole_source_stores_and_serves_exactly_its_ann_ids`, with 2 params: `unfiltered`, `filtered`
- `test_an_unfiltered_window_starting_at_the_largest_ann_id_wraps_to_the_smallest`
- `test_a_capped_filtered_populate_draws_distinct_source_ann_ids_up_to_the_cap_per_channel`
- `test_fetch_random_ann_ids_returns_a_caches_ids_in_position_order`
- `test_cached_rows_resolve_each_cached_ann_id_to_its_video_and_drop_ids_no_row_carries`
- `test_job_writes_positions_over_exactly_the_source_ann_ids_into_random_ann_ids`
- `test_open_treats_a_cache_holding_only_random_rowids_as_having_no_table`
- `test_refresh_rebuilds_a_random_rowids_cache_into_random_ann_ids_and_serves_it`
- `test_job_rebuilds_an_out_holding_only_random_rowids_and_keeps_one_holding_random_ann_ids`

### tests/tmp/test_42_ann_ids_b_readers_cutover_phase3.py

Drives `engine/server/db/jobs/build-ann-index.py` as an ENGINE_PY job subprocess. In the job, `ANN_ID_SOURCE` and `assert_video_embeddings_has_ann_id` come from `engine/server/data/ann_ids.py`, and `resolve_embedding_space` comes from `engine/server/data/embedding_space.py`.

Module-level dependencies:

- paths and imports: `ROOT`, `SERVER_DIR` (sys.path insert), `BUILD_JOB`, `ENGINE_PY`, and imports of `data.ann_ids`, `compute_ann_id` and `ensure_video_embeddings_schema`;
- constants: `DOMAIN`, `MODEL`, `DIM`, `ROWS`, `LABELS`, `SIX_COLUMNS`, `READ_IDS`;
- helpers: `_vectors`, `_source_db`, `_run_job`.

Tests:

- `test_build_indexes_exactly_the_db_ann_ids_and_records_the_ann_id_source`
- `test_build_refuses_a_table_without_ann_id_naming_migrate_whitelist_and_writes_no_index`

### tests/tmp/test_42_ann_ids_b_readers_cutover_phase4.py

Drives `engine/server/data/embedding_space.py` (`assert_index_matches_embeddings`) in-process; the function compares the sidecar against `ANN_ID_SOURCE` from `engine/server/data/ann_ids.py`. The `built` fixture runs `build-ann-index.py` only to produce a real sidecar, and its docstring says that is setup and not asserted.

Module-level dependencies:

- paths and imports: `ROOT`, `SERVER_DIR` (sys.path insert), `BUILD_JOB`, `ENGINE_PY`, and imports of `compute_ann_id`, `ensure_video_embeddings_schema` and `assert_index_matches_embeddings`;
- constants: `DOMAIN`, `MODEL`, `DIM`, `ROWS`, `LABELS`, `INDEX` (`SimpleNamespace(d=8)`);
- helpers and fixtures: `_source_db`, the function fixture `built`, `_meta`, `_rewrite`.

Tests:

- `test_accepts_the_sidecar_build_ann_index_writes`
- `test_refuses_a_rowid_sidecar_naming_the_rowid_source_and_build_ann_index`
- `test_refuses_a_near_miss_sidecar_no_legacy_value_uses_naming_it_and_build_ann_index`
- `test_refuses_a_sidecar_without_id_source_as_unset_naming_build_ann_index`
- `test_a_model_mismatch_is_refused_by_the_model_check_before_id_source`

## Step 3 — classification

What `active` holds today, as checked:

- `tests/active/test_ann.py`, `test_build_ann_index.py` and `test_embedding_space.py` do not exist, in `active` or in `archive`.
- No active test calls `compute_similar_items`, `vector_candidates`, `resolve_seed`, `search_index`, `assert_index_matches_embeddings` or the `build-ann-index.py` job. `test_similarity_candidates.py` replaces `data.ann` with a stub. `test_updater_worker.py` names `build-ann-index.py` only as a pipeline step.
- `test_precompute_similar_ann.py` already runs the job over an `ann_id`-keyed index with an `id_source: video_embeddings.ann_id` sidecar:
  - `--incremental` against hand-computed TOP2 for v2-v8, which fails if the source is not excluded or an id resolves wrongly;
  - `--refresh-existing` with `targets <= LIVE - {key}`, ranks 1..3.
  - No test runs the job in full mode, with no flag.
- `test_precompute_random_rowids.py` asserts positions 1..20 over `SOURCE_IDS` for a fresh `--out`, which is the unfiltered populate, and keep and rename for `--reset`, `--refresh` and a short `random_ann_ids` `--out`. It has no case for an old-shape `random_rowids` `--out`.
- `test_random_cache.py`:
  - asserts filtered populate (`max_per_author=100`) over the whole source equals `SOURCE_IDS` (`test_rebuild_waits_...`, `test_build_writes_...`);
  - asserts `fetch_random_ann_ids` returns a seeded cache in position order (`_served_ann_ids == SEEDED_ROWIDS`, also in `test_db.py`);
  - asserts `open_random_cache_if_usable` returns None for a `random_rowids` file (`test_a_missing_tableless_or_empty_cache_is_not_usable[no_table]`), but not the `reason=` it logs.
  - It has no test of the capped per-author populate, of the window wrap order, or of a refresh starting from an old-shape cache.
- `test_random_videos.py`'s cache tests resolve cached `ann_id`s to their labelled videos through the real `fetch_metadata`, so a rowid-keyed lookup fails them. Every id they cache belongs to an existing row, though, so none shows that an id no row carries is dropped.

Subject files Step 5 must create:

- `tests/active/test_ann.py`, for `engine/server/data/ann.py`. The phase 1 record proposed `test_stale_ann_index.py`, but harvest names a subject file for its production script and nothing else. `ann.py` is the lowest reader both halves call: `vector_candidates` calls `ann.search_index`.
- `tests/active/test_build_ann_index.py`, for `engine/server/db/jobs/build-ann-index.py`.
- `tests/active/test_embedding_space.py`, for `engine/server/data/embedding_space.py`. The phase 3 and 4 checkpoints proposed `test_ann_ids.py`, but the function under test lives in `embedding_space.py` and the build under test in `build-ann-index.py`, so neither belongs in the `ann_ids.py` subject file.

### phase1 → `tests/active/test_ann.py` (new) and `tests/active/test_precompute_similar_ann.py` (existing)

- `test_on_the_unchanged_db_both_readers_name_the_video_each_ann_id_was_built_from` → `tests/active/test_ann.py` — **DURABLE**: no active test runs `compute_similar_items` or `vector_candidates` against a real index, so none asserts their ranked keys and scores.
- `test_after_a_reverse_reinsert_both_readers_name_the_video_each_ann_id_was_built_from` → `tests/active/test_ann.py` — **DURABLE**: the stale-index rowid shuffle is ADR-0006's core rule, and no active test asserts it.
- `test_after_a_host_purge_both_readers_drop_its_videos_and_name_the_rest_by_ann_id` → `tests/active/test_ann.py` — **DURABLE**: hits for purged rows are dropped rather than substituted; not asserted in active.
- `test_a_new_unindexed_video_is_absent_from_both_reads_not_substituted` → `tests/active/test_ann.py` — **DURABLE**: an embedded but unindexed video never appears; not asserted in active.
- `test_precompute_lists_each_sources_neighbours_by_ann_id_and_never_the_source` → `tests/active/test_precompute_similar_ann.py` — **DURABLE, `full` mode only**:
  - The `incremental` param is already asserted by `test_incremental_adds_uncached_embeddings_and_keeps_cached_sources`: the same hand-computed TOP2, over an ann_id-keyed index.
  - The `refresh-existing` param's self-exclusion and resolution are already asserted by `test_refresh_rewrites_exactly_cached_live_sources`.
  - No active test runs the full-mode source selection.
  - Moved as one unparametrized test, `test_full_mode_lists_each_sources_hand_computed_neighbours_by_ann_id_and_never_the_source`. It reuses the file's `source` fixture, `_run_job` and `_read`. It extends the file's `TOP2` with v1's row `[(2, 0.8), (8, 0.6)]`, and the incremental test then skips v1, which it holds as a sentinel. The length-skipped v9 is not asserted.

### phase2 → `tests/active/test_random_cache.py`, `test_random_videos.py`, `test_precompute_random_rowids.py` (all existing)

- `test_populate_over_the_whole_source_stores_and_serves_exactly_its_ann_ids` — **REDUNDANT**:
  - The filtered param is asserted by `test_random_cache.py`'s `test_rebuild_waits_...` and `test_build_writes_...`.
  - The unfiltered param is asserted by `test_precompute_random_rowids.py::test_job_builds_a_fresh_out_and_keeps_one_at_size`, since the job runs unfiltered without `--filtered`.
  - Both read `SOURCE_IDS`, which shares nothing with rowids 1..20.
- `test_an_unfiltered_window_starting_at_the_largest_ann_id_wraps_to_the_smallest` → `tests/active/test_random_cache.py` — **DURABLE**: the window is contiguous in `ann_id` order and wraps to the smallest ids. Active size-20 runs take the whole source whatever the start or order, so none can see it.
- `test_a_capped_filtered_populate_draws_distinct_source_ann_ids_up_to_the_cap_per_channel` → `tests/active/test_random_cache.py` — **DURABLE**: the per-author cap in the `ann_id` scan. Every active populate uses `max_per_author=100`, which never binds.
- `test_fetch_random_ann_ids_returns_a_caches_ids_in_position_order` — **REDUNDANT**:
  - Position order is asserted by `test_db.py::test_swap_failure_...` and `test_random_cache.py` (`_served_ann_ids == SEEDED_ROWIDS`).
  - The limit-0 half has no grip. Without the `limit <= 0` guard, `LIMIT 0` still returns `[]`.
- `test_cached_rows_resolve_each_cached_ann_id_to_its_video_and_drop_ids_no_row_carries` → `tests/active/test_random_videos.py` — **DURABLE**: a cached id that no row carries (a stale cache entry) is dropped and the rest keep cache order. A bare rowid that happens to name a real embedding is not substituted. Every `_cache_owner` cache holds only ids of existing rows. In Step 5 this test reuses the file's own `_video_db` and `NSFW_HOST` where they fit, rather than carrying `sync-whitelist.py`'s schema.
- `test_job_writes_positions_over_exactly_the_source_ann_ids_into_random_ann_ids` — **REDUNDANT**: `test_precompute_random_rowids.py::test_job_builds_a_fresh_out_and_keeps_one_at_size` asserts the same positions 1..20 over `SOURCE_IDS` from a fresh `--out`.
- `test_open_treats_a_cache_holding_only_random_rowids_as_having_no_table` → `tests/active/test_random_cache.py` — **COMBINE** with `test_a_missing_tableless_or_empty_cache_is_not_usable`:
  - The active test is the base: three states, a usable control, and a missing file not created.
  - The working test contributes its logged-reason assertion: `random cache unusable path=<path> reason=<state>` for `missing`, `no_table` and `empty`. That reason is what tells an old `random_rowids` file apart from an empty `random_ann_ids` one, and None alone cannot.
  - The survivor is renamed `test_a_missing_tableless_or_empty_cache_is_not_usable_and_logs_which`.
  - Its `fetch_random_ann_ids` control is already asserted by `test_a_non_empty_cache_opens_read_only_even_under_a_held_write_lock`.
- `test_refresh_rebuilds_a_random_rowids_cache_into_random_ann_ids_and_serves_it` → `tests/active/test_random_cache.py` — **DURABLE**: a refresh that starts from an old-shape cache, which is not served, swaps in a `random_ann_ids` file and serves `SOURCE_IDS`. Every active refresh starts from a `random_ann_ids` cache.
- `test_job_rebuilds_an_out_holding_only_random_rowids_and_keeps_one_holding_random_ann_ids` → `tests/active/test_precompute_random_rowids.py` — **DURABLE**: the job rebuilds an old-shape `--out` at size, at a new inode, holding only `random_ann_ids`. The active rename cases seed only `random_ann_ids`.

### phase3 → `tests/active/test_build_ann_index.py` (new)

- `test_build_indexes_exactly_the_db_ann_ids_and_records_the_ann_id_source` — **DURABLE**: the FAISS ids are the DB's `ann_id`s and the sidecar's `id_source` is `ANN_ID_SOURCE`. No active test runs the build.
- `test_build_refuses_a_table_without_ann_id_naming_migrate_whitelist_and_writes_no_index` — **DURABLE**: the build refuses before writing anything; not asserted in active.

### phase4 → `tests/active/test_embedding_space.py` (new)

- `test_accepts_the_sidecar_build_ann_index_writes` — **DURABLE**: the gate's positive half on a real sidecar. `test_precompute_similar_ann.py` passes it only through a hand-written sidecar, by way of the job.
- `test_refuses_a_rowid_sidecar_naming_the_rowid_source_and_build_ann_index` — **DURABLE**: the legacy rowid refusal and its message; not asserted in active.
- `test_refuses_a_near_miss_sidecar_no_legacy_value_uses_naming_it_and_build_ann_index` — **DURABLE**: exact equality rather than a prefix match; not asserted in active.
- `test_refuses_a_sidecar_without_id_source_as_unset_naming_build_ann_index` — **DURABLE**: a missing `id_source` is refused as `<unset>`; not asserted in active.
- `test_a_model_mismatch_is_refused_by_the_model_check_before_id_source` — **DURABLE**: check order, model first. No active test asserts the model refusal.

### Counts

21 functions, 24 items.

| Verdict | Tests |
|---|---|
| DURABLE | 17 (one of them moved with its `full` param only) |
| COMBINE | 1 |
| REDUNDANT | 3 |
| REPLACES | 0 |
| SPENT | 0 |

### Carrying notes for Step 5

Each destination gets its own copy of the constants and helpers it needs; nothing is shared across groups.

- `test_ann.py` (new): carries `_CHILD`, the C1 constants, the helpers and the `stale` fixture. Its spec name drops `test_42_phase1`. The docstring states the stale-index rule, not the build.
- `test_build_ann_index.py` (new): carries phase 3 whole. The docstring drops "this phase's own", and `ann_ids.ANN_ID_SOURCE` can now be imported by name.
- `test_embedding_space.py` (new): carries phase 4 whole, with its own `_source_db` and `built` fixture. `MODEL` is renamed away from `phase4-model`.
- `test_random_cache.py`: the wrap, cap and old-shape refresh tests bring `_seed_old_cache`, `_tables`, `_populate`, `CHANNEL_OF`/`CHANNEL_BY_ID`, `WINDOW` and `PER_AUTHOR`. They reuse the file's `_source_db` (identical labels, host and channels), `_seed_cache`, `SOURCE_IDS`, `STALE_ROWID` and `READ_ALL`. The file must import `random`, `Counter` and `logging`; `logging` is already imported.
- `test_random_videos.py`: the moved test reuses `_video_db` and `NSFW_HOST`. The rowid-1 control is kept by embedding in reverse label order.
- `test_precompute_random_rowids.py`: the moved test brings `_seed_old_cache` and `_tables`, and reuses `_source_db`, `_seed_cache`, `_cache_rows`, `_run_job`, `SOURCE_IDS` and `STALE_ROWID`.
- `test_precompute_similar_ann.py`: the full-mode test reuses `source`, `_run_job`, `_read` and `TIED_TOP2`. It extends `TOP2` with v1, and the incremental test's loop skips v1.

### Group-map changes Step 5 would make

- add `test_ann.py`: `engine/server/data/ann.py`, `engine/server/data/search.py`, `engine/server/data/embeddings.py`, `engine/server/data/metadata.py`, `engine/server/data/ann_ids.py`
- add `test_build_ann_index.py`: `engine/server/db/jobs/build-ann-index.py`, `engine/server/data/ann_ids.py`, `engine/server/data/embedding_space.py`
- add `test_embedding_space.py`: `engine/server/data/embedding_space.py`, `engine/server/data/ann_ids.py`
- unchanged: `test_random_cache.py`, `test_random_videos.py`, `test_precompute_random_rowids.py`, `test_precompute_similar_ann.py`. Each already claims every production file its moved tests drive.
- no entry dropped, because no active file is retired whole

The following are fixture inputs, so no new group claims them:

- `sync-whitelist.py`, whose schema helpers build the stale-index DB;
- `moderation.py`, whose `purge_host_data` builds case B;
- `build-ann-index.py` in `test_embedding_space.py`, where it only produces the sidecar under test. The build-to-gate pairing is held from both sides through `ann_ids.py`'s `ANN_ID_SOURCE`.

### Active tests retired

None go to `tests/archive/`. The COMBINE keeps the active test and renames it, so `--compare` will show `test_a_missing_tableless_or_empty_cache_is_not_usable[missing|no_table|empty]` departing and `test_a_missing_tableless_or_empty_cache_is_not_usable_and_logs_which[...]` appearing. That is a rename, not a loss.

## Step 4 — plan status

Approved by the operator as presented, including the three decisions: the precompute test moves with only its `full` parameter, the COMBINE survivor is renamed, and the subject file is `test_ann.py`, not `test_stale_ann_index.py`.

## Step 5 — applied

Moved:

- `test_ann.py` (new) holds phase 1's four C1 tests with `_CHILD`, the C1 constants, the helpers and the `stale` fixture. It takes `ENGINE_PY` and `ROOT` from `conftest`, its spec name is `sync_whitelist_for_test_ann`, and the `# C1` tags are replaced by per-test docstrings stating the rule.
- `test_precompute_similar_ann.py` gains `test_full_mode_lists_each_sources_hand_computed_neighbours_by_ann_id_and_never_the_source`. `TOP2` gains `1: [(2, 0.8), (8, 0.6)]`, and the incremental test's `TOP2` loop skips v1, whose sentinel it still checks. The module docstring gains a full-mode bullet.
- `test_random_cache.py` gains the wrap, cap and old-shape-refresh tests. It adds `random` and `Counter` imports, `CHANNEL_BY_ID`, `WINDOW`, `PER_AUTHOR`, `_seed_old_cache`, `_tables` and `_populate`. `_populate` builds its source with the file's own `_source_db` and calls `connect_random_cache_db`/`populate_random_cache`. The old-shape refresh reuses the file's `_refresh` (filtered, per-author 100) and `_served_ann_ids`.
- COMBINE: `test_a_missing_tableless_or_empty_cache_is_not_usable` is now `test_a_missing_tableless_or_empty_cache_is_not_usable_and_logs_which`. It takes `caplog` and asserts `random cache unusable path=<path> reason=<state>` for each state. Its `no_table` file is now `_seed_old_cache` (20 `random_rowids` rows instead of 5). The emptied working test leaves with its file to `delete_me` (Step 7). No active test was emptied, so nothing goes to `archive`.
- `test_random_videos.py` gains `test_cached_rows_resolve_each_cached_ann_id_to_its_video_and_drop_ids_no_row_carries`. It is built on `_video_db` (embedded D, C, B, A, so D holds rowid 1) and an in-memory `random_ann_ids` cache. It asserts `(video_id, instance_domain)`; `_video_db` sets no title. The module docstring gains a bullet.
- `test_precompute_random_rowids.py` gains `test_job_rebuilds_an_out_holding_only_random_rowids_and_keeps_one_holding_random_ann_ids`, with `_seed_old_cache` and `_tables`. The module docstring gains a bullet.
- `test_build_ann_index.py` (new) holds phase 3 whole. It imports `ANN_ID_SOURCE` by name, `MODEL` is `build-test-model`, and the phase wording is dropped.
- `test_embedding_space.py` (new) holds phase 4 whole, with its own `_source_db` and `built`. `MODEL` is `space-test-model`.

The group map (`tests/config.json`) is changed exactly as planned: three entries were added and none was changed or dropped. `--audit-map` exits 0. Its MISSING findings for the new groups name only stale pytest tmp artefacts (`tmp/suite28/.../similar_refresh0/index.faiss`), not production files.

## Step 6 — mutations

The Step 1 snapshot was on disk before the first run. Each mutation followed the same steps: `cp` the file to `.bak`, break it with `sed` (checked to have applied), run the one test red, restore with `cp`, then check with `diff` and `cmp` (both clean). The `.bak` was moved to `delete_me/harvest42_mutations/<file>.<tag>.bak` and the same test re-run green. The driver is `delete_me/harvest42_mutations/mutate.sh`, and the red/green output for each mutation is in `<tag>.red.out` / `<tag>.green.txt`. No `.bak` remains under `engine/`.

- m01 `ann.py`, seed exclusion disabled → `test_on_the_unchanged_db_...`: `_similar_keys(base) == _keys(ORDER[1:])` fell, v0 at index 0.
- m02 `metadata.py`, `fetch_metadata` selects and filters by `e.rowid` (the pre-cutover resolution) → `test_after_a_reverse_reinsert_...`: `_similar_keys(read) == _keys(ORDER[1:])` fell, the read came back `[]`.
- m03 `ann.py`, an unresolved hit is substituted with the first resolved video → `test_after_a_host_purge_...`: `_similar_keys(read) == _keys(KEPT_ORDER[1:])` fell, with substitutes at index 3 on.
- m04 `embeddings.py`, the seed select reads `e.rowid AS ann_id` → `test_a_new_unindexed_video_...`: `_similar_keys(read) == _keys(ORDER[1:])` fell in case C, with v0 named. The `NEW not in` lines are implied by that equality, so no separate mutation reaches them first.
- m05 `precompute-similar-ann.py`, the full-mode SELECT reads `rowid AS ann_id` → `test_full_mode_...`: the never-the-source assertion fell (v1 listed itself at score 1.0).
- m06 `random_cache.py`, the wrap query orders `DESC` → `test_an_unfiltered_window_...`: `sorted(served) == sorted([SOURCE_IDS[-1], *SOURCE_IDS[:WINDOW - 1]])` fell.
- m07 `random_cache.py`, the per-author cap check changed from `>=` to `>` → `test_a_capped_filtered_populate_...`: `built == 6` fell (9).
- m08 `random_cache.py`, `ensure_random_cache_schema` also creates the legacy `random_rowids` table → `test_refresh_rebuilds_a_random_rowids_cache_...`: `_tables(active_path) == {"random_ann_ids"}` fell.
- m09 `random_cache.py`, the unusable reason is always `empty` → `test_..._not_usable_and_logs_which[no_table]`: the logged-reason assertion fell, while `opened is None` still held.
- m10 `random_videos.py`, an unresolved cached id falls back to a rowid lookup → `test_cached_rows_resolve_...`: the row-list equality fell, with D swapped in for the bare rowid 1.
- m11 `precompute-random-rowids.py`, the keep check falls back to counting `random_rowids` → `test_job_rebuilds_an_out_holding_only_random_rowids_...`: `old.stat().st_ino != old_inode` fell (the old file was kept).
- m12 `build-ann-index.py`, the add query selects `rowid` → `test_build_indexes_exactly_the_db_ann_ids_...`: `json.loads(read.stdout) == db_ids` fell, with ids 1..64.
- m13 `build-ann-index.py`, `assert_video_embeddings_has_ann_id(conn)` disabled → `test_build_refuses_a_table_without_ann_id_...`: `"migrate-whitelist.py" in result.stderr` fell.
- m14 `embedding_space.py`, compares against `"video_embeddings.rowid"` → `test_accepts_the_sidecar_...`: `assert_index_matches_embeddings(...) is None` fell with a RuntimeError.
- m15 `embedding_space.py`, allowlists the rowid source → `test_refuses_a_rowid_sidecar_...`: `pytest.raises(RuntimeError)` fell (DID NOT RAISE).
- m16 `embedding_space.py`, a prefix match on `ANN_ID_SOURCE` → `test_refuses_a_near_miss_sidecar_...`: `pytest.raises(RuntimeError)` fell (DID NOT RAISE).
- m17 `embedding_space.py`, a missing `id_source` is let through → `test_refuses_a_sidecar_without_id_source_...`: `pytest.raises(RuntimeError)` fell (DID NOT RAISE).
- m18 `embedding_space.py`, the model check is skipped when the id source is wrong → `test_a_model_mismatch_...`: `"other-model" in str(refused.value)` fell, because the id-source message came first.

No test was reclassified REDUNDANT.

## Step 7 — disposed

All four `tests/tmp/test_42_ann_ids_b_readers_cutover_phase{1,2,3,4}.py` files are now in `delete_me/`, with no name collisions, and `tests/tmp` holds none of them. `delete_me/harvest42_mutations/` holds the 18 `.bak` copies, the driver and the run outputs.

## Step 8 — suite and bank

The snapshot was restored with `mv`, then `--compare` ran with no tier. It selected 10 of 58 groups (48 unchanged) and returned 125 passed, 1 failed.

- Appeared (20): the 17 DURABLE tests and `..._not_usable_and_logs_which[missing|no_table|empty]`.
- Gone (3): `test_a_missing_tableless_or_empty_cache_is_not_usable[missing|no_table|empty]`, the COMBINE rename.
- New red (1): `test_random_cache.py::test_engines_starting_at_once_all_become_healthy`, with `OperationalError: no such table: random_ann_ids` on the checkout's `engine/server/db/random-cache.db`.
  - Cause: that file was still the old `random_rowids` shape from before phase 2. The session `engine` fixture yields at health, but over an unusable cache the Engine's startup build runs in the background after it starts listening. The test read the file before that build renamed in a `random_ann_ids` cache (file mtime 22:15:41, during the run).
  - The harvest did not touch that file.
  - Re-run of the whole `test_random_cache.py` group afterwards: 28 passed. The checkout cache was unchanged since the rebuild.
- No longer red: none.

Final state: every group green and the record banked.
