# Stable ANN ids, plan A: the id, the schema and the writers

## Requirements

### Asked for

Issue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2), first of two builds. Plan 17 (`docs/project/plans/17-stable-ann-ids.md`) was taken through build 19 as far as its Step 6, which proposed 6 phases. The operator split it into this plan (A) and `docs/project/plans/42-ann-ids-b-readers-cutover.md` (B). ADR-0006 (`docs/project/adr/0006-derived-ann-ids.md`) records the id decision, and `CONTEXT.md` defines **ANN id**.

Plan A gives every `video_embeddings` row a derived `ann_id`, guards it against collisions, migrates existing databases, and makes every writer store it. It changes no reader: the FAISS index, similar, search, metadata, the random cache and the similarity precompute stay on `video_embeddings.rowid` until plan B.

Everything below was settled with the operator in build 19 (Steps 1-5, record `docs/project/plans/19-17-stable-ann-ids.record.md`, now in `delete_me/`), narrowed to plan A. The one new decision is AC-A4.

### Purpose

Correctness, delivered in two merges. Plan A lays the id down in the database without changing what any reader returns. Plan B switches the readers and the index to it in one cutover. The purpose of the whole (a stale index never returns the wrong video) is observed in plan B (its AC8).

### Current state (checked against the tree and the live DB in build 19, read-only)

- The live `engine/server/db/whitelist.db`:
  - 890,052 `video_embeddings` rows, rowids exactly 1..890,052.
  - Primary key `(video_id, instance_domain)`; the table is a rowid table.
  - 1,548 hosts, all already lowercase and trimmed. Every `video_id` is text.
- Hash check: a 63-bit blake2b of `video_id::instance_domain` over all 890,052 keys gave 0 collisions, and no key hashed to 0.
- Writers that renumber rowids, or write `video_embeddings` at all:
  - `build-video-embeddings.py`: `init_schema` uses `CREATE TABLE IF NOT EXISTS` (line 66). Under `--force` it runs DELETE (line 177), then `INSERT OR REPLACE` (line 272).
  - `sync-whitelist.py`: `rebuild_content_tables` runs `DELETE FROM video_embeddings` (line 458), then `INSERT ... SELECT` from the attached crawl DB (lines 493-510). That copy runs only when the source's columns are a superset of `EMBEDDING_COLUMNS`. The same list drives the exact check on the target schema in `ensure_schema_compatibility` (line 194), and the schema created at line 385 has no `ann_id`.
  - `merge-staging-db.py`: `merge_rules.json` gives `video_embeddings` the `INSERT_OR_REPLACE` strategy, run as `INSERT OR REPLACE INTO main.t (common cols) SELECT ... FROM stage.t` over the columns prod and staging share (lines 152-171).
  - `updater-worker.inject_replace_embedding_for_test` (lines 1018-1064): a test-only `INSERT OR REPLACE` of one mutated embedding into staging.
  - `whitelist_migrations.migrate_videos_schema` drops `video_embeddings` (line 268) and does not recreate it. The next schema creation does that.
- Staging: the updater creates staging from `engine/crawler/schema.sql` (`init_staging_db`), which does not create `video_embeddings`, so `build-video-embeddings.init_schema` creates it. `--resume-staging` reuses an existing staging DB, whose table may be in the old shape.
- Readers resolve embedded videos by rowid (the full list is in plan B). They are not touched here.

### Acceptance criteria

- **AC1, the id:** one helper, `engine/server/data/ann_ids.py`, computes `ann_id` as blake2b with an 8-byte digest of `video_id + "::" + normalize_host(instance_domain)`, masked to 63 bits. `normalize_host` is the existing `data/moderation.normalize_host`. The result is positive, non-zero and safe as a signed int64. The same key gives the same id in any process and any DB. Every writer uses this one helper, and plan B's readers will too. Jobs import it the way they already import `data.*`.
- **AC2, the schema:** `video_embeddings` carries `ann_id INTEGER NOT NULL` with a UNIQUE index.
  - A new `whitelist_migrations.migrate_video_embeddings_schema` rebuilds an existing table into that shape and fills the column from the helper through `sqlite3` `create_function`. It follows the existing `migrate_*_schema` table-rebuild pattern, and it is idempotent. `migrate_whitelist_schema` calls it, so `migrate-whitelist.py` runs it.
  - Every job that creates the table creates the same shape: `build-video-embeddings.init_schema` and the `sync-whitelist.py` schema. So does any table recreated after `migrate_videos_schema` drops it.
  - **Collision guard:** a collision fails the write loudly on every write path, including `INSERT OR REPLACE` paths. A collision means a different `(video_id, instance_domain)` producing an `ann_id` already in use, or an id of 0. A write never probes for another id.
  - **Old-shape tables:** writing into a `video_embeddings` table that lacks `ann_id` fails loudly with a message naming `engine/server/db/jobs/migrate-whitelist.py`, or, for a resumed staging DB, saying to recreate staging. No writer ever produces rows without `ann_id`.
- **AC3, the writers:** every writer stores the helper's `ann_id`.
  - `build-video-embeddings.py` computes it per row.
  - `merge-staging-db.py` preserves it from staging. Its only change is the old-shape guard call (approved in build 19).
  - `sync-whitelist.py` copies `ann_id` when the source has the column, and computes it through the registered function when the source has embeddings without it. The target-schema check requires `ann_id`; the source-column check must not.
  - `updater-worker.inject_replace_embedding_for_test` writes `ann_id`.
  - Re-running a writer, or replacing a row, leaves the video's `ann_id` unchanged.
- **AC-A4, the merged state is today's behaviour (new, from the split):** `migrate_video_embeddings_schema` copies every row's rowid explicitly, so a rowid-keyed FAISS index and random cache built before the migration still resolve to the same videos after it. After plan A merges and the migration has run, every reader returns what it returned before. No reader, no index build and no sidecar check changes in this plan.
- **AC-A9, the cycle and docs (plan A's part of AC9):** the orchestrator smoke test's mini-prod carries the collision trigger, so its merge runs guarded on `ann_id` rows. The docs carry plan A's one-time step for existing DBs: stop the Engine, run `migrate-whitelist.py`, start the Engine. No index rebuild is needed for plan A.

### Scope

In scope: AC1, AC2, AC3, AC-A4, AC-A9.

Out of scope, in plan B: the readers (`ann.py`, `embeddings.py`, `metadata.py`, `search.py`, `similar.py`), the random cache, `precompute-similar-ann.py`, `build-ann-index.py`'s ids and `id_source`, the Engine's `id_source` gate, the stale-index test (AC8), the smoke test's `id_source` assertion.

Out of scope for both: incremental FAISS add or remove (F3/F4-M2); rebuilding or re-keying the similarity cache; `videos_fts`; backward compatibility with rowid indexes; the crawler (`engine/crawler`, including `schema.sql`).

### Consistency constraints

- Job CLIs keep their current arguments.
- Refusal messages follow `data/embedding_space.py`: say what is wrong, and name the command that fixes it.
- The migration follows the existing `migrate_*_schema` table-rebuild pattern in `whitelist_migrations.py`.
- Hosts go through the existing `data/moderation.normalize_host`.
- New code matches the style of the file it lands in.
- The smallest thing that works: stdlib `hashlib.blake2b`, no new dependency, one helper module.

### Conflicts

- **Build 19's Step 6 rationale said a DB-first split would leave a merged state that returns wrong videos.** It does not: after plan A, the index, its builder and every reader are still on rowid, and AC-A4 keeps the migration from renumbering rowids. The operator chose the split.
- **AC3's "only change to merge is the strategy change" against AC2's old-shape refusal:** resolved in build 19 by allowing the guard call in `merge-staging-db.py`.

### Tests

- Active tests live in `tests/active`, scratch work goes in `tests/tmp`, job tests in `engine/server/db/jobs/tests/`.
- Pre-build baseline (build 19): the suite exited 0 (`variant: false`). Re-taken at this build's Step 0.
- Fixture churn in plan A: only fixtures that create `video_embeddings` through the shared definition. That is `test_video.py` (its positional inserts at lines 543-544 go through `sync-whitelist.ensure_content_schema`) and `test_whitelist_migrations.py`. Every other fixture builds its own narrow table and keeps working, because no reader changes. `tests/active/conftest.py` gains the shared `compute_ann_id` re-export for plans A and B.
- New tests cover AC1 (determinism, range, normalisation, a pinned value), AC2 (migration backfill, idempotence, failure atomicity, the guard under plain INSERT, `INSERT OR REPLACE` and merge, the old-shape refusal), AC3 (each writer, sync from a source with and without `ann_id`) and AC-A4 (rowids unchanged by the migration).
- Engine-backed tests do not need the shared dataset migrated for plan A, because no reader reads `ann_id`.

### Risks and limitations accepted

- The one-time migration rewrites about 1.4 GB of embedding blobs. It needs that much free disk plus the default full-file backup (about 3.5 GB) unless `--no-backup` is used, and the Engine must be stopped while it runs.
- After plan A deploys, `sync-whitelist.py`, `build-video-embeddings.py` and the merge refuse an unmigrated DB. The migration has to run before the next dataset build or updater run.
- A collision stops a dataset build or a merge loudly, and recovery is manual. The odds are about 4e-8 at 890k keys, and 0 collisions were measured.
- A staging DB resumed from before the migration fails loudly. It is not migrated.
- Until plan B merges, the purpose is not delivered: the index is still rowid-keyed, so a renumbering write without an index rebuild still returns wrong videos, exactly as today.

## High-level plan

### Approach

One new module, `engine/server/data/ann_ids.py`, holds everything the id needs, the way `data/moderation.py` holds `normalize_host` and `ensure_moderation_schema`:
- the pure function that computes the id from `(video_id, instance_domain)`;
- a registration that exposes it to SQLite under one SQL name, through `create_function`;
- the one definition of the `video_embeddings` table (with `CHECK (ann_id > 0)`), the UNIQUE index on `ann_id`, and the collision trigger, created separately;
- an old-shape check that raises the AC2 message;
- `ANN_ID_SOURCE`, the sidecar value plan B's index build and gate use.

**AC1, the id.** blake2b with an 8-byte digest of `video_id + "::" + normalize_host(instance_domain)`, read big-endian and masked to 63 bits, using stdlib `hashlib`. It fits a SQLite INTEGER, a numpy int64 and a FAISS id. The function only computes; an id of 0 is stopped by the schema.

**AC2, the collision guard.** A BEFORE INSERT trigger raises ABORT when another row with a different `(video_id, instance_domain)` already holds `NEW.ann_id`. SQLite fires BEFORE triggers ahead of constraint resolution, so the new row is checked before `OR REPLACE` can delete the other video's row. That covers `build-video-embeddings`, the merge's `INSERT OR REPLACE`, the bulk `INSERT ... SELECT` in sync, the updater's test inject and any hand-run SQL. The trigger is plain SQL, so any connection can insert. A same-key replace matches no other row, so it keeps its id. An id of 0 fails the CHECK, which `OR REPLACE` does not override. A colliding UPDATE fails on the UNIQUE index. `merge_rules.json` keeps `INSERT_OR_REPLACE`.

**AC2, the migration.** `migrate_video_embeddings_schema` returns at once when the table is missing or already has `ann_id`. Otherwise, in one explicit transaction: register the SQL function, create `video_embeddings_new` from the shared definition, copy every row **with its rowid** and with `ann_id` filled by the function, drop the old table, rename the new one, then create the UNIQUE index and the trigger. A backfill collision or an id of 0 rolls the whole rebuild back to the old shape. `migrate_whitelist_schema` calls it last.

**AC-A4, rowids kept.** The copy names `rowid` in both its column list and its select, so the rebuilt table holds the same rowid for every key. A rowid index or random cache built before the migration stays valid, and the Engine can be restarted on it without an index rebuild.

**AC2, old-shape tables.** The helper's check reads `PRAGMA {schema}.table_info(video_embeddings)` and raises RuntimeError naming `migrate-whitelist.py`, and saying a staging DB reused through `--resume-staging` must be recreated. Callers: `build-video-embeddings.py` (through `ensure_video_embeddings_schema`), and `merge-staging-db.py` on `main` and `stage` before the merge transaction. `sync-whitelist.py` refuses through its existing exact target check, whose message already names `migrate-whitelist.py`.

**AC3, the writers.**
- `build-video-embeddings.py` computes the id per row and adds it to the existing `INSERT OR REPLACE`.
- `merge-staging-db.py` already copies the columns prod and staging share, so `ann_id` comes across unchanged; its only edit is the guard call.
- `sync-whitelist.py` gains `TARGET_EMBEDDING_COLUMNS` (with `ann_id`) for the exact check, while `EMBEDDING_COLUMNS` stays the six-column source superset. `rebuild_content_tables` copies a source `ann_id`, or computes it through the registered function.
- `updater-worker.inject_replace_embedding_for_test` computes the id through the helper and writes it.

**AC-A9.** The smoke test creates the guards in mini-prod after copying the table, since its schema copy brings tables and indexes but no triggers. `DATA_BUILD.md`, `DEPLOYMENT.md`, `UPDATER_WORKER.md` and `ORCHESTRATOR_SMOKE_TEST.md` get plan A's step and refusals.

### Alternatives considered

- **UPSERT in every writer instead of a trigger:** the guarantee would depend on every writer's SQL; the test inject, hand-run SQL and the bulk sync would each be a hole.
- **A CHECK that `ann_id` equals the registered function of the key:** every connection that writes, including the sqlite3 CLI, would fail with "no such function".
- **Always recomputing `ann_id` in sync:** safer against a foreign id, but AC3 settles on copying.
- **Letting the migration renumber rowids and requiring an index rebuild with plan A:** works, but makes plan A's deploy a cutover too. Copying rowids costs one column in the copy and keeps plan A's merged state identical to today.
- **For the old-shape merge failure:** extending the rule's `keys`, or guarding only in the updater. The operator chose the direct guard call.
- **Already rejected in ADR-0006:** a mapping table, a pinned rowid, an assigned counter, probing for a free id.

### Risks and gotchas

- **Trigger order.** The guard relies on BEFORE INSERT firing ahead of `OR REPLACE` resolution. The `INSERT OR REPLACE` collision test pins it.
- **Per-row trigger cost.** One indexed probe per row: negligible for batched embedding writes, about 890k probes in a sync reload.
- **DDL split.** `CREATE TABLE IF NOT EXISTS` is a no-op on an old table, but the index and trigger DDL then fail with a raw `no such column: ann_id`. Guards are created only after `ann_id` is confirmed, so an old table always gets the AC2 message. In sync, `ensure_content_schema` runs before `ensure_schema_compatibility`, so its guard creation is conditional.
- **Migration atomicity.** The existing pattern uses `executescript`, which commits first and runs in autocommit. This step uses one explicit `BEGIN`/`COMMIT` so a failed index build cannot leave a table with `ann_id` and no guards.
- **Ports.** `normalize_host` strips ports, so `(v, h:8080)` and `(v, h:9090)` share an id and collide loudly. Before merge, run read-only on the live DB: `SELECT COUNT(*) FROM video_embeddings WHERE instance_domain LIKE '%:%'`, expected 0.
- **`normalize_host` returns None** for an unparsable domain: the id falls back to the trimmed, lowercased domain and never raises inside the SQL function.
- **`normalize_host` is now part of the id contract.** Any edit to it re-keys every `ann_id`. The AC1 pinned value catches it.

### Tradeoffs the operator accepts

- `merge-staging-db.py` changes by one guard call.
- The one-time migration needs disk and a stopped Engine; an unmigrated DB is refused by every writer once plan A deploys.
- A collision stops the run loudly and recovery is manual.
- A resumed pre-migration staging DB fails loudly instead of being migrated.
- Two merges instead of one: the purpose lands with plan B.

### Phases proposed in build 19 (Step 6), for this build's Step 6 to re-derive

Build 19's phases 1-3. Three phases, inside the four-phase limit.

#### Phase 1 - Id function and schema guard

- **Intent:** `data/ann_ids.py` derives each embedded video's ANN id from its `(video_id, normalised host)`, and a `video_embeddings` table created through it refuses any row whose ann_id another key already holds, whatever the insert verb.
- **C1:** `compute_ann_id(video_id, instance_domain)` returns the big-endian 8-byte blake2b of `video_id::normalize_host(instance_domain)` masked to 63 bits.
- **C2:** A table created by `ensure_video_embeddings_schema` refuses a row whose ann_id is held by a different `(video_id, instance_domain)`, under both plain INSERT and INSERT OR REPLACE, and the holder's row survives.
- **Checkpoint and seam:** the public functions of `engine/server/data/ann_ids.py`, called directly (rung 1) against a tmp-path sqlite DB that already holds a `videos` table, in the new `tests/active/test_ann_ids.py`; system interpreter, `compute_ann_id` re-exported through `tests/active/conftest.py`. C1: one call returns the pinned literal for `("abc", "peertube.example")`, computed independently with `hashlib` and pasted in; `"Peertube.Example."` and `"peertube.example"` give the same id, which excludes hashing the raw domain; every id over a few hundred keys lies in `[0, 2**63-1]`, which excludes an unmasked 64-bit read. C2, after `ensure_video_embeddings_schema`: a plain INSERT carrying another key's ann_id raises IntegrityError; the same doctored row under `INSERT OR REPLACE` raises IntegrityError, and the holder's row is still present with its embedding and ann_id unchanged, which excludes a UNIQUE-only guard; a same-key `INSERT OR REPLACE` keeps the row count and the id, which excludes a trigger that also blocks re-embeds.
- **Files:** `engine/server/data/ann_ids.py` (NEW), `engine/server/data/moderation.py` (EDITED), `tests/active/conftest.py` (EDITED), `tests/active/test_ann_ids.py` (NEW), `tests/config.json` (EDITED).

#### Phase 2 - Whitelist migration

- **Intent:** `migrate_whitelist_schema` turns an existing six-column `video_embeddings` into the ann_id shape in one transaction, keeping every row's rowid, so a migrated table carries derived ids with its guards, a rowid index built before it still resolves, and a failed rebuild leaves the old table as it was.
- **C1:** After `migrate_whitelist_schema`, every pre-existing row keeps its rowid and has `ann_id` equal to `compute_ann_id` of its key, and the UNIQUE index and the collision trigger exist.
- **C2:** A rebuild that fails partway leaves `video_embeddings` with its six original columns and every original row.
- **Checkpoint and seam:** `migrate_whitelist_schema(conn)` called directly on a tmp DB holding an old six-column `video_embeddings` with 3 rows **with non-contiguous rowids** (so a copy that renumbers is visible), using the existing `tests/active/test_whitelist_migrations.py` harness. C1: `PRAGMA table_info` includes `ann_id`; for each row, the `(rowid, video_id, instance_domain)` triple equals the one before the migration, which excludes a copy that renumbers; `ann_id == compute_ann_id(video_id, instance_domain)`, which excludes a constant or rowid backfill; `sqlite_master` holds both `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision`; the embedding bytes are unchanged. C2: with a stub `ann_id_of` registered that returns a constant, `migrate_whitelist_schema` raises; afterwards the table has exactly the six old columns, all 3 rows are present and unchanged, and no `video_embeddings_new` is left. Idempotence and the missing-table no-op are inner units.
- **Files:** `engine/server/db/jobs/whitelist_migrations.py` (EDITED), `tests/active/test_whitelist_migrations.py` (EDITED), `tests/config.json` (EDITED).
- **Changed from build 19:** C1 and the checkpoint gained the rowid check (AC-A4).

#### Phase 3 - Writers store the derived id

- **Intent:** The whitelist writer jobs put the derived ann_id on every embedding they write, and a merge into or from an unmigrated table stops with the migrate message instead of writing rows without one.
- **C1:** `sync-whitelist`'s rebuild gives every copied embedding the ann_id of its key, both from a source that has `ann_id` and from one that lacks it.
- **C2:** `merge-staging-db.py` refuses an old-shape `main` and an old-shape `stage` with a message naming `migrate-whitelist.py`.
- **Checkpoint and seam:** C1: `sync-whitelist.py` loaded with `_load_job` (the precedent in `test_host_normalisation.py` and `test_repair_video_channel_names.py`); `ensure_content_schema` on a tmp target, a source attached as SOURCE_SCHEMA, then `rebuild_content_tables`, in `tests/active/test_ann_ids.py`. It runs once against a source that has `ann_id` and once against a six-column source, and asserts per-row `ann_id == compute_ann_id(key)` in each, which excludes copying only and computing only. `ensure_schema_compatibility` passes on the new target. C2: `merge-staging-db.py` run as a subprocess on a tmp prod and staging pair, once with an old-shape stage and once with an old-shape main; each exits non-zero, stderr contains `migrate-whitelist.py` and `--resume-staging` and names the right schema (`stage.` or `main.`), and prod's rows are unchanged. The doctored-staging collision through merge, the normal merge carrying `ann_id`, sync's old-target refusal and the updater test inject are inner units. `build-video-embeddings.py` is not entered because it loads the embedding model; its schema creation is phase 1's `ensure_video_embeddings_schema`.
- **Files:** `engine/server/db/jobs/sync-whitelist.py`, `engine/server/db/jobs/merge-staging-db.py`, `engine/server/db/jobs/build-video-embeddings.py`, `engine/server/db/jobs/updater-worker.py`, `engine/server/db/jobs/tests/test-orchestrator-smoke.py` (mini-prod guards only), `tests/active/test_ann_ids.py`, `tests/active/test_video.py` (inserts only), `tests/config.json` (all EDITED).
- **Changed from build 19:** the smoke test's mini-prod guards and `test_video.py`'s inserts moved here from build 19's phases 6 and 4, because `ensure_content_schema` and the merge change in this plan.

### Coordination the operator does

- Before merge: the read-only port check above.
- After merge, before the next dataset build or updater run: stop the Engine, run `engine/server/db/jobs/migrate-whitelist.py` on the shared dataset, start the Engine. Plan B needs this done.
- The smoke test needs a migrated `--source-db`; the operator runs it manually.

