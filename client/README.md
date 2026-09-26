# Client

Client workspace contains two parts:

- `client/frontend/` - static frontend UI.
- `client/backend/` - write/profile API service that publishes events to Engine.

## Backend Responsibilities

- Owns user write/profile endpoints:
  - `POST /api/profile` — mint a profile; returns `{profile_id, key}`, the key only this once. Rate-limited to 5 per hour per peer address.
  - `POST /api/profile/rotate` — replace the key; the old one stops working.
  - `POST /api/profile/delete` — remove the profile and everything keyed to it.
  - `POST /api/user-action` — publishes the event; records a server-side like only when a profile key is sent.
  - `POST /api/user-profile/reset`
  - `GET /api/user-profile/likes`
  - `POST /api/user-profile/likes` — resolves a browser-supplied like list; needs no profile.
  - `GET /api/user-profile`
- Profiles are proved by the `X-Profile-Key` request header only, stored as a SHA-256 hash. `GET /api/user-profile`, `GET /api/user-profile/likes`, `POST /api/user-profile/reset`, rotate and delete answer any missing or unknown key with the same 401.
- Publishes normalized interaction events to Engine bridge:
  - Engine endpoint: `POST /internal/events/ingest`
- Uses Engine read API over HTTP for video resolve/metadata (no direct Engine DB access).

## Boundary Contract (Client-side)
- Browser-facing ownership stays in Client backend:
  - write/profile: `/api/user-action`, `/api/user-profile/*`
  - read gateway: `/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`
- Client backend consumes Engine internal read contract over HTTP only:
  - `/internal/videos/resolve`
  - `/internal/videos/metadata`
- Client backend publishes normalized events to temporary Engine bridge ingest:
  - `/internal/events/ingest`
- Forbidden:
  - importing `engine.*` modules in `client/backend`,
  - direct reads from `engine/server/db/*`,
  - frontend direct usage of Engine API base instead of Client gateway routes.

## Run Backend Locally

```bash
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py \
  --host 127.0.0.1 \
  --port 7172 \
  --engine-url http://127.0.0.1:7070
```

`CLIENT_PUBLISH_MODE`:
- `bridge` (default): publish to Engine bridge ingest endpoint.
- `activitypub`: reserved for next milestone (currently returns not implemented).
