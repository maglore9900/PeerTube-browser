# Client

Client workspace contains two parts:

- `client/frontend/` - static frontend UI.
- `client/backend/` - write/profile API service that publishes events to Engine.

## Backend Responsibilities

- Owns user write/profile endpoints:
  - `POST /api/profile` — mint a profile; returns `{profile_id, key}`, the key only this once. Rate-limited to 5 per hour per client address; behind a proxy, that address depends on `TRUSTED_PROXIES` (see "Run Backend Locally").
  - `POST /api/profile/rotate` — replace the key; the old one stops working.
  - `POST /api/profile/delete` — remove the profile and everything keyed to it: likes, like generations, dislikes, taste vectors and blocks.
  - `GET /api/profile/reaction?uuid=&host=` — `{liked, disliked}` for one video.
  - `POST /api/profile/likes/import` — `{likes: [{uuid, host}]}`: record browser-held likes in the profile without publishing them again. Only the first 50 entries of `likes` are read; the rest are dropped, not rejected. They are resolved in one Engine `/internal/videos/metadata` call, so a video the Engine does not know, or holds at or over its error-count threshold, is not imported (ADR-0003); a video the profile dislikes is skipped. An imported like opens no published like, so un-liking it publishes nothing unless the profile's own like of that video is still published. Answers `{imported}`.
  - `GET /api/profile/blocks` — the profile's blocks, newest first.
  - `POST /api/profile/blocks` — `{kind, uuid, host}`: block the channel (`kind: "channel"`) or the account (`kind: "account"`) of that video. The backend looks the video up in the Engine and stores the channel's `(instance_domain, channel_id)` or the account's `account_url`. At most 1,000 blocks per profile; past that, 400.
  - `POST /api/profile/blocks/remove` — `{kind, instance_domain, channel_id, account_url}` as the list returns it.
  - `POST /api/user-action` — `action` is `like`, `undo_like`, `dislike` or `undo_dislike`. The dislike actions need a key. With a key, the action is stored in the profile, and a like and a dislike on one video replace each other. A `like` publishes a `Like` only when it opens the profile's published like of the video (see **Published like** in `CONTEXT.md`); an `undo_like`, or a dislike replacing a like, publishes an `UndoLike` only when it closes one. No other dislike action publishes. A request that changes nothing answers 200 `{ok, updatedAt}` and publishes nothing. Without a key, nothing is stored and every `like` and `undo_like` publishes under one fixed id per video and event type, so the Engine counts repeats as duplicates. An event id is `client-` plus the SHA-256 of the actor (profile id or `anonymous`), the Engine-resolved video uuid and host, the event type, and the like generation (0 without a key). At most 1,000 dislikes per profile; past that, 400. Each dislike change asks the Engine for the profile's new taste vectors before anything is stored; if that fails, the answer is 502 and nothing changes.
  - `POST /api/user-profile/reset`
  - `GET /api/user-profile/likes`
  - `POST /api/user-profile/likes` — `{likes: [{uuid, host}]}`: resolves a browser-supplied like list; needs no profile. Reads at most the first 50 entries and resolves them in one Engine `/internal/videos/metadata` call. Answers `{likes, updatedAt}`, with `likes` in submitted order and duplicates removed; a video the Engine does not know, or holds at or over its error-count threshold, is left out. An empty or fully malformed list answers `{likes: []}` without calling the Engine. For how the Engine matches the entries, see `engine/server/README.md`.
  - `GET /api/user-profile`
- Profiles are proved by the `X-Profile-Key` request header only, stored as a SHA-256 hash. `GET /api/user-profile`, `GET /api/user-profile/likes`, `POST /api/user-profile/reset`, rotate, delete, reaction, likes import, the block routes and the dislike actions answer any missing or unknown key with the same 401.
- The read gateway filters per profile. A `/recommendations`, `/videos/similar` or `/api/v1/search/videos` request that carries `X-Profile-Key` has that profile's blocked channels and accounts removed from the Engine's rows; feed requests also lose the profile's disliked videos (search does not). For feeds with blocks or dislikes the backend over-fetches twice the page, capped at 48, and trims back, so pages stay full. Every row the profile likes or dislikes is marked `reaction: "liked"` or `"disliked"`; on feeds only liked rows remain to be marked. An unknown key gets 401. Without the header, the response passes through.
- A keyed feed request is sent to the Engine with the profile's own likes (a random five of its stored likes) in place of any the browser sent, and with the profile's taste vectors, so the Engine ranks videos near its dislikes lower. A keyless body's `likes` are cut to their first 50 entries before being forwarded; entries past the 50th are dropped, not rejected.
- A `/recommendations` or `/videos/similar` body may carry `exclude`: up to 500 `{id, host}` entries (a video's `video_id` and `instance_domain`) that a paging feed has already shown. A non-list or more than 500 entries gets 400 `Invalid exclude payload`; entries without a non-empty string `id` and `host` are dropped, and the rest go to the Engine, keyed or not. The Engine leaves those videos out of home and up-next pages (see `engine/server/api/recommendations/docs/OVERVIEW.md`).
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

`TRUSTED_PROXIES`: the proxies whose `X-Forwarded-For` the backend believes when it resolves the client address. That address keys the rate limiters and the access log, and reaches the Engine as `X-Client-IP`. Unset or blank, it is `127.0.0.1,::1`, so a local run needs nothing. For the syntax, how a set value replaces the default, and how a malformed entry stops startup, see `DEPLOYMENT.md` section 6.
