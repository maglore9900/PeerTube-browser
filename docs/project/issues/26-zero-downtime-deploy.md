# Zero-downtime server deploy: parallel port startup and automatic nginx switch

Status: enhancement, needs-triage
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
