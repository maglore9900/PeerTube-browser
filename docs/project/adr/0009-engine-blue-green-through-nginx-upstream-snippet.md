# ADR-0009: The prod Engine is deployed blue/green behind a loopback nginx listener whose one-server upstream snippet names the active instance

Status: proposed
Date: decided while planning issue 26 (zero-downtime deploy), `docs/project/issues/26-zero-downtime-deploy.md`

## Context

Restarting the prod Engine in place takes the browser path down while the new process loads its FAISS index, which is tens of seconds on a full dataset. The Client backend reads `--engine-url` once at startup, so it cannot follow an Engine that moves between ports. The updater also stops and starts the Engine on its own schedule, so a deploy and an updater run must agree on which Engine is live and must not overlap.

## Decision

1. **A loopback nginx hop sits between the Client and the Engine.** The prod Client unit permanently uses `--engine-url http://127.0.0.1:7079`. `/etc/nginx/conf.d/peertube-engine-internal.conf` listens on `127.0.0.1:7079` only and proxies every path to the upstream `peertube_engine`, passing request headers through unchanged. It adds an `X-Engine-Upstream: $upstream_addr` response header and keeps no upstream keepalive, so after a reload no connection stays pinned to the old port.
2. **The prod Engine is the template `peertube-engine@.service`, run on the fixed pair 7070/7071.** The instance name is the port. Exactly one instance takes traffic and is enabled for boot: the active instance.
3. **The upstream snippet is the only source of truth for the active port.** `/etc/nginx/peertube-engine-upstream.conf` holds `upstream peertube_engine { server 127.0.0.1:<7070|7071>; }` and nothing else. The deploy script, the installer and the updater all read the port from it; no state file and no `systemctl` query decides it.
4. **One deploy lock serialises the deploy, the prod installer and the updater's stop/start window.** It is `engine/server/db/engine-deploy.lock`, derived from the repo root on every side. Root takes it non-blocking and sets it to 0644, so the updater, running as the service user, can open it read-only. The updater waits for it, bounded at 30 minutes, before its stop, and releases it after its start. A deploy also refuses while `peertube-updater.service` is running.
5. **Two strict parsers read the snippet, pinned by one fixture.** Bash `read_active_port` (`engine/engine-upstream.sh`) and Python `parse_upstream_snippet` (`updater-worker.py`) accept exactly one `server 127.0.0.1:7070;` or `…7071;` line and reject everything else, CRLF line endings included. `tests/active/upstream_snippet_cases.json` is the case table both are tested against.
6. **Rollback is driven by the deploy's phase, and the old instance is stopped only after 7079 confirms the target.** `scripts/deploy-bluegreen.sh` starts the other instance, waits for its health, rewrites the snippet atomically and reloads nginx. It then requires a 200 from `127.0.0.1:7079` whose `X-Engine-Upstream` names the target, because right after an asynchronous reload an old nginx worker can still answer 200 from the old instance. A failure before that confirmation restores the snippet and stops the target. A failure after it is logged and makes the exit non-zero, and traffic stays on the new instance.

How to run and troubleshoot a deploy is in `DEPLOYMENT.md`.

## Alternatives rejected

- **Restart the Client onto the new port on each flip.** The operator topology rules it out, and a Client restart is itself an outage.
- **Swap the port in place with `SO_REUSEPORT` or socket activation.** It needs Engine changes and gives no clean drain or rollback point, while nginx is already on the host.
- **A state file or a `systemctl` query as the source of the active port.** Two sources can disagree; the snippet is what nginx actually routes on, so it cannot drift from traffic.
- **An upstream with both servers and `down`/`backup` markers.** It saves nothing over rewriting one line, and it gives up the guarantee that the upstream names exactly one server at every moment.
- **The lock file in `/run/lock`.** With `fs.protected_regular` on, root opening with `O_CREAT` a file the service user created in that sticky directory is refused, so deploy and updater would block each other. `engine/server/db/` is owned by the service user and not sticky.
- **The updater asks the deploy script for the port (`--print-active-port`).** It couples a Python job to a root-oriented shell script. Two small parsers sharing one fixture cost less.

## Consequences

- A change to the snippet format has to touch both parsers and the shared case file. Moving the parser into one helper both call is the upgrade path.
- The Engine's trust in `X-Client-IP` now depends on 7079 being loopback-only as well as on the Engine's own loopback bind (ADR-0002). Exposing 7079 exposes the Engine, `/internal/*` writes included.
- With no Engine behind it, nginx answers its own 502 to the Client, so the Client sees an upstream HTTP error rather than a transport failure.
- During a deploy both instances run: memory roughly doubles for the overlap, and each may build its own random cache.
- Anything else listening on 7071 on a prod host, such as `server.py --dev`, collides with the pair; the deploy refuses rather than treating it as the target.
- The dev contour keeps a single `peertube-engine-dev` unit and in-place restarts.
