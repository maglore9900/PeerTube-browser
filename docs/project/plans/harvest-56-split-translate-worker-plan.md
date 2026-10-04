# Harvest plan: build 56 split-translate-worker

## Resolved paths (from `--show-config`, bootstrap gate clear: `defaulted` is empty, `conflicts` is empty)

- project_dir: `/home/enduser/code/PeerTube-browser`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`
- config source: `tests/config.json`

## Snapshot

`tests/last_test_validation.json` existed and was copied to `tests/last_test_validation.json.preharvest` (cmp-identical) before any harvest work ran. Nothing has banked since.

## Scope (the tests this build wrote)

- `tests/tmp/test_56_split_translate_worker_phase1.py`
- `tests/tmp/test_56_split_translate_worker_phase2.py`
- `tests/tmp/test_56_split_translate_worker_phase3.py`

All three collect (pytest `--collect-only`: 11 items from 6 functions); none is unclassifiable.

## Inventory

### tests/tmp/test_56_split_translate_worker_phase1.py

Drives `engine/server/db/jobs/translate-worker.py` (`serve` in-process on a daemon thread over the `rig` fixture).

- `test_serve_waits_the_given_back_off_before_its_next_lookup_of_the_same_head_job` (parametrised backoff 0.5 s, 1.0 s)
- `test_serve_refreshes_progress_every_given_slice_of_the_back_off_and_a_stop_during_it_returns_within_half_a_second_without_another_claim` (parametrised poll 0.05 s, 0.2 s)

Depends on: helper `_serving`; constants `GAP_SLICE_SECONDS`, `GAP_BACKOFF_SECONDS` (tuple), `GAP_SLACK_SECONDS`, `LIVE_SLICE_SECONDS` (tuple), `LIVE_BACKOFF_SECONDS` (2.5), `LOOKUP_WAIT_SECONDS` (15.0), `SAMPLE_SLICES`, `SAMPLE_EVERY_SECONDS`, `STOP_WITHIN_SECONDS`; imported from the active file: `DENIED_HOST`, `HOST`, `MAX_DURATION`, `QUEUED_AT`, `StubRunner`, `_recording`, `_until`, `clip`, `rig`, and `enqueue_translate_job`.

### tests/tmp/test_56_split_translate_worker_phase2.py

Drives `engine/server/db/jobs/translate-worker.py` (`run` subprocess under `ENGINE_PY`; `parse_args` in-process).

- `test_run_refuses_a_stall_seconds_that_is_not_a_positive_integer_with_exit_2_naming_the_flag_and_creates_nothing` (parametrised 0, -1, 1.5, x)
- `test_run_without_stall_seconds_parses_to_the_shipped_600_s`

Depends on: helper `_parse`; constants `REFUSED_STALL_SECONDS`, `FLAG_REFUSAL`, `RUN_START_SECONDS`; imported from the active file: `STOP_WINDOW_SECONDS`, `WORKER`, `_paths`, `_require_tools`, `_run_argv`, `_until`, `_worker`.

### tests/tmp/test_56_split_translate_worker_phase3.py

Drives `engine/server/db/jobs/translate-worker.py` (`run --stall-seconds N` subprocess, heartbeat rows in the real subtitles.db, whitelist.db held EXCLUSIVE).

- `test_run_given_stall_seconds_4_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on`
- `test_run_given_stall_seconds_60_keeps_beating_through_the_same_stall`

Depends on: helpers `_hold_main_loop`, `_stop`; constants `TEST_STALL_SECONDS` (int 4), `LONG_STALL_SECONDS` (60); imported from the active file: `BEAT_WINDOW_SECONDS`, `FIRST_BEAT_SECONDS`, `RESUME_SECONDS`, `STALL_KEY`, `STALLED_WINDOW_SECONDS`, `STOP_WINDOW_SECONDS`, `_beat`, `_jobs`, `_next_beat`, `_now_ms`, `_paths`, `_require_tools`, `_run_argv`, `_whitelist`, `connect_subtitles_db`, `enqueue_translate_job`.

## Classification (subject file: `tests/active/test_translate_worker.py`, not split, already mapped)

### test_serve_waits_the_given_back_off_before_its_next_lookup_of_the_same_head_job

**COMBINE** with active `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` (:1140). The checkpoint brings what active lacks: an upper bound `gap < backoff + GAP_SLACK_SECONDS`, two back-off values (0.5, 1.0), so a serve that hard-codes any one value fails, and an `errors == []` capture through `_serving`. Active holds what the checkpoint lacks: the `injected lock` parametrisation (`_recording(..., locked_calls=None)`, an injected `database is locked`), where the checkpoint covers only the missing file. Merge: start from active, take its `injected` parametrisation crossed with the backoff values, and lift in the upper bound, the clean-return `errors == []` and the `_serving` thread wrapper.

### test_serve_refreshes_progress_every_given_slice_of_the_back_off_and_a_stop_during_it_returns_within_half_a_second_without_another_claim

**REPLACES** active `test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim` (:1165). The checkpoint carries every assertion of the active test: freshness under two slices, two lookups only, stop within 0.5 s, row queued with attempts 0. It reads them at two slices (0.05, 0.2) and adds a lower bound `max(ages) > slice/2` plus `errors == []`, so a serve sleeping a fixed finer slice, or hard-coding one slice, now fails. Active asserts nothing the checkpoint does not.

### test_run_refuses_a_stall_seconds_that_is_not_a_positive_integer_with_exit_2_naming_the_flag_and_creates_nothing

**DURABLE.** No active test exercises `--stall-seconds`. It gates the refusal at parse time (exit 2, the flag named, nothing created). Destination: `tests/active/test_translate_worker.py`, Service section, after the held-lock test.

### test_run_without_stall_seconds_parses_to_the_shipped_600_s

**DURABLE.** No active test asserts the flag's default. It gates the omitted flag being the shipped 600 s, equal to `STALL_SECONDS`. Destination: `tests/active/test_translate_worker.py`, Service section.

### test_run_given_stall_seconds_4_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on

**REPLACES** active `test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on` (:1281). Same assertions (idle beat with pid, `beat_at` unchanged over the stalled window, resumed beat with pid after release, `failed`/`not in whitelist`, SIGTERM exit 0), but driven through the real CLI `run --stall-seconds 4` rather than the `-c` `STALL_DRIVER` that rewrites `STALL_SECONDS`. The plan's TR2/TR3 and its "no `-c` driver" acceptance criterion make the active one wrong now. Retiring it also retires `STALL_DRIVER` and its comment (:213-222), which have no other user.

### test_run_given_stall_seconds_60_keeps_beating_through_the_same_stall

**DURABLE.** No active test shows that the stop follows the operator's value and not a threshold fixed in the worker. Under 60 s the same stall keeps beating. Destination: `tests/active/test_translate_worker.py`, Service section.

## Counts

COMBINE 1, REPLACES 2, DURABLE 3, REDUNDANT 0, SPENT 0 (6 functions, 11 parametrised items).

## Name check (pre-computed for Step 5; subject `tests/active/test_translate_worker.py`)

- No incoming helper collides: `_serving`, `_parse`, `_hold_main_loop`, `_stop` are new. Also new: `GAP_SLICE_SECONDS`, `GAP_SLACK_SECONDS`, `LIVE_SLICE_SECONDS`, `SAMPLE_SLICES`, `LONG_STALL_SECONDS`, `REFUSED_STALL_SECONDS`, `FLAG_REFUSAL`, `RUN_START_SECONDS`.
- Same name and different body, to be resolved at Step 5:
  - `GAP_BACKOFF_SECONDS`: active 1.0, incoming (0.5, 1.0). The combined test is its only user, so the active definition takes the tuple.
  - `LIVE_BACKOFF_SECONDS`: active 1.5, incoming 2.5. It is used only by the replaced liveness test and by `LOOKUP_WAIT_SECONDS`, so it takes 2.5.
  - `LOOKUP_WAIT_SECONDS`: active `10 * LIVE_BACKOFF_SECONDS`, incoming 15.0. Keep the incoming 15.0 so it stays under the 30 s default once `LIVE_BACKOFF_SECONDS` is 2.5.
  - `STOP_WITHIN_SECONDS`: same value 0.5. Keep one copy and use the incoming comment.
  - `TEST_STALL_SECONDS`: active 4.0, incoming int 4. It becomes int 4 per TR2. Its comment and the `STALLED_WINDOW_SECONDS` comment are reworded per TR4.
- Same name and same body, one copy kept: `SAMPLE_EVERY_SECONDS`.
- Left unused once the replaced tests go: `SLICE_SECONDS` (still used by the combined gap test unless `GAP_SLICE_SECONDS` takes its place), `SAMPLE_SECONDS`, `FRESH_SECONDS`, `STALL_DRIVER`. Step 5 drops whichever has no user left.
- Module docstring: the Back-off bullets and the Service lines :47/:51 are reworded per TR4, and a Stall flag bullet is added.

## Retirements (Step 5.b; individual functions, the file stays)

To `tests/archive/translate_worker/test_translate_worker.py`:
- `test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim` (REPLACES)
- `test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on`, with `STALL_DRIVER` (REPLACES)
- `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job`, the version left emptied by the COMBINE merge (the merged test keeps the slot)

## test_groups

No change. `test_translate_worker.py` already claims `engine/server/db/jobs/translate-worker.py`, which is the only production file the harvested tests drive. No subject file is created.

## Mutation targets (Step 6, production file `engine/server/db/jobs/translate-worker.py`)

- Gap test (merged): back-off deadline `+ backoff_seconds` → hard-coded constant.
- Liveness test: slice `min(poll_seconds, ...)` → fixed finer slice or `POLL_SECONDS`.
- Refusal test: `--stall-seconds` `type=_positive_int` → `type=float`.
- Default test: `default=STALL_SECONDS` → another value.
- Stall 4 s test: `command_run` heartbeat `kwargs={"stall_seconds": ...}` dropped, or the comparison read as `STALL_SECONDS`.
- Stall 60 s test: `heartbeat_loop` comparison against a fixed 4.

## Step 5 — applied

Subject file `tests/active/test_translate_worker.py`:
- COMBINE: active `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` merged with the phase 1 checkpoint into `test_serve_waits_the_given_back_off_before_its_next_lookup_of_the_same_head_job` (its slot), parametrised `injected` (injected lock / missing file) × `backoff` (0.5 s, 1.0 s); lifted in `gap < backoff + GAP_SLACK_SECONDS`, the `_serving` wrapper and `errors == []`.
- REPLACES: `test_serve_refreshes_progress_every_given_slice_of_the_back_off_and_a_stop_during_it_returns_within_half_a_second_without_another_claim` in the replaced test's slot; `test_run_given_stall_seconds_4_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on` in the replaced stall test's slot.
- DURABLE: `test_run_refuses_a_stall_seconds_that_is_not_a_positive_integer_with_exit_2_naming_the_flag_and_creates_nothing` and `test_run_without_stall_seconds_parses_to_the_shipped_600_s` directly after the held-lock test; `test_run_given_stall_seconds_60_keeps_beating_through_the_same_stall` after the 4 s stall test.
- The `C1:`/`C2:` clause prefixes on the moved assertions' comments were dropped; the docstrings state the rule, not the phase.

Name check, as applied:
- New, no collision: helpers `_serving` (after `_until`), `_parse`, `_hold_main_loop`, `_stop` (Service helpers, after `_sidecars`); constants `GAP_SLICE_SECONDS`, `GAP_SLACK_SECONDS`, `LIVE_SLICE_SECONDS`, `SAMPLE_SLICES`, `REFUSED_STALL_SECONDS`, `FLAG_REFUSAL`, `RUN_START_SECONDS`, `LONG_STALL_SECONDS`.
- Same name, different body, resolved toward the incoming value: `GAP_BACKOFF_SECONDS` = (0.5, 1.0); `LIVE_BACKOFF_SECONDS` = 2.5; `LOOKUP_WAIT_SECONDS` = 15.0; `TEST_STALL_SECONDS` = 4 (int).
- Kept once: `STOP_WITHIN_SECONDS` (incoming comment), `SAMPLE_EVERY_SECONDS`.
- Removed, no user left: `SLICE_SECONDS` (the merged gap test uses `GAP_SLICE_SECONDS`), `SAMPLE_SECONDS`, `FRESH_SECONDS`, `STALL_DRIVER` and its comment.
- Module docstring: line 1 names `--stall-seconds`; Back-off paragraph and both bullets reworded to the given keyword timings read at two values; Service paragraph drops the `-c` driver; a Stall flag bullet added; the Stall bullet now reads `run --stall-seconds 4` and the 60 s counterpart.

Retired (5.b), individual functions, the file stays: all three into `tests/archive/translate_worker/test_translate_worker.py` (module skipped, archive docstring names each replacement), with `STALL_DRIVER` and the retired constants as they stood.

test_groups (5.c): unchanged. `--audit-map` exit 0; its `MISSING` for `test_translate_worker.py` (`engine/server/db/subtitles.db`, `engine/server/db/translate-worker.lock`) are the repo's default paths named in strings, pre-existing and not from the moved tests.

## Step 6 — mutations (production file `engine/server/db/jobs/translate-worker.py`; one per test, unbatched because M5 and M6 cancel each other when combined; each anchor counted at exactly one; copy in `.scratch/harvest/<test_name>/translate-worker.py.bak`)

Snapshot `tests/last_test_validation.json.preharvest` confirmed on disk before the first run. Baseline in the new home: 13 passed.

- M1 `test_serve_waits_the_given_back_off_before_its_next_lookup_of_the_same_head_job`: rule "waits the backoff_seconds given". `resume = time.monotonic() + backoff_seconds` → `+ 1.0`. Predicted the two 0.5 s items fall at the upper bound. Actual: `[injected lock-0.5s]` and `[missing file-0.5s]` failed `assert 1.0006 < (0.5 + 0.25)` / `1.0003 < (0.5 + 0.25)`; the 1.0 s items passed. Restored, diff clean, 4 passed.
- M2 `test_serve_refreshes_progress_every_given_slice_...`: rule "back-off slept in the given poll_seconds slices". `min(poll_seconds, ...)` → `min(0.02, ...)`. Predicted both fail the lower bound. Actual: both failed `max(ages) > slice_seconds / 2` (0.0198 vs 0.025; 0.0178 vs 0.1). Restored, diff clean, 2 passed.
- M3 `test_run_refuses_a_stall_seconds_...`: rule "the refusal is the flag's own, at parse time". `run.add_argument("--stall-seconds", ...)` → `"--stall-secs"`. Predicted all four fail `FLAG_REFUSAL in result.stderr`. Actual: all four failed it (stderr `unrecognized arguments: --stall-seconds <v>`). Restored, diff clean, 4 passed. Chosen over `type=float`/`type=int`, which accept 0 and run into the 30 s subprocess timeout, a hang the procedure rules out.
- M4 `test_run_without_stall_seconds_parses_to_the_shipped_600_s`: rule "omitted flag is the shipped 600 s". `default=STALL_SECONDS` → `default=60`. Actual: failed `assert 60 == 600`. Restored, diff clean, 1 passed.
- M5 `test_run_given_stall_seconds_4_...`: rule "the given --stall-seconds reaches the heartbeat". `kwargs={"stall_seconds": args.stall_seconds}` → `{"stall_seconds": STALL_SECONDS}`. Actual: failed `after == stalled` (beat_at moved 1791139303642 → 1791139313642). Restored, diff clean, 1 passed.
- M6 `test_run_given_stall_seconds_60_...`: rule "the threshold is the operator's, not fixed in the worker". `progress["at"] <= stall_seconds` → `<= 4`. Actual: failed `after[0] > stalled[0]` (1791139356138 both). Restored, diff clean, 1 passed.

No `.bak` from this harvest under the production tree or `tests/active` (the one `.bak` there, `engine/server/db/whitelist.db.bak-20261002-212806`, is a pre-existing DB backup).

## Step 7 — disposed

Moved to `delete_me/` (no name collisions): `test_56_split_translate_worker_phase1.py`, `test_56_split_translate_worker_phase2.py`, `test_56_split_translate_worker_phase3.py`. `tests/tmp` holds none of them.

## Step 8 — compare

Snapshot restored over the record, then `validate_tests.py --compare` (no tier): 3 groups selected (`test_translate_worker.py` changed, `test_static_page_visit_logs.py` changed by something outside this harvest, `test_search_fusion.py` unmapped), 62 unchanged carried forward; 97 passed, 0 failed, exit 0.
- Appeared 13: the merged gap test ×4, liveness ×2, refusal ×4, default ×1, stall 4 s ×1, stall 60 s ×1.
- Gone 4: pre-merge gap test ×2 (`injected lock`, `missing file`), the old liveness test, the old `-c`-driven stall test.
- No new red, nothing went from red to green. `test_translate_worker.py`: 77 passed (68 before + 13 − 4).
