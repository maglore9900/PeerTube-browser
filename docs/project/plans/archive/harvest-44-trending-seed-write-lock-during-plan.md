# Harvest plan: 44 trending seed write lock during (build 47-44)

Workflow: `.un/skills/devsecops/workflows/harvest.md`. Steps 1 to 3 are done and Step 4 is presented below, awaiting the operator's approval. Nothing has moved and the map is unchanged.

Build: `docs/project/plans/47-44-trending-seed-write-lock-during.md`. Unlike build 46-45, this build promoted nothing into `tests/active`: each phase left its checkpoint only in `tests/tmp`.

## Step 1: resolved paths and scope

Bootstrap gate: clear. `--show-config` reports `defaulted` as `[]` and `conflicts` as `[]`, so no questions were needed.

| Key | Value |
|---|---|
| project_dir | `/home/enduser/code/PeerTube-browser/` |
| config source | `tests/config.json` |
| active | `tests/active` |
| working | `tests/tmp` |
| plans | `docs/project/plans` |
| delete_me | `delete_me` |
| archive | `tests/archive` |
| record | `tests/last_test_validation.json` |
| archive topic for this harvest | `tests/archive/44_trending_seed_write_lock_during/` (not created, because no verdict retires an active test) |

Record snapshot: `tests/last_test_validation.json.preharvest` was taken with `cp -n` before anything else ran, and `cmp` confirmed it identical to the record. Step 8 restores it. Note that the record already holds the build's own checkpoint and probe runs, as the phase 1 hand-in said. The snapshot is the record as it stood at harvest start.

Pre-harvest map health: `map_health.unmapped_groups` is `["test_search_fusion.py"]`. That predates this build and is outside this harvest's scope.

### Scope

These are the tests this build wrote in `tests/tmp`:
- `tests/tmp/test_44_trending_seed_write_lock_during_phase1.py`
- `tests/tmp/test_44_trending_seed_write_lock_during_phase2.py`
- `tests/tmp/test_44_trending_seed_write_lock_during_phase3.py`

Non-test leftovers in `tests/tmp` are not classified. They are kept for Step 7 disposal and listed under "Disposal list" at the end.

Collection: all three files collect, 4 items (2 + 1 + 1). This was checked with `python3 -m pytest -p no:cacheprovider --collect-only`, which banks nothing.

## Step 2: inventory

### tests/tmp/test_44_trending_seed_write_lock_during_phase1.py
Production drive:
- `engine/server/data/trending.py`: `prepare_trending_override` and `attach_trending_override`, in-process.
- `engine/server/data/random_videos.py`: `fetch_ordered_page` and `fetch_popular_videos`, on the prepared and unprepared connections.

Module fixtures and constants:
- `harness`, which is `tests/active/test_random_videos.py` loaded by path. From it the tests use `_schema`, `_ranks_db`, `_plan`, `_trending_labels`, `RANKS` and `TRENDING_EXPECTED`.
- `OVERRIDE_EXPECTED` (`TRENDING_EXPECTED` reversed) and `OVERRIDE_UNSERVED`.
- `_private_file`, which touches a file and runs `prepare_trending_override` on it.
- `_prepared`, which connects and runs `attach_trending_override`.
- `_catalogue`: 30×100 ranked catalogue rows plus 1,000 unranked rows.
- `_catalogue_ranks`: the ranks for that catalogue.
- The `compute_ann_id` import.

Tests:
- `test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`
- `test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`

### tests/tmp/test_44_trending_seed_write_lock_during_phase2.py
Production drive: `engine/server/api/server.py` `--trending-db`, run as a subprocess under the Engine interpreter. The check behind it is `engine/server/data/trending.py` `prepare_trending_override`.

Module fixtures and constants:
- `harness`, which is `tests/active/test_server_config.py` loaded by path. From it the test uses `_run`, `_free_port`, `_has_started`, `ENGINE_PY`, `API_DIR`, `ENGINE_START_LOCK` and `VARIANT_START_SECONDS`.
- `SERVER_PY`.
- `JUNK`: 4 KB of non-SQLite bytes.
- `_argv`, `_start` and `_starts_serving`. `_starts_serving` takes the Engine start lock, waits for the `service.lifecycle` start, then terminates.
- An `ACTIVE_DIR` `sys.path` insert, needed only because the file is outside `tests/active`.

Tests:
- `test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`

### tests/tmp/test_44_trending_seed_write_lock_during_phase3.py
Production drive: the live session Engine over HTTP, started by `tests/active/conftest.py` `engine` with `--trending-db <trending_seed>`. Through it the test exercises:
- `engine/server/api/server.py`: the `attach_trending_override` wiring in `main()`.
- `engine/server/api/handlers/similar.py`: `mode=trending` pages, and the popular layer of an unseeded `/recommendations`.
- `engine/server/api/recommendations/candidates/popular_videos.py`, through that popular layer.
- `engine/server/data/random_videos.py`: `fetch_popular_videos` and `fetch_ordered_page`, through the Engine and as the reference.

Module fixtures and constants:
- From conftest: the `engine`, `dataset`, `trending_seed` and `shared_trending_before` fixtures, plus `shared_trending_fingerprint` and `WHITELIST_DB`.
- `harness`, which is `tests/active/test_similar.py` loaded by path. From it the test uses `_reference`, `_post`, `_exclude`, `_keys`, `_default_limit`, `FEED_PAGE`, `FEED_CONSTANTS` and `FEED_CONSTANTS_ERROR`.
- `POOL_KEY`.
- `TRENDING_HEADERS` (192.0.2.180) and `POPULAR_HEADERS` (192.0.2.181). No file in `tests/active` uses either address.
- `_shared`: the shared table's Trending reference and popular pool, read on a fresh plain `mode=ro` connection.
- A `hasattr` guard and `request.getfixturevalue` ordering, both build-time scaffolding.

Tests:
- `test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged`

## Step 3: classification

Production and active facts relied on:
- `tests/active/test_random_videos.py` asserts the Trending order, the pool and the plan only on main's own `trending_ranks`. Nothing in `tests/active` calls `attach_trending_override` or `prepare_trending_override`, except `conftest.py` building fixtures.
- `tests/active/test_server_config.py` has no `--trending-db` test. Its entry-point test (`test_server_py_exits_before_argument_parsing_on_a_bad_value`) covers a different rule.
- `tests/active/test_similar.py::test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` compares the Engine's Trending pages with `_reference(dataset, ...)`. `dataset` now reads the private seed. That test has no control showing the shared table differs from the seed. It does not read the popular layer, and it does not check the shared fingerprint.
- No active test reads the live Engine's `debug.layer == "popular"` rows against a pool. `test_popular_videos.py`'s mix test is in-process, on a temp DB.

### Phase 1 → subject `engine/server/data/trending.py` + `random_videos.py` → `tests/active/test_random_videos.py`

#### test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it
DURABLE → `tests/active/test_random_videos.py`.

Reason: no active test asserts what this one does:
- that a connection prepared by `attach_trending_override` serves the attached file's ranks from both `fetch_ordered_page("trending")` and `fetch_popular_videos`;
- that a plain connection on the same main still serves main's ranks;
- that main's ranks are left unchanged.

Move note:
- It uses the file's own `_ranks_db`, `RANKS`, `TRENDING_EXPECTED` and `_trending_labels` directly, not the by-path `harness`.
- It carries `OVERRIDE_EXPECTED`, `OVERRIDE_UNSERVED`, `_private_file` and `_prepared`.
- It imports `trending` from `data`. The file today imports only `ensure_trending_schema`.

#### test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting
DURABLE → `tests/active/test_random_videos.py`.

Reason: `test_a_trending_page_walks_the_ranks_index_without_sorting` plans the query against main's ranks. Nothing asserts that the TEMP VIEW over an attached file still plans as a walk of `idx_trending_ranks_order` with no `TEMP B-TREE`. The control that main's ranks are empty, so the page can only come from the file, is also new.

Move note:
- It carries `_catalogue` and `_catalogue_ranks`, and uses the file's own `_schema` and `_plan`.
- The existing unflagged plan test builds the same catalogue inline. The proposal is to have it call `_catalogue(conn)` then `_catalogue_ranks(conn)` instead of carrying a second copy of the builder. This is an extract-only refactor of an active test: its assertions are unchanged, and only the insert order of the same rows changes. Leave this out if the operator prefers that test byte-unchanged.

### Phase 2 → subject `engine/server/api/server.py` → `tests/active/test_server_config.py`

#### test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it
DURABLE → `tests/active/test_server_config.py`.

Reason: no active test asserts any of the following:
- `--trending-db` is accepted;
- a missing path or a non-SQLite file stops the start, non-zero, naming the path, with nothing created and nothing written;
- an existing SQLite file gets past the check.

Move note:
- It uses the file's own `_run`, `_free_port`, `_has_started`, `ENGINE_PY`, `API_DIR`, `ENGINE_START_LOCK` and `VARIANT_START_SECONDS` directly.
- It carries `SERVER_PY` (or reuses the file's own if it has one), `JUNK`, `_argv`, `_start` and `_starts_serving`, plus the `fcntl`, `sqlite3` and `time` imports where the file lacks them.
- The `ACTIVE_DIR` `sys.path` insert and the by-path harness load are dropped.

### Phase 3 → subject: the session Engine's Trending and popular layer (`similar.py`, `server.py` `--trending-db`) → `tests/active/test_similar.py`

#### test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged
DURABLE → `tests/active/test_similar.py`.

Reason, against the active ordered-mode test `[trending]`, which only overlaps it:
- That test's Engine-equals-`_reference(dataset)` check would still pass if the seed were written into the shared table and both sides read it. This test's control asserts that the shared head differs from the private one.
- Nothing in active asserts that live popular-layer rows come from the private pool.
- Nothing in active asserts that the shared `whitelist.db` `trending_ranks` fingerprint is unchanged after the Engine has served. That is the suite's guarantee not to write the operator's DB, the rule this build was for.

It is not a COMBINE: the ordered test is parametrized over every ordered mode, and these controls are Trending-only.

Move note:
- In `tests/active` it takes `shared_trending_before`, `engine` and `dataset` as plain fixture arguments. `trending_seed` already depends on `shared_trending_before`, so the fingerprint is read first without `request.getfixturevalue`.
- The `hasattr(conftest, "shared_trending_before")` guard and the explicit fixture imports are dropped.
- It imports `shared_trending_fingerprint` and `WHITELIST_DB` from `conftest`, which `test_similar.py` already imports from.
- It uses the file's own `_reference`, `_post`, `_exclude`, `_keys`, `_default_limit`, `FEED_PAGE`, `FEED_CONSTANTS` and `FEED_CONSTANTS_ERROR`.
- It carries `POOL_KEY`, `TRENDING_HEADERS`, `POPULAR_HEADERS` and `_shared`, plus `fetch_popular_videos` from `data.random_videos`.
- The docstring's "Observed" comments stay. Clause tags (`# C1`, `# C2`) are replaced by the rule each line gates.

Risk to record:
- The discrimination control depends on the live shared table holding a real fill (`fetched_at > 0`) whose head differs from the seed's.
- An updater trending-stage run during the suite moves the fingerprint, which goes red. The failure message names that cause.

### Verdict counts (4 test functions in scope)

| Verdict | Count |
|---|---|
| DURABLE | 4 (phase1 2, phase2 1, phase3 1) |
| REPLACES | 0 |
| COMBINE | 0 |
| REDUNDANT | 0 |
| SPENT | 0 |

### Active tests that would be retired
None. No active test is moved to `tests/archive/`, and none is renamed. The only edit to an existing active test is the optional extract-only refactor of `test_random_videos.py::test_a_trending_page_walks_the_ranks_index_without_sorting`, which would use the shared `_catalogue`/`_catalogue_ranks` builder.

### test_groups changes (Step 5.c, after approval)
- EXTEND `test_server_config.py` with `engine/server/data/trending.py`. The moved test asserts the missing/non-SQLite refusal and the no-create rule, which `prepare_trending_override` implements. This is the addition phase 2 deferred to promotion.
- EXTEND `test_similar.py` with `engine/server/api/recommendations/candidates/popular_videos.py`. The moved test asserts which rows the live popular layer serves, and that generator draws them. Drop this if the operator reads it as the mixer's concern, already claimed through `mixer.py`.
- No change to `test_random_videos.py`: it already claims `random_videos.py` and `trending.py`.
- `tests/active/conftest.py` stays unclaimed. It is a shared helper, even though the phase 3 test gates its no-write rule.

### New subject file
None.

## Step 4: plan approved

The operator approved all 4 DURABLE moves and their destinations. On the two optional items they approved both: the extract-only refactor of `test_a_trending_page_walks_the_ranks_index_without_sorting` onto `_catalogue`/`_catalogue_ranks`, and adding `popular_videos.py` to the `test_similar.py` group.

## Step 5: applied

- `tests/active/test_random_videos.py`: added `_catalogue`, `_catalogue_ranks`, `OVERRIDE_EXPECTED`, `OVERRIDE_UNSERVED`, `_private_file`, `_prepared` and the two phase 1 tests, with two module docstring bullets. The import is now `from data.trending import attach_trending_override, ensure_trending_schema, prepare_trending_override`. The existing plan test calls `_catalogue(conn)` then `_catalogue_ranks(conn)`, and its assertions are unchanged.
- `tests/active/test_server_config.py`: added `import sqlite3`, `SERVER_PY`, `JUNK`, `_argv`, `_start`, `_starts_serving` and the phase 2 test, with a docstring section. The by-path harness and the `sys.path` insert were dropped.
- `tests/active/test_similar.py`: added `WHITELIST_DB` and `shared_trending_fingerprint` to the conftest import, `fetch_popular_videos` to the `data.random_videos` import, `POOL_KEY`, `TRENDING_HEADERS`, `POPULAR_HEADERS`, `_shared` and the phase 3 test, which takes `shared_trending_before, engine, dataset` as plain fixtures. A docstring section was added. The `hasattr` guard and the `getfixturevalue` ordering were dropped.
- Clause tags (`# C1`/`# C2`) were replaced by the rule each line gates.
- `tests/config.json`: `test_server_config.py` += `engine/server/data/trending.py`; `test_similar.py` += `engine/server/api/recommendations/candidates/popular_videos.py`.
- `--audit-map` exit 0. No MISSING finding names a file the moved tests drive. The `time.py` and `tmp/suite28` findings predate this harvest.
- Retired: none.

## Step 6: mutations (`.preharvest` confirmed on disk before the first run)

Every backup was restored with `cp`, proved identical with `diff`, and moved to `delete_me/`. A `sleep 1` + `touch` came before each run.

- `test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`, m1: `trending.py` `attach_trending_override` without its `CREATE TEMP VIEW`. Red at `fetch_ordered_page(prepared, "trending") == OVERRIDE_EXPECTED` ('C1' != 'B5' at index 0). Green after restore.
- `test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`, m2: the view as `SELECT DISTINCT *`, which is not flattened. The full-page and Popular-sort controls held. Red at `any("idx_trending_ranks_order" in detail ...)`: the plan was `CO-ROUTINE trending_ranks`, `SCAN trending_override.trending_ranks`, `SCAN t`. Green after restore.
- `test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`, m3: `prepare_trending_override`'s `SystemExit` message without `{path}`. Red at `str(missing) in run.stderr` (stderr `trending ranks file cannot be opened as SQLite: unable to open database file`). Green after restore. I did not use `mode=rwc`: that start gets through and serves until `_run`'s 120 s timeout, which is the hanging kind of mutation.
- `test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged`, m4: `server.py` `main()` skips `attach_trending_override(db, args.trending_db)`, so the Engine reads the shared table without writing it. All controls held. Red at `first + second + third == reference[: 3 * FEED_PAGE]` (index 1 differs). Green after restore, with the fingerprint assertion passing.

No `.bak` from this harvest is left under the production tree.

## Step 7: disposed

All 13 entries moved with `mv -n` to `delete_me/`, with no collisions: the 3 `test_44_*` checkpoints, the 9 `probe_*.py` files, and `tests/tmp/__pycache__` as `__pycache__-harvest44`. The 4 mutation backups (`trending.py.bak-harvest44-m1..m3`, `server.py.bak-harvest44-m4`) are also there. `tests/tmp` holds 0 entries, and `delete_me/` holds 120 (103 before).

## Step 8: compare

Snapshot restored with `mv`, then `validate_tests.py --compare`, exit 0. It selected 4 of 59 groups (`test_random_videos.py`, `test_server_config.py` and `test_similar.py` changed, plus the unmapped `test_search_fusion.py`) and carried 55 forward unchanged. 175 passed, 0 failed. Moved against the pre-harvest record: 4 appeared (the 4 harvested tests), 0 gone, no new red, nothing newly green.

## Notes for Steps 5-8 (known project traps, carried from harvest 45)
- `delete_me/` already holds earlier `.bak` files. Use `mv -n`, and give every Step 6 backup a unique name such as `trending.py.bak-harvest44-m1`.
- A same-length mutation restored within the same second reuses the stale `.pyc`. Run `sleep 1` and `touch` before each mutation and after each restore.
- Step 6 runs one file and one `-k` at a time, because Engine-backed files share one Engine and its 60/min rate limit.
- `test_similar.py` has known intermittent reds (Engine 500). Re-run once before diagnosing a red there.
- Phase 1's two tests both mutate `trending.py` or `random_videos.py`, so run them one at a time with distinct `.bak` suffixes. Candidate mutations:
  - (a) `attach_trending_override` without the TEMP VIEW;
  - (b) the view as `SELECT * FROM (SELECT * FROM trending_override.trending_ranks ORDER BY 1)`, or another index-defeating form.
- Phase 2 candidate mutation: `prepare_trending_override` without `mode=rw`, which creates the missing file.
- Phase 3 candidate mutation: `server.py` skips `attach_trending_override`, so Trending and popular are read from the shared table. Any mutation must leave `whitelist.db` unwritten.

## Disposal list (Step 7, to `delete_me/`; nothing here collides with what is there today)
Checkpoints:
- `tests/tmp/test_44_trending_seed_write_lock_during_phase1.py`
- `tests/tmp/test_44_trending_seed_write_lock_during_phase2.py`
- `tests/tmp/test_44_trending_seed_write_lock_during_phase3.py`

Non-test leftovers:
- `tests/tmp/probe_override.py`, `probe_override_plan.py`
- `tests/tmp/probe_phase3_engine_popular.py`, `probe_phase3_fingerprint.py`, `probe_phase3_shared_vs_private.py`, `probe_phase3_unflagged_engine.py`
- `tests/tmp/probe_private_seed.py` (empty)
- `tests/tmp/probe_trending_db_flag.py`, `probe_valid_start.py`
- `tests/tmp/__pycache__/` → `delete_me/__pycache__-harvest44`

That is 13 entries; `tests/tmp` is empty afterwards.
