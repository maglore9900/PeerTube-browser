# Harvest: build 33 (metadata id-lookup threshold precedence)

## Resolved paths (from `--show-config`, bootstrap gate clear: `defaulted` empty)

- project_dir: /home/enduser/code/PeerTube-browser/.worktrees/33
- active: tests/active
- working: tests/tmp
- plans: docs/project/plans
- delete_me: delete_me
- archive: tests/archive
- record: tests/last_test_validation.json
- Snapshot: tests/last_test_validation.json.preharvest taken before any harvest run.

## Scope

- tests/tmp/test_33_metadata_id_threshold_precedence_phase1.py

Not in scope (build probes, not tests the build listed): tests/tmp/probe_33_id_threshold.py, tests/tmp/probe_33_rows.py, tests/tmp/probe_select_pairs.py.

## Inventory

### tests/tmp/test_33_metadata_id_threshold_precedence_phase1.py

- Drives: engine/server/data/metadata.py (`fetch_metadata_by_ids`, `fetch_metadata_by_uuids`, via `_select_pairs` / `_select_metadata`).
- Tests: `test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary`.
- Depends on: `BULK`, `THRESHOLD`, `VIDEO_TEXT`, `VIDEO_INT`, `BULK_SIZE`, `BULK_ERRORED`, `_video`, `_row`, `_add`, `_bulk`, `conn` fixture. Every one has an equivalent already in tests/active/test_metadata.py.
- Collects: yes.

## Classification

### test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary

- Verdict: COMBINE with tests/active/test_metadata.py::test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary.
- Reason: the active test already asserts C1 (exact healthy key set by id, c452 full row) and the uuid path, including the uuid c452 full row that the working test lacks. The working test alone asserts C2 (at error_threshold=None the id lookup returns c455's full row) and the guard that c455 sits in the 10-entry second chunk and is not its last pair. Neither is worth keeping whole.
- Merge: start from the active test (it keeps its name and its uuid full-row check). Hoist the entries into `id_entries` and lift in the chunk-position guard and the C2 assertion. Nothing in active is emptied, so nothing is retired to archive.
- Destination: tests/active/test_metadata.py (existing subject file, no new file, no new group).
- test_groups: no change (`test_metadata.py` already claims engine/server/data/metadata.py).

## Counts

COMBINE 1, DURABLE 0, REPLACES 0, REDUNDANT 0, SPENT 0.
