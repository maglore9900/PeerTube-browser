# 22-random-cache-background-refresh

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-22-random-cache-background-refresh.record.md`._

## Requirements

### Purpose

The random feed is served from `engine/server/db/random-cache.db`. Today the cache is built in place, and only on startup: before the Engine listens, under the refresh-on default, or when the cache is missing or empty. This build (issues 22 and 23 together, as `docs/project/issues/plan.md` lane 2d directs) makes the cache refresh while the Engine keeps serving. There is no startup delay, no request is blocked or failed by a rebuild, and no rebuild runs on the request path. It is a prerequisite for `26-zero-downtime-deploy`, and its swap/reopen primitive is meant to be reused by `24-similarity-cache-shadow-swap`.

### Scope decision (operator)

- 22 (periodic background refresh) and 23 (non-blocking startup) are delivered as one build.
- The plan file is `docs/project/plans/19-22-random-cache-background-refresh.md`.
- When 22 is delivered, 23 is delivered with it.

### One build path

- Every cache build the Engine runs, at startup and periodically, uses one path:
  - It scans the source through its own read-only connection to `whitelist.db`. It never uses `server.db` or `server.db_lock`, so a build blocks no request.
  - It computes the full candidate list with the existing `populate_random_cache` logic: same size target, filtered mode, per-instance cap and per-author cap.
  - It writes the result into a per-process temp file in the same directory as the active cache, `random-cache.tmp.<pid>.db`, commits it and closes it.
  - It then moves the temp file onto `random-cache.db` with `os.replace` (atomic rename).
- A per-process temp name is used instead of the fixed `random-cache.tmp.db`, because several Engines can share one checkout (the test harness starts one per lane) and must never write the same temp file.
- After this build, the active cache file is never written in place.

### Swap and reopen

- After a successful replace, the Engine opens a new read-only connection to the new `random-cache.db`.
- Under `server.random_cache_lock` it swaps that connection into `server.random_cache_db`. Only after the swap does it close the old connection.
- `random_cache_lock` is held only for the reference swap, never during the build.
- The swap/reopen helper takes a path, a lock and the owner/attribute to update, and has nothing random-cache-specific in its interface, so issue 24 can reuse it for the similarity cache.
- Another Engine process sharing the checkout keeps reading the file it opened, which is the old inode after a rename. It moves to the new file at its own next build/reopen. This is accepted.

### Reads

- The serving connection to `random-cache.db` is read-only (`mode=ro` URI).
- It needs no long busy wait, because nothing writes the active file in place.
- Issue 32's 3600 s `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` wait and the `reuse_non_empty` keyword of `populate_random_cache` are retired or reworked, as plan.md lane 2d anticipates.
- `fetch_random_rowids` and `fetch_random_rows_from_cache` keep their behaviour and signatures. The only change is that the connection they read may be replaced between calls.

### Non-blocking startup (issue 23)

- The Engine opens the existing cache if there is one, and starts listening without building first.
- A refresh-on start runs its first build in the background worker. Refresh is on under the production default `DEFAULT_RANDOM_CACHE_REFRESH = True` or with `--random-cache-refresh`.
- A refresh-off start builds in the background only when the cache file is missing, or its `random_rowids` table is missing or empty. Refresh is off with `--dev` or `--no-random-cache-refresh`. Otherwise it serves the existing cache as it is.
- Until a build has swapped in, a missing or empty cache is served through the existing DB fallback. That fallback is `fetch_random_rows` on the `[]` result from the cache, in `api/handlers/similar.py` `_fetch_random_rows` and the recommendation candidate sources, and it is unchanged.
- `/api/health` must answer before the startup build completes.

### Periodic refresh (issue 22)

- A new setting `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` is read from the environment in `engine/server/api/server_config.py`. It is a non-negative integer, and 0 disables the periodic refresh.
- When the variable is unset, the default is 60 minutes in production and 0 under `--dev`. An explicitly set value wins over `--dev`.
- An invalid value (not an integer, or negative) exits at startup with a message naming the variable, like the existing `_resolve_*_env` helpers. `_resolve_positive_int_env` refuses 0, so this setting needs a non-negative variant.
- `--no-random-cache-refresh` and `--random-cache-refresh` govern only the startup build, not the periodic one.
- One daemon worker thread per Engine does all the building:
  - It runs the startup build, if any, then one build every N minutes when N > 0.
  - Two builds never run at once in one process.
  - It stops on shutdown, and the Engine's shutdown is not delayed by an in-progress build.
- With interval 0 and no startup build needed, no build runs.

### Failure handling

- A failed build (any exception during the scan, write, replace or reopen) deletes its temp file if present and leaves the active cache file and the serving connection untouched. It logs the failure reason and never raises into the request path.
- A failed build is retried at the next interval tick.
- Deliberate simplification: there is no separate backoff schedule and no max-build-runtime cap (issue 23's "optional max build runtime"). With interval 0, a failed startup build is not retried until the next restart. Upgrade path: add capped backoff in the worker loop if failures prove common.

### Logs

Each build logs:

- duration
- rows scanned
- final size (valid candidates written)
- the size target
- filtered mode and the per-instance and per-author caps
- when the fill comes up short, a line with target, got and scanned
- the swap/reopen result, or on failure the reason

The log style follows the existing `logging.info` lines in `engine/server/data/random_cache.py` and `server.py`.

### SQLite

- There is no WAL. The active file is immutable between swaps and is read through a read-only connection.
- The temp file is built in the default rollback-journal mode and fully closed before the rename, so no `-wal`/`-shm`/`-journal` sidecar is left behind to be separated from its database by the rename.

### Other writer

- `engine/server/db/jobs/precompute-random-rowids.py` writes through the same temp-file plus `os.replace` path instead of writing `--out` in place. `scripts/run-dataset-build.sh` calls it.
- Its CLI (`--db`, `--out`, `--size`, `--reset`, `--refresh`, `--filtered`, `--max-per-instance`, `--max-per-author`) and output are unchanged. `--reset` and `--refresh` keep their meaning of "build fresh" versus reuse when already at size.
- A running Engine picks up a job-built cache at its next build/reopen or restart. The dataset build already says "restart the Engine".

### Unchanged

- The cache schema (`random_rowids(position, video_rowid)`) and contents semantics.
- The filter semantics, `DEFAULT_RANDOM_CACHE_SIZE`, `DEFAULT_RANDOM_CACHE_FILTERED_MODE`, `DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE`, `DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR` and `DEFAULT_RANDOM_CACHE_REFRESH`.
- The random feed's output shape.
- The test harness's `ENGINE_START_LOCK` serialisation and retry in `tests/active/conftest.py`.
- Moving the cache to `ann_id` (plan 17 / issue 08) is out of scope.
- The similarity cache is out of scope beyond keeping the swap helper reusable.

### Acceptance

- A refresh-on Engine start answers `/api/health` 200 before its startup build finishes.
- Random-feed reads running concurrently with repeated build-and-swap cycles return no errors and no empty responses caused by the swap.
- With a short interval, a periodic build swaps a new file in, and later random-feed reads are served from the new file.
- With interval 0, no periodic build runs.
- A failed build (forced) leaves the previous cache serving and its file intact, and removes its temp file.
- An invalid `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` exits at startup naming the variable. Unset gives 60, or 0 under `--dev`. An explicit value overrides `--dev`.
- `precompute-random-rowids.py` produces the same cache contents as before, via temp file and replace.
- `test_engines_starting_at_once_all_become_healthy` (8 Engines at once) still passes.
- The issue-32 tests in `tests/active/test_random_cache.py` that assert the in-place rebuild contract are retired to `tests/archive` or rewritten for the new contract. These are the busy-wait tests `test_random_cache_connection_waits_longer_than_sqlite_default` and `test_rebuild_waits_for_a_write_lock_held_past_sqlite_default`, and the `reuse_non_empty` tests. The refresh-off reuse and missing/empty build behaviours keep test coverage.

### Documentation to update

- `DATA_BUILD.md` §6 (in-place write and the one-hour wait statement).
- `engine/server/api/recommendations/docs/LAYER_PARAMS.md` (the `DEFAULT_RANDOM_CACHE_REFRESH` entry and the new interval setting).
- `DEPLOYMENT.md` where Engine env settings are listed.
- Issues 22 and 23 are marked `complete` and moved to `docs/project/issues/archive/` on delivery.

### Baseline suite state

The pre-build suite exited 0 (variant: false). Resolved paths: active tests `tests/active`, working `tests/tmp`, archive `tests/archive`, plans `docs/project/plans`, delete_me `delete_me`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`, project dir `/home/enduser/code/PeerTube-browser`.

## High-level plan

### Approach

The Engine will build every cache in the background: a temp file, then an atomic rename, then a reference swap. One daemon worker thread per Engine runs all builds. The serving connection becomes a read-only handle that is replaced between reads and never written.

**One build function in `engine/server/data/random_cache.py`.** A new build function takes the source path, the active cache path, the size target, filtered mode and the two caps. It works in this order:
1. Derive the per-process temp name next to the active file (`random-cache.tmp.<pid>.db`, formed from the active file's stem and suffix, so the job's arbitrary `--out` works too). Remove any file of that name, and its `-journal` sidecar, left behind by an earlier process with the same pid.
2. Open the source through `connect_readonly_db` from `data/db.py`. That is an existing `mode=ro` URI helper with `sqlite3.Row` rows, and it never touches `server.db` or `server.db_lock`.
3. Open the temp file writable with the default rollback journal, and run the unchanged `populate_random_cache` into it. On an empty temp file its `DELETE` is a no-op, so the result is the same candidate list, same target, same filter and caps. Commit and fully close both connections, so no sidecar survives.
4. Remove the temp file and its sidecar on any exception, then re-raise to the worker, which logs it. The function returns the count and the elapsed time.

`connect_random_cache_db` stays as the opener for the writable temp file, using sqlite's default wait. `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` and its rat-tail comment are removed. The `reuse_non_empty` keyword and its branch come out of `populate_random_cache`. The `refresh` parameter and the reuse-at-size guard stay, so the positional signature the tests and the job use does not change. `fetch_random_rowids` is untouched.

**The swap helper in `engine/server/data/db.py`.** This is the operator's validate-first choice. It sits beside `connect_readonly_db` and has nothing random-cache-specific in it, so issue 24 can reuse it. It takes the finished temp path, the target path, the lock, the owner object and the attribute name, and works in this order:
1. Open a read-only connection on the temp path through `connect_readonly_db`.
2. Run one check query, a row count on the cache table, whose SQL the caller passes in. On failure, close the connection and raise; nothing has been replaced.
3. `os.replace(temp, target)`. On POSIX the open handle follows the inode, so the connection is now reading the new `random-cache.db`. If the replace fails, close the connection and raise.
4. Under the lock, take the old value of `owner.<attr>` and set the new connection. Release the lock, then close the old connection if there was one.

Once the rename has succeeded, all that is left is an in-memory assignment that cannot fail. So any failure leaves both the active file and the serving connection exactly as they were. The helper never installs `None`. That keeps the unlocked `is None` check at `random_videos.py:435` safe, because the attribute is read again under `random_cache_lock` at line 438. Readers hold `random_cache_lock` for the whole `fetch_random_rowids` call, so the swap waits for any read in flight, and the old handle is closed only after nobody can still hold it. `fetch_random_rows_from_cache` and `fetch_random_rowids` keep their code and signatures.

**Startup in `server.py` (issue 23).** The in-place `connect_random_cache_db` + `populate_random_cache(..., reuse_non_empty=True)` block at lines 328–339 is replaced by a small "open if usable" step:
- If `random-cache.db` exists, open it through `connect_readonly_db` and check that `random_rowids` exists and holds at least one row.
- If so, that connection is `server.random_cache_db`.
- If the file is missing, has no table, is empty, or fails to open, the serving connection is `None`, closed if it was opened. The existing `[]` → `fetch_random_rows` fallback then serves the random feed. An empty table gets `None` too, so a missing table is never queried on the request path.

Whether a startup build is needed:
- **Refresh on:** always.
- **Refresh off:** only when the cache was not usable.

That flag, the interval and the paths are handed to the worker. The worker is started just before `serve_forever`, after `SimilarServer` exists, because the server is the owner the swap updates. Nothing builds before the Engine listens, so `/api/health` answers at once.

**The worker.** It is one `threading.Thread(daemon=True)` with a `threading.Event` for stopping.
- **Loop:** if a startup build is needed, run it. Then, while the interval is above 0, wait on the event for interval × 60 s, exit if the event was set, and otherwise build.
- **One build at a time:** each build is wrapped in a broad `except Exception`, which logs the reason and moves on to the next tick. Because there is a single thread, two builds never overlap and a failed build is retried at the next tick.
- **Interval 0:** with no startup build needed, the thread is not started at all, so no build runs.
- **Shutdown:** `main`'s `finally` sets the event and does not join, so an in-progress build never delays shutdown. The daemon thread dies with the interpreter. The worker checks the event before calling the swap helper. The `finally` closes whatever `server.random_cache_db` currently holds, taken under `random_cache_lock`, rather than the startup local.

**Interval setting.** `server_config.py` gets a non-negative variant of `_resolve_positive_int_env`, `_resolve_non_negative_int_env`:
- It exits naming the variable on a non-integer or negative value.
- It returns `None` when the variable is unset. That is needed because the module is imported before `--dev` is parsed.

The module defines `DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES = 60` and `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` resolved from the environment. `server.py` resolves `None` to 0 under `--dev` and to 60 otherwise, beside the existing `random_cache_refresh` resolution at line 307, so an explicit value wins over `--dev`. The startup log line at line 475 gains the interval. The refresh flags keep governing only the startup build.

**Logs.**
- Each build logs a start line (target, filtered, caps).
- `populate_random_cache` keeps its short-fill and `filtered=… size=… scanned=… max_per_instance=… max_per_author=…` lines. Its unfiltered branch gains the same summary line, with scanned equal to the rows read, so every build logs rows scanned.
- The worker logs one result line: `ok` with duration, size, target and the swapped path, or `failed` with duration and the exception reason.

All lines are plain `logging.info`, in the file's existing `random cache key=value` style.

**Precompute job.** `precompute-random-rowids.py` keeps its argparse block and its final `random cache size=%d` line.
- **Reuse:** without `--reset` or `--refresh`, it opens an existing `--out` read-only. If the table holds at least `--size` rows, it logs that count and exits without writing, which is the current "reuse when at size" behaviour.
- **Build:** otherwise it calls the same build function, then a plain `os.replace` (it has no serving connection to swap). `--reset` and `--refresh` both mean "build fresh", as today. The contents are the same because `populate_random_cache` always cleared the table before filling it.
- `run-dataset-build.sh` is unchanged.

**Tests and docs.** Handled in their own steps, in outline:
- **Retired:** the two busy-wait tests and the two `reuse_non_empty` tests go to `tests/archive`.
- **Kept coverage:** refresh-off reuse and missing/empty-builds are re-covered at the "open if usable" + startup-decision level.
- **In-process tests:** the build function, swap helper and worker take plain paths and an owner object, so the build, swap, forced-failure and interval-0 cases can run in-process on tmp files.
- **Engine-level tests:** health-before-build and the short-interval swap use real Engines with `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` set.
- **Unchanged:** the 8-Engine test's assertions still hold. It only reads the file, and a held `BEGIN IMMEDIATE` (RESERVED) does not block read-only readers. Its docstring and the conftest comments at lines 113–114 describe in-place writes and get reworded; the `ENGINE_START_LOCK` code does not change.
- **Docs:** `DATA_BUILD.md` §6, `LAYER_PARAMS.md` and `DEPLOYMENT.md` are updated. Issues 22 and 23 are archived as complete.

### Alternatives considered

- **Rebuild in place, in one transaction, with WAL for readers.** Rejected. The requirements forbid WAL. Writers in other processes would still contend on the file, which is the issue-32 problem the 3600 s wait papered over.
- **Swap in the literal order written (replace, then reopen the target path).** Rejected in favour of validate-first, by operator choice. A reopen failure after the rename would leave the new file active while the old connection serves, which breaks the failure rule.
- **Keep the candidate list in Python memory instead of a file.** Rejected. It drops the shared on-disk artefact that the job and other Engines use, changes the schema contract, and duplicates memory per process.
- **`threading.Timer` chains or a scheduler.** Rejected for a single loop thread on `Event.wait`. One thread makes "never two builds at once" true by construction, and the event gives shutdown a single stop signal.
- **Build in a subprocess to avoid the GIL.** Rejected as heavier than needed. It is the upgrade path if request latency during builds proves a problem.
- **Detect a changed inode per request so sibling Engines follow a rename quickly.** Rejected. It adds a `stat` to every read, and the requirements accept "at own next build or restart". It is a candidate for issue 26.
- **An empty placeholder cache file instead of `None` when unusable.** Rejected. `None` already routes to the existing DB fallback with no new code on the read path.
- **Split `populate_random_cache` into compute and write functions.** Rejected as churn. Pointed at an empty temp file, the existing function is the compute-and-write step.
- **A new module for the swap helper.** Rejected. `data/db.py` already owns the read-only opener the helper uses.

### Gotchas and risks

- **GIL contention.** The filtered scan is a Python loop over up to the whole table, running in the same process as request threads. Requests are never blocked or failed, but they can be slower while a build runs: at every start with refresh on, and hourly by default.
- **Lock pressure on `whitelist.db`.** The source reads are separate autocommit `SELECT`s of 10 000 rows each in filtered mode. A writer on `server.db` therefore waits at most one chunk's SHARED lock, well under the 5 s default wait. The unfiltered branch is a single `LIMIT size` query and holds SHARED longer; the default is filtered mode.
- **Leftover temp files.** A build interrupted by shutdown or `kill -9` leaves `random-cache.tmp.<pid>.db` behind. It is ignored by `*.db` in `.gitignore`, and it is only cleaned up if a later process gets the same pid. Sweeping stale temp files from dead pids is left out as a simplification.
- **An empty source is swapped in.** The Engine then serves through the DB fallback. This matches today's in-place behaviour.
- **Sibling Engines stay on the old inode** until their own next build or restart (accepted in the requirements). With interval 0 and refresh off, that means until restart. Several Engines sharing a checkout each run their own hourly build.
- **Interval 0 and failure.** With interval 0, a failed startup build is not retried until the next restart (accepted in the requirements).
- **POSIX only.** Rename-over-open-file semantics hold on POSIX (the deployment target), not Windows.
- **Invalid interval breaks the job too.** The setting is resolved when `server_config` is imported, and the precompute job imports it for `DEFAULT_DB_PATH`, so an invalid `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` also stops the job. This is the same property the existing `_resolve_*_env` constants already have.
- **Stale connection at shutdown.** A build that finishes just as shutdown begins could swap in a connection after `main` has closed the current one. The worker's check of the stop event narrows this, and whatever is left is a handle leaked at process exit.

### Tradeoffs the operator is asked to accept

- **Reordered swap steps.** The ones in "Swap and reopen" run in a different order: validate and open on the temp file, then rename, then swap. The helper's interface is a temp path plus a target path, not just a path. This is the operator's choice.
- **Build cost.** Each refresh-on start and each tick costs a full scan's CPU inside the serving process.
- **Named simplifications:**
  - no backoff and no maximum build runtime;
  - no sweep of stale temp files;
  - no fast pickup of new files by sibling Engines;
  - no guard against swapping in an empty build.

  The upgrade paths are, in order: capped backoff in the worker loop; a sweep of temp files with dead pids at worker start; an inode check at issue 26; and a minimum-row guard before the swap.

## Impacts


<impacts>
<impact path="engine/server/data/random_cache.py" element="RANDOM_CACHE_BUSY_TIMEOUT_SECONDS (line 11) and its rat-tail comment (line 10)">
**What changes:** both lines are deleted. The rat-tail comment names "the non-blocking rebuild of issues 22/23" as its own upgrade path, and this build is that upgrade.

**What depends on it:** in code, only `connect_random_cache_db` (line 16). Two tests depend on it: `tests/active/test_random_cache.py::test_random_cache_connection_waits_longer_than_sqlite_default` asserts `PRAGMA busy_timeout > 5000` (line 71), and `test_rebuild_waits_for_a_write_lock_held_past_sqlite_default` (lines 76-108) relies on the wait. The name also appears in `docs/project/issues/23-random-cache-nonblocking-startup.md:31`, `docs/project/issues/plan.md:72` and the archived issue and plan 32. Those are history and stay as they are.

**Regression risk:** low in code. Removing the constant before the two busy-wait tests are archived makes them fail.
</impact>
<impact path="engine/server/data/random_cache.py" element="connect_random_cache_db() (lines 14-18)">
**What changes:**
- `timeout=RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` is dropped, so sqlite's default 5 s wait applies.
- `check_same_thread=False` and `sqlite3.Row` stay.
- Its only remaining use is opening the writable per-pid temp file inside the new build function.
- It is the natural place for a journal-mode fix to the hot-journal hazard (see that entry), for example `PRAGMA journal_mode=MEMORY` right after connect.

**What depends on it:**
- `server.py:105` (import) and `:329`. Both go, and the serving handle becomes `connect_readonly_db`.
- `precompute-random-rowids.py:14` and `:73`. The job then reaches it only through the build function.
- `test_random_cache.py` lines 32, 69, 80, 115 and 150, all in tests being retired.

**Regression risk:** low. It must not stay the serving opener: it is writable and installs no deadline handler. Its default disk rollback journal is the root cause of the hot-journal hazard.
</impact>
<impact path="engine/server/data/random_cache.py" element="populate_random_cache(): reuse_non_empty keyword (line 47), comment lines 52-53, branch lines 54-57">
**What changes:** the keyword, the two comment lines and the `if not refresh and reuse_non_empty and _random_rowids_table_exists(cache_db)` branch are removed. The positional signature `(src_db, cache_db, size, refresh, filtered_mode, max_per_instance, max_per_author)` stays, and so does the reuse-at-size guard (lines 59-61).

**What depends on it:**
- `server.py:338` passes `reuse_non_empty=True`. Unless that call is removed in the same change, the Engine start raises `TypeError`.
- `test_random_cache.py:132` and `:155` pass it. If they stay in `tests/active` they raise `TypeError`.
- The job passes seven positionals and is unaffected.

**Regression risk:** medium, because of ordering: this function, `server.py` and the tests must change in one commit. Refresh-off reuse moves to server.py's "open if usable" step.
</impact>
<impact path="engine/server/data/random_cache.py" element="_random_rowids_table_exists() (lines 33-36)">
**What changes:** its only caller, the `reuse_non_empty` branch, goes away. Either it is deleted, or it becomes the shared table check used by server.py's "open if usable" step and by the job's reuse check. If it is shared, it wants a public name, because server.py and the job would otherwise import a leading-underscore name across modules.

**What depends on it:** nothing else. Grep finds no other reference in `engine/` or `tests/`.

**Regression risk:** low. The risks are dead code, or the `sqlite_master` query written twice.
</impact>
<impact path="engine/server/data/random_cache.py" element="populate_random_cache() unfiltered branch (lines 78-94): new summary log line">
**What changes:** the branch gains the `random cache filtered=%s size=%d scanned=%d max_per_instance=%d max_per_author=%d` line, with scanned = `len(rows)`. The branch is taken when `filtered_mode` is false, and also when `filtered_mode` is True but both caps are ≤ 0 (line 78). In that second case, logging the argument prints `filtered=True` for an unfiltered scan, so the implementer must choose between logging the argument and logging the effective mode.

**What depends on it:** neither default path takes this branch. `run-dataset-build.sh:264` passes `--filtered --max-per-author 100`, and `server_config.py:340-343` sets filtered mode with an author cap of 100. It matters only for manual runs and tests.

**Regression risk:** low; the line is additive.
</impact>
<impact path="engine/server/data/random_cache.py" element="new build function (source path, active path, size, filtered, caps → count, elapsed)">
**What changes:** a new public function.
- **Temp path:** `<stem>.tmp.<pid><suffix>` beside the active path. Any leftover file of that name and its `-journal` are unlinked first.
- **Source:** opened with `connect_readonly_db`. This needs `from data.db import connect_readonly_db`. `data/db.py` imports nothing from `data`, so there is no import cycle.
- **Temp write:** `connect_random_cache_db` plus `populate_random_cache`. On an empty temp file `refresh` makes no difference, so pick one value and say so.
- **Cleanup:** both connections close in a `finally`. On an exception the temp file and its journal are unlinked and the exception is re-raised.
- **New imports:** `os` and `time`.

**What depends on it:** the Engine worker, `precompute-random-rowids.py`, and the new in-process tests.

**Regression risk: high.**
- **Hot journal:** see the dedicated entry.
- **`size <= 0`:** `populate_random_cache` returns 0 at lines 50-51 before creating the schema. The temp file then has no `random_rowids` table, so the swap's check query fails, or the job's `os.replace` installs a table-less file. The job's `--size 0` reaches this; today it logs `size=0`.
- **Source rows:** the source must yield `sqlite3.Row`, because line 70 reads `total_row["total"]`. `connect_readonly_db` does.
- **Deadline handler:** the source connection carries it. The worker thread never sets `_deadline.at`, so the handler is a no-op, but it is still called every 10 000 VM instructions.
- **Filesystem:** the temp file must sit in the *resolved* target's directory so that `os.replace` stays on one filesystem. server.py resolves the path at line 318.
</impact>
<impact path="engine/server/data/random_cache.py" element="hot-journal hazard: per-pid temp name + default rollback journal (plan build steps 1 and 3) combined with the swap helper opening the served connection on the temp path">
**What changes:** this is a defect in the plan as written.
- SQLite fixes a connection's journal name at open, as `<opened path>-journal`.
- The swap helper opens the served `mode=ro` handle on `random-cache.tmp.<pid>.db` and then renames that file. From then on, before each read, the handle looks for a hot journal at `random-cache.tmp.<pid>.db-journal`.
- The same Engine's next build recreates exactly that name, and during its large `executemany` and commit it writes a rollback journal there. The build holds its RESERVED lock on the *new* inode, so the served inode shows no reserved lock, and the journal looks hot.
- A read-only connection cannot roll it back, so every read fails (SQLITE_READONLY_ROLLBACK / `OperationalError`) until the journal is deleted.

Before the first swap the served handle is named `random-cache.db`, so the first build is safe. From the second build on, every build breaks reads. In production that means the hourly build after a refresh-on start.

**What depends on it:** `fetch_random_rowids` → `random_videos.fetch_random_rows_from_cache:438`, which catches nothing, then `handlers/similar.py:390-392` and `:458-460`, which re-raise any non-interrupt `OperationalError`. It also reaches `builder.py:97-99`: the random, explore and similar-from-likes layers.

**Regression risk: high.** It breaks the requirement that no request is failed by a rebuild, and none of the planned tests reads during a second same-pid build. Possible fixes:
- (a) `PRAGMA journal_mode=MEMORY` or `OFF` on the temp connection. This keeps the per-pid name and no WAL. A crash leaves at worst a bad temp file that is never renamed into place.
- (b) A temp name unique per build (pid plus a counter). This changes the name the requirements fix.
- (c) Reopen on the target path after the rename. This brings back the reopen-failure problem the operator rejected.

Add a test that swaps once, then pauses a second same-pid build after its journal reaches disk and reads through the served handle. A smaller variant exists in a mixed-version rollout: an old-code Engine writing `random-cache.db` in place, beside a new Engine whose handle is named `random-cache.db` but sits on an older inode.
</impact>
<impact path="engine/server/data/random_cache.py" element="ensure_random_cache_schema() (lines 21-30)">
**What changes:** nothing in this function. The job's `--reset` branch (`precompute-random-rowids.py:74-79`) goes, and with it that caller. The job's import of it at line 15 then becomes unused.

**What depends on it:** `populate_random_cache` (line 58), the retired tests (`test_random_cache.py:81`, `:116`, `:152`), and any new test that seeds a cache. Issue 08's plan (`docs/project/plans/17-stable-ann-ids.md:105`) makes this function detect an old-shape table and repopulate it. That plan assumes an in-place write at start, which this build removes (see the plan-17 entry).

**Regression risk:** low.
</impact>
<impact path="engine/server/data/random_cache.py" element="fetch_random_rowids() (lines 185-200)">
**What changes:** the code is unchanged. It now runs on a `connect_readonly_db` handle, which carries the deadline progress handler. `docs/project/plans/archive/05-shared-connection-deadline-guard.md:155` records that `random_cache_db` was deliberately left unbounded.

**What depends on it:** `random_videos.py:438`, which runs inside the request's `statement_deadline` (`handlers/similar.py:388`, `:456`).

**Regression risk:** low-medium. The `COUNT(*)` plus `OFFSET` read on a ~486k-row table can now be interrupted and answered with 503 "Query time limit exceeded", where it used to run to completion. The plan does not name this change. This function is also where the hot-journal error surfaces.
</impact>
<impact path="engine/server/data/random_cache.py" element="optional home for the worker loop / usable-check (module-level functions)">
**What changes:** the plan leaves the worker's location open. Tests cannot import server.py in pytest's interpreter, because it imports faiss (`test_internal_events.py:42` and `test_server_config.py:73` record this). So the in-process build, swap, failure and interval-0 tests need the worker loop and the "open if usable" check as module-level functions taking plain paths, an owner, a lock and an `Event`. That points at `data/random_cache.py`, or `data/db.py` for a generic helper, not closures inside `main`.

**What depends on it:** the new tests and server.py.

**Regression risk:** medium for testability. If the loop is left in `main`, only Engine-level tests can cover it.
</impact>
<impact path="engine/server/data/db.py" element="new generic swap helper beside connect_readonly_db() (after line 94)">
**What changes:** a new function `(temp_path, target_path, lock, owner, attr, check_sql)`:
1. `connect_readonly_db(temp_path)`;
2. `execute(check_sql).fetchone()`; on failure close the connection and raise;
3. `os.replace`; on failure close the connection and raise;
4. `with lock: old = getattr(owner, attr); setattr(owner, attr, conn)`, then close `old` outside the lock if it is not `None`.

It needs `import os`. The docstring should follow the style of `statement_deadline` and `install_deadline_handler`.

**What depends on it:** the Engine worker, the reuse planned by issue 24 (`docs/project/issues/24-similarity-cache-shadow-swap.md:17`, "reopen the similarity DB under similarity_db_lock"), and the new tests.

**Regression risk: high.**
- The handle it installs is named by the temp path, which is the hot-journal hazard.
- `install_deadline_handler` runs inside `connect_readonly_db`, before publication, which honours the warning at lines 31-41.
- Closing `old` is safe only because every reader holds `random_cache_lock` across the whole `fetch_random_rowids` (`random_videos.py:437-438`).
- The helper must never install `None`, because line 435 checks it without the lock.
- If step 3 fails after step 2 succeeded, the connection must be closed, or a handle to the temp inode leaks.
- Issue 24's similarity DB is opened writable (`connect_similarity_db`, line 104) and is written at serve time (`DEFAULT_SIMILARITY_CACHE_REFRESH`). A read-only swap there changes that contract, and issue 24 needs to know.
</impact>
<impact path="engine/server/data/db.py" element="connect_readonly_db() (lines 84-94)">
**What changes:** the code is unchanged. It gains four callers: the build's source connection, server.py's "open if usable" step, the swap helper, and the job's reuse check. Its docstring ("a second, read-only handle on the same database file … statements long enough …") no longer describes these uses and wants rewording.

**What depends on it:** `server.py:321` (`search_db`), plus the new callers.

**Regression risk:**
- Opening a missing file with `mode=ro` raises `sqlite3.OperationalError: unable to open database file`. Callers must treat that as "not usable", and should check existence first.
- Every connection it opens gets the deadline handler (see `fetch_random_rowids`).
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_random_rows_from_cache() (lines 431-449) and import line 10">
**What changes:** code and signature are unchanged. `server.random_cache_db` can now be replaced at any time, and it is `None` from start until the first build when the cache is unusable.

**What depends on it:** `handlers/similar.py:671`, `recommendations/builder.py:97-99` (which feeds `candidates/random_videos.py:133`, `candidates/explore_range.py:154` and `candidates/similar_from_likes.py:44`), and `server.py:98` and `:397`.

**Regression risk:** medium.
- While the handle is `None`, every consumer falls back to `fetch_random_rows(server.db)` under `db_lock`, which is heavier.
- It catches nothing, so the hot-journal error propagates from here.
- Line 10 means an import error in the reworked `random_cache.py` breaks every importer of `random_videos`.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_fetch_random_rows() (lines 669-681); do_POST/do_GET error wrappers (lines 385-393, 453-461); /api/health (lines 470-477)">
**What changes:** no code change. The behaviour behind it changes in three ways:
- cache reads are now deadline-bounded and can return 503;
- the DB fallback serves until the first swap;
- a non-interrupt `OperationalError` from the cache, such as the hot-journal error, is re-raised and fails the request.

`/api/health` touches no cache, so it answers as soon as the Engine listens, which is what the acceptance needs. It does not report cache state.

**What depends on it:** the random feed mode and `random=1`, and every health probe (conftest fixture, smoke script, operators).

**Regression risk:** medium until the hot-journal hazard is fixed, low after. It is worth an Engine-level assertion that the random feed answers 200 across two swaps.
</impact>
<impact path="engine/server/api/recommendations/builder.py" element="fetch_random_rows_from_cache_filtered (lines 97-99) and consumers candidates/random_videos.py:131-137, candidates/explore_range.py:152-158, candidates/similar_from_likes.py:43-52">
**What changes:** nothing in code.

**What depends on it:** the home and upnext profiles' random and explore layers, and similar-from-likes when its cache is empty.

**Regression risk:** low-medium. These consumers get the same `None` → DB fallback (`with server.db_lock: fetch_random_rows(server.db, …)`), the same deadline bound and the same hot-journal exposure as the handler.
</impact>
<impact path="engine/server/api/server.py" element="imports (lines 25-82, 85, 105)">
**What changes:**
- Line 105 `from data.random_cache import connect_random_cache_db, populate_random_cache` becomes the build function, plus the worker and the usable-check if they live there.
- Line 85 gains the swap helper.
- The `server_config` import block gains `DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` and `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`.
- `threading` is already imported (line 16).

**What depends on it:**
- Every Engine start.
- `test_server_config.py`'s VARIANT_RUNNER (line 165) runs server.py against the real config module.
- `test_internal_events.py:47` and `test_video.py:162,198` `import server` in Engine-interpreter children and read module attributes such as `server.fetch_random_rows_from_cache` and `server.MAX_LIKES`.

**Regression risk:** low, provided every imported name exists. A missing name breaks those child tests as well as the Engine.
</impact>
<impact path="engine/server/api/server.py" element="parse_args(): --dev help (lines 156-163) and refresh flags help (lines 178-191)">
**What changes:**
- `--dev` help should say that it also sets the periodic interval to 0 unless `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` is set.
- The refresh flags' help ("Force/Disable random cache refresh on startup") stays accurate, since they govern only the startup build. It could name the variable for the periodic build.

**What depends on it:** `test_server_config.py:76` checks only `--port PORT` in the help output.

**Regression risk:** very low.
</impact>
<impact path="engine/server/api/server.py" element="main(): refresh and interval resolution (lines 307-310)">
**What changes:** new resolution: `interval = RANDOM_CACHE_REFRESH_INTERVAL_MINUTES if it is not None else (0 if args.dev else DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES)`.

**What depends on it:** the worker-start decision and the log line at 474-478.

**Regression risk:** low-medium. Every test-started Engine runs without `--dev` and without the variable, so each gets interval 60 and an idle worker: `conftest.py:121`, the 8 Engines at `test_random_cache.py:201`, `test_server_config.py:218`, `test_similar.py:670` and `tests/run-arch-split-smoke.sh:526`. A test session longer than 60 minutes would run a full filtered build inside the session Engine, costing CPU and competing with requests that have 5 s deadlines, and would rename over the checkout's `random-cache.db` mid-suite. Test Engines can set the variable to 0.
</impact>
<impact path="engine/server/api/server.py" element="main(): startup cache block (lines 328-339) → 'open if usable' + startup-build decision">
**What changes:**
- The `mkdir` at line 328 stays; the build's temp file needs the directory.
- The `connect_random_cache_db` + `populate_random_cache(db, …, reuse_non_empty=True)` block is replaced. If the file exists, open it with `connect_readonly_db`, check `random_rowids` in `sqlite_master` and `COUNT(*) > 0` (both fully fetched), and on any failure close it and use `None`, catching `sqlite3.Error`.
- `startup_build_needed = random_cache_refresh or not usable`.
- The build no longer uses the shared writable `db` (line 331); it uses `db_path` (line 315).

**What depends on it:**
- `SimilarServer(...)` (line 435);
- the `finally` (lines 500-501);
- the 8-Engine test's pre-asserts (`test_random_cache.py:169-175`), which read the checkout cache. Health now comes before any build, so on a checkout without the file the pre-assert at line 169 fails. Worktrees get a copy from `scripts/worktree-setup.sh:31`, and main has one today.

**Regression risk: high.**
- The checks must pass under another process's `BEGIN IMMEDIATE`, as in the 8-Engine test. RESERVED allows SHARED and no journal is written, so they do.
- The reason the cache is unusable should be logged.
- The catch must be `sqlite3.Error`, not a broad `Exception`.
- In production (refresh on) the old cache keeps serving until the background build swaps. Before this change, every start served a fresh cache.
</impact>
<impact path="engine/server/api/server.py" element="main(): new daemon worker + threading.Event, started just before serve_forever (between lines 463 and 482)">
**What changes:**
- A daemon `Thread` loop: run the optional startup build, then `while interval > 0: if event.wait(interval * 60): return`, then build.
- Each build sits in `except Exception` and logs one ok or failed line.
- The event is checked before the swap.
- No thread is started when no startup build is needed and the interval is 0.

**What depends on it:** `server.random_cache_db` and `server.random_cache_lock` (lines 242, 271), `db_path` (line 315), `random_cache_path` (line 318) and the filter constants (lines 333-337).

**Regression risk: high.**
- **GIL:** the filtered scan of up to the whole table, 500k-row target, is a pure-Python loop that competes with request threads at every refresh-on start and hourly.
- **Signals:** the SIGINT/SIGTERM → `KeyboardInterrupt` handler (lines 287-291) runs only in the main thread. The daemon flag is what keeps shutdown prompt, and it must fit inside `TimeoutStopSec=20`.
- **Order:** the thread must start after `server` exists.
- **Hot journal:** its second build triggers the hot-journal failure.
</impact>
<impact path="engine/server/api/server.py" element="main(): startup log line (lines 474-478)">
**What changes:** the line gains an interval token, for example `random_cache_refresh_interval_minutes=%d`. It keeps the key=value form that `logging_profiles` parses into `context`.

**What depends on it:** no test or doc quotes this line; grep finds none.

**Regression risk:** very low.
</impact>
<impact path="engine/server/api/server.py" element="main(): finally block (lines 493-501)">
**What changes:**
- `stop_event.set()`, with no join.
- Lines 500-501 close the startup local `random_cache_db`. They are replaced by closing whatever `server.random_cache_db` holds, read under `server.random_cache_lock`.

**What depends on it:** clean shutdown, and `TimeoutStopSec=20` (`DEPLOYMENT.md:99`).

**Regression risk:** medium.
- Closing the stale local after a swap closes an already-closed connection and leaks the live one.
- A request still running after `server_close` can hit a closed connection (`ProgrammingError`).
- A late swap after this point leaks a handle at exit, which the plan accepts.
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer.__init__ random_cache_db / random_cache_lock (lines 203, 242, 271)">
**What changes:** the signature is unchanged. The attribute is `None` more often at start and is mutated after construction, and the lock now also guards the swap.

**What depends on it:** `fetch_random_rows_from_cache`. `test_internal_events.py:51-52` and `test_video.py:169-170,228` build `SimilarServer` from its signature, with `random_cache_db=None`.

**Regression risk:** low, provided the constructor signature is not changed. Those tests fill parameters by introspection, so a new required parameter would silently get `None`.
</impact>
<impact path="engine/server/api/server_config.py" element="new _resolve_non_negative_int_env() beside _resolve_positive_int_env (lines 18-30)">
**What changes:** a new helper. It returns `None` when the variable is unset. On a `ValueError` or a negative value it raises `SystemExit(f"{name} must be a non-negative integer, got {raw!r}")`. Unlike its siblings it takes no default. How `""` is handled needs deciding: `_resolve_positive_int_env` exits on it, while `_resolve_weight_env` (lines 36-37) treats blank as unset. Its exit comment should follow line 28's style.

**What depends on it:** it runs at import. `server_config` is imported by server.py, the handlers, the jobs (`precompute-random-rowids.py:36`, `updater-worker.py:86` and others) and several tests, so an invalid value stops all of them.

**Regression risk:** low in code, medium operationally.
</impact>
<impact path="engine/server/api/server_config.py" element="random cache constants (lines 337-345): new DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES = 60 and RANDOM_CACHE_REFRESH_INTERVAL_MINUTES; comment of DEFAULT_RANDOM_CACHE_REFRESH (line 344)">
**What changes:**
- Two constants, each with a one-line `#` comment, go after line 345.
- The comment at line 344 ("Rebuild random cache on startup even if it already meets size") is reworded: the constant governs only the startup build, which now runs in the background after listening.
- `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` can be `None`, which is unusual in this file.

**What depends on it:** server.py and `LAYER_PARAMS.md`. `plan.md:74` warns that several lanes add constants here, so expect merge conflicts.

**Regression risk:** low. Arithmetic on the raw `None` raises `TypeError`, so only server.py's resolved value may be used.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="_EVENT_RULES / _classify_event (lines 31, 172-199)">
**What changes:** nothing in code. The new start, ok and failed lines are INFO with no matching rule, so they are tagged verbose only. Only WARNING and above always show (lines 85, 174), and key=value tokens are parsed into `context`.

**What depends on it:** Engine-level tests must parse the JSON `message`, as `test_server_config._messages` (line 200) does. In focused mode, `engine/watch-engine-logs.sh` hides a failed build.

**Regression risk:** low in code, medium for operability. Consider WARNING for `failed`; the plan says INFO.
</impact>
<impact path="engine/server/db/jobs/precompute-random-rowids.py" element="main() (lines 29-89)">
**What changes:**
- The argparse block (lines 31-66) and the final `random cache size=%d` line (line 89) stay.
- **Reuse:** without `--reset` or `--refresh`, if `--out` exists and `random_rowids` holds at least `--size` rows, the job logs the count and exits without writing.
- **Build:** otherwise it calls the build function and then `os.replace` onto `--out`.
- The `--reset` DELETE block and its comment (lines 74-79) go.
- `out_path.parent.mkdir` (line 72) stays.
- `data.db` is importable via line 11.

**What depends on it:** `scripts/run-dataset-build.sh:262-264`, `DATA_BUILD.md` §6, and any running Engine, which stays on the old inode.

**Regression risk:** medium.
- The reuse check must fall through when the file or table is missing.
- `--size 0` hits the empty-temp edge.
- A replaced file takes the job user's ownership and umask.
- The job makes one build and exits, so it never meets the hot-journal hazard.
- An invalid interval in the job's environment stops it at the `server_config` import (line 36).
</impact>
<impact path="engine/server/db/jobs/precompute-random-rowids.py" element="connect_source_db() (lines 20-26) and imports (lines 4-17)">
**What changes:**
- `connect_source_db` duplicates `connect_readonly_db` by hand and becomes dead once the build opens the source itself; remove it.
- The imports become the build function plus `connect_readonly_db`, or the shared table check.
- `import sqlite3` may become unused.
- `connect_random_cache_db` and `ensure_random_cache_schema` drop out of the import.

**What depends on it:** only this file.

**Regression risk:** low: dead imports, or a second read-only opener left behind.
</impact>
<impact path="scripts/run-dataset-build.sh" element="random stage (lines 260-265), RANDOM_DB (line 56)">
**What changes:** nothing. `--reset` now means "build fresh through temp and replace".

**What depends on it:** manual dataset builds. The updater does not run this stage; `updater-worker.py` runs only the similarity precompute.

**Regression risk:** low. The exit code and output are unchanged.
</impact>
<impact path="scripts/worktree-setup.sh" element="random-cache.db copy and its comment (lines 30-31)">
**What changes:** the comment "Rewritten by refresh-on starts and when missing or empty: private." becomes inaccurate. The file is now replaced by rename at startup builds and at every periodic build. It must stay a private `cp` and not a symlink: server.py `.resolve()`s the path (line 318), so a symlink would put the temp file and the rename in main's `db/`.

**What depends on it:** every lane worktree.

**Regression risk:** low; only the comment changes.
</impact>
<impact path="tests/active/test_random_cache.py" element="module docstring (lines 1-9), import (line 32), constants (lines 35-41), four in-process tests (lines 67-161)">
**What changes:**
- These tests move to a new `tests/archive/<subdir>/`, as `tests/archive/upnext_random_draw/` did:
  - `test_random_cache_connection_waits_longer_than_sqlite_default`;
  - `test_rebuild_waits_for_a_write_lock_held_past_sqlite_default`;
  - `test_refresh_off_reuses_a_short_cache_without_writing`;
  - `test_refresh_off_builds_a_missing_or_empty_cache[missing|empty]`.
- The first four docstring bullets go.
- `SQLITE_DEFAULT_BUSY_MS`, `HOLD_SECONDS`, `STALE_ROWID` and `SEEDED_ROWS` become unused unless reused.
- New in-process tests cover:
  - build;
  - swap;
  - forced failure (the file is left intact and the temp file removed);
  - interval 0;
  - "open if usable" for missing, no-table, empty and non-empty;
  - the startup decision;
  - the hot-journal case;
  - reads concurrent with repeated swaps.
- `_source_db` (lines 49-59) can be reused for building.

**What depends on it:** `tests/last_test_validation.json`.

**Regression risk:** retired tests left active fail with `TypeError`, or on a `busy_timeout` that is now 5000. There is no pytest testpaths config, so the archive stays uncollected only because runs name `tests/active`.
</impact>
<impact path="tests/active/test_random_cache.py" element="test_engines_starting_at_once_all_become_healthy (lines 164-234)">
**What changes:** the assertions stay. The wording that explains itself through in-place writes and sqlite's busy wait is reworded: the docstring (line 167), the controls (lines 172-175, 181-187) and the straggler comment (lines 225-226).

**What depends on it:**
- A non-empty checkout `random-cache.db`. The session Engine no longer builds before health, so on a fresh checkout without the file, line 169 raises.
- `DEFAULT_RANDOM_CACHE_SIZE` staying above the filtered fill (issue 32 recorded 486,662 rows against 500,000).

**Regression risk:** medium.
- Each Engine opens the cache read-only, which works under RESERVED, and becomes healthy fast.
- With interval 60 each Engine starts an idle worker, and the test stops them long before a tick.
- Seeding the cache in the test would remove the fresh-checkout dependency.
</impact>
<impact path="tests/active/test_random_cache.py" element="new Engine-level tests (health before build, short-interval swap)">
**What changes:** new tests start real Engines with `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` set. With the default config they would build a full filtered cache from the real `whitelist.db` and rename it over the checkout's `engine/server/db/random-cache.db` (`DEFAULT_RANDOM_CACHE_DB_PATH`, `server_config.py:389`). That violates the rule in `plan.md:143-145` that tests write only temporary copies, and it costs minutes of CPU. The VARIANT_RUNNER technique in `test_server_config.py:165-178` can override `DEFAULT_RANDOM_CACHE_DB_PATH` with an absolute tmp path (`repo_root / absolute` yields the absolute path, `server.py:318`) and override `DEFAULT_RANDOM_CACHE_SIZE`.

A minute is the finest interval, so a "short interval" test waits at least 60 s per tick unless the worker's tick unit can be injected.

**What depends on it:** the suite's runtime, and the checkout's cache file.

**Regression risk:** medium. Engine tests that write the real cache break the isolation between lanes and slow the suite.
</impact>
<impact path="tests/active/conftest.py" element="engine fixture comments (lines 113-115); ENGINE_START_LOCK (lines 100-102, 116-117)">
**What changes:** the comments at 113-114 are reworded: no start writes `random-cache.db` in place, and builds go to a temp file in the background. The `ENGINE_START_LOCK` code is unchanged.

**What depends on it:** `test_server_config.py:215` and `test_similar.py:667`, which also take the lock, and every test that uses the session Engine. Without a usable cache, that Engine is healthy with `random_cache_db=None`, serves random from the DB, and runs a startup build in the background. That build competes for CPU with the tests.

**Regression risk:** low.
</impact>
<impact path="tests/active/test_server_config.py" element="module docstring (lines 1-20), _run (line 41), parametrized cases (lines 55-69), VARIANT_RUNNER (line 165)">
**What changes:** the likely home for the interval tests:
- unset → `None`;
- `0` and `7` → int;
- `abc`, `-1` and `7.5`, plus `""` depending on the decision → exit 1, with the last stderr line naming the variable.

`--dev` versus explicit-value precedence needs a real Engine, where the startup log line carries the interval, or an extracted pure function. The docstring gains bullets.

**What depends on it:** `_run` strips only the one variable from the child's environment.

**Regression risk:** low.
</impact>
<impact path="tests/active/test_internal_events.py" element="ENGINE_INGEST child (lines 43-61)">
**What changes:** nothing. It imports `server` and builds `SimilarServer` by signature introspection.

**What depends on it:** server.py importing cleanly under the Engine interpreter.

**Regression risk:** low, unless server.py gains a bad import or a new constructor parameter.
</impact>
<impact path="tests/active/test_video.py" element="ANSWER_CHILD / PERSIST_CHILD (lines 158-230)">
**What changes:** nothing. These children import `server`, use `server.fetch_random_rows_from_cache` and friends, and build `SimilarServer` with `random_cache_db=None`, so they exercise the DB fallback.

**What depends on it:** server.py's module-level names.

**Regression risk:** low.
</impact>
<impact path="tests/active/test_similar.py" element="LAUNCH Engine start (lines 667-670)">
**What changes:** nothing. The Engine runs without `--dev`, so it gets an idle interval-60 worker and does no build before listening.

**What depends on it:** the checkout cache, read-only.

**Regression risk:** low.
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="Engine start (lines 523-534)">
**What changes:** nothing. It starts with `--no-random-cache-refresh` and without `--dev`, so it gets an idle 60-minute worker and becomes healthy sooner when the cache is missing.

**What depends on it:** the smoke flow.

**Regression risk:** low.
</impact>
<impact path="tests/last_test_validation.json" element="test_random_cache.py entry (line 212) and ids (lines 857-877)">
**What changes:** the retired ids disappear and new ones appear. The file is regenerated by the validator, not edited by hand, and `plan.md:146-147` says to take main's copy on merge.

**What depends on it:** the validation tooling.

**Regression risk:** low.
</impact>
<impact path="engine/install-engine-service.sh" element="unit Environment/ExecStart (lines 180-183)">
**What changes:** nothing. The unit runs without `--dev` or refresh flags, so every contour gets a background startup build and an hourly build unless `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` is set by an `Environment=` line or in `.env.bridge`.

**What depends on it:** the production CPU budget. The prod and dev contours on one host each build hourly, into their own checkout's cache.

**Regression risk:** medium operationally: a new recurring full scan inside the serving process.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="server_config import (line 86); Engine stop/start (lines 1041-1047, 1141-1147)">
**What changes:** nothing in code. After a pipeline run the Engine restarts. Under refresh on it now listens at once and rebuilds the random cache in the background from the freshly merged `whitelist.db`, instead of rebuilding before listening. An invalid interval value in the updater's environment stops it at import.

**What depends on it:** the updater timer.

**Regression risk:** low.
</impact>
<impact path=".gitignore" element="*.db / *.db-journal (lines 11-12)">
**What changes:** nothing. A leftover `random-cache.tmp.<pid>.db` and its `-journal` already match.

**What depends on it:** `git status`.

**Regression risk:** none.
</impact>
<impact path="docs/project/plans/17-stable-ann-ids.md" element="P3 random cache (line 105), AC6 (line 59), observation line 33">
**What changes:** nothing is edited in this build, but a later conflict follows from it. Plan 17 (issue 08, `ready-for-agent`, wave 5a) has `ensure_random_cache_schema` detect an old-shape `random_rowids` and repopulate it at Engine start. It also cites `server.py:319-320` and `random_cache.py:43-45`. After this build, the Engine never writes the served file at start: an old-shape cache that is "usable" (table present, non-empty) under refresh off would be served as is. The detection therefore has to move into the "open if usable" check, which would treat an old shape as unusable, or into the build.

**What depends on it:** the issue-08 lane.

**Regression risk:** medium, deferred. It should be recorded so that lane does not assume an in-place write at start.
</impact>
<impact path="DATA_BUILD.md" element="outputs list (line 13) and §6 (lines 268-280)">
**What changes:** line 280 is rewritten:
- the job builds a temp file and renames it over `--out`, and it never waits on an Engine, so the "up to an hour" sentence goes;
- without `--reset` or `--refresh` it exits early when `--out` already holds `--size` rows;
- a running Engine keeps its old copy until its own next build or restart;
- the Engine builds in the background at start (refresh on, or no usable cache) and every `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`.

Line 13 may note that a leftover `random-cache.tmp.<pid>.db` is safe to delete.

**What depends on it:** operators.

**Regression risk:** doc only.
</impact>
<impact path="engine/server/api/recommendations/docs/LAYER_PARAMS.md" element="Random Cache Params (Global) (lines 128-135); source lines 76 and 114">
**What changes:**
- Line 130 is reworded: the startup build runs in the background after the Engine listens, and refresh off with a usable cache means no build.
- A new bullet for `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`: environment variable, non-negative, default 60, 0 under `--dev` when unset, an explicit value wins, 0 disables, an invalid value exits naming the variable.
- A note on the atomic swap.
- Lines 76 and 114 ("or random from DB if cache is empty") should also cover a missing or not-yet-built cache.

**What depends on it:** `OVERVIEW.md:62` and `DATA_BUILD.md:280`, which point here.

**Regression risk:** doc only.
</impact>
<impact path="engine/server/api/recommendations/docs/OVERVIEW.md" element="§2 item 4 Random cache (lines 57-62); layer source lines 78, 94, 115">
**What changes:** line 62 covers background and periodic builds, the atomic swap, and random pools served from the DB while no usable cache exists. Lines 78 and 94 ("or random from DB if cache is empty") are aligned with that. The plan's doc list omits this file.

**What depends on it:** readers.

**Regression risk:** doc only.
</impact>
<impact path="DEPLOYMENT.md" element="§2 env paragraph (after line 114), Triage table (line 160), §4 Run (lines 234-251)">
**What changes:**
- **§2:** a paragraph for `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`, in the shape of the line-114 retention paragraph: where to set it, default 60, 0 disables, the per-build CPU cost of a full scan inside the Engine, and that the units run without `--dev`.
- **Triage:** a row for the "must be a non-negative integer" exit, which also stops the jobs and the updater.
- **§4:** health answers before any random-cache build; the random feed comes from the DB until the first `ok` line; the build lines are INFO, so they show in verbose mode only.
- **Optional:** leftover temp files are safe to delete.

**What depends on it:** operators.

**Regression risk:** doc only.
</impact>
<impact path="docs/project/issues/22-random-cache-background-refresh.md" element="Status line and Comments; file location">
**What changes:** `Status: enhancement, complete`, plus a closing comment naming the plan and the deltas from the issue text: a per-pid temp name instead of `random-cache.tmp.db`, no WAL, a read-only serving handle, the validate-first helper in `data/db.py`, and the hot-journal fix chosen. The file moves to `docs/project/issues/archive/`.

**What depends on it:** `plan.md:72`, issue 23 line 27 and issue 26 line 30 reference it by slug.

**Regression risk:** doc only.
</impact>
<impact path="docs/project/issues/23-random-cache-nonblocking-startup.md" element="Status line and Comments (lines 3, 29-37); file location">
**What changes:** archived as complete the same way. The closing comment records that the 3600 s wait and `reuse_non_empty` are retired, and names the simplifications against lines 16-18: no backoff, no maximum build runtime, and no `off`/`async` startup-mode setting, since the refresh flags stand in for it.

**What depends on it:** issue 26.

**Regression risk:** doc only.
</impact>
<impact path="docs/project/issues/plan.md" element="lane 2d row (line 72), lane 4b row (line 91)">
**What changes:** mark lane 2d delivered, and point lane 4b (issue 24) at the swap helper and its hot-journal caveat.

**What depends on it:** wave planning.

**Regression risk:** doc only.
</impact>
<impact path="docs/project/issues/24-similarity-cache-shadow-swap.md" element="Comments (line 32)">
**What changes:** optional comment: the generic validate-first helper now exists in `data/db.py`. It carries two cautions. A handle opened on a temp name must not share that name with a later rollback-journal write. And the helper installs a read-only handle, while the similarity DB is written at serve time today.

**What depends on it:** the issue-24 lane.

**Regression risk:** doc only. Without the note, lane 24 may repeat the defect.
</impact>
<impact path="docs/project/issues/26-zero-downtime-deploy.md" element="Related (line 30) / Comments">
**What changes:** optional comment: 23 is delivered, and sibling Engines stay on the old inode until their own next build or restart. That is the inode-check candidate the plan defers to 26.

**What depends on it:** the issue-26 lane.

**Regression risk:** doc only.
</impact>
<impact path="docs/project/roadmap.md" element="delivered list (lines 15-23); runtime reliability line (line 156)">
**What changes:** a delivered entry for issues 22+23 linking the plan, following the existing delivered-entry pattern at lines 21-23. Line 156's chain `22 -> 23 -> 24/25 -> 26` could mark 22 and 23 done.

**What depends on it:** roadmap readers.

**Regression risk:** doc only.
</impact>
<impact path="docs/project/adr" element="possible new ADR (next number 0007): caches replaced by temp build + rename + read-only handle swap, no WAL">
**What changes:** optional. This is a cross-cutting decision that issue 24 is meant to reuse: rollback journal, no WAL, validate-first swap, sibling Engines left on the old inode. It fits the ADR convention in `docs/project/domain.md`. Uncertain whether the operator wants one.

**What depends on it:** issues 24 and 26.

**Regression risk:** doc only.
</impact>
</impacts>


## Documentation to update

- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md §6 now describes the temp-file-and-rename job and the Engine's background builds. The claim that the job waits up to an hour is gone.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: I updated LAYER_PARAMS.md to say random-cache builds run in the background, added the interval setting, and changed the DB fallback wording to match.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md: §2 item 4 now covers when the random cache is built (background worker, at start and on an interval) and the DB fallback; the explore and random source lines say when the DB is used.
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md now documents `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`, adds a triage row for a bad value, and explains how the Engine serves while random-cache builds run.
- [x] `engine/server/api/server.py` - updated: I updated the `--dev` help, the two refresh-flag help texts and the `[similar-server] mode=` startup log line in `engine/server/api/server.py`. Nothing was run.
- [x] `engine/server/api/server_config.py` - updated: `server_config.py`: the `DEFAULT_RANDOM_CACHE_REFRESH` comment now describes the startup build as it works today, and the interval resolver's comment now says an explicit value wins over `--dev`.
- [x] `engine/server/data/db.py` - updated: Reworded the `connect_readonly_db` docstring to cover what it is used for now, and added a warning that `mode=ro` raises on a missing file.
- [x] `scripts/worktree-setup.sh` - updated: Reworded the `random-cache.db` comment in `scripts/worktree-setup.sh`: every build replaces the file by rename, and it has to stay a private copy rather than a symlink.
- [x] `tests/active/conftest.py` - updated: Reworded the `engine` fixture comment in `tests/active/conftest.py`: an Engine start no longer writes `random-cache.db` in place or waits on a lock. The `ENGINE_START_LOCK` reason and the retry are kept. Only comments changed.
- [x] `tests/active/test_random_cache.py` - updated: Reworded the 8-Engine test's docstring, comments and one assert message so they describe the read-only startup open instead of in-place writes. Comments and one message string only; no test logic changed. The operator approved the change to this gated file.
- [x] `docs/project/issues/22-random-cache-background-refresh.md` - updated: Issue 22 closed as delivered: `Status: enhancement, complete`, a `### Delivered` comment added, and the file written to `docs/project/issues/archive/22-random-cache-background-refresh.md`. **The original `docs/project/issues/22-random-cache-background-refresh.md` still has to be deleted.** I have no tool that deletes files.
- [x] `docs/project/issues/23-random-cache-nonblocking-startup.md` - updated: Issue 23 is closed as delivered: status set to `enhancement, complete`, a `### Delivered` comment added, and the file written to `docs/project/issues/archive/23-random-cache-nonblocking-startup.md`. **The original `docs/project/issues/23-random-cache-nonblocking-startup.md` still needs deleting, because I have no delete tool.**
- [x] `docs/project/issues/plan.md` - updated: plan.md: lane 2d is marked delivered with its note reworded, and lane 4b now points at `swap_readonly_connection` and its two caveats.
- [x] `docs/project/issues/24-similarity-cache-shadow-swap.md` - updated: Issue 24: added a comment that points at `swap_readonly_connection` as the swap/reopen helper, with its two cautions.
- [x] `docs/project/issues/26-zero-downtime-deploy.md` - updated: Added a comment to issue 26 saying prerequisite 23 is delivered (with 22), plus three effects on a blue/green pair that shares one checkout.
- [x] `docs/project/roadmap.md` - updated: Added a Delivered entry for issues `22` and `23` and marked both as delivered in the runtime-reliability order.
- [x] `docs/project/plans/17-stable-ann-ids.md` - updated: Plan 17 updated: its current-code description of the random cache is correct again, and the plan for detecting an old-shape cache has moved to `open_random_cache_if_usable` and the precompute job's keep check.

## Implementation plan

# Draft: random cache background refresh (issues 22 + 23)

## What the build has to prove (test inventory, worked out first)

| # | Behaviour | Level | Where |
|---|---|---|---|
| T1 | `build_random_cache` writes `<stem>.tmp.<pid><suffix>` beside the active file, with positions 1..20 over source rowids 1..20, leaves no `-journal`, and does not touch the active file | in-process | `test_random_cache.py` |
| T2 | `refresh_random_cache` swaps: the active file is the new inode, `owner.random_cache_db` is a new object and reads the new rows, the old connection is closed (`ProgrammingError` on use), and no temp file remains | in-process | same |
| T3 | Forced build failure (patched `populate_random_cache` raises after writing): returns False, logs `failed`, the active file's bytes are unchanged, the serving connection is the same object and still reads, and the temp file and `-journal` are gone | in-process | same |
| T4 | Swap-stage failure (`swap_readonly_connection` with a check SQL that fails): raises, the active file is intact, `owner.<attr>` is unchanged, and the temp file is still there (the caller removes it). Through `refresh_random_cache` the temp file is removed | in-process | same |
| T5 | Stop set before the swap: no swap happens and the temp file is removed | in-process | same |
| T6 | `run_random_cache_worker(startup_build=False, interval_seconds=0)` returns at once with no temp file and the owner unchanged. `startup_build=True, interval_seconds=0` builds exactly once | in-process | same |
| T7 | `open_random_cache_if_usable`: missing, no table and empty each give `None`; non-empty gives a `mode=ro` connection whose count matches. Still usable while another connection holds `BEGIN IMMEDIATE` on the file (replaces the retired refresh-off reuse test) | in-process | same |
| T8 | Hot journal: after one swap, a second same-pid build is paused after its first uncommitted write. During the pause, no `<served name>-journal` exists and `fetch_random_rowids` on the served handle succeeds. Control (parametrized): with the `journal_mode=MEMORY` line patched out, the same read raises `OperationalError`, which proves the test can see the defect | in-process | same |
| T9 | Three reader threads loop `fetch_random_rowids` under the lock while the main thread runs 10 `refresh_random_cache` cycles: no exception and no empty result | in-process | same |
| T10 | A refresh-on Engine (variant runner: tmp absolute cache path, size 200, and a gate patched into `data.random_cache.build_random_cache`) answers `/api/health` 200 and random-feed 200 while the build is held. Release the gate: an `ok` line appears and the tmp file holds 200 rows | Engine | same |
| T11 | Short interval (variant: `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES=0.25`, size 200, tmp path, refresh off, file missing): ≥3 `ok` lines and a changed inode on each. `POST /recommendations?random=1` is looped throughout and every answer is 200 and non-empty. After an `ok`, the returned `(video_id, instance_domain)` pairs map (via read-only `whitelist.db`) into the current file's rowids | Engine | same |
| T12 | The session Engine (refresh off, usable checkout cache, interval 0) logs no `random cache build start` line | Engine | same |
| T13 | The interval variable: unset and `""` give `None`; `0` and `7` give ints; `abc`, `-1` and `7.5` exit 1 with the last stderr line naming it. `random_cache_refresh_interval_minutes(dev)`: unset gives 60 / 0 (dev); `5` gives 5 / 5 | child process | `test_server_config.py` |
| T14 | `precompute-random-rowids.py` on a tmp source: a fresh `--out` gets positions 1..N over the source rowids; a second run without `--reset`/`--refresh` at ≥ size leaves the inode unchanged; `--reset` changes the inode; no temp file remains | child process | `test_random_cache.py` |
| — | 8-Engine test: assertions unchanged, wording reworded | Engine | same |

Retired to `tests/archive/random_cache_in_place/test_random_cache_in_place.py`: `test_random_cache_connection_waits_longer_than_sqlite_default`, `test_rebuild_waits_for_a_write_lock_held_past_sqlite_default`, `test_refresh_off_reuses_a_short_cache_without_writing`, and `test_refresh_off_builds_a_missing_or_empty_cache`. T7 and T6 carry the refresh-off reuse and missing/empty-builds coverage.

## Module map

| File | Change |
|---|---|
| `engine/server/data/random_cache.py` | Drop the 3600 s constant and `reuse_non_empty`. Add a journal-in-memory pragma. Add public `random_rowids_count`, `random_cache_temp_path`, `remove_random_cache_temp`, `build_random_cache`, `open_random_cache_if_usable`, `refresh_random_cache`, `run_random_cache_worker` and `RANDOM_CACHE_CHECK_SQL`. The unfiltered branch gains the summary log line |
| `engine/server/data/db.py` | Add the generic `swap_readonly_connection` and `import os`. Reword the `connect_readonly_db` docstring |
| `engine/server/api/server_config.py` | Add `_resolve_non_negative_int_env`, `DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`, `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` and `random_cache_refresh_interval_minutes(dev)`. Reword the comment at line 344 |
| `engine/server/api/server.py` | Change imports; resolve the interval; replace the startup block with "open if usable"; start the worker before `serve_forever`; update the `finally`, the help text and the log line |
| `engine/server/db/jobs/precompute-random-rowids.py` | Reuse-or-build through the temp file and `os.replace`; `connect_source_db`, `--reset` DELETE and the unused imports go |
| tests / docs | As listed above and in the settled documentation list |

## `engine/server/data/random_cache.py`

```python
"""Provide random cache runtime helpers."""

from __future__ import annotations

import logging
import os
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from data.db import connect_readonly_db, swap_readonly_connection

# The swap's validation query: a finished cache must have the table and answer a count.
RANDOM_CACHE_CHECK_SQL = "SELECT COUNT(*) FROM random_rowids"


def connect_random_cache_db(path: Path) -> sqlite3.Connection:
    """Open a random cache file for writing; only a build's temp file is ever opened this way."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Journal in memory, not in <path>-journal: the served handle keeps this temp name after the rename, and a later same-pid build's on-disk journal at that name would look hot to it and fail every read.
    conn.execute("PRAGMA journal_mode=MEMORY")
    return conn


def ensure_random_cache_schema(conn: sqlite3.Connection) -> None:  # unchanged


def random_rowids_count(conn: sqlite3.Connection) -> int | None:
    """Return the number of cached rowids, or None when the random_rowids table is missing."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'random_rowids' LIMIT 1").fetchall():
        return None
    return int(conn.execute("SELECT COUNT(*) FROM random_rowids").fetchall()[0][0])
```

`_random_rowids_table_exists` is folded into `random_rowids_count`, so the `sqlite_master` query exists once. `fetchall` makes sure no statement is left holding SHARED on the file.

`populate_random_cache`:
- The signature loses `reuse_non_empty`; the positional seven stay.
- Lines 52-57 are deleted, and the reuse-at-size guard (59-61) stays.
- The unfiltered branch adds, before its `random.shuffle(rows)`:

```python
        logging.info(
            "random cache filtered=%s size=%d scanned=%d max_per_instance=%d max_per_author=%d",
            False,
            len(rows),
            len(rows),
            max_per_instance,
            max_per_author,
        )
```

Decision: this line logs the *effective* mode, `False`, because this branch is the unfiltered scan even when `filtered_mode=True` with both caps ≤ 0. The requested mode is already on the build's start line.

Limit: an empty source (`total == 0`) still returns before any summary line. That build's `ok size=0` line stands in for it.

```python
def random_cache_temp_path(active_path: Path) -> Path:
    """Return this process's build file beside `active_path`: <stem>.tmp.<pid><suffix>, so Engines sharing a checkout never write the same one."""
    return active_path.with_name(f"{active_path.stem}.tmp.{os.getpid()}{active_path.suffix}")


def remove_random_cache_temp(temp_path: Path) -> None:
    """Delete a build file and its rollback-journal sidecar, whichever exist."""
    for path in (temp_path, temp_path.with_name(f"{temp_path.name}-journal")):
        path.unlink(missing_ok=True)


def build_random_cache(
    source_path: Path,
    active_path: Path,
    size: int,
    filtered_mode: bool = False,
    max_per_instance: int = 0,
    max_per_author: int = 0,
) -> tuple[Path, int, float]:
    """Build a complete random cache into this process's temp file beside `active_path` and close it.

    The source is read through its own read-only connection, never the Engine's shared one, so a build blocks no request. The active file is not touched: the caller renames the returned temp file into place. On any exception the temp file is removed and the exception re-raised.

    :returns: (temp path, rowids written, elapsed seconds).
    """
    started = time.monotonic()
    temp_path = random_cache_temp_path(active_path)
    # A file of this name can only be left by an earlier process with the same pid.
    remove_random_cache_temp(temp_path)
    logging.info(
        "random cache build start target=%d filtered=%s max_per_instance=%d max_per_author=%d temp=%s",
        size,
        filtered_mode,
        max_per_instance,
        max_per_author,
        temp_path,
    )
    src_db: sqlite3.Connection | None = None
    cache_db: sqlite3.Connection | None = None
    try:
        try:
            src_db = connect_readonly_db(source_path)
            cache_db = connect_random_cache_db(temp_path)
            # Created here because populate_random_cache returns before its own schema step when size <= 0, and a table-less file fails the swap check.
            ensure_random_cache_schema(cache_db)
            # refresh=True states the intent; on an empty temp file the reuse-at-size guard cannot fire either way.
            count = populate_random_cache(src_db, cache_db, size, True, filtered_mode, max_per_instance, max_per_author)
            cache_db.commit()
        finally:
            if cache_db is not None:
                cache_db.close()
            if src_db is not None:
                src_db.close()
    except BaseException:
        remove_random_cache_temp(temp_path)
        raise
    return temp_path, count, time.monotonic() - started
```

Deviation from the plan: it returns the temp path as well as the count and elapsed time, so callers do not re-derive it.

```python
def open_random_cache_if_usable(path: Path) -> sqlite3.Connection | None:
    """Open the random cache read-only if it holds at least one rowid; otherwise log why and return None, which serves the random feed from the DB."""
    if not path.exists():
        logging.info("random cache unusable path=%s reason=missing", path)
        return None
    conn: sqlite3.Connection | None = None
    try:
        conn = connect_readonly_db(path)
        count = random_rowids_count(conn)
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        logging.info("random cache unusable path=%s reason=%s", path, exc)
        return None
    if not count:
        conn.close()
        logging.info("random cache unusable path=%s reason=%s", path, "no_table" if count is None else "empty")
        return None
    return conn


def refresh_random_cache(
    source_path: Path,
    active_path: Path,
    size: int,
    filtered_mode: bool,
    max_per_instance: int,
    max_per_author: int,
    owner: Any,
    stop_event: threading.Event,
) -> bool:
    """Build a new random cache and swap it in as `owner.random_cache_db` under `owner.random_cache_lock`.

    Never raises: a failure anywhere in the build, rename or reopen is logged, the temp file is removed, and the active file and serving connection are left as they were.

    :returns: True when a new cache was swapped in.
    """
    started = time.monotonic()
    temp_path = random_cache_temp_path(active_path)
    try:
        _, count, _ = build_random_cache(source_path, active_path, size, filtered_mode, max_per_instance, max_per_author)
        if stop_event.is_set():
            remove_random_cache_temp(temp_path)
            logging.info("random cache build skipped duration=%.2fs reason=stopping", time.monotonic() - started)
            return False
        swap_readonly_connection(temp_path, active_path, owner.random_cache_lock, owner, "random_cache_db", RANDOM_CACHE_CHECK_SQL)
    except Exception as exc:
        remove_random_cache_temp(temp_path)
        logging.info("random cache build failed duration=%.2fs reason=%s: %s", time.monotonic() - started, type(exc).__name__, exc)
        return False
    logging.info("random cache build ok duration=%.2fs size=%d target=%d path=%s", time.monotonic() - started, count, size, active_path)
    return True


def run_random_cache_worker(
    source_path: Path,
    active_path: Path,
    size: int,
    filtered_mode: bool,
    max_per_instance: int,
    max_per_author: int,
    owner: Any,
    stop_event: threading.Event,
    startup_build: bool,
    interval_seconds: float,
) -> None:
    """Run every random cache build of one Engine, one at a time: the startup build if asked, then one per interval until `stop_event` is set.

    Meant as a daemon thread's target, so an in-progress build never delays shutdown. A failed build is retried at the next tick; with `interval_seconds` 0 it is not retried.
    """
    if startup_build:
        refresh_random_cache(source_path, active_path, size, filtered_mode, max_per_instance, max_per_author, owner, stop_event)
    while interval_seconds > 0:
        if stop_event.wait(interval_seconds):
            return
        refresh_random_cache(source_path, active_path, size, filtered_mode, max_per_instance, max_per_author, owner, stop_event)
```

The worker takes `owner` with `random_cache_db` / `random_cache_lock`, the same contract `fetch_random_rows_from_cache(server)` already uses. Tests pass a `SimpleNamespace` with a `threading.Lock()`. The generic helper keeps the owner/attr interface, so this file is the only place that names the random attributes.

`fetch_random_rowids` is unchanged.

## `engine/server/data/db.py`

Add `import os`. `connect_readonly_db`'s docstring becomes:

"Open a read-only handle (`mode=ro`) on a database file. Used for the long search statements that must not hold the shared connection's lock, for a random cache build's source scan, and for serving and validating a swapped-in cache file. Every handle carries the deadline handler."

After `connect_readonly_db`:

```python
def swap_readonly_connection(
    temp_path: Path,
    target_path: Path,
    lock: threading.Lock,
    owner: object,
    attr: str,
    check_sql: str,
) -> None:
    """Validate a finished database file, rename it over `target_path`, and publish a read-only handle on it as `owner.<attr>`.

    The order makes every failure harmless: the handle is opened and `check_sql` run on the temp file first, then `os.replace`, and only then the in-memory swap, which cannot fail. If the open, the check or the rename fails, the new handle is closed, the exception propagates, and both the target file and `owner.<attr>` are as they were. The temp file is left for the caller to remove.

    `lock` is held only for the reference swap. The old handle is closed after the lock is released, which is safe only when every reader holds `lock` for the whole of its use of `owner.<attr>`. A reader may check the attribute for None without the lock; this helper never installs None.

    On POSIX the handle follows the inode through the rename, so it reads the new target file. SQLite fixes the handle's journal name at open as `<temp_path>-journal`, so no later write may put a rollback journal at that name while this handle lives: build the temp file with an in-memory journal, or use a temp name that is never reused.

    :param check_sql: A read the finished file must answer, e.g. a count on its table.
    """
    conn = connect_readonly_db(temp_path)
    try:
        conn.execute(check_sql).fetchall()
        os.replace(temp_path, target_path)
    except BaseException:
        conn.close()
        raise
    with lock:
        old = getattr(owner, attr)
        setattr(owner, attr, conn)
    if old is not None:
        old.close()
```

`install_deadline_handler` runs inside `connect_readonly_db`, before publication, as the line 31-41 warning requires.

## `engine/server/api/server_config.py`

After `_resolve_positive_int_env`:

```python
def _resolve_non_negative_int_env(name: str) -> int | None:
    """Return a non-negative int from the environment, or None when unset or blank; exit on anything else."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        # Exit rather than fall back: a mistyped interval would otherwise silently rebuild the cache on the wrong schedule, or never.
        raise SystemExit(f"{name} must be a non-negative integer, got {raw!r}")
    return value
```

Decision: blank counts as unset, as in `_resolve_weight_env`, so an empty `VAR=` line in `.env.bridge` means the default.

Lines 344-345 onward:

```python
# Startup build only: rebuild the random cache in the background after the Engine listens, even when the existing cache is usable.
DEFAULT_RANDOM_CACHE_REFRESH = True
# Minutes between background random cache rebuilds when RANDOM_CACHE_REFRESH_INTERVAL_MINUTES is unset and --dev is off (0 disables).
DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES = 60
# Environment override of the rebuild interval; None when unset, so --dev can pick 0. Read it through random_cache_refresh_interval_minutes.
RANDOM_CACHE_REFRESH_INTERVAL_MINUTES = _resolve_non_negative_int_env("RANDOM_CACHE_REFRESH_INTERVAL_MINUTES")


def random_cache_refresh_interval_minutes(dev: bool) -> int:
    """Return the periodic random cache rebuild interval: the environment value when set, else 0 under --dev and the default otherwise."""
    if RANDOM_CACHE_REFRESH_INTERVAL_MINUTES is not None:
        return RANDOM_CACHE_REFRESH_INTERVAL_MINUTES
    return 0 if dev else DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES
```

This is a small departure from "resolve beside line 307 in server.py". The precedence rule sits in the config module so T13 can test it in a child `python -c` without faiss. server.py calls it at line 307. The function reads the module global at call time, so the variant runner's `setattr` overrides reach it.

## `engine/server/api/server.py`

**Imports.**
- Line 105 becomes `from data.random_cache import open_random_cache_if_usable, run_random_cache_worker`.
- The `server_config` block gains `random_cache_refresh_interval_minutes`.
- Line 85 is unchanged: server.py does not call the swap helper directly.
- `threading` is already imported.

**Help text.**
- `--dev`: "Enable dev defaults: bind port 7071, skip the startup random cache build, and set the periodic random cache rebuild to 0 unless RANDOM_CACHE_REFRESH_INTERVAL_MINUTES is set (unless explicitly overridden)."
- `--random-cache-refresh`: "Rebuild the random cache in the background at startup, even when it is usable."
- `--no-random-cache-refresh`: "Skip the startup random cache build when the cache is usable. The periodic rebuild is set by RANDOM_CACHE_REFRESH_INTERVAL_MINUTES."

**After line 310:**
```python
    random_cache_interval = random_cache_refresh_interval_minutes(args.dev)
```

**Lines 328-339 become:**
```python
    random_cache_path.parent.mkdir(parents=True, exist_ok=True)
    # Nothing is built before listening: a usable cache serves as it is, and a missing or empty one leaves the random feed on the DB until the background build swaps one in.
    random_cache_db = open_random_cache_if_usable(random_cache_path)
    random_cache_startup_build = random_cache_refresh or random_cache_db is None
```

`SimilarServer(...)` still receives `random_cache_db`; its signature is unchanged.

**Log line 474-478** gains a token:
```python
        "[similar-server] mode=%s random_cache_refresh=%s random_cache_refresh_interval_minutes=%s",
        ...,
        random_cache_interval,
```
It uses `%s`, so a test's fractional override prints as given.

**Just before `try: server.serve_forever()`:**
```python
    random_cache_stop = threading.Event()
    if random_cache_startup_build or random_cache_interval > 0:
        # Daemon: an in-progress build dies with the interpreter instead of delaying shutdown.
        threading.Thread(
            target=run_random_cache_worker,
            args=(db_path, random_cache_path, DEFAULT_RANDOM_CACHE_SIZE, DEFAULT_RANDOM_CACHE_FILTERED_MODE, DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE, DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR, server, random_cache_stop, random_cache_startup_build, random_cache_interval * 60),
            name="random-cache-refresh",
            daemon=True,
        ).start()
```

**`finally`:** `random_cache_stop.set()` goes first, with no join. Lines 500-501 become:
```python
        with server.random_cache_lock:
            live_random_cache_db = server.random_cache_db
            server.random_cache_db = None
        if live_random_cache_db is not None:
            live_random_cache_db.close()
```
Taking the handle under the lock means no read is mid-flight on it when it closes. Clearing the attribute is shutdown-only; the never-None rule is the swap helper's.

## `engine/server/db/jobs/precompute-random-rowids.py`

- Imports: `argparse, logging, os, sys, Path`; `sqlite3` goes.
- `from data.random_cache import build_random_cache, open_random_cache_if_usable, random_rowids_count, remove_random_cache_temp`.
- `connect_source_db` is deleted.
- The argparse block is unchanged.

```python
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Resolved so the temp file sits beside the real file and the rename stays on one filesystem.
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.reset and not args.refresh:
        existing_db = open_random_cache_if_usable(out_path)
        if existing_db is not None:
            existing = random_rowids_count(existing_db) or 0
            existing_db.close()
            if existing >= args.size:
                logging.info("random cache size=%d", existing)
                return
    temp_path, count, _ = build_random_cache(Path(args.db), out_path, args.size, args.filtered, args.max_per_instance, args.max_per_author)
    try:
        os.replace(temp_path, out_path)
    except OSError:
        remove_random_cache_temp(temp_path)
        raise
    logging.info("random cache size=%d", count)
```

`--reset` and `--refresh` both skip reuse, which is "build fresh". The contents are the same as before, because `populate_random_cache` always cleared the table before filling it. Two edges differ slightly from today:
- `--size 0` on a missing or empty `--out` now installs an empty table rather than leaving the file as it was. The end state (0 rows) is the same.
- `.resolve()` means a symlinked `--out` is replaced at its target, as the old in-place write did.

## Tests (drafted shape)

`tests/active/test_random_cache.py`:
- **Imports:** `build_random_cache, open_random_cache_if_usable, refresh_random_cache, run_random_cache_worker, random_cache_temp_path, fetch_random_rowids, RANDOM_CACHE_CHECK_SQL` and `from data.db import swap_readonly_connection`.
- **Fixtures reused:** `_source_db`, and a `_seed_cache(path, rowids)` helper using plain `sqlite3`.
- **Owner:** `SimpleNamespace(random_cache_db=conn, random_cache_lock=threading.Lock())`.
- **T8 pause:** monkeypatch `data.random_cache.populate_random_cache` with a wrapper that runs `INSERT INTO random_rowids VALUES (1, 1)`, sets `paused`, waits on `release` with a 30 s bound, then calls the real function. The control param monkeypatches `connect_random_cache_db` with a copy lacking the pragma.
- **T10/T11 runner:** a new `CACHE_VARIANT_RUNNER`, the `VARIANT_RUNNER` shape plus `sys.path.insert(0, dirname(api))`. It optionally wraps `data.random_cache.build_random_cache` to wait for a gate file with a 120 s bound. Overrides:
  - `DEFAULT_RANDOM_CACHE_DB_PATH` = absolute tmp path;
  - `DEFAULT_RANDOM_CACHE_SIZE=200`;
  - `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` = 0 or 0.25.
  The Engine is started under `ENGINE_START_LOCK` like `_start_variant`, and its log is read with `_messages`-style JSON parsing.
- **8-Engine test:** assertions unchanged. Reword docstring line 167: a start opens the cache read-only and builds nothing before listening. Reword the controls at 172-175 and 181-187: the held RESERVED lock still admits read-only opens. Reword 225-226: a straggler is killed if SIGTERM does not stop it within the bound. Its env gains `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES="0"`.
- **Module docstring:** rewritten to the new contract and T1-T14.

`tests/active/conftest.py`: the comments at lines 113-114 are reworded. The fixture env gains `"RANDOM_CACHE_REFRESH_INTERVAL_MINUTES": "0"`, so a suite longer than an hour never renames over the checkout's cache. This is a one-key env change and does not touch `ENGINE_START_LOCK`, but it is beyond "comments only", so it is flagged for the test step.

`tests/active/test_server_config.py`: T13 as a new parametrized block with `var="RANDOM_CACHE_REFRESH_INTERVAL_MINUTES"`, plus docstring bullets.

## Docs

As in the settled list, with these decisions recorded in them:
- the journal is kept in memory;
- blank counts as unset;
- the unfiltered summary logs the effective mode;
- build lines are INFO (verbose only).

The issue 24 comment carries the hot-journal caveat and the read-only-handle contract.

## Plan check (pass 1 of 3, converged)

| Requirement / plan point | Met by |
|---|---|
| One build path, own read-only source, per-pid temp, commit and close, `os.replace` | `build_random_cache` + `swap_readonly_connection` |
| Validate-first swap, lock only for the reference, generic interface, never None | `swap_readonly_connection(temp, target, lock, owner, attr, check_sql)` |
| Serving handle `mode=ro`; 3600 s wait and `reuse_non_empty` retired | `open_random_cache_if_usable`, the swap helper; deleted lines |
| Startup: open if usable, no build before listening, refresh-on or unusable → background build, DB fallback while `None` | server.py startup block and worker start |
| Interval: env, non-negative, 60 / 0 under `--dev`, explicit wins, invalid exits naming it; flags govern startup only | `_resolve_non_negative_int_env`, `random_cache_refresh_interval_minutes` |
| One daemon thread, no overlap, stops on the event, interval 0 with no startup build → no thread | `run_random_cache_worker`, server.py guard |
| Failure: temp removed, active file and connection untouched, logged, retried next tick | `build_random_cache` except path, `refresh_random_cache` |
| Logs: duration, scanned, size, target, mode and caps, short fill, swap result or reason | start, summary (both branches), short and ok/failed lines |
| No WAL, no sidecar at rename | `journal_mode=MEMORY` (operator chose fix (a) over the plan's "default" journal) |
| Job via temp + replace, CLI and output unchanged | job rewrite |

## Named simplifications and residual risks

- No backoff and no maximum build runtime.
- No sweep of stale temp files from dead pids.
- Sibling Engines stay on the old inode.
- No minimum-row guard before the swap.
- Build lines stay INFO, as the plan says. A `failed` line is therefore hidden in focused mode; making it WARNING is the one-word upgrade.
- Mixed-version rollout: an old-code Engine writing `random-cache.db` in place with a disk journal can still show a hot journal to a new Engine's handle named `random-cache.db`. This is transient, until all Engines run this code.
- Cache reads now carry the deadline handler and can answer 503 on a slow `OFFSET` read (they were unbounded before).
- Plan 17's old-shape detection must move into `open_random_cache_if_usable` or the build. Noted for the issue-08 lane.


### Phases

#### Phase 1 - Temp-file build path [code]

**Files touched.** engine/server/data/random_cache.py (EDITED), engine/server/db/jobs/precompute-random-rowids.py (EDITED), tests/active/test_random_cache.py (EDITED)

**Checkpoint.** Seam 1 is the in-process call into `data.random_cache.build_random_cache` on tmp files in `tests/active/test_random_cache.py`, using the existing `_source_db` fixture and a plain-sqlite3 `_seed_cache` helper (T1). It asserts four things. The returned path equals `<stem>.tmp.<pid><suffix>` beside the active file. The temp file holds positions 1..20 over source rowids 1..20. No `-journal` sidecar exists. The active file's bytes are unchanged. A patched `populate_random_cache` that raises leaves neither the temp file nor its `-journal`. Seam 2 is `engine/server/db/jobs/precompute-random-rowids.py` run as a child process on a tmp source, the same subprocess pattern as the job tests in `test_repair_video_channel_names.py` (T14). It asserts four things. A fresh `--out` gets positions 1..N over the source rowids. A second run without `--reset`/`--refresh`, with the file at or above size, leaves the inode unchanged. `--reset` changes the inode. No `*.tmp.*` file remains in the directory.

**Intent.** A random cache is always built complete in a per-pid temp file beside its target by `build_random_cache` in `engine/server/data/random_cache.py`, and `precompute-random-rowids.py` installs a build only by renaming that file over `--out`.

- C1 - `build_random_cache` writes a complete cache into `<stem>.tmp.<pid><suffix>` beside the active file, leaves no journal sidecar and does not touch the active file, and on an exception removes the temp file.
- C2 - The precompute job keeps an `--out` already at size without writing it, and otherwise replaces `--out` by rename, leaving no temp file.

**Outcome.** ### `engine/server/data/random_cache.py`
- New imports: `os`, `time`, and `from data.db import connect_readonly_db`. The last is an import only; `data/db.py` is not edited.
- Added `random_rowids_count(conn) -> int | None`. It returns the row count, or `None` when the `random_rowids` table is missing, and uses `fetchall` so no statement keeps holding SHARED on the file. It replaces the private `_random_rowids_table_exists`, so the `sqlite_master` query now exists once. `populate_random_cache`'s `reuse_non_empty` path now calls it, with the same behaviour as before: a non-empty table returns its count and nothing is written.
- Added `random_cache_temp_path(active_path)`, which returns `<stem>.tmp.<pid><suffix>` beside the active file.
- Added `remove_random_cache_temp(temp_path)`, which deletes the temp file and its `-journal` sidecar if either exists.
- Added `build_random_cache(source_path, active_path, size, filtered_mode=False, max_per_instance=0, max_per_author=0) -> (temp_path, count, elapsed_seconds)`. In order, it:
  - first removes any leftover at the temp name, which only an earlier process with the same pid can leave;
  - opens the source through its own `connect_readonly_db` handle;
  - creates the schema in the temp file, so a `size <= 0` build never produces a file without the table;
  - calls `populate_random_cache` through the module global with `refresh=True`, then commits;
  - closes both connections in a `finally`. Closing rolls back any open write and deletes its journal.
  
  On any exception it removes the temp file and its `-journal`, then re-raises. It never opens the active file.
- Deliberately left for later phases, following the plan: the `journal_mode=MEMORY` pragma (phase 2, T8), `open_random_cache_if_usable` (phase 4, T7), the build's start log line (phase 4, T12), and retiring `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` and `reuse_non_empty`. The last two are still used by the gated tests in `tests/active/test_random_cache.py`, which phase 4 archives.

### `engine/server/db/jobs/precompute-random-rowids.py`
- Removed `connect_source_db` and the `sqlite3` import. It now imports `os`, `connect_readonly_db`, `build_random_cache`, `random_rowids_count` and `remove_random_cache_temp`. The argparse block and the CLI are unchanged.
- `--out` is resolved, so the temp file sits beside the real file and the rename stays on one filesystem.
- **Keep:** with neither `--reset` nor `--refresh` and an existing `--out`, the job counts rows through a read-only handle. If the count is at or above `--size`, it logs `random cache size=N` and returns without writing.
- **Replace:** in every other case the job calls `build_random_cache`, then does `os.replace(temp, out)`. If the rename fails, it removes the temp file and re-raises.
- `--reset` and `--refresh` now both just skip the keep check. The in-place `DELETE` for `--reset` is gone.

### `tests/active/test_random_cache.py`
Not changed in this phase. Its existing tests still use `connect_random_cache_db`, `ensure_random_cache_schema` and `populate_random_cache(..., reuse_non_empty=True)`, which all behave as before. I did not copy the checkpoint into it: this step is limited to production code.

I did not run the checkpoint or any probe; the workflow's run is the first observation of this code.

#### Phase 2 - Validate-first swap [code]

**Files touched.** engine/server/data/db.py (EDITED), engine/server/data/random_cache.py (EDITED), tests/active/test_random_cache.py (EDITED)

**Checkpoint.** The seam is in-process calls into `data.random_cache.refresh_random_cache` and `data.db.swap_readonly_connection` on tmp files in `tests/active/test_random_cache.py`. The owner is `SimpleNamespace(random_cache_db=conn, random_cache_lock=threading.Lock())`, which is the owner contract `fetch_random_rows_from_cache(server)` already uses. C1 is covered by three tests. T2: the active file is a new inode, `owner.random_cache_db` is a new object that reads the new rows, the old connection raises `ProgrammingError`, and no temp file remains. T8: a second same-pid build is paused after its first uncommitted write. While it is paused, no `<served name>-journal` exists and `fetch_random_rowids` on the served handle succeeds. A parametrized control, with `connect_random_cache_db` patched to drop the MEMORY pragma, raises `OperationalError`. T9: three reader threads loop `fetch_random_rowids` under the lock across 10 refresh cycles, with no exception and no empty result. C2 is covered by three tests. T3: a patched `populate_random_cache` raises after writing. The refresh returns False and logs `failed`, the active file's bytes are unchanged, the owner holds the same object and it still reads, and the temp file and `-journal` are gone. T4: `swap_readonly_connection` with a failing check SQL raises, the active file and the owner attribute are unchanged, and the temp file still exists. Through `refresh_random_cache`, the temp file is removed. T5: the stop event is set before the swap, so no swap happens and the temp file is removed.

**Intent.** A finished build becomes the owner's read-only serving handle through `swap_readonly_connection` in `engine/server/data/db.py`, driven by `refresh_random_cache`, only after it has been validated, and any failure leaves the active file and the handle as they were.

- C1 - After a successful refresh, the owner's serving handle is a new read-only connection that reads the renamed file, and the old handle is closed without failing a concurrent or same-pid-journal read.
- C2 - A failure at the build, the check or the rename, or a stop set before the swap, leaves the active file's bytes and the owner's handle unchanged and removes the temp file.

**Outcome.** ### `engine/server/data/db.py`
- Added `import os`.
- Added `swap_readonly_connection(temp_path, target_path, lock, owner, attr, check_sql)` right after `connect_readonly_db`. Nothing in it is specific to the random cache, so issue 24 can reuse it. In order, it:
  - opens a read-only handle on the temp file through `connect_readonly_db`, which installs the deadline handler before the handle is published;
  - runs `check_sql` on it, fully fetched;
  - calls `os.replace(temp_path, target_path)`.
  
  If the open, the check or the rename fails, it closes the new handle and re-raises. The target file and `owner.<attr>` are left as they were, and the temp file is left for the caller to remove.
- Once the rename has succeeded, it takes the old `owner.<attr>` and sets the new handle under `lock`. It closes the old handle after releasing the lock, and never installs `None`.
- The docstring covers the order of steps, the rule that readers hold `lock`, the never-`None` rule, and the temp-name journal caveat.
- The `connect_readonly_db` docstring is not reworded; that is left to the documentation step.

### `engine/server/data/random_cache.py`
- New imports: `threading`, `typing.Any`, and `swap_readonly_connection` from `data.db`.
- Added `RANDOM_CACHE_CHECK_SQL = "SELECT COUNT(*) FROM random_rowids"`.
- `connect_random_cache_db` now runs `PRAGMA journal_mode=MEMORY` right after connecting (the hot-journal fix (a)). This fixes the hot-journal hazard: the served handle keeps the temp name `random-cache.tmp.<pid>.db`, so it looks for a journal at that name plus `-journal`. A later build in the same process writes its journal at exactly that name, which would fail every read on the served handle.
  - The pragma must live in the opener, not in `build_random_cache`, because the checkpoint's control swaps out this opener.
  - A probe showed the pragma does not wait on another connection's `BEGIN IMMEDIATE` and opens no transaction, so existing callers are not blocked.
  - `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` and `reuse_non_empty` stay: gated active tests still use them, and phase 4 retires them.
- Added `refresh_random_cache(source_path, active_path, size, filtered_mode, max_per_instance, max_per_author, owner, stop_event) -> bool`. It never raises. In order, it:
  - runs `build_random_cache`;
  - if `stop_event` is set, removes the temp file, logs `random cache build skipped ... reason=stopping` and returns False;
  - otherwise calls `swap_readonly_connection(temp, active, owner.random_cache_lock, owner, "random_cache_db", RANDOM_CACHE_CHECK_SQL)`.
  
  Any `Exception` removes the temp file and its `-journal`, logs `random cache build failed duration=… reason=<Type>: <message>` and returns False. On success it logs `random cache build ok duration=… size=… target=… path=…` and returns True.
- Known effect until phase 4: `server.py` still opens the serving cache through `connect_random_cache_db` and rebuilds it in place at a refresh-on start. That in-place write now has an in-memory journal, so a crash mid-rebuild could leave `random-cache.db` damaged until the next rebuild. Phase 4 removes that path.

### `tests/active/test_random_cache.py`
Not changed in this phase. The checkpoint lives in `tests/tmp/`, and this step covers production code only.

I did not run the checkpoint. The only thing I ran was one throwaway probe (see unanticipated).

**Beyond the files named.** tests/tmp/probe_journal_memory_under_reserved.py — a throwaway probe I wrote and ran through ValidateTests. It checked that `PRAGMA journal_mode=MEMORY` succeeds with `timeout=0` while another connection holds `BEGIN IMMEDIATE`. It does: the result is `[('memory',)]`, no transaction is opened, and no sidecar is left. I have no delete tool, so please delete this file. Its name does not match `test_*.py`, so pytest will not collect it by default.

#### Phase 3 - Interval setting [code]

**Files touched.** engine/server/api/server_config.py (EDITED), tests/active/test_server_config.py (EDITED)

**Checkpoint.** The seam is the child-process `python -c` import of `server_config` in `tests/active/test_server_config.py`, reusing its existing parametrized env-variable harness with `var="RANDOM_CACHE_REFRESH_INTERVAL_MINUTES"` (T13). For C1: unset and `""` give `None`, `0` and `7` give ints, and `abc`, `-1` and `7.5` exit 1 with the last stderr line naming the variable. For C2: `random_cache_refresh_interval_minutes(False/True)` with the variable unset gives 60/0, and with `5` gives 5/5.

**Intent.** The periodic rebuild interval is resolved from `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` in `engine/server/api/server_config.py`, and an explicit value wins over `--dev`.

- C1 - `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` resolves to None when unset or blank and to the non-negative integer given, and a non-integer or negative value exits naming the variable.
- C2 - `random_cache_refresh_interval_minutes(dev)` returns the environment value when set, otherwise 0 under dev and 60 without it.

**Outcome.** ### `engine/server/api/server_config.py`

- Added `_resolve_non_negative_int_env(name) -> int | None`, next to the other `_resolve_*_env` helpers and written the same way. It returns None when the variable is unset or only whitespace, which is the same blank handling `_resolve_weight_env` uses. Otherwise it returns the value as an int. A non-integer such as `abc` or `7.5`, or a negative value, raises `SystemExit(f"{name} must be a non-negative integer, got {raw!r}")`. That exits with status 1, and the message naming the variable is the last stderr line. The WHY comment says it exits instead of falling back because a mistyped interval would silently put rebuilds on the wrong schedule.
- In the random cache constants block, after `DEFAULT_RANDOM_CACHE_REFRESH`, added:
  - `DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES = 60`, the value used when the variable is unset and `--dev` is off. Its comment says 0 disables.
  - `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES = _resolve_non_negative_int_env("RANDOM_CACHE_REFRESH_INTERVAL_MINUTES")`, read once at import. It is `int | None`, so `--dev` can tell "unset" apart from an explicit value.
- Added `random_cache_refresh_interval_minutes(dev: bool) -> int`. It returns the environment value when it is not None, otherwise 0 under dev and `DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` without dev.
  - It checks `is not None` rather than truthiness, so an explicit `0` wins; a comment says so.
  - It reads the module global each time it is called, so a variant runner's `setattr` override reaches it.
  - Nothing calls it yet. Wiring it into `server.py` is a later phase.
- Left the existing comment on `DEFAULT_RANDOM_CACHE_REFRESH` as it is. The plan rewords it to describe the background startup build, but that describes behaviour this phase doesn't deliver.

### `tests/active/test_server_config.py`

Not touched. The gating checkpoint is `tests/tmp/test_22_random_cache_background_refresh_phase3.py`, and it passes without this file. The phase's files list names it only as the eventual home of the T13 cases, so moving those cases in is left to the workflow.

#### Phase 4 - Engine background worker [code]

**Files touched.** engine/server/data/random_cache.py (EDITED), engine/server/api/server.py (EDITED), tests/active/conftest.py (EDITED), tests/active/test_random_cache.py (EDITED), tests/archive/random_cache_in_place/test_random_cache_in_place.py (NEW)

**Checkpoint.** Seam 1 is a real Engine started through a new `CACHE_VARIANT_RUNNER` in `tests/active/test_random_cache.py`. It is modeled on the existing `VARIANT_RUNNER`/`_start_variant` and started under `ENGINE_START_LOCK`, and it overrides `DEFAULT_RANDOM_CACHE_DB_PATH` (absolute tmp path), `DEFAULT_RANDOM_CACHE_SIZE=200` and `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`. For C1, T10 holds a gate patched into `data.random_cache.build_random_cache` on a refresh-on Engine. While the gate holds, `/api/health` and the random feed both answer 200. Once it is released, an `ok` line appears and the tmp file holds 200 rows. T12 checks that the session `engine` fixture's log (refresh off, usable checkout cache, interval 0 via the conftest env) contains no `random cache build start` line. T7 checks `open_random_cache_if_usable` in-process. Missing, no table and empty each give `None`. A non-empty file gives a `mode=ro` connection whose count matches, and it still opens while another connection holds `BEGIN IMMEDIATE`. For C2, T11 runs a variant with interval 0.25, refresh off and the file missing. It sees three or more `ok` lines with a changed inode on each. `POST /recommendations?random=1` is looped throughout, and every answer is 200 and non-empty. After an `ok`, the returned pairs map through a read-only `whitelist.db` into the current file's rowids. T6 calls `run_random_cache_worker` in-process. `startup_build=False` with interval 0 returns at once, with no temp file and the owner unchanged. `startup_build=True` with interval 0 builds exactly once. The 8-Engine test's assertions stay green.

**Intent.** The Engine in `engine/server/api/server.py` opens a usable cache read-only at startup and runs every cache build in one background daemon worker, `run_random_cache_worker`, that starts after the Engine is listening.

- C1 - The Engine answers health and the random feed before any build finishes, and starts no build when its cache is usable, refresh is off and the interval is 0.
- C2 - With a positive interval the worker swaps a new cache in on each tick while the random feed keeps answering from the current file, and with interval 0 it runs at most the one startup build.

**Outcome.** ### `engine/server/data/random_cache.py`
- `refresh_random_cache` now logs `random cache build start target=… filtered=… max_per_instance=… max_per_author=… temp=…` right before it calls `build_random_cache`. The plan had this line inside `build_random_cache`. The checkpoint's gate replaces `build_random_cache` and requires the start line to be in the log while the build is held at the gate, so the line has to come from the caller. Logging it in both places would give two start lines per Engine build, and the checkpoint allows exactly one. As a result the precompute job, which calls `build_random_cache` directly, logs no start line.
- Added `open_random_cache_if_usable(path) -> Connection | None`:
  - A missing file is checked with `path.exists()` first, so it is never created, and logs `reason=missing`.
  - Otherwise the file is opened with `connect_readonly_db` (`mode=ro`) and counted with `random_rowids_count`.
  - Any `sqlite3.Error` closes the handle, logs the error type and message, and returns None.
  - A missing table or an empty table closes the handle, logs `reason=no_table` or `reason=empty`, and returns None.
  - A non-empty cache returns the read-only handle. It only reads, so it opens even while another connection holds `BEGIN IMMEDIATE`.
- Added `run_random_cache_worker(source_path, active_path, size, filtered_mode, max_per_instance, max_per_author, owner, stop_event, startup_build, interval_seconds)`. It runs the startup build through `refresh_random_cache` if asked. Then, while `interval_seconds > 0`, it waits `stop_event.wait(interval_seconds)`, returns if the event is set, and otherwise builds again. With interval 0 it returns after at most the startup build. A failed build is logged by `refresh_random_cache` and retried at the next tick.
- Left in place: `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS`, its rat-tail comment, and the `reuse_non_empty` keyword with its branch in `populate_random_cache`. The Engine no longer uses them, but the already-gated tests in `tests/active/test_random_cache.py` still import and call them. Removing them before those tests are moved to `tests/archive/random_cache_in_place/` would break the active suite (see below).

### `engine/server/api/server.py`
- Imports:
  - `from data.random_cache import open_random_cache_if_usable, run_random_cache_worker` replaces `connect_random_cache_db, populate_random_cache`.
  - `random_cache_refresh_interval_minutes` is added to the `server_config` import.
- `random_cache_interval = random_cache_refresh_interval_minutes(args.dev)` is resolved next to `random_cache_refresh`. The function reads the module global when called, so the variant runner's override (including 0.25) gets through.
- The in-place startup `connect_random_cache_db` + `populate_random_cache(..., reuse_non_empty=True)` block is replaced:
  - `random_cache_db = open_random_cache_if_usable(random_cache_path)`
  - `random_cache_startup_build = random_cache_refresh or random_cache_db is None`
  - The `mkdir` stays, because the temp file is written in that directory.
- Just before `serve_forever`, after `SimilarServer` exists, a daemon `threading.Thread` named `random-cache-refresh` runs `run_random_cache_worker`:
  - Its arguments are `db_path`, `random_cache_path`, the size, filtered mode and cap constants, `server` as the owner, a `threading.Event`, the startup-build flag, and `random_cache_interval * 60` seconds.
  - It starts only when a startup build is needed or the interval is above 0.
- The `finally` block:
  - sets the stop event first, with no join;
  - closes whatever `server.random_cache_db` holds, taken and cleared under `server.random_cache_lock`, instead of the startup local.
- Not changed here, because the plan's documentation list assigns them to the docs step: the `--dev` and refresh-flag help text, and the interval token on the `[similar-server] mode=` log line.

### `tests/active/conftest.py`, `tests/active/test_random_cache.py`, `tests/archive/random_cache_in_place/test_random_cache_in_place.py`
Not touched. This step covers production code only, and the checkpoint doesn't depend on any of these files. They still need to be done:
- Move the four in-place tests into the archive file. They are the two busy-wait tests and the two `reuse_non_empty` tests. After that, `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` and `reuse_non_empty` can be deleted from `random_cache.py`.
- Reword the conftest and 8-Engine-test comments that describe in-place writes.
- The plan's `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES=0` for the session Engine's environment is not set yet. Until it is, the session Engine and the 8 Engines each start an idle 60-minute worker. A suite run longer than an hour would do a full filtered build and rename it over the checkout's `random-cache.db`.

Not verified:
- I did not run the checkpoint or any probe. The workflow's run will be the first time this code is exercised.
- The Engine tests read `random cache build …` INFO lines from the log. The default `RECOMMENDATIONS_LOG_PROFILE` is `verbose`, which prints them. If the environment sets `focused`, those lines are dropped (this is unchanged since phase 2's `ok` line).


