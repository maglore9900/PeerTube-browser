# Harvest — build 10, video metadata completeness

## Resolved paths (from `--show-config`, bootstrap gate clear: `defaulted` is empty, `conflicts` empty)

- project_dir: /home/enduser/code/PeerTube-browser/.worktrees/10
- active: tests/active
- working: tests/tmp
- plans: docs/project/plans
- delete_me: delete_me
- archive: tests/archive
- record: tests/last_test_validation.json
- Snapshot: tests/last_test_validation.json.preharvest taken at Step 1, before any run.

## Scope (the tests build 10 wrote)

- tests/tmp/test_10_video_metadata_completeness_phase1.py
- tests/tmp/test_10_video_metadata_completeness_phase2.py
- tests/tmp/test_10_video_metadata_completeness_phase3.py
- tests/tmp/test_10_video_metadata_completeness_phase4.py

The `probe_*.py` files in tests/tmp are not in scope and are left in place.

## Inventory

### tests/tmp/test_10_video_metadata_completeness_phase1.py

Drives `engine/server/db/jobs/whitelist_migrations.py` (`migrate_whitelist_schema`) and the compiled crawler `engine/crawler/dist/videos-worker.js` + `dist/db.js` (sources `src/videos-worker.ts`, `src/db.ts`) under node.
Fixtures/constants: `_load_job`, `PRE_CHANGE_VIDEOS_SQL`, `TRIGGERS_SQL`, `EXPECTED_TRIGGERS`, `ROWS_SQL`, `MATCH_SQL`, `LANGUAGE_LINE`, `NODE_SCRIPT`, `BUILD_PAIRS`, `_table_info`, `_column_names`, `_matches`, `_git`, `_dist_is_stale`, `_require_built_crawler`, `_instance`, `_crawl`, `_stop`. `sync-whitelist.py` schema helpers build the fixture DB only.

- `test_migration_adds_language_column`
- `test_crawl_stores_each_videos_language`
- `test_crawl_adds_language_to_existing_db`

### tests/tmp/test_10_video_metadata_completeness_phase2.py

Drives `engine/server/api/handlers/video.py` (`handle_video_request`), whose labels come from `engine/server/data/peertube_labels.py`.
Fixtures/constants: `HOST`, `PARAMS`, `_load_job`, `server` fixture (sync-whitelist schema, seeded instance/channel/video).

- `test_response_labels` (5 params)
- `test_refresh_stores_raw_codes`

### tests/tmp/test_10_video_metadata_completeness_phase3.py

Drives `engine/server/api/handlers/video.py` (`handle_video_request`, the real `fetch_instance_json` under a replaced `urlopen`).
Fixtures/constants: `HOST`, `PARAMS`, `OLD_CHECKED_AT`, `VIDEO_PATH`, `VIDEO_URL`, `CHANNEL_PATH`, `OLD_THUMBNAIL`, `NEW_THUMBNAIL`, `SOURCE`, `ORIGINAL_KEYS`, `STORED_ANSWER`, `_load_job`, `server`, `responses`, `_FakeResponse`, `_serve`, `_video`, `_instance_errors`, `_snapshot`, `_only_body`, `_answered`.

- `test_fetch_failure_leaves_db_untouched` (5 params)
- `test_success_refreshes_row_and_response`
- `test_partial_payload_keeps_tags_and_category` (2 params)
- `test_failed_channel_fetch_keeps_stored_followers`
- `test_empty_tag_list_propagates`
- `test_object_body_counts_as_success` (2 params)
- `test_second_request_reflects_source_change`

### tests/tmp/test_10_video_metadata_completeness_phase4.py

Drives `client/frontend/src/pages/video-page/index.ts`, bundled by esbuild and run in node.
Fixtures/constants: `FRONTEND`, `ESBUILD`, `BASE`, `TITLE`, `ITEMS`, `RUNNER`, `bundle` (module fixture), `_page`.

- `test_a_body_with_category_language_and_tags_shows_both_values_and_one_text_chip_per_tag`
- `test_a_body_with_empty_category_language_and_tags_hides_both_items_and_reads_no_tags`
- `test_an_empty_language_alone_hides_only_the_language_item`

All four files are well-formed Python whose imports resolve against the current tree; none was marked uncollectable.

## Classification

No `active` test references `whitelist_migrations`, `handlers.video`, `peertube_labels`, `video-page`, or `language` (grep), so no verdict below can be `REDUNDANT` against `active`.

### test_migration_adds_language_column — DURABLE
No active test drives `whitelist_migrations.py`. Subject file to CREATE: `tests/active/test_whitelist_migrations.py`.

### test_crawl_stores_each_videos_language — DURABLE
`test_videos_worker.py::test_crawl_writes_each_hosts_own_channel_name` asserts channel name/url only, not language. Destination: `tests/active/test_videos_worker.py` (exists).

### test_crawl_adds_language_to_existing_db — DURABLE
Nothing in active asserts crawl.db's migration of a pre-`language` table. Destination: `tests/active/test_videos_worker.py`.

### test_response_labels — DURABLE
No active test drives `handlers/video.py`. Subject file to CREATE: `tests/active/test_video.py`.

### test_refresh_stores_raw_codes — DURABLE
The only test where the source category is id-only (stored "15", answered as its label); phase 3's success test sends a labelled category. Destination: `tests/active/test_video.py`.

### test_fetch_failure_leaves_db_untouched — DURABLE
The failure write guard is asserted nowhere else. Destination: `tests/active/test_video.py`.

### test_success_refreshes_row_and_response — DURABLE
Full-payload merge + write. Destination: `tests/active/test_video.py`.

### test_partial_payload_keeps_tags_and_category — DURABLE
Absent/null/blank fields keep the DB value. Destination: `tests/active/test_video.py`.

### test_failed_channel_fetch_keeps_stored_followers — DURABLE
Channel-detail fallback. Destination: `tests/active/test_video.py`.

### test_empty_tag_list_propagates — DURABLE
`[]` stores "[]" (to_tags_json). Destination: `tests/active/test_video.py`.

### test_object_body_counts_as_success — DURABLE
`{}` is a success (identity write guard, not truthiness). Destination: `tests/active/test_video.py`.

### test_second_request_reflects_source_change — DURABLE
No stale-row caching between requests. Destination: `tests/active/test_video.py`.

### test_a_body_with_category_language_and_tags_shows_both_values_and_one_text_chip_per_tag — DURABLE
No active test drives the video page. Subject file to CREATE: `tests/active/test_frontend_video_page.py`.

### test_a_body_with_empty_category_language_and_tags_hides_both_items_and_reads_no_tags — DURABLE
Destination: `tests/active/test_frontend_video_page.py`.

### test_an_empty_language_alone_hides_only_the_language_item — DURABLE
Destination: `tests/active/test_frontend_video_page.py`.

## Plan summary

15 test functions: DURABLE 15, REPLACES 0, COMBINE 0, REDUNDANT 0, SPENT 0. Nothing in active is retired.

Proposed destinations: test_whitelist_migrations.py (new), test_videos_worker.py (existing), test_video.py (new), test_frontend_video_page.py (new). Proposed map changes: add those three new groups; add engine/crawler/src/db.ts and engine/crawler/dist/db.js to test_videos_worker.py.

## Step 4 outcome — NOT APPROVED

The plan was put to the operator with AskUser (Approve / Approve with the build plan's file names / Stop). The operator dismissed the question without answering. No approval, so Steps 5-8 were not carried out: no file moved, `test_groups` is unchanged, no mutation ran, and nothing went to delete_me. The four phase files are still in tests/tmp.

The record snapshot was byte-identical to the record (`cmp`), because no run happened, so it was moved back over `tests/last_test_validation.json`. A resumed harvest starts again at Step 1 and takes a fresh snapshot.

## Carried out on main (combined harvest of builds 10 and 11)

This supersedes "NOT APPROVED" above. The operator approved harvesting both builds; this harvest ran on main (project_dir `/home/enduser/code/PeerTube-browser`) together with harvest-11-fast-similars-response-plan.md, which records the same outcome from build 11's side. Bootstrap gate clear; `tests/last_test_validation.json.preharvest` taken before any run and restored before the closing `--compare`.

### Changes on main since this plan was written

- video.py now treats a detail answering `{}` as a failure (issue 11's rule). Phase 3 was already edited to match: `{}` is the `empty-object` param of `test_fetch_failure_leaves_db_untouched`, and `test_object_body_counts_as_success` is object-only. The line "`{}` is a success" under `test_object_body_counts_as_success` above is stale. That test now gates "a non-empty partial object is a success".
- Phase 4's runner carries `ResizeObserver`/`getComputedStyle` stubs for issue 14's collapsible description. These moved with the test.

### Verdicts: all 15 DURABLE, as planned

No verdict differs from the plan. The REDUNDANT re-check against build 11's tests, now in the same subject file:

- `test_fetch_failure_leaves_db_untouched` vs 11's `test_a_refresh_the_instance_did_not_answer_writes_nothing`: both kept. Build 10's drives the real `fetch_instance_json` parser (404, not-JSON and bad-UTF-8 bodies, the 8 s timeout argument) and answers the stored taxonomy and media fields. Build 11's goes through the real HTTP route and dispatch, compares the full DB-only body, and covers a stub answering `None`. `/api/video` now delegates wholly to the refresh path, but neither test asserts only what the other does.
- `test_failed_channel_fetch_keeps_stored_followers` vs 11's `..._channel_call_failed_still_writes...`: both kept. Build 10's has the detail supplying the display name while the channel call fails, and asserts the row and the response of one request. Build 11's has the display name falling back to the DB and asserts the video row written.
- `test_object_body_counts_as_success`: kept. Near-redundant with `test_partial_payload_keeps_tags_and_category[absent]`, but it alone asserts that a sparse success clears `instances.last_error*` and writes title and duration.
- `test_success_refreshes_row_and_response` vs 11's `..._answered_writes_...`: both kept. They assert different columns: language, thumbnail and labels here; the `last_checked_at` window, popularity and the untouched neighbour row there.

### Destinations

- `tests/active/test_whitelist_migrations.py` (new): `test_migration_adds_language_column`.
- `tests/active/test_videos_worker.py` (existing): `test_crawl_stores_each_videos_language` and `test_crawl_adds_language_to_existing_db`. They reuse the file's `_instance` and `_git`. `_dist_is_stale` gained `src`/`dist` parameters, defaulting to the old pair, and `BUILD_PAIRS`, `_require_built_crawler`, `_crawl`, `_stop` and `_column_names` were added.
- `tests/active/test_video.py` (new, shared with build 11): phases 2 and 3. The two phases' `server` fixtures were merged into phase 3's, which seeds a superset. `HOST` became `PEER_HOST`, and phase 3's `CHANNEL_PATH` became `NEWSLUG_PATH` so it does not clash with build 11's constants. `test_response_labels` uses the shared `responses` fixture.
- `tests/active/test_frontend_video_page.py` (new): phase 4, copied whole.

The `# C1`/`# C2` build-criterion markers were dropped, and comments that named the phase or build were rewritten to state the rule.

### Group map (`.un/skills/devsecops/config.json`)

- `test_videos_worker.py` gained `engine/crawler/src/db.ts`, `engine/crawler/dist/db.js` and `engine/crawler/schema.sql`.
- New `test_whitelist_migrations.py`: `engine/server/db/jobs/whitelist_migrations.py`, `engine/server/db/jobs/sync-whitelist.py`.
- New `test_video.py`: `engine/server/api/handlers/video.py`, `engine/server/data/peertube_labels.py`, `engine/server/api/handlers/similar.py`, `engine/server/data/db.py`.
- New `test_frontend_video_page.py`: `client/frontend/src/pages/video-page/index.ts`, `client/frontend/src/video.css` and `client/frontend/video-page.html`. The css lives at `src/video.css`, not beside index.ts. The test loads css as empty and stubs `document`, so neither the css nor the html is actually driven. They are listed at the operator's request.
- `--audit-map` exits 0 and `missing_paths` is empty.

### Mutations (backups kept in `delete_me/harvest-10-11-bak/`, restores proved with `cmp`, red then green)

- `test_migration_adds_language_column`: whitelist_migrations.py's `ALTER TABLE videos ADD COLUMN language` replaced by `return`. Red: `len(language) == 1` (0).
- `test_crawl_stores_each_videos_language`: dist/videos-worker.js `language: extractLanguage(...)` changed to `null`. Red: the languages dict.
- `test_crawl_adds_language_to_existing_db`: dist/db.js's `ALTER TABLE ... language` changed to `return`. Red: node exit, with "table videos has no column named language".
- `test_response_labels`: peertube_labels `category_label` returns the raw value. Red: id-and-code and last-id ("15" != "Science & Technology", "18" != "Food").
- `test_refresh_stores_raw_codes`: merged `category` stored as `category_label(category)`. Red: stored ("Science & Technology", "en") != ("15", "en").
- `test_fetch_failure_leaves_db_untouched`: write guard `dynamic is not None and` removed. Red: all 6 params on the snapshot.
- `test_success_refreshes_row_and_response`: the UPDATE binds `None` for language. Red: row `language` None != "en".
- `test_partial_payload_keeps_tags_and_category`: `tags_json` fallback to the row removed. Red: both params, `tags_json` None.
- `test_failed_channel_fetch_keeps_stored_followers`: `channel_followers` fallback removed. Red: followers None != 3.
- `test_empty_tag_list_propagates`: `to_tags_json` answers None for `[]`. Red: '["old"]' != '[]'.
- `test_object_body_counts_as_success`: success requires a `channel` key. Red: the row was not written.
- `test_second_request_reflects_source_change`: `fetch_instance_video_dynamic` memoised with lru_cache. Red: second response at index 1.
- `test_a_body_with_category_language_and_tags_shows_both_values_and_one_text_chip_per_tag`: `tag-chip` class changed to `tag`. Red: chip False.
- `test_a_body_with_empty_category_language_and_tags_hides_both_items_and_reads_no_tags`: "No tags" changed to "". Red: [] != ['No tags'].
- `test_an_empty_language_alone_hides_only_the_language_item`: the language item is rendered from `category`. Red: language hidden False.

Process fault, recorded: the first attempts at the two tag mutations (m22 and m23) were sent as parallel calls. They mutated index.ts at the same moment, and m22's red run saw m23's mutation. Both backups had been copied from the original before either sed ran, and index.ts was `cmp`-identical to them afterwards. Both mutations were then rerun one at a time (m22b, m23b) and those clean results are the ones above.

### Disposal and closing run

- The four phase files moved to `delete_me/` with `mv -n`.
- Solo runs: test_whitelist_migrations 1, test_videos_worker 3, test_video 31, test_frontend_video_page 3, test_server 70 passed.
- Closing `--compare` against the restored pre-harvest record: 213 passed; 39 appeared, one per harvested test id of builds 10 and 11 combined; none departed; no new red.
