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
