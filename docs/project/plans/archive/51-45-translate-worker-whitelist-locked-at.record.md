# Build record - 45-translate-worker-whitelist-locked-at

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/51-45-translate-worker-whitelist-locked-at.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# A locked whitelist.db at claim time fails a translate job permanently\n\nStatus: bug, ready-for-agent\nOrigin: build 49-translate-whisper-worker (plan `docs/project/plans/archive/49-translate-whisper-worker.md`, working file `docs/project/plans/archive/52-49-translate-whisper-worker.md`). The draft named it `WhitelistBusy`, and the build left it unbuilt.\n\n## Problem\n\nWhen the translate worker claims a job, `generate` calls `resolve_video` (`engine/server/db/jobs/translate-worker.py:93`, called at `:422`) to re-check the whitelist and the denylist. `resolve_video` opens `whitelist.db` read-only with `PRAGMA busy_timeout = 30000`.\n\nIf the file is still locked after 30 s, the `sqlite3.OperationalError` escapes `generate`. The catch-all `except Exception` in `run_job` (`:469`) then ends the job `failed` with `OperationalError: database is locked`. A missing file, for example mid-restore, ends the same way.\n\n- `failed` is terminal: enqueue refuses a key in any state (`enqueue_translate_job` returns `exists`). That key can then never be queued again from the CLI or from plan 50's route.\n- The only ways out are B1's upsert, if the instance gains an English track, or a manual `DELETE` of the row.\n\nA long write lock on `whitelist.db` is expected, not rare. The updater's merge holds one while it commits. `engine/server/db/jobs/docs/TRANSLATE_WORKER.md:154` and the `DEPLOYMENT.md` triage table record the gap as known behaviour.\n\nNo acceptance criterion in plan 49 requires the fix, so plan 49 closed without it.\n\n## Proposed solution\n\nTreat a lock or a missing file during the claim-time whitelist check as transient:\n- requeue the job without spending its claim, using `requeue_translate_job`, which SIGTERM already uses;\n- have `serve` back off, for example 30 s, before the next claim.\n\nA real error, such as `no such column` from an unmigrated `whitelist.db`, should still fail the job.\n\nThe plan 49 draft had this shape:\n- a `WhitelistBusy` exception;\n- an `is_transient_db_error` check matching \"locked\", \"busy\" or \"unable to open\";\n- a `TRANSIENT_BACKOFF_SECONDS` sleep in `serve`.\n\nA gating test would:\n- make `resolve_video` raise `sqlite3.OperationalError(\"database is locked\")` at claim;\n- assert the row is back to `queued` with its `attempts` and `queued_at` restored;\n- assert the next claim waits for the back-off;\n- as a control, assert a `no such column` error still ends `failed`.\n\nWhen fixed, remove the known-gap lines from `TRANSLATE_WORKER.md` and the `DEPLOYMENT.md` triage row.\n\n## Related\n\n- `docs/project/plans/archive/49-translate-whisper-worker.md`, Outstanding.\n- `docs/project/plans/50-translate-generation-in-page.md`: its route calls the same enqueue, so a key failed this way is also refused from the page.\n- Memory `engine-concurrent-start-locks-random-cache`: the project's history of \"database is locked\".\n\n## Comments\n\n### Triage (2026-10-03): confirmed, ready for an agent\n\n- **Reproduced** with `tests/tmp/probe_45_whitelist_locked_at_claim.py`:\n  - It builds the test suite's whitelist fixture in the default rollback journal, which is the dev `whitelist.db`'s mode (`PRAGMA journal_mode` reads `delete`), so a writer's lock blocks readers.\n  - It queues and claims a job, holds `BEGIN EXCLUSIVE` on the whitelist, and calls `run_job`.\n  - After the 30 s busy timeout the row reads `failed`, with an error starting `OperationalError: database is locked`.\n  - Enqueuing the key again returns `(\"exists\", \"failed\")`.\n\n  The probe passed in 30.4 s.\n- **Checked:** nothing in the worker treats a database error as temporary; nothing requeues it or backs off. There is no `docs/project/rejected/` entry, and no ADR covers worker retries.\n- **Decided (maintainer):** a missing or unopenable `whitelist.db`, for example during a restore, is temporary, just as a lock is. The job is requeued and the worker backs off, repeating until the file is back.\n\n## Agent Brief\n\n**Category:** bug\n**Summary:** A translate job claimed while `whitelist.db` is locked or missing should go back to the queue unspent, not fail permanently.\n\n**Current behavior:**\nWhen the translate worker claims a job, it re-checks the video against the Engine's `whitelist.db`: the whitelist row, the active denylist and the stored duration. It opens that file read-only with a 30 s busy timeout.\n\nIf the file is still locked after that, or cannot be opened, the `sqlite3` error propagates to the worker's catch-all job handler. That handler ends the job `failed` with the error text, for example `OperationalError: database is locked`.\n\n`failed` is terminal. Enqueue refuses a key in any state, so the video can never be queued again from the command line or the page.\n\nThe updater's merge holds a write lock on `whitelist.db` long enough for this to happen in normal operation. The worker's own documentation and the deployment triage table record it as a known gap.\n\n**Desired behavior:**\n- A transient database error during the claim-time whitelist check requeues the job without spending its claim:\n  - the state is back to `queued`;\n  - `attempts` is restored to its value before the claim;\n  - `queued_at` is unchanged, so it stays at the head of the queue.\n\n  Transient means a lock (\"locked\" or \"busy\" in the error text) or a file that cannot be opened (\"unable to open\").\n- The worker then waits a back-off of about 30 s before its next claim, instead of reclaiming at once. It keeps beating its heartbeat during the wait, and a stop request (SIGTERM) ends the wait promptly.\n- The requeue repeats for as long as the condition lasts. A transient error never ends the job `failed`, and never counts toward the crash-retry limit.\n- Any other database error during the check still ends the job `failed` with its text, as today. An example is `no such column` from an unmigrated whitelist.\n- A transient requeue is logged at warning level, with the key and the error text.\n\n**Key interfaces:**\n- The worker's claim-time whitelist resolution: it currently returns the row or a refusal text, or raises `sqlite3.Error`. Its transient errors must be told apart from the rest.\n- The store's existing requeue-without-spending function, the one the SIGTERM path already uses. Reuse it rather than adding a second requeue.\n- The worker's serve loop, the claim, run and poll cycle, which needs the back-off. It must not block the heartbeat or a stop.\n- The worker's documentation and the deployment triage table, whose known-gap lines this removes.\n\n**Acceptance criteria:**\n- [ ] With an exclusive lock held on a rollback-journal `whitelist.db` throughout the check, a claimed job ends `queued` with `attempts` and `queued_at` as they were before the claim, not `failed`.\n- [ ] With `whitelist.db` absent at claim time, the same holds.\n- [ ] The next claim after a transient requeue happens no sooner than the back-off, and a stop during the back-off makes the worker exit promptly.\n- [ ] Control: a non-transient `sqlite3.OperationalError`, such as `no such column`, at claim time still ends the job `failed` with that error text.\n- [ ] Once the lock is released or the file restored, the requeued job is claimed and runs to a normal end state.\n- [ ] The worker's documentation and the deployment triage table no longer describe a locked `whitelist.db` as failing the job permanently. They describe the requeue and back-off instead.\n- [ ] The existing translate worker and subtitles store tests still pass.\n\n**Out of scope:**\n- Re-queuing keys that are already `failed`, including ones failed by this bug before the fix.\n- Transient handling for the `enqueue` command, which reports a database error and exits 1, or for remote fetch failures.\n- Changing the 30 s busy timeout, the crash-retry limit or the queue cap.\n- `subtitles.db` locking, which has its own busy timeout and tests.",
  "request_source": "read from docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md",
  "slug": "45-translate-worker-whitelist-locked-at",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "10": "done",
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Requeue at claim on a transient whitelist.db error",
      "checkpoint": "Seam: `run_job`, reached through the existing `Rig` harness in `tests/active/test_translate_worker.py` (`rig.claim()` then `rig.run(StubRunner(rig))`, `Rig.run` changed to return `run_job`'s result), the same entry the outcome tests at :799-852 use. Beyond that seam are a patched module-global `resolve_video` (`_raising`), a real whitelist file that is deleted, zero-byte or held under `BEGIN EXCLUSIVE` by a second connection, and `caplog` on the root logger. c1 is parametrized over injected lock, missing file and held EXCLUSIVE lock (~30 s). For each it asserts every member of the row tuple (state `queued`, attempts 0, queued_at `QUEUED_AT`, error None, finished_at None), exactly one WARNING whose message carries `[translate-worker]`, `v-1`, `HOST` and the error text, no record at ERROR or above, `rig.instance.opened == []` and `rig.media.opened == []`, and `run_job` returning `is True`. These exclude, respectively: a requeue that spends the attempt or rewrites queued_at, a branch that writes error or finished_at, a missing or duplicated log line or one that omits key or text, a branch placed after the catch-all, a guard that lets the job proceed to a remote request, and a return value serve cannot read. c2 is parametrized over injected `no such column` and a zero-byte file. It asserts state `failed` with error starting `OperationalError: no such column` / `OperationalError: no such table`, exactly one ERROR record carrying exc_info, no WARNING, and `run_job` returning `is False`, which excludes an over-broad predicate or a guard that rewraps every OperationalError.",
      "intent": "In `translate-worker.py`, a job whose claim-time `resolve_video` call hits a locked, busy or unopenable `whitelist.db` is returned by `run_job` to `queued` with its claim unspent and one warning logged, instead of failing. Every other `whitelist.db` error at claim still fails the job with today's `OperationalError: <text>`.",
      "clauses": [
        {
          "id": "C1",
          "text": "A locked, busy or unopenable `whitelist.db` at claim leaves the job `queued` with attempts restored, `queued_at` kept, no `error` or `finished_at`, nothing requested, and one warning naming the key and the error text, and `run_job` returns True."
        },
        {
          "id": "C2",
          "text": "Any other `whitelist.db` error at claim still ends the job `failed` with `OperationalError: <text>` through the logged catch-all, and `run_job` returns False."
        }
      ],
      "files": [
        "engine/server/db/jobs/translate-worker.py (EDITED)",
        "tests/active/test_translate_worker.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/db/jobs/translate-worker.py`\n\n- **New exception `WhitelistBusy`.** It sits next to `JobFailed`, `JobStopped` and `JobTakenOver` and subclasses `Exception` directly, so the `except JobFailed` branch never catches it.\n- **`generate`.** Only the claim-time `resolve_video` call is wrapped, in `try/except sqlite3.OperationalError`.\n  - If the lowercased error text contains `locked`, `busy` or `unable to open`, it raises `WhitelistBusy(str(exc)) from exc`.\n  - Any other error is re-raised unchanged with a bare `raise`, so it still reaches the catch-all and ends the job `failed` with `OperationalError: <text>`.\n  - The refusal check and every later step stay outside the `try`, so `subtitles.db` errors are never treated as transient.\n  - The plan's separate `is_transient_db_error` predicate is written inline instead, because it has one caller.\n  - The docstring now names the `WhitelistBusy` case.\n- **`run_job`.**\n  - The return type changes from `-> None` to `-> bool`.\n  - A new `except WhitelistBusy as exc` branch comes right after `JobStopped`, ahead of the catch-all, so it never reaches `logging.exception` or the CUDA-OOM unload.\n  - The branch calls the existing `requeue_translate_job(conn, *claim)`, which gives back the attempt and keeps `queued_at`. It logs one `logging.warning(\"[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s\", ...)` with the error text, and returns True. It writes no `error` and no `finished_at`.\n  - Every other path ends in a final `return False`.\n  - The docstring now covers the transient requeue and the return value.\n- **Not touched in this phase:** `serve` does not read the result yet, and the back-off constant is not added. Both belong to Phase 2.\n- **Unchanged:** `resolve_video` and `command_enqueue`.\n\n### `tests/active/test_translate_worker.py`\n\nNo change. The checkpoint calls `rig.worker.run_job` directly, so `Rig.run` did not need to return the value."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Back off before the reclaim, then recover",
      "checkpoint": "Two seams. (a) `serve`, entered in-process on a daemon thread over `rig.conn`, which is opened `check_same_thread=False`. On the loaded module, `POLL_SECONDS` is 0.05 and `TRANSIENT_BACKOFF_SECONDS` is 1.0, `resolve_video` is patched to always raise `database is locked` and record monotonic call times, and a StubRunner is used. No existing harness drives `serve` in-process, because the beat tests use the real CLI under a pty, so this is a new in-process entry and the drafted test function is its harness. For c1 it waits for two lookups, then asserts `calls[1] - calls[0] >= BACKOFF_SECONDS`, which excludes a serve that ignores the bool and reclaims on the next 0.05 s poll. It also asserts the row is still `queued` with attempts 0 and queued_at kept, which shows the reclaim is the same head job. (b) `run_job` via `Rig.run`, then a direct `claim_translate_job(rig.conn, \"en\", STARTED_AT + 1)`, parametrized over lock released (`_raising(LOCKED, then=real resolve_video)`) and file restored (unlink, then rewrite with `_whitelist`). For c2 it asserts the intermediate control (`queued`, 0), then that the reclaim is `v-1` with attempts 1, then a final row of `ready`, `whisper` and queued_at `QUEUED_AT`. This excludes a requeue that leaves the row unclaimable or a reclaimed run that fails or rewrites queued_at.",
      "intent": "After a `whitelist.db` requeue, `serve` in `translate-worker.py` waits `TRANSIENT_BACKOFF_SECONDS` before claiming the same head job again, and once `whitelist.db` is usable that reclaimed job runs like any other.",
      "clauses": [
        {
          "id": "C1",
          "text": "After a `whitelist.db` requeue, the next claim of the same head job comes no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first."
        },
        {
          "id": "C2",
          "text": "Once the lock is released or the file restored, the requeued job claimed again runs to `ready` with its `queued_at` kept."
        }
      ],
      "files": [
        "engine/server/db/jobs/translate-worker.py (EDITED)",
        "tests/active/test_translate_worker.py (EDITED)"
      ],
      "done": true,
      "outcome": "### engine/server/db/jobs/translate-worker.py\n- Added the module constant `TRANSIENT_BACKOFF_SECONDS = 30.0`, defined next to `POLL_SECONDS`. Its comment gives the reason for it: the requeued job is still at the head of the queue, so without a wait `serve` would claim it again straight away and spin.\n- `serve` now uses the `bool` that `run_job` already returned. That value is True only for the whitelist.db requeue added in phase 1. When it is True, `serve` waits `TRANSIENT_BACKOFF_SECONDS` before its next claim (C1). The wait sleeps with `time.sleep` in pieces no longer than `POLL_SECONDS`, so a stop still ends `serve` within one poll interval. It uses `time.sleep` rather than `stop.wait` for the same SIGTERM-deadlock reason already noted in the idle branch. Each sleep is clamped at 0 so a near-zero remainder can't raise. The docstring of `serve` now mentions the back-off.\n- C2 needed no change. After the back-off, the job claimed again goes through the same `run_job` path as any other job, which phase 1 already delivered.\n\n### tests/active/test_translate_worker.py\nNot changed. The checkpoint only imports its rig and constants, and they already covered what it needed."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Stay live during the back-off",
      "checkpoint": "The same in-process `serve` thread seam as phase 2, extending its serve test past the second lookup, while the worker is inside the second back-off. For c1 it samples `progress[\"at\"]` twice, 0.15 s apart, and asserts the second sample is larger and less than 0.3 s old. This excludes a back-off that sleeps the whole deadline in one call or never touches progress, which would let the heartbeat go dark. A control asserts that `len(calls) == 2`, so the samples were taken during the wait and not during a fresh claim. For c2 it sets `stop` from the test thread, joins with a 5 s timeout, and asserts the thread is dead within 0.5 s, well under the ~0.7 s left of the back-off. It also asserts `len(calls)` is still 2, with no claim after the stop, and that the row is still `queued` with attempts 0. This excludes a loop that ignores `stop` until the deadline and one that claims once more before exiting. Setting `stop` off the main thread is safe here because no signal handler is involved.",
      "intent": "The back-off wait in `serve` keeps the worker live: it refreshes `progress[\"at\"]` every `POLL_SECONDS` slice and a stop ends it within one slice.",
      "clauses": [
        {
          "id": "C1",
          "text": "During the back-off, `progress[\"at\"]` keeps advancing at least once per slice."
        },
        {
          "id": "C2",
          "text": "A stop set during the back-off makes `serve` return within about one slice without claiming again."
        }
      ],
      "files": [
        "engine/server/db/jobs/translate-worker.py (EDITED)",
        "tests/active/test_translate_worker.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/db/jobs/translate-worker.py`\nIn `serve`, the back-off loop after a whitelist.db requeue now sets `progress[\"at\"] = time.monotonic()` at the start of each `POLL_SECONDS` slice (C1). Without it, the heartbeat thread would treat a long `TRANSIENT_BACKOFF_SECONDS` wait as a stall and stop beating. The comment above the loop now gives this reason too. The loop's check of `stop.is_set()` before each slice is unchanged, so a stop still ends `serve` within one slice and nothing is claimed again (C2).\n\n### `tests/active/test_translate_worker.py`\nNot changed. The checkpoint imports only its existing rig and helpers (`HOST`, `MAX_DURATION`, `QUEUED_AT`, `StubRunner`, `clip`, `rig`). Nothing in this file covers the back-off, so this phase did not need to edit it."
    }
  ],
  "digests": {
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py": "f8b4a21896c3a3e7efaffaabc6407e88909f877dc030481612895d8d0bae119a",
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py": "71149aa7559916c39ae0dc1f79c9b629fe8641e799e3788f8294d65bb238e625",
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py": "f2a020d687addd3534834e83fbac05f149e37f9255ad3b1094f4a9cc9787edb5"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261003T232013-cdf9-dev-flow"
  ],
  "snapshot": {
    "tree": "aed68720d3bd15c60a441688639f53fc47cd4519",
    "at": "2026-10-03T23:20:24-04:00"
  },
  "plan": "docs/project/plans/51-45-translate-worker-whitelist-locked-at.md",
  "record": "docs/project/plans/51-45-translate-worker-whitelist-locked-at.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nFix issue `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md` (category bug, ready-for-agent). The translate worker (`engine/server/db/jobs/translate-worker.py`) re-checks every claimed job against the Engine's `whitelist.db` before doing any remote work. If that file is locked past the 30 s busy timeout, or cannot be opened (for example mid-restore), the job ends `failed` today. `failed` is terminal, and enqueue refuses a key in any state, so that video can never be queued again from the CLI or from plan 50's page route. The updater's merge holds a write lock on `whitelist.db` long enough for this to happen in normal operation. After this build such a condition is temporary for the job: it goes back to the queue unspent, the worker backs off, and the job runs once the file is usable again. Real errors still fail the job as today.\n\n### Current behaviour (verified in the tree)\n\n- `resolve_video(whitelist_path, video_id, host, max_duration)` (`translate-worker.py:93-110`) opens `whitelist.db` with `connect_readonly_db` (`engine/server/data/db.py:85`: URI `mode=ro`, so a missing file raises `sqlite3.OperationalError: unable to open database file`). It sets `PRAGMA busy_timeout = 30000` and calls `fetch_video_row` and `list_active_denied_hosts`. It returns `(row, None)` or `(None, refusal_text)`, or raises `sqlite3.Error`. `command_enqueue` (`:113`) also calls it and is out of scope.\n- `generate` (`:420`) calls `resolve_video(args.whitelist_db, *claim[:2], args.max_duration)` first, at `:422`. A refusal raises `JobFailed`.\n- `run_job` (`:455-474`) handles `JobStopped` with `requeue_translate_job(conn, *claim)` and an info log, `JobTakenOver` with an info log, and `JobFailed` with `finish_translate_failed`. A catch-all `except Exception` (`:469`) unloads the model on CUDA OOM, logs with a traceback and writes `failed` with `f\"{type(exc).__name__}: {exc}\"`. A locked or missing `whitelist.db` lands in this catch-all today.\n- `requeue_translate_job(conn, video_id, instance_domain, target_language, started_at) -> bool` (`engine/server/data/subtitles.py:161`) is a conditional update on the running row with that `started_at`: `state = 'queued', attempts = attempts - 1`, and `queued_at` is untouched. It returns False when B1's route took the row over. `claim_translate_job` (`:130`) picks the oldest queued row by `queued_at, rowid`, sets `running`, sets `started_at` and increments `attempts`. `recover_translate_jobs` (`:141`) fails a row found `running` at start with `attempts >= MAX_CLAIMS` (2).\n- `serve` (`translate-worker.py:493-511`) loops while `not stop.is_set()`: it sets `progress[\"at\"] = time.monotonic()`, claims, and when idle sleeps `POLL_SECONDS` (2.0) with `time.sleep`. It deliberately does not use `stop.wait`: the SIGTERM handler sets `stop` on the main thread, and `Event.set` deadlocks if it lands while that thread holds the event's lock inside `wait` (comment at `:506`). It calls `run_job` and resets `idle_since`.\n- `heartbeat_loop` (`:477`) beats every `HEARTBEAT_SECONDS` (5 s) on its own thread unless `progress[\"at\"]` is older than `STALL_SECONDS` (600 s).\n- Docs: `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` has a Known Gaps bullet at line 154 (locked `whitelist.db` fails the job permanently, no requeue or back-off). Error Texts line 137 lists \"a locked `whitelist.db`\" under `<ExceptionType>: <text>`. The Serve Loop section (line 79), the Stop/Crash section (line 141) and the Logs list (lines 159-168) do not mention a transient requeue. `DEPLOYMENT.md:353` is a triage row: \"A job ends `failed` with `OperationalError: database is locked`, or `enqueue` prints `error: whitelist.db: database is locked`\" \u2026 \"The job is not requeued and nothing backs off: the key stays `failed`\" \u2026 \"Re-queue the key \u2026 after the updater run ends\".\n- Existing tests: `tests/active/test_translate_worker.py`. Its job-pipeline rig calls `run_job` in-process over a tmp `whitelist.db` and a tmp `subtitles.db`, with a job enqueued and claimed by the store's own functions (queued_at 1000, started_at 2000). There is an existing stop-requeue test, `test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept`, and subprocess `run` tests for heartbeat and SIGTERM. The triage probe `tests/tmp/probe_45_whitelist_locked_at_claim.py` reproduced the bug in 30.4 s using a rollback-journal whitelist fixture and `BEGIN EXCLUSIVE`.\n\n### R1: Classify transient errors at the claim-time whitelist check\n\n- Only the claim-time call to `resolve_video` inside the worker's job path is affected. An `sqlite3.OperationalError` raised by it is transient when its text, compared case-insensitively, contains `locked`, `busy` or `unable to open`.\n- The transient set is exactly these three (operator decision). Every other error still fails the job permanently through today's path, with today's text (`<ExceptionType>: <text>`). That includes `no such column`, `no such table` (for example a zero-byte file), `file is not a database` and `database disk image is malformed`.\n- The plan 49 draft used a `WhitelistBusy` exception and an `is_transient_db_error` predicate. Those names are suggestions, not requirements. `db.py` already has a precedent for the text-matching shape in `is_interrupted_error`.\n- `command_enqueue`'s handling of the same errors is unchanged: it reports and exits 1.\n\n### R2: Requeue without spending the claim\n\n- A transient error requeues the job through the existing `requeue_translate_job(conn, *claim)`, the function the SIGTERM path uses. No second requeue function is added.\n- After the requeue: `state` is `queued`, `attempts` equals its value before the claim, and `queued_at` is unchanged, so the job stays at the head of the queue. No `error` or `finished_at` is written, and the row is never written `failed` for a transient error.\n- A transient requeue never counts toward the crash-retry limit (`MAX_CLAIMS`), because the attempt is given back.\n- It is logged at warning level with the key (video_id, host) and the error text, prefixed `[translate-worker]` like every other worker line. It does not use `logging.exception`.\n- The CUDA-OOM model unload is not triggered by this path.\n- If `requeue_translate_job` returns False (B1 took the row over), nothing more is written for that job, as for the other conditional writes.\n\n### R3: Back off before the next claim\n\n- After a transient requeue, `serve` waits a back-off of about 30 s (a named module constant, for example `TRANSIENT_BACKOFF_SECONDS = 30.0`) before its next claim, instead of reclaiming at once.\n- `run_job` must tell `serve` that a back-off is due. The mechanism is the designer's choice.\n- The wait must not block the heartbeat. It keeps `progress[\"at\"]` fresh at least as often as the idle poll does (every `POLL_SECONDS`), so the heartbeat thread keeps beating.\n- A stop request (SIGTERM or SIGINT setting `stop`) ends the wait promptly, within about one `POLL_SECONDS` slice, and the worker exits normally.\n- The wait must keep the existing rule that the main thread uses `time.sleep`, not `stop.wait`, for the reason in the comment at `serve` (`translate-worker.py:506`). For example, it can sleep in `POLL_SECONDS` slices and check `stop` between them.\n- The requeue and back-off repeat for as long as the condition lasts. Each cycle reclaims the same head-of-queue job. A whole cycle under a held lock is roughly the 30 s busy wait plus the 30 s back-off; with a missing file it is immediate failure plus the 30 s back-off.\n\n### R4: Recovery once the cause clears\n\n- Once the lock is released or the file restored, the requeued job is claimed on the next pass after the back-off and runs to a normal end state (`ready`, `already_english`, or a non-transient `failed`), exactly as an unaffected job would.\n\n### R5: Documentation\n\n- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`:\n  - Remove the first Known Gaps bullet (locked `whitelist.db`), keeping the second (faster-whisper and VRAM).\n  - In Error Texts, drop \"and a locked `whitelist.db`\" from the `<ExceptionType>: <text>` line.\n  - Describe the requeue and back-off as current behaviour, in the Serve Loop and Job Pipeline step 1 and/or Stop, Crash and Recovery, wherever it reads naturally. Cover what is transient (locked, busy, unable to open, for example during the updater merge or a restore), that the job goes back to `queued` with `attempts` restored and `queued_at` kept, the about 30 s back-off that a stop ends promptly, that it repeats until the file is usable, and that other database errors still fail the job.\n  - Add the new warning log line to Logs.\n- `DEPLOYMENT.md` triage row at line 353: it must no longer say a locked `whitelist.db` fails the job or that the key stays `failed`. It should describe the requeue and back-off (the job stays `queued` and runs once the updater merge or restore ends, with the warning line in the journal). The `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) stays, because enqueue is out of scope.\n- Write as current state, with no \"previously\" history. One paragraph per line, with no softwrap.\n\n### R6: Tests\n\nNew gating tests go in `tests/active/test_translate_worker.py`, reusing its rig (tmp `whitelist.db` and `subtitles.db`, job enqueued and claimed by the store's functions):\n- An exclusive lock (`BEGIN EXCLUSIVE`) is held on a rollback-journal `whitelist.db` throughout the check. The claimed job ends `queued` with `attempts` and `queued_at` as before the claim, not `failed`. Because of the real 30 s busy timeout, the test may instead inject `sqlite3.OperationalError(\"database is locked\")` from `resolve_video` at claim. At least the injected form must be covered, and one real-lock case is preferred if its runtime is acceptable.\n- `whitelist.db` is absent at claim time (a real missing path, giving `unable to open database file`). Same outcome.\n- The next claim after a transient requeue happens no sooner than the back-off. A stop set during the back-off makes `serve` return promptly. The heartbeat progress stays fresh during the wait.\n- Control: a non-transient `sqlite3.OperationalError` such as `no such column` at claim still ends the job `failed` with its text (`OperationalError: no such column\u2026`).\n- Once the lock is released or the file restored, the requeued job is claimed and runs to a normal end state.\n- A warning-level log line naming the key and the error text is emitted on a transient requeue.\n- The existing translate worker and subtitles store tests still pass.\n\n### Out of scope\n\n- Re-queuing keys already `failed`, including ones failed by this bug before the fix.\n- Transient handling for the `enqueue` command (it reports a database error and exits 1) or for remote fetch failures.\n- Changing the 30 s busy timeout, `MAX_CLAIMS`, or the queue cap.\n- `subtitles.db` locking (its own busy timeout and tests).\n- Treating corrupt or partial files (`file is not a database`, `malformed`, `no such table`) as transient.\n\n### Accepted limits\n\n- sqlite's own 30 s busy wait inside `resolve_video` cannot be interrupted, so a stop that arrives during that wait, as opposed to during the back-off, still takes up to about 30 s to take effect. The busy timeout is not changed.\n- While `whitelist.db` stays locked or missing, the head job is reclaimed every cycle and later queued jobs wait behind it. Every job needs the same file, so they could not run anyway.\n\n### Baseline suite state\n\nPre-build baseline: exit code 0, variant false (the suite is green before the build).\n</requirements>\n\n<conflicts>\nDEPLOYMENT.md:353 combines the job case (in scope: must now describe the requeue and back-off) with the `enqueue` case `error: whitelist.db: database is locked` (out of scope: unchanged). The brief says to \"remove the triage row\", but the row must instead be rewritten so that its enqueue half survives.\nThe brief's AC \"a stop during the back-off makes the worker exit promptly\" sits alongside the out-of-scope \"do not change the 30 s busy timeout\". A stop during sqlite's busy wait itself is therefore still not prompt (up to 30 s). The operator accepted this as a limit.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe change is confined to `engine/server/db/jobs/translate-worker.py`, its two docs and its test file. `db.py` and `subtitles.py` are not touched. The steps below are in the order the code runs.\n\n1. **Classify the error at the claim-time check (R1).** A small module-level predicate in the worker, named for example `is_transient_db_error`, follows the shape of `is_interrupted_error` in `db.py`. It takes the `sqlite3.OperationalError` text, lowercases it, and returns True if it contains `locked`, `busy` or `unable to open`. Nothing else counts. A new exception class, `WhitelistBusy`, sits next to `JobStopped` and `JobTakenOver` and carries the error text.\n\n2. **Raise it only from the job path.** In `generate`, only the `resolve_video` call at line 422 gets a narrow guard. If an `OperationalError` from that call passes the predicate, it is raised again as `WhitelistBusy` chained from the original. Otherwise the original exception is re-raised unchanged, so it still reaches `run_job`'s catch-all and ends `failed` with exactly today's text (`OperationalError: no such column\u2026`, `no such table`, `file is not a database`, `malformed`). `resolve_video` itself is unchanged, so `command_enqueue` still reports and exits 1.\n\n3. **Requeue without spending the claim (R2).** `run_job` gets a new `except WhitelistBusy` branch, placed before the catch-all so the CUDA-OOM unload and `logging.exception` are never reached. The branch:\n   - calls the existing `requeue_translate_job(conn, *claim)`, the function the stop path already uses, which sets `queued`, gives back the attempt and leaves `queued_at` alone;\n   - writes no `error` and no `finished_at`;\n   - logs one `logging.warning` line: `[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s` with the error text.\n\n   If the requeue returns False (B1's route took the row over), nothing more is written; the log line still goes out. Because the attempt is given back, `MAX_CLAIMS` crash recovery never counts these requeues.\n\n4. **Tell `serve` to back off (R3).** `run_job` currently returns None. It will return a boolean that is True only from the `WhitelistBusy` branch, and `serve` reads it. When it is True, `serve` runs a back-off loop before its next claim:\n   - a deadline of `TRANSIENT_BACKOFF_SECONDS = 30.0`, a new module constant next to `POLL_SECONDS`;\n   - a loop that runs while `stop` is unset and the deadline has not passed. Each pass refreshes `progress[\"at\"]` and calls `time.sleep(min(POLL_SECONDS, remaining))`.\n\n   This keeps the `time.sleep`-not-`stop.wait` rule from the line 506 comment and refreshes progress at least as often as the idle poll, so the heartbeat thread keeps beating. A stop ends the wait within one slice, after which the outer `while not stop.is_set()` exits normally. The loop reads the module globals at call time, so tests can shorten both constants.\n\n5. **Repeat until the file is usable, then recover (R3, R4).** The job keeps its `queued_at`, so the next claim takes the same job again. Each cycle repeats on its own for as long as the cause lasts. Once the lock is released or the file restored, `resolve_video` succeeds and the job runs exactly like any other job.\n\n6. **Documentation (R5).** In `TRANSLATE_WORKER.md`:\n   - delete the first Known Gaps bullet;\n   - drop \"and a locked `whitelist.db`\" from the Error Texts line;\n   - add a paragraph to Job Pipeline step 1, with a one-line reference in Serve Loop for the back-off, covering:\n     - what counts as transient: locked, busy, unable to open (updater merge, restore);\n     - the job returns to `queued` with `attempts` restored and `queued_at` kept;\n     - the about 30 s back-off, which a stop ends promptly;\n     - the cycle repeats until the file is usable;\n     - every other database error still fails the job;\n   - add the warning line to Logs.\n\n   In `DEPLOYMENT.md:353`, rewrite the job half of the row: the job stays `queued`, the journal shows the warning line, and the job runs on its own once the merge or restore ends. The `enqueue` half stays as it is. Everything is written as current state, one paragraph per line.\n\n7. **Tests (R6).** All new tests go in `tests/active/test_translate_worker.py`, reusing `Rig`.\n   - Injected `sqlite3.OperationalError(\"database is locked\")` from a patched `resolve_video`: the row ends `queued`, `attempts` 0, `queued_at` `QUEUED_AT`, with no `error` or `finished_at`. The test also checks the warning-level log record (via `caplog`) names the key and the text, and that `run_job` returns True.\n   - Real missing file: `rig.whitelist` is deleted before the run. Same outcome.\n   - Real lock: `BEGIN EXCLUSIVE` is held on the rig's rollback-journal whitelist, then released. Same outcome, about 30 s of runtime (see Tradeoffs).\n   - Control: an injected `no such column` ends `failed` with `OperationalError: no such column\u2026`, and `run_job` returns falsy.\n   - Recovery: after a transient requeue, the lock is released or the file rewritten, the job is claimed again through `claim_translate_job` (attempts back to 1) and `run_job` ends `ready`.\n   - Serve-level test, in-process on a thread, with `POLL_SECONDS` and `TRANSIENT_BACKOFF_SECONDS` shortened on the loaded module, a stub runner, and `resolve_video` patched to raise transiently and record call times:\n     - the second claim comes no sooner than the back-off after the first;\n     - `progress[\"at\"]` keeps advancing during the wait;\n     - a `stop` set mid-back-off makes `serve` return within about one slice.\n\n     Setting `stop` from the test thread is safe here; the deadlock the line 506 comment describes needs a signal handler running on the main thread.\n\n   The existing stall test holds `BEGIN EXCLUSIVE` for about 16 s, below the 30 s busy timeout, so its job still ends `not in whitelist` and it is unaffected.\n\n### Alternatives considered\n\n- **Return value from `run_job` vs other signals.**\n  - A flag in the shared `progress` dict would mix the stall clock with control flow.\n  - Letting `WhitelistBusy` propagate up to `serve` would split one job's handling across two functions and bypass `run_job`'s \"exactly one end state\" contract.\n  - A return value is the smallest signal and is local to the one caller.\n- **Guard in `generate` vs inside `resolve_video`.** Classifying inside `resolve_video` would also change `command_enqueue`, which is out of scope. Classifying in `run_job`'s catch-all by inspecting any `OperationalError` would also catch transient `subtitles.db` errors from later steps, which is also out of scope. A guard around the one claim-time call is the only place that matches R1 exactly.\n- **Predicate in `db.py` vs in the worker.** `db.py` holds the precedent. But there is a single caller, and the three substrings are an operator decision about this worker's policy, not a general database fact. Keeping the predicate in the worker touches one fewer file. It can move into `db.py` if a second caller appears.\n- **A new exception vs catching `OperationalError` in `run_job`.** A dedicated exception keeps the classification at the call site that is in scope. It also lets `run_job` list it alongside `JobStopped` and `JobTakenOver` in the same style.\n- **Making the busy timeout a constant so a real-lock test runs fast.** Rejected for now. It would be a refactor made only for the test, and the value must stay 30 s anyway. If the 30 s test proves too slow, this is the upgrade path.\n\n### Risks, gotchas and limitations\n\n- **Substring matching depends on sqlite's wording.** `unable to open` also covers `unable to open database file` caused by a permissions problem or a missing directory. Those would also requeue and back off forever, which is the operator's chosen set. The repeating warning line in the journal is how an operator spots it.\n- **Accepted limit:** a stop that arrives during sqlite's own 30 s busy wait still takes up to about 30 s to take effect.\n- **Accepted limit:** while the head job is blocked, the jobs behind it wait.\n- **Unplanned limit: idle unload is skipped.** `serve` resets `idle_since` after every `run_job`, and the idle-unload check only runs when nothing is claimed. So a model already loaded by an earlier job stays in VRAM for as long as the lock or missing file lasts. I left this unhandled to keep the change small. The cheap fix is to skip the `idle_since` reset on a transient requeue and run the same unload check in the back-off loop.\n- **Log volume.** Under a lock held long-term, the warning repeats about once a minute (30 s busy wait plus 30 s back-off). Under a missing file it repeats about every 30 s. This is intentional, so the condition shows in the journal.\n- **Test patching.** Shortening the constants only works because the back-off loop reads module globals at call time, so the design must not bind them as default arguments.\n\n### Tradeoffs the operator is accepting\n\n- One real-lock test adds about 30 s to the suite, about the same as the triage probe. The injected-lock and missing-file tests cover the same branch in milliseconds. If 30 s is too much, the real-lock test can be dropped (R6 allows the injected form alone) or the timeout constant can be hoisted.\n- A permanently unreadable `whitelist.db` (a missing file or a permissions error) never fails the job. It requeues forever and shows only in the warning log, because the repeat is not capped (R3 asks for that).\n- A loaded model stays resident through a prolonged lock (see the unplanned limit above), unless the operator wants the small idle-unload addition.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impacts>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"new module-level predicate is_transient_db_error (name per plan)\">\n**What changes:** a new function returns True when the lowercased `sqlite3.OperationalError` text contains `locked`, `busy` or `unable to open`. The plan models it on `is_interrupted_error` in `engine/server/data/db.py:68`. The closer match inside this file is `is_cuda_oom` (`translate-worker.py:351-353`): a one-line docstring, `return isinstance(...) and \"...\" in str(exc).lower()`. Put the new function next to it, or next to the exception classes at :81-90.\n\n**What depends on it:** only the new guard in `generate`.\n\n**Regression risk:**\n- Low for the code itself.\n- The behavioural risk is the substring set. `unable to open database file` is also what sqlite raises when `--whitelist-db` names a wrong path or a missing parent directory. `connect_readonly_db` (`db.py:85-94`) uses `mode=ro`, so it never creates the file. Today a mistyped `--whitelist-db` fails each job with `OperationalError: unable to open database file`. After this change the head job requeues forever, the whole queue stalls, and only the warning line shows it. `command_run` (:520-558) does not check that `--whitelist-db` exists at start.\n- `sqlite3.DatabaseError` subclasses that are not `OperationalError` (`file is not a database`, `database disk image is malformed`) never reach the predicate, which is correct. A whitelist swapped mid-read during a restore could raise `malformed` and still fail the job for good. That is outside R1 but worth knowing.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"new exception class WhitelistBusy, beside JobFailed/JobStopped/JobTakenOver (:81-90)\">\n**What changes:** a new `Exception` subclass with a one-line docstring in the style of its neighbours, for example \"whitelist.db was locked, busy or could not be opened at claim; the job is requeued without spending its claim\". It carries the error text.\n\n**What depends on it:**\n- the guard in `generate` raises it;\n- `run_job` catches it.\n\n**Regression risk:**\n- It must subclass `Exception` directly, never `JobFailed`. Otherwise the `except JobFailed` branch (:466) would end the job `failed`.\n- `run_job` must catch it before `except Exception` (:469).\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"generate() (:420-452), the resolve_video call at :422\">\n**What changes:**\n- A narrow `try/except sqlite3.OperationalError` around only the `resolve_video(args.whitelist_db, *claim[:2], args.max_duration)` call.\n- On a transient error it raises `WhitelistBusy(str(exc)) from exc`. On anything else it re-raises unchanged (bare `raise`).\n- The `refusal is not None` check and everything after it stay outside the try, so no other step's `OperationalError` is classified. That includes `subtitles.db` writes from `store_ready_subtitles` and `mark_translate_finished`.\n- The docstring may need a clause on the transient case.\n\n**What depends on it:**\n- `run_job` (:459), and through it `serve`;\n- every job-pipeline test in `tests/active/test_translate_worker.py`;\n- the bounds case `not in whitelist at claim` (test file :306), which must still end `failed` `not in whitelist`.\n\n**Regression risk:**\n- Medium. A guard placed too wide would turn transient `subtitles.db` lock errors into requeues, which is out of scope.\n- A guard catching `sqlite3.Error` rather than `OperationalError` would still be safe, because the predicate is false for other texts. But the plan says `OperationalError`, and the `no such column` control test pins the text (`OperationalError: no such column\u2026`, built at :474 from `type(exc).__name__`).\n- The unchanged re-raise must keep the original type, so use bare `raise`, not `raise exc from ...`.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"resolve_video() (:93-110)\">\n**What changes:** nothing. The plan keeps it unchanged.\n\n**What depends on it:**\n- `command_enqueue` (:122, which catches `sqlite3.Error` and exits 1);\n- `generate` (:422);\n- the tests, which will monkeypatch it on the loaded module (`monkeypatch.setattr(rig.worker, \"resolve_video\", ...)`). `generate` looks the name up as a module global, so the patch takes effect.\n\n**Regression risk:** none if left alone. The `connect_readonly_db` call (:95) sits outside its try/finally. A missing file therefore raises `unable to open database file` from the connect, before `busy_timeout` is set. The missing-file test relies on this.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"command_enqueue() (:113-148)\">\n**What changes:** nothing (out of scope). It still prints `error: whitelist.db: <text>` and returns `EXIT_ERROR` on a locked or missing whitelist.\n\n**What depends on it:**\n- the enqueue tests;\n- the `DEPLOYMENT.md:291` and `:353` enqueue half;\n- `TRANSLATE_WORKER.md:54`.\n\n**Regression risk:** none, provided the predicate and the new exception live only on the `generate` path. Listed so the next step confirms enqueue output is unchanged.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"run_job() (:455-474): new except WhitelistBusy branch, return type None to bool, docstring\">\n**What changes:**\n- The signature becomes `-> bool`.\n- A new `except WhitelistBusy as exc:` branch, before `except Exception` (:469), and best placed next to `except JobStopped` (:461). It calls `requeue_translate_job(conn, *claim)` (return value ignored, as at :462), logs `logging.warning(\"[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s\", *claim[:2], exc)` and returns True.\n- Every other path returns False, falsy, or falls through to `return False`.\n- The docstring (\"Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job\u2026\") must add the transient requeue and the return value.\n- The branch writes no `error` and no `finished_at`.\n\n**What depends on it:**\n- `serve` (:510), its only production caller;\n- `Rig.run` in the tests (`test_translate_worker.py:480-487`), which discards the return value today and must return it, or the new tests call `rig.worker.run_job` directly;\n- the probe `tests/tmp/probe_45_whitelist_locked_at_claim.py:26`.\n\n**Regression risk:**\n- Medium. Placing the branch after `except Exception` would silently keep today's behaviour.\n- `WhitelistBusy` could reach `logging.exception`, which would log a traceback each cycle, and the CUDA-OOM `is_cuda_oom` unload (:471-472) would never apply.\n- `requeue_translate_job` is a conditional update on `state='running' AND started_at=?` (`subtitles.py:149-153, 161-163`). After a B1 takeover it returns False and writes nothing; the log line still goes out (plan).\n- `requeue_translate_job` itself can raise `sqlite3.Error` if `subtitles.db` is locked past its busy timeout. That would propagate out of the `except` branch, out of `run_job` and out of `serve`, ending the worker. The same exposure already exists on the `JobStopped` path. The next step may want to note it.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"serve() (:493-511): back-off loop after a transient requeue, idle_since, docstring\">\n**What changes:**\n- `run_job`'s result is read.\n- When it is True, a loop runs before the next claim: `deadline = time.monotonic() + TRANSIENT_BACKOFF_SECONDS`, then while not `stop.is_set()` and time remains, `progress[\"at\"] = time.monotonic()` and `time.sleep(min(POLL_SECONDS, remaining))`.\n- The comment at :506 explains why `time.sleep` is used and not `stop.wait` (Event.set from the SIGTERM handler on this thread would deadlock), so that rule carries over. The loop must read the module globals at call time, not bind them as default arguments, so tests can shorten them.\n- The docstring (:494) must mention the back-off.\n\n**What depends on it:**\n- `command_run` (:549);\n- the heartbeat thread (`heartbeat_loop` :477-490, which beats only while `time.monotonic() - progress[\"at\"] <= STALL_SECONDS`);\n- the subprocess tests for idle beats, SIGTERM and the stall (`test_translate_worker.py:889-983`);\n- plan 50's \"generation available\", which comes from the heartbeat age.\n\n**Regression risk:**\n- Medium.\n  - `idle_since = time.monotonic()` (:511) is reset after every `run_job`, and the unload check (:504) runs only when nothing is claimed. A model loaded by an earlier job therefore stays in VRAM through an outage (plan's unplanned limit).\n  - Head-of-line blocking: the same `queued_at` row is reclaimed every cycle (`claim_translate_job` ORDER BY `queued_at`, rowid, `subtitles.py:133`).\n  - During sqlite's 30 s busy wait inside `resolve_video`, `progress[\"at\"]` is not refreshed. That is far under `STALL_SECONDS = 600`, so the heartbeat continues.\n  - SIGTERM during the back-off: the handler runs on the main thread between sleeps, and PEP 475 resumes `time.sleep` after the handler. Exit therefore comes within one `POLL_SECONDS` slice (\u22642 s), well within `TimeoutStopSec=120` (DEPLOYMENT.md:264) and the tests' `STOP_WINDOW_SECONDS = 60`.\n- The idle path (job None) must stay exactly as it is, or `test_idle_run_beats...` (cadence 4.5-6.5 s) could change.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"module constants: new TRANSIENT_BACKOFF_SECONDS = 30.0 beside POLL_SECONDS (:71)\">\n**What changes:** a new constant, ideally with a one-line comment in the file's style, like the other constants (:62, :64, :69, :72).\n\n**What depends on it:**\n- `serve`'s back-off loop;\n- the serve-level test, which shortens it on the loaded module together with `POLL_SECONDS`.\n\n**Regression risk:**\n- Low.\n- `POLL_SECONDS` is also read by `AudioPipe.wait_samples` (:283-285), so a test that shortens it changes that wait too. In-process this only affects the module instance the test loaded (`_worker()` loads a fresh module per call).\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"command_run() (:520-558) and the SIGTERM handler (:537-538)\">\n**What changes:** nothing in the code.\n\n**What depends on it:** `serve`'s new back-off path. The stop event set by the handler ends the back-off. The `finally` (:550-554) then sets stop, joins the heartbeat and closes the connection.\n\n**Regression risk:**\n- Low.\n- Worst-case stop latency becomes: a stop arriving during sqlite's 30 s busy wait, plus at most one 2 s slice. That is still under 120 s.\n- `command_run` does not validate `--whitelist-db`, so a misconfigured path now gives a worker that loops instead of failing jobs (see the predicate entry).\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"requeue_translate_job() (:161-163), claim_translate_job() (:130-138), recover_translate_jobs() (:141-146), MAX_CLAIMS (:18)\">\n**What changes:** nothing. The plan does not touch `subtitles.py`.\n\n**What depends on it:** the new branch reuses `requeue_translate_job` exactly as `JobStopped` does: `state='queued'`, `attempts = attempts - 1`, `queued_at` untouched, conditional on `started_at`.\n\n**Regression risk:**\n- None to the store.\n- Semantics to confirm: the attempt is given back each cycle, so `recover_translate_jobs`' `MAX_CLAIMS` count never sees transient cycles.\n- A SIGKILL during a busy wait leaves `attempts=1`, `running`. The next start requeues it, as today.\n- The docstring of `requeue_translate_job` says \"(a stop mid-job)\". It now has a second caller, so the docstring is slightly stale. That is cosmetic, and the plan says not to touch this file. Flagged as uncertain whether to update.\n</impact>\n<impact path=\"engine/server/data/db.py\" element=\"is_interrupted_error() (:68-74), connect_readonly_db() (:85-94)\">\n**What changes:** nothing. The plan keeps the predicate in the worker.\n\n**What depends on it:** `connect_readonly_db` is what produces `unable to open database file` for a missing whitelist (`mode=ro`). `install_deadline_handler` only interrupts under `statement_deadline`, which `resolve_video` does not use, so `interrupted` never arises here.\n\n**Regression risk:** none (unchanged). Listed because the predicate's wording depends on this function's open mode.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_video_row() (:25), called by resolve_video\">\n**What changes:** nothing.\n\n**What depends on it:** `resolve_video`. I checked it does not swallow `sqlite3.OperationalError`: its excepts at :91/:94/:174 are HTTP and ValueError, and :440 is in a different route handler. So a lock or no-such-column error propagates to the guard unchanged.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/data/moderation.py\" element=\"list_active_denied_hosts() (:137), called by resolve_video\">\n**What changes:** nothing.\n\n**What depends on it:** `resolve_video`'s second read on the same connection. A lock that starts between the two statements raises here, and the guard catches it the same way, because the guard wraps the whole `resolve_video` call.\n\n**Regression risk:** none. The function does not catch sqlite errors.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"new job-pipeline tests (injected lock, real missing file, real BEGIN EXCLUSIVE lock, no-such-column control, recovery)\">\n**What changes:** five or more new tests that reuse `Rig`.\n\n**What depends on it:** the suite runtime. `tests/last_test_validation.json` records 40.6 s for this file today, and the real-lock test adds about 30 s.\n\n**Regression risk:** the risk is in the test mechanics.\n- `Rig.claim()` (:472-478) enqueues and asserts `('queued','queued')`. The recovery test must not call it a second time. It should reclaim through `claim_translate_job(rig.conn, \"en\", ...)` directly, assign `rig.job`, and assert attempts == 1.\n- Missing file: `rig.whitelist.unlink()`. The recovery step rewrites it with `_whitelist(rig.whitelist, JOB_VIDEOS, deny=True)`.\n- Real lock: `sqlite3.connect(rig.whitelist, isolation_level=None).execute(\"BEGIN EXCLUSIVE\")`, as in the stall test (:946-948). `_whitelist` leaves the file in rollback-journal mode (:190), which is what makes the EXCLUSIVE lock block readers. The holder must be closed in `finally`.\n- Logging: `caplog` at WARNING on the root logger. `setup_logging` is never called in-process, and `tests/active/conftest.py` has no logging setup, so capture should work. Assert on `record.levelno == logging.WARNING` and on `getMessage()` containing `v-1`, `peer.example` and the error text.\n- Control `no such column`: `error` must start with `OperationalError: no such column`. Check that `logging.exception` is still emitted, so the catch-all was taken.\n- `Rig.run` (:480-487) must return `run_job`'s value. If not, the tests call `rig.worker.run_job` with their own Namespace.\n- The probe imports `HOST`, `JOB_VIDEOS`, `_subtitles`, `_whitelist` and `_worker` from this module (`tests/tmp/probe_45...:10`), so do not rename these.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"new serve-level test (thread, shortened POLL_SECONDS/TRANSIENT_BACKOFF_SECONDS, stub runner, patched resolve_video)\">\n**What changes:**\n- A new test runs `rig.worker.serve(rig.conn, args, runner, stop, progress)` on a thread. That is safe because `connect_subtitles_db` opens with `check_same_thread=False` (`subtitles.py:27`).\n- It shortens the constants with `monkeypatch.setattr(rig.worker, \"POLL_SECONDS\", ...)` and `monkeypatch.setattr(rig.worker, \"TRANSIENT_BACKOFF_SECONDS\", ...)`.\n- `resolve_video` is patched to record `time.monotonic()` and raise `OperationalError(\"database is locked\")`.\n- The job is only enqueued, not claimed through `Rig.claim`, because `serve` claims it.\n- `StubRunner` has `model = None` and `unload`, which is all `serve` touches.\n\n**What depends on it:** nothing else.\n\n**Regression risk:**\n- Flakiness and hangs.\n  - Use a daemon thread, and `stop.set()` plus `join(timeout)` in `finally`, so a failing assert never hangs the session.\n  - The timing assertions (second claim \u2265 back-off after the first; stop mid-back-off returns within about one slice; `progress[\"at\"]` advances) need margins for a loaded machine. Existing tests use wide margins, for example `BEAT_GAP_MS`.\n- Setting `stop` from the test thread is fine (no signal handler involved).\n- Shortening `POLL_SECONDS` also affects `AudioPipe.wait_samples` on that module instance. This is irrelevant here because the job never reaches the download.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"module docstring (:1-37)\">\n**What changes:** the docstring is the file's spec, listing every behaviour under test. It needs new bullets:\n- under Outcomes, or a new paragraph, the transient requeue (injected lock, missing file, real lock), the `no such column` control and recovery;\n- under Service, or a new paragraph, the serve back-off, heartbeat progress and stop.\n\n**What depends on it:** reviewers. The project keeps this docstring exhaustive.\n\n**Regression risk:** documentation only. Omitting it leaves the spec stale.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on (:932-983), constants STALLED_WINDOW_SECONDS/TEST_STALL_SECONDS/RESUME_SECONDS and the comment at :181\">\n**What changes:** nothing intended.\n\n**What depends on it:** the stall test holds `BEGIN EXCLUSIVE` on the whitelist while the subprocess worker is inside `resolve_video`'s 30 s busy wait. The hold lasts from the claim, which can take up to 10 s (:954), through `TEST_STALL_SECONDS + 1` (5 s) and `STALLED_WINDOW_SECONDS` (11 s). That is about 16-26 s, and the comment at :181 says about 18 s.\n\n**Regression risk:**\n- Low, but the failure mode changes. Today, on a slow machine where the hold passes 30 s, the job fails with `OperationalError: database is locked`.\n- After this change the job is requeued instead and the worker backs off for 30 s, with the heartbeat beating during it. So:\n  - the `_jobs(...) == [(\"running\", None)]` assertion at :962 would read `queued`, or `running` again;\n  - the :972 `(\"failed\", \"not in whitelist\")` assert would wait for a reclaim beyond `RESUME_SECONDS = 8`.\n- Either way it would fail, as it would today. The margin is unchanged.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept (:848-852) and the bounds case 'not in whitelist at claim' (:306, test :712)\">\n**What changes:** nothing.\n\n**What depends on it:**\n- the stop test, which shares the `requeue_translate_job` call with the new branch;\n- the `not in whitelist` case, which exercises the refusal path right after the new guard.\n\n**Regression risk:** low. The bounds case would catch a guard that swallowed the refusal. The stop test would catch a reordering of the excepts that broke `JobStopped`.\n</impact>\n<impact path=\"tests/tmp/probe_45_whitelist_locked_at_claim.py\" element=\"the triage probe\">\n**What changes:** it asserts the old, buggy behaviour (`state == \"failed\"` and `(\"exists\", \"failed\")` on re-enqueue). After the fix it would fail.\n\n**What depends on it:** nothing in the suite. `tests/config.json` maps only `tests/active` files, and no pytest config collects `tests/tmp`. It also calls `run_job(..., runner=None, ...)`, which is still valid for the new branch.\n\n**Regression risk:**\n- None to the suite.\n- It is a stale artefact, so delete it, or leave it as a scratch file. I am not certain of the project's policy for `tests/tmp` probes after a fix; `probe_green.py`, `probe_race.py` and others remain there.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"test_translate_worker.py entry (:599-606) and per-test ids (:3583-3775)\">\n**What changes:** this is a generated artifact holding the file digest, the pass count (49) and the duration (40.6 s). The test runner rewrites it; nobody edits it by hand.\n\n**What depends on it:** the project's test-validation tooling. I am not sure what consumes it.\n\n**Regression risk:** none if it is regenerated by the normal test run. After the build, the count should rise and the duration grow by about 30 s or more.\n</impact>\n<impact path=\"tests/config.json\" element=\"test_translate_worker.py source mapping (:416-424)\">\n**What changes:** nothing. It already maps `translate-worker.py` and `subtitles.py` to this test file, so the change triggers the right test.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" element=\"Known Gaps (:152-155), Error Texts (:137), Job Pipeline step 1 (:83-85), Serve Loop (:79), Logs (:159-168)\">\n**What changes (as the plan states):**\n- delete the :154 bullet and keep the faster-whisper/VRAM bullet;\n- :137 becomes \"`<ExceptionType>: <text>` for anything else, including CUDA out-of-memory\";\n- add the transient paragraph at Job Pipeline step 1;\n- one line on the back-off in Serve Loop;\n- add the `whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: <error>` warning line to Logs.\n\n**What depends on it:**\n- `engine/server/README.md:25` and `DEPLOYMENT.md:230` point here;\n- `CONTEXT.md:19` points here.\n\n**Regression risk:** doc accuracy only. See the docs checklist for the other sections of this file that the plan does not name.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" element=\"Job Lifecycle (:29-39), Job Pipeline intro (:83), Bounds row 'Whitelist and denylist' (:102), Stop, Crash and Recovery (:141), Heartbeat (:150)\">\n**What changes (not named in the plan, but now partly inaccurate):**\n- :33 `queued` meaning: a transiently requeued job is `queued` again with its `attempts` restored.\n- :39 \"Every job ends in exactly one of\u2026\": still true but incomplete. A job may now cycle `queued`/`running` while `whitelist.db` is unavailable, as it already can on stop.\n- :83 \"each bound ending the job `failed`\": step 1 can now return the job to `queued` instead.\n- :141 SIGTERM bullet: \"Stop is checked each time the chunk loop wakes\". A stop during the back-off now ends within one 2 s slice, and a stop during sqlite's busy wait takes up to about 30 s.\n- :150 Heartbeat: progress is recorded \"on every serve pass and every chunk-loop wake (at most 2 s apart)\". The back-off loop also records it each slice. The busy wait records none for up to 30 s, which is under `STALL_SECONDS`.\n\n**Regression risk:** doc drift if these are left unchanged. I am uncertain whether the operator wants them all touched. At minimum :83 and :141 read wrong after the change.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage row :353 (whitelist.db locked)\">\n**What changes:** rewrite the job half.\n- Symptom: a job stays `queued`, or flips between `queued` and `running`, and the journal repeats `[translate-worker] whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: database is locked`, or `unable to open database file`.\n- Cause: the updater's merge holds the lock past 30 s, or a restore has removed the file.\n- Action: none for the job; it runs once the merge or restore ends.\n- The `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) stays.\n- A repeating `unable to open` with no restore in progress means the `--whitelist-db` path or its permissions are wrong. Worth one clause, given the misconfiguration risk.\n\n**What depends on it:** operators.\n\n**Regression risk:** doc only.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage row :348 'Jobs stay queued' and unit note :264 (TimeoutStopSec stop path)\">\n**What changes (not in the plan):**\n- :348 lists the causes of \"Jobs stay `queued`\" as no worker, or one long job ahead. A locked or missing `whitelist.db` is now a third cause, with the warning line as the tell. A cross-reference to :353 would do.\n- :264 describes the SIGTERM path. Adding \"or ends the back-off wait\" is optional; 120 s still covers the worst case (a 30 s busy wait plus a 2 s slice).\n\n**Regression risk:** doc drift only. :348 is the more important of the two.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"glossary entry 'Translate job' (:19)\">\n**What changes:** the entry says a job moves from `queued` to `running` and ends in one of three states, and that \"A job left `running` by a crash is requeued once\u2026\". It does not mention the stop requeue either. A clause such as \"a job whose `whitelist.db` check meets a lock or a missing file goes back to `queued` unspent and is retried after a back-off\" would keep the glossary complete.\n\n**Regression risk:** doc only. I am uncertain it is wanted: the plan names only the two docs, and the glossary already leaves out the stop requeue.\n</impact>\n<impact path=\"docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md\" element=\"Status line (:3), acceptance checkboxes (:95-98), file location\">\n**What changes:** on delivery, per `docs/project/triage-labels.md`:\n- `Status: bug, complete`;\n- the file moves to `docs/project/issues/archive/`;\n- the checkboxes get ticked.\n\n**What depends on it:** `docs/project/issues/issue-tracker.md:8` links it by path.\n\n**Regression risk:** a broken link if the file moves and the tracker row is not updated.\n</impact>\n<impact path=\"docs/project/issues/issue-tracker.md\" element=\"row 45 (:8)\">\n**What changes:** the state goes from `ready-for-agent` to `complete`, and the link moves to `archive/` if the issue file moves. It follows the convention of the earlier archived issues.\n\n**Regression risk:** stale tracker.\n</impact>\n<impact path=\"docs/project/roadmap.md\" element=\"F11-M2 PARTIAL line (:60)\">\n**What changes:** \"Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`.\" becomes a delivered statement, or moves into the Delivered list with a pointer to `TRANSLATE_WORKER.md`.\n\n**Regression risk:** stale roadmap.\n</impact>\n<impact path=\"docs/project/plans/50-translate-generation-in-page.md\" element=\"AC1 feature gate (heartbeat freshness) and AC3 polling while queued/running (:27-29, :49-53)\">\n**What changes:** nothing in this plan, which is a future consumer.\n\n**What depends on it:**\n- The page polls while the state is `queued` or `running`. During an outage it now sees `queued` and `running` alternating indefinitely, instead of a terminal `failed`.\n- Generation availability stays true, because the back-off keeps `progress[\"at\"]` fresh, so the heartbeat beats.\n\n**Regression risk:** none now. Plan 50's design should know a job can sit `queued` for the length of an updater merge.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"Translate worker paragraph (:25) and heartbeat note (:31)\">\n**What changes:** nothing needed. It defers to `TRANSLATE_WORKER.md` for the lifecycle. The heartbeat statement (\"stops beating when the serve loop stalls\") stays true, because the back-off refreshes progress.\n\n**Regression risk:** none. Checked and listed for completeness.\n</impact>\n</impacts>\n\n</impacts>\n\n<docs_checklist>\n\n<doc path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\">\nChanges:\n- Delete the Known Gaps bullet at :154, and keep the faster-whisper/VRAM bullet.\n- Error Texts :137: drop \"and a locked `whitelist.db`\".\n- Job Pipeline step 1 (:85): add a paragraph covering:\n  - what counts as transient: `locked`, `busy`, `unable to open`, for example during the updater merge or a restore;\n  - the job returns to `queued` with `attempts` restored and `queued_at` kept, with no `error` or `finished_at`;\n  - an about 30 s back-off (`TRANSIENT_BACKOFF_SECONDS`) that a stop ends within one 2 s slice;\n  - the cycle repeats until the file is usable;\n  - every other database error still fails the job as `<ExceptionType>: <text>`.\n- Pipeline intro :83 (\"each bound ending the job `failed`\"): qualify it for step 1's transient case.\n- Serve Loop :79: one line saying a transient requeue is followed by the back-off before the next claim, with progress refreshed during it.\n- Logs: add `whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: <error>` (a warning).\n- Also check :33 (meaning of `queued`) and :39 (\"Every job ends in exactly one of\u2026\").\n- Stop, Crash and Recovery :141: a stop during the back-off ends it promptly; a stop during sqlite's 30 s busy wait takes up to about 30 s.\n- Heartbeat :150: the back-off also records progress.\n- All written as current state, one paragraph per line.\n</doc>\n<doc path=\"DEPLOYMENT.md\">\nChanges:\n- Triage row :353: rewrite the job half. The job stays `queued` and the journal repeats the `whitelist.db unavailable, requeued` warning while the updater merge or a restore holds or removes `whitelist.db`. The job runs by itself afterwards, with no re-queue needed. A repeating `unable to open` outside a restore points at a wrong `--whitelist-db` path or permissions. Keep the `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) as it is.\n- Triage row :348 \"Jobs stay `queued`\": add a locked or missing `whitelist.db` (the warning line) as a cause.\n- Optionally :264 (TimeoutStopSec): the stop path also ends the back-off wait.\n</doc>\n<doc path=\"CONTEXT.md\">\n\"Translate job\" glossary entry (:19): optionally add that a job whose claim-time `whitelist.db` check meets a lock or a missing file returns to `queued` unspent and is retried after a back-off. It is uncertain whether this is wanted, since the entry already leaves out the stop requeue.\n</doc>\n<doc path=\"tests/active/test_translate_worker.py\">\nModule docstring (:1-37), which is the file's behavioural spec. Add:\n- the transient-requeue outcomes: injected lock, missing file, real EXCLUSIVE lock, the `no such column` control and recovery to `ready`;\n- the serve back-off behaviour: next claim no sooner than the back-off, progress advancing, stop ending the wait promptly.\n</doc>\n<doc path=\"docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md\">\nOn delivery: `Status: bug, complete`, the acceptance boxes ticked, and the file moved to `docs/project/issues/archive/`.\n</doc>\n<doc path=\"docs/project/issues/issue-tracker.md\">\nRow 45: state set to `complete`, with the link updated to the archive path.\n</doc>\n<doc path=\"docs/project/roadmap.md\">\n:60: replace \"Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`.\" with a delivered statement pointing at `TRANSLATE_WORKER.md`.\n</doc>\n\n</docs_checklist>\n\n<highest_risk>\n\nengine/server/db/jobs/translate-worker.py, the new predicate (`unable to open`): a wrong `--whitelist-db` path, a missing parent directory or a permissions problem gives the same sqlite text as a mid-restore missing file. A misconfigured worker that today fails each job visibly would instead requeue the head job forever and stall the whole queue, with only a warning line to show it; `command_run` checks nothing at start.\nengine/server/db/jobs/translate-worker.py, `run_job` except ordering and the `generate` guard scope: `WhitelistBusy` must be caught before `except Exception` (:469) and must not subclass `JobFailed`. The try must wrap only the `resolve_video` call at :422 and re-raise non-transient errors with a bare `raise`. Any slip silently keeps today's `failed` outcome, turns `subtitles.db` lock errors into requeues, or changes the `OperationalError: no such column\u2026` text.\nengine/server/db/jobs/translate-worker.py, `serve`'s back-off loop, with the new serve-level test in tests/active/test_translate_worker.py: the loop must keep `time.sleep` in `POLL_SECONDS` slices (the :506 deadlock rule), refresh `progress[\"at\"]` each slice so the heartbeat keeps beating, and read the module constants at call time so the threaded test can shorten them. The threaded test needs a daemon thread with `stop.set()` in `finally`, or a failure hangs the run. The existing subprocess stall test's whitelist hold (about 16-26 s against the 30 s busy timeout) now ends in a requeue and back-off rather than `failed` if a slow machine pushes it past 30 s.\n\n</highest_risk>",
    "step_4_reassess": "<summary>\nI opened every path in the inventory and checked its claims against the file. The worker (`translate-worker.py`) matches what the inventory says: the exception classes are at :81-90, `resolve_video` at :93-110 with `connect_readonly_db` outside its try, the call in `generate` at :422, `run_job`'s handler order at :455-474, `serve` at :493-511 including the :506 comment and the :511 `idle_since` reset, and the SIGTERM handler at :537-538. The store matches too: in `subtitles.py`, `requeue_translate_job` (:161-163) is a conditional `attempts - 1` update keyed on `started_at`, `claim_translate_job` orders by `queued_at`, rowid, and `connect_subtitles_db` uses `check_same_thread=False`. The test file matches: `Rig.run` (:480-487) discards the return value, `StubRunner` has `model = None` and `unload`, the stall test sits at :932-983 with the about 18 s comment at :181, the stop test at :848-852, and the bounds test at :712. Neither `tests/active/conftest.py` nor any pytest config sets up logging, so `caplog` will see the root logger's warning. The probe imports the five names and calls `run_job` as the inventory says. `tests/config.json` names `tests/tmp` as the \"working\" directory, so leaving the probe there fits the project's layout. Every doc line the inventory names reads as it claims: TRANSLATE_WORKER.md :33/:39/:79/:83/:137/:141/:150/:154, DEPLOYMENT.md :264/:291/:348/:353, CONTEXT.md:19, README :25/:31, plan 50 :27-29/:49-53, roadmap :60 and issue-tracker :8. The only production caller of `run_job` and `serve` is the worker itself; nothing else in the tree calls either. I found nothing the inventory is missing that would change the build. The plan holds against the inventory.\n<question id=\"1\">\nYes. The guard wraps only the `resolve_video` call at :422, and the refusal check stays outside it. So the transient set (`locked`, `busy`, `unable to open`) becomes `WhitelistBusy`, and everything else keeps today's path into the catch-all, with its `OperationalError: \u2026` text built from `type(exc).__name__` at :474. Placing `except WhitelistBusy` beside `except JobStopped`, ahead of `except Exception` at :469, keeps it away from the OOM unload and from `logging.exception`. `requeue_translate_job` already gives exactly what R2 asks for: `queued`, the attempt given back, `queued_at` untouched. So `MAX_CLAIMS` never counts these cycles. Because `queued_at` is kept, the head-of-queue ordering in `claim_translate_job` gives the next claim to the same job. That makes the repeat and the recovery (R3, R4) fall out of existing code. The back-off loop keeps the `time.sleep` rule from :506 and refreshes `progress[\"at\"]` every slice, so `heartbeat_loop`'s `STALL_SECONDS` check keeps passing. A stop ends the wait within one `POLL_SECONDS` slice. The triage probe already showed that a `BEGIN EXCLUSIVE` holder blocks an in-process `mode=ro` reader on the rollback-journal fixture (30.4 s), so the real-lock test will work. A missing file fails at `sqlite3.connect` with `mode=ro`, as the `connect_readonly_db` docstring (`db.py:88`) states, so the missing-file test will work too.\n</question>\n<question id=\"2\">\n- **One stuck job holds up the whole queue.** While `whitelist.db` is unusable, the oldest job is reclaimed every cycle and every job behind it waits.\n- **Repeating log lines.** The warning line repeats about every 60 s under a lock and about every 30 s for a missing file.\n- **Stop can take about 30 s.** A stop that lands during sqlite's 30 s busy wait takes up to about 30 s. A stop during the back-off ends within 2 s. Both stay well under `TimeoutStopSec=120`.\n- **The model stays in VRAM.** Because `idle_since` is reset after every `run_job` (:511), a model loaded by an earlier job stays resident for as long as the outage lasts.\n- **A wrong `--whitelist-db` path no longer fails loudly.** Today each job fails. Afterwards the worker loops without end, and only the warning line shows it, because `command_run` never checks the path.\n- **Plan 50's page sees no end state.** It would see `queued`/`running` alternate with no terminal state, while availability stays true, because the heartbeat keeps beating.\n- **Some restore failures still fail the job for good.** A restore that is caught half-written still fails the job permanently. A partial file raises `malformed`, which is a `DatabaseError` and not an `OperationalError`. A zero-length file opens as an empty database and raises `no such table: videos`, which is an `OperationalError` the predicate does not match. Both are outside R1's wording, so they fail as today.\n- **`requeue_translate_job` can itself fail.** It can raise if `subtitles.db` stays locked past its own 30 s timeout. That would escape `serve`, exactly as it already can on the `JobStopped` path.\n</question>\n<question id=\"3\">\nIn code, only the ordering and placement rules the inventory already lists:\n- `WhitelistBusy` subclasses `Exception`, not `JobFailed`;\n- its branch sits before the catch-all;\n- the re-raise is a bare `raise`;\n- the guard does not widen past :422;\n- the back-off reads the module globals at call time;\n- the idle path (job `None`) is left byte-for-byte as it is, so the beat-cadence test still holds.\n\nIn the tests, `Rig.run` should return `run_job`'s value. Nothing else in the suite consumes it, and `Rig.claim` must not be called twice in the recovery test. The existing stall test keeps its margin, because its hold of about 16-26 s is still under the 30 s busy timeout. In the docs, the two named files plus the drift the inventory lists:\n- TRANSLATE_WORKER.md :83 and :141 read wrong after the change;\n- :33, :39 and :150 are incomplete;\n- DEPLOYMENT.md :348 is missing a cause.\n</question>\n<question id=\"4\">\n- **Locked or missing whitelist.** A job whose claim-time check meets a lock, a busy file or an unopenable `whitelist.db` no longer ends `failed` as `OperationalError: \u2026`. It returns to `queued` with no `error`, `finished_at` or attempt spent, and the worker pauses for about 30 s before its next claim. This repeats until the file is usable.\n- **Wrong path or permissions.** A misconfigured path or bad permissions now gives a worker that loops and logs, where today it failed every job.\n- **New return value.** `run_job` returns a bool where it returned None. Only `serve` and the test rig see this.\n- **Unchanged.** `enqueue`'s output and exit codes, every non-transient database error, every other bound and end state, the stop and crash paths, and the idle loop.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Take the small idle-unload fix the plan already names.** On a transient requeue, skip the `idle_since` reset at :511, and run the same `runner.model is not None and time.monotonic() - idle_since >= IDLE_UNLOAD_SECONDS` unload check once per back-off slice. What it changes: a model loaded before an updater merge is released after 300 s, as on an idle queue, instead of staying resident for the whole outage. Cost: about 3 lines in `serve`, one Serve Loop sentence, and one more assertion in the serve-level test (`StubRunner` with `model` set to a sentinel and `IDLE_UNLOAD_SECONDS` shortened: `unloads == 1`). If you decline it, the plan's \"unplanned limit\" stays as written and should be copied into TRANSLATE_WORKER.md Known Gaps, so the docs do not claim the 300 s unload always applies.\n\n2. **Keep the real-lock test.** Acceptance criterion 1 explicitly reads \"an exclusive lock held on a rollback-journal `whitelist.db` throughout the check\". Only the real `BEGIN EXCLUSIVE` test proves that; the injected text does not. Cost: about 30 s on this file (40.6 s now, about 71 s after). Dropping it would leave criterion 1 shown only by the injected double. Hoisting the busy timeout into a constant to make the test fast stays rejected, as the plan says, because the issue puts changing the 30 s timeout out of scope.\n\n3. **Widen the doc edits to the full set the inventory found.**\n   - TRANSLATE_WORKER.md :83 (qualify \"each bound ending the job `failed`\"), :141 (a stop during the back-off ends within one 2 s slice; a stop during the busy wait takes up to about 30 s), :33/:39 (`queued` can mean returned unspent) and :150 (the back-off records progress).\n   - DEPLOYMENT.md :348, \"Jobs stay `queued`\": add the warning line as a third cause.\n   - DEPLOYMENT.md :353: add a clause that a repeating `unable to open` with no restore running means a wrong `--whitelist-db` path or wrong permissions.\n\n   Cost: a few sentences, no code. Without them, :83 and :141 say something false after the build. CONTEXT.md:19 already omits the stop requeue, so leaving it alone is consistent. Adding one clause there is optional and costs one line.\n\n4. **Restores and the docs.** The docs should not promise that a restore is always handled. The requeue covers a file that is absent or cannot be opened. A file caught half-copied fails the job permanently, as today: a partial file raises `malformed`, and a zero-length file raises `no such table: videos`. That matches R1's wording, so nothing should change in code. But the Job Pipeline paragraph should say \"missing\", not \"during any restore\". Cost: wording only.\n\n5. **Test doubles: the plan widens none.**\n   - `StubRunner` and `ScriptedHost` see no new calls. `serve` touches only `runner.model` and `runner.unload`, which `StubRunner` already has.\n   - The patched `resolve_video` in the new tests is a new double, built to record call times and raise; no existing double is widened.\n   - `Rig.run` is a helper, not a double. Make it return `run_job`'s value. Cost: one word, no change to any existing assertion.\n\n6. **Housekeeping on delivery.**\n   - Leave or delete `tests/tmp/probe_45_whitelist_locked_at_claim.py`. `tests/config.json` names `tests/tmp` as the working directory and nothing collects it, so it is harmless either way. It now asserts the old behaviour, so deleting it avoids confusion. Cost: none.\n   - Mark issue 45 `Status: bug, complete`, move it to `issues/archive/`, and update issue-tracker.md:8's link and state and roadmap.md:60. Cost: three small edits. Skipping the tracker update leaves a broken link once the file moves.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft: issue 45, requeue and back off when `whitelist.db` is locked or missing at claim\n\nI read the following before drafting: `translate-worker.py` lines 55-154 and 340-564 (constants, exception classes, `resolve_video`, `command_enqueue`, `is_cuda_oom`, `generate`, `run_job`, `heartbeat_loop`, `serve`, `command_run`), the test file's docstring, `_whitelist`, `_worker`, `Rig`, `StubRunner` and the outcome tests at :799-852, `TRANSLATE_WORKER.md` lines 25-168, and the `DEPLOYMENT.md` rows at :264, :348 and :353. Every claim below is checked against those lines.\n\n### What has to be tested\n\n- The classification at the claim-time check: three real or injected transient forms requeue the job. A non-transient error fails it with today's text, and a refusal (`not in whitelist`) still fails the job; the existing bounds case already covers the refusal.\n- The row after a transient requeue: `queued`, `attempts` 0, `queued_at` 1000, no `error`, no `finished_at`, and no remote request made.\n- The log: exactly one WARNING record naming the key and the error text, and no ERROR or traceback record.\n- The `run_job` return value: True only on a transient requeue.\n- `serve`: the reclaim comes at least one back-off after the first claim; `progress[\"at\"]` advances during the back-off; a stop during the back-off returns within about one slice.\n- Recovery: the same row, claimed again, runs to `ready`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/db/jobs/translate-worker.py` | 1 constant, 1 exception class, 1 predicate, a 5-line guard in `generate`, a new branch and a bool return in `run_job`, a back-off loop in `serve`, 3 docstrings |\n| `tests/active/test_translate_worker.py` | `Rig.run` returns the result; 2 imports, 2 constants and 2 helpers; 4 test functions (8 cases); docstring bullets |\n| `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` | the sections listed under Documentation |\n| `DEPLOYMENT.md` | rows :353 and :348, the note at :264 |\n| issue 45, `issue-tracker.md`, `roadmap.md` | delivery bookkeeping |\n\n`db.py`, `subtitles.py`, `resolve_video` and `command_enqueue` are unchanged.\n\n### `translate-worker.py`\n\n**Constant**, placed after `POLL_SECONDS = 2.0` (:71) with a comment in the file's style:\n\n```python\nPOLL_SECONDS = 2.0\n# Wait after a claim found whitelist.db locked or missing, before the same head job is claimed again (R3).\nTRANSIENT_BACKOFF_SECONDS = 30.0\n```\n\n**Exception**, after `JobTakenOver` (:89-90). It subclasses `Exception` directly and never `JobFailed`; otherwise the `except JobFailed` branch would end the job `failed`.\n\n```python\nclass WhitelistBusy(Exception):\n    \"\"\"whitelist.db was locked, busy or could not be opened at claim; the job is requeued without spending its claim.\"\"\"\n```\n\n**Predicate**, after `is_cuda_oom` (:351-353), in the same shape:\n\n```python\ndef is_transient_db_error(exc: BaseException) -> bool:\n    \"\"\"sqlite3 names a locked, busy or unopenable database in an OperationalError's text; corrupt or partial files are not transient.\"\"\"\n    return isinstance(exc, sqlite3.OperationalError) and any(word in str(exc).lower() for word in (\"locked\", \"busy\", \"unable to open\"))\n```\n\nLadder: rung 2. This is the existing `is_cuda_oom` shape, not a reuse of `db.is_interrupted_error`, because there is one caller and the word set is this worker's policy. It is an inline tuple, not a named constant, because it is read in one place only.\n\n**`generate`**: the guard wraps only the call at :422. The refusal check and everything after it stay outside the `try`, so `subtitles.db` errors from later steps are never classified. A bare `raise` keeps the original type, so the catch-all still writes `OperationalError: \u2026`.\n\n```python\ndef generate(conn: sqlite3.Connection, claim: tuple[str, str, str, int], args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> str:\n    \"\"\"AC3 for one claim (video_id, instance_domain, target_language, started_at), each bound raising JobFailed before the next remote request, a locked or missing whitelist.db raising WhitelistBusy; the end state written.\"\"\"\n    try:\n        row, refusal = resolve_video(args.whitelist_db, *claim[:2], args.max_duration)\n    except sqlite3.OperationalError as exc:\n        if is_transient_db_error(exc):\n            raise WhitelistBusy(str(exc)) from exc\n        raise\n    if refusal is not None:\n        raise JobFailed(refusal)\n    ...  # unchanged from :425\n```\n\n`resolve_video` is looked up as a module global when the call runs, so `monkeypatch.setattr(rig.worker, \"resolve_video\", \u2026)` takes effect. A missing file raises from `connect_readonly_db` at :95, before the `try/finally` there and before `busy_timeout` is set. It surfaces as `unable to open database file` at once.\n\n**`run_job`**: it now returns `-> bool`. The new branch sits right after `JobStopped`, so it is ahead of the catch-all and cannot reach `logging.exception` or the CUDA-OOM unload.\n\n```python\ndef run_job(conn: sqlite3.Connection, job: sqlite3.Row, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> bool:\n    \"\"\"Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job or whitelist.db is locked or missing at claim; a row B1's route took over is left as B1 wrote it. True only for the whitelist.db requeue, so serve backs off before claiming again.\"\"\"\n    claim = (job[\"video_id\"], job[\"instance_domain\"], TARGET_LANGUAGE, job[\"started_at\"])\n    try:\n        state = generate(conn, claim, args, runner, stop, progress)\n        logging.info(\"[translate-worker] job %s video_id=%s host=%s\", state, *claim[:2])\n    except JobStopped:\n        requeue_translate_job(conn, *claim)\n        logging.info(\"[translate-worker] stopped mid-job, requeued video_id=%s host=%s\", *claim[:2])\n    except WhitelistBusy as exc:\n        # No error, no finished_at: the attempt is given back, so MAX_CLAIMS never counts these cycles; False from the requeue (B1 took over) writes nothing more.\n        requeue_translate_job(conn, *claim)\n        logging.warning(\"[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s\", *claim[:2], exc)\n        return True\n    except JobTakenOver:\n        ...  # the three remaining branches are unchanged (:464-474)\n    return False\n```\n\nThe requeue's return value is ignored here, as it is at :462. One known exposure is unchanged: if `requeue_translate_job` itself raises because `subtitles.db` is locked past its own timeout, the exception propagates out of `serve`. The `JobStopped` path already has the same exposure, and `subtitles.db` locking is out of scope.\n\n**`serve`**: the idle path (:503-508) is unchanged byte for byte, which protects the 4.5-6.5 s beat-cadence test.\n\n```python\ndef serve(conn: sqlite3.Connection, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> None:\n    \"\"\"Claim and run jobs one at a time until stop, polling every POLL_SECONDS when idle, waiting TRANSIENT_BACKOFF_SECONDS after a whitelist.db requeue, and unloading the model after IDLE_UNLOAD_SECONDS without a job.\"\"\"\n    idle_since = time.monotonic()\n    while not stop.is_set():\n        ...  # unchanged through the claimed log line (:497-509)\n        if run_job(conn, job, args, runner, stop, progress):\n            # Back off in POLL_SECONDS slices of time.sleep, as above, so a stop ends the wait within one slice and progress stays as fresh as on the idle poll.\n            deadline = time.monotonic() + TRANSIENT_BACKOFF_SECONDS\n            while not stop.is_set() and (remaining := deadline - time.monotonic()) > 0:\n                progress[\"at\"] = time.monotonic()\n                time.sleep(min(POLL_SECONDS, remaining))\n        idle_since = time.monotonic()\n```\n\nBoth constants are read from module globals at run time and are not bound as defaults, so the serve test can shorten them. After a stop, the inner loop exits, then the outer `while` exits, and `command_run`'s `finally` runs as it does today. `idle_since` keeps being reset after every `run_job`; that is the plan's named limit (no idle unload during an outage), not changed here.\n\n### `tests/active/test_translate_worker.py`\n\nTwo imports, `contextlib` and `logging`. `Rig.run` changes to `-> bool` and `return self.worker.run_job(...)`. Existing callers ignore the result, so they are unaffected.\n\n```python\nLOCKED = \"database is locked\"\nUNOPENABLE = \"unable to open database file\"\n# Shortened on the loaded module for the serve test; margins sized for a loaded machine.\nBACKOFF_SECONDS = 1.0\nSLICE_SECONDS = 0.05\n\n\ndef _raising(text: str, then=None):\n    \"\"\"A resolve_video stand-in raising OperationalError(text), on every call, or on the first only and then `then`.\"\"\"\n    calls: list[float] = []\n\n    def resolve(*args):\n        calls.append(time.monotonic())\n        if then is not None and len(calls) > 1:\n            return then(*args)\n        raise sqlite3.OperationalError(text)\n\n    resolve.calls = calls\n    return resolve\n\n\ndef _until(predicate, seconds: float) -> bool:\n    deadline = time.monotonic() + seconds\n    while not predicate():\n        if time.monotonic() > deadline:\n            return False\n        time.sleep(0.01)\n    return True\n\n\n@contextlib.contextmanager\ndef _exclusive(path: Path):\n    \"\"\"BEGIN EXCLUSIVE on the rollback-journal whitelist, held for the block; readers wait out their busy timeout.\"\"\"\n    holder = sqlite3.connect(path, isolation_level=None)\n    try:\n        holder.execute(\"BEGIN EXCLUSIVE\")\n        yield\n    finally:\n        holder.close()\n```\n\n**Transient requeue**, three cases. The real-lock case adds about 30 s, the same as the triage probe; it is kept because R6 prefers it.\n\n```python\n@pytest.mark.parametrize(\"case\", [\"injected lock\", \"missing file\", \"held EXCLUSIVE lock\"])\ndef test_a_whitelist_db_locked_or_missing_at_claim_requeues_the_job_unspent_with_one_warning(rig, monkeypatch, caplog, case):\n    text = UNOPENABLE if case == \"missing file\" else LOCKED\n    hold = contextlib.nullcontext()\n    if case == \"injected lock\":\n        monkeypatch.setattr(rig.worker, \"resolve_video\", _raising(LOCKED))\n    elif case == \"missing file\":\n        rig.whitelist.unlink()\n    else:\n        hold = _exclusive(rig.whitelist)\n    rig.claim()\n    with hold:\n        assert rig.run(StubRunner(rig)) is True\n    row = rig.row()\n    assert (row[\"state\"], row[\"attempts\"], row[\"queued_at\"], row[\"error\"], row[\"finished_at\"]) == (\"queued\", 0, QUEUED_AT, None, None), row\n    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]\n    assert len(warnings) == 1 and all(part in warnings[0] for part in (\"[translate-worker]\", \"v-1\", HOST, text)), warnings\n    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]  # not the catch-all\n    assert rig.instance.opened == [] and rig.media.opened == []\n```\n\n`rig.claim()` runs before the lock is taken, because the claim writes `subtitles.db`, not the whitelist, so the order does not matter for the lock itself. Taking the lock after the claim keeps the hold to the busy wait alone. `setup_logging` is never called in-process, and pytest's caplog handler sits on the root logger at level 0, so WARNING and ERROR records are captured without `set_level`.\n\n**Non-transient control**, two cases. One is injected; the other is a real zero-byte file, which raises `no such table: videos` from `fetch_video_row`.\n\n```python\n@pytest.mark.parametrize(\"case\", [\"injected no such column\", \"zero-byte file\"])\ndef test_a_non_transient_whitelist_db_error_at_claim_still_ends_failed_with_its_text(rig, monkeypatch, caplog, case):\n    if case == \"zero-byte file\":\n        rig.whitelist.write_bytes(b\"\")\n        lead = \"OperationalError: no such table\"\n    else:\n        monkeypatch.setattr(rig.worker, \"resolve_video\", _raising(\"no such column: video_uuid\"))\n        lead = \"OperationalError: no such column\"\n    assert rig.run(StubRunner(rig)) is False\n    row = rig.row()\n    assert row[\"state\"] == \"failed\" and row[\"error\"].startswith(lead), row\n    assert [record.exc_info is not None for record in caplog.records if record.levelno == logging.ERROR] == [True]  # the catch-all's logging.exception\n    assert not [record for record in caplog.records if record.levelno == logging.WARNING]\n```\n\n**Recovery**, two cases. Both cases are fast; the real lock's own release is already shown by the existing stall test.\n\n```python\n@pytest.mark.parametrize(\"case\", [\"lock released\", \"file restored\"])\ndef test_a_requeued_job_claimed_again_once_whitelist_db_is_usable_runs_to_ready(rig, monkeypatch, case):\n    from data.subtitles import claim_translate_job\n\n    if case == \"lock released\":\n        monkeypatch.setattr(rig.worker, \"resolve_video\", _raising(LOCKED, then=rig.worker.resolve_video))\n    else:\n        rig.whitelist.unlink()\n    assert rig.run(StubRunner(rig)) is True\n    assert (rig.row()[\"state\"], rig.row()[\"attempts\"]) == (\"queued\", 0)  # control: requeued unspent\n    if case == \"file restored\":\n        _whitelist(rig.whitelist, JOB_VIDEOS, deny=True)\n    rig.job = claim_translate_job(rig.conn, \"en\", STARTED_AT + 1)\n    assert (rig.job[\"video_id\"], rig.job[\"started_at\"], rig.job[\"attempts\"]) == (\"v-1\", STARTED_AT + 1, 1)\n    assert rig.run(StubRunner(rig)) is False\n    row = rig.row()\n    assert (row[\"state\"], row[\"source\"], row[\"queued_at\"]) == (\"ready\", \"whisper\", QUEUED_AT), row\n```\n\nThe test reclaims through the store function directly. It does not call `Rig.claim` again, because that would enqueue a second time and fail its `(\"queued\", \"queued\")` assert.\n\n**Serve back-off**. It runs on a daemon thread over `rig.conn`, which `connect_subtitles_db` opens with `check_same_thread=False`. Setting `stop` from the test thread is safe because no signal handler is involved.\n\n```python\ndef test_serve_waits_the_back_off_before_reclaiming_keeps_progress_fresh_and_a_stop_ends_the_wait(rig, monkeypatch):\n    monkeypatch.setattr(rig.worker, \"POLL_SECONDS\", SLICE_SECONDS)\n    monkeypatch.setattr(rig.worker, \"TRANSIENT_BACKOFF_SECONDS\", BACKOFF_SECONDS)\n    locked = _raising(LOCKED)\n    monkeypatch.setattr(rig.worker, \"resolve_video\", locked)\n    assert tuple(enqueue_translate_job(rig.conn, \"v-1\", HOST, \"en\", 50, QUEUED_AT)) == (\"queued\", \"queued\")\n    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)\n    stop = threading.Event()\n    progress = {\"at\": time.monotonic()}\n    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, progress), daemon=True)\n    thread.start()\n    try:\n        assert _until(lambda: len(locked.calls) >= 2, 10 * BACKOFF_SECONDS)\n        assert locked.calls[1] - locked.calls[0] >= BACKOFF_SECONDS, locked.calls  # the reclaim waited the back-off\n        time.sleep(0.15)\n        first = progress[\"at\"]\n        time.sleep(0.15)\n        second = progress[\"at\"]\n        assert second > first and time.monotonic() - second < 0.3, (first, second)  # refreshed each slice during the wait\n        assert len(locked.calls) == 2  # control: still inside the second back-off\n        stopped_at = time.monotonic()\n        stop.set()\n        thread.join(5)\n        assert not thread.is_alive() and time.monotonic() - stopped_at < 0.5  # well under the ~0.7 s left of the back-off\n        assert len(locked.calls) == 2  # no claim after the stop\n        row = rig.row()\n        assert (row[\"state\"], row[\"attempts\"], row[\"queued_at\"]) == (\"queued\", 0, QUEUED_AT), row\n    finally:\n        stop.set()\n        thread.join(5)\n```\n\nThe shortened `POLL_SECONDS` also reaches `AudioPipe.wait_samples` on this module instance. That does not matter here, because no job reaches the download.\n\n**Module docstring**: add these to Outcomes.\n\n- `whitelist.db` unavailable at claim: an injected `database is locked`, a removed file (`unable to open database file`) and a real EXCLUSIVE lock held through sqlite's 30 s busy wait each leave the job `queued` with `attempts` 0 and `queued_at` 1000, no `error` or `finished_at`, nothing requested, and one WARNING `[translate-worker] whitelist.db unavailable, requeued \u2026` naming v-1, peer.example and the text, with no ERROR record. `run_job` returns True. An injected `no such column` and a zero-byte file (`no such table`) still end `failed` with `OperationalError: \u2026` through the logged catch-all, and `run_job` returns False. Once the lock is released or the file rewritten, the requeued row claimed again (attempts 1) ends ready/whisper with `queued_at` still 1000.\n\nAdd a paragraph after the Job-pipeline paragraph:\n\n- Serve back-off: `serve` runs in-process on a thread with `POLL_SECONDS` 0.05 s and `TRANSIENT_BACKOFF_SECONDS` 1 s on the loaded module, and `resolve_video` always locked. The second claim's lookup comes no sooner than 1 s after the first; `progress[\"at\"]` advances during the wait; a stop set during the wait returns `serve` within 0.5 s with no further claim and the row `queued`, `attempts` 0.\n\n### Documentation (current state, one paragraph per line)\n\n`TRANSLATE_WORKER.md`:\n- :33 `queued`: append \"A job requeued by a stop or by an unavailable `whitelist.db` is `queued` again with its `attempts` restored and its `queued_at` kept.\"\n- :39: \"Every job ends in exactly one of `ready`, `already_english` or `failed`; on the way it may return to `queued` unspent (a stop, or `whitelist.db` unavailable at claim). A failed key is never queued again.\"\n- :79 Serve Loop: append \"After a job requeued because `whitelist.db` was unavailable, it waits `TRANSIENT_BACKOFF_SECONDS` (30 s) in 2 s slices before the next claim, recording progress each slice; a stop ends the wait within one slice.\"\n- :83: \"For a claimed job, in order, each bound ending the job `failed` before the next remote request (step 1 may instead return the job to `queued`):\"\n- :85 step 1: add a paragraph. When the lookup raises a sqlite `OperationalError` naming `locked`, `busy` or `unable to open` (the updater's merge holding the file past the 30 s busy timeout, or a restore that has removed it), the job goes back to `queued` with `attempts` restored and `queued_at` kept, and no `error` or `finished_at` is written. A warning is logged and the worker backs off about 30 s, which a stop ends promptly. Because the job keeps the head of the queue, the cycle repeats until the file is usable, and the job then runs as any other. Every other database error (`no such table`, `no such column`, `file is not a database`, `malformed`) fails the job as `<ExceptionType>: <text>`.\n- :137: \"`<ExceptionType>: <text>` for anything else, including CUDA out-of-memory\".\n- :141 SIGTERM: append \"A stop during the back-off ends it within one 2 s slice; a stop during sqlite's 30 s busy wait on `whitelist.db` takes effect once that wait ends.\"\n- :150 Heartbeat: \"\u2026on every serve pass, every back-off slice and every chunk-loop wake (at most 2 s apart; a `whitelist.db` busy wait records none for up to 30 s)\u2026\"\n- :154: delete the bullet; the faster-whisper/VRAM bullet stays.\n- Logs: add \"`whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: <error>` (warning)\" after the `stopped mid-job` line.\n\n`DEPLOYMENT.md`:\n- :353, replace with:\n\n  `| A job stays `queued` and the journal repeats `whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: database is locked` (or `unable to open database file`), or `enqueue` prints `error: whitelist.db: database is locked` | The updater's merge holds `whitelist.db` past the 30 s busy timeout, or a restore has removed it. The worker requeues the job unspent and retries after a 30 s back-off; `enqueue` does not retry. A repeating `unable to open` with no restore in progress means the `--whitelist-db` path or its permissions are wrong | Nothing for the job: it runs once the merge or restore ends. Re-run `enqueue` after the updater run ends. Fix the path or permissions for a persistent `unable to open` |`\n- :348 cause: append \", or `whitelist.db` is locked or missing (see the `whitelist.db unavailable` row below)\".\n- :264: \"\u2026puts the job back on the queue without counting a claim, or ends the back-off wait, waits up to\u2026\".\n\n`CONTEXT.md`: not touched. The glossary entry already leaves out the stop requeue, the transient requeue is of the same kind, and the checklist marks it optional.\n\nDelivery bookkeeping:\n- issue 45: `Status: bug, complete`, the boxes ticked, the file moved to `archive/`;\n- `issue-tracker.md` row 45: state `complete` and the link pointed at `archive/`;\n- `roadmap.md:60`: \"Requeue with back-off when `whitelist.db` is locked or missing at claim is delivered (see `TRANSLATE_WORKER.md`).\"\n\n`tests/tmp/probe_45_whitelist_locked_at_claim.py` now asserts the old behaviour. It is not collected, and the draft leaves it alone, as other `tests/tmp` probes are left.\n\n### Check against plan and requirements (pass 1, converged)\n\n- R1: the guard wraps only the `:422` call; the three words match case-insensitively; other errors are re-raised as-is, so the catch-all writes today's text; `command_enqueue` is untouched. \u2713\n- R2: the existing `requeue_translate_job`; no `error` or `finished_at`; one WARNING with the `[translate-worker]` prefix, the key and the text; ahead of the catch-all, so no OOM unload and no traceback; a False from the requeue writes nothing more. \u2713\n- R3: a named 30 s constant; a bool return from `run_job`; `time.sleep` in `POLL_SECONDS` slices with progress refreshed and `stop` checked each slice; repeats each cycle. \u2713\n- R4: the recovery test, through `claim_translate_job`, to `ready`. \u2713\n- R5: every bullet in the settled checklist is covered. \u2713\n- R6: injected, real missing file, real lock, serve timing, stop and progress, the control, recovery and the warning log; existing tests untouched (the stall test's ~16-26 s hold is still below 30 s). \u2713\n\n### Limits carried from the plan\n\n- A stop during sqlite's busy wait still takes up to about 30 s.\n- Head-of-line blocking while the file is unavailable.\n- The model stays loaded through an outage: the idle unload is skipped. The upgrade path is to skip the `idle_since` reset and run the unload check inside the back-off loop.\n- A mistyped `--whitelist-db` loops instead of failing; the `DEPLOYMENT.md` row names it.\n- The suite grows by about 30 s for the real-lock case.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: `run_job`, reached through the existing `Rig` harness in `tests/active/test_translate_worker.py` (`rig.claim()` then `rig.run(StubRunner(rig))`, `Rig.run` changed to return `run_job`'s result), the same entry the outcome tests at :799-852 use. Beyond that seam are a patched module-global `resolve_video` (`_raising`), a real whitelist file that is deleted, zero-byte or held under `BEGIN EXCLUSIVE` by a second connection, and `caplog` on the root logger. c1 is parametrized over injected lock, missing file and held EXCLUSIVE lock (~30 s). For each it asserts every member of the row tuple (state `queued`, attempts 0, queued_at `QUEUED_AT`, error None, finished_at None), exactly one WARNING whose message carries `[translate-worker]`, `v-1`, `HOST` and the error text, no record at ERROR or above, `rig.instance.opened == []` and `rig.media.opened == []`, and `run_job` returning `is True`. These exclude, respectively: a requeue that spends the attempt or rewrites queued_at, a branch that writes error or finished_at, a missing or duplicated log line or one that omits key or text, a branch placed after the catch-all, a guard that lets the job proceed to a remote request, and a return value serve cannot read. c2 is parametrized over injected `no such column` and a zero-byte file. It asserts state `failed` with error starting `OperationalError: no such column` / `OperationalError: no such table`, exactly one ERROR record carrying exc_info, no WARNING, and `run_job` returning `is False`, which excludes an over-broad predicate or a guard that rewraps every OperationalError.</checkpoint>\n<name>Requeue at claim on a transient whitelist.db error</name>\n<intent>In `translate-worker.py`, a job whose claim-time `resolve_video` call hits a locked, busy or unopenable `whitelist.db` is returned by `run_job` to `queued` with its claim unspent and one warning logged, instead of failing. Every other `whitelist.db` error at claim still fails the job with today's `OperationalError: <text>`.</intent>\n<clause_1>A locked, busy or unopenable `whitelist.db` at claim leaves the job `queued` with attempts restored, `queued_at` kept, no `error` or `finished_at`, nothing requested, and one warning naming the key and the error text, and `run_job` returns True.</clause_1>\n<clause_2>Any other `whitelist.db` error at claim still ends the job `failed` with `OperationalError: <text>` through the logged catch-all, and `run_job` returns False.</clause_2>\n<files>engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Two seams. (a) `serve`, entered in-process on a daemon thread over `rig.conn`, which is opened `check_same_thread=False`. On the loaded module, `POLL_SECONDS` is 0.05 and `TRANSIENT_BACKOFF_SECONDS` is 1.0, `resolve_video` is patched to always raise `database is locked` and record monotonic call times, and a StubRunner is used. No existing harness drives `serve` in-process, because the beat tests use the real CLI under a pty, so this is a new in-process entry and the drafted test function is its harness. For c1 it waits for two lookups, then asserts `calls[1] - calls[0] >= BACKOFF_SECONDS`, which excludes a serve that ignores the bool and reclaims on the next 0.05 s poll. It also asserts the row is still `queued` with attempts 0 and queued_at kept, which shows the reclaim is the same head job. (b) `run_job` via `Rig.run`, then a direct `claim_translate_job(rig.conn, \"en\", STARTED_AT + 1)`, parametrized over lock released (`_raising(LOCKED, then=real resolve_video)`) and file restored (unlink, then rewrite with `_whitelist`). For c2 it asserts the intermediate control (`queued`, 0), then that the reclaim is `v-1` with attempts 1, then a final row of `ready`, `whisper` and queued_at `QUEUED_AT`. This excludes a requeue that leaves the row unclaimable or a reclaimed run that fails or rewrites queued_at.</checkpoint>\n<name>Back off before the reclaim, then recover</name>\n<intent>After a `whitelist.db` requeue, `serve` in `translate-worker.py` waits `TRANSIENT_BACKOFF_SECONDS` before claiming the same head job again, and once `whitelist.db` is usable that reclaimed job runs like any other.</intent>\n<clause_1>After a `whitelist.db` requeue, the next claim of the same head job comes no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first.</clause_1>\n<clause_2>Once the lock is released or the file restored, the requeued job claimed again runs to `ready` with its `queued_at` kept.</clause_2>\n<files>engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>The same in-process `serve` thread seam as phase 2, extending its serve test past the second lookup, while the worker is inside the second back-off. For c1 it samples `progress[\"at\"]` twice, 0.15 s apart, and asserts the second sample is larger and less than 0.3 s old. This excludes a back-off that sleeps the whole deadline in one call or never touches progress, which would let the heartbeat go dark. A control asserts that `len(calls) == 2`, so the samples were taken during the wait and not during a fresh claim. For c2 it sets `stop` from the test thread, joins with a 5 s timeout, and asserts the thread is dead within 0.5 s, well under the ~0.7 s left of the back-off. It also asserts `len(calls)` is still 2, with no claim after the stop, and that the row is still `queued` with attempts 0. This excludes a loop that ignores `stop` until the deadline and one that claims once more before exiting. Setting `stop` off the main thread is safe here because no signal handler is involved.</checkpoint>\n<name>Stay live during the back-off</name>\n<intent>The back-off wait in `serve` keeps the worker live: it refreshes `progress[\"at\"]` every `POLL_SECONDS` slice and a stop ends it within one slice.</intent>\n<clause_1>During the back-off, `progress[\"at\"]` keeps advancing at least once per slice.</clause_1>\n<clause_2>A stop set during the back-off makes `serve` return within about one slice without claiming again.</clause_2>\n<files>engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nThe split follows the order the code runs and the requirements. Phase 1 covers what `generate` and `run_job` do with a claim-time `whitelist.db` error (R1, R2), and its two clauses are the positive and negative halves of the classification. Phase 2 covers what happens next: the `serve` back-off (R3) and the recovery once the file is usable (R4). Phase 3 covers the liveness guarantees of the back-off loop: the heartbeat stays fresh and a stop is honoured. The phase 3 code is the same few lines of loop that phase 2 lands. Its clauses are kept separate because the serve behaviour holds four facts (wait, recover, progress, stop), and one phase carrying them would be drawn too wide; phase 3 extends phase 2's serve test rather than adding a new seam. The operator approved keeping the real-lock case and its ~30 s of suite time. Documentation (TRANSLATE_WORKER.md, DEPLOYMENT.md) and the issue/tracker/roadmap bookkeeping are not phases; Step 9 writes them from what was delivered. No credentials, live endpoints or manual steps are needed: every checkpoint runs in-process against temporary sqlite files.\n</rationale>",
    "author:tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py": "<assertions>\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:74 \u2014 (state, attempts, queued_at, error, finished_at) == (\"queued\", 0, 1000, None, None) for an injected lock, a missing file and a held EXCLUSIVE lock. This rules out the old fail path (observed: 'failed', 1, 1000, 'OperationalError: \u2026', <ms>), a requeue that spends the attempt or rewrites queued_at, and one that writes error or finished_at. \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:76 \u2014 exactly one WARNING record. This rules out a missing or duplicated log line (today there are 0). \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:78 \u2014 that warning's message contains `[translate-worker]`, `v-1`, `peer.example` and the observed error text (`database is locked` / `unable to open database file`). This rules out a line that leaves out the key, the host or the text. \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:79 \u2014 no record at ERROR or above. This rules out a branch placed after the catch-all and a catch-all that logs before requeueing (today there is one ERROR). \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:80 \u2014 rig.instance.opened == [] and rig.media.opened == []. This rules out a guard that lets the job go on to a remote request. \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:81 \u2014 the return of rig.run (that is, run_job) `is True`. This rules out a return value serve cannot read, and a None (today's value). \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:90 \u2014 (state, error) == (\"failed\", \"OperationalError: no such column: video_uuid\") for the injected case and (\"failed\", \"OperationalError: no such table: videos\") for the zero-byte file. This rules out an over-broad predicate that requeues these, and a guard that rewraps the text. \u2014 C2\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:92 \u2014 exactly one record at ERROR or above, and it is at ERROR. This rules out a rewrap that logs twice or at CRITICAL, and an exception that goes unlogged. \u2014 C2\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:93 \u2014 that record's exc_info is set and its type is sqlite3.OperationalError. This rules out a path that writes failed without going through the catch-all's logging.exception. \u2014 C2\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:94 \u2014 no WARNING record. This rules out the requeue branch's warning firing on a non-lock error. \u2014 C2\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:95 \u2014 the return of rig.run (that is, run_job) `is False`. This rules out None (today's value) and a True from an over-broad predicate. \u2014 C2\n</assertions>\n\n<probes>\nCommand: ValidateTests [\"tests/tmp/probe_45_phase1_scenarios.py\"] (30.3 s wall). On the existing Rig fixture this claimed v-1, broke whitelist.db five ways, called worker.run_job directly with caplog at INFO, then printed the result, the row, every log record and the hosts' opened lists. It printed:\n- injected `database is locked`: result None; row failed / attempts 1 / queued_at 1000 / error 'OperationalError: database is locked' / finished_at set; one ERROR record '[translate-worker] job error video_id=v-1 host=peer.example' with exc_info sqlite3.OperationalError; opened [] [].\n- deleted file: same shape, error 'OperationalError: unable to open database file'.\n- held under BEGIN EXCLUSIVE by a second connection: same shape after the ~30 s busy timeout, error 'OperationalError: database is locked'.\n- injected `no such column: video_uuid`: same shape, error 'OperationalError: no such column: video_uuid'.\n- zero-byte file: same shape, error 'OperationalError: no such table: videos'.\n- Rig.run's return annotation is currently 'None', and no WARNING record appeared in any case.\nCheckpoint run: ValidateTests [\"tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py\"] gave 5 failed (30.4 s). All three C1 cases fail at line 74 on ('failed', 1, \u2026) != ('queued', 0, \u2026). Both C2 cases get through lines 90\u201394 and fail only at line 95 (`assert None is False`), so the C2 row, ERROR and no-WARNING expectations are confirmed against real behaviour. Clean-up still needed: I have no delete tool, so tests/tmp/probe_45_phase1_scenarios.py is still on disk. It ends in `assert False`, so it should be deleted.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase1.py:86 \u2014 `_job(rig) == (\"queued\", 0, QUEUED_AT, None, None)`: state, attempts, queued_at, error, finished_at read back through a fresh connection after run_job, for a deleted whitelist.db and for one held under BEGIN EXCLUSIVE past the 30 s busy timeout. Rig.claim's control has already shown attempts 1 and started_at 2000.</assertion>\n<expected>(\"queued\", 0, 1000, None, None) for both cases. The current code instead gives (\"failed\", 1, 1000, \"OperationalError: ...\", <finished_at ms>), which is what the run showed at line 86 for both cases.</expected>\n<wrong_implementation>Today's catch-all, which fails the job: reads (\"failed\", 1, ...). A requeue that bumps queued_at or forgets to restore attempts (a plain UPDATE state='queued' and nothing else): reads attempts 1, or a queued_at that is not 1000. A fix that only catches \"database is locked\": reads (\"failed\", ...) in the missing-file case. One that only catches a missing file: reads (\"failed\", ...) in the held-lock case.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase1.py:88 and :90 \u2014 exactly one WARNING record, and its message contains \"[translate-worker]\", \"v-1\", \"peer.example\" and the error text the run produced (\"unable to open database file\" or \"database is locked\").</assertion>\n<expected>One WARNING per case. Its message carries the worker tag, both parts of the key, and the exact OperationalError text, which I took from the tracebacks of this run.</expected>\n<wrong_implementation>A silent requeue with no log, or an INFO-level log: 0 warnings. A warning logged both at the branch and again by a retry wrapper: 2 warnings. A warning reading \"whitelist busy, requeued\" that leaves out the key or the exception text: :90 fails.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase1.py:91 \u2014 no record at ERROR or above; :92 \u2014 rig.instance.opened == [] and rig.media.opened == [].</assertion>\n<expected>[] for ERROR records. [] for both hosts. The :92 absence is armed by the control at :78, which saw INSTANCE_THEN_JSON and [MEDIA_URL] on the same rig with whitelist.db intact. The :91 absence is armed by :104, where caplog captured the catch-all's ERROR in this same run.</expected>\n<wrong_implementation>Requeuing from inside the catch-all after logging.exception: one ERROR record at :91. Treating a locked lookup as \"not found\" or \"proceed without a row\" and going on to fetch captions: the instance shows CAPTIONS_URL at :92.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase1.py:93 \u2014 `result is True`, where result is run_job's own return value, called directly.</assertion>\n<expected>True. Today run_job returns None. Line 86 is the line the run stops on today; the assertion at :93 is never reached.</expected>\n<wrong_implementation>A requeue branch that falls through and returns None as run_job does today, or that returns False the way a failed job does: `None is True` / `False is True`.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase1.py:102 \u2014 (state, error) == (\"failed\", \"OperationalError: <text>\") for a videos table with video_uuid dropped (text \"no such column: v.video_uuid\") and for a zero-byte whitelist.db (text \"no such table: videos\").</assertion>\n<expected>(\"failed\", \"OperationalError: no such column: v.video_uuid\") and (\"failed\", \"OperationalError: no such table: videos\"). Both observed passing in this run, since this is today's behaviour, which the phase must keep.</expected>\n<wrong_implementation>A requeue branch that catches every sqlite3.OperationalError (or every sqlite3.Error): reads (\"queued\", None). Rewrapping the error as JobFailed(\"whitelist unavailable\"): reads (\"failed\", \"whitelist unavailable\").</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase1.py:104 and :105 \u2014 exactly one record at ERROR or above, at ERROR level, with exc_info[0] being sqlite3.OperationalError. :106 \u2014 no WARNING records.</assertion>\n<expected>One ERROR record that carries the OperationalError traceback (logging.exception at translate-worker.py:473), and no WARNING. Both observed passing in this run. The :106 absence is armed by :88, which requires exactly one WARNING in the C1 cases.</expected>\n<wrong_implementation>Sending these through the new branch's logging.warning before failing: 1 WARNING at :106. Catching these in a narrower handler that calls logging.error without exc_info: exc_info None at :105. Logging the error twice: 2 ERROR records at :104.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase1.py:107 \u2014 `result is False`, where result is run_job's own return value.</assertion>\n<expected>False. The run currently shows `assert None is False` at :107 in both cases, because run_job returns None today.</expected>\n<wrong_implementation>A run_job that returns only from the new branch and leaves the catch-all falling through: None. One that returns True for every handled exception: True.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes in the version handed to me, now rewritten. The docstring claims \"run_job returns True/False\", but the test read `rig.run(...)`. Rig.run (tests/active/test_translate_worker.py:487) discards run_job's return value, so `result` was always None and no implementation could ever pass. The test now calls `rig.worker.run_job` directly through `_run_job` (lines 52-55), using Rig.run's exact args. Every other docstring clause (state, attempts, queued_at, error, finished_at, no requests, one WARNING with the tag, key and text, no ERROR, the failed text, one ERROR with exc_info, no WARNING) has an assertion at lines 86-93 or 102-107. I added a control bullet to the docstring for the new control test.\n2. Absence only: there was a gap, now fixed. The \"nothing requested\" absence at :92 had no positive control proving the recorders see requests on this rig. I added test_control_an_intact_whitelist_reaches_both_hosts (:74-78). It passed: state ready, instance saw INSTANCE_THEN_JSON, media saw [MEDIA_URL]. The no-ERROR absence at :91 is armed by :104/:105, which passed in this run and show caplog capturing the catch-all's ERROR. The no-WARNING absence at :106 is armed by :88.\n3. Echoed literal: no. Every expected value is either a fixture constant (QUEUED_AT, HOST, \"v-1\") or an SQLite error text observed in the run, and the test performs none of production's transformation. Lines whose deletion turns it red after the phase: the new requeue call in run_job's lock/unopenable branch (:86), its logging.warning (:88), `return True` (:93), and the catch-all's `return False` (:107). translate-worker.py:473 logging.exception carries :104/:105, and :474 finish_translate_failed carries :102.\n4. One value: no. C1 is read at two real inputs: a missing file and a held EXCLUSIVE lock. C2 is read at two: a dropped column and a zero-byte file. Error texts are pinned per case against what that case produced.\n5. The double: yes in the version handed to me, now rewritten. The two \"inject\" cases monkeypatched `rig.worker.resolve_video`, a function this project owns, to raise a synthetic OperationalError. I dropped the injected lock case, since the real held EXCLUSIVE lock covers it. I replaced the injected no-such-column case with a real whitelist.db whose videos table has video_uuid dropped (ALTER TABLE ... DROP COLUMN). The monkeypatch fixture and the `_raising` helper are gone. The remaining doubles are the existing Rig's ScriptedHost (network) and StubRunner (whisper/VAD), which shim severed layers.\n6. It collects: yes, everything resolves. The `--collect-only` summary I was handed read \"no tests\", but every ValidateTests run collected the file. The latest run's summary was \"4 failed, 1 passed\" = 5 tests: 1 control + 2 C1 cases + 2 C2 cases, which matches what I wrote. All imported names (HOST, INSTANCE_THEN_JSON, MAX_DURATION, MEDIA_URL, QUEUED_AT, StubRunner, clip, rig) exist in tests/active/test_translate_worker.py. Rig has `.worker`, `.conn`, `.job`, `.clip`, `.whitelist`, `.instance.opened`, `.media.opened` and `.row()`, and run_job's signature is (conn, job, args, runner, stop, progress).\n7. Observed, not predicted: one value was predicted, and the run corrected it. I predicted \"no such column: video_uuid\" for the dropped-column case. The run showed `AssertionError ... 'OperationalError: no such column: v.video_uuid' != 'OperationalError: no such column: video_uuid'` at line 102, and I changed the expected text to the observed one. The tracebacks of this run show \"unable to open database file\", \"database is locked\" and \"no such table: videos\". The intact-path request lists come from the passing control. What I could not observe: the WARNING's contents (:88/:90) and the True return (:93). These are what the phase will produce, so they stay predictions. The phase's own run is what confirms them.\n8. Red, not green: yes. Final run: \"tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py  4 failed, 1 passed\", \"[exit status 1]\". The one pass is the control test.\n9. Red for the right reason: yes for the final run. Both C1 cases fail at line 86, `assert _job(rig) == (\"queued\", 0, QUEUED_AT, None, None)`, with `AssertionError: assert ('failed', 1,...) == ('queued', 0,...0, None, None)` / `At index 0 diff: 'failed' != 'queued'`. The tracebacks show `sqlite3.OperationalError: unable to open database file` and `sqlite3.OperationalError: database is locked` going through the catch-all: today's code fails the job instead of requeuing it. Both C2 cases pass lines 102-106 and fail at line 107, `assert result is False`, with `E  assert None is False`: run_job, now called directly, returns None today. The first run of the version handed to me also failed `None is False` at :95. That was a harness defect, because Rig.run drops the return value; it is fixed above. No control assertion failed in the final run: Rig.claim's control passed, and the intact-whitelist control passed.\n10. Observed expected output: the expected columns match the run. Where the run disagreed with me (v.video_uuid), I took the run's value. The C1 rows' expected values for :88-:93 are the phase's target, which this run cannot show because it stops at :86. The rows say so.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/server/db/jobs/translate-worker.py`\n\n- **New exception `WhitelistBusy`.** It sits next to `JobFailed`, `JobStopped` and `JobTakenOver` and subclasses `Exception` directly, so the `except JobFailed` branch never catches it.\n- **`generate`.** Only the claim-time `resolve_video` call is wrapped, in `try/except sqlite3.OperationalError`.\n  - If the lowercased error text contains `locked`, `busy` or `unable to open`, it raises `WhitelistBusy(str(exc)) from exc`.\n  - Any other error is re-raised unchanged with a bare `raise`, so it still reaches the catch-all and ends the job `failed` with `OperationalError: <text>`.\n  - The refusal check and every later step stay outside the `try`, so `subtitles.db` errors are never treated as transient.\n  - The plan's separate `is_transient_db_error` predicate is written inline instead, because it has one caller.\n  - The docstring now names the `WhitelistBusy` case.\n- **`run_job`.**\n  - The return type changes from `-> None` to `-> bool`.\n  - A new `except WhitelistBusy as exc` branch comes right after `JobStopped`, ahead of the catch-all, so it never reaches `logging.exception` or the CUDA-OOM unload.\n  - The branch calls the existing `requeue_translate_job(conn, *claim)`, which gives back the attempt and keeps `queued_at`. It logs one `logging.warning(\"[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s\", ...)` with the error text, and returns True. It writes no `error` and no `finished_at`.\n  - Every other path ends in a final `return False`.\n  - The docstring now covers the transient requeue and the return value.\n- **Not touched in this phase:** `serve` does not read the result yet, and the back-off constant is not added. Both belong to Phase 2.\n- **Unchanged:** `resolve_video` and `command_enqueue`.\n\n### `tests/active/test_translate_worker.py`\n\nNo change. The checkpoint calls `rig.worker.run_job` directly, so `Rig.run` did not need to return the value.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py": "<items>\n<item id=\"D10\">\n<disposition>justified</disposition>\n<what>I narrowed the docstring sentence to what the test asserts. Line 4 no longer says the recovery test \"guards recovery against a back-off that breaks it\". It now says: \"Phase 1 already delivered this, so it is green before phase 2 (C2 exempted from the red by the operator). It drives `run_job` and `claim_translate_job` directly and never runs `serve`, so it checks recovery at those seams only, not past a back-off in `serve`'s loop.\" The docstring no longer claims a guard the test does not give. It names the seams the test enters (:89, :95, :98) and states the gap the audit found: a `serve` that keeps backing off v-1 once whitelist.db is usable again. I made no other change.</what>\n</item>\n</items>\n\n<findings_addressed>\nNeither auditor raised a CRITICAL. Claim Recommendation 2 (D10): taken. I narrowed the docstring at :4 to say the recovery test enters only `run_job` and `claim_translate_job` and does not cover a back-off in `serve`'s loop. Claim Observation 1 and shape Recommendation 2 (the C2 reason saying \"both the run_job and serve seams\"): the same edit fixes the docstring's account of what the test guards. Claim Recommendations 1 and 3 and shape Recommendation 1: not taken this round, because they do not block and the ledger does not name them.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73: the second whitelist lookup comes at least BACKOFF_SECONDS (1.0, set on the module as TRANSIENT_BACKOFF_SECONDS) after the first. It runs for an injected lock and for a deleted file. The control at :72 bounds the wait at 10 s. :78 asserts every lookup is (\"v-1\", HOST), and :80 asserts the row after stop is (\"queued\", 0, QUEUED_AT).</assertion>\n<expected>A gap of 1.0 s or more between the first and second lookup. Every lookup is for v-1 on HOST. The row ends queued with attempts 0 and queued_at 1000.</expected>\n<wrong_implementation>Today's `serve` ignores run_job's True and reclaims at once. When I ran it with the constant supplied, the gap was about 0.2 ms, and :73 failed. A requeue that lost v-1's place would show (\"d-1\", DENIED_HOST) at :78. A back-off that spent the attempt or rewrote queued_at would read attempts 1 or a different queued_at at :80.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:97 and :100. At :97, claim_translate_job returns v-1 on HOST with started_at STARTED_AT + 1 and attempts 1. At :100, the final row is (\"ready\", \"whisper\", QUEUED_AT, STARTED_AT + 1, 1, None). Both run for \"lock released\" and for \"file restored\".</assertion>\n<expected>At :97, (\"v-1\", HOST, 2001, 1). At :100, (\"ready\", \"whisper\", 1000, 2001, 1, None).</expected>\n<wrong_implementation>A requeue that leaves the row unclaimable makes claim_translate_job return None, which fails :97. One that spent the attempt reads attempts 2. A reclaim that fails, is requeued again or rewrites queued_at reads something other than ready/1000 at :100. This is carried at the run_job seam and not through serve. The operator exempted C2 from the red on an earlier round.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The only negative-leaning check is :78, that d-1 is never looked up. Its positive controls are :72 (at least two lookups happened) and the set equality itself: an empty set fails against {(\"v-1\", HOST)}.\n2. No. Nothing is compared to itself. :73 compares two recorded timestamps against a constant the test sets. Deleting the back-off wait that phase 2 adds to `serve` turns it red; today's code shows that, with a measured 0.2 ms gap.\n3. Partly, and I left it as is. The back-off runs at one patched value (shape Recommendation 1). The 10x ceiling at :72 rules out a serve that ignores the constant and waits 10 s or more. A second patched value would close the rest. It is a recommendation, it does not block, and the ledger does not name it, so I did not rewrite it this round.\n4. No. `resolve_video` is wrapped by a recorder. In the missing-file case it calls straight through to the real function. In the lock case the recorder raises the real sqlite3 error that the lock produces. StubRunner stands in for the external transcription runner, a layer outside this project. The store and `serve` are real.\n5. Yes, it collects. My only edit this round is docstring text on one line, so imports, names and line numbers are unchanged. The test count is still 4: 2 parametrized cases in each of the 2 tests.\n6. Yes. The real error text for the missing file, the 0.1\u20130.2 ms reclaim gap, the requeued row values and the recovery row, cues and URLs all come from the earlier probe runs recorded in my previous reply.\n7. Yes. The edit touched prose only. The C1 cases still fail at :73 on the timing, because `raising=False` at :59 lets setup reach serve. The C2 cases still pass under the operator's exemption.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase2.py:73 \u2014 `lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS`: serve's second whitelist lookup (one per claim, at the start of `generate`) comes at least the back-off (1.0 s, set on the loaded module) after the first. Parametrized over an injected `database is locked` and a really deleted whitelist.db. The control at :72 shows two lookups happened within ten back-offs.</assertion>\n<expected>Correct implementation: a gap of at least 1.0 s, because serve sleeps TRANSIENT_BACKOFF_SECONDS in POLL_SECONDS slices before the next claim. Current code, as run: gaps of 0.000156 s (injected lock) and 0.000181 s (missing file).</expected>\n<wrong_implementation>A serve that ignores run_job's True and reclaims at once, which is the code as it stands. The run read gaps of about 0.15\u20130.18 ms, so `assert (\u2026762493296 - \u2026762337015) >= 1.0` fails at :73. A back-off that waits only one POLL_SECONDS slice (0.05 s) also reads below 1.0. A back-off that binds the 30 s default instead of reading the module global fails the :72 control at 10 s.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase2.py:78 \u2014 `{call[1:] for call in lookups.calls} == {(\"v-1\", HOST)}`: every lookup was v-1, never d-1, which is queued behind it at QUEUED_AT + 1.</assertion>\n<expected>{(\"v-1\", \"peer.example\")}. The run's recorded calls were all ('v-1', 'peer.example').</expected>\n<wrong_implementation>A back-off that requeues by re-enqueueing (a fresh queued_at) or that skips the failed job and moves on. The next claim would then take d-1, and the set would include (\"d-1\", \"denied.example\").</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase2.py:80 \u2014 after stop and join (the :77 control shows the thread ended), the row's (state, attempts, queued_at) == (\"queued\", 0, QUEUED_AT).</assertion>\n<expected>(\"queued\", 0, 1000)</expected>\n<wrong_implementation>A back-off path that spends the attempt or rewrites queued_at (for example, it marks the row running or failed, or requeues with now_ms()). It would read attempts 1, state failed or running, or a queued_at other than 1000.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_45_translate_worker_whitelist_locked_at_phase2.py:97/:100/:101/:102 \u2014 after a run_job requeue (the :91 control reads queued/0/1000), with the lock released or the file rewritten, claim_translate_job returns v-1 with started_at STARTED_AT+1 and attempts 1. The reclaim then ends (state, source, queued_at, started_at, attempts, error) == (\"ready\", \"whisper\", 1000, 2001, 1, None) with cues CHUNK_1 + CHUNK_3, and the instance and media URLs are each requested once.</assertion>\n<expected>The values as written. The run shows both cases passing against the current code; the operator exempted C2 from the red (see exemptions).</expected>\n<wrong_implementation>A requeue that leaves the row unclaimable, or a reclaim that fails or rewrites queued_at. The first gives claim_translate_job None; the second gives a state other than ready or a queued_at other than 1000. Phase 1 already rules both out, so this is a green regression guard at this checkpoint.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes for C1. \"Next claim\" is measured by the lookup at the start of each claim (:73). \"Same head job\" is shown by the all-v-1 set with d-1 queued behind (:78) and the row staying queued/0/1000 (:80). C2 is carried at :97\u2013:102. It is green, which the operator accepted (exemption). The docstring now says so.\n2. Absence only: no. The \"never d-1\" check at :78 is armed by the :72 control (at least two lookups recorded), and the set must equal {v-1}, not merely exclude d-1.\n3. Echoed literal: no. :73 measures the time between two real calls from serve. The production code that turns it green is phase 2's back-off loop in serve; until it exists the assertion is red. For C2, deleting `requeue_translate_job(conn, *claim)` from run_job's WhitelistBusy branch (translate-worker.py:476) turns :91 and :97 red.\n4. One value: no. C1 is read under two causes (injected lock and real missing file). The 1.0 s back-off is set apart from both the 0.05 s slice and the 30 s default, and the 10 s control bound catches the default.\n5. The double: StubRunner stands in for WhisperRunner, a GPU layer this test cuts off. resolve_video is wrapped by a recorder. In the injected case it raises in place of the real call (R6 allows this because the real lock takes 30 s). In the missing-file case the recorder passes through to the real resolve_video and the real `unable to open database file`. So no owned module is replaced without the real path also being exercised.\n6. It collects: yes. The run printed \"collected 4 items\" (2 cases \u00d7 2 tests), matching what I wrote. The given --collect-only summary said \"no tests\", but the real run collected and ran all 4. All imports, including CHUNK_1 and CHUNK_3 from test_translate_worker, bound, and the C2 cases ran to completion.\n7. Observed, not predicted: yes. The gaps and the all-v-1 lookups come from this run, and the C2 values were seen passing. The line 25 comment (\"about 0.1 ms\") matches the 0.14\u20130.18 ms observed.\nRewrite made: the first run was red for the wrong reason. `monkeypatch.setattr(rig.worker, \"TRANSIENT_BACKOFF_SECONDS\", BACKOFF_SECONDS)` at :58 raised `AttributeError: \u2026 has no attribute 'TRANSIENT_BACKOFF_SECONDS'`, a setup failure that never reached serve. It now passes `raising=False` with a WHY comment, so the test reaches serve and fails on the timing.\n8. Red, not green: yes. ValidateTests reported exit status 1, \"2 failed, 2 passed\". The two serve back-off cases fail. The two recovery cases pass because phase 1 already delivered C2. I asked the operator, who chose \"Exempt C2 here\".\n9. Red for the right reason: yes. The :72 control passed (two lookups recorded). The failure is the C1 assertion at tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73, \"AssertionError \u2026 assert (1656236.762493296 - 1656236.762337015) >= 1.0\" (injected lock) and \"assert (1656236.792722462 - 1656236.792541957) >= 1.0\" (missing file). serve reclaimed v-1 about 0.16 ms after each requeue because there is no back-off yet. That is the phase not being built, not a test defect.\n10. Observed expected output: yes. The C1 rows' current-code readings (gaps of about 0.16\u20130.18 ms, every lookup ('v-1', 'peer.example')) are copied from the run. The \u2265 1.0 s expectation is the phase's target. The C2 row's values are the ones the run showed passing.\n</answers>\n\n<exemptions>\n<exemption clause=\"C2\">\n<answer>Exempt C2 here</answer>\n<why>Conceded: C2 contributes no red at this checkpoint. Phase 1's requeue (run_job's WhitelistBusy branch calling requeue_translate_job) already makes the requeued job claimable and lets it run to ready with queued_at kept. The recovery test at :84\u2013:102 therefore passes against the current code, at both the run_job and serve seams. It stays as a green regression guard against a phase-2 back-off that breaks recovery. C1 (:73) carries this checkpoint's red alone.</why>\n</exemption>\n</exemptions>",
    "step_7_implement:2": "<changes>\n### engine/server/db/jobs/translate-worker.py\n- Added the module constant `TRANSIENT_BACKOFF_SECONDS = 30.0`, defined next to `POLL_SECONDS`. Its comment gives the reason for it: the requeued job is still at the head of the queue, so without a wait `serve` would claim it again straight away and spin.\n- `serve` now uses the `bool` that `run_job` already returned. That value is True only for the whitelist.db requeue added in phase 1. When it is True, `serve` waits `TRANSIENT_BACKOFF_SECONDS` before its next claim (C1). The wait sleeps with `time.sleep` in pieces no longer than `POLL_SECONDS`, so a stop still ends `serve` within one poll interval. It uses `time.sleep` rather than `stop.wait` for the same SIGTERM-deadlock reason already noted in the idle branch. Each sleep is clamped at 0 so a near-zero remainder can't raise. The docstring of `serve` now mentions the back-off.\n- C2 needed no change. After the back-off, the job claimed again goes through the same `run_job` path as any other job, which phase 1 already delivered.\n\n### tests/active/test_translate_worker.py\nNot changed. The checkpoint only imports its rig and constants, and they already covered what it needed.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py": "<assertions>\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:82 \u2014 `progress[\"at\"]` sampled 0.15 s apart inside the second back-off has moved forward (`second > first`). Fails against a wait that never touches progress or sleeps the whole back-off in one call. Today's red is here, in both parametrizations \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:83 \u2014 the second sample is under 0.3 s old. Fails against a wait that refreshes once at the start or rarely \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:84 \u2014 control: `len(lookups.calls) == 2` after the second sample, so both samples were taken in the second back-off and not during a fresh claim, which sets progress itself \u2014 C1\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:74 \u2014 control: serve reached its second lookup within ten back-offs \u2014 C1/C2 setup\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:75 \u2014 control: the second requeue landed (row queued again), so serve is in the back-off before sampling \u2014 C1/C2 setup\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:88 \u2014 control: more than 0.5 s of the back-off is left when stop is set, so a wait ignoring stop until its deadline would break the bound at :95 \u2014 C2\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:95 \u2014 after `stop.set()` from the test thread and `join(5)`, the thread is dead and less than 0.5 s passed since the stop. Fails against a wait that ignores stop until its deadline \u2014 C2\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:96 \u2014 `len(lookups.calls)` is still 2 after the join. Fails against a loop that breaks out of the wait and then claims once more before exiting \u2014 C2\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:98 \u2014 row `(state, attempts) == (\"queued\", 0)`: the job is left requeued and unspent, with no claim held over the stop \u2014 C2\n</assertions>\n\n<probes>\nWrote tests/tmp/probe_45_phase3_backoff.py and ran `ValidateTests [\"tests/tmp/probe_45_phase3_backoff.py\", \"-s\"]` against today's serve (POLL_SECONDS 0.05, TRANSIENT_BACKOFF_SECONDS 1.0, both the injected-lock and missing-file lookup failures). From tests/last_test_output.txt: lookup gap 1.0003 s. Second lookup seen 0.005 s after it happened, row queued again 0.0054 s after it. `progress[\"at\"]` first and second samples identical, both equal to the value set just before the claim (-0.00014 s relative to lookup 2); sample age 0.1556 s; calls 2. Back-off left at stop 0.8445 s. Join elapsed 0.045 s, thread dead, calls 2, row queued, attempts 0. Identical figures for both parametrizations.\nRan `ValidateTests [\"tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py\"]` against today's code: 2 failed, both at :82 (`assert 1656641.351556682 > 1656641.351556682`). Every control before it (:74, :75) passed, so the red is C1's assertion and not the setup.\nI could not remove the probe file: no tool here deletes files. tests/tmp/probe_45_phase3_backoff.py is still on disk and should be deleted; the checkpoint now covers what it showed.\n</probes>\n\n<unassertable>\nnone. C2 is asserted in full, but it is green before phase 3: the probe showed phase 2's sliced wait already returns 0.045 s after a stop with no further claim. Its assertions guard the new progress-refreshing wait against ignoring stop or claiming once more, and the phase's red comes from C1 (:82). The docstring says so. If the workflow needs each clause red before the phase, C2 needs the same operator exemption phase 2's C2 got.\n</unassertable>",
    "self_check:tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:76 \u2014 `max(ages) < FRESH_SECONDS` (0.1 s, two slices): `progress[\"at\"]` is read every 0.01 s for 0.25 s (five slices) inside the second back-off, and no read is more than two slices old. Line 77's control (`len(lookups.calls) == 2`) shows no read came from a fresh claim.</assertion>\n<expected>Under the right implementation every age is under 0.1 s. This is a prediction: I could not observe it, because the phase is not built. The nearest thing I could observe was a probe thread that sets `progress[\"at\"]` and then sleeps 0.05 s, read the same way. Over 20 runs it peaked at 0.0504 s with 6 distinct values per window. Today the run reads the ages growing steadily from 0.0084 s to 0.2498 s.</expected>\n<wrong_implementation>Today's sliced wait never touches `progress`, so the oldest read is 0.2498 s and the run fails. A wait that sets `progress[\"at\"]` once, when the back-off starts, also reaches about 0.25 s. A wait that refreshes every other slice or less often goes past 0.1 s.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:88 \u2014 the thread is no longer alive and `elapsed < STOP_WITHIN_SECONDS` (0.5 s) after a stop set with more than 0.5 s of the back-off left. Line 81's control checks the time left.</assertion>\n<expected>Observed in a probe against today's code (phase 2's sliced wait): the thread returned 0.041 s after the stop, with 1.24 s of the back-off left. The new wait should match that.</expected>\n<wrong_implementation>A wait that ignores the stop, such as one `time.sleep(TRANSIENT_BACKOFF_SECONDS)` or a refresh loop that never checks `stop`, keeps running for the remaining ~1.2 s. `elapsed` then reads about 1.2 s and fails the 0.5 s bound.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:89 \u2014 `len(lookups.calls) == 2` after the stop. The pass-through spy counts lookups, and lookup is the first thing a claim reaches. Line 72's control shows the spy records lookups.</assertion>\n<expected>2. Observed in the probe against today's code: still 2 lookups after the stop.</expected>\n<wrong_implementation>A new wait that leaves the back-off loop and goes round `serve`'s outer loop once more without re-checking `stop` claims the job again. That makes a third lookup, so the count reads 3.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:91 \u2014 `(row[\"state\"], row[\"attempts\"]) == (\"queued\", 0)` after `serve` returns.</assertion>\n<expected>(\"queued\", 0). Observed in the probe against today's code: state queued, attempts 0.</expected>\n<wrong_implementation>A claim after the stop leaves the row `running` with attempts 1, or requeued with an attempt spent, so the tuple no longer equals (\"queued\", 0).</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes in the version I was handed. C1 says progress advances \"at least once per slice\", but that version checked `second > first` 0.15 s apart and a 0.3 s age limit. A wait refreshing about every 0.25 s would have passed both. Rewritten: `progress[\"at\"]` is now read every 0.01 s for 0.25 s, and line 76 requires every read to be under two slices (0.1 s) old. C2 is carried by lines 88, 89 and 91. The docstring was rewritten to match.\n2. Absence only: no. \"No claim after the stop\" (line 89) is armed by line 72, which waits for the spy to record two lookups. \"Thread not alive\" is armed by line 81, which checks more than 0.5 s of the back-off was left. Line 77 confirms the C1 reads all fell inside the back-off.\n3. Echoed literal: no. The test only reads `progress` and times against `time.monotonic()`; it does not do production's work itself. Line 76 needs the new per-slice refresh in the wait at translate-worker.py:531-532. Deleting that refresh turns line 76 red, as today's run shows. Deleting the `stop.is_set()` check at line 531 turns line 88 red.\n4. One value: yes in the version I was handed. The age was read once, at one point in time. Rewritten to 25 reads across five slices, judged by their maximum.\n5. The double: yes in the version I was handed. The \"injected lock\" case replaced `resolve_video`, a function this project owns, with one that raises. A real lock is not quick to get: `resolve_video` sets `busy_timeout = 30000`, so a held lock blocks for 30 s rather than raising. I dropped that case. The test now deletes whitelist.db, so the failure is the real `unable to open database file` going through the real `generate` and `WhitelistBusy` path. What remains on `resolve_video` is a spy that only notes a timestamp and then calls the real function.\n6. It collects: yes. The imports are `HOST`, `MAX_DURATION`, `QUEUED_AT`, `StubRunner`, `clip` and `rig` from tests/active/test_translate_worker.py (`clip` is a fixture `rig` needs), and `enqueue_translate_job` from data.subtitles. `rig.worker`, `.whitelist`, `.conn`, `.clip` and `.row()` all exist on `Rig` (lines 432-497). `serve(conn, args, runner, stop, progress)` matches translate-worker.py:511. `connect_subtitles_db` opens with `check_same_thread=False`, so the thread can use it. The run collected 1 test, which is what the file defines now that the parametrize is gone.\n7. Observed, not predicted: today's side was observed. Probe `tests/tmp/probe_45_phase3_backoff.py`, run with `-s` against today's code, printed: \"seen_after_lookup 0.008 max_age 0.2496 distinct 1 left 1.2405 elapsed 0.0411 alive False calls 2 row queued 0\". A thread refreshing once per 0.05 s slice printed \"max_age 0.0504 distinct min 6 distinct max 6\" over 20 runs, and the 0.1 s limit is set from that. Not observed: the real phase-3 wait passing line 76. It cannot be seen until the phase is built; the implementation run will confirm it. The probe file is still there and should be deleted; I have no delete tool.\n8. Red, not green: yes. `ValidateTests` on the checkpoint: \"1 failed\", \"[exit status 1]\".\n9. Red for the right reason: yes. It failed at line 76, the C1 assertion: \"assert 0.2497904570773244 < 0.1\", with ages [0.0084, 0.0185, 0.0286, 0.0386, 0.0487, 0.0587, ...] rising steadily, so today's back-off never refreshes `progress`. The controls at lines 72 and 73 passed first, so serve did reach the second requeue and its back-off. The C2 assertions at lines 88-91 are not reached in this run. Their expected values come from the probe run above (0.041 s, 2 lookups, queued 0), and they are meant to stay green as a guard.\n10. Observed expected output: the C1 row's \"today\" value, 0.2498 s, is from this run. The C2 rows' values are from the probe run. The C1 \"right implementation\" value is not observed; the row says so and gives the 0.0504 s once-per-slice measurement it rests on. The run did not contradict any row.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `engine/server/db/jobs/translate-worker.py`\nIn `serve`, the back-off loop after a whitelist.db requeue now sets `progress[\"at\"] = time.monotonic()` at the start of each `POLL_SECONDS` slice (C1). Without it, the heartbeat thread would treat a long `TRANSIENT_BACKOFF_SECONDS` wait as a stall and stop beating. The comment above the loop now gives this reason too. The loop's check of `stop.is_set()` before each slice is unchanged, so a stop still ends `serve` within one slice and nothing is claimed again (C2).\n\n### `tests/active/test_translate_worker.py`\nNot changed. The checkpoint imports only its existing rig and helpers (`HOST`, `MAX_DURATION`, `QUEUED_AT`, `StubRunner`, `clip`, `rig`). Nothing in this file covers the back-off, so this phase did not need to edit it.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nnone. I made no edits. I checked engine/server/db/jobs/translate-worker.py and the three phases are already in their smallest form. WhitelistBusy is one exception class next to its siblings. The transient check is written inline in generate's only resolve_video call, because it has a single caller. run_job has one new branch and returns a bool. serve has one back-off loop that refreshes progress in each slice. TRANSIENT_BACKOFF_SECONDS is the only new constant. The docstrings for generate, run_job and serve already describe the new behaviour.\n</refactors>\n\n<left_out>\n1. I did not merge the JobStopped and WhitelistBusy branches in run_job, although both call requeue_translate_job. They log at different levels and with different text, and only the WhitelistBusy branch returns True. A shared helper would add code to save one line. 2. I did not pull serve's back-off loop out into a helper. It has one caller, and a helper would add an indirection without making the code shorter. 3. I did not add the requeue to the module docstring's run_job sentence. The run_job docstring already states it, and that docstring is where readers look. 4. Probe and phase-checkpoint files from phases 1\u20133 are still in tests/tmp/ (probe_45_phase1_scenarios.py, probe_45_phase2_serve.py, probe_45_phase3_backoff.py, probe_45_whitelist_locked_at_claim.py, test_45_translate_worker_whitelist_locked_at_phase{1,2,3}.py). They are outside the files I was given for this step, and the phase tests are gated checkpoints, so I did not delete or edit them. Whoever owns the build's cleanup should decide what happens to them.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nI matched the shipped translate-worker.py against the inlined source with a Grep on the phase symbols, and the code is the same. run_job's only production caller is serve, so the bool return has no other caller to update. The pass found nothing to cut without changing behaviour or adding indirection.\n</observation>",
    "step_10_plan": "<harvest_file>\ndocs/project/plans/harvest-45-translate-worker-whitelist-locked-at-plan.md\n</harvest_file>\n\n<plan>\nHarvest plan for issue 45, translate-worker whitelist.db locked at claim (scope: the three `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase{1,2,3}.py` files; bootstrap gate clear; record snapshot taken at `tests/last_test_validation.json.preharvest`).\n\nCounts per verdict: DURABLE 4, REPLACES 0, COMBINE 0, REDUNDANT 2, SPENT 0 (6 test functions).\n\nDURABLE, all to `tests/active/test_translate_worker.py`:\n- `test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true` (phase 1; parametrized missing file / held EXCLUSIVE lock). No active test covers the WhitelistBusy requeue.\n- `test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false` (phase 1; parametrized videos without video_uuid / zero-byte file). It bounds the transient predicate from the other side.\n- `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` (phase 2; parametrized injected lock / missing file). No active test drives `serve` in-process or asserts `TRANSIENT_BACKOFF_SECONDS`.\n- `test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim` (phase 3). Covers heartbeat liveness and stop during the back-off; uncovered anywhere else.\n\nREDUNDANT (stay out):\n- `test_control_an_intact_whitelist_reaches_both_hosts` (phase 1). The active transcribed-job test already asserts ready plus `INSTANCE_THEN_JSON` / `[MEDIA_URL]` on the same rig.\n- `test_a_job_requeued_on_whitelist_db_claimed_again_once_it_is_usable_runs_to_ready_with_its_queued_at_kept` (phase 2). Every link is already asserted: the requeued row tuple by the phase 1 DURABLE test, the claim of a queued row by `test_subtitles.py::test_claim_hands_out_queued_jobs_oldest_first_\u2026`, and a claimed v-1 running to ready by the transcribed-job test. It was green before its own phase.\n\nActive tests retired: none.\n\n`test_groups` changes: none. The `test_translate_worker.py` entry already claims `engine/server/db/jobs/translate-worker.py` and `engine/server/data/subtitles.py`.\n\nNew subject files: none. The subject exists and is not split.\n\nHow Step 5 lands them:\n- `Rig.run` gains `return`, so it hands back `run_job`'s bool. This reuses the rig rather than carrying phase 1's `_run_job` copy.\n- Phase 2 and phase 3 each have a `_recording` helper with the same name and different signatures. They merge into one helper that records `(time, video_id, host)` with optional `locked_calls`, and there is a single `_until`.\n- The back-off constants that differ (1.0 s vs 1.5 s) get distinct names.\n- Docstrings are rewritten to state the rule instead of \"Issue 45, phase N\", and the module docstring gains the transient-whitelist and back-off rules.\n- The held-EXCLUSIVE-lock case costs about 30 s (busy timeout).\n\nNothing moved; this turn stopped at Step 4.\n</plan>",
    "step_9_triage": "<docs>\n<doc path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" update=\"yes\">\nSeveral sentences are now false or incomplete, checked against the shipped `translate-worker.py`. That code has `WhitelistBusy`, the inline `locked`/`busy`/`unable to open` check around the claim-time `resolve_video` only, `run_job -> bool`, `TRANSIENT_BACKOFF_SECONDS = 30.0`, and the `serve` back-off loop that sleeps in `POLL_SECONDS` slices and refreshes `progress[\"at\"]` each slice.\n- Known Gaps :154: delete the locked `whitelist.db` bullet, which is now false. Keep the faster-whisper/VRAM bullet.\n- Error Texts :137: drop \"and a locked `whitelist.db`\". A lock or a missing file no longer produces a `failed` row. A non-transient whitelist error such as `no such column` or `no such table` still produces `OperationalError: <text>`.\n- Job Pipeline intro :83 says \"each bound ending the job `failed`\". Qualify it for step 1's transient case.\n- Job Pipeline step 1 :85: add the transient case:\n  - what counts: an `OperationalError` whose text contains `locked`, `busy` or `unable to open`, for example during the updater merge (past the 30 s busy timeout) or a restore;\n  - the job goes back to `queued` with `attempts` lowered by 1 and `queued_at` kept, with no `error` or `finished_at`;\n  - no remote request is made;\n  - every other database error still fails the job as `<ExceptionType>: <text>`.\n- Serve Loop :79: after a `whitelist.db` requeue, `serve` waits `TRANSIENT_BACKOFF_SECONDS` (30 s) before its next claim. The wait is slept in 2 s slices with progress recorded each slice. The same head job is reclaimed every cycle until the file is usable, and then it runs normally.\n- Stop, Crash and Recovery :141: the SIGTERM bullet only describes the chunk loop. Add two points:\n  - a stop during the back-off ends `serve` within one 2 s slice, with no further claim;\n  - a stop that arrives during sqlite's 30 s busy wait inside the lookup takes up to about 30 s to act.\n- Heartbeat :150: \"records progress on every serve pass and every chunk-loop wake (at most 2 s apart)\". Add that the back-off also records it every slice, so the heartbeat keeps beating during an outage.\n- Job Lifecycle :33/:39: no sentence is false. \"A failed key is never queued again\" still holds. Optionally note in the `queued` row that a requeued job (stop or `whitelist.db` unavailable) is `queued` again with its `attempts` restored.\n- Logs: add the warning `whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: <error>` next to `stopped mid-job, requeued \u2026`.\n</doc>\n<doc path=\"DEPLOYMENT.md\" update=\"yes\">\n- Triage row :353 is now false for the job half. It says \"A job ends `failed` with `OperationalError: database is locked`\" and \"The job is not requeued and nothing backs off: the key stays `failed`\".\n  - Symptom: the job stays `queued`, or flips between `queued` and `running`, and the journal repeats `[translate-worker] whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: database is locked`, or `unable to open database file`.\n  - Cause: the updater merge holds `whitelist.db` past the 30 s busy timeout, or a restore has removed it. The worker requeues the job unspent and retries after a 30 s back-off.\n  - Action: nothing for the job, which runs once the merge or restore ends.\n  - A repeating `unable to open` with no restore in progress means the `--whitelist-db` path or its permissions are wrong. This matters because such a misconfiguration now stalls the queue instead of failing jobs.\n  - Keep the `enqueue` half as it is (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends), because `command_enqueue` is unchanged.\n- Triage row :348 \"Jobs stay `queued`\": add a locked or missing `whitelist.db` as a cause, with the warning line as the tell, pointing to the :353 row.\n- :264 TimeoutStopSec note: still true, because 120 s covers a 30 s busy wait plus a 2 s slice. Optionally add that a stop also ends the back-off wait within one slice.\n</doc>\n<doc path=\"CONTEXT.md\" update=\"no\">\nNo sentence in the \"Translate job\" entry (:19) is false. Jobs still move `queued` \u2192 `running` and end in exactly one of `ready`, `already_english` or `failed`. The entry already leaves out requeue paths that are not crash recovery, such as the stop requeue. The transient requeue is the same kind of mechanism and belongs in `TRANSLATE_WORKER.md`, which the entry points to.\n</doc>\n<doc path=\"tests/active/test_translate_worker.py\" update=\"no\">\nThe build diff leaves this file unchanged. The new tests live in `tests/tmp/test_45_\u2026_phase{1,2,3}.py`, so the module docstring does not yet describe anything the file fails to test. The harvest plan (`docs/project/plans/harvest-45-translate-worker-whitelist-locked-at-plan.md`, Step 5 notes) moves the four DURABLE tests into this file. That plan states that \"The module docstring of `test_translate_worker.py` gains the transient-whitelist and `serve` back-off rules\", so the harvest owns this update. It must cover the requeue on a missing file and on a held EXCLUSIVE lock, the `no such column`/`no such table` controls, the back-off gap, progress during the back-off, and a stop during it. The recovery-to-ready test is REDUNDANT and is not harvested, so the docstring should not claim it.\n</doc>\n<doc path=\"engine/server/data/subtitles.py\" update=\"yes\">\n`requeue_translate_job` docstring (:162): \"Put a running job back without spending its claim (a stop mid-job); \u2026\". The function now has a second caller, `run_job`'s `WhitelistBusy` branch, so the parenthetical is incomplete. Change it to name both cases, for example \"(a stop mid-job, or whitelist.db unavailable at claim)\". The checklist did not name this file; it is a gap the impact inventory flagged as uncertain.\n</doc>\n<doc path=\"docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md\" update=\"yes\">\n- Delivered, so per `triage-labels.md`: set `Status: bug, complete`.\n- Tick the acceptance boxes (:93-98) that the delivered code and tests meet. The docs box (:98) is met once the TRANSLATE_WORKER.md and DEPLOYMENT.md updates land.\n- Move the file to `docs/project/issues/archive/`.\n</doc>\n<doc path=\"docs/project/issues/issue-tracker.md\" update=\"yes\">\nRow 45 (:8) still reads `ready-for-agent` and links `45-translate-worker-whitelist-locked-at-claim.md`. Set the state to `complete` and point the link at the `archive/` path, following the earlier archived rows.\n</doc>\n<doc path=\"docs/project/roadmap.md\" update=\"yes\">\n:60 says \"Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`.\" That is now delivered. Move it into the line's Delivered list, for example \"requeue with back-off when `whitelist.db` is locked or missing at claim (issue `45`; see `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`)\". Keep the PARTIAL status, because plan 50 and the player remain.\n</doc>\n<doc path=\"engine/server/README.md\" update=\"no\">\nThe Translate worker paragraph (:25) defers to `TRANSLATE_WORKER.md` for the lifecycle. The heartbeat note (:31), \"stops beating when the serve loop stalls\", stays true because the back-off refreshes progress every slice.\n</doc>\n<doc path=\"docs/project/plans/50-translate-generation-in-page.md\" update=\"no\">\nThis is a future plan, not a description of current behaviour. Its gate (heartbeat freshness) and its polling of `queued`/`running` still hold: the heartbeat keeps beating during the back-off, and a job sitting `queued` through an outage is one of the states it already polls. Nothing it claims is false.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:engine/server/db/jobs/docs/TRANSLATE_WORKER.md": "<changes>\nTRANSLATE_WORKER.md now says that when `whitelist.db` is locked, busy or can't be opened at claim time, the job goes back to the queue and the worker waits 30 s before claiming again. It no longer says such a job fails for good.\n\nI checked every sentence against the shipped `translate-worker.py`: the inline `locked`/`busy`/`unable to open` check around the claim-time `resolve_video` call, the `WhitelistBusy` branch in `run_job`, `TRANSIENT_BACKOFF_SECONDS = 30.0`, and the back-off loop in `serve`.\n\n- **Serve Loop:** a new paragraph. After a `whitelist.db` requeue, `serve` waits 30 s (`TRANSIENT_BACKOFF_SECONDS`) in 2 s slices before it claims again. The same head job is claimed again every cycle, with later jobs waiting behind it, until the file can be used; then it runs like any other job. A cycle takes about 60 s while a lock is held and about 30 s when the file is missing.\n- **Job Pipeline:** the intro now says step 1 requeues the job instead of failing it when `whitelist.db` is unavailable. Step 1 itself covers:\n  - which errors count: an `OperationalError` whose text contains `locked`, `busy` or `unable to open`, such as during the updater merge or a restore;\n  - the job goes back to `queued` with `attempts` lowered by 1 and `queued_at` kept, with no `error` or `finished_at` written and no remote request made;\n  - every other database error still fails the job as `<ExceptionType>: <text>`.\n- **Error Texts:** \"a locked `whitelist.db`\" is gone from the `<ExceptionType>: <text>` line. In its place: a `whitelist.db` error other than a lock or a missing file, for example `no such table`.\n- **Stop, Crash and Recovery:** the SIGTERM bullet now says a stop during the back-off ends `serve` within one 2 s slice and nothing more is claimed. A stop that arrives during sqlite's 30 s busy wait only takes effect once that wait ends.\n- **Heartbeat:** progress is also recorded on every back-off slice, so the heartbeat keeps beating while `whitelist.db` is unavailable.\n- **Known Gaps:** removed the locked-`whitelist.db` bullet and kept the faster-whisper/VRAM one.\n- **Logs:** added the warning line `whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: <error>`.\n\nI left the Job Lifecycle table alone: none of its sentences became false, and the requeue is described once, in Job Pipeline step 1.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:DEPLOYMENT.md": "<changes>\nDEPLOYMENT.md: the translate-worker Triage rows now say that a locked or missing `whitelist.db` puts the job back on the queue with a back-off. It no longer says the job fails.\n\nI checked each point against the shipped `translate-worker.py`: the inline `locked`/`busy`/`unable to open` check in `generate`, the `WhitelistBusy` branch and its warning line in `run_job`, and the `TRANSIENT_BACKOFF_SECONDS = 30.0` loop in `serve`.\n\n- **Triage row for a locked `whitelist.db`, split into two rows:**\n  - **Worker row.**\n    - Symptom: the job stays `queued` or flips between `queued` and `running`, and the journal repeats `[translate-worker] whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: database is locked` (or `unable to open database file`).\n    - Cause: the updater's merge holds the file past the 30 s busy timeout, or a restore has removed it. The job is put back without counting a claim and claimed again after a 30 s back-off; the detail is left to a pointer to `TRANSLATE_WORKER.md`. A repeating `unable to open` with no restore running means the `--whitelist-db` path or its permissions are wrong, and later jobs wait behind this one.\n    - Action: nothing for the job. For a wrong path or permissions, fix them and restart the worker.\n  - **`enqueue` row:** keeps `error: whitelist.db: database is locked` and exit 1, with \"re-run `enqueue` after the updater run ends\". `command_enqueue` is unchanged.\n- **Triage row \"Jobs stay `queued`\":** adds a locked or missing `whitelist.db` as a cause, with the repeating `whitelist.db unavailable, requeued` line as the sign, and points to the row above.\n- **`TimeoutStopSec=120` bullet:** SIGTERM now also lets a `whitelist.db` lookup finish its busy wait (up to 30 s). That wait cannot be interrupted, and 120 s still covers it.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/data/subtitles.py": "<changes>\nThe `requeue_translate_job` docstring now names both of its callers' cases: a stop mid-job, and `whitelist.db` being unavailable at claim.\n\n- `engine/server/data/subtitles.py:162`: the parenthetical \"(a stop mid-job)\" now reads \"(a stop mid-job, or whitelist.db unavailable at claim)\". The rest of the docstring and the function are unchanged.\n- I checked this against `translate-worker.py:473-480`. `run_job` calls `requeue_translate_job(conn, *claim)` in both its `JobStopped` and `WhitelistBusy` branches.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md": "<changes>\nIssue 45 is marked `Status: bug, complete`, all seven acceptance boxes are ticked, and it has a Delivered section. I wrote it to `docs/project/issues/archive/`, but the old file is still in place and needs `git rm`.\n\n- **Moved:** the issue now lives at `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md`, matching the earlier archived issues and the archive link set in `issue-tracker.md`. I have no shell, so I couldn't delete the original at `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md`. Until someone runs `git rm` on it, both copies exist.\n- **Status line** changed from `ready-for-agent` to `complete`, as `triage-labels.md` says.\n- **New `### Delivered` comment**, laid out like archived issue 44:\n  - It names the delivering plan (`51-45-\u2026`) and points to `TRANSLATE_WORKER.md` and the `DEPLOYMENT.md` triage table for the behaviour, without repeating them.\n  - The worker change, written from the shipped code: `WhitelistBusy` raised for `locked`/`busy`/`unable to open` at the claim-time `resolve_video` only; `run_job -> bool` with requeue plus one warning; `serve` waits `TRANSIENT_BACKOFF_SECONDS` in `POLL_SECONDS` slices, refreshing progress each slice.\n  - The tests that landed in `tests/active/test_translate_worker.py`.\n  - The limits: a stop during sqlite's 30 s busy wait is slow to act; a wrong `--whitelist-db` path holds the head of the queue; keys already `failed` stay that way.\n- **Acceptance boxes:** all seven are ticked, each checked against the tree.\n  - Real `BEGIN EXCLUSIVE` and missing-file cases are in the durable requeue test.\n  - The back-off gap and the stop during it are covered by the two `serve` tests.\n  - The `no such column` and `no such table` control is covered.\n  - The docs box: the `TRANSLATE_WORKER.md` and `DEPLOYMENT.md` updates are already in the tree.\n  - The suite box: the pre-harvest full run exited 0.\n  - The recovery box carries a short note. The harvest retired its own test, and the durable suite now covers recovery only through its parts.\n- **Unchanged:** the Problem, Proposed solution, Triage and Agent Brief text stays as recorded.\n\n**Check this:** while I was verifying, `engine/server/db/jobs/translate-worker.py:432` read `for word in ()`, which turns the transient check off. A `translate-worker.py.bak` holds the correct `(\"locked\", \"busy\", \"unable to open\")`. The build diff also has the correct tuple. The latest `last_test_validation.json` run shows the requeue test failing against this. It looks like the harvester's mutation proof, still running and not yet restored. I didn't touch it, but make sure the file is restored from `.bak` before the build closes.\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/45-translate-worker-whitelist-locked-at-claim.md \u2014 this is the original path of the archived issue. It needs `git rm` (or the move redone as `git mv`) because I have no delete tool. Until then, both copies exist.\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/issue-tracker.md": "<changes>\nRemoved row 45 from the open-issues table, because the issue is delivered and archived.\n\n- The checklist asked for row 45 to be set to `complete` with its link pointed at `archive/`. The file's own rule (line 3) says something else: the table lists open issues only, and a row is removed when its issue moves to `archive/`. There are no archived rows in the table to copy; for example, the archived issue 44 has no row. So I deleted row 45 instead of rewriting it.\n- `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md` already exists. The copy at `docs/project/issues/45-\u2026md` is still there too, so whoever owns the issue-file move needs to delete it.\n- Rows 42 and 43 are unchanged.\n- Something I noticed and did not touch: `docs/project/issues/41-short-similarity-cache-tests.md` is outside `archive/` but has no row in the table.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/roadmap.md": "<changes>\nRoadmap F11-M2: moved issue `45`'s whitelist.db requeue with back-off from an open item into the line's Delivered list.\n\n- Line 60 (PARTIAL \u2014 F11-M2): removed \"Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`.\" and added it to the Delivered list as \"that worker's requeue with back-off when `whitelist.db` is locked or missing at claim (issue `45`, `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md`)\". It uses the TRANSLATE_WORKER.md pointer the sentence before it already gives, so the line does not repeat the behaviour.\n- I checked this against `translate-worker.py`. `WhitelistBusy` is there, and so is the inline check for `locked`/`busy`/`unable to open`, which covers a missing file as well as a locked one. `TRANSIENT_BACKOFF_SECONDS = 30.0` is there, and so is the back-off in `serve`.\n- The issue link points at the `archive/` path, the same way other delivered lines link their issues. The issue file is moved there in its own checklist turn.\n- The line stays PARTIAL, because plan 50 and the player are still open.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_10": "<moved>\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py::test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true (missing file, held EXCLUSIVE lock) -> tests/active/test_translate_worker.py, group test_translate_worker.py\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py::test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false (videos without video_uuid, zero-byte file) -> tests/active/test_translate_worker.py, group test_translate_worker.py\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py::test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job (injected lock, missing file) -> tests/active/test_translate_worker.py, group test_translate_worker.py\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py::test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim -> tests/active/test_translate_worker.py, group test_translate_worker.py\nHow they landed: `Rig.run` now returns `run_job`'s bool, so phase 1's `_run_job` copy is not carried. One merged `_recording(resolve, locked_calls=0)` records (time, video_id, host), and there is a single `_until`. The two back-offs are separate constants, GAP_BACKOFF_SECONDS = 1.0 and LIVE_BACKOFF_SECONDS = 1.5. There is one LOOKUP_WAIT_SECONDS = 15 s, which is still under the 30 s default. The phase 1 `_job` helper is renamed `_job_tuple` so it doesn't clash with the existing `_jobs`. The docstrings now state the rules, and the module docstring has new \"Whitelist at claim\" and \"Back-off\" paragraphs.\nNot moved (REDUNDANT, per the plan): test_control_an_intact_whitelist_reaches_both_hosts and test_a_job_requeued_on_whitelist_db_claimed_again_once_it_is_usable_runs_to_ready_with_its_queued_at_kept.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\nnone. The `test_translate_worker.py` entry already claims engine/server/db/jobs/translate-worker.py and engine/server/data/subtitles.py. `--audit-map` exits 0 before and after the harvest, and the moved tests add no findings: the group's findings are the same advisory MISSING (subtitles.db, translate-worker.lock) and UNRESOLVABLE (whitelist.db) entries as before.\n</group_map>\n\n<mutations>\nM1 engine/server/db/jobs/translate-worker.py generate: transient words emptied (`for word in ()`) -> test_a_locked_or_unopenable_whitelist_at_claim_\u2026 RED in both cases at `_job_tuple(rig) == (\"queued\", 0, QUEUED_AT, None, None)`, which got ('failed', 1, \u2026); restored with cp, diff clean, GREEN (2 passed)\nM2 engine/server/db/jobs/translate-worker.py generate: \"no such\" added to the transient words -> test_any_other_whitelist_error_at_claim_\u2026 RED in both cases at `(row[\"state\"], row[\"error\"]) == (\"failed\", \"OperationalError: \u2026\")`, which got ('queued', None); restored with cp, diff clean, GREEN (2 passed)\nM3 engine/server/db/jobs/translate-worker.py serve: `if run_job(...) and False:`, so serve ignores the requeue bool -> test_serve_waits_the_back_off_\u2026 RED in both cases at `lookups.calls[1][0] - lookups.calls[0][0] >= GAP_BACKOFF_SECONDS`, a gap of about 0.0002 s; restored with cp, diff clean, GREEN (2 passed)\nM4 engine/server/db/jobs/translate-worker.py serve back-off loop: `progress[\"at\"] = time.monotonic()` replaced by `pass` -> test_serve_refreshes_progress_\u2026 RED at `max(ages) < FRESH_SECONDS`, with an oldest read of 0.2495 s against the 0.1 s bound; restored with cp, diff clean, GREEN (1 passed)\nNone survived and none hung. Each .bak was moved to delete_me/translate-worker.py.bak.m1 to .m4, and there is no .bak left under engine/, client/ or scripts/.\n</mutations>\n\n<cleared>\ndelete_me/ now holds the three in-scope files: test_45_translate_worker_whitelist_locked_at_phase1.py, test_45_translate_worker_whitelist_locked_at_phase2.py and test_45_translate_worker_whitelist_locked_at_phase3.py. It also holds the four restored mutation backups, translate-worker.py.bak.m1 to .m4. The 45-translate-worker-whitelist-locked-at.build.diff that was already there is untouched. tests/tmp no longer holds any test_45_* file. The probe_*.py files there were outside the scope and were left in place. Final counts: I restored the pre-harvest snapshot over the record, then ran `--compare` with no tier named. It ran 5 changed or unmapped groups and carried 58 forward unchanged by digest: 137 passed and 0 failed, with test_translate_worker.py at 56 passed (49 before plus 7 new). Seven results appeared, all from the four harvested tests (2 + 2 + 2 + 1), and none departed. There was no new red and nothing stopped being red. The record is banked (exit 0), and HARVEST_FILE records Steps 5 to 8. Nothing has been deleted: the files in delete_me/ are waiting for the user to remove them.\n</cleared>"
  },
  "requirements": "### Purpose\n\nFix issue `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md` (category bug, ready-for-agent). The translate worker (`engine/server/db/jobs/translate-worker.py`) re-checks every claimed job against the Engine's `whitelist.db` before doing any remote work. If that file is locked past the 30 s busy timeout, or cannot be opened (for example mid-restore), the job ends `failed` today. `failed` is terminal, and enqueue refuses a key in any state, so that video can never be queued again from the CLI or from plan 50's page route. The updater's merge holds a write lock on `whitelist.db` long enough for this to happen in normal operation. After this build such a condition is temporary for the job: it goes back to the queue unspent, the worker backs off, and the job runs once the file is usable again. Real errors still fail the job as today.\n\n### Current behaviour (verified in the tree)\n\n- `resolve_video(whitelist_path, video_id, host, max_duration)` (`translate-worker.py:93-110`) opens `whitelist.db` with `connect_readonly_db` (`engine/server/data/db.py:85`: URI `mode=ro`, so a missing file raises `sqlite3.OperationalError: unable to open database file`). It sets `PRAGMA busy_timeout = 30000` and calls `fetch_video_row` and `list_active_denied_hosts`. It returns `(row, None)` or `(None, refusal_text)`, or raises `sqlite3.Error`. `command_enqueue` (`:113`) also calls it and is out of scope.\n- `generate` (`:420`) calls `resolve_video(args.whitelist_db, *claim[:2], args.max_duration)` first, at `:422`. A refusal raises `JobFailed`.\n- `run_job` (`:455-474`) handles `JobStopped` with `requeue_translate_job(conn, *claim)` and an info log, `JobTakenOver` with an info log, and `JobFailed` with `finish_translate_failed`. A catch-all `except Exception` (`:469`) unloads the model on CUDA OOM, logs with a traceback and writes `failed` with `f\"{type(exc).__name__}: {exc}\"`. A locked or missing `whitelist.db` lands in this catch-all today.\n- `requeue_translate_job(conn, video_id, instance_domain, target_language, started_at) -> bool` (`engine/server/data/subtitles.py:161`) is a conditional update on the running row with that `started_at`: `state = 'queued', attempts = attempts - 1`, and `queued_at` is untouched. It returns False when B1's route took the row over. `claim_translate_job` (`:130`) picks the oldest queued row by `queued_at, rowid`, sets `running`, sets `started_at` and increments `attempts`. `recover_translate_jobs` (`:141`) fails a row found `running` at start with `attempts >= MAX_CLAIMS` (2).\n- `serve` (`translate-worker.py:493-511`) loops while `not stop.is_set()`: it sets `progress[\"at\"] = time.monotonic()`, claims, and when idle sleeps `POLL_SECONDS` (2.0) with `time.sleep`. It deliberately does not use `stop.wait`: the SIGTERM handler sets `stop` on the main thread, and `Event.set` deadlocks if it lands while that thread holds the event's lock inside `wait` (comment at `:506`). It calls `run_job` and resets `idle_since`.\n- `heartbeat_loop` (`:477`) beats every `HEARTBEAT_SECONDS` (5 s) on its own thread unless `progress[\"at\"]` is older than `STALL_SECONDS` (600 s).\n- Docs: `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` has a Known Gaps bullet at line 154 (locked `whitelist.db` fails the job permanently, no requeue or back-off). Error Texts line 137 lists \"a locked `whitelist.db`\" under `<ExceptionType>: <text>`. The Serve Loop section (line 79), the Stop/Crash section (line 141) and the Logs list (lines 159-168) do not mention a transient requeue. `DEPLOYMENT.md:353` is a triage row: \"A job ends `failed` with `OperationalError: database is locked`, or `enqueue` prints `error: whitelist.db: database is locked`\" \u2026 \"The job is not requeued and nothing backs off: the key stays `failed`\" \u2026 \"Re-queue the key \u2026 after the updater run ends\".\n- Existing tests: `tests/active/test_translate_worker.py`. Its job-pipeline rig calls `run_job` in-process over a tmp `whitelist.db` and a tmp `subtitles.db`, with a job enqueued and claimed by the store's own functions (queued_at 1000, started_at 2000). There is an existing stop-requeue test, `test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept`, and subprocess `run` tests for heartbeat and SIGTERM. The triage probe `tests/tmp/probe_45_whitelist_locked_at_claim.py` reproduced the bug in 30.4 s using a rollback-journal whitelist fixture and `BEGIN EXCLUSIVE`.\n\n### R1: Classify transient errors at the claim-time whitelist check\n\n- Only the claim-time call to `resolve_video` inside the worker's job path is affected. An `sqlite3.OperationalError` raised by it is transient when its text, compared case-insensitively, contains `locked`, `busy` or `unable to open`.\n- The transient set is exactly these three (operator decision). Every other error still fails the job permanently through today's path, with today's text (`<ExceptionType>: <text>`). That includes `no such column`, `no such table` (for example a zero-byte file), `file is not a database` and `database disk image is malformed`.\n- The plan 49 draft used a `WhitelistBusy` exception and an `is_transient_db_error` predicate. Those names are suggestions, not requirements. `db.py` already has a precedent for the text-matching shape in `is_interrupted_error`.\n- `command_enqueue`'s handling of the same errors is unchanged: it reports and exits 1.\n\n### R2: Requeue without spending the claim\n\n- A transient error requeues the job through the existing `requeue_translate_job(conn, *claim)`, the function the SIGTERM path uses. No second requeue function is added.\n- After the requeue: `state` is `queued`, `attempts` equals its value before the claim, and `queued_at` is unchanged, so the job stays at the head of the queue. No `error` or `finished_at` is written, and the row is never written `failed` for a transient error.\n- A transient requeue never counts toward the crash-retry limit (`MAX_CLAIMS`), because the attempt is given back.\n- It is logged at warning level with the key (video_id, host) and the error text, prefixed `[translate-worker]` like every other worker line. It does not use `logging.exception`.\n- The CUDA-OOM model unload is not triggered by this path.\n- If `requeue_translate_job` returns False (B1 took the row over), nothing more is written for that job, as for the other conditional writes.\n\n### R3: Back off before the next claim\n\n- After a transient requeue, `serve` waits a back-off of about 30 s (a named module constant, for example `TRANSIENT_BACKOFF_SECONDS = 30.0`) before its next claim, instead of reclaiming at once.\n- `run_job` must tell `serve` that a back-off is due. The mechanism is the designer's choice.\n- The wait must not block the heartbeat. It keeps `progress[\"at\"]` fresh at least as often as the idle poll does (every `POLL_SECONDS`), so the heartbeat thread keeps beating.\n- A stop request (SIGTERM or SIGINT setting `stop`) ends the wait promptly, within about one `POLL_SECONDS` slice, and the worker exits normally.\n- The wait must keep the existing rule that the main thread uses `time.sleep`, not `stop.wait`, for the reason in the comment at `serve` (`translate-worker.py:506`). For example, it can sleep in `POLL_SECONDS` slices and check `stop` between them.\n- The requeue and back-off repeat for as long as the condition lasts. Each cycle reclaims the same head-of-queue job. A whole cycle under a held lock is roughly the 30 s busy wait plus the 30 s back-off; with a missing file it is immediate failure plus the 30 s back-off.\n\n### R4: Recovery once the cause clears\n\n- Once the lock is released or the file restored, the requeued job is claimed on the next pass after the back-off and runs to a normal end state (`ready`, `already_english`, or a non-transient `failed`), exactly as an unaffected job would.\n\n### R5: Documentation\n\n- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`:\n  - Remove the first Known Gaps bullet (locked `whitelist.db`), keeping the second (faster-whisper and VRAM).\n  - In Error Texts, drop \"and a locked `whitelist.db`\" from the `<ExceptionType>: <text>` line.\n  - Describe the requeue and back-off as current behaviour, in the Serve Loop and Job Pipeline step 1 and/or Stop, Crash and Recovery, wherever it reads naturally. Cover what is transient (locked, busy, unable to open, for example during the updater merge or a restore), that the job goes back to `queued` with `attempts` restored and `queued_at` kept, the about 30 s back-off that a stop ends promptly, that it repeats until the file is usable, and that other database errors still fail the job.\n  - Add the new warning log line to Logs.\n- `DEPLOYMENT.md` triage row at line 353: it must no longer say a locked `whitelist.db` fails the job or that the key stays `failed`. It should describe the requeue and back-off (the job stays `queued` and runs once the updater merge or restore ends, with the warning line in the journal). The `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) stays, because enqueue is out of scope.\n- Write as current state, with no \"previously\" history. One paragraph per line, with no softwrap.\n\n### R6: Tests\n\nNew gating tests go in `tests/active/test_translate_worker.py`, reusing its rig (tmp `whitelist.db` and `subtitles.db`, job enqueued and claimed by the store's functions):\n- An exclusive lock (`BEGIN EXCLUSIVE`) is held on a rollback-journal `whitelist.db` throughout the check. The claimed job ends `queued` with `attempts` and `queued_at` as before the claim, not `failed`. Because of the real 30 s busy timeout, the test may instead inject `sqlite3.OperationalError(\"database is locked\")` from `resolve_video` at claim. At least the injected form must be covered, and one real-lock case is preferred if its runtime is acceptable.\n- `whitelist.db` is absent at claim time (a real missing path, giving `unable to open database file`). Same outcome.\n- The next claim after a transient requeue happens no sooner than the back-off. A stop set during the back-off makes `serve` return promptly. The heartbeat progress stays fresh during the wait.\n- Control: a non-transient `sqlite3.OperationalError` such as `no such column` at claim still ends the job `failed` with its text (`OperationalError: no such column\u2026`).\n- Once the lock is released or the file restored, the requeued job is claimed and runs to a normal end state.\n- A warning-level log line naming the key and the error text is emitted on a transient requeue.\n- The existing translate worker and subtitles store tests still pass.\n\n### Out of scope\n\n- Re-queuing keys already `failed`, including ones failed by this bug before the fix.\n- Transient handling for the `enqueue` command (it reports a database error and exits 1) or for remote fetch failures.\n- Changing the 30 s busy timeout, `MAX_CLAIMS`, or the queue cap.\n- `subtitles.db` locking (its own busy timeout and tests).\n- Treating corrupt or partial files (`file is not a database`, `malformed`, `no such table`) as transient.\n\n### Accepted limits\n\n- sqlite's own 30 s busy wait inside `resolve_video` cannot be interrupted, so a stop that arrives during that wait, as opposed to during the back-off, still takes up to about 30 s to take effect. The busy timeout is not changed.\n- While `whitelist.db` stays locked or missing, the head job is reclaimed every cycle and later queued jobs wait behind it. Every job needs the same file, so they could not run anyway.\n\n### Baseline suite state\n\nPre-build baseline: exit code 0, variant false (the suite is green before the build).",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe change is confined to `engine/server/db/jobs/translate-worker.py`, its two docs and its test file. `db.py` and `subtitles.py` are not touched. The steps below are in the order the code runs.\n\n1. **Classify the error at the claim-time check (R1).** A small module-level predicate in the worker, named for example `is_transient_db_error`, follows the shape of `is_interrupted_error` in `db.py`. It takes the `sqlite3.OperationalError` text, lowercases it, and returns True if it contains `locked`, `busy` or `unable to open`. Nothing else counts. A new exception class, `WhitelistBusy`, sits next to `JobStopped` and `JobTakenOver` and carries the error text.\n\n2. **Raise it only from the job path.** In `generate`, only the `resolve_video` call at line 422 gets a narrow guard. If an `OperationalError` from that call passes the predicate, it is raised again as `WhitelistBusy` chained from the original. Otherwise the original exception is re-raised unchanged, so it still reaches `run_job`'s catch-all and ends `failed` with exactly today's text (`OperationalError: no such column\u2026`, `no such table`, `file is not a database`, `malformed`). `resolve_video` itself is unchanged, so `command_enqueue` still reports and exits 1.\n\n3. **Requeue without spending the claim (R2).** `run_job` gets a new `except WhitelistBusy` branch, placed before the catch-all so the CUDA-OOM unload and `logging.exception` are never reached. The branch:\n   - calls the existing `requeue_translate_job(conn, *claim)`, the function the stop path already uses, which sets `queued`, gives back the attempt and leaves `queued_at` alone;\n   - writes no `error` and no `finished_at`;\n   - logs one `logging.warning` line: `[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s` with the error text.\n\n   If the requeue returns False (B1's route took the row over), nothing more is written; the log line still goes out. Because the attempt is given back, `MAX_CLAIMS` crash recovery never counts these requeues.\n\n4. **Tell `serve` to back off (R3).** `run_job` currently returns None. It will return a boolean that is True only from the `WhitelistBusy` branch, and `serve` reads it. When it is True, `serve` runs a back-off loop before its next claim:\n   - a deadline of `TRANSIENT_BACKOFF_SECONDS = 30.0`, a new module constant next to `POLL_SECONDS`;\n   - a loop that runs while `stop` is unset and the deadline has not passed. Each pass refreshes `progress[\"at\"]` and calls `time.sleep(min(POLL_SECONDS, remaining))`.\n\n   This keeps the `time.sleep`-not-`stop.wait` rule from the line 506 comment and refreshes progress at least as often as the idle poll, so the heartbeat thread keeps beating. A stop ends the wait within one slice, after which the outer `while not stop.is_set()` exits normally. The loop reads the module globals at call time, so tests can shorten both constants.\n\n5. **Repeat until the file is usable, then recover (R3, R4).** The job keeps its `queued_at`, so the next claim takes the same job again. Each cycle repeats on its own for as long as the cause lasts. Once the lock is released or the file restored, `resolve_video` succeeds and the job runs exactly like any other job.\n\n6. **Documentation (R5).** In `TRANSLATE_WORKER.md`:\n   - delete the first Known Gaps bullet;\n   - drop \"and a locked `whitelist.db`\" from the Error Texts line;\n   - add a paragraph to Job Pipeline step 1, with a one-line reference in Serve Loop for the back-off, covering:\n     - what counts as transient: locked, busy, unable to open (updater merge, restore);\n     - the job returns to `queued` with `attempts` restored and `queued_at` kept;\n     - the about 30 s back-off, which a stop ends promptly;\n     - the cycle repeats until the file is usable;\n     - every other database error still fails the job;\n   - add the warning line to Logs.\n\n   In `DEPLOYMENT.md:353`, rewrite the job half of the row: the job stays `queued`, the journal shows the warning line, and the job runs on its own once the merge or restore ends. The `enqueue` half stays as it is. Everything is written as current state, one paragraph per line.\n\n7. **Tests (R6).** All new tests go in `tests/active/test_translate_worker.py`, reusing `Rig`.\n   - Injected `sqlite3.OperationalError(\"database is locked\")` from a patched `resolve_video`: the row ends `queued`, `attempts` 0, `queued_at` `QUEUED_AT`, with no `error` or `finished_at`. The test also checks the warning-level log record (via `caplog`) names the key and the text, and that `run_job` returns True.\n   - Real missing file: `rig.whitelist` is deleted before the run. Same outcome.\n   - Real lock: `BEGIN EXCLUSIVE` is held on the rig's rollback-journal whitelist, then released. Same outcome, about 30 s of runtime (see Tradeoffs).\n   - Control: an injected `no such column` ends `failed` with `OperationalError: no such column\u2026`, and `run_job` returns falsy.\n   - Recovery: after a transient requeue, the lock is released or the file rewritten, the job is claimed again through `claim_translate_job` (attempts back to 1) and `run_job` ends `ready`.\n   - Serve-level test, in-process on a thread, with `POLL_SECONDS` and `TRANSIENT_BACKOFF_SECONDS` shortened on the loaded module, a stub runner, and `resolve_video` patched to raise transiently and record call times:\n     - the second claim comes no sooner than the back-off after the first;\n     - `progress[\"at\"]` keeps advancing during the wait;\n     - a `stop` set mid-back-off makes `serve` return within about one slice.\n\n     Setting `stop` from the test thread is safe here; the deadlock the line 506 comment describes needs a signal handler running on the main thread.\n\n   The existing stall test holds `BEGIN EXCLUSIVE` for about 16 s, below the 30 s busy timeout, so its job still ends `not in whitelist` and it is unaffected.\n\n### Alternatives considered\n\n- **Return value from `run_job` vs other signals.**\n  - A flag in the shared `progress` dict would mix the stall clock with control flow.\n  - Letting `WhitelistBusy` propagate up to `serve` would split one job's handling across two functions and bypass `run_job`'s \"exactly one end state\" contract.\n  - A return value is the smallest signal and is local to the one caller.\n- **Guard in `generate` vs inside `resolve_video`.** Classifying inside `resolve_video` would also change `command_enqueue`, which is out of scope. Classifying in `run_job`'s catch-all by inspecting any `OperationalError` would also catch transient `subtitles.db` errors from later steps, which is also out of scope. A guard around the one claim-time call is the only place that matches R1 exactly.\n- **Predicate in `db.py` vs in the worker.** `db.py` holds the precedent. But there is a single caller, and the three substrings are an operator decision about this worker's policy, not a general database fact. Keeping the predicate in the worker touches one fewer file. It can move into `db.py` if a second caller appears.\n- **A new exception vs catching `OperationalError` in `run_job`.** A dedicated exception keeps the classification at the call site that is in scope. It also lets `run_job` list it alongside `JobStopped` and `JobTakenOver` in the same style.\n- **Making the busy timeout a constant so a real-lock test runs fast.** Rejected for now. It would be a refactor made only for the test, and the value must stay 30 s anyway. If the 30 s test proves too slow, this is the upgrade path.\n\n### Risks, gotchas and limitations\n\n- **Substring matching depends on sqlite's wording.** `unable to open` also covers `unable to open database file` caused by a permissions problem or a missing directory. Those would also requeue and back off forever, which is the operator's chosen set. The repeating warning line in the journal is how an operator spots it.\n- **Accepted limit:** a stop that arrives during sqlite's own 30 s busy wait still takes up to about 30 s to take effect.\n- **Accepted limit:** while the head job is blocked, the jobs behind it wait.\n- **Unplanned limit: idle unload is skipped.** `serve` resets `idle_since` after every `run_job`, and the idle-unload check only runs when nothing is claimed. So a model already loaded by an earlier job stays in VRAM for as long as the lock or missing file lasts. I left this unhandled to keep the change small. The cheap fix is to skip the `idle_since` reset on a transient requeue and run the same unload check in the back-off loop.\n- **Log volume.** Under a lock held long-term, the warning repeats about once a minute (30 s busy wait plus 30 s back-off). Under a missing file it repeats about every 30 s. This is intentional, so the condition shows in the journal.\n- **Test patching.** Shortening the constants only works because the back-off loop reads module globals at call time, so the design must not bind them as default arguments.\n\n### Tradeoffs the operator is accepting\n\n- One real-lock test adds about 30 s to the suite, about the same as the triage probe. The injected-lock and missing-file tests cover the same branch in milliseconds. If 30 s is too much, the real-lock test can be dropped (R6 allows the injected form alone) or the timeout constant can be hoisted.\n- A permanently unreadable `whitelist.db` (a missing file or a permissions error) never fails the job. It requeues forever and shows only in the warning log, because the repeat is not capped (R3 asks for that).\n- A loaded model stays resident through a prolonged lock (see the unplanned limit above), unless the operator wants the small idle-unload addition.",
  "conflicts": "none",
  "impacts": "\n<impacts>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"new module-level predicate is_transient_db_error (name per plan)\">\n**What changes:** a new function returns True when the lowercased `sqlite3.OperationalError` text contains `locked`, `busy` or `unable to open`. The plan models it on `is_interrupted_error` in `engine/server/data/db.py:68`. The closer match inside this file is `is_cuda_oom` (`translate-worker.py:351-353`): a one-line docstring, `return isinstance(...) and \"...\" in str(exc).lower()`. Put the new function next to it, or next to the exception classes at :81-90.\n\n**What depends on it:** only the new guard in `generate`.\n\n**Regression risk:**\n- Low for the code itself.\n- The behavioural risk is the substring set. `unable to open database file` is also what sqlite raises when `--whitelist-db` names a wrong path or a missing parent directory. `connect_readonly_db` (`db.py:85-94`) uses `mode=ro`, so it never creates the file. Today a mistyped `--whitelist-db` fails each job with `OperationalError: unable to open database file`. After this change the head job requeues forever, the whole queue stalls, and only the warning line shows it. `command_run` (:520-558) does not check that `--whitelist-db` exists at start.\n- `sqlite3.DatabaseError` subclasses that are not `OperationalError` (`file is not a database`, `database disk image is malformed`) never reach the predicate, which is correct. A whitelist swapped mid-read during a restore could raise `malformed` and still fail the job for good. That is outside R1 but worth knowing.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"new exception class WhitelistBusy, beside JobFailed/JobStopped/JobTakenOver (:81-90)\">\n**What changes:** a new `Exception` subclass with a one-line docstring in the style of its neighbours, for example \"whitelist.db was locked, busy or could not be opened at claim; the job is requeued without spending its claim\". It carries the error text.\n\n**What depends on it:**\n- the guard in `generate` raises it;\n- `run_job` catches it.\n\n**Regression risk:**\n- It must subclass `Exception` directly, never `JobFailed`. Otherwise the `except JobFailed` branch (:466) would end the job `failed`.\n- `run_job` must catch it before `except Exception` (:469).\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"generate() (:420-452), the resolve_video call at :422\">\n**What changes:**\n- A narrow `try/except sqlite3.OperationalError` around only the `resolve_video(args.whitelist_db, *claim[:2], args.max_duration)` call.\n- On a transient error it raises `WhitelistBusy(str(exc)) from exc`. On anything else it re-raises unchanged (bare `raise`).\n- The `refusal is not None` check and everything after it stay outside the try, so no other step's `OperationalError` is classified. That includes `subtitles.db` writes from `store_ready_subtitles` and `mark_translate_finished`.\n- The docstring may need a clause on the transient case.\n\n**What depends on it:**\n- `run_job` (:459), and through it `serve`;\n- every job-pipeline test in `tests/active/test_translate_worker.py`;\n- the bounds case `not in whitelist at claim` (test file :306), which must still end `failed` `not in whitelist`.\n\n**Regression risk:**\n- Medium. A guard placed too wide would turn transient `subtitles.db` lock errors into requeues, which is out of scope.\n- A guard catching `sqlite3.Error` rather than `OperationalError` would still be safe, because the predicate is false for other texts. But the plan says `OperationalError`, and the `no such column` control test pins the text (`OperationalError: no such column\u2026`, built at :474 from `type(exc).__name__`).\n- The unchanged re-raise must keep the original type, so use bare `raise`, not `raise exc from ...`.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"resolve_video() (:93-110)\">\n**What changes:** nothing. The plan keeps it unchanged.\n\n**What depends on it:**\n- `command_enqueue` (:122, which catches `sqlite3.Error` and exits 1);\n- `generate` (:422);\n- the tests, which will monkeypatch it on the loaded module (`monkeypatch.setattr(rig.worker, \"resolve_video\", ...)`). `generate` looks the name up as a module global, so the patch takes effect.\n\n**Regression risk:** none if left alone. The `connect_readonly_db` call (:95) sits outside its try/finally. A missing file therefore raises `unable to open database file` from the connect, before `busy_timeout` is set. The missing-file test relies on this.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"command_enqueue() (:113-148)\">\n**What changes:** nothing (out of scope). It still prints `error: whitelist.db: <text>` and returns `EXIT_ERROR` on a locked or missing whitelist.\n\n**What depends on it:**\n- the enqueue tests;\n- the `DEPLOYMENT.md:291` and `:353` enqueue half;\n- `TRANSLATE_WORKER.md:54`.\n\n**Regression risk:** none, provided the predicate and the new exception live only on the `generate` path. Listed so the next step confirms enqueue output is unchanged.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"run_job() (:455-474): new except WhitelistBusy branch, return type None to bool, docstring\">\n**What changes:**\n- The signature becomes `-> bool`.\n- A new `except WhitelistBusy as exc:` branch, before `except Exception` (:469), and best placed next to `except JobStopped` (:461). It calls `requeue_translate_job(conn, *claim)` (return value ignored, as at :462), logs `logging.warning(\"[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s\", *claim[:2], exc)` and returns True.\n- Every other path returns False, falsy, or falls through to `return False`.\n- The docstring (\"Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job\u2026\") must add the transient requeue and the return value.\n- The branch writes no `error` and no `finished_at`.\n\n**What depends on it:**\n- `serve` (:510), its only production caller;\n- `Rig.run` in the tests (`test_translate_worker.py:480-487`), which discards the return value today and must return it, or the new tests call `rig.worker.run_job` directly;\n- the probe `tests/tmp/probe_45_whitelist_locked_at_claim.py:26`.\n\n**Regression risk:**\n- Medium. Placing the branch after `except Exception` would silently keep today's behaviour.\n- `WhitelistBusy` could reach `logging.exception`, which would log a traceback each cycle, and the CUDA-OOM `is_cuda_oom` unload (:471-472) would never apply.\n- `requeue_translate_job` is a conditional update on `state='running' AND started_at=?` (`subtitles.py:149-153, 161-163`). After a B1 takeover it returns False and writes nothing; the log line still goes out (plan).\n- `requeue_translate_job` itself can raise `sqlite3.Error` if `subtitles.db` is locked past its busy timeout. That would propagate out of the `except` branch, out of `run_job` and out of `serve`, ending the worker. The same exposure already exists on the `JobStopped` path. The next step may want to note it.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"serve() (:493-511): back-off loop after a transient requeue, idle_since, docstring\">\n**What changes:**\n- `run_job`'s result is read.\n- When it is True, a loop runs before the next claim: `deadline = time.monotonic() + TRANSIENT_BACKOFF_SECONDS`, then while not `stop.is_set()` and time remains, `progress[\"at\"] = time.monotonic()` and `time.sleep(min(POLL_SECONDS, remaining))`.\n- The comment at :506 explains why `time.sleep` is used and not `stop.wait` (Event.set from the SIGTERM handler on this thread would deadlock), so that rule carries over. The loop must read the module globals at call time, not bind them as default arguments, so tests can shorten them.\n- The docstring (:494) must mention the back-off.\n\n**What depends on it:**\n- `command_run` (:549);\n- the heartbeat thread (`heartbeat_loop` :477-490, which beats only while `time.monotonic() - progress[\"at\"] <= STALL_SECONDS`);\n- the subprocess tests for idle beats, SIGTERM and the stall (`test_translate_worker.py:889-983`);\n- plan 50's \"generation available\", which comes from the heartbeat age.\n\n**Regression risk:**\n- Medium.\n  - `idle_since = time.monotonic()` (:511) is reset after every `run_job`, and the unload check (:504) runs only when nothing is claimed. A model loaded by an earlier job therefore stays in VRAM through an outage (plan's unplanned limit).\n  - Head-of-line blocking: the same `queued_at` row is reclaimed every cycle (`claim_translate_job` ORDER BY `queued_at`, rowid, `subtitles.py:133`).\n  - During sqlite's 30 s busy wait inside `resolve_video`, `progress[\"at\"]` is not refreshed. That is far under `STALL_SECONDS = 600`, so the heartbeat continues.\n  - SIGTERM during the back-off: the handler runs on the main thread between sleeps, and PEP 475 resumes `time.sleep` after the handler. Exit therefore comes within one `POLL_SECONDS` slice (\u22642 s), well within `TimeoutStopSec=120` (DEPLOYMENT.md:264) and the tests' `STOP_WINDOW_SECONDS = 60`.\n- The idle path (job None) must stay exactly as it is, or `test_idle_run_beats...` (cadence 4.5-6.5 s) could change.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"module constants: new TRANSIENT_BACKOFF_SECONDS = 30.0 beside POLL_SECONDS (:71)\">\n**What changes:** a new constant, ideally with a one-line comment in the file's style, like the other constants (:62, :64, :69, :72).\n\n**What depends on it:**\n- `serve`'s back-off loop;\n- the serve-level test, which shortens it on the loaded module together with `POLL_SECONDS`.\n\n**Regression risk:**\n- Low.\n- `POLL_SECONDS` is also read by `AudioPipe.wait_samples` (:283-285), so a test that shortens it changes that wait too. In-process this only affects the module instance the test loaded (`_worker()` loads a fresh module per call).\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"command_run() (:520-558) and the SIGTERM handler (:537-538)\">\n**What changes:** nothing in the code.\n\n**What depends on it:** `serve`'s new back-off path. The stop event set by the handler ends the back-off. The `finally` (:550-554) then sets stop, joins the heartbeat and closes the connection.\n\n**Regression risk:**\n- Low.\n- Worst-case stop latency becomes: a stop arriving during sqlite's 30 s busy wait, plus at most one 2 s slice. That is still under 120 s.\n- `command_run` does not validate `--whitelist-db`, so a misconfigured path now gives a worker that loops instead of failing jobs (see the predicate entry).\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"requeue_translate_job() (:161-163), claim_translate_job() (:130-138), recover_translate_jobs() (:141-146), MAX_CLAIMS (:18)\">\n**What changes:** nothing. The plan does not touch `subtitles.py`.\n\n**What depends on it:** the new branch reuses `requeue_translate_job` exactly as `JobStopped` does: `state='queued'`, `attempts = attempts - 1`, `queued_at` untouched, conditional on `started_at`.\n\n**Regression risk:**\n- None to the store.\n- Semantics to confirm: the attempt is given back each cycle, so `recover_translate_jobs`' `MAX_CLAIMS` count never sees transient cycles.\n- A SIGKILL during a busy wait leaves `attempts=1`, `running`. The next start requeues it, as today.\n- The docstring of `requeue_translate_job` says \"(a stop mid-job)\". It now has a second caller, so the docstring is slightly stale. That is cosmetic, and the plan says not to touch this file. Flagged as uncertain whether to update.\n</impact>\n<impact path=\"engine/server/data/db.py\" element=\"is_interrupted_error() (:68-74), connect_readonly_db() (:85-94)\">\n**What changes:** nothing. The plan keeps the predicate in the worker.\n\n**What depends on it:** `connect_readonly_db` is what produces `unable to open database file` for a missing whitelist (`mode=ro`). `install_deadline_handler` only interrupts under `statement_deadline`, which `resolve_video` does not use, so `interrupted` never arises here.\n\n**Regression risk:** none (unchanged). Listed because the predicate's wording depends on this function's open mode.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_video_row() (:25), called by resolve_video\">\n**What changes:** nothing.\n\n**What depends on it:** `resolve_video`. I checked it does not swallow `sqlite3.OperationalError`: its excepts at :91/:94/:174 are HTTP and ValueError, and :440 is in a different route handler. So a lock or no-such-column error propagates to the guard unchanged.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/data/moderation.py\" element=\"list_active_denied_hosts() (:137), called by resolve_video\">\n**What changes:** nothing.\n\n**What depends on it:** `resolve_video`'s second read on the same connection. A lock that starts between the two statements raises here, and the guard catches it the same way, because the guard wraps the whole `resolve_video` call.\n\n**Regression risk:** none. The function does not catch sqlite errors.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"new job-pipeline tests (injected lock, real missing file, real BEGIN EXCLUSIVE lock, no-such-column control, recovery)\">\n**What changes:** five or more new tests that reuse `Rig`.\n\n**What depends on it:** the suite runtime. `tests/last_test_validation.json` records 40.6 s for this file today, and the real-lock test adds about 30 s.\n\n**Regression risk:** the risk is in the test mechanics.\n- `Rig.claim()` (:472-478) enqueues and asserts `('queued','queued')`. The recovery test must not call it a second time. It should reclaim through `claim_translate_job(rig.conn, \"en\", ...)` directly, assign `rig.job`, and assert attempts == 1.\n- Missing file: `rig.whitelist.unlink()`. The recovery step rewrites it with `_whitelist(rig.whitelist, JOB_VIDEOS, deny=True)`.\n- Real lock: `sqlite3.connect(rig.whitelist, isolation_level=None).execute(\"BEGIN EXCLUSIVE\")`, as in the stall test (:946-948). `_whitelist` leaves the file in rollback-journal mode (:190), which is what makes the EXCLUSIVE lock block readers. The holder must be closed in `finally`.\n- Logging: `caplog` at WARNING on the root logger. `setup_logging` is never called in-process, and `tests/active/conftest.py` has no logging setup, so capture should work. Assert on `record.levelno == logging.WARNING` and on `getMessage()` containing `v-1`, `peer.example` and the error text.\n- Control `no such column`: `error` must start with `OperationalError: no such column`. Check that `logging.exception` is still emitted, so the catch-all was taken.\n- `Rig.run` (:480-487) must return `run_job`'s value. If not, the tests call `rig.worker.run_job` with their own Namespace.\n- The probe imports `HOST`, `JOB_VIDEOS`, `_subtitles`, `_whitelist` and `_worker` from this module (`tests/tmp/probe_45...:10`), so do not rename these.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"new serve-level test (thread, shortened POLL_SECONDS/TRANSIENT_BACKOFF_SECONDS, stub runner, patched resolve_video)\">\n**What changes:**\n- A new test runs `rig.worker.serve(rig.conn, args, runner, stop, progress)` on a thread. That is safe because `connect_subtitles_db` opens with `check_same_thread=False` (`subtitles.py:27`).\n- It shortens the constants with `monkeypatch.setattr(rig.worker, \"POLL_SECONDS\", ...)` and `monkeypatch.setattr(rig.worker, \"TRANSIENT_BACKOFF_SECONDS\", ...)`.\n- `resolve_video` is patched to record `time.monotonic()` and raise `OperationalError(\"database is locked\")`.\n- The job is only enqueued, not claimed through `Rig.claim`, because `serve` claims it.\n- `StubRunner` has `model = None` and `unload`, which is all `serve` touches.\n\n**What depends on it:** nothing else.\n\n**Regression risk:**\n- Flakiness and hangs.\n  - Use a daemon thread, and `stop.set()` plus `join(timeout)` in `finally`, so a failing assert never hangs the session.\n  - The timing assertions (second claim \u2265 back-off after the first; stop mid-back-off returns within about one slice; `progress[\"at\"]` advances) need margins for a loaded machine. Existing tests use wide margins, for example `BEAT_GAP_MS`.\n- Setting `stop` from the test thread is fine (no signal handler involved).\n- Shortening `POLL_SECONDS` also affects `AudioPipe.wait_samples` on that module instance. This is irrelevant here because the job never reaches the download.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"module docstring (:1-37)\">\n**What changes:** the docstring is the file's spec, listing every behaviour under test. It needs new bullets:\n- under Outcomes, or a new paragraph, the transient requeue (injected lock, missing file, real lock), the `no such column` control and recovery;\n- under Service, or a new paragraph, the serve back-off, heartbeat progress and stop.\n\n**What depends on it:** reviewers. The project keeps this docstring exhaustive.\n\n**Regression risk:** documentation only. Omitting it leaves the spec stale.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on (:932-983), constants STALLED_WINDOW_SECONDS/TEST_STALL_SECONDS/RESUME_SECONDS and the comment at :181\">\n**What changes:** nothing intended.\n\n**What depends on it:** the stall test holds `BEGIN EXCLUSIVE` on the whitelist while the subprocess worker is inside `resolve_video`'s 30 s busy wait. The hold lasts from the claim, which can take up to 10 s (:954), through `TEST_STALL_SECONDS + 1` (5 s) and `STALLED_WINDOW_SECONDS` (11 s). That is about 16-26 s, and the comment at :181 says about 18 s.\n\n**Regression risk:**\n- Low, but the failure mode changes. Today, on a slow machine where the hold passes 30 s, the job fails with `OperationalError: database is locked`.\n- After this change the job is requeued instead and the worker backs off for 30 s, with the heartbeat beating during it. So:\n  - the `_jobs(...) == [(\"running\", None)]` assertion at :962 would read `queued`, or `running` again;\n  - the :972 `(\"failed\", \"not in whitelist\")` assert would wait for a reclaim beyond `RESUME_SECONDS = 8`.\n- Either way it would fail, as it would today. The margin is unchanged.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept (:848-852) and the bounds case 'not in whitelist at claim' (:306, test :712)\">\n**What changes:** nothing.\n\n**What depends on it:**\n- the stop test, which shares the `requeue_translate_job` call with the new branch;\n- the `not in whitelist` case, which exercises the refusal path right after the new guard.\n\n**Regression risk:** low. The bounds case would catch a guard that swallowed the refusal. The stop test would catch a reordering of the excepts that broke `JobStopped`.\n</impact>\n<impact path=\"tests/tmp/probe_45_whitelist_locked_at_claim.py\" element=\"the triage probe\">\n**What changes:** it asserts the old, buggy behaviour (`state == \"failed\"` and `(\"exists\", \"failed\")` on re-enqueue). After the fix it would fail.\n\n**What depends on it:** nothing in the suite. `tests/config.json` maps only `tests/active` files, and no pytest config collects `tests/tmp`. It also calls `run_job(..., runner=None, ...)`, which is still valid for the new branch.\n\n**Regression risk:**\n- None to the suite.\n- It is a stale artefact, so delete it, or leave it as a scratch file. I am not certain of the project's policy for `tests/tmp` probes after a fix; `probe_green.py`, `probe_race.py` and others remain there.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"test_translate_worker.py entry (:599-606) and per-test ids (:3583-3775)\">\n**What changes:** this is a generated artifact holding the file digest, the pass count (49) and the duration (40.6 s). The test runner rewrites it; nobody edits it by hand.\n\n**What depends on it:** the project's test-validation tooling. I am not sure what consumes it.\n\n**Regression risk:** none if it is regenerated by the normal test run. After the build, the count should rise and the duration grow by about 30 s or more.\n</impact>\n<impact path=\"tests/config.json\" element=\"test_translate_worker.py source mapping (:416-424)\">\n**What changes:** nothing. It already maps `translate-worker.py` and `subtitles.py` to this test file, so the change triggers the right test.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" element=\"Known Gaps (:152-155), Error Texts (:137), Job Pipeline step 1 (:83-85), Serve Loop (:79), Logs (:159-168)\">\n**What changes (as the plan states):**\n- delete the :154 bullet and keep the faster-whisper/VRAM bullet;\n- :137 becomes \"`<ExceptionType>: <text>` for anything else, including CUDA out-of-memory\";\n- add the transient paragraph at Job Pipeline step 1;\n- one line on the back-off in Serve Loop;\n- add the `whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: <error>` warning line to Logs.\n\n**What depends on it:**\n- `engine/server/README.md:25` and `DEPLOYMENT.md:230` point here;\n- `CONTEXT.md:19` points here.\n\n**Regression risk:** doc accuracy only. See the docs checklist for the other sections of this file that the plan does not name.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" element=\"Job Lifecycle (:29-39), Job Pipeline intro (:83), Bounds row 'Whitelist and denylist' (:102), Stop, Crash and Recovery (:141), Heartbeat (:150)\">\n**What changes (not named in the plan, but now partly inaccurate):**\n- :33 `queued` meaning: a transiently requeued job is `queued` again with its `attempts` restored.\n- :39 \"Every job ends in exactly one of\u2026\": still true but incomplete. A job may now cycle `queued`/`running` while `whitelist.db` is unavailable, as it already can on stop.\n- :83 \"each bound ending the job `failed`\": step 1 can now return the job to `queued` instead.\n- :141 SIGTERM bullet: \"Stop is checked each time the chunk loop wakes\". A stop during the back-off now ends within one 2 s slice, and a stop during sqlite's busy wait takes up to about 30 s.\n- :150 Heartbeat: progress is recorded \"on every serve pass and every chunk-loop wake (at most 2 s apart)\". The back-off loop also records it each slice. The busy wait records none for up to 30 s, which is under `STALL_SECONDS`.\n\n**Regression risk:** doc drift if these are left unchanged. I am uncertain whether the operator wants them all touched. At minimum :83 and :141 read wrong after the change.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage row :353 (whitelist.db locked)\">\n**What changes:** rewrite the job half.\n- Symptom: a job stays `queued`, or flips between `queued` and `running`, and the journal repeats `[translate-worker] whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: database is locked`, or `unable to open database file`.\n- Cause: the updater's merge holds the lock past 30 s, or a restore has removed the file.\n- Action: none for the job; it runs once the merge or restore ends.\n- The `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) stays.\n- A repeating `unable to open` with no restore in progress means the `--whitelist-db` path or its permissions are wrong. Worth one clause, given the misconfiguration risk.\n\n**What depends on it:** operators.\n\n**Regression risk:** doc only.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage row :348 'Jobs stay queued' and unit note :264 (TimeoutStopSec stop path)\">\n**What changes (not in the plan):**\n- :348 lists the causes of \"Jobs stay `queued`\" as no worker, or one long job ahead. A locked or missing `whitelist.db` is now a third cause, with the warning line as the tell. A cross-reference to :353 would do.\n- :264 describes the SIGTERM path. Adding \"or ends the back-off wait\" is optional; 120 s still covers the worst case (a 30 s busy wait plus a 2 s slice).\n\n**Regression risk:** doc drift only. :348 is the more important of the two.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"glossary entry 'Translate job' (:19)\">\n**What changes:** the entry says a job moves from `queued` to `running` and ends in one of three states, and that \"A job left `running` by a crash is requeued once\u2026\". It does not mention the stop requeue either. A clause such as \"a job whose `whitelist.db` check meets a lock or a missing file goes back to `queued` unspent and is retried after a back-off\" would keep the glossary complete.\n\n**Regression risk:** doc only. I am uncertain it is wanted: the plan names only the two docs, and the glossary already leaves out the stop requeue.\n</impact>\n<impact path=\"docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md\" element=\"Status line (:3), acceptance checkboxes (:95-98), file location\">\n**What changes:** on delivery, per `docs/project/triage-labels.md`:\n- `Status: bug, complete`;\n- the file moves to `docs/project/issues/archive/`;\n- the checkboxes get ticked.\n\n**What depends on it:** `docs/project/issues/issue-tracker.md:8` links it by path.\n\n**Regression risk:** a broken link if the file moves and the tracker row is not updated.\n</impact>\n<impact path=\"docs/project/issues/issue-tracker.md\" element=\"row 45 (:8)\">\n**What changes:** the state goes from `ready-for-agent` to `complete`, and the link moves to `archive/` if the issue file moves. It follows the convention of the earlier archived issues.\n\n**Regression risk:** stale tracker.\n</impact>\n<impact path=\"docs/project/roadmap.md\" element=\"F11-M2 PARTIAL line (:60)\">\n**What changes:** \"Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`.\" becomes a delivered statement, or moves into the Delivered list with a pointer to `TRANSLATE_WORKER.md`.\n\n**Regression risk:** stale roadmap.\n</impact>\n<impact path=\"docs/project/plans/50-translate-generation-in-page.md\" element=\"AC1 feature gate (heartbeat freshness) and AC3 polling while queued/running (:27-29, :49-53)\">\n**What changes:** nothing in this plan, which is a future consumer.\n\n**What depends on it:**\n- The page polls while the state is `queued` or `running`. During an outage it now sees `queued` and `running` alternating indefinitely, instead of a terminal `failed`.\n- Generation availability stays true, because the back-off keeps `progress[\"at\"]` fresh, so the heartbeat beats.\n\n**Regression risk:** none now. Plan 50's design should know a job can sit `queued` for the length of an updater merge.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"Translate worker paragraph (:25) and heartbeat note (:31)\">\n**What changes:** nothing needed. It defers to `TRANSLATE_WORKER.md` for the lifecycle. The heartbeat statement (\"stops beating when the serve loop stalls\") stays true, because the back-off refreshes progress.\n\n**Regression risk:** none. Checked and listed for completeness.\n</impact>\n</impacts>\n",
  "docs_checklist": "- [x] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - updated: TRANSLATE_WORKER.md now says that when `whitelist.db` is locked, busy or can't be opened at claim time, the job goes back to the queue and the worker waits 30 s before claiming again. It no longer says such a job fails for good.\n- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: the translate-worker Triage rows now say that a locked or missing `whitelist.db` puts the job back on the queue with a back-off. It no longer says the job fails.\n- [x] `engine/server/data/subtitles.py` - updated: The `requeue_translate_job` docstring now names both of its callers' cases: a stop mid-job, and `whitelist.db` being unavailable at claim.\n- [x] `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md` - updated: Issue 45 is marked `Status: bug, complete`, all seven acceptance boxes are ticked, and it has a Delivered section. I wrote it to `docs/project/issues/archive/`, but the old file is still in place and needs `git rm`.\n- [x] `docs/project/issues/issue-tracker.md` - updated: Removed row 45 from the open-issues table, because the issue is delivered and archived.\n- [x] `docs/project/roadmap.md` - updated: Roadmap F11-M2: moved issue `45`'s whitelist.db requeue with back-off from an open item into the line's Delivered list.\n- [x] `CONTEXT.md` - out of scope: No sentence in the \"Translate job\" entry (:19) is false. Jobs still move `queued` \u2192 `running` and end in exactly one of `ready`, `already_english` or `failed`. The entry already leaves out requeue paths that are not crash recovery, such as the stop requeue. The transient requeue is the same kind of mechanism and belongs in `TRANSLATE_WORKER.md`, which the entry points to.\n- [x] `tests/active/test_translate_worker.py` - out of scope: The build diff leaves this file unchanged. The new tests live in `tests/tmp/test_45_\u2026_phase{1,2,3}.py`, so the module docstring does not yet describe anything the file fails to test. The harvest plan (`docs/project/plans/harvest-45-translate-worker-whitelist-locked-at-plan.md`, Step 5 notes) moves the four DURABLE tests into this file. That plan states that \"The module docstring of `test_translate_worker.py` gains the transient-whitelist and `serve` back-off rules\", so the harvest owns this update. It must cover the requeue on a missing file and on a held EXCLUSIVE lock, the `no such column`/`no such table` controls, the back-off gap, progress during the back-off, and a stop during it. The recovery-to-ready test is REDUNDANT and is not harvested, so the docstring should not claim it.\n- [x] `engine/server/README.md` - out of scope: The Translate worker paragraph (:25) defers to `TRANSLATE_WORKER.md` for the lifecycle. The heartbeat note (:31), \"stops beating when the serve loop stalls\", stays true because the back-off refreshes progress every slice.\n- [x] `docs/project/plans/50-translate-generation-in-page.md` - out of scope: This is a future plan, not a description of current behaviour. Its gate (heartbeat freshness) and its polling of `queued`/`running` still hold: the heartbeat keeps beating during the back-off, and a job sitting `queued` through an outage is one of the states it already polls. Nothing it claims is false.",
  "docs": [
    {
      "path": "engine/server/db/jobs/docs/TRANSLATE_WORKER.md",
      "note": "Changes:\n- Delete the Known Gaps bullet at :154, and keep the faster-whisper/VRAM bullet.\n- Error Texts :137: drop \"and a locked `whitelist.db`\".\n- Job Pipeline step 1 (:85): add a paragraph covering:\n  - what counts as transient: `locked`, `busy`, `unable to open`, for example during the updater merge or a restore;\n  - the job returns to `queued` with `attempts` restored and `queued_at` kept, with no `error` or `finished_at`;\n  - an about 30 s back-off (`TRANSIENT_BACKOFF_SECONDS`) that a stop ends within one 2 s slice;\n  - the cycle repeats until the file is usable;\n  - every other database error still fails the job as `<ExceptionType>: <text>`.\n- Pipeline intro :83 (\"each bound ending the job `failed`\"): qualify it for step 1's transient case.\n- Serve Loop :79: one line saying a transient requeue is followed by the back-off before the next claim, with progress refreshed during it.\n- Logs: add `whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: <error>` (a warning).\n- Also check :33 (meaning of `queued`) and :39 (\"Every job ends in exactly one of\u2026\").\n- Stop, Crash and Recovery :141: a stop during the back-off ends it promptly; a stop during sqlite's 30 s busy wait takes up to about 30 s.\n- Heartbeat :150: the back-off also records progress.\n- All written as current state, one paragraph per line."
    },
    {
      "path": "DEPLOYMENT.md",
      "note": "Changes:\n- Triage row :353: rewrite the job half. The job stays `queued` and the journal repeats the `whitelist.db unavailable, requeued` warning while the updater merge or a restore holds or removes `whitelist.db`. The job runs by itself afterwards, with no re-queue needed. A repeating `unable to open` outside a restore points at a wrong `--whitelist-db` path or permissions. Keep the `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) as it is.\n- Triage row :348 \"Jobs stay `queued`\": add a locked or missing `whitelist.db` (the warning line) as a cause.\n- Optionally :264 (TimeoutStopSec): the stop path also ends the back-off wait."
    },
    {
      "path": "CONTEXT.md",
      "note": "\"Translate job\" glossary entry (:19): optionally add that a job whose claim-time `whitelist.db` check meets a lock or a missing file returns to `queued` unspent and is retried after a back-off. It is uncertain whether this is wanted, since the entry already leaves out the stop requeue."
    },
    {
      "path": "tests/active/test_translate_worker.py",
      "note": "Module docstring (:1-37), which is the file's behavioural spec. Add:\n- the transient-requeue outcomes: injected lock, missing file, real EXCLUSIVE lock, the `no such column` control and recovery to `ready`;\n- the serve back-off behaviour: next claim no sooner than the back-off, progress advancing, stop ending the wait promptly."
    },
    {
      "path": "docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md",
      "note": "On delivery: `Status: bug, complete`, the acceptance boxes ticked, and the file moved to `docs/project/issues/archive/`."
    },
    {
      "path": "docs/project/issues/issue-tracker.md",
      "note": "Row 45: state set to `complete`, with the link updated to the archive path."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": ":60: replace \"Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`.\" with a delivered statement pointing at `TRANSLATE_WORKER.md`."
    }
  ],
  "reassessments": 1,
  "draft": "## Draft: issue 45, requeue and back off when `whitelist.db` is locked or missing at claim\n\nI read the following before drafting: `translate-worker.py` lines 55-154 and 340-564 (constants, exception classes, `resolve_video`, `command_enqueue`, `is_cuda_oom`, `generate`, `run_job`, `heartbeat_loop`, `serve`, `command_run`), the test file's docstring, `_whitelist`, `_worker`, `Rig`, `StubRunner` and the outcome tests at :799-852, `TRANSLATE_WORKER.md` lines 25-168, and the `DEPLOYMENT.md` rows at :264, :348 and :353. Every claim below is checked against those lines.\n\n### What has to be tested\n\n- The classification at the claim-time check: three real or injected transient forms requeue the job. A non-transient error fails it with today's text, and a refusal (`not in whitelist`) still fails the job; the existing bounds case already covers the refusal.\n- The row after a transient requeue: `queued`, `attempts` 0, `queued_at` 1000, no `error`, no `finished_at`, and no remote request made.\n- The log: exactly one WARNING record naming the key and the error text, and no ERROR or traceback record.\n- The `run_job` return value: True only on a transient requeue.\n- `serve`: the reclaim comes at least one back-off after the first claim; `progress[\"at\"]` advances during the back-off; a stop during the back-off returns within about one slice.\n- Recovery: the same row, claimed again, runs to `ready`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/db/jobs/translate-worker.py` | 1 constant, 1 exception class, 1 predicate, a 5-line guard in `generate`, a new branch and a bool return in `run_job`, a back-off loop in `serve`, 3 docstrings |\n| `tests/active/test_translate_worker.py` | `Rig.run` returns the result; 2 imports, 2 constants and 2 helpers; 4 test functions (8 cases); docstring bullets |\n| `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` | the sections listed under Documentation |\n| `DEPLOYMENT.md` | rows :353 and :348, the note at :264 |\n| issue 45, `issue-tracker.md`, `roadmap.md` | delivery bookkeeping |\n\n`db.py`, `subtitles.py`, `resolve_video` and `command_enqueue` are unchanged.\n\n### `translate-worker.py`\n\n**Constant**, placed after `POLL_SECONDS = 2.0` (:71) with a comment in the file's style:\n\n```python\nPOLL_SECONDS = 2.0\n# Wait after a claim found whitelist.db locked or missing, before the same head job is claimed again (R3).\nTRANSIENT_BACKOFF_SECONDS = 30.0\n```\n\n**Exception**, after `JobTakenOver` (:89-90). It subclasses `Exception` directly and never `JobFailed`; otherwise the `except JobFailed` branch would end the job `failed`.\n\n```python\nclass WhitelistBusy(Exception):\n    \"\"\"whitelist.db was locked, busy or could not be opened at claim; the job is requeued without spending its claim.\"\"\"\n```\n\n**Predicate**, after `is_cuda_oom` (:351-353), in the same shape:\n\n```python\ndef is_transient_db_error(exc: BaseException) -> bool:\n    \"\"\"sqlite3 names a locked, busy or unopenable database in an OperationalError's text; corrupt or partial files are not transient.\"\"\"\n    return isinstance(exc, sqlite3.OperationalError) and any(word in str(exc).lower() for word in (\"locked\", \"busy\", \"unable to open\"))\n```\n\nLadder: rung 2. This is the existing `is_cuda_oom` shape, not a reuse of `db.is_interrupted_error`, because there is one caller and the word set is this worker's policy. It is an inline tuple, not a named constant, because it is read in one place only.\n\n**`generate`**: the guard wraps only the call at :422. The refusal check and everything after it stay outside the `try`, so `subtitles.db` errors from later steps are never classified. A bare `raise` keeps the original type, so the catch-all still writes `OperationalError: \u2026`.\n\n```python\ndef generate(conn: sqlite3.Connection, claim: tuple[str, str, str, int], args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> str:\n    \"\"\"AC3 for one claim (video_id, instance_domain, target_language, started_at), each bound raising JobFailed before the next remote request, a locked or missing whitelist.db raising WhitelistBusy; the end state written.\"\"\"\n    try:\n        row, refusal = resolve_video(args.whitelist_db, *claim[:2], args.max_duration)\n    except sqlite3.OperationalError as exc:\n        if is_transient_db_error(exc):\n            raise WhitelistBusy(str(exc)) from exc\n        raise\n    if refusal is not None:\n        raise JobFailed(refusal)\n    ...  # unchanged from :425\n```\n\n`resolve_video` is looked up as a module global when the call runs, so `monkeypatch.setattr(rig.worker, \"resolve_video\", \u2026)` takes effect. A missing file raises from `connect_readonly_db` at :95, before the `try/finally` there and before `busy_timeout` is set. It surfaces as `unable to open database file` at once.\n\n**`run_job`**: it now returns `-> bool`. The new branch sits right after `JobStopped`, so it is ahead of the catch-all and cannot reach `logging.exception` or the CUDA-OOM unload.\n\n```python\ndef run_job(conn: sqlite3.Connection, job: sqlite3.Row, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> bool:\n    \"\"\"Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job or whitelist.db is locked or missing at claim; a row B1's route took over is left as B1 wrote it. True only for the whitelist.db requeue, so serve backs off before claiming again.\"\"\"\n    claim = (job[\"video_id\"], job[\"instance_domain\"], TARGET_LANGUAGE, job[\"started_at\"])\n    try:\n        state = generate(conn, claim, args, runner, stop, progress)\n        logging.info(\"[translate-worker] job %s video_id=%s host=%s\", state, *claim[:2])\n    except JobStopped:\n        requeue_translate_job(conn, *claim)\n        logging.info(\"[translate-worker] stopped mid-job, requeued video_id=%s host=%s\", *claim[:2])\n    except WhitelistBusy as exc:\n        # No error, no finished_at: the attempt is given back, so MAX_CLAIMS never counts these cycles; False from the requeue (B1 took over) writes nothing more.\n        requeue_translate_job(conn, *claim)\n        logging.warning(\"[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s\", *claim[:2], exc)\n        return True\n    except JobTakenOver:\n        ...  # the three remaining branches are unchanged (:464-474)\n    return False\n```\n\nThe requeue's return value is ignored here, as it is at :462. One known exposure is unchanged: if `requeue_translate_job` itself raises because `subtitles.db` is locked past its own timeout, the exception propagates out of `serve`. The `JobStopped` path already has the same exposure, and `subtitles.db` locking is out of scope.\n\n**`serve`**: the idle path (:503-508) is unchanged byte for byte, which protects the 4.5-6.5 s beat-cadence test.\n\n```python\ndef serve(conn: sqlite3.Connection, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> None:\n    \"\"\"Claim and run jobs one at a time until stop, polling every POLL_SECONDS when idle, waiting TRANSIENT_BACKOFF_SECONDS after a whitelist.db requeue, and unloading the model after IDLE_UNLOAD_SECONDS without a job.\"\"\"\n    idle_since = time.monotonic()\n    while not stop.is_set():\n        ...  # unchanged through the claimed log line (:497-509)\n        if run_job(conn, job, args, runner, stop, progress):\n            # Back off in POLL_SECONDS slices of time.sleep, as above, so a stop ends the wait within one slice and progress stays as fresh as on the idle poll.\n            deadline = time.monotonic() + TRANSIENT_BACKOFF_SECONDS\n            while not stop.is_set() and (remaining := deadline - time.monotonic()) > 0:\n                progress[\"at\"] = time.monotonic()\n                time.sleep(min(POLL_SECONDS, remaining))\n        idle_since = time.monotonic()\n```\n\nBoth constants are read from module globals at run time and are not bound as defaults, so the serve test can shorten them. After a stop, the inner loop exits, then the outer `while` exits, and `command_run`'s `finally` runs as it does today. `idle_since` keeps being reset after every `run_job`; that is the plan's named limit (no idle unload during an outage), not changed here.\n\n### `tests/active/test_translate_worker.py`\n\nTwo imports, `contextlib` and `logging`. `Rig.run` changes to `-> bool` and `return self.worker.run_job(...)`. Existing callers ignore the result, so they are unaffected.\n\n```python\nLOCKED = \"database is locked\"\nUNOPENABLE = \"unable to open database file\"\n# Shortened on the loaded module for the serve test; margins sized for a loaded machine.\nBACKOFF_SECONDS = 1.0\nSLICE_SECONDS = 0.05\n\n\ndef _raising(text: str, then=None):\n    \"\"\"A resolve_video stand-in raising OperationalError(text), on every call, or on the first only and then `then`.\"\"\"\n    calls: list[float] = []\n\n    def resolve(*args):\n        calls.append(time.monotonic())\n        if then is not None and len(calls) > 1:\n            return then(*args)\n        raise sqlite3.OperationalError(text)\n\n    resolve.calls = calls\n    return resolve\n\n\ndef _until(predicate, seconds: float) -> bool:\n    deadline = time.monotonic() + seconds\n    while not predicate():\n        if time.monotonic() > deadline:\n            return False\n        time.sleep(0.01)\n    return True\n\n\n@contextlib.contextmanager\ndef _exclusive(path: Path):\n    \"\"\"BEGIN EXCLUSIVE on the rollback-journal whitelist, held for the block; readers wait out their busy timeout.\"\"\"\n    holder = sqlite3.connect(path, isolation_level=None)\n    try:\n        holder.execute(\"BEGIN EXCLUSIVE\")\n        yield\n    finally:\n        holder.close()\n```\n\n**Transient requeue**, three cases. The real-lock case adds about 30 s, the same as the triage probe; it is kept because R6 prefers it.\n\n```python\n@pytest.mark.parametrize(\"case\", [\"injected lock\", \"missing file\", \"held EXCLUSIVE lock\"])\ndef test_a_whitelist_db_locked_or_missing_at_claim_requeues_the_job_unspent_with_one_warning(rig, monkeypatch, caplog, case):\n    text = UNOPENABLE if case == \"missing file\" else LOCKED\n    hold = contextlib.nullcontext()\n    if case == \"injected lock\":\n        monkeypatch.setattr(rig.worker, \"resolve_video\", _raising(LOCKED))\n    elif case == \"missing file\":\n        rig.whitelist.unlink()\n    else:\n        hold = _exclusive(rig.whitelist)\n    rig.claim()\n    with hold:\n        assert rig.run(StubRunner(rig)) is True\n    row = rig.row()\n    assert (row[\"state\"], row[\"attempts\"], row[\"queued_at\"], row[\"error\"], row[\"finished_at\"]) == (\"queued\", 0, QUEUED_AT, None, None), row\n    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]\n    assert len(warnings) == 1 and all(part in warnings[0] for part in (\"[translate-worker]\", \"v-1\", HOST, text)), warnings\n    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]  # not the catch-all\n    assert rig.instance.opened == [] and rig.media.opened == []\n```\n\n`rig.claim()` runs before the lock is taken, because the claim writes `subtitles.db`, not the whitelist, so the order does not matter for the lock itself. Taking the lock after the claim keeps the hold to the busy wait alone. `setup_logging` is never called in-process, and pytest's caplog handler sits on the root logger at level 0, so WARNING and ERROR records are captured without `set_level`.\n\n**Non-transient control**, two cases. One is injected; the other is a real zero-byte file, which raises `no such table: videos` from `fetch_video_row`.\n\n```python\n@pytest.mark.parametrize(\"case\", [\"injected no such column\", \"zero-byte file\"])\ndef test_a_non_transient_whitelist_db_error_at_claim_still_ends_failed_with_its_text(rig, monkeypatch, caplog, case):\n    if case == \"zero-byte file\":\n        rig.whitelist.write_bytes(b\"\")\n        lead = \"OperationalError: no such table\"\n    else:\n        monkeypatch.setattr(rig.worker, \"resolve_video\", _raising(\"no such column: video_uuid\"))\n        lead = \"OperationalError: no such column\"\n    assert rig.run(StubRunner(rig)) is False\n    row = rig.row()\n    assert row[\"state\"] == \"failed\" and row[\"error\"].startswith(lead), row\n    assert [record.exc_info is not None for record in caplog.records if record.levelno == logging.ERROR] == [True]  # the catch-all's logging.exception\n    assert not [record for record in caplog.records if record.levelno == logging.WARNING]\n```\n\n**Recovery**, two cases. Both cases are fast; the real lock's own release is already shown by the existing stall test.\n\n```python\n@pytest.mark.parametrize(\"case\", [\"lock released\", \"file restored\"])\ndef test_a_requeued_job_claimed_again_once_whitelist_db_is_usable_runs_to_ready(rig, monkeypatch, case):\n    from data.subtitles import claim_translate_job\n\n    if case == \"lock released\":\n        monkeypatch.setattr(rig.worker, \"resolve_video\", _raising(LOCKED, then=rig.worker.resolve_video))\n    else:\n        rig.whitelist.unlink()\n    assert rig.run(StubRunner(rig)) is True\n    assert (rig.row()[\"state\"], rig.row()[\"attempts\"]) == (\"queued\", 0)  # control: requeued unspent\n    if case == \"file restored\":\n        _whitelist(rig.whitelist, JOB_VIDEOS, deny=True)\n    rig.job = claim_translate_job(rig.conn, \"en\", STARTED_AT + 1)\n    assert (rig.job[\"video_id\"], rig.job[\"started_at\"], rig.job[\"attempts\"]) == (\"v-1\", STARTED_AT + 1, 1)\n    assert rig.run(StubRunner(rig)) is False\n    row = rig.row()\n    assert (row[\"state\"], row[\"source\"], row[\"queued_at\"]) == (\"ready\", \"whisper\", QUEUED_AT), row\n```\n\nThe test reclaims through the store function directly. It does not call `Rig.claim` again, because that would enqueue a second time and fail its `(\"queued\", \"queued\")` assert.\n\n**Serve back-off**. It runs on a daemon thread over `rig.conn`, which `connect_subtitles_db` opens with `check_same_thread=False`. Setting `stop` from the test thread is safe because no signal handler is involved.\n\n```python\ndef test_serve_waits_the_back_off_before_reclaiming_keeps_progress_fresh_and_a_stop_ends_the_wait(rig, monkeypatch):\n    monkeypatch.setattr(rig.worker, \"POLL_SECONDS\", SLICE_SECONDS)\n    monkeypatch.setattr(rig.worker, \"TRANSIENT_BACKOFF_SECONDS\", BACKOFF_SECONDS)\n    locked = _raising(LOCKED)\n    monkeypatch.setattr(rig.worker, \"resolve_video\", locked)\n    assert tuple(enqueue_translate_job(rig.conn, \"v-1\", HOST, \"en\", 50, QUEUED_AT)) == (\"queued\", \"queued\")\n    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)\n    stop = threading.Event()\n    progress = {\"at\": time.monotonic()}\n    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, progress), daemon=True)\n    thread.start()\n    try:\n        assert _until(lambda: len(locked.calls) >= 2, 10 * BACKOFF_SECONDS)\n        assert locked.calls[1] - locked.calls[0] >= BACKOFF_SECONDS, locked.calls  # the reclaim waited the back-off\n        time.sleep(0.15)\n        first = progress[\"at\"]\n        time.sleep(0.15)\n        second = progress[\"at\"]\n        assert second > first and time.monotonic() - second < 0.3, (first, second)  # refreshed each slice during the wait\n        assert len(locked.calls) == 2  # control: still inside the second back-off\n        stopped_at = time.monotonic()\n        stop.set()\n        thread.join(5)\n        assert not thread.is_alive() and time.monotonic() - stopped_at < 0.5  # well under the ~0.7 s left of the back-off\n        assert len(locked.calls) == 2  # no claim after the stop\n        row = rig.row()\n        assert (row[\"state\"], row[\"attempts\"], row[\"queued_at\"]) == (\"queued\", 0, QUEUED_AT), row\n    finally:\n        stop.set()\n        thread.join(5)\n```\n\nThe shortened `POLL_SECONDS` also reaches `AudioPipe.wait_samples` on this module instance. That does not matter here, because no job reaches the download.\n\n**Module docstring**: add these to Outcomes.\n\n- `whitelist.db` unavailable at claim: an injected `database is locked`, a removed file (`unable to open database file`) and a real EXCLUSIVE lock held through sqlite's 30 s busy wait each leave the job `queued` with `attempts` 0 and `queued_at` 1000, no `error` or `finished_at`, nothing requested, and one WARNING `[translate-worker] whitelist.db unavailable, requeued \u2026` naming v-1, peer.example and the text, with no ERROR record. `run_job` returns True. An injected `no such column` and a zero-byte file (`no such table`) still end `failed` with `OperationalError: \u2026` through the logged catch-all, and `run_job` returns False. Once the lock is released or the file rewritten, the requeued row claimed again (attempts 1) ends ready/whisper with `queued_at` still 1000.\n\nAdd a paragraph after the Job-pipeline paragraph:\n\n- Serve back-off: `serve` runs in-process on a thread with `POLL_SECONDS` 0.05 s and `TRANSIENT_BACKOFF_SECONDS` 1 s on the loaded module, and `resolve_video` always locked. The second claim's lookup comes no sooner than 1 s after the first; `progress[\"at\"]` advances during the wait; a stop set during the wait returns `serve` within 0.5 s with no further claim and the row `queued`, `attempts` 0.\n\n### Documentation (current state, one paragraph per line)\n\n`TRANSLATE_WORKER.md`:\n- :33 `queued`: append \"A job requeued by a stop or by an unavailable `whitelist.db` is `queued` again with its `attempts` restored and its `queued_at` kept.\"\n- :39: \"Every job ends in exactly one of `ready`, `already_english` or `failed`; on the way it may return to `queued` unspent (a stop, or `whitelist.db` unavailable at claim). A failed key is never queued again.\"\n- :79 Serve Loop: append \"After a job requeued because `whitelist.db` was unavailable, it waits `TRANSIENT_BACKOFF_SECONDS` (30 s) in 2 s slices before the next claim, recording progress each slice; a stop ends the wait within one slice.\"\n- :83: \"For a claimed job, in order, each bound ending the job `failed` before the next remote request (step 1 may instead return the job to `queued`):\"\n- :85 step 1: add a paragraph. When the lookup raises a sqlite `OperationalError` naming `locked`, `busy` or `unable to open` (the updater's merge holding the file past the 30 s busy timeout, or a restore that has removed it), the job goes back to `queued` with `attempts` restored and `queued_at` kept, and no `error` or `finished_at` is written. A warning is logged and the worker backs off about 30 s, which a stop ends promptly. Because the job keeps the head of the queue, the cycle repeats until the file is usable, and the job then runs as any other. Every other database error (`no such table`, `no such column`, `file is not a database`, `malformed`) fails the job as `<ExceptionType>: <text>`.\n- :137: \"`<ExceptionType>: <text>` for anything else, including CUDA out-of-memory\".\n- :141 SIGTERM: append \"A stop during the back-off ends it within one 2 s slice; a stop during sqlite's 30 s busy wait on `whitelist.db` takes effect once that wait ends.\"\n- :150 Heartbeat: \"\u2026on every serve pass, every back-off slice and every chunk-loop wake (at most 2 s apart; a `whitelist.db` busy wait records none for up to 30 s)\u2026\"\n- :154: delete the bullet; the faster-whisper/VRAM bullet stays.\n- Logs: add \"`whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: <error>` (warning)\" after the `stopped mid-job` line.\n\n`DEPLOYMENT.md`:\n- :353, replace with:\n\n  `| A job stays `queued` and the journal repeats `whitelist.db unavailable, requeued video_id=\u2026 host=\u2026: database is locked` (or `unable to open database file`), or `enqueue` prints `error: whitelist.db: database is locked` | The updater's merge holds `whitelist.db` past the 30 s busy timeout, or a restore has removed it. The worker requeues the job unspent and retries after a 30 s back-off; `enqueue` does not retry. A repeating `unable to open` with no restore in progress means the `--whitelist-db` path or its permissions are wrong | Nothing for the job: it runs once the merge or restore ends. Re-run `enqueue` after the updater run ends. Fix the path or permissions for a persistent `unable to open` |`\n- :348 cause: append \", or `whitelist.db` is locked or missing (see the `whitelist.db unavailable` row below)\".\n- :264: \"\u2026puts the job back on the queue without counting a claim, or ends the back-off wait, waits up to\u2026\".\n\n`CONTEXT.md`: not touched. The glossary entry already leaves out the stop requeue, the transient requeue is of the same kind, and the checklist marks it optional.\n\nDelivery bookkeeping:\n- issue 45: `Status: bug, complete`, the boxes ticked, the file moved to `archive/`;\n- `issue-tracker.md` row 45: state `complete` and the link pointed at `archive/`;\n- `roadmap.md:60`: \"Requeue with back-off when `whitelist.db` is locked or missing at claim is delivered (see `TRANSLATE_WORKER.md`).\"\n\n`tests/tmp/probe_45_whitelist_locked_at_claim.py` now asserts the old behaviour. It is not collected, and the draft leaves it alone, as other `tests/tmp` probes are left.\n\n### Check against plan and requirements (pass 1, converged)\n\n- R1: the guard wraps only the `:422` call; the three words match case-insensitively; other errors are re-raised as-is, so the catch-all writes today's text; `command_enqueue` is untouched. \u2713\n- R2: the existing `requeue_translate_job`; no `error` or `finished_at`; one WARNING with the `[translate-worker]` prefix, the key and the text; ahead of the catch-all, so no OOM unload and no traceback; a False from the requeue writes nothing more. \u2713\n- R3: a named 30 s constant; a bool return from `run_job`; `time.sleep` in `POLL_SECONDS` slices with progress refreshed and `stop` checked each slice; repeats each cycle. \u2713\n- R4: the recovery test, through `claim_translate_job`, to `ready`. \u2713\n- R5: every bullet in the settled checklist is covered. \u2713\n- R6: injected, real missing file, real lock, serve timing, stop and progress, the control, recovery and the warning log; existing tests untouched (the stall test's ~16-26 s hold is still below 30 s). \u2713\n\n### Limits carried from the plan\n\n- A stop during sqlite's busy wait still takes up to about 30 s.\n- Head-of-line blocking while the file is unavailable.\n- The model stays loaded through an outage: the idle unload is skipped. The upgrade path is to skip the `idle_since` reset and run the unload check inside the back-off loop.\n- A mistyped `--whitelist-db` loops instead of failing; the `DEPLOYMENT.md` row names it.\n- The suite grows by about 30 s for the real-lock case.",
  "coordination": "none",
  "tests": {
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "test_45_translate_worker_whitelist_locked_at_phase1.py:86 \u2014 `_job(rig) == (\"queued\", 0, QUEUED_AT, None, None)`: state, attempts, queued_at, error, finished_at read back through a fresh connection after run_job, for a deleted whitelist.db and for one held under BEGIN EXCLUSIVE past the 30 s busy timeout. Rig.claim's control has already shown attempts 1 and started_at 2000.",
          "expected": "(\"queued\", 0, 1000, None, None) for both cases. The current code instead gives (\"failed\", 1, 1000, \"OperationalError: ...\", <finished_at ms>), which is what the run showed at line 86 for both cases.",
          "wrong_implementation": "Today's catch-all, which fails the job: reads (\"failed\", 1, ...). A requeue that bumps queued_at or forgets to restore attempts (a plain UPDATE state='queued' and nothing else): reads attempts 1, or a queued_at that is not 1000. A fix that only catches \"database is locked\": reads (\"failed\", ...) in the missing-file case. One that only catches a missing file: reads (\"failed\", ...) in the held-lock case."
        },
        {
          "clause": "C1",
          "assertion": "test_45_translate_worker_whitelist_locked_at_phase1.py:88 and :90 \u2014 exactly one WARNING record, and its message contains \"[translate-worker]\", \"v-1\", \"peer.example\" and the error text the run produced (\"unable to open database file\" or \"database is locked\").",
          "expected": "One WARNING per case. Its message carries the worker tag, both parts of the key, and the exact OperationalError text, which I took from the tracebacks of this run.",
          "wrong_implementation": "A silent requeue with no log, or an INFO-level log: 0 warnings. A warning logged both at the branch and again by a retry wrapper: 2 warnings. A warning reading \"whitelist busy, requeued\" that leaves out the key or the exception text: :90 fails."
        },
        {
          "clause": "C1",
          "assertion": "test_45_translate_worker_whitelist_locked_at_phase1.py:91 \u2014 no record at ERROR or above; :92 \u2014 rig.instance.opened == [] and rig.media.opened == [].",
          "expected": "[] for ERROR records. [] for both hosts. The :92 absence is armed by the control at :78, which saw INSTANCE_THEN_JSON and [MEDIA_URL] on the same rig with whitelist.db intact. The :91 absence is armed by :104, where caplog captured the catch-all's ERROR in this same run.",
          "wrong_implementation": "Requeuing from inside the catch-all after logging.exception: one ERROR record at :91. Treating a locked lookup as \"not found\" or \"proceed without a row\" and going on to fetch captions: the instance shows CAPTIONS_URL at :92."
        },
        {
          "clause": "C1",
          "assertion": "test_45_translate_worker_whitelist_locked_at_phase1.py:93 \u2014 `result is True`, where result is run_job's own return value, called directly.",
          "expected": "True. Today run_job returns None. Line 86 is the line the run stops on today; the assertion at :93 is never reached.",
          "wrong_implementation": "A requeue branch that falls through and returns None as run_job does today, or that returns False the way a failed job does: `None is True` / `False is True`."
        },
        {
          "clause": "C2",
          "assertion": "test_45_translate_worker_whitelist_locked_at_phase1.py:102 \u2014 (state, error) == (\"failed\", \"OperationalError: <text>\") for a videos table with video_uuid dropped (text \"no such column: v.video_uuid\") and for a zero-byte whitelist.db (text \"no such table: videos\").",
          "expected": "(\"failed\", \"OperationalError: no such column: v.video_uuid\") and (\"failed\", \"OperationalError: no such table: videos\"). Both observed passing in this run, since this is today's behaviour, which the phase must keep.",
          "wrong_implementation": "A requeue branch that catches every sqlite3.OperationalError (or every sqlite3.Error): reads (\"queued\", None). Rewrapping the error as JobFailed(\"whitelist unavailable\"): reads (\"failed\", \"whitelist unavailable\")."
        },
        {
          "clause": "C2",
          "assertion": "test_45_translate_worker_whitelist_locked_at_phase1.py:104 and :105 \u2014 exactly one record at ERROR or above, at ERROR level, with exc_info[0] being sqlite3.OperationalError. :106 \u2014 no WARNING records.",
          "expected": "One ERROR record that carries the OperationalError traceback (logging.exception at translate-worker.py:473), and no WARNING. Both observed passing in this run. The :106 absence is armed by :88, which requires exactly one WARNING in the C1 cases.",
          "wrong_implementation": "Sending these through the new branch's logging.warning before failing: 1 WARNING at :106. Catching these in a narrower handler that calls logging.error without exc_info: exc_info None at :105. Logging the error twice: 2 ERROR records at :104."
        },
        {
          "clause": "C2",
          "assertion": "test_45_translate_worker_whitelist_locked_at_phase1.py:107 \u2014 `result is False`, where result is run_job's own return value.",
          "expected": "False. The run currently shows `assert None is False` at :107 in both cases, because run_job returns None today.",
          "wrong_implementation": "A run_job that returns only from the new branch and leaves the catch-all falling through: None. One that returns True for every handled exception: True."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A locked, busy or unopenable `whitelist.db` at claim leaves the job `queued` with attempts restored, `queued_at` kept, no `error` or `finished_at`, nothing requested, and one warning naming the key and the error text, and `run_job` returns True."
        },
        {
          "id": "C2",
          "text": "Any other `whitelist.db` error at claim still ends the job `failed` with `OperationalError: <text>` through the logged catch-all, and `run_job` returns False."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py  4 failed, 1 passed                     0.0s\n  ----------------------------------------------------------------\n  total                                                             4 failed, 1 passed                    30.4s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73: the second whitelist lookup comes at least BACKOFF_SECONDS (1.0, set on the module as TRANSIENT_BACKOFF_SECONDS) after the first. It runs for an injected lock and for a deleted file. The control at :72 bounds the wait at 10 s. :78 asserts every lookup is (\"v-1\", HOST), and :80 asserts the row after stop is (\"queued\", 0, QUEUED_AT).",
          "expected": "A gap of 1.0 s or more between the first and second lookup. Every lookup is for v-1 on HOST. The row ends queued with attempts 0 and queued_at 1000.",
          "wrong_implementation": "Today's `serve` ignores run_job's True and reclaims at once. When I ran it with the constant supplied, the gap was about 0.2 ms, and :73 failed. A requeue that lost v-1's place would show (\"d-1\", DENIED_HOST) at :78. A back-off that spent the attempt or rewrote queued_at would read attempts 1 or a different queued_at at :80."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:97 and :100. At :97, claim_translate_job returns v-1 on HOST with started_at STARTED_AT + 1 and attempts 1. At :100, the final row is (\"ready\", \"whisper\", QUEUED_AT, STARTED_AT + 1, 1, None). Both run for \"lock released\" and for \"file restored\".",
          "expected": "At :97, (\"v-1\", HOST, 2001, 1). At :100, (\"ready\", \"whisper\", 1000, 2001, 1, None).",
          "wrong_implementation": "A requeue that leaves the row unclaimable makes claim_translate_job return None, which fails :97. One that spent the attempt reads attempts 2. A reclaim that fails, is requeued again or rewrites queued_at reads something other than ready/1000 at :100. This is carried at the run_job seam and not through serve. The operator exempted C2 from the red on an earlier round."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "After a `whitelist.db` requeue, the next claim of the same head job comes no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first."
        },
        {
          "id": "C2",
          "text": "Once the lock is released or the file restored, the requeued job claimed again runs to `ready` with its `queued_at` kept."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py  2 failed, 2 passed                     0.0s\n  ----------------------------------------------------------------\n  total                                                             2 failed, 2 passed                     0.4s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:76 \u2014 `max(ages) < FRESH_SECONDS` (0.1 s, two slices): `progress[\"at\"]` is read every 0.01 s for 0.25 s (five slices) inside the second back-off, and no read is more than two slices old. Line 77's control (`len(lookups.calls) == 2`) shows no read came from a fresh claim.",
          "expected": "Under the right implementation every age is under 0.1 s. This is a prediction: I could not observe it, because the phase is not built. The nearest thing I could observe was a probe thread that sets `progress[\"at\"]` and then sleeps 0.05 s, read the same way. Over 20 runs it peaked at 0.0504 s with 6 distinct values per window. Today the run reads the ages growing steadily from 0.0084 s to 0.2498 s.",
          "wrong_implementation": "Today's sliced wait never touches `progress`, so the oldest read is 0.2498 s and the run fails. A wait that sets `progress[\"at\"]` once, when the back-off starts, also reaches about 0.25 s. A wait that refreshes every other slice or less often goes past 0.1 s."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:88 \u2014 the thread is no longer alive and `elapsed < STOP_WITHIN_SECONDS` (0.5 s) after a stop set with more than 0.5 s of the back-off left. Line 81's control checks the time left.",
          "expected": "Observed in a probe against today's code (phase 2's sliced wait): the thread returned 0.041 s after the stop, with 1.24 s of the back-off left. The new wait should match that.",
          "wrong_implementation": "A wait that ignores the stop, such as one `time.sleep(TRANSIENT_BACKOFF_SECONDS)` or a refresh loop that never checks `stop`, keeps running for the remaining ~1.2 s. `elapsed` then reads about 1.2 s and fails the 0.5 s bound."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:89 \u2014 `len(lookups.calls) == 2` after the stop. The pass-through spy counts lookups, and lookup is the first thing a claim reaches. Line 72's control shows the spy records lookups.",
          "expected": "2. Observed in the probe against today's code: still 2 lookups after the stop.",
          "wrong_implementation": "A new wait that leaves the back-off loop and goes round `serve`'s outer loop once more without re-checking `stop` claims the job again. That makes a third lookup, so the count reads 3."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:91 \u2014 `(row[\"state\"], row[\"attempts\"]) == (\"queued\", 0)` after `serve` returns.",
          "expected": "(\"queued\", 0). Observed in the probe against today's code: state queued, attempts 0.",
          "wrong_implementation": "A claim after the stop leaves the row `running` with attempts 1, or requeued with an attempt spent, so the tuple no longer equals (\"queued\", 0)."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "During the back-off, `progress[\"at\"]` keeps advancing at least once per slice."
        },
        {
          "id": "C2",
          "text": "A stop set during the back-off makes `serve` return within about one slice without claiming again."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py  1 failed                               0.0s\n  ----------------------------------------------------------------\n  total                                                             1 failed                               2.1s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nIn both cases of the requeue test, the assertion at line 86 should fail before any other. Today `generate` lets the `resolve_video` OperationalError reach `run_job`'s catch-all, so `_job(rig)` reads `(\"failed\", 1, 1000, \"OperationalError: unable to open database file\" / \"OperationalError: database is locked\", <finished_at>)` instead of `(\"queued\", 0, 1000, None, None)`. The held-lock case reaches this only after the 30 s busy timeout. In both cases of the other-error test, lines 102\u2013106 should hold today, and the test should fail at line 107 on `assert result is False`, because `run_job` returns `None`. The control test should pass.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. I read the `rig` fixture, `Rig` and `StubRunner` from tests/active/test_translate_worker.py:432-549, where the test imports them. I did not read the `clip` fixture body past line 425 or the `_whitelist` and `_worker` helpers. Nothing in my answer to whether a stub would pass depends on them.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (38 clauses: 17 must_prove, 12 docstring, 9 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"locked\" whitelist.db at claim requeues | :86 (held EXCLUSIVE case) | failing the job when another process holds a lock on the file; to a separate read-only reader that lock shows up only as \"database is locked\" | CARRIED |\n| C1b | must_prove | \"busy\" whitelist.db at claim requeues | :86 (held EXCLUSIVE case, past the 30 s busy_timeout) | treating SQLITE_BUSY after the timeout as a hard failure | CARRIED |\n| C1c | must_prove | \"unopenable\" whitelist.db at claim requeues | :86 (deleted file case) | sending \"unable to open database file\" through the catch-all as failed | CARRIED |\n| C1d | must_prove | job left `queued` | :86 | leaving the row running or failed | CARRIED |\n| C1e | must_prove | attempts restored | :86 (0, against 1 at claim per fixture :478) | requeueing without giving back the spent claim | CARRIED |\n| C1f | must_prove | `queued_at` kept | :86 (QUEUED_AT 1000) | requeue that stamps queued_at with now | CARRIED |\n| C1g | must_prove | no `error` | :86 | requeue that leaves an error text on the row | CARRIED |\n| C1h | must_prove | no `finished_at` | :86 | requeue that stamps finished_at | CARRIED |\n| C1i | must_prove | nothing requested | :92, paired with control :78 | swallowing the error and going on to fetch the instance or media | CARRIED |\n| C1j | must_prove | one warning, exactly | :88 | no warning, or a warning per attempt/retry | CARRIED |\n| C1k | must_prove | warning names the key | :90 (\"v-1\", HOST) | a warning that omits the video_id or host | CARRIED |\n| C1l | must_prove | warning names the error text | :90 (text per case) | a generic warning that drops the sqlite message | CARRIED |\n| C1m | must_prove | `run_job` returns True | :93 (`is True`) | returning None or a truthy non-bool | CARRIED |\n| C2a | must_prove | \"any other whitelist.db error\" still fails, with no requeue | :102 over two cases (dropped column, zero-byte file) | requeueing every OperationalError, or treating an empty file as unopenable | CARRIED |\n| C2b | must_prove | error is `OperationalError: <text>` | :102 (exact equality) | rewrapped, prefixed or truncated error text | CARRIED |\n| C2c | must_prove | through the logged catch-all | :104, :105, :106 | routing through JobFailed (INFO, no exc_info) or through the requeue warning | CARRIED |\n| C2d | must_prove | `run_job` returns False | :107 (`is False`) | returning None | CARRIED |\n| D1 | docstring | run_job on a job claimed through Rig | :84 (rig.claim; fixture :478 asserts claimed once) | running on an unclaimed or twice-claimed job | CARRIED |\n| D2 | docstring | \"a deleted file, a file held under BEGIN EXCLUSIVE past the 30 s busy timeout\" | :90 (text \"database is locked\" / \"unable to open database file\") | a break that never reached the error under claim | CARRIED |\n| D3 | docstring | \"back to queued with attempts 0, queued_at 1000, no error and no finished_at\" | :86 | any one field wrong | CARRIED |\n| D4 | docstring | \"neither host saw a request\" | :92 | fetching after the error | CARRIED |\n| D5 | docstring | \"exactly one WARNING names [translate-worker], the key and the error text\" | :88, :90 | missing prefix, key or text, or a warning count other than one | CARRIED |\n| D6 | docstring | \"nothing is logged at ERROR\" | :91 | also logging through logging.exception | CARRIED |\n| D7 | docstring | \"run_job returns True\" | :93 | non-True return | CARRIED |\n| D8 | docstring | other OperationalError \"ends failed with OperationalError: <text>\" | :102 | requeue, or a different error text | CARRIED |\n| D9 | docstring | \"exactly one ERROR record carries the exception\" | :104, :105 | zero or two ERROR records, or none carrying exc_info | CARRIED |\n| D10 | docstring | \"no WARNING\" | :106 | the requeue branch's warning also firing | CARRIED |\n| D11 | docstring | \"run_job returns False\" | :107 | non-False return | CARRIED |\n| D12 | docstring | control: intact whitelist reaches both hosts | :77, :78 | recorders that never record, which would make :92 empty by construction | CARRIED |\n| N1 | name | \"requeues the job\" | :86 | not queued | CARRIED |\n| N2 | name | \"unspent\" | :86 (attempts 0) | attempts left at 1 | CARRIED |\n| N3 | name | \"requests nothing\" | :92 | any URL opened | CARRIED |\n| N4 | name | \"logs one warning\" | :88 | warning count other than one | CARRIED |\n| N5 | name | \"returns true\" | :93 | non-True return | CARRIED |\n| N6 | name | \"still fails the job\" | :102 | requeue or another end state | CARRIED |\n| N7 | name | \"through the logged catch-all\" | :104, :105 | JobFailed route with no exc_info | CARRIED |\n| N8 | name | \"returns false\" | :107 | non-False return | CARRIED |\n| N9 | name | control \"intact whitelist reaches both hosts\" | :78 | either recorder empty | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/active/../tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:24\n   The only lock case holds the lock past the whole 30 s busy_timeout. Nothing tests a lock released inside the timeout, where the job should run on to `ready` instead of being requeued. That is the edge of the busy condition the requeue branch keys on.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:28\n   FAILED covers only OperationalError. No case covers a malformed whitelist.db that raises a sqlite3.Error which is not an OperationalError, such as non-database bytes giving \"file is not a database\". C2 pins the error text to `OperationalError: <text>`, so this is outside must_prove. It is still the malformed-input edge of \"any other whitelist.db error\".\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. I read the `rig` and `clip` fixtures, `Rig` and `StubRunner` from tests/active/test_translate_worker.py:422-549, which is listed in `code_under_test`. I did not read `_worker()` (:212) or `_whitelist()` (:189). Whether `connect_readonly_db` gives a deleted file \"unable to open database file\" and not a freshly created empty database was taken from the test's own comment at :23. I did not trace it into data/db.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nIn both cases of the requeue test, the assertion at line 86 should fail before any other. Today `generate` lets the `resolve_video` OperationalError reach `run_job`'s catch-all, so `_job(rig)` reads `(\"failed\", 1, 1000, \"OperationalError: unable to open database file\" / \"OperationalError: database is locked\", <finished_at>)` instead of `(\"queued\", 0, 1000, None, None)`. The held-lock case reaches this only after the 30 s busy timeout. In both cases of the other-error test, lines 102\u2013106 should hold today, and the test should fail at line 107 on `assert result is False`, because `run_job` returns `None`. The control test should pass.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. I read the `rig` fixture, `Rig` and `StubRunner` from tests/active/test_translate_worker.py:432-549, where the test imports them. I did not read the `clip` fixture body past line 425 or the `_whitelist` and `_worker` helpers. Nothing in my answer to whether a stub would pass depends on them.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (38 clauses: 17 must_prove, 12 docstring, 9 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"locked\" whitelist.db at claim requeues | :86 (held EXCLUSIVE case) | failing the job when another process holds a lock on the file; to a separate read-only reader that lock shows up only as \"database is locked\" | CARRIED |\n| C1b | must_prove | \"busy\" whitelist.db at claim requeues | :86 (held EXCLUSIVE case, past the 30 s busy_timeout) | treating SQLITE_BUSY after the timeout as a hard failure | CARRIED |\n| C1c | must_prove | \"unopenable\" whitelist.db at claim requeues | :86 (deleted file case) | sending \"unable to open database file\" through the catch-all as failed | CARRIED |\n| C1d | must_prove | job left `queued` | :86 | leaving the row running or failed | CARRIED |\n| C1e | must_prove | attempts restored | :86 (0, against 1 at claim per fixture :478) | requeueing without giving back the spent claim | CARRIED |\n| C1f | must_prove | `queued_at` kept | :86 (QUEUED_AT 1000) | requeue that stamps queued_at with now | CARRIED |\n| C1g | must_prove | no `error` | :86 | requeue that leaves an error text on the row | CARRIED |\n| C1h | must_prove | no `finished_at` | :86 | requeue that stamps finished_at | CARRIED |\n| C1i | must_prove | nothing requested | :92, paired with control :78 | swallowing the error and going on to fetch the instance or media | CARRIED |\n| C1j | must_prove | one warning, exactly | :88 | no warning, or a warning per attempt/retry | CARRIED |\n| C1k | must_prove | warning names the key | :90 (\"v-1\", HOST) | a warning that omits the video_id or host | CARRIED |\n| C1l | must_prove | warning names the error text | :90 (text per case) | a generic warning that drops the sqlite message | CARRIED |\n| C1m | must_prove | `run_job` returns True | :93 (`is True`) | returning None or a truthy non-bool | CARRIED |\n| C2a | must_prove | \"any other whitelist.db error\" still fails, with no requeue | :102 over two cases (dropped column, zero-byte file) | requeueing every OperationalError, or treating an empty file as unopenable | CARRIED |\n| C2b | must_prove | error is `OperationalError: <text>` | :102 (exact equality) | rewrapped, prefixed or truncated error text | CARRIED |\n| C2c | must_prove | through the logged catch-all | :104, :105, :106 | routing through JobFailed (INFO, no exc_info) or through the requeue warning | CARRIED |\n| C2d | must_prove | `run_job` returns False | :107 (`is False`) | returning None | CARRIED |\n| D1 | docstring | run_job on a job claimed through Rig | :84 (rig.claim; fixture :478 asserts claimed once) | running on an unclaimed or twice-claimed job | CARRIED |\n| D2 | docstring | \"a deleted file, a file held under BEGIN EXCLUSIVE past the 30 s busy timeout\" | :90 (text \"database is locked\" / \"unable to open database file\") | a break that never reached the error under claim | CARRIED |\n| D3 | docstring | \"back to queued with attempts 0, queued_at 1000, no error and no finished_at\" | :86 | any one field wrong | CARRIED |\n| D4 | docstring | \"neither host saw a request\" | :92 | fetching after the error | CARRIED |\n| D5 | docstring | \"exactly one WARNING names [translate-worker], the key and the error text\" | :88, :90 | missing prefix, key or text, or a warning count other than one | CARRIED |\n| D6 | docstring | \"nothing is logged at ERROR\" | :91 | also logging through logging.exception | CARRIED |\n| D7 | docstring | \"run_job returns True\" | :93 | non-True return | CARRIED |\n| D8 | docstring | other OperationalError \"ends failed with OperationalError: <text>\" | :102 | requeue, or a different error text | CARRIED |\n| D9 | docstring | \"exactly one ERROR record carries the exception\" | :104, :105 | zero or two ERROR records, or none carrying exc_info | CARRIED |\n| D10 | docstring | \"no WARNING\" | :106 | the requeue branch's warning also firing | CARRIED |\n| D11 | docstring | \"run_job returns False\" | :107 | non-False return | CARRIED |\n| D12 | docstring | control: intact whitelist reaches both hosts | :77, :78 | recorders that never record, which would make :92 empty by construction | CARRIED |\n| N1 | name | \"requeues the job\" | :86 | not queued | CARRIED |\n| N2 | name | \"unspent\" | :86 (attempts 0) | attempts left at 1 | CARRIED |\n| N3 | name | \"requests nothing\" | :92 | any URL opened | CARRIED |\n| N4 | name | \"logs one warning\" | :88 | warning count other than one | CARRIED |\n| N5 | name | \"returns true\" | :93 | non-True return | CARRIED |\n| N6 | name | \"still fails the job\" | :102 | requeue or another end state | CARRIED |\n| N7 | name | \"through the logged catch-all\" | :104, :105 | JobFailed route with no exc_info | CARRIED |\n| N8 | name | \"returns false\" | :107 | non-False return | CARRIED |\n| N9 | name | control \"intact whitelist reaches both hosts\" | :78 | either recorder empty | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/active/../tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:24\n   The only lock case holds the lock past the whole 30 s busy_timeout. Nothing tests a lock released inside the timeout, where the job should run on to `ready` instead of being requeued. That is the edge of the busy condition the requeue branch keys on.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:28\n   FAILED covers only OperationalError. No case covers a malformed whitelist.db that raises a sqlite3.Error which is not an OperationalError, such as non-database bytes giving \"file is not a database\". C2 pins the error text to `OperationalError: <text>`, so this is outside must_prove. It is still the malformed-input edge of \"any other whitelist.db error\".\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. I read the `rig` and `clip` fixtures, `Rig` and `StubRunner` from tests/active/test_translate_worker.py:422-549, which is listed in `code_under_test`. I did not read `_worker()` (:212) or `_whitelist()` (:189). Whether `connect_readonly_db` gives a deleted file \"unable to open database file\" and not a freshly created empty database was taken from the test's own comment at :23. I did not trace it into data/db.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"locked\" whitelist.db at claim requeues",
            "assertion": ":86 (held EXCLUSIVE case)",
            "excludes": "failing the job when another process holds a lock on the file; to a separate read-only reader that lock shows up only as \"database is locked\"",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"busy\" whitelist.db at claim requeues",
            "assertion": ":86 (held EXCLUSIVE case, past the 30 s busy_timeout)",
            "excludes": "treating SQLITE_BUSY after the timeout as a hard failure",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"unopenable\" whitelist.db at claim requeues",
            "assertion": ":86 (deleted file case)",
            "excludes": "sending \"unable to open database file\" through the catch-all as failed",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "job left `queued`",
            "assertion": ":86",
            "excludes": "leaving the row running or failed",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "attempts restored",
            "assertion": ":86 (0, against 1 at claim per fixture :478)",
            "excludes": "requeueing without giving back the spent claim",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "`queued_at` kept",
            "assertion": ":86 (QUEUED_AT 1000)",
            "excludes": "requeue that stamps queued_at with now",
            "status": "CARRIED"
          },
          {
            "id": "C1g",
            "source": "must_prove",
            "clause": "no `error`",
            "assertion": ":86",
            "excludes": "requeue that leaves an error text on the row",
            "status": "CARRIED"
          },
          {
            "id": "C1h",
            "source": "must_prove",
            "clause": "no `finished_at`",
            "assertion": ":86",
            "excludes": "requeue that stamps finished_at",
            "status": "CARRIED"
          },
          {
            "id": "C1i",
            "source": "must_prove",
            "clause": "nothing requested",
            "assertion": ":92, paired with control :78",
            "excludes": "swallowing the error and going on to fetch the instance or media",
            "status": "CARRIED"
          },
          {
            "id": "C1j",
            "source": "must_prove",
            "clause": "one warning, exactly",
            "assertion": ":88",
            "excludes": "no warning, or a warning per attempt/retry",
            "status": "CARRIED"
          },
          {
            "id": "C1k",
            "source": "must_prove",
            "clause": "warning names the key",
            "assertion": ":90 (\"v-1\", HOST)",
            "excludes": "a warning that omits the video_id or host",
            "status": "CARRIED"
          },
          {
            "id": "C1l",
            "source": "must_prove",
            "clause": "warning names the error text",
            "assertion": ":90 (text per case)",
            "excludes": "a generic warning that drops the sqlite message",
            "status": "CARRIED"
          },
          {
            "id": "C1m",
            "source": "must_prove",
            "clause": "`run_job` returns True",
            "assertion": ":93 (`is True`)",
            "excludes": "returning None or a truthy non-bool",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"any other whitelist.db error\" still fails, with no requeue",
            "assertion": ":102 over two cases (dropped column, zero-byte file)",
            "excludes": "requeueing every OperationalError, or treating an empty file as unopenable",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "error is `OperationalError: <text>`",
            "assertion": ":102 (exact equality)",
            "excludes": "rewrapped, prefixed or truncated error text",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "through the logged catch-all",
            "assertion": ":104, :105, :106",
            "excludes": "routing through JobFailed (INFO, no exc_info) or through the requeue warning",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "`run_job` returns False",
            "assertion": ":107 (`is False`)",
            "excludes": "returning None",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "run_job on a job claimed through Rig",
            "assertion": ":84 (rig.claim; fixture :478 asserts claimed once)",
            "excludes": "running on an unclaimed or twice-claimed job",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"a deleted file, a file held under BEGIN EXCLUSIVE past the 30 s busy timeout\"",
            "assertion": ":90 (text \"database is locked\" / \"unable to open database file\")",
            "excludes": "a break that never reached the error under claim",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"back to queued with attempts 0, queued_at 1000, no error and no finished_at\"",
            "assertion": ":86",
            "excludes": "any one field wrong",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"neither host saw a request\"",
            "assertion": ":92",
            "excludes": "fetching after the error",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"exactly one WARNING names [translate-worker], the key and the error text\"",
            "assertion": ":88, :90",
            "excludes": "missing prefix, key or text, or a warning count other than one",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"nothing is logged at ERROR\"",
            "assertion": ":91",
            "excludes": "also logging through logging.exception",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"run_job returns True\"",
            "assertion": ":93",
            "excludes": "non-True return",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "other OperationalError \"ends failed with OperationalError: <text>\"",
            "assertion": ":102",
            "excludes": "requeue, or a different error text",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"exactly one ERROR record carries the exception\"",
            "assertion": ":104, :105",
            "excludes": "zero or two ERROR records, or none carrying exc_info",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"no WARNING\"",
            "assertion": ":106",
            "excludes": "the requeue branch's warning also firing",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"run_job returns False\"",
            "assertion": ":107",
            "excludes": "non-False return",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "control: intact whitelist reaches both hosts",
            "assertion": ":77, :78",
            "excludes": "recorders that never record, which would make :92 empty by construction",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"requeues the job\"",
            "assertion": ":86",
            "excludes": "not queued",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"unspent\"",
            "assertion": ":86 (attempts 0)",
            "excludes": "attempts left at 1",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"requests nothing\"",
            "assertion": ":92",
            "excludes": "any URL opened",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"logs one warning\"",
            "assertion": ":88",
            "excludes": "warning count other than one",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"returns true\"",
            "assertion": ":93",
            "excludes": "non-True return",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"still fails the job\"",
            "assertion": ":102",
            "excludes": "requeue or another end state",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"through the logged catch-all\"",
            "assertion": ":104, :105",
            "excludes": "JobFailed route with no exc_info",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "\"returns false\"",
            "assertion": ":107",
            "excludes": "non-False return",
            "status": "CARRIED"
          },
          {
            "id": "N9",
            "source": "name",
            "clause": "control \"intact whitelist reaches both hosts\"",
            "assertion": ":78",
            "excludes": "either recorder empty",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:26, :29, :73\n   BACKOFF_SECONDS = 1.0\n   assert lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS, lookups.calls\n   The test runs the back-off at one value only, and 1.0 is the only back-off value in the file. That matches the entry's first `<how_to_spot>` bullet. The 10-back-off ceiling at :29/:72 does catch a serve that ignores the patched constant and waits a default of 10 s or more, which follows the entry's own `<alternatives>` (\"an expected value that differs from every default the code already ships\"). Some wrong implementations still pass: a serve that hard-codes any back-off from 1 s up to 10 s, or one that binds the constant when the function is defined so the monkeypatch at :59 never reaches it, as long as that default is under 10 s. The \"30 s default\" in the :28 comment cannot be checked yet because `TRANSIENT_BACKOFF_SECONDS` does not exist in translate-worker.py. Running the observable at a second patched value (e.g. 2.0) and asserting the gap follows it would close this. Not raised to Critical, because the rule's own alternative is partly met.\n\n2. EXEMPT C2: (rules/shape.md, stub question) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84\u2013102\n   rig.job = claim_translate_job(rig.conn, \"en\", STARTED_AT + 1)\n   As the builder concedes, this test passes against the current code. That is the conceded kind, so it is reported here and does not block. But the builder's reason says the test guards recovery \"at both the run_job and serve seams\", and it never calls `serve`. It drives `rig.run` (`run_job`) and calls `claim_translate_job` directly at :95. A phase-2 back-off placed in `serve`'s loop, which is where :56\u2013:80 expects it, is never run by this test. So the test cannot fail if that back-off breaks recovery, and the \"regression guard\" reason only holds for a back-off built into `run_job` or the store. If the back-off is built into the store as a claim-time not-before, :95 claims at a synthetic 2001 ms. A correct implementation could then return None there and turn :97 red for the wrong reason.\n\nPREDICTED FAILURE\nBoth parametrizations of `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` should fail at line 73 on `lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS`. `serve` ignores `run_job`'s True return and reclaims the requeued v-1 straight away, so the second lookup comes milliseconds after the first, not 1.0 s later. The line-72 control passes first. Both cases of `test_a_job_requeued_on_whitelist_db_...` are expected to pass (C2 is exempted).\n\nNOT ASSESSED\n1. `fixtures_path` was given as \"none found\". The `rig` and `clip` fixtures, `StubRunner` and `_whitelist` are imported from tests/active/test_translate_worker.py, which was read as part of `code_under_test`. No conftest was needed.\n2. The shipped default of `TRANSIENT_BACKOFF_SECONDS` could not be checked because the constant does not exist yet in engine/server/db/jobs/translate-worker.py. Recommendation 1 relies on the 30 s default stated in the comment at :28.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 10 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"after a `whitelist.db` requeue\", for both a lock and a missing file | :80 | a failed lookup that fails the job or spends its attempt instead of requeueing it unspent | CARRIED |\n| C1b | must_prove | \"the next claim ... no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first\" | :73 (with :72 as its ceiling) | a `serve` that reclaims about 0.1 ms after the requeue. The :72 control also excludes a `serve` that ignores the module value and waits the 30 s default. The gap is measured between lookups, not between claims (see Recommendation 1) | CARRIED |\n| C1c | must_prove | \"of the same head job\" | :78, :80 | a requeue that loses v-1's place, which would show as a d-1 lookup; a row that does not end back at `queued_at` 1000 | CARRIED |\n| C2 | must_prove | once usable, the requeued job is claimed again and runs to `ready` with `queued_at` kept | :97, :100 | not claimable again; a different `queued_at`; a non-ready end (carried at the `run_job` seam, not through `serve`) | EXEMPT |\n| D1 | docstring | \"lookup fails every time, either from an injected `database is locked` or from a deleted file\" | :80 (parametrized at :55) | a missing file classed as a job failure: the row would end `failed`, not `queued` | CARRIED |\n| D2 | docstring | \"The second lookup comes at least 1.0 s after the first\" | :73 | an immediate re-lookup | CARRIED |\n| D3 | docstring | \"both are for v-1\" | :78 | a d-1 lookup | CARRIED |\n| D4 | docstring | \"After a stop the row is back to queued with attempts 0 and queued_at 1000\" | :77, :80 | a spent attempt; a changed `queued_at`; a row read while `serve` is still running | CARRIED |\n| D5 | docstring | \"a job requeued by `run_job` is first seen queued with attempts 0\" | :91 | a lock or missing file that fails the job, or a requeue that keeps the attempt | CARRIED |\n| D6 | docstring | \"`claim_translate_job` hands back v-1 with attempts 1\" | :97 | a row that is not reclaimable; a different head; an attempts count that keeps growing | CARRIED |\n| D7 | docstring | \"ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1\" | :100 | a reset `queued_at`; a stale `started_at`; an error left on the row | CARRIED |\n| D8 | docstring | \"the four transcribed cues\" | :101 | a missing or partial cue list | CARRIED |\n| D9 | docstring | \"instance and media URLs each requested once\" | :102 | a pipeline that also ran on the locked or missing-file attempt | CARRIED |\n| D10 | docstring | \"guards recovery against a back-off that breaks it\" | none | the recovery test never runs `serve` (:89 and :98 call `run_job`, :95 calls `claim_translate_job` directly), so a back-off in `serve` that blocks recovery passes it | UNCARRIED |\n| N1 | name | \"serve waits the back-off\" | :73 | an immediate reclaim by `serve` | CARRIED |\n| N2 | name | \"its next lookup of the same head job\" | :78 | a lookup of d-1 | CARRIED |\n| N3 | name | \"a job requeued on whitelist.db\" | :91 | a fail or a spent attempt instead of a requeue | CARRIED |\n| N4 | name | \"claimed again once it is usable\" | :97 | a job that cannot be reclaimed after recovery | CARRIED |\n| N5 | name | \"runs to ready with its queued_at kept\" | :100 | a non-ready end; a changed `queued_at` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73\n   C1 says when the next *claim* happens. :73 measures when the next whitelist *lookup* happens, from the `resolve_video` recorder. A lookup always comes at or after its claim, so the lookup gap only bounds the claim gap from one side. One wrong implementation passes: a `serve` that reclaims at once (row `running`, new `started_at`) and then waits the back-off before the lookup. :80 does not catch it, because the requeue still gives the attempt back. The test name (:56) also says \"lookup\" where `must_prove` says \"claim\". Recording when `claim_translate_job` is called on the loaded module would carry the clause as written. It is CARRIED because :73 does exclude the immediate-reclaim defect.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:4\n   D10 is UNCARRIED. The docstring says the recovery test \"guards recovery against a back-off that breaks it\". The back-off under test lives in `serve` (C1 drives `serve` at :69), but the recovery test only calls `rig.run` \u2192 `run_job` (:89, :98) and `claim_translate_job` (:95) directly. Example of a regression it would miss: a `serve` that keeps backing off v-1 after `whitelist.db` is usable again. Either narrow the sentence or drive recovery through `serve`. This is a docstring row on a first audit, so it does not block.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:56\n   The back-off is only tested on the path where it should fire, after a `whitelist.db` requeue. Nothing shows that `serve` claims the next job without a back-off when the previous job ended normally (`ready` or `failed`). So a back-off applied after every job passes this file. No `must_prove` clause names that path.\n\nOBSERVATIONS\n1. clause_map (C2 exemption) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84\n   The builder's reason for the exemption says the recovery test passes \"at both the run_job and serve seams\". In this file it enters only `run_job` and `claim_translate_job`; `serve` is never run in the recovery test (:89, :95, :98). The exemption covers the red, and the operator decided it, so this does not block. But the guard it describes does not cover the seam where the phase-2 back-off lives (see D10).\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The `rig` and `clip` fixtures, `Rig.run`, `Rig.row` and `StubRunner` were read from tests/active/test_translate_worker.py (:423\u2013:549), which the test imports at :20. No conftest was located.\n2. engine/server/data/db.py `connect_readonly_db` was not read. D1's missing-file case was judged from :80 only: a row ending `queued` rather than `failed` shows the error was classed as transient. Which error text the missing file produces was not checked.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:26, :29, :73\n   BACKOFF_SECONDS = 1.0\n   assert lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS, lookups.calls\n   The test runs the back-off at one value only, and 1.0 is the only back-off value in the file. That matches the entry's first `<how_to_spot>` bullet. The 10-back-off ceiling at :29/:72 does catch a serve that ignores the patched constant and waits a default of 10 s or more, which follows the entry's own `<alternatives>` (\"an expected value that differs from every default the code already ships\"). Some wrong implementations still pass: a serve that hard-codes any back-off from 1 s up to 10 s, or one that binds the constant when the function is defined so the monkeypatch at :59 never reaches it, as long as that default is under 10 s. The \"30 s default\" in the :28 comment cannot be checked yet because `TRANSIENT_BACKOFF_SECONDS` does not exist in translate-worker.py. Running the observable at a second patched value (e.g. 2.0) and asserting the gap follows it would close this. Not raised to Critical, because the rule's own alternative is partly met.\n\n2. EXEMPT C2: (rules/shape.md, stub question) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84\u2013102\n   rig.job = claim_translate_job(rig.conn, \"en\", STARTED_AT + 1)\n   As the builder concedes, this test passes against the current code. That is the conceded kind, so it is reported here and does not block. But the builder's reason says the test guards recovery \"at both the run_job and serve seams\", and it never calls `serve`. It drives `rig.run` (`run_job`) and calls `claim_translate_job` directly at :95. A phase-2 back-off placed in `serve`'s loop, which is where :56\u2013:80 expects it, is never run by this test. So the test cannot fail if that back-off breaks recovery, and the \"regression guard\" reason only holds for a back-off built into `run_job` or the store. If the back-off is built into the store as a claim-time not-before, :95 claims at a synthetic 2001 ms. A correct implementation could then return None there and turn :97 red for the wrong reason.\n\nPREDICTED FAILURE\nBoth parametrizations of `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` should fail at line 73 on `lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS`. `serve` ignores `run_job`'s True return and reclaims the requeued v-1 straight away, so the second lookup comes milliseconds after the first, not 1.0 s later. The line-72 control passes first. Both cases of `test_a_job_requeued_on_whitelist_db_...` are expected to pass (C2 is exempted).\n\nNOT ASSESSED\n1. `fixtures_path` was given as \"none found\". The `rig` and `clip` fixtures, `StubRunner` and `_whitelist` are imported from tests/active/test_translate_worker.py, which was read as part of `code_under_test`. No conftest was needed.\n2. The shipped default of `TRANSIENT_BACKOFF_SECONDS` could not be checked because the constant does not exist yet in engine/server/db/jobs/translate-worker.py. Recommendation 1 relies on the 30 s default stated in the comment at :28.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 10 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"after a `whitelist.db` requeue\", for both a lock and a missing file | :80 | a failed lookup that fails the job or spends its attempt instead of requeueing it unspent | CARRIED |\n| C1b | must_prove | \"the next claim ... no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first\" | :73 (with :72 as its ceiling) | a `serve` that reclaims about 0.1 ms after the requeue. The :72 control also excludes a `serve` that ignores the module value and waits the 30 s default. The gap is measured between lookups, not between claims (see Recommendation 1) | CARRIED |\n| C1c | must_prove | \"of the same head job\" | :78, :80 | a requeue that loses v-1's place, which would show as a d-1 lookup; a row that does not end back at `queued_at` 1000 | CARRIED |\n| C2 | must_prove | once usable, the requeued job is claimed again and runs to `ready` with `queued_at` kept | :97, :100 | not claimable again; a different `queued_at`; a non-ready end (carried at the `run_job` seam, not through `serve`) | EXEMPT |\n| D1 | docstring | \"lookup fails every time, either from an injected `database is locked` or from a deleted file\" | :80 (parametrized at :55) | a missing file classed as a job failure: the row would end `failed`, not `queued` | CARRIED |\n| D2 | docstring | \"The second lookup comes at least 1.0 s after the first\" | :73 | an immediate re-lookup | CARRIED |\n| D3 | docstring | \"both are for v-1\" | :78 | a d-1 lookup | CARRIED |\n| D4 | docstring | \"After a stop the row is back to queued with attempts 0 and queued_at 1000\" | :77, :80 | a spent attempt; a changed `queued_at`; a row read while `serve` is still running | CARRIED |\n| D5 | docstring | \"a job requeued by `run_job` is first seen queued with attempts 0\" | :91 | a lock or missing file that fails the job, or a requeue that keeps the attempt | CARRIED |\n| D6 | docstring | \"`claim_translate_job` hands back v-1 with attempts 1\" | :97 | a row that is not reclaimable; a different head; an attempts count that keeps growing | CARRIED |\n| D7 | docstring | \"ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1\" | :100 | a reset `queued_at`; a stale `started_at`; an error left on the row | CARRIED |\n| D8 | docstring | \"the four transcribed cues\" | :101 | a missing or partial cue list | CARRIED |\n| D9 | docstring | \"instance and media URLs each requested once\" | :102 | a pipeline that also ran on the locked or missing-file attempt | CARRIED |\n| D10 | docstring | \"guards recovery against a back-off that breaks it\" | none | the recovery test never runs `serve` (:89 and :98 call `run_job`, :95 calls `claim_translate_job` directly), so a back-off in `serve` that blocks recovery passes it | UNCARRIED |\n| N1 | name | \"serve waits the back-off\" | :73 | an immediate reclaim by `serve` | CARRIED |\n| N2 | name | \"its next lookup of the same head job\" | :78 | a lookup of d-1 | CARRIED |\n| N3 | name | \"a job requeued on whitelist.db\" | :91 | a fail or a spent attempt instead of a requeue | CARRIED |\n| N4 | name | \"claimed again once it is usable\" | :97 | a job that cannot be reclaimed after recovery | CARRIED |\n| N5 | name | \"runs to ready with its queued_at kept\" | :100 | a non-ready end; a changed `queued_at` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73\n   C1 says when the next *claim* happens. :73 measures when the next whitelist *lookup* happens, from the `resolve_video` recorder. A lookup always comes at or after its claim, so the lookup gap only bounds the claim gap from one side. One wrong implementation passes: a `serve` that reclaims at once (row `running`, new `started_at`) and then waits the back-off before the lookup. :80 does not catch it, because the requeue still gives the attempt back. The test name (:56) also says \"lookup\" where `must_prove` says \"claim\". Recording when `claim_translate_job` is called on the loaded module would carry the clause as written. It is CARRIED because :73 does exclude the immediate-reclaim defect.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:4\n   D10 is UNCARRIED. The docstring says the recovery test \"guards recovery against a back-off that breaks it\". The back-off under test lives in `serve` (C1 drives `serve` at :69), but the recovery test only calls `rig.run` \u2192 `run_job` (:89, :98) and `claim_translate_job` (:95) directly. Example of a regression it would miss: a `serve` that keeps backing off v-1 after `whitelist.db` is usable again. Either narrow the sentence or drive recovery through `serve`. This is a docstring row on a first audit, so it does not block.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:56\n   The back-off is only tested on the path where it should fire, after a `whitelist.db` requeue. Nothing shows that `serve` claims the next job without a back-off when the previous job ended normally (`ready` or `failed`). So a back-off applied after every job passes this file. No `must_prove` clause names that path.\n\nOBSERVATIONS\n1. clause_map (C2 exemption) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84\n   The builder's reason for the exemption says the recovery test passes \"at both the run_job and serve seams\". In this file it enters only `run_job` and `claim_translate_job`; `serve` is never run in the recovery test (:89, :95, :98). The exemption covers the red, and the operator decided it, so this does not block. But the guard it describes does not cover the seam where the phase-2 back-off lives (see D10).\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The `rig` and `clip` fixtures, `Rig.run`, `Rig.row` and `StubRunner` were read from tests/active/test_translate_worker.py (:423\u2013:549), which the test imports at :20. No conftest was located.\n2. engine/server/data/db.py `connect_readonly_db` was not read. D1's missing-file case was judged from :80 only: a row ending `queued` rather than `failed` shows the error was classed as transient. Which error text the missing file produces was not checked.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"after a `whitelist.db` requeue\", for both a lock and a missing file",
            "assertion": ":80",
            "excludes": "a failed lookup that fails the job or spends its attempt instead of requeueing it unspent",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"the next claim ... no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first\"",
            "assertion": ":73 (with :72 as its ceiling)",
            "excludes": "a `serve` that reclaims about 0.1 ms after the requeue. The :72 control also excludes a `serve` that ignores the module value and waits the 30 s default. The gap is measured between lookups, not between claims (see Recommendation 1)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"of the same head job\"",
            "assertion": ":78, :80",
            "excludes": "a requeue that loses v-1's place, which would show as a d-1 lookup; a row that does not end back at `queued_at` 1000",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "once usable, the requeued job is claimed again and runs to `ready` with `queued_at` kept",
            "assertion": ":97, :100",
            "excludes": "not claimable again; a different `queued_at`; a non-ready end (carried at the `run_job` seam, not through `serve`)",
            "status": "EXEMPT"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"lookup fails every time, either from an injected `database is locked` or from a deleted file\"",
            "assertion": ":80 (parametrized at :55)",
            "excludes": "a missing file classed as a job failure: the row would end `failed`, not `queued`",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"The second lookup comes at least 1.0 s after the first\"",
            "assertion": ":73",
            "excludes": "an immediate re-lookup",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"both are for v-1\"",
            "assertion": ":78",
            "excludes": "a d-1 lookup",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"After a stop the row is back to queued with attempts 0 and queued_at 1000\"",
            "assertion": ":77, :80",
            "excludes": "a spent attempt; a changed `queued_at`; a row read while `serve` is still running",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"a job requeued by `run_job` is first seen queued with attempts 0\"",
            "assertion": ":91",
            "excludes": "a lock or missing file that fails the job, or a requeue that keeps the attempt",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"`claim_translate_job` hands back v-1 with attempts 1\"",
            "assertion": ":97",
            "excludes": "a row that is not reclaimable; a different head; an attempts count that keeps growing",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1\"",
            "assertion": ":100",
            "excludes": "a reset `queued_at`; a stale `started_at`; an error left on the row",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"the four transcribed cues\"",
            "assertion": ":101",
            "excludes": "a missing or partial cue list",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"instance and media URLs each requested once\"",
            "assertion": ":102",
            "excludes": "a pipeline that also ran on the locked or missing-file attempt",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"guards recovery against a back-off that breaks it\"",
            "assertion": "none",
            "excludes": "the recovery test never runs `serve` (:89 and :98 call `run_job`, :95 calls `claim_translate_job` directly), so a back-off in `serve` that blocks recovery passes it",
            "status": "UNCARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"serve waits the back-off\"",
            "assertion": ":73",
            "excludes": "an immediate reclaim by `serve`",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"its next lookup of the same head job\"",
            "assertion": ":78",
            "excludes": "a lookup of d-1",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"a job requeued on whitelist.db\"",
            "assertion": ":91",
            "excludes": "a fail or a spent attempt instead of a requeue",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"claimed again once it is usable\"",
            "assertion": ":97",
            "excludes": "a job that cannot be reclaimed after recovery",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"runs to ready with its queued_at kept\"",
            "assertion": ":100",
            "excludes": "a non-ready end; a changed `queued_at`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. EXEMPT C2: stub question (rules/shape.md, Recommendation per the exemption). Applies to tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84\u2013102. Test 2 (lines 84\u2013102) calls `run_job` and `claim_translate_job` directly and never runs `serve`. Phase 1's `run_job` WhitelistBusy branch already does the requeue (translate-worker.py:474\u2013478), so lines 91, 97, 100, 101 and 102 pass against the code as it stands, and they would also pass against a phase-2 stub that changed nothing. The builder concedes this. The exemption looks right. The assertions sit at rung 1, use independent literals, and include a positive control (line 91), so the test is sound as a regression guard. It cannot catch a phase-2 back-off in `serve` that breaks recovery, because it never enters `serve`. The test's docstring says this itself.\n2. single-value-pin (rules/shape.md): no rule finding; this is a residual gap. Applies to tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:59, :72 and :73. The back-off is tested at only one value, `BACKOFF_SECONDS = 1.0`.\n   - Line 72's ten-back-off cap means a `serve` that ignores the patched constant and waits the shipped default fails. Waiting with `POLL_SECONDS` or not waiting at all also fails. This is the entry's second `<alternatives>` bullet.\n   - The gap: a `serve` that hard-codes any literal wait between 1 s and 10 s still passes, because nothing checks that the wait follows `TRANSIENT_BACKOFF_SECONDS`.\n   - Fix: add a second value (for example 2.0) and check that the gap between lookups tracks it.\n   \n   This is not Critical: the plausible wrong implementations all fail, and the expected value is not the shipped default.\n\nPREDICTED FAILURE\nFails at line 73 (`lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS`) in both the \"injected lock\" and \"missing file\" cases. `serve` (translate-worker.py:509\u2013527) goes straight back into `claim_translate_job` after `run_job` returns True from the WhitelistBusy requeue. So the second v-1 lookup comes well under 1.0 s after the first, roughly the 0.1 ms the comment at line 25 records. Test 2 (lines 84\u2013102) stays green; that is the exempted C2.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The `rig` fixture, `Rig.run`, `Rig.row`, `StubRunner` and `_whitelist` were read from tests/active/test_translate_worker.py (lines 432\u2013549). `clip` and the module loader `_worker` (around line 173) were not read in full.\n2. I did not read `connect_readonly_db` or `data.subtitles` (`claim_translate_job`, `requeue_translate_job`, `enqueue_translate_job`). Two things are taken from the test's docstring and the comment at translate-worker.py:429, not confirmed in source:\n   - that deleting the whitelist file makes `resolve_video` raise \"unable to open database file\" rather than creating an empty file;\n   - that the requeue keeps `attempts` 0 and `queued_at`.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 10 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"after a `whitelist.db` requeue\", for both a lock and a missing file | :80 (parametrized at :55) | a failed lookup that fails the job or uses up its attempt instead of requeueing it with the attempt unused | CARRIED |\n| C1b | must_prove | \"the next claim ... no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first\" | :73 (with :72 as its ceiling) | a `serve` that reclaims right after the requeue (the loop at translate-worker.py:512\u2013527 goes straight back to `claim_translate_job` after `run_job`). The :72 control also excludes a `serve` that ignores the module value and waits the 30 s default. The gap is measured between lookups, not between claims | CARRIED |\n| C1c | must_prove | \"of the same head job\" | :78, :80 | a requeue that loses v-1's place, which would show up as a d-1 lookup; a row that does not end back at `queued_at` 1000 | CARRIED |\n| C2 | must_prove | once usable, the requeued job is claimed again and runs to `ready` with `queued_at` kept | :97, :100 | not claimable again; a different `queued_at`; an end state other than ready (checked at the `run_job` seam, not through `serve`) | EXEMPT |\n| D1 | docstring | \"lookup fails every time, either from an injected `database is locked` or from a deleted file\" | :80 (parametrized at :55, :60, :63) | a missing file treated as a job failure: the row would end `failed`, not `queued` | CARRIED |\n| D2 | docstring | \"The second lookup comes at least 1.0 s after the first\" | :73 | an immediate re-lookup | CARRIED |\n| D3 | docstring | \"both are for v-1\" | :78 | a d-1 lookup | CARRIED |\n| D4 | docstring | \"After a stop the row is back to queued with attempts 0 and queued_at 1000\" | :77, :80 | an attempt used up; a changed `queued_at`; a row read while `serve` is still running | CARRIED |\n| D5 | docstring | \"a job requeued by `run_job` is first seen queued with attempts 0\" | :91 | a lock or missing file that fails the job, or a requeue that keeps the attempt counted | CARRIED |\n| D6 | docstring | \"`claim_translate_job` hands back v-1 with attempts 1\" | :97 | a row that cannot be reclaimed; a different head job; an attempts count that keeps growing | CARRIED |\n| D7 | docstring | \"ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1\" | :100 | a reset `queued_at`; a stale `started_at`; an error left on the row | CARRIED |\n| D8 | docstring | \"the four transcribed cues\" | :101 | a missing or partial cue list | CARRIED |\n| D9 | docstring | \"instance and media URLs each requested once\" | :102 | a pipeline that also ran on the locked or missing-file attempt | CARRIED |\n| D10 | docstring | withdrawn | n/a | n/a | CARRIED |\n| N1 | name | \"serve waits the back-off\" | :73 | an immediate reclaim by `serve` | CARRIED |\n| N2 | name | \"its next lookup of the same head job\" | :78 | a lookup of d-1 | CARRIED |\n| N3 | name | \"a job requeued on whitelist.db\" | :91 | a failed job or a used-up attempt instead of a requeue | CARRIED |\n| N4 | name | \"claimed again once it is usable\" | :97 | a job that cannot be reclaimed after recovery | CARRIED |\n| N5 | name | \"runs to ready with its queued_at kept\" | :100 | an end state other than ready; a changed `queued_at` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:4\n   D10 was resolved by narrowing the prose, not by adding an assertion. The first-audit sentence \"guards recovery against a back-off that breaks it\" is gone. In its place the docstring now says the test \"drives `run_job` and `claim_translate_job` directly and never runs `serve`, so it checks recovery at those seams only, not past a back-off in `serve`'s loop\". The new sentence matches what :89, :95 and :98 do. Still, nothing in this file asserts that recovery survives the phase-2 back-off inside `serve`. Recorded so the narrowing stays visible.\n2. surfaces (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:95\n   C2 is EXEMPT by the operator's decision. It is still checked at the `run_job`/`claim_translate_job` seam by :97 and :100, so the exemption covers only the claim that it goes red at this checkpoint, not whether it is observable. The part of C2 that is left unproven is \"claimed again\" by `serve` after a back-off. That has an observable at the `serve` seam the first test already drives.\n3. whole-claim (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73\n   C1 is worded in terms of claims, but :73 measures the gap between `resolve_video` calls. In `serve` (translate-worker.py:515, :526 \u2192 :427), every claim of v-1 leads straight into one lookup with no step that can be skipped in between. So the lookup gap stands in for the claim gap. This was already noted on the first audit and is unchanged.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. `rig`, `StubRunner`, `_whitelist` and the constants were read from tests/active/test_translate_worker.py:440\u2013550. The `clip` fixture that `rig` depends on, and `Rig.__init__` above line 440 (including how `rig.whitelist` is seeded with v-1 and d-1), were not read.\n2. `data.subtitles` (`claim_translate_job`, `requeue_translate_job`, `enqueue_translate_job`) and `data.db.connect_readonly_db` are outside `code_under_test` and were not read. The claim that a deleted whitelist.db raises \"unable to open\" and that a requeue restores `queued_at` and `attempts` was taken from the worker's docstrings and comments.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. EXEMPT C2: stub question (rules/shape.md, Recommendation per the exemption). Applies to tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84\u2013102. Test 2 (lines 84\u2013102) calls `run_job` and `claim_translate_job` directly and never runs `serve`. Phase 1's `run_job` WhitelistBusy branch already does the requeue (translate-worker.py:474\u2013478), so lines 91, 97, 100, 101 and 102 pass against the code as it stands, and they would also pass against a phase-2 stub that changed nothing. The builder concedes this. The exemption looks right. The assertions sit at rung 1, use independent literals, and include a positive control (line 91), so the test is sound as a regression guard. It cannot catch a phase-2 back-off in `serve` that breaks recovery, because it never enters `serve`. The test's docstring says this itself.\n2. single-value-pin (rules/shape.md): no rule finding; this is a residual gap. Applies to tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:59, :72 and :73. The back-off is tested at only one value, `BACKOFF_SECONDS = 1.0`.\n   - Line 72's ten-back-off cap means a `serve` that ignores the patched constant and waits the shipped default fails. Waiting with `POLL_SECONDS` or not waiting at all also fails. This is the entry's second `<alternatives>` bullet.\n   - The gap: a `serve` that hard-codes any literal wait between 1 s and 10 s still passes, because nothing checks that the wait follows `TRANSIENT_BACKOFF_SECONDS`.\n   - Fix: add a second value (for example 2.0) and check that the gap between lookups tracks it.\n   \n   This is not Critical: the plausible wrong implementations all fail, and the expected value is not the shipped default.\n\nPREDICTED FAILURE\nFails at line 73 (`lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS`) in both the \"injected lock\" and \"missing file\" cases. `serve` (translate-worker.py:509\u2013527) goes straight back into `claim_translate_job` after `run_job` returns True from the WhitelistBusy requeue. So the second v-1 lookup comes well under 1.0 s after the first, roughly the 0.1 ms the comment at line 25 records. Test 2 (lines 84\u2013102) stays green; that is the exempted C2.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The `rig` fixture, `Rig.run`, `Rig.row`, `StubRunner` and `_whitelist` were read from tests/active/test_translate_worker.py (lines 432\u2013549). `clip` and the module loader `_worker` (around line 173) were not read in full.\n2. I did not read `connect_readonly_db` or `data.subtitles` (`claim_translate_job`, `requeue_translate_job`, `enqueue_translate_job`). Two things are taken from the test's docstring and the comment at translate-worker.py:429, not confirmed in source:\n   - that deleting the whitelist file makes `resolve_video` raise \"unable to open database file\" rather than creating an empty file;\n   - that the requeue keeps `attempts` 0 and `queued_at`.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 10 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"after a `whitelist.db` requeue\", for both a lock and a missing file | :80 (parametrized at :55) | a failed lookup that fails the job or uses up its attempt instead of requeueing it with the attempt unused | CARRIED |\n| C1b | must_prove | \"the next claim ... no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first\" | :73 (with :72 as its ceiling) | a `serve` that reclaims right after the requeue (the loop at translate-worker.py:512\u2013527 goes straight back to `claim_translate_job` after `run_job`). The :72 control also excludes a `serve` that ignores the module value and waits the 30 s default. The gap is measured between lookups, not between claims | CARRIED |\n| C1c | must_prove | \"of the same head job\" | :78, :80 | a requeue that loses v-1's place, which would show up as a d-1 lookup; a row that does not end back at `queued_at` 1000 | CARRIED |\n| C2 | must_prove | once usable, the requeued job is claimed again and runs to `ready` with `queued_at` kept | :97, :100 | not claimable again; a different `queued_at`; an end state other than ready (checked at the `run_job` seam, not through `serve`) | EXEMPT |\n| D1 | docstring | \"lookup fails every time, either from an injected `database is locked` or from a deleted file\" | :80 (parametrized at :55, :60, :63) | a missing file treated as a job failure: the row would end `failed`, not `queued` | CARRIED |\n| D2 | docstring | \"The second lookup comes at least 1.0 s after the first\" | :73 | an immediate re-lookup | CARRIED |\n| D3 | docstring | \"both are for v-1\" | :78 | a d-1 lookup | CARRIED |\n| D4 | docstring | \"After a stop the row is back to queued with attempts 0 and queued_at 1000\" | :77, :80 | an attempt used up; a changed `queued_at`; a row read while `serve` is still running | CARRIED |\n| D5 | docstring | \"a job requeued by `run_job` is first seen queued with attempts 0\" | :91 | a lock or missing file that fails the job, or a requeue that keeps the attempt counted | CARRIED |\n| D6 | docstring | \"`claim_translate_job` hands back v-1 with attempts 1\" | :97 | a row that cannot be reclaimed; a different head job; an attempts count that keeps growing | CARRIED |\n| D7 | docstring | \"ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1\" | :100 | a reset `queued_at`; a stale `started_at`; an error left on the row | CARRIED |\n| D8 | docstring | \"the four transcribed cues\" | :101 | a missing or partial cue list | CARRIED |\n| D9 | docstring | \"instance and media URLs each requested once\" | :102 | a pipeline that also ran on the locked or missing-file attempt | CARRIED |\n| D10 | docstring | withdrawn | n/a | n/a | CARRIED |\n| N1 | name | \"serve waits the back-off\" | :73 | an immediate reclaim by `serve` | CARRIED |\n| N2 | name | \"its next lookup of the same head job\" | :78 | a lookup of d-1 | CARRIED |\n| N3 | name | \"a job requeued on whitelist.db\" | :91 | a failed job or a used-up attempt instead of a requeue | CARRIED |\n| N4 | name | \"claimed again once it is usable\" | :97 | a job that cannot be reclaimed after recovery | CARRIED |\n| N5 | name | \"runs to ready with its queued_at kept\" | :100 | an end state other than ready; a changed `queued_at` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:4\n   D10 was resolved by narrowing the prose, not by adding an assertion. The first-audit sentence \"guards recovery against a back-off that breaks it\" is gone. In its place the docstring now says the test \"drives `run_job` and `claim_translate_job` directly and never runs `serve`, so it checks recovery at those seams only, not past a back-off in `serve`'s loop\". The new sentence matches what :89, :95 and :98 do. Still, nothing in this file asserts that recovery survives the phase-2 back-off inside `serve`. Recorded so the narrowing stays visible.\n2. surfaces (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:95\n   C2 is EXEMPT by the operator's decision. It is still checked at the `run_job`/`claim_translate_job` seam by :97 and :100, so the exemption covers only the claim that it goes red at this checkpoint, not whether it is observable. The part of C2 that is left unproven is \"claimed again\" by `serve` after a back-off. That has an observable at the `serve` seam the first test already drives.\n3. whole-claim (rules/testing.md) \u2014 tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73\n   C1 is worded in terms of claims, but :73 measures the gap between `resolve_video` calls. In `serve` (translate-worker.py:515, :526 \u2192 :427), every claim of v-1 leads straight into one lookup with no step that can be skipped in between. So the lookup gap stands in for the claim gap. This was already noted on the first audit and is unchanged.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. `rig`, `StubRunner`, `_whitelist` and the constants were read from tests/active/test_translate_worker.py:440\u2013550. The `clip` fixture that `rig` depends on, and `Rig.__init__` above line 440 (including how `rig.whitelist` is seeded with v-1 and d-1), were not read.\n2. `data.subtitles` (`claim_translate_job`, `requeue_translate_job`, `enqueue_translate_job`) and `data.db.connect_readonly_db` are outside `code_under_test` and were not read. The claim that a deleted whitelist.db raises \"unable to open\" and that a requeue restores `queued_at` and `attempts` was taken from the worker's docstrings and comments.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"after a `whitelist.db` requeue\", for both a lock and a missing file",
            "assertion": ":80 (parametrized at :55)",
            "excludes": "a failed lookup that fails the job or uses up its attempt instead of requeueing it with the attempt unused",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"the next claim ... no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first\"",
            "assertion": ":73 (with :72 as its ceiling)",
            "excludes": "a `serve` that reclaims right after the requeue (the loop at translate-worker.py:512\u2013527 goes straight back to `claim_translate_job` after `run_job`). The :72 control also excludes a `serve` that ignores the module value and waits the 30 s default. The gap is measured between lookups, not between claims",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"of the same head job\"",
            "assertion": ":78, :80",
            "excludes": "a requeue that loses v-1's place, which would show up as a d-1 lookup; a row that does not end back at `queued_at` 1000",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "once usable, the requeued job is claimed again and runs to `ready` with `queued_at` kept",
            "assertion": ":97, :100",
            "excludes": "not claimable again; a different `queued_at`; an end state other than ready (checked at the `run_job` seam, not through `serve`)",
            "status": "EXEMPT"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"lookup fails every time, either from an injected `database is locked` or from a deleted file\"",
            "assertion": ":80 (parametrized at :55, :60, :63)",
            "excludes": "a missing file treated as a job failure: the row would end `failed`, not `queued`",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"The second lookup comes at least 1.0 s after the first\"",
            "assertion": ":73",
            "excludes": "an immediate re-lookup",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"both are for v-1\"",
            "assertion": ":78",
            "excludes": "a d-1 lookup",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"After a stop the row is back to queued with attempts 0 and queued_at 1000\"",
            "assertion": ":77, :80",
            "excludes": "an attempt used up; a changed `queued_at`; a row read while `serve` is still running",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"a job requeued by `run_job` is first seen queued with attempts 0\"",
            "assertion": ":91",
            "excludes": "a lock or missing file that fails the job, or a requeue that keeps the attempt counted",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"`claim_translate_job` hands back v-1 with attempts 1\"",
            "assertion": ":97",
            "excludes": "a row that cannot be reclaimed; a different head job; an attempts count that keeps growing",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1\"",
            "assertion": ":100",
            "excludes": "a reset `queued_at`; a stale `started_at`; an error left on the row",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"the four transcribed cues\"",
            "assertion": ":101",
            "excludes": "a missing or partial cue list",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"instance and media URLs each requested once\"",
            "assertion": ":102",
            "excludes": "a pipeline that also ran on the locked or missing-file attempt",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"serve waits the back-off\"",
            "assertion": ":73",
            "excludes": "an immediate reclaim by `serve`",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"its next lookup of the same head job\"",
            "assertion": ":78",
            "excludes": "a lookup of d-1",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"a job requeued on whitelist.db\"",
            "assertion": ":91",
            "excludes": "a failed job or a used-up attempt instead of a requeue",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"claimed again once it is usable\"",
            "assertion": ":97",
            "excludes": "a job that cannot be reclaimed after recovery",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"runs to ready with its queued_at kept\"",
            "assertion": ":100",
            "excludes": "an end state other than ready; a changed `queued_at`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test should fail at line 76, `assert max(ages) < FRESH_SECONDS`. In `serve`, the back-off loop at translate-worker.py:530-532 only sleeps and never writes `progress[\"at\"]`. The last write happens at line 515, before the second claim. So across the 0.25 s sampling window the age keeps climbing to about 0.25 s or more, well past the 0.1 s bound. Lines 67-68 and line 77 should pass before then.\n\nNOT ASSESSED\n1. `fixtures_path` was given as \"none found\". The `rig`, `clip` and `StubRunner` fixtures come from tests/active/test_translate_worker.py through a sys.path import at test_path:16-18. I read them there (lines 422-549).\n2. `data.subtitles` (`enqueue_translate_job`, `claim_translate_job`, `requeue_translate_job`) was not in `code_under_test` and I did not read it. The `(\"queued\", 0)` row assertion at test_path:91 depends on how `requeue_translate_job` writes `attempts`. I judged that assertion's shape from the test alone.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (14 clauses: 4 must_prove, 7 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `progress[\"at\"]` \"keeps advancing\" during the back-off | :76, :77 | a back-off wait that never writes `progress` (today's `time.sleep` loop: a 0.25 s-old read). :77 rules out fresh readings that come from a new claim at :515 | CARRIED |\n| C1b | must_prove | \"at least once per slice\" | :76 | a refresh only at the start of the back-off, or every third slice or less often (the read gets older than 0.1 s). It cannot reliably catch a refresh every other slice, or one write with a future time (see Recommendation 1) | CARRIED |\n| C2a | must_prove | a stop during the back-off makes `serve` return \"within about one slice\" | :88 (with :81 as control) | a back-off that ignores `stop` and runs out the ~1.2 s left. The bound is 10 slices, not about one (see Recommendation 2) | CARRIED |\n| C2b | must_prove | \"without claiming again\" | :89, :91 | a claim after the stop, which would make a third lookup through the spy, or would leave the row `running` with attempts 1 if it returned before the lookup | CARRIED |\n| D1 | docstring | \"every lookup fails with the real `unable to open database file` and the job is requeued\" | :68 | a non-transient lookup error that fails the job (row `failed`, never `queued`) | CARRIED |\n| D2 | docstring | \"read every 0.01 s for 0.25 s (five slices) is never more than 0.1 s (two slices) old\" | :76 | a wait leaving `progress` untouched, or refreshing it every third slice or less often | CARRIED |\n| D3 | docstring | \"with still only two lookups, so every read came from the wait and not a fresh claim\" | :77 | a `serve` that spins back into a claim, where :515 refreshes `progress` | CARRIED |\n| D4 | docstring | stop set \"with more than 0.5 s of the back-off left\" | :81 | a stop that lands after the back-off is nearly over, which would make :88 hollow | CARRIED |\n| D5 | docstring | \"ends `serve` within 0.5 s\" | :88 | a thread still alive, or one that took \u22650.5 s after `stop.set()` | CARRIED |\n| D6 | docstring | \"with still only two lookups\" after the stop | :89 | another claim plus lookup after the stop | CARRIED |\n| D7 | docstring | \"the row queued with attempts 0\" | :91 | a claim taken after the stop and left `running`, or a requeue that spends the attempt | CARRIED |\n| N1 | name | \"serve refreshes progress every slice of the back-off\" | :76 | as C1b: no refresh in the wait, or a refresh every third slice or less often | CARRIED |\n| N2 | name | \"a stop during it returns within a slice\" | :88 | a wait that ignores the stop. The bound allows up to 10 slices | CARRIED |\n| N3 | name | \"without another claim\" | :89, :91 | a claim (and lookup) after the stop | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:76\n   `assert max(ages) < FRESH_SECONDS, ages` only puts an upper limit on how old the reads are. It never checks that the value goes up over time. C1 says `progress[\"at\"]` \"keeps advancing at least once per slice\", and some wrong waits still pass this line:\n   - A wait that writes `progress[\"at\"]` once with a future time (for example `resume`) makes every age negative and passes.\n   - A wait that refreshes every other slice peaks at about 0.10 s. Sampling every 0.01 s often misses that peak, so it can also pass. The comment at :26 says such a wait \"would exceed it\".\n   Assert that every age is \u2265 0, and that `progress[\"at\"]` takes several different values that go up over the five sampled slices. Then the \"advancing\" half has its own assertion.\n2. whole-claim / name-as-sentence (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:88, :54\n   The name says \"returns within a slice\" and C2 says \"within about one slice\". `STOP_WITHIN_SECONDS` is 0.5 s, which is ten 0.05 s slices. So a wait that checks `stop` only every few slices passes. The line does rule out a wait that ignores the stop, so C2a and N2 are carried. Either tighten the bound toward one or two slices (the probe measured 0.041 s), or change the name and C2 to say what is actually asserted.\n3. bounds (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:79-82\n   The stop is tested at only one point, somewhere in the middle of the back-off. Two edges of the sliced wait are not tested:\n   - a stop set during the last, shorter slice (where `min(POLL_SECONDS, resume - now)` is less than one slice);\n   - a stop set right as the back-off starts, before the first slice.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The `rig` and `clip` fixtures and `StubRunner` came from tests/active/test_translate_worker.py, lines 420-550; I did not read the rest of that file.\n2. I did not read `data.subtitles` (`claim_translate_job`, `requeue_translate_job`). For D7/C2b, I took \"attempts 0 after requeue\" from the worker's comments in `run_job` (translate-worker.py:477) and from the docstring. I did not check it against the store code.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test should fail at line 76, `assert max(ages) < FRESH_SECONDS`. In `serve`, the back-off loop at translate-worker.py:530-532 only sleeps and never writes `progress[\"at\"]`. The last write happens at line 515, before the second claim. So across the 0.25 s sampling window the age keeps climbing to about 0.25 s or more, well past the 0.1 s bound. Lines 67-68 and line 77 should pass before then.\n\nNOT ASSESSED\n1. `fixtures_path` was given as \"none found\". The `rig`, `clip` and `StubRunner` fixtures come from tests/active/test_translate_worker.py through a sys.path import at test_path:16-18. I read them there (lines 422-549).\n2. `data.subtitles` (`enqueue_translate_job`, `claim_translate_job`, `requeue_translate_job`) was not in `code_under_test` and I did not read it. The `(\"queued\", 0)` row assertion at test_path:91 depends on how `requeue_translate_job` writes `attempts`. I judged that assertion's shape from the test alone.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (14 clauses: 4 must_prove, 7 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `progress[\"at\"]` \"keeps advancing\" during the back-off | :76, :77 | a back-off wait that never writes `progress` (today's `time.sleep` loop: a 0.25 s-old read). :77 rules out fresh readings that come from a new claim at :515 | CARRIED |\n| C1b | must_prove | \"at least once per slice\" | :76 | a refresh only at the start of the back-off, or every third slice or less often (the read gets older than 0.1 s). It cannot reliably catch a refresh every other slice, or one write with a future time (see Recommendation 1) | CARRIED |\n| C2a | must_prove | a stop during the back-off makes `serve` return \"within about one slice\" | :88 (with :81 as control) | a back-off that ignores `stop` and runs out the ~1.2 s left. The bound is 10 slices, not about one (see Recommendation 2) | CARRIED |\n| C2b | must_prove | \"without claiming again\" | :89, :91 | a claim after the stop, which would make a third lookup through the spy, or would leave the row `running` with attempts 1 if it returned before the lookup | CARRIED |\n| D1 | docstring | \"every lookup fails with the real `unable to open database file` and the job is requeued\" | :68 | a non-transient lookup error that fails the job (row `failed`, never `queued`) | CARRIED |\n| D2 | docstring | \"read every 0.01 s for 0.25 s (five slices) is never more than 0.1 s (two slices) old\" | :76 | a wait leaving `progress` untouched, or refreshing it every third slice or less often | CARRIED |\n| D3 | docstring | \"with still only two lookups, so every read came from the wait and not a fresh claim\" | :77 | a `serve` that spins back into a claim, where :515 refreshes `progress` | CARRIED |\n| D4 | docstring | stop set \"with more than 0.5 s of the back-off left\" | :81 | a stop that lands after the back-off is nearly over, which would make :88 hollow | CARRIED |\n| D5 | docstring | \"ends `serve` within 0.5 s\" | :88 | a thread still alive, or one that took \u22650.5 s after `stop.set()` | CARRIED |\n| D6 | docstring | \"with still only two lookups\" after the stop | :89 | another claim plus lookup after the stop | CARRIED |\n| D7 | docstring | \"the row queued with attempts 0\" | :91 | a claim taken after the stop and left `running`, or a requeue that spends the attempt | CARRIED |\n| N1 | name | \"serve refreshes progress every slice of the back-off\" | :76 | as C1b: no refresh in the wait, or a refresh every third slice or less often | CARRIED |\n| N2 | name | \"a stop during it returns within a slice\" | :88 | a wait that ignores the stop. The bound allows up to 10 slices | CARRIED |\n| N3 | name | \"without another claim\" | :89, :91 | a claim (and lookup) after the stop | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:76\n   `assert max(ages) < FRESH_SECONDS, ages` only puts an upper limit on how old the reads are. It never checks that the value goes up over time. C1 says `progress[\"at\"]` \"keeps advancing at least once per slice\", and some wrong waits still pass this line:\n   - A wait that writes `progress[\"at\"]` once with a future time (for example `resume`) makes every age negative and passes.\n   - A wait that refreshes every other slice peaks at about 0.10 s. Sampling every 0.01 s often misses that peak, so it can also pass. The comment at :26 says such a wait \"would exceed it\".\n   Assert that every age is \u2265 0, and that `progress[\"at\"]` takes several different values that go up over the five sampled slices. Then the \"advancing\" half has its own assertion.\n2. whole-claim / name-as-sentence (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:88, :54\n   The name says \"returns within a slice\" and C2 says \"within about one slice\". `STOP_WITHIN_SECONDS` is 0.5 s, which is ten 0.05 s slices. So a wait that checks `stop` only every few slices passes. The line does rule out a wait that ignores the stop, so C2a and N2 are carried. Either tighten the bound toward one or two slices (the probe measured 0.041 s), or change the name and C2 to say what is actually asserted.\n3. bounds (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:79-82\n   The stop is tested at only one point, somewhere in the middle of the back-off. Two edges of the sliced wait are not tested:\n   - a stop set during the last, shorter slice (where `min(POLL_SECONDS, resume - now)` is less than one slice);\n   - a stop set right as the back-off starts, before the first slice.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The `rig` and `clip` fixtures and `StubRunner` came from tests/active/test_translate_worker.py, lines 420-550; I did not read the rest of that file.\n2. I did not read `data.subtitles` (`claim_translate_job`, `requeue_translate_job`). For D7/C2b, I took \"attempts 0 after requeue\" from the worker's comments in `run_job` (translate-worker.py:477) and from the docstring. I did not check it against the store code.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`progress[\"at\"]` \"keeps advancing\" during the back-off",
            "assertion": ":76, :77",
            "excludes": "a back-off wait that never writes `progress` (today's `time.sleep` loop: a 0.25 s-old read). :77 rules out fresh readings that come from a new claim at :515",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"at least once per slice\"",
            "assertion": ":76",
            "excludes": "a refresh only at the start of the back-off, or every third slice or less often (the read gets older than 0.1 s). It cannot reliably catch a refresh every other slice, or one write with a future time (see Recommendation 1)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a stop during the back-off makes `serve` return \"within about one slice\"",
            "assertion": ":88 (with :81 as control)",
            "excludes": "a back-off that ignores `stop` and runs out the ~1.2 s left. The bound is 10 slices, not about one (see Recommendation 2)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"without claiming again\"",
            "assertion": ":89, :91",
            "excludes": "a claim after the stop, which would make a third lookup through the spy, or would leave the row `running` with attempts 1 if it returned before the lookup",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"every lookup fails with the real `unable to open database file` and the job is requeued\"",
            "assertion": ":68",
            "excludes": "a non-transient lookup error that fails the job (row `failed`, never `queued`)",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"read every 0.01 s for 0.25 s (five slices) is never more than 0.1 s (two slices) old\"",
            "assertion": ":76",
            "excludes": "a wait leaving `progress` untouched, or refreshing it every third slice or less often",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"with still only two lookups, so every read came from the wait and not a fresh claim\"",
            "assertion": ":77",
            "excludes": "a `serve` that spins back into a claim, where :515 refreshes `progress`",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "stop set \"with more than 0.5 s of the back-off left\"",
            "assertion": ":81",
            "excludes": "a stop that lands after the back-off is nearly over, which would make :88 hollow",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"ends `serve` within 0.5 s\"",
            "assertion": ":88",
            "excludes": "a thread still alive, or one that took \u22650.5 s after `stop.set()`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"with still only two lookups\" after the stop",
            "assertion": ":89",
            "excludes": "another claim plus lookup after the stop",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the row queued with attempts 0\"",
            "assertion": ":91",
            "excludes": "a claim taken after the stop and left `running`, or a requeue that spends the attempt",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"serve refreshes progress every slice of the back-off\"",
            "assertion": ":76",
            "excludes": "as C1b: no refresh in the wait, or a refresh every third slice or less often",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"a stop during it returns within a slice\"",
            "assertion": ":88",
            "excludes": "a wait that ignores the stop. The bound allows up to 10 slices",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"without another claim\"",
            "assertion": ":89, :91",
            "excludes": "a claim (and lookup) after the stop",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nnone. I made no edits. I checked engine/server/db/jobs/translate-worker.py and the three phases are already in their smallest form. WhitelistBusy is one exception class next to its siblings. The transient check is written inline in generate's only resolve_video call, because it has a single caller. run_job has one new branch and returns a bool. serve has one back-off loop that refreshes progress in each slice. TRANSIENT_BACKOFF_SECONDS is the only new constant. The docstrings for generate, run_job and serve already describe the new behaviour.\n</refactors>\n\n<left_out>\n1. I did not merge the JobStopped and WhitelistBusy branches in run_job, although both call requeue_translate_job. They log at different levels and with different text, and only the WhitelistBusy branch returns True. A shared helper would add code to save one line. 2. I did not pull serve's back-off loop out into a helper. It has one caller, and a helper would add an indirection without making the code shorter. 3. I did not add the requeue to the module docstring's run_job sentence. The run_job docstring already states it, and that docstring is where readers look. 4. Probe and phase-checkpoint files from phases 1\u20133 are still in tests/tmp/ (probe_45_phase1_scenarios.py, probe_45_phase2_serve.py, probe_45_phase3_backoff.py, probe_45_whitelist_locked_at_claim.py, test_45_translate_worker_whitelist_locked_at_phase{1,2,3}.py). They are outside the files I was given for this step, and the phase tests are gated checkpoints, so I did not delete or edit them. Whoever owns the build's cleanup should decide what happens to them.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nI matched the shipped translate-worker.py against the inlined source with a Grep on the phase symbols, and the code is the same. run_job's only production caller is serve, so the bool return has no other caller to update. The pass found nothing to cut without changing behaviour or adding indirection.\n</observation>",
  "harvest_plan": {
    "harvest_file": "docs/project/plans/harvest-45-translate-worker-whitelist-locked-at-plan.md",
    "plan": "Harvest plan for issue 45, translate-worker whitelist.db locked at claim (scope: the three `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase{1,2,3}.py` files; bootstrap gate clear; record snapshot taken at `tests/last_test_validation.json.preharvest`).\n\nCounts per verdict: DURABLE 4, REPLACES 0, COMBINE 0, REDUNDANT 2, SPENT 0 (6 test functions).\n\nDURABLE, all to `tests/active/test_translate_worker.py`:\n- `test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true` (phase 1; parametrized missing file / held EXCLUSIVE lock). No active test covers the WhitelistBusy requeue.\n- `test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false` (phase 1; parametrized videos without video_uuid / zero-byte file). It bounds the transient predicate from the other side.\n- `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` (phase 2; parametrized injected lock / missing file). No active test drives `serve` in-process or asserts `TRANSIENT_BACKOFF_SECONDS`.\n- `test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim` (phase 3). Covers heartbeat liveness and stop during the back-off; uncovered anywhere else.\n\nREDUNDANT (stay out):\n- `test_control_an_intact_whitelist_reaches_both_hosts` (phase 1). The active transcribed-job test already asserts ready plus `INSTANCE_THEN_JSON` / `[MEDIA_URL]` on the same rig.\n- `test_a_job_requeued_on_whitelist_db_claimed_again_once_it_is_usable_runs_to_ready_with_its_queued_at_kept` (phase 2). Every link is already asserted: the requeued row tuple by the phase 1 DURABLE test, the claim of a queued row by `test_subtitles.py::test_claim_hands_out_queued_jobs_oldest_first_\u2026`, and a claimed v-1 running to ready by the transcribed-job test. It was green before its own phase.\n\nActive tests retired: none.\n\n`test_groups` changes: none. The `test_translate_worker.py` entry already claims `engine/server/db/jobs/translate-worker.py` and `engine/server/data/subtitles.py`.\n\nNew subject files: none. The subject exists and is not split.\n\nHow Step 5 lands them:\n- `Rig.run` gains `return`, so it hands back `run_job`'s bool. This reuses the rig rather than carrying phase 1's `_run_job` copy.\n- Phase 2 and phase 3 each have a `_recording` helper with the same name and different signatures. They merge into one helper that records `(time, video_id, host)` with optional `locked_calls`, and there is a single `_until`.\n- The back-off constants that differ (1.0 s vs 1.5 s) get distinct names.\n- Docstrings are rewritten to state the rule instead of \"Issue 45, phase N\", and the module docstring gains the transient-whitelist and back-off rules.\n- The held-EXCLUSIVE-lock case costs about 30 s (busy timeout).\n\nNothing moved; this turn stopped at Step 4."
  },
  "build_diff": {
    "path": ".scratch/45-translate-worker-whitelist-locked-at/build.diff",
    "files": [
      "docs/project/plans/harvest-45-translate-worker-whitelist-locked-at-plan.md",
      "engine/server/db/jobs/translate-worker.py",
      "tests/last_test_output.txt",
      "tests/last_test_validation.json",
      "tests/last_test_validation.json.preharvest",
      "tests/tmp/probe_45_phase1_scenarios.py",
      "tests/tmp/probe_45_phase2_serve.py",
      "tests/tmp/probe_45_phase3_backoff.py",
      "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py",
      "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py",
      "tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py"
    ],
    "withheld": 0,
    "end": "82be9aa6b3395a1041f4af288544f8a706870f30",
    "moved_to": "delete_me/45-translate-worker-whitelist-locked-at.build.diff"
  },
  "harvest_report": "<moved>\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py::test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true (missing file, held EXCLUSIVE lock) -> tests/active/test_translate_worker.py, group test_translate_worker.py\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py::test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false (videos without video_uuid, zero-byte file) -> tests/active/test_translate_worker.py, group test_translate_worker.py\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py::test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job (injected lock, missing file) -> tests/active/test_translate_worker.py, group test_translate_worker.py\ntests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py::test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim -> tests/active/test_translate_worker.py, group test_translate_worker.py\nHow they landed: `Rig.run` now returns `run_job`'s bool, so phase 1's `_run_job` copy is not carried. One merged `_recording(resolve, locked_calls=0)` records (time, video_id, host), and there is a single `_until`. The two back-offs are separate constants, GAP_BACKOFF_SECONDS = 1.0 and LIVE_BACKOFF_SECONDS = 1.5. There is one LOOKUP_WAIT_SECONDS = 15 s, which is still under the 30 s default. The phase 1 `_job` helper is renamed `_job_tuple` so it doesn't clash with the existing `_jobs`. The docstrings now state the rules, and the module docstring has new \"Whitelist at claim\" and \"Back-off\" paragraphs.\nNot moved (REDUNDANT, per the plan): test_control_an_intact_whitelist_reaches_both_hosts and test_a_job_requeued_on_whitelist_db_claimed_again_once_it_is_usable_runs_to_ready_with_its_queued_at_kept.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\nnone. The `test_translate_worker.py` entry already claims engine/server/db/jobs/translate-worker.py and engine/server/data/subtitles.py. `--audit-map` exits 0 before and after the harvest, and the moved tests add no findings: the group's findings are the same advisory MISSING (subtitles.db, translate-worker.lock) and UNRESOLVABLE (whitelist.db) entries as before.\n</group_map>\n\n<mutations>\nM1 engine/server/db/jobs/translate-worker.py generate: transient words emptied (`for word in ()`) -> test_a_locked_or_unopenable_whitelist_at_claim_\u2026 RED in both cases at `_job_tuple(rig) == (\"queued\", 0, QUEUED_AT, None, None)`, which got ('failed', 1, \u2026); restored with cp, diff clean, GREEN (2 passed)\nM2 engine/server/db/jobs/translate-worker.py generate: \"no such\" added to the transient words -> test_any_other_whitelist_error_at_claim_\u2026 RED in both cases at `(row[\"state\"], row[\"error\"]) == (\"failed\", \"OperationalError: \u2026\")`, which got ('queued', None); restored with cp, diff clean, GREEN (2 passed)\nM3 engine/server/db/jobs/translate-worker.py serve: `if run_job(...) and False:`, so serve ignores the requeue bool -> test_serve_waits_the_back_off_\u2026 RED in both cases at `lookups.calls[1][0] - lookups.calls[0][0] >= GAP_BACKOFF_SECONDS`, a gap of about 0.0002 s; restored with cp, diff clean, GREEN (2 passed)\nM4 engine/server/db/jobs/translate-worker.py serve back-off loop: `progress[\"at\"] = time.monotonic()` replaced by `pass` -> test_serve_refreshes_progress_\u2026 RED at `max(ages) < FRESH_SECONDS`, with an oldest read of 0.2495 s against the 0.1 s bound; restored with cp, diff clean, GREEN (1 passed)\nNone survived and none hung. Each .bak was moved to delete_me/translate-worker.py.bak.m1 to .m4, and there is no .bak left under engine/, client/ or scripts/.\n</mutations>\n\n<cleared>\ndelete_me/ now holds the three in-scope files: test_45_translate_worker_whitelist_locked_at_phase1.py, test_45_translate_worker_whitelist_locked_at_phase2.py and test_45_translate_worker_whitelist_locked_at_phase3.py. It also holds the four restored mutation backups, translate-worker.py.bak.m1 to .m4. The 45-translate-worker-whitelist-locked-at.build.diff that was already there is untouched. tests/tmp no longer holds any test_45_* file. The probe_*.py files there were outside the scope and were left in place. Final counts: I restored the pre-harvest snapshot over the record, then ran `--compare` with no tier named. It ran 5 changed or unmapped groups and carried 58 forward unchanged by digest: 137 passed and 0 failed, with test_translate_worker.py at 56 passed (49 before plus 7 new). Seven results appeared, all from the four harvested tests (2 + 2 + 2 + 1), and none departed. There was no new red and nothing stopped being red. The record is banked (exit 0), and HARVEST_FILE records Steps 5 to 8. Nothing has been deleted: the files in delete_me/ are waiting for the user to remove them.\n</cleared>"
}
```
dev-flow:state -->

## 2026-10-03 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Start snapshot: tree `aed68720d3bd15c60a441688639f53fc47cd4519` at 2026-10-03T23:20:24-04:00.

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 63 test groups (62 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.0s
  ---------------------
  total                  10 passed                              2.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Purpose

Fix issue `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md` (category bug, ready-for-agent). The translate worker (`engine/server/db/jobs/translate-worker.py`) re-checks every claimed job against the Engine's `whitelist.db` before doing any remote work. If that file is locked past the 30 s busy timeout, or cannot be opened (for example mid-restore), the job ends `failed` today. `failed` is terminal, and enqueue refuses a key in any state, so that video can never be queued again from the CLI or from plan 50's page route. The updater's merge holds a write lock on `whitelist.db` long enough for this to happen in normal operation. After this build such a condition is temporary for the job: it goes back to the queue unspent, the worker backs off, and the job runs once the file is usable again. Real errors still fail the job as today.

### Current behaviour (verified in the tree)

- `resolve_video(whitelist_path, video_id, host, max_duration)` (`translate-worker.py:93-110`) opens `whitelist.db` with `connect_readonly_db` (`engine/server/data/db.py:85`: URI `mode=ro`, so a missing file raises `sqlite3.OperationalError: unable to open database file`). It sets `PRAGMA busy_timeout = 30000` and calls `fetch_video_row` and `list_active_denied_hosts`. It returns `(row, None)` or `(None, refusal_text)`, or raises `sqlite3.Error`. `command_enqueue` (`:113`) also calls it and is out of scope.
- `generate` (`:420`) calls `resolve_video(args.whitelist_db, *claim[:2], args.max_duration)` first, at `:422`. A refusal raises `JobFailed`.
- `run_job` (`:455-474`) handles `JobStopped` with `requeue_translate_job(conn, *claim)` and an info log, `JobTakenOver` with an info log, and `JobFailed` with `finish_translate_failed`. A catch-all `except Exception` (`:469`) unloads the model on CUDA OOM, logs with a traceback and writes `failed` with `f"{type(exc).__name__}: {exc}"`. A locked or missing `whitelist.db` lands in this catch-all today.
- `requeue_translate_job(conn, video_id, instance_domain, target_language, started_at) -> bool` (`engine/server/data/subtitles.py:161`) is a conditional update on the running row with that `started_at`: `state = 'queued', attempts = attempts - 1`, and `queued_at` is untouched. It returns False when B1's route took the row over. `claim_translate_job` (`:130`) picks the oldest queued row by `queued_at, rowid`, sets `running`, sets `started_at` and increments `attempts`. `recover_translate_jobs` (`:141`) fails a row found `running` at start with `attempts >= MAX_CLAIMS` (2).
- `serve` (`translate-worker.py:493-511`) loops while `not stop.is_set()`: it sets `progress["at"] = time.monotonic()`, claims, and when idle sleeps `POLL_SECONDS` (2.0) with `time.sleep`. It deliberately does not use `stop.wait`: the SIGTERM handler sets `stop` on the main thread, and `Event.set` deadlocks if it lands while that thread holds the event's lock inside `wait` (comment at `:506`). It calls `run_job` and resets `idle_since`.
- `heartbeat_loop` (`:477`) beats every `HEARTBEAT_SECONDS` (5 s) on its own thread unless `progress["at"]` is older than `STALL_SECONDS` (600 s).
- Docs: `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` has a Known Gaps bullet at line 154 (locked `whitelist.db` fails the job permanently, no requeue or back-off). Error Texts line 137 lists "a locked `whitelist.db`" under `<ExceptionType>: <text>`. The Serve Loop section (line 79), the Stop/Crash section (line 141) and the Logs list (lines 159-168) do not mention a transient requeue. `DEPLOYMENT.md:353` is a triage row: "A job ends `failed` with `OperationalError: database is locked`, or `enqueue` prints `error: whitelist.db: database is locked`" … "The job is not requeued and nothing backs off: the key stays `failed`" … "Re-queue the key … after the updater run ends".
- Existing tests: `tests/active/test_translate_worker.py`. Its job-pipeline rig calls `run_job` in-process over a tmp `whitelist.db` and a tmp `subtitles.db`, with a job enqueued and claimed by the store's own functions (queued_at 1000, started_at 2000). There is an existing stop-requeue test, `test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept`, and subprocess `run` tests for heartbeat and SIGTERM. The triage probe `tests/tmp/probe_45_whitelist_locked_at_claim.py` reproduced the bug in 30.4 s using a rollback-journal whitelist fixture and `BEGIN EXCLUSIVE`.

### R1: Classify transient errors at the claim-time whitelist check

- Only the claim-time call to `resolve_video` inside the worker's job path is affected. An `sqlite3.OperationalError` raised by it is transient when its text, compared case-insensitively, contains `locked`, `busy` or `unable to open`.
- The transient set is exactly these three (operator decision). Every other error still fails the job permanently through today's path, with today's text (`<ExceptionType>: <text>`). That includes `no such column`, `no such table` (for example a zero-byte file), `file is not a database` and `database disk image is malformed`.
- The plan 49 draft used a `WhitelistBusy` exception and an `is_transient_db_error` predicate. Those names are suggestions, not requirements. `db.py` already has a precedent for the text-matching shape in `is_interrupted_error`.
- `command_enqueue`'s handling of the same errors is unchanged: it reports and exits 1.

### R2: Requeue without spending the claim

- A transient error requeues the job through the existing `requeue_translate_job(conn, *claim)`, the function the SIGTERM path uses. No second requeue function is added.
- After the requeue: `state` is `queued`, `attempts` equals its value before the claim, and `queued_at` is unchanged, so the job stays at the head of the queue. No `error` or `finished_at` is written, and the row is never written `failed` for a transient error.
- A transient requeue never counts toward the crash-retry limit (`MAX_CLAIMS`), because the attempt is given back.
- It is logged at warning level with the key (video_id, host) and the error text, prefixed `[translate-worker]` like every other worker line. It does not use `logging.exception`.
- The CUDA-OOM model unload is not triggered by this path.
- If `requeue_translate_job` returns False (B1 took the row over), nothing more is written for that job, as for the other conditional writes.

### R3: Back off before the next claim

- After a transient requeue, `serve` waits a back-off of about 30 s (a named module constant, for example `TRANSIENT_BACKOFF_SECONDS = 30.0`) before its next claim, instead of reclaiming at once.
- `run_job` must tell `serve` that a back-off is due. The mechanism is the designer's choice.
- The wait must not block the heartbeat. It keeps `progress["at"]` fresh at least as often as the idle poll does (every `POLL_SECONDS`), so the heartbeat thread keeps beating.
- A stop request (SIGTERM or SIGINT setting `stop`) ends the wait promptly, within about one `POLL_SECONDS` slice, and the worker exits normally.
- The wait must keep the existing rule that the main thread uses `time.sleep`, not `stop.wait`, for the reason in the comment at `serve` (`translate-worker.py:506`). For example, it can sleep in `POLL_SECONDS` slices and check `stop` between them.
- The requeue and back-off repeat for as long as the condition lasts. Each cycle reclaims the same head-of-queue job. A whole cycle under a held lock is roughly the 30 s busy wait plus the 30 s back-off; with a missing file it is immediate failure plus the 30 s back-off.

### R4: Recovery once the cause clears

- Once the lock is released or the file restored, the requeued job is claimed on the next pass after the back-off and runs to a normal end state (`ready`, `already_english`, or a non-transient `failed`), exactly as an unaffected job would.

### R5: Documentation

- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`:
  - Remove the first Known Gaps bullet (locked `whitelist.db`), keeping the second (faster-whisper and VRAM).
  - In Error Texts, drop "and a locked `whitelist.db`" from the `<ExceptionType>: <text>` line.
  - Describe the requeue and back-off as current behaviour, in the Serve Loop and Job Pipeline step 1 and/or Stop, Crash and Recovery, wherever it reads naturally. Cover what is transient (locked, busy, unable to open, for example during the updater merge or a restore), that the job goes back to `queued` with `attempts` restored and `queued_at` kept, the about 30 s back-off that a stop ends promptly, that it repeats until the file is usable, and that other database errors still fail the job.
  - Add the new warning log line to Logs.
- `DEPLOYMENT.md` triage row at line 353: it must no longer say a locked `whitelist.db` fails the job or that the key stays `failed`. It should describe the requeue and back-off (the job stays `queued` and runs once the updater merge or restore ends, with the warning line in the journal). The `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) stays, because enqueue is out of scope.
- Write as current state, with no "previously" history. One paragraph per line, with no softwrap.

### R6: Tests

New gating tests go in `tests/active/test_translate_worker.py`, reusing its rig (tmp `whitelist.db` and `subtitles.db`, job enqueued and claimed by the store's functions):
- An exclusive lock (`BEGIN EXCLUSIVE`) is held on a rollback-journal `whitelist.db` throughout the check. The claimed job ends `queued` with `attempts` and `queued_at` as before the claim, not `failed`. Because of the real 30 s busy timeout, the test may instead inject `sqlite3.OperationalError("database is locked")` from `resolve_video` at claim. At least the injected form must be covered, and one real-lock case is preferred if its runtime is acceptable.
- `whitelist.db` is absent at claim time (a real missing path, giving `unable to open database file`). Same outcome.
- The next claim after a transient requeue happens no sooner than the back-off. A stop set during the back-off makes `serve` return promptly. The heartbeat progress stays fresh during the wait.
- Control: a non-transient `sqlite3.OperationalError` such as `no such column` at claim still ends the job `failed` with its text (`OperationalError: no such column…`).
- Once the lock is released or the file restored, the requeued job is claimed and runs to a normal end state.
- A warning-level log line naming the key and the error text is emitted on a transient requeue.
- The existing translate worker and subtitles store tests still pass.

### Out of scope

- Re-queuing keys already `failed`, including ones failed by this bug before the fix.
- Transient handling for the `enqueue` command (it reports a database error and exits 1) or for remote fetch failures.
- Changing the 30 s busy timeout, `MAX_CLAIMS`, or the queue cap.
- `subtitles.db` locking (its own busy timeout and tests).
- Treating corrupt or partial files (`file is not a database`, `malformed`, `no such table`) as transient.

### Accepted limits

- sqlite's own 30 s busy wait inside `resolve_video` cannot be interrupted, so a stop that arrives during that wait, as opposed to during the back-off, still takes up to about 30 s to take effect. The busy timeout is not changed.
- While `whitelist.db` stays locked or missing, the head job is reclaimed every cycle and later queued jobs wait behind it. Every job needs the same file, so they could not run anyway.

### Baseline suite state

Pre-build baseline: exit code 0, variant false (the suite is green before the build).

### conflicts

DEPLOYMENT.md:353 combines the job case (in scope: must now describe the requeue and back-off) with the `enqueue` case `error: whitelist.db: database is locked` (out of scope: unchanged). The brief says to "remove the triage row", but the row must instead be rewritten so that its enqueue half survives.
The brief's AC "a stop during the back-off makes the worker exit promptly" sits alongside the out-of-scope "do not change the 30 s busy timeout". A stop during sqlite's busy wait itself is therefore still not prompt (up to 30 s). The operator accepted this as a limit.

## 2026-10-03 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

The change is confined to `engine/server/db/jobs/translate-worker.py`, its two docs and its test file. `db.py` and `subtitles.py` are not touched. The steps below are in the order the code runs.

1. **Classify the error at the claim-time check (R1).** A small module-level predicate in the worker, named for example `is_transient_db_error`, follows the shape of `is_interrupted_error` in `db.py`. It takes the `sqlite3.OperationalError` text, lowercases it, and returns True if it contains `locked`, `busy` or `unable to open`. Nothing else counts. A new exception class, `WhitelistBusy`, sits next to `JobStopped` and `JobTakenOver` and carries the error text.

2. **Raise it only from the job path.** In `generate`, only the `resolve_video` call at line 422 gets a narrow guard. If an `OperationalError` from that call passes the predicate, it is raised again as `WhitelistBusy` chained from the original. Otherwise the original exception is re-raised unchanged, so it still reaches `run_job`'s catch-all and ends `failed` with exactly today's text (`OperationalError: no such column…`, `no such table`, `file is not a database`, `malformed`). `resolve_video` itself is unchanged, so `command_enqueue` still reports and exits 1.

3. **Requeue without spending the claim (R2).** `run_job` gets a new `except WhitelistBusy` branch, placed before the catch-all so the CUDA-OOM unload and `logging.exception` are never reached. The branch:
   - calls the existing `requeue_translate_job(conn, *claim)`, the function the stop path already uses, which sets `queued`, gives back the attempt and leaves `queued_at` alone;
   - writes no `error` and no `finished_at`;
   - logs one `logging.warning` line: `[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s` with the error text.

   If the requeue returns False (B1's route took the row over), nothing more is written; the log line still goes out. Because the attempt is given back, `MAX_CLAIMS` crash recovery never counts these requeues.

4. **Tell `serve` to back off (R3).** `run_job` currently returns None. It will return a boolean that is True only from the `WhitelistBusy` branch, and `serve` reads it. When it is True, `serve` runs a back-off loop before its next claim:
   - a deadline of `TRANSIENT_BACKOFF_SECONDS = 30.0`, a new module constant next to `POLL_SECONDS`;
   - a loop that runs while `stop` is unset and the deadline has not passed. Each pass refreshes `progress["at"]` and calls `time.sleep(min(POLL_SECONDS, remaining))`.

   This keeps the `time.sleep`-not-`stop.wait` rule from the line 506 comment and refreshes progress at least as often as the idle poll, so the heartbeat thread keeps beating. A stop ends the wait within one slice, after which the outer `while not stop.is_set()` exits normally. The loop reads the module globals at call time, so tests can shorten both constants.

5. **Repeat until the file is usable, then recover (R3, R4).** The job keeps its `queued_at`, so the next claim takes the same job again. Each cycle repeats on its own for as long as the cause lasts. Once the lock is released or the file restored, `resolve_video` succeeds and the job runs exactly like any other job.

6. **Documentation (R5).** In `TRANSLATE_WORKER.md`:
   - delete the first Known Gaps bullet;
   - drop "and a locked `whitelist.db`" from the Error Texts line;
   - add a paragraph to Job Pipeline step 1, with a one-line reference in Serve Loop for the back-off, covering:
     - what counts as transient: locked, busy, unable to open (updater merge, restore);
     - the job returns to `queued` with `attempts` restored and `queued_at` kept;
     - the about 30 s back-off, which a stop ends promptly;
     - the cycle repeats until the file is usable;
     - every other database error still fails the job;
   - add the warning line to Logs.

   In `DEPLOYMENT.md:353`, rewrite the job half of the row: the job stays `queued`, the journal shows the warning line, and the job runs on its own once the merge or restore ends. The `enqueue` half stays as it is. Everything is written as current state, one paragraph per line.

7. **Tests (R6).** All new tests go in `tests/active/test_translate_worker.py`, reusing `Rig`.
   - Injected `sqlite3.OperationalError("database is locked")` from a patched `resolve_video`: the row ends `queued`, `attempts` 0, `queued_at` `QUEUED_AT`, with no `error` or `finished_at`. The test also checks the warning-level log record (via `caplog`) names the key and the text, and that `run_job` returns True.
   - Real missing file: `rig.whitelist` is deleted before the run. Same outcome.
   - Real lock: `BEGIN EXCLUSIVE` is held on the rig's rollback-journal whitelist, then released. Same outcome, about 30 s of runtime (see Tradeoffs).
   - Control: an injected `no such column` ends `failed` with `OperationalError: no such column…`, and `run_job` returns falsy.
   - Recovery: after a transient requeue, the lock is released or the file rewritten, the job is claimed again through `claim_translate_job` (attempts back to 1) and `run_job` ends `ready`.
   - Serve-level test, in-process on a thread, with `POLL_SECONDS` and `TRANSIENT_BACKOFF_SECONDS` shortened on the loaded module, a stub runner, and `resolve_video` patched to raise transiently and record call times:
     - the second claim comes no sooner than the back-off after the first;
     - `progress["at"]` keeps advancing during the wait;
     - a `stop` set mid-back-off makes `serve` return within about one slice.

     Setting `stop` from the test thread is safe here; the deadlock the line 506 comment describes needs a signal handler running on the main thread.

   The existing stall test holds `BEGIN EXCLUSIVE` for about 16 s, below the 30 s busy timeout, so its job still ends `not in whitelist` and it is unaffected.

### Alternatives considered

- **Return value from `run_job` vs other signals.**
  - A flag in the shared `progress` dict would mix the stall clock with control flow.
  - Letting `WhitelistBusy` propagate up to `serve` would split one job's handling across two functions and bypass `run_job`'s "exactly one end state" contract.
  - A return value is the smallest signal and is local to the one caller.
- **Guard in `generate` vs inside `resolve_video`.** Classifying inside `resolve_video` would also change `command_enqueue`, which is out of scope. Classifying in `run_job`'s catch-all by inspecting any `OperationalError` would also catch transient `subtitles.db` errors from later steps, which is also out of scope. A guard around the one claim-time call is the only place that matches R1 exactly.
- **Predicate in `db.py` vs in the worker.** `db.py` holds the precedent. But there is a single caller, and the three substrings are an operator decision about this worker's policy, not a general database fact. Keeping the predicate in the worker touches one fewer file. It can move into `db.py` if a second caller appears.
- **A new exception vs catching `OperationalError` in `run_job`.** A dedicated exception keeps the classification at the call site that is in scope. It also lets `run_job` list it alongside `JobStopped` and `JobTakenOver` in the same style.
- **Making the busy timeout a constant so a real-lock test runs fast.** Rejected for now. It would be a refactor made only for the test, and the value must stay 30 s anyway. If the 30 s test proves too slow, this is the upgrade path.

### Risks, gotchas and limitations

- **Substring matching depends on sqlite's wording.** `unable to open` also covers `unable to open database file` caused by a permissions problem or a missing directory. Those would also requeue and back off forever, which is the operator's chosen set. The repeating warning line in the journal is how an operator spots it.
- **Accepted limit:** a stop that arrives during sqlite's own 30 s busy wait still takes up to about 30 s to take effect.
- **Accepted limit:** while the head job is blocked, the jobs behind it wait.
- **Unplanned limit: idle unload is skipped.** `serve` resets `idle_since` after every `run_job`, and the idle-unload check only runs when nothing is claimed. So a model already loaded by an earlier job stays in VRAM for as long as the lock or missing file lasts. I left this unhandled to keep the change small. The cheap fix is to skip the `idle_since` reset on a transient requeue and run the same unload check in the back-off loop.
- **Log volume.** Under a lock held long-term, the warning repeats about once a minute (30 s busy wait plus 30 s back-off). Under a missing file it repeats about every 30 s. This is intentional, so the condition shows in the journal.
- **Test patching.** Shortening the constants only works because the back-off loop reads module globals at call time, so the design must not bind them as default arguments.

### Tradeoffs the operator is accepting

- One real-lock test adds about 30 s to the suite, about the same as the triage probe. The injected-lock and missing-file tests cover the same branch in milliseconds. If 30 s is too much, the real-lock test can be dropped (R6 allows the injected form alone) or the timeout constant can be hoisted.
- A permanently unreadable `whitelist.db` (a missing file or a permissions error) never fails the job. It requeues forever and shows only in the warning log, because the repeat is not capped (R3 asks for that).
- A loaded model stays resident through a prolonged lock (see the unplanned limit above), unless the operator wants the small idle-unload addition.

### conflicts

none

## 2026-10-03 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impacts>
<impact path="engine/server/db/jobs/translate-worker.py" element="new module-level predicate is_transient_db_error (name per plan)">
**What changes:** a new function returns True when the lowercased `sqlite3.OperationalError` text contains `locked`, `busy` or `unable to open`. The plan models it on `is_interrupted_error` in `engine/server/data/db.py:68`. The closer match inside this file is `is_cuda_oom` (`translate-worker.py:351-353`): a one-line docstring, `return isinstance(...) and "..." in str(exc).lower()`. Put the new function next to it, or next to the exception classes at :81-90.

**What depends on it:** only the new guard in `generate`.

**Regression risk:**
- Low for the code itself.
- The behavioural risk is the substring set. `unable to open database file` is also what sqlite raises when `--whitelist-db` names a wrong path or a missing parent directory. `connect_readonly_db` (`db.py:85-94`) uses `mode=ro`, so it never creates the file. Today a mistyped `--whitelist-db` fails each job with `OperationalError: unable to open database file`. After this change the head job requeues forever, the whole queue stalls, and only the warning line shows it. `command_run` (:520-558) does not check that `--whitelist-db` exists at start.
- `sqlite3.DatabaseError` subclasses that are not `OperationalError` (`file is not a database`, `database disk image is malformed`) never reach the predicate, which is correct. A whitelist swapped mid-read during a restore could raise `malformed` and still fail the job for good. That is outside R1 but worth knowing.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="new exception class WhitelistBusy, beside JobFailed/JobStopped/JobTakenOver (:81-90)">
**What changes:** a new `Exception` subclass with a one-line docstring in the style of its neighbours, for example "whitelist.db was locked, busy or could not be opened at claim; the job is requeued without spending its claim". It carries the error text.

**What depends on it:**
- the guard in `generate` raises it;
- `run_job` catches it.

**Regression risk:**
- It must subclass `Exception` directly, never `JobFailed`. Otherwise the `except JobFailed` branch (:466) would end the job `failed`.
- `run_job` must catch it before `except Exception` (:469).
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="generate() (:420-452), the resolve_video call at :422">
**What changes:**
- A narrow `try/except sqlite3.OperationalError` around only the `resolve_video(args.whitelist_db, *claim[:2], args.max_duration)` call.
- On a transient error it raises `WhitelistBusy(str(exc)) from exc`. On anything else it re-raises unchanged (bare `raise`).
- The `refusal is not None` check and everything after it stay outside the try, so no other step's `OperationalError` is classified. That includes `subtitles.db` writes from `store_ready_subtitles` and `mark_translate_finished`.
- The docstring may need a clause on the transient case.

**What depends on it:**
- `run_job` (:459), and through it `serve`;
- every job-pipeline test in `tests/active/test_translate_worker.py`;
- the bounds case `not in whitelist at claim` (test file :306), which must still end `failed` `not in whitelist`.

**Regression risk:**
- Medium. A guard placed too wide would turn transient `subtitles.db` lock errors into requeues, which is out of scope.
- A guard catching `sqlite3.Error` rather than `OperationalError` would still be safe, because the predicate is false for other texts. But the plan says `OperationalError`, and the `no such column` control test pins the text (`OperationalError: no such column…`, built at :474 from `type(exc).__name__`).
- The unchanged re-raise must keep the original type, so use bare `raise`, not `raise exc from ...`.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="resolve_video() (:93-110)">
**What changes:** nothing. The plan keeps it unchanged.

**What depends on it:**
- `command_enqueue` (:122, which catches `sqlite3.Error` and exits 1);
- `generate` (:422);
- the tests, which will monkeypatch it on the loaded module (`monkeypatch.setattr(rig.worker, "resolve_video", ...)`). `generate` looks the name up as a module global, so the patch takes effect.

**Regression risk:** none if left alone. The `connect_readonly_db` call (:95) sits outside its try/finally. A missing file therefore raises `unable to open database file` from the connect, before `busy_timeout` is set. The missing-file test relies on this.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="command_enqueue() (:113-148)">
**What changes:** nothing (out of scope). It still prints `error: whitelist.db: <text>` and returns `EXIT_ERROR` on a locked or missing whitelist.

**What depends on it:**
- the enqueue tests;
- the `DEPLOYMENT.md:291` and `:353` enqueue half;
- `TRANSLATE_WORKER.md:54`.

**Regression risk:** none, provided the predicate and the new exception live only on the `generate` path. Listed so the next step confirms enqueue output is unchanged.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="run_job() (:455-474): new except WhitelistBusy branch, return type None to bool, docstring">
**What changes:**
- The signature becomes `-> bool`.
- A new `except WhitelistBusy as exc:` branch, before `except Exception` (:469), and best placed next to `except JobStopped` (:461). It calls `requeue_translate_job(conn, *claim)` (return value ignored, as at :462), logs `logging.warning("[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s", *claim[:2], exc)` and returns True.
- Every other path returns False, falsy, or falls through to `return False`.
- The docstring ("Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job…") must add the transient requeue and the return value.
- The branch writes no `error` and no `finished_at`.

**What depends on it:**
- `serve` (:510), its only production caller;
- `Rig.run` in the tests (`test_translate_worker.py:480-487`), which discards the return value today and must return it, or the new tests call `rig.worker.run_job` directly;
- the probe `tests/tmp/probe_45_whitelist_locked_at_claim.py:26`.

**Regression risk:**
- Medium. Placing the branch after `except Exception` would silently keep today's behaviour.
- `WhitelistBusy` could reach `logging.exception`, which would log a traceback each cycle, and the CUDA-OOM `is_cuda_oom` unload (:471-472) would never apply.
- `requeue_translate_job` is a conditional update on `state='running' AND started_at=?` (`subtitles.py:149-153, 161-163`). After a B1 takeover it returns False and writes nothing; the log line still goes out (plan).
- `requeue_translate_job` itself can raise `sqlite3.Error` if `subtitles.db` is locked past its busy timeout. That would propagate out of the `except` branch, out of `run_job` and out of `serve`, ending the worker. The same exposure already exists on the `JobStopped` path. The next step may want to note it.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="serve() (:493-511): back-off loop after a transient requeue, idle_since, docstring">
**What changes:**
- `run_job`'s result is read.
- When it is True, a loop runs before the next claim: `deadline = time.monotonic() + TRANSIENT_BACKOFF_SECONDS`, then while not `stop.is_set()` and time remains, `progress["at"] = time.monotonic()` and `time.sleep(min(POLL_SECONDS, remaining))`.
- The comment at :506 explains why `time.sleep` is used and not `stop.wait` (Event.set from the SIGTERM handler on this thread would deadlock), so that rule carries over. The loop must read the module globals at call time, not bind them as default arguments, so tests can shorten them.
- The docstring (:494) must mention the back-off.

**What depends on it:**
- `command_run` (:549);
- the heartbeat thread (`heartbeat_loop` :477-490, which beats only while `time.monotonic() - progress["at"] <= STALL_SECONDS`);
- the subprocess tests for idle beats, SIGTERM and the stall (`test_translate_worker.py:889-983`);
- plan 50's "generation available", which comes from the heartbeat age.

**Regression risk:**
- Medium.
  - `idle_since = time.monotonic()` (:511) is reset after every `run_job`, and the unload check (:504) runs only when nothing is claimed. A model loaded by an earlier job therefore stays in VRAM through an outage (plan's unplanned limit).
  - Head-of-line blocking: the same `queued_at` row is reclaimed every cycle (`claim_translate_job` ORDER BY `queued_at`, rowid, `subtitles.py:133`).
  - During sqlite's 30 s busy wait inside `resolve_video`, `progress["at"]` is not refreshed. That is far under `STALL_SECONDS = 600`, so the heartbeat continues.
  - SIGTERM during the back-off: the handler runs on the main thread between sleeps, and PEP 475 resumes `time.sleep` after the handler. Exit therefore comes within one `POLL_SECONDS` slice (≤2 s), well within `TimeoutStopSec=120` (DEPLOYMENT.md:264) and the tests' `STOP_WINDOW_SECONDS = 60`.
- The idle path (job None) must stay exactly as it is, or `test_idle_run_beats...` (cadence 4.5-6.5 s) could change.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="module constants: new TRANSIENT_BACKOFF_SECONDS = 30.0 beside POLL_SECONDS (:71)">
**What changes:** a new constant, ideally with a one-line comment in the file's style, like the other constants (:62, :64, :69, :72).

**What depends on it:**
- `serve`'s back-off loop;
- the serve-level test, which shortens it on the loaded module together with `POLL_SECONDS`.

**Regression risk:**
- Low.
- `POLL_SECONDS` is also read by `AudioPipe.wait_samples` (:283-285), so a test that shortens it changes that wait too. In-process this only affects the module instance the test loaded (`_worker()` loads a fresh module per call).
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="command_run() (:520-558) and the SIGTERM handler (:537-538)">
**What changes:** nothing in the code.

**What depends on it:** `serve`'s new back-off path. The stop event set by the handler ends the back-off. The `finally` (:550-554) then sets stop, joins the heartbeat and closes the connection.

**Regression risk:**
- Low.
- Worst-case stop latency becomes: a stop arriving during sqlite's 30 s busy wait, plus at most one 2 s slice. That is still under 120 s.
- `command_run` does not validate `--whitelist-db`, so a misconfigured path now gives a worker that loops instead of failing jobs (see the predicate entry).
</impact>
<impact path="engine/server/data/subtitles.py" element="requeue_translate_job() (:161-163), claim_translate_job() (:130-138), recover_translate_jobs() (:141-146), MAX_CLAIMS (:18)">
**What changes:** nothing. The plan does not touch `subtitles.py`.

**What depends on it:** the new branch reuses `requeue_translate_job` exactly as `JobStopped` does: `state='queued'`, `attempts = attempts - 1`, `queued_at` untouched, conditional on `started_at`.

**Regression risk:**
- None to the store.
- Semantics to confirm: the attempt is given back each cycle, so `recover_translate_jobs`' `MAX_CLAIMS` count never sees transient cycles.
- A SIGKILL during a busy wait leaves `attempts=1`, `running`. The next start requeues it, as today.
- The docstring of `requeue_translate_job` says "(a stop mid-job)". It now has a second caller, so the docstring is slightly stale. That is cosmetic, and the plan says not to touch this file. Flagged as uncertain whether to update.
</impact>
<impact path="engine/server/data/db.py" element="is_interrupted_error() (:68-74), connect_readonly_db() (:85-94)">
**What changes:** nothing. The plan keeps the predicate in the worker.

**What depends on it:** `connect_readonly_db` is what produces `unable to open database file` for a missing whitelist (`mode=ro`). `install_deadline_handler` only interrupts under `statement_deadline`, which `resolve_video` does not use, so `interrupted` never arises here.

**Regression risk:** none (unchanged). Listed because the predicate's wording depends on this function's open mode.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_video_row() (:25), called by resolve_video">
**What changes:** nothing.

**What depends on it:** `resolve_video`. I checked it does not swallow `sqlite3.OperationalError`: its excepts at :91/:94/:174 are HTTP and ValueError, and :440 is in a different route handler. So a lock or no-such-column error propagates to the guard unchanged.

**Regression risk:** none.
</impact>
<impact path="engine/server/data/moderation.py" element="list_active_denied_hosts() (:137), called by resolve_video">
**What changes:** nothing.

**What depends on it:** `resolve_video`'s second read on the same connection. A lock that starts between the two statements raises here, and the guard catches it the same way, because the guard wraps the whole `resolve_video` call.

**Regression risk:** none. The function does not catch sqlite errors.
</impact>
<impact path="tests/active/test_translate_worker.py" element="new job-pipeline tests (injected lock, real missing file, real BEGIN EXCLUSIVE lock, no-such-column control, recovery)">
**What changes:** five or more new tests that reuse `Rig`.

**What depends on it:** the suite runtime. `tests/last_test_validation.json` records 40.6 s for this file today, and the real-lock test adds about 30 s.

**Regression risk:** the risk is in the test mechanics.
- `Rig.claim()` (:472-478) enqueues and asserts `('queued','queued')`. The recovery test must not call it a second time. It should reclaim through `claim_translate_job(rig.conn, "en", ...)` directly, assign `rig.job`, and assert attempts == 1.
- Missing file: `rig.whitelist.unlink()`. The recovery step rewrites it with `_whitelist(rig.whitelist, JOB_VIDEOS, deny=True)`.
- Real lock: `sqlite3.connect(rig.whitelist, isolation_level=None).execute("BEGIN EXCLUSIVE")`, as in the stall test (:946-948). `_whitelist` leaves the file in rollback-journal mode (:190), which is what makes the EXCLUSIVE lock block readers. The holder must be closed in `finally`.
- Logging: `caplog` at WARNING on the root logger. `setup_logging` is never called in-process, and `tests/active/conftest.py` has no logging setup, so capture should work. Assert on `record.levelno == logging.WARNING` and on `getMessage()` containing `v-1`, `peer.example` and the error text.
- Control `no such column`: `error` must start with `OperationalError: no such column`. Check that `logging.exception` is still emitted, so the catch-all was taken.
- `Rig.run` (:480-487) must return `run_job`'s value. If not, the tests call `rig.worker.run_job` with their own Namespace.
- The probe imports `HOST`, `JOB_VIDEOS`, `_subtitles`, `_whitelist` and `_worker` from this module (`tests/tmp/probe_45...:10`), so do not rename these.
</impact>
<impact path="tests/active/test_translate_worker.py" element="new serve-level test (thread, shortened POLL_SECONDS/TRANSIENT_BACKOFF_SECONDS, stub runner, patched resolve_video)">
**What changes:**
- A new test runs `rig.worker.serve(rig.conn, args, runner, stop, progress)` on a thread. That is safe because `connect_subtitles_db` opens with `check_same_thread=False` (`subtitles.py:27`).
- It shortens the constants with `monkeypatch.setattr(rig.worker, "POLL_SECONDS", ...)` and `monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", ...)`.
- `resolve_video` is patched to record `time.monotonic()` and raise `OperationalError("database is locked")`.
- The job is only enqueued, not claimed through `Rig.claim`, because `serve` claims it.
- `StubRunner` has `model = None` and `unload`, which is all `serve` touches.

**What depends on it:** nothing else.

**Regression risk:**
- Flakiness and hangs.
  - Use a daemon thread, and `stop.set()` plus `join(timeout)` in `finally`, so a failing assert never hangs the session.
  - The timing assertions (second claim ≥ back-off after the first; stop mid-back-off returns within about one slice; `progress["at"]` advances) need margins for a loaded machine. Existing tests use wide margins, for example `BEAT_GAP_MS`.
- Setting `stop` from the test thread is fine (no signal handler involved).
- Shortening `POLL_SECONDS` also affects `AudioPipe.wait_samples` on that module instance. This is irrelevant here because the job never reaches the download.
</impact>
<impact path="tests/active/test_translate_worker.py" element="module docstring (:1-37)">
**What changes:** the docstring is the file's spec, listing every behaviour under test. It needs new bullets:
- under Outcomes, or a new paragraph, the transient requeue (injected lock, missing file, real lock), the `no such column` control and recovery;
- under Service, or a new paragraph, the serve back-off, heartbeat progress and stop.

**What depends on it:** reviewers. The project keeps this docstring exhaustive.

**Regression risk:** documentation only. Omitting it leaves the spec stale.
</impact>
<impact path="tests/active/test_translate_worker.py" element="test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on (:932-983), constants STALLED_WINDOW_SECONDS/TEST_STALL_SECONDS/RESUME_SECONDS and the comment at :181">
**What changes:** nothing intended.

**What depends on it:** the stall test holds `BEGIN EXCLUSIVE` on the whitelist while the subprocess worker is inside `resolve_video`'s 30 s busy wait. The hold lasts from the claim, which can take up to 10 s (:954), through `TEST_STALL_SECONDS + 1` (5 s) and `STALLED_WINDOW_SECONDS` (11 s). That is about 16-26 s, and the comment at :181 says about 18 s.

**Regression risk:**
- Low, but the failure mode changes. Today, on a slow machine where the hold passes 30 s, the job fails with `OperationalError: database is locked`.
- After this change the job is requeued instead and the worker backs off for 30 s, with the heartbeat beating during it. So:
  - the `_jobs(...) == [("running", None)]` assertion at :962 would read `queued`, or `running` again;
  - the :972 `("failed", "not in whitelist")` assert would wait for a reclaim beyond `RESUME_SECONDS = 8`.
- Either way it would fail, as it would today. The margin is unchanged.
</impact>
<impact path="tests/active/test_translate_worker.py" element="test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept (:848-852) and the bounds case 'not in whitelist at claim' (:306, test :712)">
**What changes:** nothing.

**What depends on it:**
- the stop test, which shares the `requeue_translate_job` call with the new branch;
- the `not in whitelist` case, which exercises the refusal path right after the new guard.

**Regression risk:** low. The bounds case would catch a guard that swallowed the refusal. The stop test would catch a reordering of the excepts that broke `JobStopped`.
</impact>
<impact path="tests/tmp/probe_45_whitelist_locked_at_claim.py" element="the triage probe">
**What changes:** it asserts the old, buggy behaviour (`state == "failed"` and `("exists", "failed")` on re-enqueue). After the fix it would fail.

**What depends on it:** nothing in the suite. `tests/config.json` maps only `tests/active` files, and no pytest config collects `tests/tmp`. It also calls `run_job(..., runner=None, ...)`, which is still valid for the new branch.

**Regression risk:**
- None to the suite.
- It is a stale artefact, so delete it, or leave it as a scratch file. I am not certain of the project's policy for `tests/tmp` probes after a fix; `probe_green.py`, `probe_race.py` and others remain there.
</impact>
<impact path="tests/last_test_validation.json" element="test_translate_worker.py entry (:599-606) and per-test ids (:3583-3775)">
**What changes:** this is a generated artifact holding the file digest, the pass count (49) and the duration (40.6 s). The test runner rewrites it; nobody edits it by hand.

**What depends on it:** the project's test-validation tooling. I am not sure what consumes it.

**Regression risk:** none if it is regenerated by the normal test run. After the build, the count should rise and the duration grow by about 30 s or more.
</impact>
<impact path="tests/config.json" element="test_translate_worker.py source mapping (:416-424)">
**What changes:** nothing. It already maps `translate-worker.py` and `subtitles.py` to this test file, so the change triggers the right test.

**Regression risk:** none.
</impact>
<impact path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md" element="Known Gaps (:152-155), Error Texts (:137), Job Pipeline step 1 (:83-85), Serve Loop (:79), Logs (:159-168)">
**What changes (as the plan states):**
- delete the :154 bullet and keep the faster-whisper/VRAM bullet;
- :137 becomes "`<ExceptionType>: <text>` for anything else, including CUDA out-of-memory";
- add the transient paragraph at Job Pipeline step 1;
- one line on the back-off in Serve Loop;
- add the `whitelist.db unavailable, requeued video_id=… host=…: <error>` warning line to Logs.

**What depends on it:**
- `engine/server/README.md:25` and `DEPLOYMENT.md:230` point here;
- `CONTEXT.md:19` points here.

**Regression risk:** doc accuracy only. See the docs checklist for the other sections of this file that the plan does not name.
</impact>
<impact path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md" element="Job Lifecycle (:29-39), Job Pipeline intro (:83), Bounds row 'Whitelist and denylist' (:102), Stop, Crash and Recovery (:141), Heartbeat (:150)">
**What changes (not named in the plan, but now partly inaccurate):**
- :33 `queued` meaning: a transiently requeued job is `queued` again with its `attempts` restored.
- :39 "Every job ends in exactly one of…": still true but incomplete. A job may now cycle `queued`/`running` while `whitelist.db` is unavailable, as it already can on stop.
- :83 "each bound ending the job `failed`": step 1 can now return the job to `queued` instead.
- :141 SIGTERM bullet: "Stop is checked each time the chunk loop wakes". A stop during the back-off now ends within one 2 s slice, and a stop during sqlite's busy wait takes up to about 30 s.
- :150 Heartbeat: progress is recorded "on every serve pass and every chunk-loop wake (at most 2 s apart)". The back-off loop also records it each slice. The busy wait records none for up to 30 s, which is under `STALL_SECONDS`.

**Regression risk:** doc drift if these are left unchanged. I am uncertain whether the operator wants them all touched. At minimum :83 and :141 read wrong after the change.
</impact>
<impact path="DEPLOYMENT.md" element="Triage row :353 (whitelist.db locked)">
**What changes:** rewrite the job half.
- Symptom: a job stays `queued`, or flips between `queued` and `running`, and the journal repeats `[translate-worker] whitelist.db unavailable, requeued video_id=… host=…: database is locked`, or `unable to open database file`.
- Cause: the updater's merge holds the lock past 30 s, or a restore has removed the file.
- Action: none for the job; it runs once the merge or restore ends.
- The `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) stays.
- A repeating `unable to open` with no restore in progress means the `--whitelist-db` path or its permissions are wrong. Worth one clause, given the misconfiguration risk.

**What depends on it:** operators.

**Regression risk:** doc only.
</impact>
<impact path="DEPLOYMENT.md" element="Triage row :348 'Jobs stay queued' and unit note :264 (TimeoutStopSec stop path)">
**What changes (not in the plan):**
- :348 lists the causes of "Jobs stay `queued`" as no worker, or one long job ahead. A locked or missing `whitelist.db` is now a third cause, with the warning line as the tell. A cross-reference to :353 would do.
- :264 describes the SIGTERM path. Adding "or ends the back-off wait" is optional; 120 s still covers the worst case (a 30 s busy wait plus a 2 s slice).

**Regression risk:** doc drift only. :348 is the more important of the two.
</impact>
<impact path="CONTEXT.md" element="glossary entry 'Translate job' (:19)">
**What changes:** the entry says a job moves from `queued` to `running` and ends in one of three states, and that "A job left `running` by a crash is requeued once…". It does not mention the stop requeue either. A clause such as "a job whose `whitelist.db` check meets a lock or a missing file goes back to `queued` unspent and is retried after a back-off" would keep the glossary complete.

**Regression risk:** doc only. I am uncertain it is wanted: the plan names only the two docs, and the glossary already leaves out the stop requeue.
</impact>
<impact path="docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md" element="Status line (:3), acceptance checkboxes (:95-98), file location">
**What changes:** on delivery, per `docs/project/triage-labels.md`:
- `Status: bug, complete`;
- the file moves to `docs/project/issues/archive/`;
- the checkboxes get ticked.

**What depends on it:** `docs/project/issues/issue-tracker.md:8` links it by path.

**Regression risk:** a broken link if the file moves and the tracker row is not updated.
</impact>
<impact path="docs/project/issues/issue-tracker.md" element="row 45 (:8)">
**What changes:** the state goes from `ready-for-agent` to `complete`, and the link moves to `archive/` if the issue file moves. It follows the convention of the earlier archived issues.

**Regression risk:** stale tracker.
</impact>
<impact path="docs/project/roadmap.md" element="F11-M2 PARTIAL line (:60)">
**What changes:** "Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`." becomes a delivered statement, or moves into the Delivered list with a pointer to `TRANSLATE_WORKER.md`.

**Regression risk:** stale roadmap.
</impact>
<impact path="docs/project/plans/50-translate-generation-in-page.md" element="AC1 feature gate (heartbeat freshness) and AC3 polling while queued/running (:27-29, :49-53)">
**What changes:** nothing in this plan, which is a future consumer.

**What depends on it:**
- The page polls while the state is `queued` or `running`. During an outage it now sees `queued` and `running` alternating indefinitely, instead of a terminal `failed`.
- Generation availability stays true, because the back-off keeps `progress["at"]` fresh, so the heartbeat beats.

**Regression risk:** none now. Plan 50's design should know a job can sit `queued` for the length of an updater merge.
</impact>
<impact path="engine/server/README.md" element="Translate worker paragraph (:25) and heartbeat note (:31)">
**What changes:** nothing needed. It defers to `TRANSLATE_WORKER.md` for the lifecycle. The heartbeat statement ("stops beating when the serve loop stalls") stays true, because the back-off refreshes progress.

**Regression risk:** none. Checked and listed for completeness.
</impact>
</impacts>


### docs_checklist


<doc path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md">
Changes:
- Delete the Known Gaps bullet at :154, and keep the faster-whisper/VRAM bullet.
- Error Texts :137: drop "and a locked `whitelist.db`".
- Job Pipeline step 1 (:85): add a paragraph covering:
  - what counts as transient: `locked`, `busy`, `unable to open`, for example during the updater merge or a restore;
  - the job returns to `queued` with `attempts` restored and `queued_at` kept, with no `error` or `finished_at`;
  - an about 30 s back-off (`TRANSIENT_BACKOFF_SECONDS`) that a stop ends within one 2 s slice;
  - the cycle repeats until the file is usable;
  - every other database error still fails the job as `<ExceptionType>: <text>`.
- Pipeline intro :83 ("each bound ending the job `failed`"): qualify it for step 1's transient case.
- Serve Loop :79: one line saying a transient requeue is followed by the back-off before the next claim, with progress refreshed during it.
- Logs: add `whitelist.db unavailable, requeued video_id=… host=…: <error>` (a warning).
- Also check :33 (meaning of `queued`) and :39 ("Every job ends in exactly one of…").
- Stop, Crash and Recovery :141: a stop during the back-off ends it promptly; a stop during sqlite's 30 s busy wait takes up to about 30 s.
- Heartbeat :150: the back-off also records progress.
- All written as current state, one paragraph per line.
</doc>
<doc path="DEPLOYMENT.md">
Changes:
- Triage row :353: rewrite the job half. The job stays `queued` and the journal repeats the `whitelist.db unavailable, requeued` warning while the updater merge or a restore holds or removes `whitelist.db`. The job runs by itself afterwards, with no re-queue needed. A repeating `unable to open` outside a restore points at a wrong `--whitelist-db` path or permissions. Keep the `enqueue` half (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends) as it is.
- Triage row :348 "Jobs stay `queued`": add a locked or missing `whitelist.db` (the warning line) as a cause.
- Optionally :264 (TimeoutStopSec): the stop path also ends the back-off wait.
</doc>
<doc path="CONTEXT.md">
"Translate job" glossary entry (:19): optionally add that a job whose claim-time `whitelist.db` check meets a lock or a missing file returns to `queued` unspent and is retried after a back-off. It is uncertain whether this is wanted, since the entry already leaves out the stop requeue.
</doc>
<doc path="tests/active/test_translate_worker.py">
Module docstring (:1-37), which is the file's behavioural spec. Add:
- the transient-requeue outcomes: injected lock, missing file, real EXCLUSIVE lock, the `no such column` control and recovery to `ready`;
- the serve back-off behaviour: next claim no sooner than the back-off, progress advancing, stop ending the wait promptly.
</doc>
<doc path="docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md">
On delivery: `Status: bug, complete`, the acceptance boxes ticked, and the file moved to `docs/project/issues/archive/`.
</doc>
<doc path="docs/project/issues/issue-tracker.md">
Row 45: state set to `complete`, with the link updated to the archive path.
</doc>
<doc path="docs/project/roadmap.md">
:60: replace "Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`." with a delivered statement pointing at `TRANSLATE_WORKER.md`.
</doc>


### highest_risk


engine/server/db/jobs/translate-worker.py, the new predicate (`unable to open`): a wrong `--whitelist-db` path, a missing parent directory or a permissions problem gives the same sqlite text as a mid-restore missing file. A misconfigured worker that today fails each job visibly would instead requeue the head job forever and stall the whole queue, with only a warning line to show it; `command_run` checks nothing at start.
engine/server/db/jobs/translate-worker.py, `run_job` except ordering and the `generate` guard scope: `WhitelistBusy` must be caught before `except Exception` (:469) and must not subclass `JobFailed`. The try must wrap only the `resolve_video` call at :422 and re-raise non-transient errors with a bare `raise`. Any slip silently keeps today's `failed` outcome, turns `subtitles.db` lock errors into requeues, or changes the `OperationalError: no such column…` text.
engine/server/db/jobs/translate-worker.py, `serve`'s back-off loop, with the new serve-level test in tests/active/test_translate_worker.py: the loop must keep `time.sleep` in `POLL_SECONDS` slices (the :506 deadlock rule), refresh `progress["at"]` each slice so the heartbeat keeps beating, and read the module constants at call time so the threaded test can shorten them. The threaded test needs a daemon thread with `stop.set()` in `finally`, or a failure hangs the run. The existing subprocess stall test's whitelist hold (about 16-26 s against the 30 s busy timeout) now ends in a requeue and back-off rather than `failed` if a slow machine pushes it past 30 s.

## 2026-10-03 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I opened every path in the inventory and checked its claims against the file. The worker (`translate-worker.py`) matches what the inventory says: the exception classes are at :81-90, `resolve_video` at :93-110 with `connect_readonly_db` outside its try, the call in `generate` at :422, `run_job`'s handler order at :455-474, `serve` at :493-511 including the :506 comment and the :511 `idle_since` reset, and the SIGTERM handler at :537-538. The store matches too: in `subtitles.py`, `requeue_translate_job` (:161-163) is a conditional `attempts - 1` update keyed on `started_at`, `claim_translate_job` orders by `queued_at`, rowid, and `connect_subtitles_db` uses `check_same_thread=False`. The test file matches: `Rig.run` (:480-487) discards the return value, `StubRunner` has `model = None` and `unload`, the stall test sits at :932-983 with the about 18 s comment at :181, the stop test at :848-852, and the bounds test at :712. Neither `tests/active/conftest.py` nor any pytest config sets up logging, so `caplog` will see the root logger's warning. The probe imports the five names and calls `run_job` as the inventory says. `tests/config.json` names `tests/tmp` as the "working" directory, so leaving the probe there fits the project's layout. Every doc line the inventory names reads as it claims: TRANSLATE_WORKER.md :33/:39/:79/:83/:137/:141/:150/:154, DEPLOYMENT.md :264/:291/:348/:353, CONTEXT.md:19, README :25/:31, plan 50 :27-29/:49-53, roadmap :60 and issue-tracker :8. The only production caller of `run_job` and `serve` is the worker itself; nothing else in the tree calls either. I found nothing the inventory is missing that would change the build. The plan holds against the inventory.
<question id="1">
Yes. The guard wraps only the `resolve_video` call at :422, and the refusal check stays outside it. So the transient set (`locked`, `busy`, `unable to open`) becomes `WhitelistBusy`, and everything else keeps today's path into the catch-all, with its `OperationalError: …` text built from `type(exc).__name__` at :474. Placing `except WhitelistBusy` beside `except JobStopped`, ahead of `except Exception` at :469, keeps it away from the OOM unload and from `logging.exception`. `requeue_translate_job` already gives exactly what R2 asks for: `queued`, the attempt given back, `queued_at` untouched. So `MAX_CLAIMS` never counts these cycles. Because `queued_at` is kept, the head-of-queue ordering in `claim_translate_job` gives the next claim to the same job. That makes the repeat and the recovery (R3, R4) fall out of existing code. The back-off loop keeps the `time.sleep` rule from :506 and refreshes `progress["at"]` every slice, so `heartbeat_loop`'s `STALL_SECONDS` check keeps passing. A stop ends the wait within one `POLL_SECONDS` slice. The triage probe already showed that a `BEGIN EXCLUSIVE` holder blocks an in-process `mode=ro` reader on the rollback-journal fixture (30.4 s), so the real-lock test will work. A missing file fails at `sqlite3.connect` with `mode=ro`, as the `connect_readonly_db` docstring (`db.py:88`) states, so the missing-file test will work too.
</question>
<question id="2">
- **One stuck job holds up the whole queue.** While `whitelist.db` is unusable, the oldest job is reclaimed every cycle and every job behind it waits.
- **Repeating log lines.** The warning line repeats about every 60 s under a lock and about every 30 s for a missing file.
- **Stop can take about 30 s.** A stop that lands during sqlite's 30 s busy wait takes up to about 30 s. A stop during the back-off ends within 2 s. Both stay well under `TimeoutStopSec=120`.
- **The model stays in VRAM.** Because `idle_since` is reset after every `run_job` (:511), a model loaded by an earlier job stays resident for as long as the outage lasts.
- **A wrong `--whitelist-db` path no longer fails loudly.** Today each job fails. Afterwards the worker loops without end, and only the warning line shows it, because `command_run` never checks the path.
- **Plan 50's page sees no end state.** It would see `queued`/`running` alternate with no terminal state, while availability stays true, because the heartbeat keeps beating.
- **Some restore failures still fail the job for good.** A restore that is caught half-written still fails the job permanently. A partial file raises `malformed`, which is a `DatabaseError` and not an `OperationalError`. A zero-length file opens as an empty database and raises `no such table: videos`, which is an `OperationalError` the predicate does not match. Both are outside R1's wording, so they fail as today.
- **`requeue_translate_job` can itself fail.** It can raise if `subtitles.db` stays locked past its own 30 s timeout. That would escape `serve`, exactly as it already can on the `JobStopped` path.
</question>
<question id="3">
In code, only the ordering and placement rules the inventory already lists:
- `WhitelistBusy` subclasses `Exception`, not `JobFailed`;
- its branch sits before the catch-all;
- the re-raise is a bare `raise`;
- the guard does not widen past :422;
- the back-off reads the module globals at call time;
- the idle path (job `None`) is left byte-for-byte as it is, so the beat-cadence test still holds.

In the tests, `Rig.run` should return `run_job`'s value. Nothing else in the suite consumes it, and `Rig.claim` must not be called twice in the recovery test. The existing stall test keeps its margin, because its hold of about 16-26 s is still under the 30 s busy timeout. In the docs, the two named files plus the drift the inventory lists:
- TRANSLATE_WORKER.md :83 and :141 read wrong after the change;
- :33, :39 and :150 are incomplete;
- DEPLOYMENT.md :348 is missing a cause.
</question>
<question id="4">
- **Locked or missing whitelist.** A job whose claim-time check meets a lock, a busy file or an unopenable `whitelist.db` no longer ends `failed` as `OperationalError: …`. It returns to `queued` with no `error`, `finished_at` or attempt spent, and the worker pauses for about 30 s before its next claim. This repeats until the file is usable.
- **Wrong path or permissions.** A misconfigured path or bad permissions now gives a worker that loops and logs, where today it failed every job.
- **New return value.** `run_job` returns a bool where it returned None. Only `serve` and the test rig see this.
- **Unchanged.** `enqueue`'s output and exit codes, every non-transient database error, every other bound and end state, the stop and crash paths, and the idle loop.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Take the small idle-unload fix the plan already names.** On a transient requeue, skip the `idle_since` reset at :511, and run the same `runner.model is not None and time.monotonic() - idle_since >= IDLE_UNLOAD_SECONDS` unload check once per back-off slice. What it changes: a model loaded before an updater merge is released after 300 s, as on an idle queue, instead of staying resident for the whole outage. Cost: about 3 lines in `serve`, one Serve Loop sentence, and one more assertion in the serve-level test (`StubRunner` with `model` set to a sentinel and `IDLE_UNLOAD_SECONDS` shortened: `unloads == 1`). If you decline it, the plan's "unplanned limit" stays as written and should be copied into TRANSLATE_WORKER.md Known Gaps, so the docs do not claim the 300 s unload always applies.

2. **Keep the real-lock test.** Acceptance criterion 1 explicitly reads "an exclusive lock held on a rollback-journal `whitelist.db` throughout the check". Only the real `BEGIN EXCLUSIVE` test proves that; the injected text does not. Cost: about 30 s on this file (40.6 s now, about 71 s after). Dropping it would leave criterion 1 shown only by the injected double. Hoisting the busy timeout into a constant to make the test fast stays rejected, as the plan says, because the issue puts changing the 30 s timeout out of scope.

3. **Widen the doc edits to the full set the inventory found.**
   - TRANSLATE_WORKER.md :83 (qualify "each bound ending the job `failed`"), :141 (a stop during the back-off ends within one 2 s slice; a stop during the busy wait takes up to about 30 s), :33/:39 (`queued` can mean returned unspent) and :150 (the back-off records progress).
   - DEPLOYMENT.md :348, "Jobs stay `queued`": add the warning line as a third cause.
   - DEPLOYMENT.md :353: add a clause that a repeating `unable to open` with no restore running means a wrong `--whitelist-db` path or wrong permissions.

   Cost: a few sentences, no code. Without them, :83 and :141 say something false after the build. CONTEXT.md:19 already omits the stop requeue, so leaving it alone is consistent. Adding one clause there is optional and costs one line.

4. **Restores and the docs.** The docs should not promise that a restore is always handled. The requeue covers a file that is absent or cannot be opened. A file caught half-copied fails the job permanently, as today: a partial file raises `malformed`, and a zero-length file raises `no such table: videos`. That matches R1's wording, so nothing should change in code. But the Job Pipeline paragraph should say "missing", not "during any restore". Cost: wording only.

5. **Test doubles: the plan widens none.**
   - `StubRunner` and `ScriptedHost` see no new calls. `serve` touches only `runner.model` and `runner.unload`, which `StubRunner` already has.
   - The patched `resolve_video` in the new tests is a new double, built to record call times and raise; no existing double is widened.
   - `Rig.run` is a helper, not a double. Make it return `run_job`'s value. Cost: one word, no change to any existing assertion.

6. **Housekeeping on delivery.**
   - Leave or delete `tests/tmp/probe_45_whitelist_locked_at_claim.py`. `tests/config.json` names `tests/tmp` as the working directory and nothing collects it, so it is harmless either way. It now asserts the old behaviour, so deleting it avoids confusion. Cost: none.
   - Mark issue 45 `Status: bug, complete`, move it to `issues/archive/`, and update issue-tracker.md:8's link and state and roadmap.md:60. Cost: three small edits. Skipping the tracker update leaves a broken link once the file moves.

## 2026-10-03 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Draft: issue 45, requeue and back off when `whitelist.db` is locked or missing at claim

I read the following before drafting: `translate-worker.py` lines 55-154 and 340-564 (constants, exception classes, `resolve_video`, `command_enqueue`, `is_cuda_oom`, `generate`, `run_job`, `heartbeat_loop`, `serve`, `command_run`), the test file's docstring, `_whitelist`, `_worker`, `Rig`, `StubRunner` and the outcome tests at :799-852, `TRANSLATE_WORKER.md` lines 25-168, and the `DEPLOYMENT.md` rows at :264, :348 and :353. Every claim below is checked against those lines.

### What has to be tested

- The classification at the claim-time check: three real or injected transient forms requeue the job. A non-transient error fails it with today's text, and a refusal (`not in whitelist`) still fails the job; the existing bounds case already covers the refusal.
- The row after a transient requeue: `queued`, `attempts` 0, `queued_at` 1000, no `error`, no `finished_at`, and no remote request made.
- The log: exactly one WARNING record naming the key and the error text, and no ERROR or traceback record.
- The `run_job` return value: True only on a transient requeue.
- `serve`: the reclaim comes at least one back-off after the first claim; `progress["at"]` advances during the back-off; a stop during the back-off returns within about one slice.
- Recovery: the same row, claimed again, runs to `ready`.

### Module map

| File | Change |
|---|---|
| `engine/server/db/jobs/translate-worker.py` | 1 constant, 1 exception class, 1 predicate, a 5-line guard in `generate`, a new branch and a bool return in `run_job`, a back-off loop in `serve`, 3 docstrings |
| `tests/active/test_translate_worker.py` | `Rig.run` returns the result; 2 imports, 2 constants and 2 helpers; 4 test functions (8 cases); docstring bullets |
| `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` | the sections listed under Documentation |
| `DEPLOYMENT.md` | rows :353 and :348, the note at :264 |
| issue 45, `issue-tracker.md`, `roadmap.md` | delivery bookkeeping |

`db.py`, `subtitles.py`, `resolve_video` and `command_enqueue` are unchanged.

### `translate-worker.py`

**Constant**, placed after `POLL_SECONDS = 2.0` (:71) with a comment in the file's style:

```python
POLL_SECONDS = 2.0
# Wait after a claim found whitelist.db locked or missing, before the same head job is claimed again (R3).
TRANSIENT_BACKOFF_SECONDS = 30.0
```

**Exception**, after `JobTakenOver` (:89-90). It subclasses `Exception` directly and never `JobFailed`; otherwise the `except JobFailed` branch would end the job `failed`.

```python
class WhitelistBusy(Exception):
    """whitelist.db was locked, busy or could not be opened at claim; the job is requeued without spending its claim."""
```

**Predicate**, after `is_cuda_oom` (:351-353), in the same shape:

```python
def is_transient_db_error(exc: BaseException) -> bool:
    """sqlite3 names a locked, busy or unopenable database in an OperationalError's text; corrupt or partial files are not transient."""
    return isinstance(exc, sqlite3.OperationalError) and any(word in str(exc).lower() for word in ("locked", "busy", "unable to open"))
```

Ladder: rung 2. This is the existing `is_cuda_oom` shape, not a reuse of `db.is_interrupted_error`, because there is one caller and the word set is this worker's policy. It is an inline tuple, not a named constant, because it is read in one place only.

**`generate`**: the guard wraps only the call at :422. The refusal check and everything after it stay outside the `try`, so `subtitles.db` errors from later steps are never classified. A bare `raise` keeps the original type, so the catch-all still writes `OperationalError: …`.

```python
def generate(conn: sqlite3.Connection, claim: tuple[str, str, str, int], args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> str:
    """AC3 for one claim (video_id, instance_domain, target_language, started_at), each bound raising JobFailed before the next remote request, a locked or missing whitelist.db raising WhitelistBusy; the end state written."""
    try:
        row, refusal = resolve_video(args.whitelist_db, *claim[:2], args.max_duration)
    except sqlite3.OperationalError as exc:
        if is_transient_db_error(exc):
            raise WhitelistBusy(str(exc)) from exc
        raise
    if refusal is not None:
        raise JobFailed(refusal)
    ...  # unchanged from :425
```

`resolve_video` is looked up as a module global when the call runs, so `monkeypatch.setattr(rig.worker, "resolve_video", …)` takes effect. A missing file raises from `connect_readonly_db` at :95, before the `try/finally` there and before `busy_timeout` is set. It surfaces as `unable to open database file` at once.

**`run_job`**: it now returns `-> bool`. The new branch sits right after `JobStopped`, so it is ahead of the catch-all and cannot reach `logging.exception` or the CUDA-OOM unload.

```python
def run_job(conn: sqlite3.Connection, job: sqlite3.Row, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> bool:
    """Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job or whitelist.db is locked or missing at claim; a row B1's route took over is left as B1 wrote it. True only for the whitelist.db requeue, so serve backs off before claiming again."""
    claim = (job["video_id"], job["instance_domain"], TARGET_LANGUAGE, job["started_at"])
    try:
        state = generate(conn, claim, args, runner, stop, progress)
        logging.info("[translate-worker] job %s video_id=%s host=%s", state, *claim[:2])
    except JobStopped:
        requeue_translate_job(conn, *claim)
        logging.info("[translate-worker] stopped mid-job, requeued video_id=%s host=%s", *claim[:2])
    except WhitelistBusy as exc:
        # No error, no finished_at: the attempt is given back, so MAX_CLAIMS never counts these cycles; False from the requeue (B1 took over) writes nothing more.
        requeue_translate_job(conn, *claim)
        logging.warning("[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s", *claim[:2], exc)
        return True
    except JobTakenOver:
        ...  # the three remaining branches are unchanged (:464-474)
    return False
```

The requeue's return value is ignored here, as it is at :462. One known exposure is unchanged: if `requeue_translate_job` itself raises because `subtitles.db` is locked past its own timeout, the exception propagates out of `serve`. The `JobStopped` path already has the same exposure, and `subtitles.db` locking is out of scope.

**`serve`**: the idle path (:503-508) is unchanged byte for byte, which protects the 4.5-6.5 s beat-cadence test.

```python
def serve(conn: sqlite3.Connection, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> None:
    """Claim and run jobs one at a time until stop, polling every POLL_SECONDS when idle, waiting TRANSIENT_BACKOFF_SECONDS after a whitelist.db requeue, and unloading the model after IDLE_UNLOAD_SECONDS without a job."""
    idle_since = time.monotonic()
    while not stop.is_set():
        ...  # unchanged through the claimed log line (:497-509)
        if run_job(conn, job, args, runner, stop, progress):
            # Back off in POLL_SECONDS slices of time.sleep, as above, so a stop ends the wait within one slice and progress stays as fresh as on the idle poll.
            deadline = time.monotonic() + TRANSIENT_BACKOFF_SECONDS
            while not stop.is_set() and (remaining := deadline - time.monotonic()) > 0:
                progress["at"] = time.monotonic()
                time.sleep(min(POLL_SECONDS, remaining))
        idle_since = time.monotonic()
```

Both constants are read from module globals at run time and are not bound as defaults, so the serve test can shorten them. After a stop, the inner loop exits, then the outer `while` exits, and `command_run`'s `finally` runs as it does today. `idle_since` keeps being reset after every `run_job`; that is the plan's named limit (no idle unload during an outage), not changed here.

### `tests/active/test_translate_worker.py`

Two imports, `contextlib` and `logging`. `Rig.run` changes to `-> bool` and `return self.worker.run_job(...)`. Existing callers ignore the result, so they are unaffected.

```python
LOCKED = "database is locked"
UNOPENABLE = "unable to open database file"
# Shortened on the loaded module for the serve test; margins sized for a loaded machine.
BACKOFF_SECONDS = 1.0
SLICE_SECONDS = 0.05


def _raising(text: str, then=None):
    """A resolve_video stand-in raising OperationalError(text), on every call, or on the first only and then `then`."""
    calls: list[float] = []

    def resolve(*args):
        calls.append(time.monotonic())
        if then is not None and len(calls) > 1:
            return then(*args)
        raise sqlite3.OperationalError(text)

    resolve.calls = calls
    return resolve


def _until(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@contextlib.contextmanager
def _exclusive(path: Path):
    """BEGIN EXCLUSIVE on the rollback-journal whitelist, held for the block; readers wait out their busy timeout."""
    holder = sqlite3.connect(path, isolation_level=None)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        yield
    finally:
        holder.close()
```

**Transient requeue**, three cases. The real-lock case adds about 30 s, the same as the triage probe; it is kept because R6 prefers it.

```python
@pytest.mark.parametrize("case", ["injected lock", "missing file", "held EXCLUSIVE lock"])
def test_a_whitelist_db_locked_or_missing_at_claim_requeues_the_job_unspent_with_one_warning(rig, monkeypatch, caplog, case):
    text = UNOPENABLE if case == "missing file" else LOCKED
    hold = contextlib.nullcontext()
    if case == "injected lock":
        monkeypatch.setattr(rig.worker, "resolve_video", _raising(LOCKED))
    elif case == "missing file":
        rig.whitelist.unlink()
    else:
        hold = _exclusive(rig.whitelist)
    rig.claim()
    with hold:
        assert rig.run(StubRunner(rig)) is True
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"], row["error"], row["finished_at"]) == ("queued", 0, QUEUED_AT, None, None), row
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1 and all(part in warnings[0] for part in ("[translate-worker]", "v-1", HOST, text)), warnings
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]  # not the catch-all
    assert rig.instance.opened == [] and rig.media.opened == []
```

`rig.claim()` runs before the lock is taken, because the claim writes `subtitles.db`, not the whitelist, so the order does not matter for the lock itself. Taking the lock after the claim keeps the hold to the busy wait alone. `setup_logging` is never called in-process, and pytest's caplog handler sits on the root logger at level 0, so WARNING and ERROR records are captured without `set_level`.

**Non-transient control**, two cases. One is injected; the other is a real zero-byte file, which raises `no such table: videos` from `fetch_video_row`.

```python
@pytest.mark.parametrize("case", ["injected no such column", "zero-byte file"])
def test_a_non_transient_whitelist_db_error_at_claim_still_ends_failed_with_its_text(rig, monkeypatch, caplog, case):
    if case == "zero-byte file":
        rig.whitelist.write_bytes(b"")
        lead = "OperationalError: no such table"
    else:
        monkeypatch.setattr(rig.worker, "resolve_video", _raising("no such column: video_uuid"))
        lead = "OperationalError: no such column"
    assert rig.run(StubRunner(rig)) is False
    row = rig.row()
    assert row["state"] == "failed" and row["error"].startswith(lead), row
    assert [record.exc_info is not None for record in caplog.records if record.levelno == logging.ERROR] == [True]  # the catch-all's logging.exception
    assert not [record for record in caplog.records if record.levelno == logging.WARNING]
```

**Recovery**, two cases. Both cases are fast; the real lock's own release is already shown by the existing stall test.

```python
@pytest.mark.parametrize("case", ["lock released", "file restored"])
def test_a_requeued_job_claimed_again_once_whitelist_db_is_usable_runs_to_ready(rig, monkeypatch, case):
    from data.subtitles import claim_translate_job

    if case == "lock released":
        monkeypatch.setattr(rig.worker, "resolve_video", _raising(LOCKED, then=rig.worker.resolve_video))
    else:
        rig.whitelist.unlink()
    assert rig.run(StubRunner(rig)) is True
    assert (rig.row()["state"], rig.row()["attempts"]) == ("queued", 0)  # control: requeued unspent
    if case == "file restored":
        _whitelist(rig.whitelist, JOB_VIDEOS, deny=True)
    rig.job = claim_translate_job(rig.conn, "en", STARTED_AT + 1)
    assert (rig.job["video_id"], rig.job["started_at"], rig.job["attempts"]) == ("v-1", STARTED_AT + 1, 1)
    assert rig.run(StubRunner(rig)) is False
    row = rig.row()
    assert (row["state"], row["source"], row["queued_at"]) == ("ready", "whisper", QUEUED_AT), row
```

The test reclaims through the store function directly. It does not call `Rig.claim` again, because that would enqueue a second time and fail its `("queued", "queued")` assert.

**Serve back-off**. It runs on a daemon thread over `rig.conn`, which `connect_subtitles_db` opens with `check_same_thread=False`. Setting `stop` from the test thread is safe because no signal handler is involved.

```python
def test_serve_waits_the_back_off_before_reclaiming_keeps_progress_fresh_and_a_stop_ends_the_wait(rig, monkeypatch):
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", SLICE_SECONDS)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", BACKOFF_SECONDS)
    locked = _raising(LOCKED)
    monkeypatch.setattr(rig.worker, "resolve_video", locked)
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    progress = {"at": time.monotonic()}
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, progress), daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(locked.calls) >= 2, 10 * BACKOFF_SECONDS)
        assert locked.calls[1] - locked.calls[0] >= BACKOFF_SECONDS, locked.calls  # the reclaim waited the back-off
        time.sleep(0.15)
        first = progress["at"]
        time.sleep(0.15)
        second = progress["at"]
        assert second > first and time.monotonic() - second < 0.3, (first, second)  # refreshed each slice during the wait
        assert len(locked.calls) == 2  # control: still inside the second back-off
        stopped_at = time.monotonic()
        stop.set()
        thread.join(5)
        assert not thread.is_alive() and time.monotonic() - stopped_at < 0.5  # well under the ~0.7 s left of the back-off
        assert len(locked.calls) == 2  # no claim after the stop
        row = rig.row()
        assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row
    finally:
        stop.set()
        thread.join(5)
```

The shortened `POLL_SECONDS` also reaches `AudioPipe.wait_samples` on this module instance. That does not matter here, because no job reaches the download.

**Module docstring**: add these to Outcomes.

- `whitelist.db` unavailable at claim: an injected `database is locked`, a removed file (`unable to open database file`) and a real EXCLUSIVE lock held through sqlite's 30 s busy wait each leave the job `queued` with `attempts` 0 and `queued_at` 1000, no `error` or `finished_at`, nothing requested, and one WARNING `[translate-worker] whitelist.db unavailable, requeued …` naming v-1, peer.example and the text, with no ERROR record. `run_job` returns True. An injected `no such column` and a zero-byte file (`no such table`) still end `failed` with `OperationalError: …` through the logged catch-all, and `run_job` returns False. Once the lock is released or the file rewritten, the requeued row claimed again (attempts 1) ends ready/whisper with `queued_at` still 1000.

Add a paragraph after the Job-pipeline paragraph:

- Serve back-off: `serve` runs in-process on a thread with `POLL_SECONDS` 0.05 s and `TRANSIENT_BACKOFF_SECONDS` 1 s on the loaded module, and `resolve_video` always locked. The second claim's lookup comes no sooner than 1 s after the first; `progress["at"]` advances during the wait; a stop set during the wait returns `serve` within 0.5 s with no further claim and the row `queued`, `attempts` 0.

### Documentation (current state, one paragraph per line)

`TRANSLATE_WORKER.md`:
- :33 `queued`: append "A job requeued by a stop or by an unavailable `whitelist.db` is `queued` again with its `attempts` restored and its `queued_at` kept."
- :39: "Every job ends in exactly one of `ready`, `already_english` or `failed`; on the way it may return to `queued` unspent (a stop, or `whitelist.db` unavailable at claim). A failed key is never queued again."
- :79 Serve Loop: append "After a job requeued because `whitelist.db` was unavailable, it waits `TRANSIENT_BACKOFF_SECONDS` (30 s) in 2 s slices before the next claim, recording progress each slice; a stop ends the wait within one slice."
- :83: "For a claimed job, in order, each bound ending the job `failed` before the next remote request (step 1 may instead return the job to `queued`):"
- :85 step 1: add a paragraph. When the lookup raises a sqlite `OperationalError` naming `locked`, `busy` or `unable to open` (the updater's merge holding the file past the 30 s busy timeout, or a restore that has removed it), the job goes back to `queued` with `attempts` restored and `queued_at` kept, and no `error` or `finished_at` is written. A warning is logged and the worker backs off about 30 s, which a stop ends promptly. Because the job keeps the head of the queue, the cycle repeats until the file is usable, and the job then runs as any other. Every other database error (`no such table`, `no such column`, `file is not a database`, `malformed`) fails the job as `<ExceptionType>: <text>`.
- :137: "`<ExceptionType>: <text>` for anything else, including CUDA out-of-memory".
- :141 SIGTERM: append "A stop during the back-off ends it within one 2 s slice; a stop during sqlite's 30 s busy wait on `whitelist.db` takes effect once that wait ends."
- :150 Heartbeat: "…on every serve pass, every back-off slice and every chunk-loop wake (at most 2 s apart; a `whitelist.db` busy wait records none for up to 30 s)…"
- :154: delete the bullet; the faster-whisper/VRAM bullet stays.
- Logs: add "`whitelist.db unavailable, requeued video_id=… host=…: <error>` (warning)" after the `stopped mid-job` line.

`DEPLOYMENT.md`:
- :353, replace with:

  `| A job stays `queued` and the journal repeats `whitelist.db unavailable, requeued video_id=… host=…: database is locked` (or `unable to open database file`), or `enqueue` prints `error: whitelist.db: database is locked` | The updater's merge holds `whitelist.db` past the 30 s busy timeout, or a restore has removed it. The worker requeues the job unspent and retries after a 30 s back-off; `enqueue` does not retry. A repeating `unable to open` with no restore in progress means the `--whitelist-db` path or its permissions are wrong | Nothing for the job: it runs once the merge or restore ends. Re-run `enqueue` after the updater run ends. Fix the path or permissions for a persistent `unable to open` |`
- :348 cause: append ", or `whitelist.db` is locked or missing (see the `whitelist.db unavailable` row below)".
- :264: "…puts the job back on the queue without counting a claim, or ends the back-off wait, waits up to…".

`CONTEXT.md`: not touched. The glossary entry already leaves out the stop requeue, the transient requeue is of the same kind, and the checklist marks it optional.

Delivery bookkeeping:
- issue 45: `Status: bug, complete`, the boxes ticked, the file moved to `archive/`;
- `issue-tracker.md` row 45: state `complete` and the link pointed at `archive/`;
- `roadmap.md:60`: "Requeue with back-off when `whitelist.db` is locked or missing at claim is delivered (see `TRANSLATE_WORKER.md`)."

`tests/tmp/probe_45_whitelist_locked_at_claim.py` now asserts the old behaviour. It is not collected, and the draft leaves it alone, as other `tests/tmp` probes are left.

### Check against plan and requirements (pass 1, converged)

- R1: the guard wraps only the `:422` call; the three words match case-insensitively; other errors are re-raised as-is, so the catch-all writes today's text; `command_enqueue` is untouched. ✓
- R2: the existing `requeue_translate_job`; no `error` or `finished_at`; one WARNING with the `[translate-worker]` prefix, the key and the text; ahead of the catch-all, so no OOM unload and no traceback; a False from the requeue writes nothing more. ✓
- R3: a named 30 s constant; a bool return from `run_job`; `time.sleep` in `POLL_SECONDS` slices with progress refreshed and `stop` checked each slice; repeats each cycle. ✓
- R4: the recovery test, through `claim_translate_job`, to `ready`. ✓
- R5: every bullet in the settled checklist is covered. ✓
- R6: injected, real missing file, real lock, serve timing, stop and progress, the control, recovery and the warning log; existing tests untouched (the stall test's ~16-26 s hold is still below 30 s). ✓

### Limits carried from the plan

- A stop during sqlite's busy wait still takes up to about 30 s.
- Head-of-line blocking while the file is unavailable.
- The model stays loaded through an outage: the idle unload is skipped. The upgrade path is to skip the `idle_since` reset and run the unload check inside the back-off loop.
- A mistyped `--whitelist-db` loops instead of failing; the `DEPLOYMENT.md` row names it.
- The suite grows by about 30 s for the real-lock case.

## 2026-10-03 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Requeue at claim on a transient whitelist.db error [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Seam: `run_job`, reached through the existing `Rig` harness in `tests/active/test_translate_worker.py` (`rig.claim()` then `rig.run(StubRunner(rig))`, `Rig.run` changed to return `run_job`'s result), the same entry the outcome tests at :799-852 use. Beyond that seam are a patched module-global `resolve_video` (`_raising`), a real whitelist file that is deleted, zero-byte or held under `BEGIN EXCLUSIVE` by a second connection, and `caplog` on the root logger. c1 is parametrized over injected lock, missing file and held EXCLUSIVE lock (~30 s). For each it asserts every member of the row tuple (state `queued`, attempts 0, queued_at `QUEUED_AT`, error None, finished_at None), exactly one WARNING whose message carries `[translate-worker]`, `v-1`, `HOST` and the error text, no record at ERROR or above, `rig.instance.opened == []` and `rig.media.opened == []`, and `run_job` returning `is True`. These exclude, respectively: a requeue that spends the attempt or rewrites queued_at, a branch that writes error or finished_at, a missing or duplicated log line or one that omits key or text, a branch placed after the catch-all, a guard that lets the job proceed to a remote request, and a return value serve cannot read. c2 is parametrized over injected `no such column` and a zero-byte file. It asserts state `failed` with error starting `OperationalError: no such column` / `OperationalError: no such table`, exactly one ERROR record carrying exc_info, no WARNING, and `run_job` returning `is False`, which excludes an over-broad predicate or a guard that rewraps every OperationalError.

**Intent.** In `translate-worker.py`, a job whose claim-time `resolve_video` call hits a locked, busy or unopenable `whitelist.db` is returned by `run_job` to `queued` with its claim unspent and one warning logged, instead of failing. Every other `whitelist.db` error at claim still fails the job with today's `OperationalError: <text>`.

- C1 - A locked, busy or unopenable `whitelist.db` at claim leaves the job `queued` with attempts restored, `queued_at` kept, no `error` or `finished_at`, nothing requested, and one warning naming the key and the error text, and `run_job` returns True.
- C2 - Any other `whitelist.db` error at claim still ends the job `failed` with `OperationalError: <text>` through the logged catch-all, and `run_job` returns False.

**Outcome.** _pending_

#### Phase 2 - Back off before the reclaim, then recover [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Two seams. (a) `serve`, entered in-process on a daemon thread over `rig.conn`, which is opened `check_same_thread=False`. On the loaded module, `POLL_SECONDS` is 0.05 and `TRANSIENT_BACKOFF_SECONDS` is 1.0, `resolve_video` is patched to always raise `database is locked` and record monotonic call times, and a StubRunner is used. No existing harness drives `serve` in-process, because the beat tests use the real CLI under a pty, so this is a new in-process entry and the drafted test function is its harness. For c1 it waits for two lookups, then asserts `calls[1] - calls[0] >= BACKOFF_SECONDS`, which excludes a serve that ignores the bool and reclaims on the next 0.05 s poll. It also asserts the row is still `queued` with attempts 0 and queued_at kept, which shows the reclaim is the same head job. (b) `run_job` via `Rig.run`, then a direct `claim_translate_job(rig.conn, "en", STARTED_AT + 1)`, parametrized over lock released (`_raising(LOCKED, then=real resolve_video)`) and file restored (unlink, then rewrite with `_whitelist`). For c2 it asserts the intermediate control (`queued`, 0), then that the reclaim is `v-1` with attempts 1, then a final row of `ready`, `whisper` and queued_at `QUEUED_AT`. This excludes a requeue that leaves the row unclaimable or a reclaimed run that fails or rewrites queued_at.

**Intent.** After a `whitelist.db` requeue, `serve` in `translate-worker.py` waits `TRANSIENT_BACKOFF_SECONDS` before claiming the same head job again, and once `whitelist.db` is usable that reclaimed job runs like any other.

- C1 - After a `whitelist.db` requeue, the next claim of the same head job comes no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first.
- C2 - Once the lock is released or the file restored, the requeued job claimed again runs to `ready` with its `queued_at` kept.

**Outcome.** _pending_

#### Phase 3 - Stay live during the back-off [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** The same in-process `serve` thread seam as phase 2, extending its serve test past the second lookup, while the worker is inside the second back-off. For c1 it samples `progress["at"]` twice, 0.15 s apart, and asserts the second sample is larger and less than 0.3 s old. This excludes a back-off that sleeps the whole deadline in one call or never touches progress, which would let the heartbeat go dark. A control asserts that `len(calls) == 2`, so the samples were taken during the wait and not during a fresh claim. For c2 it sets `stop` from the test thread, joins with a 5 s timeout, and asserts the thread is dead within 0.5 s, well under the ~0.7 s left of the back-off. It also asserts `len(calls)` is still 2, with no claim after the stop, and that the row is still `queued` with attempts 0. This excludes a loop that ignores `stop` until the deadline and one that claims once more before exiting. Setting `stop` off the main thread is safe here because no signal handler is involved.

**Intent.** The back-off wait in `serve` keeps the worker live: it refreshes `progress["at"]` every `POLL_SECONDS` slice and a stop ends it within one slice.

- C1 - During the back-off, `progress["at"]` keeps advancing at least once per slice.
- C2 - A stop set during the back-off makes `serve` return within about one slice without claiming again.

**Outcome.** _pending_


Needs coordination: none

Rationale: The split follows the order the code runs and the requirements. Phase 1 covers what `generate` and `run_job` do with a claim-time `whitelist.db` error (R1, R2), and its two clauses are the positive and negative halves of the classification. Phase 2 covers what happens next: the `serve` back-off (R3) and the recovery once the file is usable (R4). Phase 3 covers the liveness guarantees of the back-off loop: the heartbeat stays fresh and a stop is honoured. The phase 3 code is the same few lines of loop that phase 2 lands. Its clauses are kept separate because the serve behaviour holds four facts (wait, recover, progress, stop), and one phase carrying them would be drawn too wide; phase 3 extends phase 2's serve test rather than adding a new seam. The operator approved keeping the real-lock case and its ~30 s of suite time. Documentation (TRANSLATE_WORKER.md, DEPLOYMENT.md) and the issue/tracker/roadmap bookkeeping are not phases; Step 9 writes them from what was delivered. No credentials, live endpoints or manual steps are needed: every checkpoint runs in-process against temporary sqlite files.

## 2026-10-03 - Step 7 - Phase 1 (Requeue at claim on a transient whitelist.db error) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
In `translate-worker.py`, a job whose claim-time `resolve_video` call hits a locked, busy or unopenable `whitelist.db` is returned by `run_job` to `queued` with its claim unspent and one warning logged, instead of failing. Every other `whitelist.db` error at claim still fails the job with today's `OperationalError: <text>`.

- C1 - A locked, busy or unopenable `whitelist.db` at claim leaves the job `queued` with attempts restored, `queued_at` kept, no `error` or `finished_at`, nothing requested, and one warning naming the key and the error text, and `run_job` returns True.
- C2 - Any other `whitelist.db` error at claim still ends the job `failed` with `OperationalError: <text>` through the logged catch-all, and `run_job` returns False.

must_prove:
- C1 - A locked, busy or unopenable `whitelist.db` at claim leaves the job `queued` with attempts restored, `queued_at` kept, no `error` or `finished_at`, nothing requested, and one warning naming the key and the error text, and `run_job` returns True.
- C2 - Any other `whitelist.db` error at claim still ends the job `failed` with `OperationalError: <text>` through the logged catch-all, and `run_job` returns False.

## 2026-10-03 - Step 7 - Phase 1 (Requeue at claim on a transient whitelist.db error) - self-check (audit round 1, send-back 0)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_45_translate_worker_whitelist_locked_at_phase1.py:86 — `_job(rig) == ("queued", 0, QUEUED_AT, None, None)`: state, attempts, queued_at, error, finished_at read back through a fresh connection after run_job, for a deleted whitelist.db and for one held under BEGIN EXCLUSIVE past the 30 s busy timeout. Rig.claim's control has already shown attempts 1 and started_at 2000. - expected: ("queued", 0, 1000, None, None) for both cases. The current code instead gives ("failed", 1, 1000, "OperationalError: ...", <finished_at ms>), which is what the run showed at line 86 for both cases. - excludes: Today's catch-all, which fails the job: reads ("failed", 1, ...). A requeue that bumps queued_at or forgets to restore attempts (a plain UPDATE state='queued' and nothing else): reads attempts 1, or a queued_at that is not 1000. A fix that only catches "database is locked": reads ("failed", ...) in the missing-file case. One that only catches a missing file: reads ("failed", ...) in the held-lock case.
- C1 - test_45_translate_worker_whitelist_locked_at_phase1.py:88 and :90 — exactly one WARNING record, and its message contains "[translate-worker]", "v-1", "peer.example" and the error text the run produced ("unable to open database file" or "database is locked"). - expected: One WARNING per case. Its message carries the worker tag, both parts of the key, and the exact OperationalError text, which I took from the tracebacks of this run. - excludes: A silent requeue with no log, or an INFO-level log: 0 warnings. A warning logged both at the branch and again by a retry wrapper: 2 warnings. A warning reading "whitelist busy, requeued" that leaves out the key or the exception text: :90 fails.
- C1 - test_45_translate_worker_whitelist_locked_at_phase1.py:91 — no record at ERROR or above; :92 — rig.instance.opened == [] and rig.media.opened == []. - expected: [] for ERROR records. [] for both hosts. The :92 absence is armed by the control at :78, which saw INSTANCE_THEN_JSON and [MEDIA_URL] on the same rig with whitelist.db intact. The :91 absence is armed by :104, where caplog captured the catch-all's ERROR in this same run. - excludes: Requeuing from inside the catch-all after logging.exception: one ERROR record at :91. Treating a locked lookup as "not found" or "proceed without a row" and going on to fetch captions: the instance shows CAPTIONS_URL at :92.
- C1 - test_45_translate_worker_whitelist_locked_at_phase1.py:93 — `result is True`, where result is run_job's own return value, called directly. - expected: True. Today run_job returns None. Line 86 is the line the run stops on today; the assertion at :93 is never reached. - excludes: A requeue branch that falls through and returns None as run_job does today, or that returns False the way a failed job does: `None is True` / `False is True`.
- C2 - test_45_translate_worker_whitelist_locked_at_phase1.py:102 — (state, error) == ("failed", "OperationalError: <text>") for a videos table with video_uuid dropped (text "no such column: v.video_uuid") and for a zero-byte whitelist.db (text "no such table: videos"). - expected: ("failed", "OperationalError: no such column: v.video_uuid") and ("failed", "OperationalError: no such table: videos"). Both observed passing in this run, since this is today's behaviour, which the phase must keep. - excludes: A requeue branch that catches every sqlite3.OperationalError (or every sqlite3.Error): reads ("queued", None). Rewrapping the error as JobFailed("whitelist unavailable"): reads ("failed", "whitelist unavailable").
- C2 - test_45_translate_worker_whitelist_locked_at_phase1.py:104 and :105 — exactly one record at ERROR or above, at ERROR level, with exc_info[0] being sqlite3.OperationalError. :106 — no WARNING records. - expected: One ERROR record that carries the OperationalError traceback (logging.exception at translate-worker.py:473), and no WARNING. Both observed passing in this run. The :106 absence is armed by :88, which requires exactly one WARNING in the C1 cases. - excludes: Sending these through the new branch's logging.warning before failing: 1 WARNING at :106. Catching these in a narrower handler that calls logging.error without exc_info: exc_info None at :105. Logging the error twice: 2 ERROR records at :104.
- C2 - test_45_translate_worker_whitelist_locked_at_phase1.py:107 — `result is False`, where result is run_job's own return value. - expected: False. The run currently shows `assert None is False` at :107 in both cases, because run_job returns None today. - excludes: A run_job that returns only from the new branch and leaves the catch-all falling through: None. One that returns True for every handled exception: True.

<assertions>
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:74 — (state, attempts, queued_at, error, finished_at) == ("queued", 0, 1000, None, None) for an injected lock, a missing file and a held EXCLUSIVE lock. This rules out the old fail path (observed: 'failed', 1, 1000, 'OperationalError: …', <ms>), a requeue that spends the attempt or rewrites queued_at, and one that writes error or finished_at. — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:76 — exactly one WARNING record. This rules out a missing or duplicated log line (today there are 0). — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:78 — that warning's message contains `[translate-worker]`, `v-1`, `peer.example` and the observed error text (`database is locked` / `unable to open database file`). This rules out a line that leaves out the key, the host or the text. — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:79 — no record at ERROR or above. This rules out a branch placed after the catch-all and a catch-all that logs before requeueing (today there is one ERROR). — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:80 — rig.instance.opened == [] and rig.media.opened == []. This rules out a guard that lets the job go on to a remote request. — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:81 — the return of rig.run (that is, run_job) `is True`. This rules out a return value serve cannot read, and a None (today's value). — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:90 — (state, error) == ("failed", "OperationalError: no such column: video_uuid") for the injected case and ("failed", "OperationalError: no such table: videos") for the zero-byte file. This rules out an over-broad predicate that requeues these, and a guard that rewraps the text. — C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:92 — exactly one record at ERROR or above, and it is at ERROR. This rules out a rewrap that logs twice or at CRITICAL, and an exception that goes unlogged. — C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:93 — that record's exc_info is set and its type is sqlite3.OperationalError. This rules out a path that writes failed without going through the catch-all's logging.exception. — C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:94 — no WARNING record. This rules out the requeue branch's warning firing on a non-lock error. — C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:95 — the return of rig.run (that is, run_job) `is False`. This rules out None (today's value) and a True from an over-broad predicate. — C2
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/probe_45_phase1_scenarios.py"] (30.3 s wall). On the existing Rig fixture this claimed v-1, broke whitelist.db five ways, called worker.run_job directly with caplog at INFO, then printed the result, the row, every log record and the hosts' opened lists. It printed:
- injected `database is locked`: result None; row failed / attempts 1 / queued_at 1000 / error 'OperationalError: database is locked' / finished_at set; one ERROR record '[translate-worker] job error video_id=v-1 host=peer.example' with exc_info sqlite3.OperationalError; opened [] [].
- deleted file: same shape, error 'OperationalError: unable to open database file'.
- held under BEGIN EXCLUSIVE by a second connection: same shape after the ~30 s busy timeout, error 'OperationalError: database is locked'.
- injected `no such column: video_uuid`: same shape, error 'OperationalError: no such column: video_uuid'.
- zero-byte file: same shape, error 'OperationalError: no such table: videos'.
- Rig.run's return annotation is currently 'None', and no WARNING record appeared in any case.
Checkpoint run: ValidateTests ["tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py"] gave 5 failed (30.4 s). All three C1 cases fail at line 74 on ('failed', 1, …) != ('queued', 0, …). Both C2 cases get through lines 90–94 and fail only at line 95 (`assert None is False`), so the C2 row, ERROR and no-WARNING expectations are confirmed against real behaviour. Clean-up still needed: I have no delete tool, so tests/tmp/probe_45_phase1_scenarios.py is still on disk. It ends in `assert False`, so it should be deleted.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py` - 4960 characters, inlined in full

```
"""Issue 45, phase 1 checkpoint: `run_job` (through test_translate_worker.py's `Rig`, `rig.claim()` then `rig.run(StubRunner(rig))`) on a job whose claim-time `resolve_video` hits a broken whitelist.db.

- Locked or unopenable (an injected `database is locked`, a deleted file, a file held under `BEGIN EXCLUSIVE` past the 30 s busy timeout): the row is back to queued with attempts 0, queued_at 1000, no error and no finished_at; neither host saw a request; exactly one WARNING names `[translate-worker]`, the key and the error text, nothing is logged at ERROR; `run_job` returns True.
- Any other OperationalError (an injected `no such column`, a zero-byte file read as an empty database): the row ends failed with `OperationalError: <text>`, exactly one ERROR record carries the exception, no WARNING; `run_job` returns False.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import HOST, QUEUED_AT, StubRunner, clip, rig  # noqa: E402,F401

# (how whitelist.db is broken, the OperationalError text it raises); texts probed through run_job on this rig.
REQUEUED = {
    "injected lock": ("inject", "database is locked"),
    "missing file": ("delete", "unable to open database file"),
    "held EXCLUSIVE lock": ("hold", "database is locked"),
}
FAILED = {
    "injected no such column": ("inject", "no such column: video_uuid"),
    "zero-byte file": ("truncate", "no such table: videos"),
}


def _raising(exc: Exception):
    def resolve_video(*args: object, **kwargs: object) -> None:
        raise exc

    return resolve_video


def _break_whitelist(rig, monkeypatch: pytest.MonkeyPatch, how: str, text: str) -> sqlite3.Connection | None:
    """Break the rig's whitelist.db as `how` says; the holding connection when it is held, for the caller to close."""
    if how == "inject":
        monkeypatch.setattr(rig.worker, "resolve_video", _raising(sqlite3.OperationalError(text)))
    elif how == "delete":
        rig.whitelist.unlink()
    elif how == "truncate":
        rig.whitelist.write_bytes(b"")
    else:
        holder = sqlite3.connect(rig.whitelist, isolation_level=None)
        holder.execute("BEGIN EXCLUSIVE")
        return holder
    return None


def _run_broken(rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, how: str, text: str) -> object:
    caplog.set_level(logging.INFO)
    rig.claim()
    holder = _break_whitelist(rig, monkeypatch, how, text)
    try:
        return rig.run(StubRunner(rig))
    finally:
        if holder is not None:
            holder.close()


def _job(rig) -> tuple:
    row = rig.row()
    return row["state"], row["attempts"], row["queued_at"], row["error"], row["finished_at"]


@pytest.mark.parametrize("case", REQUEUED.values(), ids=REQUEUED.keys())
def test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true(rig, monkeypatch, caplog, case):
    how, text = case
    result = _run_broken(rig, monkeypatch, caplog, how, text)

    assert _job(rig) == ("queued", 0, QUEUED_AT, None, None)  # C1: claim unspent, queued_at kept, no error, no finished_at
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1, [record.getMessage() for record in warnings]  # C1: one warning, not none and not two
    message = warnings[0].getMessage()
    assert all(part in message for part in ("[translate-worker]", "v-1", HOST, text)), message  # C1: names the worker, the key and the error text
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR] == []  # C1: not routed through the catch-all
    assert rig.instance.opened == [] and rig.media.opened == []  # C1: nothing requested
    assert result is True  # C1


@pytest.mark.parametrize("case", FAILED.values(), ids=FAILED.keys())
def test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false(rig, monkeypatch, caplog, case):
    how, text = case
    result = _run_broken(rig, monkeypatch, caplog, how, text)

    row = rig.row()
    assert (row["state"], row["error"]) == ("failed", f"OperationalError: {text}"), row  # C2: today's failure, not requeued or rewrapped
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1 and errors[0].levelno == logging.ERROR, [record.getMessage() for record in errors]  # C2: one ERROR record
    assert errors[0].exc_info is not None and errors[0].exc_info[0] is sqlite3.OperationalError, errors[0].exc_info  # C2: the catch-all's logging.exception
    assert [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING] == []  # C2: the requeue branch's warning did not fire
    assert result is False  # C2

```


Gate: satisfied

## 2026-10-03 - Step 7 - Phase 1 (Requeue at claim on a transient whitelist.db error) - red (audit round 1)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py` exited 1.

```
  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py  4 failed, 1 passed                     0.0s
  ----------------------------------------------------------------
  total                                                             4 failed, 1 passed                    30.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 1 (Requeue at claim on a transient whitelist.db error) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
In both cases of the requeue test, the assertion at line 86 should fail before any other. Today `generate` lets the `resolve_video` OperationalError reach `run_job`'s catch-all, so `_job(rig)` reads `("failed", 1, 1000, "OperationalError: unable to open database file" / "OperationalError: database is locked", <finished_at>)` instead of `("queued", 0, 1000, None, None)`. The held-lock case reaches this only after the 30 s busy timeout. In both cases of the other-error test, lines 102–106 should hold today, and the test should fail at line 107 on `assert result is False`, because `run_job` returns `None`. The control test should pass.

NOT ASSESSED
1. `fixtures_path` was not supplied. I read the `rig` fixture, `Rig` and `StubRunner` from tests/active/test_translate_worker.py:432-549, where the test imports them. I did not read the `clip` fixture body past line 425 or the `_whitelist` and `_worker` helpers. Nothing in my answer to whether a stub would pass depends on them.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (38 clauses: 17 must_prove, 12 docstring, 9 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "locked" whitelist.db at claim requeues | :86 (held EXCLUSIVE case) | failing the job when another process holds a lock on the file; to a separate read-only reader that lock shows up only as "database is locked" | CARRIED |
| C1b | must_prove | "busy" whitelist.db at claim requeues | :86 (held EXCLUSIVE case, past the 30 s busy_timeout) | treating SQLITE_BUSY after the timeout as a hard failure | CARRIED |
| C1c | must_prove | "unopenable" whitelist.db at claim requeues | :86 (deleted file case) | sending "unable to open database file" through the catch-all as failed | CARRIED |
| C1d | must_prove | job left `queued` | :86 | leaving the row running or failed | CARRIED |
| C1e | must_prove | attempts restored | :86 (0, against 1 at claim per fixture :478) | requeueing without giving back the spent claim | CARRIED |
| C1f | must_prove | `queued_at` kept | :86 (QUEUED_AT 1000) | requeue that stamps queued_at with now | CARRIED |
| C1g | must_prove | no `error` | :86 | requeue that leaves an error text on the row | CARRIED |
| C1h | must_prove | no `finished_at` | :86 | requeue that stamps finished_at | CARRIED |
| C1i | must_prove | nothing requested | :92, paired with control :78 | swallowing the error and going on to fetch the instance or media | CARRIED |
| C1j | must_prove | one warning, exactly | :88 | no warning, or a warning per attempt/retry | CARRIED |
| C1k | must_prove | warning names the key | :90 ("v-1", HOST) | a warning that omits the video_id or host | CARRIED |
| C1l | must_prove | warning names the error text | :90 (text per case) | a generic warning that drops the sqlite message | CARRIED |
| C1m | must_prove | `run_job` returns True | :93 (`is True`) | returning None or a truthy non-bool | CARRIED |
| C2a | must_prove | "any other whitelist.db error" still fails, with no requeue | :102 over two cases (dropped column, zero-byte file) | requeueing every OperationalError, or treating an empty file as unopenable | CARRIED |
| C2b | must_prove | error is `OperationalError: <text>` | :102 (exact equality) | rewrapped, prefixed or truncated error text | CARRIED |
| C2c | must_prove | through the logged catch-all | :104, :105, :106 | routing through JobFailed (INFO, no exc_info) or through the requeue warning | CARRIED |
| C2d | must_prove | `run_job` returns False | :107 (`is False`) | returning None | CARRIED |
| D1 | docstring | run_job on a job claimed through Rig | :84 (rig.claim; fixture :478 asserts claimed once) | running on an unclaimed or twice-claimed job | CARRIED |
| D2 | docstring | "a deleted file, a file held under BEGIN EXCLUSIVE past the 30 s busy timeout" | :90 (text "database is locked" / "unable to open database file") | a break that never reached the error under claim | CARRIED |
| D3 | docstring | "back to queued with attempts 0, queued_at 1000, no error and no finished_at" | :86 | any one field wrong | CARRIED |
| D4 | docstring | "neither host saw a request" | :92 | fetching after the error | CARRIED |
| D5 | docstring | "exactly one WARNING names [translate-worker], the key and the error text" | :88, :90 | missing prefix, key or text, or a warning count other than one | CARRIED |
| D6 | docstring | "nothing is logged at ERROR" | :91 | also logging through logging.exception | CARRIED |
| D7 | docstring | "run_job returns True" | :93 | non-True return | CARRIED |
| D8 | docstring | other OperationalError "ends failed with OperationalError: <text>" | :102 | requeue, or a different error text | CARRIED |
| D9 | docstring | "exactly one ERROR record carries the exception" | :104, :105 | zero or two ERROR records, or none carrying exc_info | CARRIED |
| D10 | docstring | "no WARNING" | :106 | the requeue branch's warning also firing | CARRIED |
| D11 | docstring | "run_job returns False" | :107 | non-False return | CARRIED |
| D12 | docstring | control: intact whitelist reaches both hosts | :77, :78 | recorders that never record, which would make :92 empty by construction | CARRIED |
| N1 | name | "requeues the job" | :86 | not queued | CARRIED |
| N2 | name | "unspent" | :86 (attempts 0) | attempts left at 1 | CARRIED |
| N3 | name | "requests nothing" | :92 | any URL opened | CARRIED |
| N4 | name | "logs one warning" | :88 | warning count other than one | CARRIED |
| N5 | name | "returns true" | :93 | non-True return | CARRIED |
| N6 | name | "still fails the job" | :102 | requeue or another end state | CARRIED |
| N7 | name | "through the logged catch-all" | :104, :105 | JobFailed route with no exc_info | CARRIED |
| N8 | name | "returns false" | :107 | non-False return | CARRIED |
| N9 | name | control "intact whitelist reaches both hosts" | :78 | either recorder empty | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/active/../tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:24
   The only lock case holds the lock past the whole 30 s busy_timeout. Nothing tests a lock released inside the timeout, where the job should run on to `ready` instead of being requeued. That is the edge of the busy condition the requeue branch keys on.
2. bounds (rules/testing.md) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py:28
   FAILED covers only OperationalError. No case covers a malformed whitelist.db that raises a sqlite3.Error which is not an OperationalError, such as non-database bytes giving "file is not a database". C2 pins the error text to `OperationalError: <text>`, so this is outside must_prove. It is still the malformed-input edge of "any other whitelist.db error".

OBSERVATIONS
none

NOT ASSESSED
1. `fixtures_path` was not supplied. I read the `rig` and `clip` fixtures, `Rig` and `StubRunner` from tests/active/test_translate_worker.py:422-549, which is listed in `code_under_test`. I did not read `_worker()` (:212) or `_whitelist()` (:189). Whether `connect_readonly_db` gives a deleted file "unable to open database file" and not a freshly created empty database was taken from the test's own comment at :23. I did not trace it into data/db.

## 2026-10-03 - Step 7 - Phase 1 (Requeue at claim on a transient whitelist.db error) - checkpoint outcome (run 1)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/server/db/jobs/translate-worker.py`

- **New exception `WhitelistBusy`.** It sits next to `JobFailed`, `JobStopped` and `JobTakenOver` and subclasses `Exception` directly, so the `except JobFailed` branch never catches it.
- **`generate`.** Only the claim-time `resolve_video` call is wrapped, in `try/except sqlite3.OperationalError`.
  - If the lowercased error text contains `locked`, `busy` or `unable to open`, it raises `WhitelistBusy(str(exc)) from exc`.
  - Any other error is re-raised unchanged with a bare `raise`, so it still reaches the catch-all and ends the job `failed` with `OperationalError: <text>`.
  - The refusal check and every later step stay outside the `try`, so `subtitles.db` errors are never treated as transient.
  - The plan's separate `is_transient_db_error` predicate is written inline instead, because it has one caller.
  - The docstring now names the `WhitelistBusy` case.
- **`run_job`.**
  - The return type changes from `-> None` to `-> bool`.
  - A new `except WhitelistBusy as exc` branch comes right after `JobStopped`, ahead of the catch-all, so it never reaches `logging.exception` or the CUDA-OOM unload.
  - The branch calls the existing `requeue_translate_job(conn, *claim)`, which gives back the attempt and keeps `queued_at`. It logs one `logging.warning("[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s", ...)` with the error text, and returns True. It writes no `error` and no `finished_at`.
  - Every other path ends in a final `return False`.
  - The docstring now covers the transient requeue and the return value.
- **Not touched in this phase:** `serve` does not read the result yet, and the back-off constant is not added. Both belong to Phase 2.
- **Unchanged:** `resolve_video` and `command_enqueue`.

### `tests/active/test_translate_worker.py`

No change. The checkpoint calls `rig.worker.run_job` directly, so `Rig.run` did not need to return the value.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py  5 passed                               0.0s
  ----------------------------------------------------------------
  total                                                             5 passed                              30.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 2 (Back off before the reclaim, then recover) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
After a `whitelist.db` requeue, `serve` in `translate-worker.py` waits `TRANSIENT_BACKOFF_SECONDS` before claiming the same head job again, and once `whitelist.db` is usable that reclaimed job runs like any other.

- C1 - After a `whitelist.db` requeue, the next claim of the same head job comes no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first.
- C2 - Once the lock is released or the file restored, the requeued job claimed again runs to `ready` with its `queued_at` kept.

must_prove:
- C1 - After a `whitelist.db` requeue, the next claim of the same head job comes no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first.
- C2 - Once the lock is released or the file restored, the requeued job claimed again runs to `ready` with its `queued_at` kept.

## 2026-10-03 - Step 7 - Phase 2 (Back off before the reclaim, then recover) - self-check (audit round 1, send-back 0)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_45_translate_worker_whitelist_locked_at_phase2.py:73 — `lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS`: serve's second whitelist lookup (one per claim, at the start of `generate`) comes at least the back-off (1.0 s, set on the loaded module) after the first. Parametrized over an injected `database is locked` and a really deleted whitelist.db. The control at :72 shows two lookups happened within ten back-offs. - expected: Correct implementation: a gap of at least 1.0 s, because serve sleeps TRANSIENT_BACKOFF_SECONDS in POLL_SECONDS slices before the next claim. Current code, as run: gaps of 0.000156 s (injected lock) and 0.000181 s (missing file). - excludes: A serve that ignores run_job's True and reclaims at once, which is the code as it stands. The run read gaps of about 0.15–0.18 ms, so `assert (…762493296 - …762337015) >= 1.0` fails at :73. A back-off that waits only one POLL_SECONDS slice (0.05 s) also reads below 1.0. A back-off that binds the 30 s default instead of reading the module global fails the :72 control at 10 s.
- C1 - test_45_translate_worker_whitelist_locked_at_phase2.py:78 — `{call[1:] for call in lookups.calls} == {("v-1", HOST)}`: every lookup was v-1, never d-1, which is queued behind it at QUEUED_AT + 1. - expected: {("v-1", "peer.example")}. The run's recorded calls were all ('v-1', 'peer.example'). - excludes: A back-off that requeues by re-enqueueing (a fresh queued_at) or that skips the failed job and moves on. The next claim would then take d-1, and the set would include ("d-1", "denied.example").
- C1 - test_45_translate_worker_whitelist_locked_at_phase2.py:80 — after stop and join (the :77 control shows the thread ended), the row's (state, attempts, queued_at) == ("queued", 0, QUEUED_AT). - expected: ("queued", 0, 1000) - excludes: A back-off path that spends the attempt or rewrites queued_at (for example, it marks the row running or failed, or requeues with now_ms()). It would read attempts 1, state failed or running, or a queued_at other than 1000.
- C2 - test_45_translate_worker_whitelist_locked_at_phase2.py:97/:100/:101/:102 — after a run_job requeue (the :91 control reads queued/0/1000), with the lock released or the file rewritten, claim_translate_job returns v-1 with started_at STARTED_AT+1 and attempts 1. The reclaim then ends (state, source, queued_at, started_at, attempts, error) == ("ready", "whisper", 1000, 2001, 1, None) with cues CHUNK_1 + CHUNK_3, and the instance and media URLs are each requested once. - expected: The values as written. The run shows both cases passing against the current code; the operator exempted C2 from the red (see exemptions). - excludes: A requeue that leaves the row unclaimable, or a reclaim that fails or rewrites queued_at. The first gives claim_translate_job None; the second gives a state other than ready or a queued_at other than 1000. Phase 1 already rules both out, so this is a green regression guard at this checkpoint.

Exemptions the operator granted, verified against the agent's own transcript: C2

<assertions>
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:72 - the second whitelist lookup comes at least BACKOFF_SECONDS (1.0, set on the module as TRANSIENT_BACKOFF_SECONDS) after the first. It runs for an injected `database is locked` and for a deleted file that raises the real error. Excludes today's serve, which ignores run_job's True and reclaims at once: run against today's code with the constant supplied, this line failed with a gap of about 0.2 ms. - C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:71 - control: the second lookup arrives within 10 s, ten back-offs. Excludes a serve that never reclaims, or one that waits a hard-coded 30 s instead of reading TRANSIENT_BACKOFF_SECONDS from the module. - C1 (control)
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:77 - every recorded lookup is ("v-1", HOST), while d-1 is queued behind it at QUEUED_AT + 1. Excludes a requeue that lost v-1's place at the head, which would make the reclaim look up d-1. - C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:79 - after stop and join, the v-1 row reads ("queued", 0, QUEUED_AT). Excludes a back-off that spends the claim or rewrites queued_at, which would mean the next claim is not of the same head job. - C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:76 - control: the serve thread has returned, so the row read at :79 is not caught mid-claim. - C1 (control)
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:90 - control: after the first run_job, the row is ("queued", 0, QUEUED_AT), so what follows is a reclaim of a requeued job. Runs for both the lock-released and the file-restored case. - C2 (control)
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:96 - claim_translate_job(rig.conn, "en", STARTED_AT + 1) returns v-1 on HOST with started_at 2001 and attempts 1. Excludes a requeue that leaves the row unclaimable, which would return None, or one that spent the attempt, which would give attempts 2. - C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:99 - the final row is ("ready", "whisper", QUEUED_AT, STARTED_AT + 1, 1, None) for state, source, queued_at, started_at, attempts and error. Excludes a reclaimed run that fails or is requeued again, and one that rewrites queued_at. - C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:100 - the final cues_json is CHUNK_1 + CHUNK_3, the four absolute-ms cues the stub runner produces on any normal job. Excludes a reclaim marked ready without transcribing. - C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:101 - the instance saw INSTANCE_THEN_JSON and the media host saw [MEDIA_URL], each once in total across both runs. Excludes a first run that requested anything and a reclaim that skipped the pipeline. - C2
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/probe_45_phase2_serve.py", "-s", "-q"] (first version of the probe). serve ran on a thread for 1.5 s with POLL_SECONDS 0.05, v-1 queued at 1000 and d-1 at 1001. Output: `module has TRANSIENT_BACKOFF_SECONDS: False`. With injected `database is locked` there were 26140 lookups, every key ('v-1', 'peer.example'), first gaps [0.0002, 0.0001, ...]. With a deleted whitelist.db and the real resolve_video wrapped there were 17874 lookups, each raising `OperationalError: unable to open database file`, with the same gaps. After stop, both rows read state queued, attempts 0, queued_at 1000, error None, finished_at None. Recovery with a deleted file: after the requeue the row read queued, attempts 0, queued_at 1000, started_at 2000. After the file was rewritten, claim_translate_job(conn, "en", 2001) returned v-1 on peer.example with started_at 2001 and attempts 1. The run then gave state ready, source whisper, attempts 1, queued_at 1000, started_at 2001, error None, cues equal to CHUNK_1 + CHUNK_3, instance URLs [captions, video JSON] and media [MEDIA_URL].
Command: ValidateTests ["tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py"]: 2 failed, 2 passed. Both C1 cases fail at :58 with `AttributeError: <module 'translate_worker'> has no attribute 'TRANSIENT_BACKOFF_SECONDS'`, because monkeypatch.setattr raises on a missing attribute. Both C2 cases pass.
Command: ValidateTests ["tests/tmp/probe_45_phase2_serve.py"] (second version). It supplied TRANSIENT_BACKOFF_SECONDS with raising=False, then called the checkpoint's C1 function against today's serve. Both cases failed at checkpoint :72 with `assert (1656128.26411943 - 1656128.263922303) >= 1.0`, a gap of about 0.2 ms, so the C1 assertion itself rejects today's behaviour.
Note: I could not delete tests/tmp/probe_45_phase2_serve.py, because I have no delete tool. It is a probe_* file, so the suite does not collect it, like the other probes left in tests/tmp. It should be removed by hand.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py` - 6287 characters, inlined in full

```
"""Issue 45, phase 2 checkpoint: `serve` backs off after a whitelist.db requeue, and the requeued job runs once whitelist.db is usable.

- Back-off: `serve` runs in-process on a daemon thread over the rig's connection with `POLL_SECONDS` 0.05 and `TRANSIENT_BACKOFF_SECONDS` 1.0 on the loaded module, v-1 queued at 1000 and d-1 queued behind it. Its whitelist lookup fails every time, either from an injected `database is locked` or from a deleted file (the real `unable to open database file`), and a recorder notes when each lookup happens and its key. The second lookup comes at least 1.0 s after the first, and both are for v-1. After a stop the row is back to queued with attempts 0 and queued_at 1000.
- Recovery: a job requeued by `run_job` is first seen queued with attempts 0. When the lock is released (one injected `database is locked`, then the real lookup) or the deleted file is rewritten, `claim_translate_job` hands back v-1 with attempts 1. That run ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1, the four transcribed cues, and the instance and media URLs each requested once.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import CHUNK_1, CHUNK_3, DENIED_HOST, HOST, INSTANCE_THEN_JSON, JOB_VIDEOS, MAX_DURATION, MEDIA_URL, QUEUED_AT, STARTED_AT, StubRunner, _whitelist, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, enqueue_translate_job  # noqa: E402

LOCKED = "database is locked"
# Shortened on the loaded module; without a back-off serve was probed reclaiming about 0.1 ms after each requeue.
BACKOFF_SECONDS = 1.0
SLICE_SECONDS = 0.05
# Ten back-offs: a serve still waiting the 30 s default, not the module's value, misses it.
LOOKUP_WAIT_SECONDS = 10 * BACKOFF_SECONDS


def _recording(resolve, locked_calls: int | None):
    """A resolve_video stand-in noting (monotonic time, video_id, host) per call; it raises `database is locked` for the first `locked_calls` calls (None: every call) and otherwise calls `resolve`."""
    calls: list[tuple[float, str, str]] = []

    def recorded(whitelist_path, video_id, host, max_duration):
        calls.append((time.monotonic(), video_id, host))
        if locked_calls is None or len(calls) <= locked_calls:
            raise sqlite3.OperationalError(LOCKED)
        return resolve(whitelist_path, video_id, host, max_duration)

    recorded.calls = calls
    return recorded


def _until(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.mark.parametrize("injected", [True, False], ids=["injected lock", "missing file"])
def test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job(rig, monkeypatch, injected):
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", SLICE_SECONDS)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", BACKOFF_SECONDS)
    lookups = _recording(rig.worker.resolve_video, locked_calls=None if injected else 0)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    if not injected:
        rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    # Queued behind v-1, so a requeue that lost v-1's place at the head would show as a d-1 lookup.
    assert tuple(enqueue_translate_job(rig.conn, "d-1", DENIED_HOST, "en", 50, QUEUED_AT + 1)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, {"at": time.monotonic()}), daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(lookups.calls) >= 2, LOOKUP_WAIT_SECONDS), lookups.calls  # control: serve reclaimed within ten back-offs
        assert lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS, lookups.calls  # C1: no sooner than the back-off after the first
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()  # control: serve returned, so the row below is at rest
    assert {call[1:] for call in lookups.calls} == {("v-1", HOST)}, lookups.calls  # C1: every lookup was the head job, never d-1
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row  # C1: the same head job, requeued unspent at its place


@pytest.mark.parametrize("case", ["lock released", "file restored"])
def test_a_job_requeued_on_whitelist_db_claimed_again_once_it_is_usable_runs_to_ready_with_its_queued_at_kept(rig, monkeypatch, case):
    if case == "lock released":
        monkeypatch.setattr(rig.worker, "resolve_video", _recording(rig.worker.resolve_video, locked_calls=1))
    else:
        rig.whitelist.unlink()
    rig.run(StubRunner(rig))
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row  # control: requeued unspent, so what follows is a reclaim
    if case == "file restored":
        _whitelist(rig.whitelist, JOB_VIDEOS, deny=True)

    rig.job = claim_translate_job(rig.conn, "en", STARTED_AT + 1)

    assert rig.job is not None and (rig.job["video_id"], rig.job["instance_domain"], rig.job["started_at"], rig.job["attempts"]) == ("v-1", HOST, STARTED_AT + 1, 1), rig.job and dict(rig.job)  # C2: the requeued row is claimable again
    rig.run(StubRunner(rig))
    row = rig.row()
    assert (row["state"], row["source"], row["queued_at"], row["started_at"], row["attempts"], row["error"]) == ("ready", "whisper", QUEUED_AT, STARTED_AT + 1, 1, None), row  # C2: the reclaim ran to ready, queued_at kept
    assert json.loads(row["cues_json"]) == CHUNK_1 + CHUNK_3  # C2: transcribed like any other job
    assert rig.instance.opened == INSTANCE_THEN_JSON and rig.media.opened == [MEDIA_URL]  # C2: the whole pipeline once, on the reclaim only

```


Gate: satisfied

## 2026-10-03 - Step 7 - Phase 2 (Back off before the reclaim, then recover) - red (audit round 1)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py` exited 1.

```
  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py  2 failed, 2 passed                     0.0s
  ----------------------------------------------------------------
  total                                                             2 failed, 2 passed                     0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 2 (Back off before the reclaim, then recover) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D10

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. single-value-pin (rules/shape.md) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:26, :29, :73
   BACKOFF_SECONDS = 1.0
   assert lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS, lookups.calls
   The test runs the back-off at one value only, and 1.0 is the only back-off value in the file. That matches the entry's first `<how_to_spot>` bullet. The 10-back-off ceiling at :29/:72 does catch a serve that ignores the patched constant and waits a default of 10 s or more, which follows the entry's own `<alternatives>` ("an expected value that differs from every default the code already ships"). Some wrong implementations still pass: a serve that hard-codes any back-off from 1 s up to 10 s, or one that binds the constant when the function is defined so the monkeypatch at :59 never reaches it, as long as that default is under 10 s. The "30 s default" in the :28 comment cannot be checked yet because `TRANSIENT_BACKOFF_SECONDS` does not exist in translate-worker.py. Running the observable at a second patched value (e.g. 2.0) and asserting the gap follows it would close this. Not raised to Critical, because the rule's own alternative is partly met.

2. EXEMPT C2: (rules/shape.md, stub question) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84–102
   rig.job = claim_translate_job(rig.conn, "en", STARTED_AT + 1)
   As the builder concedes, this test passes against the current code. That is the conceded kind, so it is reported here and does not block. But the builder's reason says the test guards recovery "at both the run_job and serve seams", and it never calls `serve`. It drives `rig.run` (`run_job`) and calls `claim_translate_job` directly at :95. A phase-2 back-off placed in `serve`'s loop, which is where :56–:80 expects it, is never run by this test. So the test cannot fail if that back-off breaks recovery, and the "regression guard" reason only holds for a back-off built into `run_job` or the store. If the back-off is built into the store as a claim-time not-before, :95 claims at a synthetic 2001 ms. A correct implementation could then return None there and turn :97 red for the wrong reason.

PREDICTED FAILURE
Both parametrizations of `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` should fail at line 73 on `lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS`. `serve` ignores `run_job`'s True return and reclaims the requeued v-1 straight away, so the second lookup comes milliseconds after the first, not 1.0 s later. The line-72 control passes first. Both cases of `test_a_job_requeued_on_whitelist_db_...` are expected to pass (C2 is exempted).

NOT ASSESSED
1. `fixtures_path` was given as "none found". The `rig` and `clip` fixtures, `StubRunner` and `_whitelist` are imported from tests/active/test_translate_worker.py, which was read as part of `code_under_test`. No conftest was needed.
2. The shipped default of `TRANSIENT_BACKOFF_SECONDS` could not be checked because the constant does not exist yet in engine/server/db/jobs/translate-worker.py. Recommendation 1 relies on the 30 s default stated in the comment at :28.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 4 must_prove, 10 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "after a `whitelist.db` requeue", for both a lock and a missing file | :80 | a failed lookup that fails the job or spends its attempt instead of requeueing it unspent | CARRIED |
| C1b | must_prove | "the next claim ... no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first" | :73 (with :72 as its ceiling) | a `serve` that reclaims about 0.1 ms after the requeue. The :72 control also excludes a `serve` that ignores the module value and waits the 30 s default. The gap is measured between lookups, not between claims (see Recommendation 1) | CARRIED |
| C1c | must_prove | "of the same head job" | :78, :80 | a requeue that loses v-1's place, which would show as a d-1 lookup; a row that does not end back at `queued_at` 1000 | CARRIED |
| C2 | must_prove | once usable, the requeued job is claimed again and runs to `ready` with `queued_at` kept | :97, :100 | not claimable again; a different `queued_at`; a non-ready end (carried at the `run_job` seam, not through `serve`) | EXEMPT |
| D1 | docstring | "lookup fails every time, either from an injected `database is locked` or from a deleted file" | :80 (parametrized at :55) | a missing file classed as a job failure: the row would end `failed`, not `queued` | CARRIED |
| D2 | docstring | "The second lookup comes at least 1.0 s after the first" | :73 | an immediate re-lookup | CARRIED |
| D3 | docstring | "both are for v-1" | :78 | a d-1 lookup | CARRIED |
| D4 | docstring | "After a stop the row is back to queued with attempts 0 and queued_at 1000" | :77, :80 | a spent attempt; a changed `queued_at`; a row read while `serve` is still running | CARRIED |
| D5 | docstring | "a job requeued by `run_job` is first seen queued with attempts 0" | :91 | a lock or missing file that fails the job, or a requeue that keeps the attempt | CARRIED |
| D6 | docstring | "`claim_translate_job` hands back v-1 with attempts 1" | :97 | a row that is not reclaimable; a different head; an attempts count that keeps growing | CARRIED |
| D7 | docstring | "ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1" | :100 | a reset `queued_at`; a stale `started_at`; an error left on the row | CARRIED |
| D8 | docstring | "the four transcribed cues" | :101 | a missing or partial cue list | CARRIED |
| D9 | docstring | "instance and media URLs each requested once" | :102 | a pipeline that also ran on the locked or missing-file attempt | CARRIED |
| D10 | docstring | "guards recovery against a back-off that breaks it" | none | the recovery test never runs `serve` (:89 and :98 call `run_job`, :95 calls `claim_translate_job` directly), so a back-off in `serve` that blocks recovery passes it | UNCARRIED |
| N1 | name | "serve waits the back-off" | :73 | an immediate reclaim by `serve` | CARRIED |
| N2 | name | "its next lookup of the same head job" | :78 | a lookup of d-1 | CARRIED |
| N3 | name | "a job requeued on whitelist.db" | :91 | a fail or a spent attempt instead of a requeue | CARRIED |
| N4 | name | "claimed again once it is usable" | :97 | a job that cannot be reclaimed after recovery | CARRIED |
| N5 | name | "runs to ready with its queued_at kept" | :100 | a non-ready end; a changed `queued_at` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73
   C1 says when the next *claim* happens. :73 measures when the next whitelist *lookup* happens, from the `resolve_video` recorder. A lookup always comes at or after its claim, so the lookup gap only bounds the claim gap from one side. One wrong implementation passes: a `serve` that reclaims at once (row `running`, new `started_at`) and then waits the back-off before the lookup. :80 does not catch it, because the requeue still gives the attempt back. The test name (:56) also says "lookup" where `must_prove` says "claim". Recording when `claim_translate_job` is called on the loaded module would carry the clause as written. It is CARRIED because :73 does exclude the immediate-reclaim defect.
2. whole-claim (rules/testing.md) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:4
   D10 is UNCARRIED. The docstring says the recovery test "guards recovery against a back-off that breaks it". The back-off under test lives in `serve` (C1 drives `serve` at :69), but the recovery test only calls `rig.run` → `run_job` (:89, :98) and `claim_translate_job` (:95) directly. Example of a regression it would miss: a `serve` that keeps backing off v-1 after `whitelist.db` is usable again. Either narrow the sentence or drive recovery through `serve`. This is a docstring row on a first audit, so it does not block.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:56
   The back-off is only tested on the path where it should fire, after a `whitelist.db` requeue. Nothing shows that `serve` claims the next job without a back-off when the previous job ended normally (`ready` or `failed`). So a back-off applied after every job passes this file. No `must_prove` clause names that path.

OBSERVATIONS
1. clause_map (C2 exemption) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84
   The builder's reason for the exemption says the recovery test passes "at both the run_job and serve seams". In this file it enters only `run_job` and `claim_translate_job`; `serve` is never run in the recovery test (:89, :95, :98). The exemption covers the red, and the operator decided it, so this does not block. But the guard it describes does not cover the seam where the phase-2 back-off lives (see D10).

NOT ASSESSED
1. `fixtures_path` was not supplied. The `rig` and `clip` fixtures, `Rig.run`, `Rig.row` and `StubRunner` were read from tests/active/test_translate_worker.py (:423–:549), which the test imports at :20. No conftest was located.
2. engine/server/data/db.py `connect_readonly_db` was not read. D1's missing-file case was judged from :80 only: a row ending `queued` rather than `failed` shows the error was classed as transient. Which error text the missing file produces was not checked.

## 2026-10-03 - Step 7 - Phase 2 (Back off before the reclaim, then recover) - self-check (audit round 2, send-back 0)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73: the second whitelist lookup comes at least BACKOFF_SECONDS (1.0, set on the module as TRANSIENT_BACKOFF_SECONDS) after the first. It runs for an injected lock and for a deleted file. The control at :72 bounds the wait at 10 s. :78 asserts every lookup is ("v-1", HOST), and :80 asserts the row after stop is ("queued", 0, QUEUED_AT). - expected: A gap of 1.0 s or more between the first and second lookup. Every lookup is for v-1 on HOST. The row ends queued with attempts 0 and queued_at 1000. - excludes: Today's `serve` ignores run_job's True and reclaims at once. When I ran it with the constant supplied, the gap was about 0.2 ms, and :73 failed. A requeue that lost v-1's place would show ("d-1", DENIED_HOST) at :78. A back-off that spent the attempt or rewrote queued_at would read attempts 1 or a different queued_at at :80.
- C2 - tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:97 and :100. At :97, claim_translate_job returns v-1 on HOST with started_at STARTED_AT + 1 and attempts 1. At :100, the final row is ("ready", "whisper", QUEUED_AT, STARTED_AT + 1, 1, None). Both run for "lock released" and for "file restored". - expected: At :97, ("v-1", HOST, 2001, 1). At :100, ("ready", "whisper", 1000, 2001, 1, None). - excludes: A requeue that leaves the row unclaimable makes claim_translate_job return None, which fails :97. One that spent the attempt reads attempts 2. A reclaim that fails, is requeued again or rewrites queued_at reads something other than ready/1000 at :100. This is carried at the run_job seam and not through serve. The operator exempted C2 from the red on an earlier round.

Exemptions the operator granted, verified against the agent's own transcript: C2

<items>
<item id="D10">
<disposition>justified</disposition>
<what>I narrowed the docstring sentence to what the test asserts. Line 4 no longer says the recovery test "guards recovery against a back-off that breaks it". It now says: "Phase 1 already delivered this, so it is green before phase 2 (C2 exempted from the red by the operator). It drives `run_job` and `claim_translate_job` directly and never runs `serve`, so it checks recovery at those seams only, not past a back-off in `serve`'s loop." The docstring no longer claims a guard the test does not give. It names the seams the test enters (:89, :95, :98) and states the gap the audit found: a `serve` that keeps backing off v-1 once whitelist.db is usable again. I made no other change.</what>
</item>
</items>

<findings_addressed>
Neither auditor raised a CRITICAL. Claim Recommendation 2 (D10): taken. I narrowed the docstring at :4 to say the recovery test enters only `run_job` and `claim_translate_job` and does not cover a back-off in `serve`'s loop. Claim Observation 1 and shape Recommendation 2 (the C2 reason saying "both the run_job and serve seams"): the same edit fixes the docstring's account of what the test guards. Claim Recommendations 1 and 3 and shape Recommendation 1: not taken this round, because they do not block and the ledger does not name them.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73: the second whitelist lookup comes at least BACKOFF_SECONDS (1.0, set on the module as TRANSIENT_BACKOFF_SECONDS) after the first. It runs for an injected lock and for a deleted file. The control at :72 bounds the wait at 10 s. :78 asserts every lookup is ("v-1", HOST), and :80 asserts the row after stop is ("queued", 0, QUEUED_AT).</assertion>
<expected>A gap of 1.0 s or more between the first and second lookup. Every lookup is for v-1 on HOST. The row ends queued with attempts 0 and queued_at 1000.</expected>
<wrong_implementation>Today's `serve` ignores run_job's True and reclaims at once. When I ran it with the constant supplied, the gap was about 0.2 ms, and :73 failed. A requeue that lost v-1's place would show ("d-1", DENIED_HOST) at :78. A back-off that spent the attempt or rewrote queued_at would read attempts 1 or a different queued_at at :80.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:97 and :100. At :97, claim_translate_job returns v-1 on HOST with started_at STARTED_AT + 1 and attempts 1. At :100, the final row is ("ready", "whisper", QUEUED_AT, STARTED_AT + 1, 1, None). Both run for "lock released" and for "file restored".</assertion>
<expected>At :97, ("v-1", HOST, 2001, 1). At :100, ("ready", "whisper", 1000, 2001, 1, None).</expected>
<wrong_implementation>A requeue that leaves the row unclaimable makes claim_translate_job return None, which fails :97. One that spent the attempt reads attempts 2. A reclaim that fails, is requeued again or rewrites queued_at reads something other than ready/1000 at :100. This is carried at the run_job seam and not through serve. The operator exempted C2 from the red on an earlier round.</wrong_implementation>
</row>
</rows>

<answers>
1. No. The only negative-leaning check is :78, that d-1 is never looked up. Its positive controls are :72 (at least two lookups happened) and the set equality itself: an empty set fails against {("v-1", HOST)}.
2. No. Nothing is compared to itself. :73 compares two recorded timestamps against a constant the test sets. Deleting the back-off wait that phase 2 adds to `serve` turns it red; today's code shows that, with a measured 0.2 ms gap.
3. Partly, and I left it as is. The back-off runs at one patched value (shape Recommendation 1). The 10x ceiling at :72 rules out a serve that ignores the constant and waits 10 s or more. A second patched value would close the rest. It is a recommendation, it does not block, and the ledger does not name it, so I did not rewrite it this round.
4. No. `resolve_video` is wrapped by a recorder. In the missing-file case it calls straight through to the real function. In the lock case the recorder raises the real sqlite3 error that the lock produces. StubRunner stands in for the external transcription runner, a layer outside this project. The store and `serve` are real.
5. Yes, it collects. My only edit this round is docstring text on one line, so imports, names and line numbers are unchanged. The test count is still 4: 2 parametrized cases in each of the 2 tests.
6. Yes. The real error text for the missing file, the 0.1–0.2 ms reclaim gap, the requeued row values and the recovery row, cues and URLs all come from the earlier probe runs recorded in my previous reply.
7. Yes. The edit touched prose only. The C1 cases still fail at :73 on the timing, because `raising=False` at :59 lets setup reach serve. The C2 cases still pass under the operator's exemption.
</answers>

<exemptions>
none
</exemptions>

Gate: satisfied

## 2026-10-03 - Step 7 - Phase 2 (Back off before the reclaim, then recover) - red (audit round 2)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py` exited 1.

```
  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py  2 failed, 2 passed                     0.0s
  ----------------------------------------------------------------
  total                                                             2 failed, 2 passed                     0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 2 (Back off before the reclaim, then recover) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. EXEMPT C2: stub question (rules/shape.md, Recommendation per the exemption). Applies to tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:84–102. Test 2 (lines 84–102) calls `run_job` and `claim_translate_job` directly and never runs `serve`. Phase 1's `run_job` WhitelistBusy branch already does the requeue (translate-worker.py:474–478), so lines 91, 97, 100, 101 and 102 pass against the code as it stands, and they would also pass against a phase-2 stub that changed nothing. The builder concedes this. The exemption looks right. The assertions sit at rung 1, use independent literals, and include a positive control (line 91), so the test is sound as a regression guard. It cannot catch a phase-2 back-off in `serve` that breaks recovery, because it never enters `serve`. The test's docstring says this itself.
2. single-value-pin (rules/shape.md): no rule finding; this is a residual gap. Applies to tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:59, :72 and :73. The back-off is tested at only one value, `BACKOFF_SECONDS = 1.0`.
   - Line 72's ten-back-off cap means a `serve` that ignores the patched constant and waits the shipped default fails. Waiting with `POLL_SECONDS` or not waiting at all also fails. This is the entry's second `<alternatives>` bullet.
   - The gap: a `serve` that hard-codes any literal wait between 1 s and 10 s still passes, because nothing checks that the wait follows `TRANSIENT_BACKOFF_SECONDS`.
   - Fix: add a second value (for example 2.0) and check that the gap between lookups tracks it.
   
   This is not Critical: the plausible wrong implementations all fail, and the expected value is not the shipped default.

PREDICTED FAILURE
Fails at line 73 (`lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS`) in both the "injected lock" and "missing file" cases. `serve` (translate-worker.py:509–527) goes straight back into `claim_translate_job` after `run_job` returns True from the WhitelistBusy requeue. So the second v-1 lookup comes well under 1.0 s after the first, roughly the 0.1 ms the comment at line 25 records. Test 2 (lines 84–102) stays green; that is the exempted C2.

NOT ASSESSED
1. `fixtures_path` was not supplied. The `rig` fixture, `Rig.run`, `Rig.row`, `StubRunner` and `_whitelist` were read from tests/active/test_translate_worker.py (lines 432–549). `clip` and the module loader `_worker` (around line 173) were not read in full.
2. I did not read `connect_readonly_db` or `data.subtitles` (`claim_translate_job`, `requeue_translate_job`, `enqueue_translate_job`). Two things are taken from the test's docstring and the comment at translate-worker.py:429, not confirmed in source:
   - that deleting the whitelist file makes `resolve_video` raise "unable to open database file" rather than creating an empty file;
   - that the requeue keeps `attempts` 0 and `queued_at`.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 4 must_prove, 10 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "after a `whitelist.db` requeue", for both a lock and a missing file | :80 (parametrized at :55) | a failed lookup that fails the job or uses up its attempt instead of requeueing it with the attempt unused | CARRIED |
| C1b | must_prove | "the next claim ... no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first" | :73 (with :72 as its ceiling) | a `serve` that reclaims right after the requeue (the loop at translate-worker.py:512–527 goes straight back to `claim_translate_job` after `run_job`). The :72 control also excludes a `serve` that ignores the module value and waits the 30 s default. The gap is measured between lookups, not between claims | CARRIED |
| C1c | must_prove | "of the same head job" | :78, :80 | a requeue that loses v-1's place, which would show up as a d-1 lookup; a row that does not end back at `queued_at` 1000 | CARRIED |
| C2 | must_prove | once usable, the requeued job is claimed again and runs to `ready` with `queued_at` kept | :97, :100 | not claimable again; a different `queued_at`; an end state other than ready (checked at the `run_job` seam, not through `serve`) | EXEMPT |
| D1 | docstring | "lookup fails every time, either from an injected `database is locked` or from a deleted file" | :80 (parametrized at :55, :60, :63) | a missing file treated as a job failure: the row would end `failed`, not `queued` | CARRIED |
| D2 | docstring | "The second lookup comes at least 1.0 s after the first" | :73 | an immediate re-lookup | CARRIED |
| D3 | docstring | "both are for v-1" | :78 | a d-1 lookup | CARRIED |
| D4 | docstring | "After a stop the row is back to queued with attempts 0 and queued_at 1000" | :77, :80 | an attempt used up; a changed `queued_at`; a row read while `serve` is still running | CARRIED |
| D5 | docstring | "a job requeued by `run_job` is first seen queued with attempts 0" | :91 | a lock or missing file that fails the job, or a requeue that keeps the attempt counted | CARRIED |
| D6 | docstring | "`claim_translate_job` hands back v-1 with attempts 1" | :97 | a row that cannot be reclaimed; a different head job; an attempts count that keeps growing | CARRIED |
| D7 | docstring | "ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1" | :100 | a reset `queued_at`; a stale `started_at`; an error left on the row | CARRIED |
| D8 | docstring | "the four transcribed cues" | :101 | a missing or partial cue list | CARRIED |
| D9 | docstring | "instance and media URLs each requested once" | :102 | a pipeline that also ran on the locked or missing-file attempt | CARRIED |
| D10 | docstring | withdrawn | n/a | n/a | CARRIED |
| N1 | name | "serve waits the back-off" | :73 | an immediate reclaim by `serve` | CARRIED |
| N2 | name | "its next lookup of the same head job" | :78 | a lookup of d-1 | CARRIED |
| N3 | name | "a job requeued on whitelist.db" | :91 | a failed job or a used-up attempt instead of a requeue | CARRIED |
| N4 | name | "claimed again once it is usable" | :97 | a job that cannot be reclaimed after recovery | CARRIED |
| N5 | name | "runs to ready with its queued_at kept" | :100 | an end state other than ready; a changed `queued_at` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:4
   D10 was resolved by narrowing the prose, not by adding an assertion. The first-audit sentence "guards recovery against a back-off that breaks it" is gone. In its place the docstring now says the test "drives `run_job` and `claim_translate_job` directly and never runs `serve`, so it checks recovery at those seams only, not past a back-off in `serve`'s loop". The new sentence matches what :89, :95 and :98 do. Still, nothing in this file asserts that recovery survives the phase-2 back-off inside `serve`. Recorded so the narrowing stays visible.
2. surfaces (rules/testing.md) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:95
   C2 is EXEMPT by the operator's decision. It is still checked at the `run_job`/`claim_translate_job` seam by :97 and :100, so the exemption covers only the claim that it goes red at this checkpoint, not whether it is observable. The part of C2 that is left unproven is "claimed again" by `serve` after a back-off. That has an observable at the `serve` seam the first test already drives.
3. whole-claim (rules/testing.md) — tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py:73
   C1 is worded in terms of claims, but :73 measures the gap between `resolve_video` calls. In `serve` (translate-worker.py:515, :526 → :427), every claim of v-1 leads straight into one lookup with no step that can be skipped in between. So the lookup gap stands in for the claim gap. This was already noted on the first audit and is unchanged.

NOT ASSESSED
1. `fixtures_path` was not supplied. `rig`, `StubRunner`, `_whitelist` and the constants were read from tests/active/test_translate_worker.py:440–550. The `clip` fixture that `rig` depends on, and `Rig.__init__` above line 440 (including how `rig.whitelist` is seeded with v-1 and d-1), were not read.
2. `data.subtitles` (`claim_translate_job`, `requeue_translate_job`, `enqueue_translate_job`) and `data.db.connect_readonly_db` are outside `code_under_test` and were not read. The claim that a deleted whitelist.db raises "unable to open" and that a requeue restores `queued_at` and `attempts` was taken from the worker's docstrings and comments.

## 2026-10-03 - Step 7 - Phase 2 (Back off before the reclaim, then recover) - checkpoint outcome (run 1)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py` exited 0 after the phase landed.

<changes>
### engine/server/db/jobs/translate-worker.py
- Added the module constant `TRANSIENT_BACKOFF_SECONDS = 30.0`, defined next to `POLL_SECONDS`. Its comment gives the reason for it: the requeued job is still at the head of the queue, so without a wait `serve` would claim it again straight away and spin.
- `serve` now uses the `bool` that `run_job` already returned. That value is True only for the whitelist.db requeue added in phase 1. When it is True, `serve` waits `TRANSIENT_BACKOFF_SECONDS` before its next claim (C1). The wait sleeps with `time.sleep` in pieces no longer than `POLL_SECONDS`, so a stop still ends `serve` within one poll interval. It uses `time.sleep` rather than `stop.wait` for the same SIGTERM-deadlock reason already noted in the idle branch. Each sleep is clamped at 0 so a near-zero remainder can't raise. The docstring of `serve` now mentions the back-off.
- C2 needed no change. After the back-off, the job claimed again goes through the same `run_job` path as any other job, which phase 1 already delivered.

### tests/active/test_translate_worker.py
Not changed. The checkpoint only imports its rig and constants, and they already covered what it needed.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py  4 passed                               0.0s
  ----------------------------------------------------------------
  total                                                             4 passed                               2.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 3 (Stay live during the back-off) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The back-off wait in `serve` keeps the worker live: it refreshes `progress["at"]` every `POLL_SECONDS` slice and a stop ends it within one slice.

- C1 - During the back-off, `progress["at"]` keeps advancing at least once per slice.
- C2 - A stop set during the back-off makes `serve` return within about one slice without claiming again.

must_prove:
- C1 - During the back-off, `progress["at"]` keeps advancing at least once per slice.
- C2 - A stop set during the back-off makes `serve` return within about one slice without claiming again.

## 2026-10-03 - Step 7 - Phase 3 (Stay live during the back-off) - self-check (audit round 1, send-back 0)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:76 — `max(ages) < FRESH_SECONDS` (0.1 s, two slices): `progress["at"]` is read every 0.01 s for 0.25 s (five slices) inside the second back-off, and no read is more than two slices old. Line 77's control (`len(lookups.calls) == 2`) shows no read came from a fresh claim. - expected: Under the right implementation every age is under 0.1 s. This is a prediction: I could not observe it, because the phase is not built. The nearest thing I could observe was a probe thread that sets `progress["at"]` and then sleeps 0.05 s, read the same way. Over 20 runs it peaked at 0.0504 s with 6 distinct values per window. Today the run reads the ages growing steadily from 0.0084 s to 0.2498 s. - excludes: Today's sliced wait never touches `progress`, so the oldest read is 0.2498 s and the run fails. A wait that sets `progress["at"]` once, when the back-off starts, also reaches about 0.25 s. A wait that refreshes every other slice or less often goes past 0.1 s.
- C2 - tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:88 — the thread is no longer alive and `elapsed < STOP_WITHIN_SECONDS` (0.5 s) after a stop set with more than 0.5 s of the back-off left. Line 81's control checks the time left. - expected: Observed in a probe against today's code (phase 2's sliced wait): the thread returned 0.041 s after the stop, with 1.24 s of the back-off left. The new wait should match that. - excludes: A wait that ignores the stop, such as one `time.sleep(TRANSIENT_BACKOFF_SECONDS)` or a refresh loop that never checks `stop`, keeps running for the remaining ~1.2 s. `elapsed` then reads about 1.2 s and fails the 0.5 s bound.
- C2 - tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:89 — `len(lookups.calls) == 2` after the stop. The pass-through spy counts lookups, and lookup is the first thing a claim reaches. Line 72's control shows the spy records lookups. - expected: 2. Observed in the probe against today's code: still 2 lookups after the stop. - excludes: A new wait that leaves the back-off loop and goes round `serve`'s outer loop once more without re-checking `stop` claims the job again. That makes a third lookup, so the count reads 3.
- C2 - tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:91 — `(row["state"], row["attempts"]) == ("queued", 0)` after `serve` returns. - expected: ("queued", 0). Observed in the probe against today's code: state queued, attempts 0. - excludes: A claim after the stop leaves the row `running` with attempts 1, or requeued with an attempt spent, so the tuple no longer equals ("queued", 0).

<assertions>
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:82 — `progress["at"]` sampled 0.15 s apart inside the second back-off has moved forward (`second > first`). Fails against a wait that never touches progress or sleeps the whole back-off in one call. Today's red is here, in both parametrizations — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:83 — the second sample is under 0.3 s old. Fails against a wait that refreshes once at the start or rarely — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:84 — control: `len(lookups.calls) == 2` after the second sample, so both samples were taken in the second back-off and not during a fresh claim, which sets progress itself — C1
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:74 — control: serve reached its second lookup within ten back-offs — C1/C2 setup
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:75 — control: the second requeue landed (row queued again), so serve is in the back-off before sampling — C1/C2 setup
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:88 — control: more than 0.5 s of the back-off is left when stop is set, so a wait ignoring stop until its deadline would break the bound at :95 — C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:95 — after `stop.set()` from the test thread and `join(5)`, the thread is dead and less than 0.5 s passed since the stop. Fails against a wait that ignores stop until its deadline — C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:96 — `len(lookups.calls)` is still 2 after the join. Fails against a loop that breaks out of the wait and then claims once more before exiting — C2
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:98 — row `(state, attempts) == ("queued", 0)`: the job is left requeued and unspent, with no claim held over the stop — C2
</assertions>

<probes>
Wrote tests/tmp/probe_45_phase3_backoff.py and ran `ValidateTests ["tests/tmp/probe_45_phase3_backoff.py", "-s"]` against today's serve (POLL_SECONDS 0.05, TRANSIENT_BACKOFF_SECONDS 1.0, both the injected-lock and missing-file lookup failures). From tests/last_test_output.txt: lookup gap 1.0003 s. Second lookup seen 0.005 s after it happened, row queued again 0.0054 s after it. `progress["at"]` first and second samples identical, both equal to the value set just before the claim (-0.00014 s relative to lookup 2); sample age 0.1556 s; calls 2. Back-off left at stop 0.8445 s. Join elapsed 0.045 s, thread dead, calls 2, row queued, attempts 0. Identical figures for both parametrizations.
Ran `ValidateTests ["tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py"]` against today's code: 2 failed, both at :82 (`assert 1656641.351556682 > 1656641.351556682`). Every control before it (:74, :75) passed, so the red is C1's assertion and not the setup.
I could not remove the probe file: no tool here deletes files. tests/tmp/probe_45_phase3_backoff.py is still on disk and should be deleted; the checkpoint now covers what it showed.
</probes>

<unassertable>
none. C2 is asserted in full, but it is green before phase 3: the probe showed phase 2's sliced wait already returns 0.045 s after a stop with no further claim. Its assertions guard the new progress-refreshing wait against ignoring stop or claiming once more, and the phase's red comes from C1 (:82). The docstring says so. If the workflow needs each clause red before the phase, C2 needs the same operator exemption phase 2's C2 got.
</unassertable>

### `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py` - 5319 characters, inlined in full

```
"""Issue 45, phase 3 checkpoint: `serve`'s back-off after a whitelist.db requeue keeps `progress["at"]` advancing, and a stop set during it ends `serve` within about one slice without another claim.

`serve` runs in-process on a daemon thread over the rig's connection with `POLL_SECONDS` 0.05 and `TRANSIENT_BACKOFF_SECONDS` 1.0 on the loaded module, v-1 queued at 1000, and the `progress` dict handed to it held by the test. Every whitelist lookup fails, either from an injected `database is locked` or from a deleted file (the real `unable to open database file`), and a recorder notes each one. Once the second lookup has happened and its requeue has landed, the worker is inside the second back-off:

- C1: `progress["at"]` sampled twice 0.15 s apart has moved forward, and the second sample is under 0.3 s old; only two lookups have happened, so both samples came from the wait and not a fresh claim. Today's wait was probed leaving it at the value set before the claim.
- C2: a stop set from the test thread with more than 0.5 s of the back-off left ends `serve` within 0.5 s, with still only two lookups, and the row queued with attempts 0. Phase 2's sliced wait already does this, so C2 is green before phase 3 and guards the new wait against ignoring the stop or claiming once more; the red is C1's.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import HOST, MAX_DURATION, QUEUED_AT, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import enqueue_translate_job  # noqa: E402

LOCKED = "database is locked"
BACKOFF_SECONDS = 1.0
SLICE_SECONDS = 0.05
# Three slices, so a wait refreshing once per slice has moved progress at least twice between the samples.
SAMPLE_GAP_SECONDS = 0.15
FRESH_SECONDS = 0.3
# Probed at about 0.045 s with a 0.05 s slice; a wait that ignored the stop would run out the remaining ~0.8 s.
STOP_WITHIN_SECONDS = 0.5
LOOKUP_WAIT_SECONDS = 10 * BACKOFF_SECONDS


def _recording(resolve, injected: bool):
    """A resolve_video stand-in noting the monotonic time of each call; it raises `database is locked` when injected and otherwise calls `resolve`."""
    calls: list[float] = []

    def recorded(whitelist_path, video_id, host, max_duration):
        calls.append(time.monotonic())
        if injected:
            raise sqlite3.OperationalError(LOCKED)
        return resolve(whitelist_path, video_id, host, max_duration)

    recorded.calls = calls
    return recorded


def _until(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.mark.parametrize("injected", [True, False], ids=["injected lock", "missing file"])
def test_serve_refreshes_progress_through_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim(rig, monkeypatch, injected):
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", SLICE_SECONDS)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", BACKOFF_SECONDS)
    lookups = _recording(rig.worker.resolve_video, injected)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    if not injected:
        rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    progress = {"at": time.monotonic()}
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, progress), daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(lookups.calls) >= 2, LOOKUP_WAIT_SECONDS), lookups.calls  # control: serve reached its second lookup
        assert _until(lambda: rig.row().get("state") == "queued", BACKOFF_SECONDS / 2), rig.row()  # control: the second requeue landed, so serve is in the back-off

        first = progress["at"]
        time.sleep(SAMPLE_GAP_SECONDS)
        second = progress["at"]
        age = time.monotonic() - second

        assert second > first, (first, second)  # C1: the wait moved progress forward
        assert age < FRESH_SECONDS, age  # C1: and kept it fresh
        assert len(lookups.calls) == 2, lookups.calls  # control: both samples fell in the second back-off, not a fresh claim

        stop_at = time.monotonic()
        left = lookups.calls[1] + BACKOFF_SECONDS - stop_at
        assert left > STOP_WITHIN_SECONDS, left  # control: a wait ignoring the stop would outlast the bound below
        stop.set()
        thread.join(5)
        elapsed = time.monotonic() - stop_at
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and elapsed < STOP_WITHIN_SECONDS, (thread.is_alive(), elapsed)  # C2: serve returned within about one slice of the stop
    assert len(lookups.calls) == 2, lookups.calls  # C2: no claim after the stop
    row = rig.row()
    assert (row["state"], row["attempts"]) == ("queued", 0), row  # C2: the job is left requeued unspent

```


Gate: satisfied

## 2026-10-03 - Step 7 - Phase 3 (Stay live during the back-off) - red (audit round 1)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py` exited 1.

```
  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py  1 failed                               0.0s
  ----------------------------------------------------------------
  total                                                             1 failed                               2.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 3 (Stay live during the back-off) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
The test should fail at line 76, `assert max(ages) < FRESH_SECONDS`. In `serve`, the back-off loop at translate-worker.py:530-532 only sleeps and never writes `progress["at"]`. The last write happens at line 515, before the second claim. So across the 0.25 s sampling window the age keeps climbing to about 0.25 s or more, well past the 0.1 s bound. Lines 67-68 and line 77 should pass before then.

NOT ASSESSED
1. `fixtures_path` was given as "none found". The `rig`, `clip` and `StubRunner` fixtures come from tests/active/test_translate_worker.py through a sys.path import at test_path:16-18. I read them there (lines 422-549).
2. `data.subtitles` (`enqueue_translate_job`, `claim_translate_job`, `requeue_translate_job`) was not in `code_under_test` and I did not read it. The `("queued", 0)` row assertion at test_path:91 depends on how `requeue_translate_job` writes `attempts`. I judged that assertion's shape from the test alone.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (14 clauses: 4 must_prove, 7 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `progress["at"]` "keeps advancing" during the back-off | :76, :77 | a back-off wait that never writes `progress` (today's `time.sleep` loop: a 0.25 s-old read). :77 rules out fresh readings that come from a new claim at :515 | CARRIED |
| C1b | must_prove | "at least once per slice" | :76 | a refresh only at the start of the back-off, or every third slice or less often (the read gets older than 0.1 s). It cannot reliably catch a refresh every other slice, or one write with a future time (see Recommendation 1) | CARRIED |
| C2a | must_prove | a stop during the back-off makes `serve` return "within about one slice" | :88 (with :81 as control) | a back-off that ignores `stop` and runs out the ~1.2 s left. The bound is 10 slices, not about one (see Recommendation 2) | CARRIED |
| C2b | must_prove | "without claiming again" | :89, :91 | a claim after the stop, which would make a third lookup through the spy, or would leave the row `running` with attempts 1 if it returned before the lookup | CARRIED |
| D1 | docstring | "every lookup fails with the real `unable to open database file` and the job is requeued" | :68 | a non-transient lookup error that fails the job (row `failed`, never `queued`) | CARRIED |
| D2 | docstring | "read every 0.01 s for 0.25 s (five slices) is never more than 0.1 s (two slices) old" | :76 | a wait leaving `progress` untouched, or refreshing it every third slice or less often | CARRIED |
| D3 | docstring | "with still only two lookups, so every read came from the wait and not a fresh claim" | :77 | a `serve` that spins back into a claim, where :515 refreshes `progress` | CARRIED |
| D4 | docstring | stop set "with more than 0.5 s of the back-off left" | :81 | a stop that lands after the back-off is nearly over, which would make :88 hollow | CARRIED |
| D5 | docstring | "ends `serve` within 0.5 s" | :88 | a thread still alive, or one that took ≥0.5 s after `stop.set()` | CARRIED |
| D6 | docstring | "with still only two lookups" after the stop | :89 | another claim plus lookup after the stop | CARRIED |
| D7 | docstring | "the row queued with attempts 0" | :91 | a claim taken after the stop and left `running`, or a requeue that spends the attempt | CARRIED |
| N1 | name | "serve refreshes progress every slice of the back-off" | :76 | as C1b: no refresh in the wait, or a refresh every third slice or less often | CARRIED |
| N2 | name | "a stop during it returns within a slice" | :88 | a wait that ignores the stop. The bound allows up to 10 slices | CARRIED |
| N3 | name | "without another claim" | :89, :91 | a claim (and lookup) after the stop | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:76
   `assert max(ages) < FRESH_SECONDS, ages` only puts an upper limit on how old the reads are. It never checks that the value goes up over time. C1 says `progress["at"]` "keeps advancing at least once per slice", and some wrong waits still pass this line:
   - A wait that writes `progress["at"]` once with a future time (for example `resume`) makes every age negative and passes.
   - A wait that refreshes every other slice peaks at about 0.10 s. Sampling every 0.01 s often misses that peak, so it can also pass. The comment at :26 says such a wait "would exceed it".
   Assert that every age is ≥ 0, and that `progress["at"]` takes several different values that go up over the five sampled slices. Then the "advancing" half has its own assertion.
2. whole-claim / name-as-sentence (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:88, :54
   The name says "returns within a slice" and C2 says "within about one slice". `STOP_WITHIN_SECONDS` is 0.5 s, which is ten 0.05 s slices. So a wait that checks `stop` only every few slices passes. The line does rule out a wait that ignores the stop, so C2a and N2 are carried. Either tighten the bound toward one or two slices (the probe measured 0.041 s), or change the name and C2 to say what is actually asserted.
3. bounds (rules/testing.md): tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py:79-82
   The stop is tested at only one point, somewhere in the middle of the back-off. Two edges of the sliced wait are not tested:
   - a stop set during the last, shorter slice (where `min(POLL_SECONDS, resume - now)` is less than one slice);
   - a stop set right as the back-off starts, before the first slice.

OBSERVATIONS
none

NOT ASSESSED
1. `fixtures_path` was "none found". The `rig` and `clip` fixtures and `StubRunner` came from tests/active/test_translate_worker.py, lines 420-550; I did not read the rest of that file.
2. I did not read `data.subtitles` (`claim_translate_job`, `requeue_translate_job`). For D7/C2b, I took "attempts 0 after requeue" from the worker's comments in `run_job` (translate-worker.py:477) and from the docstring. I did not check it against the store code.

## 2026-10-04 - Step 7 - Phase 3 (Stay live during the back-off) - checkpoint outcome (run 1)

`tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py` exited 0 after the phase landed.

<changes>
### `engine/server/db/jobs/translate-worker.py`
In `serve`, the back-off loop after a whitelist.db requeue now sets `progress["at"] = time.monotonic()` at the start of each `POLL_SECONDS` slice (C1). Without it, the heartbeat thread would treat a long `TRANSIENT_BACKOFF_SECONDS` wait as a stall and stop beating. The comment above the loop now gives this reason too. The loop's check of `stop.is_set()` before each slice is unchanged, so a stop still ends `serve` within one slice and nothing is claimed again (C2).

### `tests/active/test_translate_worker.py`
Not changed. The checkpoint imports only its existing rig and helpers (`HOST`, `MAX_DURATION`, `QUEUED_AT`, `StubRunner`, `clip`, `rig`). Nothing in this file covers the back-off, so this phase did not need to edit it.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py  1 passed                               0.0s
  ----------------------------------------------------------------
  total                                                             1 passed                               2.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py`
- P2C2 - exempt - rests on: the last audit of `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py`

## 2026-10-04 - Step 8 - refactor pass

<refactors>
none. I made no edits. I checked engine/server/db/jobs/translate-worker.py and the three phases are already in their smallest form. WhitelistBusy is one exception class next to its siblings. The transient check is written inline in generate's only resolve_video call, because it has a single caller. run_job has one new branch and returns a bool. serve has one back-off loop that refreshes progress in each slice. TRANSIENT_BACKOFF_SECONDS is the only new constant. The docstrings for generate, run_job and serve already describe the new behaviour.
</refactors>

<left_out>
1. I did not merge the JobStopped and WhitelistBusy branches in run_job, although both call requeue_translate_job. They log at different levels and with different text, and only the WhitelistBusy branch returns True. A shared helper would add code to save one line. 2. I did not pull serve's back-off loop out into a helper. It has one caller, and a helper would add an indirection without making the code shorter. 3. I did not add the requeue to the module docstring's run_job sentence. The run_job docstring already states it, and that docstring is where readers look. 4. Probe and phase-checkpoint files from phases 1–3 are still in tests/tmp/ (probe_45_phase1_scenarios.py, probe_45_phase2_serve.py, probe_45_phase3_backoff.py, probe_45_whitelist_locked_at_claim.py, test_45_translate_worker_whitelist_locked_at_phase{1,2,3}.py). They are outside the files I was given for this step, and the phase tests are gated checkpoints, so I did not delete or edit them. Whoever owns the build's cleanup should decide what happens to them.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
I matched the shipped translate-worker.py against the inlined source with a Grep on the phase symbols, and the code is the same. run_job's only production caller is serve, so the bool return has no other caller to update. The pass found nothing to cut without changing behaviour or adding indirection.
</observation>

## 2026-10-04 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 2 of 63 test groups (61 unchanged):
  test_search_fusion.py — no map entry
  test_translate_worker.py — changed
  test_search_fusion.py     10 passed                              2.3s
  test_translate_worker.py  49 passed                             40.5s
  ------------------------
  total                     59 passed                             40.8s wall, 2 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 10 - Harvest tests - plan

<harvest_file>
docs/project/plans/harvest-45-translate-worker-whitelist-locked-at-plan.md
</harvest_file>

<plan>
Harvest plan for issue 45, translate-worker whitelist.db locked at claim (scope: the three `tests/tmp/test_45_translate_worker_whitelist_locked_at_phase{1,2,3}.py` files; bootstrap gate clear; record snapshot taken at `tests/last_test_validation.json.preharvest`).

Counts per verdict: DURABLE 4, REPLACES 0, COMBINE 0, REDUNDANT 2, SPENT 0 (6 test functions).

DURABLE, all to `tests/active/test_translate_worker.py`:
- `test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true` (phase 1; parametrized missing file / held EXCLUSIVE lock). No active test covers the WhitelistBusy requeue.
- `test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false` (phase 1; parametrized videos without video_uuid / zero-byte file). It bounds the transient predicate from the other side.
- `test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job` (phase 2; parametrized injected lock / missing file). No active test drives `serve` in-process or asserts `TRANSIENT_BACKOFF_SECONDS`.
- `test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim` (phase 3). Covers heartbeat liveness and stop during the back-off; uncovered anywhere else.

REDUNDANT (stay out):
- `test_control_an_intact_whitelist_reaches_both_hosts` (phase 1). The active transcribed-job test already asserts ready plus `INSTANCE_THEN_JSON` / `[MEDIA_URL]` on the same rig.
- `test_a_job_requeued_on_whitelist_db_claimed_again_once_it_is_usable_runs_to_ready_with_its_queued_at_kept` (phase 2). Every link is already asserted: the requeued row tuple by the phase 1 DURABLE test, the claim of a queued row by `test_subtitles.py::test_claim_hands_out_queued_jobs_oldest_first_…`, and a claimed v-1 running to ready by the transcribed-job test. It was green before its own phase.

Active tests retired: none.

`test_groups` changes: none. The `test_translate_worker.py` entry already claims `engine/server/db/jobs/translate-worker.py` and `engine/server/data/subtitles.py`.

New subject files: none. The subject exists and is not split.

How Step 5 lands them:
- `Rig.run` gains `return`, so it hands back `run_job`'s bool. This reuses the rig rather than carrying phase 1's `_run_job` copy.
- Phase 2 and phase 3 each have a `_recording` helper with the same name and different signatures. They merge into one helper that records `(time, video_id, host)` with optional `locked_calls`, and there is a single `_until`.
- The back-off constants that differ (1.0 s vs 1.5 s) get distinct names.
- Docstrings are rewritten to state the rule instead of "Issue 45, phase N", and the module docstring gains the transient-whitelist and back-off rules.
- The held-EXCLUSIVE-lock case costs about 30 s (busy timeout).

Nothing moved; this turn stopped at Step 4.
</plan>

## 2026-10-04 - Step 9 - build diff

`.scratch/45-translate-worker-whitelist-locked-at/build.diff`: 11 changed file(s) between the Step 0 snapshot `aed68720d3bd15c60a441688639f53fc47cd4519` (2026-10-03T23:20:24-04:00) and `82be9aa6b3395a1041f4af288544f8a706870f30`. Withheld by the permission table: 0.

## 2026-10-04 - Step 9 - document triage

- [ ] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - Several sentences are now false or incomplete, checked against the shipped `translate-worker.py`. That code has `WhitelistBusy`, the inline `locked`/`busy`/`unable to open` check around the claim-time `resolve_video` only, `run_job -> bool`, `TRANSIENT_BACKOFF_SECONDS = 30.0`, and the `serve` back-off loop that sleeps in `POLL_SECONDS` slices and refreshes `progress["at"]` each slice.
- Known Gaps :154: delete the locked `whitelist.db` bullet, which is now false. Keep the faster-whisper/VRAM bullet.
- Error Texts :137: drop "and a locked `whitelist.db`". A lock or a missing file no longer produces a `failed` row. A non-transient whitelist error such as `no such column` or `no such table` still produces `OperationalError: <text>`.
- Job Pipeline intro :83 says "each bound ending the job `failed`". Qualify it for step 1's transient case.
- Job Pipeline step 1 :85: add the transient case:
  - what counts: an `OperationalError` whose text contains `locked`, `busy` or `unable to open`, for example during the updater merge (past the 30 s busy timeout) or a restore;
  - the job goes back to `queued` with `attempts` lowered by 1 and `queued_at` kept, with no `error` or `finished_at`;
  - no remote request is made;
  - every other database error still fails the job as `<ExceptionType>: <text>`.
- Serve Loop :79: after a `whitelist.db` requeue, `serve` waits `TRANSIENT_BACKOFF_SECONDS` (30 s) before its next claim. The wait is slept in 2 s slices with progress recorded each slice. The same head job is reclaimed every cycle until the file is usable, and then it runs normally.
- Stop, Crash and Recovery :141: the SIGTERM bullet only describes the chunk loop. Add two points:
  - a stop during the back-off ends `serve` within one 2 s slice, with no further claim;
  - a stop that arrives during sqlite's 30 s busy wait inside the lookup takes up to about 30 s to act.
- Heartbeat :150: "records progress on every serve pass and every chunk-loop wake (at most 2 s apart)". Add that the back-off also records it every slice, so the heartbeat keeps beating during an outage.
- Job Lifecycle :33/:39: no sentence is false. "A failed key is never queued again" still holds. Optionally note in the `queued` row that a requeued job (stop or `whitelist.db` unavailable) is `queued` again with its `attempts` restored.
- Logs: add the warning `whitelist.db unavailable, requeued video_id=… host=…: <error>` next to `stopped mid-job, requeued …`.
- [ ] `DEPLOYMENT.md` - - Triage row :353 is now false for the job half. It says "A job ends `failed` with `OperationalError: database is locked`" and "The job is not requeued and nothing backs off: the key stays `failed`".
  - Symptom: the job stays `queued`, or flips between `queued` and `running`, and the journal repeats `[translate-worker] whitelist.db unavailable, requeued video_id=… host=…: database is locked`, or `unable to open database file`.
  - Cause: the updater merge holds `whitelist.db` past the 30 s busy timeout, or a restore has removed it. The worker requeues the job unspent and retries after a 30 s back-off.
  - Action: nothing for the job, which runs once the merge or restore ends.
  - A repeating `unable to open` with no restore in progress means the `--whitelist-db` path or its permissions are wrong. This matters because such a misconfiguration now stalls the queue instead of failing jobs.
  - Keep the `enqueue` half as it is (`error: whitelist.db: database is locked`, exit 1, re-run after the updater run ends), because `command_enqueue` is unchanged.
- Triage row :348 "Jobs stay `queued`": add a locked or missing `whitelist.db` as a cause, with the warning line as the tell, pointing to the :353 row.
- :264 TimeoutStopSec note: still true, because 120 s covers a 30 s busy wait plus a 2 s slice. Optionally add that a stop also ends the back-off wait within one slice.
- [ ] `engine/server/data/subtitles.py` - `requeue_translate_job` docstring (:162): "Put a running job back without spending its claim (a stop mid-job); …". The function now has a second caller, `run_job`'s `WhitelistBusy` branch, so the parenthetical is incomplete. Change it to name both cases, for example "(a stop mid-job, or whitelist.db unavailable at claim)". The checklist did not name this file; it is a gap the impact inventory flagged as uncertain.
- [ ] `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md` - - Delivered, so per `triage-labels.md`: set `Status: bug, complete`.
- Tick the acceptance boxes (:93-98) that the delivered code and tests meet. The docs box (:98) is met once the TRANSLATE_WORKER.md and DEPLOYMENT.md updates land.
- Move the file to `docs/project/issues/archive/`.
- [ ] `docs/project/issues/issue-tracker.md` - Row 45 (:8) still reads `ready-for-agent` and links `45-translate-worker-whitelist-locked-at-claim.md`. Set the state to `complete` and point the link at the `archive/` path, following the earlier archived rows.
- [ ] `docs/project/roadmap.md` - :60 says "Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`." That is now delivered. Move it into the line's Delivered list, for example "requeue with back-off when `whitelist.db` is locked or missing at claim (issue `45`; see `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`)". Keep the PARTIAL status, because plan 50 and the player remain.

Out of scope:
- [ ] `CONTEXT.md` - No sentence in the "Translate job" entry (:19) is false. Jobs still move `queued` → `running` and end in exactly one of `ready`, `already_english` or `failed`. The entry already leaves out requeue paths that are not crash recovery, such as the stop requeue. The transient requeue is the same kind of mechanism and belongs in `TRANSLATE_WORKER.md`, which the entry points to.
- [ ] `tests/active/test_translate_worker.py` - The build diff leaves this file unchanged. The new tests live in `tests/tmp/test_45_…_phase{1,2,3}.py`, so the module docstring does not yet describe anything the file fails to test. The harvest plan (`docs/project/plans/harvest-45-translate-worker-whitelist-locked-at-plan.md`, Step 5 notes) moves the four DURABLE tests into this file. That plan states that "The module docstring of `test_translate_worker.py` gains the transient-whitelist and `serve` back-off rules", so the harvest owns this update. It must cover the requeue on a missing file and on a held EXCLUSIVE lock, the `no such column`/`no such table` controls, the back-off gap, progress during the back-off, and a stop during it. The recovery-to-ready test is REDUNDANT and is not harvested, so the docstring should not claim it.
- [ ] `engine/server/README.md` - The Translate worker paragraph (:25) defers to `TRANSLATE_WORKER.md` for the lifecycle. The heartbeat note (:31), "stops beating when the serve loop stalls", stays true because the back-off refreshes progress every slice.
- [ ] `docs/project/plans/50-translate-generation-in-page.md` - This is a future plan, not a description of current behaviour. Its gate (heartbeat freshness) and its polling of `queued`/`running` still hold: the heartbeat keeps beating during the back-off, and a job sitting `queued` through an outage is one of the states it already polls. Nothing it claims is false.

ADR conflicts: none

## 2026-10-04 - Step 9 - Update documentation

- [x] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - updated: TRANSLATE_WORKER.md now says that when `whitelist.db` is locked, busy or can't be opened at claim time, the job goes back to the queue and the worker waits 30 s before claiming again. It no longer says such a job fails for good.
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: the translate-worker Triage rows now say that a locked or missing `whitelist.db` puts the job back on the queue with a back-off. It no longer says the job fails.
- [x] `engine/server/data/subtitles.py` - updated: The `requeue_translate_job` docstring now names both of its callers' cases: a stop mid-job, and `whitelist.db` being unavailable at claim.
- [x] `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md` - updated: Issue 45 is marked `Status: bug, complete`, all seven acceptance boxes are ticked, and it has a Delivered section. I wrote it to `docs/project/issues/archive/`, but the old file is still in place and needs `git rm`.
- [x] `docs/project/issues/issue-tracker.md` - updated: Removed row 45 from the open-issues table, because the issue is delivered and archived.
- [x] `docs/project/roadmap.md` - updated: Roadmap F11-M2: moved issue `45`'s whitelist.db requeue with back-off from an open item into the line's Delivered list.
- [x] `CONTEXT.md` - out of scope: No sentence in the "Translate job" entry (:19) is false. Jobs still move `queued` → `running` and end in exactly one of `ready`, `already_english` or `failed`. The entry already leaves out requeue paths that are not crash recovery, such as the stop requeue. The transient requeue is the same kind of mechanism and belongs in `TRANSLATE_WORKER.md`, which the entry points to.
- [x] `tests/active/test_translate_worker.py` - out of scope: The build diff leaves this file unchanged. The new tests live in `tests/tmp/test_45_…_phase{1,2,3}.py`, so the module docstring does not yet describe anything the file fails to test. The harvest plan (`docs/project/plans/harvest-45-translate-worker-whitelist-locked-at-plan.md`, Step 5 notes) moves the four DURABLE tests into this file. That plan states that "The module docstring of `test_translate_worker.py` gains the transient-whitelist and `serve` back-off rules", so the harvest owns this update. It must cover the requeue on a missing file and on a held EXCLUSIVE lock, the `no such column`/`no such table` controls, the back-off gap, progress during the back-off, and a stop during it. The recovery-to-ready test is REDUNDANT and is not harvested, so the docstring should not claim it.
- [x] `engine/server/README.md` - out of scope: The Translate worker paragraph (:25) defers to `TRANSLATE_WORKER.md` for the lifecycle. The heartbeat note (:31), "stops beating when the serve loop stalls", stays true because the back-off refreshes progress every slice.
- [x] `docs/project/plans/50-translate-generation-in-page.md` - out of scope: This is a future plan, not a description of current behaviour. Its gate (heartbeat freshness) and its polling of `queued`/`running` still hold: the heartbeat keeps beating during the back-off, and a job sitting `queued` through an outage is one of the states it already polls. Nothing it claims is false.

**Updated but not named by the Step 3 inventory.** engine/server/data/subtitles.py

**Other files that had to be touched.** - while updating `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md`: docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md — this is the original path of the archived issue. It needs `git rm` (or the move redone as `git mv`) because I have no delete tool. Until then, both copies exist.

**ADR conflicts.** none

### `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`

<changes>
TRANSLATE_WORKER.md now says that when `whitelist.db` is locked, busy or can't be opened at claim time, the job goes back to the queue and the worker waits 30 s before claiming again. It no longer says such a job fails for good.

I checked every sentence against the shipped `translate-worker.py`: the inline `locked`/`busy`/`unable to open` check around the claim-time `resolve_video` call, the `WhitelistBusy` branch in `run_job`, `TRANSIENT_BACKOFF_SECONDS = 30.0`, and the back-off loop in `serve`.

- **Serve Loop:** a new paragraph. After a `whitelist.db` requeue, `serve` waits 30 s (`TRANSIENT_BACKOFF_SECONDS`) in 2 s slices before it claims again. The same head job is claimed again every cycle, with later jobs waiting behind it, until the file can be used; then it runs like any other job. A cycle takes about 60 s while a lock is held and about 30 s when the file is missing.
- **Job Pipeline:** the intro now says step 1 requeues the job instead of failing it when `whitelist.db` is unavailable. Step 1 itself covers:
  - which errors count: an `OperationalError` whose text contains `locked`, `busy` or `unable to open`, such as during the updater merge or a restore;
  - the job goes back to `queued` with `attempts` lowered by 1 and `queued_at` kept, with no `error` or `finished_at` written and no remote request made;
  - every other database error still fails the job as `<ExceptionType>: <text>`.
- **Error Texts:** "a locked `whitelist.db`" is gone from the `<ExceptionType>: <text>` line. In its place: a `whitelist.db` error other than a lock or a missing file, for example `no such table`.
- **Stop, Crash and Recovery:** the SIGTERM bullet now says a stop during the back-off ends `serve` within one 2 s slice and nothing more is claimed. A stop that arrives during sqlite's 30 s busy wait only takes effect once that wait ends.
- **Heartbeat:** progress is also recorded on every back-off slice, so the heartbeat keeps beating while `whitelist.db` is unavailable.
- **Known Gaps:** removed the locked-`whitelist.db` bullet and kept the faster-whisper/VRAM one.
- **Logs:** added the warning line `whitelist.db unavailable, requeued video_id=… host=…: <error>`.

I left the Job Lifecycle table alone: none of its sentences became false, and the requeue is described once, in Job Pipeline step 1.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `DEPLOYMENT.md`

<changes>
DEPLOYMENT.md: the translate-worker Triage rows now say that a locked or missing `whitelist.db` puts the job back on the queue with a back-off. It no longer says the job fails.

I checked each point against the shipped `translate-worker.py`: the inline `locked`/`busy`/`unable to open` check in `generate`, the `WhitelistBusy` branch and its warning line in `run_job`, and the `TRANSIENT_BACKOFF_SECONDS = 30.0` loop in `serve`.

- **Triage row for a locked `whitelist.db`, split into two rows:**
  - **Worker row.**
    - Symptom: the job stays `queued` or flips between `queued` and `running`, and the journal repeats `[translate-worker] whitelist.db unavailable, requeued video_id=… host=…: database is locked` (or `unable to open database file`).
    - Cause: the updater's merge holds the file past the 30 s busy timeout, or a restore has removed it. The job is put back without counting a claim and claimed again after a 30 s back-off; the detail is left to a pointer to `TRANSLATE_WORKER.md`. A repeating `unable to open` with no restore running means the `--whitelist-db` path or its permissions are wrong, and later jobs wait behind this one.
    - Action: nothing for the job. For a wrong path or permissions, fix them and restart the worker.
  - **`enqueue` row:** keeps `error: whitelist.db: database is locked` and exit 1, with "re-run `enqueue` after the updater run ends". `command_enqueue` is unchanged.
- **Triage row "Jobs stay `queued`":** adds a locked or missing `whitelist.db` as a cause, with the repeating `whitelist.db unavailable, requeued` line as the sign, and points to the row above.
- **`TimeoutStopSec=120` bullet:** SIGTERM now also lets a `whitelist.db` lookup finish its busy wait (up to 30 s). That wait cannot be interrupted, and 120 s still covers it.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/data/subtitles.py`

<changes>
The `requeue_translate_job` docstring now names both of its callers' cases: a stop mid-job, and `whitelist.db` being unavailable at claim.

- `engine/server/data/subtitles.py:162`: the parenthetical "(a stop mid-job)" now reads "(a stop mid-job, or whitelist.db unavailable at claim)". The rest of the docstring and the function are unchanged.
- I checked this against `translate-worker.py:473-480`. `run_job` calls `requeue_translate_job(conn, *claim)` in both its `JobStopped` and `WhitelistBusy` branches.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md`

<changes>
Issue 45 is marked `Status: bug, complete`, all seven acceptance boxes are ticked, and it has a Delivered section. I wrote it to `docs/project/issues/archive/`, but the old file is still in place and needs `git rm`.

- **Moved:** the issue now lives at `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md`, matching the earlier archived issues and the archive link set in `issue-tracker.md`. I have no shell, so I couldn't delete the original at `docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md`. Until someone runs `git rm` on it, both copies exist.
- **Status line** changed from `ready-for-agent` to `complete`, as `triage-labels.md` says.
- **New `### Delivered` comment**, laid out like archived issue 44:
  - It names the delivering plan (`51-45-…`) and points to `TRANSLATE_WORKER.md` and the `DEPLOYMENT.md` triage table for the behaviour, without repeating them.
  - The worker change, written from the shipped code: `WhitelistBusy` raised for `locked`/`busy`/`unable to open` at the claim-time `resolve_video` only; `run_job -> bool` with requeue plus one warning; `serve` waits `TRANSIENT_BACKOFF_SECONDS` in `POLL_SECONDS` slices, refreshing progress each slice.
  - The tests that landed in `tests/active/test_translate_worker.py`.
  - The limits: a stop during sqlite's 30 s busy wait is slow to act; a wrong `--whitelist-db` path holds the head of the queue; keys already `failed` stay that way.
- **Acceptance boxes:** all seven are ticked, each checked against the tree.
  - Real `BEGIN EXCLUSIVE` and missing-file cases are in the durable requeue test.
  - The back-off gap and the stop during it are covered by the two `serve` tests.
  - The `no such column` and `no such table` control is covered.
  - The docs box: the `TRANSLATE_WORKER.md` and `DEPLOYMENT.md` updates are already in the tree.
  - The suite box: the pre-harvest full run exited 0.
  - The recovery box carries a short note. The harvest retired its own test, and the durable suite now covers recovery only through its parts.
- **Unchanged:** the Problem, Proposed solution, Triage and Agent Brief text stays as recorded.

**Check this:** while I was verifying, `engine/server/db/jobs/translate-worker.py:432` read `for word in ()`, which turns the transient check off. A `translate-worker.py.bak` holds the correct `("locked", "busy", "unable to open")`. The build diff also has the correct tuple. The latest `last_test_validation.json` run shows the requeue test failing against this. It looks like the harvester's mutation proof, still running and not yet restored. I didn't touch it, but make sure the file is restored from `.bak` before the build closes.
</changes>

<not_on_checklist>
docs/project/issues/45-translate-worker-whitelist-locked-at-claim.md — this is the original path of the archived issue. It needs `git rm` (or the move redone as `git mv`) because I have no delete tool. Until then, both copies exist.
</not_on_checklist>

### `docs/project/issues/issue-tracker.md`

<changes>
Removed row 45 from the open-issues table, because the issue is delivered and archived.

- The checklist asked for row 45 to be set to `complete` with its link pointed at `archive/`. The file's own rule (line 3) says something else: the table lists open issues only, and a row is removed when its issue moves to `archive/`. There are no archived rows in the table to copy; for example, the archived issue 44 has no row. So I deleted row 45 instead of rewriting it.
- `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md` already exists. The copy at `docs/project/issues/45-…md` is still there too, so whoever owns the issue-file move needs to delete it.
- Rows 42 and 43 are unchanged.
- Something I noticed and did not touch: `docs/project/issues/41-short-similarity-cache-tests.md` is outside `archive/` but has no row in the table.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/roadmap.md`

<changes>
Roadmap F11-M2: moved issue `45`'s whitelist.db requeue with back-off from an open item into the line's Delivered list.

- Line 60 (PARTIAL — F11-M2): removed "Requeue with back-off when `whitelist.db` is locked at claim time is issue `45`." and added it to the Delivered list as "that worker's requeue with back-off when `whitelist.db` is locked or missing at claim (issue `45`, `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md`)". It uses the TRANSLATE_WORKER.md pointer the sentence before it already gives, so the line does not repeat the behaviour.
- I checked this against `translate-worker.py`. `WhitelistBusy` is there, and so is the inline check for `locked`/`busy`/`unable to open`, which covers a missing file as well as a locked one. `TRANSIENT_BACKOFF_SECONDS = 30.0` is there, and so is the back-off in `serve`.
- The issue link points at the `archive/` path, the same way other delivered lines link their issues. The issue file is moved there in its own checklist turn.
- The line stays PARTIAL, because plan 50 and the player are still open.
</changes>

<not_on_checklist>
none
</not_on_checklist>

## 2026-10-04 - Step 10 - Harvest tests

<moved>
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py::test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true (missing file, held EXCLUSIVE lock) -> tests/active/test_translate_worker.py, group test_translate_worker.py
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase1.py::test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false (videos without video_uuid, zero-byte file) -> tests/active/test_translate_worker.py, group test_translate_worker.py
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase2.py::test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job (injected lock, missing file) -> tests/active/test_translate_worker.py, group test_translate_worker.py
tests/tmp/test_45_translate_worker_whitelist_locked_at_phase3.py::test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim -> tests/active/test_translate_worker.py, group test_translate_worker.py
How they landed: `Rig.run` now returns `run_job`'s bool, so phase 1's `_run_job` copy is not carried. One merged `_recording(resolve, locked_calls=0)` records (time, video_id, host), and there is a single `_until`. The two back-offs are separate constants, GAP_BACKOFF_SECONDS = 1.0 and LIVE_BACKOFF_SECONDS = 1.5. There is one LOOKUP_WAIT_SECONDS = 15 s, which is still under the 30 s default. The phase 1 `_job` helper is renamed `_job_tuple` so it doesn't clash with the existing `_jobs`. The docstrings now state the rules, and the module docstring has new "Whitelist at claim" and "Back-off" paragraphs.
Not moved (REDUNDANT, per the plan): test_control_an_intact_whitelist_reaches_both_hosts and test_a_job_requeued_on_whitelist_db_claimed_again_once_it_is_usable_runs_to_ready_with_its_queued_at_kept.
</moved>

<retired>
none
</retired>

<group_map>
none. The `test_translate_worker.py` entry already claims engine/server/db/jobs/translate-worker.py and engine/server/data/subtitles.py. `--audit-map` exits 0 before and after the harvest, and the moved tests add no findings: the group's findings are the same advisory MISSING (subtitles.db, translate-worker.lock) and UNRESOLVABLE (whitelist.db) entries as before.
</group_map>

<mutations>
M1 engine/server/db/jobs/translate-worker.py generate: transient words emptied (`for word in ()`) -> test_a_locked_or_unopenable_whitelist_at_claim_… RED in both cases at `_job_tuple(rig) == ("queued", 0, QUEUED_AT, None, None)`, which got ('failed', 1, …); restored with cp, diff clean, GREEN (2 passed)
M2 engine/server/db/jobs/translate-worker.py generate: "no such" added to the transient words -> test_any_other_whitelist_error_at_claim_… RED in both cases at `(row["state"], row["error"]) == ("failed", "OperationalError: …")`, which got ('queued', None); restored with cp, diff clean, GREEN (2 passed)
M3 engine/server/db/jobs/translate-worker.py serve: `if run_job(...) and False:`, so serve ignores the requeue bool -> test_serve_waits_the_back_off_… RED in both cases at `lookups.calls[1][0] - lookups.calls[0][0] >= GAP_BACKOFF_SECONDS`, a gap of about 0.0002 s; restored with cp, diff clean, GREEN (2 passed)
M4 engine/server/db/jobs/translate-worker.py serve back-off loop: `progress["at"] = time.monotonic()` replaced by `pass` -> test_serve_refreshes_progress_… RED at `max(ages) < FRESH_SECONDS`, with an oldest read of 0.2495 s against the 0.1 s bound; restored with cp, diff clean, GREEN (1 passed)
None survived and none hung. Each .bak was moved to delete_me/translate-worker.py.bak.m1 to .m4, and there is no .bak left under engine/, client/ or scripts/.
</mutations>

<cleared>
delete_me/ now holds the three in-scope files: test_45_translate_worker_whitelist_locked_at_phase1.py, test_45_translate_worker_whitelist_locked_at_phase2.py and test_45_translate_worker_whitelist_locked_at_phase3.py. It also holds the four restored mutation backups, translate-worker.py.bak.m1 to .m4. The 45-translate-worker-whitelist-locked-at.build.diff that was already there is untouched. tests/tmp no longer holds any test_45_* file. The probe_*.py files there were outside the scope and were left in place. Final counts: I restored the pre-harvest snapshot over the record, then ran `--compare` with no tier named. It ran 5 changed or unmapped groups and carried 58 forward unchanged by digest: 137 passed and 0 failed, with test_translate_worker.py at 56 passed (49 before plus 7 new). Seven results appeared, all from the four harvested tests (2 + 2 + 2 + 1), and none departed. There was no new red and nothing stopped being red. The record is banked (exit 0), and HARVEST_FILE records Steps 5 to 8. Nothing has been deleted: the files in delete_me/ are waiting for the user to remove them.
</cleared>

`--audit-map` exited 0.
Files still in tests/tmp: none

`--compare` exited 0.

```
selected 1 of 63 test groups (62 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.0s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

