# Guard the shared Engine connection against the progress-handler deadlock

Status: bug, complete
Origin: follow-up to the Engine deadlock fixed on 2026-09-26 (session 20260925T203620-2cd8)

## Problem

`statement_deadline` (`engine/server/data/db.py`) installs and clears a SQLite progress handler on the shared `server.db` connection around every Engine request. Calling `set_progress_handler` while another thread's statement is running on that connection deadlocks the whole process: the running statement needs the GIL to call the handler, and the installing thread holds the GIL while it waits for the connection mutex. Every route stops answering, `/api/health` included.

The fix that landed passes `db_lock` to `statement_deadline`, so the handler only changes while that lock is held. That holds only while every statement on `server.db` is also run under `db_lock`. Nothing enforces this. A future query that skips the lock, or a caller whose `getattr(server, "db_lock", None)` fallback returns `None`, puts back a process-wide hang that nothing reports.

## Built from

`docs/project/plans/archive/05-shared-connection-deadline-guard.md`.

## Comments

- 2026-09-26 — Delivered by `docs/project/plans/archive/05-shared-connection-deadline-guard.md`. `install_deadline_handler` installs the progress handler once, when `connect_db`/`connect_readonly_db` open a connection. `statement_deadline(seconds)` now sets a per-thread deadline and never touches the connection, so a missed `db_lock` can no longer deadlock the process. Checkpoint green, live load check clean.
