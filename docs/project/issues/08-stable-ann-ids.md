# Stable ANN ids: replace `video_embeddings.rowid` with deterministic `video_id+host -> int64`

Status: enhancement, ready-for-agent
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

- Planned as `docs/project/plans/17-stable-ann-ids.md` (ADR-0006).
- Overlaps the roadmap's M2 video-ID indexing features (F1-M2 to F4-M2).

## Comments

### Triage (routed to `/devsecops:plan`)

Status stays `enhancement, needs-triage`. This is a feature, not an agent brief: a schema migration with backfill, an id/collision design decision, and about 12 files across the API, the jobs and the runbooks. Plan it as roadmap F1-M2 under `docs/project/plans/`. The plan closes this issue when it delivers.

**Established:**

- **Not implemented.** `build-ann-index.py` still calls `add_with_ids` with `video_embeddings.rowid` and writes `id_source: "video_embeddings.rowid"`. No `ann_id` exists under `engine/server`. No `docs/project/rejected/` entry or ADR covers it.
- **The claim holds in part.** The normal updater cycle keeps the index and the rowids in lockstep: it stops the service, then merges, rebuilds the ANN and precomputes, then restarts (`updater-worker.py`). The coupling breaks in three places:
  - `merge-staging-db.py` uses `INSERT OR REPLACE`, which gives every replaced row a new rowid. If the ANN build then fails, the `finally` block restarts the service with the old index against the new rowids.
  - `instance-denylist-cli.py --purge-now` deletes host rows and does not rebuild the ANN.
  - `sync-whitelist.py` reloads `video_embeddings` with a DELETE of the whole table followed by an INSERT, which reassigns every rowid.
- **Readers the issue leaves out:** `data/random_cache.py`, `data/random_videos.py` and `db/jobs/precompute-random-rowids.py` also key on embedding rowids.
- **Already on logical keys:** the similarity cache output stores targets by `(video_id, instance_domain)`.

### Planned as `docs/project/plans/17-stable-ann-ids.md`

The operator confirmed requirements AC1-AC9 and approved the high-level plan: one build, correctness only, with the random cache included. Incremental index add/remove stays with F3/F4-M2.

- **Design:** `video_embeddings.ann_id INTEGER NOT NULL UNIQUE`, a positive 63-bit blake2b of `video_id::normalize_host(instance_domain)`. A collision fails the write loudly. Existing databases are migrated by a table rebuild in `whitelist_migrations`. The Engine refuses to start on an index whose `id_source` is still `rowid`. Recorded in ADR-0006 (`docs/project/adr/0006-derived-ann-ids.md`), and `CONTEXT.md` defines **ANN id**.
- **Measured on the live `whitelist.db`:** 890,052 rows, 0 hash collisions, no id of 0.
- **Next:** `/workflows:dev-flow docs/project/plans/17-stable-ann-ids.md`. This issue closes as `enhancement, complete` when that build delivers.

## Agent Brief

**Category:** enhancement
**Summary:** Build plan 17: FAISS and every reader of embedded videos move from the SQLite rowid to a derived `ann_id`.

**Spec:** `docs/project/plans/17-stable-ann-ids.md` is the contract. Its Requirements (AC1-AC9, scope, constraints, conflicts) and its approved High-level plan govern. This brief does not restate them, and where the two disagree the plan wins. ADR-0006 records the id decision.

**Current behavior:**
The ANN index stores each embedding's rowid as its vector id. Readers turn index hits and random-cache entries back into videos by rowid, and writers renumber those rowids. So an index that is not rebuilt, or whose rebuild failed, can return the wrong video.

**Desired behavior:**
Every embedding row carries an `ann_id` derived from `(video_id, instance_domain)`. The index, similar, search's vector half, metadata lookup, the random cache and the similarity precompute all resolve videos by it. A stale index can miss a video, but it can't return the wrong one.

**How to run it:** `/workflows:dev-flow docs/project/plans/17-stable-ann-ids.md`. The build fills Impacts, Implementation plan, phases and Close in the plan file itself.

**Acceptance criteria:**
- [ ] Every one of plan 17's AC1-AC9 is met, each resolved by its phase or carrying an operator-approved exemption in the plan's Close section.

**Out of scope:** as plan 17's Scope section lists it. That includes incremental index add/remove (F3/F4-M2), the similarity cache, `videos_fts`, and compatibility with rowid indexes.
