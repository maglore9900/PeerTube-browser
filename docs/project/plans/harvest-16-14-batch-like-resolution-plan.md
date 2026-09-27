# Harvest: 16-14 batch like resolution

Scope: the four checkpoint files build 16-14 (`docs/project/plans/16-14-batch-like-resolution.md`) wrote, as named by the dispatch.

## Step 1: resolved paths

- project_dir: `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive` (does not exist; nothing is retired, so it is not created)
- record: `tests/last_test_validation.json`
- bootstrap gate: clear (`defaulted` empty, `conflicts` empty, `map_health` clean)

Snapshot: `tests/last_test_validation.json.preharvest` taken before any harvest run (record timestamp 2026-09-27T04:02:35, exit 0, 146 passed, full `tests/active`).

### Scope

- `tests/tmp/test_14_batch_like_resolution_phase1.py`
- `tests/tmp/test_14_batch_like_resolution_phase2.py`
- `tests/tmp/test_14_batch_like_resolution_phase3.py`
- `tests/tmp/test_14_batch_like_resolution_phase4.py`

Not in scope (build-14 probe files, not `test_*.py`, never collected): `probe_14_n4.py`, `probe_14_phase1.py`, `probe_14_phase2.py`, `probe_14_phase3.py`, `probe_14_phase4.py`, `probe_phase1_against_impls.py`, `probe_phase1_metadata.py`, `probe_phase4_cap.py`, `probe_refactor_row_keys.py`. Disposal put to the operator at Step 4.

## Step 2: inventory

All four files collect and pass in `tests/tmp` (20 passed, one validate run).

### tests/tmp/test_14_batch_like_resolution_phase1.py

- Drives: `engine/server/data/metadata.py` (`fetch_metadata_by_uuids`, `fetch_metadata_by_ids`), in-process on a temp SQLite DB.
- Module deps: sys.path for `engine/server` and `engine/server/api`; `HOST`, `OTHER`, `BULK`, `THRESHOLD`, `VIDEO_TEXT`, `VIDEO_INT`, `ROW_KEYS`, `A1`, `B1`, `S2`, `S1`, `S3`, `E1`, `N1`, `A1_OTHER`, `BULK_SIZE`, `BULK_ERRORED`; helpers `_video`, `_row`, `_add`, `_bulk`, `_by_uuids`; fixture `conn`.
- Tests:
  - `test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video`
  - `test_a_uuid_pair_matches_only_its_exact_uuid_and_host`
  - `test_an_empty_uuid_list_gives_nothing_and_runs_no_statement`
  - `test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold`
  - `test_an_errored_video_s_uuid_pair_is_dropped_only_while_a_threshold_is_set`
  - `test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video`
  - `test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary`

### tests/tmp/test_14_batch_like_resolution_phase2.py

- Drives: `engine/server/api/handlers/internal_client_reads.py` (`handle_internal_videos_metadata`, `handle_internal_dislike_centroids`) in an `ENGINE_PY -c` child, through the real `data.metadata` lookups.
- Module deps: `conftest.ENGINE_PY` (via `tests/active` on sys.path); `SERVER_DIR`, `API_DIR`, `HOST`, `THRESHOLD`, `VIDEO_TEXT`, `VIDEO_INT`, `A1`, `B1`, `E1`, `MISSING_ENTRIES`, `NO_ROWS`, `CHILD` script; helpers `_video`, `_row`, `_add`, `_id`, `_uuid`, `_rows`, `_handle`; fixture `db_path`.
- Tests:
  - `test_a_mixed_body_takes_the_lock_once_and_gives_each_video_once_in_first_match_order`
  - `test_an_id_only_body_takes_the_lock_once_and_gives_its_rows_in_entry_order`
  - `test_a_valid_video_id_wins_over_a_video_uuid_and_a_blank_one_falls_back_to_it`
  - `test_repeats_within_and_across_forms_give_one_row_per_video`
  - `test_an_errored_video_s_uuid_entry_is_omitted_only_under_the_threshold`
  - `test_a_body_with_no_entries_list_or_no_valid_entry_is_answered_without_the_lock`
  - `test_centroids_looks_up_only_the_id_entries`

### tests/tmp/test_14_batch_like_resolution_phase3.py

- Drives: `client/backend/server.py` (`_handle_user_profile_likes_from_client`, `_handle_likes_import`) over HTTP, with `lib/engine_api_client.py` (`fetch_metadata_for_entries`), `lib/dislikes.py` (`is_disliked`) and `lib/users_store.py` (`record_like`) on the path.
- Module deps: `conftest` `ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`; `lib.dislikes.write_dislike`, `lib.profiles.resolve_profile`, `lib.users_store.load_liked_keys`; `HOST`, `METADATA`, `A`, `B`, `C`; helpers `_like`, `_entry`, `_serving`, `_client_backend`, `_engine` (recording stand-in Engine).
- Tests:
  - `test_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order`
  - `test_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine`
  - `test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked`

### tests/tmp/test_14_batch_like_resolution_phase4.py

- Drives: `client/backend/server.py` (`MAX_CLIENT_LIKES` and its three readers) over HTTP.
- Module deps: as phase 3 (same `_serving`, `_client_backend`, `_engine`, `_like`, `_entry`), plus `VIDEOS`, `LIKES`, `urlparse`.
- Tests:
  - `test_a_60_like_likes_page_reaches_the_engine_as_its_first_50_and_is_answered_with_their_rows`
  - `test_a_60_like_import_reaches_the_engine_as_its_first_50_and_likes_exactly_those`
  - `test_a_keyless_60_like_recommendations_request_forwards_its_first_50_likes`

## Step 3: classification

Against: no `tests/active/test_metadata.py` and no `tests/active/test_internal_client_reads.py` exist, so nothing from phases 1-2 can be `REDUNDANT`. `test_server.py` (not split) asserts nothing about likes resolution or the likes cap. `test_profiles.py::test_importing_browser_likes_marks_each_imported_video_liked_and_no_other` asserts an import against the live Engine marks the imported videos liked; it does not assert one Engine call, the dislike skip or the cap, so it stays and nothing replaces it. `test_dislike_profile.py` asserts centroids for id entries only, never uuid entries.

### phase1 -> `tests/active/test_metadata.py` (NEW file, new group)

- `test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video`: DURABLE. No test asserts the uuid lookup's row equals the id lookup's.
- `test_a_uuid_pair_matches_only_its_exact_uuid_and_host`: DURABLE. Exact, case-sensitive pair match and unembedded skip on the uuid path are asserted nowhere.
- `test_an_empty_uuid_list_gives_nothing_and_runs_no_statement`: DURABLE. The no-SQL short-circuit is asserted nowhere.
- `test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold`: DURABLE. The lowest-eligible-id rule (C2) is asserted nowhere.
- `test_an_errored_video_s_uuid_pair_is_dropped_only_while_a_threshold_is_set`: DURABLE. Data-layer threshold on a lone video; no subject file to be redundant against.
- `test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video`: DURABLE. Pins the id lookup's 29-key joined row, which only live-Engine tests touch indirectly.
- `test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary`: DURABLE. Chunking across 450 is asserted nowhere.

### phase2 -> `tests/active/test_internal_client_reads.py` (NEW file, new group)

- `test_a_mixed_body_takes_the_lock_once_and_gives_each_video_once_in_first_match_order`: DURABLE. One lock hold and first-match order for mixed entries are asserted nowhere.
- `test_an_id_only_body_takes_the_lock_once_and_gives_its_rows_in_entry_order`: DURABLE. Entry order (not table order) for id-only bodies is asserted nowhere.
- `test_a_valid_video_id_wins_over_a_video_uuid_and_a_blank_one_falls_back_to_it`: DURABLE. Parser precedence and stripping are asserted nowhere.
- `test_repeats_within_and_across_forms_give_one_row_per_video`: DURABLE. Cross-form dedup is asserted nowhere.
- `test_an_errored_video_s_uuid_entry_is_omitted_only_under_the_threshold`: DURABLE. That the handler hands its threshold to the uuid lookup is asserted nowhere.
- `test_a_body_with_no_entries_list_or_no_valid_entry_is_answered_without_the_lock`: DURABLE. The 400 / empty-200 guards without the lock are asserted nowhere.
- `test_centroids_looks_up_only_the_id_entries`: DURABLE. `test_dislike_profile.py` sends id entries only; uuid entries being ignored is asserted nowhere.

### phase3 -> `tests/active/test_server.py` (existing, not split)

- `test_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order`: DURABLE. The single-call likes page is asserted nowhere.
- `test_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine`: DURABLE. The no-Engine early answer is asserted nowhere.
- `test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked`: DURABLE. One call and the dislike skip on import are asserted nowhere; `test_profiles.py`'s live import test stays beside it.

### phase4 -> `tests/active/test_server.py`

- `test_a_60_like_likes_page_reaches_the_engine_as_its_first_50_and_is_answered_with_their_rows`: DURABLE. The 50 cap is asserted nowhere.
- `test_a_60_like_import_reaches_the_engine_as_its_first_50_and_likes_exactly_those`: DURABLE. Same cap, separate reader.
- `test_a_keyless_60_like_recommendations_request_forwards_its_first_50_likes`: DURABLE. Same cap, the proxy-trim reader.

Counts: DURABLE 20, REPLACES 0, COMBINE 0, REDUNDANT 0, SPENT 0. Retired from `active`: none.

### Proposed `test_groups` changes

- add `test_metadata.py`: `engine/server/data/metadata.py`
- add `test_internal_client_reads.py`: `engine/server/api/handlers/internal_client_reads.py`, `engine/server/data/metadata.py`
- `test_server.py`: add `client/backend/lib/engine_api_client.py`, `client/backend/lib/dislikes.py`, `client/backend/lib/users_store.py`

### Fixtures carried

- `test_metadata.py` and `test_internal_client_reads.py` each get their own copy of the table schema and `_video`/`_row`/`_add` helpers (never shared across groups).
- `test_server.py` reuses its existing `_serving`; its `_client_backend(tmp_path, engine_base, rate_limiter)` yields a base URL, so the moved tests get a separate `_likes_client` that yields `conftest.ClientBackend` (needed for `.request` and `.db_path`), plus one `_recording_engine` shared by the phase 3 and 4 tests.
