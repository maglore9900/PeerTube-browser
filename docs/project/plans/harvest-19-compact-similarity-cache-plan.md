# Harvest — plan 19, compact similarity cache

## Step 1 — trees and scope

- `project_dir`: `/home/enduser/code/PeerTube-browser`
- `active`: `tests/active`; `working`: `tests/tmp`; `plans`: `docs/project/plans`; `delete_me`: `delete_me`; `archive`: `tests/archive`; `record`: `tests/last_test_validation.json`
- Bootstrap gate: clear (`defaulted` empty).
- Snapshot: `tests/last_test_validation.json.preharvest` taken 2026-10-01 15:59, before any harvest work.
- Scope (the plan's checkpoints): `tests/tmp/test_19_compact_similarity_cache_phase1.py`, `..._phase2.py`, `..._phase3.py`, `..._phase4.py`.
- Also disposed at Step 7, not harvested (this build's probes, no tests): `tests/tmp/db_size_probe.py`, `tests/tmp/probe_neighbour_depth.py`, `tests/tmp/probe_19_p2_neighbours.py`, `tests/tmp/probe_19_p4_legacy_counts.py`, `tests/tmp/probe_19_cutover_compare.py`, `tests/tmp/probe_19_random_cache_nsfw.py`.

## Step 2 — inventory

### tests/tmp/test_19_compact_similarity_cache_phase1.py
- Drives `engine/server/data/similarity_cache.py` (in-process) and `engine/server/db/jobs/migrate-similarity-cache.py` (subprocess under `ENGINE_PY`).
- Tests: `test_stored_entries_read_back_in_rank_order_from_a_two_table_file`, `test_migration_serves_every_legacy_source_its_legacy_neighbours_and_refuses_an_existing_output`.
- Depends on: `LEGACY_DDL`, `_entry`, `_tables`, `_fetch`, `_legacy_cache`, `_migrate`, `A`, `B`.

### tests/tmp/test_19_compact_similarity_cache_phase2.py
- Drives `engine/server/db/jobs/precompute-similar-ann.py` (subprocess), read through `data.similarity_cache`.
- Tests: `test_refresh_existing_recomputes_cached_embedded_sources_and_keeps_the_rest`, `test_incremental_adds_uncached_embeddings_and_keeps_cached_sources`.
- Depends on: module `source` fixture (same `VECTORS`, `SHORT_ROWID`, `DOMAIN`, `MODEL` and index builder as `tests/active/test_precompute_similar_ann.py`), `_run_job` (`--cpu --top-k 2`), `_seed`, `_read`, `_expected`, `TOP2`, `TIED_TOP2`, `SENTINEL`.

### tests/tmp/test_19_compact_similarity_cache_phase3.py
- Drives `engine/server/data/similarity_cache.py` (in-process) and `precompute-similar-ann.py` (subprocess).
- Tests: `test_ensure_schema_refuses_a_legacy_file_naming_it_and_the_migration_job`, `test_precompute_refuses_a_legacy_out_naming_the_migration_job`.
- Depends on: `LEGACY_DDL`, `_legacy_cache`, `_schema`; imports `source` and `_run_job` from the phase 2 file.

### tests/tmp/test_19_compact_similarity_cache_phase4.py
- Drives `engine/server/data/moderation.py` and `engine/server/data/videos.py` (in-process).
- Tests: `test_purge_removes_a_host_as_source_and_as_neighbour_with_legacy_counts`, `test_ensure_video_indexes_drops_the_two_duplicate_indexes_and_keeps_the_uuid_index`.
- Depends on: `_e`, `_cache`, `_read`, `_source_keys`, `_video_db`, `_indexes`, `A`, `BAD`.

All four files collect and pass (Step 8 of the build).

## Step 3 — classification

### phase1 `test_stored_entries_read_back_in_rank_order_from_a_two_table_file` — DURABLE
No `active` test asserts the compact round trip (rank renumbering, `limit` cut after ordering, the two-table file). Subject `tests/active/test_similarity_cache.py` does not exist: Step 5 creates it.

### phase1 `test_migration_serves_every_legacy_source_its_legacy_neighbours_and_refuses_an_existing_output` — DURABLE
Nothing in `active` drives `migrate-similarity-cache.py`. Subject `tests/active/test_migrate_similarity_cache.py` does not exist: Step 5 creates it.

### phase2 `test_refresh_existing_recomputes_cached_embedded_sources_and_keeps_the_rest` — REDUNDANT
`tests/active/test_precompute_similar_ann.py::test_refresh_rewrites_exactly_cached_live_sources`, now seeding a compact cache, already asserts that exactly the cached embedded sources are rewritten with fresh ranked items on live keys and every other source keeps its rows; a selection not going through `video_keys` fails it the same way.

### phase2 `test_incremental_adds_uncached_embeddings_and_keeps_cached_sources` — DURABLE
No `active` test runs `--incremental`. Destination `tests/active/test_precompute_similar_ann.py`, reusing its `source` fixture (identical data) and `_run_job`.

### phase3 `test_ensure_schema_refuses_a_legacy_file_naming_it_and_the_migration_job` — DURABLE
No `active` test covers the legacy refusal. Destination `tests/active/test_similarity_cache.py` (created for phase1's first test).

### phase3 `test_precompute_refuses_a_legacy_out_naming_the_migration_job` — DURABLE
Destination `tests/active/test_precompute_similar_ann.py`, reusing its `source` fixture.

### phase4 `test_purge_removes_a_host_as_source_and_as_neighbour_with_legacy_counts` — DURABLE
No `active` test drives `purge_similarity_for_host` on a cache (`test_updater_worker.py`'s reprune test calls it only as the fake Engine-side actor, and `test_host_normalisation.py` covers host parsing). Subject `tests/active/test_moderation.py` does not exist: Step 5 creates it.

### phase4 `test_ensure_video_indexes_drops_the_two_duplicate_indexes_and_keeps_the_uuid_index` — DURABLE
No `active` test covers `ensure_video_indexes`. Subject `tests/active/test_videos.py` does not exist: Step 5 creates it.

## Step 4 — plan (approved by the operator, "approve")

- Counts: 7 DURABLE, 1 REDUNDANT, 0 REPLACES, 0 COMBINE, 0 SPENT. No `active` test retired.
- New subject files (each a new group and map entry):
  - `tests/active/test_similarity_cache.py` ← phase1 round trip, phase3 ensure refusal. Map: `engine/server/data/similarity_cache.py`.
  - `tests/active/test_migrate_similarity_cache.py` ← phase1 migration. Map: `engine/server/db/jobs/migrate-similarity-cache.py`, `engine/server/data/similarity_cache.py`.
  - `tests/active/test_moderation.py` ← phase4 purge. Map: `engine/server/data/moderation.py`, `engine/server/data/similarity_cache.py`.
  - `tests/active/test_videos.py` ← phase4 indexes. Map: `engine/server/data/videos.py`.
- Into existing `tests/active/test_precompute_similar_ann.py` ← phase2 incremental, phase3 precompute refusal. Map entry gains `engine/server/data/similarity_cache.py`.
- Map changes for the fixture edits already made: `test_updater_worker.py` already lists `similarity_cache.py` and `moderation.py`; `test_similar.py` gains nothing (it reads the cache through `data.similarity_cache` only to snapshot an entry, a fixture use).

## Step 5 — applied

- Created `tests/active/test_similarity_cache.py` (round trip; `ensure_similarity_schema` legacy refusal), `tests/active/test_migrate_similarity_cache.py` (migration), `tests/active/test_moderation.py` (purge), `tests/active/test_videos.py` (duplicate indexes). Docstrings state the rule each gates; phase names and clause marks removed.
- Added to `tests/active/test_precompute_similar_ann.py`: `test_incremental_adds_uncached_embeddings_and_keeps_cached_sources` and `test_refresh_refuses_a_legacy_out_naming_the_migration_job`, reusing its `source` fixture, `_run_job` and `_reset_cache`; module docstring gains two bullets.
- No `active` test retired; nothing under `tests/archive/`.
- `test_groups`: new entries for the four files; `test_precompute_similar_ann.py` gains `engine/server/data/similarity_cache.py`. `--audit-map` exit 0. Its advisories on the new files are mentions, not dependencies: `test_similarity_cache.py` and `test_precompute_similar_ann.py` name `migrate-similarity-cache.py` only as the text a refusal must contain, and `similarity-cache.db` only as a default path; `test_moderation.py` and `test_videos.py` are BARREN by path text because they import their subjects.
- New files run: 18 passed across the five files.

## Step 6 — mutations (each restored with `cp` from a `.bak`, `diff` clean, `touch`ed, re-run green; every `.bak` moved to `delete_me/`)

- `test_stored_entries_read_back_in_rank_order_from_a_two_table_file` — rule: neighbours are packed in rank order. Mutation: `write_similarities` packs items in list order (`ranked = list(items)`). Felled `test_similarity_cache.py:67`: index 0 `n2` where `n1` expected. Restored; green.
- `test_ensure_schema_refuses_a_legacy_file_naming_it_and_the_migration_job` — rule: a legacy file is refused. Mutation: the guard in `ensure_similarity_schema` disabled (`if False:`). Felled `test_similarity_cache.py:105`: `DID NOT RAISE RuntimeError`.
- `test_refresh_refuses_a_legacy_out_naming_the_migration_job` — same rule, through the job; same mutation. Felled `test_precompute_similar_ann.py:287`: stderr ends `no such column: s.source_key` without the job name. Restored; both green.
- `test_migration_serves_every_legacy_source_its_legacy_neighbours_and_refuses_an_existing_output` — rule: each neighbour keeps its own identity through the conversion. Mutation: `convert` gives each neighbour its source's host. Felled `test_migrate_similarity_cache.py:81`: `n2` on a.example where b.example expected. Restored; green.
- `test_incremental_adds_uncached_embeddings_and_keeps_cached_sources` — rule: incremental selects only uncached sources. Mutation: `WHERE s.source_key IS NULL` → `WHERE 1`. Felled `test_precompute_similar_ann.py:259`: cached v1 recomputed to v2, v8 instead of the sentinel. Restored; green.
- `test_purge_removes_a_host_as_source_and_as_neighbour_with_legacy_counts` — rule: the host leaves other sources' neighbours. Mutation: the blob rewrite and the `video_keys` delete removed (sources-only purge). Felled `test_moderation.py:62`: s1 still holds x1 from bad.example. Restored; green.
- `test_ensure_video_indexes_drops_the_two_duplicate_indexes_and_keeps_the_uuid_index` — rule: the embeddings duplicate is dropped. Mutation: its `DROP INDEX` replaced by `SELECT 1`. Felled `test_videos.py` on `old.db`: extra `idx_video_embeddings_id_instance`. Restored; green.
- No mutation felled nothing. No `.bak` under the production tree. The snapshot survived to Step 8.

## Step 7 — disposed to `delete_me/` (no name collided)

`test_19_compact_similarity_cache_phase1.py` .. `_phase4.py`, `db_size_probe.py`, `probe_neighbour_depth.py`, `probe_19_p2_neighbours.py`, `probe_19_p4_legacy_counts.py`, `probe_19_cutover_compare.py`, `probe_19_random_cache_nsfw.py`, `audit_map_19.txt`. Mutation copies: `similarity_cache.py.bak-h19-m1`, `migrate-similarity-cache.py.bak-h19-m3`, `precompute-similar-ann.py.bak-h19-m4`, `moderation.py.bak-h19-m5`, `videos.py.bak-h19-m6`.

## Step 8 — suite

Snapshot restored, then `validate_tests.py --compare`: exit 0; 46 groups, 6 run (4 new, `test_precompute_similar_ann.py` changed, `test_search_fusion.py` unmapped), 28 passed; 40 answered green by the record. Moved against the pre-harvest record: 7 appeared (exactly the seven harvested tests), 0 gone, 0 new red, 0 no longer red.
