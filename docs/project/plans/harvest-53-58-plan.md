# Harvest: builds 53 and 58 (tests/tmp)

## Step 1 - Resolved paths and scope

- source: `/home/enduser/code/PeerTube-browser/tests/config.json`
- PROJECT_DIR: `/home/enduser/code/PeerTube-browser` (the merged config carried worktree 53's `project_dir`; corrected to the main checkout before this harvest)
- active `tests/active`, working `tests/tmp`, plans `docs/project/plans`, delete_me `delete_me`, archive `tests/archive`, record `tests/last_test_validation.json`
- Bootstrap gate: `defaulted` empty, `conflicts` empty.
- Snapshot: `tests/last_test_validation.json.preharvest` taken before any run.
- Scope (argument empty: every `test_*.py` under `tests/tmp`):
  1. `tests/tmp/test_53_source_instance_fetch_adapter_phase1.py`
  2. `tests/tmp/test_53_source_instance_fetch_adapter_phase2.py`
  3. `tests/tmp/test_53_source_instance_fetch_adapter_phase3.py`
  4. `tests/tmp/test_53_source_instance_fetch_adapter_phase4.py`
  5. `tests/tmp/test_58_engine_routing_out_of_similar_phase1.py`
  6. `tests/tmp/test_probe_58_seam.py`
  7. `tests/tmp/test_probe_findcue_unsorted.py`

Both builds stopped at dev-flow Step 10 (harvest refuses a worktree); both are merged.

## Steps 2-3 - Inventory and verdicts

### tests/tmp/test_53_source_instance_fetch_adapter_phase1.py

Drives `engine/server/data/source_fetch.py`. Depends on the harness in `tests/active/test_internal_translate.py` (Clock, Response, ScriptedInstance, `_body`, CHUNK, HOST, OVER_CAP, REFUSED_TARGETS, TRACK_PATH, TRACK_URL, WITHIN_CAP); module constants MOVED_URL, UNSERVED_URL, MEDIA_URL, MEDIA_MOVED_URL, MEDIA_SIZE, OPEN_ERRORS, STATUSES, MEDIA_STATUSES, MEDIA_OPEN_ERRORS, MEDIA_HOSTS, REFUSED_MEDIA_URLS; class SourceInstance; fixture `scripted_instance`; helpers `_adapter`, `_exactly`, `_budget`.

No subject file exists: `tests/active/test_source_fetch.py` must be created (test_internal_translate.py's docstring already says the bounded fetch "is tested there"; the build removed those tests from test_internal_translate.py). Every test is **DURABLE**: no active test calls `fetch_bounded`, `stream_media`, `SameHostRedirectHandler` or `media_host` directly.

- test_redirect_handler_follows_a_same_host_https_target - DURABLE: handler returns the target request, `refused` None.
- test_redirect_handler_refuses_an_off_host_or_non_https_target_and_keeps_it_as_refused - DURABLE: refusal and `refused` set.
- test_fetch_follows_a_same_host_redirect - DURABLE: absolute and relative same-host redirect followed.
- test_fetch_names_a_refused_redirect_target_and_never_opens_it - DURABLE: `redirect refused: <target>`.
- test_a_refused_redirect_does_not_carry_into_the_next_fetch - DURABLE: per-fetch handler state.
- test_fetch_names_the_status_of_a_non_200_answer - DURABLE: `HTTP <n>` reasons.
- test_fetch_refuses_a_declared_length_over_the_cap_without_reading - DURABLE.
- test_fetch_refuses_a_body_streamed_past_the_cap_reading_no_further - DURABLE.
- test_fetch_returns_a_body_of_2_000_000_bytes_whole - DURABLE: cap boundary.
- test_fetch_names_a_deadline_passed_while_the_body_is_still_arriving - DURABLE.
- test_with_no_overrides_the_deadline_is_8_seconds - DURABLE.
- test_fetch_with_its_budget_spent_names_the_deadline_and_opens_nothing - DURABLE.
- test_fetch_names_an_error_raised_at_open_by_its_text - DURABLE.
- test_with_no_overrides_fetch_sends_todays_accept_header_under_a_4s_socket_timeout_capped_by_the_budget - DURABLE.
- test_a_max_bytes_override_replaces_the_2_000_000_byte_cap - DURABLE.
- test_a_deadline_seconds_override_replaces_the_8s_deadline_and_caps_the_socket_timeout - DURABLE.
- test_a_socket_timeout_override_is_sent_capped_by_the_time_left - DURABLE.
- test_a_headers_override_replaces_the_default_accept_header - DURABLE.
- test_stream_media_feeds_the_whole_body_under_a_15s_socket_timeout_with_no_wall_clock_deadline - DURABLE.
- test_stream_media_names_a_non_200_answer_in_todays_text - DURABLE.
- test_stream_media_names_an_error_raised_at_open_in_todays_text - DURABLE.
- test_stream_media_refuses_a_declared_length_over_max_bytes_without_reading - DURABLE (the worker bounds test reads only an error prefix).
- test_stream_media_refuses_a_body_streamed_past_max_bytes_consuming_nothing_past_it - DURABLE.
- test_stream_media_names_its_own_max_bytes - DURABLE.
- test_stream_media_keeps_todays_text_for_a_refused_redirect_and_never_opens_its_target - DURABLE.
- test_stream_media_follows_a_same_host_redirect - DURABLE.
- test_stream_media_reads_nothing_more_once_stop_is_set - DURABLE.
- test_a_consumers_broken_pipe_propagates_as_itself_not_as_a_download_failure - DURABLE.
- test_media_host_returns_the_raw_lowercased_hostname - DURABLE: raw hostname, trailing dot kept; not asserted elsewhere.
- test_media_host_refuses_anything_but_an_https_dns_name_with_no_port_or_userinfo - DURABLE: covers forms the worker's REFUSED_FILES lacks (default port, user:pw, unparseable port, empty, not a URL).

### tests/tmp/test_53_source_instance_fetch_adapter_phase2.py

Route part drives `engine/server/api/handlers/internal_translate.py` (subject `tests/active/test_internal_translate.py`); worker part drives `engine/server/db/jobs/translate-worker.py` (subject `tests/active/test_translate_worker.py`). Depends on the harnesses of both active files; module fixtures `severed_network` (autouse), `instance`, `whitelist`; constants NONE_CASES, REFUSED_BODIES, BRANCHES, JOBS, FAILED_FETCH, CAPTIONS_PATH, BAD_TRACK, OFF_HOST_TRACK_URL; helpers `_route`, `_serve`, `_failed_fetches`, `_split`, `_dispatching_opener`, `_load_worker`, `UnreachedRunner`.

- test_an_unknown_video_opens_nothing_and_a_resolved_one_is_fetched_through_the_adapter - REDUNDANT: test_an_unknown_video_is_404_video_not_found_with_no_fetch.
- test_a_denylisted_host_answers_404_before_any_fetch_even_with_a_stored_track - REDUNDANT: test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track.
- test_each_bad_body_answers_its_400_with_nothing_opened - REDUNDANT: test_enqueue_refuses_a_bad_body_or_unknown_video_exactly_as_the_state_route_does (state route answer asserted) and test_after_that_is_not_a_non_negative_json_int_answers_400.
- test_a_running_row_answers_its_cues_from_after_with_the_stored_total_and_opens_nothing - REDUNDANT: test_a_running_key_answers_its_cues_from_after_with_the_stored_total_and_no_fetch.
- test_enqueue_answers_404_for_a_denied_host_and_queued_under_a_fresh_beat_opening_nothing - REDUNDANT: test_enqueue_refuses_a_denylisted_host_exactly_as_the_state_route_does.
- test_enqueue_without_a_serving_worker_answers_none_not_available_and_queues_and_opens_nothing - REDUNDANT: test_without_a_serving_worker_enqueue_answers_none_not_available_and_writes_no_row.
- test_enqueue_with_a_serving_worker_answers_a_stored_key_its_state_and_leaves_its_row_opening_nothing - REDUNDANT: test_with_a_serving_worker_a_stored_key_answers_its_state_and_its_row_is_unchanged.
- test_enqueue_at_the_queue_cap_answers_busy_and_one_below_it_queues_opening_nothing - REDUNDANT: test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues.
- test_a_store_error_from_the_enqueue_answers_503_and_queues_and_opens_nothing - COMBINE with active test_a_store_error_from_the_enqueue_answers_503_and_writes_no_row: the active test asserts only `set(body) == {"error"}`; lift the exact `503 {"error": "Translate store unavailable"}`.
- test_a_ready_track_is_fetched_from_the_row_host_stored_and_then_served_without_a_fetch - REDUNDANT: the active test of the same name (plus an empty-file control).
- test_each_none_path_answers_none_stores_nothing_and_logs_each_failed_fetch_with_its_reason - REPLACES active test_each_none_path_answers_none_and_stores_nothing: same four cases plus a Content-Length over the cap and an off-host redirect, exact URLs opened, and the `[translate] instance fetch failed ... <reason>` log line per failed fetch (the build's "failure says why" at the route).
- test_one_15_second_budget_covers_both_fetches - DURABLE: no active test asserts the shared 15 s budget.
- test_each_stored_state_answers_its_state_and_fetches_only_past_queued_and_running - REDUNDANT: the active test of the same shape.
- test_a_caption_entry_off_the_host_answers_none_with_only_the_caption_list_opened - REDUNDANT: test_caption_pick_refuses_anything_off_the_host, same PICK_REFUSED cases on the pick the route calls.
- test_a_job_stores_a_failed_video_json_fetch_with_the_adapters_reason - DURABLE → test_translate_worker.py: the active bounds test reads only the `video JSON fetch failed` prefix; this one pins each stored reason exactly.

### tests/tmp/test_53_source_instance_fetch_adapter_phase3.py

Drives `engine/server/api/handlers/video.py` (subject `tests/active/test_video.py`). Depends on test_internal_translate's Clock/ScriptedInstance/HandlerRequest and test_video's constants, fixtures `server`, `sync_job`; class TimedInstance; fixture `instance`; constants REFUSED, HTTP_REFUSED, HTTP_ANSWERED, HTTP_CHILD.

- test_fetch_instance_json_answers_none_for_a_refused_detail_and_opens_only_the_detail_url - DURABLE: no active test serves an off-host redirect or a body over the cap to `/api/video`'s fetch.
- test_api_video_answers_the_stored_row_and_writes_nothing_when_the_detail_is_refused - REDUNDANT: the test above proves the refusal is a None, and test_fetch_failure_leaves_db_untouched proves a failed detail fetch answers the stored row and writes nothing.
- test_api_video_over_http_answers_the_db_only_body_and_writes_nothing_when_the_detail_is_refused - REDUNDANT: same, over HTTP; test_a_refresh_the_instance_did_not_answer_writes_nothing covers the HTTP path with the adapter refusing.
- test_api_video_over_http_answers_the_live_body_through_the_same_opener - REDUNDANT: test_api_video_still_answers_the_instances_values.

### tests/tmp/test_53_source_instance_fetch_adapter_phase4.py

Drives `engine/server/db/jobs/fetch-trending.py` (subject `tests/active/test_fetch_trending.py`). Depends on test_fetch_trending's FAILURES, TRENDING_URL, `job`; helper `_scripted` (extends the active one with routes, statuses and headers), `_redirect`, `_padded`; constants MOVED_URL, CDN_URL, LIST_BODY.

- test_fetch_host_list_reads_the_trending_page_through_the_adapter - REDUNDANT: test_fetch_host_list_reads_the_host_s_trending_page.
- test_fetch_host_list_returns_none_after_max_retries_plus_one_failed_attempts - REDUNDANT: the active test of the same name.
- test_fetch_host_list_with_no_retries_makes_one_attempt - REDUNDANT: same name in active.
- test_fetch_host_list_returns_the_list_when_a_retry_succeeds - REDUNDANT: same name in active.
- test_an_off_host_redirect_fails_every_attempt_and_its_target_is_never_opened - DURABLE.
- test_a_body_one_byte_over_trending_max_bytes_fails_every_attempt - DURABLE.
- test_an_attempt_whose_clock_passes_timeout_s_fails_on_the_deadline_and_is_retried - DURABLE.

### tests/tmp/test_58_engine_routing_out_of_similar_phase1.py

Drives `engine/server/api/router.py` through the real `SimilarHandler` in an Engine child. Constants STUBBED, PATHS, UNAUTHORIZED, UNSET, NOT_FOUND, PRELUDE, BRIDGE_CHILD, FAKE_CHILD; helper `_run`; its own ROOT/ENGINE_PY/API_DIR (conftest has ENGINE_PY). No subject file exists: `tests/active/test_router.py` must be created. No active test references `GET_ROUTES`/`POST_ROUTES`, the 503 unset-token answer, or the ingest 501.

- test_internal_posts_answer_the_bridge_gate_before_their_route_runs - DURABLE.
- test_a_route_added_as_one_get_routes_entry_is_served_through_the_real_handler - DURABLE.

On the move the PRELUDE's pre-router fallback (`except ModuleNotFoundError` stand-in table) is dropped, since `router` exists.

### tests/tmp/test_probe_58_seam.py

A one-line comment, no tests. SPENT.

### tests/tmp/test_probe_findcue_unsorted.py

Empty file. SPENT.

## Counts

DURABLE 38 (phase1 30, phase2 2, phase3 1, phase4 3, 58 2); REPLACES 1; COMBINE 1; REDUNDANT 18 (phase2 11, phase3 3, phase4 4); SPENT 2 files with no tests.

## Step 4 - Approval

Operator approved the plan as presented (2026-10-04).

## Step 5 - Applied

- Created `tests/active/test_source_fetch.py` (30 phase-1 tests; docstring restated as the adapter's rules; the harness is imported from `test_internal_translate.py`).
- Created `tests/active/test_router.py` (both build-58 tests; the pre-router stand-in fallback dropped; `ENGINE_PY` from conftest).
- `test_internal_translate.py`: REPLACES - `test_each_none_path_answers_none_stores_nothing_and_logs_each_failed_fetch_with_its_reason` (with `NONE_CASES`, `timed_instance` fixture, `_failed_fetches`, `_split`) in place of `test_each_none_path_answers_none_and_stores_nothing` and `NONE_PATHS`; DURABLE `test_one_15_second_budget_covers_both_fetches`; COMBINE - `test_a_store_error_from_the_enqueue_answers_503_and_writes_no_row` now asserts `[[503, {"error": "Translate store unavailable"}]]`. Docstring updated.
- `test_translate_worker.py`: DURABLE `test_a_job_stores_a_failed_video_json_fetch_with_the_adapters_reason` (`FETCH_REASONS`, `UnreachedRunner`; reuses the file's `_worker`, `_whitelist`, `ScriptedHost`, `_dispatching_opener`, `INSTANCE_THEN_JSON`). Docstring updated.
- `test_video.py`: DURABLE `test_fetch_instance_json_answers_none_for_a_refused_detail_and_opens_only_the_detail_url`, rebuilt on the file's own `_serve`/`_FakeResponse` harness rather than importing test_internal_translate's. Docstring updated.
- `test_fetch_trending.py`: DURABLE off-host redirect, `TRENDING_MAX_BYTES`, clock-deadline tests; `_scripted`/`_Response` extended to routes, statuses and headers. Docstring updated.
- Archived: `tests/archive/53_source_fetch_adapter/test_internal_translate.py` (the replaced test, skipped module).
- `test_groups`: added `test_source_fetch.py` -> `engine/server/data/source_fetch.py`; `test_router.py` -> `engine/server/api/router.py`, `engine/server/api/handlers/similar.py`. No entry dropped.
- `--audit-map` exit 0; no MISSING finding concerns a moved test.

## Step 6 - Mutations

Driver: `delete_me/harvest_mutate.py` with one table per production file (`delete_me/harvest_mut_*.py`): copy to `.bak`, replace one exact snippet, run only the targeted tests, restore from the copy, byte-compare, park the copy as `delete_me/<file>.bak-harvest53-58-<label>`, re-run green. Every restore was exact and every re-run green; `git status` shows no production file modified and no `.bak` under the production tree.

`engine/server/data/source_fetch.py` -> `test_source_fetch.py`:
- A same_host_https hostname check dropped: fells redirect_handler_refuses, fetch_names_a_refused_redirect, refused_redirect_does_not_carry, stream_media_keeps_todays_text_for_a_refused_redirect (off-host, lookalike).
- B `refused` not recorded: fells redirect_handler_refuses (`refused` None) and fetch_names_a_refused_redirect (`HTTP 302`), all five targets.
- B2 one handler shared across fetches: fells refused_redirect_does_not_carry (404 misnamed as the refused redirect).
- C same-host redirect not followed: fells redirect_handler_follows (5 codes), fetch_follows_a_same_host_redirect (2), stream_media_follows_a_same_host_redirect.
- D1/D2 status unnamed: fells fetch_names_the_status (404/500; 204).
- E declared length unchecked: fells fetch_refuses_a_declared_length_over_the_cap_without_reading, a_max_bytes_override.
- F1 cap `>=`: fells fetch_returns_a_body_of_2_000_000_bytes_whole (both).
- F2 cap checked after reading the body: fells fetch_refuses_a_body_streamed_past_the_cap_reading_no_further.
- G per-chunk deadline unchecked: fells deadline_passed_while_the_body_is_still_arriving (both), deadline_is_8_seconds, deadline_seconds_override.
- H `remaining < 0`: fells budget_spent [exactly now].
- I deadline 9 s: fells with_no_overrides_the_deadline_is_8_seconds.
- J open-error text lost: fells fetch_names_an_error_raised_at_open_by_its_text (6).
- K accept header changed / K2 socket timeout uncapped / K3 4 s -> 5 s: fells with_no_overrides_fetch_sends_todays_accept_header...; K2 also socket_timeout_override.
- L headers merged: fells headers_override.
- M deadline_seconds ignored: fells deadline_seconds_override.
- N socket_timeout ignored: fells socket_timeout_override.
- O max_bytes ignored: fells max_bytes_override.
- P media socket timeout 8 s: fells stream_media_feeds_the_whole_body...
- Q media status text: fells stream_media_names_a_non_200 [returned 204].
- R media error text: fells stream_media_names_an_error_raised_at_open (6), stream_media_keeps_todays_text_for_a_refused_redirect (5), consumers_broken_pipe (control).
- S media declared length unchecked: fells stream_media_refuses_a_declared_length..., stream_media_names_its_own_max_bytes.
- T media consumed before the cap check: fells stream_media_refuses_a_body_streamed_past..., stream_media_names_its_own_max_bytes.
- U stop ignored: fells stream_media_reads_nothing_more_once_stop_is_set.
- V BrokenPipeError wrapped: fells consumers_broken_pipe.
- W media_host normalized: fells media_host_returns_the_raw_lowercased_hostname [trailing dot].
- X TLD check dropped: fells media_host_refuses... [IPv4, dotted numeric, hex].

`engine/server/api/handlers/internal_translate.py` -> `test_internal_translate.py`:
- IT1 reason dropped from the failed-fetch log: fells the none-path test (4 failing-fetch rows).
- IT2 cap lifted at the route: fells the none-path test [Content-Length row answers ready].
- IT3 fresh budget per fetch: fells test_one_15_second_budget_covers_both_fetches.
- IT4 503 text changed: fells test_a_store_error_from_the_enqueue_answers_503_and_writes_no_row (the COMBINE assertion).

`engine/server/db/jobs/translate-worker.py` -> `test_translate_worker.py`:
- TW1 JSON reason dropped: fells adapters_reason [unserved, over the cap, redirected off].
- TW2 media reason dropped: fells adapters_reason [media redirected off].

`engine/server/api/handlers/video.py` -> `test_video.py`:
- V1 fetch around the adapter (default redirects, no cap): fells all three refused params.
- V2 cap lifted: fells the two cap params.

`engine/server/db/jobs/fetch-trending.py` -> `test_fetch_trending.py`:
- FT1 default 2,000,000 cap: fells the TRENDING_MAX_BYTES test (control).
- FT2 default 8 s deadline: fells the clock-deadline test.
- FT3 fetch with default redirects: fells the off-host redirect test.

`engine/server/api/router.py` -> `test_router.py`:
- R1 gate after the table lookup: fells the bridge-gate test (unknown path 404, not 401).
- R2 empty token accepted as a token: fells the bridge-gate test (`unset`, 401 not 503).
- R3 prefix token compare: fells the bridge-gate test (`near_miss`).
- R4 GET table frozen at first request: fells the GET_ROUTES test (`after` 404).
- R5 GET prefix match: fells the GET_ROUTES test on `seen` (an extra call for `/fake/`), which precedes and states the same exact-path rule as the `trailing_slash` assertion.

No mutation felled nothing; no test reclassified.

## Step 7 - Disposal

Moved into `delete_me/` (no name collisions): the seven scope files, plus the Step 6 driver and its six tables. `tests/tmp` holds no `test_*.py`. The 46 `.bak-harvest53-58-*` copies from Step 6 are in `delete_me/` too.

## Step 8 - Suite

Snapshot restored, then `validate_tests.py --compare`: exit 0, 17 of 65 groups run (48 carried unchanged by the record), 641 passed, none failed. Delta: 101 test ids appeared (test_source_fetch 79, test_router 2, test_internal_translate 7, test_translate_worker 7, test_video 3, test_fetch_trending 3), 4 gone (the replaced `test_each_none_path_answers_none_and_stores_nothing` params). Nothing else moved. Record banked.
