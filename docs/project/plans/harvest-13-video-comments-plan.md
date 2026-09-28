# Harvest: issue 13 (video comments)

Build: `docs/project/plans/19-13-video-comments.md`, merged to main as `f3b6454`.

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

- `tests/tmp/test_13_video_comments_phase1.py`
- `tests/tmp/test_13_video_comments_phase2.py`
- `tests/tmp/test_13_video_comments_phase3.py`
- `tests/tmp/test_13_video_comments_phase4.py`

Also left in `tests/tmp` by the same merge, not `test_*.py` and so outside the scope proper, disposed with it: `probe_13_phase1_impl.py`, `probe_13_phase1_observe.py`, `probe_13_phase2.py`, `probe_13_phase2_impl.py`, `probe_13_phase3.py`, `probe_13_phase4.py`, `probe_13_refactor.py`, `probe_harness.py` (each empty or a one-line stub).

All four files collect and pass on main: 16 passed.

## Inventory

Every file drives `client/frontend/src/pages/video-page/index.ts`, bundled with esbuild and run in node under a stub-DOM `RUNNER`, and reads `client/frontend/video-page.html` for the comments elements' initial text (phases 2-4). Each defines its own `bundle` module fixture, `_page`, and `_elements`-style tree helpers.

### tests/tmp/test_13_video_comments_phase1.py

Runner extends the active taxonomy runner with the `COMMENTS` fetch map, `startUrls`, comment-root snapshots, and the markup detectors (`markupIds`, `opaqueIds`).

- `test_a_body_with_category_language_and_tags_shows_both_values_and_one_text_chip_per_tag`
- `test_a_body_with_empty_category_language_and_tags_hides_both_items_and_reads_no_tags`
- `test_an_empty_language_alone_hides_only_the_language_item`
- `test_the_first_page_is_requested_at_start_and_renders_one_text_thread_per_live_thread_under_the_total_heading`
- `test_hostile_names_and_federated_html_reach_the_comments_only_as_text`

### tests/tmp/test_13_video_comments_phase2.py

Runner adds seeded initial text, `HOST` env, `console.warn` capture, unhandled-rejection capture, `originalHref`.

- `test_an_empty_first_batch_on_a_video_not_reporting_comments_disabled_reads_no_comments_yet_under_comments_0` (3 params)
- `test_an_empty_first_batch_on_a_video_reporting_comments_disabled_shows_the_unavailable_state_and_keeps_the_taxonomy` (2 params)
- `test_a_failed_first_batch_shows_the_unavailable_state_with_the_original_href_keeps_the_taxonomy_and_warns_once` (3 params)

### tests/tmp/test_13_video_comments_phase3.py

Runner adds listener recording, `disabled`, and `STEPS` click driving with per-step snapshots.

- `test_a_double_click_on_load_more_requests_start_20_once_then_the_list_holds_all_25_and_the_button_hides`
- `test_load_more_stays_shown_below_the_total_and_hides_once_a_full_last_batch_reaches_it`

### tests/tmp/test_13_video_comments_phase4.py

Runner adds `startRequests` and per-snapshot shown-control labels.

- `test_a_double_clicked_reply_toggle_fetches_the_tree_once_shows_pre_order_depth_rows_and_hides_and_reshows_them_without_a_request`

## Classification

Subject file: `tests/active/test_frontend_video_page.py` (exists; maps `index.ts`, `video.css`, `video-page.html`). It holds only the three taxonomy tests.

| Test | Verdict | Reason |
|---|---|---|
| phase1 `test_a_body_with_category_language_and_tags_...` | REDUNDANT | Identical assertions already in the subject file |
| phase1 `test_a_body_with_empty_category_language_and_tags_...` | REDUNDANT | Identical assertions already in the subject file |
| phase1 `test_an_empty_language_alone_hides_only_the_language_item` | REDUNDANT | Identical assertions already in the subject file |
| phase1 `test_the_first_page_is_requested_at_start_...` | DURABLE | First-page request, heading from total, thread fields, handle host; nothing in active covers comments |
| phase1 `test_hostile_names_and_federated_html_reach_the_comments_only_as_text` | DURABLE | XSS gate on comment names and bodies; uncovered |
| phase2 `..._not_reporting_comments_disabled_reads_no_comments_yet...` | DURABLE | Empty-batch state and the policy-3 vs disabled-2 boundary; uncovered |
| phase2 `..._reporting_comments_disabled_shows_the_unavailable_state...` | DURABLE | Disabled state, link, heading without count; uncovered |
| phase2 `test_a_failed_first_batch_...` | DURABLE | Failure state, host-specific link, single warn; uncovered |
| phase3 `test_a_double_click_on_load_more_...` | DURABLE | Load-more in-flight guard and append; uncovered |
| phase3 `test_load_more_stays_shown_below_the_total_...` | DURABLE | Hide rule held to total, not batch size; uncovered |
| phase4 `test_a_double_clicked_reply_toggle_...` | DURABLE | Reply fetch-once, pre-order depth rows, deleted handling, hide/reshow without request; uncovered |

Counts: DURABLE 8, REDUNDANT 3, REPLACES 0, COMBINE 0, SPENT 0.

## Placement plan

- All 8 DURABLE tests move into `tests/active/test_frontend_video_page.py`.
- The four phase runners are successive supersets of one harness. The subject file gets ONE runner that is their union (seeded initial text, `HOST`, `COMMENTS` map, markup detectors, listeners/`disabled`/`STEPS`, warn and rejection capture, `startUrls`/`startRequests`, shown controls, taxonomy and `originalHref` reports) and one `_page`, replacing the taxonomy-only runner the three existing tests use. The existing three tests keep their assertions unchanged.
- No test retired, no file created, no `test_groups` change: the subject entry already claims `index.ts`, `video.css` and `video-page.html`.

Approved by the operator with the merged-runner option.

## Applied

- `tests/active/test_frontend_video_page.py` rewritten: one merged runner and one `_page` (keyword `initially_hidden`, `comments`, `steps`, `host`), the 3 taxonomy tests with their assertions unchanged, and the 8 DURABLE tests. Build clause tags (`# C1`, `# C2`) and phase and plan references dropped from comments and the docstring. Test-specific controls that lived in each phase's `_page` moved into the tests (`_state_page` for the three state tests; the `comments-more` seed check into the first load-more test). 16 passed.
- `--audit-map` exit 0; nothing flagged for `test_frontend_video_page.py` beyond the path-resolution advisory it already carried.

## Mutations

All against `client/frontend/src/pages/video-page/index.ts`, one at a time via `delete_me/h13_mutate.sh`: backup, mutate, run the one test, restore, `diff` clean, re-run green. Every restore was exact and every re-run passed.

| Test | Mutation | Assertion felled |
|---|---|---|
| first page requested at start | handle built without `account.host` | `comment-handle` == `@alice@peer.example`, `@bob@tube.other.example` |
| hostile names and federated HTML | author set via `innerHTML` | `comment-author` == hostile name as text (read `''`) |
| empty batch, not disabled | disabled check `>= 2` instead of `=== 2` | `[commentsPolicy-3]` status == "No comments yet." |
| empty batch, disabled | `commentsEnabled === false` clause removed | `[commentsEnabled-false]` status starts with unavailable text |
| failed first batch | first-batch `console.warn` removed | all 3 params: one `[comments]` warn (read 0) |
| double click on load more | in-flight `disabled = true` removed | `start=20` requested once (read 2) |
| load more hides at total | hide rule changed to short-batch | last snapshot `comments-more` hidden |
| reply toggle | flatten changed to post-order | `_rows(...) == ROWS` |

None reclassified.

## Disposal

Moved to `delete_me/` (no name collisions): `test_13_video_comments_phase1.py` .. `phase4.py`, `probe_13_phase1_impl.py`, `probe_13_phase1_observe.py`, `probe_13_phase2.py`, `probe_13_phase2_impl.py`, `probe_13_phase3.py`, `probe_13_phase4.py`, `probe_13_refactor.py`, `probe_harness.py`. Also there from Step 6: `h13_mutate.sh` and `index.ts.bak-h13-M1` .. `M8`. `tests/tmp` now holds only `__pycache__`.

## Suite

Snapshot restored, then `validate_tests.py --compare`: 2 of 25 groups selected (`test_frontend_video_page.py` changed; `test_search_fusion.py` has no map entry, a pre-existing gap), 26 passed, 23 groups unchanged and carried from the record. Delta: 13 appeared (8 functions, 13 with parameters), 0 gone, 0 new red, 0 no-longer-red. Exit 0, banked.
