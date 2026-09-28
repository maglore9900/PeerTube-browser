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

## Carried out on main (combined harvest of builds 10 and 11)

This plan was written in the build-11 worktree and not carried out there. The operator approved harvesting it on main (`/home/enduser/code/PeerTube-browser`) together with build 10. harvest-10-video-metadata-completeness-plan.md carries the full shared record: the REDUNDANT re-check between the two builds, the combined `test_video.py`, every mutation, and one process fault. Bootstrap gate clear; the record was snapshotted before any run and restored before the closing `--compare`.

### Changes on main since this plan

- Phase 1 and phase 2's expected bodies (`LIVE`, `DB_ONLY`, and the `ROW_TAXONOMY` overrides) carry issue 10's six response keys: tags, category, language, nsfw, duration and thumbnailUrl. They moved as they are.
- video.py follows this build's rule that a `{}` detail is a failure, and build 10's phase 3 was edited to agree.

### Verdicts: all 11 DURABLE, as planned

Re-checked against build 10's tests now in the same subject file, and none is REDUNDANT. `test_a_refresh_the_instance_did_not_answer_writes_nothing` and build 10's `test_fetch_failure_leaves_db_untouched` overlap on `{}`, list and URLError. This one alone goes through the real HTTP route, compares the full DB-only body, checks the neighbour row and covers a `None` stub. Build 10's alone drives the real `fetch_instance_json` parser. Build 10's plan has the other pairs.

### Destinations

- `tests/active/test_video.py` (new, shared with build 10): phases 1 and 2. The two `CHILD` scripts became `ANSWER_CHILD` (phase 1's `_get`) and `PERSIST_CHILD` (phase 2's `_run`). Phase 1 now reuses phase 2's `_seed`, whose extra `last_error_at`/`last_error_source` values, neighbour row v2 and embeddings do not reach any phase-1 answer. It passed, and the mutations confirm it still grips. `sync_job` and `data_db` are module fixtures shared with build 10's in-process tests. `conftest` is imported directly rather than through the tmp-era `sys.path` insert.
- `tests/active/test_server.py` (existing): phase 3's two tests. The constants were renamed `REFRESH_QUERY`, `REFRESH_FORWARDED` and `REFRESH_ANSWER`, `_engine_stub` became `_refresh_engine_stub`, and `_get` became `_get_json`. They reuse the file's own `_serving`, `_client_backend` and `_status`. `import time` and `parse_qs` were added, and the module docstring gained a paragraph on the refresh proxy.

### Group map

- New `test_video.py`: `engine/server/api/handlers/video.py`, `engine/server/data/peertube_labels.py`, `engine/server/api/handlers/similar.py`, `engine/server/data/db.py`. This is the pruned set above plus build 10's labels module.
- `test_server.py` is unchanged. `--audit-map` exits 0.

### Mutations (red, then restored `cmp`-exact, then green)

- `test_refresh_answers_the_instances_values_in_the_api_video_shape`: `accountAvatarUrl` changed to `""`. Red: body != LIVE.
- `test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted`: likes uses a truthiness fallback. Red: likes 2 != 0.
- `test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance`: the unknown-video answer is 200. Red: 200 != 404.
- `test_api_video_still_answers_the_instances_values`: `handle_video_request` made DB-only. Red: body reads "DB title".
- `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows`: the instance `last_error*` clear removed. Red: instances row.
- `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields`: a failed channel call returns None. Red: `last_checked_at` left at 1 (row unwritten).
- `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed`: the fresh `statement_deadline` around persist removed. Red: `last_checked_at` left at 1.
- `test_a_refresh_the_instance_did_not_answer_writes_nothing`: write guard `dynamic is not None and` removed. Red: all 4 params, after != before.
- `test_similars_answer_while_a_refresh_is_blocked_on_the_instance`: the instance fetch is wrapped in `server.db_lock`. Red: similars elapsed 5.01 s, not < 1.0.
- `test_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400`: `user_id` added to the refresh allow-list. Red: [200, 400, ...].
- `test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502`: the refresh entry dropped from `ENGINE_PROXY_ROUTE_RETRY_COUNT`. Red: the refresh was sent twice.

### Disposal and closing run

- The three phase files moved to `delete_me/` with `mv -n`, and `tests/tmp` holds only `__pycache__`.
- Closing `--compare`: 213 passed, 39 appeared (builds 10 and 11 combined), none departed, no new red.
