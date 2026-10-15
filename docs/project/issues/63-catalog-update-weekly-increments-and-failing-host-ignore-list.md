# Run the catalog update in weekly increments and stop crawling hosts that keep failing

Status: enhancement, ready
Origin: operator request, 2026-10-15 (catalog-update log review)

## Problem

A catalog update (`scripts/run-catalog-update.sh` → `engine/server/db/jobs/updater-worker.py`) crawls every instance in one run, and a run takes 4.5-9 hours:

| Run | channels | videos | channel video counts | similarity |
|---|---|---|---|---|
| 2026-10-01 | 2h06m | 2h20m | 22m | ~40m |
| 2026-10-02 | 2h19m | 1h32m | 8.5m | ~31m |
| 2026-10-14 | 2h18m | 6h16m | still running at 08:42 on 10-15 | - |

The Engine is down only for the merge, popularity and ANN rebuild (about 1.5 minutes on 10-02); the crawl and embeddings run while it serves.

Some hosts fail every run. The channels stage logs a host-level failure as `[channels] error <host>: <reason>` or `[channels] skip <host> status=<code>`. Of the 1,830 hosts the 10-14 run crawled, 46 failed in both logged runs (connection refused, DNS, timeouts, 5xx, 403/404) and 93 more in one of them. Only two catalog-update logs exist (`catalog-update-20261002-222915.log`, `catalog-update-20261014-234740.log`); the 10-01 run's log is gone, and `engine/server/db/updater-worker.log` does not record per-host outcomes. Scan scripts: `tmp/fail-hosts/scan.py`, `tmp/fail-hosts/no_video_hosts.py`.

The existing host exclusions do not fit: the moderation deny list (`load_denied_hosts`) purges a host's data, and `--skip-local-dead` reads `instances.health_status` from prod, which no update run writes (`statuses=none` in every run).

## Proposed solution

1. **Failing-host ignore list.** Record each host's channel-stage outcome per catalog update. A host that fails in 3 different catalog updates goes on an ignore list and is excluded from the crawl stages through the worker's existing `--exclude-hosts-file`. The operator can take a host off the list later, once it is healthy again. The ignore list is separate from the moderation deny list and deletes no data.
2. **Weekly increments.** Each catalog update crawls one increment of the hosts, not all of them. A cron job runs the same command once a week; the run works out which increment is next and crawls it. The merge, popularity, ANN and similarity steps still run on every increment.

To decide at requirements:
- Whether "3 failures" means 3 consecutive updates (a success resets the count) or 3 in total.
- How hosts are cut into increments (fixed groups by a stable hash of the host, or a time budget that resumes next week), and how many.
- Whether the history is seeded from the two existing logs.
- What happens to a host that is in a group but was not crawled because the run failed part way.

## Risks

- `engine/server/db/jobs/merge-staging-db.py` must not read a host absent from an increment's staging DB as a host whose channels or videos were removed. Not yet checked.
- `scripts/run-services.sh stop` and the worker's systemctl shim find the Engine with `pgrep -f engine/server/api/server.py`.

## Out of scope

Skipping the 227 instances with no videos in `whitelist.db`. They cost about 5% of a run (12-15 minutes, nearly all in the channels stage), and an instance with no videos today can publish later. The operator chose not to skip them.

## Comments
