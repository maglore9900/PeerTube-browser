# Similarity precompute: rewrite only existing cache sources

Status: enhancement, complete
Origin: task 56, [M7][F4]

## Problem

The updater runs similarity precompute over all embeddings with full cache recreation, which is heavy and can keep downtime longer than needed.

## Proposed solution

A mode that recomputes similarity only for sources already in `similarity_sources`, rewriting only those entries.

- New CLI mode in `precompute-similar-ann.py`: source set = current embeddings ∩ existing `similarity_sources` in the output cache; process only that set.
- Per processed source, keep the current rewrite semantics: upsert `similarity_sources.computed_at`, delete old `similarity_items`, insert fresh top-k.
- Leave non-processed sources untouched (no global wipe).
- The updater uses the new mode for its precompute stage and stops passing full-reset behaviour.

## Validation (from the original task)

- Processed set equals "already cached and still present in embeddings".
- Processed sources are rewritten; untouched ones are unchanged.
- Updater stage time drops against the full-rebuild baseline.

## Related

- See the ordering note in `24-similarity-cache-shadow-swap`.

## Comments

### Delivered

Delivered by `docs/project/plans/19-25-similarity-precompute-existing-sources.md`, commit `<pending>`.

- **Mode.** `engine/server/db/jobs/precompute-similar-ann.py --refresh-existing` inner-joins `video_embeddings` to the output cache's `similarity_sources` on `(video_id, instance_domain)` and rewrites only those sources, all with the run's single `computed_at`. A missing or empty cache gets the schema and 0 sources, and the run exits 0.
- **Conflict check.** Combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`, argparse rejects the run with exit 2 before the output file is touched.
- **Updater.** The precompute stage in `engine/server/db/jobs/updater-worker.py` builds its command through `similarity_precompute_cmd`, which passes `--refresh-existing`, and the GPU→CPU retry keeps the flag.
- **Scope.** Videos new from a merge get no precomputed entry; the Engine caches them the first time they are requested. Cached sources no longer in `video_embeddings` are left in place, not pruned.
- **Stage time.** "Updater stage time drops against the full-rebuild baseline" is an operator measurement on main after the merge, not an automated gate. The orchestrator smoke test's `similarity_precompute` duration does not serve as that figure, because the smoke run's cache is empty and the stage computes nothing.
- **Behaviour.** For the flags see `DATA_BUILD.md` §5. For the updater's stage see `engine/server/db/jobs/docs/UPDATER_WORKER.md`.
