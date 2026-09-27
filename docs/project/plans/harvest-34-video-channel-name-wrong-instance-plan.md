# Harvest — 34 video channel name wrong instance

## Resolved paths

- project_dir: /home/enduser/code/PeerTube-browser/.worktrees/34
- active: tests/active
- working: tests/tmp
- plans: docs/project/plans
- delete_me: delete_me
- archive: tests/archive
- record: tests/last_test_validation.json
- Bootstrap gate: clear (`defaulted` empty, `conflicts` empty).
- Snapshot: tests/last_test_validation.json.preharvest taken before any harvest run.

## Scope

The tests build 34 wrote, as named by the dispatch:

- tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py
- tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py
- tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py
- tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py

Probe files also in tests/tmp (probe_*.py, test_probe_34_*.py) are not in this scope.

## Inventory

All four files collect; 5 items pass in tests/tmp (phase 2 is parametrised crawl/whitelist).

### tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py
- Drives: engine/crawler/dist/videos-worker.js (`crawlVideos`, compiled from engine/crawler/src/videos-worker.ts) under node.
- Tests: `test_crawl_writes_each_hosts_own_channel_name`.
- Depends on: ROOT, CRAWLER_DIR, SCHEMA, SRC, DIST, BUILD_HINT, NODE_SCRIPT, `_git`, `_dist_is_stale`, `_instance`.

### tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py
- Drives: engine/server/db/jobs/repair-video-channel-names.py (`repair_channel_names`, `has_videos_fts`) in-process; uses sync-whitelist.py's `ensure_content_schema` for the fixture.
- Tests: `test_repair_sets_each_video_to_its_own_channel_name[crawl]`, `[whitelist]`.
- Depends on: JOBS_DIR, CRAWL_SCHEMA, CHANNELS, VIDEOS, STORED, REPAIRED, `_load_job`, `sync_job`, `_seed`, `seeded_db`, `_names`, `_channels`.

### tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py
- Drives: engine/server/db/jobs/repair-video-channel-names.py (FTS path) in-process; sync-whitelist.py for schema and trigger fixtures.
- Tests: `test_repaired_fts_finds_own_name_not_foreign_name`.
- Depends on: JOBS_DIR, CHANNELS, VIDEOS, UNINDEXED_VIDEO, INSERT_VIDEO_SQL, MATCH_SQL, INDEXED_COUNT_SQL, VIDEOS_COUNT_SQL, `_load_job`, `jobs`, `_seed`, `_matches`, `_count`.

### tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py
- Drives: engine/server/db/jobs/repair-video-channel-names.py as a CLI via sys.executable.
- Tests: `test_cli_requires_db_and_logs_changed_count`.
- Depends on: REPAIR_JOB, CRAWL_SCHEMA, CHANNELS, VIDEOS, STORED, REPAIRED, REPAIRED_LOG, `_names`, `_run`.

## Classification

No active test drives videos-worker or repair-video-channel-names.py (searched tests/active for `videos-worker`, `repair-video-channel`, `channel_name`: only column lists in test_metadata.py and test_internal_client_reads.py). Neither subject file exists, so no verdict can be REDUNDANT.

### test_crawl_writes_each_hosts_own_channel_name — DURABLE
Only test pinning that crawled videos carry their own host's channel name/URL when channel ids repeat across hosts. Destination: tests/active/test_videos_worker.py (NEW).

### test_repair_sets_each_video_to_its_own_channel_name — DURABLE
Only test of the repair's row selection, changed count, idempotence and channels-untouched on both DB shapes. Destination: tests/active/test_repair_video_channel_names.py (NEW).

### test_repaired_fts_finds_own_name_not_foreign_name — DURABLE
Only test that the repair rebuilds videos_fts so MATCH reflects corrected names and the index row count equals videos. Destination: tests/active/test_repair_video_channel_names.py (NEW).

### test_cli_requires_db_and_logs_changed_count — DURABLE
Only test of the CLI contract (required --db, exit 2, logged changed count). Overlaps phase 2 on names/count but asserts the command-line surface phase 2 cannot. Destination: tests/active/test_repair_video_channel_names.py (NEW).

## Planned group map changes

- ADD `test_videos_worker.py`: engine/crawler/src/videos-worker.ts, engine/crawler/dist/videos-worker.js
- ADD `test_repair_video_channel_names.py`: engine/server/db/jobs/repair-video-channel-names.py, engine/server/db/jobs/sync-whitelist.py

## Retired

None.
