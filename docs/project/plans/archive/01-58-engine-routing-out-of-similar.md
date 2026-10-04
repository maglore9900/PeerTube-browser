# 58-engine-routing-out-of-similar

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/01-58-engine-routing-out-of-similar.record.md`._

## Requirements

### Purpose

The Engine has one request handler class, `SimilarHandler` (`engine/server/api/handlers/similar.py`, 1275 lines), and it is built by `engine/server/api/server.py:123,469`. Route dispatch for every Engine path, and the `/internal/*` bridge-auth gate, live in that similarity module today. So every new route edits the similarity file: its imports, its docstring route list, and one of its `if` chains. The roadmap plans more routes (F1-M3 public REST API, F5-M3, F1-M4), a change to every unversioned route (F2-M3 API versioning), and changes at the gates (F7-M7 and F10-M7, rate limiting and service keys). This build moves routing into a router module of its own so those changes land in one routing place. It is a pure code move: no request may behave differently.

### Current state (verified against the tree)

- `SimilarHandler.do_POST` → `_run_request(_serve_post)` → `with self._statement_deadline(): self._dispatch_post()`. A `sqlite3.OperationalError` for which `is_interrupted_error` is true answers `_respond_interrupted()` (503 `{"error": "Query time limit exceeded"}` plus a `[statement.timeout]` warning). Any other error is re-raised. `do_GET` → `_serve_get` → `_dispatch_get` follows the same pattern.
- `_bridge_authorized` (`similar.py:417-440`):
  - The configured token is `getattr(self.server, "bridge_token", ENGINE_BRIDGE_TOKEN)`. It falls back only when the attribute is absent, so an empty `server.bridge_token` counts as unset.
  - When the token is falsy: `logging.error("[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting %s", self.path)`, then 503 `{"error": "Bridge token is not configured on the Engine"}`.
  - Otherwise the presented token is `self.headers.get(BRIDGE_TOKEN_HEADER, "").strip()`. When it is empty or fails `hmac.compare_digest(presented, configured)`: `logging.warning("[bridge.auth] rejected %s from ip=%s", self.path, self._get_client_ip())`, then 401 `{"error": "Unauthorized"}`.
  - `self.path` is the raw request path, including any query string.
- `_dispatch_post` (`similar.py:442-478`) uses `url = urlparse(self.path)` and matches exactly on `url.path`, in this order:
  1. When `url.path.startswith("/internal/")` and bridge auth fails, return. This covers unknown `/internal/` paths too, so they get 401 or 503, never 404.
  2. A path in `SIMILAR_POST_ROUTES` (`/recommendations`, `/videos/similar`) → `self._handle_similar_request(method="POST")`, which runs its own rate-limit check (429) itself.
  3. `/internal/videos/resolve` → `handle_internal_video_resolve(self, self.server)`.
  4. `/internal/videos/metadata` → `handle_internal_videos_metadata(self, self.server)`.
  5. `/internal/dislikes/centroids` → `handle_internal_dislike_centroids(self, self.server)`.
  6. `/internal/translate` → `handle_internal_translate(self, self.server)`.
  7. `/internal/translate/enqueue` → `handle_internal_translate_enqueue(self, self.server)`.
  8. `/internal/events/ingest`: when `getattr(self.server, "engine_ingest_mode", "bridge") != "bridge"`, answer 501 `{"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": <that mode>}`. Otherwise call `handle_internal_events_ingest(self, self.server)`.
  9. Anything else → 404 `{"error": "Not found"}`.
- `_dispatch_get` (`similar.py:494-562`), in this order:
  1. When `url.path.startswith("/api/")` and `self._rate_limit_check(url.path)` fails → 429 `{"error": "Rate limit exceeded"}`. This also applies to unknown `/api/` paths, before their 404.
  2. `/api/health` → 200 `{"ok": True, "total": server.embeddings_count, "embeddingDim": server.embeddings_dim}`, answered inline.
  3. `params = parse_qs(url.query)`. `/api/channels` is answered inline:
     - `limit = _parse_int(limit)`; when it is `<= 0` it becomes 100, then it is capped at 500;
     - `offset = _parse_int(offset)`;
     - `max_videos = _parse_non_negative_int(maxVideos)`;
     - under `server.db_lock`, `fetch_channels(server.db, limit, offset, query=q or "", instance=instance or "", min_followers=_parse_int(minFollowers), min_videos=_parse_int(minVideos), max_videos, sort=sort or "followers", direction=dir or "desc")`;
     - 200 `{"generatedAt": now_ms(), "total": total, "rows": rows}`.
  4. `/api/v1/search/videos` → `self._handle_search(params)`.
  5. `/api/video` → `handle_video_request(self, self.server, params)`.
  6. `/api/video/refresh` → `handle_video_refresh_request(self, self.server, params)`.
  7. `/videos/{id}/similar`, matched by `_extract_video_id_from_similar_path(url.path)` (exactly three segments, `videos`/<non-blank id>/`similar`): first its own `self._rate_limit_check(url.path)` (429 on failure, even though the path is not under `/api/`), then `params.setdefault("id", [video_path_id])`, then `self._handle_similar(params)`.
  8. Anything else → 404 `{"error": "Not found"}`.
- A GET to an `/internal/` path gets a plain 404, with no bridge auth. A POST to a GET-only path, or the other way round, gets 404. Routing ignores the query string, and a trailing slash does not match.
- The module docstring (`similar.py:1-20`) is titled "Similarity HTTP handler" and lists the routes. It already omits `/internal/dislikes/centroids` and `/api/v1/search/videos`.
- `SIMILAR_POST_ROUTES` is also read by `_recommendations_likes_payload_error` inside similar.py.
- `_parse_int`, `_parse_non_negative_int` and `_extract_video_id_from_similar_path` are module-level helpers in similar.py. `_parse_int` and `_parse_non_negative_int` are also used by similarity and search code that stays.

### Desired behaviour

- **One router module** in the Engine's API package (`engine/server/api/`, beside or under `handlers/`; the design step picks the place) owns:
  - the GET route table and the POST route table, each mapping an exact path to the callable that serves it, plus the GET `/videos/{id}/similar` pattern;
  - the `/internal/*` bridge-auth gate on POST;
  - the `/api/` rate-limit gate on GET;
  - the events-ingest mode check (the 501);
  - the 404 fallback.
- **Router entry points.** The router exposes one GET entry point and one POST entry point, each taking the handler. Table values are callables with one consistent signature: either `(handler, server)` or the handler alone, chosen by the design step and used throughout. Handlers whose native signature differs (the video handlers take `params`, the similar methods take `method`/`params`) are wrapped by thin adapters so the tables stay uniform.
- **Bridge auth** becomes a router function. It keeps:
  - the same token source (`getattr(server, "bridge_token", ENGINE_BRIDGE_TOKEN)`, the same fallback semantics);
  - the same header (`BRIDGE_TOKEN_HEADER`, stripped);
  - the same `hmac.compare_digest` compare;
  - the same 503 and 401 bodies;
  - the same `[bridge.auth]` log messages, levels and arguments: `self.path` and `handler._get_client_ip()`.
- **Inline routes.** `/api/health` and `/api/channels` become handler functions of their own, beside the router or in a fitting handler module, so the router is a table. Their responses and parameter parsing stay byte-for-byte the same. They need the `_parse_int`/`_parse_non_negative_int` semantics, which similar.py's similarity code also uses; how they share them is the design step's choice.
- **The `/videos/{id}/similar` rate-limit check** and the `params.setdefault("id", ...)` stay in force, in the same order, before `_handle_similar` runs.
- **`SimilarHandler` keeps:**
  - its name, module and construction by `server.py`;
  - `_run_request`, `_statement_deadline`, `_respond_interrupted`, `_serve_get`/`_serve_post` (the statement deadline and its 503 still wrap all routing, including the gates);
  - `_get_client_ip`, `_get_full_url`, `log_request`, `log_message` and `do_OPTIONS`;
  - `_rate_limit_check` and every similarity, feed and search method (`_handle_similar_request`, `_handle_similar`, `_handle_search`, and the rest).
  
  Its `do_GET`/`do_POST` path hands each request to the router's GET/POST entry point, in place of `_dispatch_get`/`_dispatch_post`.
- **Adding a route** means one table entry, plus one import in the router, and no edit to similar.py.
- **Docstrings.** The router module's docstring holds the full route list, including the two routes the old docstring omitted (`/internal/dislikes/centroids`, `/api/v1/search/videos`), and `/api/health` and `/api/channels`. similar.py's docstring describes only similarity: recommendations, similar, feeds and search.
- **README.** The `engine/server/README.md` route list is left unchanged (operator decision). Its other references to `SimilarHandler._run_request` and `_parse_include_nsfw` in `api/handlers/similar.py` stay true and are not edited.

### Behaviour that must be identical

Every request gets the same status, body, headers and log lines as today:
- every route, on both methods;
- the gate order (bridge auth before any POST `/internal/` route, including unknown ones; the `/api/` rate limit before any `/api/` GET, including unknown ones);
- both 404s;
- the 401 and 503 bridge bodies and their `[bridge.auth]` log lines;
- the 429s, including the extra one on GET `/videos/{id}/similar`;
- the 501 for ingest outside bridge mode, with its `mode` field;
- the plain 404 for GET `/internal/*`;
- the statement-timeout 503;
- the `[request.start]`/`[request.end]` records and request id.

### Acceptance criteria

- similar.py no longer contains:
  - a path-dispatch chain (`_dispatch_get`/`_dispatch_post` or an equivalent);
  - the bridge-auth check or the `hmac`/`ENGINE_BRIDGE_TOKEN`/`BRIDGE_TOKEN_HEADER` use behind it;
  - the `/api/health` or `/api/channels` handling;
  - imports of `handlers.internal_events`, `handlers.internal_client_reads`, `handlers.internal_translate` or `handlers.video`.
- One router module holds both route tables, the bridge-auth gate, the `/api/` rate-limit gate, the ingest-mode check and the 404 fallback.
- **Bridge-auth test:**
  - Every POST `/internal/*` path without a valid `X-Bridge-Token` (missing, or wrong) answers 401 `{"error": "Unauthorized"}` before its handler runs, and answers 503 `{"error": "Bridge token is not configured on the Engine"}` when the token is unset.
  - A test covers one internal route of each kind (client reads: one of resolve, metadata or dislike centroids; translate: one of translate or enqueue; events ingest) plus an unknown `/internal/` path, which also gets 401 without a token.
  - The test shows the handler did not run.
- Every Engine route answers as before. That covers every route the README lists, plus `/api/health`, `/api/channels` and `/api/v1/search/videos`, which the README's list omits.
- The existing Engine, video, similar, translate and ingest tests pass: `tests/active/test_similar.py`, `test_video.py`, `test_internal_translate.py`, `test_internal_events.py`, `test_internal_client_reads.py`, `test_random_cache.py`, `test_server.py` and `engine/server/api/tests/`. Only tests that called removed dispatch or auth methods directly are rewritten; no current test does.
- A test adds a fake route through a router table entry alone, with no edit to similar.py, and it is served through the real `SimilarHandler`.
- The route list lives in the router module's docstring, and similar.py's docstring describes only similarity.

### Constraints

- Smallest move that answers the issue. No new dependency (stdlib only). No router class hierarchy or registration framework: plain module-level dicts and functions. No change to `SimilarServer`.
- Code moves without behaviour change. New code follows the style of the file it lands in: module docstring, one-line docstrings, `respond_json(handler, status, body)` and `getattr(server, ..., default)` idioms.
- **Test environment.** pytest's own interpreter has no numpy, so it cannot import `handlers.similar` or `server.py`. Engine-level tests run in a child process under `ENGINE_PY` (from `tests/active/conftest.py`), with `sys.path` set to the Engine `api` paths, as `test_video.py`, `test_similar.py` and `test_internal_events.py` do. The new bridge-auth and fake-route tests follow that pattern, or exercise a real `SimilarServer` on an ephemeral port.
- Test trees: active tests live in `tests/active`, the working tree for in-build tests is `tests/tmp`, finished feature tests are archived under `tests/archive`, plans go in `docs/project/plans`, and the project root is `/home/enduser/code/PeerTube-browser/.worktrees/58`.

### Baseline suite state

The pre-build baseline run exited with code 0 (`variant: false`): the suite is green before the build. Any red test after the build is caused by the build.

### Out of scope

- Renaming `SimilarHandler` or `SimilarServer`, or moving similarity, feed or search methods out of the class.
- API versioning (F2-M3), new routes, or any change to rate limiting, bridge auth semantics or error bodies.
- Changing `_get_client_ip`, access logging, request-id handling or the statement deadline.
- The fetch adapter (issue 53) and translate route internals (issues 54, 55).
- Editing `engine/server/README.md`.

## High-level plan

### Approach

Add one new module, `engine/server/api/router.py`. It sits beside `server.py` and `http_utils.py` and holds routing for the whole Engine. It imports from `handlers/`, and `handlers/similar.py` imports its two entry points from it. The router never imports `handlers.similar`, so the dependency runs one way and there is no import cycle. The router also never needs the class, because every similarity call goes through the `handler` object it is given (`handler._handle_similar_request(...)`, `handler._handle_similar(...)`, `handler._handle_search(...)`, `handler._rate_limit_check(...)`).

**What the router holds**

- **Module docstring.** The full route list: every route the old docstring named, plus `/internal/dislikes/centroids` and `/api/v1/search/videos`, with `/api/health` and `/api/channels` kept. Each route is marked with its method and whether a gate covers it.
- **Two plain dicts, `GET_ROUTES` and `POST_ROUTES`.** Each maps an exact path to a callable with the signature `(handler, server)`. I chose `(handler, server)` over the handler alone because five of the nine existing callees already have it: the three client-read handlers and the two translate handlers. Those go into the table as they are, with no adapter.
- **`SIMILAR_POST_ROUTES`, moved here from similar.py.** The POST table builds its `/recommendations` and `/videos/similar` entries from it. similar.py imports it back for `_recommendations_likes_payload_error`, so the router stays the one owner of path strings and the router-to-similar import direction still holds.
- **Thin named adapters, each with a one-line docstring.** Named functions match the file style; I did not use lambdas.
  - The similar POST adapter calls `handler._handle_similar_request(method="POST")`.
  - The search, video and video-refresh adapters each read `parse_qs(urlparse(handler.path).query)` and call `handler._handle_search(params)`, `handle_video_request(handler, server, params)` and `handle_video_refresh_request(handler, server, params)`.
  - The events-ingest adapter is where the 501 lives. It checks `getattr(server, "engine_ingest_mode", "bridge")` with the same body and `mode` field as today, and only then calls `handle_internal_events_ingest`.
- **Two handler functions, `handle_health` and `handle_channels`, taking `(handler, server)`.** Their bodies are the old inline blocks moved over unchanged: the same parsing, the same clamp of `limit` to 100 when it is `<= 0` and to 500 at most, `fetch_channels` under `server.db_lock`, and the same response bodies. `/api/channels` re-parses the query from `handler.path`, which gives the same result the old shared `params` did.
- **`_extract_video_id_from_similar_path`, moved here unchanged.** Only dispatch uses it.
- **`bridge_authorized(handler)`.** This is `_bridge_authorized` moved over with only `self` changed to `handler` / `handler.server`:
  - the same `getattr(server, "bridge_token", ENGINE_BRIDGE_TOKEN)` fallback;
  - the same stripped `BRIDGE_TOKEN_HEADER` and `hmac.compare_digest`;
  - the same 503 and 401 bodies;
  - the same `logging.error` / `logging.warning` calls on the root logger, with `handler.path` and `handler._get_client_ip()`.

  I checked `logging_profiles.py`: neither the text nor the JSON formatter emits module, function or line, so moving the calls to another module leaves every log line byte-identical.
- **`route_post(handler)`:**
  1. Parse `handler.path`.
  2. When the path starts with `/internal/`, run `bridge_authorized` and return if it fails. This covers unknown `/internal/` paths too, so they still get 401 or 503.
  3. Look the exact path up in `POST_ROUTES` and call the entry with `(handler, handler.server)`.
  4. Otherwise answer 404 `{"error": "Not found"}`.
- **`route_get(handler)`:**
  1. Parse the path.
  2. Apply the `/api/` prefix rate-limit gate through `handler._rate_limit_check(path)`, answering 429 on failure, including for unknown `/api/` paths.
  3. Exact lookup in `GET_ROUTES`.
  4. Otherwise try the `/videos/{id}/similar` pattern: its own rate-limit check (429), then `params.setdefault("id", [video_id])`, then `handler._handle_similar(params)`, in that order.
  5. Otherwise 404.

  GET `/internal/*` has no table entry and no gate, so it still gets the plain 404. Wrong-method requests miss their table and get 404. Routing uses `urlparse(...).path`, so the query string is still ignored, and a trailing slash still fails the exact match.

**Shared integer parsing.** `_parse_int` and `_parse_non_negative_int` move unchanged to `http_utils.py` as public `parse_int` and `parse_non_negative_int`. The router imports them from there, and similar.py imports them and renames its handful of call sites (search, similar, channels code that stays). One definition serves both modules.

**What changes in similar.py**

- Removed:
  - `_dispatch_get`, `_dispatch_post` and `_bridge_authorized`;
  - the health and channels blocks;
  - `_extract_video_id_from_similar_path` and the two parse helpers;
  - the `hmac` import, `ENGINE_BRIDGE_TOKEN` and `BRIDGE_TOKEN_HEADER`;
  - `fetch_channels`;
  - the four `handlers.internal_*` / `handlers.video` imports.
- `_serve_get` and `_serve_post` keep their deadline / interrupted-503 wrapper exactly as now and call `route_get(self)` and `route_post(self)` inside it. So the statement deadline still wraps the gates, and `_run_request` still owns the `[request.start]` / `[request.end]` records and the request id. Nothing else in the class changes.
- The `do_GET` / `do_POST` docstrings are reworded to say "hand the request to the router".
- The module docstring is rewritten to describe only recommendations, similar, feeds and search, and points to `router.py` for the route list.
- `urlparse` and `parse_qs` stay, because `_handle_similar_request` still uses them. `now_ms` stays because feeds use it.

### How each requirement is met

- **One router module** holds both tables, the `/videos/{id}/similar` pattern, the bridge gate, the `/api/` rate-limit gate, the ingest-mode 501 and both 404s.
- **Entry points.** `route_get(handler)` and `route_post(handler)`; every table value has the signature `(handler, server)`.
- **Bridge auth** keeps its token source, header, compare, bodies and log calls exactly.
- **Inline routes** become `handle_health` and `handle_channels` with identical behaviour.
- **The `/videos/{id}/similar` rate-limit check and `setdefault`** run in the same order.
- **`SimilarHandler`** keeps its name, module, construction by `server.py`, wrapper, logging, OPTIONS, `_rate_limit_check` and every similarity, feed and search method. `SimilarServer` and `server.py` are not touched.
- **Adding a route** means one dict entry plus one import in `router.py`.
- **README** is not edited. Its references to `SimilarHandler._run_request` and `_parse_include_nsfw` stay true, since neither moves.

**Tests.** Both new tests go in `tests/tmp`. Each runs a child under `ENGINE_PY` with the Engine `api` paths on `sys.path`, starting a real `SimilarServer` with the real `SimilarHandler` on an ephemeral port, the way `test_video.py` does.

- **Bridge-auth test.** It swaps recording stubs into `POST_ROUTES` for `/internal/videos/resolve`, `/internal/translate` and `/internal/events/ingest`, then sends POSTs to those three plus an unknown `/internal/` path.
  - With no token and with a wrong token: 401 `{"error": "Unauthorized"}` for all four.
  - With `srv.bridge_token = ""`: 503 with the configured-token body.
  - Each stub records zero calls.
  - A control request with the valid token shows the stub does get called. That proves the stub is wired in, so the zero counts actually mean something.
- **Fake-route test.** It adds `GET_ROUTES["/fake"]` with a function that answers through `respond_json`, then checks the response arrives through the real handler.

The existing suites listed in the acceptance criteria run unchanged. Nothing calls the removed methods directly; I checked the tree, and the only `similar.` uses in tests are `FEED_MODES`, `DEFAULT_CLIENT_LIKES_MAX`, `_parse_client_likes`, `_handle_similar` and `_handle_similar_request`, which all stay.

### Alternatives considered

- **Keep the routing methods on a mixin or base class that `SimilarHandler` inherits.** Rejected: the constraints forbid a class hierarchy, and a mixin still couples routing to the handler class.
- **Use a decorator or registration framework, or a router class.** Rejected by the constraints. A plain dict already gives a one-line route addition.
- **Have table callables take the handler alone.** Rejected: all five client-read and translate handlers would then need adapters, where with `(handler, server)` none of them do.
- **Import the parse helpers from similar.py into the router.** Rejected: similar.py imports the router, so this would create a cycle.
- **Duplicate the parse helpers in the router.** Rejected: two copies of the clamping rules would drift apart.
- **Put the router in `handlers/router.py`.** Workable, but `handlers/` holds endpoint handlers. Dispatch is cross-cutting, like `http_utils` and `request_context`, so it sits beside them.
- **Put health and channels in a new `handlers/catalog.py`.** Rejected for now as one more file holding two small functions. Living beside the router is allowed by the requirements, and they can move out when they grow.
- **Run the ingest-mode check as a path-keyed gate in `route_post`.** Rejected: it applies to one route, so it belongs in that route's adapter, which still sits inside the router.
- **Leave `SIMILAR_POST_ROUTES` in similar.py and write the two paths out again in the router.** Rejected: that is a duplicate source of path truth.

### Gotchas and risks

- **Import cycle.** `router.py` must never import `handlers.similar`, at module level or anywhere else. A future contributor who wants a similarity helper in the router would bring the cycle back.
- **Table entries hold function references.** Patching `handlers.internal_translate.handle_internal_translate` after import does not change what gets dispatched. Tests must patch the table entry instead, and the bridge-auth test does that. Today's tests patch inner functions (`video.fetch_instance_json`, `fetch_bounded`), and those are unaffected.
- **The tables must stay plain mutable dicts, looked up per request.** If they are frozen or copied into a closure, the fake-route test breaks.
- **Re-parsing the query in adapters.** `parse_qs` with default arguments does not raise, so moving the parse from before the channels block into each adapter cannot change an outcome. The cost is negligible.
- **Order inside the tables.** Order no longer matters, because exact paths cannot overlap and the one pattern route is tried only after an exact miss, as it is today.
- **Docstring drift.** `engine/server/README.md` keeps its incomplete route list by operator decision. `router.py` becomes the route list that is correct.

### Tradeoffs the operator is accepting

- **Deliberate simplification: one hard-coded pattern route.** `/videos/{id}/similar` stays special-cased in `route_get` rather than going through a general pattern table. That limit is reached when a second parameterised path appears. The upgrade then is a small ordered list of `(matcher, callable)` pairs tried after the exact lookup, which fits F2-M3 versioning.
- **Gates are prefix checks hard-coded in the entry points** (`/internal/` on POST, `/api/` on GET), not per-route flags. That matches today exactly. F7-M7 and F10-M7 will change them in that one place.
- **`/api/health` and `/api/channels` live in `router.py`.** The router file therefore imports `fetch_channels` and `now_ms` and is not strictly a table.
- **Renamed helpers.** `_parse_int` and `_parse_non_negative_int` become public `parse_int` and `parse_non_negative_int` in `http_utils.py`, and similar.py's call sites are renamed. No test references the old names.

## Impacts

<impacts>
<impact path="engine/server/api/router.py" element="new module (whole file): docstring route list, GET_ROUTES, POST_ROUTES, SIMILAR_POST_ROUTES, adapters, handle_health, handle_channels, _extract_video_id_from_similar_path, bridge_authorized, route_get, route_post">
**What changes.** A new top-level module in the api dir. No file named `router*` exists anywhere in the tree, and none exists in the Engine pixi site-packages, so the top-level name `router` does not collide. It is imported as `from router import ...`, the same way `http_utils` and `server_config` are, because the api dir is on `sys.path` as a root.

**What it must import.**
- From the standard library: `hmac`, `logging` and `from urllib.parse import parse_qs, urlparse`.
- `from data.channels import fetch_channels` and `from data.time import now_ms`.
- `from http_utils import respond_json, parse_int, parse_non_negative_int`.
- `from server_config import BRIDGE_TOKEN_HEADER, ENGINE_BRIDGE_TOKEN`. Both are defined at `server_config.py:500-501`, and the token is read from env at import time.
- `handle_internal_events_ingest` from `handlers.internal_events`, the three `handle_internal_*` client reads from `handlers.internal_client_reads`, `handle_internal_translate` and `handle_internal_translate_enqueue` from `handlers.internal_translate`, and `handle_video_request` and `handle_video_refresh_request` from `handlers.video`.

None of these modules imports `handlers.similar`, so there is no cycle; I checked their import blocks. `handlers.internal_translate` imports `handlers.video`, which is fine.

**Behaviour that must be reproduced exactly** (from `similar.py:417-562`):
- **POST.**
  - The `/internal/` prefix gate runs before every lookup, unknown internal paths included.
  - `SIMILAR_POST_ROUTES` → `_handle_similar_request(method="POST")`.
  - The five internal routes.
  - Events ingest: the 501 body is `{"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": getattr(server, "engine_ingest_mode", "bridge")}`.
  - Anything else: 404 `{"error": "Not found"}`.
- **GET.**
  - The `/api/` prefix gate gives 429 `{"error": "Rate limit exceeded"}` before the lookup, unknown `/api/` paths included.
  - `/api/health` answers `{"ok": True, "total": server.embeddings_count, "embeddingDim": server.embeddings_dim}`.
  - `/api/channels` keeps the clamp `<=0 → 100`, then `min(…, 500)`; `offset`, `maxVideos`, `minFollowers` and `minVideos` keep their parsing; `fetch_channels` keeps its keyword args under `server.db_lock`; the response is `{"generatedAt": now_ms(), "total", "rows"}`.
  - Search, `/api/video` and `/api/video/refresh` each get `parse_qs(url.query)`.
  - Then the `/videos/{id}/similar` pattern: a second `_rate_limit_check(url.path)`, then `params.setdefault("id", [video_id])`, then `_handle_similar(params)`.
  - Anything else: 404.

**What depends on it.**
- `handlers/similar.py`: `_serve_get` / `_serve_post`, and `_recommendations_likes_payload_error` through `SIMILAR_POST_ROUTES`.
- The two new tests in `tests/tmp`, which mutate `POST_ROUTES` and `GET_ROUTES`.
- Every Engine HTTP test indirectly, because every request now flows through it.

**Regression risk: HIGH.** This is the whole request surface.
- **Ordering slips.**
  - The bridge gate must run before the `SIMILAR_POST_ROUTES` lookup. Today it cannot matter, since those paths are not `/internal/`, but the gate must still come first.
  - The `/api/` rate-limit gate must run before the exact lookup, so a 429 still lands on unknown `/api/` paths.
  - In the pattern branch, rate-limit then `setdefault` then `_handle_similar`.
- **Accidental drift.** `respond_json` here must be the `http_utils` one. Tests that patch `similar.respond_json` (test_similar.py:259, test_recommendations_likes_limit.py:55/85/105) only go through `_handle_similar_request`, which stays in similar.py, so they still capture its output.
- **Tables must be read per request.** `route_get`/`route_post` must do `GET_ROUTES.get(path)` at call time, not bind entries at import, or the fake-route and stub tests break.
- **Logging.** The bridge-auth `logging.error`/`logging.warning` must stay on the root logger (`logging.error(...)`, not `logging.getLogger(__name__)`) with the same format strings. `logging_profiles._classify_event` derives the `event` field from the `[bridge.auth]` message prefix, and `EngineJsonFormatter.format` (`logging_profiles.py:236-272`) never emits module, funcName or lineno. I confirmed that: moving modules keeps output identical, but only if the message text is unchanged.
- **Return values.** The `handle_*` functions return `bool`, and the router must ignore it, as the old chain did.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="module docstring (lines 1-20)">
**What changes.** The docstring is rewritten to describe only recommendations, similar, feeds and search, and to point to `router.py` for the route list. Today it lists 11 routes; `/internal/dislikes/centroids` and `/api/v1/search/videos` are already missing from it.

**What depends on it.** Nothing at runtime. `tests/active/test_frontend_feed_params.py:41,120` parses this file with `ast` to read `FEED_MODES`, and a docstring change is harmless to that.

**Regression risk: none.** The acceptance criterion "similarity module's docstring describes only similarity" is checked against this text.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="imports block (lines 21-103)">
**What changes.**
- **Removed:**
  - `import hmac` (line 22, only used at 434);
  - `from data.channels import fetch_channels` (36, only used at 518);
  - `BRIDGE_TOKEN_HEADER` and `ENGINE_BRIDGE_TOKEN` from the `server_config` import (52, 58, only used at 424/433);
  - the four `handlers.internal_*` / `handlers.video` imports (96-103).
- **Added:**
  - `from router import SIMILAR_POST_ROUTES, route_get, route_post`;
  - `parse_int, parse_non_negative_int` added to the existing `from http_utils import ...` line (80).
- **Stays:**
  - `urlparse` and `parse_qs` (still used at 643/647 in `_handle_similar_request`);
  - `now_ms` (still used at 622 in search and 908 in feeds);
  - `sqlite3`, and `Callable` (used by `_run_request`).

**What depends on it.**
- `server.py:123` imports `SimilarHandler` from this module, so importing `similar` now transitively imports `router` and the internal handlers. That set of modules is the same as today, only reached through router.
- Every child-process test that does `from handlers import similar` / `from handlers.similar import SimilarHandler`: test_video.py:166/202, test_similar.py:196/238/362/471/730/979, test_server.py:1405, engine/server/api/tests/test_recommendations_likes_limit.py:19 and tests/archive/... Every one of them already has the api dir on `sys.path` (it is required to import the `handlers` package), so `router` resolves.

**Regression risk: medium.**
- **Import cycle.** If router ever imports `handlers.similar`, it breaks. A partial-module error appears when `similar` is the first importer, which is the normal case through server.py.
- **Unused-import or missed-import NameError.** For example, leaving `_parse_int` references without renaming. Grep after the edit for `_parse_int`, `_parse_non_negative_int`, `fetch_channels`, `hmac` and `ENGINE_BRIDGE_TOKEN`.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SIMILAR_POST_ROUTES constant (line 106) and its reader _recommendations_likes_payload_error (lines 230-267)">
**What changes.** The constant definition moves to `router.py`. similar.py imports it back, and `_recommendations_likes_payload_error` (line 234: `if path not in SIMILAR_POST_ROUTES`) stays unchanged and reads the imported name.

**What depends on it.**
- The likes-payload 400 contract for both `/recommendations` and `/videos/similar` (archive issue 05; README line 46).
- engine/server/api/tests/test_recommendations_likes_limit.py, which calls `_handle_similar_request` with path `/recommendations`.
- test_similar.py:238-267.

**Regression risk: low.** It must stay a set with exactly the two paths. If someone writes the paths out in the router instead, they can drift.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._bridge_authorized (lines 417-440)">
**What changes.** The method is removed and moves to `router.bridge_authorized(handler)`, with `self` → `handler` and `self.server` → `handler.server`.

**What depends on it.** Only `_dispatch_post` (line 445). No test calls it directly; grep of tests for `_bridge_authorized` found nothing.

**Regression risk: medium.** The behaviours to preserve:
- `getattr(server, "bridge_token", ENGINE_BRIDGE_TOKEN)`. `SimilarServer.__init__` always sets `self.bridge_token = ENGINE_BRIDGE_TOKEN` (server.py:290), so the fallback only matters for stand-in servers.
- A falsy token gives 503 plus `logging.error`.
- An empty or mismatched presented token (`.strip()`, `hmac.compare_digest`) gives 401 plus `logging.warning` with `handler._get_client_ip()`.

Callers outside the Engine depend on these bodies:
- client/backend/lib/engine_api_client.py:14,37-47 sends `X-Bridge-Token`;
- test_internal_translate.py:1071,1074 asserts `(401, {"error": "Unauthorized"})`;
- the DEPLOYMENT.md §3b and line 315 triage text relies on the `bridge.auth` log event.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._dispatch_post (lines 442-478) and _serve_post (407-415), do_POST docstring (403-405)">
**What changes.**
- `_dispatch_post` is removed.
- `_serve_post` keeps its try / `with self._statement_deadline():` / `except sqlite3.OperationalError` → `is_interrupted_error` → `_respond_interrupted()` wrapper, and calls `route_post(self)` inside it.
- The `do_POST` docstring is reworded to "hand the request to the router".

**What depends on it.**
- Every POST: recommendations, videos/similar and all `/internal/*`.
- The statement deadline must still wrap the bridge gate and the handler, so that a `sqlite3.OperationalError` interrupt raised inside a router-called handler is still turned into a 503.
- `internal_events.py:9` imports `is_interrupted_error` and handles some of these interrupts itself; that is unchanged.

**Regression risk: medium.** If `route_post` is called outside the `with` block, or catches `OperationalError` itself, the 503 `Query time limit exceeded` path changes.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._dispatch_get (lines 494-562) and _serve_get (484-492), do_GET docstring (480-482)">
**What changes.**
- `_dispatch_get` is removed: the inline health and channels blocks, the shared `params = parse_qs(url.query)` at 509, and the pattern branch.
- `_serve_get` keeps its wrapper and calls `route_get(self)`.
- The `do_GET` docstring is reworded.

**What depends on it.** Every GET:
- `/api/health`, used as the readiness probe in conftest.py:192, test_random_cache.py:307/819/861, test_internal_translate.py:1056 and test_similar.py:437;
- `/api/channels`, which the Client proxies (client/backend/server.py:93,102) and which test_server.py:471-474 exercises through the Client;
- `/api/v1/search/videos`, `/api/video` and `/api/video/refresh` (test_video.py);
- `/videos/{id}/similar` (test_video.py:80 `SIMILAR`, PERSIST_CHILD).

**Regression risk: medium-high.** These are the call sites every Engine readiness check depends on. A broken `handle_health` makes every Engine-child fixture time out. Unknown GET paths, including GET `/internal/*`, must still give a plain 404 with no gate; test_video.py:631/659 rely on 404 `{"error": "Not found"}` for unrouted paths.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="module helpers _parse_int (1167-1173), _parse_non_negative_int (1191-1199), _extract_video_id_from_similar_path (1267-1275), and their remaining call sites">
**What changes.**
- `_parse_int` and `_parse_non_negative_int` are removed and move to http_utils as `parse_int` and `parse_non_negative_int`.
- `_extract_video_id_from_similar_path` is removed and moves to router.

**Remaining call sites to rename.** Grep confirms there are exactly four:
- `_handle_search` at 584 (`limit`) and 588 (`page`);
- `_handle_similar` at 1035 (`limit`, default `str(self.server.default_limit)`) and 1062 (`seed` → `parse_non_negative_int`).

The plan's wording "search, similar, channels code that stays" is slightly off: the channels call sites at 511/515/516/524/525 move to `router.handle_channels`, they do not stay.

**What stays.** `_parse_bool` (1176) and `_parse_include_nsfw` (1183) are not touched. README:50 and ADR-0007:17 cite `_parse_include_nsfw` in `api/handlers/similar.py`.

**What depends on it.**
- Search limit/page clamping.
- Similar limit and seed parsing: the README:49 `seed` semantics are "negative or non-integer → random draw". This is `parse_non_negative_int` returning None.

No test references the old names; I grepped `_parse_int` in tests and the only hit is client/backend/server.py's own unrelated `_parse_int` (line 1316), which is not affected.

**Regression risk: low-medium.** A missed rename raises a NameError at request time, not at import time, because the names are resolved lazily inside methods. A test run that does not hit search or seeded similar would not catch it.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler methods that stay and are now called by the router: _rate_limit_check (632-639), _handle_similar_request (641-699), _handle_similar (1033+), _handle_search (564-630), _get_client_ip (323-338)">
**What changes.** Nothing in their bodies, apart from the parse renames noted in the helpers entry. They become an implicit interface the router calls by name on the handler object.

**What depends on it.** The router's `handler._rate_limit_check(path)`, `handler._handle_similar_request(method="POST")`, `handler._handle_similar(params)`, `handler._handle_search(params)` and `handler._get_client_ip()`. Several tests call these directly on stubs:
- test_similar.py:207 builds a stub with `rate_limiter`;
- test_similar.py:265/388/500/1005;
- test_recommendations_likes_limit.py.

**Regression risk: low now, latent later.** The private, underscore-prefixed methods become a cross-module contract. A future rename in similar.py breaks the router with an AttributeError at request time, not at import.
</impact>
<impact path="engine/server/api/http_utils.py" element="new public parse_int and parse_non_negative_int">
**What changes.** The two functions are added, moved unchanged from similar.py:1167-1173 and 1191-1199, including their docstrings.
- `parse_int`: `int(value or "0")`, then 0 on ValueError, then `parsed if parsed > 0 else 0`.
- `parse_non_negative_int`: None for None, blank, invalid or negative input.

The module currently imports only `json`, `deque`, `datetime`, `BaseHTTPRequestHandler`, `threading` and `Any`, and needs no new import. Its docstring style is one line `"""Handle/Parse ..."""`.

**What depends on it.**
- Imported by `router.py` (channels) and `handlers/similar.py` (search, similar).
- Already imported by `server.py:124` (`RateLimiter`), internal_client_reads.py:10, internal_events.py:12, internal_translate.py:26, video.py:21.
- tests/config.json lists `engine/server/api/http_utils.py` in the `test_similar.py` and `test_internal_client_reads.py` / `test_internal_translate.py` groups.

**Regression risk: low.** It is additive. The semantics must be copied byte-for-byte; for example, `int(" 5")` works today because `int` strips whitespace, and that must not be "improved".

**Name collision.** client/backend/lib/http_utils.py is a separate module in a different process tree. It does not collide, because the Engine never has `client/backend/lib` on its path.
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer construction and handler import (lines 123, 249/283 engine_ingest_mode, 279 rate_limiter, 290 bridge_token, 469 SimilarHandler)">
**What changes.** Nothing; the plan leaves this file untouched.

**What depends on it.** The router reads, through `handler.server`:
- `bridge_token` (always set at 290);
- `engine_ingest_mode` (set at 283);
- `rate_limiter`, via `_rate_limit_check`;
- `embeddings_count`, `embeddings_dim`, `db` and `db_lock`.

`from handlers.similar import SimilarHandler` (123) now transitively loads `router`.

**Regression risk: low.** Test children built the test_video.py way (`dict.fromkeys(signature params)`, test_video.py:170/229) pass `engine_ingest_mode=None` and `rate_limiter=None`. Under such a server, a real ingest request answers 501, because `None != "bridge"`, and rate limiting is off. The new bridge-auth test must replace the ingest table entry (which it plans to do), or its control request would see 501 instead of the stub. In such a child, `bridge_token` comes from the child's `ENGINE_BRIDGE_TOKEN` env, so the test should set `srv.bridge_token` explicitly.
</impact>
<impact path="engine/server/api/server_config.py" element="ENGINE_BRIDGE_TOKEN and BRIDGE_TOKEN_HEADER (lines 500-501)">
**What changes.** Nothing in this file. Its importer changes from handlers/similar.py to router.py; server.py:77 still imports `ENGINE_BRIDGE_TOKEN`.

**What depends on it.** The bridge gate in router.

**Regression risk: low.** It is read at import time from env, the same as today.
</impact>
<impact path="engine/server/api/handlers/internal_events.py" element="handle_internal_events_ingest(handler, server) (line 18)">
**What changes.** Nothing in the file. It is now referenced only from the router's events-ingest adapter, which holds the 501 ingest-mode check before calling it.

**What depends on it.**
- The Client's ingest bridge (client/backend/server.py:1254).
- test_internal_events.py.

**Regression risk: low-medium.** The 501 branch has no existing test; grepping tests/active for `Bridge ingest is disabled` and `501` found only unrelated hits. The planned bridge-auth test swaps this adapter out for a stub, so the 501 path stays unverified by tests. It is preserved only by careful copying.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="handle_internal_video_resolve, handle_internal_videos_metadata, handle_internal_dislike_centroids (lines 86, 130, 175)">
**What changes.** Nothing. They are put into `POST_ROUTES` directly, since their signature is already `(handler: Any, server: Any) -> bool`.

**What depends on it.**
- The Client's engine_api_client.py:100/120/141.
- test_internal_client_reads.py, which imports the module directly.

**Regression risk: low.** The table holds function references, so patching `reads.handle_internal_video_resolve` after import would no longer affect dispatch. No current test does that; they patch inner functions.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="handle_internal_translate, handle_internal_translate_enqueue (lines 277, 312)">
**What changes.** Nothing. They go into `POST_ROUTES` directly.

**What depends on it.**
- The Client's engine_api_client.py:186/207.
- test_internal_translate.py, including the variant Engine at 1044-1074, which asserts 401 without a token and 404 `Video not found` with one. That end-to-end check covers both translate routes through the new router.

**Regression risk: low.** Tests patch `fetch_bounded` and similar inner names, which are unaffected by table references.
</impact>
<impact path="engine/server/api/handlers/video.py" element="handle_video_request, handle_video_refresh_request (lines 463, 449)">
**What changes.** Nothing. They are called from router adapters as `(handler, server, params)`, with `params = parse_qs(urlparse(handler.path).query)`.

**What depends on it.** test_video.py, both in-process and in its Engine children ANSWER_CHILD/PERSIST_CHILD. The children patch `video.fetch_instance_json` / `video.urlopen`, which are module attributes looked up at call time, so dispatch through router still sees the patches.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="package docstring (lines 1-9)">
**What changes.** Possibly nothing; the plan does not mention it. It describes `similar` as the "main Engine read handler for recommendations and read endpoints". After the move that is arguably still true, because `SimilarHandler` is still the one handler class. A one-line reword would avoid implying that it routes, and could mention that routing lives in `api/router.py`. I am flagging this for the operator rather than asserting an edit.

**What depends on it.** Nothing at runtime.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/logging_profiles.py" element="EngineJsonFormatter.format (lines 236-272), _classify_event">
**What changes.** Nothing.

**What depends on it.** The bridge-auth log lines, when they are emitted from router.py. I verified that the formatter emits only ts, level, event, message, modes, request_id, context and traceback. It never emits record.module, funcName, lineno or name. So moving the `logging.error` / `logging.warning` calls to another module leaves output identical as long as they stay on the root logger with the same message text.

**Regression risk: low.** The risk materialises only if the move switches to `logging.getLogger(__name__)`. Even then the formatter would not show the name, but handler and level configuration differ: `configure_engine_logging` sets only the root logger, so a named logger would still propagate. The risk stays small.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="bridge_headers / X-Bridge-Token sender (lines 14, 37-47) and internal POST calls">
**What changes.** Nothing.

**What depends on it.** It depends on the Engine keeping the header name `X-Bridge-Token`, the 401 and 503 semantics, and the exact `/internal/*` paths.

**Regression risk: low.** This is an external consumer that would break if the router's POST table mistyped a path; the stub-backed new test catches only the three stubbed paths. `/internal/videos/metadata` and `/internal/dislikes/centroids` are exercised end-to-end only by existing Client↔Engine tests, such as test_server.py with `engine_client`, test_dislikes and test_blocks.
</impact>
<impact path="client/backend/server.py" element="Client proxy of /api/channels, /api/v1/search/videos, /api/video(/refresh) (lines 80, 93, 101-102) and its own /api/health (418)">
**What changes.** Nothing.

**What depends on it.** It depends on the Engine answering those GET paths with the same bodies. Its own `/api/health` at 418 is the Client's, not the Engine's.

**Regression risk: low.** It is covered by test_server.py:471-474, which runs `/api/channels` through the Client against the real Engine.
</impact>
<impact path="tests/tmp/test_bridge_auth_router.py" element="new test (name to be chosen) - bridge-auth via router with stubbed POST_ROUTES">
**What changes.** A new file. `tests/tmp` is the configured working dir (tests/config.json "working") and holds only probe scripts today.

**Shape.** The test should follow the test_video.py pattern:
- import `ENGINE_PY` and `ROOT` from conftest;
- run a child under `ENGINE_PY` with `SERVER_DIR` and `API_DIR` on `sys.path`;
- build `server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**dict.fromkeys(params[3:]), "db": conn, ...})`;
- start `serve_forever` on a thread.

**Details to get right.**
- `db` must be a real connection, or some placeholder. Health and channels are not hit, so a placeholder may suffice; confirm that the constructor does not touch `db`.
- Set `srv.bridge_token` explicitly for the valid-token control. The env token from conftest's `BRIDGE_TOKEN` (conftest.py:35/260) is an alternative.
- `srv.bridge_token = ""` gives the 503 case.
- The stubs must replace `router.POST_ROUTES[...]` entries, not the handler module functions.
- The control request with a valid token must show that the stub was called once. For `/internal/events/ingest`, replacing the table entry bypasses the 501 adapter. That is acceptable here, but it means the 501 path stays untested.
- The unknown `/internal/` path with a valid token should give 404. This is not in the plan but would be a cheap extra control.

**What depends on it.** It is evidence for acceptance criterion 3.

**Regression risk: medium for test validity.** If the child imports `router` before `handlers.similar`, it still works, since router does not import similar. If the stub is installed after the server thread starts, it is still fine, because lookup happens per request.
</impact>
<impact path="tests/tmp/test_router_fake_route.py" element="new test (name to be chosen) - GET_ROUTES['/fake'] served through real SimilarHandler">
**What changes.** A new file with the same child-process pattern. It adds `router.GET_ROUTES["/fake"] = fn` where `fn(handler, server)` calls `respond_json`, then GETs `/fake` and checks the status and body.

**Details to get right.**
- `/fake` is not under `/api/`, so no rate-limit gate applies.
- A good control: GET `/fake` before adding the entry gives 404, which shows the entry is what serves it.

**What depends on it.** It is evidence for acceptance criterion 5.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_video.py" element="ANSWER_CHILD / PERSIST_CHILD Engine children (lines 159-267) and unrouted-404 controls (631, 659)">
**What changes.** Nothing. This is an existing suite that must pass unchanged. It serves `/api/video`, `/api/video/refresh` and `/videos/v1/similar` through the real handler, now via the router.

**What depends on it.** It is the primary end-to-end check of GET routing: the adapters, the pattern route and its concurrency with the refresh.

**Regression risk: low.** It catches GET table and pattern mistakes.
</impact>
<impact path="tests/active/test_similar.py" element="engine fixture route checks (line 437-439), direct-method children (196, 238-267, 362-388, 471-500, 730, 979-1005)">
**What changes.** Nothing.

**What depends on it.**
- The direct calls to `_handle_similar_request` and `_handle_similar`, and the patching of `similar.respond_json`, `read_json_body`, `_parse_client_likes`, `_resolve_client_likes`, `set_request_client_likes` and `clear_request_context`. All of these names stay in similar.py.
- line 982, which subclasses `SimilarHandler`; that is unaffected.

**Regression risk: low.**

The test docstring line 30 ("The `engine` fixture answers GET /api/health ...") is unaffected. conftest.py:264's comment "(similar.py `_handle_similar`)" also stays true.
</impact>
<impact path="tests/active/test_server.py" element="FEED_MODES child (1399-1414) and Client-through-Engine /api/channels (471-474)">
**What changes.** Nothing.

**What depends on it.** It imports `handlers.similar` under the Engine interpreter, so the router import must resolve there. It does, because the api dir is on the path. It also reaches `/api/channels` through the Client.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_internal_translate.py" element="variant Engine bridge checks (lines 1044-1074)">
**What changes.** Nothing.

**What depends on it.** It is a real-Engine check that `/internal/translate` and `/internal/translate/enqueue` answer 401 without a token and reach their handler with one. That gives the router independent coverage of the bridge gate on two routes.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_frontend_feed_params.py" element="AST read of FEED_MODES from similar.py (lines 41, 120)">
**What changes.** Nothing.

**What depends on it.** `FEED_MODES` must remain a module-level tuple literal assignment in `handlers/similar.py`. The plan keeps it there; it must not be moved alongside the routing code.

**Regression risk: low.** It is listed because a broader-than-planned cleanup of similar.py's top section would break it silently.
</impact>
<impact path="engine/server/api/tests/test_recommendations_likes_limit.py" element="direct _handle_similar_request tests with patched similar.respond_json">
**What changes.** Nothing.

**What depends on it.** `similar.SIMILAR_POST_ROUTES` must still be visible inside similar.py as a module global, because `_recommendations_likes_payload_error` reads it. An import-back gives that. It also needs `similar.DEFAULT_CLIENT_LIKES_MAX` and `similar.respond_json`, both of which stay.

**Regression risk: low.**
</impact>
<impact path="tests/config.json" element="test_groups entries (e.g. test_similar.py, test_video.py, test_internal_translate.py, test_internal_events.py, test_server.py, test_logging_profiles.py)">
**What changes.** Uncertain; the plan does not mention it. These groups map test files to the source files whose change should trigger them. The new `engine/server/api/router.py` is in no group, so a later edit to the router alone would select no test. Consider adding `router.py` wherever `handlers/similar.py` appears for routing reasons, and adding `http_utils.py` to `test_video.py`/`test_server.py` if they rely on the parse helpers. Whether this file is edited as part of builds is a process question for the operator.

**What depends on it.** The test-selection tooling.

**Regression risk: none at runtime.** The risk is a coverage-selection gap.
</impact>
<impact path="engine/server/README.md" element="route list (lines 7-27) and references at lines 50 and 53">
**What changes.** Nothing, by operator decision.
- Line 50 cites `_parse_include_nsfw` in `api/handlers/similar.py`, and line 53 cites `SimilarHandler._run_request` in `api/handlers/similar.py`. Both stay true.
- The route list stays incomplete: it lacks `/api/health`, `/api/channels` and `/api/v1/search/videos`. `router.py`'s docstring becomes the complete list.
- No README line names `_dispatch_*`, `_bridge_authorized` or `SIMILAR_POST_ROUTES`; I grepped for them.

**What depends on it.** Human readers.

**Regression risk: none.** There is doc drift between README and router.py, which the operator accepts.
</impact>
<impact path="docs/project/adr/0007-nsfw-filter-default-at-request-edge.md" element="decision point 2 (line 17)">
**What changes.** Nothing. It cites `_handle_similar` and `_parse_include_nsfw` in `api/handlers/similar.py`, and `_handle_search`. None of these move.

**Regression risk: none.** It is listed for completeness, because it names the module being edited.
</impact>
<impact path="DEPLOYMENT.md" element="§3b bridge shared secret (lines 504-509) and triage row (line 315)">
**What changes.** Nothing. The 503/401 behaviour and the `bridge.auth` log event it documents are preserved, and it names no source file or function.

**Regression risk: none,** as long as the log message text is unchanged.
</impact>
<impact path="docs/project/issues/58-engine-routing-out-of-similar-handler.md" element="issue status line">
**What changes.** Not in this step. On delivery, the triage-labels convention moves the issue to `complete` and into `docs/project/issues/archive/`.

**Regression risk: none.**
</impact>
</impacts>

## Documentation to update

- [ ] `engine/server/api/router.py` - New module docstring: the complete Engine route list with method and gate per route. That means every route from the old similar.py docstring, plus `/internal/dislikes/centroids` and `/api/v1/search/videos`, with `/api/health` and `/api/channels` kept. `/internal/*` POST routes are marked as behind the bridge-auth gate, `/api/*` GET routes as behind the rate-limit gate, `/videos/{id}/similar` as having its own rate-limit check, and `/internal/events/ingest` as answering 501 outside bridge mode.
- [ ] `engine/server/api/handlers/similar.py` - Module docstring rewritten to describe only recommendations, similar, feeds and search, with the route list removed and a pointer to `api/router.py`. The `do_GET`/`do_POST` docstrings are reworded to "hand the request to the router", and `_serve_get`/`_serve_post` now say they route instead of dispatching.
- [ ] `engine/server/api/handlers/__init__.py` - Optional, not in the plan: the package docstring calls `similar` the "main Engine read handler for recommendations and read endpoints". A reword could note that routing now lives in `api/router.py`. Operator's call.
- [ ] `engine/server/README.md` - No edit, by operator decision. I verified that its references to `SimilarHandler._run_request` (line 53) and `_parse_include_nsfw` (line 50) in `api/handlers/similar.py` stay true. Its route list (lines 7-27) stays incomplete; router.py becomes the complete list.

## Implementation plan

## Draft — issue 58: Engine routing out of `SimilarHandler`

Files I read for this draft: `handlers/similar.py` (lines 1-120, 300-650, 1160-1275), `http_utils.py`, `server.py:240-300` and its `sys.path` setup at 21-23, the import blocks of `handlers/internal_*.py` and `handlers/video.py`, `handlers/__init__.py`, `tests/active/test_video.py` (the child pattern and its `subprocess.run` lines 564/608), `tests/active/conftest.py:1-60` and `tests/config.json`. Everything below matches the plan. Pass 1 against the plan and the requirements came out clean, so no further passes were needed. The one thing that differs from the plan's wording, the channels rename, is called out in the similar.py section.

### What has to be tested

- **Bridge gate on POST `/internal/*`.**
  - Missing token gives 401. A wrong token gives 401. An unset token (`""`) gives 503.
  - This holds for one route of each kind (resolve, translate, ingest) and for an unknown `/internal/` path.
  - The handler does not run in any of those cases.
  - A valid token reaches the stub once per path, and the unknown path gets 404.
- **Fake route.** A `GET_ROUTES` entry alone serves `/fake` through the real `SimilarHandler`. Before the entry exists, `/fake` gets 404.
- **Cheap extras, not in the plan.** Each closes a gap the impact inventory names:
  - the 501 ingest-mode body with its `mode` field, which was untested until now;
  - the plain 404 for GET `/internal/*`, which has no gate.
- **Everything else is covered by existing suites, unchanged.**
  - test_video: the `/api/video` and refresh adapters, the `/videos/{id}/similar` pattern, and unrouted 404s.
  - test_internal_translate 1044-1074: real bridge 401s on two routes.
  - test_server: `/api/channels` via the Client.
  - The conftest `/api/health` readiness probe, which every Engine fixture depends on.
  - test_similar and test_recommendations_likes_limit: direct `_handle_similar*` calls and `SIMILAR_POST_ROUTES` through the import-back.

### Module map

| File | Change |
|---|---|
| `engine/server/api/router.py` | **new.** Route list docstring, `SIMILAR_POST_ROUTES`, `GET_ROUTES`, `POST_ROUTES`, adapters, `handle_health`, `handle_channels`, `_extract_video_id_from_similar_path`, `bridge_authorized`, `route_get`, `route_post` |
| `engine/server/api/http_utils.py` | adds `parse_int`, `parse_non_negative_int` (moved unchanged) |
| `engine/server/api/handlers/similar.py` | docstring, imports, `SIMILAR_POST_ROUTES` removed (imported back), `_bridge_authorized`/`_dispatch_*` removed, `_serve_*` call the router, 4 call-site renames, 3 helpers removed |
| `tests/tmp/test_router_bridge_auth.py` | **new** |
| `tests/tmp/test_router_fake_route.py` | **new** |

Dependency direction: `handlers.similar` → `router` → `handlers.internal_*`, `handlers.video`, `http_utils`, `server_config`, `data.*`. Nothing below `router` imports `handlers.similar`; I checked all four import blocks. `handlers/__init__.py` is docstring only, so importing `handlers.internal_events` from inside a partly initialised `handlers.similar` is safe.

### `engine/server/api/router.py` (whole file)

```python
"""Route Engine HTTP requests to their handlers.

SimilarHandler hands every GET and POST here, inside its statement deadline. A route is one entry in GET_ROUTES or POST_ROUTES keyed by exact path (query string ignored, no trailing-slash match) whose value takes (handler, server); a path in neither table, or sent with the other method, answers 404 {"error": "Not found"}.

Routes:
- POST /recommendations: recommendation feed and debug payloads; own per-IP rate-limit check.
- POST /videos/similar: extended similar route; own per-IP rate-limit check.
- GET /videos/{id}/similar: id-based similar alias; the one pattern route, tried after an exact miss, with its own per-IP rate-limit check.
- GET /api/health: health check. [rate-limit gate]
- GET /api/channels: channels listing. [rate-limit gate]
- GET /api/v1/search/videos: hybrid video search. [rate-limit gate]
- GET /api/video: single video metadata. [rate-limit gate]
- GET /api/video/refresh: single video metadata refreshed from its instance. [rate-limit gate]
- POST /internal/videos/resolve: internal Client read lookup by video_id/uuid(+host). [bridge gate]
- POST /internal/videos/metadata: internal Client metadata batch lookup. [bridge gate]
- POST /internal/dislikes/centroids: internal Client clustering of a visitor's disliked videos into taste centroids; nothing stored. [bridge gate]
- POST /internal/translate: internal Client read of a video's English translate state and whether a translate worker is serving; cues from a stored job, or from its own instance (cached). [bridge gate]
- POST /internal/translate/enqueue: internal Client request to queue a video's whisper translate job while a translate worker is serving. [bridge gate]
- POST /internal/events/ingest: internal bridge ingest for normalized events; 501 outside ENGINE_INGEST_MODE=bridge. [bridge gate]

Gates:
- bridge gate: every POST /internal/* path, unknown ones included, needs the shared X-Bridge-Token first: 503 when the Engine has none configured, 401 when it is missing or wrong.
- rate-limit gate: every GET /api/* path, unknown ones included, passes the per-IP limiter first: 429.
- GET /internal/* has no gate and answers 404.
"""
import hmac
import logging
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from data.channels import fetch_channels
from data.time import now_ms
from http_utils import parse_int, parse_non_negative_int, respond_json
from server_config import BRIDGE_TOKEN_HEADER, ENGINE_BRIDGE_TOKEN
from handlers.internal_events import handle_internal_events_ingest
from handlers.internal_client_reads import (
    handle_internal_dislike_centroids,
    handle_internal_video_resolve,
    handle_internal_videos_metadata,
)
from handlers.internal_translate import handle_internal_translate, handle_internal_translate_enqueue
from handlers.video import handle_video_refresh_request, handle_video_request


SIMILAR_POST_ROUTES = {"/recommendations", "/videos/similar"}


def handle_health(handler: Any, server: Any) -> None:
    """Answer the health check with the loaded embedding count and dimension."""
    payload = {
        "ok": True,
        "total": server.embeddings_count,
        "embeddingDim": server.embeddings_dim,
    }
    respond_json(handler, 200, payload)


def handle_channels(handler: Any, server: Any) -> None:
    """Answer a page of the channels listing."""
    params = parse_qs(urlparse(handler.path).query)
    limit = parse_int(params.get("limit", [None])[0])
    if limit <= 0:
        limit = 100
    limit = min(limit, 500)
    offset = parse_int(params.get("offset", [None])[0])
    max_videos = parse_non_negative_int(params.get("maxVideos", [None])[0])
    with server.db_lock:
        rows, total = fetch_channels(
            server.db,
            limit=limit,
            offset=offset,
            query=params.get("q", [""])[0] or "",
            instance=params.get("instance", [""])[0] or "",
            min_followers=parse_int(params.get("minFollowers", [None])[0]),
            min_videos=parse_int(params.get("minVideos", [None])[0]),
            max_videos=max_videos,
            sort=params.get("sort", ["followers"])[0] or "followers",
            direction=params.get("dir", ["desc"])[0] or "desc",
        )
    respond_json(
        handler,
        200,
        {
            "generatedAt": now_ms(),
            "total": total,
            "rows": rows,
        },
    )


def _similar_post(handler: Any, server: Any) -> None:
    """Serve a recommendations or extended-similar POST through the handler's similarity path."""
    handler._handle_similar_request(method="POST")


def _search(handler: Any, server: Any) -> None:
    """Serve a video search with the request's query parameters."""
    handler._handle_search(parse_qs(urlparse(handler.path).query))


def _video(handler: Any, server: Any) -> None:
    """Serve single video metadata with the request's query parameters."""
    handle_video_request(handler, server, parse_qs(urlparse(handler.path).query))


def _video_refresh(handler: Any, server: Any) -> None:
    """Serve refreshed single video metadata with the request's query parameters."""
    handle_video_refresh_request(handler, server, parse_qs(urlparse(handler.path).query))


def _events_ingest(handler: Any, server: Any) -> None:
    """Serve bridge ingest, answering 501 when the Engine is not in bridge ingest mode."""
    if getattr(server, "engine_ingest_mode", "bridge") != "bridge":
        respond_json(
            handler,
            501,
            {
                "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
                "mode": getattr(server, "engine_ingest_mode", "bridge"),
            },
        )
        return
    handle_internal_events_ingest(handler, server)


# Exact path -> callable(handler, server); read per request, so a test may add or replace an entry at run time.
GET_ROUTES: dict[str, Callable[[Any, Any], Any]] = {
    "/api/health": handle_health,
    "/api/channels": handle_channels,
    "/api/v1/search/videos": _search,
    "/api/video": _video,
    "/api/video/refresh": _video_refresh,
}

POST_ROUTES: dict[str, Callable[[Any, Any], Any]] = {
    **dict.fromkeys(SIMILAR_POST_ROUTES, _similar_post),
    "/internal/videos/resolve": handle_internal_video_resolve,
    "/internal/videos/metadata": handle_internal_videos_metadata,
    "/internal/dislikes/centroids": handle_internal_dislike_centroids,
    "/internal/translate": handle_internal_translate,
    "/internal/translate/enqueue": handle_internal_translate_enqueue,
    "/internal/events/ingest": _events_ingest,
}


def _extract_video_id_from_similar_path(path: str) -> str | None:
    """Resolve /videos/{id}/similar route shape to seed video id."""
    if not path.startswith("/videos/") or not path.endswith("/similar"):
        return None
    parts = path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "videos" or parts[2] != "similar":
        return None
    video_id = parts[1].strip()
    return video_id or None


def bridge_authorized(handler: Any) -> bool:
    """Check the shared secret on internal bridge routes.

    These routes write to the interaction event stream and read across the
    Client/Engine boundary, so an unset secret fails closed: accepting them
    unauthenticated is what let any browser rewrite the global ranking.
    """
    configured = getattr(handler.server, "bridge_token", ENGINE_BRIDGE_TOKEN)
    if not configured:
        logging.error(
            "[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting %s", handler.path
        )
        respond_json(
            handler, 503, {"error": "Bridge token is not configured on the Engine"}
        )
        return False
    presented = handler.headers.get(BRIDGE_TOKEN_HEADER, "").strip()
    if not presented or not hmac.compare_digest(presented, configured):
        logging.warning(
            "[bridge.auth] rejected %s from ip=%s", handler.path, handler._get_client_ip()
        )
        respond_json(handler, 401, {"error": "Unauthorized"})
        return False
    return True


def route_post(handler: Any) -> None:
    """Route a POST through the /internal/ bridge gate to its POST_ROUTES entry, or 404."""
    url = urlparse(handler.path)
    if url.path.startswith("/internal/") and not bridge_authorized(handler):
        return
    route = POST_ROUTES.get(url.path)
    if route is not None:
        route(handler, handler.server)
        return
    respond_json(handler, 404, {"error": "Not found"})


def route_get(handler: Any) -> None:
    """Route a GET through the /api/ rate-limit gate to its GET_ROUTES entry, the /videos/{id}/similar pattern, or 404."""
    url = urlparse(handler.path)
    if url.path.startswith("/api/") and not handler._rate_limit_check(url.path):
        respond_json(handler, 429, {"error": "Rate limit exceeded"})
        return
    route = GET_ROUTES.get(url.path)
    if route is not None:
        route(handler, handler.server)
        return
    video_path_id = _extract_video_id_from_similar_path(url.path)
    if video_path_id is not None:
        if not handler._rate_limit_check(url.path):
            respond_json(handler, 429, {"error": "Rate limit exceeded"})
            return
        params = parse_qs(url.query)
        params.setdefault("id", [video_path_id])
        handler._handle_similar(params)
        return
    respond_json(handler, 404, {"error": "Not found"})
```

**Invariants**

- **Gate order.**
  - `route_post`: the bridge gate, then `POST_ROUTES.get`, then 404.
  - `route_get`: the `/api/` limiter, then `GET_ROUTES.get`, then the pattern (limiter, then `setdefault`, then `_handle_similar`), then 404.
  - This is the same order as `similar.py:442-562`.
- **Table lookups happen at call time.** The tables are plain module-level dicts and are never copied.
- **Logging stays byte-identical.** Bridge-auth logging uses the root `logging.error` / `logging.warning` with the old format strings and the raw `handler.path`.
- **Return values are ignored.** Each `handle_internal_*` returns a bool, and the router discards it, as the old chain did.
- **Small differences that cannot change an outcome.**
  - `parse_qs` now runs after the pattern's limiter, where the old code ran it before. `parse_qs` with default arguments cannot raise, so this changes nothing.
  - Search and video re-parse the query from `handler.path`. That gives the same dict the old shared `params` did.
- **No import of `handlers.similar` anywhere in this file.** The router reaches similarity only through methods on `handler`: `_handle_similar_request`, `_handle_similar`, `_handle_search`, `_rate_limit_check` and `_get_client_ip`.

### `engine/server/api/http_utils.py` (insert after `read_json_body`, before `class RateLimiter`)

```python
def parse_int(value: str | None) -> int:
    """Parse a positive integer; return 0 on invalid input."""
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def parse_non_negative_int(value: str | None) -> int | None:
    """Parse a non-negative integer; return None on invalid input."""
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
```

The bodies and docstrings are byte-for-byte the old `_parse_int` / `_parse_non_negative_int`. No new import is needed.

### `engine/server/api/handlers/similar.py` edits

1. **Docstring.** Lines 1-20 become:
```python
"""Similarity HTTP handler for Engine read surface.

Serves recommendations, similar videos (by id and the extended POST route), the home feeds and hybrid video search. SimilarHandler is the Engine's one request handler class; it hands every GET and POST to `api/router.py`, which holds the route list, the bridge-auth and rate-limit gates and the 404.

Key steps:
- Parse seed/params, resolve likes (client JSON or users DB).
- Build candidate pools, score, mix, and return stable rows.
"""
```
2. **Imports.**
   - Removed:
     - `import hmac` (22);
     - `from data.channels import fetch_channels` (36);
     - `BRIDGE_TOKEN_HEADER,` (52) and `ENGINE_BRIDGE_TOKEN,` (58) from the `server_config` import;
     - lines 96-103, the four handler imports.
   - Line 80 becomes `from http_utils import parse_int, parse_non_negative_int, read_json_body, respond_json, respond_options, resolve_user_id`.
   - Added in place of 96-103: `from router import SIMILAR_POST_ROUTES, route_get, route_post`.
   - Kept: `urlparse` / `parse_qs` (643/647), `now_ms`, `sqlite3`, `Callable`, `logging`.
3. **`SIMILAR_POST_ROUTES = {...}` (106) is deleted.** `_recommendations_likes_payload_error` (234) reads the imported name, unchanged. `FEED_MODES` stays a module-level tuple literal, as test_frontend_feed_params requires.
4. **`do_POST` / `_serve_post` (403-415):**
```python
    def do_POST(self) -> None:  # noqa: N802
        """Hand a POST to the router under the time budget."""
        self._run_request(self._serve_post)

    def _serve_post(self) -> None:
        """Route a POST under the time budget, answering 503 when its database work is interrupted."""
        try:
            with self._statement_deadline():
                route_post(self)
        except sqlite3.OperationalError as exc:
            if not is_interrupted_error(exc):
                raise
            self._respond_interrupted()
```
5. **`_bridge_authorized` (417-440) and `_dispatch_post` (442-478) are deleted.**
6. **`do_GET` / `_serve_get` (480-492):** the same shape, with docstrings `"""Hand a GET to the router under the time budget."""` / `"""Route a GET under the time budget, answering 503 when its database work is interrupted."""` and the body `route_get(self)`.
7. **`_dispatch_get` (494-562) is deleted.**
8. **Renames.** These are the only remaining call sites (grep-verified):
   - 584 `_parse_int` → `parse_int`;
   - 588 `_parse_int` → `parse_int`;
   - 1035 `_parse_int` → `parse_int`;
   - 1062 `_parse_non_negative_int` → `parse_non_negative_int`.

   The plan says channels call sites "stay". That is slightly off: they move into `router.handle_channels` instead, as the impact inventory already notes.
9. **Deleted helpers:** `_parse_int` (1167-1173), `_parse_non_negative_int` (1191-1199) and `_extract_video_id_from_similar_path` (1267-1275). `_parse_bool` and `_parse_include_nsfw` stay.
10. **Post-edit grep must return nothing** in similar.py for: `_parse_int(`, `_parse_non_negative_int`, `_extract_video_id`, `fetch_channels`, `hmac`, `ENGINE_BRIDGE_TOKEN`, `BRIDGE_TOKEN_HEADER`, `_dispatch_`, `_bridge_authorized`, `handlers.internal_`, `handlers.video`. A missed rename would only surface at request time, as a NameError.

Nothing else in `SimilarHandler` changes. `_run_request`, the deadline and 503 wrapper, `_get_client_ip`, `_get_full_url`, `log_request`, `log_message`, `do_OPTIONS`, `_rate_limit_check` and every similarity, feed and search method stay as they are.

### Tests

Both tests are pytest launchers that run an Engine child the way test_video does: `subprocess.run([ENGINE_PY, "-c", CHILD], cwd=API_DIR)`. The child imports `server` first, because it puts `engine/server` on `sys.path`. Then it builds a real `SimilarServer` with the real `SimilarHandler` on port 0, using `dict.fromkeys(signature params[3:])`. So `db`, `rate_limiter` and `engine_ingest_mode` are all `None`; the constructor never touches `db`, and these paths never reach it.

`ROOT` and `ENGINE_PY` are defined locally, with the same expressions as conftest. `tests/tmp` has no conftest, and importing `tests/active/conftest.py` would load the Client backend. That is a deliberate two-line duplication; when the files are archived to `tests/active`, switch to `from conftest import ENGINE_PY, ROOT`.

**`tests/tmp/test_router_bridge_auth.py`**

```python
"""POST /internal/* behind the router's bridge-auth gate (engine/server/api/router.py), through a real SimilarServer and SimilarHandler in an Engine child.

- With the Engine's token set, a POST to /internal/videos/resolve, /internal/translate, /internal/events/ingest or an unknown /internal/ path answers 401 {"error": "Unauthorized"} without an X-Bridge-Token and with a wrong one, and 503 {"error": "Bridge token is not configured on the Engine"} once the token is "".
- None of those requests reaches the route: the three routes' POST_ROUTES entries are replaced by a recording stub, which records nothing for them; with the right token each stub is reached once and the unknown path answers 404 {"error": "Not found"}.
- Before the stubs, a valid-token ingest under engine_ingest_mode None answers 501 with that mode, from the router's own ingest adapter.
- A GET to /internal/videos/resolve answers a plain 404, with no gate.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
API_DIR = ROOT / "engine" / "server" / "api"

CHILD = r'''
import http.client, inspect, json, threading
import server
import router
from handlers.similar import SimilarHandler
from http_utils import respond_json

TOKEN = "router-test-token"
STUBBED = ["/internal/videos/resolve", "/internal/translate", "/internal/events/ingest"]
PATHS = STUBBED + ["/internal/no-such-route"]

def send(port, method, path, headers):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    client.request(method, path, body=b"{}" if method == "POST" else None, headers=headers)
    resp = client.getresponse()
    body = json.loads(resp.read() or b"null")
    client.close()
    return [resp.status, body]

args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **args)
srv.bridge_token = TOKEN
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
calls = []
def stub(handler, server_):
    calls.append(handler.path)
    respond_json(handler, 200, {"stub": handler.path})
report = {}
try:
    report["ingest_mode"] = send(port, "POST", "/internal/events/ingest", {"X-Bridge-Token": TOKEN})
    for path in STUBBED:
        router.POST_ROUTES[path] = stub
    report["missing"] = {p: send(port, "POST", p, {}) for p in PATHS}
    report["wrong"] = {p: send(port, "POST", p, {"X-Bridge-Token": "wrong"}) for p in PATHS}
    report["calls_rejected"] = list(calls)
    report["valid"] = {p: send(port, "POST", p, {"X-Bridge-Token": TOKEN}) for p in PATHS}
    report["calls_valid"] = list(calls)
    srv.bridge_token = ""
    report["unset"] = {p: send(port, "POST", p, {"X-Bridge-Token": TOKEN}) for p in PATHS}
    report["calls_after_unset"] = list(calls)
    report["get_internal"] = send(port, "GET", "/internal/videos/resolve", {"X-Bridge-Token": TOKEN})
finally:
    srv.shutdown()
    srv.server_close()
print(json.dumps(report))
'''

PATHS = ["/internal/videos/resolve", "/internal/translate", "/internal/events/ingest", "/internal/no-such-route"]
STUBBED = PATHS[:3]
UNAUTHORIZED = [401, {"error": "Unauthorized"}]
UNSET = [503, {"error": "Bridge token is not configured on the Engine"}]


def test_internal_posts_are_gated_before_their_route():
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["ingest_mode"] == [501, {"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": None}]
    assert report["missing"] == {path: UNAUTHORIZED for path in PATHS}
    assert report["wrong"] == {path: UNAUTHORIZED for path in PATHS}
    assert report["calls_rejected"] == []
    assert report["valid"] == {**{path: [200, {"stub": path}] for path in STUBBED}, "/internal/no-such-route": [404, {"error": "Not found"}]}
    assert report["calls_valid"] == STUBBED
    assert report["unset"] == {path: UNSET for path in PATHS}
    assert report["calls_after_unset"] == STUBBED
    assert report["get_internal"] == [404, {"error": "Not found"}]
```

**`tests/tmp/test_router_fake_route.py`**

```python
"""A route added as one router.GET_ROUTES entry, with no edit to handlers/similar.py, is served through a real SimilarServer and SimilarHandler in an Engine child.

- Before the entry, GET /fake answers 404 {"error": "Not found"}.
- After router.GET_ROUTES["/fake"] is set to a function answering through respond_json, GET /fake?x=1 answers 200 with that function's body, which carries the raw request path, query included.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
API_DIR = ROOT / "engine" / "server" / "api"

CHILD = r'''
import http.client, inspect, json, threading
import server
import router
from handlers.similar import SimilarHandler
from http_utils import respond_json

def get(port, path):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    client.request("GET", path)
    resp = client.getresponse()
    body = json.loads(resp.read() or b"null")
    client.close()
    return [resp.status, body]

def fake(handler, server_):
    respond_json(handler, 200, {"fake": True, "path": handler.path})

args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **args)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
report = {}
try:
    report["before"] = get(port, "/fake")
    router.GET_ROUTES["/fake"] = fake
    report["after"] = get(port, "/fake?x=1")
finally:
    srv.shutdown()
    srv.server_close()
print(json.dumps(report))
'''


def test_fake_route_is_served_from_a_table_entry():
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["before"] == [404, {"error": "Not found"}]
    assert report["after"] == [200, {"fake": True, "path": "/fake?x=1"}]
```

### Decisions behind the draft

- **Table signature `(handler, server)`.** The five client-read and translate handlers go into the table with no adapter. The four adapters are named one-line-docstring functions, matching the file style; no lambdas.
- **`POST_ROUTES` derives its two similar entries from `SIMILAR_POST_ROUTES` with `dict.fromkeys`.** Each path string is written exactly once, in router.py.
- **`handle_health` / `handle_channels` are public `handle_*`,** following the `handlers/*.py` naming. The adapters are private, because nothing outside the router should call them.
- **Tests replace table entries, never module functions.** Only the table entry is looked up at dispatch time.
- **Ingest 501 check runs before stubbing.** The 501 request comes before the stubs replace the ingest entry, so the router's own adapter is exercised. `handle_internal_events_ingest` is never reached there, because `engine_ingest_mode` is `None`.
- **Deliberate simplification: one hard-coded pattern route.** `/videos/{id}/similar` is special-cased in `route_get`. The ceiling is a second parameterised path. The upgrade is an ordered list of `(matcher, callable)` pairs tried after the exact lookup.

### Left for the operator (not edited, outside the settled plan)

- **`handlers/__init__.py`.** The docstring line "similar: main Engine read handler …" could gain "routing lives in `api/router.py`". This is optional, per the inventory.
- **`tests/config.json`.** `engine/server/api/router.py` is in no test group, so an edit to the router alone selects no test. Candidates for adding it: `test_similar.py`, `test_video.py`, `test_internal_translate.py`, `test_internal_events.py` and `test_server.py`. This is a process decision.

### Phases

#### Phase 1 - Engine routing moves into router.py [code]

**Files touched.** engine/server/api/router.py (NEW), engine/server/api/http_utils.py (EDITED), engine/server/api/handlers/similar.py (EDITED), tests/tmp/test_router_bridge_auth.py (NEW), tests/tmp/test_router_fake_route.py (NEW)

**Checkpoint.** Seam: real HTTP requests into a real `SimilarServer` running the real `SimilarHandler` on an ephemeral port. The server runs in an Engine child process (`ENGINE_PY -c CHILD`, cwd `engine/server/api`), which imports `server` first so the `sys.path` setup runs. The server is built with `dict.fromkeys(signature params[3:])`. This copies the existing child harness in `tests/active/test_video.py`, the precedent for this seam. The only shim is a replaced router table entry, never a patched module function, because dispatch looks up the table per request. `tests/tmp/test_router_bridge_auth.py` (clause_1) replaces the `POST_ROUTES` entries for `/internal/videos/resolve`, `/internal/translate` and `/internal/events/ingest` with recording stubs. It then asserts, for those three paths plus `/internal/no-such-route`: 401 `{"error": "Unauthorized"}` with no token; 401 again with a wrong token; zero stub calls after both; 503 `{"error": "Bridge token is not configured on the Engine"}` after `srv.bridge_token = ""`, with no new stub calls. A valid-token control reaches each stub exactly once and gets 404 on the unknown path. Without that control, the zero counts would prove nothing. Beyond the clause, the same test asserts the ingest adapter's 501 body with `mode: None` and the ungated plain 404 for GET `/internal/videos/resolve`. `tests/tmp/test_router_fake_route.py` (clause_2) asserts that GET `/fake` answers 404 `{"error": "Not found"}` before `router.GET_ROUTES["/fake"]` is set. After it is set, GET `/fake?x=1` answers 200 with the stub's body carrying the raw path, which proves the request reached the stub through the real handler. Existing suites cover everything else unchanged: test_video, test_internal_translate 1044-1074, test_server `/api/channels`, the conftest `/api/health` probe, test_similar and test_recommendations_likes_limit.

**Intent.** Every Engine GET and POST that `SimilarHandler` receives is answered by `engine/server/api/router.py`, through its `/internal/` bridge gate, its `/api/` rate-limit gate and its `GET_ROUTES`/`POST_ROUTES` tables. `SimilarHandler`'s own `_dispatch_*` and `_bridge_authorized` methods no longer exist.

- C1 - Every POST to an `/internal/*` path, unknown paths included, gets the router's bridge-gate answer before its `POST_ROUTES` entry runs: 401 when the token is missing or wrong, 503 when the Engine has none set.
- C2 - A route added as one `GET_ROUTES` entry, with no edit to `handlers/similar.py`, is served through the real `SimilarHandler`.

**Outcome.** ### `engine/server/api/router.py` (new)
- The module docstring is now the full Engine route list. Each entry gives the method and gate, and it adds the two routes the old similar.py docstring left out: `/internal/dislikes/centroids` and `/api/v1/search/videos`.
- `SIMILAR_POST_ROUTES` moved here from similar.py. The two similar POST entries in `POST_ROUTES` are built from it with `dict.fromkeys`.
- `GET_ROUTES` and `POST_ROUTES` are plain module dicts mapping an exact path to `callable(handler, server)`. They are looked up on every request.
  - The three client-read handlers and the two translate handlers go into the table as they are.
  - Thin adapters cover the rest: `_similar_post`, `_search`, `_video`, `_video_refresh`, and `_events_ingest`, which now holds the 501 ingest-mode check with its `mode` field.
- `handle_health` and `handle_channels` are the old inline `/api/health` and `/api/channels` blocks, moved over unchanged.
- `_extract_video_id_from_similar_path` moved here unchanged.
- `bridge_authorized(handler)` is the old `_bridge_authorized` with `self` replaced by `handler`. The token fallback, the stripped `X-Bridge-Token`, `hmac.compare_digest`, the 503/401 bodies and the root-logger `[bridge.auth]` lines are all the same.
- `route_post(handler)`: the `/internal/` bridge gate, then a `POST_ROUTES` lookup, then 404.
- `route_get(handler)`: the `/api/` rate-limit gate (429), then a `GET_ROUTES` lookup, then the `/videos/{id}/similar` pattern, then 404. The pattern keeps its own limiter, then `setdefault("id")`, then `_handle_similar`.
- The one hard-coded pattern route carries a `rat-tail:` comment naming its ceiling and upgrade path.
- The router never imports `handlers.similar`, so there is no import cycle.

### `engine/server/api/http_utils.py`
- Added `parse_int` and `parse_non_negative_int`, moved byte-for-byte from similar.py's `_parse_int` and `_parse_non_negative_int`. The router's channels code and similar.py's search and similar code share them.

### `engine/server/api/handlers/similar.py`
- **Docstring:** the module docstring now describes only similarity (recommendations, similar, feeds, search) and points to `api/router.py` for the route list.
- **Imports removed:** `hmac`, `fetch_channels`, `BRIDGE_TOKEN_HEADER`, `ENGINE_BRIDGE_TOKEN`, and the `handlers.internal_events`, `handlers.internal_client_reads`, `handlers.internal_translate` and `handlers.video` imports.
- **Imports added:** `from router import SIMILAR_POST_ROUTES, route_get, route_post`, plus `parse_int` and `parse_non_negative_int` from `http_utils`. `_recommendations_likes_payload_error` reads the imported `SIMILAR_POST_ROUTES`.
- **Methods removed:** `_bridge_authorized`, `_dispatch_post` and `_dispatch_get`. `_serve_post` and `_serve_get` keep the statement-deadline / interrupted-503 wrapper and now call `route_post(self)` and `route_get(self)` inside it. The `do_GET`/`do_POST` and `_serve_*` docstrings were reworded to say they hand the request to the router.
- **Renames:** four call sites renamed to the public names (`_handle_search` limit and page, `_handle_similar` limit and seed).
- **Helpers removed:** `_parse_int`, `_parse_non_negative_int` and `_extract_video_id_from_similar_path`. `_parse_bool`, `_parse_include_nsfw` and `FEED_MODES` stay.

### `tests/tmp/test_router_bridge_auth.py`, `tests/tmp/test_router_fake_route.py`
- Not created. The gated checkpoint `tests/tmp/test_58_engine_routing_out_of_similar_phase1.py` already holds both planned tests (bridge gate and fake route), so writing them again would only duplicate it.

### Verification
- I did not run the checkpoint.
- A throwaway import probe under the Engine interpreter showed:
  - `server`, `handlers.similar` and `router` import with no cycle;
  - both tables hold the expected paths;
  - `similar.SIMILAR_POST_ROUTES is router.SIMILAR_POST_ROUTES`;
  - `_dispatch_get` is gone;
  - `parse_int(" 5") == 5` and `parse_non_negative_int("-1") is None`.

**Beyond the files named.** tests/tmp/probe_router_import.py — a throwaway import probe I wrote and ran through ValidateTests. I have no tool that deletes files, so it is still there: please delete it. It is named `probe_*`, not `test_*`, so the default pytest collection should skip it.


