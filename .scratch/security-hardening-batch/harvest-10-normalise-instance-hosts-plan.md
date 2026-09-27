# Harvest: 10-normalise-instance-hosts

## Resolved paths (from `--show-config`, bootstrap gate clear: `defaulted` is empty, `conflicts` is empty)

- project_dir: `/home/enduser/code/PeerTube-browser/.worktrees/fix-10-normalise-instance-hosts`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`

## Scope

- `tests/tmp/test_10_normalise_instance_hosts_phase1.py`
- `tests/tmp/test_10_normalise_instance_hosts_phase2.py`
- `tests/tmp/test_10_normalise_instance_hosts_phase3.py`

Also present in `tests/tmp`, written by this build as probes, gating nothing and not `test_*.py`: `probe_durable_host.py`, `probe_git_outside_worktree.py`, `probe_host_token.py`, `probe_phase2_env.py`, `probe_phase2_harness.py`, `probe_phase3.py`, `probe_phase3_seams.py`. Out of scope unless the operator adds them at Step 4.

## Snapshot

`tests/last_test_validation.json` copied to `tests/last_test_validation.json.preharvest` before any run.

## Map state at start

`--show-config` `map_health.unmapped_groups` = `[test_host_normalisation.py]`: the durable file this build created in `tests/active` has no `test_groups` entry. `--audit-map` exits 0 (advisory MISSING/BARREN on other groups only).

## Inventory

### tests/tmp/test_10_normalise_instance_hosts_phase1.py
Drives `engine/server/data/moderation.py` (`normalize_host_token`). Constants: `ROOT`, `SERVER_DIR`, `FIXTURE`, `PINNED` (15 pairs written independently of the fixture). Tests: `test_fixture_holds_exactly_the_pinned_pairs`, `test_normalize_host_token_returns_pinned_value` (15 params).

### tests/tmp/test_10_normalise_instance_hosts_phase2.py
Drives `engine/crawler/dist/host-filters.js` under node and, via pytest subprocesses, the durable test `tests/active/test_host_normalisation.py::test_crawler_dist_returns_pinned_values`. Constants/helpers: `PINNED`, `FIXTURE_PAIRS`, `NODE_SCRIPT`, `PATHS_PLUGIN`, `_run_crawler_test`, `_git`, `_commit`, `_crawler_copy`, `_older_on_disk`, `_git_env`, `_path_with_only`, `_dist_outputs`. Tests: `test_crawler_dist_under_node_returns_pinned_values`, `test_durable_crawler_test_passes_on_this_tree`, `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input` (15 params), `test_durable_crawler_test_fails_on_current_dist_with_one_wrong_value`, `test_durable_crawler_test_fails_loudly_without_node`, `test_durable_crawler_test_fails_loudly_when_dist_is_missing`, `test_durable_crawler_test_fails_loudly_when_src_committed_after_dist`, `test_durable_crawler_test_passes_when_dist_committed_after_src_though_older_on_disk`, `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk`, `test_durable_crawler_test_fails_loudly_when_uncommitted_src_edit_is_newer_than_dist`, `test_durable_crawler_test_fails_loudly_when_dist_has_no_history_and_is_older`, `test_durable_crawler_test_fails_without_git`.

### tests/tmp/test_10_normalise_instance_hosts_phase3.py
Drives `engine/server/db/jobs/sync-whitelist.py` and `engine/server/db/jobs/updater-worker.py`. Helpers: `_load`, module fixture `jobs`, `_serve`, constant `DROPPED`. Tests: `test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row`, `test_both_fetchers_drop_entries_that_normalise_to_none`, `test_fetch_hosts_still_raises_when_every_entry_normalises_to_none`.

All three files collected and ran green in the build.

## Classification (subject file: `tests/active/test_host_normalisation.py`)

### phase1
- `test_fixture_holds_exactly_the_pinned_pairs` — SPENT: guards that the phase created `host_tokens.json` with the pinned pairs; the fixture is now the durable spec and no production code is asserted.
- `test_normalize_host_token_returns_pinned_value` — REDUNDANT: `test_python_port_returns_pinned_value` asserts the same 15 pairs on the same function.

### phase2
- `test_crawler_dist_under_node_returns_pinned_values` — REDUNDANT: `test_crawler_dist_returns_pinned_values` runs the same dist under node against the same pairs (its fixture==PINNED half is SPENT as above).
- `test_durable_crawler_test_passes_on_this_tree` — REDUNDANT: the durable test running green in the suite is that assertion.
- `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input` — SPENT: a meta-test of the durable test's grip, not of production code; the phase it gated has landed.
- `test_durable_crawler_test_fails_on_current_dist_with_one_wrong_value` — SPENT: same, meta-test.
- `test_durable_crawler_test_fails_loudly_without_node` — SPENT: asserts the durable test's own fail-not-skip policy; no production code.
- `test_durable_crawler_test_fails_loudly_when_dist_is_missing` — SPENT: same.
- `test_durable_crawler_test_fails_loudly_when_src_committed_after_dist` — SPENT: asserts the staleness rule, which lives only in the test file.
- `test_durable_crawler_test_passes_when_dist_committed_after_src_though_older_on_disk` — SPENT: same.
- `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk` — SPENT: same.
- `test_durable_crawler_test_fails_loudly_when_uncommitted_src_edit_is_newer_than_dist` — SPENT: same.
- `test_durable_crawler_test_fails_loudly_when_dist_has_no_history_and_is_older` — SPENT: same.
- `test_durable_crawler_test_fails_without_git` — SPENT: same.

### phase3
- `test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row` — REDUNDANT: `test_sync_job_stores_one_spelling_per_host` asserts the same set, the same (1, 0, 1) and the same row.
- `test_both_fetchers_drop_entries_that_normalise_to_none` — REDUNDANT: `test_jobs_drop_entries_that_normalise_to_none` uses the same entries and asserts the same set from both fetchers.
- `test_fetch_hosts_still_raises_when_every_entry_normalises_to_none` — REDUNDANT: `test_sync_job_still_rejects_a_list_with_no_usable_host` asserts the same error on the same payload.

Counts: DURABLE 0, REPLACES 0, COMBINE 0, REDUNDANT 7, SPENT 11 (by function; parametrised cases counted once).

## Proposed group map change

Add `test_host_normalisation.py` (created by this build in Phase 1, currently unmapped): `engine/server/data/moderation.py`, `engine/crawler/src/host-filters.ts`, `engine/crawler/dist/host-filters.js`, `engine/server/db/jobs/sync-whitelist.py`, `engine/server/db/jobs/updater-worker.py`, `tests/active/host_tokens.json`. Not `engine/server/db/whitelist.db`, which `--suggest-map` offers: the tests use a tmp_path database and only reference that path through the job's default.
