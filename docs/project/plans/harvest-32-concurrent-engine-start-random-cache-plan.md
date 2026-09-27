# Harvest — 32 concurrent engine start / random cache

## Resolved paths (from `--show-config`, bootstrap gate clear: `defaulted` [], `conflicts` [])

- project_dir: /home/enduser/code/PeerTube-browser/.worktrees/32
- active: tests/active
- working: tests/tmp
- plans: docs/project/plans
- delete_me: delete_me
- archive: tests/archive
- record: tests/last_test_validation.json
- Snapshot: tests/last_test_validation.json.preharvest taken before any run (the pre-harvest record holds no `tests/tmp` node, so every harvested node should appear as new in `--compare`).

## Scope

- tests/tmp/test_32_concurrent_engine_start_random_cache_phase1.py
- tests/tmp/test_32_concurrent_engine_start_random_cache_phase2.py
- tests/tmp/test_32_concurrent_engine_start_random_cache_phase3.py

Out of scope (build probes, not named in the scope list, left in tests/tmp): probe_32_lock.py, probe_32_long_wait.py, probe_32_orphans.py, probe_32_phase2.py, probe_32_phase3.py, probe_cache_size.py, probe_lock_premises.py.

## Inventory

### tests/tmp/test_32_concurrent_engine_start_random_cache_phase1.py

- Drives: engine/server/data/random_cache.py (`connect_random_cache_db`, `ensure_random_cache_schema`, `populate_random_cache`), in-process on tmp_path sqlite files.
- Tests: `test_random_cache_connection_waits_longer_than_sqlite_default`, `test_rebuild_waits_for_a_write_lock_held_past_sqlite_default`.
- Depends on: sys.path insert of engine/server and engine/server/api; `_source_db`; constants `SQLITE_DEFAULT_BUSY_MS`, `SOURCE_ROWS`, `HOLD_SECONDS`, `STALE_ROWID`.

### tests/tmp/test_32_concurrent_engine_start_random_cache_phase2.py

- Drives: engine/server/data/random_cache.py (`populate_random_cache(..., reuse_non_empty=True)`).
- Tests: `test_refresh_off_reuses_a_short_cache_without_writing`, `test_refresh_off_builds_a_missing_or_empty_cache` (parametrized missing/empty).
- Depends on: same sys.path pattern; `_source_db` (identical to phase 1's); constants `SOURCE_ROWS`, `SEEDED_ROWS`.

### tests/tmp/test_32_concurrent_engine_start_random_cache_phase3.py

- Drives: engine/server/api/server.py (Engine start, real processes on the checkout's dataset and random-cache.db).
- Tests: `test_engines_starting_at_once_all_become_healthy`.
- Depends on: conftest `BRIDGE_TOKEN`, `ENGINE_PY`, `ENGINE_SERVER`, `ClientBackend`, `_free_port`, session fixture `engine`; `server_config.DEFAULT_RANDOM_CACHE_SIZE`; `_log_tail`; constants `RANDOM_CACHE_DB`, `ENGINE_COUNT`, `HEALTHY_WITHIN_SECONDS`, `STOP_WITHIN_SECONDS`, `LOG_TAIL_LINES`.

All three files collect (they were the build's gating checkpoints).

## Classification

No subject file for engine/server/data/random_cache.py exists in tests/active, and nothing in tests/active asserts on random_cache, busy_timeout or reuse_non_empty, so none of these can be REDUNDANT. Subject file to create: tests/active/test_random_cache.py (the plan's named file).

### test_random_cache_connection_waits_longer_than_sqlite_default

DURABLE — the only assertion that a random-cache connection's busy wait exceeds sqlite's 5 s default. → tests/active/test_random_cache.py

### test_rebuild_waits_for_a_write_lock_held_past_sqlite_default

DURABLE — the only assertion that a refresh rebuild waits out a held write lock and completes a full build. → tests/active/test_random_cache.py

### test_refresh_off_reuses_a_short_cache_without_writing

DURABLE — the only assertion that `reuse_non_empty=True` returns a short non-empty cache by count with no write. → tests/active/test_random_cache.py

### test_refresh_off_builds_a_missing_or_empty_cache

DURABLE — the only assertion that the reuse path still builds a missing or empty cache. → tests/active/test_random_cache.py

### test_engines_starting_at_once_all_become_healthy

DURABLE — the only gate on engine/server/api/server.py passing `reuse_non_empty=True` at start; the phase-2 tests stay green if server.py drops the keyword, and the conftest `engine` fixture hides it behind its flock and retries. → proposed tests/active/test_random_cache.py (plan's named file for phase 3; `test_server.py` is the Client backend's server.py), with engine/server/api/server.py added to that group's entry.

## Counts

DURABLE 5, REPLACES 0, COMBINE 0, REDUNDANT 0, SPENT 0. Retired: none.

## Proposed test_groups change

- Add `"test_random_cache.py": ["engine/server/data/random_cache.py", "engine/server/api/server.py"]`.
