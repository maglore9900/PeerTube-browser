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
