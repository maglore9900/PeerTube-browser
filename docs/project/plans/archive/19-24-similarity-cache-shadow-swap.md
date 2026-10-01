# 24-similarity-cache-shadow-swap

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-24-similarity-cache-shadow-swap.record.md`._

## Requirements

### Purpose

The updater (`engine/server/db/jobs/updater-worker.py`) currently keeps the Engine service stopped from the merge until `precompute-similar-ann.py --refresh-existing` finishes. That precompute can be very long, so the API is down for all of it. This build moves the similarity precompute out of the stopped-service window. The updater builds the new cache in a shadow file while the Engine serves, gates it, and swaps it in atomically. Every running Engine picks up the new file on its own, without a restart and without IPC. Source: issue 24 (`docs/project/issues/24-similarity-cache-shadow-swap.md`). Design record: ADR-0008 (`docs/project/adr/0008-similarity-cache-handoff-through-files.md`). Glossary: `Shadow build`, `Build marker` in `CONTEXT.md`. Issue 25 (the `--refresh-existing` precompute mode) is already delivered. This build must land before issue 26 (zero-downtime deploy, two Engines on ports 7070/7071 from one checkout), and its file-based handoff is chosen so that both of those Engines pick up a swap.

### Files involved (as found in the tree)

- `engine/server/db/jobs/updater-worker.py`: `main()` holds the stop → merge (`merge-staging-db.py`) → denylist safety prune (`purge_hosts(prod_db=..., similarity_db=..., hosts=denied_hosts, dry_run=False)`) → `recompute-popularity.py --incremental` → `build-ann-index.py` → precompute (`similarity_precompute_cmd(...)` with `out_path=similarity_db`, run through `run_with_cpu_fallback`) → start sequence. The service start happens today in a `finally` after the precompute. The file also has `_pid_alive(pid)` (reuse it for marker liveness), `single_run_lock`, the test-only flags `--fail-before-merge`, `--fail-during-ann-build`, `--fail-after-merge-before-similarity`, and `--skip-systemctl`.
- `engine/server/db/jobs/precompute-similar-ann.py`: `--refresh-existing` rewrites only cached sources still in `video_embeddings` and never deletes a source. Its `connect_db` is plain `sqlite3.connect`, so it uses the default disk rollback journal at `<out>-journal`.
- `engine/server/api/server.py`: opens `similarity_db = connect_similarity_db(similarity_db_path)` from the fixed `repo_root / DEFAULT_SIMILARITY_DB_PATH`, runs `ensure_similarity_schema`, and stores `server.similarity_db` and `server.similarity_db_lock = threading.Lock()`.
- `engine/server/data/db.py`: `connect_similarity_db(path)` opens read-write with `check_same_thread=False` and `row_factory = sqlite3.Row`. It also holds `swap_readonly_connection`, which this build does NOT use and does NOT change.
- `engine/server/data/similarity_candidates.py`: `_read_cache` and `_write_cache` are the only Engine users of `server.similarity_db`, and both hold `similarity_db_lock` when it is present. `_write_cache` calls `write_cache` from `data/similarity_cache.py`.
- `engine/server/data/moderation.py` / `engine/server/db/jobs/instance-denylist-cli.py`: operator-run denylist purge that deletes host rows from the similarity cache and runs outside the updater's lock.
- Docs: `engine/server/db/jobs/docs/UPDATER_WORKER.md` (step 10 currently says "Refresh the similarity cache in place"), `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`, `CONTEXT.md`, ADR-0008.
- Smoke test: `engine/server/db/jobs/tests/test-orchestrator-smoke.py` drives the updater's failure-injection flags (e.g. the `after_merge_before_similarity` scenario).

### Requirement 1: Updater sequence

The Engine service is stopped only across the write-conflict-critical stages: merge, post-merge denylist safety prune, popularity recompute and ANN index rebuild. The service is started again (the existing `try/finally` start logic, still guaranteed on failure) before the similarity stage begins. The API therefore serves during the whole precompute, with the new ANN index and the old cache. The pre-existing `--fail-after-merge-before-similarity` injection keeps working and still results in the service being started. With `--skip-systemctl`, the sequence is otherwise unchanged.

### Requirement 2: Start-of-run cleanup

At updater start, inside the single-run lock and before any stage, the updater:
- reads the build marker if it exists. When the marker's PID is not alive (per `_pid_alive`) or its content is unparseable, the updater deletes it and logs the removal (path and PID). A marker whose PID is alive is left alone (it cannot belong to another updater run, because of `single_run_lock`, but the updater does not delete a live one).
- deletes any leftover `similarity-cache.next.db` and its `similarity-cache.next.db-journal` from a crashed earlier build, and logs each removal. A leftover `-journal` would otherwise be applied as a hot journal to the next build's fresh copy.

### Requirement 3: Build marker

- A file next to the active cache whose name is derived from the cache path (e.g. `<similarity-cache.db>.building`, the exact name being the implementer's choice). Its content is the updater's PID as decimal text.
- The name and format are recorded in `engine/server/db/jobs/docs/UPDATER_WORKER.md`, and `CONTEXT.md`'s `Build marker` entry stays consistent with them.
- The updater and the Engine derive the marker path from the same cache path. The updater derives it from its `--similarity-db` argument and the Engine from its `similarity_db_path`. In production these are the same file.
- The marker is written before the shadow copy starts, and it is removed on every exit from the similarity stage: success, gate failure, precompute failure or exception (a `finally`).

### Requirement 4: Shadow build

With the marker in place, the updater:
1. Takes a consistent copy of the active `similarity-cache.db` as `similarity-cache.next.db` (next to it) with the stdlib `sqlite3` backup API (`Connection.backup`), which stays consistent even if a write that was already in flight when the marker appeared commits during the copy. If the active file does not exist, the shadow starts empty and precompute creates its schema.
2. Runs the existing precompute stage against the shadow: `similarity_precompute_cmd(..., out_path=<.next.db>, ...)` (still `--refresh-existing`), through `run_with_cpu_fallback` as today.
3. Re-applies the denylist to the shadow (operator decision). It reloads the active denied hosts from the prod DB (`load_denied_hosts(prod_db)`) and runs the existing `purge_hosts`-style similarity deletion against the shadow file only, so rows purged from the active file by `instance-denylist-cli.py --purge-now` during the build are not brought back by the swap. The deleted counts are logged.
4. Does not write the active file at any point during the build.
5. Leaves no disk rollback journal that a served handle could trip over. The shadow's journal name (`.next.db-journal`) is never the served file's journal name. The start-of-run cleanup removes any leftover, and the shadow is closed (committed, journal gone) before the gate and swap.

### Requirement 5: Pre-swap gate

Before swapping, the updater checks the shadow:
- `PRAGMA integrity_check` returns exactly `ok`;
- the cache schema is present (the `similarity_sources` and `similarity_items` tables exist);
- `COUNT(*)` of `similarity_sources` in the shadow is >= the same count in the active file, read at gate time (the freeze keeps the active count stable during the build; a missing active file counts as 0).

On a pass: it creates or replaces `similarity-cache.prev.db` holding the active file's content (a hardlink of the active file, falling back to a copy, with any older `.prev.db` replaced), then runs `os.replace(<.next.db>, <similarity-cache.db>)`. On a fail: it deletes the shadow, leaves `similarity-cache.db` byte-identical, logs the gate reason, removes the marker and exits non-zero. The service stays up, because it was already started before the similarity stage. No automatic post-swap rollback is built, and `.prev.db` restore stays a manual rename, which the Engine's inode check then picks up.

A new test-only flag (e.g. `--fail-similarity-gate`, in the style of the existing `--fail-*` flags with a `Test-only:` help text) forces a gate failure through the real failure path: the shadow is deleted, the active file is untouched, the marker is removed and the exit is non-zero.

### Requirement 6: Engine freeze

In the Engine's write path (`_write_cache` in `engine/server/data/similarity_candidates.py`, or the connection-owning helper it calls), a similarity cache write is skipped (returns without writing) while a build marker exists whose PID is alive. Reads and live ANN computation continue. Misses are served but not stored. A marker whose PID is dead, or whose content is unparseable, is ignored, and writes proceed. The Engine never deletes a marker. The liveness check uses `os.kill(pid, 0)` semantics (`ProcessLookupError` → dead, `PermissionError` → alive), matching `_pid_alive`.

### Requirement 7: Engine reopen on inode change

- The Engine records the inode (and device) of the active cache path when it opens `server.similarity_db`.
- Under `similarity_db_lock`, it compares that record with `os.stat(active_path)`. When they differ, it opens a new read-write connection by the active path with `connect_similarity_db` and runs a schema check (the cache tables exist and answer a read). Only when both succeed does it install the new handle in `server.similarity_db`, record the new inode and then close the old handle. If the open or the check fails, it closes the failed new handle, keeps the old handle and old inode record, logs the failure, and tries again on a later check. A missing active path also counts as a failed reopen: keep the old handle.
- Reads may throttle the check (ADR-0008 leaves the cadence open). **A write never goes through a handle whose inode no longer matches the active path.** The write path runs the check first, and if the handle is still stale after the check (the reopen failed), the write is skipped. The reason: the old handle's rollback journal name is `similarity-cache.db-journal`, which now belongs to the new file, so a write through the stale handle could leave a hot journal that corrupts the new file (and the write would be lost anyway).
- `swap_readonly_connection` is not used and not modified.
- No request sees a read error during the handoff: concurrent `/api/similar` requests during a swap produce no errors.

### Requirement 8: Logs

Structured, in the existing style of each process (the updater: `logging.info("key=value ...")`; the Engine: its existing logger/profile style):
- the updater: stale marker removed (path, PID); leftover `.next.db` / `-journal` removed; shadow copy duration; shadow build (precompute) duration and processed source count (the shadow's `similarity_sources` count after the build is acceptable); denylist re-prune counts on the shadow; gate result and reason (with the shadow and active counts); swap duration; `.prev.db` written.
- the Engine: reopen result (success with the old and new inode, or failure with its reason); a write skipped due to a live marker (at a level/throttle that does not flood the log).

### Requirement 9: Documentation

- `engine/server/db/jobs/docs/UPDATER_WORKER.md`: the new stage order (service started before the similarity stage), the shadow build, the marker name and format, the gate, `.next.db` / `.prev.db`, the manual restore procedure and the new test flag.
- `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`: updated if the smoke scenarios change.
- `CONTEXT.md` `Shadow build` / `Build marker` entries consistent with the implementation. ADR-0008 followed, not revised.

### Acceptance criteria

- An updater run with the Engine up keeps `/api/health` and `/api/similar` answering throughout the similarity precompute stage. The service is stopped only across merge through the ANN rebuild.
- While a marker with a live PID exists, a request for an uncached source returns results and adds no rows to `similarity_sources` or `similarity_items`. With the marker gone, the same request stores its rows.
- A marker holding a dead PID does not stop writes, and the next updater run deletes it.
- After a successful build, `similarity-cache.db` holds the shadow's content, `similarity-cache.prev.db` holds the previous content, no `.next.db` or marker remains, and a running Engine serves from the new file without a restart.
- A forced gate failure (corrupt shadow, fewer sources than active, or the new test flag) leaves `similarity-cache.db` byte-identical, removes the shadow and the marker, logs the reason, exits non-zero, and keeps `/api/health` green.
- An Engine whose reopen fails (e.g. the file swapped in is not a valid cache) keeps serving from its old handle, logs the failure, and picks up a valid file swapped in later.
- Concurrent `/api/similar` requests during a swap produce no errors.
- Rows deleted from the active cache by a denylist purge during a build are not present after the swap (denylist re-applied to the shadow).
- Tests write only temporary copies of the similarity cache, never the shared `similarity-cache.db`.

### Test placement and baseline

- The test trees resolved for this build: active tests in `tests/active`, working/temporary files in `tests/tmp`, archive in `tests/archive`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`, project dir `/home/enduser/code/PeerTube-browser`. Plans go to `docs/project/plans`.
- Baseline suite state before the build: exit code 0 (green), no variant.
- Tests use temporary cache files (under a temp dir or `tests/tmp`) and must never open the shared `similarity-cache.db` for writing.

### Out of scope

- The precompute selection mode itself (issue 25 owns which sources are recomputed; `--refresh-existing` stays).
- An automatic rollback after the swap; `.prev.db` restore stays manual.
- Blue/green deploy and nginx switching (issue 26).
- The random cache's own swap mechanism (issue 22) and any change to `swap_readonly_connection`.
- Signals, admin endpoints or any IPC between the updater and the Engines (rejected in ADR-0008).
- Running the real cutover against the shared `similarity-cache.db`; per `docs/project/issues/plan.md`, that runs on main after the merge.
- Making `instance-denylist-cli.py` marker-aware (the operator chose re-applying the denylist to the shadow instead).

## High-level plan

### Approach

The build touches two processes, and the only thing they share is the path of the active cache file. There is no IPC. Everything that builds, swaps or cleans up lives in the updater. Everything that freezes writes or reopens the file lives in the Engine's similarity data layer.

**Shared naming (Req 3).** One small helper in `engine/server/data/similarity_cache.py` turns a cache path into its marker path, `<cache>.building`. A second helper reads the marker and says whether it blocks writes: parse the decimal PID, then check liveness with `os.kill(pid, 0)` semantics, where `ProcessLookupError` means dead and `PermissionError` means alive. The updater already imports from `data.*` (`data.moderation`, for example), so both processes derive the name from one definition and it cannot drift. For its own liveness check at start-of-run the updater keeps `_pid_alive`, as Req 2 asks. The `.next.db` and `.prev.db` names are built from the cache path in the updater only, because the Engine never needs them.

**Updater sequence (Req 1).** In `main()`, the existing `try/finally` that stops and starts the service shrinks. It now covers only the service stop, merge, post-merge denylist safety prune, popularity recompute and ANN rebuild, and ends with the `--fail-after-merge-before-similarity` injection. The `finally` still starts the service on success and on failure, so the injected failure still ends with the service started, as today. The similarity stage moves after that block and runs with the service up. Any exception it raises propagates out of `single_run_lock`, so the exit is non-zero. With `--skip-systemctl` the only change is where the precompute sits relative to the (skipped) start. The early exits for `--dry-run` and "no changes" are untouched.

**Start-of-run cleanup (Req 2).** This is the first thing inside `single_run_lock`, before `load_denied_hosts` and before any stage:
- Read the marker. If its content is unparseable or its PID is dead per `_pid_alive`, delete it and log `path` and `pid`. If its PID is alive, leave it alone.
- Unlink `similarity-cache.next.db` and `similarity-cache.next.db-journal` if they exist, logging each removal.

Because this runs before the dry-run return, a dry run also clears stale leftovers. That is harmless and intended.

**Similarity stage (Req 3, 4, 5, 8).** This is a new function in `updater-worker.py`, in the file's keyword-argument style. It runs as `try/finally`, and the `finally` always removes the marker. On any path that did not swap, it also deletes the shadow and its `-journal`, so a failed precompute does not leave a large file behind. The steps, in order:
1. **Write the marker** with `os.getpid()` as decimal text.
2. **Shadow copy.** If the active file exists, open it read-only through a `mode=ro` URI, so the updater can never create or write it. Copy it into `.next.db` with `Connection.backup` in page batches, not in one step. Between batches the source lock is released, so an Engine write that was already in flight when the marker appeared can commit. SQLite then restarts the backup, and the result is still one consistent snapshot. Close both handles, then log the copy duration. If the active file is missing, skip the copy, and precompute creates the schema in the empty shadow (its `ensure_schema` runs on open).
3. **Precompute.** Run `similarity_precompute_cmd(..., out_path=<.next.db>)` through `run_with_cpu_fallback`, unchanged apart from the path. Log the duration and the shadow's `similarity_sources` count.
4. **Denylist re-apply.** Call `load_denied_hosts(prod_db)` again, fresh at this point, and run `purge_similarity_for_host` for each host on one connection to the shadow. Close it and log the per-table counts. This is a new similarity-only helper beside `purge_hosts_from_staging`. The existing `purge_hosts` is not reused, because it also deletes rows from the prod DB, and prod is being served at this point.
5. **Gate.** Open the shadow read-only and check three things: `PRAGMA integrity_check` returns exactly `ok`, both cache tables exist, and the shadow's source count is at least the active count, read now (0 if the active file is missing). The new test-only flag `--fail-similarity-gate` forces a failing reason inside this same check, so it goes through the real failure path. On a fail: log the reason with both counts, delete the shadow, and raise, which exits non-zero. The active file is never opened for writing.
6. **Swap.** Delete any old `.prev.db`, then hardlink the active file to `.prev.db` with `os.link`. If linking fails with `OSError`, fall back to `shutil.copy2`. If there is no active file, write no `.prev.db` and log that. Then `os.replace(.next.db, active)`, and log the swap duration.
7. **`finally`:** remove the marker.

Every shadow connection is closed before the next step starts. The precompute runs as a subprocess and has exited. So when the gate and swap run, no `.next.db-journal` exists. That journal name is never the served file's journal name. That covers Req 4.5.

**Engine freeze and reopen (Req 6, 7, 8).**
- **Startup (`server.py`).** Store `server.similarity_db_path` and the `(st_dev, st_ino)` of the file right after it is opened.
- **Shutdown.** Close `server.similarity_db` under `similarity_db_lock`, the way the random cache handle is already closed. Closing the startup local is not enough: after a reopen it is stale, and the live handle would leak.
- **Reopen check** (a helper in `similarity_candidates.py`, run under the lock):
  - `os.stat` the path. A missing file counts as a failed reopen.
  - If the inode matches the record, do nothing.
  - Otherwise open with `connect_similarity_db` and run a `SELECT ... LIMIT 1` on both tables. Do not run `ensure_similarity_schema`: it would create tables, and an invalid file would pass the check.
  - Stat again. If the inode moved during the open, treat it as a failure.
  - Only then install the new handle, record the new inode, close the old handle, and log `old_inode`/`new_inode`.
  - On failure, close the new handle, keep the old handle and record, and log a warning. The warning is logged once per failing target inode, so a bad file does not log on every request, but the reopen is retried on every check.
- **`_read_cache`** runs the check before every read. I chose not to throttle (see alternatives).
- **`_write_cache`**, in order: marker check (a live marker skips the write), then the reopen check, then skip the write if the handle is still stale. Skipped writes are logged at most once per 60 s, with a count of how many were skipped since the last log line. The Engine never deletes a marker.
- **Log style.** Engine lines use the `[similar-cache] key=value` style the file already uses.

**Docs (Req 9).**
- `UPDATER_WORKER.md`: the new stage order, the shadow build, the marker name and format, the gate, `.next.db`/`.prev.db`, the manual restore (stop nothing; `mv similarity-cache.prev.db similarity-cache.db`, and running Engines reopen on the inode change), and the new flag.
- `ORCHESTRATOR_SMOKE_TEST.md` and the smoke test: add a `similarity_gate` failure scenario with the new flag. For it, and for the success run, assert that no `.next.db` and no marker remain afterwards and that the active file is byte-identical (or still absent) after the gate failure.
- `CONTEXT.md`: check the `Shadow build` and `Build marker` entries against the implementation.
- ADR-0008 is followed, not revised.

**Tests.** Everything runs on temporary files under a temp dir or `tests/tmp`.
- The Engine side is tested at helper level with a stub server object (`similarity_db`, `similarity_db_lock`, `similarity_db_path`, inode record). Live and dead PIDs come from a sleeping child process and from a child that has already been reaped. The tests cover the freeze, the reopen after a replace, a reopen onto an invalid file, and threads reading concurrently during a replace.
- The updater side is tested through the smoke test and a direct test of the stage function.

### Alternatives considered

- **Throttling the Engine's inode check on reads** (e.g. once per second) was rejected. A `stat` costs microseconds next to an ANN request. A read through a stale handle also carries a real risk: it can treat the new file's live `-journal` as a hot journal for the old inode, roll it back and delete it. Checking on every access removes that within one Engine, and it is less code than a throttle.
- **`Connection.backup` in a single step** (`pages=-1`) was rejected. It holds a shared lock for the whole copy. An Engine write already in flight would wait out Python's 5 s busy timeout and fail the request on a large cache. Batching releases the lock between batches.
- **Reusing `purge_hosts` for the shadow re-prune** was rejected. It also deletes from the prod DB while the Engine serves. A similarity-only helper does exactly what Req 4.3 asks.
- **`shutil.copy` of the active file** instead of the backup API was rejected, because it is not consistent against a commit happening during the copy (Req 4.1).
- **A new module for the marker and reopen logic** was rejected in favour of two existing files: `data/similarity_cache.py` for naming and marker reading, and `data/similarity_candidates.py` for the reopen next to its only two callers. No interface, no class.
- **Leaving the shadow on disk after a failed precompute** for the next run to clean up was rejected. The file can be as large as the cache, and deleting it in the same `finally` costs one line.

### Risks, gotchas, limitations

- **Denylist `block` without `--purge-now` during a build makes the gate fail.**
  - The re-prune removes that host's sources from the shadow, but the active file still has them. The count check (shadow ≥ active) then fails and the swap is refused.
  - This fails safe: the active file is untouched, the service stays up, and the next run's post-merge safety prune removes those rows from the active file before its copy, so that run's gate passes.
  - The cost is one skipped refresh and a non-zero exit that the log reason explains.
  - It follows from Req 4.3 and Req 5 as written. I am not working around it, only naming it.
- **Denylist purge window before the swap.** A `--purge-now` that lands after the shadow re-prune but before the swap has its rows brought back. The window is about as long as the gate's `integrity_check`. This is the ceiling of the operator's choice not to make the CLI marker-aware, and making it marker-aware is the upgrade path.
- **In-flight write at marker creation.** An Engine write that checked the marker just before it was written and commits after the backup has finished would be lost from the shadow. The check and the write happen back to back under the lock, and the copy takes far longer, so the window is milliseconds. A write that commits during the copy is handled by the backup restart.
- **Two Engines (issue 26).** Engine A can reopen and write the new file while Engine B is between its inode check and its read on the old handle. A timing overlap that tight could make B treat A's journal as hot. Per-access checks make this very unlikely. It does not exist with today's single Engine.
- **Startup edge case.** The Engine creates the active file at startup (`sqlite3.connect` plus `ensure_similarity_schema`). The missing-active path therefore matters mostly for the smoke test, which starts with no cache. There the shadow starts empty, `--refresh-existing` adds nothing, the gate passes at 0 ≥ 0, and the swap creates the active file.
- **Test coverage limit.**
  - The Engine's cache path is fixed (`repo_root / DEFAULT_SIMILARITY_DB_PATH`), so no test starts a real Engine against a temporary cache. The freeze, reopen and concurrent-swap criteria are tested at helper level with a stub server.
  - "`/api/health` stays green during precompute" is verified through stage order (the start runs before the precompute) with `--skip-systemctl`.
  - The live-Engine check belongs to the manual cutover on main, which is out of scope.
- **Hardlink fallback.** On a filesystem without hardlinks, `.prev.db` falls back to a full copy. That costs time and disk equal to the cache size. It is logged.

### Tradeoffs the operator accepts

- **No live misses stored during a build.** For the whole precompute, misses are computed live and not stored. That is repeated ANN work for uncached sources until the swap. It is the freeze ADR-0008 chose.
- **One `stat` per similarity cache access** in the Engine, instead of a throttle, in exchange for never reading through a stale handle.
- **Occasional refused swaps.** A gate refusal can follow from a denylist `block` during a build, as described above. The refusal is safe, but it shows up as a non-zero updater exit.
- **Disk space.** Peak disk use during the stage is about three times the cache size: the active file, `.next.db`, and `.prev.db` (which shares its blocks with the active file when hardlinked).

## Impacts


<impact path="engine/server/data/similarity_cache.py" element="new marker helpers: cache path → `<cache>.building` path, and the 'live marker blocks writes' reader">
**What changes.** Two new module-level functions go next to `ensure_similarity_schema` (line 19). The module imports only `sqlite3` and `typing.Any` today (lines 5-6), so it gains `os` and probably `pathlib.Path`. The path helper appends `.building` to the full file name (`similarity-cache.db.building`). The reader parses a decimal PID and reports "blocks" only when `os.kill(pid, 0)` succeeds or raises `PermissionError`. A missing file, unparseable content or `ProcessLookupError` means no block.

**What depends on it.**
- `data/similarity_candidates.py` `_write_cache`, on every write.
- `engine/server/db/jobs/updater-worker.py`, for the marker name. The updater already imports `data.moderation` (lines 27-33), so `engine/server` is on `sys.path`.
- `data/similarity_cache_manager.py` imports `fetch_cached_similarities`, `has_cached_similarities` and `store_similarity_cache` from here (lines 19-23). Those names stay the same.
- `tests/active/test_updater_worker.py` and `tests/active/test_host_normalisation.py:78-87` load `updater-worker.py` in the pytest interpreter, which has no numpy. This module stays numpy-free, so the new import is safe.

**Regression risk: low, with traps.**
- `os.kill(0, 0)` or a negative PID signals the process group and succeeds. The updater's `_pid_alive` (299-309) guards `pid <= 0`. The Engine reader needs the same guard, or a marker holding `0` freezes writes forever.
- The reader runs inside a request, so it must never raise. It has to catch `OSError` and `ValueError`.
- A half-written marker reads as empty, which means no block. Writing the marker via a temp file plus `os.replace` closes that window.
- The PID can be reused. A marker left by an updater that was SIGKILLed or SIGTERMed (the default SIGTERM action skips `finally`) holds a dead PID. If the OS hands that PID to an unrelated live process, writes stay frozen until the next updater run cleans the marker up. This is accepted by ADR-0008, but it should be known.
</impact>
<impact path="engine/server/data/similarity_cache.py" element="store_similarity_cache (96-140): INSERT / DELETE / executemany, then commit, with no rollback">
**What changes.** Nothing in the plan. It is listed because of how it interacts with the reopen.

**What depends on it.** `similarity_cache_manager.write_cache` (86-96), called from `_write_cache`.

**Regression risk: medium, latent.**
- If a statement raises part-way, for example `database is locked` after the 5 s busy timeout (which is more likely now that the updater's `Connection.backup` holds shared locks), the Engine's shared handle keeps an open write transaction and a `similarity-cache.db-journal` on disk.
- Nothing rolls it back: there is no `rollback` anywhere in `similarity_cache*.py` or `similarity_candidates.py`.
- After the swap, that journal name belongs to the new file. The reopen's first `SELECT` on the new inode could treat it as hot and roll old pages into the new file.
- The reopen helper should roll back the old handle if `old.in_transaction` before it opens the new file, and/or `_write_cache` should roll back on exception.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="new reopen-check helper (stat, compare (st_dev, st_ino), open + SELECT … LIMIT 1 on both tables, re-stat, install, close old, log once per failing inode)">
**What changes.** A new private helper that runs under `similarity_db_lock`.
- It reads from the server: `similarity_db`, `similarity_db_path`, the inode record, and the last failing target inode (for logging once).
- It needs new imports: `os`, and `connect_similarity_db` from `data.db`. The current imports are lines 11-24. `data/db.py` imports only stdlib (lines 5-11), so the pytest interpreter can still import it.
- Logs use the `[similar-cache] key=value` style, as at line 78 here and in `similarity_cache_manager.py:54-69`.

**What depends on it.** `_read_cache` and `_write_cache` only. They are the only Engine users of `server.similarity_db`: grep over `engine/` finds only `server.py` setting it and these two reading it.

**Regression risk: high.**
- **Must be a no-op on stubs.** These have no `similarity_db_path`, no inode record and sometimes no handle or lock, so the helper must use `getattr` defaults and short-circuit:
  - `tests/active/test_similarity_candidates.py:85` and `tests/tmp/test_probe_36_p2.py:58` (`SimpleNamespace` without `similarity_db`).
  - `tests/active/test_video.py:169-170, 228-230` and `tests/active/test_internal_events.py:51-52` (a real `SimilarServer` built from `dict.fromkeys`, so `similarity_db=None`).
- **Create-on-missing.** `connect_similarity_db` (`db.py:141-145`) is a plain `sqlite3.connect`. If the path vanishes between the stat and the connect, the Engine creates an empty file at the active path. The table check then fails, and every later check fails against that empty inode until something replaces it. A `file:…?mode=rw` URI avoids this, but departs from the plan's wording.
- **Close ordering.** Install the new handle, then close the old one, all while holding the lock. Every caller must re-read `server.similarity_db` after the check.
- **Warning logged once per failing target inode.** The retry still runs on every access. A missing file must not log on every request.
- **Inode record of `None`.** It should count as a mismatch (see the `server.py` startup entry).
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="_read_cache (242-256)">
**What changes.**
- Today it reads `conn = getattr(server, "similarity_db", None)` at 249, before it takes the lock at 255.
- New order: take the lock, run the reopen check, then re-read `server.similarity_db`. Otherwise it reads through a handle the check just closed. `fetch_cached_similarities` catches `sqlite3.Error` (similarity_cache.py:75), which includes `ProgrammingError`, so that read would come back as a silent miss.
- The `lock is None` branch (253-254) needs a decision. No current stub reaches it with a handle.

**What depends on it.**
- `get_similar_candidates` (72).
- `get_upnext_candidates` (148). Up-next never writes, so on up-next pages the reopen is driven by reads.
- Through those, `handlers/similar.py`, the recommendation builder and `sources/cached_similar_from_likes.py`.

**Regression risk: medium.**
- One `os.stat` per call, under a lock every similarity request already serializes on.
- Behaviour is unchanged when the inode matches.
- `tests/active/test_similar.py:822-839` (up-next leaves the cache entry unchanged) still holds.
- Test groups that include this file: `test_similar.py`, `test_video.py` (via handlers), `test_similarity_candidates.py`, `test_frontend_upnext_pager.py` (config.json lines 48-64, 147-152, 169-174, 188-191).
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="_write_cache (259-274)">
**What changes.**
- New order: marker check (a live marker skips the write), then the reopen check, then skip if the handle is still stale, then `write_cache(...)`.
- Skipped writes are logged at most once per 60 s, with a count. That needs throttle state (last log time, skipped count) on the server or at module level, plus `time.monotonic`. Only `perf_counter` is imported today (line 12).
- The marker path comes from `server.similarity_db_path`, which is absent on stubs, so it must be guarded.
- The Engine never deletes a marker.

**What depends on it.** `get_similar_candidates` (88) on the home layers after a compute. Up-next never calls it.

**Regression risk: medium.**
- A marker read plus `os.kill` on every write, under the lock. It must never raise into the request.
- If the throttle state lives at module level, it is shared between tests. If it lives on the server, it needs `getattr` defaults.
- Test groups as above.
</impact>
<impact path="engine/server/data/similarity_cache_manager.py" element="write_cache / should_write_cache / read_cached_similarities (42-96)">
**What changes.** Nothing expected, because the freeze sits in `_write_cache`. If the implementer puts the marker check here instead, `should_write_cache` would need the path, which it does not have. Keep it in `_write_cache`.

**What depends on it.** `similarity_candidates.py` (imports at 18-22).

**Regression risk: low.** Listed because ADR-0008 and issue 24 name `write_cache` as the freeze point.
</impact>
<impact path="engine/server/data/db.py" element="connect_similarity_db (141-145); swap_readonly_connection (97-131) untouched">
**What changes.** Nothing. The reopen reuses `connect_similarity_db`, and `swap_readonly_connection` is explicitly not used (ADR-0008, Consequences).

**What depends on it.** `server.py:86, 337` and the new reopen helper.

**Regression risk: low.** Its create-on-missing behaviour is the hazard described in the reopen-helper entry. The `test_db.py` and `test_random_cache.py` groups map this file (config.json 15-17, 134-139, 147-152). Touching the file reselects them, so leave it unchanged.
</impact>
<impact path="engine/server/api/server.py" element="startup: similarity_db_path (328), connect + ensure_similarity_schema (337-338), SimilarServer construction (435-465)">
**What changes.**
- Store `server.similarity_db_path` (already `.resolve()`d at 328) and the `(st_dev, st_ino)` record.
- Store them either as attributes set after `server = SimilarServer(...)`, following the existing pattern at 468 (`server.embeddings_model`), or as new constructor parameters.
- Initial values for the log-once and throttle state go here too, unless the helpers use `getattr` defaults.

**What depends on it.** The reopen helper and `_write_cache`.

**Regression risk: medium.**
- **Race-safe record.** If the file is swapped between the connect at 337 and the `os.stat`, the Engine records the new inode against a handle on the old file, never reopens, and writes through a stale handle. Stat before the connect and again after `ensure_similarity_schema`, and record the inode only when the two agree (or when the file was absent before). Otherwise record `None`, so the first access reopens.
- **Startup during a live build.** `ensure_similarity_schema` still runs `CREATE … IF NOT EXISTS` on the active file, which is a no-op when the tables exist. The backup handles it.
- **Worktrees.** `scripts/worktree-setup.sh:27-28` symlinks `similarity-cache.db` from main, so `.resolve()` points every worktree Engine at main's real file. The marker and the inode are therefore derived from main's path, which is correct: a main-checkout updater run freezes and reopens worktree Engines too.
- Test groups that map `server.py`: `test_similar.py`, `test_server_config.py`, `test_internal_events.py`, `test_random_cache.py` (config.json).
</impact>
<impact path="engine/server/api/server.py" element="shutdown finally (519-533): closes startup local similarity_db at 526-527">
**What changes.** Replace the close of the startup local with a close of `server.similarity_db`, taken under `server.similarity_db_lock` and set to `None`, the same way the random cache block at 528-533 does it.

**What depends on it.** Clean shutdown under the unit's `TimeoutStopSec=20` (install-engine-service.sh:185).

**Regression risk: low.**
- After a reopen, the startup local is already closed (closing it again is harmless), and the live handle would leak.
- Taking the lock waits for an in-flight read. A read holds the lock only for one SQLite query plus a stat.
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer.__init__ (205-281)">
**What changes.** Possibly nothing. It already sets `self.similarity_db` (251) and `self.similarity_db_lock` (280). If the path, inode record and throttle state are initialised here, the signature grows.

**What depends on it.**
- The positional call at 435-465.
- `tests/active/test_video.py:169, 228` and `tests/active/test_internal_events.py:51`, which build it with `dict.fromkeys(parameters[3:])`. New parameters therefore arrive as `None`, and the helpers must tolerate a `None` path and a `None` record.

**Regression risk: low to medium.** A new positional parameter inserted mid-list desynchronises the call at 435-465. Append at the end, or set attributes after construction.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="imports (4-33)">
**What changes.**
- The marker-path helper is imported from `data.similarity_cache`.
- `shutil` is new, for the `copy2` fallback. It is not imported today.
- `os`, `sqlite3`, `time` and `logging` are already there.
- `purge_similarity_for_host` is already imported (32).

**What depends on it.** Module load in `tests/active/test_updater_worker.py:22-31` and `tests/active/test_host_normalisation.py:78-87`, both in the pytest interpreter without numpy.

**Regression risk: low**, provided `data/similarity_cache.py` stays numpy-free.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="parse_args (80-285): new --fail-similarity-gate flag">
**What changes.** A new `store_true` flag with a "Test-only: …" help, next to `--fail-after-merge-before-similarity` (260-264). The parser description (102-105) still says "... full ANN rebuild -> start service" and should mention the similarity shadow build after the start.

**What depends on it.** The gate step, the smoke test's new scenario, and the flag list in `UPDATER_WORKER.md`.

**Regression risk: low.** It is additive.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="_pid_alive (299-309) and single_run_lock (312-348)">
**What changes.** `_pid_alive` is reused for the start-of-run marker check. `single_run_lock` itself does not change.

**What depends on it.** The new start-of-run cleanup.

**Regression risk: low.** The start-of-run check and the Engine reader must agree on unparseable content: stale for the updater, non-blocking for the Engine.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="new start-of-run cleanup (first statement inside `with single_run_lock`, before load_denied_hosts at 859)">
**What changes.**
- Read `<similarity_db>.building`. If the content is unparseable or the PID is dead, unlink it and log the path and PID. If the PID is alive, leave it.
- Unlink `similarity-cache.next.db` and `.next.db-journal` if they exist, logging each removal.
- All paths derive from the resolved `similarity_db` (829).
- It runs before the dry-run return (890) and the "no changes" return (1069), as the plan intends.

**What depends on it.** Recovery from killed runs. With `TimeoutStartSec=24h` (install-updater-service.sh:338), a `systemctl stop` sends SIGTERM, which the updater does not catch, so its `finally` does not run and the marker and shadow are left behind.

**Regression risk: low.**
- **A live PID that is not an updater.** If a stale marker's PID was reused by another process, the cleanup leaves it, and `.next.db` is still deleted. The lock guarantees no other updater is running, so a live-PID marker can only be a reused PID. It is worth logging as a warning.
- **Symlinked checkouts.** If the resolved cache is shared, as in `worktree-setup.sh`, a worktree updater run with default paths would clean and build main's cache. That is the same exposure as today's in-place precompute.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main() service try/finally (1074-1171) shrink; precompute block (1148-1160) moves out">
**What changes.**
- The `try` now ends at the `--fail-after-merge-before-similarity` raise (1144-1147).
- The `finally` (1161-1171) starts the service.
- The new similarity stage runs after the `finally`, still inside `single_run_lock` and inside the outer `try` that cleans `temp_files` (1172-1177).
- With `--skip-systemctl`, `service_stopped` is never set, so the only change is ordering.

**What depends on it.**
- Issue 24's acceptance criterion "`/api/health` green during precompute".
- The smoke test's failure scenarios.
- **`tests/active/test_updater_worker.py::test_updater_main_uses_builder` (57-68).** It walks the AST of `main` only and asserts that `similarity_precompute_cmd` is a direct `ast.Name` call. If the precompute call moves into the new stage function, this test goes red. Either `main` keeps building the argv and passes it in, or the test is updated to scan the stage function. `tests/tmp/test_probe_25_p3.py` has a similar scan; it is a tmp probe and not in the suite.

**Regression risk: medium.**
- An exception in the start inside the `finally` still masks the original exception, as today.
- The early returns (890, 1069) still skip the stage.
- The final "worker completed" log (1179-1180) must still come after the stage. The smoke test's `assert_worker_log` requires it (495).
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="new similarity stage function (marker → backup copy → precompute → denylist re-prune → gate → swap → finally)">
**What changes.** A new keyword-argument function in the file's style.

**Steps.**
- **Marker.** Write the PID; tmp + `os.replace` is advisable.
- **Copy.** Open the active file through a `file:…?mode=ro` URI, then `Connection.backup(dst, pages=N)` into `.next.db`.
- **Precompute.** `similarity_precompute_cmd(out_path=.next.db)` through `run_with_cpu_fallback`.
- **Denylist re-prune.** `load_denied_hosts(prod_db)` again, then a new similarity-only helper beside `purge_hosts_from_staging` (554-568) that calls `purge_similarity_for_host`.
- **Gate.** On a read-only connection: `integrity_check == "ok"`, both tables exist, and the shadow count is at least the active count (0 if the file is missing). `--fail-similarity-gate` forces a failing reason.
- **Swap.** Unlink `.prev.db`, `os.link(active, prev)` with a `shutil.copy2` fallback on `OSError`, then `os.replace(next, active)`.
- **`finally`.** Unlink the marker. When no swap happened, also unlink `.next.db` and `.next.db-journal`.

**What depends on it.** Every Engine, which reads the marker and reopens on the new inode. Also the smoke test and the new direct test.

**Regression risk: high.**
- **Backup can hang.** CPython's `Connection.backup` retries SQLITE_BUSY/LOCKED with no limit. An Engine handle stuck holding a RESERVED/PENDING lock (see the `store_similarity_cache` entry) could stall the copy while the marker is live, and writes stay frozen for as long as it stalls. The copy duration is logged, but there is no timeout.
- **The purge creates indexes.** `purge_similarity_for_host` runs `ensure_similarity_purge_indexes` (moderation.py:326-345). The shadow therefore gains `idx_similarity_*` indexes on its first re-prune, which cost time and size. The post-merge prune already does this to the active file, so it is expected. It is a no-op when there are no denied hosts.
- **Journal names.** The shadow's journal is `similarity-cache.next.db-journal`, because the precompute opens `--out` with a plain connect (precompute-similar-ann.py:45-49, 418-419). It is never the served file's journal name, which covers Req 4.5.
- **Soft stop still exits 0.** On SIGTERM or SIGINT the precompute soft-stops and exits 0 (360-377, 575-591), leaving a partly refreshed shadow. Refresh never deletes, so the gate passes and a partial but valid refresh is swapped in. That is acceptable, but it should be logged.
- **Log wording and the smoke parser.** `parse_stage_durations` in the smoke test pairs `" run: "` and `" done: "` lines FIFO (518-527). New stage log lines must not contain `" run: "` or `" done: "`, or the stage timings shift.
- **Missing active file.** No copy is made. The precompute creates the schema. The gate passes at 0 ≥ 0 and the swap creates the active file. No `.prev.db` is written, and that is logged.
- **Hardlink semantics.** After `os.link` plus `os.replace`, `.prev.db` is the old inode that non-reopened Engines still hold. Deleting an old `.prev.db` next run removes only the name.
- **Dry-run mode.** `purge_hosts(..., dry_run=True)` at 878 still opens the active similarity DB read-write. That is harmless.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="purge_hosts (519-551): unchanged, still used for sync stale purge (878-907) and post-merge safety prune (1100-1108)">
**What changes.** Nothing. It is not reused for the shadow re-prune, because it also deletes rows from prod.

**What depends on it.** The sync-join stale purge, which runs before the stage with the service up, and the safety prune, which runs with the service stopped.

**Regression risk: low.**
- The sync-join stale purge writes to the active similarity file while the Engine is up and before the marker exists. That is the same as today.
- The safety prune still runs while the service is stopped. That keeps the plan's "the next run's prune fixes a gate failure caused by `block` without `--purge-now`" argument valid.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="similarity_precompute_cmd (415-446) and run_with_cpu_fallback (380-398)">
**What changes.** Nothing. `out_path` becomes `.next.db`. The docstring says "refreshing the existing cache in place", which becomes inaccurate, since it now refreshes the shadow. That is one line of wording.

**What depends on it.** `tests/active/test_updater_worker.py:39-54`, which checks the exact argv and must stay green.

**Regression risk: low.**
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="connect_db (45-49), ensure_schema (140-167), refresh-existing mode=ro ATTACH (443-462), soft-stop (360-377, 566-591)">
**What changes.** Nothing. It is run against `.next.db`.

**What depends on it.** The shadow build relies on four behaviours:
- It creates the schema on a missing or empty file, which covers the missing-active path.
- It attaches `--out` read-only only to select.
- It never deletes a source, so the gate's count check holds for a healthy build.
- It exits 0 on a soft stop.

**Regression risk: low.** `tests/active/test_precompute_similar_ann.py` is unaffected.
</impact>
<impact path="engine/server/data/moderation.py" element="purge_similarity_for_host (228-280), ensure_similarity_purge_indexes (326-345)">
**What changes.** Nothing. The new updater helper calls it on the shadow connection.

**What depends on it.** `purge_hosts`, `instance-denylist-cli.py:265` and the new helper.

**Regression risk: low.** It raises `ValueError` on an invalid host. Hosts from `list_active_denied_hosts` are normalized already. If it raises, the stage's `finally` still removes the marker and the shadow.
</impact>
<impact path="engine/server/db/jobs/instance-denylist-cli.py" element="run_purge similarity branch (235-272)">
**What changes.** Nothing. The plan names the ceiling: the CLI is not marker-aware.

**What depends on it.** Operators running `--purge-now` during a build.

**Regression risk: medium, behavioural.**
- **Purge after the re-prune.** A purge that lands after the shadow re-prune and before the swap has its rows brought back by the swap.
- **Purge during the copy.** It writes the active file, which restarts the backup. That is correct, but slower.
- **`block` without `--purge-now` during a build.** The gate fails on the source count, because the shadow is below the active file.
- The operator guidance belongs in `UPDATER_WORKER.md`.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="run_failure_scenarios (845-897): new similarity_gate scenario; success-run post-conditions in main (986-1025)">
**What changes.**
- Add `("similarity_gate", "--fail-similarity-gate", False)` to `scenarios` (852-856). The merge happens before it, so `db_unchanged` may be false.
- **Post-conditions for this scenario and the success run.** No `<similarity_db>.next.db`, `.next.db-journal` or `.building` remains.
- **Gate failure only.** The active file is byte-identical, or still absent. The scenario's `similarity_db` (866) starts absent, because nothing copies one in, so "still absent" is the realistic check unless the test seeds a cache to exercise the backup path.
- **Success run.** `validate_outputs` (750-751) already requires the similarity DB to exist, which the swap now creates. Optionally, `.prev.db` is absent when the active file started absent.

**What depends on it.** `ORCHESTRATOR_SMOKE_TEST.md`.

**Regression risk: medium.**
- `assert_worker_log` (482-500) still requires `precompute-similar-ann.py` and "worker completed" markers. Both stay.
- `parse_stage_durations` FIFO pairing (503-528) is fragile against new " run: " / " done: " lines.
- The smoke test needs the real crawler and a network-free whitelist server. It is not in `tests/active` and not in config.json.
</impact>
<impact path="tests/active/test_updater_worker.py" element="test_updater_main_uses_builder (57-68); new stage tests">
**What changes.**
- The AST scan of `main` for a direct `similarity_precompute_cmd` call breaks if the call moves into the stage function. Update the scan, or keep the call in `main`.
- New direct tests of the stage function on `tmp_path`:
  - success: swap, `.prev.db` and the marker removed;
  - gate failure: the active file byte-identical, the shadow and marker removed, and an exception raised;
  - a missing active file;
  - start-of-run cleanup: dead PID, live PID, unparseable content, and `.next.db` leftovers.
- The precompute subprocess can be replaced at the `run_with_cpu_fallback` / `run_cmd` boundary.

**What depends on it.** The config.json group `test_updater_worker.py` → `updater-worker.py` (205-207).

**Regression risk: medium.** The test must never touch the resolved shared `similarity-cache.db`, which is symlinked from main in worktrees.
</impact>
<impact path="tests/active/test_similarity_candidates.py" element="stub server SimpleNamespace (85) with no similarity_db / lock / path">
**What changes.** Nothing, provided the new checks short-circuit on an absent handle or path.

**Regression risk: low if guarded.** Otherwise `AttributeError` or a `TypeError` from `os.stat(None)`.
</impact>
<impact path="tests/active/test_video.py" element="direct SimilarServer construction with dict.fromkeys (169-170, 228-230), similars case">
**What changes.** Nothing, provided the helpers tolerate `similarity_db=None` and a missing or `None` path and record. The similars case goes through `get_similar_candidates` → `_read_cache` / `_write_cache`.

**Regression risk: low if guarded.** This group is reselected through `handlers/similar.py` and `db.py`.
</impact>
<impact path="tests/active/test_internal_events.py" element="SimilarServer built via dict.fromkeys (51-52)">
**What changes.** Nothing. It asserts only ingest attributes. A new constructor parameter arrives as `None`.

**Regression risk: low.** Its group maps `server.py`, so it is reselected.
</impact>
<impact path="tests/active/test_similar.py" element="session Engine against the shared similarity-cache.db (46-76, 709-716, 822-839)">
**What changes.** Nothing.

**What depends on it.** It reads the shared cache read-only and asserts that up-next leaves an entry unchanged. The home layers can write to the shared cache.

**Regression risk: low.**
- A leftover live-PID marker next to main's cache would freeze home writes during the suite. No assertion depends on home writes.
- The group maps `similarity_candidates.py` and `server.py`, so it is reselected.
</impact>
<impact path="tests/active (new file, e.g. test_similarity_cache_swap.py)">
**What changes.** New Engine helper-level tests on `tmp_path`, with a stub server holding `similarity_db`, `similarity_db_lock`, `similarity_db_path` and the inode record.
- A live PID comes from a sleeping child, and a dead PID from a reaped child.
- **Cases:**
  - freeze: a live marker adds no rows;
  - a dead-PID marker does not block;
  - reopen after `os.replace`;
  - reopen onto an invalid file: the old handle is kept, a warning is logged once, and a later valid file is picked up;
  - a missing path;
  - concurrent reader threads during a replace, with no errors.
- It imports `data.similarity_candidates`, which needs the `SERVER_DIR` and `SERVER_DIR/api` `sys.path` setup from `test_similarity_candidates.py:19-26`.

**What depends on it.** A new `test_groups` entry in `.un/skills/devsecops/config.json`.

**Regression risk: low.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (14-208)">
**What changes.**
- Add a group for the new Engine test, mapping `engine/server/data/similarity_cache.py`, `engine/server/data/similarity_candidates.py` and probably `engine/server/api/server.py`.
- **No group maps `similarity_cache.py` today.** Consider adding `similarity_cache.py` to `test_updater_worker.py`'s group (205-207), since the updater now imports it.

**What depends on it.** Test selection by `validate_tests.py`.

**Regression risk: low.** Without the new group, edits to `similarity_cache.py` select no test.
</impact>
<impact path=".gitignore" element="*.db / *.db-journal patterns (11-14)">
**What changes.** `similarity-cache.next.db`, `.prev.db` and `.next.db-journal` are already ignored. The marker `similarity-cache.db.building` is not: it ends in `.building`. During a build, or after a killed run, it shows as untracked in `git status`, and `scripts/worktree-setup.sh:51-53` warns on runtime files that show up. Consider adding `*.db.building`.

**Regression risk: low.**
</impact>
<impact path="scripts/worktree-setup.sh" element="symlink of similarity-cache.db into worktrees (27-29)">
**What changes.** Nothing.

**What depends on it.** Worktree Engines and updaters resolve to main's real file. After a swap on main, the symlink still points at the name, so the target changes inode, and worktree Engines reopen it through the resolved path, which is correct. An updater run in a worktree with default paths builds and swaps main's cache and writes the marker next to main's file.

**Regression risk: low.** Worth noting, because the random cache was deliberately copied rather than symlinked for rename reasons (line 30). Here the rename happens on the resolved target, so the symlink survives.
</impact>
<impact path="scripts/run-dataset-build.sh" element="similarity stage with --recreate-out-db on the active path (252-256)">
**What changes.** Nothing.

**What depends on it.** Once reopen exists, a running Engine sees the unlink and recreate as an inode change. It then reopens onto a half-built file and writes to it with no marker, which can contend with the build (`database is locked`).

**Regression risk: low to medium.** The full build is normally run with no Engine up. `DATA_BUILD.md` could note that.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="/api/health (472-479)">
**What changes.** Nothing. Health reads only `embeddings_count` and `embeddings_dim`, never the cache, so it stays green through the stage and on a gate failure.

**Regression risk: none.** Listed for the acceptance criterion.
</impact>
<impact path="engine/install-updater-service.sh" element="updater unit (326-339): Type=oneshot, TimeoutStartSec=24h, User=SERVICE_USER">
**What changes.** Nothing.

**What depends on it.**
- The updater and the Engine run as the same service user, so `os.kill(pid, 0)` works without `PermissionError`. The plan also treats `PermissionError` as alive.
- A `systemctl stop` of the updater sends SIGTERM to the cgroup. The updater dies without running `finally` and leaves the marker and shadow; the precompute child soft-stops.

**Regression risk: low.** Recovery is the start-of-run cleanup. Until then the dead PID is ignored.
</impact>
<impact path="docs/project/adr/0008-similarity-cache-handoff-through-files.md" element="Decision 1-3, Consequences">
**What changes.** Nothing: it is followed, not revised. The plan's per-access stat is the "implementation choice" Consequences leaves open (line 26).

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/docs/UPDATER_WORKER.md" element="Execution Order (33-59), Outputs (25-28), Service Stop/Start (89-97), Test-only flags (128-132)">
See docs_checklist. The flow it describes changes.
</impact>
<impact path="engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md" element="Purpose (6-22), failure scenarios (121-130)">
See docs_checklist.
</impact>
<impact path="CONTEXT.md" element="Shadow build (15), Build marker (16)">
See docs_checklist. Check these entries against the implementation.
</impact>
<impact path="DEPLOYMENT.md" element="The updater timer (128-141), Triage table (143-161)">
See docs_checklist. Issue 24 says the marker name and format are "recorded in the deployment docs".
</impact>
<impact path="docs/project/issues/24-similarity-cache-shadow-swap.md" element="Status line and acceptance checklist">
See docs_checklist: the status changes on completion and the issue is archived.
</impact>


## Documentation to update

- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - updated: Rewrote `UPDATER_WORKER.md` for the current stage order: the service starts again after the ANN rebuild, and the similarity cache is built as a shadow, gated and swapped in while the API serves.
- [x] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - updated: I updated `ORCHESTRATOR_SMOKE_TEST.md` to match the smoke test's current similarity stage, the new `similarity_gate` scenario and the new pass/fail checks.
- [x] `CONTEXT.md` - updated: CONTEXT.md: the `Shadow build` and `Build marker` entries now match the delivered code.
- [x] `DEPLOYMENT.md` - updated: I rewrote "The updater timer" section of DEPLOYMENT.md to describe the shadow build and swap, and added two rows to the Triage table.
- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md §5: added two paragraphs. One covers the updater's shadow build and swap and the files a killed run leaves behind. The other says to stop the Engine before a `--recreate-out-db` build against the active cache.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: I added two lines to section 2, item 3, "Similarity cache": when the Engine skips cache writes, and how it switches to a new cache file after the updater swaps one in.
- [x] `docs/project/issues/24-similarity-cache-shadow-swap.md` - updated: Issue 24 is marked complete and its archive copy is written, but I couldn't delete the original file. The checked criteria are ticked, and a "Delivered" section records the marker name.
- [x] `docs/project/issues/plan.md` - updated: I marked lane 4b (issue 24) in `docs/project/issues/plan.md` as delivered and replaced the instruction to reuse `swap_readonly_connection` with a pointer to ADR-0008.
- [x] `docs/project/adr/0008-similarity-cache-handoff-through-files.md` - out of scope: The build follows all three decisions:
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - out of scope: Its only claim on this subject is that up-next reads the similarity cache and never writes it (line 70), and that is still true. It makes no claim about home-layer writes, the marker or the reopen.
- [x] `docs/project/issues/26-zero-downtime-deploy.md` - out of scope: Line 30 only orders 26 after 24, which still holds. The "Sibling Engines stay on the old inode" note (line 41) is about the random cache's rename, not the similarity cache, so nothing it says is made false.

## Implementation plan

## Draft: similarity cache shadow build, gate, swap, Engine freeze and reopen (issue 24)

**Ladder note.** The step's ladder reached me as the unfilled placeholder `{rat_tail_ladder}`, so no ladder text was given. I wrote this draft against the two numbered steps in the prompt: first what needs testing, then the draft, then checks against the plan and the requirements.

### 1. What has to be testable

| Behaviour | Where it lives | How it is tested |
|---|---|---|
| Marker name `<cache>.building`, parse rules shared by both processes | `data/similarity_cache.py` | direct unit tests |
| Engine freeze: a live-PID marker skips writes; a dead, unparseable, `0` or oversized PID does not | `_write_cache` | stub server on `tmp_path`, live child and reaped child |
| Engine reopen after `os.replace`; old handle closed; identity updated; log | `_refresh_similarity_handle` | stub server |
| Reopen onto an invalid file or a missing path: old handle kept, warning logged once, a later valid file is picked up | same | stub server plus `caplog` |
| No handle is written through while stale | `_write_cache` | invalid file swapped in; old inode gets no new rows |
| Concurrent reads during repeated replaces: no errors | `_read_cache` | threads |
| Stubs with no path or handle are unchanged | both | existing suites, plus one small case |
| Start-of-run cleanup: dead, unparseable, live marker; `.next.db` and `-journal` leftovers | updater | direct test |
| Stage: success swap, `.prev.db` a hardlink of the old inode, marker present during the build | updater | direct test, precompute faked at `run_with_cpu_fallback` |
| Gate failures (forced flag, fewer sources, corrupt shadow), precompute failure, missing active file | updater | direct test |
| A denylist purge of the active file during the build is not undone by the swap | updater | direct test |
| Stage order: service started before the stage; nothing left behind after a run | updater, smoke | smoke test (`--skip-systemctl`) |

### 2. Module map

| File | Change |
|---|---|
| `engine/server/data/similarity_cache.py` | + `BUILD_MARKER_SUFFIX`, `build_marker_path`, `read_build_marker_pid`, `build_marker_blocks_writes` |
| `engine/server/data/similarity_candidates.py` | + `similarity_file_identity`, `_refresh_similarity_handle`, `_log_reopen_failure`, `_note_skipped_write`; `_read_cache` and `_write_cache` reordered |
| `engine/server/api/server.py` | race-safe identity record at startup; `similarity_db_path` and `similarity_db_identity` attributes; shutdown closes the live handle under the lock |
| `engine/server/db/jobs/updater-worker.py` | + path helpers, `cleanup_similarity_leftovers`, `backup_similarity_db`, `purge_hosts_from_similarity`, `count_similarity_sources`, `similarity_gate_reason`, `swap_similarity_db`, `run_similarity_stage`, `--fail-similarity-gate`; `main()` try block shrunk |
| `tests/active/test_similarity_cache_swap.py` | new (Engine side) |
| `tests/active/test_updater_worker.py` | + cleanup and stage tests (the AST test is untouched and stays green) |
| `engine/server/db/jobs/tests/test-orchestrator-smoke.py` | + `similarity_gate` scenario, leftover post-conditions |
| `.un/skills/devsecops/config.json` | + group for the new test; `similarity_cache.py` added to the `test_updater_worker.py` group |
| `.gitignore` | + `*.db.building` |
| docs | per the settled checklist (§8) |

`db.py`, `similarity_cache_manager.py`, `precompute-similar-ann.py`, `moderation.py` and `instance-denylist-cli.py` are not changed.

### 3. `engine/server/data/similarity_cache.py`

Imports become `os`, `sqlite3`, `pathlib.Path` and `typing.Any`, all stdlib, so the module stays numpy-free.

```python
# The build marker sits next to the cache as `<cache file name>.building` and holds the updater's PID as decimal text (ADR-0008).
BUILD_MARKER_SUFFIX = ".building"
# os.kill takes a pid_t: a larger number is unparseable here, not an OverflowError later.
_MAX_PID = 2**31 - 1


def build_marker_path(cache_path: Path) -> Path:
    """Return the build marker path for a similarity cache file: its full file name plus `.building`."""
    return cache_path.with_name(cache_path.name + BUILD_MARKER_SUFFIX)


def read_build_marker_pid(marker_path: Path) -> int | None:
    """Return the PID a build marker holds, or None when it is missing, unreadable, or not a decimal in 1.._MAX_PID."""
    try:
        text = marker_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not text.isdigit():
        return None
    pid = int(text)
    return pid if 0 < pid <= _MAX_PID else None


def build_marker_blocks_writes(cache_path: Path) -> bool:
    """Return True when the cache's build marker holds a live PID (os.kill(pid, 0) succeeds or raises PermissionError). Never raises."""
    pid = read_build_marker_pid(build_marker_path(cache_path))
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True
```

**What these guarantee:**
- `0`, negative numbers, empty text, anything non-decimal and oversized numbers all parse to `None`. The Engine treats `None` as not blocking, and the updater treats it as stale. That is the agreement the inventory asks for, and it comes from one parser.
- `PermissionError` is caught before `OSError`, since it is a subclass. `ProcessLookupError` means dead.

**This is three functions, not the inventory's two.** I split the parser out of the "blocks" reader so the updater's cleanup can reuse it and both processes agree on what "unparseable" means. It is the inventory's reader split in two, not a new element.

### 4. `engine/server/data/similarity_candidates.py`

New imports: `os`, `sqlite3`, `from pathlib import Path`, `from time import monotonic, perf_counter`, `from data.db import connect_similarity_db` and `from data.similarity_cache import build_marker_blocks_writes`.

```python
# A write skipped because of a live build marker or a stale handle is logged at most this often, with a count.
SKIPPED_WRITE_LOG_INTERVAL_S = 60.0


def similarity_file_identity(path: Path | None) -> tuple[int, int] | None:
    """Return (st_dev, st_ino) of path, or None when path is None or cannot be stat'ed."""
    if path is None:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_dev, stat.st_ino)


def _refresh_similarity_handle(server: Any) -> bool:
    """Reopen server.similarity_db when similarity_db_path now names a different inode; return True when the installed handle is on the active file.

    The caller holds similarity_db_lock and re-reads server.similarity_db afterwards. A server without similarity_db_path (stubs, dict.fromkeys) is untouched and reports True. On any failure (missing path, open error, missing table, inode moved during the open) the new handle is closed, the old handle and record stay, a warning is logged once per failing target, and the next call retries.
    """
    path = getattr(server, "similarity_db_path", None)
    if path is None:
        return True
    current = similarity_file_identity(path)
    recorded = getattr(server, "similarity_db_identity", None)
    if current is not None and current == recorded:
        return True
    if current is None:
        _log_reopen_failure(server, path, recorded, None, "missing")
        return False
    try:
        new = connect_similarity_db(path)
    except sqlite3.Error as exc:
        _log_reopen_failure(server, path, recorded, current, f"open: {exc}")
        return False
    try:
        # A read on each table, not ensure_similarity_schema: that would create the tables and pass an invalid file.
        new.execute("SELECT 1 FROM similarity_sources LIMIT 1").fetchall()
        new.execute("SELECT 1 FROM similarity_items LIMIT 1").fetchall()
        if similarity_file_identity(path) != current:
            raise sqlite3.DatabaseError("inode changed during reopen")
    except sqlite3.Error as exc:
        new.close()
        _log_reopen_failure(server, path, recorded, current, str(exc))
        return False
    old = getattr(server, "similarity_db", None)
    server.similarity_db = new
    server.similarity_db_identity = current
    server.similarity_db_reopen_failed = None
    if old is not None:
        old.close()
    logging.info("[similar-cache] reopen ok path=%s old_inode=%s new_inode=%s", path, recorded[1] if recorded else None, current[1])
    return True


def _log_reopen_failure(server: Any, path: Path, recorded: tuple[int, int] | None, target: tuple[int, int] | None, reason: str) -> None:
    """Log a failed reopen once per failing target inode (a missing path counts as one target)."""
    key = target or ("missing",)
    if getattr(server, "similarity_db_reopen_failed", None) == key:
        return
    server.similarity_db_reopen_failed = key
    logging.warning("[similar-cache] reopen failed path=%s old_inode=%s new_inode=%s reason=%s", path, recorded[1] if recorded else None, target[1] if target else None, reason)


def _note_skipped_write(server: Any, reason: str) -> None:
    """Count a skipped cache write; log the count at most once per SKIPPED_WRITE_LOG_INTERVAL_S. Caller holds the lock."""
    skipped = getattr(server, "similarity_write_skipped", 0) + 1
    last = getattr(server, "similarity_write_skip_logged_at", None)
    now = monotonic()
    if last is not None and now - last < SKIPPED_WRITE_LOG_INTERVAL_S:
        server.similarity_write_skipped = skipped
        return
    logging.info("[similar-cache] write skipped reason=%s skipped=%d", reason, skipped)
    server.similarity_write_skipped = 0
    server.similarity_write_skip_logged_at = now
```

`_read_cache` takes the lock first, then checks, then re-reads the handle:

```python
def _read_cache(server, source, limit, policy):
    """Read cached candidates under the similarity DB lock when available, reopening the cache first if the updater swapped it in."""
    lock = getattr(server, "similarity_db_lock", None)
    if lock is None:
        conn = getattr(server, "similarity_db", None)
        if conn is None:
            return []
        return read_cached_similarities(conn, source, limit, policy)
    with lock:
        _refresh_similarity_handle(server)
        conn = getattr(server, "similarity_db", None)
        if conn is None:
            return []
        return read_cached_similarities(conn, source, limit, policy)
```

`_write_cache` checks the marker, then runs the reopen check, then refuses a stale handle, and rolls back on error:

```python
def _write_cache(server, source, entries, policy):
    """Write candidates to cache under the similarity DB lock; skipped while a live build marker exists or while the handle is on a replaced inode."""
    if getattr(server, "similarity_db", None) is None:
        return
    lock = getattr(server, "similarity_db_lock", None)
    if lock is None:
        write_cache(server.similarity_db, source, entries, now_ms(), policy)
        return
    path = getattr(server, "similarity_db_path", None)
    with lock:
        if path is not None and build_marker_blocks_writes(path):
            _note_skipped_write(server, "build-marker")
            return
        if not _refresh_similarity_handle(server):
            _note_skipped_write(server, "stale-handle")
            return
        conn = server.similarity_db
        if conn is None:
            return
        try:
            write_cache(conn, source, entries, now_ms(), policy)
        except sqlite3.Error:
            # No open write transaction may outlive the call: after a swap its journal name belongs to the new file.
            if conn.in_transaction:
                conn.rollback()
            raise
```

**Decisions and invariants:**
- **Reads through a stale handle.** A read may go through a stale handle only while the reopen is failing, which Req 7 allows ("keep the old handle"). A write never does.
- **No lock, no reopen.** With `lock is None` the helpers do not reopen, because an unlocked reopen could close a handle another thread is using. Production always sets the lock, and the stubs that lack one also lack a path.
- **Handle closes are serialized.** Old handles are closed only under the lock, by the thread that installed the new one. Every caller re-reads `server.similarity_db` after the check, so no reader holds a closed handle.
- **Rollback in `_write_cache`, not in the reopen.** The rollback-on-error closes the `store_similarity_cache` open-transaction trap in the one place a transaction opens. That makes the rollback before reopen that the inventory suggested unnecessary.
- **Where state lives.** Throttle and log-once state is kept on the server, read through `getattr` defaults, so tests do not share it.
- **Approximate skip count.** The marker check runs before `should_write_cache`, so the skip count can include a write the policy would have declined anyway. This is a deliberate simplification: the count is only a log number.

### 5. `engine/server/api/server.py`

The import line becomes `from data.similarity_candidates import get_similar_candidates, similarity_file_identity`.

At startup (lines 337-338 become):

```python
    identity_before_open = similarity_file_identity(similarity_db_path)
    similarity_db = connect_similarity_db(similarity_db_path)
    ensure_similarity_schema(similarity_db)
    identity_after_open = similarity_file_identity(similarity_db_path)
```

After line 468:

```python
    # The reopen check compares this record with the active path; a swap (or a first-start create) between the two stats leaves it None, so the first cache access reopens onto whatever the path names then.
    server.similarity_db_path = similarity_db_path
    server.similarity_db_identity = identity_before_open if identity_before_open == identity_after_open else None
```

`None == None` also gives `None`, so a cache created at first start is reopened once, harmlessly.

At shutdown, lines 526-527 are replaced, mirroring the random cache block:

```python
        # The handle the last reopen installed, not the startup one it may already have closed; taken under the lock so no read is mid-flight on it.
        with server.similarity_db_lock:
            live_similarity_db = server.similarity_db
            server.similarity_db = None
        if live_similarity_db is not None:
            live_similarity_db.close()
```

`SimilarServer.__init__` and the positional call are unchanged, so the `dict.fromkeys` builders still work.

### 6. `engine/server/db/jobs/updater-worker.py`

**Imports:** add `import shutil` and `from data.similarity_cache import build_marker_path, read_build_marker_pid`.

**Constant and path helpers** (next to `similarity_precompute_cmd`):

```python
# Pages per Connection.backup step; the source lock is released between steps, so an Engine write already in flight when the marker appeared can commit (SQLite then restarts the copy, still one consistent snapshot).
SHADOW_BACKUP_PAGES = 1024


def similarity_shadow_path(similarity_db: Path) -> Path:
    """Return the shadow build file next to the cache: similarity-cache.db -> similarity-cache.next.db."""
    return similarity_db.with_suffix(".next" + similarity_db.suffix)


def similarity_prev_path(similarity_db: Path) -> Path:
    """Return the previous-cache file next to the cache: similarity-cache.db -> similarity-cache.prev.db."""
    return similarity_db.with_suffix(".prev" + similarity_db.suffix)


def journal_path(db_path: Path) -> Path:
    """Return SQLite's rollback journal name for db_path."""
    return db_path.with_name(db_path.name + "-journal")
```

**Start-of-run cleanup:**

```python
def cleanup_similarity_leftovers(*, similarity_db: Path) -> None:
    """Remove a stale build marker and a crashed build's shadow and journal before any stage runs."""
    marker = build_marker_path(similarity_db)
    if marker.exists():
        pid = read_build_marker_pid(marker)
        if pid is None or not _pid_alive(pid):
            marker.unlink(missing_ok=True)
            logging.info("similarity stale marker removed path=%s pid=%s", marker, pid if pid is not None else "unparseable")
        else:
            # single_run_lock rules out another updater, so a live PID here is a reused one; it is left, and Engines stay frozen until it exits.
            logging.warning("similarity marker kept path=%s pid=%d (pid alive, not an updater run)", marker, pid)
    shadow_db = similarity_shadow_path(similarity_db)
    for leftover in (shadow_db, journal_path(shadow_db)):
        if leftover.exists():
            leftover.unlink()
            logging.info("similarity leftover removed path=%s", leftover)
```

**Stage helpers:**

```python
def backup_similarity_db(*, source: Path, target: Path) -> None:
    """Copy source into target with the SQLite backup API in SHADOW_BACKUP_PAGES batches; source is opened read-only, so it can never be written or created."""
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target.as_posix())
        try:
            src.backup(dst, pages=SHADOW_BACKUP_PAGES)
        finally:
            dst.close()
    finally:
        src.close()


def purge_hosts_from_similarity(similarity_db: Path, hosts: set[str]) -> dict[str, int]:
    """Handle purge hosts from similarity: similarity-cache rows only, never the prod DB (the Engine is serving it)."""
    summary: dict[str, int] = {}
    if not hosts:
        return summary
    conn = sqlite3.connect(similarity_db.as_posix())
    conn.row_factory = sqlite3.Row
    try:
        for host in sorted(hosts):
            counts = purge_similarity_for_host(conn, host, dry_run=False)
            for table, value in counts.items():
                summary[table] = summary.get(table, 0) + int(value)
    finally:
        conn.close()
    return summary


def count_similarity_sources(path: Path) -> int | None:
    """Return COUNT(*) of similarity_sources in path, 0 when the file is missing, None when it cannot be read as a cache; opened read-only."""
    if not path.exists():
        return 0
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return int(conn.execute("SELECT COUNT(*) FROM similarity_sources").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def similarity_gate_reason(*, shadow_db: Path, similarity_db: Path, force_fail: bool) -> tuple[str | None, int | None, int | None]:
    """Check the shadow before the swap; return (reason, shadow_sources, active_sources), reason None on a pass. The active count is read now."""
    shadow_count = count_similarity_sources(shadow_db)
    active_count = count_similarity_sources(similarity_db)
    try:
        conn = sqlite3.connect(f"file:{shadow_db.as_posix()}?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchall()
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('similarity_sources', 'similarity_items')")}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"shadow unreadable: {exc}", shadow_count, active_count
    reason = None
    if integrity != [("ok",)]:
        reason = f"integrity_check={integrity[:3]}"
    elif tables != {"similarity_sources", "similarity_items"}:
        reason = f"missing tables: {sorted({'similarity_sources', 'similarity_items'} - tables)}"
    elif shadow_count is None or active_count is None:
        reason = "source count unreadable"
    elif shadow_count < active_count:
        reason = "shadow has fewer sources than active"
    if reason is None and force_fail:
        reason = "forced by --fail-similarity-gate"
    return reason, shadow_count, active_count


def swap_similarity_db(*, similarity_db: Path, shadow_db: Path, prev_db: Path) -> None:
    """Keep the active cache as prev_db (hardlink, copy on OSError, older prev replaced), then os.replace the shadow over it."""
    prev_db.unlink(missing_ok=True)
    if similarity_db.exists():
        try:
            os.link(similarity_db, prev_db)
            prev_mode = "hardlink"
        except OSError:
            shutil.copy2(similarity_db, prev_db)
            prev_mode = "copy"
        logging.info("similarity prev written path=%s mode=%s", prev_db, prev_mode)
    else:
        logging.info("similarity prev skipped: no active cache path=%s", similarity_db)
    os.replace(shadow_db, similarity_db)
```

**The stage function:**

```python
def run_similarity_stage(
    *,
    similarity_db: Path,
    prod_db: Path,
    precompute_cmd: list[str],
    repo_root: Path,
    fail_gate: bool,
) -> None:
    """Build the similarity cache in similarity-cache.next.db with the Engine serving, gate it, and swap it in; the marker is removed and an unswapped shadow deleted on every exit."""
    marker = build_marker_path(similarity_db)
    shadow_db = similarity_shadow_path(similarity_db)
    swapped = False
    # Plain write, not tmp + replace: an Engine reading the half-written marker sees "no block" and writes, which is the in-flight write the batched backup already absorbs.
    marker.write_text(str(os.getpid()), encoding="ascii")
    logging.info("similarity marker written path=%s pid=%d", marker, os.getpid())
    try:
        copy_start = time.monotonic()
        if similarity_db.exists():
            backup_similarity_db(source=similarity_db, target=shadow_db)
            logging.info("similarity shadow copy path=%s ms=%d", shadow_db, int((time.monotonic() - copy_start) * 1000))
        else:
            logging.info("similarity shadow copy skipped: no active cache path=%s", similarity_db)
        build_start = time.monotonic()
        run_with_cpu_fallback(precompute_cmd, stage="precompute-similar-ann", cwd=repo_root)
        logging.info("similarity shadow build ms=%d sources=%s", int((time.monotonic() - build_start) * 1000), count_similarity_sources(shadow_db))
        denied_hosts = load_denied_hosts(prod_db)
        reprune = purge_hosts_from_similarity(shadow_db, denied_hosts)
        logging.info("similarity shadow denylist reprune hosts=%d deleted=%s", len(denied_hosts), reprune)
        reason, shadow_count, active_count = similarity_gate_reason(shadow_db=shadow_db, similarity_db=similarity_db, force_fail=fail_gate)
        if reason is not None:
            logging.error("similarity gate result=fail reason=%s shadow_sources=%s active_sources=%s", reason, shadow_count, active_count)
            raise RuntimeError(f"Similarity gate failed: {reason}")
        logging.info("similarity gate result=pass shadow_sources=%s active_sources=%s", shadow_count, active_count)
        swap_start = time.monotonic()
        swap_similarity_db(similarity_db=similarity_db, shadow_db=shadow_db, prev_db=similarity_prev_path(similarity_db))
        swapped = True
        logging.info("similarity swap path=%s ms=%d", similarity_db, int((time.monotonic() - swap_start) * 1000))
    finally:
        if not swapped:
            for leftover in (shadow_db, journal_path(shadow_db)):
                leftover.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        logging.info("similarity marker removed path=%s", marker)
```

No log line in the stage contains `" run: "` or `" done: "`, so the smoke test's `parse_stage_durations` FIFO pairing is unaffected. The only run/done pair added is the precompute's own `run_cmd` pair, which was there before.

**`parse_args` changes:**
- The description becomes `"... merge -> incremental jobs -> full ANN rebuild -> start service -> similarity shadow build, gate and swap."`
- After `--fail-after-merge-before-similarity`, add:

```python
    parser.add_argument(
        "--fail-similarity-gate",
        action="store_true",
        help="Test-only: force the similarity pre-swap gate to fail (shadow deleted, active cache untouched, non-zero exit).",
    )
```

**The `similarity_precompute_cmd` docstring** becomes: "Build the similarity precompute command, refreshing the cache file at out_path (the shadow build's `.next.db`)."

**`main()` changes:**
- The first statement inside `with single_run_lock(lock_file):` is `cleanup_similarity_leftovers(similarity_db=similarity_db)`. It runs before `load_denied_hosts`, so it also runs before the dry-run and "no changes" returns, which stay as they are.
- In the service `try`, delete lines 1148-1160 (the precompute). The `try` now ends at the `--fail-after-merge-before-similarity` raise, and its `finally` starts the service unchanged.
- Directly after that `finally`, still inside the `with`, add:

```python
            precompute_cmd = similarity_precompute_cmd(
                python_bin=args.python_bin,
                script_path=script_dir / "precompute-similar-ann.py",
                db_path=prod_db,
                index_path=index_path,
                out_path=similarity_shadow_path(similarity_db),
                use_gpu=args.use_gpu,
            )
            run_similarity_stage(
                similarity_db=similarity_db,
                prod_db=prod_db,
                precompute_cmd=precompute_cmd,
                repo_root=repo_root,
                fail_gate=args.fail_similarity_gate,
            )
```

**Why `main` still builds the argv.** Keeping the argv built in `main` leaves `similarity_precompute_cmd` as a direct call in `main`, so `test_updater_main_uses_builder` stays green unchanged. It also means the stage function is testable with any argv. An injected or real failure in the service block propagates before the stage, and "worker completed" is still logged after it.

### 7. Tests

**`tests/active/test_similarity_cache_swap.py`** (new).
- **Setup:** the same `sys.path` setup as `test_similarity_candidates.py:19-26`. Every file is created under `tmp_path`.
- **Helpers:**
  - `_cache(path, rows)` creates a cache with `ensure_similarity_schema` and one source.
  - `_server(path)` returns `SimpleNamespace(similarity_db=connect_similarity_db(path), similarity_db_lock=threading.Lock(), similarity_db_path=path, similarity_db_identity=similarity_file_identity(path))`.
  - `live_pid` fixture: `Popen([sys.executable, "-c", "import time; time.sleep(60)"])`, terminated and waited on in teardown.
  - `dead_pid` fixture: `Popen([sys.executable, "-c", "pass"]).wait()`, so the process is already reaped.
- **Cases:**
  - `test_marker_path_appends_building`: `similarity-cache.db` gives `similarity-cache.db.building`.
  - `test_live_marker_freezes_writes`: `_write_cache` for an uncached source adds 0 rows to both tables. After the marker is unlinked, the same call stores its rows. `caplog` shows one `write skipped reason=build-marker` line for two skipped writes.
  - `test_marker_does_not_block` parametrized over dead PID, `"garbage"`, `""`, `"0"`, `"-1"` and `"99999999999"`: rows are stored, and the marker file still exists afterwards (the Engine never deletes it).
  - `test_reopen_after_replace`: `os.replace` a second cache holding entry B over the path. `_read_cache` returns B, and `server.similarity_db` is a new object. The old handle raises `sqlite3.ProgrammingError` on `execute`, the identity equals the new stat, and a `reopen ok` line carries both inodes.
  - `test_reopen_onto_invalid_file_keeps_old_handle`: replace the path with a text file, then with a schema-less SQLite file.
    - Two reads return the old entry through the old handle, and the warning is logged once per target inode.
    - `_write_cache` skips (`stale-handle`), and the old inode (kept open under another name via `os.link` before the replace) gets no new rows.
    - A valid cache then replaced over the path is picked up on the next read.
  - `test_missing_path_keeps_old_handle`: unlink the path. Reads return the old entry and the warning appears once. Restoring the path by `os.replace` is picked up.
  - `test_concurrent_reads_during_replace`: 8 threads each call `_read_cache` 200 times while the main thread `os.replace`s 20 prepared valid caches (all holding the source) over the path. There are no exceptions and every result is non-empty.
  - `test_server_without_path_is_untouched`: `SimpleNamespace(similarity_db=conn, similarity_db_lock=lock)` reads and writes as before, and no identity attributes are added.

**`tests/active/test_updater_worker.py`** (additions; the existing three tests are unchanged).
- **Helpers:**
  - `_fake_precompute(action)` monkeypatches `updater.run_with_cpu_fallback` with a function that takes `cmd`, reads `out = Path(cmd[cmd.index("--out") + 1])`, asserts the marker exists and holds `str(os.getpid())`, then runs `action(out)`.
  - `prod_db` is `tmp_path / "prod.db"`. `load_denied_hosts` creates the moderation schema, and denied hosts are inserted into `instance_denylist(host, is_active, created_at, updated_at)`.
- **Cleanup tests:**
  - `test_cleanup_removes_dead_and_unparseable_marker` (parametrized).
  - `test_cleanup_keeps_live_marker`.
  - `test_cleanup_removes_shadow_and_journal`.
- **Stage tests** (each asserts no `.next.db`, `.next.db-journal` or `.building` remains):
  - `test_stage_swaps`: the active cache has 2 sources and the fake adds 1. The active file then has 3, `.prev.db` has 2, and `os.stat(prev).st_ino` equals the old active inode.
  - `test_stage_gate_forced`: with `fail_gate=True` it raises `RuntimeError`, `similarity_db.read_bytes()` is unchanged, and no `.prev.db` exists.
  - `test_stage_gate_fewer_sources`: the fake deletes one source, and the gate raises with "fewer sources" logged.
  - `test_stage_gate_corrupt_shadow`: the fake overwrites `out` with garbage bytes, it raises, and the active bytes are unchanged.
  - `test_stage_precompute_failure`: the fake raises `CalledProcessError`, which propagates, and the active bytes are unchanged.
  - `test_stage_missing_active`: the fake creates the schema and 1 source. The active file then exists with 1 source, there is no `.prev.db`, and "prev skipped" is logged.
  - `test_stage_reapplies_denylist`: the active cache holds sources on `bad.example` and `ok.example`. Mid-build, the fake denies `bad.example` in prod and purges it from the active file with `purge_similarity_for_host`, as `--purge-now` would. After the swap, the active file has no `bad.example` rows in either table.

**`engine/server/db/jobs/tests/test-orchestrator-smoke.py`**
- Add `("similarity_gate", "--fail-similarity-gate", False)` to `scenarios`.
- New `assert_no_similarity_leftovers(similarity_db)` checks that `.next.db`, `.next.db-journal` and `.building` are absent. It is called after the success run and after every failure scenario.
- In `run_failure_scenarios`, record `sim_before = read_bytes() if exists else None` before the run. For `similarity_gate`, assert it is equal afterwards. The scenario's cache starts absent, so in practice this is the "still absent" check.
- Success run: `validate_outputs` already requires the active file. Add a check that `.prev.db` is absent, because the cache started absent.

**Config and ignore file**
- `.un/skills/devsecops/config.json`: add a `"test_similarity_cache_swap.py"` group covering `engine/server/data/similarity_cache.py`, `engine/server/data/similarity_candidates.py` and `engine/server/api/server.py`. Add `engine/server/data/similarity_cache.py` to the `test_updater_worker.py` group.
- `.gitignore`: add `*.db.building` under "Local data files".

### 8. Documentation (settled checklist, applied as written)

- **`UPDATER_WORKER.md`:**
  - Execution Order: cleanup first; the service start moves before the similarity stage; step 10 becomes the shadow build (marker `similarity-cache.db.building` holding the decimal PID, backup copy, `--refresh-existing` on the shadow, denylist re-prune, gate, swap, marker and shadow cleanup).
  - Outputs: add `.prev.db`.
  - Service Stop/Start: the service is stopped only from the merge through the ANN rebuild.
  - Add the manual restore `mv similarity-cache.prev.db similarity-cache.db`, which needs nothing stopped.
  - Add the Engine freeze, and operator notes on `block` without `--purge-now` and on a purge after the re-prune.
  - Test-only flags: add `--fail-similarity-gate`.
- **`ORCHESTRATOR_SMOKE_TEST.md`:** Purpose line 16; the `similarity_gate` scenario and its `db_unchanged` may be false; the new post-conditions.
- **`CONTEXT.md`:** the marker file name and format, ".prev.db hardlinked or copied", and reopen by inode change.
- **`DEPLOYMENT.md`:** the updater timer paragraph (stop window, marker, `.next`/`.prev`, restore, about 3× disk at peak). Two triage rows: a gate-reason non-zero exit, and a `[similar-cache] reopen failed` line.
- **`DATA_BUILD.md` §5:** the shadow build is mentioned; killed-run leftovers are removed by the next run; stop the Engine before `--recreate-out-db`.
- **`recommendations/docs/OVERVIEW.md`:** one line on the freeze and the reopen.
- **Issue 24:** `Status: enhancement, complete`, criteria ticked (live-Engine health check deferred to the cutover on main), moved to `archive/`.
- **`plan.md` line 90:** point at ADR-0008 instead of `swap_readonly_connection`.

### 9. Check against plan and requirements

**Pass 1** found one gap. The shadow's post-build count was read with a raising helper, so a corrupt shadow crashed the stage at the build log line instead of going through the gate's reason. The exit was still non-zero and the cleanup still ran, but "logs the gate reason" was not met. Fix: `count_similarity_sources` returns `None` on `sqlite3.Error`, and the gate turns `None` into a reason.

**Pass 2** converged:

| Requirement | Where it is met |
|---|---|
| **Req 1** | Stop/merge/prune/popularity/ANN/injection stay in the `try`; the `finally` starts the service; the stage runs after it; `--skip-systemctl` only changes ordering |
| **Req 2** | `cleanup_similarity_leftovers` runs first in the lock via `_pid_alive`, logs path and PID, keeps a live marker, removes `.next.db` and `-journal` |
| **Req 3** | One `build_marker_path` in the shared module; decimal PID; written before the copy; unlinked in the `finally`; name documented |
| **Req 4** | Backup API with a read-only source in batches; missing active gives an empty shadow; precompute on `.next.db` through `run_with_cpu_fallback`; fresh `load_denied_hosts` with a similarity-only purge, counts logged; the active file is never opened writable; every shadow handle is closed before gate and swap, and the precompute has exited |
| **Req 5** | integrity `ok`, both tables, shadow ≥ active read at gate time (missing counts as 0); pass gives hardlink or `copy2` `.prev.db` then `os.replace`; fail deletes the shadow, logs the reason and counts, removes the marker, raises (non-zero); the forced flag goes through the same path |
| **Req 6** | Marker check first in `_write_cache`; `os.kill` semantics; dead or unparseable ignored; the Engine never deletes |
| **Req 7** | Race-safe identity record; check under the lock; `connect_similarity_db` plus a `SELECT` on both tables; install, record, then close old; failure keeps old and retries; missing path counts as a failure; a stale write is skipped; `swap_readonly_connection` untouched; readers never hold a closed handle |
| **Req 8** | Every listed updater line and both Engine lines are present, the skip line throttled to 60 s |
| **Req 9** | §8 |
| **Acceptance** | Each criterion maps to a test in §7, except live `/api/health` during precompute, which is covered by stage order plus the smoke test and belongs to the manual cutover on main, per the plan |

### 10. Named simplifications and limits

**Path vanishing during a reopen.** The reopen uses `connect_similarity_db`, as Req 7 says, which creates the file if it is missing. If the path vanishes between the stat and the connect, an empty file appears at the active path. The re-stat catches it as a failure and the old handle stays.
- **Ceiling:** it needs a manual `rm` within microseconds of a check. Swaps and restores are renames and never make the path vanish.
- **Upgrade path:** a `mode=rw` URI variant of the open.

**The marker is written without tmp + `os.replace`.** The half-written window reads as "no block", which is the in-flight-write case the batched backup already covers. It also leaves no `.tmp` file for cleanup to handle.

**Soft-stopped precompute.** SIGTERM to the precompute makes it exit 0 with a partial refresh, which passes the gate and is swapped in. The updater does not detect this. The precompute's own log shows the soft stop, and the updater logs the shadow's source count.

**Backup can wait indefinitely.** `Connection.backup` retries busy locks with no limit. Only the copy duration is logged.

**Marker check order.** The marker check runs before `should_write_cache`, so the skipped-write count is approximate.

**Accepted as planned:** a gate refusal after a denylist `block` without `--purge-now` during a build; a `--purge-now` that lands after the re-prune is undone by the swap; PID reuse keeping a dead updater's marker "live"; the two-Engine hot-journal timing overlap for issue 26.

### Phases

#### Phase 1 - Shared build marker: Engine freeze and stale-marker cleanup [code]

**Files touched.** engine/server/data/similarity_cache.py (EDITED), engine/server/data/similarity_candidates.py (EDITED), engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_similarity_cache_swap.py (NEW), tests/active/test_updater_worker.py (EDITED), .un/skills/devsecops/config.json (EDITED), .gitignore (EDITED)

**Checkpoint.** Seam: the Engine's `_write_cache` entered with a `SimpleNamespace` stub server (`similarity_db`, `similarity_db_lock`, `similarity_db_path`, `similarity_db_identity`) on a `tmp_path` cache, following the stub-server harness of `tests/active/test_similarity_candidates.py` (same `sys.path` setup). Live PIDs come from a sleeping `Popen` child; dead PIDs come from a child that has already been waited on. Assert: with a live-PID marker, an uncached source adds 0 rows to both tables, and one `write skipped reason=build-marker` line covers two skips. Parametrized over a dead PID, `garbage`, the empty string, `0`, `-1` and `99999999999`: rows are stored and the marker file still exists. Second seam: `updater.cleanup_similarity_leftovers(similarity_db=...)` in `tests/active/test_updater_worker.py`, with the module loaded in-process through the existing `updater` fixture. Assert: a dead or unparseable marker is removed and the removal is logged with path and pid; a live-PID marker is kept; `.next.db` and `.next.db-journal` are removed.

**Intent.** Both processes judge the `<cache>.building` marker through one parser in `data/similarity_cache.py`. The Engine's `_write_cache` stores nothing while the marker holds a live PID, and the updater's `cleanup_similarity_leftovers` removes a dead marker and a crashed build's shadow before any stage.

- C1 - `_write_cache` stores no rows while the marker holds a live PID, and stores rows (leaving the marker in place) when the marker's PID is dead or unparseable.
- C2 - `cleanup_similarity_leftovers` removes a dead or unparseable marker and any `.next.db` or `.next.db-journal`, and keeps a marker whose PID is live.

**Outcome.** ### `engine/server/data/similarity_cache.py`
Added the one marker parser that both processes use, plus the `os` and `pathlib.Path` imports it needs:
- `build_marker_path(cache_path)` returns `<cache>.building`. It appends `.building` to the full file name, so `similarity-cache.db` becomes `similarity-cache.db.building`.
- `build_marker_live_pid(content: bytes) -> int | None` returns the PID only when it is alive and `None` otherwise:
  - Content that is not ASCII decimal digits after stripping is unparseable. `bytes.isdigit` refuses the signs, spaces and underscores that `int()` would accept, which covers `garbage`, the empty string and `-1`.
  - A PID of 0 or less is dead, because `os.kill(0, 0)` signals the caller's own process group and would read as alive.
  - Otherwise the PID is checked with `os.kill(pid, 0)`. `ProcessLookupError` or `OverflowError` (a PID beyond the C int range, e.g. `99999999999`) means dead. `PermissionError` means alive.
- `build_marker_blocks_writes(cache_path) -> bool` reads the marker and asks the parser. A missing marker returns `False`. Any other read error is not caught and propagates.

### `engine/server/data/similarity_candidates.py`
- `_write_cache` now runs its write, under `similarity_db_lock` when there is one, through the new `_write_cache_unless_building`. The marker check therefore happens right before the write, under the same lock.
- `_write_cache_unless_building` skips the write when `server.similarity_db_path` is set and `build_marker_blocks_writes` is true. It never deletes the marker. If there is no path (the existing stubs), there is no check.
- Skips are counted and logged at most once per `WRITE_SKIP_LOG_INTERVAL_S = 60.0`, as `[similar-cache] write skipped reason=build-marker count=N`. N is the number of skips since the last line.
  - The throttle state is kept on the server object, read through `getattr` defaults: `similarity_write_skipped` and `similarity_write_skip_logged_at`. That way `server.py` does not change, and state from an earlier server or test cannot hide the first line.
  - The file now also imports `monotonic` and `build_marker_blocks_writes`.
- With a dead or unparseable marker, `write_cache` runs as before.

### `engine/server/db/jobs/updater-worker.py`
- Imports `build_marker_live_pid` and `build_marker_path` from `data.similarity_cache`.
- New `cleanup_similarity_leftovers(*, similarity_db)`:
  - Reads the marker's bytes. If the parser finds no live PID, it unlinks the marker and logs `removed stale similarity build marker path=<marker> pid=<content>`. If the PID is live, it keeps the marker and logs a warning with the path and PID, since `single_run_lock` means such a PID can only be a reused one.
  - Then it unlinks `<stem>.next<suffix>` (`similarity-cache.next.db`) and its `-journal` if either exists, logging `removed similarity shadow leftover path=...` for each.
  - It uses the shared parser, not `_pid_alive`. The plan suggested `_pid_alive`, but it raises `OverflowError` on an oversized PID, and the intent is one parser for both processes. `_pid_alive` is unchanged and still used by `single_run_lock`.
  - None of the log lines contain ` run: ` or ` done: `, so the smoke parser's stage pairing is unaffected.
- `main()` calls `cleanup_similarity_leftovers(similarity_db=similarity_db)` as the first statement inside `single_run_lock`. That is before `load_denied_hosts`, so the cleanup runs before any stage and before the dry-run return, as the plan says.

### `.gitignore`
Added `*.db.building`, so a marker left by a running or killed build does not show as untracked. The `.next.db`, `.next.db-journal` and `.prev.db` files are already covered by `*.db` and `*.db-journal`.

### `.un/skills/devsecops/config.json`
Added `engine/server/data/similarity_cache.py` to the `test_updater_worker.py` group, because the updater now imports it.
- No `test_similarity_cache_swap.py` group yet: that test file does not exist in `tests/active`, so a group for it would appear under `unknown_groups`. It should be added when the checkpoint is promoted, mapping `similarity_cache.py` and `similarity_candidates.py`.
- `tests/active/test_similarity_cache_swap.py` (NEW) and `tests/active/test_updater_worker.py` (EDITED) are both on this phase's file list. I left both untouched because this step is production code only, and I take them to be the checkpoint's promotion target.

#### Phase 2 - Engine reopen on inode change [code]

**Files touched.** engine/server/data/similarity_candidates.py (EDITED), engine/server/api/server.py (EDITED), tests/active/test_similarity_cache_swap.py (EDITED)

**Checkpoint.** Seam: `_read_cache` and `_write_cache` entered with the same stub server in `tests/active/test_similarity_cache_swap.py`, and `os.replace` done on the stub's `similarity_db_path` under `tmp_path`. Assert, after replacing with a valid cache that holds entry B: `_read_cache` returns B; `server.similarity_db` is a new object; the old handle raises `sqlite3.ProgrammingError`; the identity equals the new stat; a `reopen ok` line carries both inodes. Assert, after replacing with a text file, then a schema-less SQLite file, then unlinking the path: reads return the old entry; the warning is logged once per target; `_write_cache` skips with `stale-handle`, and neither the old inode (kept reachable through `os.link`) nor the new file gains rows; a valid cache replaced in later is picked up. Assert, with 8 threads reading while 20 valid caches are replaced in: no exceptions and no empty results. Assert, for a stub without a path: reads and writes behave as before and no identity attributes are added.

**Intent.** Once the active cache path names a different inode, the Engine's next locked cache access moves its similarity handle onto that file if it is a valid cache. Otherwise it keeps the old handle and writes through no handle.

- C1 - After an `os.replace` with a valid cache, `_read_cache` returns the new file's rows and the old handle is closed.
- C2 - After the path is replaced with an invalid file or goes missing, reads come from the old handle and `_write_cache` adds rows to neither inode.

**Outcome.** ### `engine/server/data/similarity_candidates.py`
- New imports: `os`, `sqlite3`, `pathlib.Path`, and `connect_similarity_db` from `data.db`.
- `similarity_file_identity(path)` returns `(st_dev, st_ino)` for a path. It returns `None` when the path is `None` or cannot be stat'ed. `server.py` uses it to record the identity at startup.
- `_refresh_similarity_handle(server)` is the reopen check. The caller holds `similarity_db_lock`. It returns `True` when the installed handle is on the active file.
  - A server with no `similarity_db_path` or no handle is left alone and reports `True`. So stubs and `dict.fromkeys` servers get no new attributes, and nothing is reopened after shutdown has set the handle to `None`.
  - When the inode is unchanged, nothing happens.
  - When the inode differs, it opens the path with `connect_similarity_db` and runs `SELECT 1 … LIMIT 1` on `similarity_sources` and on `similarity_items`. It does not use `ensure_similarity_schema`, which would create the tables and let an invalid file pass. It then re-stats the path to catch a swap during the open.
  - On success it installs the new handle, records the new identity, clears the failure record, closes the old handle, and logs `[similar-cache] reopen ok path=… old_inode=… new_inode=…`.
  - On failure it closes the new handle and keeps the old handle and its identity record. Failures are: a missing path, an open error, a missing table or non-database file, or the inode moving during the open.
- `_log_reopen_failure` logs `[similar-cache] reopen failed path=… old_inode=… new_inode=… reason=…` as a WARNING once per failing target. A target is an inode, and a missing path counts as one target. The state lives in `server.similarity_db_reopen_failed`. The reopen is still retried on every check.
- `_read_cache` with a lock:
  - Order: take the lock, run the reopen check, re-read `server.similarity_db`, then read. The re-read matters because a handle taken before the check may just have been closed, and `fetch_cached_similarities` would turn a read on it into a silent miss.
  - A failed reopen still reads through the old handle.
  - Without a lock it reads as before and never reopens, because an unlocked reopen could close a handle another thread is using.
- `_write_cache` with a lock:
  - Order: marker check (`_write_blocked_by_marker`, the Phase 1 freeze), then the reopen check. If the handle is still stale after the check, the write is skipped with reason `stale-handle`. Otherwise it writes through the re-read handle.
  - Without a lock it does the marker check and writes, as before, with no reopen.
- The Phase 1 skip throttle moved into `_note_skipped_write(server, reason)`. The build-marker and stale-handle skips share it: same 60 s interval, same server attributes, line format `[similar-cache] write skipped reason=<reason> count=N`. `_write_cache_unless_building` is gone; `_write_blocked_by_marker` and `_store_cache` replace it.
- `_store_cache` rolls back on a `sqlite3.Error` if a transaction is still open. If an open write transaction were closed after a swap, it would leave a journal under the `-journal` name the new file now owns. The plan's draft puts this rollback in `_write_cache`; no checkpoint assertion covers it.

### `engine/server/api/server.py`
- It now imports `similarity_file_identity` along with `get_similar_candidates`.
- At startup it stats the cache path before `connect_similarity_db` and again after `ensure_similarity_schema`.
- After `SimilarServer` is built it sets `server.similarity_db_path`. It sets `server.similarity_db_identity` only when the two stats agree, and `None` otherwise (including when the file was created at first start), so the first locked access reopens onto whatever the path names then.
- Before this change `server.py` never set `similarity_db_path`, so the Phase 1 build-marker freeze did nothing in production. It now takes effect.
- At shutdown it closes the live `server.similarity_db` under `similarity_db_lock` and sets it to `None`, instead of closing the startup local, which a reopen may already have closed while the live handle leaked. This mirrors the random-cache block below it.

### `tests/active/test_similarity_cache_swap.py`
Not touched. The file does not exist, and I take it to be where the checkpoint gets promoted (as with Phase 1's files). The checkpoint is `tests/tmp/test_24_similarity_cache_shadow_swap_phase2.py`, and I did not modify it.

#### Phase 3 - Gated shadow build and swap [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_updater_worker.py (EDITED)

**Checkpoint.** Seam: `updater.run_similarity_stage(...)` called directly in `tests/active/test_updater_worker.py` through the in-process `updater` fixture. The precompute is faked by monkeypatching `updater.run_with_cpu_fallback`: the fake reads `--out` from the argv, asserts that the marker exists and holds `os.getpid()`, then acts on the shadow. Assert, on a pass (2 active sources, the fake adds 1): the active file has 3 sources; `.prev.db` has 2 and its `st_ino` equals the old active inode. Assert, on a missing active file: the active file is created and no `.prev.db` exists. Assert, for `fail_gate=True`, a fake that deletes a source, a fake that writes garbage bytes, and a fake that raises `CalledProcessError`: the call raises, `similarity_db.read_bytes()` is unchanged, and no `.prev.db` exists. After every case, no `.next.db`, `.next.db-journal` or `.building` remains.

**Intent.** `run_similarity_stage` swaps a shadow build that passes the gate over the active cache and keeps the replaced file. If the build or the gate fails, the active cache is untouched and nothing is left behind.

- C1 - A build that passes the gate becomes the active cache file, and `.prev.db` is the replaced active inode.
- C2 - A failed precompute or gate raises and leaves the active cache byte-identical, with no shadow or marker left behind.

**Outcome.** ### `engine/server/db/jobs/updater-worker.py`
- Added `import shutil`. It is used for the `.prev.db` copy when hardlinking fails.
- New constant `SHADOW_BACKUP_PAGES = 1024`. This is the batch size for `Connection.backup`, so the source lock is released between batches.
- New `similarity_shadow_path(similarity_db)` returns `<stem>.next<suffix>`. New `similarity_prev_path(similarity_db)` returns `<stem>.prev<suffix>`. They derive the names the same way `cleanup_similarity_leftovers` already does. That function is unchanged.
- New `backup_similarity_db(*, source, target)` copies the active cache into the shadow with the stdlib backup API, in page batches. It opens the source through a `mode=ro` URI, so the active file is never written or created.
- New `count_similarity_sources(path)` returns `COUNT(*)` of `similarity_sources`, read-only. A missing file counts as 0.
- New `similarity_gate_reason(*, shadow_db, similarity_db, force_fail)` returns `(reason, shadow_sources, active_sources)`, with `reason` set to `None` on a pass. It checks, in this order:
  - `PRAGMA integrity_check` must return exactly `ok`.
  - Both cache tables must exist.
  - The shadow's source count must be at least the active count, read at gate time.
  - `force_fail` gives the reason `forced by --fail-similarity-gate`.
  - A `sqlite3.Error` from either file becomes the reason `shadow or active cache unreadable: <error>`. SQLite's own text for a garbage shadow is `file is not a database`, which I saw in a probe.
- New `swap_similarity_db(*, similarity_db, shadow_db)`:
  - Deletes any older `.prev.db`.
  - Hardlinks the active file to `.prev.db` with `os.link`, falling back to `shutil.copy2` on `OSError`. With no active file it writes no `.prev.db` and logs that.
  - Then runs `os.replace(shadow, active)`. The active path therefore names the inode the precompute wrote, and `.prev.db` is the replaced one.
- New `run_similarity_stage(*, similarity_db, prod_db, precompute_cmd, repo_root, fail_gate)`:
  - Writes the marker `<cache>.building` with `os.getpid()` as decimal text.
  - If the active file exists, copies it into `.next.db` with the backup API.
  - Runs `precompute_cmd` through the existing `run_with_cpu_fallback`.
  - Runs the gate. A failure is logged with its reason and both counts, then raises `RuntimeError("Similarity gate failed: <reason>")`. A pass is followed by the swap.
  - A `finally` removes the marker on every exit. When no swap happened, it also deletes `.next.db` and `.next.db-journal`, so a failed precompute or gate leaves nothing behind. A `CalledProcessError` from the precompute propagates unchanged.
  - The copy, build and swap durations and the gate result are logged in the file's `key=value` style. No line contains ` run: ` or ` done: `, so the smoke test's stage-duration pairing is not affected.
  - `prod_db` is accepted but not used yet. Phase 4 uses it for the denylist re-prune of the shadow. I left that out here so Phase 4's checkpoint can still go red for the right reason.
- `main()` is not changed. It still runs the precompute in place inside the service try block. Both of these belong to Phase 4:
  - moving the call into `run_similarity_stage` after the service-start `finally`, with `out_path=similarity_shadow_path(similarity_db)`;
  - the `--fail-similarity-gate` CLI flag.

### `tests/active/test_updater_worker.py`
Not touched. I take it to be where the checkpoint gets promoted, as in Phases 1 and 2. The checkpoint `tests/tmp/test_24_similarity_cache_shadow_swap_phase3.py` was not modified.

### `tests/tmp/probe_phase3_garbage.py`
A throwaway probe confirming that a read-only `PRAGMA integrity_check` on the garbage shadow raises `DatabaseError('file is not a database')` and creates no files. My tools cannot delete files, so it is still on disk and should be removed.

**Beyond the files named.** tests/tmp/probe_phase3_garbage.py - a throwaway probe under tests/tmp. It confirmed the SQLite error text for a garbage shadow (`file is not a database`), which is what the corrupt-shadow gate reason relies on. It should be deleted; I have no tool that can remove a file.

#### Phase 4 - Stage runs while serving [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_updater_worker.py (EDITED), engine/server/db/jobs/tests/test-orchestrator-smoke.py (EDITED)

**Checkpoint.** Seam 1: a source-order AST check on `main` in `tests/active/test_updater_worker.py`, following the precedent of `test_updater_main_uses_builder` and carrying the same rat-tail note, because reaching the stage through `main` means running the whole pipeline. Assert: the `run_similarity_stage` call lies after the `try` statement whose `finally` starts the service, and no precompute call remains inside that `try`. Seam 2: `run_similarity_stage` with the faked precompute. The active cache holds sources on `bad.example` and `ok.example`. Mid-build, the fake inserts `bad.example` into prod's `instance_denylist` and purges it from the active file. Assert: after the swap, neither table in the active cache holds a `bad.example` row. Seam 3 (outside the gating suite): the orchestrator smoke test's new `similarity_gate` scenario and the no-leftover checks, run by the operator.

**Intent.** The similarity stage now runs with the Engine up, so `main` calls it after the service-start `finally`, and the stage re-prunes prod's current denylist from the shadow only.

- C1 - In `main`, `run_similarity_stage` is called after the `try` whose `finally` starts the service.
- C2 - A host denied in prod during the build has no rows in the cache the stage swaps in.

**Outcome.** ### `engine/server/db/jobs/updater-worker.py`
- `main`: the service `try` now ends at the `--fail-after-merge-before-similarity` raise. Its `finally` still starts the service on success and on failure. The precompute that used to sit inside it is gone.
- `main`: right after that `finally`, still inside `single_run_lock`, `main` builds the precompute argv with `similarity_precompute_cmd(..., out_path=similarity_shadow_path(similarity_db), ...)` and calls `run_similarity_stage(similarity_db=..., prod_db=..., precompute_cmd=..., repo_root=..., fail_gate=args.fail_similarity_gate)`. The stage therefore runs with the Engine up, and the "worker completed" log still comes after it. `main` still calls `similarity_precompute_cmd` directly, so `test_updater_main_uses_builder` stays green unchanged (C1).
- New `purge_hosts_from_similarity(similarity_db, hosts)`, next to `purge_hosts_from_staging` and in the same shape. It calls `purge_similarity_for_host` on the given cache file only and never touches prod. `purge_hosts` was not reused because it also deletes from prod while the Engine is serving.
- `run_similarity_stage`: after the precompute and before the gate, it reads prod's current active denylist again (`load_denied_hosts(prod_db)`) and re-prunes those hosts from the shadow. It logs `similarity shadow denylist reprune hosts=%d deleted=%s`; the line contains no ` run: ` or ` done: `, so the smoke parser's stage pairing is not affected. A host denied while the build runs therefore has no rows in the cache that gets swapped in (C2).
- `parse_args`: new test-only flag `--fail-similarity-gate`, placed after `--fail-after-merge-before-similarity`. It feeds the `force_fail` path that phase 3 already wired into the gate. The parser description now ends with `start service -> similarity shadow build, gate and swap.`
- `similarity_precompute_cmd` docstring: it now says the command refreshes the cache file at `out_path`, which is the shadow `.next.db`.

### `engine/server/db/jobs/tests/test-orchestrator-smoke.py`
This is the operator-run smoke test, outside the gating suite; the changes follow plan §7.
- It imports `build_marker_path` from `data.similarity_cache`.
- New `assert_no_similarity_leftovers(similarity_db)`: it fails if `.next.db`, `.next.db-journal` or `.building` exists. It is called after the success run and after every failure scenario.
- New scenario `("similarity_gate", "--fail-similarity-gate", False)`. The merge runs before the gate, so `db_unchanged` may be false for it.
- `run_failure_scenarios` records the active cache's bytes before the run, or `None` if the file is absent. For `similarity_gate` it requires them to be the same afterwards, which in practice is the "still absent" check.
- Success run: it fails if `similarity-cache.prev.db` exists, because that run starts with no cache.

### `tests/active/test_updater_worker.py`
Not changed. It has already gated, its three tests still hold against the new `main`, and the phase checkpoint carries the new stage and ordering assertions, which makes it this file's promotion target. Phases 1 and 3 handled their listed test files the same way.


