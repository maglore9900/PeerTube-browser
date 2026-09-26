# Stable ANN ids: replace `video_embeddings.rowid` with deterministic `video_id+host -> int64`

Status: enhancement, needs-triage
Origin: task 37, [M2][F7]

## Problem

ANN uses SQLite `video_embeddings.rowid` as the FAISS id source. This is tightly coupled to physical row layout and becomes operationally fragile after purge/merge/rebuild cycles. ANN ids should derive from logical video identity.

## Proposed solution

Introduce a deterministic ANN id (`ann_id`) from the canonical key `(video_id, instance_domain)` and migrate the ANN, search and precompute pipelines to it end to end.

- **ID contract + helper module:** canonical key builder (`video_id + "::" + normalized instance_domain`); deterministic `int64` generator (stable hash) and collision policy; one helper used by all writers and readers.
- **Schema + migration:** `ann_id` on `video_embeddings` (or a mapping table) with a unique index; backfill existing rows and validate no collisions; schema migration jobs guarantee `ann_id` exists before ANN build.
- **Embedding write paths:** every insert/update into `video_embeddings` writes `ann_id`; idempotent across re-runs and replace merges.
- **ANN build:** `build-ann-index.py` reads `ann_id` instead of `rowid` (`add_with_ids(..., ann_id)`); index metadata `id_source` records the new contract.
- **Runtime search:** `data/ann.py` returns `ann_id`s; `data/embeddings.py` resolves `exclude_ann_id`; `data/metadata.py` fetches by `ann_id`; `handlers/similar.py` uses both. The search endpoint's vector half (`data/search.py`) also resolves rowids today and must move with them.
- **Similarity precompute:** `precompute-similar-ann.py` switches internal ids and metadata lookup to `ann_id`; incremental selection stays logical-key based.
- **Updater/ops:** updater keeps ANN id consistency before ANN rebuild/precompute; runbooks include the backfill step for existing DBs.

## Validation (from the original task)

- Deterministic id generation and collision guard.
- Backfill creates stable ids and the unique constraint holds.
- ANN response correctness after a host purge (no rowid coupling).
- Updater full cycle (merge -> ANN build -> precompute) with the new id source.

## Affected areas (expected)

`engine/server/data/{ann,embeddings,metadata,search}.py`, `engine/server/api/handlers/similar.py`, `engine/server/db/jobs/{build-ann-index,precompute-similar-ann,migrate-whitelist,build-video-embeddings,sync-whitelist,updater-worker}.py`, updater docs.

## Related

- Large enough that triage may route it to `/devsecops:plan` rather than a brief.
- Overlaps the roadmap's M2 video-ID indexing features (F1-M2 to F4-M2).

## Comments
