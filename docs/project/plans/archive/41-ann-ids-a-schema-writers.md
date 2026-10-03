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

## Impacts

_Carried from build 19's Step 3-4 inventory (line numbers as of that tree). Entries that span both plans are carried whole; the part outside this plan is for context._

<impacts>
<impact path="engine/server/data/ann_ids.py" element="new module: id function, SQL registration, shared video_embeddings definition (CHECK, UNIQUE index, BEFORE INSERT collision trigger), old-shape check">
New file, modelled on `data/moderation.py` (stdlib only, `from __future__ import annotations`, one-line docstrings).

Contents:
- The pure id function.
- A `register_*(conn)` wrapper over `conn.create_function(name, 2, fn, deterministic=True)`.
- DDL constants or helpers for the table, the UNIQUE index and the trigger.
- The old-shape check, which raises RuntimeError.

Dependencies:
- It imports `normalize_host` from `data.moderation`. That module imports `data.similarity_cache`, which is also stdlib only (os, sqlite3, struct, pathlib), so importing `data.ann_ids` stays safe under the system interpreter that several tests and jobs use (`sys.executable` in `test_precompute_random_rowids.py`). If you add numpy or faiss here, those runs break.
- Every writer, reader-side fixture, migration and job imports it.

Points the implementer must settle:
1. **`normalize_host` can return None** (empty, whitespace or unparsable input). It also **strips ports**. The crawler's `normalize_host_token` keeps `host:port` for bare entries, so `instance_domain` can legitimately hold a port. Two videos with the same `video_id` on `h:8080` and `h:9090` would then hash the same key and collide loudly. The function must define what it hashes when the result is None: raise, or fall back to the raw lowercased domain.
2. **The old-shape check needs a `schema` argument** (`PRAGMA {schema}.table_info(video_embeddings)`). `merge-staging-db.py` must check `main` and `stage` on one connection.
3. **The DDL must be split.** `CREATE TABLE IF NOT EXISTS` is a no-op on an old table, but `CREATE UNIQUE INDEX ... ON video_embeddings(ann_id)` and `CREATE TRIGGER ... NEW.ann_id` fail with `no such column: ann_id`. Index and trigger creation must come after, or be guarded by, the old-shape check, or every caller gets a raw sqlite error instead of AC2's message.
4. **Index and trigger names must not collide** with `idx_video_embeddings_id_instance`, which `data/videos.ensure_video_indexes` drops at every Engine start.
5. **The trigger must use plain SQL** (no registered function) so that the sqlite3 CLI and the Engine's connections can still insert. Inside a trigger on `main`, unqualified table names resolve to `main`, which is correct for merge's attached `stage`.

Regression risk: medium. A change to `normalize_host` silently changes every id, so the AC1 fixed-value test is the only thing that catches it.
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host (dependency, no edit expected); purge_host_data / _host_table_column_pairs">
**`normalize_host`** becomes part of the id contract. Any future edit to it (port handling, IDNA, trimming) re-keys every `ann_id` and silently desynchronises the DB from the stored index and random cache. No code change is planned. Consider a comment at `normalize_host` pointing at `data/ann_ids.py`, or rely on the AC1 pinned-value test.

**`purge_host_data`** deletes `video_embeddings` rows by host. The new BEFORE INSERT trigger does not fire on DELETE, so purges are unaffected. This is the AC8 "purge one host" path. Afterwards a stale index returns misses, not wrong videos, through `fetch_metadata`'s `ann_id` lookup.

Callers:
- `updater-worker.purge_hosts` and `purge_hosts_from_staging`
- `instance-denylist-cli.py --purge-now`
- the moderation integration test

Risk: low.
</impact>
<impact path="engine/server/db/jobs/whitelist_migrations.py" element="new migrate_video_embeddings_schema(conn); migrate_whitelist_schema calls it last">
New function, following the `migrate_*_schema` rebuild pattern:
1. Return at once if the table is missing or already has `ann_id`.
2. Register the SQL function.
3. Create `video_embeddings_new` from the shared DDL.
4. `INSERT ... SELECT` with `ann_id` filled by the function.
5. DROP the old table and RENAME the new one.
6. Create the UNIQUE index and the trigger, IF NOT EXISTS.

`migrate_whitelist_schema` appends the call after `migrate_videos_language`. When `migrate_videos_schema` has just dropped `video_embeddings`, the new step does nothing.

Import: module-level `from data.ann_ids import ...` requires `engine/server` on `sys.path`.
- `migrate-whitelist.py` inserts `server_dir`.
- `tests/active/test_whitelist_migrations.py` loads this file with `importlib` after loading `sync-whitelist.py`, which inserts `server_dir`. It works only by that side effect, so make the test, or the module, insert the path explicitly.

Risks:
- **Atomicity.** The existing pattern uses `executescript`, which COMMITs first and runs each statement in autocommit, so `with conn:` in `migrate-whitelist.py` gives no atomicity. If the UNIQUE index build fails on a backfill collision after the DROP and RENAME, the DB is left with `ann_id` but **no UNIQUE index and no trigger**. A re-run then takes the early return because `ann_id` exists, and the guard is never installed. Either run the whole rebuild in one explicit `BEGIN ... COMMIT`, or make the early-return path still `CREATE ... IF NOT EXISTS` the index and trigger.
- **Size.** About 890k rows rewritten (around 1.4 GB). The Engine must be stopped.
- **FK.** The table declares an FK to `videos`, but `migrate-whitelist`'s connection does not enable `foreign_keys`, so DROP and RENAME are unaffected.

Regression risk: high.
</impact>
<impact path="engine/server/db/jobs/migrate-whitelist.py" element="main(); backup_db">
No logic change is needed beyond the new step running through `migrate_whitelist_schema`. `server_dir` is already on `sys.path` for `data.ann_ids`.

Operational impact:
- **Free space.** `backup_db` (the default) copies the whole `whitelist.db`, about 3.5 GB according to DATA_BUILD's VACUUM note, before the 1.4 GB rebuild. The "about 1.4 GB free" in the accepted tradeoffs understates this unless `--no-backup` is used.
- **No longer additive.** The migration now rewrites a large table, so it must run with the Engine stopped.
- **Help text.** The description, "Migrate whitelist.db schema in-place", stays accurate.

Risk: low in code, medium operationally.
</impact>
<impact path="engine/server/db/jobs/build-video-embeddings.py" element="init_schema(); main() insert tuple and INSERT OR REPLACE; --force path">
Changes:
- `init_schema` creates the table from the shared definition, then calls the old-shape check. The index and trigger must be created only after that check passes (see `ann_ids` point 3), because `CREATE TABLE IF NOT EXISTS` is a no-op on an old staging or whitelist table.
- The per-row tuple gains the id, computed in Python, and the INSERT column list gains `ann_id`.
- New import: `from data.ann_ids import ...`. `server_dir` is already on `sys.path`.

Callers:
- `updater-worker` on staging (fresh from `crawler/schema.sql`, which has no `video_embeddings`, so the table is created in the new shape; a `--resume-staging` old staging fails with the AC2 message)
- `run-dataset-build.sh` (`--force` on `whitelist.db`)
- operators on `whitelist.db`

`--force` does DELETE then reinsert, so every key gets back the same id. The trigger raises on a doctored collision. The IntegrityError aborts that batch; earlier batches are already committed (per-batch commit), which is acceptable as a loud stop.

`scripts/run-reembed.sh` parses the `--model-name` default through the AST; it must remain an `add_argument` with a Constant default.

Risk: medium.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="EMBEDDING_COLUMNS split; ensure_content_schema video_embeddings DDL; ensure_schema_compatibility; rebuild_content_tables embeddings copy">
Changes:
- `EMBEDDING_COLUMNS` becomes two lists:
  - the target list, with `ann_id`, for `_assert_columns_exact(conn, "video_embeddings", ...)`;
  - the source superset, today's six columns.
- `ensure_content_schema` replaces its inline `video_embeddings` DDL with the shared definition.
- `rebuild_content_tables` reads the source `table_info`. If the source has `ann_id`, it copies it; otherwise it selects `<fn>(video_id, instance_domain)`, which needs the function registered on this connection before the INSERT. The trigger fires per row (around 890k indexed probes) inside the single `with conn:` transaction, so a collision rolls back the whole sync.

**Ordering hazard.** `main()` calls `ensure_content_schema(conn)` **before** `ensure_schema_compatibility(conn)`. If the shared DDL creates the UNIQUE index or trigger unconditionally, an unmigrated `whitelist.db` fails with `no such column: ann_id` from the index DDL instead of the exact check's "missing columns: ann_id ... Run migrate-whitelist.py". Keep index and trigger creation conditional, or move the check first.

Other consumers of `ensure_content_schema` and of the module:
- `tests/active/test_video.py`, `test_whitelist_migrations.py`, `test_repair_video_channel_names.py` and `test_host_normalisation.py` (module load)
- `repair-video-channel-names.py`, which loads this module for its FTS helpers

`_load_schema_columns` and `videos_fts` are unaffected.

Risk: high.
</impact>
<impact path="engine/server/db/jobs/merge-staging-db.py" element="main(): old-shape guard on main and stage before BEGIN IMMEDIATE">
Change: one guard call per schema (`main`, `stage`) after ATTACH and before the transaction (approved). Needs `from data.ann_ids import ...`; `server_dir` is already inserted.

The rule loop is unchanged:
- `merge_columns` includes `ann_id` once both sides have it.
- `INSERT OR REPLACE INTO main.video_embeddings (... ann_id ...) SELECT ... FROM stage` hits the trigger per row. A same-key replace keeps the id; a doctored foreign id ABORTs, and the existing `except` rolls back.
- The connection needs no registered function.

Without the guard, an old-shape `stage` would drop `ann_id` from `merge_columns` and fail NOT NULL with a generic error. An old-shape `main` would let rows through with no `ann_id`.

Caller: `updater-worker` step "merge"; the smoke test exercises it.

Risk: low to medium.
</impact>
<impact path="engine/server/db/jobs/merge_rules.json" element="video_embeddings rule">
No change: `INSERT_OR_REPLACE` with keys `video_id`, `instance_domain` stays. Listed because the plan relies on it staying unchanged. `test-orchestrator-smoke.validate_outputs` reads the rules and checks replace and mismatch behaviour per strategy.

Risk: none.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="inject_replace_embedding_for_test; (no-change) count_staging_deltas, seed_staging_from_prod, init_staging_db, --resume-staging flow">
**`inject_replace_embedding_for_test`** must:
- select `ann_id` from `prod.video_embeddings`, or compute it through the helper;
- add `ann_id` to the `INSERT OR REPLACE` into staging.

Without that, NOT NULL fails on a new-shape staging. `server_dir` is already on `sys.path` (lines 24-27), so the "two-line insert" contingency in the plan is not needed. Its docstring may need wording.

No change:
- `init_staging_db` (crawler `schema.sql` has no `video_embeddings`)
- `seed_staging_from_prod` (instances and channels only)
- `count_staging_deltas` (key-based)
- `purge_hosts*`

With `--resume-staging`, a pre-cutover staging now fails loudly in `build-video-embeddings` (accepted).

`tests/active/test_updater_worker.py` AST-scans this file for `build-ann-index.py` and `run_with_cpu_fallback` inside the `try`. A new import does not affect that.

Risk: low.
</impact>
<impact path="engine/server/data/videos.py" element="ensure_video_indexes">
No change. It drops only `idx_video_embeddings_id_instance`, so the new UNIQUE index's name must differ (see `ann_ids`). It runs at every Engine start against `whitelist.db`.

`tests/active/test_videos.py` builds its own table and is unaffected.

Risk: low.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="copy_and_prune_prod / create_table_and_indexes_from_source; validate_outputs">
Changes:
- **Add an `id_source == "video_embeddings.ann_id"` assertion** in `validate_outputs` next to the `meta_total` check (AC9).
- **Copy the triggers.** `create_table_and_indexes_from_source` copies only `type='table'` and `type='index'` DDL from the source, so **the collision trigger is not copied** into mini-prod. The smoke merge would then run without the guard. Extend it to copy `type='trigger'` for `tbl_name`, or build `video_embeddings` from the shared definition.

Dependencies:
- `INSERT INTO video_embeddings SELECT e.*` relies on identical column order, which holds when the DDL is copied.
- `--source-db` defaults to `DEFAULT_DB_PATH` (`whitelist.db`), which must already be migrated. Otherwise mini-prod is old-shape and the merge guard stops the run (arguably correct, but it fails the smoke test).
- `--inject-replace-embedding-for-test` depends on the updater inject computing `ann_id`.
- The replace and mismatch checks compare all columns, `ann_id` included, which is equal for same-key replaces.

Risk: medium.
</impact>
<impact path="engine/server/db/jobs/tests/test-moderation-integration.py" element="synthetic schema and the two INSERT OR REPLACE INTO video_embeddings seeds">
Its own `CREATE TABLE IF NOT EXISTS video_embeddings` has no `ann_id`, and it never runs `fetch_metadata`, ANN or the merge. It exercises purge and serving moderation only, so as written it should keep passing without change.

The plan lists it as churned. Change it only if the fixture is switched to the shared definition, or if the prod-sample mode copies from a migrated DB into this narrower table (it uses explicit column lists, so that is fine).

Uncertain: I did not trace every prod-sample path past line 790.

Risk: low.
</impact>
<impact path="tests/active/conftest.py" element="new shared ann_id fixture helper; engine fixture; embedding_of">
The plan puts a shared helper here that computes `ann_id` for fixture inserts. It must put `engine/server` on `sys.path` to import `data.ann_ids`; conftest currently inserts only `client/backend`.

The existing `embedding_of`, `closeness` and `identity_of` only SELECT from `whitelist.db` and need no change.

**The session `engine` fixture starts the real Engine on the repo's `whitelist.db` and `whitelist-video-embeddings.faiss`.** After AC5 it exits at start until that dataset is migrated and the index rebuilt. That fails every Engine-backed active test, including:
- `test_similar`, `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles`, `test_frontend_reactions` and the `test_random_cache` Engine cases.

This worktree has no `engine/server/db/whitelist.db` (only `random-cache.db`), so these tests read a shared dataset. DATA_BUILD says shared DB migrations run on main after merge only, so pre-merge validation of the Engine-backed suite is constrained.

Risk: high, for the test environment.
</impact>
<impact path="tests/active/test_video.py" element="similars_stack (SELECT rowid → add_with_ids); embedded-video inserts at lines 543-544">
The DB comes from `sync-whitelist.ensure_content_schema`, so it takes the new shape. The positional `INSERT INTO video_embeddings VALUES (6 values)` then breaks, both on column count and on NOT NULL `ann_id`. `similars_stack` must add the index with `ann_id`. The similars case asserts `seed v1 → ["v2"]`, which keeps working once ids match.

Risk: low.
</impact>
<impact path="tests/active/test_whitelist_migrations.py" element="_load_job of whitelist_migrations.py; new migration test">
This is the natural place for:
- the AC2 migration tests: backfill values, the UNIQUE index and trigger present, idempotence, and the early return when the table is missing;
- an old-shape fixture.

The existing test passes, because `ensure_content_schema` creates the new-shape table and the migration no-ops. The module import of `data.ann_ids` relies on `sync-whitelist.py` having been loaded first; see `whitelist_migrations`.

Risk: low.
</impact>
<impact path="tests/config.json" element="test → source file map">
Add `engine/server/data/ann_ids.py` to the tests that exercise it: `test_metadata`, `test_random_cache`, `test_random_videos`, `test_precompute_*`, `test_whitelist_migrations`, `test_video` and the new AC8 test. Add `embedding_space.py` where the gate matters. If the build adds a new job test file for AC8, add its entry.

Risk: low. A missed mapping only weakens change-based selection.
</impact>
<impact path="scripts/run-dataset-build.sh" element="sync, embeddings, index, random cache stages">
No code change is required:
- `precompute-random-rowids.py` keeps its name.
- The `--force` re-embed keeps ids.
- The index stage writes the new `id_source`.

An existing unmigrated `whitelist.db` now fails at the sync stage on the exact check, or at `--from index` on the AC4 guard. DATA_BUILD already says this script does not migrate. Optionally add a migrate step or a log hint.

Risk: low.
</impact>
</impacts>

### Documentation to update

- [ ] `DATA_BUILD.md`
  - **Line 155:** embeddings are copied with their `ann_id`, or `ann_id` is computed when the crawl DB lacks it.
  - **Line 159:** the exact check now includes `ann_id`.
  - **Lines 161-172:** "The migration is additive ... without touching rows ... second run does nothing" is no longer true for `video_embeddings`. Add the one-time step: stop the Engine, run `migrate-whitelist.py` (a table rebuild that keeps rowids and needs about 1.4 GB free plus the default full-file backup), start the Engine. No index rebuild is needed until plan B.
  - **Line 191:** the "schedule with the stable-ANN-ids cutover" note points at that step.
- [ ] `DEPLOYMENT.md`
  - **Triage table:** a row for the `migrate-whitelist.py` message from `sync-whitelist`, merge and `build-video-embeddings`.
  - **Deploy steps:** the one-time migration before the first dataset build or updater run on the new code.
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md`
  - **Prerequisite:** the one-time migration before the first updater run on the new code.
  - **`--resume-staging` (lines 48, 149, 186):** a pre-migration staging DB fails with the AC2 message and must be recreated by running without the flag.
  - **Merge:** it refuses an unmigrated prod or staging.
  - **Line 197:** `--inject-replace-embedding-for-test` keeps the row's `ann_id`.
- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`
  - **Source DB:** it must be migrated, since mini-prod copies its schema.
- [ ] `engine/server/README.md` - line 9 explains the `migrate-whitelist.py` requirement for `videos.language`; add that the writers now also need its `ann_id` step.
- [ ] `docs/project/issues/08-stable-ann-ids.md` - at close, a dated comment that plan A delivered. The issue stays open; plan B closes it.

## Changes to the carried draft for plan A

- **Section 3, the migration:** the copy carries `rowid` (AC-A4), already applied in the code below.
- **Section 1, `ann_ids.py`:** `ANN_ID_SOURCE` lands here though nothing in plan A reads it; plan B's index build and gate import it. Drop it if this build's Step 5 prefers to add it in plan B.
- **Section 13, the smoke test:** only the mini-prod guard part. The `validate_outputs` `id_source` assertion is plan B's.
- **Section 14, tests:** only the shared helper, `test_ann_ids.py`'s AC1, AC2 and AC3 cases, the migration tests (plus the rowid check) and `test_video.py`'s inserts. The AC5 cases, `test_stale_ann_index.py` and the rest of the fixture churn are plan B's.

## Draft implementation carried from build 19 (Step 5)

_The settled draft, sections for this plan only, numbered as in build 19. This build's Step 5 re-drafts against the tree; where the two differ, the tree wins._

### 1. `engine/server/data/ann_ids.py` (new)

```python
"""Derive, store and guard the ANN id of an embedded video (ADR-0006)."""

from __future__ import annotations

import hashlib
import sqlite3

from data.moderation import normalize_host

# The sidecar id_source every index must carry; the Engine refuses any other.
ANN_ID_SOURCE = "video_embeddings.ann_id"
# SQL name of compute_ann_id once register_ann_id_function has run on a connection.
ANN_ID_SQL_FUNCTION = "ann_id_of"
ANN_ID_MASK = (1 << 63) - 1

ANN_ID_INDEX_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)"
# Plain SQL so every connection (Engine, sqlite3 CLI) can insert; BEFORE triggers run ahead of OR REPLACE conflict resolution, so a foreign id aborts instead of deleting the row that holds it.
ANN_ID_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision
BEFORE INSERT ON video_embeddings
WHEN EXISTS (
  SELECT 1 FROM video_embeddings
  WHERE ann_id = NEW.ann_id
    AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)
)
BEGIN
  SELECT RAISE(ABORT, 'video_embeddings ann_id collision: another (video_id, instance_domain) already holds this ann_id; see docs/project/adr/0006-derived-ann-ids.md');
END
"""


def compute_ann_id(video_id: str, instance_domain: str) -> int:
    """Return the 63-bit blake2b ANN id of video_id::normalize_host(instance_domain); 0 is left to the table's CHECK."""
    # A domain normalize_host rejects hashes as its trimmed lowercase text, so every key still has one deterministic id.
    host = normalize_host(instance_domain) or str(instance_domain).strip().lower()
    digest = hashlib.blake2b(f"{video_id}::{host}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ANN_ID_MASK


def register_ann_id_function(conn: sqlite3.Connection) -> None:
    """Expose compute_ann_id to SQL on this connection as ann_id_of(video_id, instance_domain)."""
    conn.create_function(ANN_ID_SQL_FUNCTION, 2, compute_ann_id, deterministic=True)


def create_video_embeddings_table(conn: sqlite3.Connection, table: str = "video_embeddings") -> None:
    """Create the video_embeddings table (or a rebuild's `table`) if missing; a no-op on an existing table of any shape."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB NOT NULL,
          embedding_dim INTEGER NOT NULL,
          model_name TEXT NOT NULL,
          created_at TEXT NOT NULL,
          ann_id INTEGER NOT NULL CHECK (ann_id > 0),
          PRIMARY KEY (video_id, instance_domain),
          FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
        )
        """
    )


def create_ann_id_guards(conn: sqlite3.Connection) -> None:
    """Create the UNIQUE ann_id index and the collision trigger; the table must already have ann_id."""
    conn.execute(ANN_ID_INDEX_SQL)
    conn.execute(ANN_ID_TRIGGER_SQL)


def assert_video_embeddings_has_ann_id(conn: sqlite3.Connection, schema: str = "main") -> None:
    """Raise if {schema}.video_embeddings exists without ann_id; a missing table is left to the caller."""
    columns = [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info(video_embeddings)")]
    if columns and "ann_id" not in columns:
        raise RuntimeError(
            f"{schema}.video_embeddings has no ann_id column. "
            "Run `engine/server/db/jobs/migrate-whitelist.py` to migrate the whitelist DB; "
            "a staging DB reused with --resume-staging must be recreated by running the updater without --resume-staging."
        )


def ensure_video_embeddings_schema(conn: sqlite3.Connection) -> None:
    """Create video_embeddings and its guards, refusing an old-shape table with the migrate message."""
    create_video_embeddings_table(conn)
    assert_video_embeddings_has_ann_id(conn)
    create_ann_id_guards(conn)
```

**Invariants and decisions**

- **Stdlib only.** The module imports `hashlib` and `sqlite3`, plus `data.moderation`, which itself only imports `data.similarity_cache`. Jobs and tests that run under `sys.executable` (such as `test_precompute_random_rowids`) can still import it.
- **When `normalize_host` returns None** (impact point 1): the id falls back to the trimmed, lowercased domain and never raises. A raise inside the registered SQL function would abort a whole sync over one odd host. `normalize_host` never returns text containing whitespace, and it returns every live host unchanged, because they are all already lowercase and trimmed.
- **Ports** (impact point 1): `normalize_host` strips them, as AC1 requires. So `(v, h:8080)` and `(v, h:9090)` share an id, and the trigger stops that write loudly, which falls under the accepted "collision stops loudly". The live 0-collision measurement hashed the raw domain, so **check before merge, read-only:** `SELECT COUNT(*) FROM video_embeddings WHERE instance_domain LIKE '%:%'` on the live DB. If it returns 0, ports cannot cause a collision today.
- **The DDL is split** (impact point 3). The table is created first. The guards are created only by callers that have confirmed `ann_id` exists (`ensure_video_embeddings_schema`, the sync column check, the migration), so an old-shape table always gets the AC2 message and never a raw `no such column: ann_id`.
- **Names** (impact point 4): `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision` do not clash with `idx_video_embeddings_id_instance`, which `ensure_video_indexes` drops at every Engine start.
- **Single statements.** Every DDL goes through `conn.execute`, never `executescript`, so creating the table and guards inside sync's `with conn:` does not commit early.
- **Collisions.** An id of 0 fails the CHECK, which `OR REPLACE` cannot override. A colliding UPDATE fails on the UNIQUE index. A same-key replace matches no other row, so it passes the trigger and keeps the same id.

### 2. `engine/server/data/moderation.py`

Add one line above `def normalize_host`:

```python
# Part of the ANN id contract (data/ann_ids.py): any change here re-keys every video_embeddings.ann_id, stored index and random cache.
```

### 3. `engine/server/db/jobs/whitelist_migrations.py`

Header. The `sys.path` insert means the module no longer relies on `sync-whitelist.py` having been loaded first (as `test_whitelist_migrations.py` currently does):

```python
import sqlite3
import sys
from pathlib import Path

server_dir = Path(__file__).resolve().parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function
```

New function, placed before `migrate_whitelist_schema`:

```python
def migrate_video_embeddings_schema(conn: sqlite3.Connection) -> None:
    """Rebuild video_embeddings with the derived ann_id column, its UNIQUE index and its collision trigger (ADR-0006).

    The rebuild runs in one explicit transaction. A backfill collision or a zero id fails the UNIQUE index or the CHECK and rolls back to the old shape, so a re-run retries the whole rebuild instead of skipping a table left without its guards. Idempotent: a table that already has ann_id, or no table at all, is left alone. Rowids are copied, so a rowid-keyed index built before the migration still resolves the same videos.
    """
    if not _table_exists(conn, "video_embeddings"):
        return
    if "ann_id" in _columns(conn, "video_embeddings"):
        return
    register_ann_id_function(conn)
    # Close whatever the earlier steps left open, as their executescript calls do.
    conn.commit()
    conn.execute("BEGIN")
    try:
        conn.execute("DROP TABLE IF EXISTS video_embeddings_new")
        create_video_embeddings_table(conn, "video_embeddings_new")
        conn.execute(
            f"""
            INSERT INTO video_embeddings_new (
              rowid,
              video_id,
              instance_domain,
              embedding,
              embedding_dim,
              model_name,
              created_at,
              ann_id
            )
            SELECT
              rowid,
              video_id,
              instance_domain,
              embedding,
              embedding_dim,
              model_name,
              created_at,
              {ANN_ID_SQL_FUNCTION}(video_id, instance_domain)
            FROM video_embeddings
            """
        )
        conn.execute("DROP TABLE video_embeddings")
        conn.execute("ALTER TABLE video_embeddings_new RENAME TO video_embeddings")
        # Created after the rename so their SQL names the final table.
        create_ann_id_guards(conn)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
```

`migrate_whitelist_schema` gains a last line, `migrate_video_embeddings_schema(conn)`, after `migrate_videos_language`. When `migrate_videos_schema` has just dropped the table, the new step returns early.

**Departure from the pattern, named.** The existing steps use `executescript`, which commits before it runs and then runs in autocommit. This step uses an explicit `BEGIN`/`COMMIT` instead, because of the atomicity risk the impact inventory names. Its shape (`_new` table, copy, drop, rename) is the existing pattern. The `with conn:` in `migrate-whitelist.py` stays harmless: nothing is left open for it to commit. The FK on `videos` does not affect the DROP or the RENAME, because `migrate-whitelist`'s connection does not enable `foreign_keys`.

### 4. `engine/server/db/jobs/build-video-embeddings.py`

- Import, after `CompactHelpFormatter`: `from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema`.
- `init_schema` becomes:

```python
def init_schema(conn: sqlite3.Connection) -> None:
    """Create video_embeddings in its ann_id shape, refusing an old-shape table."""
    ensure_video_embeddings_schema(conn)
    conn.commit()
```

- The tuple in the batch loop gains `compute_ann_id(video_id, instance_domain)` as its last item. The insert becomes:

```python
            INSERT OR REPLACE INTO video_embeddings
              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
```

- `--force` (DELETE, then reinsert) gives every key back its old id. `--model-name` stays an `add_argument` with a constant default, which `run-reembed.sh` depends on.
- An old-shape staging DB (`--resume-staging`) or `whitelist.db` stops in `init_schema` with the AC2 message, before the model loads.

### 5. `engine/server/db/jobs/sync-whitelist.py`

- Import: `from data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function`.
- `EMBEDDING_COLUMNS` keeps its six names; it is now the source superset and the copied columns. Add, following the `WHITELIST_DERIVED_VIDEO_COLUMNS` precedent:

```python
# Derived in the whitelist DB from (video_id, instance_domain) (data/ann_ids.py). An older crawl DB lacks it, so it belongs in the exact check against `main.video_embeddings` but not in the source superset check.
TARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + ["ann_id"]
```

- `ensure_schema_compatibility`: `_assert_columns_exact(conn, "video_embeddings", TARGET_EMBEDDING_COLUMNS)`. An unmigrated DB gets "missing columns: ann_id ... Run `engine/server/db/jobs/migrate-whitelist.py`".
- `ensure_content_schema`: remove the inline `video_embeddings` DDL from the `executescript`. After it, and before `create_videos_fts_triggers(conn)`, add:

```python
    create_video_embeddings_table(conn)
    # An old-shape table is left for ensure_schema_compatibility to refuse with the migrate message; creating guards on it would fail on the missing column first.
    if "ann_id" in _table_columns(conn, "video_embeddings"):
        create_ann_id_guards(conn)
```

This resolves the ordering hazard without moving the check that `main()` runs afterwards. `repair-video-channel-names.py` and the tests that call `ensure_content_schema` on new DBs get the new shape with guards.

- `rebuild_content_tables` embedding copy:

```python
    if source_embedding_columns.issuperset(EMBEDDING_COLUMNS):
        embedding_columns = ", ".join(EMBEDDING_COLUMNS)
        # A crawl DB that predates ann_id gets it derived here, so its embeddings are kept rather than re-embedded; the trigger guards every row either way.
        register_ann_id_function(conn)
        ann_id_expr = "ann_id" if "ann_id" in source_embedding_columns else f"{ANN_ID_SQL_FUNCTION}(video_id, instance_domain)"
        conn.execute(
            f"""
            INSERT INTO video_embeddings ({embedding_columns}, ann_id)
            SELECT {embedding_columns}, {ann_id_expr}
            FROM {SOURCE_SCHEMA}.video_embeddings
            WHERE (video_id, instance_domain) IN (
              SELECT video_id, instance_domain FROM videos
            );
            """
        )
```

  A collision raises inside the `with conn:` in `main()`, so the whole sync rolls back. Each row costs one probe of the UNIQUE index (around 890k).

### 6. `engine/server/db/jobs/merge-staging-db.py`

- Import: `from data.ann_ids import assert_video_embeddings_has_ann_id`.
- In `main()`, the first lines inside `try:`, before `conn.execute("BEGIN IMMEDIATE")`:

```python
        # An old-shape stage would drop ann_id from merge_columns, and an old-shape main would take rows without one: refuse both with the migrate message.
        assert_video_embeddings_has_ann_id(conn, "main")
        assert_video_embeddings_has_ann_id(conn, "stage")
```

- They sit inside `try` so the existing `finally` still detaches and closes. The existing `except` calls `rollback()`, which does nothing when no transaction is open.
- The rule loop is unchanged. `merge_columns` now includes `ann_id`, and `INSERT OR REPLACE INTO main.video_embeddings` fires `main`'s trigger on each row. Inside a trigger on `main`, the unqualified `video_embeddings` resolves to `main`, which is the intended table.

### 7. `engine/server/db/jobs/updater-worker.py`

- Import, next to `data.moderation`: `from data.ann_ids import compute_ann_id`. `server_dir` is already on `sys.path` (lines 24-27), so the plan's fallback `sys.path` insert is not needed.
- `inject_replace_embedding_for_test`: docstring "Insert one overlapping embedding row into staging with modified payload and the same ann_id." The insert becomes:

```python
            INSERT OR REPLACE INTO video_embeddings
              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)
            VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
```

  with `compute_ann_id(video_id, instance_domain)` added to the parameters. The id is computed rather than read from prod, so the inject works whatever shape prod has, and an old-shape prod is still refused at merge.

### 13. `engine/server/db/jobs/tests/test-orchestrator-smoke.py`

- Import: `from data.ann_ids import ANN_ID_SOURCE, assert_video_embeddings_has_ann_id, create_ann_id_guards`.
- In `copy_and_prune_prod`, right after `create_table_and_indexes_from_source(conn, table)` for `table == "video_embeddings"`:

```python
            if table == "video_embeddings":
                # The copy brings tables and indexes only; mini-prod needs the collision trigger for the merge to run guarded, and an unmigrated source is refused here with the migrate message.
                assert_video_embeddings_has_ann_id(conn)
                create_ann_id_guards(conn)
```

  This is chosen over copying `type='trigger'` generally, which would also bring `videos_fts_*` triggers into a mini-prod that has no `videos_fts`.

- In `validate_outputs`, after `meta_total`:

```python
    if meta.get("id_source") != ANN_ID_SOURCE:
        raise RuntimeError(f"ANN meta id_source is {meta.get('id_source')!r}, expected {ANN_ID_SOURCE!r}")
    checks["ann_id_source"] = meta["id_source"]
```

- `INSERT INTO video_embeddings SELECT e.*` still works, because the DDL is copied with the same column order.

### 14. Tests

**Shared helper.** `tests/active/conftest.py` appends `ROOT / "engine" / "server"` to `sys.path` after the client imports. Appending rather than inserting keeps `client/backend`'s `server` and `lib` first. It then re-exports `from data.ann_ids import compute_ann_id  # noqa: E402`, and tests use `from conftest import compute_ann_id`.

**New: `tests/active/test_ann_ids.py`.** Runs on the system interpreter, apart from the AC8 child.
- AC1:
  - the same call gives the same result;
  - `1 <= id <= 2**63-1` over a few hundred keys;
  - one literal pinned value for `("abc", "peertube.example")`, computed once by an independent `hashlib` one-liner at implementation time and pasted in as a constant;
  - `"Peertube.Example."` gives the same id;
  - an unparsable domain falls back deterministically.
- AC2, schema: `ensure_video_embeddings_schema` on a DB that has `videos`, then:
  - `INSERT` with `ann_id=0` raises IntegrityError (CHECK);
  - a doctored `ann_id` equal to another key's id raises IntegrityError on a plain INSERT, and again on `INSERT OR REPLACE`; afterwards the other row still exists, unchanged;
  - a same-key `INSERT OR REPLACE` keeps the count and the id;
  - an UPDATE to a taken id raises (UNIQUE).
- AC2, old shape:
  - `assert_video_embeddings_has_ann_id` on a six-column table raises a message containing `migrate-whitelist.py` and `--resume-staging`;
  - on an attached schema, it names `stage.`;
  - on a missing table, it does nothing.
- AC2, merge: run `merge-staging-db.py` as a subprocess on a tmp prod and staging pair.
  - A doctored staging row (a new key carrying an existing prod id) exits non-zero; prod is unchanged and the other video is present.
  - An old-shape stage exits non-zero with the message.
  - A normal merge carries `ann_id` across.
- AC3: `sync-whitelist.rebuild_content_tables`, loaded with `importlib` the way the existing tests do, on an attached source **with** `ann_id`, which is copied, and on one **without**, which is computed and equals `compute_ann_id`. In both cases `ensure_schema_compatibility` passes on the new shape and fails on an old target with "missing columns: ann_id ... migrate-whitelist.py".
- AC5: `assert_index_matches_embeddings` with a stub index (`SimpleNamespace(d=4)`) and a sidecar:
  - `id_source` `video_embeddings.rowid` raises naming `build-ann-index.py`;
  - a missing `id_source` raises;
  - `video_embeddings.ann_id` passes.

**New: `tests/active/test_stale_ann_index.py` (AC8).** It runs a child under `ENGINE_PY`, the `test_precompute_similar_ann` pattern, because it needs faiss and numpy.
- The child builds a small DB (`videos`, `channels`, `video_embeddings` via `ensure_video_embeddings_schema`) and an `IDMap2,IVF1,Flat` index on `ann_id`. It records `ann_id → (video_id, host)` from the vectors it indexed.
- **Case A, renumber.** Delete every row and reinsert them in reversed order. The rowids change and the ids do not.
- **Case B, purge.** Run `purge_host_data` for one host.
- **Case C.** Insert a new video that the index does not hold.
- After each case, the child calls `ann.compute_similar_items` and `search.vector_candidates`. It uses a stub server (`index`, `index_lock`, `db`, `db_lock`, `normalize_queries=False`, `similarity_*` defaults, and a `query_encoder` stub whose `enabled=True` and whose `encode` returns a fixed vector).
- It prints JSON. The test asserts that every returned `(video_id, instance_domain)` equals the identity recorded for the vector whose hit produced it, that the purged host's videos are absent, and that the new video is absent rather than substituted.
- This is a departure from the plan's word "job test": it lives in `tests/active`, where the gating suite runs and where the faiss-in-a-child precedent already exists.

**Migration tests (in `tests/active/test_whitelist_migrations.py`).** An old six-column table with 3 rows, then `migrate_whitelist_schema`:
- the columns include `ann_id`, and each value equals `compute_ann_id`;
- `idx_video_embeddings_ann_id` and the trigger are in `sqlite_master`;
- a second run changes nothing (same `sqlite_master` and the same rows);
- a DB without the table is left alone;
- an old table with a doctored duplicate cannot occur from the function, so failure atomicity is pinned by registering a stub `ann_id_of` that returns a constant. The migration raises, and the old table still has six columns and every row.

The test also inserts `engine/server` on `sys.path` itself; the module now does that too.

**Fixture churn.**

| File | Change |
|---|---|
| `test_metadata.py` | Fixture DDL gains `ann_id INTEGER`. Inserts pass `compute_ann_id(label, HOST)`. `_nsfw_metadata` selects `ann_id` instead of `rowid`. |
| `test_random_videos.py` | `NSFW_EMBEDDINGS_TABLE` gains `ann_id`. `_video_db` maps labels to `compute_ann_id`. `_cache_owner` creates `random_ann_ids(position, ann_id)` and monkeypatches `fetch_random_ann_ids` on both modules. The docstring says "unseen ANN id". CTAS copies from `whitelist.db` are unchanged. |
| `test_random_cache.py` | `_source_db` gains an `ann_id` column with computed values. Every `random_rowids` becomes `random_ann_ids`. "positions 1..20 over rowids 1..20" becomes the set of the 20 computed ids. Engine cases map rows back with `SELECT ann_id`. The "no table" probe uses an old-format `random_rowids` file, which pins AC6's old-shape case. |
| `test_db.py` | Its source gains `ann_id`. `_seed_cache` and `CHECK_SQL` move to `random_ann_ids`. Imports `fetch_random_ann_ids`. `SEEDED_ROWIDS` becomes computed ids. |
| `test_precompute_random_rowids.py` | Its source gains `ann_id`. Assertions use `sorted(computed ids)`. New case: an `--out` holding an old `random_rowids` table with `--size` rows is rebuilt into `random_ann_ids`, not kept. |
| `test_precompute_similar_ann.py` | The fixture table gains `ann_id` (`compute_ann_id`). `INDEX_BUILDER` adds with `SELECT ann_id, embedding`. The sidecar adds `"id_source": "video_embeddings.ann_id"`. `SHORT_ROWID` and `v{n}` stay as labels only. |
| `test_video.py` | The positional inserts at 543-544 become explicit column lists, with `ann_id`. `similars_stack` selects `ann_id` for `add_with_ids`. |

`test_internal_client_reads`, `test_search`, `test_similarity_candidates` and `test_videos` are unchanged, because none of them reaches `ann_id`. `test_blocks`, `test_dislikes`, `test_dislike_profile`, `test_profiles` and `test_frontend_reactions` are SELECT-only and need no code change. `test-moderation-integration.py` is unchanged, per its impact. The plan's "Conflicts" list is corrected when Impacts is filled.

**`tests/config.json`.**
- Add `engine/server/data/ann_ids.py` to `test_ann_ids`, `test_stale_ann_index`, `test_metadata`, `test_random_cache`, `test_random_videos`, `test_db`, `test_precompute_random_rowids`, `test_precompute_similar_ann`, `test_whitelist_migrations` and `test_video`.
- Add `embedding_space.py` to `test_ann_ids` and `test_precompute_similar_ann`.
- Map the two new files to the sources they exercise.

`tests/last_test_validation.json` is regenerated by the test run, not edited by hand.
