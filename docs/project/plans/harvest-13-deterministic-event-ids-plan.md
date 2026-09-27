# Harvest: 13 deterministic event ids

Scope argument: the three test files build 13 (deterministic event ids) wrote in `tests/tmp`, as named by the dispatch.

## Step 1: resolved paths

- project_dir: `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive` (does not exist yet; created on first retirement)
- record: `tests/last_test_validation.json`
- bootstrap gate: clear (`defaulted` empty, `conflicts` empty, `map_health` all empty)

Snapshot: `tests/last_test_validation.json.preharvest` was taken before any harvest run. The record's timestamp is 2026-09-27T03:55:29, it targets `tests/active`, and it shows 75 passed with exit 0. That is a whole-suite record, not the probe-only record Phase 2's note describes, so it can serve as the pre-harvest baseline.

### Scope

- `tests/tmp/test_13_deterministic_event_ids_phase1.py`
- `tests/tmp/test_13_deterministic_event_ids_phase2.py`
- `tests/tmp/test_13_deterministic_event_ids_phase3.py`

Build-13 probe files are also in `tests/tmp`. They are not `test_*.py`, and they are proposed for disposal alongside the scope, pending approval at Step 4: `probe_13_phase2.py`, `probe_13_phase3.py`, `probe_cap.py`, `probe_like_generations.py` (Phase 2 asked for this last one to be deleted).

## Step 2: inventory

All three files collect and pass: `validate_tests.py` on the three paths gives 10 passed.

### tests/tmp/test_13_deterministic_event_ids_phase1.py

- Drives: `engine/server/data/random_videos.py` (`fetch_popular_videos`, `POPULAR_SIGNAL_CAP`).
- Module deps: sys.path setup for `engine/server` and `engine/server/api`; `WHITELIST_DB`; `SIGNAL`, `CAP`, `SUB_CAP_SIGNAL`; helpers `_two_video_db`, `_set_popularity`, `_set_signal`.
- Tests:
  - `test_the_popular_order_caps_the_interaction_signal`

### tests/tmp/test_13_deterministic_event_ids_phase2.py

- Drives: `client/backend/server.py` (`_handle_user_action`, `_store_reaction`, `_handle_likes_import`) through `client/backend/lib/users_store.py` (`record_like(publish=True)`, `close_like`), over HTTP on a real `ClientBackendServer` against a stub Engine whose ingest route runs the real `ingest_interaction_event`.
- Module deps: conftest's `ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`; Engine sys.path set up after the conftest import; `HOST`; helpers `_event_id`, `_serving`, the `rig` fixture (with an inline `EngineStub`), `_mint`, `_video`, `_act`, `_reaction`, `_published`, `_signal`.
- Tests:
  - `test_a_repeated_like_publishes_one_like_at_generation_1`
  - `test_like_undo_like_like_publishes_like_undolike_like_under_generations_1_1_2`
  - `test_two_anonymous_likes_carry_one_id_and_the_engine_counts_the_second_as_a_duplicate`
  - `test_a_like_named_in_a_non_canonical_spelling_derives_its_id_from_the_resolved_identity`
  - `test_an_undo_like_of_an_unliked_video_answers_200_and_publishes_nothing`
  - `test_a_dislike_replacing_a_like_publishes_the_undo_likes_id_and_one_of_an_unliked_video_publishes_nothing`
  - `test_a_like_after_a_reset_publishes_nothing_and_the_next_undo_like_withdraws_the_first`
  - `test_an_undo_like_of_an_imported_like_publishes_nothing`

### tests/tmp/test_13_deterministic_event_ids_phase3.py

- Drives: `client/backend/lib/profiles.py` (`delete_profile`) through POST /api/profile/delete on conftest's `client_backend`; seeds through `users_store.record_like(publish=True)`, `remove_like`, `close_like`.
- Module deps: `client_backend` fixture; `HOST`; helpers `_mint`, `_seed_like`, `_seed_undone_like`, `_rows_for` (four tables).
- Tests:
  - `test_deleting_a_profile_removes_its_open_and_closed_like_generations_and_keeps_anothers`

## Step 3: classification

I searched `tests/active` for `user-action`, `event_id`, `like_generation`, `close_like`, `UndoLike`, `POPULAR_SIGNAL_CAP` and `signal_score`. Nothing there asserts the popular-order cap, a published event's id, like generations, or publish-on-change at the Engine boundary. `test_dislikes`, `test_frontend_reactions`, `test_profiles` and `test_server` do drive `/api/user-action`, but always through `unpublished_client`, where they read a 502 or 200 status and never an event. None of them asserts which events were published or with which id.

Counts: DURABLE 9, COMBINE 1, REPLACES 0, REDUNDANT 0, SPENT 0.

### → existing `tests/active/test_random_videos.py`

- `test_the_popular_order_caps_the_interaction_signal`: **DURABLE**. The cap on the signal in `fetch_popular_videos` is asserted nowhere. The only popular-order test in active uses a signal of 1.0, well under the cap. The test reuses the active file's `_two_video_db`, whose views and likes tie-breakers come after the popularity term and so cannot decide any case here.

### → existing `tests/active/test_server.py` (subject: `client/backend/server.py`)

The plan's checkpoint named a new `test_event_ids.py`. The harvest binds one script to one test file, and the behaviour lives in `server.py`'s `_handle_user_action`, so these tests go to `test_server.py`. They reuse its `_serving` and `_client_backend` rather than carrying a second copy.

- `test_a_repeated_like_publishes_one_like_at_generation_1`: **DURABLE**. The C1 no-reopen rule and the C2 id at generation 1.
- `test_like_undo_like_like_publishes_like_undolike_like_under_generations_1_1_2`: **DURABLE**. The generation advance on a re-open, which gives distinct Like ids.
- `test_two_anonymous_likes_carry_one_id_and_the_engine_counts_the_second_as_a_duplicate`: **DURABLE**. An anonymous id is deterministic at generation 0.
- `test_a_like_named_in_a_non_canonical_spelling_derives_its_id_from_the_resolved_identity`: **DURABLE**. The id hashes the resolved identity, not the one sent.
- `test_an_undo_like_of_an_unliked_video_answers_200_and_publishes_nothing`: **DURABLE**. An undo that closes nothing publishes nothing.
- `test_a_dislike_replacing_a_like_publishes_the_undo_likes_id_and_one_of_an_unliked_video_publishes_nothing`: **DURABLE**. A dislike withdraws a published like under that like's generation.
- `test_a_like_after_a_reset_publishes_nothing_and_the_next_undo_like_withdraws_the_first`: **DURABLE**. A like still published survives a reset and is not re-opened.
- `test_an_undo_like_of_an_imported_like_publishes_nothing`: **DURABLE**. An import opens no generation.

### → existing `tests/active/test_profiles.py`

- `test_deleting_a_profile_removes_its_open_and_closed_like_generations_and_keeps_anothers`: **COMBINE** with active `test_deleting_a_profile_removes_its_rows_and_keeps_anothers`. The working test adds the `like_generations` count, open and closed. The active test adds the key reading 200 before the delete and 401 after it. The merge starts from the working test (it carries more) and lifts in the active test's `_read` assertions. The survivor is `test_deleting_a_profile_removes_its_rows_and_like_generations_and_keeps_anothers`. The emptied active function is retired to `tests/archive/profile_deletion/test_profiles.py`. `_seed_like` gains `publish=True` and `_rows_for` gains the `like_generations` count. Both helpers are used only by tests that tolerate this: publish just adds a generation row, and the other readers of `_rows_for` are only in this test.

### test_groups change

- `test_server.py`: add `client/backend/lib/users_store.py` (`record_like`/`close_like` decide what publishes) and `client/backend/lib/engine_api_client.py` (the resolve and import-resolve paths the tests drive). The stub Engine's real `ingest_interaction_event` is a fixture and is not claimed.
- `test_random_videos.py`, `test_profiles.py`: unchanged, because they already claim `random_videos.py`, `profiles.py` and `users_store.py`.
- No subject file is created.
