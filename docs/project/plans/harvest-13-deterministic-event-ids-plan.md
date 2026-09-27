# Harvest: 13 deterministic event ids

Run on main after the wave 2 merges (build 13 and build 14 are both merged), as the batch plan requires (`.scratch/security-hardening-batch/notes.md`). This replaces the worktree draft of the same name, whose paths named the removed worktree.

## Step 1: resolved paths

From `validate_tests.py --show-config`, run from the project root on 2026-09-27:

- project_dir: `/home/enduser/code/PeerTube-browser`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive` (does not exist yet; it is created on the first retirement)
- record: `tests/last_test_validation.json`
- Bootstrap gate: clear. `defaulted` is empty, `conflicts` is empty, and every `map_health` list is empty.

Snapshot: `tests/last_test_validation.json.preharvest` was taken before any harvest run, from the record banked at 2026-09-27T04:14:29. That record is a bare run over `tests/active` on the merged main: exit 0, 146 tests in the summary.

### Scope

The three test files build 13 wrote (`docs/project/plans/16-13-deterministic-event-ids.md`):

- `tests/tmp/test_13_deterministic_event_ids_phase1.py`
- `tests/tmp/test_13_deterministic_event_ids_phase2.py`
- `tests/tmp/test_13_deterministic_event_ids_phase3.py`

Build 13 also left four probes in `tests/tmp`: `probe_13_phase2.py`, `probe_13_phase3.py`, `probe_cap.py` and `probe_like_generations.py`. They are not `test_*.py` files and gate nothing. They are proposed for disposal with the scope at Step 7. Build 14's files in `tests/tmp` are outside this scope and belong to the harvest that follows.

## Step 2: inventory

The three files together, run through `validate_tests.py` on main, give 9 passed and 1 failed.

**Collection finding: one test fails on the merged tree.** `test_an_undo_like_of_an_imported_like_publishes_nothing` gets a 502 from `POST /api/profile/likes/import`. The cause is its stub Engine, which answers only `/internal/videos/resolve`. Since build 14, likes import resolves through one `/internal/videos/metadata` call (`client/backend/server.py` `_handle_likes_import` calls `fetch_metadata_for_entries`), which the stub answers 404. This is a harness gap between the two builds, not a regression: the import behaviour 13 relies on (an import passes no `publish`, so it opens no generation) is intact at `server.py:905`.

### tests/tmp/test_13_deterministic_event_ids_phase1.py

- Drives: `engine/server/data/random_videos.py` (`fetch_popular_videos`, `POPULAR_SIGNAL_CAP`).
- Module deps: `sys.path` setup for `engine/server` and `engine/server/api`; `WHITELIST_DB`; the constants `SIGNAL`, `CAP` and `SUB_CAP_SIGNAL`; the helpers `_two_video_db`, `_set_popularity` and `_set_signal`.
- Tests:
  - `test_the_popular_order_caps_the_interaction_signal`, which passes.

### tests/tmp/test_13_deterministic_event_ids_phase2.py

- Drives: `client/backend/server.py` (`_handle_user_action`, `_store_reaction`, `_handle_likes_import`) through `client/backend/lib/users_store.py` (`record_like(publish=True)`, `close_like`). It runs over HTTP against a real `ClientBackendServer`, whose Engine is a stub. The stub's ingest route runs the real `ingest_interaction_event` on a temporary `engine.db`.
- Module deps: conftest's `ClientBackend`, `RateLimiter`, `client_server` and `ensure_user_schema`; the Engine's `sys.path`, set up after the conftest import; `HOST`; the helpers `_event_id`, `_serving`, `_mint`, `_video`, `_act`, `_reaction`, `_published` and `_signal`; the `rig` fixture, with an inline `EngineStub`.
- Tests:
  - `test_a_repeated_like_publishes_one_like_at_generation_1`, which passes.
  - `test_like_undo_like_like_publishes_like_undolike_like_under_generations_1_1_2`, which passes.
  - `test_two_anonymous_likes_carry_one_id_and_the_engine_counts_the_second_as_a_duplicate`, which passes.
  - `test_a_like_named_in_a_non_canonical_spelling_derives_its_id_from_the_resolved_identity`, which passes.
  - `test_an_undo_like_of_an_unliked_video_answers_200_and_publishes_nothing`, which passes.
  - `test_a_dislike_replacing_a_like_publishes_the_undo_likes_id_and_one_of_an_unliked_video_publishes_nothing`, which passes.
  - `test_a_like_after_a_reset_publishes_nothing_and_the_next_undo_like_withdraws_the_first`, which passes.
  - `test_an_undo_like_of_an_imported_like_publishes_nothing`, which **fails on main** (stub gap, above).

### tests/tmp/test_13_deterministic_event_ids_phase3.py

- Drives: `client/backend/lib/profiles.py` (`delete_profile`) through `POST /api/profile/delete` on conftest's `client_backend`. It seeds rows through `users_store.record_like(publish=True)`, `remove_like` and `close_like`.
- Module deps: the `client_backend` fixture; `HOST`; the helpers `_mint`, `_seed_like`, `_seed_undone_like` and `_rows_for`, which counts four tables.
- Tests:
  - `test_deleting_a_profile_removes_its_open_and_closed_like_generations_and_keeps_anothers`, which passes.

## Step 3: classification

Checked against main's `tests/active`. Nothing there asserts the popular-order cap, the id of a published event, like generations, or publish-on-change at the Engine boundary. `test_dislikes`, `test_frontend_reactions`, `test_profiles` and `test_server` do drive `/api/user-action`, but always through `unpublished_client` or a closed Engine. They read a status and never an event.

Counts: DURABLE 9, COMBINE 1, REPLACES 0, REDUNDANT 0, SPENT 0.

### → existing `tests/active/test_random_videos.py`

- `test_the_popular_order_caps_the_interaction_signal`: **DURABLE**. The cap on the signal in `fetch_popular_videos` is asserted nowhere; the only popular-order test in active uses a signal of 1.0. It reuses the active `_two_video_db`. That helper also sets views to 1000/10 and crawled likes to 7, but those are tie-breakers after the popularity term, and no case in this test ties on that term (the closest pairs differ by 0.5). `_set_popularity`, `_set_signal`, `SIGNAL`, `CAP` and `SUB_CAP_SIGNAL` move with it.

### → existing `tests/active/test_server.py` (subject: `client/backend/server.py`)

The behaviour lives in `server.py`'s `_handle_user_action`, and a harvest binds one script to one test file, so these tests go to `test_server.py`. They reuse its `_serving` and `_client_backend` rather than carrying second copies. The `rig` fixture becomes `_client_backend` plus conftest's `ClientBackend` over the same `users.db`.

- `test_a_repeated_like_publishes_one_like_at_generation_1`: **DURABLE**. The no-reopen rule, and the id at generation 1.
- `test_like_undo_like_like_publishes_like_undolike_like_under_generations_1_1_2`: **DURABLE**. The generation advance on a re-open, which gives distinct Like ids.
- `test_two_anonymous_likes_carry_one_id_and_the_engine_counts_the_second_as_a_duplicate`: **DURABLE**. An anonymous id is deterministic at generation 0.
- `test_a_like_named_in_a_non_canonical_spelling_derives_its_id_from_the_resolved_identity`: **DURABLE**. The id hashes the resolved identity, not the one sent.
- `test_an_undo_like_of_an_unliked_video_answers_200_and_publishes_nothing`: **DURABLE**. An undo that closes nothing publishes nothing.
- `test_a_dislike_replacing_a_like_publishes_the_undo_likes_id_and_one_of_an_unliked_video_publishes_nothing`: **DURABLE**. A dislike withdraws a published like under that like's generation.
- `test_a_like_after_a_reset_publishes_nothing_and_the_next_undo_like_withdraws_the_first`: **DURABLE**. A like still published survives a reset and is not re-opened.
- `test_an_undo_like_of_an_imported_like_publishes_nothing`: **DURABLE**, moved with a harness fix. The stub Engine gains a `/internal/videos/metadata` route that answers `{video_uuid, instance_domain}` entries with the same lower-cased canonical identity its resolve route gives (`{"ok": true, "count", "rows": [{video_id, video_uuid, instance_domain}]}`), so the test drives the post-14 import path. The assertions do not change.

### → existing `tests/active/test_profiles.py`

- `test_deleting_a_profile_removes_its_open_and_closed_like_generations_and_keeps_anothers`: **COMBINE** with the active `test_deleting_a_profile_removes_its_rows_and_keeps_anothers`.
  - What the working test adds: the `like_generations` counts, open and closed.
  - What the active test adds: the key reads 200 before the delete and 401 after it.
  - The merge starts from the working test, which carries more, and lifts in the active test's `_read` assertions.
  - The survivor is `test_deleting_a_profile_removes_its_rows_and_like_generations_and_keeps_anothers`.
  - The emptied active function is retired to `tests/archive/profile_deletion/test_profiles.py`.
  - Helper changes, which correct the worktree draft: the active `_seed_like` gains a `publish: bool = False` parameter, and only the merged test passes `True`. The draft set `publish=True` for every caller, which would silently change what four other tests seed. `_rows_for` gains the `like_generations` count. Its only readers are the test being merged, so no other assertion changes. `_seed_undone_like` moves in, and so do the `close_like` and `remove_like` imports.

### test_groups change

- `test_server.py`: add `client/backend/lib/users_store.py` (`record_like` and `close_like` decide what publishes) and `client/backend/lib/engine_api_client.py` (the resolve and metadata calls the tests drive). The stub Engine's real `ingest_interaction_event` is a fixture and is not claimed.
- `test_random_videos.py` and `test_profiles.py`: unchanged. They already claim `random_videos.py`, and `profiles.py` with `users_store.py`.
- No subject file is created.

## Step 4: approval

Approved by the operator on 2026-09-27, as recorded: every verdict, the stub fix to the import test, the `_seed_like(publish=False)` default, and the `test_server.py` map entry.

## Step 5: applied

- `tests/active/test_random_videos.py`: the cap test was added, with `SIGNAL`, `CAP`, `SUB_CAP_SIGNAL`, `_set_popularity` and `_set_signal`. It reuses the active `_two_video_db`. The module docstring states the rule.
- `tests/active/test_server.py`: the eight event tests were added, with the `rig` fixture (built on the file's `_serving` and `_client_backend`) and the helpers `_event_id`, `_canonical`, `_mint_profile` (renamed from `_mint`, which the file already defines with another return shape), `_video`, `_act`, `_reaction`, `_published` and `_signal`. The stub Engine answers `/internal/videos/metadata`. The Engine's `sys.path` entries go in after the conftest import. The module docstring states the rules. Phase-numbered `# C1`/`# C2` markers were dropped, and the `control` comments kept.
- `tests/active/test_profiles.py`: the merged `test_deleting_a_profile_removes_its_rows_and_like_generations_and_keeps_anothers` was added. `_seed_like` gains `publish=False`; `_seed_undone_like` was added; `_rows_for` counts `like_generations`; and `close_like` and `remove_like` are imported. The merged test also asserts that the kept profile's key still reads 200 after the delete.
- Retired: `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` → `tests/archive/profile_deletion/test_profiles.py`. It is module-skipped, because pytest has no `testpaths` and a bare run would otherwise collect it.
- `test_groups`: `test_server.py` gains `client/backend/lib/users_store.py` and `client/backend/lib/engine_api_client.py`. `--audit-map` exits 0; its MISSING advisories name only data files (`*.db`) and `data/time.py` for `test_db.py`, none of them this harvest's.

## Step 6: mutations

Each mutation was run by `.scratch/security-hardening-batch/mutate.py` in five steps: an exact single replacement, the target test run red, a byte-exact restore, the backup moved to `delete_me/`, and the target test run green.

- H13-M1 `random_videos.py`: `POPULAR_SIGNAL_CAP` 25.0 → 1000.0. Felled `test_the_popular_order_caps_the_interaction_signal` at its first ordering assertion.
- H13-M2 `server.py`: a profile publishes on every like. Felled `test_a_repeated_like_publishes_one_like_at_generation_1`: `['Like', 'Like'] != ['Like']`.
- H13-M3 `users_store.py`: a re-open no longer advances the generation. Felled `test_like_undo_like_like_…_1_1_2` at the distinct-Like-ids assertion.
- H13-M4 `server.py`: the anonymous generation goes from 0 to 1. Felled `test_two_anonymous_likes_…` at the id assertion.
- H13-M5 `server.py`: the id hashes the uuid and host as sent. Felled `test_a_like_named_in_a_non_canonical_spelling_…` at the id assertion; its two controls passed.
- H13-M6 `server.py`: every undo_like publishes. Felled `test_an_undo_like_of_an_unliked_video_…`: `rig.events == []`.
- H13-M7 `server.py`: a dislike withdraws under generation + 1. Felled `test_a_dislike_replacing_a_like_…` at the UndoLike id.
- H13-M8 `users_store.py`: the upsert drops `WHERE published = 0`, so a like still published is re-opened. Felled `test_a_like_after_a_reset_…`: `['Like', 'Like'] != ['Like']`.
- H13-M9 `server.py`: likes import passes `publish=True`. Felled `test_an_undo_like_of_an_imported_like_…`: `rig.events == []`.
- H13-M10 `profiles.py`: the delete no longer removes `like_generations` rows. Felled `test_deleting_a_profile_removes_its_rows_and_like_generations_…`: `{'like_generations': 2} != {… 0}`.

Every restore was byte-exact and every target went green again. No `.bak` file remains under `client/` or `engine/`.

## Step 7: disposal

Moved to `delete_me/`, with no name collisions:
- the scope: `test_13_deterministic_event_ids_phase1.py`, `test_13_deterministic_event_ids_phase2.py` and `test_13_deterministic_event_ids_phase3.py`;
- the probes: `probe_13_phase2.py`, `probe_13_phase3.py`, `probe_cap.py` and `probe_like_generations.py`.

Build 14's files remain in `tests/tmp` for its own harvest.

## Step 8: suite

The snapshot was restored, then `validate_tests.py --compare` ran with no tier. It selected the three changed groups; the 13 others were unchanged. Results: `test_profiles` 11 passed, `test_random_videos` 3 passed, `test_server` 41 passed, 55 passed in total, exit 0.

Movement against the pre-harvest record: 10 appeared, which are the ten harvested tests, and 1 gone, the retired `test_deleting_a_profile_removes_its_rows_and_keeps_anothers`. Nothing else moved. The suite total goes from 146 to 155.
