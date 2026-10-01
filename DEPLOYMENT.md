# Deployment Guide

This project now has separate services:
- Engine API (read/analytics) — default: `http://127.0.0.1:7070`
- Client backend API (write/profile) — recommended local port: `7072` (dev default is `7172`)
- Static client (built assets)

Below is a clean, minimal order of operations. Docker is intentionally not used.

## 0) Python environment

`engine/server/requirements.txt` pins `torch==2.5.1+cu121`, which publishes no wheels
for Python 3.13+. Use Python 3.12. Verify with `python3 --version` before anything else;
a 3.14 interpreter fails at pip resolution, not at runtime, so the error appears late.

Two supported routes.

**venv** (what the systemd units expect — see section 2):
```bash
python3.12 -m venv venv
./venv/bin/python3 -m pip install --no-cache-dir -r ./engine/server/requirements.txt
```

**pixi**, with a manifest dedicated to the Engine. The repo root `pixi.toml` belongs to a
different workspace and resolves a newer Python, so do not install Engine deps into it:
```bash
pixi init engine --channel conda-forge
pixi add --manifest-path engine/pixi.toml "python==3.12.*" pip
pixi run --manifest-path engine/pixi.toml python -m pip install --no-cache-dir \
  -r engine/server/requirements.txt
```
Every later `python` command then becomes
`pixi run --manifest-path engine/pixi.toml python …`, run from the project root so the
repo-relative paths in `DATA_BUILD.md` still resolve.

Without an NVIDIA GPU, swap `faiss-gpu-cu12` for the commented `faiss-cpu` line in
`engine/server/requirements.txt` and drop the `--extra-index-url` line.

## 1) Prepare the database
Follow `DATA_BUILD.md`. It explains how to create the SQLite files and FAISS index in `engine/server/db/`.

An existing `whitelist.db` must be migrated with `migrate-whitelist.py` before the Engine is started on newer code, or `/api/video` fails (see Triage). For the upgrade order, see `DATA_BUILD.md`.

The crawl stages are strictly sequential and each must **finish** before the next starts;
running them concurrently, or running `sync-whitelist.py` before `crawl:videos` completes,
produces an empty or partial dataset rather than an error. The npm scripts live in
`engine/crawler/package.json`, so either `cd engine/crawler` first or use `--prefix`:
```bash
nohup bash -c 'cd engine/crawler && npm run crawl:instances \
  && npm run crawl:channels && npm run crawl:channels:videos-count \
  && npm run crawl:videos' > /tmp/crawl.log 2>&1 &
```
Expect hours. `crawl:videos:tags` and `crawl:videos:comments` are optional enrichment
(one request per video); skipping them builds a working dataset with weaker embedding
text, and they can be added later followed by `build-video-embeddings.py --force`.

Checkpoint before moving on — `channels` and `videos` must both be non-zero:
```bash
sqlite3 engine/crawler/data/crawl.db \
  "select (select count(*) from channels), (select count(*) from videos);"
```

Expected files (examples):
- `engine/server/db/whitelist.db`
- `engine/server/db/similarity-cache.db`
- `engine/server/db/random-cache.db`
- `engine/server/db/whitelist-video-embeddings.faiss`

Client backend keeps its own users DB (default):
- `client/backend/db/users.db`

Note: Engine recommendation ranking does not require local `engine/server/db/users.db`.
Bridge-ingested interaction events are aggregated in the Engine's `interaction_signals`, which no ranking reads: the popular ordering (the recommendation mix's popular layer and the hot feed mode) and the popular feed mode sort on crawled `popularity`, likes and views only. For the feed orders themselves see `engine/server/api/recommendations/docs/OVERVIEW.md`.

## 2) Install systemd services (prod/dev contours)

### Prerequisite: the installers require a venv interpreter

`engine/install-engine-service.sh` sets `VENV_PY="${PROJECT_DIR}/venv/bin/python3"` and
aborts with `Missing python interpreter in venv` if that file is absent. The unit's
`ExecStart` is written against that exact path. A pixi-only setup (section 0) therefore
**cannot install services** without one of:

1. **Create a real venv.** Follow the venv route in section 0. Correct and boring, but
   it installs torch and faiss a second time — several GB duplicated.
2. **Symlink it.** `mkdir -p venv/bin && ln -s "$PWD/engine/.pixi/envs/default/bin/python" venv/bin/python3`.
   The installers only ever execute that path, so this works. It is a deliberate lie to
   the installer; note it somewhere, because a future pixi environment rebuild silently
   breaks the services.
3. **Add a `--python` argument to the installers.** The right fix, and the only one that
   leaves the repo honest. Needs a task.

### What gets installed

| Unit | Type | Behaviour |
|---|---|---|
| `peertube-engine.service` | simple | `ExecStart=<venv python> engine/server/api/server.py --host 127.0.0.1 --port 7070`, `Restart=on-failure`, `TimeoutStopSec=20`, runs as the invoking user |
| `peertube-client.service` | simple | same shape, `--port 7072 --engine-url http://127.0.0.1:7070` |
| `peertube-updater.service` | oneshot | full data pipeline, `TimeoutStartSec=24h` |
| `peertube-updater.timer` | — | `OnCalendar=Fri *-*-* 20:00:00`, `Persistent=false` |

Dev contour installs the same units under `-dev` names on ports 7171/7172, so both
contours can run side by side.

Both service units carry `Environment=PYTHONUNBUFFERED=1`, their mode variable
(`ENGINE_INGEST_MODE` / `CLIENT_PUBLISH_MODE`) and
`EnvironmentFile=-<project>/.env.bridge` for the bridge secret from section 3b. The
leading `-` makes the file optional to systemd, so a missing secret is **not** a startup
failure — it surfaces later as 503s on `/internal/*`. The Client unit also reads
`TRUSTED_PROXIES` from that file (section 6).

The Engine also reads an optional `INTERACTION_RAW_RETENTION_DAYS`, a positive integer that defaults to 30; set it with an `Environment=` line in the Engine unit or in `.env.bridge`. Interaction events older than that many days lose their `raw_payload_json`, `actor_id` and `source_instance` and keep their ids (`docs/project/adr/0005-raw-event-retention-keeps-ids.md`). The strip runs from a successful `/internal/events/ingest`, at most once per `INTERACTION_RAW_PRUNE_INTERVAL_SECONDS` (3600), and the first successful ingest after each Engine start runs one. Only `ENGINE_INGEST_MODE=bridge` serves that route, so only a bridge-mode Engine strips. Each strip shares the ingest request's 5 s statement deadline, so a large backlog, such as the one the first run after an upgrade finds, clears over several hourly runs and does not advance while no likes are ingested. A value that is not a positive integer stops the Engine at startup (see Triage).

The Engine also reads an optional `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`, a non-negative integer that sets the minutes between rebuilds of `random-cache.db`; set it with an `Environment=` line in the Engine unit or in `.env.bridge`. It defaults to 60, and 0 disables the periodic rebuild. The units run without `--dev`, so both contours use the default. Each rebuild is a full filtered scan of `whitelist.db` in a background thread of the serving Engine, so it takes CPU and GIL time from request threads. For what the setting and the startup build do, see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`. A value that is not a non-negative integer stops the Engine at startup (see Triage).

### Day to day

```bash
systemctl status peertube-engine
systemctl restart peertube-client
journalctl -u peertube-engine -f
systemctl list-timers peertube-updater.timer
```

What systemd buys over running the processes by hand: restart on crash, start on boot
(`WantedBy=multi-user.target`), and journald log capture.

### The updater timer

Enabled by `--with-updater-timer`. Weekly, it crawls to a staging database, builds embeddings, merges to prod, recomputes popularity, rebuilds the ANN index and refreshes the similarity cache. It **stops the Engine service** only from the merge through the ANN rebuild and starts it again before the similarity stage, also when an earlier stage fails. That is why the installer adds a narrow sudoers rule allowing only `systemctl stop|start <exact unit>`.

The similarity stage runs with the Engine up, as a shadow build next to `engine/server/db/similarity-cache.db`:
- `similarity-cache.db.building` is the build marker: the cache file name plus `.building`, holding the updater's PID as decimal text. While it names a live process, running Engines serve cache misses without storing them. A marker with a dead PID or unparseable content is ignored, and the next updater run deletes it.
- `similarity-cache.next.db` is the shadow: a copy of the active cache that the precompute refreshes. If it passes the gate, it replaces `similarity-cache.db`, and each running Engine reopens the new file on its next cache access, with no restart. A shadow and its `-journal` left by a killed run are deleted by the next run.
- `similarity-cache.prev.db` is the cache the last swap replaced, hardlinked where the filesystem allows and copied otherwise. There is no automatic rollback; to restore it, run `mv engine/server/db/similarity-cache.prev.db engine/server/db/similarity-cache.db`. The Engines pick it up the same way, so nothing needs a restart.

During the stage the active cache and the shadow sit side by side, so plan for twice the cache size free; where the hardlink falls back to a copy, the swap briefly needs three times. A hardlinked `.prev.db` takes no extra space at the swap, but it keeps the replaced cache on disk until the next swap, so between runs the cache takes about twice its size. For the stage order, the gate and the log lines, see `engine/server/db/jobs/docs/UPDATER_WORKER.md`.

Two things it does not know about: the crawler's `excluded-hosts.txt`, and any manual
enrichment stages. `UPDATER_FLAGS` defaults to `--gpu --skip-local-dead --concurrency 5`.

Recommendation: install **without** `--with-updater-timer` first, run the updater once by
hand (`systemctl start peertube-updater.service`, then `journalctl -u peertube-updater -f`)
and watch what it does to your dataset before letting it run unattended.

### Triage

| Symptom | Likely cause | Action |
|---|---|---|
| Installer exits `Missing python interpreter in venv` | pixi-only setup, no `venv/` | Prerequisite above |
| Unit `activating` then `failed`, journal shows `ModuleNotFoundError` | `venv` symlink points at a rebuilt or removed pixi env | Re-point the symlink, or install deps into a real venv |
| Engine `active` but `/api/health` refuses connections for minutes | Normal: ANN index load on a large dataset | Wait; confirm with `journalctl -u peertube-engine -f` |
| Browsing works, likes fail, Engine logs `bridge.auth` | `.env.bridge` missing or unreadable by the service user | Section 3b; the `-` prefix makes systemd ignore a missing file |
| Client unit `failed` or restarting in a loop, journal shows `TRUSTED_PROXIES entry is not an IP address or CIDR range` | Malformed `TRUSTED_PROXIES` entry | Fix the entry the journal names; syntax in section 6 |
| `502` from the Client backend on profile routes or likes | Engine 401/503 on `/internal/*` — token mismatch between the two units. The body names only the failing call; the Engine's status and error are in `journalctl -u peertube-client`, in the ERROR `engine.call` or `engine.bridge` record's `context.error` | Confirm both read the same `.env.bridge` |
| `500` from the Engine with `Recommendations request failed` or `Event ingest failed` | An unexpected exception in the recommendations or ingest handler; the body is fixed text | `journalctl -u peertube-engine`; the JSON log record's `traceback` key holds the cause |
| `debug=1` answers `403 Debug mode is disabled` | The Engine runs without `RECOMMENDATIONS_DEBUG` | Section 7 |
| Dev page's API calls blocked by CORS in the browser console | The Client backend does not list the page's exact origin | Set `CLIENT_CORS_ORIGINS` on the Client backend; section 6 "Local alternative" |
| Nothing on port 80 | nginx serves the static client; the units only bind loopback | Section 6 |
| Updater ran and the feed went stale or empty | Updater rebuilt the dataset with its own flags | `journalctl -u peertube-updater`; consider disabling the timer |
| Updater exits non-zero, journal shows `Similarity gate failed: <reason>` | The shadow cache failed the pre-swap gate. The active cache is untouched and the Engine is serving. A denylist `block` without `--purge-now` during the build is one cause: the shadow loses that host's sources, so it holds fewer than the active cache | Read the reason and the `similarity gate result=fail` line's counts in `journalctl -u peertube-updater`; for a denylist block, the next run's post-merge prune clears it |
| Engine journal shows `[similar-cache] reopen failed ... reason=...` | The file at `similarity-cache.db` is not a valid cache, or is missing. The Engine keeps serving from its old handle, stores nothing, and retries on each cache access | Put a valid cache in place, for example by restoring `similarity-cache.prev.db` (see "The updater timer") |
| Dev and prod fighting over ports | Both contours installed | `systemctl list-units 'peertube-*'`; dev uses 7171/7172 |
| Every video page shows its metadata but no category, language or tags; the Client logs `engine.proxy` 502 on `/api/video`; the Engine journal shows `sqlite3.OperationalError: no such column: v.language` | `whitelist.db` was not migrated before the Engine restarted. The Engine drops the connection, and the page falls back to reading the source instance directly | Run `migrate-whitelist.py` on the Engine's `whitelist.db` (see `DATA_BUILD.md`), then `systemctl restart peertube-engine` |
| Engine unit `activating` then `failed` and restart-looping, last journal line `INTERACTION_RAW_RETENTION_DAYS must be a positive integer, got '…'` | The value is not a positive integer (`abc`, `0`, `-3`, `7.5`, empty). The check runs when `server_config` is imported, so the DB jobs and the updater worker exit the same way when the value is in their environment, and with the value in `.env.bridge` the Engine the updater restarts fails the same way | Fix or remove the value in the unit or `.env.bridge`, then `systemctl restart peertube-engine` |
| Engine unit `activating` then `failed` and restart-looping, last journal line `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES must be a non-negative integer, got '…'` | The value is not a non-negative integer (`abc`, `-3`, `7.5`). The check runs when `server_config` is imported, so the DB jobs, `precompute-random-rowids.py` and the updater worker exit the same way when the value is in their environment | Fix or remove the value in the unit or `.env.bridge`, then `systemctl restart peertube-engine` |

Centralized installer (source of truth):
```bash
# Prod contour (force reinstall default + updater timer enabled by default)
sudo bash install-service.sh --mode prod --force --with-updater-timer

# Dev contour (separate unit names/ports, safe for local parallel run with prod)
sudo bash install-service.sh --mode dev --force --uninstall
```

Convenience wrappers:
```bash
sudo bash install-service-prod.sh
sudo bash install-service-dev.sh --uninstall
```

Service-specific installers (each supports its own `--mode prod|dev`):
```bash
sudo bash engine/install-engine-service.sh --mode prod --force
sudo bash client/install-client-service.sh --mode dev --force --engine-url http://127.0.0.1:7171
```

Uninstall (symmetric):
```bash
# Centralized contour uninstall
sudo bash uninstall-service.sh --mode dev
sudo bash uninstall-service.sh --mode prod --purge-updater-state

# Wrapper presets
sudo bash uninstall-service-dev.sh
sudo bash uninstall-service-prod.sh --purge-updater-state

# Service-specific uninstallers
sudo bash engine/uninstall-engine-service.sh --mode dev
sudo bash client/uninstall-client-service.sh --mode dev
```

## 3) Build the client
From the project root:
```bash
cd client/frontend
npm install
npm run build
```

Output is in `client/frontend/dist/` (static files to be served).

Every page is a separate build input, so adding one means rebuilding and re-copying:
nginx serves `dist/` through `try_files`, and a page missing from the document root is a
404 rather than a fallback. After adding or changing a page, re-run this build and repeat
the `rsync` in section 6. The current pages are `index`, `videos`, `search`, `likes`,
`video-page`, `channels` and `about`.

## 3b) Bridge shared secret (required)

The Engine's `/internal/*` routes are the Client backend's read and event-ingest bridge.
They write to the interaction signal stream, so the Engine **fails closed**: without
`ENGINE_BRIDGE_TOKEN` it answers `503` on those routes, and with a wrong or missing
`X-Bridge-Token` header it answers `401`. Public `/api/*` routes are unaffected.

Both services must see the same value. Put it in one file rather than in the unit files,
which are world-readable:

```bash
printf 'ENGINE_BRIDGE_TOKEN=%s\n' "$(openssl rand -hex 32)" > .env.bridge
chmod 600 .env.bridge
```

Both systemd units read it via `EnvironmentFile=-<project>/.env.bridge`. For manual runs,
`set -a; source .env.bridge; set +a` before starting either service.

Symptom of a missing or mismatched value: likes and the profile page fail with a `502` from the Client backend, whose body is a fixed message such as `Engine metadata failed`, while browsing and search keep working. The Engine's status (`401` or `503`) and error text are only in the Client log (`journalctl -u peertube-client`), in the ERROR `engine.call` record's `context.error`.

## 4) Run the API server
From the project root (environment from section 0):
```bash
set -a; source .env.bridge; set +a
ENGINE_INGEST_MODE=bridge ./venv/bin/python3 engine/server/api/server.py
```

Engine API listens on `http://127.0.0.1:7070`.

The retention window from section 2 is set here the same way: prefix the command with `INTERACTION_RAW_RETENTION_DAYS=7`, or put the line in `.env.bridge`.

First startup loads the FAISS index and counts embeddings, which takes a while on a
full dataset — a few hundred thousand embeddings means tens of seconds before the port
accepts connections. Health checks that poll immediately will log connection refusals
until it finishes; wait for JSON from:
```bash
until curl -sf http://127.0.0.1:7070/api/health; do sleep 5; done
```

`/api/health` answers without waiting on any random-cache build. Until the first `random cache build ok` line, and whenever no usable cache is open, the random feed is served from `whitelist.db`. Each build logs `random cache build start`, then `ok` or `failed`; a `failed` line leaves the previous cache serving, and the build is retried at the next interval. These lines are INFO records tagged for the `verbose` view only, so a log viewer filtered to `focused` hides them. A `random-cache.tmp.<pid>.db` left in `engine/server/db/` by a killed Engine is safe to delete.

### Up-next logs and load

Up-next is the seeded similar-video request behind the video page (`/recommendations?id=&host=`, `/videos/similar`, `GET /videos/{id}/similar`); how its pool is built and drawn is in `engine/server/api/recommendations/docs/OVERVIEW.md`. Three Engine log lines trace it:
- `[similar-server] upnext_config SIMILAR_VIDEO_SEARCH_LIMIT=… SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR=…` is logged once at startup, right after `ann_nprobe_configured`, with the values of all nine up-next constants.
- `[similar-server] ann_fallback nprobe= search_limit= floor= hits= restored_nprobe=` is logged for each live ANN search the up-next fallback runs; `restored_nprobe` is the value read back from the index after the search and should equal the `ann_nprobe_configured` value.
- `[similar-server][<id>] upnext_pool initial= steps= restored_nprobe= final= tail= sampling= window= likes_rerank= returned=` is logged once per up-next request. `steps` lists each search as `nprobe/search_limit->pool`, or `none`, and `sampling` is `random` or `seeded`.

The similarity cache holds 20 candidates per seed (`--top-k 20`, see `DATA_BUILD.md`), fewer than the 48-row pool up-next needs, so nearly every up-next request runs the fallback: up to three searches, from nprobe 32 / k 5000 up to nprobe 128 / k 20000, each under the `index_lock` that home and search requests share. The Engine's 5 s request deadline bounds only SQLite statements, not FAISS, so a request whose searches overrun it fails at its next database statement with `500 Recommendations request failed`.

### Ordered feed load

The hot and popular feed modes sort every embedded video on stored columns for each chunk they read (hot leads with `popularity`, popular with `likes`), and recent sorts on `published_at`. A chunk is the page plus the request's `exclude` list plus 32 rows, so a late page, with about 500 rows in `exclude`, reads 580 or more rows per chunk, and a request reads at most 4 chunks, each under `db_lock`. Each chunk's query runs inside the 5 s request deadline; one that overruns it answers `500 Recommendations request failed`.

## 5) Run the client backend service
From the project root:
```bash
set -a; source .env.bridge; set +a
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py \
  --port 7072 \
  --engine-url http://127.0.0.1:7070
```

Start it only after the Engine answers `/api/health`.

There is no browser-facing event publish route. Interaction events are emitted by the
Client backend from `/api/user-action`, after the video identity has been resolved
against the Engine; `POST /client/events/publish` no longer exists and returns 404.

A request with `X-Profile-Key` publishes a `Like` only when it opens the profile's published like of the video, and an `UndoLike` only when it closes one; a request that changes nothing answers 200 and publishes nothing. The Client backend tracks published likes in the `like_generations` table of `users.db`, which it creates at startup, so there is no migration step. Event ids are derived from the actor, the video, the event type and the like generation, so a replayed event is a duplicate at the Engine's ingest and changes no counts. A request without a key always publishes, and every keyless `Like` of a video carries one fixed id, as does every keyless `UndoLike`. For the definition of a published like see `CONTEXT.md`, and for the id scheme see `docs/project/adr/0001-derived-interaction-event-ids.md`.

Per-visitor profiles are optional. `POST /api/profile` returns a key once, and the Client backend stores only its SHA-256 in `client/backend/db/users.db`. The profile routes (`/api/user-profile*`, `/api/profile/rotate`, `/api/profile/delete`, `/api/profile/blocks*`, `/api/profile/reaction`, `/api/profile/likes/import`) and the `dislike`/`undo_dislike` actions of `/api/user-action` accept the key only in the `X-Profile-Key` request header and answer anything else with 401. A key that is lost cannot be recovered. Minting is limited to 5 per hour per client address; behind a proxy, see `TRUSTED_PROXIES` in section 6 for how that address is resolved.

A profile can block channels and accounts, up to 1,000 blocks. Blocks are stored in `users.db`, so dataset builds and the updater never touch them. When a feed (`/recommendations`, `/videos/similar`) or search (`/api/v1/search/videos`) request carries `X-Profile-Key`, the Client backend removes that profile's blocked rows from the Engine's response before returning it. For a profile with blocks, it asks the Engine for twice the page and trims to one page in every feed mode, so feed pages stay full; search pages are filtered as they are and can come back short. A feed or search request with a key that does not resolve gets the same 401 as the profile routes. Without the header, reads pass through unfiltered. The Client caps a browser's feed `limit` at 48, the Engine's page size, and the Engine accepts up to 96 so the Client can over-fetch.

A profile's likes and dislikes are kept in `users.db`; a like and a dislike on one video replace each other, and a profile holds at most 1,000 dislikes. A dislike publishes no interaction event; disliking a liked video publishes the `UndoLike` that withdraws the like from the Engine's `interaction_signals`. On every dislike change the Client backend asks the Engine (`/internal/dislikes/centroids`) for up to four taste vectors of the profile's dislikes and stores them; the Engine keeps nothing. For a feed request carrying `X-Profile-Key`, the Client backend sends the Engine the profile's own likes in place of the browser's and its taste vectors, which the Engine uses to rank similar videos lower, and removes the disliked videos from the page, over-fetching as for blocks. Search is not filtered by dislikes. On keyed feed and search responses the Client backend marks each row the profile likes or dislikes with `reaction`, which the frontend shows on the card; marking alone does not over-fetch. Taste vectors are tied to the embedding model: after a re-embed with another model the Engine ignores stored ones until the profile's next dislike change.

Boundary contract (mandatory):
- Client backend talks to Engine only over HTTP (`/internal/videos/resolve`, `/internal/videos/metadata`, `/internal/dislikes/centroids`, `/internal/events/ingest`).
- Client backend must not import `engine.server.*` modules and must not open `engine/server/db/*` files.
- Frontend reads/writes of Client and Engine data must use Client API base; no direct Engine API base calls from UI code. The video page also reads the source PeerTube instance directly from the browser (metadata fallback, `/api/v1/config`, channels, comments).

## 6) Serve the client

The frontend resolves its API base to `window.location.origin`
(`client/frontend/src/data/api-base.ts`), so whatever serves the static files must also
proxy the Client backend on the **same** origin. There are exactly four browser-facing
prefixes: `/api/`, `/recommendations`, `/videos/similar`, `/client/`.

### nginx (production)

```bash
sudo apt update && sudo apt install -y nginx
```

nginx runs as `www-data` and cannot traverse a `750` home directory, so serving straight
out of the repo fails with 404 even though the files themselves are world-readable.
Copy the build into `/var/www` instead:

```bash
sudo mkdir -p /var/www/peertube-browser
sudo rsync -a --delete client/frontend/dist/ /var/www/peertube-browser/
sudo chown -R www-data:www-data /var/www/peertube-browser
```

The served copy is not the build directory, and the `dist/` committed to the repository lags the source, so copying it unbuilt deploys an older client. `scripts/sync.sh` runs `npm run build` (section 3) and then these three commands; use it after every frontend change.

`/etc/nginx/sites-available/peertube-browser`:
```nginx
server {
    listen 80;
    server_name _;

    root /var/www/peertube-browser;
    index index.html;

    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-src https:; connect-src 'self' https:; img-src 'self' https: data:" always;

    location / {
        try_files $uri $uri/ =404;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:7072;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /recommendations {
        proxy_pass http://127.0.0.1:7072;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    location /videos/similar {
        proxy_pass http://127.0.0.1:7072;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    location /client/ {
        proxy_pass http://127.0.0.1:7072;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

The browser enforces this header and each page's own `<meta>` CSP together, so a source the header omits is blocked whatever the page allows. `connect-src 'self' https:` lets the video page read source PeerTube instances directly (metadata fallback, `/api/v1/config`, channels, comments), and `img-src 'self' https: data:` lets pages show remote images such as avatars.

The `X-Forwarded-For` lines are required, not cosmetic. When the TCP peer is a trusted proxy, the Client backend walks `X-Forwarded-For` from right to left, skipping hops that are themselves trusted proxies, and takes the first untrusted hop as the client address; a hop that is empty or not an IP address stops the walk at the last trusted address. From any other peer, the peer is the client address. The Client backend keys its rate limiters and access log on that address and forwards it to the Engine as `X-Client-IP`, which is what the Engine's rate limiter keys on. Omit the lines and every visitor shares one bucket. `X-Real-IP` is never read, so the `X-Real-IP` lines above have no effect.

`TRUSTED_PROXIES` lists the proxies the Client backend trusts: comma-separated IPv4/IPv6 addresses and CIDR ranges, for example `127.0.0.1,::1,10.0.0.0/8`. Whitespace around entries and empty items are ignored. Unset or blank, it is `127.0.0.1,::1`, which matches the same-host nginx above. A set value replaces that default rather than adding to it, so keep the loopback entries when adding others. A malformed entry stops the Client backend before it binds its port, with an error naming the entry. Every layer in front of nginx, such as a CDN or a load balancer, must be listed as well, or that layer's address becomes every visitor's key. The systemd unit reads it from `.env.bridge` through its `EnvironmentFile`, or from a drop-in (`sudo systemctl edit peertube-client`, then `Environment=TRUSTED_PROXIES=…` under `[Service]`); for a manual run, export it before starting the Client backend.

```bash
sudo ln -s /etc/nginx/sites-available/peertube-browser /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Verify:
```bash
curl -I http://localhost/                 # 200, text/html
curl -s http://localhost/api/health       # client-backend JSON, publish_mode=bridge
```
A 404 on `/` with a successful `nginx -t` means the document root is unreadable by
`www-data`; check with `sudo -u www-data stat /var/www/peertube-browser/index.html`.

### Firewall (ufw)

Loopback is exempt from ufw's default policy, so the Engine and Client backend need no
rules while they stay bound to `127.0.0.1`. **Never** open 7070 or 7072 — the Engine has
no authentication and its `/internal/*` routes accept writes.

```bash
sudo ufw allow out 443/tcp     # crawler, live video metadata, whitelist sync
sudo ufw allow out 53          # DNS
sudo ufw allow in 80/tcp       # only if reachable beyond localhost
sudo ufw allow in 443/tcp
```
Outbound 443 is a runtime dependency, not just a build one: `/api/video` makes live calls to source instances per request, and the updater timer re-crawls weekly.

`/api/video` writes the refreshed metadata back to `whitelist.db` only when the source answers with a valid video object. The write shares the request's statement deadline (5 s by default, `DEFAULT_STATEMENT_TIMEOUT_SECONDS`), which also counts the time spent waiting on the source. When a slow source uses up that deadline, the page still gets the fresh values, the write can be interrupted, and the Engine logs `[video] failed to persist dynamic metadata`.

### TLS

If this is publicly reachable, terminate TLS before opening it up — the session, the
user's like history and the `X-Profile-Key` header are otherwise in clear, and anyone who
reads that header owns the profile:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx
```

### Local alternative

For a quick local check without nginx:
```bash
cd client/frontend
npx serve -l 5173 dist
```

Dev mode shortcut:
```bash
cd client/frontend
npm run dev
```

Optional overrides:
```bash
# Set Client API target explicitly in dev
npm run dev -- --client-api-port 7172
npm run dev -- --client-api-base http://127.0.0.1:7072

# Vite port flags still work
npm run dev -- --port 5175 --strictPort --client-api-port 7172
```

`npm run dev` always points the page at a Client API base on another origin (`VITE_CLIENT_API_BASE`, `http://127.0.0.1:7172` unless overridden), so the dev setup is cross-origin, and its API calls fail in the browser until the Client backend lists the page's origin in `CLIENT_CORS_ORIGINS`. The value is comma-separated exact origins (`scheme://host[:port]`), for example `http://127.0.0.1:5173`. Whitespace around entries, empty entries and a literal `*` are ignored. Matching is exact string equality with no case folding and no trailing-slash normalisation, so `http://localhost:5173` and `http://127.0.0.1:5173` are separate entries, and a `--port 5175` run needs its own. Unset or blank, the Client backend sends no CORS headers, which is correct for production, where nginx serves everything on one origin. A request from a listed origin gets that origin echoed with `Vary: Origin`; `*` and credentials are never sent (`docs/project/adr/0004-cors-opt-in-by-origin.md`). The Client backend reads it once at startup, so a change needs a restart. Set it only on the dev Client backend: export it for a manual run, or use a drop-in on the dev unit (`sudo systemctl edit peertube-client-dev`, then `Environment=CLIENT_CORS_ORIGINS=…` under `[Service]`). Do not put it in `.env.bridge`, which the prod and dev units share.

## 7) Verify
Open:
- `/` (home)
- `/videos.html`
- `/videos.html?debug=1` (debug view, needs the toggle below)

Optional debug toggle: `debug=1` on `/recommendations` and `/videos/similar` returns per-row scoring details only when the Engine runs with `RECOMMENDATIONS_DEBUG=1`. It is off by default. `1`, `true` and `yes` turn it on, in any case and with surrounding whitespace; any other value, blank or unset leaves it off, and `debug=1` then answers `403 Debug mode is disabled`, which the debug view shows. The Engine reads it once at startup, so a change needs a restart. Set it on one Engine unit with a drop-in:
```bash
sudo systemctl edit peertube-engine    # add under [Service]: Environment=RECOMMENDATIONS_DEBUG=1
sudo systemctl restart peertube-engine
```
Putting it in `.env.bridge` turns it on for every Engine unit that reads that file, and `scripts/run-services.sh` exports that file to both services.

Up-next pages are a random draw, so two requests for one video differ. To reproduce a page, add `seed=<int>` to the up-next request; it needs no toggle. Send it to the Engine directly (`http://127.0.0.1:7070`): the Client backend does not forward it and answers `400 Unknown query parameter: seed`.

## 8) Split architecture smoke tests
Use two dedicated smoke scripts.

### A) Installer/uninstaller matrix and runtime behavior
Contract matrix only (safe, no service changes):
```bash
bash tests/run-installers-smoke.sh --dry-run-only
```

Full live dev contour verification (requires sudo/systemd):
```bash
sudo bash tests/run-installers-smoke.sh --mode dev
```

Live all-contours verification (explicit opt-in for prod changes):
```bash
sudo bash tests/run-installers-smoke.sh --mode all --allow-prod
```

What it verifies:
- all installer/uninstaller entrypoints support `--help` and `--dry-run`,
- install -> HTTP/e2e verify -> uninstall -> verify cleanup,
- idempotent re-install/re-uninstall,
- contour isolation checks,
- teardown on exit.

### B) Client/Engine boundary + bridge interaction
This script starts temporary local processes on test ports and validates split
boundaries and bridge interaction:
```bash
bash tests/run-arch-split-smoke.sh
```

It is self-contained: it starts its own Engine (7072) and Client (7272), runs its checks,
then **stops both**. It is a test, not a way to bring the services up, and its ports are
unrelated to the 7070/7072 pair used in production. While the Engine loads its index the
script prints repeated `curl: (7) Failed to connect` lines; those are its own poll loop,
not a failure.

It resolves the interpreter as `venv/bin/python3`, `venv/bin/python`, then `python3` from
`PATH`, and knows nothing about pixi. With a pixi-only setup, put the env first on `PATH`:
```bash
PATH="$PWD/engine/.pixi/envs/default/bin:$PATH" bash tests/run-arch-split-smoke.sh
```

Optional explicit endpoints:
```bash
ENGINE_URL=http://127.0.0.1:7072 CLIENT_URL=http://127.0.0.1:7272 \
  bash tests/run-arch-split-smoke.sh
```
