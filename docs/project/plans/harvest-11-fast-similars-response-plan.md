# Harvest — 11 fast similars response

## Resolved paths

- project_dir: `/home/enduser/code/PeerTube-browser/.worktrees/11`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- Bootstrap gate: clear (`defaulted` is empty, `conflicts` is empty).
- Snapshot: `tests/last_test_validation.json.preharvest` taken before any run.

## Scope

- `tests/tmp/test_11_fast_similars_response_phase1.py`
- `tests/tmp/test_11_fast_similars_response_phase2.py`
- `tests/tmp/test_11_fast_similars_response_phase3.py`

The `probe_*.py` files in `tests/tmp` are not in scope and are left where they are.

## Inventory

### tests/tmp/test_11_fast_similars_response_phase1.py

- Drives: `engine/server/api/handlers/video.py` (`handle_video_refresh_request`, `handle_video_request`) through `SimilarHandler`'s dispatch in `engine/server/api/handlers/similar.py`, in an `ENGINE_PY` child.
- Tests: `test_refresh_answers_the_instances_values_in_the_api_video_shape`, `test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted`, `test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance`, `test_api_video_still_answers_the_instances_values`.
- Depends on: `ENGINE_PY`, `ROOT` from conftest; constants `HOST`, `UUID`, `REFRESH`, `DETAIL_PATH`, `CHANNEL_PATH`, `DETAIL`, `CHANNEL`, `ANSWERING`, `PARTIAL`, `OMITTING`, `BY_VIDEO_ID`, `LIVE`, `CHILD`; fixture `sync_job`; helpers `_seed`, `_get`.
- Collects: yes.

### tests/tmp/test_11_fast_similars_response_phase2.py

- Drives: `engine/server/api/handlers/video.py` (`fetch_instance_video_dynamic`, `persist_video_metadata`, `handle_video_refresh_request`) and the similars route in `engine/server/api/handlers/similar.py`, in an `ENGINE_PY` child.
- Tests: `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows`, `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields`, `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed`, `test_a_refresh_the_instance_did_not_answer_writes_nothing` (4 params), `test_similars_answer_while_a_refresh_is_blocked_on_the_instance`.
- Depends on: `ENGINE_PY`, `ROOT`; constants `HOST`, `UUID`, `REFRESH`, `SIMILAR`, `DETAIL_PATH`, `CHANNEL_PATH`, `DETAIL`, `ANSWERING`, `CHANNEL_FAILED`, `LIVE_VIDEO`, `LIVE_CHANNEL`, `DB_CHANNEL_VIDEO`, `DB_CHANNEL_CHANNEL`, `CLEARED_INSTANCE`, `DB_ONLY`, `CHILD`; fixtures `sync_job`, `data_db`; helpers `_seed`, `_interrupted`, `_rows`, `_run`, `_assert_written`.
- Collects: yes.

### tests/tmp/test_11_fast_similars_response_phase3.py

- Drives: `client/backend/server.py` (`PROXY_READ_GET_ROUTES`, `PROXY_ALLOWED_QUERY_PARAMS`, `_proxy_engine_request` per-path timeout/retry).
- Tests: `test_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400`, `test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502`.
- Depends on: `RateLimiter`, `client_server` from conftest; `_client_backend`, `_serving`, `_status` from `test_server`; constants `REFRESH_ROUTE`, `QUERY`, `FORWARDED`, `ANSWER`; helpers `_engine_stub`, `_get`.
- Collects: yes.

## Classification

No subject file for `video.py` exists in `tests/active`, and no active test mentions `/api/video`, `handlers.video`, `fetch_instance_json`, or `ENGINE_PROXY_*`, so no verdict can be `REDUNDANT` against the durable suite; no two in-scope tests assert the same behaviour.

Subject file to create: `tests/active/test_video.py` (for `engine/server/api/handlers/video.py`).

### phase1 → tests/active/test_video.py

- `test_refresh_answers_the_instances_values_in_the_api_video_shape` — DURABLE: the refresh route's live-values answer shape; asserted nowhere in active.
- `test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted` — DURABLE: field-by-field fallback to the row, incl. `likes: 0` kept; asserted nowhere in active.
- `test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance` — DURABLE: the 400/404 refusals with no instance call; asserted nowhere in active.
- `test_api_video_still_answers_the_instances_values` — DURABLE: `/api/video`'s live behaviour is live production code today; the follow-up plan that makes it DB-only will replace this test.

### phase2 → tests/active/test_video.py

- `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows` — DURABLE: the persist on success; asserted nowhere in active.
- `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields` — DURABLE: a failed channel sub-call still persists; asserted nowhere in active.
- `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` — DURABLE: persist under its own statement deadline; asserted nowhere in active.
- `test_a_refresh_the_instance_did_not_answer_writes_nothing` — DURABLE: no write when the detail call did not answer; asserted nowhere in active.
- `test_similars_answer_while_a_refresh_is_blocked_on_the_instance` — DURABLE: instance calls outside `db_lock`; asserted nowhere in active.

### phase3 → tests/active/test_server.py

- `test_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400` — DURABLE: the refresh allow-list; test_server.py has no refresh-route test.
- `test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502` — DURABLE: per-path timeout and zero retries; test_server.py has no proxy timeout/retry test.

## Counts

DURABLE 11, REPLACES 0, COMBINE 0, REDUNDANT 0, SPENT 0. No active test retired.

## Planned group map change

- Add `test_video.py`: `engine/server/api/handlers/video.py`, `engine/server/api/handlers/similar.py`, `engine/server/data/db.py` (pruned against `--suggest-map`).
- `test_server.py`: unchanged; it already claims `client/backend/server.py`.
