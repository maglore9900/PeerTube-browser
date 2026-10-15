# Tests retired in build 01-63-catalog-update-weekly-increments

## `tests/active/test_install_updater_service.py::test_updater_installer_dev_dry_run_keeps_single_name_rule`

Cut whole and unchanged at step 7, phase 4, into `test_install_updater_service.py` in this folder. Its file stays active with the prod test, so its `test_groups` entry is unchanged.

**What it asserted.** A dev `engine/install-updater-service.sh --dry-run --with-updater-timer --force` exits 0, its sudoers preview is the single-name rule for `peertube-engine-dev`, and its `ExecStart` is exactly the pre-build string ending `--max-retries 3'`, with no `--engine-upstream-snippet`.

**Why no repoint could save it.** The exact `ExecStart` string is the assertion, and it spells out the pre-build default `UPDATER_FLAGS`. Phase 4's confirmed requirement C1 replaces that default: the dev unit's worker argv now ends `--max-retries 3 --increments 7`. The flags come from the installer's own default, not from a fixture or harness constant, and the harness's `Tree.run` is shared with the phase-4 checkpoint, which needs the real default; so the only way to make it pass is to rewrite the asserted string.

**What answers its concern now.** The phase-4 checkpoint `tests/tmp/test_63_catalog_update_weekly_increments_phase4.py::test_dev_updater_unit_runs_one_increment_of_seven_daily_at_20` covers the same dev dry-run: exit 0, `--mode dev`, the argv ending `--max-retries 3 --increments 7`, and `parse_args` reading it. It does not assert the dev single-name sudoers rule or the absence of `--engine-upstream-snippet`. Those two claims have no active test until the Step 10 harvest restores this test with the new default pinned (the plan's impact entry for this file: the dev ExecStart pin ends `--max-retries 3 --increments 7'`). The module docstring of the active file still describes the dev test (its line 4) and should be reworded at the same time.
