# A locked whitelist.db at claim time fails a translate job permanently

Status: bug, needs-triage
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
