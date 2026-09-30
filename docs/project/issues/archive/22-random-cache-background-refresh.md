# Background refresh of the random cache

Status: enhancement, complete
Origin: task 16l, [M7][F4]

## Problem

The random cache is rebuilt only on server start and/or on a refresh flag. It needs a background mechanism with safe updates and no read conflicts.

## Proposed solution

A periodic job rebuilds the cache into a separate file and atomically swaps the active cache.

- Config `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` (0 = disabled).
- A background thread/timer in the server rebuilds every N minutes.
- Rebuild into `random-cache.tmp.db`, then atomic rename and safe connection reopen under `random_cache_lock`.
- Logs: build time, size, valid candidates, short-fill reasons.
- SQLite: WAL/read-only connection for reads; replacement only under the lock.

## Related

- First of the runtime-reliability chain: this, `23-random-cache-nonblocking-startup`, `24-similarity-cache-shadow-swap`, `25-similarity-precompute-existing-sources`, `26-zero-downtime-deploy`. One swap/reopen pattern should serve both the random and the similarity caches.

## Comments

### Delivered

Delivered together with `23-random-cache-nonblocking-startup` by `docs/project/plans/19-22-random-cache-background-refresh.md`, commit `<pending>`.

- **Worker.** One daemon thread per Engine, `run_random_cache_worker` in `engine/server/data/random_cache.py`, runs every build one at a time: the startup build if one is needed, then one every `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`. A failed build is retried at the next tick, and shutdown does not wait for a build in progress.
- **Interval.** `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` defaults to 60, or to 0 under `--dev` when unset. An explicit value, 0 included, wins over `--dev`. The refresh flags do not affect it.
- **Temp name.** Each build writes `random-cache.tmp.<pid>.db` beside the active file instead of `random-cache.tmp.db`, so Engines sharing a checkout never write the same temp file.
- **No WAL.** The active file is never written in place, so the serving handle is a plain read-only (`mode=ro`) connection.
- **Swap.** `swap_readonly_connection` in `engine/server/data/db.py` opens the finished temp file read-only and validates it with a check query before the rename. It then swaps the handle in under the lock and closes the old one afterwards. A failed open, check or rename leaves the active file and the serving handle as they were. The helper has nothing random-cache-specific in its interface, so issue 24 can reuse it.
- **Hot journal.** The swapped-in handle keeps the temp name, and a later build in the same process writes to that name. `connect_random_cache_db` therefore sets `PRAGMA journal_mode=MEMORY`, so the build leaves no `-journal` file for the served handle to read as a hot journal.
- **Logs.** Each build logs a `random cache build start` line (target, filtered mode, caps), then `ok` (duration, size, target) or `failed` (duration, reason). The rows scanned and the `filtered fill short` line (target, got, scanned) come from the existing `populate_random_cache` logging.
- **Behaviour.** For the Engine's cache settings see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`. For operating it see `DEPLOYMENT.md`. For the precompute job see `DATA_BUILD.md`.
