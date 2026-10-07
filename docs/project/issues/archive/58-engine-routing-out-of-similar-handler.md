# Move Engine routing out of handlers/similar.py

Status: enhancement, complete
Origin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate "routing out of handlers/similar.py" (Speculative)

## Problem

`SimilarHandler` is the Engine's only handler class (`engine/server/api/server.py:123, 469`). Routing and bridge auth for every `/internal/*` route therefore live in `engine/server/api/handlers/similar.py`, a 1275-line file named for similarity:
- dispatch at `:442-478`;
- bridge auth at `:413-440`.

The translate builds edited it only to add routes:
- the import at `:102`;
- the route list in the docstring at `:13-14`;
- the dispatch branches at `:459-464`.

The cost is to locality, not depth: every new route edits the similarity file. The review didn't read the similarity code itself.

## Proposed solution

Move the dispatch table and bridge auth into a router module of their own. This moves code without hiding anything new, so it is low value until routes keep being added. Triage may reasonably close it as `wontfix`.

## Related

- `engine/server/README.md` (route list).

## Comments

**Triage (2026-10-04).** The code claims above were checked against the tree, and all of them hold. Bridge auth now sits at `similar.py:417-440`, four lines off. The GET dispatch (`:494` on) also holds the `/api/` rate-limit gate and answers `/api/health` and `/api/channels` inline. Nothing already does this, and there are no prior rejections.

The issue says the move is low value "until routes keep being added", and the roadmap says they will. It plans new endpoints in F1-M3 (public REST API), F5-M3 and F1-M4. F2-M3 (API versioning) touches every unversioned route. F7-M7 and F10-M7 (rate limiting, service keys) sit where the bridge-auth and rate-limit gates sit today. The maintainer chose to brief it now.

Scope is the smallest move that answers the issue. The route tables and the bridge-auth gate leave `similar.py`. `SimilarHandler`, its request lifecycle and its similarity methods stay, because tests call them directly on stubs.

## Agent Brief

**Category:** enhancement
**Summary:** Move the Engine's route dispatch and its `/internal/*` bridge-auth gate out of the similarity handler module into a router module of their own, with no change to any route's behaviour.

**Current behavior:**
The Engine has one request handler class, `SimilarHandler`, in the similarity handler module. Its `do_GET` and `do_POST` run each request under the statement deadline and call `_dispatch_get` and `_dispatch_post`, which are `if` chains over the URL path:
- **POST:**
  - every `/internal/*` path must first pass `_bridge_authorized`: 503 when `ENGINE_BRIDGE_TOKEN` is unset, 401 on a missing or wrong `X-Bridge-Token`, compared with `hmac.compare_digest`;
  - then `SIMILAR_POST_ROUTES` (`/recommendations`, `/videos/similar`);
  - then the internal video resolve, video metadata, dislike centroids, translate and translate enqueue routes;
  - then events ingest, which answers 501 unless the ingest mode is `bridge`;
  - anything else gets 404 `{"error": "Not found"}`.
- **GET:**
  - every `/api/` path must first pass the rate limiter (429);
  - `/api/health` and `/api/channels` are answered inline;
  - then search, `/api/video`, `/api/video/refresh` and `/videos/{id}/similar`;
  - anything else gets 404.

The module docstring lists every route under the title "Similarity HTTP handler". Adding any route means editing the similarity module's imports, its docstring and one of the chains.

**Desired behavior:**
- **The router module.** One router module in the Engine's API package owns:
  - the GET and POST route tables, mapping each exact path, plus the `/videos/{id}/similar` pattern, to the function or handler method that serves it;
  - the `/internal/*` bridge-auth gate;
  - the `/api/` rate-limit gate on GET;
  - the 404 fallback;
  - the events-ingest mode check.
- **Adding a route** means one table entry and one import in the router, and no edit to the similarity module.
- **`SimilarHandler` keeps** the request lifecycle (`_run_request`, the statement deadline, the 503 on an interrupted statement), client-address resolution, access logging, `_rate_limit_check` and every similarity, feed and search method. Its `do_GET` and `do_POST` hand each request to the router.
- **Inline routes.** `/api/health` and `/api/channels` move out of the dispatch method into their own handler functions, beside the router or in a fitting handler module, so the router stays a table.
- **Behaviour is identical for every request:**
  - every route, method, status code, body and header;
  - the gate order: bridge auth before any internal route, the rate limit before any `/api/` GET;
  - the 401 and 503 bodies and their log lines;
  - the 429;
  - the 501 for ingest outside bridge mode;
  - both 404s.
- **The route list** moves from the similarity module's docstring to the router module. The Engine server README route list is unchanged, or corrected where it was already wrong.

**Key interfaces:**
- The router exposes one GET and one POST entry point that take the handler. Its tables map a path to a callable taking `(handler, server)` or the handler alone. The agent chooses which, and uses it consistently.
- `SimilarHandler` keeps its name and module, and the server still constructs it as today.
- Bridge auth becomes a router function using the same token source (the server's `bridge_token`, else `ENGINE_BRIDGE_TOKEN`) and the same constant-time compare.

**Acceptance criteria:**
- [ ] The similarity handler module no longer contains a path-dispatch chain, the bridge-auth check, the `/api/health` or `/api/channels` handling, or imports of the internal route handlers.
- [ ] One router module holds both route tables, the bridge-auth gate, the `/api/` rate-limit gate, the ingest-mode check and the 404 fallback.
- [ ] Every POST `/internal/*` path without a valid `X-Bridge-Token` answers 401 before its handler runs, and with the token unset answers 503. A test covers one internal route of each kind, plus an unknown `/internal/` path. The unknown path also gets 401 without a token, as today.
- [ ] Every route listed in the Engine server README answers as before. The existing Engine, video, similar, translate and ingest tests pass, and only tests that called the removed dispatch or auth methods directly are rewritten.
- [ ] Adding a fake route in a test needs only a router table entry, and no edit to the similarity module, to be served.
- [ ] The route list lives in the router module's docstring, and the similarity module's docstring describes only similarity.

**Out of scope:**
- Renaming `SimilarHandler` or `SimilarServer`, or moving the similarity, feed and search methods out of the class.
- API versioning (F2-M3), new routes, or any change to rate limiting, bridge auth or error bodies.
- Changing `_get_client_ip`, access logging or the statement deadline.
- The fetch adapter (issue 53) and the translate route internals (issues 54 and 55).

