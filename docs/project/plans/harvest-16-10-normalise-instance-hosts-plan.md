# Harvest: 16-10-normalise-instance-hosts

## Resolved paths (Step 1)

- project_dir: `/home/enduser/code/PeerTube-browser`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- config: `.un/skills/devsecops/config.json`
- Bootstrap gate: `defaulted` empty, `conflicts` empty. `map_health.unmapped_groups` = [`test_host_normalisation.py`]. The build deferred that entry to this harvest.

## Snapshot

- A `tests/last_test_validation.json.preharvest` was already on disk, left by an earlier pass: stamped 2026-09-26T20:14:42, 12 groups, no `test_host_normalisation.py`. With the operator's approval it was moved to `delete_me/last_test_validation.json.preharvest-stale`.
- A fresh snapshot of the current record (stamped 2026-09-26T19:42:03, 13 groups, exit 0, 87 tests) was then taken to `tests/last_test_validation.json.preharvest`.

## Scope

Taken from the plan `docs/project/plans/16-10-normalise-instance-hosts.md` and its record `16-10-normalise-instance-hosts.record.md`.

Checkpoints:
- `tests/tmp/test_10_normalise_instance_hosts_phase1.py`
- `tests/tmp/test_10_normalise_instance_hosts_phase2.py`
- `tests/tmp/test_10_normalise_instance_hosts_phase3.py`

Probes the build wrote. The plan's outcomes and refactor notes name them as this build's scratch. They are not `test_*.py` and hold nothing to harvest; they are in scope for disposal only:
- `tests/tmp/probe_host_token.py`
- `tests/tmp/probe_git_outside_worktree.py`
- `tests/tmp/probe_durable_host.py`
- `tests/tmp/probe_phase2_env.py`
- `tests/tmp/probe_phase2_harness.py`
- `tests/tmp/probe_phase3.py`
- `tests/tmp/probe_phase3_seams.py`

Out of scope: every `tests/tmp` file from builds 11 and 12 (`*_11_*`, `*_12_*`, `test_probe_*`).

## Inventory (Step 2)

All three checkpoints collected and ran red to green during the build, according to the build record. The durable subject is `tests/active/test_host_normalisation.py` (the build wrote it straight into active, and it is green in the record with 19 passed).

### tests/tmp/test_10_normalise_instance_hosts_phase1.py
- Drives: `engine/server/data/moderation.py` (`normalize_host_token`), plus the fixture `tests/active/host_tokens.json`.
- Module constants: `ROOT`, `SERVER_DIR`, `FIXTURE`, `PINNED` (15 hand-written pairs).
- Tests: `test_fixture_holds_exactly_the_pinned_pairs`, `test_normalize_host_token_returns_pinned_value` (15 cases).

### tests/tmp/test_10_normalise_instance_hosts_phase2.py
- Drives: `tests/active/test_host_normalisation.py -k crawler_dist` in a nested pytest (junit outcome and message), plus `engine/crawler/dist/host-filters.js` under node.
- Module constants and helpers: `PINNED`, `FIXTURE_PAIRS`, `NODE_SCRIPT`, `PATHS_PLUGIN`, `LOWERCASE_LINE`, `EXPORT_LINE`, `WRONG_HOST`, `_run_crawler_test`, `_git`, `_commit`, `_crawler_copy`, `_older_on_disk`, `_git_env`, `_path_with_only`, `_dist_outputs`.
- Tests: `test_crawler_dist_under_node_returns_pinned_values`, `test_durable_crawler_test_passes_on_this_tree`, `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input` (15 cases), `test_durable_crawler_test_fails_on_current_dist_with_one_wrong_value`, `test_durable_crawler_test_fails_loudly_without_node`, `test_durable_crawler_test_fails_loudly_when_dist_is_missing`, `test_durable_crawler_test_fails_loudly_when_src_committed_after_dist`, `test_durable_crawler_test_passes_when_dist_committed_after_src_though_older_on_disk`, `test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk`, `test_durable_crawler_test_fails_loudly_when_uncommitted_src_edit_is_newer_than_dist`, `test_durable_crawler_test_fails_loudly_when_dist_has_no_history_and_is_older`, `test_durable_crawler_test_fails_without_git`.

### tests/tmp/test_10_normalise_instance_hosts_phase3.py
- Drives: `engine/server/db/jobs/sync-whitelist.py` (`fetch_hosts`, `ensure_whitelist_schema`, `sync_hosts`) and `engine/server/db/jobs/updater-worker.py` (`fetch_join_hosts`).
- Module constants and helpers: `ROOT`, `JOBS_DIR`, `DROPPED`, `_load`, `jobs` fixture, `_serve`.
- Tests: `test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row`, `test_both_fetchers_drop_entries_that_normalise_to_none`, `test_fetch_hosts_still_raises_when_every_entry_normalises_to_none`.

## Classification (Step 3)

Subject file for all three production scripts: `tests/active/test_host_normalisation.py`.

### phase1
- `test_fixture_holds_exactly_the_pinned_pairs`: **REDUNDANT**. It holds the fixture to a second hand-written copy, which guarded the build against writing the fixture to fit the port. In active, `test_crawler_dist_returns_pinned_values` already holds every fixture pair to the crawler's real output, so a fixture drifting to match a broken port goes red there without a lockstep copy.
- `test_normalize_host_token_returns_pinned_value` (15): **REDUNDANT**. The same 15 inputs and expected values are asserted by active `test_python_port_returns_pinned_value`, which is parametrised over the fixture.

### phase2
- `test_crawler_dist_under_node_returns_pinned_values`: **REDUNDANT**. Active `test_crawler_dist_returns_pinned_values` runs the same dist under node against the same fixture.
- `test_durable_crawler_test_passes_on_this_tree`: **SPENT**. This asserts that an active test passes, which every suite run already observes directly.
- `test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input` (15), `..._fails_on_current_dist_with_one_wrong_value`, `..._fails_loudly_without_node`, `..._fails_loudly_when_dist_is_missing`, `..._fails_loudly_when_src_committed_after_dist`, `..._passes_when_dist_committed_after_src_though_older_on_disk`, `..._passes_when_dist_committed_with_clean_src_though_older_on_disk`, `..._fails_loudly_when_uncommitted_src_edit_is_newer_than_dist`, `..._fails_loudly_when_dist_has_no_history_and_is_older`, `..._fails_without_git`: **SPENT**. These tests exercise a test file (`tests/active/test_host_normalisation.py`) and its `_dist_is_stale` gate, not a production script. They proved the gating test could discriminate while the build ran. `active` binds one production script to one subject file, and none of these has a production subject to live in.

### phase3
- `test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row`: **REDUNDANT**. Active `test_sync_job_stores_one_spelling_per_host` has the same payload and asserts the same set, `(1, 0, 1)`, and the same row.
- `test_both_fetchers_drop_entries_that_normalise_to_none`: **REDUNDANT**. Active `test_jobs_drop_entries_that_normalise_to_none` has the same six entries and the same two assertions.
- `test_fetch_hosts_still_raises_when_every_entry_normalises_to_none`: **REDUNDANT**. Active `test_sync_job_still_rejects_a_list_with_no_usable_host` has the same payload and the same anchored message.

### Totals
Test functions (parametrised cases in brackets): 17 functions (45 cases).
- DURABLE 0
- REPLACES 0
- COMBINE 0
- REDUNDANT 6 functions (20 cases)
- SPENT 11 functions (25 cases)

## Map change proposed (Step 5.c)

Add the entry the build deferred to harvest (plan impact on `.un/skills/devsecops/config.json`):

```
"test_host_normalisation.py": [
  "engine/server/data/moderation.py",
  "engine/server/db/jobs/sync-whitelist.py",
  "engine/server/db/jobs/updater-worker.py",
  "engine/crawler/src/host-filters.ts",
  "engine/crawler/dist/host-filters.js",
  "tests/active/host_tokens.json"
]
```

`host_tokens.json` is a test-tree file that only this group drives, as its spec, so the group claims it. `host-filters.ts` is claimed because the test's staleness gate reads it.

## Approval (Step 4)

The operator approved the plan as written: the phase-2 meta-tests are SPENT, the map entry is added, and all 10 files go to delete_me/.

## Applied (Step 5)

- No test moved into active and no active test was retired, because no DURABLE, REPLACES or COMBINE verdicts were given.
- `test_groups` gained the `test_host_normalisation.py` entry above.
- `--audit-map` exited 0 with no MISSING findings. It gave advisory UNRESOLVABLE findings for the hyphenated job files and the paths built from strings.

## Mutation (Step 6)

Nothing to verify: no test was moved into a subject file, and no `.bak` copy was made.

## Disposal (Step 7)

Moved to `delete_me/`, with no name collisions: test_10_normalise_instance_hosts_phase1.py, _phase2.py, _phase3.py, probe_host_token.py, probe_git_outside_worktree.py, probe_durable_host.py, probe_phase2_env.py, probe_phase2_harness.py, probe_phase3.py, probe_phase3_seams.py. Also there: `last_test_validation.json.preharvest-stale`, the stale snapshot from Step 1. `tests/tmp` still holds only files from builds 11 and 12.

## Suite (Step 8)

The snapshot was restored, then `validate_tests.py --compare` was run with no tier named. It exited 1.
- Selected 11 of 13 groups as changed. Only `test_host_normalisation.py` changed because of this harvest (its map entry). The other 10 changed because production files such as server.py and similar.py have moved since the 19:42 record, from the merges of builds 11 and 12.
- `test_host_normalisation.py`: 19 passed.
- Result: 28 passed, 2 failed, 53 errors. Every red is environmental. `engine/.pixi` and `client/frontend/node_modules` in the main tree are symlinks to themselves, both created at 20:23 and pointing at their own absolute path. So `engine/.pixi/envs/default/bin/python` and `node_modules/.bin/esbuild` raise ELOOP ("Too many levels of symbolic links"), and every Engine-backed and frontend-bundle test errors at fixture setup.
- `--compare`: no test appeared or departed, as expected with nothing moved. It lists 55 new reds, all from the ELOOP breakage above. None is in the harvested subject.
- Gate 1 is open: the suite is not green, and the reds need the operator's acceptance or an environment fix followed by a re-run.
