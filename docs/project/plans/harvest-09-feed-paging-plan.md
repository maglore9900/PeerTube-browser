# Harvest — plan 09 feed paging

## Resolved paths (Step 1)

- `project_dir`: `/home/enduser/code/PeerTube-browser`
- `active`: `tests/active`
- `working`: `tests/tmp`
- `plans`: `docs/project/plans`
- `delete_me`: `delete_me`
- `archive`: `tests/archive`
- `record`: `tests/last_test_validation.json`; snapshot `tests/last_test_validation.json.preharvest` taken before any harvest run.
- Bootstrap gate: `defaulted` empty, `conflicts` empty.

## Scope

The four checkpoints of `docs/project/plans/09-feed-paging.md`:

- `tests/tmp/test_feed_exclude_home.py`
- `tests/tmp/test_feed_exclude_upnext.py`
- `tests/tmp/test_feed_exclude_gateway.py`
- `tests/tmp/test_frontend_feed_pager.py`

The build's scratch in the same tree goes to `delete_me/` at Step 7 with them: `conftest.py` (a copy of the active one), `probe_*.py` (5), `tsc_after.txt`.

## Inventory (Step 2)

### tests/tmp/test_feed_exclude_home.py
- Drives: Engine `POST /recommendations` home — `engine/server/api/recommendations/mixer.py`, `handlers/similar.py`, `request_context.py`, `builder.py`, `server.py`.
- Tests: `test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[linux|cooking|music]`.
- Depends on: `LIKE_QUERIES`, `PLAIN_FLOOR = 45`, helpers `_likes`, `_home`, `_keys`; fixture `engine`.

### tests/tmp/test_feed_exclude_upnext.py
- Drives: Engine up-next and the exclude cap — `handlers/similar.py`, `server_config.py`.
- Tests: `test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos[linux|cooking]`, `test_a_feed_request_with_more_than_500_exclude_entries_is_refused_and_500_is_served[/recommendations|/videos/similar]`.
- Depends on: `SEED_QUERIES`, `PAGE = 8`, `EXCLUDE_CAP = 500`, helpers `_upnext_path`, `_keys`, `_real_exclude`; fixtures `engine`, `dataset`.

### tests/tmp/test_feed_exclude_gateway.py
- Drives: the Client read gateway — `client/backend/server.py` (`PROXY_ALLOWED_BODY_KEYS`, `_handle_engine_read_proxy_post`), and the Engine body limit `engine/server/api/server_config.py`.
- Tests: `test_a_keyed_request_s_500_entry_exclude_reaches_the_engine_and_none_of_it_is_returned`, `test_the_client_refuses_501_exclude_entries_and_passes_500_on_to_the_engine`.
- Depends on: `EXCLUDE_CAP`, helpers `_mint`, `_search`, `_home`, `_keys`, `_longest_host_entries`; fixtures `unpublished_client`, `client_backend`, `dataset`.

### tests/tmp/test_frontend_feed_pager.py
- Drives: `client/frontend/src/data/videos.ts` (`createFeedPager`, `fetchSimilarVideosPayload`) through the Client and Engine.
- Tests: `test_the_pager_s_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch`.
- Depends on: `RUNNER`, `PAGE`, `MAX_BATCHES`, `_run`, `_seed`; fixture `engine_client`.

All four collect (6 test functions, 10 node ids).

## Classification (Step 3)

- `test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page` — **DURABLE** → `tests/active/test_similar.py`. No active test sends `exclude`; `test_similar.py` is the subject file for `handlers/similar.py` and `mixer.py`.
- `test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos` — **DURABLE** → `tests/active/test_similar.py`. Same reason.
- `test_a_feed_request_with_more_than_500_exclude_entries_is_refused_and_500_is_served` — **DURABLE** → `tests/active/test_similar.py`. No active test covers the exclude cap.
- `test_a_keyed_request_s_500_entry_exclude_reaches_the_engine_and_none_of_it_is_returned` — **DURABLE** → NEW `tests/active/test_server.py`, the subject for `client/backend/server.py`'s read gateway. `test_blocks.py`, `test_dislikes.py` and `test_profiles.py` are named for `lib/*` modules, and none asserts the gateway's body allowlist or its forwarding.
- `test_the_client_refuses_501_exclude_entries_and_passes_500_on_to_the_engine` — **DURABLE** → NEW `tests/active/test_server.py`. Same reason.
- `test_the_pager_s_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch` — **DURABLE** → NEW `tests/active/test_frontend_videos.py`, the subject for `client/frontend/src/data/videos.ts`. `test_frontend_blocks.py` bundles `videos.ts` but asserts blocks.

REDUNDANT: none. SPENT: none. REPLACES / COMBINE: none.

## Approval (Step 4)

Operator: "approve" (the verdicts above, subject file named `test_server.py`).

## Applied (Step 5)

- `tests/active/test_similar.py`: the three Engine tests, with their constants (`LIKE_QUERIES`, `PLAIN_FLOOR`, `UPNEXT_SEED_QUERIES`, `UPNEXT_PAGE`, `EXCLUDE_CAP`) and helpers (`_likes`, `_home`, `_upnext_path`). The two source files' `_keys` helpers differ (a set and a list), so they are `_key_set` and `_key_list` here. The module docstring gained three bullets stating the rules.
- NEW `tests/active/test_server.py`: a copy of `test_feed_exclude_gateway.py`, whose docstring already states the rule.
- NEW `tests/active/test_frontend_videos.py`: a copy of `test_frontend_feed_pager.py`.
- The `# C1`/`# C2` markers are kept, as in `tests/active/test_db.py`.
- Retired: none.
- `--audit-map`: exit 0. Advisory findings: MISSING on `test_db.py` and `test_random_videos.py` (groups this harvest did not touch); BARREN on the new `test_server.py` and `test_frontend_videos.py`, like every existing HTTP-driven group.

## Mutations (Step 6)

- `test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page` — rule: a home page holds none of the excluded videos. Mutation: `mixer.py`'s per-layer exclusion filter disabled (`if False:`). Felled `test_similar.py:121` (the disjointness assertion) on all three like-sets. Restored (`diff` identical), 3 passed.
- `test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos` — rule: up-next removes excluded rows before the page is cut. Mutation: `similar.py`'s filter in `_handle_seed_with_embedding` disabled. Felled `test_similar.py:154` (page == ranked pool minus excluded) on both seeds. Restored, 2 passed.
- `test_a_feed_request_with_more_than_500_exclude_entries_is_refused_and_500_is_served` — rule: the Engine refuses more than 500. Mutation: `DEFAULT_CLIENT_EXCLUDE_MAX = 501`. Felled `test_similar.py:168` with `(200, None) != (400, …)` on both routes. Restored, 2 passed.
- `test_a_keyed_request_s_500_entry_exclude_reaches_the_engine_and_none_of_it_is_returned` — rule: the keyed rewrite keeps `exclude`. Mutation: `sanitized_body.pop("exclude", None)` in the profile branch of `_handle_engine_read_proxy_post`. Felled `test_server.py:87` (the disjointness assertion).
  - **The first restore was not exact.** The `.bak` copy and the mutating Edit were issued in the same parallel batch, so the copy captured the mutated file. `diff` then reported identical and the test stayed red after the "restore". Probe `probe_keyed_leak.py` showed exclusion missing on the keyed path (22-25 of 48 previous rows came back, whatever the top-up size), and `Grep` found the mutation line still at `server.py:495`. It was removed by hand, `git diff` confirmed no mutation remains, and the test passed (1 passed). The three Engine mutations took their copies in separate calls first and were unaffected. M5 and M6 took theirs in separate calls, and each restore was checked by `Grep` for the mutated line as well as by `diff`.
- `test_the_client_refuses_501_exclude_entries_and_passes_500_on_to_the_engine` — rule: the Client refuses more than 500. Mutation: `MAX_FEED_EXCLUDE = 501`. Felled `test_server.py:98` (`(502, …) != (400, "Invalid exclude payload")`). Restored (`diff` identical, `Grep` shows 500), 1 passed.
- `test_the_pager_s_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch` — rule: the pager excludes the rows it has shown. Mutation: `fetchBatch([])` in `createFeedPager`. Felled `test_frontend_videos.py:92` ("the second batch is empty"). Restored (`diff` identical, `Grep` shows `shown.slice(-MAX_FEED_EXCLUDE)`), 1 passed.
- No `.bak` remains under `client/` or `engine/server/`. The copies are in `delete_me/` as `mixer.py.bak`, `similar.py.bak`, `server_config.py.bak`, `server.py.feed-paging-m4.bak`, `server.py.feed-paging-m5.bak`, `videos.ts.feed-paging-m6.bak`.

## Disposed (Step 7)

Moved from `tests/tmp/` to `delete_me/plan09-tmp/`: the four checkpoints, `conftest.py`, `probe_closed_engine.py`, `probe_forwarded_body.py`, `probe_home_repeat.py`, `probe_identity_sizes.py`, `probe_keyed_leak.py`, `probe_upnext_repeat.py`, `tsc_after.txt`. `tests/tmp/` holds only `__pycache__`.

## Suite (Step 8)

Snapshot restored, then `validate_tests.py --compare`. 3 of 12 groups selected (`test_frontend_videos.py` and `test_server.py` new, `test_similar.py` changed), 16 passed; 9 groups unchanged against the pre-harvest record. "moved against the previous record": 10 `appeared`, one per harvested node id, and nothing gone, no new red. Suite total 68 (58 before the harvest plus 10).

## Map changes (Step 5.c, applied)

- `test_similar.py`: add `engine/server/api/request_context.py`, `engine/server/api/recommendations/builder.py`.
- NEW `test_server.py`: `client/backend/server.py`, `engine/server/api/server_config.py`, `engine/server/api/handlers/similar.py`.
- NEW `test_frontend_videos.py`: `client/frontend/src/data/videos.ts`, `client/backend/server.py`, `engine/server/api/handlers/similar.py`.
