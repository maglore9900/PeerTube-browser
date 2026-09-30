# ADR-0008: The updater hands a new similarity cache to running Engines through files on disk

Status: accepted
Date: decided while triaging issue 24 (similarity cache shadow swap), `docs/project/issues/24-similarity-cache-shadow-swap.md`

## Context

Issue 24 moves the similarity precompute out of the updater's stopped-service window: the updater builds a shadow copy of `similarity-cache.db` while the Engine serves, then swaps it in. That needs two messages from the updater to every running Engine: "stop writing to the cache" while the shadow builds, and "reopen the cache" after the swap.

- The Engine writes the cache at serve time (`write_cache` in `data/similarity_cache_manager.py`, through `server.similarity_db`), so rows written to the active file during the build would be lost at the swap.
- SIGUSR1 is already taken by the faulthandler thread dump, and the Engine has no admin endpoint.
- Issue 26 will run two Engines (ports 7070 and 7071) from one checkout, so a message has to reach both.

## Decision

1. **Freeze by marker file.** While a shadow build runs, a build marker file sits next to the active cache and holds the updater's PID. An Engine skips every similarity cache write while a marker exists whose PID is alive; reads continue, and misses are computed live without being stored. A marker whose PID is dead is ignored, and the next updater run removes it at start.
2. **Reopen by inode.** An Engine notices that the active cache path now points to a different inode and reopens it by that path, read-write, under `similarity_db_lock`. If the new file cannot be opened, the Engine keeps its old handle and logs the failure.
3. **The updater gates before the swap, and does not restore after it.** The shadow must pass an integrity check, a schema check, and hold no fewer sources than the active file before `os.replace`; a failure deletes the shadow and leaves the active file. The replaced file is kept as `similarity-cache.prev.db` for a manual one-step restore.

A signal (SIGHUP) was rejected because the updater would need every Engine's PID, and a loopback admin endpoint because it needs bind and auth rules and one call per port. Copying rows written during the build into the shadow, and accepting their loss, were both rejected in favour of the freeze.

## Consequences

- `swap_readonly_connection` in `data/db.py` does not fit here: it installs a read-only handle under the temp file's name. Reopening by the active name read-write avoids both of its cautions.
- Every Engine on the checkout picks up a swap without being addressed, which is what issue 26's blue/green pair needs.
- The reopen check costs a `stat` of the cache path; how often it runs (per access or throttled) is an implementation choice.
- An automatic post-swap rollback is not built. If a swap goes bad, an operator renames `similarity-cache.prev.db` back, and the inode check picks it up.
