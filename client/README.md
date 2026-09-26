# Client

Client workspace contains two parts:

- `client/frontend/` - static frontend UI.
- `client/backend/` - write/profile API service that publishes events to Engine.

## Backend Responsibilities

- Owns user write/profile endpoints:
  - `POST /api/profile` — mint a profile; returns `{profile_id, key}`, the key only this once. Rate-limited to 5 per hour per peer address.
  - `POST /api/profile/rotate` — replace the key; the old one stops working.
  - `POST /api/profile/delete` — remove the profile and everything keyed to it: likes, dislikes, taste vectors and blocks.
  - `GET /api/profile/reaction?uuid=&host=` — `{liked, disliked}` for one video.
  - `POST /api/profile/likes/import` — `{likes: [{uuid, host}]}`: record browser-held likes in the profile without publishing them again; a video the profile dislikes is skipped. Answers `{imported}`.
  - `GET /api/profile/blocks` — the profile's blocks, newest first.
  - `POST /api/profile/blocks` — `{kind, uuid, host}`: block the channel (`kind: "channel"`) or the account (`kind: "account"`) of that video. The backend looks the video up in the Engine and stores the channel's `(instance_domain, channel_id)` or the account's `account_url`. At most 1,000 blocks per profile; past that, 400.
  - `POST /api/profile/blocks/remove` — `{kind, instance_domain, channel_id, account_url}` as the list returns it.
  - `POST /api/user-action` — `action` is `like`, `undo_like`, `dislike` or `undo_dislike`. A like publishes its event and is kept server-side only when a profile key is sent. The dislike actions need a key. A like and a dislike on one video replace each other. A dislike publishes nothing, except the `UndoLike` that withdraws a like it replaced. At most 1,000 dislikes per profile; past that, 400. Each dislike change asks the Engine for the profile's new taste vectors before anything is stored; if that fails, the answer is 502 and nothing changes.
  - `POST /api/user-profile/reset`
  - `GET /api/user-profile/likes`
  - `POST /api/user-profile/likes` — resolves a browser-supplied like list; needs no profile.
  - `GET /api/user-profile`
- Profiles are proved by the `X-Profile-Key` request header only, stored as a SHA-256 hash. `GET /api/user-profile`, `GET /api/user-profile/likes`, `POST /api/user-profile/reset`, rotate, delete, reaction, likes import, the block routes and the dislike actions answer any missing or unknown key with the same 401.
- The read gateway filters per profile. A `/recommendations`, `/videos/similar` or `/api/v1/search/videos` request that carries `X-Profile-Key` has that profile's blocked channels and accounts removed from the Engine's rows; feed requests also lose the profile's disliked videos (search does not). For feeds the backend over-fetches twice the page, capped at 48, and trims back, so pages stay full. An unknown key gets 401. Without the header, the response passes through.
- A keyed feed request is sent to the Engine with the profile's own likes (a random five of its stored likes) in place of any the browser sent, and with the profile's taste vectors, so the Engine ranks videos near its dislikes lower.
- Publishes normalized interaction events to Engine bridge:
  - Engine endpoint: `POST /internal/events/ingest`
- Uses Engine read API over HTTP for video resolve/metadata (no direct Engine DB access).

## Boundary Contract (Client-side)
- Browser-facing ownership stays in Client backend:
  - write/profile: `/api/user-action`, `/api/user-profile/*`, `/api/profile*`
  - read gateway: `/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`, `/api/v1/search/videos`
- Client backend consumes Engine internal read contract over HTTP only:
  - `/internal/videos/resolve`
  - `/internal/videos/metadata`
  - `/internal/dislikes/centroids`
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
