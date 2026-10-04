# Build record - 58-engine-routing-out-of-similar

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/01-58-engine-routing-out-of-similar.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Move Engine routing out of handlers/similar.py\n\nStatus: enhancement, ready-for-agent\nOrigin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate \"routing out of handlers/similar.py\" (Speculative)\n\n## Problem\n\n`SimilarHandler` is the Engine's only handler class (`engine/server/api/server.py:123, 469`). Routing and bridge auth for every `/internal/*` route therefore live in `engine/server/api/handlers/similar.py`, a 1275-line file named for similarity:\n- dispatch at `:442-478`;\n- bridge auth at `:413-440`.\n\nThe translate builds edited it only to add routes:\n- the import at `:102`;\n- the route list in the docstring at `:13-14`;\n- the dispatch branches at `:459-464`.\n\nThe cost is to locality, not depth: every new route edits the similarity file. The review didn't read the similarity code itself.\n\n## Proposed solution\n\nMove the dispatch table and bridge auth into a router module of their own. This moves code without hiding anything new, so it is low value until routes keep being added. Triage may reasonably close it as `wontfix`.\n\n## Related\n\n- `engine/server/README.md` (route list).\n\n## Comments\n\n**Triage (2026-10-04).** The code claims above were checked against the tree, and all of them hold. Bridge auth now sits at `similar.py:417-440`, four lines off. The GET dispatch (`:494` on) also holds the `/api/` rate-limit gate and answers `/api/health` and `/api/channels` inline. Nothing already does this, and there are no prior rejections.\n\nThe issue says the move is low value \"until routes keep being added\", and the roadmap says they will. It plans new endpoints in F1-M3 (public REST API), F5-M3 and F1-M4. F2-M3 (API versioning) touches every unversioned route. F7-M7 and F10-M7 (rate limiting, service keys) sit where the bridge-auth and rate-limit gates sit today. The maintainer chose to brief it now.\n\nScope is the smallest move that answers the issue. The route tables and the bridge-auth gate leave `similar.py`. `SimilarHandler`, its request lifecycle and its similarity methods stay, because tests call them directly on stubs.\n\n## Agent Brief\n\n**Category:** enhancement\n**Summary:** Move the Engine's route dispatch and its `/internal/*` bridge-auth gate out of the similarity handler module into a router module of their own, with no change to any route's behaviour.\n\n**Current behavior:**\nThe Engine has one request handler class, `SimilarHandler`, in the similarity handler module. Its `do_GET` and `do_POST` run each request under the statement deadline and call `_dispatch_get` and `_dispatch_post`, which are `if` chains over the URL path:\n- **POST:**\n  - every `/internal/*` path must first pass `_bridge_authorized`: 503 when `ENGINE_BRIDGE_TOKEN` is unset, 401 on a missing or wrong `X-Bridge-Token`, compared with `hmac.compare_digest`;\n  - then `SIMILAR_POST_ROUTES` (`/recommendations`, `/videos/similar`);\n  - then the internal video resolve, video metadata, dislike centroids, translate and translate enqueue routes;\n  - then events ingest, which answers 501 unless the ingest mode is `bridge`;\n  - anything else gets 404 `{\"error\": \"Not found\"}`.\n- **GET:**\n  - every `/api/` path must first pass the rate limiter (429);\n  - `/api/health` and `/api/channels` are answered inline;\n  - then search, `/api/video`, `/api/video/refresh` and `/videos/{id}/similar`;\n  - anything else gets 404.\n\nThe module docstring lists every route under the title \"Similarity HTTP handler\". Adding any route means editing the similarity module's imports, its docstring and one of the chains.\n\n**Desired behavior:**\n- **The router module.** One router module in the Engine's API package owns:\n  - the GET and POST route tables, mapping each exact path, plus the `/videos/{id}/similar` pattern, to the function or handler method that serves it;\n  - the `/internal/*` bridge-auth gate;\n  - the `/api/` rate-limit gate on GET;\n  - the 404 fallback;\n  - the events-ingest mode check.\n- **Adding a route** means one table entry and one import in the router, and no edit to the similarity module.\n- **`SimilarHandler` keeps** the request lifecycle (`_run_request`, the statement deadline, the 503 on an interrupted statement), client-address resolution, access logging, `_rate_limit_check` and every similarity, feed and search method. Its `do_GET` and `do_POST` hand each request to the router.\n- **Inline routes.** `/api/health` and `/api/channels` move out of the dispatch method into their own handler functions, beside the router or in a fitting handler module, so the router stays a table.\n- **Behaviour is identical for every request:**\n  - every route, method, status code, body and header;\n  - the gate order: bridge auth before any internal route, the rate limit before any `/api/` GET;\n  - the 401 and 503 bodies and their log lines;\n  - the 429;\n  - the 501 for ingest outside bridge mode;\n  - both 404s.\n- **The route list** moves from the similarity module's docstring to the router module. The Engine server README route list is unchanged, or corrected where it was already wrong.\n\n**Key interfaces:**\n- The router exposes one GET and one POST entry point that take the handler. Its tables map a path to a callable taking `(handler, server)` or the handler alone. The agent chooses which, and uses it consistently.\n- `SimilarHandler` keeps its name and module, and the server still constructs it as today.\n- Bridge auth becomes a router function using the same token source (the server's `bridge_token`, else `ENGINE_BRIDGE_TOKEN`) and the same constant-time compare.\n\n**Acceptance criteria:**\n- [ ] The similarity handler module no longer contains a path-dispatch chain, the bridge-auth check, the `/api/health` or `/api/channels` handling, or imports of the internal route handlers.\n- [ ] One router module holds both route tables, the bridge-auth gate, the `/api/` rate-limit gate, the ingest-mode check and the 404 fallback.\n- [ ] Every POST `/internal/*` path without a valid `X-Bridge-Token` answers 401 before its handler runs, and with the token unset answers 503. A test covers one internal route of each kind, plus an unknown `/internal/` path. The unknown path also gets 401 without a token, as today.\n- [ ] Every route listed in the Engine server README answers as before. The existing Engine, video, similar, translate and ingest tests pass, and only tests that called the removed dispatch or auth methods directly are rewritten.\n- [ ] Adding a fake route in a test needs only a router table entry, and no edit to the similarity module, to be served.\n- [ ] The route list lives in the router module's docstring, and the similarity module's docstring describes only similarity.\n\n**Out of scope:**\n- Renaming `SimilarHandler` or `SimilarServer`, or moving the similarity, feed and search methods out of the class.\n- API versioning (F2-M3), new routes, or any change to rate limiting, bridge auth or error bodies.\n- Changing `_get_client_ip`, access logging or the statement deadline.\n- The fetch adapter (issue 53) and the translate route internals (issues 54 and 55).",
  "request_source": "read from docs/project/issues/58-engine-routing-out-of-similar-handler.md",
  "slug": "58-engine-routing-out-of-similar",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Engine routing moves into router.py",
      "checkpoint": "Seam: real HTTP requests into a real `SimilarServer` running the real `SimilarHandler` on an ephemeral port. The server runs in an Engine child process (`ENGINE_PY -c CHILD`, cwd `engine/server/api`), which imports `server` first so the `sys.path` setup runs. The server is built with `dict.fromkeys(signature params[3:])`. This copies the existing child harness in `tests/active/test_video.py`, the precedent for this seam. The only shim is a replaced router table entry, never a patched module function, because dispatch looks up the table per request. `tests/tmp/test_router_bridge_auth.py` (clause_1) replaces the `POST_ROUTES` entries for `/internal/videos/resolve`, `/internal/translate` and `/internal/events/ingest` with recording stubs. It then asserts, for those three paths plus `/internal/no-such-route`: 401 `{\"error\": \"Unauthorized\"}` with no token; 401 again with a wrong token; zero stub calls after both; 503 `{\"error\": \"Bridge token is not configured on the Engine\"}` after `srv.bridge_token = \"\"`, with no new stub calls. A valid-token control reaches each stub exactly once and gets 404 on the unknown path. Without that control, the zero counts would prove nothing. Beyond the clause, the same test asserts the ingest adapter's 501 body with `mode: None` and the ungated plain 404 for GET `/internal/videos/resolve`. `tests/tmp/test_router_fake_route.py` (clause_2) asserts that GET `/fake` answers 404 `{\"error\": \"Not found\"}` before `router.GET_ROUTES[\"/fake\"]` is set. After it is set, GET `/fake?x=1` answers 200 with the stub's body carrying the raw path, which proves the request reached the stub through the real handler. Existing suites cover everything else unchanged: test_video, test_internal_translate 1044-1074, test_server `/api/channels`, the conftest `/api/health` probe, test_similar and test_recommendations_likes_limit.",
      "intent": "Every Engine GET and POST that `SimilarHandler` receives is answered by `engine/server/api/router.py`, through its `/internal/` bridge gate, its `/api/` rate-limit gate and its `GET_ROUTES`/`POST_ROUTES` tables. `SimilarHandler`'s own `_dispatch_*` and `_bridge_authorized` methods no longer exist.",
      "clauses": [
        {
          "id": "C1",
          "text": "Every POST to an `/internal/*` path, unknown paths included, gets the router's bridge-gate answer before its `POST_ROUTES` entry runs: 401 when the token is missing or wrong, 503 when the Engine has none set."
        },
        {
          "id": "C2",
          "text": "A route added as one `GET_ROUTES` entry, with no edit to `handlers/similar.py`, is served through the real `SimilarHandler`."
        }
      ],
      "files": [
        "engine/server/api/router.py (NEW)",
        "engine/server/api/http_utils.py (EDITED)",
        "engine/server/api/handlers/similar.py (EDITED)",
        "tests/tmp/test_router_bridge_auth.py (NEW)",
        "tests/tmp/test_router_fake_route.py (NEW)"
      ],
      "done": true,
      "outcome": "### `engine/server/api/router.py` (new)\n- The module docstring is now the full Engine route list. Each entry gives the method and gate, and it adds the two routes the old similar.py docstring left out: `/internal/dislikes/centroids` and `/api/v1/search/videos`.\n- `SIMILAR_POST_ROUTES` moved here from similar.py. The two similar POST entries in `POST_ROUTES` are built from it with `dict.fromkeys`.\n- `GET_ROUTES` and `POST_ROUTES` are plain module dicts mapping an exact path to `callable(handler, server)`. They are looked up on every request.\n  - The three client-read handlers and the two translate handlers go into the table as they are.\n  - Thin adapters cover the rest: `_similar_post`, `_search`, `_video`, `_video_refresh`, and `_events_ingest`, which now holds the 501 ingest-mode check with its `mode` field.\n- `handle_health` and `handle_channels` are the old inline `/api/health` and `/api/channels` blocks, moved over unchanged.\n- `_extract_video_id_from_similar_path` moved here unchanged.\n- `bridge_authorized(handler)` is the old `_bridge_authorized` with `self` replaced by `handler`. The token fallback, the stripped `X-Bridge-Token`, `hmac.compare_digest`, the 503/401 bodies and the root-logger `[bridge.auth]` lines are all the same.\n- `route_post(handler)`: the `/internal/` bridge gate, then a `POST_ROUTES` lookup, then 404.\n- `route_get(handler)`: the `/api/` rate-limit gate (429), then a `GET_ROUTES` lookup, then the `/videos/{id}/similar` pattern, then 404. The pattern keeps its own limiter, then `setdefault(\"id\")`, then `_handle_similar`.\n- The one hard-coded pattern route carries a `rat-tail:` comment naming its ceiling and upgrade path.\n- The router never imports `handlers.similar`, so there is no import cycle.\n\n### `engine/server/api/http_utils.py`\n- Added `parse_int` and `parse_non_negative_int`, moved byte-for-byte from similar.py's `_parse_int` and `_parse_non_negative_int`. The router's channels code and similar.py's search and similar code share them.\n\n### `engine/server/api/handlers/similar.py`\n- **Docstring:** the module docstring now describes only similarity (recommendations, similar, feeds, search) and points to `api/router.py` for the route list.\n- **Imports removed:** `hmac`, `fetch_channels`, `BRIDGE_TOKEN_HEADER`, `ENGINE_BRIDGE_TOKEN`, and the `handlers.internal_events`, `handlers.internal_client_reads`, `handlers.internal_translate` and `handlers.video` imports.\n- **Imports added:** `from router import SIMILAR_POST_ROUTES, route_get, route_post`, plus `parse_int` and `parse_non_negative_int` from `http_utils`. `_recommendations_likes_payload_error` reads the imported `SIMILAR_POST_ROUTES`.\n- **Methods removed:** `_bridge_authorized`, `_dispatch_post` and `_dispatch_get`. `_serve_post` and `_serve_get` keep the statement-deadline / interrupted-503 wrapper and now call `route_post(self)` and `route_get(self)` inside it. The `do_GET`/`do_POST` and `_serve_*` docstrings were reworded to say they hand the request to the router.\n- **Renames:** four call sites renamed to the public names (`_handle_search` limit and page, `_handle_similar` limit and seed).\n- **Helpers removed:** `_parse_int`, `_parse_non_negative_int` and `_extract_video_id_from_similar_path`. `_parse_bool`, `_parse_include_nsfw` and `FEED_MODES` stay.\n\n### `tests/tmp/test_router_bridge_auth.py`, `tests/tmp/test_router_fake_route.py`\n- Not created. The gated checkpoint `tests/tmp/test_58_engine_routing_out_of_similar_phase1.py` already holds both planned tests (bridge gate and fake route), so writing them again would only duplicate it.\n\n### Verification\n- I did not run the checkpoint.\n- A throwaway import probe under the Engine interpreter showed:\n  - `server`, `handlers.similar` and `router` import with no cycle;\n  - both tables hold the expected paths;\n  - `similar.SIMILAR_POST_ROUTES is router.SIMILAR_POST_ROUTES`;\n  - `_dispatch_get` is gone;\n  - `parse_int(\" 5\") == 5` and `parse_non_negative_int(\"-1\") is None`.",
      "beyond": "tests/tmp/probe_router_import.py \u2014 a throwaway import probe I wrote and ran through ValidateTests. I have no tool that deletes files, so it is still there: please delete it. It is named `probe_*`, not `test_*`, so the default pytest collection should skip it."
    }
  ],
  "digests": {
    "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py": "22eb74b9c4a87c36394a42709a5535fb5928ea357af2efa7b2e704c257cd0e78"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/58",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261004T094350-b497-dev-flow"
  ],
  "snapshot": {
    "tree": "4ad7ae9b9c41fab0b9d593d9fd49de130830be31",
    "at": "2026-10-04T09:44:00-04:00"
  },
  "plan": "docs/project/plans/01-58-engine-routing-out-of-similar.md",
  "record": "docs/project/plans/01-58-engine-routing-out-of-similar.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nThe Engine has one request handler class, `SimilarHandler` (`engine/server/api/handlers/similar.py`, 1275 lines), and it is built by `engine/server/api/server.py:123,469`. Route dispatch for every Engine path, and the `/internal/*` bridge-auth gate, live in that similarity module today. So every new route edits the similarity file: its imports, its docstring route list, and one of its `if` chains. The roadmap plans more routes (F1-M3 public REST API, F5-M3, F1-M4), a change to every unversioned route (F2-M3 API versioning), and changes at the gates (F7-M7 and F10-M7, rate limiting and service keys). This build moves routing into a router module of its own so those changes land in one routing place. It is a pure code move: no request may behave differently.\n\n### Current state (verified against the tree)\n\n- `SimilarHandler.do_POST` \u2192 `_run_request(_serve_post)` \u2192 `with self._statement_deadline(): self._dispatch_post()`. A `sqlite3.OperationalError` for which `is_interrupted_error` is true answers `_respond_interrupted()` (503 `{\"error\": \"Query time limit exceeded\"}` plus a `[statement.timeout]` warning). Any other error is re-raised. `do_GET` \u2192 `_serve_get` \u2192 `_dispatch_get` follows the same pattern.\n- `_bridge_authorized` (`similar.py:417-440`):\n  - The configured token is `getattr(self.server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)`. It falls back only when the attribute is absent, so an empty `server.bridge_token` counts as unset.\n  - When the token is falsy: `logging.error(\"[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting %s\", self.path)`, then 503 `{\"error\": \"Bridge token is not configured on the Engine\"}`.\n  - Otherwise the presented token is `self.headers.get(BRIDGE_TOKEN_HEADER, \"\").strip()`. When it is empty or fails `hmac.compare_digest(presented, configured)`: `logging.warning(\"[bridge.auth] rejected %s from ip=%s\", self.path, self._get_client_ip())`, then 401 `{\"error\": \"Unauthorized\"}`.\n  - `self.path` is the raw request path, including any query string.\n- `_dispatch_post` (`similar.py:442-478`) uses `url = urlparse(self.path)` and matches exactly on `url.path`, in this order:\n  1. When `url.path.startswith(\"/internal/\")` and bridge auth fails, return. This covers unknown `/internal/` paths too, so they get 401 or 503, never 404.\n  2. A path in `SIMILAR_POST_ROUTES` (`/recommendations`, `/videos/similar`) \u2192 `self._handle_similar_request(method=\"POST\")`, which runs its own rate-limit check (429) itself.\n  3. `/internal/videos/resolve` \u2192 `handle_internal_video_resolve(self, self.server)`.\n  4. `/internal/videos/metadata` \u2192 `handle_internal_videos_metadata(self, self.server)`.\n  5. `/internal/dislikes/centroids` \u2192 `handle_internal_dislike_centroids(self, self.server)`.\n  6. `/internal/translate` \u2192 `handle_internal_translate(self, self.server)`.\n  7. `/internal/translate/enqueue` \u2192 `handle_internal_translate_enqueue(self, self.server)`.\n  8. `/internal/events/ingest`: when `getattr(self.server, \"engine_ingest_mode\", \"bridge\") != \"bridge\"`, answer 501 `{\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": <that mode>}`. Otherwise call `handle_internal_events_ingest(self, self.server)`.\n  9. Anything else \u2192 404 `{\"error\": \"Not found\"}`.\n- `_dispatch_get` (`similar.py:494-562`), in this order:\n  1. When `url.path.startswith(\"/api/\")` and `self._rate_limit_check(url.path)` fails \u2192 429 `{\"error\": \"Rate limit exceeded\"}`. This also applies to unknown `/api/` paths, before their 404.\n  2. `/api/health` \u2192 200 `{\"ok\": True, \"total\": server.embeddings_count, \"embeddingDim\": server.embeddings_dim}`, answered inline.\n  3. `params = parse_qs(url.query)`. `/api/channels` is answered inline:\n     - `limit = _parse_int(limit)`; when it is `<= 0` it becomes 100, then it is capped at 500;\n     - `offset = _parse_int(offset)`;\n     - `max_videos = _parse_non_negative_int(maxVideos)`;\n     - under `server.db_lock`, `fetch_channels(server.db, limit, offset, query=q or \"\", instance=instance or \"\", min_followers=_parse_int(minFollowers), min_videos=_parse_int(minVideos), max_videos, sort=sort or \"followers\", direction=dir or \"desc\")`;\n     - 200 `{\"generatedAt\": now_ms(), \"total\": total, \"rows\": rows}`.\n  4. `/api/v1/search/videos` \u2192 `self._handle_search(params)`.\n  5. `/api/video` \u2192 `handle_video_request(self, self.server, params)`.\n  6. `/api/video/refresh` \u2192 `handle_video_refresh_request(self, self.server, params)`.\n  7. `/videos/{id}/similar`, matched by `_extract_video_id_from_similar_path(url.path)` (exactly three segments, `videos`/<non-blank id>/`similar`): first its own `self._rate_limit_check(url.path)` (429 on failure, even though the path is not under `/api/`), then `params.setdefault(\"id\", [video_path_id])`, then `self._handle_similar(params)`.\n  8. Anything else \u2192 404 `{\"error\": \"Not found\"}`.\n- A GET to an `/internal/` path gets a plain 404, with no bridge auth. A POST to a GET-only path, or the other way round, gets 404. Routing ignores the query string, and a trailing slash does not match.\n- The module docstring (`similar.py:1-20`) is titled \"Similarity HTTP handler\" and lists the routes. It already omits `/internal/dislikes/centroids` and `/api/v1/search/videos`.\n- `SIMILAR_POST_ROUTES` is also read by `_recommendations_likes_payload_error` inside similar.py.\n- `_parse_int`, `_parse_non_negative_int` and `_extract_video_id_from_similar_path` are module-level helpers in similar.py. `_parse_int` and `_parse_non_negative_int` are also used by similarity and search code that stays.\n\n### Desired behaviour\n\n- **One router module** in the Engine's API package (`engine/server/api/`, beside or under `handlers/`; the design step picks the place) owns:\n  - the GET route table and the POST route table, each mapping an exact path to the callable that serves it, plus the GET `/videos/{id}/similar` pattern;\n  - the `/internal/*` bridge-auth gate on POST;\n  - the `/api/` rate-limit gate on GET;\n  - the events-ingest mode check (the 501);\n  - the 404 fallback.\n- **Router entry points.** The router exposes one GET entry point and one POST entry point, each taking the handler. Table values are callables with one consistent signature: either `(handler, server)` or the handler alone, chosen by the design step and used throughout. Handlers whose native signature differs (the video handlers take `params`, the similar methods take `method`/`params`) are wrapped by thin adapters so the tables stay uniform.\n- **Bridge auth** becomes a router function. It keeps:\n  - the same token source (`getattr(server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)`, the same fallback semantics);\n  - the same header (`BRIDGE_TOKEN_HEADER`, stripped);\n  - the same `hmac.compare_digest` compare;\n  - the same 503 and 401 bodies;\n  - the same `[bridge.auth]` log messages, levels and arguments: `self.path` and `handler._get_client_ip()`.\n- **Inline routes.** `/api/health` and `/api/channels` become handler functions of their own, beside the router or in a fitting handler module, so the router is a table. Their responses and parameter parsing stay byte-for-byte the same. They need the `_parse_int`/`_parse_non_negative_int` semantics, which similar.py's similarity code also uses; how they share them is the design step's choice.\n- **The `/videos/{id}/similar` rate-limit check** and the `params.setdefault(\"id\", ...)` stay in force, in the same order, before `_handle_similar` runs.\n- **`SimilarHandler` keeps:**\n  - its name, module and construction by `server.py`;\n  - `_run_request`, `_statement_deadline`, `_respond_interrupted`, `_serve_get`/`_serve_post` (the statement deadline and its 503 still wrap all routing, including the gates);\n  - `_get_client_ip`, `_get_full_url`, `log_request`, `log_message` and `do_OPTIONS`;\n  - `_rate_limit_check` and every similarity, feed and search method (`_handle_similar_request`, `_handle_similar`, `_handle_search`, and the rest).\n  \n  Its `do_GET`/`do_POST` path hands each request to the router's GET/POST entry point, in place of `_dispatch_get`/`_dispatch_post`.\n- **Adding a route** means one table entry, plus one import in the router, and no edit to similar.py.\n- **Docstrings.** The router module's docstring holds the full route list, including the two routes the old docstring omitted (`/internal/dislikes/centroids`, `/api/v1/search/videos`), and `/api/health` and `/api/channels`. similar.py's docstring describes only similarity: recommendations, similar, feeds and search.\n- **README.** The `engine/server/README.md` route list is left unchanged (operator decision). Its other references to `SimilarHandler._run_request` and `_parse_include_nsfw` in `api/handlers/similar.py` stay true and are not edited.\n\n### Behaviour that must be identical\n\nEvery request gets the same status, body, headers and log lines as today:\n- every route, on both methods;\n- the gate order (bridge auth before any POST `/internal/` route, including unknown ones; the `/api/` rate limit before any `/api/` GET, including unknown ones);\n- both 404s;\n- the 401 and 503 bridge bodies and their `[bridge.auth]` log lines;\n- the 429s, including the extra one on GET `/videos/{id}/similar`;\n- the 501 for ingest outside bridge mode, with its `mode` field;\n- the plain 404 for GET `/internal/*`;\n- the statement-timeout 503;\n- the `[request.start]`/`[request.end]` records and request id.\n\n### Acceptance criteria\n\n- similar.py no longer contains:\n  - a path-dispatch chain (`_dispatch_get`/`_dispatch_post` or an equivalent);\n  - the bridge-auth check or the `hmac`/`ENGINE_BRIDGE_TOKEN`/`BRIDGE_TOKEN_HEADER` use behind it;\n  - the `/api/health` or `/api/channels` handling;\n  - imports of `handlers.internal_events`, `handlers.internal_client_reads`, `handlers.internal_translate` or `handlers.video`.\n- One router module holds both route tables, the bridge-auth gate, the `/api/` rate-limit gate, the ingest-mode check and the 404 fallback.\n- **Bridge-auth test:**\n  - Every POST `/internal/*` path without a valid `X-Bridge-Token` (missing, or wrong) answers 401 `{\"error\": \"Unauthorized\"}` before its handler runs, and answers 503 `{\"error\": \"Bridge token is not configured on the Engine\"}` when the token is unset.\n  - A test covers one internal route of each kind (client reads: one of resolve, metadata or dislike centroids; translate: one of translate or enqueue; events ingest) plus an unknown `/internal/` path, which also gets 401 without a token.\n  - The test shows the handler did not run.\n- Every Engine route answers as before. That covers every route the README lists, plus `/api/health`, `/api/channels` and `/api/v1/search/videos`, which the README's list omits.\n- The existing Engine, video, similar, translate and ingest tests pass: `tests/active/test_similar.py`, `test_video.py`, `test_internal_translate.py`, `test_internal_events.py`, `test_internal_client_reads.py`, `test_random_cache.py`, `test_server.py` and `engine/server/api/tests/`. Only tests that called removed dispatch or auth methods directly are rewritten; no current test does.\n- A test adds a fake route through a router table entry alone, with no edit to similar.py, and it is served through the real `SimilarHandler`.\n- The route list lives in the router module's docstring, and similar.py's docstring describes only similarity.\n\n### Constraints\n\n- Smallest move that answers the issue. No new dependency (stdlib only). No router class hierarchy or registration framework: plain module-level dicts and functions. No change to `SimilarServer`.\n- Code moves without behaviour change. New code follows the style of the file it lands in: module docstring, one-line docstrings, `respond_json(handler, status, body)` and `getattr(server, ..., default)` idioms.\n- **Test environment.** pytest's own interpreter has no numpy, so it cannot import `handlers.similar` or `server.py`. Engine-level tests run in a child process under `ENGINE_PY` (from `tests/active/conftest.py`), with `sys.path` set to the Engine `api` paths, as `test_video.py`, `test_similar.py` and `test_internal_events.py` do. The new bridge-auth and fake-route tests follow that pattern, or exercise a real `SimilarServer` on an ephemeral port.\n- Test trees: active tests live in `tests/active`, the working tree for in-build tests is `tests/tmp`, finished feature tests are archived under `tests/archive`, plans go in `docs/project/plans`, and the project root is `/home/enduser/code/PeerTube-browser/.worktrees/58`.\n\n### Baseline suite state\n\nThe pre-build baseline run exited with code 0 (`variant: false`): the suite is green before the build. Any red test after the build is caused by the build.\n\n### Out of scope\n\n- Renaming `SimilarHandler` or `SimilarServer`, or moving similarity, feed or search methods out of the class.\n- API versioning (F2-M3), new routes, or any change to rate limiting, bridge auth semantics or error bodies.\n- Changing `_get_client_ip`, access logging, request-id handling or the statement deadline.\n- The fetch adapter (issue 53) and translate route internals (issues 54, 55).\n- Editing `engine/server/README.md`.\n</requirements>\n\n<conflicts>\nThe brief's criterion \"every route listed in the Engine server README answers as before\" doesn't match the README itself: its route list (`engine/server/README.md:7-27`) leaves out `/api/health`, `/api/channels` and `/api/v1/search/videos`, all of which `_dispatch_get` serves. The operator chose to leave the README unchanged, so the criterion is widened to every route the Engine serves.\nThe brief says to move the route list out of similar.py's docstring, but that docstring (`similar.py:1-20`) already leaves out `/internal/dislikes/centroids` and `/api/v1/search/videos`, which the dispatch serves. The router docstring has to list them, so it won't be a verbatim move.\nThe brief says the router owns \"the `/api/` rate-limit gate on GET\", but the tree also rate-limits GET `/videos/{id}/similar` in dispatch (`similar.py:555`), on a path outside `/api/`. The brief doesn't mention this second gate, and keeping behaviour identical means the router must keep it.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nAdd one new module, `engine/server/api/router.py`. It sits beside `server.py` and `http_utils.py` and holds routing for the whole Engine. It imports from `handlers/`, and `handlers/similar.py` imports its two entry points from it. The router never imports `handlers.similar`, so the dependency runs one way and there is no import cycle. The router also never needs the class, because every similarity call goes through the `handler` object it is given (`handler._handle_similar_request(...)`, `handler._handle_similar(...)`, `handler._handle_search(...)`, `handler._rate_limit_check(...)`).\n\n**What the router holds**\n\n- **Module docstring.** The full route list: every route the old docstring named, plus `/internal/dislikes/centroids` and `/api/v1/search/videos`, with `/api/health` and `/api/channels` kept. Each route is marked with its method and whether a gate covers it.\n- **Two plain dicts, `GET_ROUTES` and `POST_ROUTES`.** Each maps an exact path to a callable with the signature `(handler, server)`. I chose `(handler, server)` over the handler alone because five of the nine existing callees already have it: the three client-read handlers and the two translate handlers. Those go into the table as they are, with no adapter.\n- **`SIMILAR_POST_ROUTES`, moved here from similar.py.** The POST table builds its `/recommendations` and `/videos/similar` entries from it. similar.py imports it back for `_recommendations_likes_payload_error`, so the router stays the one owner of path strings and the router-to-similar import direction still holds.\n- **Thin named adapters, each with a one-line docstring.** Named functions match the file style; I did not use lambdas.\n  - The similar POST adapter calls `handler._handle_similar_request(method=\"POST\")`.\n  - The search, video and video-refresh adapters each read `parse_qs(urlparse(handler.path).query)` and call `handler._handle_search(params)`, `handle_video_request(handler, server, params)` and `handle_video_refresh_request(handler, server, params)`.\n  - The events-ingest adapter is where the 501 lives. It checks `getattr(server, \"engine_ingest_mode\", \"bridge\")` with the same body and `mode` field as today, and only then calls `handle_internal_events_ingest`.\n- **Two handler functions, `handle_health` and `handle_channels`, taking `(handler, server)`.** Their bodies are the old inline blocks moved over unchanged: the same parsing, the same clamp of `limit` to 100 when it is `<= 0` and to 500 at most, `fetch_channels` under `server.db_lock`, and the same response bodies. `/api/channels` re-parses the query from `handler.path`, which gives the same result the old shared `params` did.\n- **`_extract_video_id_from_similar_path`, moved here unchanged.** Only dispatch uses it.\n- **`bridge_authorized(handler)`.** This is `_bridge_authorized` moved over with only `self` changed to `handler` / `handler.server`:\n  - the same `getattr(server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)` fallback;\n  - the same stripped `BRIDGE_TOKEN_HEADER` and `hmac.compare_digest`;\n  - the same 503 and 401 bodies;\n  - the same `logging.error` / `logging.warning` calls on the root logger, with `handler.path` and `handler._get_client_ip()`.\n\n  I checked `logging_profiles.py`: neither the text nor the JSON formatter emits module, function or line, so moving the calls to another module leaves every log line byte-identical.\n- **`route_post(handler)`:**\n  1. Parse `handler.path`.\n  2. When the path starts with `/internal/`, run `bridge_authorized` and return if it fails. This covers unknown `/internal/` paths too, so they still get 401 or 503.\n  3. Look the exact path up in `POST_ROUTES` and call the entry with `(handler, handler.server)`.\n  4. Otherwise answer 404 `{\"error\": \"Not found\"}`.\n- **`route_get(handler)`:**\n  1. Parse the path.\n  2. Apply the `/api/` prefix rate-limit gate through `handler._rate_limit_check(path)`, answering 429 on failure, including for unknown `/api/` paths.\n  3. Exact lookup in `GET_ROUTES`.\n  4. Otherwise try the `/videos/{id}/similar` pattern: its own rate-limit check (429), then `params.setdefault(\"id\", [video_id])`, then `handler._handle_similar(params)`, in that order.\n  5. Otherwise 404.\n\n  GET `/internal/*` has no table entry and no gate, so it still gets the plain 404. Wrong-method requests miss their table and get 404. Routing uses `urlparse(...).path`, so the query string is still ignored, and a trailing slash still fails the exact match.\n\n**Shared integer parsing.** `_parse_int` and `_parse_non_negative_int` move unchanged to `http_utils.py` as public `parse_int` and `parse_non_negative_int`. The router imports them from there, and similar.py imports them and renames its handful of call sites (search, similar, channels code that stays). One definition serves both modules.\n\n**What changes in similar.py**\n\n- Removed:\n  - `_dispatch_get`, `_dispatch_post` and `_bridge_authorized`;\n  - the health and channels blocks;\n  - `_extract_video_id_from_similar_path` and the two parse helpers;\n  - the `hmac` import, `ENGINE_BRIDGE_TOKEN` and `BRIDGE_TOKEN_HEADER`;\n  - `fetch_channels`;\n  - the four `handlers.internal_*` / `handlers.video` imports.\n- `_serve_get` and `_serve_post` keep their deadline / interrupted-503 wrapper exactly as now and call `route_get(self)` and `route_post(self)` inside it. So the statement deadline still wraps the gates, and `_run_request` still owns the `[request.start]` / `[request.end]` records and the request id. Nothing else in the class changes.\n- The `do_GET` / `do_POST` docstrings are reworded to say \"hand the request to the router\".\n- The module docstring is rewritten to describe only recommendations, similar, feeds and search, and points to `router.py` for the route list.\n- `urlparse` and `parse_qs` stay, because `_handle_similar_request` still uses them. `now_ms` stays because feeds use it.\n\n### How each requirement is met\n\n- **One router module** holds both tables, the `/videos/{id}/similar` pattern, the bridge gate, the `/api/` rate-limit gate, the ingest-mode 501 and both 404s.\n- **Entry points.** `route_get(handler)` and `route_post(handler)`; every table value has the signature `(handler, server)`.\n- **Bridge auth** keeps its token source, header, compare, bodies and log calls exactly.\n- **Inline routes** become `handle_health` and `handle_channels` with identical behaviour.\n- **The `/videos/{id}/similar` rate-limit check and `setdefault`** run in the same order.\n- **`SimilarHandler`** keeps its name, module, construction by `server.py`, wrapper, logging, OPTIONS, `_rate_limit_check` and every similarity, feed and search method. `SimilarServer` and `server.py` are not touched.\n- **Adding a route** means one dict entry plus one import in `router.py`.\n- **README** is not edited. Its references to `SimilarHandler._run_request` and `_parse_include_nsfw` stay true, since neither moves.\n\n**Tests.** Both new tests go in `tests/tmp`. Each runs a child under `ENGINE_PY` with the Engine `api` paths on `sys.path`, starting a real `SimilarServer` with the real `SimilarHandler` on an ephemeral port, the way `test_video.py` does.\n\n- **Bridge-auth test.** It swaps recording stubs into `POST_ROUTES` for `/internal/videos/resolve`, `/internal/translate` and `/internal/events/ingest`, then sends POSTs to those three plus an unknown `/internal/` path.\n  - With no token and with a wrong token: 401 `{\"error\": \"Unauthorized\"}` for all four.\n  - With `srv.bridge_token = \"\"`: 503 with the configured-token body.\n  - Each stub records zero calls.\n  - A control request with the valid token shows the stub does get called. That proves the stub is wired in, so the zero counts actually mean something.\n- **Fake-route test.** It adds `GET_ROUTES[\"/fake\"]` with a function that answers through `respond_json`, then checks the response arrives through the real handler.\n\nThe existing suites listed in the acceptance criteria run unchanged. Nothing calls the removed methods directly; I checked the tree, and the only `similar.` uses in tests are `FEED_MODES`, `DEFAULT_CLIENT_LIKES_MAX`, `_parse_client_likes`, `_handle_similar` and `_handle_similar_request`, which all stay.\n\n### Alternatives considered\n\n- **Keep the routing methods on a mixin or base class that `SimilarHandler` inherits.** Rejected: the constraints forbid a class hierarchy, and a mixin still couples routing to the handler class.\n- **Use a decorator or registration framework, or a router class.** Rejected by the constraints. A plain dict already gives a one-line route addition.\n- **Have table callables take the handler alone.** Rejected: all five client-read and translate handlers would then need adapters, where with `(handler, server)` none of them do.\n- **Import the parse helpers from similar.py into the router.** Rejected: similar.py imports the router, so this would create a cycle.\n- **Duplicate the parse helpers in the router.** Rejected: two copies of the clamping rules would drift apart.\n- **Put the router in `handlers/router.py`.** Workable, but `handlers/` holds endpoint handlers. Dispatch is cross-cutting, like `http_utils` and `request_context`, so it sits beside them.\n- **Put health and channels in a new `handlers/catalog.py`.** Rejected for now as one more file holding two small functions. Living beside the router is allowed by the requirements, and they can move out when they grow.\n- **Run the ingest-mode check as a path-keyed gate in `route_post`.** Rejected: it applies to one route, so it belongs in that route's adapter, which still sits inside the router.\n- **Leave `SIMILAR_POST_ROUTES` in similar.py and write the two paths out again in the router.** Rejected: that is a duplicate source of path truth.\n\n### Gotchas and risks\n\n- **Import cycle.** `router.py` must never import `handlers.similar`, at module level or anywhere else. A future contributor who wants a similarity helper in the router would bring the cycle back.\n- **Table entries hold function references.** Patching `handlers.internal_translate.handle_internal_translate` after import does not change what gets dispatched. Tests must patch the table entry instead, and the bridge-auth test does that. Today's tests patch inner functions (`video.fetch_instance_json`, `fetch_bounded`), and those are unaffected.\n- **The tables must stay plain mutable dicts, looked up per request.** If they are frozen or copied into a closure, the fake-route test breaks.\n- **Re-parsing the query in adapters.** `parse_qs` with default arguments does not raise, so moving the parse from before the channels block into each adapter cannot change an outcome. The cost is negligible.\n- **Order inside the tables.** Order no longer matters, because exact paths cannot overlap and the one pattern route is tried only after an exact miss, as it is today.\n- **Docstring drift.** `engine/server/README.md` keeps its incomplete route list by operator decision. `router.py` becomes the route list that is correct.\n\n### Tradeoffs the operator is accepting\n\n- **Deliberate simplification: one hard-coded pattern route.** `/videos/{id}/similar` stays special-cased in `route_get` rather than going through a general pattern table. That limit is reached when a second parameterised path appears. The upgrade then is a small ordered list of `(matcher, callable)` pairs tried after the exact lookup, which fits F2-M3 versioning.\n- **Gates are prefix checks hard-coded in the entry points** (`/internal/` on POST, `/api/` on GET), not per-route flags. That matches today exactly. F7-M7 and F10-M7 will change them in that one place.\n- **`/api/health` and `/api/channels` live in `router.py`.** The router file therefore imports `fetch_channels` and `now_ms` and is not strictly a table.\n- **Renamed helpers.** `_parse_int` and `_parse_non_negative_int` become public `parse_int` and `parse_non_negative_int` in `http_utils.py`, and similar.py's call sites are renamed. No test references the old names.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n<impacts>\n<impact path=\"engine/server/api/router.py\" element=\"new module (whole file): docstring route list, GET_ROUTES, POST_ROUTES, SIMILAR_POST_ROUTES, adapters, handle_health, handle_channels, _extract_video_id_from_similar_path, bridge_authorized, route_get, route_post\">\n**What changes.** A new top-level module in the api dir. No file named `router*` exists anywhere in the tree, and none exists in the Engine pixi site-packages, so the top-level name `router` does not collide. It is imported as `from router import ...`, the same way `http_utils` and `server_config` are, because the api dir is on `sys.path` as a root.\n\n**What it must import.**\n- From the standard library: `hmac`, `logging` and `from urllib.parse import parse_qs, urlparse`.\n- `from data.channels import fetch_channels` and `from data.time import now_ms`.\n- `from http_utils import respond_json, parse_int, parse_non_negative_int`.\n- `from server_config import BRIDGE_TOKEN_HEADER, ENGINE_BRIDGE_TOKEN`. Both are defined at `server_config.py:500-501`, and the token is read from env at import time.\n- `handle_internal_events_ingest` from `handlers.internal_events`, the three `handle_internal_*` client reads from `handlers.internal_client_reads`, `handle_internal_translate` and `handle_internal_translate_enqueue` from `handlers.internal_translate`, and `handle_video_request` and `handle_video_refresh_request` from `handlers.video`.\n\nNone of these modules imports `handlers.similar`, so there is no cycle; I checked their import blocks. `handlers.internal_translate` imports `handlers.video`, which is fine.\n\n**Behaviour that must be reproduced exactly** (from `similar.py:417-562`):\n- **POST.**\n  - The `/internal/` prefix gate runs before every lookup, unknown internal paths included.\n  - `SIMILAR_POST_ROUTES` \u2192 `_handle_similar_request(method=\"POST\")`.\n  - The five internal routes.\n  - Events ingest: the 501 body is `{\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": getattr(server, \"engine_ingest_mode\", \"bridge\")}`.\n  - Anything else: 404 `{\"error\": \"Not found\"}`.\n- **GET.**\n  - The `/api/` prefix gate gives 429 `{\"error\": \"Rate limit exceeded\"}` before the lookup, unknown `/api/` paths included.\n  - `/api/health` answers `{\"ok\": True, \"total\": server.embeddings_count, \"embeddingDim\": server.embeddings_dim}`.\n  - `/api/channels` keeps the clamp `<=0 \u2192 100`, then `min(\u2026, 500)`; `offset`, `maxVideos`, `minFollowers` and `minVideos` keep their parsing; `fetch_channels` keeps its keyword args under `server.db_lock`; the response is `{\"generatedAt\": now_ms(), \"total\", \"rows\"}`.\n  - Search, `/api/video` and `/api/video/refresh` each get `parse_qs(url.query)`.\n  - Then the `/videos/{id}/similar` pattern: a second `_rate_limit_check(url.path)`, then `params.setdefault(\"id\", [video_id])`, then `_handle_similar(params)`.\n  - Anything else: 404.\n\n**What depends on it.**\n- `handlers/similar.py`: `_serve_get` / `_serve_post`, and `_recommendations_likes_payload_error` through `SIMILAR_POST_ROUTES`.\n- The two new tests in `tests/tmp`, which mutate `POST_ROUTES` and `GET_ROUTES`.\n- Every Engine HTTP test indirectly, because every request now flows through it.\n\n**Regression risk: HIGH.** This is the whole request surface.\n- **Ordering slips.**\n  - The bridge gate must run before the `SIMILAR_POST_ROUTES` lookup. Today it cannot matter, since those paths are not `/internal/`, but the gate must still come first.\n  - The `/api/` rate-limit gate must run before the exact lookup, so a 429 still lands on unknown `/api/` paths.\n  - In the pattern branch, rate-limit then `setdefault` then `_handle_similar`.\n- **Accidental drift.** `respond_json` here must be the `http_utils` one. Tests that patch `similar.respond_json` (test_similar.py:259, test_recommendations_likes_limit.py:55/85/105) only go through `_handle_similar_request`, which stays in similar.py, so they still capture its output.\n- **Tables must be read per request.** `route_get`/`route_post` must do `GET_ROUTES.get(path)` at call time, not bind entries at import, or the fake-route and stub tests break.\n- **Logging.** The bridge-auth `logging.error`/`logging.warning` must stay on the root logger (`logging.error(...)`, not `logging.getLogger(__name__)`) with the same format strings. `logging_profiles._classify_event` derives the `event` field from the `[bridge.auth]` message prefix, and `EngineJsonFormatter.format` (`logging_profiles.py:236-272`) never emits module, funcName or lineno. I confirmed that: moving modules keeps output identical, but only if the message text is unchanged.\n- **Return values.** The `handle_*` functions return `bool`, and the router must ignore it, as the old chain did.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"module docstring (lines 1-20)\">\n**What changes.** The docstring is rewritten to describe only recommendations, similar, feeds and search, and to point to `router.py` for the route list. Today it lists 11 routes; `/internal/dislikes/centroids` and `/api/v1/search/videos` are already missing from it.\n\n**What depends on it.** Nothing at runtime. `tests/active/test_frontend_feed_params.py:41,120` parses this file with `ast` to read `FEED_MODES`, and a docstring change is harmless to that.\n\n**Regression risk: none.** The acceptance criterion \"similarity module's docstring describes only similarity\" is checked against this text.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"imports block (lines 21-103)\">\n**What changes.**\n- **Removed:**\n  - `import hmac` (line 22, only used at 434);\n  - `from data.channels import fetch_channels` (36, only used at 518);\n  - `BRIDGE_TOKEN_HEADER` and `ENGINE_BRIDGE_TOKEN` from the `server_config` import (52, 58, only used at 424/433);\n  - the four `handlers.internal_*` / `handlers.video` imports (96-103).\n- **Added:**\n  - `from router import SIMILAR_POST_ROUTES, route_get, route_post`;\n  - `parse_int, parse_non_negative_int` added to the existing `from http_utils import ...` line (80).\n- **Stays:**\n  - `urlparse` and `parse_qs` (still used at 643/647 in `_handle_similar_request`);\n  - `now_ms` (still used at 622 in search and 908 in feeds);\n  - `sqlite3`, and `Callable` (used by `_run_request`).\n\n**What depends on it.**\n- `server.py:123` imports `SimilarHandler` from this module, so importing `similar` now transitively imports `router` and the internal handlers. That set of modules is the same as today, only reached through router.\n- Every child-process test that does `from handlers import similar` / `from handlers.similar import SimilarHandler`: test_video.py:166/202, test_similar.py:196/238/362/471/730/979, test_server.py:1405, engine/server/api/tests/test_recommendations_likes_limit.py:19 and tests/archive/... Every one of them already has the api dir on `sys.path` (it is required to import the `handlers` package), so `router` resolves.\n\n**Regression risk: medium.**\n- **Import cycle.** If router ever imports `handlers.similar`, it breaks. A partial-module error appears when `similar` is the first importer, which is the normal case through server.py.\n- **Unused-import or missed-import NameError.** For example, leaving `_parse_int` references without renaming. Grep after the edit for `_parse_int`, `_parse_non_negative_int`, `fetch_channels`, `hmac` and `ENGINE_BRIDGE_TOKEN`.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SIMILAR_POST_ROUTES constant (line 106) and its reader _recommendations_likes_payload_error (lines 230-267)\">\n**What changes.** The constant definition moves to `router.py`. similar.py imports it back, and `_recommendations_likes_payload_error` (line 234: `if path not in SIMILAR_POST_ROUTES`) stays unchanged and reads the imported name.\n\n**What depends on it.**\n- The likes-payload 400 contract for both `/recommendations` and `/videos/similar` (archive issue 05; README line 46).\n- engine/server/api/tests/test_recommendations_likes_limit.py, which calls `_handle_similar_request` with path `/recommendations`.\n- test_similar.py:238-267.\n\n**Regression risk: low.** It must stay a set with exactly the two paths. If someone writes the paths out in the router instead, they can drift.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._bridge_authorized (lines 417-440)\">\n**What changes.** The method is removed and moves to `router.bridge_authorized(handler)`, with `self` \u2192 `handler` and `self.server` \u2192 `handler.server`.\n\n**What depends on it.** Only `_dispatch_post` (line 445). No test calls it directly; grep of tests for `_bridge_authorized` found nothing.\n\n**Regression risk: medium.** The behaviours to preserve:\n- `getattr(server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)`. `SimilarServer.__init__` always sets `self.bridge_token = ENGINE_BRIDGE_TOKEN` (server.py:290), so the fallback only matters for stand-in servers.\n- A falsy token gives 503 plus `logging.error`.\n- An empty or mismatched presented token (`.strip()`, `hmac.compare_digest`) gives 401 plus `logging.warning` with `handler._get_client_ip()`.\n\nCallers outside the Engine depend on these bodies:\n- client/backend/lib/engine_api_client.py:14,37-47 sends `X-Bridge-Token`;\n- test_internal_translate.py:1071,1074 asserts `(401, {\"error\": \"Unauthorized\"})`;\n- the DEPLOYMENT.md \u00a73b and line 315 triage text relies on the `bridge.auth` log event.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._dispatch_post (lines 442-478) and _serve_post (407-415), do_POST docstring (403-405)\">\n**What changes.**\n- `_dispatch_post` is removed.\n- `_serve_post` keeps its try / `with self._statement_deadline():` / `except sqlite3.OperationalError` \u2192 `is_interrupted_error` \u2192 `_respond_interrupted()` wrapper, and calls `route_post(self)` inside it.\n- The `do_POST` docstring is reworded to \"hand the request to the router\".\n\n**What depends on it.**\n- Every POST: recommendations, videos/similar and all `/internal/*`.\n- The statement deadline must still wrap the bridge gate and the handler, so that a `sqlite3.OperationalError` interrupt raised inside a router-called handler is still turned into a 503.\n- `internal_events.py:9` imports `is_interrupted_error` and handles some of these interrupts itself; that is unchanged.\n\n**Regression risk: medium.** If `route_post` is called outside the `with` block, or catches `OperationalError` itself, the 503 `Query time limit exceeded` path changes.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._dispatch_get (lines 494-562) and _serve_get (484-492), do_GET docstring (480-482)\">\n**What changes.**\n- `_dispatch_get` is removed: the inline health and channels blocks, the shared `params = parse_qs(url.query)` at 509, and the pattern branch.\n- `_serve_get` keeps its wrapper and calls `route_get(self)`.\n- The `do_GET` docstring is reworded.\n\n**What depends on it.** Every GET:\n- `/api/health`, used as the readiness probe in conftest.py:192, test_random_cache.py:307/819/861, test_internal_translate.py:1056 and test_similar.py:437;\n- `/api/channels`, which the Client proxies (client/backend/server.py:93,102) and which test_server.py:471-474 exercises through the Client;\n- `/api/v1/search/videos`, `/api/video` and `/api/video/refresh` (test_video.py);\n- `/videos/{id}/similar` (test_video.py:80 `SIMILAR`, PERSIST_CHILD).\n\n**Regression risk: medium-high.** These are the call sites every Engine readiness check depends on. A broken `handle_health` makes every Engine-child fixture time out. Unknown GET paths, including GET `/internal/*`, must still give a plain 404 with no gate; test_video.py:631/659 rely on 404 `{\"error\": \"Not found\"}` for unrouted paths.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"module helpers _parse_int (1167-1173), _parse_non_negative_int (1191-1199), _extract_video_id_from_similar_path (1267-1275), and their remaining call sites\">\n**What changes.**\n- `_parse_int` and `_parse_non_negative_int` are removed and move to http_utils as `parse_int` and `parse_non_negative_int`.\n- `_extract_video_id_from_similar_path` is removed and moves to router.\n\n**Remaining call sites to rename.** Grep confirms there are exactly four:\n- `_handle_search` at 584 (`limit`) and 588 (`page`);\n- `_handle_similar` at 1035 (`limit`, default `str(self.server.default_limit)`) and 1062 (`seed` \u2192 `parse_non_negative_int`).\n\nThe plan's wording \"search, similar, channels code that stays\" is slightly off: the channels call sites at 511/515/516/524/525 move to `router.handle_channels`, they do not stay.\n\n**What stays.** `_parse_bool` (1176) and `_parse_include_nsfw` (1183) are not touched. README:50 and ADR-0007:17 cite `_parse_include_nsfw` in `api/handlers/similar.py`.\n\n**What depends on it.**\n- Search limit/page clamping.\n- Similar limit and seed parsing: the README:49 `seed` semantics are \"negative or non-integer \u2192 random draw\". This is `parse_non_negative_int` returning None.\n\nNo test references the old names; I grepped `_parse_int` in tests and the only hit is client/backend/server.py's own unrelated `_parse_int` (line 1316), which is not affected.\n\n**Regression risk: low-medium.** A missed rename raises a NameError at request time, not at import time, because the names are resolved lazily inside methods. A test run that does not hit search or seeded similar would not catch it.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler methods that stay and are now called by the router: _rate_limit_check (632-639), _handle_similar_request (641-699), _handle_similar (1033+), _handle_search (564-630), _get_client_ip (323-338)\">\n**What changes.** Nothing in their bodies, apart from the parse renames noted in the helpers entry. They become an implicit interface the router calls by name on the handler object.\n\n**What depends on it.** The router's `handler._rate_limit_check(path)`, `handler._handle_similar_request(method=\"POST\")`, `handler._handle_similar(params)`, `handler._handle_search(params)` and `handler._get_client_ip()`. Several tests call these directly on stubs:\n- test_similar.py:207 builds a stub with `rate_limiter`;\n- test_similar.py:265/388/500/1005;\n- test_recommendations_likes_limit.py.\n\n**Regression risk: low now, latent later.** The private, underscore-prefixed methods become a cross-module contract. A future rename in similar.py breaks the router with an AttributeError at request time, not at import.\n</impact>\n<impact path=\"engine/server/api/http_utils.py\" element=\"new public parse_int and parse_non_negative_int\">\n**What changes.** The two functions are added, moved unchanged from similar.py:1167-1173 and 1191-1199, including their docstrings.\n- `parse_int`: `int(value or \"0\")`, then 0 on ValueError, then `parsed if parsed > 0 else 0`.\n- `parse_non_negative_int`: None for None, blank, invalid or negative input.\n\nThe module currently imports only `json`, `deque`, `datetime`, `BaseHTTPRequestHandler`, `threading` and `Any`, and needs no new import. Its docstring style is one line `\"\"\"Handle/Parse ...\"\"\"`.\n\n**What depends on it.**\n- Imported by `router.py` (channels) and `handlers/similar.py` (search, similar).\n- Already imported by `server.py:124` (`RateLimiter`), internal_client_reads.py:10, internal_events.py:12, internal_translate.py:26, video.py:21.\n- tests/config.json lists `engine/server/api/http_utils.py` in the `test_similar.py` and `test_internal_client_reads.py` / `test_internal_translate.py` groups.\n\n**Regression risk: low.** It is additive. The semantics must be copied byte-for-byte; for example, `int(\" 5\")` works today because `int` strips whitespace, and that must not be \"improved\".\n\n**Name collision.** client/backend/lib/http_utils.py is a separate module in a different process tree. It does not collide, because the Engine never has `client/backend/lib` on its path.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"SimilarServer construction and handler import (lines 123, 249/283 engine_ingest_mode, 279 rate_limiter, 290 bridge_token, 469 SimilarHandler)\">\n**What changes.** Nothing; the plan leaves this file untouched.\n\n**What depends on it.** The router reads, through `handler.server`:\n- `bridge_token` (always set at 290);\n- `engine_ingest_mode` (set at 283);\n- `rate_limiter`, via `_rate_limit_check`;\n- `embeddings_count`, `embeddings_dim`, `db` and `db_lock`.\n\n`from handlers.similar import SimilarHandler` (123) now transitively loads `router`.\n\n**Regression risk: low.** Test children built the test_video.py way (`dict.fromkeys(signature params)`, test_video.py:170/229) pass `engine_ingest_mode=None` and `rate_limiter=None`. Under such a server, a real ingest request answers 501, because `None != \"bridge\"`, and rate limiting is off. The new bridge-auth test must replace the ingest table entry (which it plans to do), or its control request would see 501 instead of the stub. In such a child, `bridge_token` comes from the child's `ENGINE_BRIDGE_TOKEN` env, so the test should set `srv.bridge_token` explicitly.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"ENGINE_BRIDGE_TOKEN and BRIDGE_TOKEN_HEADER (lines 500-501)\">\n**What changes.** Nothing in this file. Its importer changes from handlers/similar.py to router.py; server.py:77 still imports `ENGINE_BRIDGE_TOKEN`.\n\n**What depends on it.** The bridge gate in router.\n\n**Regression risk: low.** It is read at import time from env, the same as today.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_events.py\" element=\"handle_internal_events_ingest(handler, server) (line 18)\">\n**What changes.** Nothing in the file. It is now referenced only from the router's events-ingest adapter, which holds the 501 ingest-mode check before calling it.\n\n**What depends on it.**\n- The Client's ingest bridge (client/backend/server.py:1254).\n- test_internal_events.py.\n\n**Regression risk: low-medium.** The 501 branch has no existing test; grepping tests/active for `Bridge ingest is disabled` and `501` found only unrelated hits. The planned bridge-auth test swaps this adapter out for a stub, so the 501 path stays unverified by tests. It is preserved only by careful copying.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"handle_internal_video_resolve, handle_internal_videos_metadata, handle_internal_dislike_centroids (lines 86, 130, 175)\">\n**What changes.** Nothing. They are put into `POST_ROUTES` directly, since their signature is already `(handler: Any, server: Any) -> bool`.\n\n**What depends on it.**\n- The Client's engine_api_client.py:100/120/141.\n- test_internal_client_reads.py, which imports the module directly.\n\n**Regression risk: low.** The table holds function references, so patching `reads.handle_internal_video_resolve` after import would no longer affect dispatch. No current test does that; they patch inner functions.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"handle_internal_translate, handle_internal_translate_enqueue (lines 277, 312)\">\n**What changes.** Nothing. They go into `POST_ROUTES` directly.\n\n**What depends on it.**\n- The Client's engine_api_client.py:186/207.\n- test_internal_translate.py, including the variant Engine at 1044-1074, which asserts 401 without a token and 404 `Video not found` with one. That end-to-end check covers both translate routes through the new router.\n\n**Regression risk: low.** Tests patch `fetch_bounded` and similar inner names, which are unaffected by table references.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"handle_video_request, handle_video_refresh_request (lines 463, 449)\">\n**What changes.** Nothing. They are called from router adapters as `(handler, server, params)`, with `params = parse_qs(urlparse(handler.path).query)`.\n\n**What depends on it.** test_video.py, both in-process and in its Engine children ANSWER_CHILD/PERSIST_CHILD. The children patch `video.fetch_instance_json` / `video.urlopen`, which are module attributes looked up at call time, so dispatch through router still sees the patches.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"engine/server/api/handlers/__init__.py\" element=\"package docstring (lines 1-9)\">\n**What changes.** Possibly nothing; the plan does not mention it. It describes `similar` as the \"main Engine read handler for recommendations and read endpoints\". After the move that is arguably still true, because `SimilarHandler` is still the one handler class. A one-line reword would avoid implying that it routes, and could mention that routing lives in `api/router.py`. I am flagging this for the operator rather than asserting an edit.\n\n**What depends on it.** Nothing at runtime.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"EngineJsonFormatter.format (lines 236-272), _classify_event\">\n**What changes.** Nothing.\n\n**What depends on it.** The bridge-auth log lines, when they are emitted from router.py. I verified that the formatter emits only ts, level, event, message, modes, request_id, context and traceback. It never emits record.module, funcName, lineno or name. So moving the `logging.error` / `logging.warning` calls to another module leaves output identical as long as they stay on the root logger with the same message text.\n\n**Regression risk: low.** The risk materialises only if the move switches to `logging.getLogger(__name__)`. Even then the formatter would not show the name, but handler and level configuration differ: `configure_engine_logging` sets only the root logger, so a named logger would still propagate. The risk stays small.\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"bridge_headers / X-Bridge-Token sender (lines 14, 37-47) and internal POST calls\">\n**What changes.** Nothing.\n\n**What depends on it.** It depends on the Engine keeping the header name `X-Bridge-Token`, the 401 and 503 semantics, and the exact `/internal/*` paths.\n\n**Regression risk: low.** This is an external consumer that would break if the router's POST table mistyped a path; the stub-backed new test catches only the three stubbed paths. `/internal/videos/metadata` and `/internal/dislikes/centroids` are exercised end-to-end only by existing Client\u2194Engine tests, such as test_server.py with `engine_client`, test_dislikes and test_blocks.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"Client proxy of /api/channels, /api/v1/search/videos, /api/video(/refresh) (lines 80, 93, 101-102) and its own /api/health (418)\">\n**What changes.** Nothing.\n\n**What depends on it.** It depends on the Engine answering those GET paths with the same bodies. Its own `/api/health` at 418 is the Client's, not the Engine's.\n\n**Regression risk: low.** It is covered by test_server.py:471-474, which runs `/api/channels` through the Client against the real Engine.\n</impact>\n<impact path=\"tests/tmp/test_bridge_auth_router.py\" element=\"new test (name to be chosen) - bridge-auth via router with stubbed POST_ROUTES\">\n**What changes.** A new file. `tests/tmp` is the configured working dir (tests/config.json \"working\") and holds only probe scripts today.\n\n**Shape.** The test should follow the test_video.py pattern:\n- import `ENGINE_PY` and `ROOT` from conftest;\n- run a child under `ENGINE_PY` with `SERVER_DIR` and `API_DIR` on `sys.path`;\n- build `server.SimilarServer((\"127.0.0.1\", 0), SimilarHandler, **{**dict.fromkeys(params[3:]), \"db\": conn, ...})`;\n- start `serve_forever` on a thread.\n\n**Details to get right.**\n- `db` must be a real connection, or some placeholder. Health and channels are not hit, so a placeholder may suffice; confirm that the constructor does not touch `db`.\n- Set `srv.bridge_token` explicitly for the valid-token control. The env token from conftest's `BRIDGE_TOKEN` (conftest.py:35/260) is an alternative.\n- `srv.bridge_token = \"\"` gives the 503 case.\n- The stubs must replace `router.POST_ROUTES[...]` entries, not the handler module functions.\n- The control request with a valid token must show that the stub was called once. For `/internal/events/ingest`, replacing the table entry bypasses the 501 adapter. That is acceptable here, but it means the 501 path stays untested.\n- The unknown `/internal/` path with a valid token should give 404. This is not in the plan but would be a cheap extra control.\n\n**What depends on it.** It is evidence for acceptance criterion 3.\n\n**Regression risk: medium for test validity.** If the child imports `router` before `handlers.similar`, it still works, since router does not import similar. If the stub is installed after the server thread starts, it is still fine, because lookup happens per request.\n</impact>\n<impact path=\"tests/tmp/test_router_fake_route.py\" element=\"new test (name to be chosen) - GET_ROUTES['/fake'] served through real SimilarHandler\">\n**What changes.** A new file with the same child-process pattern. It adds `router.GET_ROUTES[\"/fake\"] = fn` where `fn(handler, server)` calls `respond_json`, then GETs `/fake` and checks the status and body.\n\n**Details to get right.**\n- `/fake` is not under `/api/`, so no rate-limit gate applies.\n- A good control: GET `/fake` before adding the entry gives 404, which shows the entry is what serves it.\n\n**What depends on it.** It is evidence for acceptance criterion 5.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_video.py\" element=\"ANSWER_CHILD / PERSIST_CHILD Engine children (lines 159-267) and unrouted-404 controls (631, 659)\">\n**What changes.** Nothing. This is an existing suite that must pass unchanged. It serves `/api/video`, `/api/video/refresh` and `/videos/v1/similar` through the real handler, now via the router.\n\n**What depends on it.** It is the primary end-to-end check of GET routing: the adapters, the pattern route and its concurrency with the refresh.\n\n**Regression risk: low.** It catches GET table and pattern mistakes.\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"engine fixture route checks (line 437-439), direct-method children (196, 238-267, 362-388, 471-500, 730, 979-1005)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The direct calls to `_handle_similar_request` and `_handle_similar`, and the patching of `similar.respond_json`, `read_json_body`, `_parse_client_likes`, `_resolve_client_likes`, `set_request_client_likes` and `clear_request_context`. All of these names stay in similar.py.\n- line 982, which subclasses `SimilarHandler`; that is unaffected.\n\n**Regression risk: low.**\n\nThe test docstring line 30 (\"The `engine` fixture answers GET /api/health ...\") is unaffected. conftest.py:264's comment \"(similar.py `_handle_similar`)\" also stays true.\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"FEED_MODES child (1399-1414) and Client-through-Engine /api/channels (471-474)\">\n**What changes.** Nothing.\n\n**What depends on it.** It imports `handlers.similar` under the Engine interpreter, so the router import must resolve there. It does, because the api dir is on the path. It also reaches `/api/channels` through the Client.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"variant Engine bridge checks (lines 1044-1074)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is a real-Engine check that `/internal/translate` and `/internal/translate/enqueue` answer 401 without a token and reach their handler with one. That gives the router independent coverage of the bridge gate on two routes.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_frontend_feed_params.py\" element=\"AST read of FEED_MODES from similar.py (lines 41, 120)\">\n**What changes.** Nothing.\n\n**What depends on it.** `FEED_MODES` must remain a module-level tuple literal assignment in `handlers/similar.py`. The plan keeps it there; it must not be moved alongside the routing code.\n\n**Regression risk: low.** It is listed because a broader-than-planned cleanup of similar.py's top section would break it silently.\n</impact>\n<impact path=\"engine/server/api/tests/test_recommendations_likes_limit.py\" element=\"direct _handle_similar_request tests with patched similar.respond_json\">\n**What changes.** Nothing.\n\n**What depends on it.** `similar.SIMILAR_POST_ROUTES` must still be visible inside similar.py as a module global, because `_recommendations_likes_payload_error` reads it. An import-back gives that. It also needs `similar.DEFAULT_CLIENT_LIKES_MAX` and `similar.respond_json`, both of which stay.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/config.json\" element=\"test_groups entries (e.g. test_similar.py, test_video.py, test_internal_translate.py, test_internal_events.py, test_server.py, test_logging_profiles.py)\">\n**What changes.** Uncertain; the plan does not mention it. These groups map test files to the source files whose change should trigger them. The new `engine/server/api/router.py` is in no group, so a later edit to the router alone would select no test. Consider adding `router.py` wherever `handlers/similar.py` appears for routing reasons, and adding `http_utils.py` to `test_video.py`/`test_server.py` if they rely on the parse helpers. Whether this file is edited as part of builds is a process question for the operator.\n\n**What depends on it.** The test-selection tooling.\n\n**Regression risk: none at runtime.** The risk is a coverage-selection gap.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"route list (lines 7-27) and references at lines 50 and 53\">\n**What changes.** Nothing, by operator decision.\n- Line 50 cites `_parse_include_nsfw` in `api/handlers/similar.py`, and line 53 cites `SimilarHandler._run_request` in `api/handlers/similar.py`. Both stay true.\n- The route list stays incomplete: it lacks `/api/health`, `/api/channels` and `/api/v1/search/videos`. `router.py`'s docstring becomes the complete list.\n- No README line names `_dispatch_*`, `_bridge_authorized` or `SIMILAR_POST_ROUTES`; I grepped for them.\n\n**What depends on it.** Human readers.\n\n**Regression risk: none.** There is doc drift between README and router.py, which the operator accepts.\n</impact>\n<impact path=\"docs/project/adr/0007-nsfw-filter-default-at-request-edge.md\" element=\"decision point 2 (line 17)\">\n**What changes.** Nothing. It cites `_handle_similar` and `_parse_include_nsfw` in `api/handlers/similar.py`, and `_handle_search`. None of these move.\n\n**Regression risk: none.** It is listed for completeness, because it names the module being edited.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a73b bridge shared secret (lines 504-509) and triage row (line 315)\">\n**What changes.** Nothing. The 503/401 behaviour and the `bridge.auth` log event it documents are preserved, and it names no source file or function.\n\n**Regression risk: none,** as long as the log message text is unchanged.\n</impact>\n<impact path=\"docs/project/issues/58-engine-routing-out-of-similar-handler.md\" element=\"issue status line\">\n**What changes.** Not in this step. On delivery, the triage-labels convention moves the issue to `complete` and into `docs/project/issues/archive/`.\n\n**Regression risk: none.**\n</impact>\n</impacts>\n</impacts>\n\n<docs_checklist>\n<doc path=\"engine/server/api/router.py\">\nNew module docstring: the complete Engine route list with method and gate per route. That means every route from the old similar.py docstring, plus `/internal/dislikes/centroids` and `/api/v1/search/videos`, with `/api/health` and `/api/channels` kept. `/internal/*` POST routes are marked as behind the bridge-auth gate, `/api/*` GET routes as behind the rate-limit gate, `/videos/{id}/similar` as having its own rate-limit check, and `/internal/events/ingest` as answering 501 outside bridge mode.\n</doc>\n<doc path=\"engine/server/api/handlers/similar.py\">\nModule docstring rewritten to describe only recommendations, similar, feeds and search, with the route list removed and a pointer to `api/router.py`. The `do_GET`/`do_POST` docstrings are reworded to \"hand the request to the router\", and `_serve_get`/`_serve_post` now say they route instead of dispatching.\n</doc>\n<doc path=\"engine/server/api/handlers/__init__.py\">\nOptional, not in the plan: the package docstring calls `similar` the \"main Engine read handler for recommendations and read endpoints\". A reword could note that routing now lives in `api/router.py`. Operator's call.\n</doc>\n<doc path=\"engine/server/README.md\">\nNo edit, by operator decision. I verified that its references to `SimilarHandler._run_request` (line 53) and `_parse_include_nsfw` (line 50) in `api/handlers/similar.py` stay true. Its route list (lines 7-27) stays incomplete; router.py becomes the complete list.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nengine/server/api/router.py route_get/route_post \u2014 every Engine request now flows through it. Gate order (bridge check before any POST lookup, unknown /internal/ included; /api/ rate limit before the GET lookup, unknown /api/ included; then rate-limit \u2192 setdefault \u2192 _handle_similar on the pattern route), byte-identical 401/503/429/501/404 bodies, and per-request table lookup must all be reproduced exactly. A broken handle_health also breaks the readiness probe of every Engine-child test fixture.\nengine/server/api/handlers/similar.py imports and helper renames \u2014 router must never import handlers.similar, or there is a partial-module cycle on server.py's import path. The four remaining _parse_int/_parse_non_negative_int call sites (584, 588, 1035, 1062) must be renamed, and a miss only raises NameError at request time on search or seeded/limited similar, which a narrow test run may not hit.\nengine/server/api/router.py events-ingest adapter (501 ingest-mode check) \u2014 no existing test covers the 501 path, and the planned bridge-auth test replaces this adapter with a stub, so a copying mistake in the mode check or its body would ship unnoticed. Test servers built with dict.fromkeys also carry engine_ingest_mode=None, so any test that hits the real adapter gets 501.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the files it names, and the plan holds up. similar.py matches every line range the inventory cites: the docstring at 1-20, `hmac` at 22, `fetch_channels` at 36, the bridge constants at 52/58, the four handler imports at 96-103, `SIMILAR_POST_ROUTES` at 106 and its reader at 234, `_bridge_authorized` at 417-440, `_dispatch_post` at 442-478, `_dispatch_get` at 494-562, `_rate_limit_check` at 632-639, and the helpers at 1167/1191/1267. Grep finds exactly four parse call sites that stay (584, 588, 1035, 1062) and five in channels that move (511, 515, 516, 524, 525). No other module in `engine/server/api` imports `handlers.similar` (the only cross-import is internal_translate \u2192 handlers.video), and `handlers/__init__.py` imports nothing. So `similar \u2192 router \u2192 handlers.internal_*/video` has no cycle, whether `similar` or `router` is imported first. No test calls or patches `_dispatch_*`, `_bridge_authorized`, `_extract_video_id_from_similar_path`, `similar._parse_*`, `similar.fetch_channels`, `similar.handle_*` or the bridge constants. No test reads similar.py's source text except the AST read of `FEED_MODES`. `SimilarServer.__init__` does not touch `db` beyond storing it, and it always sets `bridge_token` (290) and `engine_ingest_mode` (283). The test_video.py children build the server with `dict.fromkeys`, so `engine_ingest_mode` and `rate_limiter` are None there, as the inventory says. I found nothing the inventory is missing.\n<question id=\"1\">\nYes. Every branch of `_dispatch_get` and `_dispatch_post` maps onto a table entry, an adapter, a prefix gate or the one pattern branch. Gate order, 404s, 429s, 501 and bridge bodies stay the same. Calling `route_get(self)` and `route_post(self)` inside the unchanged `_serve_*` wrapper keeps the statement deadline and the interrupted-503 around all routing. Imports resolve in every place that loads similar.py today, because each of those already has the api dir on `sys.path` as a root (seen at test_similar.py:195 and test_video.py's children). The `[bridge.auth]` log lines stay byte-identical as long as the message text and the root-logger calls are copied exactly.\n</question>\n<question id=\"2\">\n1. Every Engine request now goes through a new module, so a mistake there shows up everywhere. A broken `handle_health` alone would time out every Engine-child fixture.\n2. Four underscore-prefixed `SimilarHandler` methods (`_rate_limit_check`, `_handle_similar_request`, `_handle_similar`, `_handle_search`), plus `_get_client_ip`, become a cross-module contract that is only checked when a request arrives.\n3. Table entries hold function references, so tests have to patch the table and not the handler modules. No current test patches the handler modules.\n4. The parse helpers become public in `http_utils`.\n5. The 501 ingest-mode branch has no test today, and the planned test swaps its adapter out, so it stays untested.\n6. `tests/config.json` maps no test group to `router.py`, so a later edit to the router alone would select no tests.\n</question>\n<question id=\"3\">\nNothing beyond what the plan and inventory already list:\n- rename the four remaining parse call sites in similar.py;\n- import `SIMILAR_POST_ROUTES` back into similar.py so `_recommendations_likes_payload_error` keeps reading it as a module global (test_recommendations_likes_limit.py and test_similar.py rely on that);\n- keep `FEED_MODES` as a module-level tuple literal in similar.py;\n- keep `urlparse`, `parse_qs` and `now_ms` imported in similar.py;\n- leave `server.py` and `SimilarServer` untouched.\n\nGrep after the edit for `_parse_int`, `_parse_non_negative_int`, `fetch_channels`, `hmac` and `ENGINE_BRIDGE_TOKEN` in similar.py. A missed rename only fails when a search or a seeded similar request runs, not at import.\n</question>\n<question id=\"4\">\nNo request behaves differently: same status, body, headers and log lines on every route and gate. What changes is code structure and naming: routing and bridge auth move to `router.py`; `_parse_int`/`_parse_non_negative_int` become `http_utils.parse_int`/`parse_non_negative_int`; `SIMILAR_POST_ROUTES` is owned by the router. Adding a route becomes a table entry plus one import in `router.py`, and routes can now be added at runtime by changing a table, which the fake-route test relies on.\n</question>\n\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Test the 501 ingest branch in the planned bridge-auth test.** Add one valid-token POST to `/internal/events/ingest` while the router's real ingest adapter is still in `POST_ROUTES`, under the `dict.fromkeys` server whose `engine_ingest_mode` is None. Assert 501 `{\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": null}`, then swap in the stub for the auth cases. Change: the only branch the move currently leaves unverified gets checked, and so do the adapter's body and its `mode` field. Cost: about five lines in a test file that is being written anyway, and no extra child process.\n\n2. **Add a valid-token POST to the unknown `/internal/` path in the same test, expecting 404 `{\"error\": \"Not found\"}`.** Change: it shows the unknown path gets 401 because the gate stopped it, not because nothing was routed there. Cost: one request and one assert.\n\n3. **Add `engine/server/api/router.py` to the `tests/config.json` groups that already list `engine/server/api/handlers/similar.py`.** These include `test_similar.py`, `test_video.py`, `test_internal_translate.py` and `test_server.py`. Change: a later edit to the router alone selects the suites that cover routing. Cost: a few JSON lines. This is a process file, so the operator decides whether builds edit it.\n\n4. **Optionally reword `engine/server/api/handlers/__init__.py` line 4** so it says routing lives in `api/router.py`. Change: the package docstring stops implying that `similar` routes. Cost: one docstring line, no runtime effect. Skipping it leaves a slightly stale but not wrong description.\n\n5. **No test-double recommendation is needed.** The plan widens no existing double. The stub handlers in test_similar.py (around 240-265, 362, 471, 979) and test_recommendations_likes_limit.py call the similar methods directly and never go through the router, so their recorded calls and expected sequences are unchanged. The new tests' recording stubs are the plan's own, and each has a control showing it is wired in.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft \u2014 issue 58: Engine routing out of `SimilarHandler`\n\nFiles I read for this draft: `handlers/similar.py` (lines 1-120, 300-650, 1160-1275), `http_utils.py`, `server.py:240-300` and its `sys.path` setup at 21-23, the import blocks of `handlers/internal_*.py` and `handlers/video.py`, `handlers/__init__.py`, `tests/active/test_video.py` (the child pattern and its `subprocess.run` lines 564/608), `tests/active/conftest.py:1-60` and `tests/config.json`. Everything below matches the plan. Pass 1 against the plan and the requirements came out clean, so no further passes were needed. The one thing that differs from the plan's wording, the channels rename, is called out in the similar.py section.\n\n### What has to be tested\n\n- **Bridge gate on POST `/internal/*`.**\n  - Missing token gives 401. A wrong token gives 401. An unset token (`\"\"`) gives 503.\n  - This holds for one route of each kind (resolve, translate, ingest) and for an unknown `/internal/` path.\n  - The handler does not run in any of those cases.\n  - A valid token reaches the stub once per path, and the unknown path gets 404.\n- **Fake route.** A `GET_ROUTES` entry alone serves `/fake` through the real `SimilarHandler`. Before the entry exists, `/fake` gets 404.\n- **Cheap extras, not in the plan.** Each closes a gap the impact inventory names:\n  - the 501 ingest-mode body with its `mode` field, which was untested until now;\n  - the plain 404 for GET `/internal/*`, which has no gate.\n- **Everything else is covered by existing suites, unchanged.**\n  - test_video: the `/api/video` and refresh adapters, the `/videos/{id}/similar` pattern, and unrouted 404s.\n  - test_internal_translate 1044-1074: real bridge 401s on two routes.\n  - test_server: `/api/channels` via the Client.\n  - The conftest `/api/health` readiness probe, which every Engine fixture depends on.\n  - test_similar and test_recommendations_likes_limit: direct `_handle_similar*` calls and `SIMILAR_POST_ROUTES` through the import-back.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/router.py` | **new.** Route list docstring, `SIMILAR_POST_ROUTES`, `GET_ROUTES`, `POST_ROUTES`, adapters, `handle_health`, `handle_channels`, `_extract_video_id_from_similar_path`, `bridge_authorized`, `route_get`, `route_post` |\n| `engine/server/api/http_utils.py` | adds `parse_int`, `parse_non_negative_int` (moved unchanged) |\n| `engine/server/api/handlers/similar.py` | docstring, imports, `SIMILAR_POST_ROUTES` removed (imported back), `_bridge_authorized`/`_dispatch_*` removed, `_serve_*` call the router, 4 call-site renames, 3 helpers removed |\n| `tests/tmp/test_router_bridge_auth.py` | **new** |\n| `tests/tmp/test_router_fake_route.py` | **new** |\n\nDependency direction: `handlers.similar` \u2192 `router` \u2192 `handlers.internal_*`, `handlers.video`, `http_utils`, `server_config`, `data.*`. Nothing below `router` imports `handlers.similar`; I checked all four import blocks. `handlers/__init__.py` is docstring only, so importing `handlers.internal_events` from inside a partly initialised `handlers.similar` is safe.\n\n### `engine/server/api/router.py` (whole file)\n\n```python\n\"\"\"Route Engine HTTP requests to their handlers.\n\nSimilarHandler hands every GET and POST here, inside its statement deadline. A route is one entry in GET_ROUTES or POST_ROUTES keyed by exact path (query string ignored, no trailing-slash match) whose value takes (handler, server); a path in neither table, or sent with the other method, answers 404 {\"error\": \"Not found\"}.\n\nRoutes:\n- POST /recommendations: recommendation feed and debug payloads; own per-IP rate-limit check.\n- POST /videos/similar: extended similar route; own per-IP rate-limit check.\n- GET /videos/{id}/similar: id-based similar alias; the one pattern route, tried after an exact miss, with its own per-IP rate-limit check.\n- GET /api/health: health check. [rate-limit gate]\n- GET /api/channels: channels listing. [rate-limit gate]\n- GET /api/v1/search/videos: hybrid video search. [rate-limit gate]\n- GET /api/video: single video metadata. [rate-limit gate]\n- GET /api/video/refresh: single video metadata refreshed from its instance. [rate-limit gate]\n- POST /internal/videos/resolve: internal Client read lookup by video_id/uuid(+host). [bridge gate]\n- POST /internal/videos/metadata: internal Client metadata batch lookup. [bridge gate]\n- POST /internal/dislikes/centroids: internal Client clustering of a visitor's disliked videos into taste centroids; nothing stored. [bridge gate]\n- POST /internal/translate: internal Client read of a video's English translate state and whether a translate worker is serving; cues from a stored job, or from its own instance (cached). [bridge gate]\n- POST /internal/translate/enqueue: internal Client request to queue a video's whisper translate job while a translate worker is serving. [bridge gate]\n- POST /internal/events/ingest: internal bridge ingest for normalized events; 501 outside ENGINE_INGEST_MODE=bridge. [bridge gate]\n\nGates:\n- bridge gate: every POST /internal/* path, unknown ones included, needs the shared X-Bridge-Token first: 503 when the Engine has none configured, 401 when it is missing or wrong.\n- rate-limit gate: every GET /api/* path, unknown ones included, passes the per-IP limiter first: 429.\n- GET /internal/* has no gate and answers 404.\n\"\"\"\nimport hmac\nimport logging\nfrom typing import Any, Callable\nfrom urllib.parse import parse_qs, urlparse\n\nfrom data.channels import fetch_channels\nfrom data.time import now_ms\nfrom http_utils import parse_int, parse_non_negative_int, respond_json\nfrom server_config import BRIDGE_TOKEN_HEADER, ENGINE_BRIDGE_TOKEN\nfrom handlers.internal_events import handle_internal_events_ingest\nfrom handlers.internal_client_reads import (\n    handle_internal_dislike_centroids,\n    handle_internal_video_resolve,\n    handle_internal_videos_metadata,\n)\nfrom handlers.internal_translate import handle_internal_translate, handle_internal_translate_enqueue\nfrom handlers.video import handle_video_refresh_request, handle_video_request\n\n\nSIMILAR_POST_ROUTES = {\"/recommendations\", \"/videos/similar\"}\n\n\ndef handle_health(handler: Any, server: Any) -> None:\n    \"\"\"Answer the health check with the loaded embedding count and dimension.\"\"\"\n    payload = {\n        \"ok\": True,\n        \"total\": server.embeddings_count,\n        \"embeddingDim\": server.embeddings_dim,\n    }\n    respond_json(handler, 200, payload)\n\n\ndef handle_channels(handler: Any, server: Any) -> None:\n    \"\"\"Answer a page of the channels listing.\"\"\"\n    params = parse_qs(urlparse(handler.path).query)\n    limit = parse_int(params.get(\"limit\", [None])[0])\n    if limit <= 0:\n        limit = 100\n    limit = min(limit, 500)\n    offset = parse_int(params.get(\"offset\", [None])[0])\n    max_videos = parse_non_negative_int(params.get(\"maxVideos\", [None])[0])\n    with server.db_lock:\n        rows, total = fetch_channels(\n            server.db,\n            limit=limit,\n            offset=offset,\n            query=params.get(\"q\", [\"\"])[0] or \"\",\n            instance=params.get(\"instance\", [\"\"])[0] or \"\",\n            min_followers=parse_int(params.get(\"minFollowers\", [None])[0]),\n            min_videos=parse_int(params.get(\"minVideos\", [None])[0]),\n            max_videos=max_videos,\n            sort=params.get(\"sort\", [\"followers\"])[0] or \"followers\",\n            direction=params.get(\"dir\", [\"desc\"])[0] or \"desc\",\n        )\n    respond_json(\n        handler,\n        200,\n        {\n            \"generatedAt\": now_ms(),\n            \"total\": total,\n            \"rows\": rows,\n        },\n    )\n\n\ndef _similar_post(handler: Any, server: Any) -> None:\n    \"\"\"Serve a recommendations or extended-similar POST through the handler's similarity path.\"\"\"\n    handler._handle_similar_request(method=\"POST\")\n\n\ndef _search(handler: Any, server: Any) -> None:\n    \"\"\"Serve a video search with the request's query parameters.\"\"\"\n    handler._handle_search(parse_qs(urlparse(handler.path).query))\n\n\ndef _video(handler: Any, server: Any) -> None:\n    \"\"\"Serve single video metadata with the request's query parameters.\"\"\"\n    handle_video_request(handler, server, parse_qs(urlparse(handler.path).query))\n\n\ndef _video_refresh(handler: Any, server: Any) -> None:\n    \"\"\"Serve refreshed single video metadata with the request's query parameters.\"\"\"\n    handle_video_refresh_request(handler, server, parse_qs(urlparse(handler.path).query))\n\n\ndef _events_ingest(handler: Any, server: Any) -> None:\n    \"\"\"Serve bridge ingest, answering 501 when the Engine is not in bridge ingest mode.\"\"\"\n    if getattr(server, \"engine_ingest_mode\", \"bridge\") != \"bridge\":\n        respond_json(\n            handler,\n            501,\n            {\n                \"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\",\n                \"mode\": getattr(server, \"engine_ingest_mode\", \"bridge\"),\n            },\n        )\n        return\n    handle_internal_events_ingest(handler, server)\n\n\n# Exact path -> callable(handler, server); read per request, so a test may add or replace an entry at run time.\nGET_ROUTES: dict[str, Callable[[Any, Any], Any]] = {\n    \"/api/health\": handle_health,\n    \"/api/channels\": handle_channels,\n    \"/api/v1/search/videos\": _search,\n    \"/api/video\": _video,\n    \"/api/video/refresh\": _video_refresh,\n}\n\nPOST_ROUTES: dict[str, Callable[[Any, Any], Any]] = {\n    **dict.fromkeys(SIMILAR_POST_ROUTES, _similar_post),\n    \"/internal/videos/resolve\": handle_internal_video_resolve,\n    \"/internal/videos/metadata\": handle_internal_videos_metadata,\n    \"/internal/dislikes/centroids\": handle_internal_dislike_centroids,\n    \"/internal/translate\": handle_internal_translate,\n    \"/internal/translate/enqueue\": handle_internal_translate_enqueue,\n    \"/internal/events/ingest\": _events_ingest,\n}\n\n\ndef _extract_video_id_from_similar_path(path: str) -> str | None:\n    \"\"\"Resolve /videos/{id}/similar route shape to seed video id.\"\"\"\n    if not path.startswith(\"/videos/\") or not path.endswith(\"/similar\"):\n        return None\n    parts = path.strip(\"/\").split(\"/\")\n    if len(parts) != 3 or parts[0] != \"videos\" or parts[2] != \"similar\":\n        return None\n    video_id = parts[1].strip()\n    return video_id or None\n\n\ndef bridge_authorized(handler: Any) -> bool:\n    \"\"\"Check the shared secret on internal bridge routes.\n\n    These routes write to the interaction event stream and read across the\n    Client/Engine boundary, so an unset secret fails closed: accepting them\n    unauthenticated is what let any browser rewrite the global ranking.\n    \"\"\"\n    configured = getattr(handler.server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)\n    if not configured:\n        logging.error(\n            \"[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting %s\", handler.path\n        )\n        respond_json(\n            handler, 503, {\"error\": \"Bridge token is not configured on the Engine\"}\n        )\n        return False\n    presented = handler.headers.get(BRIDGE_TOKEN_HEADER, \"\").strip()\n    if not presented or not hmac.compare_digest(presented, configured):\n        logging.warning(\n            \"[bridge.auth] rejected %s from ip=%s\", handler.path, handler._get_client_ip()\n        )\n        respond_json(handler, 401, {\"error\": \"Unauthorized\"})\n        return False\n    return True\n\n\ndef route_post(handler: Any) -> None:\n    \"\"\"Route a POST through the /internal/ bridge gate to its POST_ROUTES entry, or 404.\"\"\"\n    url = urlparse(handler.path)\n    if url.path.startswith(\"/internal/\") and not bridge_authorized(handler):\n        return\n    route = POST_ROUTES.get(url.path)\n    if route is not None:\n        route(handler, handler.server)\n        return\n    respond_json(handler, 404, {\"error\": \"Not found\"})\n\n\ndef route_get(handler: Any) -> None:\n    \"\"\"Route a GET through the /api/ rate-limit gate to its GET_ROUTES entry, the /videos/{id}/similar pattern, or 404.\"\"\"\n    url = urlparse(handler.path)\n    if url.path.startswith(\"/api/\") and not handler._rate_limit_check(url.path):\n        respond_json(handler, 429, {\"error\": \"Rate limit exceeded\"})\n        return\n    route = GET_ROUTES.get(url.path)\n    if route is not None:\n        route(handler, handler.server)\n        return\n    video_path_id = _extract_video_id_from_similar_path(url.path)\n    if video_path_id is not None:\n        if not handler._rate_limit_check(url.path):\n            respond_json(handler, 429, {\"error\": \"Rate limit exceeded\"})\n            return\n        params = parse_qs(url.query)\n        params.setdefault(\"id\", [video_path_id])\n        handler._handle_similar(params)\n        return\n    respond_json(handler, 404, {\"error\": \"Not found\"})\n```\n\n**Invariants**\n\n- **Gate order.**\n  - `route_post`: the bridge gate, then `POST_ROUTES.get`, then 404.\n  - `route_get`: the `/api/` limiter, then `GET_ROUTES.get`, then the pattern (limiter, then `setdefault`, then `_handle_similar`), then 404.\n  - This is the same order as `similar.py:442-562`.\n- **Table lookups happen at call time.** The tables are plain module-level dicts and are never copied.\n- **Logging stays byte-identical.** Bridge-auth logging uses the root `logging.error` / `logging.warning` with the old format strings and the raw `handler.path`.\n- **Return values are ignored.** Each `handle_internal_*` returns a bool, and the router discards it, as the old chain did.\n- **Small differences that cannot change an outcome.**\n  - `parse_qs` now runs after the pattern's limiter, where the old code ran it before. `parse_qs` with default arguments cannot raise, so this changes nothing.\n  - Search and video re-parse the query from `handler.path`. That gives the same dict the old shared `params` did.\n- **No import of `handlers.similar` anywhere in this file.** The router reaches similarity only through methods on `handler`: `_handle_similar_request`, `_handle_similar`, `_handle_search`, `_rate_limit_check` and `_get_client_ip`.\n\n### `engine/server/api/http_utils.py` (insert after `read_json_body`, before `class RateLimiter`)\n\n```python\ndef parse_int(value: str | None) -> int:\n    \"\"\"Parse a positive integer; return 0 on invalid input.\"\"\"\n    try:\n        parsed = int(value or \"0\")\n    except ValueError:\n        return 0\n    return parsed if parsed > 0 else 0\n\n\ndef parse_non_negative_int(value: str | None) -> int | None:\n    \"\"\"Parse a non-negative integer; return None on invalid input.\"\"\"\n    if value is None or not value.strip():\n        return None\n    try:\n        parsed = int(value)\n    except ValueError:\n        return None\n    return parsed if parsed >= 0 else None\n```\n\nThe bodies and docstrings are byte-for-byte the old `_parse_int` / `_parse_non_negative_int`. No new import is needed.\n\n### `engine/server/api/handlers/similar.py` edits\n\n1. **Docstring.** Lines 1-20 become:\n```python\n\"\"\"Similarity HTTP handler for Engine read surface.\n\nServes recommendations, similar videos (by id and the extended POST route), the home feeds and hybrid video search. SimilarHandler is the Engine's one request handler class; it hands every GET and POST to `api/router.py`, which holds the route list, the bridge-auth and rate-limit gates and the 404.\n\nKey steps:\n- Parse seed/params, resolve likes (client JSON or users DB).\n- Build candidate pools, score, mix, and return stable rows.\n\"\"\"\n```\n2. **Imports.**\n   - Removed:\n     - `import hmac` (22);\n     - `from data.channels import fetch_channels` (36);\n     - `BRIDGE_TOKEN_HEADER,` (52) and `ENGINE_BRIDGE_TOKEN,` (58) from the `server_config` import;\n     - lines 96-103, the four handler imports.\n   - Line 80 becomes `from http_utils import parse_int, parse_non_negative_int, read_json_body, respond_json, respond_options, resolve_user_id`.\n   - Added in place of 96-103: `from router import SIMILAR_POST_ROUTES, route_get, route_post`.\n   - Kept: `urlparse` / `parse_qs` (643/647), `now_ms`, `sqlite3`, `Callable`, `logging`.\n3. **`SIMILAR_POST_ROUTES = {...}` (106) is deleted.** `_recommendations_likes_payload_error` (234) reads the imported name, unchanged. `FEED_MODES` stays a module-level tuple literal, as test_frontend_feed_params requires.\n4. **`do_POST` / `_serve_post` (403-415):**\n```python\n    def do_POST(self) -> None:  # noqa: N802\n        \"\"\"Hand a POST to the router under the time budget.\"\"\"\n        self._run_request(self._serve_post)\n\n    def _serve_post(self) -> None:\n        \"\"\"Route a POST under the time budget, answering 503 when its database work is interrupted.\"\"\"\n        try:\n            with self._statement_deadline():\n                route_post(self)\n        except sqlite3.OperationalError as exc:\n            if not is_interrupted_error(exc):\n                raise\n            self._respond_interrupted()\n```\n5. **`_bridge_authorized` (417-440) and `_dispatch_post` (442-478) are deleted.**\n6. **`do_GET` / `_serve_get` (480-492):** the same shape, with docstrings `\"\"\"Hand a GET to the router under the time budget.\"\"\"` / `\"\"\"Route a GET under the time budget, answering 503 when its database work is interrupted.\"\"\"` and the body `route_get(self)`.\n7. **`_dispatch_get` (494-562) is deleted.**\n8. **Renames.** These are the only remaining call sites (grep-verified):\n   - 584 `_parse_int` \u2192 `parse_int`;\n   - 588 `_parse_int` \u2192 `parse_int`;\n   - 1035 `_parse_int` \u2192 `parse_int`;\n   - 1062 `_parse_non_negative_int` \u2192 `parse_non_negative_int`.\n\n   The plan says channels call sites \"stay\". That is slightly off: they move into `router.handle_channels` instead, as the impact inventory already notes.\n9. **Deleted helpers:** `_parse_int` (1167-1173), `_parse_non_negative_int` (1191-1199) and `_extract_video_id_from_similar_path` (1267-1275). `_parse_bool` and `_parse_include_nsfw` stay.\n10. **Post-edit grep must return nothing** in similar.py for: `_parse_int(`, `_parse_non_negative_int`, `_extract_video_id`, `fetch_channels`, `hmac`, `ENGINE_BRIDGE_TOKEN`, `BRIDGE_TOKEN_HEADER`, `_dispatch_`, `_bridge_authorized`, `handlers.internal_`, `handlers.video`. A missed rename would only surface at request time, as a NameError.\n\nNothing else in `SimilarHandler` changes. `_run_request`, the deadline and 503 wrapper, `_get_client_ip`, `_get_full_url`, `log_request`, `log_message`, `do_OPTIONS`, `_rate_limit_check` and every similarity, feed and search method stay as they are.\n\n### Tests\n\nBoth tests are pytest launchers that run an Engine child the way test_video does: `subprocess.run([ENGINE_PY, \"-c\", CHILD], cwd=API_DIR)`. The child imports `server` first, because it puts `engine/server` on `sys.path`. Then it builds a real `SimilarServer` with the real `SimilarHandler` on port 0, using `dict.fromkeys(signature params[3:])`. So `db`, `rate_limiter` and `engine_ingest_mode` are all `None`; the constructor never touches `db`, and these paths never reach it.\n\n`ROOT` and `ENGINE_PY` are defined locally, with the same expressions as conftest. `tests/tmp` has no conftest, and importing `tests/active/conftest.py` would load the Client backend. That is a deliberate two-line duplication; when the files are archived to `tests/active`, switch to `from conftest import ENGINE_PY, ROOT`.\n\n**`tests/tmp/test_router_bridge_auth.py`**\n\n```python\n\"\"\"POST /internal/* behind the router's bridge-auth gate (engine/server/api/router.py), through a real SimilarServer and SimilarHandler in an Engine child.\n\n- With the Engine's token set, a POST to /internal/videos/resolve, /internal/translate, /internal/events/ingest or an unknown /internal/ path answers 401 {\"error\": \"Unauthorized\"} without an X-Bridge-Token and with a wrong one, and 503 {\"error\": \"Bridge token is not configured on the Engine\"} once the token is \"\".\n- None of those requests reaches the route: the three routes' POST_ROUTES entries are replaced by a recording stub, which records nothing for them; with the right token each stub is reached once and the unknown path answers 404 {\"error\": \"Not found\"}.\n- Before the stubs, a valid-token ingest under engine_ingest_mode None answers 501 with that mode, from the router's own ingest adapter.\n- A GET to /internal/videos/resolve answers a plain 404, with no gate.\n\"\"\"\nfrom __future__ import annotations\n\nimport json\nimport subprocess\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[2]\nENGINE_PY = ROOT / \"engine\" / \".pixi\" / \"envs\" / \"default\" / \"bin\" / \"python\"\nAPI_DIR = ROOT / \"engine\" / \"server\" / \"api\"\n\nCHILD = r'''\nimport http.client, inspect, json, threading\nimport server\nimport router\nfrom handlers.similar import SimilarHandler\nfrom http_utils import respond_json\n\nTOKEN = \"router-test-token\"\nSTUBBED = [\"/internal/videos/resolve\", \"/internal/translate\", \"/internal/events/ingest\"]\nPATHS = STUBBED + [\"/internal/no-such-route\"]\n\ndef send(port, method, path, headers):\n    client = http.client.HTTPConnection(\"127.0.0.1\", port, timeout=30)\n    client.request(method, path, body=b\"{}\" if method == \"POST\" else None, headers=headers)\n    resp = client.getresponse()\n    body = json.loads(resp.read() or b\"null\")\n    client.close()\n    return [resp.status, body]\n\nargs = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])\nsrv = server.SimilarServer((\"127.0.0.1\", 0), SimilarHandler, **args)\nsrv.bridge_token = TOKEN\nthreading.Thread(target=srv.serve_forever, daemon=True).start()\nport = srv.server_address[1]\ncalls = []\ndef stub(handler, server_):\n    calls.append(handler.path)\n    respond_json(handler, 200, {\"stub\": handler.path})\nreport = {}\ntry:\n    report[\"ingest_mode\"] = send(port, \"POST\", \"/internal/events/ingest\", {\"X-Bridge-Token\": TOKEN})\n    for path in STUBBED:\n        router.POST_ROUTES[path] = stub\n    report[\"missing\"] = {p: send(port, \"POST\", p, {}) for p in PATHS}\n    report[\"wrong\"] = {p: send(port, \"POST\", p, {\"X-Bridge-Token\": \"wrong\"}) for p in PATHS}\n    report[\"calls_rejected\"] = list(calls)\n    report[\"valid\"] = {p: send(port, \"POST\", p, {\"X-Bridge-Token\": TOKEN}) for p in PATHS}\n    report[\"calls_valid\"] = list(calls)\n    srv.bridge_token = \"\"\n    report[\"unset\"] = {p: send(port, \"POST\", p, {\"X-Bridge-Token\": TOKEN}) for p in PATHS}\n    report[\"calls_after_unset\"] = list(calls)\n    report[\"get_internal\"] = send(port, \"GET\", \"/internal/videos/resolve\", {\"X-Bridge-Token\": TOKEN})\nfinally:\n    srv.shutdown()\n    srv.server_close()\nprint(json.dumps(report))\n'''\n\nPATHS = [\"/internal/videos/resolve\", \"/internal/translate\", \"/internal/events/ingest\", \"/internal/no-such-route\"]\nSTUBBED = PATHS[:3]\nUNAUTHORIZED = [401, {\"error\": \"Unauthorized\"}]\nUNSET = [503, {\"error\": \"Bridge token is not configured on the Engine\"}]\n\n\ndef test_internal_posts_are_gated_before_their_route():\n    assert ENGINE_PY.exists(), f\"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/\"\n    run = subprocess.run([str(ENGINE_PY), \"-c\", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)\n    assert run.returncode == 0, run.stderr\n    report = json.loads(run.stdout)\n    assert report[\"ingest_mode\"] == [501, {\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": None}]\n    assert report[\"missing\"] == {path: UNAUTHORIZED for path in PATHS}\n    assert report[\"wrong\"] == {path: UNAUTHORIZED for path in PATHS}\n    assert report[\"calls_rejected\"] == []\n    assert report[\"valid\"] == {**{path: [200, {\"stub\": path}] for path in STUBBED}, \"/internal/no-such-route\": [404, {\"error\": \"Not found\"}]}\n    assert report[\"calls_valid\"] == STUBBED\n    assert report[\"unset\"] == {path: UNSET for path in PATHS}\n    assert report[\"calls_after_unset\"] == STUBBED\n    assert report[\"get_internal\"] == [404, {\"error\": \"Not found\"}]\n```\n\n**`tests/tmp/test_router_fake_route.py`**\n\n```python\n\"\"\"A route added as one router.GET_ROUTES entry, with no edit to handlers/similar.py, is served through a real SimilarServer and SimilarHandler in an Engine child.\n\n- Before the entry, GET /fake answers 404 {\"error\": \"Not found\"}.\n- After router.GET_ROUTES[\"/fake\"] is set to a function answering through respond_json, GET /fake?x=1 answers 200 with that function's body, which carries the raw request path, query included.\n\"\"\"\nfrom __future__ import annotations\n\nimport json\nimport subprocess\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[2]\nENGINE_PY = ROOT / \"engine\" / \".pixi\" / \"envs\" / \"default\" / \"bin\" / \"python\"\nAPI_DIR = ROOT / \"engine\" / \"server\" / \"api\"\n\nCHILD = r'''\nimport http.client, inspect, json, threading\nimport server\nimport router\nfrom handlers.similar import SimilarHandler\nfrom http_utils import respond_json\n\ndef get(port, path):\n    client = http.client.HTTPConnection(\"127.0.0.1\", port, timeout=30)\n    client.request(\"GET\", path)\n    resp = client.getresponse()\n    body = json.loads(resp.read() or b\"null\")\n    client.close()\n    return [resp.status, body]\n\ndef fake(handler, server_):\n    respond_json(handler, 200, {\"fake\": True, \"path\": handler.path})\n\nargs = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])\nsrv = server.SimilarServer((\"127.0.0.1\", 0), SimilarHandler, **args)\nthreading.Thread(target=srv.serve_forever, daemon=True).start()\nport = srv.server_address[1]\nreport = {}\ntry:\n    report[\"before\"] = get(port, \"/fake\")\n    router.GET_ROUTES[\"/fake\"] = fake\n    report[\"after\"] = get(port, \"/fake?x=1\")\nfinally:\n    srv.shutdown()\n    srv.server_close()\nprint(json.dumps(report))\n'''\n\n\ndef test_fake_route_is_served_from_a_table_entry():\n    assert ENGINE_PY.exists(), f\"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/\"\n    run = subprocess.run([str(ENGINE_PY), \"-c\", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)\n    assert run.returncode == 0, run.stderr\n    report = json.loads(run.stdout)\n    assert report[\"before\"] == [404, {\"error\": \"Not found\"}]\n    assert report[\"after\"] == [200, {\"fake\": True, \"path\": \"/fake?x=1\"}]\n```\n\n### Decisions behind the draft\n\n- **Table signature `(handler, server)`.** The five client-read and translate handlers go into the table with no adapter. The four adapters are named one-line-docstring functions, matching the file style; no lambdas.\n- **`POST_ROUTES` derives its two similar entries from `SIMILAR_POST_ROUTES` with `dict.fromkeys`.** Each path string is written exactly once, in router.py.\n- **`handle_health` / `handle_channels` are public `handle_*`,** following the `handlers/*.py` naming. The adapters are private, because nothing outside the router should call them.\n- **Tests replace table entries, never module functions.** Only the table entry is looked up at dispatch time.\n- **Ingest 501 check runs before stubbing.** The 501 request comes before the stubs replace the ingest entry, so the router's own adapter is exercised. `handle_internal_events_ingest` is never reached there, because `engine_ingest_mode` is `None`.\n- **Deliberate simplification: one hard-coded pattern route.** `/videos/{id}/similar` is special-cased in `route_get`. The ceiling is a second parameterised path. The upgrade is an ordered list of `(matcher, callable)` pairs tried after the exact lookup.\n\n### Left for the operator (not edited, outside the settled plan)\n\n- **`handlers/__init__.py`.** The docstring line \"similar: main Engine read handler \u2026\" could gain \"routing lives in `api/router.py`\". This is optional, per the inventory.\n- **`tests/config.json`.** `engine/server/api/router.py` is in no test group, so an edit to the router alone selects no test. Candidates for adding it: `test_similar.py`, `test_video.py`, `test_internal_translate.py`, `test_internal_events.py` and `test_server.py`. This is a process decision.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: real HTTP requests into a real `SimilarServer` running the real `SimilarHandler` on an ephemeral port. The server runs in an Engine child process (`ENGINE_PY -c CHILD`, cwd `engine/server/api`), which imports `server` first so the `sys.path` setup runs. The server is built with `dict.fromkeys(signature params[3:])`. This copies the existing child harness in `tests/active/test_video.py`, the precedent for this seam. The only shim is a replaced router table entry, never a patched module function, because dispatch looks up the table per request. `tests/tmp/test_router_bridge_auth.py` (clause_1) replaces the `POST_ROUTES` entries for `/internal/videos/resolve`, `/internal/translate` and `/internal/events/ingest` with recording stubs. It then asserts, for those three paths plus `/internal/no-such-route`: 401 `{\"error\": \"Unauthorized\"}` with no token; 401 again with a wrong token; zero stub calls after both; 503 `{\"error\": \"Bridge token is not configured on the Engine\"}` after `srv.bridge_token = \"\"`, with no new stub calls. A valid-token control reaches each stub exactly once and gets 404 on the unknown path. Without that control, the zero counts would prove nothing. Beyond the clause, the same test asserts the ingest adapter's 501 body with `mode: None` and the ungated plain 404 for GET `/internal/videos/resolve`. `tests/tmp/test_router_fake_route.py` (clause_2) asserts that GET `/fake` answers 404 `{\"error\": \"Not found\"}` before `router.GET_ROUTES[\"/fake\"]` is set. After it is set, GET `/fake?x=1` answers 200 with the stub's body carrying the raw path, which proves the request reached the stub through the real handler. Existing suites cover everything else unchanged: test_video, test_internal_translate 1044-1074, test_server `/api/channels`, the conftest `/api/health` probe, test_similar and test_recommendations_likes_limit.</checkpoint>\n<name>Engine routing moves into router.py</name>\n<intent>Every Engine GET and POST that `SimilarHandler` receives is answered by `engine/server/api/router.py`, through its `/internal/` bridge gate, its `/api/` rate-limit gate and its `GET_ROUTES`/`POST_ROUTES` tables. `SimilarHandler`'s own `_dispatch_*` and `_bridge_authorized` methods no longer exist.</intent>\n<clause_1>Every POST to an `/internal/*` path, unknown paths included, gets the router's bridge-gate answer before its `POST_ROUTES` entry runs: 401 when the token is missing or wrong, 503 when the Engine has none set.</clause_1>\n<clause_2>A route added as one `GET_ROUTES` entry, with no edit to `handlers/similar.py`, is served through the real `SimilarHandler`.</clause_2>\n<files>engine/server/api/router.py (NEW), engine/server/api/http_utils.py (EDITED), engine/server/api/handlers/similar.py (EDITED), tests/tmp/test_router_bridge_auth.py (NEW), tests/tmp/test_router_fake_route.py (NEW)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nOne phase, because no coherent intermediate state can be verified on its own. The parse-helper move to `http_utils.py` has no observable behaviour; it is covered only by the call sites in the router and similar.py, so as a separate phase it would have no checkpoint. Moving POST routing before GET routing would leave dispatch split between the router and `SimilarHandler`, and the plan does not describe that state. All of the router, `http_utils.py` and similar.py have to land together for imports to resolve and requests to route. The phase's intent cuts into two observable facts, and each one maps to one of the two new tests the draft supplies. The tests' extra assertions (the ingest 501 body and the ungated GET `/internal` 404) are cheap regression cover for gaps the impact inventory named, not extra clauses. Everything else in the pure-move contract is covered by the existing suites, which run unchanged. The work involves no prose or agent-facing text. The README and `handlers/__init__.py` docstring are documentation, so they get no phase. The operator approved this plan.\n</rationale>",
    "author:tests/tmp/test_58_engine_routing_out_of_similar_phase1.py": "<assertions>\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:112 - control: the Engine child exits 0, meaning it imported `router`, built the real SimilarServer/SimilarHandler and sent every request. Before the phase this fails with `ModuleNotFoundError: No module named 'router'` (observed), which is the checkpoint's expected red.\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:119 - extra, not a clause: before any stub goes in, a valid-token POST /internal/events/ingest with engine_ingest_mode None gets the router adapter's 501 `{\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": None}`.\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:121 - all four of /internal/videos/resolve, /internal/translate, /internal/events/ingest and /internal/no-such-route answer 401 `{\"error\": \"Unauthorized\"}` with no X-Bridge-Token. Fails if the gate runs after the table lookup (stub's 200) or covers only known routes (404 on the unknown path). C1\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:123 - the same four answer 401 with a near-miss token (the real token minus its last character). Fails if the token check is a prefix or containment compare instead of an exact match. C1\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:124 - the recording stubs in POST_ROUTES saw no call after the missing-token and wrong-token requests. Shows the gate answered before the entry ran. C1\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:126 - control: with the valid token, each stubbed path answers the stub's `[200, {\"stub\": path}]` and the unknown path answers 404 `{\"error\": \"Not found\"}`. Fails if the table was copied at import, and without it the zero count at :124 would prove nothing.\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:127 - control: the stubs were reached exactly once each, in request order.\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:129 - after `srv.bridge_token = \"\"`, all four answer 503 `{\"error\": \"Bridge token is not configured on the Engine\"}` even with the previously valid token. Fails if \"\" counts as a token or the check falls back to another token. C1\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:130 - the 503 requests added no stub calls (the record is still exactly the three valid-token calls). C1\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:132 - extra, not a clause: GET /internal/videos/resolve answers a plain 404 with no gate, so a gate applied to both methods would fail here.\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:138 - control: GET /fake answers 404 `{\"error\": \"Not found\"}` before the GET_ROUTES entry exists, so the later 200 can only come from the entry.\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:140 - after `router.GET_ROUTES[\"/fake\"]` is set (and only that is touched, no edit to handlers/similar.py), GET /fake?x=1 answers 200 `{\"fake\": True, \"path\": \"/fake?x=1\"}`. The raw path, query included, shows the entry answered this request. A table bound or copied at import still answers 404. C2\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:142 - the entry was called exactly once, with `type(handler) is SimilarHandler` and with `server` being the SimilarServer instance itself, which carries \"served through the real SimilarHandler\". C2\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:144 - extra, not a clause: GET /fake/ still answers 404 after the entry is set, so matching is exact-path and a prefix match would fail.\ntests/tmp/test_58_engine_routing_out_of_similar_phase1.py:145 - extra, not a clause: POST /fake still answers 404, so a GET_ROUTES entry serves GET only and a table that ignores the method would fail.\n</assertions>\n\n<probes>\nProbe 1. I wrote tests/tmp/test_probe_58_seam.py, which starts an Engine child against the current (pre-router) code: `server.SimilarServer((\"127.0.0.1\", 0), SimilarHandler, **dict.fromkeys(params[3:]))` with `srv.bridge_token = \"tok-abc\"`. I ran it with ValidateTests [\"tests/tmp/test_probe_58_seam.py\", \"-s\"]. It printed:\n- ENGINE_PY exists: True. Child rc 0. `importlib.util.find_spec(\"router\")` is None, so no `router` module exists yet and nothing in the Engine env collides with that name.\n- env ENGINE_BRIDGE_TOKEN is null, so `srv.bridge_token` defaults to \"\" in the child. That is why the test sets it explicitly; left alone, every request would get the 503.\n- srv.engine_ingest_mode is None.\n- POST /internal/no-such-route with no token: [401, {\"error\": \"Unauthorized\"}]. With token \"tok-ab\": [401, {\"error\": \"Unauthorized\"}]. With the valid token: [404, {\"error\": \"Not found\"}].\n- POST /internal/events/ingest with the valid token: [501, {\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": null}].\n- GET /internal/videos/resolve with the valid token: [404, {\"error\": \"Not found\"}]. GET /fake: [404, {\"error\": \"Not found\"}].\n- after `srv.bridge_token = \"\"`, POST /internal/translate: [503, {\"error\": \"Bridge token is not configured on the Engine\"}].\n- stderr: `WARNING:root:[bridge.auth] rejected ... from ip=127.0.0.1` and `ERROR:root:[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting ...`.\n\nProbe 2. The same probe file, rewritten to load the checkpoint module and run its own PRELUDE (with only `import router\\n` removed) plus a flow that passes json.dumps(STUBBED) as argv. Same ValidateTests command. It printed:\n- rc 0, and argv arrived as the JSON list.\n- ingest_mode [501, {..., \"mode\": null}]; missing [401, Unauthorized]; near_miss (TOKEN[:-1]) [401, Unauthorized]; get_internal [404, Not found]; GET /fake [404]; GET /fake/ [404]; POST /fake [404]; unset [503, configured-token body].\n- `send` to a refused port returned [null, \"ConnectionRefusedError(111, 'Connection refused')\"], so a dropped connection reads as a value in the report rather than crashing the child.\n- the unmodified FAKE_CHILD exits 1 with `ModuleNotFoundError: No module named 'router'`, the expected pre-phase red.\n\nNot observed, and not observable until router.py exists: that replacing `router.POST_ROUTES[...]` or `router.GET_ROUTES[\"/fake\"]` changes dispatch, and the post-phase values at :126, :127, :140 and :142 (the stub's 200, the call records, handler/server identity). These are predictions from the plan's route_get/route_post draft, which looks each table up per request and calls `route(handler, handler.server)`. The phase's own validate_tests run of this file is what confirms them.\n\nCleanup. The probe is spent. I have no delete tool, so I overwrote tests/tmp/test_probe_58_seam.py with a single comment line (it collects no tests). That file should be deleted; it is outside the one file this step names.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_58_engine_routing_out_of_similar_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:127 \u2014 POST to /internal/videos/resolve, /internal/translate, /internal/events/ingest and /internal/no-such-route with no X-Bridge-Token, after the three POST_ROUTES entries were replaced by recording stubs, each answers [401, {\"error\": \"Unauthorized\"}]</assertion>\n<expected>{path: [401, {\"error\": \"Unauthorized\"}] for all four paths}. The run showed this, and the line passed against today's gate.</expected>\n<wrong_implementation>A route_post that looks up POST_ROUTES before it runs the gate reads [200, {\"stub\": path}] for the three stubbed paths. A gate that only covers paths in the table reads [404, {\"error\": \"Not found\"}] for /internal/no-such-route.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:129 \u2014 the same four POSTs carrying a near-miss token (the real token less its last character) each answer [401, {\"error\": \"Unauthorized\"}]</assertion>\n<expected>{path: [401, {\"error\": \"Unauthorized\"}] for all four paths}. Observed passing in the run.</expected>\n<wrong_implementation>A startswith or containment compare in place of hmac.compare_digest accepts \"router-test-toke\" and reads the stub's [200, {\"stub\": path}], or 404 for the unknown path.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:130 \u2014 the stubs recorded no call across the missing-token and near-miss requests</assertion>\n<expected>[] (observed). Lines 132-133 arm it: with the valid token every stub is reached.</expected>\n<wrong_implementation>A gate that writes the 401 but still falls through to the table entry (a missing return after a False bridge_authorized) records every stubbed path here, while the status lines could still read 401 first.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:132 \u2014 with the valid token, the three stubbed paths answer the stub's [200, {\"stub\": path}] and /internal/no-such-route answers [404, {\"error\": \"Not found\"}]</assertion>\n<expected>{\"/internal/videos/resolve\": [200, {\"stub\": \"/internal/videos/resolve\"}], \"/internal/translate\": [200, {\"stub\": \"/internal/translate\"}], \"/internal/events/ingest\": [200, {\"stub\": \"/internal/events/ingest\"}], \"/internal/no-such-route\": [404, {\"error\": \"Not found\"}]}. The stub response shape [200, {\"stub\": path}] came from a probe run through a real SimilarHandler. The 404 body for the unknown path was observed in this run.</expected>\n<wrong_implementation>Today's code, observed in this run: it dispatches through SimilarHandler's own if-chain instead of POST_ROUTES and reads [400, {\"error\": \"Missing video_id or uuid\"}], [400, {\"error\": \"Missing id or host\"}] and [501, {... \"mode\": None}]. A table copied or bound at import reads the same.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:133 \u2014 the stubs were reached exactly once each, in request order</assertion>\n<expected>[\"/internal/videos/resolve\", \"/internal/translate\", \"/internal/events/ingest\"] (the recording shape was observed in the probe as calls == [\"/stubbed\"])</expected>\n<wrong_implementation>Dispatch that bypasses the table records [], the current state. A route_post that calls the entry twice, or calls it for rejected requests too, records extra entries.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:135 \u2014 after srv.bridge_token = \"\", the four POSTs with the formerly valid token each answer [503, {\"error\": \"Bridge token is not configured on the Engine\"}]</assertion>\n<expected>{path: [503, {\"error\": \"Bridge token is not configured on the Engine\"}] for all four paths}. The probe run observed this body for a known path and for an unknown path. This test does not reach line 135 yet, because it stops at line 132.</expected>\n<wrong_implementation>A gate that falls back to ENGINE_BRIDGE_TOKEN when the attribute is falsy (`server.bridge_token or ENGINE_BRIDGE_TOKEN`; the env value is \"\") still reads 503. One that treats \"\" as a token reads 401. One that skips the check when unset reads the stub's 200, or 404 for the unknown path.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:136 \u2014 the 503 requests added no stub call (the record is still exactly STUBBED)</assertion>\n<expected>[\"/internal/videos/resolve\", \"/internal/translate\", \"/internal/events/ingest\"]</expected>\n<wrong_implementation>An unset-token branch that writes the 503 but falls through to the entry appends the three stubbed paths again: six entries.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:146 \u2014 after router.GET_ROUTES[\"/fake\"] = fake, GET /fake?x=1 answers the entry's [200, {\"fake\": True, \"path\": \"/fake?x=1\"}]</assertion>\n<expected>[200, {\"fake\": True, \"path\": \"/fake?x=1\"}]. Observed in the probe, where the same function was driven from a real SimilarHandler; handler.path keeps the query string.</expected>\n<wrong_implementation>Today's code, observed in this run: SimilarHandler's own _dispatch_get never consults a table, so it reads [404, {\"error\": \"Not found\"}]. A route_get that binds or copies GET_ROUTES at import reads the same 404. A lookup keyed on the raw path, query included, misses \"/fake\" and also reads 404.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:148 \u2014 the entry was called exactly once, with type(handler) is SimilarHandler and server is the running SimilarServer</assertion>\n<expected>[{\"handler_is_similar\": True, \"server_is_srv\": True}]. Observed in the probe, with isinstance against a SimilarHandler subclass; here the server is built with SimilarHandler itself.</expected>\n<wrong_implementation>A router that calls entries with a wrapper or adapter object, or with the module-level default server, reads False in the matching field. Calling the entry for /fake/ or for POST adds a second record. Today nothing calls it, so the record reads [].</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, before the rewrite, so it was rewritten. C1's positive half, that the POST_ROUTES entry is what runs past the gate, sat only in assertions labelled as controls, and the run never reached them. Lines 132-133 now carry C1 alongside 127/129/130/135/136. Every docstring bullet has an assertion: 501 at :125, 401 missing at :127, 401 near-miss at :129, no calls at :130, valid reaches stubs at :132-133, 503 at :135-136, GET /internal 404 at :138, /fake 404 before at :144, 200 after at :146, handler/server at :148, /fake/ and POST 404 at :150-151. C2's \"no edit to handlers/similar.py\" is structural: the test adds only a GET_ROUTES entry and never touches similar.py. Now no.\n2. Absence only: no. The empty call record at :130 is armed by :132-133, the stubs reached with the valid token. The 404 for /fake before the entry (:144) is armed by the 200 after it (:146). The 404s for /fake/ and POST (:150-151) come after :146 proved the entry serves GET /fake.\n3. Echoed literal: no. The stub and fake bodies are the test's own, but what is judged is whether the router called them at all. Deleting route_post's `route = POST_ROUTES.get(url.path); route(handler, handler.server)` turns :132 red. Deleting route_get's `GET_ROUTES.get(url.path)` call turns :146 red. Deleting route_post's gate line (`if url.path.startswith(\"/internal/\") and not bridge_authorized(handler): return`) turns :127 red.\n4. One value: no. The gate is read at four paths (three known, one unknown), under three token states (missing, near-miss, unset) plus the valid control. The fake route is read at the exact path, the trailing-slash variant and the other method.\n5. The double: the only shims are router table entries, which the plan names as the one allowed shim. The children also bind a `types.SimpleNamespace(GET_ROUTES={}, POST_ROUTES={})` when `import router` raises ModuleNotFoundError for exactly \"router\". This is not a stand-in for an owned module on the request path. Nothing in production reads it: SimilarHandler dispatches with or without it. It exists so the pre-phase run reaches the judging assertions instead of dying on an import. Once router.py exists the except branch is dead, and no judging assertion can pass through it, since the stubs and /fake are never served. Any other ImportError re-raises.\n6. It collects: yes. The `--collect-only` summary printed \"no tests\", but the real run's pytest header reads \"collected 2 items\", and both tests ran. Every name in the children binds: http.client, inspect, json, sys, threading, types, server, router (or the stand-in), SimilarHandler, respond_json. srv.bridge_token, srv.server_address, shutdown and server_close all exist on SimilarServer, as the run showed.\n7. Observed, not predicted: yes, after the probe. tests/tmp/probe_58_shapes.py drove a real SimilarServer and SimilarHandler and observed:\n- the respond_json response shape [200, {\"fake\": true, \"path\": \"/fake?x=1\"}], with handler.path keeping the query;\n- the stub shape and its call record;\n- the seen record with server_is_srv true;\n- the 503 body for a known path and an unknown path after bridge_token = \"\";\n- 404 for GET /internal/videos/resolve and for POST /fake;\n- the real handlers' answers to valid-token POSTs.\nThe 401 bodies, the 501 body with mode None and the 404 for the unknown path were observed passing in the checkpoint run itself. One residual prediction: :148 uses `type(handler) is SimilarHandler`. The probe used isinstance against a subclass, and here the server is constructed with SimilarHandler itself. I could not delete the probe file because I have no delete tool, so tests/tmp/probe_58_shapes.py still needs removing. It is not test_*-named.\n8. Red, not green: yes, red. ValidateTests reported \"2 failed\", \"[exit status 1]\".\n9. Red for the right reason: yes, after the rewrite. The first run failed only on the CONTROL at :112, `assert run.returncode == 0`, with \"ModuleNotFoundError: No module named 'router'\". That measured nothing, so the child now tolerates the missing module as described in 5. Current run:\n- test_internal_posts\u2026: passes :125, :127, :129 and :130, then fails at line 132, `assert report[\"valid\"] == {...}  # C1`. The diff reads `{'/internal/translate': [400, {'error': 'Missing id or host'}]} != {... [200, {'stub': '/internal/translate'}]}`, `{'/internal/videos/resolve': [400, {'error': 'Missing video_id or uuid'}]} != ...` and `{'/internal/events/ingest': [501, {...'mode': None}]} != ...`. That is SimilarHandler's own dispatch answering instead of a POST_ROUTES entry: the phase is not built.\n- test_a_route_added\u2026: passes the :144 control and fails at line 146, `assert report[\"after\"] == [200, {\"fake\": True, \"path\": \"/fake?x=1\"}]  # C2`, with `assert [404, {'error': 'Not found'}] == [200, ...]`. No GET_ROUTES table is consulted yet.\nNeither failure is a control.\n10. Observed expected output: yes. Lines 127/129/130 match what the run printed, since they passed. The expected values at 132/146 match the shapes the probe printed through a real SimilarHandler, and the run's failure diffs show the current values as the wrong-implementation readings. Lines 135/136/148 are not reached by this run; their values come from the probe output quoted in 7. Nothing in either run contradicted an `expected` column.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/server/api/router.py` (new)\n- The module docstring is now the full Engine route list. Each entry gives the method and gate, and it adds the two routes the old similar.py docstring left out: `/internal/dislikes/centroids` and `/api/v1/search/videos`.\n- `SIMILAR_POST_ROUTES` moved here from similar.py. The two similar POST entries in `POST_ROUTES` are built from it with `dict.fromkeys`.\n- `GET_ROUTES` and `POST_ROUTES` are plain module dicts mapping an exact path to `callable(handler, server)`. They are looked up on every request.\n  - The three client-read handlers and the two translate handlers go into the table as they are.\n  - Thin adapters cover the rest: `_similar_post`, `_search`, `_video`, `_video_refresh`, and `_events_ingest`, which now holds the 501 ingest-mode check with its `mode` field.\n- `handle_health` and `handle_channels` are the old inline `/api/health` and `/api/channels` blocks, moved over unchanged.\n- `_extract_video_id_from_similar_path` moved here unchanged.\n- `bridge_authorized(handler)` is the old `_bridge_authorized` with `self` replaced by `handler`. The token fallback, the stripped `X-Bridge-Token`, `hmac.compare_digest`, the 503/401 bodies and the root-logger `[bridge.auth]` lines are all the same.\n- `route_post(handler)`: the `/internal/` bridge gate, then a `POST_ROUTES` lookup, then 404.\n- `route_get(handler)`: the `/api/` rate-limit gate (429), then a `GET_ROUTES` lookup, then the `/videos/{id}/similar` pattern, then 404. The pattern keeps its own limiter, then `setdefault(\"id\")`, then `_handle_similar`.\n- The one hard-coded pattern route carries a `rat-tail:` comment naming its ceiling and upgrade path.\n- The router never imports `handlers.similar`, so there is no import cycle.\n\n### `engine/server/api/http_utils.py`\n- Added `parse_int` and `parse_non_negative_int`, moved byte-for-byte from similar.py's `_parse_int` and `_parse_non_negative_int`. The router's channels code and similar.py's search and similar code share them.\n\n### `engine/server/api/handlers/similar.py`\n- **Docstring:** the module docstring now describes only similarity (recommendations, similar, feeds, search) and points to `api/router.py` for the route list.\n- **Imports removed:** `hmac`, `fetch_channels`, `BRIDGE_TOKEN_HEADER`, `ENGINE_BRIDGE_TOKEN`, and the `handlers.internal_events`, `handlers.internal_client_reads`, `handlers.internal_translate` and `handlers.video` imports.\n- **Imports added:** `from router import SIMILAR_POST_ROUTES, route_get, route_post`, plus `parse_int` and `parse_non_negative_int` from `http_utils`. `_recommendations_likes_payload_error` reads the imported `SIMILAR_POST_ROUTES`.\n- **Methods removed:** `_bridge_authorized`, `_dispatch_post` and `_dispatch_get`. `_serve_post` and `_serve_get` keep the statement-deadline / interrupted-503 wrapper and now call `route_post(self)` and `route_get(self)` inside it. The `do_GET`/`do_POST` and `_serve_*` docstrings were reworded to say they hand the request to the router.\n- **Renames:** four call sites renamed to the public names (`_handle_search` limit and page, `_handle_similar` limit and seed).\n- **Helpers removed:** `_parse_int`, `_parse_non_negative_int` and `_extract_video_id_from_similar_path`. `_parse_bool`, `_parse_include_nsfw` and `FEED_MODES` stay.\n\n### `tests/tmp/test_router_bridge_auth.py`, `tests/tmp/test_router_fake_route.py`\n- Not created. The gated checkpoint `tests/tmp/test_58_engine_routing_out_of_similar_phase1.py` already holds both planned tests (bridge gate and fake route), so writing them again would only duplicate it.\n\n### Verification\n- I did not run the checkpoint.\n- A throwaway import probe under the Engine interpreter showed:\n  - `server`, `handlers.similar` and `router` import with no cycle;\n  - both tables hold the expected paths;\n  - `similar.SIMILAR_POST_ROUTES is router.SIMILAR_POST_ROUTES`;\n  - `_dispatch_get` is gone;\n  - `parse_int(\" 5\") == 5` and `parse_non_negative_int(\"-1\") is None`.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_router_import.py \u2014 a throwaway import probe I wrote and ran through ValidateTests. I have no tool that deletes files, so it is still there: please delete it. It is named `probe_*`, not `test_*`, so the default pytest collection should skip it.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nengine/server/api/handlers/similar.py \u2014 merged the identical `_serve_post` and `_serve_get` into one `_serve(route)` method. `do_POST` and `do_GET` now call `self._run_request(lambda: self._serve(route_post))` and `lambda: self._serve(route_get)`, the same lambda style `do_OPTIONS` already uses. The statement deadline, the interrupted-503 and the re-raise of other errors are unchanged. Nothing in engine/ or tests/ referenced the two old method names.\nengine/server/api/router.py \u2014 `_events_ingest` now reads `getattr(server, \"engine_ingest_mode\", \"bridge\")` once into `mode` and uses it for both the check and the 501 body's `mode` field, instead of calling getattr twice.\n</refactors>\n\n<left_out>\nrouter.py `_extract_video_id_from_similar_path`: the `startswith`/`endswith` check looks redundant next to the segment check, but it isn't. `strip(\"/\")` would let `/videos/x/similar/` through, and the endswith check is what rejects it. Removing it would change behaviour, so I left it.\nrouter.py `route_get`: the two identical 429 blocks (the `/api/` gate and the pattern route's own limiter) stay as they are. A helper would add about as much code as it removes, and the pattern block is the one the rat-tail comment marks for replacement with a matcher list later.\nsimilar.py `_recommendations_likes_payload_error`: its `path not in SIMILAR_POST_ROUTES` guard can never fire from the router now, because only SIMILAR_POST_ROUTES paths reach `_handle_similar_request`. I kept it because it is that function's own contract, and direct callers or tests may pass other paths.\nengine/server/README.md and handlers/__init__.py docstring: not touched. The plan's docs checklist left them to operator decision.\ntests/tmp/probe_router_import.py (outside the files named): I reused the earlier probe file for this pass's check instead of creating another one. I have no tool that deletes files, so it is still there: please delete it. It is named `probe_*`, so default pytest collection skips it.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nAn Engine-interpreter probe run through ValidateTests confirmed the refactored code. `SimilarHandler._serve` calls the route with the handler. An interrupted OperationalError gives `_respond_interrupted`, and a \"disk I/O error\" one is re-raised. `_serve_get` and `_serve_post` no longer exist. `_events_ingest` answers 501 with `mode: None` for `engine_ingest_mode=None`, and passes through to ingest for \"bridge\" and when the attribute is absent. I did not run the phase checkpoint or the suite.\n</observation>"
  },
  "requirements": "### Purpose\n\nThe Engine has one request handler class, `SimilarHandler` (`engine/server/api/handlers/similar.py`, 1275 lines), and it is built by `engine/server/api/server.py:123,469`. Route dispatch for every Engine path, and the `/internal/*` bridge-auth gate, live in that similarity module today. So every new route edits the similarity file: its imports, its docstring route list, and one of its `if` chains. The roadmap plans more routes (F1-M3 public REST API, F5-M3, F1-M4), a change to every unversioned route (F2-M3 API versioning), and changes at the gates (F7-M7 and F10-M7, rate limiting and service keys). This build moves routing into a router module of its own so those changes land in one routing place. It is a pure code move: no request may behave differently.\n\n### Current state (verified against the tree)\n\n- `SimilarHandler.do_POST` \u2192 `_run_request(_serve_post)` \u2192 `with self._statement_deadline(): self._dispatch_post()`. A `sqlite3.OperationalError` for which `is_interrupted_error` is true answers `_respond_interrupted()` (503 `{\"error\": \"Query time limit exceeded\"}` plus a `[statement.timeout]` warning). Any other error is re-raised. `do_GET` \u2192 `_serve_get` \u2192 `_dispatch_get` follows the same pattern.\n- `_bridge_authorized` (`similar.py:417-440`):\n  - The configured token is `getattr(self.server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)`. It falls back only when the attribute is absent, so an empty `server.bridge_token` counts as unset.\n  - When the token is falsy: `logging.error(\"[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting %s\", self.path)`, then 503 `{\"error\": \"Bridge token is not configured on the Engine\"}`.\n  - Otherwise the presented token is `self.headers.get(BRIDGE_TOKEN_HEADER, \"\").strip()`. When it is empty or fails `hmac.compare_digest(presented, configured)`: `logging.warning(\"[bridge.auth] rejected %s from ip=%s\", self.path, self._get_client_ip())`, then 401 `{\"error\": \"Unauthorized\"}`.\n  - `self.path` is the raw request path, including any query string.\n- `_dispatch_post` (`similar.py:442-478`) uses `url = urlparse(self.path)` and matches exactly on `url.path`, in this order:\n  1. When `url.path.startswith(\"/internal/\")` and bridge auth fails, return. This covers unknown `/internal/` paths too, so they get 401 or 503, never 404.\n  2. A path in `SIMILAR_POST_ROUTES` (`/recommendations`, `/videos/similar`) \u2192 `self._handle_similar_request(method=\"POST\")`, which runs its own rate-limit check (429) itself.\n  3. `/internal/videos/resolve` \u2192 `handle_internal_video_resolve(self, self.server)`.\n  4. `/internal/videos/metadata` \u2192 `handle_internal_videos_metadata(self, self.server)`.\n  5. `/internal/dislikes/centroids` \u2192 `handle_internal_dislike_centroids(self, self.server)`.\n  6. `/internal/translate` \u2192 `handle_internal_translate(self, self.server)`.\n  7. `/internal/translate/enqueue` \u2192 `handle_internal_translate_enqueue(self, self.server)`.\n  8. `/internal/events/ingest`: when `getattr(self.server, \"engine_ingest_mode\", \"bridge\") != \"bridge\"`, answer 501 `{\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": <that mode>}`. Otherwise call `handle_internal_events_ingest(self, self.server)`.\n  9. Anything else \u2192 404 `{\"error\": \"Not found\"}`.\n- `_dispatch_get` (`similar.py:494-562`), in this order:\n  1. When `url.path.startswith(\"/api/\")` and `self._rate_limit_check(url.path)` fails \u2192 429 `{\"error\": \"Rate limit exceeded\"}`. This also applies to unknown `/api/` paths, before their 404.\n  2. `/api/health` \u2192 200 `{\"ok\": True, \"total\": server.embeddings_count, \"embeddingDim\": server.embeddings_dim}`, answered inline.\n  3. `params = parse_qs(url.query)`. `/api/channels` is answered inline:\n     - `limit = _parse_int(limit)`; when it is `<= 0` it becomes 100, then it is capped at 500;\n     - `offset = _parse_int(offset)`;\n     - `max_videos = _parse_non_negative_int(maxVideos)`;\n     - under `server.db_lock`, `fetch_channels(server.db, limit, offset, query=q or \"\", instance=instance or \"\", min_followers=_parse_int(minFollowers), min_videos=_parse_int(minVideos), max_videos, sort=sort or \"followers\", direction=dir or \"desc\")`;\n     - 200 `{\"generatedAt\": now_ms(), \"total\": total, \"rows\": rows}`.\n  4. `/api/v1/search/videos` \u2192 `self._handle_search(params)`.\n  5. `/api/video` \u2192 `handle_video_request(self, self.server, params)`.\n  6. `/api/video/refresh` \u2192 `handle_video_refresh_request(self, self.server, params)`.\n  7. `/videos/{id}/similar`, matched by `_extract_video_id_from_similar_path(url.path)` (exactly three segments, `videos`/<non-blank id>/`similar`): first its own `self._rate_limit_check(url.path)` (429 on failure, even though the path is not under `/api/`), then `params.setdefault(\"id\", [video_path_id])`, then `self._handle_similar(params)`.\n  8. Anything else \u2192 404 `{\"error\": \"Not found\"}`.\n- A GET to an `/internal/` path gets a plain 404, with no bridge auth. A POST to a GET-only path, or the other way round, gets 404. Routing ignores the query string, and a trailing slash does not match.\n- The module docstring (`similar.py:1-20`) is titled \"Similarity HTTP handler\" and lists the routes. It already omits `/internal/dislikes/centroids` and `/api/v1/search/videos`.\n- `SIMILAR_POST_ROUTES` is also read by `_recommendations_likes_payload_error` inside similar.py.\n- `_parse_int`, `_parse_non_negative_int` and `_extract_video_id_from_similar_path` are module-level helpers in similar.py. `_parse_int` and `_parse_non_negative_int` are also used by similarity and search code that stays.\n\n### Desired behaviour\n\n- **One router module** in the Engine's API package (`engine/server/api/`, beside or under `handlers/`; the design step picks the place) owns:\n  - the GET route table and the POST route table, each mapping an exact path to the callable that serves it, plus the GET `/videos/{id}/similar` pattern;\n  - the `/internal/*` bridge-auth gate on POST;\n  - the `/api/` rate-limit gate on GET;\n  - the events-ingest mode check (the 501);\n  - the 404 fallback.\n- **Router entry points.** The router exposes one GET entry point and one POST entry point, each taking the handler. Table values are callables with one consistent signature: either `(handler, server)` or the handler alone, chosen by the design step and used throughout. Handlers whose native signature differs (the video handlers take `params`, the similar methods take `method`/`params`) are wrapped by thin adapters so the tables stay uniform.\n- **Bridge auth** becomes a router function. It keeps:\n  - the same token source (`getattr(server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)`, the same fallback semantics);\n  - the same header (`BRIDGE_TOKEN_HEADER`, stripped);\n  - the same `hmac.compare_digest` compare;\n  - the same 503 and 401 bodies;\n  - the same `[bridge.auth]` log messages, levels and arguments: `self.path` and `handler._get_client_ip()`.\n- **Inline routes.** `/api/health` and `/api/channels` become handler functions of their own, beside the router or in a fitting handler module, so the router is a table. Their responses and parameter parsing stay byte-for-byte the same. They need the `_parse_int`/`_parse_non_negative_int` semantics, which similar.py's similarity code also uses; how they share them is the design step's choice.\n- **The `/videos/{id}/similar` rate-limit check** and the `params.setdefault(\"id\", ...)` stay in force, in the same order, before `_handle_similar` runs.\n- **`SimilarHandler` keeps:**\n  - its name, module and construction by `server.py`;\n  - `_run_request`, `_statement_deadline`, `_respond_interrupted`, `_serve_get`/`_serve_post` (the statement deadline and its 503 still wrap all routing, including the gates);\n  - `_get_client_ip`, `_get_full_url`, `log_request`, `log_message` and `do_OPTIONS`;\n  - `_rate_limit_check` and every similarity, feed and search method (`_handle_similar_request`, `_handle_similar`, `_handle_search`, and the rest).\n  \n  Its `do_GET`/`do_POST` path hands each request to the router's GET/POST entry point, in place of `_dispatch_get`/`_dispatch_post`.\n- **Adding a route** means one table entry, plus one import in the router, and no edit to similar.py.\n- **Docstrings.** The router module's docstring holds the full route list, including the two routes the old docstring omitted (`/internal/dislikes/centroids`, `/api/v1/search/videos`), and `/api/health` and `/api/channels`. similar.py's docstring describes only similarity: recommendations, similar, feeds and search.\n- **README.** The `engine/server/README.md` route list is left unchanged (operator decision). Its other references to `SimilarHandler._run_request` and `_parse_include_nsfw` in `api/handlers/similar.py` stay true and are not edited.\n\n### Behaviour that must be identical\n\nEvery request gets the same status, body, headers and log lines as today:\n- every route, on both methods;\n- the gate order (bridge auth before any POST `/internal/` route, including unknown ones; the `/api/` rate limit before any `/api/` GET, including unknown ones);\n- both 404s;\n- the 401 and 503 bridge bodies and their `[bridge.auth]` log lines;\n- the 429s, including the extra one on GET `/videos/{id}/similar`;\n- the 501 for ingest outside bridge mode, with its `mode` field;\n- the plain 404 for GET `/internal/*`;\n- the statement-timeout 503;\n- the `[request.start]`/`[request.end]` records and request id.\n\n### Acceptance criteria\n\n- similar.py no longer contains:\n  - a path-dispatch chain (`_dispatch_get`/`_dispatch_post` or an equivalent);\n  - the bridge-auth check or the `hmac`/`ENGINE_BRIDGE_TOKEN`/`BRIDGE_TOKEN_HEADER` use behind it;\n  - the `/api/health` or `/api/channels` handling;\n  - imports of `handlers.internal_events`, `handlers.internal_client_reads`, `handlers.internal_translate` or `handlers.video`.\n- One router module holds both route tables, the bridge-auth gate, the `/api/` rate-limit gate, the ingest-mode check and the 404 fallback.\n- **Bridge-auth test:**\n  - Every POST `/internal/*` path without a valid `X-Bridge-Token` (missing, or wrong) answers 401 `{\"error\": \"Unauthorized\"}` before its handler runs, and answers 503 `{\"error\": \"Bridge token is not configured on the Engine\"}` when the token is unset.\n  - A test covers one internal route of each kind (client reads: one of resolve, metadata or dislike centroids; translate: one of translate or enqueue; events ingest) plus an unknown `/internal/` path, which also gets 401 without a token.\n  - The test shows the handler did not run.\n- Every Engine route answers as before. That covers every route the README lists, plus `/api/health`, `/api/channels` and `/api/v1/search/videos`, which the README's list omits.\n- The existing Engine, video, similar, translate and ingest tests pass: `tests/active/test_similar.py`, `test_video.py`, `test_internal_translate.py`, `test_internal_events.py`, `test_internal_client_reads.py`, `test_random_cache.py`, `test_server.py` and `engine/server/api/tests/`. Only tests that called removed dispatch or auth methods directly are rewritten; no current test does.\n- A test adds a fake route through a router table entry alone, with no edit to similar.py, and it is served through the real `SimilarHandler`.\n- The route list lives in the router module's docstring, and similar.py's docstring describes only similarity.\n\n### Constraints\n\n- Smallest move that answers the issue. No new dependency (stdlib only). No router class hierarchy or registration framework: plain module-level dicts and functions. No change to `SimilarServer`.\n- Code moves without behaviour change. New code follows the style of the file it lands in: module docstring, one-line docstrings, `respond_json(handler, status, body)` and `getattr(server, ..., default)` idioms.\n- **Test environment.** pytest's own interpreter has no numpy, so it cannot import `handlers.similar` or `server.py`. Engine-level tests run in a child process under `ENGINE_PY` (from `tests/active/conftest.py`), with `sys.path` set to the Engine `api` paths, as `test_video.py`, `test_similar.py` and `test_internal_events.py` do. The new bridge-auth and fake-route tests follow that pattern, or exercise a real `SimilarServer` on an ephemeral port.\n- Test trees: active tests live in `tests/active`, the working tree for in-build tests is `tests/tmp`, finished feature tests are archived under `tests/archive`, plans go in `docs/project/plans`, and the project root is `/home/enduser/code/PeerTube-browser/.worktrees/58`.\n\n### Baseline suite state\n\nThe pre-build baseline run exited with code 0 (`variant: false`): the suite is green before the build. Any red test after the build is caused by the build.\n\n### Out of scope\n\n- Renaming `SimilarHandler` or `SimilarServer`, or moving similarity, feed or search methods out of the class.\n- API versioning (F2-M3), new routes, or any change to rate limiting, bridge auth semantics or error bodies.\n- Changing `_get_client_ip`, access logging, request-id handling or the statement deadline.\n- The fetch adapter (issue 53) and translate route internals (issues 54, 55).\n- Editing `engine/server/README.md`.",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6"
  ],
  "initial_solution": "### Approach\n\nAdd one new module, `engine/server/api/router.py`. It sits beside `server.py` and `http_utils.py` and holds routing for the whole Engine. It imports from `handlers/`, and `handlers/similar.py` imports its two entry points from it. The router never imports `handlers.similar`, so the dependency runs one way and there is no import cycle. The router also never needs the class, because every similarity call goes through the `handler` object it is given (`handler._handle_similar_request(...)`, `handler._handle_similar(...)`, `handler._handle_search(...)`, `handler._rate_limit_check(...)`).\n\n**What the router holds**\n\n- **Module docstring.** The full route list: every route the old docstring named, plus `/internal/dislikes/centroids` and `/api/v1/search/videos`, with `/api/health` and `/api/channels` kept. Each route is marked with its method and whether a gate covers it.\n- **Two plain dicts, `GET_ROUTES` and `POST_ROUTES`.** Each maps an exact path to a callable with the signature `(handler, server)`. I chose `(handler, server)` over the handler alone because five of the nine existing callees already have it: the three client-read handlers and the two translate handlers. Those go into the table as they are, with no adapter.\n- **`SIMILAR_POST_ROUTES`, moved here from similar.py.** The POST table builds its `/recommendations` and `/videos/similar` entries from it. similar.py imports it back for `_recommendations_likes_payload_error`, so the router stays the one owner of path strings and the router-to-similar import direction still holds.\n- **Thin named adapters, each with a one-line docstring.** Named functions match the file style; I did not use lambdas.\n  - The similar POST adapter calls `handler._handle_similar_request(method=\"POST\")`.\n  - The search, video and video-refresh adapters each read `parse_qs(urlparse(handler.path).query)` and call `handler._handle_search(params)`, `handle_video_request(handler, server, params)` and `handle_video_refresh_request(handler, server, params)`.\n  - The events-ingest adapter is where the 501 lives. It checks `getattr(server, \"engine_ingest_mode\", \"bridge\")` with the same body and `mode` field as today, and only then calls `handle_internal_events_ingest`.\n- **Two handler functions, `handle_health` and `handle_channels`, taking `(handler, server)`.** Their bodies are the old inline blocks moved over unchanged: the same parsing, the same clamp of `limit` to 100 when it is `<= 0` and to 500 at most, `fetch_channels` under `server.db_lock`, and the same response bodies. `/api/channels` re-parses the query from `handler.path`, which gives the same result the old shared `params` did.\n- **`_extract_video_id_from_similar_path`, moved here unchanged.** Only dispatch uses it.\n- **`bridge_authorized(handler)`.** This is `_bridge_authorized` moved over with only `self` changed to `handler` / `handler.server`:\n  - the same `getattr(server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)` fallback;\n  - the same stripped `BRIDGE_TOKEN_HEADER` and `hmac.compare_digest`;\n  - the same 503 and 401 bodies;\n  - the same `logging.error` / `logging.warning` calls on the root logger, with `handler.path` and `handler._get_client_ip()`.\n\n  I checked `logging_profiles.py`: neither the text nor the JSON formatter emits module, function or line, so moving the calls to another module leaves every log line byte-identical.\n- **`route_post(handler)`:**\n  1. Parse `handler.path`.\n  2. When the path starts with `/internal/`, run `bridge_authorized` and return if it fails. This covers unknown `/internal/` paths too, so they still get 401 or 503.\n  3. Look the exact path up in `POST_ROUTES` and call the entry with `(handler, handler.server)`.\n  4. Otherwise answer 404 `{\"error\": \"Not found\"}`.\n- **`route_get(handler)`:**\n  1. Parse the path.\n  2. Apply the `/api/` prefix rate-limit gate through `handler._rate_limit_check(path)`, answering 429 on failure, including for unknown `/api/` paths.\n  3. Exact lookup in `GET_ROUTES`.\n  4. Otherwise try the `/videos/{id}/similar` pattern: its own rate-limit check (429), then `params.setdefault(\"id\", [video_id])`, then `handler._handle_similar(params)`, in that order.\n  5. Otherwise 404.\n\n  GET `/internal/*` has no table entry and no gate, so it still gets the plain 404. Wrong-method requests miss their table and get 404. Routing uses `urlparse(...).path`, so the query string is still ignored, and a trailing slash still fails the exact match.\n\n**Shared integer parsing.** `_parse_int` and `_parse_non_negative_int` move unchanged to `http_utils.py` as public `parse_int` and `parse_non_negative_int`. The router imports them from there, and similar.py imports them and renames its handful of call sites (search, similar, channels code that stays). One definition serves both modules.\n\n**What changes in similar.py**\n\n- Removed:\n  - `_dispatch_get`, `_dispatch_post` and `_bridge_authorized`;\n  - the health and channels blocks;\n  - `_extract_video_id_from_similar_path` and the two parse helpers;\n  - the `hmac` import, `ENGINE_BRIDGE_TOKEN` and `BRIDGE_TOKEN_HEADER`;\n  - `fetch_channels`;\n  - the four `handlers.internal_*` / `handlers.video` imports.\n- `_serve_get` and `_serve_post` keep their deadline / interrupted-503 wrapper exactly as now and call `route_get(self)` and `route_post(self)` inside it. So the statement deadline still wraps the gates, and `_run_request` still owns the `[request.start]` / `[request.end]` records and the request id. Nothing else in the class changes.\n- The `do_GET` / `do_POST` docstrings are reworded to say \"hand the request to the router\".\n- The module docstring is rewritten to describe only recommendations, similar, feeds and search, and points to `router.py` for the route list.\n- `urlparse` and `parse_qs` stay, because `_handle_similar_request` still uses them. `now_ms` stays because feeds use it.\n\n### How each requirement is met\n\n- **One router module** holds both tables, the `/videos/{id}/similar` pattern, the bridge gate, the `/api/` rate-limit gate, the ingest-mode 501 and both 404s.\n- **Entry points.** `route_get(handler)` and `route_post(handler)`; every table value has the signature `(handler, server)`.\n- **Bridge auth** keeps its token source, header, compare, bodies and log calls exactly.\n- **Inline routes** become `handle_health` and `handle_channels` with identical behaviour.\n- **The `/videos/{id}/similar` rate-limit check and `setdefault`** run in the same order.\n- **`SimilarHandler`** keeps its name, module, construction by `server.py`, wrapper, logging, OPTIONS, `_rate_limit_check` and every similarity, feed and search method. `SimilarServer` and `server.py` are not touched.\n- **Adding a route** means one dict entry plus one import in `router.py`.\n- **README** is not edited. Its references to `SimilarHandler._run_request` and `_parse_include_nsfw` stay true, since neither moves.\n\n**Tests.** Both new tests go in `tests/tmp`. Each runs a child under `ENGINE_PY` with the Engine `api` paths on `sys.path`, starting a real `SimilarServer` with the real `SimilarHandler` on an ephemeral port, the way `test_video.py` does.\n\n- **Bridge-auth test.** It swaps recording stubs into `POST_ROUTES` for `/internal/videos/resolve`, `/internal/translate` and `/internal/events/ingest`, then sends POSTs to those three plus an unknown `/internal/` path.\n  - With no token and with a wrong token: 401 `{\"error\": \"Unauthorized\"}` for all four.\n  - With `srv.bridge_token = \"\"`: 503 with the configured-token body.\n  - Each stub records zero calls.\n  - A control request with the valid token shows the stub does get called. That proves the stub is wired in, so the zero counts actually mean something.\n- **Fake-route test.** It adds `GET_ROUTES[\"/fake\"]` with a function that answers through `respond_json`, then checks the response arrives through the real handler.\n\nThe existing suites listed in the acceptance criteria run unchanged. Nothing calls the removed methods directly; I checked the tree, and the only `similar.` uses in tests are `FEED_MODES`, `DEFAULT_CLIENT_LIKES_MAX`, `_parse_client_likes`, `_handle_similar` and `_handle_similar_request`, which all stay.\n\n### Alternatives considered\n\n- **Keep the routing methods on a mixin or base class that `SimilarHandler` inherits.** Rejected: the constraints forbid a class hierarchy, and a mixin still couples routing to the handler class.\n- **Use a decorator or registration framework, or a router class.** Rejected by the constraints. A plain dict already gives a one-line route addition.\n- **Have table callables take the handler alone.** Rejected: all five client-read and translate handlers would then need adapters, where with `(handler, server)` none of them do.\n- **Import the parse helpers from similar.py into the router.** Rejected: similar.py imports the router, so this would create a cycle.\n- **Duplicate the parse helpers in the router.** Rejected: two copies of the clamping rules would drift apart.\n- **Put the router in `handlers/router.py`.** Workable, but `handlers/` holds endpoint handlers. Dispatch is cross-cutting, like `http_utils` and `request_context`, so it sits beside them.\n- **Put health and channels in a new `handlers/catalog.py`.** Rejected for now as one more file holding two small functions. Living beside the router is allowed by the requirements, and they can move out when they grow.\n- **Run the ingest-mode check as a path-keyed gate in `route_post`.** Rejected: it applies to one route, so it belongs in that route's adapter, which still sits inside the router.\n- **Leave `SIMILAR_POST_ROUTES` in similar.py and write the two paths out again in the router.** Rejected: that is a duplicate source of path truth.\n\n### Gotchas and risks\n\n- **Import cycle.** `router.py` must never import `handlers.similar`, at module level or anywhere else. A future contributor who wants a similarity helper in the router would bring the cycle back.\n- **Table entries hold function references.** Patching `handlers.internal_translate.handle_internal_translate` after import does not change what gets dispatched. Tests must patch the table entry instead, and the bridge-auth test does that. Today's tests patch inner functions (`video.fetch_instance_json`, `fetch_bounded`), and those are unaffected.\n- **The tables must stay plain mutable dicts, looked up per request.** If they are frozen or copied into a closure, the fake-route test breaks.\n- **Re-parsing the query in adapters.** `parse_qs` with default arguments does not raise, so moving the parse from before the channels block into each adapter cannot change an outcome. The cost is negligible.\n- **Order inside the tables.** Order no longer matters, because exact paths cannot overlap and the one pattern route is tried only after an exact miss, as it is today.\n- **Docstring drift.** `engine/server/README.md` keeps its incomplete route list by operator decision. `router.py` becomes the route list that is correct.\n\n### Tradeoffs the operator is accepting\n\n- **Deliberate simplification: one hard-coded pattern route.** `/videos/{id}/similar` stays special-cased in `route_get` rather than going through a general pattern table. That limit is reached when a second parameterised path appears. The upgrade then is a small ordered list of `(matcher, callable)` pairs tried after the exact lookup, which fits F2-M3 versioning.\n- **Gates are prefix checks hard-coded in the entry points** (`/internal/` on POST, `/api/` on GET), not per-route flags. That matches today exactly. F7-M7 and F10-M7 will change them in that one place.\n- **`/api/health` and `/api/channels` live in `router.py`.** The router file therefore imports `fetch_channels` and `now_ms` and is not strictly a table.\n- **Renamed helpers.** `_parse_int` and `_parse_non_negative_int` become public `parse_int` and `parse_non_negative_int` in `http_utils.py`, and similar.py's call sites are renamed. No test references the old names.",
  "conflicts": "none",
  "impacts": "<impacts>\n<impact path=\"engine/server/api/router.py\" element=\"new module (whole file): docstring route list, GET_ROUTES, POST_ROUTES, SIMILAR_POST_ROUTES, adapters, handle_health, handle_channels, _extract_video_id_from_similar_path, bridge_authorized, route_get, route_post\">\n**What changes.** A new top-level module in the api dir. No file named `router*` exists anywhere in the tree, and none exists in the Engine pixi site-packages, so the top-level name `router` does not collide. It is imported as `from router import ...`, the same way `http_utils` and `server_config` are, because the api dir is on `sys.path` as a root.\n\n**What it must import.**\n- From the standard library: `hmac`, `logging` and `from urllib.parse import parse_qs, urlparse`.\n- `from data.channels import fetch_channels` and `from data.time import now_ms`.\n- `from http_utils import respond_json, parse_int, parse_non_negative_int`.\n- `from server_config import BRIDGE_TOKEN_HEADER, ENGINE_BRIDGE_TOKEN`. Both are defined at `server_config.py:500-501`, and the token is read from env at import time.\n- `handle_internal_events_ingest` from `handlers.internal_events`, the three `handle_internal_*` client reads from `handlers.internal_client_reads`, `handle_internal_translate` and `handle_internal_translate_enqueue` from `handlers.internal_translate`, and `handle_video_request` and `handle_video_refresh_request` from `handlers.video`.\n\nNone of these modules imports `handlers.similar`, so there is no cycle; I checked their import blocks. `handlers.internal_translate` imports `handlers.video`, which is fine.\n\n**Behaviour that must be reproduced exactly** (from `similar.py:417-562`):\n- **POST.**\n  - The `/internal/` prefix gate runs before every lookup, unknown internal paths included.\n  - `SIMILAR_POST_ROUTES` \u2192 `_handle_similar_request(method=\"POST\")`.\n  - The five internal routes.\n  - Events ingest: the 501 body is `{\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": getattr(server, \"engine_ingest_mode\", \"bridge\")}`.\n  - Anything else: 404 `{\"error\": \"Not found\"}`.\n- **GET.**\n  - The `/api/` prefix gate gives 429 `{\"error\": \"Rate limit exceeded\"}` before the lookup, unknown `/api/` paths included.\n  - `/api/health` answers `{\"ok\": True, \"total\": server.embeddings_count, \"embeddingDim\": server.embeddings_dim}`.\n  - `/api/channels` keeps the clamp `<=0 \u2192 100`, then `min(\u2026, 500)`; `offset`, `maxVideos`, `minFollowers` and `minVideos` keep their parsing; `fetch_channels` keeps its keyword args under `server.db_lock`; the response is `{\"generatedAt\": now_ms(), \"total\", \"rows\"}`.\n  - Search, `/api/video` and `/api/video/refresh` each get `parse_qs(url.query)`.\n  - Then the `/videos/{id}/similar` pattern: a second `_rate_limit_check(url.path)`, then `params.setdefault(\"id\", [video_id])`, then `_handle_similar(params)`.\n  - Anything else: 404.\n\n**What depends on it.**\n- `handlers/similar.py`: `_serve_get` / `_serve_post`, and `_recommendations_likes_payload_error` through `SIMILAR_POST_ROUTES`.\n- The two new tests in `tests/tmp`, which mutate `POST_ROUTES` and `GET_ROUTES`.\n- Every Engine HTTP test indirectly, because every request now flows through it.\n\n**Regression risk: HIGH.** This is the whole request surface.\n- **Ordering slips.**\n  - The bridge gate must run before the `SIMILAR_POST_ROUTES` lookup. Today it cannot matter, since those paths are not `/internal/`, but the gate must still come first.\n  - The `/api/` rate-limit gate must run before the exact lookup, so a 429 still lands on unknown `/api/` paths.\n  - In the pattern branch, rate-limit then `setdefault` then `_handle_similar`.\n- **Accidental drift.** `respond_json` here must be the `http_utils` one. Tests that patch `similar.respond_json` (test_similar.py:259, test_recommendations_likes_limit.py:55/85/105) only go through `_handle_similar_request`, which stays in similar.py, so they still capture its output.\n- **Tables must be read per request.** `route_get`/`route_post` must do `GET_ROUTES.get(path)` at call time, not bind entries at import, or the fake-route and stub tests break.\n- **Logging.** The bridge-auth `logging.error`/`logging.warning` must stay on the root logger (`logging.error(...)`, not `logging.getLogger(__name__)`) with the same format strings. `logging_profiles._classify_event` derives the `event` field from the `[bridge.auth]` message prefix, and `EngineJsonFormatter.format` (`logging_profiles.py:236-272`) never emits module, funcName or lineno. I confirmed that: moving modules keeps output identical, but only if the message text is unchanged.\n- **Return values.** The `handle_*` functions return `bool`, and the router must ignore it, as the old chain did.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"module docstring (lines 1-20)\">\n**What changes.** The docstring is rewritten to describe only recommendations, similar, feeds and search, and to point to `router.py` for the route list. Today it lists 11 routes; `/internal/dislikes/centroids` and `/api/v1/search/videos` are already missing from it.\n\n**What depends on it.** Nothing at runtime. `tests/active/test_frontend_feed_params.py:41,120` parses this file with `ast` to read `FEED_MODES`, and a docstring change is harmless to that.\n\n**Regression risk: none.** The acceptance criterion \"similarity module's docstring describes only similarity\" is checked against this text.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"imports block (lines 21-103)\">\n**What changes.**\n- **Removed:**\n  - `import hmac` (line 22, only used at 434);\n  - `from data.channels import fetch_channels` (36, only used at 518);\n  - `BRIDGE_TOKEN_HEADER` and `ENGINE_BRIDGE_TOKEN` from the `server_config` import (52, 58, only used at 424/433);\n  - the four `handlers.internal_*` / `handlers.video` imports (96-103).\n- **Added:**\n  - `from router import SIMILAR_POST_ROUTES, route_get, route_post`;\n  - `parse_int, parse_non_negative_int` added to the existing `from http_utils import ...` line (80).\n- **Stays:**\n  - `urlparse` and `parse_qs` (still used at 643/647 in `_handle_similar_request`);\n  - `now_ms` (still used at 622 in search and 908 in feeds);\n  - `sqlite3`, and `Callable` (used by `_run_request`).\n\n**What depends on it.**\n- `server.py:123` imports `SimilarHandler` from this module, so importing `similar` now transitively imports `router` and the internal handlers. That set of modules is the same as today, only reached through router.\n- Every child-process test that does `from handlers import similar` / `from handlers.similar import SimilarHandler`: test_video.py:166/202, test_similar.py:196/238/362/471/730/979, test_server.py:1405, engine/server/api/tests/test_recommendations_likes_limit.py:19 and tests/archive/... Every one of them already has the api dir on `sys.path` (it is required to import the `handlers` package), so `router` resolves.\n\n**Regression risk: medium.**\n- **Import cycle.** If router ever imports `handlers.similar`, it breaks. A partial-module error appears when `similar` is the first importer, which is the normal case through server.py.\n- **Unused-import or missed-import NameError.** For example, leaving `_parse_int` references without renaming. Grep after the edit for `_parse_int`, `_parse_non_negative_int`, `fetch_channels`, `hmac` and `ENGINE_BRIDGE_TOKEN`.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SIMILAR_POST_ROUTES constant (line 106) and its reader _recommendations_likes_payload_error (lines 230-267)\">\n**What changes.** The constant definition moves to `router.py`. similar.py imports it back, and `_recommendations_likes_payload_error` (line 234: `if path not in SIMILAR_POST_ROUTES`) stays unchanged and reads the imported name.\n\n**What depends on it.**\n- The likes-payload 400 contract for both `/recommendations` and `/videos/similar` (archive issue 05; README line 46).\n- engine/server/api/tests/test_recommendations_likes_limit.py, which calls `_handle_similar_request` with path `/recommendations`.\n- test_similar.py:238-267.\n\n**Regression risk: low.** It must stay a set with exactly the two paths. If someone writes the paths out in the router instead, they can drift.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._bridge_authorized (lines 417-440)\">\n**What changes.** The method is removed and moves to `router.bridge_authorized(handler)`, with `self` \u2192 `handler` and `self.server` \u2192 `handler.server`.\n\n**What depends on it.** Only `_dispatch_post` (line 445). No test calls it directly; grep of tests for `_bridge_authorized` found nothing.\n\n**Regression risk: medium.** The behaviours to preserve:\n- `getattr(server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)`. `SimilarServer.__init__` always sets `self.bridge_token = ENGINE_BRIDGE_TOKEN` (server.py:290), so the fallback only matters for stand-in servers.\n- A falsy token gives 503 plus `logging.error`.\n- An empty or mismatched presented token (`.strip()`, `hmac.compare_digest`) gives 401 plus `logging.warning` with `handler._get_client_ip()`.\n\nCallers outside the Engine depend on these bodies:\n- client/backend/lib/engine_api_client.py:14,37-47 sends `X-Bridge-Token`;\n- test_internal_translate.py:1071,1074 asserts `(401, {\"error\": \"Unauthorized\"})`;\n- the DEPLOYMENT.md \u00a73b and line 315 triage text relies on the `bridge.auth` log event.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._dispatch_post (lines 442-478) and _serve_post (407-415), do_POST docstring (403-405)\">\n**What changes.**\n- `_dispatch_post` is removed.\n- `_serve_post` keeps its try / `with self._statement_deadline():` / `except sqlite3.OperationalError` \u2192 `is_interrupted_error` \u2192 `_respond_interrupted()` wrapper, and calls `route_post(self)` inside it.\n- The `do_POST` docstring is reworded to \"hand the request to the router\".\n\n**What depends on it.**\n- Every POST: recommendations, videos/similar and all `/internal/*`.\n- The statement deadline must still wrap the bridge gate and the handler, so that a `sqlite3.OperationalError` interrupt raised inside a router-called handler is still turned into a 503.\n- `internal_events.py:9` imports `is_interrupted_error` and handles some of these interrupts itself; that is unchanged.\n\n**Regression risk: medium.** If `route_post` is called outside the `with` block, or catches `OperationalError` itself, the 503 `Query time limit exceeded` path changes.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._dispatch_get (lines 494-562) and _serve_get (484-492), do_GET docstring (480-482)\">\n**What changes.**\n- `_dispatch_get` is removed: the inline health and channels blocks, the shared `params = parse_qs(url.query)` at 509, and the pattern branch.\n- `_serve_get` keeps its wrapper and calls `route_get(self)`.\n- The `do_GET` docstring is reworded.\n\n**What depends on it.** Every GET:\n- `/api/health`, used as the readiness probe in conftest.py:192, test_random_cache.py:307/819/861, test_internal_translate.py:1056 and test_similar.py:437;\n- `/api/channels`, which the Client proxies (client/backend/server.py:93,102) and which test_server.py:471-474 exercises through the Client;\n- `/api/v1/search/videos`, `/api/video` and `/api/video/refresh` (test_video.py);\n- `/videos/{id}/similar` (test_video.py:80 `SIMILAR`, PERSIST_CHILD).\n\n**Regression risk: medium-high.** These are the call sites every Engine readiness check depends on. A broken `handle_health` makes every Engine-child fixture time out. Unknown GET paths, including GET `/internal/*`, must still give a plain 404 with no gate; test_video.py:631/659 rely on 404 `{\"error\": \"Not found\"}` for unrouted paths.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"module helpers _parse_int (1167-1173), _parse_non_negative_int (1191-1199), _extract_video_id_from_similar_path (1267-1275), and their remaining call sites\">\n**What changes.**\n- `_parse_int` and `_parse_non_negative_int` are removed and move to http_utils as `parse_int` and `parse_non_negative_int`.\n- `_extract_video_id_from_similar_path` is removed and moves to router.\n\n**Remaining call sites to rename.** Grep confirms there are exactly four:\n- `_handle_search` at 584 (`limit`) and 588 (`page`);\n- `_handle_similar` at 1035 (`limit`, default `str(self.server.default_limit)`) and 1062 (`seed` \u2192 `parse_non_negative_int`).\n\nThe plan's wording \"search, similar, channels code that stays\" is slightly off: the channels call sites at 511/515/516/524/525 move to `router.handle_channels`, they do not stay.\n\n**What stays.** `_parse_bool` (1176) and `_parse_include_nsfw` (1183) are not touched. README:50 and ADR-0007:17 cite `_parse_include_nsfw` in `api/handlers/similar.py`.\n\n**What depends on it.**\n- Search limit/page clamping.\n- Similar limit and seed parsing: the README:49 `seed` semantics are \"negative or non-integer \u2192 random draw\". This is `parse_non_negative_int` returning None.\n\nNo test references the old names; I grepped `_parse_int` in tests and the only hit is client/backend/server.py's own unrelated `_parse_int` (line 1316), which is not affected.\n\n**Regression risk: low-medium.** A missed rename raises a NameError at request time, not at import time, because the names are resolved lazily inside methods. A test run that does not hit search or seeded similar would not catch it.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler methods that stay and are now called by the router: _rate_limit_check (632-639), _handle_similar_request (641-699), _handle_similar (1033+), _handle_search (564-630), _get_client_ip (323-338)\">\n**What changes.** Nothing in their bodies, apart from the parse renames noted in the helpers entry. They become an implicit interface the router calls by name on the handler object.\n\n**What depends on it.** The router's `handler._rate_limit_check(path)`, `handler._handle_similar_request(method=\"POST\")`, `handler._handle_similar(params)`, `handler._handle_search(params)` and `handler._get_client_ip()`. Several tests call these directly on stubs:\n- test_similar.py:207 builds a stub with `rate_limiter`;\n- test_similar.py:265/388/500/1005;\n- test_recommendations_likes_limit.py.\n\n**Regression risk: low now, latent later.** The private, underscore-prefixed methods become a cross-module contract. A future rename in similar.py breaks the router with an AttributeError at request time, not at import.\n</impact>\n<impact path=\"engine/server/api/http_utils.py\" element=\"new public parse_int and parse_non_negative_int\">\n**What changes.** The two functions are added, moved unchanged from similar.py:1167-1173 and 1191-1199, including their docstrings.\n- `parse_int`: `int(value or \"0\")`, then 0 on ValueError, then `parsed if parsed > 0 else 0`.\n- `parse_non_negative_int`: None for None, blank, invalid or negative input.\n\nThe module currently imports only `json`, `deque`, `datetime`, `BaseHTTPRequestHandler`, `threading` and `Any`, and needs no new import. Its docstring style is one line `\"\"\"Handle/Parse ...\"\"\"`.\n\n**What depends on it.**\n- Imported by `router.py` (channels) and `handlers/similar.py` (search, similar).\n- Already imported by `server.py:124` (`RateLimiter`), internal_client_reads.py:10, internal_events.py:12, internal_translate.py:26, video.py:21.\n- tests/config.json lists `engine/server/api/http_utils.py` in the `test_similar.py` and `test_internal_client_reads.py` / `test_internal_translate.py` groups.\n\n**Regression risk: low.** It is additive. The semantics must be copied byte-for-byte; for example, `int(\" 5\")` works today because `int` strips whitespace, and that must not be \"improved\".\n\n**Name collision.** client/backend/lib/http_utils.py is a separate module in a different process tree. It does not collide, because the Engine never has `client/backend/lib` on its path.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"SimilarServer construction and handler import (lines 123, 249/283 engine_ingest_mode, 279 rate_limiter, 290 bridge_token, 469 SimilarHandler)\">\n**What changes.** Nothing; the plan leaves this file untouched.\n\n**What depends on it.** The router reads, through `handler.server`:\n- `bridge_token` (always set at 290);\n- `engine_ingest_mode` (set at 283);\n- `rate_limiter`, via `_rate_limit_check`;\n- `embeddings_count`, `embeddings_dim`, `db` and `db_lock`.\n\n`from handlers.similar import SimilarHandler` (123) now transitively loads `router`.\n\n**Regression risk: low.** Test children built the test_video.py way (`dict.fromkeys(signature params)`, test_video.py:170/229) pass `engine_ingest_mode=None` and `rate_limiter=None`. Under such a server, a real ingest request answers 501, because `None != \"bridge\"`, and rate limiting is off. The new bridge-auth test must replace the ingest table entry (which it plans to do), or its control request would see 501 instead of the stub. In such a child, `bridge_token` comes from the child's `ENGINE_BRIDGE_TOKEN` env, so the test should set `srv.bridge_token` explicitly.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"ENGINE_BRIDGE_TOKEN and BRIDGE_TOKEN_HEADER (lines 500-501)\">\n**What changes.** Nothing in this file. Its importer changes from handlers/similar.py to router.py; server.py:77 still imports `ENGINE_BRIDGE_TOKEN`.\n\n**What depends on it.** The bridge gate in router.\n\n**Regression risk: low.** It is read at import time from env, the same as today.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_events.py\" element=\"handle_internal_events_ingest(handler, server) (line 18)\">\n**What changes.** Nothing in the file. It is now referenced only from the router's events-ingest adapter, which holds the 501 ingest-mode check before calling it.\n\n**What depends on it.**\n- The Client's ingest bridge (client/backend/server.py:1254).\n- test_internal_events.py.\n\n**Regression risk: low-medium.** The 501 branch has no existing test; grepping tests/active for `Bridge ingest is disabled` and `501` found only unrelated hits. The planned bridge-auth test swaps this adapter out for a stub, so the 501 path stays unverified by tests. It is preserved only by careful copying.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"handle_internal_video_resolve, handle_internal_videos_metadata, handle_internal_dislike_centroids (lines 86, 130, 175)\">\n**What changes.** Nothing. They are put into `POST_ROUTES` directly, since their signature is already `(handler: Any, server: Any) -> bool`.\n\n**What depends on it.**\n- The Client's engine_api_client.py:100/120/141.\n- test_internal_client_reads.py, which imports the module directly.\n\n**Regression risk: low.** The table holds function references, so patching `reads.handle_internal_video_resolve` after import would no longer affect dispatch. No current test does that; they patch inner functions.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"handle_internal_translate, handle_internal_translate_enqueue (lines 277, 312)\">\n**What changes.** Nothing. They go into `POST_ROUTES` directly.\n\n**What depends on it.**\n- The Client's engine_api_client.py:186/207.\n- test_internal_translate.py, including the variant Engine at 1044-1074, which asserts 401 without a token and 404 `Video not found` with one. That end-to-end check covers both translate routes through the new router.\n\n**Regression risk: low.** Tests patch `fetch_bounded` and similar inner names, which are unaffected by table references.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"handle_video_request, handle_video_refresh_request (lines 463, 449)\">\n**What changes.** Nothing. They are called from router adapters as `(handler, server, params)`, with `params = parse_qs(urlparse(handler.path).query)`.\n\n**What depends on it.** test_video.py, both in-process and in its Engine children ANSWER_CHILD/PERSIST_CHILD. The children patch `video.fetch_instance_json` / `video.urlopen`, which are module attributes looked up at call time, so dispatch through router still sees the patches.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"engine/server/api/handlers/__init__.py\" element=\"package docstring (lines 1-9)\">\n**What changes.** Possibly nothing; the plan does not mention it. It describes `similar` as the \"main Engine read handler for recommendations and read endpoints\". After the move that is arguably still true, because `SimilarHandler` is still the one handler class. A one-line reword would avoid implying that it routes, and could mention that routing lives in `api/router.py`. I am flagging this for the operator rather than asserting an edit.\n\n**What depends on it.** Nothing at runtime.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"EngineJsonFormatter.format (lines 236-272), _classify_event\">\n**What changes.** Nothing.\n\n**What depends on it.** The bridge-auth log lines, when they are emitted from router.py. I verified that the formatter emits only ts, level, event, message, modes, request_id, context and traceback. It never emits record.module, funcName, lineno or name. So moving the `logging.error` / `logging.warning` calls to another module leaves output identical as long as they stay on the root logger with the same message text.\n\n**Regression risk: low.** The risk materialises only if the move switches to `logging.getLogger(__name__)`. Even then the formatter would not show the name, but handler and level configuration differ: `configure_engine_logging` sets only the root logger, so a named logger would still propagate. The risk stays small.\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"bridge_headers / X-Bridge-Token sender (lines 14, 37-47) and internal POST calls\">\n**What changes.** Nothing.\n\n**What depends on it.** It depends on the Engine keeping the header name `X-Bridge-Token`, the 401 and 503 semantics, and the exact `/internal/*` paths.\n\n**Regression risk: low.** This is an external consumer that would break if the router's POST table mistyped a path; the stub-backed new test catches only the three stubbed paths. `/internal/videos/metadata` and `/internal/dislikes/centroids` are exercised end-to-end only by existing Client\u2194Engine tests, such as test_server.py with `engine_client`, test_dislikes and test_blocks.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"Client proxy of /api/channels, /api/v1/search/videos, /api/video(/refresh) (lines 80, 93, 101-102) and its own /api/health (418)\">\n**What changes.** Nothing.\n\n**What depends on it.** It depends on the Engine answering those GET paths with the same bodies. Its own `/api/health` at 418 is the Client's, not the Engine's.\n\n**Regression risk: low.** It is covered by test_server.py:471-474, which runs `/api/channels` through the Client against the real Engine.\n</impact>\n<impact path=\"tests/tmp/test_bridge_auth_router.py\" element=\"new test (name to be chosen) - bridge-auth via router with stubbed POST_ROUTES\">\n**What changes.** A new file. `tests/tmp` is the configured working dir (tests/config.json \"working\") and holds only probe scripts today.\n\n**Shape.** The test should follow the test_video.py pattern:\n- import `ENGINE_PY` and `ROOT` from conftest;\n- run a child under `ENGINE_PY` with `SERVER_DIR` and `API_DIR` on `sys.path`;\n- build `server.SimilarServer((\"127.0.0.1\", 0), SimilarHandler, **{**dict.fromkeys(params[3:]), \"db\": conn, ...})`;\n- start `serve_forever` on a thread.\n\n**Details to get right.**\n- `db` must be a real connection, or some placeholder. Health and channels are not hit, so a placeholder may suffice; confirm that the constructor does not touch `db`.\n- Set `srv.bridge_token` explicitly for the valid-token control. The env token from conftest's `BRIDGE_TOKEN` (conftest.py:35/260) is an alternative.\n- `srv.bridge_token = \"\"` gives the 503 case.\n- The stubs must replace `router.POST_ROUTES[...]` entries, not the handler module functions.\n- The control request with a valid token must show that the stub was called once. For `/internal/events/ingest`, replacing the table entry bypasses the 501 adapter. That is acceptable here, but it means the 501 path stays untested.\n- The unknown `/internal/` path with a valid token should give 404. This is not in the plan but would be a cheap extra control.\n\n**What depends on it.** It is evidence for acceptance criterion 3.\n\n**Regression risk: medium for test validity.** If the child imports `router` before `handlers.similar`, it still works, since router does not import similar. If the stub is installed after the server thread starts, it is still fine, because lookup happens per request.\n</impact>\n<impact path=\"tests/tmp/test_router_fake_route.py\" element=\"new test (name to be chosen) - GET_ROUTES['/fake'] served through real SimilarHandler\">\n**What changes.** A new file with the same child-process pattern. It adds `router.GET_ROUTES[\"/fake\"] = fn` where `fn(handler, server)` calls `respond_json`, then GETs `/fake` and checks the status and body.\n\n**Details to get right.**\n- `/fake` is not under `/api/`, so no rate-limit gate applies.\n- A good control: GET `/fake` before adding the entry gives 404, which shows the entry is what serves it.\n\n**What depends on it.** It is evidence for acceptance criterion 5.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_video.py\" element=\"ANSWER_CHILD / PERSIST_CHILD Engine children (lines 159-267) and unrouted-404 controls (631, 659)\">\n**What changes.** Nothing. This is an existing suite that must pass unchanged. It serves `/api/video`, `/api/video/refresh` and `/videos/v1/similar` through the real handler, now via the router.\n\n**What depends on it.** It is the primary end-to-end check of GET routing: the adapters, the pattern route and its concurrency with the refresh.\n\n**Regression risk: low.** It catches GET table and pattern mistakes.\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"engine fixture route checks (line 437-439), direct-method children (196, 238-267, 362-388, 471-500, 730, 979-1005)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The direct calls to `_handle_similar_request` and `_handle_similar`, and the patching of `similar.respond_json`, `read_json_body`, `_parse_client_likes`, `_resolve_client_likes`, `set_request_client_likes` and `clear_request_context`. All of these names stay in similar.py.\n- line 982, which subclasses `SimilarHandler`; that is unaffected.\n\n**Regression risk: low.**\n\nThe test docstring line 30 (\"The `engine` fixture answers GET /api/health ...\") is unaffected. conftest.py:264's comment \"(similar.py `_handle_similar`)\" also stays true.\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"FEED_MODES child (1399-1414) and Client-through-Engine /api/channels (471-474)\">\n**What changes.** Nothing.\n\n**What depends on it.** It imports `handlers.similar` under the Engine interpreter, so the router import must resolve there. It does, because the api dir is on the path. It also reaches `/api/channels` through the Client.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"variant Engine bridge checks (lines 1044-1074)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is a real-Engine check that `/internal/translate` and `/internal/translate/enqueue` answer 401 without a token and reach their handler with one. That gives the router independent coverage of the bridge gate on two routes.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_frontend_feed_params.py\" element=\"AST read of FEED_MODES from similar.py (lines 41, 120)\">\n**What changes.** Nothing.\n\n**What depends on it.** `FEED_MODES` must remain a module-level tuple literal assignment in `handlers/similar.py`. The plan keeps it there; it must not be moved alongside the routing code.\n\n**Regression risk: low.** It is listed because a broader-than-planned cleanup of similar.py's top section would break it silently.\n</impact>\n<impact path=\"engine/server/api/tests/test_recommendations_likes_limit.py\" element=\"direct _handle_similar_request tests with patched similar.respond_json\">\n**What changes.** Nothing.\n\n**What depends on it.** `similar.SIMILAR_POST_ROUTES` must still be visible inside similar.py as a module global, because `_recommendations_likes_payload_error` reads it. An import-back gives that. It also needs `similar.DEFAULT_CLIENT_LIKES_MAX` and `similar.respond_json`, both of which stay.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/config.json\" element=\"test_groups entries (e.g. test_similar.py, test_video.py, test_internal_translate.py, test_internal_events.py, test_server.py, test_logging_profiles.py)\">\n**What changes.** Uncertain; the plan does not mention it. These groups map test files to the source files whose change should trigger them. The new `engine/server/api/router.py` is in no group, so a later edit to the router alone would select no test. Consider adding `router.py` wherever `handlers/similar.py` appears for routing reasons, and adding `http_utils.py` to `test_video.py`/`test_server.py` if they rely on the parse helpers. Whether this file is edited as part of builds is a process question for the operator.\n\n**What depends on it.** The test-selection tooling.\n\n**Regression risk: none at runtime.** The risk is a coverage-selection gap.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"route list (lines 7-27) and references at lines 50 and 53\">\n**What changes.** Nothing, by operator decision.\n- Line 50 cites `_parse_include_nsfw` in `api/handlers/similar.py`, and line 53 cites `SimilarHandler._run_request` in `api/handlers/similar.py`. Both stay true.\n- The route list stays incomplete: it lacks `/api/health`, `/api/channels` and `/api/v1/search/videos`. `router.py`'s docstring becomes the complete list.\n- No README line names `_dispatch_*`, `_bridge_authorized` or `SIMILAR_POST_ROUTES`; I grepped for them.\n\n**What depends on it.** Human readers.\n\n**Regression risk: none.** There is doc drift between README and router.py, which the operator accepts.\n</impact>\n<impact path=\"docs/project/adr/0007-nsfw-filter-default-at-request-edge.md\" element=\"decision point 2 (line 17)\">\n**What changes.** Nothing. It cites `_handle_similar` and `_parse_include_nsfw` in `api/handlers/similar.py`, and `_handle_search`. None of these move.\n\n**Regression risk: none.** It is listed for completeness, because it names the module being edited.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a73b bridge shared secret (lines 504-509) and triage row (line 315)\">\n**What changes.** Nothing. The 503/401 behaviour and the `bridge.auth` log event it documents are preserved, and it names no source file or function.\n\n**Regression risk: none,** as long as the log message text is unchanged.\n</impact>\n<impact path=\"docs/project/issues/58-engine-routing-out-of-similar-handler.md\" element=\"issue status line\">\n**What changes.** Not in this step. On delivery, the triage-labels convention moves the issue to `complete` and into `docs/project/issues/archive/`.\n\n**Regression risk: none.**\n</impact>\n</impacts>",
  "docs_checklist": "- [ ] `engine/server/api/router.py` - New module docstring: the complete Engine route list with method and gate per route. That means every route from the old similar.py docstring, plus `/internal/dislikes/centroids` and `/api/v1/search/videos`, with `/api/health` and `/api/channels` kept. `/internal/*` POST routes are marked as behind the bridge-auth gate, `/api/*` GET routes as behind the rate-limit gate, `/videos/{id}/similar` as having its own rate-limit check, and `/internal/events/ingest` as answering 501 outside bridge mode.\n- [ ] `engine/server/api/handlers/similar.py` - Module docstring rewritten to describe only recommendations, similar, feeds and search, with the route list removed and a pointer to `api/router.py`. The `do_GET`/`do_POST` docstrings are reworded to \"hand the request to the router\", and `_serve_get`/`_serve_post` now say they route instead of dispatching.\n- [ ] `engine/server/api/handlers/__init__.py` - Optional, not in the plan: the package docstring calls `similar` the \"main Engine read handler for recommendations and read endpoints\". A reword could note that routing now lives in `api/router.py`. Operator's call.\n- [ ] `engine/server/README.md` - No edit, by operator decision. I verified that its references to `SimilarHandler._run_request` (line 53) and `_parse_include_nsfw` (line 50) in `api/handlers/similar.py` stay true. Its route list (lines 7-27) stays incomplete; router.py becomes the complete list.",
  "docs": [
    {
      "path": "engine/server/api/router.py",
      "note": "New module docstring: the complete Engine route list with method and gate per route. That means every route from the old similar.py docstring, plus `/internal/dislikes/centroids` and `/api/v1/search/videos`, with `/api/health` and `/api/channels` kept. `/internal/*` POST routes are marked as behind the bridge-auth gate, `/api/*` GET routes as behind the rate-limit gate, `/videos/{id}/similar` as having its own rate-limit check, and `/internal/events/ingest` as answering 501 outside bridge mode."
    },
    {
      "path": "engine/server/api/handlers/similar.py",
      "note": "Module docstring rewritten to describe only recommendations, similar, feeds and search, with the route list removed and a pointer to `api/router.py`. The `do_GET`/`do_POST` docstrings are reworded to \"hand the request to the router\", and `_serve_get`/`_serve_post` now say they route instead of dispatching."
    },
    {
      "path": "engine/server/api/handlers/__init__.py",
      "note": "Optional, not in the plan: the package docstring calls `similar` the \"main Engine read handler for recommendations and read endpoints\". A reword could note that routing now lives in `api/router.py`. Operator's call."
    },
    {
      "path": "engine/server/README.md",
      "note": "No edit, by operator decision. I verified that its references to `SimilarHandler._run_request` (line 53) and `_parse_include_nsfw` (line 50) in `api/handlers/similar.py` stay true. Its route list (lines 7-27) stays incomplete; router.py becomes the complete list."
    }
  ],
  "reassessments": 1,
  "draft": "## Draft \u2014 issue 58: Engine routing out of `SimilarHandler`\n\nFiles I read for this draft: `handlers/similar.py` (lines 1-120, 300-650, 1160-1275), `http_utils.py`, `server.py:240-300` and its `sys.path` setup at 21-23, the import blocks of `handlers/internal_*.py` and `handlers/video.py`, `handlers/__init__.py`, `tests/active/test_video.py` (the child pattern and its `subprocess.run` lines 564/608), `tests/active/conftest.py:1-60` and `tests/config.json`. Everything below matches the plan. Pass 1 against the plan and the requirements came out clean, so no further passes were needed. The one thing that differs from the plan's wording, the channels rename, is called out in the similar.py section.\n\n### What has to be tested\n\n- **Bridge gate on POST `/internal/*`.**\n  - Missing token gives 401. A wrong token gives 401. An unset token (`\"\"`) gives 503.\n  - This holds for one route of each kind (resolve, translate, ingest) and for an unknown `/internal/` path.\n  - The handler does not run in any of those cases.\n  - A valid token reaches the stub once per path, and the unknown path gets 404.\n- **Fake route.** A `GET_ROUTES` entry alone serves `/fake` through the real `SimilarHandler`. Before the entry exists, `/fake` gets 404.\n- **Cheap extras, not in the plan.** Each closes a gap the impact inventory names:\n  - the 501 ingest-mode body with its `mode` field, which was untested until now;\n  - the plain 404 for GET `/internal/*`, which has no gate.\n- **Everything else is covered by existing suites, unchanged.**\n  - test_video: the `/api/video` and refresh adapters, the `/videos/{id}/similar` pattern, and unrouted 404s.\n  - test_internal_translate 1044-1074: real bridge 401s on two routes.\n  - test_server: `/api/channels` via the Client.\n  - The conftest `/api/health` readiness probe, which every Engine fixture depends on.\n  - test_similar and test_recommendations_likes_limit: direct `_handle_similar*` calls and `SIMILAR_POST_ROUTES` through the import-back.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/router.py` | **new.** Route list docstring, `SIMILAR_POST_ROUTES`, `GET_ROUTES`, `POST_ROUTES`, adapters, `handle_health`, `handle_channels`, `_extract_video_id_from_similar_path`, `bridge_authorized`, `route_get`, `route_post` |\n| `engine/server/api/http_utils.py` | adds `parse_int`, `parse_non_negative_int` (moved unchanged) |\n| `engine/server/api/handlers/similar.py` | docstring, imports, `SIMILAR_POST_ROUTES` removed (imported back), `_bridge_authorized`/`_dispatch_*` removed, `_serve_*` call the router, 4 call-site renames, 3 helpers removed |\n| `tests/tmp/test_router_bridge_auth.py` | **new** |\n| `tests/tmp/test_router_fake_route.py` | **new** |\n\nDependency direction: `handlers.similar` \u2192 `router` \u2192 `handlers.internal_*`, `handlers.video`, `http_utils`, `server_config`, `data.*`. Nothing below `router` imports `handlers.similar`; I checked all four import blocks. `handlers/__init__.py` is docstring only, so importing `handlers.internal_events` from inside a partly initialised `handlers.similar` is safe.\n\n### `engine/server/api/router.py` (whole file)\n\n```python\n\"\"\"Route Engine HTTP requests to their handlers.\n\nSimilarHandler hands every GET and POST here, inside its statement deadline. A route is one entry in GET_ROUTES or POST_ROUTES keyed by exact path (query string ignored, no trailing-slash match) whose value takes (handler, server); a path in neither table, or sent with the other method, answers 404 {\"error\": \"Not found\"}.\n\nRoutes:\n- POST /recommendations: recommendation feed and debug payloads; own per-IP rate-limit check.\n- POST /videos/similar: extended similar route; own per-IP rate-limit check.\n- GET /videos/{id}/similar: id-based similar alias; the one pattern route, tried after an exact miss, with its own per-IP rate-limit check.\n- GET /api/health: health check. [rate-limit gate]\n- GET /api/channels: channels listing. [rate-limit gate]\n- GET /api/v1/search/videos: hybrid video search. [rate-limit gate]\n- GET /api/video: single video metadata. [rate-limit gate]\n- GET /api/video/refresh: single video metadata refreshed from its instance. [rate-limit gate]\n- POST /internal/videos/resolve: internal Client read lookup by video_id/uuid(+host). [bridge gate]\n- POST /internal/videos/metadata: internal Client metadata batch lookup. [bridge gate]\n- POST /internal/dislikes/centroids: internal Client clustering of a visitor's disliked videos into taste centroids; nothing stored. [bridge gate]\n- POST /internal/translate: internal Client read of a video's English translate state and whether a translate worker is serving; cues from a stored job, or from its own instance (cached). [bridge gate]\n- POST /internal/translate/enqueue: internal Client request to queue a video's whisper translate job while a translate worker is serving. [bridge gate]\n- POST /internal/events/ingest: internal bridge ingest for normalized events; 501 outside ENGINE_INGEST_MODE=bridge. [bridge gate]\n\nGates:\n- bridge gate: every POST /internal/* path, unknown ones included, needs the shared X-Bridge-Token first: 503 when the Engine has none configured, 401 when it is missing or wrong.\n- rate-limit gate: every GET /api/* path, unknown ones included, passes the per-IP limiter first: 429.\n- GET /internal/* has no gate and answers 404.\n\"\"\"\nimport hmac\nimport logging\nfrom typing import Any, Callable\nfrom urllib.parse import parse_qs, urlparse\n\nfrom data.channels import fetch_channels\nfrom data.time import now_ms\nfrom http_utils import parse_int, parse_non_negative_int, respond_json\nfrom server_config import BRIDGE_TOKEN_HEADER, ENGINE_BRIDGE_TOKEN\nfrom handlers.internal_events import handle_internal_events_ingest\nfrom handlers.internal_client_reads import (\n    handle_internal_dislike_centroids,\n    handle_internal_video_resolve,\n    handle_internal_videos_metadata,\n)\nfrom handlers.internal_translate import handle_internal_translate, handle_internal_translate_enqueue\nfrom handlers.video import handle_video_refresh_request, handle_video_request\n\n\nSIMILAR_POST_ROUTES = {\"/recommendations\", \"/videos/similar\"}\n\n\ndef handle_health(handler: Any, server: Any) -> None:\n    \"\"\"Answer the health check with the loaded embedding count and dimension.\"\"\"\n    payload = {\n        \"ok\": True,\n        \"total\": server.embeddings_count,\n        \"embeddingDim\": server.embeddings_dim,\n    }\n    respond_json(handler, 200, payload)\n\n\ndef handle_channels(handler: Any, server: Any) -> None:\n    \"\"\"Answer a page of the channels listing.\"\"\"\n    params = parse_qs(urlparse(handler.path).query)\n    limit = parse_int(params.get(\"limit\", [None])[0])\n    if limit <= 0:\n        limit = 100\n    limit = min(limit, 500)\n    offset = parse_int(params.get(\"offset\", [None])[0])\n    max_videos = parse_non_negative_int(params.get(\"maxVideos\", [None])[0])\n    with server.db_lock:\n        rows, total = fetch_channels(\n            server.db,\n            limit=limit,\n            offset=offset,\n            query=params.get(\"q\", [\"\"])[0] or \"\",\n            instance=params.get(\"instance\", [\"\"])[0] or \"\",\n            min_followers=parse_int(params.get(\"minFollowers\", [None])[0]),\n            min_videos=parse_int(params.get(\"minVideos\", [None])[0]),\n            max_videos=max_videos,\n            sort=params.get(\"sort\", [\"followers\"])[0] or \"followers\",\n            direction=params.get(\"dir\", [\"desc\"])[0] or \"desc\",\n        )\n    respond_json(\n        handler,\n        200,\n        {\n            \"generatedAt\": now_ms(),\n            \"total\": total,\n            \"rows\": rows,\n        },\n    )\n\n\ndef _similar_post(handler: Any, server: Any) -> None:\n    \"\"\"Serve a recommendations or extended-similar POST through the handler's similarity path.\"\"\"\n    handler._handle_similar_request(method=\"POST\")\n\n\ndef _search(handler: Any, server: Any) -> None:\n    \"\"\"Serve a video search with the request's query parameters.\"\"\"\n    handler._handle_search(parse_qs(urlparse(handler.path).query))\n\n\ndef _video(handler: Any, server: Any) -> None:\n    \"\"\"Serve single video metadata with the request's query parameters.\"\"\"\n    handle_video_request(handler, server, parse_qs(urlparse(handler.path).query))\n\n\ndef _video_refresh(handler: Any, server: Any) -> None:\n    \"\"\"Serve refreshed single video metadata with the request's query parameters.\"\"\"\n    handle_video_refresh_request(handler, server, parse_qs(urlparse(handler.path).query))\n\n\ndef _events_ingest(handler: Any, server: Any) -> None:\n    \"\"\"Serve bridge ingest, answering 501 when the Engine is not in bridge ingest mode.\"\"\"\n    if getattr(server, \"engine_ingest_mode\", \"bridge\") != \"bridge\":\n        respond_json(\n            handler,\n            501,\n            {\n                \"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\",\n                \"mode\": getattr(server, \"engine_ingest_mode\", \"bridge\"),\n            },\n        )\n        return\n    handle_internal_events_ingest(handler, server)\n\n\n# Exact path -> callable(handler, server); read per request, so a test may add or replace an entry at run time.\nGET_ROUTES: dict[str, Callable[[Any, Any], Any]] = {\n    \"/api/health\": handle_health,\n    \"/api/channels\": handle_channels,\n    \"/api/v1/search/videos\": _search,\n    \"/api/video\": _video,\n    \"/api/video/refresh\": _video_refresh,\n}\n\nPOST_ROUTES: dict[str, Callable[[Any, Any], Any]] = {\n    **dict.fromkeys(SIMILAR_POST_ROUTES, _similar_post),\n    \"/internal/videos/resolve\": handle_internal_video_resolve,\n    \"/internal/videos/metadata\": handle_internal_videos_metadata,\n    \"/internal/dislikes/centroids\": handle_internal_dislike_centroids,\n    \"/internal/translate\": handle_internal_translate,\n    \"/internal/translate/enqueue\": handle_internal_translate_enqueue,\n    \"/internal/events/ingest\": _events_ingest,\n}\n\n\ndef _extract_video_id_from_similar_path(path: str) -> str | None:\n    \"\"\"Resolve /videos/{id}/similar route shape to seed video id.\"\"\"\n    if not path.startswith(\"/videos/\") or not path.endswith(\"/similar\"):\n        return None\n    parts = path.strip(\"/\").split(\"/\")\n    if len(parts) != 3 or parts[0] != \"videos\" or parts[2] != \"similar\":\n        return None\n    video_id = parts[1].strip()\n    return video_id or None\n\n\ndef bridge_authorized(handler: Any) -> bool:\n    \"\"\"Check the shared secret on internal bridge routes.\n\n    These routes write to the interaction event stream and read across the\n    Client/Engine boundary, so an unset secret fails closed: accepting them\n    unauthenticated is what let any browser rewrite the global ranking.\n    \"\"\"\n    configured = getattr(handler.server, \"bridge_token\", ENGINE_BRIDGE_TOKEN)\n    if not configured:\n        logging.error(\n            \"[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting %s\", handler.path\n        )\n        respond_json(\n            handler, 503, {\"error\": \"Bridge token is not configured on the Engine\"}\n        )\n        return False\n    presented = handler.headers.get(BRIDGE_TOKEN_HEADER, \"\").strip()\n    if not presented or not hmac.compare_digest(presented, configured):\n        logging.warning(\n            \"[bridge.auth] rejected %s from ip=%s\", handler.path, handler._get_client_ip()\n        )\n        respond_json(handler, 401, {\"error\": \"Unauthorized\"})\n        return False\n    return True\n\n\ndef route_post(handler: Any) -> None:\n    \"\"\"Route a POST through the /internal/ bridge gate to its POST_ROUTES entry, or 404.\"\"\"\n    url = urlparse(handler.path)\n    if url.path.startswith(\"/internal/\") and not bridge_authorized(handler):\n        return\n    route = POST_ROUTES.get(url.path)\n    if route is not None:\n        route(handler, handler.server)\n        return\n    respond_json(handler, 404, {\"error\": \"Not found\"})\n\n\ndef route_get(handler: Any) -> None:\n    \"\"\"Route a GET through the /api/ rate-limit gate to its GET_ROUTES entry, the /videos/{id}/similar pattern, or 404.\"\"\"\n    url = urlparse(handler.path)\n    if url.path.startswith(\"/api/\") and not handler._rate_limit_check(url.path):\n        respond_json(handler, 429, {\"error\": \"Rate limit exceeded\"})\n        return\n    route = GET_ROUTES.get(url.path)\n    if route is not None:\n        route(handler, handler.server)\n        return\n    video_path_id = _extract_video_id_from_similar_path(url.path)\n    if video_path_id is not None:\n        if not handler._rate_limit_check(url.path):\n            respond_json(handler, 429, {\"error\": \"Rate limit exceeded\"})\n            return\n        params = parse_qs(url.query)\n        params.setdefault(\"id\", [video_path_id])\n        handler._handle_similar(params)\n        return\n    respond_json(handler, 404, {\"error\": \"Not found\"})\n```\n\n**Invariants**\n\n- **Gate order.**\n  - `route_post`: the bridge gate, then `POST_ROUTES.get`, then 404.\n  - `route_get`: the `/api/` limiter, then `GET_ROUTES.get`, then the pattern (limiter, then `setdefault`, then `_handle_similar`), then 404.\n  - This is the same order as `similar.py:442-562`.\n- **Table lookups happen at call time.** The tables are plain module-level dicts and are never copied.\n- **Logging stays byte-identical.** Bridge-auth logging uses the root `logging.error` / `logging.warning` with the old format strings and the raw `handler.path`.\n- **Return values are ignored.** Each `handle_internal_*` returns a bool, and the router discards it, as the old chain did.\n- **Small differences that cannot change an outcome.**\n  - `parse_qs` now runs after the pattern's limiter, where the old code ran it before. `parse_qs` with default arguments cannot raise, so this changes nothing.\n  - Search and video re-parse the query from `handler.path`. That gives the same dict the old shared `params` did.\n- **No import of `handlers.similar` anywhere in this file.** The router reaches similarity only through methods on `handler`: `_handle_similar_request`, `_handle_similar`, `_handle_search`, `_rate_limit_check` and `_get_client_ip`.\n\n### `engine/server/api/http_utils.py` (insert after `read_json_body`, before `class RateLimiter`)\n\n```python\ndef parse_int(value: str | None) -> int:\n    \"\"\"Parse a positive integer; return 0 on invalid input.\"\"\"\n    try:\n        parsed = int(value or \"0\")\n    except ValueError:\n        return 0\n    return parsed if parsed > 0 else 0\n\n\ndef parse_non_negative_int(value: str | None) -> int | None:\n    \"\"\"Parse a non-negative integer; return None on invalid input.\"\"\"\n    if value is None or not value.strip():\n        return None\n    try:\n        parsed = int(value)\n    except ValueError:\n        return None\n    return parsed if parsed >= 0 else None\n```\n\nThe bodies and docstrings are byte-for-byte the old `_parse_int` / `_parse_non_negative_int`. No new import is needed.\n\n### `engine/server/api/handlers/similar.py` edits\n\n1. **Docstring.** Lines 1-20 become:\n```python\n\"\"\"Similarity HTTP handler for Engine read surface.\n\nServes recommendations, similar videos (by id and the extended POST route), the home feeds and hybrid video search. SimilarHandler is the Engine's one request handler class; it hands every GET and POST to `api/router.py`, which holds the route list, the bridge-auth and rate-limit gates and the 404.\n\nKey steps:\n- Parse seed/params, resolve likes (client JSON or users DB).\n- Build candidate pools, score, mix, and return stable rows.\n\"\"\"\n```\n2. **Imports.**\n   - Removed:\n     - `import hmac` (22);\n     - `from data.channels import fetch_channels` (36);\n     - `BRIDGE_TOKEN_HEADER,` (52) and `ENGINE_BRIDGE_TOKEN,` (58) from the `server_config` import;\n     - lines 96-103, the four handler imports.\n   - Line 80 becomes `from http_utils import parse_int, parse_non_negative_int, read_json_body, respond_json, respond_options, resolve_user_id`.\n   - Added in place of 96-103: `from router import SIMILAR_POST_ROUTES, route_get, route_post`.\n   - Kept: `urlparse` / `parse_qs` (643/647), `now_ms`, `sqlite3`, `Callable`, `logging`.\n3. **`SIMILAR_POST_ROUTES = {...}` (106) is deleted.** `_recommendations_likes_payload_error` (234) reads the imported name, unchanged. `FEED_MODES` stays a module-level tuple literal, as test_frontend_feed_params requires.\n4. **`do_POST` / `_serve_post` (403-415):**\n```python\n    def do_POST(self) -> None:  # noqa: N802\n        \"\"\"Hand a POST to the router under the time budget.\"\"\"\n        self._run_request(self._serve_post)\n\n    def _serve_post(self) -> None:\n        \"\"\"Route a POST under the time budget, answering 503 when its database work is interrupted.\"\"\"\n        try:\n            with self._statement_deadline():\n                route_post(self)\n        except sqlite3.OperationalError as exc:\n            if not is_interrupted_error(exc):\n                raise\n            self._respond_interrupted()\n```\n5. **`_bridge_authorized` (417-440) and `_dispatch_post` (442-478) are deleted.**\n6. **`do_GET` / `_serve_get` (480-492):** the same shape, with docstrings `\"\"\"Hand a GET to the router under the time budget.\"\"\"` / `\"\"\"Route a GET under the time budget, answering 503 when its database work is interrupted.\"\"\"` and the body `route_get(self)`.\n7. **`_dispatch_get` (494-562) is deleted.**\n8. **Renames.** These are the only remaining call sites (grep-verified):\n   - 584 `_parse_int` \u2192 `parse_int`;\n   - 588 `_parse_int` \u2192 `parse_int`;\n   - 1035 `_parse_int` \u2192 `parse_int`;\n   - 1062 `_parse_non_negative_int` \u2192 `parse_non_negative_int`.\n\n   The plan says channels call sites \"stay\". That is slightly off: they move into `router.handle_channels` instead, as the impact inventory already notes.\n9. **Deleted helpers:** `_parse_int` (1167-1173), `_parse_non_negative_int` (1191-1199) and `_extract_video_id_from_similar_path` (1267-1275). `_parse_bool` and `_parse_include_nsfw` stay.\n10. **Post-edit grep must return nothing** in similar.py for: `_parse_int(`, `_parse_non_negative_int`, `_extract_video_id`, `fetch_channels`, `hmac`, `ENGINE_BRIDGE_TOKEN`, `BRIDGE_TOKEN_HEADER`, `_dispatch_`, `_bridge_authorized`, `handlers.internal_`, `handlers.video`. A missed rename would only surface at request time, as a NameError.\n\nNothing else in `SimilarHandler` changes. `_run_request`, the deadline and 503 wrapper, `_get_client_ip`, `_get_full_url`, `log_request`, `log_message`, `do_OPTIONS`, `_rate_limit_check` and every similarity, feed and search method stay as they are.\n\n### Tests\n\nBoth tests are pytest launchers that run an Engine child the way test_video does: `subprocess.run([ENGINE_PY, \"-c\", CHILD], cwd=API_DIR)`. The child imports `server` first, because it puts `engine/server` on `sys.path`. Then it builds a real `SimilarServer` with the real `SimilarHandler` on port 0, using `dict.fromkeys(signature params[3:])`. So `db`, `rate_limiter` and `engine_ingest_mode` are all `None`; the constructor never touches `db`, and these paths never reach it.\n\n`ROOT` and `ENGINE_PY` are defined locally, with the same expressions as conftest. `tests/tmp` has no conftest, and importing `tests/active/conftest.py` would load the Client backend. That is a deliberate two-line duplication; when the files are archived to `tests/active`, switch to `from conftest import ENGINE_PY, ROOT`.\n\n**`tests/tmp/test_router_bridge_auth.py`**\n\n```python\n\"\"\"POST /internal/* behind the router's bridge-auth gate (engine/server/api/router.py), through a real SimilarServer and SimilarHandler in an Engine child.\n\n- With the Engine's token set, a POST to /internal/videos/resolve, /internal/translate, /internal/events/ingest or an unknown /internal/ path answers 401 {\"error\": \"Unauthorized\"} without an X-Bridge-Token and with a wrong one, and 503 {\"error\": \"Bridge token is not configured on the Engine\"} once the token is \"\".\n- None of those requests reaches the route: the three routes' POST_ROUTES entries are replaced by a recording stub, which records nothing for them; with the right token each stub is reached once and the unknown path answers 404 {\"error\": \"Not found\"}.\n- Before the stubs, a valid-token ingest under engine_ingest_mode None answers 501 with that mode, from the router's own ingest adapter.\n- A GET to /internal/videos/resolve answers a plain 404, with no gate.\n\"\"\"\nfrom __future__ import annotations\n\nimport json\nimport subprocess\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[2]\nENGINE_PY = ROOT / \"engine\" / \".pixi\" / \"envs\" / \"default\" / \"bin\" / \"python\"\nAPI_DIR = ROOT / \"engine\" / \"server\" / \"api\"\n\nCHILD = r'''\nimport http.client, inspect, json, threading\nimport server\nimport router\nfrom handlers.similar import SimilarHandler\nfrom http_utils import respond_json\n\nTOKEN = \"router-test-token\"\nSTUBBED = [\"/internal/videos/resolve\", \"/internal/translate\", \"/internal/events/ingest\"]\nPATHS = STUBBED + [\"/internal/no-such-route\"]\n\ndef send(port, method, path, headers):\n    client = http.client.HTTPConnection(\"127.0.0.1\", port, timeout=30)\n    client.request(method, path, body=b\"{}\" if method == \"POST\" else None, headers=headers)\n    resp = client.getresponse()\n    body = json.loads(resp.read() or b\"null\")\n    client.close()\n    return [resp.status, body]\n\nargs = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])\nsrv = server.SimilarServer((\"127.0.0.1\", 0), SimilarHandler, **args)\nsrv.bridge_token = TOKEN\nthreading.Thread(target=srv.serve_forever, daemon=True).start()\nport = srv.server_address[1]\ncalls = []\ndef stub(handler, server_):\n    calls.append(handler.path)\n    respond_json(handler, 200, {\"stub\": handler.path})\nreport = {}\ntry:\n    report[\"ingest_mode\"] = send(port, \"POST\", \"/internal/events/ingest\", {\"X-Bridge-Token\": TOKEN})\n    for path in STUBBED:\n        router.POST_ROUTES[path] = stub\n    report[\"missing\"] = {p: send(port, \"POST\", p, {}) for p in PATHS}\n    report[\"wrong\"] = {p: send(port, \"POST\", p, {\"X-Bridge-Token\": \"wrong\"}) for p in PATHS}\n    report[\"calls_rejected\"] = list(calls)\n    report[\"valid\"] = {p: send(port, \"POST\", p, {\"X-Bridge-Token\": TOKEN}) for p in PATHS}\n    report[\"calls_valid\"] = list(calls)\n    srv.bridge_token = \"\"\n    report[\"unset\"] = {p: send(port, \"POST\", p, {\"X-Bridge-Token\": TOKEN}) for p in PATHS}\n    report[\"calls_after_unset\"] = list(calls)\n    report[\"get_internal\"] = send(port, \"GET\", \"/internal/videos/resolve\", {\"X-Bridge-Token\": TOKEN})\nfinally:\n    srv.shutdown()\n    srv.server_close()\nprint(json.dumps(report))\n'''\n\nPATHS = [\"/internal/videos/resolve\", \"/internal/translate\", \"/internal/events/ingest\", \"/internal/no-such-route\"]\nSTUBBED = PATHS[:3]\nUNAUTHORIZED = [401, {\"error\": \"Unauthorized\"}]\nUNSET = [503, {\"error\": \"Bridge token is not configured on the Engine\"}]\n\n\ndef test_internal_posts_are_gated_before_their_route():\n    assert ENGINE_PY.exists(), f\"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/\"\n    run = subprocess.run([str(ENGINE_PY), \"-c\", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)\n    assert run.returncode == 0, run.stderr\n    report = json.loads(run.stdout)\n    assert report[\"ingest_mode\"] == [501, {\"error\": \"Bridge ingest is disabled in current ENGINE_INGEST_MODE\", \"mode\": None}]\n    assert report[\"missing\"] == {path: UNAUTHORIZED for path in PATHS}\n    assert report[\"wrong\"] == {path: UNAUTHORIZED for path in PATHS}\n    assert report[\"calls_rejected\"] == []\n    assert report[\"valid\"] == {**{path: [200, {\"stub\": path}] for path in STUBBED}, \"/internal/no-such-route\": [404, {\"error\": \"Not found\"}]}\n    assert report[\"calls_valid\"] == STUBBED\n    assert report[\"unset\"] == {path: UNSET for path in PATHS}\n    assert report[\"calls_after_unset\"] == STUBBED\n    assert report[\"get_internal\"] == [404, {\"error\": \"Not found\"}]\n```\n\n**`tests/tmp/test_router_fake_route.py`**\n\n```python\n\"\"\"A route added as one router.GET_ROUTES entry, with no edit to handlers/similar.py, is served through a real SimilarServer and SimilarHandler in an Engine child.\n\n- Before the entry, GET /fake answers 404 {\"error\": \"Not found\"}.\n- After router.GET_ROUTES[\"/fake\"] is set to a function answering through respond_json, GET /fake?x=1 answers 200 with that function's body, which carries the raw request path, query included.\n\"\"\"\nfrom __future__ import annotations\n\nimport json\nimport subprocess\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[2]\nENGINE_PY = ROOT / \"engine\" / \".pixi\" / \"envs\" / \"default\" / \"bin\" / \"python\"\nAPI_DIR = ROOT / \"engine\" / \"server\" / \"api\"\n\nCHILD = r'''\nimport http.client, inspect, json, threading\nimport server\nimport router\nfrom handlers.similar import SimilarHandler\nfrom http_utils import respond_json\n\ndef get(port, path):\n    client = http.client.HTTPConnection(\"127.0.0.1\", port, timeout=30)\n    client.request(\"GET\", path)\n    resp = client.getresponse()\n    body = json.loads(resp.read() or b\"null\")\n    client.close()\n    return [resp.status, body]\n\ndef fake(handler, server_):\n    respond_json(handler, 200, {\"fake\": True, \"path\": handler.path})\n\nargs = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])\nsrv = server.SimilarServer((\"127.0.0.1\", 0), SimilarHandler, **args)\nthreading.Thread(target=srv.serve_forever, daemon=True).start()\nport = srv.server_address[1]\nreport = {}\ntry:\n    report[\"before\"] = get(port, \"/fake\")\n    router.GET_ROUTES[\"/fake\"] = fake\n    report[\"after\"] = get(port, \"/fake?x=1\")\nfinally:\n    srv.shutdown()\n    srv.server_close()\nprint(json.dumps(report))\n'''\n\n\ndef test_fake_route_is_served_from_a_table_entry():\n    assert ENGINE_PY.exists(), f\"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/\"\n    run = subprocess.run([str(ENGINE_PY), \"-c\", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)\n    assert run.returncode == 0, run.stderr\n    report = json.loads(run.stdout)\n    assert report[\"before\"] == [404, {\"error\": \"Not found\"}]\n    assert report[\"after\"] == [200, {\"fake\": True, \"path\": \"/fake?x=1\"}]\n```\n\n### Decisions behind the draft\n\n- **Table signature `(handler, server)`.** The five client-read and translate handlers go into the table with no adapter. The four adapters are named one-line-docstring functions, matching the file style; no lambdas.\n- **`POST_ROUTES` derives its two similar entries from `SIMILAR_POST_ROUTES` with `dict.fromkeys`.** Each path string is written exactly once, in router.py.\n- **`handle_health` / `handle_channels` are public `handle_*`,** following the `handlers/*.py` naming. The adapters are private, because nothing outside the router should call them.\n- **Tests replace table entries, never module functions.** Only the table entry is looked up at dispatch time.\n- **Ingest 501 check runs before stubbing.** The 501 request comes before the stubs replace the ingest entry, so the router's own adapter is exercised. `handle_internal_events_ingest` is never reached there, because `engine_ingest_mode` is `None`.\n- **Deliberate simplification: one hard-coded pattern route.** `/videos/{id}/similar` is special-cased in `route_get`. The ceiling is a second parameterised path. The upgrade is an ordered list of `(matcher, callable)` pairs tried after the exact lookup.\n\n### Left for the operator (not edited, outside the settled plan)\n\n- **`handlers/__init__.py`.** The docstring line \"similar: main Engine read handler \u2026\" could gain \"routing lives in `api/router.py`\". This is optional, per the inventory.\n- **`tests/config.json`.** `engine/server/api/router.py` is in no test group, so an edit to the router alone selects no test. Candidates for adding it: `test_similar.py`, `test_video.py`, `test_internal_translate.py`, `test_internal_events.py` and `test_server.py`. This is a process decision.",
  "coordination": "none",
  "tests": {
    "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:127 \u2014 POST to /internal/videos/resolve, /internal/translate, /internal/events/ingest and /internal/no-such-route with no X-Bridge-Token, after the three POST_ROUTES entries were replaced by recording stubs, each answers [401, {\"error\": \"Unauthorized\"}]",
          "expected": "{path: [401, {\"error\": \"Unauthorized\"}] for all four paths}. The run showed this, and the line passed against today's gate.",
          "wrong_implementation": "A route_post that looks up POST_ROUTES before it runs the gate reads [200, {\"stub\": path}] for the three stubbed paths. A gate that only covers paths in the table reads [404, {\"error\": \"Not found\"}] for /internal/no-such-route."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:129 \u2014 the same four POSTs carrying a near-miss token (the real token less its last character) each answer [401, {\"error\": \"Unauthorized\"}]",
          "expected": "{path: [401, {\"error\": \"Unauthorized\"}] for all four paths}. Observed passing in the run.",
          "wrong_implementation": "A startswith or containment compare in place of hmac.compare_digest accepts \"router-test-toke\" and reads the stub's [200, {\"stub\": path}], or 404 for the unknown path."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:130 \u2014 the stubs recorded no call across the missing-token and near-miss requests",
          "expected": "[] (observed). Lines 132-133 arm it: with the valid token every stub is reached.",
          "wrong_implementation": "A gate that writes the 401 but still falls through to the table entry (a missing return after a False bridge_authorized) records every stubbed path here, while the status lines could still read 401 first."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:132 \u2014 with the valid token, the three stubbed paths answer the stub's [200, {\"stub\": path}] and /internal/no-such-route answers [404, {\"error\": \"Not found\"}]",
          "expected": "{\"/internal/videos/resolve\": [200, {\"stub\": \"/internal/videos/resolve\"}], \"/internal/translate\": [200, {\"stub\": \"/internal/translate\"}], \"/internal/events/ingest\": [200, {\"stub\": \"/internal/events/ingest\"}], \"/internal/no-such-route\": [404, {\"error\": \"Not found\"}]}. The stub response shape [200, {\"stub\": path}] came from a probe run through a real SimilarHandler. The 404 body for the unknown path was observed in this run.",
          "wrong_implementation": "Today's code, observed in this run: it dispatches through SimilarHandler's own if-chain instead of POST_ROUTES and reads [400, {\"error\": \"Missing video_id or uuid\"}], [400, {\"error\": \"Missing id or host\"}] and [501, {... \"mode\": None}]. A table copied or bound at import reads the same."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:133 \u2014 the stubs were reached exactly once each, in request order",
          "expected": "[\"/internal/videos/resolve\", \"/internal/translate\", \"/internal/events/ingest\"] (the recording shape was observed in the probe as calls == [\"/stubbed\"])",
          "wrong_implementation": "Dispatch that bypasses the table records [], the current state. A route_post that calls the entry twice, or calls it for rejected requests too, records extra entries."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:135 \u2014 after srv.bridge_token = \"\", the four POSTs with the formerly valid token each answer [503, {\"error\": \"Bridge token is not configured on the Engine\"}]",
          "expected": "{path: [503, {\"error\": \"Bridge token is not configured on the Engine\"}] for all four paths}. The probe run observed this body for a known path and for an unknown path. This test does not reach line 135 yet, because it stops at line 132.",
          "wrong_implementation": "A gate that falls back to ENGINE_BRIDGE_TOKEN when the attribute is falsy (`server.bridge_token or ENGINE_BRIDGE_TOKEN`; the env value is \"\") still reads 503. One that treats \"\" as a token reads 401. One that skips the check when unset reads the stub's 200, or 404 for the unknown path."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:136 \u2014 the 503 requests added no stub call (the record is still exactly STUBBED)",
          "expected": "[\"/internal/videos/resolve\", \"/internal/translate\", \"/internal/events/ingest\"]",
          "wrong_implementation": "An unset-token branch that writes the 503 but falls through to the entry appends the three stubbed paths again: six entries."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:146 \u2014 after router.GET_ROUTES[\"/fake\"] = fake, GET /fake?x=1 answers the entry's [200, {\"fake\": True, \"path\": \"/fake?x=1\"}]",
          "expected": "[200, {\"fake\": True, \"path\": \"/fake?x=1\"}]. Observed in the probe, where the same function was driven from a real SimilarHandler; handler.path keeps the query string.",
          "wrong_implementation": "Today's code, observed in this run: SimilarHandler's own _dispatch_get never consults a table, so it reads [404, {\"error\": \"Not found\"}]. A route_get that binds or copies GET_ROUTES at import reads the same 404. A lookup keyed on the raw path, query included, misses \"/fake\" and also reads 404."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:148 \u2014 the entry was called exactly once, with type(handler) is SimilarHandler and server is the running SimilarServer",
          "expected": "[{\"handler_is_similar\": True, \"server_is_srv\": True}]. Observed in the probe, with isinstance against a SimilarHandler subclass; here the server is built with SimilarHandler itself.",
          "wrong_implementation": "A router that calls entries with a wrapper or adapter object, or with the module-level default server, reads False in the matching field. Calling the entry for /fake/ or for POST adds a second record. Today nothing calls it, so the record reads []."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Every POST to an `/internal/*` path, unknown paths included, gets the router's bridge-gate answer before its `POST_ROUTES` entry runs: 401 when the token is missing or wrong, 503 when the Engine has none set."
        },
        {
          "id": "C2",
          "text": "A route added as one `GET_ROUTES` entry, with no edit to `handlers/similar.py`, is served through the real `SimilarHandler`."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_58_engine_routing_out_of_similar_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_58_engine_routing_out_of_similar_phase1.py  2 failed                               0.0s\n  ---------------------------------------------------------\n  total                                                      2 failed                               1.5s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_58_engine_routing_out_of_similar_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_internal_posts_answer_the_bridge_gate_before_their_route_runs fails at line 132\non `report[\"valid\"] == {**{path: [200, {\"stub\": path}] ...}, ...}`. Without `router`,\nthe child writes its stubs into an unwired SimpleNamespace table. The hard-coded\n`_dispatch_post` in handlers/similar.py:442-478 then sends the valid-token POSTs to the\nreal `handle_internal_*` functions and the 501 ingest branch, not to the stubs. Lines\n125-130 pass today because the existing prefix gate at similar.py:445 already answers\n401 for these requests, and the ingest 501 at similar.py:466-475 already reports\n`mode: None`.\ntest_a_route_added_as_one_get_routes_entry_is_served_through_the_real_handler fails at\nline 146 on `report[\"after\"] == [200, {\"fake\": True, \"path\": \"/fake?x=1\"}]`. Today's\n`_dispatch_get` never reads the stand-in `GET_ROUTES`, so it answers [404, {\"error\": \"Not found\"}].\n\nNOT ASSESSED\n1. `code_under_test` engine/server/api/router.py does not resolve. It is marked NEW, so\n   the stub question was answered from the assertion form and today's\n   handlers/similar.py dispatch.\n2. `code_under_test` tests/tmp/test_router_bridge_auth.py and\n   tests/tmp/test_router_fake_route.py do not resolve. Neither one is imported by the\n   test under audit.\n3. For the valid-token requests at line 132, I did not work out what status the real\n   `handle_internal_*` functions give with `db` None. The prediction only claims the\n   response is not the stub's [200, {\"stub\": path}].\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 7 must_prove, 14 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | every POST to `/internal/*`, unknown path included, answers 401 when the token is missing | :127 | a gate checked after the table lookup (the stubbed paths would read 200); a gate that covers known routes only (`/internal/no-such-route` would read 404) | CARRIED |\n| C1b | must_prove | 401 when the token is wrong | :129 | a prefix or containment compare that accepts `TOKEN[:-1]` | CARRIED |\n| C1c | must_prove | 503 when the Engine has no token set | :135 | a fallback to another token, or `\"\"` accepted as a token (would read 401 or the stub's 200) | CARRIED |\n| C1d | must_prove | the gate answers before the `POST_ROUTES` entry runs | :130, :136 | a gate that answers 401/503 after the entry has run: the stub records the request | CARRIED |\n| C1e | must_prove | past the gate, the `POST_ROUTES` entry is what runs, so the empty record means something | :132, :133 | dispatch that skips the table, or a table copied at import (would answer the real handlers' codes, not the stub's 200) | CARRIED |\n| C2a | must_prove | a route added as one `GET_ROUTES` entry is served, with no edit to `handlers/similar.py` | :144, :146 | a table bound or copied at import; dispatch that hardcodes each path in `similar.py` (`/fake` stays 404) | CARRIED |\n| C2b | must_prove | served through the real `SimilarHandler` | :148 | the entry being called by some other handler class, or without the serving `SimilarServer` | CARRIED |\n| D1 | docstring | \"over real HTTP into a real `SimilarServer` running the real `SimilarHandler` in an Engine child\" | :118, :148 | a child that never built the server or never ran the requests (non-zero exit); the wrong handler type | CARRIED |\n| D2 | docstring | 401 `Unauthorized` without `X-Bridge-Token` on the four paths | :127 | the same as C1a | CARRIED |\n| D3 | docstring | 401 with a near-miss token (the real token less its last character) | :129 | the same as C1b | CARRIED |\n| D4 | docstring | 503 with the exact message once the Engine's token is `\"\"` | :135 | the same as C1c, plus a wrong body | CARRIED |\n| D5 | docstring | \"None of those requests reaches its route\": the stubs record nothing | :130, :136 | the same as C1d | CARRIED |\n| D6 | docstring | \"With the right token each stub is reached exactly once\" | :133 | a stub hit twice, or a stub skipped (exact list equality) | CARRIED |\n| D7 | docstring | with the right token, the unknown path answers 404 `Not found` | :132 | the unknown path falling through to a stub, or answering some other status | CARRIED |\n| D8 | docstring | before the stubs, a valid-token ingest under mode None answers the 501 with `mode: None` | :125 | a stub installed too early; a lost 501 branch | CARRIED |\n| D9 | docstring | GET `/internal/videos/resolve` answers a plain 404, with no gate | :138 | a gate on GET too (it would answer 503, because `bridge_token` is `\"\"` from :86) | CARRIED |\n| D10 | docstring | before the entry, GET `/fake` answers 404 | :144 | something already serving `/fake`, which would make the 200 at :146 meaningless | CARRIED |\n| D11 | docstring | after the entry, GET `/fake?x=1` answers 200 with a body carrying the raw path, query included | :146 | an entry not called for this request; a body or path rewritten on the way | CARRIED |\n| D12 | docstring | the entry is called with the serving `SimilarHandler` and the `SimilarServer` itself | :148 | a different handler or server object passed in | CARRIED |\n| D13 | docstring | exact-path matching on GET: GET `/fake/` answers 404 | :150 | prefix matching | CARRIED |\n| D14 | docstring | GET-only: POST `/fake` answers 404 | :151 | a table that ignores the method | CARRIED |\n| N1 | name | \"internal posts answer the bridge gate\" | :127, :129, :135 | the same as C1a\u2013C1c | CARRIED |\n| N2 | name | \"before their route runs\" | :130, :136 | the same as C1d | CARRIED |\n| N3 | name | \"a route added as one get_routes entry is served\" | :146 | the same as C2a | CARRIED |\n| N4 | name | \"through the real handler\" | :148 | the same as C2b | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:82\n   `report[\"near_miss\"] = {p: send(port, \"POST\", p, {\"X-Bridge-Token\": TOKEN[:-1]}) for p in PATHS}`\n   The only wrong token sent is one character short. C1b says \"wrong\", and two kinds of wrong token are never sent: one the same length that differs in a character, and the real token with a character added. A `presented.startswith(configured)` compare would pass :129.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:87\n   The 503 is only checked with the real token in the request. The case where the Engine has no token set and the request carries none is never sent. So a gate that answers 401 for a missing token before it checks the Engine's own token is not ruled out. C1 does not say which answer wins when both conditions hold, so this is not blocking.\n3. No rule in testing.md covers this \u2014 tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:137\n   The comment says \"a gate on both methods reads 401 here\". But :86 sets `srv.bridge_token = \"\"` before the GET at :89, so a gate on GET would answer 503. The assertion at :138 still rules that gate out. Only the comment's stated status is wrong.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/api/router.py, which does not exist. Three things the test assumes could not be checked against it: the `GET_ROUTES` / `POST_ROUTES` names, the `(handler, server)` signature of an entry, and whether the router itself answers the gate and the ingest 501. I judged the clauses from the test, from the dispatch in the current `handlers/similar.py`, and from `SimilarServer.__init__`.\n2. `code_under_test` lists tests/tmp/test_router_bridge_auth.py and tests/tmp/test_router_fake_route.py. Neither exists, so neither was read.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_internal_posts_answer_the_bridge_gate_before_their_route_runs fails at line 132\non `report[\"valid\"] == {**{path: [200, {\"stub\": path}] ...}, ...}`. Without `router`,\nthe child writes its stubs into an unwired SimpleNamespace table. The hard-coded\n`_dispatch_post` in handlers/similar.py:442-478 then sends the valid-token POSTs to the\nreal `handle_internal_*` functions and the 501 ingest branch, not to the stubs. Lines\n125-130 pass today because the existing prefix gate at similar.py:445 already answers\n401 for these requests, and the ingest 501 at similar.py:466-475 already reports\n`mode: None`.\ntest_a_route_added_as_one_get_routes_entry_is_served_through_the_real_handler fails at\nline 146 on `report[\"after\"] == [200, {\"fake\": True, \"path\": \"/fake?x=1\"}]`. Today's\n`_dispatch_get` never reads the stand-in `GET_ROUTES`, so it answers [404, {\"error\": \"Not found\"}].\n\nNOT ASSESSED\n1. `code_under_test` engine/server/api/router.py does not resolve. It is marked NEW, so\n   the stub question was answered from the assertion form and today's\n   handlers/similar.py dispatch.\n2. `code_under_test` tests/tmp/test_router_bridge_auth.py and\n   tests/tmp/test_router_fake_route.py do not resolve. Neither one is imported by the\n   test under audit.\n3. For the valid-token requests at line 132, I did not work out what status the real\n   `handle_internal_*` functions give with `db` None. The prediction only claims the\n   response is not the stub's [200, {\"stub\": path}].\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 7 must_prove, 14 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | every POST to `/internal/*`, unknown path included, answers 401 when the token is missing | :127 | a gate checked after the table lookup (the stubbed paths would read 200); a gate that covers known routes only (`/internal/no-such-route` would read 404) | CARRIED |\n| C1b | must_prove | 401 when the token is wrong | :129 | a prefix or containment compare that accepts `TOKEN[:-1]` | CARRIED |\n| C1c | must_prove | 503 when the Engine has no token set | :135 | a fallback to another token, or `\"\"` accepted as a token (would read 401 or the stub's 200) | CARRIED |\n| C1d | must_prove | the gate answers before the `POST_ROUTES` entry runs | :130, :136 | a gate that answers 401/503 after the entry has run: the stub records the request | CARRIED |\n| C1e | must_prove | past the gate, the `POST_ROUTES` entry is what runs, so the empty record means something | :132, :133 | dispatch that skips the table, or a table copied at import (would answer the real handlers' codes, not the stub's 200) | CARRIED |\n| C2a | must_prove | a route added as one `GET_ROUTES` entry is served, with no edit to `handlers/similar.py` | :144, :146 | a table bound or copied at import; dispatch that hardcodes each path in `similar.py` (`/fake` stays 404) | CARRIED |\n| C2b | must_prove | served through the real `SimilarHandler` | :148 | the entry being called by some other handler class, or without the serving `SimilarServer` | CARRIED |\n| D1 | docstring | \"over real HTTP into a real `SimilarServer` running the real `SimilarHandler` in an Engine child\" | :118, :148 | a child that never built the server or never ran the requests (non-zero exit); the wrong handler type | CARRIED |\n| D2 | docstring | 401 `Unauthorized` without `X-Bridge-Token` on the four paths | :127 | the same as C1a | CARRIED |\n| D3 | docstring | 401 with a near-miss token (the real token less its last character) | :129 | the same as C1b | CARRIED |\n| D4 | docstring | 503 with the exact message once the Engine's token is `\"\"` | :135 | the same as C1c, plus a wrong body | CARRIED |\n| D5 | docstring | \"None of those requests reaches its route\": the stubs record nothing | :130, :136 | the same as C1d | CARRIED |\n| D6 | docstring | \"With the right token each stub is reached exactly once\" | :133 | a stub hit twice, or a stub skipped (exact list equality) | CARRIED |\n| D7 | docstring | with the right token, the unknown path answers 404 `Not found` | :132 | the unknown path falling through to a stub, or answering some other status | CARRIED |\n| D8 | docstring | before the stubs, a valid-token ingest under mode None answers the 501 with `mode: None` | :125 | a stub installed too early; a lost 501 branch | CARRIED |\n| D9 | docstring | GET `/internal/videos/resolve` answers a plain 404, with no gate | :138 | a gate on GET too (it would answer 503, because `bridge_token` is `\"\"` from :86) | CARRIED |\n| D10 | docstring | before the entry, GET `/fake` answers 404 | :144 | something already serving `/fake`, which would make the 200 at :146 meaningless | CARRIED |\n| D11 | docstring | after the entry, GET `/fake?x=1` answers 200 with a body carrying the raw path, query included | :146 | an entry not called for this request; a body or path rewritten on the way | CARRIED |\n| D12 | docstring | the entry is called with the serving `SimilarHandler` and the `SimilarServer` itself | :148 | a different handler or server object passed in | CARRIED |\n| D13 | docstring | exact-path matching on GET: GET `/fake/` answers 404 | :150 | prefix matching | CARRIED |\n| D14 | docstring | GET-only: POST `/fake` answers 404 | :151 | a table that ignores the method | CARRIED |\n| N1 | name | \"internal posts answer the bridge gate\" | :127, :129, :135 | the same as C1a\u2013C1c | CARRIED |\n| N2 | name | \"before their route runs\" | :130, :136 | the same as C1d | CARRIED |\n| N3 | name | \"a route added as one get_routes entry is served\" | :146 | the same as C2a | CARRIED |\n| N4 | name | \"through the real handler\" | :148 | the same as C2b | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:82\n   `report[\"near_miss\"] = {p: send(port, \"POST\", p, {\"X-Bridge-Token\": TOKEN[:-1]}) for p in PATHS}`\n   The only wrong token sent is one character short. C1b says \"wrong\", and two kinds of wrong token are never sent: one the same length that differs in a character, and the real token with a character added. A `presented.startswith(configured)` compare would pass :129.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:87\n   The 503 is only checked with the real token in the request. The case where the Engine has no token set and the request carries none is never sent. So a gate that answers 401 for a missing token before it checks the Engine's own token is not ruled out. C1 does not say which answer wins when both conditions hold, so this is not blocking.\n3. No rule in testing.md covers this \u2014 tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:137\n   The comment says \"a gate on both methods reads 401 here\". But :86 sets `srv.bridge_token = \"\"` before the GET at :89, so a gate on GET would answer 503. The assertion at :138 still rules that gate out. Only the comment's stated status is wrong.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/api/router.py, which does not exist. Three things the test assumes could not be checked against it: the `GET_ROUTES` / `POST_ROUTES` names, the `(handler, server)` signature of an entry, and whether the router itself answers the gate and the ingest 501. I judged the clauses from the test, from the dispatch in the current `handlers/similar.py`, and from `SimilarServer.__init__`.\n2. `code_under_test` lists tests/tmp/test_router_bridge_auth.py and tests/tmp/test_router_fake_route.py. Neither exists, so neither was read.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "every POST to `/internal/*`, unknown path included, answers 401 when the token is missing",
            "assertion": ":127",
            "excludes": "a gate checked after the table lookup (the stubbed paths would read 200); a gate that covers known routes only (`/internal/no-such-route` would read 404)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "401 when the token is wrong",
            "assertion": ":129",
            "excludes": "a prefix or containment compare that accepts `TOKEN[:-1]`",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "503 when the Engine has no token set",
            "assertion": ":135",
            "excludes": "a fallback to another token, or `\"\"` accepted as a token (would read 401 or the stub's 200)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "the gate answers before the `POST_ROUTES` entry runs",
            "assertion": ":130, :136",
            "excludes": "a gate that answers 401/503 after the entry has run: the stub records the request",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "past the gate, the `POST_ROUTES` entry is what runs, so the empty record means something",
            "assertion": ":132, :133",
            "excludes": "dispatch that skips the table, or a table copied at import (would answer the real handlers' codes, not the stub's 200)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a route added as one `GET_ROUTES` entry is served, with no edit to `handlers/similar.py`",
            "assertion": ":144, :146",
            "excludes": "a table bound or copied at import; dispatch that hardcodes each path in `similar.py` (`/fake` stays 404)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "served through the real `SimilarHandler`",
            "assertion": ":148",
            "excludes": "the entry being called by some other handler class, or without the serving `SimilarServer`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"over real HTTP into a real `SimilarServer` running the real `SimilarHandler` in an Engine child\"",
            "assertion": ":118, :148",
            "excludes": "a child that never built the server or never ran the requests (non-zero exit); the wrong handler type",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "401 `Unauthorized` without `X-Bridge-Token` on the four paths",
            "assertion": ":127",
            "excludes": "the same as C1a",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "401 with a near-miss token (the real token less its last character)",
            "assertion": ":129",
            "excludes": "the same as C1b",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "503 with the exact message once the Engine's token is `\"\"`",
            "assertion": ":135",
            "excludes": "the same as C1c, plus a wrong body",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"None of those requests reaches its route\": the stubs record nothing",
            "assertion": ":130, :136",
            "excludes": "the same as C1d",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"With the right token each stub is reached exactly once\"",
            "assertion": ":133",
            "excludes": "a stub hit twice, or a stub skipped (exact list equality)",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "with the right token, the unknown path answers 404 `Not found`",
            "assertion": ":132",
            "excludes": "the unknown path falling through to a stub, or answering some other status",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "before the stubs, a valid-token ingest under mode None answers the 501 with `mode: None`",
            "assertion": ":125",
            "excludes": "a stub installed too early; a lost 501 branch",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "GET `/internal/videos/resolve` answers a plain 404, with no gate",
            "assertion": ":138",
            "excludes": "a gate on GET too (it would answer 503, because `bridge_token` is `\"\"` from :86)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "before the entry, GET `/fake` answers 404",
            "assertion": ":144",
            "excludes": "something already serving `/fake`, which would make the 200 at :146 meaningless",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "after the entry, GET `/fake?x=1` answers 200 with a body carrying the raw path, query included",
            "assertion": ":146",
            "excludes": "an entry not called for this request; a body or path rewritten on the way",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "the entry is called with the serving `SimilarHandler` and the `SimilarServer` itself",
            "assertion": ":148",
            "excludes": "a different handler or server object passed in",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "exact-path matching on GET: GET `/fake/` answers 404",
            "assertion": ":150",
            "excludes": "prefix matching",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "GET-only: POST `/fake` answers 404",
            "assertion": ":151",
            "excludes": "a table that ignores the method",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"internal posts answer the bridge gate\"",
            "assertion": ":127, :129, :135",
            "excludes": "the same as C1a\u2013C1c",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"before their route runs\"",
            "assertion": ":130, :136",
            "excludes": "the same as C1d",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"a route added as one get_routes entry is served\"",
            "assertion": ":146",
            "excludes": "the same as C2a",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"through the real handler\"",
            "assertion": ":148",
            "excludes": "the same as C2b",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nengine/server/api/handlers/similar.py \u2014 merged the identical `_serve_post` and `_serve_get` into one `_serve(route)` method. `do_POST` and `do_GET` now call `self._run_request(lambda: self._serve(route_post))` and `lambda: self._serve(route_get)`, the same lambda style `do_OPTIONS` already uses. The statement deadline, the interrupted-503 and the re-raise of other errors are unchanged. Nothing in engine/ or tests/ referenced the two old method names.\nengine/server/api/router.py \u2014 `_events_ingest` now reads `getattr(server, \"engine_ingest_mode\", \"bridge\")` once into `mode` and uses it for both the check and the 501 body's `mode` field, instead of calling getattr twice.\n</refactors>\n\n<left_out>\nrouter.py `_extract_video_id_from_similar_path`: the `startswith`/`endswith` check looks redundant next to the segment check, but it isn't. `strip(\"/\")` would let `/videos/x/similar/` through, and the endswith check is what rejects it. Removing it would change behaviour, so I left it.\nrouter.py `route_get`: the two identical 429 blocks (the `/api/` gate and the pattern route's own limiter) stay as they are. A helper would add about as much code as it removes, and the pattern block is the one the rat-tail comment marks for replacement with a matcher list later.\nsimilar.py `_recommendations_likes_payload_error`: its `path not in SIMILAR_POST_ROUTES` guard can never fire from the router now, because only SIMILAR_POST_ROUTES paths reach `_handle_similar_request`. I kept it because it is that function's own contract, and direct callers or tests may pass other paths.\nengine/server/README.md and handlers/__init__.py docstring: not touched. The plan's docs checklist left them to operator decision.\ntests/tmp/probe_router_import.py (outside the files named): I reused the earlier probe file for this pass's check instead of creating another one. I have no tool that deletes files, so it is still there: please delete it. It is named `probe_*`, so default pytest collection skips it.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nAn Engine-interpreter probe run through ValidateTests confirmed the refactored code. `SimilarHandler._serve` calls the route with the handler. An interrupted OperationalError gives `_respond_interrupted`, and a \"disk I/O error\" one is re-raised. `_serve_get` and `_serve_post` no longer exist. `_events_ingest` answers 501 with `mode: None` for `engine_ingest_mode=None`, and passes through to ingest for \"bridge\" and when the attribute is absent. I did not run the phase checkpoint or the suite.\n</observation>"
}
```
dev-flow:state -->

## 2026-10-04 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/58",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Start snapshot: tree `4ad7ae9b9c41fab0b9d593d9fd49de130830be31` at 2026-10-04T09:44:00-04:00.

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 63 test groups (62 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.8s
  ---------------------
  total                  10 passed                              2.0s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

The brief's criterion "every route listed in the Engine server README answers as before" doesn't match the README itself: its route list (`engine/server/README.md:7-27`) leaves out `/api/health`, `/api/channels` and `/api/v1/search/videos`, all of which `_dispatch_get` serves. The operator chose to leave the README unchanged, so the criterion is widened to every route the Engine serves.
The brief says to move the route list out of similar.py's docstring, but that docstring (`similar.py:1-20`) already leaves out `/internal/dislikes/centroids` and `/api/v1/search/videos`, which the dispatch serves. The router docstring has to list them, so it won't be a verbatim move.
The brief says the router owns "the `/api/` rate-limit gate on GET", but the tree also rate-limits GET `/videos/{id}/similar` in dispatch (`similar.py:555`), on a path outside `/api/`. The brief doesn't mention this second gate, and keeping behaviour identical means the router must keep it.

## 2026-10-04 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-10-04 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

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

### docs_checklist

<doc path="engine/server/api/router.py">
New module docstring: the complete Engine route list with method and gate per route. That means every route from the old similar.py docstring, plus `/internal/dislikes/centroids` and `/api/v1/search/videos`, with `/api/health` and `/api/channels` kept. `/internal/*` POST routes are marked as behind the bridge-auth gate, `/api/*` GET routes as behind the rate-limit gate, `/videos/{id}/similar` as having its own rate-limit check, and `/internal/events/ingest` as answering 501 outside bridge mode.
</doc>
<doc path="engine/server/api/handlers/similar.py">
Module docstring rewritten to describe only recommendations, similar, feeds and search, with the route list removed and a pointer to `api/router.py`. The `do_GET`/`do_POST` docstrings are reworded to "hand the request to the router", and `_serve_get`/`_serve_post` now say they route instead of dispatching.
</doc>
<doc path="engine/server/api/handlers/__init__.py">
Optional, not in the plan: the package docstring calls `similar` the "main Engine read handler for recommendations and read endpoints". A reword could note that routing now lives in `api/router.py`. Operator's call.
</doc>
<doc path="engine/server/README.md">
No edit, by operator decision. I verified that its references to `SimilarHandler._run_request` (line 53) and `_parse_include_nsfw` (line 50) in `api/handlers/similar.py` stay true. Its route list (lines 7-27) stays incomplete; router.py becomes the complete list.
</doc>

### highest_risk

engine/server/api/router.py route_get/route_post — every Engine request now flows through it. Gate order (bridge check before any POST lookup, unknown /internal/ included; /api/ rate limit before the GET lookup, unknown /api/ included; then rate-limit → setdefault → _handle_similar on the pattern route), byte-identical 401/503/429/501/404 bodies, and per-request table lookup must all be reproduced exactly. A broken handle_health also breaks the readiness probe of every Engine-child test fixture.
engine/server/api/handlers/similar.py imports and helper renames — router must never import handlers.similar, or there is a partial-module cycle on server.py's import path. The four remaining _parse_int/_parse_non_negative_int call sites (584, 588, 1035, 1062) must be renamed, and a miss only raises NameError at request time on search or seeded/limited similar, which a narrow test run may not hit.
engine/server/api/router.py events-ingest adapter (501 ingest-mode check) — no existing test covers the 501 path, and the planned bridge-auth test replaces this adapter with a stub, so a copying mistake in the mode check or its body would ship unnoticed. Test servers built with dict.fromkeys also carry engine_ingest_mode=None, so any test that hits the real adapter gets 501.

## 2026-10-04 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I checked the inventory against the files it names, and the plan holds up. similar.py matches every line range the inventory cites: the docstring at 1-20, `hmac` at 22, `fetch_channels` at 36, the bridge constants at 52/58, the four handler imports at 96-103, `SIMILAR_POST_ROUTES` at 106 and its reader at 234, `_bridge_authorized` at 417-440, `_dispatch_post` at 442-478, `_dispatch_get` at 494-562, `_rate_limit_check` at 632-639, and the helpers at 1167/1191/1267. Grep finds exactly four parse call sites that stay (584, 588, 1035, 1062) and five in channels that move (511, 515, 516, 524, 525). No other module in `engine/server/api` imports `handlers.similar` (the only cross-import is internal_translate → handlers.video), and `handlers/__init__.py` imports nothing. So `similar → router → handlers.internal_*/video` has no cycle, whether `similar` or `router` is imported first. No test calls or patches `_dispatch_*`, `_bridge_authorized`, `_extract_video_id_from_similar_path`, `similar._parse_*`, `similar.fetch_channels`, `similar.handle_*` or the bridge constants. No test reads similar.py's source text except the AST read of `FEED_MODES`. `SimilarServer.__init__` does not touch `db` beyond storing it, and it always sets `bridge_token` (290) and `engine_ingest_mode` (283). The test_video.py children build the server with `dict.fromkeys`, so `engine_ingest_mode` and `rate_limiter` are None there, as the inventory says. I found nothing the inventory is missing.
<question id="1">
Yes. Every branch of `_dispatch_get` and `_dispatch_post` maps onto a table entry, an adapter, a prefix gate or the one pattern branch. Gate order, 404s, 429s, 501 and bridge bodies stay the same. Calling `route_get(self)` and `route_post(self)` inside the unchanged `_serve_*` wrapper keeps the statement deadline and the interrupted-503 around all routing. Imports resolve in every place that loads similar.py today, because each of those already has the api dir on `sys.path` as a root (seen at test_similar.py:195 and test_video.py's children). The `[bridge.auth]` log lines stay byte-identical as long as the message text and the root-logger calls are copied exactly.
</question>
<question id="2">
1. Every Engine request now goes through a new module, so a mistake there shows up everywhere. A broken `handle_health` alone would time out every Engine-child fixture.
2. Four underscore-prefixed `SimilarHandler` methods (`_rate_limit_check`, `_handle_similar_request`, `_handle_similar`, `_handle_search`), plus `_get_client_ip`, become a cross-module contract that is only checked when a request arrives.
3. Table entries hold function references, so tests have to patch the table and not the handler modules. No current test patches the handler modules.
4. The parse helpers become public in `http_utils`.
5. The 501 ingest-mode branch has no test today, and the planned test swaps its adapter out, so it stays untested.
6. `tests/config.json` maps no test group to `router.py`, so a later edit to the router alone would select no tests.
</question>
<question id="3">
Nothing beyond what the plan and inventory already list:
- rename the four remaining parse call sites in similar.py;
- import `SIMILAR_POST_ROUTES` back into similar.py so `_recommendations_likes_payload_error` keeps reading it as a module global (test_recommendations_likes_limit.py and test_similar.py rely on that);
- keep `FEED_MODES` as a module-level tuple literal in similar.py;
- keep `urlparse`, `parse_qs` and `now_ms` imported in similar.py;
- leave `server.py` and `SimilarServer` untouched.

Grep after the edit for `_parse_int`, `_parse_non_negative_int`, `fetch_channels`, `hmac` and `ENGINE_BRIDGE_TOKEN` in similar.py. A missed rename only fails when a search or a seeded similar request runs, not at import.
</question>
<question id="4">
No request behaves differently: same status, body, headers and log lines on every route and gate. What changes is code structure and naming: routing and bridge auth move to `router.py`; `_parse_int`/`_parse_non_negative_int` become `http_utils.parse_int`/`parse_non_negative_int`; `SIMILAR_POST_ROUTES` is owned by the router. Adding a route becomes a table entry plus one import in `router.py`, and routes can now be added at runtime by changing a table, which the fake-route test relies on.
</question>


New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Test the 501 ingest branch in the planned bridge-auth test.** Add one valid-token POST to `/internal/events/ingest` while the router's real ingest adapter is still in `POST_ROUTES`, under the `dict.fromkeys` server whose `engine_ingest_mode` is None. Assert 501 `{"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": null}`, then swap in the stub for the auth cases. Change: the only branch the move currently leaves unverified gets checked, and so do the adapter's body and its `mode` field. Cost: about five lines in a test file that is being written anyway, and no extra child process.

2. **Add a valid-token POST to the unknown `/internal/` path in the same test, expecting 404 `{"error": "Not found"}`.** Change: it shows the unknown path gets 401 because the gate stopped it, not because nothing was routed there. Cost: one request and one assert.

3. **Add `engine/server/api/router.py` to the `tests/config.json` groups that already list `engine/server/api/handlers/similar.py`.** These include `test_similar.py`, `test_video.py`, `test_internal_translate.py` and `test_server.py`. Change: a later edit to the router alone selects the suites that cover routing. Cost: a few JSON lines. This is a process file, so the operator decides whether builds edit it.

4. **Optionally reword `engine/server/api/handlers/__init__.py` line 4** so it says routing lives in `api/router.py`. Change: the package docstring stops implying that `similar` routes. Cost: one docstring line, no runtime effect. Skipping it leaves a slightly stale but not wrong description.

5. **No test-double recommendation is needed.** The plan widens no existing double. The stub handlers in test_similar.py (around 240-265, 362, 471, 979) and test_recommendations_likes_limit.py call the similar methods directly and never go through the router, so their recorded calls and expected sequences are unchanged. The new tests' recording stubs are the plan's own, and each has a control showing it is wired in.

## 2026-10-04 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-10-04 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Engine routing moves into router.py [code]

**Files touched.** engine/server/api/router.py (NEW), engine/server/api/http_utils.py (EDITED), engine/server/api/handlers/similar.py (EDITED), tests/tmp/test_router_bridge_auth.py (NEW), tests/tmp/test_router_fake_route.py (NEW)

**Checkpoint.** Seam: real HTTP requests into a real `SimilarServer` running the real `SimilarHandler` on an ephemeral port. The server runs in an Engine child process (`ENGINE_PY -c CHILD`, cwd `engine/server/api`), which imports `server` first so the `sys.path` setup runs. The server is built with `dict.fromkeys(signature params[3:])`. This copies the existing child harness in `tests/active/test_video.py`, the precedent for this seam. The only shim is a replaced router table entry, never a patched module function, because dispatch looks up the table per request. `tests/tmp/test_router_bridge_auth.py` (clause_1) replaces the `POST_ROUTES` entries for `/internal/videos/resolve`, `/internal/translate` and `/internal/events/ingest` with recording stubs. It then asserts, for those three paths plus `/internal/no-such-route`: 401 `{"error": "Unauthorized"}` with no token; 401 again with a wrong token; zero stub calls after both; 503 `{"error": "Bridge token is not configured on the Engine"}` after `srv.bridge_token = ""`, with no new stub calls. A valid-token control reaches each stub exactly once and gets 404 on the unknown path. Without that control, the zero counts would prove nothing. Beyond the clause, the same test asserts the ingest adapter's 501 body with `mode: None` and the ungated plain 404 for GET `/internal/videos/resolve`. `tests/tmp/test_router_fake_route.py` (clause_2) asserts that GET `/fake` answers 404 `{"error": "Not found"}` before `router.GET_ROUTES["/fake"]` is set. After it is set, GET `/fake?x=1` answers 200 with the stub's body carrying the raw path, which proves the request reached the stub through the real handler. Existing suites cover everything else unchanged: test_video, test_internal_translate 1044-1074, test_server `/api/channels`, the conftest `/api/health` probe, test_similar and test_recommendations_likes_limit.

**Intent.** Every Engine GET and POST that `SimilarHandler` receives is answered by `engine/server/api/router.py`, through its `/internal/` bridge gate, its `/api/` rate-limit gate and its `GET_ROUTES`/`POST_ROUTES` tables. `SimilarHandler`'s own `_dispatch_*` and `_bridge_authorized` methods no longer exist.

- C1 - Every POST to an `/internal/*` path, unknown paths included, gets the router's bridge-gate answer before its `POST_ROUTES` entry runs: 401 when the token is missing or wrong, 503 when the Engine has none set.
- C2 - A route added as one `GET_ROUTES` entry, with no edit to `handlers/similar.py`, is served through the real `SimilarHandler`.

**Outcome.** _pending_


Needs coordination: none

Rationale: One phase, because no coherent intermediate state can be verified on its own. The parse-helper move to `http_utils.py` has no observable behaviour; it is covered only by the call sites in the router and similar.py, so as a separate phase it would have no checkpoint. Moving POST routing before GET routing would leave dispatch split between the router and `SimilarHandler`, and the plan does not describe that state. All of the router, `http_utils.py` and similar.py have to land together for imports to resolve and requests to route. The phase's intent cuts into two observable facts, and each one maps to one of the two new tests the draft supplies. The tests' extra assertions (the ingest 501 body and the ungated GET `/internal` 404) are cheap regression cover for gaps the impact inventory named, not extra clauses. Everything else in the pure-move contract is covered by the existing suites, which run unchanged. The work involves no prose or agent-facing text. The README and `handlers/__init__.py` docstring are documentation, so they get no phase. The operator approved this plan.

## 2026-10-04 - Step 7 - Phase 1 (Engine routing moves into router.py) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
Every Engine GET and POST that `SimilarHandler` receives is answered by `engine/server/api/router.py`, through its `/internal/` bridge gate, its `/api/` rate-limit gate and its `GET_ROUTES`/`POST_ROUTES` tables. `SimilarHandler`'s own `_dispatch_*` and `_bridge_authorized` methods no longer exist.

- C1 - Every POST to an `/internal/*` path, unknown paths included, gets the router's bridge-gate answer before its `POST_ROUTES` entry runs: 401 when the token is missing or wrong, 503 when the Engine has none set.
- C2 - A route added as one `GET_ROUTES` entry, with no edit to `handlers/similar.py`, is served through the real `SimilarHandler`.

must_prove:
- C1 - Every POST to an `/internal/*` path, unknown paths included, gets the router's bridge-gate answer before its `POST_ROUTES` entry runs: 401 when the token is missing or wrong, 503 when the Engine has none set.
- C2 - A route added as one `GET_ROUTES` entry, with no edit to `handlers/similar.py`, is served through the real `SimilarHandler`.

## 2026-10-04 - Step 7 - Phase 1 (Engine routing moves into router.py) - self-check (audit round 1, send-back 0)

`tests/tmp/test_58_engine_routing_out_of_similar_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:127 — POST to /internal/videos/resolve, /internal/translate, /internal/events/ingest and /internal/no-such-route with no X-Bridge-Token, after the three POST_ROUTES entries were replaced by recording stubs, each answers [401, {"error": "Unauthorized"}] - expected: {path: [401, {"error": "Unauthorized"}] for all four paths}. The run showed this, and the line passed against today's gate. - excludes: A route_post that looks up POST_ROUTES before it runs the gate reads [200, {"stub": path}] for the three stubbed paths. A gate that only covers paths in the table reads [404, {"error": "Not found"}] for /internal/no-such-route.
- C1 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:129 — the same four POSTs carrying a near-miss token (the real token less its last character) each answer [401, {"error": "Unauthorized"}] - expected: {path: [401, {"error": "Unauthorized"}] for all four paths}. Observed passing in the run. - excludes: A startswith or containment compare in place of hmac.compare_digest accepts "router-test-toke" and reads the stub's [200, {"stub": path}], or 404 for the unknown path.
- C1 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:130 — the stubs recorded no call across the missing-token and near-miss requests - expected: [] (observed). Lines 132-133 arm it: with the valid token every stub is reached. - excludes: A gate that writes the 401 but still falls through to the table entry (a missing return after a False bridge_authorized) records every stubbed path here, while the status lines could still read 401 first.
- C1 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:132 — with the valid token, the three stubbed paths answer the stub's [200, {"stub": path}] and /internal/no-such-route answers [404, {"error": "Not found"}] - expected: {"/internal/videos/resolve": [200, {"stub": "/internal/videos/resolve"}], "/internal/translate": [200, {"stub": "/internal/translate"}], "/internal/events/ingest": [200, {"stub": "/internal/events/ingest"}], "/internal/no-such-route": [404, {"error": "Not found"}]}. The stub response shape [200, {"stub": path}] came from a probe run through a real SimilarHandler. The 404 body for the unknown path was observed in this run. - excludes: Today's code, observed in this run: it dispatches through SimilarHandler's own if-chain instead of POST_ROUTES and reads [400, {"error": "Missing video_id or uuid"}], [400, {"error": "Missing id or host"}] and [501, {... "mode": None}]. A table copied or bound at import reads the same.
- C1 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:133 — the stubs were reached exactly once each, in request order - expected: ["/internal/videos/resolve", "/internal/translate", "/internal/events/ingest"] (the recording shape was observed in the probe as calls == ["/stubbed"]) - excludes: Dispatch that bypasses the table records [], the current state. A route_post that calls the entry twice, or calls it for rejected requests too, records extra entries.
- C1 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:135 — after srv.bridge_token = "", the four POSTs with the formerly valid token each answer [503, {"error": "Bridge token is not configured on the Engine"}] - expected: {path: [503, {"error": "Bridge token is not configured on the Engine"}] for all four paths}. The probe run observed this body for a known path and for an unknown path. This test does not reach line 135 yet, because it stops at line 132. - excludes: A gate that falls back to ENGINE_BRIDGE_TOKEN when the attribute is falsy (`server.bridge_token or ENGINE_BRIDGE_TOKEN`; the env value is "") still reads 503. One that treats "" as a token reads 401. One that skips the check when unset reads the stub's 200, or 404 for the unknown path.
- C1 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:136 — the 503 requests added no stub call (the record is still exactly STUBBED) - expected: ["/internal/videos/resolve", "/internal/translate", "/internal/events/ingest"] - excludes: An unset-token branch that writes the 503 but falls through to the entry appends the three stubbed paths again: six entries.
- C2 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:146 — after router.GET_ROUTES["/fake"] = fake, GET /fake?x=1 answers the entry's [200, {"fake": True, "path": "/fake?x=1"}] - expected: [200, {"fake": True, "path": "/fake?x=1"}]. Observed in the probe, where the same function was driven from a real SimilarHandler; handler.path keeps the query string. - excludes: Today's code, observed in this run: SimilarHandler's own _dispatch_get never consults a table, so it reads [404, {"error": "Not found"}]. A route_get that binds or copies GET_ROUTES at import reads the same 404. A lookup keyed on the raw path, query included, misses "/fake" and also reads 404.
- C2 - tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:148 — the entry was called exactly once, with type(handler) is SimilarHandler and server is the running SimilarServer - expected: [{"handler_is_similar": True, "server_is_srv": True}]. Observed in the probe, with isinstance against a SimilarHandler subclass; here the server is built with SimilarHandler itself. - excludes: A router that calls entries with a wrapper or adapter object, or with the module-level default server, reads False in the matching field. Calling the entry for /fake/ or for POST adds a second record. Today nothing calls it, so the record reads [].

<assertions>
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:112 - control: the Engine child exits 0, meaning it imported `router`, built the real SimilarServer/SimilarHandler and sent every request. Before the phase this fails with `ModuleNotFoundError: No module named 'router'` (observed), which is the checkpoint's expected red.
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:119 - extra, not a clause: before any stub goes in, a valid-token POST /internal/events/ingest with engine_ingest_mode None gets the router adapter's 501 `{"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": None}`.
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:121 - all four of /internal/videos/resolve, /internal/translate, /internal/events/ingest and /internal/no-such-route answer 401 `{"error": "Unauthorized"}` with no X-Bridge-Token. Fails if the gate runs after the table lookup (stub's 200) or covers only known routes (404 on the unknown path). C1
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:123 - the same four answer 401 with a near-miss token (the real token minus its last character). Fails if the token check is a prefix or containment compare instead of an exact match. C1
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:124 - the recording stubs in POST_ROUTES saw no call after the missing-token and wrong-token requests. Shows the gate answered before the entry ran. C1
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:126 - control: with the valid token, each stubbed path answers the stub's `[200, {"stub": path}]` and the unknown path answers 404 `{"error": "Not found"}`. Fails if the table was copied at import, and without it the zero count at :124 would prove nothing.
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:127 - control: the stubs were reached exactly once each, in request order.
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:129 - after `srv.bridge_token = ""`, all four answer 503 `{"error": "Bridge token is not configured on the Engine"}` even with the previously valid token. Fails if "" counts as a token or the check falls back to another token. C1
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:130 - the 503 requests added no stub calls (the record is still exactly the three valid-token calls). C1
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:132 - extra, not a clause: GET /internal/videos/resolve answers a plain 404 with no gate, so a gate applied to both methods would fail here.
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:138 - control: GET /fake answers 404 `{"error": "Not found"}` before the GET_ROUTES entry exists, so the later 200 can only come from the entry.
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:140 - after `router.GET_ROUTES["/fake"]` is set (and only that is touched, no edit to handlers/similar.py), GET /fake?x=1 answers 200 `{"fake": True, "path": "/fake?x=1"}`. The raw path, query included, shows the entry answered this request. A table bound or copied at import still answers 404. C2
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:142 - the entry was called exactly once, with `type(handler) is SimilarHandler` and with `server` being the SimilarServer instance itself, which carries "served through the real SimilarHandler". C2
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:144 - extra, not a clause: GET /fake/ still answers 404 after the entry is set, so matching is exact-path and a prefix match would fail.
tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:145 - extra, not a clause: POST /fake still answers 404, so a GET_ROUTES entry serves GET only and a table that ignores the method would fail.
</assertions>

<probes>
Probe 1. I wrote tests/tmp/test_probe_58_seam.py, which starts an Engine child against the current (pre-router) code: `server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **dict.fromkeys(params[3:]))` with `srv.bridge_token = "tok-abc"`. I ran it with ValidateTests ["tests/tmp/test_probe_58_seam.py", "-s"]. It printed:
- ENGINE_PY exists: True. Child rc 0. `importlib.util.find_spec("router")` is None, so no `router` module exists yet and nothing in the Engine env collides with that name.
- env ENGINE_BRIDGE_TOKEN is null, so `srv.bridge_token` defaults to "" in the child. That is why the test sets it explicitly; left alone, every request would get the 503.
- srv.engine_ingest_mode is None.
- POST /internal/no-such-route with no token: [401, {"error": "Unauthorized"}]. With token "tok-ab": [401, {"error": "Unauthorized"}]. With the valid token: [404, {"error": "Not found"}].
- POST /internal/events/ingest with the valid token: [501, {"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": null}].
- GET /internal/videos/resolve with the valid token: [404, {"error": "Not found"}]. GET /fake: [404, {"error": "Not found"}].
- after `srv.bridge_token = ""`, POST /internal/translate: [503, {"error": "Bridge token is not configured on the Engine"}].
- stderr: `WARNING:root:[bridge.auth] rejected ... from ip=127.0.0.1` and `ERROR:root:[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting ...`.

Probe 2. The same probe file, rewritten to load the checkpoint module and run its own PRELUDE (with only `import router\n` removed) plus a flow that passes json.dumps(STUBBED) as argv. Same ValidateTests command. It printed:
- rc 0, and argv arrived as the JSON list.
- ingest_mode [501, {..., "mode": null}]; missing [401, Unauthorized]; near_miss (TOKEN[:-1]) [401, Unauthorized]; get_internal [404, Not found]; GET /fake [404]; GET /fake/ [404]; POST /fake [404]; unset [503, configured-token body].
- `send` to a refused port returned [null, "ConnectionRefusedError(111, 'Connection refused')"], so a dropped connection reads as a value in the report rather than crashing the child.
- the unmodified FAKE_CHILD exits 1 with `ModuleNotFoundError: No module named 'router'`, the expected pre-phase red.

Not observed, and not observable until router.py exists: that replacing `router.POST_ROUTES[...]` or `router.GET_ROUTES["/fake"]` changes dispatch, and the post-phase values at :126, :127, :140 and :142 (the stub's 200, the call records, handler/server identity). These are predictions from the plan's route_get/route_post draft, which looks each table up per request and calls `route(handler, handler.server)`. The phase's own validate_tests run of this file is what confirms them.

Cleanup. The probe is spent. I have no delete tool, so I overwrote tests/tmp/test_probe_58_seam.py with a single comment line (it collects no tests). That file should be deleted; it is outside the one file this step names.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_58_engine_routing_out_of_similar_phase1.py` - 8221 characters, inlined in full

```
"""Engine routing through `engine/server/api/router.py`, over real HTTP into a real `SimilarServer` running the real `SimilarHandler` in an Engine child.

Bridge gate (POST `/internal/*`):

- The Engine token set, a POST to `/internal/videos/resolve`, `/internal/translate`, `/internal/events/ingest` or the unknown `/internal/no-such-route` answers 401 `{"error": "Unauthorized"}` without an `X-Bridge-Token` and with a near-miss one (the real token less its last character), and 503 `{"error": "Bridge token is not configured on the Engine"}` once the Engine's token is "".
- None of those requests reaches its route: the three routes' `POST_ROUTES` entries are recording stubs, which record nothing for them. With the right token each stub is reached exactly once, and the unknown path answers 404 `{"error": "Not found"}`.
- Before the stubs go in, a valid-token ingest under `engine_ingest_mode` None answers the router's own 501 with `mode: None`.
- A GET to `/internal/videos/resolve` answers a plain 404, with no gate.

Fake route (one `GET_ROUTES` entry, no edit to `handlers/similar.py`):

- Before the entry, GET `/fake` answers 404 `{"error": "Not found"}`.
- After `router.GET_ROUTES["/fake"]` is set, GET `/fake?x=1` answers 200 with the entry's body, which carries the raw request path, query included; the entry was called with the `SimilarHandler` serving the request and the `SimilarServer` itself.
- The entry serves only its exact path on GET: GET `/fake/` and POST `/fake` still answer 404.

The only shim is a replaced router table entry, never a patched module function: dispatch looks the table up per request. The server is built the `tests/active/test_video.py` way (`dict.fromkeys` over the constructor's parameters), so `db`, `rate_limiter` and `engine_ingest_mode` are None; none of these paths reaches the DB.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# tests/tmp has no conftest, and tests/active's loads the Client backend: the same two expressions as conftest's, until this file is archived to tests/active.
ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
API_DIR = ROOT / "engine" / "server" / "api"

STUBBED = ["/internal/videos/resolve", "/internal/translate", "/internal/events/ingest"]
PATHS = STUBBED + ["/internal/no-such-route"]
UNAUTHORIZED = [401, {"error": "Unauthorized"}]
UNSET = [503, {"error": "Bridge token is not configured on the Engine"}]
NOT_FOUND = [404, {"error": "Not found"}]

# Shared by both children: `server` first, so its sys.path setup puts engine/server on the path.
PRELUDE = r'''
import http.client, inspect, json, sys, threading
import server
import router
from handlers.similar import SimilarHandler
from http_utils import respond_json

def send(port, method, path, headers=None):
    try:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        client.request(method, path, body=b"{}" if method == "POST" else None, headers=headers or {})
        resp = client.getresponse()
        body = json.loads(resp.read() or b"null")
        client.close()
        return [resp.status, body]
    except Exception as exc:
        return [None, repr(exc)]

args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **args)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
report = {}
'''

BRIDGE_CHILD = PRELUDE + r'''
TOKEN = "router-test-token"
STUBBED = json.loads(sys.argv[1])
PATHS = STUBBED + ["/internal/no-such-route"]
calls = []
def stub(handler, server_):
    calls.append(handler.path)
    respond_json(handler, 200, {"stub": handler.path})
# Set explicitly: the child's ENGINE_BRIDGE_TOKEN env (observed unset, so "") is not this test's input.
srv.bridge_token = TOKEN
try:
    report["ingest_mode"] = send(port, "POST", "/internal/events/ingest", {"X-Bridge-Token": TOKEN})
    for path in STUBBED:
        router.POST_ROUTES[path] = stub
    report["missing"] = {p: send(port, "POST", p) for p in PATHS}
    report["near_miss"] = {p: send(port, "POST", p, {"X-Bridge-Token": TOKEN[:-1]}) for p in PATHS}
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

FAKE_CHILD = PRELUDE + r'''
seen = []
def fake(handler, server_):
    seen.append({"handler_is_similar": type(handler) is SimilarHandler, "server_is_srv": server_ is srv})
    respond_json(handler, 200, {"fake": True, "path": handler.path})
try:
    report["before"] = send(port, "GET", "/fake")
    router.GET_ROUTES["/fake"] = fake
    report["after"] = send(port, "GET", "/fake?x=1")
    report["trailing_slash"] = send(port, "GET", "/fake/")
    report["post"] = send(port, "POST", "/fake")
    report["seen"] = seen
finally:
    srv.shutdown()
    srv.server_close()
print(json.dumps(report))
'''


def _run(child: str, *argv: str) -> dict:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", child, *argv], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported router, built the server and ran every request
    return json.loads(run.stdout)


def test_internal_posts_answer_the_bridge_gate_before_their_route_runs():
    report = _run(BRIDGE_CHILD, json.dumps(STUBBED))
    # The router's own ingest adapter, before its entry is stubbed: a stub installed too early, or a lost 501 branch, reads anything else.
    assert report["ingest_mode"] == [501, {"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": None}]
    # A gate run after the table lookup reads [200, {"stub": ...}] here; a gate keyed on known routes only reads 404 for the unknown path.
    assert report["missing"] == {path: UNAUTHORIZED for path in PATHS}  # C1
    # A prefix or containment compare in place of an exact one accepts the near-miss token.
    assert report["near_miss"] == {path: UNAUTHORIZED for path in PATHS}  # C1
    assert report["calls_rejected"] == []  # C1
    # control: with the right token each stub is reached, once, so the empty record above means the gate stopped the request; a table copied at import never calls the stubs.
    assert report["valid"] == {**{path: [200, {"stub": path}] for path in STUBBED}, "/internal/no-such-route": NOT_FOUND}
    assert report["calls_valid"] == STUBBED
    # A gate that falls back to another token, or treats "" as a token, reads 401 or the stub's 200 here.
    assert report["unset"] == {path: UNSET for path in PATHS}  # C1
    assert report["calls_after_unset"] == STUBBED  # C1
    # GET /internal/* is ungated: a gate on both methods reads 401 here.
    assert report["get_internal"] == NOT_FOUND


def test_a_route_added_as_one_get_routes_entry_is_served_through_the_real_handler():
    report = _run(FAKE_CHILD)
    # control: nothing serves /fake until the entry exists, so the 200 below comes from the entry.
    assert report["before"] == NOT_FOUND
    # A table bound or copied at import still reads 404; the path proves the entry answered this request, query string and all.
    assert report["after"] == [200, {"fake": True, "path": "/fake?x=1"}]  # C2
    # Called once, for GET /fake?x=1 only, with the SimilarHandler serving it and the SimilarServer as `server`.
    assert report["seen"] == [{"handler_is_similar": True, "server_is_srv": True}]  # C2
    # Exact-path, GET-only: a prefix match reads 200 for /fake/, a method-blind table reads 200 for POST.
    assert report["trailing_slash"] == NOT_FOUND
    assert report["post"] == NOT_FOUND

```


Gate: satisfied

## 2026-10-04 - Step 7 - Phase 1 (Engine routing moves into router.py) - red (audit round 1)

`tests/tmp/test_58_engine_routing_out_of_similar_phase1.py` exited 1.

```
  tests/tmp/test_58_engine_routing_out_of_similar_phase1.py  2 failed                               0.0s
  ---------------------------------------------------------
  total                                                      2 failed                               1.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 1 (Engine routing moves into router.py) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
test_internal_posts_answer_the_bridge_gate_before_their_route_runs fails at line 132
on `report["valid"] == {**{path: [200, {"stub": path}] ...}, ...}`. Without `router`,
the child writes its stubs into an unwired SimpleNamespace table. The hard-coded
`_dispatch_post` in handlers/similar.py:442-478 then sends the valid-token POSTs to the
real `handle_internal_*` functions and the 501 ingest branch, not to the stubs. Lines
125-130 pass today because the existing prefix gate at similar.py:445 already answers
401 for these requests, and the ingest 501 at similar.py:466-475 already reports
`mode: None`.
test_a_route_added_as_one_get_routes_entry_is_served_through_the_real_handler fails at
line 146 on `report["after"] == [200, {"fake": True, "path": "/fake?x=1"}]`. Today's
`_dispatch_get` never reads the stand-in `GET_ROUTES`, so it answers [404, {"error": "Not found"}].

NOT ASSESSED
1. `code_under_test` engine/server/api/router.py does not resolve. It is marked NEW, so
   the stub question was answered from the assertion form and today's
   handlers/similar.py dispatch.
2. `code_under_test` tests/tmp/test_router_bridge_auth.py and
   tests/tmp/test_router_fake_route.py do not resolve. Neither one is imported by the
   test under audit.
3. For the valid-token requests at line 132, I did not work out what status the real
   `handle_internal_*` functions give with `db` None. The prediction only claims the
   response is not the stub's [200, {"stub": path}].
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (25 clauses: 7 must_prove, 14 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | every POST to `/internal/*`, unknown path included, answers 401 when the token is missing | :127 | a gate checked after the table lookup (the stubbed paths would read 200); a gate that covers known routes only (`/internal/no-such-route` would read 404) | CARRIED |
| C1b | must_prove | 401 when the token is wrong | :129 | a prefix or containment compare that accepts `TOKEN[:-1]` | CARRIED |
| C1c | must_prove | 503 when the Engine has no token set | :135 | a fallback to another token, or `""` accepted as a token (would read 401 or the stub's 200) | CARRIED |
| C1d | must_prove | the gate answers before the `POST_ROUTES` entry runs | :130, :136 | a gate that answers 401/503 after the entry has run: the stub records the request | CARRIED |
| C1e | must_prove | past the gate, the `POST_ROUTES` entry is what runs, so the empty record means something | :132, :133 | dispatch that skips the table, or a table copied at import (would answer the real handlers' codes, not the stub's 200) | CARRIED |
| C2a | must_prove | a route added as one `GET_ROUTES` entry is served, with no edit to `handlers/similar.py` | :144, :146 | a table bound or copied at import; dispatch that hardcodes each path in `similar.py` (`/fake` stays 404) | CARRIED |
| C2b | must_prove | served through the real `SimilarHandler` | :148 | the entry being called by some other handler class, or without the serving `SimilarServer` | CARRIED |
| D1 | docstring | "over real HTTP into a real `SimilarServer` running the real `SimilarHandler` in an Engine child" | :118, :148 | a child that never built the server or never ran the requests (non-zero exit); the wrong handler type | CARRIED |
| D2 | docstring | 401 `Unauthorized` without `X-Bridge-Token` on the four paths | :127 | the same as C1a | CARRIED |
| D3 | docstring | 401 with a near-miss token (the real token less its last character) | :129 | the same as C1b | CARRIED |
| D4 | docstring | 503 with the exact message once the Engine's token is `""` | :135 | the same as C1c, plus a wrong body | CARRIED |
| D5 | docstring | "None of those requests reaches its route": the stubs record nothing | :130, :136 | the same as C1d | CARRIED |
| D6 | docstring | "With the right token each stub is reached exactly once" | :133 | a stub hit twice, or a stub skipped (exact list equality) | CARRIED |
| D7 | docstring | with the right token, the unknown path answers 404 `Not found` | :132 | the unknown path falling through to a stub, or answering some other status | CARRIED |
| D8 | docstring | before the stubs, a valid-token ingest under mode None answers the 501 with `mode: None` | :125 | a stub installed too early; a lost 501 branch | CARRIED |
| D9 | docstring | GET `/internal/videos/resolve` answers a plain 404, with no gate | :138 | a gate on GET too (it would answer 503, because `bridge_token` is `""` from :86) | CARRIED |
| D10 | docstring | before the entry, GET `/fake` answers 404 | :144 | something already serving `/fake`, which would make the 200 at :146 meaningless | CARRIED |
| D11 | docstring | after the entry, GET `/fake?x=1` answers 200 with a body carrying the raw path, query included | :146 | an entry not called for this request; a body or path rewritten on the way | CARRIED |
| D12 | docstring | the entry is called with the serving `SimilarHandler` and the `SimilarServer` itself | :148 | a different handler or server object passed in | CARRIED |
| D13 | docstring | exact-path matching on GET: GET `/fake/` answers 404 | :150 | prefix matching | CARRIED |
| D14 | docstring | GET-only: POST `/fake` answers 404 | :151 | a table that ignores the method | CARRIED |
| N1 | name | "internal posts answer the bridge gate" | :127, :129, :135 | the same as C1a–C1c | CARRIED |
| N2 | name | "before their route runs" | :130, :136 | the same as C1d | CARRIED |
| N3 | name | "a route added as one get_routes entry is served" | :146 | the same as C2a | CARRIED |
| N4 | name | "through the real handler" | :148 | the same as C2b | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:82
   `report["near_miss"] = {p: send(port, "POST", p, {"X-Bridge-Token": TOKEN[:-1]}) for p in PATHS}`
   The only wrong token sent is one character short. C1b says "wrong", and two kinds of wrong token are never sent: one the same length that differs in a character, and the real token with a character added. A `presented.startswith(configured)` compare would pass :129.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:87
   The 503 is only checked with the real token in the request. The case where the Engine has no token set and the request carries none is never sent. So a gate that answers 401 for a missing token before it checks the Engine's own token is not ruled out. C1 does not say which answer wins when both conditions hold, so this is not blocking.
3. No rule in testing.md covers this — tests/tmp/test_58_engine_routing_out_of_similar_phase1.py:137
   The comment says "a gate on both methods reads 401 here". But :86 sets `srv.bridge_token = ""` before the GET at :89, so a gate on GET would answer 503. The assertion at :138 still rules that gate out. Only the comment's stated status is wrong.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists engine/server/api/router.py, which does not exist. Three things the test assumes could not be checked against it: the `GET_ROUTES` / `POST_ROUTES` names, the `(handler, server)` signature of an entry, and whether the router itself answers the gate and the ingest 501. I judged the clauses from the test, from the dispatch in the current `handlers/similar.py`, and from `SimilarServer.__init__`.
2. `code_under_test` lists tests/tmp/test_router_bridge_auth.py and tests/tmp/test_router_fake_route.py. Neither exists, so neither was read.

## 2026-10-04 - Step 7 - Phase 1 (Engine routing moves into router.py) - checkpoint outcome (run 1)

`tests/tmp/test_58_engine_routing_out_of_similar_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/server/api/router.py` (new)
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_router_import.py — a throwaway import probe I wrote and ran through ValidateTests. I have no tool that deletes files, so it is still there: please delete it. It is named `probe_*`, not `test_*`, so the default pytest collection should skip it.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_58_engine_routing_out_of_similar_phase1.py  2 passed                               0.0s
  ---------------------------------------------------------
  total                                                      2 passed                               1.6s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_58_engine_routing_out_of_similar_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_58_engine_routing_out_of_similar_phase1.py`

## 2026-10-04 - Step 8 - refactor pass

<refactors>
engine/server/api/handlers/similar.py — merged the identical `_serve_post` and `_serve_get` into one `_serve(route)` method. `do_POST` and `do_GET` now call `self._run_request(lambda: self._serve(route_post))` and `lambda: self._serve(route_get)`, the same lambda style `do_OPTIONS` already uses. The statement deadline, the interrupted-503 and the re-raise of other errors are unchanged. Nothing in engine/ or tests/ referenced the two old method names.
engine/server/api/router.py — `_events_ingest` now reads `getattr(server, "engine_ingest_mode", "bridge")` once into `mode` and uses it for both the check and the 501 body's `mode` field, instead of calling getattr twice.
</refactors>

<left_out>
router.py `_extract_video_id_from_similar_path`: the `startswith`/`endswith` check looks redundant next to the segment check, but it isn't. `strip("/")` would let `/videos/x/similar/` through, and the endswith check is what rejects it. Removing it would change behaviour, so I left it.
router.py `route_get`: the two identical 429 blocks (the `/api/` gate and the pattern route's own limiter) stay as they are. A helper would add about as much code as it removes, and the pattern block is the one the rat-tail comment marks for replacement with a matcher list later.
similar.py `_recommendations_likes_payload_error`: its `path not in SIMILAR_POST_ROUTES` guard can never fire from the router now, because only SIMILAR_POST_ROUTES paths reach `_handle_similar_request`. I kept it because it is that function's own contract, and direct callers or tests may pass other paths.
engine/server/README.md and handlers/__init__.py docstring: not touched. The plan's docs checklist left them to operator decision.
tests/tmp/probe_router_import.py (outside the files named): I reused the earlier probe file for this pass's check instead of creating another one. I have no tool that deletes files, so it is still there: please delete it. It is named `probe_*`, so default pytest collection skips it.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
An Engine-interpreter probe run through ValidateTests confirmed the refactored code. `SimilarHandler._serve` calls the route with the handler. An interrupted OperationalError gives `_respond_interrupted`, and a "disk I/O error" one is re-raised. `_serve_get` and `_serve_post` no longer exist. `_events_ingest` answers 501 with `mode: None` for `engine_ingest_mode=None`, and passes through to ingest for "bridge" and when the attribute is absent. I did not run the phase checkpoint or the suite.
</observation>

## 2026-10-04 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 13 of 63 test groups (50 unchanged):
  test_blocks.py — changed
  test_dislike_profile.py — changed
  test_dislikes.py — changed
  test_frontend_blocks.py — changed
  test_frontend_feed_params.py — changed
  test_frontend_upnext_pager.py — changed
  test_internal_client_reads.py — changed
  test_internal_translate.py — changed
  test_logging_profiles.py — changed
  test_search_fusion.py — no map entry
  test_server.py — changed
  test_similar.py — changed
  test_video.py — changed
  test_blocks.py                 7 passed                              74.0s
  test_dislike_profile.py        9 passed                              47.1s
  test_dislikes.py               10 passed                            119.6s
  test_frontend_blocks.py        2 passed                              30.4s
  test_frontend_feed_params.py   31 passed                              0.9s
  test_frontend_upnext_pager.py  1 passed                              24.2s
  test_internal_client_reads.py  7 passed                               0.9s
  test_internal_translate.py     137 passed                             2.7s
  test_logging_profiles.py       12 passed                             12.1s
  test_search_fusion.py          10 passed                              2.6s
  test_server.py                 155 passed                            88.0s
  test_similar.py                83 passed                             58.0s
  test_video.py                  31 passed                             15.8s
  -----------------------------
  total                          495 passed                           119.9s wall, 13 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 10 - stopped

Harvest tests did not complete. The entries above carry what the step established before it stopped; the gate it failed is the last of them.

