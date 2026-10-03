# Harvest plan: 45 trending from source instances (build 46-45)

Workflow: `.un/skills/devsecops/workflows/harvest.md`, Steps 1-4 done (operator APPROVED with changes, see Step 4); Steps 5-8 recorded below.

Build: `docs/project/plans/46-45-trending-from-source-instances.md` (Trending replaces Hot). Its dev-flow Step 8 already promoted the four checkpoints verbatim into `tests/active` and retired conflicting durable tests to `tests/archive/45_trending_from_source_instances/`.

## Step 1: resolved paths and scope

Bootstrap gate: clear (`--show-config` `defaulted` is `[]`, `conflicts` is `[]`), cleared with no questions.

| Key | Value |
|---|---|
| project_dir | `/home/enduser/code/PeerTube-browser/` |
| config source | `tests/config.json` |
| active | `tests/active` |
| working | `tests/tmp` |
| plans | `docs/project/plans` |
| delete_me | `delete_me` |
| archive | `tests/archive` |
| record | `tests/last_test_validation.json` |
| archive topic for this harvest | `tests/archive/45_trending_from_source_instances/` (exists; holds `test_random_videos.py`, `test_similar.py`) |

Record snapshot: `tests/last_test_validation.json.preharvest` taken with `cp -n` before anything ran, then `cmp`-identical to the record. Step 8 restores it.

Pre-harvest map health: `--audit-map` exits 0 (25 MISSING, 50 UNRESOLVABLE and 7 BARREN, all advisory). `map_health.unmapped_groups` is `["test_search_fusion.py"]`, which predates this harvest and is outside its scope. The record was still `cmp`-identical after that run.

### Scope

Working checkpoints:
- `tests/tmp/test_45_trending_from_source_instances_phase1.py`
- `tests/tmp/test_45_trending_from_source_instances_phase2.py`
- `tests/tmp/test_45_trending_from_source_instances_phase3.py`
- `tests/tmp/test_45_trending_from_source_instances_phase4.py`

Their promoted copies in active, classified as if they came from working (a promoted copy and its checkpoint are one test, not two):
- `tests/active/test_fetch_trending.py`: byte-identical to phase1 (`cmp`).
- `tests/active/test_trending_feed.py`: phase2 less 3 lines. The tmp copy re-registers conftest's fixtures through `globals().update(...)`, which active does not need. Otherwise identical (`diff`).
- `tests/active/test_updater_trending_stage.py`: byte-identical to phase3.
- `tests/active/test_frontend_trending_mode.py`: byte-identical to phase4.

Archive "to be carried back" assertions:
- `tests/archive/45_trending_from_source_instances/test_random_videos.py` (header lists 5 still-valid assertions).
- `tests/archive/45_trending_from_source_instances/test_similar.py` (header lists none to carry back; checked below).

Non-test leftovers in `tests/tmp`, kept for Step 7 disposal: see "Disposal list" at the end.

Collection: all four tmp checkpoints and all four promoted copies collect, 54 items in each tree (15 + 25 + 6 + 8). This was checked with `python3 -m pytest -p no:cacheprovider --collect-only`, which banks nothing.

## Step 2: inventory

### tests/tmp/test_45_trending_from_source_instances_phase1.py (= tests/active/test_fetch_trending.py)
Drives `engine/server/db/jobs/fetch-trending.py`, loaded in-process. The denylist read goes through `data.moderation.list_active_denied_hosts`, and `purge_host_data` lives in `engine/server/data/moderation.py`.
Module fixtures and constants: `job` (module-scoped loader), `_load_job`, `_db` (crawler `schema.sql`, `create_video_embeddings_table`, `ensure_moderation_schema`, timeout 0.2), `_rows`, `_fetcher`, `_at`, `_Response`, `_fake_urlopen`, `FAILURES`, `JOB`, `JOBS_DIR`, `CRAWL_SCHEMA`, `TRENDING_URL`, `T0`, `DAY_MS`, `TEN_DAYS_MS`.
Tests: `test_a_run_asks_only_undenied_embedded_hosts_and_replaces_each_answered_host_s_rows_with_its_list`, `test_a_failed_host_keeps_its_rows_for_ten_days_and_loses_them_one_ms_later`, `test_purge_host_data_deletes_and_counts_the_host_s_trending_rows`, `test_fetch_host_list_reads_the_host_s_trending_page`, `test_fetch_host_list_returns_none_after_max_retries_plus_one_failed_attempts` (x7), `test_fetch_host_list_with_no_retries_makes_one_attempt`, `test_fetch_host_list_returns_the_list_when_a_retry_succeeds`, `test_a_run_that_cannot_take_the_write_lock_raises_and_leaves_the_table_unchanged`, `test_the_job_exits_non_zero_on_a_missing_db_and_creates_no_file`.

### tests/tmp/test_45_trending_from_source_instances_phase2.py (= tests/active/test_trending_feed.py)
Drives `engine/server/data/random_videos.py` (`fetch_ordered_page`, `fetch_popular_videos`, `ORDERED_FEED_ORDER_BY`, `ORDERED_FEED_SOURCE`) over the index from `engine/server/data/trending.py`. It also drives `engine/server/api/handlers/similar.py` (`SimilarHandler._handle_similar`, in a child under the Engine interpreter, and the live session Engine) and `engine/server/api/recommendations/mixer.py` (`MixingRecommendationStrategy` with the real `PopularVideosGenerator` from `candidates/popular_videos.py` on `server_config.RECOMMENDATION_PIPELINE`).
Module fixtures and constants: `active` (conftest import; `engine`, `dataset` and `trending_seed` fixtures), `ENGINE_PY`, `CRAWL_SCHEMA`, `THRESHOLD`, `RANKS`, `EXPECTED`, `FILTERED`, `FILTERS`, `LABEL_OF`, `_schema`, `_ranks_db`, `_labels`, `_Recorder`, `_plan`, `_HANDLER_CHILD`, `_handle`, `_key`, `_MIX_CHILD`, `_server_config`/`SERVER_CONFIG`, `FEED_PAGE`, `REFERENCE_DEPTH`, `LIVE_LIMIT`, `MODE_HEADERS`/`ORDERED_HEADERS`/`NSFW_HEADERS` (192.0.2.231-233), `_post`, `_keys`, `_exclude`, `_reference`, `_in_rank_order`, `nsfw_flagged` (module fixture), `NSFW_VALUES`.
Tests: `test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain` (x8), `test_a_trending_page_holds_only_ranked_catalogue_rows`, `test_an_empty_ranks_table_gives_an_empty_trending_page_and_an_empty_popular_pool`, `test_the_popular_pool_of_size_n_is_the_first_n_rows_of_the_trending_order_under_the_same_filters` (x4), `test_a_trending_page_walks_the_ranks_index_without_sorting`, `test_every_ordered_feed_has_a_source_and_serves_catalogue_rows`, `test_the_handler_serves_trending_until_the_ranked_rows_run_out_then_an_empty_page_not_a_fallback`, `test_the_mix_answers_with_an_empty_popular_layer_full_for_guests_and_short_by_popular_s_share_with_likes`, `test_mode_hot_is_refused_400_with_trending_among_the_allowed_modes` (live Engine), `test_trending_pages_after_excluded_pages_continue_the_rank_order_with_no_row_repeated` (live Engine), `test_trending_without_exactly_nsfw_1_serves_no_flagged_row_where_nsfw_1_serves_some` (live Engine, x5).

### tests/tmp/test_45_trending_from_source_instances_phase3.py (= tests/active/test_updater_trending_stage.py)
Drives `engine/server/db/jobs/updater-worker.py` (`main` in-process down the sync-join path, plus an AST scan of `main`). Child processes are replaced at `subprocess.run`, `run_similarity_stage` is a recorder, and `script_dir` points at a relocated jobs dir of empty scripts. The real `fetch-trending.py` is NOT driven.
Module fixtures and constants: `updater` (module loader, name `updater_worker_trending_phase3`), `sys.path` gets `engine/server` AND `engine/server/api` (`parse_args` imports `server_config`), `SYSTEMCTL`, `PYTHON_BIN`, `STOP`, `START`, `JOB_SCRIPTS`, `RUN_FLAGS`, `_jobs`, `_is_trending`, `_run`, `_children`, `_position`, `_completed`, `_layout`.
Tests: `test_trending_child_runs_against_prod_with_the_run_flags_after_the_engine_start_and_before_similarity` (x2), `test_trending_call_sits_after_the_service_try_and_before_the_similarity_stage`, `test_a_failure_inside_the_service_try_runs_no_trending_child`, `test_a_missing_fetch_trending_script_stops_the_run_before_any_child`, `test_a_failed_trending_child_still_runs_similarity_once_then_raises_trending_stage_failed`.

### tests/tmp/test_45_trending_from_source_instances_phase4.py (= tests/active/test_frontend_trending_mode.py)
Drives `client/frontend/src/data/feed-params.ts` and `client/frontend/src/data/videos.ts` through the harness in `tests/active/test_frontend_feed_params.py`, loaded by path. Reads the Engine's `FEED_MODES` from `engine/server/api/handlers/similar.py` by AST.
Module fixtures and constants: `harness` (`test_frontend_feed_params` module: `_modes`, `_stored`, `_run`, `VIDEOS`, `VIDEOS_ERROR`, `FEED_PARAMS_ERROR`), `ENGINE_FEED_MODES`.
Tests: `test_a_legacy_hot_from_the_url_or_storage_requests_trending`, `test_only_hot_is_read_as_trending`, `test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot`, `test_every_engine_mode_round_trips_through_the_url_and_storage` (x5).

### tests/archive/45_trending_from_source_instances/test_random_videos.py (carry-back candidates only)
Drives `engine/server/data/random_videos.py`. The carry-back functions need `VIDEOS`, `LABELS`, `NULL`, `FUTURE`, `EXPECTED["popular"]`, `EXPECTED["recent"]`, `_feed_db` (copies rows out of the repo's `whitelist.db`, read-only ATTACH), `_served`, `LIKES_VIDEOS`, `LIKES_SIGNAL_LIKES`, `LIKES_SIGNAL_SCORE`, `THRESHOLDS`, `_two_video_db`, `_reads`, `_by_label`, the `nsfw_conn` fixture (already in active) and the `time` import.
Retired functions holding still-valid assertions: `test_consecutive_pages_concatenate_into_the_order_s_total_sort`, `test_a_page_holds_exactly_the_embedded_rows_under_the_threshold`, `test_every_read_reports_each_video_s_crawled_likes_whatever_its_signal_likes`, `test_popular_and_ordered_rows_carry_no_interaction_signal_score`, `test_limits_count_only_allowed_rows`.

### tests/archive/45_trending_from_source_instances/test_similar.py (carry-back check only)
Retired: `test_every_feed_mode_and_a_missing_or_empty_mode_is_served_not_refused`, the `mode=hot` and `mode=recent` cases of `test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some`. Its header names nothing to carry back.

## Step 3: classification

Production facts relied on (read Step 3):
- `similar.py:105` `FEED_MODES = ("recommendations", "trending", "recent", "random", "popular")`.
- `similar.py:107` `ORDERED_FEED_MODES = {"trending", "popular", "recent"}`.
- `random_videos.fetch_popular_videos` is `fetch_ordered_page(conn, "trending", limit, 0, ...)`.
- Every order's SELECT reports `v.likes` (crawled), never `t.likes`.
- `fetch-trending.py` imports `list_active_denied_hosts` from `data.moderation`.
- `updater-worker.py` takes its `--concurrency/--timeout-ms/--max-retries` defaults from its own `parse_args`, not `server_config`.
- `moderation._host_table_column_pairs` lists `trending_ranks`.
- `tests/active/test_similar.py` parametrizes its ordered-paging test over `ORDERED_FEED_MODES`, so it already runs `[trending]`.

### Phase 1 → subject `engine/server/db/jobs/fetch-trending.py` → `tests/active/test_fetch_trending.py` (that file already is the subject file; these tests stay where they are)

#### test_a_run_asks_only_undenied_embedded_hosts_and_replaces_each_answered_host_s_rows_with_its_list
DURABLE → `tests/active/test_fetch_trending.py` (stays). Reason: no other active test asserts the asked-host set, positional ranks, key rules or run stats of the trending job.

#### test_a_failed_host_keeps_its_rows_for_ten_days_and_loses_them_one_ms_later
DURABLE → `tests/active/test_fetch_trending.py` (stays). Reason: the 10-day keep and the 1 ms-later age purge are asserted nowhere else.

#### test_purge_host_data_deletes_and_counts_the_host_s_trending_rows
DURABLE → `tests/active/test_moderation.py`, because its subject is `purge_host_data` in `data/moderation.py`, not the job. Reason: `test_moderation.py` holds only `purge_similarity_for_host`. `test_ann.py` calls `purge_host_data` only to set up an ANN read, and nothing asserts its `trending_ranks` delete or count.
Move note: the job only seeds the rank rows. In `test_moderation.py`, seed `trending_ranks` and `video_embeddings` directly (`data.trending.ensure_trending_schema`, `data.ann_ids.create_video_embeddings_table`, plain INSERTs) rather than carrying the job loader. The fixture is copied, not shared, and the assertions are unchanged.

#### test_fetch_host_list_reads_the_host_s_trending_page
DURABLE → `tests/active/test_fetch_trending.py` (stays). Reason: the exact trending URL, the timeout and the `data`-list return, `[]` included, are asserted nowhere else.

#### test_fetch_host_list_returns_none_after_max_retries_plus_one_failed_attempts (x7)
DURABLE → `tests/active/test_fetch_trending.py` (stays). Reason: retry count and None on every failure kind are asserted nowhere else.

#### test_fetch_host_list_with_no_retries_makes_one_attempt
DURABLE → `tests/active/test_fetch_trending.py` (stays). Reason: the `max_retries=0` bound is asserted nowhere else.

#### test_fetch_host_list_returns_the_list_when_a_retry_succeeds
DURABLE → `tests/active/test_fetch_trending.py` (stays). Reason: a successful retry returning its list is asserted nowhere else.

#### test_a_run_that_cannot_take_the_write_lock_raises_and_leaves_the_table_unchanged
DURABLE → `tests/active/test_fetch_trending.py` (stays). Reason: a locked DB raising and leaving the table unchanged is asserted nowhere else.

#### test_the_job_exits_non_zero_on_a_missing_db_and_creates_no_file
DURABLE → `tests/active/test_fetch_trending.py` (stays). Reason: the script's CLI exit codes and its no-create rule are asserted nowhere else.

### Phase 2 → subjects `data/random_videos.py` (`test_random_videos.py`), `api/handlers/similar.py` (`test_similar.py`) and `api/recommendations/mixer.py` (`test_mixer.py`, NEW)

#### test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain (x8)
DURABLE → `tests/active/test_random_videos.py`. Reason: `test_random_videos.py` holds only Popular and Recent orders, so the Trending total order, its filters, its end page and the index/no-index tie-break are asserted nowhere else.
Move note: carry `RANKS`, `EXPECTED` (rename it `TRENDING_EXPECTED`, because the carry-back below restores a different `EXPECTED`), `FILTERED`, `FILTERS`, `LABEL_OF`, `_schema`, `_ranks_db` and a label helper that does not collide with the existing `_labels(rows, label_of)`. Also carry `CRAWL_SCHEMA` and the imports of `ensure_moderation_schema`, `ensure_trending_schema` and `create_video_embeddings_table`.

#### test_a_trending_page_holds_only_ranked_catalogue_rows
REDUNDANT. Reason: the test above asserts exact list equality with `EXPECTED` at limits 1, 2 and 3, so a GHOST, U or N row on any page already fails it. If wanted, its one fixture control (GHOST and U are ranked) can be lifted into that test as a control line.

#### test_an_empty_ranks_table_gives_an_empty_trending_page_and_an_empty_popular_pool
DURABLE → `tests/active/test_random_videos.py`. Reason: that an empty `trending_ranks` gives an empty Trending page and an empty pool, with no fallback, is asserted nowhere else.

#### test_the_popular_pool_of_size_n_is_the_first_n_rows_of_the_trending_order_under_the_same_filters (x4)
DURABLE → `tests/active/test_random_videos.py`. Reason: that the pool is the Trending head under each filter pair is asserted nowhere else; the old Hot-pool test is archived.

#### test_a_trending_page_walks_the_ranks_index_without_sorting
DURABLE → `tests/active/test_random_videos.py`. Reason: the query-plan rule (`idx_trending_ranks_order`, no TEMP B-TREE) is asserted nowhere else. It carries `_Recorder` and `_plan`.

#### test_every_ordered_feed_has_a_source_and_serves_catalogue_rows
DURABLE → `tests/active/test_random_videos.py`. Reason: that the `ORDERED_FEED_SOURCE` keys equal the `ORDERED_FEED_ORDER_BY` keys is asserted nowhere else.

#### test_the_handler_serves_trending_until_the_ranked_rows_run_out_then_an_empty_page_not_a_fallback
DURABLE → `tests/active/test_similar.py`. Reason: `test_similar.py` checks ordered modes only live, against non-empty orders. An empty page with `seed {}` and no random fallback once the ranks run out or are emptied is asserted nowhere else. It carries `_HANDLER_CHILD`, `_handle`, `_key` and the `_ranks_db` fixture (a copy, not an import from `test_random_videos.py`).

#### test_the_mix_answers_with_an_empty_popular_layer_full_for_guests_and_short_by_popular_s_share_with_likes
DURABLE → NEW `tests/active/test_mixer.py` (subject `engine/server/api/recommendations/mixer.py`; there is no mixer test file today). Reason: the mixer's answer to an empty popular layer (guests 48 rows, home with likes 43 rows, popular serving 0 slots) is asserted nowhere else. It carries `_MIX_CHILD`, its own `_ranks_db` copy, `ENGINE_PY` and `random_videos`.
Alternative, if no new file is wanted: `tests/active/test_popular_videos.py`, since the real `PopularVideosGenerator` is driven. But the assertions under test are the mixer's slot accounting.

#### test_mode_hot_is_refused_400_with_trending_among_the_allowed_modes
COMBINE with `tests/active/test_similar.py::test_an_unseeded_request_with_a_mode_outside_feed_modes_is_answered_400_naming_them`.
Reason: the active test asserts the 400 body for near-misses (`bogus`, `HOT`, `home`) against the module's `FEED_MODES`, and this one asserts the retired `hot` itself is refused.
What comes across: add `"hot"` to `UNKNOWN_MODES`. The active test's controls then also gate `hot not in FEED_MODES`. Its "trending served 200" half is already asserted by `test_similar.py::test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` (`_post` requires 200).
Survivor keeps the active test's name; the parameter `[hot]` appears.
Flag: `UNKNOWN_MODES`' `"HOT"` comment ("a known mode in the wrong case") and `REQUIRED_MODES` still naming `hot` are stale since `hot` left `FEED_MODES`. Changing them is a behaviour change to an active test and is NOT proposed without approval.

#### test_trending_pages_after_excluded_pages_continue_the_rank_order_with_no_row_repeated
REDUNDANT. Reason: `test_similar.py::test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` sends the same three pages against the same `fetch_ordered_page` reference, plus a likes-invariance check. This test's extra `_in_rank_order` check reads the order `fetch_ordered_page` produces, and the moved fixture-DB order test above gates that order exactly.

#### test_trending_without_exactly_nsfw_1_serves_no_flagged_row_where_nsfw_1_serves_some (x5)
COMBINE with `tests/active/test_similar.py::test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some`.
Reason: the active test covers eight listings and no ordered mode, since `mode=recent` was retired in build Step 8 on the strength of this one. This test asserts the same filter for `mode=trending`.
What comes across: add `"mode=trending"` to `NSFW_LISTINGS`. `_nsfw_listing` already builds the identical request (`POST /recommendations?mode=trending&limit=2*BATCH_SIZE`, body `{}`), with one draw, a fresh client IP per request, the same nsfw=1 control and the same non-empty, no-flagged assertions.
Survivor keeps the active test's name; the parameters `[*-mode=trending]` appear.
Risk to record: its nsfw=1 control was rehearsed with exactly one flagged row in the first 96 seeded Trending rows. The seed is derived from the live dev `whitelist.db`, so a crawl can starve it, as happened to `mode=recent`.

### Phase 3 → subject `engine/server/db/jobs/updater-worker.py` → `tests/active/test_updater_worker.py`

#### test_trending_child_runs_against_prod_with_the_run_flags_after_the_engine_start_and_before_similarity (x2)
DURABLE → `tests/active/test_updater_worker.py`. Reason: `test_updater_worker.py` asserts nothing about the trending child's argv or its place between the start and the similarity stage.
Move note: `test_updater_worker.py` already has a `_run` (similarity-stage helper) and a `SYSTEMCTL` (same value). Carry this file's `_run` as `_run_trending_main` and carry `_jobs`, `_is_trending`, `_children`, `_position`, `_completed`, `PYTHON_BIN`, `STOP`, `START`, `JOB_SCRIPTS` and `RUN_FLAGS`.
Add `engine/server/api` to `sys.path`; `test_updater_worker.py` only adds `engine/server`, and `parse_args` imports `server_config`. Reuse the existing module `updater` fixture.

#### test_trending_call_sits_after_the_service_try_and_before_the_similarity_stage
COMBINE with `tests/active/test_updater_worker.py::test_main_runs_similarity_stage_after_service_start`. Reason: both scan `main` for the same service-start `try` and the same `run_similarity_stage` call. The active test asserts the stage sits after that `try` with no precompute inside it; this one asserts the one `fetch-trending.py` `run_cmd` sits between them.
What comes across: the name-following `trending_calls` scan from `_layout` and the assertions `len(trending_calls) == 1` and `service_try.end_lineno < trending_calls[0] < stage_calls[0]`, lifted into the active test.
Survivor name: `test_main_runs_trending_then_similarity_stage_after_service_start`. The old name departs in `--compare`, the new one appears, and no active test goes to archive.

#### test_a_failure_inside_the_service_try_runs_no_trending_child
DURABLE → `tests/active/test_updater_worker.py`. Reason: a raise inside the service `try` skipping both the trending child and the similarity stage is asserted nowhere else.

#### test_a_missing_fetch_trending_script_stops_the_run_before_any_child
DURABLE → `tests/active/test_updater_worker.py`. Reason: `fetch-trending.py` as a required file, checked before the Engine is stopped, is asserted nowhere else. The checkpoint itself says it is not a clause, but it is live behaviour.

#### test_a_failed_trending_child_still_runs_similarity_once_then_raises_trending_stage_failed
DURABLE → `tests/active/test_updater_worker.py`. Reason: the held-failure order (similarity still runs once, then exactly `RuntimeError("trending stage failed")`, no "worker completed") is asserted nowhere else.

### Phase 4 → subject `client/frontend/src/data/feed-params.ts` → `tests/active/test_frontend_feed_params.py`

#### test_a_legacy_hot_from_the_url_or_storage_requests_trending
DURABLE → `tests/active/test_frontend_feed_params.py`. Reason: no active test asserts the `hot`→`trending` alias from the URL, from storage or through persist. It uses the file's own `_modes`, `_stored`, `VIDEOS` and `VIDEOS_ERROR` directly instead of the by-path `harness` import.

#### test_only_hot_is_read_as_trending
COMBINE with `test_a_legacy_hot_from_the_url_or_storage_requests_trending` at its destination in `tests/active/test_frontend_feed_params.py`.
Reason: its `?mode=bogus` and stored-`bogus` cases are already asserted by `test_an_invalid_url_mode_gives_recommendations_even_over_a_stored_mode` and `test_unusable_stored_values_give_recommendations`, and its `hot` cases by the test above. Only one case is new: a bare JSON string `"hot"` stored gives `["recommendations"]`.
What comes across: that case, as one more row and assertion in the moved alias test.
Survivor name: `test_a_legacy_hot_from_the_url_or_a_stored_mode_object_requests_trending_and_a_bare_hot_string_does_not`. Nothing in active is retired.

#### test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot
COMBINE with `tests/active/test_frontend_feed_params.py::test_the_client_s_feed_modes_are_the_engine_s`. Reason: the active test asserts client == Engine, no repeats and five modes. This one adds `"trending" in ENGINE_FEED_MODES and "hot" not in ENGINE_FEED_MODES`, which nothing else gates when trending leaves `FEED_MODES` and `ORDERED_FEED_MODES` together.
What comes across: that one assertion (the client's "hot not in" follows from the existing equality).
Survivor name: `test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot`. The old name departs in `--compare`, the new one appears, and no active test goes to archive.

#### test_every_engine_mode_round_trips_through_the_url_and_storage (x5)
REDUNDANT. Reason: `test_the_url_mode_beats_the_stored_mode_and_the_legacy_random_flag[*]` (`?mode=<mode>` → `[mode]`) and `test_with_no_url_mode_the_stored_mode_is_sent_and_an_empty_mode_falls_through_to_it[*]` (stored `{mode}` → `[mode]`) already cover each of the five Engine modes, `trending` included.

### Archive carry-backs → `tests/active/test_random_videos.py`

#### Popular and Recent total-sort paging (from `test_consecutive_pages_concatenate_into_the_order_s_total_sort`)
DURABLE → `tests/active/test_random_videos.py`, as `test_popular_and_recent_pages_concatenate_into_the_order_s_total_sort`. Reason: active covers Popular's likes→views keys (signal test) and filtered paging on a fixture with no ties. Nothing asserts the `video_id DESC` tie (E/A) or the `instance_domain DESC` tie (T2/T) for either order, and nothing asserts Recent's paging under a threshold on tied rows.
Shape: parametrize `order` over `("popular", "recent")`, not over `ORDERED_FEED_ORDER_BY`, which now holds `trending`, and the fixture has no `trending_ranks`. Drop the `set(ORDERS) == set(EXPECTED)` line and the Hot/pool branch. `EXPECTED` keeps only `popular` and `recent`.

#### Embedded-rows-under-threshold page for Popular and Recent (from `test_a_page_holds_exactly_the_embedded_rows_under_the_threshold`)
DURABLE → `tests/active/test_random_videos.py`, as `test_a_popular_or_recent_page_holds_exactly_the_embedded_rows_under_the_threshold`. Reason: every active fixture row is embedded, has 0 errors (or exactly the threshold) and is dated in the past. Leaving out an unembedded row (N), keeping a row at threshold minus one (F), and Recent dropping NULL and future `published_at` (C, D) are asserted nowhere. Parametrize `order` over `("popular", "recent")`.

#### Crawled likes on the random, Popular-order and Recent-order reads (from `test_every_read_reports_each_video_s_crawled_likes_whatever_its_signal_likes`)
DURABLE → `tests/active/test_random_videos.py`. Reason: no active test reads the reported `likes` value; the signal test only ranks. `_reads` keeps `random`, `popular` and `recent` and drops `popular pool` and `hot`.
Optional, not proposed: Trending rows also report crawled `v.likes`. Asserting that is a new claim, not a carry-back.

#### No `interaction_signal_score` on Popular-order and Recent-order rows (from `test_popular_and_ordered_rows_carry_no_interaction_signal_score`)
DURABLE → `tests/active/test_random_videos.py`. Reason: asserted nowhere in active. It reads `popular` and `recent` through the same trimmed `_reads`, still skipping `random`.

#### LIMIT counts only allowed rows for `fetch_recent_videos` and `fetch_random_rows` (from `test_limits_count_only_allowed_rows`)
DURABLE → `tests/active/test_random_videos.py`, as `test_recent_and_random_limits_count_only_allowed_rows` (x2 thresholds), on the existing `nsfw_conn`. Reason: active's filter test reads at limit 100 only, so LIMIT counting allowed rows is asserted nowhere. Drop the two `fetch_popular_videos` lines (the "NSFW heads Hot" control and the pool loop); keep the Recent control.

#### tests/archive/45_trending_from_source_instances/test_similar.py
Nothing to carry back. Every `FEED_MODES` value is served by `test_a_mode_outside_the_ordered_set_answers_the_seed_its_pre_build_spelling_did` or by the ordered test (`[trending]` included). An empty `mode` is served by the former's `recommendations` case, and a missing `mode` by every home test. The request-edge NSFW filter on the ordered path returns through the `mode=trending` COMBINE above. `mode=recent` stays retired by operator decision.

### Verdict counts (29 test functions in scope; parametrized cases counted once)

| Verdict | Count |
|---|---|
| DURABLE | 21 (phase1 9, phase2 7, phase3 4, phase4 1) |
| COMBINE | 5 (phase2 2, phase3 1, phase4 2) |
| REPLACES | 0 |
| REDUNDANT | 3 (phase2 2, phase4 1) |
| SPENT | 0 |

Plus 5 archive carry-backs proposed DURABLE.

### Active tests that would be retired
- No pre-existing active test function is retired. All three active-side COMBINEs start from the active test and lift into it.
- Two active test functions are RENAMED by their COMBINE: `test_updater_worker.py::test_main_runs_similarity_stage_after_service_start` → `test_main_runs_trending_then_similarity_stage_after_service_start`, and `test_frontend_feed_params.py::test_the_client_s_feed_modes_are_the_engine_s` → `..._with_trending_and_not_hot`. Each shows as one departure and one appearance in `--compare`.
- The three promoted copies leave active whole once their tests are placed: `tests/active/test_trending_feed.py`, `tests/active/test_updater_trending_stage.py` and `tests/active/test_frontend_trending_mode.py`. Proposed destination: `tests/archive/45_trending_from_source_instances/`; no name collides there. They were in the durable suite, even if only for one step. OPEN for the operator: archive (proposed) or `delete_me/`, since their content is also in the tmp checkpoints going to `delete_me/`.
- `tests/active/test_fetch_trending.py` stays as the subject file; only `test_purge_host_data_deletes_and_counts_the_host_s_trending_rows` leaves it, for `test_moderation.py`.

### test_groups changes (Step 5.c, after approval)
- DROP `test_trending_feed.py`.
- DROP `test_updater_trending_stage.py`. Its claim on `fetch-trending.py` was never a subject: the stage tests run an empty relocated script.
- DROP `test_frontend_trending_mode.py`.
- ADD `test_mixer.py`: `engine/server/api/recommendations/mixer.py`, `engine/server/api/recommendations/candidates/popular_videos.py`, `engine/server/data/random_videos.py`, `engine/server/api/server_config.py` (`RECOMMENDATION_PIPELINE` sets the 48/5 counts asserted).
- EXTEND `test_random_videos.py` with `engine/server/data/trending.py`: the plan test asserts the index `ensure_trending_schema` defines.
- No change: `test_fetch_trending.py` (it keeps `moderation.py`, because the job's denylist read is `moderation.list_active_denied_hosts`), `test_moderation.py` (trending/ann schema helpers only build its fixture), `test_similar.py` (already claims `similar.py`, `random_videos.py` and `trending.py`), `test_updater_worker.py`, and `test_frontend_feed_params.py`.

### New subject file
- `tests/active/test_mixer.py`: new group and new map entry, holding the one mix test. Alternative without a new file: `test_popular_videos.py`.

## Step 4: agreed plan

The operator APPROVED the plan above, with these changes. Where they conflict with Step 3, they win.

1. The three emptied phase-named files (`tests/active/test_trending_feed.py`, `tests/active/test_updater_trending_stage.py`, `tests/active/test_frontend_trending_mode.py`) go to the configured `delete_me` dir (`delete_me`, per `--show-config`), NOT to the archive. Use `mv -n`, and on a name clash prefix the file with its subject.
2. `tests/active/test_mixer.py` is NOT created. The empty-popular-layer mix test (guest_home full batch, home with likes 43 of 48) goes into `tests/active/test_popular_videos.py`. That group's `test_groups` entry is extended with the production files the test drives, not with what it only imports for fixtures.
3. Tidy `tests/active/test_similar.py`:
   - In `REQUIRED_MODES`, `"hot"` becomes `"trending"`.
   - The near-miss `"HOT"` ("a known mode in the wrong case") becomes `"TRENDING"` in `UNKNOWN_MODES` and `SEEDED_MODES`, so the comment is true again.
   - The COMBINE adds plain `"hot"` to `UNKNOWN_MODES`, and to `SEEDED_MODES` so a seeded `mode=hot` request is still proven to ignore mode.
   - Any comment there that still describes hot as a live mode gets fixed.

Everything else is approved as proposed: 21 DURABLE, 5 COMBINE (the two renames included), 3 REDUNDANT, and the 5 archive carry-backs into `test_random_videos.py` over popular and recent. `test_groups` drops the three emptied files' entries and adds `engine/server/data/trending.py` to `test_random_videos.py`. The `test_mixer.py` map entry is replaced by an extension of `test_popular_videos.py`.

## Step 5: applied

The edits were made with the Edit tool; the sandbox refuses inline interpreter code. Every edited file collects (`pytest --collect-only`, which banks nothing), and the record stayed `cmp`-identical to the snapshot through Step 5.

### 5.a Tests placed

`tests/active/test_random_videos.py` (47 collected; was 20):
- The Trending block, carried with `RANKS`, `TRENDING_EXPECTED` (renamed from `EXPECTED`), `TRENDING_FILTERED`, `TRENDING_FILTERS`, `TRENDING_LABEL_OF`, `_schema`, `_ranks_db`, `_trending_labels` (wraps the file's own `_labels(rows, label_of)`), `_Recorder`, `_plan`, `CRAWL_SCHEMA`, and imports of `create_video_embeddings_table`, `ensure_moderation_schema` and `ensure_trending_schema`. Tests:
  - `test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain` (x8)
  - `test_an_empty_ranks_table_gives_an_empty_trending_page_and_an_empty_popular_pool`
  - `test_the_popular_pool_of_size_n_is_the_first_n_rows_of_the_trending_order_under_the_same_filters` (x4)
  - `test_a_trending_page_walks_the_ranks_index_without_sorting`
  - `test_every_ordered_feed_has_a_source_and_serves_catalogue_rows`
- Carry-backs, with `NULL`, `FUTURE`, `VIDEOS`, `SIGNAL_SCORE`, `SIGNAL_LIKES`, `LABELS`, `EXPECTED` (popular and recent only), `_feed_db`, `_served`, `LIKES_VIDEOS`, `LIKES_SIGNAL_LIKES`, `LIKES_SIGNAL_SCORE`, `THRESHOLDS`, `_two_video_db`, `_reads` (random, popular, recent) and `_by_label`, plus the `time` import. Comments that named hot were rewritten for two orders. Tests:
  - `test_popular_and_recent_pages_concatenate_into_the_order_s_total_sort` (x4)
  - `test_a_popular_or_recent_page_holds_exactly_the_embedded_rows_under_the_threshold` (x4)
  - `test_every_read_reports_each_video_s_crawled_likes_whatever_its_signal_likes`
  - `test_popular_and_recent_order_rows_carry_no_interaction_signal_score`: renamed from `test_popular_and_ordered_rows_carry_no_interaction_signal_score`, whose "popular" meant the pool, which it no longer reads.
  - `test_recent_and_random_limits_count_only_allowed_rows` (x2), on the existing `nsfw_conn`.
- The module docstring now describes all of the above. The pointer to `test_trending_feed.py` is gone.

`tests/active/test_moderation.py` (2 collected):
- `test_purge_host_data_deletes_and_counts_the_host_s_trending_rows`, moved out of `test_fetch_trending.py`. Its fixture `_ranks_and_embeddings` seeds `video_embeddings` and `trending_ranks` directly, through `create_video_embeddings_table` and `ensure_trending_schema`, rather than by running the job. `purge_host_data` skips absent tables, so no other schema is needed.
- `T0` and `_trending_rows` are copied, not shared. The assertions are unchanged.
- The docstring gained a paragraph for it.

`tests/active/test_fetch_trending.py` (14 collected; was 15): the purge test and its `purge_host_data` import are removed, and the docstring now points to `test_moderation.py`.

`tests/active/test_similar.py` (82 collected):
- `test_the_handler_serves_trending_until_the_ranked_rows_run_out_then_an_empty_page_not_a_fallback` is added. It carries its own copies of `RANKS`, `TRENDING_EXPECTED`, `TRENDING_SERVED` (the two threshold rows of `FILTERED`, keyed by `include_nsfw`), `TRENDING_LABEL_OF`, `TRENDING_THRESHOLD`, `CRAWL_SCHEMA`, `_ranks_db`, `_trending_labels`, `_rank_key` (was `_key`), `_TRENDING_HANDLER_CHILD` and `_handle_trending`, and a `sqlite3` import.
- COMBINE (`mode=hot` 400): `"hot"` was added to `UNKNOWN_MODES`.
- COMBINE (NSFW): `"mode=trending"` was added to `NSFW_LISTINGS`, with the starvation risk recorded in a comment beside it.
- Operator tidy:
  - `REQUIRED_MODES` names `trending` in place of `hot`.
  - `UNKNOWN_MODES` is `["bogus", "TRENDING", "home", "hot"]` and `SEEDED_MODES` is `[*REQUIRED_MODES, "bogus", "TRENDING", "hot", ""]`; the comment names hot as the mode trending replaced.
  - The "such as hot" comment in the pre-build test now reads "such as trending".
  - "observed for all three" now reads "observed for the near misses …; hot answered 200 while it was a feed mode".
  - The docstring bullets were updated, including "Nine listing paths".

`tests/active/test_popular_videos.py` (12 collected): `test_the_mix_answers_with_an_empty_popular_layer_full_for_guests_and_short_by_popular_s_share_with_likes`, per operator change 2. It carries its own `RANKS`, `TRENDING_ORDER`, `CRAWL_SCHEMA`, `_ranks_db` and `_MIX_CHILD`, and imports `data.random_videos` in-process for the catalogue control. The docstring gained a paragraph.

`tests/active/test_updater_worker.py` (61 collected):
- `engine/server/api` was added to `sys.path`, because `parse_args` imports `server_config`.
- Carried `PYTHON_BIN`, `STOP`, `START`, `JOB_SCRIPTS`, `RUN_FLAGS`, `_jobs`, `_is_trending`, `_run_trending_main` (was `_run`), `_children`, `_position` and `_completed`. They are placed after the module's `SYSTEMCTL`, and the existing module `updater` fixture is reused.
- DURABLE:
  - `test_trending_child_runs_against_prod_with_the_run_flags_after_the_engine_start_and_before_similarity` (x2)
  - `test_a_failure_inside_the_service_try_runs_no_trending_child`
  - `test_a_missing_fetch_trending_script_stops_the_run_before_any_child`
  - `test_a_failed_trending_child_still_runs_similarity_once_then_raises_trending_stage_failed`
- COMBINE: `test_main_runs_similarity_stage_after_service_start` became `test_main_runs_trending_then_similarity_stage_after_service_start`, with the name-following `trending_calls` scan and its two assertions lifted in.
- The docstring gained a trending-stage section.

`tests/active/test_frontend_feed_params.py` (31 collected):
- DURABLE + COMBINE: `test_a_legacy_hot_from_the_url_or_a_stored_mode_object_requests_trending_and_a_bare_hot_string_does_not`, with the bare-`"hot"`-string row lifted in from `test_only_hot_is_read_as_trending`.
- COMBINE: `test_the_client_s_feed_modes_are_the_engine_s` became `test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot`.
- The docstring bullets were updated.

Phase docstrings that named clause tags (`# C1`, `# R2`) had them replaced by the rule they gate.

### 5.b Retired

Per operator change 1, `mv -n` into `delete_me/` with no name clash:
- `tests/active/test_trending_feed.py`
- `tests/active/test_updater_trending_stage.py`
- `tests/active/test_frontend_trending_mode.py`

Nothing went to `tests/archive/`; no pre-existing active test function was retired.

### 5.c Group map (`tests/config.json`)

- Dropped `test_trending_feed.py`, `test_updater_trending_stage.py` and `test_frontend_trending_mode.py`.
- `test_random_videos.py` adds `engine/server/data/trending.py`.
- `test_popular_videos.py` adds:
  - `engine/server/api/recommendations/mixer.py`: the slot accounting asserted.
  - `engine/server/api/recommendations/profile.py`: `resolve_profile_config_with_guest` picks `guest_home` against `home`, which is what makes the guest batch full.
  - `engine/server/api/server_config.py`: `RECOMMENDATION_PIPELINE`'s 48 and 5.
  - `engine/server/data/random_videos.py`: the real `fetch_popular_videos`, whose empty pool is asserted.
  - Not added: `recommendations/keys.py`, `scoring.py`, `trending.py` and `moderation.py`. They are a passed-in key helper, scoring that does not set the counts, and fixture schema builders.
- No other entry changed.

`--audit-map` exits 0 (25 MISSING, 50 UNRESOLVABLE, 6 BARREN, all advisory; BARREN was 7 before the emptied files left). Its MISSING list for the moved tests names only:
- in `test_updater_worker.py`: the empty job scripts and `merge_rules.json` the trending tests write into a relocated jobs dir. These are fixture and correctly unclaimed.
- `time.py` and `tmp/suite28` paths, which predate the harvest.

## Notes for Steps 5-8 (known project traps)
- `delete_me/` already holds `cache_entry_sizes_issue41.py`, `logging_profiles.py.bak-issue39`, `logging_profiles.py.bak-issue39.2` and `similar.py.bak-issue39`. Always `mv -n`, or check first. Every Step 6 `.bak` must get a name unique within `delete_me/`, e.g. `similar.py.bak-harvest45`, because `similar.py.bak-issue39` is already there.
- A same-length mutation restored within the same second reuses the stale `.pyc`. Run `sleep 1` and `touch` the source before each mutation and after each restore.
- Several Engine-backed test files in one `validate_tests.py` call share one Engine and trip its 60/min rate limit. Step 6 runs one file and one `-k` at a time. The live COMBINEs (`test_similar.py` `[hot]` and `[*-mode=trending]`) each need the session Engine.
- `test_similar.py` has known intermittent reds (Engine 500 "Recommendations request failed"). Re-run before diagnosing a red there.
- Phase 1 tests staying in `test_fetch_trending.py` still each need their own Step 6 mutation; staying in place does not exempt them.
- Two mutations on one production file (`random_videos.py` for most phase-2 moves and carry-backs; `updater-worker.py`; `similar.py`): mutate one test at a time, with a distinct `.bak` suffix each.
- `--audit-map` exits 0 before the harvest, so a non-zero exit after Step 5.c comes from the harvest's own edit.

## Disposal list (Step 7, to `delete_me/`, no name collides with what is there today)
Checkpoints:
- `tests/tmp/test_45_trending_from_source_instances_phase1.py`
- `tests/tmp/test_45_trending_from_source_instances_phase2.py`
- `tests/tmp/test_45_trending_from_source_instances_phase3.py`
- `tests/tmp/test_45_trending_from_source_instances_phase4.py`

Non-test leftovers:
- `tests/tmp/draft_fetch_trending.py`
- `tests/tmp/probe_45_live_ranks.py`, `probe_45_mix_empty.py`, `probe_fetch_trending_cli.py`, `probe_mix_old_setup.py`
- `tests/tmp/probe_phase2_env.py`, `probe_phase2_layers.py`, `probe_phase2_planned.py`
- `tests/tmp/probe_phase3_harness.py`, `probe_phase3_layout.py`, `probe_phase3_red.py`
- `tests/tmp/probe_phase4_harness.py`, `probe_phase4_mutants.py`
- `tests/tmp/probe_purge_embeddings.py`
- `tests/tmp/probe_step8_recent.py`, `probe_step8_recent_head.py`, `probe_step8_seed_timing.py`
- `tests/tmp/probe_trending_draft.py`, `probe_trending_env.py`, `probe_trending_mutants.py`, `probe_trending_setup.py`
- `tests/tmp/__pycache__/` (37 `.pyc`, including stale ones from the build 41/42 checkpoints): moved whole as `delete_me/__pycache__-harvest45` so it is not mistaken for anything else.

That is 26 entries; `tests/tmp` is empty afterwards.

## Step 6: mutations (redone; recorded as run)

A previous run's mutations (backups `delete_me/*.bak-harvest45-m*`) left no record, so Step 6 was redone from scratch. Each mutation below ran alone: `cp` to `delete_me/<file>.bak-harvest45-r<N>`, `sleep 1`, Edit, `touch`, one `validate_tests.py <file> -k <test>` run; then `cp` back, `cmp`/`diff` clean, `sleep 1`, `touch`, the same run green. Backups stay in `delete_me/` (moved there with `mv -n`; none was ever written under the production tree). `tests/last_test_validation.json.preharvest` was checked on disk before the first run.

| Id | Test (subject file) | Rule broken | Edit | Assertion felled, diagnostic | Green after restore |
|---|---|---|---|---|---|
| R1 | `test_fetch_trending.py::test_a_run_asks_only_undenied_embedded_hosts_and_replaces_each_answered_host_s_rows_with_its_list` | the denylist is matched case-insensitively | `fetch-trending.py:105` `row[0].lower() not in denied` → `row[0] not in denied` | `assert sorted(calls) == asked` (line 102): `'Denied.Exam...' ... At index 0 diff: 'Denied.Example' != 'a.example'` | yes (diff clean, 1 passed) |
| R2 | `test_fetch_trending.py::test_a_failed_host_keeps_its_rows_for_ten_days_and_loses_them_one_ms_later` | a row exactly 10 days old is kept (purge is strictly older) | `fetch-trending.py:119` `fetched_at < ?` → `fetched_at <= ?` | `assert _rows(conn, "c.example") == [("c-1"...), ("c-2"...)]` (line 145): `assert [] == [('c-1', 1, 0...)]` | yes |
| R3 | `test_fetch_trending.py::test_fetch_host_list_reads_the_host_s_trending_page` | the request is the exact trending URL | `fetch-trending.py:32` `nsfw=both` → `nsfw=false` | `assert attempts == [(TRENDING_URL, 0.25)]` (line 186): `At index 0 diff: ('...&nsfw=false', 0.25) != ('...&nsfw=both', 0.25)` | yes |
| R4 | `test_fetch_trending.py::test_fetch_host_list_returns_none_after_max_retries_plus_one_failed_attempts` (x7) | every failure kind gets exactly `max_retries + 1` attempts | `fetch-trending.py:77` `range(max_retries + 1)` → `range(max_retries)` | all 7 cases, `assert attempts == [(TRENDING_URL, 0.25)] * 3` (line 209): `Right contains one more item` | yes (7 passed) |
| R5 | `test_fetch_trending.py::test_fetch_host_list_with_no_retries_makes_one_attempt` | `max_retries=0` makes exactly one attempt | `fetch-trending.py:77` `range(max_retries + 1)` → `range(max(max_retries, 1) + 1)` | `assert len(attempts) == 1`: `assert 2 == 1` | yes |
| R6 | `test_fetch_trending.py::test_fetch_host_list_returns_the_list_when_a_retry_succeeds` | a retry that succeeds returns its list | `fetch-trending.py:84` `return data` → `return data if attempt == 0 else None` | `assert job.fetch_host_list(...) == [{"uuid": "x"}]`: `assert None == [{'uuid': 'x'}]` | yes |
| R7 | `test_fetch_trending.py::test_a_run_that_cannot_take_the_write_lock_raises_and_leaves_the_table_unchanged` | a run that cannot take the write lock raises instead of reporting success | `fetch-trending.py:113` `BEGIN IMMEDIATE` wrapped in `try`, `except sqlite3.OperationalError: return {...stats, answered 0...}` | `with pytest.raises(sqlite3.OperationalError, match="database is locked")`: `Failed: DID NOT RAISE OperationalError` | yes |
| R8 | `test_fetch_trending.py::test_the_job_exits_non_zero_on_a_missing_db_and_creates_no_file` | a missing `--db` is refused before `sqlite3.connect` creates a file | `fetch-trending.py:147-148` removed the `if not db_path.is_file(): parser.error(...)` check | `assert not missing.exists()`: `assert not True` (the run still exited non-zero, on missing tables) | yes |
| R9 | `test_moderation.py::test_purge_host_data_deletes_and_counts_the_host_s_trending_rows` | `purge_host_data` deletes and counts the host's `trending_ranks` rows | `moderation.py:318` removed `("trending_ranks", "instance_domain")` from `_host_table_column_pairs` | `assert counts["trending_ranks"] == 2`: `KeyError: 'trending_ranks'` | yes |
| R10 | `test_random_videos.py::test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain` (x8) | within a rank, listed likes descend | `random_videos.py:18` trending `t.likes DESC` → `t.likes ASC` | all 8 cases, `assert labels == expected` (the order assertion): `AssertionError: (1, ['B1', 'A1', 'X', 'C1', ...])` | yes (8 passed) |
| R11 | `test_random_videos.py::test_an_empty_ranks_table_gives_an_empty_trending_page_and_an_empty_popular_pool` | an empty `trending_ranks` gives an empty pool, no fallback | `random_videos.py:238` `fetch_popular_videos` returns `fetch_ordered_page(..."trending"...) or fetch_ordered_page(..."popular"...)` | `assert random_videos.fetch_popular_videos(conn, 100) == []`: `Left contains 11 more items, first extra item: {'video_id': 'n1', ...}` | yes |
| R12 | `test_random_videos.py::test_the_popular_pool_of_size_n_is_the_first_n_rows_of_the_trending_order_under_the_same_filters` (x4) | the pool is the Trending head under the SAME filters | `random_videos.py:238` dropped `error_threshold=..., include_nsfw=...` from the pool's `fetch_ordered_page` call | 3 of 4 cases (`[3-False]`, `[3-True]`, `[None-False]`; `[None-True]` is unfiltered so cannot differ), `assert _trending_labels(pool) == expected[:n]`: `AssertionError: (2, ['C1', 'X'])` | yes (4 passed) |
| R13 | `test_random_videos.py::test_a_trending_page_walks_the_ranks_index_without_sorting` | a Trending page walks `idx_trending_ranks_order` and does not sort | `random_videos.py:17` `t.rank ASC` → `+t.rank ASC` (same order, index unusable for ORDER BY) | `assert any("idx_trending_ranks_order" in detail ...)`: `['SCAN t USING INDEX sqlite_autoindex_trending_ranks_1', ..., 'USE TEMP B-TREE FOR ORDER BY']` | yes |
| R14 | `test_random_videos.py::test_every_ordered_feed_has_a_source_and_serves_catalogue_rows` | `ORDERED_FEED_SOURCE` keys equal `ORDERED_FEED_ORDER_BY` keys | `random_videos.py:41` added a stale `"hot": "video_embeddings e"` source | `assert set(ORDERED_FEED_SOURCE) == set(ORDERED_FEED_ORDER_BY)`: `Extra items in the left set: 'hot'` | yes |
| R15 | `test_random_videos.py::test_popular_and_recent_pages_concatenate_into_the_order_s_total_sort` (x4) | Popular and Recent ties close on `instance_domain DESC` | `random_videos.py:27,32` `v.instance_domain DESC` → `ASC` in both orders | all 4 cases, `assert labels == expected`: `(1, ['C', 'D', 'T', 'T2', ...])` (T before T2) | yes (4 passed) |
| R16 | `test_random_videos.py::test_a_popular_or_recent_page_holds_exactly_the_embedded_rows_under_the_threshold` (x4) | Recent leaves out a future-dated row | `random_videos.py:250` `v.published_at <= ?` → `? IS NOT NULL` | the 2 recent cases (popular has no date bound to break), `assert served == set(VIDEOS) - left_out \| {"T2"}`: `{'A', 'B', 'D', 'F', 'T', 'T2'}` (future D served) | yes (4 passed) |
| R17 | `test_random_videos.py::test_every_read_reports_each_video_s_crawled_likes_whatever_its_signal_likes` | a read reports the crawled `likes`, not crawled plus signal likes | `random_videos.py:323` (ordered-page row dict) `"likes": row["likes"]` → `row["likes"] + (SUM(likes_count) from interaction_signals for the row)` | `assert likes == LIKES_VIDEOS, name`: `('popular', None) ... {'X': 53} != {'X': 3}` | yes |
| R18 | `test_random_videos.py::test_popular_and_recent_order_rows_carry_no_interaction_signal_score` | ordered-page rows carry no `interaction_signal_score` | `random_videos.py:328` added `"interaction_signal_score": row["popularity"]` to the ordered-page row | `assert "interaction_signal_score" not in row`: `(('popular', None), 'Y')` | yes |
| R19 | `test_random_videos.py::test_recent_and_random_limits_count_only_allowed_rows` (x2) | Recent's LIMIT counts only allowed rows | `fetch_recent_videos` built its conditions with `include_nsfw=True` and filtered NSFW rows after the LIMIT | both cases, line 610 `assert ... fetch_recent_videos(..., n, include_nsfw=False) == allowed[:n], n`: `AssertionError: 1 / assert [] == ['A']` | yes (2 passed) |
| S1 | `test_similar.py::test_the_handler_serves_trending_until_the_ranked_rows_run_out_then_an_empty_page_not_a_fallback` | an exhausted ordered feed answers an empty page, not the random fallback | `similar.py` `_handle_ordered_feed`: `if not rows: self._handle_random(...); return` before the response | line 979 `case["body"]["seed"] == {}`: the case answered `seed: {'random': True}` | yes |
| S2 | `test_similar.py::test_an_unseeded_request_with_a_mode_outside_feed_modes_is_answered_400_naming_them[hot]` (COMBINE) | `mode=hot` is refused 400 | `similar.py` mapped `feed_mode == "hot"` to `"trending"` before the FEED_MODES check | line 765: `(200, None) == (400, 'Unknown mode')` | yes (with S3's re-run) |
| S3 | `test_similar.py::test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[mode=trending-*]` (x5, COMBINE) | the ordered feed honours the request NSFW filter | `_handle_ordered_feed`: `include_nsfw = True` | all 5 cases, the no-flagged-row assertion (served set intersects the flagged set) | yes (9 passed incl. S2's `[hot]`) |
| P1 | `test_popular_videos.py::test_the_mix_answers_with_an_empty_popular_layer_full_for_guests_and_short_by_popular_s_share_with_likes` | an empty `trending_ranks` gives the popular layer an empty pool | `fetch_popular_videos` returned the trending page `or` the popular-order page | line 266 `out["home_empty"]["popular_served"] == 0`: `assert 5 == 0` | yes |
| U1 | `test_updater_worker.py::test_trending_child_runs_against_prod_with_the_run_flags_after_the_engine_start_and_before_similarity` (x2) | the child carries the run's own retries | trending argv `--max-retries str(args.concurrency)` | both cases, line 842 dict equality: `retries '4' != '3'`, `'7' != '5'` | yes |
| U2 | `test_updater_worker.py::test_main_runs_trending_then_similarity_stage_after_service_start` (COMBINE) | the trending `run_cmd` sits after the service `try` and before similarity | trending `run_cmd` moved into the service `finally`, after the start | line 359 (the lifted-in assertion): `assert 1443 < 1427` | yes |
| U2 / U2b | `test_updater_worker.py::test_a_failure_inside_the_service_try_runs_no_trending_child` | a raise inside the service `try` skips the trending child | U2 felled the control at line 856 (START no longer last), not the moved assertion; U2b put a trending `run_cmd` in the `finally` BEFORE the start | U2b: line 857 `assert not [trending cmds]` | yes |
| U3 | `test_updater_worker.py::test_a_missing_fetch_trending_script_stops_the_run_before_any_child` | `fetch-trending.py` is a required file | removed it from the required-files tuple | line 865: `assert NoneType is FileNotFoundError` | yes |
| U4 | `test_updater_worker.py::test_a_failed_trending_child_still_runs_similarity_once_then_raises_trending_stage_failed` | a failed trending child still lets similarity run | `except CalledProcessError`: `raise RuntimeError("trending stage failed") from exc` at once | line 881 `len(similarity_at) == 1`: events end at the trending child | yes (6 trending tests passed) |
| F1 | `test_frontend_feed_params.py::test_a_legacy_hot_from_the_url_or_a_stored_mode_object_requests_trending_and_a_bare_hot_string_does_not` | `hot` reads as trending | `parseFeedMode`: `const name = raw` | `got[0] == ["trending"]`: `['recommendations']` | yes |
| F2 | same test (lifted-in bare-string row) | the alias applies only inside the stored object | `readStoredFeedParams`: `if (parsed === "hot") return { mode: parseFeedMode(parsed) }` | `got[4] == ["recommendations"]`: `['trending']` | yes |
| F3 | `test_frontend_feed_params.py::test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot` (COMBINE) | the client's modes equal the Engine's | client `FEED_MODES` gained `"hot"` | line 153 equality: client list carries `hot` | yes |
| F4 | same test (lifted-in assertion) | the Engine names trending, not hot | `similar.py` `FEED_MODES` with `"hot"` in place of `"trending"` | line 150: `['recommendations', 'hot', 'recent', 'random', 'popular']` | yes (2 passed) |

R19 onwards were run by the main session after the second harvester run stopped mid-R19 with `random_videos.py` still mutated; it was restored from `random_videos.py.bak-harvest45-r19` (identical to r10-r18 and m10) before R19 was re-applied. Backups for these runs: `delete_me/*.bak-harvest45-{r19,s1,s2,s3,p1,u1..u4,f1..f3}` and `delete_me/similar.py.bak-harvest45-f4`. Every mutated production file was `cmp`-clean against its backup afterwards, and no `.bak` exists under the production tree. The `delete_me/*.bak-harvest45-m*` files are the first run's unrecorded mutations; they carry no evidence.

Gate: every test in a subject file has a recorded mutation felling the assertion it was moved for (the REDUNDANT three stayed out); none was reclassified; the snapshot `tests/last_test_validation.json.preharvest` is on disk.

## Step 7: disposed

All 26 entries moved to `delete_me/` with `mv -n` and a clash check (none clashed): the four `test_45_trending_from_source_instances_phase*.py` checkpoints, `draft_fetch_trending.py`, the 20 `probe_*.py` files (including `probe_step8_seed_timing.py`), and `tests/tmp/__pycache__` as `delete_me/__pycache__-harvest45`. `tests/tmp` is empty. The three emptied active files went there at Step 5.b.

## Step 8: suite

`tests/last_test_validation.json.preharvest` was restored with `mv`, then `./.un/skills/devsecops/scripts/validate_tests.py --compare` ran with no tier: exit 0, 9 of 59 groups selected (50 unchanged), 269 passed, 0 failed, 9 lanes.

- No new red and nothing no longer red.
- Appeared: every moved test in its subject file, the two COMBINE survivors under their new names, `test_similar` `[TRENDING]` and `[hot]` (the operator tidy), and the five `[mode=trending-*]` NSFW cases.
- Gone: the three emptied phase-named files' tests, `test_fetch_trending`'s purge test (moved to `test_moderation.py`), the two COMBINE old names, and `test_similar` `[HOT]` (renamed `TRENDING`).
- `test_static_page_visit_logs.py` re-ran as "changed" because of uncommitted work outside this build; it passed.
- `test_search_fusion.py` still has no map entry (pre-existing, out of scope).
