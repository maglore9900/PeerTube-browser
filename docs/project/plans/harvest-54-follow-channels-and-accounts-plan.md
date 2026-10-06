# Harvest: plan 54 follow channels and accounts

## Step 1: resolved paths and scope

Bootstrap gate: clear. `./.un/skills/devsecops/scripts/validate_tests.py --show-config` reports `defaulted` as `[]` and `conflicts` as `[]`.

- project_dir: `/home/enduser/code/PeerTube-browser` (the session directory, where `source` lives). `--show-config` reports `project_dir` as `/home/enduser/code/PeerTube-browser/.worktrees/55`, a value set in `tests/config.json` line 3; that directory does not exist (`.worktrees/` is empty), so every command here runs from `/home/enduser/code/PeerTube-browser` and every `<PROJECT_DIR>` prefix is that path. The stale `project_dir` value is not changed by this harvest.
- source (group map): `/home/enduser/code/PeerTube-browser/tests/config.json`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- HARVEST_FILE: `docs/project/plans/harvest-54-follow-channels-and-accounts-plan.md`

Record snapshot: `tests/last_test_validation.json` existed and was copied to `tests/last_test_validation.json.preharvest` (235076 bytes, `cmp`-identical). The only command run before it was a non-banking `pytest --collect-only` over the four files in scope; no `validate_tests.py` run has banked in this harvest.

Scope: the four tests this build wrote, as named by the build dispatch:

- `tests/tmp/test_54_follow_channels_and_accounts_phase1.py`
- `tests/tmp/test_54_follow_channels_and_accounts_phase2.py`
- `tests/tmp/test_54_follow_channels_and_accounts_phase3.py`
- `tests/tmp/test_54_follow_channels_and_accounts_phase4.py`

Out of scope but present in `tests/tmp`: `__pycache__/`, `delete_failed_row.py`, 98 `probe_*.py` files (among them this build's emptied probes `probe_following_phase1.py`, `probe_following_sqlite.py`, `probe_phase2_channels.py`, `probe_phase4_follow_frontend.py`, `probe_phase4_durable_a.py` to `_d.py`, which the phase reports ask to delete), and `test_probe_55_phase3_drivers.py` (0 bytes, collects nothing). Step 7 moves only the four files in scope, so `tests/tmp` will not be empty afterwards unless the operator widens the disposal.

Existing related state: `tests/archive/54_follow_channels_and_accounts/test_frontend_feed_params.py` already holds the `== 5` FEED_MODES control this build's step 8 retired by operator decision; this harvest's archive topic would be the same directory, but no test is retired here.

Collection: all four files collect, 49 test functions and 80 items (`pytest --collect-only`): phase1 18, phase2 24, phase3 24, phase4 14. None needed a `validate_tests.py <path>` run to diagnose a collection failure.

## Step 2: inventory

### tests/tmp/test_54_follow_channels_and_accounts_phase1.py

Drives `engine/server/api/handlers/similar.py` (`SimilarHandler.do_POST`, `_handle_similar_request`, `_handle_following`, `_parse_follows`) over `engine/server/data/random_videos.py` (`fetch_followed_page`, cursor encode/decode), plus `engine/server/data/videos.py` `ensure_video_indexes` and `engine/server/db/jobs/sync-whitelist.py` `ensure_whitelist_schema`/`ensure_content_schema`. The walk tests run the real handler under `ENGINE_PY` in a child (`_FOLLOWING_CHILD`) on a temp catalogue; the request tests use the session `engine` fixture.

Module-level dependencies: conftest import of `ENGINE_PY`, `ROOT`, `engine`, `shared_trending_before`, `trending_seed`; `SERVER_DIR` sys.path setup; imports `compute_ann_id`, `create_video_embeddings_table`, `ensure_moderation_schema`, `ensure_video_indexes`; constants `CRAWL_SCHEMA`, `SYNC_JOB`, `T0`, `FUTURE`, `FOLLOW_PAGE`, `THRESHOLD`, `MAX_PAGES`, `ACCT_A`/`ACCT_B`/`ACCT_X`, `CATALOGUE`, `LABEL_OF`, `MAIN_CHANNELS`, `MAIN_FOLLOWS`, `MAIN_PAGES`, `NSFW_PAGES`, `MODERATION_FOLLOWS`, `FOLLOWING_PATH`, `EMPTY_HEADERS`/`PAYLOAD_HEADERS`/`CURSOR_HEADERS`/`RANDOM_HEADERS`/`SEEDED_HEADERS` (203.0.113.51-55), `NOWHERE_FOLLOWS`, `UPNEXT_PAGE`, `MALFORMED_FOLLOWS`, `MALFORMED_CURSORS`, `RECENCY_INDEXES`, `EXPECTED_INDEXES`; script `_FOLLOWING_CHILD`; helpers `_dummy_channels`, `_dummy_accounts`, `_catalogue`, `_walk`, `_cursor`, `_served`, `_pages`, `_key_columns`.

The Phase 1 report's "checkpoint defect" (walk bodies posted without a `follows` key) is no longer present: every `_walk` case now posts `{"follows": ...}`.

Tests:
- `test_a_following_walk_serves_the_followed_channels_and_accounts_newest_first_once_each_in_pages_that_start_strictly_after_the_cursor`
- `test_nsfw_flagged_rows_of_a_followed_source_are_served_only_with_nsfw_1`
- `test_a_full_last_page_carries_a_cursor_whose_page_is_empty_and_carries_none`
- `test_more_than_500_sources_and_exactly_1000_are_served_the_pages_their_few_row_holding_sources_give`
- `test_moderation_shortens_a_following_page_but_leaves_its_cursor_and_the_next_page_as_they_were`
- `test_a_following_request_without_follows_is_an_empty_page_with_no_cursor_not_a_fallback`
- `test_a_malformed_follows_payload_is_refused_400` (4 params)
- `test_more_than_1000_follow_sources_counted_across_channels_and_accounts_are_refused_400`
- `test_a_malformed_cursor_is_refused_400` (3 params)
- `test_random_1_still_wins_over_mode_following`
- `test_a_seeded_request_with_mode_following_and_follows_is_still_the_same_upnext`
- `test_ensure_video_indexes_creates_the_channel_and_account_recency_indexes_and_runs_again_on_a_database_that_has_them` (videos.py)
- `test_the_sync_stage_schema_creates_the_channel_and_account_recency_indexes_and_runs_again_on_a_database_that_has_them` (sync-whitelist.py)

### tests/tmp/test_54_follow_channels_and_accounts_phase2.py

Drives the Client backend's `/api/profile/follows` routes (`client/backend/server.py` `_handle_follow_add`/`_handle_follow_remove`/list) over `client/backend/lib/follows.py`, with `client/backend/lib/blocks.py` `add_block` for the swap, `client/backend/lib/profiles.py` `delete_profile`, and through `client/backend/lib/engine_api_client.py` `resolve_channel` the real Engine's `/internal/channels/resolve` (`engine/server/api/handlers/internal_client_reads.py`, `engine/server/data/channels.py`, routed by `engine/server/api/router.py`). Uses `engine_client` and `dataset`; the 429 test uses its own `limited_client` (`lib/http_utils.py` `RateLimiter`).

Module-level dependencies: conftest import of `CLOSED_ENGINE`, `ClientBackend`, `RateLimiter`, `client_server`, `dataset`, `engine`, `engine_client`, `ensure_user_schema`, `shared_trending_before`, `trending_seed`; constants `FOLLOWS`, `REMOVE`, `BLOCKS`, `SEARCH`, `KEY_FIELDS`, `LISTED_FIELDS`, `MAX_FOLLOWS`, `REFERENCE_MAX`, `NO_SUCH_UUID`, `RATE_BUDGET`, `REFUSAL`, `RESOLVABLE`, `MALFORMED`; fixture `limited_client`; helpers `_labelled_video`, `_twin`, `_unrelated`, `_videoless_channel`, `_channel_id_held_elsewhere`, `_mint`, `_key`, `_follow`, `_by_video`, `_by_channel`, `_listed`, `_follow_keys`, `_block_keys`, `_block`, `_remove`, `_channel_key`, `_account_key`, `_row`, `_follow_rows`, `_search`.

Tests:
- `test_a_video_s_channel_and_account_are_followed_under_whitelist_db_s_keys_and_labels_listed_per_profile_and_removed`
- `test_a_channel_named_in_upper_case_and_padded_is_stored_under_the_catalogue_s_own_key_and_label`
- `test_a_channel_or_a_video_the_catalogue_lacks_is_refused_404_and_nothing_is_stored`
- `test_a_malformed_follow_body_is_refused_with_its_reason_and_stores_nothing` (9 params)
- `test_following_a_target_already_followed_by_either_form_keeps_one_follow`
- `test_a_profile_holding_1000_follows_is_refused_a_1001st_keeps_its_1000_and_keeps_the_block_on_the_refused_key`
- `test_deleting_a_profile_removes_its_follows_and_keeps_another_s` (profiles.py)
- `test_every_follow_route_refuses_a_missing_or_unknown_key_with_the_one_401_and_changes_nothing`
- `test_a_follow_route_answers_429_once_an_address_has_spent_its_budget` (3 params)
- `test_following_a_channel_removes_the_block_on_that_channel_and_no_other_block`
- `test_blocking_a_channel_removes_the_follow_of_that_channel_and_no_other_follow` (blocks.py)
- `test_following_an_account_removes_the_block_on_that_account_and_no_other_block`
- `test_blocking_an_account_removes_the_follow_of_that_account_and_no_other_follow` (blocks.py)
- `test_an_account_follow_leaves_the_block_on_one_of_its_channels_in_place_and_that_channel_s_rows_still_go`

### tests/tmp/test_54_follow_channels_and_accounts_phase3.py

Drives the Client read gateway `client/backend/server.py` (`_handle_engine_read_proxy_post`, `_profile_filter`, `_is_following_read`, `FEED_CURSOR_PATTERN`), reading stored follows through `client/backend/lib/follows.py` `list_follows`. All but the last test run in front of a recording stand-in Engine (`_recording_engine`); the last walks the real Engine (`engine/server/api/handlers/similar.py` over `engine/server/data/random_videos.py`) through `engine_client`.

Module-level dependencies: conftest import of `ClientBackend`, `RateLimiter`, `client_server`, `dataset`, `engine`, `engine_client`, `ensure_user_schema`, `shared_trending_before`, `trending_seed`; imports `add_block`, `write_dislike`, `add_follow`, `resolve_profile`, `record_like`; constants `HOST`, `PAGE`, `FOLLOWING`, `STUB_CURSOR`, `CURSOR_MAX`, `CLEAN`, `BLOCKED_CHANNEL`, `BLOCKED_ACCOUNT`, `DISLIKED`, `ENGINE_ROWS`, `FOLLOWED_CHANNELS`, `FOLLOWED_ACCOUNTS`, `LONE_ACCOUNT`, `BYSTANDER_CHANNEL`, `STORED_LIKE`, `CENTROIDS`, `BROWSER_BODY`, `MALFORMED_CURSORS`, `OTHER_READS`, `WALK_PAGE`; helpers `_row`, `_channel`, `_account`, `_recording_engine`, `_serving`, `_query`, `_sent_follows`, `_keys`, `_published_key`; class `_Gateway`; fixture `gateway`.

Tests:
- `test_a_keyed_following_read_sends_exactly_the_profile_s_stored_follows_and_no_likes_centroids_or_exclude_at_the_page_limit`
- `test_a_keyed_profile_with_nothing_to_filter_still_sends_its_follow`
- `test_a_keyed_following_page_keeps_the_engine_s_cursor_and_serves_every_row_not_blocked_or_disliked_past_the_page_size`
- `test_a_keyless_following_read_reaches_the_engine_without_follows_and_is_served_the_whole_page`
- `test_a_browser_body_carrying_follows_is_refused_400_before_the_engine` (2 params)
- `test_a_malformed_cursor_is_refused_400_before_the_engine` (8 params)
- `test_a_url_safe_cursor_reaches_the_engine_unchanged_beside_the_follows` (2 params)
- `test_a_seeded_following_read_and_every_other_mode_keep_the_profile_s_like_centroids_exclude_and_doubled_limit` (7 params)
- `test_a_followed_channel_is_walked_through_the_gateway_in_two_cursor_pages_the_second_strictly_after_the_first`

### tests/tmp/test_54_follow_channels_and_accounts_phase4.py

Drives four frontend modules, each bundled with esbuild and run in node:
- `client/frontend/src/data/videos.ts` `createCursorPager`, with a scripted `fetchPage` (`PAGER_RUNNER`, fixture `pager_bundle`);
- `client/frontend/src/data/follows.ts` against the real Client and Engine (`FOLLOWS_RUNNER`, fixture `follows_runner`, `engine_client`, `dataset`, `identity_of`);
- `client/frontend/src/pages/videos/index.ts`, `pages/video-page/index.ts` and `pages/channels/index.ts` on a recording, innerHTML-parsing DOM (`DOM_JS` + `PAGE_RUNNER`, fixture `pages`, which bundles all three pages), with `components/video-card.ts` rendering the card follow buttons.

Module-level dependencies: conftest import of `dataset`, `engine`, `engine_client`, `identity_of`, `shared_trending_before`, `trending_seed`; constants `FRONTEND`, `ESBUILD`, `BASE`, `KEY_STORAGE`, `NEEDS_PROFILE`, `NEEDS_PROFILE_VIDEO_PAGE`, `LIMIT_ERROR`, `DOM_JS`, `PAGE_RUNNER`, `PAGER_RUNNER`, `FOLLOWS_RUNNER`, `PEER`, `OTHER`, `ALICE`, `BOB`, `OTHER_ALICE`, `CARDS`, `K1`-`K4`, `HOME_FOLLOWS`, `VIDEO_SEARCH`, `VIDEO_BODY`, `CHANNEL_NAMES`, `CHANNEL_ROWS`; fixtures `pages`, `pager_bundle`, `follows_runner`; helpers `_esbuild`, `_node`, `_seeds`, `_page`, `_follows_paths`, `_sent`, `_key_fields`, `_video_form`, `_channel`, `_account`, `_pager`, `_rows`, `_follows`, `_keyset`, `_card`, `_labels`, `_uids`, `_status`, `_feed_requests`, `_video_answers`, `_video_follow`, `_channel_row`, `_row_labels`, `_row_texts`.

Tests:
- `test_the_cursor_pager_walks_an_empty_page_resolves_a_short_one_and_is_exhausted_only_by_a_page_with_no_cursor` (videos.ts)
- `test_an_empty_page_with_a_null_cursor_ends_the_walk_instead_of_asking_again` (videos.ts)
- `test_a_fetch_that_throws_leaves_the_cursor_so_the_next_call_asks_for_the_same_page` (videos.ts)
- `test_follows_ts_follows_a_video_s_channel_and_account_and_a_named_channel_lists_them_and_unfollows_one_through_the_real_client` (follows.ts)
- `test_every_follows_ts_call_the_client_answers_401_rejects_with_profile_key_required` (follows.ts, 2 params)
- `test_home_cards_are_labelled_from_the_loaded_follow_list_and_a_toggle_relabels_every_card_of_its_source_in_place` (pages/videos)
- `test_keyless_home_cards_read_follow_and_a_click_sends_nothing_and_says_following_needs_a_profile` (pages/videos)
- `test_keyless_following_mode_shows_following_needs_a_profile_and_requests_no_feed` (pages/videos)
- `test_keyed_following_mode_walks_an_empty_page_by_its_cursor_to_the_rows_and_stops_without_a_cursor` (pages/videos)
- `test_the_video_page_s_buttons_are_labelled_from_the_follow_list_flip_on_each_toggle_and_a_block_resets_the_channel` (pages/video-page)
- `test_keyless_video_page_follow_buttons_send_nothing_and_say_following_needs_a_profile_on_the_home_page` (pages/video-page)
- `test_channels_rows_are_labelled_from_the_follow_list_and_flip_on_follow_and_unfollow_but_not_on_a_refusal` (pages/channels)
- `test_keyless_channels_rows_read_follow_and_a_click_sends_nothing_and_says_following_needs_a_profile` (pages/channels)

## Step 3: classification

Read against `rules/testing.md` `<surfaces>` and each subject file in `tests/active`. No active test asserts anything about the Following read, follows storage, the follow routes, the gateway's follow injection or cursor check, `createCursorPager`, `follows.ts` or any follow control: a search of `tests/active` for following/follows/recency-index terms finds only `test_similar.py`'s `POST_BUILD_MODES = {"following"}` exclusion and `test_videos.py`'s index-name set. Neither subject is split into `_a|_b|_c` parts. No two tests in scope assert the same behaviour: the Engine's cursor refusal (phase1) and the gateway's (phase3), the Client routes (phase2) and `follows.ts` over them (phase4), and the Engine walk (phase1) and the gateway walk (phase3) each gate a different producer.

### test_similar.py (`engine/server/api/handlers/similar.py` over `random_videos.py`)

- `test_a_following_walk_serves_the_followed_channels_and_accounts_newest_first_once_each_in_pages_that_start_strictly_after_the_cursor`: DURABLE. Order, source union, dedup, strict cursor and tie split across a page edge; no active test asserts any of it.
- `test_nsfw_flagged_rows_of_a_followed_source_are_served_only_with_nsfw_1`: DURABLE. `test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some` parametrises over `NSFW_LISTINGS`, which holds no following listing.
- `test_a_full_last_page_carries_a_cursor_whose_page_is_empty_and_carries_none`: DURABLE. Cursor-on-full-page rule, unasserted elsewhere.
- `test_more_than_500_sources_and_exactly_1000_are_served_the_pages_their_few_row_holding_sources_give`: DURABLE. The 500-term batching and the inclusive 1000 cap, unasserted elsewhere.
- `test_moderation_shortens_a_following_page_but_leaves_its_cursor_and_the_next_page_as_they_were`: DURABLE. Moderation-after-selection for the following arm, unasserted elsewhere.
- `test_a_following_request_without_follows_is_an_empty_page_with_no_cursor_not_a_fallback`: DURABLE. `test_the_handler_serves_trending_until_the_ranked_rows_run_out_then_an_empty_page_not_a_fallback` is the trending arm only.
- `test_a_malformed_follows_payload_is_refused_400`: DURABLE. New 400 text, unasserted elsewhere.
- `test_more_than_1000_follow_sources_counted_across_channels_and_accounts_are_refused_400`: DURABLE. New 400 text and cross-kind count, unasserted elsewhere.
- `test_a_malformed_cursor_is_refused_400`: DURABLE. Engine-edge cursor validation, unasserted elsewhere.
- `test_random_1_still_wins_over_mode_following`: DURABLE. No active test sends `random=1` together with `mode=following`; the dispatch order it gates is new.
- `test_a_seeded_request_with_mode_following_and_follows_is_still_the_same_upnext`: COMBINE with active `test_a_seeded_request_is_served_the_same_upnext_whatever_its_mode`. The active test already holds the same seed lookup, the seed=11 plain page and the repeat control, and loops `SEEDED_MODES`, which lacks `following`; this one adds only `mode=following` with a `follows` body. Neither is worth keeping whole: the incoming test is the active test's setup repeated for one more case. Merge: the active test survives in `test_similar.py`; lift into its loop the `mode=following` request with body `{"follows": NOWHERE_FOLLOWS}` and its two assertions (same `seed`, same `(video_id, instance_domain)` rows), with `NOWHERE_FOLLOWS` copied in. Rename the survivor `test_a_seeded_request_is_served_the_same_upnext_whatever_its_mode_or_follows`, so `--compare` will show the old name departing and the new one appearing. The emptied working test goes with its file in Step 7; no active test is archived.

### test_videos.py (`engine/server/data/videos.py`)

- `test_ensure_video_indexes_creates_the_channel_and_account_recency_indexes_and_runs_again_on_a_database_that_has_them`: DURABLE. The active `test_ensure_video_indexes_drops_the_two_duplicate_indexes_and_keeps_the_uuid_and_recency_indexes` asserts only index names; this asserts each key column, its DESC flag, the table, and a second run on a DB already holding them. The active test keeps its own value (the duplicate drop), so this is not a COMBINE.

### test_sync_whitelist.py (`engine/server/db/jobs/sync-whitelist.py`)

- `test_the_sync_stage_schema_creates_the_channel_and_account_recency_indexes_and_runs_again_on_a_database_that_has_them`: DURABLE. No active test reads an index the sync-stage schema creates.

### test_follows.py (NEW, `client/backend/lib/follows.py`, through the `/api/profile/follows` routes)

No subject file exists, so none of these can be `REDUNDANT`; Step 5 must create it. The plan's files list for Phase 2 names this file too.

- `test_a_video_s_channel_and_account_are_followed_under_whitelist_db_s_keys_and_labels_listed_per_profile_and_removed`: DURABLE. C1 key and label from the Engine row, list per profile, remove.
- `test_a_channel_named_in_upper_case_and_padded_is_stored_under_the_catalogue_s_own_key_and_label`: DURABLE. The channel form's strip, the Engine's lowercase lookup, and a channel with no videos.
- `test_a_channel_or_a_video_the_catalogue_lacks_is_refused_404_and_nothing_is_stored`: DURABLE. Both 404 texts on the exact pair.
- `test_a_malformed_follow_body_is_refused_with_its_reason_and_stores_nothing`: DURABLE. Every 400 text and the 200/201-character bound.
- `test_following_a_target_already_followed_by_either_form_keeps_one_follow`: DURABLE. Re-follow no-op across both forms.
- `test_a_profile_holding_1000_follows_is_refused_a_1001st_keeps_its_1000_and_keeps_the_block_on_the_refused_key`: DURABLE. The 1000 limit, exists-before-count order, and the refused key's block kept.
- `test_every_follow_route_refuses_a_missing_or_unknown_key_with_the_one_401_and_changes_nothing`: DURABLE. 401 on the three follow routes.
- `test_a_follow_route_answers_429_once_an_address_has_spent_its_budget`: DURABLE. The limiter on the three follow routes.
- `test_following_a_channel_removes_the_block_on_that_channel_and_no_other_block`: DURABLE. `add_follow`'s block delete on exactly one key, both forms.
- `test_following_an_account_removes_the_block_on_that_account_and_no_other_block`: DURABLE. The same for kind account.
- `test_an_account_follow_leaves_the_block_on_one_of_its_channels_in_place_and_that_channel_s_rows_still_go`: DURABLE. An account follow does not lift a channel block, read on the served search page.

### test_blocks.py (`client/backend/lib/blocks.py`)

- `test_blocking_a_channel_removes_the_follow_of_that_channel_and_no_other_follow`: DURABLE. It drives `POST /api/profile/blocks`, so its subject is `add_block`; no active block test reads follows.
- `test_blocking_an_account_removes_the_follow_of_that_account_and_no_other_follow`: DURABLE. The same for kind account.

### test_profiles.py (`client/backend/lib/profiles.py`)

- `test_deleting_a_profile_removes_its_follows_and_keeps_another_s`: DURABLE. The active `test_deleting_a_profile_removes_its_rows_and_like_generations_and_keeps_anothers` counts `profiles`, `users`, `likes` and `like_generations` through `_rows_for`, and not `follows`. It is not a COMBINE because the incoming test stores its follows through the real Engine (`engine_client`, `dataset`), while the active one runs on `client_backend` against a closed Engine; merging would mean rewriting one side's setup.

### test_server.py (`client/backend/server.py`, the read gateway)

- `test_a_keyed_following_read_sends_exactly_the_profile_s_stored_follows_and_no_likes_centroids_or_exclude_at_the_page_limit`: DURABLE. Follow injection in place of likes, centroids and exclude, at the unmultiplied limit.
- `test_a_keyed_profile_with_nothing_to_filter_still_sends_its_follow`: DURABLE. Injection is not gated on the row filter.
- `test_a_keyed_following_page_keeps_the_engine_s_cursor_and_serves_every_row_not_blocked_or_disliked_past_the_page_size`: DURABLE. Filtered, not trimmed, cursor kept.
- `test_a_keyless_following_read_reaches_the_engine_without_follows_and_is_served_the_whole_page`: DURABLE. Keyless pass-through with cursor; no active test sends a cursor.
- `test_a_browser_body_carrying_follows_is_refused_400_before_the_engine`: DURABLE. `follows` refused at the allowlist, with no Engine call.
- `test_a_malformed_cursor_is_refused_400_before_the_engine`: DURABLE. `FEED_CURSOR_PATTERN` refusals.
- `test_a_url_safe_cursor_reaches_the_engine_unchanged_beside_the_follows`: DURABLE. Pass-through at the 1024 bound.
- `test_a_seeded_following_read_and_every_other_mode_keep_the_profile_s_like_centroids_exclude_and_doubled_limit`: DURABLE. The active `test_a_keyed_hot_page_drops_the_blocked_channel_and_disliked_video_and_asks_the_engine_for_twice_the_page` covers only `mode=hot`'s doubled limit and filter. It asserts nothing about likes, centroids or exclude, and nothing about a seeded `mode=following` or a body `mode` being ignored.
- `test_a_followed_channel_is_walked_through_the_gateway_in_two_cursor_pages_the_second_strictly_after_the_first`: DURABLE. Real Client in front of the real Engine: the gateway's page equals the Engine's own, and the cursor page is strictly after it.

### test_frontend_upnext_pager.py (`client/frontend/src/data/videos.ts`)

The existing subject file for `data/videos.ts`'s pager: its group lists `videos.ts` first, and its one test drives `createFeedPager`. A new `test_frontend_videos.py` would give `videos.ts` a second subject file, and its name would sit next to `test_frontend_videos_page.py`. Step 5 would widen the module docstring to the feed pagers of `data/videos.ts`.

- `test_the_cursor_pager_walks_an_empty_page_resolves_a_short_one_and_is_exhausted_only_by_a_page_with_no_cursor`: DURABLE. `createCursorPager` is unasserted elsewhere.
- `test_an_empty_page_with_a_null_cursor_ends_the_walk_instead_of_asking_again`: DURABLE.
- `test_a_fetch_that_throws_leaves_the_cursor_so_the_next_call_asks_for_the_same_page`: DURABLE.

### test_frontend_follows.py (NEW, `client/frontend/src/data/follows.ts`)

No subject file exists; Step 5 must create it. The plan's Phase 4 files list names it.

- `test_follows_ts_follows_a_video_s_channel_and_account_and_a_named_channel_lists_them_and_unfollows_one_through_the_real_client`: DURABLE.
- `test_every_follows_ts_call_the_client_answers_401_rejects_with_profile_key_required`: DURABLE.

### test_frontend_videos_page.py (`client/frontend/src/pages/videos/index.ts`)

The active file covers only the NSFW checkbox reload.

- `test_home_cards_are_labelled_from_the_loaded_follow_list_and_a_toggle_relabels_every_card_of_its_source_in_place`: DURABLE.
- `test_keyless_home_cards_read_follow_and_a_click_sends_nothing_and_says_following_needs_a_profile`: DURABLE.
- `test_keyless_following_mode_shows_following_needs_a_profile_and_requests_no_feed`: DURABLE.
- `test_keyed_following_mode_walks_an_empty_page_by_its_cursor_to_the_rows_and_stops_without_a_cursor`: DURABLE.

### test_frontend_video_page.py (`client/frontend/src/pages/video-page/index.ts`)

The active file covers taxonomy and comments.

- `test_the_video_page_s_buttons_are_labelled_from_the_follow_list_flip_on_each_toggle_and_a_block_resets_the_channel`: DURABLE.
- `test_keyless_video_page_follow_buttons_send_nothing_and_say_following_needs_a_profile_on_the_home_page`: DURABLE.

### test_frontend_channels_page.py (`client/frontend/src/pages/channels/index.ts`)

The active file covers the `channel-domain` class.

- `test_channels_rows_are_labelled_from_the_follow_list_and_flip_on_follow_and_unfollow_but_not_on_a_refusal`: DURABLE.
- `test_keyless_channels_rows_read_follow_and_a_click_sends_nothing_and_says_following_needs_a_profile`: DURABLE.

### Fixtures to copy, not share (for Step 5)

- Phase 4's `DOM_JS` + `PAGE_RUNNER` and its `pages` fixture go to three subject files (`test_frontend_videos_page.py`, `test_frontend_video_page.py`, `test_frontend_channels_page.py`). Each gets its own copy, with the fixture cut to bundle only that file's page.
- `_esbuild`/`_node` go to those three files and to `test_frontend_upnext_pager.py` and `test_frontend_follows.py`.
- Phase 2's helpers go to `test_follows.py`, `test_blocks.py` and `test_profiles.py`, copied into each.
- Name collisions already visible for the Step 5 name check:
  - `test_server.py` already defines `DISLIKED` with a different body (title "D" vs "d").
  - `test_server.py` already defines `_serving`.
  - The active frontend files already define `FRONTEND`, `ESBUILD`, `BASE` and `bundle` fixtures.
  - `test_similar.py` already defines `FEED_PAGE`, `UPNEXT_PAGE`, `_keys` and `_post`.

## Step 4: plan (as presented)

See the `plan` presented at Step 4; no operator approval is taken in this build (dispatch instruction), and nothing has moved.

## Step 5: applied

The edits to `tests/active` and `tests/config.json` were made between 07:11 and 07:18 by an earlier pass of this step that recorded nothing here; this pass checked them before going on. Each of the 48 DURABLE tests is defined exactly once, in the destination the plan names. The COMBINE survivor is `test_similar.py::test_a_seeded_request_is_served_the_same_upnext_whatever_its_mode_or_follows`: its loop is followed by the `mode=following` request with body `{"follows": NOWHERE_FOLLOWS}` and its seed and row assertions, and the old name `test_a_seeded_request_is_served_the_same_upnext_whatever_its_mode` is gone. No active test was retired. No file in the twelve destinations binds a module-level name twice (AST check). The record was rewritten at 08:20, after the 07:08 snapshot; the snapshot itself is untouched (235076 bytes), and no production code file is newer than it.

### Name check, by subject file
- `test_similar.py`: phase1's constants, helpers and `_FOLLOWING_CHILD` are added with no clash. `SERVER_DIR`, `CRAWL_SCHEMA` and `UPNEXT_PAGE` are kept once (same body). The Engine `MALFORMED_CURSORS` stays in this file and does not clash with test_server.py's, which is a separate module.
- `test_videos.py`, `test_sync_whitelist.py`: `RECENCY_INDEXES`, `_key_columns` and `EXPECTED_INDEXES` are added to each file. `CRAWL_SCHEMA` is kept once in test_sync_whitelist.py (same body). In test_videos.py, `CRAWL_SCHEMA` is the file's own spelling of the same path.
- `test_follows.py` (new): every phase2 helper is copied in whole.
- `test_blocks.py`: kept once `KEY_FIELDS`, `LISTED_FIELDS`, `FOLLOWS`, `BLOCKS`, `SEARCH`, `_labelled_video`, `_follow`, `_by_video`, `_listed`, `_follow_keys`, `_block_keys`, `_channel_key` and `_account_key`. Renamed on a clash, with every use: `RESOLVABLE` -> `SERVED_RESOLVABLE`, `_mint` -> `_mint_profile`, `_block` -> `_add_block`.
- `test_profiles.py`: phase2's `_follow_rows`, `_labelled_video`, `_follow`, `_by_video` and `_listed` are added, and `_mint` is kept once (same body).
- `test_server.py`: renamed on a clash, with every use: `DISLIKED` -> `FOLLOWING_DISLIKED`, `_recording_engine` -> `_recording_following_engine`, `_keys` -> `_row_keys`. Kept once: `_serving`. `ENGINE_ROWS` and `gateway` differ from the phase file only by those renames.
- `test_frontend_upnext_pager.py`: `FRONTEND`, `ESBUILD`, `BASE`, `_esbuild` and `_node` are kept once (same body). `PAGER_RUNNER`, `pager_bundle`, `_pager` and `_rows` are added.
- `test_frontend_follows.py` (new): copies of `_esbuild`, `_node`, `_key_fields` and `FOLLOWS_RUNNER`. `follows_runner` builds only `profile.ts` + `follows.ts`.
- `test_frontend_videos_page.py`, `test_frontend_video_page.py`, `test_frontend_channels_page.py`: each holds its own copy of `DOM_JS`, `PAGE_RUNNER` and `_esbuild`/`_node`. Each `pages` fixture is cut to bundle only that file's page. `_page` clashed in test_frontend_video_page.py and was renamed `_follow_page`, with every use.

### Group map
Changes in `tests/config.json` `test_groups` (script `.scratch/harvest/map_edit.py`):
- New entries for `test_follows.py` and `test_frontend_follows.py`.
- `client/backend/lib/follows.py` added to `test_blocks.py`, `test_profiles.py` and `test_server.py`.
- `engine/server/data/random_videos.py` added to `test_server.py`.
- `client/frontend/src/data/follows.ts` added to the three page groups, and `client/frontend/src/components/video-card.ts` to `test_frontend_videos_page.py`.

`--audit-map` exits 0. Its MISSING findings for the destination groups are pytest tmp files, `time.py` and `client.log`, which are fixtures and shared helpers rather than subjects.

## Step 6: mutation plan (predicted before any run)

Baseline before any mutation: the 49 moved tests (80 items) passed in one run. The snapshot `tests/last_test_validation.json.preharvest` is on disk.

The mutation table and its driver are `.scratch/harvest/mutations.py`. Every anchor counts exactly 1 in the unmutated file. Each copy goes to `.scratch/harvest/<test_name>/<basename>.bak` (cp, then mv) before any mutation in its batch is applied.

There are six batches, A to F. In each, every mutation is predicted to fell its own target and no other target selected in that batch, so within a batch the predicted felled sets are disjoint singletons. Overlaps outside the batch that set the grouping:
- the phase1 walk tests share MAIN_PAGES;
- the exclude pop is read by both keyed injection tests;
- the GET 401 mutation also reads in follows.ts's no-key case;
- the follows.ts mutations are also read by the page tests;
- the pager's empty-page walk is also read by the keyed home walk;
- the account-follow channel-block drop is also read by the account-follow swap test;
- the cursor drop is also read by the URL-safe cursor test.

| Batch | Targets |
|---|---|
| A | walk dedup, moderation cursor, both index tests, follow removal, channel-block drop, profile delete, case-insensitive resolve, video-and-channel refusal, null-cursor end, home relabel, video-page block reset, channels refusal |
| B | NSFW, no-follows cursor, malformed follows, re-follow, account-block drop, unknown channel 404, keyless gateway, failed fetch keeps cursor, keyless home, keyless video page, keyless channels |
| C | full last page, 1000 cap, malformed Engine cursor, 1001st follow, 429, browser follows refused, empty page walked, keyless Following mode, follows.ts unfollow |
| D | >500 batching, random wins, seeded up-next (COMBINE), channel follow swap, keyed injection exclude, gateway malformed cursor, home cursor sent, follows.ts 401 message |
| E | account follow swap, lone profile injection, URL-safe cursor, other reads keep likes, follow route 401 |
| F | account follow keeps channel block, Following page uncut, gateway two-page walk |

## Step 6: mutations run

The outputs of every red run are kept as `.scratch/harvest/out<batch>.txt`. In every batch, the actual felled set matched the predicted one exactly, with no cancellations. After each run the batch's files were restored with `cp` from their copies; every `diff` exited 0 and the same selection re-ran green. At the end, all 14 mutated production files are byte-identical (`cmp`) to the earliest copy taken of each. No `.bak` remains under the production tree or `tests/active`, and the Step 1 snapshot is still on disk.

| Batch | Red | Green after restore |
|---|---|---|
| A | 13 failed | 21 passed |
| B | 11 failed | 14 passed |
| C | 13 failed (9 tests) | 22 passed |
| D | 9 failed (8 tests) | 16 passed |
| E | 5 failed | 12 passed |
| F | 4 failed | 4 passed |

**A different assertion, then a retry.** In batch B, the re-follow test's mutation was `if exists: return` -> `if False:`. It broke the rule, but the re-follow hit the primary key and the Client closed the connection (`RemoteDisconnected`), so the test errored inside `_follow` and never read `answers == [201] * 5`. That assertion was treated as unverified. It was re-mutated at another site in batch F, `if exists: raise FollowLimitReached`, which felled it cleanly: `[201, 400, 400, 201, 400] != [201] * 5`.

**Lost grip or never-had-grip:** none. Every test's final mutation felled the assertion it was moved for.

Per test, the mutation and the assertion it felled:
- walk (similar): dedup removed (`if key in seen` -> `if False`). Fell `_served(walk) == _pages(MAIN_PAGES)`: page 1 read A3 X2 X1 X1.
- nsfw: `include_nsfw=True` in `_handle_following`. Fell the filtered walk: NSF opens page 1.
- full last page: an empty page re-issues its input cursor. Fell `_pages([every, []])`: the empty page carried a cursor.
- >500 / 1000: only the first 500-term batch is read. Fell `_served(over)`: page 1 read A3 TA AM A1.
- moderation: the cursor is dropped when moderation shortens the page. Fell `_pages([["A3","TA"],["AM","A1"]])`.
- no follows: `cursor = "c"` when follows is None. Fell `page.get("cursor") is None`.
- malformed follows: the account-type check removed. Fell `(400, "Invalid follows payload")` for [a non-string account]: 200.
- >1000: `received = len(follows[0])`. Fell `(400, "Too many follow sources…")`: 200.
- malformed cursor: a decode error leaves `cursor = None`. Fell `(400, "Invalid cursor")` in all 3 params: 200.
- random wins: the random arm skipped for `mode=following`. Fell `seed == {"random": True}`: {}.
- COMBINE survivor: a seeded `mode=following` is dispatched to following. Fell the lifted `following["seed"] == plain["seed"]`: {}.
- ensure_video_indexes: the account index `published_at` set ASC. Fell `_key_columns == EXPECTED_INDEXES`.
- sync schema: the channel index `published_at` set ASC. Fell `_key_columns == EXPECTED_INDEXES`.
- follows video form, list, remove: remove_follow matches every follow of the profile. Fell `_listed == [account]`: [].
- upper-case channel: the Engine lookup no longer lowercases. Fell `(201, expected)`: 404.
- unknown channel 404: an unconfirmed channel is stored under the browser's key. Fell `(404, "Channel not found in Engine")`: 201.
- malformed body: the both-forms check disabled. Fell [a video and a channel] `(400, "Name a video or a channel, not both")`: 201.
- re-follow: see the retry above.
- 1001st: `count > MAX_FOLLOWS`. Fell `(400, "Follow limit reached (1000)")`: 201.
- 401: a keyless GET lists the empty profile. Fell `GET == REFUSAL`: (200, {"follows": []}).
- 429: the follow POST routes skip the limiter. Fell `[400, 400, 429]` in [add] and [remove]: the third read 400.
- follow channel swap: add_follow never drops a channel block. Fell `_block_keys == {twin, account(video), account(other)}`.
- follow account swap: add_follow never drops an account block. Fell `_block_keys == {channel(video), account(twin), account(other)}`.
- account follow keeps channel block: an account follow drops every channel block. Fell `_block_keys == {_channel_key(row)}`: set().
- block channel removes follow (test_blocks): add_block never drops a channel follow. Fell `_follow_keys == {twin, account(video), account(other)}`.
- block account removes follow (test_blocks): add_block never drops an account follow. Fell `_follow_keys == {channel(video), account(twin), account(other)}`.
- profile delete (test_profiles): the `DELETE FROM follows` line removed from delete_profile. Fell `(_follow_rows(gone), _follow_rows(kept)) == (0, 2)`: (2, 2).
- gateway keyed: the exclude pop removed. Fell `{"likes","dislike_centroids","exclude"} & keys == set()`: {'exclude'}.
- gateway lone: injection gated on row_filter. Fell `_sent_follows(body) == ([], [LONE_ACCOUNT])`: None.
- gateway cursor kept, uncut: `page_size = None` -> `pass`. Fell `_row_keys(rows) == _row_keys(CLEAN)`: trimmed to 3.
- gateway keyless: follows injected without a profile. Fell `"follows" not in body`.
- gateway browser follows: `follows` allowed in the body. Fell `(400, "Unknown body field: follows", [])` in both params: 200.
- gateway malformed cursor: the pattern became `{0,1024}`. Fell [empty] `(400, "Invalid cursor payload", [])`: 200.
- gateway URL-safe cursor: the pattern became `{1,1000}`. Fell [longest] `status == 200`: 400.
- gateway other reads: the `"id" not in query` check dropped from `_is_following_read`. Fell [seeded following] `likes == [stored like]`: None.
- gateway two-page walk: the keyed Following read pops the cursor. Fell `not first & second`: page 2 repeated page 1.
- pager walk: every page returned as-is. Fell `second == {"rows": ["b1"], …}`: rows [], asked [None, "c1"].
- pager null cursor: an exhausted empty page is walked past. Fell `second == {"rows": [], "exhausted": True, …}`: fetch 3 not scripted.
- pager throw: the cursor is cleared before the fetch. Fell `retried["asked"] == [None, "c1", "c1"]`: [None, "c1", None].
- follows.ts round trip: unfollow omits channel_id. Fell `_keyset(relisted) == {account, named}`: three remained.
- follows.ts 401: the Client's error replaced by `Follow request failed (n)`. Fell `results == [Profile key required] * 4` in both params.
- home labels and toggle: no relabel after a toggle. Fell `_labels(unfollowed)`: K1 and K2 still read Unfollow channel.
- home keyless: the follow text says Blocking. Fell `_status(channel, K1) == NEEDS_PROFILE`.
- home keyless Following: the keyless guard bypassed. Fell `_feed_requests(page) == []`.
- home keyed Following: the cursor not sent. Fell feed `[(following, None), (following, "c1")]`: the second request had None.
- video page labels: a block leaves the follow state. Fell `_video_follow(blocked) == (["Follow channel"], …)`.
- video page keyless: the keyless guard bypassed. Fell `NEEDS_PROFILE_VIDEO_PAGE in channel["texts"]`.
- channels labels: a refused follow flips the label. Fell `_row_labels(refused) == _row_labels(unfollowed)`: Night Drive read Unfollow.
- channels keyless: the keyless guard bypassed. Fell `NEEDS_PROFILE in _row_texts(clicked, lofi)`: the row read "Follow request failed (404)".

## Step 7: disposed

Moved with `mv` from `tests/tmp/` to `delete_me/`. No name was already taken there, so none was prefixed.
- `delete_me/test_54_follow_channels_and_accounts_phase1.py`
- `delete_me/test_54_follow_channels_and_accounts_phase2.py`
- `delete_me/test_54_follow_channels_and_accounts_phase3.py`
- `delete_me/test_54_follow_channels_and_accounts_phase4.py`

`tests/tmp` holds none of them. It still holds 101 out-of-scope entries, as noted in Step 1: 98 `probe_*.py` (among them this build's emptied probes), `delete_failed_row.py`, the empty `test_probe_55_phase3_drivers.py` and `__pycache__/`.

## Step 8: suite and bank

The snapshot was restored with `mv tests/last_test_validation.json.preharvest tests/last_test_validation.json` (235076 bytes) before the closing run. The closing run was `validate_tests.py --compare`, with no tier named, and it exited 0. It re-ran the 16 groups whose digest or map entry had changed since the pre-harvest record and carried the other 52 forward unchanged: 418 passed, 0 failed. The record is banked.

Delta against the pre-harvest record:
- 80 appeared: 79 moved items (48 DURABLE functions with their parametrisations) plus the renamed COMBINE survivor `test_similar.py::test_a_seeded_request_is_served_the_same_upnext_whatever_its_mode_or_follows`.
- 1 gone: `test_similar.py::test_a_seeded_request_is_served_the_same_upnext_whatever_its_mode`, the survivor's old name.
- 0 new red, 0 red turned green.

After the restore, `--audit-map` exits 0.
