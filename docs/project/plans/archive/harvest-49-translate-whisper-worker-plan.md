# Harvest: plan 49 translate whisper worker

## Step 1: resolved paths and scope

Bootstrap gate: clear (`defaulted` is `[]`, `conflicts` is `[]`), from `./.un/skills/devsecops/scripts/validate_tests.py --show-config`.

- project_dir: `/home/enduser/code/PeerTube-browser/`
- source (group map): `/home/enduser/code/PeerTube-browser/tests/config.json`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- HARVEST_FILE: `docs/project/plans/harvest-49-translate-whisper-worker-plan.md`

Record snapshot: `tests/last_test_validation.json` existed and was copied to `tests/last_test_validation.json.preharvest` (155610 bytes, `cmp`-identical) before anything else ran.

Scope: the four tests this build wrote, as named by the build dispatch, not by a whole-tree sweep:

- `tests/tmp/test_49_translate_whisper_worker_phase1.py`
- `tests/tmp/test_49_translate_whisper_worker_phase2.py`
- `tests/tmp/test_49_translate_whisper_worker_phase3.py`
- `tests/tmp/test_49_translate_whisper_worker_phase4.py`

Out of scope but present in `tests/tmp`: `probe_49_phase2_resolution.py`, `probe_barrier.py`, `probe_green.py`, `probe_phase2_enqueue.py`, `probe_phase2_worker_cli.py`, `probe_phase3_clip.py`, `probe_phase3_instance_redirect.py`, `probe_phase3_rig.py`, `probe_phase3_run_job.py`, `probe_phase4_cuda_libs.py`, `probe_phase4_drive.py`, `probe_phase4_fw.py`, `probe_phase4_harness.py`, `probe_phase4_stall.py`, `probe_race.py`, `probe_subtitles_race.py`, `probe_wal_env.py`, `probe_wal_switch.py`, and `__pycache__/`. None is a `test_*.py`, so none is collected. The phase reports ask for these probes to be deleted. Step 7 moves only the four files in scope, so `tests/tmp` will not be empty afterwards unless the operator widens the disposal to the probes.

Collection: all four files collect, 55 test items in total (`pytest --collect-only`). None needed a `validate_tests.py <path>` run to diagnose a collection failure.

## Step 2: inventory

### tests/tmp/test_49_translate_whisper_worker_phase1.py

Drives `engine/server/data/subtitles.py`. The upgrade test calls the store functions in-process. The two concurrent tests run explicit `-c` scripts under `ENGINE_PY` (engine/.pixi), released together from a file barrier.

Module-level dependencies: `ROOT`/`ENGINE_PY`/`SERVER_DIR` sys.path setup; constants `B1_CREATE`, `B1_COLUMNS`, `JOB_COLUMN_NAMES`, `ALL_COLUMNS`, `B1_ROWS`, `B1_CUES`, `UPGRADE_ROUNDS` (24), `WRITE_SECONDS` (5.0), `BEAT_BASE`, `ENGINE_HOST`, `WORKER_HOST`; scripts `UPGRADE_SCRIPT`, `ENGINE_SCRIPT`, `WORKER_SCRIPT`; helpers `_b1_file`, `_plain`, `_old_cues`, `_run_together`.

Tests:
- `test_a_b1_file_upgrades_in_place_to_wal_with_the_job_columns_and_reads_its_old_cues_unchanged`
- `test_two_upgraders_racing_on_one_b1_file_both_succeed_and_leave_one_set_of_job_columns` (24 rounds in one test)
- `test_an_engine_and_a_worker_writing_one_file_at_once_never_hit_a_lock_and_leave_every_row_ready_with_its_own_cues`

### tests/tmp/test_49_translate_whisper_worker_phase2.py

Drives two files:
- `engine/server/db/jobs/translate-worker.py enqueue`, run as a subprocess under `ENGINE_PY` against a tmp whitelist.db and subtitles.db;
- `engine/server/data/subtitles.py`, where `claim_translate_job` and `recover_translate_jobs` are called in-process.

Module-level dependencies: `ROOT`/`ENGINE_PY`/`SERVER_DIR`/`WORKER` sys.path setup (server and api dirs); constants `HOST`, `DENIED_HOST`, `PEER_VIDEO`, `SECOND_VIDEO`, `DENIED_VIDEO`, `LONG_VIDEO`, `AT_MAX_VIDEO`, `EXIT_QUEUED`/`EXIT_EXISTS`/`EXIT_CAP`/`EXIT_REFUSED`, `QUEUE_CAP` (50), `RECOVERY_TEXT`, `PRESENT`, `REFUSALS`, `CONTROL_KEYS`; helpers `_whitelist` (five videos with stored durations), `_subtitles`, `_insert`, `_snapshot`, `_rows`, `_enqueue`, `_leads`; fixture `dbs`.

Tests:
- `test_enqueue_by_uuid_and_unnormalised_host_queues_one_whisper_row_under_the_canonical_key`
- `test_a_key_already_present_in_any_state_is_reported_with_that_state_and_left_untouched` (6 params)
- `test_enqueue_at_the_queue_cap_is_refused_and_writes_nothing`
- `test_a_refused_video_exits_5_naming_its_reason_and_writes_no_row` (5 params)
- `test_claim_hands_out_queued_jobs_oldest_first_each_running_with_its_started_at_and_one_more_attempt` (subtitles.py)
- `test_recovery_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time` (subtitles.py)

### tests/tmp/test_49_translate_whisper_worker_phase3.py

Drives `engine/server/db/jobs/translate-worker.py`:
- `run_job`, called in-process on a job enqueued and claimed through the store's own functions;
- `pick_media_url`, called directly.

The instance is a `ScriptedHost` patched over `handlers.internal_translate.build_opener`, and the media host a second one patched over the worker's own `build_opener`. ffmpeg is real (`pytest.fail` if it is missing), and a stub runner stands in for Whisper/VAD.

Module-level dependencies: `ROOT`/`SERVER_DIR`/`WORKER` sys.path setup; constants `HOST`, `DENIED_HOST`, `PEER_VIDEO`, `DENIED_VIDEO`, the URLs (`CAPTIONS_URL`, `VIDEO_URL`, `TRACK_PATH`, `TRACK_URL`, `INSTANCE_THEN_JSON`, `MEDIA_HOST`, `MEDIA_URL`, `SAME_HOST_TARGET`, `OFF_HOST_TARGET`, `OFF_DOMAIN_VIDEO_URL`, `SAME_DOMAIN_VIDEO_URL`), `MEDIA_FILE`, `SAMPLE_RATE`, `CHUNK`, `MAX_DURATION`, `QUEUED_AT`, `STARTED_AT`, `CLIP_SOURCE`, `EN_LISTING`, `TRACK`, `CUES`, `CHUNK_1`, `CHUNK_3`, `OOM`, `REFUSED_FILES`, `BOUNDS`, `PICKS`; helpers `_video`, `_socket_handler`, `_worker`, `_whitelist` (two videos, NULL durations), `_now_ms`, `_leads`; classes `Response`, `ScriptedHost`, `Rig`, `StubRunner`; fixtures `clip` (module scope, ffmpeg lavfi WAV) and `rig`.

Tests:
- `test_a_job_breaking_a_bound_ends_failed_with_that_bounds_text_and_requests_nothing_after_the_refusal` (19 params)
- `test_a_media_redirect_that_stays_on_the_media_host_is_followed`
- `test_a_video_json_redirect_that_stays_on_the_instance_domain_is_followed`
- `test_pick_media_url_takes_the_smallest_file_and_sorts_unknown_sizes_last` (4 params)
- `test_a_transcribed_job_rewrites_the_running_cues_after_each_speech_chunk_skips_silence_and_ends_ready_with_absolute_ms_times`
- `test_english_detected_on_the_first_chunk_ends_already_english_without_ever_writing_cues`
- `test_audio_with_no_speech_ends_failed_no_speech_detected_without_transcribing`
- `test_a_cuda_out_of_memory_ends_failed_with_its_text_and_unloads_the_model_once`
- `test_an_english_instance_track_ends_ready_instance_with_finished_at_and_no_media_fetch`
- `test_a_b1_takeover_mid_job_leaves_the_ready_instance_row_untouched`
- `test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept`

### tests/tmp/test_49_translate_whisper_worker_phase4.py

Drives `engine/server/db/jobs/translate-worker.py run`:
- as a subprocess under `ENGINE_PY`;
- through a `-c` `STALL_DRIVER` that lowers `STALL_SECONDS` and calls `main()`;
- in-process, through `heartbeat_loop`.

Module-level dependencies: `ROOT`/`ENGINE_PY`/`SERVER_DIR`/`WORKER` sys.path setup and top-level imports of `data.moderation`/`data.subtitles`; constants `B1_CREATE`, `B1_COLUMNS`, `B1_ROW`, `STOP_WINDOW_SECONDS`, `BEAT_GAP_MS`, `BEAT_WINDOW_SECONDS`, `FIRST_BEAT_SECONDS`, `STALL_DRIVER`, `TEST_STALL_SECONDS`, `STALLED_WINDOW_SECONDS`, `RESUME_SECONDS`, `STALL_KEY`; helpers `_now_ms`, `_worker`, `_paths`, `_run_argv`, `_require_tools`, `_locked_by_someone`, `_beat`, `_heartbeat_rows`, `_next_beat`, `_jobs`, `_whitelist` (tables, no videos, rollback journal), `_b1_file`, `_sidecars`; fixture `holder`.

Tests:
- `test_run_against_a_held_lock_exits_6_names_the_lock_and_writes_nothing` (2 params)
- `test_idle_run_beats_with_its_pid_every_5_s_and_releases_the_lock_on_sigterm`
- `test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on`
- `test_heartbeat_loop_skips_beats_while_the_main_loop_is_stalled_and_beats_once_it_progresses`

## Step 3: classification

`tests/active` has no subject file for either production script these tests drive: no `test_subtitles.py` and no `test_translate_worker.py`. So no test here can be `REDUNDANT` against `active`, and Step 5 must create both. The only active group touching `data/subtitles.py` is `test_internal_translate.py`. That group's subject is `internal_translate.py`; it opens the store as a fixture, and only `test_an_engine_start_creates_the_subtitles_table_...` asserts anything about the schema: that an Engine start creates the `subtitles` table. Nothing there asserts the upgrade, WAL, the job columns or any job function, and nothing there is made wrong by them. So there is no `REPLACES` and no `COMBINE`.

Destination by script, per Step 5.a ("one script, one test file"): tests that drive `engine/server/data/subtitles.py` go to `tests/active/test_subtitles.py`, and tests that drive `engine/server/db/jobs/translate-worker.py` go to `tests/active/test_translate_worker.py`. The build's phase notes named `test_translate_worker.py` for everything; the two store-level phase-2 tests and all of phase 1 drive `subtitles.py`, not the worker, so they go to `test_subtitles.py`.

### tests/tmp/test_49_translate_whisper_worker_phase1.py

- `test_a_b1_file_upgrades_in_place_to_wal_with_the_job_columns_and_reads_its_old_cues_unchanged`: **DURABLE** → `tests/active/test_subtitles.py`. The in-place B1 upgrade (job columns, index, heartbeat table, WAL, old rows and cues unchanged, mode=ro readable) is asserted nowhere in active.
- `test_two_upgraders_racing_on_one_b1_file_both_succeed_and_leave_one_set_of_job_columns`: **DURABLE** → `tests/active/test_subtitles.py`. The only gate on the single-IMMEDIATE-transaction upgrade and the WAL-switch retry under concurrent openers.
- `test_an_engine_and_a_worker_writing_one_file_at_once_never_hit_a_lock_and_leave_every_row_ready_with_its_own_cues`: **DURABLE** → `tests/active/test_subtitles.py`. Risk R8 (no "database is locked" with two writers, consistent rows, heartbeat upsert) is asserted nowhere in active.

### tests/tmp/test_49_translate_whisper_worker_phase2.py

- `test_enqueue_by_uuid_and_unnormalised_host_queues_one_whisper_row_under_the_canonical_key`: **DURABLE** → `tests/active/test_translate_worker.py`. Enqueue under the canonical key, with exit 0 and its line; there is no worker test in active.
- `test_a_key_already_present_in_any_state_is_reported_with_that_state_and_left_untouched`: **DURABLE** → `tests/active/test_translate_worker.py`. Exit 3 per state, and existing rows are never overwritten (B1 ready/instance included).
- `test_enqueue_at_the_queue_cap_is_refused_and_writes_nothing`: **DURABLE** → `tests/active/test_translate_worker.py`. Exit 4 at the default cap, and only queued rows count toward it.
- `test_a_refused_video_exits_5_naming_its_reason_and_writes_no_row`: **DURABLE** → `tests/active/test_translate_worker.py`. Exit 5 with a reason for whitelist, denylist, stored duration and empty host. This is the enqueue command's own gate, distinct from the `/internal/translate` handler gate that `test_internal_translate.py` asserts.
- `test_claim_hands_out_queued_jobs_oldest_first_each_running_with_its_started_at_and_one_more_attempt`: **DURABLE** → `tests/active/test_subtitles.py`. Claim order by queued_at, the running transition and attempts+1 are asserted nowhere else. (Phase 1's worker script only claims a single queued key.)
- `test_recovery_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time`: **DURABLE** → `tests/active/test_subtitles.py`. The only test of `recover_translate_jobs`, its one-retry rule and `RECOVERY_ERROR`.

### tests/tmp/test_49_translate_whisper_worker_phase3.py

All of these drive `run_job` or `pick_media_url` in `translate-worker.py`, and active has no worker test.

- `test_a_job_breaking_a_bound_ends_failed_with_that_bounds_text_and_requests_nothing_after_the_refusal`: **DURABLE** → `tests/active/test_translate_worker.py`. Every AC5 bound at the worker's own seam. `test_internal_translate.py` asserts `fetch_bounded`/`SameHostRedirectHandler` in isolation; it does not assert that the worker routes the video JSON and the media through them, nor the worker-only bounds (JSON duration, media URL acceptance, media bytes, decoded duration).
- `test_a_media_redirect_that_stays_on_the_media_host_is_followed`: **DURABLE** → `tests/active/test_translate_worker.py`. `AudioPipe` follows a same-host media redirect, which is the worker's own opener. Without this test, a worker refusing every redirect would pass the off-host bound.
- `test_a_video_json_redirect_that_stays_on_the_instance_domain_is_followed`: **DURABLE** → `tests/active/test_translate_worker.py`. The same reasoning applies to the video JSON fetch in `generate`. Active asserts that `fetch_bounded` follows the redirect, not that the worker keeps it working.
- `test_pick_media_url_takes_the_smallest_file_and_sorts_unknown_sizes_last`: **DURABLE** → `tests/active/test_translate_worker.py`. Asserts the smallest-file pick across both lists and that unknown sizes sort last.
- `test_a_transcribed_job_rewrites_the_running_cues_after_each_speech_chunk_skips_silence_and_ends_ready_with_absolute_ms_times`: **DURABLE** → `tests/active/test_translate_worker.py`. Per-chunk cue rewrite, absolute ms times, no transcribe call on silence, and ending ready/whisper.
- `test_english_detected_on_the_first_chunk_ends_already_english_without_ever_writing_cues`: **DURABLE** → `tests/active/test_translate_worker.py`. The already_english end state, with no cue write.
- `test_audio_with_no_speech_ends_failed_no_speech_detected_without_transcribing`: **DURABLE** → `tests/active/test_translate_worker.py`. The no-speech end state.
- `test_a_cuda_out_of_memory_ends_failed_with_its_text_and_unloads_the_model_once`: **DURABLE** → `tests/active/test_translate_worker.py`. On out-of-memory the job is failed and the model is unloaded once.
- `test_an_english_instance_track_ends_ready_instance_with_finished_at_and_no_media_fetch`: **DURABLE** → `tests/active/test_translate_worker.py`. The instance-track short-circuit inside the worker, plus `mark_translate_finished`.
- `test_a_b1_takeover_mid_job_leaves_the_ready_instance_row_untouched`: **DURABLE** → `tests/active/test_translate_worker.py`. A takeover leads to no write and the job stops.
- `test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept`: **DURABLE** → `tests/active/test_translate_worker.py`. On stop the job is requeued, with attempts restored and queued_at kept.

### tests/tmp/test_49_translate_whisper_worker_phase4.py

- `test_run_against_a_held_lock_exits_6_names_the_lock_and_writes_nothing`: **DURABLE** → `tests/active/test_translate_worker.py`. The single-instance flock gives exit 6, takes effect before the store is opened, and writes nothing.
- `test_idle_run_beats_with_its_pid_every_5_s_and_releases_the_lock_on_sigterm`: **DURABLE** → `tests/active/test_translate_worker.py`. The idle heartbeat cadence and pid, and a clean SIGTERM exit that releases the lock.
- `test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on`: **DURABLE** → `tests/active/test_translate_worker.py`. The stall guard through the real `run`: `serve` refreshes `progress`, and `heartbeat_loop` withholds beats while the main loop is stuck and resumes after it moves on.
- `test_heartbeat_loop_skips_beats_while_the_main_loop_is_stalled_and_beats_once_it_progresses`: **REDUNDANT**, staying out. It asserts the same stall-guard behaviour as the test above (no beat past `STALL_SECONDS`, a beat once `progress['at']` is refreshed), but on `heartbeat_loop` alone. The test above drives the real producer, with the real main loop stalled, so it is the one kept (Step 3: of two in-scope tests asserting one behaviour, keep the one driving the real producer). By reading, not yet by mutation: breaking the threshold check in `heartbeat_loop` should also fail the subprocess test, which reads the same module-global `STALL_SECONDS`, lowered by its driver. Step 6's mutation of that test is what will confirm this.

## Step 4: harvest plan

Counts (test functions; parametrised cases in brackets): **DURABLE 23** (54 items), **REPLACES 0**, **COMBINE 0**, **REDUNDANT 1** (1 item), **SPENT 0**. Total 24 functions, 55 items.

New subject files Step 5 creates (each is a new group and a new map entry):
- `tests/active/test_subtitles.py` (5 tests): phase 1's three tests and phase 2's claim and recovery tests. It carries copies of `B1_CREATE`, `B1_COLUMNS`, `JOB_COLUMN_NAMES`, `ALL_COLUMNS`, `B1_ROWS`, `B1_CUES`, the three subprocess scripts, `_b1_file`, `_plain`, `_old_cues`, `_run_together`, and phase 2's `_subtitles`, `_insert`, `_snapshot` and the `PRESENT["B1 ready/instance"]` row.
- `tests/active/test_translate_worker.py` (18 tests): phase 2's four enqueue tests, all eleven of phase 3's tests, and three of phase 4's four tests. It needs one `_whitelist` builder covering the three variants. Phase 2's has five videos with durations, and phase 3's has v-1/d-1 with NULL durations; both have the deny row. Phase 4's has no videos and no deny row, in a rollback journal. The builder takes the video set (phase 3's PEER_VIDEO/DENIED_VIDEO keys are a subset of phase 2's, but phase 3's durations are NULL and phase 2's v-1 is 600). It also carries copies of `B1_CREATE`/`B1_COLUMNS`/`B1_ROW`/`_b1_file`; these fixtures are copied, not shared with `test_subtitles.py`. One `_worker()` loader, one `_now_ms`, and one `ENGINE_PY`/`WORKER` setup replace the duplicates. Phase 2's `_leads(lines, prefix)` and phase 3's `_leads(error, text)` differ, so one is renamed.

Docstrings: every module and test docstring that names "plan 49 phase N" is rewritten to state the rule it gates.

Active tests retired: **none** (no `REPLACES` or `COMBINE`). Nothing moves to `tests/archive/`.

`test_groups` changes in `tests/config.json`:
- add `"test_subtitles.py": ["engine/server/data/subtitles.py"]`;
- add `"test_translate_worker.py": ["engine/server/db/jobs/translate-worker.py", "engine/server/data/subtitles.py", "engine/server/api/handlers/internal_translate.py", "engine/server/api/handlers/video.py", "engine/server/data/moderation.py", "engine/server/api/server_config.py"]`. These are the worker, its store, B1's fetch/redirect/instance-track code whose bounds the run_job tests assert, `fetch_video_row` and `normalize_host`/denylist (the whitelist, denied-host and canonical-key outcomes), and the default `SUBTITLE_QUEUE_CAP` the cap test relies on;
- every existing entry stays unchanged (`test_internal_translate.py` already claims `subtitles.py`).

Step 5.c's `--suggest-map`/`--audit-map` may argue for `engine/server/data/db.py` (`connect_readonly_db`) or `engine/server/data/time.py` (`now_ms`; the enqueue test asserts queued_at is wall-clock ms) on `test_translate_worker.py`. They are left out unless the audit flags them.

Mutation cost: Step 6 mutates `subtitles.py` 5 times and `translate-worker.py` 18 times. The phase-4 subprocess tests take about 15–40 s each, so Step 6 takes several minutes.

Stays out (moves to `delete_me/` with its file at Step 7): `test_heartbeat_loop_skips_beats_while_the_main_loop_is_stalled_and_beats_once_it_progresses` (REDUNDANT).

Step 7 disposes only the four files in scope. The 18 probe files in `tests/tmp` listed in Step 1 are outside this harvest's scope, so `tests/tmp` will not be empty afterwards unless the operator widens the disposal to them.

Approval: per this build's dispatch, no operator approval is sought at this step; a second turn carries the plan out.

Approval (Step 10 turn): the plan was put to the operator with AskUser before anything moved, and the operator answered "Approve as written" (probes stay in `tests/tmp`).

## Step 5: applied

- `tests/active/test_subtitles.py` (new, 5 tests, 5 items): phase 1's three tests and phase 2's claim and recovery tests, with the fixtures listed in Step 4 copied in. Phase 2's `PRESENT["B1 ready/instance"]` row is carried as `B1_READY_INSTANCE`. The `# C1`/`# C2` markers were dropped, and the "plan 49 phase N" docstrings were rewritten to the rules they gate.
- `tests/active/test_translate_worker.py` (new, 18 tests, 49 items): phase 2's four enqueue tests, phase 3's eleven tests and phase 4's three kept tests. It has one `_whitelist(path, videos, deny)` builder: phase 2 uses `ENQUEUE_VIDEOS` with the deny row, phase 3 uses `JOB_VIDEOS` (NULL durations) with the deny row, and phase 4 passes no videos and no deny row. One `_worker`, `_now_ms`, `ENGINE_PY`/`WORKER` setup and one `B1_CREATE`/`B1_COLUMNS`/`B1_ROW`/`_b1_file` copy. Phase 2's `_leads` became `_one_line_leads` and phase 3's became `_error_leads`.
- Nothing retired; `tests/archive/` untouched.
- `tests/config.json` `test_groups`: added `test_subtitles.py` → `[engine/server/data/subtitles.py]`, and `test_translate_worker.py` → the six planned files plus `engine/server/data/time.py`. `--audit-map` flagged `time.py` as MISSING on the worker group, and that group's enqueue/finished_at assertions read `now_ms` as wall-clock ms. Not added: `engine/server/db/subtitles.db`, flagged on both groups, because it is the repo's default path and no test touches it; and `time.py` on `test_subtitles.py`, because every timestamp there is passed explicitly. `--audit-map` exits 0.
- Both new files ran green before any mutation: 5 passed and 49 passed.

## Step 6: mutations

The snapshot `tests/last_test_validation.json.preharvest` was confirmed on disk before the first run. Each copy was taken as `<file>.bak-harvest49-mNN`, restored with `cp`, proved with `diff` (no output), and moved to `delete_me/`. Each test was re-run green after its restore.

- m01 `test_a_b1_file_upgrades_in_place_...`: subtitles.py `PRAGMA journal_mode=WAL` → `DELETE`. Felled `after ... PRAGMA journal_mode == "wal"` ('delete' == 'wal'). Green after restore.
- m02 `test_two_upgraders_racing_...`: subtitles.py `ensure_subtitles_schema`'s `with _immediate(conn):` → `with conn:`. Felled `failures == []` with "duplicate column name: error". Green after restore.
- m03 `test_an_engine_and_a_worker_writing_...`: subtitles.py `SUBTITLES_BUSY_TIMEOUT_SECONDS = 30.0` → `0.0`. Felled `"database is locked" not in worker_err`. Green after restore.
- m04 `test_claim_hands_out_...oldest_first...`: subtitles.py claim `ORDER BY queued_at, rowid` → `ORDER BY rowid`. Felled the claimed-order assertion ('c' claimed first). Green after restore.
- m05 `test_recovery_requeues_...`: subtitles.py recovery `attempts >= ?` → `attempts > ?`. Felled `recover_translate_jobs(conn, 9500) == (2, 1)` ((3, 0)). Green after restore.
- m06 `test_enqueue_by_uuid_...canonical_key`: worker enqueue under `video_id, host` instead of `row["video_id"], row["instance_domain"]`. Felled the `_rows == [("v-1", ...)]` assertion (row keyed 'u-1'). Green after restore.
- m07 `test_a_key_already_present_...`: worker `return EXIT_EXISTS` → `EXIT_QUEUED`. Felled `returncode == EXIT_EXISTS` in all 6 params (0 == 3). Green after restore.
- m08 `test_enqueue_at_the_queue_cap_...`: worker `--cap` default `SUBTITLE_QUEUE_CAP` → `SUBTITLE_QUEUE_CAP + 1`. Felled `returncode == EXIT_CAP` (0 == 4). Green after restore.
- m09 `test_a_refused_video_exits_5_...`: worker `refused: <reason>` path `return EXIT_REFUSED` → `EXIT_CAP`. Felled `returncode == EXIT_REFUSED` in 4 of 5 params; the empty-host param takes the earlier, unmutated return, as expected. Green after restore.
- m10 `test_a_job_breaking_a_bound_...`: worker `media_host` accepts `http` as well as `https`. Felled `_error_leads(row["error"], "no usable https media file")` for [media URL http]: the worker went on to request the http URL ("media download failed: HTTP Error 404"). Green after restore (19 passed).
- m11 `test_a_media_redirect_that_stays_on_the_media_host_is_followed`: worker `SameHostRedirectHandler(self.host)` → `SameHostRedirectHandler("")`. Felled `(state, source) == ("ready", "whisper")` (failed). Green after restore.
- m12 `test_a_video_json_redirect_that_stays_on_the_instance_domain_is_followed`: internal_translate.py `SameHostRedirectHandler.redirect_request` `if not same_host_https(...)` → `if True:` (every redirect refused). The worker follows the video JSON redirect only through B1's handler, so no translate-worker.py mutation could reach this rule. Felled `(state, source) == ("ready", "whisper")` (failed). Green after restore.
- m13 `test_pick_media_url_...`: worker `min(ranked, ...)` → `max(ranked, ...)`. Felled `pick_media_url(video) == expected` in 3 of 4 params. Green after restore.
- m14 `test_a_transcribed_job_rewrites_...absolute_ms_times`: worker `chunk_cues` `round(offset + start, 3)` → `round(start, 3)`. Felled the `runner.events == [...]` running-cues assertion. Green after restore.
- m15 `test_english_detected_...`: worker `if language == TARGET_LANGUAGE:` → `== "xx"`. Felled the CONTROL `runner.transcribes == 1`, not a named assertion, so the test was treated as unverified.
- m15b, same test: worker writes `store_running_cues` before `finish_translate_already_english`. Felled the named `row["cues_json"] is None`. Green after restore.
- m16 `test_audio_with_no_speech_...`: worker `if not cues:` → `if False:`. Felled `(state, error) == ("failed", "no speech detected")` (('ready', None)). Green after restore.
- m17 `test_a_cuda_out_of_memory_...`: worker `if is_cuda_oom(exc):` → `if False and ...`. Felled `runner.unloads == 1` (0). Green after restore.
- m18 `test_an_english_instance_track_...`: worker `mark_translate_finished(...)` → `pass`. Felled the `finished_at` int-within-run assertion (None). Green after restore.
- m19 `test_a_b1_takeover_mid_job_...`: subtitles.py `_update_claim` drops `AND state = 'running'`. The row's protection from a takeover lives in the store's conditional update, which this group claims. Felled `rig.row() == taken`. Green after restore.
- m20 `test_a_stop_mid_job_requeues_...`: worker `requeue_translate_job(conn, *claim)` → `finish_translate_failed(..., "stopped", ...)`. Felled `(state, attempts, queued_at) == ("queued", 0, 1000)` (('failed', 1, 1000)). Green after restore.
- m21 `test_run_against_a_held_lock_...`: worker `return EXIT_LOCKED` → `EXIT_ERROR`. Felled `returncode == 6` in both params (1 == 6). Green after restore.
- m22 `test_idle_run_beats_...every_5_s...`: worker `HEARTBEAT_SECONDS = 5.0` → `3.0`. Felled the beat-gap assertion ([3000, 3000]). Green after restore.
- m23 `test_run_stops_beating_while_its_main_loop_is_stalled_...`: worker `heartbeat_loop` stall check → `if True:`. Felled `_beat(...) == stalled` (a new beat landed during the stall). Green after restore. This is the threshold mutation Step 4 predicted, so the REDUNDANT `heartbeat_loop` test's behaviour is confirmed covered.

No mutation survived. No test was reclassified. No `.bak` remains under `engine/`. `subtitles.py`, `translate-worker.py` and `internal_translate.py` are each `cmp`-identical to their first pre-mutation copy.

## Step 7: disposed

Moved to `delete_me/`: `test_49_translate_whisper_worker_phase1.py`, `..._phase2.py`, `..._phase3.py` and `..._phase4.py`, with no name collisions. The 24 mutation backups (`*.bak-harvest49-m01` … `m23`, plus `m15b`) are also there. `tests/tmp` holds none of the four. The 18 out-of-scope `probe_*.py` files and `__pycache__/` remain there, as approved.

## Step 8: compare

Restored `tests/last_test_validation.json.preharvest` → `tests/last_test_validation.json` (155610 bytes), then ran `--compare` with no tier. Groups whose digest was unchanged were carried forward from the pre-harvest record; the run re-ran `test_search_fusion.py`, `test_static_page_visit_logs.py`, `test_subtitles.py` (5 passed) and `test_translate_worker.py` (49 passed). Delta against the pre-harvest record: 54 appeared (5 in `test_subtitles`, 49 in `test_translate_worker`, one per harvested item), 0 gone, no new red, no newly green. Banked: the record is now 166230 bytes.
