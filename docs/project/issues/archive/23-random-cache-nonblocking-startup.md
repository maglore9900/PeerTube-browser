# Random cache refresh without startup downtime

Status: enhancement, complete
Origin: task 39, [M7][F4]

## Problem

Rebuilding the random cache during startup delays readiness and creates a visible unavailable window after restart.

## Proposed solution

Serve from the existing cache immediately and rebuild in a background worker with an atomic swap.

- Non-blocking startup: open the existing `random-cache.db` and start listening first; if the cache is missing/invalid, use a safe DB fallback until the first successful build.
- Background worker rebuilds into `random-cache.tmp.db`; atomic swap and reopen under `random_cache_lock`.
- Backoff/retry for failed refreshes; never block the request path.
- Logs: build duration, scanned rows, final size, short-fill reasons, swap result.
- Config: refresh interval (minutes), startup refresh mode (`off`/`async`), optional max build runtime.

## Validation (from the original task)

- `/api/health` responds before the cache rebuild completes.
- Concurrent reads during a swap show no request failures.

## Related

- Builds on `22-random-cache-background-refresh`; required before `26-zero-downtime-deploy`.

## Comments

**From issue 32** (`docs/project/issues/archive/32-concurrent-engine-start-random-cache-lock.md` has the full detail). A start with refresh off sends no write to `random-cache.db`. It reuses any non-empty `random_rowids` table as it is (`populate_random_cache(..., reuse_non_empty=True)`), and builds only when that table is missing or empty. `connect_random_cache_db` opens every cache connection with `timeout=RANDOM_CACHE_BUSY_TIMEOUT_SECONDS` (3600 s), so a writer waits for another writer's lock instead of failing after 5 s.

What remains of the startup-downtime problem:

- A start with refresh on, which is the production default, still rebuilds the cache before it listens.
- A start that meets another writer's lock waits up to 3600 s. The wait runs inside sqlite, so during it the Engine is not healthy and does not act on SIGTERM.
- The serving connection has the same wait, so a serving-time random read that meets another process's write lock can block for up to 3600 s while holding `random_cache_lock`.

### Delivered

Delivered together with `22-random-cache-background-refresh` by `docs/project/plans/19-22-random-cache-background-refresh.md`, commit `<pending>`.

- **Startup.** `engine/server/api/server.py` opens the cache with `open_random_cache_if_usable`, which returns a read-only handle only when `random_rowids` exists and holds rows. The Engine then listens without building. Any startup build runs in the background worker `run_random_cache_worker` (see issue 22): always under refresh on, and under refresh off only when no usable cache was opened.
- **Fallback.** Until a build swaps in, a missing, empty or unusable cache is served through the existing DB fallback, so `/api/health` and the random feed answer before any build finishes.
- **No startup write, no long wait.** No start writes `random-cache.db`, and the serving handle is a plain `mode=ro` connection on a file that is never written in place, so the startup and serving-time waits the issue-32 comment lists no longer arise.
- **Startup mode.** There is no separate `off`/`async` setting. The existing `--random-cache-refresh` / `--no-random-cache-refresh` flags (and `DEFAULT_RANDOM_CACHE_REFRESH`) decide whether the background startup build runs, and they do not affect the periodic build.
- **Simplifications.** No backoff schedule: a failed build is retried at the next interval tick, and with interval 0 a failed startup build is not retried until the next restart. No maximum build runtime. Upgrade path: capped backoff in the worker loop if failures prove common.
- **Behaviour.** For the cache settings see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`. For operating it see `DEPLOYMENT.md`.
