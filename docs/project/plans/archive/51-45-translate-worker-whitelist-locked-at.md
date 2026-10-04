# 45-translate-worker-whitelist-locked-at

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/51-45-translate-worker-whitelist-locked-at.record.md`._

## Requirements

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

## High-level plan

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

## Impacts


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


## Documentation to update

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

## Implementation plan

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

### Phases

#### Phase 1 - Requeue at claim on a transient whitelist.db error [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Seam: `run_job`, reached through the existing `Rig` harness in `tests/active/test_translate_worker.py` (`rig.claim()` then `rig.run(StubRunner(rig))`, `Rig.run` changed to return `run_job`'s result), the same entry the outcome tests at :799-852 use. Beyond that seam are a patched module-global `resolve_video` (`_raising`), a real whitelist file that is deleted, zero-byte or held under `BEGIN EXCLUSIVE` by a second connection, and `caplog` on the root logger. c1 is parametrized over injected lock, missing file and held EXCLUSIVE lock (~30 s). For each it asserts every member of the row tuple (state `queued`, attempts 0, queued_at `QUEUED_AT`, error None, finished_at None), exactly one WARNING whose message carries `[translate-worker]`, `v-1`, `HOST` and the error text, no record at ERROR or above, `rig.instance.opened == []` and `rig.media.opened == []`, and `run_job` returning `is True`. These exclude, respectively: a requeue that spends the attempt or rewrites queued_at, a branch that writes error or finished_at, a missing or duplicated log line or one that omits key or text, a branch placed after the catch-all, a guard that lets the job proceed to a remote request, and a return value serve cannot read. c2 is parametrized over injected `no such column` and a zero-byte file. It asserts state `failed` with error starting `OperationalError: no such column` / `OperationalError: no such table`, exactly one ERROR record carrying exc_info, no WARNING, and `run_job` returning `is False`, which excludes an over-broad predicate or a guard that rewraps every OperationalError.

**Intent.** In `translate-worker.py`, a job whose claim-time `resolve_video` call hits a locked, busy or unopenable `whitelist.db` is returned by `run_job` to `queued` with its claim unspent and one warning logged, instead of failing. Every other `whitelist.db` error at claim still fails the job with today's `OperationalError: <text>`.

- C1 - A locked, busy or unopenable `whitelist.db` at claim leaves the job `queued` with attempts restored, `queued_at` kept, no `error` or `finished_at`, nothing requested, and one warning naming the key and the error text, and `run_job` returns True.
- C2 - Any other `whitelist.db` error at claim still ends the job `failed` with `OperationalError: <text>` through the logged catch-all, and `run_job` returns False.

**Outcome.** ### `engine/server/db/jobs/translate-worker.py`

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

#### Phase 2 - Back off before the reclaim, then recover [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Two seams. (a) `serve`, entered in-process on a daemon thread over `rig.conn`, which is opened `check_same_thread=False`. On the loaded module, `POLL_SECONDS` is 0.05 and `TRANSIENT_BACKOFF_SECONDS` is 1.0, `resolve_video` is patched to always raise `database is locked` and record monotonic call times, and a StubRunner is used. No existing harness drives `serve` in-process, because the beat tests use the real CLI under a pty, so this is a new in-process entry and the drafted test function is its harness. For c1 it waits for two lookups, then asserts `calls[1] - calls[0] >= BACKOFF_SECONDS`, which excludes a serve that ignores the bool and reclaims on the next 0.05 s poll. It also asserts the row is still `queued` with attempts 0 and queued_at kept, which shows the reclaim is the same head job. (b) `run_job` via `Rig.run`, then a direct `claim_translate_job(rig.conn, "en", STARTED_AT + 1)`, parametrized over lock released (`_raising(LOCKED, then=real resolve_video)`) and file restored (unlink, then rewrite with `_whitelist`). For c2 it asserts the intermediate control (`queued`, 0), then that the reclaim is `v-1` with attempts 1, then a final row of `ready`, `whisper` and queued_at `QUEUED_AT`. This excludes a requeue that leaves the row unclaimable or a reclaimed run that fails or rewrites queued_at.

**Intent.** After a `whitelist.db` requeue, `serve` in `translate-worker.py` waits `TRANSIENT_BACKOFF_SECONDS` before claiming the same head job again, and once `whitelist.db` is usable that reclaimed job runs like any other.

- C1 - After a `whitelist.db` requeue, the next claim of the same head job comes no sooner than `TRANSIENT_BACKOFF_SECONDS` after the first.
- C2 - Once the lock is released or the file restored, the requeued job claimed again runs to `ready` with its `queued_at` kept.

**Outcome.** ### engine/server/db/jobs/translate-worker.py
- Added the module constant `TRANSIENT_BACKOFF_SECONDS = 30.0`, defined next to `POLL_SECONDS`. Its comment gives the reason for it: the requeued job is still at the head of the queue, so without a wait `serve` would claim it again straight away and spin.
- `serve` now uses the `bool` that `run_job` already returned. That value is True only for the whitelist.db requeue added in phase 1. When it is True, `serve` waits `TRANSIENT_BACKOFF_SECONDS` before its next claim (C1). The wait sleeps with `time.sleep` in pieces no longer than `POLL_SECONDS`, so a stop still ends `serve` within one poll interval. It uses `time.sleep` rather than `stop.wait` for the same SIGTERM-deadlock reason already noted in the idle branch. Each sleep is clamped at 0 so a near-zero remainder can't raise. The docstring of `serve` now mentions the back-off.
- C2 needed no change. After the back-off, the job claimed again goes through the same `run_job` path as any other job, which phase 1 already delivered.

### tests/active/test_translate_worker.py
Not changed. The checkpoint only imports its rig and constants, and they already covered what it needed.

#### Phase 3 - Stay live during the back-off [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** The same in-process `serve` thread seam as phase 2, extending its serve test past the second lookup, while the worker is inside the second back-off. For c1 it samples `progress["at"]` twice, 0.15 s apart, and asserts the second sample is larger and less than 0.3 s old. This excludes a back-off that sleeps the whole deadline in one call or never touches progress, which would let the heartbeat go dark. A control asserts that `len(calls) == 2`, so the samples were taken during the wait and not during a fresh claim. For c2 it sets `stop` from the test thread, joins with a 5 s timeout, and asserts the thread is dead within 0.5 s, well under the ~0.7 s left of the back-off. It also asserts `len(calls)` is still 2, with no claim after the stop, and that the row is still `queued` with attempts 0. This excludes a loop that ignores `stop` until the deadline and one that claims once more before exiting. Setting `stop` off the main thread is safe here because no signal handler is involved.

**Intent.** The back-off wait in `serve` keeps the worker live: it refreshes `progress["at"]` every `POLL_SECONDS` slice and a stop ends it within one slice.

- C1 - During the back-off, `progress["at"]` keeps advancing at least once per slice.
- C2 - A stop set during the back-off makes `serve` return within about one slice without claiming again.

**Outcome.** ### `engine/server/db/jobs/translate-worker.py`
In `serve`, the back-off loop after a whitelist.db requeue now sets `progress["at"] = time.monotonic()` at the start of each `POLL_SECONDS` slice (C1). Without it, the heartbeat thread would treat a long `TRANSIENT_BACKOFF_SECONDS` wait as a stall and stop beating. The comment above the loop now gives this reason too. The loop's check of `stop.is_set()` before each slice is unchanged, so a stop still ends `serve` within one slice and nothing is claimed again (C2).

### `tests/active/test_translate_worker.py`
Not changed. The checkpoint imports only its existing rig and helpers (`HOST`, `MAX_DURATION`, `QUEUED_AT`, `StubRunner`, `clip`, `rig`). Nothing in this file covers the back-off, so this phase did not need to edit it.


