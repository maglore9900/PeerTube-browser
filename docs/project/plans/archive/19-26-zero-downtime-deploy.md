# 26-zero-downtime-deploy

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-26-zero-downtime-deploy.record.md`._

## Requirements

### Purpose

Restarting the Engine API in place on one port takes the whole browser path down while the new process loads its FAISS index and warms up. That is tens of seconds on a full dataset (DEPLOYMENT.md §4, Triage "Engine `active` but `/api/health` refuses connections for minutes"). The browser path is nginx `:80` → Client backend `127.0.0.1:7072` → Engine `127.0.0.1:7070` (DEPLOYMENT.md §6; `client/backend/server.py` reads `--engine-url` once at startup, default `http://127.0.0.1:7070`). The build gives the operator one command that restarts the Engine on the code currently on disk (after a `git pull`, a dependency change or an environment change) with no window where the Client cannot reach an Engine. A second Engine starts on the other port of a fixed pair, is health-checked, and gets traffic through an nginx upstream switch; only then is the old one drained and stopped. Failures roll back on their own.

### Decided topology (operator decision)

- The Engine is what gets blue/green. The Client backend is not blue/green and is not restarted by a deploy.
- nginx is placed between the Client and the Engine through a new loopback-only listener on `127.0.0.1:7079`. It proxies every path to an nginx `upstream` whose single server is the active Engine port (`127.0.0.1:7070` or `127.0.0.1:7071`).
- The prod Client unit's `--engine-url` becomes `http://127.0.0.1:7079`, permanently. After this one-time change the Client never has to change or restart for an Engine deploy.
- The public `:80` site config (`/etc/nginx/sites-available/peertube-browser`, DEPLOYMENT.md §6) is not changed by this work. The `7079` listener must bind `127.0.0.1` only and must never be reachable from outside the host; the Engine has no authentication and `/internal/*` accepts writes (DEPLOYMENT.md §6 Firewall).

### Scope

- Prod contour only. The dev contour (`peertube-engine-dev` on 7171, Client dev on 7172) keeps its current single unit and in-place restart, unchanged.
- Fixed port pair `7070`/`7071` only: no free-port selection, no custom port list, no port options on the deploy script.
- Out of scope: fetching or updating code (the deploy restarts whatever is on disk), Client backend blue/green, dev-contour blue/green, unit hardening (review findings F1/F3), a per-request random-cache inode check, and `scripts/run-services.sh` (manual/dev runner without nginx; it keeps starting a single Engine on 7070).

### systemd instance template

- A template unit `peertube-engine@.service` replaces `peertube-engine.service` in the prod contour. The name follows the existing `peertube-engine` naming; the issue's `peertube-browser@.service` was only an example. The instance name is the port, so `peertube-engine@7070` and `peertube-engine@7071` can run at the same time.
- Template content matches today's prod Engine unit (`engine/install-engine-service.sh`): `Type=simple`, same `User=`, `WorkingDirectory=`, `Environment=PYTHONUNBUFFERED=1`, `Environment=ENGINE_INGEST_MODE=bridge`, `EnvironmentFile=-<project>/.env.bridge`, `Restart=on-failure`, `TimeoutStopSec=20`, `WantedBy=multi-user.target`. The one difference is that `ExecStart` takes `--port` from the instance name (`%i`), with `--host 127.0.0.1`.
- The prod Engine installer (`engine/install-engine-service.sh --mode prod`, also reached through `scripts/install-service.sh`) installs the template instead of the single unit. On an existing install it migrates: it stops and disables the old `peertube-engine.service`, removes its unit file, then starts and enables one instance, `peertube-engine@7070`, and writes the snippet pointing at 7070. Re-running the installer is idempotent; it must not flip or restart a healthy active instance just because it is re-run without `--force`.
- Exactly one instance is enabled for boot: the one the snippet names. A deploy enables the new instance and disables the old one.
- The Engine uninstaller (`engine/uninstall-engine-service.sh --mode prod`, and `scripts/uninstall-service.sh`) stops, disables and removes both instances and the template, and removes the nginx snippet and the 7079 listener config that the installer wrote. Afterwards nginx must still pass `nginx -t` and keep serving the public site.
- `--help` and `--dry-run` keep working on all installer and uninstaller entrypoints. `tests/run-installers-smoke.sh --dry-run-only` relies on both.

### nginx: single source snippet and internal listener

- One snippet file is the single source of truth for which Engine port is active. It contains only the upstream definition, one server line: `127.0.0.1:7070` or `127.0.0.1:7071`. Nothing else (no state file, no systemctl query) decides which port is active.
- A loopback-only server block listens on `127.0.0.1:7079`, includes or references that upstream, and proxies every path to it.
- The listener passes request headers through unchanged. In particular `X-Request-ID` from the Client must reach the Engine as sent: it is neither stripped nor replaced. `X-Client-IP` and `X-Bridge-Token` must also arrive unchanged, because the Engine's rate limiter keys on `X-Client-IP` (DEPLOYMENT.md §6) and `/internal/*` authenticates on `X-Bridge-Token` (§3b). This keeps the work compatible with `X-Request-ID` forwarding from issue `20-request-lifecycle-logs`, which is not delivered yet.
- Proxy timeouts on the listener must not cut off legitimate long Engine requests (up-next FAISS searches are not bounded by the 5 s statement deadline, DEPLOYMENT.md §4 "Up-next logs and load"). Keep nginx defaults or set them at least as generous.
- Setup of the snippet, the listener and the Client's `--engine-url` change is scripted, with no manual nginx edits: done by the prod install path (Engine and Client installers or the central `scripts/install-service.sh`). Setup validates with `nginx -t` before reloading.
- The prod Client installer (`client/install-client-service.sh --mode prod`) writes `--engine-url http://127.0.0.1:7079` by default. Dev keeps `http://127.0.0.1:7171`.

### Deploy command

- New script `scripts/deploy-bluegreen.sh`. It operates on the repository root the same way `scripts/run-services.sh` resolves it.
- It requires the explicit `--blue-green` flag. Without it the script prints usage and exits non-zero, with no side effects.
- It supports `--help` and `--dry-run`. Dry-run prints the detected active port, the target port, and every action it would take, without starting, stopping, writing or reloading anything.
- Options: a readiness timeout in seconds (default 300, matching `run-services.sh` `HEALTH_TIMEOUT`); an optional warm-up wait in seconds after the first healthy answer (default 0); a drain wait in seconds between the switch and stopping the old instance (default long enough for in-flight requests to finish; design picks the value and documents it).
- It runs as root (via sudo), like the installers, because it calls `systemctl` and `nginx`. It fails fast with a clear message otherwise, except in `--dry-run`.
- One command does the whole deploy. No step needs a manual `systemctl` call or nginx edit.

### Deploy flow

1. Acquire an exclusive non-blocking lock (flock on a fixed lock file). If another deploy holds it, exit non-zero at once with a message, touching nothing.
2. Refuse to start (non-zero, message) while the prod updater service (`peertube-updater.service`) is active, since it stops and starts the Engine itself.
3. Read the active port from the snippet. If the snippet is missing or names anything other than 7070/7071, stop with an error and touch nothing. The target port is the other one of the pair.
4. If the target instance is already running (leftover from an interrupted deploy), stop it first. A leftover is restarted, never reused, so the deploy always runs freshly started code.
5. Start `peertube-engine@<target>`.
6. Readiness: poll `http://127.0.0.1:<target>/api/health` until it returns HTTP 200 or the readiness timeout expires. The poll interval must stay well inside the Engine's `/api/` rate limit, because `/api/health` sits behind `_rate_limit_check`. Then wait the optional warm-up time and check health once more.
7. Switch: keep a copy of the current snippet, write the new snippet atomically (temp file plus rename) naming the target port, run `nginx -t`, then reload nginx.
8. Post-switch check: `http://127.0.0.1:7079/api/health` returns 200.
9. Wait the drain period, then stop `peertube-engine@<old>` with `systemctl stop` (SIGTERM; the Engine shuts down gracefully), enable the new instance and disable the old one.
10. Remove the old instance's leftover `engine/server/db/random-cache.tmp.<old MainPID>.db` if one exists. The PID is recorded before the stop. A stop during a background cache build leaves this file, and it is safe to delete (issue comment; DEPLOYMENT.md §4).
11. Release the lock and exit 0.

### Automatic rollback

- Readiness failure (timeout, or the target unit fails or exits): stop the new instance; the snippet and nginx are untouched and the old instance keeps serving. Exit non-zero.
- `nginx -t` failure, reload failure, or post-switch check failure: restore the previous snippet, run `nginx -t`, reload nginx, stop the new instance. The old instance keeps serving. Exit non-zero.
- The old instance is never stopped before the switch has been verified (step 8).
- After the switch is verified, failures (stopping the old instance, enable/disable, temp-file cleanup) are logged and make the exit code non-zero, but do not roll back the switch, because traffic is already on the new instance.
- A failure inside rollback itself (for example the restore's `nginx -t` fails) is logged loudly with the state left behind, and exits non-zero.
- The lock is released on every exit path, including signals.

### Idempotency

- Re-running after a successful deploy deploys again: it flips to the other port. Re-running after an interrupted or failed deploy converges, because the snippet is the only source of truth and a leftover target instance is restarted, not reused.
- A deploy never leaves both instances serving through nginx: the upstream names exactly one server at every moment.

### Updater compatibility

- `engine/server/db/jobs/updater-worker.py` currently stops and starts one fixed unit name (`--service-name`, default `peertube-engine`). In prod it must stop and start the active instance instead: the one the snippet names when the updater reaches its stop step. It must start the same instance it stopped.
- The updater's sudoers rule (`engine/install-updater-service.sh`, `/etc/sudoers.d/peertube-updater-systemctl`) must allow exactly `stop` and `start` on `peertube-engine@7070` and `peertube-engine@7071`, nothing broader.
- A deploy and the updater's Engine stop/start window must not overlap in either direction. The deploy refuses while the updater is active (flow step 2), and the updater must not stop/start an Engine while a deploy holds the lock; design picks the mechanism.
- Dev updater behaviour is unchanged.

### Random cache and similarity cache during the overlap

- Both instances building `random-cache.db` during the overlap (each with its own `random-cache.tmp.<pid>.db`) is accepted, as is the extra CPU while both run.
- Readiness does not wait for a random-cache build. `/api/health` does not report it, and the Engine serves the random feed from `whitelist.db` until its build finishes (DEPLOYMENT.md §4). The optional warm-up wait is the operator's control for this.
- No per-request inode check is added. Only one instance takes traffic at a time, and the old instance is stopped after the drain, so a sibling holding an old `random-cache.db` inode only lasts for the overlap.
- The similarity cache needs nothing new. Running Engines already reopen a swapped `similarity-cache.db` on their next cache access (DEPLOYMENT.md "The updater timer").

### Logging

- Every deploy has a deploy id, unique per run (for example UTC timestamp plus PID). Every log line carries it.
- Logged at minimum: deploy id, old port, new port, the switch time (when the reload succeeded), the health result (HTTP status and seconds waited, for readiness and for the post-switch check), the drain and stop outcome, and on any rollback the rollback reason and the step it happened at.
- Lines go to stdout and to journald through `logger` with a fixed tag, matching `log_lifecycle` in the installers (`logger -t peertube-service-lifecycle`, or a deploy-specific tag; design picks).

### Documentation

- `DEPLOYMENT.md` is updated: the units table (template instances replace `peertube-engine.service` in prod); "Day to day" (deploy command instead of `systemctl restart peertube-engine`, and how to find the active instance); the nginx section (the 7079 listener, the snippet, and that 7079 must stay loopback-only; Firewall says never open 7070, 7071, 7072 or 7079); the updater section (it stops/starts the active instance); Triage rows for deploy lock held, readiness timeout, nginx validation failure and rollback, and finding the active port; the Client `--engine-url` in prod; and §7's note that `seed=` goes to the Engine directly, which now means the active port, not always 7070.
- Every other doc that names `peertube-engine.service` for prod, or 7070 as the only prod Engine port, is brought in line (`README.md`, `engine/server/README.md`, `engine/server/db/jobs/docs/UPDATER_WORKER.md`, as the impact inventory finds them).

### Validation

- Automated tests run without root, systemd or a real nginx, using stub `systemctl`, `nginx`, `curl` and `logger` injected through PATH or environment, the way `updater-worker.py` takes `--systemctl-bin` and `--skip-systemctl`. They cover: a normal flip 7070→7071 and back 7071→7070 (snippet contents, start/stop/enable/disable calls in order, old stopped only after the switch); readiness-timeout rollback (new stopped, snippet unchanged, old untouched, non-zero exit); `nginx -t` failure rollback; reload failure rollback; post-switch probe failure rollback (previous snippet restored); lock contention (second run exits non-zero without side effects); refusal without `--blue-green`; refusal while the updater is active; leftover target instance restarted; missing or invalid snippet refused; leftover `random-cache.tmp.<old pid>.db` removed; required log fields present, including the rollback reason.
- The updater's active-instance resolution and the installer's template/sudoers output are covered by tests or by dry-run contract checks in `tests/run-installers-smoke.sh --dry-run-only`.
- Operator validation on the live host, not automated: repeated deploys show no 5xx spike in the nginx access log for the public site, and a forced failure (for example a readiness timeout of 1 s, or a deliberately broken snippet) exercises rollback with the old instance still serving.

### Baseline suite state

Pre-build suite exited 0 (baseline variant: false). Paths: active tests `tests/active`, working `tests/tmp`, plans `docs/project/plans`, archive `tests/archive`, delete-me `delete_me`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`, project dir `/home/enduser/code/PeerTube-browser`.

## High-level plan

### Approach

The build has four parts. One bash script does the deploy. The Engine installer and uninstaller learn about the template unit and own the nginx files. The updater gets one extra argument for prod. The docs and tests are updated to match. Nothing in the Engine's Python server changes, and there are no new dependencies: the script uses only bash, `flock(1)` from util-linux, `curl`, `systemctl`, `nginx` and `logger`.

**nginx files (owned by the prod Engine installer).** There are two files.

- **The snippet**, `/etc/nginx/peertube-engine-upstream.conf`. It holds only `upstream peertube_engine { server 127.0.0.1:<port>; }` and is the single source of truth for the active port. It sits outside `conf.d/` so nothing else includes it by accident.
- **The listener**, `/etc/nginx/conf.d/peertube-engine-internal.conf`. It includes the snippet by absolute path and declares one `server` that listens on `127.0.0.1:7079` only, with `location /` doing a `proxy_pass` to `http://peertube_engine`.
  - **Headers pass through.** nginx forwards client request headers unchanged by default, so `X-Request-ID`, `X-Client-IP` and `X-Bridge-Token` reach the Engine as sent. The block sets no `proxy_set_header` for them. The only header line is `proxy_set_header Host $http_host`, so that `Host` is passed through too instead of being replaced with the upstream name.
  - **Timeouts and body size.** Proxy timeouts stay at the nginx defaults (60 s read/send). The Client's longest Engine timeout is 20 s (`ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` for `/api/video/refresh`). `client_max_body_size` is set explicitly at or above the Client's `ENGINE_PROXY_MAX_BODY_BYTES` (1 000 000), so the new hop cannot add a 413.
  - **No upstream keepalive, on purpose.** Each request opens a new connection, so after a reload no connection stays pinned to the old port.
  - **Instance tag.** The listener adds a response header `X-Engine-Upstream: $upstream_addr`. The post-switch check uses it (see Risks). It is safe because the Client backend copies only `content-type` from Engine responses (`client/backend/server.py`), so the header never reaches a browser.
- **Why `conf.d`.** It is included in the `http` context by the stock Debian/Ubuntu `nginx.conf`, and `sites-available/peertube-browser` is not touched. After writing, the installer runs `nginx -t`, reloads, and then checks `127.0.0.1:7079/api/health`. If the host's `nginx.conf` does not include `conf.d`, the install fails loudly instead of passing quietly.

**Template unit and installer (`engine/install-engine-service.sh --mode prod`).**
- **Template.** It writes `peertube-engine@.service`, a byte-for-byte copy of today's unit except that `ExecStart` ends in `--host 127.0.0.1 --port %i`. The unit base name stays `peertube-engine`, so `--print-default-service-name` keeps printing it and the instance names are derived as `peertube-engine@<port>`.
- **Port options in prod.** `--port` and `--host` are rejected in prod (fixed pair). `scripts/install-service.sh` stops passing them for the prod contour and refuses `--engine-port` for prod.
- **Install sequence:**
  1. Take the deploy lock (non-blocking; refuse if a deploy is running).
  2. Write the template and listener, and `daemon-reload`.
  3. If the legacy `/etc/systemd/system/peertube-engine.service` exists, stop it, disable it, remove it and `daemon-reload` (migration).
  4. If the snippet is missing, write it naming 7070. If it exists and is valid, keep its port. If it is invalid, fail without touching anything.
  5. Bring up the snippet's instance: start it if not running, restart it only under `--force`, and leave a healthy running one alone without `--force`. Enable it and disable the other instance.
  6. Run `nginx -t`, reload, and check health on 7079.
- **Re-runs.** Never flip the port. A re-run without `--force` on a healthy host only rewrites identical files.
- **`--dry-run`** prints the template, snippet and listener previews and the detected migration and port plan, and writes nothing.

**Client installer.** The prod default `--engine-url` becomes `http://127.0.0.1:7079`, and the central installer's prod `engine_ingest_base` follows it. Dev keeps 7171. The central installer already runs the Engine installer first, so the listener exists before the Client is pointed at it.

**Uninstaller (`engine/uninstall-engine-service.sh --mode prod`).**
- It stops and disables `peertube-engine@7070` and `@7071`, and removes the template and any legacy single unit, so an un-migrated host also uninstalls cleanly.
- It removes the listener and snippet, runs `daemon-reload`, and if nginx is present runs `nginx -t` and reloads. Removing the two files removes the only references to the upstream, so the public site config still validates.
- `--dry-run` lists every action. Dev is untouched.

**Deploy script (`scripts/deploy-bluegreen.sh`).**
- **Repo root.** Found the same way `run-services.sh` and `install-service.sh` find it: `SCRIPT_DIR`, or its parent when `engine/` sits one level up.
- **Options:** `--blue-green` (required), `--timeout <s>` (readiness, default 300, same name as `run-services.sh`), `--warmup <s>` (default 0), `--drain <s>` (default 30), `--dry-run`, `-h|--help`.
- **Drain default of 30 s.** It is the Client's longest Engine request timeout (20 s) plus margin. nginx's graceful reload lets old workers finish their in-flight requests to the old Engine. After 30 s, every request the Client sent before the switch has either finished or been abandoned by the Client itself.
- **Without `--blue-green`:** print usage and exit 2 with no side effects.
- **Root check.** Non-root fails fast except in `--dry-run`. The script checks `id -u` rather than `$EUID`, so tests can stub `id` through PATH and production keeps no bypass flag.
- **Snippet path.** Defaults to `/etc/nginx/peertube-engine-upstream.conf` and can be overridden by one environment variable for tests.
- **Lock file.** `<repo>/engine/server/db/engine-deploy.lock`.
- **Deploy id.** UTC `YYYYmmddTHHMMSSZ-<pid>`. Every line is `deploy_id=… event=… key=value`, printed to stdout and sent through `logger -t peertube-engine-deploy`.
- **Flow (requirements steps 1–11):**
  1. `flock -n` on fd 9 of the lock file.
  2. Refuse if `systemctl is-active peertube-updater.service` reports `active`, `activating`, `deactivating` or `reloading`.
  3. Parse the snippet strictly: exactly one `server 127.0.0.1:(7070|7071);` line.
  4. Stop a leftover target instance if it is not inactive.
  5. `systemctl start peertube-engine@<target>`.
  6. Poll `curl --max-time` on `/api/health` every 2 s. Each round also checks `systemctl is-active` and fails at once on `failed`/`inactive`. 2 s is about 30 requests a minute against the Engine's 60/60 s per-key limit on the fresh instance's own limiter, and a 429 just counts as not ready. Then the optional warm-up sleep and one more health check.
  7. Copy the snippet to a backup beside it, write the new snippet to a temp file in the same directory and `mv` it into place, run `nginx -t`, then `systemctl reload nginx` and log the switch time.
  8. Check `127.0.0.1:7079/api/health` for HTTP 200 whose `X-Engine-Upstream` names the target. Retry about 1 s apart for up to about 10 s, because the reload is asynchronous.
  9. Record the old instance's `MainPID` (`systemctl show -p MainPID --value`). Sleep the drain, stop the old instance, enable the new one, disable the old one.
  10. Remove `engine/server/db/random-cache.tmp.<pid>.db` and its `-journal` sidecar, the same pair `remove_random_cache_temp` deletes.
  11. Exit 0.
- **Phases and rollback.** A phase variable (`pre-switch`, `switching`, `switched`) drives one rollback function. It is called on any failure and from the `INT`/`TERM` traps.
  - `pre-switch`: stop the new instance.
  - `switching`: restore the backup snippet, run `nginx -t`, reload, stop the new instance.
  - `switched`: no rollback; log and mark the exit non-zero.
  - A failure inside rollback logs `ROLLBACK FAILED` with the snippet contents and both instances' states, and exits non-zero.
- **Lock release.** The lock is tied to the open fd, so it is released on every exit, including `SIGKILL`.
- **Client preflight.** Before touching anything, the script refuses if `/etc/systemd/system/peertube-client.service` exists and does not contain `--engine-url http://127.0.0.1:7079`. A flip would otherwise cut off a Client that still points straight at 7070. This guard is my addition: it touches nothing and is listed under Tradeoffs.
- **`--dry-run`** prints the deploy id, active and target ports, updater state, Client preflight result and the ordered action list. It takes no lock and writes, starts, stops and reloads nothing.

**Updater (`updater-worker.py`).**
- **New argument.** It gains `--engine-upstream-snippet <path>`; the prod updater installer writes it into the prod unit. With it set:
  - The worker takes `fcntl.flock` on the deploy lock (`--deploy-lock-file`, defaulting to the same repo-relative path), polling non-blocking up to a bounded wait of 30 minutes. If the wait runs out it fails before stopping anything.
  - Once it holds the lock, it parses the snippet with the same strict rule as the deploy script, resolves `peertube-engine@<port>` once into a local variable, stops that unit, and in the existing `finally` starts the same unit. It releases the lock after the start.
- **Without the argument** the behaviour is byte-for-byte today's, so dev is unchanged.
- **Overlap in both directions.** The deploy refuses while the updater unit is running, and the updater cannot stop or start while a deploy holds the lock.
- **Sudoers.** In prod the updater installer writes exactly four `NOPASSWD` entries: `<systemctl> stop|start peertube-engine@7070|7071`. Sudoers matches arguments literally, so the worker must call the unit without the `.service` suffix, exactly as written there. Dev keeps its single-name rule.

**Docs.** `DEPLOYMENT.md` gets every section the requirements list:
- the units table (template instances replace `peertube-engine.service` in prod);
- "Day to day": the deploy command, and how to find the active instance (`cat` the snippet);
- §6: the 7079 listener and the snippet; 7079 stays loopback-only; Firewall says never open 7070, 7071, 7072 or 7079;
- the updater section: it stops and starts the active instance;
- Triage rows for: lock held, readiness timeout, nginx validation failure and rollback, finding the active port;
- the Client `--engine-url` in prod;
- §7: `seed=` goes to the active port.

`README.md`, `engine/server/README.md` and `UPDATER_WORKER.md` are brought in line wherever the impact inventory finds the prod unit name or 7070 named as the only prod port.

**How each requirement is met.**
- **No outage window:** the Client talks to a fixed 7079 and nginx flips the upstream only after the new instance is healthy.
- **One command and automatic rollback:** the phase machine above.
- **Snippet as single source of truth:** the deploy, installer and updater all read only the snippet.
- **One instance enabled:** the installer and deploy step 9 keep enablement equal to the snippet.
- **Updater compatibility:** the snippet argument, the shared lock and the four-entry sudoers rule.
- **Logging:** one tag, `deploy_id` on every line, and the required fields as `key=value` pairs.
- **Dev contour:** untouched, because every new behaviour is gated on `--mode prod` or on the updater's new argument.

**Validation.**
- **New `tests/active/test_deploy_bluegreen.py`** copies the script into a temp tree (`scripts/` and `engine/server/db/`) and runs it with a stub `bin/` on PATH:
  - `systemctl` logs calls and answers `is-active` and `MainPID` from scripted state files;
  - `nginx -t` passes or fails on a toggle;
  - `curl` returns scripted statuses and the `X-Engine-Upstream` header per URL;
  - `logger` records lines;
  - `id` prints 0.
  - It covers every case in the requirements list. Lock contention is tested by holding `fcntl.flock` on the lock path from the test process.
- **`test_updater_worker.py` additions:** snippet parsing (valid, missing, foreign port), unit resolution, and that stop and start use the same resolved name. The existing AST test (`systemctl_cmd(action="start")` inside a `finally`) must still pass, so the structure is kept.
- **Installer test:** a pytest runs the Engine and updater installers with `--dry-run` against a fake project tree (stub `venv/bin/python3` and `server.py`) and asserts the template's `--port %i`, the four exact sudoers entries, and the 7079 default in the Client installer.

### Alternatives considered

- **Keep the Client pointed at a port and restart the Client on each flip.** Rejected by the operator topology, and a Client restart is itself a gap.
- **Swap the port in place with `SO_REUSEPORT` or socket activation.** This needs Engine changes and gives no clean drain or rollback point. nginx is already on the host.
- **State file or `systemctl` query as the source of the active port.** The requirements forbid it, and two sources can disagree. The snippet is what nginx actually uses, so it cannot drift from traffic.
- **Upstream with both servers and `down`/`backup` markers.** It saves nothing over rewriting one line, and it breaks "the upstream names exactly one server at every moment".
- **`nginx -s reload` vs `systemctl reload nginx`.** Both are asynchronous. The systemd form matches how the host runs nginx and is just as easy to stub.
- **Post-switch check on a plain 200.** Rejected: right after an async reload, a 200 can come from an old worker still proxying to the old Engine, which is alive, so a broken switch would pass. Identifying the upstream through `X-Engine-Upstream` closes that hole without adding an instance field to the Engine.
- **Lock file in `/run/lock`.** Rejected. With `fs.protected_regular` on (the default on current distros), root opening with `O_CREAT` a lock file the service user created in that sticky, world-writable directory is refused, which would make deploy and updater block each other. The repo's `engine/server/db/` is owned by the service user and not sticky. Both sides can create or open the file there, and both derive the path from the repo root with no configuration.
- **Updater fails at once if a deploy holds the lock.** Rejected in favour of a bounded wait: the crawl before that point takes hours, and a deploy takes minutes.
- **Updater finds the active instance through the deploy script (`--print-active-port`).** Rejected. It would couple a Python job to a root-oriented shell script. The snippet format is one line, so two small parsers with one shared test fixture is the cheaper simplification. Ceiling: a format change must touch both. Upgrade path: move the parser into one helper both call.
- **Deploy pulls code or restarts the Client.** Out of scope by requirement.

### Gotchas and risks

- **Oneshot updater state.** `peertube-updater.service` is `Type=oneshot`, so while it runs `is-active` prints `activating`, not `active`. Checking only for `active` would let a deploy start mid-run.
- **Async reload.** Covered by the `X-Engine-Upstream` check with a short retry window. The retry has to be bounded, and failing it takes the full rollback path.
- **`Restart=on-failure` during readiness.** A crashing new instance cycles through `activating (auto-restart)`. Readiness treats only `failed`/`inactive` as an immediate failure. A crash loop runs until the readiness timeout, then rolls back.
- **Behaviour change while the Engine is down.** During the updater's stop/merge window the Client now gets an nginx 502 instead of a refused connection. The Client's Engine-down handling and `/api/health` reporting must treat both the same. The impact step should confirm this in `client/backend/server.py` around its `URLError`/`RemoteDisconnected` handling.
- **nginx becomes a hard dependency of the prod Engine install.** The install fails cleanly without it. If `nginx.conf` lacks the `conf.d` include, the post-install check on 7079 reports it.
- **One-time migration outage.** Moving from `peertube-engine.service` to `@7070` means stopping the old unit before the instance can bind 7070. Pointing the Client at 7079 means restarting the Client once. Both are inherent to the migration, not to deploys.
- **Reboot inside the drain window.** If the host reboots during the drain, the old instance is still the enabled one while the snippet names the new. That follows from the specified step-9 order: about 30 s of exposure per deploy, and the next deploy or an installer run converges it. Upgrade path: enable the new instance right after step 8.
- **The central installer passes `--force` for prod by default.** Re-running it restarts the active instance in place, which is today's behaviour. Restarting without downtime is what the deploy command is for, and the docs say so.
- **The smoke script is broken before this build.** `tests/run-installers-smoke.sh` points at `${ROOT_DIR}/install-service.sh` and the root-level `install-service-prod.sh`/`-dev.sh` wrappers, which no longer exist (the scripts live in `scripts/`). It therefore exits before its checks even in `--dry-run-only`, and it is not in the gating suite. The new contract checks go in pytest so they actually run. Fixing the smoke paths, plus its prod `engine_ingest_base`, engine unit name and port expectations, is a small adjacent fix to schedule separately, not to fold in silently.
- **Lock fd inheritance.** The script launches nothing long-lived, and systemd spawns the Engines, so no child keeps fd 9 open past the script's exit.

### Tradeoffs the operator accepts

- An extra loopback nginx hop on every Client→Engine request, which also adds nginx to the Engine path's failure surface.
- A 30 s default drain and 2 s readiness poll, which make every deploy take at least `startup + 30 s`.
- The updater can wait up to 30 minutes for a running deploy before it fails without touching anything.
- Two copies of the snippet parser, one bash and one Python (named simplification above).
- Two small additions beyond the letter of the requirements, both refusals or tighter checks that never change state:
  - the Client-URL preflight refusal;
  - the stricter post-switch check (200 and the target named in `X-Engine-Upstream`).
- A response header (`X-Engine-Upstream`) on the internal listener only. The Client never forwards it.

## Impacts

<impacts>
<impact path="scripts/deploy-bluegreen.sh" element="new script (whole file)">
**What changes.** A new root-only bash script. It finds the repo root with the same `SCRIPT_DIR`/parent rule as `scripts/run-services.sh:24-29` and `scripts/install-service.sh:4-9`. Its options are `--blue-green` (required; without it, print usage and exit 2), `--timeout` (default 300, the same name as `run-services.sh:15,40,60`), `--warmup` (default 0), `--drain` (default 30), `--dry-run` and `-h`. It holds `flock -n` on fd 9 of `<repo>/engine/server/db/engine-deploy.lock`. A `pre-switch`/`switching`/`switched` phase variable drives a single rollback function, which the `INT`/`TERM` traps also call. Log lines are `deploy_id=… event=…`, sent to stdout and to `logger -t peertube-engine-deploy`. One env var overrides the snippet path. The root check uses `id -u`.

**What it depends on.**
- The snippet and listener written by `engine/install-engine-service.sh`, and the `peertube-engine@.service` template.
- Engine `/api/health`, handled at `engine/server/api/handlers/similar.py:469-472`. The rate limit is checked before the health branch (line 469), at 60 requests per 60 s (`engine/server/api/server_config.py:482-483`). curl sends no `X-Client-IP`, so readiness polls on the target, the warm-up recheck and the post-switch probes through 7079 all count against one `127.0.0.1` bucket in the new instance. That is about 30+1+10 per 60 s, which fits with little margin. A 429 must count as not ready.
- The temp-file naming in `engine/server/data/random_cache.py:197-205`: `<stem>.tmp.<pid><suffix>` plus `-journal`. Bash reimplements it.
- `peertube-updater.service` is `Type=oneshot` (`engine/install-updater-service.sh:333`), so while it runs `is-active` prints `activating`, not `active`.
- The Client preflight depends on the literal `ExecStart` that `client/install-client-service.sh:197` writes.

**Risks.**
- **Rollback phase.** If the phase is wrong at the moment of failure, rollback either stops the only serving instance or leaves a snippet that nginx never loaded.
- **Snippet mode.** A `mktemp` file moved into place is root `0600`. nginx still reads it, but the updater runs as the service user (`install-updater-service.sh:334`) and can no longer parse it, so every updater run fails before its stop. The new file needs `chmod 0644` before the `mv`.
- **Foreign listener on the target port.** A manual `server.py --dev` binds 7071 by default (`engine/server/api/server.py:141,315`). So can `run-services.sh --engine-port 7071`. Either answers 200 while the unit is in `activating (auto-restart)`, so readiness passes on the wrong process. `X-Engine-Upstream` still names the target port, so the post-switch check does not catch it either.
- **fd 9 inheritance.** Child processes (`sleep`, `curl`, `logger`) inherit fd 9. A SIGKILL during the drain leaves the lock held until that `sleep` exits. Use `9>&-` on children if "released on every exit" must hold literally.
- **Preflight string match.** The preflight is an exact string match. An equivalent URL (`localhost`, a trailing `/`), a custom Client `--service-name` or an `ExecStart` drop-in is misjudged.
- **Backup file name.** The backup must stay outside `conf.d/`, or must not end in `.conf`. Otherwise nginx loads a duplicate `upstream`.
- **Startup lock contention.** At startup the new instance runs schema DDL on the shared `whitelist.db` while the old one serves (see the `engine/server/data/db.py` entry). A "database is locked" error at startup restart-loops until the readiness timeout, then rolls back.
</impact>
<impact path="engine/install-engine-service.sh" element="install_engine_service() prod branch (lines 147-245): unit path/content, --force block, enable/restart/verify, dry-run block, root/cmd checks">
**What changes.**
- In prod, `unit_path` (line 170) becomes `/etc/systemd/system/peertube-engine@.service`, and `ExecStart` (line 183) ends `--host 127.0.0.1 --port %i`. The rest of the unit stays byte-identical.
- The prod sequence: take the deploy lock (non-blocking); write the template and listener; daemon-reload; migrate the legacy `peertube-engine.service` (stop, disable, rm, daemon-reload); read, create or validate the snippet; bring up the snippet's instance (restart only with `--force`), enable it and disable the other; then `nginx -t`, reload, and a health check on 7079.
- Dev keeps lines 170-244 unchanged.

**Code that must change.**
- The `--force` block (205-214) acts on `${ENGINE_SERVICE_NAME}.service`, which is the wrong unit in prod.
- The enable/restart/verify lines (222-244), the `journalctl -u` call and the Status/Logs hints all use `${ENGINE_SERVICE_NAME}.service`. In prod they need `peertube-engine@<port>`.
- The non-dry-run checks (163-167) must add `nginx`, `flock` and `curl` for prod.
- The dry-run block (191-202) must print the template, snippet and listener previews and the migration and port plan, and must write nothing.

**What depends on it.**
- `scripts/install-service.sh:308-323,344` calls it through `engine_cmd`.
- `--print-default-service-name` (311-315) must keep printing `peertube-engine`. `scripts/install-service.sh:147-155` and `updater-worker.py:38-79` read it.
- `install_updater_with_timer` (126-145) passes `--engine-service-name`.
- The deploy script and the updater read the snippet.

**Risks.**
- **Migration outage.** Migration stops the live Engine once.
- **Drop-ins lost.** Drop-ins under `/etc/systemd/system/peertube-engine.service.d/` (DEPLOYMENT.md §7, lines 447-448, has operators create one for `RECOMMENDATIONS_DEBUG`) do not apply to the template instances. The installer should warn about them or move them to `peertube-engine@.service.d/`.
- **Old updater unit.** An Engine-only reinstall leaves the old updater unit running `systemctl stop peertube-engine`, so its next run fails at the stop. It fails safe, but stays broken until the updater installer is re-run.
- **nginx becomes mandatory.** A host without nginx, or without the `conf.d` include, now fails the prod install.
- **Invalid snippet.** An invalid snippet must fail before any stop.
- **Dry-run reads `/etc/nginx`.** The dry-run port plan reads the snippet, so it needs the same env override, or the pytest reads the real host file.
- **Lock path.** The lock path comes from `PROJECT_DIR` after `realpath` (line 308). A `--project-dir` that differs from the checkout gives a different lock than the one the deploy script uses.
- **Lock file owner.** Root creates the lock file as root `0644` inside the service user's directory. That is harmless for flock, but the updater must open it `O_RDONLY`.
- **`--service-name` in prod.** It is still accepted (line 261). If honoured in prod, it diverges from the hard-coded `peertube-engine@`. Reject it or ignore it, and say which.
- **Snippet mode.** The snippet must be written `0644`.
</impact>
<impact path="engine/install-engine-service.sh" element="argument parsing --host/--port (265-272), DEFAULT_PROD_ENGINE_PORT/resolve_default_engine_port (23, 111-118), print_usage (26-61)">
**What changes.** `--host` and `--port` are rejected with `--mode prod`. In prod the port now comes from the snippet, or 7070 on first install. The usage text at lines 35 and 43-44 must describe the template, the 7070/7071 pair, the nginx files and the prod rejection.

**What depends on it.** `scripts/install-service.sh:315-316` always passes both options, so it must change in the same phase. `tests/run-installers-smoke.sh` calls `--help`.

**Risk.** If the two installers change in different phases, the central prod install breaks. Dev must keep accepting both options: usage line 57 and DEPLOYMENT.md pass `--port 7171`.
</impact>
<impact path="engine/install-engine-service.sh" element="generated files /etc/nginx/peertube-engine-upstream.conf (snippet) and /etc/nginx/conf.d/peertube-engine-internal.conf (listener)">
**What changes.** Two new files.
- The snippet holds `upstream peertube_engine { server 127.0.0.1:<port>; }` with mode 0644.
- The listener has:
  - `listen 127.0.0.1:7079`;
  - an absolute `include` of the snippet;
  - `location /` with `proxy_pass http://peertube_engine`;
  - `proxy_set_header Host $http_host`;
  - `client_max_body_size` of at least 1 000 000;
  - `add_header X-Engine-Upstream $upstream_addr`;
  - no keepalive.

**Verified.**
- The Client's custom headers have no underscores, so nginx's default `underscores_in_headers off` passes them: `x-client-ip` (`client/backend/server.py:599`) and `X-Bridge-Token` (`client/backend/lib/engine_api_client.py:10`).
- The body cap is 1 000 000 (`server.py:80`).
- The longest Client timeout is 20 s (`server.py:79`), under nginx's 60 s default.
- The Client copies only `content-type` from Engine responses (`server.py:627,658`).
- With a single server in an upstream, nginx ignores `max_fails`, so the server is never marked down.

**Risks.**
- **`add_header` without `always`.** It is not emitted on nginx's own 5xx. That is fine for the 200 post-switch check.
- **Shared access log.** 7079 traffic shares the default `access.log` with the public site unless `access_log` is set. That pollutes the issue's "no 5xx spikes in nginx access log" check, because the updater stop window logs 502s.
- **Non-loopback listen.** Any non-loopback `listen` exposes the unauthenticated `/internal/*` routes.
- **Temp file inside `conf.d/`.** A temp file written inside `conf.d/` under a `.conf` name duplicates the listener.
</impact>
<impact path="engine/uninstall-engine-service.sh" element="prod branch (lines 105-141)">
**What changes.**
- Prod stops and disables `peertube-engine@7070` and `@7071`. It removes the template, any legacy `peertube-engine.service`, the listener, the snippet and the snippet backup.
- It then runs daemon-reload and reset-failed, plus `nginx -t` and a reload when nginx is present.
- Dev is unchanged. `MODE` defaults to `prod` here (line 7).

**Existing quirk.** Lines 130 and 132 redirect `run_cmd` output to `/dev/null`, which hides the `[dry-run]` echo. Today's dry-run therefore lists only the `rm`. New lines must not copy that redirect.

**What depends on it.** `scripts/uninstall-service.sh:243-257` passes `--service-name peertube-engine` and runs the Client uninstaller first. The smoke check `dry_uninstall_engine_prod_unit` greps for `peertube-engine`.

**Risks.**
- **Removal order.** Removing the snippet before the listener fails `nginx -t`.
- **No nginx.** The uninstall must not fail when nginx is absent.
- **Un-migrated hosts.** An un-migrated host must uninstall cleanly.
- **Keyed off the name.** The prod branch must not be keyed off `ENGINE_SERVICE_NAME`.
- **Leftovers.** The lock file and `.service.d` drop-ins are left behind.
</impact>
<impact path="engine/install-updater-service.sh" element="updater_exec (line 324), sudoers preview (364) and written rule (376), print_usage (40), dry-run prerequisites (239, 275-278)">
**What changes.**
- In prod, `updater_exec` gains `--engine-upstream-snippet /etc/nginx/peertube-engine-upstream.conf`.
- In prod the sudoers line, both the preview and the written file, becomes exactly four entries: `${systemctl_bin} stop|start peertube-engine@7070|7071`, with no `.service` suffix. Dev keeps its single-name rule.
- Usage line 40 changes.

**What depends on it.**
- `scripts/install-service.sh:213-244` and `engine/install-engine-service.sh:126-145` call it.
- `visudo -cf` (377) checks the rule.
- `scripts/uninstall-service.sh:181` removes `/etc/sudoers.d/${updater_service_name}-systemctl`, which keeps the same name.

**Risks.**
- **Literal match.** Any argv difference between the worker and the rule, such as a `.service` suffix or a different systemctl path, makes `sudo -n` fail mid-pipeline. The `finally` start then fails too, and prod is left down.
- **Literal vs derived names.** Literal entries silently ignore an `--engine-service-name` override, while derived ones follow it. Decide which.
- **Dry-run prerequisites.** Even in dry-run, it needs `systemctl` on PATH (275-276), a real `updater-worker.py`, an executable `venv/bin/python3` and an existing user (239). The pytest needs a stub `systemctl`.
- **Flag precedence.** `UPDATER_FLAGS` is appended after the fixed flags, so an operator's `--skip-systemctl` combined with the snippet argument has unclear precedence.
</impact>
<impact path="scripts/install-service.sh" element="install_contour() prod branch (246-354), --engine-port/--engine-host parsing (371-380), DEFAULT_PROD_ENGINE_PORT (45), print_usage (52-97)">
**What changes.**
- For prod, `engine_cmd` (308-317) stops passing `--host`/`--port`.
- `engine_ingest_base` (298-302) becomes `http://127.0.0.1:7079` for prod.
- `--engine-port` is refused for prod. `--engine-host` should be refused too, since it feeds both the Engine `--host` and the ingest URL.
- The port-collision check (294-296) and the echo lines (305-306) need prod wording.
- `--mode all` already forbids overrides (204-211).

**What depends on it.** Operators; DEPLOYMENT.md 170-174; README.md 65-77; the smoke check `dry_install_prod_engine_port`, which is already broken.

**Risks.**
- **Order.** The Engine installer must keep running before the Client (344-345), so the listener exists first.
- **Client restart.** The prod default `force_reinstall=1` (270-273) restarts the Client onto 7079 (the one-time migration) and restarts the active Engine in place on every run.
- **Dry-run.** In dry-run, `run_cmd` only echoes the sub-installer commands (139-145). The contract test must call the sub-installers directly.
</impact>
<impact path="scripts/uninstall-service.sh" element="uninstall_contour() engine_cmd (236-258), print_usage">
**What changes.** Probably no code change. It still passes `--service-name peertube-engine` for prod. The usage text could mention the nginx files.

**Order.** It removes the Client, then the Engine, then the updater (256-258).

**Risk.** Low, provided the Engine uninstaller's prod branch is independent of the name.
</impact>
<impact path="client/install-client-service.sh" element="DEFAULT_PROD_ENGINE_PORT (20), ENGINE_URL default (162-168), usage example (46)">
**What changes.** The prod default becomes `http://127.0.0.1:7079`, and the usage example on line 46 changes to match. Dev stays on 7171.

**What depends on it.** The generated `ExecStart` (197), which the deploy preflight matches literally. The central installer always passes `--engine-url`. The smoke `--help` check.

**Risk.** A direct Client install before the Engine listener exists gets refused connections. The order is documented but not enforced. Dry-run exits before the root check (205-221), so the pytest is safe.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request() HTTPError vs URLError branches (612-754); /api/health (289-299); DEFAULT_ENGINE_INGEST_BASE (46)">
**What changes.** No code change is planned. This entry checks the plan's Gotcha, and the Gotcha does not hold.

**Today.** With the Engine down, the connection is refused, which raises `URLError` (703-708). The Client retries once after 0.25 s, then answers a JSON 502 with `code: ENGINE_PROXY_UNAVAILABLE` and logs the WARNING `proxy request unavailable` (731-753).

**Behind nginx.** nginx answers its own 502 with an HTML body, which raises `HTTPError` and takes the branch at 655-686. The payload is non-empty, so the Client relays status 502 and nginx's `text/html` body to the browser. There is no retry and no `ENGINE_PROXY_UNAVAILABLE` code, and the log line is INFO `proxy request completed status=502`. A mid-request drop by the Engine, which today is the JSON `ENGINE_PROXY_FAILURE` (709-730), also becomes nginx HTML.

**Risk: medium.**
- Status codes are unchanged, but the body, the retry and the log level change.
- Log filters or alerts keyed on `ENGINE_PROXY_UNAVAILABLE` go quiet.
- nginx may expose its version unless `server_tokens off` is set.
- Restoring today's behaviour needs a small Client change: treat a non-JSON `HTTPError` 502/503/504 as a transport error. That conflicts with "no Python change" and needs an explicit decision, or the gotcha must be rewritten as a documented behaviour change.

`/api/health` never probes the Engine, so it is unaffected; it now shows `engine_ingest_base: http://127.0.0.1:7079`. `DEFAULT_ENGINE_INGEST_BASE` stays 7070 for manual runs.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="_post_json() HTTPError handling (49-59)">
**What changes.** No code change. With the Engine down behind nginx, `/internal/videos/resolve`, `/internal/videos/metadata` and `/internal/dislikes/centroids` get an HTML 502. `_post_json` swallows the `JSONDecodeError` and returns `(502, {})`, so callers raise `EngineApiError("… (HTTP 502): unknown error")`. `_publish_to_engine_bridge` (`server.py:1073-1076`) returns `engine bridge HTTP 502` instead of `engine bridge unavailable`.

**Risk.** Low. The outward fixed-text 502 through `_respond_engine_failure` (`server.py:417-421`) is unchanged. Only the log text differs.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="parse_args(): new --engine-upstream-snippet and --deploy-lock-file (82-293)">
**What changes.**
- `--engine-upstream-snippet` is new and defaults to None.
- `--deploy-lock-file` is new and defaults to `script_dir.parents[3] / "engine/server/db/engine-deploy.lock"`, using the same `repo_root` as line 84.
- `--service-name` and `resolve_default_engine_service_name` (38-79, 291-292) stay for dev and for the no-snippet path.

**What depends on it.** The prod `ExecStart` written by `install-updater-service.sh:324`. `engine/server/db/jobs/tests/test-orchestrator-smoke.py:455-467` passes neither new option and keeps today's path.

**Risk.** Low. The existing `--lock-file` (168-172; the updater's own single-run lock, `/tmp/peertube-browser-staging-sync.lock`, with O_EXCL plus a PID file) is easily confused with the deploy lock. Keep the names distinct and document both.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main() stop/start try/finally (1261-1345), systemctl_cmd() (409-420), new snippet-parse and deploy-lock helpers, fcntl import">
**What changes.** These steps run only when the snippet argument is set:
1. Poll a non-blocking `fcntl.flock` on the deploy lock for up to 30 minutes, and fail before the stop if it times out.
2. Parse the snippet strictly.
3. Resolve `peertube-engine@<port>` once into a local.
4. Stop that unit, and in the existing `finally` start the same local.
5. Release the lock after the start.

Without the argument, behaviour is byte-identical to today's.

**What depends on it.**
- `systemctl_cmd` builds `[bin, action, name]` with no suffix, plus `sudo -n`, which matches the literal sudoers entries.
- `tests/active/test_updater_worker.py::test_main_runs_similarity_stage_after_service_start` (307-326) requires all of the following:
  - exactly one `ast.Try` in `main` whose `finalbody` contains `systemctl_cmd(...)` with a literal `action="start"`;
  - `run_similarity_stage` once, after that try's `end_lineno`;
  - `build-ann-index.py` and `run_with_cpu_fallback` inside the try;
  - no `similarity_precompute_cmd` or `run_similarity_stage` inside it.
- These changes would break that test:
  - moving the start into a helper;
  - passing `action` through a variable;
  - nesting a try whose own `finalbody` also contains the start, which gives two matches. Nest the lock release as `try: start / finally: release` inside the outer `finally`; the inner `finalbody` then holds only the release.
  - wrapping the similarity stage inside the lock.

**Risk: high.**
- **Lock permissions.** A root-created `engine-deploy.lock` (written by the deploy or the installer) is root `0644`. Opening it for write raises `PermissionError` after hours of crawling. Use `O_RDONLY|O_CREAT`, since flock works on a read-only fd.
- **Snippet mode.** A `0600` snippet makes the parse fail.
- **Order.** The lock and the parse must both happen before `service_stopped = True` (1271), so a failure never starts a unit that was never stopped.
- **Lock release on a failed start.** If the start fails, the lock must still be released.
- **Deploys blocked.** The lock is held through merge, popularity and ANN rebuild, which can take tens of minutes. A deploy fails at `flock -n` in that window, as designed.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_get_client_ip() (315-330), _get_full_url() (332-338), /api/health rate limit (469-472, 604-616)">
**What changes.** No code change.
- `X-Client-IP` passes through nginx unchanged. Without it, the peer is nginx's 127.0.0.1, the same as today.
- `_get_full_url` logs `Host`, so Engine logs now show `127.0.0.1:7079`.
- `X-Request-ID` is not read from requests here (`request_context.py` sets its id internally), so the issue-20 compatibility is unaffected.

**Risk.** Low. The docstring (318-321) says "the gateway is its only reachable peer", which is now inexact (the same applies to ADR-0002). The deploy's probe budget must stay under 60 requests per 60 s.
</impact>
<impact path="engine/server/api/server.py" element="DEV_SERVER_PORT=7071 and --dev help (141, 159-179, 315); startup schema DDL (331-339); SIGTERM handling (298-311); FAISS mmap (350); daemon cache worker (511)">
**What changes.** No code change. During a deploy, two instances of one checkout run at once. Verified:
- there is no port-keyed PID file;
- the index is opened mmap read-only;
- SIGTERM becomes a graceful shutdown;
- the cache worker is a daemon thread, so a stop leaves `random-cache.tmp.<pid>.db` behind (deploy step 10).

**Risks.**
- **`--dev` port.** `--dev` binds 7071, the green port. A manual `server.py --dev` on a prod host breaks the deploy, or fools readiness. Change the default or document the clash; that needs an explicit decision.
- **Memory.** Peak RSS roughly doubles during the overlap: two query encoders and two Python heaps. This is a host-sizing risk the plan does not mention.
- **Startup DDL.** At startup, `ensure_moderation_schema`, `ensure_interaction_event_schema` and `ensure_*_indexes` run on the shared `whitelist.db` while the old instance serves (see the `db.py` entry).
- **Overlapping startup cache builds.** The two instances' startup random-cache builds overlap. Each uses its own per-pid temp file, so they do not collide.
</impact>
<impact path="engine/server/data/db.py" element="connect_db() (77-82): sqlite3 default 5 s busy timeout">
**What changes.** Nothing. `connect_db` passes no `timeout`, so it uses sqlite3's 5 s default.

**Risk: low to medium, and uncertain.** The startup DDL of the new instance (`interaction_events.py:19-54` commits) needs a write lock. The old instance may hold one during an ingest or a `/api/video` write; those are bounded by the 5 s deadline. A collision makes startup fail with "database is locked". `Restart=on-failure` retries, so this most likely costs only time, and in the worst case it ends in a readiness-timeout rollback. Whether the `CREATE … IF NOT EXISTS` statements take the lock when the objects already exist was not tested.
</impact>
<impact path="engine/server/data/random_cache.py" element="random_cache_temp_path()/remove_random_cache_temp() (197-205)">
**What changes.** No code change. The deploy reimplements `<stem>.tmp.<pid><suffix>` plus `-journal` in bash.

**Risk.** Low, but nothing ties the two implementations together. A rename here would silently break the deploy's cleanup.
</impact>
<impact path="engine/server/api/server_config.py" element="DEFAULT_SERVER_PORT=7070 (412), DEFAULT_RATE_LIMIT_MAX_REQUESTS/WINDOW_SECONDS (482-483)">
**What changes.** Nothing. The template always passes `--port`.

**Risk.** Lowering the rate limit later would make readiness polls return 429, ending in a spurious rollback.
</impact>
<impact path="engine/watch-engine-logs.sh" element="-prod → UNIT=peertube-engine.service (help line 12, 67-73, journalctl 150-156)">
**What changes.** This is needed, though the plan does not list it. After the migration, `journalctl -u peertube-engine.service` shows nothing for prod. Use `peertube-engine@*` (journalctl accepts a glob for `-u`) and update the help text.

**Risk.** Medium for operability. During a deploy, lines from both instances interleave.
</impact>
<impact path="scripts/run-services.sh" element="ENGINE_PORT=7070 default, --engine-port (13, 38, 58)">
**What changes.** Nothing; it is out of scope.

**Risk.** On a prod host it collides with the active or target instance, and it can fool readiness. The docs should warn against running it there.
</impact>
<impact path="scripts/run-reembed.sh" element="--restart-engine via run-services.sh restart (21-26, 61, 215-223)">
**What changes.** Nothing. This entry is listed so the next step does not treat it as missed.

**Risk.** On a systemd prod host, `--restart-engine` drives `run-services.sh`, not the units. That is pre-existing, but in prod it should now point operators at the deploy command. It is a doc-level concern only.
</impact>
<impact path="scripts/run-dataset-build.sh" element="final log line (275) 'restart the Engine so it loads the new index'">
**What changes.** Optional: in prod the restart is `scripts/deploy-bluegreen.sh --blue-green`.

**Risk.** None.
</impact>
<impact path="tests/active/test_deploy_bluegreen.py" element="new test module">
**What changes.** A new pytest. It copies the script into `tmp_path/scripts/` alongside `tmp_path/engine/server/db/`. It puts stub `systemctl`, `nginx`, `curl`, `logger` and `id` on PATH and sets the snippet env override. It covers every requirement case. Lock contention is tested with `fcntl.flock` held from the test process.

**What it depends on.** Real `bash` and `flock(1)` on the test host. Whether `flock` is on PATH in the pixi environment the suite runs under is not verified; no pixi manifest is tracked.

**Risks.**
- **Runtime.** Tests must pass `--drain 0`, `--warmup 0` and a small `--timeout`, because the 2 s and 1 s sleeps cost real time.
- **Ports.** Never touch the real 7070/7079, because an operator Engine runs on this machine.
- **Snippet mode.** Assert that the written snippet is world-readable.
- **Shared conftest.** `tests/active/conftest.py` imports the Client server module at import time (line 41). That is harmless, but the new tests must not use the `engine` fixture.
</impact>
<impact path="tests/active/test_updater_worker.py" element="new snippet/resolution/lock tests; existing AST tests (78-89, 307-326); _load_job (43-52)">
**What changes.** New tests:
- snippet parsing: 7070 and 7071 valid; missing file, foreign port and an extra server line rejected;
- resolution to `peertube-engine@<port>` with no suffix;
- stop and start use the same name;
- the lock opens read-only on an unwritable file.

The module loads through `_load_job`, so a new `fcntl` import is fine.

**Risk.** The existing AST test constrains how `main()` can be restructured (see the `main()` entry above). A shared snippet fixture with the deploy test is the only thing tying the two parsers together.
</impact>
<impact path="tests/active/test_installers_dry_run.py" element="new installer contract test (name to be chosen)">
**What changes.** A new pytest. It runs the Engine, updater (`--with-updater-timer`) and Client installers in `--dry-run` for prod and dev against a fake `--project-dir`. It asserts:
- `--port %i` in the template;
- the four exact sudoers entries;
- `--engine-upstream-snippet` in the updater `ExecStart`;
- the 7079 default in the Client installer;
- unchanged dev output.

**What it depends on.**
- A fake tree with `venv/bin/python3` (executable), `engine/server/api/server.py`, `engine/server/db/jobs/updater-worker.py`, `client/backend/server.py` and `engine/install-updater-service.sh`.
- The current user as the service user.
- A stub `systemctl` on PATH.
- The snippet override.

**Risk.** None, provided every installer handles dry-run before its root check.
</impact>
<impact path="tests/run-installers-smoke.sh" element="constants (33-45), dry-run matrix (812-886), root guard (1062)">
**What changes.** Nothing; the plan defers it. It is already broken: it calls `${ROOT_DIR}/install-service.sh`, `uninstall-service.sh` and wrapper scripts that do not exist, and line 1062 exits early. After this build these prod expectations also go stale:
- `PROD_ENGINE_PORT=7070` (37);
- `dry_install_prod_engine_port` expecting `127.0.0.1:7070` (836);
- the expected `engine_ingest_base`;
- the live prod path, which assumes a single unit.

**Risk.** None to the gating suite.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="hardcoded Engine port guard (line 28)">
**What changes.** Recommended: add 7079 to both `(7070|7071|7072|7171)` alternations.

**Risk.** None.
</impact>
<impact path="tests/check-client-engine-boundary.sh" element="Engine DB coupling guard (line 28)">
**What changes.** Nothing. The deploy-lock path and the preflight must stay out of `client/backend`, or the `engine/server/db/` pattern trips.

**Risk.** None if kept out.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="updater command builder (55-57, 455-467)">
**What changes.** Nothing. It passes `--service-name` (default `peertube-browser`, stale) and `--skip-systemctl` unless `--use-systemctl` is given, and never passes the snippet argument.

**Risk.** None.
</impact>
<impact path=".gitignore" element="local data patterns (10-19)">
**What changes.** Add `engine/server/db/engine-deploy.lock`. The existing `*.db*` patterns do not cover it.

**Risk.** Without the entry, the lock file shows as untracked on the prod checkout, and `git add -A` would commit it.
</impact>
<impact path="client/uninstall-client-service.sh" element="whole script">
**What changes.** Nothing. The Client unit name is unchanged, and it runs before the Engine uninstall.

**Risk.** None.
</impact>
<impact path="DEPLOYMENT.md" element="intro (4), units table (95-103), Day to day (116-126), updater timer (128-144), Triage (146-166), installer examples (168-202)">
**What changes.**
- Line 4 gets a prod qualifier.
- The units table shows `peertube-engine@.service` with `@7070`/`@7071`, and the Client row gets `--engine-url http://127.0.0.1:7079`.
- Day to day: the deploy command, `cat /etc/nginx/peertube-engine-upstream.conf`, and `journalctl -u 'peertube-engine@*'`.
- The updater paragraph (130): the active instance, the four sudoers entries, and the deploy lock with its 30-minute wait.
- New Triage rows: lock held, readiness timeout, `nginx -t` failure and rollback, `ROLLBACK FAILED`, finding the active port, the updater's lock-wait failure, and an unreadable snippet.
- Existing Triage rows 152, 156 and 164-166 name `peertube-engine`. They must name the active instance and the deploy or `@<active>` restart.
- New migration notes: the one-time outage, the Client restart, moving drop-ins, and reinstalling the updater.
- Note that a central `--force` restarts in place.
- The examples at 170-197 use root-level paths that no longer exist. That is pre-existing.

**Risk.** Operator instructions would otherwise name a unit that no longer exists.
</impact>
<impact path="DEPLOYMENT.md" element="§4 (240-259), §5 (274-283), §6 nginx (302-385), Firewall (387-391), §7 debug drop-in (445-450) and seed= (452), §8 (454-503)">
**What changes.**
- §4 and §5: manual runs stay on 7070. Add a note that prod uses the pair behind 7079.
- §6:
  - the 7079 loopback listener in `conf.d` and the snippet;
  - the `conf.d` include requirement;
  - the public site file is unchanged;
  - `X-Engine-Upstream`;
  - the access log.
- Firewall (390): never open 7070, 7071, 7072 or 7079.
- §7 (447-448): the drop-in goes on `peertube-engine@` and is followed by a deploy.
- §7 (452): `seed=` goes to the active port.
- §8: the smoke prod expectations are stale.
- New: the deploy options and defaults, with the reason for the 30 s drain.
- New: the Client now relays nginx's HTML 502 while the Engine is down.
- New: warnings against `server.py --dev` and `run-services.sh` on a prod host.

**Risk.** The public site block must not gain the internal listener.
</impact>
<impact path="DATA_BUILD.md" element="Upgrade order step 4 (172), 'Stop the Engine before running such a build' (268)">
**What changes.** Step 4's "Restart the Engine" becomes the deploy command in prod; migrate `whitelist.db` before deploying. The note at line 268 should say that in prod both instances count, so stop the active instance or avoid the full build while one is up.

**Risk.** None in code.
</impact>
<impact path="engine/server/db/jobs/docs/UPDATER_WORKER.md" element="Execution Order 1/7/12/14 (41, 57, 62, 75), Lock Behavior (134-138), Service Stop/Start (146-154), Important Flags (164-183), Systemd Run (200-223)">
**What changes.**
- Steps 7 and 12: the active instance comes from the snippet, and the deploy lock is taken before the stop and released after the start.
- Lock Behavior: distinguish the deploy lock from the updater's own `--lock-file`.
- Line 149: the stale `peertube-browser` becomes `peertube-engine@<active>` in prod.
- Flags: add `--engine-upstream-snippet` and `--deploy-lock-file`.
- Line 206: the four sudoers entries.
- Lines 209-211 (`OnBootSec`, `Persistent=true`) are stale, pre-existing and optional to fix.

**Risk.** None in code.
</impact>
<impact path="engine/server/README.md" element="seed= note (line 28)">
**What changes.** "Sent straight to the Engine" means the active instance's port in prod, from the snippet, or through 7079.

**Risk.** None.
</impact>
<impact path="README.md" element="service installers/uninstallers (59-115)">
**What changes.** Add a pointer to `scripts/deploy-bluegreen.sh --blue-green` and to DEPLOYMENT.md. The root-level installer paths are stale and should read `scripts/`; that is pre-existing and optional. No prod unit name or 7070-only mention was found.

**Risk.** None.
</impact>
<impact path="client/README.md" element="Run Backend Locally (line 58)">
**What changes.** Optional: one sentence saying the prod unit uses `--engine-url http://127.0.0.1:7079`. The manual 7070 example stays valid.

**Risk.** None.
</impact>
<impact path="docs/project/adr/0002-trusted-proxy-client-address.md" element="Decision item 4 (19), Consequences (24)">
**What changes.** Item 4 bases the Engine's trust on the Client being its only peer. In prod the peer is now the loopback nginx 7079 listener, which forwards `X-Client-IP` verbatim. Add an amendment.

**Risk.** None.
</impact>
<impact path="docs/project/adr/0008-similarity-cache-handoff-through-files.md" element="Context line 12">
**What changes.** Nothing. The ADR already anticipates 7070 and 7071 from one checkout. It is listed as confirmation.

**Risk.** None.
</impact>
<impact path="docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md" element="new ADR (proposed, optional per docs/project/domain.md)">
**What changes.** A new ADR covering:
- the 7079 hop;
- the snippet as single source of truth;
- the lock in `engine/server/db/`;
- the two parsers;
- the rejected alternatives (Client restart, `SO_REUSEPORT`, a state file, a two-server upstream, `/run/lock`, `--print-active-port`).

**Risk.** None.
</impact>
<impact path="CONTEXT.md" element="glossary">
**What changes.** Optional terms: "Active instance" and "Upstream snippet".

**Risk.** None.
</impact>
<impact path="docs/project/issues/26-zero-downtime-deploy.md" element="Status line (3)">
**What changes.** At harvest, the status changes from `enhancement, needs-triage` to `complete`, and the file moves to `docs/project/issues/archive/`.

**Risk.** None.
</impact>
<impact path="docs/project/roadmap.md" element="runtime reliability chain (157), F4-M7 note (117)">
**What changes.** At harvest, mark `26` delivered.

**Risk.** None.
</impact>
<impact path="peertube-browser-service-review.md" element="install footprint (15-20), sudoers line (31)">
**What changes.** Nothing is required, since it is a historical review. After this build, line 20's "no nginx" and line 31's single-unit sudoers rule are false. Annotate them only if the operator wants that.

**Risk.** None.
</impact>
<impact path="docs/project/security-audit/run-2/architecture.md" element="Engine 127.0.0.1:7070 row (run-1/architecture.md likewise)">
**What changes.** Nothing. These are dated audit snapshots.

**Risk.** None.
</impact>
</impacts>

## Documentation to update

- [x] `DEPLOYMENT.md` - updated: I updated DEPLOYMENT.md for the prod blue/green Engine. It now covers the instance pair, the 7079 listener, the deploy command, rollback, the updater lock, the new Triage rows and the installer rules.
- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - updated: I updated UPDATER_WORKER.md so it describes how the updater stops and starts the active `peertube-engine@<port>` instance in prod while holding the deploy lock. I checked every claim against `updater-worker.py` and `engine/install-updater-service.sh`.
- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md: the schema-upgrade restart and the "stop the Engine before a `--recreate-out-db` build" warning now cover the prod blue/green Engine.
- [x] `README.md` - updated: README.md now has a short "Restarting the prod Engine" section with the blue/green deploy command, and the central installer and uninstaller paths are corrected to `scripts/`.
- [x] `client/README.md` - updated: I updated `client/README.md` for prod, where the Client reaches the Engine through nginx on `127.0.0.1:7079`. I checked each claim against `client/backend/server.py` and `client/install-client-service.sh`.
- [x] `docs/project/adr/0002-trusted-proxy-client-address.md` - updated: ADR-0002 now says the Engine's trust in `X-Client-IP` rests on the loopback-only 7079 nginx hop as well as the Engine's own loopback bind.
- [x] `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md` - updated: Created ADR-0009 (Status: proposed). It records the Engine blue/green design: the loopback 7079 hop, the snippet as the only source of truth, the shared deploy lock, the two parsers tied to one fixture, phase-driven rollback, and the rejected alternatives.
- [x] `CONTEXT.md` - updated: I added two glossary entries to CONTEXT.md: **Active instance** and **Upstream snippet**.
- [x] `docs/project/issues/26-zero-downtime-deploy.md` - updated: Issue 26 is now marked `enhancement, complete` with a Delivered comment. The file is still in `docs/project/issues/` and has to be moved to `archive/` at harvest.
- [x] `docs/project/roadmap.md` - updated: I marked issue `26` as delivered in `docs/project/roadmap.md` and added a Delivered entry for it.
- [x] `engine/server/README.md` - out of scope: Line 28 says `seed=` works only on requests sent straight to the Engine. That stays true: the active instance's port and the 7079 listener both reach the Engine with the query unchanged. The sentence names no port or unit, so nothing in it is false. The port detail belongs in DEPLOYMENT.md §7.
- [x] `engine/watch-engine-logs.sh` - out of scope: Phase 3 already updated it. Help line 12 reads `Use peertube-engine@* (both blue/green instances)`, and `-prod` sets `UNIT="peertube-engine@*"`.
- [x] `docs/project/adr/0008-similarity-cache-handoff-through-files.md` - out of scope: Context line 12 already anticipates Engines on 7070 and 7071 from one checkout, and the build relies on that inode-swap handoff unchanged.
- [x] `peertube-browser-service-review.md` - out of scope: This is a dated historical review. Its "no nginx" and single-unit sudoers statements describe the system as reviewed at the time, not the current state.
- [x] `docs/project/security-audit/run-2/architecture.md` - out of scope: This is a dated audit snapshot (run-1 likewise). Its Engine `127.0.0.1:7070` row records the system as audited.

## Implementation plan


# Draft implementation: Engine blue/green deploy behind a loopback nginx upstream (issue 26)

The template's `{rat_tail_ladder}` placeholder came through unfilled, so no ladder text was supplied. I wrote the draft against the repo's own convention instead: a source-scan test carries a `# rat-tail:` comment naming the harness that would replace it, as `tests/active/test_updater_worker.py:80,309` do.

## 0. What the build has to test (ladder step 1)

| Behaviour | Where it is proven | How |
|---|---|---|
| Snippet parse rule (bash and Python agree) | `test_deploy_bluegreen.py::test_bash_parser_matches_cases`, `test_updater_worker.py::test_parse_upstream_snippet_cases` | One JSON case file read by both tests |
| Flip 7070→7071 and 7071→7070 | deploy test | Stub `systemctl`/`nginx`/`curl`/`logger`/`id`. Checks call order, snippet bytes, file mode `0644` |
| Rollback on readiness timeout, unit failure, `nginx -t` failure, reload failure, post-switch failure | deploy test | Scripted stub sequences |
| `ROLLBACK FAILED` path | deploy test | `nginx -t` fails on both the switch and the restore |
| Refusals: no `--blue-green`, lock held, updater active or activating, invalid or missing snippet, non-root, Client not on 7079, foreign listener on the target port | deploy test | No state-changing call in the stub log |
| Leftover target instance is restarted, not reused | deploy test | `stop @7071` comes before `start @7071` |
| `random-cache.tmp.<old pid>.db` and `-journal` removed; a decoy kept | deploy test | Files in `tmp/engine/server/db/` |
| Log fields | deploy test | Read the `logger` stub's log |
| `--dry-run` changes nothing | deploy test | Only `is-active` queries; no lock file; snippet unchanged |
| Updater resolves the instance, holds the lock read-only, stops and starts the same unit | `test_updater_worker.py` | Unit tests plus a `# rat-tail:` AST scan |
| Installer output: template `--port %i`, the four sudoers entries, `--engine-upstream-snippet`, Client default 7079, dev unchanged | `test_installers_dry_run.py` | `--dry-run` against a fake project tree |

## 1. Module map

| File | Change |
|---|---|
| `engine/engine-upstream.sh` **(new, sourced)** | The only place that defines the paths, the snippet format and the bash parser. It is sourced by the Engine installer, the Engine uninstaller, the updater installer and the deploy script. This is a departure from the plan; see §9 D1 |
| `scripts/deploy-bluegreen.sh` **(new)** | The deploy (§3) |
| `engine/install-engine-service.sh` | New `install_engine_prod()`. `--host`/`--port` and a non-default `--service-name` are refused in prod. Dev path unchanged |
| `engine/uninstall-engine-service.sh` | New prod branch. Dev path unchanged |
| `engine/install-updater-service.sh` | Prod `ExecStart` gains `--engine-upstream-snippet`. Prod sudoers rule becomes four literal entries |
| `scripts/install-service.sh` | Prod drops `--host`/`--port` from `engine_cmd`, refuses `--engine-port`/`--engine-host`, and sets ingest to `http://127.0.0.1:7079` |
| `client/install-client-service.sh` | Prod default `--engine-url http://127.0.0.1:7079`; usage text updated |
| `engine/server/db/jobs/updater-worker.py` | `fcntl`, `re`; snippet, unit and lock helpers; two new arguments; `main()` stop/start restructured so the existing AST test still holds |
| `engine/watch-engine-logs.sh` | `-prod` → `UNIT="peertube-engine@*"`; help line 12 |
| `.gitignore` | `engine/server/db/engine-deploy.lock` |
| `tests/check-frontend-client-gateway.sh` | Add `7079` to both alternations on line 28 |
| `tests/active/upstream_snippet_cases.json` **(new)** | Shared parser cases |
| `tests/active/test_deploy_bluegreen.py` **(new)**, `tests/active/test_installers_dry_run.py` **(new)**, `tests/active/test_updater_worker.py` (additions) | §7 |
| Docs | Settled list, §8 |

Constants, in one table:

| Name | Value | Lives in |
|---|---|---|
| `ENGINE_INSTANCE_BASE` | `peertube-engine` | `engine-upstream.sh`, `updater-worker.py` |
| `ENGINE_INSTANCE_PORTS` | `7070 7071` | both |
| `ENGINE_LISTENER_PORT` | `7079` | `engine-upstream.sh` |
| `UPSTREAM_SNIPPET` | `${PEERTUBE_ENGINE_UPSTREAM_SNIPPET:-/etc/nginx/peertube-engine-upstream.conf}` | `engine-upstream.sh` |
| `ENGINE_LISTENER_CONF` | `/etc/nginx/conf.d/peertube-engine-internal.conf` | `engine-upstream.sh` |
| Snippet backup | `${UPSTREAM_SNIPPET}.bak` (outside `conf.d`, not `*.conf`) | deploy, uninstaller |
| Deploy lock | `<repo>/engine/server/db/engine-deploy.lock` | `engine_deploy_lock_path`, `--deploy-lock-file` default |
| Deploy log tag | `peertube-engine-deploy` | deploy |
| Readiness poll / probe `--max-time` / post-switch attempts | 2 s / 5 s / 10 × 1 s | deploy |
| Updater lock wait / poll | 1800 s / 5 s | `updater-worker.py` |

Rate-limit budget on the new instance's `127.0.0.1` bucket (60 per 60 s), worst 60 s window: 30 readiness polls + 1 warm-up recheck + 10 post-switch probes = 41. A 429 counts as "not ready".

## 2. `engine/engine-upstream.sh` (sourced library)

```bash
#!/usr/bin/env bash
# engine-upstream.sh - shared by the Engine installers and scripts/deploy-bluegreen.sh. Sourced, never run.
# The nginx upstream snippet is the single source of truth for which prod Engine instance (7070 or 7071) takes traffic.
# Its parse rule is mirrored by parse_upstream_snippet() in engine/server/db/jobs/updater-worker.py; tests/active/upstream_snippet_cases.json pins both.

ENGINE_INSTANCE_BASE="peertube-engine"
ENGINE_INSTANCE_PORTS=(7070 7071)
ENGINE_LISTENER_PORT=7079
# Overridable for tests only; production uses the default.
UPSTREAM_SNIPPET="${PEERTUBE_ENGINE_UPSTREAM_SNIPPET:-/etc/nginx/peertube-engine-upstream.conf}"
ENGINE_LISTENER_CONF="/etc/nginx/conf.d/peertube-engine-internal.conf"

# Print the deploy lock path for a repository root. Deploy, installer and updater all derive it the same way.
engine_deploy_lock_path() {
  printf '%s' "$1/engine/server/db/engine-deploy.lock"
}

# Print the active port: exactly one line starting with `server`, and that line is `server 127.0.0.1:7070;` or `…7071;`. Non-zero otherwise, including a missing or unreadable file.
read_active_port() {
  local path="$1" count line
  [[ -f "${path}" && -r "${path}" ]] || return 1
  count="$(grep -cE '^[[:blank:]]*server([[:blank:]]|$)' "${path}" || true)"
  [[ "${count}" == "1" ]] || return 1
  line="$(grep -E '^[[:blank:]]*server[[:blank:]]+127\.0\.0\.1:(7070|7071);[[:blank:]]*$' "${path}")" || return 1
  line="${line##*:}"
  printf '%s' "${line%%;*}"
}

# Print the other port of the pair.
other_instance_port() {
  if [[ "$1" == "7070" ]]; then printf '7071'; else printf '7070'; fi
}

# Print the snippet for a port. Three lines; nothing else lives in the file.
snippet_text() {
  printf 'upstream peertube_engine {\n    server 127.0.0.1:%s;\n}\n' "$1"
}

# Print the loopback listener. It must never listen beyond 127.0.0.1: Engine /internal/* accepts writes without authentication.
engine_listener_text() {
  cat <<EOF_LISTENER
# Managed by engine/install-engine-service.sh: the Client reaches the active prod Engine instance through this loopback hop.
# Loopback only. Never add another listen: the Engine has no authentication and /internal/* accepts writes.
include ${UPSTREAM_SNIPPET};

server {
    listen 127.0.0.1:${ENGINE_LISTENER_PORT};
    server_name _;
    server_tokens off;
    access_log /var/log/nginx/peertube-engine-internal.access.log;
    # At or above the Client's ENGINE_PROXY_MAX_BODY_BYTES (1000000), so this hop never adds a 413.
    client_max_body_size 2m;

    location / {
        # No keepalive to the upstream: after a reload no connection stays pinned to the old port.
        proxy_pass http://peertube_engine;
        proxy_set_header Host \$http_host;
        # Read by scripts/deploy-bluegreen.sh's post-switch check. The Client copies only content-type, so browsers never see it.
        add_header X-Engine-Upstream \$upstream_addr;
    }
}
EOF_LISTENER
}

# Replace a file atomically from stdin with mode 0644. The temp file sits in the destination's directory under a dotted name that does not end in .conf, so nginx never includes it. 0644 lets the updater (service user) read the snippet.
replace_file() {
  local dest="$1" tmp
  tmp="$(mktemp "$(dirname "${dest}")/.$(basename "${dest}").XXXXXX")" || return 1
  if cat > "${tmp}" && chmod 0644 "${tmp}" && mv -f "${tmp}" "${dest}"; then
    return 0
  fi
  rm -f "${tmp}"
  return 1
}
```

Parse-rule invariants:
- `[[:blank:]]` in bash and `[ \t]` in Python match exactly the same characters.
- Python splits lines on `"\n"` only, as `grep` does. A CRLF file is therefore rejected by both. `splitlines()` would have accepted it in Python, which is why it is not used.

## 3. `scripts/deploy-bluegreen.sh`

The file follows `run-services.sh` style:
- `set -uo pipefail`, with explicit `||` handling. There is no `-e`, because every failure has to route through `rollback`.
- The same root rule.
- `print_usage` prints the header comment block.

```bash
#!/usr/bin/env bash
#
# deploy-bluegreen.sh - restart the prod Engine on the code on disk with no gap for the Client.
#
# The Client reaches the Engine through nginx on 127.0.0.1:7079, whose upstream names one port of the
# fixed pair 7070/7071. This starts peertube-engine@<other port>, waits for its /api/health, points the
# upstream snippet at it, checks 7079, drains and stops the old instance. A failure before the switch
# is verified rolls back on its own and the old instance keeps serving.
#
# Usage:
#   sudo bash scripts/deploy-bluegreen.sh --blue-green [options]
#
# Options:
#   --blue-green      Required. Without it this help is printed and the exit code is 2.
#   --timeout <sec>   How long the new instance may take to answer /api/health 200 (default: 300).
#   --warmup <sec>    Extra wait after the first healthy answer, then one more check (default: 0).
#   --drain <sec>     Wait between the switch and stopping the old instance (default: 30; the
#                     Client's longest Engine request timeout is 20 s).
#   --dry-run         Print the active and target ports and every planned action; change nothing.
#   -h, --help        Show this help.
#
# Active port: cat /etc/nginx/peertube-engine-upstream.conf   Logs: journalctl -t peertube-engine-deploy

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Same root rule as run-services.sh: this lives in scripts/ and operates on the repository root.
if [[ ! -d "${SCRIPT_DIR}/engine" && -d "${SCRIPT_DIR}/../engine" ]]; then
  SCRIPT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
# shellcheck source=../engine/engine-upstream.sh
source "${SCRIPT_DIR}/engine/engine-upstream.sh"

DB_DIR="${SCRIPT_DIR}/engine/server/db"
LOCK_FILE="$(engine_deploy_lock_path "${SCRIPT_DIR}")"
SNIPPET_BACKUP="${UPSTREAM_SNIPPET}.bak"
# Overridable for tests only: the developer machine may carry a real prod Client unit.
CLIENT_UNIT_PATH="${PEERTUBE_CLIENT_UNIT_PATH:-/etc/systemd/system/peertube-client.service}"
UPDATER_UNIT="peertube-updater.service"
LOG_TAG="peertube-engine-deploy"
READY_POLL_SECONDS=2
SWITCH_CHECK_ATTEMPTS=10
PROBE_MAX_TIME=5

BLUE_GREEN=0
HEALTH_TIMEOUT=300
WARMUP_SECONDS=0
DRAIN_SECONDS=30
DRY_RUN=0

DEPLOY_ID="$(date -u '+%Y%m%dT%H%M%SZ')-$$"
PHASE="init"
ACTIVE_PORT=""
TARGET_PORT=""
FAIL_REASON=""
EXIT_CODE=0

# Print the usage block from this file's header.
print_usage() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --blue-green) BLUE_GREEN=1; shift ;;
    --timeout) HEALTH_TIMEOUT="${2:-}"; shift 2 ;;
    --warmup) WARMUP_SECONDS="${2:-}"; shift 2 ;;
    --drain) DRAIN_SECONDS="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) print_usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
  esac
done

if (( BLUE_GREEN == 0 )); then
  echo "ERROR: --blue-green is required." >&2
  print_usage >&2
  exit 2
fi
[[ "${HEALTH_TIMEOUT}" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: --timeout must be a positive integer: ${HEALTH_TIMEOUT}" >&2; exit 2; }
[[ "${WARMUP_SECONDS}" =~ ^[0-9]+$ ]] || { echo "ERROR: --warmup must be a non-negative integer: ${WARMUP_SECONDS}" >&2; exit 2; }
[[ "${DRAIN_SECONDS}" =~ ^[0-9]+$ ]] || { echo "ERROR: --drain must be a non-negative integer: ${DRAIN_SECONDS}" >&2; exit 2; }

# Emit one deploy_id-tagged line to stdout and journald. Children get fd 9 closed so none of them outlives the lock.
log_event() {
  local line="deploy_id=${DEPLOY_ID} event=$*"
  echo "${line}"
  if (( DRY_RUN == 0 )); then
    logger -t "${LOG_TAG}" -- "${line}" 9>&- 2>/dev/null || true
  fi
}

# Stop before any change and exit 1.
refuse() {
  log_event "refused reason=$*"
  echo "ERROR: deploy refused: $*" >&2
  exit 1
}

# Sleep where a trapped INT/TERM interrupts at once instead of after the sleep.
pause() {
  sleep "$1" 9>&- &
  wait "$!"
}

unit_state() {
  systemctl is-active "$1" 2>/dev/null || true
}

# Print the HTTP status for a URL, 000 when nothing answers.
http_status() {
  curl -s -o /dev/null -w '%{http_code}' --max-time "${PROBE_MAX_TIME}" "$1" 9>&- 2>/dev/null || true
}

# Print every flag that is not already a key=value pair as one; used for state dumps.
state_dump() {
  printf 'snippet="%s" old_state=%s new_state=%s' "$(tr '\n' ' ' < "${UPSTREAM_SNIPPET}" 2>/dev/null)" "$(unit_state "${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}")" "$(unit_state "${ENGINE_INSTANCE_BASE}@${TARGET_PORT}")"
}

# A step inside rollback failed: say so loudly with the state left behind, and stop.
rollback_failed() {
  log_event "rollback_failed msg=\"ROLLBACK FAILED\" at=$1 phase=${PHASE} $(state_dump)"
  echo "ROLLBACK FAILED at $1 (phase ${PHASE}). $(state_dump)" >&2
  exit 1
}

# Undo by phase. pre-switch: stop the target. switching: restore the snippet, nginx -t, reload, stop the target. switched: traffic is already on the target, so log and mark the exit non-zero.
rollback() {
  local step="$1" reason="$2"
  trap '' INT TERM
  if [[ "${PHASE}" == "switched" ]]; then
    log_event "post_switch_failure step=${step} reason=${reason} rollback=none"
    EXIT_CODE=1
    trap 'on_signal INT' INT
    trap 'on_signal TERM' TERM
    return 0
  fi
  log_event "rollback phase=${PHASE} step=${step} reason=${reason} old_port=${ACTIVE_PORT} new_port=${TARGET_PORT}"
  case "${PHASE}" in
    init) ;;
    pre-switch)
      systemctl stop "${ENGINE_INSTANCE_BASE}@${TARGET_PORT}" || rollback_failed "stop_target"
      ;;
    switching)
      replace_file "${UPSTREAM_SNIPPET}" < "${SNIPPET_BACKUP}" || rollback_failed "restore_snippet"
      nginx -t >/dev/null 2>&1 || rollback_failed "restore_nginx_test"
      systemctl reload nginx || rollback_failed "restore_nginx_reload"
      systemctl stop "${ENGINE_INSTANCE_BASE}@${TARGET_PORT}" || rollback_failed "stop_target"
      ;;
  esac
  log_event "rollback_done phase=${PHASE} step=${step} serving_port=${ACTIVE_PORT}"
  exit 1
}

on_signal() {
  log_event "signal name=$1 phase=${PHASE}"
  if [[ "${PHASE}" == "switched" ]]; then
    exit 1
  fi
  rollback "signal" "SIG$1"
}

# Poll the target until /api/health is 200 with the unit active. 429 or a refused connection means not ready; failed/inactive ends the wait at once.
wait_ready() {
  local port="$1" unit="${ENGINE_INSTANCE_BASE}@$1" started="${SECONDS}" state status="000"
  while :; do
    state="$(unit_state "${unit}")"
    if [[ "${state}" == "failed" || "${state}" == "inactive" ]]; then
      log_event "readiness_failed port=${port} unit_state=${state} last_status=${status} waited_s=$(( SECONDS - started ))"
      FAIL_REASON="unit_${state}"
      return 1
    fi
    status="$(http_status "http://127.0.0.1:${port}/api/health")"
    if [[ "${status}" == "200" && "${state}" == "active" ]]; then
      log_event "ready port=${port} status=200 waited_s=$(( SECONDS - started ))"
      return 0
    fi
    if (( SECONDS - started >= HEALTH_TIMEOUT )); then
      log_event "readiness_timeout port=${port} unit_state=${state} last_status=${status} waited_s=$(( SECONDS - started ))"
      FAIL_REASON="readiness_timeout"
      return 1
    fi
    pause "${READY_POLL_SECONDS}"
  done
}

# Ask 7079 until it answers 200 from the target. X-Engine-Upstream names the upstream nginx used, so an old worker still proxying to the old instance does not pass.
check_switched() {
  local want="127.0.0.1:${TARGET_PORT}" started="${SECONDS}" attempt out status="000" upstream=""
  for (( attempt = 1; attempt <= SWITCH_CHECK_ATTEMPTS; attempt++ )); do
    out="$(curl -s -o /dev/null -D - -w '%{http_code}' --max-time "${PROBE_MAX_TIME}" "http://127.0.0.1:${ENGINE_LISTENER_PORT}/api/health" 9>&- 2>/dev/null || true)"
    status="${out: -3}"
    upstream="$(printf '%s\n' "${out}" | tr -d '\r' | awk 'tolower($1) == "x-engine-upstream:" { value = $2 } END { print value }')"
    if [[ "${status}" == "200" && "${upstream}" == "${want}" ]]; then
      log_event "post_switch_check status=200 upstream=${upstream} attempts=${attempt} waited_s=$(( SECONDS - started ))"
      return 0
    fi
    (( attempt < SWITCH_CHECK_ATTEMPTS )) && pause 1
  done
  log_event "post_switch_check_failed last_status=${status:-000} upstream=${upstream:-none} want=${want} waited_s=$(( SECONDS - started ))"
  FAIL_REASON="post_switch_check"
  return 1
}

# The old instance's interrupted random-cache build: <stem>.tmp.<pid><suffix> plus -journal, as random_cache_temp_path()/remove_random_cache_temp() name them (engine/server/data/random_cache.py).
remove_random_cache_temp() {
  local pid="$1" path removed=0
  if [[ ! "${pid}" =~ ^[1-9][0-9]*$ ]]; then
    log_event "cache_cleanup skipped=no_pid"
    return 0
  fi
  for path in "${DB_DIR}/random-cache.tmp.${pid}.db" "${DB_DIR}/random-cache.tmp.${pid}.db-journal"; do
    if [[ -e "${path}" ]]; then
      rm -f -- "${path}" || { log_event "cache_cleanup_failed path=${path}"; return 1; }
      removed=$(( removed + 1 ))
    fi
  done
  log_event "cache_cleanup pid=${pid} removed=${removed}"
}

# Print the Client preflight verdict: absent | ok | wrong.
client_preflight() {
  [[ -f "${CLIENT_UNIT_PATH}" ]] || { printf 'absent'; return 0; }
  if grep -qE -- "--engine-url http://127\.0\.0\.1:${ENGINE_LISTENER_PORT}( |$)" "${CLIENT_UNIT_PATH}"; then printf 'ok'; else printf 'wrong'; fi
}

print_dry_run() {
  local updater_state client_state target_state
  updater_state="$(unit_state "${UPDATER_UNIT}")"
  client_state="$(client_preflight)"
  target_state="$(unit_state "${ENGINE_INSTANCE_BASE}@${TARGET_PORT}")"
  echo "[dry-run] deploy-bluegreen deploy_id=${DEPLOY_ID}"
  echo "  repo=${SCRIPT_DIR}"
  echo "  snippet=${UPSTREAM_SNIPPET} active_port=${ACTIVE_PORT} target_port=${TARGET_PORT}"
  echo "  updater=${UPDATER_UNIT} state=${updater_state}"
  echo "  client_unit=${CLIENT_UNIT_PATH} preflight=${client_state}"
  echo "  lock=${LOCK_FILE}"
  echo "  timeout=${HEALTH_TIMEOUT}s warmup=${WARMUP_SECONDS}s drain=${DRAIN_SECONDS}s"
  echo "  actions:"
  echo "    1. flock -n ${LOCK_FILE}; refuse if ${UPDATER_UNIT} is active|activating|deactivating|reloading; refuse unless the Client unit uses --engine-url http://127.0.0.1:${ENGINE_LISTENER_PORT}"
  echo "    2. systemctl stop ${ENGINE_INSTANCE_BASE}@${TARGET_PORT} (only if not inactive; now: ${target_state}); refuse if 127.0.0.1:${TARGET_PORT} still answers"
  echo "    3. systemctl start ${ENGINE_INSTANCE_BASE}@${TARGET_PORT}"
  echo "    4. poll http://127.0.0.1:${TARGET_PORT}/api/health every ${READY_POLL_SECONDS}s up to ${HEALTH_TIMEOUT}s; warm-up ${WARMUP_SECONDS}s and one more check"
  echo "    5. cp ${UPSTREAM_SNIPPET} ${SNIPPET_BACKUP}; write snippet naming 127.0.0.1:${TARGET_PORT} (temp + rename, 0644); nginx -t; systemctl reload nginx"
  echo "    6. check http://127.0.0.1:${ENGINE_LISTENER_PORT}/api/health = 200 with X-Engine-Upstream 127.0.0.1:${TARGET_PORT} (${SWITCH_CHECK_ATTEMPTS} x 1s)"
  echo "    7. sleep ${DRAIN_SECONDS}; systemctl stop ${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}; systemctl enable ${ENGINE_INSTANCE_BASE}@${TARGET_PORT}; systemctl disable ${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}"
  echo "    8. rm -f ${DB_DIR}/random-cache.tmp.<MainPID of ${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}>.db{,-journal}"
}

if (( DRY_RUN == 1 )); then
  ACTIVE_PORT="$(read_active_port "${UPSTREAM_SNIPPET}")" || { echo "ERROR: ${UPSTREAM_SNIPPET} is missing or does not name exactly one of 127.0.0.1:7070/7071." >&2; exit 1; }
  TARGET_PORT="$(other_instance_port "${ACTIVE_PORT}")"
  print_dry_run
  exit 0
fi

[[ "$(id -u)" == "0" ]] || { echo "ERROR: run as root: sudo bash scripts/deploy-bluegreen.sh --blue-green" >&2; exit 1; }
for cmd in flock curl systemctl nginx logger; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "ERROR: required command not found: ${cmd}" >&2; exit 1; }
done
[[ -d "${DB_DIR}" ]] || { echo "ERROR: missing ${DB_DIR}" >&2; exit 1; }

# Step 1. The lock is bound to fd 9, so it is released on every exit, SIGKILL included.
exec 9>>"${LOCK_FILE}" || { echo "ERROR: cannot open ${LOCK_FILE}" >&2; exit 1; }
flock -n 9 || refuse "lock_held lock=${LOCK_FILE}"
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
log_event "lock_acquired lock=${LOCK_FILE}"

# Step 2. The updater is Type=oneshot: while it runs, is-active prints "activating".
updater_state="$(unit_state "${UPDATER_UNIT}")"
case "${updater_state}" in
  active|activating|deactivating|reloading) refuse "updater_running unit=${UPDATER_UNIT} state=${updater_state}" ;;
esac
[[ "$(client_preflight)" != "wrong" ]] || refuse "client_not_on_listener unit=${CLIENT_UNIT_PATH} want=--engine-url_http://127.0.0.1:${ENGINE_LISTENER_PORT}"

# Step 3.
ACTIVE_PORT="$(read_active_port "${UPSTREAM_SNIPPET}")" || refuse "snippet_invalid path=${UPSTREAM_SNIPPET}"
TARGET_PORT="$(other_instance_port "${ACTIVE_PORT}")"
OLD_UNIT="${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}"
NEW_UNIT="${ENGINE_INSTANCE_BASE}@${TARGET_PORT}"
log_event "start old_port=${ACTIVE_PORT} new_port=${TARGET_PORT} timeout_s=${HEALTH_TIMEOUT} warmup_s=${WARMUP_SECONDS} drain_s=${DRAIN_SECONDS}"

PHASE="pre-switch"
# Step 4: a leftover is restarted, never reused.
target_state="$(unit_state "${NEW_UNIT}")"
if [[ "${target_state}" != "inactive" ]]; then
  log_event "stop_leftover unit=${NEW_UNIT} state=${target_state}"
  systemctl stop "${NEW_UNIT}" || rollback "stop_leftover" "systemctl_stop_failed"
fi
leftover_status="$(http_status "http://127.0.0.1:${TARGET_PORT}/api/health")"
[[ "${leftover_status}" == "000" ]] || rollback "preflight_port" "port_in_use_by_foreign_process status=${leftover_status}"

# Step 5.
log_event "start_target unit=${NEW_UNIT}"
systemctl start "${NEW_UNIT}" || rollback "start_target" "systemctl_start_failed"

# Step 6.
wait_ready "${TARGET_PORT}" || rollback "readiness" "${FAIL_REASON}"
if (( WARMUP_SECONDS > 0 )); then
  pause "${WARMUP_SECONDS}"
  warm_status="$(http_status "http://127.0.0.1:${TARGET_PORT}/api/health")"
  log_event "warmup_check port=${TARGET_PORT} status=${warm_status} warmup_s=${WARMUP_SECONDS}"
  [[ "${warm_status}" == "200" ]] || rollback "warmup_check" "warmup_status_${warm_status}"
fi

# Step 7.
cp -p "${UPSTREAM_SNIPPET}" "${SNIPPET_BACKUP}" || rollback "snippet_backup" "cp_failed"
PHASE="switching"
snippet_text "${TARGET_PORT}" | replace_file "${UPSTREAM_SNIPPET}" || rollback "snippet_write" "write_failed"
log_event "snippet_written port=${TARGET_PORT}"
nginx -t >/dev/null 2>&1 || rollback "nginx_test" "nginx_test_failed"
systemctl reload nginx || rollback "nginx_reload" "nginx_reload_failed"
log_event "switched old_port=${ACTIVE_PORT} new_port=${TARGET_PORT} switch_time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Step 8.
check_switched || rollback "post_switch_check" "${FAIL_REASON}"
PHASE="switched"

# Step 9. The PID is recorded before the stop, for step 10.
old_pid="$(systemctl show -p MainPID --value "${OLD_UNIT}" 2>/dev/null || true)"
log_event "drain_begin unit=${OLD_UNIT} main_pid=${old_pid:-0} drain_s=${DRAIN_SECONDS}"
pause "${DRAIN_SECONDS}"
if systemctl stop "${OLD_UNIT}"; then log_event "old_stopped unit=${OLD_UNIT}"; else rollback "stop_old" "systemctl_stop_failed"; fi
if systemctl enable "${NEW_UNIT}" 2>/dev/null; then log_event "enabled unit=${NEW_UNIT}"; else rollback "enable_new" "systemctl_enable_failed"; fi
if systemctl disable "${OLD_UNIT}" 2>/dev/null; then log_event "disabled unit=${OLD_UNIT}"; else rollback "disable_old" "systemctl_disable_failed"; fi

# Step 10.
remove_random_cache_temp "${old_pid}" || rollback "cache_cleanup" "rm_failed"

# Step 11: the lock goes with fd 9 at exit.
log_event "done result=$([[ ${EXIT_CODE} == 0 ]] && echo ok || echo degraded) active_port=${TARGET_PORT} exit_code=${EXIT_CODE}"
exit "${EXIT_CODE}"
```

Invariants:
- **`PHASE` changes at exactly two points.**
  - It becomes `switching` immediately before the first write to the snippet, after the backup exists.
  - It becomes `switched` only after `check_switched` passes.
  - Rollback therefore never stops the old instance, and always restores a backup that exists.
- **In the `switched` phase, `rollback` returns instead of exiting.** Steps 9–10 continue and `EXIT_CODE=1`.
- **Exit codes:**
  - 2: usage error, or `--blue-green` missing. Exit 2 has no side effects; no lock file is created.
  - 1: every refusal and every failure.
  - 0: a clean deploy.
- **Pausing.** `pause` runs `sleep` in the background and waits for it, so INT/TERM act within the poll.
- **fd 9.** `curl`, `sleep` and `logger` all get fd 9 closed.

## 4. Installers and uninstaller

### 4.1 `engine/install-engine-service.sh`

- **New source line, after `PROJECT_DIR` is set:** `source "${SCRIPT_DIR}/engine-upstream.sh"`. `SCRIPT_DIR` is the script's own `engine/` directory, so this does not depend on `--project-dir`.
- **New globals:**
  - `HOST_SET=0` and `PORT_SET=0`, set in the `--host`/`--port` cases.
  - `PROD_TEMPLATE_PATH="/etc/systemd/system/${DEFAULT_PROD_ENGINE_SERVICE}@.service"`.
  - `LEGACY_PROD_UNIT_PATH="/etc/systemd/system/${DEFAULT_PROD_ENGINE_SERVICE}.service"`.
  - `PROD_READY_TIMEOUT=300`.
- **Entry point.** It becomes `if [[ "${MODE}" == "prod" ]]; then install_engine_prod; else install_engine_service; fi`, so the dev path stays byte-identical. `--print-default-service-name` is unchanged and still prints `peertube-engine`.
- **Usage text.** Line 35 becomes `prod: template peertube-engine@.service, instances @7070/@7071 behind nginx 127.0.0.1:7079 (snippet /etc/nginx/peertube-engine-upstream.conf)`. The `--host`/`--port` lines gain `(dev only; refused with --mode prod)`. `--service-name` gains `(prod: fixed peertube-engine)`.

```bash
# Poll a health URL every 2 s until 200 or the timeout.
wait_http_200() {
  local url="$1" timeout="$2" started="${SECONDS}"
  while (( SECONDS - started < timeout )); do
    [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${url}" 2>/dev/null || true)" == "200" ]] && return 0
    sleep 2
  done
  return 1
}

install_engine_prod() {
  if [[ -n "${ENGINE_SERVICE_NAME}" && "${ENGINE_SERVICE_NAME}" != "${ENGINE_INSTANCE_BASE}" ]]; then
    fail "--service-name is fixed to ${ENGINE_INSTANCE_BASE} in --mode prod (instances ${ENGINE_INSTANCE_BASE}@7070 and @7071)"
  fi
  ENGINE_SERVICE_NAME="${ENGINE_INSTANCE_BASE}"
  (( HOST_SET == 0 && PORT_SET == 0 )) || fail "--host/--port do not apply to --mode prod: instances bind 127.0.0.1:7070/7071 and the Client uses nginx 127.0.0.1:${ENGINE_LISTENER_PORT}"
  [[ -n "${SERVICE_USER}" ]] || fail "--service-user cannot be empty"
  [[ -f "${SERVER_PY}" ]] || fail "Missing server entrypoint: ${SERVER_PY}"
  [[ -x "${VENV_PY}" ]] || fail "Missing python interpreter in venv: ${VENV_PY}"
  if (( DRY_RUN == 0 )); then
    [[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
    require_cmd systemctl
    require_cmd journalctl
    require_cmd nginx
    require_cmd flock
    require_cmd curl
  fi
  id "${SERVICE_USER}" >/dev/null 2>&1 || fail "User does not exist: ${SERVICE_USER}"

  # The deploy lock before reading the snippet, so a running deploy cannot flip it underneath.
  if (( DRY_RUN == 0 )); then
    local lock_path
    lock_path="$(engine_deploy_lock_path "${PROJECT_DIR}")"
    exec 9>>"${lock_path}" || fail "Cannot open deploy lock: ${lock_path}"
    flock -n 9 || fail "A blue/green deploy holds ${lock_path}; re-run after it finishes."
  fi

  # Validate before touching anything: an invalid snippet fails here, before any write or stop.
  local active_port snippet_new=0
  if [[ -e "${UPSTREAM_SNIPPET}" ]]; then
    active_port="$(read_active_port "${UPSTREAM_SNIPPET}")" || fail "Invalid upstream snippet ${UPSTREAM_SNIPPET}: it must name exactly one of 'server 127.0.0.1:7070;' / 'server 127.0.0.1:7071;'. Nothing was changed."
  else
    active_port="${ENGINE_INSTANCE_PORTS[0]}"
    snippet_new=1
  fi
  local other_port unit other_unit legacy=0 listener_existed=0
  other_port="$(other_instance_port "${active_port}")"
  unit="${ENGINE_INSTANCE_BASE}@${active_port}"
  other_unit="${ENGINE_INSTANCE_BASE}@${other_port}"
  [[ -f "${LEGACY_PROD_UNIT_PATH}" ]] && legacy=1
  [[ -f "${ENGINE_LISTENER_CONF}" ]] && listener_existed=1

  local template_content
  template_content="[Unit]
Description=PeerTube Engine (${MODE})
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=ENGINE_INGEST_MODE=bridge
EnvironmentFile=-${PROJECT_DIR}/.env.bridge
ExecStart=${VENV_PY} ${SERVER_PY} --host 127.0.0.1 --port %i
Restart=on-failure
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
"
  if [[ -d "${LEGACY_PROD_UNIT_PATH}.d" ]]; then
    echo "WARNING: drop-ins in ${LEGACY_PROD_UNIT_PATH}.d/ do not apply to ${PROD_TEMPLATE_PATH}; move them to ${PROD_TEMPLATE_PATH}.d/ and run scripts/deploy-bluegreen.sh --blue-green." >&2
  fi

  if (( DRY_RUN == 1 )); then
    echo "[dry-run] install-engine-service"
    echo "  mode=${MODE}"
    echo "  service=${ENGINE_INSTANCE_BASE}@ (template; instances @7070 @7071)"
    echo "  active_port=${active_port} snippet=$([[ ${snippet_new} == 1 ]] && echo new || echo existing)"
    echo "  user=${SERVICE_USER}"
    echo "  unit=${PROD_TEMPLATE_PATH}"
    echo "  snippet_path=${UPSTREAM_SNIPPET}"
    echo "  listener_path=${ENGINE_LISTENER_CONF}"
    echo "  migrate_legacy_unit=$([[ ${legacy} == 1 ]] && echo "yes (stop, disable, rm ${LEGACY_PROD_UNIT_PATH})" || echo no)"
    echo "  plan: write snippet (if new), listener, template; daemon-reload; start ${unit} if not active ($([[ ${FORCE_REINSTALL} == 1 ]] && echo 'restart: --force' || echo 'healthy one kept')); stop+disable ${other_unit}; enable ${unit}; nginx -t; reload nginx; check 127.0.0.1:${ENGINE_LISTENER_PORT}/api/health"
    echo "----- unit preview -----"
    printf '%s\n' "${template_content}"
    echo "----- snippet preview -----"
    snippet_text "${active_port}"
    echo "----- listener preview -----"
    engine_listener_text
    echo "----- end preview -----"
    return
  fi

  # Snippet before listener: the listener includes it, and an unrelated nginx reload in between must not fail.
  if (( snippet_new == 1 )); then
    log_lifecycle "[engine-install] writing snippet=${UPSTREAM_SNIPPET} port=${active_port}"
    snippet_text "${active_port}" | replace_file "${UPSTREAM_SNIPPET}" || fail "Cannot write ${UPSTREAM_SNIPPET}"
  fi
  engine_listener_text | replace_file "${ENGINE_LISTENER_CONF}" || fail "Cannot write ${ENGINE_LISTENER_CONF}"
  echo "[engine-install] Writing unit: ${PROD_TEMPLATE_PATH}"
  printf '%s\n' "${template_content}" > "${PROD_TEMPLATE_PATH}"
  systemctl daemon-reload

  if (( legacy == 1 )); then
    log_lifecycle "[engine-install] migrating service=${DEFAULT_PROD_ENGINE_SERVICE}.service -> ${unit} (one-time outage)"
    systemctl stop "${DEFAULT_PROD_ENGINE_SERVICE}.service" >/dev/null 2>&1 || true
    systemctl disable "${DEFAULT_PROD_ENGINE_SERVICE}.service" >/dev/null 2>&1 || true
    rm -f "${LEGACY_PROD_UNIT_PATH}"
    systemctl daemon-reload
    systemctl reset-failed "${DEFAULT_PROD_ENGINE_SERVICE}.service" >/dev/null 2>&1 || true
  fi

  local state started=0
  state="$(systemctl is-active "${unit}" 2>/dev/null || true)"
  if (( FORCE_REINSTALL == 1 )); then
    log_lifecycle "[engine-install] restarting service=${unit} (--force)"
    systemctl restart "${unit}"
    started=1
  elif [[ "${state}" != "active" ]]; then
    log_lifecycle "[engine-install] starting service=${unit}"
    systemctl start "${unit}"
    started=1
  else
    log_lifecycle "[engine-install] keeping active service=${unit}"
  fi
  if [[ "$(systemctl is-active "${other_unit}" 2>/dev/null || true)" != "inactive" ]]; then
    log_lifecycle "[engine-install] stopping non-active service=${other_unit}"
    systemctl stop "${other_unit}" || true
  fi
  systemctl disable "${other_unit}" >/dev/null 2>&1 || true
  systemctl enable "${unit}" >/dev/null

  if ! wait_http_200 "http://127.0.0.1:${active_port}/api/health" "$(( started == 1 ? PROD_READY_TIMEOUT : 10 ))"; then
    echo "Engine instance ${unit} did not answer /api/health 200. Recent logs:" >&2
    journalctl -u "${unit}" -n 80 --no-pager >&2 || true
    exit 1
  fi
  if ! nginx -t; then
    (( listener_existed == 0 )) && rm -f "${ENGINE_LISTENER_CONF}"
    fail "nginx -t failed; nginx was not reloaded$([[ ${listener_existed} == 0 ]] && echo " and ${ENGINE_LISTENER_CONF} was removed")."
  fi
  systemctl reload nginx
  wait_http_200 "http://127.0.0.1:${ENGINE_LISTENER_PORT}/api/health" 10 || fail "127.0.0.1:${ENGINE_LISTENER_PORT}/api/health did not answer 200 after the reload: check that nginx.conf includes /etc/nginx/conf.d/*.conf in the http block."

  echo "Engine service installed: ${unit} (template ${PROD_TEMPLATE_PATH}, upstream ${UPSTREAM_SNIPPET})"
  log_lifecycle "[engine-install] service active service=${unit} mode=${MODE} listener=127.0.0.1:${ENGINE_LISTENER_PORT}"
  echo "Status: systemctl status '${ENGINE_INSTANCE_BASE}@*'"
  echo "Logs  : journalctl -u '${ENGINE_INSTANCE_BASE}@*' -f"
  echo "Deploy: sudo bash scripts/deploy-bluegreen.sh --blue-green"
}
```

Idempotency: a re-run without `--force` on a healthy host rewrites identical files, keeps the active instance, never flips the port, and only reloads nginx (a graceful reload). A re-run with `--force`, the central default, restarts the active instance in place, which is today's behaviour and is documented.

### 4.2 `engine/uninstall-engine-service.sh`

- **Sourcing.** It sources `engine-upstream.sh`.
- **Name check.** After the name defaults (line 112) it adds: `if [[ "${MODE}" == "prod" ]]; then [[ "${ENGINE_SERVICE_NAME}" == "${ENGINE_INSTANCE_BASE}" ]] || fail "--service-name is fixed to ${ENGINE_INSTANCE_BASE} in --mode prod"; uninstall_engine_prod; exit 0; fi`.
- **Dev.** Lines 114-141 are unchanged.
- **`uninstall_engine_prod`:**
  - Dry-run header: `[dry-run] uninstall-engine-service`, then `mode`, `service=peertube-engine@ (template)`, `unit=/etc/systemd/system/peertube-engine@.service` (the smoke check greps `peertube-engine`), `legacy_unit`, `snippet` and `listener`.
  - Root check and `require_cmd systemctl`, both skipped in dry-run.
  - For each port in `7070 7071`: `run_cmd systemctl stop peertube-engine@<p> 2>/dev/null || true` and `run_cmd systemctl disable peertube-engine@<p> 2>/dev/null || true`. stdout is **not** redirected, so the dry-run echo shows; the line 130 quirk is not copied.
  - The same stop and disable for a legacy `peertube-engine.service`.
  - `run_cmd rm -f` on the template, the legacy unit, then **the listener first**, then the snippet and `${UPSTREAM_SNIPPET}.bak`.
  - Outside dry-run: `systemctl daemon-reload`, then `systemctl reset-failed 'peertube-engine@*' peertube-engine.service 2>/dev/null || true`.
  - If `command -v nginx`: `run_cmd nginx -t || fail "nginx -t failed after removing the Engine listener; nginx was not reloaded"`, then `run_cmd systemctl reload nginx`. Without nginx, it logs `nginx not found; skipped reload` and succeeds.
  - It leaves the lock file and any `.service.d` drop-ins, and logs both paths as left behind.

### 4.3 `engine/install-updater-service.sh`

- It sources `"${SCRIPT_DIR}/engine-upstream.sh"`. `SCRIPT_DIR` already exists in that file's header; if it does not, add it.
- After `validate_service_name "${ENGINE_SERVICE_NAME}"` (line 251):

```bash
if [[ "${MODE}" == "prod" ]]; then
  [[ "${ENGINE_SERVICE_NAME}" == "${ENGINE_INSTANCE_BASE}" ]] || fail "--engine-service-name is fixed to ${ENGINE_INSTANCE_BASE} in --mode prod (the worker stops/starts ${ENGINE_INSTANCE_BASE}@7070|7071 from ${UPSTREAM_SNIPPET})"
fi
```

- Line 324, with the sudoers line built once and used by both the preview (364) and the written rule (376):

```bash
if [[ "${MODE}" == "prod" ]]; then
  updater_exec="${venv_py} ${updater_py} --mode ${MODE} --service-name ${ENGINE_SERVICE_NAME} --systemctl-bin ${systemctl_bin} --systemctl-use-sudo --engine-upstream-snippet ${UPSTREAM_SNIPPET} ${UPDATER_FLAGS}"
  # Literal entries, no .service suffix: sudo matches argv exactly, and updater-worker.py calls `systemctl stop|start peertube-engine@<port>`.
  updater_sudoers_line="${SERVICE_USER} ALL=(root) NOPASSWD: ${systemctl_bin} stop ${ENGINE_INSTANCE_BASE}@7070, ${systemctl_bin} stop ${ENGINE_INSTANCE_BASE}@7071, ${systemctl_bin} start ${ENGINE_INSTANCE_BASE}@7070, ${systemctl_bin} start ${ENGINE_INSTANCE_BASE}@7071"
else
  updater_exec="${venv_py} ${updater_py} --mode ${MODE} --service-name ${ENGINE_SERVICE_NAME} --systemctl-bin ${systemctl_bin} --systemctl-use-sudo ${UPDATER_FLAGS}"
  updater_sudoers_line="${SERVICE_USER} ALL=(root) NOPASSWD: ${systemctl_bin} stop ${ENGINE_SERVICE_NAME}, ${systemctl_bin} start ${ENGINE_SERVICE_NAME}"
fi
```

- Line 364 becomes `echo "${updater_sudoers_line}"`, and line 376 becomes `printf '%s\n' "${updater_sudoers_line}" > "${tmp_sudoers}"`. The dev output is byte-identical.
- Usage line 40 is updated to match.
- `--deploy-lock-file` is not passed. The worker derives the same repo-relative default, because the unit's `updater_py` path lies inside `PROJECT_DIR`.
- **Flag precedence.** An operator's `--skip-systemctl` in `UPDATER_FLAGS` wins: no stop, no start, no deploy lock. This is documented in UPDATER_WORKER.md.

### 4.4 `scripts/install-service.sh`

In `install_contour`:

```bash
  if [[ "${contour}" == "prod" ]]; then
    (( ENGINE_PORT_SET == 0 && ENGINE_HOST_SET == 0 )) || fail "--engine-port/--engine-host do not apply to prod: the Engine runs as peertube-engine@7070|7071 behind nginx 127.0.0.1:7079"
  fi
```

- **Ingest URL.** `engine_ingest_base` defaults to `http://127.0.0.1:7079` for prod, through a new constant `PROD_ENGINE_LISTENER_URL`. An explicit `--client-engine-url` is still honoured; the deploy's preflight then refuses, and the docs say so.
- **Collision check.** In prod it checks the Client port against `7070 7071 7079`.
- **Echo.** The prod echo becomes `engine=peertube-engine@{7070|7071} via 127.0.0.1:7079`.
- **`engine_cmd`.** It appends `--host`/`--port` only when `contour == dev`.
- **Order.** The Engine is installed, then the Client, then the updater (lines 344-353), unchanged.
- **Same phase.** This must ship in the same phase as §4.1, because prod now refuses `--host`/`--port`.

### 4.5 `client/install-client-service.sh`

- Line 20 becomes `DEFAULT_PROD_ENGINE_LISTENER_PORT=7079`, with the comment `# nginx loopback listener in front of the active Engine instance (peertube-engine@7070|7071)`.
- Line 164 uses it.
- Usage: line 36 reads `(default: 7079 prod nginx listener, 7171 dev)`, and line 46 reads `--engine-url http://127.0.0.1:7079`.
- Dev is unchanged.

### 4.6 Small files

| File | Change |
|---|---|
| `engine/watch-engine-logs.sh` | Line 72 becomes `UNIT="peertube-engine@*"`. Line 12 becomes `-prod, --prod  Use peertube-engine@* (both blue/green instances)`. `journalctl -u` accepts the glob |
| `.gitignore` | Under `# Local data files`: `engine/server/db/engine-deploy.lock` |
| `tests/check-frontend-client-gateway.sh:28` | `(7070\|7071\|7072\|7079\|7171)` in both alternations |

## 5. `engine/server/db/jobs/updater-worker.py`

- **Imports.** Add `import fcntl` and `import re`, in alphabetical position.
- **Module constants**, after the imports block:

```python
ENGINE_INSTANCE_BASE = "peertube-engine"
ENGINE_INSTANCE_PORTS = (7070, 7071)
DEPLOY_LOCK_WAIT_SECONDS = 30 * 60
DEPLOY_LOCK_POLL_SECONDS = 5.0
# Same rule as read_active_port in engine/engine-upstream.sh: [ \t] there is [[:blank:]], and lines split on "\n" only, as grep does.
UPSTREAM_ANY_SERVER_RE = re.compile(r"^[ \t]*server([ \t]|$)")
UPSTREAM_SERVER_LINE_RE = re.compile(r"^[ \t]*server[ \t]+127\.0\.0\.1:(7070|7071);[ \t]*$")
```

- **New arguments**, in `parse_args`, after `--skip-systemctl`:

```python
    parser.add_argument(
        "--engine-upstream-snippet",
        default=None,
        help="Prod blue/green: nginx upstream snippet naming the active Engine port; stop/start peertube-engine@<port> instead of --service-name.",
    )
    parser.add_argument(
        "--deploy-lock-file",
        default=str((repo_root / "engine/server/db/engine-deploy.lock").resolve()),
        help="Blue/green deploy lock (flock), held from Engine stop to start with --engine-upstream-snippet. Not --lock-file.",
    )
```

- **Helpers**, after `systemctl_cmd`:

```python
def parse_upstream_snippet(path: Path) -> int:
    """Return the active Engine port: exactly one line starting with `server`, and it is `server 127.0.0.1:7070;` or `…7071;`; ValueError otherwise."""
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot read upstream snippet {path}: {exc}") from exc
    servers = [line for line in lines if UPSTREAM_ANY_SERVER_RE.match(line)]
    if len(servers) != 1:
        raise ValueError(f"upstream snippet {path} has {len(servers)} server lines, expected 1")
    match = UPSTREAM_SERVER_LINE_RE.match(servers[0])
    if match is None:
        raise ValueError(f"upstream snippet {path} names neither 127.0.0.1:7070 nor 127.0.0.1:7071: {servers[0].strip()!r}")
    return int(match.group(1))


def engine_instance_unit(port: int) -> str:
    """Return the instance unit exactly as the prod sudoers rule spells it: no `.service` suffix."""
    if port not in ENGINE_INSTANCE_PORTS:
        raise ValueError(f"not an Engine instance port: {port}")
    return f"{ENGINE_INSTANCE_BASE}@{port}"


def acquire_deploy_lock(lock_path: Path, *, wait_seconds: float, poll_seconds: float = DEPLOY_LOCK_POLL_SECONDS) -> int:
    """Take the blue/green deploy flock, polling non-blocking up to `wait_seconds`; return the fd. Opened O_RDONLY because root may have created the file 0644."""
    fd = os.open(lock_path.as_posix(), os.O_RDONLY | os.O_CREAT, 0o644)
    deadline = time.monotonic() + wait_seconds
    waiting_logged = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise RuntimeError(f"deploy lock {lock_path} still held after {int(wait_seconds)}s; Engine not stopped")
            if not waiting_logged:
                logging.info("waiting for deploy lock %s (up to %ds)", lock_path, int(wait_seconds))
                waiting_logged = True
            time.sleep(poll_seconds)


def release_deploy_lock(fd: int | None) -> None:
    """Release and close the deploy lock fd, if one is held."""
    if fd is None:
        return
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
```

- **`main()`.** The block at lines 1261-1345 is restructured; only the changed lines are shown:

```python
            engine_unit = args.service_name
            deploy_lock_fd = None
            try:
                if not args.skip_systemctl:
                    if args.engine_upstream_snippet:
                        # Blue/green prod: hold the deploy lock from stop to start, and stop/start the instance the snippet names now.
                        deploy_lock_fd = acquire_deploy_lock(Path(args.deploy_lock_file), wait_seconds=DEPLOY_LOCK_WAIT_SECONDS)
                        engine_unit = engine_instance_unit(parse_upstream_snippet(Path(args.engine_upstream_snippet)))
                        logging.info("engine active instance=%s (from %s)", engine_unit, args.engine_upstream_snippet)
                    run_cmd(
                        systemctl_cmd(
                            systemctl_bin=args.systemctl_bin,
                            service_name=engine_unit,
                            action="stop",
                            use_sudo=args.systemctl_use_sudo,
                        )
                    )
                    service_stopped = True
                # … merge / prune / popularity / ANN unchanged …
            finally:
                try:
                    if service_stopped and not args.skip_systemctl:
                        run_cmd(
                            systemctl_cmd(
                                systemctl_bin=args.systemctl_bin,
                                service_name=engine_unit,
                                action="start",
                                use_sudo=args.systemctl_use_sudo,
                            )
                        )
                        service_stopped = False
                finally:
                    release_deploy_lock(deploy_lock_fd)
```

Invariants:
- **Lock and parse come first.** They both run before `service_stopped = True`. A lock timeout or a parse error therefore stops nothing and starts nothing.
- **Lock release.** It is released after the start, on success and on failure alike.
- **Same unit.** Stop and start use the one local `engine_unit`.
- **The AST test still passes:**
  - The outer `Try`'s `finalbody`, walked, contains the `action="start"` call.
  - The inner `Try`'s `finalbody` holds only `release_deploy_lock`.
  - So exactly one match. `run_similarity_stage` stays after the outer `end_lineno`.
- **Without `--engine-upstream-snippet`.** `engine_unit == args.service_name` and `deploy_lock_fd is None`, so the commands are identical to today's. Dev and `test-orchestrator-smoke.py` are unaffected.

## 6. Logging contract (deploy)

Every line has the form `deploy_id=<UTC>-<pid> event=<name> k=v …`. It is printed to stdout and sent to journald with tag `peertube-engine-deploy`.

| Event | Fields |
|---|---|
| `lock_acquired` | `lock` |
| `refused` | `reason` (`lock_held`, `updater_running`, `client_not_on_listener`, `snippet_invalid`) plus detail |
| `start` | `old_port new_port timeout_s warmup_s drain_s` |
| `stop_leftover`, `start_target` | `unit state` |
| `ready` / `readiness_timeout` / `readiness_failed` | `port status`/`last_status unit_state waited_s` |
| `warmup_check` | `port status warmup_s` |
| `snippet_written`, `switched` | `port`; `old_port new_port switch_time` |
| `post_switch_check` / `post_switch_check_failed` | `status upstream attempts waited_s` / `last_status upstream want waited_s` |
| `drain_begin`, `old_stopped`, `enabled`, `disabled` | `unit main_pid drain_s` |
| `cache_cleanup` | `pid removed` |
| `rollback`, `rollback_done` | `phase step reason old_port new_port`, `serving_port` |
| `post_switch_failure` | `step reason rollback=none` |
| `rollback_failed` | `msg="ROLLBACK FAILED" at phase snippet old_state new_state` |
| `signal` | `name phase` |
| `done` | `result=ok\|degraded active_port exit_code` |

## 7. Tests

### 7.1 `tests/active/upstream_snippet_cases.json`

Each case is `{id, text, port}`, with `port: null` meaning rejected.

| id | text | port |
|---|---|---|
| `active-7070` | `"upstream peertube_engine {\n    server 127.0.0.1:7070;\n}\n"` | 7070 |
| `active-7071` | the same with 7071 | 7071 |
| `tabs-no-final-newline` | `"upstream peertube_engine {\n\tserver\t127.0.0.1:7071;\t\n}"` | 7071 |
| `foreign-port` | `…server 127.0.0.1:7072;…` | null |
| `foreign-host` | `…server 0.0.0.0:7070;…` | null |
| `two-servers` | 7070 and 7071 lines | null |
| `server-params` | `server 127.0.0.1:7070 max_fails=0;` | null |
| `commented-out` | `#    server 127.0.0.1:7070;` only | null |
| `crlf` | the 7070 text with `\r\n` | null |
| `empty` | `""` | null |

A missing file is a separate case in each test.

### 7.2 `tests/active/test_deploy_bluegreen.py`

**Fixture `deploy_tree(tmp_path)`.**
- Copies `scripts/deploy-bluegreen.sh` to `tmp/scripts/` and `engine/engine-upstream.sh` to `tmp/engine/`.
- Creates `tmp/engine/server/db/` and `tmp/nginx/peertube-engine-upstream.conf` (7070 by default).
- Writes the stubs into `tmp/bin/`.
- Builds an env with:
  - `PATH=tmp/bin:/usr/bin:/bin`;
  - `STUB_DIR=tmp/stub`;
  - `PEERTUBE_ENGINE_UPSTREAM_SNIPPET=tmp/nginx/peertube-engine-upstream.conf`;
  - `PEERTUBE_CLIENT_UNIT_PATH=tmp/absent.service`.
- Every run passes `--drain 0 --warmup 0 --timeout 3`.
- The test never touches real ports 7070 or 7079: `curl` is a stub.
- At module level: `assert shutil.which("flock")`, with the message `util-linux flock(1) required`. It is a fail, not a skip.

Stub contracts. "Sequence files" are read one line per call; the last line is sticky.

| Stub | Behaviour |
|---|---|
| `systemctl` | Appends `$*` to `stub/calls.log`. `is-active U` prints `stub/state/U` (default `inactive`). `start U` writes `active`, or `failed` if `stub/fail-start/U` exists. `stop U` writes `inactive`. `restart` is `stop`+`start`. `show -p MainPID --value U` prints `stub/pid/U` or `0`. `reload nginx` takes its exit code from the sequence `stub/reload-nginx` (default 0) and, on 0, copies the snippet to `stub/nginx-loaded`. `enable`/`disable` exit 0 |
| `nginx` | `-t`: exit code from the sequence `stub/nginx-t` (default 0). Appends to `calls.log` |
| `curl` | Finds the URL port. **7070/7071**: prints `000` if `stub/state/peertube-engine@<p>` is not `active` (unless `stub/foreign/<p>` exists); otherwise the status from the sequence `stub/curl.<p>` (default 200). **7079**: the status from the sequence `stub/curl.7079` if present; otherwise the port read from `stub/nginx-loaded` decides, 502 if that unit is inactive, else its status. With `-D` in the args it prints `HTTP/1.1 <s>\r\nX-Engine-Upstream: 127.0.0.1:<p>\r\n\r\n` before the code. Appends to `stub/curl.log` |
| `logger` | Appends the last argument to `stub/journal.log` |
| `id` | `-u` prints `stub/uid` (default `0`) |

**Cases.** "No change" means: no `start`/`stop`/`reload`/`enable`/`disable` in `calls.log`, and the snippet bytes unchanged.

| Test | Setup | Asserts |
|---|---|---|
| `test_flip_7070_to_7071` | `@7070` active, pid 4242 | exit 0. Snippet is `snippet_text 7071` with mode `0o644`. Call order is `start @7071` < `reload nginx` < `stop @7070` < `enable @7071` < `disable @7070` (old stopped only after the switch). `.bak` holds 7070 |
| `test_flip_7071_to_7070` | snippet 7071, `@7071` active | mirror image |
| `test_readiness_timeout_rolls_back` | `curl.7071` = 503 | exit 1. `stop @7071`. No reload. Snippet unchanged. No call on `@7070`. Journal has `event=rollback phase=pre-switch step=readiness reason=readiness_timeout` |
| `test_readiness_unit_failed` | `fail-start/@7071` | exit 1, `reason=unit_failed`, finishes in under 2 s |
| `test_rate_limited_counts_not_ready` | `curl.7071` = `429\n200` | exit 0, with two health probes on 7071 |
| `test_nginx_test_failure_restores` | `nginx-t` = `1\n0` | exit 1. Snippet == original. `reload nginx` once (the restore). `stop @7071`. `@7070` untouched. `reason=nginx_test_failed step=nginx_test` |
| `test_reload_failure_restores` | `reload-nginx` = `1\n0` | the same, with `step=nginx_reload` |
| `test_post_switch_failure_restores` | `curl.7079` = 502 | exit 1. Snippet restored. `stop @7071`. `@7070` never stopped. `reason=post_switch_check` |
| `test_post_switch_wrong_upstream` | reload stub never updates `nginx-loaded` (sequence makes `nginx-loaded` stay 7070) | exit 1, rolled back |
| `test_rollback_failure_is_loud` | `nginx-t` = `1\n1` | exit 1. Journal and stderr contain `ROLLBACK FAILED` and `at=restore_nginx_test` |
| `test_lock_contention` | the test holds `fcntl.flock(LOCK_EX)` on `engine-deploy.lock` | exit 1. `calls.log` empty. `reason=lock_held` |
| `test_requires_blue_green` | no flag | exit 2. Usage on stderr. No lock file. `calls.log` absent |
| `test_refuses_while_updater_running[active,activating]` | `state/peertube-updater.service` | exit 1, no change, `reason=updater_running` |
| `test_leftover_target_restarted` | `@7071` active beforehand | `stop @7071` < `start @7071`. Exit 0 |
| `test_foreign_listener_refused` | `foreign/7071` | exit 1, no `start @7071`, `reason=port_in_use_by_foreign_process` |
| `test_invalid_snippet_refused[case…]` | every `null` case plus a missing file | exit 1, no change, `reason=snippet_invalid` |
| `test_bash_parser_matches_cases[case…]` | `bash -c 'source engine-upstream.sh; read_active_port "$1"'` | port or non-zero, per the JSON |
| `test_client_preflight_refuses` | a Client unit file with `--engine-url http://127.0.0.1:7070` | exit 1, no change |
| `test_random_cache_temp_removed` | `random-cache.tmp.4242.db`, `-journal`, decoy `random-cache.tmp.999.db` | the first two are gone; the decoy remains |
| `test_log_fields` | the normal flip | every journal line starts `deploy_id=`, with one id throughout. Lines present: `event=start old_port=7070 new_port=7071`, `event=ready … status=200 waited_s=`, `event=switched … switch_time=`, `event=post_switch_check status=200`, `event=old_stopped`, `event=done result=ok` |
| `test_non_root_refused` | `uid` 1000 | exit 1, no change |
| `test_dry_run_changes_nothing` | `uid` 1000, `--dry-run` | exit 0. Prints `active_port=7070 target_port=7071` and actions 1–8. `calls.log` has only `is-active`. No lock file. Journal empty |

### 7.3 `tests/active/test_updater_worker.py` additions

- `test_parse_upstream_snippet_cases[case…]`: from the JSON, plus a missing file → `ValueError`.
- `test_engine_instance_unit`: `7070` → `"peertube-engine@7070"`, with no `.service`; `7072` → `ValueError`.
- `test_deploy_lock_opens_read_only`: the lock file is `chmod 0o444`. `acquire_deploy_lock(wait_seconds=0)` returns an fd, and `release_deploy_lock` closes it.
- `test_deploy_lock_times_out_when_held`: a second `os.open`+`flock` in the test holds the lock; `wait_seconds=0` → `RuntimeError`.
- `test_main_stops_and_starts_same_unit`, marked `# rat-tail: a source scan, because reaching the stop/start through main means running the whole crawl/merge/ANN pipeline; a pipeline harness with systemctl shimmed would replace it.` It checks that both `systemctl_cmd` calls in `main` pass `service_name=` as `ast.Name` `engine_unit`. It also checks that the `acquire_deploy_lock` call's line comes before the line of `service_stopped = True`.
- The existing `test_main_runs_similarity_stage_after_service_start` must stay green unchanged.

### 7.4 `tests/active/test_installers_dry_run.py`

**Fake project tree.** It contains:
- an executable `venv/bin/python3`;
- `engine/server/api/server.py`, `engine/server/db/jobs/updater-worker.py`, `client/backend/server.py`;
- the real `engine/install-updater-service.sh` and `engine/engine-upstream.sh` copied in, since `resolve_updater_installer` resolves from `PROJECT_DIR`.

**Environment.** It runs with the stub `systemctl` on PATH, `--service-user $(id -un)`, and `PEERTUBE_ENGINE_UPSTREAM_SNIPPET=tmp/snippet`.

**Assertions:**
- **Prod Engine:**
  - `ExecStart=… --host 127.0.0.1 --port %i`;
  - `unit=/etc/systemd/system/peertube-engine@.service`;
  - `active_port=7070 snippet=new` with no snippet, and `active_port=7071 snippet=existing` with a 7071 snippet;
  - an invalid snippet → exit 1;
  - the listener preview contains `listen 127.0.0.1:7079;` and no other `listen`;
  - the snippet file is not created.
- **Prod Engine `--port 7070`:** exit 1.
- **Dev Engine:** output equals the pre-change output (`--host 127.0.0.1 --port 7171`, `peertube-engine-dev.service`).
- **Prod updater:**
  - the sudoers preview line equals the four-entry string exactly;
  - `ExecStart` contains `--engine-upstream-snippet <snippet>`.
- **Dev updater:** the single-name rule.
- **Prod Client:** `--engine-url http://127.0.0.1:7079`. **Dev Client:** `http://127.0.0.1:7171`.
- **Prod uninstaller `--dry-run`:** lists `peertube-engine@7070`, `@7071`, the template, the listener before the snippet, and `nginx -t`.

## 8. Documentation (settled list, applied as given)

- `DEPLOYMENT.md`: every item on the settled list.
  - **Triage rows** carry the exact log tokens from §6 (`reason=lock_held`, `readiness_timeout`, `nginx_test_failed`, `ROLLBACK FAILED`) and `cat /etc/nginx/peertube-engine-upstream.conf` for the active port.
  - **Deploy options section:** `--timeout 300` (same as `run-services.sh`), `--warmup 0`, `--drain 30` (the Client's 20 s ceiling plus margin). It also covers the 2 s poll set against the 60/60 s limit, and the Client preflight.
- `engine/server/db/jobs/docs/UPDATER_WORKER.md`, `engine/server/README.md`, `DATA_BUILD.md`, `README.md`, `client/README.md`: per the settled list.
- `engine/watch-engine-logs.sh` help text, ADR 0002 amendment, new ADR 0009, `CONTEXT.md` terms "Active instance" and "Upstream snippet": per the settled list. ADR 0009 also records the decisions in §9.
- Harvest-time items (the issue moved to archive, the roadmap entry) are not part of this draft.

## 9. Check against the plan and requirements (ladder step 2)

There were two passes.

**Pass 1 found four gaps:**
1. The plan's installer order writes files before it validates the snippet. That breaks "an invalid snippet fails without touching anything", so validation was moved first.
2. A third bash copy of the parser, in the installer.
3. A CRLF divergence between `grep` and Python `splitlines()`.
4. The foreign-listener hole on 7071.

**Pass 2** found nothing unmet.

| Requirement | Met by |
|---|---|
| Template matches today's unit except `--host 127.0.0.1 --port %i` | §4.1 `template_content` |
| Migration; idempotent re-run with no flip; `--force` restarts | §4.1 |
| Exactly one instance enabled (the snippet's) | installer: enable active, disable other; deploy step 9 |
| Uninstall removes both instances, the template, legacy, listener, snippet and backup; `nginx -t` passes; works without nginx | §4.2 |
| `--help`/`--dry-run` on every entrypoint | §3, §4, tested in §7.4 |
| Snippet is the single source of truth; listener `127.0.0.1:7079` only; headers passed unchanged; timeouts at nginx defaults; scripted, `nginx -t` before reload | §2, §4.1 |
| Client prod default 7079; dev 7171 | §4.5, §4.4 |
| Deploy: `--blue-green` required (exit 2), `--help`, `--dry-run`, three timing options, root except in dry-run | §3 |
| Flow steps 1–11 | §3, with comments per step |
| Rollback by phase; old instance never stopped before step 8; post-switch failures are non-fatal but give a non-zero exit; `ROLLBACK FAILED` is loud; lock released on every exit | §3 `rollback`, `on_signal`, fd 9 |
| Idempotency and convergence; one upstream server at every moment | the snippet is the only source; a leftover is restarted |
| Updater uses the active instance, starts the same one, four exact sudoers entries, no overlap either way, dev unchanged | §4.3, §5, deploy step 2 |
| Logging fields and a single tag | §6 |
| Tests run without root, systemd or nginx; every listed case covered | §7 |

**Decisions beyond the letter of the plan.** All are refusals, tighter checks or a file-layout simplification; none changes what the build is for.
- **D1. Shared sourced `engine/engine-upstream.sh`.** It is one new file. Without it the installer would hold a third parser copy. It keeps the plan's "two parsers, one bash and one Python". Ceiling: a format change touches the bash and Python implementations, held together by the JSON fixture.
- **D2. Installer order.** Deploy lock, then snippet validation, then snippet, listener, template, then legacy migration.
- **D3. Installer handles a stray second instance.** It stops a running non-active instance, and removes a listener it newly wrote if `nginx -t` fails.
- **D4. Deploy rejects a foreign listener on the target port.** It refuses when the target port answers while the unit is inactive, and readiness also requires the unit to be `active`. This closes the impact's foreign-listener hole, for example `server.py --dev` on 7071.
- **D5. Second test-only env var, `PEERTUBE_CLIENT_UNIT_PATH`.** The developer machine runs a real prod Client unit, which would otherwise make the preflight refuse inside tests.
- **D6. Listener details.** It gets its own `access_log` and `server_tokens off`. The public `access.log` then stays a clean signal for the "no 5xx spike" check, and the internal hop does not advertise nginx's version.
- **D7. Prod names are fixed.** A non-default `--service-name`/`--engine-service-name` is refused in prod, as are `--host`/`--port` and the central `--engine-port`/`--engine-host`. Sudoers entries are literal.
- **D8. Interruptible sleeps.** `pause` (a background sleep plus `wait`) lets INT/TERM roll back immediately.

**Accepted risks the operator should know.** Each is named, and none needs code:
- Peak RSS roughly doubles during the overlap.
- The new instance's startup DDL on `whitelist.db` can hit "database is locked". That costs restart time, or at worst a readiness rollback.
- On a `switching` rollback, the stop of the new instance can cut requests that reached it in the ≤10 s before the restore.
- A reboot inside the drain boots the old enabled instance. The next deploy or installer run converges it.
- The Client now relays nginx's HTML 502 while the Engine is down (a documented behaviour change).
- `tests/run-installers-smoke.sh` stays broken; it is deferred, as the plan says.


### Phases

#### Phase 1 - Updater targets the active instance [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED), tests/active/upstream_snippet_cases.json (NEW), tests/active/test_updater_worker.py (EDITED)

**Checkpoint.** Test boundary: the updater module is loaded in-process from its file, the way tests/active/test_updater_worker.py already loads it (the test_host_normalisation._load_job pattern). C1: `parse_upstream_snippet` is parametrized over tests/active/upstream_snippet_cases.json, which the test reads at run time, plus a missing-file case that raises ValueError. `engine_instance_unit(7070)` returns exactly "peertube-engine@7070" with no `.service`, and 7072 raises ValueError. A source scan of `main`, marked `# rat-tail:` as at lines 80 and 309, asserts that both `systemctl_cmd` calls pass `service_name=engine_unit` (an ast.Name). C2: the test holds a real `fcntl.flock` on a tmp lock file, and `acquire_deploy_lock(wait_seconds=0)` must raise RuntimeError. On a chmod 0444 lock file it must return an fd, which `release_deploy_lock` closes. The same source scan asserts that the `acquire_deploy_lock` call comes before the `service_stopped = True` line. The existing `test_main_runs_similarity_stage_after_service_start` stays green unchanged.

**Intent.** When updater-worker.py is given `--engine-upstream-snippet`, it stops and restarts the `peertube-engine@<port>` instance that the snippet names, and it holds the deploy flock from before the stop until after the start.

- C1 - The stop and the start both act on the single unit `peertube-engine@<port>`, spelled without `.service`, that `parse_upstream_snippet` resolves from the snippet.
- C2 - The worker takes the deploy lock before stopping anything, and if the lock is still held when the bounded wait runs out, it raises and stops nothing.

**Outcome.** ### `engine/server/db/jobs/updater-worker.py`
- **Imports and constants.** Added `import fcntl` and `import re`. After the imports, added these module constants: `ENGINE_INSTANCE_BASE = "peertube-engine"`, `ENGINE_INSTANCE_PORTS = (7070, 7071)`, `DEPLOY_LOCK_WAIT_SECONDS = 30 * 60`, `DEPLOY_LOCK_POLL_SECONDS = 5.0`, and the two snippet regexes `UPSTREAM_ANY_SERVER_RE` and `UPSTREAM_SERVER_LINE_RE`. These use the same rule as the bash `read_active_port`.
- **`parse_args`.** Two new options after `--skip-systemctl`:
  - `--engine-upstream-snippet`, default `None`.
  - `--deploy-lock-file`, default `<repo>/engine/server/db/engine-deploy.lock`, resolved. It is a different file from `--lock-file`.
- **New helpers after `systemctl_cmd`.**
  - `parse_upstream_snippet(path) -> int`: the file needs exactly one `server` line, and it must be `server 127.0.0.1:7070;` or `…7071;`. Anything else raises `ValueError`, and so does an unreadable or missing file. It reads bytes and splits on `\n` only, so a CRLF snippet is rejected the way the bash grep rejects it. The plan's `read_text` would have translated the CRLF away and accepted it.
  - `engine_instance_unit(port)`: returns `peertube-engine@<port>` with no `.service` suffix, only for 7070 and 7071. Any other port raises `ValueError`.
  - `acquire_deploy_lock(lock_path, *, wait_seconds, poll_seconds=DEPLOY_LOCK_POLL_SECONDS)`: opens the file `O_RDONLY|O_CREAT` (root may own it as 0644) and tries a non-blocking `fcntl.flock` every `poll_seconds` until `wait_seconds` is used up. It returns the fd. On timeout it closes the fd and raises `RuntimeError`.
  - `release_deploy_lock(fd)`: does nothing for `None`; otherwise it unlocks and closes the fd.
- **`main()`, stop/start block.**
  - `engine_unit` starts as `args.service_name` and `deploy_lock_fd` as `None`.
  - When `--engine-upstream-snippet` is given and systemctl is not skipped, the worker first takes the deploy lock with `wait_seconds=DEPLOY_LOCK_WAIT_SECONDS`. Only then does it resolve the unit, once, as `engine_instance_unit(parse_upstream_snippet(Path(args.engine_upstream_snippet)))`, logs it, and stops it. A lock timeout or a bad snippet therefore raises before anything is stopped.
  - The stop and the start both pass `service_name=engine_unit`.
  - The outer `finally` now wraps the start in its own `try` whose `finally` calls `release_deploy_lock(deploy_lock_fd)`. The lock is held through merge, popularity and the ANN rebuild, and is released after the start even when the start raises.
  - The existing `test_main_runs_similarity_stage_after_service_start` scan still finds exactly one `Try` whose `finalbody` contains the start.
  - Without the flag, the commands are the same as before.

### `tests/active/upstream_snippet_cases.json` (new)
The plan's §7.1 case table as a JSON list of `{id, text, port}`, with `port: null` for a rejected snippet. Accepted: `active-7070`, `active-7071`, `tabs-no-final-newline`. Rejected: `foreign-port`, `foreign-host`, `two-servers`, `server-params`, `commented-out`, `crlf`, `empty`.

### `tests/active/test_updater_worker.py`
Not touched. The phase checkpoint covers the plan's §7.3 additions, and this step asked for production code only. The existing tests in this file still match the new `main()` structure: the start is still inside the outer `finally`, and `run_similarity_stage` still comes after that `try`.

#### Phase 2 - Blue/green deploy script [code]

**Files touched.** engine/engine-upstream.sh (NEW), scripts/deploy-bluegreen.sh (NEW), tests/active/test_deploy_bluegreen.py (NEW), .gitignore (EDITED)

**Checkpoint.** Test boundary: scripts/deploy-bluegreen.sh run as a subprocess from a temp tree (`scripts/`, `engine/engine-upstream.sh`, `engine/server/db/`, `nginx/` snippet), with stubs for systemctl, nginx, curl, logger and id in `bin/` on PATH. Two test-only variables are set: PEERTUBE_ENGINE_UPSTREAM_SNIPPET and PEERTUBE_CLIENT_UNIT_PATH. Every run uses `--drain 0 --warmup 0 --timeout 3`. This is a new harness: tests/active has no earlier shell-script test. C1: in both directions (7070→7071 and 7071→7070) the run exits 0, and calls.log shows `start @target` < `reload nginx` < `stop @old` < `enable @target` < `disable @old`. The snippet bytes equal `snippet_text <target>` with mode 0644. random-cache.tmp.<old pid>.db and its -journal sidecar are removed, and the decoy file stays. C2: covers the readiness timeout, a failed unit, `nginx -t` failure, reload failure, a post-switch 502 and a wrong upstream, plus the refusals: lock held (by a real fcntl.flock in the test), updater active or activating, invalid snippet (every null case from the shared JSON), Client not on 7079, a foreign listener and non-root. Each ends with a non-zero exit, the snippet bytes unchanged and no `stop @old` in calls.log. A missing `--blue-green` exits 2 with no lock file created. The bash `read_active_port` is checked against the same JSON cases, and a failure inside rollback logs `ROLLBACK FAILED`.

**Intent.** scripts/deploy-bluegreen.sh, using the shared engine/engine-upstream.sh, moves traffic to the other instance and stops the old instance only after 127.0.0.1:7079 confirms the target. Every refusal, and every failure before that confirmation, leaves the old instance serving and the snippet as it was.

- C1 - A clean run starts the target instance, switches the snippet and reloads nginx, and stops the old instance only after the 7079 check has named the target.
- C2 - Every refusal, and every failure before the 7079 check passes, ends non-zero with the original snippet in place and the old instance never stopped.

**Outcome.** ### `engine/engine-upstream.sh` (new, sourced, never run)
The bash side of the upstream snippet. It defines `ENGINE_INSTANCE_BASE=peertube-engine`, `ENGINE_INSTANCE_PORTS=(7070 7071)`, `ENGINE_LISTENER_PORT=7079` and `UPSTREAM_SNIPPET` (`${PEERTUBE_ENGINE_UPSTREAM_SNIPPET:-/etc/nginx/peertube-engine-upstream.conf}`; the env var is only for tests). Functions:
- `engine_deploy_lock_path <repo>` prints `<repo>/engine/server/db/engine-deploy.lock`.
- `read_active_port <path>` prints 7070 or 7071. The file must have exactly one line starting with `server`, and that line must be `server 127.0.0.1:7070;` or `…7071;` (`[[:blank:]]` around it). Anything else returns non-zero: a missing or unreadable file, CRLF line endings, a foreign host or port, two servers, server parameters. This is the same rule as `parse_upstream_snippet` in `updater-worker.py`.
- `other_instance_port` returns the other port of the pair.
- `snippet_text <port>` prints the three-line snippet.
- `replace_file <dest>` replaces a file atomically from stdin. It uses `mktemp` in the destination's directory under a dotted name that does not end in `.conf`, then `chmod 0644`, then `mv -f`, and removes the temp file if any step fails.

The plan's `ENGINE_LISTENER_CONF` and `engine_listener_text` are not added here: only the Phase 3 installer uses them, so they belong in that phase.

### `scripts/deploy-bluegreen.sh` (new)
The plan's §3 script. Usage is the header comment block. Options are `--blue-green` (required; without it the script prints usage and exits 2 before anything else), `--timeout` (300), `--warmup` (0), `--drain` (30), `--dry-run` and `-h`. The repo root is found the same way as in `run-services.sh`. The script sources `engine/engine-upstream.sh`.

Order of a run:
1. Root check through `id -u`, then the required commands (`flock`, `curl`, `systemctl`, `nginx`, `logger`).
2. `exec 9>>` on the lock file, `chmod 0644` on it, then `flock -n 9` (refused if held).
3. Refused if `peertube-updater.service` is active, activating, deactivating or reloading.
4. Client preflight: refused if the Client unit exists without `--engine-url http://127.0.0.1:7079`. The unit path can be overridden with `PEERTUBE_CLIENT_UNIT_PATH`.
5. `read_active_port`, refused if the snippet is invalid or missing.
6. A leftover target instance that is not inactive is stopped.
7. Refused if anything still answers on the target port.
8. Start the target, then wait for readiness: every 2 s; 429 or no answer means not ready; a `failed` or `inactive` unit ends the wait at once. Then the optional warm-up and one more check.
9. Copy the snippet to a `.bak` backup, then set `PHASE=switching`.
10. Write the target snippet with `replace_file`, run `nginx -t`, then `systemctl reload nginx`.
11. Probe 7079 up to 10 times, 1 s apart. It needs a 200 whose `X-Engine-Upstream` names the target. Then `PHASE=switched`.
12. Record the old instance's `MainPID`, drain, stop the old instance, enable the new one and disable the old one.
13. Remove `random-cache.tmp.<pid>.db` and its `-journal`, then exit 0.

How failures are handled:
- One `rollback` function acts on the phase.
  - `pre-switch`: stop the target.
  - `switching`: restore the backup, run `nginx -t`, reload, stop the target.
  - `switched`: log `post_switch_failure`, carry on, and exit 1 at the end.
- If a step inside rollback fails, it logs `event=rollback_failed msg="ROLLBACK FAILED" at=<step>` with the snippet and both unit states, and exits 1.
- `INT` and `TERM` traps route to the same rollback.
- `sleep`, `curl` and `logger` get `9>&-`, so no child keeps the lock open.
- Every line is `deploy_id=<UTC>-<pid> event=… k=v`. It goes to stdout and to `logger -t peertube-engine-deploy`.
- `--dry-run` prints the ports, the updater and Client preflight state, and the ordered actions. It takes no lock and changes nothing.

Where I departed from the plan's draft:
- **Foreign listener.** It is a `refuse` (`port_in_use_by_foreign_process`) rather than a `rollback`, because nothing has been started at that point.
- **`logger` failure.** If `logger` fails, the script prints a warning to stderr instead of `|| true`, so the failure is not swallowed.
- **Lock file mode.** The lock file is set to `chmod 0644` after it is opened. Phase 1's updater opens it `O_RDONLY` as the service user, and a root umask of 077 would otherwise leave it at 0600 and lock the updater out.
- **Not gated:** `--dry-run`, `--help` and the warm-up check are in the approved §3 design and the requirements, but this checkpoint does not exercise them.

### `.gitignore`
Under the local data patterns, added `engine/server/db/engine-deploy.lock` with a one-line reason: the existing `*.db*` patterns do not match it.

### `tests/active/test_deploy_bluegreen.py`
Not touched. The phase checkpoint in `tests/tmp` carries every C1/C2 case. This step asked for production code only, so this is the same handling as Phase 1's `test_updater_worker.py`.

**Beyond the files named.** tests/tmp/test_probe_26_p2_impl.py: a throwaway probe. It loaded the checkpoint module by path and ran every one of its test bodies against the new script: 37 passed, and `/usr/bin/flock` exists. I have no delete tool, so its content is now a single comment line asking for the file to be deleted, like the earlier `tests/tmp/probe_26_p2_draft/` leftovers; it collects no tests.

#### Phase 3 - Prod Engine install and uninstall [code]

**Files touched.** engine/install-engine-service.sh (EDITED), engine/uninstall-engine-service.sh (EDITED), scripts/install-service.sh (EDITED), engine/watch-engine-logs.sh (EDITED), tests/active/test_installers_dry_run.py (NEW)

**Checkpoint.** Test boundary: engine/install-engine-service.sh and engine/uninstall-engine-service.sh run as subprocesses with `--mode prod --dry-run`, against a fake project tree (an executable stub `venv/bin/python3` plus stub server.py files) and with the stub systemctl on PATH. PEERTUBE_ENGINE_UPSTREAM_SNIPPET points into tmp, and the checks are on stdout. C1: the install preview contains `ExecStart=… --host 127.0.0.1 --port %i` and `unit=/etc/systemd/system/peertube-engine@.service`. Its listener preview has `listen 127.0.0.1:7079;` and no other `listen`. It reports `active_port=7070 snippet=new` when there is no snippet and `active_port=7071 snippet=existing` with a 7071 snippet. An invalid snippet exits 1, `--port 7070` in prod exits 1, the snippet file is never created, and the dev preview is unchanged (`--port 7171`, `peertube-engine-dev.service`). C2: the uninstall preview lists stop and disable for `peertube-engine@7070` and `@7071`, removal of the template, the listener before the snippet, and `nginx -t`.

**Intent.** The prod Engine installer manages the `peertube-engine@.service` template, the 7079 loopback listener and the upstream snippet without changing the port the snippet already names, and the prod uninstaller removes all of them.

- C1 - A prod install --dry-run previews a template ending in `--port %i` and a listener whose only listen is 127.0.0.1:7079, keeps the port the existing snippet names (7070 when there is none), and writes nothing.
- C2 - A prod uninstall --dry-run stops and disables both instances, removes the template, then the listener, then the snippet, and then runs `nginx -t`.

**Outcome.** ### `engine/install-engine-service.sh`
- **Library and flags.** It now sources `engine/engine-upstream.sh` from its own directory. It adds the flags `HOST_SET` and `PORT_SET`, which the `--host` and `--port` cases set, and the constants `PROD_TEMPLATE_PATH` (`/etc/systemd/system/peertube-engine@.service`), `LEGACY_PROD_UNIT_PATH` (`/etc/systemd/system/peertube-engine.service`) and `PROD_READY_TIMEOUT=300`.
- **Mode dispatch.** The entry point runs `install_engine_prod` for `--mode prod` and the unchanged `install_engine_service` for dev. The dev dry-run output is byte-for-byte the same as before. `--print-default-service-name` still prints `peertube-engine`.
- **`engine_listener_text`.** Prints the 7079 listener. It includes the snippet by absolute path, and its one `server` block has:
  - `listen 127.0.0.1:7079` only;
  - `server_tokens off`;
  - its own `access_log`;
  - `client_max_body_size 2m`;
  - `location /` with `proxy_pass http://peertube_engine`, `proxy_set_header Host $http_host` and `add_header X-Engine-Upstream $upstream_addr`;
  - no keepalive.
  This function lives in the installer, not the library, because the installer is its only user.
- **`wait_http_200`.** A curl poll every 2 s until HTTP 200 or a timeout.
- **`install_engine_prod`, refusals and checks:**
  - It refuses a non-default `--service-name`, and `--host`/`--port` in any form, even `--port 7070`. Both exit 1.
  - It checks for `server.py` and the venv python.
  - Outside dry-run only, it requires root and the commands `systemctl`, `journalctl`, `nginx`, `flock` and `curl`.
- **`install_engine_prod`, deploy lock.** Outside dry-run only, it takes the deploy lock with `exec 9>>`, sets the lock file to `chmod 0644` (as the deploy script does, so the updater can open it read-only), then runs `flock -n`.
- **`install_engine_prod`, snippet.** It reads the snippet before writing anything:
  - missing: port 7070, `snippet=new`;
  - valid: its port is kept, `snippet=existing`;
  - invalid: exit 1, and nothing is touched.
- **`install_engine_prod`, dry-run.** It prints the header (`active_port=<p> snippet=new|existing`, `unit=<template>`, the snippet and listener paths, the legacy-migration flag and the plan), then the unit, snippet and listener previews, and writes nothing. The unit preview is today's unit except that it ends `--host 127.0.0.1 --port %i`. A warning goes to stderr when `peertube-engine.service.d/` drop-ins exist.
- **`install_engine_prod`, real install:**
  1. Write the snippet (only if it is new), then the listener, then the template; `daemon-reload`.
  2. Migrate the legacy unit if it exists: stop, disable, rm, daemon-reload, reset-failed.
  3. Bring up the instance the snippet names: restart it under `--force`, start it if it is not active, and otherwise leave it alone. The port never changes.
  4. Stop the other instance if it is running, disable it, and enable the active one.
  5. Health-check the instance.
  6. Run `nginx -t`. If it fails, remove a listener this run newly created, then exit 1.
  7. Reload nginx and health-check `127.0.0.1:7079`.
  The plan's `|| true` on stopping the stray instance was dropped, so a failed stop now fails the install.
- **Usage text.** It describes the prod template, the instance pair, the nginx files and the prod refusals.

### `engine/uninstall-engine-service.sh`
- **Prod path.** It sources `engine-upstream.sh`. In prod, any `--service-name` other than `peertube-engine` exits 1. Otherwise it runs the new `uninstall_engine_prod` and exits; the dev path is unchanged.
- **`uninstall_engine_prod`:**
  - Dry-run prints a header listing the template, the legacy unit, the listener and the snippet. Outside dry-run it requires root and `systemctl`.
  - It stops and disables `peertube-engine@7070.service`, `@7071.service` and the legacy `peertube-engine.service`. These lines drop only stderr, not stdout, so their `[dry-run]` lines now show; the existing quirk of hiding them was not copied.
  - `rm -f` runs in this order: the template and the legacy unit, then the listener, then the snippet and `.bak`.
  - Outside dry-run: daemon-reload and reset-failed.
  - If nginx is present: `nginx -t`, and on success `systemctl reload nginx`. If `nginx -t` fails it exits 1 without reloading.
  - Without nginx, it logs that the check and reload were skipped, and succeeds.
  - It ends by saying that the deploy lock and any `.service.d` drop-ins are left in place.
- **Usage text.** It describes the prod removal.

### `scripts/install-service.sh`
- `install_contour` refuses `--engine-port`/`--engine-host` for the prod contour.
- `engine_cmd` passes `--host`/`--port` only for dev. They are added at the same position as before, so the dev argv is unchanged.
- In the usage text, both options are marked dev-only.
- The prod ingest URL, the echo lines and the collision check are left for Phase 4.

### `engine/watch-engine-logs.sh`
- `-prod` now follows `UNIT="peertube-engine@*"`; journalctl `-u` takes the glob.
- The help line was updated to match.

### `engine/engine-upstream.sh`
- Added `ENGINE_LISTENER_CONF="/etc/nginx/conf.d/peertube-engine-internal.conf"`, which the installer and uninstaller share. See `<unanticipated>`.

### `tests/active/test_installers_dry_run.py`
- Not created. The Phase 3 checkpoint in `tests/tmp` carries C1 and C2, and this step asked for production code only. Phases 1 and 2 handled their `tests/active` files the same way.

### Verification
- A throwaway probe loaded the checkpoint module by path and ran every test body in it. All 16 parametrised cases passed:
  - prod install: no snippet, plus the three accepted snippets;
  - the seven rejected snippets;
  - `--port`;
  - dev, both variants;
  - uninstall, both variants.
- I have no delete tool, so `tests/tmp/test_probe_26_p3_impl.py` now holds a single comment line asking for it to be deleted.

**Beyond the files named.** engine/engine-upstream.sh — added one line, `ENGINE_LISTENER_CONF=/etc/nginx/conf.d/peertube-engine-internal.conf`. The installer and the uninstaller both need the listener path. Phase 2 left it out of the shared library on purpose, as belonging to this phase, but this phase's file list does not name the library.
tests/tmp/test_probe_26_p3_impl.py — a throwaway probe. I have no delete tool, so it is now a single comment line asking to be deleted, and it collects no tests.

#### Phase 4 - Point the Client and updater at blue/green [code]

**Files touched.** client/install-client-service.sh (EDITED), scripts/install-service.sh (EDITED), engine/install-updater-service.sh (EDITED), tests/check-frontend-client-gateway.sh (EDITED), tests/active/test_installers_dry_run.py (EDITED)

**Checkpoint.** Test boundary: the Phase 3 dry-run harness in tests/active/test_installers_dry_run.py, extended. C1: `client/install-client-service.sh --mode prod --dry-run` and `scripts/install-service.sh` prod `--dry-run` both show `--engine-url http://127.0.0.1:7079`. The central installer's Engine command carries no `--host`/`--port`, and dev still shows `http://127.0.0.1:7171`. C2: `engine/install-updater-service.sh --mode prod --dry-run` has `--engine-upstream-snippet <snippet>` in its ExecStart, and its sudoers line equals exactly `<user> ALL=(root) NOPASSWD: <systemctl> stop peertube-engine@7070, <systemctl> stop peertube-engine@7071, <systemctl> start peertube-engine@7070, <systemctl> start peertube-engine@7071`. Dev keeps its single-name rule.

**Intent.** In prod, the generated Client unit reaches the Engine through the 127.0.0.1:7079 listener, and the generated updater unit runs the worker against the upstream snippet with sudo allowed only for the four instance stop/start commands.

- C1 - The prod default `--engine-url` is http://127.0.0.1:7079 in both the Client installer and the central installer, and dev stays on 7171.
- C2 - The prod updater installer's unit passes `--engine-upstream-snippet`, and its sudoers rule is exactly the four `stop|start peertube-engine@7070|7071` entries.

**Outcome.** ### `engine/install-updater-service.sh`
- Now sources `engine/engine-upstream.sh`, the same way the Engine installer and uninstaller already do. That gives it `UPSTREAM_SNIPPET` (which follows the test override `PEERTUBE_ENGINE_UPSTREAM_SNIPPET`, otherwise `/etc/nginx/peertube-engine-upstream.conf`), `ENGINE_INSTANCE_BASE` and `ENGINE_INSTANCE_PORTS`.
- The sudoers rule is built once into `updater_sudoers_rule`. The dry-run preview and the file checked by `visudo -cf` both print that one value, so they cannot drift apart.
- **Prod:** `updater_exec` gets `--engine-upstream-snippet ${UPSTREAM_SNIPPET}`, placed after the fixed flags and before `${UPDATER_FLAGS}`. It is added in the installer itself, not in the `UPDATER_FLAGS` default, so it survives the `--updater-flags` value that the central installer always passes.
- **Prod sudoers rule:** exactly `<user> ALL=(root) NOPASSWD: <systemctl> stop peertube-engine@7070, <systemctl> stop peertube-engine@7071, <systemctl> start peertube-engine@7070, <systemctl> start peertube-engine@7071`. It is built from the shared base name and port list, with no `.service` suffix, matching the worker's `systemctl_cmd`. A comment says that `--engine-service-name` no longer affects the prod rule.
- **Dev:** `ExecStart` and the single-name rule are unchanged.
- Usage line for prod now names `peertube-engine@7070|7071 (active one from the nginx upstream snippet)`.

### `client/install-client-service.sh`
- `DEFAULT_PROD_ENGINE_PORT` is now 7079, so the prod default `--engine-url` is `http://127.0.0.1:7079`. A comment says this is the nginx loopback listener. Dev stays on 7171.
- An explicit `--engine-url` still overrides the default.
- The `--engine-url` help now states both defaults, and the prod usage example uses 7079.

### `scripts/install-service.sh`
- Added `PROD_ENGINE_LISTENER_URL="http://127.0.0.1:7079"`. For the prod contour, `engine_ingest_base` is that URL unless `--client-engine-url` is given. Dev keeps `http://${engine_host}:${engine_port}`.
- Port collision check: in prod it refuses a Client port of 7070, 7071 or 7079. Dev keeps the Engine≠Client check.
- The prod Engine echo line now reads `engine=peertube-engine@7070|7071 via http://127.0.0.1:7079` instead of a host:port the prod Engine no longer uses. Dev's line is unchanged.
- Phase 3 had left the ingest URL, echo lines and collision check for this phase; they are all done.

### `tests/check-frontend-client-gateway.sh`
- Added `7079` to both port alternations on the hardcoded-Engine-port guard, as the plan says.

### `tests/active/test_installers_dry_run.py`
- Not created. The Phase 4 checkpoint in `tests/tmp` carries C1 and C2, and this step asked for production code only. Phase 3 handled the file the same way.

### Verification
- A throwaway probe loaded the checkpoint by path and ran every test body in it. All 11 cases passed: Client prod, dev and explicit URL; central prod, dev and all; the four updater prod variants (direct or via the central installer, with and without the snippet override); and updater dev.
- I have no delete tool, so `tests/tmp/test_probe_26_p4_impl.py` is now a single comment line asking to be deleted. It collects no tests.

### Noticed, not changed
- `tests/run-installers-smoke.sh` is outside this phase's files.
- `dry_install_prod_engine_port` (line 836) greps the central prod dry-run for `127.0.0.1:7070`. The plan already lists that check as broken since Phase 3.
- The live-install check at lines 589-595 builds the expected prod ingest base as `http://127.0.0.1:7070`. It will now see 7079.

**Beyond the files named.** tests/tmp/test_probe_26_p4_impl.py — throwaway probe; I can't delete files, so it is now one comment line asking to be deleted, and it collects no tests.


