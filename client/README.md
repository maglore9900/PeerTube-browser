# Client

Client workspace contains two parts:

- `client/frontend/` - static frontend UI.
- `client/backend/` - write/profile and analytics API service that publishes interaction events to Engine.

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
  - `GET /api/user-profile/likes` — the profile's most recent stored likes, at most 100 (fewer with `?limit=`), resolved in one Engine `/internal/videos/metadata` call. Answers `{user_id, likes, updatedAt}`; a video the Engine does not know, or holds at or over its error-count threshold, is left out of `likes` but stays stored in the profile, and shows again once its error count drops below the threshold.
  - `POST /api/user-profile/likes` — `{likes: [{uuid, host}]}`: resolves a browser-supplied like list; needs no profile. Reads at most the first 50 entries and resolves them in one Engine `/internal/videos/metadata` call. Answers `{likes, updatedAt}`, with `likes` in submitted order and duplicates removed; a video the Engine does not know, or holds at or over its error-count threshold, is left out. An empty or fully malformed list answers `{likes: []}` without calling the Engine. For how the Engine matches the entries, see `engine/server/README.md`.
  - `GET /api/user-profile`
- Owns `POST /api/analytics/event`, which records one anonymous About page event (see **Analytics event** in `CONTEXT.md`). The body is `{type: "outbound_click", track_id, href, page_path, timestamp}` or `{type: "page_view", page_path, timestamp}`: `track_id` fully matches `[a-z0-9_]{1,64}`, `href` is an absolute `http` or `https` URL with a host and at most 2048 characters, `page_path` is 1 to 256 characters starting with `/`, and `timestamp` is a non-negative integer. A `page_view` must not carry `track_id` or `href`, and unknown keys are ignored. The body is parsed as JSON whatever its Content-Type, so a `sendBeacon` body is accepted, and no key is needed. A valid event answers 204 with an empty body and is stored as one row in the `analytics_events` table of `users.db`, with `created_at` set from the server's clock (the client `timestamp` is checked, not stored) and the request's `User-Agent` and `Referer` headers, each NULL when empty. Nothing derived from the client address is stored, and nothing is published to the Engine. An invalid body answers 400 `{"error": ...}` and stores nothing; past the shared limit of 90 requests per 60 s per client address it answers 429 before the body is read. To count the stored events, see "Count About analytics events" in `DEPLOYMENT.md`.
- Profiles are proved by the `X-Profile-Key` request header only, stored as a SHA-256 hash. `GET /api/user-profile`, `GET /api/user-profile/likes`, `POST /api/user-profile/reset`, rotate, delete, reaction, translate, likes import, the block routes and the dislike actions answer any missing or unknown key with the same 401.
- The read gateway filters per profile. A `/recommendations`, `/videos/similar` or `/api/v1/search/videos` request that carries `X-Profile-Key` has that profile's blocked channels and accounts removed from the Engine's rows; feed requests also lose the profile's disliked videos (search does not). For feeds with blocks or dislikes the backend over-fetches twice the page, capped at 48, and trims back, so pages stay full. Every row the profile likes or dislikes is marked `reaction: "liked"` or `"disliked"`; on feeds only liked rows remain to be marked. An unknown key gets 401. Without the header, the response passes through.
- A keyed feed request is sent to the Engine with the profile's own likes (a random five of its stored likes) in place of any the browser sent, and with the profile's taste vectors, so the Engine ranks videos near its dislikes lower. A keyless body's `likes` are cut to their first 50 entries before being forwarded; entries past the 50th are dropped, not rejected.
- A `/recommendations` or `/videos/similar` body may carry `exclude`: up to 500 `{id, host}` entries (a video's `video_id` and `instance_domain`) that a paging feed has already shown. A non-list or more than 500 entries gets 400 `Invalid exclude payload`; entries without a non-empty string `id` and `host` are dropped, and the rest go to the Engine, keyed or not. The Engine leaves those videos out of home, up-next, trending, recent and popular pages (see `engine/server/api/recommendations/docs/OVERVIEW.md`).
- The feed mode travels as the `mode` query parameter on `/recommendations` and `/videos/similar`, and the gateway forwards it unchanged; any query parameter not on a route's allowlist still answers 400 `Unknown query parameter`. The Engine's 400 for an unknown mode reaches the browser with its status and body. For the mode values and what each serves, see `engine/server/README.md`. Block and dislike filtering and the twice-the-page over-fetch apply in every mode. In the fixed-order feeds (trending, recent, popular), rows the gateway removes are never shown, so the browser never puts them in `exclude` and the Engine returns them at the head of every later page; a profile with many blocks or dislikes near the top of an order gets short pages, and eventually an ended feed.
- `nsfw` is on the allowlist for `/recommendations`, `/videos/similar` and `/api/v1/search/videos`; `/api/video` answers it with 400. Unlike every other query parameter, it is forwarded without whitespace stripping (`PROXY_UNSTRIPPED_QUERY_PARAMS`), so a value such as ` 1` reaches the Engine as sent and the Engine alone decides whether it opts in; an empty value is dropped and reaches the Engine as missing. For which values include NSFW-flagged videos, see `engine/server/README.md`. The Engine does this filtering for keyed and keyless requests alike; it is separate from the gateway's block and dislike filter and plays no part in its over-fetch.
- `GET /api/video/refresh` is proxied like the other GET reads, but accepts only `id` and `host`; any other key, or a repeated key, answers 400. The Engine waits on the source instance for this route (see `engine/server/README.md`), so the proxy waits up to 20 s and sends it once with no retry (`ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS`, `ENGINE_PROXY_ROUTE_RETRY_COUNT`); a transport failure or timeout answers 502 `ENGINE_PROXY_UNAVAILABLE`. Every other proxied read waits 10 s and is retried once.
- `GET /api/translate?id=&host=` answers one video's English translate state to a profile holder: `{state: "ready", cues: [{start, end, text}]}` or `{state: "none"}`. It is not proxied; its checks run in this order: the read rate limit (429 `Rate limit exceeded`), `X-Profile-Key` (401), then the query, which accepts only `id` and `host` (an unknown or repeated key answers 400 with the proxy texts; a missing, blank or over-200-character value answers 400 `id and host must be non-empty strings`). It then POSTs once to the Engine's `/internal/translate`, waiting up to 20 s (`TRANSLATE_TIMEOUT_SECONDS`). An Engine 404 `Video not found` (an unknown or denylisted video) answers `none`; any other Engine failure, including the 404 of an Engine without the route and an invalid payload, answers 502 `Engine translate failed`. For how the Engine finds and caches the track, see `engine/server/README.md`.
- In prod the backend reaches the Engine through the nginx loopback listener on `127.0.0.1:7079` (see `DEPLOYMENT.md` section 6), so a down Engine is not a transport failure: nginx answers its own 502 with an HTML body, and the backend relays it like an Engine response, with no retry and no `ENGINE_PROXY_UNAVAILABLE` code, logged as an INFO `engine.proxy` record with `status: 502`. The retry and `ENGINE_PROXY_UNAVAILABLE` still apply when the listener itself cannot be reached or the request times out.
- When an Engine resolve, centroids, lookup, metadata or translate call fails, the answer is 502 `{"error": "Engine <operation> failed"}`, e.g. `Engine metadata failed`. The Engine's status and error text go only to the Client log, as an ERROR `engine.call` record with the text in `context.error`.
- Publishes normalized interaction events to Engine bridge:
  - Engine endpoint: `POST /internal/events/ingest`
  - A failed publish answers `/api/user-action` with 502 and `bridge_error` set to `engine bridge HTTP <code>` when the Engine returned an error status, or `engine bridge unavailable` for any other failure. In prod, a down Engine behind the `7079` listener reads `engine bridge HTTP 502`. The cause goes to the Client log as an ERROR `engine.bridge` record.
- Uses Engine read API over HTTP for video resolve/metadata (no direct Engine DB access).
- Every Engine call made while serving a request sends that request's id as `X-Request-ID` (see `LOG_FORMAT` below): each proxied read, with the same id on every retry attempt, and every bridge call (resolve, metadata, centroids, lookup, translate and the publish). The Engine logs each call under that id, so one browser request can show several Engine `request.start` … `request.end` pairs under one id, e.g. two for a retried read.

## Boundary Contract (Client-side)
- Browser-facing ownership stays in Client backend:
  - write/profile: `/api/user-action`, `/api/user-profile/*`, `/api/profile*`
  - analytics: `/api/analytics/event`
  - profile-gated read, not proxied: `/api/translate`
  - read gateway: `/recommendations`, `/videos/similar`, `/api/video`, `/api/video/refresh`, `/api/channels`, `/api/v1/search/videos`
- Client backend consumes Engine internal read contract over HTTP only:
  - `/internal/videos/resolve`
  - `/internal/videos/metadata`
  - `/internal/dislikes/centroids`
  - `/internal/translate`
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

The prod unit that `client/install-client-service.sh --mode prod` writes uses `--engine-url http://127.0.0.1:7079`, the nginx listener in front of the active Engine instance; see `DEPLOYMENT.md`.

`CLIENT_PUBLISH_MODE`:
- `bridge` (default): publish to Engine bridge ingest endpoint.
- `activitypub`: reserved for next milestone (currently returns not implemented).

`TRUSTED_PROXIES`: the proxies whose `X-Forwarded-For` the backend believes when it resolves the client address. That address keys the rate limiters, is the `ip` of each request's `request.start` record, and reaches the Engine as `X-Client-IP`. Unset or blank, it is `127.0.0.1,::1`, so a local run needs nothing. For the syntax, how a set value replaces the default, and how a malformed entry stops startup, see `DEPLOYMENT.md` section 6.

`CLIENT_CORS_ORIGINS`: the page origins the backend sends CORS headers to. Unset or blank, it sends none, which suits production, where nginx serves the page and the API from one origin. The Vite dev page calls the backend from another origin, so for that setup list the page's exact origin, e.g. `CLIENT_CORS_ORIGINS=http://127.0.0.1:5173`. It is read once at startup, so a change needs a restart. The About page's analytics beacons are cross-origin in that setup too; see `client/frontend/README.md`. For the syntax and how origins are matched, see `DEPLOYMENT.md` section 6.

`LOG_FORMAT`: `json` (the default) or `text`, for every record the backend logs; see `DEPLOYMENT.md` section 2. A record logged other than through `_emit_client_log`, such as a bare `logging` call, appears as event `client.log`, and a record carrying exception info gets a `traceback` key.

Each request logs `request.start` "request started" first, with context `ip`, `method`, `url` and, when the `User-Agent` header is non-empty, `user_agent`, and `request.end` "request finished" last, with context `status` (the code sent, or `-` if none was sent) and integer `duration_ms`; byte counts are in the nginx access log, not here. Every record logged while a request is being served carries a top-level `request_id`: the incoming `X-Request-ID` when it fully matches `[A-Za-z0-9._-]{1,64}`, otherwise a generated `uuid4().hex`, so a rejected value is never logged. Records outside a request, such as startup and stop, carry none. http.server's own errors (a bad request line, an unsupported method, a timeout) log a WARNING `client.http` record with context `peer`. To follow one request across nginx, the Client backend and the Engine, see "Follow one request" in `DEPLOYMENT.md`.
