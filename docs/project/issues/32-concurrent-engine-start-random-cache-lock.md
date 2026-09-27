# Concurrent Engine starts exit on a locked random-cache.db

Status: bug, needs-triage
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
