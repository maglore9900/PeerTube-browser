# 32-concurrent-engine-start-random-cache

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/01-32-concurrent-engine-start-random-cache.record.md`._

## Requirements

### Purpose

An Engine start must never exit 1 because another Engine process, started at the same time against the same checkout, is writing `engine/server/db/random-cache.db`. Today such a start dies with `sqlite3.OperationalError: database is locked` at `engine/server/data/random_cache.py:46` (`cache_db.execute("DELETE FROM random_rowids")`). In the active suite this surfaces as a whole test group erroring at Engine setup, which reads like a regression in whatever unrelated build is running. This build fixes the Engine. Reworking how the cache is built (`22-random-cache-background-refresh`, `23-random-cache-nonblocking-startup`: background rebuild, atomic swap, non-blocking startup) stays out of scope.

### Root cause found in the tree

- `engine/server/api/server.py:341-350` calls `populate_random_cache(db, random_cache_db, DEFAULT_RANDOM_CACHE_SIZE, random_cache_refresh, DEFAULT_RANDOM_CACHE_FILTERED_MODE, DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE, DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR)`, with `DEFAULT_RANDOM_CACHE_SIZE = 500000` (`engine/server/api/server_config.py:335`), `DEFAULT_RANDOM_CACHE_FILTERED_MODE = True` and `DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR = 100`.
- `populate_random_cache` (`engine/server/data/random_cache.py:30-166`) reuses the existing cache only when `not refresh and existing >= size`. One build writes at most `min(size, total rows in video_embeddings)` rows, and fewer in filtered mode when the per-author cap stops the fill short. The documented precompute run (`DATA_BUILD.md:228-236`) builds a 5000-row cache. So the reuse check never passes, and every Engine start, including under `--no-random-cache-refresh`, runs the DELETE and a full rebuild.
- The DELETE opens a write transaction that is only committed after the rebuild (`cache_db.commit()` at lines 77/165), so the write lock is held for the whole scan.
- `connect_random_cache_db` (`random_cache.py:11-15`) calls `sqlite3.connect(path.as_posix(), check_same_thread=False)` with sqlite's default 5 s busy timeout. A concurrent start that meets the held write lock fails after 5 s.

### R1 - Reuse an existing cache without writing when refresh is off

When refresh is off (`--no-random-cache-refresh`, or `--dev` without an explicit flag, or `DEFAULT_RANDOM_CACHE_REFRESH` false) and the `random_rowids` table already holds at least one row, the start uses the cache as it is and performs no write to `random-cache.db`: no DELETE, no INSERT, no write transaction. With refresh off, the cache is (re)built only when the `random_rowids` table is missing or empty.

Deliberate simplification: "non-empty" replaces "count >= size" as the reuse test, because `size` is a ceiling that one build cannot be relied on to reach. Limit: with refresh off, a short or stale cache (for example the 5000-row cache from `DATA_BUILD.md`) is kept until a refresh is asked for (`--random-cache-refresh`, a start with refresh on, or the precompute job's `--refresh`/`--reset`). Upgrade path: record the build's parameters or achieved target in the cache file and compare against those.

### R2 - A start that does write waits for the lock instead of crashing

A start that rewrites the cache (refresh on, or the cache is missing or empty) waits for another connection's write lock on `random-cache.db` to be released, rather than failing with `database is locked` after sqlite's default 5 s. The busy wait on the random-cache connection must be long enough to cover a concurrent full filtered rebuild on the real dataset. The rebuild itself may still hold the write lock for its full duration.

### R3 - Behaviour that must not change

- `engine/server/db/jobs/precompute-random-rowids.py` keeps its documented behaviour: `--refresh` always rebuilds, `--reset` clears the table first, and `--size`, `--filtered`, `--max-per-instance`, `--max-per-author` mean what they mean now.
- An Engine start with refresh on (the production default, `DEFAULT_RANDOM_CACHE_REFRESH = True`) still rebuilds the cache on every start.
- The contents a rebuild produces (unfiltered and filtered paths, shuffling, position numbering) are unchanged.
- Serving-time reads (`engine/server/data/random_videos.py:313-316`, `fetch_random_rowids` under `server.random_cache_lock`) are unchanged.

### R4 - Test harness

The cross-lane `fcntl.flock` serialisation of Engine starts in the session `engine` fixture (`tests/active/conftest.py:100-139`, `ENGINE_START_LOCK`) stays in place as a second guard. Its comment at `tests/active/conftest.py:113-115` ("Every Engine start rewrites random-cache.db, so Engines starting at once … exit on "database is locked"…") must be corrected so it no longer states that every start rewrites the cache. It should describe the flock as a guard for starts that do write. The fixture's start command, retry count and backoff are not changed.

### R5 - Tests

New tests in `tests/active` (there is currently no test of `populate_random_cache` or `connect_random_cache_db`) cover:
- (a) With refresh off, `populate_random_cache` on a non-empty cache holding fewer rows than `size` makes no write. The rows are unchanged afterwards, and the call succeeds while another connection holds a write lock on the same cache file.
- (b) A rebuild through a connection from `connect_random_cache_db` waits for a write lock held briefly (shorter than the new wait, longer than 5 s is not required) by another connection, then succeeds instead of raising `database is locked`.
- (c) With refresh off, an empty (or missing-table) cache is built.
- Where practical, a test starts several Engines at once against one checkout with the fixture's command line (`--no-random-cache-refresh`) and requires every one to become healthy.

Tests use temporary sqlite files, not the checkout's live `random-cache.db`, except for the multi-Engine test, which by nature uses the checkout's Engine start path.

### Baseline suite state

Pre-build suite exited 0 (baseline variant: false). Only `test_search_fusion.py` was selected (10 passed); the other 19 groups were unchanged and not rerun.

### Out of scope

- Background refresh, atomic swap and non-blocking startup of the random cache (`22-random-cache-background-refresh`, `23-random-cache-nonblocking-startup`).
- Changing `DEFAULT_RANDOM_CACHE_SIZE` or the other random-cache defaults.
- Retry/backoff changes in the `engine` fixture.

## High-level plan

### Approach

The fix lives in the Engine and has two parts, both in `engine/server/data/random_cache.py`, plus one argument added at the Engine's call site in `engine/server/api/server.py`, a comment fix in the test harness and a new test module.

**R1: reuse without writing.** `populate_random_cache` gets one keyword parameter that switches its reuse test from "count >= size" to "table is non-empty". It defaults to today's behaviour, so `precompute-random-rowids.py` is unaffected. Only the Engine start in `server.py` passes it; the operator chose this over changing the rule for every caller. When refresh is off and the keyword is set, the function reads the cache before touching the schema. If `random_rowids` exists and has at least one row, it returns that count straight away. On that path it sends no DDL, no DELETE, no INSERT and never begins a write transaction. The existence check reads `sqlite_master`, or equivalently tolerates a missing table on the count, before `ensure_random_cache_schema` is called. The reason: `ensure_random_cache_schema` runs `CREATE TABLE IF NOT EXISTS` through `executescript`, and whether sqlite treats that statement as a write when the table already exists depends on the version. The simplest way to guarantee "no write" is to not send it. If the table is missing or empty, the function falls through to the existing path unchanged: create the schema, DELETE, rebuild, commit. So R1's "(re)built only when missing or empty" holds. With refresh on, the reuse check is skipped as it is today, and every refresh-on start still rebuilds (R3). The code that builds the contents (unfiltered and filtered scans, shuffle, position numbering) is not touched (R3).

**R2: wait instead of crash.** `connect_random_cache_db` passes an explicit `timeout=` to `sqlite3.connect`, taken from a named module constant in `random_cache.py`. The setting belongs to the connection, so it covers all three callers: the Engine start, the precompute job and serving-time reads. For serving-time reads it only lengthens how long a read would wait on a writer's exclusive phase. The read code in `random_videos.py` and `fetch_random_rowids` does not change (R3). The value I propose is 3600 s, one hour. Nobody has measured how long a full filtered 500k rebuild takes on the real dataset, and R2 requires the wait to cover one, so the ceiling is deliberately generous. That is safe because sqlite's locks are OS file locks: a writer that dies releases them, so a waiting start only waits as long as a live writer is actually rebuilding. The rebuild still holds its write lock from the DELETE to the commit, which R2 allows.

**R3: precompute unchanged.** The job never passes the new keyword. `--refresh`, `--reset`, `--size`, `--filtered` and the per-instance and per-author caps behave exactly as now. The job also gets the longer busy wait, so a job run next to a starting Engine now waits instead of failing. That is a strict improvement and changes no documented behaviour.

**R4: harness.** In `tests/active/conftest.py`, only the comment above the flock is rewritten. It will say that a start rewrites `random-cache.db` only when refresh is on or the cache is missing or empty, and that the cross-lane flock is a second guard for those writing starts on top of the Engine's own busy wait. The start command, `ENGINE_START_ATTEMPTS`, the backoff and the flock itself stay as they are.

**R5: tests.** One new module in `tests/active` builds a tiny source database in `tmp_path`: a `video_embeddings` table, plus a `videos` table with `video_id`, `instance_domain` and `channel_id` for the filtered path. The cache files are also temporary.
- **(a)** Seed a cache with fewer rows than `size`. A second connection opens `BEGIN IMMEDIATE` and holds the write lock. The function under test runs on a cache connection opened with `timeout=0`, so any write attempt would fail at once instead of hanging. It is called with refresh off and the new keyword set. The test asserts that the call returns the existing count and that the rows are identical afterwards.
- **(b)** A second connection holds `BEGIN IMMEDIATE` on the cache file and a timer thread releases it after about 1–2 s. A rebuild with refresh on, through a connection from `connect_random_cache_db`, must succeed and produce the expected rows. The test also asserts that the connection's configured wait is longer than sqlite's 5 s default, so shrinking the constant would be caught without the test itself sleeping more than 5 s.
- **(c)** With refresh off and the keyword set, a missing-table cache and an empty-table cache are both built from the source database.
- **Multi-Engine test.** It depends on the session `engine` fixture, so the checkout's cache is known to be populated. It then starts several Engines at once without the flock, using the fixture's exact command line with `--no-random-cache-refresh` on free ports, and requires each one to answer `/api/health` 200 within the fixture's 120 s. All are terminated at the end. It uses 8 Engines, the count from the issue's failing probe.

### Alternatives considered

- **Apply the non-empty rule inside `populate_random_cache` for every caller.** Smaller diff, but a precompute run without `--refresh` would stop rebuilding a short cache, which bends R3's "`--size` means what it means now". Rejected; the operator chose the opt-in keyword.
- **Check for an existing cache in `server.py` and skip `populate_random_cache` entirely.** No change to the function's signature, but R5(a) names `populate_random_cache` as the unit under test, and the Engine's reuse policy would then sit apart from the function that owns the cache. Rejected.
- **Only lengthen the busy timeout (the issue's first candidate).** Stops the crashes, but every refresh-off start would still rebuild 500k rows while holding the lock. Parallel starts would line up behind each other and could run past the fixture's 120 s health deadline. R1 is what makes refresh-off starts cheap. Rejected on its own; kept as the R2 half of the fix.
- **Switch the cache file to WAL mode.** Readers would never block, but writers would still conflict. It also persistently changes the file format the precompute job writes and leaves `-wal`/`-shm` side files. Unnecessary for this bug. Rejected.
- **Store the build's parameters in the cache file and compare them on start.** This is R1's named upgrade path, and it is more machinery than this bug needs. Deferred.
- **Take a lock and re-check the count before rebuilding**, so that two refresh-off starts on an empty cache don't both build. It would need explicit `BEGIN IMMEDIATE` handling in a module that uses Python's implicit transactions. Rejected; the race is harmless (see Risks).

### Risks, gotchas and limitations

- **The 3600 s ceiling is not measured.** If a real filtered rebuild takes longer, a concurrent writing start would still fail, just after an hour instead of 5 s. The value is a named constant, so raising it is a one-line change. Measuring one full rebuild on the real dataset during the build would confirm it.
- **A long wait delays readiness.** A writing start that meets another writer blocks until that rebuild commits, and until then it is not healthy. That is R2's explicit trade (wait rather than crash). Removing the wait altogether belongs to issues 22/23.
- **Double build.** Two refresh-off starts on an empty cache can both see it empty. The second waits for the first, then DELETEs and rebuilds again. The result is correct but costs twice the time. This only happens on a first start with an empty cache.
- **Reading under a writer's exclusive phase.** A reuse-path read can still meet a concurrent writer's EXCLUSIVE lock during its commit or a cache spill. The longer busy wait covers it, so the read waits instead of failing.
- **Multi-Engine test cost.** Eight concurrent Engines each map the FAISS index and load the query encoder, which is heavy on memory and time for one test. If it proves too heavy on the CI host, the count can drop to a smaller N; that is the "where practical" allowance. The test also depends on the live cache being non-empty. It gets that through the session fixture, not by writing to the file itself.
- **Stale cache kept.** Accepted in R1: with refresh off, a short or stale cache is served until a refresh is requested.

### Tradeoffs the operator is asked to accept

- `populate_random_cache` gains one keyword that only the Engine uses. It is a small asymmetry between the two callers, and it is the cost of keeping precompute exactly as it is.
- The random-cache busy wait becomes very long (proposed 3600 s) instead of being sized to a measured rebuild time.
- One test starts 8 Engines at once against the checkout, which makes the active suite noticeably heavier.

## Impacts

<impacts>
<impact path="engine/server/data/random_cache.py" element="new module-level busy-wait constant (proposed 3600 s), placed above connect_random_cache_db (line 11)">
**What changes.** A named constant is added, for example `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS = 3600`. The module has no constants today and imports only `logging`, `random`, `sqlite3` and `Path` (lines 5-8). Its style is one-line `"""Handle ..."""` docstrings and no comments. The only prose needed is one `#` line above the constant saying why it is long: it must cover a concurrent full filtered rebuild, and the value was not measured.

**What depends on it.** Only `connect_random_cache_db`, plus new test (b). Test (b) asserts the configured wait is above sqlite's 5 s default, either by reading the constant or by reading `PRAGMA busy_timeout`.

**Regression risk: low in code, medium in behaviour.** The value itself is the risk; see the `connect_random_cache_db` and serving-time entries. A `> 5` assertion catches shrinking the value but not an unreasonably large one.
</impact>
<impact path="engine/server/data/random_cache.py" element="connect_random_cache_db() (lines 11-15)">
**What changes.** `sqlite3.connect(path.as_posix(), check_same_thread=False)` gains `timeout=<constant>`. `row_factory = sqlite3.Row` stays, and the signature `(path: Path) -> sqlite3.Connection` does not change.

**What depends on it.** Exactly three callers, found by grep; all of them get the longer wait.
- `engine/server/api/server.py:341` opens the Engine's one long-lived cache connection. It is used at startup by `populate_random_cache` and afterwards for every serving-time read (`SimilarServer.random_cache_db`, server.py:254).
- `engine/server/db/jobs/precompute-random-rowids.py:73` opens the job's connection, including its `--reset` DELETE (lines 74-79).
- New test (b).

**Regression risk: medium.**
- **The busy wait cannot be interrupted.** sqlite's default busy handler sleeps in C. Python signal handlers (server.py:312-313 maps SIGTERM/SIGINT to KeyboardInterrupt) only run when control returns to the interpreter. So a start blocked on another writer ignores SIGTERM until the lock clears, or up to an hour. systemd copes: `TimeoutStopSec=20` (`engine/install-engine-service.sh:185`) escalates to SIGKILL. `proc.terminate(); proc.wait(timeout=30)` teardowns do not cope (conftest.py:143-144 and the planned multi-Engine teardown): they raise `TimeoutExpired`.
- **Serving-time reads** now wait up to an hour instead of failing after 5 s (see the `random_videos.py` entry).
- **The precompute job** now waits when an Engine is rebuilding. That is intended, but a job run by hand next to a refresh-on Engine will look like a silent hang.
- **No statement deadline.** Unlike `connect_db` (`data/db.py:76`, progress handler installed at :41), this connection has no progress handler, and the change does not add one. Archived plan 05 records that `random_cache_db` was left unbounded on purpose.
</impact>
<impact path="engine/server/data/random_cache.py" element="populate_random_cache() signature and reuse check (lines 30-45)">
**What changes.**
- **Signature.** One new parameter, for example `reuse_non_empty: bool = False`, goes after `max_per_author`. Both existing callers pass all seven arguments positionally (server.py:342-350, precompute-random-rowids.py:80-88), so the new parameter must go last or be keyword-only (`*,`, not used anywhere in this file today). The default of False keeps today's behaviour exactly.
- **Reuse check.** When `not refresh and <keyword>`, the function acts before `ensure_random_cache_schema` (line 42). It checks `sqlite_master` for `random_rowids`; the in-tree idiom is `engine/server/data/videos.py:10-15`: `SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '...' LIMIT 1`. If the table exists, it runs `SELECT COUNT(*)`. If the count is above 0, it returns the count with no DDL, DELETE, INSERT or commit. Otherwise it falls through to the existing path unchanged.
- **Unchanged guard.** The `size <= 0 → return 0` guard (line 40) stays first.
- **Keyword False.** Lines 42-45 run as today: schema first, then `count >= size`.

**What depends on it.**
- `server.py:342`, which passes the keyword.
- `precompute-random-rowids.py:80`, which never passes it.
- New tests (a) and (c).
- Indirectly, every test group that imports `data.random_videos`, because that module imports `data.random_cache` at line 9.

**Regression risk: medium.**
- **Lingering read lock.** The reuse read runs on the Engine's long-lived connection, so both queries must be fully consumed with `fetchone()`, as line 43 already does. A statement left un-reset would keep a SHARED lock on `random-cache.db` for the Engine's lifetime. Every other process's commit would then wait the full new timeout. Under Python's legacy transaction handling, a bare SELECT issues no BEGIN.
- **Row factories.** `existing[0]` works for both `sqlite3.Row` and plain tuples, which matters for the test's `timeout=0` connection. The source DB connection, however, must use `row_factory = sqlite3.Row`, because the build path indexes by name (`total_row["total"]`, `row["rowid"]`, `entry["instance_domain"]`). Tests (b) and (c) must set it.
- **Empty table.** An empty table still falls through to DELETE and a rebuild. Two refresh-off starts on an empty cache both build; this is the plan's accepted double build. The second start now waits instead of crashing.
- **Evidence on the DDL.** The issue's probe failed only at line 46, never at line 42. So on this machine `CREATE TABLE IF NOT EXISTS` on an existing table did not hit the lock. Skipping it anyway removes the version dependence.
</impact>
<impact path="engine/server/data/random_cache.py" element="ensure_random_cache_schema() (lines 18-27)">
**What changes.** Nothing in the function. It is now skipped on the reuse path and still runs on every other path.

**What depends on it.** `populate_random_cache` (line 42) and `precompute-random-rowids.py:77`. The `--reset` branch there creates the table before its own DELETE.

**Regression risk: low.** `executescript` still commits any pending transaction first. The reuse check must stay above this call, or R1's "no DDL" guarantee is lost.
</impact>
<impact path="engine/server/data/random_cache.py" element="populate_random_cache() build body: DELETE (46), unfiltered scan (47-78), filtered scan with try_add/scan_range (80-166)">
**What changes.** Nothing (R3). The write lock is still held from the DELETE at 46 to the commit at 77 or 165.

**What depends on it.** Every refresh-on Engine start (the production default `DEFAULT_RANDOM_CACHE_REFRESH = True`, server_config.py:342), every precompute run that rebuilds, and every refresh-off start that finds the table missing or empty.

**Regression risk: low for content, medium for concurrency.** A 500k-row INSERT can spill sqlite's page cache and take EXCLUSIVE before the commit. In rollback-journal mode that blocks readers for the rest of the rebuild, and those readers now wait instead of failing after 5 s. Moving the early commits (52, 56) or the DELETE would change R3 behaviour.
</impact>
<impact path="engine/server/data/random_cache.py" element="fetch_random_rowids() (lines 169-184)">
**What changes.** No code change (R3). It now runs on a connection with the long busy wait.

**What depends on it.** `engine/server/data/random_videos.py:316`.

**Regression risk: low.** It assumes `random_rowids` exists. That holds, because the Engine reaches serving only through the reuse path (table exists and is non-empty) or the build path (schema created). It would break if the reuse path ever returned without the table existing.
</impact>
<impact path="engine/server/api/server.py" element="main(): populate_random_cache call (lines 340-350) and refresh resolution (lines 319-322)">
**What changes.** The call gains the new keyword set to True. The positional arguments stay, and the return value is still ignored.

**What depends on it.** Every way the Engine is started:
- The systemd unit (`engine/install-engine-service.sh:183`, no refresh flag): refresh on, so the rebuild is unchanged.
- `scripts/run-services.sh:146` (no flag): refresh on.
- `--dev` without a flag: refresh off (server.py:320), so it now reuses the cache.
- `tests/run-arch-split-smoke.sh:526` and the `tests/active` `engine` fixture, both with `--no-random-cache-refresh`: they now reuse the cache.

**Regression risk: medium.**
- **Short caches are kept.** Refresh-off starts no longer rebuild a short cache. On the documented 5000-row cache (DATA_BUILD.md:231) they now serve 5000 rows until a refresh is asked for. This is R1's accepted limit.
- **Unhealthy while waiting.** The call sits after the signal handlers (312-313) and before the `try:` around `serve_forever` (481). A start waiting on the lock is not healthy and does not react to SIGTERM until the wait ends.
- **Log line.** The line at 473-477 reports only `random_cache_refresh`. Optionally, log the returned count and which path was taken, to help diagnose a stale cache.
- **Suite reselection.** Editing `server.py` reselects the `test_server_config.py` and `test_internal_events.py` groups (`.un/skills/devsecops/config.json:105-115`).
</impact>
<impact path="engine/server/api/server.py" element="parse_args(): --dev help (lines 146-153), --random-cache-refresh / --no-random-cache-refresh help (lines 168-181)">
**What changes.** No code change is required. "Disable random cache refresh on startup." (line 179) and "disable random cache refresh" in `--dev` (line 150) now mean: reuse any non-empty cache, and build only when it is missing or empty. The help text could say so.

**What depends on it.** `--help` output only. `tests/active/test_server_config.py:57-65` runs `server.py --help` and asserts only the return code and `"--port PORT"`, so rewording these strings is safe.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer.random_cache_db / random_cache_lock (lines 215, 254, 283) and shutdown close (499-500)">
**What changes.** Nothing in code. The connection stored here now carries the long busy timeout.

**What depends on it.** `fetch_random_rows_from_cache` (random_videos.py:313-316) holds `random_cache_lock`, a plain `threading.Lock`, around `fetch_random_rowids`.

**Regression risk: medium.**
- **How the stall happens.** Suppose another process holds EXCLUSIVE on `random-cache.db` while this Engine is serving. That process could be a refresh-on Engine start, or the precompute job. The first random read then blocks inside sqlite while holding `random_cache_lock`, and every other request thread that needs the random cache queues behind it.
- **What changes.** Before, that read failed after 5 s. Now it can hang for up to 3600 s, and no statement deadline applies to this connection.
- **When it can happen.** Only when a writer and a serving Engine share one `random-cache.db`.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_random_rows_from_cache() (lines 309-327) and module import of fetch_random_rowids (line 9)">
**What changes.** Nothing (R3).

**What depends on it.** `engine/server/api/handlers/similar.py:647`, and the recommendation deps wired at server.py:396.

**Regression risk: medium, behavioural only.** An `OperationalError('database is locked')` used to surface here after 5 s; now the call waits instead. The DB fallback in `_fetch_random_rows` (similar.py:650-657) runs only on empty rows, never on an error. Leaving this file untouched keeps the `test_random_videos.py` group (config.json:91-93) unselected.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_fetch_random_rows() (lines 645-657)">
**What changes.** Nothing.

**What depends on it.** The random feed (`random=1`) on `/recommendations` and `/videos/similar`. That includes the live-Engine tests `tests/active/test_similar.py:89-90,110`.

**Regression risk: low.** It inherits the serving-time wait. The request's `statement_deadline` covers `server.db` only.
</impact>
<impact path="engine/server/api/recommendations/builder.py" element="fetch_random_rows_from_cache_filtered (lines 97-103) and its two wirings (167, 181)">
**What changes.** Nothing.

**What depends on it.** The explore and random candidate layers.

**Regression risk: low.** It inherits the same serving-time wait under `random_cache_lock`.
</impact>
<impact path="engine/server/api/recommendations/candidates/random_videos.py" element="random layer: deps.fetch_random_rows_from_cache call (line 133)">
**What changes.** Nothing.

**Regression risk: low.** It only inherits the serving-time wait.
</impact>
<impact path="engine/server/api/recommendations/candidates/explore_range.py" element="explore layer: deps.fetch_random_rows_from_cache call (line 154)">
**What changes.** Nothing.

**Regression risk: low.** It only inherits the serving-time wait.
</impact>
<impact path="engine/server/api/recommendations/candidates/similar_from_likes.py" element="optional random fallback via deps.fetch_random_rows_from_cache (lines 43-44)">
**What changes.** Nothing.

**Regression risk: low.** It only inherits the serving-time wait.
</impact>
<impact path="engine/server/db/jobs/precompute-random-rowids.py" element="main(): connect (73), --reset branch (74-79), populate call (80-88), --refresh help (47)">
**What changes.** No code change. The job never passes the new keyword, so `--refresh`, `--reset`, `--size`, `--filtered`, `--max-per-instance` and `--max-per-author` behave as today (R3). Its connection gets the long busy wait.

**What depends on it.** `scripts/run-dataset-build.sh:262-264` and the manual command in DATA_BUILD.md:228-236.

**Regression risk: low.**
- The `--reset` DELETE (line 78) and the rebuild now wait behind a running Engine's rebuild instead of failing after 5 s.
- The `--refresh` help, "Rebuild cache even if it already meets the size.", stays accurate, because the job keeps the `count >= size` rule.
- The positional call at 80-88 breaks if the keyword is inserted before `max_per_author`.
</impact>
<impact path="scripts/run-dataset-build.sh" element="random stage (lines 260-265)">
**What changes.** Nothing. It still builds a 5000-row filtered cache with `--reset`.

**Why it matters.** A refresh-off Engine (`--dev`, `--no-random-cache-refresh`, the test fixture, the smoke script) now keeps this 5000-row cache. A refresh-on Engine still replaces it on its first start.

**Regression risk: none in code.**
</impact>
<impact path="engine/server/api/server_config.py" element="random cache block: DEFAULT_RANDOM_CACHE_SIZE (335), FILTERED_MODE (337), caps (339-340), comment and DEFAULT_RANDOM_CACHE_REFRESH (341-342), DEFAULT_RANDOM_CACHE_DB_PATH (367)">
**What changes.** Nothing; the values are out of scope. The comment at 341 stays true for refresh on. The busy-wait constant belongs in `random_cache.py`, not here.

**What depends on it.** `server.py:33-37, 50`.

**Regression risk: none.** Editing this file would reselect `test_dislike_profile.py`, `test_similar.py`, `test_server.py`, `test_server_config.py` and `test_internal_events.py` (config.json), so leaving it alone keeps the run small.
</impact>
<impact path="tests/active/conftest.py" element="engine fixture: flock comment (lines 113-115)">
**What changes.** Only this comment (R4).
- **Now:** "Every Engine start rewrites random-cache.db, so Engines starting at once (one per lane) exit on "database is locked"...".
- **Becomes:** a start rewrites the cache only when refresh is on or the cache is missing or empty, and the flock is a second guard for those writing starts on top of the Engine's own busy wait.

The command at 120-123 (with `--no-random-cache-refresh`), `ENGINE_START_ATTEMPTS` (100), the `1 + attempt` backoff (136) and the flock (116-117) all stay.

**What depends on it.** Every Engine-backed group. Editing conftest.py previously reselected every conftest-dependent group (the 16-15 record, step 8), so this edit may trigger a wide parallel rerun. That is exactly the case the fix should make safe, so the rerun doubles as a check.

**Regression risk: low.**
</impact>
<impact path="tests/active/conftest.py" element="engine fixture env (line 110), module-level names (ROOT/ENGINE_PY/ENGINE_SERVER 31-33, BRIDGE_TOKEN 35, _free_port 94-97), retry loop (118-138), teardown (141-145)">
**What changes.** Nothing under R4. The multi-Engine test depends on this code.

**What depends on it.** The new multi-Engine test.
- **Env is not importable.** `env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}` is a local variable inside the fixture. Only `ROOT`, `ENGINE_PY`, `ENGINE_SERVER`, `BRIDGE_TOKEN` and `_free_port` are module-level. So the new test must duplicate the env and the command line, which can drift from the fixture's "exact command line".
- **The alternative is out of R4 scope.** Lifting the env and command line into a shared module-level helper prevents drift, but it is a code edit beyond R4's comment-only scope; that is the operator's call.
- **Port collisions.** The fixture's retry loop covers a port collision between `_free_port()` and Popen. The multi-Engine test has no such loop, so a collision would fail it for a reason unrelated to the fix.

**Regression risk: low (fixture), medium (drift or flake in the new test).**
- **Teardown.** The fixture teardown `proc.wait(timeout=30)` can raise if an Engine is stuck in the new busy wait. With refresh off and a non-empty cache, the fixture's Engine never waits.
</impact>
<impact path="tests/active/test_random_cache.py" element="new test module (working name; the plan names none): imports and source-DB helper">
**What changes.** A new file.
- **Imports.** Follow `tests/active/test_random_videos.py:24-29`: put `engine/server` and `engine/server/api` on `sys.path`, then `from data.random_cache import ...  # noqa: E402`. `random_cache.py` imports only the stdlib, so the module runs in the pytest interpreter without an `ENGINE_PY` child. The multi-Engine test imports `ENGINE_PY`, `ENGINE_SERVER`, `BRIDGE_TOKEN` and `_free_port` from `conftest`, the same way `test_similar.py:60` imports from it.
- **Source DB.** In `tmp_path`: `video_embeddings` as a rowid table with `video_id` and `instance_domain`, and `videos` with `video_id`, `instance_domain` and `channel_id` for the filtered JOIN (random_cache.py:117-131). Set `row_factory = sqlite3.Row` on the source connection.
- **Unit tests stay off the live cache.** They must never open the live `engine/server/db/random-cache.db`.

**What depends on it.** `validate_tests.py` sees the file as an unmapped group, so it runs on every invocation until config.json maps it.

**Regression risk: medium for suite stability.** See the per-test entries below.
</impact>
<impact path="tests/active/test_random_cache.py" element="test (a): refresh off + keyword on a short non-empty cache under a held write lock">
**What changes.** New test.
1. Seed the cache with fewer rows than `size`.
2. A holder connection runs `BEGIN IMMEDIATE`, which takes RESERVED; readers are still admitted in rollback-journal mode. The holder must write nothing, or a cache spill could take EXCLUSIVE and block the read.
3. Call the unit on `sqlite3.connect(..., timeout=0)` with refresh off and the keyword set.
4. Assert the returned count and that the rows are identical afterwards.

**Control assertion.** The same call without the keyword should raise `OperationalError` on the locked file, which proves the lock is real. Python's legacy transaction handling issues an implicit BEGIN before the DELETE at line 46, so after the failure that connection is left with `in_transaction` true. Run the control on its own connection and roll it back or close it. Never run it on the connection used for the keyword call or the row comparison.

**Regression risk: medium.** A contaminated connection makes the "rows unchanged" read unreliable.
</impact>
<impact path="tests/active/test_random_cache.py" element="test (b): rebuild through connect_random_cache_db waits for a briefly held lock">
**What changes.** New test.
1. A holder takes `BEGIN IMMEDIATE`.
2. A timer thread releases it after 1-2 s.
3. A refresh-on rebuild through `connect_random_cache_db` must succeed and produce the expected rows.
4. `PRAGMA busy_timeout` (milliseconds) on that connection must be > 5000.

**Pitfalls.**
- **Thread affinity (hang risk).** A connection from `sqlite3.connect` defaults to `check_same_thread=True`. If the holder is opened in the test thread and released from the timer thread, the release raises `ProgrammingError`, the lock is never freed, and the rebuild blocks for the full 3600 s. The test then hangs for an hour instead of failing. Open the holder with `check_same_thread=False`, or take and release it inside one helper thread. Release it in `finally`.
- **Arming check.** Nothing yet proves the rebuild actually waited: if `BEGIN IMMEDIATE` never took the lock, (b) passes trivially. Assert either that elapsed time is at least the hold duration, or that a `timeout=0` connection's DELETE raises `OperationalError` while the holder is live. Roll back and close that control connection.

**Regression risk: medium to high.** Built naively, it stalls the suite for an hour instead of failing.
</impact>
<impact path="tests/active/test_random_cache.py" element="test (c): refresh off + keyword on missing-table and empty-table caches">
**What changes.** New test. With refresh off and the keyword set, both a fresh file with no table and a file with an empty `random_rowids` must be built from the source DB. The returned count must equal the row count.

**Regression risk: low.** It needs the source connection's `sqlite3.Row` factory. Randomness in the start rowid and the shuffle means asserting a set or count, not an order.
</impact>
<impact path="tests/active/test_random_cache.py" element="multi-Engine test: 8 concurrent refresh-off Engines, no flock">
**What changes.** New test.
1. Depend on the `engine` fixture, so the worktree's cache is known to be non-empty.
2. Start 8 Engines with `ENGINE_PY`/`ENGINE_SERVER`, the duplicated fixture env and `--no-random-cache-refresh`, each on its own `_free_port()`.
3. Require `/api/health` 200 from each within 120 s.
4. Give each Engine its own log file, not a shared pipe that can fill.
5. Teardown terminates each one, falling back to `kill()` on `TimeoutExpired`.

**Regression risk: medium.**
- **Load.** 9 Engines run at once. The plan overstates the cost: `QueryEncoder` loads nothing at startup (the model import is lazy, `engine/server/data/query_encoder.py`), and the index is opened `IO_FLAG_MMAP | IO_FLAG_READ_ONLY` (server.py:355).
- **Other startup DDL.** The other startup DDL (moderation, interaction_events, similarity, channel and video indexes) is all `IF NOT EXISTS` or checks `sqlite_master` first, per the step 4 reassessment. It still runs with the default 5 s busy wait on the shared `whitelist.db`/`similarity-cache.db`.
- **Flakes.** Port collisions and env drift are possible (see the conftest env entry).
- **Hands off the cache file.** The test must never write `random-cache.db` itself.
</impact>
<impact path="tests/active/test_random_videos.py" element="sys.path setup (24-29) and import of data.random_videos (33), which imports data.random_cache">
**What changes.** Nothing. It is the import pattern for the new module.

**What depends on it.** It imports `data.random_cache` transitively (random_videos.py:9). An import-time error in the edited `random_cache.py` would break this group. But config.json maps the group only to `engine/server/data/random_videos.py` (lines 91-93), so an edit to `random_cache.py` alone does not reselect it.

**Regression risk: low.** Selection could miss a break until the mapping is fixed; see the config.json entry.
</impact>
<impact path="engine/server/data/db.py" element="connect_db (76), connect_readonly_db (84), connect_similarity_db (104): default 5 s busy timeout for the other startup DDL">
**What changes.** Nothing.

**Why it is listed.** The multi-Engine test runs 8 concurrent starts of this DDL against the shared symlinked `whitelist.db` and `similarity-cache.db`. The step 4 reassessment read the ensure_* functions and found none that writes against an existing schema. The issue's probe also failed only at random_cache.py:46.

**Regression risk: low.** If the multi-Engine test does fail with "database is locked" in one of these, the fault lies outside this plan.
</impact>
<impact path="engine/server/data/videos.py" element="ensure_video_indexes sqlite_master checks (lines 10-15)">
**What changes.** Nothing.

**Why it is listed.** It is the in-tree idiom for the new existence check. The check should be a private helper in `random_cache.py`, not an import from `data.moderation` (`_table_exists`).

**Regression risk: none.**
</impact>
<impact path="engine/server/data/query_encoder.py" element="QueryEncoder.__init__ and lazy _acquire_model">
**What changes.** Nothing.

**Why it is listed.** It corrects the plan's cost estimate for the multi-Engine test: Engines do not load the encoder at startup.

**Regression risk: none.**
</impact>
<impact path="engine/server/db/random-cache.db" element="the worktree's live cache file (copied, not symlinked, by scripts/worktree-setup.sh:31; present in this worktree)">
**What changes.** Nothing directly. The fixture's refresh-off Engines now reuse whatever it holds, for example a 5000-row build, instead of rewriting it on every start.

**What depends on it.** The session `engine` fixture, the multi-Engine test, and the random-feed tests in `test_similar.py` that go through the live Engine.

**Regression risk: low.**
- **Empty file.** If the file is empty or has no table, the first start builds it. The multi-Engine test avoids racing that by depending on the session fixture first.
- **Unverified contents.** I could not check its row count with these tools, so that the cache is non-empty is assumed, not seen.
- **Pool size.** Pool size may differ from before, and no test asserts it.
</impact>
<impact path="scripts/worktree-setup.sh" element="comment 'Rewritten on every Engine start: private.' (line 30) and cp (line 31)">
**What changes.** An optional comment fix. After this build, refresh-off starts no longer rewrite the file, but refresh-on starts and missing or empty caches still do. So the copy should stay private.

**Regression risk: none.**
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="Engine start with --no-random-cache-refresh (lines 523-536)">
**What changes.** Nothing in the script. Its Engine now reuses a non-empty cache and starts faster; a missing or empty cache is built as before.

**Regression risk: low.**
</impact>
<impact path="scripts/run-services.sh" element="Engine start (line 146), no refresh flag">
**What changes.** Nothing. Refresh stays on, so it still rebuilds on every start, now with the long busy wait if another writer holds the file.

**Regression risk: low.**
</impact>
<impact path="engine/install-engine-service.sh" element="ExecStart (line 183), TimeoutStopSec=20 (line 185)">
**What changes.** Nothing. Production keeps refresh on and still rebuilds. A stop during a busy wait escalates to SIGKILL after 20 s.

**Regression risk: low.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (lines 14-129)">
**What changes.** Nothing during the build. At harvest, add a `test_groups` entry for the new module mapping `engine/server/data/random_cache.py`, `engine/server/api/server.py` and `engine/server/db/jobs/precompute-random-rowids.py`. Also consider adding `engine/server/data/random_cache.py` to the `test_random_videos.py` entry, since that group imports it transitively.

**What depends on it.** `validate_tests.py` group selection. No group maps `random_cache.py` today.

**Regression risk: low.** `.un/` is local config. Until the new group is mapped, it runs as unmapped on every invocation, which puts the heavy 8-Engine test in every suite run.
</impact>
<impact path="tests/last_test_validation.json" element="tracked suite record, with tests/last_test_output.txt">
**What changes.** Every `validate_tests.py` run in this build rewrites it.

**Regression risk: merge process only.** On merge, take main's copy and re-run `--compare`.
</impact>
<impact path="DEPLOYMENT.md" element="expected files list (line 64)">
**What changes.** Nothing. It only lists `engine/server/db/random-cache.db` as an expected file.

**Regression risk: none.**
</impact>
</impacts>

## Documentation to update

- [x] `docs/project/issues/32-concurrent-engine-start-random-cache-lock.md` - updated: Issue 32 is closed as `bug, complete` and a delivery comment is added, but the archive move is only half done: `docs/project/issues/32-concurrent-engine-start-random-cache-lock.md` still has to be deleted, and I have no tool that can delete files.
- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md §6: added two sentences after the precompute code block on how the Engine treats this cache and how the job handles a concurrent rebuild.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: LAYER_PARAMS.md "Random Cache Params (Global)": the cache size is now described as what a build aims for, and the section says what a refresh-off start does.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md §2 item 4 now describes the random-cache size as a build target, and says a refresh-off start reuses any non-empty cache.
- [x] `docs/project/issues/plan.md` - updated: Marked lane 1a (issue 32) as delivered with the files that actually changed, and added 32's leftovers to the notes for lane 2d (22+23).
- [x] `docs/project/issues/23-random-cache-nonblocking-startup.md` - updated: Added a comment to issue 23 saying what issue 32 changed and which parts of the startup-downtime problem are still open.
- [x] `scripts/worktree-setup.sh` - updated: Corrected the random-cache comment in `scripts/worktree-setup.sh`: the cache is rewritten by refresh-on starts and when it is missing or empty, not on every start.
- [x] `docs/project/issues/22-random-cache-background-refresh.md` - out of scope: Its only claim about current behaviour is "The random cache is rebuilt only on server start and/or on a refresh flag." That is still true: the cache is still built only at start (on refresh-on, or when missing or empty) or by the precompute job. The build added no background mechanism. Plan.md row 2d and the issue 23 comment carry the details that matter to 22/23.
- [x] `docs/project/issues/26-zero-downtime-deploy.md` - out of scope: It mentions the random cache only in its dependency on issue 23. That dependency still stands, because the refresh-on startup rebuild still blocks.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - out of scope: It shows the random layer drawing from the "random cache" node and says nothing about how or when the cache is built. The serving-time reads are unchanged (R3).
- [x] `DEPLOYMENT.md` - out of scope: Line 64 only lists `engine/server/db/random-cache.db` as an expected file, which is still true. Production keeps refresh on and still rebuilds on every start.

## Implementation plan

## Draft implementation: concurrent Engine starts on `random-cache.db` (issue 32)

I checked the draft against the plan and R1–R5 once, and it met all of them on the first pass. Nothing is left for the operator to accept beyond the three tradeoffs the plan already names. I read the current code in `random_cache.py`, `server.py:300-359`, `tests/active/conftest.py:1-160` and the import pattern in `test_random_videos.py:18-33`, and I checked which tests already import from `conftest`.

### Module map

| File | Change | Requirement |
|---|---|---|
| `engine/server/data/random_cache.py` | New constant `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS`, `timeout=` in `connect_random_cache_db`, new private `_random_rowids_table_exists`, new last parameter `reuse_non_empty` and reuse branch in `populate_random_cache` | R1, R2 |
| `engine/server/api/server.py` | `reuse_non_empty=True` added to the one `populate_random_cache` call (line 342) | R1 |
| `tests/active/conftest.py` | Flock comment rewritten (lines 113-115) and nothing else | R4 |
| `tests/active/test_random_cache.py` | New module: tests (a), (b), (c) and the multi-Engine test | R5 |
| `engine/server/db/jobs/precompute-random-rowids.py` | Nothing. It never passes the keyword and still calls positionally | R3 |
| `random_videos.py`, handlers, recommendations, `server_config.py` | Nothing | R3 |

### What the tests have to prove

- **(a) No write on reuse.** The reuse path must not write. Proof: the call succeeds on a `timeout=0` connection while another connection holds RESERVED, the rows are unchanged, and the connection is not in a transaction afterwards. A control call without the keyword on its own connection must fail on the same lock, which proves the lock is real.
- **(b) Wait, don't crash.** A refresh-on rebuild through `connect_random_cache_db` must wait out a held lock and then produce a full build. Checks: `PRAGMA busy_timeout > 5000`, a `timeout=0` probe DELETE fails while the lock is held (proving the lock is armed), and the elapsed time is at least the hold time.
- **(c) Missing or empty cache is built.** With refresh off and the keyword set, a cache file with no table and a cache with an empty table are both built in full.
- **Multi-Engine.** 8 refresh-off Engines started at once, without the flock, all reach `/api/health` 200.

### `engine/server/data/random_cache.py`

The file's style stays as it is: one-line `"""Handle ..."""` docstrings and no inline comments, except the single `#` line the impact entry allows above the constant.

```python
"""Provide random cache runtime helpers."""

from __future__ import annotations

import logging
import random
import sqlite3
from pathlib import Path

# Long enough to wait out a concurrent full filtered rebuild of the real dataset; not measured, chosen generously.
RANDOM_CACHE_BUSY_TIMEOUT_SECONDS = 3600


def connect_random_cache_db(path: Path) -> sqlite3.Connection:
    """Handle connect random cache db."""
    conn = sqlite3.connect(path.as_posix(), timeout=RANDOM_CACHE_BUSY_TIMEOUT_SECONDS, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_random_cache_schema(conn: sqlite3.Connection) -> None:
    ...  # unchanged


def _random_rowids_table_exists(conn: sqlite3.Connection) -> bool:
    """Handle random rowids table exists."""
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'random_rowids' LIMIT 1").fetchone()
    return row is not None


def populate_random_cache(
    src_db: sqlite3.Connection,
    cache_db: sqlite3.Connection,
    size: int,
    refresh: bool = False,
    filtered_mode: bool = False,
    max_per_instance: int = 0,
    max_per_author: int = 0,
    reuse_non_empty: bool = False,
) -> int:
    """Handle populate random cache."""
    if size <= 0:
        return 0
    if not refresh and reuse_non_empty and _random_rowids_table_exists(cache_db):
        existing = cache_db.execute("SELECT COUNT(*) FROM random_rowids").fetchone()
        if existing and int(existing[0]) > 0:
            return int(existing[0])
    ensure_random_cache_schema(cache_db)
    existing = cache_db.execute("SELECT COUNT(*) FROM random_rowids").fetchone()
    if not refresh and existing and int(existing[0]) >= size:
        return int(existing[0])
    cache_db.execute("DELETE FROM random_rowids")
    ...  # lines 47-166 unchanged
```

**Rules the new code must keep:**
- **Guard order.** `size <= 0 → 0` stays first. The reuse branch sits above `ensure_random_cache_schema`, so the reuse path sends no DDL, DELETE, INSERT or commit (R1).
- **Parameter position.** `reuse_non_empty` is the last parameter, not keyword-only, which matches the file (no `*,` anywhere in it). Both existing positional callers keep binding their seven arguments exactly as today. With the default `False`, lines 42-45 run exactly as they do now, so precompute is unchanged (R3).
- **No lingering read lock.** Both reuse-path SELECTs return a single row and are read with `fetchone()` on a throwaway cursor, the same as line 43. CPython steps the statement to DONE after a one-row fetch and resets it, and the cursor is dropped straight away. So the Engine's long-lived connection keeps no SHARED lock afterwards. Under legacy isolation a bare SELECT opens no transaction, so `cache_db.in_transaction` stays False. Test (a) asserts this.
- **Works with any row factory.** `existing[0]` and `row is not None` work for both `sqlite3.Row` and plain tuples, which matters for the `timeout=0` connection in test (a).
- **Fall-through.** A missing table, or one with count 0, falls through to the existing path unchanged: schema, count (0 < size), DELETE, build, commit. `fetch_random_rowids` can still rely on the table existing, because the reuse path only returns when the table exists.
- **`timeout=` covers every caller.** It is set on the connection, so it applies to all three callers: Engine start and serving reads, the precompute job, and test (b). `fetch_random_rowids` and `random_videos.py` are not edited (R3).

### `engine/server/api/server.py`

The call at lines 342-350 gains one argument. The positional arguments stay and the return value is still ignored:

```python
    populate_random_cache(
        db,
        random_cache_db,
        DEFAULT_RANDOM_CACHE_SIZE,
        random_cache_refresh,
        DEFAULT_RANDOM_CACHE_FILTERED_MODE,
        DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE,
        DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR,
        reuse_non_empty=True,
    )
```

**Left out on purpose:** rewording the `--help` text (lines 150, 179) and logging the returned count. Both are optional in the inventory, and "disable refresh" is still accurate. The docs checklist carries the new meaning. Adding a `logging.info("random cache rows=%d", ...)` line is the cheap upgrade if a stale cache ever needs diagnosing.

### `tests/active/conftest.py`

Only lines 113-115 change. One sentence goes on each line, matching the one-comment-one-line rule while keeping the block shape of the existing comment:

```python
        # A start rewrites random-cache.db only with refresh on or when the cache is missing or empty; this start passes --no-random-cache-refresh, so it normally only reads it.
        # The Engine itself waits on another writer's lock; serialising starts across lanes, up to healthy, stays as a second guard for starts that do write.
        # A start that still exits is retried.
```

The command, `ENGINE_START_ATTEMPTS`, the `1 + attempt` backoff and the flock are unchanged.

### `tests/active/test_random_cache.py` (new)

```python
"""Engine starts share random-cache.db without crashing each other.

- With refresh off and `reuse_non_empty`, `populate_random_cache` keeps a non-empty cache holding fewer rows than `size`: it returns that count and writes nothing, so it succeeds while another connection holds the write lock, and the rows are unchanged; without the keyword the same call fails on that lock.
- A refresh-on rebuild through `connect_random_cache_db` waits out a write lock another connection holds briefly, then builds every source row; the connection's busy wait is longer than sqlite's 5 s default.
- With refresh off and `reuse_non_empty`, a cache with no table and a cache with an empty table are both built.
- Eight Engines started at once against this checkout with `--no-random-cache-refresh`, and no start lock, all become healthy.

The unit tests use a tiny source database and cache files under tmp_path; only the multi-Engine test touches the checkout, through the Engine's own start path, after the session Engine has ensured its cache is populated.
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, _free_port  # noqa: E402
from data.random_cache import connect_random_cache_db, ensure_random_cache_schema, populate_random_cache  # noqa: E402

SOURCE_ROWS = 20
SIZE = 100
# The Engine's filtered path with caps that admit every source row, so a full build holds rowids 1..SOURCE_ROWS.
FILTERED, MAX_PER_INSTANCE, MAX_PER_AUTHOR = True, 0, 100
HOLD_SECONDS = 1.5
# Test (b)'s own ceiling, set after checking the configured wait, so a broken release fails in 30 s instead of hanging for an hour.
TEST_BUSY_TIMEOUT_MS = 30000
ENGINE_COUNT = 8
HEALTH_DEADLINE_SECONDS = 120


def _source_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL);"
        "CREATE TABLE videos (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, channel_id TEXT);"
    )
    videos = [(f"v{i}", "a.example" if i % 2 else "b.example", f"c{i % 4}") for i in range(1, SOURCE_ROWS + 1)]
    conn.executemany("INSERT INTO video_embeddings (video_id, instance_domain) VALUES (?, ?)", [v[:2] for v in videos])
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id) VALUES (?, ?, ?)", videos)
    conn.commit()
    return conn


def _seed_cache(path: Path, rowids: list[int]) -> None:
    conn = sqlite3.connect(path)
    ensure_random_cache_schema(conn)
    conn.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", list(enumerate(rowids, start=1)))
    conn.commit()
    conn.close()


def _rows(path: Path) -> list[tuple[int, int]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    finally:
        conn.close()


def _assert_full_build(path: Path) -> None:
    rows = _rows(path)
    assert [position for position, _ in rows] == list(range(1, SOURCE_ROWS + 1))
    assert {rowid for _, rowid in rows} == set(range(1, SOURCE_ROWS + 1))


def _hold_write_lock(path: Path) -> sqlite3.Connection:
    """Take RESERVED on the file and write nothing, so readers are still admitted; releasable from any thread."""
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    return holder


def _release(holder: sqlite3.Connection) -> None:
    with contextlib.suppress(sqlite3.ProgrammingError):
        holder.rollback()
        holder.close()


def _assert_locked_for_writes(path: Path, call) -> None:
    """Run `call` on its own timeout=0 connection, expect it to fail on the lock, and discard the connection."""
    conn = sqlite3.connect(path, timeout=0)
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            call(conn)
    finally:
        conn.rollback()
        conn.close()


def test_refresh_off_reuses_a_short_cache_without_writing(tmp_path):
    source = _source_db(tmp_path)
    cache_path = tmp_path / "random-cache.db"
    _seed_cache(cache_path, [3, 1, 2])
    before = _rows(cache_path)
    holder = _hold_write_lock(cache_path)
    try:
        _assert_locked_for_writes(cache_path, lambda conn: populate_random_cache(source, conn, SIZE, False, FILTERED, MAX_PER_INSTANCE, MAX_PER_AUTHOR))
        cache = sqlite3.connect(cache_path, timeout=0)
        try:
            count = populate_random_cache(source, cache, SIZE, False, FILTERED, MAX_PER_INSTANCE, MAX_PER_AUTHOR, reuse_non_empty=True)
            assert not cache.in_transaction
        finally:
            cache.close()
    finally:
        _release(holder)
    assert count == 3
    assert _rows(cache_path) == before


def test_rebuild_waits_for_a_briefly_held_write_lock(tmp_path):
    source = _source_db(tmp_path)
    cache_path = tmp_path / "random-cache.db"
    _seed_cache(cache_path, [1])
    cache = connect_random_cache_db(cache_path)
    try:
        assert cache.execute("PRAGMA busy_timeout").fetchone()[0] > 5000
        cache.execute(f"PRAGMA busy_timeout = {TEST_BUSY_TIMEOUT_MS}")
        holder = _hold_write_lock(cache_path)
        timer = threading.Timer(HOLD_SECONDS, _release, (holder,))
        try:
            _assert_locked_for_writes(cache_path, lambda conn: conn.execute("DELETE FROM random_rowids"))
            started = time.monotonic()
            timer.start()
            count = populate_random_cache(source, cache, SIZE, True, FILTERED, MAX_PER_INSTANCE, MAX_PER_AUTHOR)
            elapsed = time.monotonic() - started
        finally:
            timer.cancel()
            if timer.is_alive():
                timer.join()
            _release(holder)
    finally:
        cache.close()
    assert elapsed >= HOLD_SECONDS
    assert count == SOURCE_ROWS
    _assert_full_build(cache_path)


@pytest.mark.parametrize("seed", ["missing table", "empty table"])
def test_refresh_off_builds_a_missing_or_empty_cache(tmp_path, seed):
    source = _source_db(tmp_path)
    cache_path = tmp_path / "random-cache.db"
    if seed == "empty table":
        _seed_cache(cache_path, [])
    cache = connect_random_cache_db(cache_path)
    try:
        count = populate_random_cache(source, cache, SIZE, False, FILTERED, MAX_PER_INSTANCE, MAX_PER_AUTHOR, reuse_non_empty=True)
    finally:
        cache.close()
    assert count == SOURCE_ROWS
    _assert_full_build(cache_path)


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as resp:
            return resp.status == 200
    except OSError:
        return False


@pytest.mark.usefixtures("engine")
def test_engines_starting_at_once_all_become_healthy(tmp_path):
    # Mirrors the engine fixture's env and command line (conftest.py:110, 121-122); keep the two in step.
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
    engines: list[tuple[subprocess.Popen, int, Path]] = []
    logs = []
    try:
        for index in range(ENGINE_COUNT):
            port = _free_port()
            log_path = tmp_path / f"engine-{index}.log"
            log = open(log_path, "w")
            logs.append(log)
            proc = subprocess.Popen(
                [str(ENGINE_PY), str(ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"],
                env=env, stdout=log, stderr=log,
            )
            engines.append((proc, port, log_path))
        pending = list(engines)
        deadline = time.time() + HEALTH_DEADLINE_SECONDS
        while pending and time.time() < deadline:
            for entry in list(pending):
                proc, port, log_path = entry
                assert proc.poll() is None, f"Engine on port {port} exited {proc.returncode}:\n{log_path.read_text()[-2000:]}"
                if _healthy(port):
                    pending.remove(entry)
            time.sleep(0.25)
        assert not pending, f"{len(pending)} of {ENGINE_COUNT} Engines not healthy within {HEALTH_DEADLINE_SECONDS}s; see {[str(p) for _, _, p in pending]}"
    finally:
        for proc, _, _ in engines:
            if proc.poll() is None:
                proc.terminate()
        for proc, _, _ in engines:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for log in logs:
            log.close()
```

**Decisions behind the tests:**
- **Imports.** The module uses the `test_random_videos.py` sys.path pattern and imports from `conftest` the way `test_similar.py:60` does. `random_cache.py` imports only the stdlib, so the unit tests run in the pytest interpreter with no `ENGINE_PY` child process.
- **Source DB.** It uses `row_factory = sqlite3.Row`, because the build path indexes columns by name. The filtered path with caps (0, 100) is the Engine's own path, and those caps admit all 20 rows, so a full build is exactly rowids 1..20 at positions 1..20. The start rowid and shuffle are random, so the tests compare sets for rowids and the exact sequence only for positions.
- **The lock holder.** It uses `isolation_level=None` so its `BEGIN IMMEDIATE` is explicit, takes RESERVED only, and never writes, so no cache spill can take EXCLUSIVE. It uses `check_same_thread=False` so the timer thread can release it; this is the hang risk the inventory names. `_release` is idempotent, so the `finally` blocks are safe whether or not the timer already ran.
- **Control connections.** They go through `_assert_locked_for_writes` on their own `timeout=0` connection, which is always rolled back and closed. Neither the keyword call nor the row comparison ever uses a connection left in a transaction by the implicit BEGIN before the failed DELETE.
- **Test (b)'s wait.** The test asserts the configured wait is above 5000 ms before it lowers it to 30 s for its own run. That lowering is a deliberate simplification. It guards against an hour-long hang if the release ever breaks, and it does not weaken what is proven: the wait itself is sqlite's handler on the connection `connect_random_cache_db` returned, and the constant's size is covered by the first assertion. The elapsed time is measured from before `timer.start()`, so `elapsed >= HOLD_SECONDS` holds only if the rebuild really waited.
- **Multi-Engine test.** It depends on the session `engine` fixture, so the checkout's cache has already been through one start and is non-empty. It never takes `ENGINE_START_LOCK` and never opens `random-cache.db` itself. Each Engine gets its own log file, and failure messages show the log tail. Teardown terminates everything first, then waits and falls back to `kill()`. The env and command line are duplicated from the fixture: lifting them into a shared helper would be a code edit beyond R4's comment-only scope, so drift is guarded only by the comment.

### Accepted limits carried into the build

- **Port collisions.** A collision between `_free_port()` and Popen fails the multi-Engine test with no retry. The failure message shows the log tail, so an "Address already in use" failure is easy to tell apart from "database is locked".
- **Other shared DBs.** The multi-Engine test also exercises startup DDL on the shared `whitelist.db` and `similarity-cache.db` with their 5 s wait. A lock failure there is outside this plan (see the `db.py` impact entry).
- **Unmapped test group.** Until `config.json` maps `test_random_cache.py` at harvest, it runs as an unmapped group on every suite run, 8-Engine test included.
- **Unmeasured ceiling.** The 3600 s value is unmeasured, and the busy wait does not react to SIGTERM (plan and inventory risks, unchanged).

### Check against plan and requirements

| Requirement | How the draft meets it |
|---|---|
| R1 | The reuse branch is above the schema DDL. It returns on count > 0 with no write, and missing or empty tables fall through to the build. Only `server.py` sets the keyword. |
| R2 | `timeout=RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` (3600) on every random-cache connection. The build body and its lock span are unchanged. |
| R3 | The keyword defaults to False and is placed last, so precompute is untouched. Refresh on skips the reuse branch. The build body, `fetch_random_rowids` and `random_videos.py` are untouched. |
| R4 | Comment only. The command, retries, backoff and flock are unchanged. |
| R5 | Tests (a), (b) and (c) run on tmp files. The multi-Engine test runs 8 Engines through the checkout's start path. |

The draft converged on pass 1.

### Phases

#### Phase 1 - Random-cache busy wait [code]

**Files touched.** engine/server/data/random_cache.py (EDITED), tests/active/test_random_cache.py (NEW)

**Checkpoint.** Seam: the `data.random_cache` module functions, called directly in the pytest interpreter against tmp_path sqlite files. The test uses the sys.path import pattern of `tests/active/test_random_videos.py:18-33`, with no Engine child process, because `random_cache.py` imports only the stdlib. Test (b), `test_rebuild_waits_for_a_briefly_held_write_lock` in `tests/active/test_random_cache.py`: on a connection from `connect_random_cache_db`, it asserts `PRAGMA busy_timeout` > 5000. It then lowers that connection's wait to 30 s, which is the test's own hang guard. A second connection with `isolation_level=None` holds `BEGIN IMMEDIATE`, and a `timeout=0` probe DELETE fails with "locked" to prove the lock is armed. A `threading.Timer` releases the lock after 1.5 s. The test asserts that a refresh-on `populate_random_cache(source, cache, 100, True, True, 0, 100)` returns 20, that elapsed >= 1.5 s, and that the cache holds positions 1..20 over the rowid set {1..20}.

**Intent.** Every connection returned by `connect_random_cache_db` in `engine/server/data/random_cache.py` waits on another writer's lock for longer than sqlite's 5 s default, taken from the named constant `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS`, so a refresh-on rebuild through it waits out a held write lock and completes instead of raising "database is locked".

- C1 - A connection returned by `connect_random_cache_db` has a busy wait longer than sqlite's 5 s default.
- C2 - A refresh-on `populate_random_cache` through that connection waits out a write lock held by another connection and then completes a full build.

**Outcome.** ### `engine/server/data/random_cache.py`

- **New constant.** Added the module constant `RANDOM_CACHE_BUSY_TIMEOUT_SECONDS = 3600` above `connect_random_cache_db`. The value is the one from the plan's draft.
- **`rat-tail:` comment.** One comment line above the constant says why the value is so long and marks it as a deliberate simplification. It was not measured; it is a generous ceiling meant to outlast another process's full filtered rebuild. A rebuild longer than that still fails with "database is locked". The fix for that is to measure a real rebuild, or to use the non-blocking rebuild from issues 22/23.
- **`connect_random_cache_db`.** It now opens with `sqlite3.connect(path.as_posix(), timeout=RANDOM_CACHE_BUSY_TIMEOUT_SECONDS, check_same_thread=False)`. Every random-cache connection therefore gets a 3600 s busy wait (`PRAGMA busy_timeout` 3600000) instead of sqlite's 5 s default. That includes the Engine's start and serving connection, the precompute job, and the tests.
- **Unchanged.** The signature, `row_factory` and everything else in the module are as before.

I did not run the checkpoint myself. My expectation that it goes green comes from the test author's recorded probe (`tests/tmp/probe_32_long_wait.py`), not from a run of mine. That probe showed a `timeout=3600` connection reporting `PRAGMA busy_timeout 3600000`, and a rebuild behind the same 6 s lock returning `built=20 elapsed=6.03` with positions 1..20 over rowids 1..20.

**Beyond the files named.** none. The phase's files list names `tests/active/test_random_cache.py (NEW)`. I did not create it, because the checkpoint covers both clauses and lives in `tests/tmp/`. I assume the workflow moves it to `tests/active` later. Separately, the test author left two probe files, `tests/tmp/probe_32_lock.py` and `tests/tmp/probe_32_long_wait.py`, and said they should be removed. I did not touch them because they are outside this phase's files.

#### Phase 2 - Reuse a non-empty cache without writing [code]

**Files touched.** engine/server/data/random_cache.py (EDITED), tests/active/test_random_cache.py (EDITED)

**Checkpoint.** Seam: the same one as Phase 1, `populate_random_cache` called directly on tmp_path files in `tests/active/test_random_cache.py`. Test (a), `test_refresh_off_reuses_a_short_cache_without_writing`: it seeds a 3-row cache (size=100) and holds `BEGIN IMMEDIATE` on a second connection. As a control, the call without `reuse_non_empty` on its own `timeout=0` connection raises OperationalError "locked". It then asserts that the call with refresh off and `reuse_non_empty=True` on a `timeout=0` connection returns 3, that `cache.in_transaction` is False, and that the rows are identical to before. Test (c), `test_refresh_off_builds_a_missing_or_empty_cache`, is parametrized over a missing table and an empty table. Each case, with refresh off and the keyword set, returns 20 and leaves positions 1..20 over the rowid set {1..20}.

**Intent.** With refresh off and the new last parameter `reuse_non_empty=True`, `populate_random_cache` in `engine/server/data/random_cache.py` returns the row count of an existing non-empty `random_rowids` table without sending any write to the cache, and still builds the cache when that table is missing or empty.

- C1 - With refresh off and `reuse_non_empty=True`, a non-empty cache holding fewer rows than `size` is returned by count with no write to the cache file.
- C2 - With refresh off and `reuse_non_empty=True`, a cache whose `random_rowids` table is missing or empty is built from the source database.

**Outcome.** ### engine/server/data/random_cache.py
- New private helper `_random_rowids_table_exists(conn)`. It runs `SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'random_rowids' LIMIT 1` and reads the result with `fetchone()`, the same idiom as `engine/server/data/videos.py`.
- `populate_random_cache` has a new last parameter, `reuse_non_empty: bool = False`. It goes after `max_per_author`, so the seven-argument positional calls in `server.py` and `precompute-random-rowids.py` still bind as before. With the default, the function behaves exactly as it did.
- New reuse branch, placed after the `size <= 0` guard and before `ensure_random_cache_schema`. When `not refresh and reuse_non_empty` and the table exists, the function counts the rows with `fetchone()`. If there is at least one row, it returns that count. On this path it sends no DDL, DELETE, INSERT or commit, and only runs two SELECTs, so the connection is not left in a transaction.
- If the table is missing or empty, the function falls through to the existing path unchanged: schema, `>= size` check, DELETE, build, commit. The build body is not touched.
- Two comments above the branch:
  - Why the check runs before the schema call: this way the reuse path never sends the DDL, whose locking varies between sqlite versions.
  - A `rat-tail:` comment for R1's deliberate simplification. The ceiling is that any non-empty cache is reused, so a short or stale one is kept until a refresh. The upgrade path is to record the build's parameters in the cache file and compare them here.

### tests/active/test_random_cache.py
Not touched. The file is named in this phase's files list but does not exist in the tree. The gating checkpoint is `tests/tmp/test_32_concurrent_engine_start_random_cache_phase2.py`, and it covers the phase.

I did not run the checkpoint. The workflow's run is the one that counts.

#### Phase 3 - Engine start opts into reuse [code]

**Files touched.** engine/server/api/server.py (EDITED), tests/active/test_random_cache.py (EDITED), tests/active/conftest.py (EDITED)

**Checkpoint.** Seam: the Engine process at its HTTP boundary, started the way the session `engine` fixture in `tests/active/conftest.py:105-145` starts it. The test uses the same env (conftest.py:110) and the same command line with `--no-random-cache-refresh` (conftest.py:121-122) on ports from `_free_port()`, and depends on `engine` so the checkout's cache is already non-empty. `test_engines_starting_at_once_all_become_healthy` launches 8 Engines at once without taking `ENGINE_START_LOCK`. It asserts that none exits (the failure shows the log tail) and that every one answers `/api/health` 200 within 120 s. Teardown terminates all 8.

**Intent.** The Engine start in `engine/server/api/server.py` calls `populate_random_cache` with `reuse_non_empty=True`, so Engines started at once against the checkout with refresh off no longer crash on `random-cache.db` and all become healthy without the harness's start lock.

- C1 - Eight Engines started at once against the checkout with `--no-random-cache-refresh`, and no start lock, all answer `/api/health` 200 within 120 s.

**Outcome.** ### engine/server/api/server.py
- In `main()`, the Engine start's one `populate_random_cache` call (lines 342-351) now also passes `reuse_non_empty=True` after its seven positional arguments. Nothing else changed: the positional arguments are the same and the return value is still ignored.
- Effect: a start with refresh off (`--no-random-cache-refresh`, or `--dev` with no refresh flag) reuses a non-empty `random_rowids` table and only reads it. It sends no DDL, DELETE or INSERT, so it no longer waits on another connection's write lock on `random-cache.db`.
- Starts with refresh on, and starts that find the cache missing or empty, still rebuild as before.
- `precompute-random-rowids.py` does not pass the keyword and is unchanged.

### tests/active/conftest.py
- Only the three comment lines above the `ENGINE_START_LOCK` flock in the `engine` fixture changed (R4). The old comment said every Engine start rewrites `random-cache.db`. The new one says:
  - a start rewrites the cache only with refresh on or when the cache is missing or empty;
  - this fixture's `--no-random-cache-refresh` start only reads a populated cache;
  - the Engine now waits on another writer's lock itself, and the cross-lane flock stays as a second guard for starts that do write.
- The command line, `ENGINE_START_ATTEMPTS`, the backoff and the flock itself are unchanged.

### tests/active/test_random_cache.py
- Not touched. The phase's files list names this file, but it does not exist in the tree; phases 1 and 2 did not create it either. The gating checkpoint is `tests/tmp/test_32_concurrent_engine_start_random_cache_phase3.py`, and it covers this phase. Moving the checkpoints into `tests/active` is left to harvest.

I did not run the checkpoint; the workflow's run is the one that counts. Nothing in this turn observed the green side, so it is still a prediction. It rests on two earlier observations: phase 2's checkpoint showed the `reuse_non_empty=True` path returning without a write under a held `BEGIN IMMEDIATE`, and the phase-3 probe measured the checkout cache at 486662 rows (non-empty, and short of 500000).


