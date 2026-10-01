# Harvest - 19-timestamped-request-logs

Step 10 of build `docs/project/plans/20-19-timestamped-request-logs.md`, run under `.un/skills/devsecops/workflows/harvest.md`.

## Step 1 - Trees and scope

Bootstrap gate clear: `--show-config` reports `defaulted: []`, `conflicts: []`.

- project_dir: `/home/enduser/code/PeerTube-browser/.worktrees/19`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- config (holds `test_groups`): `.un/skills/devsecops/config.json`

Snapshot: `tests/last_test_validation.json.preharvest` taken before any harvest run.

Scope: the four checkpoints the plan records under its phases, plus this build's probes in `tests/tmp` (untracked, written by build 19):

- `tests/tmp/test_19_timestamped_request_logs_phase1.py`
- `tests/tmp/test_19_timestamped_request_logs_phase2.py`
- `tests/tmp/test_19_timestamped_request_logs_phase3.py`
- `tests/tmp/test_19_timestamped_request_logs_phase4.py`
- probes: `tests/tmp/test_probe_19_p1.py`, `tests/tmp/test_probe_19_p2.py`, `tests/tmp/test_probe_19_p3.py`, `tests/tmp/test_probe_19_p3_values.py`, `tests/tmp/test_probe_19_p4.py`, `tests/tmp/test_probe_step8_home_overlap.py`, `tests/tmp/probe_caplog_formatter.py`, `tests/tmp/probe_client_tb.py`, `tests/tmp/probe_engine_render.py`, `tests/tmp/probe_fromtimestamp.py`, `tests/tmp/probe_step8_dataset.py`, `tests/tmp/probe_step8_pager.py`, `tests/tmp/probe_ts_values.py`

## Step 2 - Inventory

### tests/tmp/test_19_timestamped_request_logs_phase1.py
Drives `engine/server/api/logging_profiles.py` (child process, `TZ=Asia/Kathmandu`) and the session Engine (`engine` fixture from conftest).
- `test_engine_ts_is_record_created_in_utc_with_milliseconds`
- `test_engine_request_ts_never_decreases_from_access_start_to_access` (uses `engine`)
- Module-level: `API_DIR`, `TS_RE`, `HOUR`, `OFF_UTC_ZONE`, `LOG_WAIT_SECONDS`, `_ENGINE_CHILD`, `_epoch`, `_request_records`. Imports `ROOT, engine` from conftest via a `sys.path` insert.

### tests/tmp/test_19_timestamped_request_logs_phase2.py
Drives `engine/server/api/logging_profiles.py` (child process, `LOG_FORMAT` pinned).
- `test_engine_log_format_unset_empty_json_or_unknown_writes_todays_json_lines` (5 params)
- `test_engine_log_format_text_writes_one_escaped_text_line_per_record` (4 params)
- Module-level: `TS_RE`, `TEXT_HEAD_RE`, `_ENGINE_CHILD`, `JSON_PAYLOADS`, `EXCEPTION_TEXT_RE`, `_run_child`, `_json_object`.

### tests/tmp/test_19_timestamped_request_logs_phase3.py
Drives `client/backend/server.py` in-process (`configure_client_logging`, `ClientLogFormatter`, `_emit_client_log`).
- `test_client_records_leave_as_json_lines_in_client_key_order_with_utc_ts_and_bare_ones_as_client_log`
- Module-level: `TS_RE`, `OFF_UTC_ZONE`, `EMIT_KEYS`, `BARE_KEYS`, `_client_logging`, `_epoch`, `_fixed_record`.

### tests/tmp/test_19_timestamped_request_logs_phase4.py
Drives `client/backend/server.py` in-process, and `engine/server/api/logging_profiles.py` in a child for the drift guard.
- `test_client_log_format_unset_empty_json_or_unknown_writes_json_lines` (5 params)
- `test_client_log_format_text_writes_the_engines_escaped_text_line_per_record` (4 params)
- `test_client_format_ts_and_render_text_return_the_engines_strings`
- Module-level: `TS_RE`, `TEXT_HEAD_RE`, `JSON_PAYLOADS`, `EXCEPTION_TEXT_RE`, `_ENGINE_CHILD`, `CREATED`, `RENDER_PAYLOADS`, `ENGINE_TEXTS`, `_client_logging`, `_log_records`, `_json_object`.

### Probes
Scaffolding for observations already recorded in the build record; several were emptied by the builder. None asserts a rule.

## Step 3 - Classification

Subject files: `tests/active/test_logging_profiles.py` for `engine/server/api/logging_profiles.py` (today it asserts only the `traceback` key); `tests/active/test_server.py` for `client/backend/server.py` (it has no test of `ts`, `LOG_FORMAT`, `configure_client_logging` or the text renderer; its `_error_messages` only uses `ClientLogFormatter` to read records).

- `test_engine_ts_is_record_created_in_utc_with_milliseconds` - DURABLE -> `tests/active/test_logging_profiles.py`. No active test asserts the UTC `ts` from `record.created`.
- `test_engine_request_ts_never_decreases_from_access_start_to_access` - DURABLE -> `tests/active/test_logging_profiles.py`. The only live-request check that `access.start` -> work -> `access` stamps are UTC and non-decreasing.
- `test_engine_log_format_unset_empty_json_or_unknown_writes_todays_json_lines` - DURABLE -> `tests/active/test_logging_profiles.py`. Pins the Engine JSON payload (keys, order, values) and the fail-safe `json` selection.
- `test_engine_log_format_text_writes_one_escaped_text_line_per_record` - DURABLE -> `tests/active/test_logging_profiles.py`. The only test of Engine text selection and line shape.
- `test_client_records_leave_as_json_lines_in_client_key_order_with_utc_ts_and_bare_ones_as_client_log` - DURABLE -> `tests/active/test_server.py`. The only test of the Client root formatter, its UTC `ts`, context omission and the `client.log` fallback.
- `test_client_log_format_unset_empty_json_or_unknown_writes_json_lines` - DURABLE -> `tests/active/test_server.py`. Client fail-safe selection over json/JSON/bogus/empty; the phase-3 test covers unset only.
- `test_client_log_format_text_writes_the_engines_escaped_text_line_per_record` - DURABLE -> `tests/active/test_server.py`. The only test of Client text lines.
- `test_client_format_ts_and_render_text_return_the_engines_strings` - DURABLE -> `tests/active/test_server.py`. The drift guard the `rat-tail:` comment in `client/backend/server.py` names; nothing else backs it.
- Every probe - SPENT. Scaffolding for a phase that has landed.

Counts: 8 DURABLE, 0 REPLACES, 0 COMBINE, 0 REDUNDANT, 13 SPENT (probe files). No active test is retired. No subject file is created.

`test_groups` changes (approved at Step 4 and applied):
- `test_logging_profiles.py`: add `engine/server/api/handlers/similar.py` and `engine/server/api/request_context.py` (the live-request test reads the `access.start`/`access` records they emit).
- `test_server.py`: add `engine/server/api/logging_profiles.py` (the drift guard compares the Engine copy).

## Step 4 - Plan agreed

The operator approved the plan as listed: the eight DURABLE tests, the two destinations and the three map additions.

## Step 5 - Applied

- `tests/active/test_logging_profiles.py`: the four Engine tests were added beside the existing traceback test. The module docstring now states the `ts`, live-request ordering, JSON-payload and text-line rules. `_TS_CHILD` imports `_format_ts` directly; the build-time `getattr` fallback for a missing helper was dropped. The JSON test is renamed `..._writes_json_lines`, so it no longer cites "today's" JSON. The `engine` fixture comes from conftest without an import.
- `tests/active/test_server.py`: the four Client tests went after the Engine-failures block, with names prefixed where they could collide (`LOG_TS_RE`, `LOG_TEXT_HEAD_RE`, `LOG_EMIT_KEYS`, `LOG_BARE_KEYS`, `LOG_API_DIR`, `CLIENT_LOG_JSON_PAYLOADS`, `CLIENT_EXCEPTION_TEXT_RE`, `_ENGINE_RENDER_CHILD`, `RENDER_CREATED`, `ENGINE_RENDER_TEXTS`). The imports `io`, `re` and `datetime, timezone` were added, and the module docstring gained a "Client log lines" section.
- Build clause ids (`# C1`) were not carried into `active`.
- `.un/skills/devsecops/config.json`: the map additions above. `--audit-map` exits 0. Its only new advisory finding is MISSING `engine/server/data/time.py` for `test_logging_profiles.py`, which the `engine` fixture imports; that is a fixture dependency and was left unclaimed.

## Step 6 - Mutations

Each mutation was copied to `<file>.bak-trl-M<n>`, run, restored with `diff` clean, and green again; each backup is now in `delete_me/`.

- `test_engine_ts_is_record_created_in_utc_with_milliseconds` - M1: Engine `_format_ts` used `datetime.now(tz=timezone.utc)` instead of `record.created`. This failed `fixed == {...56.789Z}` (test_logging_profiles.py:160), which read `2026-10-01T23:08:51.369Z`.
- `test_engine_request_ts_never_decreases_from_access_start_to_access` - M2: Engine `_format_ts` subtracted 0.5 s for `[recommendations…` messages. This failed the non-decreasing assertion (:205): `recommendations.incoming_likes_body` read 23:09:04.957, after `access.start` at 23:09:05.457.
- `test_engine_log_format_unset_empty_json_or_unknown_writes_json_lines` - M3: Engine `normalize_log_format` returned `text` for any unknown non-empty value. This failed `[bogus]` at the all-JSON assertion (:214).
- `test_engine_log_format_text_writes_one_escaped_text_line_per_record` - M4: Engine `_TEXT_ESCAPES` stopped escaping CR. All four params failed the five-line count (:229).
- `test_client_records_leave_as_json_lines_in_client_key_order_with_utc_ts_and_bare_ones_as_client_log` - M5: the Client formatter's fallback event became `engine.log`. This failed the bare-record assertion (test_server.py:1250).
- `test_client_log_format_unset_empty_json_or_unknown_writes_json_lines` - M6: Client `normalize_log_format` returned `text` for unknown values. This failed `[bogus]` at the all-JSON assertion (:1260).
- `test_client_log_format_text_writes_the_engines_escaped_text_line_per_record` - M7: Client `normalize_log_format` stopped calling `.strip()`. ` Text ` and `\ttext\n` failed the text-head assertion (:1274).
- `test_client_format_ts_and_render_text_return_the_engines_strings` - M8: Client `_text_value` used `str(value)`. This failed `client_texts == engine["text"]` (:1300). The Client text-line test stayed green, because `str(200)` and the JSON form of 200 are the same.

After the restores, `git diff --stat` of both production files matched the pre-harvest state (101 and 63 lines), and no `.bak` remains under the production tree.

## Step 7 - Disposed

All 17 in-scope files were moved to `delete_me/` with `mv -n`, with no name collisions: the four phase files, `test_probe_19_p1.py`, `test_probe_19_p2.py`, `test_probe_19_p3.py`, `test_probe_19_p3_values.py`, `test_probe_19_p4.py`, `test_probe_step8_home_overlap.py`, `probe_caplog_formatter.py`, `probe_client_tb.py`, `probe_engine_render.py`, `probe_fromtimestamp.py`, `probe_step8_dataset.py`, `probe_step8_pager.py` and `probe_ts_values.py`. Also in `delete_me/`: `logging_profiles.py.bak-trl-M1`..`M4` and `server.py.bak-trl-M5`..`M8`.

## Step 8 - Suite

The snapshot was restored, then `--compare` ran with no tier. It selected 4 of 46 groups and exited 1: 197 passed, 16 failed.

- Appeared: 22 test ids, exactly the eight harvested tests with their parameters (11 in `test_logging_profiles.py`, 11 in `test_server.py`). Departed: none.
- Still red, already red in the pre-harvest record: the 15 data-pinned controls the build's Step 8 reported and the operator ruled out of scope ("report only").
- New red: `test_similar.py::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[linux]`, at its control "a plain page repeats none of the previous one" (test_similar.py:213). This is the home-overlap control that build Step 8 triage attempt 2 showed is intermittent on the rebuilt dataset. The harvest changed no production code. Rerun alone three times, `-k test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page` exited 0 each time.
