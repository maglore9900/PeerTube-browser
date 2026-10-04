# A locked whitelist.db at claim time fails a translate job permanently

Status: bug, complete
Origin: build 49-translate-whisper-worker (plan `docs/project/plans/archive/49-translate-whisper-worker.md`, working file `docs/project/plans/archive/52-49-translate-whisper-worker.md`). The draft named it `WhitelistBusy`, and the build left it unbuilt.

## Problem

When the translate worker claims a job, `generate` calls `resolve_video` (`engine/server/db/jobs/translate-worker.py:93`, called at `:422`) to re-check the whitelist and the denylist. `resolve_video` opens `whitelist.db` read-only with `PRAGMA busy_timeout = 30000`.

If the file is still locked after 30 s, the `sqlite3.OperationalError` escapes `generate`. The catch-all `except Exception` in `run_job` (`:469`) then ends the job `failed` with `OperationalError: database is locked`. A missing file, for example mid-restore, ends the same way.

- `failed` is terminal: enqueue refuses a key in any state (`enqueue_translate_job` returns `exists`). That key can then never be queued again from the CLI or from plan 50's route.
- The only ways out are B1's upsert, if the instance gains an English track, or a manual `DELETE` of the row.

A long write lock on `whitelist.db` is expected, not rare. The updater's merge holds one while it commits. `engine/server/db/jobs/docs/TRANSLATE_WORKER.md:154` and the `DEPLOYMENT.md` triage table record the gap as known behaviour.

No acceptance criterion in plan 49 requires the fix, so plan 49 closed without it.

## Proposed solution

Treat a lock or a missing file during the claim-time whitelist check as transient:
- requeue the job without spending its claim, using `requeue_translate_job`, which SIGTERM already uses;
- have `serve` back off, for example 30 s, before the next claim.

A real error, such as `no such column` from an unmigrated `whitelist.db`, should still fail the job.

The plan 49 draft had this shape:
- a `WhitelistBusy` exception;
- an `is_transient_db_error` check matching "locked", "busy" or "unable to open";
- a `TRANSIENT_BACKOFF_SECONDS` sleep in `serve`.

A gating test would:
- make `resolve_video` raise `sqlite3.OperationalError("database is locked")` at claim;
- assert the row is back to `queued` with its `attempts` and `queued_at` restored;
- assert the next claim waits for the back-off;
- as a control, assert a `no such column` error still ends `failed`.

When fixed, remove the known-gap lines from `TRANSLATE_WORKER.md` and the `DEPLOYMENT.md` triage row.

## Related

- `docs/project/plans/archive/49-translate-whisper-worker.md`, Outstanding.
- `docs/project/plans/50-translate-generation-in-page.md`: its route calls the same enqueue, so a key failed this way is also refused from the page.
- Memory `engine-concurrent-start-locks-random-cache`: the project's history of "database is locked".

## Comments

### Triage (2026-10-03): confirmed, ready for an agent

- **Reproduced** with `tests/tmp/probe_45_whitelist_locked_at_claim.py`:
  - It builds the test suite's whitelist fixture in the default rollback journal, which is the dev `whitelist.db`'s mode (`PRAGMA journal_mode` reads `delete`), so a writer's lock blocks readers.
  - It queues and claims a job, holds `BEGIN EXCLUSIVE` on the whitelist, and calls `run_job`.
  - After the 30 s busy timeout the row reads `failed`, with an error starting `OperationalError: database is locked`.
  - Enqueuing the key again returns `("exists", "failed")`.

  The probe passed in 30.4 s.
- **Checked:** nothing in the worker treats a database error as temporary; nothing requeues it or backs off. There is no `docs/project/rejected/` entry, and no ADR covers worker retries.
- **Decided (maintainer):** a missing or unopenable `whitelist.db`, for example during a restore, is temporary, just as a lock is. The job is requeued and the worker backs off, repeating until the file is back.

### Delivered

Delivered by `docs/project/plans/51-45-translate-worker-whitelist-locked-at.md`. The behaviour is documented in `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` (Serve Loop, Job Pipeline step 1, Logs) and the `DEPLOYMENT.md` triage table.

- **Worker** (`engine/server/db/jobs/translate-worker.py`). `generate` wraps only the claim-time `resolve_video` call: an `sqlite3.OperationalError` whose lowercased text contains `locked`, `busy` or `unable to open` raises `WhitelistBusy`, and any other error is re-raised to the catch-all as before. `run_job` returns `bool`; its `WhitelistBusy` branch calls `requeue_translate_job`, logs one warning `[translate-worker] whitelist.db unavailable, requeued video_id=… host=…: <error>`, and returns True. `serve` then waits `TRANSIENT_BACKOFF_SECONDS` (30 s) in `POLL_SECONDS` slices, refreshing `progress["at"]` and checking `stop` each slice.
- **Tests** (`tests/active/test_translate_worker.py`): the requeue for a missing file and a held `BEGIN EXCLUSIVE` lock past the real busy timeout; the `failed` control for `no such column` and a zero-byte file (`no such table`); the back-off gap between lookups of the same head job; progress freshness and a prompt stop during the back-off.
- **Limits.**
  - A stop that arrives during sqlite's 30 s busy wait inside `resolve_video` takes up to about 30 s to act.
  - A wrong `--whitelist-db` path or permissions shows as a repeating `unable to open` requeue that holds the head of the queue, not as failed jobs.
  - Keys already `failed`, including those failed by this bug before the fix, stay `failed`.

## Agent Brief

**Category:** bug
**Summary:** A translate job claimed while `whitelist.db` is locked or missing should go back to the queue unspent, not fail permanently.

**Current behavior:**
When the translate worker claims a job, it re-checks the video against the Engine's `whitelist.db`: the whitelist row, the active denylist and the stored duration. It opens that file read-only with a 30 s busy timeout.

If the file is still locked after that, or cannot be opened, the `sqlite3` error propagates to the worker's catch-all job handler. That handler ends the job `failed` with the error text, for example `OperationalError: database is locked`.

`failed` is terminal. Enqueue refuses a key in any state, so the video can never be queued again from the command line or the page.

The updater's merge holds a write lock on `whitelist.db` long enough for this to happen in normal operation. The worker's own documentation and the deployment triage table record it as a known gap.

**Desired behavior:**
- A transient database error during the claim-time whitelist check requeues the job without spending its claim:
  - the state is back to `queued`;
  - `attempts` is restored to its value before the claim;
  - `queued_at` is unchanged, so it stays at the head of the queue.

  Transient means a lock ("locked" or "busy" in the error text) or a file that cannot be opened ("unable to open").
- The worker then waits a back-off of about 30 s before its next claim, instead of reclaiming at once. It keeps beating its heartbeat during the wait, and a stop request (SIGTERM) ends the wait promptly.
- The requeue repeats for as long as the condition lasts. A transient error never ends the job `failed`, and never counts toward the crash-retry limit.
- Any other database error during the check still ends the job `failed` with its text, as today. An example is `no such column` from an unmigrated whitelist.
- A transient requeue is logged at warning level, with the key and the error text.

**Key interfaces:**
- The worker's claim-time whitelist resolution: it currently returns the row or a refusal text, or raises `sqlite3.Error`. Its transient errors must be told apart from the rest.
- The store's existing requeue-without-spending function, the one the SIGTERM path already uses. Reuse it rather than adding a second requeue.
- The worker's serve loop, the claim, run and poll cycle, which needs the back-off. It must not block the heartbeat or a stop.
- The worker's documentation and the deployment triage table, whose known-gap lines this removes.

**Acceptance criteria:**
- [x] With an exclusive lock held on a rollback-journal `whitelist.db` throughout the check, a claimed job ends `queued` with `attempts` and `queued_at` as they were before the claim, not `failed`.
- [x] With `whitelist.db` absent at claim time, the same holds.
- [x] The next claim after a transient requeue happens no sooner than the back-off, and a stop during the back-off makes the worker exit promptly.
- [x] Control: a non-transient `sqlite3.OperationalError`, such as `no such column`, at claim time still ends the job `failed` with that error text.
- [x] Once the lock is released or the file restored, the requeued job is claimed and runs to a normal end state. (Gated during the build; the durable suite covers it through its parts: the requeued row, oldest-first claim, and a claimed job running to `ready`.)
- [x] The worker's documentation and the deployment triage table no longer describe a locked `whitelist.db` as failing the job permanently. They describe the requeue and back-off instead.
- [x] The existing translate worker and subtitles store tests still pass.

**Out of scope:**
- Re-queuing keys that are already `failed`, including ones failed by this bug before the fix.
- Transient handling for the `enqueue` command, which reports a database error and exits 1, or for remote fetch failures.
- Changing the 30 s busy timeout, the crash-retry limit or the queue cap.
- `subtitles.db` locking, which has its own busy timeout and tests.
