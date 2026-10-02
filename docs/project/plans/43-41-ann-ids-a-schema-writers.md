# 41-ann-ids-a-schema-writers

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/43-41-ann-ids-a-schema-writers.record.md`._

## Requirements

### Asked for

Issue `docs/project/issues/08-stable-ann-ids.md` (roadmap F1-M2): plan A of two (`docs/project/plans/42-ann-ids-b-readers-cutover.md` is plan B). Build 19 took plan 17 (`docs/project/plans/17-stable-ann-ids.md`) through Step 6, and the operator then split it. ADR-0006 (`docs/project/adr/0006-derived-ann-ids.md`) records the id decision, and `CONTEXT.md` defines **ANN id**. Plan A gives every `video_embeddings` row a derived `ann_id`, guards it against collisions, migrates existing databases and makes every writer store it. It changes no reader: the FAISS index, similar, search, metadata, the random cache and the similarity precompute all stay on `video_embeddings.rowid` until plan B. Every decision here was settled with the operator in build 19 (record now in `delete_me/`) and narrowed to plan A. AC-A4 is the one new decision. The operator approved these requirements in this build's Step 1 without changes.

### Purpose

Correctness, delivered in two merges. Plan A puts the id in the database and changes nothing any reader returns. Plan B switches the readers and the index over to it in one cutover. The purpose of the whole, that a stale index never returns the wrong video, is observed in plan B (its AC8). Until plan B merges, a renumbering write without an index rebuild still returns wrong videos, exactly as today.

### Current state (verified against the tree in this build's Step 1)

- `engine/server/data/ann_ids.py` does not exist.
- `data/moderation.py`: `normalize_host` is at line 44. The module imports only stdlib and `data.similarity_cache`.
- `sync-whitelist.py`:
  - `EMBEDDING_COLUMNS` (six columns, line 104) drives both the exact target check `_assert_columns_exact(conn, "video_embeddings", EMBEDDING_COLUMNS)` (line 194) and the source superset copy (lines 493-510).
  - `ensure_content_schema` (line 323) creates `video_embeddings` inline with no `ann_id` (line 385).
  - `rebuild_content_tables` runs `DELETE FROM video_embeddings` (line 458) and then `INSERT ... SELECT` from `SOURCE_SCHEMA`.
  - Helpers `_table_exists(conn, table, schema=None)` and `_table_columns(conn, table, schema=None)` exist.
  - `WHITELIST_DERIVED_VIDEO_COLUMNS` is the precedent for a target-only column.
- `build-video-embeddings.py`:
  - `init_schema` (line 62) uses `CREATE TABLE IF NOT EXISTS` (line 66).
  - `--force` runs DELETE (line 177), then `INSERT OR REPLACE` (line 272).
  - `server_dir` is on `sys.path`.
- `merge-staging-db.py`:
  - ATTACHes `stage` (line 121), then `try:` (line 123) and `BEGIN IMMEDIATE` (line 124).
  - Runs `INSERT OR REPLACE INTO main.{table} ({cols})` over the shared columns (line 169).
  - `server_dir` is on `sys.path`.
  - `merge_rules.json` gives `video_embeddings` `INSERT_OR_REPLACE` with keys `video_id`, `instance_domain`.
- `updater-worker.py`:
  - `inject_replace_embedding_for_test` (line 1018) runs `INSERT OR REPLACE INTO video_embeddings` (line 1046).
  - `server_dir` is on `sys.path` (lines 26-27), and the file already imports `data.moderation`.
- `whitelist_migrations.py`:
  - Imports only `sqlite3`; it has helpers `_table_exists` and `_columns`.
  - Its `migrate_*_schema` steps use `executescript`.
  - `migrate_videos_schema` drops `video_embeddings` (line 268) and does not recreate it.
  - `migrate_whitelist_schema` is at line 390.
- `test-orchestrator-smoke.py`: `create_table_and_indexes_from_source` (line 199) copies only `type='table'` and `type='index'` DDL, so no triggers. `copy_and_prune_prod` is at line 225.
- `tests/active/test_video.py`:
  - Lines 543-544 make positional six-value inserts into a `video_embeddings` table created through `sync-whitelist.ensure_content_schema`.
  - `similars_stack` (line 217) adds to the FAISS index by `rowid`.
- Live DB (build 19, read-only):
  - 890,052 `video_embeddings` rows, with rowids exactly 1..890,052.
  - Primary key `(video_id, instance_domain)`; the table is a rowid table.
  - 1,548 hosts, all already lowercase and trimmed.
  - A 63-bit blake2b over every key gave 0 collisions and no zero id.
- Staging:
  - The updater creates it from `engine/crawler/schema.sql`, which has no `video_embeddings`, so `build-video-embeddings.init_schema` creates the table.
  - `--resume-staging` reuses an existing staging DB, whose table may be in the old shape.

### Acceptance criteria

- **AC1, the id.**
  - One helper module, `engine/server/data/ann_ids.py`, computes `ann_id` as blake2b with an 8-byte digest of `video_id + "::" + normalize_host(instance_domain)`, read big-endian and masked to 63 bits. `normalize_host` is the existing `data/moderation.normalize_host`.
  - The result is positive, non-zero and safe as a signed int64. A zero is refused by the schema's CHECK, not by the function.
  - The same key gives the same id in any process and any DB.
  - When `normalize_host` returns None, the id falls back to the trimmed, lowercased domain and never raises.
  - Every writer uses this helper, and plan B's readers will too.
  - Jobs import it the way they already import `data.*`.
  - The module uses the stdlib only (plus `data.moderation`), so the system interpreter can import it.
- **AC2, the schema.**
  - **Table shape.** `video_embeddings` carries `ann_id INTEGER NOT NULL CHECK (ann_id > 0)` with a UNIQUE index named `idx_video_embeddings_ann_id`. That name must differ from `idx_video_embeddings_id_instance`, which `data/videos.ensure_video_indexes` drops at every Engine start.
  - **Collision trigger.** A plain-SQL BEFORE INSERT trigger named `video_embeddings_ann_id_collision` raises ABORT when a different `(video_id, instance_domain)` already holds `NEW.ann_id`. It uses no registered function, so the sqlite3 CLI and Engine connections can still insert.
  - **Collision guard.** A collision fails the write loudly on every write path: plain INSERT, `INSERT OR REPLACE` (the BEFORE trigger fires ahead of OR REPLACE resolution, so the holder's row survives), the merge, the bulk sync and the test inject. A colliding UPDATE fails on the UNIQUE index, and an id of 0 fails the CHECK. A write never probes for another id. A same-key replace keeps its id.
  - **The migration.** A new `whitelist_migrations.migrate_video_embeddings_schema(conn)`:
    - returns at once when the table is missing or already has `ann_id`;
    - otherwise, in one explicit `BEGIN`/`COMMIT`, registers the SQL function, creates `video_embeddings_new` from the shared definition, copies every row with its rowid and with `ann_id` filled through `sqlite3` `create_function`, drops the old table, renames the new one, then creates the index and the trigger;
    - rolls the whole rebuild back to the old shape on any failure, such as a backfill collision or a zero id, leaving no `video_embeddings_new`;
    - is idempotent.
    It follows the existing `_new`/copy/drop/rename pattern; the explicit transaction is a named departure from the pattern's `executescript`. `migrate_whitelist_schema` calls it last, after `migrate_videos_language`, so `migrate-whitelist.py` runs it. `whitelist_migrations.py` inserts `engine/server` on `sys.path` itself.
  - **Table creation.** Every job that creates the table uses the one shared definition: `build-video-embeddings.init_schema`, `sync-whitelist.ensure_content_schema`, and any table recreated after `migrate_videos_schema` drops it. The DDL is split: `CREATE TABLE IF NOT EXISTS` comes first, and the index and trigger are created only after `ann_id` has been confirmed present. That way an old table always gets the AC2 message, never a raw `no such column: ann_id`. All DDL goes through `conn.execute`, never `executescript`, so nothing commits early inside a caller's transaction.
  - **Old-shape tables.**
    - Writing into a `video_embeddings` table that lacks `ann_id` fails loudly with a RuntimeError. The message names `{schema}.video_embeddings`, names `engine/server/db/jobs/migrate-whitelist.py`, and says a staging DB reused with `--resume-staging` must be recreated.
    - The check takes a `schema` argument (`main`, `stage`) and does nothing when the table is missing.
    - `sync-whitelist.py` refuses through its existing exact target check instead, whose message names `migrate-whitelist.py`.
    - No writer ever produces rows without `ann_id`.
- **AC3, the writers.** Every writer stores the helper's `ann_id`.
  - `build-video-embeddings.py` computes it per row and adds it to its `INSERT OR REPLACE`. Its `init_schema` refuses an old-shape table before the model loads. `--model-name` stays an `add_argument` with a Constant default, because `scripts/run-reembed.sh` parses it.
  - `merge-staging-db.py` preserves the id from staging through its unchanged shared-column copy. Its only change, approved in build 19, is the old-shape guard on `main` and `stage`, placed inside the existing `try` before `BEGIN IMMEDIATE`. `merge_rules.json` is unchanged.
  - `sync-whitelist.py`:
    - The new `TARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + ["ann_id"]` drives the exact target check.
    - `EMBEDDING_COLUMNS` stays the six-column source superset; the source check must not require `ann_id`.
    - `rebuild_content_tables` copies `ann_id` when the source has it, and otherwise computes it through the registered SQL function.
    - A collision rolls back the whole sync, because it runs inside `main()`'s `with conn:`.
  - `updater-worker.inject_replace_embedding_for_test` computes `ann_id` through the helper and writes it.
  - Re-running a writer, `--force` included, or replacing a row leaves the video's `ann_id` unchanged.
- **AC-A4, the merged state is today's behaviour.** `migrate_video_embeddings_schema` names `rowid` in both its INSERT column list and its SELECT. A rowid-keyed FAISS index and random cache built before the migration therefore still resolve to the same videos after it, and the Engine can restart without an index rebuild. Once plan A merges and the migration has run, every reader returns what it returned before. No reader, no index build and no sidecar check changes in plan A.
- **AC-A9, the cycle and docs.**
  - **Smoke test.** In `copy_and_prune_prod`, after `create_table_and_indexes_from_source` for `video_embeddings`, the smoke test's mini-prod calls the old-shape check and creates the guards, so its merge runs guarded on `ann_id` rows. It does not copy all triggers, which would bring in `videos_fts_*` triggers without `videos_fts`.
  - **Docs.** The docs carry plan A's one-time step for existing DBs: stop the Engine, run `migrate-whitelist.py`, start the Engine. No index rebuild is needed for plan A.

### Scope

- **In scope:** AC1, AC2, AC3, AC-A4, AC-A9.
- **Out of scope, in plan B:**
  - the readers (`ann.py`, `embeddings.py`, `metadata.py`, `search.py`, `similar.py`);
  - the random cache and `precompute-random-rowids.py`'s tables;
  - `precompute-similar-ann.py`;
  - `build-ann-index.py`'s ids and `id_source`;
  - the Engine's `id_source` gate (`embedding_space.py`);
  - the stale-index test (AC8, `test_stale_ann_index.py`);
  - the smoke test's `validate_outputs` `id_source` assertion;
  - `test_video.py`'s `similars_stack` switch to `ann_id`;
  - the fixture churn in `test_metadata`, `test_random_videos`, `test_random_cache`, `test_db`, `test_precompute_random_rowids` and `test_precompute_similar_ann`;
  - the AC5 test cases.
- **Out of scope for both plans:**
  - incremental FAISS add or remove (F3/F4-M2);
  - rebuilding or re-keying the similarity cache;
  - `videos_fts`;
  - backward compatibility with rowid indexes;
  - the crawler (`engine/crawler`, including `schema.sql`).
- **`ANN_ID_SOURCE`:** whether the constant lands in `ann_ids.py` now (nothing in plan A reads it) or in plan B is left to Step 5.

### Consistency constraints

- Job CLIs keep their current arguments.
- Refusal messages follow `data/embedding_space.py`: say what is wrong, and name the command that fixes it.
- The migration follows the existing `migrate_*_schema` table-rebuild pattern in `whitelist_migrations.py`, apart from the named explicit-transaction departure.
- Hosts go through the existing `data/moderation.normalize_host`. A one-line comment above it marks it as part of the ANN id contract.
- New code matches the style of the file it lands in.
- `ann_ids.py` follows `data/moderation.py`: stdlib only, `from __future__ import annotations`, one-line docstrings.
- The smallest thing that works: stdlib `hashlib.blake2b`, no new dependency, one helper module.

### Tests

- **Locations.** Active tests live in `tests/active`, scratch work in `tests/tmp` and job tests in `engine/server/db/jobs/tests/`. The record is `tests/last_test_validation.json`, which the test run regenerates; it is never edited by hand. Output goes to `tests/last_test_output.txt`.
- **Baseline suite state.** The pre-build baseline taken at this build's Step 0 exited 0 (`code: 0`, `variant: false`).
- **Fixture churn, plan A only:**
  - `tests/active/test_video.py`: the positional inserts at lines 543-544 become explicit column lists with `ann_id`. `similars_stack` stays on rowid.
  - `tests/active/test_whitelist_migrations.py`: gains the migration tests and inserts `engine/server` on `sys.path` itself.
  - `tests/active/conftest.py`: appends `ROOT / "engine" / "server"` to `sys.path` after the client imports, appending so that `client/backend` stays first, and re-exports `compute_ann_id` for plans A and B.
  - Every other fixture builds its own narrow table and keeps working, because no reader changes.
  - `test-moderation-integration.py` is unchanged.
- **New `tests/active/test_ann_ids.py`**, run on the system interpreter:
  - **AC1:**
    - the same call gives the same result;
    - every id over a few hundred keys lies in `1..2**63-1`;
    - `("abc", "peertube.example")` returns a literal pinned value, computed independently with `hashlib` and pasted in;
    - `"Peertube.Example."` gives the same id as `"peertube.example"`;
    - an unparsable domain falls back deterministically.
  - **AC2 schema**, after `ensure_video_embeddings_schema` on a DB that has `videos`:
    - an `ann_id` of 0 raises IntegrityError;
    - another key's id raises IntegrityError under plain INSERT and under `INSERT OR REPLACE`, and the holder's row survives unchanged;
    - a same-key `INSERT OR REPLACE` keeps the row count and the id;
    - an UPDATE to a taken id raises.
  - **AC2 old shape:**
    - the check on a six-column table raises with `migrate-whitelist.py` and `--resume-staging` in the message;
    - on an attached schema it names `stage.`;
    - on a missing table it does nothing.
  - **AC2/AC3 merge**, run as a `merge-staging-db.py` subprocess on a tmp prod and staging pair:
    - an old-shape stage exits non-zero naming `stage.`;
    - an old-shape main exits non-zero naming `main.`;
    - a doctored staging collision exits non-zero with prod unchanged;
    - a normal merge carries `ann_id` across.
  - **AC3 sync**, with `sync-whitelist.py` loaded through `_load_job`:
    - `rebuild_content_tables` from a source with `ann_id` and from one without gives per-row `ann_id == compute_ann_id(key)`;
    - `ensure_schema_compatibility` passes on the new target and fails on an old target with "missing columns: ann_id ... migrate-whitelist.py".
  - **AC3 updater:** the test inject writes `ann_id`.
- **Migration tests in `test_whitelist_migrations.py`**, starting from an old six-column table with 3 rows on non-contiguous rowids:
  - after `migrate_whitelist_schema`, `ann_id` is present and equals `compute_ann_id` per row;
  - each `(rowid, video_id, instance_domain)` triple is unchanged (AC-A4), and the embedding bytes are unchanged;
  - the index and the trigger are in `sqlite_master`;
  - a second run changes nothing;
  - a missing table is a no-op;
  - with a stub `ann_id_of` that returns a constant, the migration raises and leaves the six old columns, all 3 rows and no `video_embeddings_new`.
- **`build-video-embeddings.py`** is not run end to end, because it loads the embedding model. Its schema path is `ensure_video_embeddings_schema`.
- **`tests/config.json`:**
  - map `engine/server/data/ann_ids.py` to `test_ann_ids`, `test_whitelist_migrations` and `test_video`;
  - map `test_ann_ids` to the sources it exercises (`ann_ids.py`, `moderation.py`, `sync-whitelist.py`, `merge-staging-db.py`, `updater-worker.py`);
  - map `whitelist_migrations.py` to `test_whitelist_migrations`.
- **Engine-backed tests** do not need the shared dataset migrated for plan A, because no reader reads `ann_id`.

### Documentation to update

- **`DATA_BUILD.md`:**
  - **Line 155:** sync copies `ann_id`, or computes it when the crawl DB lacks it.
  - **Line 159:** the exact check now includes `ann_id`.
  - **Lines 161-172:** the migration is no longer purely additive for `video_embeddings`. Add the one-time step: stop the Engine, run `migrate-whitelist.py` (a table rebuild that keeps rowids and needs about 1.4 GB free plus the default full-file backup of about 3.5 GB unless `--no-backup`), start the Engine. No index rebuild is needed until plan B.
  - **Line 191:** the cutover note points at that step.
- **`DEPLOYMENT.md`:**
  - a triage row for the `migrate-whitelist.py` refusal from sync, merge and `build-video-embeddings`;
  - the one-time migration in the deploy steps.
- **`engine/server/db/jobs/docs/UPDATER_WORKER.md`:**
  - the migration as a prerequisite;
  - `--resume-staging` (lines 48, 149, 186): a pre-migration staging DB fails and must be recreated;
  - the merge refuses an unmigrated prod or staging;
  - line 197: the inject keeps `ann_id`.
- **`engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`:** the `--source-db` must be migrated.
- **`engine/server/README.md` line 9:** the writers also need `migrate-whitelist.py`'s `ann_id` step.
- **`docs/project/issues/08-stable-ann-ids.md`:** at close, a dated comment that plan A delivered. The issue stays open for plan B.

### Risks and limitations accepted

- **The one-time migration** rewrites about 1.4 GB of embedding blobs. It needs that much free disk plus the default full-file backup (about 3.5 GB) unless `--no-backup` is used, and the Engine must be stopped while it runs.
- **Unmigrated DBs are refused.** After deploy, `sync-whitelist.py`, `build-video-embeddings.py` and the merge refuse an unmigrated DB, so the migration must run before the next dataset build or updater run. `scripts/run-dataset-build.sh` does not migrate.
- **Collisions.** A collision stops a dataset build, sync or merge loudly, and recovery is manual. The odds are about 4e-8 at 890k keys, and 0 collisions were measured. In `build-video-embeddings`, batches committed before the failing one stay committed.
- **Ports.** `normalize_host` strips ports, so `(v, h:8080)` and `(v, h:9090)` share an id and collide loudly. Operator check before merge, read-only: `SELECT COUNT(*) FROM video_embeddings WHERE instance_domain LIKE '%:%'` on the live DB, expected 0.
- **`normalize_host` is now part of the id contract.** Any edit to it re-keys every `ann_id`; the AC1 pinned value catches that.
- **Resumed staging.** A staging DB resumed from before the migration fails loudly and is not migrated.
- **Trigger cost.** The trigger costs one indexed probe per inserted row, about 890k in a sync reload.
- **Trigger order.** The guard relies on BEFORE INSERT firing ahead of OR REPLACE resolution, which the `INSERT OR REPLACE` collision test pins.
- **Purpose not yet delivered.** Until plan B merges, the index is still rowid-keyed.

### Coordination the operator does

- Before merge: the read-only port check.
- After merge, before the next dataset build or updater run: stop the Engine, run `engine/server/db/jobs/migrate-whitelist.py` on the shared dataset, start the Engine. Plan B needs this done.
- The smoke test needs a migrated `--source-db`; the operator runs it manually.

### Phases proposed in build 19, for this build's Step 6 to re-derive

1. **Id function and schema guard:**
   - Files: `ann_ids.py`, `moderation.py` comment, `conftest.py`, `test_ann_ids.py`, `tests/config.json`.
   - Checkpoint: rung 1, on the public functions against a tmp DB.
2. **Whitelist migration:**
   - Files: `whitelist_migrations.py`, `test_whitelist_migrations.py`, `tests/config.json`.
   - Checkpoint: the rowid, backfill and guards checks, and failure atomicity through a stub `ann_id_of`.
3. **Writers store the derived id:**
   - Files: `sync-whitelist.py`, `merge-staging-db.py`, `build-video-embeddings.py`, `updater-worker.py`, the smoke test's mini-prod guards, `test_ann_ids.py`, `test_video.py` inserts, `tests/config.json`.
   - Checkpoint: sync from a source with and without `ann_id`, and the merge subprocess refusing an old-shape main and an old-shape stage.


## High-level plan

### What I read

Before planning I read the parts of the tree the plan touches:

- `data/moderation.py`: `normalize_host` and the module's imports. Its only non-stdlib import is `data.similarity_cache`, and that module is stdlib only. `data/__init__.py` is empty. So `data.ann_ids` will import on the system interpreter.
- `whitelist_migrations.py`: `migrate_videos_schema` and `migrate_whitelist_schema`.
- `migrate-whitelist.py`: a default-isolation connection, with the backup taken before the connection is opened.
- `sync-whitelist.py`: the column lists, the check helpers, the FTS trigger helpers, `ensure_content_schema`, `rebuild_content_tables` and `main`.
- `build-video-embeddings.py`: `init_schema` and the write loop.
- `merge-staging-db.py`: the whole file.
- `updater-worker.inject_replace_embedding_for_test`.
- `repair-video-channel-names.py` and its test, which reuse sync's FTS helpers.

Both existing `video_embeddings` definitions are identical, including `FOREIGN KEY (video_id, instance_domain) REFERENCES videos`. The shared definition keeps that foreign key.

### Approach

**AC1, one id module.** The new `engine/server/data/ann_ids.py` follows `moderation.py`'s style: `from __future__ import annotations`, stdlib plus `data.moderation`, one-line docstrings. It holds everything plan A and plan B share:

- **`compute_ann_id(video_id, instance_domain)`.** It normalises the host with `normalize_host`. If that returns None, it falls back to the trimmed, lowercased domain. It then hashes `video_id + "::" + host` with `hashlib.blake2b(digest_size=8)`, reads the digest big-endian and masks it to 63 bits. It never raises and never probes for another id. A zero is left for the schema's CHECK to refuse.
- **A registration helper.** It calls `conn.create_function` with the deterministic flag, so SQL (the migration and sync's computed path) can call the same function.
- **The shared table definition**, parameterised by table name so the migration can create `video_embeddings_new` from it. It has the six existing columns, `ann_id INTEGER NOT NULL CHECK (ann_id > 0)`, the composite primary key and the foreign key.
- **The guard DDL:**
  - the UNIQUE index `idx_video_embeddings_ann_id`;
  - the plain-SQL BEFORE INSERT trigger `video_embeddings_ann_id_collision`. It raises ABORT when a row with `NEW.ann_id` and a different `(video_id, instance_domain)` already exists. A RAISE inside a trigger surfaces as `sqlite3.IntegrityError`, which is what the tests expect.
- **An old-shape check** taking `conn` and `schema` (default `main`). It does nothing when the table is missing. When the table lacks `ann_id`, it raises a RuntimeError in `embedding_space.py`'s wording. The message names `{schema}.video_embeddings` and `engine/server/db/jobs/migrate-whitelist.py`, and says a staging DB reused with `--resume-staging` must be recreated.
- **`ensure_video_embeddings_schema(conn)`.** It runs, in order: `CREATE TABLE IF NOT EXISTS`, the old-shape check, then `CREATE ... IF NOT EXISTS` for the index and the trigger. Each statement goes through `conn.execute`, never `executescript`, so nothing commits inside a caller's transaction. Because the guards come after the check, an old table gets the AC2 message and never a raw `no such column: ann_id`.

`moderation.normalize_host` gets the one-line comment marking it as part of the ANN id contract. Whether `ANN_ID_SOURCE` lands now is Step 5's call. My recommendation is plan B, because nothing in plan A reads it and the smallest-thing rule argues against a dead constant.

**AC2, the migration.** `whitelist_migrations.py` inserts `engine/server` on `sys.path` itself and imports the helper. It binds `compute_ann_id` to a module-level name, `ann_id_of`, which the migration looks up at call time, so the failure test can monkeypatch it with a constant stub. `migrate_video_embeddings_schema(conn)` works like this:

1. It returns at once when the table is missing or already has `ann_id`. This also makes it idempotent.
2. It commits any implicit transaction the caller left open, which is what the sibling steps' `executescript` already does, so that its own `BEGIN` cannot fail with "transaction within a transaction".
3. Inside an explicit `BEGIN`/`COMMIT`, it:
   - registers the SQL function over `ann_id_of`;
   - creates `video_embeddings_new` from the shared definition;
   - runs `INSERT INTO video_embeddings_new (rowid, six columns, ann_id) SELECT rowid, six columns, <function>(video_id, instance_domain) FROM video_embeddings`;
   - drops the old table, renames the new one, and creates the index and the trigger.
4. Any exception rolls the whole thing back and re-raises, leaving the old six-column table, all its rows and no `video_embeddings_new`.

A zero id fails the CHECK during the copy. A backfill collision fails when the UNIQUE index is built, still inside the transaction. That is how the constant-stub test fails atomically even though the trigger does not exist yet during the copy.

Naming `rowid` on both sides is AC-A4. Every `(rowid, key)` pair survives, so a rowid-keyed FAISS index and the random cache built before the migration still resolve to the same videos, and no reader changes. The explicit transaction is the named departure from the `executescript` pattern. `migrate_whitelist_schema` calls the new step last, after `migrate_videos_language`.

When an older DB passes through `migrate_videos_schema`, that step drops `video_embeddings` (pre-existing behaviour). The new step then finds the table missing and returns. The next `build-video-embeddings` or sync creates the table from the shared definition.

**AC2/AC3, the writers.**

- **`build-video-embeddings.py`.** `init_schema` becomes `ensure_video_embeddings_schema` plus its existing commit. It runs before the model loads, so an old table is refused cheaply. Each row tuple gains `compute_ann_id(video_id, instance_domain)`, and the `INSERT OR REPLACE` names `ann_id`. `--force` deletes and rewrites, but the id is derived from the key, so it comes back the same. `--model-name` is untouched.
- **`merge-staging-db.py`.** Inside the existing `try`, before `BEGIN IMMEDIATE`, it runs the old-shape check on `main` and then on `stage`. The existing `except` rolls back, which is a no-op with no transaction open, and re-raises. The merge exits non-zero naming the schema. The shared-column `INSERT OR REPLACE` then carries `ann_id` unchanged, and prod's trigger guards it. `merge_rules.json` is unchanged.
- **`sync-whitelist.py`:**
  - The inline `video_embeddings` DDL leaves `ensure_content_schema`'s `executescript`. In its place, `ensure_content_schema` creates the table from the shared definition, and creates the guards only when `ann_id` is already present. This is how sync satisfies "refuse through its existing exact target check instead": an old table is left for `ensure_schema_compatibility`, which runs next.
  - `TARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + ["ann_id"]` drives the exact check, so an old table fails with "missing columns: ann_id" plus the existing `migrate-whitelist.py` suffix.
  - `EMBEDDING_COLUMNS` stays the six-column source superset.
  - `rebuild_content_tables` copies `ann_id` when the source table has it. Otherwise it registers the SQL function and computes `ann_id` in the `INSERT ... SELECT`.
  - **Operator decision taken in this step: "rolls back the whole sync" is made true.** Both FTS trigger helpers currently use `executescript`, which COMMITs first. That would commit `sync_hosts` and the trigger drop before a collision, and leave `videos_fts` unguarded. `drop_videos_fts_triggers` and `create_videos_fts_triggers` will run their statements one by one through `conn.execute`. The two SQL constants become per-statement sequences, still one source of truth. After that, the host sync, the trigger drop, the reload and the FTS rebuild sit in the one implicit transaction that `sync_hosts`' INSERT opens, and `main()`'s `with conn:` commits or rolls back all of it.
- **`updater-worker.inject_replace_embedding_for_test`.** It imports the helper alongside its existing `data.moderation` import, computes `ann_id` for the prod row's key, and writes it. A same-key replace keeps the id.

**AC-A9, the smoke test and docs.**

- `copy_and_prune_prod` copies the `video_embeddings` DDL from the migrated source, so the table has `ann_id`. After `create_table_and_indexes_from_source` for that table, it calls the old-shape check and the guard creation (through `ensure_video_embeddings_schema`). It does not copy all triggers.
- The doc edits follow the requirements' list. They carry the stop / migrate / start step, the disk figures, the `--resume-staging` caveat and the refusal triage row.

**Tests.**

- `conftest.py` appends `engine/server` after the client paths and re-exports `compute_ann_id`.
- `test_ann_ids.py`, the migration cases in `test_whitelist_migrations.py`, the explicit column lists in `test_video.py`, and the `tests/config.json` mappings are as specified.
- `test_repair_video_channel_names.py` must stay green. `repair-video-channel-names.py` already ends with `conn.commit()`, so the helper change only makes its update and rebuild one transaction, and its rat-tail comment, which says the helpers commit, is updated to match. `sync-whitelist.py` maps to that test in `tests/config.json` if it does not already.

### Alternatives considered

- **Store the id in a separate mapping table instead of a column.** Rejected: it adds a join to every plan-B read and a second table that every writer must keep in step. ADR-0006 settled on a derived column.
- **`ALTER TABLE ADD COLUMN ann_id` plus an UPDATE backfill, instead of the rebuild.** It is cheaper on disk. But SQLite cannot add a NOT NULL column without a default, nor add a CHECK through ALTER, so the settled shape would be lost. The rebuild keeps the shape exact and, by naming rowid, keeps AC-A4.
- **Guard collisions with the UNIQUE index alone.** Rejected: under `INSERT OR REPLACE`, a UNIQUE conflict on `ann_id` would silently delete the other video's row. The BEFORE trigger fires ahead of conflict resolution and aborts instead. The UNIQUE index stays for UPDATEs and as the backfill check.
- **A trigger that calls the registered function to recompute the id.** Rejected: the sqlite3 CLI and Engine connections that lack the registration could no longer insert. The trigger only compares stored values.
- **Probing for a free id on collision.** Rejected by the requirements. It would make the id depend on insertion order and break "same key, same id in any DB".
- **Keeping sync's executescript helpers and accepting a partial rollback.** I offered this to the operator in this step, and the operator chose to make the rollback whole.
- **Raising the AC2 message from sync's `ensure_content_schema`.** Rejected because the requirement routes sync's refusal through the exact check. Creating the guards only when `ann_id` exists gives the same refusal without a second message.
- **A `migrate_video_embeddings_schema` parameter for the stub, instead of a module-level `ann_id_of`.** Either works. The module-level name keeps the step's signature `(conn)` like its siblings, and the test monkeypatches it.

### Gotchas and risks

- **Transaction state in the migration.** Python's legacy isolation mode opens implicit transactions only before DML. The explicit `BEGIN` therefore needs a clean connection, hence the commit-first step. The rollback must use `conn.rollback()` so the connection state stays consistent.
- **Sync's implicit transaction.** Once the helpers stop committing, the trigger drop joins the transaction that `sync_hosts`' INSERT opened. In the degenerate case of an empty host set, the drop may autocommit, but nothing collides on that path.
- **`ensure_content_schema` still uses `executescript`** for the other tables. That commit happens at the top of the `with conn:` block, before any data is written, as it does today.
- **Foreign keys during the migration.** `migrate-whitelist.py` does not enable foreign keys, so orphan embedding rows copy across as they are today. A caller that enables foreign keys would fail on orphans and roll back cleanly.
- **The rename.** Renaming `video_embeddings_new` is safe because no other table references `video_embeddings`.
- **Trigger order under OR REPLACE.** The guard relies on SQLite firing the BEFORE INSERT trigger ahead of REPLACE resolution. The `INSERT OR REPLACE` collision test pins this.
- **Same-key REPLACE still gets a new rowid**, as it does today. That is exactly the stale-index problem plan B fixes, and it is not a plan-A regression.
- **Ports collide loudly** because `normalize_host` strips them. The operator's read-only port check covers this before merge.
- **`build-video-embeddings` commits per batch.** On a collision, earlier batches stay committed.
- **The helper change reaches `repair-video-channel-names.py`.** That job becomes more atomic, not less, but it is a second consumer touched by the operator's decision.

### Tradeoffs the operator accepts

- A one-time, Engine-stopped rebuild of about 1.4 GB, plus the default backup of about 3.5 GB.
- Unmigrated databases and pre-migration staging DBs are refused until migrated or recreated.
- Collisions stop builds loudly and need manual recovery.
- About 890k extra indexed probes per full sync from the trigger.
- `normalize_host` is frozen into the id contract.
- The sync FTS trigger helpers no longer commit. This is a behaviour change to a shared helper, chosen in this step.
- Until plan B merges, a renumbering write without an index rebuild still returns wrong videos, exactly as today.

### Deliberate simplifications

- **One module holds both the id function and the schema DDL**, with no schema abstraction. The ceiling is that `ann_ids.py` knows the `video_embeddings` shape. If a second table ever needs derived ids, the upgrade is to split the DDL out.
- **The merge only checks the shape and does not create guards on `main` or `stage`.** It relies on the migration and the creating jobs to have installed them. The ceiling is a prod migrated by a tool other than `migrate-whitelist.py`, which would have the column without the trigger. The upgrade is to call guard creation in the merge, which the requirements currently forbid.

## Impacts

<impacts>
<impact path="engine/server/data/ann_ids.py" element="new module: compute_ann_id, the SQL registration, create_video_embeddings_table(conn, table), create_ann_id_guards, assert_video_embeddings_has_ann_id(conn, schema='main'), ensure_video_embeddings_schema, constants (SQL name, mask, index and trigger DDL; ANN_ID_SOURCE only if Step 5 keeps it)">
**What changes:** a new file. `engine/server/data/__init__.py` exists and is a regular package; no other `data` package or `data.py` exists anywhere in the repo (globbed), and `engine/` has no `data` dir, so `migrate-whitelist.py` putting `engine_dir` ahead of `server_dir` (lines 15-18) cannot shadow it. Jobs that already put `engine/server` on `sys.path` and can import it: sync-whitelist (16-19), merge-staging-db (14-17), build-video-embeddings (11-14), updater-worker (24-27), the smoke test (24-27), migrate-whitelist (13-18). repair-video-channel-names appends it at the end (line 14), which still resolves.

**Style:** match `data/moderation.py`: `from __future__ import annotations`, stdlib imports, then `from data.moderation import normalize_host`, one-line docstrings.

**Import closure:** `data.moderation` imports only stdlib (ipaddress, re, sqlite3, dataclasses, datetime, urllib.parse) plus `data.similarity_cache` (line 21), which imports only os, sqlite3, struct, pathlib, typing. The module therefore imports on the system interpreter. That matters because conftest will import it for the whole active suite, and job subprocesses run under `sys.executable`. Adding numpy or faiss here breaks suite collection.

**Points the implementer must get exactly right:**
- **Hash input:** `f"{video_id}::{host}".encode("utf-8")`, `hashlib.blake2b(..., digest_size=8)`, then `int.from_bytes(..., "big") & ((1 << 63) - 1)`.
- **None fallback:** `str(instance_domain).strip().lower()`. `normalize_host` (moderation.py 44-68) returns None for None, empty or whitespace-only input, a `urlparse` ValueError, no hostname, a dots-only host (62-64) and a host containing whitespace (66-67).
- **Ports:** they are stripped through `.hostname`. `normalize_host_token` keeps a bare `host:port` (DATA_BUILD.md 153), so same-`video_id` rows on two ports of one host collide loudly. That is what the operator's read-only port check covers.
- **No IDNA:** a unicode host and its punycode spelling hash differently.
- **Table definition:** six columns in today's order (`video_id`, `instance_domain`, `embedding`, `embedding_dim`, `model_name`, `created_at`), then `ann_id INTEGER NOT NULL CHECK (ann_id > 0)`, `PRIMARY KEY (video_id, instance_domain)` and the FK to `videos`. It must stay a rowid table (no WITHOUT ROWID), for AC-A4 and for every rowid reader. The order matters to the smoke test's `SELECT e.*` (line 331) and to `test_random_videos.py`'s CTAS and `SELECT *` copies (113-135).
- **Guard names:** `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision`. Neither may equal `idx_video_embeddings_id_instance`, which `data/videos.py:28` drops at every Engine start. No code in `engine/server` drops indexes or triggers by enumeration (grepped `DROP INDEX`, `DROP TRIGGER` and `type='trigger'`), so the guards survive Engine starts and syncs.
- **Trigger body:** plain SQL, with no registered function. In a non-TEMP trigger, unqualified `video_embeddings` resolves to the trigger's own schema, which is right for the merge's attached `stage` and the inject's attached `prod`.
- **DDL calls:** all through `conn.execute`, one statement each, never `executescript`.
- **Old-shape check:** reads `PRAGMA {schema}.table_info(video_embeddings)` and takes `row[1]` positionally, because merge and sync set `row_factory = sqlite3.Row`. An empty result (missing table) is a no-op. The message names `{schema}.video_embeddings`, `engine/server/db/jobs/migrate-whitelist.py` and `--resume-staging`, in `embedding_space.py`'s say-what-is-wrong-then-the-fix style (lines 82-84).
- **Registration:** `create_function(..., deterministic=True)` needs Python 3.8+ and SQLite 3.8.3+ (DEPLOYMENT.md line 13 pins Python 3.12). One SQL-name constant is shared by the migration and sync.

**Limit of the guard:** the trigger refuses an `ann_id` that a different key already holds in the target. It never checks that a copied id equals `compute_ann_id`, so a wrong but unique id from staging or from a sync source is accepted.

**Dependents:** whitelist_migrations, build-video-embeddings, sync-whitelist, merge-staging-db, updater-worker and the smoke test; `tests/active/conftest.py`, and through it every active test; `test_ann_ids.py`, `test_whitelist_migrations.py` and `test_video.py`; plan B's readers later.

**Regression risk:** medium. Any deviation in input format, byte order, mask or fallback silently re-keys every id; the AC1 pinned literal is the only guard. An import error breaks collection of the whole active suite.
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host (line 44): one-line ANN-id-contract comment; purge_host_data and _host_table_column_pairs: no change">
**What changes:** one comment line above `def normalize_host` (line 44). No logic change.

**Dependents:** operator input (the denylist CLI and moderation helpers), `test_moderation.py`, and now every stored `ann_id`. `normalize_host_token` (line 71), which sync uses for hosts-list entries, is a different function and is not part of the contract.

**`purge_host_data`:** deletes `video_embeddings` rows by host. A BEFORE INSERT trigger does not fire on DELETE, so purges are unaffected. Its callers (`updater-worker.purge_hosts` and `purge_hosts_from_staging`, `instance-denylist-cli.py --purge-now`, the moderation integration test) need nothing.

**New coupling:** once conftest imports `data.ann_ids`, a syntax or import error in this file fails collection of every active test, not just its mapped groups.

**Risk:** low for the edit. Any future change to `normalize_host`'s output re-keys every id.
</impact>
<impact path="engine/server/db/jobs/whitelist_migrations.py" element="module header (sys/Path imports, server_dir sys.path insert, data.ann_ids import, module-level ann_id_of); new migrate_video_embeddings_schema(conn); migrate_whitelist_schema (lines 390-395) calls it last">
**Today:** the module imports only `sqlite3` (line 5) and has `_table_exists` (8-14) and `_columns` (17-19).

**What changes:**
- **Header.** It gains `sys`, `Path`, `server_dir = Path(__file__).resolve().parents[2]` (that is `engine/server`), a guarded insert, and `from data.ann_ids import ...`. Without its own insert the module would depend on load order: `test_whitelist_migrations.py` loads `sync-whitelist.py` first (line 79), which happens to insert the path.
- **Stub hook.** A module-level `ann_id_of = compute_ann_id`, looked up at call time (for example `register(lambda v, h: ann_id_of(v, h))`). Registering the object captured at import time would make the test's monkeypatch a no-op.
- **The new function** goes before `migrate_whitelist_schema`, which gains the call after `migrate_videos_language(conn)` at line 395.

**Callers:** `migrate-whitelist.py:21`, as `server.db.jobs.whitelist_migrations` (`engine/server/db/__init__.py` and `jobs/__init__.py` exist), and `test_whitelist_migrations.py:80`, by file path. Nothing else calls `migrate_whitelist_schema` (grepped .py and .sh).

**Transaction behaviour:**
- `migrate_instances_schema` and `migrate_channels_schema` run `executescript`, which commits first. `migrate_videos_language` (387) runs `ALTER TABLE` through `execute`, and legacy isolation opens no transaction for DDL.
- The early return comes before `conn.commit()`. Then the step runs an explicit `BEGIN`, and on any exception `conn.rollback()` and a re-raise.
- `migrate-whitelist.py`'s `with conn:` (86) then has nothing to commit or roll back.
- The existing test commits before each call (87, 102), so an open caller transaction is never exercised.

**AC-A4:** the copy names `rowid` in both the column list and the SELECT. `random_cache.py` and `build-ann-index.py` key on `video_embeddings.rowid`.

**Atomicity:** a zero id fails the CHECK during the copy. A duplicate fails at the UNIQUE index build after the rename. Both happen inside the transaction, so the rollback leaves the six-column table and no `video_embeddings_new`.

**Side effects:**
- **Rename.** After `ALTER TABLE ... RENAME`, `sqlite_master.sql` reads `CREATE TABLE "video_embeddings"`. The smoke test executes it verbatim, which is fine.
- **Older DBs.** `migrate_videos_schema` (268) drops `video_embeddings`, guards included, on DBs that predate the error columns. The new step then returns early, and the next sync or build recreates the table from the shared definition.
- **Foreign keys.** `migrate-whitelist.py` never enables `foreign_keys`, so orphan rows copy as they are.

**One-way:** the pre-plan code fails on a migrated DB. Sync's exact check (sync-whitelist 194) raises `extra columns: ann_id`. The six-column INSERTs (build-video-embeddings 270-277, updater 1044-1057) fail NOT NULL. A merge of an old-code staging DB leaves `ann_id` out of `merge_columns` (merge 152) and fails NOT NULL. Rolling the code back therefore means restoring the backup.

**File size:** about 1.4 GB of freelist pages stay in `whitelist.db`, because nothing sets `auto_vacuum`. A VACUUM may renumber rowids, which is unsafe before plan B.

**WAL:** if the live DB is in WAL mode, the copy also lands in `-wal`, so peak space is higher. The journal mode is unconfirmed.

**Lock duration:** the transaction holds the write lock for the whole 890k-row copy and index build. With cache spill it also takes EXCLUSIVE early, so readers on that file block too. That is why the Engine and the updater must both be down (see `scripts/deploy-bluegreen.sh` and `engine/install-updater-service.sh`).

**Regression risk:** high.
</impact>
<impact path="engine/server/db/jobs/migrate-whitelist.py" element="module docstring (line 2); argparse description (line 30); backup_db (56-69); main() with conn: (84-89); no logic change">
**No logic change.** The new step runs through `migrate_whitelist_schema` (line 87). `server_dir` and `engine_dir` are already on `sys.path` (15-18).

**Docstring:** line 2's "without rebuilding data" becomes false, because `video_embeddings` is now rebuilt; edit it. Line 30's "Migrate whitelist.db schema in-place" stays accurate.

**Operational:**
- `backup_db` uses `path.read_bytes()`, about 3.5 GB of RAM plus 3.5 GB of disk, and copies `-wal`/`-shm` if present.
- The backup is the only rollback (see the one-way note under `whitelist_migrations.py`), so the docs must not suggest `--no-backup` for this migration.
- The default `--db` is the relative `engine/server/db/whitelist.db`, which in a worktree is main's live DB through the symlink. Run it from main after merge, with the Engine and the updater timer stopped.

**Risk:** low in code, medium operationally.
</impact>
<impact path="engine/server/db/jobs/build-video-embeddings.py" element="imports (after line 16); init_schema (62-78); row tuple (257-268); INSERT OR REPLACE (270-277); --force DELETE (175-178); per-batch commit (278)">
**What changes:**
- Import `from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema` after `CompactHelpFormatter` (16).
- `init_schema` becomes `ensure_video_embeddings_schema(conn)` plus the existing `conn.commit()` (78).
- Each tuple gains `compute_ann_id(video_id, instance_domain)`.
- The INSERT names `ann_id` and takes seven placeholders.

**Order, corrected:** `init_schema` runs at line 160. That is after `import numpy`, `torch` and `sentence_transformers` (154-156), and before the CUDA check (163) and `SentenceTransformer(...)` (166). So an old shape is refused before the model loads, but after the heavy imports, not "cheaply" in the import sense.

**`--force`:** DELETE (177) and commit (178), then reinsert, so every key gets back the same id. Rowids still renumber, as today.

**Collisions:** each batch commits at 278, so an IntegrityError leaves the earlier batches committed. The new UNIQUE index adds one index write and one trigger probe per row to a full `--force` run of about 890k rows.

**Foreign keys:** not enabled on this connection, as today.

**`--model-name`:** stays an `add_argument` with a literal Constant default (115-116), because `scripts/run-reembed.sh:143-155` parses it through `ast`.

**Callers:**
- `updater-worker.py:1294-1308`, on staging, through `run_with_cpu_fallback`;
- `scripts/run-dataset-build.sh:236-237` (`--force`);
- `scripts/run-reembed.sh:40`;
- operators.

**Risk:** medium.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="import (line 26); EMBEDDING_COLUMNS (104-111) and new TARGET_EMBEDDING_COLUMNS; ensure_schema_compatibility (186-216, exact check 194); VIDEOS_FTS_TRIGGERS_SQL (270-285) and VIDEOS_FTS_DROP_TRIGGERS_SQL (287-291); create_videos_fts_triggers (294-296) and drop_videos_fts_triggers (299-306); ensure_content_schema (323-418, inline DDL 385-394); rebuild_content_tables (449-523); main() (567-648)">
**What changes:**
1. **Import:** `data.ann_ids`, next to line 26.
2. **Columns:** add `TARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + ["ann_id"]`, with a comment in the style of `WHITELIST_DERIVED_VIDEO_COLUMNS` (98-102), and use it at 194. `EMBEDDING_COLUMNS` stays the source superset (499) and the copied list (500).
3. **`ensure_content_schema`:** delete 385-394 from the `executescript`. Then create the table from the shared definition and create the guards only `if "ann_id" in _table_columns(conn, "video_embeddings")`, before `create_videos_fts_triggers` (418).
4. **`rebuild_content_tables`** (493-510): the target list gains `ann_id`. It selects `ann_id` when the source has it; otherwise it registers the function and selects `<fn>(video_id, instance_domain)`.
5. **FTS helpers:** they run per statement through `conn.execute`.

**Splitting the FTS constants:**
- `VIDEOS_FTS_TRIGGERS_SQL` has `;` inside each `BEGIN ... END` (273, 277, 281, 283), so a naive `split(";")` breaks.
- Use an explicit tuple of complete statements.
- The trigger names must stay `videos_fts_ai`, `_ad` and `_au`: `whitelist_migrations.py:264-266` drops them by name, and `test_whitelist_migrations.EXPECTED_TRIGGERS` (54) asserts them.
- Both constants are used only in this module.

**Why the guards are conditional:** `main()` calls `ensure_content_schema` (598) before `ensure_schema_compatibility` (599). Unconditional guard DDL would raise a raw `no such column: ann_id` instead of "missing columns: ann_id ... Run `engine/server/db/jobs/migrate-whitelist.py`" (196-198).

**Transaction scope:**
- `ensure_moderation_schema` and `ensure_content_schema` use `executescript`, so the top of `with conn:` (595) commits as it does today.
- `sync_hosts`' `executemany` (428) is the first DML and opens the implicit transaction. The trigger drop (456), the DELETEs (458-460), the reload, the trigger recreate (513) and the FTS rebuild (514) then all sit in it, `instances` included.
- The empty-host path (462-465) depends on where CPython issues the BEGIN for an empty `executemany`; that is unverified. Nothing collides there.

**Connection settings:** `foreign_keys = ON` (589); the embedding INSERT passes thanks to its `IN (SELECT ... FROM videos)` filter. `row_factory = sqlite3.Row` (586); `_table_columns` reads `row[1]`.

**Trigger cost:** after `DELETE FROM video_embeddings` the reload inserts into an empty table, with one UNIQUE-index probe per row (about 890k).

**In practice:** a normal crawl DB has no `video_embeddings`, so the copy and compute paths run only for unusual sources and need tests.

**Consumers that execute the module-level import:** `repair-video-channel-names.py` (`_load_sync_whitelist`), `test_video.py`, `test_whitelist_migrations.py`, `test_repair_video_channel_names.py`, `test_host_normalisation.py` and the new `test_ann_ids.py`.

**Risk:** high.
</impact>
<impact path="engine/server/db/jobs/repair-video-channel-names.py" element="repair_channel_names (49-68), rat-tail comment line 58, docstring line 52; module docstring (line 4)">
**What changes in its own code:** the line 58 rat-tail, which says the helpers commit through `executescript`, becomes false. Line 52's "runs between the trigger drop and recreate" stays true.

**Behaviour through the helpers:**
- **Before:** the DROP committed, the UPDATE ran, the `create` `executescript` committed the UPDATE and the triggers, and the rebuild ran in a new transaction.
- **After:** no transaction is open on entry (`main` connects at 84; `has_videos_fts` is a SELECT), so the DROP TRIGGERs autocommit. The UPDATE (61) opens the implicit transaction, the CREATE TRIGGERs and the rebuild join it, and `conn.commit()` (67) commits them together.

**New failure state:** if the count check (65-66) raises, `main` closes without committing (85-88). That rolls back the UPDATE, the recreate and the rebuild, but the DROP is already committed, so `whitelist.db` is left without `videos_fts_*` triggers until a re-run. Re-running recovers (IF EXISTS). An updater merge in that window lets `videos_fts` drift.

**Decision for Step 5:** full atomicity needs `conn.execute("BEGIN")` after `has_videos_fts` (54), before line 60. Without it, `DATA_BUILD.md:197` must describe the dropped-trigger state.

**Path:** it appends `engine/server` (14), so `data.ann_ids` resolves through the tail of `sys.path`; nothing earlier on the path is named `data`.

**Risk:** medium.
</impact>
<impact path="engine/server/db/jobs/merge-staging-db.py" element="import (after line 19); main() try block (123-124): old-shape check on main then stage before BEGIN IMMEDIATE; rule loop (125-200) unchanged">
**What changes:** an import, and two calls at the top of `try:` (123), before `BEGIN IMMEDIATE` (124).

**Failure path:** the existing `except` (203-205) rolls back, a no-op with no transaction open, and re-raises. `finally` (206-208) detaches and closes, and the process exits non-zero with the schema-named message.

**Missing staging table:** the updater's sync-join path with stale hosts but no new hosts (updater-worker 1189, 1320-1326) skips `build-video-embeddings`, so staging, created from the crawler schema, has no `video_embeddings`. The check is a no-op on a missing table, so the existing "table missing in staging DB: video_embeddings" (139-140) still fires. That pre-existing failure is unchanged. Because `main` is checked first, an unmigrated prod gets the migrate message even on that path.

**Rule loop, unchanged:**
- `merge_columns` (152) includes `ann_id` once both sides have it.
- `INSERT OR REPLACE INTO main.video_embeddings` (168-171) fires `main`'s trigger per row. A same-key replace keeps its id.
- A staged id held by another prod key ABORTs, and the whole merge rolls back.
- A wrong but unique id is accepted.

**Connection settings:** `row_factory = sqlite3.Row` (118), `foreign_keys = ON` (119; `videos` merges before `video_embeddings`), `busy_timeout = 10000` (120; a merge during the migration fails after 10 s).

**Callers:** `updater-worker.py:1350-1362` (subprocess, after the Engine stop), the smoke test through the updater, and the new `test_ann_ids.py` subprocess cases. `parse_args` imports `server_config` (28).

**Risk:** low to medium.
</impact>
<impact path="engine/server/db/jobs/merge_rules.json" element="video_embeddings rule (INSERT_OR_REPLACE, keys video_id/instance_domain)">
**No change.** The plan relies on the rule staying `INSERT_OR_REPLACE`, and on `videos` (INSERT_ONLY) merging before `video_embeddings`, so that FK checks pass.

**Readers:** the smoke test's `load_merge_rules` (556) and `validate_outputs` (777-843).

**Risk:** none.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="imports (30-37); inject_replace_embedding_for_test (1018-1068); no change: run_with_cpu_fallback (408), count_staging_deltas (912-963), --resume-staging branch (1166-1173), build step (1294-1310), sync-join skip (1320-1326), stop and merge (1331-1362)">
**`inject_replace_embedding_for_test`:**
- Add `from data.ann_ids import compute_ann_id` next to the `data.moderation` import (30).
- The INSERT (1044-1057) names `ann_id` and passes `compute_ann_id(video_id, instance_domain)`.
- The docstring (1019) gains "with the same ann_id".
- It is called at 1310, right after the build stage (1304), so staging's `main.video_embeddings`, and in the new shape its trigger, already exist. The unqualified INSERT therefore resolves to staging, not to the attached `prod`. Same key, so the trigger passes.

**`run_with_cpu_fallback`:** with `--gpu`, a non-zero exit from `build-video-embeddings` is retried on CPU, so an old-shape refusal or a collision is logged as a GPU failure and fails again. `UPDATER_WORKER.md:168` says there is no CPU fallback.

**`--resume-staging` (1166):** a pre-migration staging DB fails at the build stage, as accepted.

**No change:** `init_staging_db` (the crawler `schema.sql` has no `video_embeddings`), `seed_staging_from_prod`, `count_staging_deltas` (key-based joins on `main`/`stage.video_embeddings`), `purge_hosts*`.

**Tests:**
- `test_updater_worker.py` loads the module in-process; `server_dir` is inserted at 27, so the import resolves.
- Its `_run_main` cases (652-722) fake every `subprocess.run`, so no real merge or build runs there and they are unaffected.
- `test_host_normalisation.py` also loads it.

**Risk:** low.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="imports (29-31); copy_and_prune_prod loop (267-268); create_table_and_indexes_from_source (199-222) unchanged; embeddings copy (327-340); validate_outputs replace checks (821-843)">
**What changes:** an import from `data.ann_ids`. After `create_table_and_indexes_from_source(conn, "video_embeddings")` (268), a call to `ensure_video_embeddings_schema(conn)` (the old-shape check plus the guards), before the copy at 327-340.

**Interactions:**
- **Index created twice.** The source copy takes only `type='table'` (204) and `type='index'` (215) SQL, never triggers. SQLite stores index SQL without `IF NOT EXISTS`, so the copied `idx_video_embeddings_ann_id` is created first and the guard step's IF NOT EXISTS is a no-op.
- **Table SQL.** The table SQL is the rename-quoted `CREATE TABLE "video_embeddings"`, which executes fine.
- **Copy.** Mini-prod uses `journal_mode=OFF` (240). The trigger fires on each row of the `SELECT e.*` copy, which needs the source's column order.
- **Unmigrated source.** The default `--source-db` is `repo_root / DEFAULT_DB_PATH` (36), the symlinked live DB in a worktree. An unmigrated source fails at the check with the migrate message.
- **Replace and mismatch checks** (821-843) compare every column, `ann_id` included, which is equal for same-key replaces. `--inject-replace-embedding-for-test` (1010) depends on the updater inject writing `ann_id`.

**Out of scope:** the `id_source` assertion is plan B's.

**How it runs:** manually, not in the gating suite.

**Risk:** medium.
</impact>
<impact path="engine/server/db/jobs/tests/test-moderation-integration.py" element="own video_embeddings schema (166-174) and INSERT OR REPLACE seeds (361, 776); no change">
**No change.** It builds its own table without `ann_id`, PK, FK or trigger, imports only `data.moderation`, `data.serving_moderation` and `data.similarity_cache` (31-40), and never runs sync, merge or build-video-embeddings. Its prod-sample copy uses explicit six-column lists (776), so a migrated source still works.

**Risk:** low.
</impact>
<impact path="engine/server/data/videos.py" element="ensure_video_indexes (8-28)">
**No change.** At every Engine start it runs `executescript("DROP INDEX IF EXISTS idx_video_embeddings_id_instance;")` (28), and only that name, so the new guards survive.

**Uncertain:** that statement is a write on `whitelist.db`. An Engine instance that starts while the migration holds the write lock (a blue/green deploy, or the updater's `finally` start) would wait on the lock and could fail its start. The Engine's connect timeout was not checked.

**Risk:** low.
</impact>
<impact path="engine/server/db/jobs/build-ann-index.py" element="SELECT rowid, embedding; id_source rowid; no change in plan A">
**No change.** It keeps adding vectors by rowid, which AC-A4 preserves across the migration.

**Still renumbers rowids, as today:** a sync reload, `--force`, a same-key REPLACE, or a VACUUM. `DATA_BUILD.md:232` stays true.

**Risk:** none from code.
</impact>
<impact path="engine/server/data/random_cache.py" element="rowid-range reads; no change">
**No change.** Its rowid windows stay valid only because the migration copies `rowid` explicitly.

**Risk:** low if AC-A4 holds.
</impact>
<impact path="engine/server/data/embedding_space.py" element="refusal messages (44-91): style reference only">
**No change.** Its messages (for example 82-84: "... now holds X. Rebuild the index with build-ann-index.py.") are the style the old-shape RuntimeError must follow. Plan A changes no gate here.

**Risk:** none.
</impact>
<impact path="engine/server/db/jobs/inspect-embedding.py" element="SELECT of named columns from video_embeddings (~37-38)">
**No change.** It is a read-only diagnostic over named columns, so the extra column does not affect it.

**Risk:** none.
</impact>
<impact path="tests/active/conftest.py" element="sys.path setup (39-45), new append of engine/server and compute_ann_id re-export; module docstring (1-13)">
**What changes:**
- After the client imports (43-45), append `ROOT / "engine" / "server"` to `sys.path`. Appending keeps `client/backend`'s `server` and `lib` first.
- Re-export `from data.ann_ids import compute_ann_id  # noqa: E402`.
- Add a docstring line about the re-export.
- Add a one-line comment saying the append makes the test modules' later guarded `engine/server` inserts no-ops (see the per-file entries below).

**Effect on the suite:**
- `data`, `data.moderation`, `data.similarity_cache` and `data.ann_ids` are imported and cached in `sys.modules` at collection, for every active test. An import error in any of them fails the whole suite.
- `test_similarity_candidates.py:94` stubs only `sys.modules["data.ann"]`, which `ann_ids` does not import, so it is unaffected.
- Nothing named `data` or `db` exists in `client/backend` (only `server.py` and `lib/`), in `tests/active`, or in `engine/server/api` (whose packages are `handlers` and `recommendations`), so there is no shadowing.

**Shared dataset:** the `engine` and `dataset` fixtures read the shared `whitelist.db` (36). Plan A's Engine reads no `ann_id`, so they pass whether or not that DB is migrated.

**Risk:** medium.
</impact>
<impact path="tests/active/test_server.py" element="guarded engine/server and api inserts (167-171) before `from data.interaction_events import ...` (172)">
**No code change.** Once conftest appends `engine/server`, the `if not in sys.path` guard skips it: `engine/server` stays at the end of `sys.path` while `api` is still inserted at the front.

`data` is already in `sys.modules` from conftest, so `data.interaction_events` resolves the same way. The line 167 comment ("The Engine dirs go on sys.path after conftest's import") becomes half true.

**Risk:** low, harmless today.
</impact>
<impact path="tests/active/test_video.py" element="positional inserts (543-544); guarded sys.path inserts (54-57); _seed (529-552); similars_stack (215-223) unchanged">
**What changes:** the six-value `INSERT INTO video_embeddings VALUES (...)` at 543-544 breaks against the seven-column table `ensure_content_schema` (533) now creates, on both column count and NOT NULL `ann_id`. It becomes an explicit column list carrying `compute_ann_id('v1'|'v2', HOST)`, imported next to line 49's conftest import.

**Unchanged:** `similars_stack` stays on rowid in plan A. The `heavy_au` trigger (549) is unaffected.

**Path:** the guard at 55-57 now skips `engine/server`; `api` still goes first, and `from handlers import video` (59) resolves as before.

**Mapping:** `tests/config.json` (158-163) maps this test to neither `sync-whitelist.py` nor `ann_ids.py`.

**Risk:** low.
</impact>
<impact path="tests/active/test_host_normalisation.py" element="guarded engine/server insert (21-23); in-process loads of sync-whitelist.py and updater-worker.py">
**No code change.** The guard becomes a no-op. `from data.moderation import normalize_host_token` (25) resolves through the cached `data` package.

The in-process loads of sync-whitelist and updater-worker now also execute their `data.ann_ids` imports, which resolve.

**Risk:** low.
</impact>
<impact path="tests/active/test_updater_worker.py" element="guarded engine/server insert (42-44); _load_job of updater-worker.py (59-68)">
**No code change.** The guard becomes a no-op; the module's own insert at line 27 is skipped too. The new `data.ann_ids` import resolves.

The AST scans of `main` (around 640-649) look at lock, stop and start calls, which a new import does not disturb.

**Risk:** low.
</impact>
<impact path="tests/active/test_videos.py" element="guarded engine/server insert (13-15); own narrow video_embeddings table (23)">
**No code change.** The guard becomes a no-op, and its own table never meets the shared definition.

**Risk:** low.
</impact>
<impact path="tests/active/test_precompute_similar_ann.py" element="guarded engine/server insert (25-26); own six-column fixture table (65-68, 81)">
**No code change in plan A.** The guard becomes a no-op. The fixture table and its rowid-keyed inserts are plan B's churn.

**Risk:** low.
</impact>
<impact path="tests/active/test_similar.py" element="engine/server and api insert loop (90)">
**No code change.** I saw this as a `for _path in (...)` loop on line 90 but did not read its guard. If it has the same `not in sys.path` guard, `engine/server` stays at the end, which is harmless; if it inserts unconditionally, it becomes a duplicate front entry, also harmless.

**Risk:** low.
</impact>
<impact path="tests/active/test_moderation.py" element="engine/server and api insert loop (16-17)">
**No code change.** The same guarded-loop pattern (16-17); with the guard, `engine/server` stays at the end. `data.moderation` is already cached from conftest.

**Risk:** low.
</impact>
<impact path="tests/active/test_db.py" element="engine/server and api insert loop (27-29); own two-column video_embeddings (165-168)">
**No code change.** The guarded loop skips `engine/server`. The own narrow table is unaffected. `_C1_CHILD` runs under `sys.executable` with `SERVER_DIR` passed explicitly.

**Risk:** low.
</impact>
<impact path="tests/active/test_interaction_events.py" element="engine/server and api insert loop (18-20)">
**No code change.** The guarded loop skips `engine/server`, and the module imports resolve through the cached `data` package.

**Risk:** low.
</impact>
<impact path="tests/active/test_internal_events.py" element="engine/server and api insert loop (26-29)">
**No code change.** The guarded loop skips `engine/server`. Its Engine child runs under `ENGINE_PY` with explicit paths.

**Risk:** low.
</impact>
<impact path="tests/active/test_metadata.py" element="engine/server and api insert loop (24-27); own fixture tables (72, 91, 196-205)">
**No code change in plan A.** The guarded loop skips `engine/server`. The fixture churn is plan B's.

**Risk:** low.
</impact>
<impact path="tests/active/test_migrate_similarity_cache.py" element="engine/server and api insert loop (16-17)">
**No code change.** The guarded loop skips `engine/server`. `data.similarity_cache` is already cached from conftest.

**Risk:** low.
</impact>
<impact path="tests/active/test_random_cache.py" element="engine/server and api insert loop (42-44); sys.modules['server_config'] assignment (112); own two-column source (134-137)">
**No code change in plan A.** The guarded loop skips `engine/server`. The `server_config` module swap (112) is unrelated to `data.*`.

**Risk:** low.
</impact>
<impact path="tests/active/test_random_videos.py" element="engine/server and api insert loop (54-56); CTAS and SELECT * copies from the shared whitelist.db (113-135, 225-228, 299-302); NSFW fixture (372-389, 477)">
**No change in plan A.** The guarded loop skips `engine/server`.

Once the shared DB is migrated, the CTAS tables gain an `ann_id` column with no index, CHECK or trigger. The T→T2 duplicate (132-135) then leaves two rows with one `ann_id`, which is harmless because no plan-A reader reads `ann_id`. Plan B must revisit this.

**Risk:** low.
</impact>
<impact path="tests/active/test_similarity_cache.py" element="engine/server and api insert loop (16-17)">
**No code change.** The guarded loop skips `engine/server`.

**Risk:** low.
</impact>
<impact path="tests/active/test_similarity_candidates.py" element="engine/server and api insert loop (27-29); sys.modules['data.ann'] stub (94)">
**No code change.** The guarded loop skips `engine/server`. The `data.ann` stub is independent of `data.ann_ids`, which never imports `data.ann`.

**Risk:** low.
</impact>
<impact path="tests/active/test_ann_ids.py" element="new test module">
**New file.** It covers:
- **AC1:** determinism, the range `1..2**63-1`, the pinned literal for `("abc", "peertube.example")`, `"Peertube.Example."` matching, and the None fallback with at least one dots-only or embedded-whitespace input.
- **AC2 schema:** the CHECK refusing 0; collisions under plain INSERT and INSERT OR REPLACE, with the holder row surviving; a same-key replace keeping its id; an UPDATE to a taken id.
- **Old shape:** `main`, `stage` and a missing table.
- **Merge subprocesses** under `sys.executable`: the tmp prod and staging need every rule table (`instances`, `channels`, `videos`, `video_embeddings`), or the merge raises "table missing".
- **Sync:** `_load_job` of `sync-whitelist.py`, a source attached as `source`, with and without `ann_id`, plus the old-target refusal.
- **The updater inject:** in-process.

**Wording:** say "refuses an id another prod key holds", never "verifies ids". Use the module-docstring-as-spec style.

**Risk:** low.
</impact>
<impact path="tests/active/test_whitelist_migrations.py" element="module docstring (1-6); _load_job (59-63, 79-80); test_migration_adds_language_column (78-112); new migration cases">
**Existing case:** it keeps passing. `ensure_content_schema` (85) now creates the new-shape table with guards, so the new step returns early, and the second-run assertions (104-110) on `videos` and the triggers still hold.

**New cases:**
- A literal six-column `CREATE TABLE video_embeddings` in the style of `PRE_LANGUAGE_VIDEOS_SQL`, with 3 rows on non-contiguous rowids.
- The stub case monkeypatches the loaded module's `ann_id_of`.
- `compute_ann_id` comes from conftest.

**Docstring:** it describes only the language migration and must gain the `video_embeddings` behaviours.

**Risk:** low.
</impact>
<impact path="tests/active/test_repair_video_channel_names.py" element="seeded_db (62-75); test_repaired_fts_finds_own_name_not_foreign_name (130-158)">
**No code change expected.** `ensure_content_schema` (70, 134) also creates the new-shape `video_embeddings` with guards; the test inserts no embeddings. The direct helper calls (138, 142) follow commits (136, 141), so they run per statement in autocommit as before. `repair_channel_names` then commits its UPDATE, recreate and rebuild together.

**Coverage gap:** no test covers the failure path that leaves the triggers dropped.

**Mapping:** `tests/config.json` (173-175) maps this test only to `repair-video-channel-names.py`; it must gain `sync-whitelist.py`.

**Risk:** low.
</impact>
<impact path="tests/config.json" element="test_groups">
**Changes:**
- **New group** `test_ann_ids.py`: `engine/server/data/ann_ids.py`, `engine/server/data/moderation.py`, `engine/server/db/jobs/sync-whitelist.py`, `engine/server/db/jobs/merge-staging-db.py`, `engine/server/db/jobs/updater-worker.py`, and optionally `build-video-embeddings.py`, which maps to no test today.
- **`test_whitelist_migrations.py` (164-167):** add `ann_ids.py`. Correction to the requirements: `whitelist_migrations.py` is already mapped there (165), so no new entry is needed for it.
- **`test_video.py` (158-163):** add `ann_ids.py` and `sync-whitelist.py`.
- **`test_repair_video_channel_names.py` (173-175):** add `sync-whitelist.py`.

**Limit:** conftest's import makes every active test depend on `ann_ids.py`, `moderation.py` and `similarity_cache.py`, which change-based selection does not express.

**Not to touch:** `tests/last_test_validation.json` is regenerated by the run.

**Risk:** low.
</impact>
<impact path="scripts/run-dataset-build.sh" element="sync stage (227-228), embeddings stage (235-237); no change">
**No code change.** An unmigrated `whitelist.db` fails at the sync stage on the exact check, or at `--from embeddings` with the old-shape message. `DATA_BUILD.md:166` already says the script does not migrate.

**Risk:** low.
</impact>
<impact path="scripts/run-reembed.sh" element="--model-name AST read (139-155); detached build">
**No change,** provided `--model-name` keeps a literal default. A refusal shows only in the detached build's log.

**Risk:** low.
</impact>
<impact path="scripts/worktree-setup.sh" element="lines 27-28: symlinks whitelist.db, similarity-cache.db, whitelist-video-embeddings.faiss and .faiss.json to main's files">
**No change. Operational hazard:** in a worktree, `engine/server/db/whitelist.db` is main's live DB. Any of these, run from the worktree before merge, rewrites main's live DB, which main's code then cannot write (one-way):
- `migrate-whitelist.py` with its default `--db`;
- the smoke test with its default `--source-db`;
- a manual sync or build against the default path.

Every test of the migration must use tmp DBs.

**Uncertain:** Glob could not see the symlinked files in this worktree, probably because they are gitignored, so whether they are present here is unconfirmed.

**Risk:** high operationally if ignored; none in code.
</impact>
<impact path="scripts/deploy-bluegreen.sh" element="start-other-instance, readiness and switch flow (165-307); deploy lock">
**No change. New operational impact:** in prod the Engine is two `peertube-engine@7070`/`@7071` instances behind the nginx snippet. A deploy starts the idle instance and waits for `/api/health`.

So the plan's one-time step "stop the Engine, migrate, start the Engine" must mean, in prod:
1. stop the active instance named by the snippet, and stop or disable the updater timer;
2. make sure no deploy runs: the migration does not take `engine/server/db/engine-deploy.lock`;
3. migrate;
4. start the same instance, matching DATA_BUILD 172's existing "restart through `deploy-bluegreen.sh --blue-green`".

A deploy fired during the migration would start an instance whose start-up DDL (`data/videos.py:28`) and random-cache build contend with the migration's write lock.

**Risk:** medium operationally; none in code.
</impact>
<impact path="engine/install-updater-service.sh" element="systemd timer OnCalendar (line 366)">
**No change.** The updater runs from its own timer (Fri 20:00 per DEPLOYMENT.md:100), independent of the Engine, so "stop the Engine" does not stop it.
- A cycle fired during the migration fails its merge after the 10 s `busy_timeout`.
- A cycle fired between deploy and migration crawls and embeds staging, then is refused at merge.

The runbook must stop the timer and restart it after the Engine.

**Risk:** low in code, medium operationally.
</impact>
<impact path="engine/crawler/schema.sql" element="crawl schema (no video_embeddings); out of scope">
**No change.** It defines no `video_embeddings`, so sync's `_load_schema_columns` never parses one, staging starts without the table, and `EMBEDDING_COLUMNS` stays hand-maintained.

**Risk:** none.
</impact>
<impact path="CONTEXT.md" element="ANN id glossary entry (line 12)">
**No change.** The entry describes the end state that plan B delivers ("the id an embedded video carries in the FAISS index and the random cache"). Until plan B it is ahead of the code.

**Risk:** none.
</impact>
<impact path="docs/project/adr/0006-derived-ann-ids.md" element="Decision 3 and Consequences (line 22)">
**No change required.** Decision 3 (an id of 0 counts as a collision) is enforced by the CHECK. Line 22's "table rebuild ... and an index rebuild before the Engine starts" describes the combined cutover; plan A alone needs no index rebuild. Optionally note the 41/42 split.

**Risk:** none.
</impact>
<impact path="docs/project/roadmap.md" element="F1-M2 entry (line 45)">
**No change.** The issue stays open until plan B.

**Risk:** none.
</impact>
<impact path="docs/project/issues/08-stable-ann-ids.md" element="Comments; Status line (3)">
**At close:** add a dated comment that plan A (plan 41, build 43) delivered the column, the guards, the migration and the writers. The status stays `enhancement, ready-for-agent`; plan B closes the issue. The agent brief still names plan 17; line 82 already records the split.

**Risk:** none.
</impact>
</impacts>

## Documentation to update

- [ ] `DATA_BUILD.md` - - **Line 155:** sync copies `video_embeddings` with `ann_id` when the source has the column, and computes it when the source has embeddings without it. A normal crawl DB has no `video_embeddings`, so the embeddings stage fills the table.
- **Line 159:** "match that schema exactly, plus the whitelist-only `popularity` column" must also name `video_embeddings.ann_id`. An unmigrated DB fails with "missing columns: ann_id" plus the `migrate-whitelist.py` pointer.
- **Line 166:** "The migration is additive ... without touching rows ... a second run does nothing" is false for `video_embeddings`. It now rebuilds the table, keeps rowids, is one-way, and a second run does nothing only once `ann_id` exists.
- **Lines 168-172, upgrade order:** add the one-time step:
  1. Run it from main after merge, never from a worktree.
  2. Stop the updater timer and the Engine. In prod that is the active `peertube-engine@<port>`, with no deploy running.
  3. Run `migrate-whitelist.py` and keep the default backup: it is the only rollback, and it is read into RAM.
  4. Start the Engine (prod: `deploy-bluegreen.sh --blue-green`), then the timer.
  - Space: about 1.4 GB plus the roughly 3.5 GB backup, more in WAL mode.
  - No index rebuild is needed until plan B.
  - `build-video-embeddings.py` and the merge also refuse an unmigrated DB.
- **Line 191:** point the stable-ANN-ids note at the one-time step, and at plan B for the index rebuild.
- **Line 197:** "The update is already committed by then" becomes wrong once the sync FTS helpers stop committing. Either a failed rebuild rolls back the update but leaves the `videos_fts_*` triggers dropped until a re-run, or, if Step 5 adds BEGIN, a failed rebuild leaves the DB as it was.
- **Lines 314-319 (VACUUM):** after the migration the file keeps about 1.4 GB of freed pages. Until plan B a VACUUM may renumber `video_embeddings` rowids, so rebuild the ANN index after any VACUUM.
- [ ] `DEPLOYMENT.md` - - **Line 42:** add the one-time `video_embeddings` migration before the first dataset build or updater run on the new code. Stop the updater timer and the active Engine instance, with no deploy running; run `migrate-whitelist.py`; start the Engine and the timer. Point to `DATA_BUILD.md`.
- **Triage table (near line 216):** add a row.
  - **Symptom:** `sync-whitelist.py`, `build-video-embeddings.py` or the updater's merge exits with "video_embeddings has no ann_id column" or "missing columns: ann_id".
  - **Fix:** run `migrate-whitelist.py` on `whitelist.db`; for staging, re-run the updater without `--resume-staging`.
- **Optional row:** "video_embeddings ann_id collision" stops the run; recovery is manual (ADR-0006).
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - - **Prerequisite:** run `migrate-whitelist.py` on prod once, with the timer stopped.
- **Step 8 (line 58):** the merge refuses an unmigrated `main.` or `stage.` `video_embeddings` before its transaction opens, and a collision aborts the whole merge.
- **`--resume-staging` (lines 48, 149-151, 186):** a pre-migration staging DB fails at the build stage and must be recreated by running without the flag.
- **Line 168:** "no CPU fallback" contradicts `run_with_cpu_fallback`. A refusal in `--gpu` mode is logged as a GPU failure and retried on CPU.
- **Line 197:** `--inject-replace-embedding-for-test` keeps the row's derived `ann_id`.
- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - **Line 27:** the source DB must already be migrated, because mini-prod copies its `video_embeddings` DDL; an unmigrated source fails with the migrate message. In a worktree the default source is main's live DB through the symlink. Mini-prod gets the `ann_id` collision guards, so the merge runs guarded.
- [ ] `engine/server/README.md` - **Line 9:** next to the `videos.language` requirement, add that the writer jobs (sync, `build-video-embeddings`, the merge) also need `migrate-whitelist.py`'s `video_embeddings.ann_id` step. The Engine reads no `ann_id` until plan B.
- [ ] `docs/project/issues/08-stable-ann-ids.md` - **At close:** add a dated comment that plan A (plan 41, build 43) delivered the column, the guards, the migration and the writers. The status stays open; plan B closes the issue.

## Implementation plan

## Draft implementation: plan 41 (plan A), derived `ann_id` in the schema and the writers

I made two passes against the plan and the requirements, and they converged without needing an operator decision. Before drafting I read these files: `data/moderation.py` (1-75), all of `whitelist_migrations.py`, `migrate-whitelist.py` (1-35), `sync-whitelist.py` (1-660), `build-video-embeddings.py` (1-290), all of `merge-staging-db.py`, `merge_rules.json`, `updater-worker.py` (1-45, 1015-1070), the smoke test (20-40, 195-345), all of `repair-video-channel-names.py`, `conftest.py` (1-60), `test_whitelist_migrations.py`, `test_video.py` (40-64, 525-554), `embedding_space.py` (40-94) and `tests/config.json` (150-184). The FTS SQL constants are used nowhere outside `sync-whitelist.py` except in plan docs (checked with grep).

### Step 5 decisions

- **`ANN_ID_SOURCE` waits for plan B.** Nothing in plan A reads it (rung 1).
- **`repair-video-channel-names.py` gets one `conn.execute("BEGIN")`.** It goes after `has_videos_fts`, before the trigger drop. This one line removes the failure state the impact names, where triggers are dropped but nothing is committed. The drop, update, recreate and rebuild then commit or roll back together. `DATA_BUILD.md:197` becomes "a failed rebuild leaves the DB as it was".
- **The SQL function is named `compute_ann_id`.** That is the Python name. It is deliberately not `ann_id`, so that `ann_id(video_id, instance_domain)` cannot be misread as the column.
- **The registration helper takes an optional `func`.** The migration passes a lambda that resolves `ann_id_of` at call time, which keeps the stub hook live. Sync passes nothing.
- **The pinned AC1 literal is not in this draft.** I have no way to execute code in this step. The implementer computes the value with a one-off stdlib command that does not use the helper, and pastes it in: `python3 -c "import hashlib; print(int.from_bytes(hashlib.blake2b(b'abc::peertube.example', digest_size=8).digest(), 'big') & ((1 << 63) - 1))"`.

### Module map

| Path | Change | AC |
|---|---|---|
| `engine/server/data/ann_ids.py` | new | AC1, AC2 |
| `engine/server/data/moderation.py` | one comment line above `normalize_host` | AC1 |
| `engine/server/db/jobs/whitelist_migrations.py` | path header, import, `ann_id_of`, `migrate_video_embeddings_schema`, last call in `migrate_whitelist_schema` | AC2, AC-A4 |
| `engine/server/db/jobs/migrate-whitelist.py` | docstring line 2 only | AC2 |
| `engine/server/db/jobs/build-video-embeddings.py` | import, `init_schema`, row tuple, INSERT | AC3 |
| `engine/server/db/jobs/sync-whitelist.py` | import, `TARGET_EMBEDDING_COLUMNS`, exact check, FTS constants and helpers, `ensure_content_schema`, `rebuild_content_tables` | AC2, AC3 |
| `engine/server/db/jobs/repair-video-channel-names.py` | `BEGIN`, rat-tail, docstrings | consequence of the helper change |
| `engine/server/db/jobs/merge-staging-db.py` | import, two checks inside `try` | AC2, AC3 |
| `engine/server/db/jobs/updater-worker.py` | import, inject INSERT, docstring | AC3 |
| `engine/server/db/jobs/tests/test-orchestrator-smoke.py` | import, one call after the table copy loop | AC-A9 |
| `tests/active/conftest.py` | append `engine/server`, re-export `compute_ann_id` | tests |
| `tests/active/test_ann_ids.py` | new | AC1-AC3 |
| `tests/active/test_whitelist_migrations.py` | new cases, docstring | AC2, AC-A4 |
| `tests/active/test_video.py` | two inserts get explicit columns and `ann_id` | tests |
| `tests/config.json` | mappings | tests |
| Docs | see the last section | AC-A9 |

---

### 1. `engine/server/data/ann_ids.py` (new)

The ladder: `hashlib.blake2b` comes from the stdlib (rung 3). The UNIQUE index, the CHECK and the trigger are native SQLite features (rung 4). `normalize_host` is reused from this codebase (rung 2).

```python
"""Derive the stable ANN id of a video and hold the shared video_embeddings definition and its guards."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Callable

from data.moderation import normalize_host

ANN_ID_SQL_FUNCTION = "compute_ann_id"
ANN_ID_MASK = (1 << 63) - 1

ANN_ID_INDEX_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)"
# Plain SQL, no registered function, so the sqlite3 CLI and Engine connections can still insert; BEFORE fires ahead of OR REPLACE resolution, so the holder's row survives.
ANN_ID_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision
BEFORE INSERT ON video_embeddings
WHEN EXISTS (
  SELECT 1 FROM video_embeddings
  WHERE ann_id = NEW.ann_id
    AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)
)
BEGIN
  SELECT RAISE(ABORT, 'video_embeddings ann_id collision: another (video_id, instance_domain) holds this ann_id');
END
"""


def compute_ann_id(video_id: str, instance_domain: str | None) -> int:
    """Return the 63-bit blake2b id of `video_id::normalized host`; the same key gives the same id in any process and DB."""
    host = normalize_host(instance_domain)
    if host is None:
        host = str(instance_domain).strip().lower()
    digest = hashlib.blake2b(f"{video_id}::{host}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ANN_ID_MASK


def register_ann_id_function(conn: sqlite3.Connection, func: Callable[[str, str], int] = compute_ann_id) -> None:
    """Register `func` as the deterministic SQL function compute_ann_id(video_id, instance_domain)."""
    conn.create_function(ANN_ID_SQL_FUNCTION, 2, func, deterministic=True)


def create_video_embeddings_table(conn: sqlite3.Connection, table: str = "video_embeddings") -> None:
    """Create `table` from the shared video_embeddings definition unless it exists; a rowid table, columns in this order."""
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
    """Create the UNIQUE ann_id index and the collision trigger on main.video_embeddings, which must already carry ann_id."""
    conn.execute(ANN_ID_INDEX_SQL)
    conn.execute(ANN_ID_TRIGGER_SQL)


def assert_video_embeddings_has_ann_id(conn: sqlite3.Connection, schema: str = "main") -> None:
    """Raise unless {schema}.video_embeddings carries ann_id; a missing table passes."""
    columns = [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info(video_embeddings)")]
    if columns and "ann_id" not in columns:
        raise RuntimeError(
            f"{schema}.video_embeddings has no ann_id column; it predates the stable ANN ids. "
            "Run engine/server/db/jobs/migrate-whitelist.py on this database; a staging DB reused "
            "with --resume-staging must instead be recreated by running the updater without it."
        )


def ensure_video_embeddings_schema(conn: sqlite3.Connection) -> None:
    """Create video_embeddings from the shared definition, refuse an old-shape table, then create the guards; never commits."""
    create_video_embeddings_table(conn)
    assert_video_embeddings_has_ann_id(conn)
    create_ann_id_guards(conn)
```

**Invariants**
- **Fixed derivation.** The hash input, byte order, mask and fallback are exactly the ones AC1 specifies. `compute_ann_id` never raises, because a None domain falls back to `"none"`. It never probes for another id. It can return 0, and the CHECK refuses that.
- **Every DDL statement goes through `conn.execute`, one statement per call.** Python's legacy isolation opens no implicit transaction for DDL, so these calls join a transaction the caller already has open and autocommit otherwise.
- **Guards follow the check.** `create_ann_id_guards` runs only after `ann_id` is confirmed present, so an old table gets the AC2 message and never a raw `no such column: ann_id`.
- **Positional row reads.** The check reads `row[1]`, which works under the `sqlite3.Row` factory that merge and sync use.
- **Schema resolution.** An unqualified `video_embeddings` in a non-TEMP trigger body resolves to the trigger's own schema. The guards are always created on `main` of the connection that owns the DB.
- **Collision error type.** `RAISE(ABORT, …)` returns SQLITE_CONSTRAINT, which Python surfaces as `sqlite3.IntegrityError`.

**Guard limit.** The guard refuses an id that another key already holds. It does not check that a copied id equals `compute_ann_id`.

### 2. `engine/server/data/moderation.py`

Above `def normalize_host` (line 44), add one line:

```python
# Part of the ANN id contract (data/ann_ids.compute_ann_id): any change to this output re-keys every stored ann_id.
```

### 3. `engine/server/db/jobs/whitelist_migrations.py`

**Header**, which replaces `import sqlite3`:

```python
import sqlite3
import sys
from pathlib import Path

server_dir = Path(__file__).resolve().parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.ann_ids import ANN_ID_SQL_FUNCTION, compute_ann_id, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function

# Looked up at call time by migrate_video_embeddings_schema so a test can monkeypatch it.
ann_id_of = compute_ann_id
```

**New step**, placed before `migrate_whitelist_schema`:

```python
def migrate_video_embeddings_schema(conn: sqlite3.Connection) -> None:
    """Rebuild video_embeddings with the derived, guarded ann_id column, keeping every row's rowid.

    Unlike the executescript rebuilds above, this runs in one explicit transaction: the backfill can fail (a zero id at the CHECK, a collision at the UNIQUE index) and must then leave the six-column table and its rows as they were. Rowids are copied by name so a rowid-keyed ANN index and random cache built before the migration still resolve to the same videos.
    """
    if not _table_exists(conn, "video_embeddings"):
        return
    if "ann_id" in _columns(conn, "video_embeddings"):
        return
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        register_ann_id_function(conn, lambda video_id, instance_domain: ann_id_of(video_id, instance_domain))
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
        create_ann_id_guards(conn)
    except Exception:
        conn.rollback()
        raise
    conn.commit()
```

**`migrate_whitelist_schema`** gains a final line, `migrate_video_embeddings_schema(conn)`, after `migrate_videos_language(conn)`.

**How it behaves**

| Case | Result |
|---|---|
| Table missing (including right after `migrate_videos_schema` dropped it) | Early return; no commit, no transaction. |
| Table already has `ann_id` | Early return; a second run changes nothing. |
| A zero id | The CHECK fails during the INSERT, then rollback. |
| A collision | The UNIQUE index build inside `create_ann_id_guards` fails, then rollback. The old six-column table and its rows come back, and `video_embeddings_new` is gone. The trigger did not exist during the copy, so the index is what catches a backfill collision. |

Python's own implicit BEGIN never fires inside this block, because `in_transaction` is already true after the explicit `BEGIN`. `migrate-whitelist.py`'s `with conn:` then has nothing left to commit.

### 4. `engine/server/db/jobs/migrate-whitelist.py`

Line 2 becomes: `"""Migrate an existing whitelist.db to the latest schema in place; additive except video_embeddings, which is rebuilt once to add ann_id."""`. No logic change.

### 5. `engine/server/db/jobs/build-video-embeddings.py`

```python
from scripts.cli_format import CompactHelpFormatter
from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema


def init_schema(conn: sqlite3.Connection) -> None:
    """Create video_embeddings from the shared definition, refusing a table that predates ann_id."""
    ensure_video_embeddings_schema(conn)
    conn.commit()
```

**Row tuple.** It gains a final element, `compute_ann_id(video_id, instance_domain),`.

**INSERT:**

```python
            INSERT OR REPLACE INTO video_embeddings
              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
```

**Unchanged:** `--model-name`, `--force` and the per-batch commit.

**Behaviour:**
- `init_schema` still runs after the heavy imports but before the CUDA check and the model load, so an old shape is refused before the model loads.
- `--force` rewrites every key with the same id.

### 6. `engine/server/db/jobs/sync-whitelist.py`

**Import** at line 26: `from data.ann_ids import ANN_ID_SQL_FUNCTION, create_ann_id_guards, create_video_embeddings_table, register_ann_id_function`.

**Columns**, after `EMBEDDING_COLUMNS`:

```python
# The derived ANN id exists only in the whitelist DB (data/ann_ids.py): it belongs in the exact check against `main.video_embeddings`, but a crawl DB's embeddings need not carry it, so `EMBEDDING_COLUMNS` stays the source superset.
TARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + ["ann_id"]
```

**Exact check.** Line 194 becomes `_assert_columns_exact(conn, "video_embeddings", TARGET_EMBEDDING_COLUMNS)`. An old target now fails with "Schema mismatch for video_embeddings (missing columns: ann_id). Run `engine/server/db/jobs/migrate-whitelist.py` …".

**FTS constants.** They become tuples of whole statements, keeping the same names and the same trigger names. A trigger body with internal `;` counts as one statement for `conn.execute`:

```python
VIDEOS_FTS_TRIGGERS_SQL = (
    """CREATE TRIGGER IF NOT EXISTS videos_fts_ai AFTER INSERT ON videos BEGIN
  INSERT INTO videos_fts (rowid, title, description, tags_json, category, channel_name)
  VALUES (new.rowid, new.title, new.description, new.tags_json, new.category, new.channel_name);
END""",
    """CREATE TRIGGER IF NOT EXISTS videos_fts_ad AFTER DELETE ON videos BEGIN
  INSERT INTO videos_fts (videos_fts, rowid, title, description, tags_json, category, channel_name)
  VALUES ('delete', old.rowid, old.title, old.description, old.tags_json, old.category, old.channel_name);
END""",
    """CREATE TRIGGER IF NOT EXISTS videos_fts_au AFTER UPDATE ON videos BEGIN
  INSERT INTO videos_fts (videos_fts, rowid, title, description, tags_json, category, channel_name)
  VALUES ('delete', old.rowid, old.title, old.description, old.tags_json, old.category, old.channel_name);
  INSERT INTO videos_fts (rowid, title, description, tags_json, category, channel_name)
  VALUES (new.rowid, new.title, new.description, new.tags_json, new.category, new.channel_name);
END""",
)

VIDEOS_FTS_DROP_TRIGGERS_SQL = (
    "DROP TRIGGER IF EXISTS videos_fts_ai",
    "DROP TRIGGER IF EXISTS videos_fts_ad",
    "DROP TRIGGER IF EXISTS videos_fts_au",
)


def create_videos_fts_triggers(conn: sqlite3.Connection) -> None:
    """Create the triggers that keep videos_fts in step with videos, inside the caller's transaction (no commit)."""
    for statement in VIDEOS_FTS_TRIGGERS_SQL:
        conn.execute(statement)


def drop_videos_fts_triggers(conn: sqlite3.Connection) -> None:
    """Drop the videos_fts triggers, inside the caller's transaction (no commit).

    Used around a bulk reload, where per-row trigger work is pure waste: the wholesale
    delete and re-insert would fire one index write per row in each direction, and the
    `rebuild` that follows discards all of it anyway.
    """
    for statement in VIDEOS_FTS_DROP_TRIGGERS_SQL:
        conn.execute(statement)
```

**`ensure_content_schema`:**
- Delete the inline `CREATE TABLE IF NOT EXISTS video_embeddings (...)` block (385-394) from the `executescript`.
- Between the `executescript` and `create_videos_fts_triggers(conn)`, add:

```python
    create_video_embeddings_table(conn)
    # An old-shape table gets no guards here; ensure_schema_compatibility refuses it next with the migrate pointer.
    if "ann_id" in _table_columns(conn, "video_embeddings"):
        create_ann_id_guards(conn)
```

- In the docstring, add one sentence noting that `video_embeddings` comes from `data/ann_ids.py`'s shared definition.

**`rebuild_content_tables`.** This replaces the embeddings block (493-510):

```python
    if source_embedding_columns.issuperset(EMBEDDING_COLUMNS):
        source_columns = ", ".join(EMBEDDING_COLUMNS)
        if "ann_id" in source_embedding_columns:
            ann_id_expr = "ann_id"
        else:
            register_ann_id_function(conn)
            ann_id_expr = f"{ANN_ID_SQL_FUNCTION}(video_id, instance_domain)"
        target_columns = ", ".join(TARGET_EMBEDDING_COLUMNS)
        conn.execute(
            f"""
            INSERT INTO video_embeddings ({target_columns})
            SELECT {source_columns}, {ann_id_expr}
            FROM {SOURCE_SCHEMA}.video_embeddings
            WHERE (video_id, instance_domain) IN (
              SELECT video_id, instance_domain FROM videos
            );
            """
        )
```

**Transaction.** Inside `main()`'s `with conn:`, the first DML is `sync_hosts`' INSERT, which opens the implicit transaction. Everything after it joins that transaction:
- the trigger drop
- the DELETEs and the reload, where the trigger fires once per embedding row
- the trigger recreate
- the FTS rebuild

A collision's IntegrityError leaves `with conn:` through the exception path and rolls all of it back, `instances` included. The `executescript` in `ensure_moderation_schema` and `ensure_content_schema` still commits at the top of the block, before any data is written, as it does today.

### 7. `engine/server/db/jobs/repair-video-channel-names.py`

In `repair_channel_names`, the rat-tail at line 58 is replaced, and one line is added before `sync = _load_sync_whitelist()`:

```python
    # One transaction: the sync helpers run their SQL through conn.execute, so the trigger drop, the update, the recreate and the rebuild commit together below, and a failed count check leaves the DB as it was (main closes without committing).
    conn.execute("BEGIN")
```

**Docstrings.** In the line 52 docstring, "commit" now applies to all four steps together. The module docstring (line 4) gains "in the same transaction" after "the index is rebuilt afterwards".

**Test impact.** The existing test calls the helpers directly after commits, where they autocommit, so it is unaffected.

### 8. `engine/server/db/jobs/merge-staging-db.py`

Import, after `CompactHelpFormatter`: `from data.ann_ids import assert_video_embeddings_has_ann_id`. Then, at the top of `try:`:

```python
    try:
        # Refuse an unmigrated side before the write lock: either one would drop or reject ann_id in the shared-column copy.
        assert_video_embeddings_has_ann_id(conn, "main")
        assert_video_embeddings_has_ann_id(conn, "stage")
        conn.execute("BEGIN IMMEDIATE")
```

**Failure path.** The existing `except` rolls back, which is a no-op because no transaction is open, and re-raises. `finally` detaches the staging DB and closes the connection. The process exits non-zero with a message naming `main.` or `stage.`.

**Rule loop.** It is unchanged. `merge_columns` picks up `ann_id` on both sides. Main's trigger refuses a staged id that another prod key holds, and the whole merge rolls back.

### 9. `engine/server/db/jobs/updater-worker.py`

**Import.** Add `from data.ann_ids import compute_ann_id` immediately before `from data.moderation import (`.

**Inject.** The docstring becomes `"""Insert one overlapping embedding row into staging with modified payload and the same ann_id."""`. The INSERT becomes:

```python
            INSERT OR REPLACE INTO video_embeddings
              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id)
            VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
```

The parameter tuple gains `compute_ann_id(video_id, instance_domain)`.

The INSERT resolves to staging's `main`. The key is the same, so the trigger lets it through.

### 10. `engine/server/db/jobs/tests/test-orchestrator-smoke.py`

**Import**, after the `data.similarity_cache` import: `from data.ann_ids import ensure_video_embeddings_schema`.

**After the `for table in (...)` loop** at line 267:

```python
        # Only table and index DDL is copied (the videos_fts_* triggers would arrive without videos_fts); the ann_id guards are the one trigger mini-prod needs, so its merge runs guarded. An unmigrated source is refused here.
        ensure_video_embeddings_schema(conn)
```

**How the existing steps interact with it:**
- **Index already copied.** The index copied from the source already exists, so the guard's `IF NOT EXISTS` does nothing.
- **Trigger and column order.** The trigger is created before the `SELECT e.*` copy and fires for each copied row. That copy relies on the source's column order, which is the shared order.

### 11. Tests

#### `tests/active/conftest.py`

After line 45:

```python
# Appended, not inserted, so client/backend's `server` and `lib` stay first; the test modules' guarded engine/server inserts become no-ops.
ENGINE_SERVER_DIR = ROOT / "engine" / "server"
if str(ENGINE_SERVER_DIR) not in sys.path:
    sys.path.append(str(ENGINE_SERVER_DIR))
from data.ann_ids import compute_ann_id  # noqa: E402,F401
```

The module docstring gains one line: "`compute_ann_id` is re-exported from `engine/server/data/ann_ids.py` for tests that seed `video_embeddings`."

#### `tests/active/test_ann_ids.py` (new)

The module docstring is the spec, one bullet per case. It describes the guard as one that "refuses an id another key holds" and never as one that "verifies ids".

**Fixtures:**
- A `_db(tmp_path)` with a minimal `videos (video_id, instance_domain, PRIMARY KEY …)` table and `ensure_video_embeddings_schema`.
- `_load_job` copied from `test_whitelist_migrations.py`.

**AC1:**
- `test_compute_ann_id_is_deterministic`.
- `test_ids_are_positive_int64`: 300 keys, each id in `1..2**63-1`.
- `test_pinned_value`: `compute_ann_id("abc", "peertube.example") == <literal>`, using the literal from the stdlib one-liner in the Step 5 decisions.
- `test_host_is_normalised`: `"Peertube.Example."` gives the same id as `"peertube.example"`.
- `test_unparsable_domain_falls_back`. For `"..."` and for `"bad host"`, the result:
  - equals a stdlib blake2b over `f"v::{domain.strip().lower()}"`, computed in the test;
  - is the same on a repeat call;
  - does not raise.

**AC2 schema:**
- **Zero id.** `ann_id` 0 raises `IntegrityError`.
- **Plain INSERT of another key's id.** Raises `IntegrityError`, and the holder row is unchanged.
- **Same collision under `INSERT OR REPLACE`.** Raises `IntegrityError`; the holder row is unchanged and the row count is the same.
- **Same-key `INSERT OR REPLACE` with a new payload.** Gives the same row count and the same `ann_id`.
- **UPDATE to a taken id.** Raises `IntegrityError` (UNIQUE).

**AC2 old shape:**
- **Six-column table.** `assert_video_embeddings_has_ann_id` raises `RuntimeError`, and the message contains `main.video_embeddings`, `migrate-whitelist.py` and `--resume-staging`.
- **Attached as `stage`.** The message names `stage.video_embeddings`.
- **Missing table.** Nothing happens.
- **`ensure_video_embeddings_schema` on a six-column table.** Raises the same `RuntimeError`, not `OperationalError`.

**Merge**, run as a subprocess: `[sys.executable, JOBS_DIR / "merge-staging-db.py", "--prod-db", …, "--staging-db", …]`.
- **Fixture DBs.** Each tmp DB gets `instances`, `channels` and `videos` through `sync-whitelist`'s `ensure_whitelist_schema`/`ensure_content_schema`. Those also create `video_embeddings` in the new shape with guards.
- **Old shape.** For an old-shape side, `DROP TABLE video_embeddings` is followed by a literal six-column CREATE.
- **Cases:**
  - Old stage: non-zero exit, `stage.video_embeddings` in stderr.
  - Old main: non-zero exit, `main.video_embeddings`.
  - **Collision.** Prod holds (v1, h) with its real id. Stage has videos v1 and v2, and its `video_embeddings` is created with `create_video_embeddings_table` only, with no guards, as a hand-doctored staging DB would be. The stage row (v2, h) carries v1's id. Expect a non-zero exit, and prod's `video_embeddings` and `videos` rows byte-identical to before.
  - **Normal merge.** It carries `ann_id` across, and `ann_id == compute_ann_id(key)` for each row.

**Sync**, using `sync-whitelist.py` loaded through `_load_job`.
- **Fixture DBs.**
  - Target: `ensure_whitelist_schema` and `ensure_content_schema`.
  - Source: a tmp DB built by `executescript` of `engine/crawler/schema.sql`, plus a `video_embeddings` table in the six-column or the seven-column shape. It is attached as `source`.
- **Cases.** Each one calls `rebuild_content_tables(conn, {host})` and then commits.
  - Source without `ann_id`: each target row has `ann_id == compute_ann_id(key)`.
  - Source with `ann_id`: the id is copied.
- **`ensure_schema_compatibility`:**
  - It passes on a new target.
  - On a target whose `video_embeddings` is the six-column table, it raises with both `missing columns: ann_id` and `migrate-whitelist.py`.

**Updater.** Load `updater-worker.py` in-process.
- Fixture: a prod and a staging tmp DB, each prepared with `ensure_video_embeddings_schema`, holding one same-key row.
- Call `inject_replace_embedding_for_test(prod, staging)`.
- Expect: it returns True; the staging row's `ann_id` equals `compute_ann_id(key)`; the embedding is mutated.

#### `tests/active/test_whitelist_migrations.py`

**New constant**, `OLD_VIDEO_EMBEDDINGS_SQL`. This is the literal six-column table (PK and FK, no `ann_id`), in the style of `PRE_LANGUAGE_VIDEOS_SQL`.

**Fixture:**
1. `executescript(OLD_VIDEO_EMBEDDINGS_SQL)`.
2. `ensure_whitelist_schema` and `ensure_content_schema`. The table already exists, so no guards are created on it.
3. Seed videos v1, v2 and v3.
4. Insert three embeddings with explicit rowids 2, 5 and 9 and distinct blobs.
5. Commit.

**Cases:**
- `test_migration_adds_ann_id_keeping_rowids`. After `migrate_whitelist_schema(conn, "instances")`:
  - `ann_id` is NOT NULL;
  - `SELECT rowid, video_id, instance_domain, embedding` matches the seeded rows exactly;
  - `ann_id == compute_ann_id(v, h)` per row;
  - `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision` are in `sqlite_master`;
  - a second run leaves `table_info`, the rows and `sqlite_master` identical.
- `test_migration_without_video_embeddings_is_a_no_op`. A DB with no table: `migrate_video_embeddings_schema` returns, no table appears, and `conn.in_transaction` is False.
- `test_failed_backfill_rolls_back`. `monkeypatch.setattr(migrations, "ann_id_of", lambda video_id, instance_domain: 7)`. Then:
  - `pytest.raises(sqlite3.IntegrityError)`;
  - the columns are the six old ones;
  - all three `(rowid, …)` rows are present;
  - there is no `video_embeddings_new`, no `idx_video_embeddings_ann_id` and no trigger;
  - `conn.in_transaction` is False.
- **The existing language case stays as it is.** `ensure_content_schema` now creates the new shape, so the new step returns early.
- **Imports and docstring.** `compute_ann_id` is imported from conftest. The module docstring gains `video_embeddings` bullets.

#### `tests/active/test_video.py`

- Line 49 becomes `from conftest import ENGINE_PY, ROOT, compute_ann_id`.
- Lines 543-544 become explicit column lists:

```python
        conn.execute("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES ('v1', ?, ?, 4, 'm', 'now', ?)", (HOST, array("f", [1, 0, 0, 0]).tobytes(), compute_ann_id("v1", HOST)))
        conn.execute("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES ('v2', ?, ?, 4, 'm', 'now', ?)", (HOST, array("f", [0.8, 0.6, 0, 0]).tobytes(), compute_ann_id("v2", HOST)))
```

`similars_stack` stays on rowid.

#### `tests/config.json`

- **New group** `"test_ann_ids.py"`, mapped to:
  - `engine/server/data/ann_ids.py`
  - `engine/server/data/moderation.py`
  - `engine/server/db/jobs/sync-whitelist.py`
  - `engine/server/db/jobs/merge-staging-db.py`
  - `engine/server/db/jobs/updater-worker.py`
- **`test_whitelist_migrations.py`:** add `engine/server/data/ann_ids.py`. `whitelist_migrations.py` is already mapped.
- **`test_video.py`:** add `engine/server/data/ann_ids.py` and `engine/server/db/jobs/sync-whitelist.py`.
- **`test_repair_video_channel_names.py`:** add `engine/server/db/jobs/sync-whitelist.py`.
- **`build-video-embeddings.py` stays unmapped.** No test runs it end to end.

### 12. Docs

Each doc edit follows the settled list.

**`DATA_BUILD.md`**
- **155:** sync copies `ann_id`, or computes it.
- **159:** the exact check includes `video_embeddings.ann_id`.
- **166:** the migration is not additive for `video_embeddings`. It is a rebuild that keeps rowids and is one-way.
- **168-172:** the one-time step:
  1. run it from main, never from a worktree;
  2. stop the updater timer and the active Engine instance, with no deploy running;
  3. run `migrate-whitelist.py` with the default backup, which is the only rollback and is read into RAM;
  4. start the Engine through `deploy-bluegreen.sh --blue-green`, then the timer.
  - Space: about 1.4 GB plus about 3.5 GB of backup, more in WAL mode.
  - No index rebuild is needed until plan B.
- **191:** points at that step.
- **197:** with the repair job's `BEGIN`, a failed rebuild leaves the DB as it was.
- **314-319:** about 1.4 GB of freed pages remain. A VACUUM may renumber rowids, so rebuild the ANN index after one.

**`DEPLOYMENT.md`**
- **42:** the one-time step.
- **Triage row.**
  - Symptom: "video_embeddings has no ann_id column" or "missing columns: ann_id".
  - Fix: run `migrate-whitelist.py`; for staging, re-run without `--resume-staging`.
- **Collision row.** "video_embeddings ann_id collision" stops the run, and recovery is manual (ADR-0006).

**`UPDATER_WORKER.md`**
- the migration as a prerequisite;
- step 8: the merge refuses an unmigrated main or stage before its transaction opens, and a collision aborts the whole merge;
- `--resume-staging` (48, 149-151, 186): a pre-migration staging DB fails and must be recreated;
- 168: the CPU-fallback correction;
- 197: the inject keeps `ann_id`.

**`ORCHESTRATOR_SMOKE_TEST.md`**
- 27: the `--source-db` must be migrated.
- In a worktree, the default source is main's live DB.
- Mini-prod gets the guards.

**`engine/server/README.md`**
- 9: the writer jobs need the `ann_id` step.

**Issue 08**
- At close: a dated comment that plan A delivered.
- It stays open for plan B.

### Checked against the plan and the requirements

**AC1**
- `ann_ids.py` is stdlib plus `data.moderation`.
- Exact derivation, fallback and no raise.
- Every writer imports this one helper.

**AC2**
- **Table shape:** NOT NULL, CHECK, UNIQUE index `idx_video_embeddings_ann_id`, plain-SQL BEFORE trigger.
- **Old shape:** the RuntimeError text required by the requirements, the schema argument, and a no-op on a missing table.
- **Ordering:** CREATE, then check, then guards, each through `execute`.
- **Migration:** explicit `BEGIN`, rollback on failure, idempotent, called last, its own `sys.path` insert.

**AC3**
- **build-video-embeddings:** computes and inserts the id, and refuses an old table before the model loads.
- **merge-staging-db:** checks main and then stage inside `try` before `BEGIN IMMEDIATE`, and `merge_rules.json` is untouched.
- **sync-whitelist:** `TARGET_EMBEDDING_COLUMNS` drives the exact check, and `rebuild_content_tables` copies or computes the id. A collision rolls the whole sync back, now true because the helpers no longer commit.
- **updater-worker:** the test inject writes the id.
- **Same key, same id:** `--force` and REPLACE keep it.

**AC-A4.** `rowid` is named on both sides of the copy, and no reader changes.

**AC-A9.** The smoke test's mini-prod guards come from `ensure_video_embeddings_schema` after the copy loop, with no other triggers copied. The docs carry the one-time step.

**Consistency.**
- CLIs are unchanged.
- Messages follow `embedding_space.py`'s style.
- Each file keeps its own style.
- No new dependency.

### Deliberate simplifications

| Simplification | Ceiling | Upgrade path |
|---|---|---|
| One module holds both the id and the `video_embeddings` DDL. | `ann_ids.py` knows that table's shape. | Split the DDL out if a second table ever needs derived ids. |
| The merge only checks shape and creates no guards. | A prod migrated by some tool other than `migrate-whitelist.py` would have the column but no trigger. | Call `create_ann_id_guards` in the merge, which the requirements currently forbid. |
| The guard checks uniqueness, not that the id is correct. | A wrong but unique id copied from staging or a sync source is accepted. | Add a `compute_ann_id` comparison on copy paths if one is ever needed. |

### Open risks carried forward

- **Empty-host sync.** When the host set is empty, whether `sync_hosts`' empty `executemany` opens the transaction is unverified. Nothing on that path can collide.
- **Build batches.** In `build-video-embeddings`, batches committed before a collision stay committed.
- **The migration is one-way.** Rolling back the code means restoring the backup.
- **Pinned literal.** The AC1 literal still has to be computed and pasted in by the implementer, as described in the Step 5 decisions.


### Phases

#### Phase 1 - Id derivation and schema guards [code]

**Files touched.** engine/server/data/ann_ids.py (NEW), engine/server/data/moderation.py (EDITED), tests/active/conftest.py (EDITED), tests/active/test_ann_ids.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the public functions of `engine/server/data/ann_ids.py`, entered directly (rung 1) in the new `tests/active/test_ann_ids.py`, against a tmp sqlite DB that has a minimal `videos` table. The table and guards come from `create_video_embeddings_table` + `create_ann_id_guards`; `ensure_video_embeddings_schema` arrives in phase 4. For clause_1 it asserts: `compute_ann_id("abc", "peertube.example")` equals the literal computed by the stdlib one-liner in the draft (this excludes a wrong separator, byte order or mask); two calls give the same id; 300 keys all give ids in 1..2**63-1; `"Peertube.Example."` gives the same id as `"peertube.example"` (this excludes skipping normalize_host); for `"..."` and for `"bad host"` the result equals a blake2b computed in the test over `v::<stripped, lowercased domain>`, and the call does not raise. For clause_2 it asserts: `ann_id` 0 raises IntegrityError; a plain INSERT of another key's id raises IntegrityError and the holder row is unchanged; the same collision under INSERT OR REPLACE raises IntegrityError, the holder row is unchanged and the row count is the same (this excludes a UNIQUE-only guard that silently deletes); a same-key INSERT OR REPLACE with a new payload keeps the row count and the `ann_id` (this excludes a guard that also blocks the same key); an UPDATE to a taken id raises IntegrityError.

**Intent.** `engine/server/data/ann_ids.py` derives one stable 63-bit id from each (video_id, normalised host), and the shared `video_embeddings` definition with its guards refuses an `ann_id` that is zero or that another key already holds.

- C1 - `compute_ann_id` returns the pinned blake2b-derived positive 63-bit value for a key: the same id for a host and its normalised form, and a non-raising fallback for an unparsable host.
- C2 - A `video_embeddings` table built from the shared definition and guards refuses a zero `ann_id`, and refuses another key's `ann_id` under INSERT, INSERT OR REPLACE and UPDATE, leaving the holder row unchanged.

**Outcome.** ### `engine/server/data/ann_ids.py` (NEW)
New module in `data/moderation.py`'s style: stdlib `hashlib` and `sqlite3`, plus `normalize_host`.
- `ANN_ID_MASK = (1 << 63) - 1`.
- `compute_ann_id(video_id, instance_domain)` hashes `video_id::normalize_host(instance_domain)` with blake2b at `digest_size=8`, reads the digest big-endian and masks it to 63 bits. When `normalize_host` rejects the domain, the trimmed, lowercased domain is hashed instead, so the function never raises.
- `create_video_embeddings_table(conn)` holds the one shared `CREATE TABLE IF NOT EXISTS video_embeddings` definition: the six existing columns, plus `ann_id INTEGER NOT NULL CHECK (ann_id > 0)`, with the existing primary key and foreign key.
- `create_ann_id_guards(conn)` creates two guards:
  - `idx_video_embeddings_ann_id`, a UNIQUE index that refuses a colliding UPDATE. Its name does not clash with `idx_video_embeddings_id_instance`, which `data/videos.py` drops.
  - `video_embeddings_ann_id_collision`, a plain-SQL BEFORE INSERT trigger. It raises ABORT when a row with a different `(video_id, instance_domain)` already holds `NEW.ann_id`. Because it runs before `OR REPLACE` resolves conflicts, the holder's row is never deleted.
- Every statement goes through `conn.execute`, so nothing commits inside a caller's transaction.
- Left for later phases, because this checkpoint doesn't use them: `register_ann_id_function` and its SQL name (phase 2's migration), and `assert_video_embeddings_has_ann_id` / `ensure_video_embeddings_schema` (phase 4).

### `engine/server/data/moderation.py` (EDITED)
One comment line above `normalize_host`, marking it as part of the ANN id contract: changing its output re-keys every stored `ann_id`. No code change.

### `tests/active/conftest.py`, `tests/active/test_ann_ids.py`, `tests/config.json` (not touched)
- Nothing in this phase's checkpoint goes through the conftest re-export of `compute_ann_id`. Its first users are later phases' tests, so it waits for them.
- `tests/active/test_ann_ids.py` is where this checkpoint will be promoted. Writing my own copy would duplicate it.
- A `test_ann_ids.py` group in `tests/config.json` would be an "unknown group" until that file exists. It belongs with the promotion, mapped to `engine/server/data/ann_ids.py` and `engine/server/data/moderation.py`.

### Probe (to delete)
I ran a probe, `tests/tmp/probe_ann_ids_impl.py`. It ends in `assert False` so that it prints its output.
- Seen: `compute_ann_id("abc", "peertube.example")` and the URL spelling both give 3578322927313005651. The fallbacks `"..."` and `"  Bad Host  "` give 2717215193390831227 and 9164601000067536921.
- Seen: a foreign id under both INSERT and INSERT OR REPLACE raises `sqlite3.IntegrityError` with the trigger's message, and the holder row `('v1', 111)` survives. An id of 0 raises `IntegrityError` (CHECK).
- I have no delete tool, so the operator should delete the probe file.

#### Phase 2 - Rowid-preserving ann_id migration [code]

**Files touched.** engine/server/db/jobs/whitelist_migrations.py (EDITED), engine/server/db/jobs/migrate-whitelist.py (EDITED), tests/active/test_whitelist_migrations.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: `migrate_whitelist_schema` / `migrate_video_embeddings_schema` on a tmp DB, entered through the existing `tests/active/test_whitelist_migrations.py` harness (`_load_job` plus the sync `ensure_*` fixtures, the `PRE_LANGUAGE_VIDEOS_SQL` precedent). The fixture holds an `OLD_VIDEO_EMBEDDINGS_SQL` six-column table with rowids 2, 5 and 9. For clause_1 it asserts: `ann_id` is NOT NULL; `(rowid, video_id, instance_domain, embedding)` matches the seed exactly (this excludes a copy that renumbers rowids); for each row `ann_id == compute_ann_id(key)` (three rows, so per-row); `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision` are in sqlite_master; a second run leaves table_info, the rows and sqlite_master identical. A DB with no table: the step returns, creates no table, and `in_transaction` is False. For clause_2, with `ann_id_of` monkeypatched to `lambda v, h: 7`, it asserts: IntegrityError is raised; the columns are the six old ones; all three `(rowid, ...)` rows are present; there is no `video_embeddings_new`, no index and no trigger; `conn.in_transaction` is False. Each check excludes a partial or non-transactional rebuild.

**Intent.** `whitelist_migrations.migrate_whitelist_schema` rebuilds a six-column `video_embeddings` into the guarded shape with derived ids, keeping every rowid, inside one transaction that a failed backfill rolls back whole.

- C1 - After migration, every pre-existing (rowid, key, embedding) row survives with `ann_id == compute_ann_id(key)`, the guards exist, and a second run changes nothing.
- C2 - A failed backfill raises and leaves the six-column table, its rows, no `video_embeddings_new`, no guards and no open transaction.

**Outcome.** I added a new `migrate_video_embeddings_schema` step to the whitelist migration. I haven't run the Phase 2 checkpoint; the workflow runs it after this hand-in. A probe I wrote for it (`tests/tmp/probe_phase2_rename.py`) passed. It is still in `tests/tmp/`, because none of my tools can delete files, so it needs removing by hand.

### engine/server/db/jobs/whitelist_migrations.py
- **Imports:** the module now puts `engine/server` on `sys.path` itself, the same way the job scripts do. It imports `compute_ann_id`, `create_ann_id_guards` and `create_video_embeddings_table` from `data.ann_ids`, so it no longer depends on `sync-whitelist.py` having been loaded first.
- **New `migrate_video_embeddings_schema(conn)`:**
  - It does nothing if the table is missing or already has `ann_id`.
  - Otherwise it registers `compute_ann_id` as the SQL function `ann_id_of` (deterministic) and commits anything earlier steps left open. Then it runs one explicit transaction (`BEGIN` … `COMMIT`):
    1. Rename `video_embeddings` to `video_embeddings_old`.
    2. Call `create_video_embeddings_table(conn)` to create the new table from the shared definition.
    3. Copy every row with its `rowid` named in both the column list and the SELECT, filling `ann_id` with `ann_id_of(video_id, instance_domain)`.
    4. Drop `video_embeddings_old`.
    5. Call `create_ann_id_guards(conn)` to create the UNIQUE index and the collision trigger.
  - Any exception, `BaseException` included, rolls back and re-raises.
  - **Why I didn't follow the plan's draft:** the draft creates `video_embeddings_new`, but Phase 1's `create_video_embeddings_table` takes no table-name argument, and editing it would mean touching a file outside this phase. Moving the old table aside keeps a single table definition, and the stored schema SQL is the same as on a freshly created DB.
- **Probe results:**
  - The rename carries the old automatic index with it, so the new table gets `sqlite_autoindex_video_embeddings_1` without a clash.
  - Rowids 2 and 9 kept their numbers, and their `ann_id`s equal the checkpoint's pinned values.
  - A duplicate id fails building the UNIQUE index with `IntegrityError: UNIQUE constraint failed: video_embeddings.ann_id`. After that, `sqlite_master` is unchanged and no transaction is left open.
- **`migrate_whitelist_schema`:** now calls the new step last, after `migrate_videos_language`. If `migrate_videos_schema` has just dropped the table, the new step returns at once.

### engine/server/db/jobs/migrate-whitelist.py
No edit needed. It already puts `server_dir` on `sys.path`, so `data.ann_ids` imports. The new step commits its own transaction, so the existing `with conn:` has nothing left to commit.

### tests/active/test_whitelist_migrations.py
Not edited. It is an active test that has already gated, so it isn't mine to change. It still holds without changes: `ensure_content_schema` creates an empty six-column `video_embeddings`, which the new step rebuilds without touching `videos` or its FTS triggers.

### tests/config.json
Added `engine/server/data/ann_ids.py` to the `test_whitelist_migrations.py` group, because the migration module now imports it.

**Beyond the files named.** tests/tmp/probe_phase2_rename.py - a throwaway probe that confirmed the rename, rowid and rollback behaviour. None of my tools can delete files, so it is still there and should be removed by hand.

#### Phase 3 - Sync, merge and updater carry the derived id [code]

**Files touched.** engine/server/db/jobs/sync-whitelist.py (EDITED), engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_ann_ids.py (EDITED), tests/active/test_video.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seams: `sync-whitelist.py` and `updater-worker.py` loaded in-process with `_load_job` (the harness that `test_whitelist_migrations.py` and `test_repair_video_channel_names.py` already use), and `merge-staging-db.py` run as a CLI subprocess (rung 2, through `[sys.executable, script, --prod-db, --staging-db]`). Tests go in `tests/active/test_ann_ids.py`. The target DBs come from sync's `ensure_whitelist_schema` + `ensure_content_schema`. The source DB is `engine/crawler/schema.sql` plus a six-column or a seven-column `video_embeddings`, attached as `source`. For clause_1 it asserts: `ensure_schema_compatibility` passes on a new target; on a target whose table is the six-column one it raises, and the message contains both `missing columns: ann_id` and `migrate-whitelist.py`. For clause_2 it asserts, per writer: after `rebuild_content_tables` from a source without `ann_id`, every target row's `ann_id == compute_ann_id(key)`; from a source carrying `ann_id`, the stored value is the source's (this excludes always recomputing, and copying when it should compute); after a normal merge subprocess (exit 0), every prod row's `ann_id == compute_ann_id(key)`; `inject_replace_embedding_for_test(prod, staging)` returns True, the staging row's `ann_id == compute_ann_id(key)` and its embedding is mutated. `test_video.py`'s two seeded inserts gain explicit columns and `ann_id`, and stay green.

**Intent.** `sync-whitelist.py` builds `video_embeddings` from the shared definition, so an unmigrated target fails its exact column check, and the rows that sync's reload, the merge and the updater inject write carry the derived `ann_id`.

- C1 - On a six-column `video_embeddings` target, `ensure_schema_compatibility` raises naming `missing columns: ann_id` and `migrate-whitelist.py`.
- C2 - Rows written by sync's reload (computed or copied from source), by `merge-staging-db.py` and by `inject_replace_embedding_for_test` carry `ann_id` equal to `compute_ann_id` of their key.

**Outcome.** ### `engine/server/db/jobs/sync-whitelist.py`
- **Import:** `compute_ann_id`, `create_ann_id_guards` and `create_video_embeddings_table` from `data.ann_ids`.
- **New `TARGET_EMBEDDING_COLUMNS = EMBEDDING_COLUMNS + ["ann_id"]`:** follows the `WHITELIST_DERIVED_VIDEO_COLUMNS` precedent. `EMBEDDING_COLUMNS` stays the six-column list that the source must contain.
- **`ensure_schema_compatibility`:** the exact check on `main.video_embeddings` now uses `TARGET_EMBEDDING_COLUMNS`. A six-column target fails with "Schema mismatch for video_embeddings (missing columns: ann_id). Run `engine/server/db/jobs/migrate-whitelist.py` …", through the existing wrapper.
- **`ensure_content_schema`:**
  - The inline `video_embeddings` DDL is removed from the `executescript`. The table is now created by `create_video_embeddings_table(conn)`, which uses the shared definition (six columns, then `ann_id`).
  - The guards (`create_ann_id_guards`) are created only when the table already has `ann_id`. An old six-column table therefore gets no guards here, and `ensure_schema_compatibility` refuses it next with the migrate pointer instead of failing with a raw `no such column: ann_id`.
  - The docstring now says where the table definition comes from.
- **`rebuild_content_tables`:** the embeddings copy fills all seven target columns.
  - If the source `video_embeddings` has `ann_id`, it is copied as is.
  - If not, `compute_ann_id` is registered on the connection as the deterministic SQL function `ann_id_of` and computed per row. That is the same SQL name `whitelist_migrations.py` uses. It is registered inline because `ann_ids.py` has no registration helper and is not in this phase's files.
- **Unchanged:** the FTS trigger helpers. They still commit through `executescript`; that change belongs to phase 4.

### `engine/server/db/jobs/updater-worker.py`
- **Import:** `from data.ann_ids import compute_ann_id`, next to the `data.moderation` import.
- **`inject_replace_embedding_for_test`:** the `INSERT OR REPLACE` now names `ann_id` and writes `compute_ann_id(video_id, instance_domain)` for the prod row's key. It never copies prod's stored id. The docstring says so.

### `engine/server/db/jobs/merge-staging-db.py`
No change. It already copies every column prod and staging share, so `ann_id` comes across unchanged once both sides have it. Prod's collision trigger, installed by `ensure_content_schema`, sees the same key and lets the replace through.

### `tests/active/test_video.py`
- The two positional six-value `INSERT INTO video_embeddings VALUES (...)` in `_seed` now use explicit column lists ending in `ann_id`, with `compute_ann_id("v1"|"v2", HOST)`. The table `ensure_content_schema` creates now has seven columns, so the positional inserts would fail.
- `compute_ann_id` is imported from `data.ann_ids`, after the existing guarded `engine/server` path insert. conftest does not re-export it yet.
- `similars_stack` stays on rowid.

### `tests/config.json`
The `test_video.py` group now also covers `engine/server/db/jobs/sync-whitelist.py` and `engine/server/data/ann_ids.py`, since its fixture goes through both. No `test_ann_ids.py` group was added: that file does not exist yet, and the group belongs with promoting the checkpoint into it.

### `tests/active/test_ann_ids.py`
Not created. It is where the phase 1 and phase 3 checkpoints will be promoted; a separate copy now would duplicate them.

#### Phase 4 - Unmigrated refusal and whole-run collision rollback [code]

**Files touched.** engine/server/data/ann_ids.py (EDITED), engine/server/db/jobs/merge-staging-db.py (EDITED), engine/server/db/jobs/build-video-embeddings.py (EDITED), engine/server/db/jobs/sync-whitelist.py (EDITED), engine/server/db/jobs/repair-video-channel-names.py (EDITED), engine/server/db/jobs/tests/test-orchestrator-smoke.py (EDITED), tests/active/test_ann_ids.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seams: `merge-staging-db.py` as a CLI subprocess (rung 2); `ensure_video_embeddings_schema` directly (rung 1), which build's `init_schema` delegates to; and sync's `main()` in-process through `_load_job`, with `sys.argv` set to tmp `--source-db`/`--output-db` and `fetch_hosts` monkeypatched to a fixed set, since the network is the severed layer. `build-video-embeddings.py` is not entered because its module imports the model stack, so its row tuple is not proven by a test. For clause_1 it asserts: an old stage gives a non-zero exit with `stage.video_embeddings` in stderr; an old main gives a non-zero exit with `main.video_embeddings` (two sides, two assertions); prod rows are unchanged; `ensure_video_embeddings_schema` on a six-column table raises a RuntimeError, not an OperationalError, whose message contains `main.video_embeddings`, `migrate-whitelist.py` and `--resume-staging`; `assert_video_embeddings_has_ann_id` on a missing table does nothing. For clause_2 it asserts: sync `main()` with a source whose `ann_id` collides with another key raises IntegrityError, and afterwards the target's `instances`, `videos` and `video_embeddings` rows are identical to before and the `videos_fts_ai/ad/au` triggers are in sqlite_master (this excludes the executescript commit-first partial rollback); a merge subprocess whose unguarded stage carries v1's id on (v2, h) exits non-zero, and prod's `video_embeddings` and `videos` rows are byte-identical. The existing `test_repair_video_channel_names.py` stays green.

**Intent.** An unmigrated `video_embeddings` is refused with the migrate pointer before any write, and an `ann_id` collision during a sync or a merge leaves the target DB as it was before the run.

- C1 - A `video_embeddings` without `ann_id` is refused before any write, with a RuntimeError that names its schema (`main` or `stage`) and `migrate-whitelist.py`.
- C2 - An `ann_id` collision during a sync or a merge fails the run and leaves the target DB's rows and its FTS triggers as they were before it.

**Outcome.** ### `engine/server/data/ann_ids.py`
- New `assert_video_embeddings_has_ann_id(conn, schema="main")`. It reads `PRAGMA {schema}.table_info(video_embeddings)` by position, so it also works under `sqlite3.Row`. A missing table is a no-op. A table without `ann_id` raises a single-line RuntimeError that names `{schema}.video_embeddings`, `engine/server/db/jobs/migrate-whitelist.py`, and the rule that a staging DB reused with `--resume-staging` must be recreated.
- New `ensure_video_embeddings_schema(conn)`. It runs `create_video_embeddings_table`, then the check above, then `create_ann_id_guards`. Because the check comes before the guards, an old table gets the migrate message instead of a raw `no such column: ann_id`, and nothing is written. It never commits.

### `engine/server/db/jobs/merge-staging-db.py`
- Imports `assert_video_embeddings_has_ann_id`. At the top of `try:`, before `BEGIN IMMEDIATE`, it checks `main` and then `stage`. An unmigrated side is refused before the write lock and before the first rule, with a message that names only that side.
- The rule loop is unchanged. A colliding staged `ann_id` hits prod's collision trigger, and the existing `except` rolls the whole merge back.

### `engine/server/db/jobs/build-video-embeddings.py`
- Imports `compute_ann_id` and `ensure_video_embeddings_schema`.
- `init_schema` is now `ensure_video_embeddings_schema(conn)` plus its existing commit. A resumed six-column staging table is therefore refused before the model loads.
- Each row tuple gains `compute_ann_id(video_id, instance_domain)`, and `INSERT OR REPLACE` names `ann_id`.
- `--model-name`, `--force` and the per-batch commit are unchanged. On a collision, batches committed before the failing one stay committed, as the plan accepts.

### `engine/server/db/jobs/sync-whitelist.py`
- `VIDEOS_FTS_TRIGGERS_SQL` and `VIDEOS_FTS_DROP_TRIGGERS_SQL` are now tuples of whole statements, with the same names and the same trigger names.
- `create_videos_fts_triggers` and `drop_videos_fts_triggers` run each statement through `conn.execute` instead of `executescript`. They now join the caller's transaction instead of committing first. In `main()`'s `with conn:`, the host changes, trigger drop, reload, trigger recreate and FTS rebuild are one transaction, so a collision's IntegrityError rolls all of it back, including `instances` and the `videos_fts_*` triggers.
- The exact check on `video_embeddings` passes `schema="main"`, so the refusal reads `Schema mismatch for main.video_embeddings (missing columns: ann_id). Run ...migrate-whitelist.py...`. Phase 3's substring `video_embeddings (missing columns: ann_id)` still matches.

### `engine/server/db/jobs/repair-video-channel-names.py`
- Adds `conn.execute("BEGIN")` before the sync helpers. Now that the helpers no longer commit, the trigger drop, update, recreate and rebuild commit together. A failed count check leaves the DB as it was, because `main` closes without committing.
- The old rat-tail comment is replaced with one that describes the single transaction. The function docstring now says the four steps commit together, and the module docstring says the rebuild runs "in the same transaction".

### `engine/server/db/jobs/tests/test-orchestrator-smoke.py`
- Imports `ensure_video_embeddings_schema` and calls it after the table/index copy loop in `copy_and_prune_prod`. Mini-prod therefore gets the `ann_id` guards (and no other triggers), and an unmigrated source is refused there.

### `tests/config.json`
- The `test_repair_video_channel_names.py` group now also maps to `engine/server/db/jobs/sync-whitelist.py`, because that test exercises sync's FTS helpers, which this phase changed.
- No `test_ann_ids.py` group was added: that file still doesn't exist, and the plan ties the group to promoting the checkpoints into it.

### `tests/active/test_ann_ids.py`
Not created. Per the phase 1–3 notes, it is where the checkpoints get promoted, so a copy now would duplicate this checkpoint.

**Beyond the files named.** tests/tmp/probe_fts_execute.py — a throwaway probe I wrote and ran once with ValidateTests. It showed that trigger DDL with internal semicolons runs through `conn.execute`, that the trigger drop joins an open implicit transaction, and that a rollback restores both the triggers and an `instances` insert. I have no delete tool, so it is still there and should be removed by hand.


