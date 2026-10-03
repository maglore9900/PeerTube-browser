# Harvest: plan 48 translate instance captions

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
- HARVEST_FILE: `docs/project/plans/harvest-48-translate-instance-captions-plan.md`

Record snapshot: `tests/last_test_validation.json` existed and was copied to `tests/last_test_validation.json.preharvest` (141660 bytes, both) before anything else ran.

Scope: the four tests this build wrote. These are named by the build dispatch, not by a whole-tree sweep:

- `tests/tmp/test_48_translate_instance_captions_phase1.py`
- `tests/tmp/test_48_translate_instance_captions_phase2.py`
- `tests/tmp/test_48_translate_instance_captions_phase3.py`
- `tests/tmp/test_48_translate_instance_captions_phase4.py`

Out of scope but present in `tests/tmp`: `probe_48_phase2.py`, `probe_48_phase3.py`, `probe_48_phase3_observe.py`, `probe_48_phase4.py`, `probe_opener.py`, `probe_phase2_fixture.py`, `probe_phase2_routes.py`, `probe_phase2_standin.py`, `probe_phase4_controls.py`, `probe_red_suite.py`, `probe_redirect_308.py`, `probe_standin.py`, `probe_suite_red.py`, `probe_translate_bundle.py`, and `__pycache__/`. None is a `test_*.py`, so none is collected. Step 7 moves only the four files in scope, so `tests/tmp` will not be empty afterwards unless the operator widens the disposal to these probes as well.

Collection: all four files collect, 82 test items in total (`pytest --collect-only`). None needed a `validate_tests.py <path>` run to diagnose a collection failure.

## Step 2: inventory

### tests/tmp/test_48_translate_instance_captions_phase1.py

Drives `engine/server/api/handlers/internal_translate.py` in-process: `parse_webvtt`, `pick_english_track_path`, `SameHostRedirectHandler.redirect_request` and `fetch_bounded`. The instance is stood in for at `internal_translate.build_opener`, using a real urllib opener whose http(s) open step is scripted, plus a monotonic `Clock` patched over `time.monotonic`.

Module-level dependencies: `ROOT`/`SERVER_DIR`/`API_DIR` sys.path setup; constants `HOST`, `TRACK_PATH`, `TRACK_URL`, `WITHIN_CAP`, `OVER_CAP`, `CHUNK`, `REFUSED_TARGETS`, `WELL_FORMED`, `GOOD`, `REJECTED`, `NO_TEXT`, `PICK_REFUSED`; classes `Clock`, `Response`, `Instance`; helpers `_socket_handler`, `_translate(instance=None)`, `_body`, `_listing`; fixture `instance` (monkeypatches `time.monotonic`).

Tests:
- `test_well_formed_track_parses_to_plain_text_cues_sorted_by_start`
- `test_markup_is_stripped_and_entities_decoded_to_plain_text`
- `test_the_good_cue_the_rejected_tracks_share_parses_alone`
- `test_any_failing_part_rejects_the_whole_track` (9 params)
- `test_a_track_with_no_cue_text_is_none` (4 params)
- `test_caption_pick_takes_the_first_exact_en_track`
- `test_caption_pick_takes_a_same_host_https_file_url`
- `test_caption_pick_refuses_anything_off_the_host` (7 params)
- `test_redirect_handler_follows_a_same_host_https_target` (301/302/303/307/308)
- `test_redirect_handler_refuses_an_off_host_or_non_https_target` (5 params)
- `test_fetch_returns_the_joined_body_of_the_https_url`
- `test_fetch_follows_a_same_host_redirect` (absolute, relative)
- `test_fetch_refuses_an_off_host_or_non_https_redirect` (5 params)
- `test_fetch_refuses_a_declared_length_over_the_cap_without_reading`
- `test_fetch_refuses_a_body_streamed_past_the_cap`
- `test_fetch_returns_a_body_of_2_000_000_bytes_whole` (declared, streamed)
- `test_fetch_refuses_a_body_still_arriving_past_its_deadline` (per-fetch deadline, request budget)
- `test_fetch_returns_a_body_finished_inside_its_deadline`
- `test_fetch_with_its_budget_spent_opens_nothing`

### tests/tmp/test_48_translate_instance_captions_phase2.py

Drives `handle_internal_translate` in `engine/server/api/handlers/internal_translate.py` in-process. It runs over a temporary whitelist.db (videos, channels, `instance_denylist` through `data.moderation.ensure_moderation_schema`) and a temporary subtitles.db opened with `data.subtitles.connect_subtitles_db`/`ensure_subtitles_schema`. `fetch_bounded` is patched to a recording `Instance`. A last test runs the real Engine `engine/server/api/server.py` through `VARIANT_RUNNER` with `DEFAULT_SUBTITLES_DB_PATH` overridden, under the Engine start lock.

Module-level dependencies: sys.path setup; `ENGINE_PY` and `ENGINE_START_LOCK`, both duplicates of `tests/active/conftest.py`'s; `ENGINE_SERVER`, `BRIDGE_TOKEN`, `HEALTHY_WITHIN_SECONDS`, `STOP_WITHIN_SECONDS`, `THRESHOLD`, `HOST`, `DENIED_HOST`, `PEER_VIDEO`, `DENIED_VIDEO`, `TRACK_PATH`, `TRACK`, `CUES`, `VIDEO_NOT_FOUND`, `NONE`, `READY`, `EN_LISTING`, `FR_LISTING`, `NONE_PATHS`, `VARIANT_RUNNER`; classes `Request` and `Instance` (a different `Instance` from phase 1's); helpers `_translate(instance, monkeypatch)`, `_whitelist`, `_set_denied`, `_subtitles_db`, `_server`, `_handle`, `_stored`, `_free_port`, `_post`; fixtures `whitelist` and `instance` (phase 1 also has an `instance` fixture, so the names collide).

Tests:
- `test_an_unknown_video_is_404_video_not_found_with_no_fetch`
- `test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track`
- `test_a_ready_track_is_fetched_from_the_row_host_stored_and_then_served_from_subtitles_db_without_a_fetch`
- `test_each_none_path_answers_none_and_stores_nothing` (4 params)
- `test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate`

### tests/tmp/test_48_translate_instance_captions_phase3.py

Drives `GET /api/translate` on a real Client backend (`client/backend/server.py`, which loads `ClientBackendServer` under the module name `client_backend_server_phase3`). The Engine is a recording `EngineStub`, and the answer mapping lives in `client/backend/lib/engine_api_client.py` `fetch_translate`.

Module-level dependencies: `ROUTE`, `BRIDGE_TOKEN`, `CLOSED_ENGINE` (duplicates conftest's), `VALID`, `FAILED`, `NONE`, `UNAUTHORIZED`, `RATE_LIMITED`, `READY`, `BAD_QUERIES`, `ENGINE_ANSWERS`; class `EngineStub`; helpers `_serving` (identical to test_server.py's), `_engine`, `_client` (test_server.py's `_client_backend` plus a minted profile key), `_get`; an autouse fixture `bridge_token` that sets `ENGINE_BRIDGE_TOKEN`.

Tests:
- `test_a_rate_limited_request_is_429_before_the_profile_and_param_checks_with_no_engine_call`
- `test_a_keyless_request_with_bad_params_is_401_not_400_with_no_engine_call`
- `test_each_bad_param_is_400_with_no_engine_call_and_a_valid_request_reaches_the_bridge_route_with_token_request_id_and_stripped_id_host`
- `test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502` (8 params)
- `test_an_unreachable_engine_is_a_fixed_502`
- `test_a_ready_answer_reaches_the_visitor_with_only_start_end_and_text_per_cue`

### tests/tmp/test_48_translate_instance_captions_phase4.py

Drives the video page bundle (`client/frontend/src/pages/video-page/index.ts`, built with esbuild) in node. The rules it gates live in `client/frontend/src/pages/video-page/translate.ts` (`withEmbedApi`, `setupTranslate`) and `client/frontend/src/data/translate.ts` (`readTranslate`/`setTranslate`/`fetchTranslate`). The bundle aliases `@peertube/embed-api` to `EMBED_STUB`, and the toggle's initial label is read from `client/frontend/video-page.html`.

Module-level dependencies: `FRONTEND`, `ESBUILD`, `BASE`, `HOST`, `TITLE`, `EMBED`, `ORIGINAL`, `KEY`, `TOGGLE`, `STATUS`, `OVERLAY`, `NO_TRANSLATION`, `CUES`, `READY`, `NONE`, `INITIAL_TEXT`, `EMBED_STUB`, `RUNNER` (its own runner, different from test_frontend_video_page.py's), `BLOCKED`, `SEEK`, `SHOWN`, `EMBEDS`; the module-scoped fixture `bundle`; helpers `_page`, `_translate_requests`, `_parts`, `_overlay`, `_src_parts`.

Tests:
- `test_with_a_key_the_toggle_stays_hidden_and_translate_unasked_until_ready_resolves_then_shows_labelled_translate`
- `test_without_a_key_or_a_resolved_ready_there_is_no_toggle_no_translate_request_and_no_escaped_failure` (4 params)
- `test_loaded_with_translate_on_the_overlay_shows_as_text_the_cue_at_each_reported_position_including_after_a_seek_back`
- `test_a_none_state_reads_no_english_translation_and_a_reported_position_shows_nothing`
- `test_a_click_stores_on_and_asks_once_and_a_second_click_stores_off_after_which_a_reported_position_shows_nothing`
- `test_the_embed_src_gains_api_1_with_or_without_a_query_and_a_javascript_or_unparseable_url_sets_no_src`
- `test_with_no_reported_position_the_overlay_follows_the_position_the_page_asks_the_player_for`

## Step 3: classification

How I checked against `active`: I searched `tests/active` for `translate`, `subtitles`, `embed-api`, `api=1`, `video-embed`, `embedUrl` and `_sanitize_query`. Nothing in `active` asserts any translate behaviour. `test_server.py`'s `FAILURE_ROUTES` has no `/api/translate` row, and no frontend test asserts the embed src. That leaves no `REPLACES` or `COMBINE`. The only `REDUNDANT` verdicts are in-scope duplicates, where a sibling's control already asserts the same thing.

Subject files:
- `engine/server/api/handlers/internal_translate.py` → `tests/active/test_internal_translate.py`. **It does not exist yet, so Step 5 creates it.** The phase 2 Engine-start test goes here too. That follows the precedent of `test_random_cache.py`, which holds the random-cache Engine-start variant, and its route and store assertions are both this handler's.
- `client/backend/server.py` (`/api/translate` order) with `lib/engine_api_client.py` (`fetch_translate` mapping) → `tests/active/test_server.py`. It exists and is not split, and its map entry already claims both files.
- `client/frontend/src/pages/video-page/translate.ts` and `client/frontend/src/data/translate.ts` → `tests/active/test_frontend_translate.py`. **It does not exist yet, so Step 5 creates it.** The name follows the `test_frontend_<script>` convention, as with `test_frontend_reactions.py` for `data/reactions.ts`. Alternative for the operator: the entry module `index.ts`, whose existing subject file is `test_frontend_video_page.py`. That file's runner differs, so the translate RUNNER, EMBED_STUB and aliased bundle fixture would have to be copied into it under separate names.

### Phase 1 → tests/active/test_internal_translate.py

- `test_well_formed_track_parses_to_plain_text_cues_sorted_by_start`: **DURABLE**. No active test parses WebVTT. Gates the sort order, float times, and skipping NOTE/STYLE/REGION, BOM and CRLF.
- `test_markup_is_stripped_and_entities_decoded_to_plain_text`: **DURABLE**. Tag stripping followed by entity decoding, which nothing else asserts.
- `test_the_good_cue_the_rejected_tracks_share_parses_alone`: **REDUNDANT**. Its only assertion, `parse_webvtt(GOOD) == ["Kept"]`, is repeated as the first line of `test_any_failing_part_rejects_the_whole_track` and of `test_a_track_with_no_cue_text_is_none`, which are moving.
- `test_any_failing_part_rejects_the_whole_track`: **DURABLE**. Whole-track rejection on each of nine malformed blocks.
- `test_a_track_with_no_cue_text_is_none`: **DURABLE**. An empty result gives None.
- `test_caption_pick_takes_the_first_exact_en_track`: **DURABLE**. First exact `en` wins, past `en-US`, `fr` and a second `en`.
- `test_caption_pick_takes_a_same_host_https_file_url`: **REDUNDANT**. A same-host https `fileUrl` giving its path is asserted as the on-host control of every `REFUSED_TARGETS` case in `test_caption_pick_refuses_anything_off_the_host`, which is moving.
- `test_caption_pick_refuses_anything_off_the_host`: **DURABLE**. Off-host, lookalike, http, ported, userinfo and protocol-relative entries each give None, each beside a passing twin.
- `test_redirect_handler_follows_a_same_host_https_target`: **DURABLE**. The handler passes every 3xx code through for a same-host target, 308 included.
- `test_redirect_handler_refuses_an_off_host_or_non_https_target`: **DURABLE**. `redirect_request` returns None for each refused target. It is called directly, which is a different layer from the fetch-level refusal test.
- `test_fetch_returns_the_joined_body_of_the_https_url`: **REDUNDANT**. The URL formed from host and path is asserted by `test_fetch_with_its_budget_spent_opens_nothing` (`opened == [TRACK_URL]` and the body returned). Multi-chunk joining is asserted by `test_fetch_returns_a_body_of_2_000_000_bytes_whole`, at about 31 chunks. Both of those are moving.
- `test_fetch_follows_a_same_host_redirect`: **DURABLE**. A real urllib follows an absolute and a relative same-host redirect.
- `test_fetch_refuses_an_off_host_or_non_https_redirect`: **DURABLE**. The fetch returns None and the refused target is never opened.
- `test_fetch_refuses_a_declared_length_over_the_cap_without_reading`: **DURABLE**. The declared `Content-Length` cap, with zero reads.
- `test_fetch_refuses_a_body_streamed_past_the_cap`: **DURABLE**. The cap on the running byte count.
- `test_fetch_returns_a_body_of_2_000_000_bytes_whole`: **DURABLE**. The cap boundary. The declared case asserts something nothing else does.
- `test_fetch_refuses_a_body_still_arriving_past_its_deadline`: **DURABLE**. The per-fetch deadline and the request budget, each refusing mid-read.
- `test_fetch_returns_a_body_finished_inside_its_deadline`: **DURABLE**. Seven 1 s chunks finish whole, which shows the deadline is the 8 s one and not the 4 s socket timeout.
- `test_fetch_with_its_budget_spent_opens_nothing`: **DURABLE**. A spent budget gives None before any open.

### Phase 2 → tests/active/test_internal_translate.py

- `test_an_unknown_video_is_404_video_not_found_with_no_fetch`: **DURABLE**. The 404 comes before any fetch, for an unknown id and for a known uuid on the wrong host. Nothing in active covers it.
- `test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track`: **DURABLE**. The denylist check, against a host stored uppercase, runs before both the store and the network.
- `test_a_ready_track_is_fetched_from_the_row_host_stored_and_then_served_from_subtitles_db_without_a_fetch`: **DURABLE**. Fetching from the row host, the canonical-id key, compact `cues_json`, and serving from subtitles.db after a reopen.
- `test_each_none_path_answers_none_and_stores_nothing`: **DURABLE**. Each `none` path stores nothing.
- `test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate`: **DURABLE**. Startup creates the `subtitles` table at the overridden path, and `/internal/translate` is routed (404 `Video not found`, not `Not found`) behind the bridge gate (401). No active Engine-start test covers either.

### Phase 3 → tests/active/test_server.py

- `test_a_rate_limited_request_is_429_before_the_profile_and_param_checks_with_no_engine_call`: **DURABLE**. The translate route's 429 comes first. No active test touches `/api/translate`.
- `test_a_keyless_request_with_bad_params_is_401_not_400_with_no_engine_call`: **DURABLE**. 401 comes before 400.
- `test_each_bad_param_is_400_with_no_engine_call_and_a_valid_request_reaches_the_bridge_route_with_token_request_id_and_stripped_id_host`: **DURABLE**. The shared allow-list texts, the 200/201 length bound, and the bridge call's token, request id and stripped body.
- `test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502`: **DURABLE**. The `fetch_translate` mapping: `Video not found` gives `none`, and a route-missing 404 or an invalid payload gives 502. `FAILURE_ROUTES` has no translate row.
- `test_an_unreachable_engine_is_a_fixed_502`: **DURABLE**. A transport failure on this route gives the fixed 502.
- `test_a_ready_answer_reaches_the_visitor_with_only_start_end_and_text_per_cue`: **DURABLE**. Extra cue keys are dropped.

### Phase 4 → tests/active/test_frontend_translate.py

- `test_with_a_key_the_toggle_stays_hidden_and_translate_unasked_until_ready_resolves_then_shows_labelled_translate`: **DURABLE**. The toggle waits for `ready`, the label is exactly "Translate", and the page builds one player on `#video-embed`.
- `test_without_a_key_or_a_resolved_ready_there_is_no_toggle_no_translate_request_and_no_escaped_failure`: **DURABLE**. No key, a pending `ready`, a rejected `ready` and a throwing constructor each give no toggle, no request and no escaped rejection, and `originalHref` is still set.
- `test_loaded_with_translate_on_the_overlay_shows_as_text_the_cue_at_each_reported_position_including_after_a_seek_back`: **DURABLE**. The cue lookup (start inclusive, end exclusive, seek back), the overlay staying text-only, `api=1` before the player is built, and one request with the body's uuid and the key.
- `test_a_none_state_reads_no_english_translation_and_a_reported_position_shows_nothing`: **DURABLE**. The exact `none` status text.
- `test_a_click_stores_on_and_asks_once_and_a_second_click_stores_off_after_which_a_reported_position_shows_nothing`: **DURABLE**. The click toggles the `translate:v1` storage, and updates are ignored once off.
- `test_the_embed_src_gains_api_1_with_or_without_a_query_and_a_javascript_or_unparseable_url_sets_no_src`: **DURABLE**. `withEmbedApi` with and without a query; a `javascript:` URL and an unparseable one set no src.
- `test_with_no_reported_position_the_overlay_follows_the_position_the_page_asks_the_player_for`: **DURABLE**. The `getCurrentPosition` polling fallback.

## Step 4: approval

The dispatch treated the plan as approved. I put its two open points to the operator, who chose to move the 14 `probe_*.py` files and `tests/tmp/__pycache__` to `delete_me/` along with the scope, so `tests/tmp` ends up empty. The phase 4 tests went to a new `tests/active/test_frontend_translate.py`, which is the plan's primary option.

Count correction: the four files hold 37 test functions (19 + 5 + 6 + 7), not 38. 34 are DURABLE (16 + 5 + 6 + 7), not 35, and 3 are REDUNDANT. Every DURABLE function in the plan's lists moved; the plan's totals were off by one.

## Step 5: applied

- `tests/active/test_internal_translate.py` (NEW): the 16 DURABLE phase-1 and 5 phase-2 tests, 56 items. Phase 1's `Instance`/`instance` became `ScriptedInstance`/`scripted_instance`, and phase 2's became `RecordingInstance`/`recording_instance`. Phase 2's `Request` became `HandlerRequest`, because phase 1 uses urllib's `Request`. Phase 2's `_translate` became `_handler_module`. `ENGINE_PY` and `ENGINE_START_LOCK` are imported from `conftest`. The module docstring now states the rules without the build identifier, and the `# C1`/`# C2` clause markers were dropped.
- `tests/active/test_server.py` (EXISTING, not split): the 6 phase-3 tests and a docstring section were appended. They reuse its `_serving`, `client_server`, `CLOSED_ENGINE`, `RateLimiter`, `ensure_user_schema` and `mint_profile`. The phase's own pieces came across under their own names: `_TranslateEngine` (the stub), `_translate_engine`, `_keyed_client_backend` (`_client_backend` plus a minted key), `_translate_get`, and the `TRANSLATE_*` constants. Its autouse `bridge_token` became `translate_bridge_token`, a fixture that only these six tests request.
- `tests/active/test_frontend_translate.py` (NEW): the 7 phase-4 tests, 10 items, with their own `RUNNER`, `EMBED_STUB` and `bundle`. The `# C1`/`# C2` markers were dropped and the key renamed to `translate-profile-key`.
- `tests/config.json`: added `test_internal_translate.py` and `test_frontend_translate.py` exactly as planned. `test_server.py` is unchanged.
- `--audit-map` exited 0. Its MISSING findings for `test_internal_translate.py` are `engine/server/data/time.py`, which is imported only transitively and is unclaimed by every other group too, and `engine/server/db/subtitles.db`, the default path rather than a subject. Neither was added.
- Retired: none.

## Step 6: mutations

Each production file was copied to `delete_me/<name>.bak-harvest48-<tag>` (never beside the production file), mutated with one sed edit, run with `validate_tests.py <subject> -k <test>` (red), restored with `cp`, checked with `diff` (clean), and run again (green). The `.pyc` for the module was dropped after every write.

Tool fault found and fixed: m13 survived and m15's green run failed. Both edits kept the line length the same and landed in the same second as the previous write, so Python reused a stale `.pyc`. After the helper started dropping the `.pyc` on every write, I re-ran both as m13b and m15b, and each went red and then green. This was a caching artefact, not a test that lost or never had grip.

- m01 `internal_translate.py` sort removed → `test_well_formed_track_parses_to_plain_text_cues_sorted_by_start` red: text order `Second line` before `First line`.
- m02 `html.unescape` dropped → `test_markup_is_stripped_and_entities_decoded_to_plain_text` red: `x&lt;i&gt;` != `x<i>`.
- m03 a bad timing block `continue`s instead of rejecting the track → `test_any_failing_part_rejects_the_whole_track` red (6 params): `[Kept] is None`.
- m04 `return cues or None` → `return cues` → `test_a_track_with_no_cue_text_is_none` red: `[] is None`.
- m05 `language.id == "en"` → `startswith("en")` → `test_caption_pick_takes_the_first_exact_en_track` red: picked `us.vtt`.
- m06 `fileUrl` same-host check removed → `test_caption_pick_refuses_anything_off_the_host` red: `/track.vtt is None`.
- m07 `redirect_request` always None → `test_redirect_handler_follows_a_same_host_https_target` red: `isinstance(None, Request)`.
- m08 same-host check in `redirect_request` disabled → `test_redirect_handler_refuses_an_off_host_or_non_https_target` red: Request `is None`.
- m09 `redirect_request` always None → `test_fetch_follows_a_same_host_redirect` red: `None == b"WEBVTT\n"`.
- m10 opener built without `SameHostRedirectHandler` → `test_fetch_refuses_an_off_host_or_non_https_redirect` red: `b"LEAKED" is None`.
- m11 declared Content-Length cap disabled → `test_fetch_refuses_a_declared_length_over_the_cap_without_reading` red: reads `[31] == [0]`.
- m12 running byte cap disabled → `test_fetch_refuses_a_body_streamed_past_the_cap` red: body `is None`.
- m13b `FETCH_MAX_BYTES` 2_000_000 → 1_999_999 → `test_fetch_returns_a_body_of_2_000_000_bytes_whole` red (both params): `None == body`.
- m14 per-read deadline check disabled → `test_fetch_refuses_a_body_still_arriving_past_its_deadline` red: `b"c0…c9" is None`.
- m15b deadline from `SOCKET_TIMEOUT_SECONDS` instead of `FETCH_DEADLINE_SECONDS` → `test_fetch_returns_a_body_finished_inside_its_deadline` red: `None == b"c0…c6"`.
- m16 spent-budget early return disabled → `test_fetch_with_its_budget_spent_opens_nothing` red: `opened == []` fails.
- m17 instance fetch inserted before `resolve_video_row` → `test_an_unknown_video_is_404_video_not_found_with_no_fetch` red: `fetched == []` fails.
- m18 denylist check disabled → `test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track` red: 200 ready != 404.
- m19 `_store_cues` call removed → `test_a_ready_track_is_fetched_from_the_row_host_stored_and_then_served_from_subtitles_db_without_a_fetch` red: `(row,) = _stored(...)` has no row.
- m20 the none path stores an empty row → `test_each_none_path_answers_none_and_stores_nothing` red (4 params): `_stored == []` fails.
- m21 `engine/server/api/server.py` `ensure_subtitles_schema` call removed → `test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate` red: `"subtitles" in set()`.
- m22 `client/backend/server.py` translate rate-limit check disabled → `test_a_rate_limited_request_is_429_before_the_profile_and_param_checks_with_no_engine_call` red: keyed valid got 200, not 429.
- m23 `_handle_translate_get` profile check disabled → `test_a_keyless_request_with_bad_params_is_401_not_400_with_no_engine_call` red: 400 != 401.
- m24 length bound 200 → 201 → `test_each_bad_param_is_400_…_stripped_id_host` red: the 201-character cases are not 400.
- m25 `engine_api_client.py` any 404 → none → `test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502[route missing]` red: 200 none != 502.
- m26 the `EngineApiError` branch answers 200 none → `test_an_unreachable_engine_is_a_fixed_502` red: 200 != 502.
- m27 cue passed through unrebuilt → `test_a_ready_answer_reaches_the_visitor_with_only_start_end_and_text_per_cue` red: extra keys `id`/`voice`/`settings`.
- m28 `translate.ts` unhides the toggle in `setupTranslate` before `ready` → `test_with_a_key_the_toggle_stays_hidden_…` red: `(False, False) != (True, False)`.
- m29 profile-key check removed in `onReady` → `test_without_a_key_or_a_resolved_ready_…[no key]` red: shown and asked once.
- m30 `findCue` start made exclusive → `test_loaded_with_translate_on_the_overlay_…_seek_back` red: index 4 (position 1.0) shows nothing instead of `First cue`.
- m31 `NO_TRANSLATION` text changed → `test_a_none_state_reads_no_english_translation_…` red: status text.
- m32 `turnOff` no longer stores off → `test_a_click_stores_on_…_second_click_stores_off_…` red: `"on" == "off"`.
- m33 `withEmbedApi` replaces the query → `test_the_embed_src_gains_api_1_…` red: `start=10` lost.
- m34 `startPolling` not called → `test_with_no_reported_position_the_overlay_follows_…` red: `positionCalls 0 >= 1`.

Every green re-run passed. Every mutated production file was `diff`-clean against its copy afterwards. No `.bak` is left in the production tree; the only one is the pre-existing `engine/server/db/whitelist.db.bak-20261002-212806`, which is not from this harvest.

## Step 7: disposed

Moved to `delete_me/`, with no name collisions:
- the four scope files `test_48_translate_instance_captions_phase{1,2,3,4}.py`;
- the 14 probes `probe_48_phase2.py`, `probe_48_phase3.py`, `probe_48_phase3_observe.py`, `probe_48_phase4.py`, `probe_opener.py`, `probe_phase2_fixture.py`, `probe_phase2_routes.py`, `probe_phase2_standin.py`, `probe_phase4_controls.py`, `probe_red_suite.py`, `probe_redirect_308.py`, `probe_standin.py`, `probe_suite_red.py`, `probe_translate_bundle.py`;
- `__pycache__/`.

`tests/tmp` is empty. The mutation helper `harvest48-mutate.sh`, the 36 mutation copies `*.bak-harvest48-m*`, and the red/green logs `harvest48-m*.{red,green}.txt` are in `delete_me/` too.

## Step 8: comparison

I restored `tests/last_test_validation.json.preharvest` over the record, then ran `validate_tests.py --compare` with no tier. It reports 79 items appeared and nothing else: no departures, no new red, nothing newly green.
- `test_frontend_translate`: 10 items.
- `test_internal_translate`: 56 items.
- `test_server`: 13 items (6 tests).

Groups the closing run re-ran: `test_frontend_translate` (10 passed), `test_internal_translate` (56 passed), `test_server` (112 passed), `test_search_fusion` (10 passed) and `test_static_page_visit_logs` (10 passed). The rest were current against the pre-harvest record and carried forward. The record is banked.
