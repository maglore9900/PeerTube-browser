# Build record - 25-similarity-precompute-existing-sources

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/19-25-similarity-precompute-existing-sources.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Similarity precompute: rewrite only existing cache sources\n\nStatus: enhancement, needs-triage\nOrigin: task 56, [M7][F4]\n\n## Problem\n\nThe updater runs similarity precompute over all embeddings with full cache recreation, which is heavy and can keep downtime longer than needed.\n\n## Proposed solution\n\nA mode that recomputes similarity only for sources already in `similarity_sources`, rewriting only those entries.\n\n- New CLI mode in `precompute-similar-ann.py`: source set = current embeddings \u2229 existing `similarity_sources` in the output cache; process only that set.\n- Per processed source, keep the current rewrite semantics: upsert `similarity_sources.computed_at`, delete old `similarity_items`, insert fresh top-k.\n- Leave non-processed sources untouched (no global wipe).\n- The updater uses the new mode for its precompute stage and stops passing full-reset behaviour.\n\n## Validation (from the original task)\n\n- Processed set equals \"already cached and still present in embeddings\".\n- Processed sources are rewritten; untouched ones are unchanged.\n- Updater stage time drops against the full-rebuild baseline.\n\n## Related\n\n- See the ordering note in `24-similarity-cache-shadow-swap`.\n\n## Comments",
  "request_source": "read from docs/project/issues/25-similarity-precompute-existing-sources.md",
  "slug": "25-similarity-precompute-existing-sources",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "9": "done",
    "10": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Refresh guard",
      "checkpoint": "Seam: the process boundary of `engine/server/db/jobs/precompute-similar-ann.py`. The job runs as a subprocess, following the harness in `tests/active/test_precompute_random_rowids.py` (`_run_job` with `cwd=tmp_path`, `capture_output`), but under `conftest.ENGINE_PY` because the job imports numpy and faiss. The run is guarded by `assert ENGINE_PY.exists()` with the message \"run `pixi install` in engine/\", as `test_internal_client_reads.py` does. `test_refresh_rejects_each_destructive_flag` is parametrised over the four flags `--incremental`, `--reset`, `--reset-only`, `--recreate-out-db` \u00d7 {seeded cache, absent cache}. The seeded cache is made by the job's own `--reset-only` plus sqlite3 sentinel inserts, all under tmp_path. It records `read_bytes()` and `stat().st_mtime_ns`, or records that the file is absent, then runs `--refresh-existing <flag> --cpu`. It asserts `returncode == 2`, that stderr contains `--refresh-existing cannot be combined with` and the flag, and that bytes and mtime are unchanged or the file is still absent.",
      "intent": "`precompute-similar-ann.py` accepts `--refresh-existing`, and its post-`parse_args` conflict check rejects it together with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` before the output file is opened, unlinked or created.",
      "clauses": [
        {
          "id": "C1",
          "text": "Combining `--refresh-existing` with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` exits 2, naming the conflicting flag on stderr."
        },
        {
          "id": "C2",
          "text": "After a rejected combination the output file keeps its bytes and mtime, or stays absent if it was absent."
        }
      ],
      "files": [
        "engine/server/db/jobs/precompute-similar-ann.py (EDITED)",
        "tests/active/test_precompute_similar_ann_refresh.py (NEW)",
        ".un/skills/devsecops/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/db/jobs/precompute-similar-ann.py`\n- **New flag.** `--refresh-existing` (store_true) goes right after `--incremental`, in the same multi-line `add_argument` style. Its help text is the plan's: \"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\"\n- **Conflict check.** A new check sits right after `parse_args()` and before the existing `--cpu`/`--gpu` check. When `--refresh-existing` is set, it collects whichever of `--incremental`, `--reset`, `--reset-only` and `--recreate-out-db` are also set. If there are any, it calls `parser.error(\"--refresh-existing cannot be combined with <those flags, comma-joined>\")`, which exits 2 on one `precompute-similar-ann.py: error:` line.\n- **Why the output file is safe.** The check runs before logging setup, the signal handlers, the source connection, the `--recreate-out-db`/`--reset-only` unlinks and `connect_db`/`ensure_schema`. So a refused combination leaves `--out` exactly as it was, or still absent.\n- **Why it comes before the `--cpu`/`--gpu` check.** `--refresh-existing --reset-only` given without an accelerator flag gets the conflict message, not the cpu/gpu one.\n- **What is unchanged.** Combinations among the other four flags are still allowed.\n- **Behaviour in between phases.** Until phase 2, `--refresh-existing` on its own is accepted and runs the existing full-scan path. The selection SQL and the `mode=` log field belong to phase 2.\n\n### `.un/skills/devsecops/config.json`\n- **New `test_groups` entry.** `\"test_precompute_similar_ann_refresh.py\"` maps to `engine/server/db/jobs/precompute-similar-ann.py` and `engine/server/data/embedding_space.py`, as the plan says.\n\n### `tests/active/test_precompute_similar_ann_refresh.py`\n- **Not written this turn.** This phase's gate is the audited checkpoint in `tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py`, and I was asked for production code only. I did not copy it into `tests/active`. I expect the workflow's promotion step to create the durable file from that checkpoint, and the new `config.json` entry above is already keyed to that name."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Refresh selection",
      "checkpoint": "Seam: the same subprocess boundary and harness as phase 1, in `tests/active/test_precompute_similar_ann_refresh.py`. The module fixture (`tmp_path_factory`) builds a tmp source DB, with `video_embeddings` rowids 1..9 where v9 has a 3-float blob, and an `IDMap2,IVF1,Flat` inner-product index built by an `ENGINE_PY` child, plus its `.json` sidecar. The child's non-zero exit is asserted along with its stderr, so a missing faiss fails the test and does not skip it. Each test creates its cache with `--reset-only` and seeds sentinel rows for `CACHED_LIVE + CACHED_UNTOUCHED`. `test_refresh_rewrites_exactly_cached_live_sources` runs `--refresh-existing --cpu --top-k 3` and asserts: exit 0; `mode=refresh-existing`, `total sources=4` and `done processed=3/4` in stderr; v1\u2013v3 share one `computed_at` > 1 and hold only non-sentinel items ranked 1..n (n \u2264 3), each a LIVE key on DOMAIN other than the source itself; gone1, gone2, (v5, \"\") and v9 have source rows and items equal to the pre-run snapshot; no UNCACHED key has a row; there are still 7 sources. `test_refresh_over_missing_or_empty_cache_is_a_no_op`, parametrised [\"missing\", \"empty\"], asserts exit 0, total 0, done 0/0, both tables present in `sqlite_master`, and 0 sources.",
      "intent": "Under `--refresh-existing`, the shared incremental/refresh selection branch in `precompute-similar-ann.py` inner-joins `video_embeddings` to the read-only attached `similarity_sources`, so the job rewrites exactly the cached sources still in `video_embeddings` and leaves every other cache row as it was.",
      "clauses": [
        {
          "id": "C1",
          "text": "Each cached source still in `video_embeddings` that `build_query_batch` accepts is rewritten with the run's single new `computed_at` and only fresh ranked items, and nothing is selected when the cache is missing or schema-only."
        },
        {
          "id": "C2",
          "text": "Every other cache row, whether a stale source, an empty-domain key or a length-skipped source, is left as it was, and uncached embeddings gain no rows."
        }
      ],
      "files": [
        "engine/server/db/jobs/precompute-similar-ann.py (EDITED)",
        "tests/active/test_precompute_similar_ann_refresh.py (EDITED)"
      ],
      "done": true,
      "outcome": "### engine/server/db/jobs/precompute-similar-ann.py\n- The job now picks a selection mode (`refresh-existing`, `incremental` or `full`) and logs it as `selection mode=%s` just before the `total sources=` line. The checkpoint looks for `mode=refresh-existing` in the output.\n- The existing incremental branch now also runs under `--refresh-existing`. Both modes attach the output cache read-only as `out_cache` and collect a list of rowids before any writes, as incremental already did. Only the SELECT differs:\n  - **`--refresh-existing`:** `video_embeddings` is inner-joined to `out_cache.similarity_sources` on both `video_id` and `instance_domain`.\n  - **`--incremental`:** keeps its `LEFT JOIN ... WHERE s.video_id IS NULL`.\n- Effect on the cache:\n  - Only cached sources that are still in `video_embeddings` are selected and rewritten, all with the run's single `computed_at`.\n  - Stale cache rows are never selected, so they are left as they were. So is a key that only matches on `video_id`, like `(\"v5\", \"\")`.\n  - A cached source with the wrong embedding length is counted in `total sources` but dropped by `build_query_batch`, so its row is also left alone.\n  - Embeddings that aren't cached are not selected, so they gain no rows.\n- A missing or schema-only cache selects nothing, so the run logs 0 total and 0/0 processed. The existing `connect_db` + `ensure_schema` step creates and commits both tables before the attach, so the tables are there afterwards.\n- Nothing else in the job changed: the search, the recording, the full-scan path and incremental's results are all as before.\n\n### tests/active/test_precompute_similar_ann_refresh.py\nNot touched. The phase's files list names it, but the gating checkpoint lives at `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py`, and this step's job is only the production code.\n\nI did not run the checkpoint; the workflow's run is the one that counts."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Updater argv",
      "checkpoint": "Seam: the function boundary of `updater-worker.py`. The module is loaded in-process with `importlib.util.spec_from_file_location` from `JOBS_DIR / \"updater-worker.py\"`, following `test_host_normalisation._load_job`. `tests/active/test_updater_precompute_cmd.py::test_updater_builds_refresh_command`, parametrised over `use_gpu` \u2208 {True, False}, asserts that `similarity_precompute_cmd(...)` with fixed tmp_path `Path`s and `python_bin=\"python3\"` equals, as a list, the old literal with `--refresh-existing` in place of `--recreate-out-db` plus the `[\"--gpu\", \"--gpu-device\", \"0\"]` or `[\"--cpu\"]` suffix, and that `--recreate-out-db` is not in it. `test_cpu_fallback_keeps_refresh` asserts `module._to_cpu_cmd(gpu_cmd) == cpu_cmd`.",
      "intent": "The updater's precompute stage builds its command through a module-level `similarity_precompute_cmd` in `updater-worker.py` that runs `--refresh-existing` in place of `--recreate-out-db`, and the CPU retry keeps that flag.",
      "clauses": [
        {
          "id": "C1",
          "text": "For both `use_gpu` values, `similarity_precompute_cmd` returns the previous argv with `--recreate-out-db` replaced by `--refresh-existing`."
        },
        {
          "id": "C2",
          "text": "`_to_cpu_cmd` applied to the GPU argv gives the CPU argv, keeping `--refresh-existing`."
        }
      ],
      "files": [
        "engine/server/db/jobs/updater-worker.py (EDITED)",
        "tests/active/test_updater_precompute_cmd.py (NEW)",
        ".un/skills/devsecops/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/db/jobs/updater-worker.py`\n- New module-level `similarity_precompute_cmd(*, python_bin, script_path, db_path, index_path, out_path, use_gpu) -> list[str]`. It sits after `systemctl_cmd` and uses the same keyword-only style. It returns the precompute argv the updater used to build inline, token for token. The one change is that `--refresh-existing` now takes the slot `--recreate-out-db` held. The argv ends in `--gpu --gpu-device 0` when `use_gpu` is true and `--cpu` otherwise (C1). Paths are passed through `.as_posix()`, as they were before.\n- `main`'s precompute stage now gets `precompute_cmd` from `similarity_precompute_cmd(...)` and no longer builds the list and appends the accelerator flags itself. `run_with_cpu_fallback` still runs it. `_to_cpu_cmd` is unchanged: it drops only `--gpu` and `--gpu-device <n>`, so a CPU retry keeps `--refresh-existing` in place (C2). The module now contains no `--recreate-out-db` literal.\n\n### `.un/skills/devsecops/config.json`\n- Registered the test group `\"test_updater_precompute_cmd.py\": [\"engine/server/db/jobs/updater-worker.py\"]`. Phases 1\u20132 did the same for `test_precompute_similar_ann_refresh.py`: the group is registered now and the test file itself lands in `tests/active/` when the checkpoint is promoted.\n\n### `tests/active/test_updater_precompute_cmd.py`\n- Not created in this step. The step asked for production code only, and the checkpoint in `tests/tmp/` carries this phase. Following the phase 1\u20132 pattern, promoting it into `tests/active/` under this name is left to the promotion step. The checkpoint file was not touched."
    }
  ],
  "digests": {
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py": "cdf46625607a92ded0bf999aba4f225c1bbbdecfb377afa15a5c8d1d0214d265",
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py": "fa777593311b4ca275900c6eb0f7c2ff84d2a22589893aaec118361ba59875d4",
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py": "74418b37fb48f3a5582313d90bb7dec010ffb620d3da588533f83be2341f30ee"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260930T154127-37f1-dev-flow",
    "20260930T154243-614a-dev-flow"
  ],
  "plan": "docs/project/plans/19-25-similarity-precompute-existing-sources.md",
  "record": "docs/project/plans/19-25-similarity-precompute-existing-sources.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nThe updater's similarity precompute stage currently recreates `similarity-cache.db` and recomputes similarity for every row in `video_embeddings` (`updater-worker.py` passes `--recreate-out-db` to `engine/server/db/jobs/precompute-similar-ann.py`). This build adds a mode that refreshes only the sources already cached and still present in embeddings, rewriting only those entries. The updater switches to that mode. Issue 24 (similarity cache shadow build and swap) is settled to land after this one and will run whichever mode the updater uses, so the updater's precompute stage is rewritten once here.\n\n### Operator decision (approved)\n\nThe mode refreshes exactly cached \u2229 embeddings, as the issue states. Videos added by a merge get no precomputed entry from the updater. The Engine caches them lazily the first time they are requested (the serve-time write path `write_cache` in `engine/server/data/similarity_cache_manager.py` / `_write_cache` in `engine/server/data/similarity_candidates.py`, which is unchanged). Cached sources whose video is no longer in `video_embeddings` are left in the cache untouched, not pruned. The operator accepts that the stage-time gain depends on how many sources are cached: the live cache was built full, so early runs will process nearly all of prod, saving only the new videos and the file recreation.\n\n### Precompute CLI mode\n\n- Add a new flag `--refresh-existing` (store_true) to `precompute-similar-ann.py`, with a help text in the style of the existing flags, e.g. \"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\"\n- Source set: the rows of the source DB's `video_embeddings` whose `(video_id, instance_domain)` matches a row in the output cache's `similarity_sources`, i.e. an INNER JOIN in place of the `LEFT JOIN ... WHERE s.video_id IS NULL` used by `--incremental`. It is read the same way `--incremental` reads today: ATTACH the output cache read-only (`file:...?mode=ro`) to the source connection as `out_cache`, materialise the matching rowids into a list, DETACH, then iterate with `iter_embedding_rows_by_rowids`. `total_sources` is the length of that list.\n- Only that set is processed. The FAISS search, top-k selection, self-exclusion, `fetch_similarity_targets_chunked`, batching, the commit every 500, progress logging and soft-stop handling all stay as they are.\n- Per processed source, keep the current rewrite semantics through the existing `record_similarities`: upsert `similarity_sources.computed_at` (one `computed_at` for the run, as today), delete that source's old `similarity_items`, insert the fresh ranked top-k.\n- No other row is written or deleted. There is no global DELETE and no file recreation. Cached sources absent from `video_embeddings` keep their `similarity_sources` and `similarity_items` rows unchanged, and embeddings absent from the cache are not added.\n- A source that is skipped by `build_query_batch` (embedding_dim or embedding length mismatch) is not rewritten, the same behaviour as the other modes.\n- `--refresh-existing` combined with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` is a usage error reported through argparse (`parser.error` or a mutually exclusive group), exiting non-zero before any file is touched. `--cpu`/`--gpu` stay required as today.\n- If the output cache file does not exist or has no `similarity_sources` rows, the run creates the schema (via the existing `connect_db` + `ensure_schema`), processes 0 sources and exits 0. `ensure_schema` must run on the output DB before the read-only ATTACH, as the current code order already does.\n- Logging reuses the existing lines: `total sources=%d` reports the size of the refresh set, and `done processed=%d/%d` reports the result. A mode indicator may be added to an existing log line if it fits the file's style. No new log format is required.\n\n### Updater precompute stage\n\n- In `engine/server/db/jobs/updater-worker.py`, the `precompute_cmd` passes `--refresh-existing` in place of `--recreate-out-db`. Nothing else in the command changes: `--db`, `--index`, `--out`, `--top-k 1000`, `--nprobe 16`, `--search-batch-size 1024`, `--gpu --gpu-device 0` / `--cpu`, `run_with_cpu_fallback` with `stage=\"precompute-similar-ann\"`.\n- The service stop/start sequence, the failure-injection flags and the other stages are unchanged. Moving the service start before the precompute is issue 24's scope.\n\n### Documentation\n\n- `engine/server/db/jobs/docs/UPDATER_WORKER.md` step 10 currently says `precompute-similar-ann.py --incremental`, which does not match the code (`--recreate-out-db`). Correct it to describe `--refresh-existing`: only already-cached sources still in embeddings are rewritten, new videos are cached at serve time, and stale cached sources are left in place.\n- Document `--refresh-existing` in the precompute section of `DATA_BUILD.md` alongside the existing flags, including its exclusivity with `--incremental`/`--reset`/`--reset-only`/`--recreate-out-db`.\n- The initial dataset build (`scripts/run-dataset-build.sh`, and DATA_BUILD.md's full-build example) keeps its full `--recreate-out-db` / `--reset` rebuild, unchanged.\n\n### Tests and validation\n\n- Tests write only temporary copies of the source DB, FAISS index and similarity cache, never the shared `whitelist.db` or `similarity-cache.db` (these are symlinked across worktrees per `docs/project/issues/plan.md`).\n- Processed set: with a cache holding some sources that are in embeddings, some that are not (stale), and embeddings that are not cached, a `--refresh-existing` run processes exactly cached \u2229 embeddings (verified by row state and by the `total sources=` / `done processed=` counts).\n- Rewrite: every processed source has the new run's `computed_at` and a freshly inserted item set (its prior sentinel items are gone).\n- Untouched: stale cached sources keep byte-identical `similarity_sources` and `similarity_items` rows, and uncached embeddings gain no rows.\n- Empty or missing cache: exits 0 with the schema present and 0 sources.\n- Flag conflicts: each forbidden combination exits non-zero with the output file unchanged.\n- Updater: the precompute command the updater builds contains `--refresh-existing` and not `--recreate-out-db`.\n- \"Updater stage time drops against the full-rebuild baseline\" is an operator measurement on main after the merge (the orchestrator smoke test's `similarity_precompute` stage duration can serve as the figure). It is not an automated gate in this build.\n\n### Baseline suite state\n\nThe pre-build suite exited 0 (baseline variant: false). Resolved paths: active tests `tests/active`, working `tests/tmp`, plans `docs/project/plans`, delete_me `delete_me`, archive `tests/archive`, project dir `/home/enduser/code/PeerTube-browser`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.\n\n### Out of scope\n\n- Shadow build, build marker, gate, swap and Engine reopen (issue 24).\n- Pruning stale cached sources, and precomputing new sources in the updater.\n- Changes to the Engine's serve-time cache read/write path.\n- Running the new mode against the shared `similarity-cache.db` (that happens on main after the merge).\n</requirements>\n\n<conflicts>\nengine/server/db/jobs/docs/UPDATER_WORKER.md step 10 says the updater runs `precompute-similar-ann.py --incremental`, but `updater-worker.py` actually passes `--recreate-out-db`. The build resolves this by correcting the doc to the new `--refresh-existing` mode.\nThe issue's validation \"Updater stage time drops against the full-rebuild baseline\" vs the live cache's state: `similarity-cache.db` is built full by `--recreate-out-db`, so cached \u2229 embeddings is nearly all of prod and the drop will be small at first. The operator accepted this and made it a measurement, not a gate.\ndocs/project/issues/plan.md row 4b (issue 24) says to reuse `swap_readonly_connection` for the reopen, while issue 24's triage says the reopen does not use it. This is not in this build's scope and is noted only for issue 24.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe change touches three places: the precompute CLI, one line of the updater, and two docs. The tests are two new files under `tests/active`.\n\n**Precompute CLI (`engine/server/db/jobs/precompute-similar-ann.py`).** Add `--refresh-existing` as a store_true flag next to `--incremental`, with a help text in the same one-sentence style (\"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\"). Right after `parse_args()`, and before the existing `--cpu`/`--gpu` check, add one `parser.error` check: if `--refresh-existing` is set together with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`, argparse prints a message naming the conflicting flags and exits with code 2. Nothing has been opened at that point: no source connection, no unlink, no `connect_db`. So the output file is guaranteed to be unchanged. Putting the check before the cpu/gpu check means `--refresh-existing --reset-only` (which does not need `--cpu`) gets the specific conflict message and not the cpu/gpu one.\n\nThe source selection extends the existing `--incremental` branch rather than adding a second copy of it. The branch condition becomes \"incremental or refresh-existing\". The ATTACH of the output cache read-only (`file:...?mode=ro`) as `out_cache`, the rowid materialisation, the DETACH, `iter_embedding_rows_by_rowids` and `total_sources = len(...)` stay shared. Only the SELECT differs: an INNER JOIN of `video_embeddings` to `out_cache.similarity_sources` on `(video_id, instance_domain)` for refresh, and the current LEFT JOIN / IS NULL for incremental. A short comment in the style of the one already there says what refresh selects. Everything after selection is untouched: FAISS search, top-k, self-exclusion, `fetch_similarity_targets_chunked`, `record_similarities`, the commit every 500, progress and soft-stop.\n\nHow each CLI requirement is met:\n- **Processed set = cached \u2229 embeddings.** The INNER JOIN produces exactly this set. Stale cached sources are not in `video_embeddings`, so they never enter it. Uncached embeddings have no matching `similarity_sources` row, so they are excluded too.\n- **Rewrite semantics.** Unchanged: the existing `record_similarities` upserts `computed_at` (one value per run, set once as today), deletes that source's old items and inserts the new ranked top-k.\n- **No other writes.** Refresh does not take the `--reset` DELETE path or the `--recreate-out-db` unlink path; the parser check blocks both combinations. The only write in the loop is `record_similarities` for a selected source.\n- **Skipped rows.** `build_query_batch` still drops dim/length mismatches before `record_similarities`, so those sources keep their old rows, as in the other modes.\n- **Empty or missing cache.** The current order already runs `connect_db` + `ensure_schema` on the output before the read-only ATTACH. `ensure_schema` uses `executescript` with DDL only, so the tables are on disk when the attach reads them. The join returns no rows, `total sources=0` and `done processed=0/0` are logged, and the exit code is 0.\n- **Logging.** The existing `total sources=%d` line gets a `mode=` field (full / incremental / refresh-existing), in the file's key=value style next to lines like `faiss acceleration=cpu`. There is no new log line. `done processed=%d/%d` is unchanged.\n\n**Updater (`engine/server/db/jobs/updater-worker.py`).** In `precompute_cmd`, `--recreate-out-db` is replaced by `--refresh-existing`, so the argv is otherwise identical. To test the command without running the pipeline, the list construction moves into a small module-level builder next to `systemctl_cmd`, which is the existing precedent for a command builder in this file. It takes python_bin, script path, prod db, index, similarity db and use_gpu, and returns the same list; `main` calls it in place of the inline literal. The GPU/CPU suffix and `run_with_cpu_fallback(stage=\"precompute-similar-ann\")` behave as before. `_to_cpu_cmd` removes only `--gpu`/`--gpu-device`, so the new flag passes through the CPU retry.\n\n**Docs.**\n- `UPDATER_WORKER.md` step 10 is rewritten: it runs `precompute-similar-ann.py --refresh-existing`, which rewrites only sources already in the cache that are still in `video_embeddings`. New videos are cached by the Engine the first time they are requested, and stale cached sources are left in place.\n- `DATA_BUILD.md` \u00a75 gets a short flag note after the example. It lists `--incremental`, `--recreate-out-db`, `--reset`/`--reset-only` and the new `--refresh-existing`, and says the new flag cannot be combined with the other four. The \u00a75 full-build example and `scripts/run-dataset-build.sh` are not changed.\n\n**Tests (new, under `tests/active`).**\n- `test_precompute_similar_ann_refresh.py` builds everything in `tmp_path`:\n  - a tiny source DB whose `video_embeddings` hold one model_name/dim, a few rowids and normalised float32 vectors;\n  - a flat IP FAISS index with rowid ids, plus the `.json` sidecar that `assert_index_matches_embeddings` requires;\n  - a cache seeded with sentinel rows: a few cached sources that are in embeddings, a few stale ones that are not, and some embeddings left uncached.\n- The job runs as a subprocess with `--cpu`, the same way `test_precompute_random_rowids.py` runs its job. The test asserts:\n  - the processed set, from row state and from the `total sources=` and `done processed=` counts in stderr;\n  - that every processed source has one shared new `computed_at` greater than the sentinel, and that none of its sentinel items remain;\n  - that stale sources' `similarity_sources` and `similarity_items` rows are identical before and after, and that uncached embeddings have no rows;\n  - that a missing cache file and a schema-only empty cache both exit 0, have the schema, and hold 0 sources;\n  - that each of the four forbidden combinations exits non-zero and leaves the output file byte-identical and at the same mtime, or absent if it was absent.\n- A second small test loads `updater-worker.py` through importlib, the way `test_host_normalisation.py` does. It asserts that the builder's output contains `--refresh-existing` and not `--recreate-out-db`, for both use_gpu values.\n- No test touches the shared `whitelist.db` or `similarity-cache.db`.\n\n### Alternatives considered\n\n- **Argparse mutually exclusive group instead of `parser.error`.** Rejected. One group of all five flags would also reject combinations that work today among the other four, for example `--reset` with `--incremental` or `--recreate-out-db` with `--incremental`. That is a behaviour change nobody asked for. argparse cannot nest groups to say \"exclusive with each of these, but not the others among themselves\". A single explicit check is clearer and changes nothing else.\n- **A separate `elif args.refresh_existing` branch copying the ATTACH/materialise/DETACH code.** Rejected in favour of sharing the incremental branch and changing only the SQL. The two modes differ in one join, and duplicating the ATTACH handling would let them drift apart.\n- **Testing the updater's command by reading the source text or AST of `updater-worker.py`, or by running `main` with `run_with_cpu_fallback` stubbed out.** A source-text check can pass while the command actually built is wrong. Driving `main` needs locks, systemctl, crawler and staging stubs, which is a lot of setup for one argv assertion. Extracting a builder is a small refactor with an existing precedent (`systemctl_cmd`), and it leaves the command itself unchanged.\n- **Returning early before loading the FAISS index when the refresh set is empty.** Rejected. It would save a trivial amount on an empty cache but reorder a path the other modes share, and it would skip the embedding-space verification. The run still reads and checks `--index` and resolves the embedding space, so an empty refresh needs a valid index and non-empty embeddings, as the other modes do.\n\n### Gotchas and risks\n\n- **Interrupted runs now leave a usable cache.** Because refresh never truncates, a failure or soft stop partway through leaves a cache where some entries are new and others are one run older, all still valid. With `--recreate-out-db`, the same failure left a truncated cache. If a GPU run fails and falls back to CPU, the retry reprocesses the same set: the earlier attempt only rewrote sources already in the set, so the join returns the same rows, and the result is idempotent.\n- **The Engine's lazy writes change which sources get refreshed.** Sources the Engine cached lazily between runs join the next run's refresh set and get rewritten at the updater's `--top-k 1000`, whatever limit the Engine wrote them with. This is the intended behaviour of cached \u2229 embeddings, but it means the set grows with traffic and does not shrink.\n- **Stale sources stay in the cache.** Their items may point at videos that no longer exist. This was accepted and is out of scope; the Engine's read path already filters targets.\n- **Read-only ATTACH while the write connection is open.** The ATTACH runs on the source connection while `out_db` is open for writing on the same file. This is the pattern `--incremental` already uses. Nothing is written before the rowids are materialised and the database is detached, so there is no lock contention.\n- **faiss in the test environment.** The new test needs faiss, the same dependency the job has. If the test environment lacks it, the test should fail loudly rather than skip, so the gate cannot pass without running.\n- **Existing doc and log wording.** `ORCHESTRATOR_SMOKE_TEST.md` line 16 says \"incremental similarity precompute\". That was already inaccurate and is not in the requirements' doc list, so it is noted here and left alone unless the operator wants a one-word fix. The smoke test itself only checks that the similarity DB file exists, which refresh still satisfies because it creates the schema. The updater's description string (\"full ANN rebuild\") is untouched.\n\n### Tradeoffs the operator accepts\n\n- **Stage time.** The stage now does work proportional to the number of cached sources that are still live, not all embeddings. The live cache was built full, so early runs save only the new videos and the file recreation. The gain grows only if the cache is ever rebuilt smaller or pruned, and pruning is out of scope.\n- **New videos after a merge.** Each new video gets no precomputed entry. Its first request pays the serve-time ANN cost and the lazy write.\n- **Stale sources.** They keep taking up cache space indefinitely.\n- **Empty-refresh requirements.** An empty refresh still needs a valid index and embeddings. This is a deliberate simplification: it keeps one code path, and the upgrade path, if it ever matters, is an early exit after selection.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impacts>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"argparse definition in main() (lines 277-334): new --refresh-existing flag\">\n**What changes.** A new `parser.add_argument(\"--refresh-existing\", action=\"store_true\", help=\"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\")` goes right after `--incremental` (lines 329-333), in the same multi-line style. `--incremental`'s help reads \"Compute only for videos that do not exist in similarity_sources.\" and the new help mirrors it. Argparse gives the attribute `args.refresh_existing`.\n\n**What depends on it.** The conflict check, the selection branch and the `mode=` log field (all below), the updater's new builder, and the new subprocess test. No other script or test parses this CLI. `scripts/run-dataset-build.sh` and the smoke test only call it.\n\n**Regression risk: low.** It is an additive store_true flag. The only way to break it is a typo in the dest name. `args.refresh_existing` is read in three places, so an inconsistent spelling would raise AttributeError at runtime and not at parse time. The new test catches that because it runs the real CLI.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"post-parse validation (lines 334-336): new parser.error conflict check before the --cpu/--gpu check\">\n**What changes.** Between `args = parser.parse_args()` (334) and `if not args.reset_only and not (args.cpu or args.gpu): parser.error(...)` (335-336), one check is added. If `args.refresh_existing` is set together with any of `incremental`, `reset`, `reset_only` or `recreate_out_db`, it calls `parser.error(...)` naming the conflicting flags. That exits with code 2 and prints the usage to stderr.\n\n**What depends on it.** The guarantee that the output file is untouched on a forbidden combination. That holds only because nothing has run yet: `connect_source_db` is at 370, the `--recreate-out-db` unlink at 373-386, the `--reset-only` unlink at 388-406, `connect_db`/`ensure_schema` at 408-409, and the `--reset` DELETE at 410-412. `logging.basicConfig` (338) and the signal handlers (362-367) also come later. The test's byte-identical/mtime/absent assertions for the four combinations depend on it.\n\n**Regression risk: medium.** It must stay *before* line 335. Otherwise `--refresh-existing --reset-only` without `--cpu` would still exit 2, but with the cpu/gpu message, and the test would need to match the message to notice. It must not be placed after `connect_db`. Combinations among the other four flags must not be rejected: `--reset --incremental` and `--recreate-out-db --incremental` work today and are not in scope. `--gpu-device` is validated much later (425-426) and is unaffected.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"source selection branch (lines 433-463): `if args.incremental:` becomes incremental-or-refresh, SQL chosen per mode\">\n**What changes.** The condition becomes `if args.incremental or args.refresh_existing:`. The shared parts stay as they are: `out_uri = f\"file:{...}?mode=ro\"` (437), `ATTACH DATABASE ? AS out_cache` (438), the rowid list comprehension (439-451), `DETACH DATABASE out_cache` (452), `iter_embedding_rows_by_rowids` (453) and `total_sources = len(pending_rowids)` (454). Only the SELECT text differs:\n- refresh: `SELECT e.rowid FROM video_embeddings e JOIN out_cache.similarity_sources s ON s.video_id = e.video_id AND s.instance_domain = e.instance_domain`;\n- incremental: the current LEFT JOIN \u2026 `WHERE s.video_id IS NULL`.\n\nThe existing comment (434-436) gets a one-line companion saying what refresh selects. The variable name `pending_rowids` still fits both modes.\n\n**What depends on it.**\n- The processed set, which must equal cached \u2229 embeddings.\n- `iter_embedding_rows_by_rowids` (61-76), which batches rowids 512 at a time under SQLite's variable limit.\n- The progress/ETA maths (519-541) and the `done processed=%d/%d` total.\n- The ATTACH needs the source connection opened with `uri=True` (`connect_source_db`, 52-58), which it is.\n- The attached file must already have the schema. `connect_db` + `ensure_schema` (408-409) run first, and `executescript` commits pending work before running DDL in autocommit, so a missing or empty cache is attachable and has the tables.\n\n**Regression risk: medium.**\n- The INNER JOIN is on raw `(video_id, instance_domain)` text. The Engine's lazy writer stores `source.get(\"instance_domain\") or \"\"` (`similarity_cache.py:110`), so a source cached with an empty domain never joins. That is correct: it is not \"still in embeddings\" under the same key.\n- A duplicated `similarity_sources` key cannot produce duplicate rowids, because the table has a PK on `(video_id, instance_domain)`.\n- Order: without an ORDER BY, rowids come back in join order. Nothing depends on the order except commit batching.\n- `--incremental` behaviour must stay byte-for-byte the same. A careless refactor of the shared block (for example moving the DETACH) would change it, and no existing test covers `--incremental`.\n- Issue 08 (stable ANN ids, plan wave 5a) will later migrate this job from rowid to `ann_id`. This join is one more site it must convert.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"`total sources=%d` log line (line 464): gains a mode= field\">\n**What changes.** `logging.info(\"total sources=%d\", total_sources)` becomes something like `logging.info(\"total sources=%d mode=%s\", total_sources, mode)`, where mode is `full` / `incremental` / `refresh-existing`. It is derived from args; the precedence when `--incremental` is combined with `--reset` should be spelled out, and stays `incremental`. The `done processed=%d/%d elapsed=%s` line (562-567) and the soft-stop line (554-560) do not change.\n\n**What depends on it.** Only the new test, which parses stderr: `basicConfig` (338) logs to stderr with format `%(levelname)s %(message)s`, so the line is `INFO total sources=N mode=...`. A grep of the repo outside the plan docs finds no other consumer of `total sources` or `done processed`. The updater's `run_cmd` does not capture child output, and the smoke test parses only the updater's `run:`/`done:` lines.\n\n**Regression risk: low.** The test's regex must be tolerant of the added field, for example `total sources=(\\d+)`.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"unchanged dependencies used by refresh: ensure_schema (140-167), record_similarities (229-272), build_query_batch (93-107), the search loop (472-551), the --recreate-out-db and --reset-only unlink paths (373-406), the --reset DELETE (410-412), resolve_embedding_space / faiss.read_index / assert_index_matches_embeddings (414-420), set_nprobe (110-123)\">\n**What changes.** Nothing. Refresh relies on each of these unchanged:\n- `record_similarities` upserts `computed_at` (one value per run, set at 465 in epoch ms), deletes the source's items and inserts the new ranked items.\n- `build_query_batch` silently drops dim/length mismatches, so those sources keep their old rows.\n- The unlink and DELETE paths are unreachable under refresh because the conflict check blocks them.\n- The embedding-space check still runs on an empty refresh, so an empty refresh needs a readable index, a `.json` sidecar with a matching `model_name`/`embedding_dim`, and non-empty `video_embeddings`. Otherwise `resolve_embedding_space` raises \"No embeddings found\" and the run exits non-zero.\n\n**What depends on it.** Every mode shares this code. The new test's fixture must satisfy it:\n- `video_embeddings` columns `video_id, instance_domain, embedding, embedding_dim, model_name`, with one model/dim pair;\n- index ids equal to rowids > 0, since the loop drops `rowid_int <= 0` and self-matches;\n- a `<index>.json` sidecar with `model_name` and `embedding_dim` (`embedding_space.py:68-89`).\n\n**Regression risk: low (no edit).** Two test-fixture caveats:\n- `index.search(query, top_k + 1)` on a tiny index returns -1 ids, which are filtered out, so the item count is below `--top-k`. Assertions should not expect exactly top_k items.\n- `set_nprobe` calls `faiss.extract_index_ivf`, which raises on a flat index; this is caught by `except Exception` at 116.\n</impact>\n<impact path=\"engine/server/data/embedding_space.py\" element=\"resolve_embedding_space / assert_index_matches_embeddings\">\n**What changes.** Nothing.\n\n**What depends on it.** The refresh run and the new test fixture:\n- The sidecar must be `f\"{index_path}.json\"` with `model_name` equal to the DB's single `model_name` and `embedding_dim` equal to the dim.\n- `index.d` must equal the dim.\n- An empty `video_embeddings` table raises.\n\n**Regression risk: none from code.** The one risk is fixture mistakes, which make the test fail with a RuntimeError message in stderr.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"new module-level command builder placed next to systemctl_cmd (lines 401-412)\">\n**What changes.** A new keyword-only function in the `systemctl_cmd` style (`*,` parameters, one-line `\"\"\"Handle ...\"\"\"` docstring, returns `list[str]`). It takes `python_bin`, the script path, the prod db, the index, the similarity db and `use_gpu`. It returns the exact list at lines 1114-1134, with `--recreate-out-db` replaced by `--refresh-existing`: `[python_bin, script.as_posix(), \"--db\", prod, \"--index\", index, \"--out\", sim, \"--top-k\", \"1000\", \"--nprobe\", \"16\", \"--search-batch-size\", \"1024\", \"--refresh-existing\"]` plus `[\"--gpu\", \"--gpu-device\", \"0\"]` or `[\"--cpu\"]`.\n\n**What depends on it.** `main()` (the call site below) and the new updater test. That test loads the module with `importlib.util.spec_from_file_location` exactly as `tests/active/test_host_normalisation.py:78-87` does. Loading under the root test env works today: the module imports only stdlib, `scripts.cli_format` and `data.moderation`, and puts `server_dir` on `sys.path` itself (21-33).\n\n**Regression risk: medium, because of naming.** `main()` already has a local variable `precompute_cmd` (1114). If the builder is named `precompute_cmd` and main writes `precompute_cmd = precompute_cmd(...)`, Python treats the name as local for the whole of `main` and raises UnboundLocalError. That would happen only at the precompute stage, after the merge and ANN rebuild, which is the worst place for a failure. Use a distinct name (for example `build_precompute_cmd` / `similarity_precompute_cmd`), or rename the local. Paths should be passed as `Path` and converted with `.as_posix()` inside the builder, as the current literal does, so the argv strings are identical.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"main(): precompute stage call site (lines 1110-1139)\">\n**What changes.** The inline list literal and the `if args.use_gpu` suffix (1114-1134) are replaced by one call to the builder. `run_with_cpu_fallback(precompute_cmd, stage=\"precompute-similar-ann\", cwd=repo_root)` (1135-1139) is unchanged. `--fail-after-merge-before-similarity` (1110-1113) stays before it.\n\n**What depends on it.**\n- The production updater run. The Engine is stopped from the merge through this stage and started in the `finally` (1140-1150). It still is: issue 24 will move that later.\n- The smoke test, whose `similarity_precompute` stage duration is parsed from the `run:`/`done:` log lines that `run_cmd` writes (the marker is the script name, which is unchanged).\n- `purge_hosts` on the similarity DB (844-873, 1066-1074) runs earlier in the same run. It deletes rows for stale or denied hosts, so those sources leave the refresh set. That is the only pruning left, now that recreation is gone.\n\n**Regression risk: medium (behaviour, accepted).**\n- The cache is no longer truncated and rebuilt. New merged videos get no precomputed entry, and stale sources stay.\n- A cache that is missing at run time (first deployment, or a deleted file) now stays empty instead of being fully built. The stage logs `total sources=0` and exits 0, so the updater reports success with an empty cache. Worth stating in UPDATER_WORKER.md: the initial full build is `DATA_BUILD.md` \u00a75 / `run-dataset-build.sh`.\n- The GPU\u2192CPU retry reprocesses the same set, and the argv passes through `_to_cpu_cmd` unchanged apart from the GPU flags.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"_to_cpu_cmd (361-377) and run_with_cpu_fallback (380-398)\">\n**What changes.** Nothing.\n\n**What depends on it.** The refresh argv's CPU retry. `_to_cpu_cmd` drops `--gpu` and `--gpu-device <n>` and appends `--cpu`, so `--refresh-existing` survives. The retry cannot trip the new conflict check, because none of the four conflicting flags is ever in the list.\n\n**Regression risk: low.** The retry is idempotent: a partial GPU attempt only rewrote rows that were already cached, so the set is the same. The GPU attempt may have committed batches of 500 before failing, and the retry rewrites those again with a new `computed_at`.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"parse_args description string (lines 102-105) and module docstring (line 2)\">\n**What changes.** Nothing, as the plan says. The description says \"merge -> incremental jobs -> full ANN rebuild -> start service\". \"full ANN rebuild\" refers to the index, not the similarity cache, so it is not made wrong by this change.\n\n**Regression risk: none.** Listed so the next step does not treat it as missed.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-orchestrator-smoke.py\" element=\"validate_outputs (735-760), assert_worker_log (482-500), parse_stage_durations (503-528), per-run path setup (864-872, 917-919)\">\n**What changes.** No edit. The behaviour it observes does change. Each run or scenario directory starts with no `similarity-cache.db` (the paths at 866/919 are fresh and not copied from prod). Under refresh the precompute creates the schema-only file and processes 0 sources, where before it built a full cache.\n\n**What depends on it.** The check at 750 only requires the file to exist, so it still passes. The markers still include `precompute-similar-ann.py`. The `similarity_precompute` duration will drop sharply, which is what it measures now: it is no longer a meaningful precompute timing.\n\n**Regression risk: low for pass/fail. The coverage lost is real:** the smoke run no longer exercises the FAISS search or write path of the precompute at all. That is not within the gate (the script is not in `tests/active`); note it for the operator.\n</impact>\n<impact path=\"scripts/run-dataset-build.sh\" element=\"similarity stage (lines 251-258)\">\n**What changes.** Nothing. It keeps `--top-k 20 --nprobe 16 --recreate-out-db \"${ACCEL}\"` as the full-build path.\n\n**What depends on it.** It is the documented way to build the initial full cache that refresh then maintains. It still works, because `--recreate-out-db` without `--refresh-existing` is allowed.\n\n**Regression risk: none.** Documentation consistency: the plan's DATA_BUILD \u00a75 flag note must describe `--recreate-out-db` as this script uses it.\n</impact>\n<impact path=\"engine/server/data/similarity_cache.py\" element=\"ensure_similarity_schema (19-46) and store_similarity_cache (\u224896-120): the Engine's own schema and serve-time writer\">\n**What changes.** Nothing.\n\n**What depends on it.** Refresh's source set grows with Engine traffic: any source the Engine stores lazily joins the next refresh and is rewritten at `--top-k 1000`. The Engine's schema must stay compatible with the job's `ensure_schema` (same tables and PK), because both open the same file. The writer stores `instance_domain or \"\"`, which affects which rows join (see the selection entry).\n\n**Regression risk: none from this build.** The accepted behaviour change (set only grows; pruning only via host purge) is recorded in the plan.\n</impact>\n<impact path=\"engine/server/data/similarity_cache_manager.py\" element=\"read_cached_similarities / should_write_cache / write_cache (42-96)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is the lazy path for new videos, which no longer get precomputed entries. `should_write_cache` writes only when the source has no cached rows, unless the policy is refresh. `read_cached_similarities` treats a count below the limit as a miss when `require_full` is set (61-68). Sources that refresh writes with fewer than top-k items stay partial, as they were under the full build.\n\n**Regression risk: none from this build.** It is the documented consequence: a new video's first request pays the ANN cost and the lazy write.\n</impact>\n<impact path=\"engine/server/data/similarity_candidates.py\" element=\"_write_cache (\u2248259)\">\n**What changes.** Nothing. It is the other half of the lazy write path named in the requirements as unchanged.\n\n**What depends on it.** It is the only way new videos enter the cache after this build, apart from a manual full build.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_precompute_similar_ann_refresh.py\" element=\"new test module (subprocess tests of --refresh-existing)\">\n**What changes.** A new file. It builds a source DB, a FAISS index plus `.json` sidecar, and a seeded cache in `tmp_path`. It runs the job and asserts on:\n- the processed set;\n- the shared new `computed_at` above the sentinel;\n- stale and uncached rows left unchanged;\n- a missing or empty cache giving exit 0 with the schema and 0 sources;\n- the four forbidden combinations exiting non-zero and leaving the file byte-identical, at the same mtime, or absent.\n\n**What depends on it.** The gate. `.un/skills/devsecops/config.json` needs a `test_groups` entry for it (see that entry).\n\n**Regression risk: HIGH, because of the interpreter. The plan's \"run it the way `test_precompute_random_rowids.py` does\" (via `sys.executable`) will not work.** `tests/last_test_validation.json:3-13` shows the suite runs under the root `pixi.toml` env (Python 3.14). That env's dependencies are the harness's own (`pyproject.toml:6`: anthropic, openai, pyyaml\u2026), with no numpy and no faiss. The job imports numpy at line 14, before its faiss guard, so under `sys.executable` it dies with ModuleNotFoundError. The test cannot `import faiss`/`numpy` in-process to build the index either. The established pattern for faiss/numpy work in `tests/active` is `ENGINE_PY` from `conftest.py:32` (`engine/.pixi/envs/default/bin/python`):\n- `test_video.py:197,216-218` builds `faiss.IndexIDMap(faiss.IndexFlatIP(d))` + `add_with_ids` inside an ENGINE_PY child;\n- `test_similar.py:616`, `test_popular_videos.py:92-93` and `test_internal_client_reads.py:144-145` follow the same pattern;\n- each asserts `ENGINE_PY.exists()` with the message \"run `pixi install` in engine/\", which fails loudly rather than skipping, as the plan wants.\n\nSo the job subprocess should run with `str(ENGINE_PY)`, and index construction (and vector normalisation) should happen in an ENGINE_PY child or a small child script. Pure-sqlite fixture work (the source DB with float32 blobs via `array(\"f\")`, the cache seeding, and the byte/mtime checks) can stay in the test process.\n\nOther fixture caveats:\n- The job reads the index with `IO_FLAG_MMAP | IO_FLAG_READ_ONLY` (417). The production index is `IndexIDMap2(IndexIVFPQ)` (`build-ann-index.py:110-113`). I did not verify that the installed faiss (1.13.2 per requirements) accepts the MMAP flag on a flat `IndexIDMap`; if it rejects it, use `IndexIDMap2(IndexIVFFlat(..., nlist=1))`, trained on the tiny set.\n- Rowids must be > 0, and self-matches are excluded.\n- The sidecar needs `model_name` and `embedding_dim`.\n- `computed_at` is in epoch milliseconds, so the sentinel must be small (e.g. 1).\n- The job's `main()` imports `server_config` from `engine/server/api`, so the env var checks in `server_config` apply. They are harmless unless `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` is set to garbage in the environment.\n- Use `cwd=tmp_path` and pass explicit `--db`/`--index`/`--out`, so the shared `whitelist.db`/`similarity-cache.db` defaults (lines 287-289) are never touched.\n- The mtime check needs the forbidden-combo run to open nothing, which the conflict check's placement guarantees.\n</impact>\n<impact path=\"tests/active/test_updater_precompute_cmd.py\" element=\"new test module (name illustrative): importlib load of updater-worker.py, asserts on the builder's argv\">\n**What changes.** A new file. It loads `engine/server/db/jobs/updater-worker.py` with importlib, as `test_host_normalisation.py:78-82` does. It calls the builder for `use_gpu=True` and `False` and asserts that `--refresh-existing` is present and `--recreate-out-db` absent. It could also assert that `_to_cpu_cmd(builder(use_gpu=True))` keeps `--refresh-existing`, a cheap check of the fallback path.\n\n**What depends on it.** The gate and the `config.json` mapping.\n\n**Regression risk: low.**\n- Loading the module runs only module-level code: path setup and imports of `scripts.cli_format` and `data.moderation`, which already work under the root env since `test_host_normalisation` passes.\n- Loading must not call `parse_args` or `resolve_default_engine_service_name`, which shells out to bash. Neither runs at import.\n- Use a distinct `module_name` from `\"updater_worker_job\"` or accept the re-exec; each spec load is a fresh module object, so a collision is harmless.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups map (lines 14-201)\">\n**What changes.** Add entries for the two new test files, mapping each to the sources it covers:\n- the refresh test \u2192 `engine/server/db/jobs/precompute-similar-ann.py` and `engine/server/data/embedding_space.py`;\n- the updater test \u2192 `engine/server/db/jobs/updater-worker.py`.\n\n`test_host_normalisation.py` already maps `updater-worker.py` (99-106), so that file also reruns when the updater changes.\n\n**What depends on it.** The test-selection harness. According to the issue-32 record (`docs/project/plans/archive/01-32-...record.md:1403`), an unmapped test file runs on every invocation.\n\n**Regression risk: low.** If the entries are forgotten, the tests still run (every time), so nothing is lost, only speed.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"ENGINE_PY constant (line 32)\">\n**What changes.** Nothing. It is the import the new refresh test should use (`from conftest import ENGINE_PY`), as `test_internal_client_reads.py:20` and `test_video.py:49` do.\n\n**Regression risk: none.** Importing conftest pulls in `client/backend/server.py` at module level (lines 37-43). That already happens for every test in the directory.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"generated validation record\">\n**What changes.** Nothing by hand. The harness regenerates it and adds entries for the new files.\n\n**Regression risk: none.** Listed only because it references test file names.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\" element=\"Execution Order step 10 (line 53); Outputs (line 28)\">\n**What changes.** Line 53 currently says `Update similarity cache incrementally (precompute-similar-ann.py --incremental)`. That is already wrong: the code passes `--recreate-out-db`. It is rewritten to `--refresh-existing`, with the semantics from the plan: it rewrites only sources already cached and still in `video_embeddings`, new videos are cached lazily by the Engine, and stale sources are left. Line 28 (\"Updated similarity cache\") stays true.\n\nOptionally, add one sentence saying the updater no longer builds a missing or empty cache: the initial full build is `DATA_BUILD.md` \u00a75.\n\n**Regression risk: low.** Doc only.\n</impact>\n<impact path=\"DATA_BUILD.md\" element=\"\u00a75 Precompute similarity cache (lines 252-266); updater cross-reference (line 30)\">\n**What changes.** A flag note is added after the example (after line 263 or 264). It covers `--incremental` (only uncached embeddings), `--recreate-out-db` (delete and recreate the file), `--reset`/`--reset-only` (clear tables / clear and exit), and `--refresh-existing`, which rewrites cached \u2229 embeddings, leaves the other rows alone, and cannot be combined with the other four (exit 2). The example block (256-262) and the `--top-k` paragraph (266) are unchanged.\n\nA pre-existing inaccuracy is not in scope: line 30 points at `engine/server/db/jobs/UPDATER_WORKER.md`, but the file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`. It is a one-word fix if the operator wants it.\n\n**Regression risk: low.** Doc only.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md\" element=\"Purpose list line 16 ('incremental similarity precompute')\">\n**What changes.** Nothing, per the plan (already inaccurate, and not in the requirements' doc list). Recorded so it is a known decision. After this build the accurate wording would be \"refresh of existing similarity cache sources\". The smoke run now produces an empty cache, as described in the smoke-test entry.\n\n**Regression risk: none.** This is doc drift only.\n</impact>\n<impact path=\"docs/project/issues/24-similarity-cache-shadow-swap.md\" element=\"Proposed solution line 15 (`run precompute-similar-ann.py --incremental`), triage notes line 46, gate description line 67\">\n**What changes.** Nothing is required by this plan. Line 15 still names `--incremental`, while lines 46/65 already say the shadow build uses \"whichever mode the updater uses once 25 is delivered\". A one-line comment under `## Comments` or an edit to line 15 to say `--refresh-existing` would keep issue 24 accurate for the next lane.\n\n**What depends on it.** Issue 24's future implementation. Its gate (\"the shadow holds no fewer `similarity_sources` rows than the active file\") works with refresh, because refresh never deletes sources.\n\n**Regression risk: low.** A stale issue text could lead lane 4b to wire `--incremental`.\n</impact>\n<impact path=\"docs/project/issues/25-similarity-precompute-existing-sources.md\" element=\"Status line and issue lifecycle\">\n**What changes.** On delivery, per `docs/project/triage-labels.md` / `issue-tracker.md`, the status becomes `complete` and the file moves to `docs/project/issues/archive/`. The validation item \"Updater stage time drops against the full-rebuild baseline\" was turned into a measurement, not a gate (record line 148). A comment should say so.\n\n**Regression risk: none.** This is bookkeeping, probably owned by a later step.\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"wave 3c row (line 82), 24/25 ordering note (line 125), wave 5a row (line 97)\">\n**What changes.** Nothing. Row 82 lists exactly the two code files this plan touches. Line 125 fixes the order as 25 before 24. Row 97 (issue 08) will later migrate this job's rowid usage, including the new join.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"updater timer paragraph (lines 130-134) and similarity-cache capacity note (line 263)\">\n**What changes.** Nothing. Line 131 says the updater \"precomputes similarity\", which is still true in a general sense. Line 263 says the cache holds 20 per seed (`--top-k 20`), while the updater writes 1000. That inconsistency already existed and is not in scope.\n\n**Regression risk: none.** Listed for completeness.\n</impact>\n</impacts>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\">\nRewrite Execution Order step 10 (line 53, which today wrongly says `--incremental`) to `precompute-similar-ann.py --refresh-existing`. It rewrites only sources already in `similarity_sources` that are still in `video_embeddings`; new videos are cached lazily by the Engine on first request; stale cached sources are left in place. Optionally add that a missing or empty cache stays empty after an updater run, and that the initial full build is `DATA_BUILD.md` \u00a75.\n</doc>\n<doc path=\"DATA_BUILD.md\">\n\u00a75 (lines 252-266): add a short flag note after the example. It covers `--incremental`, `--recreate-out-db`, `--reset`/`--reset-only` and the new `--refresh-existing` (cached \u2229 embeddings; other rows untouched; cannot be combined with the other four, exits 2). The example and the `--top-k` paragraph are unchanged. Optional one-word fix: line 30 points at `engine/server/db/jobs/UPDATER_WORKER.md`, but the file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md\">\nNo change per the plan. Line 16 (\"incremental similarity precompute\") was already inaccurate and is left alone unless the operator asks. The smoke run now yields an empty schema-only similarity cache.\n</doc>\n<doc path=\"docs/project/issues/24-similarity-cache-shadow-swap.md\">\nOptional: line 15 still says the shadow build runs `precompute-similar-ann.py --incremental`. Update it, or add a comment, to say `--refresh-existing` now that 25 is delivered, so lane 4b wires the right mode.\n</doc>\n<doc path=\"docs/project/issues/25-similarity-precompute-existing-sources.md\">\nOn delivery: `Status:` becomes `complete` and the file moves to `docs/project/issues/archive/`. Comment that the stage-time validation became a measurement, not a gate.\n</doc>\n</docs_checklist>\n\n<highest_risk>\ntests/active/test_precompute_similar_ann_refresh.py: the plan says to run the job via `sys.executable` like test_precompute_random_rowids.py, but the suite runs under the root pixi env (Python 3.14, harness deps only, no numpy or faiss per pyproject.toml and last_test_validation.json). The job would die at `import numpy` and the test could not build a FAISS index. It must use conftest's ENGINE_PY for the job and for index construction, as test_video.py and test_similar.py do. The faiss MMAP read flag on a flat IndexIDMap is also unverified.\nengine/server/db/jobs/updater-worker.py (builder + main call site): `main()` already binds a local `precompute_cmd`. Naming the new module-level builder the same makes the name local for all of `main` and raises UnboundLocalError only at the precompute stage, after the merge and ANN rebuild. The switch also means a missing or empty cache is never fully rebuilt by the updater again, while the run reports success.\nengine/server/db/jobs/precompute-similar-ann.py (conflict check + shared selection branch): the check must sit before the cpu/gpu check and before any connect or unlink, or the byte-identical guarantee breaks. The shared ATTACH/materialise/DETACH refactor must leave `--incremental` identical, and no existing test covers `--incremental`.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the files and every entry holds. `precompute-similar-ann.py` matches the line numbers the inventory cites: parse_args at 334, the cpu/gpu check at 335-336, the first file access at 370, the incremental branch at 433-463, and the `total sources` log at 464. `updater-worker.py` matches too: `_to_cpu_cmd` at 361-377, `systemctl_cmd` at 401-412, and the inline `precompute_cmd` at 1114-1134 with `--recreate-out-db` at 1129. The docs match: UPDATER_WORKER.md:53 still says `--incremental`, and DATA_BUILD.md:30 still has the stale path. `similarity_cache.py:110` stores `or \"\"`, and the smoke test's check at 750 only tests that the file exists. `video_embeddings` has `PRIMARY KEY (video_id, instance_domain)` (`build-video-embeddings.py:73`), so the INNER JOIN cannot produce duplicate rowids from either side. That is slightly stronger than the inventory said. One problem remains open: the settled plan tells the refresh test to run the job the way `test_precompute_random_rowids.py` does, through `sys.executable`. That cannot work, because the root env has no numpy or faiss (`pyproject.toml:6`), and the job imports numpy at line 14. The inventory already flagged this, and I report it as a conflict below because the wrong instruction is in the settled plan. The only thing I could not confirm is the MMAP read of a flat index, which the inventory had already marked unverified.\n<question id=\"1\">\nYes, for the production code. The conflict check comes before `connect_source_db`, so a rejected flag combination touches nothing. The shared ATTACH/materialise/DETACH block already works on a cache that `connect_db` + `ensure_schema` has just created. `record_similarities` already gives the rewrite semantics the requirements ask for. The updater change is a one-token swap, and `_to_cpu_cmd` keeps it on the CPU retry. The refresh test is the one part that does not work as the plan words it. It has to run under `ENGINE_PY` (`conftest.py:32`) and build the FAISS index in an ENGINE_PY child, as `test_video.py:197,216-218` does. Run under `sys.executable`, as the plan says, the job dies with ModuleNotFoundError before it parses any arguments.\n</question>\n<question id=\"2\">\n- The updater stops truncating the similarity cache. A missing or deleted cache now stays empty after an updater run, and the run still exits 0 with `total sources=0`.\n- New merged videos are cached only lazily by the Engine.\n- Stale sources stay in the cache. Only `purge_hosts` removes any.\n- Sources the Engine writes lazily join the next refresh at `--top-k 1000`.\n- An interrupted or GPU-failed run leaves a valid, mixed-age cache, not a truncated one.\n- The orchestrator smoke run starts from a fresh similarity path. It now produces a schema-only cache and never exercises the FAISS search or write path. Its `similarity_precompute` duration stops measuring precompute work.\n- Issue 08 gains one more rowid join to convert.\n\nThe inventory records all of these, and the operator accepted them in the requirements.\n</question>\n<question id=\"3\">\n- The conflict check must sit between lines 334 and 335. It must not reject combinations among the other four flags.\n- The shared incremental block must stay byte-identical for `--incremental`. No existing test covers that mode.\n- The updater builder must not be named `precompute_cmd`. The local of that name in `main` would make it UnboundLocalError at the precompute stage.\n- The refresh test needs ENGINE_PY, and so does the index construction.\n- `config.json` `test_groups` should gain entries for both new files.\n- UPDATER_WORKER.md step 10 should say that the initial full build is DATA_BUILD \u00a75 / `run-dataset-build.sh`, because the updater no longer builds a missing cache.\n\n`run-dataset-build.sh` needs nothing: `--recreate-out-db` on its own stays legal.\n</question>\n<question id=\"4\">\nThe CLI gains one mode and one conflict check. Every existing flag combination behaves as before, and the `total sources` log line gains a `mode=` field. The updater's precompute stage changes from delete-and-rebuild-everything to rewrite-only-what-is-already-cached-and-still-embedded. Coverage of new videos moves from the updater to the Engine's first-request lazy write. Stale entries are no longer removed by the stage. A missing cache is no longer rebuilt by the updater.\n</question>\n\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\ntests/active/test_precompute_similar_ann_refresh.py (fixture caveat): I could not confirm whether `faiss.read_index(path, IO_FLAG_MMAP | IO_FLAG_READ_ONLY)` (precompute-similar-ann.py:417) accepts a flat `IndexIDMap(IndexFlatIP)` under the installed faiss. The installed faiss is `faiss-gpu-cu12==1.13.2` per `engine/server/requirements.txt:5`, not faiss-cpu. `test_video.py:216` only builds such an index in memory and never reads one back with MMAP. This needs a probe run under ENGINE_PY before the test is written, and the inventory's fallback (IndexIDMap2 over an nlist=1 IVFFlat) is still the plan B.\ntests/active/conftest.py (ENGINE_PY): the constant is confirmed at line 32. However, `engine/pixi.toml` declares only python and pip. numpy and faiss come from `pip install -r engine/server/requirements.txt` into that env. The \"run `pixi install` in engine/\" hint that the inventory proposes reusing therefore does not by itself provide faiss. A fresh environment will fail on import, not on `ENGINE_PY.exists()`.\n</unconfirmed>\n\n<new_conflicts>\nSettled plan, Tests paragraph: \"The job runs as a subprocess with `--cpu`, the same way `test_precompute_random_rowids.py` runs its job\". That test runs the job through `sys.executable`, and the test \"builds everything in `tmp_path`\", including \"a flat IP FAISS index\". Against it stands the repository: the gate runs under the root pixi env (`tests/last_test_validation.json:3-13`), whose dependencies (`pyproject.toml:6`) include neither numpy nor faiss. `precompute-similar-ann.py:14` imports numpy unconditionally, and faiss at line 17. `precompute-random-rowids.py` works under `sys.executable` only because it needs neither. Followed literally, the plan gives a test that fails on ModuleNotFoundError before argparse, including in the four forbidden-combination cases, which would then \"pass\" on a non-zero exit for the wrong reason. The minimal amendment is to run the job with `str(ENGINE_PY)` and build the index in an ENGINE_PY child, per `test_video.py:197,216-218`. This keeps the plan's intent (a real subprocess, failing loudly without faiss) and changes nothing else.\n</new_conflicts>\n\n<recommendations>\n1. Amend the plan's Tests paragraph as the conflict describes: ENGINE_PY for the job subprocess, and an ENGINE_PY child to build the index. Pure sqlite fixture work and the byte/mtime checks stay in-process. Cost: one sentence in the plan and about 15 lines of child-script string in the test. Without it, the test either cannot pass or passes vacuously on the forbidden combinations.\n2. In the forbidden-combination cases, assert exit code 2 and a stderr fragment naming `--refresh-existing`, not just \"non-zero\". Cost: one assert per case. This is what separates a real argparse rejection from an import crash, which also exits non-zero and also leaves the file untouched.\n3. Before the refresh test is drafted, probe once under ENGINE_PY that `read_index` with `IO_FLAG_MMAP|IO_FLAG_READ_ONLY` loads an `IndexIDMap(IndexFlatIP)`. If it does not, use `IndexIDMap2(IndexIVFFlat, nlist=1)`. Cost: one throwaway run. It avoids a red gate caused by the fixture, not by the code.\n4. Name the updater builder `build_precompute_cmd` (or similar), never `precompute_cmd`. Cost: nothing. The wrong name gives an UnboundLocalError that surfaces only after the merge and the ANN rebuild.\n5. Add the two `test_groups` entries to `.un/skills/devsecops/config.json`: refresh test \u2192 `precompute-similar-ann.py` + `data/embedding_space.py`; updater test \u2192 `updater-worker.py`. Cost: about 8 lines of JSON. If you skip them, both tests run on every invocation, which is slower but not less safe.\n6. Take the optional UPDATER_WORKER.md sentence saying that a missing or empty cache stays empty and that the initial build is DATA_BUILD \u00a75. Cost: one line. Without it, an operator who deletes the cache and expects the updater to rebuild it gets an empty cache and a green run.\n7. Optional one-line fixes, each costing a line: DATA_BUILD.md:30 path (`jobs/docs/UPDATER_WORKER.md`), ORCHESTRATOR_SMOKE_TEST.md:16 wording, and issue 24 line 15 (`--incremental` \u2192 `--refresh-existing`). The issue 24 fix matters most, because lane 4b reads it.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft: `--refresh-existing` for the similarity precompute, wired into the updater\n\n### What has to be tested (step 1)\n\n| Behaviour | Where it is proved |\n|---|---|\n| The processed set is exactly cached \u2229 embeddings, keyed on the raw `(video_id, instance_domain)` | refresh test: row state, plus `total sources=` and `done processed=` in stderr |\n| A processed source gets the run's single `computed_at`, above the sentinel, and fresh items (no sentinel items left) | refresh test |\n| Stale cached sources, including an empty-domain key, keep identical rows. Uncached embeddings gain no rows | refresh test: before/after snapshots |\n| A source dropped by `build_query_batch` (length mismatch) is counted in the total, not processed and not rewritten | refresh test: `done processed=3/4` and an unchanged row |\n| A missing or schema-only cache exits 0, has the schema and holds 0 sources | refresh test, parametrised |\n| Each of the 4 forbidden combinations exits 2, with the output unchanged (same bytes and mtime) or still absent | refresh test, 4 flags \u00d7 {seeded, absent} |\n| The updater's argv is the old one with `--recreate-out-db` swapped for `--refresh-existing`, and the CPU retry keeps the flag | updater test, exact list equality |\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/db/jobs/precompute-similar-ann.py` | flag, conflict check, `mode`, shared selection branch with the SQL chosen per mode, `mode=` in the `total sources` line |\n| `engine/server/db/jobs/updater-worker.py` | new `similarity_precompute_cmd` next to `systemctl_cmd`. `main()` calls it |\n| `tests/active/test_precompute_similar_ann_refresh.py` | new |\n| `tests/active/test_updater_precompute_cmd.py` | new |\n| `.un/skills/devsecops/config.json` | two `test_groups` entries |\n| `engine/server/db/jobs/docs/UPDATER_WORKER.md`, `DATA_BUILD.md`, `docs/project/issues/24-similarity-cache-shadow-swap.md` | doc text below |\n\n---\n\n### `precompute-similar-ann.py`\n\n**Flag**, right after `--incremental` (after line 333), in the same multi-line style:\n\n```python\n    parser.add_argument(\n        \"--refresh-existing\",\n        action=\"store_true\",\n        help=\"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\",\n    )\n```\n\n**Conflict check** goes between `args = parser.parse_args()` (334) and the `--cpu/--gpu` check (335). At that point nothing has run: no logging config, no signal handlers, no connection, no unlink.\n\n```python\n    args = parser.parse_args()\n    if args.refresh_existing:\n        conflicts = [flag for flag, enabled in ((\"--incremental\", args.incremental), (\"--reset\", args.reset), (\"--reset-only\", args.reset_only), (\"--recreate-out-db\", args.recreate_out_db)) if enabled]\n        if conflicts:\n            parser.error(f\"--refresh-existing cannot be combined with {', '.join(conflicts)}\")\n    if not args.reset_only and not (args.cpu or args.gpu):\n        parser.error(\"one of --cpu or --gpu is required unless --reset-only is used\")\n```\n\nWhat this guarantees:\n- `parser.error` exits 2 and prints the usage plus the message to stderr.\n- Combinations among the other four flags are not touched: `--reset --incremental` and `--recreate-out-db --incremental` still work.\n- Because the check comes first, `--refresh-existing --reset-only` without `--cpu` gets the conflict message, not the cpu/gpu one.\n\n**Mode and selection** replace lines 433-464. The `else` (full) branch is kept verbatim.\n\n```python\n        if args.refresh_existing:\n            mode = \"refresh-existing\"\n        elif args.incremental:\n            mode = \"incremental\"\n        else:\n            mode = \"full\"\n        if args.incremental or args.refresh_existing:\n            # Incremental mode compares source embeddings with already-computed rows\n            # from the output cache DB. We materialize only rowids first to avoid\n            # lock contention while writing to the output DB.\n            # Refresh mode selects the complement: embeddings whose source is already cached.\n            if args.refresh_existing:\n                selection_sql = \"\"\"\n                    SELECT e.rowid\n                    FROM video_embeddings e\n                    JOIN out_cache.similarity_sources s\n                      ON s.video_id = e.video_id\n                     AND s.instance_domain = e.instance_domain\n                    \"\"\"\n            else:\n                selection_sql = \"\"\"\n                    SELECT e.rowid\n                    FROM video_embeddings e\n                    LEFT JOIN out_cache.similarity_sources s\n                      ON s.video_id = e.video_id\n                     AND s.instance_domain = e.instance_domain\n                    WHERE s.video_id IS NULL\n                    \"\"\"\n            out_uri = f\"file:{out_db_path.as_posix()}?mode=ro\"\n            src_db.execute(\"ATTACH DATABASE ? AS out_cache\", (out_uri,))\n            pending_rowids = [int(row[\"rowid\"]) for row in src_db.execute(selection_sql)]\n            src_db.execute(\"DETACH DATABASE out_cache\")\n            row_iter = iter_embedding_rows_by_rowids(src_db, pending_rowids)\n            total_sources = len(pending_rowids)\n        else:\n            ...  # unchanged full-scan branch\n        logging.info(\"total sources=%d mode=%s\", total_sources, mode)\n```\n\nInvariants:\n- **Mode precedence.** Refresh cannot be combined with incremental (the parser blocks it). `--incremental` wins over `--reset` / `--recreate-out-db`, whose runs log `mode=incremental`. Those flags alone log `mode=full`. `--reset-only` returns before this line and never logs a mode.\n- **`--incremental` is unchanged.** Its SQL is the same text as before. The ATTACH, materialisation, DETACH and iteration order are the same.\n- **Missing or empty cache is safe to attach.** The ATTACH still runs after `connect_db` + `ensure_schema` (408-409). `executescript` has committed by then, so a missing or empty cache is attachable and has the tables. The join yields `[]`, so the log shows `total sources=0` and `done processed=0/0`, and the exit code is 0.\n- **Writes are limited to the selected set.** Under refresh, the unlink and DELETE paths cannot be reached. The only write is `record_similarities` for rows selected by the join. `computed_at` (465) is still set once per run.\n- **No duplicate rowids.** The PK on `similarity_sources(video_id, instance_domain)` guarantees this.\n\n---\n\n### `updater-worker.py`\n\n**Builder**, placed after `systemctl_cmd` (after line 412) in the same keyword-only style. It is deliberately not named `precompute_cmd`: that name is a local in `main()`, and reusing it would raise UnboundLocalError at the precompute stage.\n\n```python\ndef similarity_precompute_cmd(\n    *,\n    python_bin: str,\n    script_path: Path,\n    db_path: Path,\n    index_path: Path,\n    out_path: Path,\n    use_gpu: bool,\n) -> list[str]:\n    \"\"\"Handle similarity precompute cmd.\"\"\"\n    cmd = [\n        python_bin,\n        script_path.as_posix(),\n        \"--db\",\n        db_path.as_posix(),\n        \"--index\",\n        index_path.as_posix(),\n        \"--out\",\n        out_path.as_posix(),\n        \"--top-k\",\n        \"1000\",\n        \"--nprobe\",\n        \"16\",\n        \"--search-batch-size\",\n        \"1024\",\n        \"--refresh-existing\",\n    ]\n    if use_gpu:\n        cmd.extend([\"--gpu\", \"--gpu-device\", \"0\"])\n    else:\n        cmd.append(\"--cpu\")\n    return cmd\n```\n\n**Call site.** Lines 1114-1134 become the block below. `run_with_cpu_fallback(precompute_cmd, stage=\"precompute-similar-ann\", cwd=repo_root)` and the failure injection at 1110-1113 do not change.\n\n```python\n                precompute_cmd = similarity_precompute_cmd(\n                    python_bin=args.python_bin,\n                    script_path=script_dir / \"precompute-similar-ann.py\",\n                    db_path=prod_db,\n                    index_path=index_path,\n                    out_path=similarity_db,\n                    use_gpu=args.use_gpu,\n                )\n```\n\nThe argv strings are identical to the old literal apart from the one swapped flag. The `run:` log marker (the script name) does not change. `_to_cpu_cmd` passes `--refresh-existing` through unchanged.\n\n---\n\n### `tests/active/test_precompute_similar_ann_refresh.py`\n\nDocstring, in the style of `test_precompute_random_rowids.py`:\n\n```\n\"\"\"`precompute-similar-ann.py --refresh-existing` rewrites exactly the cached sources still in `video_embeddings` and nothing else.\n\n- Over a cache holding three live sources, two gone sources, an empty-domain key and one live source whose blob is too short, the job logs `total sources=4 mode=refresh-existing` and `done processed=3/4`. The three live sources share one new `computed_at` above the sentinel and hold only fresh ranked items. Every other cached row is unchanged, and uncached embeddings gain no rows.\n- Over a missing or a schema-only cache, the job exits 0 with both tables present and no source.\n- With `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`, the job exits 2 naming the conflict, and the output file keeps its bytes and mtime, or stays absent.\n\nThe job and the FAISS index build run under the Engine's pixi interpreter (`ENGINE_PY`), since numpy and faiss live only there. Every file is under tmp_path.\n\"\"\"\n```\n\n**Constants and fixture contents**\n\n```python\nPRECOMPUTE_JOB = ROOT / \"engine\" / \"server\" / \"db\" / \"jobs\" / \"precompute-similar-ann.py\"\nDIM = 4\nMODEL = \"test-model\"\nDOMAIN = \"a.example\"\nSENTINEL_COMPUTED_AT = 1  # computed_at is epoch ms, so any real run is far above this\nLIVE = [f\"v{i}\" for i in range(1, 9)]  # rowids 1..8, valid unit vectors, all in the index\nSHORT = \"v9\"  # rowid 9, embedding_dim 4 but a 3-float blob: in the join, dropped by build_query_batch\nCACHED_LIVE = [(\"v1\", DOMAIN), (\"v2\", DOMAIN), (\"v3\", DOMAIN)]  # expected processed set\nCACHED_UNTOUCHED = [(\"gone1\", DOMAIN), (\"gone2\", DOMAIN), (\"v5\", \"\"), (SHORT, DOMAIN)]  # stale, empty-domain key, skipped\nUNCACHED = [(f\"v{i}\", DOMAIN) for i in range(4, 9)]\nFORBIDDEN = [\"--incremental\", \"--reset\", \"--reset-only\", \"--recreate-out-db\"]\n```\n\n**Source DB (in-process, sqlite3 plus `array(\"f\")`).**\n- Table: `video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT)`.\n- Rows are inserted with explicit rowids 1..9.\n- Vector i is `[cos i, sin i, cos 2i, sin 2i]`, normalised with `math.hypot`, then packed as `array(\"f\", \u2026).tobytes()`.\n- v9 gets `array(\"f\", [1, 0, 0]).tobytes()` with `embedding_dim=4`.\n- Every row has one model/dim pair, so `resolve_embedding_space` passes.\n\n**Index (an `ENGINE_PY` child, `BUILD_INDEX_CHILD`).**\n- It reads the rows whose blob is `DIM*4` bytes and builds `faiss.index_factory(DIM, \"IDMap2,IVF1,Flat\", faiss.METRIC_INNER_PRODUCT)`.\n- It then trains, calls `add_with_ids` with the rowids, and runs `faiss.write_index`.\n- The test writes the sidecar `f\"{index}.json\"` = `{\"model_name\": MODEL, \"embedding_dim\": DIM}`.\n- **Why IVF and not flat.** This is the same inverted-list family as production (`IndexIDMap2(IndexIVFPQ)`), so the job's `IO_FLAG_MMAP | IO_FLAG_READ_ONLY` read and `set_nprobe` are known to work. nprobe 16 over nlist 1 is clamped by faiss. The \"too few training points\" warning is harmless.\n- **Failure mode.** The child's non-zero exit is asserted with its stderr, and `ENGINE_PY.exists()` is asserted with the message \"run `pixi install` in engine/\". A missing faiss fails the test and never skips it.\n- **Sharing.** The source DB and index are built once, as a module fixture via `tmp_path_factory`. The job opens the DB read-only.\n\n**Cache seeding.**\n- Each test creates its cache with the job itself: `--reset-only --out <cache>`. That gives one schema source, the real `ensure_schema`, and the setup's exit code is asserted.\n- It then inserts through sqlite3, for each key in `CACHED_LIVE + CACHED_UNTOUCHED`:\n  - `similarity_sources(key, SENTINEL_COMPUTED_AT)`;\n  - two items, `(\"sentinel-a\", DOMAIN, 0.5, 1)` and `(\"sentinel-b\", DOMAIN, 0.4, 2)`.\n\n**Helpers.**\n\n```python\ndef _run_job(tmp_path: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:\n    return subprocess.run([str(ENGINE_PY), str(PRECOMPUTE_JOB), \"--db\", str(source_db), \"--index\", str(index_path), \"--out\", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, encoding=\"utf-8\", timeout=120)\n```\n\n- `_sources(path)` and `_items(path, key)` read through `file:\u2026?mode=ro` with ORDER BY, returning tuples.\n- `_counts(stderr)` returns `int(re.search(r\"total sources=(\\d+)\", \u2026))` and the `done processed=(\\d+)/(\\d+)` pair.\n\n**Tests.**\n1. **`test_refresh_rewrites_exactly_cached_live_sources`**\n   - Seed, snapshot `_sources` and every untouched key's items, then run `--refresh-existing --cpu --top-k 3`.\n   - Assert `returncode == 0`, `mode=refresh-existing` in stderr, total 4, done `(3, 4)`.\n   - The live keys all have the same `computed_at` T > 1.\n   - Each live key's items have no `sentinel-` target and ranks `1..n` with 1 \u2264 n \u2264 3. Every target is a LIVE key on DOMAIN other than the source itself.\n   - The untouched keys' source rows and items equal the snapshot. For v9, this proves a skipped source is not rewritten.\n   - No `similarity_sources` or `similarity_items` source row exists for any `UNCACHED` key.\n   - `COUNT(*)` of `similarity_sources` is still 7.\n2. **`test_refresh_over_missing_or_empty_cache_is_a_no_op`**, parametrised `[\"missing\", \"empty\"]`\n   - \"empty\" is created by `--reset-only`.\n   - Assert: exit 0, total 0, done `(0, 0)`, both tables in `sqlite_master`, 0 sources.\n3. **`test_refresh_rejects_each_destructive_flag`**, parametrised FORBIDDEN \u00d7 `[\"seeded\", \"absent\"]`\n   - Record `read_bytes()` and `stat().st_mtime_ns`, or absence.\n   - Run `--refresh-existing <flag> --cpu`.\n   - Assert `returncode == 2`, `\"--refresh-existing cannot be combined with\"` and the flag in stderr, and the bytes/mtime unchanged or the file still absent.\n\n### `tests/active/test_updater_precompute_cmd.py`\n\n- The module is loaded with `importlib.util.spec_from_file_location(\"updater_worker_precompute\", JOBS_DIR / \"updater-worker.py\")`, as `test_host_normalisation._load_job` does.\n- `test_updater_builds_refresh_command`, parametrised `use_gpu`:\n  - It asserts the builder's list `==` the old literal with `\"--refresh-existing\"` in place of `\"--recreate-out-db\"`, with the `[\"--gpu\", \"--gpu-device\", \"0\"]` or `[\"--cpu\"]` suffix.\n  - It asserts `\"--recreate-out-db\" not in cmd`.\n  - The inputs are fixed `Path`s under tmp_path and `python_bin=\"python3\"`.\n- `test_cpu_fallback_keeps_refresh`: `module._to_cpu_cmd(gpu_cmd) == cpu_cmd`.\n\n### `.un/skills/devsecops/config.json`\n\n```json\n    \"test_precompute_similar_ann_refresh.py\": [\n      \"engine/server/db/jobs/precompute-similar-ann.py\",\n      \"engine/server/data/embedding_space.py\"\n    ],\n    \"test_updater_precompute_cmd.py\": [\n      \"engine/server/db/jobs/updater-worker.py\"\n    ]\n```\n\n### Docs\n\n**`UPDATER_WORKER.md`, line 53:**\n\n> 10. Refresh the similarity cache's existing entries (`precompute-similar-ann.py --refresh-existing`). Only sources already in `similarity_sources` whose video is still in `video_embeddings` are recomputed and rewritten. Videos added by this run get no entry here; the Engine caches each one the first time it is requested. Cached sources whose video is gone are left in place. A missing or empty cache stays empty after this step, so build the initial cache with `DATA_BUILD.md` \u00a75.\n\n**`DATA_BUILD.md` \u00a75**, inserted after the code block (after line 263):\n\n> Output modes:\n> - no mode flag: compute every row of `video_embeddings`, upserting into the existing cache.\n> - `--reset`: clear both cache tables, then compute every row.\n> - `--recreate-out-db`: delete and recreate the cache file, then compute every row (this is what `scripts/run-dataset-build.sh` runs).\n> - `--reset-only`: recreate the cache file empty and exit; needs neither `--cpu` nor `--gpu`.\n> - `--incremental`: compute only videos not yet in `similarity_sources`.\n> - `--refresh-existing`: recompute only videos already in `similarity_sources` that are still in `video_embeddings`, leaving every other cache row untouched. The updater runs this mode. It cannot be combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` (the job exits 2).\n\n**Issue 24, line 15:** `--incremental` becomes `--refresh-existing`. The issue-25 status/archive move is left to the delivery step.\n\n---\n\n### Check against plan and requirements (step 2)\n\n- **Pass 1: plan versus requirements, one by one.**\n  - Help text, flag and exclusivity are all met, with exit 2 before any file is touched. `--cpu`/`--gpu` are still required.\n  - Selection: INNER JOIN, read-only ATTACH, materialise, DETACH, iterate by rowids; `total_sources` is `len`.\n  - The search/commit/soft-stop code is untouched, and the rewrite goes through `record_similarities`.\n  - There is no other write. Skipped rows are not rewritten.\n  - Missing or empty cache gives exit 0: `ensure_schema` runs before the ATTACH.\n  - Logging reuses `total sources=`, with a `mode=` field.\n  - Updater argv changes only by the flag.\n  - Docs: step 10 and the \u00a75 note. `run-dataset-build.sh` is unchanged.\n  - Tests cover every validation bullet on tmp files only.\n- **Pass 2: where the draft deliberately departs from the plan text, with the impact inventory's reason.**\n  - Tests run under `ENGINE_PY`, not `sys.executable`: the root env has no numpy or faiss.\n  - The builder is named `similarity_precompute_cmd`, to avoid the UnboundLocalError on the `precompute_cmd` local.\n  - The conflict check sits before the cpu/gpu check.\n  - The fixture uses an IVF1 index, so the MMAP read is known to work.\n  - The pass converged: nothing else is left unmet.\n\n### Deliberate simplifications (named)\n\n- **An empty refresh still reads and verifies the index.** It needs non-empty embeddings, a readable index and a valid sidecar. This keeps one code path for all modes. The upgrade path is an early exit after selection.\n- **One schema source in the tests.** Seeding goes through `--reset-only` rather than a copied DDL, so a broken `--reset-only` shows up as a setup failure in this test.\n\n### Notes for the operator (not in the gate)\n\n- **Smoke test coverage drops.** The orchestrator smoke run starts every run with no similarity cache. It now produces a schema-only cache and no longer exercises the precompute's FAISS or write path. Its `similarity_precompute` duration stops being a meaningful baseline.\n- **Stale wording left alone.** `ORCHESTRATOR_SMOKE_TEST.md` line 16 and `DATA_BUILD.md` line 30's path are unchanged, per the settled doc list.\n\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the process boundary of `engine/server/db/jobs/precompute-similar-ann.py`. The job runs as a subprocess, following the harness in `tests/active/test_precompute_random_rowids.py` (`_run_job` with `cwd=tmp_path`, `capture_output`), but under `conftest.ENGINE_PY` because the job imports numpy and faiss. The run is guarded by `assert ENGINE_PY.exists()` with the message \"run `pixi install` in engine/\", as `test_internal_client_reads.py` does. `test_refresh_rejects_each_destructive_flag` is parametrised over the four flags `--incremental`, `--reset`, `--reset-only`, `--recreate-out-db` \u00d7 {seeded cache, absent cache}. The seeded cache is made by the job's own `--reset-only` plus sqlite3 sentinel inserts, all under tmp_path. It records `read_bytes()` and `stat().st_mtime_ns`, or records that the file is absent, then runs `--refresh-existing <flag> --cpu`. It asserts `returncode == 2`, that stderr contains `--refresh-existing cannot be combined with` and the flag, and that bytes and mtime are unchanged or the file is still absent.</checkpoint>\n<name>Refresh guard</name>\n<intent>`precompute-similar-ann.py` accepts `--refresh-existing`, and its post-`parse_args` conflict check rejects it together with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` before the output file is opened, unlinked or created.</intent>\n<clause_1>Combining `--refresh-existing` with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` exits 2, naming the conflicting flag on stderr.</clause_1>\n<clause_2>After a rejected combination the output file keeps its bytes and mtime, or stays absent if it was absent.</clause_2>\n<files>engine/server/db/jobs/precompute-similar-ann.py (EDITED), tests/active/test_precompute_similar_ann_refresh.py (NEW), .un/skills/devsecops/config.json (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the same subprocess boundary and harness as phase 1, in `tests/active/test_precompute_similar_ann_refresh.py`. The module fixture (`tmp_path_factory`) builds a tmp source DB, with `video_embeddings` rowids 1..9 where v9 has a 3-float blob, and an `IDMap2,IVF1,Flat` inner-product index built by an `ENGINE_PY` child, plus its `.json` sidecar. The child's non-zero exit is asserted along with its stderr, so a missing faiss fails the test and does not skip it. Each test creates its cache with `--reset-only` and seeds sentinel rows for `CACHED_LIVE + CACHED_UNTOUCHED`. `test_refresh_rewrites_exactly_cached_live_sources` runs `--refresh-existing --cpu --top-k 3` and asserts: exit 0; `mode=refresh-existing`, `total sources=4` and `done processed=3/4` in stderr; v1\u2013v3 share one `computed_at` > 1 and hold only non-sentinel items ranked 1..n (n \u2264 3), each a LIVE key on DOMAIN other than the source itself; gone1, gone2, (v5, \"\") and v9 have source rows and items equal to the pre-run snapshot; no UNCACHED key has a row; there are still 7 sources. `test_refresh_over_missing_or_empty_cache_is_a_no_op`, parametrised [\"missing\", \"empty\"], asserts exit 0, total 0, done 0/0, both tables present in `sqlite_master`, and 0 sources.</checkpoint>\n<name>Refresh selection</name>\n<intent>Under `--refresh-existing`, the shared incremental/refresh selection branch in `precompute-similar-ann.py` inner-joins `video_embeddings` to the read-only attached `similarity_sources`, so the job rewrites exactly the cached sources still in `video_embeddings` and leaves every other cache row as it was.</intent>\n<clause_1>Each cached source still in `video_embeddings` that `build_query_batch` accepts is rewritten with the run's single new `computed_at` and only fresh ranked items, and nothing is selected when the cache is missing or schema-only.</clause_1>\n<clause_2>Every other cache row, whether a stale source, an empty-domain key or a length-skipped source, is left as it was, and uncached embeddings gain no rows.</clause_2>\n<files>engine/server/db/jobs/precompute-similar-ann.py (EDITED), tests/active/test_precompute_similar_ann_refresh.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the function boundary of `updater-worker.py`. The module is loaded in-process with `importlib.util.spec_from_file_location` from `JOBS_DIR / \"updater-worker.py\"`, following `test_host_normalisation._load_job`. `tests/active/test_updater_precompute_cmd.py::test_updater_builds_refresh_command`, parametrised over `use_gpu` \u2208 {True, False}, asserts that `similarity_precompute_cmd(...)` with fixed tmp_path `Path`s and `python_bin=\"python3\"` equals, as a list, the old literal with `--refresh-existing` in place of `--recreate-out-db` plus the `[\"--gpu\", \"--gpu-device\", \"0\"]` or `[\"--cpu\"]` suffix, and that `--recreate-out-db` is not in it. `test_cpu_fallback_keeps_refresh` asserts `module._to_cpu_cmd(gpu_cmd) == cpu_cmd`.</checkpoint>\n<name>Updater argv</name>\n<intent>The updater's precompute stage builds its command through a module-level `similarity_precompute_cmd` in `updater-worker.py` that runs `--refresh-existing` in place of `--recreate-out-db`, and the CPU retry keeps that flag.</intent>\n<clause_1>For both `use_gpu` values, `similarity_precompute_cmd` returns the previous argv with `--recreate-out-db` replaced by `--refresh-existing`.</clause_1>\n<clause_2>`_to_cpu_cmd` applied to the GPU argv gives the CPU argv, keeping `--refresh-existing`.</clause_2>\n<files>engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_updater_precompute_cmd.py (NEW), .un/skills/devsecops/config.json (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone. Phases 1 and 2 need the Engine pixi environment with numpy and faiss (`pixi install` in engine/). This is a local prerequisite that other tests in tests/active already share, not a credential or a manual step. If it is missing, the test fails and does not skip.\n</needs_coordination>\n\n<rationale>\nThe precompute change has two separately observable halves, so it is two phases.\n\n- **Phase 1** is the argparse guard, which works on its own: the flag exists and the destructive combinations are refused before any file is touched.\n- **Phase 2** is the selection SQL, which decides which rows are rewritten and which are left alone.\n\nPutting the guard first means the first thing that lands with the new flag is its safety property. In the intermediate state, `--refresh-existing` alone runs as a full scan, and nothing calls it yet. The missing and empty cache cases are not a separate phase: they are the boundary case of the selected set being cached \u2229 embeddings, which is empty over an empty cache. They are folded into phase 2's clause_1, so there is no phase with no code in it.\n\n**Phase 3**, the updater builder, is independent of the job's internals. It is proved at the function boundary with the existing importlib harness.\n\nThe four forbidden flags are written as an explicit list in the clauses, not as a universal. They are a fixed set named by the plan, not one derived from production at run time.\n\nKnown limit: nothing asserts that `main()` calls `similarity_precompute_cmd`. The settled plan rejected driving `main()` because it would need lock, systemctl and crawler stubs. The call-site swap is a one-line replacement reviewed in the diff.\n\nDocumentation (UPDATER_WORKER.md step 10, DATA_BUILD.md \u00a75, issue 24 line 15) gets no phase and is updated in Step 9. The `config.json` test_groups entries go in with the phase that creates each test file. The operator approved this breakdown.\n</rationale>",
    "author:tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py": "<assertions>\ntests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:74 \u2014 `--refresh-existing <flag> --cpu` exits with returncode 2, for each of the 4 flags \u00d7 {seeded, absent} cache (8 cases). Today this already passes, because argparse exits 2 on the unknown `--refresh-existing`, so line 76 carries the red \u2014 C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:76 \u2014 stderr holds exactly one line containing `--refresh-existing cannot be combined with`. Fails today (0 == 1) in all 8 cases \u2014 C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:79 \u2014 the whole `--flag` tokens after that phrase on the refusal line, intersected with the four destructive flags, equal exactly {flag}. The check is limited to the refusal line because argparse's usage block on stderr lists all four flags. Matching whole tokens stops `--reset` being found inside `--reset-only`. It also rejects a fixed message that lists every flag instead of the one that conflicted \u2014 C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:81 \u2014 seeded case: `--out` still exists after the refusal. Catches a check placed after `--recreate-out-db`/`--reset-only` unlink the file \u2014 C2\ntests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:82 \u2014 seeded case: `(read_bytes(), st_mtime_ns)` of `--out` equals the pair recorded after the sentinel commit. The cache was laid out by the job's own `--reset-only`, then given one sentinel similarity_sources row and one similarity_items row through sqlite3. A late check after the `--reset` DELETE, or after `--reset-only` recreates the file, drops the sentinels and changes the bytes \u2014 C2\ntests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:84 \u2014 absent case: `--out` does not exist after the refusal; line 69 asserts it was absent before. Catches a check placed after `connect_db`/`ensure_schema`, which the probe showed creates the file \u2014 C2\ntests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:93 \u2014 positive control: `--refresh-existing --cpu` with no destructive flag produces no refusal line, so the conflict check depends on a destructive flag being present \u2014 C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:94 \u2014 positive control: that same run's stderr has no `unrecognized arguments`, so the job accepts `--refresh-existing` (the intent's \"accepts `--refresh-existing`\"). Fails today \u2014 C1\nSetup controls, not clause-bearing: `_seed_cache` asserts that the seeding `--reset-only` run returns 0. `_run_job` asserts `ENGINE_PY.exists()` with the \"run `pixi install` in engine/\" message. Every path is under tmp_path, including `--db`, `--index` (not present) and `--out`, so the repo's whitelist.db and faiss index are never read.\nCurrent red, observed: all 8 parametrised cases get past the seeding and line 74, then fail at line 76. test_refresh_alone_is_not_refused fails at line 94.\n</assertions>\n\n<probes>\nCommand: ValidateTests [\"tests/tmp/test_probe_25_p1.py\", \"-s\"] (probe at tests/tmp/test_probe_25_p1.py). It used ENGINE_PY, a tmp source.db holding an empty video_embeddings table, `--index tmp/missing.faiss` and `--out tmp/similarity-cache.db`. It printed:\n(1) ENGINE_PY is /home/enduser/code/PeerTube-browser/engine/.pixi/envs/default/bin/python and exists=True; importing it from tests/tmp works after adding tests/active to sys.path.\n(2) `--reset-only` with no `--cpu` returned rc 0. stderr was \"INFO reset-only: no existing file at \u2026\" then \"INFO reset-only completed: output cache recreated\". Tables created: similarity_items, similarity_sources, similarity_source_rank_idx plus the two autoindexes. The sentinel INSERTs into both tables succeeded. Afterwards the directory held only similarity-cache.db and source.db, with no journal file left.\n(3) Current code, `--refresh-existing <flag> --cpu`, for each of the 4 flags: rc 2. stderr was the full argparse usage block, which lists [--recreate-out-db] [--reset] [--reset-only] [--incremental], then \"precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing\". The seeded file's (bytes, mtime_ns) were unchanged. So returncode == 2 and \"flag in stderr\" both pass on today's code, which is why the flag check is limited to the refusal line.\n(4) Unknown `--bogus`: the same rc 2 and usage block.\n(5) Plain `--cpu` on an absent `--out`: rc 1, sqlite3.OperationalError \"no such column: model_name\" raised from resolve_embedding_space, and the absent `--out` now existed. So a check placed after connect_db/ensure_schema creates the file, and the absent case catches it.\nCleanup: the probe file tests/tmp/test_probe_25_p1.py is still there. I have no delete tool, so it needs removing by hand.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:74, :76 and :80 \u2014 for each of the four flags \u00d7 {seeded, absent}, `result.returncode == 2`, exactly one `precompute-similar-ann.py: error: ` line in stderr, and the set of whole `--flag` tokens on that line, intersected with the four destructive flags, `== {flag}`. Supported by :79 (`--refresh-existing` is on the line) and :95/:97 (with `--refresh-existing --cpu` alone there is no error line and the job goes on to create `--out`).</assertion>\n<expected>Exit 2, and one line `precompute-similar-ann.py: error: --refresh-existing cannot be combined with <flag>` whose destructive tokens are exactly {flag}. The run confirmed that argparse puts the error on its own `prog: error: message` line after the usage block, and that the usage block lists every flag; this is why only the error line is searched. With the flag alone, the run gets past parsing and creates `--out`. The probe saw this for `--cpu` alone: rc=1 and the absent file exists afterwards.</expected>\n<wrong_implementation>The code as it stands, which does not know the flag: the run showed exit 2 and the line `precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing`, so the intersection is `set()` and :80 goes red on all 8 cases. A check that names all four flags at once, or names the wrong one, gives an intersection other than {flag}. A plain substring check would let `--reset` match inside `--reset-only`; whole tokens prevent that. A guard that refuses `--refresh-existing` on its own prints an error line with no destructive flag, which fails :95.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:82 and :83 \u2014 for a seeded `--out`, the file still exists and `(read_bytes(), st_mtime_ns) == before`. :85 \u2014 for an absent `--out`, `not out_path.exists()`. Both hold after each of the four refused combinations.</expected></assertion>\n<expected>Seeded: the file exists and has the same bytes and mtime. Absent: still absent. Seen in the probe on the argparse-exit path, which is the same exit `parser.error` takes: rc=2, seeded exists=True unchanged=True, absent exists=False.</expected>\n<wrong_implementation>A conflict check placed after the output file is opened (after `connect_db`/`ensure_schema`, the `--reset` DELETE, or the `--reset-only`/`--recreate-out-db` unlink). The probe showed what the destructive paths do to the observable: in every absent case the file is created (exists=True for `--cpu`, `--incremental --cpu` and `--reset --cpu`), so :85 goes red for all four flags. In the seeded `--reset` case the bytes change (unchanged=False), so :83 goes red. `--reset-only` and `--recreate-out-db` unlink the seeded file and recreate it or leave it removed, so :82/:83 go red; this last one comes from reading the source (lines 373-406) and was not probed. Seeded `--incremental` was observed to leave the file unchanged, so that one cell is carried only by its absent twin.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, and rewritten. The old test pinned the refusal on the plan's predicted wording `--refresh-existing cannot be combined with`. C1 only requires that the conflicting flag is named on stderr, and argparse's own mutually-exclusive-group message would have failed a test pinned on that wording. The test now selects the one `precompute-similar-ann.py: error: ` line, a format I observed in the run, and checks the flags named on it. After the rewrite: C1 is covered at :74/:76/:80 over 4 flags \u00d7 2 cache states, and C2 at :82/:83/:85. The alone test checks that the guard does not refuse `--refresh-existing` on its own.\n2. Absence only: yes, and rewritten. `test_refresh_alone_is_not_refused` asserted only absences: no refusal line and no \"unrecognized arguments\". A job that died before parsing would have passed both. I added a positive control at :97, `out_path.exists()`, which shows the job got past its argument checks into `connect_db`. The probe observed this path creating the file for `--cpu` alone. The absent-case `not out_path.exists()` at :85 is armed by the error line at :76/:80, which proves the job ran and reached the guard, and by :97, which proves this harness's `--out` does get created when the job is not refused.\n3. Echoed literal: no. `before` is read from disk before the run and compared with a fresh read after it. The test does no transformation of its own. Deleting the new `parser.error` conflict check (plan lines 414-417) turns :80 red in every case. Moving it below `connect_db` or the unlink/DELETE paths turns :85 red for every flag and :82/:83 red for `--reset`, `--reset-only` and `--recreate-out-db`.\n4. One value: no. The named-flag observable is read over four different flags, each expected to give a different set. C2 is read over two cache states. The exit code 2 is already true today, because argparse also exits 2 on an unknown flag; the run showed :74 passing. So :74 is not the discriminator on its own; :80 is.\n5. The double: no. There are no doubles. The real job runs as a child under `ENGINE_PY` on tmp sqlite files, and the seed schema comes from the job's own `--reset-only`.\n6. It collects: yes. `conftest.ENGINE_PY` resolves, and the run collected 9 items, which matches 4\u00d72 parametrised cases plus 1. The `--collect-only` \"no tests\" line is the runner's summary for a collect-only pass. The INSERT column counts (3 and 6) match the job's schema, since the seeded cases got past `_seed_cache` in the run.\n7. Observed, not predicted: fixed with a probe (`tests/tmp/probe_refresh_guard.py`). It showed the argparse error line format; that a rejected run leaves a seeded file unchanged and an absent one absent; that `--cpu` alone creates an absent `--out` (rc=1, OperationalError `no such column: model_name`, and no `prog: error:` line in the traceback); that seeded `--reset --cpu` changes the bytes; and that seeded `--incremental --cpu` does not. One premise is still a prediction that could not be observed before the phase exists: that `--refresh-existing --cpu` takes the same post-parse path as `--cpu`. The plan's phase 1 adds only the flag and the pre-cpu-check guard. The phase-1 implementation run will confirm it, since :97 must pass. I emptied the probe's contents but could not delete the file with my tools. `tests/tmp/probe_refresh_guard.py` is left as an empty file and should be removed.\n8. Red, not green: yes. `ValidateTests` exited 1 with \"9 failed\".\n9. Red for the right reason: yes. All 8 parametrised cases fail at :80, `assert named & set(DESTRUCTIVE_FLAGS) == {flag}`, with \"AssertionError: precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing / assert set() == {'--incremental'}\" (and the same for `--reset`, `--reset-only`, `--recreate-out-db`). `test_refresh_alone_is_not_refused` fails at :95, `assert _error_lines(result.stderr) == []`, because the list holds 'precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing'. Every control before these passed: the `ENGINE_PY` existence check, the `--reset-only` seed at :47, the absent check at :70, exit 2 at :74, one error line at :76, and `--refresh-existing` named at :79. So the job ran, and the red is the missing flag and guard, not the harness.\n10. Observed expected output: the C1 `expected` matches the run's error-line format and exit status. Only the message text after `error: ` is the phase's own output, so it is necessarily a prediction; the assertions check only which flags it names. In the C2 row, the unchanged and absent cases and the wrong-implementation readings for absent files and for seeded `--reset`/`--incremental` come from the probe run. The seeded `--reset-only`/`--recreate-out-db` readings come from the source and are marked as unprobed. C2 is not reached in the checkpoint run because :80 fails first, and it would hold under the current code, since argparse exits before touching the file. The red rests on C1.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/server/db/jobs/precompute-similar-ann.py`\n- **New flag.** `--refresh-existing` (store_true) goes right after `--incremental`, in the same multi-line `add_argument` style. Its help text is the plan's: \"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\"\n- **Conflict check.** A new check sits right after `parse_args()` and before the existing `--cpu`/`--gpu` check. When `--refresh-existing` is set, it collects whichever of `--incremental`, `--reset`, `--reset-only` and `--recreate-out-db` are also set. If there are any, it calls `parser.error(\"--refresh-existing cannot be combined with <those flags, comma-joined>\")`, which exits 2 on one `precompute-similar-ann.py: error:` line.\n- **Why the output file is safe.** The check runs before logging setup, the signal handlers, the source connection, the `--recreate-out-db`/`--reset-only` unlinks and `connect_db`/`ensure_schema`. So a refused combination leaves `--out` exactly as it was, or still absent.\n- **Why it comes before the `--cpu`/`--gpu` check.** `--refresh-existing --reset-only` given without an accelerator flag gets the conflict message, not the cpu/gpu one.\n- **What is unchanged.** Combinations among the other four flags are still allowed.\n- **Behaviour in between phases.** Until phase 2, `--refresh-existing` on its own is accepted and runs the existing full-scan path. The selection SQL and the `mode=` log field belong to phase 2.\n\n### `.un/skills/devsecops/config.json`\n- **New `test_groups` entry.** `\"test_precompute_similar_ann_refresh.py\"` maps to `engine/server/db/jobs/precompute-similar-ann.py` and `engine/server/data/embedding_space.py`, as the plan says.\n\n### `tests/active/test_precompute_similar_ann_refresh.py`\n- **Not written this turn.** This phase's gate is the audited checkpoint in `tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py`, and I was asked for production code only. I did not copy it into `tests/active`. I expect the workflow's promotion step to create the durable file from that checkpoint, and the new `config.json` entry above is already keyed to that name.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py": "<assertions>\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:131 - `--refresh-existing --cpu --top-k 3` over the seeded cache exits 0 - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:132 - stderr contains `mode=refresh-existing` - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:134 - logged `total sources` is exactly 4 (v1, v2, v3, v9: the cached keys still in video_embeddings); a full scan logs 9 - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:135 - logged `done processed` is exactly 3/4 (v9 dropped by build_query_batch); a full scan logs 8/9 - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:138 - v1, v2 and v3 have source rows sharing a single computed_at - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:140 - that computed_at is not None, is greater than the sentinel 1, and falls between wall-clock ms taken just before and just after the run - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:142 - each of v1, v2 and v3 has items ranked exactly [1, 2, 3], so a rewrite that leaves no items fails (stricter than the agreed n <= 3 because the 8 unit vectors make exactly 3 non-self neighbours certain, as the probe showed) - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:144 - no item of v1, v2 or v3 still points at the sentinel target - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:145 - every item target of v1, v2 and v3 is a LIVE key on DOMAIN other than the source itself - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:146 - gone1, gone2, (v5, \"\") and v9 each keep a computed_at and items equal to the pre-run snapshot - C2\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:147 - control, not a clause: that snapshot holds the sentinel computed_at, so line 146 is not comparing empty against empty - (control)\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:148 - the UNCACHED keys v4, (v5, DOMAIN), v6, v7 and v8 have no source row and no items - C2\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:149 - similarity_sources still holds exactly 7 rows; a full scan leaves 12 - C2\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:163 - [missing|empty] `--refresh-existing --cpu --top-k 3` exits 0 - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:165 - [missing|empty] logged `total sources` is exactly 0; a full scan logs 9 - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:166 - [missing|empty] logged `done processed` is exactly 0/0 - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:170 - [missing|empty] similarity_sources and similarity_items are both present in sqlite_master - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:171 - [missing|empty] similarity_sources has 0 rows - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:172 - [missing|empty] similarity_items has 0 rows - C1\n</assertions>\n\n<probes>\nRan ValidateTests [\"tests/tmp/test_probe_25_p2.py\", \"-s\"] and read the printed values from tests/last_test_output.txt. The probe built the checkpoint's fixture: a source DB with rowids 1..8 holding 4-float unit vectors, v9 declaring dim 4 but storing 3 floats, an `IDMap2,IVF1,Flat` METRIC_INNER_PRODUCT index built by an ENGINE_PY child, and a `.json` sidecar. It seeded sentinels, then ran the CURRENT code with `--refresh-existing --cpu --top-k 3`, both over the seeded cache and over a missing one.\nBUILD: rc 0, stdout 'ntotal 8', stderr only 'WARNING clustering 8 points to 1 centroids: please provide at least 39 training points', a harmless warning.\nSEED: `--reset-only` rc 0.\nRUN on the current code: rc 0; stderr: 'INFO embedding space model=probe-model dim=4 / INFO index verified ... / INFO faiss acceleration=cpu / INFO total sources=9 / INFO done processed=8/9 elapsed=0s'. So the current code, treating --refresh-existing as a full scan, logs 9 and 8/9, and there is no mode line yet.\nSOURCES on the current code: 12 rows. v1-v8 on live.example are stamped 1790808320827 (epoch ms), and gone1, gone2, (v5, '') and v9 stay at 1. So the uncached v4-v8 gain rows under the wrong behaviour, and v9 is length-skipped.\nITEMS on the current code: every processed source has exactly 3 items ranked 1..3, all on live.example and never the source itself (e.g. v1 -> v2 0.8, v8 0.6, v4 0.0). The untouched keys keep their sentinel item.\nMISSING cache on the current code: rc 0, total sources=9, processed 8/9, file created.\nThen ran ValidateTests [\"tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py\"] against the unchanged code: 3 failed, all after setup succeeded. test_refresh_rewrites_exactly_cached_live_sources fails at line 132 (no `mode=refresh-existing`; stderr shows total sources=9 and 8/9). Both parametrised no-op cases fail at line 165 with ('9',) != ('0',).\nThe probe file tests/tmp/test_probe_25_p2.py should be deleted, but I have no delete tool, so it is still on disk. Please remove it.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:131, :132, :134, :135 \u2014 over the seeded cache, `--refresh-existing --cpu --top-k 3` exits 0, stderr contains `mode=refresh-existing`, the logged `total sources=` is exactly (\"4\",), and `done processed=` is exactly (\"3\", \"4\")</assertion>\n<expected>rc 0, then `INFO total sources=4 mode=refresh-existing` and `INFO done processed=3/4`. Four are selected (v1, v2, v3 and v9, the cached keys still in video_embeddings) and three processed, because build_query_batch drops v9's 3-float blob. The run showed that this drop really happens on this fixture: today's full scan logs `total sources=9` and `done processed=8/9`.</expected>\n<wrong_implementation>The code as it stands, a full scan with no `mode=` field. The run showed rc 0, no `mode=` in stderr, `total sources=9` and `done processed=8/9`, so :132 goes red. The incremental LEFT JOIN / IS NULL reused for refresh selects the 5 uncached keys and logs 5 and 5/5. A join on video_id alone also picks up (v5, live.example) and logs 5 and 4/5.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:138, :140, :142, :144, :145 \u2014 v1, v2 and v3 share exactly one `computed_at`, which lies between the wall-clock ms taken before and after the run and above the sentinel 1. Each has items ranked exactly [1, 2, 3], none points at the sentinel target, and every target is a LIVE key other than the source itself.</assertion>\n<expected>The probe ran the same seeded cache through the job's rewrite path (today's full scan writes v1-v3 through the same record_similarities). One stamp, 1790808419854, fell inside the window [1790808419716, 1790808419887]. v1 got [(v2,1),(v8,2),(v4,3)], v2 got [(v1,1),(v3,2),(v8,3)] and v3 got [(v4,1),(v2,2),(v1,3)], all on live.example, with no sentinel item left.</expected>\n<wrong_implementation>A refresh that selects the right keys but never rewrites them, for example one that only updates `computed_at` or skips record_similarities. v1-v3 then keep computed_at 1 and the single sentinel item: :140 and :142/:144 go red. A per-row stamp would give more than one stamp and fail :138. Dropping the self-exclusion would put the source among its own targets and fail :145.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:163, :165, :166, :170, :171, :172 \u2014 for a missing cache and for a schema-only cache: rc 0, `total sources=` (\"0\",), `done processed=` (\"0\", \"0\"), both cache tables in sqlite_master, and 0 rows in each</assertion>\n<expected>rc 0, `total sources=0 mode=refresh-existing`, `done processed=0/0`, and a file holding both empty tables. The job's own connect_db + ensure_schema creates the tables before selection runs. The probe saw the missing-cache run exit 0 and leave the file in place. The table-list and 0-row assertions have not been observed passing, because the run stops at :165. They rest on ensure_schema running before selection, which the phase does not change.</expected>\n<wrong_implementation>The code as it stands. The run showed rc 0 and `total sources=9` in both the missing and the empty case, so :165 fails with ('9',) == ('0',). If the run reached :171, 8 source rows would be written. A refresh that treats an empty cache as \"refresh everything\" gives the same result.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:146 \u2014 gone1, gone2, (v5, \"\") and v9 each have a `computed_at` and items equal to the pre-run snapshot (control :147: that snapshot holds the sentinel stamp)</assertion>\n<expected>Each of the four keeps (1, [('sentinel-target', 'sentinel.example', 0.5, 1)]). The probe showed exactly this before and after the run.</expected>\n<wrong_implementation>A refresh that prunes cached sources that are gone from video_embeddings: gone1/gone2 read (None, []). A refresh that clears items for every selected key before search, including ones build_query_batch then drops: v9 reads (1, []). A key match that ignores the empty domain and rewrites (v5, \"\"): (v5, \"\") gets a new stamp and new items.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:148, :149 \u2014 v4 to v8 on live.example have no source row and no items, and similarity_sources still holds exactly 7 rows</assertion>\n<expected>{key: (None, []) for each of v4..v8}, and COUNT = 7.</expected>\n<wrong_implementation>The code as it stands (full scan). The probe showed v4-v8 each gaining a source row with stamp 1790808419854 and 3 items, and COUNT 12. A join on video_id alone writes (v5, live.example). The incremental outer join writes all five.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. C1's selection is covered by the counts at :134/:135. The rewrite is covered by the stamp at :138/:140 and the fresh ranked items at :142/:144/:145. \"Nothing selected when missing or schema-only\" is covered by :165/:166/:171/:172. C2 is covered by the unchanged snapshot of gone1/gone2/(v5,\"\")/v9 at :146 and by the uncached keys and the count at :148/:149. The docstring's `mode=refresh-existing` is the plan's logging requirement (plan line 76: the `total sources` line gains `mode=`), asserted at :132.\n2. Absence only: no. :144 (no sentinel item) is armed by :142 (exactly three ranked items). :146 (unchanged) is armed by :147 (the snapshot really holds the sentinel) and by the positive rewrite of v1-v3 in the same run. :148 (no rows for v4-v8) is armed by :135 (3 processed) and :138/:140 (a real write happened). The no-op test's zero counts are armed by :170 (the tables exist) and by rc 0 plus the logged 0/0.\n3. Echoed literal: no. The test does not compute a neighbour or a stamp itself. Deleting the INNER JOIN selection turns :134 red. Deleting the `mode=` field in the log call turns :132 red. Deleting record_similarities' DELETE/INSERT turns :142/:144 red.\n4. One value: no. The counts are pinned against a fixture with 9 embeddings, 7 cached keys and 5 uncached keys, where the wrong selections give 9, 5 and 5 rather than 4. The stamp is pinned against an external wall-clock window, not against a sibling from the job.\n5. The double: none. The job runs as a real child under ENGINE_PY on a real sqlite source and a real FAISS index built by that interpreter.\n6. It collects: yes. The injected `--collect-only` summary printed \"no tests\" but exited 0. The ValidateTests run printed \"collected 3 items\" and ran all three (1 test + 2 parametrised). ENGINE_PY resolves from tests/active/conftest, and every helper argument exists.\n7. Observed, not predicted: yes. I wrote tests/tmp/probe_phase2_state.py, which imports this module's fixture and helpers and runs `--refresh-existing --cpu --top-k 3` over the seeded cache. It showed RC 0, `total sources=9` / `done processed=8/9`, one stamp 1790808419854 inside the window [1790808419716, 1790808419887], v1-v3 items ranked [1,2,3] on live keys other than self with no sentinel, the four untouched keys unchanged at (1, sentinel item), v4-v8 each gaining a row (COUNT 12), and a missing-cache run with rc 0 that creates the file. Not observed: the sqlite_master table list after a refresh run, because :165 stops the run first. It rests on connect_db + ensure_schema running before selection. I have emptied the probe file, but no tool here can delete it, so tests/tmp/probe_phase2_state.py remains as an empty file to remove.\nNo rewrite was needed.\n8. Red, not green: yes. ValidateTests printed \"3 failed\", \"[exit status 1]\".\n9. Red for the right reason: yes. The failing assertions are judging assertions, not controls, and all fire after rc 0. test_refresh_rewrites_exactly_cached_live_sources fails at line 132, `assert \"mode=refresh-existing\" in result.stderr`, on stderr \"INFO total sources=9\\nINFO done processed=8/9\". Both parametrised no-op cases fail at line 165 with \"AssertionError: assert ('9',) == ('0',)\". The fixture's index build, the `--reset-only` seed and the job's rc 0 all passed, and the stderr shows the full-scan path running: the phase is not implemented.\n10. Observed expected output: every row's `expected` matches the run or the probe. The pre-phase values (9, 8/9, rc 0, 12 sources, v4-v8 rows) are quoted from the runs. The post-phase log lines follow the plan's format and are not yet observed, since they are the phase's own output. The one premise I did not observe (tables present after a no-op) is stated as such in its row.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### engine/server/db/jobs/precompute-similar-ann.py\n- The job now picks a selection mode (`refresh-existing`, `incremental` or `full`) and logs it as `selection mode=%s` just before the `total sources=` line. The checkpoint looks for `mode=refresh-existing` in the output.\n- The existing incremental branch now also runs under `--refresh-existing`. Both modes attach the output cache read-only as `out_cache` and collect a list of rowids before any writes, as incremental already did. Only the SELECT differs:\n  - **`--refresh-existing`:** `video_embeddings` is inner-joined to `out_cache.similarity_sources` on both `video_id` and `instance_domain`.\n  - **`--incremental`:** keeps its `LEFT JOIN ... WHERE s.video_id IS NULL`.\n- Effect on the cache:\n  - Only cached sources that are still in `video_embeddings` are selected and rewritten, all with the run's single `computed_at`.\n  - Stale cache rows are never selected, so they are left as they were. So is a key that only matches on `video_id`, like `(\"v5\", \"\")`.\n  - A cached source with the wrong embedding length is counted in `total sources` but dropped by `build_query_batch`, so its row is also left alone.\n  - Embeddings that aren't cached are not selected, so they gain no rows.\n- A missing or schema-only cache selects nothing, so the run logs 0 total and 0/0 processed. The existing `connect_db` + `ensure_schema` step creates and commits both tables before the attach, so the tables are there afterwards.\n- Nothing else in the job changed: the search, the recording, the full-scan path and incremental's results are all as before.\n\n### tests/active/test_precompute_similar_ann_refresh.py\nNot touched. The phase's files list names it, but the gating checkpoint lives at `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py`, and this step's job is only the production code.\n\nI did not run the checkpoint; the workflow's run is the one that counts.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py": "<assertions>\ntests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:44 - for each `use_gpu` in {True, False}, `similarity_precompute_cmd(python_bin=\"python3\", ...)` given four distinct tmp_path Paths equals, token for token, a hand-written list: `python3, <script>, --db <prod.db>, --index <ann.faiss>, --out <similarity-cache.db>, --top-k 1000, --nprobe 16, --search-batch-size 1024, --refresh-existing`, then `--gpu --gpu-device 0` or `--cpu`. It is red today, because the probe saw no builder in the module, so the call raises AttributeError. A builder that keeps `--recreate-out-db`, swaps two paths, changes a tuning value, puts the flag somewhere else or gets the suffix wrong also fails the exact comparison - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:45 - `--recreate-out-db` is not in the builder's argv, for both `use_gpu` values. This is the negative half: it catches a builder that appends `--refresh-existing` but leaves the old flag in - C1\ntests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:52 - a precondition, not a clause: the GPU argv ends in `--gpu --gpu-device 0`. `run_with_cpu_fallback` only retries a command that carries `--gpu`, so without this line C2 would pass even if the builder ignored `use_gpu` and `_to_cpu_cmd` just returned its input - C2 (precondition)\ntests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:54 - `_to_cpu_cmd(gpu_cmd)` equals the hand-written CPU list: the same prefix with `--refresh-existing` in the same place, then a single trailing `--cpu`. It fails if the retry drops `--refresh-existing`, leaves the device value `0` behind, keeps `--gpu`, or adds `--cpu` twice - C2\ntests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:64 - the operator approved this extra guard for the Intent's call site. `main` in updater-worker.py, parsed with `ast`, calls `similarity_precompute_cmd`. It is red today: the probe listed `main`'s calls and the builder is not among them. It catches a builder that is added while `main` keeps its inline literal - Intent (call site)\ntests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:65 - also operator-approved: the module has no `\"--recreate-out-db\"` string constant anywhere. It is red today, because the probe found exactly one, at line 1129, which is `main`'s precompute literal - Intent (call site)\n</assertions>\n\n<probes>\nCommand: ValidateTests [\"tests/tmp/test_probe_25_p3.py\", \"-s\"]. The probe loaded engine/server/db/jobs/updater-worker.py in-process with spec_from_file_location, with nothing else on sys.path; the module adds its own server dir. It printed:\n- `has builder: False`. `similarity_precompute_cmd` does not exist yet, so C1 and C2 are red today with AttributeError.\n- `tmp_path str==posix: True /tmp/pytest-of-enduser/pytest-6643/test_probe0`. So `f\"{tmp_path}/...\"` in the expected lists matches the `.as_posix()` strings the plan's builder produces.\n- `to_cpu: ['python3', 's.py', '--db', 'd', '--index', 'i', '--out', 'o', '--top-k', '1000', '--nprobe', '16', '--search-batch-size', '1024', '--refresh-existing', '--cpu']`. The current `_to_cpu_cmd` keeps `--refresh-existing` in place and puts a single `--cpu` at the end. So the C2 expectation is the right target, and C2 is red today only because the builder is missing.\n- `flag consts: [(1129, '--recreate-out-db')]`. That is the only `--recreate-out-db` string constant in the module: main's inline precompute literal.\n- `main calls: [... 'run_with_cpu_fallback', 'systemctl_cmd', ...]`. There is no `similarity_precompute_cmd` in the list, so the call-site guard is red today.\nLeftover: the probe file tests/tmp/test_probe_25_p3.py is still on disk because I have no delete tool. It should be removed; the checkpoint now covers everything it was used to check.\nI did not run the checkpoint file itself. Its red state (AttributeError in the two builder tests, and line 64 failing) is taken from the probe output above.\n</probes>\n\n<unassertable>\nnone. The one requirement the agreed function-boundary checkpoint could not reach was the Intent's claim that the precompute stage builds its command through the builder, i.e. that `main` uses it. I asked with AskUser and the operator chose \"Add a source-scan guard\", so it is covered by the AST assertions at :64-65. That guard is structural: it proves the call is made and the old literal is gone, not what argv `main` passes at run time. It carries a `rat-tail:` comment naming its limit and how to replace it (a pipeline harness with the stage commands shimmed).\n</unassertable>",
    "self_check:tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:44 \u2014 for each `use_gpu` in {True, False} (parametrised ids `gpu`, `cpu`), `similarity_precompute_cmd(python_bin=\"python3\", use_gpu=..., script_path, db_path, index_path, out_path)` with four distinct tmp_path Paths equals, as a list: `python3, <tmp>/jobs/precompute-similar-ann.py, --db, <tmp>/prod.db, --index, <tmp>/ann.faiss, --out, <tmp>/similarity-cache.db, --top-k, 1000, --nprobe, 16, --search-batch-size, 1024, --refresh-existing`, then `--gpu, --gpu-device, 0` or `--cpu`.</assertion>\n<expected>Under the right implementation, each case returns exactly that list. The probe read the old literal out of `main` at updater-worker.py:1114-1130 with ast: `args.python_bin, (script_dir / 'precompute-similar-ann.py').as_posix(), '--db', prod_db.as_posix(), '--index', index_path.as_posix(), '--out', similarity_db.as_posix(), '--top-k', '1000', '--nprobe', '16', '--search-batch-size', '1024', '--recreate-out-db'`. The expected list is that literal with its last token swapped. The probe also saw `f\"{tmp_path}/prod.db\" == (tmp_path / \"prod.db\").as_posix()` \u2192 True. Today both cases are red with `AttributeError: module 'updater_worker_precompute' has no attribute 'similarity_precompute_cmd'` at line 42.</expected>\n<wrong_implementation>Four builders fail this comparison. (a) One that keeps `--recreate-out-db` and appends `--refresh-existing` reads `[..., '1024', '--recreate-out-db', '--refresh-existing', ...]`. (b) One that swaps db/out, or index/out, puts the wrong path in a slot, and the four paths are distinct so the lists differ. (c) One that drops or changes a tuning value, or puts `--refresh-existing` after the accelerator suffix, gives a different order. (d) One that ignores `use_gpu` returns the GPU suffix in the `cpu` case, or the reverse.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:45 \u2014 `\"--recreate-out-db\" not in cmd`, for both `use_gpu` values.</assertion>\n<expected>True in both cases under the right implementation. Its positive control is line 44 on the same `cmd`, which shows that the builder ran and returned the full argv. Today it is not reached, because line 42 raises AttributeError.</expected>\n<wrong_implementation>A builder that adds `--refresh-existing` but leaves the old destructive flag in the argv would contain `'--recreate-out-db'`, and this line would fail. It is the negative half of \"replaced by\", stated on its own so the failure message names the destructive flag.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:54 \u2014 `_to_cpu_cmd(gpu_cmd)`, where `gpu_cmd` is the builder's `use_gpu=True` argv, equals `[python3, <script>, --db, <prod.db>, --index, <ann.faiss>, --out, <similarity-cache.db>, --top-k, 1000, --nprobe, 16, --search-batch-size, 1024, --refresh-existing, --cpu]`. It is armed by the control at line 52, which checks that `gpu_cmd[-3:] == ['--gpu', '--gpu-device', '0']`, because `run_with_cpu_fallback` retries only a command carrying `--gpu`.</assertion>\n<expected>Exactly the CPU list. This was observed: the probe ran the real `_to_cpu_cmd` over the hand-built GPU list and it printed `['python3', '/tmp/pytest-of-enduser/pytest-6645/test_probe0/jobs/precompute-similar-ann.py', '--db', '.../prod.db', '--index', '.../ann.faiss', '--out', '.../similarity-cache.db', '--top-k', '1000', '--nprobe', '16', '--search-batch-size', '1024', '--refresh-existing', '--cpu']`. Today the test is red at line 50 with AttributeError, because the builder is missing.</expected>\n<wrong_implementation>Three cases fail here. (a) A change to `_to_cpu_cmd` that strips the non-GPU flags, or rebuilds the argv from a fixed template, drops `--refresh-existing`. (b) One that skips only `--gpu-device` and not its value leaves a stray `'0'`. (c) One that appends `--cpu` without the membership check, or keeps `--gpu`, produces a different list. Separately, a builder that ignored `use_gpu=True` and emitted `--cpu` would be caught by the line 52 control, not passed vacuously.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\nThe test is red for the right reason on all four tests. I changed one thing: I added a positive control to the source-scan test (question 2). I also wrote a throwaway probe to confirm the expected argvs from a real run.\n\n1. Whole claim \u2014 no gap. The docstring makes three claims: the builder's exact argv (lines 44-45, both `use_gpu` values), the CPU retry (line 54, armed by line 52), and the call site plus no leftover literal (lines 64-67). C1 and C2 are both carried.\n\n2. Absence only \u2014 yes, and I rewrote it. Line 45 (`--recreate-out-db` not in cmd) is armed by line 44 on the same `cmd`. But the old last line of `test_updater_main_uses_builder` (`\"--recreate-out-db\" not in` the module's constants) had no control showing the scan sees string constants at all. The rewrite computes `constants` once, then line 66 asserts `\"--gpu-device\" in constants` before line 67 asserts `\"--recreate-out-db\" not in constants`. The probe saw `--gpu-device` in the module's constants \u2192 True today, and it stays after the phase (it is a literal in `_to_cpu_cmd` and the builder). With that change, no absence assertion is left unarmed.\n\n3. Echoed literal \u2014 no. The expected lists are hand-written and the test never builds an argv itself. Deleting the `\"--refresh-existing\",` token from the builder's list, or keeping `\"--recreate-out-db\",` there (plan lines 493-509), turns line 44 red.\n\n4. One value \u2014 no. C1 runs at both `use_gpu` inputs. The four paths are distinct, so a swap shows up. `python_bin` is `\"python3\"`, which differs from the argparse default `sys.executable` (updater-worker.py:177), so a builder hard-coding the default fails. C2 compares against a hand-written list, not against a second builder call.\n\n5. The double \u2014 no. There are no doubles. The real `updater-worker.py` is loaded with `spec_from_file_location`, and the real `_to_cpu_cmd` is called.\n\n6. It collects \u2014 yes, it collects. The `--collect-only -q` wrapper prints \"no tests\", but the full run's `tests/last_test_output.txt` shows `collected 4 items` (gpu, cpu, cpu-fallback, main-uses-builder), matching what I wrote. The imports resolve (ast, importlib.util, pathlib, pytest). The keyword names match the plan's signature (python_bin, script_path, db_path, index_path, out_path, use_gpu; plan lines 483-491).\n\n7. Observed, not predicted \u2014 yes, all observed. `tests/tmp/probe_phase3_argv.py` printed three things. OLD LITERAL came from ast on `main`: `[..., \"'--search-batch-size'\", \"'1024'\", \"'--recreate-out-db'\"]`, the source of the C1 list. TO_CPU was the real `_to_cpu_cmd` over the GPU list: `[..., '1024', '--refresh-existing', '--cpu']`, the C2 expectation. FSTR==POSIX: True, which backs the f-string paths. The builder's own output cannot be observed until it exists; its expectation is the observed old literal with one token swapped, as the clause states. I cannot delete files, so the probe file is now empty: it holds nothing and collects nothing.\n\n8. Red, not green \u2014 yes, red. `ValidateTests` on the checkpoint gave `4 failed`, `recorded: tests/last_test_validation.json (exit 1)`, `[exit status 1]`.\n\n9. Red for the right reason \u2014 yes. Test by test:\n- `test_updater_builds_refresh_command[gpu]` and `[cpu]`: `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:42: AttributeError`, \"module 'updater_worker_precompute' has no attribute 'similarity_precompute_cmd'\". The module loaded (the fixture repr shows `.../engine/server/db/jobs/updater-worker.py`), so the path and harness are fine. The missing attribute is exactly what this phase adds.\n- `test_cpu_fallback_keeps_refresh`: the same AttributeError at line 50. The line 52 control is not reached, so it did not fail.\n- `test_updater_main_uses_builder`: fails at line 64, `assert 'similarity_precompute_cmd' in {'FileNotFoundError', 'Path', 'RuntimeError', 'bool', 'count_staging_deltas', 'fetch_join_hosts', ...}`. The ast walk over `main` worked and found real calls; `main` just does not call the builder yet.\n\nNo control assertion failed.\n\n10. Observed expected output \u2014 yes. Each row's `expected` states what the run showed. Today that is the AttributeError at line 42 (C1) and line 50 (C2). The expected lists after implementation are the probe-observed old literal with the flag swapped, and the probe-observed `_to_cpu_cmd` output. The run contradicted nothing.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `engine/server/db/jobs/updater-worker.py`\n- New module-level `similarity_precompute_cmd(*, python_bin, script_path, db_path, index_path, out_path, use_gpu) -> list[str]`. It sits after `systemctl_cmd` and uses the same keyword-only style. It returns the precompute argv the updater used to build inline, token for token. The one change is that `--refresh-existing` now takes the slot `--recreate-out-db` held. The argv ends in `--gpu --gpu-device 0` when `use_gpu` is true and `--cpu` otherwise (C1). Paths are passed through `.as_posix()`, as they were before.\n- `main`'s precompute stage now gets `precompute_cmd` from `similarity_precompute_cmd(...)` and no longer builds the list and appends the accelerator flags itself. `run_with_cpu_fallback` still runs it. `_to_cpu_cmd` is unchanged: it drops only `--gpu` and `--gpu-device <n>`, so a CPU retry keeps `--refresh-existing` in place (C2). The module now contains no `--recreate-out-db` literal.\n\n### `.un/skills/devsecops/config.json`\n- Registered the test group `\"test_updater_precompute_cmd.py\": [\"engine/server/db/jobs/updater-worker.py\"]`. Phases 1\u20132 did the same for `test_precompute_similar_ann_refresh.py`: the group is registered now and the test file itself lands in `tests/active/` when the checkpoint is promoted.\n\n### `tests/active/test_updater_precompute_cmd.py`\n- Not created in this step. The step asked for production code only, and the checkpoint in `tests/tmp/` carries this phase. Following the phase 1\u20132 pattern, promoting it into `tests/active/` under this name is left to the promotion step. The checkpoint file was not touched.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nengine/server/db/jobs/precompute-similar-ann.py: the selection branch now checks the already-computed `mode` (`mode != \"full\"`, then `mode == \"refresh-existing\"`) and no longer re-tests `args.incremental or args.refresh_existing` and `args.refresh_existing`, so the logged mode and the SQL that runs come from the same value.\nengine/server/db/jobs/precompute-similar-ann.py: rewrote the attach-block comment, which still said \"Incremental mode\" although the block now serves both incremental and refresh-existing. It is now one line covering both modes, where it used to be wrapped over three.\n</refactors>\n\n<left_out>\nengine/server/db/jobs/updater-worker.py: nothing to refactor. `similarity_precompute_cmd` already matches the keyword-only style of `systemctl_cmd`, and `main` just calls it.\nengine/server/db/jobs/precompute-similar-ann.py: left the `--recreate-out-db` and `--reset-only` unlink blocks alone. They are near-duplicates, but they were there before this build and merging them is outside this build's scope.\nengine/server/db/jobs/precompute-similar-ann.py: left the one-line conflict-check comprehension as it is. It follows the no-softwrap rule and is checked before any output-file side effect; moving it into a helper would add indirection for a single caller.\nNot run: I did not run the checkpoints myself (the workflow's run is the one that counts). The edit only swaps equivalent conditions, because `mode` is derived from exactly `args.refresh_existing` / `args.incremental` a few lines above.\nProcess gap, not a refactor: `tests/active/test_precompute_similar_ann_refresh.py` and `tests/active/test_updater_precompute_cmd.py` do not exist, although `config.json` already has test groups for both. The gating tests are still only in `tests/tmp/test_25_similarity_precompute_existing_sources_phase{1,2,3}.py`, so the promotion step still has to create them. The step's \"{rat_tail_rules}\" placeholder was also never filled in, so I measured the pass against the role's rules; no simplification in this build needed a `rat-tail:` comment.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nThe three phases fit together without duplicated logic; the only cleanup was making the selection branch use the logged `mode` and fixing a comment that dated from before refresh-existing, and nothing needed new behaviour.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\" update=\"yes\">\nExecution Order step 10 (line 53) says `Update similarity cache incrementally (precompute-similar-ann.py --incremental)`. That is false: the updater now runs `precompute-similar-ann.py --refresh-existing` (built by `similarity_precompute_cmd`, which keeps the flag on the GPU\u2192CPU retry). Rewrite step 10 to say that it refreshes the similarity cache in place with `--refresh-existing`. It rewrites only sources already in `similarity_sources` that are still in `video_embeddings`. Videos new from the merge are cached lazily by the Engine the first time they are requested. Cached sources no longer in embeddings are left in place, and only the stale-host purge removes rows. Add one sentence saying that a missing or empty cache stays empty (schema only, 0 sources, the stage still succeeds), and point to `DATA_BUILD.md` \u00a75 / `scripts/run-dataset-build.sh` for the initial full build. The goals line \"refresh popularity/similarity data\" (line 14) and Outputs \"Updated similarity cache\" (line 28) stay true.\n</doc>\n<doc path=\"DATA_BUILD.md\" update=\"yes\">\n\u00a75 \"Precompute similarity cache\" documents only the full-build example and `--top-k`, and nothing about `--refresh-existing`, which the updater now depends on. After the example, add a short flag note. `--recreate-out-db`: delete and recreate the output file (the full build, as used by the example and `run-dataset-build.sh`). `--reset`: clear the cache tables before computing. `--reset-only`: clear them and exit. `--incremental`: compute only embeddings not yet in `similarity_sources`. `--refresh-existing`: recompute only sources already in `similarity_sources` that are still in `video_embeddings`, leave all other cache rows untouched, and select nothing on a missing or empty cache. It cannot be combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`; argparse rejects that combination with exit 2 before the output file is touched. Leave the example block and the `--top-k` paragraph as they are. Line 30 also points at `engine/server/db/jobs/UPDATER_WORKER.md`. That path is wrong: the file is `engine/server/db/jobs/docs/UPDATER_WORKER.md`. Fix it in the same edit, since readers follow that link to find the updater's precompute mode. Line 24's stage list is still accurate.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md\" update=\"yes\">\nThe Purpose list (line 16) claims the smoke test validates an \"incremental similarity precompute\". After this build, each smoke run starts with no `similarity-cache.db`, and the updater's `--refresh-existing` stage only creates the schema and processes 0 sources. So the smoke test no longer exercises the precompute's FAISS search or write path, and its `similarity_precompute` stage duration is not a precompute timing. The plan left this line alone because it was already inaccurate, but the sentence is now materially false about what the test covers. Reword it to say that the similarity precompute stage runs in `--refresh-existing` mode against the run's fresh, empty cache: it checks that the stage runs and produces a schema-only cache, not that similarities are computed. This is a single-line change; the operator may decline it.\n</doc>\n<doc path=\"docs/project/issues/24-similarity-cache-shadow-swap.md\" update=\"yes\">\nTwo statements are now false after issue 25. Proposed solution line 15 says the shadow build runs `precompute-similar-ann.py --incremental`. The updater's mode is now `--refresh-existing`, so change that line. The Agent Brief's Current behavior (line 60) says the precompute runs into the active cache \"(recreating it)\". It now refreshes the cached sources in place without recreating the file, so change that too. The triage bullet at line 45 (\"runs with `--recreate-out-db`\") is a dated triage observation. Leave it, and add a short comment under `## Comments` saying 25 is delivered, the updater's precompute stage runs `--refresh-existing` through `similarity_precompute_cmd` in `updater-worker.py`, and so the shadow build wires that mode. The comment should also note that refresh never deletes sources, so the gate's \"no fewer `similarity_sources` rows\" check still holds.\n</doc>\n<doc path=\"docs/project/issues/25-similarity-precompute-existing-sources.md\" update=\"yes\">\nDelivered. Set `Status:` to `complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md` / `issue-tracker.md`. Add a comment covering four points. `--refresh-existing` landed with its conflict check. The updater uses it. New videos are cached lazily at serve time and stale sources are left in place. The validation item \"Updater stage time drops against the full-rebuild baseline\" is an operator measurement on main after the merge (the smoke test's `similarity_precompute` duration no longer measures precompute work, because the smoke cache is empty), not an automated gate.\n</doc>\n<doc path=\"DEPLOYMENT.md\" update=\"no\">\nThe updater-timer paragraph (lines 130-134) says only that the updater \"precomputes similarity\" and stops/starts the Engine around the write-critical stages. Both are still true, because the stop/start sequence is unchanged. The line 263 note about `--top-k 20` describes the dataset build and was already inconsistent with the updater's `--top-k 1000`. This build did not change that inconsistency, and it is out of scope.\n</doc>\n<doc path=\"docs/project/adr/0008-similarity-cache-handoff-through-files.md\" update=\"no\">\nThis ADR decides how a shadow-built cache is handed to running Engines (the build marker, reopen by inode, the pre-swap gate). None of that is built yet, and nothing in it names a precompute mode. Refresh never deletes sources, so the \"no fewer sources than the active file\" gate stays consistent.\n</doc>\n<doc path=\"docs/project/adr/0006-derived-ann-ids.md\" update=\"no\">\nIts only claim here is that the similarity cache is keyed by `(video_id, instance_domain)`. That is still true, and the refresh join uses exactly that key.\n</doc>\n<doc path=\"CONTEXT.md\" update=\"no\">\nThe glossary entries `Shadow build` and `Build marker` describe issue 24's design. They do not name a precompute mode, and this build does not affect them.\n</doc>\n<doc path=\"docs/project/issues/08-stable-ann-ids.md\" update=\"no\">\nLine 19 says precompute moves to `ann_id` and \"incremental selection stays logical-key based\". The new refresh selection is also keyed on the logical `(video_id, instance_domain)`, so the statement holds. The extra rowid join site is recorded in the plan and inventory for issue 08's implementer; it is not a false claim in the issue.\n</doc>\n<doc path=\"docs/project/issues/plan.md\" update=\"no\">\nRow 82 lists the two code files this build touched, and line 125 already orders 25 before 24. Nothing in it describes the precompute mode.\n</doc>\n\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:engine/server/db/jobs/docs/UPDATER_WORKER.md": "<changes>\nRewrote Execution Order step 10 to describe the in-place `--refresh-existing` precompute and replace the incorrect `--incremental` claim.\n\n- Step 10 now reads \"Refresh the similarity cache in place (`precompute-similar-ann.py --refresh-existing`)\". It has four sub-bullets:\n  - Only sources already in `similarity_sources` that are still in `video_embeddings` are recomputed and rewritten.\n  - Videos new from the merge get no entry in this stage. The Engine caches each one the first time it is requested.\n  - Cached sources that are no longer in `video_embeddings` stay in the cache. Only the stale-host purge removes cache rows.\n  - A missing or empty cache stays empty (schema only, 0 sources), and the stage still succeeds. The initial full build is `scripts/run-dataset-build.sh`, and the bullet points to `DATA_BUILD.md` \u00a75 for it.\n- I checked these claims against the code:\n  - `similarity_precompute_cmd` in `updater-worker.py` puts `--refresh-existing` in the argv, and `_to_cpu_cmd` keeps it.\n  - The inner-join selection is at `precompute-similar-ann.py` lines 454\u2013462.\n  - `ensure_schema` uses `executescript` and runs before the read-only ATTACH.\n  - `purge_hosts` deletes from `similarity_db`.\n- Everything outside step 10 is unchanged. Line 14 (\"refresh popularity/similarity data\") and the Outputs line \"Updated similarity cache\" are still accurate.\n- I found an existing inaccuracy outside this build's scope and left it as it is. The \"GPU/CPU Mode\" section says `--gpu` has \"no CPU fallback\", but `run_with_cpu_fallback` retries the ANN build and the precompute on CPU.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:DATA_BUILD.md": "<changes>\nDATA_BUILD.md \u00a75 now lists the precompute cache-mode flags, including `--refresh-existing` and the flags it can't be combined with. The broken link to UPDATER_WORKER.md is fixed.\n\n- **\u00a75 \"Precompute similarity cache\":** added a \"Cache modes\" list after the output-size line.\n  - `--recreate-out-db`: the full build, which `scripts/run-dataset-build.sh` uses.\n  - `--reset` and `--reset-only`: clear the cache tables; `--reset-only` then exits without computing.\n  - `--incremental`: computes only embeddings not yet in `similarity_sources`.\n  - `--refresh-existing`: recomputes only cached sources that are still in `video_embeddings` and leaves every other row alone. On a missing or empty cache it creates the schema and processes 0 sources. Combining it with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` is rejected by argparse with exit code 2 before the output file is touched.\n  - The entry says the updater uses this mode and points to UPDATER_WORKER.md for how the updater runs it, rather than repeating it here.\n- **Link fix:** the \"Automatic background updater\" section pointed at `engine/server/db/jobs/UPDATER_WORKER.md`, which doesn't exist. It now points at `engine/server/db/jobs/docs/UPDATER_WORKER.md`.\n- **Left as they were:** the example command block, the `--top-k` paragraph and the updater stage list.\n- **Checked against the code:** the flag help texts and conflict check in `precompute-similar-ann.py` (lines 323\u2013346), the join and read-only attach (lines 443\u2013476), and `--recreate-out-db` in `run-dataset-build.sh` (line 257).\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md": "<changes>\nReworded the Purpose bullet on similarity precompute so it matches what the smoke test covers: the `--refresh-existing` stage runs against an empty cache and leaves only the schema.\n\n- Line 16 said the test validates an \"incremental similarity precompute\". It now says the smoke test runs the similarity precompute stage in `--refresh-existing` mode against the run's fresh, empty similarity cache. It checks that the stage runs and leaves a schema-only cache, not that similarities are computed.\n- I checked this against `test-orchestrator-smoke.py`. `paths[\"similarity_db\"]` is a path inside the per-run (or per-scenario) directory, and nothing copies a cache into it; only the prod DB is copied. The only check on it is `validate_outputs`, which confirms the file exists. So a smoke run starts with no cache, and the updater's `--refresh-existing` stage selects 0 sources.\n- Nothing else in the file changed. The rest of the Purpose list, the failure scenarios (including `after_merge_before_similarity`) and the Artifacts section (\"ANN/similarity outputs\") are still accurate.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/24-similarity-cache-shadow-swap.md": "<changes>\nIssue 24 now names `--refresh-existing` as the updater's precompute mode, and I added a comment recording that issue 25 is delivered.\n\n- **Proposed solution, Shadow build (line 15):** the shadow build now runs `precompute-similar-ann.py --refresh-existing` against the copy, not `--incremental`. The reason in brackets for copying the active cache now reads \"keeps the cached sources to refresh\" instead of \"keeps the incremental baseline\".\n- **Agent Brief, Current behavior (line 60):** the precompute now \"runs with `--refresh-existing` against the active `similarity-cache.db` (rewriting its cached sources in place)\", replacing \"(recreating it)\".\n- **New comment, `### Issue 25 delivered`, after the Triage block under `## Comments`:** the updater's precompute stage runs `--refresh-existing`, built by `similarity_precompute_cmd` in `engine/server/db/jobs/updater-worker.py`, so the shadow build uses that mode. Refresh never deletes a source, so the gate's \"no fewer `similarity_sources` rows\" check still holds.\n- **Left as they were:** the triage bullet at line 45 (\"runs with `--recreate-out-db`\"), the `--incremental` remark at line 46 and the \"Settle at triage\" line in Related. All three are dated triage notes.\n- **Checked against the code:** `similarity_precompute_cmd` in `updater-worker.py` puts `--refresh-existing` in the argv, and `main` calls it for the precompute stage.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/25-similarity-precompute-existing-sources.md": "<changes>\nClosed issue 25 as delivered. The archive copy has `Status: enhancement, complete` and a `### Delivered` comment, but I couldn't remove the original file.\n\n- **New file:** `docs/project/issues/archive/25-similarity-precompute-existing-sources.md`. Its body is the original's word for word, except for the `Status:` line and the new comment. This follows the archived issue 23.\n- **Original not removed:** I have no tool that deletes files, so `docs/project/issues/25-similarity-precompute-existing-sources.md` is still there with its old contents. Until someone runs `git rm` on it, the issue exists in two places.\n- **The comment** links the plan `docs/project/plans/19-25-similarity-precompute-existing-sources.md`. The commit is written as `<pending>`, as in issue 23. It covers the four points the checklist asked for:\n  - **What landed:** the `--refresh-existing` mode (an inner join on `(video_id, instance_domain)`, with one `computed_at` for the whole run), and the conflict check. The check rejects `--incremental`, `--reset`, `--reset-only` and `--recreate-out-db` with exit 2 before the output file is touched.\n  - **Updater:** it uses the mode through `similarity_precompute_cmd`, and the GPU\u2192CPU retry keeps the flag.\n  - **Scope:** new videos are cached the first time they are requested, and stale sources stay in the cache rather than being removed.\n  - **Stage time:** the speed-up is measured by the operator on main after the merge; no automated test checks it. The smoke test's `similarity_precompute` duration can't stand in for that figure, because the smoke run's cache is empty.\n- **Not restated:** for flag details and the updater stage, the comment points to `DATA_BUILD.md` \u00a75 and `engine/server/db/jobs/docs/UPDATER_WORKER.md`.\n- **Checked against the code:** the flag and its conflict message in `precompute-similar-ann.py` at lines 335\u2013344, the inner-join selection at lines 443\u2013471, and `similarity_precompute_cmd` passing `--refresh-existing` in `updater-worker.py` at lines 415\u2013440.\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/archive/25-similarity-precompute-existing-sources.md \u2014 new file. The delivered issue has to move into archive/ (issue-tracker.md: \"move the file to docs/project/issues/archive/\"). This is the updated document at its new path.\ndocs/project/issues/25-similarity-precompute-existing-sources.md \u2014 STILL NEEDS REMOVING (`git rm`), which finishes the move. I have no tool that deletes files, so it is unchanged and repeats the archived copy.\n</not_on_checklist>",
    "step_10_plan": "<harvest_file>\ndocs/project/plans/harvest-25-similarity-precompute-existing-sources-plan.md\n</harvest_file>\n\n<plan>\n**Harvest plan: build 25 (similarity precompute existing sources)**\n\nScope is the three checkpoint files in `tests/tmp`, with 7 test functions between them. The build's other probe files stay where they are. The config check found no defaulted keys and no conflicts. The record is saved as `tests/last_test_validation.json.preharvest`. All three files collected and passed during the build, so none needed a collection check.\n\n**Count per verdict**\n- `DURABLE`: 6\n- `REDUNDANT`: 1\n- `REPLACES`: 0\n- `COMBINE`: 0\n- `SPENT`: 0\n\n**Tests to move (`DURABLE`)**\n\n| Test | From | Destination |\n|---|---|---|\n| `test_refresh_rejects_each_destructive_flag` (4 flags \u00d7 seeded/absent) | phase1 | `tests/active/test_precompute_similar_ann.py` |\n| `test_refresh_rewrites_exactly_cached_live_sources` | phase2 | `tests/active/test_precompute_similar_ann.py` |\n| `test_refresh_over_missing_or_empty_cache_is_a_no_op` (missing/empty) | phase2 | `tests/active/test_precompute_similar_ann.py` |\n| `test_updater_builds_refresh_command` (gpu/cpu) | phase3 | `tests/active/test_updater_worker.py` |\n| `test_cpu_fallback_keeps_refresh` | phase3 | `tests/active/test_updater_worker.py` |\n| `test_updater_main_uses_builder` | phase3 | `tests/active/test_updater_worker.py` |\n\nNothing in `tests/active` tests `precompute-similar-ann.py`. The only active test that loads `updater-worker.py` is `test_host_normalisation.py`, and it checks nothing but host normalisation. So none of these six is already covered.\n\n**Please decide on `test_updater_main_uses_builder`.** It reads the source code of `updater-worker.py` rather than running it, and its author marked it as a stopgap. Without it, though, nothing in the durable suite would notice if `main` went back to building the command itself with `--recreate-out-db`, which is the regression this build exists to prevent. I classed it `DURABLE`. The alternative is `SPENT`, which accepts that gap until a test that drives the whole pipeline exists.\n\n**Not moved**\n- `test_refresh_alone_is_not_refused` (phase1) is `REDUNDANT`. The phase2 test `test_refresh_over_missing_or_empty_cache_is_a_no_op[missing]` runs the same `--refresh-existing --cpu` command and checks more (exit 0 and both tables present). This test only guarded an in-between state that phase 2 replaced.\n\n**Active tests retired:** none. No `REPLACES` or `COMBINE`, so nothing goes to `tests/archive`.\n\n**New subject files Step 5 would create** (each is a new test group and needs a new map entry)\n- `tests/active/test_precompute_similar_ann.py` for `precompute-similar-ann.py`. It gets phase2's module fixture (source DB, FAISS index, sidecar), its constants and helpers, plus phase1's `DESTRUCTIVE_FLAGS`, `ERROR_PREFIX`, `_source_db` and `_error_lines`. The two `_run_job` helpers become one that takes the source directory, and the two equivalent `_seed_cache` copies become one.\n- `tests/active/test_updater_worker.py` for `updater-worker.py`. It gets `_load_job`, the `updater` fixture and `_paths`.\n\n**The file names differ from what the build registered.** The build added `test_groups` entries for `test_precompute_similar_ann_refresh.py` and `test_updater_precompute_cmd.py`, but neither file exists. The harvest workflow says a subject file is named after its production script and nothing else, as `test_precompute_random_rowids.py` is. So this plan uses `test_precompute_similar_ann.py` and `test_updater_worker.py` and replaces those two entries. If you'd rather keep the build's names, say so.\n\n**`test_groups` changes** (in `.un/skills/devsecops/config.json`)\n- Remove `test_precompute_similar_ann_refresh.py`.\n- Add `test_precompute_similar_ann.py` \u2192 `engine/server/db/jobs/precompute-similar-ann.py`, `engine/server/data/embedding_space.py`\n- Remove `test_updater_precompute_cmd.py`.\n- Add `test_updater_worker.py` \u2192 `engine/server/db/jobs/updater-worker.py`\n\nAfter Steps 5 to 8, all three checkpoint files move to `delete_me/`. Each moved test will be checked by breaking the production code once and confirming it fails.\n</plan>",
    "step_10": "<moved>\nI moved six test functions (15 test cases) into two new subject files, each its own new group, and updated the harvest record.\n- `tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py::test_refresh_rejects_each_destructive_flag` (8 cases) \u2192 `tests/active/test_precompute_similar_ann.py`, group `test_precompute_similar_ann.py`\n- `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py::test_refresh_rewrites_exactly_cached_live_sources` \u2192 `tests/active/test_precompute_similar_ann.py`, group `test_precompute_similar_ann.py`\n- `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py::test_refresh_over_missing_or_empty_cache_is_a_no_op` (missing/empty) \u2192 `tests/active/test_precompute_similar_ann.py`, group `test_precompute_similar_ann.py`\n- `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py::test_updater_builds_refresh_command` (gpu/cpu) \u2192 `tests/active/test_updater_worker.py`, group `test_updater_worker.py`\n- `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py::test_cpu_fallback_keeps_refresh` \u2192 `tests/active/test_updater_worker.py`, group `test_updater_worker.py`\n- `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py::test_updater_main_uses_builder` \u2192 `tests/active/test_updater_worker.py`, group `test_updater_worker.py`\n- Not moved: `test_refresh_alone_is_not_refused` (phase1), `REDUNDANT` as the approved plan says.\n- **Setup code carried over:** in `test_precompute_similar_ann.py`, one `_run_job(source, out_path, *args)` and one `_seed_cache` now serve all three tests, replacing the two copies of each. Phase2's `source` fixture, constants and helpers came over, plus phase1's `DESTRUCTIVE_FLAGS`, `ERROR_PREFIX`, `_source_db` and `_error_lines`. In `test_updater_worker.py`, `_load_job`, the `updater` fixture and `_paths` came over. `ENGINE_PY` and `ROOT` are imported from `conftest`. Nothing is shared between the two groups.\n- **Docstrings:** they now state the rules the tests gate, and the phase and `C1`/`C2` tags are gone.\n- **Harvest record:** `docs/project/plans/harvest-25-similarity-precompute-existing-sources-plan.md` now has sections for the approval and Steps 5\u20138.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\nTwo entries changed in `test_groups` in `.un/skills/devsecops/config.json`. Neither old entry had a file behind it.\n- `test_precompute_similar_ann_refresh.py` removed; `test_precompute_similar_ann.py` added \u2192 `engine/server/db/jobs/precompute-similar-ann.py`, `engine/server/data/embedding_space.py`\n- `test_updater_precompute_cmd.py` removed; `test_updater_worker.py` added \u2192 `engine/server/db/jobs/updater-worker.py`\n- `--audit-map` exits 0, both right after the edit and again after Step 8.\n- For the new files it lists three advisory MISSING items, which I did not add to the map. `engine/server/data/time.py` is imported but not tested. `engine/server/db/similarity-cache.db` appears only as a path string. The updater test names `precompute-similar-ann.py` only in a path string.\n</group_map>\n\n<mutations>\nEach of the six mutations made its test fail on the assertion it was moved for, and the test passed again after the restore. Backups went to `delete_me/<script>.bak-h25-mN`, outside the production tree. After each restore `diff` against the backup was empty. At the end `cmp` matched every backup against the live file, and no `.bak` file is left under `engine/`.\n- m1 `precompute-similar-ann.py`, conflict guard disabled (`if conflicts:` \u2192 `if False and conflicts:`) \u2192 `test_refresh_rejects_each_destructive_flag`: all 8 cases failed at `assert result.returncode == 2` (the job exited 1) \u2192 after restore, 8 passed.\n- m2 `precompute-similar-ann.py`, refresh join matched on `video_id` only (dropped `AND s.instance_domain = e.instance_domain`) \u2192 `test_refresh_rewrites_exactly_cached_live_sources`: failed at the `total sources` check, `('5',) == ('4',)` \u2192 after restore, passed.\n- m3 `precompute-similar-ann.py`, refresh falls through to the full scan (`if mode != \"full\":` \u2192 `if mode == \"incremental\":`) \u2192 `test_refresh_over_missing_or_empty_cache_is_a_no_op`: both cases failed at the `total sources` check, `('9',) == ('0',)` \u2192 after restore, 2 passed.\n- m4 `updater-worker.py`, `similarity_precompute_cmd` emits `--recreate-out-db` instead of `--refresh-existing` \u2192 `test_updater_builds_refresh_command`: both cases failed at the exact argv comparison, index 14 `'--recreate-out-db' != '--refresh-existing'` \u2192 after restore, 2 passed.\n- m5 `updater-worker.py`, `_to_cpu_cmd` also strips `--refresh-existing` \u2192 `test_cpu_fallback_keeps_refresh`: failed at the `_to_cpu_cmd(gpu_cmd) == [...]` comparison, index 14 `'--cpu' != '--refresh-existing'` \u2192 after restore, passed.\n- m6 `updater-worker.py`, `main` builds the precompute argv itself with `--recreate-out-db` instead of calling the builder \u2192 `test_updater_main_uses_builder`: failed at `assert \"similarity_precompute_cmd\" in called` \u2192 after restore, passed.\n</mutations>\n\n<cleared>\nNothing was deleted; the files below are in `delete_me/` for you to review and remove.\n- **This harvest added nine files to `delete_me/`:**\n  - The three checkpoint files: `test_25_similarity_precompute_existing_sources_phase1.py`, `test_25_similarity_precompute_existing_sources_phase2.py` and `test_25_similarity_precompute_existing_sources_phase3.py`. None of their names clashed with a file already there.\n  - The six mutation backups: `precompute-similar-ann.py.bak-h25-m1` to `-m3`, and `updater-worker.py.bak-h25-m4` to `-m6`.\n  - `delete_me/` went from 175 to 184 entries.\n- **`tests/tmp`:** none of the three checkpoint files remain. The build's out-of-scope probe files are still there, as the plan says.\n- **Final counts:**\n  - Verdicts: 6 `DURABLE` moved (15 cases), 1 `REDUNDANT` left out, 0 retired.\n  - Closing run: I moved `tests/last_test_validation.json.preharvest` back over the record, then ran `--compare`. It selected 3 of 35 groups: the two new groups, plus `test_search_fusion.py` (10 passed), which runs because it already had no map entry before this build. The other 32 groups were unchanged and not re-run. All 25 tests that ran passed.\n  - Against the pre-harvest record: 15 appeared (11 in `test_precompute_similar_ann.py`, 4 in `test_updater_worker.py`), 0 departed, 0 new failures, 0 failures that now pass.\n</cleared>"
  },
  "requirements": "### Purpose\n\nThe updater's similarity precompute stage currently recreates `similarity-cache.db` and recomputes similarity for every row in `video_embeddings` (`updater-worker.py` passes `--recreate-out-db` to `engine/server/db/jobs/precompute-similar-ann.py`). This build adds a mode that refreshes only the sources already cached and still present in embeddings, rewriting only those entries. The updater switches to that mode. Issue 24 (similarity cache shadow build and swap) is settled to land after this one and will run whichever mode the updater uses, so the updater's precompute stage is rewritten once here.\n\n### Operator decision (approved)\n\nThe mode refreshes exactly cached \u2229 embeddings, as the issue states. Videos added by a merge get no precomputed entry from the updater. The Engine caches them lazily the first time they are requested (the serve-time write path `write_cache` in `engine/server/data/similarity_cache_manager.py` / `_write_cache` in `engine/server/data/similarity_candidates.py`, which is unchanged). Cached sources whose video is no longer in `video_embeddings` are left in the cache untouched, not pruned. The operator accepts that the stage-time gain depends on how many sources are cached: the live cache was built full, so early runs will process nearly all of prod, saving only the new videos and the file recreation.\n\n### Precompute CLI mode\n\n- Add a new flag `--refresh-existing` (store_true) to `precompute-similar-ann.py`, with a help text in the style of the existing flags, e.g. \"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\"\n- Source set: the rows of the source DB's `video_embeddings` whose `(video_id, instance_domain)` matches a row in the output cache's `similarity_sources`, i.e. an INNER JOIN in place of the `LEFT JOIN ... WHERE s.video_id IS NULL` used by `--incremental`. It is read the same way `--incremental` reads today: ATTACH the output cache read-only (`file:...?mode=ro`) to the source connection as `out_cache`, materialise the matching rowids into a list, DETACH, then iterate with `iter_embedding_rows_by_rowids`. `total_sources` is the length of that list.\n- Only that set is processed. The FAISS search, top-k selection, self-exclusion, `fetch_similarity_targets_chunked`, batching, the commit every 500, progress logging and soft-stop handling all stay as they are.\n- Per processed source, keep the current rewrite semantics through the existing `record_similarities`: upsert `similarity_sources.computed_at` (one `computed_at` for the run, as today), delete that source's old `similarity_items`, insert the fresh ranked top-k.\n- No other row is written or deleted. There is no global DELETE and no file recreation. Cached sources absent from `video_embeddings` keep their `similarity_sources` and `similarity_items` rows unchanged, and embeddings absent from the cache are not added.\n- A source that is skipped by `build_query_batch` (embedding_dim or embedding length mismatch) is not rewritten, the same behaviour as the other modes.\n- `--refresh-existing` combined with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` is a usage error reported through argparse (`parser.error` or a mutually exclusive group), exiting non-zero before any file is touched. `--cpu`/`--gpu` stay required as today.\n- If the output cache file does not exist or has no `similarity_sources` rows, the run creates the schema (via the existing `connect_db` + `ensure_schema`), processes 0 sources and exits 0. `ensure_schema` must run on the output DB before the read-only ATTACH, as the current code order already does.\n- Logging reuses the existing lines: `total sources=%d` reports the size of the refresh set, and `done processed=%d/%d` reports the result. A mode indicator may be added to an existing log line if it fits the file's style. No new log format is required.\n\n### Updater precompute stage\n\n- In `engine/server/db/jobs/updater-worker.py`, the `precompute_cmd` passes `--refresh-existing` in place of `--recreate-out-db`. Nothing else in the command changes: `--db`, `--index`, `--out`, `--top-k 1000`, `--nprobe 16`, `--search-batch-size 1024`, `--gpu --gpu-device 0` / `--cpu`, `run_with_cpu_fallback` with `stage=\"precompute-similar-ann\"`.\n- The service stop/start sequence, the failure-injection flags and the other stages are unchanged. Moving the service start before the precompute is issue 24's scope.\n\n### Documentation\n\n- `engine/server/db/jobs/docs/UPDATER_WORKER.md` step 10 currently says `precompute-similar-ann.py --incremental`, which does not match the code (`--recreate-out-db`). Correct it to describe `--refresh-existing`: only already-cached sources still in embeddings are rewritten, new videos are cached at serve time, and stale cached sources are left in place.\n- Document `--refresh-existing` in the precompute section of `DATA_BUILD.md` alongside the existing flags, including its exclusivity with `--incremental`/`--reset`/`--reset-only`/`--recreate-out-db`.\n- The initial dataset build (`scripts/run-dataset-build.sh`, and DATA_BUILD.md's full-build example) keeps its full `--recreate-out-db` / `--reset` rebuild, unchanged.\n\n### Tests and validation\n\n- Tests write only temporary copies of the source DB, FAISS index and similarity cache, never the shared `whitelist.db` or `similarity-cache.db` (these are symlinked across worktrees per `docs/project/issues/plan.md`).\n- Processed set: with a cache holding some sources that are in embeddings, some that are not (stale), and embeddings that are not cached, a `--refresh-existing` run processes exactly cached \u2229 embeddings (verified by row state and by the `total sources=` / `done processed=` counts).\n- Rewrite: every processed source has the new run's `computed_at` and a freshly inserted item set (its prior sentinel items are gone).\n- Untouched: stale cached sources keep byte-identical `similarity_sources` and `similarity_items` rows, and uncached embeddings gain no rows.\n- Empty or missing cache: exits 0 with the schema present and 0 sources.\n- Flag conflicts: each forbidden combination exits non-zero with the output file unchanged.\n- Updater: the precompute command the updater builds contains `--refresh-existing` and not `--recreate-out-db`.\n- \"Updater stage time drops against the full-rebuild baseline\" is an operator measurement on main after the merge (the orchestrator smoke test's `similarity_precompute` stage duration can serve as the figure). It is not an automated gate in this build.\n\n### Baseline suite state\n\nThe pre-build suite exited 0 (baseline variant: false). Resolved paths: active tests `tests/active`, working `tests/tmp`, plans `docs/project/plans`, delete_me `delete_me`, archive `tests/archive`, project dir `/home/enduser/code/PeerTube-browser`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.\n\n### Out of scope\n\n- Shadow build, build marker, gate, swap and Engine reopen (issue 24).\n- Pruning stale cached sources, and precomputing new sources in the updater.\n- Changes to the Engine's serve-time cache read/write path.\n- Running the new mode against the shared `similarity-cache.db` (that happens on main after the merge).",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe change touches three places: the precompute CLI, one line of the updater, and two docs. The tests are two new files under `tests/active`.\n\n**Precompute CLI (`engine/server/db/jobs/precompute-similar-ann.py`).** Add `--refresh-existing` as a store_true flag next to `--incremental`, with a help text in the same one-sentence style (\"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\"). Right after `parse_args()`, and before the existing `--cpu`/`--gpu` check, add one `parser.error` check: if `--refresh-existing` is set together with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`, argparse prints a message naming the conflicting flags and exits with code 2. Nothing has been opened at that point: no source connection, no unlink, no `connect_db`. So the output file is guaranteed to be unchanged. Putting the check before the cpu/gpu check means `--refresh-existing --reset-only` (which does not need `--cpu`) gets the specific conflict message and not the cpu/gpu one.\n\nThe source selection extends the existing `--incremental` branch rather than adding a second copy of it. The branch condition becomes \"incremental or refresh-existing\". The ATTACH of the output cache read-only (`file:...?mode=ro`) as `out_cache`, the rowid materialisation, the DETACH, `iter_embedding_rows_by_rowids` and `total_sources = len(...)` stay shared. Only the SELECT differs: an INNER JOIN of `video_embeddings` to `out_cache.similarity_sources` on `(video_id, instance_domain)` for refresh, and the current LEFT JOIN / IS NULL for incremental. A short comment in the style of the one already there says what refresh selects. Everything after selection is untouched: FAISS search, top-k, self-exclusion, `fetch_similarity_targets_chunked`, `record_similarities`, the commit every 500, progress and soft-stop.\n\nHow each CLI requirement is met:\n- **Processed set = cached \u2229 embeddings.** The INNER JOIN produces exactly this set. Stale cached sources are not in `video_embeddings`, so they never enter it. Uncached embeddings have no matching `similarity_sources` row, so they are excluded too.\n- **Rewrite semantics.** Unchanged: the existing `record_similarities` upserts `computed_at` (one value per run, set once as today), deletes that source's old items and inserts the new ranked top-k.\n- **No other writes.** Refresh does not take the `--reset` DELETE path or the `--recreate-out-db` unlink path; the parser check blocks both combinations. The only write in the loop is `record_similarities` for a selected source.\n- **Skipped rows.** `build_query_batch` still drops dim/length mismatches before `record_similarities`, so those sources keep their old rows, as in the other modes.\n- **Empty or missing cache.** The current order already runs `connect_db` + `ensure_schema` on the output before the read-only ATTACH. `ensure_schema` uses `executescript` with DDL only, so the tables are on disk when the attach reads them. The join returns no rows, `total sources=0` and `done processed=0/0` are logged, and the exit code is 0.\n- **Logging.** The existing `total sources=%d` line gets a `mode=` field (full / incremental / refresh-existing), in the file's key=value style next to lines like `faiss acceleration=cpu`. There is no new log line. `done processed=%d/%d` is unchanged.\n\n**Updater (`engine/server/db/jobs/updater-worker.py`).** In `precompute_cmd`, `--recreate-out-db` is replaced by `--refresh-existing`, so the argv is otherwise identical. To test the command without running the pipeline, the list construction moves into a small module-level builder next to `systemctl_cmd`, which is the existing precedent for a command builder in this file. It takes python_bin, script path, prod db, index, similarity db and use_gpu, and returns the same list; `main` calls it in place of the inline literal. The GPU/CPU suffix and `run_with_cpu_fallback(stage=\"precompute-similar-ann\")` behave as before. `_to_cpu_cmd` removes only `--gpu`/`--gpu-device`, so the new flag passes through the CPU retry.\n\n**Docs.**\n- `UPDATER_WORKER.md` step 10 is rewritten: it runs `precompute-similar-ann.py --refresh-existing`, which rewrites only sources already in the cache that are still in `video_embeddings`. New videos are cached by the Engine the first time they are requested, and stale cached sources are left in place.\n- `DATA_BUILD.md` \u00a75 gets a short flag note after the example. It lists `--incremental`, `--recreate-out-db`, `--reset`/`--reset-only` and the new `--refresh-existing`, and says the new flag cannot be combined with the other four. The \u00a75 full-build example and `scripts/run-dataset-build.sh` are not changed.\n\n**Tests (new, under `tests/active`).**\n- `test_precompute_similar_ann_refresh.py` builds everything in `tmp_path`:\n  - a tiny source DB whose `video_embeddings` hold one model_name/dim, a few rowids and normalised float32 vectors;\n  - a flat IP FAISS index with rowid ids, plus the `.json` sidecar that `assert_index_matches_embeddings` requires;\n  - a cache seeded with sentinel rows: a few cached sources that are in embeddings, a few stale ones that are not, and some embeddings left uncached.\n- The job runs as a subprocess with `--cpu`, the same way `test_precompute_random_rowids.py` runs its job. The test asserts:\n  - the processed set, from row state and from the `total sources=` and `done processed=` counts in stderr;\n  - that every processed source has one shared new `computed_at` greater than the sentinel, and that none of its sentinel items remain;\n  - that stale sources' `similarity_sources` and `similarity_items` rows are identical before and after, and that uncached embeddings have no rows;\n  - that a missing cache file and a schema-only empty cache both exit 0, have the schema, and hold 0 sources;\n  - that each of the four forbidden combinations exits non-zero and leaves the output file byte-identical and at the same mtime, or absent if it was absent.\n- A second small test loads `updater-worker.py` through importlib, the way `test_host_normalisation.py` does. It asserts that the builder's output contains `--refresh-existing` and not `--recreate-out-db`, for both use_gpu values.\n- No test touches the shared `whitelist.db` or `similarity-cache.db`.\n\n### Alternatives considered\n\n- **Argparse mutually exclusive group instead of `parser.error`.** Rejected. One group of all five flags would also reject combinations that work today among the other four, for example `--reset` with `--incremental` or `--recreate-out-db` with `--incremental`. That is a behaviour change nobody asked for. argparse cannot nest groups to say \"exclusive with each of these, but not the others among themselves\". A single explicit check is clearer and changes nothing else.\n- **A separate `elif args.refresh_existing` branch copying the ATTACH/materialise/DETACH code.** Rejected in favour of sharing the incremental branch and changing only the SQL. The two modes differ in one join, and duplicating the ATTACH handling would let them drift apart.\n- **Testing the updater's command by reading the source text or AST of `updater-worker.py`, or by running `main` with `run_with_cpu_fallback` stubbed out.** A source-text check can pass while the command actually built is wrong. Driving `main` needs locks, systemctl, crawler and staging stubs, which is a lot of setup for one argv assertion. Extracting a builder is a small refactor with an existing precedent (`systemctl_cmd`), and it leaves the command itself unchanged.\n- **Returning early before loading the FAISS index when the refresh set is empty.** Rejected. It would save a trivial amount on an empty cache but reorder a path the other modes share, and it would skip the embedding-space verification. The run still reads and checks `--index` and resolves the embedding space, so an empty refresh needs a valid index and non-empty embeddings, as the other modes do.\n\n### Gotchas and risks\n\n- **Interrupted runs now leave a usable cache.** Because refresh never truncates, a failure or soft stop partway through leaves a cache where some entries are new and others are one run older, all still valid. With `--recreate-out-db`, the same failure left a truncated cache. If a GPU run fails and falls back to CPU, the retry reprocesses the same set: the earlier attempt only rewrote sources already in the set, so the join returns the same rows, and the result is idempotent.\n- **The Engine's lazy writes change which sources get refreshed.** Sources the Engine cached lazily between runs join the next run's refresh set and get rewritten at the updater's `--top-k 1000`, whatever limit the Engine wrote them with. This is the intended behaviour of cached \u2229 embeddings, but it means the set grows with traffic and does not shrink.\n- **Stale sources stay in the cache.** Their items may point at videos that no longer exist. This was accepted and is out of scope; the Engine's read path already filters targets.\n- **Read-only ATTACH while the write connection is open.** The ATTACH runs on the source connection while `out_db` is open for writing on the same file. This is the pattern `--incremental` already uses. Nothing is written before the rowids are materialised and the database is detached, so there is no lock contention.\n- **faiss in the test environment.** The new test needs faiss, the same dependency the job has. If the test environment lacks it, the test should fail loudly rather than skip, so the gate cannot pass without running.\n- **Existing doc and log wording.** `ORCHESTRATOR_SMOKE_TEST.md` line 16 says \"incremental similarity precompute\". That was already inaccurate and is not in the requirements' doc list, so it is noted here and left alone unless the operator wants a one-word fix. The smoke test itself only checks that the similarity DB file exists, which refresh still satisfies because it creates the schema. The updater's description string (\"full ANN rebuild\") is untouched.\n\n### Tradeoffs the operator accepts\n\n- **Stage time.** The stage now does work proportional to the number of cached sources that are still live, not all embeddings. The live cache was built full, so early runs save only the new videos and the file recreation. The gain grows only if the cache is ever rebuilt smaller or pruned, and pruning is out of scope.\n- **New videos after a merge.** Each new video gets no precomputed entry. Its first request pays the serve-time ANN cost and the lazy write.\n- **Stale sources.** They keep taking up cache space indefinitely.\n- **Empty-refresh requirements.** An empty refresh still needs a valid index and embeddings. This is a deliberate simplification: it keeps one code path, and the upgrade path, if it ever matters, is an early exit after selection.",
  "conflicts": "none",
  "impacts": "\n<impacts>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"argparse definition in main() (lines 277-334): new --refresh-existing flag\">\n**What changes.** A new `parser.add_argument(\"--refresh-existing\", action=\"store_true\", help=\"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\")` goes right after `--incremental` (lines 329-333), in the same multi-line style. `--incremental`'s help reads \"Compute only for videos that do not exist in similarity_sources.\" and the new help mirrors it. Argparse gives the attribute `args.refresh_existing`.\n\n**What depends on it.** The conflict check, the selection branch and the `mode=` log field (all below), the updater's new builder, and the new subprocess test. No other script or test parses this CLI. `scripts/run-dataset-build.sh` and the smoke test only call it.\n\n**Regression risk: low.** It is an additive store_true flag. The only way to break it is a typo in the dest name. `args.refresh_existing` is read in three places, so an inconsistent spelling would raise AttributeError at runtime and not at parse time. The new test catches that because it runs the real CLI.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"post-parse validation (lines 334-336): new parser.error conflict check before the --cpu/--gpu check\">\n**What changes.** Between `args = parser.parse_args()` (334) and `if not args.reset_only and not (args.cpu or args.gpu): parser.error(...)` (335-336), one check is added. If `args.refresh_existing` is set together with any of `incremental`, `reset`, `reset_only` or `recreate_out_db`, it calls `parser.error(...)` naming the conflicting flags. That exits with code 2 and prints the usage to stderr.\n\n**What depends on it.** The guarantee that the output file is untouched on a forbidden combination. That holds only because nothing has run yet: `connect_source_db` is at 370, the `--recreate-out-db` unlink at 373-386, the `--reset-only` unlink at 388-406, `connect_db`/`ensure_schema` at 408-409, and the `--reset` DELETE at 410-412. `logging.basicConfig` (338) and the signal handlers (362-367) also come later. The test's byte-identical/mtime/absent assertions for the four combinations depend on it.\n\n**Regression risk: medium.** It must stay *before* line 335. Otherwise `--refresh-existing --reset-only` without `--cpu` would still exit 2, but with the cpu/gpu message, and the test would need to match the message to notice. It must not be placed after `connect_db`. Combinations among the other four flags must not be rejected: `--reset --incremental` and `--recreate-out-db --incremental` work today and are not in scope. `--gpu-device` is validated much later (425-426) and is unaffected.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"source selection branch (lines 433-463): `if args.incremental:` becomes incremental-or-refresh, SQL chosen per mode\">\n**What changes.** The condition becomes `if args.incremental or args.refresh_existing:`. The shared parts stay as they are: `out_uri = f\"file:{...}?mode=ro\"` (437), `ATTACH DATABASE ? AS out_cache` (438), the rowid list comprehension (439-451), `DETACH DATABASE out_cache` (452), `iter_embedding_rows_by_rowids` (453) and `total_sources = len(pending_rowids)` (454). Only the SELECT text differs:\n- refresh: `SELECT e.rowid FROM video_embeddings e JOIN out_cache.similarity_sources s ON s.video_id = e.video_id AND s.instance_domain = e.instance_domain`;\n- incremental: the current LEFT JOIN \u2026 `WHERE s.video_id IS NULL`.\n\nThe existing comment (434-436) gets a one-line companion saying what refresh selects. The variable name `pending_rowids` still fits both modes.\n\n**What depends on it.**\n- The processed set, which must equal cached \u2229 embeddings.\n- `iter_embedding_rows_by_rowids` (61-76), which batches rowids 512 at a time under SQLite's variable limit.\n- The progress/ETA maths (519-541) and the `done processed=%d/%d` total.\n- The ATTACH needs the source connection opened with `uri=True` (`connect_source_db`, 52-58), which it is.\n- The attached file must already have the schema. `connect_db` + `ensure_schema` (408-409) run first, and `executescript` commits pending work before running DDL in autocommit, so a missing or empty cache is attachable and has the tables.\n\n**Regression risk: medium.**\n- The INNER JOIN is on raw `(video_id, instance_domain)` text. The Engine's lazy writer stores `source.get(\"instance_domain\") or \"\"` (`similarity_cache.py:110`), so a source cached with an empty domain never joins. That is correct: it is not \"still in embeddings\" under the same key.\n- A duplicated `similarity_sources` key cannot produce duplicate rowids, because the table has a PK on `(video_id, instance_domain)`.\n- Order: without an ORDER BY, rowids come back in join order. Nothing depends on the order except commit batching.\n- `--incremental` behaviour must stay byte-for-byte the same. A careless refactor of the shared block (for example moving the DETACH) would change it, and no existing test covers `--incremental`.\n- Issue 08 (stable ANN ids, plan wave 5a) will later migrate this job from rowid to `ann_id`. This join is one more site it must convert.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"`total sources=%d` log line (line 464): gains a mode= field\">\n**What changes.** `logging.info(\"total sources=%d\", total_sources)` becomes something like `logging.info(\"total sources=%d mode=%s\", total_sources, mode)`, where mode is `full` / `incremental` / `refresh-existing`. It is derived from args; the precedence when `--incremental` is combined with `--reset` should be spelled out, and stays `incremental`. The `done processed=%d/%d elapsed=%s` line (562-567) and the soft-stop line (554-560) do not change.\n\n**What depends on it.** Only the new test, which parses stderr: `basicConfig` (338) logs to stderr with format `%(levelname)s %(message)s`, so the line is `INFO total sources=N mode=...`. A grep of the repo outside the plan docs finds no other consumer of `total sources` or `done processed`. The updater's `run_cmd` does not capture child output, and the smoke test parses only the updater's `run:`/`done:` lines.\n\n**Regression risk: low.** The test's regex must be tolerant of the added field, for example `total sources=(\\d+)`.\n</impact>\n<impact path=\"engine/server/db/jobs/precompute-similar-ann.py\" element=\"unchanged dependencies used by refresh: ensure_schema (140-167), record_similarities (229-272), build_query_batch (93-107), the search loop (472-551), the --recreate-out-db and --reset-only unlink paths (373-406), the --reset DELETE (410-412), resolve_embedding_space / faiss.read_index / assert_index_matches_embeddings (414-420), set_nprobe (110-123)\">\n**What changes.** Nothing. Refresh relies on each of these unchanged:\n- `record_similarities` upserts `computed_at` (one value per run, set at 465 in epoch ms), deletes the source's items and inserts the new ranked items.\n- `build_query_batch` silently drops dim/length mismatches, so those sources keep their old rows.\n- The unlink and DELETE paths are unreachable under refresh because the conflict check blocks them.\n- The embedding-space check still runs on an empty refresh, so an empty refresh needs a readable index, a `.json` sidecar with a matching `model_name`/`embedding_dim`, and non-empty `video_embeddings`. Otherwise `resolve_embedding_space` raises \"No embeddings found\" and the run exits non-zero.\n\n**What depends on it.** Every mode shares this code. The new test's fixture must satisfy it:\n- `video_embeddings` columns `video_id, instance_domain, embedding, embedding_dim, model_name`, with one model/dim pair;\n- index ids equal to rowids > 0, since the loop drops `rowid_int <= 0` and self-matches;\n- a `<index>.json` sidecar with `model_name` and `embedding_dim` (`embedding_space.py:68-89`).\n\n**Regression risk: low (no edit).** Two test-fixture caveats:\n- `index.search(query, top_k + 1)` on a tiny index returns -1 ids, which are filtered out, so the item count is below `--top-k`. Assertions should not expect exactly top_k items.\n- `set_nprobe` calls `faiss.extract_index_ivf`, which raises on a flat index; this is caught by `except Exception` at 116.\n</impact>\n<impact path=\"engine/server/data/embedding_space.py\" element=\"resolve_embedding_space / assert_index_matches_embeddings\">\n**What changes.** Nothing.\n\n**What depends on it.** The refresh run and the new test fixture:\n- The sidecar must be `f\"{index_path}.json\"` with `model_name` equal to the DB's single `model_name` and `embedding_dim` equal to the dim.\n- `index.d` must equal the dim.\n- An empty `video_embeddings` table raises.\n\n**Regression risk: none from code.** The one risk is fixture mistakes, which make the test fail with a RuntimeError message in stderr.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"new module-level command builder placed next to systemctl_cmd (lines 401-412)\">\n**What changes.** A new keyword-only function in the `systemctl_cmd` style (`*,` parameters, one-line `\"\"\"Handle ...\"\"\"` docstring, returns `list[str]`). It takes `python_bin`, the script path, the prod db, the index, the similarity db and `use_gpu`. It returns the exact list at lines 1114-1134, with `--recreate-out-db` replaced by `--refresh-existing`: `[python_bin, script.as_posix(), \"--db\", prod, \"--index\", index, \"--out\", sim, \"--top-k\", \"1000\", \"--nprobe\", \"16\", \"--search-batch-size\", \"1024\", \"--refresh-existing\"]` plus `[\"--gpu\", \"--gpu-device\", \"0\"]` or `[\"--cpu\"]`.\n\n**What depends on it.** `main()` (the call site below) and the new updater test. That test loads the module with `importlib.util.spec_from_file_location` exactly as `tests/active/test_host_normalisation.py:78-87` does. Loading under the root test env works today: the module imports only stdlib, `scripts.cli_format` and `data.moderation`, and puts `server_dir` on `sys.path` itself (21-33).\n\n**Regression risk: medium, because of naming.** `main()` already has a local variable `precompute_cmd` (1114). If the builder is named `precompute_cmd` and main writes `precompute_cmd = precompute_cmd(...)`, Python treats the name as local for the whole of `main` and raises UnboundLocalError. That would happen only at the precompute stage, after the merge and ANN rebuild, which is the worst place for a failure. Use a distinct name (for example `build_precompute_cmd` / `similarity_precompute_cmd`), or rename the local. Paths should be passed as `Path` and converted with `.as_posix()` inside the builder, as the current literal does, so the argv strings are identical.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"main(): precompute stage call site (lines 1110-1139)\">\n**What changes.** The inline list literal and the `if args.use_gpu` suffix (1114-1134) are replaced by one call to the builder. `run_with_cpu_fallback(precompute_cmd, stage=\"precompute-similar-ann\", cwd=repo_root)` (1135-1139) is unchanged. `--fail-after-merge-before-similarity` (1110-1113) stays before it.\n\n**What depends on it.**\n- The production updater run. The Engine is stopped from the merge through this stage and started in the `finally` (1140-1150). It still is: issue 24 will move that later.\n- The smoke test, whose `similarity_precompute` stage duration is parsed from the `run:`/`done:` log lines that `run_cmd` writes (the marker is the script name, which is unchanged).\n- `purge_hosts` on the similarity DB (844-873, 1066-1074) runs earlier in the same run. It deletes rows for stale or denied hosts, so those sources leave the refresh set. That is the only pruning left, now that recreation is gone.\n\n**Regression risk: medium (behaviour, accepted).**\n- The cache is no longer truncated and rebuilt. New merged videos get no precomputed entry, and stale sources stay.\n- A cache that is missing at run time (first deployment, or a deleted file) now stays empty instead of being fully built. The stage logs `total sources=0` and exits 0, so the updater reports success with an empty cache. Worth stating in UPDATER_WORKER.md: the initial full build is `DATA_BUILD.md` \u00a75 / `run-dataset-build.sh`.\n- The GPU\u2192CPU retry reprocesses the same set, and the argv passes through `_to_cpu_cmd` unchanged apart from the GPU flags.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"_to_cpu_cmd (361-377) and run_with_cpu_fallback (380-398)\">\n**What changes.** Nothing.\n\n**What depends on it.** The refresh argv's CPU retry. `_to_cpu_cmd` drops `--gpu` and `--gpu-device <n>` and appends `--cpu`, so `--refresh-existing` survives. The retry cannot trip the new conflict check, because none of the four conflicting flags is ever in the list.\n\n**Regression risk: low.** The retry is idempotent: a partial GPU attempt only rewrote rows that were already cached, so the set is the same. The GPU attempt may have committed batches of 500 before failing, and the retry rewrites those again with a new `computed_at`.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"parse_args description string (lines 102-105) and module docstring (line 2)\">\n**What changes.** Nothing, as the plan says. The description says \"merge -> incremental jobs -> full ANN rebuild -> start service\". \"full ANN rebuild\" refers to the index, not the similarity cache, so it is not made wrong by this change.\n\n**Regression risk: none.** Listed so the next step does not treat it as missed.\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-orchestrator-smoke.py\" element=\"validate_outputs (735-760), assert_worker_log (482-500), parse_stage_durations (503-528), per-run path setup (864-872, 917-919)\">\n**What changes.** No edit. The behaviour it observes does change. Each run or scenario directory starts with no `similarity-cache.db` (the paths at 866/919 are fresh and not copied from prod). Under refresh the precompute creates the schema-only file and processes 0 sources, where before it built a full cache.\n\n**What depends on it.** The check at 750 only requires the file to exist, so it still passes. The markers still include `precompute-similar-ann.py`. The `similarity_precompute` duration will drop sharply, which is what it measures now: it is no longer a meaningful precompute timing.\n\n**Regression risk: low for pass/fail. The coverage lost is real:** the smoke run no longer exercises the FAISS search or write path of the precompute at all. That is not within the gate (the script is not in `tests/active`); note it for the operator.\n</impact>\n<impact path=\"scripts/run-dataset-build.sh\" element=\"similarity stage (lines 251-258)\">\n**What changes.** Nothing. It keeps `--top-k 20 --nprobe 16 --recreate-out-db \"${ACCEL}\"` as the full-build path.\n\n**What depends on it.** It is the documented way to build the initial full cache that refresh then maintains. It still works, because `--recreate-out-db` without `--refresh-existing` is allowed.\n\n**Regression risk: none.** Documentation consistency: the plan's DATA_BUILD \u00a75 flag note must describe `--recreate-out-db` as this script uses it.\n</impact>\n<impact path=\"engine/server/data/similarity_cache.py\" element=\"ensure_similarity_schema (19-46) and store_similarity_cache (\u224896-120): the Engine's own schema and serve-time writer\">\n**What changes.** Nothing.\n\n**What depends on it.** Refresh's source set grows with Engine traffic: any source the Engine stores lazily joins the next refresh and is rewritten at `--top-k 1000`. The Engine's schema must stay compatible with the job's `ensure_schema` (same tables and PK), because both open the same file. The writer stores `instance_domain or \"\"`, which affects which rows join (see the selection entry).\n\n**Regression risk: none from this build.** The accepted behaviour change (set only grows; pruning only via host purge) is recorded in the plan.\n</impact>\n<impact path=\"engine/server/data/similarity_cache_manager.py\" element=\"read_cached_similarities / should_write_cache / write_cache (42-96)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is the lazy path for new videos, which no longer get precomputed entries. `should_write_cache` writes only when the source has no cached rows, unless the policy is refresh. `read_cached_similarities` treats a count below the limit as a miss when `require_full` is set (61-68). Sources that refresh writes with fewer than top-k items stay partial, as they were under the full build.\n\n**Regression risk: none from this build.** It is the documented consequence: a new video's first request pays the ANN cost and the lazy write.\n</impact>\n<impact path=\"engine/server/data/similarity_candidates.py\" element=\"_write_cache (\u2248259)\">\n**What changes.** Nothing. It is the other half of the lazy write path named in the requirements as unchanged.\n\n**What depends on it.** It is the only way new videos enter the cache after this build, apart from a manual full build.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_precompute_similar_ann_refresh.py\" element=\"new test module (subprocess tests of --refresh-existing)\">\n**What changes.** A new file. It builds a source DB, a FAISS index plus `.json` sidecar, and a seeded cache in `tmp_path`. It runs the job and asserts on:\n- the processed set;\n- the shared new `computed_at` above the sentinel;\n- stale and uncached rows left unchanged;\n- a missing or empty cache giving exit 0 with the schema and 0 sources;\n- the four forbidden combinations exiting non-zero and leaving the file byte-identical, at the same mtime, or absent.\n\n**What depends on it.** The gate. `.un/skills/devsecops/config.json` needs a `test_groups` entry for it (see that entry).\n\n**Regression risk: HIGH, because of the interpreter. The plan's \"run it the way `test_precompute_random_rowids.py` does\" (via `sys.executable`) will not work.** `tests/last_test_validation.json:3-13` shows the suite runs under the root `pixi.toml` env (Python 3.14). That env's dependencies are the harness's own (`pyproject.toml:6`: anthropic, openai, pyyaml\u2026), with no numpy and no faiss. The job imports numpy at line 14, before its faiss guard, so under `sys.executable` it dies with ModuleNotFoundError. The test cannot `import faiss`/`numpy` in-process to build the index either. The established pattern for faiss/numpy work in `tests/active` is `ENGINE_PY` from `conftest.py:32` (`engine/.pixi/envs/default/bin/python`):\n- `test_video.py:197,216-218` builds `faiss.IndexIDMap(faiss.IndexFlatIP(d))` + `add_with_ids` inside an ENGINE_PY child;\n- `test_similar.py:616`, `test_popular_videos.py:92-93` and `test_internal_client_reads.py:144-145` follow the same pattern;\n- each asserts `ENGINE_PY.exists()` with the message \"run `pixi install` in engine/\", which fails loudly rather than skipping, as the plan wants.\n\nSo the job subprocess should run with `str(ENGINE_PY)`, and index construction (and vector normalisation) should happen in an ENGINE_PY child or a small child script. Pure-sqlite fixture work (the source DB with float32 blobs via `array(\"f\")`, the cache seeding, and the byte/mtime checks) can stay in the test process.\n\nOther fixture caveats:\n- The job reads the index with `IO_FLAG_MMAP | IO_FLAG_READ_ONLY` (417). The production index is `IndexIDMap2(IndexIVFPQ)` (`build-ann-index.py:110-113`). I did not verify that the installed faiss (1.13.2 per requirements) accepts the MMAP flag on a flat `IndexIDMap`; if it rejects it, use `IndexIDMap2(IndexIVFFlat(..., nlist=1))`, trained on the tiny set.\n- Rowids must be > 0, and self-matches are excluded.\n- The sidecar needs `model_name` and `embedding_dim`.\n- `computed_at` is in epoch milliseconds, so the sentinel must be small (e.g. 1).\n- The job's `main()` imports `server_config` from `engine/server/api`, so the env var checks in `server_config` apply. They are harmless unless `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` is set to garbage in the environment.\n- Use `cwd=tmp_path` and pass explicit `--db`/`--index`/`--out`, so the shared `whitelist.db`/`similarity-cache.db` defaults (lines 287-289) are never touched.\n- The mtime check needs the forbidden-combo run to open nothing, which the conflict check's placement guarantees.\n</impact>\n<impact path=\"tests/active/test_updater_precompute_cmd.py\" element=\"new test module (name illustrative): importlib load of updater-worker.py, asserts on the builder's argv\">\n**What changes.** A new file. It loads `engine/server/db/jobs/updater-worker.py` with importlib, as `test_host_normalisation.py:78-82` does. It calls the builder for `use_gpu=True` and `False` and asserts that `--refresh-existing` is present and `--recreate-out-db` absent. It could also assert that `_to_cpu_cmd(builder(use_gpu=True))` keeps `--refresh-existing`, a cheap check of the fallback path.\n\n**What depends on it.** The gate and the `config.json` mapping.\n\n**Regression risk: low.**\n- Loading the module runs only module-level code: path setup and imports of `scripts.cli_format` and `data.moderation`, which already work under the root env since `test_host_normalisation` passes.\n- Loading must not call `parse_args` or `resolve_default_engine_service_name`, which shells out to bash. Neither runs at import.\n- Use a distinct `module_name` from `\"updater_worker_job\"` or accept the re-exec; each spec load is a fresh module object, so a collision is harmless.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups map (lines 14-201)\">\n**What changes.** Add entries for the two new test files, mapping each to the sources it covers:\n- the refresh test \u2192 `engine/server/db/jobs/precompute-similar-ann.py` and `engine/server/data/embedding_space.py`;\n- the updater test \u2192 `engine/server/db/jobs/updater-worker.py`.\n\n`test_host_normalisation.py` already maps `updater-worker.py` (99-106), so that file also reruns when the updater changes.\n\n**What depends on it.** The test-selection harness. According to the issue-32 record (`docs/project/plans/archive/01-32-...record.md:1403`), an unmapped test file runs on every invocation.\n\n**Regression risk: low.** If the entries are forgotten, the tests still run (every time), so nothing is lost, only speed.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"ENGINE_PY constant (line 32)\">\n**What changes.** Nothing. It is the import the new refresh test should use (`from conftest import ENGINE_PY`), as `test_internal_client_reads.py:20` and `test_video.py:49` do.\n\n**Regression risk: none.** Importing conftest pulls in `client/backend/server.py` at module level (lines 37-43). That already happens for every test in the directory.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"generated validation record\">\n**What changes.** Nothing by hand. The harness regenerates it and adds entries for the new files.\n\n**Regression risk: none.** Listed only because it references test file names.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\" element=\"Execution Order step 10 (line 53); Outputs (line 28)\">\n**What changes.** Line 53 currently says `Update similarity cache incrementally (precompute-similar-ann.py --incremental)`. That is already wrong: the code passes `--recreate-out-db`. It is rewritten to `--refresh-existing`, with the semantics from the plan: it rewrites only sources already cached and still in `video_embeddings`, new videos are cached lazily by the Engine, and stale sources are left. Line 28 (\"Updated similarity cache\") stays true.\n\nOptionally, add one sentence saying the updater no longer builds a missing or empty cache: the initial full build is `DATA_BUILD.md` \u00a75.\n\n**Regression risk: low.** Doc only.\n</impact>\n<impact path=\"DATA_BUILD.md\" element=\"\u00a75 Precompute similarity cache (lines 252-266); updater cross-reference (line 30)\">\n**What changes.** A flag note is added after the example (after line 263 or 264). It covers `--incremental` (only uncached embeddings), `--recreate-out-db` (delete and recreate the file), `--reset`/`--reset-only` (clear tables / clear and exit), and `--refresh-existing`, which rewrites cached \u2229 embeddings, leaves the other rows alone, and cannot be combined with the other four (exit 2). The example block (256-262) and the `--top-k` paragraph (266) are unchanged.\n\nA pre-existing inaccuracy is not in scope: line 30 points at `engine/server/db/jobs/UPDATER_WORKER.md`, but the file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`. It is a one-word fix if the operator wants it.\n\n**Regression risk: low.** Doc only.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md\" element=\"Purpose list line 16 ('incremental similarity precompute')\">\n**What changes.** Nothing, per the plan (already inaccurate, and not in the requirements' doc list). Recorded so it is a known decision. After this build the accurate wording would be \"refresh of existing similarity cache sources\". The smoke run now produces an empty cache, as described in the smoke-test entry.\n\n**Regression risk: none.** This is doc drift only.\n</impact>\n<impact path=\"docs/project/issues/24-similarity-cache-shadow-swap.md\" element=\"Proposed solution line 15 (`run precompute-similar-ann.py --incremental`), triage notes line 46, gate description line 67\">\n**What changes.** Nothing is required by this plan. Line 15 still names `--incremental`, while lines 46/65 already say the shadow build uses \"whichever mode the updater uses once 25 is delivered\". A one-line comment under `## Comments` or an edit to line 15 to say `--refresh-existing` would keep issue 24 accurate for the next lane.\n\n**What depends on it.** Issue 24's future implementation. Its gate (\"the shadow holds no fewer `similarity_sources` rows than the active file\") works with refresh, because refresh never deletes sources.\n\n**Regression risk: low.** A stale issue text could lead lane 4b to wire `--incremental`.\n</impact>\n<impact path=\"docs/project/issues/25-similarity-precompute-existing-sources.md\" element=\"Status line and issue lifecycle\">\n**What changes.** On delivery, per `docs/project/triage-labels.md` / `issue-tracker.md`, the status becomes `complete` and the file moves to `docs/project/issues/archive/`. The validation item \"Updater stage time drops against the full-rebuild baseline\" was turned into a measurement, not a gate (record line 148). A comment should say so.\n\n**Regression risk: none.** This is bookkeeping, probably owned by a later step.\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"wave 3c row (line 82), 24/25 ordering note (line 125), wave 5a row (line 97)\">\n**What changes.** Nothing. Row 82 lists exactly the two code files this plan touches. Line 125 fixes the order as 25 before 24. Row 97 (issue 08) will later migrate this job's rowid usage, including the new join.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"updater timer paragraph (lines 130-134) and similarity-cache capacity note (line 263)\">\n**What changes.** Nothing. Line 131 says the updater \"precomputes similarity\", which is still true in a general sense. Line 263 says the cache holds 20 per seed (`--top-k 20`), while the updater writes 1000. That inconsistency already existed and is not in scope.\n\n**Regression risk: none.** Listed for completeness.\n</impact>\n</impacts>\n",
  "docs_checklist": "- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - updated: Rewrote Execution Order step 10 to describe the in-place `--refresh-existing` precompute and replace the incorrect `--incremental` claim.\n- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md \u00a75 now lists the precompute cache-mode flags, including `--refresh-existing` and the flags it can't be combined with. The broken link to UPDATER_WORKER.md is fixed.\n- [x] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - updated: Reworded the Purpose bullet on similarity precompute so it matches what the smoke test covers: the `--refresh-existing` stage runs against an empty cache and leaves only the schema.\n- [x] `docs/project/issues/24-similarity-cache-shadow-swap.md` - updated: Issue 24 now names `--refresh-existing` as the updater's precompute mode, and I added a comment recording that issue 25 is delivered.\n- [x] `docs/project/issues/25-similarity-precompute-existing-sources.md` - updated: Closed issue 25 as delivered. The archive copy has `Status: enhancement, complete` and a `### Delivered` comment, but I couldn't remove the original file.\n- [x] `DEPLOYMENT.md` - out of scope: The updater-timer paragraph (lines 130-134) says only that the updater \"precomputes similarity\" and stops/starts the Engine around the write-critical stages. Both are still true, because the stop/start sequence is unchanged. The line 263 note about `--top-k 20` describes the dataset build and was already inconsistent with the updater's `--top-k 1000`. This build did not change that inconsistency, and it is out of scope.\n- [x] `docs/project/adr/0008-similarity-cache-handoff-through-files.md` - out of scope: This ADR decides how a shadow-built cache is handed to running Engines (the build marker, reopen by inode, the pre-swap gate). None of that is built yet, and nothing in it names a precompute mode. Refresh never deletes sources, so the \"no fewer sources than the active file\" gate stays consistent.\n- [x] `docs/project/adr/0006-derived-ann-ids.md` - out of scope: Its only claim here is that the similarity cache is keyed by `(video_id, instance_domain)`. That is still true, and the refresh join uses exactly that key.\n- [x] `CONTEXT.md` - out of scope: The glossary entries `Shadow build` and `Build marker` describe issue 24's design. They do not name a precompute mode, and this build does not affect them.\n- [x] `docs/project/issues/08-stable-ann-ids.md` - out of scope: Line 19 says precompute moves to `ann_id` and \"incremental selection stays logical-key based\". The new refresh selection is also keyed on the logical `(video_id, instance_domain)`, so the statement holds. The extra rowid join site is recorded in the plan and inventory for issue 08's implementer; it is not a false claim in the issue.\n- [x] `docs/project/issues/plan.md` - out of scope: Row 82 lists the two code files this build touched, and line 125 already orders 25 before 24. Nothing in it describes the precompute mode.",
  "docs": [
    {
      "path": "engine/server/db/jobs/docs/UPDATER_WORKER.md",
      "note": "Rewrite Execution Order step 10 (line 53, which today wrongly says `--incremental`) to `precompute-similar-ann.py --refresh-existing`. It rewrites only sources already in `similarity_sources` that are still in `video_embeddings`; new videos are cached lazily by the Engine on first request; stale cached sources are left in place. Optionally add that a missing or empty cache stays empty after an updater run, and that the initial full build is `DATA_BUILD.md` \u00a75."
    },
    {
      "path": "DATA_BUILD.md",
      "note": "\u00a75 (lines 252-266): add a short flag note after the example. It covers `--incremental`, `--recreate-out-db`, `--reset`/`--reset-only` and the new `--refresh-existing` (cached \u2229 embeddings; other rows untouched; cannot be combined with the other four, exits 2). The example and the `--top-k` paragraph are unchanged. Optional one-word fix: line 30 points at `engine/server/db/jobs/UPDATER_WORKER.md`, but the file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`."
    },
    {
      "path": "engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md",
      "note": "No change per the plan. Line 16 (\"incremental similarity precompute\") was already inaccurate and is left alone unless the operator asks. The smoke run now yields an empty schema-only similarity cache."
    },
    {
      "path": "docs/project/issues/24-similarity-cache-shadow-swap.md",
      "note": "Optional: line 15 still says the shadow build runs `precompute-similar-ann.py --incremental`. Update it, or add a comment, to say `--refresh-existing` now that 25 is delivered, so lane 4b wires the right mode."
    },
    {
      "path": "docs/project/issues/25-similarity-precompute-existing-sources.md",
      "note": "On delivery: `Status:` becomes `complete` and the file moves to `docs/project/issues/archive/`. Comment that the stage-time validation became a measurement, not a gate."
    }
  ],
  "reassessments": 1,
  "draft": "## Draft: `--refresh-existing` for the similarity precompute, wired into the updater\n\n### What has to be tested (step 1)\n\n| Behaviour | Where it is proved |\n|---|---|\n| The processed set is exactly cached \u2229 embeddings, keyed on the raw `(video_id, instance_domain)` | refresh test: row state, plus `total sources=` and `done processed=` in stderr |\n| A processed source gets the run's single `computed_at`, above the sentinel, and fresh items (no sentinel items left) | refresh test |\n| Stale cached sources, including an empty-domain key, keep identical rows. Uncached embeddings gain no rows | refresh test: before/after snapshots |\n| A source dropped by `build_query_batch` (length mismatch) is counted in the total, not processed and not rewritten | refresh test: `done processed=3/4` and an unchanged row |\n| A missing or schema-only cache exits 0, has the schema and holds 0 sources | refresh test, parametrised |\n| Each of the 4 forbidden combinations exits 2, with the output unchanged (same bytes and mtime) or still absent | refresh test, 4 flags \u00d7 {seeded, absent} |\n| The updater's argv is the old one with `--recreate-out-db` swapped for `--refresh-existing`, and the CPU retry keeps the flag | updater test, exact list equality |\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/db/jobs/precompute-similar-ann.py` | flag, conflict check, `mode`, shared selection branch with the SQL chosen per mode, `mode=` in the `total sources` line |\n| `engine/server/db/jobs/updater-worker.py` | new `similarity_precompute_cmd` next to `systemctl_cmd`. `main()` calls it |\n| `tests/active/test_precompute_similar_ann_refresh.py` | new |\n| `tests/active/test_updater_precompute_cmd.py` | new |\n| `.un/skills/devsecops/config.json` | two `test_groups` entries |\n| `engine/server/db/jobs/docs/UPDATER_WORKER.md`, `DATA_BUILD.md`, `docs/project/issues/24-similarity-cache-shadow-swap.md` | doc text below |\n\n---\n\n### `precompute-similar-ann.py`\n\n**Flag**, right after `--incremental` (after line 333), in the same multi-line style:\n\n```python\n    parser.add_argument(\n        \"--refresh-existing\",\n        action=\"store_true\",\n        help=\"Recompute only videos that already exist in similarity_sources; leave all other cache rows untouched.\",\n    )\n```\n\n**Conflict check** goes between `args = parser.parse_args()` (334) and the `--cpu/--gpu` check (335). At that point nothing has run: no logging config, no signal handlers, no connection, no unlink.\n\n```python\n    args = parser.parse_args()\n    if args.refresh_existing:\n        conflicts = [flag for flag, enabled in ((\"--incremental\", args.incremental), (\"--reset\", args.reset), (\"--reset-only\", args.reset_only), (\"--recreate-out-db\", args.recreate_out_db)) if enabled]\n        if conflicts:\n            parser.error(f\"--refresh-existing cannot be combined with {', '.join(conflicts)}\")\n    if not args.reset_only and not (args.cpu or args.gpu):\n        parser.error(\"one of --cpu or --gpu is required unless --reset-only is used\")\n```\n\nWhat this guarantees:\n- `parser.error` exits 2 and prints the usage plus the message to stderr.\n- Combinations among the other four flags are not touched: `--reset --incremental` and `--recreate-out-db --incremental` still work.\n- Because the check comes first, `--refresh-existing --reset-only` without `--cpu` gets the conflict message, not the cpu/gpu one.\n\n**Mode and selection** replace lines 433-464. The `else` (full) branch is kept verbatim.\n\n```python\n        if args.refresh_existing:\n            mode = \"refresh-existing\"\n        elif args.incremental:\n            mode = \"incremental\"\n        else:\n            mode = \"full\"\n        if args.incremental or args.refresh_existing:\n            # Incremental mode compares source embeddings with already-computed rows\n            # from the output cache DB. We materialize only rowids first to avoid\n            # lock contention while writing to the output DB.\n            # Refresh mode selects the complement: embeddings whose source is already cached.\n            if args.refresh_existing:\n                selection_sql = \"\"\"\n                    SELECT e.rowid\n                    FROM video_embeddings e\n                    JOIN out_cache.similarity_sources s\n                      ON s.video_id = e.video_id\n                     AND s.instance_domain = e.instance_domain\n                    \"\"\"\n            else:\n                selection_sql = \"\"\"\n                    SELECT e.rowid\n                    FROM video_embeddings e\n                    LEFT JOIN out_cache.similarity_sources s\n                      ON s.video_id = e.video_id\n                     AND s.instance_domain = e.instance_domain\n                    WHERE s.video_id IS NULL\n                    \"\"\"\n            out_uri = f\"file:{out_db_path.as_posix()}?mode=ro\"\n            src_db.execute(\"ATTACH DATABASE ? AS out_cache\", (out_uri,))\n            pending_rowids = [int(row[\"rowid\"]) for row in src_db.execute(selection_sql)]\n            src_db.execute(\"DETACH DATABASE out_cache\")\n            row_iter = iter_embedding_rows_by_rowids(src_db, pending_rowids)\n            total_sources = len(pending_rowids)\n        else:\n            ...  # unchanged full-scan branch\n        logging.info(\"total sources=%d mode=%s\", total_sources, mode)\n```\n\nInvariants:\n- **Mode precedence.** Refresh cannot be combined with incremental (the parser blocks it). `--incremental` wins over `--reset` / `--recreate-out-db`, whose runs log `mode=incremental`. Those flags alone log `mode=full`. `--reset-only` returns before this line and never logs a mode.\n- **`--incremental` is unchanged.** Its SQL is the same text as before. The ATTACH, materialisation, DETACH and iteration order are the same.\n- **Missing or empty cache is safe to attach.** The ATTACH still runs after `connect_db` + `ensure_schema` (408-409). `executescript` has committed by then, so a missing or empty cache is attachable and has the tables. The join yields `[]`, so the log shows `total sources=0` and `done processed=0/0`, and the exit code is 0.\n- **Writes are limited to the selected set.** Under refresh, the unlink and DELETE paths cannot be reached. The only write is `record_similarities` for rows selected by the join. `computed_at` (465) is still set once per run.\n- **No duplicate rowids.** The PK on `similarity_sources(video_id, instance_domain)` guarantees this.\n\n---\n\n### `updater-worker.py`\n\n**Builder**, placed after `systemctl_cmd` (after line 412) in the same keyword-only style. It is deliberately not named `precompute_cmd`: that name is a local in `main()`, and reusing it would raise UnboundLocalError at the precompute stage.\n\n```python\ndef similarity_precompute_cmd(\n    *,\n    python_bin: str,\n    script_path: Path,\n    db_path: Path,\n    index_path: Path,\n    out_path: Path,\n    use_gpu: bool,\n) -> list[str]:\n    \"\"\"Handle similarity precompute cmd.\"\"\"\n    cmd = [\n        python_bin,\n        script_path.as_posix(),\n        \"--db\",\n        db_path.as_posix(),\n        \"--index\",\n        index_path.as_posix(),\n        \"--out\",\n        out_path.as_posix(),\n        \"--top-k\",\n        \"1000\",\n        \"--nprobe\",\n        \"16\",\n        \"--search-batch-size\",\n        \"1024\",\n        \"--refresh-existing\",\n    ]\n    if use_gpu:\n        cmd.extend([\"--gpu\", \"--gpu-device\", \"0\"])\n    else:\n        cmd.append(\"--cpu\")\n    return cmd\n```\n\n**Call site.** Lines 1114-1134 become the block below. `run_with_cpu_fallback(precompute_cmd, stage=\"precompute-similar-ann\", cwd=repo_root)` and the failure injection at 1110-1113 do not change.\n\n```python\n                precompute_cmd = similarity_precompute_cmd(\n                    python_bin=args.python_bin,\n                    script_path=script_dir / \"precompute-similar-ann.py\",\n                    db_path=prod_db,\n                    index_path=index_path,\n                    out_path=similarity_db,\n                    use_gpu=args.use_gpu,\n                )\n```\n\nThe argv strings are identical to the old literal apart from the one swapped flag. The `run:` log marker (the script name) does not change. `_to_cpu_cmd` passes `--refresh-existing` through unchanged.\n\n---\n\n### `tests/active/test_precompute_similar_ann_refresh.py`\n\nDocstring, in the style of `test_precompute_random_rowids.py`:\n\n```\n\"\"\"`precompute-similar-ann.py --refresh-existing` rewrites exactly the cached sources still in `video_embeddings` and nothing else.\n\n- Over a cache holding three live sources, two gone sources, an empty-domain key and one live source whose blob is too short, the job logs `total sources=4 mode=refresh-existing` and `done processed=3/4`. The three live sources share one new `computed_at` above the sentinel and hold only fresh ranked items. Every other cached row is unchanged, and uncached embeddings gain no rows.\n- Over a missing or a schema-only cache, the job exits 0 with both tables present and no source.\n- With `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`, the job exits 2 naming the conflict, and the output file keeps its bytes and mtime, or stays absent.\n\nThe job and the FAISS index build run under the Engine's pixi interpreter (`ENGINE_PY`), since numpy and faiss live only there. Every file is under tmp_path.\n\"\"\"\n```\n\n**Constants and fixture contents**\n\n```python\nPRECOMPUTE_JOB = ROOT / \"engine\" / \"server\" / \"db\" / \"jobs\" / \"precompute-similar-ann.py\"\nDIM = 4\nMODEL = \"test-model\"\nDOMAIN = \"a.example\"\nSENTINEL_COMPUTED_AT = 1  # computed_at is epoch ms, so any real run is far above this\nLIVE = [f\"v{i}\" for i in range(1, 9)]  # rowids 1..8, valid unit vectors, all in the index\nSHORT = \"v9\"  # rowid 9, embedding_dim 4 but a 3-float blob: in the join, dropped by build_query_batch\nCACHED_LIVE = [(\"v1\", DOMAIN), (\"v2\", DOMAIN), (\"v3\", DOMAIN)]  # expected processed set\nCACHED_UNTOUCHED = [(\"gone1\", DOMAIN), (\"gone2\", DOMAIN), (\"v5\", \"\"), (SHORT, DOMAIN)]  # stale, empty-domain key, skipped\nUNCACHED = [(f\"v{i}\", DOMAIN) for i in range(4, 9)]\nFORBIDDEN = [\"--incremental\", \"--reset\", \"--reset-only\", \"--recreate-out-db\"]\n```\n\n**Source DB (in-process, sqlite3 plus `array(\"f\")`).**\n- Table: `video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT)`.\n- Rows are inserted with explicit rowids 1..9.\n- Vector i is `[cos i, sin i, cos 2i, sin 2i]`, normalised with `math.hypot`, then packed as `array(\"f\", \u2026).tobytes()`.\n- v9 gets `array(\"f\", [1, 0, 0]).tobytes()` with `embedding_dim=4`.\n- Every row has one model/dim pair, so `resolve_embedding_space` passes.\n\n**Index (an `ENGINE_PY` child, `BUILD_INDEX_CHILD`).**\n- It reads the rows whose blob is `DIM*4` bytes and builds `faiss.index_factory(DIM, \"IDMap2,IVF1,Flat\", faiss.METRIC_INNER_PRODUCT)`.\n- It then trains, calls `add_with_ids` with the rowids, and runs `faiss.write_index`.\n- The test writes the sidecar `f\"{index}.json\"` = `{\"model_name\": MODEL, \"embedding_dim\": DIM}`.\n- **Why IVF and not flat.** This is the same inverted-list family as production (`IndexIDMap2(IndexIVFPQ)`), so the job's `IO_FLAG_MMAP | IO_FLAG_READ_ONLY` read and `set_nprobe` are known to work. nprobe 16 over nlist 1 is clamped by faiss. The \"too few training points\" warning is harmless.\n- **Failure mode.** The child's non-zero exit is asserted with its stderr, and `ENGINE_PY.exists()` is asserted with the message \"run `pixi install` in engine/\". A missing faiss fails the test and never skips it.\n- **Sharing.** The source DB and index are built once, as a module fixture via `tmp_path_factory`. The job opens the DB read-only.\n\n**Cache seeding.**\n- Each test creates its cache with the job itself: `--reset-only --out <cache>`. That gives one schema source, the real `ensure_schema`, and the setup's exit code is asserted.\n- It then inserts through sqlite3, for each key in `CACHED_LIVE + CACHED_UNTOUCHED`:\n  - `similarity_sources(key, SENTINEL_COMPUTED_AT)`;\n  - two items, `(\"sentinel-a\", DOMAIN, 0.5, 1)` and `(\"sentinel-b\", DOMAIN, 0.4, 2)`.\n\n**Helpers.**\n\n```python\ndef _run_job(tmp_path: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:\n    return subprocess.run([str(ENGINE_PY), str(PRECOMPUTE_JOB), \"--db\", str(source_db), \"--index\", str(index_path), \"--out\", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, encoding=\"utf-8\", timeout=120)\n```\n\n- `_sources(path)` and `_items(path, key)` read through `file:\u2026?mode=ro` with ORDER BY, returning tuples.\n- `_counts(stderr)` returns `int(re.search(r\"total sources=(\\d+)\", \u2026))` and the `done processed=(\\d+)/(\\d+)` pair.\n\n**Tests.**\n1. **`test_refresh_rewrites_exactly_cached_live_sources`**\n   - Seed, snapshot `_sources` and every untouched key's items, then run `--refresh-existing --cpu --top-k 3`.\n   - Assert `returncode == 0`, `mode=refresh-existing` in stderr, total 4, done `(3, 4)`.\n   - The live keys all have the same `computed_at` T > 1.\n   - Each live key's items have no `sentinel-` target and ranks `1..n` with 1 \u2264 n \u2264 3. Every target is a LIVE key on DOMAIN other than the source itself.\n   - The untouched keys' source rows and items equal the snapshot. For v9, this proves a skipped source is not rewritten.\n   - No `similarity_sources` or `similarity_items` source row exists for any `UNCACHED` key.\n   - `COUNT(*)` of `similarity_sources` is still 7.\n2. **`test_refresh_over_missing_or_empty_cache_is_a_no_op`**, parametrised `[\"missing\", \"empty\"]`\n   - \"empty\" is created by `--reset-only`.\n   - Assert: exit 0, total 0, done `(0, 0)`, both tables in `sqlite_master`, 0 sources.\n3. **`test_refresh_rejects_each_destructive_flag`**, parametrised FORBIDDEN \u00d7 `[\"seeded\", \"absent\"]`\n   - Record `read_bytes()` and `stat().st_mtime_ns`, or absence.\n   - Run `--refresh-existing <flag> --cpu`.\n   - Assert `returncode == 2`, `\"--refresh-existing cannot be combined with\"` and the flag in stderr, and the bytes/mtime unchanged or the file still absent.\n\n### `tests/active/test_updater_precompute_cmd.py`\n\n- The module is loaded with `importlib.util.spec_from_file_location(\"updater_worker_precompute\", JOBS_DIR / \"updater-worker.py\")`, as `test_host_normalisation._load_job` does.\n- `test_updater_builds_refresh_command`, parametrised `use_gpu`:\n  - It asserts the builder's list `==` the old literal with `\"--refresh-existing\"` in place of `\"--recreate-out-db\"`, with the `[\"--gpu\", \"--gpu-device\", \"0\"]` or `[\"--cpu\"]` suffix.\n  - It asserts `\"--recreate-out-db\" not in cmd`.\n  - The inputs are fixed `Path`s under tmp_path and `python_bin=\"python3\"`.\n- `test_cpu_fallback_keeps_refresh`: `module._to_cpu_cmd(gpu_cmd) == cpu_cmd`.\n\n### `.un/skills/devsecops/config.json`\n\n```json\n    \"test_precompute_similar_ann_refresh.py\": [\n      \"engine/server/db/jobs/precompute-similar-ann.py\",\n      \"engine/server/data/embedding_space.py\"\n    ],\n    \"test_updater_precompute_cmd.py\": [\n      \"engine/server/db/jobs/updater-worker.py\"\n    ]\n```\n\n### Docs\n\n**`UPDATER_WORKER.md`, line 53:**\n\n> 10. Refresh the similarity cache's existing entries (`precompute-similar-ann.py --refresh-existing`). Only sources already in `similarity_sources` whose video is still in `video_embeddings` are recomputed and rewritten. Videos added by this run get no entry here; the Engine caches each one the first time it is requested. Cached sources whose video is gone are left in place. A missing or empty cache stays empty after this step, so build the initial cache with `DATA_BUILD.md` \u00a75.\n\n**`DATA_BUILD.md` \u00a75**, inserted after the code block (after line 263):\n\n> Output modes:\n> - no mode flag: compute every row of `video_embeddings`, upserting into the existing cache.\n> - `--reset`: clear both cache tables, then compute every row.\n> - `--recreate-out-db`: delete and recreate the cache file, then compute every row (this is what `scripts/run-dataset-build.sh` runs).\n> - `--reset-only`: recreate the cache file empty and exit; needs neither `--cpu` nor `--gpu`.\n> - `--incremental`: compute only videos not yet in `similarity_sources`.\n> - `--refresh-existing`: recompute only videos already in `similarity_sources` that are still in `video_embeddings`, leaving every other cache row untouched. The updater runs this mode. It cannot be combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` (the job exits 2).\n\n**Issue 24, line 15:** `--incremental` becomes `--refresh-existing`. The issue-25 status/archive move is left to the delivery step.\n\n---\n\n### Check against plan and requirements (step 2)\n\n- **Pass 1: plan versus requirements, one by one.**\n  - Help text, flag and exclusivity are all met, with exit 2 before any file is touched. `--cpu`/`--gpu` are still required.\n  - Selection: INNER JOIN, read-only ATTACH, materialise, DETACH, iterate by rowids; `total_sources` is `len`.\n  - The search/commit/soft-stop code is untouched, and the rewrite goes through `record_similarities`.\n  - There is no other write. Skipped rows are not rewritten.\n  - Missing or empty cache gives exit 0: `ensure_schema` runs before the ATTACH.\n  - Logging reuses `total sources=`, with a `mode=` field.\n  - Updater argv changes only by the flag.\n  - Docs: step 10 and the \u00a75 note. `run-dataset-build.sh` is unchanged.\n  - Tests cover every validation bullet on tmp files only.\n- **Pass 2: where the draft deliberately departs from the plan text, with the impact inventory's reason.**\n  - Tests run under `ENGINE_PY`, not `sys.executable`: the root env has no numpy or faiss.\n  - The builder is named `similarity_precompute_cmd`, to avoid the UnboundLocalError on the `precompute_cmd` local.\n  - The conflict check sits before the cpu/gpu check.\n  - The fixture uses an IVF1 index, so the MMAP read is known to work.\n  - The pass converged: nothing else is left unmet.\n\n### Deliberate simplifications (named)\n\n- **An empty refresh still reads and verifies the index.** It needs non-empty embeddings, a readable index and a valid sidecar. This keeps one code path for all modes. The upgrade path is an early exit after selection.\n- **One schema source in the tests.** Seeding goes through `--reset-only` rather than a copied DDL, so a broken `--reset-only` shows up as a setup failure in this test.\n\n### Notes for the operator (not in the gate)\n\n- **Smoke test coverage drops.** The orchestrator smoke run starts every run with no similarity cache. It now produces a schema-only cache and no longer exercises the precompute's FAISS or write path. Its `similarity_precompute` duration stops being a meaningful baseline.\n- **Stale wording left alone.** `ORCHESTRATOR_SMOKE_TEST.md` line 16 and `DATA_BUILD.md` line 30's path are unchanged, per the settled doc list.\n",
  "coordination": "none. Phases 1 and 2 need the Engine pixi environment with numpy and faiss (`pixi install` in engine/). This is a local prerequisite that other tests in tests/active already share, not a credential or a manual step. If it is missing, the test fails and does not skip.",
  "tests": {
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:74, :76 and :80 \u2014 for each of the four flags \u00d7 {seeded, absent}, `result.returncode == 2`, exactly one `precompute-similar-ann.py: error: ` line in stderr, and the set of whole `--flag` tokens on that line, intersected with the four destructive flags, `== {flag}`. Supported by :79 (`--refresh-existing` is on the line) and :95/:97 (with `--refresh-existing --cpu` alone there is no error line and the job goes on to create `--out`).",
          "expected": "Exit 2, and one line `precompute-similar-ann.py: error: --refresh-existing cannot be combined with <flag>` whose destructive tokens are exactly {flag}. The run confirmed that argparse puts the error on its own `prog: error: message` line after the usage block, and that the usage block lists every flag; this is why only the error line is searched. With the flag alone, the run gets past parsing and creates `--out`. The probe saw this for `--cpu` alone: rc=1 and the absent file exists afterwards.",
          "wrong_implementation": "The code as it stands, which does not know the flag: the run showed exit 2 and the line `precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing`, so the intersection is `set()` and :80 goes red on all 8 cases. A check that names all four flags at once, or names the wrong one, gives an intersection other than {flag}. A plain substring check would let `--reset` match inside `--reset-only`; whole tokens prevent that. A guard that refuses `--refresh-existing` on its own prints an error line with no destructive flag, which fails :95."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:82 and :83 \u2014 for a seeded `--out`, the file still exists and `(read_bytes(), st_mtime_ns) == before`. :85 \u2014 for an absent `--out`, `not out_path.exists()`. Both hold after each of the four refused combinations.</expected>",
          "expected": "Seeded: the file exists and has the same bytes and mtime. Absent: still absent. Seen in the probe on the argparse-exit path, which is the same exit `parser.error` takes: rc=2, seeded exists=True unchanged=True, absent exists=False.",
          "wrong_implementation": "A conflict check placed after the output file is opened (after `connect_db`/`ensure_schema`, the `--reset` DELETE, or the `--reset-only`/`--recreate-out-db` unlink). The probe showed what the destructive paths do to the observable: in every absent case the file is created (exists=True for `--cpu`, `--incremental --cpu` and `--reset --cpu`), so :85 goes red for all four flags. In the seeded `--reset` case the bytes change (unchanged=False), so :83 goes red. `--reset-only` and `--recreate-out-db` unlink the seeded file and recreate it or leave it removed, so :82/:83 go red; this last one comes from reading the source (lines 373-406) and was not probed. Seeded `--incremental` was observed to leave the file unchanged, so that one cell is carried only by its absent twin."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Combining `--refresh-existing` with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` exits 2, naming the conflicting flag on stderr."
        },
        {
          "id": "C2",
          "text": "After a rejected combination the output file keeps its bytes and mtime, or stays absent if it was absent."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py  9 failed                               0.0s\n  ------------------------------------------------------------------\n  total                                                               9 failed                               2.4s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:131, :132, :134, :135 \u2014 over the seeded cache, `--refresh-existing --cpu --top-k 3` exits 0, stderr contains `mode=refresh-existing`, the logged `total sources=` is exactly (\"4\",), and `done processed=` is exactly (\"3\", \"4\")",
          "expected": "rc 0, then `INFO total sources=4 mode=refresh-existing` and `INFO done processed=3/4`. Four are selected (v1, v2, v3 and v9, the cached keys still in video_embeddings) and three processed, because build_query_batch drops v9's 3-float blob. The run showed that this drop really happens on this fixture: today's full scan logs `total sources=9` and `done processed=8/9`.",
          "wrong_implementation": "The code as it stands, a full scan with no `mode=` field. The run showed rc 0, no `mode=` in stderr, `total sources=9` and `done processed=8/9`, so :132 goes red. The incremental LEFT JOIN / IS NULL reused for refresh selects the 5 uncached keys and logs 5 and 5/5. A join on video_id alone also picks up (v5, live.example) and logs 5 and 4/5."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:138, :140, :142, :144, :145 \u2014 v1, v2 and v3 share exactly one `computed_at`, which lies between the wall-clock ms taken before and after the run and above the sentinel 1. Each has items ranked exactly [1, 2, 3], none points at the sentinel target, and every target is a LIVE key other than the source itself.",
          "expected": "The probe ran the same seeded cache through the job's rewrite path (today's full scan writes v1-v3 through the same record_similarities). One stamp, 1790808419854, fell inside the window [1790808419716, 1790808419887]. v1 got [(v2,1),(v8,2),(v4,3)], v2 got [(v1,1),(v3,2),(v8,3)] and v3 got [(v4,1),(v2,2),(v1,3)], all on live.example, with no sentinel item left.",
          "wrong_implementation": "A refresh that selects the right keys but never rewrites them, for example one that only updates `computed_at` or skips record_similarities. v1-v3 then keep computed_at 1 and the single sentinel item: :140 and :142/:144 go red. A per-row stamp would give more than one stamp and fail :138. Dropping the self-exclusion would put the source among its own targets and fail :145."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:163, :165, :166, :170, :171, :172 \u2014 for a missing cache and for a schema-only cache: rc 0, `total sources=` (\"0\",), `done processed=` (\"0\", \"0\"), both cache tables in sqlite_master, and 0 rows in each",
          "expected": "rc 0, `total sources=0 mode=refresh-existing`, `done processed=0/0`, and a file holding both empty tables. The job's own connect_db + ensure_schema creates the tables before selection runs. The probe saw the missing-cache run exit 0 and leave the file in place. The table-list and 0-row assertions have not been observed passing, because the run stops at :165. They rest on ensure_schema running before selection, which the phase does not change.",
          "wrong_implementation": "The code as it stands. The run showed rc 0 and `total sources=9` in both the missing and the empty case, so :165 fails with ('9',) == ('0',). If the run reached :171, 8 source rows would be written. A refresh that treats an empty cache as \"refresh everything\" gives the same result."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:146 \u2014 gone1, gone2, (v5, \"\") and v9 each have a `computed_at` and items equal to the pre-run snapshot (control :147: that snapshot holds the sentinel stamp)",
          "expected": "Each of the four keeps (1, [('sentinel-target', 'sentinel.example', 0.5, 1)]). The probe showed exactly this before and after the run.",
          "wrong_implementation": "A refresh that prunes cached sources that are gone from video_embeddings: gone1/gone2 read (None, []). A refresh that clears items for every selected key before search, including ones build_query_batch then drops: v9 reads (1, []). A key match that ignores the empty domain and rewrites (v5, \"\"): (v5, \"\") gets a new stamp and new items."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:148, :149 \u2014 v4 to v8 on live.example have no source row and no items, and similarity_sources still holds exactly 7 rows",
          "expected": "{key: (None, []) for each of v4..v8}, and COUNT = 7.",
          "wrong_implementation": "The code as it stands (full scan). The probe showed v4-v8 each gaining a source row with stamp 1790808419854 and 3 items, and COUNT 12. A join on video_id alone writes (v5, live.example). The incremental outer join writes all five."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Each cached source still in `video_embeddings` that `build_query_batch` accepts is rewritten with the run's single new `computed_at` and only fresh ranked items, and nothing is selected when the cache is missing or schema-only."
        },
        {
          "id": "C2",
          "text": "Every other cache row, whether a stale source, an empty-domain key or a length-skipped source, is left as it was, and uncached embeddings gain no rows."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py  3 failed                               0.0s\n  ------------------------------------------------------------------\n  total                                                               3 failed                               1.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:44 \u2014 for each `use_gpu` in {True, False} (parametrised ids `gpu`, `cpu`), `similarity_precompute_cmd(python_bin=\"python3\", use_gpu=..., script_path, db_path, index_path, out_path)` with four distinct tmp_path Paths equals, as a list: `python3, <tmp>/jobs/precompute-similar-ann.py, --db, <tmp>/prod.db, --index, <tmp>/ann.faiss, --out, <tmp>/similarity-cache.db, --top-k, 1000, --nprobe, 16, --search-batch-size, 1024, --refresh-existing`, then `--gpu, --gpu-device, 0` or `--cpu`.",
          "expected": "Under the right implementation, each case returns exactly that list. The probe read the old literal out of `main` at updater-worker.py:1114-1130 with ast: `args.python_bin, (script_dir / 'precompute-similar-ann.py').as_posix(), '--db', prod_db.as_posix(), '--index', index_path.as_posix(), '--out', similarity_db.as_posix(), '--top-k', '1000', '--nprobe', '16', '--search-batch-size', '1024', '--recreate-out-db'`. The expected list is that literal with its last token swapped. The probe also saw `f\"{tmp_path}/prod.db\" == (tmp_path / \"prod.db\").as_posix()` \u2192 True. Today both cases are red with `AttributeError: module 'updater_worker_precompute' has no attribute 'similarity_precompute_cmd'` at line 42.",
          "wrong_implementation": "Four builders fail this comparison. (a) One that keeps `--recreate-out-db` and appends `--refresh-existing` reads `[..., '1024', '--recreate-out-db', '--refresh-existing', ...]`. (b) One that swaps db/out, or index/out, puts the wrong path in a slot, and the four paths are distinct so the lists differ. (c) One that drops or changes a tuning value, or puts `--refresh-existing` after the accelerator suffix, gives a different order. (d) One that ignores `use_gpu` returns the GPU suffix in the `cpu` case, or the reverse."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:45 \u2014 `\"--recreate-out-db\" not in cmd`, for both `use_gpu` values.",
          "expected": "True in both cases under the right implementation. Its positive control is line 44 on the same `cmd`, which shows that the builder ran and returned the full argv. Today it is not reached, because line 42 raises AttributeError.",
          "wrong_implementation": "A builder that adds `--refresh-existing` but leaves the old destructive flag in the argv would contain `'--recreate-out-db'`, and this line would fail. It is the negative half of \"replaced by\", stated on its own so the failure message names the destructive flag."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:54 \u2014 `_to_cpu_cmd(gpu_cmd)`, where `gpu_cmd` is the builder's `use_gpu=True` argv, equals `[python3, <script>, --db, <prod.db>, --index, <ann.faiss>, --out, <similarity-cache.db>, --top-k, 1000, --nprobe, 16, --search-batch-size, 1024, --refresh-existing, --cpu]`. It is armed by the control at line 52, which checks that `gpu_cmd[-3:] == ['--gpu', '--gpu-device', '0']`, because `run_with_cpu_fallback` retries only a command carrying `--gpu`.",
          "expected": "Exactly the CPU list. This was observed: the probe ran the real `_to_cpu_cmd` over the hand-built GPU list and it printed `['python3', '/tmp/pytest-of-enduser/pytest-6645/test_probe0/jobs/precompute-similar-ann.py', '--db', '.../prod.db', '--index', '.../ann.faiss', '--out', '.../similarity-cache.db', '--top-k', '1000', '--nprobe', '16', '--search-batch-size', '1024', '--refresh-existing', '--cpu']`. Today the test is red at line 50 with AttributeError, because the builder is missing.",
          "wrong_implementation": "Three cases fail here. (a) A change to `_to_cpu_cmd` that strips the non-GPU flags, or rebuilds the argv from a fixed template, drops `--refresh-existing`. (b) One that skips only `--gpu-device` and not its value leaves a stray `'0'`. (c) One that appends `--cpu` without the membership check, or keeps `--gpu`, produces a different list. Separately, a builder that ignored `use_gpu=True` and emitted `--cpu` would be caught by the line 52 control, not passed vacuously."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "For both `use_gpu` values, `similarity_precompute_cmd` returns the previous argv with `--recreate-out-db` replaced by `--refresh-existing`."
        },
        {
          "id": "C2",
          "text": "`_to_cpu_cmd` applied to the GPU argv gives the CPU argv, keeping `--refresh-existing`."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py  4 failed                               0.0s\n  ------------------------------------------------------------------\n  total                                                               4 failed                               0.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll 8 parametrizations of `test_refresh_rejects_each_destructive_flag` should fail at line 80 on `assert named & set(DESTRUCTIVE_FLAGS) == {flag}`. The current parser has no `--refresh-existing`, so argparse exits 2 with the single line `precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing`. That line names no destructive flag, so the intersection is `set()`, and lines 74, 76 and 79 pass before it. `test_refresh_alone_is_not_refused` should fail at line 95 on `assert _error_lines(result.stderr) == []`, because the same unrecognized-arguments line is there.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_precompute_similar_ann_refresh.py (NEW), which does not resolve. That file was not read, and the checks did not need it.\n2. .un/skills/devsecops/config.json was read. It holds only test-group mappings and plays no part in this test's assertion form.\n3. Whether `ENGINE_PY` (tests/active/conftest.py:32) exists on disk was not checked, since that would mean running the test. If it is missing, the test fails at line 40 on the `ENGINE_PY.exists()` precondition instead of at the predicted line 80.\n\nBasis:\n- Anti-pattern pass (rules/shape.md): no entry matches.\n  - **doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep:** the test never reads a `.md` file.\n  - **hardcoded-spec-mirror:** `DESTRUCTIVE_FLAGS` (line 27) is only used as parametrized input. It is never compared for equality against a code constant.\n  - **tautological-assertion:** the expected values are the parameter and the exit code 2. The test works none of them out the way the code would.\n  - **echoed-literal:** `flag` is an input that line 80 expects back, but the job's own conflict check produces the error line in between. Removing that check makes line 80 fail.\n  - **absence-only-assertion:** the `absent` case's `assert not out_path.exists()` (line 85) comes after positive assertions in the same test (lines 74, 76, 79, 80). Test 2's `== []` (line 95) is paired with `assert out_path.exists()` (line 97).\n  - **single-value-pin:** each of the four flags must appear alone in the error, so a hard-coded conflict message fails three of the four.\n- Ladder pass (rules/shape.md `<ladder>`): the code under test is a CLI script, and the clauses are its exit code, its stderr and what it leaves on disk. That is rung 2 (subprocess) combined with rung 3 (file bytes and mtime), which is the highest rung that fits. It is not the anti-rung, and nothing is shifted to a lower rung, so `<downshift_rule>` does not apply.\n- Stub question: the test does not pass against these plausible wrong implementations:\n  - **Current code (flag unknown):** fails at line 80.\n  - **`--refresh-existing` accepted but no conflict check:** fails at line 74.\n  - **A fixed conflict message:** fails at line 80 for three of the four flags.\n  - **Conflict check placed after the output file is opened:** the job runs `connect_db` at engine/server/db/jobs/precompute-similar-ann.py:408, and `--recreate-out-db`/`--reset-only` delete the file at lines 383 and 396. The `absent` case fails at line 85 and the seeded case fails at line 83.\n  - **A job that rejects `--refresh-existing` in every case:** fails at line 95.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 13 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `--refresh-existing` with any of the four destructive flags \"exits 2\" | :74 (parametrized over all four at :61) | only some flags rejected; a refusal raised inside `main`'s try block (exit 1) instead of a usage error | CARRIED |\n| C1b | must_prove | \"naming the conflicting flag on stderr\" | :80 | a generic refusal naming no flag; naming the wrong flag; a message listing all four. On its own, :80 also passes the \"unrecognized arguments: --refresh-existing <flag>\" error that an unimplemented flag produces. :95 rules that case out. | CARRIED |\n| C2a | must_prove | seeded output \"keeps its bytes and mtime\" | :83 | the `--reset` DELETE or the `--recreate-out-db` unlink running before the refusal; a rewrite that leaves the same bytes but a new mtime | CARRIED |\n| C2b | must_prove | absent output \"stays absent\" | :85 | `connect_db`/`ensure_schema` creating `--out` before the refusal | CARRIED |\n| D1 | docstring | \"refuses ... before it touches `--out`\" (module :1) | :83, :85 | any write, or creation of the file, ahead of the argument check | CARRIED |\n| D2 | docstring | \"exits 2\" (module :3, fn :63) | :74 | a non-argparse failure exit | CARRIED |\n| D3 | docstring | \"on one argparse error line\" (module :3, fn :63) | :76 | a traceback or logged RuntimeError, which carries no `prog: error:` line; a refusal spread over several error lines | CARRIED |\n| D4 | docstring | error line names `--refresh-existing` (module :3) | :79 | a message naming only the destructive flag | CARRIED |\n| D5 | docstring | names \"that flag and no other of the four\" (module :3, fn :63 \"`flag` alone of the four\") | :80 | a blanket message listing every destructive flag; `--reset` mis-matched inside `--reset-only`, which the whole-token regex at :78 prevents | CARRIED |\n| D6 | docstring | \"over a seeded cache or none\" (module :3) | :60 with :74\u2013:80 run under both params | a refusal that only happens when the cache exists, or only when it is absent | CARRIED |\n| D7 | docstring | \"a seeded `--out` keeps its bytes and mtime\" (module :4, fn :63) | :82, :83 | deletion (:82); content or timestamp change (:83) | CARRIED |\n| D8 | docstring | \"an absent one is still absent\" (module :4, fn :63) | :85 | creation of `--out` on the refusal path | CARRIED |\n| D9 | docstring | `--refresh-existing --cpu` alone \"prints no argparse error\" (module :5, fn :89) | :95 | a parser that refuses `--refresh-existing` whatever it is paired with, or does not recognise it at all | CARRIED |\n| D10 | docstring | \"goes on to create `--out`\" (module :5, fn :89) | :97 | a refusal of the flag-alone case by non-argparse means before the output connect | CARRIED |\n| D11 | docstring | \"runs as a child process under the engine's pixi interpreter\" (module :7) | :40, :41 | an in-process import or a different interpreter | CARRIED |\n| D12 | docstring | \"on temporary sqlite files\" (module :7) | :33, :41, :65 | running against the repo's real `--db`/`--out` defaults | CARRIED |\n| D13 | docstring | `_seed_cache`: cache \"laid out by the job's own `--reset-only`\" holding a sentinel (:45) | :47 | a seeded cache the job did not create, so C2a would compare a foreign file | CARRIED |\n| N1 | name | \"refresh rejects each destructive flag\" | :74, :80 over :61 | rejecting a subset of `DESTRUCTIVE_FLAGS`, which matches C1's four exactly | CARRIED |\n| N2 | name | \"refresh alone is not refused\" | :95, :97 | a refresh flag refused unconditionally | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:72\n   `result = _run_job(tmp_path, out_path, \"--refresh-existing\", flag, \"--cpu\")`\n   Each run pairs `--refresh-existing` with one destructive flag and always adds `--cpu`. Two cases at the edge of the accepted input are untested:\n   - Two destructive flags at once, e.g. `--refresh-existing --reset --incremental`. :80 would then need a stated expectation for which flags the line names.\n   - A combination without an accelerator flag. The job's existing `--cpu/--gpu` check at precompute-similar-ann.py:335 can then fire first, and C1's \"naming the conflicting flag\" is not pinned for that order.\n   C1's four single-flag cases are fully covered, so this is not a Critical.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_precompute_similar_ann_refresh.py (NEW), which does not resolve. It was not read.\n2. The copy of engine/server/db/jobs/precompute-similar-ann.py I read has no `--refresh-existing` option (`main` at :275\u2013:336). I could not check the refusal path or the order of its argument checks against the code. I judged C1 and C2 on argparse's error-line convention and on where `main` first opens `--out` (:370\u2013:409).\n3. Only the first 40 of 202 lines of .un/skills/devsecops/config.json were read. It carries no behaviour the claims depend on.\n4. No `fixtures_path` was supplied. The test uses no pytest fixture beyond `tmp_path`. `ENGINE_PY` is imported from tests/active/conftest.py and resolved there (:32).",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll 8 parametrizations of `test_refresh_rejects_each_destructive_flag` should fail at line 80 on `assert named & set(DESTRUCTIVE_FLAGS) == {flag}`. The current parser has no `--refresh-existing`, so argparse exits 2 with the single line `precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing`. That line names no destructive flag, so the intersection is `set()`, and lines 74, 76 and 79 pass before it. `test_refresh_alone_is_not_refused` should fail at line 95 on `assert _error_lines(result.stderr) == []`, because the same unrecognized-arguments line is there.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_precompute_similar_ann_refresh.py (NEW), which does not resolve. That file was not read, and the checks did not need it.\n2. .un/skills/devsecops/config.json was read. It holds only test-group mappings and plays no part in this test's assertion form.\n3. Whether `ENGINE_PY` (tests/active/conftest.py:32) exists on disk was not checked, since that would mean running the test. If it is missing, the test fails at line 40 on the `ENGINE_PY.exists()` precondition instead of at the predicted line 80.\n\nBasis:\n- Anti-pattern pass (rules/shape.md): no entry matches.\n  - **doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep:** the test never reads a `.md` file.\n  - **hardcoded-spec-mirror:** `DESTRUCTIVE_FLAGS` (line 27) is only used as parametrized input. It is never compared for equality against a code constant.\n  - **tautological-assertion:** the expected values are the parameter and the exit code 2. The test works none of them out the way the code would.\n  - **echoed-literal:** `flag` is an input that line 80 expects back, but the job's own conflict check produces the error line in between. Removing that check makes line 80 fail.\n  - **absence-only-assertion:** the `absent` case's `assert not out_path.exists()` (line 85) comes after positive assertions in the same test (lines 74, 76, 79, 80). Test 2's `== []` (line 95) is paired with `assert out_path.exists()` (line 97).\n  - **single-value-pin:** each of the four flags must appear alone in the error, so a hard-coded conflict message fails three of the four.\n- Ladder pass (rules/shape.md `<ladder>`): the code under test is a CLI script, and the clauses are its exit code, its stderr and what it leaves on disk. That is rung 2 (subprocess) combined with rung 3 (file bytes and mtime), which is the highest rung that fits. It is not the anti-rung, and nothing is shifted to a lower rung, so `<downshift_rule>` does not apply.\n- Stub question: the test does not pass against these plausible wrong implementations:\n  - **Current code (flag unknown):** fails at line 80.\n  - **`--refresh-existing` accepted but no conflict check:** fails at line 74.\n  - **A fixed conflict message:** fails at line 80 for three of the four flags.\n  - **Conflict check placed after the output file is opened:** the job runs `connect_db` at engine/server/db/jobs/precompute-similar-ann.py:408, and `--recreate-out-db`/`--reset-only` delete the file at lines 383 and 396. The `absent` case fails at line 85 and the seeded case fails at line 83.\n  - **A job that rejects `--refresh-existing` in every case:** fails at line 95.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 13 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `--refresh-existing` with any of the four destructive flags \"exits 2\" | :74 (parametrized over all four at :61) | only some flags rejected; a refusal raised inside `main`'s try block (exit 1) instead of a usage error | CARRIED |\n| C1b | must_prove | \"naming the conflicting flag on stderr\" | :80 | a generic refusal naming no flag; naming the wrong flag; a message listing all four. On its own, :80 also passes the \"unrecognized arguments: --refresh-existing <flag>\" error that an unimplemented flag produces. :95 rules that case out. | CARRIED |\n| C2a | must_prove | seeded output \"keeps its bytes and mtime\" | :83 | the `--reset` DELETE or the `--recreate-out-db` unlink running before the refusal; a rewrite that leaves the same bytes but a new mtime | CARRIED |\n| C2b | must_prove | absent output \"stays absent\" | :85 | `connect_db`/`ensure_schema` creating `--out` before the refusal | CARRIED |\n| D1 | docstring | \"refuses ... before it touches `--out`\" (module :1) | :83, :85 | any write, or creation of the file, ahead of the argument check | CARRIED |\n| D2 | docstring | \"exits 2\" (module :3, fn :63) | :74 | a non-argparse failure exit | CARRIED |\n| D3 | docstring | \"on one argparse error line\" (module :3, fn :63) | :76 | a traceback or logged RuntimeError, which carries no `prog: error:` line; a refusal spread over several error lines | CARRIED |\n| D4 | docstring | error line names `--refresh-existing` (module :3) | :79 | a message naming only the destructive flag | CARRIED |\n| D5 | docstring | names \"that flag and no other of the four\" (module :3, fn :63 \"`flag` alone of the four\") | :80 | a blanket message listing every destructive flag; `--reset` mis-matched inside `--reset-only`, which the whole-token regex at :78 prevents | CARRIED |\n| D6 | docstring | \"over a seeded cache or none\" (module :3) | :60 with :74\u2013:80 run under both params | a refusal that only happens when the cache exists, or only when it is absent | CARRIED |\n| D7 | docstring | \"a seeded `--out` keeps its bytes and mtime\" (module :4, fn :63) | :82, :83 | deletion (:82); content or timestamp change (:83) | CARRIED |\n| D8 | docstring | \"an absent one is still absent\" (module :4, fn :63) | :85 | creation of `--out` on the refusal path | CARRIED |\n| D9 | docstring | `--refresh-existing --cpu` alone \"prints no argparse error\" (module :5, fn :89) | :95 | a parser that refuses `--refresh-existing` whatever it is paired with, or does not recognise it at all | CARRIED |\n| D10 | docstring | \"goes on to create `--out`\" (module :5, fn :89) | :97 | a refusal of the flag-alone case by non-argparse means before the output connect | CARRIED |\n| D11 | docstring | \"runs as a child process under the engine's pixi interpreter\" (module :7) | :40, :41 | an in-process import or a different interpreter | CARRIED |\n| D12 | docstring | \"on temporary sqlite files\" (module :7) | :33, :41, :65 | running against the repo's real `--db`/`--out` defaults | CARRIED |\n| D13 | docstring | `_seed_cache`: cache \"laid out by the job's own `--reset-only`\" holding a sentinel (:45) | :47 | a seeded cache the job did not create, so C2a would compare a foreign file | CARRIED |\n| N1 | name | \"refresh rejects each destructive flag\" | :74, :80 over :61 | rejecting a subset of `DESTRUCTIVE_FLAGS`, which matches C1's four exactly | CARRIED |\n| N2 | name | \"refresh alone is not refused\" | :95, :97 | a refresh flag refused unconditionally | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:72\n   `result = _run_job(tmp_path, out_path, \"--refresh-existing\", flag, \"--cpu\")`\n   Each run pairs `--refresh-existing` with one destructive flag and always adds `--cpu`. Two cases at the edge of the accepted input are untested:\n   - Two destructive flags at once, e.g. `--refresh-existing --reset --incremental`. :80 would then need a stated expectation for which flags the line names.\n   - A combination without an accelerator flag. The job's existing `--cpu/--gpu` check at precompute-similar-ann.py:335 can then fire first, and C1's \"naming the conflicting flag\" is not pinned for that order.\n   C1's four single-flag cases are fully covered, so this is not a Critical.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_precompute_similar_ann_refresh.py (NEW), which does not resolve. It was not read.\n2. The copy of engine/server/db/jobs/precompute-similar-ann.py I read has no `--refresh-existing` option (`main` at :275\u2013:336). I could not check the refusal path or the order of its argument checks against the code. I judged C1 and C2 on argparse's error-line convention and on where `main` first opens `--out` (:370\u2013:409).\n3. Only the first 40 of 202 lines of .un/skills/devsecops/config.json were read. It carries no behaviour the claims depend on.\n4. No `fixtures_path` was supplied. The test uses no pytest fixture beyond `tmp_path`. `ENGINE_PY` is imported from tests/active/conftest.py and resolved there (:32).",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`--refresh-existing` with any of the four destructive flags \"exits 2\"",
            "assertion": ":74 (parametrized over all four at :61)",
            "excludes": "only some flags rejected; a refusal raised inside `main`'s try block (exit 1) instead of a usage error",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"naming the conflicting flag on stderr\"",
            "assertion": ":80",
            "excludes": "a generic refusal naming no flag; naming the wrong flag; a message listing all four. On its own, :80 also passes the \"unrecognized arguments: --refresh-existing <flag>\" error that an unimplemented flag produces. :95 rules that case out.",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "seeded output \"keeps its bytes and mtime\"",
            "assertion": ":83",
            "excludes": "the `--reset` DELETE or the `--recreate-out-db` unlink running before the refusal; a rewrite that leaves the same bytes but a new mtime",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "absent output \"stays absent\"",
            "assertion": ":85",
            "excludes": "`connect_db`/`ensure_schema` creating `--out` before the refusal",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"refuses ... before it touches `--out`\" (module :1)",
            "assertion": ":83, :85",
            "excludes": "any write, or creation of the file, ahead of the argument check",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"exits 2\" (module :3, fn :63)",
            "assertion": ":74",
            "excludes": "a non-argparse failure exit",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"on one argparse error line\" (module :3, fn :63)",
            "assertion": ":76",
            "excludes": "a traceback or logged RuntimeError, which carries no `prog: error:` line; a refusal spread over several error lines",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "error line names `--refresh-existing` (module :3)",
            "assertion": ":79",
            "excludes": "a message naming only the destructive flag",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "names \"that flag and no other of the four\" (module :3, fn :63 \"`flag` alone of the four\")",
            "assertion": ":80",
            "excludes": "a blanket message listing every destructive flag; `--reset` mis-matched inside `--reset-only`, which the whole-token regex at :78 prevents",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"over a seeded cache or none\" (module :3)",
            "assertion": ":60 with :74\u2013:80 run under both params",
            "excludes": "a refusal that only happens when the cache exists, or only when it is absent",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"a seeded `--out` keeps its bytes and mtime\" (module :4, fn :63)",
            "assertion": ":82, :83",
            "excludes": "deletion (:82); content or timestamp change (:83)",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"an absent one is still absent\" (module :4, fn :63)",
            "assertion": ":85",
            "excludes": "creation of `--out` on the refusal path",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "`--refresh-existing --cpu` alone \"prints no argparse error\" (module :5, fn :89)",
            "assertion": ":95",
            "excludes": "a parser that refuses `--refresh-existing` whatever it is paired with, or does not recognise it at all",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"goes on to create `--out`\" (module :5, fn :89)",
            "assertion": ":97",
            "excludes": "a refusal of the flag-alone case by non-argparse means before the output connect",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"runs as a child process under the engine's pixi interpreter\" (module :7)",
            "assertion": ":40, :41",
            "excludes": "an in-process import or a different interpreter",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"on temporary sqlite files\" (module :7)",
            "assertion": ":33, :41, :65",
            "excludes": "running against the repo's real `--db`/`--out` defaults",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "`_seed_cache`: cache \"laid out by the job's own `--reset-only`\" holding a sentinel (:45)",
            "assertion": ":47",
            "excludes": "a seeded cache the job did not create, so C2a would compare a foreign file",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"refresh rejects each destructive flag\"",
            "assertion": ":74, :80 over :61",
            "excludes": "rejecting a subset of `DESTRUCTIVE_FLAGS`, which matches C1's four exactly",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"refresh alone is not refused\"",
            "assertion": ":95, :97",
            "excludes": "a refresh flag refused unconditionally",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_refresh_rewrites_exactly_cached_live_sources` fails at line 132 on `assert \"mode=refresh-existing\" in result.stderr`. The job has no `--refresh-existing` branch yet: it falls through to the full scan at precompute-similar-ann.py:465\u2013473 and never logs that token. Both `test_refresh_over_missing_or_empty_cache_is_a_no_op[missing]` and `[empty]` fail at line 165 on `_logged(result.stderr, r\"total sources=(\\d+)\") == (\"0\",)`, because the full scan logs `total sources=9`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_precompute_similar_ann_refresh.py, which does not resolve (no such file). It was not read. Nothing in this test imports from it, so the stub question was answered from precompute-similar-ann.py and the test alone.\n2. `fixtures_path` was not supplied. `ENGINE_PY` was resolved from tests/active/conftest.py:32. The module-scoped `source` fixture is defined in the test file itself.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (29 clauses: 10 must_prove, 15 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | each cached source still in `video_embeddings` is selected, and no other key is | :134 | a full scan (9), a left/outer join over the source, a join on `video_id` alone that picks up (v5, DOMAIN) (5) | CARRIED |\n| C1b | must_prove | \"that `build_query_batch` accepts\": the length-skipped cached v9 is selected but not processed | :135 | processing or counting v9 as rewritten (4/4), dropping v9 before selection (3/3) | CARRIED |\n| C1c | must_prove | \"is rewritten\": every one of v1-v3 is rewritten | :138 | skipping any of v1-v3, since its stamp stays `SENTINEL_AT` and the set then holds 2 values | CARRIED |\n| C1d | must_prove | \"the run's single new `computed_at`\" | :138, :140 | a stamp per source, a kept sentinel stamp, a stamp from outside the run window | CARRIED |\n| C1e | must_prove | \"only fresh ranked items\" | :142, :144, :145 | appending to the old items (ranks [1,1,2,3]), keeping `SENTINEL_TARGET`, a self-match, a target outside the live keys | CARRIED |\n| C1f | must_prove | nothing is selected when the cache is missing | :165, :166, :171, :172 (`missing` param) | a fallback to a full scan when there is no cache file (9, 8/9) | CARRIED |\n| C1g | must_prove | nothing is selected when the cache is schema-only | :165, :166, :171, :172 (`empty` param) | treating an empty `similarity_sources` as \"refresh everything\" | CARRIED |\n| C2a | must_prove | a stale source (gone1, gone2) is left as it was | :146, with :147 showing the snapshot is non-trivial | deleting or pruning cache rows whose source left `video_embeddings` | CARRIED |\n| C2b | must_prove | the empty-domain key (v5, \"\") is left as it was | :146 | a join on `video_id` alone that rewrites (v5, \"\") | CARRIED |\n| C2c | must_prove | the length-skipped source v9 is left as it was | :146 | rewriting v9 with an empty item list, or clearing its items | CARRIED |\n| C2d | must_prove | uncached embeddings gain no rows | :148, :149 | incremental or full-scan behaviour writing v4-v8, including (v5, DOMAIN) | CARRIED |\n| D1 | docstring | \"logs `mode=refresh-existing`\" | :132 | a run that never announces or enters the mode | CARRIED |\n| D2 | docstring | \"4 total sources\" | :134 | as C1a | CARRIED |\n| D3 | docstring | \"3/4 processed\" | :135 | as C1b | CARRIED |\n| D4 | docstring | \"v1-v3 carry one `computed_at` stamped during the run\" | :138, :140 | as C1d | CARRIED |\n| D5 | docstring | \"exactly three fresh items ranked 1..3\" | :142, :144 | more or fewer than 3 items, stale items kept, gaps or duplicates in the ranks | CARRIED |\n| D6 | docstring | \"on other live keys\" | :145 | a self-match, a dead or sentinel target | CARRIED |\n| D7 | docstring | \"the rest keep their snapshot rows and items\" | :146 | any change to gone1, gone2, (v5, \"\") or v9 | CARRIED |\n| D8 | docstring | \"the uncached v4-v8 gain no rows\" | :148 | as C2d | CARRIED |\n| D9 | docstring | \"7 sources remain\" | :149 | pruning stale rows, or adding uncached ones | CARRIED |\n| D10 | docstring | missing/schema-only: \"exits 0\" | :163 | refusing, or crashing, on a missing or empty cache | CARRIED |\n| D11 | docstring | missing/schema-only: \"0 total and 0/0 processed\" | :165, :166 | as C1f/C1g | CARRIED |\n| D12 | docstring | \"leaves both cache tables in place\" | :170 | deleting the out file, or never creating the schema over a missing cache | CARRIED |\n| D13 | docstring | \"writes no rows\" / \"present and empty\" | :171, :172 | any row written on the no-op path | CARRIED |\n| D14 | docstring | \"runs as a child process under the engine's pixi interpreter\" | :131, :163 via `_run_job` :76 | an in-process call that bypasses the CLI's argument handling | CARRIED |\n| D15 | docstring | \"a real FAISS index built by that interpreter\" | :70 | a skipped or faked index build; a missing faiss fails instead of skipping | CARRIED |\n| N1 | name | \"refresh rewrites\" | :138, :140, :142 | a refresh that leaves stamps or items unchanged | CARRIED |\n| N2 | name | \"exactly cached live sources\" | :134, :146, :148, :149 | selecting too many (uncached, stale) or too few | CARRIED |\n| N3 | name | \"over missing or empty cache\" | parametrize :152, branches :156-159 | covering only one of the two cache states | CARRIED |\n| N4 | name | \"is a no-op\" | :165, :166, :171, :172 | any selection or write on those caches | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:128\n   `result = _run_job(source, out_path, \"--refresh-existing\", \"--cpu\", \"--top-k\", \"3\")`\n   Every call to `--refresh-existing` in this file is on the success path. The job's expected failure, refusing the flag when it is combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` (precompute-similar-ann.py:341-344), is never run. Whether another phase's test covers it cannot be told from this file.\n2. whole-claim, context only (rules/testing.md): tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:142\n   `assert [rank for *_, rank in items] == [1, 2, 3], (key, items)  # C1`\n   C1e counts as carried because it rules out stale, appended and self items. Nothing checks that rank order follows score, so ranks assigned in reverse score order would still pass. This is recorded because \"ranked\" can be read more strongly than \"carries ranks 1..3\". It does not block.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_precompute_similar_ann_refresh.py, and that path does not exist. Its contents, and any overlap with this test or with the abnormal path in Recommendation 1, were not assessed.\n2. No `fixtures_path` was supplied, and no conftest.py covers tests/tmp/. The file imports `ENGINE_PY` straight from tests/active/conftest.py:32 and defines its own `source` fixture. Only that import was read from tests/active/conftest.py.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_refresh_rewrites_exactly_cached_live_sources` fails at line 132 on `assert \"mode=refresh-existing\" in result.stderr`. The job has no `--refresh-existing` branch yet: it falls through to the full scan at precompute-similar-ann.py:465\u2013473 and never logs that token. Both `test_refresh_over_missing_or_empty_cache_is_a_no_op[missing]` and `[empty]` fail at line 165 on `_logged(result.stderr, r\"total sources=(\\d+)\") == (\"0\",)`, because the full scan logs `total sources=9`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_precompute_similar_ann_refresh.py, which does not resolve (no such file). It was not read. Nothing in this test imports from it, so the stub question was answered from precompute-similar-ann.py and the test alone.\n2. `fixtures_path` was not supplied. `ENGINE_PY` was resolved from tests/active/conftest.py:32. The module-scoped `source` fixture is defined in the test file itself.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (29 clauses: 10 must_prove, 15 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | each cached source still in `video_embeddings` is selected, and no other key is | :134 | a full scan (9), a left/outer join over the source, a join on `video_id` alone that picks up (v5, DOMAIN) (5) | CARRIED |\n| C1b | must_prove | \"that `build_query_batch` accepts\": the length-skipped cached v9 is selected but not processed | :135 | processing or counting v9 as rewritten (4/4), dropping v9 before selection (3/3) | CARRIED |\n| C1c | must_prove | \"is rewritten\": every one of v1-v3 is rewritten | :138 | skipping any of v1-v3, since its stamp stays `SENTINEL_AT` and the set then holds 2 values | CARRIED |\n| C1d | must_prove | \"the run's single new `computed_at`\" | :138, :140 | a stamp per source, a kept sentinel stamp, a stamp from outside the run window | CARRIED |\n| C1e | must_prove | \"only fresh ranked items\" | :142, :144, :145 | appending to the old items (ranks [1,1,2,3]), keeping `SENTINEL_TARGET`, a self-match, a target outside the live keys | CARRIED |\n| C1f | must_prove | nothing is selected when the cache is missing | :165, :166, :171, :172 (`missing` param) | a fallback to a full scan when there is no cache file (9, 8/9) | CARRIED |\n| C1g | must_prove | nothing is selected when the cache is schema-only | :165, :166, :171, :172 (`empty` param) | treating an empty `similarity_sources` as \"refresh everything\" | CARRIED |\n| C2a | must_prove | a stale source (gone1, gone2) is left as it was | :146, with :147 showing the snapshot is non-trivial | deleting or pruning cache rows whose source left `video_embeddings` | CARRIED |\n| C2b | must_prove | the empty-domain key (v5, \"\") is left as it was | :146 | a join on `video_id` alone that rewrites (v5, \"\") | CARRIED |\n| C2c | must_prove | the length-skipped source v9 is left as it was | :146 | rewriting v9 with an empty item list, or clearing its items | CARRIED |\n| C2d | must_prove | uncached embeddings gain no rows | :148, :149 | incremental or full-scan behaviour writing v4-v8, including (v5, DOMAIN) | CARRIED |\n| D1 | docstring | \"logs `mode=refresh-existing`\" | :132 | a run that never announces or enters the mode | CARRIED |\n| D2 | docstring | \"4 total sources\" | :134 | as C1a | CARRIED |\n| D3 | docstring | \"3/4 processed\" | :135 | as C1b | CARRIED |\n| D4 | docstring | \"v1-v3 carry one `computed_at` stamped during the run\" | :138, :140 | as C1d | CARRIED |\n| D5 | docstring | \"exactly three fresh items ranked 1..3\" | :142, :144 | more or fewer than 3 items, stale items kept, gaps or duplicates in the ranks | CARRIED |\n| D6 | docstring | \"on other live keys\" | :145 | a self-match, a dead or sentinel target | CARRIED |\n| D7 | docstring | \"the rest keep their snapshot rows and items\" | :146 | any change to gone1, gone2, (v5, \"\") or v9 | CARRIED |\n| D8 | docstring | \"the uncached v4-v8 gain no rows\" | :148 | as C2d | CARRIED |\n| D9 | docstring | \"7 sources remain\" | :149 | pruning stale rows, or adding uncached ones | CARRIED |\n| D10 | docstring | missing/schema-only: \"exits 0\" | :163 | refusing, or crashing, on a missing or empty cache | CARRIED |\n| D11 | docstring | missing/schema-only: \"0 total and 0/0 processed\" | :165, :166 | as C1f/C1g | CARRIED |\n| D12 | docstring | \"leaves both cache tables in place\" | :170 | deleting the out file, or never creating the schema over a missing cache | CARRIED |\n| D13 | docstring | \"writes no rows\" / \"present and empty\" | :171, :172 | any row written on the no-op path | CARRIED |\n| D14 | docstring | \"runs as a child process under the engine's pixi interpreter\" | :131, :163 via `_run_job` :76 | an in-process call that bypasses the CLI's argument handling | CARRIED |\n| D15 | docstring | \"a real FAISS index built by that interpreter\" | :70 | a skipped or faked index build; a missing faiss fails instead of skipping | CARRIED |\n| N1 | name | \"refresh rewrites\" | :138, :140, :142 | a refresh that leaves stamps or items unchanged | CARRIED |\n| N2 | name | \"exactly cached live sources\" | :134, :146, :148, :149 | selecting too many (uncached, stale) or too few | CARRIED |\n| N3 | name | \"over missing or empty cache\" | parametrize :152, branches :156-159 | covering only one of the two cache states | CARRIED |\n| N4 | name | \"is a no-op\" | :165, :166, :171, :172 | any selection or write on those caches | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:128\n   `result = _run_job(source, out_path, \"--refresh-existing\", \"--cpu\", \"--top-k\", \"3\")`\n   Every call to `--refresh-existing` in this file is on the success path. The job's expected failure, refusing the flag when it is combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` (precompute-similar-ann.py:341-344), is never run. Whether another phase's test covers it cannot be told from this file.\n2. whole-claim, context only (rules/testing.md): tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:142\n   `assert [rank for *_, rank in items] == [1, 2, 3], (key, items)  # C1`\n   C1e counts as carried because it rules out stale, appended and self items. Nothing checks that rank order follows score, so ranks assigned in reverse score order would still pass. This is recorded because \"ranked\" can be read more strongly than \"carries ranks 1..3\". It does not block.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_precompute_similar_ann_refresh.py, and that path does not exist. Its contents, and any overlap with this test or with the abnormal path in Recommendation 1, were not assessed.\n2. No `fixtures_path` was supplied, and no conftest.py covers tests/tmp/. The file imports `ENGINE_PY` straight from tests/active/conftest.py:32 and defines its own `source` fixture. Only that import was read from tests/active/conftest.py.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "each cached source still in `video_embeddings` is selected, and no other key is",
            "assertion": ":134",
            "excludes": "a full scan (9), a left/outer join over the source, a join on `video_id` alone that picks up (v5, DOMAIN) (5)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"that `build_query_batch` accepts\": the length-skipped cached v9 is selected but not processed",
            "assertion": ":135",
            "excludes": "processing or counting v9 as rewritten (4/4), dropping v9 before selection (3/3)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"is rewritten\": every one of v1-v3 is rewritten",
            "assertion": ":138",
            "excludes": "skipping any of v1-v3, since its stamp stays `SENTINEL_AT` and the set then holds 2 values",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"the run's single new `computed_at`\"",
            "assertion": ":138, :140",
            "excludes": "a stamp per source, a kept sentinel stamp, a stamp from outside the run window",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"only fresh ranked items\"",
            "assertion": ":142, :144, :145",
            "excludes": "appending to the old items (ranks [1,1,2,3]), keeping `SENTINEL_TARGET`, a self-match, a target outside the live keys",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "nothing is selected when the cache is missing",
            "assertion": ":165, :166, :171, :172 (`missing` param)",
            "excludes": "a fallback to a full scan when there is no cache file (9, 8/9)",
            "status": "CARRIED"
          },
          {
            "id": "C1g",
            "source": "must_prove",
            "clause": "nothing is selected when the cache is schema-only",
            "assertion": ":165, :166, :171, :172 (`empty` param)",
            "excludes": "treating an empty `similarity_sources` as \"refresh everything\"",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a stale source (gone1, gone2) is left as it was",
            "assertion": ":146, with :147 showing the snapshot is non-trivial",
            "excludes": "deleting or pruning cache rows whose source left `video_embeddings`",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "the empty-domain key (v5, \"\") is left as it was",
            "assertion": ":146",
            "excludes": "a join on `video_id` alone that rewrites (v5, \"\")",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "the length-skipped source v9 is left as it was",
            "assertion": ":146",
            "excludes": "rewriting v9 with an empty item list, or clearing its items",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "uncached embeddings gain no rows",
            "assertion": ":148, :149",
            "excludes": "incremental or full-scan behaviour writing v4-v8, including (v5, DOMAIN)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"logs `mode=refresh-existing`\"",
            "assertion": ":132",
            "excludes": "a run that never announces or enters the mode",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"4 total sources\"",
            "assertion": ":134",
            "excludes": "as C1a",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"3/4 processed\"",
            "assertion": ":135",
            "excludes": "as C1b",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"v1-v3 carry one `computed_at` stamped during the run\"",
            "assertion": ":138, :140",
            "excludes": "as C1d",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"exactly three fresh items ranked 1..3\"",
            "assertion": ":142, :144",
            "excludes": "more or fewer than 3 items, stale items kept, gaps or duplicates in the ranks",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"on other live keys\"",
            "assertion": ":145",
            "excludes": "a self-match, a dead or sentinel target",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the rest keep their snapshot rows and items\"",
            "assertion": ":146",
            "excludes": "any change to gone1, gone2, (v5, \"\") or v9",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"the uncached v4-v8 gain no rows\"",
            "assertion": ":148",
            "excludes": "as C2d",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"7 sources remain\"",
            "assertion": ":149",
            "excludes": "pruning stale rows, or adding uncached ones",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "missing/schema-only: \"exits 0\"",
            "assertion": ":163",
            "excludes": "refusing, or crashing, on a missing or empty cache",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "missing/schema-only: \"0 total and 0/0 processed\"",
            "assertion": ":165, :166",
            "excludes": "as C1f/C1g",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"leaves both cache tables in place\"",
            "assertion": ":170",
            "excludes": "deleting the out file, or never creating the schema over a missing cache",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"writes no rows\" / \"present and empty\"",
            "assertion": ":171, :172",
            "excludes": "any row written on the no-op path",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"runs as a child process under the engine's pixi interpreter\"",
            "assertion": ":131, :163 via `_run_job` :76",
            "excludes": "an in-process call that bypasses the CLI's argument handling",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"a real FAISS index built by that interpreter\"",
            "assertion": ":70",
            "excludes": "a skipped or faked index build; a missing faiss fails instead of skipping",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"refresh rewrites\"",
            "assertion": ":138, :140, :142",
            "excludes": "a refresh that leaves stamps or items unchanged",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"exactly cached live sources\"",
            "assertion": ":134, :146, :148, :149",
            "excludes": "selecting too many (uncached, stale) or too few",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"over missing or empty cache\"",
            "assertion": "parametrize :152, branches :156-159",
            "excludes": "covering only one of the two cache states",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"is a no-op\"",
            "assertion": ":165, :166, :171, :172",
            "excludes": "any selection or write on those caches",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:42 and :50\n   cmd = updater.similarity_precompute_cmd(python_bin=\"python3\", use_gpu=use_gpu, **_paths(tmp_path))\n   `python_bin` only ever takes the value \"python3\" in this file. A builder that writes \"python3\" as a fixed value instead of passing the argument through would still pass. This is not Critical. The C1 and C2 clauses are about the flag swap and the accelerator suffix, and those are covered: `use_gpu` is tested at two values that give different outputs, and all four paths come from each test's own `tmp_path` and differ from each other. Fix: add a second `python_bin` value that differs from \"python3\" and from `sys.executable` (the `--python-bin` default at updater-worker.py:177).\n\nPREDICTED FAILURE\nAll three tests fail. `test_updater_builds_refresh_command[gpu]` and `[cpu]` fail at line 42, and `test_cpu_fallback_keeps_refresh` fails at line 50, each with AttributeError: the loaded module has no `similarity_precompute_cmd` yet, because updater-worker.py:1114-1134 still builds the argv inline in `main`. `test_updater_main_uses_builder` fails on the assertion at line 64, `assert \"similarity_precompute_cmd\" in called`. If execution got past that line, line 68 would also fail on the `--recreate-out-db` literal at updater-worker.py:1129.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_updater_precompute_cmd.py, but that path doesn't exist, so it was not read.\n2. `code_under_test` lists .un/skills/devsecops/config.json. It was not read because the test never references it.\n3. `similarity_precompute_cmd` isn't defined anywhere in engine/server/db/jobs/updater-worker.py yet. So the stub question was answered from the assertion form alone. Lines 44 and 54 compare the whole argv to a fixed literal list, and line 45 adds a check that `--recreate-out-db` is absent. Lines 64 and 68 check the call site, and line 67 (`--gpu-device` in constants) checks the module's constants are actually scanned. With those assertions, a stub, a builder that returns the old argv, or a `main` left unchanged all fail.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (18 clauses: 2 must_prove, 13 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"for both `use_gpu` values\" | :39 + :44 | a builder right for only one accelerator. The parametrize runs both, and each checks the exact suffix | CARRIED |\n| C1b | must_prove | returns \"the previous argv\", every token kept | :44 | a dropped, reordered or changed token, or two path kwargs swapped (the four `_paths` values at :36 all differ). The literal matches the old inline argv at updater-worker.py:1114-1134 | CARRIED |\n| C1c | must_prove | `--refresh-existing` in the slot `--recreate-out-db` held | :44 | the flag missing, appended after the suffix, or put anywhere other than just before the suffix | CARRIED |\n| C1d | must_prove | `--recreate-out-db` replaced, not kept alongside | :44, :45 | a builder that adds `--refresh-existing` and keeps `--recreate-out-db`. The exact comparison already rules this out and :45 repeats it | CARRIED |\n| C2a | must_prove | `_to_cpu_cmd`(GPU argv) gives the CPU argv | :50, :54 | GPU flags left in, `--cpu` missing or doubled, or any other token changed. The expected list at :54 is the same as the `cpu` case at :44 | CARRIED |\n| C2b | must_prove | \"keeping `--refresh-existing`\" | :54 | a GPU argv whose layout makes the `--gpu-device` skip (updater-worker.py:370-372) drop `--refresh-existing` | CARRIED |\n| D1 | docstring | module: \"builds its similarity precompute argv with `--refresh-existing` where it passed `--recreate-out-db`\" | :44 | same as C1c. Only the builder is checked. Nothing checks the arguments `main` passes to it (see Recommendation 1) | CARRIED |\n| D2 | docstring | module: \"its CPU retry keeps that flag\" | :52, :54 | a GPU argv without `--gpu`, which the retry gate at updater-worker.py:387 would skip, and a retry that drops the flag | CARRIED |\n| D3 | docstring | module: \"token for token, the old precompute argv\" | :44 | same as C1b | CARRIED |\n| D4 | docstring | module: \"ending in `--gpu --gpu-device 0` or `--cpu`\" | :44 | a wrong suffix, or the suffix in the wrong position | CARRIED |\n| D5 | docstring | module: \"and without `--recreate-out-db`\" | :45 | keeping the old flag next to the new one | CARRIED |\n| D6 | docstring | module: \"`_to_cpu_cmd` turns the GPU argv into exactly the CPU argv, `--refresh-existing` included\" | :54 | same as C2a/C2b | CARRIED |\n| D7 | docstring | module: \"`main` calls `similarity_precompute_cmd`\" | :64 | a `main` that keeps building the argv inline and never calls the builder | CARRIED |\n| D8 | docstring | module: \"no `--recreate-out-db` literal is left anywhere in the module\" | :67, :68 | a leftover literal on some other code path. :67 shows the scan really reads the module's string constants | CARRIED |\n| D9 | docstring | test_updater_builds_refresh_command: \"old literal token for token \u2026 accelerator suffix for `use_gpu`\" | :44 | same as C1a-C1c | CARRIED |\n| D10 | docstring | test_cpu_fallback_keeps_refresh: \"exactly the CPU argv, `--refresh-existing` still in its slot\" | :54 | same as C2a/C2b | CARRIED |\n| D11 | docstring | test_updater_main_uses_builder: \"`main` calls `similarity_precompute_cmd`\" | :64 | same as D7 | CARRIED |\n| D12 | docstring | test_updater_main_uses_builder: \"the module holds no `--recreate-out-db` string literal\" | :68 | same as D8 | CARRIED |\n| D13 | docstring | module: \"loaded in-process from its file\" | :22-31 | a fixture that imports some other copy of the module. The module-scoped fixture loads exactly updater-worker.py | CARRIED |\n| N1 | name | \"updater builds refresh command\" | :44 | a builder that does not emit `--refresh-existing` | CARRIED |\n| N2 | name | \"cpu fallback keeps refresh\" | :52, :54 | a retry argv without `--refresh-existing`, or a GPU argv the fallback would never retry | CARRIED |\n| N3 | name | \"updater main uses builder\" | :64 | a `main` that never calls the builder | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:64\n   `assert \"similarity_precompute_cmd\" in called, sorted(called)`\n   D1 says the module \"builds its similarity precompute argv\" with the new flag. D7 is carried: `main` calls the builder. But no assertion checks what `main` passes in or what it hands to `run_with_cpu_fallback`. A `main` that calls the builder with `index_path` and `similarity_db` swapped, or that throws away the result, still passes. The claim is outside `must_prove`, so this is not a Critical. Either narrow the module docstring's first sentence to the builder, or accept that the call-site check carries it only partly.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:36\n   Every argv expected at :44 and :54 is built with f-strings from `tmp_path`, while `main` builds paths with `.as_posix()` (updater-worker.py:1116-1122). The two only agree on POSIX paths. Nothing tests a path with spaces or other unusual characters. No rule requires those inputs for a list-form argv, so this is advisory only.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_updater_precompute_cmd.py (NEW), and that path does not exist.\n2. `similarity_precompute_cmd` is not defined in engine/server/db/jobs/updater-worker.py yet. `main` still builds the argv inline at :1114-1134, including `\"--recreate-out-db\"` at :1129. I judged the builder's signature (`python_bin`, `use_gpu`, `script_path`, `db_path`, `index_path`, `out_path`) from the test alone. I checked the expected argv at :44 against the old inline literal.\n3. I did not read .un/skills/devsecops/config.json. The test does not use it, and it has no bearing on the claims.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:42 and :50\n   cmd = updater.similarity_precompute_cmd(python_bin=\"python3\", use_gpu=use_gpu, **_paths(tmp_path))\n   `python_bin` only ever takes the value \"python3\" in this file. A builder that writes \"python3\" as a fixed value instead of passing the argument through would still pass. This is not Critical. The C1 and C2 clauses are about the flag swap and the accelerator suffix, and those are covered: `use_gpu` is tested at two values that give different outputs, and all four paths come from each test's own `tmp_path` and differ from each other. Fix: add a second `python_bin` value that differs from \"python3\" and from `sys.executable` (the `--python-bin` default at updater-worker.py:177).\n\nPREDICTED FAILURE\nAll three tests fail. `test_updater_builds_refresh_command[gpu]` and `[cpu]` fail at line 42, and `test_cpu_fallback_keeps_refresh` fails at line 50, each with AttributeError: the loaded module has no `similarity_precompute_cmd` yet, because updater-worker.py:1114-1134 still builds the argv inline in `main`. `test_updater_main_uses_builder` fails on the assertion at line 64, `assert \"similarity_precompute_cmd\" in called`. If execution got past that line, line 68 would also fail on the `--recreate-out-db` literal at updater-worker.py:1129.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_updater_precompute_cmd.py, but that path doesn't exist, so it was not read.\n2. `code_under_test` lists .un/skills/devsecops/config.json. It was not read because the test never references it.\n3. `similarity_precompute_cmd` isn't defined anywhere in engine/server/db/jobs/updater-worker.py yet. So the stub question was answered from the assertion form alone. Lines 44 and 54 compare the whole argv to a fixed literal list, and line 45 adds a check that `--recreate-out-db` is absent. Lines 64 and 68 check the call site, and line 67 (`--gpu-device` in constants) checks the module's constants are actually scanned. With those assertions, a stub, a builder that returns the old argv, or a `main` left unchanged all fail.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (18 clauses: 2 must_prove, 13 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"for both `use_gpu` values\" | :39 + :44 | a builder right for only one accelerator. The parametrize runs both, and each checks the exact suffix | CARRIED |\n| C1b | must_prove | returns \"the previous argv\", every token kept | :44 | a dropped, reordered or changed token, or two path kwargs swapped (the four `_paths` values at :36 all differ). The literal matches the old inline argv at updater-worker.py:1114-1134 | CARRIED |\n| C1c | must_prove | `--refresh-existing` in the slot `--recreate-out-db` held | :44 | the flag missing, appended after the suffix, or put anywhere other than just before the suffix | CARRIED |\n| C1d | must_prove | `--recreate-out-db` replaced, not kept alongside | :44, :45 | a builder that adds `--refresh-existing` and keeps `--recreate-out-db`. The exact comparison already rules this out and :45 repeats it | CARRIED |\n| C2a | must_prove | `_to_cpu_cmd`(GPU argv) gives the CPU argv | :50, :54 | GPU flags left in, `--cpu` missing or doubled, or any other token changed. The expected list at :54 is the same as the `cpu` case at :44 | CARRIED |\n| C2b | must_prove | \"keeping `--refresh-existing`\" | :54 | a GPU argv whose layout makes the `--gpu-device` skip (updater-worker.py:370-372) drop `--refresh-existing` | CARRIED |\n| D1 | docstring | module: \"builds its similarity precompute argv with `--refresh-existing` where it passed `--recreate-out-db`\" | :44 | same as C1c. Only the builder is checked. Nothing checks the arguments `main` passes to it (see Recommendation 1) | CARRIED |\n| D2 | docstring | module: \"its CPU retry keeps that flag\" | :52, :54 | a GPU argv without `--gpu`, which the retry gate at updater-worker.py:387 would skip, and a retry that drops the flag | CARRIED |\n| D3 | docstring | module: \"token for token, the old precompute argv\" | :44 | same as C1b | CARRIED |\n| D4 | docstring | module: \"ending in `--gpu --gpu-device 0` or `--cpu`\" | :44 | a wrong suffix, or the suffix in the wrong position | CARRIED |\n| D5 | docstring | module: \"and without `--recreate-out-db`\" | :45 | keeping the old flag next to the new one | CARRIED |\n| D6 | docstring | module: \"`_to_cpu_cmd` turns the GPU argv into exactly the CPU argv, `--refresh-existing` included\" | :54 | same as C2a/C2b | CARRIED |\n| D7 | docstring | module: \"`main` calls `similarity_precompute_cmd`\" | :64 | a `main` that keeps building the argv inline and never calls the builder | CARRIED |\n| D8 | docstring | module: \"no `--recreate-out-db` literal is left anywhere in the module\" | :67, :68 | a leftover literal on some other code path. :67 shows the scan really reads the module's string constants | CARRIED |\n| D9 | docstring | test_updater_builds_refresh_command: \"old literal token for token \u2026 accelerator suffix for `use_gpu`\" | :44 | same as C1a-C1c | CARRIED |\n| D10 | docstring | test_cpu_fallback_keeps_refresh: \"exactly the CPU argv, `--refresh-existing` still in its slot\" | :54 | same as C2a/C2b | CARRIED |\n| D11 | docstring | test_updater_main_uses_builder: \"`main` calls `similarity_precompute_cmd`\" | :64 | same as D7 | CARRIED |\n| D12 | docstring | test_updater_main_uses_builder: \"the module holds no `--recreate-out-db` string literal\" | :68 | same as D8 | CARRIED |\n| D13 | docstring | module: \"loaded in-process from its file\" | :22-31 | a fixture that imports some other copy of the module. The module-scoped fixture loads exactly updater-worker.py | CARRIED |\n| N1 | name | \"updater builds refresh command\" | :44 | a builder that does not emit `--refresh-existing` | CARRIED |\n| N2 | name | \"cpu fallback keeps refresh\" | :52, :54 | a retry argv without `--refresh-existing`, or a GPU argv the fallback would never retry | CARRIED |\n| N3 | name | \"updater main uses builder\" | :64 | a `main` that never calls the builder | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:64\n   `assert \"similarity_precompute_cmd\" in called, sorted(called)`\n   D1 says the module \"builds its similarity precompute argv\" with the new flag. D7 is carried: `main` calls the builder. But no assertion checks what `main` passes in or what it hands to `run_with_cpu_fallback`. A `main` that calls the builder with `index_path` and `similarity_db` swapped, or that throws away the result, still passes. The claim is outside `must_prove`, so this is not a Critical. Either narrow the module docstring's first sentence to the builder, or accept that the call-site check carries it only partly.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:36\n   Every argv expected at :44 and :54 is built with f-strings from `tmp_path`, while `main` builds paths with `.as_posix()` (updater-worker.py:1116-1122). The two only agree on POSIX paths. Nothing tests a path with spaces or other unusual characters. No rule requires those inputs for a list-form argv, so this is advisory only.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_updater_precompute_cmd.py (NEW), and that path does not exist.\n2. `similarity_precompute_cmd` is not defined in engine/server/db/jobs/updater-worker.py yet. `main` still builds the argv inline at :1114-1134, including `\"--recreate-out-db\"` at :1129. I judged the builder's signature (`python_bin`, `use_gpu`, `script_path`, `db_path`, `index_path`, `out_path`) from the test alone. I checked the expected argv at :44 against the old inline literal.\n3. I did not read .un/skills/devsecops/config.json. The test does not use it, and it has no bearing on the claims.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"for both `use_gpu` values\"",
            "assertion": ":39 + :44",
            "excludes": "a builder right for only one accelerator. The parametrize runs both, and each checks the exact suffix",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "returns \"the previous argv\", every token kept",
            "assertion": ":44",
            "excludes": "a dropped, reordered or changed token, or two path kwargs swapped (the four `_paths` values at :36 all differ). The literal matches the old inline argv at updater-worker.py:1114-1134",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "`--refresh-existing` in the slot `--recreate-out-db` held",
            "assertion": ":44",
            "excludes": "the flag missing, appended after the suffix, or put anywhere other than just before the suffix",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "`--recreate-out-db` replaced, not kept alongside",
            "assertion": ":44, :45",
            "excludes": "a builder that adds `--refresh-existing` and keeps `--recreate-out-db`. The exact comparison already rules this out and :45 repeats it",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "`_to_cpu_cmd`(GPU argv) gives the CPU argv",
            "assertion": ":50, :54",
            "excludes": "GPU flags left in, `--cpu` missing or doubled, or any other token changed. The expected list at :54 is the same as the `cpu` case at :44",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"keeping `--refresh-existing`\"",
            "assertion": ":54",
            "excludes": "a GPU argv whose layout makes the `--gpu-device` skip (updater-worker.py:370-372) drop `--refresh-existing`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "module: \"builds its similarity precompute argv with `--refresh-existing` where it passed `--recreate-out-db`\"",
            "assertion": ":44",
            "excludes": "same as C1c. Only the builder is checked. Nothing checks the arguments `main` passes to it (see Recommendation 1)",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "module: \"its CPU retry keeps that flag\"",
            "assertion": ":52, :54",
            "excludes": "a GPU argv without `--gpu`, which the retry gate at updater-worker.py:387 would skip, and a retry that drops the flag",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "module: \"token for token, the old precompute argv\"",
            "assertion": ":44",
            "excludes": "same as C1b",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "module: \"ending in `--gpu --gpu-device 0` or `--cpu`\"",
            "assertion": ":44",
            "excludes": "a wrong suffix, or the suffix in the wrong position",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "module: \"and without `--recreate-out-db`\"",
            "assertion": ":45",
            "excludes": "keeping the old flag next to the new one",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "module: \"`_to_cpu_cmd` turns the GPU argv into exactly the CPU argv, `--refresh-existing` included\"",
            "assertion": ":54",
            "excludes": "same as C2a/C2b",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "module: \"`main` calls `similarity_precompute_cmd`\"",
            "assertion": ":64",
            "excludes": "a `main` that keeps building the argv inline and never calls the builder",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "module: \"no `--recreate-out-db` literal is left anywhere in the module\"",
            "assertion": ":67, :68",
            "excludes": "a leftover literal on some other code path. :67 shows the scan really reads the module's string constants",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "test_updater_builds_refresh_command: \"old literal token for token \u2026 accelerator suffix for `use_gpu`\"",
            "assertion": ":44",
            "excludes": "same as C1a-C1c",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "test_cpu_fallback_keeps_refresh: \"exactly the CPU argv, `--refresh-existing` still in its slot\"",
            "assertion": ":54",
            "excludes": "same as C2a/C2b",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "test_updater_main_uses_builder: \"`main` calls `similarity_precompute_cmd`\"",
            "assertion": ":64",
            "excludes": "same as D7",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "test_updater_main_uses_builder: \"the module holds no `--recreate-out-db` string literal\"",
            "assertion": ":68",
            "excludes": "same as D8",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "module: \"loaded in-process from its file\"",
            "assertion": ":22-31",
            "excludes": "a fixture that imports some other copy of the module. The module-scoped fixture loads exactly updater-worker.py",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"updater builds refresh command\"",
            "assertion": ":44",
            "excludes": "a builder that does not emit `--refresh-existing`",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"cpu fallback keeps refresh\"",
            "assertion": ":52, :54",
            "excludes": "a retry argv without `--refresh-existing`, or a GPU argv the fallback would never retry",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"updater main uses builder\"",
            "assertion": ":64",
            "excludes": "a `main` that never calls the builder",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nengine/server/db/jobs/precompute-similar-ann.py: the selection branch now checks the already-computed `mode` (`mode != \"full\"`, then `mode == \"refresh-existing\"`) and no longer re-tests `args.incremental or args.refresh_existing` and `args.refresh_existing`, so the logged mode and the SQL that runs come from the same value.\nengine/server/db/jobs/precompute-similar-ann.py: rewrote the attach-block comment, which still said \"Incremental mode\" although the block now serves both incremental and refresh-existing. It is now one line covering both modes, where it used to be wrapped over three.\n</refactors>\n\n<left_out>\nengine/server/db/jobs/updater-worker.py: nothing to refactor. `similarity_precompute_cmd` already matches the keyword-only style of `systemctl_cmd`, and `main` just calls it.\nengine/server/db/jobs/precompute-similar-ann.py: left the `--recreate-out-db` and `--reset-only` unlink blocks alone. They are near-duplicates, but they were there before this build and merging them is outside this build's scope.\nengine/server/db/jobs/precompute-similar-ann.py: left the one-line conflict-check comprehension as it is. It follows the no-softwrap rule and is checked before any output-file side effect; moving it into a helper would add indirection for a single caller.\nNot run: I did not run the checkpoints myself (the workflow's run is the one that counts). The edit only swaps equivalent conditions, because `mode` is derived from exactly `args.refresh_existing` / `args.incremental` a few lines above.\nProcess gap, not a refactor: `tests/active/test_precompute_similar_ann_refresh.py` and `tests/active/test_updater_precompute_cmd.py` do not exist, although `config.json` already has test groups for both. The gating tests are still only in `tests/tmp/test_25_similarity_precompute_existing_sources_phase{1,2,3}.py`, so the promotion step still has to create them. The step's \"{rat_tail_rules}\" placeholder was also never filled in, so I measured the pass against the role's rules; no simplification in this build needed a `rat-tail:` comment.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nThe three phases fit together without duplicated logic; the only cleanup was making the selection branch use the logged `mode` and fixing a comment that dated from before refresh-existing, and nothing needed new behaviour.\n</observation>"
}
```
dev-flow:state -->

## Entries from earlier runs of this build

## 2026-09-30 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 33 test groups (32 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.0s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-30 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

engine/server/db/jobs/docs/UPDATER_WORKER.md step 10 says the updater runs `precompute-similar-ann.py --incremental`, but `updater-worker.py` actually passes `--recreate-out-db`. The build resolves this by correcting the doc to the new `--refresh-existing` mode.
The issue's validation "Updater stage time drops against the full-rebuild baseline" vs the live cache's state: `similarity-cache.db` is built full by `--recreate-out-db`, so cached ∩ embeddings is nearly all of prod and the drop will be small at first. The operator accepted this and made it a measurement, not a gate.
docs/project/issues/plan.md row 4b (issue 24) says to reuse `swap_readonly_connection` for the reopen, while issue 24's triage says the reopen does not use it. This is not in this build's scope and is noted only for issue 24.

## 2026-09-30 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-09-30 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


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


### docs_checklist

<doc path="engine/server/db/jobs/docs/UPDATER_WORKER.md">
Rewrite Execution Order step 10 (line 53, which today wrongly says `--incremental`) to `precompute-similar-ann.py --refresh-existing`. It rewrites only sources already in `similarity_sources` that are still in `video_embeddings`; new videos are cached lazily by the Engine on first request; stale cached sources are left in place. Optionally add that a missing or empty cache stays empty after an updater run, and that the initial full build is `DATA_BUILD.md` §5.
</doc>
<doc path="DATA_BUILD.md">
§5 (lines 252-266): add a short flag note after the example. It covers `--incremental`, `--recreate-out-db`, `--reset`/`--reset-only` and the new `--refresh-existing` (cached ∩ embeddings; other rows untouched; cannot be combined with the other four, exits 2). The example and the `--top-k` paragraph are unchanged. Optional one-word fix: line 30 points at `engine/server/db/jobs/UPDATER_WORKER.md`, but the file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`.
</doc>
<doc path="engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md">
No change per the plan. Line 16 ("incremental similarity precompute") was already inaccurate and is left alone unless the operator asks. The smoke run now yields an empty schema-only similarity cache.
</doc>
<doc path="docs/project/issues/24-similarity-cache-shadow-swap.md">
Optional: line 15 still says the shadow build runs `precompute-similar-ann.py --incremental`. Update it, or add a comment, to say `--refresh-existing` now that 25 is delivered, so lane 4b wires the right mode.
</doc>
<doc path="docs/project/issues/25-similarity-precompute-existing-sources.md">
On delivery: `Status:` becomes `complete` and the file moves to `docs/project/issues/archive/`. Comment that the stage-time validation became a measurement, not a gate.
</doc>

### highest_risk

tests/active/test_precompute_similar_ann_refresh.py: the plan says to run the job via `sys.executable` like test_precompute_random_rowids.py, but the suite runs under the root pixi env (Python 3.14, harness deps only, no numpy or faiss per pyproject.toml and last_test_validation.json). The job would die at `import numpy` and the test could not build a FAISS index. It must use conftest's ENGINE_PY for the job and for index construction, as test_video.py and test_similar.py do. The faiss MMAP read flag on a flat IndexIDMap is also unverified.
engine/server/db/jobs/updater-worker.py (builder + main call site): `main()` already binds a local `precompute_cmd`. Naming the new module-level builder the same makes the name local for all of `main` and raises UnboundLocalError only at the precompute stage, after the merge and ANN rebuild. The switch also means a missing or empty cache is never fully rebuilt by the updater again, while the run reports success.
engine/server/db/jobs/precompute-similar-ann.py (conflict check + shared selection branch): the check must sit before the cpu/gpu check and before any connect or unlink, or the byte-identical guarantee breaks. The shared ATTACH/materialise/DETACH refactor must leave `--incremental` identical, and no existing test covers `--incremental`.

## 2026-09-30 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I checked the inventory against the files and every entry holds. `precompute-similar-ann.py` matches the line numbers the inventory cites: parse_args at 334, the cpu/gpu check at 335-336, the first file access at 370, the incremental branch at 433-463, and the `total sources` log at 464. `updater-worker.py` matches too: `_to_cpu_cmd` at 361-377, `systemctl_cmd` at 401-412, and the inline `precompute_cmd` at 1114-1134 with `--recreate-out-db` at 1129. The docs match: UPDATER_WORKER.md:53 still says `--incremental`, and DATA_BUILD.md:30 still has the stale path. `similarity_cache.py:110` stores `or ""`, and the smoke test's check at 750 only tests that the file exists. `video_embeddings` has `PRIMARY KEY (video_id, instance_domain)` (`build-video-embeddings.py:73`), so the INNER JOIN cannot produce duplicate rowids from either side. That is slightly stronger than the inventory said. One problem remains open: the settled plan tells the refresh test to run the job the way `test_precompute_random_rowids.py` does, through `sys.executable`. That cannot work, because the root env has no numpy or faiss (`pyproject.toml:6`), and the job imports numpy at line 14. The inventory already flagged this, and I report it as a conflict below because the wrong instruction is in the settled plan. The only thing I could not confirm is the MMAP read of a flat index, which the inventory had already marked unverified.
<question id="1">
Yes, for the production code. The conflict check comes before `connect_source_db`, so a rejected flag combination touches nothing. The shared ATTACH/materialise/DETACH block already works on a cache that `connect_db` + `ensure_schema` has just created. `record_similarities` already gives the rewrite semantics the requirements ask for. The updater change is a one-token swap, and `_to_cpu_cmd` keeps it on the CPU retry. The refresh test is the one part that does not work as the plan words it. It has to run under `ENGINE_PY` (`conftest.py:32`) and build the FAISS index in an ENGINE_PY child, as `test_video.py:197,216-218` does. Run under `sys.executable`, as the plan says, the job dies with ModuleNotFoundError before it parses any arguments.
</question>
<question id="2">
- The updater stops truncating the similarity cache. A missing or deleted cache now stays empty after an updater run, and the run still exits 0 with `total sources=0`.
- New merged videos are cached only lazily by the Engine.
- Stale sources stay in the cache. Only `purge_hosts` removes any.
- Sources the Engine writes lazily join the next refresh at `--top-k 1000`.
- An interrupted or GPU-failed run leaves a valid, mixed-age cache, not a truncated one.
- The orchestrator smoke run starts from a fresh similarity path. It now produces a schema-only cache and never exercises the FAISS search or write path. Its `similarity_precompute` duration stops measuring precompute work.
- Issue 08 gains one more rowid join to convert.

The inventory records all of these, and the operator accepted them in the requirements.
</question>
<question id="3">
- The conflict check must sit between lines 334 and 335. It must not reject combinations among the other four flags.
- The shared incremental block must stay byte-identical for `--incremental`. No existing test covers that mode.
- The updater builder must not be named `precompute_cmd`. The local of that name in `main` would make it UnboundLocalError at the precompute stage.
- The refresh test needs ENGINE_PY, and so does the index construction.
- `config.json` `test_groups` should gain entries for both new files.
- UPDATER_WORKER.md step 10 should say that the initial full build is DATA_BUILD §5 / `run-dataset-build.sh`, because the updater no longer builds a missing cache.

`run-dataset-build.sh` needs nothing: `--recreate-out-db` on its own stays legal.
</question>
<question id="4">
The CLI gains one mode and one conflict check. Every existing flag combination behaves as before, and the `total sources` log line gains a `mode=` field. The updater's precompute stage changes from delete-and-rebuild-everything to rewrite-only-what-is-already-cached-and-still-embedded. Coverage of new videos moves from the updater to the Engine's first-request lazy write. Stale entries are no longer removed by the stage. A missing cache is no longer rebuilt by the updater.
</question>


New impacts:
none

Inventory entries that did not hold up:
tests/active/test_precompute_similar_ann_refresh.py (fixture caveat): I could not confirm whether `faiss.read_index(path, IO_FLAG_MMAP | IO_FLAG_READ_ONLY)` (precompute-similar-ann.py:417) accepts a flat `IndexIDMap(IndexFlatIP)` under the installed faiss. The installed faiss is `faiss-gpu-cu12==1.13.2` per `engine/server/requirements.txt:5`, not faiss-cpu. `test_video.py:216` only builds such an index in memory and never reads one back with MMAP. This needs a probe run under ENGINE_PY before the test is written, and the inventory's fallback (IndexIDMap2 over an nlist=1 IVFFlat) is still the plan B.
tests/active/conftest.py (ENGINE_PY): the constant is confirmed at line 32. However, `engine/pixi.toml` declares only python and pip. numpy and faiss come from `pip install -r engine/server/requirements.txt` into that env. The "run `pixi install` in engine/" hint that the inventory proposes reusing therefore does not by itself provide faiss. A fresh environment will fail on import, not on `ENGINE_PY.exists()`.

Conflicts: Settled plan, Tests paragraph: "The job runs as a subprocess with `--cpu`, the same way `test_precompute_random_rowids.py` runs its job". That test runs the job through `sys.executable`, and the test "builds everything in `tmp_path`", including "a flat IP FAISS index". Against it stands the repository: the gate runs under the root pixi env (`tests/last_test_validation.json:3-13`), whose dependencies (`pyproject.toml:6`) include neither numpy nor faiss. `precompute-similar-ann.py:14` imports numpy unconditionally, and faiss at line 17. `precompute-random-rowids.py` works under `sys.executable` only because it needs neither. Followed literally, the plan gives a test that fails on ModuleNotFoundError before argparse, including in the four forbidden-combination cases, which would then "pass" on a non-zero exit for the wrong reason. The minimal amendment is to run the job with `str(ENGINE_PY)` and build the index in an ENGINE_PY child, per `test_video.py:197,216-218`. This keeps the plan's intent (a real subprocess, failing loudly without faiss) and changes nothing else.

Recommendations: 1. Amend the plan's Tests paragraph as the conflict describes: ENGINE_PY for the job subprocess, and an ENGINE_PY child to build the index. Pure sqlite fixture work and the byte/mtime checks stay in-process. Cost: one sentence in the plan and about 15 lines of child-script string in the test. Without it, the test either cannot pass or passes vacuously on the forbidden combinations.
2. In the forbidden-combination cases, assert exit code 2 and a stderr fragment naming `--refresh-existing`, not just "non-zero". Cost: one assert per case. This is what separates a real argparse rejection from an import crash, which also exits non-zero and also leaves the file untouched.
3. Before the refresh test is drafted, probe once under ENGINE_PY that `read_index` with `IO_FLAG_MMAP|IO_FLAG_READ_ONLY` loads an `IndexIDMap(IndexFlatIP)`. If it does not, use `IndexIDMap2(IndexIVFFlat, nlist=1)`. Cost: one throwaway run. It avoids a red gate caused by the fixture, not by the code.
4. Name the updater builder `build_precompute_cmd` (or similar), never `precompute_cmd`. Cost: nothing. The wrong name gives an UnboundLocalError that surfaces only after the merge and the ANN rebuild.
5. Add the two `test_groups` entries to `.un/skills/devsecops/config.json`: refresh test → `precompute-similar-ann.py` + `data/embedding_space.py`; updater test → `updater-worker.py`. Cost: about 8 lines of JSON. If you skip them, both tests run on every invocation, which is slower but not less safe.
6. Take the optional UPDATER_WORKER.md sentence saying that a missing or empty cache stays empty and that the initial build is DATA_BUILD §5. Cost: one line. Without it, an operator who deletes the cache and expects the updater to rebuild it gets an empty cache and a green run.
7. Optional one-line fixes, each costing a line: DATA_BUILD.md:30 path (`jobs/docs/UPDATER_WORKER.md`), ORCHESTRATOR_SMOKE_TEST.md:16 wording, and issue 24 line 15 (`--incremental` → `--refresh-existing`). The issue 24 fix matters most, because lane 4b reads it.

## 2026-09-30 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-09-30 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Refresh guard [code]

**Files touched.** engine/server/db/jobs/precompute-similar-ann.py (EDITED), tests/active/test_precompute_similar_ann_refresh.py (NEW), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: the process boundary of `engine/server/db/jobs/precompute-similar-ann.py`. The job runs as a subprocess, following the harness in `tests/active/test_precompute_random_rowids.py` (`_run_job` with `cwd=tmp_path`, `capture_output`), but under `conftest.ENGINE_PY` because the job imports numpy and faiss. The run is guarded by `assert ENGINE_PY.exists()` with the message "run `pixi install` in engine/", as `test_internal_client_reads.py` does. `test_refresh_rejects_each_destructive_flag` is parametrised over the four flags `--incremental`, `--reset`, `--reset-only`, `--recreate-out-db` × {seeded cache, absent cache}. The seeded cache is made by the job's own `--reset-only` plus sqlite3 sentinel inserts, all under tmp_path. It records `read_bytes()` and `stat().st_mtime_ns`, or records that the file is absent, then runs `--refresh-existing <flag> --cpu`. It asserts `returncode == 2`, that stderr contains `--refresh-existing cannot be combined with` and the flag, and that bytes and mtime are unchanged or the file is still absent.

**Intent.** `precompute-similar-ann.py` accepts `--refresh-existing`, and its post-`parse_args` conflict check rejects it together with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` before the output file is opened, unlinked or created.

- C1 - Combining `--refresh-existing` with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` exits 2, naming the conflicting flag on stderr.
- C2 - After a rejected combination the output file keeps its bytes and mtime, or stays absent if it was absent.

**Outcome.** _pending_

#### Phase 2 - Refresh selection [code]

**Files touched.** engine/server/db/jobs/precompute-similar-ann.py (EDITED), tests/active/test_precompute_similar_ann_refresh.py (EDITED)

**Checkpoint.** Seam: the same subprocess boundary and harness as phase 1, in `tests/active/test_precompute_similar_ann_refresh.py`. The module fixture (`tmp_path_factory`) builds a tmp source DB, with `video_embeddings` rowids 1..9 where v9 has a 3-float blob, and an `IDMap2,IVF1,Flat` inner-product index built by an `ENGINE_PY` child, plus its `.json` sidecar. The child's non-zero exit is asserted along with its stderr, so a missing faiss fails the test and does not skip it. Each test creates its cache with `--reset-only` and seeds sentinel rows for `CACHED_LIVE + CACHED_UNTOUCHED`. `test_refresh_rewrites_exactly_cached_live_sources` runs `--refresh-existing --cpu --top-k 3` and asserts: exit 0; `mode=refresh-existing`, `total sources=4` and `done processed=3/4` in stderr; v1–v3 share one `computed_at` > 1 and hold only non-sentinel items ranked 1..n (n ≤ 3), each a LIVE key on DOMAIN other than the source itself; gone1, gone2, (v5, "") and v9 have source rows and items equal to the pre-run snapshot; no UNCACHED key has a row; there are still 7 sources. `test_refresh_over_missing_or_empty_cache_is_a_no_op`, parametrised ["missing", "empty"], asserts exit 0, total 0, done 0/0, both tables present in `sqlite_master`, and 0 sources.

**Intent.** Under `--refresh-existing`, the shared incremental/refresh selection branch in `precompute-similar-ann.py` inner-joins `video_embeddings` to the read-only attached `similarity_sources`, so the job rewrites exactly the cached sources still in `video_embeddings` and leaves every other cache row as it was.

- C1 - Each cached source still in `video_embeddings` that `build_query_batch` accepts is rewritten with the run's single new `computed_at` and only fresh ranked items, and nothing is selected when the cache is missing or schema-only.
- C2 - Every other cache row, whether a stale source, an empty-domain key or a length-skipped source, is left as it was, and uncached embeddings gain no rows.

**Outcome.** _pending_

#### Phase 3 - Updater argv [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED), tests/active/test_updater_precompute_cmd.py (NEW), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: the function boundary of `updater-worker.py`. The module is loaded in-process with `importlib.util.spec_from_file_location` from `JOBS_DIR / "updater-worker.py"`, following `test_host_normalisation._load_job`. `tests/active/test_updater_precompute_cmd.py::test_updater_builds_refresh_command`, parametrised over `use_gpu` ∈ {True, False}, asserts that `similarity_precompute_cmd(...)` with fixed tmp_path `Path`s and `python_bin="python3"` equals, as a list, the old literal with `--refresh-existing` in place of `--recreate-out-db` plus the `["--gpu", "--gpu-device", "0"]` or `["--cpu"]` suffix, and that `--recreate-out-db` is not in it. `test_cpu_fallback_keeps_refresh` asserts `module._to_cpu_cmd(gpu_cmd) == cpu_cmd`.

**Intent.** The updater's precompute stage builds its command through a module-level `similarity_precompute_cmd` in `updater-worker.py` that runs `--refresh-existing` in place of `--recreate-out-db`, and the CPU retry keeps that flag.

- C1 - For both `use_gpu` values, `similarity_precompute_cmd` returns the previous argv with `--recreate-out-db` replaced by `--refresh-existing`.
- C2 - `_to_cpu_cmd` applied to the GPU argv gives the CPU argv, keeping `--refresh-existing`.

**Outcome.** _pending_


Needs coordination: none. Phases 1 and 2 need the Engine pixi environment with numpy and faiss (`pixi install` in engine/). This is a local prerequisite that other tests in tests/active already share, not a credential or a manual step. If it is missing, the test fails and does not skip.

Rationale: The precompute change has two separately observable halves, so it is two phases.

- **Phase 1** is the argparse guard, which works on its own: the flag exists and the destructive combinations are refused before any file is touched.
- **Phase 2** is the selection SQL, which decides which rows are rewritten and which are left alone.

Putting the guard first means the first thing that lands with the new flag is its safety property. In the intermediate state, `--refresh-existing` alone runs as a full scan, and nothing calls it yet. The missing and empty cache cases are not a separate phase: they are the boundary case of the selected set being cached ∩ embeddings, which is empty over an empty cache. They are folded into phase 2's clause_1, so there is no phase with no code in it.

**Phase 3**, the updater builder, is independent of the job's internals. It is proved at the function boundary with the existing importlib harness.

The four forbidden flags are written as an explicit list in the clauses, not as a universal. They are a fixed set named by the plan, not one derived from production at run time.

Known limit: nothing asserts that `main()` calls `similarity_precompute_cmd`. The settled plan rejected driving `main()` because it would need lock, systemctl and crawler stubs. The call-site swap is a one-line replacement reviewed in the diff.

Documentation (UPDATER_WORKER.md step 10, DATA_BUILD.md §5, issue 24 line 15) gets no phase and is updated in Step 9. The `config.json` test_groups entries go in with the phase that creates each test file. The operator approved this breakdown.

## 2026-09-30 - Step 7 - Phase 1 (Refresh guard) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`precompute-similar-ann.py` accepts `--refresh-existing`, and its post-`parse_args` conflict check rejects it together with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` before the output file is opened, unlinked or created.

- C1 - Combining `--refresh-existing` with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` exits 2, naming the conflicting flag on stderr.
- C2 - After a rejected combination the output file keeps its bytes and mtime, or stays absent if it was absent.

must_prove:
- C1 - Combining `--refresh-existing` with any of `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` exits 2, naming the conflicting flag on stderr.
- C2 - After a rejected combination the output file keeps its bytes and mtime, or stays absent if it was absent.

## 2026-09-30 - Step 7 - Phase 1 (Refresh guard) - self-check (audit round 1, send-back 0)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:74, :76 and :80 — for each of the four flags × {seeded, absent}, `result.returncode == 2`, exactly one `precompute-similar-ann.py: error: ` line in stderr, and the set of whole `--flag` tokens on that line, intersected with the four destructive flags, `== {flag}`. Supported by :79 (`--refresh-existing` is on the line) and :95/:97 (with `--refresh-existing --cpu` alone there is no error line and the job goes on to create `--out`). - expected: Exit 2, and one line `precompute-similar-ann.py: error: --refresh-existing cannot be combined with <flag>` whose destructive tokens are exactly {flag}. The run confirmed that argparse puts the error on its own `prog: error: message` line after the usage block, and that the usage block lists every flag; this is why only the error line is searched. With the flag alone, the run gets past parsing and creates `--out`. The probe saw this for `--cpu` alone: rc=1 and the absent file exists afterwards. - excludes: The code as it stands, which does not know the flag: the run showed exit 2 and the line `precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing`, so the intersection is `set()` and :80 goes red on all 8 cases. A check that names all four flags at once, or names the wrong one, gives an intersection other than {flag}. A plain substring check would let `--reset` match inside `--reset-only`; whole tokens prevent that. A guard that refuses `--refresh-existing` on its own prints an error line with no destructive flag, which fails :95.
- C2 - tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:82 and :83 — for a seeded `--out`, the file still exists and `(read_bytes(), st_mtime_ns) == before`. :85 — for an absent `--out`, `not out_path.exists()`. Both hold after each of the four refused combinations.</expected> - expected: Seeded: the file exists and has the same bytes and mtime. Absent: still absent. Seen in the probe on the argparse-exit path, which is the same exit `parser.error` takes: rc=2, seeded exists=True unchanged=True, absent exists=False. - excludes: A conflict check placed after the output file is opened (after `connect_db`/`ensure_schema`, the `--reset` DELETE, or the `--reset-only`/`--recreate-out-db` unlink). The probe showed what the destructive paths do to the observable: in every absent case the file is created (exists=True for `--cpu`, `--incremental --cpu` and `--reset --cpu`), so :85 goes red for all four flags. In the seeded `--reset` case the bytes change (unchanged=False), so :83 goes red. `--reset-only` and `--recreate-out-db` unlink the seeded file and recreate it or leave it removed, so :82/:83 go red; this last one comes from reading the source (lines 373-406) and was not probed. Seeded `--incremental` was observed to leave the file unchanged, so that one cell is carried only by its absent twin.

<assertions>
tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:74 — `--refresh-existing <flag> --cpu` exits with returncode 2, for each of the 4 flags × {seeded, absent} cache (8 cases). Today this already passes, because argparse exits 2 on the unknown `--refresh-existing`, so line 76 carries the red — C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:76 — stderr holds exactly one line containing `--refresh-existing cannot be combined with`. Fails today (0 == 1) in all 8 cases — C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:79 — the whole `--flag` tokens after that phrase on the refusal line, intersected with the four destructive flags, equal exactly {flag}. The check is limited to the refusal line because argparse's usage block on stderr lists all four flags. Matching whole tokens stops `--reset` being found inside `--reset-only`. It also rejects a fixed message that lists every flag instead of the one that conflicted — C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:81 — seeded case: `--out` still exists after the refusal. Catches a check placed after `--recreate-out-db`/`--reset-only` unlink the file — C2
tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:82 — seeded case: `(read_bytes(), st_mtime_ns)` of `--out` equals the pair recorded after the sentinel commit. The cache was laid out by the job's own `--reset-only`, then given one sentinel similarity_sources row and one similarity_items row through sqlite3. A late check after the `--reset` DELETE, or after `--reset-only` recreates the file, drops the sentinels and changes the bytes — C2
tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:84 — absent case: `--out` does not exist after the refusal; line 69 asserts it was absent before. Catches a check placed after `connect_db`/`ensure_schema`, which the probe showed creates the file — C2
tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:93 — positive control: `--refresh-existing --cpu` with no destructive flag produces no refusal line, so the conflict check depends on a destructive flag being present — C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:94 — positive control: that same run's stderr has no `unrecognized arguments`, so the job accepts `--refresh-existing` (the intent's "accepts `--refresh-existing`"). Fails today — C1
Setup controls, not clause-bearing: `_seed_cache` asserts that the seeding `--reset-only` run returns 0. `_run_job` asserts `ENGINE_PY.exists()` with the "run `pixi install` in engine/" message. Every path is under tmp_path, including `--db`, `--index` (not present) and `--out`, so the repo's whitelist.db and faiss index are never read.
Current red, observed: all 8 parametrised cases get past the seeding and line 74, then fail at line 76. test_refresh_alone_is_not_refused fails at line 94.
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/test_probe_25_p1.py", "-s"] (probe at tests/tmp/test_probe_25_p1.py). It used ENGINE_PY, a tmp source.db holding an empty video_embeddings table, `--index tmp/missing.faiss` and `--out tmp/similarity-cache.db`. It printed:
(1) ENGINE_PY is /home/enduser/code/PeerTube-browser/engine/.pixi/envs/default/bin/python and exists=True; importing it from tests/tmp works after adding tests/active to sys.path.
(2) `--reset-only` with no `--cpu` returned rc 0. stderr was "INFO reset-only: no existing file at …" then "INFO reset-only completed: output cache recreated". Tables created: similarity_items, similarity_sources, similarity_source_rank_idx plus the two autoindexes. The sentinel INSERTs into both tables succeeded. Afterwards the directory held only similarity-cache.db and source.db, with no journal file left.
(3) Current code, `--refresh-existing <flag> --cpu`, for each of the 4 flags: rc 2. stderr was the full argparse usage block, which lists [--recreate-out-db] [--reset] [--reset-only] [--incremental], then "precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing". The seeded file's (bytes, mtime_ns) were unchanged. So returncode == 2 and "flag in stderr" both pass on today's code, which is why the flag check is limited to the refusal line.
(4) Unknown `--bogus`: the same rc 2 and usage block.
(5) Plain `--cpu` on an absent `--out`: rc 1, sqlite3.OperationalError "no such column: model_name" raised from resolve_embedding_space, and the absent `--out` now existed. So a check placed after connect_db/ensure_schema creates the file, and the absent case catches it.
Cleanup: the probe file tests/tmp/test_probe_25_p1.py is still there. I have no delete tool, so it needs removing by hand.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py` - 4553 characters, inlined in full

```
"""`precompute-similar-ann.py` refuses `--refresh-existing` beside a destructive flag before it touches `--out`.

- Run with `--refresh-existing --cpu` and one of `--incremental`, `--reset`, `--reset-only`, `--recreate-out-db`, the job exits 2 with a `--refresh-existing cannot be combined with` line naming that flag and no other of the four, over a seeded cache or none.
- After that refusal a seeded `--out` keeps its bytes and mtime, and an absent one is still absent.
- Run with `--refresh-existing --cpu` alone, the job reports neither that refusal nor an unrecognised argument.

The job runs as a child process under the engine's pixi interpreter on temporary sqlite files.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import ENGINE_PY  # noqa: E402

SIMILAR_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py"
DESTRUCTIVE_FLAGS = ["--incremental", "--reset", "--reset-only", "--recreate-out-db"]
REFUSAL = "--refresh-existing cannot be combined with"


def _source_db(tmp_path: Path) -> None:
    """An empty source: the refusal must come before anything reads it."""
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER)")
    conn.commit()
    conn.close()


def _run_job(tmp_path: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    return subprocess.run([str(ENGINE_PY), str(SIMILAR_JOB), "--db", str(tmp_path / "source.db"), "--index", str(tmp_path / "missing.faiss"), "--out", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=120)


def _seed_cache(tmp_path: Path, out_path: Path) -> None:
    """A cache laid out by the job's own `--reset-only`, then holding one sentinel source and item."""
    seeded = _run_job(tmp_path, out_path, "--reset-only")
    assert seeded.returncode == 0, seeded.stderr
    conn = sqlite3.connect(out_path)
    conn.execute("INSERT INTO similarity_sources VALUES ('sentinel-video', 'sentinel.example', 1)")
    conn.execute("INSERT INTO similarity_items VALUES ('sentinel-video', 'sentinel.example', 'other-video', 'sentinel.example', 0.5, 1)")
    conn.commit()
    conn.close()


def _refusal_lines(stderr: str) -> list[str]:
    # The usage block argparse prints lists every flag, so only the refusal line itself can name one.
    return [line for line in stderr.splitlines() if REFUSAL in line]


@pytest.mark.parametrize("cache", ["seeded", "absent"])
@pytest.mark.parametrize("flag", DESTRUCTIVE_FLAGS)
def test_refresh_rejects_each_destructive_flag(tmp_path: Path, flag: str, cache: str) -> None:
    """`--refresh-existing` beside `flag` exits 2 on a refusal line naming `flag` alone, and leaves a seeded `--out` at the same bytes and mtime, or an absent one absent."""
    _source_db(tmp_path)
    out_path = tmp_path / "similarity-cache.db"
    if cache == "seeded":
        _seed_cache(tmp_path, out_path)
        before = (out_path.read_bytes(), out_path.stat().st_mtime_ns)
    else:
        assert not out_path.exists()

    result = _run_job(tmp_path, out_path, "--refresh-existing", flag, "--cpu")

    assert result.returncode == 2, result.stderr  # C1
    refusals = _refusal_lines(result.stderr)
    assert len(refusals) == 1, result.stderr  # C1
    named = set(re.findall(r"--[\w-]+", refusals[0].split(REFUSAL, 1)[1]))
    # Whole tokens, so `--reset` is not found inside `--reset-only`.
    assert named & set(DESTRUCTIVE_FLAGS) == {flag}, refusals[0]  # C1
    if cache == "seeded":
        assert out_path.exists()  # C2
        assert (out_path.read_bytes(), out_path.stat().st_mtime_ns) == before  # C2
    else:
        assert not out_path.exists()  # C2


def test_refresh_alone_is_not_refused(tmp_path: Path) -> None:
    """`--refresh-existing --cpu` with no destructive flag reports neither the refusal nor an unrecognised argument."""
    _source_db(tmp_path)

    result = _run_job(tmp_path, tmp_path / "similarity-cache.db", "--refresh-existing", "--cpu")

    assert _refusal_lines(result.stderr) == [], result.stderr  # C1
    assert "unrecognized arguments" not in result.stderr, result.stderr  # C1

```


Gate: satisfied

## 2026-09-30 - Step 7 - Phase 1 (Refresh guard) - red (audit round 1)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py` exited 1.

```
  tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py  9 failed                               0.0s
  ------------------------------------------------------------------
  total                                                               9 failed                               2.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-30 - Step 7 - Phase 1 (Refresh guard) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
All 8 parametrizations of `test_refresh_rejects_each_destructive_flag` should fail at line 80 on `assert named & set(DESTRUCTIVE_FLAGS) == {flag}`. The current parser has no `--refresh-existing`, so argparse exits 2 with the single line `precompute-similar-ann.py: error: unrecognized arguments: --refresh-existing`. That line names no destructive flag, so the intersection is `set()`, and lines 74, 76 and 79 pass before it. `test_refresh_alone_is_not_refused` should fail at line 95 on `assert _error_lines(result.stderr) == []`, because the same unrecognized-arguments line is there.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_precompute_similar_ann_refresh.py (NEW), which does not resolve. That file was not read, and the checks did not need it.
2. .un/skills/devsecops/config.json was read. It holds only test-group mappings and plays no part in this test's assertion form.
3. Whether `ENGINE_PY` (tests/active/conftest.py:32) exists on disk was not checked, since that would mean running the test. If it is missing, the test fails at line 40 on the `ENGINE_PY.exists()` precondition instead of at the predicted line 80.

Basis:
- Anti-pattern pass (rules/shape.md): no entry matches.
  - **doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep:** the test never reads a `.md` file.
  - **hardcoded-spec-mirror:** `DESTRUCTIVE_FLAGS` (line 27) is only used as parametrized input. It is never compared for equality against a code constant.
  - **tautological-assertion:** the expected values are the parameter and the exit code 2. The test works none of them out the way the code would.
  - **echoed-literal:** `flag` is an input that line 80 expects back, but the job's own conflict check produces the error line in between. Removing that check makes line 80 fail.
  - **absence-only-assertion:** the `absent` case's `assert not out_path.exists()` (line 85) comes after positive assertions in the same test (lines 74, 76, 79, 80). Test 2's `== []` (line 95) is paired with `assert out_path.exists()` (line 97).
  - **single-value-pin:** each of the four flags must appear alone in the error, so a hard-coded conflict message fails three of the four.
- Ladder pass (rules/shape.md `<ladder>`): the code under test is a CLI script, and the clauses are its exit code, its stderr and what it leaves on disk. That is rung 2 (subprocess) combined with rung 3 (file bytes and mtime), which is the highest rung that fits. It is not the anti-rung, and nothing is shifted to a lower rung, so `<downshift_rule>` does not apply.
- Stub question: the test does not pass against these plausible wrong implementations:
  - **Current code (flag unknown):** fails at line 80.
  - **`--refresh-existing` accepted but no conflict check:** fails at line 74.
  - **A fixed conflict message:** fails at line 80 for three of the four flags.
  - **Conflict check placed after the output file is opened:** the job runs `connect_db` at engine/server/db/jobs/precompute-similar-ann.py:408, and `--recreate-out-db`/`--reset-only` delete the file at lines 383 and 396. The `absent` case fails at line 85 and the seeded case fails at line 83.
  - **A job that rejects `--refresh-existing` in every case:** fails at line 95.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 4 must_prove, 13 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `--refresh-existing` with any of the four destructive flags "exits 2" | :74 (parametrized over all four at :61) | only some flags rejected; a refusal raised inside `main`'s try block (exit 1) instead of a usage error | CARRIED |
| C1b | must_prove | "naming the conflicting flag on stderr" | :80 | a generic refusal naming no flag; naming the wrong flag; a message listing all four. On its own, :80 also passes the "unrecognized arguments: --refresh-existing <flag>" error that an unimplemented flag produces. :95 rules that case out. | CARRIED |
| C2a | must_prove | seeded output "keeps its bytes and mtime" | :83 | the `--reset` DELETE or the `--recreate-out-db` unlink running before the refusal; a rewrite that leaves the same bytes but a new mtime | CARRIED |
| C2b | must_prove | absent output "stays absent" | :85 | `connect_db`/`ensure_schema` creating `--out` before the refusal | CARRIED |
| D1 | docstring | "refuses ... before it touches `--out`" (module :1) | :83, :85 | any write, or creation of the file, ahead of the argument check | CARRIED |
| D2 | docstring | "exits 2" (module :3, fn :63) | :74 | a non-argparse failure exit | CARRIED |
| D3 | docstring | "on one argparse error line" (module :3, fn :63) | :76 | a traceback or logged RuntimeError, which carries no `prog: error:` line; a refusal spread over several error lines | CARRIED |
| D4 | docstring | error line names `--refresh-existing` (module :3) | :79 | a message naming only the destructive flag | CARRIED |
| D5 | docstring | names "that flag and no other of the four" (module :3, fn :63 "`flag` alone of the four") | :80 | a blanket message listing every destructive flag; `--reset` mis-matched inside `--reset-only`, which the whole-token regex at :78 prevents | CARRIED |
| D6 | docstring | "over a seeded cache or none" (module :3) | :60 with :74–:80 run under both params | a refusal that only happens when the cache exists, or only when it is absent | CARRIED |
| D7 | docstring | "a seeded `--out` keeps its bytes and mtime" (module :4, fn :63) | :82, :83 | deletion (:82); content or timestamp change (:83) | CARRIED |
| D8 | docstring | "an absent one is still absent" (module :4, fn :63) | :85 | creation of `--out` on the refusal path | CARRIED |
| D9 | docstring | `--refresh-existing --cpu` alone "prints no argparse error" (module :5, fn :89) | :95 | a parser that refuses `--refresh-existing` whatever it is paired with, or does not recognise it at all | CARRIED |
| D10 | docstring | "goes on to create `--out`" (module :5, fn :89) | :97 | a refusal of the flag-alone case by non-argparse means before the output connect | CARRIED |
| D11 | docstring | "runs as a child process under the engine's pixi interpreter" (module :7) | :40, :41 | an in-process import or a different interpreter | CARRIED |
| D12 | docstring | "on temporary sqlite files" (module :7) | :33, :41, :65 | running against the repo's real `--db`/`--out` defaults | CARRIED |
| D13 | docstring | `_seed_cache`: cache "laid out by the job's own `--reset-only`" holding a sentinel (:45) | :47 | a seeded cache the job did not create, so C2a would compare a foreign file | CARRIED |
| N1 | name | "refresh rejects each destructive flag" | :74, :80 over :61 | rejecting a subset of `DESTRUCTIVE_FLAGS`, which matches C1's four exactly | CARRIED |
| N2 | name | "refresh alone is not refused" | :95, :97 | a refresh flag refused unconditionally | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py:72
   `result = _run_job(tmp_path, out_path, "--refresh-existing", flag, "--cpu")`
   Each run pairs `--refresh-existing` with one destructive flag and always adds `--cpu`. Two cases at the edge of the accepted input are untested:
   - Two destructive flags at once, e.g. `--refresh-existing --reset --incremental`. :80 would then need a stated expectation for which flags the line names.
   - A combination without an accelerator flag. The job's existing `--cpu/--gpu` check at precompute-similar-ann.py:335 can then fire first, and C1's "naming the conflicting flag" is not pinned for that order.
   C1's four single-flag cases are fully covered, so this is not a Critical.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_precompute_similar_ann_refresh.py (NEW), which does not resolve. It was not read.
2. The copy of engine/server/db/jobs/precompute-similar-ann.py I read has no `--refresh-existing` option (`main` at :275–:336). I could not check the refusal path or the order of its argument checks against the code. I judged C1 and C2 on argparse's error-line convention and on where `main` first opens `--out` (:370–:409).
3. Only the first 40 of 202 lines of .un/skills/devsecops/config.json were read. It carries no behaviour the claims depend on.
4. No `fixtures_path` was supplied. The test uses no pytest fixture beyond `tmp_path`. `ENGINE_PY` is imported from tests/active/conftest.py and resolved there (:32).

## 2026-09-30 - Step 7 - Phase 1 (Refresh guard) - checkpoint outcome (run 1)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/server/db/jobs/precompute-similar-ann.py`
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py  9 passed                               0.0s
  ------------------------------------------------------------------
  total                                                               9 passed                               2.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-30 - Step 7 - Phase 2 (Refresh selection) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
Under `--refresh-existing`, the shared incremental/refresh selection branch in `precompute-similar-ann.py` inner-joins `video_embeddings` to the read-only attached `similarity_sources`, so the job rewrites exactly the cached sources still in `video_embeddings` and leaves every other cache row as it was.

- C1 - Each cached source still in `video_embeddings` that `build_query_batch` accepts is rewritten with the run's single new `computed_at` and only fresh ranked items, and nothing is selected when the cache is missing or schema-only.
- C2 - Every other cache row, whether a stale source, an empty-domain key or a length-skipped source, is left as it was, and uncached embeddings gain no rows.

must_prove:
- C1 - Each cached source still in `video_embeddings` that `build_query_batch` accepts is rewritten with the run's single new `computed_at` and only fresh ranked items, and nothing is selected when the cache is missing or schema-only.
- C2 - Every other cache row, whether a stale source, an empty-domain key or a length-skipped source, is left as it was, and uncached embeddings gain no rows.

## 2026-09-30 - Step 7 - Phase 2 (Refresh selection) - self-check (audit round 1, send-back 0)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:131, :132, :134, :135 — over the seeded cache, `--refresh-existing --cpu --top-k 3` exits 0, stderr contains `mode=refresh-existing`, the logged `total sources=` is exactly ("4",), and `done processed=` is exactly ("3", "4") - expected: rc 0, then `INFO total sources=4 mode=refresh-existing` and `INFO done processed=3/4`. Four are selected (v1, v2, v3 and v9, the cached keys still in video_embeddings) and three processed, because build_query_batch drops v9's 3-float blob. The run showed that this drop really happens on this fixture: today's full scan logs `total sources=9` and `done processed=8/9`. - excludes: The code as it stands, a full scan with no `mode=` field. The run showed rc 0, no `mode=` in stderr, `total sources=9` and `done processed=8/9`, so :132 goes red. The incremental LEFT JOIN / IS NULL reused for refresh selects the 5 uncached keys and logs 5 and 5/5. A join on video_id alone also picks up (v5, live.example) and logs 5 and 4/5.
- C1 - tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:138, :140, :142, :144, :145 — v1, v2 and v3 share exactly one `computed_at`, which lies between the wall-clock ms taken before and after the run and above the sentinel 1. Each has items ranked exactly [1, 2, 3], none points at the sentinel target, and every target is a LIVE key other than the source itself. - expected: The probe ran the same seeded cache through the job's rewrite path (today's full scan writes v1-v3 through the same record_similarities). One stamp, 1790808419854, fell inside the window [1790808419716, 1790808419887]. v1 got [(v2,1),(v8,2),(v4,3)], v2 got [(v1,1),(v3,2),(v8,3)] and v3 got [(v4,1),(v2,2),(v1,3)], all on live.example, with no sentinel item left. - excludes: A refresh that selects the right keys but never rewrites them, for example one that only updates `computed_at` or skips record_similarities. v1-v3 then keep computed_at 1 and the single sentinel item: :140 and :142/:144 go red. A per-row stamp would give more than one stamp and fail :138. Dropping the self-exclusion would put the source among its own targets and fail :145.
- C1 - tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:163, :165, :166, :170, :171, :172 — for a missing cache and for a schema-only cache: rc 0, `total sources=` ("0",), `done processed=` ("0", "0"), both cache tables in sqlite_master, and 0 rows in each - expected: rc 0, `total sources=0 mode=refresh-existing`, `done processed=0/0`, and a file holding both empty tables. The job's own connect_db + ensure_schema creates the tables before selection runs. The probe saw the missing-cache run exit 0 and leave the file in place. The table-list and 0-row assertions have not been observed passing, because the run stops at :165. They rest on ensure_schema running before selection, which the phase does not change. - excludes: The code as it stands. The run showed rc 0 and `total sources=9` in both the missing and the empty case, so :165 fails with ('9',) == ('0',). If the run reached :171, 8 source rows would be written. A refresh that treats an empty cache as "refresh everything" gives the same result.
- C2 - tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:146 — gone1, gone2, (v5, "") and v9 each have a `computed_at` and items equal to the pre-run snapshot (control :147: that snapshot holds the sentinel stamp) - expected: Each of the four keeps (1, [('sentinel-target', 'sentinel.example', 0.5, 1)]). The probe showed exactly this before and after the run. - excludes: A refresh that prunes cached sources that are gone from video_embeddings: gone1/gone2 read (None, []). A refresh that clears items for every selected key before search, including ones build_query_batch then drops: v9 reads (1, []). A key match that ignores the empty domain and rewrites (v5, ""): (v5, "") gets a new stamp and new items.
- C2 - tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:148, :149 — v4 to v8 on live.example have no source row and no items, and similarity_sources still holds exactly 7 rows - expected: {key: (None, []) for each of v4..v8}, and COUNT = 7. - excludes: The code as it stands (full scan). The probe showed v4-v8 each gaining a source row with stamp 1790808419854 and 3 items, and COUNT 12. A join on video_id alone writes (v5, live.example). The incremental outer join writes all five.

<assertions>
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:131 - `--refresh-existing --cpu --top-k 3` over the seeded cache exits 0 - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:132 - stderr contains `mode=refresh-existing` - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:134 - logged `total sources` is exactly 4 (v1, v2, v3, v9: the cached keys still in video_embeddings); a full scan logs 9 - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:135 - logged `done processed` is exactly 3/4 (v9 dropped by build_query_batch); a full scan logs 8/9 - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:138 - v1, v2 and v3 have source rows sharing a single computed_at - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:140 - that computed_at is not None, is greater than the sentinel 1, and falls between wall-clock ms taken just before and just after the run - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:142 - each of v1, v2 and v3 has items ranked exactly [1, 2, 3], so a rewrite that leaves no items fails (stricter than the agreed n <= 3 because the 8 unit vectors make exactly 3 non-self neighbours certain, as the probe showed) - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:144 - no item of v1, v2 or v3 still points at the sentinel target - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:145 - every item target of v1, v2 and v3 is a LIVE key on DOMAIN other than the source itself - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:146 - gone1, gone2, (v5, "") and v9 each keep a computed_at and items equal to the pre-run snapshot - C2
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:147 - control, not a clause: that snapshot holds the sentinel computed_at, so line 146 is not comparing empty against empty - (control)
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:148 - the UNCACHED keys v4, (v5, DOMAIN), v6, v7 and v8 have no source row and no items - C2
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:149 - similarity_sources still holds exactly 7 rows; a full scan leaves 12 - C2
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:163 - [missing|empty] `--refresh-existing --cpu --top-k 3` exits 0 - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:165 - [missing|empty] logged `total sources` is exactly 0; a full scan logs 9 - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:166 - [missing|empty] logged `done processed` is exactly 0/0 - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:170 - [missing|empty] similarity_sources and similarity_items are both present in sqlite_master - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:171 - [missing|empty] similarity_sources has 0 rows - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:172 - [missing|empty] similarity_items has 0 rows - C1
</assertions>

<probes>
Ran ValidateTests ["tests/tmp/test_probe_25_p2.py", "-s"] and read the printed values from tests/last_test_output.txt. The probe built the checkpoint's fixture: a source DB with rowids 1..8 holding 4-float unit vectors, v9 declaring dim 4 but storing 3 floats, an `IDMap2,IVF1,Flat` METRIC_INNER_PRODUCT index built by an ENGINE_PY child, and a `.json` sidecar. It seeded sentinels, then ran the CURRENT code with `--refresh-existing --cpu --top-k 3`, both over the seeded cache and over a missing one.
BUILD: rc 0, stdout 'ntotal 8', stderr only 'WARNING clustering 8 points to 1 centroids: please provide at least 39 training points', a harmless warning.
SEED: `--reset-only` rc 0.
RUN on the current code: rc 0; stderr: 'INFO embedding space model=probe-model dim=4 / INFO index verified ... / INFO faiss acceleration=cpu / INFO total sources=9 / INFO done processed=8/9 elapsed=0s'. So the current code, treating --refresh-existing as a full scan, logs 9 and 8/9, and there is no mode line yet.
SOURCES on the current code: 12 rows. v1-v8 on live.example are stamped 1790808320827 (epoch ms), and gone1, gone2, (v5, '') and v9 stay at 1. So the uncached v4-v8 gain rows under the wrong behaviour, and v9 is length-skipped.
ITEMS on the current code: every processed source has exactly 3 items ranked 1..3, all on live.example and never the source itself (e.g. v1 -> v2 0.8, v8 0.6, v4 0.0). The untouched keys keep their sentinel item.
MISSING cache on the current code: rc 0, total sources=9, processed 8/9, file created.
Then ran ValidateTests ["tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py"] against the unchanged code: 3 failed, all after setup succeeded. test_refresh_rewrites_exactly_cached_live_sources fails at line 132 (no `mode=refresh-existing`; stderr shows total sources=9 and 8/9). Both parametrised no-op cases fail at line 165 with ('9',) != ('0',).
The probe file tests/tmp/test_probe_25_p2.py should be deleted, but I have no delete tool, so it is still on disk. Please remove it.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py` - 10002 characters, inlined in full

```
"""`precompute-similar-ann.py --refresh-existing` rewrites exactly the cached sources still in `video_embeddings` and leaves every other cache row as it was.

- Over a cache holding v1-v3 (live), gone1, gone2, (v5, "") and the length-skipped v9, the job logs `mode=refresh-existing`, 4 total sources and 3/4 processed; v1-v3 carry one `computed_at` stamped during the run and exactly three fresh items ranked 1..3 on other live keys, the rest keep their snapshot rows and items, the uncached v4-v8 gain no rows, and 7 sources remain.
- Over a missing or schema-only cache the job exits 0 with 0 total and 0/0 processed, leaves both cache tables in place, and writes no rows.

The job runs as a child process under the engine's pixi interpreter on temporary sqlite files and a real FAISS index built by that interpreter.
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import ENGINE_PY  # noqa: E402

SIMILAR_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py"
DOMAIN = "live.example"
MODEL = "refresh-test-model"
DIM = 4
# Unit vectors: under inner product each is its own nearest neighbour, so after the job drops self a --top-k 3 search over these 8 leaves exactly 3 others.
VECTORS = {1: (1.0, 0.0, 0.0, 0.0), 2: (0.8, 0.6, 0.0, 0.0), 3: (0.0, 1.0, 0.0, 0.0), 4: (0.0, 0.6, 0.8, 0.0), 5: (0.0, 0.0, 1.0, 0.0), 6: (0.0, 0.0, 0.6, 0.8), 7: (0.0, 0.0, 0.0, 1.0), 8: (0.6, 0.0, 0.0, 0.8)}
# Declares DIM but stores 3 floats, so it shares the table's one embedding space yet `build_query_batch` drops it.
SHORT_ROWID = 9
LIVE = {(f"v{rowid}", DOMAIN) for rowid in [*VECTORS, SHORT_ROWID]}
CACHED_LIVE = [("v1", DOMAIN), ("v2", DOMAIN), ("v3", DOMAIN)]
# gone1/gone2 left video_embeddings; ("v5", "") shares a video_id with a live key, so a join on video_id alone would wrongly pick up (v5, DOMAIN).
CACHED_UNTOUCHED = [("gone1", DOMAIN), ("gone2", DOMAIN), ("v5", ""), (f"v{SHORT_ROWID}", DOMAIN)]
UNCACHED = [("v4", DOMAIN), ("v5", DOMAIN), ("v6", DOMAIN), ("v7", DOMAIN), ("v8", DOMAIN)]
SENTINEL_AT = 1
SENTINEL_TARGET = ("sentinel-target", "sentinel.example")
INDEX_BUILDER = """
import sqlite3, sys
import faiss, numpy as np
db, index_path, dim = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = sqlite3.connect(db).execute("SELECT rowid, embedding FROM video_embeddings WHERE length(embedding) = ?", (dim * 4,)).fetchall()
vectors = np.vstack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
index = faiss.index_factory(dim, "IDMap2,IVF1,Flat", faiss.METRIC_INNER_PRODUCT)
index.train(vectors)
index.add_with_ids(vectors, np.array([row[0] for row in rows], dtype=np.int64))
faiss.write_index(index, index_path)
"""


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A source DB with `video_embeddings` rowids 1..9 and an inner-product index over the 8 full-length vectors, with its model sidecar."""
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    root = tmp_path_factory.mktemp("similar_refresh")
    conn = sqlite3.connect(root / "source.db")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL)")
    rows = [(rowid, f"v{rowid}", DOMAIN, struct.pack(f"<{DIM}f", *vector), DIM, MODEL) for rowid, vector in VECTORS.items()]
    rows.append((SHORT_ROWID, f"v{SHORT_ROWID}", DOMAIN, struct.pack("<3f", 1.0, 1.0, 1.0), DIM, MODEL))
    conn.executemany("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name) VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    # A missing faiss or numpy fails here with the child's stderr rather than skipping.
    built = subprocess.run([str(ENGINE_PY), "-c", INDEX_BUILDER, str(root / "source.db"), str(root / "index.faiss"), str(DIM)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert built.returncode == 0, built.stderr
    (root / "index.faiss.json").write_text(json.dumps({"model_name": MODEL, "embedding_dim": DIM}), encoding="utf-8")
    return root


def _run_job(source: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(ENGINE_PY), str(SIMILAR_JOB), "--db", str(source / "source.db"), "--index", str(source / "index.faiss"), "--out", str(out_path), *args], cwd=out_path.parent, capture_output=True, text=True, encoding="utf-8", timeout=120)


def _reset_cache(source: Path, out_path: Path) -> None:
    """A schema-only cache laid out by the job's own `--reset-only`."""
    seeded = _run_job(source, out_path, "--reset-only")
    assert seeded.returncode == 0, seeded.stderr


def _seed_cache(source: Path, out_path: Path) -> None:
    """Every key in CACHED_LIVE + CACHED_UNTOUCHED gets a source row at SENTINEL_AT and one item pointing at SENTINEL_TARGET."""
    _reset_cache(source, out_path)
    conn = sqlite3.connect(out_path)
    for video_id, domain in CACHED_LIVE + CACHED_UNTOUCHED:
        conn.execute("INSERT INTO similarity_sources VALUES (?, ?, ?)", (video_id, domain, SENTINEL_AT))
        conn.execute("INSERT INTO similarity_items VALUES (?, ?, ?, ?, 0.5, 1)", (video_id, domain, *SENTINEL_TARGET))
    conn.commit()
    conn.close()


def _snapshot(out_path: Path, keys: list[tuple[str, str]]) -> dict[tuple[str, str], tuple[int | None, list[tuple]]]:
    """Per key: its `computed_at` (None without a source row) and its items as (similar_video_id, similar_instance_domain, score, rank) in rank order."""
    conn = sqlite3.connect(out_path)
    snapshot = {}
    for video_id, domain in keys:
        row = conn.execute("SELECT computed_at FROM similarity_sources WHERE video_id = ? AND instance_domain = ?", (video_id, domain)).fetchone()
        items = conn.execute("SELECT similar_video_id, similar_instance_domain, score, rank FROM similarity_items WHERE source_video_id = ? AND source_instance_domain = ? ORDER BY rank", (video_id, domain)).fetchall()
        snapshot[(video_id, domain)] = (row[0] if row else None, items)
    conn.close()
    return snapshot


def _count(out_path: Path, table: str) -> int:
    conn = sqlite3.connect(out_path)
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return count


def _logged(stderr: str, pattern: str) -> tuple[str, ...]:
    match = re.search(pattern, stderr)
    assert match, stderr
    return match.groups()


def test_refresh_rewrites_exactly_cached_live_sources(source: Path, tmp_path: Path) -> None:
    """v1-v3 get one run-time `computed_at` and exactly three fresh items ranked 1..3 on other live keys; gone1, gone2, (v5, "") and the length-skipped v9 keep their rows and items; v4-v8 gain nothing; 4 sources are selected and 3 processed."""
    out_path = tmp_path / "similarity-cache.db"
    _seed_cache(source, out_path)
    before = _snapshot(out_path, CACHED_UNTOUCHED)
    started_ms = int(time.time() * 1000)

    result = _run_job(source, out_path, "--refresh-existing", "--cpu", "--top-k", "3")

    finished_ms = int(time.time() * 1000)
    assert result.returncode == 0, result.stderr  # C1
    assert "mode=refresh-existing" in result.stderr, result.stderr  # C1
    # A full scan logs 9 and 8/9; an outer join from the incremental path would also count the uncached keys.
    assert _logged(result.stderr, r"total sources=(\d+)") == ("4",)  # C1
    assert _logged(result.stderr, r"done processed=(\d+)/(\d+)") == ("3", "4")  # C1
    rewritten = _snapshot(out_path, CACHED_LIVE)
    stamps = {computed_at for computed_at, _ in rewritten.values()}
    assert len(stamps) == 1, rewritten  # C1
    (stamp,) = stamps
    assert stamp is not None and stamp > SENTINEL_AT and started_ms <= stamp <= finished_ms, (stamp, started_ms, finished_ms)  # C1
    for key, (_, items) in rewritten.items():
        assert [rank for *_, rank in items] == [1, 2, 3], (key, items)  # C1
        targets = {(video_id, domain) for video_id, domain, _, _ in items}
        assert SENTINEL_TARGET not in targets, (key, items)  # C1
        assert targets <= LIVE - {key}, (key, items)  # C1
    assert _snapshot(out_path, CACHED_UNTOUCHED) == before  # C2
    assert all(computed_at == SENTINEL_AT for computed_at, _ in before.values()), before
    assert _snapshot(out_path, UNCACHED) == {key: (None, []) for key in UNCACHED}  # C2
    assert _count(out_path, "similarity_sources") == len(CACHED_LIVE + CACHED_UNTOUCHED) == 7  # C2


@pytest.mark.parametrize("cache", ["missing", "empty"])
def test_refresh_over_missing_or_empty_cache_is_a_no_op(source: Path, tmp_path: Path, cache: str) -> None:
    """Over a missing or schema-only cache, `--refresh-existing` exits 0 with 0 total and 0/0 processed, and leaves both cache tables present and empty."""
    out_path = tmp_path / "similarity-cache.db"
    if cache == "empty":
        _reset_cache(source, out_path)
    else:
        assert not out_path.exists()

    result = _run_job(source, out_path, "--refresh-existing", "--cpu", "--top-k", "3")

    assert result.returncode == 0, result.stderr  # C1
    # A full scan over this source logs 9 and 8/9.
    assert _logged(result.stderr, r"total sources=(\d+)") == ("0",)  # C1
    assert _logged(result.stderr, r"done processed=(\d+)/(\d+)") == ("0", "0")  # C1
    conn = sqlite3.connect(out_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert {"similarity_sources", "similarity_items"} <= tables, tables  # C1
    assert _count(out_path, "similarity_sources") == 0  # C1
    assert _count(out_path, "similarity_items") == 0  # C1

```


Gate: satisfied

## 2026-09-30 - Step 7 - Phase 2 (Refresh selection) - red (audit round 1)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py` exited 1.

```
  tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py  3 failed                               0.0s
  ------------------------------------------------------------------
  total                                                               3 failed                               1.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-30 - Step 7 - Phase 2 (Refresh selection) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
`test_refresh_rewrites_exactly_cached_live_sources` fails at line 132 on `assert "mode=refresh-existing" in result.stderr`. The job has no `--refresh-existing` branch yet: it falls through to the full scan at precompute-similar-ann.py:465–473 and never logs that token. Both `test_refresh_over_missing_or_empty_cache_is_a_no_op[missing]` and `[empty]` fail at line 165 on `_logged(result.stderr, r"total sources=(\d+)") == ("0",)`, because the full scan logs `total sources=9`.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_precompute_similar_ann_refresh.py, which does not resolve (no such file). It was not read. Nothing in this test imports from it, so the stub question was answered from precompute-similar-ann.py and the test alone.
2. `fixtures_path` was not supplied. `ENGINE_PY` was resolved from tests/active/conftest.py:32. The module-scoped `source` fixture is defined in the test file itself.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (29 clauses: 10 must_prove, 15 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | each cached source still in `video_embeddings` is selected, and no other key is | :134 | a full scan (9), a left/outer join over the source, a join on `video_id` alone that picks up (v5, DOMAIN) (5) | CARRIED |
| C1b | must_prove | "that `build_query_batch` accepts": the length-skipped cached v9 is selected but not processed | :135 | processing or counting v9 as rewritten (4/4), dropping v9 before selection (3/3) | CARRIED |
| C1c | must_prove | "is rewritten": every one of v1-v3 is rewritten | :138 | skipping any of v1-v3, since its stamp stays `SENTINEL_AT` and the set then holds 2 values | CARRIED |
| C1d | must_prove | "the run's single new `computed_at`" | :138, :140 | a stamp per source, a kept sentinel stamp, a stamp from outside the run window | CARRIED |
| C1e | must_prove | "only fresh ranked items" | :142, :144, :145 | appending to the old items (ranks [1,1,2,3]), keeping `SENTINEL_TARGET`, a self-match, a target outside the live keys | CARRIED |
| C1f | must_prove | nothing is selected when the cache is missing | :165, :166, :171, :172 (`missing` param) | a fallback to a full scan when there is no cache file (9, 8/9) | CARRIED |
| C1g | must_prove | nothing is selected when the cache is schema-only | :165, :166, :171, :172 (`empty` param) | treating an empty `similarity_sources` as "refresh everything" | CARRIED |
| C2a | must_prove | a stale source (gone1, gone2) is left as it was | :146, with :147 showing the snapshot is non-trivial | deleting or pruning cache rows whose source left `video_embeddings` | CARRIED |
| C2b | must_prove | the empty-domain key (v5, "") is left as it was | :146 | a join on `video_id` alone that rewrites (v5, "") | CARRIED |
| C2c | must_prove | the length-skipped source v9 is left as it was | :146 | rewriting v9 with an empty item list, or clearing its items | CARRIED |
| C2d | must_prove | uncached embeddings gain no rows | :148, :149 | incremental or full-scan behaviour writing v4-v8, including (v5, DOMAIN) | CARRIED |
| D1 | docstring | "logs `mode=refresh-existing`" | :132 | a run that never announces or enters the mode | CARRIED |
| D2 | docstring | "4 total sources" | :134 | as C1a | CARRIED |
| D3 | docstring | "3/4 processed" | :135 | as C1b | CARRIED |
| D4 | docstring | "v1-v3 carry one `computed_at` stamped during the run" | :138, :140 | as C1d | CARRIED |
| D5 | docstring | "exactly three fresh items ranked 1..3" | :142, :144 | more or fewer than 3 items, stale items kept, gaps or duplicates in the ranks | CARRIED |
| D6 | docstring | "on other live keys" | :145 | a self-match, a dead or sentinel target | CARRIED |
| D7 | docstring | "the rest keep their snapshot rows and items" | :146 | any change to gone1, gone2, (v5, "") or v9 | CARRIED |
| D8 | docstring | "the uncached v4-v8 gain no rows" | :148 | as C2d | CARRIED |
| D9 | docstring | "7 sources remain" | :149 | pruning stale rows, or adding uncached ones | CARRIED |
| D10 | docstring | missing/schema-only: "exits 0" | :163 | refusing, or crashing, on a missing or empty cache | CARRIED |
| D11 | docstring | missing/schema-only: "0 total and 0/0 processed" | :165, :166 | as C1f/C1g | CARRIED |
| D12 | docstring | "leaves both cache tables in place" | :170 | deleting the out file, or never creating the schema over a missing cache | CARRIED |
| D13 | docstring | "writes no rows" / "present and empty" | :171, :172 | any row written on the no-op path | CARRIED |
| D14 | docstring | "runs as a child process under the engine's pixi interpreter" | :131, :163 via `_run_job` :76 | an in-process call that bypasses the CLI's argument handling | CARRIED |
| D15 | docstring | "a real FAISS index built by that interpreter" | :70 | a skipped or faked index build; a missing faiss fails instead of skipping | CARRIED |
| N1 | name | "refresh rewrites" | :138, :140, :142 | a refresh that leaves stamps or items unchanged | CARRIED |
| N2 | name | "exactly cached live sources" | :134, :146, :148, :149 | selecting too many (uncached, stale) or too few | CARRIED |
| N3 | name | "over missing or empty cache" | parametrize :152, branches :156-159 | covering only one of the two cache states | CARRIED |
| N4 | name | "is a no-op" | :165, :166, :171, :172 | any selection or write on those caches | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:128
   `result = _run_job(source, out_path, "--refresh-existing", "--cpu", "--top-k", "3")`
   Every call to `--refresh-existing` in this file is on the success path. The job's expected failure, refusing the flag when it is combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` (precompute-similar-ann.py:341-344), is never run. Whether another phase's test covers it cannot be told from this file.
2. whole-claim, context only (rules/testing.md): tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py:142
   `assert [rank for *_, rank in items] == [1, 2, 3], (key, items)  # C1`
   C1e counts as carried because it rules out stale, appended and self items. Nothing checks that rank order follows score, so ranks assigned in reverse score order would still pass. This is recorded because "ranked" can be read more strongly than "carries ranks 1..3". It does not block.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_precompute_similar_ann_refresh.py, and that path does not exist. Its contents, and any overlap with this test or with the abnormal path in Recommendation 1, were not assessed.
2. No `fixtures_path` was supplied, and no conftest.py covers tests/tmp/. The file imports `ENGINE_PY` straight from tests/active/conftest.py:32 and defines its own `source` fixture. Only that import was read from tests/active/conftest.py.

## 2026-09-30 - Step 7 - Phase 2 (Refresh selection) - checkpoint outcome (run 1)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py` exited 0 after the phase landed.

<changes>
### engine/server/db/jobs/precompute-similar-ann.py
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py  3 passed                               0.0s
  ------------------------------------------------------------------
  total                                                               3 passed                               1.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-30 - Step 7 - Phase 3 (Updater argv) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The updater's precompute stage builds its command through a module-level `similarity_precompute_cmd` in `updater-worker.py` that runs `--refresh-existing` in place of `--recreate-out-db`, and the CPU retry keeps that flag.

- C1 - For both `use_gpu` values, `similarity_precompute_cmd` returns the previous argv with `--recreate-out-db` replaced by `--refresh-existing`.
- C2 - `_to_cpu_cmd` applied to the GPU argv gives the CPU argv, keeping `--refresh-existing`.

must_prove:
- C1 - For both `use_gpu` values, `similarity_precompute_cmd` returns the previous argv with `--recreate-out-db` replaced by `--refresh-existing`.
- C2 - `_to_cpu_cmd` applied to the GPU argv gives the CPU argv, keeping `--refresh-existing`.

## 2026-09-30 - Step 7 - Phase 3 (Updater argv) - self-check (audit round 1, send-back 0)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:44 — for each `use_gpu` in {True, False} (parametrised ids `gpu`, `cpu`), `similarity_precompute_cmd(python_bin="python3", use_gpu=..., script_path, db_path, index_path, out_path)` with four distinct tmp_path Paths equals, as a list: `python3, <tmp>/jobs/precompute-similar-ann.py, --db, <tmp>/prod.db, --index, <tmp>/ann.faiss, --out, <tmp>/similarity-cache.db, --top-k, 1000, --nprobe, 16, --search-batch-size, 1024, --refresh-existing`, then `--gpu, --gpu-device, 0` or `--cpu`. - expected: Under the right implementation, each case returns exactly that list. The probe read the old literal out of `main` at updater-worker.py:1114-1130 with ast: `args.python_bin, (script_dir / 'precompute-similar-ann.py').as_posix(), '--db', prod_db.as_posix(), '--index', index_path.as_posix(), '--out', similarity_db.as_posix(), '--top-k', '1000', '--nprobe', '16', '--search-batch-size', '1024', '--recreate-out-db'`. The expected list is that literal with its last token swapped. The probe also saw `f"{tmp_path}/prod.db" == (tmp_path / "prod.db").as_posix()` → True. Today both cases are red with `AttributeError: module 'updater_worker_precompute' has no attribute 'similarity_precompute_cmd'` at line 42. - excludes: Four builders fail this comparison. (a) One that keeps `--recreate-out-db` and appends `--refresh-existing` reads `[..., '1024', '--recreate-out-db', '--refresh-existing', ...]`. (b) One that swaps db/out, or index/out, puts the wrong path in a slot, and the four paths are distinct so the lists differ. (c) One that drops or changes a tuning value, or puts `--refresh-existing` after the accelerator suffix, gives a different order. (d) One that ignores `use_gpu` returns the GPU suffix in the `cpu` case, or the reverse.
- C1 - tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:45 — `"--recreate-out-db" not in cmd`, for both `use_gpu` values. - expected: True in both cases under the right implementation. Its positive control is line 44 on the same `cmd`, which shows that the builder ran and returned the full argv. Today it is not reached, because line 42 raises AttributeError. - excludes: A builder that adds `--refresh-existing` but leaves the old destructive flag in the argv would contain `'--recreate-out-db'`, and this line would fail. It is the negative half of "replaced by", stated on its own so the failure message names the destructive flag.
- C2 - tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:54 — `_to_cpu_cmd(gpu_cmd)`, where `gpu_cmd` is the builder's `use_gpu=True` argv, equals `[python3, <script>, --db, <prod.db>, --index, <ann.faiss>, --out, <similarity-cache.db>, --top-k, 1000, --nprobe, 16, --search-batch-size, 1024, --refresh-existing, --cpu]`. It is armed by the control at line 52, which checks that `gpu_cmd[-3:] == ['--gpu', '--gpu-device', '0']`, because `run_with_cpu_fallback` retries only a command carrying `--gpu`. - expected: Exactly the CPU list. This was observed: the probe ran the real `_to_cpu_cmd` over the hand-built GPU list and it printed `['python3', '/tmp/pytest-of-enduser/pytest-6645/test_probe0/jobs/precompute-similar-ann.py', '--db', '.../prod.db', '--index', '.../ann.faiss', '--out', '.../similarity-cache.db', '--top-k', '1000', '--nprobe', '16', '--search-batch-size', '1024', '--refresh-existing', '--cpu']`. Today the test is red at line 50 with AttributeError, because the builder is missing. - excludes: Three cases fail here. (a) A change to `_to_cpu_cmd` that strips the non-GPU flags, or rebuilds the argv from a fixed template, drops `--refresh-existing`. (b) One that skips only `--gpu-device` and not its value leaves a stray `'0'`. (c) One that appends `--cpu` without the membership check, or keeps `--gpu`, produces a different list. Separately, a builder that ignored `use_gpu=True` and emitted `--cpu` would be caught by the line 52 control, not passed vacuously.

<assertions>
tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:44 - for each `use_gpu` in {True, False}, `similarity_precompute_cmd(python_bin="python3", ...)` given four distinct tmp_path Paths equals, token for token, a hand-written list: `python3, <script>, --db <prod.db>, --index <ann.faiss>, --out <similarity-cache.db>, --top-k 1000, --nprobe 16, --search-batch-size 1024, --refresh-existing`, then `--gpu --gpu-device 0` or `--cpu`. It is red today, because the probe saw no builder in the module, so the call raises AttributeError. A builder that keeps `--recreate-out-db`, swaps two paths, changes a tuning value, puts the flag somewhere else or gets the suffix wrong also fails the exact comparison - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:45 - `--recreate-out-db` is not in the builder's argv, for both `use_gpu` values. This is the negative half: it catches a builder that appends `--refresh-existing` but leaves the old flag in - C1
tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:52 - a precondition, not a clause: the GPU argv ends in `--gpu --gpu-device 0`. `run_with_cpu_fallback` only retries a command that carries `--gpu`, so without this line C2 would pass even if the builder ignored `use_gpu` and `_to_cpu_cmd` just returned its input - C2 (precondition)
tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:54 - `_to_cpu_cmd(gpu_cmd)` equals the hand-written CPU list: the same prefix with `--refresh-existing` in the same place, then a single trailing `--cpu`. It fails if the retry drops `--refresh-existing`, leaves the device value `0` behind, keeps `--gpu`, or adds `--cpu` twice - C2
tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:64 - the operator approved this extra guard for the Intent's call site. `main` in updater-worker.py, parsed with `ast`, calls `similarity_precompute_cmd`. It is red today: the probe listed `main`'s calls and the builder is not among them. It catches a builder that is added while `main` keeps its inline literal - Intent (call site)
tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:65 - also operator-approved: the module has no `"--recreate-out-db"` string constant anywhere. It is red today, because the probe found exactly one, at line 1129, which is `main`'s precompute literal - Intent (call site)
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/test_probe_25_p3.py", "-s"]. The probe loaded engine/server/db/jobs/updater-worker.py in-process with spec_from_file_location, with nothing else on sys.path; the module adds its own server dir. It printed:
- `has builder: False`. `similarity_precompute_cmd` does not exist yet, so C1 and C2 are red today with AttributeError.
- `tmp_path str==posix: True /tmp/pytest-of-enduser/pytest-6643/test_probe0`. So `f"{tmp_path}/..."` in the expected lists matches the `.as_posix()` strings the plan's builder produces.
- `to_cpu: ['python3', 's.py', '--db', 'd', '--index', 'i', '--out', 'o', '--top-k', '1000', '--nprobe', '16', '--search-batch-size', '1024', '--refresh-existing', '--cpu']`. The current `_to_cpu_cmd` keeps `--refresh-existing` in place and puts a single `--cpu` at the end. So the C2 expectation is the right target, and C2 is red today only because the builder is missing.
- `flag consts: [(1129, '--recreate-out-db')]`. That is the only `--recreate-out-db` string constant in the module: main's inline precompute literal.
- `main calls: [... 'run_with_cpu_fallback', 'systemctl_cmd', ...]`. There is no `similarity_precompute_cmd` in the list, so the call-site guard is red today.
Leftover: the probe file tests/tmp/test_probe_25_p3.py is still on disk because I have no delete tool. It should be removed; the checkpoint now covers everything it was used to check.
I did not run the checkpoint file itself. Its red state (AttributeError in the two builder tests, and line 64 failing) is taken from the probe output above.
</probes>

<unassertable>
none. The one requirement the agreed function-boundary checkpoint could not reach was the Intent's claim that the precompute stage builds its command through the builder, i.e. that `main` uses it. I asked with AskUser and the operator chose "Add a source-scan guard", so it is covered by the AST assertions at :64-65. That guard is structural: it proves the call is made and the old literal is gone, not what argv `main` passes at run time. It carries a `rat-tail:` comment naming its limit and how to replace it (a pipeline harness with the stage commands shimmed).
</unassertable>

### `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py` - 4127 characters, inlined in full

```
"""`updater-worker.py` builds its similarity precompute argv with `--refresh-existing` where it passed `--recreate-out-db`, and its CPU retry keeps that flag.

- `similarity_precompute_cmd` returns, token for token, the old precompute argv with `--refresh-existing` in the slot `--recreate-out-db` held, ending in `--gpu --gpu-device 0` or `--cpu`, and without `--recreate-out-db`.
- `_to_cpu_cmd` turns the GPU argv into exactly the CPU argv, `--refresh-existing` included.
- `main` calls `similarity_precompute_cmd`, and no `--recreate-out-db` literal is left anywhere in the module.

The module is loaded in-process from its file, the way `test_host_normalisation._load_job` does.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
UPDATER = JOBS_DIR / "updater-worker.py"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def updater():
    return _load_job("updater_worker_precompute", "updater-worker.py")


def _paths(tmp_path: Path) -> dict[str, Path]:
    # Four distinct paths, so a builder that swaps two of them fails the exact comparison.
    return {"script_path": tmp_path / "jobs" / "precompute-similar-ann.py", "db_path": tmp_path / "prod.db", "index_path": tmp_path / "ann.faiss", "out_path": tmp_path / "similarity-cache.db"}


@pytest.mark.parametrize(("use_gpu", "suffix"), [(True, ["--gpu", "--gpu-device", "0"]), (False, ["--cpu"])], ids=["gpu", "cpu"])
def test_updater_builds_refresh_command(updater, tmp_path: Path, use_gpu: bool, suffix: list[str]) -> None:
    """The builder's argv is the old literal token for token, with `--refresh-existing` where `--recreate-out-db` was and the accelerator suffix for `use_gpu`."""
    cmd = updater.similarity_precompute_cmd(python_bin="python3", use_gpu=use_gpu, **_paths(tmp_path))

    assert cmd == ["python3", f"{tmp_path}/jobs/precompute-similar-ann.py", "--db", f"{tmp_path}/prod.db", "--index", f"{tmp_path}/ann.faiss", "--out", f"{tmp_path}/similarity-cache.db", "--top-k", "1000", "--nprobe", "16", "--search-batch-size", "1024", "--refresh-existing", *suffix]  # C1
    assert "--recreate-out-db" not in cmd  # C1


def test_cpu_fallback_keeps_refresh(updater, tmp_path: Path) -> None:
    """`_to_cpu_cmd` over the GPU argv gives exactly the CPU argv, `--refresh-existing` still in its slot."""
    gpu_cmd = updater.similarity_precompute_cmd(python_bin="python3", use_gpu=True, **_paths(tmp_path))
    # `run_with_cpu_fallback` retries only a command carrying `--gpu`; without it the retry below is never taken.
    assert gpu_cmd[-3:] == ["--gpu", "--gpu-device", "0"], gpu_cmd

    assert updater._to_cpu_cmd(gpu_cmd) == ["python3", f"{tmp_path}/jobs/precompute-similar-ann.py", "--db", f"{tmp_path}/prod.db", "--index", f"{tmp_path}/ann.faiss", "--out", f"{tmp_path}/similarity-cache.db", "--top-k", "1000", "--nprobe", "16", "--search-batch-size", "1024", "--refresh-existing", "--cpu"]  # C2


def test_updater_main_uses_builder() -> None:
    """`main` calls `similarity_precompute_cmd`, and the module holds no `--recreate-out-db` string literal."""
    # rat-tail: a source scan, because reaching the precompute stage through `main` means running the whole crawl/merge/ANN pipeline; a pipeline harness with the stage commands shimmed would replace it.
    tree = ast.parse(UPDATER.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    called = {node.func.id for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

    assert "similarity_precompute_cmd" in called, sorted(called)  # Intent: call site
    assert "--recreate-out-db" not in {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}  # Intent: call site

```


Gate: satisfied

## 2026-09-30 - Step 7 - Phase 3 (Updater argv) - red (audit round 1)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py` exited 1.

```
  tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py  4 failed                               0.0s
  ------------------------------------------------------------------
  total                                                               4 failed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-30 - Step 7 - Phase 3 (Updater argv) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. single-value-pin (rules/shape.md) — tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:42 and :50
   cmd = updater.similarity_precompute_cmd(python_bin="python3", use_gpu=use_gpu, **_paths(tmp_path))
   `python_bin` only ever takes the value "python3" in this file. A builder that writes "python3" as a fixed value instead of passing the argument through would still pass. This is not Critical. The C1 and C2 clauses are about the flag swap and the accelerator suffix, and those are covered: `use_gpu` is tested at two values that give different outputs, and all four paths come from each test's own `tmp_path` and differ from each other. Fix: add a second `python_bin` value that differs from "python3" and from `sys.executable` (the `--python-bin` default at updater-worker.py:177).

PREDICTED FAILURE
All three tests fail. `test_updater_builds_refresh_command[gpu]` and `[cpu]` fail at line 42, and `test_cpu_fallback_keeps_refresh` fails at line 50, each with AttributeError: the loaded module has no `similarity_precompute_cmd` yet, because updater-worker.py:1114-1134 still builds the argv inline in `main`. `test_updater_main_uses_builder` fails on the assertion at line 64, `assert "similarity_precompute_cmd" in called`. If execution got past that line, line 68 would also fail on the `--recreate-out-db` literal at updater-worker.py:1129.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_updater_precompute_cmd.py, but that path doesn't exist, so it was not read.
2. `code_under_test` lists .un/skills/devsecops/config.json. It was not read because the test never references it.
3. `similarity_precompute_cmd` isn't defined anywhere in engine/server/db/jobs/updater-worker.py yet. So the stub question was answered from the assertion form alone. Lines 44 and 54 compare the whole argv to a fixed literal list, and line 45 adds a check that `--recreate-out-db` is absent. Lines 64 and 68 check the call site, and line 67 (`--gpu-device` in constants) checks the module's constants are actually scanned. With those assertions, a stub, a builder that returns the old argv, or a `main` left unchanged all fail.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (18 clauses: 2 must_prove, 13 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "for both `use_gpu` values" | :39 + :44 | a builder right for only one accelerator. The parametrize runs both, and each checks the exact suffix | CARRIED |
| C1b | must_prove | returns "the previous argv", every token kept | :44 | a dropped, reordered or changed token, or two path kwargs swapped (the four `_paths` values at :36 all differ). The literal matches the old inline argv at updater-worker.py:1114-1134 | CARRIED |
| C1c | must_prove | `--refresh-existing` in the slot `--recreate-out-db` held | :44 | the flag missing, appended after the suffix, or put anywhere other than just before the suffix | CARRIED |
| C1d | must_prove | `--recreate-out-db` replaced, not kept alongside | :44, :45 | a builder that adds `--refresh-existing` and keeps `--recreate-out-db`. The exact comparison already rules this out and :45 repeats it | CARRIED |
| C2a | must_prove | `_to_cpu_cmd`(GPU argv) gives the CPU argv | :50, :54 | GPU flags left in, `--cpu` missing or doubled, or any other token changed. The expected list at :54 is the same as the `cpu` case at :44 | CARRIED |
| C2b | must_prove | "keeping `--refresh-existing`" | :54 | a GPU argv whose layout makes the `--gpu-device` skip (updater-worker.py:370-372) drop `--refresh-existing` | CARRIED |
| D1 | docstring | module: "builds its similarity precompute argv with `--refresh-existing` where it passed `--recreate-out-db`" | :44 | same as C1c. Only the builder is checked. Nothing checks the arguments `main` passes to it (see Recommendation 1) | CARRIED |
| D2 | docstring | module: "its CPU retry keeps that flag" | :52, :54 | a GPU argv without `--gpu`, which the retry gate at updater-worker.py:387 would skip, and a retry that drops the flag | CARRIED |
| D3 | docstring | module: "token for token, the old precompute argv" | :44 | same as C1b | CARRIED |
| D4 | docstring | module: "ending in `--gpu --gpu-device 0` or `--cpu`" | :44 | a wrong suffix, or the suffix in the wrong position | CARRIED |
| D5 | docstring | module: "and without `--recreate-out-db`" | :45 | keeping the old flag next to the new one | CARRIED |
| D6 | docstring | module: "`_to_cpu_cmd` turns the GPU argv into exactly the CPU argv, `--refresh-existing` included" | :54 | same as C2a/C2b | CARRIED |
| D7 | docstring | module: "`main` calls `similarity_precompute_cmd`" | :64 | a `main` that keeps building the argv inline and never calls the builder | CARRIED |
| D8 | docstring | module: "no `--recreate-out-db` literal is left anywhere in the module" | :67, :68 | a leftover literal on some other code path. :67 shows the scan really reads the module's string constants | CARRIED |
| D9 | docstring | test_updater_builds_refresh_command: "old literal token for token … accelerator suffix for `use_gpu`" | :44 | same as C1a-C1c | CARRIED |
| D10 | docstring | test_cpu_fallback_keeps_refresh: "exactly the CPU argv, `--refresh-existing` still in its slot" | :54 | same as C2a/C2b | CARRIED |
| D11 | docstring | test_updater_main_uses_builder: "`main` calls `similarity_precompute_cmd`" | :64 | same as D7 | CARRIED |
| D12 | docstring | test_updater_main_uses_builder: "the module holds no `--recreate-out-db` string literal" | :68 | same as D8 | CARRIED |
| D13 | docstring | module: "loaded in-process from its file" | :22-31 | a fixture that imports some other copy of the module. The module-scoped fixture loads exactly updater-worker.py | CARRIED |
| N1 | name | "updater builds refresh command" | :44 | a builder that does not emit `--refresh-existing` | CARRIED |
| N2 | name | "cpu fallback keeps refresh" | :52, :54 | a retry argv without `--refresh-existing`, or a GPU argv the fallback would never retry | CARRIED |
| N3 | name | "updater main uses builder" | :64 | a `main` that never calls the builder | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:64
   `assert "similarity_precompute_cmd" in called, sorted(called)`
   D1 says the module "builds its similarity precompute argv" with the new flag. D7 is carried: `main` calls the builder. But no assertion checks what `main` passes in or what it hands to `run_with_cpu_fallback`. A `main` that calls the builder with `index_path` and `similarity_db` swapped, or that throws away the result, still passes. The claim is outside `must_prove`, so this is not a Critical. Either narrow the module docstring's first sentence to the builder, or accept that the call-site check carries it only partly.
2. bounds (rules/testing.md) — tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py:36
   Every argv expected at :44 and :54 is built with f-strings from `tmp_path`, while `main` builds paths with `.as_posix()` (updater-worker.py:1116-1122). The two only agree on POSIX paths. Nothing tests a path with spaces or other unusual characters. No rule requires those inputs for a list-form argv, so this is advisory only.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_updater_precompute_cmd.py (NEW), and that path does not exist.
2. `similarity_precompute_cmd` is not defined in engine/server/db/jobs/updater-worker.py yet. `main` still builds the argv inline at :1114-1134, including `"--recreate-out-db"` at :1129. I judged the builder's signature (`python_bin`, `use_gpu`, `script_path`, `db_path`, `index_path`, `out_path`) from the test alone. I checked the expected argv at :44 against the old inline literal.
3. I did not read .un/skills/devsecops/config.json. The test does not use it, and it has no bearing on the claims.

## 2026-09-30 - Step 7 - Phase 3 (Updater argv) - checkpoint outcome (run 1)

`tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py` exited 0 after the phase landed.

<changes>
### `engine/server/db/jobs/updater-worker.py`
- New module-level `similarity_precompute_cmd(*, python_bin, script_path, db_path, index_path, out_path, use_gpu) -> list[str]`. It sits after `systemctl_cmd` and uses the same keyword-only style. It returns the precompute argv the updater used to build inline, token for token. The one change is that `--refresh-existing` now takes the slot `--recreate-out-db` held. The argv ends in `--gpu --gpu-device 0` when `use_gpu` is true and `--cpu` otherwise (C1). Paths are passed through `.as_posix()`, as they were before.
- `main`'s precompute stage now gets `precompute_cmd` from `similarity_precompute_cmd(...)` and no longer builds the list and appends the accelerator flags itself. `run_with_cpu_fallback` still runs it. `_to_cpu_cmd` is unchanged: it drops only `--gpu` and `--gpu-device <n>`, so a CPU retry keeps `--refresh-existing` in place (C2). The module now contains no `--recreate-out-db` literal.

### `.un/skills/devsecops/config.json`
- Registered the test group `"test_updater_precompute_cmd.py": ["engine/server/db/jobs/updater-worker.py"]`. Phases 1–2 did the same for `test_precompute_similar_ann_refresh.py`: the group is registered now and the test file itself lands in `tests/active/` when the checkpoint is promoted.

### `tests/active/test_updater_precompute_cmd.py`
- Not created in this step. The step asked for production code only, and the checkpoint in `tests/tmp/` carries this phase. Following the phase 1–2 pattern, promoting it into `tests/active/` under this name is left to the promotion step. The checkpoint file was not touched.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py  4 passed                               0.0s
  ------------------------------------------------------------------
  total                                                               4 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-30 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py`

## 2026-09-30 - Step 8 - refactor pass

<refactors>
engine/server/db/jobs/precompute-similar-ann.py: the selection branch now checks the already-computed `mode` (`mode != "full"`, then `mode == "refresh-existing"`) and no longer re-tests `args.incremental or args.refresh_existing` and `args.refresh_existing`, so the logged mode and the SQL that runs come from the same value.
engine/server/db/jobs/precompute-similar-ann.py: rewrote the attach-block comment, which still said "Incremental mode" although the block now serves both incremental and refresh-existing. It is now one line covering both modes, where it used to be wrapped over three.
</refactors>

<left_out>
engine/server/db/jobs/updater-worker.py: nothing to refactor. `similarity_precompute_cmd` already matches the keyword-only style of `systemctl_cmd`, and `main` just calls it.
engine/server/db/jobs/precompute-similar-ann.py: left the `--recreate-out-db` and `--reset-only` unlink blocks alone. They are near-duplicates, but they were there before this build and merging them is outside this build's scope.
engine/server/db/jobs/precompute-similar-ann.py: left the one-line conflict-check comprehension as it is. It follows the no-softwrap rule and is checked before any output-file side effect; moving it into a helper would add indirection for a single caller.
Not run: I did not run the checkpoints myself (the workflow's run is the one that counts). The edit only swaps equivalent conditions, because `mode` is derived from exactly `args.refresh_existing` / `args.incremental` a few lines above.
Process gap, not a refactor: `tests/active/test_precompute_similar_ann_refresh.py` and `tests/active/test_updater_precompute_cmd.py` do not exist, although `config.json` already has test groups for both. The gating tests are still only in `tests/tmp/test_25_similarity_precompute_existing_sources_phase{1,2,3}.py`, so the promotion step still has to create them. The step's "{rat_tail_rules}" placeholder was also never filled in, so I measured the pass against the role's rules; no simplification in this build needed a `rat-tail:` comment.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
The three phases fit together without duplicated logic; the only cleanup was making the selection branch use the logged `mode` and fixing a comment that dated from before refresh-existing, and nothing needed new behaviour.
</observation>

## 2026-09-30 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 2 of 33 test groups (31 unchanged):
  test_host_normalisation.py — changed
  test_search_fusion.py — no map entry
  test_host_normalisation.py  19 passed                              0.1s
  test_search_fusion.py       10 passed                              2.0s
  --------------------------
  total                       29 passed                              2.2s wall, 2 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-30 - Step 9 - document triage

- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - Execution Order step 10 (line 53) says `Update similarity cache incrementally (precompute-similar-ann.py --incremental)`. That is false: the updater now runs `precompute-similar-ann.py --refresh-existing` (built by `similarity_precompute_cmd`, which keeps the flag on the GPU→CPU retry). Rewrite step 10 to say that it refreshes the similarity cache in place with `--refresh-existing`. It rewrites only sources already in `similarity_sources` that are still in `video_embeddings`. Videos new from the merge are cached lazily by the Engine the first time they are requested. Cached sources no longer in embeddings are left in place, and only the stale-host purge removes rows. Add one sentence saying that a missing or empty cache stays empty (schema only, 0 sources, the stage still succeeds), and point to `DATA_BUILD.md` §5 / `scripts/run-dataset-build.sh` for the initial full build. The goals line "refresh popularity/similarity data" (line 14) and Outputs "Updated similarity cache" (line 28) stay true.
- [ ] `DATA_BUILD.md` - §5 "Precompute similarity cache" documents only the full-build example and `--top-k`, and nothing about `--refresh-existing`, which the updater now depends on. After the example, add a short flag note. `--recreate-out-db`: delete and recreate the output file (the full build, as used by the example and `run-dataset-build.sh`). `--reset`: clear the cache tables before computing. `--reset-only`: clear them and exit. `--incremental`: compute only embeddings not yet in `similarity_sources`. `--refresh-existing`: recompute only sources already in `similarity_sources` that are still in `video_embeddings`, leave all other cache rows untouched, and select nothing on a missing or empty cache. It cannot be combined with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db`; argparse rejects that combination with exit 2 before the output file is touched. Leave the example block and the `--top-k` paragraph as they are. Line 30 also points at `engine/server/db/jobs/UPDATER_WORKER.md`. That path is wrong: the file is `engine/server/db/jobs/docs/UPDATER_WORKER.md`. Fix it in the same edit, since readers follow that link to find the updater's precompute mode. Line 24's stage list is still accurate.
- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` - The Purpose list (line 16) claims the smoke test validates an "incremental similarity precompute". After this build, each smoke run starts with no `similarity-cache.db`, and the updater's `--refresh-existing` stage only creates the schema and processes 0 sources. So the smoke test no longer exercises the precompute's FAISS search or write path, and its `similarity_precompute` stage duration is not a precompute timing. The plan left this line alone because it was already inaccurate, but the sentence is now materially false about what the test covers. Reword it to say that the similarity precompute stage runs in `--refresh-existing` mode against the run's fresh, empty cache: it checks that the stage runs and produces a schema-only cache, not that similarities are computed. This is a single-line change; the operator may decline it.
- [ ] `docs/project/issues/24-similarity-cache-shadow-swap.md` - Two statements are now false after issue 25. Proposed solution line 15 says the shadow build runs `precompute-similar-ann.py --incremental`. The updater's mode is now `--refresh-existing`, so change that line. The Agent Brief's Current behavior (line 60) says the precompute runs into the active cache "(recreating it)". It now refreshes the cached sources in place without recreating the file, so change that too. The triage bullet at line 45 ("runs with `--recreate-out-db`") is a dated triage observation. Leave it, and add a short comment under `## Comments` saying 25 is delivered, the updater's precompute stage runs `--refresh-existing` through `similarity_precompute_cmd` in `updater-worker.py`, and so the shadow build wires that mode. The comment should also note that refresh never deletes sources, so the gate's "no fewer `similarity_sources` rows" check still holds.
- [ ] `docs/project/issues/25-similarity-precompute-existing-sources.md` - Delivered. Set `Status:` to `complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md` / `issue-tracker.md`. Add a comment covering four points. `--refresh-existing` landed with its conflict check. The updater uses it. New videos are cached lazily at serve time and stale sources are left in place. The validation item "Updater stage time drops against the full-rebuild baseline" is an operator measurement on main after the merge (the smoke test's `similarity_precompute` duration no longer measures precompute work, because the smoke cache is empty), not an automated gate.

Out of scope:
- [ ] `DEPLOYMENT.md` - The updater-timer paragraph (lines 130-134) says only that the updater "precomputes similarity" and stops/starts the Engine around the write-critical stages. Both are still true, because the stop/start sequence is unchanged. The line 263 note about `--top-k 20` describes the dataset build and was already inconsistent with the updater's `--top-k 1000`. This build did not change that inconsistency, and it is out of scope.
- [ ] `docs/project/adr/0008-similarity-cache-handoff-through-files.md` - This ADR decides how a shadow-built cache is handed to running Engines (the build marker, reopen by inode, the pre-swap gate). None of that is built yet, and nothing in it names a precompute mode. Refresh never deletes sources, so the "no fewer sources than the active file" gate stays consistent.
- [ ] `docs/project/adr/0006-derived-ann-ids.md` - Its only claim here is that the similarity cache is keyed by `(video_id, instance_domain)`. That is still true, and the refresh join uses exactly that key.
- [ ] `CONTEXT.md` - The glossary entries `Shadow build` and `Build marker` describe issue 24's design. They do not name a precompute mode, and this build does not affect them.
- [ ] `docs/project/issues/08-stable-ann-ids.md` - Line 19 says precompute moves to `ann_id` and "incremental selection stays logical-key based". The new refresh selection is also keyed on the logical `(video_id, instance_domain)`, so the statement holds. The extra rowid join site is recorded in the plan and inventory for issue 08's implementer; it is not a false claim in the issue.
- [ ] `docs/project/issues/plan.md` - Row 82 lists the two code files this build touched, and line 125 already orders 25 before 24. Nothing in it describes the precompute mode.

ADR conflicts: none

## 2026-09-30 - Step 9 - Update documentation

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

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** - while updating `docs/project/issues/25-similarity-precompute-existing-sources.md`: docs/project/issues/archive/25-similarity-precompute-existing-sources.md — new file. The delivered issue has to move into archive/ (issue-tracker.md: "move the file to docs/project/issues/archive/"). This is the updated document at its new path.
docs/project/issues/25-similarity-precompute-existing-sources.md — STILL NEEDS REMOVING (`git rm`), which finishes the move. I have no tool that deletes files, so it is unchanged and repeats the archived copy.

**ADR conflicts.** none

### `engine/server/db/jobs/docs/UPDATER_WORKER.md`

<changes>
Rewrote Execution Order step 10 to describe the in-place `--refresh-existing` precompute and replace the incorrect `--incremental` claim.

- Step 10 now reads "Refresh the similarity cache in place (`precompute-similar-ann.py --refresh-existing`)". It has four sub-bullets:
  - Only sources already in `similarity_sources` that are still in `video_embeddings` are recomputed and rewritten.
  - Videos new from the merge get no entry in this stage. The Engine caches each one the first time it is requested.
  - Cached sources that are no longer in `video_embeddings` stay in the cache. Only the stale-host purge removes cache rows.
  - A missing or empty cache stays empty (schema only, 0 sources), and the stage still succeeds. The initial full build is `scripts/run-dataset-build.sh`, and the bullet points to `DATA_BUILD.md` §5 for it.
- I checked these claims against the code:
  - `similarity_precompute_cmd` in `updater-worker.py` puts `--refresh-existing` in the argv, and `_to_cpu_cmd` keeps it.
  - The inner-join selection is at `precompute-similar-ann.py` lines 454–462.
  - `ensure_schema` uses `executescript` and runs before the read-only ATTACH.
  - `purge_hosts` deletes from `similarity_db`.
- Everything outside step 10 is unchanged. Line 14 ("refresh popularity/similarity data") and the Outputs line "Updated similarity cache" are still accurate.
- I found an existing inaccuracy outside this build's scope and left it as it is. The "GPU/CPU Mode" section says `--gpu` has "no CPU fallback", but `run_with_cpu_fallback` retries the ANN build and the precompute on CPU.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `DATA_BUILD.md`

<changes>
DATA_BUILD.md §5 now lists the precompute cache-mode flags, including `--refresh-existing` and the flags it can't be combined with. The broken link to UPDATER_WORKER.md is fixed.

- **§5 "Precompute similarity cache":** added a "Cache modes" list after the output-size line.
  - `--recreate-out-db`: the full build, which `scripts/run-dataset-build.sh` uses.
  - `--reset` and `--reset-only`: clear the cache tables; `--reset-only` then exits without computing.
  - `--incremental`: computes only embeddings not yet in `similarity_sources`.
  - `--refresh-existing`: recomputes only cached sources that are still in `video_embeddings` and leaves every other row alone. On a missing or empty cache it creates the schema and processes 0 sources. Combining it with `--incremental`, `--reset`, `--reset-only` or `--recreate-out-db` is rejected by argparse with exit code 2 before the output file is touched.
  - The entry says the updater uses this mode and points to UPDATER_WORKER.md for how the updater runs it, rather than repeating it here.
- **Link fix:** the "Automatic background updater" section pointed at `engine/server/db/jobs/UPDATER_WORKER.md`, which doesn't exist. It now points at `engine/server/db/jobs/docs/UPDATER_WORKER.md`.
- **Left as they were:** the example command block, the `--top-k` paragraph and the updater stage list.
- **Checked against the code:** the flag help texts and conflict check in `precompute-similar-ann.py` (lines 323–346), the join and read-only attach (lines 443–476), and `--recreate-out-db` in `run-dataset-build.sh` (line 257).
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`

<changes>
Reworded the Purpose bullet on similarity precompute so it matches what the smoke test covers: the `--refresh-existing` stage runs against an empty cache and leaves only the schema.

- Line 16 said the test validates an "incremental similarity precompute". It now says the smoke test runs the similarity precompute stage in `--refresh-existing` mode against the run's fresh, empty similarity cache. It checks that the stage runs and leaves a schema-only cache, not that similarities are computed.
- I checked this against `test-orchestrator-smoke.py`. `paths["similarity_db"]` is a path inside the per-run (or per-scenario) directory, and nothing copies a cache into it; only the prod DB is copied. The only check on it is `validate_outputs`, which confirms the file exists. So a smoke run starts with no cache, and the updater's `--refresh-existing` stage selects 0 sources.
- Nothing else in the file changed. The rest of the Purpose list, the failure scenarios (including `after_merge_before_similarity`) and the Artifacts section ("ANN/similarity outputs") are still accurate.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/24-similarity-cache-shadow-swap.md`

<changes>
Issue 24 now names `--refresh-existing` as the updater's precompute mode, and I added a comment recording that issue 25 is delivered.

- **Proposed solution, Shadow build (line 15):** the shadow build now runs `precompute-similar-ann.py --refresh-existing` against the copy, not `--incremental`. The reason in brackets for copying the active cache now reads "keeps the cached sources to refresh" instead of "keeps the incremental baseline".
- **Agent Brief, Current behavior (line 60):** the precompute now "runs with `--refresh-existing` against the active `similarity-cache.db` (rewriting its cached sources in place)", replacing "(recreating it)".
- **New comment, `### Issue 25 delivered`, after the Triage block under `## Comments`:** the updater's precompute stage runs `--refresh-existing`, built by `similarity_precompute_cmd` in `engine/server/db/jobs/updater-worker.py`, so the shadow build uses that mode. Refresh never deletes a source, so the gate's "no fewer `similarity_sources` rows" check still holds.
- **Left as they were:** the triage bullet at line 45 ("runs with `--recreate-out-db`"), the `--incremental` remark at line 46 and the "Settle at triage" line in Related. All three are dated triage notes.
- **Checked against the code:** `similarity_precompute_cmd` in `updater-worker.py` puts `--refresh-existing` in the argv, and `main` calls it for the precompute stage.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/25-similarity-precompute-existing-sources.md`

<changes>
Closed issue 25 as delivered. The archive copy has `Status: enhancement, complete` and a `### Delivered` comment, but I couldn't remove the original file.

- **New file:** `docs/project/issues/archive/25-similarity-precompute-existing-sources.md`. Its body is the original's word for word, except for the `Status:` line and the new comment. This follows the archived issue 23.
- **Original not removed:** I have no tool that deletes files, so `docs/project/issues/25-similarity-precompute-existing-sources.md` is still there with its old contents. Until someone runs `git rm` on it, the issue exists in two places.
- **The comment** links the plan `docs/project/plans/19-25-similarity-precompute-existing-sources.md`. The commit is written as `<pending>`, as in issue 23. It covers the four points the checklist asked for:
  - **What landed:** the `--refresh-existing` mode (an inner join on `(video_id, instance_domain)`, with one `computed_at` for the whole run), and the conflict check. The check rejects `--incremental`, `--reset`, `--reset-only` and `--recreate-out-db` with exit 2 before the output file is touched.
  - **Updater:** it uses the mode through `similarity_precompute_cmd`, and the GPU→CPU retry keeps the flag.
  - **Scope:** new videos are cached the first time they are requested, and stale sources stay in the cache rather than being removed.
  - **Stage time:** the speed-up is measured by the operator on main after the merge; no automated test checks it. The smoke test's `similarity_precompute` duration can't stand in for that figure, because the smoke run's cache is empty.
- **Not restated:** for flag details and the updater stage, the comment points to `DATA_BUILD.md` §5 and `engine/server/db/jobs/docs/UPDATER_WORKER.md`.
- **Checked against the code:** the flag and its conflict message in `precompute-similar-ann.py` at lines 335–344, the inner-join selection at lines 443–471, and `similarity_precompute_cmd` passing `--refresh-existing` in `updater-worker.py` at lines 415–440.
</changes>

<not_on_checklist>
docs/project/issues/archive/25-similarity-precompute-existing-sources.md — new file. The delivered issue has to move into archive/ (issue-tracker.md: "move the file to docs/project/issues/archive/"). This is the updated document at its new path.
docs/project/issues/25-similarity-precompute-existing-sources.md — STILL NEEDS REMOVING (`git rm`), which finishes the move. I have no tool that deletes files, so it is unchanged and repeats the archived copy.
</not_on_checklist>

## 2026-09-30 - Step 10 - Harvest tests - plan approved

Approved by the operator.

<harvest_file>
docs/project/plans/harvest-25-similarity-precompute-existing-sources-plan.md
</harvest_file>

<plan>
**Harvest plan: build 25 (similarity precompute existing sources)**

Scope is the three checkpoint files in `tests/tmp`, with 7 test functions between them. The build's other probe files stay where they are. The config check found no defaulted keys and no conflicts. The record is saved as `tests/last_test_validation.json.preharvest`. All three files collected and passed during the build, so none needed a collection check.

**Count per verdict**
- `DURABLE`: 6
- `REDUNDANT`: 1
- `REPLACES`: 0
- `COMBINE`: 0
- `SPENT`: 0

**Tests to move (`DURABLE`)**

| Test | From | Destination |
|---|---|---|
| `test_refresh_rejects_each_destructive_flag` (4 flags × seeded/absent) | phase1 | `tests/active/test_precompute_similar_ann.py` |
| `test_refresh_rewrites_exactly_cached_live_sources` | phase2 | `tests/active/test_precompute_similar_ann.py` |
| `test_refresh_over_missing_or_empty_cache_is_a_no_op` (missing/empty) | phase2 | `tests/active/test_precompute_similar_ann.py` |
| `test_updater_builds_refresh_command` (gpu/cpu) | phase3 | `tests/active/test_updater_worker.py` |
| `test_cpu_fallback_keeps_refresh` | phase3 | `tests/active/test_updater_worker.py` |
| `test_updater_main_uses_builder` | phase3 | `tests/active/test_updater_worker.py` |

Nothing in `tests/active` tests `precompute-similar-ann.py`. The only active test that loads `updater-worker.py` is `test_host_normalisation.py`, and it checks nothing but host normalisation. So none of these six is already covered.

**Please decide on `test_updater_main_uses_builder`.** It reads the source code of `updater-worker.py` rather than running it, and its author marked it as a stopgap. Without it, though, nothing in the durable suite would notice if `main` went back to building the command itself with `--recreate-out-db`, which is the regression this build exists to prevent. I classed it `DURABLE`. The alternative is `SPENT`, which accepts that gap until a test that drives the whole pipeline exists.

**Not moved**
- `test_refresh_alone_is_not_refused` (phase1) is `REDUNDANT`. The phase2 test `test_refresh_over_missing_or_empty_cache_is_a_no_op[missing]` runs the same `--refresh-existing --cpu` command and checks more (exit 0 and both tables present). This test only guarded an in-between state that phase 2 replaced.

**Active tests retired:** none. No `REPLACES` or `COMBINE`, so nothing goes to `tests/archive`.

**New subject files Step 5 would create** (each is a new test group and needs a new map entry)
- `tests/active/test_precompute_similar_ann.py` for `precompute-similar-ann.py`. It gets phase2's module fixture (source DB, FAISS index, sidecar), its constants and helpers, plus phase1's `DESTRUCTIVE_FLAGS`, `ERROR_PREFIX`, `_source_db` and `_error_lines`. The two `_run_job` helpers become one that takes the source directory, and the two equivalent `_seed_cache` copies become one.
- `tests/active/test_updater_worker.py` for `updater-worker.py`. It gets `_load_job`, the `updater` fixture and `_paths`.

**The file names differ from what the build registered.** The build added `test_groups` entries for `test_precompute_similar_ann_refresh.py` and `test_updater_precompute_cmd.py`, but neither file exists. The harvest workflow says a subject file is named after its production script and nothing else, as `test_precompute_random_rowids.py` is. So this plan uses `test_precompute_similar_ann.py` and `test_updater_worker.py` and replaces those two entries. If you'd rather keep the build's names, say so.

**`test_groups` changes** (in `.un/skills/devsecops/config.json`)
- Remove `test_precompute_similar_ann_refresh.py`.
- Add `test_precompute_similar_ann.py` → `engine/server/db/jobs/precompute-similar-ann.py`, `engine/server/data/embedding_space.py`
- Remove `test_updater_precompute_cmd.py`.
- Add `test_updater_worker.py` → `engine/server/db/jobs/updater-worker.py`

After Steps 5 to 8, all three checkpoint files move to `delete_me/`. Each moved test will be checked by breaking the production code once and confirming it fails.
</plan>

## 2026-09-30 - Step 10 - Harvest tests

<moved>
I moved six test functions (15 test cases) into two new subject files, each its own new group, and updated the harvest record.
- `tests/tmp/test_25_similarity_precompute_existing_sources_phase1.py::test_refresh_rejects_each_destructive_flag` (8 cases) → `tests/active/test_precompute_similar_ann.py`, group `test_precompute_similar_ann.py`
- `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py::test_refresh_rewrites_exactly_cached_live_sources` → `tests/active/test_precompute_similar_ann.py`, group `test_precompute_similar_ann.py`
- `tests/tmp/test_25_similarity_precompute_existing_sources_phase2.py::test_refresh_over_missing_or_empty_cache_is_a_no_op` (missing/empty) → `tests/active/test_precompute_similar_ann.py`, group `test_precompute_similar_ann.py`
- `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py::test_updater_builds_refresh_command` (gpu/cpu) → `tests/active/test_updater_worker.py`, group `test_updater_worker.py`
- `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py::test_cpu_fallback_keeps_refresh` → `tests/active/test_updater_worker.py`, group `test_updater_worker.py`
- `tests/tmp/test_25_similarity_precompute_existing_sources_phase3.py::test_updater_main_uses_builder` → `tests/active/test_updater_worker.py`, group `test_updater_worker.py`
- Not moved: `test_refresh_alone_is_not_refused` (phase1), `REDUNDANT` as the approved plan says.
- **Setup code carried over:** in `test_precompute_similar_ann.py`, one `_run_job(source, out_path, *args)` and one `_seed_cache` now serve all three tests, replacing the two copies of each. Phase2's `source` fixture, constants and helpers came over, plus phase1's `DESTRUCTIVE_FLAGS`, `ERROR_PREFIX`, `_source_db` and `_error_lines`. In `test_updater_worker.py`, `_load_job`, the `updater` fixture and `_paths` came over. `ENGINE_PY` and `ROOT` are imported from `conftest`. Nothing is shared between the two groups.
- **Docstrings:** they now state the rules the tests gate, and the phase and `C1`/`C2` tags are gone.
- **Harvest record:** `docs/project/plans/harvest-25-similarity-precompute-existing-sources-plan.md` now has sections for the approval and Steps 5–8.
</moved>

<retired>
none
</retired>

<group_map>
Two entries changed in `test_groups` in `.un/skills/devsecops/config.json`. Neither old entry had a file behind it.
- `test_precompute_similar_ann_refresh.py` removed; `test_precompute_similar_ann.py` added → `engine/server/db/jobs/precompute-similar-ann.py`, `engine/server/data/embedding_space.py`
- `test_updater_precompute_cmd.py` removed; `test_updater_worker.py` added → `engine/server/db/jobs/updater-worker.py`
- `--audit-map` exits 0, both right after the edit and again after Step 8.
- For the new files it lists three advisory MISSING items, which I did not add to the map. `engine/server/data/time.py` is imported but not tested. `engine/server/db/similarity-cache.db` appears only as a path string. The updater test names `precompute-similar-ann.py` only in a path string.
</group_map>

<mutations>
Each of the six mutations made its test fail on the assertion it was moved for, and the test passed again after the restore. Backups went to `delete_me/<script>.bak-h25-mN`, outside the production tree. After each restore `diff` against the backup was empty. At the end `cmp` matched every backup against the live file, and no `.bak` file is left under `engine/`.
- m1 `precompute-similar-ann.py`, conflict guard disabled (`if conflicts:` → `if False and conflicts:`) → `test_refresh_rejects_each_destructive_flag`: all 8 cases failed at `assert result.returncode == 2` (the job exited 1) → after restore, 8 passed.
- m2 `precompute-similar-ann.py`, refresh join matched on `video_id` only (dropped `AND s.instance_domain = e.instance_domain`) → `test_refresh_rewrites_exactly_cached_live_sources`: failed at the `total sources` check, `('5',) == ('4',)` → after restore, passed.
- m3 `precompute-similar-ann.py`, refresh falls through to the full scan (`if mode != "full":` → `if mode == "incremental":`) → `test_refresh_over_missing_or_empty_cache_is_a_no_op`: both cases failed at the `total sources` check, `('9',) == ('0',)` → after restore, 2 passed.
- m4 `updater-worker.py`, `similarity_precompute_cmd` emits `--recreate-out-db` instead of `--refresh-existing` → `test_updater_builds_refresh_command`: both cases failed at the exact argv comparison, index 14 `'--recreate-out-db' != '--refresh-existing'` → after restore, 2 passed.
- m5 `updater-worker.py`, `_to_cpu_cmd` also strips `--refresh-existing` → `test_cpu_fallback_keeps_refresh`: failed at the `_to_cpu_cmd(gpu_cmd) == [...]` comparison, index 14 `'--cpu' != '--refresh-existing'` → after restore, passed.
- m6 `updater-worker.py`, `main` builds the precompute argv itself with `--recreate-out-db` instead of calling the builder → `test_updater_main_uses_builder`: failed at `assert "similarity_precompute_cmd" in called` → after restore, passed.
</mutations>

<cleared>
Nothing was deleted; the files below are in `delete_me/` for you to review and remove.
- **This harvest added nine files to `delete_me/`:**
  - The three checkpoint files: `test_25_similarity_precompute_existing_sources_phase1.py`, `test_25_similarity_precompute_existing_sources_phase2.py` and `test_25_similarity_precompute_existing_sources_phase3.py`. None of their names clashed with a file already there.
  - The six mutation backups: `precompute-similar-ann.py.bak-h25-m1` to `-m3`, and `updater-worker.py.bak-h25-m4` to `-m6`.
  - `delete_me/` went from 175 to 184 entries.
- **`tests/tmp`:** none of the three checkpoint files remain. The build's out-of-scope probe files are still there, as the plan says.
- **Final counts:**
  - Verdicts: 6 `DURABLE` moved (15 cases), 1 `REDUNDANT` left out, 0 retired.
  - Closing run: I moved `tests/last_test_validation.json.preharvest` back over the record, then ran `--compare`. It selected 3 of 35 groups: the two new groups, plus `test_search_fusion.py` (10 passed), which runs because it already had no map entry before this build. The other 32 groups were unchanged and not re-run. All 25 tests that ran passed.
  - Against the pre-harvest record: 15 appeared (11 in `test_precompute_similar_ann.py`, 4 in `test_updater_worker.py`), 0 departed, 0 new failures, 0 failures that now pass.
</cleared>

`--audit-map` exited 0.
Files still in tests/tmp: ['tests/tmp/test_probe_25_p3.py', 'tests/tmp/test_probe_25_p2.py', 'tests/tmp/test_probe_25_p1.py', 'tests/tmp/test_probe_step8_exclude_500.py', 'tests/tmp/test_probe_36_refactor_equivalence.py', 'tests/tmp/test_probe_36_p4.py', 'tests/tmp/test_probe_36_p3_impl.py', 'tests/tmp/test_probe_36_p3.py', 'tests/tmp/test_probe_36_p2.py', 'tests/tmp/test_probe_36_p1.py', 'tests/tmp/test_probe_phase4_gate.py', 'tests/tmp/test_probe_22_p4.py']

`--compare` exited 0.

```
selected 1 of 35 test groups (34 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

