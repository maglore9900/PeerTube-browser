# PeerTube-browser — service installation review

Source: https://github.com/denikryt/PeerTube-browser/tree/main (AGPL-3.0, 105 commits on `main`)

Reviewed: `install-service.sh`, `uninstall-service.sh`, `engine/install-engine-service.sh`, `client/install-client-service.sh`, `engine/install-updater-service.sh`, `engine/uninstall-engine-service.sh`, `client/uninstall-client-service.sh`, `engine/server/db/jobs/updater-worker.py`, `README.md`, `DEPLOYMENT.md`.

## Summary

The service install is more modest than it sounds, and it does **not** auto-update code — but it does leave a permanent passwordless sudo grant on your login account, and the units have zero hardening.

## What it actually installs

Five files outside the repo, all under root:

- `/etc/systemd/system/peertube-engine[-dev].service`
- `/etc/systemd/system/peertube-client[-dev].service`
- `/etc/systemd/system/peertube-updater[-dev].service` + `.timer`
- `/etc/sudoers.d/peertube-updater[-dev]-systemctl`, mode 0440

No `/usr/local/bin`, no nginx, no logrotate, no Docker (explicitly rejected). No `rm -rf`, no `chown -R` anywhere. Both servers bind `127.0.0.1` by default (engine 7070, client 7072; dev 7171/7172). Uninstall removes everything the installers wrote.

## F1 — No dedicated service user

`SERVICE_USER="${SUDO_USER:-$(id -un)}"`. It never calls `useradd`. The services run as *you* — your login account, your home directory, your shell profile. If you run the installer as root with no `SUDO_USER`, they run as root.

## F2 — Persistent NOPASSWD sudo grant

The installer writes:

```
<you> ALL=(root) NOPASSWD: /usr/bin/systemctl stop peertube-engine, /usr/bin/systemctl start peertube-engine
```

Narrowly scoped to two verbs on one unit, which is the right way to do it. But it survives until you run the uninstaller, and it exists so a weekly timer job can bounce the engine around a DB merge.

## F3 — Units have no hardening at all

Every unit is `User=`, `WorkingDirectory=`, two `Environment=`, `Restart=on-failure`, `TimeoutStopSec=20`. No `ProtectSystem`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges`, `ReadWritePaths`, `RestrictAddressFamilies`. `NoNewPrivileges` is absent by necessity — the updater needs `sudo` from inside the unit.

## F4 — The weekly timer is a data crawl, not a self-update

`OnCalendar=Fri *-*-* 20:00:00`. `updater-worker.py` contains no `git`, `curl`, `wget`, or `pip`. It runs four Node crawler CLIs against instances seeded from `instances.joinpeertube.org`, builds embeddings, stops the engine, merges staging SQLite into prod, rebuilds the FAISS index, restarts the engine. Then, with the engine serving, it runs `fetch-trending.py`, which calls `GET https://<host>/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both` on every host with an embedded video (minus the denylist) and writes the parsed ids and counts into prod's `trending_ranks`, followed by the similarity-cache rebuild. The restart runs the same on-disk code.

The real exposure: a weekly job fetches data from thousands of third-party PeerTube servers into your prod DB, including one HTTPS request per catalogue host whose response is written into the live DB while the engine reads it, and its `ExecStart` is `/usr/bin/bash -lc '...'` — a **login** shell, so it sources your `~/.bashrc`/`~/.profile` into a process holding that sudo grant.

## F5 — Top-level `--dry-run` under-reports detail

`install-service.sh` echoes the delegated command lines instead of running them, so you never see the unit previews the child scripts would print. Run `engine/install-engine-service.sh --dry-run` and `client/install-client-service.sh --dry-run` directly to see actual unit text. Honest, just shallow.

## Minor

Docs reference `install-service-prod.sh` / `install-service-dev.sh` wrappers that don't exist in the repo. Ports are inconsistent across README vs DEPLOYMENT.md (7072 is both "client backend" and "smoke-test engine"). `--purge-updater-state` targets `/var/lib/peertube-browser/updater-last-success-week.txt`, which nothing creates. The worker's log and `/tmp` lock are never cleaned up.

## If you want it without the service layer

Nothing requires systemd. Run the two processes directly:

```
ENGINE_INGEST_MODE=bridge ./venv/bin/python3 engine/server/api/server.py
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py --port 7072 --engine-url http://127.0.0.1:7070
```

Skip `--with-updater-timer` and you skip the sudoers file entirely — run the updater by hand when you want fresh data. That drops F2 and most of F4. You'd still want to add hardening directives yourself if you do install units, and switch `bash -lc` to `bash -c`.
