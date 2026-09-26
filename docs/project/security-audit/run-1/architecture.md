# Architecture summary — PeerTube Browser

Audit scope: whole repository **except** `.un/` and `src/un/` (excluded by operator request).
Run: `security-audit/run-1`. No prior runs exist for this repo.

## What this is

A video-discovery front-end for the federated PeerTube network. It crawls public
PeerTube instances, builds a local SQLite dataset plus a FAISS ANN index, and serves a
recommendation feed and video pages to anonymous browser users. No user accounts, no
login, no passwords, no payments. Docker is deliberately not used; deployment is
systemd units plus a static asset server (`DEPLOYMENT.md`).

## Components and entry points

| Component | Language | Entry point | Binds |
|---|---|---|---|
| Engine API (read) | Python 3, `http.server` | `engine/server/api/server.py`, handler `engine/server/api/handlers/similar.py` | `127.0.0.1:7070` |
| Client backend (write/profile/gateway) | Python 3, `http.server` | `client/backend/server.py` | `127.0.0.1:7172` (7072 in docs) |
| Frontend | TypeScript + Vite, no framework | `client/frontend/src/pages/{videos,video-page,channels}/index.ts` | static build |
| Crawler | TypeScript, Node | `engine/crawler/src/{channels,videos,instances}-*.ts` | outbound only |
| Batch jobs / updater | Python | `engine/server/db/jobs/*.py` | local, systemd timer |

Trust model as built: **everything is anonymous**. There is no authentication and no
authorization anywhere in either HTTP service. `user_id` is an arbitrary
caller-supplied string (`client/backend/lib/http_utils.py:33`) defaulting to the
literal `local-user`; the frontend never sends one, so every visitor shares one
server-side profile row. The Engine/Client split is an architectural boundary, not a
security boundary: `/internal/*` endpoints on the Engine are unauthenticated and rely
solely on the loopback bind.

## Input surfaces

Browser-facing (via Client backend, CORS `*`):
- `GET /api/video`, `GET /api/channels` — proxied reads to Engine
- `POST /recommendations`, `POST /videos/similar` — proxied reads with a `likes` body
- `POST /api/user-action`, `POST /api/user-profile/reset`, `GET|POST /api/user-profile/likes`, `GET /api/user-profile`
- `POST /client/events/publish` — forwards arbitrary JSON to the Engine bridge ingest
- `GET /api/health`

Engine-facing (loopback): the same read routes plus `/internal/videos/resolve`,
`/internal/videos/metadata`, `/internal/events/ingest`.

Federated/remote input (the important one): the crawler ingests JSON from **arbitrary
third-party PeerTube instances** discovered through the public
`instances.joinpeertube.org` index (`engine/server/db/jobs/sync-whitelist.py:29`).
Channel/video titles, descriptions, avatar URLs, `channel.url`, `video.url` and
`embedPath` are stored as-is and later rendered in the browser. The Engine also fetches
live instance metadata at request time (`engine/server/api/handlers/video.py:75`), and
the frontend fetches instance APIs directly from the user's browser.

URL-parameter input on the frontend: `id`, `host`, `title`, `channel`, `channelUrl`,
`embed`, `url`, `api`, `debug`, `mode` — several of these are assigned straight into
DOM URL sinks.

## Dangerous sinks inventory

- SQL: all queries parameterized; the only interpolated fragments are a whitelisted
  sort expression (`engine/server/data/channels.py:56`) and a constant error clause
  (`engine/server/api/handlers/video.py:67`). Batch jobs interpolate fixed table names.
- HTML: hand-rolled `escapeHtml` + template literals assigned to `innerHTML` in three
  page modules. One attribute is not escaped at all; URL-scheme sinks (`href`, iframe
  `src`) are escaped but not scheme-validated.
- Shell: `subprocess.run/check_output` with argument lists, `execFile("curl", [...])` —
  no `shell=True` anywhere.
- Deserialization: JSON only. No pickle, eval, or dynamic import.
- Outbound HTTP: crawler (by design), Engine `/api/video` live refresh, browser-side
  instance fetches.

## Baseline comparable

The closest comparables are federated-content aggregators and PeerTube's own web
client. PeerTube's client renders remote instance metadata through Angular's
contextual auto-escaping and sanitizes video descriptions; it validates URL schemes
before binding them to `href`. Other aggregators of untrusted federated content
(Mastodon front-ends, RSS readers) treat all remote strings as hostile and allowlist
URL schemes. The tradeoff this project accepts that its comparables do not: remote
strings are stored raw and re-emitted into HTML with an ad-hoc escaper and no CSP.
