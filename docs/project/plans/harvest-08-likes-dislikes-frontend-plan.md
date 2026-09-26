# Harvest: plan 08 (likes and dislikes frontend)

## Step 1 — Trees and scope

- `project_dir`: `/home/enduser/code/PeerTube-browser`
- `active`: `tests/active`; `working`: `tests/tmp`; `plans`: `docs/project/plans`; `delete_me`: `delete_me`; `archive`: `tests/archive`; `record`: `tests/last_test_validation.json`
- Bootstrap gate: clear (`defaulted` empty, `conflicts` empty).
- Snapshot: `tests/last_test_validation.json.preharvest` taken before any harvest work ran (48 passed banked).
- **Scope** (the build's checkpoints; WORKING_FILE `docs/project/plans/08-likes-dislikes-frontend.md`):
  - `tests/tmp/test_frontend_keyless_likes.py`
  - `tests/tmp/test_frontend_keyed_reactions.py`
  - `tests/tmp/test_frontend_likes_import.py`
  - `tests/tmp/test_card_reactions.py`
  - `tests/tmp/test_undone_like_neutral.py`
- Disposed at Step 7 with them, not classified (no tests): `tests/tmp/conftest.py` (byte-identical to `tests/active/conftest.py`), `tests/tmp/probe_keyless.py`, `tests/tmp/probe_step8_checks.py`, `tests/tmp/tsc.out`.

## Step 2 — Inventory

### tests/tmp/test_frontend_keyless_likes.py
- Drives `client/frontend/src/data/reactions.ts` (`fetchReaction`, `sendReaction`) and `local-likes.ts`, bundled in node, against the real Client and Engine (`engine_client`, `unpublished_client`, `dataset`).
- Tests: `test_a_keyless_like_reads_back_liked_and_its_undo_reads_back_not_liked`, `test_a_keyless_like_the_client_refuses_throws_and_leaves_the_stored_likes_unchanged`.
- Module-level: `RUNNER`, `_bundle`, `_run`, `_videos`, `_withdraw`.

### tests/tmp/test_frontend_keyed_reactions.py
- Drives `reactions.ts` with a key, and `local-likes.ts`, `profile.ts`, against the real Client and Engine (`engine_client`).
- Tests: `test_with_a_key_fetch_reaction_reads_the_profile_s_state_after_each_action`, `test_with_a_key_a_like_the_profile_holds_is_not_kept_in_the_browser`.
- Module-level: `RUNNER` (with `wait`), `_Node`, `_server_reaction`, `_act`, `_withdraw_if_liked`, `UNKNOWN_KEY`.

### tests/tmp/test_frontend_likes_import.py
- Drives `reactions.ts` `importLocalLikes` against the real Client (`unpublished_client`).
- Tests: `test_with_a_key_the_import_moves_every_local_like_into_the_profile_and_empties_the_store`, `test_an_import_the_client_refuses_keeps_the_local_likes`.
- Module-level: `RUNNER`, `_liked`, `UNKNOWN_KEY`.

### tests/tmp/test_card_reactions.py
- Test 1 drives `client/backend/server.py`'s read proxy over HTTP (`_profile_filter`, `_filter_payload`).
- Test 2 drives `reactions.ts` `cardReaction` and `components/video-card.ts` `renderVideoCard` in node over `fetchSearchResults` rows.
- Tests: `test_a_keyed_search_marks_the_profile_s_liked_and_disliked_rows_and_a_keyless_one_marks_none`, `test_a_card_shows_the_like_or_dislike_the_client_marked_or_the_like_the_browser_holds_and_nothing_else`.
- Module-level: `RUNNER` (`cards`), `QUERY`, `SEARCH`, `_search`, `_profile_reacting`, `_key`, `_unmarked`.

### tests/tmp/test_undone_like_neutral.py
- Drives `engine/server/data/random_videos.py` (`fetch_random_rows`, `fetch_popular_videos`) in-process, on a temp copy of two `whitelist.db` videos, with the real `ingest_interaction_event`.
- Tests: `test_an_undone_like_leaves_the_random_row_s_likes_at_the_crawled_count`, `test_an_undone_like_keeps_the_popular_order_of_two_tied_videos`.
- Module-level: `_two_video_db`, `_set_views`, `_event`, `_likes_by_video`, `_popular`, `_popular_order`, `CRAWLED_LIKES`, `POPULARITY`.

All five collect (2 node ids each) and pass.

## Step 3 — Classification

Subject files:
- `client/frontend/src/data/reactions.ts` has none in `active`. It is created as `tests/active/test_frontend_reactions.py`, following `test_frontend_blocks.py` / `test_frontend_profile.py`, which name the frontend data module they drive.
- `engine/server/data/random_videos.py` has none. It is created as `tests/active/test_random_videos.py`, as `test_db.py` is named for `engine/server/data/db.py`.
- The read proxy's reaction mark goes to `tests/active/test_profiles.py`, the subject that holds the profile's likes on the proxy (keyed likes, the import).

- `test_a_keyless_like_reads_back_liked_and_its_undo_reads_back_not_liked` — **DURABLE** → `test_frontend_reactions.py`. No active test drives the browser's like store through the Client.
- `test_a_keyless_like_the_client_refuses_throws_and_leaves_the_stored_likes_unchanged` — **DURABLE** → `test_frontend_reactions.py`. It gates L3 (a failed like stores nothing), asserted nowhere else.
- `test_with_a_key_fetch_reaction_reads_the_profile_s_state_after_each_action` — **DURABLE** → `test_frontend_reactions.py`. `test_dislikes.py` asserts the reaction route. This asserts the frontend reads it, including a change made outside the module and a refused key.
- `test_with_a_key_a_like_the_profile_holds_is_not_kept_in_the_browser` — **DURABLE** → `test_frontend_reactions.py`. It gates L8 (keyed likes never in the browser).
- `test_with_a_key_the_import_moves_every_local_like_into_the_profile_and_empties_the_store` — **DURABLE** → `test_frontend_reactions.py`. `test_profiles.py` asserts the import route; this asserts the frontend trigger and the clear.
- `test_an_import_the_client_refuses_keeps_the_local_likes` — **DURABLE** → `test_frontend_reactions.py`. It gates keeping local likes on a refused import (data loss).
- `test_a_keyed_search_marks_the_profile_s_liked_and_disliked_rows_and_a_keyless_one_marks_none` — **DURABLE** → `test_profiles.py`. No active test asserts the `reaction` mark.
- `test_a_card_shows_the_like_or_dislike_the_client_marked_or_the_like_the_browser_holds_and_nothing_else` — **DURABLE** → `test_frontend_reactions.py`. No active test renders a card's reaction.
- `test_an_undone_like_leaves_the_random_row_s_likes_at_the_crawled_count` — **DURABLE** → `test_random_videos.py`. The ingest contract test asserts the stored counters, not the reads.
- `test_an_undone_like_keeps_the_popular_order_of_two_tied_videos` — **DURABLE** → `test_random_videos.py`.

No REPLACES, COMBINE, REDUNDANT or SPENT. Nothing in `active` is retired.

**Merge note.** The four frontend files each carry their own node runner. In `test_frontend_reactions.py` they become one `RUNNER` whose steps are the union: `seed` for one like, `seedlist` for several, `store` for a key, then `create`, `stored`, `browser`, `read`, `react`, `import`, `cards` and `wait`. There is one `_bundle` exporting what the tests use, and the `_Node` stdin driver serves every test. Each test's assertions move unchanged. Step 6's mutations check that the merged runner still discriminates.

**`test_groups` changes:**
- `test_frontend_reactions.py` (NEW): `client/frontend/src/data/reactions.ts`, `client/frontend/src/data/local-likes.ts`, `client/frontend/src/data/user-actions.ts`, `client/frontend/src/components/video-card.ts`, `client/backend/server.py`.
- `test_random_videos.py` (NEW): `engine/server/data/random_videos.py`.
- `test_profiles.py`: gains `client/backend/lib/dislikes.py` (the mark reads the profile's dislikes).

## Step 4 — Plan agreed

Operator: "Approve" (10 DURABLE; 2 new subject files; 1 test into `test_profiles.py`; `test_groups` +2 entries and `test_profiles.py` gains `client/backend/lib/dislikes.py`; `tests/tmp` to `delete_me/`).

## Step 5 — Applied

- `tests/active/test_frontend_reactions.py` (NEW), 7 tests. The four checkpoint runners are merged into one `RUNNER`: `seed` (one like) and `seedlist` (several), `store` (a key, which was `key` in the card test), `create`, `stored`, `browser`, `read`, `react`, `import`, `cards`, `wait`. Assertions are unchanged. The build's clause markers were dropped, and the module docstring states the rules.
- `tests/active/test_profiles.py`: `test_a_keyed_search_marks_the_profile_s_liked_and_disliked_rows_and_a_keyless_one_marks_none` added, with `_search_by_key`. It reuses `_key_header`, and the module docstring gains its rule.
- `tests/active/test_random_videos.py` (NEW), 2 tests, copied whole; the clause markers were dropped.
- `test_groups`: `test_frontend_reactions.py` → `reactions.ts`, `local-likes.ts`, `user-actions.ts`, `video-card.ts`, `server.py`; `test_random_videos.py` → `engine/server/data/random_videos.py`; `test_profiles.py` gains `client/backend/lib/dislikes.py`.
- `--audit-map`: exit 0. Advisory `MISSING test_random_videos.py engine/server/db/whitelist.db`, left unclaimed deliberately: it is the fixture's data source, not what the test tests. The other advisories are pre-existing.
- Nothing retired; `tests/archive` untouched.

## Step 6 — Mutations (each run alone with `-k`, each restore `diff`-clean, each backup moved to `delete_me/`)

- `test_a_keyless_like_reads_back_liked_and_its_undo_reads_back_not_liked` — `reactions.ts`: `addLocalLike` removed from `sendReaction`. Felled `:216` (`False is True`, liked after the like).
- `test_a_keyless_like_the_client_refuses_throws_and_leaves_the_stored_likes_unchanged` — `reactions.ts`: the keyless like is stored before the request. Felled `:243` (the unknown video in the store after its refusal). A first attempt ran against the unmutated file, because the Edit was refused as stale and ran in parallel with the test; it passed and was discarded as no evidence.
- `test_with_a_key_fetch_reaction_reads_the_profile_s_state_after_each_action` — `reactions.ts`: `fetchReaction` reads `localLikes:v1` whatever the key. Felled `:296` (`(False, False) == (True, False)`).
- `test_with_a_key_a_like_the_profile_holds_is_not_kept_in_the_browser` — `reactions.ts`: the key guard around the local writes removed. Felled `:338` (the video in `getStoredLikes()`).
- `test_with_a_key_the_import_moves_every_local_like_into_the_profile_and_empties_the_store` — `reactions.ts`: `clearLocalLikes()` removed from `importLocalLikes`. Felled `:361` (the store still holding the three likes).
- `test_an_import_the_client_refuses_keeps_the_local_likes` — `reactions.ts`: `clearLocalLikes()` before the request. Felled `:374` (`[] == held`).
- `test_a_card_shows_the_like_or_dislike_the_client_marked_or_the_like_the_browser_holds_and_nothing_else` — `video-card.ts`: the likes stat's class ignores the reaction. Felled `:414` (the liked card with no active stat).
- `test_a_keyed_search_marks_the_profile_s_liked_and_disliked_rows_and_a_keyless_one_marks_none` — `server.py` `_filter_payload`: the liked mark removed. Felled `test_profiles.py:306` (`None == 'liked'`).
- `test_an_undone_like_leaves_the_random_row_s_likes_at_the_crawled_count` — `random_videos.py:45`: `- COALESCE(sig.undo_likes_count, 0)` restored. Felled `:102` (`6 == 7`).
- `test_an_undone_like_keeps_the_popular_order_of_two_tied_videos` — `random_videos.py:248`: the same term restored in the tiebreak. Felled `:122` (`[low, high]`).
- After the restores: `test_frontend_reactions.py` 7 passed, `test_random_videos.py` 2 passed, the new `test_profiles.py` test passed. No `.bak` remains under `client/` or `engine/`. The snapshot `tests/last_test_validation.json.preharvest` is still on disk.

## Step 7 — Disposed

To `delete_me/plan08-tmp/`: the five checkpoint files, `conftest.py` (a copy of the active one), `probe_keyless.py`, `probe_step8_checks.py`, `tsc.out` and `__pycache__`. `tests/tmp` is empty. The four mutation backups are in `delete_me/` (`reactions.ts.bak`, `video-card.ts.bak`, `server.py.bak`, `random_videos.py.bak`).

## Step 8 — Suite

Snapshot restored (`tests/last_test_validation.json.preharvest` → the record), then `--compare`:
- 3 of 10 groups selected: `test_frontend_reactions.py` (no record) 7 passed, `test_profiles.py` (changed) 11 passed, `test_random_videos.py` (no record) 2 passed.
- **Appeared:** the 10 harvested tests, and nothing else. **Gone:** none. No new red, no red cleared.
- Total: 58 (48 before + 10). The seven unchanged groups carried forward green.
