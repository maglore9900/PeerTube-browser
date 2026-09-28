# 11-fast-similars-response

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-11-fast-similars-response.record.md`._

## Requirements

### Purpose

Nothing on the video page (`client/frontend/video-page.html`, `client/frontend/src/pages/video-page/index.ts`) waits on the source PeerTube instance. Similar videos and the current video's stored metadata render immediately from the Engine's local DB; a separate refresh request fetches live metadata from the instance, persists it to the Engine DB, and updates the page when it arrives. Operator chose the "two-phase metadata" reading of the issue.

### Findings from the tree that shape this build

- The page already starts `loadVideo()` and `loadSimilarVideos()` in parallel, and the similars route (`/recommendations`, proxied by `client/backend/server.py` to the Engine's `_handle_similar` in `engine/server/api/handlers/similar.py`) is served from ANN/cache/DB without contacting the instance. Both the Client backend and the Engine are `ThreadingHTTPServer`, so the two requests do not serialise. The "similars first" part of the issue is therefore already mostly true; what stays empty is the current video's own panel.
- `loadVideo()` renders nothing until metadata arrives. The Engine's `handle_video_request` (`engine/server/api/handlers/video.py`) reads the DB row, then synchronously calls the instance (`fetch_instance_video_dynamic`: `/api/v1/videos/{id}` then `/api/v1/video-channels/{slug}`, `timeout=8` each), merges, writes the DB, then responds. The Client backend proxy (`ENGINE_PROXY_TIMEOUT_SECONDS = 10`) can time out first, after which the browser falls back to `fetchVideoMetadataFromInstance` (another instance wait). Even on success, `fetchVideoMetadataFromServer` awaits the browser-side `fetchInstanceMetadata` (`https://{host}/api/v1/config`) before rendering.
- The DB row (`fetch_video_row`) already holds title, description, embed_path, video_url, channel (name/url/display name/followers/avatar), account name/url, views, likes, dislikes and published_at: enough to render the panel immediately.
- The Client backend allow-list `PROXY_ALLOWED_QUERY_PARAMS["/api/video"]` already lists `refresh_cache`, which the Engine's video handler ignores today.

### R1 - Fast metadata from the DB

The Engine's `GET /api/video` answers from the DB row only; it makes no instance call and performs no DB write. The response keeps its current JSON shape and field names (`videoUuid`, `title`, `description`, `channelName`, `channelUrl`, `channelAvatarUrl`, `subscribersCount`, `instanceName`, `instanceUrl`, `accountName`, `accountUrl`, `accountAvatarUrl`, `embedUrl`, `originalUrl`, `views`, `likes`, `dislikes`, `publishedAt`), each filled from the DB with the same fallbacks as today (e.g. channel URL built from slug + host, original URL built from uuid/id + host). Fields only the instance supplies today (e.g. `accountAvatarUrl`) are empty or DB-sourced. A missing row still answers 404 `{"error": "Video not found"}`; a missing id still answers 400.

### R2 - Separate refresh request

A separate Engine route performs the live refresh, and the Client backend proxies it with its own query-parameter allow-list (same sanitising rules as the other read proxies). It:
- resolves the row exactly as `/api/video` does (404 if absent);
- fetches from the instance with today's behaviour: `timeout=8`, catching `HTTPError`/`URLError`/`TimeoutError`, field-by-field fallback to the DB row when the instance omits or fails a field;
- on a successful instance fetch, persists with today's writes: the `videos` UPDATE (title, description, channel_name, views, likes, dislikes, popularity via `compute_popularity`, tags_json, category, nsfw, last_checked_at), the `channels` UPDATE when `channel_id` is known, and the reset of `instances.last_error`/`last_error_at`/`last_error_source`; a `sqlite3.OperationalError` on write is logged and does not fail the response, as today;
- on a failed instance fetch writes nothing;
- returns the merged metadata in the same shape as `/api/video`.
This route is the single write path for per-request metadata refresh, so issue 10 (metadata completeness) can extend it later.

### R3 - Page flow and ordering

On load the page starts three independent requests: similars, fast metadata (R1), and refresh (R2); none awaits another. The video panel renders from whichever metadata response arrives first; when the refresh succeeds the panel re-renders with its values. Refreshed data always wins regardless of arrival order: a fast response arriving after the refresh must not overwrite refreshed values. If the refresh fails, errors or times out, the panel keeps what it shows and no error is shown to the visitor (a console warning is acceptable).

### R4 - No instance wait before first render

Nothing in the first render of the video panel awaits a request to the source instance. The browser-side `fetchInstanceMetadata` call (`/api/v1/config`, supplying instance name and avatar) moves off the first-render path; its values fill in when it resolves. Until then the instance chip shows the host with initials fallback, as it does today when that call fails.

### R5 - Video unknown to the Engine

When fast metadata answers 404 (or fails), the panel renders immediately from the URL params (`title`, `channel`, `channelUrl`, `embed`, `url`, `host`, as `fallback` holds them today), and the existing direct browser-to-instance fallback (`fetchVideoMetadataFromInstance`) fills it in when it arrives. The existing `https://`-only check on the embed URL is kept on every render path.

### R6 - Re-render safety

A re-render of the panel:
- does not reassign the embed iframe `src` when the embed URL is unchanged (playback must not restart);
- does not attach duplicate listeners to the like, dislike, block-channel or block-account buttons (the existing `dataset.wired` guards keep holding);
- does not fetch the visitor's reaction again once it has been fetched for the same video uuid/host;
- keeps escaping and `safeExternalUrl` on every value it writes, as today.

### R7 - Similars unchanged

Similars content, ranking, limit (8), the `localLikesImported` wait, profile-key handling and error display are unchanged. A test shows that a similars request is answered without contacting the source instance and is not delayed by a slow metadata/refresh call running concurrently.

### Constraints

- The refresh route's worst case on the instance is about 16 s (two sequential 8 s calls) while the Client proxy times out at 10 s. The design step must decide how the refresh fits that budget (for example a per-route proxy timeout, a shorter instance timeout, or a single overall budget) and state the choice; a proxy timeout on the refresh must degrade per R3 (panel keeps its values), never blank the page.
- Stdlib only on the Python side; no new frontend dependency. New code matches the style of the file it lands in.
- `client/frontend/dist/` is build output and is not hand-edited.

### Out of scope

- Rendering tags/category and refreshing further fields (issue `10-video-metadata-completeness`).
- Loading more similars on scroll / removing the similar-videos page (issue `12-similars-on-scroll`).
- Similars diversity (issue `09-similars-diversity`).

### Baseline suite state

Pre-build suite exited 0; baseline variant: false. Tests live in `tests/active` (working area `tests/tmp`).

## High-level plan

### Approach

The Engine's single video handler becomes two routes over one merge step. On the frontend, `loadVideo` is split into a render function that can run more than once and a small coordinator that decides which result wins.

**Engine (`engine/server/api/handlers/video.py`, dispatch in `engine/server/api/handlers/similar.py`).** `handle_video_request` is split into three module-level functions in the file's existing style:
- a row resolver: id/host parsing, 400 on missing id, 404 `{"error": "Video not found"}` on a missing row, using `fetch_video_row` with `video_error_threshold` as today;
- a pure merge that takes the row, a `dynamic` dict and the instance domain, and returns the response dict. This is today's merge block unchanged: `dynamic`-or-row per field, channel URL from slug + host, original URL from uuid/id + host, embed from `embed_path`;
- a persist function holding today's three UPDATEs, its `sqlite3.OperationalError` catch and its log line, unchanged.

How each requirement is met:
- **R1.** `GET /api/video` = resolve, then merge with an empty `dynamic`. No `urlopen`, no write. Every field falls back to the DB exactly as today. `accountAvatarUrl` comes back empty because no DB column holds it.
- **R2.** A new `GET /api/video/refresh`, added next to the `/api/video` branch in `SimilarHandler`'s GET dispatch. It resolves the row the same way, calls `fetch_instance_video_dynamic` (unchanged: `timeout=8` per call, same exception set, same field picking), merges, persists only when the instance fetch succeeded, and responds with the same shape. This handler is the one per-request write path that issue 10 extends later.
- **Success signal (a gotcha found while reading).** `fetch_instance_video_dynamic` currently always returns a non-empty dict of keys, even when the detail call failed. Today's `if dynamic` guard is therefore always true, so today a failed fetch still writes DB values back, bumps `last_checked_at` and clears `instances.last_error`. R2 says a failed fetch writes nothing, so the function returns `{}` when the `/api/v1/videos/{id}` call itself returns `None`. Success means "the video detail came back". A failed channel sub-call still counts as success, with DB fallback for the channel fields, which matches the field-by-field rule. The function has no other callers; I grepped the tree.

**Client backend (`client/backend/server.py`).**
- `/api/video/refresh` is added to `PROXY_READ_GET_ROUTES`, so it gets the same rate limit and the same `_handle_engine_read_proxy_get` sanitising: unknown key → 400, repeated key → 400, values stripped.
- Its own `PROXY_ALLOWED_QUERY_PARAMS` entry is `{"id", "host"}`. `refresh_cache` stays on `/api/video`'s list, untouched.
- It is not in `FILTERED_ROUTES`, so it passes through `_profile_filter` untouched.

**Budget decision (the constraint).** The refresh route gets a per-route proxy timeout of 20 s and no proxy retry. Everything else keeps `ENGINE_PROXY_TIMEOUT_SECONDS = 10` and `ENGINE_PROXY_RETRY_COUNT = 1`. It is implemented as a small path→timeout mapping and a path check on the retry count inside `_proxy_engine_request`.
- The Engine's worst case of about 16 s (two sequential 8 s calls) fits, so R2 keeps today's instance timeouts literally.
- Dropping the retry matters as much as the timeout. Today a transport timeout is retried, which on this route would fire a second pair of instance calls and possibly a second write.
- If the proxy still gives up, the browser gets the proxy's usual failure status. R3 treats that as a failed refresh: the panel keeps its values and a console warning is logged.
- The Engine thread carries on and may still persist the result, which is harmless and even useful for the next visit.

**Frontend (`client/frontend/src/pages/video-page/index.ts`).**
- `loadVideo` becomes `renderVideo(metadata)`: today's body, minus the fetching.
- A coordinator starts three things at load, none awaiting another:
  - the fast `/api/video` fetch;
  - the `/api/video/refresh` fetch;
  - one shared `fetchInstanceMetadata(host)` promise.
  `loadSimilarVideos()` stays exactly as it is.
- **R3 ordering.** Each metadata source carries a rank: URL params 0, fast DB 1, direct browser-to-instance fallback 2, refresh 3. A result renders only if its rank is at least the rank currently shown. A late fast response therefore never overwrites refreshed values, whatever the arrival order. A failed or non-OK refresh logs `console.warn` and changes nothing.
- **R4.** `fetchVideoMetadataFromServer` no longer awaits `fetchInstanceMetadata`. When the shared instance promise resolves, its avatar (and its name, where today's precedence lets the name through) is stored and the current best metadata is re-rendered. Until then the instance chip shows the host with initials, as it does today when `/api/v1/config` fails. Today's precedence is kept: the Engine's `instanceName`/`instanceUrl` win over the config values, and only the avatar is new. The direct-instance fallback also stops awaiting `fetchInstanceMetadata` and uses the shared promise.
- **R5.** If the fast fetch returns non-OK or throws, the panel renders at once from `fallback` (rank 0). `fetchVideoMetadataFromInstance` then runs, and its result renders at rank 2 when it arrives. The `https://` check on the embed stays inside `renderVideo`, so every path passes through it.
- **R6.**
  - A module-level `lastEmbed` holds the last embed string assigned; `src` is set only when the checked embed differs from it. The comparison is against our own string, not `embedEl.src`, which the browser normalises.
  - The block and like buttons keep their `dataset.wired` guards.
  - `loadReaction` is gated by a `uuid|host` key of the last reaction fetched, so re-renders do not fetch it again for the same video.
  - Escaping and `safeExternalUrl` stay on every write because the rendering code itself is not changed.
- **R7.** Similars code is untouched. The new test starts the Engine handler over a fixture DB with `fetch_instance_json` patched to block for several seconds. It fires a refresh and then a similars request concurrently, and asserts the similars answer arrives well inside that delay with the instance stub never called by it.

Files touched: `engine/server/api/handlers/video.py`, `engine/server/api/handlers/similar.py` (one dispatch branch), `client/backend/server.py`, `client/frontend/src/pages/video-page/index.ts`, and `engine/server/README.md` (route list). `dist/` is regenerated by the build, not edited.

### Alternatives considered

- **Keep one `/api/video` with a `refresh_cache` flag, since the allow-list already carries it.** Rejected: R2 asks for a separate route. A flag would also give one route two latency profiles, so a proxy timeout could not be tuned per behaviour.
- **Refresh in the background inside the Engine after `/api/video` answers from the DB, with the page polling or calling again.** Rejected: it needs a thread or queue and a second read to see the result, where one extra request already carries the data.
- **Shorten the instance timeouts, or give the Engine one overall deadline of about 9 s across both calls, so the refresh fits the existing 10 s proxy timeout.** This keeps the proxy uniform. Rejected because R2 fixes `timeout=8` as today's behaviour, and the refresh is off the render path, so waiting longer costs the visitor nothing. It remains the upgrade if long-held threads ever matter.
- **Render from the URL params at t=0, before any response.** Rejected: the `?embed=` value and the DB `embed_path` can differ textually, which would reload the iframe moments later. R3 also says the first render comes from a metadata response. The URL-param render happens only when the fast call fails, as R5 says.
- **Extract the rank arbitration into a shared lib module for testability.** Not chosen by default: it has one caller. Tests can drive the page in node with a stubbed `document`/`fetch`, the same way `test_frontend_blocks.py` stubs the platform. If that proves too heavy, the test step may justify extracting the helper.

### Risks, gotchas and limitations

- `urlopen(timeout=8)` bounds each socket operation, not the whole call. A slowly dripping instance can take longer than 16 s. The 20 s proxy timeout caps what the browser waits, and R3's degrade covers it.
- Each page view now holds a Client thread and an Engine thread for up to about 20 s on a slow instance, instead of up to 10 s plus a retry. Both servers are `ThreadingHTTPServer` with unbounded threads, so this costs memory, not correctness.
- Each page view now makes two Client→Engine metadata requests, so it spends two rate-limit tokens instead of one. The refresh has its own per-path bucket, so it does not eat into `/api/video`'s.
- The fast path no longer bumps `last_checked_at`; only a successful refresh does. Nothing I read keys on it per request, but a worker that relies on it would see fewer bumps. They would now be honest ones, because today it is bumped even on failure.
- The first-wired closures keep the first known video: the reaction listener captures the first `reactionVideo()`, and `enableBlockButtons` the first uuid. Re-renders do not rewire them. This is unchanged from today, but it becomes visible only if a later source reports a different uuid than the first, which should not happen for one row.
- Avatar `innerHTML` is rewritten on every re-render, so the images may flicker once. This is cosmetic; skipping unchanged avatars is a trivial follow-up if it shows.
- If the fast call fails but the refresh succeeds, for example on a transient proxy error, rank 3 wins as intended, and the direct-instance fallback's later result is ignored.

### Tradeoffs the operator is asked to accept

- A refresh against a slow or dead instance can keep a request open for up to 20 s, and the proxy does not retry it. This is the price of keeping today's 8 s per-call instance timeouts inside R2.
- `accountAvatarUrl` is empty on first render and appears only after a successful refresh, because the DB has no column for it. Adding one is issue-10 territory.
- A failed instance fetch no longer clears `instances.last_error` or bumps `last_checked_at`. This follows directly from R2 but changes today's accidental behaviour.

## Impacts

<impacts>
<impact path="engine/server/api/handlers/video.py" element="handle_video_request() (lines 208-361), split into resolver, pure merge, persist, plus a /api/video handler and a /api/video/refresh handler">
**What changes.** The one function becomes three module-level helpers and two thin route handlers.
- **Resolver.** Takes lines 210-224. `id` falls back to `video_id` and `host` to `instance_domain` (210-211). It answers 400 `{"error": "Missing video id"}` and 404 `{"error": "Video not found"}`, and calls `fetch_video_row(..., error_threshold=server.video_error_threshold)` inside `with server.db_lock:`, which is held for 215-221 only.
- **Merge.** Takes lines 226-290 with `dynamic` passed in. Line 226, `instance_domain = row.get("instance_domain") or host_param or ""`, needs `host_param`, so the resolver has to hand back `host_param` or `instance_domain` along with the row.
- **Persist.** Takes lines 292-358. It needs the merged intermediates (`title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`) plus `row["video_id"]`, `row["channel_id"]`, `row["published_at"]` and `instance_domain`. The response dict cannot supply them:
  - it has no `channel_slug`, `tags_json`, `category` or `nsfw`;
  - it turns `None` into `""` (`channelName: channel_display or ""`, `title or ""`).
  So feeding persist from the response would write `""` where today's code writes `NULL`. The plan says the merge "returns the response dict"; it must also expose the intermediates, or persist must re-derive them. The plan leaves this open.
- **`/api/video`.** Resolve, then merge with `{}`. Every `dynamic.get(...)` is `None`, so each field falls back to the row exactly as today. `accountAvatarUrl` (283) becomes `""`. `accountName`/`accountUrl` (281-282) already come from the row only.
- **`/api/video/refresh`.** Resolve, `fetch_instance_video_dynamic`, merge, persist only on success, then respond with the same shape.
- **Docstrings.** The module docstring (1-7, "Merge DB metadata with live instance metadata (when available)") and line 209 must say which route does what.

**What depends on it.** `engine/server/api/handlers/similar.py:84` imports `handle_video_request` by name, and `similar.py:495-497` calls it. Nothing else imports it. No test in `tests/active` touches this module (grep for `handlers.video`, `/api/video` and `fetch_instance` over `tests/`); only the smoke scripts call `/api/video`.

**Regression risk: medium.**
- **Lock boundary.** The instance call must stay outside `server.db_lock`, as today, where the lock is taken only around the SELECT (215) and around the UPDATEs (303). Pulling the fetch inside the resolver's `with` block would stall every Engine route that takes the lock (similar.py 261, 467, 652, 884, 957; similars included) for up to about 16 s, which breaks R7.
- **Renames.** A renamed or removed `handle_video_request` breaks the import at similar.py:84. That is an import-time failure of the whole Engine, and every test that uses the session `engine` fixture fails with it.
- **Races.** The row is read before the instance call and written after it, so two concurrent refreshes of one video both write and the last one wins. This is harmless.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_video_dynamic() (lines 162-205): return {} when the detail call fails">
**What changes.** Line 164 today is `detail = fetch_instance_json(host, f"/api/v1/videos/{quote(video_id)}") or {}`. It becomes an early `return {}` when the detail call does not come back.

**The gotcha is confirmed.** The return at 188-205 always builds a 14-key dict, so the `if dynamic and instance_domain and row.get("video_id")` guard at 293 is always true today. A failed fetch therefore:
- writes DB values back;
- recomputes `popularity`;
- bumps `last_checked_at`;
- clears `instances.last_error*`.

**Edge cases for the success test.**
- **Non-dict JSON.** `fetch_instance_json` returns whatever `json.loads` gives. A 200 with a JSON array or string reaches `detail.get` and raises `AttributeError`, which nothing catches. This is pre-existing.
- **Empty object.** A 200 with `{}` passes an `is not None` test but carries no data, so persist would write DB values back and clear `last_error`.
- **The fix.** Testing `isinstance(detail, dict) and detail` closes both cases.

**Channel sub-call.** The sub-call at 176 runs only when `channel_slug` came back, so after the change it runs only on success.

**What depends on it.** Only `handle_video_request` today (grep of the tree, tests included), and only the refresh handler after the build.

**Regression risk: low.** This is the one deliberate behaviour change and the operator accepts it. The consequence: a failed fetch no longer resets `instances.last_error` or bumps `last_checked_at`.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_json() (lines 75-87): unchanged; the test seam; narrow exception set">
**What changes.** Nothing. The R7 test and the refresh tests patch it.

**What depends on it.**
- Both instance calls in `fetch_instance_video_dynamic` look it up as a module global. A test must patch the attribute on the `handlers.video` module; patching an imported alias has no effect.

**The error path.**
- **What is not caught.** `except (HTTPError, URLError, TimeoutError)` misses `json.JSONDecodeError` (a non-JSON 200), `UnicodeDecodeError`, and `ConnectionResetError`/`http.client.RemoteDisconnected` raised during `resp.read()`.
- **What happens then.** These escape the refresh handler. `SimilarHandler.do_GET` (similar.py:433-441) re-raises anything that is not an interrupted `OperationalError`, so the Engine drops the connection without answering.
- **What the Client sees.** The drop reaches the Client as `RemoteDisconnected` or a reset, not as a `URLError`. It therefore lands in `except Exception` (client/backend/server.py:700-721), which answers 502 `ENGINE_PROXY_FAILURE`. The page treats that as a failed refresh (R3).
- **Before and after.** This is pre-existing: today the same failure kills `/api/video` itself. After the split only the refresh can hit it.
- **Timeout scope.** `timeout=8` bounds each socket operation, not the whole call.

**Regression risk: none in code.**
</impact>
<impact path="engine/server/data/db.py" element="statement_deadline() / _deadline_passed() / PROGRESS_HANDLER_INSTRUCTIONS (lines 14-64), as it applies to the refresh's persist">
**What changes.** Nothing in code, but the refresh's timing brings this into play.

**How the deadline applies.**
- `SimilarHandler.do_GET` (similar.py:436) runs the whole dispatch inside `self._statement_deadline()` (similar.py:345-353). That is `statement_deadline(server.statement_timeout_seconds)`, and `DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0` (server_config.py:435) is assigned at `engine/server/api/server.py:272`.
- The deadline is wall-clock time, thread-local, and counted from the start of the request.
- The refresh reaches its UPDATEs only after up to about 16 s of instance calls, so by then its thread's deadline has usually passed.
- The progress handler fires every 10,000 VM instructions (line 14). Any persist statement that runs that long after the deadline is aborted with `OperationalError: interrupted`.
- The `videos` UPDATE fires `videos_fts_au` (`engine/server/db/jobs/sync-whitelist.py:279-284`), which deletes and re-inserts title, description, tags_json, category and channel_name into FTS5. Crossing 10,000 instructions is plausible there, especially with long descriptions.

**Consequence.**
- The persist's own `except sqlite3.OperationalError` (video.py:352-358) catches the abort, logs `[video] failed to persist dynamic metadata ... interrupted`, and `with server.db:` rolls back.
- The response is still 200 with the refreshed values, so a successful but slow refresh can silently fail to persist, against R2.
- This is pre-existing and masked today. After the build the refresh is the only writer, so it now matters.

**Mitigation.** Wrap persist in its own nested `statement_deadline(...)`. Lines 59-64 save and restore the outer deadline, so nesting is supported. The other option is to state it as a limitation.

**Regression risk: medium to high for R2's persist guarantee.** I have not measured whether one UPDATE plus the trigger actually crosses 10,000 instructions. A child-process test with a lowered `statement_timeout_seconds` and a sleeping `fetch_instance_json` would show it.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._dispatch_get() /api/video branch (lines 495-497), import at line 84, module docstring route list (lines 3-13)">
**What changes.**
- A new branch, `if url.path == "/api/video/refresh":`, goes beside line 495 and calls the refresh handler.
- The import at line 84 gains the new name or names.
- The docstring gains a `/api/video/refresh` line, and line 9 (`/api/video: single video metadata.`) should say it reads from the DB.

**What depends on it.**
- **Rate limit.** Line 447 rate-limits every path under `/api/` on the key `f"{ip}:{path}"` (`_rate_limit_check`, 576-583). The refresh therefore gets its own bucket (`DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60`, server_config.py:431). The ip comes from the `x-client-ip` header the Client sets (client/backend/server.py:590).
- **Matching.** Paths are matched with `==`. `_extract_video_id_from_similar_path` (499) matches only `/videos/.../similar`, so without the new branch `/api/video/refresh` falls through to the 404 at 508. Nothing shadows it.
- **Deadline.** Both routes run inside the statement deadline in `do_GET` (see the db.py entry). An interrupted error raised during the resolver's SELECT would still reach `_respond_interrupted` as a 503, but that SELECT is fast.

**Regression risk: low.** It is one branch, and the similars dispatch (499-506, `_handle_similar_request`) is untouched, which keeps R7.
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="module docstring line 5 ('video: fetches video metadata for /api/video.')">
**What changes.** The line names both routes: `/api/video` (DB only) and `/api/video/refresh` (live instance refresh, persisted on success).

**What depends on it.** Nothing.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/http_utils.py" element="respond_json() (lines 23-30), the refresh's final write">
**What changes.** Nothing.

**Why it matters.**
- It writes to `handler.wfile` unguarded.
- A slowly dripping instance can outlast the Client's 20 s proxy timeout, because `timeout=8` applies per socket operation. The Engine then writes its late answer to a socket the Client has already closed.
- The write raises `BrokenPipeError`/`ConnectionResetError`, which `do_GET` does not catch, so `socketserver` prints a traceback to stderr.
- By then persist has already run, so the data is kept, and the browser has already had its 502.
- This is pre-existing on `/api/video` at 10 s; after the build only the refresh can hit it.

Unlike this Engine helper, the Client side's `respond_bytes` already returns False when the client disconnects (server.py:619).

**Regression risk: low (log noise).**
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer (ThreadingHTTPServer, line 207): video_error_threshold (230/264), popularity_like_weight (234/268), statement_timeout_seconds (272), db, db_lock">
**What changes.** Nothing.

**What depends on it.**
- The resolver reads `server.video_error_threshold` directly, not through `getattr`.
- Persist reads `getattr(server, "popularity_like_weight", 2.0)`, `server.db` and `server.db_lock`.
- `ThreadingHTTPServer` gives each request its own thread, so a refresh blocked on an instance holds one thread and not the server. R7 relies on this.

**Test note.** A child-process test needs a server object that carries `db`, `db_lock` and `video_error_threshold`, plus `popularity_like_weight` if persist runs and `statement_timeout_seconds` if the deadline is exercised. `tests/active/test_internal_events.py:52` builds a real `SimilarServer` from kwargs this way.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/popularity.py" element="compute_popularity(), called by persist (video.py:295-301)">
**What changes.** Nothing. It moves with the persist block. Its arguments must stay:
- the merged `views`/`likes` (the instance value, or the DB fallback);
- `row["published_at"]`;
- the like weight;
- `now_ms_value=checked_at`.

**What depends on it.** The `videos.popularity` column, which ranking reads.

**Regression risk: low.** Today it runs on every page view, including failed fetches that write the DB values back unchanged. After the build it runs only on a successful refresh, and the popular-video ordering reads the same column.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="videos_fts_au AFTER UPDATE trigger (lines 279-284)">
**What changes.** Nothing.

**What depends on it.** Every persisted refresh fires the trigger and re-indexes the video for search. Writes fall from one per page view (failures included) to one per successful refresh, so FTS churn and write-lock time go down. It is also why the statement-deadline entry matters.

**Regression risk: none in code.**
</impact>
<impact path="engine/server/data/metadata.py" element="readers of videos.last_checked_at (lines 57, 98, 201); also data/random_videos.py (54-301), data/search.py (80), data/channels.py (129-159, instances.last_error*)">
**What changes.** Nothing.

**What depends on it.**
- These files only project `last_checked_at` and `instances.last_error*` into rows. A grep of `engine/server` (outside whitelist_migrations.py) shows nothing that filters or orders on them.
- The frontend source never reads `last_checked_at` (grep of `client/`, dist excluded).
- So the fast path no longer bumping them, and a failed refresh no longer clearing `last_error`, is invisible to serving.
- `/api/channels` exposes `last_error*` as data, so a stale error now stays visible there until a successful refresh or a crawl clears it.

**Regression risk: none in serving; low for the `/api/channels` display.** I did not audit the crawler (`engine/crawler`), which keeps its own DB.
</impact>
<impact path="engine/server/api/server_config.py" element="DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0 (435), DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60 (431), line 455 comment ('Optional future toggle for /api/video hide behavior')">
**What changes.** Nothing.

**What depends on it.**
- The statement budget interacts with the refresh persist.
- The Engine's per-path rate limit now applies to the refresh as a separate bucket.
- The line 455 toggle is not referenced by video.py and stays unrelated.

**Regression risk: none.**
</impact>
<impact path="client/backend/server.py" element="PROXY_READ_GET_ROUTES (lines 81-83) and PROXY_ALLOWED_QUERY_PARAMS (lines 85-101)">
**What changes.**
- `"/api/video/refresh"` joins the frozenset.
- A new entry `"/api/video/refresh": {"id", "host"}` is added.
- `/api/video` keeps `{"id", "host", "refresh_cache", "user_id"}`.

**What depends on it.**
- `do_GET` (277-282) routes on `url.path in PROXY_READ_GET_ROUTES`. It applies `_rate_limit_check(url.path)` (406-409, key `ip:path`, `RATE_LIMIT_MAX_REQUESTS = 90` per 60 s), so the refresh gets its own Client bucket, then calls `_handle_engine_read_proxy_get`.
- `_handle_engine_read_proxy_get` (417-436) answers 400 on an unknown key or a repeated key, and strips values.
- The frontend must send only `id` and `host`: a `user_id` or `refresh_cache` on the refresh now gets 400.

**Regression risk: low.** It is a pure addition.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request() (lines 570-745) with ENGINE_PROXY_TIMEOUT_SECONDS (77), ENGINE_PROXY_RETRY_COUNT (79), ENGINE_PROXY_RETRY_DELAY_SECONDS (80)">
**What changes.** A path→timeout mapping (20 s for the refresh, `ENGINE_PROXY_TIMEOUT_SECONDS` otherwise) and a per-path retry count (0 for the refresh, `ENGINE_PROXY_RETRY_COUNT` otherwise).

**Four sites must read the per-path values.**
- 604: `for attempt in range(ENGINE_PROXY_RETRY_COUNT + 1)`.
- 606: `urlopen(request, timeout=ENGINE_PROXY_TIMEOUT_SECONDS)`.
- 696: `if attempt < ENGINE_PROXY_RETRY_COUNT`.
- 731: the `"attempts": ENGINE_PROXY_RETRY_COUNT + 1` field of the "proxy request unavailable" log. It is easy to miss; left alone it logs 2 attempts for a refresh that made 1.

**Key on `path`.** The mapping must use `path`, not `upstream`, which carries the query string (581-583).

**What depends on it.** Every proxied read:
- GET `/api/video`, `/api/channels` and `/api/v1/search/videos`;
- POST `/recommendations` and `/videos/similar` (561).

All of them must keep 10 s and one retry.

**How a refresh failure surfaces.**
- The Engine writes nothing until it finishes, so the proxy waits up to the full timeout.
- `socket.timeout` is `TimeoutError`, which lands in the `(URLError, TimeoutError)` branch (694). With 0 retries the loop breaks to the 502 `ENGINE_PROXY_UNAVAILABLE` (736-744).
- A dropped Engine connection lands in the generic 502 (700-721).
- An Engine 404 or 400 with a body passes through the HTTPError branch (646-677).
- All of these are non-OK for the browser.

**Test harness.** `tests/active/test_server.py` offers `_serving` (347-355), `_client_backend` (358-367), `_status` (370-378, `timeout=30`) and an `EngineStub` (400-422), which together are the template for a stub that counts GETs and sleeps. No existing test monkeypatches the proxy constants, so a new test can patch them or the mapping on `client_server` to stay fast.

**Regression risk: medium.** This loop carries every browser read. A wrong key or a missed site silently changes the timeout or retry for every route, so tests must pin both the refresh and one ordinary route.
</impact>
<impact path="client/backend/server.py" element="_handle_engine_read_proxy_get() (417-436) and _profile_filter() (438-469)">
**What changes.** Nothing.

**What depends on it.**
- The refresh gets the same sanitising.
- An empty value is dropped (431), so `id=` reaches the Engine with no `id` and gets its 400 `Missing video id`, which the Client passes through.
- `_profile_filter` returns `(True, None, None, None)` for the refresh, because it is in neither `FEED_ROUTES` nor `FILTERED_ROUTES` (71-72). An `X-Profile-Key` header on it is therefore ignored rather than validated.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="module top level: `void loadVideo()` (79), `void loadSimilarVideos()` (80), currentMetadata (50), seedId/seedHost (54-55), fallback (57-63), localLikesImported (75-77), applyActionIcons() (1226)">
**What changes.** Line 79 becomes the coordinator start. Line 80 is unchanged.

**What the coordinator must preserve.**
- **No usable source.** When `resolveVideoSource()` gives no host or no id, `fetchVideoMetadata` returns `null` at 508, and today the page renders once with `metadata = null` from `fallback`, `seedHost` and `https://${seedHost}`. That must be kept, and in that case neither the fast fetch nor the refresh should fire.
- **`currentMetadata` in step.** It must always equal the metadata actually rendered, because `reactionVideo()` (381-386) reads it through `resolveLikeUuid`/`resolveLikeHost` (1151-1166).

**Testing constraints.** The module does DOM work at import:
- about 27 `getElementById` constants (22-48);
- `window.location.search` (53);
- `importLocalLikes` (75);
- `applyActionIcons()` (1226);
- `import "../../video.css"` (5).

A node test of the page therefore needs a stubbed `document`/`window`, a scripted `fetch`, `localStorage`, and an esbuild css loader flag. The existing frontend tests (`test_frontend_blocks.py:23,66`, `test_frontend_videos.py`, `test_frontend_reactions.py`, `test_frontend_profile.py`) bundle data modules only, with `--platform=node`.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadVideo() (lines 85-229) becoming renderVideo(metadata)">
**What changes.** The body stays, minus `await fetchVideoMetadata()` (86). `currentMetadata = metadata` (87) moves into or next to it. It now runs once per accepted source, and again when the instance config arrives.

**What re-runs on every render.**
- **Text and markup.** Title, the channel `innerHTML` through `escapeHtml`/`safeExternalUrl` (120-122), subscribers, instance link, account link, description, views, counts and the original link. All of these are idempotent.
- **Avatars.** `channelAvatarEl.innerHTML` (129) and the instance and account avatars (154-161, 179-186) are rewritten, and `bindAvatarFallback` (426-437) binds a `once` listener to each fresh `<img>`. The old nodes are discarded, so listeners do not pile up, though an image may flicker.
- **Embed (212-221).** Today it sets `embedEl.src = embed` unconditionally. The new `lastEmbed` guard must compare against the checked string actually assigned, and must be cleared when the `else` branch calls `removeAttribute("src")`; otherwise a later valid identical URL is never reassigned.
- **`document.title`** (114).
- **`enableBlockButtons`** (196) is guarded by `dataset.wired`.
- **`void loadReaction()`** (197) needs the new gate (see its entry).

**Values across sources.**
- The Engine sends `""`, not null, for empty strings, so `metadata?.title ?? fallback.title` gives `""`, and `titleEl` shows "Video page" through `title || "Video page"`, as today.
- Ranks 1 and 3 both carry `embedUrl = resolve_asset_url(instance_domain, row.embed_path)`, which is textually identical, so there is no reload between them.
- Rank 0 uses `fallback.embed` and rank 2 uses `resolveApiAssetUrl(host, embedPath)` (592). So when the fast call fails, one iframe reload between rank 0 and a later rank is possible. R6 covers only an unchanged URL.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadata() (506-512) and fetchVideoMetadataFromServer() (517-555)">
**What changes.**
- The sequential "server, else instance" logic in `fetchVideoMetadata` moves into the coordinator.
- `fetchVideoMetadataFromServer` drops `await fetchInstanceMetadata(source.host)` (525). It must now serve both `/api/video` and `/api/video/refresh`, through a path argument or a shared mapper; the refresh answers the same shape, so the mapping at 527-551 applies unchanged.

**Precedence, confirmed in code.**
- The Engine always sends `instanceName`/`instanceUrl` as strings (video.py:279-280, possibly `""`), and `??` does not skip `""`. So for ranks 1 and 3, `instanceMeta?.name`/`url` never win today (534-539); the config supplies only `instanceAvatarUrl` (540).
- For rank 2 (608-610), the config's name and URL do win.
- If re-applying the shared config overwrote `instanceName` for ranks 1 and 3, the chip label would visibly change from the host to the display name. It would also change `resolveLikeHost` when `seedHost` is empty.

**Other effects.**
- `catch { return null; }` (552-554) also swallows `response.json()` failures and non-OK statuses. The refresh caller needs its own failure signal to `console.warn`.
- `instanceAvatarUrl` must be merged in from the shared promise on every render, or it disappears when a later rank re-renders.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadataFromInstance() (560-625) and fetchChannelMetadata() (630-650)">
**What changes.** `await fetchInstanceMetadata(source.host)` (600) is replaced by the shared promise. The awaited `fetchChannelMetadata` (599) stays, because it is part of rank 2 itself.

**Behaviour to keep.**
- The rank-2 result has no `videoUuid`, so `resolveLikeUuid` falls back to `seedId` only when `looksLikeUuid` (1171-1173) accepts it.
- `instanceName: instanceMeta?.name ?? source.host` (608) can be `""`, because `getString` returns `""` (724-730). `instanceMetaEl.hidden = !instanceName` (140) then hides the chip. This is pre-existing.
- It runs only after the fast fetch fails (R5). If rank 3 is already shown, the rank rule drops its result, so the coordinator could skip starting it.

**Regression risk: low to medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchInstanceMetadata() (655-688) and getString() (724-730), as one shared promise">
**What changes.** It is called once per load, and the promise is shared.

**What it returns.**
- `getString` returns `""`, never undefined, so the `?? ... ?? host` chain at 664-667 never reaches `host`.
- `avatarUrl` is always set on success, falling back to `https://${host}/favicon.ico`.
- Any failure, including a CORS failure, resolves to `null` and never rejects, so a `.then` needs no `.catch`.

**What depends on it.**
- The instance avatar on every rank, and the name and URL on rank 2.
- When it resolves, the current best metadata is re-rendered at the same rank, so the rank rule must allow equal-rank renders ("at least the rank shown").
- Rank 0 renders with `null` metadata, so if the avatar should appear there, it has to be applied in `renderVideo` from a module variable, not merged into the metadata object.

**Constraint.** It may start only once a host is known.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadReaction() (318-341), reactionVideo() (381-386), react()/renderReaction() (346-364)">
**What changes.** A module-level `uuid|host` key for the last reaction fetched gates `fetchReaction`.

**How the gate must work.**
- **Non-null video only.** `reactionVideo()` depends on `currentMetadata`. On a rank-0 or rank-2 render with a non-UUID `seedId` it returns `null`, and `loadReaction` returns at 320 without wiring the buttons. A later rank that carries `videoUuid` (1 or 3) must still fetch and wire, so the key is set only when `video` is non-null.
- **Before the first await.** `await localLikesImported` (322) comes before the fetch, so the key must be written before that first `await`. Otherwise two quick renders both pass the gate and fetch twice.
- **Listeners.** The listeners (331-340) capture the first non-null `video` and are never rewired, because of `likeButton.dataset.wired` (327). This is unchanged.

**What depends on it.** `renderReaction` and `setReactionStatus`. `tests/active/test_frontend_reactions.py` exercises `data/reactions.ts`, not this page.

**Regression risk: medium.** A wrong gate either breaks R6 (a second fetch) or leaves the buttons disabled when the uuid arrives only with a later rank.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="enableBlockButtons() (275-308)">
**What changes.** Nothing. The `button.dataset.wired` guard (282) makes re-renders no-ops.

**What depends on it.**
- It captures `uuid` and `host` from the first call where both are non-empty.
- On a rank-0 render, `metadata?.videoUuid || resolveVideoSource()?.id` (196) is `seedId`, which may be a numeric id, and the buttons keep it for good.
- That already happens today when `/api/video` fails. It is more reachable now, if the fast call fails and the refresh brings the real uuid later.
- I did not trace whether `blockVideoSource` resolves a numeric id.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadSimilarVideos() (234-269) and the similar stats helpers">
**What changes.** Nothing (R7). It waits only on `localLikesImported` and never on metadata.

**Regression risk: none,** as long as the coordinator neither awaits it nor chains it.
</impact>
<impact path="client/frontend/video-page.html" element="CSP meta (line 8)">
**What changes.** Nothing.

**What depends on it.**
- `connect-src 'self' https:` already allows the same-origin `/api/video/refresh` and the browser→instance fetches.
- `frame-src https:` matches the embed's `https://` check.

**Regression risk: none.**
</impact>
<impact path="client/frontend/dist/assets/video-gjYm1MC8.js" element="built video page bundle (build output)">
**What changes.** The build regenerates it under a new hash; it is never edited by hand.

**What depends on it.** The deployed static site serves `dist`.

**Regression risk: low.** A stale `dist` deployed against the new Engine still works, because `/api/video` keeps its shape. It just no longer gets live values or the account avatar.
</impact>
<impact path="client/frontend/vite.config.ts" element="dev server proxy '/api' (lines 27-28)">
**What changes.** Nothing. The `/api` prefix already covers `/api/video/refresh` in dev.

**Regression risk: none.** I did not check whether a dev proxy timeout is set.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="frontend gateway preflight (lines 22-38)">
**What changes.** Nothing. It forbids only:
- Engine base usage;
- hard-coded Engine ports;
- `/internal/*` routes in `client/frontend/src`.

A `/api/video/refresh` literal passes.

**Regression risk: none.**
</impact>
<impact path="DEPLOYMENT.md" element="nginx `location /api/` (319-325); ufw prose (369, 374-375)">
**What changes.**
- **nginx block.** Needs nothing. `location /api/` already proxies `/api/video/refresh`, and no `proxy_read_timeout` is set, so nginx's 60 s default exceeds 20 s.
- **ufw comment (369).** "live video metadata" stays true.
- **Prose at 374-375.** "`/api/video` makes live calls to source instances per request" becomes wrong (see the docs checklist).

**Regression risk: none in config.**
</impact>
<impact path="tests/active/conftest.py" element="engine fixture (105-140) over WHITELIST_DB (34); ENGINE_PY (32); ENGINE_SERVER (33); CLOSED_ENGINE (45)">
**What changes.** Nothing.

**What new tests must avoid.**
- A refresh through the session `engine` fixture would make real outbound HTTPS calls and write to the shared `whitelist.db`.
- Refresh tests and the R7 test must run the handler in an `ENGINE_PY` child over a temporary DB, with `handlers.video.fetch_instance_json` patched.
- Precedents: `test_internal_client_reads.py:144-145`, `test_internal_events.py:52,174`, and the child runs in `test_similar.py` (237, 307, 415, 533).
- A fast `/api/video` against the shared Engine is safe after the build (no calls, no writes).

**Regression risk: medium for test hygiene.**
</impact>
<impact path="tests/active/test_server.py" element="_serving/_client_backend/_status/EngineStub pattern (lines 347-422)">
**What changes.** Nothing. It is the template for the new proxy test.

**The new test.** A stub Engine counts GETs and sleeps past a monkeypatched timeout on `/api/video/refresh`. It checks two things:
- the refresh makes one attempt;
- `/api/video` still retries once.

**Test group.** The file maps to `client/backend/server.py` and `engine/server/api/handlers/similar.py` in `.un/skills/devsecops/config.json` (57-60).

**Regression risk: low.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups mapping">
**What changes.** Nothing during the build.

**Coverage gaps.** Grep finds no mapping for `engine/server/api/handlers/video.py` or `client/frontend/src/pages/video-page/index.ts`. Any new test file for them needs an entry at harvest, or it runs only in full-suite runs.

**Regression risk: low.**
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="client_video_proxy check (line 582); also tests/run-installers-smoke.sh (line 647) and README.md line 134">
**What changes.** Nothing is required: `/api/video` still answers 200, and faster.

**Optional.** A `/api/video/refresh` check would depend on outbound 443, so asserting "200 or 502" is safer.

**Regression risk: none.**
</impact>
<impact path="docs/project/security-audit/run-1/REPORT.md" element="line 299 (`/api/video` performs up to two outbound HTTPS requests); also run-1/architecture.md:35,67, run-1/FINDINGS-DETAIL.md:127, run-2/REPORT.md:73,125,221, run-2/FINDINGS-DETAIL.md:12,136, run-2/findings.json">
**What changes.** Nothing. These are dated audit records and are not rewritten. I list them only because a grep for `/api/video` hits them and they describe the old behaviour.

**Regression risk: none.**
</impact>
<impact path="docs/project/plans/19-11-fast-similars-response.record.md" element="workflow record for this build">
**What changes.** The workflow renders it; do not hand-edit it. It already holds an earlier step-3 pass. I re-read the files it names, and its line numbers still match the tree.

**Regression risk: none.**
</impact>
</impacts>

## Documentation to update

- [x] `engine/server/README.md` - updated: `engine/server/README.md`: the `/api/video` entry is updated, a `/api/video/refresh` entry is added, the write-back rule is documented, and the "read-only" claim on line 3 is corrected.
- [x] `README.md` - updated: Added `/api/video/refresh` to two rows of the boundary table: the Engine public read API and the Client read gateway.
- [x] `client/README.md` - updated: Added `/api/video/refresh` to the Client read gateway list and described how its proxy differs from the other reads (allow-list, 20 s, no retry, 502 when it times out).
- [x] `docs/project/issues/10-video-metadata-completeness.md` - updated: Added a comment to issue 10 about the metadata write path, merge rules and persist-on-success behaviour that issue 11 delivered. Body and `Status:` are unchanged.
- [x] `docs/project/roadmap.md` - updated: Added `/api/video/refresh` to F2-M3's list of routes that still need versioning.
- [x] `docs/project/issues/11-fast-similars-response.md` - updated: Added a partial-delivery comment to issue 11. Status and location unchanged: the issue stays open in `docs/project/issues/`.
- [x] `client/frontend/README.md` - out of scope: No frontend phase landed: `client/frontend/src/pages/video-page/index.ts` was not touched, and the page does not call `/api/video/refresh`. Line 8's list of routes the frontend fetches (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`) is still exactly right, and the page loads in the same order as before. The checklist's addition and its load-order sentence belong to the follow-up plan that builds the page coordinator.
- [x] `DEPLOYMENT.md` - out of scope: Lines 374-375 ("`/api/video` makes live calls to source instances per request") are still true. `/api/video` was kept live in this build; only the follow-up plan makes it DB-only. The sentence's point, that outbound 443 is a runtime dependency, also still holds. The ufw comment at 369 ("live video metadata") is true. The nginx `location /api/` block already covers `/api/video/refresh`, and its default 60 s read timeout is longer than the 20 s proxy budget.
- [x] `docs/project/issues/20-request-lifecycle-logs.md` - out of scope: Line 25 names `/api/video` in the smoke list for start→end request logs. That route still exists and is still the long-running call bound to the instance, because it was kept live. This future-work spec says nothing that is now false. Adding `/api/video/refresh` would be a scope choice for whoever plans issue 20, not a correction.

## Implementation plan

## Draft implementation: two-phase video metadata (issue 11)

### Module map

| File | Change |
|---|---|
| `engine/server/api/handlers/video.py` | `fetch_instance_video_dynamic` returns `{}` on a failed detail call. `handle_video_request` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`. `handle_video_request` (DB only) keeps its name; `handle_video_refresh_request` is new. Module docstring updated. |
| `engine/server/api/handlers/similar.py` | Import gains `handle_video_refresh_request`. New `/api/video/refresh` dispatch branch. Docstring route list updated. |
| `engine/server/api/handlers/__init__.py` | Docstring line 5 names both routes. |
| `client/backend/server.py` | Route and allow-list entries. Two per-path mappings (timeout, retry count), read at four sites in `_proxy_engine_request`. |
| `client/frontend/src/pages/video-page/index.ts` | `loadVideo` → `renderVideo(metadata)`. Coordinator `startVideoLoad` with rank arbitration. Shared instance-config promise. Embed and reaction guards. `fetchVideoMetadataFromServer(path, source)`. `fetchVideoMetadata` removed. |
| Docs | `engine/server/README.md`, `README.md`, `client/README.md`, `client/frontend/README.md`, `DEPLOYMENT.md`, issue/roadmap comments, per the settled checklist. |

`dist/` is regenerated by the build.

---

### Engine: `engine/server/api/handlers/video.py`

**Module docstring**

```python
"""Video metadata endpoint handlers.

Responsibilities:
- Resolve video row by id/uuid/host.
- /api/video: answer from the DB row only, with no instance call and no write.
- /api/video/refresh: fetch live instance metadata, merge it over the row field by field, persist it when the instance answered, and answer the same shape.
"""
```

**New imports**, in the file's existing style:

```python
from data.db import statement_deadline
from server_config import DEFAULT_STATEMENT_TIMEOUT_SECONDS
```

**`fetch_instance_video_dynamic`: success signal.** Only line 164 changes; the rest of the function is untouched.

```python
    detail = fetch_instance_json(host, f"/api/v1/videos/{quote(video_id)}")
    # An empty dict tells the caller the instance did not answer, so nothing is persisted.
    if not isinstance(detail, dict) or not detail:
        return {}
```

- Invariant: it returns `{}` if and only if the detail call failed or came back as a non-dict or empty JSON value. Otherwise it returns today's 14-key dict.
- A non-dict JSON body no longer reaches `detail.get` and raises `AttributeError`.
- The channel sub-call now runs only on success. When it fails, the channel fields fall back to the DB in the merge, and the result still counts as success.

**`resolve_video_row`**, which takes lines 210-224 and 226:

```python
def resolve_video_row(
    handler: Any,
    server: Any,
    params: dict[str, list[str]],
) -> tuple[dict[str, Any], str, str] | None:
    """Resolve the requested row, or answer 400/404 and return None.

    Returns the row, the requested id and the instance domain the merge and refresh use.
    """
    id_param = params.get("id", params.get("video_id", [None]))[0]
    host_param = params.get("host", params.get("instance_domain", [None]))[0]
    if not id_param:
        respond_json(handler, 400, {"error": "Missing video id"})
        return None
    with server.db_lock:
        row = fetch_video_row(
            server.db,
            id_param,
            host_param,
            error_threshold=server.video_error_threshold,
        )
    if not row:
        respond_json(handler, 404, {"error": "Video not found"})
        return None
    instance_domain = row.get("instance_domain") or host_param or ""
    return row, id_param, instance_domain
```

The lock covers the SELECT only.

**`merge_video_metadata`**, which takes lines 229-290 verbatim:

```python
def merge_video_metadata(
    row: dict[str, Any],
    dynamic: dict[str, Any],
    instance_domain: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge live `dynamic` fields over the DB row, field by field.

    Returns the response payload and the merged column values the persist step writes.
    An empty `dynamic` gives the DB-only answer.
    """
    # lines 229-290 unchanged: title … nsfw, channel_url, embed_url, original_url, response
    merged = {
        "title": title,
        "description": description,
        "channel_display": channel_display,
        "channel_slug": channel_slug,
        "channel_followers": channel_followers,
        "views": views,
        "likes": likes,
        "dislikes": dislikes,
        "tags_json": tags_json,
        "category": category,
        "nsfw": nsfw,
    }
    return response, merged
```

- **The impact inventory's open point.** `merged` carries the raw intermediates, `None` included, so persist writes `NULL` where today's code writes `NULL` and never the response's `""`.
- The function is pure: no DB access and no I/O.
- With `dynamic={}`, every `dynamic.get` is `None`, so each field falls back to the row exactly as today, and `accountAvatarUrl` is `""`.

**`persist_video_metadata`**, which takes lines 294-358:

```python
def persist_video_metadata(
    server: Any,
    row: dict[str, Any],
    instance_domain: str,
    merged: dict[str, Any],
) -> None:
    """Write a successful refresh to the videos, channels and instances tables.

    The writes run under a fresh statement budget taken once the DB lock is held, because the request's own budget is mostly spent on the instance calls by then.
    """
    checked_at = now_ms()
    popularity = compute_popularity(
        merged["views"],
        merged["likes"],
        row.get("published_at"),
        float(getattr(server, "popularity_like_weight", 2.0)),
        now_ms_value=checked_at,
    )
    channel_id = row.get("channel_id")
    try:
        with server.db_lock:
            with statement_deadline(
                float(getattr(server, "statement_timeout_seconds", DEFAULT_STATEMENT_TIMEOUT_SECONDS))
            ):
                with server.db:
                    # today's three UPDATEs, parameters read from `merged` and `row`, unchanged SQL
    except sqlite3.OperationalError as exc:
        logging.warning(
            "[video] failed to persist dynamic metadata for video_id=%s host=%s: %s",
            row.get("video_id"),
            instance_domain,
            exc,
        )
```

- **Why the nested deadline.** The settled db.py entry picks this mitigation. Without it the outer deadline has usually expired after roughly 16 s of instance calls, and the FTS trigger's UPDATE could be interrupted, which silently breaks R2's persist.
- **Why it sits inside `db_lock`.** Time spent waiting for the lock does not use up the new budget.
- **Nesting is safe.** `statement_deadline` restores the outer deadline on exit (db.py:59-64).
- **The rest is today's code.** The SQL, the parameter order, the `channels` UPDATE only when `channel_id` is set, the `instances` reset, and the catch-and-log.

**Route handlers**

```python
def handle_video_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Handle /api/video: answer from the DB row only, with no instance call and no write."""
    resolved = resolve_video_row(handler, server, params)
    if resolved is None:
        return True
    row, _id_param, instance_domain = resolved
    response, _merged = merge_video_metadata(row, {}, instance_domain)
    respond_json(handler, 200, response)
    return True


def handle_video_refresh_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Handle /api/video/refresh: fetch live metadata, persist it when the instance answered, answer the merge.

    This is the single per-request metadata write path; issue 10 extends it.
    """
    resolved = resolve_video_row(handler, server, params)
    if resolved is None:
        return True
    row, id_param, instance_domain = resolved
    # The instance calls run outside the DB lock, so a slow instance never stalls other routes.
    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else {}
    response, merged = merge_video_metadata(row, dynamic, instance_domain)
    if dynamic and instance_domain and row.get("video_id"):
        persist_video_metadata(server, row, instance_domain, merged)
    respond_json(handler, 200, response)
    return True
```

- Keeping the name `handle_video_request` means the import at similar.py:84 cannot break.
- The `if dynamic` guard is now meaningful, because a failed fetch returns `{}`.

### Engine: `engine/server/api/handlers/similar.py`

- **Line 84:** `from handlers.video import handle_video_refresh_request, handle_video_request`.
- **After line 497:**
  ```python
          if url.path == "/api/video/refresh":
              handle_video_refresh_request(self, self.server, params)
              return
  ```
- **Docstring lines 9-10:**
  - `- /api/video: single video metadata from the local DB (no instance call).`
  - `- /api/video/refresh: live instance refresh of one video's metadata, persisted on success.`
- **Unchanged:** the rate limit at 447 (its own `ip:/api/video/refresh` bucket), the statement deadline in `do_GET`, and the similars dispatch.

### Engine: `engine/server/api/handlers/__init__.py`

Line 5 becomes: `- video: /api/video (DB only) and /api/video/refresh (live instance refresh, persisted on success).`

---

### Client backend: `client/backend/server.py`

**Constants**, next to lines 77-101:

```python
ENGINE_PROXY_TIMEOUT_SECONDS = 10
# The refresh waits on up to two 8 s instance calls in the Engine, and a retry would repeat them and the write.
ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS: dict[str, float] = {"/api/video/refresh": 20}
ENGINE_PROXY_MAX_BODY_BYTES = 1_000_000
ENGINE_PROXY_RETRY_COUNT = 1
ENGINE_PROXY_ROUTE_RETRY_COUNT: dict[str, int] = {"/api/video/refresh": 0}
ENGINE_PROXY_RETRY_DELAY_SECONDS = 0.25
PROXY_READ_GET_ROUTES = frozenset(
    ("/api/video", "/api/video/refresh", "/api/channels", "/api/v1/search/videos")
)
PROXY_ALLOWED_QUERY_PARAMS: dict[str, set[str]] = {
    ...
    "/api/video": {"id", "host", "refresh_cache", "user_id"},
    "/api/video/refresh": {"id", "host"},
    ...
}
```

The plan asked for "a path check on the retry count". A second one-entry dict does the same job, with the same shape as the timeout mapping and one more place a test can monkeypatch.

**`_proxy_engine_request`.** Two locals are resolved once, from `path` (never from `upstream`, which carries the query string), right after `upstream` is built. The mappings are module globals read at call time, so a test that patches `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` takes effect.

```python
        timeout_seconds = ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS.get(path, ENGINE_PROXY_TIMEOUT_SECONDS)
        retry_count = ENGINE_PROXY_ROUTE_RETRY_COUNT.get(path, ENGINE_PROXY_RETRY_COUNT)
```

Four sites change:

| Line | Before | After |
|---|---|---|
| 604 | `range(ENGINE_PROXY_RETRY_COUNT + 1)` | `range(retry_count + 1)` |
| 606 | `timeout=ENGINE_PROXY_TIMEOUT_SECONDS` | `timeout=timeout_seconds` |
| 696 | `attempt < ENGINE_PROXY_RETRY_COUNT` | `attempt < retry_count` |
| 731 | `"attempts": ENGINE_PROXY_RETRY_COUNT + 1` | `"attempts": retry_count + 1` |

- Every other route keeps 10 s and one retry.
- `_handle_engine_read_proxy_get` and `_profile_filter` are unchanged. The refresh gets the same sanitising: an unknown or repeated key answers 400, and a `user_id` or `refresh_cache` on it now answers 400 too.

**How a failed refresh reaches the browser:**
- a timeout breaks the loop with 0 retries → 502 `ENGINE_PROXY_UNAVAILABLE`;
- a dropped Engine connection → 502 `ENGINE_PROXY_FAILURE`;
- an Engine 400 or 404 → passed through.

The page treats all of these as a failed refresh.

---

### Frontend: `client/frontend/src/pages/video-page/index.ts`

**Module state.** These lines go next to `currentMetadata` (line 50-51). They must be declared before the coordinator call at line 79: the no-source path renders synchronously, and a `let` declared later would throw a TDZ error.

```ts
type InstanceMetadata = Awaited<ReturnType<typeof fetchInstanceMetadata>>;
// Which metadata source the panel shows; a source renders only if it ranks at least as high.
const METADATA_RANK = { params: 0, fast: 1, instance: 2, refresh: 3 } as const;
let shownRank = -1;
let instanceConfig: InstanceMetadata = null;
let instanceMetadata: Promise<InstanceMetadata> = Promise.resolve(null);
let lastEmbed = "";
let reactionKey = "";
```

**Start (line 79).** `void loadVideo();` becomes `startVideoLoad();`. Line 80, `void loadSimilarVideos();`, is unchanged, and the coordinator neither awaits nor chains it.

**Coordinator**

```ts
/**
 * Start the three metadata sources at once: the Engine's DB answer, its live refresh, and the instance config. None awaits another.
 */
function startVideoLoad() {
  const source = resolveVideoSource();
  if (!source?.host || !source.id) {
    offerMetadata(METADATA_RANK.params, null);
    return;
  }
  instanceMetadata = fetchInstanceMetadata(source.host);
  void instanceMetadata.then((meta) => {
    instanceConfig = meta;
    if (meta && shownRank >= 0) renderVideo(currentMetadata);
  });
  void loadFastMetadata(source);
  void loadRefreshedMetadata(source);
}

/**
 * Render `metadata` unless a higher-ranked source is already shown, so a late fast answer never overwrites refreshed values.
 */
function offerMetadata(rank: number, metadata: VideoMetadata | null) {
  if (rank < shownRank) return;
  shownRank = rank;
  renderVideo(metadata);
}

/**
 * Show the Engine's stored metadata, or the URL params and then the instance's own answer when the Engine has no row.
 */
async function loadFastMetadata(source: { host: string; id: string; url: string }) {
  const metadata = await fetchVideoMetadataFromServer("/api/video", source);
  if (metadata) {
    offerMetadata(METADATA_RANK.fast, metadata);
    return;
  }
  offerMetadata(METADATA_RANK.params, null);
  if (shownRank > METADATA_RANK.instance) return;
  const instanceMeta = await fetchVideoMetadataFromInstance(source);
  if (instanceMeta) offerMetadata(METADATA_RANK.instance, instanceMeta);
}

/**
 * Show live metadata once the Engine has refreshed it; a failure keeps what the panel shows.
 */
async function loadRefreshedMetadata(source: { host: string; id: string; url: string }) {
  const metadata = await fetchVideoMetadataFromServer("/api/video/refresh", source);
  if (!metadata) {
    console.warn("[video] metadata refresh failed; keeping the values shown");
    return;
  }
  offerMetadata(METADATA_RANK.refresh, metadata);
}
```

- **No-source path.** It renders once with `null`, with no fetch and no config, exactly as today.
- **Equal ranks re-render.** Equal-rank renders are allowed, which is what lets the config's re-render at the current rank through.
- **`currentMetadata` stays in step.** It is set only inside `renderVideo`, so it always equals what is shown, and the config re-render reuses it.
- **Skipped fallback.** If the refresh is already shown, the direct-instance fallback is not started at all.

**`renderVideo(metadata: VideoMetadata | null)`.** This is today's `loadVideo` body without `await fetchVideoMetadata()`, and it is synchronous. Line 87 stays as the first statement: `currentMetadata = metadata;`. Three edits:

1. **Instance avatar** (line 109) is taken from the shared config at render time, so it survives every re-render and also reaches rank 0:
   `const instanceAvatarUrl = metadata?.instanceAvatarUrl || instanceConfig?.avatarUrl || "";`
2. **Embed** (lines 212-221). The comparison is against our own last assigned string, and the guard is cleared when `src` is removed:
   ```ts
   if (embedEl) {
     // The embed URL can come straight from the `?embed=` query parameter when metadata resolution fails, so a scheme check is what stops a `javascript:` URL from executing in this origin via iframe navigation.
     const checkedEmbed = embed && /^https:\/\//i.test(embed.trim()) ? embed : "";
     if (!checkedEmbed) {
       embedEl.removeAttribute("src");
       lastEmbed = "";
     } else if (checkedEmbed !== lastEmbed) {
       // Reassigning an unchanged src would restart playback on every re-render.
       embedEl.src = checkedEmbed;
       lastEmbed = checkedEmbed;
     }
   }
   ```
3. **Everything else is unchanged:** `escapeHtml`/`safeExternalUrl` on every write, the `enableBlockButtons(...)` call (its `dataset.wired` guard makes re-renders no-ops), and `void loadReaction()`.

**`loadReaction` gate.** The key is written only for a non-null video, and before the first `await`:

```ts
async function loadReaction() {
  const video = reactionVideo();
  if (!video || !likeButton || !dislikeButton) return;
  // Re-renders call this again; the visitor's reaction is read once per video.
  const key = `${video.uuid}|${video.host}`;
  if (key === reactionKey) return;
  reactionKey = key;
  try {
    await localLikesImported;
    ...unchanged
```

A rank-0 render with a non-UUID `seedId` returns `null` and leaves the gate open, so a later rank that carries `videoUuid` still fetches and wires the buttons.

**`fetchVideoMetadataFromServer(path, source)`**

- Signature: `async function fetchVideoMetadataFromServer(path: string, source: { host: string; id: string; url: string }): Promise<VideoMetadata | null>`.
- `new URL(path, apiBase)`, with only `id` and `host` set, as today. The refresh allow-list accepts exactly these.
- `await fetchInstanceMetadata(source.host)` (line 525) is removed.
- The instance fields become:
  ```ts
  instanceName: (data.instanceName as string | undefined) ?? source.host,
  instanceUrl: (data.instanceUrl as string | undefined) ?? `https://${source.host}`,
  instanceAvatarUrl: "",
  ```
  The Engine always sends both as strings (video.py:279-280), so `instanceMeta?.name`/`url` could never win here today. Dropping them keeps what is visible, and the avatar now comes from `instanceConfig` in `renderVideo`.
- `catch { return null; }` is unchanged. `null` is the failure signal both callers use.

**`fetchVideoMetadataFromInstance`.** Line 600 becomes `const instanceMeta = await instanceMetadata;`, which awaits the shared promise instead of issuing a second `/api/v1/config` request. The effect on R4:
- This source ranks 2 and runs only after rank 0 has rendered, so the wait is never on the first-render path.
- It keeps today's rank-2 precedence exactly, with the config's name and URL winning.

**Removed:** `loadVideo` and `fetchVideoMetadata`, whose sequencing moved into the coordinator. `loadSimilarVideos` and the similars helpers are untouched (R7).

---

### What the build needs to test

**Engine: new `tests/active/test_video_metadata.py`.** Each case runs in an `ENGINE_PY` child over a temporary DB, following `test_internal_events.py:52` / `test_similar.py`. The child uses a real `SimilarServer` with `db`, `db_lock`, `video_error_threshold`, `popularity_like_weight` and `statement_timeout_seconds`. The patch goes on `handlers.video.fetch_instance_json`, never the shared `engine` fixture.
- **Fast route.**
  - `/api/video` answers the DB fields with the shape unchanged, `accountAvatarUrl == ""`, the channel URL built from slug + host, and the original URL built from uuid + host.
  - The stub is never called.
  - `last_checked_at` and `instances.last_error` are unchanged.
- **Errors on both routes.** 400 `Missing video id` and 404 `Video not found`.
- **Successful refresh.** It answers the instance values, including `accountAvatarUrl`. The `videos`, `channels` and `instances` rows are updated, with `last_error*` set to NULL. A failed channel sub-call still persists, with the DB channel fields.
- **Failed refresh.** Detail `None`, `{}`, a JSON list and a raised `URLError` each answer 200 with DB values and change no row.
- **Deadline.** With `statement_timeout_seconds` around 0.2 and a stub that sleeps 0.5 s, a successful refresh still persists.
- **R7.**
  - Setup: a stub that blocks about 5 s, and a refresh started on a thread.
  - The id-based similars GET is answered in well under 5 s.
  - The stub's call log holds only the refresh's paths.

**Client proxy: added to `tests/active/test_server.py`,** using `EngineStub`, `_serving`, `_client_backend` and `_status`:
- `/api/video/refresh` forwards `id`/`host` and answers 400 on `user_id`, `refresh_cache` or a repeated key;
- with both mappings patched to a small timeout, a sleeping stub sees exactly one refresh GET and the browser gets 502;
- `/api/video` against a sleeping stub still makes two attempts;
- `/api/video` keeps the 10 s default (assert the mapping lookup).

**Frontend: new `tests/active/test_frontend_video_page.py`.** The page is bundled with esbuild (`--platform=node`, css loader `empty`) and driven with a stubbed `document`/`window`/`localStorage` and a scripted `fetch`, following `test_frontend_blocks.py`. It asserts:
- the first render happens before `/api/v1/config` resolves;
- whichever of refresh and fast arrives first, the refreshed values end up shown;
- a failed refresh keeps the values shown and calls `console.warn`;
- a fast 404 renders the URL params, then the instance data;
- `src` is assigned once across the rank 1 → 3 renders;
- `fetchReaction` is called once;
- a `javascript:` embed is never assigned;
- similars are fetched with `limit=8` regardless of metadata timing.

If the stubbing proves too heavy, the plan's own escape hatch applies: extract `offerMetadata`'s rank rule into a lib module.

**At harvest:** `.un/skills/devsecops/config.json` maps the new files to `video.py`, `similar.py`, `server.py` and `video-page/index.ts`.

---

### Check against the plan and requirements

This took two passes; the first found gaps and the second closed them.

| Item | Met by |
|---|---|
| R1 | `merge_video_metadata(row, {}, …)`, no fetch, no write. 400/404 through the shared resolver. |
| R2 | Separate route and handler. Same resolver. `fetch_instance_video_dynamic` unchanged except the success signal. Persist only when `dynamic` is non-empty, with today's SQL and catch. Same response shape. The proxy's own allow-list `{id, host}`. |
| R3 | Three independent starts. The rank rule keeps refreshed values over a late fast answer. A failed refresh is `console.warn` only. |
| R4 | No first-render path awaits `/api/v1/config`. The avatar fills in through the shared promise's re-render. The chip uses host initials until then. |
| R5 | Fast failure renders rank 0 at once, then rank 2. The `https://` check sits inside `renderVideo`, which every path passes through. |
| R6 | `lastEmbed` guard. `dataset.wired` guards unchanged. `reactionKey` gate written before the first await. Escaping unchanged. |
| R7 | Similars code untouched. The instance calls run outside `db_lock`. Covered by the Engine R7 test. |
| Budget constraint | 20 s, no retry, refresh only. A proxy failure degrades per R3. |
| Stdlib / style / dist | Stdlib only. No new dependency. Module-level functions in the files' style. `dist` rebuilt. |

**What pass 1 missed, and pass 2 fixed:**
- **Persist intermediates.** Solved by returning a `merged` dict instead of feeding persist from the response.
- **Persist under an expired deadline.** Nested `statement_deadline` inside `db_lock`.
- **TDZ.** The coordinator's state is declared before line 79.
- **Reaction gate.** Written before the `await` and only for a non-null video.
- **Line 731 log.** Now uses `retry_count`.

### Named simplifications and residual limits

- **Rank rule is one number.** It has no per-field merge: a higher-ranked source replaces the whole panel. That is enough because the refresh answers a superset of the fast answer. The ceiling: a future partial refresh would need per-field precedence.
- **Refresh failure is a bare `null`.** The console warning carries no reason; the status can be logged later if diagnosis needs it.
- **Engine's late write after a Client timeout.** `respond_json` writes to a closed socket and prints a `BrokenPipeError` traceback. This is pre-existing log noise and is left as is; the persist has already run.
- **Different uuid on a later render.** The reaction and block listeners keep the first video they captured. If a later rank reported a different uuid, which should not happen for one row, the reaction is re-read for the new key but clicks still act on the first video. This is unchanged from today.
- **Deviations from the settled plan text, both taken from the settled impacts.**
  - Persist gains a nested statement deadline; the plan said "unchanged".
  - The rank-2 fallback awaits the shared config promise rather than not awaiting it at all. This keeps today's rank-2 name/URL precedence and stays off the first-render path.


### Phases

#### Phase 1 - Engine refresh route [code]

**Files touched.** engine/server/api/handlers/video.py (EDITED), engine/server/api/handlers/similar.py (EDITED), engine/server/api/handlers/__init__.py (EDITED), tests/active/test_video_metadata.py (NEW)

**Checkpoint.** Seam: the Engine's HTTP handler over a real DB. New `tests/active/test_video_metadata.py` runs each case in an `ENGINE_PY` child over a temporary DB, following the `subprocess.run([str(ENGINE_PY), "-c", CHILD, ...], cwd=API_DIR)` pattern of `test_similar.py` / `test_internal_events.py`. The child builds a real `SimilarServer` carrying `db`, `db_lock`, `video_error_threshold`, `popularity_like_weight` and `statement_timeout_seconds`, and patches `handlers.video.fetch_instance_json` with a recording stub (never the shared `engine` fixture). It asserts over GET `/api/video/refresh`: (a) with the stub answering detail + channel JSON, the response carries today's response keys with the instance's values, `accountAvatarUrl` included, the channel URL built from slug + host and the original URL from uuid + host. (b) With the detail JSON omitting fields (e.g. no `description`, no `tags`) and the channel sub-call answering `None`, those fields and the channel fields come from the seeded DB row. Guards: 400 `Missing video id` with no id, and 404 `Video not found` for an unknown id; and `/api/video` against the same answering stub still returns the instance's values (today's live behaviour kept until the follow-up plan).

**Intent.** `engine/server/api/handlers/video.py` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`, and a new `handle_video_refresh_request`, dispatched from `SimilarHandler`'s GET branch in `similar.py`, answers `/api/video/refresh` with the instance's live values merged over the DB row field by field, while `/api/video` keeps today's live behaviour through the same functions.

- C1 - `/api/video/refresh` answers the instance's live values in today's `/api/video` response shape.
- C2 - A field the instance did not supply in a refresh falls back to the DB row's value.

**Outcome.** ### engine/server/api/handlers/video.py
- `handle_video_request` is split into three module-level functions. The merge rules and SQL are the same as before; only their location changed.
  - `resolve_video_row(handler, server, params)` reads `id`/`video_id` and `host`/`instance_domain` and answers 400 `Missing video id` or 404 `Video not found`. Otherwise it returns `(row, id_param, instance_domain)`. `db_lock` is still held only around the SELECT.
  - `merge_video_metadata(row, dynamic, instance_domain)` returns `(response, merged)`. `response` has the same eighteen `/api/video` keys as before, and a field the instance left out falls back to the row, field by field. Title and description use `or`; the numbers use `is None`, so a supplied `likes: 0` is kept. `merged` holds the raw values (`None` included), so the write stores `NULL` rather than the response's `""`.
  - `persist_video_metadata(server, row, instance_domain, merged)` holds the three UPDATEs (videos, channels, instances), the popularity calculation and the logged `sqlite3.OperationalError` catch. It reads its values from `merged`. The argument order follows the Step 5 draft, so Phase 2 can add its statement deadline there.
- New `handle_video_refresh_request` runs resolve, then `fetch_instance_video_dynamic` (by the requested id, outside the lock), then merge, then persist under the same `if dynamic and instance_domain and row.get("video_id")` guard as before, then answers 200.
- `handle_video_request` keeps its name and passes the request to `handle_video_refresh_request`, so `/api/video` behaves as before: it calls the instance live and writes to the DB.
  - A `rat-tail:` comment says what's left: `/api/video` still makes the instance call and the write, and the follow-up plan makes it DB-only by answering `merge_video_metadata(row, {}, instance_domain)` with no fetch and no write.
  - Phase 1 did not touch the `{}`-on-failed-detail success signal in `fetch_instance_video_dynamic`; that is Phase 2's clause.
- Module docstring updated to cover both routes and the persist step.

### engine/server/api/handlers/similar.py
- The import now reads `from handlers.video import handle_video_refresh_request, handle_video_request`.
- New branch in `_dispatch_get`: `if url.path == "/api/video/refresh": handle_video_refresh_request(self, self.server, params)`, placed after the `/api/video` branch. It gets the existing `/api/` rate limit (its own per-path bucket) and the statement deadline in `do_GET`.
- A `/api/video/refresh` line is added to the docstring's list of routes.

### engine/server/api/handlers/__init__.py
- The `video` module line in the docstring now names both routes.

### tests/active/test_video_metadata.py
- Not written. This path is where the gated checkpoint `tests/tmp/test_11_fast_similars_response_phase1.py` gets promoted to; I did not touch the checkpoint or write a copy of it.

### Not run
- I did not run the checkpoint; the workflow's run is the one that counts.
- I expect it to go green because the checkpoint's own probe showed today's `/api/video` returning exactly the expected bodies with the same stubs, and the refresh route now runs that same merge.

### Leftovers in tests/tmp
- The earlier authoring turns left `tests/tmp/probe_11_video_metadata.py` and `tests/tmp/probe_11_remediation.py` in place. I didn't touch them and have no tool to delete them, so they still need removing.

#### Phase 2 - Refresh persists only on instance success [code]

**Files touched.** engine/server/api/handlers/video.py (EDITED), tests/active/test_video_metadata.py (EDITED)

**Checkpoint.** Seam: the same `ENGINE_PY`-child harness in `tests/active/test_video_metadata.py`, going through the HTTP handler and reading the DB afterwards. (a) Persist on success: the stub answers detail JSON, and after `/api/video/refresh` the `videos`, `channels` and `instances` rows hold the instance's values, with `instances.last_error*` NULL. A failed channel sub-call still persists, with the DB channel fields. With `statement_timeout_seconds` about 0.2 and a stub that sleeps 0.5 s before answering, the rows are still updated. (b) No write on failure: parametrized over a detail answer of `None`, `{}`, a JSON list, and a raised `URLError`. Each answers 200 with the DB values, and the `videos`, `channels` and `instances` rows (including `last_checked_at` and `last_error`) are identical before and after. (c) R7: with a stub that blocks about 5 s, a refresh is started on a thread; the id-based similars GET then returns 200 in well under 5 s, and the stub's call log holds only the refresh's `/api/v1/videos/...` paths.

**Intent.** `fetch_instance_video_dynamic` returns `{}` when the video detail call did not answer, so `handle_video_refresh_request` writes the merge through `persist_video_metadata`, under its own statement deadline, only when the instance answered, and its instance calls run outside `db_lock`, so a slow refresh leaves the similars route answering.

- C1 - A refresh updates the videos, channels and instances rows only when the instance's video detail call answered.
- C2 - A refresh blocked on a slow instance does not delay the similars route's answer.

**Outcome.** ### `engine/server/api/handlers/video.py`
- `fetch_instance_video_dynamic` now returns `{}` when the video detail call didn't answer. That covers `None` (which includes `URLError`/`HTTPError`/timeout, since `fetch_instance_json` already catches those), an empty object, and any non-dict JSON. Before, a JSON list crashed on `detail.get` and dropped the connection, and `None` or `{}` produced a dict of `None`s. That dict counts as true, so `handle_video_refresh_request`'s existing `if dynamic and ...` guard went ahead and wrote anyway. Now that guard really does limit the write to refreshes the instance answered (C1). A failed refresh still answers 200 with the DB-only values, through `merge_video_metadata(row, {}, ...)`.
- `persist_video_metadata` now runs its write under its own `statement_deadline(server.statement_timeout_seconds)`, falling back to `DEFAULT_STATEMENT_TIMEOUT_SECONDS`. The deadline is entered just before `db_lock`. The request's deadline from `do_GET` has usually been used up waiting on the instance, so an UPDATE long enough to reach the progress handler used to get interrupted and logged, and nothing was saved. `statement_deadline` puts the request's own deadline back on exit. New imports: `statement_deadline` from `data.db` and `DEFAULT_STATEMENT_TIMEOUT_SECONDS` from `server_config`. `similar.py` already uses both from the same places.
- C2 needed no code change. The instance calls already ran outside `db_lock`: `resolve_video_row` takes the lock only for the row read, and `persist_video_metadata` takes it only for the write. I didn't observe this with a run; the checkpoint run will confirm it.
- I updated the module docstring's persist line to say the write happens only when the detail call answered.

### `tests/active/test_video_metadata.py`
I didn't touch it. It doesn't exist in the worktree yet. I take this to be where the checkpoint (`tests/tmp/test_11_fast_similars_response_phase2.py`) will be moved; it isn't a file for me to write.

#### Phase 3 - Client proxy for the refresh route [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_server.py (EDITED)

**Checkpoint.** Seam: the Client backend's HTTP proxy in front of a stub Engine. Added to `tests/active/test_server.py`, using its `EngineStub(BaseHTTPRequestHandler)` + `_serving(ThreadingHTTPServer(...))` + `_client_backend(tmp_path, engine_base, RateLimiter(1000, 60))` + `_status` harness (precedent: `test_engine_receives_the_resolved_address_as_x_client_ip`). (a) GET `/api/video/refresh?id=…&host=…` reaches the stub with exactly those two params. Adding `user_id`, adding `refresh_cache`, or repeating `id` each answers 400, and the stub records no request. (b) With `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` monkeypatched to about 0.3 s for the refresh and a stub that sleeps past it, the browser gets 502 and the stub counts exactly one refresh GET. Guard: `/api/video` against the same sleeping stub (with `ENGINE_PROXY_TIMEOUT_SECONDS` patched small) counts two attempts.

**Intent.** `client/backend/server.py` proxies `/api/video/refresh` as a read route with its own `{id, host}` allow-list, and `_proxy_engine_request` gives it a 20 s timeout and zero retries through the per-path mappings while every other route keeps 10 s and one retry.

- C1 - The Client forwards `/api/video/refresh` with only `id` and `host`, and refuses any other or repeated query key with 400.
- C2 - A refresh that times out at the proxy is sent to the Engine once and answered 502.

**Outcome.** ### client/backend/server.py
- `/api/video/refresh` added to `PROXY_READ_GET_ROUTES`. It now goes through the same rate limit and the same `_handle_engine_read_proxy_get` sanitising as the other GET read proxies: an unknown key or a repeated key gets 400, and values are stripped.
- New `PROXY_ALLOWED_QUERY_PARAMS["/api/video/refresh"] = {"id", "host"}`. The `/api/video` entry is unchanged and keeps `refresh_cache` and `user_id`.
- Two new per-path mappings sit next to the shared constants, with a one-line comment saying why the refresh differs:
  - `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS = {"/api/video/refresh": 20}`
  - `ENGINE_PROXY_ROUTE_RETRY_COUNT = {"/api/video/refresh": 0}`
- `_proxy_engine_request` looks up `timeout_seconds` and `retry_count` once per request from these mappings. The lookup is keyed on `path`, not `upstream`, which carries the query string. Any path not in a mapping falls back to `ENGINE_PROXY_TIMEOUT_SECONDS` / `ENGINE_PROXY_RETRY_COUNT`. Both are module globals read at call time, which lets a test patch them.
- All four sites that used the shared constants now read the locals: the retry loop's `range`, the `urlopen` timeout, the retry check `attempt < retry_count`, and the `"attempts"` field of the "proxy request unavailable" log.
- Result: the refresh gets 20 s and no retry, and a transport timeout on it is answered 502 `ENGINE_PROXY_UNAVAILABLE` after one send. Every other proxied route still gets 10 s and one retry.


