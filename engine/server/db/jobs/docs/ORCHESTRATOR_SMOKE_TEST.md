# Orchestrator Smoke Test

This document describes how to run and interpret
`engine/server/db/jobs/tests/test-orchestrator-smoke.py`.

## Purpose

The smoke test validates the full updater pipeline on a temporary mini-prod DB:

- staging init + seed from prod snapshot,
- crawler steps (`instances`, `channels`, `videos`, `channels-videos-count`),
- embeddings build,
- merge from staging into mini-prod,
- incremental popularity recompute,
- full ANN build,
- service start (skipped unless `--use-systemctl`),
- trending stage: `fetch-trending.py` against mini-prod, which makes real HTTPS requests to every host embedded in mini-prod and writes `trending_ranks` there. A host that fails or is unreachable does not fail the run. For the stage itself see `UPDATER_WORKER.md`.
- similarity stage: a shadow build of `similarity-cache.next.db` in `--refresh-existing` mode, gated and swapped in as the active cache. The run starts with no cache, so the swap creates a schema-only active cache and writes no `similarity-cache.prev.db`. It checks that the stage runs, not that similarities are computed. For the stage itself see `UPDATER_WORKER.md`.

It also runs failure-injection scenarios by default to verify:

- lock file release,
- DB integrity,
- expected behavior before/after merge boundaries.

## What It Uses

- Source DB (`--source-db`): default from `server_config.DEFAULT_DB_PATH`. It must already be migrated by `migrate-whitelist.py`, because mini-prod copies its `video_embeddings` DDL and then refuses a table without `ann_id` with the migrate-whitelist message. In a worktree that default is main's live `whitelist.db` through the symlink, so migrate it from main as `DATA_BUILD.md` describes.
- Mini-prod schema: the table and index DDL of `instances`, `channels`, `videos` and `video_embeddings`, plus the `ann_id` UNIQUE index and collision trigger, so the merge runs guarded on `ann_id` rows. No other triggers are copied.
- Test instances list: `engine/server/db/jobs/tests/test-instances.json`
- Temporary workdir: `tmp/orchestrator-smoke/<run-id>/`
- Local whitelist JSON server (generated inside workdir)

The generated whitelist JSON is JoinPeerTube-like:

```json
{
  "total": 3,
  "data": [
    { "host": "example.org" }
  ]
}
```

Source hosts are taken from `engine/server/db/jobs/tests/test-instances.json`.

## Quick Start

Run with GPU (default mode):

```bash
./venv/bin/python3 engine/server/db/jobs/tests/test-orchestrator-smoke.py --keep-workdir
```

Run CPU-only:

```bash
./venv/bin/python3 engine/server/db/jobs/tests/test-orchestrator-smoke.py --cpu --keep-workdir
```

Run with real systemd stop/start during test:

```bash
./venv/bin/python3 engine/server/db/jobs/tests/test-orchestrator-smoke.py --use-systemctl --keep-workdir
```

## Common Limits (for faster test runs)

```bash
./venv/bin/python3 engine/server/db/jobs/tests/test-orchestrator-smoke.py \
  --keep-workdir \
  --max-instances 3 \
  --max-channels 30 \
  --max-videos-pages 1 \
  --seed-videos-limit 2000 \
  --concurrency 4 \
  --nlist 256
```

## Key Flags

- `--gpu` / `--cpu`
- `--keep-workdir`
- `--skip-failure-checks`
- `--use-systemctl`
- `--max-instances`
- `--max-channels`
- `--max-videos-pages`
- `--seed-videos-limit`
- `--nlist`

Run `--help` for full list:

```bash
./venv/bin/python3 engine/server/db/jobs/tests/test-orchestrator-smoke.py --help
```

## Artifacts

By default, the latest report is always written to:

- `tmp/orchestrator-smoke/last-report.json`

When `--keep-workdir` is set, per-run artifacts remain in:

- `tmp/orchestrator-smoke/<run-id>/report.json`
- `tmp/orchestrator-smoke/<run-id>/smoke.log`
- `tmp/orchestrator-smoke/<run-id>/worker.log`
- `tmp/orchestrator-smoke/<run-id>/whitelist-http.log`
- mini-prod/staging DB and ANN/similarity outputs

## Pass / Fail

PASS means:

- required pipeline markers found in worker log,
- ANN meta total matches DB embeddings count,
- ANN meta `id_source` is `video_embeddings.ann_id` (recorded as `checks.ann_id_source` in the report),
- merge-rule invariants hold (`INSERT_ONLY`, `INSERT_OR_REPLACE`),
- no duplicate key groups for merge keys,
- lock file is released,
- SQLite integrity check is `ok`,
- no `similarity-cache.next.db`, `similarity-cache.next.db-journal` or `similarity-cache.db.building` remains after the success run or after any failure scenario,
- no `similarity-cache.prev.db` exists after the success run,
- failure scenarios behave as expected (unless skipped).

Failure scenarios included by default:

- `before_merge`
- `during_ann_build`
- `after_merge_before_similarity`
- `similarity_gate` (`--fail-similarity-gate`): the active similarity cache must be byte-identical afterwards, which in practice means it is still absent.

How to read `db_unchanged` in failure scenarios:

- `before_merge`: should stay `true` (no merge happened yet).
- `during_ann_build`, `after_merge_before_similarity` and `similarity_gate`: may be `false` (merge already happened).

FAIL means report contains `status: "fail"` and `error`.

## GPU / CPU Verification

When running `--gpu`, verify logs contain:

- embeddings step with `device=cuda`
- ANN step with `mode=gpu`

When running `--cpu`, verify logs contain:

- embeddings step with `device=cpu`
- ANN step with `mode=cpu`

## Notes

- This test works against a temporary mini-prod DB copy, not real production DB.
- If you use `--use-systemctl`, test can stop/start the configured service.
- Keep `--nlist` safely below the available embedding count in mini DB.
- First files to inspect after run:
  - `tmp/orchestrator-smoke/last-report.json`
  - `tmp/orchestrator-smoke/<run-id>/report.json`
  - `tmp/orchestrator-smoke/<run-id>/smoke.log`
  - `tmp/orchestrator-smoke/<run-id>/worker.log`
