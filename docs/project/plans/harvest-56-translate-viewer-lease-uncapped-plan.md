# Harvest — build 56, translate viewer lease and uncapped length

## Resolved paths (from `--show-config`, Step 1)

- project_dir: `/home/enduser/code/PeerTube-browser`
- source: `tests/config.json`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- defaulted: none, conflicts: none, so the bootstrap gate is clear.

## Snapshot

`tests/last_test_validation.json.preharvest` was taken at Step 1, before any harvesting run.

## Scope

Only the tests this build wrote; the dispatch set the scope, not the whole of `tests/tmp`:

- `tests/tmp/test_56_translate_viewer_lease_uncapped_phase1.py`
- `tests/tmp/test_56_translate_viewer_lease_uncapped_phase2.py`
- `tests/tmp/test_56_translate_viewer_lease_uncapped_phase3.py`
- `tests/tmp/test_56_translate_viewer_lease_uncapped_phase4.py`

All four collect (`pytest --collect-only`: 37 items). None is unclassifiable.

## Inventory (Step 2)

### tests/tmp/test_56_translate_viewer_lease_uncapped_phase1.py

Drives `engine/server/db/jobs/translate-worker.py` (`run_job` through `Rig`, and `AudioPipe`), with `engine/server/data/source_fetch.py`'s `stream_media` as the real feeder.

- `test_a_video_with_no_duration_a_long_json_or_stored_duration_or_a_huge_declared_size_translates_to_ready`, parametrized over `UNCAPPED` (4 cases).
- `test_audio_pipe_never_buffers_past_its_limit_parks_until_release_frees_room_and_still_ends_at_eof`.
- Module-level names: `CLIP_CUES`, `LONG_SECONDS`, `HUGE_LENGTH`, `UNCAPPED`, `LOOKAHEAD_SECONDS`, `WINDOW_SAMPLES`, `LIMIT_SAMPLES`, `LIMIT_BYTES`, `BYTES_PER_SAMPLE`, `MEDIA_BODY`, `DECODED_SAMPLES`, `RELEASED_TO`, `FAKE_FFMPEG`, `QUIET_SECONDS`, `FILL_SECONDS`, `PARKED_SECONDS`, `DRAIN_SECONDS`, `CLOSE_SECONDS`.
- Helpers: `_video`, `_buffered`, `_settle`, `_close`.
- Imports from `test_translate_worker`: `MEDIA_HOST`, `MEDIA_URL`, `ScriptedHost`, `StubRunner`, `VIDEO_URL`, `_dispatching_opener`, `_worker`, `clip`, `rig`.

### tests/tmp/test_56_translate_viewer_lease_uncapped_phase2.py

Drives `engine/server/data/subtitles.py` (`claim_translate_job(..., expired_at=)`, `enqueue_translate_job(..., wanted_at=)`) and `engine/server/db/jobs/translate-worker.py` (`run_job` abandon through `Rig`, `now_ms` patched).

- `test_the_claim_drops_every_queued_row_whose_lease_expired_at_the_cutoff_and_claims_the_oldest_survivor_leaving_unleased_fresh_running_and_ready_rows`.
- `test_a_running_job_whose_lease_has_lapsed_is_deleted_at_its_first_wake_with_one_abandoned_line`.
- `test_an_unleased_job_or_one_whose_lease_is_current_runs_to_ready_however_late_the_clock`, parametrized over `[None, FAR_NOW]`.
- Module-level names: `CLAIM_AT`, `CUTOFF`, `EXPIRED`, `FRESH`, `QUEUED`, `READY_ID`, `READY_QUEUED_AT`, `RUNNING_ID`, `RUNNING_QUEUED_AT`, `RUNNING_AT`, `OLD_LEASE`, `FAR_NOW`, `ABANDONED`, `CLIP_CUES` (same body as phase 1's), `READY_LINE`.
- Helpers: `_rows`, `_enqueue`, `_claim`, `_messages`.
- Imports from `test_translate_worker`: `HOST`, `INSTANCE_THEN_JSON`, `MEDIA_URL`, `QUEUED_AT`, `STARTED_AT`, `Rig`, `StubRunner`, `clip`, `rig`.

### tests/tmp/test_56_translate_viewer_lease_uncapped_phase3.py

Drives `engine/server/api/handlers/internal_translate.py` (state-route renewal, `handle_internal_translate_cancel`), `client/backend/server.py` (`/api/translate/cancel`), `client/backend/lib/engine_api_client.py` (`cancel_translate`), `client/frontend/src/data/translate.ts` (`cancelTranslate`) and `tests/active/fixtures/translate_contract.json`.

- `test_a_state_read_renews_only_a_leased_queued_or_running_row_to_now_and_answers_as_before`, parametrized over `RENEWAL` (7 cases).
- `test_the_engine_cancel_caps_a_leased_queued_or_running_lease_at_now_less_160_s_never_lengthens_one_and_answers_the_stored_state`, parametrized over `CANCEL` (8 cases).
- `test_the_engine_cancel_of_a_key_with_no_row_writes_nothing_and_answers_none`.
- `test_the_engine_cancel_answers_available_false_with_no_worker_beat_and_still_caps_the_lease`.
- `test_the_gateway_cancel_makes_one_bridge_call_to_the_engine_cancel_route_and_answers_its_state_and_available`, parametrized over `GATEWAY_ANSWERS` (3 cases).
- `test_a_cancel_through_the_client_gateway_reaches_the_started_engines_cancel_route_and_caps_the_lease`.
- `test_the_contract_states_the_cancel_route_as_the_six_stored_states_one_video_not_found_and_its_refusals`.
- `test_every_cancel_contract_case_parses_through_the_gateway_cancel_translate_from_one_post_to_the_engine_cancel_route`.
- `test_every_cancel_contract_case_parses_through_the_page_data_layer_cancel_translate_from_one_post_to_the_gateway_cancel_route`.
- `test_the_engine_drivers_cover_exactly_the_contract_pairs_and_each_cancel_state_answers_its_case_shape_from_the_real_cancel_handler`.
- Module-level names: `LEASE`, `CAPPED`, `FRESH`, `STORED_STATES`, `CANCEL_ROUTE`, `GATEWAY_CANCEL`, `GATEWAY_BODY`, `MALFORMED`, `KEY`, `OTHER_KEYS`, `RENEWAL`, `RENEWED`, `FETCHED`, `CANCEL`, `GATEWAY_ANSWERS`, `OTHER_ROUTES`, `FRONTEND`, `ESBUILD`, `FRONTEND_BASE`, `DIRECT`, `CANCEL_RUNNER`.
- Helpers: `_rows` (dict keyed by key tuple), `_seed_key`, `_seed_others`, `_cancel`, `_cancel_post`, `_whitelisted_video`, `_started_engine`, `_cancel_cases`.
- Imports from `test_internal_translate` (`BODY`, `BRIDGE_TOKEN`, `CONTRACT`, `ENGINE_DRIVERS`, `ENGINE_PY`, `ENGINE_SERVER`, `ENGINE_START_LOCK`, `HANDLERS`, `HEALTHY_WITHIN_SECONDS`, `HOST`, `NOW`, `RUNNING`, `STOP_WITHIN_SECONDS`, `STORED_READY`, `VARIANT_RUNNER`, `VIDEO_ID`, `_beat`, `_engine_cases`, `_free_port`, `_instance`, `_post`, `_record_handlers`, `_request`, `_route`, `_server`, `_state`, `_subtitles_db`, `_types`, `whitelist`), from `test_server` (`TRANSLATE_BRIDGE_TOKEN`, `TRANSLATE_UNAUTHORIZED`, `_keyed_client_backend`, `_routed_translate_engine`, `_translate_engine`, `translate_bridge_token`) and from `conftest` (`WHITELIST_DB`, `RateLimiter`).

### tests/tmp/test_56_translate_viewer_lease_uncapped_phase4.py

Drives `client/frontend/src/pages/video-page/translate.ts` (bundled through `pages/video-page/index.ts`) in node under its own `RUNNER`, a variant of the active `GENERATION_RUNNER` that adds the cancel path, per-answer `delay`, `answeredAfter`, `held` and a `posts` step.

- `test_turning_translate_off_during_a_held_poll_sends_one_cancel_with_the_video_and_key_only_after_that_poll_answered`.
- `test_turning_translate_off_between_polls_sends_one_cancel_with_the_video_and_key_at_once`.
- `test_a_poll_reading_none_from_a_serving_worker_requests_generation_again_each_time_with_the_video_and_key_and_shows_waiting_and_one_without_does_not`.
- Module-level names: `FRONTEND`, `ESBUILD`, `BASE`, `HOST`, `TITLE`, `EMBED`, `ORIGINAL`, `KEY`, `TOGGLE`, `STATUS`, `OVERLAY`, `NO_TRANSLATION`, `WAITING`, `TRANSLATE`, `CANCEL`, `VIDEO`, `STOP_WAIT`, `HELD_MS`, `EMBED_STUB`, `RUNNER`, `SCENARIOS`.
- Helpers and fixtures: `_state`, `_bundle`, `_env`, `_run`, `pages` (module fixture), `_page`, `_indexed`, `_asked`.

## Classification (Step 3)

Subject files read: `test_translate_worker.py`, `test_subtitles.py`, `test_source_fetch.py`, `test_internal_translate.py`, `test_engine_api_client.py`, `test_server.py`, `test_frontend_translate.py`. None is split into parts.

### phase1

- `test_a_video_with_no_duration_a_long_json_or_stored_duration_or_a_huge_declared_size_translates_to_ready` — **DURABLE** → `tests/active/test_translate_worker.py`. Phase 1 retired the cap cases from `BOUNDS` and `FETCH_REASONS`, and no active test asserts that a missing, long JSON or long stored duration, or a huge declared Content-Length, ends ready.
- `test_audio_pipe_never_buffers_past_its_limit_parks_until_release_frees_room_and_still_ends_at_eof` — **DURABLE** → `tests/active/test_translate_worker.py`. No active test names `AudioPipe`, `limit` or `release`; the bounded buffer and the park/resume are asserted nowhere else.

### phase2

- `test_the_claim_drops_every_queued_row_whose_lease_expired_at_the_cutoff_and_claims_the_oldest_survivor_leaving_unleased_fresh_running_and_ready_rows` — **DURABLE** → `tests/active/test_subtitles.py`. The active claim test covers oldest-first claiming only; nothing drives `expired_at` or `wanted_at`.
- `test_a_running_job_whose_lease_has_lapsed_is_deleted_at_its_first_wake_with_one_abandoned_line` — **DURABLE** → `tests/active/test_translate_worker.py`. No active test drives `lease_lapsed`, `JobAbandoned` or the abandoned log line.
- `test_an_unleased_job_or_one_whose_lease_is_current_runs_to_ready_however_late_the_clock` — **DURABLE** → `tests/active/test_translate_worker.py`. This is the negative half of the abandon rule. Active Rig runs queue unleased rows, but under a real clock, so none of them rules out an abandon that ignores `wanted_at IS NOT NULL`.

### phase3

- `test_a_state_read_renews_only_a_leased_queued_or_running_row_to_now_and_answers_as_before` — **DURABLE** → `tests/active/test_internal_translate.py`. The only active mention of `wanted_at` is the enqueue row (`QUEUED_ROW`); renewal on read is asserted nowhere.
- `test_the_engine_cancel_caps_a_leased_queued_or_running_lease_at_now_less_160_s_never_lengthens_one_and_answers_the_stored_state` — **DURABLE** → `tests/active/test_internal_translate.py`. The active cancel drivers check the answer's state and types only, never the lease cap or the never-lengthen rule.
- `test_the_engine_cancel_of_a_key_with_no_row_writes_nothing_and_answers_none` — **DURABLE** → `tests/active/test_internal_translate.py`. The `("cancel", "none")` driver checks the answer's shape but not that the cancel creates no row.
- `test_the_engine_cancel_answers_available_false_with_no_worker_beat_and_still_caps_the_lease` — **DURABLE** → `tests/active/test_internal_translate.py`. The active heartbeat test (`test_available_is_true_only_for_a_heartbeat_0_to_15000_ms_old`) drives the state route only, and nothing asserts that the cap is not gated on the beat.
- `test_the_gateway_cancel_makes_one_bridge_call_to_the_engine_cancel_route_and_answers_its_state_and_available` — **DURABLE** → `tests/active/test_server.py`. `test_server.py` has no `/api/translate/cancel` test: one bridge call, the 404 mapping and the keyless 401 are unasserted.
- `test_a_cancel_through_the_client_gateway_reaches_the_started_engines_cancel_route_and_caps_the_lease` — **REDUNDANT**. Every link is asserted in `active` once this harvest lands. The startup test in `test_internal_translate.py` proves the route is wired to the handler (404 `Video not found`, not `Not found`) and behind the bridge gate (401). The cancel-cap tests above prove the cap, the gateway test above proves the bridge call, and the `test_engine_api_client.py` replay proves `cancel_translate`'s parse. It also starts a whole Engine for no extra discrimination.
- `test_the_contract_states_the_cancel_route_as_the_six_stored_states_one_video_not_found_and_its_refusals` — **REDUNDANT**. `test_engine_api_client.py::test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names` already holds the cancel route to `TRANSLATE_STATES` with and without `available`, one `Video not found`, and at least one rejected case. The remaining checks (which refusals exist, no cues) are about the fixture's contents, not production behaviour, and every case is replayed through all three parsers.
- `test_every_cancel_contract_case_parses_through_the_gateway_cancel_translate_from_one_post_to_the_engine_cancel_route` — **REDUNDANT**. `test_engine_api_client.py::test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route` replays every cancel case through `cancel_translate`, asserting one POST of `{id, host}` to `/internal/translate/cancel`.
- `test_every_cancel_contract_case_parses_through_the_page_data_layer_cancel_translate_from_one_post_to_the_gateway_cancel_route` — **REDUNDANT**. `test_frontend_translate.py`'s `CONTRACT_RUNNER` replays every cancel case through `cancelTranslate`, valid and rejected (including `cancel busy`), and `_result` checks POST to `/api/translate/cancel`. The `{id, host}` body is asserted by the phase 4 cancel tests moving into the same file.
- `test_the_engine_drivers_cover_exactly_the_contract_pairs_and_each_cancel_state_answers_its_case_shape_from_the_real_cancel_handler` — **REDUNDANT**. `test_internal_translate.py::test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states` and `::test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included` already cover the exact set and each cancel pair's shape from the real handler (`ROUTE_STATES` has the six cancel pairs).

### phase4

- `test_turning_translate_off_during_a_held_poll_sends_one_cancel_with_the_video_and_key_only_after_that_poll_answered` — **DURABLE** → `tests/active/test_frontend_translate.py`. The active `stop-off` scenario asserts only that the poll ends; no active test asserts a cancel, its body, its key, or its ordering after the in-flight poll.
- `test_turning_translate_off_between_polls_sends_one_cancel_with_the_video_and_key_at_once` — **DURABLE** → `tests/active/test_frontend_translate.py`. Same gap, with nothing in flight.
- `test_a_poll_reading_none_from_a_serving_worker_requests_generation_again_each_time_with_the_video_and_key_and_shows_waiting_and_one_without_does_not` — **DURABLE** → `tests/active/test_frontend_translate.py`. The active `request` scenario covers turnOn's single request only (its poll answers queued after that, so it does not conflict). The poll's re-request on `none` + `available`, and its gating by `available`, are asserted nowhere.
  - This test and the two above need phase 4's own runner (cancel path, `delay`, `answeredAfter`, `held`, a `posts` step), which `GENERATION_RUNNER` lacks. It comes across as a second runner with its fixture; nothing is hoisted into a shared `conftest.py`.
  - Step 5 renames the colliding names: `RUNNER`, `EMBED_STUB`, `SCENARIOS`, `_bundle`, `_env`, `_run`, `pages`, `_page`, `_asked` (different body), `_indexed`, `CANCEL`, `VIDEO`, `HELD_MS`, `TRANSLATE`, `NO_TRANSLATION`.
  - These are kept once (same body): `_state`, `WAITING`, `STOP_WAIT`, `BASE`, `HOST`, `KEY`, `TITLE`, `EMBED`, `ORIGINAL`, `TOGGLE`, `STATUS`, `OVERLAY`, `FRONTEND`, `ESBUILD`. Step 5 confirms each body before keeping one.

## Counts

18 test functions: DURABLE 13, REPLACES 0, COMBINE 0, REDUNDANT 5, SPENT 0.

## Retirements

None. No `REPLACES` or `COMBINE`, so nothing moves to `tests/archive/`.

## test_groups

No change. Every production file the moved tests drive is already claimed by its destination entry:

- `test_translate_worker.py`: translate-worker.py, subtitles.py, source_fetch.py, server_config.py.
- `test_subtitles.py`: subtitles.py.
- `test_internal_translate.py`: internal_translate.py, subtitles.py, server_config.py, router.py.
- `test_server.py`: client/backend/server.py, engine_api_client.py.
- `test_frontend_translate.py`: pages/video-page/translate.ts, data/translate.ts, pages/video-page/index.ts.

## New subject files

None.

## Apply (Step 5)

Every DURABLE test was copied, with the constants and helpers it depends on, into its subject file. No conftest hoist and no shared fixture: each name a test needs is defined in its own subject file. The `C1`/`C2` checkpoint labels were dropped from the inline comments, and each module docstring gained the rule the incoming tests gate, with no build or phase named.

### tests/active/test_translate_worker.py (4 tests, from phase 1 and phase 2)

- Kept once, using the active copy: `_video`. Phase 1's `_video(duration)` built the same dict the active `_video(duration)` builds (`files` defaults to `[MEDIA_FILE]`, which is `{"fileUrl": MEDIA_URL, "size": 4096}`, and None leaves `duration` out). So the incoming copy was dropped and its one use calls the active helper.
- The names phase 1 imported from this module (`MEDIA_HOST`, `MEDIA_URL`, `ScriptedHost`, `StubRunner`, `VIDEO_URL`, `_dispatching_opener`, `_worker`, `clip`, `rig`) and the ones phase 2 imported (`HOST`, `INSTANCE_THEN_JSON`, `QUEUED_AT`, `STARTED_AT`, `Rig`) are the module's own.
- Kept once, same body in phases 1 and 2: `CLIP_CUES`.
- Renamed because the name exists here with a different body: phase 2's `_enqueue` became `_enqueue_leased` (the active `_enqueue` runs the CLI).
- Renamed for clarity beside `Rig.claim`: `_claim` became `_claim_leased`. It now imports `claim_translate_job` locally, as `Rig.claim` does.
- Added with no clash: `LONG_SECONDS`, `HUGE_LENGTH`, `UNCAPPED`, `LOOKAHEAD_SECONDS`, `WINDOW_SAMPLES`, `LIMIT_SAMPLES`, `LIMIT_BYTES`, `BYTES_PER_SAMPLE`, `MEDIA_BODY`, `DECODED_SAMPLES`, `RELEASED_TO`, `FAKE_FFMPEG`, `QUIET_SECONDS`, `FILL_SECONDS`, `PARKED_SECONDS`, `DRAIN_SECONDS`, `CLOSE_SECONDS`, `_buffered`, `_settle`, `_close`, `OLD_LEASE`, `FAR_NOW`, `ABANDONED`, `READY_LINE`, `_messages`.
- Phase 2's `_rows` was not brought here, because only the claim test uses it and that test went to test_subtitles.py. The active `_rows` is untouched.

### tests/active/test_subtitles.py (1 test, from phase 2)

- Added with no clash: `CLAIM_AT`, `CUTOFF`, `EXPIRED`, `FRESH`, `QUEUED`, `READY_ID`, `READY_QUEUED_AT`, `RUNNING_ID`, `RUNNING_QUEUED_AT`, `RUNNING_AT`, `_rows`, `_enqueue`.
- `HOST` is kept once. The active `HOST = "peer.example"` is the value phase 2 imported from test_translate_worker.py.
- The store functions are imported inside the test and the helper, as this file does everywhere.

### tests/active/test_internal_translate.py (4 tests, from phase 3)

- Renamed because the name exists here with a different body: phase 3's `_rows` (a dict keyed by key tuple, rowid included) became `_lease_rows`.
- Added with no clash: `LEASE`, `CAPPED`, `FRESH`, `KEY`, `OTHER_KEYS`, `RENEWAL`, `RENEWED`, `FETCHED`, `CANCEL`, `_seed_key`, `_seed_others`, `_cancel`.
- Every name phase 3 imported from this module is the module's own. The store functions are imported locally, as here.
- Phase 3's `STORED_STATES`, `MALFORMED`, `FRONTEND`, `ESBUILD`, `FRONTEND_BASE`, `DIRECT`, `CANCEL_RUNNER`, `_whitelisted_video`, `_started_engine` and `_cancel_cases` were not brought over. They serve only the five REDUNDANT tests.

### tests/active/test_server.py (1 test, from phase 3)

- Kept once under the active name, same value: `GATEWAY_BODY` is `TRANSLATE_BODY`.
- Renamed to the file's `TRANSLATE_` naming, with no clash either way:
  - `CANCEL_ROUTE` became `TRANSLATE_CANCEL_ROUTE`.
  - `GATEWAY_CANCEL` became `TRANSLATE_GATEWAY_CANCEL`.
  - `GATEWAY_ANSWERS` became `TRANSLATE_CANCEL_ANSWERS`. Its 404 answer is now spelled `TRANSLATE_NONE_UNAVAILABLE`, which has the same value.
  - `OTHER_ROUTES` became `TRANSLATE_CANCEL_OTHER_REPLIES`, keyed by `TRANSLATE_STATE_ROUTE` and `TRANSLATE_ENQUEUE_ROUTE`, which have the same paths.
  - `_cancel_post` became `_translate_cancel_post`.
- `RateLimiter`, `_routed_translate_engine`, `_keyed_client_backend`, `translate_bridge_token`, `TRANSLATE_BRIDGE_TOKEN` and `TRANSLATE_UNAUTHORIZED` are the module's own.

### tests/active/test_frontend_translate.py (3 tests, from phase 4)

- Kept once, same body: `_state`, `WAITING`, `STOP_WAIT`, `BASE`, `HOST`, `KEY`, `TITLE`, `EMBED`, `ORIGINAL`, `TOGGLE`, `STATUS`, `OVERLAY`, `FRONTEND`, `ESBUILD`, `NO_TRANSLATION`.
- Phase 4's `EMBED_STUB` body is character for character the active `GENERATION_EMBED_STUB`, so the active one is used.
- Renamed because the name exists here with a different body:
  - `RUNNER` became `CANCEL_RUNNER`.
  - `_page` became `_cancel_page`.
  - `_asked` became `_cancel_asked`.
- Renamed to sit beside the generation runner's names:
  - `SCENARIOS` became `CANCEL_SCENARIOS`.
  - `_bundle` became the module fixture `cancel_bundle`.
  - `_env` became `_cancel_env`.
  - `_run` + `pages` became the module fixture `cancel_pages`.
  - `TRANSLATE` became `TRANSLATE_PATH`.
  - `CANCEL` became `CANCEL_PATH`.
- Added with no clash: `VIDEO`, `HELD_MS`, `_indexed`.
- Step 3's list also named `CANCEL`, `VIDEO`, `HELD_MS`, `TRANSLATE`, `NO_TRANSLATION` and `_indexed` as clashing. Checked here: `NO_TRANSLATION` is the same body, and the rest are not defined in the active file.
- A top-level duplicate-name scan of all five subject files finds none.

### Group map

`--audit-map` exits 0. Its MISSING findings for the five subject files (`engine/server/data/time.py`, `engine/server/db/subtitles.db`, `translate-worker.lock`, `client.log`) were there before this harvest. They are imports or runtime files, not subjects of the moved tests. `test_groups` is unchanged.

## Verify by mutation (Step 6)

The snapshot `tests/last_test_validation.json.preharvest` was confirmed on disk before the first run. Each pass: copy the production file to `<file>.bak`, move it to `.scratch/harvest/<test_name>/`, apply one mutation whose anchor was counted at exactly one occurrence (`.scratch/harvest/mutate.py --check`), run `validate_tests.py <subject> -k <test_name>`, restore from the copy, `diff` clean, re-run green. No batching: one test per run. A previous session had begun this step without recording results; every mutation below was run again in this session, and its backups were first proved identical to the production files.

Stale bytecode: M4's first green run failed though `diff` was clean, because a same-size edit restored within one mtime second left the mutant's `translate-worker.cpython-314.pyc` valid. The `.pyc` was removed, the pass driver now drops the module's `.pyc` after every mutate and every restore, and M4 was re-run in full (red, then green).

- `test_a_video_with_no_duration_a_long_json_or_stored_duration_or_a_huge_declared_size_translates_to_ready` — M1, translate-worker.py: re-added `JobFailed("video duration unknown")` in `generate` for a JSON duration missing or over 600. Red: `[JSON without duration]` and `[JSON duration far over the old cap]` failed `(state, source, error) == ("ready", "whisper", None)` with `failed`/`video duration unknown`. Restore diff clean; green 4 passed.
- `test_audio_pipe_never_buffers_past_its_limit_parks_until_release_frees_room_and_still_ends_at_eof` — M2, translate-worker.py: `read1(min(READ_CHUNK_BYTES, room))` → `read1(READ_CHUNK_BYTES)`. Red: `largest <= LIMIT_BYTES` failed, 65536 <= 48000. Restore diff clean; green 1 passed.
- `test_a_running_job_whose_lease_has_lapsed_is_deleted_at_its_first_wake_with_one_abandoned_line` — M3, translate-worker.py: `lease <= expired_at` → `lease > expired_at` in `lease_lapsed`. Red: `rig.row() == {}` failed, the row ended ready with the clip's cues. Restore diff clean; green 1 passed.
- `test_an_unleased_job_or_one_whose_lease_is_current_runs_to_ready_however_late_the_clock` — M4, translate-worker.py: cutoff `now_ms() - TRANSLATE_LEASE_MS` → `now_ms() + TRANSLATE_LEASE_MS`. Red: `[lease stamped now]` failed `(state, source) == ("ready", "whisper")` with `{}` (abandoned); `[unleased]` passed, as predicted, since the store's DELETE keeps its own NULL guard. Restore diff clean; green 2 passed.
- `test_the_claim_drops_every_queued_row_..._leaving_unleased_fresh_running_and_ready_rows` — M5, subtitles.py: claim DELETE `wanted_at <= ?` → `wanted_at < ?`. Red: `"v-expired" not in after` failed (the boundary row survived). Restore diff clean; green 1 passed.
- `test_a_state_read_renews_only_a_leased_queued_or_running_row_to_now_and_answers_as_before` — M6, internal_translate.py: renew only when `stored[0] in ("queued",)`. Red: `[leased running]` failed `after == {**before, KEY: {... "wanted_at": NOW}}`. Restore diff clean; green 7 passed.
- `test_the_engine_cancel_caps_a_leased_queued_or_running_lease_at_now_less_160_s_never_lengthens_one_and_answers_the_stored_state` — M7, subtitles.py: `MIN(wanted_at, ?)` → `MAX(wanted_at, ?)`. Red: the four leased queued/running cases failed `_lease_rows(path) == {KEY: {... "wanted_at": capped}}`, including `lease 1 ms before the cap` (lengthened). Restore diff clean; green 8 passed.
- `test_the_engine_cancel_of_a_key_with_no_row_writes_nothing_and_answers_none` — M8, internal_translate.py: the cancel reads the state first and enqueues a row when there is none. Red: `_lease_rows(path) == {}` failed (a v-1 row was created) while the answer stayed none. Restore diff clean; green 1 passed.
- `test_the_engine_cancel_answers_available_false_with_no_worker_beat_and_still_caps_the_lease` — M9, internal_translate.py: `_generation_available(conn) and cancel_translate_lease(...)`. Red: `wanted_at == CAPPED` failed, 1759999999000 == 1759999840000, with the answer assertion passing. Restore diff clean; green 1 passed.
- `test_the_gateway_cancel_makes_one_bridge_call_to_the_engine_cancel_route_and_answers_its_state_and_available` — M10, client/backend/server.py: `_handle_translate_post(cancel_translate)` → `_handle_translate_post(request_translate)`. Red: all three cases failed `answered == expected` (the enqueue route's busy answer came back). Restore diff clean; green 3 passed.
- `test_turning_translate_off_during_a_held_poll_sends_one_cancel_with_the_video_and_key_only_after_that_poll_answered` — M11, pages/video-page/translate.ts: `requestsSettled.then(...)` → `Promise.resolve().then(...)`. Red: `cancel_index >= held_get["answeredAfter"]` failed, 9 >= 10. Restore diff clean; green 1 passed.
- `test_turning_translate_off_between_polls_sends_one_cancel_with_the_video_and_key_at_once` — M12, pages/video-page/translate.ts: a 500 ms delay before `cancelTranslate`. Red: `snapshots[3]["cancels"] == 1` failed, 0 == 1. Restore diff clean; green 1 passed.
- `test_a_poll_reading_none_from_a_serving_worker_requests_generation_again_..._and_one_without_does_not` — M13, pages/video-page/translate.ts: the poll calls `applyState` instead of `applyFetched`. Red: `len(posts) == 3` failed, 1 == 3. Restore diff clean; green 1 passed.

No mutation survived, none hung, none was reclassified. No `.bak` exists under the production tree or `tests/active`; the copies stay under `.scratch/harvest/`.

## Dispose (Step 7)

Moved to `delete_me/`, no name collisions: `test_56_translate_viewer_lease_uncapped_phase1.py`, `..._phase2.py`, `..._phase3.py`, `..._phase4.py`. `tests/tmp` holds none of them. Out of scope and left in place: `tests/tmp/probe_56_phase1_audiopipe.py` and the other probes.

## Run and bank (Step 8)

`tests/last_test_validation.json.preharvest` was moved back over the record, then `validate_tests.py --compare` ran with no tier: 7 groups selected (6 changed, plus test_search_fusion.py with no map entry), 63 unchanged carried forward; 539 passed, 0 failed. Moved against the pre-harvest record: 32 appeared (the 13 harvested functions with their parameters: test_translate_worker 8, test_subtitles 1, test_internal_translate 17, test_server 3, test_frontend_translate 3), 0 gone, 0 new red, 0 no-longer-red.
