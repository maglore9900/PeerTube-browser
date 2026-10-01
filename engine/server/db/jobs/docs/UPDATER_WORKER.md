# Updater Worker

This document describes how `engine/server/db/jobs/updater-worker.py` works.

## Purpose

`updater-worker.py` is a background pipeline that refreshes the production dataset.
It uses a staging database, merges changes into prod, then rebuilds derived artifacts.

Main goals:
- fetch new instances/channels/videos,
- compute embeddings for new content,
- merge staging into prod with merge rules,
- refresh popularity data,
- rebuild ANN index for prod,
- rebuild the similarity cache in a shadow file and swap it in while the API serves.

## Inputs and Outputs

Inputs:
- Prod DB: `engine/server/db/whitelist.db` (default)
- Merge rules: `engine/server/db/jobs/merge_rules.json`
- Crawler CLIs from `engine/crawler/dist/*.js`
- Python jobs in `engine/server/db/jobs/*.py`

Outputs:
- Updated prod DB (`whitelist.db`)
- Rebuilt FAISS index (`whitelist-video-embeddings.faiss` + `.json`)
- Similarity cache (`similarity-cache.db`), rebuilt by shadow build and swap
- Replaced similarity cache (`similarity-cache.prev.db`), the file the last swap replaced

Temporary output:
- Staging DB (`engine/server/db/staging-worker.db`, recreated each run)
- Shadow cache (`similarity-cache.next.db` and its `-journal`), removed by the swap or on failure
- Build marker (`similarity-cache.db.building`), present only during the similarity stage

## Execution Order

The worker runs this sequence:

1. Acquire single-run lock (`/tmp/peertube-browser-staging-sync.lock` by default).
2. Clean up after a crashed run (`cleanup_similarity_leftovers`), before any stage and before the `--dry-run` exit:
   - a build marker with no live PID (unparseable content, a PID that is dead, `<= 0` or out of range) is removed;
   - a build marker with a live PID is kept and logged as a warning; the run lock rules out another updater, so such a PID is a reused one;
   - a leftover `similarity-cache.next.db` and `similarity-cache.next.db-journal` are removed. A leftover journal would otherwise be applied as a hot journal to the next shadow.
3. Prepare staging DB:
   - default: recreate staging DB from crawler schema (`schema.sql`);
   - with `--resume-staging`: reuse existing staging DB and progress state.
4. Seed staging from prod (`instances` + `channels`) unless `--resume-staging` is used.
5. Run crawler steps into staging:
   - `instances-cli`
   - optional local health filter (`--skip-local-dead`)
   - `channels-cli --new-channels`
   - `videos-cli --new-videos --existing-db <prod> --sort -publishedAt`
   - `channels-videos-count-cli`
6. Build embeddings in staging (`build-video-embeddings.py`).
7. Optionally stop API service (unless `--skip-systemctl`).
8. Merge staging into prod (`merge-staging-db.py` with `merge_rules.json`).
9. Prune denylisted hosts from prod and the active similarity cache (post-merge safety prune).
10. Recompute popularity incrementally (`recompute-popularity.py --incremental`).
11. Rebuild ANN index from prod (`build-ann-index.py`).
12. Start API service back. This runs in a `finally`, so the service is started even when steps 8-11 or `--fail-after-merge-before-similarity` fail.
13. Similarity stage (`run_similarity_stage`), with the API serving the new ANN index and the old cache:
   1. Write the build marker (see [Build Marker](#build-marker)).
   2. If `similarity-cache.db` exists, copy it into `similarity-cache.next.db` with the sqlite3 backup API, 1024 pages per step, reading the active file read-only. With no active file, the shadow starts empty.
   3. Refresh the shadow with `precompute-similar-ann.py --refresh-existing --out similarity-cache.next.db`:
      - only sources already in `similarity_sources` that are still in `video_embeddings` are recomputed and rewritten;
      - videos new from the merge get no entry here; the Engine caches each one the first time it is requested;
      - cached sources no longer in `video_embeddings` are left in place; only the stale-host purge and the denylist prunes remove cache rows;
      - a missing or empty cache stays empty (schema only, 0 sources) and the stage still succeeds. The initial full build is `scripts/run-dataset-build.sh`; see `DATA_BUILD.md` §5 "Precompute similarity cache".
   4. Reload prod's active denylist and delete those hosts from the shadow only, so a host denied during the build has no rows in the swapped-in cache.
   5. Gate the shadow (see [Similarity Gate](#similarity-gate)). A failure raises `Similarity gate failed: <reason>` and the worker exits non-zero, with the active cache untouched and the service already up.
   6. Swap: remove any older `similarity-cache.prev.db`, hardlink `similarity-cache.db` to `similarity-cache.prev.db` (a copy where hardlinking fails, none when there is no active file), then `os.replace` the shadow onto `similarity-cache.db`.
   7. On every exit, remove the marker. When no swap happened, also remove `similarity-cache.next.db` and its `-journal`.
14. Release lock and finish.

The active `similarity-cache.db` is never written during the similarity stage; only the swap replaces it.

## Build Marker

- Path: the cache path plus `.building`, so `similarity-cache.db` has the marker `similarity-cache.db.building`. The updater derives it from `--similarity-db` and the Engine from its own cache path; in production both name the same file.
- Content: the updater's PID as decimal ASCII text.
- A marker whose content is not decimal digits, or whose PID is `<= 0`, out of range or not running, is ignored by the Engine and removed by the next updater run (step 2). Only the updater deletes a marker.

## Similarity Gate

The shadow passes only if all of these hold, checked in this order:
- `PRAGMA integrity_check` returns exactly `ok`;
- both `similarity_sources` and `similarity_items` exist;
- the shadow's `similarity_sources` count is at least the active file's, read at gate time (a missing active file counts as 0);
- `--fail-similarity-gate` is not set.

A shadow or active file SQLite cannot read fails with the reason `shadow or active cache unreadable: <error>`.

## Engine Freeze and Reopen

Running Engines follow the stage through files alone, with no restart and no signal:
- While a marker with a live PID exists, an Engine serves cache misses but does not store them. It logs `[similar-cache] write skipped reason=build-marker count=N` at most once per 60 s, N being the skips since the last line.
- On each cache access under its lock, an Engine compares the inode of `similarity-cache.db` with the one it has open. After a swap it opens the new file, checks both cache tables, switches to it and logs `[similar-cache] reopen ok`. If the new file is missing or not a valid cache, it keeps its old handle for reads, skips writes (`reason=stale-handle`), logs `[similar-cache] reopen failed ... reason=...` once per failing file, and retries on the next access.

For the Engine's read and write path, see `engine/server/api/recommendations/docs/OVERVIEW.md`.

## Restoring the Previous Cache

There is no automatic rollback. To go back to the cache the last swap replaced, run this in the cache directory while no updater run is active:

```bash
mv similarity-cache.prev.db similarity-cache.db
```

The service does not need to be stopped: running Engines pick up the restored file through the inode change.

## Operator Notes

- A denylist `block` without `--purge-now` during a build makes the gate fail on the source count: the shadow re-prune removes the host's rows, but the active file still has them. The next run's post-merge prune (step 9) removes them from the active file, and its gate passes.
- A `--purge-now` that lands after the shadow re-prune (step 13.4) and before the swap is undone by the swap. Run the purge again after the stage finishes.

## What Exactly Is Collected

- Instances: from whitelist source (`--whitelist-url`, JoinPeerTube by default).
  - Default mode: `instances-cli` reads `--whitelist-url` itself.
  - With `--sync-join-whitelist`: `fetch_join_hosts` fetches the list and passes every entry through `data.moderation.normalize_host_token`, which returns the same host spelling as the crawler's `normalizeHostToken`. Entries that normalise to nothing (`""`, `.`, `https://`) are dropped. Denylisted hosts are removed. The remaining hosts are compared with the `instances` hosts in prod: hosts absent from prod are new and are crawled through `instances-cli --whitelist-file`, and prod hosts absent from the list are stale.
  - Stale hosts are purged from the prod and similarity DBs only when `--yes` is given. If there are stale hosts and `--yes` is missing, the worker refuses to run. `--dry-run` logs the stale hosts and the delete plan, then exits without changing anything.
  - Prod hosts are compared after only trimming and lowercasing. An `instances` row stored in a spelling the crawler does not produce (for example with a scheme or trailing dots) is therefore stale, and `--yes` purges it. Review the plan with `--dry-run` before passing `--yes`.
- Channels:
  - crawler requests channel pages from each instance API;
  - with `--new-channels`, only channels absent in DB are inserted/kept as new rows.
- Videos: new videos only (`--new-videos`) using prod DB as reference.
- Channel video counts: refreshed in staging for crawled channels.
- Embeddings: computed for new/required rows in staging.

After merge, prod contains merged changes according to `merge_rules.json`.

## Lock Behavior

- Only one worker run is allowed at a time.
- If lock file exists and PID is alive, worker exits with a clear "another run is active" error.
- If lock file exists but PID is stale, worker removes stale lock and continues.

## Resume Staging Behavior

- `--resume-staging` keeps current staging DB and crawler progress tables.
- This allows continuing from the latest saved crawler position instead of starting a fresh staging cycle.
- Without `--resume-staging`, staging DB is recreated each run.

## Service Stop/Start Behavior

Default behavior:
- worker stops `peertube-browser` before the merge and starts it right after the ANN rebuild (steps 7-12); the similarity stage runs while the service serves.
- systemd install uses `--systemctl-use-sudo` so stop/start runs as `sudo -n systemctl ...`
  without interactive auth prompts.

Alternative:
- `--skip-systemctl` disables stop/start control (for manual orchestration).

## GPU/CPU Mode

Acceleration mode is explicit:
- `--gpu`: embeddings + FAISS build run in GPU mode (no CPU fallback).
- `--cpu`: embeddings + FAISS build run in CPU mode.

Default is `--gpu` unless overridden.

## Important Flags

- `--prod-db`, `--staging-db` paths
- `--index-path`, `--index-meta-path`
- `--similarity-db` (active cache; the shadow, `.prev.db` and marker paths are derived from it)
- `--merge-rules`
- `--service-name`
- `--systemctl-bin`
- `--systemctl-use-sudo`
- `--skip-systemctl`
- `--skip-local-dead`
- `--resume-staging`
- `--whitelist-url`
- `--sync-join-whitelist` (reconcile prod hosts with the whitelist and crawl only new hosts)
- `--yes` (confirm the stale-host purge in `--sync-join-whitelist` mode)
- `--dry-run` (log the sync/purge plan and exit; only with `--sync-join-whitelist`)
- `--concurrency`, `--timeout-ms`, `--max-retries`
- `--max-instances`, `--max-channels`, `--max-videos-pages` (test caps)
- `--videos-stop-after-full-pages`
- `--nlist` (FAISS build)

Test-only failure/injection flags:
- `--inject-replace-embedding-for-test`
- `--fail-before-merge`
- `--fail-during-ann-build`
- `--fail-after-merge-before-similarity`
- `--fail-similarity-gate` (the shadow is built, then the gate fails: shadow and marker removed, active cache untouched, non-zero exit)

## Manual Run

From repo root:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py --gpu --skip-local-dead
```

## Systemd Run

`install-service.sh --with-updater-timer` installs:
- `peertube-updater.service` (oneshot worker)
- `peertube-updater.timer` (daily schedule)
- `/etc/sudoers.d/peertube-updater-systemctl` scoped rule allowing updater user to run
  `/usr/bin/systemctl stop/start peertube-browser` via `sudo -n`.

Current timer behavior:
- `OnBootSec=10m`
- `OnUnitInactiveSec=1d`
- `Persistent=true`

Updater flags for systemd are configured in `install-service.sh` via:

- `UPDATER_FLAGS="..."`

You can set mode and crawler/network options there, for example:

- `--gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3`

Installer force reinstall:

- `install-service.sh --force` fully reinstalls unit files (stop/disable/remove/recreate/reload/reset-failed).
- It affects systemd units only; it does not delete prod/staging DB files.

## Logs

Worker logs:
- stdout/stderr from systemd journal
- file log path from `--logs` (default `engine/server/db/updater-worker.log`)

Similarity lines in the worker log:
- `removed stale similarity build marker path=... pid=...` / `kept similarity build marker with live pid path=... pid=...`
- `removed similarity shadow leftover path=...`
- `similarity build marker written path=... pid=...` / `similarity build marker removed path=...`
- `similarity shadow copy path=... ms=...` (or `similarity shadow copy skipped: no active cache`)
- `similarity shadow build ms=...`
- `similarity shadow denylist reprune hosts=... deleted=...`
- `similarity gate result=pass|fail [reason=...] shadow_sources=... active_sources=...`
- `similarity prev written path=... mode=hardlink|copy` (or `similarity prev skipped: no active cache`)
- `similarity swap path=... ms=...`

Useful commands:

```bash
systemctl status peertube-updater.service -l
journalctl -u peertube-updater.service -f -o cat
systemctl list-timers --all peertube-updater.timer
```
