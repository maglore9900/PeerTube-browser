# Architecture summary — PeerTube Browser (run-2)

Audit scope: whole repository **except** `.un/` and `src/un/` (excluded by operator request).
Run: `security-audit/run-2`. Prior run: `security-audit/run-1` (8 findings).

## Prior-run state

`git log` shows no commits touching application code since run-1 was written, and
`git status` shows no working-tree changes outside the audit artefacts themselves.
Every run-1 finding (F1–F8) was re-checked at its cited sink and is still present:
`channels/index.ts:277` still interpolates the channel URL into `href` without
`escapeHtml`, `video-page/index.ts:200` still assigns `?embed=` to the iframe `src`,
`api-base.ts` still honours `?api=`, and neither service authenticates anything.

This run therefore did not re-hunt the DOM-XSS and URL-scheme surface that run-1
covered. Effort was weighted toward the areas run-1 named as thin: the batch/updater
jobs, the crawler, the installers, and server-side resource/availability behaviour,
plus request-shape handling at the Client→Engine boundary.

## What this is

A video-discovery front end for the federated PeerTube network: a Node/TypeScript
crawler builds a SQLite dataset plus a FAISS index from public PeerTube instances,
a Python Engine serves recommendations over `http.server`, a Python Client backend
owns writes/profile and acts as the browser-facing gateway, and a Vite-built static
frontend renders the result. No accounts, no login, no secrets in the repo.

## Components and entry points

| Component | Entry point | Binds |
|---|---|---|
| Engine API (read + internal) | `engine/server/api/server.py`, handler `handlers/similar.py` | `127.0.0.1:7070` |
| Client backend (write/profile/gateway) | `client/backend/server.py` | `127.0.0.1:7172` (7072 in docs) |
| Frontend | `client/frontend/src/pages/*` | static build |
| Crawler | `engine/crawler/src/*-cli.ts` | outbound only |
| Updater/batch jobs | `engine/server/db/jobs/*.py` | local, systemd timer |

Trust model as built: everything is anonymous; `user_id` is a caller-supplied string.
The Engine/Client split is an architectural boundary, not a security boundary — the
Engine's `/internal/*` routes are unauthenticated and rely on the loopback bind.

**Deployment shape that matters for this run** (`DEPLOYMENT.md`): both services bind
loopback, the browser talks only to the Client backend, and the Client backend is the
sole caller of the Engine. `_proxy_engine_request` builds its own request headers
(`accept`, `content-type`) and forwards no client identity, so from the Engine's point
of view *the entire user base is one client at 127.0.0.1*. Run-1 assumed the opposite
(that `X-Forwarded-For` reaches the Engine and is spoofable); that assumption is wrong
for the documented deployment and inverts the consequence — see F9.

## Input surfaces re-examined this run

- Gateway-allowlisted query parameters per route (`client/backend/server.py:48-67`) —
  in particular `q`, `instance`, `sort`, `dir` on `/api/channels`, which are the only
  free-text strings a browser can push into an Engine SQL statement.
- `POST /client/events/publish` — arbitrary JSON forwarded verbatim to the Engine's
  bridge ingest, including the batch form `{"events": [...]}`.
- Crawled instance data as *stored content* rather than as markup: long or repetitive
  `channels.display_name` / `channel_name` values, `channel_url`, `avatar_url`.
- Installers and the updater worker (sudoers rule, unit generation, lock file,
  subprocess argument construction).

## Shared-resource inventory (the theme of this run)

- `server.db_lock` is a single global mutex taken by *every* Engine read path
  (`similar.py:316`, `:632`, `:705`, `handlers/video.py:215`, `internal_client_reads.py:36`,
  `internal_events.py:32`). Anything that holds it for a long time is a full outage.
- `sqlite3` connections are created with library defaults — rollback journal,
  `synchronous=FULL` (`engine/server/data/db.py:9-13`) — so every `commit()` fsyncs.
- The in-memory `RateLimiter` (`engine/server/api/http_utils.py:66-91`) is keyed on
  `"{ip}:{path}"` and never evicts empty buckets.

## Baseline comparable

Federated-content aggregators and PeerTube's own web client. Two calibration points
used this run: (a) mature aggregators treat crawled strings as hostile *data* as well
as hostile *markup* — they bound stored field lengths and never let a user-supplied
pattern run unbounded against them; (b) production services put per-query CPU limits
(SQLite `progress_handler`/`interrupt`, statement timeouts) in front of a single-writer
embedded database that is shared by every request thread. This project does neither.
