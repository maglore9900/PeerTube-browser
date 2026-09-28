# Harvest: issue 12 (similars on scroll)

Build: `docs/project/plans/19-12-similars-on-scroll.md`, merged to main as `4322724`. After the merge, the phase 3 checkpoint's runner was fixed to drain stdout before exit (its 125,932-byte report was cut at 65,536), and main's `test_groups` gained the `test_frontend_upnext_pager.py` entry that `config.json`, being untracked, did not carry over.

## Resolved paths

- project_dir: `/home/enduser/code/PeerTube-browser`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json` (snapshot `tests/last_test_validation.json.preharvest` taken before any run)

## Scope

Every `test_*.py` under `tests/tmp`:

- `tests/tmp/test_12_similars_on_scroll_phase1.py`
- `tests/tmp/test_12_similars_on_scroll_phase2.py`
- `tests/tmp/test_12_similars_on_scroll_phase3.py`
- `tests/tmp/test_probe_12_phase3_runner.py`

Also in `tests/tmp` from the same build, outside the `test_*.py` scope and disposed with it: `draft_stub_pager.py`, `draft_upnext_pager.py`, `probe_12_claimed.py`, `probe_12_durable.py`, `probe_12_nolimit.py`, `probe_12_pager.py`, `probe_12_pager_lengths.py`, `probe_12_phase2_cards.py`, `probe_12_phase2_request.py`, `probe_12_phase3_drained_assert.py`, `probe_12_phase3_exclude.py`, `probe_12_phase3_fake.py`, `probe_12_phase3_pipe.py`, `probe_pager_exclude_body.py`, `probe_pager_sizes.py`, `probe_upnext_durable.py`.

All four files collect and pass on main (23 passed across them and the three active frontend files, after the merge fixes).

## Inventory

### tests/tmp/test_12_similars_on_scroll_phase1.py

Drives `client/frontend/src/data/videos.ts` (`createFeedPager`, `fetchSimilarVideosPayload`) against the real Client and Engine (`engine_client` from `tests/active/conftest.py`), and reads `validate_tests.py`'s `claimed` map.

- `test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch`
- `test_the_durable_pager_test_passes_a_pager_that_holds_the_contract_and_fails_one_that_repeats_keeps_asking_or_never_runs_dry`
- `test_the_durable_pager_group_is_fingerprinted_over_videos_ts_the_client_server_and_both_engine_similars_files`

### tests/tmp/test_12_similars_on_scroll_phase2.py

Drives `client/frontend/src/pages/video-page/index.ts` in node; runner identical to the one in `tests/active/test_frontend_video_page_similars.py`.

- `test_the_first_batch_is_one_recommendations_request_for_48_rows_of_which_the_first_8_are_shown`

### tests/tmp/test_12_similars_on_scroll_phase3.py

Drives `index.ts` in node; runner is phase 2's plus per-element `innerHTML` write counts and `insertAdjacentHTML` records, id-tagged elements, a queue of `/recommendations` answers, and six hand-fired intersections on `#similar-sentinel`.

- `test_each_sentinel_intersection_appends_the_next_8_rows_and_the_one_after_all_48_asks_for_a_batch_excluding_them`

### tests/tmp/test_probe_12_phase3_runner.py

A docstring only ("Spent probe ... delete this file"). No tests.

## Classification

| Test | Verdict | Reason |
|---|---|---|
| phase1 `test_the_pager_s_48_row_batches_...` | COMBINE with `tests/active/test_frontend_upnext_pager.py::test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch` | The active test asserts everything this one does except the limit-20 second run (batch size follows the `limit` sent, not the Engine's default of 48); lift that run and `_run`'s `page`/`max_batches` parameters in |
| phase1 `test_the_durable_pager_test_passes_...` | SPENT | Meta-test proving the phase's durable test discriminates on canned batches; scaffolding for a landed phase |
| phase1 `test_the_durable_pager_group_is_fingerprinted_...` | SPENT | Checks the `test_groups` entry, not production behaviour; the entry now exists and `--audit-map` owns that check |
| phase2 `test_the_first_batch_is_one_recommendations_request_...` | REDUNDANT | Byte-identical to the test already in `tests/active/test_frontend_video_page_similars.py` |
| phase3 `test_each_sentinel_intersection_...` | DURABLE → `tests/active/test_frontend_video_page_similars.py` | Scroll reveal in chunks of 8, append-not-rewrite, and the next batch's `exclude`; nothing in active covers it |
| `test_probe_12_phase3_runner.py` | SPENT | No tests |

Counts: DURABLE 1, COMBINE 1, REDUNDANT 1, SPENT 2 (+1 empty file), REPLACES 0.

## Placement plan

- `tests/active/test_frontend_upnext_pager.py`: `_run` gains `page` and `max_batches` parameters; the existing test gains the limit-20 two-batch run and its assertion, and its docstring the clause. The active test survives the merge, so nothing goes to `tests/archive/`; the emptied phase 1 test leaves with its file to `delete_me/`.
- `tests/active/test_frontend_video_page_similars.py`: the runner becomes phase 3's (a superset of the current one; with no intersections it is today's run), taking a list of `/recommendations` answers, and draining stdout before exit. `_page` takes the answers and the intersection count. The existing first-batch test keeps its assertions; the phase 3 test is added.
- `test_groups`: `test_frontend_video_page_similars.py` has no entry today, so changes to the page never reselect it. Add `client/frontend/src/pages/video-page/index.ts` and `client/frontend/src/data/videos.ts` (the page's pager and the `exclude` body are built there).
- No new test file. Nothing in `active` retired.

Approved by the operator as planned.

## Applied

- `tests/active/test_frontend_upnext_pager.py`: `_run(..., page=PAGE, max_batches=MAX_BATCHES)`; the test keeps its seed and adds the limit-20 two-batch run asserting `[20, 20]`; docstring gains the clause. 1 passed (Engine-backed).
- `tests/active/test_frontend_video_page_similars.py`: phase 3's runner with the stdout drain; `_page(bundle, answers, intersections=0)`; the first-batch test reads `snapshots[0]["similar"]` with its assertions unchanged; the scroll test added with build clause tags dropped. 2 passed.
- `test_groups`: added `test_frontend_video_page_similars.py` → `client/frontend/src/pages/video-page/index.ts`, `client/frontend/src/data/videos.ts`. `--audit-map` exit 0.

## Mutations

Via `delete_me/h12_mutate.sh`: backup, mutate, run the one test, restore, `diff` clean, re-run green. Both restores exact, both re-runs passed.

| Test | Mutation | Assertion felled |
|---|---|---|
| pager (COMBINE) | `buildSimilarUrl` in `videos.ts` stops sending `limit` | the lifted `[len(rows)] == [20, 20]` (read `[48, 48]`) |
| sentinel intersection (DURABLE) | `index.ts` reveals `2 * SIMILAR_CHUNK` per intersection | first append's keys == rows 8-15 |

None reclassified.

## Disposal

Moved to `delete_me/` (no name collisions): the 4 scoped files and the 16 drafts and probes listed under Scope. Also there from Step 6: `h12_mutate.sh`, `videos.ts.bak-h12-M1`, `index.ts.bak-h12-M2`. `tests/tmp` now holds only `__pycache__`.

## Suite

Snapshot restored, then `validate_tests.py --compare`: 3 of 27 groups selected (the two changed subjects, and `test_search_fusion.py`, which still has no map entry), 13 passed, 24 groups unchanged and carried from the record. Delta: 1 appeared (the DURABLE scroll test; the COMBINE added no test id), 0 gone, 0 new red, 0 no-longer-red. Exit 0, banked.
