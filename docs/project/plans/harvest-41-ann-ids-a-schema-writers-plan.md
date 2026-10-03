# Harvest — 41 ann ids (a): schema and writers

## Step 1 — resolved paths and scope

Resolved from `./.un/skills/devsecops/scripts/validate_tests.py --show-config` (`defaulted: []`, so the bootstrap gate is clear; `conflicts: []`).

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

Scope (the tests build 41 wrote; the build-42 files, `test_probe_*` files and `probe_*` scratch files in `tests/tmp` are out of scope):

- `tests/tmp/test_41_ann_ids_a_schema_writers_phase1.py`
- `tests/tmp/test_41_ann_ids_a_schema_writers_phase2.py`
- `tests/tmp/test_41_ann_ids_a_schema_writers_phase3.py`
- `tests/tmp/test_41_ann_ids_a_schema_writers_phase4.py`

Record snapshot: `tests/last_test_validation.json` existed and was copied to `tests/last_test_validation.json.preharvest` (123306 bytes, same as the original) before anything else ran.

## Step 2 — inventory

All four files collect: `pytest --collect-only` lists 35 test items from 30 test functions, and nothing fails to import. None is marked uncollectable.

### tests/tmp/test_41_ann_ids_a_schema_writers_phase1.py

Drives `engine/server/data/ann_ids.py` in-process: `compute_ann_id`, `create_video_embeddings_table` and `create_ann_id_guards`. `normalize_host` from `engine/server/data/moderation.py` is part of the id contract it pins.

Module-level dependencies: the `SERVER_DIR` sys.path insert, `HOST`, `PINNED_ABC_ID`, `HOLDER_ID`, `COLUMNS`, the helpers `_ann_ids`, `_write`, `_rows` and `_guard`, and the `db` fixture (a tmp DB with a minimal `videos` table).

Tests: `test_pinned_id`, `test_host_spelling_gives_the_pinned_id` (3 params), `test_ids_are_distinct_positive_63_bit_values`, `test_unparsable_domain_falls_back_to_trimmed_lowercased_text` (3 params), `test_zero_ann_id_is_refused`, `test_insert_of_another_keys_id_is_refused`, `test_insert_or_replace_of_another_keys_id_is_refused_and_keeps_the_holder`, `test_same_key_replace_keeps_its_id`, `test_update_to_another_keys_id_is_refused`.

### tests/tmp/test_41_ann_ids_a_schema_writers_phase2.py

Drives `engine/server/db/jobs/whitelist_migrations.py` (`migrate_whitelist_schema`, `migrate_video_embeddings_schema`). It uses `sync-whitelist.py`'s schema helpers only to build the fixture.

Module-level dependencies: `ROOT`, `JOBS_DIR`, `OLD_VIDEO_EMBEDDINGS_SQL`, `OLD_COLUMNS`, `SEED`, `EXPECTED_ANN_IDS`, `COLLIDING_ROW`, `ROWS_SQL`, `MASTER_SQL`, `REBUILD_NAMES_SQL`, `EXPECTED_GUARDS`, the helpers `_load_job`, `_migrations`, `_table_info`, `_column_names` and `_content_db`, and the `old_db` fixture.

Tests: `test_migration_backfills_derived_ann_ids_keeping_rowids_and_guards`, `test_missing_video_embeddings_is_left_alone`, `test_failed_backfill_rolls_back_to_the_six_column_table`.

### tests/tmp/test_41_ann_ids_a_schema_writers_phase3.py

Drives three production scripts:

- `engine/server/db/jobs/sync-whitelist.py`: `ensure_content_schema`, `ensure_schema_compatibility` and `rebuild_content_tables`, loaded in-process.
- `engine/server/db/jobs/merge-staging-db.py`: run as a CLI subprocess.
- `engine/server/db/jobs/updater-worker.py`: `inject_replace_embedding_for_test`, loaded in-process.

Module-level dependencies: `ROOT`, `JOBS_DIR`, `CRAWL_SCHEMA`, `MERGE_JOB`, `OLD_VIDEO_EMBEDDINGS_SQL`, `SOURCE_ANN_ID_EMBEDDINGS_SQL`, `OLD_COLUMNS`, `V1_ID`, `V2_ID`, `V3_ID`, `V3_SENTINEL`, `V1_SENTINEL`, `HOSTS`, `CHANNELS`, `VIDEOS`, `EMBEDDINGS`, `COLUMNS`, `ROWS_SQL`, the helpers `_load_job`, `_column_names`, `_target`, `_source`, `_attach_source` and `_seed`, and the module fixtures `sync_job` and `updater`.

Tests: `test_new_target_carries_ann_id_and_passes_the_exact_check`, `test_six_column_target_is_refused_naming_ann_id_and_the_migration`, `test_reload_from_a_source_without_ann_id_stores_the_derived_id`, `test_reload_from_a_source_with_ann_id_stores_the_sources_value`, `test_merge_leaves_prod_rows_carrying_the_derived_id`, `test_inject_writes_the_derived_id` (2 params).

### tests/tmp/test_41_ann_ids_a_schema_writers_phase4.py

Drives four production scripts:

- `engine/server/data/ann_ids.py`: `ensure_video_embeddings_schema` and `assert_video_embeddings_has_ann_id`.
- `engine/server/db/jobs/build-video-embeddings.py`: `init_schema`, loaded in-process.
- `engine/server/db/jobs/merge-staging-db.py`: run as a CLI subprocess.
- `engine/server/db/jobs/sync-whitelist.py`: `main()`, in-process with `fetch_hosts` and `sys.argv` monkeypatched.

Module-level dependencies: `ROOT`, `SERVER_DIR` (sys.path insert), `JOBS_DIR`, `CRAWL_SCHEMA`, `MERGE_JOB`, `OLD_VIDEO_EMBEDDINGS_SQL`, `SOURCE_ANN_ID_EMBEDDINGS_SQL`, `OLD_COLUMNS`, `HOST`, `STAGE_ONLY_HOST`, `V1_ID`, `V2_ID`, `PROD_V1`, `STAGE_V1`, `STAGE_V2`, `FTS_TRIGGERS`, `COLLISION_MESSAGE`, the helpers `_ann_ids`, `_load_job`, `_whitelist_db`, `_seed`, `_state`, `_merge`, `_master`, `_old_table_with_a_row`, `_collision_pair`, `_crawl_source` and `_run_sync`, and the module fixtures `sync_job` and `build_job`.

Tests: `test_ensure_schema_refuses_a_six_column_table_with_the_migrate_pointer_and_writes_nothing`, `test_ensure_schema_creates_and_then_accepts_the_ann_id_table`, `test_has_ann_id_check_does_nothing_without_the_table`, `test_build_init_schema_refuses_a_resumed_six_column_staging_table_and_writes_nothing`, `test_build_init_schema_creates_the_ann_id_table_on_a_fresh_db`, `test_merge_refuses_a_six_column_side_naming_it_before_any_write` (2 params), `test_merge_collision_fails_and_leaves_prod_rows_as_they_were`, `test_merge_without_collision_writes_the_staged_rows`, `test_sync_refuses_a_six_column_target_naming_main_before_any_write`, `test_sync_collision_fails_and_leaves_target_rows_and_fts_triggers_as_they_were`, `test_sync_without_collision_replaces_the_target_rows`.

## Step 3 — classification

What `active` holds today, as checked:

- `tests/active/test_ann_ids.py`, `test_sync_whitelist.py`, `test_merge_staging_db.py` and `test_build_video_embeddings.py` do not exist, in `active` or in `archive`.
- `tests/active/test_whitelist_migrations.py` asserts only the `videos.language` migration.
- `tests/active/test_updater_worker.py` has no test of `inject_replace_embedding_for_test`.
- Other active files (`test_db.py`, `test_metadata.py`, `test_video.py`, `test_random_*`, `test_precompute_*`) use `compute_ann_id` only to seed fixtures; none of them asserts it.

No `active` test asserts any behaviour in scope, so there is no `REPLACES` and no `COMBINE`. The only `REDUNDANT` verdicts come from overlap within the scope itself.

Subject files Step 5 must create:

- `tests/active/test_ann_ids.py`
- `tests/active/test_sync_whitelist.py`
- `tests/active/test_merge_staging_db.py`
- `tests/active/test_build_video_embeddings.py`

### phase1 → `tests/active/test_ann_ids.py` (new)

- `test_pinned_id` — **DURABLE**: pins the cross-process id literal; no active test asserts `compute_ann_id`'s value.
- `test_host_spelling_gives_the_pinned_id` — **DURABLE**: host normalisation inside the id; not asserted in active.
- `test_ids_are_distinct_positive_63_bit_values` — **DURABLE**: range and distinctness over 300 keys; not asserted in active.
- `test_unparsable_domain_falls_back_to_trimmed_lowercased_text` — **DURABLE**: the non-raising fallback; not asserted in active.
- `test_zero_ann_id_is_refused` — **DURABLE**: the CHECK guard; not asserted in active.
- `test_insert_of_another_keys_id_is_refused` — **DURABLE**: the collision trigger under INSERT; not asserted in active.
- `test_insert_or_replace_of_another_keys_id_is_refused_and_keeps_the_holder` — **DURABLE**: the trigger fires before OR REPLACE deletes the holder; not asserted in active.
- `test_same_key_replace_keeps_its_id` — **DURABLE**: the guard does not block a same-key replace; not asserted in active.
- `test_update_to_another_keys_id_is_refused` — **DURABLE**: the UNIQUE index refuses a colliding UPDATE; not asserted in active.

### phase2 → `tests/active/test_whitelist_migrations.py` (existing)

- `test_migration_backfills_derived_ann_ids_keeping_rowids_and_guards` — **DURABLE**: the rowid-preserving backfill, the guards and idempotence; the existing file covers only `language`.
- `test_missing_video_embeddings_is_left_alone` — **DURABLE**: the step is a no-op without the table; not asserted in active.
- `test_failed_backfill_rolls_back_to_the_six_column_table` — **DURABLE**: whole-transaction rollback on a collision; not asserted in active.

### phase3

- `test_new_target_carries_ann_id_and_passes_the_exact_check` — **REDUNDANT**: covered in scope by phase4 `test_sync_without_collision_replaces_the_target_rows`. That test builds its target the same way, seeds a seven-value positional row (which fails on any other shape) and drives sync's real `main()` through `ensure_schema_compatibility` to a written seven-column row.
- `test_six_column_target_is_refused_naming_ann_id_and_the_migration` — **REDUNDANT**: covered in scope by phase4 `test_sync_refuses_a_six_column_target_naming_main_before_any_write`. That test drives the real producer, sync's `main()`, through the same check and asserts `main.video_embeddings`, `missing columns: ann_id` and `migrate-whitelist.py`. It also asserts that nothing was written.
- `test_reload_from_a_source_without_ann_id_stores_the_derived_id` → `tests/active/test_sync_whitelist.py` (new) — **DURABLE**: computing the id during the reload. The phase4 sync tests use a source that already carries `ann_id`, so they never reach this path.
- `test_reload_from_a_source_with_ann_id_stores_the_sources_value` → `tests/active/test_sync_whitelist.py` (new) — **DURABLE**: copying the id rather than recomputing it, shown by the sentinel. No other test can tell the two apart.
- `test_merge_leaves_prod_rows_carrying_the_derived_id` → `tests/active/test_merge_staging_db.py` (new) — **DURABLE**: prod's stored id (the sentinel) is replaced by the staged id. phase4's merge control starts prod on the derived id already, so it cannot show this.
- `test_inject_writes_the_derived_id` → `tests/active/test_updater_worker.py` (existing) — **DURABLE**: the inject derives the id and never copies prod's. Active has no test of `inject_replace_embedding_for_test`.

### phase4

- `test_ensure_schema_refuses_a_six_column_table_with_the_migrate_pointer_and_writes_nothing` → `tests/active/test_ann_ids.py` — **DURABLE**: RuntimeError with the migrate and resume pointers, and no write; not asserted in active.
- `test_ensure_schema_creates_and_then_accepts_the_ann_id_table` → `tests/active/test_ann_ids.py` — **DURABLE**: fresh create with guards, and a second call accepted; not asserted in active.
- `test_has_ann_id_check_does_nothing_without_the_table` → `tests/active/test_ann_ids.py` — **DURABLE**: no-op when the table is missing; not asserted in active.
- `test_build_init_schema_refuses_a_resumed_six_column_staging_table_and_writes_nothing` → `tests/active/test_build_video_embeddings.py` (new) — **DURABLE**: build refuses before the model loads. It is the only test of `build-video-embeddings.py`.
- `test_build_init_schema_creates_the_ann_id_table_on_a_fresh_db` → `tests/active/test_build_video_embeddings.py` (new) — **DURABLE**: build's `init_schema` produces the guarded table. It catches a revert to inline DDL, which the `ann_ids` tests would not.
- `test_merge_refuses_a_six_column_side_naming_it_before_any_write` → `tests/active/test_merge_staging_db.py` (new) — **DURABLE**: a per-side refusal before the write lock; not asserted in active.
- `test_merge_collision_fails_and_leaves_prod_rows_as_they_were` → `tests/active/test_merge_staging_db.py` (new) — **DURABLE**: whole-merge rollback on a collision; not asserted in active.
- `test_merge_without_collision_writes_the_staged_rows` → `tests/active/test_merge_staging_db.py` (new) — **DURABLE**: the merge writes `instances`, `videos` and `video_embeddings` and logs `merged table=`. No active test runs the merge.
- `test_sync_refuses_a_six_column_target_naming_main_before_any_write` → `tests/active/test_sync_whitelist.py` (new) — **DURABLE**: sync's `main()` refuses before any write; not asserted in active.
- `test_sync_collision_fails_and_leaves_target_rows_and_fts_triggers_as_they_were` → `tests/active/test_sync_whitelist.py` (new) — **DURABLE**: one-transaction rollback that includes the FTS triggers; not asserted in active.
- `test_sync_without_collision_replaces_the_target_rows` → `tests/active/test_sync_whitelist.py` (new) — **DURABLE**: sync's `main()` end to end on the ann_id shape. No active test runs sync's `main()`.

### Counts

| Verdict | Tests |
|---|---|
| DURABLE | 28 |
| REDUNDANT | 2 |
| REPLACES | 0 |
| COMBINE | 0 |
| SPENT | 0 |

### Carrying notes for Step 5

Each destination gets its own copy of the constants and helpers it needs. Nothing is shared across groups.

- In `test_whitelist_migrations.py`, the existing `_table_info`, `_column_names` and `ROWS_SQL` read `videos`. The moved tests' versions for `video_embeddings` are renamed (`_embeddings_table_info`, `_embeddings_columns`, `EMBEDDINGS_ROWS_SQL`) so they do not shadow the existing ones, and the moved tests reuse the existing `_load_job`.
- In `test_updater_worker.py`, the moved test reuses the existing `updater` fixture and `_load_job`. Its `HOST`-free constants and the `_target`/`_seed` helpers come across under names that do not collide with the existing `_rows`/`_write`.
- The phase docstrings are rewritten to state the rule, not the build or phase.

### Group-map changes Step 5 would make

- add `test_ann_ids.py`: `engine/server/data/ann_ids.py`, `engine/server/data/moderation.py`
- add `test_sync_whitelist.py`: `engine/server/db/jobs/sync-whitelist.py`, `engine/server/data/ann_ids.py`
- add `test_merge_staging_db.py`: `engine/server/db/jobs/merge-staging-db.py`, `engine/server/data/ann_ids.py`
- add `test_build_video_embeddings.py`: `engine/server/db/jobs/build-video-embeddings.py`, `engine/server/data/ann_ids.py`
- `test_updater_worker.py`: add `engine/server/data/ann_ids.py`
- `test_whitelist_migrations.py`: unchanged (it already lists `whitelist_migrations.py`, `sync-whitelist.py` and `ann_ids.py`)
- no entry dropped, because nothing is retired

`engine/crawler/schema.sql`, and `sync-whitelist.py` where it only builds a fixture DB, are fixture inputs, so no new group claims them.

## Step 4 — plan status

Approved by the operator as presented. Count correction found while applying it: the scope holds 29 test functions (phase1 9, phase2 3, phase3 6, phase4 11; 35 items), not 30, so the plan's DURABLE count is 27, not 28. Every test the plan names was handled as named; nothing was added or dropped.

## Step 5 — applied

Moved (27 functions, 33 items):

- `tests/active/test_ann_ids.py` (NEW, group `test_ann_ids.py`): the 9 phase1 tests and phase4 `test_ensure_schema_refuses_a_six_column_table_with_the_migrate_pointer_and_writes_nothing`, `test_ensure_schema_creates_and_then_accepts_the_ann_id_table`, `test_has_ann_id_check_does_nothing_without_the_table`. `data.ann_ids` is imported at module level now that it exists.
- `tests/active/test_whitelist_migrations.py` (existing): the 3 phase2 tests; their helpers renamed `_embeddings_table_info`, `_embeddings_columns`, `EMBEDDINGS_ROWS_SQL`, `EMBEDDING_SEED`, `OLD_EMBEDDING_COLUMNS`; reuses the file's `_load_job`.
- `tests/active/test_sync_whitelist.py` (NEW): phase3 `test_reload_from_a_source_without_ann_id_stores_the_derived_id`, `test_reload_from_a_source_with_ann_id_stores_the_sources_value`; phase4 `test_sync_refuses_a_six_column_target_naming_main_before_any_write`, `test_sync_collision_fails_and_leaves_target_rows_and_fts_triggers_as_they_were`, `test_sync_without_collision_replaces_the_target_rows`.
- `tests/active/test_merge_staging_db.py` (NEW): phase3 `test_merge_leaves_prod_rows_carrying_the_derived_id`; phase4 `test_merge_refuses_a_six_column_side_naming_it_before_any_write`, `test_merge_collision_fails_and_leaves_prod_rows_as_they_were`, `test_merge_without_collision_writes_the_staged_rows`.
- `tests/active/test_build_video_embeddings.py` (NEW): phase4 `test_build_init_schema_refuses_a_resumed_six_column_staging_table_and_writes_nothing`, `test_build_init_schema_creates_the_ann_id_table_on_a_fresh_db`.
- `tests/active/test_updater_worker.py` (existing): phase3 `test_inject_writes_the_derived_id`, reusing the `updater` fixture and `_load_job`; its own helpers are `INJECT_*`, `inject_sync_job` and `_inject_db`.

Retired: none. Group map: added `test_ann_ids.py`, `test_sync_whitelist.py`, `test_merge_staging_db.py`, `test_build_video_embeddings.py`; `engine/server/data/ann_ids.py` added to `test_updater_worker.py`. `--audit-map` exited 0; no MISSING finding names a moved test.

## Step 6 — mutations

Each run backed up the production file, applied one sed mutation, ran the one test red, restored from the copy (`diff` clean), and ran green. Backups and logs are in `delete_me/harvest41_mutations/`. No `.bak` is left under `engine/`.

- M1 `test_pinned_id`: ann_ids.py `from_bytes(..., "big")`→`"little"`; felled `compute_ann_id("abc", HOST) == PINNED_ABC_ID` (6029229592441628849).
- M2 `test_host_spelling_gives_the_pinned_id`: ann_ids.py skip `normalize_host`; felled the pinned-id assertion for `Peertube.Example.` and the URL spelling.
- M3 `test_ids_are_distinct_positive_63_bit_values`: ann_ids.py drop `& ANN_ID_MASK`; felled the 1..2**63-1 range assertion (150 out of range).
- M4 `test_unparsable_domain_falls_back_to_trimmed_lowercased_text`: ann_ids.py fallback without `.strip().lower()`; felled `[  Bad Host  ]` (8528140052437447888).
- M5 `test_zero_ann_id_is_refused`: ann_ids.py `CHECK (ann_id > 0)`→`>= 0`; felled `pytest.raises(IntegrityError)` (DID NOT RAISE).
- M6 `test_insert_of_another_keys_id_is_refused`: ann_ids.py `create_ann_id_guards` returns first; felled `pytest.raises(IntegrityError)`.
- M7 `test_insert_or_replace_of_another_keys_id_is_refused_and_keeps_the_holder`: ann_ids.py trigger `BEFORE INSERT`→`AFTER INSERT`; felled `pytest.raises(IntegrityError)`.
- M8 `test_same_key_replace_keeps_its_id`: ann_ids.py trigger key exclusion→`AND 1`; the same-key replace raised the collision IntegrityError.
- M9 `test_update_to_another_keys_id_is_refused`: ann_ids.py UNIQUE index→plain index; felled `pytest.raises(IntegrityError)`.
- M10 `test_ensure_schema_refuses_...`: ann_ids.py ann_id check in `ensure_video_embeddings_schema`→`pass`; `pytest.raises(RuntimeError)` felled by the raw `OperationalError: no such column: ann_id`.
- M11 `test_ensure_schema_creates_and_then_accepts_the_ann_id_table`: ann_ids.py guards call→`pass`; felled the guards-in-sqlite_master assertion.
- M12 `test_has_ann_id_check_does_nothing_without_the_table`: ann_ids.py `if columns and ...`→`if ...`; felled `assert_video_embeddings_has_ann_id(conn) is None` (raised RuntimeError).
- M13 `test_migration_backfills_derived_ann_ids_keeping_rowids_and_guards`: whitelist_migrations.py SELECT `rowid`→`NULL`; felled "a row was renumbered, lost or altered by the rebuild".
- M14 `test_missing_video_embeddings_is_left_alone`: whitelist_migrations.py creates the table before the missing-table return; felled "the step created something on a DB without video_embeddings".
- M15 `test_failed_backfill_rolls_back_to_the_six_column_table`: whitelist_migrations.py `rollback()`→`commit()`; felled "the failed rebuild left a changed video_embeddings".
- M16 `test_reload_from_a_source_without_ann_id_stores_the_derived_id`: sync-whitelist.py `ann_id_of(instance_domain, video_id)`; felled the rows assertion (v1 4746003751325829368 ≠ 8241284212183890047).
- M17 `test_reload_from_a_source_with_ann_id_stores_the_sources_value`: sync-whitelist.py source-ann_id branch→`if False:`; felled the rows assertion (v3 derived id ≠ 777).
- M18 `test_sync_refuses_a_six_column_target_naming_main_before_any_write`: sync-whitelist.py exact check against `EMBEDDING_COLUMNS`; `pytest.raises(RuntimeError)` felled by `OperationalError: table video_embeddings has no column named ann_id`.
- M19 `test_sync_collision_fails_and_leaves_target_rows_and_fts_triggers_as_they_were`: sync-whitelist.py trigger drop through `executescript`; felled `after["instances"] == before["instances"]`.
- M20 `test_sync_without_collision_replaces_the_target_rows`: sync-whitelist.py embeddings copy→`if False:`; felled the `video_embeddings` assertion ([] ≠ two rows).
- M21 `test_merge_leaves_prod_rows_carrying_the_derived_id`: merge-staging-db.py `INSERT OR REPLACE`→`INSERT OR IGNORE`; felled the prod rows assertion (v1 kept 555).
- M22 `test_merge_refuses_a_six_column_side_naming_it_before_any_write`: merge-staging-db.py both up-front checks neutralised; old-stage felled `refusal.startswith("RuntimeError:")`, old-main felled `returncode != 0`.
- M23 `test_merge_collision_fails_and_leaves_prod_rows_as_they_were`: merge-staging-db.py `rollback()`→`commit()`; felled `after["instances"] == before["instances"]`.
- M24 `test_merge_without_collision_writes_the_staged_rows`: merge-staging-db.py `commit()`→`pass` felled a DIFFERENT assertion, `returncode == 0` (DETACH on a locked stage), so it was re-run as M24b: INSERT_OR_REPLACE SELECT `WHERE 0`, which felled `after["video_embeddings"] == [...]`.
- M25 `test_build_init_schema_refuses_...`: build-video-embeddings.py `init_schema` reverted to inline seven-column DDL; felled `pytest.raises(RuntimeError)` (DID NOT RAISE).
- M26 `test_build_init_schema_creates_the_ann_id_table_on_a_fresh_db`: the same inline-DDL revert; felled the guards-in-sqlite_master assertion.
- M27 `test_inject_writes_the_derived_id`: updater-worker.py `compute_ann_id(instance_domain, video_id)`; felled the staging rows assertion in both params.

No mutation survived, none hung, nothing was reclassified.

## Step 7 — disposed

Moved to `delete_me/`: `test_41_ann_ids_a_schema_writers_phase1.py`, `..._phase2.py`, `..._phase3.py`, `..._phase4.py`. `tests/tmp` holds none of them. The `probe_*`, `test_probe_*` and `test_42_*` files stay, out of scope.

## Step 8 — closing run

`tests/last_test_validation.json.preharvest` restored over the record, then `--compare` (no tier): 8 of 55 groups selected, 108 passed, 0 failed. 33 appeared (the 27 moved functions' items), 0 gone, no new red, nothing newly green. `test_search_fusion.py` (no map entry) and `test_static_page_visit_logs.py` (changed) were selected for state that predates this harvest and passed.
