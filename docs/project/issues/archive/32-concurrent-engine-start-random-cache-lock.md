# Concurrent Engine starts exit on a locked random-cache.db

Status: bug, ready-for-agent
Origin: step 8 of the `12-trusted-proxy-client-address` build, where it turned `tests/active/test_dislikes.py` red with no code at fault

## Problem

Engines that start at the same time against one checkout race to write `random-cache.db`, and those that lose the race exit 1 instead of waiting. `populate_random_cache` reaches `cache_db.execute("DELETE FROM random_rowids")` (`engine/server/data/random_cache.py:46`) even under `--no-random-cache-refresh`, and `connect_random_cache_db` opens the file with sqlite's default 5 s busy timeout, so a start that meets another start's write transaction dies with `sqlite3.OperationalError: database is locked`.

The active suite starts one Engine per lane through the session `engine` fixture (`tests/active/conftest.py:101-137`). That fixture retries a start 5 times with a `1 + attempt` second backoff. The lanes retry in near lockstep, so a lane can lose every attempt. Its whole group then errors at setup, and the error reads like a regression in whatever build is running.

## Observed

- A probe in `tests/tmp` started 1 Engine: healthy.
- It then started 8 Engines at once with the fixture's command line: 3 healthy, 5 exited 1, each with the traceback above ending at `random_cache.py:46`.
- In the `12-trusted-proxy-client-address` suite run, 10 groups were reselected and `test_dislikes.py` errored 10/10 at `conftest.py:131` ("Engine exited on every start"). The Engine-backed lanes `test_similar.py`, `test_dislike_profile.py` and `test_server.py` in the same run came up normally. That build changed no Engine startup code.

## Candidate fixes (not chosen)

- Engine: pass a longer `timeout=` to `sqlite3.connect` in `connect_random_cache_db`, so a concurrent start waits for the lock. Also find out why the DELETE branch runs on every start under `--no-random-cache-refresh`, which suggests the cache never reaches `DEFAULT_RANDOM_CACHE_SIZE` on this dataset.
- Harness: more attempts and jittered backoff in the `engine` fixture, or start Engines one at a time across lanes.

## Related

- `22-random-cache-background-refresh` and `23-random-cache-nonblocking-startup` rework how the cache is built at startup and may make this go away. This issue is narrower: a concurrent start should not crash.

## Comments

### Triage

**Established:**

- **The harness half is already done.** After this issue was filed, the active suite's `engine` fixture started serialising Engine starts across lanes with a shared `flock` on `<tmp>/peertube-browser-engine-start.lock`, and it keeps the retry. The Engine half is unchanged, so a concurrent start outside that harness still exits. That covers a second harness, a manual start, or a test Engine starting beside a live one.
- **Why the DELETE runs under `--no-random-cache-refresh` (the open question above):** the stored `random-cache.db` holds 486,662 rows against `DEFAULT_RANDOM_CACHE_SIZE = 500000`. The filtered fill (`MAX_PER_AUTHOR = 100`) cannot reach the target on this dataset, and the reuse check only accepts a cache at or above the target size. So every start rewrites the cache.
- **Why the second start hits the lock:** the DELETE opens the write transaction, which stays open through the whole filtered scan of `whitelist.db` (up to about 890k rows) until the final commit. The cache DB is in rollback-journal mode, and the connection uses sqlite's default 5 s busy timeout.
- **Verification:** reproduced from the code and the measured cache size. The issue's 8-Engine probe was not re-run at triage.
- **Scope, as the maintainer chose it:** all three fixes below. 22+23 (background refresh with an atomic swap) remain the long-term rework and are not a prerequisite.
- **Ordering:** plan 17 (stable ANN ids) rewrites the same module to store `ann_id` instead of rowids. Whichever lands second rebases. Nothing in this fix depends on the id type.

## Agent Brief

**Category:** bug
**Summary:** Engines starting at the same time must not exit on a locked random cache. A start that does not ask for a refresh must not rewrite a valid cache.

**Current behavior:**
At startup the Engine populates the random cache (`populate_random_cache`). It reuses a stored cache only when the cache holds at least the configured size. The filtered fill (per-author cap) comes up short of that size on the real dataset, so every start deletes and refills the cache, even with `--no-random-cache-refresh`. The refill holds the cache DB's write transaction from its first DELETE through the whole scan of the source DB. A second Engine starting meanwhile waits the default 5 s, then exits 1 with `sqlite3.OperationalError: database is locked`.

**Desired behavior:**
- **Reuse:** a stored cache counts as valid when it was built for the current size target and filter settings (filtered mode, per-instance cap, per-author cap), even if the fill came up short. A no-refresh start that finds a valid cache writes nothing to the cache DB. A cache built under different settings, or with no record of its settings (including today's file), is rebuilt once.
- **Short write:** a rebuild computes its full candidate list before writing. It then replaces the cache contents and records the settings in one short write transaction. No write transaction is open while the source DB is scanned.
- **Wait, don't exit:** the cache connection waits on a busy lock long enough to outlast another start's write, so a colliding start waits instead of exiting.

**Key interfaces:**
- `populate_random_cache(src_db, cache_db, size, refresh, filtered_mode, max_per_instance, max_per_author) -> int`: same signature and return (entries in the cache). The reuse decision compares stored build settings, not only the row count.
- Cache DB schema: a small record of the settings the stored cache was built with, beside the existing entries table, created by the schema-ensure function.
- `connect_random_cache_db(path)`: a busy timeout well above the default 5 s.
- `fetch_random_rowids` and the random feed: unchanged behavior.

**Acceptance criteria:**
- [ ] With a cache already built for the current settings, a `--no-random-cache-refresh` start leaves the cache DB's contents and settings record unchanged, including when the stored entry count is below the size target.
- [ ] Changing any of size, filtered mode, per-instance cap or per-author cap causes the next start to rebuild, even with `--no-random-cache-refresh`.
- [ ] A cache file with no settings record (today's shape) is rebuilt on the next start and reused on the one after.
- [ ] No write transaction on the cache DB is open while the source DB is being scanned. A reader of the cache DB, or a second connection trying to write, is not blocked for the duration of the scan.
- [ ] 8 Engines started at once against one checkout, once with `--no-random-cache-refresh` and once with refresh on, all reach a healthy `/api/health`, and none exits with `database is locked`.
- [ ] `/api/similar` random mode still returns random-feed rows after a rebuild and after a reuse.

**Out of scope:**
- Background or periodic refresh, and atomic file swap (issues 22 and 23).
- Changing the cache size, the filter caps or their defaults.
- Removing the test harness's start lock or retry in `tests/active/conftest.py`.
- Moving the cache from rowids to `ann_id` (plan 17).
