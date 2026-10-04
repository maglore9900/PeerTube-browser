# Split translate-worker.py along its deep parts

Status: enhancement, complete
Origin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate "split translate-worker.py along its deep parts" (Worth exploring)

## Problem

`engine/server/db/jobs/translate-worker.py` (about 620 lines) is several modules in one file:

| Part | Lines |
|---|---|
| Enqueue CLI | `:100-155`, `588-620` |
| Media choice | `:158-198` |
| `AudioPipe` | `:201-308` |
| `WhisperRunner` | `:311-361` |
| Chunking | `:364-381` |
| Job pipeline | `:384-496` |
| Heartbeat and service loop | `:499-585` |

`AudioPipe` and `WhisperRunner` each hide a lot behind a narrow interface and should stay as they are. The problems are elsewhere:

- `generate` (`:430-468`) mixes whitelist I/O, the instance-track shortcut, JSON validation and pipe orchestration.
- Timing is tuned through module globals (`POLL_SECONDS`, `TRANSIENT_BACKOFF_SECONDS`, `STALL_SECONDS`).

The tests show the cost:

- They load the hyphenated script with `spec_from_file_location` (`tests/active/test_translate_worker.py:252-253`).
- They monkeypatch constants and `resolve_video` (`:1029-1032, 1056-1057`).
- They need a `-c` driver subprocess to lower `STALL_SECONDS` (`:207-216, 1177`).

## Proposed solution

Most of this follows from the other issues:

- Media acquisition joins the fetch adapter (issue 53).
- Job state moves behind the job handle (issue 54).

What remains is the pipeline and the service loop. Pass the timing values to `serve` as parameters, which removes the `-c` driver.

The cost is locality. The R1/R2/R5 rationale comments now sit beside the code they justify, and they would have to move with it.

Triage should decide whether this is its own work or the remainder after 53 and 54.

## Related

- Issues 53 and 54.
- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`.

## Comments

**Triage (2026-10-04).** The code claims above were checked against the tree, and all of them hold. One correction to the proposal: passing the timing values to `serve` does not remove the `-c` driver. The driver lowers `STALL_SECONDS`, which `heartbeat_loop` reads, not `serve`. It also runs the real `main()` in a subprocess, because the test needs the flock, the signal handling and the heartbeat thread. The stall threshold therefore has to reach `run` from the command line. `POLL_SECONDS` is also read by `AudioPipe.wait_samples`.

Most of the split is covered by other issues. Media acquisition is in 53, the video lookup and the instance-track shortcut are in 54, and the heartbeat interval is in 55. The maintainer narrowed this issue to **timing as parameters only**. The code stays in the script, so the rationale comments stay beside the code they justify. Moving the pipeline into an importable module is out of scope.

None of this depends on 53, 54 or 55. All four edit the worker script, though, so building them one after another avoids merge conflicts.

**Delivered (2026-10-04).** `serve` takes keyword-only `poll_seconds`, `backoff_seconds` and `idle_unload_seconds`, and `heartbeat_loop` takes keyword-only `stall_seconds`, each defaulting to its module constant. `run --stall-seconds` (a positive integer, default `STALL_SECONDS`) reaches the heartbeat thread; `command_run` calls `serve` with its defaults. One departure from the brief, approved by the maintainer: `AudioPipe` takes no wait slice. Its only caller is `generate`, which would always pass the default, so `wait_samples` waits `POLL_SECONDS` and the chunk-loop progress refresh stays at most 2 s apart whatever `serve` is given. To make that tunable, thread a parameter through `run_job` and `generate`.

## Agent Brief

**Category:** enhancement
**Summary:** Pass the translate worker's timing values as parameters instead of module globals, and give `run` a stall-threshold option, so tests drive the real service with short timings and no longer monkeypatch the script or run it through a `-c` driver.

**Current behavior:**
The worker's service timing lives in module globals of the worker script:
- `POLL_SECONDS` (2 s): the idle claim poll, the slice of the whitelist back-off wait, and `AudioPipe.wait_samples`' wait.
- `TRANSIENT_BACKOFF_SECONDS` (30 s): the wait after a whitelist.db requeue.
- `IDLE_UNLOAD_SECONDS` (300 s): how long the model stays loaded without a job.
- `STALL_SECONDS` (600 s): how long the main loop may be silent before the heartbeat thread stops beating.

`serve`, `heartbeat_loop` and `AudioPipe` read these globals directly. To shorten them, the tests monkeypatch `POLL_SECONDS` and `TRANSIENT_BACKOFF_SECONDS` on the loaded script module. For the stall test, they start the service through a `python -c` driver that loads the script, overwrites `STALL_SECONDS` and calls `main()`.

**Desired behavior:**
- `serve` takes its poll interval, whitelist back-off and idle-unload time as parameters, and `heartbeat_loop` takes its stall threshold as a parameter. `AudioPipe` takes its wait slice at construction (not delivered; see the Delivered comment). All of them default to today's values.
- `run` gains a `--stall-seconds` option: a positive integer, defaulting to today's 600. `run` passes it to the heartbeat thread. Its help text says what it bounds: how long the main loop may be silent before the worker stops beating, so the Engine reads generation as unavailable.
- Every other `run` behaviour, exit code and log line is unchanged, and so is every timing default.
- The tests:
  - call `serve` with short timings as arguments, instead of monkeypatching module globals;
  - start the stall test's service as an ordinary `translate-worker.py … run --stall-seconds 4 …` subprocess, with the `-c` driver deleted;
  - stop setting any timing attribute on the loaded worker module.

**Key interfaces:**
- The `serve(...)` signature gains keyword parameters for poll, back-off and idle unload, each with a default.
- The `heartbeat_loop(...)` signature gains a keyword stall threshold with a default.
- `AudioPipe(...)` gains a keyword wait slice with a default (not delivered; see the Delivered comment).
- `run`'s argument parser gains `--stall-seconds`.
- The module-level constants may stay as the defaults' single source.

**Acceptance criteria:**
- [x] No test sets `POLL_SECONDS`, `TRANSIENT_BACKOFF_SECONDS`, `IDLE_UNLOAD_SECONDS` or `STALL_SECONDS` on the worker module.
- [x] The stall test starts the worker as a plain `run` subprocess with `--stall-seconds`, and the `-c` driver is gone from the tests.
- [x] With `--stall-seconds` omitted, the heartbeat stops after 600 s of main-loop silence, as today. A zero, negative or non-integer value is refused by the parser.
- [x] The back-off tests (same head job looked up again no sooner than the back-off, stop honoured within one slice) pass with the timings passed as arguments.
- [x] Every existing translate worker test passes, and the default timings are unchanged.
- [x] The translate worker doc lists `--stall-seconds` with the other `run` options.

**Out of scope:**
- Moving `AudioPipe`, `WhisperRunner`, chunking or the job pipeline out of the script into an importable module, or renaming the hyphenated script.
- The heartbeat interval (`HEARTBEAT_SECONDS`) and its fresh window, which belong to issue 55.
- The fetch adapter (53), the job handle and shared resolve (54), and any change to `generate`'s steps.
- Exposing the poll, back-off or idle-unload values as command-line options.
- Changing any timing default.
