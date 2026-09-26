# Background refresh of the random cache

Status: enhancement, needs-triage
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
