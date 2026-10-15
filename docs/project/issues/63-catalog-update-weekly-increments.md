# Run the catalog update in weekly increments

Status: enhancement, complete
Origin: operator request, 2026-10-15 (catalog-update log review)

## Problem

A catalog update (`scripts/run-catalog-update.sh` → `engine/server/db/jobs/updater-worker.py`) crawls every instance in one run, and a run takes 4.5-9 hours:

| Run | channels | videos | channel video counts | similarity |
|---|---|---|---|---|
| 2026-10-01 | 2h06m | 2h20m | 22m | ~40m |
| 2026-10-02 | 2h19m | 1h32m | 8.5m | ~31m |
| 2026-10-14 | 2h18m | 6h16m | still running at 08:42 on 10-15 | - |

The Engine is down only for the merge, popularity and ANN rebuild (about 1.5 minutes on 10-02); the crawl and embeddings run while it serves.

## Proposed solution

Each catalog update crawls one increment of the hosts, not all of them. A cron job runs the same command once a week; the run works out which increment is next and crawls it. The merge, popularity, ANN and similarity steps still run on every increment.

To decide at requirements:
- How hosts are cut into increments (fixed groups by a stable hash of the host, or a time budget that resumes next week), and how many.
- What happens to a host that is in a group but was not crawled because the run failed part way.

## Risks

- `engine/server/db/jobs/merge-staging-db.py` must not read a host absent from an increment's staging DB as a host whose channels or videos were removed. Not yet checked.
- `scripts/run-services.sh stop` and the worker's systemctl shim find the Engine with `pgrep -f engine/server/api/server.py`.

## Out of scope

Skipping the 227 instances with no videos in `whitelist.db`. They cost about 5% of a run (12-15 minutes, nearly all in the channels stage), and an instance with no videos today can publish later. The operator chose not to skip them.

## Comments

2026-10-15: delivered by plan `docs/project/plans/01-63-catalog-update-weekly-increments.md` (record `docs/project/plans/01-63-catalog-update-weekly-increments.record.md`). The operator chose daily runs that each crawl one seventh of the hosts, which supersedes "a cron job runs the command once a week"; each host is still refreshed about weekly.
- `updater-worker.py --increments N` crawls one fixed group, `int(sha1(host).hexdigest(), 16) % N` over `instances.host` as stored, by deleting the other hosts' staging `instances` rows before the channels stage; `0` or absent crawls every host. `--increment-state PATH` overrides the pointer file, `updater-increment.json` next to the prod DB.
- The pointer records the last completed group and is written atomically only after `merge-staging-db.py` succeeds, so a run that fails before or during the merge retries the same group. A corrupt pointer fails the run before any crawl.
- Both installers default to a daily timer (`*-*-* 20:00:00`) with `--increments 7` in `UPDATER_FLAGS`, and `scripts/run-catalog-update.sh` passes `--increments 7`. The crontab line for hosts without systemd is in `engine/server/db/jobs/docs/UPDATER_WORKER.md`.
- The merge risk did not hold: `merge-staging-db.py` never deletes, so a host absent from staging keeps its prod rows.
