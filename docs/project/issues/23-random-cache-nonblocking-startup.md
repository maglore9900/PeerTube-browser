# Random cache refresh without startup downtime

Status: enhancement, needs-triage
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
