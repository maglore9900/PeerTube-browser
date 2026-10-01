# Zero-downtime server deploy: parallel port startup and automatic nginx switch

Status: enhancement, complete
Origin: task 40, [M7][F4]

## Problem

An in-place restart on one port causes downtime during server initialisation and warm-up.

## Proposed solution

Blue/green deploy for the API: start a new instance on the second port, health-check it, switch the nginx upstream, then drain and stop the old one.

- One-command script (e.g. `deploy-bluegreen.sh`) with an explicit `--blue-green` mode.
- Fixed port pair `7070`/`7071` only (no free-port selection, no custom port list).
- systemd instance template (e.g. `peertube-browser@.service`) so `@7070` and `@7071` can run in parallel.
- Flow: detect the active port and target the other; start the new instance; readiness check (`/api/health`, optional warm-up wait); switch the upstream in a single source snippet; `nginx -t` and reload; stop the old instance.
- Automatic rollback: failed readiness stops the new instance and keeps the old port; failed nginx validation/reload restores the previous upstream.
- Idempotent and lock-protected against concurrent deploys.
- Logs: deploy id, old/new port, switch time, health result, rollback reason.

## Validation (from the original task)

- Repeated deploys show no 5xx spikes in the nginx access log.
- A forced failure exercises rollback.
- One command, no manual `systemctl`/nginx edits.

## Related

- After `23-random-cache-nonblocking-startup` and `24-similarity-cache-shadow-swap`.
- Keep compatible with `X-Request-ID` forwarding from `20-request-lifecycle-logs`.

## Comments

### Prerequisite 23 delivered, with 22

`23-random-cache-nonblocking-startup` and `22-random-cache-background-refresh` are delivered together (plan `docs/project/plans/19-22-random-cache-background-refresh.md`). An Engine opens a usable `random-cache.db` read-only and starts listening; every cache build runs in a background worker and is renamed over the active file, so `/api/health` answering says nothing about whether a build has finished.

What this means for a blue/green pair sharing one checkout:

- **Sibling Engines stay on the old inode.** After one Engine renames a new build over `random-cache.db`, the other keeps reading the file it opened until its own next build or a restart. The plan deferred a per-request inode check to this issue; it is a candidate if both ports must serve the same cache during a switch.
- **Both ports build.** Each Engine runs its own startup build (refresh on in production) and its own periodic build every `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`, so during an overlap two full scans of `whitelist.db` can run at once. Each writes its own `random-cache.tmp.<pid>.db`, so they never share a temp file.
- **Stopping mid-build leaves a temp file.** The worker is a daemon thread and shutdown does not wait for it, so stopping the old instance during a build leaves its `random-cache.tmp.<pid>.db` behind. It is safe to delete.

### Delivered

Delivered by `docs/project/plans/19-26-zero-downtime-deploy.md`, commit `<pending>`.

- **Command.** `sudo scripts/deploy-bluegreen.sh --blue-green` restarts the prod Engine onto the other port of 7070/7071. Its options, rollback and log lines are in `DEPLOYMENT.md`.
- **Topology.** The Client reaches the Engine through a loopback-only nginx listener on `127.0.0.1:7079`, and the upstream snippet `/etc/nginx/peertube-engine-upstream.conf` alone decides the active port. The Client is not restarted by a deploy. The reasoning and rejected alternatives are in ADR-0009; the terms are `Active instance` and `Upstream snippet` in `CONTEXT.md`.
- **Unit name.** The template is `peertube-engine@.service`, following the existing Engine naming, not the `peertube-browser@.service` the proposal gave as an example. The dev contour keeps its single unit.
- **Updater.** In prod the updater stops and starts the instance the snippet names and shares the deploy lock, so a deploy and the updater's stop/start window never overlap. See `engine/server/db/jobs/docs/UPDATER_WORKER.md`.
- **Random cache.** No per-request inode check was added: only one instance takes traffic, and the old one is stopped after the drain. The deploy deletes the old instance's leftover `random-cache.tmp.<pid>.db` and its `-journal`.
- **Live check.** The first two validation items, no 5xx spike over repeated deploys and a forced rollback with the old instance still serving, are checked by the operator on the live host. The suite drives the script against stub `systemctl`, `nginx`, `curl` and `logger`.
