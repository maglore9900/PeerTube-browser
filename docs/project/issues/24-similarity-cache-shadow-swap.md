# Similarity cache shadow build and atomic swap without long API downtime

Status: enhancement, ready-for-agent
Origin: task 44, [M7][F4]

## Problem

The updater keeps the API stopped until `precompute-similar-ann.py` finishes. Similarity precompute can be very long, causing unnecessary downtime.

## Proposed solution

Build the similarity cache in a shadow DB while the API runs, then cut over atomically.

- **Updater sequence:** stop/start the service only around write-conflict-critical stages (merge + ANN rebuild); start the API before the similarity precompute.
- **Shadow build:** create `similarity-cache.next.db` from the active `similarity-cache.db` (keeps the cached sources to refresh); run `precompute-similar-ann.py --refresh-existing` against it.
- **Cutover:** `os.replace` onto the active file on success; keep `similarity-cache.prev.db` for one-step restore.
- **Runtime handoff:** reopen the similarity DB in the API under `similarity_db_lock` (signal or admin hook); fallback a short controlled restart.
- **Safety:** a failed shadow build leaves the active cache untouched; a failed swap/reopen restores the previous cache and keeps the service healthy.
- **Logs:** shadow build duration, processed sources, swap duration, reopen result, rollback reason.

## Validation (from the original task)

- API stays available during the precompute window.
- No read errors during swap/reopen.
- A forced swap failure restores the previous cache and keeps `/api/health` green.

## Related

- The old tracker ordered this before `25-similarity-precompute-existing-sources` in the block list but said 25 should land first in its overlap notes, to avoid two rewrites of the precompute stage. Settle at triage.
- Land before `26-zero-downtime-deploy`.

## Comments

### Swap helper from issue 22

The cutover and runtime handoff can use `swap_readonly_connection(temp_path, target_path, lock, owner, attr, check_sql)` in `engine/server/data/db.py`, which the random cache already uses (`refresh_random_cache` in `engine/server/data/random_cache.py`). It opens the finished file read-only, runs `check_sql`, renames the file over the target, swaps the handle into `owner.<attr>` under `lock` and closes the old handle afterwards. A failed open, check or rename leaves the target file and the handle as they were. It keeps no previous file, so `similarity-cache.prev.db` would be a copy the caller makes before the swap.

Two cautions before reusing it here:

- **Hot journal.** The installed handle keeps the temp file's name, so SQLite looks for its journal at `<temp_path>-journal`. If a later build writes a disk rollback journal at that name, every read on the served handle fails. Every build would reuse the fixed name `similarity-cache.next.db`, so the shadow build must use an in-memory journal (as `connect_random_cache_db` does with `PRAGMA journal_mode=MEMORY`) or a temp name that is never reused.
- **Read-only handle.** The helper installs a `mode=ro` handle, but the Engine writes the similarity DB at serve time: `_write_cache` in `engine/server/data/similarity_candidates.py` writes through `server.similarity_db`, which `connect_similarity_db` opens read-write. Either those writes move elsewhere, or the helper needs a way to open the new file read-write.

### Triage

- **Not implemented.** Searched the updater (`updater-worker.py`), `precompute-similar-ann.py`, `api/server.py`, `data/db.py` and `data/similarity_*`: no shadow, `.next` or `.prev` file and no runtime reopen. The updater stops the Engine before the merge and starts it again only after precompute, which runs with `--recreate-out-db`, so the downtime claim holds.
- **Ordering settled:** 25 lands first (`docs/project/issues/plan.md`, "24/25 ordering"). The shadow build runs whichever precompute mode the updater uses once 25 is delivered. Today's `--incremental` means "only sources not yet cached", which on its own would never refresh an existing source.
- **Decisions (maintainer), recorded in ADR-0008 and the glossary (`Shadow build`, `Build marker`):**
  - Serve-time cache writes are **frozen** during the build, not lost or replayed.
  - The updater and Engines communicate through **files on disk, no IPC**: a build marker holding the updater's PID freezes writes, and a change of the active file's inode triggers a reopen.
  - A **pre-swap gate** (integrity, schema, source count not below the active file's) decides the swap. After the swap, an Engine that cannot open the new file keeps its old handle. `.prev.db` is kept for a manual restore, and no automatic post-swap rollback is built.
  - A marker whose PID is dead is ignored; the next updater run removes it at start.
- The reopen does **not** use `swap_readonly_connection`. Opening the active path read-write addresses both cautions in the comment above.

### Issue 25 delivered

The updater's precompute stage runs `precompute-similar-ann.py --refresh-existing`, built by `similarity_precompute_cmd` in `engine/server/db/jobs/updater-worker.py`, so the shadow build wires that mode against `similarity-cache.next.db`. Refresh rewrites only cached sources still in `video_embeddings` and never deletes a source, so the gate's "no fewer `similarity_sources` rows than the active file" check holds for a healthy build.

## Agent Brief

**Category:** enhancement
**Summary:** Let the Engine keep serving while the updater rebuilds the similarity cache in a shadow file, then hand the new file to every running Engine without a restart.

**Current behavior:**
The updater stops the Engine service, merges staging into the main DB, applies the denylist safety prune, recomputes popularity, rebuilds the ANN index, runs the similarity precompute with `--refresh-existing` against the active `similarity-cache.db` (rewriting its cached sources in place), and only then starts the Engine again. The API is down for the whole precompute. At serve time the Engine reads the similarity cache and also writes ANN results for uncached sources into it, through one read-write connection (`server.similarity_db`) guarded by `similarity_db_lock`. Nothing in the Engine notices when the cache file is replaced.

**Desired behavior:**
- **Updater sequence.** The service is stopped only around the stages that need it: merge, prune, popularity and the ANN index rebuild. It is started again before the similarity precompute, so the API serves during the precompute with the new ANN index and the old cache.
- **Stale marker cleanup.** At start, the updater removes a build marker whose PID is not alive.
- **Shadow build.** The updater writes the build marker (its PID) next to the active cache, then takes a consistent copy of the active cache as `similarity-cache.next.db` and runs the precompute against the copy, in the mode the updater's precompute stage uses after issue 25. The shadow build must not leave a disk rollback journal for the served file to trip over. The active file is not written by the build.
- **Freeze.** While a build marker exists and its PID is alive, every Engine skips similarity cache writes. Reads and live ANN computation continue, and misses are served but not stored. A marker whose PID is dead is ignored.
- **Gate and swap.** Before swapping, the updater checks the shadow: `PRAGMA integrity_check` is `ok`, the cache schema is present, and the shadow holds no fewer `similarity_sources` rows than the active file. On a pass, it copies or links the active file to `similarity-cache.prev.db` (replacing an older one), then runs `os.replace` of the shadow onto `similarity-cache.db`. On a failure, it deletes the shadow, leaves the active file untouched, logs the reason and exits non-zero. The marker is removed in every case, success, failure or exception.
- **Reopen.** An Engine detects that the active cache path now refers to a different inode, and reopens it by the active path, read-write, under `similarity_db_lock`. It closes the old handle only after the new one is installed. If the open or a schema check fails, it keeps the old handle, logs, and tries again on a later check. No request sees a read error during the handoff.
- **Logs** (structured, in the existing style of each process): shadow build duration and processed source count, gate result and reason, swap duration, the Engine's reopen result, and any stale marker removed.

**Key interfaces:**
- The updater's precompute stage: gains the marker, copy, gate and swap steps around the existing precompute invocation. Its test-only failure injection flags (`--fail-after-merge-before-similarity` and similar) should gain an equivalent that forces a gate failure.
- The build marker: a file next to the active cache, with a name derived from the cache path and content that is the updater's PID. The name and format are the agent's choice, recorded in the deployment docs.
- The Engine's similarity cache write path (`write_cache` / `_write_cache` under `similarity_db_lock`): returns without writing while a live marker exists.
- The Engine's similarity cache connection (`server.similarity_db`, opened by `connect_similarity_db`): replaced in place on an inode change. `swap_readonly_connection` is not used, because it installs a read-only handle under the temp file's name.
- Glossary: `Shadow build`, `Build marker` in `CONTEXT.md`. Design record: ADR-0008.

**Acceptance criteria:**
- [ ] An updater run with the Engine up keeps `/api/health` and `/api/similar` answering throughout the similarity precompute stage. The service is stopped only across merge through the ANN rebuild.
- [ ] While a marker with a live PID exists, a request for an uncached source returns results and adds no rows to `similarity_sources` or `similarity_items`. With the marker gone, the same request stores its rows.
- [ ] A marker holding a dead PID does not stop writes, and the next updater run deletes it.
- [ ] After a successful build, `similarity-cache.db` holds the shadow's content, `similarity-cache.prev.db` holds the previous content, no `.next.db` or marker remains, and a running Engine serves from the new file without a restart.
- [ ] A forced gate failure (corrupt shadow, or fewer sources than active) leaves `similarity-cache.db` byte-identical, removes the shadow and the marker, logs the reason, exits non-zero, and keeps `/api/health` green.
- [ ] An Engine whose reopen fails (e.g. the file swapped in is not a valid cache) keeps serving from its old handle, logs the failure, and picks up a valid file swapped in later.
- [ ] Concurrent `/api/similar` requests during a swap produce no errors.
- [ ] Tests write only temporary copies of the similarity cache, never the shared `similarity-cache.db`.

**Out of scope:**
- The precompute mode itself: issue 25 owns which sources are recomputed.
- An automatic rollback after the swap. `.prev.db` restore stays manual.
- Blue/green deploy and nginx switching (issue 26), although the file-based handoff is chosen so both of its Engines pick up a swap.
- The random cache's own swap mechanism (issue 22), and any change to `swap_readonly_connection`.
- Running the real cutover against the shared `similarity-cache.db`. Per `plan.md`, that runs on main after the merge.
