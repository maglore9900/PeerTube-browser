# 48-translate-instance-captions

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/51-48-translate-instance-captions.record.md`._

## Requirements

### Purpose

A visitor with a profile can follow a non-English video in English. A **Translate** toggle on the video page shows an English line over the embedded player, in time with the video. This build (B1) builds every part except the GPU: the toggle, serving through the Client and Engine, storage, the overlay and its sync. In B1 the only source of English is a caption track that the video's own PeerTube instance already has. B2 adds a second source (Whisper generation: worker in plan 49, connection to the page in plan 50) without changing the display path. Plans 18, 49 and 50 are not in the tree (`docs/project/plans/` has none of them), so this file is self-contained.

### Acceptance criteria

- **AC1: When the toggle shows.** The Translate toggle shows only when the visitor has a profile (`getProfileKey()` in `client/frontend/src/data/profile.ts` returns a key) AND the embed API's `ready` has resolved. Otherwise there is no toggle and no translate request is made. The label is exactly **Translate**, never "CC" or "Captions".
- **AC2: Instance track.** When Translate is on, the Engine reads the instance's caption list (`/api/v1/videos/{id}/captions`) and looks for a track whose `language.id` is English (`en`). If one exists, it fetches the track, validates it as WebVTT, parses it into cues and caches it. The cache key is `(video_id, instance_domain, target_language)`, with `target_language` always `en` and `video_id` the canonical id from the Engine's video row.
- **AC3: Serving.** A Client gateway GET route that requires a profile (`_require_profile`, 401 otherwise) returns the translate state for a video: `ready` or `none`. When the state is `ready`, it also returns the cues, each with start, end and text. The frontend never fetches captions from an instance.
- **AC4: Display.** While Translate is on and the state is `ready`, a layer over `#video-embed` shows the cue that contains the current embed position. It updates during playback and after a seek. Cue text is inserted with `textContent`, never as HTML. When the state is `none`, the page says that no English translation is available for this video.
- **AC5: Persistence.** Translate stays on for later videos until the visitor turns it off. The on/off setting is kept in the browser's `localStorage`, the same way as the NSFW filter (`client/frontend/src/data/feed-params.ts`). There is no Client schema change, and the setting does not follow the profile key to another browser.
- **AC6: Bounds.** Every remote fetch for this feature, meaning both the caption-list read and the track read, goes only to the video's own instance. That instance must be a known whitelisted host, and the rule for that is in the Engine section below. Each fetch is https only, follows no redirect off that host, has a timeout, and is capped at 2 MB per response. A track that doesn't parse as WebVTT is rejected as a whole, never served in part.

### Engine requirements

- A new internal route, `POST /internal/translate`, with a JSON body `{id, host}`, dispatched in `engine/server/api/handlers/similar.py` `_dispatch_post`. It sits behind the existing `/internal/` bridge-token check (`_bridge_authorized`, `X-Bridge-Token`). The handler lives with the other internal client reads (`engine/server/api/handlers/internal_client_reads.py`) or in a sibling handler module.
- Host check: `host` is normalised with `normalize_host` (`engine/server/data/moderation.py:45`). The pair `(id, host)` must resolve to an existing video row in `whitelist.db`, through the existing resolution used by `/api/video` (`resolve_video_row` in `engine/server/api/handlers/video.py`), and the host must not be on the active instance denylist. If either check fails, the route makes no remote fetch.
- Flow: check the cache. On a hit, return the cached `ready` + cues. On a miss, read the caption list, pick an `en` track, fetch it within the AC6 bounds, parse it as WebVTT into cues `{start, end, text}`, store it, and return `{state: "ready", cues}`. Otherwise return `{state: "none"}`.
- The caption path or URL comes from instance JSON. It must resolve to `https://<the same host>`, and anything else is refused (SSRF, R5).
- `fetch_instance_json` (`video.py:82`) follows redirects and has no size cap, so it does not meet AC6. The caption reads use a bounded fetch: https only, a redirect handler that refuses any redirect off the host, the 2 MB cap, and a timeout in line with the existing 8 s.
- `none` is never cached. That covers no English track, a network or HTTP failure, an off-host path, an oversized body and a malformed VTT. This way a track added later, or B2's generation, can still change the answer.
- WebVTT parsing uses only the stdlib and runs once, on the server. A file with no `WEBVTT` header, a bad timestamp, an end before its start, or a cue that otherwise fails to parse rejects the whole track.

### Storage requirements

- A separate SQLite database, `engine/server/db/subtitles.db`, with no `.vtt` files on disk. There is one row per `(video_id, instance_domain, target_language)` key, holding the state, the source (`instance`), the fetched time, the original track text and the parsed cues.
- `.gitignore` already covers `*.db` and its WAL files, so no new ignore rule or directory is needed.
- Plan 49 later adds job states and the `whisper` source to this same DB. The schema must allow that without a rewrite, for example with a source column and a state column.
- A worktree gets its own empty `subtitles.db`, the same way `random-cache.db` is private.

### Client (gateway) requirements

- One new GET route on the Client backend (`client/backend/server.py`) with query params `id` and `host` only. It has an allow-list entry, and unknown or repeated params get 400, matching the existing proxy rules. It is rate-limited like the other reads.
- It calls `_require_profile` before anything else (one 401 for every failure).
- It reaches the Engine through `client/backend/lib/engine_api_client.py`, as a POST to `/internal/translate` with `bridge_headers()`, the same pattern as `/internal/videos/resolve`. The generic `_proxy_engine_request` does not send the bridge token and is not used for this route. An Engine failure is answered as a fixed-text 502 (`_respond_engine_failure`).
- The response is `{state: "ready", cues: [{start, end, text}]}` or `{state: "none"}`.

### Frontend requirements

- Add `@peertube/embed-api` as an npm dependency in `client/frontend/package.json`, bundled by Vite (Q2, decided).
- The embed URL set on `#video-embed` (`client/frontend/src/pages/video-page/index.ts`, `metadata.embedUrl` or the `?embed=` fallback) gets `api=1`, appended correctly whether or not the URL already has a query string. The iframe keeps `sandbox="allow-scripts allow-same-origin"` (`client/frontend/video-page.html:36`).
- Create a `PeerTubePlayer` on `#video-embed`. Show the toggle only after `ready` resolves and a profile exists (AC1). If `ready` never resolves, there is no toggle (R1).
- On toggle-on, or when a page loads with Translate already on, request the state from the Client gateway with `profileHeaders()`. On `ready`, subscribe to `playbackStatusUpdate` and show the cue that contains the position. Polling `getCurrentPosition()` is a fallback only.
- The overlay's CSS goes in `client/frontend/src/video.css`.
- The build must check the case where a page loads with Translate already on (R6: in S0 the overlay once worked only after a reload, cause unknown).

### Consistency constraints

- The frontend talks only to the Client gateway. The Client reaches the Engine only over the existing bridge pattern and its token auth.
- Remote fetches reuse `normalize_host` and the https-only rule.
- New code follows the style of the file it lands in, and each paragraph or statement is kept on one line.

### Out of scope

- Whisper generation, the job queue and the worker (B2, plans 49/50).
- Target languages other than English.
- The overlay in the embed's own fullscreen (accepted limitation).
- Pruning stored translations.
- Replacing the iframe with our own player.

### Risks and accepted limitations

- R1: the embed API was tested only on `tube.rsi.cnr.it`. On an instance where it fails, the toggle is hidden: the feature degrades but does not break.
- R2: few videos have English tracks, so B1 mostly shows "no English translation available" until B2 lands (accepted tradeoff).
- R3: caption text is untrusted. It is parsed on the server, rejected as a whole when malformed, and rendered with `textContent` only.
- R4: a track labelled English is shown as the instance labels it.
- R5: SSRF is handled by the same-host https check and the no-off-host-redirect rule.
- R6: the reload anomaly from S0 (see Frontend requirements).
- Limitations: English only; no overlay in the embed's fullscreen; no toggle where the embed API doesn't answer.

### Baseline suite state

Pre-build baseline: the test suite exits with code 0 (green), with no variant run. Any red test after the build is caused by the build.

## High-level plan

### Approach

The feature has four parts: a stdlib Engine module that fetches and parses captions, a small SQLite store, one bridge route on each backend, and a page module that keeps the overlay in sync. Nothing new sits in front of the existing patterns. I read each file the requirements name, and the plan below follows what is there.

**Engine: route and checks (AC2, AC6, Engine requirements).** `_dispatch_post` in `similar.py` gets one more branch, `/internal/translate`, after the existing `/internal/` bridge-token gate at line 442. It calls `handle_internal_translate`, which lives in a new sibling module `engine/server/api/handlers/internal_translate.py`. A sibling is used because the handler makes remote calls and none of the other internal reads do. The handler works in this order:
- Read the JSON body with `read_json_body`.
- Take `id` and `host` as stripped strings. A missing or empty value gets a 400.
- Normalise `host` with `normalize_host`. A host that normalises to None gets a 400.
- Resolve the row through `resolve_video_row`, giving it the `{"id": [id], "host": [normalised host]}` dict shape it already reads. It does its own 404 and takes `db_lock` only for the lookup.
- Check the row's `instance_domain` against `list_active_denied_hosts(server.db)`, under `db_lock`. A denied host gets the same 404 as an unknown video, so the route does not reveal which check failed.

Only after both checks pass does the handler touch the cache or the network. `db_lock` is never held across a remote fetch.

**Engine: fetch (AC6, R5).** One bounded fetch function sits in the new module. It builds `https://<host><path>`, where the host is always the resolved row's `instance_domain`. It opens the URL through an opener whose redirect handler refuses any target that is not `https` on exactly that host. Before reading, it rejects a `Content-Length` over 2 MB. It then reads in chunks against a wall-clock deadline of 8 s per fetch, and stops when the body passes 2 MB or the deadline passes. It returns bytes or None. `fetch_instance_json` stays as it is, because `/api/video` still depends on its behaviour.

The caption list is read from `/api/v1/videos/{uuid}/captions`, using the row's `video_uuid` and falling back to `video_id`. The uuid is used because PeerTube accepts it on every instance version, while the Engine's `video_id` may be an instance-local number. From the list, the first entry whose `language.id` is exactly `en` is taken. Its `captionPath` is used if it is a path starting with `/`. Otherwise its `fileUrl` is used, but only if that URL parses as `https` with a hostname equal to the row's host. Anything else is refused and the answer is `none`.

**Engine: parse (AC6, R3).** A stdlib WebVTT parser in the same module works as follows:
- It decodes UTF-8 and strips a BOM.
- The first line must be `WEBVTT`, or `WEBVTT` followed by a space or tab.
- It splits on blank lines. It skips `NOTE`, `STYLE` and `REGION` blocks, takes an optional cue identifier, and needs a timing line of the form `[hh:]mm:ss.ttt --> [hh:]mm:ss.ttt [settings]`, where minutes and seconds are below 60 and there are exactly three millisecond digits.
- The cue text has its `<...>` tags removed and the basic entities decoded to plain text. It is still treated as untrusted.

Any of these makes the whole track fail: a missing header, a block that contains `-->` but does not parse, an end time before its start, or a decode error. A track that parses to zero cues is also `none`. Cues are `{start, end, text}`, with start and end in seconds as floats.

**Storage (Storage requirements).** A new data module, `engine/server/data/subtitles.py`, holds the store.
- **Table.** It has `ensure_subtitles_schema`, `fetch_ready_subtitles` and `store_ready_subtitles`, over one table keyed `(video_id, instance_domain, target_language)`. The table has columns `state`, `source`, `fetched_at`, `track_text` and `cues_json`. The key is the canonical `video_id` from the row and `target_language` is always `en`.
- **Plan 49.** Because `state` and `source` are plain TEXT columns, plan 49 can add job states and the `whisper` source without a rewrite.
- **Startup.** `server.py` opens `engine/server/db/subtitles.db` at start, through a new `DEFAULT_SUBTITLES_DB_PATH` in `server_config.py` resolved against `repo_root`, the same way `random-cache.db` is. A worktree therefore gets its own empty file, created on first open. The connection gets its own lock and is closed at shutdown beside `similarity_db`.
- **What gets written.** Only `ready` is ever written, with an upsert. Every failure is answered as `none` and nothing is written, so a track added later, or B2's generation, can still change the answer.

**Engine: deadline and lock.** The handler runs inside `_serve_post`'s statement deadline. The cache write comes after up to two network fetches, so it runs under a fresh `statement_deadline`, as `persist_video_metadata` already does. The subtitles connection has no progress handler installed, but the fresh deadline costs nothing and keeps the pattern. The subtitles lock is taken only around single reads and writes. Two concurrent misses on the same key both fetch, and the upsert makes the second write harmless.

**Client gateway (AC3, Client requirements).**
- **Route.** One GET route, `/api/translate`, gets an allow-list entry `{id, host}` in `PROXY_ALLOWED_QUERY_PARAMS`.
- **Order of work.** The route first does the rate-limit check every read does, then `_require_profile` (a single 401). It then validates the params: unknown or repeated params get 400, and so do empty `id` or `host`. Only after that does it call the Engine. "Before anything else" is read as: before any params or Engine work. This keeps the rate limit in front, as on every other profile route.
- **Shared check.** The unknown/repeated-param check is copied inline twice today, in the GET and POST proxy handlers. I extract it once into a helper and call it from the GET proxy and the new route. The POST proxy can follow later.
- **Engine call.** `engine_api_client.py` gets `fetch_translate(engine_base_url, video_id, host)`. It posts `{id, host}` to `/internal/translate` through `_post_json`, so `bridge_headers()` are sent. It passes a 20 s timeout, because the 6 s default is shorter than the Engine's worst case of two 8 s fetches.
- **Answers.** An Engine 404 becomes `{state: "none"}`, because the page has nothing to show either way. Any other non-200, or a malformed payload, raises `EngineApiError`, which the route answers through `_respond_engine_failure("translate", ...)`. A 200 is passed on only as `{state: "ready", cues}` with each cue checked for numeric start and end and string text, or as `{state: "none"}`.

**Frontend (AC1, AC4, AC5, Frontend requirements).**
- **Dependency.** `@peertube/embed-api` is added to `package.json`.
- **New data module, `src/data/translate.ts`.** It holds the on/off setting in `localStorage` under `translate:v1`, with the same in-memory fallback as `readNsfwFilter` and `setNsfwFilter`, defaulting to off. It also has `fetchTranslate(apiBase, id, host)`, which sends `profileHeaders()` and raises `ProfileKeyRejectedError` on a 401, as `reactions.ts` does.
- **New page module, `src/pages/video-page/translate.ts`.** It is called from `loadVideo` at the point where `embedEl.src` is set, which today is the only place it is set. That point:
  - appends `api=1` with `URL.searchParams`, which is correct whether or not the URL already has a query string;
  - sets the src;
  - constructs `PeerTubePlayer` on the iframe straight away, and only for an `https` embed.
- **Toggle.** It appears only after `player.ready` resolves AND `getProfileKey()` returns a key. If `ready` never resolves, there is no toggle and no request (R1).
- **Request and sync.** When the toggle is turned on, or when the page loads with the setting already on, the module requests the state from the gateway using the same `resolveVideoSource()` id and host the rest of the page uses. On `ready`, it subscribes to `playbackStatusUpdate`. On each update it binary-searches the sorted cues for the one that contains `position` and sets the overlay with `textContent`, so a seek is handled by the next update. Polling `getCurrentPosition()` is used only if no update has arrived within a few seconds of playing.
- **`none`.** A status line says "No English translation is available for this video."
- **Turning off.** It hides the overlay and stores off. Any later updates are ignored through a flag; the listener is not torn down.
- **Markup and CSS.** `video-page.html` gets a hidden toggle button labelled exactly "Translate" in `.player-actions`, a status span, and an overlay `div` inside `.player-frame`. `video.css` positions the overlay absolutely at the bottom of `.player-frame`, with `pointer-events: none` so the player's controls still work.

**R6 (loaded with Translate already on).** In this design the on-load path and the click path are the same function. The state request and `ready` run in parallel, and nothing is shown until both have settled, so the overlay does not depend on which finishes first. The player is created only after the `api=1` src is set, never before. My leading guess for the S0 anomaly is a player bound to an iframe whose src was not yet the `api=1` URL. That guess is unverified, so the build must exercise this path directly.

### Alternatives considered

- **Reuse `fetch_instance_json` and add a size check afterwards.** Rejected. It follows redirects, including off-host ones, before any check could run, and `resp.read()` has no limit, so it fails AC6 before the check is reached.
- **Refuse every redirect.** This would be simpler, but the requirement allows same-host redirects, and some instances redirect `/lazy-static/` to a canonical path on the same host. Same-host-only is what R5 asks for.
- **Rely on urllib's socket timeout alone.** Rejected. That timeout applies to each socket operation, so a server sending one byte every 7 s never trips it. A wall-clock deadline on the chunked read is what actually bounds the fetch.
- **A table in `whitelist.db`, or `.vtt` files on disk.** Both are ruled out by the requirements. A separate file also keeps translate writes off `server.db` and its global `db_lock`.
- **Open a connection per request instead of keeping one with a lock.** That is equally small, but the startup-opened connection follows the `similarity_db` precedent, puts schema creation in one place, and gives shutdown one handle to close.
- **Send the raw cue markup and strip it in the browser.** Rejected. Parsing once on the server is required. Stripping there also means the browser only ever handles plain text, and `textContent` would show tags as literal `<i>` anyway.
- **Put the translate code inside the 1,759-line `index.ts`.** Rejected in favour of one data module and one page module, in the existing `data/` and `pages/video-page/` layout. `index.ts` gets one call.
- **Keep the setting in `feed-params.ts` beside NSFW.** Rejected. That module is the feed's parameters, and the translate setting does not affect any feed. The requirement asks for "the same way", meaning the pattern, not the same file.
- **Answer a denylisted host with 200 `none` from the Engine.** Rejected in favour of the same 404 as an unknown video. The Engine then does not reveal which check failed, and the Client turns both into `none`.

### Gotchas and risks

- **Caption files on object storage come back as `none`.** Newer PeerTube versions can serve caption files from object storage, either through a `fileUrl` on another host or through a `/lazy-static/` redirect to one. Both are refused by the same-host rule, so those videos answer `none`. This is R5 working as designed, but it makes R2's "few videos" fewer still.
- **Only `language.id` exactly `en` matches.** `en-US`, or a track that has no language id, does not match. When several `en` tracks exist (for example PeerTube 6.2+ auto-generated ones), the first in list order is taken.
- **The gateway call can take up to about 16 s on a cold miss.** It runs on a threaded Engine (`ThreadingHTTPServer`), so other routes are not blocked. The visitor sees nothing until the request answers, and the toggle shows a pending state meanwhile.
- **`none` is never cached.** Every toggle-on for a video with no English track therefore repeats both remote reads. The Client rate limit is the only throttle on that. This is the price of letting B2 change the answer.
- **The parser is deliberately strict.** A track that the instance's own player accepts leniently, for example with two-digit milliseconds, is rejected as a whole. That is the AC6 rule.
- **The embed API is unproven outside `tube.rsi.cnr.it` (R1).** `playbackStatusUpdate` frequency also varies by PeerTube version, which is why the polling fallback exists.
- **CSP.** The page's CSP (`script-src 'self'`) is satisfied because Vite bundles the package. The embed API talks over `postMessage`, which CSP does not restrict.
- **R6 is not explained, only designed around.** The build has to reproduce the "loaded with Translate already on" path.

### Tradeoffs the operator is asked to accept

- **Per-fetch bound, not per-request.** The fetch deadline is 8 s per fetch, so 16 s per request, and the Client timeout is raised to 20 s for this one route. The alternative, a single 8 s budget for both fetches, fails more often on slow instances.
- **Denied and unknown look the same.** A denylisted host and an unknown video both reach the page as "No English translation is available". The page does not tell them apart.
- **One shared helper.** The unknown/repeated-param check is extracted into one helper used by the GET proxy and the new route. That touches the existing GET proxy path in a small way, which is the cost of not adding a fourth inline copy.
- **Ceilings that stay.** Simultaneous misses fetch twice; the upgrade is a per-key in-flight guard if it is ever seen in the logs. Stored translations are never pruned (out of scope). Each stored row holds up to 2 MB of original track text.

## Impacts

<impacts>
<impact path="engine/server/api/handlers/internal_translate.py" element="new module: handle_internal_translate(handler, server), the bounded same-host fetch and its redirect handler, the caption-list pick, the WebVTT parser">
**What changes.** A new sibling of `internal_client_reads.py` holding the `/internal/translate` handler, one bounded https fetch, the caption-list pick and the stdlib WebVTT parser.

**What it depends on (checked in the files).**
- `read_json_body` / `respond_json` (`engine/server/api/http_utils.py:39`, `:23`). `read_json_body` raises `ValueError` for a body over 1 MB, a non-numeric `Content-Length` (`int(length)`), invalid JSON, a non-object body, and a bad UTF-8 decode (`UnicodeDecodeError` is a `ValueError`). Every other internal handler catches it and answers 400 (`internal_client_reads.py:88-92`); this one must too. `respond_json` writes `indent=2`, so a large cue list is padded on the wire.
- `normalize_host` (`engine/server/data/moderation.py:45`): lowercases, drops scheme, path and **port**, strips dots, and returns None for empty input.
- `resolve_video_row` (`engine/server/api/handlers/video.py:264-286`): reads `params["id"][0]` / `params["host"][0]`, takes `db_lock` only for `fetch_video_row`, applies `server.video_error_threshold`, and answers its own 400 `Missing video id` and 404 `{"error": "Video not found"}`. `fetch_video_row` matches `(v.video_id = :id OR v.video_uuid = :id) AND v.instance_domain = :host`, an exact, case-sensitive comparison.
- `list_active_denied_hosts(server.db)` (`moderation.py:137`): a lowercased set of whole hosts, read under `db_lock`.
- `statement_deadline` (`engine/server/data/db.py:46`) and the new `data.subtitles` functions.

**Regression risk: medium (new, security-sensitive code on a new outbound surface).**
- **Redirects (R5).** urllib's default `HTTPRedirectHandler` follows redirects before any later check runs, so it has to be replaced inside the opener. The same-host https check covers 301/302/303/307/308. The comparison is against the resolved row's `instance_domain`, never the request `host`. A `fileUrl` with `user@` or an explicit port needs an explicit decision: compare `.hostname` and decide whether to refuse a port.
- **Denylist comparison.** Normalise before the membership test: `normalize_host(row["instance_domain"]) in denied`, as `filter_rows_by_moderation` does through `_row_host` (`moderation.py:394-402`). Otherwise a stored domain that differs by case or a trailing dot passes here but is filtered on every feed. A host that is denied and already purged has no `videos` row (`purge_host_data` deletes it, `moderation.py:194-228`), so it 404s at lookup anyway. The denylist check matters only for hosts that are denied but not yet purged.
- **Port mismatch (uncertain).** The plan passes the normalised host into `resolve_video_row`. `normalize_host` strips a port, while the crawler's `normalize_host_token` (`moderation.py:72-85`) keeps a port on bare host entries. If any `instance_domain` in `whitelist.db` carries a port, the lookup can never match and those videos always answer `none`. I could not query the DB to confirm whether such rows exist.
- **Deadline.** The socket timeout bounds connect and each recv, not the whole body. The wall-clock check between chunks still lets one `read(n)` block for a full socket timeout, so the real bound is about deadline + timeout unless each recv's timeout is set to the remaining budget. DNS (`getaddrinfo` inside `urlopen`) is bounded by neither, so a hanging resolver holds the thread past the Client's 20 s. Either bound it, or name it as an accepted gap in the docstring.
- **Exceptions escape as a dropped connection.** `SimilarHandler._run_request` (`similar.py:345-361`) lets exceptions propagate to socketserver, so no response is sent. The Client then sees a reset and answers 502 `Engine translate failed` instead of `none`. The fetch must catch more than `fetch_instance_json` does (`video.py:91-97`): read-phase `http.client.HTTPException` (IncompleteRead, RemoteDisconnected), `OSError` (`ConnectionResetError`, `ssl.SSLError`, `socket.timeout`), `UnicodeError` from IDNA, and `ValueError` (InvalidURL). JSON parsing of the caption list must reject non-object bodies and non-list `data`.
- **Caption list.** Use `/api/v1/videos/{uuid}/captions` with `quote()`, as `fetch_instance_video_dynamic` does (`video.py:210`). Pick the first `language.id == "en"`. Use `captionPath` only if it starts with `/` and not `//`; a protocol-relative `//evil/x` would otherwise build `https://host//evil/x`, which is harmless but should be pinned in a test.
- **Parser edge cases:** CRLF, a BOM, the `WEBVTT` header followed by text, a cue identifier containing `-->`, `NOTE`/`STYLE`/`REGION` blocks, zero-length cues (end == start is allowed), cues out of order (the frontend binary search needs them sorted: sort them or reject), and the zero-cue result, which answers `none`.
- **Cache write.** Wrap it in a fresh `statement_deadline` and catch `sqlite3.OperationalError` (including `database is locked` from a second Engine during a blue/green overlap), then still answer `ready`. The precedent is `persist_video_metadata`, `video.py:386-446`. An uncaught error escapes `_serve_post` (`similar.py:404-412`), which answers 503 for an interrupt and re-raises anything else.
- **Importability.** Keep it numpy-free. `internal_client_reads.py` imports numpy at line 6, which is why its tests run in an `ENGINE_PY` child; `handlers.video`, `data.moderation` (via `data.similarity_cache`), `data.db` and `http_utils` import none.
- **Plan 49 reuse (placement question).** `docs/project/plans/49-translate-whisper-worker.md:38` has the worker re-check for an instance English track and store it "the way B1 stores it". With the fetch and parser in an `api/handlers/` module, a separate worker process would import a request-handler module. Placing the fetch and parser under `engine/server/data/` (or a small shared module) avoids that. The plan does not decide it.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_dispatch_post (lines 439-469): new /internal/translate branch; handlers import block (lines 94-100); module docstring route list (lines 1-18)">
**What changes.** One `if url.path == "/internal/translate": handle_internal_translate(self, self.server); return` branch after the bridge gate, one import, and a docstring line beside `/internal/videos/resolve` (lines 11-13).

**What depends on it.**
- Every Engine POST passes through `_dispatch_post`.
- The gate at line 442 covers any `/internal/` path, so the route fails closed: 503 when the token is unset, 401 on a wrong token. It needs no new auth code.
- The handler runs inside `_serve_post`'s `with self._statement_deadline()` (5.0 s, `server_config.py:486`), so a statement on a deadline-handled connection after up to about 16 s of fetching is interrupted unless it is re-armed.
- Engine POSTs have no Engine-side rate limit; only `/api/` GETs call `_rate_limit_check` (line 488). This is the first Engine route whose outbound fetches are driven by a POST, and the Client limit is the only throttle.
- The fallthrough `respond_json(self, 404, {"error": "Not found"})` (line 469) is what an Engine without this route answers. That bears on the Client's 404 mapping (see `engine_api_client.py`).

**Regression risk: low for existing routes.** It adds one branch before the 404. `similar.py` already imports numpy, so the new import changes no import chain.
</impact>
<impact path="engine/server/api/handlers/video.py" element="resolve_video_row (264-286), fetch_video_row (25-79), fetch_instance_json (82-101), persist_video_metadata (373-446): reused or left alone">
**What changes.** Nothing in code if the plan holds. `resolve_video_row` is called with a synthesised `{"id": [id], "host": [normalised host]}`. `fetch_instance_json` is not reused or changed.

**What depends on it.**
- `/api/video` and `/api/video/refresh` (`handle_video_refresh_request`, line 449). Note that those routes fetch from the instance with no denylist check, so the new route is stricter than this precedent; that is deliberate.
- `tests/active/test_video.py` monkeypatches `handlers.video.fetch_instance_json` and `handlers.video.urlopen`. The new module needs its own patch seam (its own opener or fetch function), or those patches reach nothing in it.

**Regression risk: low.** It becomes medium only if someone "improves" `fetch_instance_json` (cap, redirect rule, wider except): `/api/video` and its tests depend on its exact behaviour. The handler must take the fetch host from `row["instance_domain"]`, not from the third tuple element, which falls back to the request host when the row's domain is empty (line 286).
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host (45), list_active_denied_hosts (137), filter_rows_by_moderation/_row_host (148, 394), purge_host_data (194)">
**What changes.** Nothing; they are reused.

**What depends on it.** `normalize_host` is part of the ANN id contract (comment at line 44) and must not be changed to suit this feature.

**Things to know.**
- `list_active_denied_hosts` reads the whole active list on every call, under `db_lock`. That is cheap today and runs once per translate request.
- Serving filters honour `server.enable_instance_ignore` (`serving_moderation.py:21`). The plan's check is unconditional, which suits a remote fetch, but it should be a stated choice.
- Blocked channels (`channel_moderation`) are not checked, so a video from an operator-blocked channel can still be translated.
- `purge_host_data` and `purge_similarity_for_host` touch only `whitelist.db` and the similarity cache, so `subtitles.db` rows of a purged host stay on disk. They are never served, because the row lookup 404s first.

**Regression risk: none in code.** Semantically, the comparison must use the normalised row host (see the handler entry).
</impact>
<impact path="engine/server/data/subtitles.py" element="new module: ensure_subtitles_schema, fetch_ready_subtitles, store_ready_subtitles">
**What changes.** A new data module with one table keyed `(video_id, instance_domain, target_language)` and the columns `state`, `source`, `fetched_at`, `track_text`, `cues_json`, written with an upsert of `ready` only.

**What depends on it.** The new handler, `server.py` startup, and the two follow-on plans. Those plans **do exist** in the tree, although the requirements say otherwise (`docs/project/plans/49-translate-whisper-worker.md`, `50-translate-generation-in-page.md`):
- Plan 49 line 98: "B1's `subtitles` table gains the job states (`queued`, `running`, `failed`, `already_english`) and their timestamps, and the cue store becomes append-only … SQLite runs in WAL mode, because B1's Engine route and the worker both write." The table should therefore be named `subtitles`. Plan 49 line 43 appends cues per chunk while `running`, and one `cues_json` blob is not append-friendly. Plan 49 must either add a cue table or rewrite the blob; this is a design debt to state, not a blocker.
- Plan 49 line 31 puts the job queue in this same `subtitles.db`.
- Do not add a CHECK constraint on `state` or `source`, or plan 49 needs a table rebuild.
- `PRAGMA journal_mode=WAL` is persistent in the file. If B1 sets it, B1 owns the choice and its `-wal`/`-shm` sidecars. If not, plan 49 sets it.

**Regression risk: low (new file).**
- `INSERT … ON CONFLICT(video_id, instance_domain, target_language) DO UPDATE` needs SQLite 3.24+, which the pixi Python has; `INSERT OR REPLACE` is the alternative.
- Store cues as compact JSON, since `track_text` alone can be 2 MB.
- A row whose `cues_json` fails to load must read as a miss, not raise.
</impact>
<impact path="engine/server/data/db.py" element="connect_db (77-82), connect_similarity_db (141-145), statement_deadline (46); possibly a new connect_subtitles_db">
**What changes.** Possibly a new `connect_subtitles_db(path)`, or reuse of `connect_similarity_db`, which already has the shape needed: `check_same_thread=False`, `sqlite3.Row`, no progress handler.

**What depends on it.**
- `connect_db` installs `install_deadline_handler` (line 81). Opening `subtitles.db` with it would bind every post-fetch statement to the request's 5 s deadline. A no-handler connection makes `statement_deadline` a no-op for it (docstring lines 49-52); that is harmless and keeps the pattern.
- `install_deadline_handler`'s docstring warns never to install a handler later on a shared connection.
- sqlite3's default busy `timeout` is 5 s. A larger `timeout=` covers concurrent starts and blue/green writers.

**Regression risk: low.** It adds a function; no existing opener changes.
</impact>
<impact path="engine/server/api/server_config.py" element="data path constants (lines 413-418): new DEFAULT_SUBTITLES_DB_PATH; possibly translate fetch constants">
**What changes.**
- `DEFAULT_SUBTITLES_DB_PATH = "engine/server/db/subtitles.db"` beside `DEFAULT_RANDOM_CACHE_DB_PATH` (line 418).
- Possibly the 2 MB cap and 8 s per-fetch deadline as constants, unless they live in the handler module.

**What depends on it.**
- The `server.py` import list (lines 25-83).
- Variant runners that override constants by name (`tests/active/test_random_cache.py:289`, and the `test_server_config.py` variant start at line 265). An isolated-DB Engine test needs this name to be overridable the same way.
- `tests/config.json` maps this file into many groups (`test_dislike_profile.py`, `test_similar.py`, `test_server_config.py` and others), so they all rerun.

**Regression risk: low.** The constants are additive.
</impact>
<impact path="engine/server/api/server.py" element="main(): path resolution (337-341), open/ensure (343-366), server attributes (489-494), shutdown finally (545-563); SimilarServer.__init__ (219-293)">
**What changes.**
- Resolve `(repo_root / DEFAULT_SUBTITLES_DB_PATH).resolve()`, open the DB, run `ensure_subtitles_schema`, and attach `server.subtitles_db`.
- Add a `subtitles_db_lock`.
- Close the handle in the `finally` beside the similarity and random-cache handles.

**What depends on it.**
- **Open order.** Open after `prepare_trending_override` (line 345). `tests/active/test_server_config.py` (docstring lines 27-31, test from line 344) expects a bad `--trending-db` to stop the start without touching anything, and an earlier open would create `subtitles.db` first. Also open after `random_cache_path.parent.mkdir` (line 363), because nothing before that line ensures `engine/server/db/` exists: `connect_db` (346) and `connect_similarity_db` (359) do not create directories. The earlier inventory said the mkdir "runs before", which holds only if the open is placed after line 363.
- **Constructor stand-ins.** `tests/active/test_video.py:170,229` and `tests/active/test_internal_events.py:51` build `SimilarServer` with `dict.fromkeys(...parameters[3:])`. A new constructor parameter arrives as None there, and an attribute set only in `main()` is absent. The lock belongs in `__init__` beside `similarity_db_lock` (line 292), and the handler must read `getattr(server, "subtitles_db", None)` and degrade cleanly.
- **Concurrent starts.** `tests/active/test_random_cache.py:771-839` starts eight Engines at once against the checkout's `engine/server/db/`. Each now opens `subtitles.db` and runs DDL. The held write lock there is on `random-cache.db` only. On a fresh file the eight `CREATE TABLE IF NOT EXISTS` statements contend under the default 5 s busy timeout. The session Engine normally creates the file first, but this is a new startup failure mode, and the same applies to two blue/green Engines. A `PRAGMA journal_mode=WAL` at every open would also need a write lock the first time.
- **Session Engine.** The fixture (`tests/active/conftest.py:169-209`) creates and writes the checkout's `subtitles.db`; `.gitignore` covers it.
- **Shutdown.** Close after `db.close()` and outside `db_lock`.

**Regression risk: medium.** This touches the startup and shutdown of every Engine.
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="module docstring (lines 1-8)">
**What changes.** Add one line: `internal_translate: …`.

**What depends on it.** Nothing in code.

**Regression risk: none.**
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="new fetch_translate(engine_base_url, video_id, host); _post_json (44-75); resolve_video_seed 404 precedent (92-94)">
**What changes.** A new function posting `{id, host}` to `{base}/internal/translate` through `_post_json(..., timeout=20)`.
- A 200 is validated: `state` is `ready` or `none`; for `ready`, `cues` is a list of dicts with numeric, non-bool `start`/`end` and str `text`. Anything else raises `EngineApiError`.
- Any other non-200 raises `EngineApiError("Engine translate failed (HTTP n): …")`.

**404 mapping (open decision).** The plan maps every 404 to `none`, copying `resolve_video_seed` (lines 93-94). The Engine also answers `404 {"error": "Not found"}` for a route it does not have (`similar.py:469`), so a Client deployed ahead of its Engine, or left on a new build after a blue/green rollback, would answer `none` for every video with nothing logged. Mapping only a body of `{"error": "Video not found"}` to `none` (the text `resolve_video_row` sends, which the denied-host branch should reuse) surfaces version skew as a logged 502. It couples the Client to that string, so pin it on both sides.

**Things to know about `_post_json`.**
- `timeout` is annotated `int`; 20 fits.
- It reads the whole body with no cap, and a `ready` payload for a 2 MB track can be several MB of indented JSON.
- `HTTPError` is caught before `URLError` and returns `(code, parsed)`. A connection reset, which is what an uncaught Engine exception produces, falls into `except Exception` and becomes `EngineApiError`.
- `bool` is an `int` subclass, so it must be excluded explicitly.
- Plan 50 (`50-translate-generation-in-page.md:21-22,41`) later adds the states `queued`, `running`, `already_english`, `failed`, partial cues and an `after` parameter, so this validator will be widened there.

**Regression risk: low.** It is additive. The file is in the `test_profiles.py`, `test_dislikes.py` and `test_server.py` groups.
</impact>
<impact path="client/backend/server.py" element="_serve_get (386-440): new /api/translate branch and handler method; PROXY_ALLOWED_QUERY_PARAMS (95-112); lib.engine_api_client import (32-34); possibly ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS precedent (84-89)">
**What changes.**
- A new `/api/translate` branch shaped like `/api/profile/reaction` (434-439): `_rate_limit_check` then 429, `_require_profile` then 401, then the param check then 400, then `fetch_translate(self.server.engine_ingest_base, …)`. `EngineApiError` goes to `_respond_engine_failure("translate", exc)` (530-534).
- A new entry `"/api/translate": {"id", "host"}` in `PROXY_ALLOWED_QUERY_PARAMS`.
- The `fetch_translate` import.

**What depends on it.**
- `/api/translate` must **not** be added to `PROXY_READ_GET_ROUTES` (91-93), which routes through `_proxy_engine_request` with no profile check and no bridge token.
- `PROXY_ALLOWED_QUERY_PARAMS` is read by both proxy handlers with `.get(path, set())`, so an entry for a path that is not proxied is inert there.
- `parse_qs(url.query)` (line 389) runs without `keep_blank_values`, so `?id=&host=x` arrives with no `id` key: "empty" has to be tested as missing after the strip.
- Length bound: the reaction route caps values at `BLOCK_REFERENCE_MAX_LENGTH` (200, defined line 69, used 1054). The plan sets no cap, though one is cheap.
- The route blocks one Client thread for up to 20 s; `ClientBackendServer` is a `ThreadingHTTPServer` (line 300).
- Order: 429, then 401, then 400, so a keyless request with bad params gets 401. Tests should pin that.
- The 20 s translate timeout follows the refresh precedent (`ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS`, line 86), but it is a separate literal in `engine_api_client`. A named constant keeps it visible beside the deploy drain (see `scripts/deploy-bluegreen.sh`).

**Regression risk: low to medium.** It is a new GET branch; the risk is in the shared helper (next entry).
</impact>
<impact path="client/backend/server.py" element="_handle_engine_read_proxy_get (536-555) and _handle_engine_read_proxy_post (590-613): unknown/repeated-param loop extracted into one helper">
**What changes.** The loop at 538-551 moves into a helper called by the GET proxy and the new route. The POST copy (593-606) stays inline.

**What depends on it.** Every proxied GET (`/api/video`, `/api/video/refresh`, `/api/channels`, `/api/v1/search/videos`). The helper must preserve, byte for byte:
- the texts `Unknown query parameter: {key}` and `Multiple values are not allowed for query parameter: {key}`;
- first-offending-key order (dict order of the `parse_qs` output);
- skipping an empty list (`if not values: continue`);
- `PROXY_UNSTRIPPED_QUERY_PARAMS` (`nsfw` forwarded unstripped, ADR-0007);
- dropping a value that is empty after the strip.

These are pinned by `tests/active/test_server.py:1519`, and documented in `client/README.md:29-31`, `engine/server/README.md:28` and `DEPLOYMENT.md:703`.

**Regression risk: medium.** A changed strip or empty-handling rule alters what reaches the Engine on every read. A helper that both answers 400 and returns a value invites a double response when a caller forgets to return.
</impact>
<impact path="client/frontend/package.json" element="dependencies: add @peertube/embed-api">
**What changes.** A new runtime dependency. It is not installed today: there is no `client/frontend/node_modules/@peertube`.

**What depends on it.**
- `package-lock.json` (next entry).
- `scripts/worktree-setup.sh:35` symlinks a worktree's `node_modules` to main's, so an `npm install` in a build lane writes into main's shared tree.
- Every `vite build` (`test_frontend_dist.py`, `test_frontend_base_css.py`) and both esbuild bundles of `video-page/index.ts` must resolve it, and fail outright if it is missing.
- **Library behaviour, read from S0's local copy `.scratch/18-subtitles/player.min.js`.** This is the unpkg UMD build; the npm ESM entry may differ, so confirm it in the installed package.
  - jschannel registers `window.addEventListener("message", …)` at **module evaluation**, so merely importing the module touches `window`.
  - The `PeerTubePlayer` constructor calls `Channel.build({window: iframe.contentWindow, origin: "*", scope: "peertube"})`. That throws **strings, not `Error`s** when `window.postMessage` is missing, when `contentWindow` lacks `postMessage`, or when a channel is already bound to the same window, origin and scope.
  - `ready` can **reject** (`bind("ready", p => p ? r() : d())`), as well as never resolve.
  - `destroy()` calls `this.embedElement.remove()`, which **removes the iframe**.
  - `sendMessage` promises (`getCurrentPosition`) have no timeout.
  - `addEventListener` on an unknown event name calls `console.warn`.
  - The UMD build also sets `window.PeerTubePlayer`.
- Whether the package ships TypeScript types is unverified. `vite build` does not type-check.

**Regression risk: medium.** It adds a third-party bundle on a `script-src 'self'` page. Vite inlines it, so CSP holds, and the library uses no eval.
</impact>
<impact path="client/frontend/package-lock.json" element="lockfile">
**What changes.** Regenerated by `npm install @peertube/embed-api`.

**What depends on it.** Reproducible installs. The file is in the `test_frontend_dist.py` group (`tests/config.json:358`), but `package.json` is not.

**Regression risk: low.** Unrelated churn (a vite or esbuild bump) would move every asset hash, so the install should add only the new package and its dependencies.
</impact>
<impact path="client/frontend/src/data/translate.ts" element="new module: readTranslate/setTranslate (localStorage translate:v1, in-memory fallback, default off) and fetchTranslate(apiBase, id, host)">
**What changes.** A new data module.
- The setting copies `readNsfwFilter`/`setNsfwFilter` (`src/data/feed-params.ts:68-97`): a module-level in-memory value and try/catch around `window.localStorage`. Unlike NSFW it defaults to **off**, so only a stored `on` means on.
- `fetchTranslate` copies `fetchReaction` (`src/data/reactions.ts:30-46`): `new URL("/api/translate", resolveClientApiBase(apiBase))`, `searchParams.set`, `headers: profileHeaders()`, `cache: "no-store"` (so a `none` that later becomes `ready` is not cached), a 401 throwing `ProfileKeyRejectedError`, and any other non-OK status throwing.

**What depends on it.** The new page module.

**Things to know.**
- Validate the payload shape in the module (state, finite numeric start/end, string text) rather than trusting the gateway.
- `getProfileKey` reads bare `localStorage` while feed-params reads `window.localStorage`; both node harnesses define both (`test_frontend_video_page.py:64-67`).
- The key `translate:v1` must not collide with an existing key (`profileKey:v1`, `nsfwFilter:v1`, `feedParams:v1`, `localLikes:v1`).

**Regression risk: low (new file).**
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="new page module: PeerTubePlayer construction, toggle gating, state request, playbackStatusUpdate sync, overlay, polling fallback">
**What changes.** A new module, called once from `loadVideo`. It constructs one `PeerTubePlayer` for an https embed and shows the toggle after `ready` resolves and `getProfileKey()` is non-null. It requests the state, binary-searches the cues on `playbackStatusUpdate`, writes the overlay with `textContent`, and falls back to polling `getCurrentPosition()`.

**What depends on it.** `index.ts`, `data/translate.ts`, `data/profile.ts`, `components/key-rejected.ts` (a 401 can reuse `keyRejectedNotice`, as similars do at `index.ts:355-357`) and `@peertube/embed-api`.

**Unresolved conflict carried from step 4 pass 1.** The plan's R6 paragraph runs "the state request and `ready` … in parallel", so with Translate already on, `/api/translate` is sent before `ready`. The Toggle bullet and AC1 say no translate request is made unless `ready` resolved. Both cannot hold, and the plan text handed to this step still contains both. The on-load request has to wait for `ready` and a key, or the operator has to accept the AC1 deviation.

**Risks.**
- **Constructor throws.** Wrap it: it throws strings in the node harnesses (stub `window` has no `postMessage`; stub elements have no `contentWindow`). Catch any value, not just `Error`.
- **Construct exactly once per iframe per page.** A second `PeerTubePlayer` on the same `contentWindow` with the default scope throws "A channel is already bound…". The iframe's WindowProxy is stable across `src` changes. This is a plausible, unverified cause of the S0 R6 anomaly: `embed_check.html:57-74` builds a new player on every Load click on the same iframe, so only the first Load after a page reload could work.
- Handle a **rejected** `ready` as well as one that never settles. Neither may surface as an unhandled rejection (the harness records `rejections`), and neither may show the toggle or send a request.
- Never call `player.destroy()`; it removes `#video-embed`.
- `playbackStatusUpdate` payloads come from the instance, so check `Number.isFinite(position)`.
- Do not stack un-settling `getCurrentPosition()` calls, and clear the fallback timer on toggle-off.
- The overlay must use a CSS class, never `setAttribute("style")`, because the page CSP has `style-src 'self'` (`video-page.html:8`).
- Cues must be sorted for the binary search. Plan 50 AC4 appends cues while a job is `running`, so keep the cue list replaceable.
- **Short-UUID pages.** `resolveVideoSource()` (`index.ts:1204-1212`) can yield an id from `/w/<shortUUID>` (`parseVideoUrl`, `index.ts:1217-1230`), which matches neither `video_id` nor `video_uuid`, so Translate answers `none` there. `enableBlockButtons` already prefers `metadata?.videoUuid` (`index.ts:246`).

**Regression risk: medium.** This is new code on the page's main load path.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadVideo (133-292), embed block (280-289), imports (5-20), resolveVideoSource (1204-1212)">
**What changes.**
- Inside the existing https branch (284-285), the URL gets `api=1` via `URL.searchParams`, then `src` is set, then the iframe and identity are handed to the translate module.
- One import is added.

**What depends on it.**
- **Every video page load, keyless visitors included.** The embed now always carries `api=1`, and a player channel is built on every https embed.
- **The scheme check.** `/^https:\/\//i` is the only guard against a `javascript:` URL arriving through `?embed=` (comment 281-283), so the `new URL()` parse stays inside that branch. A throw on a malformed https-prefixed string must fall back to `removeAttribute("src")`.
- **Code after the block.** `applyOriginalHref(originalLink)` and `applyOriginalHref(commentsUnavailableLink)` (290-291) run after the embed block. Any throw from the translate setup skips them and becomes an unhandled rejection (`void loadVideo()`, line 126). The harness reads `originalHref`.
- **Embed source.** `embed` is `metadata?.embedUrl ?? fallback.embed` (line 147), and cards always pass `?embed=` (`src/components/video-card.ts:302-303`). This is the only place `embedEl.src` is set.
- **Identity.** `seedHost` from card links is the row's raw `instance_domain` (`video-card.ts:288-291`). The URL-parsed host can include a port, which the Engine's `normalize_host` strips (see the handler entry's port caveat).

**Regression risk: medium.** A mistake here breaks the player for every visitor. The file is bundled whole by two node harnesses.
</impact>
<impact path="tests/active/test_frontend_video_page.py" element="esbuild bundle of video-page/index.ts (197-208) and node RUNNER stubs (60-194)">
**What changes.** Nothing need change, but the bundle now includes `@peertube/embed-api` and the translate modules.

**What depends on it.**
- All cases import the bundle with a stub `window = {location, localStorage, sessionStorage, addEventListener(){}}` (line 66-67). It has `addEventListener`, so jschannel's import-time listener registration succeeds, but there is no `postMessage`.
- Stub elements (71-98) have no `contentWindow`, and `src` is a plain property.
- No case sets `embedUrl` or `?embed=`; the `VIDEO_BODY` default is `{videoUuid, title}` (line 215). So the https branch and player construction are not reached today.
- `rejections` and `warned` are reported, and exact request lists (`requested`, `startUrls`, `startRequests`, `requestsSoFar`) are asserted. A translate request occurs only with a key and `translate:v1=on`, and storage starts empty.

**Regression risk: medium.** It goes red if the package cannot be resolved, or if its ESM build touches something the stub lacks at import. New R6 cases need an esbuild `--alias` stand-in for `@peertube/embed-api` that records `ready`, `addEventListener('playbackStatusUpdate')` and `getCurrentPosition` in order. Any case that seeds a key and `translate:v1=on` must give `/api/translate` an explicit stub entry and update its expected request counts.
</impact>
<impact path="tests/active/test_frontend_video_page_similars.py" element="second esbuild bundle of video-page/index.ts (line 113) with its own window stub (35-37)">
**What changes.** Nothing directly. Its stub `window` has `addEventListener` and `removeEventListener` but no `postMessage`, so the same import-resolution and import-side-effect risk applies.

**What depends on it.** The similar-videos cases.

**Regression risk: medium**, for the same reason as the previous entry.
</impact>
<impact path="client/frontend/video-page.html" element=".player-frame (30-38), .player-actions (75-94), CSP meta (6-9)">
**What changes.**
- A hidden `<button id="translate-toggle" class="ghost-button" type="button" aria-pressed="false" hidden>Translate</button>` labelled exactly "Translate".
- A `role="status"` span like `#reaction-status` (line 90).
- An overlay `div` inside `.player-frame`, after the iframe.
- The iframe sandbox (line 36) and the CSP meta stay unchanged.

**What depends on it.**
- `test_frontend_video_page.py:55-58` regex-reads the initial text of the comments elements, which is unaffected.
- `test_frontend_dist.py` compares `dist/video-page.html` with a fresh build.
- CSP: `frame-src https:` and `connect-src 'self' https:` already cover the embed and the gateway, and postMessage is not governed by CSP. The nginx server CSP (`DEPLOYMENT.md:523`) agrees.

**Regression risk: low.** The overlay must sit above the iframe (DOM order or z-index) with `pointer-events: none`.
</impact>
<impact path="client/frontend/src/video.css" element=".player-frame (44-52) / .player-frame iframe (54-60); .block-status (200); .player-actions (249)">
**What changes.**
- An absolutely positioned overlay rule at the bottom of `.player-frame` (already `position: relative; overflow: hidden; padding-top: 56.25%`), with `pointer-events: none`, white-space handling and a readable text shadow, as in S0 (`.scratch/18-subtitles/embed_check.html:15-16`).
- The status span can reuse `.block-status`.

**What depends on it.**
- `test_frontend_base_css.py` requires the bundle to start with `base.css`, so nothing may go before `@import "./base.css"` (line 1).
- The hashed CSS asset name in `test_frontend_dist.py`.

**Regression risk: low.**
</impact>
<impact path="client/frontend/dist/" element="committed build output: video-page.html and assets">
**What changes.** It is rebuilt and recommitted. The video JS/CSS hashes change, and shared chunks may move.

**What depends on it.** `tests/active/test_frontend_dist.py` (line 17) asserts that the committed dist holds exactly what a fresh build emits.

**Regression risk: high if forgotten, none if it is rebuilt last**, after every source change, the lockfile included.
</impact>
<impact path="tests/active/test_server.py" element="GET proxy allow-list tests (docstring ~117-130, line 1361, line 1519); FAILURE_ROUTES table (1045-1051) and _failing_engine stub">
**What changes.** No existing edit is needed if the helper extraction is faithful.
- The new route belongs in the `FAILURE_ROUTES` table (1045-1051), e.g. `("translate", "GET", "/api/translate?id=…&host=…", True, None, {}, ["/internal/translate"], "Engine translate failed")`.
- New cases cover: 429 before 401, 401 before 400, unknown, repeated and empty params, Engine `Video not found` 404 mapping to `none`, any other 404 mapping to 502 (if that is adopted), a malformed payload mapping to 502, and the bridge token being sent.

**What depends on it.** The GET proxy's 400 texts and order.

**Regression risk: medium.** This file is the canary for the helper extraction.
</impact>
<impact path="tests/active/test_video.py" element="SimilarServer built from its signature (170, 229); monkeypatches of handlers.video.fetch_instance_json/urlopen; SimpleNamespace server (300)">
**What changes.** Nothing; it is a dependency to respect.

**What depends on it.** A new `SimilarServer.__init__` parameter arrives as None here, so `__init__` must only store it.

**Regression risk: low.** New handler tests can use a `SimpleNamespace(db, db_lock, video_error_threshold, subtitles_db, subtitles_db_lock)` in-process, as `test_internal_client_reads.py:83` does, because the new module is numpy-free.
</impact>
<impact path="tests/active/test_internal_events.py" element="SimilarServer built with dict.fromkeys of the constructor signature (line 51)">
**What changes.** Nothing; the same constructor-signature dependency as the previous entry applies.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_random_cache.py" element="test_engines_starting_at_once_all_become_healthy (771-839)">
**What changes.** Nothing. The eight Engines now also open the checkout's `subtitles.db` and run its DDL at start.

**Regression risk: low to medium.** If the file is fresh, they contend under the 5 s default busy timeout, and a loser that exits fails `exited == {}`. A raised `timeout=` on the subtitles connection mitigates this.
</impact>
<impact path="tests/active/test_server_config.py" element="--trending-db rejected-start checks (docstring 27-31, test 344-360)">
**What changes.** Nothing in the test.

**What depends on it.** A rejected start must touch nothing.

**Regression risk: low.** The current asserts look only at `absent.db` and `junk.db`, but opening `subtitles.db` before `prepare_trending_override` would break the stated intent.
</impact>
<impact path="tests/active/conftest.py" element="session engine fixture (169-209)">
**What changes.** Nothing in code. The session Engine runs against the checkout's `engine/server/db/` and creates `subtitles.db` there.

**What depends on it.** Any end-to-end translate test through it would make real outbound requests unless the fetch is stubbed, and a stored `ready` row persists across runs. New tests should run in-process with a patched fetch, or on a variant Engine with an overridden `DEFAULT_SUBTITLES_DB_PATH`.

**Regression risk: low for existing tests.** Test isolation is a risk for new ones.
</impact>
<impact path="tests/config.json" element="test_groups: test_frontend_video_page.py (218-222), test_frontend_video_page_similars.py (227-230), test_frontend_dist.py (349-396), new groups">
**What changes.**
- Map `engine/server/api/handlers/internal_translate.py` and `engine/server/data/subtitles.py` to the new Engine test file.
- Map `client/frontend/src/data/translate.ts` and `src/pages/video-page/translate.ts` to the new frontend test file, to `test_frontend_video_page.py` and `test_frontend_video_page_similars.py` (which bundle them), and to `test_frontend_dist.py` (whose list enumerates every `src` file).
- Add `client/frontend/package.json` to the `test_frontend_dist.py` group; it is missing today, as only `package-lock.json` is listed at line 358.
- Map `client/backend/server.py` and `lib/engine_api_client.py` to the new Client test file.

**Regression risk: none at runtime.** Missing mappings only mean changed files do not trigger their tests.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="forbidden internal-route pattern (line 34)">
**What changes.** Add `/internal/translate` to the list (optional). `/internal/dislikes/centroids` is also missing today.

**What depends on it.** The frontend gateway guard.

**Regression risk: none.** Without it, the guard misses a direct frontend call to the route.
</impact>
<impact path="scripts/deploy-bluegreen.sh" element="--drain help text (17-18) and DRAIN_SECONDS=30 (50); two Engines on one checkout">
**What changes.** The help text justifies the 30 s drain by "the Client's longest Engine request timeout is 20 s". `/api/translate` becomes a second route at 20 s and should be named there. The translate timeout must stay at or below the drain.

**What depends on it.**
- During the overlap both Engines open `subtitles.db` read-write, and a locked upsert must be caught (see the handler entry).
- Handler threads are daemon threads (`ThreadingHTTPServer`), so a translate request still fetching when the old instance stops is cut off. The Client then answers 502.
- No temp files are created, so the cleanup needs no change; `tests/active/test_deploy_bluegreen.py:385` lists only random-cache files.

**Regression risk: low.**
</impact>
<impact path="scripts/worktree-setup.sh" element="shared/private db lists (26-31) and node_modules symlink (35)">
**What changes.** None. `subtitles.db` is neither symlinked nor copied, so each worktree's Engine creates its own, as required.

**What depends on it.** Build lanes.

**Regression risk: none.** The `node_modules` symlink means an `npm install` in a lane installs into main's tree.
</impact>
<impact path=".gitignore" element="*.db, *.db-journal, *.db-shm, *.db-wal (11-14)">
**What changes.** None; `subtitles.db` and any WAL sidecars are already ignored.

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/instance-denylist-cli.py" element="denylist add/purge via data/moderation.py purge_host_data">
**What changes.** None in this plan.

**What depends on it.** A denied host's `subtitles.db` rows are not purged. They are never served, because the denylist check and the row lookup come first, but the caption text stays on disk until a future prune (out of scope).

**Regression risk: none functionally.**
</impact>
<impact path="docs/project/plans/51-48-translate-instance-captions.md" element="Requirements Purpose paragraph and High-level plan R6/Toggle text">
**What changes.**
- The Purpose says "Plans 18, 49 and 50 are not in the tree … so this file is self-contained". That is false: `docs/project/plans/18-english-subtitles.md`, `49-translate-whisper-worker.md` and `50-translate-generation-in-page.md` all exist, and 49 and 50 constrain B1's store and state route (see the `subtitles.py` and `engine_api_client.py` entries).
- The R6 paragraph conflicts with the Toggle bullet and AC1 (see the `translate.ts` entry).

**What depends on it.** Steps 4 and 5 read this file as the source of truth.

**Regression risk: none at runtime.** It is a planning-correctness risk.
</impact>
</impacts>

## Documentation to update

- [x] `client/README.md` - updated: Documented `GET /api/translate` in `client/README.md`: the check order, the query rules, how Engine answers become `ready`, `none` or 502, and the 20 s bridge call. Also added it to the 401, Engine-failure, request-id and boundary lists.
- [x] `engine/server/README.md` - updated: engine/server/README.md: documented `/internal/translate` and `subtitles.db`, and corrected the opening "read-only" claim.
- [x] `client/frontend/README.md` - updated: Added the video page's Translate toggle and overlay to `client/frontend/README.md`, and added `/api/translate` to the list of gateway routes.
- [x] `README.md` - updated: README.md: added the translate routes to the Engine/Client boundary table and reworded the `engine/server/` line, which no longer says "read-only".
- [x] `DEPLOYMENT.md` - updated: I added the Translate feature to DEPLOYMENT.md in six places. I checked each fact against the code, not just the change report.
- [x] `DATA_BUILD.md` - updated: I added `subtitles.db` to the Outputs section of `DATA_BUILD.md` as a runtime cache that no build step makes.
- [x] `CONTEXT.md` - updated: I added three glossary terms to `CONTEXT.md`: **Translate**, **Translate state** and **Instance caption track**.
- [x] `docs/project/roadmap.md` - updated: Roadmap now records the Translate overlay (B1) as delivered under F11-M2, with Whisper generation (plans 49/50) and the player still listed as remaining.
- [x] `docs/project/plans/49-translate-whisper-worker.md` - updated: Plan 49 now matches what B1 shipped: the `subtitles` schema, the single `cues_json` blob, WAL left to this plan, where the shared code lives, and B1's archived path.
- [x] `docs/project/plans/50-translate-generation-in-page.md` - updated: Plan 50 now matches what B1 shipped: route names, the allow-list entry, the 404 mapping, the two validators to widen and the cue list. The B1 citation points at its archive path.
- [x] `docs/project/plans/18-english-subtitles.md` - updated: I updated plan 18: B1 is now marked delivered and points at its archived path, and P1 says the shipped store keeps cues in rows, with no `.vtt` directory.
- [x] `docs/project/plans/48-translate-instance-captions.md` - updated: I copied plan 48 into `docs/project/plans/archive/48-translate-instance-captions.md`, but the original at `docs/project/plans/48-translate-instance-captions.md` still has to be deleted, because I have no delete tool.
- [x] `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md` - out of scope: This ADR decides the deploy topology. Its Consequences mention only the random cache built per instance during the overlap. Both instances now write `subtitles.db` as well, and the overlap behaviour belongs in DEPLOYMENT.md (listed above); the decision itself is unchanged.
- [x] `docs/project/adr/0007-nsfw-filter-default-at-request-edge.md` - out of scope: This ADR says `/internal/*` reads are not NSFW-filtered. `/internal/translate` applies no NSFW filter, which is consistent with it; the denylist check is operator moderation, not the NSFW filter.
- [x] `docs/project/security-audit/run-2/architecture.md` - out of scope: This is a dated audit snapshot, not a current-state description. It records the architecture at the time of that run and is not maintained as living documentation.

## Implementation plan

## Draft implementation: B1 Translate (instance captions)

### 0. Decisions this draft makes that the plan left open

| Open point (source) | Decision | Why |
|---|---|---|
| R6 paragraph ("state request and `ready` in parallel") vs AC1 / Toggle bullet (inventory: `translate.ts` entry) | **Sequential:** the translate request is sent only after `ready` resolves AND `getProfileKey()` returns a key. The click path and the on-load path use the same function (`turnOn`). | AC1 is a hard requirement and the parallel wording breaks it. Running them in sequence also takes away the ordering race R6 was designed around, so nothing depends on which finishes first. **This deviates from the plan's R6 wording and keeps to AC1.** |
| Client 404 mapping (inventory: `engine_api_client.py`) | Only a 404 whose body is exactly `{"error": "Video not found"}` maps to `none`. Any other 404 (for example an Engine without the route) becomes a logged 502. | Version skew shows up as an error instead of a silent `none`. The string is pinned on both sides: `VIDEO_NOT_FOUND` in the Engine and `TRANSLATE_NOT_FOUND_ERROR` in the Client, each with a test. |
| Where the fetch and parser live (plan 49 reuse) | In the handler module `handlers/internal_translate.py`, the element the inventory names. The module is numpy-free and imports only `data.*`, `http_utils` and `handlers.video`, so a plan-49 worker can import it. Moving it to `data/` is plan 49's call. | Fewest files. The design debt is recorded in plan 49's reconcile note. |
| `fileUrl` with userinfo or a port | Refused if it has any explicit port (443 included), or any username or password. The host is compared through `.hostname`. | It is the strictest rule and costs one line. Ceiling: an instance that publishes `https://host:443/...` answers `none`. |
| Port in `instance_domain` (uncertain) | The lookup uses the normalised (port-less) host. | **Named ceiling:** a video whose stored `instance_domain` carries a port never matches and always answers `none`. The upgrade is to retry the lookup with the raw lowercased request host. |
| Deadline beyond one `read` | `read1()` in chunks. Each fetch has an 8 s wall-clock deadline, and the whole request has a 15 s budget. The socket timeout is 4 s per operation. | Worst case is about 15 + 4 = 19 s, which is under the Client's 20 s. **Accepted gap:** DNS resolution (`getaddrinfo`) and a TLS handshake that stalls across several records are not covered by the wall clock. This is stated in the docstring. |
| `journal_mode=WAL` | Not set in B1. Plan 49 owns it. | Setting it would need a write lock on first open, which adds contention when eight Engines start at once. |
| Denylist check vs `enable_instance_ignore` | The check is unconditional. | A remote fetch should never go to a denied host, whatever the serving filter flag says. Blocked channels are **not** checked: an operator-blocked channel's video can still be translated (named limitation). |
| Engine with no `subtitles_db` (constructor stand-ins in tests) | It still fetches and answers, but neither reads nor writes the cache. | This is the clean degrade the inventory asks for. |

### 1. Module map

| File | Change |
|---|---|
| `engine/server/api/handlers/internal_translate.py` | **New.** Handler, bounded fetch, same-host redirect handler, caption pick, WebVTT parser. |
| `engine/server/data/subtitles.py` | **New.** `connect_subtitles_db`, `ensure_subtitles_schema`, `fetch_ready_subtitles`, `store_ready_subtitles`. |
| `engine/server/api/handlers/similar.py` | One import, one `_dispatch_post` branch, one docstring line. |
| `engine/server/api/handlers/__init__.py` | One docstring line. |
| `engine/server/api/server_config.py` | `DEFAULT_SUBTITLES_DB_PATH`. |
| `engine/server/api/server.py` | Open/ensure after the `random_cache_path.parent.mkdir`, attach after the server is constructed, close in `finally`; lock in `SimilarServer.__init__`. |
| `client/backend/lib/engine_api_client.py` | `fetch_translate`, `_is_seconds`, two constants, `import math`. |
| `client/backend/server.py` | `_sanitize_query` helper (GET proxy switched to it), `/api/translate` branch + `_handle_translate_get`, allow-list entry, import. |
| `client/frontend/package.json` (+ lock) | `@peertube/embed-api`. |
| `client/frontend/src/data/translate.ts` | **New.** Setting + `fetchTranslate`. |
| `client/frontend/src/pages/video-page/translate.ts` | **New.** Player, toggle, sync, overlay. |
| `client/frontend/src/pages/video-page/index.ts` | One import; the embed block rewritten to add `api=1` and call `setupTranslate`. |
| `client/frontend/video-page.html` | Toggle button, status span, overlay div. |
| `client/frontend/src/video.css` | `.translate-overlay`. |
| `client/frontend/dist/` | Rebuilt **last**. |
| `tests/config.json`, `tests/check-frontend-client-gateway.sh` | Mappings; forbidden-route pattern. |
| New tests | `tests/active/test_internal_translate.py`, `tests/active/test_translate_gateway.py`, `tests/active/test_frontend_translate.py`. |

Not changed: `video.py` (`fetch_instance_json` untouched), `moderation.py`, `db.py`, `.gitignore`, `worktree-setup.sh`.

### 2. Engine

#### 2.1 `engine/server/api/handlers/internal_translate.py`

```python
"""Internal translate endpoint: the English caption track a video's own instance holds, fetched within bounds, parsed as WebVTT once, cached in subtitles.db.

POST /internal/translate {id, host} answers {"state": "ready", "cues": [{start, end, text}]} or {"state": "none"}. An unknown or denylisted video answers 404 {"error": "Video not found"} before any remote fetch; the Client reads that one body as none. Only ready is stored; every failure is none and is never stored, so a track added later can still change the answer.

Bounds (AC6): https only, to the resolved row's instance_domain only, no redirect off that host, 2 MB per response, an 8 s wall-clock deadline per fetch inside a 15 s budget per request, 4 s per socket operation. Not bounded by the wall clock: DNS resolution inside urlopen and a TLS handshake stalling across several records (stdlib has no DNS timeout); accepted gap.
"""
from __future__ import annotations

import html
import http.client
import json
import logging
import re
import sqlite3
import time
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from data.db import statement_deadline
from data.moderation import list_active_denied_hosts, normalize_host
from data.subtitles import fetch_ready_subtitles, store_ready_subtitles
from data.time import now_ms
from handlers.video import resolve_video_row
from http_utils import read_json_body, respond_json
from server_config import DEFAULT_STATEMENT_TIMEOUT_SECONDS

TARGET_LANGUAGE = "en"
SOURCE_INSTANCE = "instance"
FETCH_MAX_BYTES = 2_000_000
FETCH_DEADLINE_SECONDS = 8.0
# Two fetches share it, so the Client's 20 s timeout covers the budget plus one socket timeout past it.
REQUEST_BUDGET_SECONDS = 15.0
SOCKET_TIMEOUT_SECONDS = 4.0
READ_CHUNK_BYTES = 65_536
# The body resolve_video_row answers; the Client maps exactly this 404 to none (TRANSLATE_NOT_FOUND_ERROR in client/backend/lib/engine_api_client.py).
VIDEO_NOT_FOUND = {"error": "Video not found"}
_HEADER = re.compile(r"WEBVTT(?:[ \t].*)?")
_SKIPPED_BLOCK = re.compile(r"(?:NOTE|STYLE|REGION)(?:[ \t].*)?")
_TIMESTAMP = r"(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})"
_TIMING_LINE = re.compile(rf"{_TIMESTAMP}[ \t]+-->[ \t]+{_TIMESTAMP}(?:[ \t].*)?")
_TAG = re.compile(r"<[^>]*>")


def _stripped(value: Any) -> str | None:
    """Return a non-empty stripped string, or None."""
    return (value.strip() or None) if isinstance(value, str) else None


def same_host_https(url: str, host: str) -> bool:
    """Whether url is https on exactly host, with no explicit port and no userinfo (R5)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == host and port is None and parts.username is None and parts.password is None


class SameHostRedirectHandler(HTTPRedirectHandler):
    """Follow a redirect only to https on the same host; any other target ends the fetch as an HTTPError."""

    def __init__(self, host: str) -> None:
        """Bind the handler to the one host its fetch may reach."""
        super().__init__()
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        """Refuse an off-host or non-https target; None makes urllib raise the 3xx as an HTTPError."""
        if not same_host_https(newurl, self.host):
            logging.info("[translate] refused redirect host=%s target=%s", self.host, newurl)
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bounded(host: str, path: str, budget_at: float) -> bytes | None:
    """GET https://<host><path> within the AC6 bounds; None on any failure, non-200, a body over FETCH_MAX_BYTES, or a passed deadline."""
    deadline = min(time.monotonic() + FETCH_DEADLINE_SECONDS, budget_at)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    request = Request(f"https://{host}{path}", headers={"accept": "application/json, text/vtt"})
    chunks: list[bytes] = []
    size = 0
    try:
        with build_opener(SameHostRedirectHandler(host)).open(request, timeout=min(SOCKET_TIMEOUT_SECONDS, remaining)) as resp:
            if resp.status != 200:
                return None
            length = (resp.headers.get("content-length") or "").strip()
            if length.isdigit() and int(length) > FETCH_MAX_BYTES:
                logging.info("[translate] response over cap host=%s path=%s length=%s", host, path, length)
                return None
            while True:
                if time.monotonic() > deadline:
                    logging.info("[translate] fetch deadline passed host=%s path=%s", host, path)
                    return None
                # read1 returns what has arrived, so a trickling server cannot hold one read open past the deadline for more than one socket timeout.
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > FETCH_MAX_BYTES:
                    logging.info("[translate] response over cap host=%s path=%s", host, path)
                    return None
                chunks.append(chunk)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        # OSError covers HTTPError, URLError, timeouts, resets and ssl errors; ValueError covers InvalidURL and IDNA UnicodeError; HTTPException covers IncompleteRead and RemoteDisconnected.
        logging.info("[translate] instance fetch failed host=%s path=%s: %s", host, path, exc)
        return None
    return b"".join(chunks)


def pick_english_track_path(listing: bytes, host: str) -> str | None:
    """Return the path of the first caption whose language.id is exactly en, or None; a path that is not same-host https is refused (R5)."""
    try:
        payload = json.loads(listing.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    for item in data:
        language = item.get("language") if isinstance(item, dict) else None
        if isinstance(language, dict) and language.get("id") == TARGET_LANGUAGE:
            return _track_path(item, host)
    return None


def _track_path(item: dict[str, Any], host: str) -> str | None:
    """captionPath when it is a rooted path (not protocol-relative), else fileUrl's path when fileUrl is same-host https."""
    caption_path = item.get("captionPath")
    if isinstance(caption_path, str) and caption_path.startswith("/") and not caption_path.startswith("//"):
        return caption_path
    file_url = item.get("fileUrl")
    if isinstance(file_url, str) and same_host_https(file_url, host):
        parts = urlsplit(file_url)
        return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return None


def _seconds(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    """Convert one parsed WebVTT timestamp to seconds."""
    return round(int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000, 3)


def _blocks(lines: list[str]) -> list[list[str]]:
    """Split lines into blocks separated by blank lines."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def parse_webvtt(text: str) -> list[dict[str, Any]] | None:
    """Parse a WebVTT track into cues {start, end, text} sorted by start, or None when any part fails (whole-track rejection, AC6) or no cue has text.

    The first line must be WEBVTT, optionally followed by a space or tab and text. After the header block, every block is a NOTE/STYLE/REGION block (skipped) or a cue: an optional identifier without "-->", then a timing line. Anything else rejects the track, and so does an end before its start. Cue text has its tags removed and its entities decoded; it is still untrusted and rendered with textContent only.
    """
    lines = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not _HEADER.fullmatch(lines[0]):
        return None
    cues: list[dict[str, Any]] = []
    for block in _blocks(lines)[1:]:
        if _SKIPPED_BLOCK.fullmatch(block[0]):
            continue
        timing_at = 0 if "-->" in block[0] else 1
        match = _TIMING_LINE.fullmatch(block[timing_at]) if len(block) > timing_at else None
        if match is None:
            return None
        start = _seconds(*match.group(1, 2, 3, 4))
        end = _seconds(*match.group(5, 6, 7, 8))
        if end < start:
            return None
        cue_text = html.unescape(_TAG.sub("", "\n".join(block[timing_at + 1:]))).strip()
        if cue_text:
            cues.append({"start": start, "end": end, "text": cue_text})
    # The page binary-searches by start, so the order is fixed here, once.
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    return cues or None


def fetch_instance_track(host: str, video_key: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Read host's caption list for video_key, fetch its first en track and parse it; the track text and cues, or None."""
    budget_at = time.monotonic() + REQUEST_BUDGET_SECONDS
    listing = fetch_bounded(host, f"/api/v1/videos/{quote(video_key, safe='')}/captions", budget_at)
    path = pick_english_track_path(listing, host) if listing is not None else None
    raw = fetch_bounded(host, path, budget_at) if path is not None else None
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    cues = parse_webvtt(text)
    return (text, cues) if cues is not None else None


def _cached_cues(server: Any, video_id: str, instance_domain: str) -> list[dict[str, Any]] | None:
    """The stored ready cues, or None on a miss, with no store attached, or on a store error."""
    lock = getattr(server, "subtitles_db_lock", None)
    if lock is None or getattr(server, "subtitles_db", None) is None:
        return None
    try:
        with lock:
            conn = server.subtitles_db
            return fetch_ready_subtitles(conn, video_id, instance_domain, TARGET_LANGUAGE) if conn is not None else None
    except sqlite3.Error as exc:
        logging.warning("[translate] cache read failed video_id=%s host=%s: %s", video_id, instance_domain, exc)
        return None


def _store_cues(server: Any, video_id: str, instance_domain: str, track_text: str, cues: list[dict[str, Any]]) -> None:
    """Store a ready track; a failed write (e.g. locked by the other blue/green Engine) is logged and the answer stays ready."""
    lock = getattr(server, "subtitles_db_lock", None)
    if lock is None or getattr(server, "subtitles_db", None) is None:
        return
    try:
        # A fresh budget: the request's own deadline was spent on the instance, as in persist_video_metadata.
        with statement_deadline(getattr(server, "statement_timeout_seconds", DEFAULT_STATEMENT_TIMEOUT_SECONDS)), lock:
            conn = server.subtitles_db
            if conn is not None:
                store_ready_subtitles(conn, video_id, instance_domain, TARGET_LANGUAGE, SOURCE_INSTANCE, track_text, cues, now_ms())
    except sqlite3.Error as exc:
        logging.warning("[translate] cache write failed video_id=%s host=%s: %s", video_id, instance_domain, exc)


def handle_internal_translate(handler: Any, server: Any) -> bool:
    """Answer a video's English translate state; no remote fetch happens until the video resolves and its host is not denied."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True
    video_id = _stripped(body.get("id"))
    raw_host = _stripped(body.get("host"))
    if video_id is None or raw_host is None:
        respond_json(handler, 400, {"error": "Missing id or host"})
        return True
    host = normalize_host(raw_host)
    if host is None:
        respond_json(handler, 400, {"error": "Invalid host"})
        return True
    resolved = resolve_video_row(handler, server, {"id": [video_id], "host": [host]})
    if resolved is None:
        return True
    row = resolved[0]
    # Never the request host or resolve_video_row's fallback: the fetch goes to the row's own domain.
    instance = row.get("instance_domain") or ""
    canonical_id = str(row.get("video_id") or "")
    with server.db_lock:
        denied = list_active_denied_hosts(server.db)
    if not instance or not canonical_id or normalize_host(instance) in denied:
        respond_json(handler, 404, VIDEO_NOT_FOUND)
        return True
    cues = _cached_cues(server, canonical_id, instance)
    if cues is None:
        fetched = fetch_instance_track(instance, str(row.get("video_uuid") or canonical_id))
        if fetched is None:
            respond_json(handler, 200, {"state": "none"})
            return True
        track_text, cues = fetched
        _store_cues(server, canonical_id, instance, track_text, cues)
    respond_json(handler, 200, {"state": "ready", "cues": cues})
    return True
```

Invariants:
- The lookup host is the normalised request host. Because `fetch_video_row` compares exactly, a row that resolves always has `instance_domain == host` (lowercase, no port). So `SameHostRedirectHandler` and `_track_path` compare against an already-normalised value.
- `db_lock` is held only inside `resolve_video_row` and the denylist read, never across a fetch. `subtitles_db_lock` is held only around a single read or a single upsert.
- Nothing raises out of the handler on network, JSON, parse or store errors. Only the request-deadline `OperationalError` on `server.db`, during the two pre-fetch reads, reaches `_serve_post` (503).
- Patch seams for tests: `internal_translate.fetch_bounded` (handler tests), `internal_translate.build_opener` (fetch tests). `SameHostRedirectHandler.redirect_request` is tested directly.

#### 2.2 `engine/server/data/subtitles.py`

```python
"""Translated caption tracks in engine/server/db/subtitles.db, one row per (video_id, instance_domain, target_language).

B1 writes only state 'ready' with source 'instance'. state and source are plain TEXT with no CHECK, so plan 49 adds its job states and the 'whisper' source to this table without a rebuild. cues_json is one compact JSON array per row; plan 49's per-chunk appends need a cue table or a blob rewrite (recorded in plan 49).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

# Longer than sqlite3's 5 s default: several Engines may create the table at once on a fresh file, and two blue/green Engines write it.
SUBTITLES_BUSY_TIMEOUT_SECONDS = 30.0


def connect_subtitles_db(path: Path) -> sqlite3.Connection:
    """Open or create the subtitles database; no deadline handler, so statement_deadline does not bound it."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False, timeout=SUBTITLES_BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_subtitles_schema(conn: sqlite3.Connection) -> None:
    """Create the subtitles table if it is missing."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subtitles (
              video_id TEXT NOT NULL,
              instance_domain TEXT NOT NULL,
              target_language TEXT NOT NULL,
              state TEXT NOT NULL,
              source TEXT NOT NULL,
              fetched_at INTEGER NOT NULL,
              track_text TEXT,
              cues_json TEXT,
              PRIMARY KEY (video_id, instance_domain, target_language)
            )
            """
        )


def fetch_ready_subtitles(conn: sqlite3.Connection, video_id: str, instance_domain: str, target_language: str) -> list[dict[str, Any]] | None:
    """The stored cues of a ready row; None for no row, another state, or a cues_json that does not load as a non-empty list."""
    row = conn.execute(
        "SELECT cues_json FROM subtitles WHERE video_id = ? AND instance_domain = ? AND target_language = ? AND state = 'ready'",
        (video_id, instance_domain, target_language),
    ).fetchone()
    if row is None:
        return None
    try:
        cues = json.loads(row["cues_json"] or "")
    except (ValueError, RecursionError):
        return None
    return cues if isinstance(cues, list) and cues else None


def store_ready_subtitles(conn: sqlite3.Connection, video_id: str, instance_domain: str, target_language: str, source: str, track_text: str, cues: list[dict[str, Any]], fetched_at: int) -> None:
    """Upsert a ready row; a concurrent miss on the same key writes the same row twice, harmlessly."""
    with conn:
        conn.execute(
            """
            INSERT INTO subtitles (video_id, instance_domain, target_language, state, source, fetched_at, track_text, cues_json)
            VALUES (?, ?, ?, 'ready', ?, ?, ?, ?)
            ON CONFLICT(video_id, instance_domain, target_language) DO UPDATE SET
              state = excluded.state, source = excluded.source, fetched_at = excluded.fetched_at, track_text = excluded.track_text, cues_json = excluded.cues_json
            """,
            (video_id, instance_domain, target_language, source, fetched_at, track_text, json.dumps(cues, ensure_ascii=False, separators=(",", ":"))),
        )
```

The table is named `subtitles`, matching plan 49 line 98. The connector lives here and not in `db.py`, so the store is one module; `db.py` stays unchanged.

#### 2.3 Wiring

- `server_config.py`, after line 418: `DEFAULT_SUBTITLES_DB_PATH = "engine/server/db/subtitles.db"`.
- `similar.py`:
  - docstring after line 11: `- /internal/translate: internal Client read of a video's English caption cues, from its own instance (cached).`
  - import: `from handlers.internal_translate import handle_internal_translate`.
  - after the `/internal/dislikes/centroids` branch: `if url.path == "/internal/translate": handle_internal_translate(self, self.server); return` (written as three lines in the file's style). The existing bridge gate at line 442 covers it.
- `handlers/__init__.py`: `- internal_translate: bridge read of a video's English caption cues, fetched within bounds from its own instance and cached in subtitles.db.`
- `server.py`:
  - **Imports:** `DEFAULT_SUBTITLES_DB_PATH` in the config import; `from data.subtitles import connect_subtitles_db, ensure_subtitles_schema`.
  - **Path:** after line 341, `subtitles_db_path = (repo_root / DEFAULT_SUBTITLES_DB_PATH).resolve()`.
  - **Open:** right after `random_cache_path.parent.mkdir(...)` (line 363), and therefore after `prepare_trending_override` with the directory guaranteed: `subtitles_db = connect_subtitles_db(subtitles_db_path)` then `ensure_subtitles_schema(subtitles_db)`.
  - **`SimilarServer.__init__`:** no new parameter, so the `dict.fromkeys(signature)` stand-ins are untouched. Add `self.subtitles_db: sqlite3.Connection | None = None` and `self.subtitles_db_lock = threading.Lock()` beside `similarity_db_lock`.
  - **Attach:** after `server.similarity_db_identity = ...`, `server.subtitles_db = subtitles_db`.
  - **`finally`:** after the random-cache close, `with server.subtitles_db_lock: live_subtitles_db = server.subtitles_db; server.subtitles_db = None`, then close it outside the lock when it is not None. This mirrors the similarity block.

### 3. Client gateway

#### 3.1 `client/backend/lib/engine_api_client.py`

```python
# The Engine's translate route spends at most a 15 s fetch budget plus one 4 s socket timeout; scripts/deploy-bluegreen.sh's 30 s drain must stay above this.
TRANSLATE_TIMEOUT_SECONDS = 20
# The 404 body the Engine answers for an unknown or denylisted video (VIDEO_NOT_FOUND in engine/server/api/handlers/internal_translate.py); any other 404, such as an Engine without the route, is a failure.
TRANSLATE_NOT_FOUND_ERROR = "Video not found"


def _is_seconds(value: Any) -> bool:
    """Whether value is a finite JSON number (never a bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fetch_translate(engine_base_url: str, video_id: str, host: str) -> dict[str, Any]:
    """Ask the Engine for a video's English translate state: ``{"state": "ready", "cues": [{start, end, text}]}`` or ``{"state": "none"}``; anything else raises EngineApiError."""
    status, body = _post_json(f"{engine_base_url.rstrip('/')}/internal/translate", {"id": video_id, "host": host}, timeout=TRANSLATE_TIMEOUT_SECONDS)
    if status == 404 and body.get("error") == TRANSLATE_NOT_FOUND_ERROR:
        return {"state": "none"}
    if status != 200:
        message = body.get("error") if isinstance(body, dict) else None
        raise EngineApiError(f"Engine translate failed (HTTP {status}): {message or 'unknown error'}")
    state = body.get("state")
    if state == "none":
        return {"state": "none"}
    cues = body.get("cues")
    if state != "ready" or not isinstance(cues, list):
        raise EngineApiError("Engine translate returned invalid payload")
    checked: list[dict[str, Any]] = []
    for cue in cues:
        if not isinstance(cue, dict) or not _is_seconds(cue.get("start")) or not _is_seconds(cue.get("end")) or not isinstance(cue.get("text"), str):
            raise EngineApiError("Engine translate returned invalid payload")
        checked.append({"start": cue["start"], "end": cue["end"], "text": cue["text"]})
    return {"state": "ready", "cues": checked}
```

`import math` is added. The response size is not capped here: the payload comes from our own Engine and the track is already capped at 2 MB. That is a named ceiling, because `indent=2` pads the response.

#### 3.2 `client/backend/server.py`

- **Import:** add `fetch_translate` to the `lib.engine_api_client` import.
- **Allow-list:** `PROXY_ALLOWED_QUERY_PARAMS["/api/translate"] = {"id", "host"}`. It is **not** in `PROXY_READ_GET_ROUTES`.
- **Helper:** a module-level helper next to `_resolve_mode`. It is a pure function that sends nothing, so it cannot cause a double response:

```python
def _sanitize_query(allowed: set[str], params: dict[str, list[str]]) -> tuple[dict[str, str], str | None]:
    """Keep one value per allowed query parameter, stripped unless in PROXY_UNSTRIPPED_QUERY_PARAMS and dropped when empty; or return the 400 text for the first unknown or repeated parameter.

    It sends nothing, so the caller owns the one response.
    """
    sanitized: dict[str, str] = {}
    for key, values in params.items():
        if key not in allowed:
            return {}, f"Unknown query parameter: {key}"
        if not values:
            continue
        if len(values) != 1:
            return {}, f"Multiple values are not allowed for query parameter: {key}"
        value = values[0] if key in PROXY_UNSTRIPPED_QUERY_PARAMS else values[0].strip()
        if value:
            sanitized[key] = value
    return sanitized, None
```

- **GET proxy:** `_handle_engine_read_proxy_get` lines 538-551 become `sanitized, error = _sanitize_query(PROXY_ALLOWED_QUERY_PARAMS.get(path, set()), params)` then `if error is not None: respond_json(self, 400, {"error": error}); return`. The texts, the order, empty-list skipping, the `nsfw` exemption and empty-value dropping all stay the same. The POST copy stays inline.
- **New `_serve_get` branch,** before the final 404:

```python
        if url.path == "/api/translate":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_translate_get(params)
            return
```

```python
    def _handle_translate_get(self, params: dict[str, list[str]]) -> None:
        """Answer one video's English translate state for the presented profile, from the Engine's /internal/translate."""
        if self._require_profile() is None:
            return
        query, error = _sanitize_query(PROXY_ALLOWED_QUERY_PARAMS["/api/translate"], params)
        if error is None and (set(query) != {"id", "host"} or any(len(value) > BLOCK_REFERENCE_MAX_LENGTH for value in query.values())):
            error = "id and host must be non-empty strings"
        if error is not None:
            respond_json(self, 400, {"error": error})
            return
        try:
            payload = fetch_translate(self.server.engine_ingest_base, query["id"], query["host"])
        except EngineApiError as exc:
            self._respond_engine_failure("translate", exc)
            return
        respond_json(self, 200, payload)
```

The order is 429, then 401, then 400, then the Engine call. An empty param is missing after `parse_qs`, so it gets 400.

### 4. Frontend

#### 4.1 `package.json`

`"@peertube/embed-api": "^<version npm resolves>"` under `dependencies`. Install it with `npm install @peertube/embed-api` from **main's** `client/frontend`, because worktrees symlink `node_modules`. Check that the lockfile diff adds only that package and its dependencies.

Two things must be checked in the installed package before the frontend code lands:
- whether the ESM entry touches anything at import beyond `window.addEventListener` (both node stubs provide that);
- whether it ships `.d.ts` files. No typecheck runs in the build or the tests, so missing types need no shim.

#### 4.2 `src/data/translate.ts`

```ts
/**
 * Module `client/frontend/src/data/translate.ts`: the Translate setting and the gateway read of a video's English cues.
 *
 * The setting lives in this browser only (`translate:v1`), off unless the visitor turned it on; it does not follow the profile key.
 */

import { resolveClientApiBase } from "./api-base";
import { ProfileKeyRejectedError, profileHeaders } from "./profile";

export type TranslateCue = { start: number; end: number; text: string };
export type TranslateState = { state: "ready"; cues: TranslateCue[] } | { state: "none" };

const TRANSLATE_KEY = "translate:v1";

// Set on every change, so the choice holds on this page even when storage refuses the write.
let translateInMemory: boolean | null = null;

/**
 * Whether Translate is on: only a stored "on" means on; missing, unreadable or corrupt storage means off.
 */
export function readTranslate(): boolean {
  if (translateInMemory !== null) return translateInMemory;
  try {
    return window.localStorage.getItem(TRANSLATE_KEY) === "on";
  } catch {
    return false;
  }
}

/**
 * Turn Translate on or off for this page and, when storage allows, for later videos.
 */
export function setTranslate(on: boolean) {
  translateInMemory = on;
  try {
    window.localStorage.setItem(TRANSLATE_KEY, on ? "on" : "off");
  } catch {
    // Ignore storage failures (quota/private mode): the in-memory value above still applies on this page.
  }
}

/**
 * Read a video's English translate state from the Client gateway; a 401 throws ProfileKeyRejectedError, a malformed body throws.
 */
export async function fetchTranslate(apiBase: string, id: string, host: string): Promise<TranslateState> {
  const url = new URL("/api/translate", resolveClientApiBase(apiBase));
  url.searchParams.set("id", id);
  url.searchParams.set("host", host);
  // A none can become ready once a track exists, so a stored answer must never be reused.
  const response = await fetch(url, { headers: profileHeaders(), cache: "no-store" });
  if (response.status === 401) throw new ProfileKeyRejectedError("Your profile key is no longer valid");
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : {};
  if (!response.ok) {
    const message = (payload as { error?: unknown }).error;
    throw new Error(typeof message === "string" ? message : `Translate request failed (${response.status})`);
  }
  return parseTranslateState(payload);
}

/**
 * Check the gateway's payload rather than trust it; cues come back sorted by start for the page's binary search.
 */
function parseTranslateState(payload: unknown): TranslateState {
  const body = payload as { state?: unknown; cues?: unknown };
  if (body?.state === "none") return { state: "none" };
  if (body?.state !== "ready" || !Array.isArray(body.cues)) throw new Error("Translate response was malformed");
  const cues = body.cues.map((cue: { start?: unknown; end?: unknown; text?: unknown }) => {
    if (!Number.isFinite(cue?.start) || !Number.isFinite(cue?.end) || typeof cue?.text !== "string") throw new Error("Translate response was malformed");
    return { start: cue.start as number, end: cue.end as number, text: cue.text };
  });
  return { state: "ready", cues: cues.sort((a, b) => a.start - b.start || a.end - b.end) };
}
```

#### 4.3 `src/pages/video-page/translate.ts`

```ts
/**
 * Module `client/frontend/src/pages/video-page/translate.ts`: the Translate toggle and the English line shown over the embedded player.
 *
 * One PeerTubePlayer is built per page, on #video-embed, right after its api=1 src is set. A second one on the same iframe window throws, and destroy() removes the iframe, so neither is ever done. The toggle shows only once the embed API's `ready` resolved and a profile key is held; before that no translate request is made (AC1). The on-load path and the click path are the same turnOn, so a page loaded with Translate on behaves like a click (R6).
 */

import { PeerTubePlayer } from "@peertube/embed-api";
import { getProfileKey } from "../../data/profile";
import { fetchTranslate, readTranslate, setTranslate, type TranslateCue } from "../../data/translate";

export type TranslateVideo = { id: string; host: string };

const toggleEl = document.getElementById("translate-toggle") as HTMLButtonElement | null;
const statusEl = document.getElementById("translate-status");
const overlayEl = document.getElementById("translate-overlay");
const NO_TRANSLATION = "No English translation is available for this video.";
// The embed's playbackStatusUpdate is the clock; getCurrentPosition is polled only after this much silence.
const POLL_AFTER_SILENCE_MS = 3000;
const POLL_INTERVAL_MS = 1000;

let started = false;
let player: PeerTubePlayer | null = null;
let on = false;
let cues: TranslateCue[] = [];
// Bumped by every turn-on and turn-off, so the reply to an earlier request is dropped.
let requestTicket = 0;
let lastUpdateAt = 0;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let pollInFlight = false;

/**
 * The embed URL with api=1 set, correct with or without an existing query; null when it does not parse.
 */
export function withEmbedApi(embed: string): string | null {
  try {
    const url = new URL(embed.trim());
    url.searchParams.set("api", "1");
    return url.href;
  } catch {
    return null;
  }
}

/**
 * Bind the embed API to the iframe once per page and show the toggle when it answers; never throws.
 */
export function setupTranslate(iframe: HTMLIFrameElement, apiBase: string, video: TranslateVideo): void {
  if (started || !toggleEl || !overlayEl) return;
  started = true;
  let created: PeerTubePlayer;
  try {
    created = new PeerTubePlayer(iframe);
  } catch {
    // jschannel throws strings, not Errors, when this window or the iframe cannot post messages; the page works on with no toggle (R1).
    return;
  }
  // A rejected ready is caught here, so it never surfaces as an unhandled rejection; one that never settles leaves the toggle hidden.
  created.ready.then(() => onReady(created, apiBase, video), () => undefined);
}

/**
 * Binary-search cues sorted by start for the latest-started cue, and return it when it contains position.
 */
export function findCue(sorted: TranslateCue[], position: number): TranslateCue | null {
  let low = 0;
  let high = sorted.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (sorted[mid].start <= position) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  const cue = found >= 0 ? sorted[found] : null;
  return cue && position < cue.end ? cue : null;
}

function onReady(ready: PeerTubePlayer, apiBase: string, video: TranslateVideo) {
  if (!toggleEl || !getProfileKey() || !video.id || !video.host) return;
  player = ready;
  // Subscribed once and never removed; updates are ignored while Translate is off.
  ready.addEventListener("playbackStatusUpdate", (status: unknown) => {
    lastUpdateAt = Date.now();
    showAt(finiteNumber((status as { position?: unknown } | null)?.position));
  });
  toggleEl.addEventListener("click", () => {
    if (on) turnOff();
    else void turnOn(apiBase, video);
  });
  renderToggle();
  toggleEl.hidden = false;
  if (readTranslate()) void turnOn(apiBase, video);
}

async function turnOn(apiBase: string, video: TranslateVideo) {
  on = true;
  setTranslate(true);
  renderToggle();
  setStatus("Loading translation…");
  const ticket = ++requestTicket;
  try {
    const state = await fetchTranslate(apiBase, video.id, video.host);
    if (ticket !== requestTicket) return;
    if (state.state === "none") {
      cues = [];
      setStatus(NO_TRANSLATION);
      return;
    }
    cues = state.cues;
    setStatus("");
    startPolling();
  } catch (error) {
    if (ticket !== requestTicket) return;
    setStatus(error instanceof Error ? error.message : "Could not load the translation");
  }
}

function turnOff() {
  on = false;
  requestTicket += 1;
  cues = [];
  setTranslate(false);
  stopPolling();
  renderToggle();
  setStatus("");
  showText("");
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(() => {
    if (!player || pollInFlight || Date.now() - lastUpdateAt < POLL_AFTER_SILENCE_MS) return;
    // getCurrentPosition has no timeout, so one call at a time: a call that never settles stops the fallback instead of stacking.
    pollInFlight = true;
    player.getCurrentPosition().then((position: unknown) => showAt(finiteNumber(position)), () => undefined).finally(() => {
      pollInFlight = false;
    });
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer !== null) clearInterval(pollTimer);
  pollTimer = null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function showAt(position: number | null) {
  if (!on || position === null) return;
  showText(findCue(cues, position)?.text ?? "");
}

// Cue text is untrusted instance text: set with textContent only (R3).
function showText(text: string) {
  if (!overlayEl) return;
  overlayEl.textContent = text;
  overlayEl.hidden = !text;
}

function renderToggle() {
  if (!toggleEl) return;
  toggleEl.setAttribute("aria-pressed", String(on));
  toggleEl.classList.toggle("active", on);
}

function setStatus(text: string) {
  if (statusEl) statusEl.textContent = text;
}
```

A seek needs no special code: the next `playbackStatusUpdate` carries the new position, and the binary search is stateless.

#### 4.4 `index.ts`

- Import: `import { setupTranslate, withEmbedApi } from "./translate";`.
- The embed block at lines 280-289 becomes:

```ts
  if (embedEl) {
    // The embed URL can come straight from the `?embed=` query parameter when
    // metadata resolution fails, so a scheme check is what stops a
    // `javascript:` URL from executing in this origin via iframe navigation.
    const apiEmbed = embed && /^https:\/\//i.test(embed.trim()) ? withEmbedApi(embed) : null;
    if (apiEmbed) {
      embedEl.src = apiEmbed;
      // After the api=1 src is set, never before; setupTranslate binds once per page and never throws, so applyOriginalHref below always runs.
      setupTranslate(embedEl, apiBase, { id: metadata?.videoUuid || resolveVideoSource()?.id || "", host: resolveVideoSource()?.host || "" });
    } else {
      embedEl.removeAttribute("src");
    }
  }
```

The id prefers `videoUuid`, as `enableBlockButtons` does, so `/w/<shortUUID>` pages still resolve. An https-prefixed string that does not parse now leaves no src, where before it set a broken one.

#### 4.5 HTML and CSS

- **`video-page.html`, inside `.player-frame` after the iframe:** `<div id="translate-overlay" class="translate-overlay" hidden></div>`. The sandbox and CSP stay unchanged.
- **`video-page.html`, in `.player-actions` after `#reaction-status`:** `<button id="translate-toggle" class="ghost-button" type="button" aria-pressed="false" hidden>Translate</button>` and `<span id="translate-status" class="block-status" role="status"></span>`.
- **`video.css`, after `.player-frame iframe`.** DOM order puts it above the iframe; a class, never an inline style, because the CSP is `style-src 'self'`:

```css
.translate-overlay {
  position: absolute;
  left: 5%;
  right: 5%;
  bottom: 12%;
  text-align: center;
  pointer-events: none;
  color: #fff;
  font-size: 1.15rem;
  line-height: 1.35;
  white-space: pre-wrap;
  text-shadow: 0 0 4px #000, 0 0 4px #000;
}
```

`.ghost-button` sets no `display`, so `hidden` works on the toggle as it does on `#description-toggle`.

### 5. Tests the build needs (what must be exercised)

**`tests/active/test_internal_translate.py`** runs in-process with no numpy. It uses `SimpleNamespace(db, db_lock, video_error_threshold, subtitles_db, subtitles_db_lock, statement_timeout_seconds)` over a temporary `whitelist.db` (with `videos`, `channels` and `instance_denylist`) and a temporary `subtitles.db`.

- **Parser:**
  - accepts CRLF, a BOM, `WEBVTT - title`, `NOTE`/`STYLE`/`REGION` blocks, a cue identifier, hours present or absent, and `end == start`;
  - sorts cues that arrive out of order;
  - strips tags and decodes entities, so `&lt;i&gt;` becomes the literal `<i>`.
  - Rejects the whole track for: no header, `WEBVTTX`, a leading blank line, two-digit milliseconds, minutes of 60, an end before its start, an identifier containing `-->`, a block with an identifier but no timing, or a stray block with no timing.
  - A track of zero cues, or of cues that are all empty, gives None.
- **Pick:**
  - takes the first `en` entry even when a later one is valid;
  - ignores `en-US`;
  - accepts a `captionPath`;
  - refuses `//evil/x`, falling to `fileUrl`;
  - accepts a same-host `fileUrl` and keeps its query;
  - refuses a `fileUrl` with an off-host, `http`, `:443`, `:8443` or `user@` host;
  - answers None for a non-object body, non-list `data`, invalid UTF-8, or deeply nested JSON (RecursionError).
- **Redirect:** `SameHostRedirectHandler.redirect_request` returns a request for same-host https on 301/302/303/307/308, and None for off-host, http, a port, or userinfo.
- **`fetch_bounded`, with a patched `build_opener` returning a fake response:**
  - non-200 gives None;
  - a `Content-Length` over the cap gives None without reading;
  - chunked bytes over the cap give None;
  - a deadline passed mid-read gives None;
  - each of `URLError`, `HTTPError`, `ConnectionResetError`, `socket.timeout`, `ssl.SSLError`, `http.client.IncompleteRead`, `InvalidURL` and `UnicodeError` raised from `open` or `read1` gives None;
  - an exhausted budget gives None with no `open` call;
  - a call made with the budget nearly spent passes a socket timeout of at most `remaining`.
- **Handler, with `fetch_bounded` patched to record calls:**
  - a body that is bad JSON, non-object, or has a non-numeric `Content-Length` gets 400;
  - a missing or blank `id`/`host` gets 400;
  - a host that normalises to None gets 400;
  - an unknown video gets 404 `Video not found` with **no fetch**;
  - a denylisted host (stored in the denylist uppercase) gets 404 with **no fetch**;
  - an `error_count` over the threshold gets 404;
  - a request host `PEER.Example.` resolves the row `peer.example`, and the fetch goes to `row["instance_domain"]`;
  - the caption-list path uses the uuid, quoted;
  - a miss gives `ready`, stores a row (`state ready`, `source instance`, track text, compact cues), and a second call makes no fetch;
  - every `none` path stores nothing;
  - a corrupt `cues_json` reads as a miss and refetches;
  - a store whose upsert raises `sqlite3.OperationalError("database is locked")` still answers `ready`;
  - `subtitles_db=None` answers without touching the store.
- **Startup:** a variant Engine with `DEFAULT_SUBTITLES_DB_PATH` overridden creates the `subtitles` table. The existing `test_random_cache` eight-Engine start and the `test_server_config` rejected start stay green, which proves the open order and the busy timeout.

**`tests/active/test_translate_gateway.py`** (Client, with a stub Engine recording the requests):

- **Order:** 429 comes before 401; 401 comes before 400 (a keyless request with bad params gets 401).
- **Params:** an unknown param, a repeated `id`, `id=` (blank), a missing `host`, and a 201-character value each get 400 with no Engine call.
- **Engine call:** the request carries `X-Bridge-Token` and `X-Request-ID`, and the body is exactly `{id, host}` after the strip.
- **Mapping:**
  - Engine 404 `Video not found` becomes 200 `none`;
  - Engine 404 `Not found` becomes 502 `Engine translate failed`;
  - an Engine 500, an unreachable Engine, an unknown state, cues that are not a list, a `start` of `true`, and a non-string `text` each become 502;
  - a `ready` passthrough drops any extra cue keys.
- **`FAILURE_ROUTES`:** a row is added in `test_server.py`.
- **Helper extraction:** the existing GET-proxy tests (`test_server.py:1361`, `:1519`) stay green unchanged, which shows the extraction is faithful.

**`tests/active/test_frontend_translate.py`** uses the `test_frontend_video_page.py` runner shape, bundled with `--alias:@peertube/embed-api=<stub>`. The stub records `constructed`, the moment `ready` is awaited, `addEventListener` names, and `getCurrentPosition` calls. It exposes `emit(position)` and a `ready` mode of `resolve`, `reject`, `never` or `throw-in-constructor`. The body carries `embedUrl`.

- **AC1:**
  - no key, with `translate:v1=on`, and `ready` resolving: the toggle stays hidden and there is no `/api/translate`;
  - a key with `ready` never settling: no toggle and no request;
  - a key with `ready` rejecting: no toggle, no request, and `rejections == []`;
  - a constructor that throws a string: no toggle, and `originalHref` is still set.
- **R6 (loaded with Translate on):** the key is set and `translate:v1=on`.
  - Exactly one `/api/translate?id=uuid-1&host=peer.example` is sent, recorded **after** `ready` resolved, and `constructed == 1`.
  - Emitting positions 1.5, 7, then 0.5 (a seek back) shows the matching cue text each time, and an empty, hidden overlay between cues.
  - A cue `<b>x</b>` is shown as a text node with the literal text, and `markupIds` does not include the overlay.
- **Toggle:**
  - with the setting off, the toggle is shown and nothing is requested;
  - a click requests, stores `on`, and sets `aria-pressed=true`;
  - a second click stores `off`, hides the overlay, and a later `emit` changes nothing.
- **`none`:** the status reads exactly "No English translation is available for this video.".
- **401:** the status reads "Your profile key is no longer valid".
- **Embed URL:**
  - `https://h/videos/embed/u` becomes `...?api=1`;
  - `https://h/videos/embed/u?start=10` becomes `...?start=10&api=1`;
  - `javascript:...` sets no src;
  - `https://[bad` sets no src.
- **Polling fallback:** one slow case of about 4 s. With no updates emitted, `getCurrentPosition` is called and its value drives the overlay. A second tick while the first call is unsettled makes no new call.
- **Unit:** `findCue` is checked at a boundary (`start` inclusive, `end` exclusive), before the first cue, and after the last.

**Existing frontend harnesses:** `test_frontend_video_page.py` and `_similars.py` set no embed URL, so the player is never built there. They go red only if the package fails to resolve, or if its ESM entry touches something the stubs lack. Check this right after the install.

### 6. Config, guards and build order

- **`tests/config.json`:**
  - map `internal_translate.py`, `data/subtitles.py`, `server.py` (Engine) and `server_config.py` to `test_internal_translate.py`;
  - map `client/backend/server.py` and `lib/engine_api_client.py` to `test_translate_gateway.py`;
  - map `src/data/translate.ts`, `src/pages/video-page/translate.ts`, `index.ts`, `video-page.html`, `video.css` and `package.json` to `test_frontend_translate.py`;
  - add both translate `.ts` files to the `test_frontend_video_page.py`, `test_frontend_video_page_similars.py` and `test_frontend_dist.py` groups;
  - add `client/frontend/package.json` to the `test_frontend_dist.py` group.
- **`tests/check-frontend-client-gateway.sh` line 34:** the pattern becomes `/internal/videos/resolve|/internal/videos/metadata|/internal/events/ingest|/internal/dislikes/centroids|/internal/translate`.
- **Order of work:**
  1. Engine (data, handler, wiring) with its tests.
  2. Client with its tests.
  3. `npm install` in main and the import-side-effect check.
  4. Frontend sources with their tests.
  5. Docs from the settled list.
  6. `vite build` and commit `dist/`, **last**.

### 7. Check against the plan and requirements (pass 2 of at most 3: converged)

| Requirement | Where met |
|---|---|
| AC1: toggle only after `ready` + key; label "Translate"; no request otherwise | `onReady` guard; HTML label; `turnOn` is reachable only from `onReady` |
| AC2: caption list → first `en` → validate → parse → cache keyed `(video_id, instance_domain, en)` | `fetch_instance_track`, `pick_english_track_path`, `parse_webvtt`, `_store_cues` with the row's `video_id` |
| AC3: GET route, `_require_profile`, `ready`+cues / `none`; browser never reads the instance | `_handle_translate_get`; `fetchTranslate` targets only `/api/translate` |
| AC4: overlay at the current position, updates on play and seek, `textContent`, `none` message | `playbackStatusUpdate` → `findCue` → `showText`; `NO_TRANSLATION` |
| AC5: `localStorage` `translate:v1`, NSFW pattern, no schema change | `readTranslate`/`setTranslate` |
| AC6: same host, whitelisted and not denied, https, no off-host redirect, timeout, 2 MB, whole-track rejection | row resolution + denylist before any fetch; `SameHostRedirectHandler`; `fetch_bounded`; `parse_webvtt` returns None |
| Engine: dispatch behind the bridge gate, sibling module, `normalize_host`, `resolve_video_row`, `fetch_instance_json` untouched, `none` never cached, stdlib | §2 |
| Storage: separate `subtitles.db`; state/source/fetched_at/track/cues; plan-49-extensible; private per worktree | §2.2, §2.3 |
| Client: allow-list entry, 400 rules, rate limit, bridge pattern, fixed 502 | §3 |
| Frontend: dependency, `api=1` either way, sandbox kept, one player, CSS in `video.css`, R6 exercised | §4, §5 |

Pass 1 found three gaps, and this draft fixes them:
- the parallel R6 request broke AC1, so the requests are now sequential;
- `resp.read(n)` could block well past the deadline on a trickling server, so it is now `read1`;
- `json.loads` on nested input raises RecursionError, which is not a ValueError and would have dropped the connection, so it is now caught.

### 8. Named ceilings and simplifications

- **Port-bearing domains:** a stored `instance_domain` with a port never resolves, so it always answers `none`.
- **`fileUrl` ports:** any explicit port is refused, 443 included.
- **Unbounded steps:** DNS and a stalled multi-record TLS handshake are outside the wall-clock bound.
- **Overlapping cues:** only the latest-started cue that contains the position is shown.
- **Response size:** the cue list is sent `indent=2` from the Engine and is not capped in the Client.
- **Blocked channels:** they are not checked for translate.
- **Stored rows:** rows of a denied or purged host stay in `subtitles.db`, never served (no pruning, which is out of scope).
- **Re-fetch on every turn-on:** `/api/translate` is called each time Translate is turned on. The Engine cache absorbs `ready`, while `none` repeats both instance reads.
- **Polling:** the fallback stops for good if one `getCurrentPosition` never settles.
- **Plan 49 debts, recorded in its reconcile note:**
  - the single `cues_json` blob is not append-friendly;
  - WAL is left for plan 49 to set;
  - the fetch and parser live in an `api/handlers/` module.

### Phases

#### Phase 1 - Engine fetch and WebVTT parse [code]

**Files touched.** engine/server/api/handlers/internal_translate.py (NEW), tests/active/test_internal_translate.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the module functions of `engine/server/api/handlers/internal_translate.py`, called directly (rung 1). New file `tests/active/test_internal_translate.py`, in-process, no numpy. Network is shimmed only at `internal_translate.build_opener`, which returns a fake response with `status`, `headers` and a scripted `read1`, plus a monotonic clock the test can advance. `SameHostRedirectHandler.redirect_request` is called directly. Clause 1 asserts: (a) a track with CRLF, a BOM, a `WEBVTT - title` header, NOTE/STYLE/REGION blocks, a cue id, hours present and absent, and out-of-order cues parses to `{start,end,text}` floats sorted by start, which excludes an unsorted or string-timed output; (b) `<b>x</b>&lt;i&gt;` becomes the plain text `x<i>`, which excludes leaving tags in or skipping entity decoding; (c) parametrized whole-track rejection gives None for a missing header, `WEBVTTX`, a leading blank line, two-digit ms, minutes of 60, end before start, an id containing `-->`, an id with no timing, and a stray block, which excludes a parser that drops bad cues and keeps the rest; (d) a track of zero cues or only empty cues gives None. Clause 2 asserts None for each of: a redirect to an off-host, http, ported or userinfo target, where `redirect_request` returns None for each and a request for a same-host https target, so both halves are covered; a `Content-Length` over 2 MB with no `read1` call made; chunked bytes over the cap; a deadline passed mid-read; and an exhausted budget with no `open` call. A control case returns the joined bytes, which excludes an implementation that always returns None. The caption pick (first exact `en`, captionPath / same-host fileUrl only) is asserted here as a supporting case of clause 1's input path.

**Intent.** `internal_translate.py` holds a bounded same-host https fetch and a strict WebVTT parser, so an instance's English track becomes sorted plain-text cues and anything outside the AC6 bounds becomes None.

- C1 - `parse_webvtt` turns a well-formed track into plain-text cues sorted by start, and rejects the whole track as None when any block fails.
- C2 - `fetch_bounded` returns None for an off-host or non-https redirect, a body over 2 MB, or a passed wall-clock deadline.

**Outcome.** ### `engine/server/api/handlers/internal_translate.py` (NEW)
This is the phase-1 part of the plan's §2.1 module. It holds the bounded fetch, the caption pick and the parser. It has no handler, cache or DB code, because those belong to phase 2. The module uses only the stdlib and does not import numpy or `data.*` yet.
- `same_host_https(url, host)` is true only when the scheme is `https`, the hostname is exactly `host`, and the URL has no explicit port and no userinfo. A URL that won't parse gives False.
- `SameHostRedirectHandler(host)` is an `HTTPRedirectHandler` subclass. For a target that fails `same_host_https`, `redirect_request` logs the refusal and returns None, which makes urllib raise the 3xx as an `HTTPError` without opening the target. Any other target is passed to the stdlib's own `redirect_request`, which handles 301, 302, 303, 307 and 308 (I checked 308 on this Python, 3.14.7). urllib turns a relative `Location` into an absolute URL before this check runs.
- `fetch_bounded(host, path, budget_at)` opens `https://<host><path>` through `build_opener(SameHostRedirectHandler(host))`. That is a module-level name, so the checkpoint can stand in for it.
  - **Deadline:** `min(now + FETCH_DEADLINE_SECONDS (8.0), budget_at)`, read from `time.monotonic()`. If the deadline has already passed, it returns None before opening anything. The socket timeout is `min(4.0, remaining)`.
  - **Response checks:** a status other than 200 gives None. A declared `Content-Length` over `FETCH_MAX_BYTES` (2,000,000) gives None before any read.
  - **Reading:** it then reads in `read1(65_536)` chunks. Before each read it checks the deadline, and after each read it adds to a running byte count that must not pass the cap.
  - **Errors:** `OSError`, `ValueError` and `http.client.HTTPException` are logged and give None. `OSError` covers `HTTPError` from a refused redirect, plus URL errors, timeouts and SSL errors.
  - Otherwise it returns the chunks joined.
- `pick_english_track_path(listing, host)` decodes the listing JSON and takes the first entry in `data` whose `language.id` is exactly `en`.
  - `_track_path` returns that entry's `captionPath` if it is a rooted path and not protocol-relative.
  - Otherwise it returns the path (plus any query) of a `fileUrl` that passes `same_host_https`.
  - Anything else gives None, as do bad JSON and a payload with the wrong shape.
- `parse_webvtt(text)` drops a leading BOM and normalises CRLF/CR line endings.
  - **Header:** the first line must fully match `WEBVTT` or `WEBVTT<space|tab>…`. The rest of the text is split into blocks separated by blank lines.
  - **Blocks:** after the header block, each block is either skipped as NOTE/STYLE/REGION or must be a cue. A cue is an optional identifier line with no `-->`, then a timing line that fully matches `[hh:]mm:ss.mmm --> [hh:]mm:ss.mmm [settings]`. Minutes and seconds must be 00–59 and milliseconds must be exactly 3 digits.
  - **Whole-track rejection:** a block that fails these rules, or an end before its start, makes the whole track None.
  - **Cue text:** tags are stripped and then entities are decoded with `html.unescape`. A cue with empty text is dropped.
  - **Output:** times are floats rounded to ms, and cues are sorted by `(start, end)`. An empty result gives None.
- Constants: `TARGET_LANGUAGE`, `FETCH_MAX_BYTES`, `FETCH_DEADLINE_SECONDS`, `SOCKET_TIMEOUT_SECONDS`, `READ_CHUNK_BYTES`. `REQUEST_BUDGET_SECONDS`, `VIDEO_NOT_FOUND`, `fetch_instance_track` and the handler are left for phase 2, which is where their callers arrive.

### `tests/tmp/probe_redirect_308.py` (NEW, throwaway)
This probe checked that the stdlib `redirect_request` returns a `Request` for all of 301, 302, 303, 307 and 308 on Python 3.14.7, and that `HTTPError` is an `OSError`. It can be deleted: I have no delete tool, and nothing depends on it.

### `tests/active/test_internal_translate.py`, `tests/config.json`
I did not touch these in this step. The step asks for production code only, and the gating checkpoint lives in `tests/tmp/`. Copying it into `tests/active/test_internal_translate.py` and mapping `engine/server/api/handlers/internal_translate.py` to it in `test_groups` is left for the build's promotion step.

**Beyond the files named.** tests/tmp/probe_redirect_308.py: a throwaway probe in the working directory, used to check urllib's 308 handling before relying on it. Not production code, and it can be deleted.

#### Phase 2 - Engine translate route and subtitles store [code]

**Files touched.** engine/server/api/handlers/internal_translate.py (EDITED), engine/server/data/subtitles.py (NEW), engine/server/api/handlers/similar.py (EDITED), engine/server/api/handlers/__init__.py (EDITED), engine/server/api/server_config.py (EDITED), engine/server/api/server.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: `handle_internal_translate(handler, server)`, the handler entry that `_dispatch_post` calls behind the bridge gate. It follows the harness in `tests/active/test_internal_client_reads.py`: a `Request` stand-in capturing responses, and `SimpleNamespace(db, db_lock, video_error_threshold, subtitles_db, subtitles_db_lock, statement_timeout_seconds)` over a temporary whitelist.db (videos, channels, instance_denylist) and a temporary subtitles.db. `internal_translate.fetch_bounded` is patched to record calls and serve a canned caption list and track. Clause 1 asserts, for an unknown video AND for a host that is in the denylist (stored uppercase), the response is 404 with the body exactly `{"error": "Video not found"}` and the recorded fetch list is empty. A control asserts that a resolved, non-denied video does fetch, and that the fetch goes to the row's `instance_domain` when the request host is `PEER.Example.`, which excludes a handler that never fetches or that fetches the request host. Clause 2 asserts: (a) a miss answers `ready` with the cues; (b) the subtitles row has `state='ready'`, `source='instance'`, the track text and compact cues_json, keyed on the row's canonical video_id; (c) a second call answers the same cues with zero new fetches; (d) each `none` path (no en track, a track that fails to parse, a failed fetch) answers `{"state":"none"}` and leaves the table empty. Supporting case: a variant Engine started with `DEFAULT_SUBTITLES_DB_PATH` overridden creates the `subtitles` table, using the `test_random_cache` startup precedent, and the existing eight-Engine and rejected-start tests stay green.

**Intent.** The Engine answers `/internal/translate` behind the bridge gate, and makes no remote fetch until the video resolves and its host is not denied. It caches only `ready` answers in a new `subtitles.db` that `server.py` opens at startup.

- C1 - An unknown or denylisted video is answered 404 `Video not found` without any instance fetch.
- C2 - A `ready` answer is stored in `subtitles.db` and served from it on the next request without a fetch, while a `none` answer stores nothing.

**Outcome.** ### `engine/server/api/handlers/internal_translate.py` (EDITED)
Adds the request side on top of phase 1's fetch, pick and parser. Phase 1's functions are unchanged.
- **Module docstring:** now describes the route, the 404 for an unknown or denied video, and that only `ready` is stored. The bounds paragraph now names the row's `instance_domain` and the 15 s per-request budget.
- **New imports:** `sqlite3`, `quote`, `list_active_denied_hosts`/`normalize_host` (`data.moderation`), `fetch_ready_subtitles`/`store_ready_subtitles` (`data.subtitles`), `now_ms` (`data.time`), `resolve_video_row` (`handlers.video`), `read_json_body`/`respond_json` (`http_utils`). Still no numpy, so it loads in-process.
- **New constants:** `SOURCE_INSTANCE = "instance"`, `REQUEST_BUDGET_SECONDS = 15.0`, `VIDEO_NOT_FOUND = {"error": "Video not found"}`.
- **`fetch_instance_track(host, video_key)`:** sets one 15 s monotonic budget. It reads `/api/v1/videos/{quote(video_key, safe='')}/captions` through `fetch_bounded`, picks the `en` path, fetches the track, decodes it as UTF-8 and parses it. It returns `(track_text, cues)`, or None at the first failure.
- **`_cached_cues(server, video_id, instance_domain)`:** reads one `ready` row under `subtitles_db_lock`. A closed store (`subtitles_db` None) or an `sqlite3.Error` is logged and treated as a miss, so the instance answers instead of the connection dropping.
- **`_store_cues(...)`:** one upsert under `subtitles_db_lock`. An `sqlite3.Error` (for example a lock held by the other blue/green Engine) is logged, and the answer stays `ready`.
- **`handle_internal_translate(handler, server)`:**
  - A body `read_json_body` rejects gets 400 with its message. A missing or blank `id`/`host` gets 400 `Missing id or host`, and a host `normalize_host` rejects gets 400 `Invalid host`.
  - The row is resolved with `resolve_video_row` on `{"id": [id], "host": [normalised host]}`, which sends its own 404 `Video not found`.
  - `list_active_denied_hosts` is read under `db_lock`. If `normalize_host(row["instance_domain"])` is denied, it answers the same 404 body.
  - Only after both checks does it read the store, keyed on the row's `video_id` and `instance_domain` (never the request's). A miss fetches from the row's `instance_domain` using `video_uuid`, falling back to `video_id`. `none` is answered and not stored; `ready` is stored and answered.
  - The plan's fresh `statement_deadline` around the store write is left out: the subtitles connection has no progress handler, so it would do nothing.

### `engine/server/data/subtitles.py` (NEW)
- **`connect_subtitles_db(path)`:** `check_same_thread=False`, `sqlite3.Row`, a 30 s busy timeout (`SUBTITLES_BUSY_TIMEOUT_SECONDS`) so Engines starting at once on a fresh file wait instead of failing, and no deadline handler.
- **`ensure_subtitles_schema(conn)`:** `CREATE TABLE IF NOT EXISTS subtitles`. Columns: `video_id`, `instance_domain`, `target_language`, `state`, `source`, `fetched_at`, `track_text`, `cues_json`. The primary key is `(video_id, instance_domain, target_language)`. There is no CHECK on `state`/`source`, so plan 49 can add its states and sources without a rebuild.
- **`fetch_ready_subtitles(conn, video_id, instance_domain, target_language)`:** returns the cues of a `state='ready'` row. None if there is no row, or if `cues_json` does not load as a non-empty list.
- **`store_ready_subtitles(conn, ..., source, track_text, cues, fetched_at)`:** an `ON CONFLICT ... DO UPDATE` upsert of a `ready` row, committed. `cues_json` is compact JSON (`separators=(",", ":")`, `ensure_ascii=False`).
- WAL is not set; plan 49 owns that.

### `engine/server/api/handlers/similar.py` (EDITED)
- A docstring route line for `/internal/translate`.
- The import `from handlers.internal_translate import handle_internal_translate`.
- In `_dispatch_post`, an `if url.path == "/internal/translate"` branch after `/internal/dislikes/centroids`. It sits behind the existing `/internal/` bridge-token gate, so no new auth code was needed.

### `engine/server/api/handlers/__init__.py` (EDITED)
One docstring line for `internal_translate`.

### `engine/server/api/server_config.py` (EDITED)
`DEFAULT_SUBTITLES_DB_PATH = "engine/server/db/subtitles.db"` beside `DEFAULT_RANDOM_CACHE_DB_PATH`. Variant runners can override it by name.

### `engine/server/api/server.py` (EDITED)
- **Imports:** `DEFAULT_SUBTITLES_DB_PATH`, `connect_subtitles_db`, `ensure_subtitles_schema`.
- **`SimilarServer.__init__`:** sets `self.subtitles_db = None` and `self.subtitles_db_lock = threading.Lock()`. There is no new constructor parameter, so the `dict.fromkeys(signature)` stand-ins in test_video.py and test_internal_events.py are untouched.
- **`main()`:**
  - resolves `subtitles_db_path` against `repo_root`, so an absolute override stays absolute;
  - opens the DB and ensures the schema right after `random_cache_path.parent.mkdir`, which is after `prepare_trending_override`, so a rejected `--trending-db` start still creates nothing;
  - sets `server.subtitles_db` after construction;
  - in `finally`, swaps the handle to None under `subtitles_db_lock` and closes it outside the lock, as the similarity and random-cache handles are.

### `tests/active/test_internal_translate.py`, `tests/config.json`
Not touched. This step asks for production code only, and the gating checkpoint is in `tests/tmp/`, as in phase 1. Copying the checkpoint into `tests/active/test_internal_translate.py` and mapping `internal_translate.py`, `data/subtitles.py`, `server.py` and `server_config.py` to it in `test_groups` is left to the promotion step.

#### Phase 3 - Client translate gateway [code]

**Files touched.** client/backend/lib/engine_api_client.py (EDITED), client/backend/server.py (EDITED), tests/check-frontend-client-gateway.sh (EDITED), tests/active/test_translate_gateway.py (NEW), tests/active/test_server.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the real Client backend HTTP server, entered over HTTP at `GET /api/translate`, with a `BaseHTTPRequestHandler` EngineStub that records each request, following the EngineStub precedent in `tests/active/test_server.py`. New file `tests/active/test_translate_gateway.py`, plus a `FAILURE_ROUTES` row in test_server.py. Clause 1 asserts each step of the order, with the stub's call count checked as 0 each time: a rate-limited request with no key gets 429, not 401; a keyless request with bad params gets 401, not 400; and an unknown param, a repeated `id`, a blank `id`, a missing `host`, and a 201-character value each get 400. A control asserts that a valid keyed request does reach the stub, carrying `X-Bridge-Token` and `X-Request-ID` and the exact body `{id, host}` after the strip, which excludes a route that never calls the Engine. Clause 2 asserts: an Engine 404 `{"error":"Video not found"}` becomes 200 `{"state":"none"}`; an Engine 404 `Not found` becomes 502 `Engine translate failed`; an Engine 500, an unreachable Engine, an unknown state, non-list cues, a `start` of `true`, and a non-string text each become 502; and a `ready` payload whose cues carry extra keys comes back with only start/end/text. The existing GET-proxy tests (test_server.py around :1361 and :1519) stay green unchanged, which shows the `_sanitize_query` extraction is faithful.

**Intent.** The Client serves `GET /api/translate` to a profile holder, after the rate-limit, profile and param checks, by asking the Engine's bridge route. It maps the Engine's answer to `ready` cues or `none`, and anything else to a 502.

- C1 - `/api/translate` answers 429, then 401, then 400, each before any Engine call is made.
- C2 - An Engine 404 `Video not found` reaches the visitor as `none`, a valid `ready` reaches them with only start, end and text per cue, and any other Engine answer becomes a 502.

**Outcome.** ### `client/backend/lib/engine_api_client.py` (EDITED)
- Added `import math` and two constants. `TRANSLATE_TIMEOUT_SECONDS = 20` is commented as the Engine's 15 s budget plus one 4 s socket timeout, which must stay under the 30 s blue/green drain. `TRANSLATE_NOT_FOUND_ERROR = "Video not found"` is commented as the body the Engine's `VIDEO_NOT_FOUND` sends.
- `_is_seconds(value)`: true only for a finite int or float that is not a bool.
- `fetch_translate(engine_base_url, video_id, host)` POSTs `{"id", "host"}` to `{base}/internal/translate` through the existing `_post_json`, so `bridge_headers()` sends `X-Bridge-Token` and `X-Request-ID`. It uses the 20 s timeout. How it maps the Engine's answer:
  - A 404 whose body `error` is exactly `Video not found` returns `{"state": "none"}`.
  - Any other non-200 raises `EngineApiError("Engine translate failed (HTTP n): …")`. That includes a route-missing 404 `Not found`.
  - A 200 with `state` `none` returns `{"state": "none"}`.
  - A 200 with `state` `ready` must have `cues` as a list of dicts, each with `_is_seconds` start and end and a str text. Otherwise it raises `EngineApiError("Engine translate returned invalid payload")`.
  - Each valid cue is rebuilt as `{start, end, text}`, so extra keys are dropped.
  - A transport failure is already an `EngineApiError` from `_post_json`.

### `client/backend/server.py` (EDITED)
- `fetch_translate` is added to the `lib.engine_api_client` import.
- `PROXY_ALLOWED_QUERY_PARAMS["/api/translate"] = {"id", "host"}`, with a comment that it is not a proxied route. It is not added to `PROXY_READ_GET_ROUTES`.
- New module-level `_sanitize_query(allowed, params)` beside `_resolve_mode`. It is the GET proxy's old unknown/repeated-param loop moved out unchanged: same texts, first-offending-key order, empty-list skip, the `nsfw` strip exemption and empty-value drop. It returns `(sanitized, error_text_or_None)` and sends nothing itself, so a caller cannot send two responses.
- `_handle_engine_read_proxy_get` now calls `_sanitize_query` and answers 400 with the returned text. The POST copy is still inline, as the plan says.
- New `_serve_get` branch for `/api/translate`, placed before the final 404. It runs `_rate_limit_check` (429 `Rate limit exceeded`), then `_handle_translate_get(params)`.
- New `_handle_translate_get` checks in this order:
  - `_require_profile`: 401 `Profile key required`.
  - `_sanitize_query`: 400 with the shared texts for an unknown or repeated param.
  - 400 `id and host must be non-empty strings` unless exactly `id` and `host` are left after the strip, each no longer than `BLOCK_REFERENCE_MAX_LENGTH` (200), as on the reaction route.
  - Then `fetch_translate` with the stripped values. `EngineApiError` goes to the existing `_respond_engine_failure("translate", exc)`, which logs it and answers 502 `{"error": "Engine translate failed"}`. Otherwise it answers 200 with the payload.

### `tests/check-frontend-client-gateway.sh`, `tests/active/test_translate_gateway.py`, `tests/active/test_server.py`, `tests/config.json`
Not touched, as in phases 1 and 2: this step asks for production code only, and the gating checkpoint lives in `tests/tmp/`. Left for the promotion step:
- copying the checkpoint into `tests/active/test_translate_gateway.py`;
- the `FAILURE_ROUTES` row in `test_server.py` for `/api/translate` → `/internal/translate` → `Engine translate failed`;
- mapping `client/backend/server.py` and `lib/engine_api_client.py` to the new test in `test_groups`;
- adding `|/internal/translate` (and the missing `/internal/dislikes/centroids`) to the forbidden pattern on line 34 of the gateway guard.

The unchanged GET-proxy tests in `test_server.py` (around :1361 and :1519) check that the `_sanitize_query` extraction is faithful.

#### Phase 4 - Video page Translate toggle and overlay [code]

**Files touched.** client/frontend/package.json (EDITED), client/frontend/package-lock.json (EDITED), client/frontend/src/data/translate.ts (NEW), client/frontend/src/pages/video-page/translate.ts (NEW), client/frontend/src/pages/video-page/index.ts (EDITED), client/frontend/video-page.html (EDITED), client/frontend/src/video.css (EDITED), client/frontend/dist/ (REBUILT), tests/active/test_frontend_translate.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the video page bundle (`src/pages/video-page/index.ts`) run in node, using the esbuild+runner harness of `tests/active/test_frontend_video_page.py` (`bundle` fixture, `_page` runner, stubbed DOM and fetch). It adds `--alias:@peertube/embed-api=<stub>`, where the stub records construction, when `ready` was awaited, listener names and `getCurrentPosition` calls, exposes `emit(position)`, and offers `ready` modes resolve, reject, never and throw-in-constructor. The body carries `embedUrl`. New file `tests/active/test_frontend_translate.py`. Clause 1 asserts, with zero `/api/translate` requests and the toggle hidden in each case: no key with `translate:v1=on` and `ready` resolving; a key with `ready` never settling; a key with `ready` rejecting, which also gives `rejections == []`; and a constructor throwing a string, where `originalHref` is still set. A control asserts that with a key and `ready` resolving the toggle is visible and labelled exactly `Translate`, which excludes a page that never shows it. Clause 2 asserts, with a key and `translate:v1=on`: exactly one `/api/translate?id=uuid-1&host=peer.example`, recorded after `ready` resolved, with `constructed == 1` and the iframe src carrying `api=1`; `emit` of 1.5, then 7, then 0.5 (a seek back) shows each matching cue's text, and between cues the overlay is empty and hidden; and a cue `<b>x</b>` shows the literal text, with the overlay absent from `markupIds`, which excludes innerHTML. Supporting cases under the same harness: the exact `none` status text; a click storing `on`/`off` with a later `emit` ignored once off; embed URLs with and without a query; `javascript:` and an unparseable URL setting no src; and the polling fallback. `test_frontend_video_page.py`, `_similars.py` and `test_frontend_dist.py` stay green after the install and the `dist/` rebuild.

**Intent.** The video page builds one embed-API player on its `api=1` iframe and shows a Translate toggle only once `ready` resolves and a profile key is held. While Translate is on, it overlays as plain text the English cue at the player's reported position.

- C1 - No Translate toggle appears and no `/api/translate` request is made until the embed API's `ready` resolves and a profile key is held.
- C2 - With Translate stored on at load, the overlay shows as plain text the cue that contains each reported playback position, including after a seek back.

**Outcome.** ### Install status, which needs your attention
You said you had installed the package, but this checkout doesn't show it. I checked with a probe from `/home/enduser/code/PeerTube-browser`. Here `client/frontend/node_modules` is a real directory, not a symlink, so this is main. `node_modules/@peertube/embed-api` is not there, `package.json` doesn't list it, and `package-lock.json` has no entry for it. The checkpoint doesn't need it, because it aliases the import to its own stand-in. With that alias the page bundled cleanly in the probe. Without the alias, esbuild fails with `Could not resolve "@peertube/embed-api"`. So `test_frontend_video_page.py`, `test_frontend_video_page_similars.py`, `test_frontend_dist.py` and `vite build` stay red until the install shows up in this checkout.

### `client/frontend/package.json`, `client/frontend/package-lock.json`
Not edited by hand. `npm install @peertube/embed-api` writes both files with the version it resolves. Its lockfile diff should add only that package and its dependencies.

### `client/frontend/src/data/translate.ts` (NEW)
- `readTranslate()` / `setTranslate(on)` keep the setting in `localStorage` under `translate:v1`. They follow the same pattern as `readNsfwFilter` / `setNsfwFilter`, including the in-memory fallback, but default to off: only a stored `on` counts as on.
- `fetchTranslate(apiBase, id, host)` makes a GET to `/api/translate` through `resolveClientApiBase`, sending `profileHeaders()` with `cache: "no-store"`, as `fetchReaction` does.
  - A 401 throws `ProfileKeyRejectedError`; any other non-OK status throws the server's error message.
  - The reply is checked rather than trusted: state is `none`, or `ready` with cues that have finite start and end and string text. Anything else throws.
  - Cues come back sorted by start, then end.

### `client/frontend/src/pages/video-page/translate.ts` (NEW)
- `withEmbedApi(embed)` sets `api=1` through `URL.searchParams`, so it works with or without an existing query. It returns null when the URL doesn't parse.
- `setupTranslate(iframe, apiBase, video)` builds one `PeerTubePlayer` per page.
  - If the constructor throws anything (jschannel throws strings), it is caught and the page carries on with no toggle.
  - `ready` gets a rejection handler, so a rejected `ready` never becomes an unhandled rejection. A `ready` that never settles just leaves the toggle hidden.
- Once `ready` resolves, `onReady` checks for a profile key and a known id and host. Only then does it:
  - subscribe to `playbackStatusUpdate` (once, never removed);
  - wire the toggle click;
  - un-hide the toggle;
  - call `turnOn` if Translate is stored on. Page load and click go through the same function, and no `/api/translate` request is possible before this point.
- `turnOn` stores on and requests the state. A ticket counter drops replies that arrive after a later on/off.
  - `none`: the status reads "No English translation is available for this video."
  - `ready`: the cues are kept and the polling fallback starts.
- `turnOff` stores off, clears the cues, stops polling and hides the overlay. Updates that arrive after that are ignored through the `on` flag.
- Each reported position goes to a binary search over the sorted cues (start inclusive, end exclusive). The overlay is set with `textContent` and hidden when empty.
- Polling fallback: every 1 s, but only after 3 s with no update, it calls `getCurrentPosition()`, one call at a time. The `rat-tail:` comment names the limit: a call that never settles stops the fallback for the page, and a per-call timeout is the upgrade.

### `client/frontend/src/pages/video-page/index.ts` (EDITED)
- One import.
- The embed block now builds the src through `withEmbedApi`, still behind the https check. It sets `api=1` and only then calls `setupTranslate`, with `metadata.videoUuid` (falling back to the `resolveVideoSource()` id) and the `resolveVideoSource()` host.
- An https-prefixed string that won't parse now leaves no src. `applyOriginalHref` still runs afterwards, because `setupTranslate` never throws.

### `client/frontend/video-page.html` (EDITED)
- A `#translate-overlay` div with class `translate-overlay`, `hidden`, inside `.player-frame` after the iframe.
- In `.player-actions` after `#reaction-status`: a hidden `#translate-toggle` button labelled exactly `Translate`, and a `#translate-status` span with `role="status"`.
- The iframe sandbox and the CSP are unchanged.

### `client/frontend/src/video.css` (EDITED)
`.translate-overlay` comes right after `.player-frame iframe`. It is positioned absolutely near the bottom, with `pointer-events: none`, white centred text using `pre-wrap`, and a text shadow. It sets no `display`, so the `hidden` attribute still works.

### `client/frontend/dist/` (REBUILT)
Not rebuilt. This needs the install above, and per Step 6 it runs last, after the checkpoint is green.

### `tests/active/test_frontend_translate.py`, `tests/config.json`
Not touched, as in phases 1–3. This step asks for production code only, so copying the checkpoint into `tests/active/` and updating the `test_groups` mappings is left to the promotion step.

**Beyond the files named.** tests/tmp/probe_translate_bundle.py: a throwaway probe. It showed that the page bundles with the checkpoint's alias, that it does not bundle without it, and that the package isn't installed in this checkout. I have no tool to delete files, so I emptied it; it can be deleted.


