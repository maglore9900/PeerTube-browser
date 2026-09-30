# Similarity cache shadow build and atomic swap without long API downtime

Status: enhancement, needs-triage
Origin: task 44, [M7][F4]

## Problem

The updater keeps the API stopped until `precompute-similar-ann.py` finishes. Similarity precompute can be very long, causing unnecessary downtime.

## Proposed solution

Build the similarity cache in a shadow DB while the API runs, then cut over atomically.

- **Updater sequence:** stop/start the service only around write-conflict-critical stages (merge + ANN rebuild); start the API before the similarity precompute.
- **Shadow build:** create `similarity-cache.next.db` from the active `similarity-cache.db` (keeps the incremental baseline); run `precompute-similar-ann.py --incremental` against it.
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

