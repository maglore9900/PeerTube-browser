# 25-similarity-precompute-existing-sources

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-25-similarity-precompute-existing-sources.record.md`._

## Requirements

### Purpose

The updater's similarity precompute stage currently recreates `similarity-cache.db` and recomputes similarity for every row in `video_embeddings` (`updater-worker.py` passes `--recreate-out-db` to `engine/server/db/jobs/precompute-similar-ann.py`). This build adds a mode that refreshes only the sources already cached and still present in embeddings, rewriting only those entries. The updater switches to that mode. Issue 24 (similarity cache shadow build and swap) is settled to land after this one and will run whichever mode the updater uses, so the updater's precompute stage is rewritten once here.

### Operator decision (approved)

The mode refreshes exactly cached ∩ embeddings, as the issue states. Videos added by a merge get no precomputed entry from the updater. The Engine caches them lazily the first time they are requested (the serve-time write path `write_cache` in `engine/server/data/similarity_cache_manager.py` / `_write_cache` in `engine/server/data/similarity_candidates.py`, which is unchanged). Cached sources whose video is no longer in `video_embeddings` are left in the cache untouched, not pruned. The operator accepts that the stage-time gain depends on how many sources are cached: the live cache was built full, so early runs will process nearly all of prod, saving only the new videos and the file recreation.

### Precompute CLI mode

- Add a new flag `--refresh-existing` (store_true) to `precompute-similar-ann.py`, with a help text in the style of the existing flags, e.g. "Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched."
- Source set: the rows of the source DB's `video_embeddings` whose `(video_id, instance_domain)` matches a row in the output cache's `similarity_sources`, i.e. an INNER JOIN in place of the `LEFT JOIN ... WHERE s.video_id IS NULL` used by `--incremental`. It is read the same way `--incremental` reads today: ATTACH the output cache read-only (`file:...?mode=ro`) to the source connection as `out_cache`, materialise the matching rowids into a list, DETACH, then iterate with `iter_embedding_rows_by_rowids`. `total_sources` is the length of that list.
- Only that set is processed. The FAISS search, top-k selection, self-exclusion, `fetch_similarity_targets_chunked`, batching, the commit every 500, progress logging and soft-stop handling all stay as they are.
- Per processed source, keep the current rewrite semantics through the existing `record_similarities`: upsert `similarity_sources.computed_at` (one `computed_at` for the run, as today), delete that source's old `similarity_items`, insert the fresh ranked top-k.
- No other row is written or deleted. There is no global DELETE and no file recreation. Cached sources absent from `video_embeddings` keep their `similarity_sources` and `similarity_items` rows unchanged, and embeddings absent from the cache are not added.
- A source that is skipped by `build_query_batch` (embedding_dim or embedding length mismatch) is not rewritten, the same behaviour as the other modes.
- `--refresh-existing` combined with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` is a usage error reported through argparse (`parser.error` or a mutually exclusive group), exiting non-zero before any file is touched. `--cpu`/`--gpu` stay required as today.
- If the output cache file does not exist or has no `similarity_sources` rows, the run creates the schema (via the existing `connect_db` + `ensure_schema`), processes 0 sources and exits 0. `ensure_schema` must run on the output DB before the read-only ATTACH, as the current code order already does.
- Logging reuses the existing lines: `total sources=%d` reports the size of the refresh set, and `done processed=%d/%d` reports the result. A mode indicator may be added to an existing log line if it fits the file's style. No new log format is required.

### Updater precompute stage

- In `engine/server/db/jobs/updater-worker.py`, the `precompute_cmd` passes `--refresh-existing` in place of `--recreate-out-db`. Nothing else in the command changes: `--db`, `--index`, `--out`, `--top-k 1000`, `--nprobe 16`, `--search-batch-size 1024`, `--gpu --gpu-device 0` / `--cpu`, `run_with_cpu_fallback` with `stage="precompute-similar-ann"`.
- The service stop/start sequence, the failure-injection flags and the other stages are unchanged. Moving the service start before the precompute is issue 24's scope.

### Documentation

- `engine/server/db/jobs/docs/UPDATER_WORKER.md` step 10 currently says `precompute-similar-ann.py --incremental`, which does not match the code (`--recreate-out-db`). Correct it to describe `--refresh-existing`: only already-cached sources still in embeddings are rewritten, new videos are cached at serve time, and stale cached sources are left in place.
- Document `--refresh-existing` in the precompute section of `DATA_BUILD.md` alongside the existing flags, including its exclusivity with `--incremental`/`--reset`/`--reset-only`/`--recreate-out-db`.
- The initial dataset build (`scripts/run-dataset-build.sh`, and DATA_BUILD.md's full-build example) keeps its full `--recreate-out-db` / `--reset` rebuild, unchanged.

### Tests and validation

- Tests write only temporary copies of the source DB, FAISS index and similarity cache, never the shared `whitelist.db` or `similarity-cache.db` (these are symlinked across worktrees per `docs/project/issues/plan.md`).
- Processed set: with a cache holding some sources that are in embeddings, some that are not (stale), and embeddings that are not cached, a `--refresh-existing` run processes exactly cached ∩ embeddings (verified by row state and by the `total sources=` / `done processed=` counts).
- Rewrite: every processed source has the new run's `computed_at` and a freshly inserted item set (its prior sentinel items are gone).
- Untouched: stale cached sources keep byte-identical `similarity_sources` and `similarity_items` rows, and uncached embeddings gain no rows.
- Empty or missing cache: exits 0 with the schema present and 0 sources.
- Flag conflicts: each forbidden combination exits non-zero with the output file unchanged.
- Updater: the precompute command the updater builds contains `--refresh-existing` and not `--recreate-out-db`.
- "Updater stage time drops against the full-rebuild baseline" is an operator measurement on main after the merge (the orchestrator smoke test's `similarity_precompute` stage duration can serve as the figure). It is not an automated gate in this build.

### Baseline suite state

The pre-build suite exited 0 (baseline variant: false). Resolved paths: active tests `tests/active`, working `tests/tmp`, plans `docs/project/plans`, delete_me `delete_me`, archive `tests/archive`, project dir `/home/enduser/code/PeerTube-browser`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.

### Out of scope

- Shadow build, build marker, gate, swap and Engine reopen (issue 24).
- Pruning stale cached sources, and precomputing new sources in the updater.
- Changes to the Engine's serve-time cache read/write path.
- Running the new mode against the shared `similarity-cache.db` (that happens on main after the merge).

## High-level plan

### Approach

The change touches three places: the precompute CLI, one line of the updater, and two docs. The tests are two new files under `tests/active`.

**Precompute CLI (`engine/server/db/jobs/precompute-similar-ann.py`).** Add `--refresh-existing` as a store_true flag next to `--incremental`, with a help text in the same one-sentence style ("Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched."). Right after `parse_args()`, and before the existing `--cpu`/`--gpu` check, add one `parser.error` check: if `--refresh-existing` is set together with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`, argparse prints a message naming the conflicting flags and exits with code 2. Nothing has been opened at that point: no source connection, no unlink, no `connect_db`. So the output file is guaranteed to be unchanged. Putting the check before the cpu/gpu check means `--refresh-existing --reset-only` (which does not need `--cpu`) gets the specific conflict message and not the cpu/gpu one.

The source selection extends the existing `--incremental` branch rather than adding a second copy of it. The branch condition becomes "incremental or refresh-existing". The ATTACH of the output cache read-only (`file:...?mode=ro`) as `out_cache`, the rowid materialisation, the DETACH, `iter_embedding_rows_by_rowids` and `total_sources = len(...)` stay shared. Only the SELECT differs: an INNER JOIN of `video_embeddings` to `out_cache.similarity_sources` on `(video_id, instance_domain)` for refresh, and the current LEFT JOIN / IS NULL for incremental. A short comment in the style of the one already there says what refresh selects. Everything after selection is untouched: FAISS search, top-k, self-exclusion, `fetch_similarity_targets_chunked`, `record_similarities`, the commit every 500, progress and soft-stop.

How each CLI requirement is met:
- **Processed set = cached ∩ embeddings.** The INNER JOIN produces exactly this set. Stale cached sources are not in `video_embeddings`, so they never enter it. Uncached embeddings have no matching `similarity_sources` row, so they are excluded too.
- **Rewrite semantics.** Unchanged: the existing `record_similarities` upserts `computed_at` (one value per run, set once as today), deletes that source's old items and inserts the new ranked top-k.
- **No other writes.** Refresh does not take the `--reset` DELETE path or the `--recreate-out-db` unlink path; the parser check blocks both combinations. The only write in the loop is `record_similarities` for a selected source.
- **Skipped rows.** `build_query_batch` still drops dim/length mismatches before `record_similarities`, so those sources keep their old rows, as in the other modes.
- **Empty or missing cache.** The current order already runs `connect_db` + `ensure_schema` on the output before the read-only ATTACH. `ensure_schema` uses `executescript` with DDL only, so the tables are on disk when the attach reads them. The join returns no rows, `total sources=0` and `done processed=0/0` are logged, and the exit code is 0.
- **Logging.** The existing `total sources=%d` line gets a `mode=` field (full / incremental / refresh-existing), in the file's key=value style next to lines like `faiss acceleration=cpu`. There is no new log line. `done processed=%d/%d` is unchanged.

**Updater (`engine/server/db/jobs/updater-worker.py`).** In `precompute_cmd`, `--recreate-out-db` is replaced by `--refresh-existing`, so the argv is otherwise identical. To test the command without running the pipeline, the list construction moves into a small module-level builder next to `systemctl_cmd`, which is the existing precedent for a command builder in this file. It takes python_bin, script path, prod db, index, similarity db and use_gpu, and returns the same list; `main` calls it in place of the inline literal. The GPU/CPU suffix and `run_with_cpu_fallback(stage="precompute-similar-ann")` behave as before. `_to_cpu_cmd` removes only `--gpu`/`--gpu-device`, so the new flag passes through the CPU retry.

**Docs.**
- `UPDATER_WORKER.md` step 10 is rewritten: it runs `precompute-similar-ann.py --refresh-existing`, which rewrites only sources already in the cache that are still in `video_embeddings`. New videos are cached by the Engine the first time they are requested, and stale cached sources are left in place.
- `DATA_BUILD.md` §5 gets a short flag note after the example. It lists `--incremental`, `--recreate-out-db`, `--reset`/`--reset-only` and the new `--refresh-existing`, and says the new flag cannot be combined with the other four. The §5 full-build example and `scripts/run-dataset-build.sh` are not changed.

**Tests (new, under `tests/active`).**
- `test_precompute_similar_ann_refresh.py` builds everything in `tmp_path`:
  - a tiny source DB whose `video_embeddings` hold one model_name/dim, a few rowids and normalised float32 vectors;
  - a flat IP FAISS index with rowid ids, plus the `.json` sidecar that `assert_index_matches_embeddings` requires;
  - a cache seeded with sentinel rows: a few cached sources that are in embeddings, a few stale ones that are not, and some embeddings left uncached.
- The job runs as a subprocess with `--cpu`, the same way `test_precompute_random_rowids.py` runs its job. The test asserts:
  - the processed set, from row state and from the `total sources=` and `done processed=` counts in stderr;
  - that every processed source has one shared new `computed_at` greater than the sentinel, and that none of its sentinel items remain;
  - that stale sources' `similarity_sources` and `similarity_items` rows are identical before and after, and that uncached embeddings have no rows;
  - that a missing cache file and a schema-only empty cache both exit 0, have the schema, and hold 0 sources;
  - that each of the four forbidden combinations exits non-zero and leaves the output file byte-identical and at the same mtime, or absent if it was absent.
- A second small test loads `updater-worker.py` through importlib, the way `test_host_normalisation.py` does. It asserts that the builder's output contains `--refresh-existing` and not `--recreate-out-db`, for both use_gpu values.
- No test touches the shared `whitelist.db` or `similarity-cache.db`.

### Alternatives considered

- **Argparse mutually exclusive group instead of `parser.error`.** Rejected. One group of all five flags would also reject combinations that work today among the other four, for example `--reset` with `--incremental` or `--recreate-out-db` with `--incremental`. That is a behaviour change nobody asked for. argparse cannot nest groups to say "exclusive with each of these, but not the others among themselves". A single explicit check is clearer and changes nothing else.
- **A separate `elif args.refresh_existing` branch copying the ATTACH/materialise/DETACH code.** Rejected in favour of sharing the incremental branch and changing only the SQL. The two modes differ in one join, and duplicating the ATTACH handling would let them drift apart.
- **Testing the updater's command by reading the source text or AST of `updater-worker.py`, or by running `main` with `run_with_cpu_fallback` stubbed out.** A source-text check can pass while the command actually built is wrong. Driving `main` needs locks, systemctl, crawler and staging stubs, which is a lot of setup for one argv assertion. Extracting a builder is a small refactor with an existing precedent (`systemctl_cmd`), and it leaves the command itself unchanged.
- **Returning early before loading the FAISS index when the refresh set is empty.** Rejected. It would save a trivial amount on an empty cache but reorder a path the other modes share, and it would skip the embedding-space verification. The run still reads and checks `--index` and resolves the embedding space, so an empty refresh needs a valid index and non-empty embeddings, as the other modes do.

### Gotchas and risks

- **Interrupted runs now leave a usable cache.** Because refresh never truncates, a failure or soft stop partway through leaves a cache where some entries are new and others are one run older, all still valid. With `--recreate-out-db`, the same failure left a truncated cache. If a GPU run fails and falls back to CPU, the retry reprocesses the same set: the earlier attempt only rewrote sources already in the set, so the join returns the same rows, and the result is idempotent.
- **The Engine's lazy writes change which sources get refreshed.** Sources the Engine cached lazily between runs join the next run's refresh set and get rewritten at the updater's `--top-k 1000`, whatever limit the Engine wrote them with. This is the intended behaviour of cached ∩ embeddings, but it means the set grows with traffic and does not shrink.
- **Stale sources stay in the cache.** Their items may point at videos that no longer exist. This was accepted and is out of scope; the Engine's read path already filters targets.
- **Read-only ATTACH while the write connection is open.** The ATTACH runs on the source connection while `out_db` is open for writing on the same file. This is the pattern `--incremental` already uses. Nothing is written before the rowids are materialised and the database is detached, so there is no lock contention.
- **faiss in the test environment.** The new test needs faiss, the same dependency the job has. If the test environment lacks it, the test should fail loudly rather than skip, so the gate cannot pass without running.
- **Existing doc and log wording.** `ORCHESTRATOR_SMOKE_TEST.md` line 16 says "incremental similarity precompute". That was already inaccurate and is not in the requirements' doc list, so it is noted here and left alone unless the operator wants a one-word fix. The smoke test itself only checks that the similarity DB file exists, which refresh still satisfies because it creates the schema. The updater's description string ("full ANN rebuild") is untouched.

### Tradeoffs the operator accepts

- **Stage time.** The stage now does work proportional to the number of cached sources that are still live, not all embeddings. The live cache was built full, so early runs save only the new videos and the file recreation. The gain grows only if the cache is ever rebuilt smaller or pruned, and pruning is out of scope.
- **New videos after a merge.** Each new video gets no precomputed entry. Its first request pays the serve-time ANN cost and the lazy write.
- **Stale sources.** They keep taking up cache space indefinitely.
- **Empty-refresh requirements.** An empty refresh still needs a valid index and embeddings. This is a deliberate simplification: it keeps one code path, and the upgrade path, if it ever matters, is an early exit after selection.

## Impacts


<impacts>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="argparse definition in main() (lines 277-334): new --refresh-existing flag">
**What changes.** A new `parser.add_argument("--refresh-existing", action="store_true", help="Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.")` goes right after `--incremental` (lines 329-333), in the same multi-line style. `--incremental`'s help reads "Compute only for videos that do not exist in similarity_sources." and the new help mirrors it. Argparse gives the attribute `args.refresh_existing`.

**What depends on it.** The conflict check, the selection branch and the `mode=` log field (all below), the updater's new builder, and the new subprocess test. No other script or test parses this CLI. `scripts/run-dataset-build.sh` and the smoke test only call it.

**Regression risk: low.** It is an additive store_true flag. The only way to break it is a typo in the dest name. `args.refresh_existing` is read in three places, so an inconsistent spelling would raise AttributeError at runtime and not at parse time. The new test catches that because it runs the real CLI.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="post-parse validation (lines 334-336): new parser.error conflict check before the --cpu/--gpu check">
**What changes.** Between `args = parser.parse_args()` (334) and `if not args.reset_only and not (args.cpu or args.gpu): parser.error(...)` (335-336), one check is added. If `args.refresh_existing` is set together with any of `incremental`, `reset`, `reset_only` or `recreate_out_db`, it calls `parser.error(...)` naming the conflicting flags. That exits with code 2 and prints the usage to stderr.

**What depends on it.** The guarantee that the output file is untouched on a forbidden combination. That holds only because nothing has run yet: `connect_source_db` is at 370, the `--recreate-out-db` unlink at 373-386, the `--reset-only` unlink at 388-406, `connect_db`/`ensure_schema` at 408-409, and the `--reset` DELETE at 410-412. `logging.basicConfig` (338) and the signal handlers (362-367) also come later. The test's byte-identical/mtime/absent assertions for the four combinations depend on it.

**Regression risk: medium.** It must stay *before* line 335. Otherwise `--refresh-existing --reset-only` without `--cpu` would still exit 2, but with the cpu/gpu message, and the test would need to match the message to notice. It must not be placed after `connect_db`. Combinations among the other four flags must not be rejected: `--reset --incremental` and `--recreate-out-db --incremental` work today and are not in scope. `--gpu-device` is validated much later (425-426) and is unaffected.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="source selection branch (lines 433-463): `if args.incremental:` becomes incremental-or-refresh, SQL chosen per mode">
**What changes.** The condition becomes `if args.incremental or args.refresh_existing:`. The shared parts stay as they are: `out_uri = f"file:{...}?mode=ro"` (437), `ATTACH DATABASE ? AS out_cache` (438), the rowid list comprehension (439-451), `DETACH DATABASE out_cache` (452), `iter_embedding_rows_by_rowids` (453) and `total_sources = len(pending_rowids)` (454). Only the SELECT text differs:
- refresh: `SELECT e.rowid FROM video_embeddings e JOIN out_cache.similarity_sources s ON s.video_id = e.video_id AND s.instance_domain = e.instance_domain`;
- incremental: the current LEFT JOIN … `WHERE s.video_id IS NULL`.

The existing comment (434-436) gets a one-line companion saying what refresh selects. The variable name `pending_rowids` still fits both modes.

**What depends on it.**
- The processed set, which must equal cached ∩ embeddings.
- `iter_embedding_rows_by_rowids` (61-76), which batches rowids 512 at a time under SQLite's variable limit.
- The progress/ETA maths (519-541) and the `done processed=%d/%d` total.
- The ATTACH needs the source connection opened with `uri=True` (`connect_source_db`, 52-58), which it is.
- The attached file must already have the schema. `connect_db` + `ensure_schema` (408-409) run first, and `executescript` commits pending work before running DDL in autocommit, so a missing or empty cache is attachable and has the tables.

**Regression risk: medium.**
- The INNER JOIN is on raw `(video_id, instance_domain)` text. The Engine's lazy writer stores `source.get("instance_domain") or ""` (`similarity_cache.py:110`), so a source cached with an empty domain never joins. That is correct: it is not "still in embeddings" under the same key.
- A duplicated `similarity_sources` key cannot produce duplicate rowids, because the table has a PK on `(video_id, instance_domain)`.
- Order: without an ORDER BY, rowids come back in join order. Nothing depends on the order except commit batching.
- `--incremental` behaviour must stay byte-for-byte the same. A careless refactor of the shared block (for example moving the DETACH) would change it, and no existing test covers `--incremental`.
- Issue 08 (stable ANN ids, plan wave 5a) will later migrate this job from rowid to `ann_id`. This join is one more site it must convert.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="`total sources=%d` log line (line 464): gains a mode= field">
**What changes.** `logging.info("total sources=%d", total_sources)` becomes something like `logging.info("total sources=%d mode=%s", total_sources, mode)`, where mode is `full` / `incremental` / `refresh-existing`. It is derived from args; the precedence when `--incremental` is combined with `--reset` should be spelled out, and stays `incremental`. The `done processed=%d/%d elapsed=%s` line (562-567) and the soft-stop line (554-560) do not change.

**What depends on it.** Only the new test, which parses stderr: `basicConfig` (338) logs to stderr with format `%(levelname)s %(message)s`, so the line is `INFO total sources=N mode=...`. A grep of the repo outside the plan docs finds no other consumer of `total sources` or `done processed`. The updater's `run_cmd` does not capture child output, and the smoke test parses only the updater's `run:`/`done:` lines.

**Regression risk: low.** The test's regex must be tolerant of the added field, for example `total sources=(\d+)`.
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="unchanged dependencies used by refresh: ensure_schema (140-167), record_similarities (229-272), build_query_batch (93-107), the search loop (472-551), the --recreate-out-db and --reset-only unlink paths (373-406), the --reset DELETE (410-412), resolve_embedding_space / faiss.read_index / assert_index_matches_embeddings (414-420), set_nprobe (110-123)">
**What changes.** Nothing. Refresh relies on each of these unchanged:
- `record_similarities` upserts `computed_at` (one value per run, set at 465 in epoch ms), deletes the source's items and inserts the new ranked items.
- `build_query_batch` silently drops dim/length mismatches, so those sources keep their old rows.
- The unlink and DELETE paths are unreachable under refresh because the conflict check blocks them.
- The embedding-space check still runs on an empty refresh, so an empty refresh needs a readable index, a `.json` sidecar with a matching `model_name`/`embedding_dim`, and non-empty `video_embeddings`. Otherwise `resolve_embedding_space` raises "No embeddings found" and the run exits non-zero.

**What depends on it.** Every mode shares this code. The new test's fixture must satisfy it:
- `video_embeddings` columns `video_id, instance_domain, embedding, embedding_dim, model_name`, with one model/dim pair;
- index ids equal to rowids > 0, since the loop drops `rowid_int <= 0` and self-matches;
- a `<index>.json` sidecar with `model_name` and `embedding_dim` (`embedding_space.py:68-89`).

**Regression risk: low (no edit).** Two test-fixture caveats:
- `index.search(query, top_k + 1)` on a tiny index returns -1 ids, which are filtered out, so the item count is below `--top-k`. Assertions should not expect exactly top_k items.
- `set_nprobe` calls `faiss.extract_index_ivf`, which raises on a flat index; this is caught by `except Exception` at 116.
</impact>
<impact path="engine/server/data/embedding_space.py" element="resolve_embedding_space / assert_index_matches_embeddings">
**What changes.** Nothing.

**What depends on it.** The refresh run and the new test fixture:
- The sidecar must be `f"{index_path}.json"` with `model_name` equal to the DB's single `model_name` and `embedding_dim` equal to the dim.
- `index.d` must equal the dim.
- An empty `video_embeddings` table raises.

**Regression risk: none from code.** The one risk is fixture mistakes, which make the test fail with a RuntimeError message in stderr.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="new module-level command builder placed next to systemctl_cmd (lines 401-412)">
**What changes.** A new keyword-only function in the `systemctl_cmd` style (`*,` parameters, one-line `"""Handle ..."""` docstring, returns `list[str]`). It takes `python_bin`, the script path, the prod db, the index, the similarity db and `use_gpu`. It returns the exact list at lines 1114-1134, with `--recreate-out-db` replaced by `--refresh-existing`: `[python_bin, script.as_posix(), "--db", prod, "--index", index, "--out", sim, "--top-k", "1000", "--nprobe", "16", "--search-batch-size", "1024", "--refresh-existing"]` plus `["--gpu", "--gpu-device", "0"]` or `["--cpu"]`.

**What depends on it.** `main()` (the call site below) and the new updater test. That test loads the module with `importlib.util.spec_from_file_location` exactly as `tests/active/test_host_normalisation.py:78-87` does. Loading under the root test env works today: the module imports only stdlib, `scripts.cli_format` and `data.moderation`, and puts `server_dir` on `sys.path` itself (21-33).

**Regression risk: medium, because of naming.** `main()` already has a local variable `precompute_cmd` (1114). If the builder is named `precompute_cmd` and main writes `precompute_cmd = precompute_cmd(...)`, Python treats the name as local for the whole of `main` and raises UnboundLocalError. That would happen only at the precompute stage, after the merge and ANN rebuild, which is the worst place for a failure. Use a distinct name (for example `build_precompute_cmd` / `similarity_precompute_cmd`), or rename the local. Paths should be passed as `Path` and converted with `.as_posix()` inside the builder, as the current literal does, so the argv strings are identical.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main(): precompute stage call site (lines 1110-1139)">
**What changes.** The inline list literal and the `if args.use_gpu` suffix (1114-1134) are replaced by one call to the builder. `run_with_cpu_fallback(precompute_cmd, stage="precompute-similar-ann", cwd=repo_root)` (1135-1139) is unchanged. `--fail-after-merge-before-similarity` (1110-1113) stays before it.

**What depends on it.**
- The production updater run. The Engine is stopped from the merge through this stage and started in the `finally` (1140-1150). It still is: issue 24 will move that later.
- The smoke test, whose `similarity_precompute` stage duration is parsed from the `run:`/`done:` log lines that `run_cmd` writes (the marker is the script name, which is unchanged).
- `purge_hosts` on the similarity DB (844-873, 1066-1074) runs earlier in the same run. It deletes rows for stale or denied hosts, so those sources leave the refresh set. That is the only pruning left, now that recreation is gone.

**Regression risk: medium (behaviour, accepted).**
- The cache is no longer truncated and rebuilt. New merged videos get no precomputed entry, and stale sources stay.
- A cache that is missing at run time (first deployment, or a deleted file) now stays empty instead of being fully built. The stage logs `total sources=0` and exits 0, so the updater reports success with an empty cache. Worth stating in UPDATER_WORKER.md: the initial full build is `DATA_BUILD.md` §5 / `run-dataset-build.sh`.
- The GPU→CPU retry reprocesses the same set, and the argv passes through `_to_cpu_cmd` unchanged apart from the GPU flags.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="_to_cpu_cmd (361-377) and run_with_cpu_fallback (380-398)">
**What changes.** Nothing.

**What depends on it.** The refresh argv's CPU retry. `_to_cpu_cmd` drops `--gpu` and `--gpu-device <n>` and appends `--cpu`, so `--refresh-existing` survives. The retry cannot trip the new conflict check, because none of the four conflicting flags is ever in the list.

**Regression risk: low.** The retry is idempotent: a partial GPU attempt only rewrote rows that were already cached, so the set is the same. The GPU attempt may have committed batches of 500 before failing, and the retry rewrites those again with a new `computed_at`.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="parse_args description string (lines 102-105) and module docstring (line 2)">
**What changes.** Nothing, as the plan says. The description says "merge -> incremental jobs -> full ANN rebuild -> start service". "full ANN rebuild" refers to the index, not the similarity cache, so it is not made wrong by this change.

**Regression risk: none.** Listed so the next step does not treat it as missed.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="validate_outputs (735-760), assert_worker_log (482-500), parse_stage_durations (503-528), per-run path setup (864-872, 917-919)">
**What changes.** No edit. The behaviour it observes does change. Each run or scenario directory starts with no `similarity-cache.db` (the paths at 866/919 are fresh and not copied from prod). Under refresh the precompute creates the schema-only file and processes 0 sources, where before it built a full cache.

**What depends on it.** The check at 750 only requires the file to exist, so it still passes. The markers still include `precompute-similar-ann.py`. The `similarity_precompute` duration will drop sharply, which is what it measures now: it is no longer a meaningful precompute timing.

**Regression risk: low for pass/fail. The coverage lost is real:** the smoke run no longer exercises the FAISS search or write path of the precompute at all. That is not within the gate (the script is not in `tests/active`); note it for the operator.
</impact>
<impact path="scripts/run-dataset-build.sh" element="similarity stage (lines 251-258)">
**What changes.** Nothing. It keeps `--top-k 20 --nprobe 16 --recreate-out-db "${ACCEL}"` as the full-build path.

**What depends on it.** It is the documented way to build the initial full cache that refresh then maintains. It still works, because `--recreate-out-db` without `--refresh-existing` is allowed.

**Regression risk: none.** Documentation consistency: the plan's DATA_BUILD §5 flag note must describe `--recreate-out-db` as this script uses it.
</impact>
<impact path="engine/server/data/similarity_cache.py" element="ensure_similarity_schema (19-46) and store_similarity_cache (≈96-120): the Engine's own schema and serve-time writer">
**What changes.** Nothing.

**What depends on it.** Refresh's source set grows with Engine traffic: any source the Engine stores lazily joins the next refresh and is rewritten at `--top-k 1000`. The Engine's schema must stay compatible with the job's `ensure_schema` (same tables and PK), because both open the same file. The writer stores `instance_domain or ""`, which affects which rows join (see the selection entry).

**Regression risk: none from this build.** The accepted behaviour change (set only grows; pruning only via host purge) is recorded in the plan.
</impact>
<impact path="engine/server/data/similarity_cache_manager.py" element="read_cached_similarities / should_write_cache / write_cache (42-96)">
**What changes.** Nothing.

**What depends on it.** It is the lazy path for new videos, which no longer get precomputed entries. `should_write_cache` writes only when the source has no cached rows, unless the policy is refresh. `read_cached_similarities` treats a count below the limit as a miss when `require_full` is set (61-68). Sources that refresh writes with fewer than top-k items stay partial, as they were under the full build.

**Regression risk: none from this build.** It is the documented consequence: a new video's first request pays the ANN cost and the lazy write.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="_write_cache (≈259)">
**What changes.** Nothing. It is the other half of the lazy write path named in the requirements as unchanged.

**What depends on it.** It is the only way new videos enter the cache after this build, apart from a manual full build.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_precompute_similar_ann_refresh.py" element="new test module (subprocess tests of --refresh-existing)">
**What changes.** A new file. It builds a source DB, a FAISS index plus `.json` sidecar, and a seeded cache in `tmp_path`. It runs the job and asserts on:
- the processed set;
- the shared new `computed_at` above the sentinel;
- stale and uncached rows left unchanged;
- a missing or empty cache giving exit 0 with the schema and 0 sources;
- the four forbidden combinations exiting non-zero and leaving the file byte-identical, at the same mtime, or absent.

**What depends on it.** The gate. `.un/skills/devsecops/config.json` needs a `test_groups` entry for it (see that entry).

**Regression risk: HIGH, because of the interpreter. The plan's "run it the way `test_precompute_random_rowids.py` does" (via `sys.executable`) will not work.** `tests/last_test_validation.json:3-13` shows the suite runs under the root `pixi.toml` env (Python 3.14). That env's dependencies are the harness's own (`pyproject.toml:6`: anthropic, openai, pyyaml…), with no numpy and no faiss. The job imports numpy at line 14, before its faiss guard, so under `sys.executable` it dies with ModuleNotFoundError. The test cannot `import faiss`/`numpy` in-process to build the index either. The established pattern for faiss/numpy work in `tests/active` is `ENGINE_PY` from `conftest.py:32` (`engine/.pixi/envs/default/bin/python`):
- `test_video.py:197,216-218` builds `faiss.IndexIDMap(faiss.IndexFlatIP(d))` + `add_with_ids` inside an ENGINE_PY child;
- `test_similar.py:616`, `test_popular_videos.py:92-93` and `test_internal_client_reads.py:144-145` follow the same pattern;
- each asserts `ENGINE_PY.exists()` with the message "run `pixi install` in engine/", which fails loudly rather than skipping, as the plan wants.

So the job subprocess should run with `str(ENGINE_PY)`, and index construction (and vector normalisation) should happen in an ENGINE_PY child or a small child script. Pure-sqlite fixture work (the source DB with float32 blobs via `array("f")`, the cache seeding, and the byte/mtime checks) can stay in the test process.

Other fixture caveats:
- The job reads the index with `IO_FLAG_MMAP | IO_FLAG_READ_ONLY` (417). The production index is `IndexIDMap2(IndexIVFPQ)` (`build-ann-index.py:110-113`). I did not verify that the installed faiss (1.13.2 per requirements) accepts the MMAP flag on a flat `IndexIDMap`; if it rejects it, use `IndexIDMap2(IndexIVFFlat(..., nlist=1))`, trained on the tiny set.
- Rowids must be > 0, and self-matches are excluded.
- The sidecar needs `model_name` and `embedding_dim`.
- `computed_at` is in epoch milliseconds, so the sentinel must be small (e.g. 1).
- The job's `main()` imports `server_config` from `engine/server/api`, so the env var checks in `server_config` apply. They are harmless unless `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` is set to garbage in the environment.
- Use `cwd=tmp_path` and pass explicit `--db`/`--index`/`--out`, so the shared `whitelist.db`/`similarity-cache.db` defaults (lines 287-289) are never touched.
- The mtime check needs the forbidden-combo run to open nothing, which the conflict check's placement guarantees.
</impact>
<impact path="tests/active/test_updater_precompute_cmd.py" element="new test module (name illustrative): importlib load of updater-worker.py, asserts on the builder's argv">
**What changes.** A new file. It loads `engine/server/db/jobs/updater-worker.py` with importlib, as `test_host_normalisation.py:78-82` does. It calls the builder for `use_gpu=True` and `False` and asserts that `--refresh-existing` is present and `--recreate-out-db` absent. It could also assert that `_to_cpu_cmd(builder(use_gpu=True))` keeps `--refresh-existing`, a cheap check of the fallback path.

**What depends on it.** The gate and the `config.json` mapping.

**Regression risk: low.**
- Loading the module runs only module-level code: path setup and imports of `scripts.cli_format` and `data.moderation`, which already work under the root env since `test_host_normalisation` passes.
- Loading must not call `parse_args` or `resolve_default_engine_service_name`, which shells out to bash. Neither runs at import.
- Use a distinct `module_name` from `"updater_worker_job"` or accept the re-exec; each spec load is a fresh module object, so a collision is harmless.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups map (lines 14-201)">
**What changes.** Add entries for the two new test files, mapping each to the sources it covers:
- the refresh test → `engine/server/db/jobs/precompute-similar-ann.py` and `engine/server/data/embedding_space.py`;
- the updater test → `engine/server/db/jobs/updater-worker.py`.

`test_host_normalisation.py` already maps `updater-worker.py` (99-106), so that file also reruns when the updater changes.

**What depends on it.** The test-selection harness. According to the issue-32 record (`docs/project/plans/archive/01-32-...record.md:1403`), an unmapped test file runs on every invocation.

**Regression risk: low.** If the entries are forgotten, the tests still run (every time), so nothing is lost, only speed.
</impact>
<impact path="tests/active/conftest.py" element="ENGINE_PY constant (line 32)">
**What changes.** Nothing. It is the import the new refresh test should use (`from conftest import ENGINE_PY`), as `test_internal_client_reads.py:20` and `test_video.py:49` do.

**Regression risk: none.** Importing conftest pulls in `client/backend/server.py` at module level (lines 37-43). That already happens for every test in the directory.
</impact>
<impact path="tests/last_test_validation.json" element="generated validation record">
**What changes.** Nothing by hand. The harness regenerates it and adds entries for the new files.

**Regression risk: none.** Listed only because it references test file names.
</impact>
<impact path="engine/server/db/jobs/docs/UPDATER_WORKER.md" element="Execution Order step 10 (line 53); Outputs (line 28)">
**What changes.** Line 53 currently says `Update similarity cache incrementally (precompute-similar-ann.py --incremental)`. That is already wrong: the code passes `--recreate-out-db`. It is rewritten to `--refresh-existing`, with the semantics from the plan: it rewrites only sources already cached and still in `video_embeddings`, new videos are cached lazily by the Engine, and stale sources are left. Line 28 ("Updated similarity cache") stays true.

Optionally, add one sentence saying the updater no longer builds a missing or empty cache: the initial full build is `DATA_BUILD.md` §5.

**Regression risk: low.** Doc only.
</impact>
<impact path="DATA_BUILD.md" element="§5 Precompute similarity cache (lines 252-266); updater cross-reference (line 30)">
**What changes.** A flag note is added after the example (after line 263 or 264). It covers `--incremental` (only uncached embeddings), `--recreate-out-db` (delete and recreate the file), `--reset`/`--reset-only` (clear tables / clear and exit), and `--refresh-existing`, which rewrites cached ∩ embeddings, leaves the other rows alone, and cannot be combined with the other four (exit 2). The example block (256-262) and the `--top-k` paragraph (266) are unchanged.

A pre-existing inaccuracy is not in scope: line 30 points at `engine/server/db/jobs/UPDATER_WORKER.md`, but the file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`. It is a one-word fix if the operator wants it.

**Regression risk: low.** Doc only.
</impact>
<impact path="engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md" element="Purpose list line 16 ('incremental similarity precompute')">
**What changes.** Nothing, per the plan (already inaccurate, and not in the requirements' doc list). Recorded so it is a known decision. After this build the accurate wording would be "refresh of existing similarity cache sources". The smoke run now produces an empty cache, as described in the smoke-test entry.

**Regression risk: none.** This is doc drift only.
</impact>
<impact path="docs/project/issues/24-similarity-cache-shadow-swap.md" element="Proposed solution line 15 (`run precompute-similar-ann.py --incremental`), triage notes line 46, gate description line 67">
**What changes.** Nothing is required by this plan. Line 15 still names `--incremental`, while lines 46/65 already say the shadow build uses "whichever mode the updater uses once 25 is delivered". A one-line comment under `## Comments` or an edit to line 15 to say `--refresh-existing` would keep issue 24 accurate for the next lane.

**What depends on it.** Issue 24's future implementation. Its gate ("the shadow holds no fewer `similarity_sources` rows than the active file") works with refresh, because refresh never deletes sources.

**Regression risk: low.** A stale issue text could lead lane 4b to wire `--incremental`.
</impact>
<impact path="docs/project/issues/25-similarity-precompute-existing-sources.md" element="Status line and issue lifecycle">
**What changes.** On delivery, per `docs/project/triage-labels.md` / `issue-tracker.md`, the status becomes `complete` and the file moves to `docs/project/issues/archive/`. The validation item "Updater stage time drops against the full-rebuild baseline" was turned into a measurement, not a gate (record line 148). A comment should say so.

**Regression risk: none.** This is bookkeeping, probably owned by a later step.
</impact>
<impact path="docs/project/issues/plan.md" element="wave 3c row (line 82), 24/25 ordering note (line 125), wave 5a row (line 97)">
**What changes.** Nothing. Row 82 lists exactly the two code files this plan touches. Line 125 fixes the order as 25 before 24. Row 97 (issue 08) will later migrate this job's rowid usage, including the new join.

**Regression risk: none.**
</impact>
<impact path="DEPLOYMENT.md" element="updater timer paragraph (lines 130-134) and similarity-cache capacity note (line 263)">
**What changes.** Nothing. Line 131 says the updater "precomputes similarity", which is still true in a general sense. Line 263 says the cache holds 20 per seed (`--top-k 20`), while the updater writes 1000. That inconsistency already existed and is not in scope.

**Regression risk: none.** Listed for completeness.
</impact>
</impacts>


## Documentation to update

- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - updated: Rewrote Execution Order step 10 to describe the in-place `--refresh-existing` precompute and replace the incorrect `--incremental` claim.
- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md §5 now lists the precompute cache-mode flags, including `--refresh-existing` and the flags it can't be combined with. The broken link to UPDATER_WORKER.md is fixed.
- [x] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - updated: Reworded the Purpose bullet on similarity precompute so it matches what the smoke test covers: the `--refresh-existing` stage runs against an empty cache and leaves only the schema.
- [x] `docs/project/issues/24-similarity-cache-shadow-swap.md` - updated: Issue 24 now names `--refresh-existing` as the updater's precompute mode, and I added a comment recording that issue 25 is delivered.
- [x] `docs/project/issues/25-similarity-precompute-existing-sources.md` - updated: Closed issue 25 as delivered. The archive copy has `Status: enhancement, complete` and a `### Delivered` comment, but I couldn't remove the original file.
- [x] `DEPLOYMENT.md` - out of scope: The updater-timer paragraph (lines 130-134) says only that the updater "precomputes similarity" and stops/starts the Engine around the write-critical stages. Both are still true, because the stop/start sequence is unchanged. The line 263 note about `--top-k 20` describes the dataset build and was already inconsistent with the updater's `--top-k 1000`. This build did not change that inconsistency, and it is out of scope.
- [x] `docs/project/adr/0008-similarity-cache-handoff-through-files.md` - out of scope: This ADR decides how a shadow-built cache is handed to running Engines (the build marker, reopen by inode, the pre-swap gate). None of that is built yet, and nothing in it names a precompute mode. Refresh never deletes sources, so the "no fewer sources than the active file" gate stays consistent.
- [x] `docs/project/adr/0006-derived-ann-ids.md` - out of scope: Its only claim here is that the similarity cache is keyed by `(video_id, instance_domain)`. That is still true, and the refresh join uses exactly that key.
- [x] `CONTEXT.md` - out of scope: The glossary entries `Shadow build` and `Build marker` describe issue 24's design. They do not name a precompute mode, and this build does not affect them.
- [x] `docs/project/issues/08-stable-ann-ids.md` - out of scope: Line 19 says precompute moves to `ann_id` and "incremental selection stays logical-key based". The new refresh selection is also keyed on the logical `(video_id, instance_domain)`, so the statement holds. The extra rowid join site is recorded in the plan and inventory for issue 08's implementer; it is not a false claim in the issue.
- [x] `docs/project/issues/plan.md` - out of scope: Row 82 lists the two code files this build touched, and line 125 already orders 25 before 24. Nothing in it describes the precompute mode.

## Implementation plan

## Draft: `--refresh-existing` for the similarity precompute, wired into the updater

### What has to be tested (step 1)

| Behaviour | Where it is proved |
|---|---|
| The processed set is exactly cached ∩ embeddings, keyed on the raw `(video_id, instance_domain)` | refresh test: row state, plus `total sources=` and `done processed=` in stderr |
| A processed source gets the run's single `computed_at`, above the sentinel, and fresh items (no sentinel items left) | refresh test |
| Stale cached sources, including an empty-domain key, keep identical rows. Uncached embeddings gain no rows | refresh test: before/after snapshots |
| A source dropped by `build_query_batch` (length mismatch) is counted in the total, not processed and not rewritten | refresh test: `done processed=3/4` and an unchanged row |
| A missing or schema-only cache exits 0, has the schema and holds 0 sources | refresh test, parametrised |
| Each of the 4 forbidden combinations exits 2, with the output unchanged (same bytes and mtime) or still absent | refresh test, 4 flags × {seeded, absent} |
| The updater's argv is the old one with `--recreate-out-db` swapped for `--refresh-existing`, and the CPU retry keeps the flag | updater test, exact list equality |

### Module map

| File | Change |
|---|---|
| `engine/server/db/jobs/precompute-similar-ann.py` | flag, conflict check, `mode`, shared selection branch with the SQL chosen per mode, `mode=` in the `total sources` line |
| `engine/server/db/jobs/updater-worker.py` | new `similarity_precompute_cmd` next to `systemctl_cmd`. `main()` calls it |
| `tests/active/test_precompute_similar_ann_refresh.py` | new |
| `tests/active/test_updater_precompute_cmd.py` | new |
| `.un/skills/devsecops/config.json` | two `test_groups` entries |
| `engine/server/db/jobs/docs/UPDATER_WORKER.md`, `DATA_BUILD.md`, `docs/project/issues/24-similarity-cache-shadow-swap.md` | doc text below |

---

### `precompute-similar-ann.py`

**Flag**, right after `--incremental` (after line 333), in the same multi-line style:

```python
    parser.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.",
    )
```

**Conflict check** goes between `args = parser.parse_args()` (334) and the `--cpu/--gpu` check (335). At that point nothing has run: no logging config, no signal handlers, no connection, no unlink.

```python
    args = parser.parse_args()
    if args.refresh_existing:
        conflicts = [flag for flag, enabled in (("--incremental", args.incremental), ("--reset", args.reset), ("--reset-only", args.reset_only), ("--recreate-out-db", args.recreate_out_db)) if enabled]
        if conflicts:
            parser.error(f"--refresh-existing cannot be combined with {', '.join(conflicts)}")
    if not args.reset_only and not (args.cpu or args.gpu):
        parser.error("one of --cpu or --gpu is required unless --reset-only is used")
```

What this guarantees:
- `parser.error` exits 2 and prints the usage plus the message to stderr.
- Combinations among the other four flags are not touched: `--reset --incremental` and `--recreate-out-db --incremental` still work.
- Because the check comes first, `--refresh-existing --reset-only` without `--cpu` gets the conflict message, not the cpu/gpu one.

**Mode and selection** replace lines 433-464. The `else` (full) branch is kept verbatim.

```python
        if args.refresh_existing:
            mode = "refresh-existing"
        elif args.incremental:
            mode = "incremental"
        else:
            mode = "full"
        if args.incremental or args.refresh_existing:
            # Incremental mode compares source embeddings with already-computed rows
            # from the output cache DB. We materialize only rowids first to avoid
            # lock contention while writing to the output DB.
            # Refresh mode selects the complement: embeddings whose source is already cached.
            if args.refresh_existing:
                selection_sql = """
                    SELECT e.rowid
                    FROM video_embeddings e
                    JOIN out_cache.similarity_sources s
                      ON s.video_id = e.video_id
                     AND s.instance_domain = e.instance_domain
                    """
            else:
                selection_sql = """
                    SELECT e.rowid
                    FROM video_embeddings e
                    LEFT JOIN out_cache.similarity_sources s
                      ON s.video_id = e.video_id
                     AND s.instance_domain = e.instance_domain
                    WHERE s.video_id IS NULL
                    """
            out_uri = f"file:{out_db_path.as_posix()}?mode=ro"
            src_db.execute("ATTACH DATABASE ? AS out_cache", (out_uri,))
            pending_rowids = [int(row["rowid"]) for row in src_db.execute(selection_sql)]
            src_db.execute("DETACH DATABASE out_cache")
            row_iter = iter_embedding_rows_by_rowids(src_db, pending_rowids)
            total_sources = len(pending_rowids)
        else:
            ...  # unchanged full-scan branch
        logging.info("total sources=%d mode=%s", total_sources, mode)
```

Invariants:
- **Mode precedence.** Refresh cannot be combined with incremental (the parser blocks it). `--incremental` wins over `--reset` / `--recreate-out-db`, whose runs log `mode=incremental`. Those flags alone log `mode=full`. `--reset-only` returns before this line and never logs a mode.
- **`--incremental` is unchanged.** Its SQL is the same text as before. The ATTACH, materialisation, DETACH and iteration order are the same.
- **Missing or empty cache is safe to attach.** The ATTACH still runs after `connect_db` + `ensure_schema` (408-409). `executescript` has committed by then, so a missing or empty cache is attachable and has the tables. The join yields `[]`, so the log shows `total sources=0` and `done processed=0/0`, and the exit code is 0.
- **Writes are limited to the selected set.** Under refresh, the unlink and DELETE paths cannot be reached. The only write is `record_similarities` for rows selected by the join. `computed_at` (465) is still set once per run.
- **No duplicate rowids.** The PK on `similarity_sources(video_id, instance_domain)` guarantees this.

---

### `updater-worker.py`

**Builder**, placed after `systemctl_cmd` (after line 412) in the same keyword-only style. It is deliberately not named `precompute_cmd`: that name is a local in `main()`, and reusing it would raise UnboundLocalError at the precompute stage.

```python
def similarity_precompute_cmd(
    *,
    python_bin: str,
    script_path: Path,
    db_path: Path,
    index_path: Path,
    out_path: Path,
    use_gpu: bool,
) -> list[str]:
    """Handle similarity precompute cmd."""
    cmd = [
        python_bin,
        script_path.as_posix(),
        "--db",
        db_path.as_posix(),
        "--index",
        index_path.as_posix(),
        "--out",
        out_path.as_posix(),
        "--top-k",
        "1000",
        "--nprobe",
        "16",
        "--search-batch-size",
        "1024",
        "--refresh-existing",
    ]
    if use_gpu:
        cmd.extend(["--gpu", "--gpu-device", "0"])
    else:
        cmd.append("--cpu")
    return cmd
```

**Call site.** Lines 1114-1134 become the block below. `run_with_cpu_fallback(precompute_cmd, stage="precompute-similar-ann", cwd=repo_root)` and the failure injection at 1110-1113 do not change.

```python
                precompute_cmd = similarity_precompute_cmd(
                    python_bin=args.python_bin,
                    script_path=script_dir / "precompute-similar-ann.py",
                    db_path=prod_db,
                    index_path=index_path,
                    out_path=similarity_db,
                    use_gpu=args.use_gpu,
                )
```

The argv strings are identical to the old literal apart from the one swapped flag. The `run:` log marker (the script name) does not change. `_to_cpu_cmd` passes `--refresh-existing` through unchanged.

---

### `tests/active/test_precompute_similar_ann_refresh.py`

Docstring, in the style of `test_precompute_random_rowids.py`:

```
"""`precompute-similar-ann.py --refresh-existing` rewrites exactly the cached sources still in `video_embeddings` and nothing else.

- Over a cache holding three live sources, two gone sources, an empty-domain key and one live source whose blob is too short, the job logs `total sources=4 mode=refresh-existing` and `done processed=3/4`. The three live sources share one new `computed_at` above the sentinel and hold only fresh ranked items. Every other cached row is unchanged, and uncached embeddings gain no rows.
- Over a missing or a schema-only cache, the job exits 0 with both tables present and no source.
- With `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`, the job exits 2 naming the conflict, and the output file keeps its bytes and mtime, or stays absent.

The job and the FAISS index build run under the Engine's pixi interpreter (`ENGINE_PY`), since numpy and faiss live only there. Every file is under tmp_path.
"""
```

**Constants and fixture contents**

```python
PRECOMPUTE_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py"
DIM = 4
MODEL = "test-model"
DOMAIN = "a.example"
SENTINEL_COMPUTED_AT = 1  # computed_at is epoch ms, so any real run is far above this
LIVE = [f"v{i}" for i in range(1, 9)]  # rowids 1..8, valid unit vectors, all in the index
SHORT = "v9"  # rowid 9, embedding_dim 4 but a 3-float blob: in the join, dropped by build_query_batch
CACHED_LIVE = [("v1", DOMAIN), ("v2", DOMAIN), ("v3", DOMAIN)]  # expected processed set
CACHED_UNTOUCHED = [("gone1", DOMAIN), ("gone2", DOMAIN), ("v5", ""), (SHORT, DOMAIN)]  # stale, empty-domain key, skipped
UNCACHED = [(f"v{i}", DOMAIN) for i in range(4, 9)]
FORBIDDEN = ["--incremental", "--reset", "--reset-only", "--recreate-out-db"]
```

**Source DB (in-process, sqlite3 plus `array("f")`).**
- Table: `video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT)`.
- Rows are inserted with explicit rowids 1..9.
- Vector i is `[cos i, sin i, cos 2i, sin 2i]`, normalised with `math.hypot`, then packed as `array("f", …).tobytes()`.
- v9 gets `array("f", [1, 0, 0]).tobytes()` with `embedding_dim=4`.
- Every row has one model/dim pair, so `resolve_embedding_space` passes.

**Index (an `ENGINE_PY` child, `BUILD_INDEX_CHILD`).**
- It reads the rows whose blob is `DIM*4` bytes and builds `faiss.index_factory(DIM, "IDMap2,IVF1,Flat", faiss.METRIC_INNER_PRODUCT)`.
- It then trains, calls `add_with_ids` with the rowids, and runs `faiss.write_index`.
- The test writes the sidecar `f"{index}.json"` = `{"model_name": MODEL, "embedding_dim": DIM}`.
- **Why IVF and not flat.** This is the same inverted-list family as production (`IndexIDMap2(IndexIVFPQ)`), so the job's `IO_FLAG_MMAP | IO_FLAG_READ_ONLY` read and `set_nprobe` are known to work. nprobe 16 over nlist 1 is clamped by faiss. The "too few training points" warning is harmless.
- **Failure mode.** The child's non-zero exit is asserted with its stderr, and `ENGINE_PY.exists()` is asserted with the message "run `pixi install` in engine/". A missing faiss fails the test and never skips it.
- **Sharing.** The source DB and index are built once, as a module fixture via `tmp_path_factory`. The job opens the DB read-only.

**Cache seeding.**
- Each test creates its cache with the job itself: `--reset-only --out <cache>`. That gives one schema source, the real `ensure_schema`, and the setup's exit code is asserted.
- It then inserts through sqlite3, for each key in `CACHED_LIVE + CACHED_UNTOUCHED`:
  - `similarity_sources(key, SENTINEL_COMPUTED_AT)`;
  - two items, `("sentinel-a", DOMAIN, 0.5, 1)` and `("sentinel-b", DOMAIN, 0.4, 2)`.

**Helpers.**

```python
def _run_job(tmp_path: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(ENGINE_PY), str(PRECOMPUTE_JOB), "--db", str(source_db), "--index", str(index_path), "--out", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=120)
```

- `_sources(path)` and `_items(path, key)` read through `file:…?mode=ro` with ORDER BY, returning tuples.
- `_counts(stderr)` returns `int(re.search(r"total sources=(\d+)", …))` and the `done processed=(\d+)/(\d+)` pair.

**Tests.**
1. **`test_refresh_rewrites_exactly_cached_live_sources`**
   - Seed, snapshot `_sources` and every untouched key's items, then run `--refresh-existing --cpu --top-k 3`.
   - Assert `returncode == 0`, `mode=refresh-existing` in stderr, total 4, done `(3, 4)`.
   - The live keys all have the same `computed_at` T > 1.
   - Each live key's items have no `sentinel-` target and ranks `1..n` with 1 ≤ n ≤ 3. Every target is a LIVE key on DOMAIN other than the source itself.
   - The untouched keys' source rows and items equal the snapshot. For v9, this proves a skipped source is not rewritten.
   - No `similarity_sources` or `similarity_items` source row exists for any `UNCACHED` key.
   - `COUNT(*)` of `similarity_sources` is still 7.
2. **`test_refresh_over_missing_or_empty_cache_is_a_no_op`**, parametrised `["missing", "empty"]`
   - "empty" is created by `--reset-only`.
   - Assert: exit 0, total 0, done `(0, 0)`, both tables in `sqlite_master`, 0 sources.
3. **`test_refresh_rejects_each_destructive_flag`**, parametrised FORBIDDEN × `["seeded", "absent"]`
   - Record `read_bytes()` and `stat().st_mtime_ns`, or absence.
   - Run `--refresh-existing <flag> --cpu`.
   - Assert `returncode == 2`, `"--refresh-existing cannot be combined with"` and the flag in stderr, and the bytes/mtime unchanged or the file still absent.

### `tests/active/test_updater_precompute_cmd.py`

- The module is loaded with `importlib.util.spec_from_file_location("updater_worker_precompute", JOBS_DIR / "updater-worker.py")`, as `test_host_normalisation._load_job` does.
- `test_updater_builds_refresh_command`, parametrised `use_gpu`:
  - It asserts the builder's list `==` the old literal with `"--refresh-existing"` in place of `"--recreate-out-db"`, with the `["--gpu", "--gpu-device", "0"]` or `["--cpu"]` suffix.
  - It asserts `"--recreate-out-db" not in cmd`.
  - The inputs are fixed `Path`s under tmp_path and `python_bin="python3"`.
- `test_cpu_fallback_keeps_refresh`: `module._to_cpu_cmd(gpu_cmd) == cpu_cmd`.

### `.un/skills/devsecops/config.json`

```json
    "test_precompute_similar_ann_refresh.py": [
      "engine/server/db/jobs/precompute-similar-ann.py",
      "engine/server/data/embedding_space.py"
    ],
    "test_updater_precompute_cmd.py": [
      "engine/server/db/jobs/updater-worker.py"
    ]
```

### Docs

**`UPDATER_WORKER.md`, line 53:**

> 10. Refresh the similarity cache's existing entries (`precompute-similar-ann.py --refresh-existing`). Only sources already in `similarity_sources` whose video is still in `video_embeddings` are recomputed and rewritten. Videos added by this run get no entry here; the Engine caches each one the first time it is requested. Cached sources whose video is gone are left in place. A missing or empty cache stays empty after this step, so build the initial cache with `DATA_BUILD.md` §5.

**`DATA_BUILD.md` §5**, inserted after the code block (after line 263):

> Output modes:
> - no mode flag: compute every row of `video_embeddings`, upserting into the existing cache.
> - `--reset`: clear both cache tables, then compute every row.
> - `--recreate-out-db`: delete and recreate the cache file, then compute every row (this is what `scripts/run-dataset-build.sh` runs).
> - `--reset-only`: recreate the cache file empty and exit; needs neither `--cpu` nor `--gpu`.
> - `--incremental`: compute only videos not yet in `similarity_sources`.
> - `--refresh-existing`: recompute only videos already in `similarity_sources` that are still in `video_embeddings`, leaving every other cache row untouched. The updater runs this mode. It cannot be combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` (the job exits 2).

**Issue 24, line 15:** `--incremental` becomes `--refresh-existing`. The issue-25 status/archive move is left to the delivery step.

---

### Check against plan and requirements (step 2)

- **Pass 1: plan versus requirements, one by one.**
  - Help text, flag and exclusivity are all met, with exit 2 before any file is touched. `--cpu`/`--gpu` are still required.
  - Selection: INNER JOIN, read-only ATTACH, materialise, DETACH, iterate by rowids; `total_sources` is `len`.
  - The search/commit/soft-stop code is untouched, and the rewrite goes through `record_similarities`.
  - There is no other write. Skipped rows are not rewritten.
  - Missing or empty cache gives exit 0: `ensure_schema` runs before the ATTACH.
  - Logging reuses `total sources=`, with a `mode=` field.
  - Updater argv changes only by the flag.
  - Docs: step 10 and the §5 note. `run-dataset-build.sh` is unchanged.
  - Tests cover every validation bullet on tmp files only.
- **Pass 2: where the draft deliberately departs from the plan text, with the impact inventory's reason.**
  - Tests run under `ENGINE_PY`, not `sys.executable`: the root env has no numpy or faiss.
  - The builder is named `similarity_precompute_cmd`, to avoid the UnboundLocalError on the `precompute_cmd` local.
  - The conflict check sits before the cpu/gpu check.
  - The fixture uses an IVF1 index, so the MMAP read is known to work.
  - The pass converged: nothing else is left unmet.

### Deliberate simplifications (named)

- **An empty refresh still reads and verifies the index.** It needs non-empty embeddings, a readable index and a valid sidecar. This keeps one code path for all modes. The upgrade path is an early exit after selection.
- **One schema source in the tests.** Seeding goes through `--reset-only` rather than a copied DDL, so a broken `--reset-only` shows up as a setup failure in this test.

### Notes for the operator (not in the gate)

- **Smoke test coverage drops.** The orchestrator smoke run starts every run with no similarity cache. It now produces a schema-only cache and no longer exercises the precompute's FAISS or write path. Its `similarity_precompute` duration stops being a meaningful baseline.
- **Stale wording left alone.** `ORCHESTRATOR_SMOKE_TEST.md` line 16 and `DATA_BUILD.md` line 30's path are unchanged, per the settled doc list.


### Phases

#### Phase 1 - Refresh guard [code]

**Files touched.** engine/server/db/jobs/precompute-similar-ann.py (EDITED), tests/active/test_precompute_similar_ann_refresh.py (NEW), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: the process boundary of `engine/server/db/jobs/precompute-similar-ann.py`. The job runs as a subprocess, following the harness in `tests/active/test_precompute_random_rowids.py` (`_run_job` with `cwd=tmp_path`, `capture_output`), but under `conftest.ENGINE_PY` because the job imports numpy and faiss. The run is guarded by `assert ENGINE_PY.exists()` with the message "run `pixi install` in engine/", as `test_internal_client_reads.py` does. `test_refresh_rejects_each_destructive_flag` is parametrised over the four flags `--incremental`, `--reset`, `--reset-only`, `--recreate-out-db` × {seeded cache, absent cache}. The seeded cache is made by the job's own `--reset-only` plus sqlite3 sentinel inserts, all under tmp_path. It records `read_bytes()` and `stat().st_mtime_ns`, or records that the file is absent, then runs `--refresh-existing <flag> --cpu`. It asserts `returncode == 2`, that stderr contains `--refresh-existing cannot be combined with` and the flag, and that bytes and mtime are unchanged or the file is still absent.

**Intent.** `precompute-similar-ann.py` accepts `--refresh-existing`, and its post-`parse_args` conflict check rejects it together with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` before the output file is opened, unlinked or created.

- C1 - Combining `--refresh-existing` with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` exits 2, naming the conflicting flag on stderr.
- C2 - After a rejected combination the output file keeps its bytes and mtime, or stays absent if it was absent.

**Outcome.** ### `engine/server/db/jobs/precompute-similar-ann.py`
- **New flag.** `--refresh-existing` (store_true) goes right after `--incremental`, in the same multi-line `add_argument` style. Its help text is the plan's: "Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched."
- **Conflict check.** A new check sits right after `parse_args()` and before the existing `--cpu`/`--gpu` check. When `--refresh-existing` is set, it collects whichever of `--incremental`, `--reset`, `--reset-only` and `--recreate-out-db` are also set. If there are any, it calls `parser.error("--refresh-existing cannot be combined with <those flags, comma-joined>")`, which exits 2 on one `precompute-similar-ann.py: error:` line.
- **Why the output file is safe.** The check runs before logging setup, the signal handlers, the source connection, the `--recreate-out-db`/`--reset-only` unlinks and `connect_db`/`ensure_schema`. So a refused combination leaves `--out` exactly as it was, or still absent.
- **Why it comes before the `--cpu`/`--gpu` check.** `--refresh-existing --reset-only` given without an accelerator flag gets the conflict message, not the cpu/gpu one.
- **What is unchanged.** Combinations among the other four flags are still allowed.
- **Behaviour in between phases.** Until phase 2, `--refresh-existing` on its own is accepted and runs the existing full-scan path. The selection SQL and the `mode=` log field belong to phase 2.

### `.un/skills/devsecops/config.json`
- **New `test_groups` entry.** `"test_precompute_similar_ann_refresh.py"` maps to `engine/server/db/jobs/precompute-similar-ann.py` and `engine/server/data/embedding_space.py`, as the plan says.

### `tests/active/test_precompute_similar_ann_refresh.py`
- **Not written this turn.** This phase's gate is the audited checkpoint in `tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py`, and I was asked for production code only. I did not copy it into `tests/active`. I expect the workflow's promotion step to create the durable file from that checkpoint, and the new `config.json` entry above is already keyed to that name.

#### Phase 2 - Refresh selection [code]

**Files touched.** engine/server/db/jobs/precompute-similar-ann.py (EDITED), tests/active/test_precompute_similar_ann_refresh.py (EDITED)

**Checkpoint.** Seam: the same subprocess boundary and harness as phase 1, in `tests/active/test_precompute_similar_ann_refresh.py`. The module fixture (`tmp_path_factory`) builds a tmp source DB, with `video_embeddings` rowids 1..9 where v9 has a 3-float blob, and an `IDMap2,IVF1,Flat` inner-product index built by an `ENGINE_PY` child, plus its `.json` sidecar. The child's non-zero exit is asserted along with its stderr, so a missing faiss fails the test and does not skip it. Each test creates its cache with `--reset-only` and seeds sentinel rows for `CACHED_LIVE + CACHED_UNTOUCHED`. `test_refresh_rewrites_exactly_cached_live_sources` runs `--refresh-existing --cpu --top-k 3` and asserts: exit 0; `mode=refresh-existing`, `total sources=4` and `done processed=3/4` in stderr; v1–v3 share one `computed_at` > 1 and hold only non-sentinel items ranked 1..n (n ≤ 3), each a LIVE key on DOMAIN other than the source itself; gone1, gone2, (v5, "") and v9 have source rows and items equal to the pre-run snapshot; no UNCACHED key has a row; there are still 7 sources. `test_refresh_over_missing_or_empty_cache_is_a_no_op`, parametrised ["missing", "empty"], asserts exit 0, total 0, done 0/0, both tables present in `sqlite_master`, and 0 sources.

**Intent.** Under `--refresh-existing`, the shared incremental/refresh selection branch in `precompute-similar-ann.py` inner-joins `video_embeddings` to the read-only attached `similarity_sources`, so the job rewrites exactly the cached sources still in `video_embeddings` and leaves every other cache row as it was.

- C1 - Each cached source still in `video_embeddings` that `build_query_batch` accepts is rewritten with the run's single new `computed_at` and only fresh ranked items, and nothing is selected when the cache is missing or schema-only.
- C2 - Every other cache row, whether a stale source, an empty-domain key or a length-skipped source, is left as it was, and uncached embeddings gain no rows.

**Outcome.** ### engine/server/db/jobs/precompute-similar-ann.py
- The job now picks a selection mode (`refresh-existing`, `incremental` or `full`) and logs it as `selection mode=%s` just before the `total sources=` line. The checkpoint looks for `mode=refresh-existing` in the output.
- The existing incremental branch now also runs under `--refresh-existing`. Both modes attach the output cache read-only as `out_cache` and collect a list of rowids before any writes, as incremental already did. Only the SELECT differs:
  - **`--refresh-existing`:** `video_embeddings` is inner-joined to `out_cache.similarity_sources` on both `video_id` and `instance_domain`.
  - **`--incremental`:** keeps its `LEFT JOIN ... WHERE s.video_id IS NULL`.
- Effect on the cache:
  - Only cached sources that are still in `video_embeddings` are selected and rewritten, all with the run's single `computed_at`.
  - Stale cache rows are never selected, so they are left as they were. So is a key that only matches on `video_id`, like `("v5", "")`.
  - A cached source with the wrong embedding length is counted in `total sources` but dropped by `build_query_batch`, so its row is also left alone.
  - Embeddings that aren't cached are not selected, so they gain no rows.
- A missing or schema-only cache selects nothing, so the run logs 0 total and 0/0 processed. The existing `connect_db` + `ensure_schema` step creates and commits both tables before the attach, so the tables are there afterwards.
- Nothing else in the job changed: the search, the recording, the full-scan path and incremental's results are all as before.

### tests/active/test_precompute_similar_ann_refresh.py
Not touched. The phase's files list names it, but the gating checkpoint lives at `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py`, and this step's job is only the production code.

I did not run the checkpoint; the workflow's run is the one that counts.

#### Phase 3 - Updater argv [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_updater_precompute_cmd.py (NEW), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: the function boundary of `updater-worker.py`. The module is loaded in-process with `importlib.util.spec_from_file_location` from `JOBS_DIR / "updater-worker.py"`, following `test_host_normalisation._load_job`. `tests/active/test_updater_precompute_cmd.py::test_updater_builds_refresh_command`, parametrised over `use_gpu` ∈ {True, False}, asserts that `similarity_precompute_cmd(...)` with fixed tmp_path `Path`s and `python_bin="python3"` equals, as a list, the old literal with `--refresh-existing` in place of `--recreate-out-db` plus the `["--gpu", "--gpu-device", "0"]` or `["--cpu"]` suffix, and that `--recreate-out-db` is not in it. `test_cpu_fallback_keeps_refresh` asserts `module._to_cpu_cmd(gpu_cmd) == cpu_cmd`.

**Intent.** The updater's precompute stage builds its command through a module-level `similarity_precompute_cmd` in `updater-worker.py` that runs `--refresh-existing` in place of `--recreate-out-db`, and the CPU retry keeps that flag.

- C1 - For both `use_gpu` values, `similarity_precompute_cmd` returns the previous argv with `--recreate-out-db` replaced by `--refresh-existing`.
- C2 - `_to_cpu_cmd` applied to the GPU argv gives the CPU argv, keeping `--refresh-existing`.

**Outcome.** ### `engine/server/db/jobs/updater-worker.py`
- New module-level `similarity_precompute_cmd(*, python_bin, script_path, db_path, index_path, out_path, use_gpu) -> list[str]`. It sits after `systemctl_cmd` and uses the same keyword-only style. It returns the precompute argv the updater used to build inline, token for token. The one change is that `--refresh-existing` now takes the slot `--recreate-out-db` held. The argv ends in `--gpu --gpu-device 0` when `use_gpu` is true and `--cpu` otherwise (C1). Paths are passed through `.as_posix()`, as they were before.
- `main`'s precompute stage now gets `precompute_cmd` from `similarity_precompute_cmd(...)` and no longer builds the list and appends the accelerator flags itself. `run_with_cpu_fallback` still runs it. `_to_cpu_cmd` is unchanged: it drops only `--gpu` and `--gpu-device <n>`, so a CPU retry keeps `--refresh-existing` in place (C2). The module now contains no `--recreate-out-db` literal.

### `.un/skills/devsecops/config.json`
- Registered the test group `"test_updater_precompute_cmd.py": ["engine/server/db/jobs/updater-worker.py"]`. Phases 1–2 did the same for `test_precompute_similar_ann_refresh.py`: the group is registered now and the test file itself lands in `tests/active/` when the checkpoint is promoted.

### `tests/active/test_updater_precompute_cmd.py`
- Not created in this step. The step asked for production code only, and the checkpoint in `tests/tmp/` carries this phase. Following the phase 1–2 pattern, promoting it into `tests/active/` under this name is left to the promotion step. The checkpoint file was not touched.


