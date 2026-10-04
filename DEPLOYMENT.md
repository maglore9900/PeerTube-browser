# Deployment Guide

This project runs as separate services:
- Engine API (read/analytics) — prod: two systemd instances on `127.0.0.1:7070` and `127.0.0.1:7071`, one of them active, reached through nginx at `http://127.0.0.1:7079` (section 6); a manual run listens on `http://127.0.0.1:7070`
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

### Translate worker dependencies

Only a host that runs the translate worker (section 2, "Translate worker") needs these; the Engine never imports them.

1. Install ffmpeg on the system `PATH`: `sudo apt install -y ffmpeg`. Without it, `translate-worker.py run` logs `ffmpeg not found on PATH` and exits 1.
2. Pip-install faster-whisper 1.2.1 and ctranslate2 4.8.2 into the interpreter the worker's unit runs, `venv/bin/python3`. A real venv takes them with the command below; when `venv/bin/python3` is the symlink into the pixi env (section 2, "Prerequisite"), use the pixi form from above, which installs into that env. Dry-run first:
   ```bash
   ./venv/bin/python3 -m pip install --dry-run faster-whisper==1.2.1 ctranslate2==4.8.2
   ```
   Go ahead only when its `Would install` line names none of the packages the Engine's query encoder runs on — `transformers` (4.57.6), `huggingface-hub` (0.36.0), `tokenizers` (0.22.2), `numpy` (2.4.1), `torch` (2.5.1+cu121), `sympy`, `nvidia-cublas-cu12` (12.1.3.1), `nvidia-cudnn-cu12` (9.1.0.70) — and no other `nvidia-*` CUDA wheel. If it names any, leave the environment as it is and resolve the conflict first. Then run the same command without `--dry-run`. The worker loads cuBLAS and cuDNN from the `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` wheels torch already installed, so it needs no `LD_LIBRARY_PATH`.
3. Download the `medium` model once, as the service user, into the cache the unit's `HF_HOME` names:
   ```bash
   sudo -u <engine user> env HOME=/home/<engine user> HF_HOME=/home/<engine user>/.cache/huggingface \
     ./venv/bin/python3 -c "from faster_whisper import download_model; download_model('medium')"
   ```

## 1) Prepare the database
Follow `DATA_BUILD.md`. It explains how to create the SQLite files and FAISS index in `engine/server/db/`.

An existing `whitelist.db` must be migrated with `migrate-whitelist.py` before the Engine is started on newer code, or `/api/video` fails (see Triage). For the upgrade order, see `DATA_BUILD.md`.

The same run rebuilds `video_embeddings` once to add `ann_id`, which `sync-whitelist.py`, `build-video-embeddings.py` and the updater's merge require (see Triage). The ANN index is then rebuilt on `ann_id`: the Engine refuses to start while the index sidecar's `id_source` is not `video_embeddings.ann_id`, and `precompute-similar-ann.py` refuses the same way (see Triage). This cutover is a one-time Engine outage and the one exception to blue/green (`docs/project/adr/0006-derived-ann-ids.md`); a blue/green deploy onto an index not yet rebuilt rolls back at readiness and leaves the old instance serving. Run it before the first dataset build or updater run on the new code, as the service user, with the updater idle and the Engine stopped. The migration takes no deploy lock, so start it only when no deploy is running:
```bash
sudo systemctl stop peertube-updater.timer                  # then wait until peertube-updater.service is inactive
sudo systemctl stop peertube-engine@<active port>           # the port named in /etc/nginx/peertube-engine-upstream.conf
./venv/bin/python3 engine/server/db/jobs/migrate-whitelist.py --db engine/server/db/whitelist.db
./venv/bin/python3 engine/server/db/jobs/build-ann-index.py --db-path engine/server/db/whitelist.db \
  --index-path engine/server/db/whitelist-video-embeddings.faiss \
  --meta-path engine/server/db/whitelist-video-embeddings.faiss.json \
  --normalize --gpu                                         # or --cpu; keep the served paths, the job's defaults write a file the Engine does not read
sudo bash scripts/deploy-bluegreen.sh --blue-green
sudo systemctl start peertube-updater.timer
```
For the free disk, the backup it writes, why that backup is the only rollback and the random cache's rebuild on first start, see `DATA_BUILD.md` ("One-time `video_embeddings.ann_id` migration").

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
- `engine/server/db/subtitles.db`, which the Engine creates empty at its first start. It holds the English cues `/api/translate` serves, from two sources: the instance's own English caption tracks (per video, up to 2 MB of the original track text plus the parsed cues) and the translate worker's Whisper cues (about 48 KB per hour of video). It also holds the translate jobs and the worker's `translate_worker_heartbeat` row. Nothing prunes it, a denylist purge included, so include it in backups and disk sizing. It is in WAL mode: back it up with `sqlite3 engine/server/db/subtitles.db ".backup <dest>"`, or copy it together with its `-wal` and `-shm` files. Both Engine instances during a blue/green deploy, the translate worker and its `enqueue` command write it; an Engine write that finds it locked is logged as `[translate] cache write failed` and the visitor still gets the cues.

Client backend keeps its own users DB (default):
- `client/backend/db/users.db`, which also holds the About page's analytics events in `analytics_events`. Nothing prunes that table, so it grows with every About view and tracked click; include it when sizing backups (see "Count About analytics events" under Triage).

Note: Engine recommendation ranking does not require local `engine/server/db/users.db`.
Bridge-ingested interaction events are aggregated in the Engine's `interaction_signals`, which no ranking reads: the Trending feed mode and the recommendation mix's popular layer rank on each source instance's own trending list (`trending_ranks`), and the popular feed mode sorts on crawled likes and views. For the feed orders themselves see `engine/server/api/recommendations/docs/OVERVIEW.md`.

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
| `peertube-engine@.service` | simple | template: `ExecStart=<venv python> engine/server/api/server.py --host 127.0.0.1 --port %i`, `Restart=on-failure`, `TimeoutStopSec=20`, runs as the invoking user. Instances `peertube-engine@7070` and `peertube-engine@7071`; outside a deploy only the active one runs and is enabled for boot (see "Blue/green deploy") |
| `peertube-client.service` | simple | same shape, `--port 7072 --engine-url http://127.0.0.1:7079` (the nginx listener in front of the active Engine instance, section 6) |
| `peertube-updater.service` | oneshot | full data pipeline, `TimeoutStartSec=24h` |
| `peertube-updater.timer` | — | `OnCalendar=Fri *-*-* 20:00:00`, `Persistent=false` |
| `/etc/nginx/peertube-engine-upstream.conf`, `/etc/nginx/conf.d/peertube-engine-internal.conf` | nginx | the upstream snippet naming the active Engine port, and the `127.0.0.1:7079` listener (section 6) |

The dev contour installs single units under `-dev` names on ports 7171/7172 (`peertube-engine-dev.service`, no instance pair, no nginx hop, restarted in place), so both contours can run side by side.

The Engine template and the Client unit carry `Environment=PYTHONUNBUFFERED=1`, their mode variable
(`ENGINE_INGEST_MODE` / `CLIENT_PUBLISH_MODE`) and
`EnvironmentFile=-<project>/.env.bridge` for the bridge secret from section 3b. The
leading `-` makes the file optional to systemd, so a missing secret is **not** a startup
failure — it surfaces later as 503s on `/internal/*`. The Client unit also reads
`TRUSTED_PROXIES` from that file (section 6).

The Engine also reads an optional `INTERACTION_RAW_RETENTION_DAYS`, a positive integer that defaults to 30; set it with an `Environment=` line in the Engine unit or in `.env.bridge`. Interaction events older than that many days lose their `raw_payload_json`, `actor_id` and `source_instance` and keep their ids (`docs/project/adr/0005-raw-event-retention-keeps-ids.md`). The strip runs from a successful `/internal/events/ingest`, at most once per `INTERACTION_RAW_PRUNE_INTERVAL_SECONDS` (3600), and the first successful ingest after each Engine start runs one. Only `ENGINE_INGEST_MODE=bridge` serves that route, so only a bridge-mode Engine strips. Each strip shares the ingest request's 5 s statement deadline, so a large backlog, such as the one the first run after an upgrade finds, clears over several hourly runs and does not advance while no likes are ingested. A value that is not a positive integer stops the Engine at startup (see Triage).

The Engine also reads an optional `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`, a non-negative integer that sets the minutes between rebuilds of `random-cache.db`; set it with an `Environment=` line in the Engine unit or in `.env.bridge`. It defaults to 60, and 0 disables the periodic rebuild. The units run without `--dev`, so both contours use the default. Each rebuild is a full filtered scan of `whitelist.db` in a background thread of the serving Engine, so it takes CPU and GIL time from request threads. For what the setting and the startup build do, see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`. A value that is not a non-negative integer stops the Engine at startup (see Triage).

The Engine and the Client backend both read an optional `LOG_FORMAT` when they set up logging: `json` (the default) or `text`, case-insensitive, with surrounding whitespace ignored. An unset, empty or unknown value selects `json` and never stops startup. Set it in `.env.bridge`, which the prod and dev units share and `scripts/run-services.sh` exports to both services, or with an `Environment=` drop-in for one unit. Every record's `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, taken when the log call was made, and is the timestamp to order a request's lines by, not the journal's. `text` writes one `ts LEVEL event message key=value… [request_id=…] [traceback]` line per record, with CR and LF escaped as `\r` and `\n`, so a traceback stays on its record's line; values are not quoted, so it is for reading by eye. `engine/watch-engine-logs.sh` shows nothing in text mode, `client/watch-client-logs.sh` shows each line as `{"raw": …}`, and the Triage recipes that name JSON keys (`traceback`, `context.error`) assume `json`. To read every line of one request across nginx, the Client backend and the Engine, see "Follow one request" under Triage; to tie an About page visit to the visitor's app requests, see "Follow an About visit".

### Day to day

```bash
cat /etc/nginx/peertube-engine-upstream.conf          # the active Engine port: its one server line
systemctl status 'peertube-engine@*'
sudo bash scripts/deploy-bluegreen.sh --blue-green    # restart the prod Engine on the code on disk
systemctl restart peertube-client
journalctl -u 'peertube-engine@*' -f                  # or: bash engine/watch-engine-logs.sh -prod
journalctl -t peertube-engine-deploy                  # deploy runs
systemctl list-timers peertube-updater.timer
```

Never `systemctl restart` a prod Engine instance to pick up new code: the instance is down while it loads its index. The dev Engine has no instance pair and is restarted in place (`systemctl restart peertube-engine-dev`).

What systemd buys over running the processes by hand: restart on crash, start on boot
(`WantedBy=multi-user.target`), and journald log capture.

### Blue/green deploy

`scripts/deploy-bluegreen.sh --blue-green` restarts the prod Engine on the code currently on disk with no window where the Client cannot reach an Engine. Run it as root after a `git pull`, a dependency change, an `.env.bridge` change or a drop-in change. It fetches no code. Without `--blue-green` it prints its usage and exits 2.

| Option | Default | Meaning |
|---|---|---|
| `--timeout <s>` | 300 | How long the new instance has to answer `/api/health` with 200. It is polled every 2 s, which stays inside the Engine's `/api/` rate limit; a 429 counts as not ready, and a unit that turns `failed` or `inactive` ends the wait at once |
| `--warmup <s>` | 0 | Extra wait after the first 200, followed by one more check that must also answer 200. Readiness does not wait for the random-cache build (section 4), so this is the control for letting it finish |
| `--drain <s>` | 30 | Wait between the switch and stopping the old instance. The Client's longest Engine request timeout is 20 s (`/api/video/refresh`, `/api/translate`), so a request the old instance took before the switch finishes inside it |
| `--dry-run` | — | Prints the active and target ports, the updater state, the Client preflight result and every planned action. It needs no root, takes no lock and changes nothing |

A run, in order:
1. Take the deploy lock `engine/server/db/engine-deploy.lock` (non-blocking `flock`).
2. Refuse while `peertube-updater.service` is active or activating, or while the Client unit exists without `--engine-url http://127.0.0.1:7079`.
3. Read the active port from the upstream snippet and pick the other port of the pair as the target.
4. Stop a leftover target instance from an interrupted deploy, so the target always runs freshly started code, and refuse if anything else still answers on the target port.
5. Start `peertube-engine@<target>` and wait for readiness, then the warm-up.
6. Back the snippet up to `/etc/nginx/peertube-engine-upstream.conf.bak`, write the snippet naming the target (temp file plus rename, mode 0644), run `nginx -t` and reload nginx.
7. Check `http://127.0.0.1:7079/api/health`: up to 10 tries, 1 s apart, until it answers 200 with the response header `X-Engine-Upstream: 127.0.0.1:<target>`.
8. Wait the drain, stop the old instance, enable the new one and disable the old one.
9. Delete the old instance's `random-cache.tmp.<pid>.db` and its `-journal`, if a stop during a cache build left them.

A refusal exits 1 and leaves everything as it was. Any failure before the check in step 7 passes rolls back and exits 1, with the old instance still serving:
- a failed start, readiness or warm-up stops the new instance, and the snippet and nginx are never touched;
- a failed snippet write, `nginx -t`, reload or step 7 check restores the snippet from `.bak`, runs `nginx -t`, reloads nginx and stops the new instance.

After step 7 passes, traffic is on the new instance and nothing is undone: a failure in steps 8–9 logs `post_switch_failure`, the run carries on and exits 1 with `done result=degraded`. A step of the rollback itself that fails logs `ROLLBACK FAILED` with the snippet and both instances' states, and exits 1 (see Triage). `SIGINT` and `SIGTERM` roll back the same way before the switch, and exit 1 without rollback after it. The lock is held on an open file descriptor, so it is released on every exit, `SIGKILL` included; the lock file itself stays.

Every log line has the form `deploy_id=<UTC timestamp>-<pid> event=<name> key=value…` and goes to stdout and to journald under the tag `peertube-engine-deploy`. The events include `start` (`old_port`, `new_port`), `ready` (`waited_s`), `switched` (`switch_time`), `post_switch_check` (status, upstream, `waited_s`), `old_stopped`, `rollback` (`phase`, `step`, `reason`) and `done`.

Both instances run from the target's start to the old instance's stop, so plan for about twice the Engine's memory and extra CPU during a deploy, while the new instance loads its index and builds its random cache.

`scripts/install-service.sh --mode prod` passes `--force` by default, and `--force` restarts the active instance in place: the Engine is down while it loads. Without `--force` the installer leaves a healthy active instance running. The installer never changes the active port.

### Moving a host from `peertube-engine.service`

The first prod install on a host that runs the single `peertube-engine.service` migrates it:
1. `sudo bash scripts/install-service.sh --mode prod` stops, disables and removes `peertube-engine.service`, then starts `peertube-engine@7070`, so the Engine is down once while that instance loads. It writes the upstream snippet and the listener (section 6), rewrites the Client unit with `--engine-url http://127.0.0.1:7079` and restarts the Client, and rewrites the updater unit and its sudoers rule. Running the Engine installer alone leaves the Client and the updater on the old unit; re-run the Client and updater installers for prod as well, or the deploy refuses and the updater stops a unit that no longer exists.
2. Drop-ins under `/etc/systemd/system/peertube-engine.service.d/` do not apply to the template, and the installer only warns about them. Move them to `/etc/systemd/system/peertube-engine@.service.d/`, then run a deploy.

### The updater timer

Enabled by `--with-updater-timer`. Weekly, it crawls to a staging database, builds embeddings, merges to prod, recomputes popularity, rebuilds the ANN index, refreshes the Trending ranks and refreshes the similarity cache. It **stops the Engine** only from the merge through the ANN rebuild and starts it again before the trending and similarity stages, also when an earlier stage fails. In prod that is the active instance, the `peertube-engine@<port>` the upstream snippet names when the updater reaches its stop, and it starts the same instance it stopped; in dev it is `peertube-engine-dev`. That is why the installer adds a narrow sudoers rule: in prod exactly `systemctl stop` and `systemctl start` on `peertube-engine@7070` and `peertube-engine@7071`, in dev only `stop|start` on the dev unit.

The updater and a deploy never overlap. Before the stop, the prod updater takes the deploy lock `engine/server/db/engine-deploy.lock`, waiting up to 30 minutes for a running deploy or install, and holds it until the Engine is started again; a deploy refuses to start while the updater service is active or activating. For how the worker reads the snippet and holds the lock, see `engine/server/db/jobs/docs/UPDATER_WORKER.md`.

The trending stage runs with the Engine up: `fetch-trending.py` asks every catalogue host not on the denylist for its own trending list over HTTPS, then rewrites `trending_ranks` in the served `whitelist.db` in one write transaction. While it holds the write lock, Engine writes and, at commit, reads wait on it, and a wait past SQLite's 5 s busy timeout fails that request; the job logs the transaction's length as `transaction=<ms>`. `trending_ranks` starts empty, so on a new host the Trending feed and the mix's popular layer stay empty until the first updater run or a by-hand fill; for the command see "First fill" in `engine/server/db/jobs/docs/UPDATER_WORKER.md`.

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

### Translate worker

`engine/server/db/jobs/translate-worker.py run` is a separate long-running GPU process that turns queued translate jobs into English Whisper cues in `subtitles.db`, one job at a time. `/api/translate` serves those cues for any video the worker finished, the same way it serves an instance's own English track. Jobs are queued from the command line with `enqueue`. For the job lifecycle, the bounds, the pipeline and the log lines, see `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`. It needs the dependencies from section 0, "Translate worker dependencies".

The installers and uninstallers leave this unit alone: write it by hand as `/etc/systemd/system/peertube-translate-worker.service`, and remove it by hand when uninstalling.
```ini
[Unit]
Description=PeerTube Browser translate worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<engine user>
WorkingDirectory=<project>
Environment=PYTHONUNBUFFERED=1
Environment=CUDA_VISIBLE_DEVICES=GPU-<RTX 3070 UUID>
Environment=HOME=/home/<engine user>
Environment=HF_HOME=/home/<engine user>/.cache/huggingface
EnvironmentFile=-<project>/.env.bridge
ExecStart=<project>/venv/bin/python3 engine/server/db/jobs/translate-worker.py run
Restart=on-failure
RestartPreventExitStatus=6
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now peertube-translate-worker
```

- `User=` is the Engine's user, so the worker and the Engines can both write `subtitles.db` and its `-wal`/`-shm` files.
- `CUDA_VISIBLE_DEVICES` pins the worker to the RTX 3070; the display stays on that card. Take the UUID from `nvidia-smi -L`. A UUID is used rather than an index because CUDA can number the cards differently from `nvidia-smi`.
- `HOME` and `HF_HOME` name the cache the `medium` model was downloaded into (section 0).
- `.env.bridge` is read because the worker imports `server_config`, which checks the Engine's variables (see Triage).
- `TimeoutStopSec=120` covers the stop path: SIGTERM lets the current fetch, Whisper chunk or `whitelist.db` lookup (up to its 30 s busy wait) finish, puts the job back on the queue without counting a claim, waits up to 15 s for the download thread and up to 5 s for the heartbeat thread. A stop that runs past it is a SIGKILL, which leaves the job `running`; the next start requeues it, counting that claim.
- `RestartPreventExitStatus=6` keeps systemd from restarting a worker that found another one holding the lock.

`run` flags; the top-level `--whitelist-db` and `--subtitles-db` (default the files in `engine/server/db/`) go before the subcommand:

| Flag | Default | Meaning |
|---|---|---|
| `--lock <path>` | `engine/server/db/translate-worker.lock` | `flock` file; one worker per lock. A second `run` logs `another worker holds <lock>` and exits 6 without opening `subtitles.db` |
| `--log <path>` | `engine/server/db/translate-worker.log` | Log file, written beside stdout (the journal) |
| `--max-duration <s>` | 3600 (`SUBTITLE_MAX_DURATION`) | Longest video accepted |
| `--max-bytes <n>` | 1 GiB (`SUBTITLE_MAX_BYTES`) | Largest media download accepted |
| `--max-chunk-seconds <s>` | 30 (`SUBTITLE_MAX_CHUNK_SECONDS`) | Longest audio chunk handed to Whisper |

`run` exits 0 after a stop, 1 when ffmpeg is missing and 6 when the lock is held.

Queue a video as the service user, with the `id` or `uuid` and the host as the catalogue has them:
```bash
sudo -u <engine user> ./venv/bin/python3 engine/server/db/jobs/translate-worker.py enqueue --id <id or uuid> --host <instance host>
```
It resolves the video in `whitelist.db` as `/internal/translate` does and queues it under the catalogue's canonical `video_id` and host. `--cap` (default 50, `SUBTITLE_QUEUE_CAP`) is the most `queued` jobs at once, and `--max-duration` (default 3600) is checked against the stored duration, which passes when unknown. It prints one line and exits with its code:

| Line | Exit | Meaning |
|---|---|---|
| `queued video_id=… host=…` | 0 | A new job |
| `already present: <state> video_id=… host=…` | 3 | The key exists in any state (`queued`, `running`, `ready`, `already_english`, `failed`); nothing written |
| `refused: queue cap N` | 4 | N jobs are already `queued` |
| `refused: not in whitelist`, `host denied`, `duration Ns over Ms` or `invalid id or host` | 5 | Refused before the queue |
| `error: whitelist.db: …` or `error: subtitles.db: …` | 1 | A SQLite error, such as a lock held past 30 s |

A `failed` key stays failed, and `enqueue` answers it `already present: failed`. To try it again, delete the row as the service user, then enqueue it again:
```bash
sqlite3 engine/server/db/subtitles.db "DELETE FROM subtitles WHERE video_id = '<video_id>' AND instance_domain = '<host>' AND target_language = 'en' AND state = 'failed';"
```

Day to day:
```bash
systemctl status peertube-translate-worker
journalctl -u peertube-translate-worker -f            # [translate-worker] lines; also in engine/server/db/translate-worker.log
sqlite3 -readonly engine/server/db/subtitles.db "SELECT (CAST(strftime('%s','now') AS INTEGER) * 1000 - beat_at) / 1000 AS age_s, pid FROM translate_worker_heartbeat;"    # under 10 s while the worker serves
sqlite3 -readonly engine/server/db/subtitles.db "SELECT state, source, COUNT(*) FROM subtitles GROUP BY state, source;"
sqlite3 -readonly engine/server/db/subtitles.db "SELECT video_id, instance_domain, error FROM subtitles WHERE state = 'failed' ORDER BY finished_at DESC LIMIT 20;"
```

### Triage

| Symptom | Likely cause | Action |
|---|---|---|
| Installer exits `Missing python interpreter in venv` | pixi-only setup, no `venv/` | Prerequisite above |
| Unit `activating` then `failed`, journal shows `ModuleNotFoundError` | `venv` symlink points at a rebuilt or removed pixi env | Re-point the symlink, or install deps into a real venv |
| Engine `active` but `/api/health` refuses connections for minutes | Normal: ANN index load on a large dataset | Wait; confirm with `journalctl -u 'peertube-engine@*' -f`. A deploy waits for this up to `--timeout` |
| Which prod Engine instance is serving? | — | `cat /etc/nginx/peertube-engine-upstream.conf`: its one `server` line names the active port |
| Browsing works, likes fail, Engine logs `bridge.auth` | `.env.bridge` missing or unreadable by the service user | Section 3b; the `-` prefix makes systemd ignore a missing file |
| Client unit `failed` or restarting in a loop, journal shows `TRUSTED_PROXIES entry is not an IP address or CIDR range` | Malformed `TRUSTED_PROXIES` entry | Fix the entry the journal names; syntax in section 6 |
| `502` from the Client backend on profile routes or likes | Engine 401/503 on `/internal/*` — token mismatch between the two units. The body names only the failing call; the Engine's status and error are in `journalctl -u peertube-client`, in the ERROR `engine.call` or `engine.bridge` record's `context.error` | Confirm both read the same `.env.bridge` |
| `500` from the Engine with `Recommendations request failed` or `Event ingest failed` | An unexpected exception in the recommendations or ingest handler; the body is fixed text | `journalctl -u 'peertube-engine@*'`; the JSON log record's `traceback` key holds the cause |
| The site answers nginx's HTML `502 Bad Gateway` page on API routes; the Client logs `engine.proxy` INFO records with `status=502`, and likes fail with `engine bridge HTTP 502` | No Engine answers behind `127.0.0.1:7079`: the active instance is stopped or failed, or the snippet names an instance that is not running. The Client relays nginx's 502 as it is (`client/README.md`) | `cat /etc/nginx/peertube-engine-upstream.conf` and `systemctl status 'peertube-engine@*'`; start the instance the snippet names |
| `debug=1` answers `403 Debug mode is disabled` | The Engine runs without `RECOMMENDATIONS_DEBUG` | Section 7 |
| Dev page's API calls blocked by CORS in the browser console | The Client backend does not list the page's exact origin | Set `CLIENT_CORS_ORIGINS` on the Client backend; section 6 "Local alternative" |
| Nothing on port 80 | nginx serves the static client; the units only bind loopback | Section 6 |
| Updater ran and the feed went stale or empty | Updater rebuilt the dataset with its own flags | `journalctl -u peertube-updater`; consider disabling the timer |
| Updater exits non-zero, journal shows `Similarity gate failed: <reason>` | The shadow cache failed the pre-swap gate. The active cache is untouched and the Engine is serving. A denylist `block` without `--purge-now` during the build is one cause: the shadow loses that host's sources, so it holds fewer than the active cache | Read the reason and the `similarity gate result=fail` line's counts in `journalctl -u peertube-updater`; for a denylist block, the next run's post-merge prune clears it |
| Engine journal shows `[similar-cache] reopen failed ... reason=...` | The file at `similarity-cache.db` is not a valid cache, or is missing; a cache in the older layout (with a `similarity_items` table) counts as not valid. The Engine keeps serving from its old handle, stores nothing, and retries on each cache access | Put a valid cache in place, for example by restoring `similarity-cache.prev.db` (see "The updater timer"), or convert an older-layout file with `migrate-similarity-cache.py` (see `DATA_BUILD.md`, step 5) |
| Engine instance `activating` then `failed` and restart-looping, last journal line `<path> holds the legacy similarity cache layout. Convert it with migrate-similarity-cache.py ...`; `precompute-similar-ann.py`, and so the updater's similarity stage, exits with the same message | `similarity-cache.db` is still in the older layout. It is converted once, not on start | Stop the Engine instances, run `migrate-similarity-cache.py` and move the new file into place as `DATA_BUILD.md` step 5 shows, then start the instance the snippet names |
| Dev and prod fighting over ports | Both contours installed | `systemctl list-units 'peertube-*'`; dev uses 7171/7172, prod 7070, 7071, 7072 and 7079 |
| Every video page shows its metadata but no category, language or tags; the Client logs `engine.proxy` 502 on `/api/video`; the Engine journal shows `sqlite3.OperationalError: no such column: v.language` | `whitelist.db` was not migrated before the Engine restarted. The Engine drops the connection, and the page falls back to reading the source instance directly | Run `migrate-whitelist.py` on the Engine's `whitelist.db` (see `DATA_BUILD.md`), then `sudo bash scripts/deploy-bluegreen.sh --blue-green` |
| Engine instance `activating` then `failed` and restart-looping, last journal line `Index ids come from <source or <unset>> but readers resolve video_embeddings.ann_id. Rebuild the index with build-ann-index.py.`; `precompute-similar-ann.py`, and so the updater's similarity stage, exits with the same message. A deploy rolls back at readiness | The ANN index was built before the `ann_id` cutover (its sidecar records `video_embeddings.rowid` or no `id_source`) | Stop the Engine instances, run `build-ann-index.py` with the served paths as in section 1, then start the instance the snippet names |
| `sync-whitelist.py` exits with `Schema mismatch for main.video_embeddings (missing columns: ann_id)` and a pointer to `migrate-whitelist.py`; `build-video-embeddings.py`, `build-ann-index.py` or the updater's merge exits with `main.video_embeddings has no ann_id column` or `stage.video_embeddings has no ann_id column` | The named `video_embeddings` predates the one-time `ann_id` rebuild. Nothing was written. Under the updater, the embeddings stage runs on the staging DB, so its `main.` is staging; a staging DB from before the rebuild comes from `--resume-staging` | For `whitelist.db`, run the migration as in section 1. For staging, re-run the updater without `--resume-staging` |
| Sync, merge, `build-video-embeddings.py` or `migrate-whitelist.py` exits with `video_embeddings ann_id collision: another (video_id, instance_domain) holds this ann_id`, `UNIQUE constraint failed: video_embeddings.ann_id` or `CHECK constraint failed` | Two video keys derive the same `ann_id`, or one derives 0. Sync, the merge and the migration roll back whole; `build-video-embeddings.py` keeps the batches it committed before the failing one | Recovery is manual: find the two keys and decide which to keep (`docs/project/adr/0006-derived-ann-ids.md`) |
| Engine instance `activating` then `failed` and restart-looping, last journal line `INTERACTION_RAW_RETENTION_DAYS must be a positive integer, got '…'` | The value is not a positive integer (`abc`, `0`, `-3`, `7.5`, empty). The check runs when `server_config` is imported, so the DB jobs, the updater worker and the translate worker exit the same way when the value is in their environment, and with the value in `.env.bridge` the Engine the updater restarts fails the same way. A deploy with the bad value rolls back at readiness | Fix or remove the value in the unit, a drop-in or `.env.bridge`, then `sudo systemctl restart peertube-engine@<active port>` if the active instance is down, or deploy if it is serving |
| Engine instance `activating` then `failed` and restart-looping, last journal line `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES must be a non-negative integer, got '…'` | The value is not a non-negative integer (`abc`, `-3`, `7.5`). The check runs when `server_config` is imported, so the DB jobs, `precompute-random-rowids.py`, the updater worker and the translate worker exit the same way when the value is in their environment. A deploy with the bad value rolls back at readiness | Fix or remove the value in the unit, a drop-in or `.env.bridge`, then `sudo systemctl restart peertube-engine@<active port>` if the active instance is down, or deploy if it is serving |
| Deploy exits 1 with `refused reason=lock_held` | Another deploy, a prod Engine install, or the updater's Engine stop/start window holds `engine/server/db/engine-deploy.lock` | Wait and re-run; `journalctl -t peertube-engine-deploy` and `systemctl status peertube-updater` show the holder. The lock file left on disk is not a held lock |
| Deploy exits 1 with `refused reason=updater_running` | `peertube-updater.service` is running; it stops and starts the Engine itself | Wait for it to finish (`journalctl -u peertube-updater -f`), then deploy |
| Deploy exits 1 with `refused reason=client_not_on_listener` | `/etc/systemd/system/peertube-client.service` does not run with `--engine-url http://127.0.0.1:7079`, so a deploy would leave the Client on a stopped port | `sudo bash client/install-client-service.sh --mode prod --force`, or the central prod install |
| Deploy exits 1 with `refused reason=port_in_use_by_foreign_process port=<p>` | Something other than the target instance answers on the target port, such as `server.py --dev` (binds 7071) or a manual Engine | Stop that process; on a prod host run no manual Engine on 7070 or 7071 (section 4) |
| Deploy exits 1 with `refused reason=snippet_invalid`; the Engine installer exits `Invalid upstream snippet`; the updater fails with `upstream snippet … has N server lines` or `names neither 127.0.0.1:7070 nor 127.0.0.1:7071` or `cannot read upstream snippet` | `/etc/nginx/peertube-engine-upstream.conf` is missing (deploy and updater only), was edited, has CRLF line endings, names two servers or another host or port, or is not readable by the updater's user. The installer refuses an invalid snippet and does not replace it | Rewrite it naming the port of the instance that is running: `printf 'upstream peertube_engine {\n    server 127.0.0.1:7070;\n}\n' \| sudo tee /etc/nginx/peertube-engine-upstream.conf`, `sudo chmod 0644` it, then `sudo nginx -t && sudo systemctl reload nginx` |
| Deploy log `rollback phase=pre-switch step=readiness reason=readiness_timeout` (or `unit_failed`, `unit_inactive`), exit 1 | The new instance did not answer `/api/health` 200 within `--timeout`: a slow index load, or the code or environment on disk fails at startup | The old instance is still serving and the snippet is unchanged. Read `journalctl -u peertube-engine@<new_port>`; fix the startup error, or raise `--timeout` for a slow load |
| Deploy log `rollback phase=switching step=nginx_test`, `nginx_reload` or `post_switch_check`, exit 1 | `nginx -t` failed (often an unrelated broken config), the reload failed, or `127.0.0.1:7079` did not answer 200 from the target within 10 s | The previous snippet is restored, nginx reloaded and the new instance stopped; the old instance is serving. Run `sudo nginx -t`; for `post_switch_check`, check the listener file and the `conf.d` include (section 6) |
| Deploy log `rollback_failed msg="ROLLBACK FAILED" at=<step>`, exit 1 | A step of the rollback itself failed (`restore_snippet`, `restore_nginx_test`, `restore_nginx_reload`, `stop_target`) | The line records `snippet=`, `old_state=` and `new_state=`. Make the snippet name an instance that is running and answers `/api/health` (`/etc/nginx/peertube-engine-upstream.conf.bak` holds the previous one), run `sudo nginx -t && sudo systemctl reload nginx`, then stop the instance the snippet does not name |
| Deploy log `post_switch_failure step=<step>`, then `done result=degraded`, exit 1 | Traffic is already on the new instance; stopping the old one, `enable`, `disable` or the cache-file cleanup failed | Nothing to roll back. Finish the step by hand: `sudo systemctl stop peertube-engine@<old>`, `sudo systemctl enable peertube-engine@<new>`, `sudo systemctl disable peertube-engine@<old>` |
| Both `peertube-engine@7070` and `@7071` running outside a deploy | A deploy was killed after its switch, before stopping the old instance | Stop and disable the instance the snippet does not name, or run a deploy, which restarts that one as its target |
| Updater fails with `deploy lock … still held after 1800s; Engine not stopped` | A deploy or prod install held the lock for 30 minutes | The run stopped before the merge and the Engine kept serving. Find the holder in `journalctl -t peertube-engine-deploy`, then re-run the updater |
| `/about`, `/about/` or `/about.html` answers 404 | The site file lacks the About locations, or the document root has no `dev-pages/about.html` or `dev-pages/about.template.html` | Merge the About locations from section 6 into the site file, or run `scripts/sync.sh` |
| `translate_worker_heartbeat` is empty, or its `beat_at` is more than a few beats old | The worker is not running, or its main loop has made no progress for 600 s (a hung fetch or GPU call), after which the heartbeat thread stops beating on purpose | `systemctl status peertube-translate-worker` and its journal; a stalled worker is restarted with `sudo systemctl restart peertube-translate-worker` |
| `translate-worker.py run` logs `another worker holds <lock>` and exits 6 | Another worker, usually the service, holds `engine/server/db/translate-worker.lock`. Nothing was written | Run the worker only as the service; the lock file left on disk is not a held lock |
| Jobs stay `queued` | No worker serves the queue (heartbeat missing or stale), one long job is running ahead of them, or `whitelist.db` is locked or missing and the head job keeps being requeued (the journal repeats `whitelist.db unavailable, requeued`; see that row) | Check the heartbeat and the state counts (section 2, "Translate worker", "Day to day"); start or restart the unit |
| Jobs end `failed` with an `out of memory` error text | The RTX 3070 had too little free VRAM for Whisper `medium` next to the desktop. The worker dropped the model and keeps serving later jobs | `nvidia-smi` for what else holds VRAM; re-queue the key as section 2 shows once it is free |
| Jobs end `failed` with `ModuleNotFoundError: No module named 'faster_whisper'` | faster-whisper is not installed in the interpreter the unit runs | Section 0, "Translate worker dependencies", then re-queue the keys |
| Worker unit `failed` or restarting, journal shows `ffmpeg not found on PATH` | ffmpeg is not installed | `sudo apt install -y ffmpeg` |
| A job ends `failed` with `worker stopped while running twice` | The worker died while running that job twice in a row (a crash, or a stop past `TimeoutStopSec`); the second time it is failed rather than retried | Read the journal around the job's `claimed` lines, then re-queue the key as section 2 shows |
| A job stays `queued` or flips between `queued` and `running`, and the journal repeats `[translate-worker] whitelist.db unavailable, requeued video_id=… host=…: database is locked` (or `unable to open database file`) | The updater's merge holds `whitelist.db` past the 30 s busy timeout, or a restore has removed it. The worker puts the job back on the queue without counting a claim and claims it again after a 30 s back-off (`engine/server/db/jobs/docs/TRANSLATE_WORKER.md`). A repeating `unable to open` with no restore running means the `--whitelist-db` path or its permissions are wrong, and every later job waits behind this one | Nothing for the job: it runs once the merge or restore ends. For a wrong path or permissions, fix the unit's `--whitelist-db` or the file's mode, then `sudo systemctl restart peertube-translate-worker` |
| `enqueue` prints `error: whitelist.db: database is locked` and exits 1 | The updater's merge held `whitelist.db` past the 30 s busy timeout. Nothing was queued | Re-run `enqueue` after the updater run ends |

### Follow an About visit

nginx writes every request for `/about`, `/about/` and `/about.html` to `/var/log/nginx/peertube-browser.pages.access.log` in the `peertube_browser_pages` format (section 6), HEAD requests and 404s included. Its fields are space-separated in a fixed order and the visitor-supplied `x_request_id` and `ua` come last, so filter by position: `$5` is the method, `$6` the status, `$8` the request id. A substring grep for `status=200` also matches a user agent that contains that text. List the successful views:
```bash
sudo awk '$5 == "method=GET" && $6 == "status=200"' /var/log/nginx/peertube-browser.pages.access.log
```

The same visit's line in the main access log carries the same request id: `sudo grep "request_id=$id" /var/log/nginx/peertube-browser.access.log`, with `id` set as below.

The page's own API calls are new requests with their own ids, so a visit links to the Client backend only by address and time: the commands below print the Client `request.start` records from the visit's `ip` in the 60 s after it. Widen the `+ 60` for a slow visitor; visitors behind one shared address are not told apart. A view of the About page itself sends one such request, its `POST /api/analytics/event` page view, plus one per tracked link the visitor clicks (see "Count About analytics events").
```bash
id=<request_id of the visit's pages line>
read -r ts ip < <(sudo awk -v id="$id" '$8 == "request_id=" id { print substr($2, 4), substr($4, 4) }' /var/log/nginx/peertube-browser.pages.access.log)
from="$(date -u -d "@${ts%.*}" +%Y-%m-%dT%H:%M:%S).${ts#*.}Z"
to="$(date -u -d "@$(( ${ts%.*} + 60 ))" +%Y-%m-%dT%H:%M:%S).${ts#*.}Z"
journalctl -u peertube-client.service -o cat | jq -cR --arg ip "$ip" --arg from "$from" --arg to "$to" 'fromjson? | select(.event == "request.start" and .context.ip == $ip and .ts >= $from and .ts <= $to)'
# LOG_FORMAT=text: field 6 of a request.start line is its ip
journalctl -u peertube-client.service -o cat | awk -v ip="$ip" -v from="$from" -v to="$to" '$3 == "request.start" && $6 == "ip=" ip && $1 >= from && $1 <= to'
```
Each printed record's `request_id` leads to the rest of that request (see "Follow one request").

Caveats:
- No app record carries the visit's request id, so the match is by address and time only and is probabilistic: visitors behind NAT or another shared address are indistinguishable, and another visitor's requests from that address fall in the same window.
- The Client's `ip` is resolved through `X-Forwarded-For` and `TRUSTED_PROXIES` (section 6), so it equals the pages log's `ip` (nginx's `$remote_addr`) only when nginx is the sole proxy. Behind a CDN or a load balancer, `$remote_addr` is that layer's address and the match finds every visitor through it.
- The pages log's `time=` field is server-local time with an offset, while the apps' `ts` is UTC. The `from` and `to` lines therefore build the window from `ts=` (`$msec`, epoch seconds) in UTC.
- The `LOG_FORMAT=text` command matches by field position over unquoted values, `ip` among them, and `user_agent` is written unquoted after it, so it is looser than the JSON command, which compares named keys.
- Bots and crawlers appear in the pages log, and the `ua` field is the only way to filter them out. The page's own beacon counts only views that ran its JavaScript, which most crawlers do not; count those under "Count About analytics events" (delivered by `docs/project/issues/archive/18-about-outbound-click-tracking.md`).

### Count About analytics events

The About page's script `client/frontend/src/about-analytics.ts` sends one `page_view` event per load and one `outbound_click` event per click on a link carrying `data-track-id`, to `POST /api/analytics/event` on the Client backend. Each accepted event is one row in the `analytics_events` table of the Client backend's `users.db`: `type`, `track_id` and `href` (both NULL for a page view), `page_path` as the browser sent it (`/about`, `/about/` and `/about.html` stay separate), `created_at` in server epoch milliseconds, and the request's `user_agent` and `referer` (NULL when absent). Nothing derived from the client address is stored. For the request body and its validation, see `client/README.md`; for what an About override needs to send events, see `client/frontend/README.md`.

Open the database read-only, so a query never takes a write lock from the running Client backend:
```bash
sqlite3 -readonly <project>/client/backend/db/users.db
```

Total outbound clicks per `track_id`:
```sql
SELECT track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' GROUP BY track_id ORDER BY clicks DESC;
```

Daily outbound clicks per `track_id`, by UTC day:
```sql
SELECT date(created_at / 1000, 'unixepoch') AS day, track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' GROUP BY day, track_id ORDER BY day, track_id;
```

Total and daily page views, then the same per `page_path`:
```sql
SELECT COUNT(*) AS views FROM analytics_events WHERE type = 'page_view';
SELECT date(created_at / 1000, 'unixepoch') AS day, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY day ORDER BY day;
SELECT page_path, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY page_path ORDER BY views DESC;
SELECT date(created_at / 1000, 'unixepoch') AS day, page_path, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY day, page_path ORDER BY day, page_path;
```

To leave out obvious bots, add a `user_agent` filter to the `WHERE` clause of any query above; SQLite's `LIKE` ignores ASCII case. Daily clicks per `track_id` without them:
```sql
SELECT date(created_at / 1000, 'unixepoch') AS day, track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' AND user_agent IS NOT NULL AND user_agent NOT LIKE '%bot%' AND user_agent NOT LIKE '%crawl%' AND user_agent NOT LIKE '%spider%' AND user_agent NOT LIKE '%headless%' AND user_agent NOT LIKE 'curl/%' GROUP BY day, track_id ORDER BY day, track_id;
```

Caveats:
- The route needs no key, so anyone can post events. One client address gets 90 requests per 60 s on this route, the Client backend's shared limit, so forged counts grow by at most that much per address.
- Nothing prunes `analytics_events`; every row is kept.
- The `user_agent` filter is a heuristic: a client that sends a browser user agent passes it, and the patterns are examples to extend.
- `referer` is often only the origin, or absent, because browsers reduce it by referrer policy.
- Only a click that fires the `click` event is counted, so a link opened with the middle button or from the context menu is not.
- A tracked link whose resolved address is not `http` or `https`, such as a `mailto:` link, is answered 400 and not stored.
- The rate limit keys on the client address resolved through `TRUSTED_PROXIES` (section 6, `docs/project/adr/0002-trusted-proxy-client-address.md`). When visitors share one address, or a missing `X-Forwarded-For` line or an unlisted CDN makes them appear to, they share one bucket, and events past it are answered 429 and silently not counted.
- Under `npm run dev` the beacon goes to a Client backend on another origin, so it needs `CLIENT_CORS_ORIGINS` (section 6, "Local alternative") and can still be dropped by the browser; dev counts are not reliable (`docs/project/adr/0004-cors-opt-in-by-origin.md`).
- Every request thread of the Client backend shares one `users.db` connection with no lock around its transactions, so an event stored while another request writes to `users.db` can be committed or rolled back with that request's transaction.

### Follow one request

Public nginx sets `X-Request-ID` to its own `$request_id` on every proxied request (section 6), the Client backend sends that id on every Engine call it makes for the request, and both services put it on every log record of the request as `request_id`. Take the id from any one line, then find the rest:
```bash
id=<request id>
sudo grep "request_id=$id" /var/log/nginx/peertube-browser.access.log
journalctl -u peertube-client.service -o cat | jq -cR --arg id "$id" 'fromjson? | select(.request_id == $id)'
journalctl -u 'peertube-engine@*' -o cat | jq -cR --arg id "$id" 'fromjson? | select(.request_id == $id)'
```
With `LOG_FORMAT=text`, grep the journal instead: `journalctl -u peertube-client.service -o cat | grep "request_id=$id"`, and the same for `'peertube-engine@*'`.

What each log is for:
- The nginx line is the network view: client address, status, bytes sent, the upstream address and nginx's request time.
- The pages log, `/var/log/nginx/peertube-browser.pages.access.log`, has one line per About request: the `page=about` marker, the millisecond epoch timestamp, local time, client address, method, status, request time, request id, URI with query, the incoming `X-Request-ID` (`-` when absent) and the user agent. Its `request_id` joins it to the request's line in the main access log (see "Follow an About visit").
- Each service's records are its internal processing: `request.start` (`ip`, `method`, `url`, and `user_agent` when the request has one) first, then the work records, then `request.end` with the `status` sent (`-` if none was sent) and `duration_ms`. Read them in order by `ts`. The order holds within one request in one service; records of different requests interleave.

Caveats:
- One Client request can produce several Engine `request.start` … `request.end` pairs under the same id: a retried proxied read, the resolve, metadata and centroids calls, and the bridge publish each reach the Engine as their own request.
- A service accepts an incoming `X-Request-ID` only when the whole value matches `[A-Za-z0-9._-]{1,64}`. A missing or malformed header makes it generate its own 32-hex id, which then differs from the nginx line's id; a rejected value is never logged as `request_id`.
- The 7079 listener's own access log does not carry the id.

Centralized installer (source of truth):
```bash
# Prod contour (--force and the updater timer are the prod defaults; --force restarts the active Engine instance in place)
sudo bash scripts/install-service.sh --mode prod --force --with-updater-timer

# Dev contour (separate unit names/ports, safe for local parallel run with prod)
sudo bash scripts/install-service.sh --mode dev --force --uninstall
```

Service-specific installers (each supports its own `--mode prod|dev`):
```bash
sudo bash engine/install-engine-service.sh --mode prod
sudo bash client/install-client-service.sh --mode prod --force    # --engine-url defaults to http://127.0.0.1:7079
sudo bash client/install-client-service.sh --mode dev --force --engine-url http://127.0.0.1:7171
```

The prod Engine installer:
- refuses `--host`, `--port` and any `--service-name` other than `peertube-engine`, and `scripts/install-service.sh` refuses `--engine-port` and `--engine-host` for prod: the instances always bind `127.0.0.1:7070` and `127.0.0.1:7071`;
- needs root, `nginx` with an `http` block that includes `/etc/nginx/conf.d/*.conf`, `flock` and `curl`;
- takes the deploy lock, so it refuses while a deploy runs;
- reads the upstream snippet before writing anything: a missing snippet is written naming 7070, a valid one keeps its port, and an invalid one stops the install with nothing changed;
- brings up the instance the snippet names, stops and disables the other one, and enables the active one;
- does not reload nginx when `nginx -t` fails, and removes a listener file it created in that run.

Uninstall (symmetric):
```bash
# Centralized contour uninstall (--purge-updater-state or --keep-updater-state is required)
sudo bash scripts/uninstall-service.sh --mode dev --keep-updater-state
sudo bash scripts/uninstall-service.sh --mode prod --purge-updater-state

# Service-specific uninstallers
sudo bash engine/uninstall-engine-service.sh --mode prod
sudo bash engine/uninstall-engine-service.sh --mode dev
sudo bash client/uninstall-client-service.sh --mode dev
```

The prod Engine uninstaller stops and disables both instances and a remaining `peertube-engine.service`, removes the template, that legacy unit, the listener, the snippet and its `.bak`, then runs `nginx -t` and reloads nginx; the public site keeps serving. It leaves the deploy lock file and any drop-ins under `peertube-engine@.service.d/` in place.

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

`about` is the exception: it is built under `dist/dev-pages/`, as `about.html` when the local override `client/frontend/dev-pages/about.html` exists and as `about.template.html` otherwise, and never as `dist/about.html`. It is reached at `/about`, `/about/` and `/about.html` only through the About locations in section 6. Another purely informational page is added the same way, with one more exact location of the same shape.

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

On a host with the prod contour installed, 7070 and 7071 belong to the `peertube-engine@` instances: run no manual Engine there, neither this command, `server.py --dev` (it binds 7071) nor `scripts/run-services.sh`. A manual Engine on the deploy's target port makes the deploy refuse (`port_in_use_by_foreign_process`).

The retention window from section 2 is set here the same way: prefix the command with `INTERACTION_RAW_RETENTION_DAYS=7`, or put the line in `.env.bridge`.

First startup loads the FAISS index and counts embeddings, which takes a while on a
full dataset — a few hundred thousand embeddings means tens of seconds before the port
accepts connections. Health checks that poll immediately will log connection refusals
until it finishes; wait for JSON from:
```bash
until curl -sf http://127.0.0.1:7070/api/health; do sleep 5; done
```

`/api/health` answers without waiting on any random-cache build. Until the first `random cache build ok` line, and whenever no usable cache is open, the random feed is served from `whitelist.db`. A `random-cache.db` holding only the old `random_rowids` table is unusable (`random cache unusable … reason=no_table`), so the first start after the `ann_id` cutover (section 1) builds a `random_ann_ids` cache in the background, even with cache refresh off (`--dev`). Each build logs `random cache build start`, then `ok` or `failed`; a `failed` line leaves the previous cache serving, and the build is retried at the next interval. These lines are INFO records tagged for the `verbose` view only, so a log viewer filtered to `focused` hides them. A `random-cache.tmp.<pid>.db` left in `engine/server/db/` by a killed Engine is safe to delete; a deploy deletes the one its old instance leaves. During a deploy the new instance runs its startup build while the old one keeps serving, and each instance builds in its own `random-cache.tmp.<pid>.db`.

### Up-next logs and load

Up-next is the seeded similar-video request behind the video page (`/recommendations?id=&host=`, `/videos/similar`, `GET /videos/{id}/similar`); how its pool is built and drawn is in `engine/server/api/recommendations/docs/OVERVIEW.md`. Three Engine log lines trace it:
- `[similar-server] upnext_config SIMILAR_VIDEO_SEARCH_LIMIT=… SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR=…` is logged once at startup, right after `ann_nprobe_configured`, with the values of all nine up-next constants.
- `[similar-server] ann_fallback nprobe= search_limit= floor= hits= restored_nprobe=` is logged for each live ANN search the up-next fallback runs; `restored_nprobe` is the value read back from the index after the search and should equal the `ann_nprobe_configured` value.
- `[similar-server][<id>] upnext_pool initial= steps= restored_nprobe= final= tail= sampling= window= likes_rerank= returned=` is logged once per up-next request. `<id>` is the request id, the same value as the record's `request_id` (see "Follow one request" under Triage). `steps` lists each search as `nprobe/search_limit->pool`, or `none`, and `sampling` is `random` or `seeded`.

The similarity cache holds 20 candidates per seed (`--top-k 20`, see `DATA_BUILD.md`), fewer than the 48-row pool up-next needs, so nearly every up-next request runs the fallback: up to three searches, from nprobe 32 / k 5000 up to nprobe 128 / k 20000, each under the `index_lock` that home and search requests share. The Engine's 5 s request deadline bounds only SQLite statements, not FAISS, so a request whose searches overrun it fails at its next database statement with `500 Recommendations request failed`.

### Ordered feed load

The popular feed mode sorts every embedded video on stored columns for each chunk it reads (`likes` first), and recent sorts on `published_at`. The trending feed mode reads `trending_ranks` in the order of its index `idx_trending_ranks_order`, so it runs no sort and reads only ranked rows. A chunk is the page plus the request's `exclude` list plus 32 rows, so a late page, with about 500 rows in `exclude`, reads 580 or more rows per chunk, and a request reads at most 4 chunks, each under `db_lock`. Each chunk's query runs inside the 5 s request deadline; one that overruns it answers `500 Recommendations request failed`.

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

`POST /api/analytics/event` is browser-facing and needs no key, but it publishes nothing to the Engine: it stores the About page's analytics events in the `analytics_events` table of `users.db` (see "Count About analytics events" under Triage).

A request with `X-Profile-Key` publishes a `Like` only when it opens the profile's published like of the video, and an `UndoLike` only when it closes one; a request that changes nothing answers 200 and publishes nothing. The Client backend tracks published likes in the `like_generations` table of `users.db`, which it creates at startup, so there is no migration step. Event ids are derived from the actor, the video, the event type and the like generation, so a replayed event is a duplicate at the Engine's ingest and changes no counts. A request without a key always publishes, and every keyless `Like` of a video carries one fixed id, as does every keyless `UndoLike`. For the definition of a published like see `CONTEXT.md`, and for the id scheme see `docs/project/adr/0001-derived-interaction-event-ids.md`.

Per-visitor profiles are optional. `POST /api/profile` returns a key once, and the Client backend stores only its SHA-256 in `client/backend/db/users.db`. The profile routes (`/api/user-profile*`, `/api/profile/rotate`, `/api/profile/delete`, `/api/profile/blocks*`, `/api/profile/reaction`, `/api/profile/likes/import`, `/api/translate`) and the `dislike`/`undo_dislike` actions of `/api/user-action` accept the key only in the `X-Profile-Key` request header and answer anything else with 401. A key that is lost cannot be recovered. Minting is limited to 5 per hour per client address; behind a proxy, see `TRUSTED_PROXIES` in section 6 for how that address is resolved.

A profile can block channels and accounts, up to 1,000 blocks. Blocks are stored in `users.db`, so dataset builds and the updater never touch them. When a feed (`/recommendations`, `/videos/similar`) or search (`/api/v1/search/videos`) request carries `X-Profile-Key`, the Client backend removes that profile's blocked rows from the Engine's response before returning it. For a profile with blocks, it asks the Engine for twice the page and trims to one page in every feed mode, so feed pages stay full; search pages are filtered as they are and can come back short. A feed or search request with a key that does not resolve gets the same 401 as the profile routes. Without the header, reads pass through unfiltered. The Client caps a browser's feed `limit` at 48, the Engine's page size, and the Engine accepts up to 96 so the Client can over-fetch.

A profile's likes and dislikes are kept in `users.db`; a like and a dislike on one video replace each other, and a profile holds at most 1,000 dislikes. A dislike publishes no interaction event; disliking a liked video publishes the `UndoLike` that withdraws the like from the Engine's `interaction_signals`. On every dislike change the Client backend asks the Engine (`/internal/dislikes/centroids`) for up to four taste vectors of the profile's dislikes and stores them; the Engine keeps nothing. For a feed request carrying `X-Profile-Key`, the Client backend sends the Engine the profile's own likes in place of the browser's and its taste vectors, which the Engine uses to rank similar videos lower, and removes the disliked videos from the page, over-fetching as for blocks. Search is not filtered by dislikes. On keyed feed and search responses the Client backend marks each row the profile likes or dislikes with `reaction`, which the frontend shows on the card; marking alone does not over-fetch. Taste vectors are tied to the embedding model: after a re-embed with another model the Engine ignores stored ones until the profile's next dislike change.

Boundary contract (mandatory):
- Client backend talks to Engine only over HTTP (`/internal/videos/resolve`, `/internal/videos/metadata`, `/internal/dislikes/centroids`, `/internal/translate`, `/internal/events/ingest`).
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
log_format peertube_browser '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent" request_id=$request_id upstream=$upstream_addr rt=$request_time';
log_format peertube_browser_pages 'page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri=$request_uri x_request_id="$http_x_request_id" ua="$http_user_agent"';

server {
    listen 80;
    server_name _;

    root /var/www/peertube-browser;
    index index.html;
    access_log /var/log/nginx/peertube-browser.access.log peertube_browser;

    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-src https:; connect-src 'self' https:; img-src 'self' https: data:" always;

    location / {
        try_files $uri $uri/ =404;
    }

    # rat-tail: these three URLs and the two dev-pages names mirror rewriteToAbout and aboutSourcePath in client/frontend/vite.config.ts; tests/active/test_static_page_visit_logs.py compares them, and building About to dist/about.html is the upgrade if the mapping grows.
    # An access_log in a location replaces the server's, so each About location repeats the main log beside the pages log.
    location = /about {
        set $static_page about;
        access_log /var/log/nginx/peertube-browser.access.log peertube_browser;
        access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;
        try_files /dev-pages/about.html /dev-pages/about.template.html =404;
    }
    location = /about/ {
        set $static_page about;
        access_log /var/log/nginx/peertube-browser.access.log peertube_browser;
        access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;
        try_files /dev-pages/about.html /dev-pages/about.template.html =404;
    }
    location = /about.html {
        set $static_page about;
        access_log /var/log/nginx/peertube-browser.access.log peertube_browser;
        access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;
        try_files /dev-pages/about.html /dev-pages/about.template.html =404;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:7072;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
    }
    location /recommendations {
        proxy_pass http://127.0.0.1:7072;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $request_id;
    }
    location /videos/similar {
        proxy_pass http://127.0.0.1:7072;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $request_id;
    }
    location /client/ {
        proxy_pass http://127.0.0.1:7072;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $request_id;
    }
}
```

The browser enforces this header and each page's own `<meta>` CSP together, so a source the header omits is blocked whatever the page allows. `connect-src 'self' https:` lets the video page read source PeerTube instances directly (metadata fallback, `/api/v1/config`, channels, comments), and `img-src 'self' https: data:` lets pages show remote images such as avatars.

Each proxied location sets `X-Request-ID` to nginx's own `$request_id`, replacing any value the browser sent, and the `peertube_browser` access log records the same id, so the nginx line and the app records of one request share it (see "Follow one request" under Triage). The line is repeated in every location because a location that sets any `proxy_set_header` inherits none from the server level. Both `log_format` lines, `peertube_browser` and `peertube_browser_pages`, stay outside `server {}`: the file is included in nginx's `http` block, the only place `log_format` is allowed.

The three exact About locations serve `/dev-pages/about.html`, then `/dev-pages/about.template.html`, then 404, the same override-then-template choice the vite build makes (section 3). Each one sets `$static_page` and lists both `access_log` lines, because an `access_log` in a location replaces the server's: without the repeated main line, About requests would vanish from `peertube-browser.access.log`. They declare no `add_header`, so they inherit the server's `Content-Security-Policy`, which is the About page's only CSP since the template carries no `<meta>` CSP; an `add_header` in one of them would drop it. The pages log, `/var/log/nginx/peertube-browser.pages.access.log`, sits under `/var/log/nginx/` with a `.log` suffix, so the Debian/Ubuntu nginx logrotate rule for `/var/log/nginx/*.log` rotates it. A direct request for `/dev-pages/about.html` or `/dev-pages/about.template.html` goes through `location /` and writes no pages line.

On a host that already runs this site, merge the `peertube_browser_pages` line and the three About locations into the existing file rather than copying the whole block over it, which would drop the changes certbot made (see "TLS"), then run `sudo nginx -t && sudo systemctl reload nginx`.

The `X-Forwarded-For` lines are required, not cosmetic. When the TCP peer is a trusted proxy, the Client backend walks `X-Forwarded-For` from right to left, skipping hops that are themselves trusted proxies, and takes the first untrusted hop as the client address; a hop that is empty or not an IP address stops the walk at the last trusted address. From any other peer, the peer is the client address. The Client backend keys its rate limiters on that address, logs it as the `ip` of its `request.start` record, and forwards it to the Engine as `X-Client-IP`, which is what the Engine's rate limiter keys on. Omit the lines and every visitor shares one bucket, which also silently undercounts About analytics events (see "Count About analytics events" under Triage). `X-Real-IP` is never read, so the `X-Real-IP` lines above have no effect.

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
curl -I http://localhost/about            # 200, with a Content-Security-Policy header; /about/ and /about.html the same
sudo tail -n 1 /var/log/nginx/peertube-browser.pages.access.log    # page=about … method=HEAD status=200
curl -s -o /dev/null -w '%{http_code}\n' --data '{"type":"page_view","page_path":"/about","timestamp":0}' http://localhost/api/analytics/event    # 204; stores a real page_view row with a curl/ user agent
```
A 404 on `/` with a successful `nginx -t` means the document root is unreadable by
`www-data`; check with `sudo -u www-data stat /var/www/peertube-browser/index.html`. A 404 on `/about` while `/` answers means the About locations are missing from the site file, or the document root has no `dev-pages/about.html` or `dev-pages/about.template.html`.

### Engine listener on 127.0.0.1:7079 (prod)

In prod the Client backend reaches the Engine through a second, loopback-only nginx server, so a deploy can move traffic between the two Engine instances without touching the Client. The prod Engine installer writes both files; edit neither by hand, and leave the public site file above as it is, since nothing here changes it.

`/etc/nginx/peertube-engine-upstream.conf` is the upstream snippet, and the only record of which instance is active:
```nginx
upstream peertube_engine {
    server 127.0.0.1:7070;
}
```
It holds exactly one `server` line naming 7070 or 7071, with LF line endings and mode 0644, because the updater reads it as the service user. The deploy, the installer and the updater all read the active port from it, and the deploy rewrites it atomically, keeping the previous version as `peertube-engine-upstream.conf.bak`. For why the active port lives in this file, see `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md`.

`/etc/nginx/conf.d/peertube-engine-internal.conf` is the listener. It includes the snippet and has one `server` block:
- `listen 127.0.0.1:7079` and nothing else;
- `server_tokens off` and its own access log, `/var/log/nginx/peertube-engine-internal.access.log`;
- `client_max_body_size 2m`, above the Client's own 1,000,000-byte limit, so this hop never adds a 413;
- `location /` proxying every path to the upstream, passing the Client's `Host`, and adding the response header `X-Engine-Upstream` with the address nginx used, which the deploy's post-switch check reads.

Request headers pass through unchanged. The Client backend sends `X-Client-IP`, `X-Bridge-Token` and, on every Engine call it makes while serving a request, `X-Request-ID` with that request's id, and the listener passes all three to the Engine as they are. Proxy timeouts are nginx's defaults (60 s), longer than any Engine request timeout the Client sets.

The listener loads only if the `http` block of `/etc/nginx/nginx.conf` includes `/etc/nginx/conf.d/*.conf`, as the Debian and Ubuntu packages do. Check it:
```bash
cat /etc/nginx/peertube-engine-upstream.conf
curl -s -o /dev/null -D - http://127.0.0.1:7079/api/health    # 200, X-Engine-Upstream: 127.0.0.1:<active port>
```

The listener must never bind anything but `127.0.0.1`. The Engine trusts the `X-Client-IP` it receives (`docs/project/adr/0002-trusted-proxy-client-address.md`) and its `/internal/*` routes accept writes, so a reachable 7079 exposes the Engine as much as a reachable 7070.

### Firewall (ufw)

Loopback is exempt from ufw's default policy, so the Engine instances, the Client backend and the 7079 listener need no rules while they stay bound to `127.0.0.1`. **Never** open 7070, 7071, 7072 or 7079 — the Engine has no authentication and its `/internal/*` routes accept writes.

```bash
sudo ufw allow out 443/tcp     # crawler, live video metadata, caption tracks, translate worker media, whitelist sync
sudo ufw allow out 53          # DNS
sudo ufw allow in 80/tcp       # only if reachable beyond localhost
sudo ufw allow in 443/tcp
```
Outbound 443 is a runtime dependency, not just a build one: `/api/video` makes live calls to source instances per request, `/internal/translate` fetches a video's caption list and English track from that video's own instance on each cache miss (https only, no redirect off the host), the translate worker fetches each job's caption list, English track and video JSON from the video's own instance under the same rule and downloads its media from the https host the instance's JSON names, which may be object storage or a CDN (a DNS name only, no port, no redirect off that host), and the updater timer re-crawls weekly.

`/api/video` writes the refreshed metadata back to `whitelist.db` only when the source answers with a valid video object. The write shares the request's statement deadline (5 s by default, `DEFAULT_STATEMENT_TIMEOUT_SECONDS`), which also counts the time spent waiting on the source. When a slow source uses up that deadline, the page still gets the fresh values, the write can be interrupted, and the Engine logs `[video] failed to persist dynamic metadata`.

### TLS

If this is publicly reachable, terminate TLS before opening it up — the session, the
user's like history and the `X-Profile-Key` header are otherwise in clear, and anyone who
reads that header owns the profile:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx
```
`certbot --nginx` edits `/etc/nginx/sites-available/peertube-browser` in place. Copying the whole site block from "nginx (production)" over that file later drops TLS: merge changes into it, or re-run `certbot --nginx` afterwards.

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
- `/about.html` (the About page every page's nav links to)

Optional debug toggle: `debug=1` on `/recommendations` and `/videos/similar` returns per-row scoring details only when the Engine runs with `RECOMMENDATIONS_DEBUG=1`. It is off by default. `1`, `true` and `yes` turn it on, in any case and with surrounding whitespace; any other value, blank or unset leaves it off, and `debug=1` then answers `403 Debug mode is disabled`, which the debug view shows. The Engine reads it once at startup, so a change needs a restart. In prod, set it on the template with a drop-in, which applies to both instances, then deploy:
```bash
sudo systemctl edit peertube-engine@.service    # add under [Service]: Environment=RECOMMENDATIONS_DEBUG=1
sudo bash scripts/deploy-bluegreen.sh --blue-green
```
On the dev Engine, use `sudo systemctl edit peertube-engine-dev` and `sudo systemctl restart peertube-engine-dev`.

Putting it in `.env.bridge` turns it on for every Engine unit that reads that file, and `scripts/run-services.sh` exports that file to both services.

Up-next pages are a random draw, so two requests for one video differ. To reproduce a page, add `seed=<int>` to the up-next request; it needs no toggle. Send it to the Engine directly: in prod to `http://127.0.0.1:7079` or the active instance's port (see the upstream snippet), for a manual run to `http://127.0.0.1:7070`. The Client backend does not forward it and answers `400 Unknown query parameter: seed`.

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

Its prod checks expect a single `peertube-engine` unit on 7070 and a Client `--engine-url` on 7070 (`PROD_ENGINE_PORT=7070`), which is not the prod contour's topology, so treat their results on the prod contour as unreliable.

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
then **stops both**. It is a test, not a way to bring the services up. Its Engine port 7072 is the prod Client's port, so on a prod host pass other ports (below). While the Engine loads its index the
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
