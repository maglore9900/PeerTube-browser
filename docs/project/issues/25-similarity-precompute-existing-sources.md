# Similarity precompute: rewrite only existing cache sources

Status: enhancement, needs-triage
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
