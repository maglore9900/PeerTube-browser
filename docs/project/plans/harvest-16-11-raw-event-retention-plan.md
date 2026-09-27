# Harvest: 16-11 raw-event retention

Scope argument: `docs/project/plans/archive/16-11-raw-event-retention.md` (build plan 16-11, closed and merged to main).

## Step 1: resolved paths

- project_dir: `/home/enduser/code/PeerTube-browser`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive` (does not exist yet; created on first retirement)
- record: `tests/last_test_validation.json`
- bootstrap gate: clear (`defaulted` empty, `conflicts` empty)

Snapshot: `tests/last_test_validation.json.preharvest` taken before any harvest run (record timestamp 2026-09-26T22:18:57, exit 1, 107 passed / 12 failed).

Pre-existing red in the snapshot: 12 frontend tests (`test_frontend_blocks` x2, `test_frontend_profile` x2, `test_frontend_reactions` x7, `test_frontend_videos` x1) failed with `OSError: [Errno 40] Too many levels of symbolic links: client/frontend/node_modules/.bin/esbuild`. `client/frontend/node_modules` was rebuilt as a real directory at 22:21, after that run (memory `worktree-symlinks-committed-deleted-node-modules`), and `esbuild --version` now answers 0.21.5. Step 8 expects these 12 to go green and accounts for them by that repair, not by this harvest.

### Scope

The plan records its test files in its phase checkpoints:

- `tests/tmp/test_11_raw_event_retention_phase1.py`
- `tests/tmp/test_11_raw_event_retention_phase2.py`
- `tests/tmp/test_11_raw_event_retention_phase3.py`
- `tests/tmp/test_11_raw_event_retention_phase4.py`

Build-11 probe files (all 0 bytes, not `test_*.py`, never collected), proposed for disposal alongside the scope, pending approval at Step 4:
`probe_11_payload_only.py`, `probe_11_phase2_env.py`, `probe_11_phase3_failures.py`, `probe_11_phase3_handler.py`, `probe_11_phase4_sentinel.py`, `probe_11_phase4_similar.py`, `probe_11_prune_sqlite.py`, `probe_retention_import_origin.py`.

## Step 2: inventory

All four files collect and pass on main (phase1 5 passed, phase2 9 passed, phase3 8 passed, phase4 3 passed).

### tests/tmp/test_11_raw_event_retention_phase1.py

- Drives: `engine/server/data/interaction_events.py` (`prune_interaction_raw_events`, `ensure_interaction_event_schema`, `ingest_interaction_event`).
- Module deps: sys.path setup for `engine/server` and `engine/server/api`; `DAY_MS`, `STRIPPED`, `UNSTRIPPED_INDEX`; helpers `_db`, `_insert_raw`, `_rows`, `_stripped`; class `_CountingLock`.
- Tests:
  - `test_a_31_day_row_is_stripped_of_actor_and_payload_only_and_a_29_day_row_is_untouched`
  - `test_the_cutoff_is_exclusive_and_a_row_holding_any_one_column_is_stripped`
  - `test_five_stale_rows_are_stripped_two_per_committed_lock_hold`
  - `test_a_stripped_event_replayed_is_still_a_duplicate_and_moves_no_signal`
  - `test_the_schema_creates_the_unstripped_index_and_the_prune_finds_its_rows_through_it`

### tests/tmp/test_11_raw_event_retention_phase2.py

- Drives: `engine/server/api/server_config.py` (`_resolve_positive_int_env`, `INTERACTION_RAW_RETENTION_DAYS`), and `engine/server/api/server.py` as the entry point that must stop.
- Module deps: `API_DIR`, `ENGINE_PY` (duplicate of `conftest.ENGINE_PY`), `VAR`, `PRINT_DAYS`; helpers `_run`, `_last_stderr_line`.
- Tests:
  - `test_a_positive_integer_becomes_the_constant_and_unset_gives_30` (params seven, one, unset)
  - `test_a_value_that_is_not_a_positive_integer_stops_the_import` (params abc, zero, negative, fraction, empty)
  - `test_server_py_exits_before_argument_parsing_on_a_bad_value`

### tests/tmp/test_11_raw_event_retention_phase3.py

- Drives: `engine/server/api/handlers/internal_events.py` (`handle_internal_events_ingest`, `_prune_raw_events_if_due`), plus `engine/server/api/server.py` (`SimilarServer.__init__`) in one test.
- Module deps: sys.path setup; `DAY_MS`, `STRIPPED`, `ENGINE_PY`, `RETENTION_VAR`, `ENGINE_INGEST` child script; helpers `_db`, `_server`, `_insert_raw`, `_rows`, `_stripped`, `_stripped_ids`, `_event`, `_ok_body`, `_post`, `_patch_prune`; class `_LockFailingInsideTheStrip`; arms `_interrupt_the_strip`, `_abort_the_strip`, `_fail_the_strips_lock`.
- Tests:
  - `test_the_first_ingest_strips_and_the_next_strip_waits_until_the_last_one_is_an_interval_old`
  - `test_the_strip_uses_the_servers_retention_days` (params 7, 9)
  - `test_the_engines_server_carries_the_env_retention_days_and_an_unset_last_strip` (params 7, 9)
  - `test_a_strip_that_raises_leaves_the_200_body_unchanged` (params interrupted, integrity-error, runtime-error)

### tests/tmp/test_11_raw_event_retention_phase4.py

- Drives: `engine/server/api/handlers/similar.py` (`_handle_similar_request`, `_recommendations_likes_payload_error`, `_parse_client_likes`).
- Module deps: `ENGINE_PY`, `LIKES_MAX`, `RESOLVED_LIKES`, `HANDLE_CASES` child script (imports `_DummySimilarHandler` from `engine/server/api/tests/test_recommendations_likes_limit.py`, outside `tests/active`); helpers `_handle`, `_likes`, `_rejected`. Written as a `unittest.TestCase` class `VideosSimilarLikesLimitTests`.
- Tests:
  - `test_videos_similar_rejects_more_likes_than_allowed`
  - `test_videos_similar_rejects_invalid_likes_item_format`
  - `test_videos_similar_allows_likes_at_limit`

## Step 3: classification

Nothing in `tests/active` touches the prune, the retention env var, the ingest handler, or likes validation on `/videos/similar` (searched `tests/active` for `interaction_events`, `internal_events`, `RETENTION`, `prune`, `likes`, `videos/similar`). `engine/server/api/tests/test_recommendations_likes_limit.py` is outside `active`, so it is not the durable suite, and it covers `/recommendations` only. Subject files `test_interaction_events.py`, `test_server_config.py` and `test_internal_events.py` do not exist in `active`, so their tests cannot be `REDUNDANT`, and Step 5 must create these files.

Counts: DURABLE 15, REPLACES 0, COMBINE 0, REDUNDANT 0, SPENT 0.

### → new `tests/active/test_interaction_events.py`

- `test_a_31_day_row_is_stripped_of_actor_and_payload_only_and_a_29_day_row_is_untouched`: **DURABLE**. The R1 strip boundary and kept columns are asserted nowhere in `active`.
- `test_the_cutoff_is_exclusive_and_a_row_holding_any_one_column_is_stripped`: **DURABLE**. It is the only test that pins the exclusive cutoff and the partial-row OR.
- `test_five_stale_rows_are_stripped_two_per_committed_lock_hold`: **DURABLE**. It is the only test of the R2 chunking and per-hold commit.
- `test_a_stripped_event_replayed_is_still_a_duplicate_and_moves_no_signal`: **DURABLE**. It covers R6 idempotency after a strip. `test_random_videos.py` ingests, but it never strips or replays.
- `test_the_schema_creates_the_unstripped_index_and_the_prune_finds_its_rows_through_it`: **DURABLE**. It is the only guard against the partial-index WHERE drifting from the query.

### → new `tests/active/test_server_config.py`

- `test_a_positive_integer_becomes_the_constant_and_unset_gives_30`: **DURABLE**. The R4 env parsing and default are untested elsewhere.
- `test_a_value_that_is_not_a_positive_integer_stops_the_import`: **DURABLE**. It is the R4 fail-closed rule.
- `test_server_py_exits_before_argument_parsing_on_a_bad_value`: **DURABLE**. It proves that the Engine entry point stops before argparse. The rule it gates is server_config's import-time validation, so it is filed with that subject, and the map entry names `engine/server/api/server.py` too.

### → new `tests/active/test_internal_events.py`

- `test_the_first_ingest_strips_and_the_next_strip_waits_until_the_last_one_is_an_interval_old`: **DURABLE**. It is the R5 hourly gate.
- `test_the_strip_uses_the_servers_retention_days`: **DURABLE**. The handler honours the server's window rather than a fixed one.
- `test_the_engines_server_carries_the_env_retention_days_and_an_unset_last_strip`: **DURABLE**. The real `SimilarServer` wiring of the env value and the first-ingest strip are asserted nowhere else.
- `test_a_strip_that_raises_leaves_the_200_body_unchanged`: **DURABLE**. A strip failure never reaches the ingest caller.

### → existing `tests/active/test_similar.py`

- `test_videos_similar_rejects_more_likes_than_allowed`: **DURABLE**. It is the R7 cap on `/videos/similar`. `active` only covers the `exclude` cap there.
- `test_videos_similar_rejects_invalid_likes_item_format`: **DURABLE**. It covers the R7 per-item 400 on `/videos/similar`.
- `test_videos_similar_allows_likes_at_limit`: **DURABLE**. At the limit, the request still reaches parse, resolve and handle.

Placement notes for Step 5:
- `test_similar.py` is not split, so there is no part choice.
- The phase-4 tests convert from `unittest.TestCase` methods to plain pytest functions, matching `test_similar.py`.
- `_DummySimilarHandler` is inlined into the child script, so the durable test no longer imports a test file outside `active`.
- Moved files use `conftest.ENGINE_PY` / `ROOT` instead of their own copies.
- Docstrings that name the build or phase are rewritten to state the rule.

## Step 4: approval

The operator approved the plan as presented. They also approved moving the 8 empty build-11 probe files to `delete_me/` along with the scope.

## Step 5: applied

- Created `tests/active/test_interaction_events.py` (5 phase-1 tests), `tests/active/test_server_config.py` (3 phase-2 tests) and `tests/active/test_internal_events.py` (4 phase-3 tests). They import `ENGINE_PY` and `ROOT` from `conftest` rather than keeping their own copies. Phase and clause markers (`# C1`, `# C2`) are dropped. Module docstrings state the rules.
- Extended `tests/active/test_similar.py` with the 3 phase-4 tests as pytest functions:
  - `test_videos_similar_rejects_more_likes_than_allowed_with_the_recommendations_400_body`
  - `test_videos_similar_rejects_a_malformed_likes_entry_with_the_recommendations_400_body` (the former subTests, now parametrised: blank-uuid, non-object-entry, non-string-host-after-two-valid)
  - `test_videos_similar_parses_resolves_and_handles_likes_at_the_limit`

  `_DummySimilarHandler` is inlined into the `_LIKES_CHILD` script, and `DEFAULT_CLIENT_LIKES_MAX` is read by exec'ing `server_config.py`, the same way `_default_limit()` does. The module docstring gains one bullet.
- Retired: none. `tests/archive` is not created.
- `test_groups`:
  - added `test_interaction_events.py` → `engine/server/data/interaction_events.py`
  - added `test_server_config.py` → `engine/server/api/server_config.py`, `engine/server/api/server.py`
  - added `test_internal_events.py` → `engine/server/api/handlers/internal_events.py`, `engine/server/data/interaction_events.py`, `engine/server/api/server.py`, `engine/server/api/server_config.py`
  - `test_similar.py` is unchanged, because it already claims `handlers/similar.py` and `server_config.py`.
- `--audit-map` exit 0. The advisories on the new files are not missing dependencies:
  - `UNRESOLVABLE test_server_config.py server.py` is the `API_DIR / "server.py"` literal, which the entry names in full.
  - `BARREN test_interaction_events.py` is the `data.*` package import that the static scan cannot follow; the entry is explicit.
  - The other MISSING, UNRESOLVABLE and BARREN lines are pre-existing and concern other groups.
- Each moved file ran green in its new home before mutation: 5, 9, 8, and 5 of `test_similar.py -k likes`.

## Step 6: mutations

Every mutation was made on a `.bak` copy, followed by `sleep 1; touch` (memory `mutation-restore-stale-pyc`). The test was run alone with `-k`. The file was then restored with `cp` and `diff` came back identical. After another `sleep 1; touch`, the same test ran green again. All `.bak` copies are now in `delete_me/`, and none is left under `engine/`.

| # | Test | Rule | Mutation (production file) | Assertion felled |
|---|---|---|---|---|
| M1 | `test_a_31_day_row_is_stripped_of_actor_and_payload_only_and_a_29_day_row_is_untouched` | the strip nulls only the three columns | SET also `canonical_url = NULL` (`data/interaction_events.py`) | `:84` `after["old"] == _stripped(before["old"])`, canonical_url None != url |
| M2 | `test_the_cutoff_is_exclusive_and_a_row_holding_any_one_column_is_stripped` | the cutoff is exclusive | `ingested_at < ?` → `<= ?` | `:102` `_rows(conn) == {...}`, the `at` row stripped |
| M3 | `test_five_stale_rows_are_stripped_two_per_committed_lock_hold` | at most `chunk_size` rows per lock hold | LIMIT bound to `chunk_size * 10` | `:124` `lock.entered == 4` (got 2) |
| M4 | `test_a_stripped_event_replayed_is_still_a_duplicate_and_moves_no_signal` | a replay of a stripped event is a duplicate | `ON CONFLICT(event_id) DO UPDATE SET actor_id = excluded.actor_id WHERE ... actor_id IS NULL` | `:150` `duplicate is True` (got False) |
| M5 | `test_the_schema_creates_the_unstripped_index_and_the_prune_finds_its_rows_through_it` | the prune WHERE matches the partial index | prune OR terms reordered | `:169` index in plan (plan became `SCAN interaction_raw_events`) |
| M6 | `test_a_positive_integer_becomes_the_constant_and_unset_gives_30` | the env value becomes the int constant | resolver returns `raw` (`api/server_config.py`) | `:41` stdout `'7'` != `7` (seven, one). The unset case is unaffected by this mutation and not separately mutated. |
| M7 | `test_a_value_that_is_not_a_positive_integer_stops_the_import` | a bad value stops the import instead of falling back | `raise SystemExit` → `return default` | `:49` `returncode == 1`, all 5 cases |
| M8 | `test_server_py_exits_before_argument_parsing_on_a_bad_value` | the Engine entry point stops on a bad value | `os.environ.pop(VAR)` before the `server_config` import (`api/server.py`) | `:61` `returncode == 1` (got 0, usage printed) |
| M9 | `test_the_first_ingest_strips_and_the_next_strip_waits_until_the_last_one_is_an_interval_old` | at most one strip per interval | interval guard → `if False` (`handlers/internal_events.py`) | `:130` `prune.call_count == 1` (got 2) |
| M10 | `test_the_strip_uses_the_servers_retention_days` | the handler uses the server's window | `days = INTERACTION_RAW_RETENTION_DAYS` | `:159` stale row not stripped, both params |
| M11 | `test_the_engines_server_carries_the_env_retention_days_and_an_unset_last_strip` | `SimilarServer` carries the env window | `self.raw_retention_days = 30` (`api/server.py`) | `:178` `report["server"]`, 30 != 7 / 9 |
| M12 | `test_a_strip_that_raises_leaves_the_200_body_unchanged` | a strip failure never changes the 200 body | first try: except narrowed to `OperationalError`. This felled integrity-error and runtime-error, but at `:234` by the exception escaping the handler, not at the named assertion, so the named assertion was treated as unverified. Second try (M12b): that plus the strip call moved inside the ingest `try`, so a failure becomes the 500 | M12b: `:236` `(500, {'error': 'strip failed'}) != (200, ok_body)`, integrity-error and runtime-error. The interrupted case survives by design, because the helper still catches `OperationalError`. |
| M13 | `test_videos_similar_rejects_more_likes_than_allowed_with_the_recommendations_400_body` | the likes cap applies to `/videos/similar` | gate reverted to `path != "/recommendations"` (`handlers/similar.py`) | `:310` `similar_report == expected` |
| M14 | `test_videos_similar_rejects_a_malformed_likes_entry_with_the_recommendations_400_body` | per-item 400 on `/videos/similar` | same gate revert | `:325` `similar_report == expected`, all 3 params |
| M15 | `test_videos_similar_parses_resolves_and_handles_likes_at_the_limit` | a list at the limit is served | `received <= max_items` → `<` | `:335` `report["respond"] == []` (got the 400) |

No mutation felled nothing. Nothing was reclassified REDUNDANT. `tests/last_test_validation.json.preharvest` is still on disk.

## Step 7: disposal

Moved to `delete_me/` with `mv -n` (checked first; no name collisions):
- Scope: `test_11_raw_event_retention_phase1.py`, `test_11_raw_event_retention_phase2.py`, `test_11_raw_event_retention_phase3.py`, `test_11_raw_event_retention_phase4.py`
- Approved probes: `probe_11_payload_only.py`, `probe_11_phase2_env.py`, `probe_11_phase3_failures.py`, `probe_11_phase3_handler.py`, `probe_11_phase4_sentinel.py`, `probe_11_phase4_similar.py`, `probe_11_prune_sqlite.py`, `probe_retention_import_origin.py`
- Mutation backups: `interaction_events.py.bak`, `server_config.py.bak`, `internal_events.py.bak`, `server.py.bak`, `similar.py.bak`

`tests/tmp` now holds only `__pycache__/`.

## Step 8: closing run

The snapshot was restored to `tests/last_test_validation.json`. Then a bare `validate_tests.py --compare` exited 0. It selected 8 of 16 groups:
- the 4 frontend groups, not green in the snapshot;
- the 3 new groups, which had no record;
- `test_similar.py`, which had changed.

The other 8 groups were unchanged and green, so they were carried forward.

- Banked: 146 passed, 0 failed. Before the harvest: 107 passed, 12 failed = 119. Delta: +27 appeared, 0 gone.
- Appeared, 27, matching the harvest exactly: `test_interaction_events` 5, `test_internal_events` 8, `test_server_config` 9, `test_similar` 5.
- Gone: none, as expected, since nothing was retired.
- New red: none.
- No longer red: 12 frontend tests. These are the snapshot's `esbuild` symlink-loop failures. They went green because `client/frontend/node_modules` was rebuilt at 22:21, after the snapshot's 22:18 run. This harvest did not cause it, and no test was weakened: none of the 12 files was touched.

The `.bak` copies went into a `delete_me/` that already held earlier harvests' files. The read-only status check shows only these five `.bak` files as new there, and every earlier file there is tracked and unmodified, so nothing was overwritten.
