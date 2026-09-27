# Harvest — 11 raw-event retention

## Resolved paths (from `--show-config`, bootstrap gate clear: `defaulted` is empty)

- project_dir: `/home/enduser/code/PeerTube-browser/.worktrees/fix-11-raw-event-retention`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- config: `.un/skills/devsecops/config.json`

## Scope

The tests build 11 wrote (the `probe_*.py` files in `tests/tmp` are outside this scope and are left untouched):

- `tests/tmp/test_11_raw_event_retention_phase1.py`
- `tests/tmp/test_11_raw_event_retention_phase2.py`
- `tests/tmp/test_11_raw_event_retention_phase3.py`
- `tests/tmp/test_11_raw_event_retention_phase4.py`

## Snapshot

`tests/last_test_validation.json.preharvest` was taken before any run (cmp-identical to the record at that moment).

## Inventory

All four files collect; a run of the four gave 25 passed (5 + 9 + 8 + 3).

### tests/tmp/test_11_raw_event_retention_phase1.py

Drives `engine/server/data/interaction_events.py` (`prune_interaction_raw_events`, `ensure_interaction_event_schema`, `ingest_interaction_event`). Depends on: sys.path setup for `engine/server` and `engine/server/api`, `DAY_MS`, `STRIPPED`, `UNSTRIPPED_INDEX`, `_db`, `_insert_raw`, `_rows`, `_stripped`, `_CountingLock`.

- `test_a_31_day_row_is_stripped_of_actor_and_payload_only_and_a_29_day_row_is_untouched`
- `test_the_cutoff_is_exclusive_and_a_row_holding_any_one_column_is_stripped`
- `test_five_stale_rows_are_stripped_two_per_committed_lock_hold`
- `test_a_stripped_event_replayed_is_still_a_duplicate_and_moves_no_signal`
- `test_the_schema_creates_the_unstripped_index_and_the_prune_finds_its_rows_through_it`

### tests/tmp/test_11_raw_event_retention_phase2.py

Drives `engine/server/api/server_config.py` (`INTERACTION_RAW_RETENTION_DAYS`, `_resolve_positive_int_env`) in a child process, and `engine/server/api/server.py --help`. Depends on: `API_DIR`, `ENGINE_PY`, `VAR`, `PRINT_DAYS`, `_run`, `_last_stderr_line`.

- `test_a_positive_integer_becomes_the_constant_and_unset_gives_30` (3 params)
- `test_a_value_that_is_not_a_positive_integer_stops_the_import` (5 params)
- `test_server_py_exits_before_argument_parsing_on_a_bad_value`

### tests/tmp/test_11_raw_event_retention_phase3.py

Drives `engine/server/api/handlers/internal_events.py` (`handle_internal_events_ingest` → `_prune_raw_events_if_due`), plus `SimilarServer.__init__` in `engine/server/api/server.py` via the Engine interpreter. Depends on: sys.path setup, `DAY_MS`, `STRIPPED`, `ENGINE_PY`, `RETENTION_VAR`, `ENGINE_INGEST`, `_db`, `_server`, `_insert_raw`, `_rows`, `_stripped`, `_stripped_ids`, `_event`, `_ok_body`, `_post`, `_patch_prune`, `_LockFailingInsideTheStrip`, `_interrupt_the_strip`, `_abort_the_strip`, `_fail_the_strips_lock`.

- `test_the_first_ingest_strips_and_the_next_strip_waits_until_the_last_one_is_an_interval_old`
- `test_the_strip_uses_the_servers_retention_days` (7, 9)
- `test_the_engines_server_carries_the_env_retention_days_and_an_unset_last_strip` (7, 9)
- `test_a_strip_that_raises_leaves_the_200_body_unchanged` (3 params)

### tests/tmp/test_11_raw_event_retention_phase4.py

Drives `engine/server/api/handlers/similar.py` (`_handle_similar_request` → `_recommendations_likes_payload_error`) in the Engine interpreter. Depends on: `ENGINE_PY`, `LIKES_MAX`, `RESOLVED_LIKES`, `HANDLE_CASES`, `_handle`, `_likes`, `_rejected`, and `_DummySimilarHandler` imported from `engine/server/api/tests/test_recommendations_likes_limit.py`.

- `VideosSimilarLikesLimitTests.test_videos_similar_rejects_more_likes_than_allowed`
- `VideosSimilarLikesLimitTests.test_videos_similar_rejects_invalid_likes_item_format`
- `VideosSimilarLikesLimitTests.test_videos_similar_allows_likes_at_limit`

## Classification

A search of `tests/active` for `prune_interaction_raw_events`, `interaction_raw_events`, `INTERACTION_RAW`, `internal_events`, `raw_retention`, `likes_payload_error`, `Too many likes`, `Invalid likes payload` and `DEFAULT_CLIENT_LIKES_MAX` found nothing. No active subject file exists for `interaction_events.py`, `server_config.py` or `internal_events.py`; `test_similar.py` exists for `similar.py` and covers only the exclude cap and feed contents, not likes validation.

Totals: DURABLE 15, REPLACES 0, COMBINE 0, REDUNDANT 0, SPENT 0.

### phase1 → new `tests/active/test_interaction_events.py`

- `test_a_31_day_row_is_stripped_...`: DURABLE — no active test asserts the prune strips only the three columns of a stale row.
- `test_the_cutoff_is_exclusive_...`: DURABLE — the exclusive cutoff and the partial-column rows are asserted nowhere else.
- `test_five_stale_rows_are_stripped_two_per_committed_lock_hold`: DURABLE — chunking and per-lock-hold commits are asserted nowhere else.
- `test_a_stripped_event_replayed_is_still_a_duplicate_...`: DURABLE — the no-delete / dedup-survives guarantee is asserted nowhere else.
- `test_the_schema_creates_the_unstripped_index_...`: DURABLE — the partial index and the plan using it are asserted nowhere else.

### phase2 → new `tests/active/test_server_config.py`

- `test_a_positive_integer_becomes_the_constant_and_unset_gives_30`: DURABLE — no active test reads `INTERACTION_RAW_RETENTION_DAYS`.
- `test_a_value_that_is_not_a_positive_integer_stops_the_import`: DURABLE — fail-closed validation is asserted nowhere else.
- `test_server_py_exits_before_argument_parsing_on_a_bad_value`: DURABLE — the Engine entry point stopping on a bad value is asserted nowhere else.

### phase3 → new `tests/active/test_internal_events.py`

- `test_the_first_ingest_strips_and_the_next_strip_waits_...`: DURABLE — the hourly throttle is asserted nowhere else.
- `test_the_strip_uses_the_servers_retention_days`: DURABLE — kept alongside the SimilarServer test rather than marked REDUNDANT: in the child the env sets both the module constant and the server attribute to the same value, so only this stand-in test catches a handler that reads `INTERACTION_RAW_RETENTION_DAYS` instead of `server.raw_retention_days`.
- `test_the_engines_server_carries_the_env_retention_days_...`: DURABLE — the only test of the real `SimilarServer` carrying the window and an unset last-strip.
- `test_a_strip_that_raises_leaves_the_200_body_unchanged`: DURABLE — failure isolation of the strip is asserted nowhere else.

### phase4 → existing `tests/active/test_similar.py`

- `test_videos_similar_rejects_more_likes_than_allowed`: DURABLE — likes-cap 400 on `/videos/similar` is asserted nowhere in active (only in the separate `engine/server/api/tests` unittest, and only for `/recommendations`).
- `test_videos_similar_rejects_invalid_likes_item_format`: DURABLE — same, for malformed entries.
- `test_videos_similar_allows_likes_at_limit`: DURABLE — the at-limit pass-through on `/videos/similar` is asserted nowhere else.

Converted from a `unittest.TestCase` class to module-level pytest functions to match `test_similar.py`. `_DummySimilarHandler` is copied into the child script rather than imported from `engine/server/api/tests/test_recommendations_likes_limit.py`, so the group does not depend on another suite's test file. `LIKES_MAX` is read through `importlib` the way `_default_limit` reads `BATCH_SIZE`, since the file does not import `server_config` in-process.

## Planned map changes

- add `test_interaction_events.py`: `engine/server/data/interaction_events.py`
- add `test_server_config.py`: `engine/server/api/server_config.py`, `engine/server/api/server.py`
- add `test_internal_events.py`: `engine/server/api/handlers/internal_events.py`, `engine/server/api/server.py`, `engine/server/api/server_config.py`, `engine/server/data/interaction_events.py`
- `test_similar.py`: unchanged (already claims `similar.py` and `server_config.py`)

## Retired

none planned.
