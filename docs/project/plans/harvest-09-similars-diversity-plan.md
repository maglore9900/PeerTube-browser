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

## Resumed on main (after merging 09)

The worktree harvest above stopped at Step 4. It is resumed here on main.

- **Paths:** `project_dir` is `/home/enduser/code/PeerTube-browser`. Every other path is unchanged. `--show-config` shows `defaulted` = [] and `conflicts` = [].
- **Snapshot:** the worktree's `.preharvest` came in with the merge and was moved to `delete_me/worktree09-last_test_validation.json.preharvest`. A fresh `tests/last_test_validation.json.preharvest` was taken on main, byte-identical to the record (`cmp`), before any run.
- **Scope:** the same four `test_09_*` files.
- **Classification re-checked against main's `tests/active`:** main now also holds the 10/11 harvest files `test_video.py`, `test_whitelist_migrations.py` and `test_frontend_video_page.py`. A grep of `tests/active` for `upnext_config`, `upnext_pool`, `ann_fallback`, `restored_nprobe`, `SIMILAR_VIDEO_TARGET_MIN_POOL`, `likes_rerank`, `similarity-cache`, `_draw_page` and `seed=` finds nothing. All seven DURABLE verdicts stand, with the destinations above.
- **Additional map change:** 09 moved `tests/active/test_frontend_videos.py` to `tests/archive/upnext_random_draw/`. Its `test_groups` entry is still present, and `map_health` reports it as an unknown group, so the entry is dropped (the Step 5.b rule for a file moved out whole).
- **Pre-existing, not changed here:** `test_search_fusion.py` has no `test_groups` entry.
- **Step 4:** approved by the operator on main, verdicts and map changes as listed.
- **Probes:** the 18 `probe_09_*.py` files in `tests/tmp` are out of scope by rule. The operator asked for probes to go to `delete_me/`, so Step 7 moves them too (`mv -n`).

## Carried out on main

### Step 5: apply

- `tests/active/test_server_config.py` gained `test_the_engine_holds_and_logs_the_upnext_constants_at_their_defaults` with its constants (SERVER_CONFIG, UPNEXT_PREFIX, NPROBE_PREFIX, LOG_WAIT_SECONDS, VARIANT_START_SECONDS, HOME_BATCH_SIZE_LITERAL, EXPECTED_DEFAULTS, EXPECTED_LOG_TOKENS, VARIANT_OVERRIDES, VARIANT_LOG_TOKENS, VARIANT_RUNNER) and helpers (_load, _payloads, _messages, _tokens, _has_started, _start_variant). It reuses the file's API_DIR and conftest's ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, ROOT, _free_port and the `engine` fixture. The phase's module docstring is now a block of the subject file's module docstring.
- `tests/active/test_similar.py` gained the six phase 2-4 tests: `test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux|cooking]`, `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`, `test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor`, `test_upnext_with_and_without_likes_both_diversify_and_liked_rows_stay_above_the_floor`, `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default`, `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored`, plus the `off_default_engine` fixture.
- Reuse in test_similar.py: the existing SERVER_DIR, UPNEXT_PAGE (8, the phases' PAGE_LIMIT) and `_upnext_path` (phase 3's path is `_upnext_path(engine, "linux") + "&debug=1"`, the same URL it built); conftest's `engine`, `dataset`, `embedding_of`, BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, ClientBackend, _free_port. The helpers the three phase files duplicated (_config, _messages, _tokens, _keys, _nprobe_steps, _mean_jaccard) are carried once; phase 2/3's `_seed` is `_search(engine, q, 1)[0]`. To avoid clashing with names already in the file, phase 2's PAGE_LIMIT=30 became SHORT_PAGE_LIMIT, SEARCH_PATH/SEARCH_ROWS became FALLBACK_SEARCH_PATH/FALLBACK_SEARCH_ROWS, and phase 3's HEADERS became DRAW_HEADERS (same 192.0.2.109 bucket).
- Docstrings and comments: the three phase module docstrings are now blocks of the subject module docstring. "R2's ladder" became "the fallback ladder", "before this phase" became "without the fallback", "(probe)" became "(observed)", phase 1's "C1 is a claim about these values (R1, R5), so the operator kept them as literals over hardcoded-spec-mirror" became "The defaults are the claim, so they stay literals". The `# C1`/`# C2` clause tags were dropped. No assertion was changed.
- Nothing retired (0 REPLACES, 0 COMBINE), so nothing went to tests/archive/.
- `test_groups`: `test_similar.py` gained `engine/server/data/similarity_candidates.py`, `engine/server/data/ann.py`, `engine/server/api/recommendations/related_personalization.py`; the `test_frontend_videos.py` entry was dropped. `test_search_fusion.py` stays unmapped (pre-existing).
- `--audit-map`: exit 0. Its one MISSING finding against a moved test, `test_similar.py engine.log`, is the fixture's `tmp_path / "engine.log"` file name, not the repo's engine.log; not a subject, not added.

### Step 6: mutations

Snapshot confirmed on disk and `cmp`-identical to the record before the first run. Each backup went to `delete_me/harvest-09-bak/mNN.<file>.bak` (never in the production tree), each mutation and restore was followed by `sleep 1` + `touch`, each run was a solo `validate_tests.py <file> -k <test>`, one call at a time.

#### test_the_engine_holds_and_logs_the_upnext_constants_at_their_defaults
M01, `engine/server/api/server.py`: the upnext_config log call passed SIMILAR_VIDEO_NPROBE in the SIMILAR_VIDEO_MAX_NPROBE slot. Red at `assert _tokens(message) == sorted(EXPECTED_LOG_TOKENS.items())`: `('SIMILAR_VIDEO_MAX_NPROBE', '32') != ('SIMILAR_VIDEO_MAX_NPROBE', '128')`. Restored, diff clean, green (1 passed).

#### test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux|cooking]
M02, `engine/server/data/similarity_candidates.py`: the fallback guard `if len(rows) < policy.target_min_pool or not cache_hit:` became `if False:`. Both ids red at `assert len(rows) == limit`: `('linux', 48, 18)` and `('cooking', 48, 17)`. Restored, diff clean, green (2 passed).

#### test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored
M03, `engine/server/data/ann.py`: the nprobe restore in `search_similar_above`'s finally was skipped (`if previous is not None:` became `if False:`). Red at the restored_nprobe assertion: `ann_fallback nprobe=32 ... restored_nprobe=32` against DEFAULT_NPROBE 24. Restored, diff clean, green (1 passed).

#### test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor
M04, `engine/server/api/handlers/similar.py`: `_draw_page` returned the ranked window's first `limit` rows (a fixed top-8, no draw). Red at `assert mean < MAX_MEAN_JACCARD`: mean 1.0. Restored, diff clean, green (1 passed).

#### test_upnext_with_and_without_likes_both_diversify_and_liked_rows_stay_above_the_floor
M05, `engine/server/api/handlers/similar.py`: after the likes rerank, a stamped window was cut to its top `limit` before the draw. The likes-resolved controls and the floor held; red at `assert liked_mean < MAX_MEAN_JACCARD`: liked_mean 1.0. Restored, diff clean, green (1 passed).

#### test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default
M06, `engine/server/api/handlers/similar.py`: `_log_upnext_pool` wrote `steps = "none"` whatever the request searched. Red at `assert _steps(line) == _searched(fallbacks)`: `[] == [(32, 5000)]`. Restored, diff clean, green (1 passed).

#### test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored
M07, `engine/server/api/handlers/similar.py`: `_log_upnext_pool` printed server_config.DEFAULT_NPROBE as restored_nprobe whenever steps ran, instead of the read-back. The off-default Engine started, its controls and the steps assertion held; red at the restored_nprobe relay assertion: `'24' == '16'`. Restored, diff clean, green (1 passed).

No test reclassified. After M07 every mutated file was `cmp`-identical to its first backup (server.py = m01, similarity_candidates.py = m02, ann.py = m03, similar.py = m04..m07), and `find` found no `.bak` under engine/, client/, src/ or scripts/. The seven backups stay in `delete_me/harvest-09-bak/`.

### Step 7: disposal

Checked `delete_me/` for collisions first; there were none, so every file kept its name. Moved with `mv -n`:
- `tests/tmp/test_09_similars_diversity_phase1.py` .. `phase4.py` (4 files, the scope) to `delete_me/`.
- The 18 `tests/tmp/probe_09_*.py` files (operator's instruction): engine_log, phase2, phase2_debug, phase2_limits, phase2_nprobe, phase2_pool, phase2_rawvec, phase2_sensitive, phase2_shapes, phase3, phase4, phase4_impl, phase4_nofallback, phase4_offdefault, step8_blocks_vacuity, step8_home_pair, variant, variant_start, to `delete_me/`.
`tests/tmp` now holds only `__pycache__`.

### Step 8: suite and bank

`mv tests/last_test_validation.json.preharvest tests/last_test_validation.json`, then `./.un/skills/devsecops/scripts/validate_tests.py --compare`. It selected 10 of 25 groups (9 changed plus the unmapped test_search_fusion.py); 158 passed, 0 failed, 37.8 s wall. The banked record's whole-suite summary: 264 passed, 0 failed.

- Appeared: exactly the 8 harvested ids (1 in test_server_config, 7 in test_similar counting both parametrizations).
- New red: none. No longer red: none.
- Gone: 17 ids, none of them retired by this harvest. They are build 09's own Step 8 retirements, which reached main with the merge: the up-next cases of test_blocks (4: `test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it[×2]`, `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page[/recommendations|/videos/similar]`, whose active version is now parametrized on `search` only), test_dislike_profile (4), test_dislikes (8) and test_frontend_blocks (1). All seven functions are in `tests/archive/upnext_random_draw/`. Those files have the merge's mtime (23:14:47), before the snapshot (23:17). The pre-harvest record still carried the old ids because none of those four groups had run on main since the merge.
- Count check: 264 = pre-harvest total + 8 appeared − 17 gone, so the pre-harvest record held 273.
