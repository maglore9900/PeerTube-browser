# Harvest: plan 50 translate generation in page

## Step 1: resolved paths and scope

Bootstrap gate: clear (`defaulted` is `[]`, `conflicts` is `[]`), from `./.un/skills/devsecops/scripts/validate_tests.py --show-config`.

- project_dir: `/home/enduser/code/PeerTube-browser/`
- source (group map): `/home/enduser/code/PeerTube-browser/tests/config.json`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- HARVEST_FILE: `docs/project/plans/harvest-50-translate-generation-in-page-plan.md`

Record snapshot: `tests/last_test_validation.json` existed and was copied to `tests/last_test_validation.json.preharvest` (167431 bytes, `cmp`-identical) before anything else ran. No `.preharvest` was on disk before the copy.

Scope: the four tests this build wrote, as named by the build dispatch, not a whole-tree sweep:

- `tests/tmp/test_50_translate_generation_in_page_phase1.py`
- `tests/tmp/test_50_translate_generation_in_page_phase2.py`
- `tests/tmp/test_50_translate_generation_in_page_phase3.py`
- `tests/tmp/test_50_translate_generation_in_page_phase4.py`

Out of scope but present in `tests/tmp`: 29 `probe_*.py` files (among them `probe_50_phase1_rows.py`, `probe_50_phase2_enqueue.py`, `probe_50_phase2_observe.py`, `probe_50_phase3_client.py`, and the emptied `probe_phase4_compile.py` the phase 4 report asks to be deleted) and `__pycache__/`. None is a `test_*.py`, so none is collected. Step 7 moves only the four files in scope, so `tests/tmp` will not be empty afterwards unless the operator widens the disposal to the probes.

Collection: all four files collect. Each has a pytest-9.1.1 assertion-rewritten `.pyc` in `tests/tmp/__pycache__`, and each was the workflow's checkpoint run for its phase (phase 3's last run read "collected 47 items … 47 passed"). None needed a `validate_tests.py <path>` run to diagnose a collection failure. Item counts by reading the parametrisations: phase 1 61, phase 2 23, phase 3 47, phase 4 10; 141 in total.

## Step 2: inventory

### tests/tmp/test_50_translate_generation_in_page_phase1.py

Drives `engine/server/data/subtitles.py` (`fetch_subtitle_state`, `fetch_translate_heartbeat`, called directly) and `engine/server/api/handlers/internal_translate.py` (`handle_internal_translate`, through the `test_internal_translate.py` harness, with `now_ms` pinned on the module).

Module-level dependencies: imports `CUES`, `EN_LISTING`, `FR_LISTING`, `HOST`, `PEER_VIDEO`, `TRACK`, `TRACK_PATH`, `RecordingInstance`, `_handle`, `_handler_module`, `_server`, `_subtitles_db`, `whitelist` from `tests/active/test_internal_translate.py`; constants `VIDEO_ID`/`VIDEO_UUID`, `BODY`, `CAPTIONS`, `TRACK_FETCHES`, `NOW`, `RUNNING` (stored out of start order), `STORED_READY`, `BAD_AFTER`, `BEATS`, `BRANCHES`, `AFTERS`, `ZERO_CUES`, `REFUSED_ROWS`; helpers `_instance`, `_route`, `_damage`, `_claimed`, `_seed`.

Tests:
- `test_fetch_subtitle_state_gives_a_keys_state_and_raw_cues_json_or_none`
- `test_fetch_translate_heartbeat_gives_none_on_a_fresh_schema_then_the_last_beat`
- `test_available_is_true_only_for_a_heartbeat_0_to_15000_ms_old` (5 params)
- `test_a_closed_store_answers_none_and_not_available`
- `test_each_stored_state_answers_its_state_with_available_and_fetches_only_past_queued_and_running` (10 × 2 params)
- `test_a_running_key_answers_its_cues_from_after_with_the_stored_total_and_no_fetch` (5 params)
- `test_a_running_key_with_unset_empty_or_damaged_cues_answers_no_cues_and_total_0` (4 params)
- `test_after_that_is_not_a_non_negative_json_int_answers_400` (6 × 3 params)
- `test_an_unknown_video_with_a_bad_after_answers_404_video_not_found` (6 params)

### tests/tmp/test_50_translate_generation_in_page_phase2.py

Drives `engine/server/api/handlers/internal_translate.py` (`handle_internal_translate_enqueue`, and `handle_internal_translate` for the shared refusals) through the `test_internal_translate.py` harness, with `now_ms` pinned; and `engine/server/api/server.py` → `handlers/similar.py` dispatch for the bridge-gate test (a real Engine subprocess under `ENGINE_PY`).

Module-level dependencies: `conftest.ENGINE_PY`/`ENGINE_START_LOCK` (shared helper); imports `BRIDGE_TOKEN`, `CUES`, `DENIED_HOST`, `DENIED_VIDEO`, `ENGINE_SERVER`, `HEALTHY_WITHIN_SECONDS`, `HOST`, `PEER_VIDEO`, `STOP_WITHIN_SECONDS`, `TRACK`, `VARIANT_RUNNER`, `VIDEO_NOT_FOUND`, `HandlerRequest`, `RecordingInstance`, `_free_port`, `_handler_module`, `_post`, `_server`, `_set_denied`, `_subtitles_db`, `whitelist` from `test_internal_translate.py`; `SUBTITLE_QUEUE_CAP` from `server_config`; constants `VIDEO_ID`/`VIDEO_UUID`, `BODY`, `NOW`, `NONE_UNAVAILABLE`, `QUEUED`, `QUEUED_ROW`, `UNAVAILABLE_BEATS`, `FRESH_BEATS`, `MISSING`, `INVALID_JSON`, `REFUSED`; helpers `_route`, `_request` (raw-bytes bodies), `_enqueue`, `_state`, `_rows` (every column, read-only connection), `_write`, `_beat`, `_seed` (path-based).

Tests:
- `test_without_a_serving_worker_enqueue_answers_none_not_available_and_writes_no_row` (3 params)
- `test_a_closed_store_enqueue_answers_none_not_available_and_writes_no_row`
- `test_with_a_serving_worker_a_new_key_is_queued_under_its_canonical_key` (2 params)
- `test_with_a_serving_worker_a_stored_key_answers_its_state_and_its_row_is_unchanged` (5 params)
- `test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues`
- `test_a_store_error_from_the_enqueue_answers_503_and_writes_no_row`
- `test_enqueue_refuses_a_bad_body_or_unknown_video_exactly_as_the_state_route_does` (8 params)
- `test_enqueue_refuses_a_denylisted_host_exactly_as_the_state_route_does`
- `test_an_engine_routes_internal_translate_enqueue_behind_the_bridge_gate`

### tests/tmp/test_50_translate_generation_in_page_phase3.py

Drives `client/backend/server.py` (`_handle_translate_get`, `_serve_post`'s `/api/translate` branch, `_handle_translate_post`) and `client/backend/lib/engine_api_client.py` (`fetch_translate`, `request_translate`, `_translate_available`, `_checked_cues`), over HTTP through the real Client backend in front of a stand-in Engine.

Module-level dependencies: `conftest.RateLimiter` (shared helper); imports `_keyed_client_backend`, `_serving`, `_translate_get` from `tests/active/test_server.py`; constants `BRIDGE_TOKEN`, `STATE_ROUTE`, `ENQUEUE_ROUTE`, `VALID`, `BODY`, `FAILED`, `UNAUTHORIZED`, `RATE_LIMITED`, `NONE_AVAILABLE`, `NONE_UNAVAILABLE`, `QUEUED`, `READY_CUES`, `RUNNING_CUES`, `STATE_ANSWERS`, `AFTER_FORWARDED`, `AFTER_REFUSED`, `GET_ENGINE_ANSWERS`, `POST_REPLIES`, `KEYLESS_BODIES`, `BAD_BODIES`, `ENQUEUE_ANSWERS`; class `_RoutedEngine` (per-path replies, 404 `Not found` default); helpers `_engine`, `_translate_post`; fixture `bridge_token`.

Tests:
- `test_get_forwards_an_ascii_digit_after_to_the_engine_as_an_int_and_leaves_out_an_absent_or_blank_one`
- `test_get_refuses_an_after_that_is_not_ascii_digits_400_with_no_engine_call`
- `test_get_passes_each_engine_state_through_unchanged_with_its_available_flag` (7 × 2 params)
- `test_get_reads_an_engine_answer_without_available_as_not_available` (7 params)
- `test_get_answers_video_not_found_as_none_not_available_and_a_malformed_or_failed_answer_502` (11 params)
- `test_post_is_429_before_the_profile_and_body_checks_with_no_engine_call`
- `test_post_without_a_valid_profile_is_401_before_the_body_is_read_with_no_engine_call`
- `test_post_with_a_bad_body_is_400_with_no_engine_call_and_a_valid_one_reaches_the_enqueue_route_with_the_bridge_token`
- `test_post_returns_the_engine_enqueue_answer_mapped_for_the_page` (10 params)

### tests/tmp/test_50_translate_generation_in_page_phase4.py

Drives `client/frontend/src/pages/video-page/translate.ts` and `client/frontend/src/data/translate.ts` (with `data/profile.ts` for the key header and `ProfileKeyRejectedError`), bundled from `pages/video-page/index.ts` by esbuild and run in node.

Module-level dependencies: constants `FRONTEND`, `ESBUILD`, `BASE`, `HOST`, `TITLE`, `EMBED`, `KEY`, `TOGGLE`, `STATUS`, `OVERLAY`, `NO_TRANSLATION`, `WAITING`, `BUSY`, `STOP_WAIT`, `RUNNING_FIRST`, `RUNNING_MORE`, `FINAL`, `SCENARIOS`; scripts `EMBED_STUB` and `RUNNER` (fetch stub serving a queue of answers per `METHOD path`, `gets`/`wait`/`emit`/`click` steps); fixtures `bundle` (module scope) and `pages` (module scope, all eleven scenarios run concurrently in node); helpers `_state`, `_env`, `_page`, `_translate`, `_query`, `_asked`.

Tests:
- `test_a_none_state_from_a_serving_worker_sends_one_generation_request_with_the_video_and_key_and_no_second_while_polled`
- `test_a_none_state_without_a_serving_worker_sends_no_request_polls_nothing_and_reads_the_plan_48_message`
- `test_running_cues_are_asked_for_after_the_held_count_shown_at_their_positions_and_replaced_by_ready_which_ends_the_poll`
- `test_a_running_total_below_the_held_count_makes_the_next_poll_ask_from_zero`
- `test_failed_clears_the_overlay_and_its_lines_and_ends_the_poll`
- `test_busy_shows_its_label_and_is_not_polled`
- `test_a_none_answer_a_401_or_turning_translate_off_ends_the_poll` (3 params)
- `test_a_502_keeps_the_waiting_label_and_the_poll_asks_again`

## Step 3: classification

Subject files in `active`, one per production script: `test_subtitles.py` (`data/subtitles.py`), `test_internal_translate.py` (`handlers/internal_translate.py`), `test_server.py` (the Client backend's translate gateway), `test_frontend_translate.py` (the video page's translate modules). All four exist, so Step 5 creates no subject file. Searching `active` for `fetch_subtitle_state`, `fetch_translate_heartbeat`, `HEARTBEAT_FRESH_MS`, `handle_internal_translate_enqueue`, `request_translate`, `requestTranslate` and `after=` finds nothing: no active test asserts the state route's job states, `available`, `after`/`total`, the enqueue route, the Client POST, the Client `after` forwarding, or the page's request and poll. The overlaps found are two, both COMBINE. No active test is made wrong by plan 50 beyond what the build already updated (the `NONE`/`READY` constants and three retired `TRANSLATE_ENGINE_ANSWERS` rows), so there is no `REPLACES`. No production script named here is gone, so nothing is `SPENT`. No two in-scope tests assert the same behaviour.

### tests/tmp/test_50_translate_generation_in_page_phase1.py

- `test_fetch_subtitle_state_gives_a_keys_state_and_raw_cues_json_or_none`: **DURABLE** → `tests/active/test_subtitles.py`. The reader's None/(state, raw cues_json) contract and its keying on language and host are asserted nowhere in active.
- `test_fetch_translate_heartbeat_gives_none_on_a_fresh_schema_then_the_last_beat`: **DURABLE** → `tests/active/test_subtitles.py`. Active writes a heartbeat (the concurrent-writer test reads the row by SQL) but never calls the reader.
- `test_available_is_true_only_for_a_heartbeat_0_to_15000_ms_old`: **DURABLE** → `tests/active/test_internal_translate.py`. The only gate on the 0..15 000 ms window and its future guard.
- `test_a_closed_store_answers_none_and_not_available`: **DURABLE** → `tests/active/test_internal_translate.py`. The closed-store branch of `_read_key` is asserted nowhere else.
- `test_each_stored_state_answers_its_state_with_available_and_fetches_only_past_queued_and_running`: **DURABLE** → `tests/active/test_internal_translate.py`. The AC3 answer order across all six stored states with `available` both ways. Active's store-and-serve and none-path tests touch only the `no row`/`ready` branches, with `available` false.
- `test_a_running_key_answers_its_cues_from_after_with_the_stored_total_and_no_fetch`: **DURABLE** → `tests/active/test_internal_translate.py`. C2's slice-from-`after`, stored order, stored `total` and no fetch.
- `test_a_running_key_with_unset_empty_or_damaged_cues_answers_no_cues_and_total_0`: **DURABLE** → `tests/active/test_internal_translate.py`. `_stored_cues`' fallback for a running row.
- `test_after_that_is_not_a_non_negative_json_int_answers_400`: **DURABLE** → `tests/active/test_internal_translate.py`. The `after` type check (bool, negative, string, null, float) is new.
- `test_an_unknown_video_with_a_bad_after_answers_404_video_not_found`: **DURABLE** → `tests/active/test_internal_translate.py`. Active's `test_an_unknown_video_is_404_video_not_found_with_no_fetch` sends no `after`; this one pins that resolve runs before the `after` check.

### tests/tmp/test_50_translate_generation_in_page_phase2.py

- `test_without_a_serving_worker_enqueue_answers_none_not_available_and_writes_no_row`: **DURABLE** → `tests/active/test_internal_translate.py`. C1's gate, for the stale, future and absent beat.
- `test_a_closed_store_enqueue_answers_none_not_available_and_writes_no_row`: **DURABLE** → `tests/active/test_internal_translate.py`. The closed-store gate of the enqueue route.
- `test_with_a_serving_worker_a_new_key_is_queued_under_its_canonical_key`: **DURABLE** → `tests/active/test_internal_translate.py`. The route's write under the canonical key, every column. Active's `test_translate_worker.py` asserts the worker CLI's enqueue, not this route.
- `test_with_a_serving_worker_a_stored_key_answers_its_state_and_its_row_is_unchanged`: **DURABLE** → `tests/active/test_internal_translate.py`. `exists` → stored state, row untouched, at the route.
- `test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues`: **DURABLE** → `tests/active/test_internal_translate.py`. `cap` → `busy` (the raw `cap` never leaks), exactly at the cap.
- `test_a_store_error_from_the_enqueue_answers_503_and_writes_no_row`: **DURABLE** → `tests/active/test_internal_translate.py`. The 503 branch is asserted nowhere else.
- `test_enqueue_refuses_a_bad_body_or_unknown_video_exactly_as_the_state_route_does`: **DURABLE** → `tests/active/test_internal_translate.py`. The shared `_resolve_translate_key` refusals on the enqueue route; active asserts only the state route's unknown-video 404.
- `test_enqueue_refuses_a_denylisted_host_exactly_as_the_state_route_does`: **DURABLE** → `tests/active/test_internal_translate.py`. The denylist on the enqueue route, writing nothing; active's denylist test covers only the state route.
- `test_an_engine_routes_internal_translate_enqueue_behind_the_bridge_gate`: **COMBINE** with active `test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate` in `tests/active/test_internal_translate.py`. Both start the same variant Engine and assert a route's bridge gate; the active one also asserts the store's creation and the state route's gate, this one the enqueue route's 404-with-token / 401-without. Merging keeps all four assertions and saves one Engine start (up to 120 s healthy wait) per run.

### tests/tmp/test_50_translate_generation_in_page_phase3.py

- `test_get_forwards_an_ascii_digit_after_to_the_engine_as_an_int_and_leaves_out_an_absent_or_blank_one`: **DURABLE** → `tests/active/test_server.py`. `after` forwarding is new; active's GET tests send only `id`/`host`.
- `test_get_refuses_an_after_that_is_not_ascii_digits_400_with_no_engine_call`: **DURABLE** → `tests/active/test_server.py`. The ASCII-digit rule is new.
- `test_get_passes_each_engine_state_through_unchanged_with_its_available_flag`: **DURABLE** → `tests/active/test_server.py`. Active passes only `ready` with `available` false; the five other states and `available` true are new.
- `test_get_reads_an_engine_answer_without_available_as_not_available`: **DURABLE** → `tests/active/test_server.py`. The version-skew default; its active predecessor ("engine none") was retired by the build.
- `test_get_answers_video_not_found_as_none_not_available_and_a_malformed_or_failed_answer_502`: **COMBINE** with active `test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502` in `tests/active/test_server.py`. Same shape (one Engine reply → one visitor answer, one state-route call). They share one row, "route missing" (404 `Not found` → 502), identical in both. The active table owns engine 500, cues not a list, start true and text not a string; this one owns video not found → none/false, `available` a string/1/null, running `total` missing/-1/true/a string/1.5, and state `bogus`.
- `test_post_is_429_before_the_profile_and_body_checks_with_no_engine_call`: **DURABLE** → `tests/active/test_server.py`. POST ordering; active covers GET only.
- `test_post_without_a_valid_profile_is_401_before_the_body_is_read_with_no_engine_call`: **DURABLE** → `tests/active/test_server.py`. POST 401-before-body.
- `test_post_with_a_bad_body_is_400_with_no_engine_call_and_a_valid_one_reaches_the_enqueue_route_with_the_bridge_token`: **DURABLE** → `tests/active/test_server.py`. POST body validation and the bridge call to the enqueue route.
- `test_post_returns_the_engine_enqueue_answer_mapped_for_the_page`: **DURABLE** → `tests/active/test_server.py`. `request_translate`'s mapping, including `busy`, 503 and an old Engine's 404.

### tests/tmp/test_50_translate_generation_in_page_phase4.py

All DURABLE → `tests/active/test_frontend_translate.py`; that file asserts the plan 48 page (toggle, overlay, one GET, the none message with no `available`) and nothing of the request or the poll.

- `test_a_none_state_from_a_serving_worker_sends_one_generation_request_with_the_video_and_key_and_no_second_while_polled`: **DURABLE**. C1, exactly one POST with body and key.
- `test_a_none_state_without_a_serving_worker_sends_no_request_polls_nothing_and_reads_the_plan_48_message`: **DURABLE**. C1 with `available` false. Active's `test_a_none_state_reads_no_english_translation_...` reads the message from a `none` with no `available` and counts one request; it does not split GET from POST or wait past the backoff, so it would not catch a POST or a poll.
- `test_running_cues_are_asked_for_after_the_held_count_shown_at_their_positions_and_replaced_by_ready_which_ends_the_poll`: **DURABLE**. C2's `after` = held count, re-sort, ready replacing the list.
- `test_a_running_total_below_the_held_count_makes_the_next_poll_ask_from_zero`: **DURABLE**. `dropRunning` on a lower total.
- `test_failed_clears_the_overlay_and_its_lines_and_ends_the_poll`: **DURABLE**. The ended-state reset.
- `test_busy_shows_its_label_and_is_not_polled`: **DURABLE**. `applyRequest`'s busy branch.
- `test_a_none_answer_a_401_or_turning_translate_off_ends_the_poll`: **DURABLE**. The three stop paths of the poll chain.
- `test_a_502_keeps_the_waiting_label_and_the_poll_asks_again`: **DURABLE**. The retry path.

## Step 4: harvest plan

Counts (test functions; parametrised items in brackets): **DURABLE 33** (129 items), **COMBINE 2** (12 items from scope, merged into 2 active tests), **REPLACES 0**, **REDUNDANT 0**, **SPENT 0**. Total 35 functions, 141 items. After the merge the four subject files gain 33 tests and, net, 139 items: the 129 DURABLE items, plus 10 new rows on the merged gateway table (5 items become 15; the duplicate "route missing" row is kept once), plus nothing for the enqueue bridge assertions, which fold into the existing Engine-start item. Step 8's `--compare` should therefore show 2 test ids departing (the two retired active functions, 1 + 5 items) and the two survivors' ids appearing (1 + 15 items) beside the 129 moved items.

New subject files: **none**. All four destinations exist and are already mapped.

DURABLE, by destination:

- `tests/active/test_subtitles.py` (2 tests, 2 items): `test_fetch_subtitle_state_gives_a_keys_state_and_raw_cues_json_or_none`, `test_fetch_translate_heartbeat_gives_none_on_a_fresh_schema_then_the_last_beat`. They reuse the file's `_subtitles` opener and `HOST`, and bring a copy of `_damage` plus an inline enqueue/claim/`store_running_cues` seed; nothing is imported from `test_internal_translate.py`.
- `tests/active/test_internal_translate.py` (15 tests, 81 items): phase 1's other seven tests and phase 2's eight DURABLE tests. Phase 1 and phase 2 helpers collide by name and are unified once: one `NOW`, `BODY`, `VIDEO_ID`/`VIDEO_UUID`, `CAPTIONS`, `TRACK_FETCHES`; one `_route(instance, monkeypatch)` (phase 2 passes `RecordingInstance()`); one connection-based `_seed(store, row)` with phase 1's `RUNNING`/`STORED_READY`, which phase 2's path-based callers wrap in open/close; plus `_damage`, `_claimed`, `_instance`, `_beat`, `_rows` (every column, beside the existing `_stored`), `_write`, `_request`, `_enqueue`, `_state`, `SUBTITLE_QUEUE_CAP`, `NONE_UNAVAILABLE`, `QUEUED`, `QUEUED_ROW`, `MISSING`, `INVALID_JSON` and the parametrisation tables. The existing `whitelist`, `_server`, `_subtitles_db`, `HandlerRequest`, `RecordingInstance`, `_handler_module`, `_set_denied` are reused.
- `tests/active/test_server.py` (8 tests, 36 items): phase 3's four GET tests use the existing `_translate_engine` stub (they hit the state route only), the existing `translate_bridge_token` fixture (same token value) and the existing `TRANSLATE_VALID`/`TRANSLATE_FAILED`/`TRANSLATE_UNAUTHORIZED`/`TRANSLATE_RATE_LIMITED`. The four POST tests need a stub that answers per path, so `_RoutedEngine`/`_engine` come across as `_RoutedTranslateEngine`/`_routed_translate_engine`, with `_translate_post`; phase 3's own `bridge_token` fixture and duplicate constants are dropped.
- `tests/active/test_frontend_translate.py` (8 tests, 10 items): all of phase 4. The active runner serves one fixed answer for any method and has no answer queue or `gets` step, and its embed stub keeps a different state shape, so phase 4's harness comes across as a second one under distinct names: `GENERATION_EMBED_STUB`, `GENERATION_RUNNER`, `GENERATION_SCENARIOS`, fixtures `generation_bundle` and `generation_pages`, helpers `_generation_env`, `_generation_page`, `_translate_by_method` (the file already has `_translate_requests`), `_query`, `_asked`. It reuses the file's `FRONTEND`, `ESBUILD`, `BASE`, `HOST`, `TITLE`, `EMBED`, `KEY`, `TOGGLE`, `STATUS`, `OVERLAY`, `NO_TRANSLATION`. The group's run time rises from about 14 s to about 35 s (the eleven scenarios run concurrently; the slowest waits out its backoff).

COMBINE:

- Phase 2 `test_an_engine_routes_internal_translate_enqueue_behind_the_bridge_gate` + active `test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate` (`tests/active/test_internal_translate.py`). Start from the active test; lift in the enqueue route's two assertions: with the token, `/internal/translate/enqueue` for an unknown video answers `(404, {"error": "Video not found"})`; without it, `(401, {"error": "Unauthorized"})`. Survivor: `test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_and_its_enqueue_behind_the_bridge_gate`. The emptied active test is retired to `tests/archive/50_translate_generation_in_page/test_internal_translate.py`.
- Phase 3 `test_get_answers_video_not_found_as_none_not_available_and_a_malformed_or_failed_answer_502` + active `test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502` (`tests/active/test_server.py`). Start from the active test and its `TRANSLATE_ENGINE_ANSWERS` table; lift in the ten rows it lacks: video not found → `(200, {"state": "none", "available": false})`, `available` a string / 1 / null → 502, running `total` missing / -1 / true / a string / 1.5 → 502, state `bogus` → 502. "route missing" is in both and is kept once. The one-call-to-the-state-route assertion is the same in both. Survivor: `test_the_engine_answer_reaches_the_visitor_as_none_not_available_or_a_fixed_502` (15 items). The emptied active test is retired to `tests/archive/50_translate_generation_in_page/test_server.py`.

Active tests retired (moved to `tests/archive/50_translate_generation_in_page/`, functions cut, the files themselves stay):
- `tests/active/test_internal_translate.py::test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate` (merged into the survivor above)
- `tests/active/test_server.py::test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502` (merged into the survivor above)

No active file is emptied, so no `test_groups` entry is dropped.

`test_groups` changes in `tests/config.json`:
- `test_frontend_translate.py`: add `client/frontend/src/data/profile.ts`. The harvested page tests assert the POST carries the stored key through `profileHeaders()` and that a 401 poll ends the chain through `ProfileKeyRejectedError`, both from `data/profile.ts`, which the entry does not claim.
- `test_server.py`: add `client/backend/lib/request_context.py`. The harvested POST tests assert the visitor's `X-Request-ID` reaches the enqueue route unchanged through `resolve_request_id`; the entry already claims `server.py` and `engine_api_client.py` but not this module.
- `test_internal_translate.py` and `test_subtitles.py`: unchanged. The first already claims `internal_translate.py`, `subtitles.py`, `server_config.py` (`SUBTITLE_QUEUE_CAP`), `similar.py` (the enqueue dispatch) and `server.py`; the second claims `subtitles.py`.
- Step 5.c's `--audit-map` has the final word on the two additions; if it argues against either, or for another file, that is recorded there.

Docstrings: every module and test docstring naming "plan 50 phase N" or "checkpoint" is rewritten to state the rule it gates, and each destination's module docstring gains the rules it now covers. The `# C1`/`# C2` markers are dropped.

Mutation cost: Step 6 runs 35 mutations: `subtitles.py` 2, `internal_translate.py` about 16 (the COMBINE's enqueue assertions are reached through `similar.py`'s dispatch branch), `engine_api_client.py`/`server.py` 9, `pages/video-page/translate.ts`/`data/translate.ts` 8. Each phase 4 run rebuilds the bundle and runs all eleven scenarios (about 25 s), and the Engine-start test about 10–30 s.

Stays out: nothing is REDUNDANT or SPENT. Step 7 moves all four scope files to `delete_me/`. The 29 out-of-scope `probe_*.py` files stay in `tests/tmp` unless the operator widens the disposal.

Approval: per this build's dispatch, no operator approval is sought at this step and AskUser is not used; a second turn carries the plan out. Nothing has moved and the map is unchanged.

## Step 5: applied

Moved (DURABLE), each into its subject file, harvest-era names and docstrings rewritten to state the rule gated, `# C1`/`# C2` markers dropped:

- `tests/active/test_subtitles.py`: the 2 phase 1 reader tests, with a local `_damage(conn, video_id, cues_json)` and an inline enqueue/claim/`store_running_cues` seed; reuses `_subtitles` and `HOST`. Module docstring gains a "Readers" section.
- `tests/active/test_internal_translate.py`: phase 1's 7 state-route tests and phase 2's 8 enqueue tests, with one set of `VIDEO_ID`/`VIDEO_UUID`, `BODY`, `CAPTIONS`, `TRACK_FETCHES`, `NOW`, `RUNNING`, `STORED_READY`, `BAD_AFTER`, `QUEUED`, `QUEUED_ROW`, `MISSING`, `INVALID_JSON`, one `_route(instance, monkeypatch)`, one connection-based `_seed` (the stored-key test opens, seeds and closes around it), plus `_instance`, `_damage`, `_claimed`, `_beat`, `_rows`, `_write`, `_request`, `_enqueue`, `_state`; `SUBTITLE_QUEUE_CAP` imported from `server_config` after the path setup. Phase 2's `NONE_UNAVAILABLE` was dropped for the file's identical `NONE`, whose comment now says so. Module docstring gains "Job state" and "Enqueue" sections and the startup line covers the enqueue route.
- `tests/active/test_server.py`: phase 3's 4 GET tests on the existing `_translate_engine`/`translate_bridge_token`, and its 4 POST tests on `_RoutedTranslateEngine`/`_routed_translate_engine`/`_translate_post`; constants carried under a `TRANSLATE_` prefix (`TRANSLATE_STATE_ROUTE`, `TRANSLATE_ENQUEUE_ROUTE`, `TRANSLATE_BODY`, `TRANSLATE_STATE_ANSWERS`, `TRANSLATE_AFTER_FORWARDED`, `TRANSLATE_AFTER_REFUSED`, `TRANSLATE_POST_REPLIES`, `TRANSLATE_KEYLESS_BODIES`, `TRANSLATE_BAD_BODIES`, `TRANSLATE_ENQUEUE_ANSWERS`, ...); phase 3's own `bridge_token` fixture dropped. Docstring's translate gateway section extended and a "generation request" section added.
- `tests/active/test_frontend_translate.py`: phase 4's 8 tests on a second harness, `GENERATION_EMBED_STUB`, `GENERATION_RUNNER` (byte-identical to phase 4's runner apart from two comments losing "the plan's"), `GENERATION_SCENARIOS`, fixtures `generation_bundle`/`generation_pages`, helpers `_state`, `_generation_env`, `_generation_page`, `_translate_by_method`, `_query`, `_asked`; reuses the file's `FRONTEND`, `ESBUILD`, `BASE`, `HOST`, `TITLE`, `EMBED`, `ORIGINAL`, `KEY`, `TOGGLE`, `STATUS`, `OVERLAY`, `NO_TRANSLATION`. Docstring gains "Generation request" and "State poll" sections and a paragraph on the second runner.

COMBINE, merged:

- `test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_and_its_enqueue_behind_the_bridge_gate` (test_internal_translate.py): the active Engine-start test plus phase 2's two enqueue assertions (404 `Video not found` with the token, 401 without).
- `test_the_engine_answer_reaches_the_visitor_as_none_not_available_or_a_fixed_502` (test_server.py): `TRANSLATE_ENGINE_ANSWERS` gains phase 3's ten rows (video not found → none/false; available a string, 1, null; running total missing, -1, true, a string, 1.5; state bogus), "route missing" kept once: 15 items. The "available null" row uses `{**TRANSLATE_READY, "available": None}`.

Retired to `tests/archive/50_translate_generation_in_page/` (functions cut, module skipped, retirement reason in its docstring): `test_internal_translate.py` (the old Engine-start test) and `test_server.py` (the old 5-row Engine-answer test with its table quoted).

5.c `test_groups`: `test_server.py` += `client/backend/lib/request_context.py`; `test_frontend_translate.py` += `client/frontend/src/data/profile.ts`. No entry added or dropped. `--audit-map` exit 0; its MISSING findings for the touched groups (`engine/server/data/time.py`, `engine/server/db/subtitles.db`, `client.log`) are a pinned clock and runtime files, not subjects of the moved tests, so no further entry.

Baseline after the move, before any mutation: test_subtitles 2 moved passed; test_internal_translate 137 passed; test_server translate tests 56 passed; test_frontend_translate 20 passed.

## Step 6: mutations

Each: `cp <file> <file>.bak.<tag>`, mutate by `sed`, run only that test (`-k <name>`), confirm the named assertion red, restore from the copy, `diff` clean, copy moved to `delete_me/`, re-run green. All 35 felled their assertion and returned green.

- T1 subtitles.py:95 `fetch_subtitle_state` returns `(row[0], None)` → `assert ('running', None) == ('running', '{not json')`.
- T2 subtitles.py:101 `fetch_translate_heartbeat` no-row → 0 → `assert 0 is None`.
- I1 internal_translate.py:210 future guard `0 <=` dropped → "1 ms ahead" answers available true (1 of 5 red).
- I2 :219 closed store `return None, True` → closed-store answer reads available true.
- I3 :294 `queued` branch disabled → queued fresh/no beat answers wrong (2 of 20 red).
- I4 :299 `cues[after:]` → `cues` → after 1, 3, 5 red.
- I5 :297 `running and stored` → all 4 unset/empty/damaged cases fetch and answer ready.
- I6 :284 bool check dropped → `after` true/false × 3 rows answer 200 (`assert 200 == 400`).
- I7 an `after` check inserted before resolve (after :258) → all 6 bad `after` on an unknown video answer 400 not 404.
- I8 :322 heartbeat gate dropped → all 3 unavailable beats answer queued.
- I9 :328 closed-store answer `available: conn is None` → reads true.
- I10 :317 keyed on the uuid (`_, _, instance, canonical_id`) → `assert [('u-1', ...)] == [('v-1', ...)]`, both items.
- I11 :331 `else state` → `else "queued"` → 4 of 5 stored states answer queued.
- I12 :331 `"busy"` → `kind` → `cap` leaks instead of busy.
- I13 :325 503 → 200 → `assert 200 == 503`.
- I14 :255 `or not raw_host` dropped → blank host answers `Invalid host` not `Missing id or host`.
- I15 :271 denylist check disabled → enqueue answers queued for the denied host instead of 404.
- C1 similar.py:462 enqueue dispatch path renamed → merged Engine-start test: `assert (404, {'error': 'Not found'}) == (404, {'error': 'Video not found'})` on the enqueue-with-token assertion.
- S1 client server.py:1088 `after` forwarded as the string → Engine log body `after` '3' ≠ 3.
- S2 server.py:1082 `isascii()` dropped → the Arabic-Indic digit reaches the Engine (`seen == [after-1 only]` red).
- S3 engine_api_client.py:194 `available` forced False → 7 `available` items red.
- S4 engine_api_client.py:163 missing `available` defaults True → all 7 red.
- S5 engine_api_client.py:199 bool check on `total` dropped → merged table's "running total true" row answers 200 not 502.
- S6 server.py:537 POST rate-limit check disabled → limited requests are not 429.
- S7 server.py:1096 profile check disabled → keyless/wrong-key bodies answer 400/200, not 401.
- S8 server.py:1106 length cap +1 → 201-character id/host not refused 400.
- S9 engine_api_client.py:23 `busy` dropped from `TRANSLATE_REQUEST_STATES` → busy item answers 502.
- F1 data/translate.ts:75 `profileHeaders()` dropped from the POST → `assert None == 'translate-profile-key'`.
- F2 pages/video-page/translate.ts:127 `&& state.available` dropped → unavailable page POSTs (`assert [...] == []`).
- F3 :210 poll sends `after` 0 → `after` ['0'] where ['3'] expected.
- F4 :175 total-below-held reset disabled → `[['2'], ['2']] == [['2'], ['0']]`.
- F5 :195 ended-state `showText("")` removed → failed snapshot overlay `['Seven running', False] == ['', True]`.
- F6 :153 busy shows WAITING → `'Waiting for translation…' == 'The translat...to try again.'`.
- F7 :216 401 treated as a retryable error → stop-401 makes a third GET (`assert 3 == 2`), the none and off items stay green.
- F8 :222 error retry removed → 502 scenario stops at 2 GETs (`assert 2 == 3`).

Bytecode caveat met during the loop: I10's first green re-run failed and I13's first run did not go red. Both mutations keep the file's byte size, and the mutate and restore fell in the same second, so CPython's mtime+size `.pyc` check served stale bytecode. Neither result was about the test. The driver then waited 1.1 s before each write, and I10 and I13 were re-run whole: I10 red then green, I13 red (`assert 200 == 503`) then green. Their first-run copies are kept as `delete_me/internal_translate.py.bak.I10.run1` and `.I13.run1`. All earlier results were sound: each went red on the mutant and green on the restored code, which a stale cache could not have produced. The whole test_internal_translate group then passed (137). No `.bak` from this harvest remains under the production tree (`engine/server/db/whitelist.db.bak-20261002-212806` predates it).

## Step 7: disposal

Moved to `delete_me/`: the four `tests/tmp/test_50_translate_generation_in_page_phase{1..4}.py`; no name collided. `tests/tmp` holds none of them; it still holds the 29 out-of-scope `probe_*.py`, `test_probe_findcue_unsorted.py` and `__pycache__/`.

## Step 8: closing run

`tests/last_test_validation.json.preharvest` moved back over the record, then `validate_tests.py --compare` (no tier). Groups run: test_frontend_translate 20 passed, test_internal_translate 137 passed, test_search_fusion 10 passed (unmapped, always runs), test_server 155 passed, test_static_page_visit_logs 10 passed, test_subtitles 7 passed; the rest carried forward as unchanged. Gone: exactly the 6 retired ids (the old Engine-start test, and the old Engine-answer test's 5 rows). Appeared: the moved tests and the two merged survivors (15 rows on the Engine-answer table). Net per group: test_internal_translate +81, test_server +46, test_subtitles +2, test_frontend_translate +10, total +139 as planned. A follow-up `--failures-by-cause` reported no failing tests in the merged record (it also ran and banked test_search_fusion, 10 passed). Only the last 80 lines of the `--compare` output were read, so its header sections (new reds, no-longer-reds) were not seen directly. The green record is the evidence against new reds. Why test_static_page_visit_logs was selected was not established; it maps `client/backend/server.py`, which was mutated and restored byte-identical.
