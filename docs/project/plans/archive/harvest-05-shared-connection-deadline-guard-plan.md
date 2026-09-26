# Harvest: plan 05, shared-connection deadline guard

## Resolved paths (from `--show-config`, 2026-09-26)

- `project_dir`: `/home/enduser/code/PeerTube-browser`
- `active`: `tests/active`
- `working`: `tests/tmp`
- `plans`: `docs/project/plans`
- `delete_me`: `delete_me`
- `archive`: `tests/archive`
- `record`: `tests/last_test_validation.json`

Bootstrap gate clear: `defaulted` and `conflicts` empty.

## Scope

From `docs/project/plans/05-shared-connection-deadline-guard.md`:

- `tests/tmp/test_statement_deadline.py`

Also in `tests/tmp` from this build and not a test file: `tests/tmp/probe_old_deadline.py`, the Step 7.2 probe. It is disposed at Step 7 with the scope.

## Snapshot

`tests/last_test_validation.json.preharvest` taken before any harvest run. The record holds no groups and no tests: `tests/active` has never held a test.

## Inventory

### `tests/tmp/test_statement_deadline.py`

- **Drives:** `engine/server/data/db.py` — `connect_db`, `statement_deadline`, `is_interrupted_error`.
- **Tests:** `test_a_deadline_entered_and_left_mid_statement_returns_at_once`, `test_a_passed_deadline_interrupts_its_own_thread_and_not_another`.
- **Module-level dependencies:** `SERVER_DIR` and its `sys.path` insert; `_SERIES`, `BOUNDED`, `BOUNDED_COUNT`, `UNBOUNDED`; `_C1_CHILD` (the child script for the first test).
- Collects: 2 tests.

## Classification

### `test_a_deadline_entered_and_left_mid_statement_returns_at_once`

**DURABLE.** No test in `tests/active` asserts anything about `data/db.py`. This is the only guard against the process-wide deadlock coming back, e.g. through a later per-request `set_progress_handler`.

### `test_a_passed_deadline_interrupts_its_own_thread_and_not_another`

**DURABLE.** No `active` test asserts that the deadline is scoped to a thread. It is the only check that one request's budget cannot cancel another request's statement.

### Subject file to create

`tests/active/test_db.py`, named for `engine/server/data/db.py`. New group; map entry `"test_db.py": ["engine/server/data/db.py"]` (keys are relative to `tests/active`; first written with the `tests/active/` prefix, which `--audit-map` passed but `map_health` flagged, and corrected 2026-09-26).

## Approval

Operator approved the plan as presented, 2026-09-26.

## Applied

- Both tests copied whole, with their constants and child script, into the new `tests/active/test_db.py`. The module docstring was rewritten from the plan/phase reference to the two rules the tests gate.
- `test_groups` gained `"test_db.py": ["engine/server/data/db.py"]` (keys are relative to `tests/active`; first written with the `tests/active/` prefix, which `--audit-map` passed but `map_health` flagged, and corrected 2026-09-26). `--audit-map`: exit 0, "every group's entry accounts for what its test file names".
- Nothing retired; `tests/archive` untouched.

## Mutations

### `test_a_deadline_entered_and_left_mid_statement_returns_at_once`

Rule: entering a deadline never waits on another thread's statement. Mutation: `install_deadline_handler` recorded each connection, and `statement_deadline` re-installed the handler on every recorded connection at entry (the per-request install). Felled the named assertion: `Failed: the child never exited: entering the deadline waited on the other thread's statement and the process deadlocked` after the 30s timeout. Restored from the copy, `diff` clean, green again (1 passed).

### `test_a_passed_deadline_interrupts_its_own_thread_and_not_another`

Rule: a deadline is scoped to the thread that set it. Mutation: `_deadline = threading.local()` replaced by one shared object. Felled the named assertion at `test_db.py:137`: `assert 'interrupted' == 216000000`. Restored from the copy, `diff` clean, green again (1 passed).

No `.bak` remains under `engine/server/data/`.

## Disposed

Moved to `delete_me/`: `test_statement_deadline.py`, `probe_old_deadline.py`, and the two mutation backups `db.py.bak`, `db.py.bak-mutation2`. `tests/tmp` holds only `__pycache__`.

## Final run

Snapshot restored before the run. `validate_tests.py --compare`, no tier: `test_db.py` 2 passed, exit 0. `--compare` reported no prior record to compare against — the pre-harvest record had no groups — so every result is new. Appearances: 2 (the harvested tests). Departures: 0. Matches the harvest.
