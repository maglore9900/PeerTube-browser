# Harvest — 09 similars diversity

## Resolved paths (from `--show-config`, bootstrap gate clear: `defaulted` = [], `conflicts` = [])

- project_dir: /home/enduser/code/PeerTube-browser/.worktrees/09
- active: tests/active
- working: tests/tmp
- plans: docs/project/plans
- delete_me: delete_me
- archive: tests/archive
- record: tests/last_test_validation.json
- snapshot: tests/last_test_validation.json.preharvest (taken at Step 1, before any run)

## Scope (named by the build)

- tests/tmp/test_09_similars_diversity_phase1.py
- tests/tmp/test_09_similars_diversity_phase2.py
- tests/tmp/test_09_similars_diversity_phase3.py
- tests/tmp/test_09_similars_diversity_phase4.py

The probe_09_* / probe_3x_* files in tests/tmp are not in this scope and are left untouched.

## Inventory (Step 2)

### tests/tmp/test_09_similars_diversity_phase1.py
- Drives: engine/server/api/server_config.py (loaded from file) and engine/server/api/server.py (startup `upnext_config` log line, session `engine` fixture plus one variant Engine start).
- Tests: `test_the_engine_holds_and_logs_the_upnext_constants_at_their_defaults`.
- Depends on: conftest `ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, ROOT, _free_port, engine`; module constants SERVER_CONFIG, UPNEXT_PREFIX, NPROBE_PREFIX, LOG_WAIT_SECONDS, VARIANT_START_SECONDS, HOME_BATCH_SIZE_LITERAL, EXPECTED_DEFAULTS, EXPECTED_LOG_TOKENS, VARIANT_OVERRIDES, VARIANT_LOG_TOKENS, VARIANT_RUNNER; helpers _load, _payloads, _messages, _tokens, _has_started, _start_variant.

### tests/tmp/test_09_similars_diversity_phase2.py
- Drives: engine/server/api/handlers/similar.py up-next route → engine/server/data/similarity_candidates.py `get_upnext_candidates` and engine/server/data/ann.py `search_similar_above`.
- Tests: `test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux|cooking]`, `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`.
- Depends on: conftest `ENGINE_PY, ROOT, dataset, embedding_of, engine`; constants SERVER_DIR, SERVER_CONFIG, SHORT_SEED_QUERIES, FILL_LIMIT, PAGE_LIMIT, SEARCH_PATH, SEARCH_ROWS, FALLBACK_PREFIX, NPROBE_PREFIX, LOG_WAIT_SECONDS, VECTOR_QUERY, VECTOR_LIMIT, UNSET_NPROBE, ANN_CHILD; helpers _config, _seed, _cache_entry, _messages, _tokens, _keys, _nprobe_steps, _vector_page, _ann_pages.

### tests/tmp/test_09_similars_diversity_phase3.py
- Drives: engine/server/api/handlers/similar.py `_draw_page` / `seed` parameter.
- Tests: `test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor`.
- Depends on: conftest `ROOT, engine`; constants PAGE_LIMIT, REFRESHES, MAX_MEAN_JACCARD, HEADERS (X-Client-IP 192.0.2.109); helpers _config, _seed, _page, _keys, _mean_jaccard.

### tests/tmp/test_09_similars_diversity_phase4.py
- Drives: engine/server/api/handlers/similar.py (`_draw_weight`, `_log_upnext_pool`) and engine/server/api/recommendations/related_personalization.py (`personalized_score` stamp).
- Tests: `test_upnext_with_and_without_likes_both_diversify_and_liked_rows_stay_above_the_floor`, `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default`, `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored`.
- Depends on: conftest `BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, ROOT, ClientBackend, _free_port, engine`; fixture off_default_engine; constants LIKES_HEADERS/POOL_HEADERS (192.0.2.140/141), SERVER_PREFIX, NPROBE_PREFIX, FALLBACK_PREFIX, PROFILE_PREFIX, POOL_LINE, START_LINE, STEPS, OFF_DEFAULT_NPROBE, LAUNCH; helpers _config, _search, _messages, _tokens, _keys, _mean_jaccard, _nprobe_steps, _pool_lines, _requests, _pools_with_fallbacks, _steps, _searched.

All four files collected and gated during the build; none is unclassifiable.

## Classification (Step 3)

The subject files in `active` for these scripts are test_server_config.py (server_config.py, server.py) and test_similar.py (handlers/similar.py). Neither asserts the upnext constants, the upnext_config / ann_fallback / upnext_pool lines, the fallback pool fill, the cache staying unwritten, the nprobe restore, the weighted draw or the seeded draw; the build's earlier up-next assertions were retired to tests/archive/upnext_random_draw/ at Step 8.

### test_the_engine_holds_and_logs_the_upnext_constants_at_their_defaults
DURABLE → tests/active/test_server_config.py. Nothing in active asserts the SIMILAR_VIDEO_* defaults or the startup upnext_config line.

### test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged
DURABLE → tests/active/test_similar.py. No active test asserts a short-cached seed fills a full up-next page or that up-next leaves similarity-cache.db unwritten.

### test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored
DURABLE → tests/active/test_similar.py. No active test asserts the shared index's nprobe is restored after an up-next fallback. Not redundant with phase 4's pool-line test: this one reads the index itself (raw-vector page) and search/home, phase 4 reads the upnext_pool line.

### test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor
DURABLE → tests/active/test_similar.py. No active test asserts up-next pages vary across refreshes or that `seed` reproduces a page.

### test_upnext_with_and_without_likes_both_diversify_and_liked_rows_stay_above_the_floor
DURABLE → tests/active/test_similar.py. No active test asserts the likes-weighted draw diversifies, stays above the tail floor, or logs likes_rerank.

### test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default
DURABLE → tests/active/test_similar.py. No active test asserts the upnext_pool line's steps and restored_nprobe.

### test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored
DURABLE → tests/active/test_similar.py. The only assertion that separates relaying the read-back from printing DEFAULT_NPROBE.

Counts: DURABLE 7, REPLACES 0, COMBINE 0, REDUNDANT 0, SPENT 0. No active test retired. No subject file created.

Proposed test_groups change: test_similar.py gains engine/server/data/similarity_candidates.py, engine/server/data/ann.py, engine/server/api/recommendations/related_personalization.py. test_server_config.py already claims server_config.py and server.py.

## Approval (Step 4)

Pending.
