# Harvest — 15 tighten response defaults

## Resolved paths (from `--show-config`, bootstrap gate clear: `defaulted` empty, `conflicts` empty)

- project_dir: /home/enduser/code/PeerTube-browser
- active: tests/active
- working: tests/tmp
- plans: docs/project/plans
- delete_me: delete_me
- archive: tests/archive
- record: tests/last_test_validation.json
- Snapshot: tests/last_test_validation.json.preharvest (taken before any run)

## Scope (the tests build 15 wrote)

- tests/tmp/test_15_tighten_response_defaults_phase1.py
- tests/tmp/test_15_tighten_response_defaults_phase2.py
- tests/tmp/test_15_tighten_response_defaults_phase3.py
- tests/tmp/test_15_tighten_response_defaults_phase4.py

Resumed session (harvest invoked with empty scope): scope widened to every `test_*.py` under tests/tmp, adding:
- tests/tmp/test_probe_phase2.py
- tests/tmp/test_probe_phase3.py
- tests/tmp/test_probe_phase4.py

Out of scope and left in tests/tmp: probe_*.py (not `test_*.py`), __pycache__.

Record note: tests/last_test_validation.json was rebanked at 08:20 by a `tests/active/test_blocks.py` run unrelated to the harvest (after the 08:00 snapshot). The snapshot is still the pre-harvest state; Step 8 restores it, so test_blocks.py re-runs.

## Inventory

### tests/tmp/test_15_tighten_response_defaults_phase1.py
Drives client/backend/server.py (`parse_cors_origins`, `ClientBackendServer`) and client/backend/lib/http_utils.py (`_send_cors_headers` via respond_json/respond_bytes/respond_options). Depends on: CLOSED_ENGINE, LISTED, SECOND, BOTH, UNLISTED, BLOCK_REMOVE, `_echo`, `_preflight_echo`, `_client` (live Client holding cors_origins), `_raw`, `_cors`, `_star_values`. Collects.
- test_parse_cors_origins_keeps_exact_origins_only — DURABLE → tests/active/test_server.py. No active test asserts parse_cors_origins.
- test_server_holds_trailing_cors_origins — DURABLE → tests/active/test_server.py. Constructor plumbing of cors_origins is asserted nowhere else.
- test_no_listed_origin_sends_no_cors_headers — DURABLE → tests/active/test_server.py. No active test reads access-control-* headers.
- test_listed_origins_are_echoed_with_vary_and_preflight_max_age — DURABLE → tests/active/test_server.py. Echo, Vary and preflight max-age asserted nowhere else.
- test_unlisted_origin_gets_no_cors_headers — DURABLE → tests/active/test_server.py. Exact-match refusal (case, trailing slash, `*`, absent) asserted nowhere else.
- test_error_and_bytes_responses_echo_listed_origin — DURABLE → tests/active/test_server.py. respond_json-401 and respond_bytes-204 echo asserted nowhere else.

### tests/tmp/test_15_tighten_response_defaults_phase2.py
Drives engine/server/api/server_config.py (`RECOMMENDATIONS_DEBUG_ENABLED`), engine/server/api/handlers/similar.py (`_handle_similar` 403), engine/server/api/http_utils.py (no CORS) via the live `engine` fixture. Depends on: VAR, ORIGIN, DISABLED, PRINT_FLAG, `_env`, `_DEBUG_CHILD`, `_handle`, `_raw`, `_cors`; conftest ENGINE_PY, ROOT, engine. Collects.
- test_flag_is_true_only_for_1_true_or_yes — DURABLE → tests/active/test_server_config.py. No active test reads RECOMMENDATIONS_DEBUG_ENABLED.
- test_debug_request_is_refused_403_unless_the_flag_is_set — DURABLE → tests/active/test_similar.py. The 403 refusal is asserted nowhere in active.
- test_no_engine_response_carries_a_cors_header — DURABLE → tests/active/test_similar.py. No active test reads Engine access-control-* headers; test_similar.py already claims engine http_utils.py and uses the live engine (~28 /recommendations calls per session, adding 2 stays under the 60/min limit).
- test_engine_started_with_the_flag_returns_debug_rows — REDUNDANT. tests/active/test_profiles.py `_upnext_profile` already asserts a debug=1 /recommendations answers 200 with rows[0].debug.profile on the fixture Engine; the env-dependence is carried by the two DURABLE tests above.

### tests/tmp/test_15_tighten_response_defaults_phase3.py
Drives client/backend/server.py (`_respond_engine_failure`, `_publish_to_engine_bridge`). Depends on: CLOSED_ENGINE, SENTINEL, LIKES, SEED, BRIDGE_FIXED, DROPPED_TEXT, `_StubEngine`, `_engine`, `_client` (profile with one like), `_raw`, `_error_messages`, `_error_events`, ROUTES. Collects.
- test_client_likes_502_is_fixed_text_and_engine_error_is_logged — DURABLE → tests/active/test_server.py. No active test asserts 502 body text or ERROR logging of Engine failures.
- test_other_engine_502s_carry_no_engine_text — DURABLE → tests/active/test_server.py. Per-site fixed operation text asserted nowhere else.
- test_user_action_bridge_error_carries_no_exception_text — DURABLE → tests/active/test_server.py. bridge_error text asserted nowhere else.
- test_user_action_bridge_http_error_carries_no_engine_text — DURABLE → tests/active/test_server.py. Fixed `engine bridge HTTP 500` asserted nowhere else.
- test_bridge_publish_to_closed_port_returns_fixed_text_and_logs_cause — DURABLE → tests/active/test_server.py. `_publish_to_engine_bridge` return and engine.bridge log asserted nowhere else.
- test_client_likes_malformed_json_still_answers_400 — DURABLE → tests/active/test_server.py. Client `Invalid JSON body` 400 asserted nowhere in active.

### tests/tmp/test_15_tighten_response_defaults_phase4.py
Drives engine/server/api/logging_profiles.py (`EngineJsonFormatter` traceback), engine/server/api/handlers/similar.py (fixed 500), engine/server/api/handlers/internal_events.py (fixed 500). Depends on: TRACEBACK_HEAD, SIMILAR_FAILED, INGEST_FAILED, INGEST_CASES, `_FORMAT_CHILD`, `_WIRE`, `_SIMILAR_CHILD`, `_INGEST_CHILD`, `_json_lines`, `_tracebacks`, `_engine_child`, BOOM, VALUE, NEAR, BAD_REQUEST, SIMILAR_CASES; conftest ENGINE_PY, ROOT. Collects.
- test_formatter_writes_the_traceback_of_an_exception_record_only — DURABLE → NEW tests/active/test_logging_profiles.py. No subject file exists for logging_profiles.py; no active test asserts the traceback key.
- test_recommendations_failure_answers_a_fixed_500_and_logs_its_traceback — DURABLE → tests/active/test_similar.py. Fixed 500 and the SIMILAR_BAD_REQUEST_ERRORS 400 split asserted nowhere else.
- test_ingest_failure_answers_a_fixed_500_and_logs_its_traceback — DURABLE → tests/active/test_internal_events.py. Fixed ingest 500 asserted nowhere else.

### tests/tmp/test_probe_phase2.py, test_probe_phase3.py, test_probe_phase4.py
Each is a one-line comment/docstring stub with no test functions (collects 0 tests). No verdict per function applies; the files are SPENT scaffolding and go to delete_me in Step 7.

## Counts
DURABLE 18 (earlier record said 16; the listed tests are 6+3+6+3 = 18, all shown to the operator by name), REDUNDANT 1, REPLACES 0, COMBINE 0, SPENT 0 (plus 3 empty SPENT stub files). Retired: none.

## Step 5 applied
- test_server.py: 12 tests + helpers (`_wire`, `_cors_client`, `_failing_engine`, `_liking_client`, ...), reusing `_serving`; docstring extended.
- test_server_config.py: flag test; `_run` gained a `var` parameter.
- test_similar.py: 403 test, CORS test (live engine), fixed-500 test.
- test_internal_events.py: fixed-500 ingest test.
- NEW test_logging_profiles.py: formatter test.
- test_groups edited as proposed. `--audit-map` exit 0; its MISSING/UNRESOLVABLE/BARREN advisories all concern pre-existing entries, none the moved tests.
- All five subject files green in their new homes (1, 19, 9, 68, 27 passed).

## Step 6 mutations (backups `<file>.bak-H15-M<n>`, restored diff-exact, moved to delete_me/, green after restore)
- M1 server.py:173 `*` no longer dropped → test_parse_cors_origins_keeps_exact_origins_only: 3 `*` cases fail `parsed == expected`.
- M2 server.py:230 `cors_origins = frozenset()` → test_server_holds_trailing_cors_origins: `servers[0].cors_origins == CORS_BOTH`.
- M3 lib/http_utils.py:36 empty set echoes any Origin → test_no_listed_origin_sends_no_cors_headers: `_cors(got[1]) == {}`.
- M4 lib/http_utils.py:42 max-age 60 → test_listed_origins_are_echoed_with_vary_and_preflight_max_age: `_cors(preflight[1]) == _cors_preflight_echo(origin)`.
- M5 lib/http_utils.py:36 `origin.rstrip("/")` → test_unlisted_origin_gets_no_cors_headers: `_cors(got[1]) == {}` for `http://127.0.0.1:5173/`.
- M6 lib/http_utils.py:66 respond_bytes sends no CORS → test_error_and_bytes_responses_echo_listed_origin: `_cors(removed[CORS_SECOND][1]) == _cors_echo(CORS_SECOND)`.
- M7 server.py:415 502 body carries exc → test_client_likes_502_is_fixed_text_and_engine_error_is_logged: `json.loads(raw) == {"error": "Engine metadata failed"}`.
- M8 server.py:974 "lookup"→"resolve" → test_other_engine_502s_carry_no_engine_text[block-add]: `error == expected`.
- M9 server.py:1071 unavailable text carries exc → test_user_action_bridge_error_carries_no_exception_text: `bridge_error == BRIDGE_FIXED`.
- M10 server.py:1067 HTTP text carries detail → test_user_action_bridge_http_error_carries_no_engine_text: `bridge_error == "engine bridge HTTP 500"`.
- M11 server.py:1070 log loses str(exc) → test_bridge_publish_to_closed_port_returns_fixed_text_and_logs_cause: `error != BRIDGE_FIXED` assertion.
- M12 lib/http_utils.py:92 malformed JSON → {} → test_client_likes_malformed_json_still_answers_400: `status == 400` (got 200).
- M13 server_config.py:49 accepts "on" → test_flag_is_true_only_for_1_true_or_yes[on]: `stdout == expected`.
- M14 similar.py:935 `if False:` first applied then restored unrun on an operator interrupt (backup delete_me/similar.py.bak-H15-M14); redone as M14b → test_debug_request_is_refused_403_unless_the_flag_is_set: `disabled["cases"][0] == {"respond": [DEBUG_DISABLED], ...}`.
- M15 engine http_utils.py respond_json/respond_options send `access-control-allow-origin: *` → test_no_engine_response_carries_a_cors_header: all 6 cases fail the no-`access-control-` assertion.
- M16 similar.py:1023 500 body `str(exc)` → test_recommendations_failure_answers_a_fixed_500_and_logs_its_traceback: `value == SIMILAR_FAILED`. M16b similar.py:1025 `logging.exception`→`logging.error` → same test: the traceback assertion (RuntimeError case).
- M17 internal_events.py:79/81 500 body `str(exc)` → test_ingest_failure_answers_a_fixed_500_and_logs_its_traceback: `(statuses, body) == INGEST_FAILED`. M17b internal_events.py:80 `logging.exception`→`logging.error` → same test: the traceback assertion.
- M18 logging_profiles.py:224 `if False:` → test_formatter_writes_the_traceback_of_an_exception_record_only: `traceback.startswith(TRACEBACK_HEAD)`.

Every mutation felled the named assertion; none needed reclassification. No `.bak-H15*` left under client/ or engine/.

## Step 7
Moved to delete_me/ (no collisions): test_15_tighten_response_defaults_phase1-4.py, test_probe_phase2-4.py. tests/tmp keeps only out-of-scope probe_*.py (incl. probe_random_*.py, which appeared during the harvest) and __pycache__.

## Step 8
Snapshot restored, `validate_tests.py --compare`: 9 of 20 groups ran (11 unchanged carried), 151 passed, 0 failed, exit 0.
- Appeared: 42 harvested test ids (the 18 tests with their parameters). No departures, no new red, nothing newly green.
- Also appeared: 10 test_search_fusion.py ids. Not from this harvest: that group had never banked in the pre-harvest record ("no record"). It still has no test_groups entry (pre-existing).
- test_dislike_profile.py, test_frontend_reactions.py, test_frontend_videos.py re-ran because files they claim changed outside this harvest (uncommitted build work); all green.

## Proposed test_groups changes
- ADD `test_logging_profiles.py`: ["engine/server/api/logging_profiles.py"]
- `test_similar.py`: add "engine/server/api/logging_profiles.py" (the 500 test reads the traceback it renders)
- `test_internal_events.py`: add "engine/server/api/logging_profiles.py" (same)
- `test_server.py`, `test_server_config.py`: unchanged (already claim client server.py + lib/http_utils.py, and server_config.py)

## Approval
Approved as planned by the operator (resumed session), including the 3 SPENT stubs.
