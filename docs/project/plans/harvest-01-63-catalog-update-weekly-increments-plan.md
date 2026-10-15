# Harvest: plan 01-63 catalog update weekly increments

## Step 1: resolved paths and scope

Bootstrap gate: clear. `./.un/skills/devsecops/scripts/validate_tests.py --show-config` reports `defaulted: []` and `conflicts: []`. `map_health.unmapped_groups` lists `test_search_fusion.py`, which predates this build and is outside this harvest.

- project_dir: `/home/enduser/code/PeerTube-browser`
- source (group map): `/home/enduser/code/PeerTube-browser/tests/config.json`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- HARVEST_FILE: `docs/project/plans/harvest-01-63-catalog-update-weekly-increments-plan.md`

Start tree: `4dd6b0c54893236564a1dc178ab9cacbda826ce7`. This is the build's start tree, handed in by the build dispatch as Step 1's start tree. Per that dispatch, no snapshot of my own was taken: `tests/last_test_validation.json.preharvest` was NOT created this turn. Step 8's comparison is measured against this start tree. Step 6 must not run until whoever carries out Step 5 onwards has confirmed how the pre-harvest record is held.

Scope: the four tests this build wrote, as the build dispatch names them. This is not a sweep of the whole tree.

- `tests/tmp/test_63_catalog_update_weekly_increments_phase1.py`
- `tests/tmp/test_63_catalog_update_weekly_increments_phase2.py`
- `tests/tmp/test_63_catalog_update_weekly_increments_phase3.py`
- `tests/tmp/test_63_catalog_update_weekly_increments_phase4.py`

Files in `tests/tmp` that are out of scope: they were left by earlier builds and this harvest does not touch them. Step 7 moves only the four files above, so `tests/tmp` will NOT be empty afterwards.
- Test files: `test_53_tags_on_cards_and_tag_phase1.py`, `test_blocks_tags.py`, `test_frontend_search_page.py`, `test_frontend_tag_chips.py`, `test_probe_55_phase3_drivers.py` (empty), `test_search_tags.py`, `test_search_tags_index_missing.py`, `test_similar_tags.py`.
- Probes and data: `probe_45_*`, `probe_49_*`, `probe_50_*`, `probe_53_*`, `delete_failed_row.py`, `inspect_subtitles.py`, `mt.json`.
- `__pycache__/`.

Collection: I did not run any of the four files. I checked their imports by reading them, and all of them resolve:
- phases 1-3 import stdlib, `pytest` and `data.ann_ids.create_video_embeddings_table`, which `tests/active/test_updater_worker.py` also imports;
- phase 4 loads `tests/active/test_install_updater_service.py` as a module and uses `Tree`, `UPDATER_INSTALLER`, `CENTRAL_INSTALLER`, `UPDATER_WORKER`, `BASH`, `_report`, `_previews`, `_exec_start`, `_values`, `_worker_argv` and `_sub_installer_argvs`, all of which that file defines.
No file needed a `validate_tests.py <path>` run to diagnose a collection failure. I counted the parametrised items by reading the files, not by collecting them. There are 23 items from 12 functions: phase 1 has 7, phase 2 has 6, phase 3 has 5 and phase 4 has 5.

## Step 2: inventory

### tests/tmp/test_63_catalog_update_weekly_increments_phase1.py

Drives `engine/server/db/jobs/updater-worker.py`. `main()` runs in-process through `sys.argv` down the full crawl path to `--fail-before-merge`, with only `subprocess.run` faked.

Module-level dependencies:
- sys.path setup: `ROOT`, `SERVER_DIR`, and the server and api dirs;
- constants: `JOBS_DIR`, `PYTHON_BIN`, `JOB_SCRIPTS` (includes `fetch-trending.py`), `HOSTS` (8 hosts, including `Mixed.Example.` and `Watch.Example.`), `GROUP_CASES`, `VALID_POINTER`, `CORRUPT_POINTER`, `REFUSALS`;
- helpers: `_load_job`, `_jobs`, `_is`, `_run_crawl_main(updater, monkeypatch, tmp_path, *, extra, state)`;
- fixture: `updater` (module scope, loaded as `updater_worker_increments_phase1`).

Tests:
- `test_the_channels_crawl_sees_only_the_hosts_of_the_group_after_the_stored_one` (3 params: last-3-crawls-4, last-1-crawls-2, last-6-wraps-to-0)
- `test_an_untrustworthy_pointer_or_increment_flag_stops_the_run_before_any_child` (4 params: corrupt-pointer, negative-increments, with-sync-join, missing-state-dir)

### tests/tmp/test_63_catalog_update_weekly_increments_phase2.py

Drives `engine/server/db/jobs/updater-worker.py`. `main()` runs in-process down the full crawl and merge path with `--skip-systemctl`, `subprocess.run` faked, and `run_similarity_stage` replaced by a recorder.

Module-level dependencies:
- constants: `ROOT`, `SERVER_DIR`, `JOBS_DIR`, `PYTHON_BIN`, `JOB_SCRIPTS`, `HOSTS` (6 hosts), `PRIOR_POINTER`, `SUCCESS_CASES`, `STOPS`;
- helpers: `_load_job`, `_jobs`, `_is`, `_snapshot`, `_run_increment_main` (records similarity calls), `_pointer`;
- fixture: `updater` (`updater_worker_increments_phase2`).

Tests:
- `test_a_completed_run_records_the_crawled_group_after_the_merge_child_and_before_the_popularity_child` (3 params: n7-no-pointer-crawls-0, n7-last-3-crawls-4, n3-over-n7-pointer-crawls-0)
- `test_a_run_that_stops_before_the_merge_commits_leaves_the_pointer_byte_identical` (3 params: fail-before-merge, merge-child-fails, run-lock-held)

### tests/tmp/test_63_catalog_update_weekly_increments_phase3.py

Drives `engine/server/db/jobs/updater-worker.py`. `main()` runs in-process through the same crawl and merge path. Here the real `write_increment_pointer` and `run_similarity_stage` run, a fake precompute child writes an empty shadow cache, and caplog is read at INFO.

Module-level dependencies:
- constants: `ROOT`, `SERVER_DIR`, `JOBS_DIR`, `PYTHON_BIN`, `JOB_SCRIPTS`, `HOSTS` (6 hosts), `PRIOR_POINTER`, `NOT_ADVANCED`, `PRE_MERGE_STOPS`;
- helpers: `_load_job`, `_jobs`, `_is`, `_snapshot`, `_run_increment_main` (a different body from phase 2: it has the precompute shadow writer and `similarity_swapped`, and does not replace `run_similarity_stage`), `_pointer`, `_messages`, `_run_armed`;
- fixture: `updater` (`updater_worker_increments_phase3`).

Tests:
- `test_a_run_failing_before_the_merge_commits_logs_one_pointer_not_advanced_line_with_the_reason` (2 params: fail-before-merge, merge-child-fails)
- `test_a_run_refused_by_the_run_lock_logs_no_pointer_not_advanced_line`
- `test_a_completed_run_logs_worker_completed_and_no_pointer_not_advanced_line`
- `test_a_failed_pointer_write_runs_ann_trending_and_similarity_then_fails_the_run`

### tests/tmp/test_63_catalog_update_weekly_increments_phase4.py

Drives three scripts, each run as a subprocess:
- `engine/install-updater-service.sh` (`--dry-run`);
- `scripts/install-service.sh` (`--dry-run`, central argv);
- `scripts/run-catalog-update.sh` (copied into a temp repo).
It also drives `engine/server/db/jobs/updater-worker.py` `parse_args`, in-process.

Module-level dependencies:
- constants: `ROOT`, `CATALOG_SCRIPT`, `DAILY`, `RECORDER` (the recording interpreter body);
- `harness`: `tests/active/test_install_updater_service.py` loaded as a module, from which it uses `Tree`, `UPDATER_INSTALLER`, `CENTRAL_INSTALLER`, `UPDATER_WORKER`, `BASH`, `_report`, `_previews`, `_exec_start`, `_values`, `_worker_argv` and `_sub_installer_argvs`;
- fixture: `worker` (`updater_worker_increments_phase4`);
- helpers: `_parse`, `_on_calendar`, `_run_catalog_update`.

Tests:
- `test_prod_updater_unit_runs_one_increment_of_seven_daily_at_20` (2 params: defaults, central-argv): installers
- `test_dev_updater_unit_runs_one_increment_of_seven_daily_at_20`: installer
- `test_catalog_update_passes_increments_seven_ahead_of_operator_flags_so_increments_zero_overrides`: run-catalog-update.sh
- `test_catalog_update_without_operator_flags_passes_increments_seven`: run-catalog-update.sh

## Step 3: classification

Subject files read:
- `tests/active/test_updater_worker.py` (not split, 66 tests). Grep for `increment`: no test asserts anything about `--increments`, the pointer file, group selection or `pointer not advanced`.
- `tests/active/test_install_updater_service.py` (not split). It has one prod test, which asserts the sudoers rule, the snippet and the `parse_args` snippet. Nothing in it asserts `--increments` or `OnCalendar`. Its dev test was retired by this build to `tests/archive/01-63-catalog-update-weekly-increments/`.
- `tests/active/test_install_service.py`: no `OnCalendar` or updater-flag assertion.
- `scripts/run-catalog-update.sh`: no subject file exists in `tests/active`, and no `test_groups` entry names the script. Its tests therefore cannot be `REDUNDANT`, and Step 5 must create `tests/active/test_run_catalog_update.py`.

No test in scope duplicates another in scope. The overlapping harness runs read different observables: in phases 2 and 3 the same stops are read for pointer bytes in one and for the log line in the other, and in phases 1 and 2 the group selection is the claim in one and a control in the other.

### test_the_channels_crawl_sees_only_the_hosts_of_the_group_after_the_stored_one
DURABLE → `tests/active/test_updater_worker.py`. No active test asserts that the channels crawl sees only the selected sha1 group, (last_group+1)%N, hashed on the host string as stored.

### test_an_untrustworthy_pointer_or_increment_flag_stops_the_run_before_any_child
DURABLE → `tests/active/test_updater_worker.py`. No active test covers the startup refusals: a corrupt pointer, negative N, `--sync-join-whitelist` with increments, and a missing state dir, each refused with no child run and the pointer byte-identical.

### test_a_completed_run_records_the_crawled_group_after_the_merge_child_and_before_the_popularity_child
DURABLE → `tests/active/test_updater_worker.py`. No active test asserts that the pointer is written between the merge child and the popularity child, with the crawled group and the run's N. This includes the N-changed restart at 0.

### test_a_run_that_stops_before_the_merge_commits_leaves_the_pointer_byte_identical
DURABLE → `tests/active/test_updater_worker.py`. No active test asserts that a fail-before-merge stop, a failed merge child or a held run lock leaves the pointer byte-identical.

### test_a_run_failing_before_the_merge_commits_logs_one_pointer_not_advanced_line_with_the_reason
DURABLE → `tests/active/test_updater_worker.py`. No active test reads the `pointer not advanced` log.

### test_a_run_refused_by_the_run_lock_logs_no_pointer_not_advanced_line
DURABLE → `tests/active/test_updater_worker.py`. It is the only test that gates "no line on a run that never read the pointer". The phase-2 lock case reads pointer bytes, not the log.

### test_a_completed_run_logs_worker_completed_and_no_pointer_not_advanced_line
DURABLE → `tests/active/test_updater_worker.py`. It is the only test that gates "no line on a run whose pointer advanced". The active trending tests read `worker completed` only on non-increment runs.

### test_a_failed_pointer_write_runs_ann_trending_and_similarity_then_fails_the_run
DURABLE → `tests/active/test_updater_worker.py`. No active test covers a failed pointer write. The required behaviour: the ANN, trending and similarity steps still run, then the run raises `increment pointer not advanced`, logs no `worker completed`, and logs exactly one line.

### test_prod_updater_unit_runs_one_increment_of_seven_daily_at_20
DURABLE → `tests/active/test_install_updater_service.py`. The active prod test reads the sudoers rule and the snippet from the same dry-run but never `--increments` or `OnCalendar`, so the daily schedule and the increments default have no active gate.

### test_dev_updater_unit_runs_one_increment_of_seven_daily_at_20
DURABLE → `tests/active/test_install_updater_service.py`. No active test covers the dev unit: the build retired the only one, `test_updater_installer_dev_dry_run_keeps_single_name_rule`, to archive.

Its counterpart is in `<archive>`, not `<active>`, so this is not a `COMBINE`. On the move, Step 5 also lifts the archived test's two claims, which the build's plan and the archive README leave for this harvest:
- the dev sudoers preview is exactly the single-name `stop|start peertube-engine-dev` rule;
- the `ExecStart` has no `--engine-upstream-snippet` even with the override set. The exact-string pin becomes `... --max-retries 3 --increments 7'`.

The test's name and docstring are reworded to cover all of it. The active module docstring's line 4, which describes the dev test, is reworded to match. Each lifted claim needs its own Step 6 mutation.

### test_catalog_update_passes_increments_seven_ahead_of_operator_flags_so_increments_zero_overrides
DURABLE → `tests/active/test_run_catalog_update.py` (NEW subject file). There is no active subject for `scripts/run-catalog-update.sh`.

### test_catalog_update_without_operator_flags_passes_increments_seven
DURABLE → `tests/active/test_run_catalog_update.py` (NEW subject file). It is the only gate for "7 alone, not missing and not doubled" on the default call.

## Notes for Step 5 (name check preview; recorded in full at Step 5)

### Folding into `tests/active/test_updater_worker.py`

These incoming names are already defined in the active file:
- **Same body, keep one copy:** `_load_job`, `updater`, `PYTHON_BIN`, `ROOT`, `SERVER_DIR`, `JOBS_DIR`.
- **`_jobs`:** the active one has a `with_trending=True` default that already writes `fetch-trending.py`. Keep it and drop the incoming `_jobs` and `JOB_SCRIPTS`, whose value differs.
- **`_run_crawl_main`:** the active one (`fail_tags`) has a different body from phase 1's (`extra`, `state`). Phase 1's must be renamed, e.g. `_run_increment_crawl_main`.

These names collide across the incoming files:
- **Same body, keep one copy:** `_is`, `_snapshot`, `_pointer`, and `PRIOR_POINTER` (phase 1's `VALID_POINTER` is the same bytes).
- **Rename:** `HOSTS` differs between phase 1 (8 hosts) and phases 2-3 (6 hosts). `_run_increment_main` differs between phases 2 and 3.

Every test monkeypatches `script_dir`, `subprocess.run` and `sys.argv` on the module-scoped `updater` fixture, so sharing the active fixture changes nothing.

### Folding into `tests/active/test_install_updater_service.py`

- Keep: `worker` (same body, different module name).
- Add: `DAILY`, `_parse`, `_on_calendar`.
- Calls to `harness.X` become direct `X`.

### Creating `tests/active/test_run_catalog_update.py`

- Copy in: `BASH`, `_values`, `UPDATER_WORKER`, the `worker` fixture, `_parse`, `RECORDER`, `CATALOG_SCRIPT`, `_run_catalog_update`.
- Do not import them from `test_install_updater_service.py`: the fixture is copied, never shared across groups.

## Step 4: plan presented

See the Submit `plan` field of this turn. In this build the plan needs no operator approval. A second turn carries out Steps 5-8.

## Pre-harvest record (resolved at the start of Step 5)

`tests/last_test_validation.json` was last written at 11:05:00, before HARVEST_FILE (11:07:29), and Steps 1-4 ran only `--show-config`, which does not bank. So the record on disk was still the pre-harvest one. I copied it to `tests/last_test_validation.json.preharvest` (`cmp` clean) before any banking run, and Step 8 restored it from there.

## Step 5: applied

### tests/active/test_updater_worker.py (8 tests added)
- Kept once (the active copy): `ROOT` (from conftest), `SERVER_DIR`, `JOBS_DIR`, `PYTHON_BIN`, `_load_job`, `updater`, `_jobs` (active `with_trending=True` already writes `fetch-trending.py`; incoming `_jobs` and `JOB_SCRIPTS` dropped).
- Kept once across the incoming files: `_is`, `_snapshot`, `_pointer`, `_messages`, `PRIOR_POINTER` (phase 1's `VALID_POINTER` is the same bytes, so its uses now read `PRIOR_POINTER`), `NOT_ADVANCED`.
- Renamed: phase 1 `_run_crawl_main` -> `_run_increment_crawl_main` (clashes with the active tags harness); phase 1 `HOSTS` (8 hosts) -> `GROUP_HOSTS`, phases 2-3 keep `HOSTS` (6 hosts); phase 3 `_run_increment_main` -> `_run_increment_main_with_similarity`, phase 2 keeps `_run_increment_main`.
- Added unchanged: `GROUP_CASES`, `CORRUPT_POINTER`, `REFUSALS`, `SUCCESS_CASES`, `STOPS`, `PRE_MERGE_STOPS`, `_run_armed`.
- Module docstring gains an increments paragraph; `# C1`/`# C2` phase tags dropped from comments.

### tests/active/test_install_updater_service.py (2 tests added)
- Kept once: `worker` (active copy). Added: `DAILY`, `_parse`, `_on_calendar`. `harness.X` references became direct names.
- `test_dev_updater_unit_runs_one_increment_of_seven_daily_at_20` renamed `test_dev_updater_unit_keeps_single_name_rule_and_no_snippet_and_runs_one_increment_of_seven_daily_at_20` and given the archived test's two claims: the exact single-name dev sudoers rule, and the exact `ExecStart` with no snippet, re-pinned to end `--max-retries 3 --increments 7'`.
- Module docstring: line 1 adds the daily increments; the old dev line 4 is replaced by a prod increments line and a dev line covering everything the dev test now asserts.

### tests/active/test_run_catalog_update.py (NEW, 2 tests)
- Copied in, not imported: `BASH`, `UPDATER_WORKER`, `_values`, `worker` (module name `updater_worker_catalog_update`), `_parse`, `RECORDER`, `CATALOG_SCRIPT`, `_run_catalog_update`.

### test_groups
- Added `"test_run_catalog_update.py": ["scripts/run-catalog-update.sh", "engine/server/db/jobs/updater-worker.py"]`. `--audit-map` exits 0. The new group's only finding is advisory UNRESOLVABLE `updater-worker.py`, which is the worker basename. The MISSING findings for `test_updater_worker.py` are the empty fake job scripts the harness writes, and they are unchanged.

## Step 6: mutations (each restored from `.scratch/harvest/<test>/`, `diff` clean, then green)
1. `test_the_channels_crawl_sees_only_the_hosts_of_the_group_after_the_stored_one`: `read_increment_pointer` returns `last % increments` (selects the stored group, not its successor). All 3 items red on `hosts_at_channels == [expected]`. Green after restore.
2. `test_an_untrustworthy_pointer_or_increment_flag_stops_the_run_before_any_child`: `if args.increments < 0` -> `< -1`. `[negative-increments]` red on `run["calls"] == []` (the run went on to crawl). Green after restore.
3. `test_a_completed_run_records_the_crawled_group_after_the_merge_child_and_before_the_popularity_child`: write passes `(selected_group + 1) % N`. All 3 items red on `written["last_group"] == group`. Green after restore.
4. `test_a_run_that_stops_before_the_merge_commits_leaves_the_pointer_byte_identical`: `write_increment_pointer` inserted right after the pointer read (advance before the merge). `[fail-before-merge]` red on `state.read_bytes() == PRIOR_POINTER`, and `[merge-child-fails]` red on its `pointer_at_merge` control. Green after restore.
5. `test_a_run_failing_before_the_merge_commits_logs_one_pointer_not_advanced_line_with_the_reason`: the outer handler logs `type(exc).__name__` instead of `exc`. Both items red on `reason in lines[0]`. Green after restore.
6. `test_a_run_refused_by_the_run_lock_logs_no_pointer_not_advanced_line`: the outer handler is guarded on `pointer_pending or args.increments >= 1` (`%s` for the group). Red on `_messages(caplog, NOT_ADVANCED) == []`. Green after restore.
7. `test_a_completed_run_logs_worker_completed_and_no_pointer_not_advanced_line`: the `finally` logs `increment pointer not advanced` whenever `selected_group is not None`. Red on `_messages(caplog, NOT_ADVANCED) == []`. Green after restore.
8. `test_a_failed_pointer_write_runs_ann_trending_and_similarity_then_fails_the_run`: `except OSError` around the write -> `except ValueError` (the error propagates at once). Red on `any(_is(cmd, "build-ann-index.py") ...)`. Green after restore.
9. `test_prod_updater_unit_runs_one_increment_of_seven_daily_at_20`: `scripts/install-service.sh` default `UPDATER_FLAGS` drops `--increments 7` (the installers drift). `[central-argv]` red on `_values(argv, "--increments") == ["7"]`; `[defaults]` stayed green, as predicted. Green after restore.
10a. dev test: `engine/install-updater-service.sh` default `UPDATER_FLAGS` drops `--increments 7`. Red on the exact `ExecStart` pin. Green after restore.
10b. dev test (lifted sudoers claim): `engine_units` gains `${ENGINE_SERVICE_NAME}.service`. Red on the single-name sudoers assertion. Green after restore.
10c. dev test (lifted no-snippet claim): `snippet_flag=""` -> `" --engine-upstream-snippet ${UPSTREAM_SNIPPET}"`. Red on the exact `ExecStart` pin, which now carries the snippet. Green after restore.
11. `test_catalog_update_passes_increments_seven_ahead_of_operator_flags_so_increments_zero_overrides`: `--increments 7` moved after `EXTRA_ARGS`. Red on `_values(argv, "--increments") == ["7", "0"]`. Green after restore.
12. `test_catalog_update_without_operator_flags_passes_increments_seven`: `--increments 7` removed. Red on `_values(argv, "--increments") == ["7"]`. Green after restore.

No batches, so no cancellations. No mutation hung. Nothing was reclassified. No `.bak` is under `engine/`, `scripts/` or `tests/active/`. All four production files `diff` clean against their first copies.

## Step 7: disposed
Moved to `delete_me/`, with no name clashes: `test_63_catalog_update_weekly_increments_phase1.py` to `phase4.py`. `tests/tmp` holds none of them; its out-of-scope files stay.

## Step 8: compare
I restored `.preharvest` to `tests/last_test_validation.json` and ran `--compare` with no tier. It selected 5 of 71 groups and gave 113 passed, 0 failed. The appearances were 23, which are the 23 harvested items; departures 0; new reds 0; no-longer-red 0. `test_static_page_visit_logs.py` re-ran as "changed" (10 passed). The harvest touched none of its mapped files. `test_search_fusion.py` re-ran as it always does, because it has no map entry.
