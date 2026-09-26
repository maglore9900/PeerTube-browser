# Harvest: plan 07 (channel and account blocks)

## Resolved paths

- `project_dir`: `/home/enduser/code/PeerTube-browser`
- `active`: `tests/active`
- `working`: `tests/tmp`
- `plans`: `docs/project/plans`
- `delete_me`: `delete_me`
- `archive`: `tests/archive`
- `record`: `tests/last_test_validation.json`, snapshotted to `tests/last_test_validation.json.preharvest` at Step 1.

## Scope

The checkpoints plan 07 recorded:
- `tests/tmp/test_engine_row_identity.py` (Phase 1)
- `tests/tmp/test_block_routes.py` (Phase 2)
- `tests/tmp/test_block_filtering.py` (Phase 3)
- `tests/tmp/test_block_frontend.py` (Phase 4)

Their shared seam `tests/tmp/conftest.py` is a helper, not a test. The build's other `working` files go to `delete_me/` at Step 7 with the scope:
- probes: `probe_account_identity.py`, `probe_engine_start.py`, `probe_step8_checks.py`
- logs: `engine-checkpoint.log`, `probe_engine.log`, `tsc.txt`

## Inventory (Step 2)

### tests/tmp/test_engine_row_identity.py
- **Drives:** `engine/server/api/handlers/similar.py` (projection, limit cap) and `engine/server/api/recommendations/mixer.py` (batch cap), over HTTP to a real Engine.
- **Tests:**
  - `test_every_row_carries_the_channel_and_account_the_dataset_holds[home|random|upnext|search]`
  - `test_home_and_random_return_more_than_the_default_page_when_asked_for_twice_it[/recommendations|?random=1]`
- **Depends on:** the `engine` and `dataset` fixtures and `identity_of` (conftest); `ROOT` (conftest); `_default_limit`, which loads `server_config.BATCH_SIZE`.

### tests/tmp/test_block_routes.py
- **Drives:** `client/backend/server.py` block routes and `client/backend/lib/blocks.py`, over HTTP to a real Client wired to a real Engine.
- **Tests:**
  - `test_a_video_s_channel_and_account_are_listed_after_blocking_and_gone_after_removal`
  - `test_a_profile_holding_1000_blocks_is_refused_a_further_one_and_keeps_1000`
- **Depends on:** the `client_backend` (Engine-wired) and `dataset` fixtures; the `RESOLVABLE` SQL fragment.

### tests/tmp/test_block_filtering.py
- **Drives:** the `client/backend/server.py` read proxy (`_block_filter`, `_filter_payload`) and `blocks.filter_blocked`, over HTTP.
- **Tests:**
  - `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page[/recommendations|/videos/similar|search]`
  - `test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it[/recommendations|/videos/similar]`
- **Depends on:** the `client_backend` (Engine-wired) fixture.

### tests/tmp/test_block_frontend.py
- **Drives:** `client/frontend/src/data/blocks.ts`, `videos.ts`, `search.ts` and `profile.ts`, bundled with esbuild and run in node against the real Client and Engine.
- **Tests:**
  - `test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches`
  - `test_a_key_the_server_refuses_surfaces_as_profile_key_rejected_on_upnext_and_search`
- **Depends on:** the `client_backend` (Engine-wired) fixture; `RUNNER`, `_bundle` and `_run`.

## Classification (Step 3)

`tests/active` holds `test_db.py`, `test_profiles.py` and `test_frontend_profile.py`. None asserts row identity, the feed limit, blocks, or read filtering. So every test in scope is **DURABLE**, and none is REDUNDANT, REPLACES or COMBINE.

- `test_every_row_carries_the_channel_and_account_the_dataset_holds` — **DURABLE.** No active test reads the Engine's projection. New subject file: `tests/active/test_similar.py`.
- `test_home_and_random_return_more_than_the_default_page_when_asked_for_twice_it` — **DURABLE.** No active test covers the handler or mixer cap. → `tests/active/test_similar.py`.
- `test_a_video_s_channel_and_account_are_listed_after_blocking_and_gone_after_removal` — **DURABLE.** No active test covers the block routes. New subject file: `tests/active/test_blocks.py`.
- `test_a_profile_holding_1000_blocks_is_refused_a_further_one_and_keeps_1000` — **DURABLE**, same reason. → `tests/active/test_blocks.py`.
- `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page` — **DURABLE.** No active test covers read filtering. → `tests/active/test_blocks.py`.
- `test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it` — **DURABLE**, same reason. → `tests/active/test_blocks.py`.
- `test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches` — **DURABLE.** `test_frontend_profile.py` covers `profile.ts` and `user-profile.ts` only. New subject file: `tests/active/test_frontend_blocks.py`.
- `test_a_key_the_server_refuses_surfaces_as_profile_key_rejected_on_upnext_and_search` — **DURABLE**, same reason. → `tests/active/test_frontend_blocks.py`.

### Fixture move

`tests/active/conftest.py`'s `client_backend` points at a closed Engine, and `test_profiles.py` and `test_frontend_profile.py` rely on that. The harvest adds, and changes nothing existing:
- a session `engine` fixture (the real Engine subprocess from the pixi env);
- a session `dataset` fixture (read-only `whitelist.db`);
- `identity_of`;
- an `engine_client` fixture: the Client wired to that Engine with a shared bridge token.

The moved tests take `engine_client` where they took `client_backend`.

## Approval (Step 4)

The operator approved the plan as written ("Approve as planned").

## Applied (Step 5)

- **`tests/active/test_similar.py`** (NEW): the two Engine tests. The docstring states the rule, and the clause ids are removed.
- **`tests/active/test_blocks.py`** (NEW)
  - The four Client tests from `test_block_routes.py` and `test_block_filtering.py`, under one module docstring stating the rules.
  - The two `_block` helpers became `_post_block` (returns the status) and `_block` (asserts 201).
- **`tests/active/test_frontend_blocks.py`** (NEW): the two frontend tests. The docstring states the rules.
- **`tests/active/conftest.py`**
  - Adds `engine`, `engine_client`, `dataset` and `identity_of`, and raises `ClientBackend.request`'s timeout from 10 s to 120 s, because a search can take 3 s.
  - `client_backend` is unchanged.
- **`.un/skills/devsecops/config.json`**: entries for the three new files, as below.
  - `test_similar.py` also claims `engine/server/api/server_config.py`, because it reads `BATCH_SIZE` from there (an `--audit-map` MISSING advisory).
- **`--audit-map`**: exit 0.
  - Remaining advisories: `test_db.py` MISSING `data/time.py`, which predates this harvest.
  - `test_similar.py` UNRESOLVABLE `conftest.py`: a shared helper, intentionally unclaimed.
  - BARREN is reported on the files that `sys.path`-import `lib.*`, including the pre-existing `test_profiles.py`.

### Map entries (Step 5.c)

- `test_similar.py` → `engine/server/api/handlers/similar.py`, `engine/server/api/recommendations/mixer.py`
- `test_blocks.py` → `client/backend/server.py`, `client/backend/lib/blocks.py`, `client/backend/lib/users_store.py`, `client/backend/lib/engine_api_client.py`
- `test_frontend_blocks.py` → `client/frontend/src/data/blocks.ts`, `client/frontend/src/data/videos.ts`, `client/frontend/src/data/search.ts`, `client/frontend/src/data/profile.ts`, `client/backend/server.py`

## Mutations (Step 6)

Each mutation was applied to a backed-up production file, the named test was run alone, and the file was restored and diffed. Each test was green again afterwards.

- `test_every_row_carries_the_channel_and_account_the_dataset_holds` — `"account_url"` removed from `STABLE_VIDEO_FIELDS`. It failed on all four routes at the key-presence assertion.
  - **Mishap:** the backup was taken in the same parallel tool batch as the edit, so it captured the mutated file. The line was restored by hand, and `git diff` confirmed the intended projection before the green re-run. Every later backup was taken in its own, earlier step.
- `test_home_and_random_return_more_than_the_default_page_when_asked_for_twice_it` — the mixer cap reverted to `configured_batch`. `[/recommendations]` failed at `len > default` (48). `[random]` still passed; random does not go through the mixer.
- `test_a_video_s_channel_and_account_are_listed_after_blocking_and_gone_after_removal` — `block_target` stored `channel_url` as the account. It failed at `account_target in listed`.
- `test_a_profile_holding_1000_blocks_is_refused_a_further_one_and_keeps_1000` — `MAX_BLOCKS` = 1001. It failed at `201 == 400`.
- `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page` — `filter_blocked` ignored account blocks. It failed at "blocked account absent" on all three surfaces.
- `test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it` — `FEED_OVERFETCH_FACTOR` = 1. It failed at `5 == 8` on both routes.
- `test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches` — `fetchSearchResults` always took the cached keyless path. It failed at the search omission (line 124).
- `test_a_key_the_server_refuses_surfaces_as_profile_key_rejected_on_upnext_and_search` — `fetchSimilarVideosPayload` no longer mapped 401 to `ProfileKeyRejectedError`. It failed at line 137 with `rejected: False`.

No `.bak` remains in the production tree. The copies are in `delete_me/`.

## Disposed (Step 7)

Everything from `tests/tmp` is in `delete_me/plan07-tmp/`:
- the four checkpoints and their `conftest.py`
- the probes and `mutate.sh`
- the logs, `tsc.txt` and `__pycache__`
- the concurrent-start probe and its logs

`tests/tmp` is empty.

## Suite (Step 8)

- **The snapshot was restored, but its comparison was spent.** The first `--compare` after restoring showed the 6 `test_similar` cases as appeared, and all 9 `test_blocks`/`test_frontend_blocks` cases as new red, every one `Engine exited during startup`.
  - **Cause:** each lane starts its own Engine, and every Engine start rewrites `random-cache.db`. Engines starting at once exit with `sqlite3.OperationalError: database is locked`. A probe starting three Engines at once saw one exit.
  - **Fix:** the `engine` fixture retries a start that exits, up to 5 times with a growing delay.
  - Three concurrent pytest sessions, one per new file, then all passed.
- **Delta, by counting,** because the restored record was consumed by the failing run:
  - pre-harvest 12 tests;
  - 15 added (6 in `test_similar.py`, 7 in `test_blocks.py`, 2 in `test_frontend_blocks.py`);
  - 0 retired;
  - final 27.
- **Final state:**
  - The second `--compare` shows only the 9 "no longer red" left from the fixture failure.
  - A bare run: 27 passed, green.
  - `--audit-map` exits 0.
