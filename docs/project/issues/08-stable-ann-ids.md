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

### Re-triage against the current tree (after plans 19-23)

Status stays `enhancement, ready-for-agent`. Plan 17 has not been built, and its Requirements and High-level plan still govern. The facts below have drifted since it was written, and the build's reassessment against the impact inventory has to take them in.

**Still holds:**

- No `ann_id` exists under `engine/`. The live sidecar reads `id_source: "video_embeddings.rowid"` (897,889 vectors, built 2026-10-01). Every reader the plan lists still resolves videos by rowid: `ann.py` (including `search_similar_above`, now the up-next fallback that `data/similarity_candidates.py` calls), `embeddings.py`, `metadata.fetch_metadata`, `search.vector_candidates`, `similar._handle_vector_search`, `random_cache.py`, `random_videos.py`, `precompute-random-rowids.py` and `precompute-similar-ann.py`.
- The hazard still exists. The updater stops the Engine, merges, prunes denied hosts and builds the ANN, then restarts the Engine in a `finally`. A failed ANN build therefore still serves the old index against renumbered rows.
- `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` (internal client reads, similarity candidates) are keyed by logical identity and stay outside this build.

**Changed since plan 17 was written:**

- **The dataset was rebuilt** (commit 57c8417). The 890,052-row count and the zero-collision measurement come from the old DB, so the build re-measures both on the current DB. A collision fails loudly under AC2 either way.
- **The similarity cache uses the compact layout** (`video_keys` + `similarity_sources`, CONTEXT **Video key**). It is still keyed by `(video_id, instance_domain)` and still out of scope. Where plan 17 mentions `similarity_items`, it means the old layout.
- **The similarity precompute now runs after the Engine restarts,** as a shadow build that is gated and then swapped in (ADR-0008). It is no longer inside the stopped window. AC7 and AC9 still apply, and the orchestrator smoke test now covers this shape.
- **Prod runs blue/green** (ADR-0009). The updater stops and starts only the active instance, under the deploy lock.
- **Random cache:** a background worker now runs the builds into per-pid temp files, and during a blue/green overlap two Engines on different code can share `random-cache.db`. Recommendation: give the new shape a new table name rather than reusing `random_rowids`. Old code then sees `no_table` and serves from the DB, instead of accepting the file and failing on a missing `video_rowid` column.
- **Test fixtures:** these files now insert into `video_embeddings`: `test_db`, `test_internal_client_reads`, `test_metadata`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_random_cache`, `test_random_videos`, `test_search`, `test_similarity_candidates` and `test_video` under `tests/active`, plus the two job tests. The list of 9 in plan 17's Conflicts section is out of date.
- Line numbers in plan 17 are stale, especially for the updater.

**Decided (operator, this triage):**

- **Cutover is a one-time outage (O1).** Stop the active instance, run `migrate-whitelist.py`, run `build-ann-index.py`, then start it. Plan 17's R1 and R2 stand as written. `DEPLOYMENT.md` documents the cutover as the one exception to blue/green. Recorded in ADR-0006. A zero-downtime cutover through side files was considered and declined.

**Left open, not blocking:** whether the random cache build scans by `ann_id` (hash order, which gives a uniform sample) or keeps scanning by rowid within one build and only stores `ann_id`. The plan leaves this to the build.

### Plan 17 updated

At the operator's request, plan 17 now includes everything above. "What the current code does" was re-checked against the tree. The Conflicts section has the full fixture list (17 `tests/active` files and 2 job tests, wider than the list given above) and the cutover decision. P3 takes the new random cache table name. P4 covers the shadow similarity stage. R1-R5 reflect blue/green and the unmeasured rebuilt DB. Two findings were not in the comment above:

- `sync-whitelist.ensure_schema_compatibility` requires the embedding columns to match exactly, so adding `ann_id` to `EMBEDDING_COLUMNS` has to be done with R3 in mind.
- Once the new index has overwritten the old file, rolling back to pre-build code needs a `rowid` index rebuilt.

### Note while the build runs: test Engines against the shared index

Recorded here, not in plan 17. The operator expects the build to find this itself. If it doesn't, this is where it is written down.

- **Shared files in the worktree.** In the build worktree, `engine/server/db/whitelist.db`, `whitelist-video-embeddings.faiss`, its `.faiss.json` and `similarity-cache.db` are symlinks to main's files. The session `engine` fixture in `tests/active/conftest.py` starts `server.py` with no path arguments, and the Engine has no data-path flags (`server.py` resolves the default paths under `engine/server/db/`). Every Engine-backed test therefore reads main's live DB and main's `rowid` index.
- **The P2 gate breaks them.** Once AC5 makes the Engine refuse a sidecar whose `id_source` is not `video_embeddings.ann_id`, the build's Engine-backed tests can't start an Engine until those shared files are migrated. Migrating them from the worktree is forbidden: real data migrations run on main after the merge, and every other lane and main's own Engines read the same files.
- **What the build needs.** Engine-backed tests have to start against a migrated temporary copy, with an `ann_id` index built from it. That needs a way to point the Engine at other data paths, or a fixture-level arrangement that does the same. Either way it falls inside the build's scope.
- **After the merge.** Lanes branched before 08 merged (for example 39 or 41) fail to start their test Engines once the `ann_id` cutover has run on main. Merge them before the cutover, or rebase them onto 08.

## Agent Brief

**Category:** enhancement
**Summary:** Build plan 17: FAISS and every reader of embedded videos move from the SQLite rowid to a derived `ann_id`.

**Spec:** `docs/project/plans/17-stable-ann-ids.md` is the contract. Its Requirements (AC1-AC9, scope, constraints, conflicts) and its approved High-level plan govern. This brief does not restate them, and where the two disagree the plan wins. ADR-0006 records the id decision and the one-time-outage cutover. Plan 17 was brought up to date with the tree after plans 19-23. Its line numbers are from that check.

**Current behavior:**
The ANN index stores each embedding's rowid as its vector id. Readers turn index hits and random-cache entries back into videos by rowid, and writers renumber those rowids. So an index that is not rebuilt, or whose rebuild failed, can return the wrong video.

**Desired behavior:**
Every embedding row carries an `ann_id` derived from `(video_id, instance_domain)`. The index, similar, search's vector half, metadata lookup, the random cache and the similarity precompute all resolve videos by it. A stale index can miss a video, but it can't return the wrong one.

**How to run it:** `/workflows:dev-flow docs/project/plans/17-stable-ann-ids.md`. The build fills Impacts, Implementation plan, phases and Close in the plan file itself.

**Acceptance criteria:**
- [ ] Every one of plan 17's AC1-AC9 is met, each resolved by its phase or carrying an operator-approved exemption in the plan's Close section.

**Out of scope:** as plan 17's Scope section lists it. That includes incremental index add/remove (F3/F4-M2), the similarity cache, `videos_fts`, and compatibility with rowid indexes.
