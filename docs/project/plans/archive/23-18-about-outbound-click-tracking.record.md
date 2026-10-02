# Build record - 18-about-outbound-click-tracking

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/23-18-about-outbound-click-tracking.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# About page outbound links: proper click tracking\n\nStatus: enhancement, needs-triage\nOrigin: task 8c, [M3][F6] (marker was wrong in the old tracker: F6-M3 is the search API)\n\n## Problem\n\nClicks on external links from `about.html` are visible only indirectly in nginx logs, and are noisy because bots and malformed requests are mixed in.\n\n## Proposed solution\n\nExplicit client event tracking for outbound link clicks on the About page, stored in an API database.\n\n- **Client:** `data-track-id` on each outbound link in `client/frontend/about.html` (e.g. `about_patreon`, `about_github`, `about_youtube`); one delegated click handler for `a[data-track-id]`; send with `navigator.sendBeacon()` to `/api/analytics/outbound-click` (fallback `fetch(..., { keepalive: true })`); payload `track_id`, `href`, `page_path`, `timestamp`.\n- **API:** `POST /api/analytics/outbound-click`; validate payload against an allowlist of known ids/hosts; append a row to SQLite.\n- **Schema:** `outbound_click_events(id INTEGER PRIMARY KEY, track_id TEXT NOT NULL, href TEXT NOT NULL, page_path TEXT NOT NULL, created_at INTEGER NOT NULL)`, optional `ip_hash`, `user_agent`, `referer`; index on `(track_id, created_at)`.\n- **Reporting:** aggregated counts by `track_id`, daily and total; raw events kept.\n- **Abuse/noise:** per-IP rate limit; reject unknown `track_id`; no raw IP stored.\n\nWhich service owns the endpoint (Client backend vs Engine) and its gateway route is not decided in the original task and must be, given the Client/Engine boundary.\n\n## Validation (from the original task)\n\n- Click dispatch sends the correct payload.\n- A valid event is stored; an invalid one is rejected.\n- Clicking About links increases the counter in the DB.\n\n## Related\n\n- `21-static-page-visit-logs` also instruments the About page: keep this as event analytics and that as request-log visibility.\n\n## Comments\n\n### Issue 21 names this endpoint as its pageview upgrade path\n\nIssue 21 (`docs/project/issues/archive/21-static-page-visit-logs.md`) logs About visits in nginx and adds no endpoint, so the two issues do not overlap. Its runbook (\"Follow an About visit\" in `DEPLOYMENT.md`) notes that bots and crawlers appear in the nginx pages log. Counting human visits would need a client-side pageview beacon sent to this issue's endpoint. That endpoint is planned above as click-specific (`/api/analytics/outbound-click`, `outbound_click_events`). Its design should also accept a page-view event type, so pageviews do not need a second endpoint.",
  "request_source": "read from docs/project/issues/18-about-outbound-click-tracking.md",
  "slug": "18-about-outbound-click-tracking",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Analytics storage",
      "checkpoint": "Seam: `lib/users_store.py` called directly on a tmp `sqlite3` connection. No server is involved. Assert two things. First, after `ensure_user_schema(conn)` (run twice, to show it is idempotent), `[r[1] for r in conn.execute(\"PRAGMA table_info(analytics_events)\")]` equals exactly `[\"id\",\"type\",\"track_id\",\"href\",\"page_path\",\"created_at\",\"user_agent\",\"referer\"]`. Second, one `insert_analytics_event(...)` inside `with conn:` leaves exactly one row with the passed values, read back through a second connection to the same file.",
      "intent": "`users.db` gains an `analytics_events` table, created by `ensure_user_schema` with the settled columns, CHECK and index. `lib/users_store.py` gains an `insert_analytics_event` that writes one row inside the caller's transaction.",
      "clauses": [
        {
          "id": "C1",
          "text": "After `ensure_user_schema`, `analytics_events` has exactly the eight settled columns and none derived from the client address."
        },
        {
          "id": "C2",
          "text": "One `insert_analytics_event` call inside `with conn:` commits exactly one row with the given values."
        }
      ],
      "files": [
        "client/backend/lib/users_store.py (EDITED)",
        "tests/active/test_analytics_events.py (NEW)"
      ],
      "done": true,
      "outcome": "### `client/backend/lib/users_store.py`\n- `ensure_user_schema` now also creates `analytics_events` with `CREATE TABLE IF NOT EXISTS`. Its columns are `id INTEGER PRIMARY KEY`, `type TEXT NOT NULL CHECK (type IN ('page_view', 'outbound_click'))`, `track_id TEXT`, `href TEXT`, `page_path TEXT NOT NULL`, `created_at INTEGER NOT NULL`, `user_agent TEXT` and `referer TEXT`. No column comes from the client's address.\n- It also creates the index `analytics_events_type_track_created_idx` on `(type, track_id, created_at)` with `CREATE INDEX IF NOT EXISTS`. Running it again leaves the table, the index and the rows alone. The docstring now lists the analytics event table.\n- New `insert_analytics_event(conn, event_type, track_id, href, page_path, created_at, user_agent, referer)` runs one parameterised `INSERT` and does not commit, so the row belongs to the caller's transaction, the same way `remove_like` and `close_like` work.\n- The event-type argument is called `event_type` so it doesn't shadow the built-in `type`. It goes into the `type` column.\n\n### `tests/active/test_analytics_events.py`\nNot created. This step was to write production code only, and the checkpoint in `tests/tmp/` already covers the phase. The phase's files list names this durable test as NEW, so it is still waiting to be written or promoted from the checkpoint.\n\nI did not run the checkpoint: the workflow's run is the one that counts."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Event validator",
      "checkpoint": "Seam: the pure module function `client_server._validate_analytics_event(dict)`, imported the way `test_server.py` imports server internals. Assert that valid `outbound_click` and `page_view` bodies return the expected `(type, track_id, href, page_path)` tuple, including `track_id`/`href` absent versus `null` and unknown keys ignored. Assert that every invalid body in the draft's case list (`type`, `track_id`, `href`, `page_path`, `timestamp` and the page_view-with-extras cases, including the list `type`, lone surrogates and `http://[::1`) returns a `str` and does not raise. The parametrization is taken from the draft's list.",
      "intent": "`server.py` gains a pure `_validate_analytics_event` (with `_analytics_href_ok` and `_utf8_safe`) that turns any JSON-decoded dict into either the four storable values or an error message, following the settled rules.",
      "clauses": [
        {
          "id": "C1",
          "text": "Each valid event body yields its `(type, track_id, href, page_path)` tuple."
        },
        {
          "id": "C2",
          "text": "Each invalid event body yields an error string without raising."
        }
      ],
      "files": [
        "client/backend/server.py (EDITED)",
        "tests/active/test_analytics_events.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `client/backend/server.py`\n- New imports: `re`, and `urlsplit` added to the existing `urllib.parse` import.\n- Four new constants after `BLOCK_REFERENCE_MAX_LENGTH`, in the style of the ones around them: `ANALYTICS_EVENT_TYPES = frozenset((\"outbound_click\", \"page_view\"))`, `ANALYTICS_TRACK_ID_PATTERN = re.compile(r\"[a-z0-9_]{1,64}\")`, `ANALYTICS_HREF_MAX_LENGTH = 2048` and `ANALYTICS_PAGE_PATH_MAX_LENGTH = 256`.\n- New pure function `_validate_analytics_event(body)`, placed after `_parse_client_likes` and taken from the plan's settled code. It returns `(type, track_id, href, page_path)` for a valid event, or an error message for a 400. It never raises. The checks run in this order:\n  - `type` must be a `str` in the two-value set. The `str` check comes first because a list `type` can't be hashed for the set lookup.\n  - `page_path` must be a `str` of 1\u2013256 characters that starts with `/` and can be encoded as UTF-8.\n  - `timestamp` must be a non-negative `int`. `bool` and `float` are rejected. The value is checked and then thrown away.\n  - On a `page_view`, `track_id` and `href` must be absent or null, and the result is `(page_view, None, None, page_path)`.\n  - On an `outbound_click`, `track_id` must match the pattern with `fullmatch`, so a trailing newline is rejected, and `href` must pass `_analytics_href_ok`.\n  - Valid values come back exactly as sent, and unknown keys are ignored.\n- New `_analytics_href_ok(href)`: `href` must be a `str` of at most 2048 characters that encodes as UTF-8. `urlsplit` must give a scheme of `http` or `https` and a non-empty `hostname`. The scheme check ignores case because `urlsplit` lowercases it, but the original `href` is what gets stored. A `ValueError` from `urlsplit` or `.hostname` (for example `http://[::1`) makes it return False.\n- New `_utf8_safe(value)`: returns False when `str.encode(\"utf-8\")` raises `UnicodeEncodeError`. That catches lone surrogates from `json.loads`, which sqlite3 cannot bind.\n- The route, handler method and `insert_analytics_event` import are not added here. They belong to a later phase.\n\n### `tests/active/test_analytics_events.py`\nNot created and not edited. It doesn't exist in the worktree: Phase 1 left it unwritten and recorded that. This step asks for production code only, and the checkpoint in `tests/tmp/` covers this phase. The durable test is still waiting to be written or promoted from the checkpoints.\n\nI did not run the checkpoint, because the workflow's run is the one that counts."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Analytics route",
      "checkpoint": "Seam: real HTTP over a socket to `ClientBackendServer`, through the conftest `client_backend` fixture, with raw `urllib.request` POSTs (the `test_server.py` precedent). The 429 case uses a `_serving_limited` server built like conftest but with the production `RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)` and `X-Forwarded-For: 203.0.113.18`. For accepted events, assert 204 with an empty body and exactly one row. `created_at` must be within the [before, after] `now_ms()` window and not equal the client `timestamp`. UA and Referer must be copied from the headers, and empty or absent values must be NULL. This holds for `application/json` and `text/plain`. For refused POSTs, assert the row count is unchanged: a sample of invalid bodies (empty, `{`, `[]`, `\\xff` and one per field) gets 400 with a JSON `error`, and the 91st of 91 gets 429 with `{\"error\":\"Rate limit exceeded\"}` and 90 rows. A `GET` of the path gets 404 as a regression line, not as a clause.",
      "intent": "`POST /api/analytics/event` in `_serve_post` stores each accepted event as one server-stamped row in `analytics_events`, and stores nothing for a request it refuses.",
      "clauses": [
        {
          "id": "C1",
          "text": "A valid event of either type, with any Content-Type, gets 204 and adds one row whose `created_at`, `user_agent` and `referer` come from the server."
        },
        {
          "id": "C2",
          "text": "A refused POST, whether 400 for an invalid body or 429 over the route limit, adds no row."
        }
      ],
      "files": [
        "client/backend/server.py (EDITED)",
        "tests/active/test_analytics_events.py (EDITED)",
        ".un/skills/devsecops/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### `client/backend/server.py`\n- `_serve_post` now has a `POST /api/analytics/event` route. Like the other write routes, it checks `_rate_limit_check(url.path)` first. That limiter allows 90 requests per address in 60 s, and the address comes from `X-Forwarded-For` behind a trusted proxy. A request over the limit gets 429 `{\"error\": \"Rate limit exceeded\"}` before the body is read. A GET of the path still falls through to the existing 404.\n- New `ClientBackendHandler._handle_analytics_event`, which works in four steps:\n  - It reads the body with the shared `read_json_body`. That function ignores Content-Type, so `application/json`, `text/plain;charset=UTF-8` and form-encoded `sendBeacon` bodies are all accepted.\n  - If the body fails to parse (invalid JSON, a non-object, or non-UTF-8, since `UnicodeDecodeError` is a `ValueError`), it answers 400 with the parse error. An empty body parses to `{}`, which the validator then refuses.\n  - It runs the existing `_validate_analytics_event`. A refused event gets 400 with that function's message, and no row is written.\n  - A valid event is stored as one row through `insert_analytics_event` inside a `with self.server.user_db:` transaction, and the answer is 204 with an empty body. The server sets `created_at = now_ms()`; the client `timestamp` is validated but never stored. `user_agent` and `referer` come from the request headers, and are NULL when the header is empty or missing.\n- `insert_analytics_event` was added to the `lib.users_store` import.\n\n### `tests/active/test_analytics_events.py`, `.un/skills/devsecops/config.json`\nNot changed. This step asked for production code only. The checkpoint gates from `tests/tmp/`, and `tests/active/test_analytics_events.py` does not exist in the worktree yet. That file and its `test_groups` entry belong to the promotion of the phase checkpoints, not to this implementation step."
    },
    {
      "n": "4",
      "kind": "code",
      "name": "About beacon",
      "checkpoint": "There are two seams. (a) `src/about-analytics.ts` is bundled with the project's esbuild into node, the same harness as `tests/active/test_frontend_profile.py`, with `VITE_CLIENT_API_BASE=\"http://api.test/\"` defined. Stubbed `window`, `navigator`, `document` and a rejecting `fetch` are installed before the import. The test is parametrized over the sendBeacon modes true, false, missing and throws. It asserts exactly 2 sends to `http://api.test/api/analytics/event`: a `page_view` for `/about` and then an `outbound_click` with `about_patreon` and its href, where the untracked target and the Text-like target send nothing. It also asserts beacon delivery only in mode true and otherwise fetch with `keepalive: true` and `Content-Type: application/json`, 0 unhandled rejections, and one `click` listener. (b) A real `node_modules/.bin/vite build --outDir <tmp_path>/dist` run from `client/frontend`. It asserts that `dist/dev-pages/about.template.html` has a `src=\"/assets/*.js\"` script whose file contains `/api/analytics/event`. It skips with a reason if `dev-pages/about.html` exists.",
      "intent": "The About page template loads a new `src/about-analytics.ts`, which on import sends one `page_view` and then one `outbound_click` per click on an `a[data-track-id]`. Delivery is `sendBeacon` with a keepalive `fetch` fallback, and the built page ships it as a bundled asset.",
      "clauses": [
        {
          "id": "C1",
          "text": "Importing the module sends one `page_view` and one `outbound_click` per tracked click, falling back to keepalive `fetch` when `sendBeacon` is unavailable, refuses or throws."
        },
        {
          "id": "C2",
          "text": "A vite build of the About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`."
        }
      ],
      "files": [
        "client/frontend/src/about-analytics.ts (NEW)",
        "client/frontend/dev-pages/about.template.html (EDITED)",
        "tests/active/test_analytics_events.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `client/frontend/src/about-analytics.ts` (NEW)\n- New module, written from the plan's settled draft. It has no exports and does its work when imported.\n- **Page view.** On import it sends one `{type: \"page_view\", page_path: window.location.pathname, timestamp: Date.now()}`.\n- **Click listener.** On import it also adds one delegated `click` listener on `document`. The listener:\n  - ignores a target that has no `closest`, such as a Text node or the document;\n  - resolves `target.closest(\"a[data-track-id]\")`;\n  - for a match, sends `{type: \"outbound_click\", track_id: <data-track-id attribute>, href: link.href, page_path: window.location.pathname, timestamp: Date.now()}`;\n  - sends nothing when the link's `href` is not a string, as on an SVG `<a>`;\n  - never calls `preventDefault`.\n- **URL.** `sendAnalyticsEvent` builds the URL as `new URL(\"/api/analytics/event\", resolveClientApiBase())`.\n  - It passes no argument, so `?api=` is never read.\n  - Using `new URL` means a base that ends in `/` does not produce `//api`.\n- **Transport.** It first tries `navigator.sendBeacon(url, Blob[JSON], type application/json)`, called on `navigator` itself so the browser does not throw \"Illegal invocation\".\n  - If `sendBeacon` is missing, returns false or throws, it sends `fetch(url, {method: \"POST\", body, headers: {\"Content-Type\": \"application/json\"}, keepalive: true})` instead.\n  - The fetch has a no-op `.catch`, and an outer try/catch covers anything thrown synchronously, so nothing reaches the visitor as an error or an unhandled rejection.\n\n### `client/frontend/dev-pages/about.template.html` (EDITED)\n- Added `<script type=\"module\" src=\"/src/about-analytics.ts\"></script>` before `</body>`. Like `videos.html`, it uses a root-absolute path, so vite bundles it into an `/assets/*.js` entry for the built About page. No About URL or dev-pages file name changed.\n\n### `tests/active/test_analytics_events.py` (EDITED in the files list)\n- Not changed. The file still does not exist in the worktree; Phases 1\u20133 recorded the same thing.\n- This step asks for production code only, and the checkpoint `tests/tmp/test_18_about_outbound_click_tracking_phase4.py` gates the phase.\n- The durable file and its `.un/skills/devsecops/config.json` `test_groups` entry are still to be written or promoted from the phase checkpoints.\n\nI did not run the checkpoint; the workflow's run is the one that counts."
    }
  ],
  "digests": {
    "tests/tmp/test_18_about_outbound_click_tracking_phase1.py": "5f5b32230f1f26c611941f1286fcdb2e1c68d96d0c5113cf426d4274578607b8",
    "tests/tmp/test_18_about_outbound_click_tracking_phase2.py": "abc69ea25bcec954b8919859f60e75946fcf577d606057b885e5d5461ab6dd64",
    "tests/tmp/test_18_about_outbound_click_tracking_phase3.py": "b52a263a374001a2d0954071fd77bbcd8383a0897377cbbc037c663b09e11bf0",
    "tests/tmp/test_18_about_outbound_click_tracking_phase4.py": "4e889f83fe489ac09353fb8a062f75954de37883e2b90fa4028e926939a6d227"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/18",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261002T071749-f110-dev-flow"
  ],
  "plan": "docs/project/plans/23-18-about-outbound-click-tracking.md",
  "record": "docs/project/plans/23-18-about-outbound-click-tracking.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nCount real human interest on the About page as explicit browser events, not by reading nginx logs. The events are outbound link clicks and page views. The nginx pages log added by issue 21 (`docs/project/issues/archive/21-static-page-visit-logs.md`) mixes in bots, crawlers, HEAD requests and malformed requests. An event sent by the page's own JavaScript is a much cleaner signal of a person who loaded the page or clicked a link. This build delivers issue `docs/project/issues/18-about-outbound-click-tracking.md`. It also delivers the client-side pageview beacon that issue 21 and `DEPLOYMENT.md` (\"Follow an About visit\") name as their upgrade path. This is event analytics. Issue 21's nginx pages log is request-log visibility, stays as it is, and is not duplicated or changed.\n\n### Ownership and routing (decided)\n\n- The Client backend (`client/backend/server.py`, port 7072 in prod) owns the endpoint. The Engine is not touched.\n- Reasons from the tree: prod nginx (`DEPLOYMENT.md` \u00a76) already proxies every `/api/` path to the Client backend. The boundary contract (`DEPLOYMENT.md` \u00a75) requires frontend reads and writes to use the Client API base, never the Engine. The Client backend already owns its own SQLite (`client/backend/db/users.db`), an in-memory per-key `RateLimiter` (`client/backend/lib/http_utils.py`), and client-address resolution (ADR-0002, `TRUSTED_PROXIES`).\n- No nginx or gateway change is needed: `location /api/` already covers the route. The vite dev server already proxies `/api`.\n- The CSP header `connect-src 'self'` already allows a same-origin beacon. No CSP change.\n\n### Endpoint\n\n- One route, `POST /api/analytics/event`, for both event types. There is no separate `/api/analytics/outbound-click`.\n- The body is JSON, read with the existing `read_json_body`. `navigator.sendBeacon` with a JSON `Blob` sends `Content-Type: application/json`. The route must not reject a request because of its Content-Type: it parses the body as JSON whatever the header says, so a `text/plain` beacon is also accepted.\n- `outbound_click` body: `{\"type\": \"outbound_click\", \"track_id\": <str>, \"href\": <str>, \"page_path\": <str>, \"timestamp\": <int ms>}`.\n- `page_view` body: `{\"type\": \"page_view\", \"page_path\": <str>, \"timestamp\": <int ms>}`.\n- Success answers `204` with an empty body (`respond_bytes(self, 204, b\"\")`, as `/api/profile/delete` does).\n- A body that fails validation answers `400` with a JSON `{\"error\": ...}`, and nothing is stored. Invalid JSON, a non-object body and a missing or wrong-typed field all count as failures.\n- Rate limit: the route goes through the existing `_rate_limit_check(url.path)` before any parsing. That is the shared `RateLimiter` at `RATE_LIMIT_MAX_REQUESTS` = 90 per `RATE_LIMIT_WINDOW_SECONDS` = 60, keyed `<client address>:<path>`. Over the limit it answers `429 {\"error\": \"Rate limit exceeded\"}`, as the other routes do. No new limiter is added.\n- The request is wrapped in the existing `_run_request`, so it gets `request.start`/`request.end` log records like every other route.\n- Unknown paths keep answering 404. `GET /api/analytics/event` is not a route.\n\n### Validation rules (no track_id allowlist)\n\nThe operator chose shape validation instead of an id/host allowlist, because the real About page is an untracked local override whose links the repository cannot know.\n- `type`: exactly `\"outbound_click\"` or `\"page_view\"`. Anything else is rejected.\n- `track_id`: required for `outbound_click` and must fully match `[a-z0-9_]{1,64}`. Examples: `about_patreon`, `about_github`, `about_youtube`. For `page_view` it must be absent or null; it is stored as NULL.\n- `href`: required for `outbound_click`. It must be a string of at most 2048 characters that parses (`urllib.parse`) as an absolute URL with scheme `http` or `https` and a non-empty host. For `page_view` it must be absent or null; it is stored as NULL.\n- `page_path`: required for both types. It must be a string of 1 to 256 characters that starts with `/`. It is stored as sent, so `/about`, `/about/` and `/about.html` stay distinguishable.\n- `timestamp`: the client's `Date.now()`. It is required and must be a JSON integer (not a bool) that is at least 0. It is shape-checked only and not stored, because a client clock is not trusted. The stored time is the server's receive time.\n- Extra unknown keys in the body are ignored.\n\n### Storage\n\n- A new table in the Client backend's existing SQLite database `users.db` (`DEFAULT_USERS_DB_PATH`). It is created idempotently with `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` alongside the existing tables in `ensure_user_schema` (`client/backend/lib/users_store.py`), or in an equivalent schema function that runs at the same startup point.\n- Schema: `analytics_events(id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK (type IN ('outbound_click', 'page_view')), track_id TEXT, href TEXT, page_path TEXT NOT NULL, created_at INTEGER NOT NULL, user_agent TEXT, referer TEXT)`.\n- `created_at` is server time in epoch milliseconds (`now_ms()` from `lib/time_utils.py`, the convention of the other tables).\n- `user_agent` is the request's `User-Agent` header and `referer` is its `Referer` header. Each is stored as NULL when absent or empty, so bots can be filtered in queries.\n- Index: `(type, track_id, created_at)`, which serves the per-track_id daily and total queries and the page_view counts.\n- Privacy: no raw IP, no `ip_hash` and no value derived from the client address is stored. The rate limit uses the client address in memory only.\n- Retention: every raw row is kept. Nothing prunes the table.\n- One accepted request inserts exactly one row.\n\n### Frontend\n\n- A bundled module, e.g. `client/frontend/src/about-analytics.ts` (exact name and location are for the design step). Inline script is not an option: the server CSP `script-src 'self'` blocks inline JS, and it is the About page's only CSP.\n- On page load it sends one `page_view` event with `page_path = location.pathname`.\n- It installs one delegated `click` listener on `document` for `a[data-track-id]`. When a click resolves (via `closest`) to such a link, it sends one `outbound_click` event: `track_id` from the attribute, `href` from the link's resolved `href`, `page_path = location.pathname`, `timestamp = Date.now()`. It never calls `preventDefault`, so navigation is unaffected. A click on a link without `data-track-id` sends nothing.\n- Transport: `navigator.sendBeacon(url, new Blob([JSON.stringify(payload)], {type: \"application/json\"}))`. If `sendBeacon` is missing or returns false, it falls back to `fetch(url, {method: \"POST\", body, headers: {\"Content-Type\": \"application/json\"}, keepalive: true})`. Failures are swallowed and never surface to the visitor.\n- The URL is built from the existing Client API base (`client/frontend/src/data/api-base.ts`), never an Engine base.\n- `client/frontend/dev-pages/about.template.html` gets the module's `<script type=\"module\" src=\"/src/...\">` tag with a root-absolute URL, so the default About page sends page views. The template has no outbound links, so it sends no clicks.\n- The local override `client/frontend/dev-pages/about.html` is untracked and is not edited. `client/frontend/README.md` (\"Local About Overrides\") documents what an override adds: the same root-absolute `<script type=\"module\">` tag, and a `data-track-id=\"<id matching [a-z0-9_]{1,64}>\"` attribute on each outbound link to count. Vite bundles the tag because the override is the `about` build input in `vite.config.ts`.\n\n### Reporting\n\n- No new code, HTTP endpoint or CLI. `DEPLOYMENT.md` gets a Triage runbook section with ready-to-run `sqlite3` queries against the Client backend's `users.db` for:\n  - total `outbound_click` count per `track_id`;\n  - daily `outbound_click` count per `track_id`, with the day in UTC from `created_at` ms;\n  - total and daily `page_view` count, optionally per `page_path`;\n  - the same queries with a `user_agent` filter shown as the way to exclude obvious bots.\n- The existing \"Follow an About visit\" caveat in `DEPLOYMENT.md` points at issue 18 as the pageview upgrade path. Update it to say the pageview beacon now exists and where its counts are queried. Fix the issue path there and in related docs if issue 18 moves to `docs/project/issues/archive/`.\n- The `/api/analytics/event` route is added wherever `DEPLOYMENT.md` or `client/README.md` lists the Client backend's public routes.\n\n### Tracker housekeeping\n\n- When delivered, issue 18's `Status:` becomes `enhancement, complete`, a delivery comment is added in the style of issue 21's, and the file moves to `docs/project/issues/archive/` (see `docs/project/triage-labels.md`, `docs/project/issue-tracker.md`).\n- `CONTEXT.md` gets one glossary entry for **Analytics event**: what it is and its two types, that it is the Client backend's and not the Engine's, and that it is distinct from an Interaction event, which feeds the Engine.\n\n### Validation (acceptance)\n\n- Click dispatch: clicking an `a[data-track-id]` sends exactly one beacon to `/api/analytics/event` with `type`, `track_id`, `href`, `page_path` and `timestamp` correct. Clicking a link without the attribute sends none. Page load sends exactly one `page_view` with `page_path` and `timestamp`. When `sendBeacon` is unavailable or returns false, the `fetch` keepalive fallback is used.\n- A valid `outbound_click` and a valid `page_view` each answer 204 and add exactly one row with the expected columns. `created_at` is server time, `user_agent` and `referer` come from the headers, and nothing IP-derived is stored.\n- Each invalid case answers 400 and stores nothing: unknown `type`, bad `track_id` shape, non-http(s) or hostless or over-long `href`, bad `page_path`, missing or non-integer `timestamp`, invalid JSON, and a `track_id` or `href` on a `page_view`.\n- Exceeding the rate limit for one client address answers 429 and stores nothing for the rejected requests.\n- Counter: repeated valid clicks for one `track_id` raise its count in the DB, measured by the documented total and daily queries. The tracked template has no outbound links, so this is exercised through the endpoint or a test fixture page, not the template.\n- The built About page, from the template, includes the bundled analytics script, so a page load beacons a `page_view`.\n\n### Test locations and baseline suite state\n\n- New gating tests go in `tests/active`, with working files in `tests/tmp`. Archived tests are in `tests/archive`. Plans go in `docs/project/plans`. The run record is `tests/last_test_validation.json` and the output is `tests/last_test_output.txt`. The project dir is `/home/enduser/code/PeerTube-browser/.worktrees/18`.\n- Baseline before the build: the suite passes (exit code 0, not a variant run). Any red test after the build is caused by the build.\n- `tests/active/test_static_page_visit_logs.py` compares the nginx About locations with `vite.config.ts`. The build must keep it green: no About URL or dev-pages name changes.\n</requirements>\n\n<conflicts>\nIssue 18 places `data-track-id` on links in `client/frontend/about.html`, but that file does not exist in the tree: About is built from the tracked placeholder `client/frontend/dev-pages/about.template.html`, which has no outbound links, or from the operator's untracked `dev-pages/about.html`. The tracked change is therefore the script tag in the template plus documentation for overrides.\nIssue 18 says to validate against an allowlist of known ids/hosts and reject unknown `track_id`, but the operator decided on no allowlist, only shape validation of `track_id` (`[a-z0-9_]{1,64}`) and of `href` (absolute http(s) URL with a host).\nIssue 18 specifies `POST /api/analytics/outbound-click` and table `outbound_click_events`, but the issue's own comment from issue 21, and the operator, want page views on the same endpoint now. The route is `POST /api/analytics/event` with a `type` field, and the table is `analytics_events` with nullable `track_id`/`href`.\nIssue 18 lists an optional `ip_hash` column, but the operator chose to store no IP-derived value. A plain SHA-256 of an IPv4 address is reversible.\nIssue 18 lists the `timestamp` payload field and `created_at` without saying whose clock is used. The requirements store the server's receive time and only shape-check the client timestamp.\nIssue 18's validation \"Clicking About links increases the counter in the DB\" cannot run against the tracked template, which has no links. It is exercised through the endpoint or a fixture page.\nIssue 18 leaves the endpoint's owner undecided, but the tree decides it: nginx proxies `/api/` to the Client backend, and the boundary contract in `DEPLOYMENT.md` \u00a75 forbids UI calls to the Engine. So the Client backend owns it and no gateway route is added.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nI read `client/backend/server.py` (the `_serve_post` router, `_run_request`, `_rate_limit_check`, startup at line 1308), `lib/http_utils.py` (`read_json_body`, `respond_bytes`), `vite.config.ts`, `dev-pages/about.template.html`, `src/data/api-base.ts` and the existing esbuild-in-node frontend tests (`tests/active/test_frontend_profile.py`). The settled design fits the tree as it stands. Nothing needs new infrastructure: no dependency, no new limiter, no nginx, CSP or Engine change.\n\n**Backend route.** `_serve_post` gets one new branch for `/api/analytics/event`, placed before the final 404 and shaped like its neighbours:\n- `_rate_limit_check(url.path)` runs first, and a refusal answers `429 {\"error\": \"Rate limit exceeded\"}`.\n- The body is read with `read_json_body`. That function never looks at Content-Type, so the `text/plain` acceptance requirement is met without any extra code. It already raises `ValueError` for invalid JSON, a non-object body, invalid UTF-8 (`UnicodeDecodeError` is a `ValueError`), a non-numeric Content-Length and a body over 1 MB. All of these map to `400 {\"error\": ...}`. An empty or missing body comes back as `{}` and then fails validation on the missing `type`, so it is also a 400.\n- A valid event gets one row inserted and the answer `respond_bytes(self, 204, b\"\")`.\n\nThe route already sits inside `do_POST` \u2192 `_run_request`, so it gets `request.start`/`request.end` for free. `GET /api/analytics/event` matches no GET branch and keeps answering 404, as does every other unknown path.\n\n**Validation.** One pure module-level function in `server.py`. It takes the parsed dict and returns either the row values or an error string, so the route stays a thin branch and the rules can be tested directly. It applies the rules exactly as settled:\n- `type` must be in the two-value set.\n- `track_id` must pass `re.fullmatch` against `[a-z0-9_]{1,64}`. That is `fullmatch`, not `match` with `$`, because `$` accepts a trailing newline. It is required for `outbound_click` and must be absent or `None` for `page_view`.\n- `href` must be a `str` of at most 2048 characters. `urllib.parse.urlsplit` must give a scheme of `http` or `https` and a non-empty `hostname`. The `ValueError` that `urlsplit` raises on a malformed bracketed host is caught and becomes a 400. The same absent-or-null rule as `track_id` applies on `page_view`.\n- `page_path` must be a `str` of 1 to 256 characters starting with `/`, and is stored verbatim.\n- `timestamp` must be an `int` that is not a `bool` and is `>= 0`. It is checked and then discarded.\n- Unknown keys are ignored.\n\nThe handler adds the server-side values: `now_ms()`, plus the `User-Agent` and `Referer` headers, each turned into `None` when absent or empty after stripping. Nothing derived from `_get_client_ip()` reaches the row.\n\n**Storage.** `ensure_user_schema` in `lib/users_store.py` gains the `analytics_events` `CREATE TABLE IF NOT EXISTS` with the settled columns and CHECK, and the `(type, track_id, created_at)` `CREATE INDEX IF NOT EXISTS`. It already runs at startup (`server.py:1311`), and it is the literal option the requirements name, so existing databases pick up the table on the next restart. The same module gets a small `insert_analytics_event(conn, ...)` that does one `INSERT`, called inside `with self.server.user_db:` the way the other writes are, so one accepted request is one committed row.\n\n**Frontend.** A new module, `client/frontend/src/about-analytics.ts`. When it runs it:\n- builds the URL once as `resolveClientApiBase()` plus `/api/analytics/event`. It is called without an argument, so `?api=` is never read; in a prod build it is the page origin;\n- sends one `page_view` (`page_path = location.pathname`, `timestamp = Date.now()`);\n- adds one delegated `click` listener on `document`. The listener resolves `event.target.closest(\"a[data-track-id]\")`, guarding a target that has no `closest`, and for a match sends `outbound_click` with the attribute value, `link.href` (the browser-resolved absolute URL), the pathname and `Date.now()`. It never calls `preventDefault`.\n\nOne `send` helper does the transport: `sendBeacon` with a JSON `Blob`. If `sendBeacon` is missing, returns false or throws, the helper falls back to `fetch` with `keepalive: true`. It wraps everything in try/catch and attaches a no-op `.catch` to the fetch promise, so nothing reaches the console as an unhandled rejection. The template gets `<script type=\"module\" src=\"/src/about-analytics.ts\"></script>`, the same root-absolute style as its `/src/videos.css` link. No About URL, input name or dev-pages filename changes, so `test_static_page_visit_logs.py` stays green.\n\n**Reporting and docs.** No new code.\n- **`DEPLOYMENT.md`**:\n  - A new Triage subsection, \"Count About analytics events\". It holds a `sqlite3 -readonly <root>/client/backend/db/users.db` invocation and fenced `sql` blocks: total clicks per `track_id`; daily clicks per `track_id` using `date(created_at / 1000, 'unixepoch')`, which is UTC; total and daily `page_view`, optionally grouped by `page_path`; and the same queries with a `user_agent IS NOT NULL AND user_agent NOT LIKE '%bot%' AND \u2026 '%crawl%' AND \u2026 '%spider%'` filter shown as the bot exclusion.\n  - The \"Follow an About visit\" caveat at line 258 is rewritten to say the beacon exists and to point at the new subsection, with the issue path changed to `archive/`.\n  - The public-route prose near line 405 gets the route.\n- **`client/README.md`**: the route list at line 41 gets the route, and the API bullets get one line describing it.\n- **`client/frontend/README.md`**: \"Local About Overrides\" gets the script tag and the `data-track-id` convention. It also notes that only http(s) links can be counted.\n- **`CONTEXT.md`**: one **Analytics event** entry.\n- **Tracker**: issue 18 gets its status, a delivery comment and the move to the archive. Lane 5c in `docs/project/issues/plan.md` gets a path and delivery fix.\n\n**Tests (gating, `tests/active`).**\n- **Backend.** The `client_backend` fixture over a socket covers: each valid type gives 204 and exactly one row with the expected columns, with `created_at` inside the request window rather than equal to the client timestamp, and UA/Referer taken from the headers. A `PRAGMA table_info` assertion checks there is no IP-like column. Each invalid case gives 400 and zero rows, as does a `text/plain` valid beacon, which must be accepted. The rate-limit test sends 91 posts from one address: the extras get 429 and add no rows. `GET` answers 404.\n- **Counter.** The test posts N clicks for one `track_id` and runs the SQL blocks extracted from the new `DEPLOYMENT.md` subsection against the fixture's DB, using Python `sqlite3` so the test does not depend on the CLI binary.\n- **Frontend.** The module is bundled with the project's esbuild, as `test_frontend_profile.py` does. It runs in node against stubbed `document`, `location`, `navigator.sendBeacon` and `fetch`, and the test asserts one `page_view` on load, one correct `outbound_click` per tracked click, none for an untracked link, and the fetch keepalive fallback when `sendBeacon` is undefined or returns false.\n- **Built page.** `vite build --outDir tests/tmp/...` is run and the test asserts that the built `dev-pages/about.template.html` references a bundled `/assets/*.js` whose contents include `/api/analytics/event`.\n\n### Alternatives considered\n\n- **Validation in a new `lib/analytics_events.py` (schema, validate, insert).** Rejected. It adds a file and a second schema call site at startup for about 40 lines of code. `users_store.py` already owns `users.db`'s schema, and `server.py` already holds the route-level checks.\n- **Validation inside `users_store.py`.** Rejected. The store module takes trusted values and HTTP-shaped validation does not belong there.\n- **A separate SQLite file for analytics.** Rejected: the requirement says `users.db`, and a second file means a second connection, startup step and backup path.\n- **Per-day aggregate counters instead of raw rows.** Rejected: the bot filter on `user_agent` would be impossible after aggregation, and the requirement keeps raw rows.\n- **Transport:** `fetch` alone can be cancelled by the navigation an outbound click causes. A GET image pixel would need a GET route and puts the payload in URLs and logs. `sendBeacon` alone has no fallback for browsers or privacy settings that disable it. The settled `sendBeacon` plus `fetch keepalive` combination covers all three.\n- **Per-link listeners instead of one delegated listener.** Rejected: they miss links inserted later and need a query at load time. The delegated listener is the settled choice as well.\n- **Built-page check by reading the template source only.** Rejected as the sole check: it proves the tag is there, not that vite bundles it. The real build is the acceptance criterion.\n\n### Risks, gotchas and limitations\n\n- **Local override and the built-page test.** `vite.config.ts` builds `dev-pages/about.html` when it exists. On a checkout with an untracked override, the build produces the override, not the template. The test will skip with an explicit reason in that case rather than assert on the wrong file. The worktree normally has no override, so the gate runs. The ceiling is that an operator's override without the tag sends nothing, which the README documents.\n- **Non-http(s) tracked links.** A `mailto:` or `tel:` link with `data-track-id` is beaconed and rejected with 400 by the shape rule, so it is never counted. The README says so. Widening the rule is the upgrade path if that is ever wanted.\n- **Clicks the `click` event does not see.** Middle-click opens a tab through `auxclick`, not `click`, and the context-menu \"Open in new tab\" fires nothing, so neither is counted. Ctrl/Cmd-click and keyboard Enter do fire `click` and are counted. This is a deliberate simplification: listening for `auxclick` as well is a one-line upgrade, but it is outside the settled spec.\n- **Cross-origin dev base.** If `VITE_CLIENT_API_BASE` points at a different origin, a `sendBeacon` with an `application/json` Blob is a non-CORS-safelisted request, and some browsers throw or refuse it. The try/catch then falls through to `fetch`, which preflights through the existing `respond_options` CORS handling. In prod the base is same-origin and none of this applies.\n- **Forgeable counts.** The endpoint is anonymous and accepts any well-formed body. A script can inflate counts at up to 90 per minute per address, roughly 130k rows a day per address. Retention is unbounded by requirement, so a sustained abuser grows `users.db` without limit. The per-address limiter is the only control. Both are named in the DEPLOYMENT section, and a prune or a per-address daily cap is the upgrade path.\n- **Header storage.** `User-Agent` and `Referer` are stored as sent. `http.server` caps a header line at 64 KiB, which bounds each row, but there is no tighter truncation because the spec does not ask for one.\n- **Shared SQLite connection.** Analytics writes share the connection and transaction pattern of the profile writes, so a burst of beacons briefly serialises with like and dislike writes. At the 90/min/address rate this is negligible.\n- **The bot filter is a heuristic.** The UA can be forged. The documented `NOT LIKE` filter removes honest crawlers only. That is said in the docs, consistent with the issue-21 caveat.\n- **Referer is often reduced.** The default `strict-origin-when-cross-origin` policy usually leaves `Referer` as the About URL itself. It is mostly useful as a has-or-hasn't signal.\n\n### Tradeoffs the operator is asked to accept\n\n- The built-page gate skips rather than fails on a checkout that has a local `about.html` override.\n- Middle-click and context-menu opens are not counted.\n- Tracked non-http(s) links are silently not counted.\n- Counts are best-effort human signals: anonymous, forgeable within the rate limit, and growing without pruning.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n<impacts>\n<impact path=\"client/backend/server.py\" element=\"module imports (lines 5-41) and module constants (lines 46-73)\">\n**What changes.**\n- `re` is not imported today (lines 5-23).\n- `urllib.parse` imports only `parse_qs, urlencode, urlparse` (line 20), so the plan's `urlsplit` must be added there.\n- `insert_analytics_event` joins the wrapped, alphabetised `from lib.users_store import (...)` block at lines 39-41, between `get_or_create_user` and `load_liked_keys`.\n- New constants follow the style of `USER_ACTIONS = frozenset((...))` (line 62) and `BLOCK_REFERENCE_MAX_LENGTH = 200` (line 68): a two-value event-type frozenset, a `[a-z0-9_]{1,64}` pattern, a 2048 href cap and a 256 page_path cap.\n\n**What depends on it.** `tests/active/conftest.py:43` imports the module as `client_server`, and `tests/active/test_server.py:161` re-imports from conftest. Every Client-backend test therefore loads it at collection time.\n\n**Regression risk.** Low. An import or name error fails the whole active suite loudly at collection.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"ClientBackendHandler._serve_post (lines 437-501): new `/api/analytics/event` branch and its handler method\">\n**What changes.**\n- A new `if url.path == \"/api/analytics/event\":` branch goes before the comment at 497-500 and the final 404 at 501.\n- It is shaped like `/api/user-action` (464-469): `_rate_limit_check(url.path)`, then 429 `{\"error\": \"Rate limit exceeded\"}`, then a `_handle_analytics_event()` method.\n- That method reads the body with `try: read_json_body(self) except ValueError as exc: respond_json(self, 400, {\"error\": str(exc)})`, the exact idiom at 1014-1018 and 1050-1054. It then validates, writes with `with self.server.user_db: insert_analytics_event(...)` (the idiom at 410 and 1119), and answers `respond_bytes(self, 204, b\"\")` like `/api/profile/delete` (line 462).\n\n**What depends on it.**\n- `do_POST` \u2192 `_run_request` (377-379, 339-357) gives `request.start`/`request.end` with no extra code. `request.start` already logs `ip` and `user_agent`, but that is a log, not storage.\n- `_serve_get` (381-435) is untouched, so `GET /api/analytics/event` falls to the 404 at 435.\n- `do_OPTIONS` (369-371) answers `respond_options` for any path, so a CORS preflight to the new path already gets 204.\n- In prod, nginx's `location /api/` (DEPLOYMENT.md:486-493) already proxies the path to 7072, so no nginx change is needed.\n\n**Regression risk.** Low for existing routes, since the match is on the exact path.\n- A branch placed after line 501 never runs.\n- The limiter key is `<ip>:/api/analytics/event` (`_rate_limit_check`, 514-517), so analytics has its own 90/min bucket and does not drain `/api/user-action`'s.\n- A 429 or a validation 400 leaves part of the body unread. That is harmless only because nothing in `client/backend` sets `protocol_version` or `close_connection` (I grepped), so each connection is HTTP/1.0 and closes.\n- No socket timeout is set, so a `Content-Length` larger than the bytes actually sent blocks a thread in `rfile.read`. Every POST route already has this, but this route is anonymous and hit on every About view.\n- `str(exc)` for a `UnicodeDecodeError` is a long codec message rather than \"Invalid JSON body\". It is still a 400, but tests should assert the status, not the text.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"new module-level validator (e.g. `_validate_analytics_event(body)`), near `_parse_client_likes` (lines 1236-1252)\">\n**What changes.** A new pure function that returns the row values or an error string, in the sibling style: a `_` prefix and a `\"\"\"Handle ...`/`:returns:` docstring.\n\n**What depends on it.** The route handler, and the backend tests, which can call it directly as `client_server._validate_...`.\n\n**Regression risk.** Medium. An exception that escapes the validator does not become a 400. It goes to socketserver's `handle_error`, the client gets no response, and `request.end` logs status `-`. The cases:\n- **Type checks first.** `re.fullmatch` on an int raises `TypeError`, and `len`, `.startswith` and `urlsplit` also fail on non-strings. Check `isinstance(..., str)` before each.\n- **`bool` is an `int`.** `timestamp: true` must be rejected. `1.0` arrives as a `float` from `json.loads` and must be rejected too.\n- **Lone surrogates.** `json.loads('\"\\ud800\"')` gives a `str` that sqlite3 cannot bind (`UnicodeEncodeError` at INSERT, after validation). `href` and `page_path` therefore need an encodability check. `track_id` is safe because of its regex.\n- **`urlsplit` details.**\n  - `\"https://\"` gives `hostname=None`, which must be rejected.\n  - `\"http://[::1\"` raises `ValueError`, which must be caught.\n  - `.hostname` itself can raise on a malformed bracketed netloc, so the catch must cover the attribute read as well as the call.\n  - The scheme comes back lowercased, so `HTTPS://` passes.\n- **Null handling.** An explicit `null` `track_id` or `href` is accepted on `page_view` and rejected on `outbound_click`.\n- **`page_path`.** `//host` passes the leading-slash rule. That is acceptable because the value is stored, never followed.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"User-Agent / Referer capture in the new handler, and `_get_client_ip` (lines 326-329)\">\n**What changes.** The handler reads `self.headers.get(\"User-Agent\")` and `self.headers.get(\"Referer\")`, strips each, and stores `None` when the result is empty. That is the same idiom as `_run_request` at 347-349. `_get_client_ip` is reached only through `_rate_limit_check`.\n\n**What depends on it.** The \"nothing IP-derived stored\" requirement and the `PRAGMA table_info` test.\n\n**Regression risk.** Low.\n- nginx sets `X-Real-IP` and `X-Forwarded-For` on `/api/` (DEPLOYMENT.md:489-490), and neither may reach the row.\n- Headers are stored up to http.server's 64 KiB line cap, which the plan accepts. http.server decodes headers as latin-1, so they always bind in sqlite.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"connect_db (lines 230-234) and the single shared `user_db` connection used by every handler thread\">\n**What changes.** No code change. The new route adds writes on this connection.\n\n**What depends on it.** Every profile write: `_store_reaction`'s `with conn:` blocks (974, 991, 999), the likes import (1027), reset and blocks (1119, 1135), `lib/blocks.py:56,80` and `lib/profiles.py:74`.\n\n**Regression risk.** Medium, and the plan understates it as \"serialises briefly\".\n- There is one `sqlite3.Connection` (`check_same_thread=False`) shared by all `ThreadingHTTPServer` threads, with no lock. I grepped: the only lock is `RateLimiter.lock`.\n- `with conn:` commits or rolls back the connection's single open transaction. A beacon commit on one thread can commit another thread's half-done multi-statement write, and a rollback elsewhere can drop a beacon insert.\n- The race exists today. This is the first anonymous write route allowed 90/min per address on every About view, so it is hit far more often.\n- Name it as an inherited limitation and open a follow-up issue (a write lock or per-thread connections). The plan does not fix it.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"main(): `ensure_user_schema(user_db)` (line 1311)\">\n**What changes.** No edit. Existing databases get the table and index on the next restart.\n\n**What depends on it.** Prod and dev upgrades. There is no migration step, consistent with DEPLOYMENT.md:408.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"ensure_user_schema (lines 10-71): docstring and script\">\n**What changes.**\n- Add `CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK (type IN ('outbound_click','page_view')), track_id TEXT, href TEXT, page_path TEXT NOT NULL, created_at INTEGER NOT NULL, user_agent TEXT, referer TEXT)`.\n- Add `CREATE INDEX IF NOT EXISTS <name>_idx ON analytics_events (type, track_id, created_at)`, named like `likes_user_updated_idx` (line 27).\n- Both go before the `local-user` cleanup DELETEs (67-69).\n- The docstring on line 11 enumerates the tables the function creates, so it must gain the analytics events table.\n\n**What depends on it.** `server.py:1311`, `tests/active/conftest.py:77` and `:169`, and `tests/active/test_server.py:398`, `:834` and `:997`.\n\n**Regression risk.** Low. No active test enumerates users.db tables: the `sqlite_master`/`table_info` hits are in Engine-DB tests. `test_profiles.py:103` byte-scans `users.db*` for key material, and an empty new table adds none.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"new insert_analytics_event(conn, ...)\">\n**What changes.** A new function that runs one parameterised INSERT. It must not call `conn.commit()`, because the handler's `with self.server.user_db:` owns the transaction.\n\nThe module is inconsistent on this point. `get_or_create_user`, `record_like` and `clear_likes` commit internally, while `remove_like` and `close_like` say \"inside the caller's transaction\" (lines 192, 216). Follow the latter, docstring phrase included.\n\n**What depends on it.** The route, and the counter test that reads the rows back.\n\n**Regression risk.** Low. `created_at` must come from the handler's single `now_ms()` (lib/time_utils), so that the test's before/after window holds.\n</impact>\n<impact path=\"client/backend/lib/http_utils.py\" element=\"read_json_body (lines 78-95)\">\n**What changes.** Nothing. I confirmed by reading it that the plan's assumptions hold:\n- Content-Type is never read, so `text/plain` is accepted.\n- `int()` on a non-numeric length raises `ValueError`.\n- A length over 1,000,000 raises `ValueError`.\n- `.decode(\"utf-8\")` raises `UnicodeDecodeError`, which is a `ValueError`.\n- A non-dict body raises `ValueError`.\n- A length of 0 or less, a missing length, or a whitespace-only body returns `{}`.\n\n**What depends on it.** Every JSON POST route.\n\n**Regression risk.** None, provided it is not edited.\n</impact>\n<impact path=\"client/backend/lib/http_utils.py\" element=\"_send_cors_headers / respond_options / ALLOWED_REQUEST_HEADERS (lines 12-44, 71-75)\">\n**What changes.** Nothing.\n\n**What depends on it.** Cross-origin dev beacons, and `respond_bytes`' CORS headers on the 204.\n\n**Regression risk.** No backend regression. There is a frontend consequence the plan's cross-origin note understates:\n- No `Access-Control-Allow-Credentials` is ever sent.\n- `navigator.sendBeacon` uses credentials mode `include`, and an `application/json` Blob is not CORS-safelisted, so cross-origin it is preflighted, and a credentialed preflight without Allow-Credentials fails.\n- Whether a browser then throws, which reaches the fetch fallback, or returns `true` and drops the event silently varies. I could not verify this from the tree. Treat dev cross-origin beacon loss as possible.\n- Prod is same-origin and unaffected.\n</impact>\n<impact path=\"client/backend/lib/http_utils.py\" element=\"RateLimiter (lines 98-124)\">\n**What changes.** Nothing.\n\n**What depends on it.** The new 429, and the forgeability ceiling.\n\n**Regression risk.** Low.\n- Buckets are never evicted, so each distinct address adds a deque until restart. This route grows the map faster than the others.\n- `max_requests <= 0` disables limiting.\n- A 429 is invisible to `sendBeacon`, so behind a shared or misresolved address, counts silently cap at 90/min.\n</impact>\n<impact path=\"client/backend/lib/profiles.py\" element=\"delete_profile\">\n**What changes.** Nothing. Analytics rows carry no profile id, so profile deletion neither touches them nor needs to. client/README.md:13 (\"everything keyed to it\") stays true.\n\n**What depends on it.** Nothing new.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"client/frontend/src/about-analytics.ts\" element=\"new module (whole file)\">\n**What changes.** A new module that imports `resolveClientApiBase` from `./data/api-base`. On import it sends one `page_view` and installs one delegated `document` click listener. A `send` helper tries `navigator.sendBeacon(url, Blob)` and falls back to `fetch(url, {method: \"POST\", keepalive: true, ...})` with a no-op `.catch`.\n\n**What depends on it.** Five things must all name the same path:\n- the template's script tag;\n- the README override instructions;\n- the node test;\n- the built-page test;\n- the new config.json test group.\n\n**Regression risk.** Medium, because every failure is silent by design.\n- **URL construction.** Every sibling builds URLs as `new URL(\"/api/...\", base)` (user-actions.ts:20, reactions.ts:34/68, blocks.ts:57, profile.ts:88, user-profile.ts:23/43/61). None concatenates, and plain concatenation produces `//api/...` when `VITE_CLIENT_API_BASE` ends in `/`. Use `new URL`, inside the try, since it throws on a bad base.\n- **Placement.** The page entries live at `src/pages/<page>/index.ts` (channels, likes, search, video-page, videos). The plan's `src/about-analytics.ts` at the src root departs from that convention. Either is workable, but decide it at design.\n- **`sendBeacon` binding.** It must be called as `navigator.sendBeacon(...)`. A detached reference throws \"Illegal invocation\", the catch swallows it, and every event goes through fetch.\n- **`event.target`.** It can be a Text or non-Element node with no `closest`.\n- **SVG links.** An SVG `<a>`'s `.href` is an `SVGAnimatedString`, so read `getAttribute`/`href` defensively or accept a 400.\n- **Module script.** A module script is deferred, so no DOMContentLoaded wait is needed.\n- **Import-time read.** api-base.ts:5 reads `window.location.origin` at import.\n- **`fetch` failures.** `fetch` can throw synchronously (a keepalive body over 64 KiB) as well as reject, so it needs both the try and the `.catch`.\n- **No type gate.** The build script is plain `vite build` (package.json:9), so TS type errors do not fail the build.\n- **Gateway scan.** `tests/check-frontend-client-gateway.sh` scans `src`. It passes provided no Engine base, `127.0.0.1:707x` or `/internal/*` literal appears.\n</impact>\n<impact path=\"client/frontend/src/data/api-base.ts\" element=\"resolveClientApiBase (lines 18-33), DEFAULT_CLIENT_API_BASE (line 5)\">\n**What changes.** Nothing. The new module calls it with no argument, so `?api=` is never read and prod returns `window.location.origin`.\n\n**What depends on it.** Every data module and the new one.\n\n**Regression risk.** Low.\n- Line 5 runs at import, so the node test must define `globalThis.window.location.origin` before `await import(bundle)`, as test_frontend_profile.py:30 does.\n- `normalizeApiBase` keeps a trailing slash. This is harmless with `new URL`.\n- Bundling it into the About entry may move it into a shared chunk and change other pages' asset hashes. That is harmless.\n</impact>\n<impact path=\"client/frontend/dev-pages/about.template.html\" element=\"new `<script type=\\\"module\\\" src=\\\"/src/about-analytics.ts\\\">` tag\">\n**What changes.** One line. It is root-absolute like the `/src/videos.css` link on line 8, as client/frontend/README.md:41 requires. Today the template has no script at all, so it becomes the About page's first JS.\n\n**What depends on it.**\n- `vite.config.ts` uses it as the `about` input when no override exists, which is the case in this worktree: Glob finds only the template.\n- nginx serves the built copy from `dev-pages/` (DEPLOYMENT.md:467-483, 519).\n- `.un/skills/devsecops/config.json:263-268` maps it to a test that does not exist.\n- `tests/tmp/test_21_static_page_visit_logs_phase{1,2,3}.py` read the template bytes into nginx. They are non-gating.\n\n**Regression risk.** Low.\n- The server CSP (DEPLOYMENT.md:459) has `script-src 'self'` and `connect-src 'self' https:`, which allow the bundled `/assets/*.js` and a same-origin beacon. An inline script would be blocked.\n- The template's text (line 30) tells operators to replace it with an override, so the override docs carry the real instruction burden.\n</impact>\n<impact path=\"client/frontend/vite.config.ts\" element=\"aboutSourcePath (16-18), build.rollupOptions.input.about (91-93), server.proxy['/api'] (27-32)\">\n**What changes.** Nothing.\n\n**What depends on it.** The built-page test, and dev beacons.\n\n**Regression risk.** Medium for test design.\n- **Override switch.** `existsSync(devAboutPath)` switches the input to an untracked override (`.gitignore:29-30`). The plan skips the test in that case.\n- **Output location.** The built page lands at `<outDir>/dev-pages/about.template.html`. The `/api/analytics/event` literal sits in the About entry chunk, while api-base may land in a shared chunk. The assertion must follow the page's `<script src>`, not assume a single file.\n- **Output directory.**\n  - `tests/tmp` is not gitignored (I grepped `.gitignore`), so `--outDir tests/tmp/...` leaves untracked build output in the tree. Prefer pytest's `tmp_path`, passed as an absolute path.\n  - An outDir outside the root needs `--emptyOutDir` or a fresh directory.\n  - Never write into the committed `client/frontend/dist/`.\n- **First vite test.** No active test runs vite today. Eight tests run `node_modules/.bin/esbuild`. `vite` is a devDependency (package.json:18). `node_modules` is outside the sandbox, so I could not confirm `.bin/vite` exists.\n- **Dev proxy.** `server.proxy['/api']` makes plain `npx vite` same-origin.\n</impact>\n<impact path=\"client/frontend/scripts/dev.mjs\" element=\"VITE_CLIENT_API_BASE default (lines 15, 46, 104)\">\n**What changes.** Nothing.\n\n**What depends on it.** `npm run dev` always sets a cross-origin base (`http://127.0.0.1:7172`), so dev beacons need `CLIENT_CORS_ORIGINS` and are subject to the credentialed-sendBeacon uncertainty above.\n\n**Regression risk.** Dev-only event loss, not a regression. Document it.\n</impact>\n<impact path=\"client/frontend/dist/dev-pages/about.template.html\" element=\"committed build output (and dist/assets)\">\n**What changes.** Not in the plan. Today it holds only the CSS link (line 8) and no script, and it lags the source until a rebuild.\n\n**What depends on it.** Prod gets the beacon only after `scripts/sync.sh` runs `npm run build` (sync.sh:19).\n\n**Regression risk.** Low. State in the delivery comment that prod sends nothing until the next sync. The built-page test must not write here.\n</impact>\n<impact path=\"scripts/sync.sh\" element=\"build-then-rsync (line 19 onward)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is the only path by which the beacon reaches prod.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"client_backend fixture (73-93) and ClientBackend.request (55-70)\">\n**What changes.** Nothing, unless a helper is added.\n\n**What depends on it.** The new backend tests.\n\n**Regression risk.** Medium for test design.\n- The fixture uses `RateLimiter(1000, 60)` (line 84), so the plan's \"91 posts \u2192 429\" test cannot run on it. It needs its own server with `RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS)`.\n- `ClientBackend.request` always sets `content-type: application/json` and JSON-encodes the body. The `text/plain`, invalid-JSON, non-UTF-8, empty-body and custom UA/Referer cases need raw `urllib.request`.\n- A 204's empty body comes back as `None`, which is fine.\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"_serving (383-391), _client_backend(tmp_path, engine_base, rate_limiter) (394-403), _status (406-414), test_route_limiter_buckets_by_last_hop (417)\">\n**What changes.** Nothing, unless the new tests live here or copy these helpers.\n\n**What depends on it.** It is the precedent for the rate-limit test: `_client_backend(..., RateLimiter(...))` builds a server with a chosen limiter. The peer 127.0.0.1 is a trusted proxy by default, so `X-Forwarded-For` can model a fresh address per test.\n\n**Regression risk.** Low. No existing test enumerates POST routes or uses the new path.\n</impact>\n<impact path=\"tests/active/test_frontend_profile.py\" element=\"esbuild-in-node pattern (ESBUILD line 21, RUNNER 23-43, _bundle 46-62)\">\n**What changes.** Nothing. It is the template for the node test. The `--define:import.meta.env.VITE_CLIENT_API_BASE=...` and `--define:import.meta.env.DEV=false` flags (56-57) are required, or `import.meta.env` is undefined in node.\n\n**What depends on it.** The new frontend test. `test_frontend_video_page.py:105,117,133` and `test_frontend_videos_page.py:57,65,80` are the precedents for `globalThis.document`/`fetch` stubs and `unhandledRejection` capture.\n\n**Regression risk.** For the new test:\n- No active test stubs `navigator`. On Node 21 and later `globalThis.navigator` is a getter, so plain assignment may not take. Use `Object.defineProperty(globalThis, \"navigator\", {value, configurable: true})`.\n- Every stub, `window` and `location` included, must be installed before `import()`, because the module acts at import.\n- The Blob payload is read with `await blob.text()`.\n- `document.addEventListener` must capture the handler so the test can dispatch synthetic events with a `target.closest` stub.\n</impact>\n<impact path=\"tests/active/test_analytics_events.py\" element=\"new gating test file(s) (name for the design step)\">\n**What changes.** New tests covering the backend endpoint, the counter that runs SQL taken from DEPLOYMENT.md, the node frontend test and the vite built-page test.\n\n**What depends on it.** The suite gate, and new config.json groups.\n\n**Regression risk.** Medium.\n- **SQL extraction.** Pin the subsection heading and assert the expected number of `sql` blocks, so an empty extraction cannot pass vacuously.\n- **Timestamps.** Bound `created_at` by `now_ms()` taken before and after the request.\n- **Columns.** Assert the exact `PRAGMA table_info(analytics_events)` column list, not just the absence of an IP column.\n- **Build output.** Run the vite build in `tmp_path` with a generous timeout. Skip with a reason only when `dev-pages/about.html` exists.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups (lines 14-269)\">\n**What changes.** A new `test_groups` entry for each new test file. It maps the file to:\n- `client/backend/server.py`\n- `client/backend/lib/users_store.py`\n- `client/backend/lib/http_utils.py`\n- the new frontend module\n- `client/frontend/src/data/api-base.ts`\n- `client/frontend/dev-pages/about.template.html`\n- `client/frontend/vite.config.ts`\n- `DEPLOYMENT.md`, for the SQL extraction\n\n**What depends on it.** The validator that selects re-runs. These existing groups claim server.py and/or users_store.py and will re-run:\n- `test_profiles`\n- `test_dislikes`\n- `test_frontend_profile`\n- `test_server`\n- `test_blocks`\n- `test_frontend_blocks`\n- `test_frontend_reactions`\n- `test_frontend_upnext_pager`\n\n**Regression risk.** Medium. Without a group, the new tests are not selected when these files change.\n\nLines 263-268 are pre-existing drift. They map `test_static_page_visit_logs.py`, which does not exist, onto `DEPLOYMENT.md`, `vite.config.ts`, `about.template.html` and `server.py`, all four of which this build edits.\n</impact>\n<impact path=\"tests/active/test_static_page_visit_logs.py\" element=\"(does not exist)\">\n**What changes.** Nothing. Glob for `**/test_static_page_visit_logs*` finds no file. Issue 21's plan said the test step would write it; it was never written.\n\n**What depends on it.** Four places claim it as a guard:\n- the plan (\"stays green\");\n- DEPLOYMENT.md:465's rat-tail comment;\n- config.json:263;\n- issue 21's delivery.\n\n**Regression risk.** No regression, since no About URL or dev-pages name changes, but the claimed guard is absent. Drop the \"stays green\" wording, name the gap in the delivery comment, and open a follow-up issue.\n</impact>\n<impact path=\"tests/tmp/test_21_static_page_visit_logs_phase1.py\" element=\"template reads (phase1/2/3 working files)\">\n**What changes.** Nothing.\n\n**What depends on it.** These working files serve the template bytes through a real nginx.\n\n**Regression risk.** None for the gate: they are not gating. The extra tag lengthens the template, which keeps any template-versus-override length difference true.\n</impact>\n<impact path=\"tests/active/test_profiles.py\" element=\"users.db byte scan (line 103)\">\n**What changes.** Nothing.\n\n**What depends on it.** The users.db contents.\n\n**Regression risk.** None. The new table holds no key material.\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"Client route smoke checks (lines 548-617)\">\n**What changes.** Nothing is planned. A 204 check here would write a real row into the target users.db.\n\n**What depends on it.** Nothing.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"tests/check-frontend-client-gateway.sh\" element=\"forbidden-pattern scan of client/frontend/src (lines 22-38)\">\n**What changes.** Nothing.\n\n**What depends on it.** It will scan the new module.\n\n**Regression risk.** None, provided the module routes through `resolveClientApiBase` and hardcodes no Engine host or internal route.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"per-group records\">\n**What changes.** The run regenerates it. Never hand-edit it.\n\n**What depends on it.** The validator.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage: new subsection \\\"Count About analytics events\\\" between \\\"Follow an About visit\\\" (232-258) and \\\"Follow one request\\\" (260)\">\n**What changes.** A new subsection with:\n- the `sqlite3 -readonly <root>/client/backend/db/users.db` invocation;\n- fenced `sql` blocks: total clicks per `track_id`, daily clicks per `track_id` in UTC, total and daily `page_view` (optionally per `page_path`), and the bot-filtered variants.\n\nIts caveats:\n- counts are forgeable at 90/min per address;\n- retention is unbounded;\n- the UA filter is a heuristic;\n- Referer is often reduced;\n- middle-click and context-menu opens are not counted;\n- non-http(s) tracked links are rejected;\n- a shared or misresolved address silently undercounts;\n- dev cross-origin beacons may be lost;\n- the shared-connection limitation, if it is documented here.\n\n**What depends on it.** The counter test extracts its SQL from here.\n\n**Regression risk.** Medium, through that coupling. Renaming the heading or changing a fence breaks the gate.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\\\"Follow an About visit\\\": recipe prose (line 241) and caveat (line 258)\">\n**What changes.**\n- **Line 258.** Say the pageview beacon exists, point to the new subsection, and change the path to `docs/project/issues/archive/18-about-outbound-click-tracking.md`.\n- **Line 241.** It says \"The page's own API calls are new requests\". Until now the template page made none. Every view now produces a `POST /api/analytics/event` `request.start` from the visitor's `ip`, plus one per tracked click, so the 242-250 recipe always prints at least the beacon. Add one sentence.\n- **Line 254.** The caveat stays true, because the beacon does not carry the pages-log request id.\n\n**What depends on it.** Runbook readers.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a75 route prose (lines 404-410)\">\n**What changes.** Lines 404-406 say \"There is no browser-facing event publish route\". Clarify that `POST /api/analytics/event` is browser-facing and keyless, stores Client-side rows in users.db, and publishes nothing to the Engine. The keyed-route list on line 410 is unchanged.\n\n**What depends on it.** Readers of the boundary contract.\n\n**Regression risk.** Low. The line 408 phrasing \"creates at startup, so there is no migration step\" also covers the new table.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a71 users.db list (70), \u00a76 CSP (459) and prose (515, 519), rat-tail (465), X-Forwarded-For prose (523), Verify (533-541), Triage CORS row (209)\">\n**What changes.**\n- **70.** Optionally note that users.db now holds `analytics_events`, which grows without pruning and matters for backups.\n- **459, 515, 519.** No change. `script-src 'self'` and `connect-src 'self' https:` already cover the bundle and the beacon, and 519's \"template carries no `<meta>` CSP\" stays true.\n- **465.** It cites the non-existent test. Flag it; do not silently rewrite it.\n- **523.** \"Omit the lines and every visitor shares one bucket\" now also means a silent analytics undercount. Cross-reference it.\n- **533-541.** Optionally add a POST check, noting that it writes a real row.\n- **209.** The dev CORS row also covers dev beacons.\n\n**What depends on it.** Operators.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"client/README.md\" element=\"Backend Responsibilities (10-23), Boundary Contract (41), scope wording (6, 10), CLIENT_CORS_ORIGINS (71)\">\n**What changes.**\n- **New bullet** for `POST /api/analytics/event`, covering:\n  - the two types and their fields;\n  - 204/400/429;\n  - Content-Type ignored;\n  - no key needed;\n  - rows in users.db `analytics_events`;\n  - nothing IP-derived stored;\n  - no Engine publish.\n- **Line 41.** The \"write/profile\" list gets the route, or an \"analytics\" line is added.\n- **Lines 6 and 10.** \"write/profile API service\" is now slightly narrow; optionally widen it.\n- **Line 71.** Optionally add the dev beacon note.\n- **Lines 13 and 69.** Both stay true.\n\n**What depends on it.** Readers.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"client/frontend/README.md\" element=\"\\\"Local About Overrides\\\" (36-42), \\\"What it does\\\" (7-19), Boundary Contract (24)\">\n**What changes.**\n- **Overrides.** Add the module's root-absolute `<script type=\"module\" src=\"/src/...\">` tag and `data-track-id=\"<[a-z0-9_]{1,64}>\"` on each outbound link. Only http(s) links count, and middle-click and context-menu opens are not counted. An override without the tag sends nothing.\n- **\"What it does\".** Add a bullet for the About `page_view`/`outbound_click` beacons.\n- **Line 24.** Under `npm run dev`, beacons are cross-origin and need `CLIENT_CORS_ORIGINS`, and may be lost.\n\n**What depends on it.** Owners of the untracked override.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"README.md\" element=\"boundary table row (line 50)\">\n**What changes.** Line 50 lists the Client backend's browser-facing write/profile routes. Add `/api/analytics/event`, or a new row for it. The plan omits this file, but the requirement \"wherever ... lists the Client backend's public routes\" covers it.\n\n**What depends on it.** Readers.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"lines 4 and 19 (Engine does not own browser-facing write/profile routes)\">\n**What changes.** Optional. The Engine does not own `/api/analytics/event` either. Both lines stay true without an edit.\n\n**What depends on it.** Nothing.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"new **Analytics event** entry, near **Interaction event** (line 6); **Client address** (line 9) unchanged\">\n**What changes.** One line in the `- **Term** \u2014 ...` style. An analytics event:\n- has the types `outbound_click` and `page_view`;\n- is owned by the Client backend (users.db `analytics_events`) and never sent to the Engine;\n- is anonymous, with nothing derived from the address stored;\n- is distinct from an **Interaction event**.\n\nLine 9 (\"keys every rate limiter\") stays true.\n\n**What depends on it.** Domain docs.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"docs/project/issues/18-about-outbound-click-tracking.md\" element=\"Status (line 3), `## Comments`, file location\">\n**What changes.**\n- Set `Status: enhancement, complete`.\n- Append a delivery comment in the style of archive/21:31. It names the plan and the departures from the issue text:\n  - the route is `/api/analytics/event`, not `/outbound-click`;\n  - the table is `analytics_events`, not `outbound_click_events`;\n  - validation is by shape, not an allowlist (line 15);\n  - there is no `ip_hash` (line 16);\n  - the template and the override docs changed, not `client/frontend/about.html` (line 14), which does not exist.\n- The comment also names the follow-ups: the shared-connection race and the missing static-page test.\n- Move the file to `docs/project/issues/archive/` (issue-tracker.md:21).\n\n**What depends on it.** Links to the current path at DEPLOYMENT.md:258 and in plan 23.\n\n**Regression risk.** Low. Update those links in the same change. Slug-only references (archive/21:27,31, plan 22) need no change.\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"P5 row (line 42), lane 5c (line 98)\">\n**What changes.**\n- **Line 42.** \"19, 20 and 21 are delivered, and 18 remains\" becomes all four delivered.\n- **Line 98.** Mark 18 delivered, with the plan path.\n\n**What depends on it.** The tracker.\n\n**Regression risk.** None. The plan names only lane 5c, but line 42 needs the change too.\n</impact>\n<impact path=\"docs/project/issues/21-static-page-visit-logs.md\" element=\"stale non-archive duplicate of delivered issue 21\">\n**What changes.** Nothing is planned. It sits beside its `archive/` copy: issue 21's delivery recorded that it could not delete it. Its line 27 mentions 18 by slug only.\n\n**What depends on it.** Tracker hygiene.\n\n**Regression risk.** None. Mention it in the delivery notes.\n</impact>\n<impact path=\"docs/project/plans/23-18-about-outbound-click-tracking.md\" element=\"the plan document\">\n**What changes.** The workflow renders it, so do not hand-edit it. Per issue-tracker.md:29, a delivered plan moves to `docs/project/plans/archive/`, and links from plan.md:98 and the issue-18 comment must follow if it moves.\n\n**What depends on it.** Those links.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"docs/project/adr/0004-cors-opt-in-by-origin.md\" element=\"CORS opt-in decision\">\n**What changes.** Nothing. The build sends no credentials header and no `*`. The dev beacon caveat follows from this ADR, so cite it there.\n\n**What depends on it.** Nothing new.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"docs/project/adr/0002-trusted-proxy-client-address.md\" element=\"client address resolution\">\n**What changes.** Nothing. The analytics limiter keys on this address, so a misconfiguration now also undercounts analytics silently.\n\n**What depends on it.** Counting accuracy.\n\n**Regression risk.** None from the code. It needs a docs caveat only.\n</impact>\n</impacts>\n</impacts>\n\n<docs_checklist>\n<doc path=\"DEPLOYMENT.md\">\n- **New Triage subsection \"Count About analytics events\"**, between \"Follow an About visit\" and \"Follow one request\". It holds:\n  - the `sqlite3 -readonly` invocation;\n  - fenced `sql` blocks for total and daily (UTC) clicks per `track_id`, total and daily `page_view` (optionally per `page_path`), and the bot-filter variants;\n  - its caveats: forgeable within 90/min per address, unbounded retention, a heuristic UA filter, reduced Referer, middle-click and context-menu not counted, non-http(s) links rejected, a shared or misresolved address undercounts, and dev cross-origin beacons may be lost.\n- **Line 241.** One sentence: each About view now produces its own beacon `request.start`.\n- **Line 258.** The beacon exists; point to the new subsection and change the issue path to `archive/`.\n- **Lines 404-406.** The new keyless browser-facing route, which publishes nothing to the Engine.\n- **Optional.**\n  - 70: users.db holds `analytics_events` and grows unpruned;\n  - 523: cross-reference to the undercount;\n  - Verify: a POST that writes a row.\n- **Line 465.** Flag that it names the non-existent `tests/active/test_static_page_visit_logs.py`.\n</doc>\n<doc path=\"client/README.md\">\n- **Backend Responsibilities.** A new bullet for `POST /api/analytics/event`, covering:\n  - the two types and their fields;\n  - 204/400/429;\n  - Content-Type ignored;\n  - no key needed;\n  - users.db `analytics_events`;\n  - nothing IP-derived stored;\n  - no Engine publish.\n- **Boundary Contract, line 41.** Add the route.\n- **Optional.** Widen lines 6 and 10, and add a dev beacon note at line 71.\n</doc>\n<doc path=\"client/frontend/README.md\">\n- **\"Local About Overrides\".**\n  - the module's root-absolute script tag;\n  - the `data-track-id` convention (`[a-z0-9_]{1,64}`);\n  - only http(s) links count, and middle-click and context-menu opens do not;\n  - an override without the tag sends nothing.\n- **\"What it does\".** A bullet for the About beacons.\n- **Line 24.** Under `npm run dev`, beacons are cross-origin, need `CLIENT_CORS_ORIGINS`, and may be lost.\n</doc>\n<doc path=\"README.md\">\nLine 50 boundary table: add `/api/analytics/event` to the Client backend's browser-facing routes, or add a row for it.\n</doc>\n<doc path=\"CONTEXT.md\">\nA new **Analytics event** entry:\n- the two types;\n- owned by the Client backend in users.db, never sent to the Engine;\n- anonymous;\n- distinct from an **Interaction event**.\n</doc>\n<doc path=\"docs/project/issues/18-about-outbound-click-tracking.md\">\n- Set `Status: enhancement, complete`.\n- Add a delivery comment that names the plan and the departures from the issue text: the route, the table, no allowlist, no ip_hash, and the template plus override docs rather than `about.html`.\n- Name the follow-ups: the shared-connection race and the missing static-page test with its config.json group.\n- Note that prod gets the beacon only after the next `scripts/sync.sh`.\n- Move the file to `docs/project/issues/archive/` and update the link at DEPLOYMENT.md:258.\n</doc>\n<doc path=\"docs/project/issues/plan.md\">\n- Line 42 (P5 row): mark 18 delivered.\n- Line 98 (lane 5c): mark 18 delivered and give the plan path.\n</doc>\n<doc path=\".un/skills/devsecops/config.json\">\n- Add a `test_groups` entry for each new test file, mapping it to:\n  - `server.py`\n  - `users_store.py`\n  - `http_utils.py`\n  - the new frontend module\n  - `api-base.ts`\n  - `about.template.html`\n  - `vite.config.ts`\n  - `DEPLOYMENT.md`\n- Note that the existing `test_static_page_visit_logs.py` group points at a missing file.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nclient/backend/server.py (new analytics validator): any unguarded type escapes as an exception and gives no response instead of the required 400. The cases are a non-str field into `re.fullmatch`/`urlsplit`, `bool`/`float` timestamps, lone-surrogate strings that fail at INSERT, and `.hostname` raising on a malformed bracketed host.\nclient/backend/server.py (connect_db and the shared `user_db` connection): one unlocked sqlite3 connection is shared by every handler thread. `with conn:` commits or rolls back whatever is open, so a 90/min anonymous beacon route makes cross-thread commits or rollbacks of half-done profile writes far more likely. It is inherited, but this build is the first to amplify it.\ntests/active/conftest.py (client_backend fixture and request helper), together with the vite and node test setup. The fixture's `RateLimiter(1000, 60)` cannot produce the planned 91st-request 429, and `ClientBackend.request` forces JSON. `navigator` must be stubbed with defineProperty before import. A `vite build` into the untracked-but-not-ignored `tests/tmp` leaves artifacts. Any of these makes the gating tests wrong or vacuous rather than red.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI read the files the inventory points at: `server.py` (imports, constants, `connect_db`, the handler, `_serve_get`/`_serve_post`, `_rate_limit_check`, the read-body idiom at 1014-1018 and 1050-1054), `http_utils.py`, `users_store.py`, `api-base.ts`, `vite.config.ts`, `about.template.html`, `conftest.py`, the `test_server.py` limiter helpers, `test_frontend_profile.py`, `config.json`, `.gitignore`, `package.json`, the DEPLOYMENT.md sections it cites, README.md, CONTEXT.md and plan.md. Every inventory claim I checked matches the tree. The plan holds. I found four small things the inventory does not carry: a body the JSON parser cannot handle without a 400, how `page_path` splits the About counts, the fact that `config.json` is not tracked in git, and one more README line.\n<question id=\"1\">\nYes. The route slots into `_serve_post` before line 501 with the same rate-limit-then-handler shape as its neighbours. `read_json_body` (http_utils.py:78-95) never reads Content-Type, and every parse failure it raises is a `ValueError` that the 1014-1018 idiom turns into a 400. `ensure_user_schema` runs at startup, `respond_bytes(self, 204, b\"\")` is already used at line 462, `resolveClientApiBase()` with no argument returns the env base or `window.location.origin`, and the vite `about` input picks up the template's module script. Things that would break it if done carelessly, all already listed as impacts: build URLs with `new URL`, not string concatenation; check `isinstance(str)` before every string operation in the validator; and the rate-limit test needs its own server (`conftest.py:84` uses `RateLimiter(1000, 60)`). One edge the plan misses (new impact 1): a body nested deeply enough to raise `RecursionError` inside `json.loads` gets no response at all instead of a 400. Every JSON route already has this, so it does not stop the build from working.\n</question>\n<question id=\"2\">\n- **First About JS.** The About page gets its first JavaScript and the Client gets its first anonymous write route that every page view hits.\n- **`users.db` growth.** The database grows without bound, and the RateLimiter map gains an entry per distinct address.\n- **Shared connection.** Writes now go through the unlocked shared `user_db` connection far more often than before (`connect_db`, line 232, `check_same_thread=False`, no lock).\n- **Visit tracing.** The \"Follow an About visit\" recipe will always show at least the beacon's `request.start`.\n- **Prod timing.** Prod sends nothing until `scripts/sync.sh` rebuilds `dist/`.\n- **Split page counts.** nginx serves About at `/about`, `/about/` and `/about.html` (DEPLOYMENT.md:467-484), and vite rewrites the same three. `location.pathname` keeps whichever one the visitor used, and `page_path` is stored verbatim, so per-`page_path` page_view counts for the one About page come out as three rows (new impact 2).\n- **Test groups.** The new test groups go into `.un/skills/devsecops/config.json`, which `.gitignore:32` excludes, so they never reach the commit (new impact 3).\n</question>\n<question id=\"3\">\nCode: nothing beyond the plan. Existing routes are untouched because the match is on the exact path. GET still answers 404, `do_OPTIONS` already answers any path, and nginx `location /api/` already proxies the route.\n\nDocs and tracker, which the inventory already lists:\n- the line 241/258 and line 404-406 DEPLOYMENT.md edits;\n- README.md:50;\n- the plan.md:42 and :98 rows;\n- moving issue 18 to the archive and fixing its links;\n- the config.json test groups.\n\nTwo additions here: README.md:28 says \"client write/profile API that publishes normalized events to Engine\", which is now slightly narrow (new impact 4). And because config.json is untracked, its edit has to be made in the working tree that runs the validator, not only in the commit.\n</question>\n<question id=\"4\">\n- **Existing behaviour.** Nothing existing changes. Every current route, status code, CORS header and schema table stays the same. `ensure_user_schema` adds one table and one index, and its docstring grows.\n- **About page.** It changes from a static page with no script to one that POSTs on load and on clicks of tracked links. It never calls `preventDefault`, so navigation is unchanged. CSP `script-src 'self'` / `connect-src 'self'` already allow this.\n- **DEPLOYMENT.md:404 \"no browser-facing event publish route\".** The statement stays literally true, since nothing is published to the Engine, but it needs the clarifying sentence the inventory already lists.\n- **Rate limits.** Analytics gets its own 90/min bucket per address (the key is `ip:path`, line 516), so it does not use up the other routes' budgets.\n</question>\n</summary>\n\n<new_impacts>\nclient/backend/lib/http_utils.py \u2014 `read_json_body` (lines 89-92) catches only `json.JSONDecodeError`. A body nested deeply enough (e.g. 100k `[` within the 1 MB cap) makes `json.loads` raise `RecursionError`, which is not a `ValueError`. It slips past both `read_json_body` and the handler's `except ValueError` and reaches socketserver's `handle_error`. The client gets no response and `request.end` logs status `-`, so the plan's \"invalid JSON \u2192 400\" fails for that input. The flaw is shared by every JSON route but now sits on an anonymous route hit on every page view. Cost to cover: catch `RecursionError` alongside `ValueError` in the new handler, one line, or add it to `read_json_body`, which changes a shared helper that the inventory says to leave alone. An oversized integer literal raises `ValueError` (the int-digits limit) and is correctly a 400.\nDEPLOYMENT.md \u2014 the new \"Count About analytics events\" subsection's per-`page_path` page_view queries. nginx (467-484) and vite's `rewriteToAbout` serve About at `/about`, `/about/` and `/about.html`, `location.pathname` keeps whichever one the visitor used, and `page_path` is stored verbatim, so one page appears as up to three groups. The doc should either say so or show a query that folds them (e.g. `rtrim(replace(page_path, '.html', ''), '/')`). The counter test should seed at least two variants if a folded query is documented.\n.un/skills/devsecops/config.json \u2014 `.gitignore:32` ignores `.un/`, so the new `test_groups` entries (and any fix to the stale 263-268 entry) are local-only and do not ship with the commit. Re-run selection for the new tests exists only in working trees that carry this file.\nREADME.md \u2014 line 28's component summary (\"client write/profile API that publishes normalized events to Engine\") is narrow now that the backend also stores analytics events it never publishes. It is a separate element from the line-50 boundary row already in the inventory. Optional one-phrase widening.\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Catch `RecursionError` in `_handle_analytics_event`'s body read alongside `ValueError`, answer 400, and add a test with a deeply nested body.** Costs: about two lines and one test case. Keep `read_json_body` itself unchanged, as the inventory advises. A shared-helper fix for the other routes belongs in a follow-up issue rather than this build.\n2. **Fold the three About URLs in the documented per-`page_path` page_view queries, or state the split in a caveat.** Costs: one SQL expression or one bullet. If folded, the counter test seeds `/about` and `/about.html` and asserts one group. Normalising on the server instead would change the settled rule that `page_path` is stored verbatim, so I do not recommend it.\n3. **Make the `config.json` test-group edits in the working tree that runs the validator, and say in the delivery comment that they are local (`.un/` is gitignored).** Costs: nothing extra. The alternative, moving the config into git, is out of scope.\n4. **Take the inventory's design-stage items as given:**\n   - `new URL` for the endpoint;\n   - an `isinstance(str)` check before each string rule;\n   - a surrogate-encodability check on `href` and `page_path`;\n   - catching `ValueError` around both `urlsplit` and `.hostname`;\n   - a dedicated server for the 91-post limiter test (the `_client_backend` helper in test_server.py);\n   - raw `urllib` for the text/plain and bad-body cases;\n   - a `tmp_path` vite outDir with `--emptyOutDir`;\n   - `Object.defineProperty` for `navigator`;\n   - stubbing `window`, `location` and `document` before import;\n   - following the built page's `<script src>`, not a fixed asset name.\n\n   Costs: none beyond the planned tests.\n5. **Open follow-up issues for the unlocked shared `user_db` connection, the missing `test_static_page_visit_logs.py`, and optionally `auxclick` counting and an analytics prune.** Costs: tracker entries only. Fixing the connection race in this build would widen its scope beyond the settled plan.\n6. **Optional: widen README.md:28 alongside the line-50 row.** Costs: one phrase.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft: About analytics events (issue 18)\n\nBefore writing this I read: `server.py` (imports, constants, the `_run_request` / `_serve_post` / `_rate_limit_check` handler methods, `_handle_likes_import`, `_read_block_body`, `_parse_client_likes`), `lib/users_store.py`, `src/data/api-base.ts`, `src/data/user-actions.ts`, `dev-pages/about.template.html`, `videos.html`, `vite.config.ts`, `tests/active/conftest.py`, the `test_server.py` server helpers, `test_frontend_profile.py`, DEPLOYMENT.md 228-263, archive issue 21 and the `config.json` test groups.\n\n**Template defect.** The step's \"ladder the draft is written against\" arrived as the literal placeholder `{rat_tail_ladder}`. No ladder was rendered, so this draft is checked against the high-level plan, the requirements, the settled impacts and the settled doc list only.\n\n### What the build must prove (test inventory first)\n\n1. **Valid events.** A valid `outbound_click` and a valid `page_view` (with `track_id`/`href` either absent or `null`) each answer 204 with an empty body and add exactly one row.\n   - `created_at` falls between the server `now_ms()` readings taken before and after the request. It is not the client `timestamp`.\n   - `user_agent` and `referer` are copied from the headers. Empty or absent values are stored as NULL.\n2. **Content-Type is ignored.** A `text/plain` body carrying a valid event gets 204.\n3. **Exact schema.** `PRAGMA table_info(analytics_events)` returns exactly `id, type, track_id, href, page_path, created_at, user_agent, referer`, so no IP-derived column exists.\n4. **Invalid bodies.** Every invalid body gets 400 with a JSON `error` and leaves zero rows. That includes bodies that would crash a naive validator (unhashable `type`, lone surrogates, a malformed IPv6 host).\n5. **Rate limit.** Under the production limiter (90/60 s), the 91st POST from one address gets 429 and the row count stays at 90.\n6. **Unknown method.** `GET /api/analytics/event` gets 404.\n7. **Counting queries.** The SQL blocks taken from DEPLOYMENT.md's new subsection, run read-only against the fixture DB, return the expected counts after N posted clicks and views.\n8. **Browser behaviour (node).**\n   - Import sends exactly one `page_view`.\n   - A tracked click sends one correct `outbound_click`.\n   - An untracked click, or a click on a Text node, sends nothing.\n   - `fetch` with `keepalive` is used when `sendBeacon` is missing, returns false, or throws.\n   - No unhandled rejection occurs when `fetch` rejects.\n9. **Built page.** A real `vite build` of the template references a bundled `/assets/*.js` entry that contains `/api/analytics/event`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `client/backend/server.py` | imports `re` and `urlsplit`; imports `insert_analytics_event`; 4 constants; one `_serve_post` branch; `_handle_analytics_event` method; module functions `_validate_analytics_event`, `_analytics_href_ok`, `_utf8_safe` |\n| `client/backend/lib/users_store.py` | table + index in `ensure_user_schema` and its docstring; new `insert_analytics_event` |\n| `client/frontend/src/about-analytics.ts` | new module (whole file below) |\n| `client/frontend/dev-pages/about.template.html` | one script tag |\n| `tests/active/test_analytics_events.py` | new gating file (backend, counter, node, vite build) |\n| `.un/skills/devsecops/config.json` | one `test_groups` entry |\n| docs | DEPLOYMENT.md, client/README.md, client/frontend/README.md, README.md, CONTEXT.md, issue 18 (moved to archive), plan.md, two new follow-up issues 42 and 43 |\n\n**Placement decision.** The impacts asked for the module's location to be decided at design. It stays at `src/about-analytics.ts`, as every settled impact and doc entry names it.\n- It is not a page entry: About has no page logic, so `src/pages/about/index.ts` would claim a convention that doesn't apply.\n- Keeping it means the template tag, the README, the test and config.json all name one path.\n\n### Backend: `client/backend/server.py`\n\n**Imports.**\n- `import re` is added between `import random` and `import signal`.\n- Line 20 becomes `from urllib.parse import parse_qs, urlencode, urlparse, urlsplit`.\n- The users_store import block becomes:\n```python\nfrom lib.users_store import (clear_likes, close_like, ensure_user_schema, fetch_recent_likes,\n                             get_or_create_user, insert_analytics_event, load_liked_keys,\n                             record_like, remove_like, video_reaction)\n```\n\n**Constants.** These go after `BLOCK_REFERENCE_MAX_LENGTH = 200`:\n```python\nANALYTICS_EVENT_TYPES = frozenset((\"outbound_click\", \"page_view\"))\n# fullmatch only: `$` would accept a trailing newline.\nANALYTICS_TRACK_ID_PATTERN = re.compile(r\"[a-z0-9_]{1,64}\")\nANALYTICS_HREF_MAX_LENGTH = 2048\nANALYTICS_PAGE_PATH_MAX_LENGTH = 256\n```\n\n**Route.** The new branch goes in `_serve_post`, after the blocks branch and before the `/client/events/publish` comment and the final 404:\n```python\n        if url.path == \"/api/analytics/event\":\n            if not self._rate_limit_check(url.path):\n                respond_json(self, 429, {\"error\": \"Rate limit exceeded\"})\n                return\n            self._handle_analytics_event()\n            return\n```\n- The rate-limit check runs before any parsing.\n- The limiter key is `<ip>:/api/analytics/event`, so analytics gets its own 90/min bucket.\n\n**Handler method.** It sits next to `_handle_likes_import`:\n```python\n    def _handle_analytics_event(self) -> None:\n        \"\"\"Store one About page analytics event; the client address is never stored, only rate-limited on.\"\"\"\n        try:\n            body = read_json_body(self)\n        except ValueError as exc:\n            respond_json(self, 400, {\"error\": str(exc)})\n            return\n        event = _validate_analytics_event(body)\n        if isinstance(event, str):\n            respond_json(self, 400, {\"error\": event})\n            return\n        event_type, track_id, href, page_path = event\n        user_agent = self.headers.get(\"User-Agent\", \"\").strip() or None\n        referer = self.headers.get(\"Referer\", \"\").strip() or None\n        with self.server.user_db:\n            insert_analytics_event(self.server.user_db, event_type, track_id, href, page_path, now_ms(), user_agent, referer)\n        respond_bytes(self, 204, b\"\")\n```\n- **Content-Type.** Never read, because `read_json_body` ignores it.\n- **Empty body.** It parses to `{}` and fails on `type`, so it gets 400.\n- **Errors from `read_json_body`.** It raises `ValueError` for invalid JSON, a non-object body, non-UTF-8 bytes (`UnicodeDecodeError`), and a bad or over-1 MB length. Each becomes 400.\n- **Headers.** They arrive latin-1 decoded, so they always bind in SQLite.\n- **One clock read.** `now_ms()` is read exactly once per row.\n\n**Validator.** These are module-level functions placed after `_parse_client_likes`. They are pure and never raise on any JSON-decoded dict.\n```python\ndef _validate_analytics_event(body: dict[str, Any]) -> tuple[str, str | None, str | None, str] | str:\n    \"\"\"Handle validate analytics event.\n\n    :returns: `(type, track_id, href, page_path)` to store, or the error message for a 400.\n    \"\"\"\n    event_type = body.get(\"type\")\n    # Checked as a str first: a list or dict `type` is unhashable and would raise in the set lookup.\n    if not isinstance(event_type, str) or event_type not in ANALYTICS_EVENT_TYPES:\n        return \"type must be outbound_click or page_view\"\n    page_path = body.get(\"page_path\")\n    if (not isinstance(page_path, str) or not 1 <= len(page_path) <= ANALYTICS_PAGE_PATH_MAX_LENGTH\n            or not page_path.startswith(\"/\") or not _utf8_safe(page_path)):\n        return \"page_path must be a path of 1 to 256 characters starting with /\"\n    timestamp = body.get(\"timestamp\")\n    # bool is an int subclass; a JSON 1.0 arrives as float and is rejected too. Checked, then discarded.\n    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0:\n        return \"timestamp must be a non-negative integer\"\n    track_id = body.get(\"track_id\")\n    href = body.get(\"href\")\n    if event_type == \"page_view\":\n        if track_id is not None or href is not None:\n            return \"page_view takes no track_id or href\"\n        return event_type, None, None, page_path\n    if not isinstance(track_id, str) or not ANALYTICS_TRACK_ID_PATTERN.fullmatch(track_id):\n        return \"track_id must match [a-z0-9_]{1,64}\"\n    if not _analytics_href_ok(href):\n        return \"href must be an absolute http or https URL of at most 2048 characters\"\n    return event_type, track_id, href, page_path\n\n\ndef _analytics_href_ok(href: Any) -> bool:\n    \"\"\"Return whether `href` is an absolute http(s) URL with a host, short enough and storable.\"\"\"\n    if not isinstance(href, str) or len(href) > ANALYTICS_HREF_MAX_LENGTH or not _utf8_safe(href):\n        return False\n    try:\n        # `.hostname` re-parses the netloc and can raise on a malformed bracketed host, so it sits inside the try.\n        parts = urlsplit(href)\n        hostname = parts.hostname\n    except ValueError:\n        return False\n    return parts.scheme in (\"http\", \"https\") and bool(hostname)\n\n\ndef _utf8_safe(value: str) -> bool:\n    \"\"\"Return whether `value` encodes as UTF-8; a JSON lone surrogate decodes to a str sqlite3 cannot bind.\"\"\"\n    try:\n        value.encode(\"utf-8\")\n    except UnicodeEncodeError:\n        return False\n    return True\n```\n\nInvariants:\n- **Return shape.** The result is either a 4-tuple whose values are safe to bind, or an error string.\n- **`track_id` encoding.** It needs no UTF-8 check because its regex is ASCII-only.\n- **Scheme case.** `urlsplit` lowercases the scheme, so `HTTPS://x.y` passes.\n- **Rejected `href` shapes.** `https://` (hostname None), `http://[::1` (ValueError), `mailto:` and `/relative` all fail.\n- **`page_path` is stored verbatim.** `//host` passes, which is acceptable because the value is never followed.\n- **Known looseness.** `urlsplit` silently drops tab and newline characters when it parses, so an `href` containing them passes and is stored verbatim. Browsers never produce such a resolved `href`. There is no extra rule because the spec does not ask for one.\n\n### Storage: `client/backend/lib/users_store.py`\n\n**Docstring.** Line 11 becomes `\"\"\"Create the users, likes, like generation, profile, block, dislike and analytics event tables if missing.\"\"\"`.\n\n**Schema.** Inserted after the `like_generations` table and before the `-- Every visitor's actions\u2026` cleanup:\n```sql\n        CREATE TABLE IF NOT EXISTS analytics_events (\n          id INTEGER PRIMARY KEY,\n          type TEXT NOT NULL CHECK (type IN ('outbound_click', 'page_view')),\n          track_id TEXT,\n          href TEXT,\n          page_path TEXT NOT NULL,\n          created_at INTEGER NOT NULL,\n          user_agent TEXT,\n          referer TEXT\n        );\n        CREATE INDEX IF NOT EXISTS analytics_events_type_track_created_idx\n          ON analytics_events (type, track_id, created_at);\n```\n\n**Insert function.** New, placed after `video_reaction`. It does not commit: the handler's `with self.server.user_db:` owns the transaction, following `remove_like`/`close_like`.\n```python\ndef insert_analytics_event(conn: sqlite3.Connection, event_type: str, track_id: str | None, href: str | None,\n                           page_path: str, created_at: int, user_agent: str | None, referer: str | None) -> None:\n    \"\"\"Insert one analytics event, inside the caller's transaction.\"\"\"\n    conn.execute(\n        \"INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES (?, ?, ?, ?, ?, ?, ?)\",\n        (event_type, track_id, href, page_path, created_at, user_agent, referer),\n    )\n```\n\n**Startup.** No edit: `server.py:1311` already calls `ensure_user_schema`, so existing DBs gain the table on restart.\n\n### Frontend: `client/frontend/src/about-analytics.ts`\n\n```ts\n/**\n * Module `client/frontend/src/about-analytics.ts`: send the About page's analytics events (one page view, one event per tracked outbound click).\n */\n\nimport { resolveClientApiBase } from \"./data/api-base\";\n\ntype AnalyticsEvent =\n  | { type: \"page_view\"; page_path: string; timestamp: number }\n  | { type: \"outbound_click\"; track_id: string; href: string; page_path: string; timestamp: number };\n\n/**\n * Handle send analytics event. Never throws and never rejects: analytics must not surface to the visitor.\n */\nfunction sendAnalyticsEvent(event: AnalyticsEvent): void {\n  try {\n    // No argument, so `?api=` is never read; built with `new URL` like every sibling, so a base ending in `/` gives no `//api`.\n    const url = new URL(\"/api/analytics/event\", resolveClientApiBase()).toString();\n    const body = JSON.stringify(event);\n    try {\n      // Called on `navigator` itself: a detached reference throws \"Illegal invocation\".\n      if (typeof navigator !== \"undefined\" && typeof navigator.sendBeacon === \"function\"\n        && navigator.sendBeacon(url, new Blob([body], { type: \"application/json\" }))) {\n        return;\n      }\n    } catch {\n      // A refused cross-origin beacon can throw; fetch gets one more try.\n    }\n    fetch(url, { method: \"POST\", body, headers: { \"Content-Type\": \"application/json\" }, keepalive: true }).catch(() => undefined);\n  } catch {\n    // A bad base, a missing fetch or an over-64 KiB keepalive body throws synchronously; swallowed.\n  }\n}\n\n/**\n * Handle document click: one outbound_click per click that resolves to an `a[data-track-id]`.\n */\nfunction handleDocumentClick(event: Event): void {\n  const target = event.target as Element | null;\n  // A Text node or the document itself has no `closest`.\n  if (!target || typeof target.closest !== \"function\") {\n    return;\n  }\n  const link = target.closest(\"a[data-track-id]\");\n  if (!link) {\n    return;\n  }\n  // An SVG <a>'s `href` is an SVGAnimatedString; the server would reject it, so nothing is sent.\n  const href = (link as HTMLAnchorElement).href;\n  if (typeof href !== \"string\") {\n    return;\n  }\n  sendAnalyticsEvent({\n    type: \"outbound_click\",\n    track_id: link.getAttribute(\"data-track-id\") ?? \"\",\n    href,\n    page_path: window.location.pathname,\n    timestamp: Date.now()\n  });\n}\n\nsendAnalyticsEvent({ type: \"page_view\", page_path: window.location.pathname, timestamp: Date.now() });\ndocument.addEventListener(\"click\", handleDocumentClick);\n```\n- **No exports.** The module acts on import. A module script is deferred, so `document` is parsed by the time it runs and there is no DOMContentLoaded wait.\n- **No `preventDefault`,** so navigation is untouched.\n- **A malformed `data-track-id`** (for example uppercase) is still sent and gets 400. That is the shape-validation contract, and the README documents the pattern.\n- **Gateway scan.** There is no Engine base, no `127.0.0.1:707x` literal and no `/internal/` path, so `check-frontend-client-gateway.sh` passes.\n\n### Template: `client/frontend/dev-pages/about.template.html`\n\nOne line goes before `</body>`, as in `videos.html:65`:\n```html\n    <script type=\"module\" src=\"/src/about-analytics.ts\"></script>\n```\nNo About URL or dev-pages filename changes.\n\n### Tests: `tests/active/test_analytics_events.py`\n\nOne file holds everything, so one config.json group maps it to all eight settled paths (the \"fewest files\" choice).\n\n**Constants and helpers:**\n- `FRONTEND`, `ESBUILD` and `VITE` (`node_modules/.bin/vite`).\n- `_post(base, raw: bytes, headers: dict) -> (status, body)` over raw `urllib.request`. This is needed for `text/plain`, invalid JSON, non-UTF-8 and custom/empty UA. Setting `User-Agent: \"\"` overrides urllib's default.\n- `_rows(db_path)` reads all rows as dicts.\n- `_event(**overrides)` builds a valid click body.\n- `_serving_limited(tmp_path)` is a contextmanager. It builds `ClientBackendServer` exactly as conftest does, but with `RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS)`.\n\n**Backend tests (they use the conftest `client_backend` fixture unless stated):**\n- `test_outbound_click_stores_one_row`:\n  - Setup: take `before = now_ms()`, then POST a click with `timestamp: 1`, `User-Agent: Mozilla/5.0 analytics-test`, `Referer: https://example.org/about`.\n  - Expect a 204 with an empty body.\n  - Expect exactly one row with the expected `type`, `track_id`, `href` and `page_path`, `before <= created_at <= now_ms()`, `created_at != 1`, and UA and Referer equal to the headers.\n- `test_page_view_stores_one_row`: parametrized over `track_id`/`href` absent vs explicit `null`. Expect 204, one row with NULL `track_id` and `href`.\n- `test_text_plain_beacon_accepted`: send `Content-Type: text/plain;charset=UTF-8`. Expect 204 and one row.\n- `test_missing_headers_store_null`: send `User-Agent: \"\"` and no Referer. Both columns are NULL.\n- `test_schema_has_no_address_column`: the `PRAGMA table_info` names equal the exact 8-column list.\n- `test_invalid_event_rejected` is parametrized over raw bodies. Each case expects 400, a JSON `error` key and zero rows. Status is asserted, not message text. The cases:\n  - **body:** `b\"\"`, `b\"{\"`, `b\"[]\"`, `b\"\\xff\"`;\n  - **type:** missing, `\"click\"`, `[\"page_view\"]`;\n  - **track_id:** missing on a click, `null` on a click, `\"About_Patreon\"`, `\"\"`, 65\u00d7`a`, `\"a-b\"`, `\"abc\\n\"`, `5`;\n  - **href:** missing, `\"mailto:a@b.c\"`, `\"javascript:alert(1)\"`, `\"https://\"`, `\"/relative\"`, `\"http://[::1\"`, `\"https://x.y/\" + \"a\"*2040`, `42`, `json.dumps(\"https://x.y/\\ud800\")`;\n  - **page_path:** missing, `\"\"`, `\"about\"`, `\"/\" + \"a\"*256`, `7`, `\"/\\ud800\"`;\n  - **timestamp:** missing, `\"1\"`, `1.0`, `true`, `-1`, `null`;\n  - **page_view:** with `track_id: \"about_x\"`, and with `href: \"https://x.y\"`.\n- `test_get_is_not_a_route`: `GET` gives 404.\n- `test_rate_limit_rejects_and_stores_nothing`: uses `_serving_limited`, with `X-Forwarded-For: 203.0.113.18` (127.0.0.1 is a trusted proxy by default). 90 valid posts each give 204. The 91st gives 429 with `{\"error\": \"Rate limit exceeded\"}`, and the row count is 90.\n\n**Counter test (`test_documented_queries_count_events`):**\n- **Extraction.**\n  - The DEPLOYMENT.md text is sliced from `### Count About analytics events` to the next `\\n### `.\n  - Blocks are found with `re.findall(r\"```sql\\n(.*?)```\", section, re.S)`.\n  - The test asserts `len(blocks) == 7`, so the extraction can't pass vacuously.\n- **Posted events:**\n  - 3 clicks `about_test`;\n  - 1 click `about_other`;\n  - 1 click `about_test` with UA `Googlebot/2.1`;\n  - 1 click `about_test` with empty UA;\n  - page views: 2 on `/about` and 1 on `/about.html`, plus 1 on `/about` with UA `bingbot`.\n- **Connection.** The DB is opened with `sqlite3.connect(f\"file:{db}?mode=ro\", uri=True)`, matching `-readonly`.\n- **Expected results.** `day` is computed from the stored `created_at` rather than from the wall clock, so the test is midnight-safe. Each block in order must return:\n  1. `{about_test: 5, about_other: 1}`\n  2. `[(day, about_other, 1), (day, about_test, 5)]`\n  3. `4`\n  4. `[(day, 4)]`\n  5. `{/about: 3, /about.html: 1}`\n  6. `{about_test: 3, about_other: 1}`\n  7. `[(day, 3)]`\n- The clicks for one `track_id` are counted, which is the counter acceptance criterion.\n\n**Node test (`test_beacon_dispatch`):**\n- **Bundling.** `src/about-analytics.ts` is bundled with esbuild using `--define:import.meta.env.VITE_CLIENT_API_BASE=\"http://api.test/\"` (trailing slash on purpose) and `--define:import.meta.env.DEV=false`.\n- **Runner stubs, all installed before `await import(BUNDLE)`:**\n  - `globalThis.window = {location: {origin: \"http://page.test\", pathname: \"/about\"}}`;\n  - `Object.defineProperty(globalThis, \"navigator\", {value: {...}, configurable: true})`, with `sendBeacon` per `MODE`: `true` returns true, `false` returns false, `missing` is undefined, `throws` throws;\n  - `globalThis.document = {addEventListener: (t, h) => handlers.push([t, h])}`;\n  - `globalThis.fetch` records the call and returns `Promise.reject(new Error(\"offline\"))`;\n  - a `process.on(\"unhandledRejection\")` counter.\n- **Runner actions.** After the import, the runner:\n  - dispatches the captured click handler with three targets: a tracked target whose `closest` returns `{href: \"https://www.patreon.com/x\", getAttribute: () => \"about_patreon\"}`, an untracked target whose `closest` returns null, and a Text-like `{}`;\n  - awaits `blob.text()` for each beacon and lets microtasks drain;\n  - prints JSON of `{sent: [{via, url, body, keepalive, contentType}], rejections}`.\n- **Assertions,** parametrized over the four MODEs:\n  - exactly 2 sends;\n  - every `url == \"http://api.test/api/analytics/event\"`;\n  - the first is `page_view` with `page_path \"/about\"` and an int `timestamp`;\n  - the second is `outbound_click` with `about_patreon`, the href, `/about` and an int `timestamp`;\n  - `via` is `beacon` only in mode `true`, otherwise `fetch` with `keepalive: true` and `Content-Type: application/json`;\n  - `rejections == 0`;\n  - exactly one `click` listener is installed.\n\n**Built-page test (`test_built_about_page_bundles_beacon`):**\n- **Skip.** It runs `pytest.skip` with a reason when `FRONTEND / \"dev-pages/about.html\"` exists, because a local override would be built instead of the template.\n- **Build.** `[VITE, \"build\", \"--outDir\", str(tmp_path / \"dist\"), \"--emptyOutDir\"]` runs with `cwd=FRONTEND`, an env without `VITE_CLIENT_API_BASE`, and `timeout=300`. It never writes into `client/frontend/dist` or `tests/tmp`.\n- **Assertions.**\n  - `dist/dev-pages/about.template.html` contains a `src=\"(/assets/[^\"]+\\.js)\"` script.\n  - That entry file contains `/api/analytics/event`. The literal lives in the module, which is the About entry chunk, while `api-base` may be split into a shared chunk.\n\n### `.un/skills/devsecops/config.json`\n\nA new entry is added before `test_static_page_visit_logs.py`. That existing entry is left in place and flagged in issue 43.\n```json\n    \"test_analytics_events.py\": [\n      \"client/backend/server.py\",\n      \"client/backend/lib/users_store.py\",\n      \"client/backend/lib/http_utils.py\",\n      \"client/frontend/src/about-analytics.ts\",\n      \"client/frontend/src/data/api-base.ts\",\n      \"client/frontend/dev-pages/about.template.html\",\n      \"client/frontend/vite.config.ts\",\n      \"DEPLOYMENT.md\"\n    ],\n```\n\n### Docs (content drafted, one paragraph per line in the files)\n\n**DEPLOYMENT.md, new `### Count About analytics events`.** It goes between \"Follow an About visit\" and \"Follow one request\".\n- **Lead paragraph.** The About page's own script sends a `page_view` per load and an `outbound_click` per click on an `a[data-track-id]` to `POST /api/analytics/event`. The Client backend stores each as one row of `analytics_events` in `users.db`, with server time in `created_at` (epoch ms), `user_agent` and `referer`, and no address. The queries below count them.\n- **Invocation.** `sudo sqlite3 -readonly <root>/client/backend/db/users.db`.\n- **The seven `sql` blocks,** one statement each and in this order. The order is pinned by the counter test.\n  1. `SELECT track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' GROUP BY track_id ORDER BY clicks DESC;`\n  2. `SELECT date(created_at / 1000, 'unixepoch') AS day, track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' GROUP BY day, track_id ORDER BY day, track_id;`\n  3. `SELECT COUNT(*) AS views FROM analytics_events WHERE type = 'page_view';`\n  4. `SELECT date(created_at / 1000, 'unixepoch') AS day, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY day ORDER BY day;`\n  5. `SELECT page_path, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY page_path ORDER BY views DESC;`\n  6. Block 1 with `AND user_agent IS NOT NULL AND user_agent NOT LIKE '%bot%' AND user_agent NOT LIKE '%crawl%' AND user_agent NOT LIKE '%spider%'` added to the `WHERE`.\n  7. Block 4 with the same filter.\n- **Prose around the blocks.**\n  - Days are UTC.\n  - Add `page_path` to block 4's SELECT and GROUP BY to split daily views by path.\n  - Add the four filter conditions to any query to exclude obvious bots. `LIKE` is ASCII case-insensitive.\n- **Caveats** (one bullet each):\n  - **Forgeable counts.** The endpoint is anonymous and accepts up to 90 per minute per address.\n  - **Unbounded retention.** Rows are never pruned, so `users.db` grows. It matters for backups.\n  - **The UA filter is a heuristic.** It removes honest crawlers only.\n  - **Referer is often reduced** to the About URL by the default referrer policy.\n  - **Clicks not counted.** Middle-click and context-menu \"open in new tab\" are not counted. Ctrl/Cmd-click and keyboard activation are.\n  - **Non-http(s) tracked links** (`mailto:`, `tel:`) are rejected and never counted.\n  - **Silent undercount.** A shared or misresolved client address caps a whole population at 90/min. `sendBeacon` never sees the 429. See `TRUSTED_PROXIES`, ADR-0002 and section 6's `X-Forwarded-For` lines.\n  - **Dev beacons may be lost.** Under `npm run dev` the API base is cross-origin. A credentialed `application/json` beacon's preflight gets no `Access-Control-Allow-Credentials` (ADR-0004), so dev beacons may be lost.\n  - **Shared connection.** Analytics writes share the single unlocked `users.db` connection with profile writes (issue 42).\n  - **Prod rollout.** Prod sends nothing until `scripts/sync.sh` rebuilds `dist/`.\n\n**DEPLOYMENT.md, edits elsewhere:**\n- **241.** Append: \"Every About view now also makes one `POST /api/analytics/event` (and one per tracked click), so the window always shows at least that beacon's `request.start`.\"\n- **258.** Second sentence becomes: \"Counting human visits uses the page's own pageview beacon: see \"Count About analytics events\" and `docs/project/issues/archive/18-about-outbound-click-tracking.md`.\"\n- **404-406.** Add: \"`POST /api/analytics/event` is browser-facing and needs no key: it stores About analytics rows in the Client's `users.db` and publishes nothing to the Engine.\"\n- **465.** Add a parenthesis to the rat-tail comment: \"(`tests/active/test_static_page_visit_logs.py` does not exist yet; issue 43)\".\n- **Optional lines taken:**\n  - **70:** \"`analytics_events`, unpruned\".\n  - **523:** \"\u2026and About analytics undercounts silently\".\n- **Skipped as optional.** The Verify POST is left out, because it would write a real row into prod `users.db`.\n\n**client/README.md:**\n- **New Backend Responsibilities bullet:** \"`POST /api/analytics/event`: anonymous About analytics. Body `{type: \"page_view\", page_path, timestamp}` or `{type: \"outbound_click\", track_id, href, page_path, timestamp}`. Answers 204, 400 on any invalid field, 429 over the route limit. Content-Type is ignored and no profile key is needed. One row per event in `users.db` `analytics_events`. Nothing derived from the client address is stored, and nothing is published to the Engine.\"\n- **Line 41.** The route list gains `/api/analytics/event`.\n- **Line 71.** Gains: \"also needed for dev About beacons, which may still be lost (credentialed beacon).\"\n\n**client/frontend/README.md:**\n- **\"What it does\"** gains a bullet: \"About sends one anonymous `page_view` per load and one `outbound_click` per click on an `a[data-track-id]` link to the Client backend (`src/about-analytics.ts`).\"\n- **\"Local About Overrides\"** gains a paragraph. An override adds `<script type=\"module\" src=\"/src/about-analytics.ts\"></script>` (root-absolute, like the stylesheet) and `data-track-id=\"about_<name>\"` on each outbound link to count, matching `[a-z0-9_]{1,64}`. The paragraph also says:\n  - only http(s) links count;\n  - middle-click and context-menu opens are not counted;\n  - an override without the tag sends nothing, not even page views.\n- **Line 24.** Gains the dev cross-origin note: needs `CLIENT_CORS_ORIGINS`, may be lost.\n\n**README.md line 50.** `/api/analytics/event` is added to the Client backend's browser-facing routes cell.\n\n**CONTEXT.md, after Interaction event:** \"- **Analytics event** \u2014 an anonymous `page_view` or `outbound_click` the About page's own script sends to the Client backend, which stores it in `users.db` `analytics_events` with nothing derived from the client address and never sends it to the Engine; unlike an **Interaction event**, it does not feed ranking.\"\n\n**Issue 18:**\n- `Status: enhancement, complete`.\n- `git mv` to `docs/project/issues/archive/`.\n- A comment in the style of archive/21:31, covering:\n  - which plan delivered it;\n  - the route and table names chosen, and that no allowlist or `ip_hash` was used;\n  - that the template and override docs changed, not the non-existent `client/frontend/about.html`;\n  - the follow-ups, issues 42 and 43;\n  - that prod beacons start after the next `scripts/sync.sh`;\n  - that the stale non-archive `21-static-page-visit-logs.md` duplicate remains.\n\nDraft wording:\n> Delivered by `docs/project/plans/23-18-about-outbound-click-tracking.md`, as one route `POST /api/analytics/event` for both `page_view` and `outbound_click` (not `/outbound-click`), one table `analytics_events` (not `outbound_click_events`), shape validation instead of an allowlist (the real About page is an untracked override), and no `ip_hash` or other address-derived value. The tracked template `dev-pages/about.template.html` and the override docs changed; `client/frontend/about.html` does not exist. Counts are queried with the \"Count About analytics events\" runbook in `DEPLOYMENT.md`. Prod sends nothing until the next `scripts/sync.sh`. Follow-ups: `42-users-db-shared-connection-race`, `43-static-page-visit-logs-test-missing`. The stale `docs/project/issues/21-static-page-visit-logs.md` duplicate is still beside its archive copy.\n\n**plan.md:**\n- **Line 42.** \"19, 20, 21 and 18 are delivered\".\n- **Line 98.** \"18 delivered by `docs/project/plans/23-18-about-outbound-click-tracking.md`\". The plan document itself is workflow-rendered and not hand-edited. If it moves to `plans/archive/`, this link and the issue comment follow.\n\n**New follow-up issues (`Status: bug, needs-triage`):**\n- **`42-users-db-shared-connection-race.md`.** One `check_same_thread=False` connection is shared by all handler threads without a lock. A `with conn:` on one thread commits or rolls back another's transaction. The anonymous analytics route raises the write rate. Fix with a write lock or per-thread connections.\n- **`43-static-page-visit-logs-test-missing.md`.** Issue 21's guard `tests/active/test_static_page_visit_logs.py` was never written. It is still cited at DEPLOYMENT.md:465 and config.json:263.\n\n### Check against plan and requirements\n\n**Pass 1 found and fixed these gaps:**\n- **Unhashable `type`.** `type` as a list raised `TypeError` in the frozenset lookup, which drops the connection. It is now checked as a str first.\n- **SVG links.** An SVG link sent a non-string `href`. It now sends nothing.\n- **Missing `navigator`.** A missing `navigator` threw before the fallback. It is now guarded.\n- **Rate-limit fixture.** The rate-limit test could not use the fixture's 1000/60 limiter, so it has its own server.\n- **Header in a test.** One test also needed an empty UA header.\n\n**Pass 2: every requirement maps to code or a test:**\n- **Endpoint.** Route, 204/400/429, Content-Type ignored, `_run_request` wrapping, GET 404.\n- **Validation.** Every validation rule and the unknown-keys rule.\n- **Schema and storage.** Exact schema, CHECK and index, created at startup, `now_ms`, UA/Referer\u2192NULL, no address, one row per request, no pruning.\n- **Frontend.** Module behaviour, transport and fallback, swallowed failures, Client API base, template tag, override docs.\n- **Docs and tracker.** Reporting queries including the bot filter, doc route lists, CONTEXT entry, tracker housekeeping.\n- **Acceptance tests.** One for each acceptance bullet.\n\nNothing remains unmet. It converged on pass 2.\n\n**Limitations the operator accepts** (from the plan, all documented):\n- **Override checkouts.** The built-page gate skips on a checkout with a local override.\n- **Uncounted opens.** Middle-click and context-menu opens are not counted.\n- **Non-http(s) links.** Tracked non-http(s) links are not counted.\n- **Best-effort counts.** Counts are best-effort: forgeable within 90/min/address, unpruned, with a heuristic bot filter.\n- **Dev beacons.** Dev cross-origin beacons may be lost.\n- **Shared connection.** The shared-connection race is inherited, and filed as issue 42 rather than fixed here.\n- **Missing guard.** `test_static_page_visit_logs.py` does not exist, so the plan's \"stays green\" wording is dropped and issue 43 is filed instead.\n\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: `lib/users_store.py` called directly on a tmp `sqlite3` connection. No server is involved. Assert two things. First, after `ensure_user_schema(conn)` (run twice, to show it is idempotent), `[r[1] for r in conn.execute(\"PRAGMA table_info(analytics_events)\")]` equals exactly `[\"id\",\"type\",\"track_id\",\"href\",\"page_path\",\"created_at\",\"user_agent\",\"referer\"]`. Second, one `insert_analytics_event(...)` inside `with conn:` leaves exactly one row with the passed values, read back through a second connection to the same file.</checkpoint>\n<name>Analytics storage</name>\n<intent>`users.db` gains an `analytics_events` table, created by `ensure_user_schema` with the settled columns, CHECK and index. `lib/users_store.py` gains an `insert_analytics_event` that writes one row inside the caller's transaction.</intent>\n<clause_1>After `ensure_user_schema`, `analytics_events` has exactly the eight settled columns and none derived from the client address.</clause_1>\n<clause_2>One `insert_analytics_event` call inside `with conn:` commits exactly one row with the given values.</clause_2>\n<files>client/backend/lib/users_store.py (EDITED), tests/active/test_analytics_events.py (NEW)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the pure module function `client_server._validate_analytics_event(dict)`, imported the way `test_server.py` imports server internals. Assert that valid `outbound_click` and `page_view` bodies return the expected `(type, track_id, href, page_path)` tuple, including `track_id`/`href` absent versus `null` and unknown keys ignored. Assert that every invalid body in the draft's case list (`type`, `track_id`, `href`, `page_path`, `timestamp` and the page_view-with-extras cases, including the list `type`, lone surrogates and `http://[::1`) returns a `str` and does not raise. The parametrization is taken from the draft's list.</checkpoint>\n<name>Event validator</name>\n<intent>`server.py` gains a pure `_validate_analytics_event` (with `_analytics_href_ok` and `_utf8_safe`) that turns any JSON-decoded dict into either the four storable values or an error message, following the settled rules.</intent>\n<clause_1>Each valid event body yields its `(type, track_id, href, page_path)` tuple.</clause_1>\n<clause_2>Each invalid event body yields an error string without raising.</clause_2>\n<files>client/backend/server.py (EDITED), tests/active/test_analytics_events.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: real HTTP over a socket to `ClientBackendServer`, through the conftest `client_backend` fixture, with raw `urllib.request` POSTs (the `test_server.py` precedent). The 429 case uses a `_serving_limited` server built like conftest but with the production `RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)` and `X-Forwarded-For: 203.0.113.18`. For accepted events, assert 204 with an empty body and exactly one row. `created_at` must be within the [before, after] `now_ms()` window and not equal the client `timestamp`. UA and Referer must be copied from the headers, and empty or absent values must be NULL. This holds for `application/json` and `text/plain`. For refused POSTs, assert the row count is unchanged: a sample of invalid bodies (empty, `{`, `[]`, `\\xff` and one per field) gets 400 with a JSON `error`, and the 91st of 91 gets 429 with `{\"error\":\"Rate limit exceeded\"}` and 90 rows. A `GET` of the path gets 404 as a regression line, not as a clause.</checkpoint>\n<name>Analytics route</name>\n<intent>`POST /api/analytics/event` in `_serve_post` stores each accepted event as one server-stamped row in `analytics_events`, and stores nothing for a request it refuses.</intent>\n<clause_1>A valid event of either type, with any Content-Type, gets 204 and adds one row whose `created_at`, `user_agent` and `referer` come from the server.</clause_1>\n<clause_2>A refused POST, whether 400 for an invalid body or 429 over the route limit, adds no row.</clause_2>\n<files>client/backend/server.py (EDITED), tests/active/test_analytics_events.py (EDITED), .un/skills/devsecops/config.json (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>There are two seams. (a) `src/about-analytics.ts` is bundled with the project's esbuild into node, the same harness as `tests/active/test_frontend_profile.py`, with `VITE_CLIENT_API_BASE=\"http://api.test/\"` defined. Stubbed `window`, `navigator`, `document` and a rejecting `fetch` are installed before the import. The test is parametrized over the sendBeacon modes true, false, missing and throws. It asserts exactly 2 sends to `http://api.test/api/analytics/event`: a `page_view` for `/about` and then an `outbound_click` with `about_patreon` and its href, where the untracked target and the Text-like target send nothing. It also asserts beacon delivery only in mode true and otherwise fetch with `keepalive: true` and `Content-Type: application/json`, 0 unhandled rejections, and one `click` listener. (b) A real `node_modules/.bin/vite build --outDir <tmp_path>/dist` run from `client/frontend`. It asserts that `dist/dev-pages/about.template.html` has a `src=\"/assets/*.js\"` script whose file contains `/api/analytics/event`. It skips with a reason if `dev-pages/about.html` exists.</checkpoint>\n<name>About beacon</name>\n<intent>The About page template loads a new `src/about-analytics.ts`, which on import sends one `page_view` and then one `outbound_click` per click on an `a[data-track-id]`. Delivery is `sendBeacon` with a keepalive `fetch` fallback, and the built page ships it as a bundled asset.</intent>\n<clause_1>Importing the module sends one `page_view` and one `outbound_click` per tracked click, falling back to keepalive `fetch` when `sendBeacon` is unavailable, refuses or throws.</clause_1>\n<clause_2>A vite build of the About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`.</clause_2>\n<files>client/frontend/src/about-analytics.ts (NEW), client/frontend/dev-pages/about.template.html (EDITED), tests/active/test_analytics_events.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone. No credential, live endpoint or manual step is needed. Phase 4 needs `client/frontend/node_modules` (esbuild and vite) installed, which `test_frontend_profile.py` already requires. Its built-page check skips on a checkout that has an untracked `dev-pages/about.html` override.\n</needs_coordination>\n\n<rationale>\nThe build splits along the dependency chain, so each slice can be checked before the next one exists. Storage (P1) is tested on a bare sqlite connection. The validator (P2) is a pure function and gets the large invalid-case matrix without a server. The route (P3) puts them together over a socket and only needs a sample of invalid bodies plus the rate limit. The frontend (P4) depends on nothing in the backend and is proven in node and through a real vite build.\n\nEach phase's Intent reduces to two clauses. Phase 3's second clause is one fact, \"a refused request stores nothing\", parametrized over the two refusal causes (400 and 429). GET\u2192404 is not a clause because unknown routes already answer 404. It stays in the P3 test only as a regression line.\n\nThe counter test (`test_documented_queries_count_events`) extracts its SQL from DEPLOYMENT.md. Documentation gets no phase, so the operator approved moving that test to Step 9, where it is added together with the \"Count About analytics events\" subsection and gated by the full-suite-green close. The config.json test group lands in P3, where the test file starts covering `server.py`.\n\nAll other documentation and tracker edits are left to Step 9 as well: DEPLOYMENT.md, both READMEs, README.md, CONTEXT.md, the move of issue 18, plan.md and issues 42 and 43. There is no prose phase, because no agent-facing text changes.\n\nTemplate defect: `{principles}`, `{shape_ladder-ladder}` and `{tdd_seams}` arrived unrendered. Seams were therefore chosen from the existing harnesses: the conftest `client_backend` fixture, `test_server.py`-style raw POSTs, and `test_frontend_profile.py`'s esbuild-in-node runner. All three exist in the tree.\n</rationale>",
    "author:tests/tmp/test_18_about_outbound_click_tracking_phase1.py": "<assertions>\ntests/tmp/test_18_about_outbound_click_tracking_phase1.py:42 \u2014 after two ensure_user_schema runs, the PRAGMA table_info(analytics_events) names equal exactly [\"id\",\"type\",\"track_id\",\"href\",\"page_path\",\"created_at\",\"user_agent\",\"referer\"], so an ip_hash or any other address-derived column fails it (current code: [] \u2014 observed red here) \u2014 C1\ntests/tmp/test_18_about_outbound_click_tracking_phase1.py:43 \u2014 each column's (name, declared type, notnull, pk) matches the settled DDL: id INTEGER pk, type/page_path/created_at NOT NULL, created_at INTEGER, the rest nullable TEXT (catches a nullable page_path) \u2014 C1\ntests/tmp/test_18_about_outbound_click_tracking_phase1.py:44 \u2014 the table's only index covers [\"type\",\"track_id\",\"created_at\"] in that order. The index name is not asserted because it is not part of the settled contract \u2014 C1\ntests/tmp/test_18_about_outbound_click_tracking_phase1.py:49-51 \u2014 a raw INSERT with type 'click' raises sqlite3.IntegrityError matching \"CHECK\" \u2014 C1\ntests/tmp/test_18_about_outbound_click_tracking_phase1.py:52 \u2014 a row written before a third ensure_user_schema run is still the only row afterwards: the run neither drops nor recreates the table, and the refused CHECK insert left nothing \u2014 C1 (idempotence)\ntests/tmp/test_18_about_outbound_click_tracking_phase1.py:65 \u2014 insert_analytics_event inside a `with conn:` that raises leaves zero rows, seen through a second connection. This proves the write is part of the caller's transaction, so an implementation that calls conn.commit() itself fails here (current code: AttributeError, no insert_analytics_event \u2014 observed red) \u2014 C2\ntests/tmp/test_18_about_outbound_click_tracking_phase1.py:71 \u2014 one insert_analytics_event inside a completed `with conn:` leaves exactly one row, read through a fresh second connection, equal to the seven passed values in their own columns. Every value is distinct and non-null, so swapping two columns (e.g. user_agent and referer) fails it \u2014 C2\n</assertions>\n\n<probes>\n1) tests/tmp/test_probe_18_p1.py (first version), run as ValidateTests [\"tests/tmp/test_probe_18_p1.py\",\"-s\"]. It applied the plan's settled DDL twice to a tmp sqlite file (sqlite 3.53.4, Python 3.14.7) and printed:\n- `lib.users_store` imports from tests/tmp via sys.path at client/backend; `insert_analytics_event` is absent today; the current ensure_user_schema gives table_info(analytics_events) = [].\n- table_info: [(0,'id','INTEGER',0,None,1),(1,'type','TEXT',1,None,0),(2,'track_id','TEXT',0,None,0),(3,'href','TEXT',0,None,0),(4,'page_path','TEXT',1,None,0),(5,'created_at','INTEGER',1,None,0),(6,'user_agent','TEXT',0,None,0),(7,'referer','TEXT',0,None,0)].\n- index_list: [(0,'analytics_events_type_track_created_idx',0,'c',0)]; index_info: [(0,1,'type'),(1,2,'track_id'),(2,5,'created_at')].\n- A 'click' insert raises \"IntegrityError CHECK constraint failed: type IN ('outbound_click', 'page_view')\".\n- After a rolled-back `with conn:` and then a committed one, a second connection saw only the committed row.\n\n2) The same file, rewritten as a self-check, run as ValidateTests [\"tests/tmp/test_probe_18_p1.py\",\"-s\",\"-v\"] and then with \"-k planned\". It monkeypatched users_store and called the checkpoint's two test functions:\n- Against the planned DDL plus a plain INSERT (no commit), both pass.\n- Against mutants, each one fails at the expected assertion:\n  - ip_hash column \u2192 names mismatch;\n  - nullable page_path \u2192 defs mismatch;\n  - no index \u2192 [] vs expected;\n  - no CHECK \u2192 \"DID NOT RAISE IntegrityError\";\n  - DROP+CREATE \u2192 [] vs surviving row;\n  - insert that commits itself \u2192 rolled-back row still present;\n  - user_agent/referer swapped \u2192 value mismatch.\n\n3) The checkpoint against the current tree, ValidateTests [\"tests/tmp/test_18_about_outbound_click_tracking_phase1.py\"]: 2 failed, at line 42 (`assert [] == ['id','type',...]`) and line 62 (AttributeError: no insert_analytics_event). After that run I edited only the line-52 comment (\"second run\" \u2192 \"third run\"); no assertion changed.\n\nI have no delete tool, so tests/tmp/test_probe_18_p1.py is still there. It is a throwaway and can be removed once this checkpoint is accepted.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_18_about_outbound_click_tracking_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase1.py:42 \u2014 `[row[1] for row in PRAGMA table_info(analytics_events)] == COLUMNS`, after ensure_user_schema has run twice</assertion>\n<expected>[\"id\", \"type\", \"track_id\", \"href\", \"page_path\", \"created_at\", \"user_agent\", \"referer\"]. The probe showed exactly this for the plan's settled DDL run twice through executescript. Against the current code the run shows `[]` because the table does not exist yet.</expected>\n<wrong_implementation>A table that also has an `ip_hash` or `client_ip` column (the address-derived column the issue first proposed) reads a nine-item list. One missing a column (for example no `referer`) or in a different order also fails, and so does an ensure_user_schema that never creates the table, which reads `[]`.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase1.py:43 \u2014 `(name, type, notnull, pk)` for each column from PRAGMA table_info == COLUMN_DEFS</assertion>\n<expected>[(\"id\",\"INTEGER\",0,1), (\"type\",\"TEXT\",1,0), (\"track_id\",\"TEXT\",0,0), (\"href\",\"TEXT\",0,0), (\"page_path\",\"TEXT\",1,0), (\"created_at\",\"INTEGER\",1,0), (\"user_agent\",\"TEXT\",0,0), (\"referer\",\"TEXT\",0,0)]. Observed in the probe as `(0, 'id', 'INTEGER', 0, None, 1), (1, 'type', 'TEXT', 1, None, 0), \u2026`.</expected>\n<wrong_implementation>Getting the column names right but not the declarations fails here. Examples: `page_path TEXT` without NOT NULL reads notnull 0, `created_at TEXT` reads 'TEXT', and `id INTEGER` that is not the primary key reads pk 0.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase1.py:44 \u2014 the ordered column lists of every index on analytics_events == [[\"type\",\"track_id\",\"created_at\"]]</assertion>\n<expected>[[\"type\", \"track_id\", \"created_at\"]]. The probe saw a single index, analytics_events_type_track_created_idx, whose index_info is (type, track_id, created_at). INTEGER PRIMARY KEY adds no autoindex.</expected>\n<wrong_implementation>Leaving out the CREATE INDEX reads `[]`. An index in a different order, such as (created_at, type, track_id), or an extra UNIQUE constraint that brings an autoindex, reads a different list.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase1.py:49-51 \u2014 inserting type 'click' raises sqlite3.IntegrityError matching \"CHECK\"</assertion>\n<expected>IntegrityError(\"CHECK constraint failed: type IN ('outbound_click', 'page_view')\"), as observed in the probe.</expected>\n<wrong_implementation>A `type TEXT NOT NULL` with no CHECK accepts 'click'. pytest.raises then fails with DID NOT RAISE, and line 52 would also see a second row.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase1.py:52 \u2014 after a row is written and ensure_user_schema runs a third time, STORED reads exactly that one row</assertion>\n<expected>[(\"page_view\", None, None, \"/about\", 1, None, None)]. CREATE TABLE IF NOT EXISTS keeps the row, and the probe showed the CHECK-refused insert is rolled back by `with conn:`.</expected>\n<wrong_implementation>A schema function that does `DROP TABLE IF EXISTS analytics_events` before creating it, or plain CREATE TABLE inside a try/except that recreates the table, reads `[]` here. Plain CREATE TABLE without IF NOT EXISTS raises \"table already exists\" at line 40.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase1.py:71 \u2014 after one insert_analytics_event inside a completed `with conn:`, a second connection reads STORED == the passed values</assertion>\n<expected>[(\"outbound_click\", \"about_patreon\", \"https://www.patreon.com/x\", \"/about.html\", 1767225600123, \"Mozilla/5.0 analytics-test\", \"https://example.org/about\")]. The probe showed this row read back through a second connection after the equivalent INSERT committed. Against the current code the run fails earlier, with AttributeError at line 62.</expected>\n<wrong_implementation>Several plausible bugs fail here. Swapping parameters (href into track_id, or user_agent and referer reversed) shows the value in the wrong column. Writing two rows (for example once per type) reads a two-row list. Stamping created_at with now_ms() instead of the passed value reads a different integer. A no-op insert reads `[]`.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase1.py:65 \u2014 after insert_analytics_event inside a `with conn:` that raises, a second connection reads STORED == []</assertion>\n<expected>[]. The probe showed in_transaction True after the INSERT and `[]` from a reader after the rollback. Line 71 (a written, committed row) is what proves the function writes at all.</expected>\n<wrong_implementation>An insert_analytics_event that calls conn.commit() itself, the way record_like and get_or_create_user do, persists the row before the raise. The reader then sees [(\"page_view\", None, None, \"/rolled-back\", 1, None, None)].</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. C1 is carried by lines 42-44 (exact names, then declared type, NOT NULL and pk, then the one index), 49-51 (the CHECK) and 52 (a further ensure_user_schema keeps the table and its row). The exact column list on line 42 is what excludes any address-derived column. C2 is carried by line 71 (one committed row, each value in its own column, read through a second connection) and line 65 (rolled back with the caller's transaction). Every clause in the module docstring and the test docstrings has an assertion.\n2. Absence only: no. The one absence assertion is line 65, `[]` after rollback. It is armed by line 71 in the same test, where the same function inside a completed `with conn:` produces a row that a second connection can read. If the function wrote nothing, line 71 would fail. Line 52 reads a present row, not an absence.\n3. Echoed literal: no. Expected values are fixed literals, and the test never does production's work. The raw INSERT on line 47 is setup for C1's persistence check and is not the C2 path. Deleting the CREATE TABLE in ensure_user_schema turns line 42 red (observed: `assert [] == [...]`). Deleting the `CREATE INDEX` turns 44 red, deleting the CHECK turns 49 red, and deleting insert_analytics_event's conn.execute turns 71 red.\n4. One value: no. The schema is pinned against the settled column list and declarations, not against another reading from the same source. insert_analytics_event is exercised twice: once rolled back, and once with seven distinct non-null values, so a column swap shows up.\n5. The double: none. Real sqlite3 runs on a tmp file and the real lib.users_store is imported.\n6. It collects: yes. The `--collect-only` summary shows \"no tests\" because that mode only lists, but the real run printed \"collected 2 items\". It reached the module's functions: line 42 executed against `ensure_user_schema`, and the AttributeError on line 62 shows the import bound. Both tests exist and both ran.\n7. Observed, not predicted: yes, now. Before this turn the PRAGMA tuples, the index_info shape and the CHECK message were predictions. I wrote tests/tmp/probe_18_analytics_schema.py, which runs the plan's settled DDL twice and the plan's INSERT, and ran it. It printed `TABLE_INFO [(0, 'id', 'INTEGER', 0, None, 1), (1, 'type', 'TEXT', 1, None, 0), (2, 'track_id', 'TEXT', 0, None, 0), (3, 'href', 'TEXT', 0, None, 0), (4, 'page_path', 'TEXT', 1, None, 0), (5, 'created_at', 'INTEGER', 1, None, 0), (6, 'user_agent', 'TEXT', 0, None, 0), (7, 'referer', 'TEXT', 0, None, 0)]`, `INDEX_INFO analytics_events_type_track_created_idx [(0, 1, 'type'), (1, 2, 'track_id'), (2, 5, 'created_at')]`, `CHECK_ERR IntegrityError(\"CHECK constraint failed: type IN ('outbound_click', 'page_view')\")`, `IN_TXN True`, `AFTER_ROLLBACK []` and `AFTER_COMMIT [(1, 'outbound_click', 'about_patreon', ...)]`. Every expected value in the checkpoint matches, so nothing needed rewriting. I have no delete tool, so the probe file is still there. Its name, probe_*.py, does not match pytest's default test_*.py pattern and pyproject sets no python_files, so it is not collected. It should be removed.\n8. Red, not green: yes, it is red. ValidateTests on the checkpoint printed \"2 failed\" and \"[exit status 1]\".\n9. Red for the right reason: yes. Test 1 failed at line 42 with `AssertionError: assert [] == ['id', 'type'...ated_at', ...]` (\"Right contains 8 more items, first extra item: 'id'\"), because ensure_user_schema does not yet create analytics_events. That line is the C1 assertion, not a control. Test 2 failed at line 62 with `AttributeError: module 'lib.users_store' has no attribute 'insert_analytics_event'`, because the phase's function does not exist yet. This is not a typo: the name and signature are the plan's (`insert_analytics_event(conn, event_type, track_id, href, page_path, created_at, user_agent, referer)`), and the module import resolved. No control assertion failed.\n10. Observed expected output: yes. Each row's `expected` is what the probe printed for the settled DDL and INSERT. The checkpoint run agrees where it reached: line 42 read `[]` on the current code. No row was contradicted by a run.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `client/backend/lib/users_store.py`\n- `ensure_user_schema` now also creates `analytics_events` with `CREATE TABLE IF NOT EXISTS`. Its columns are `id INTEGER PRIMARY KEY`, `type TEXT NOT NULL CHECK (type IN ('page_view', 'outbound_click'))`, `track_id TEXT`, `href TEXT`, `page_path TEXT NOT NULL`, `created_at INTEGER NOT NULL`, `user_agent TEXT` and `referer TEXT`. No column comes from the client's address.\n- It also creates the index `analytics_events_type_track_created_idx` on `(type, track_id, created_at)` with `CREATE INDEX IF NOT EXISTS`. Running it again leaves the table, the index and the rows alone. The docstring now lists the analytics event table.\n- New `insert_analytics_event(conn, event_type, track_id, href, page_path, created_at, user_agent, referer)` runs one parameterised `INSERT` and does not commit, so the row belongs to the caller's transaction, the same way `remove_like` and `close_like` work.\n- The event-type argument is called `event_type` so it doesn't shadow the built-in `type`. It goes into the `type` column.\n\n### `tests/active/test_analytics_events.py`\nNot created. This step was to write production code only, and the checkpoint in `tests/tmp/` already covers the phase. The phase's files list names this durable test as NEW, so it is still waiting to be written or promoted from the checkpoint.\n\nI did not run the checkpoint: the workflow's run is the one that counts.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_18_about_outbound_click_tracking_phase2.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D10\">\n<disposition>justified</disposition>\n<what>I narrowed the prose to what the data does. The module docstring at :6 now reads: \"Each invalid body except the empty object `{}` is the valid baseline with one key changed or removed; the baseline is itself asserted valid, so every such rejection is down to that one key. `{}` lacks every key at once and only shows that a body with nothing in it is rejected.\" The one-key claim now covers only the 39 params that are one-key changes. The `{}` case at :57 stays in INVALID and is described for what it is: a whole-body rejection, still carried by :110 (`isinstance(result, str) and result`), which fails a validator that raises KeyError on an empty dict or accepts it. No assertion or param changed.</what>\n</item>\n</items>\n\n<findings_addressed>\nNeither auditor raised a CRITICAL. Claim recommendation 1 (D10, `{}` at :57): taken. I narrowed the docstring sentence at :6 to name `{}` as the exception (see item D10). Claim recommendation 2 (non-object JSON bodies): not taken. The caller's contract for whether non-dict json.loads output reaches this function is not written yet, so adding a case now would mean guessing it. Claim recommendation 3 (page_view page_path edges): not taken. The ledger does not name it, and the C2 params already cover page_path bounds on outbound_click and the missing slash on page_view. Shape recommendation 1 (positive control inside the C2 function): not taken. C1's baseline cases at :45 and :50 run in the same file and gate together with it, and a reject-all stub turns those red.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase2.py:103 \u2014 `client_server._validate_analytics_event(body) == expected` over the 9 VALID params (5 outbound_click, 4 page_view), with the expected tuples written out by hand.</assertion>\n<expected>The exact 4-tuple for each case. For example, (\"outbound_click\", \"about_patreon\", \"https://www.patreon.com/x\", \"/about\") for the baseline, (\"outbound_click\", \"about_patreon\", \"HTTPS://Example.ORG/Path\", \"/about\") for the upper-case scheme, and (\"page_view\", None, None, \"/about\") for the page_view with both keys absent.</expected>\n<wrong_implementation>A validator that lower-cases the scheme returns \"https://Example.ORG/Path\". One with an off-by-one cap returns an error string at track_id 64, href 2048 or page_path 256. One that rejects unknown keys returns an error string on the `ip`/`session` and `referrer`/`extra` cases. One that indexes body[\"track_id\"] on a page_view raises KeyError. A hard-coded tuple matches at most one case. Every one of these reads != expected.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110 \u2014 `isinstance(result, str) and result` over the 40 INVALID params. Each is called directly, so a raise fails the case.</assertion>\n<expected>A non-empty str for every invalid body.</expected>\n<wrong_implementation>Missing the str check before the set lookup raises TypeError on `[\"page_view\"]`. Not catching urlsplit's error raises ValueError on `http://[::1`. Skipping the UTF-8 check returns the tuple for lone surrogates. Using `re.match` with `$` accepts `abc\\n`. Letting bool through as int accepts `true`. A cap that is one too loose accepts 65, 2049 or 257 characters. Skipping the checks on page_view accepts a page_view that carries a track_id or href. Accept-all returns tuples. Each of these reads a tuple, or raises, where a str is required.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Both assertions are positive. :103 requires an exact tuple, so deleting the code under test turns all 9 cases red. :110 requires a non-empty str, so a deleted function fails all 40 cases with AttributeError. A reject-all stub is caught by :103.\n2. No. Every expected tuple is a hand-written literal compared against the production call. The test does no normalising or validation of its own. Deleting the scheme or length handling in `_validate_analytics_event` (the function does not exist yet, so I cannot cite a line) turns :103 red. Deleting any single rule check turns its :110 case red.\n3. No. There are 9 valid and 40 invalid inputs, and nothing is pinned against a sibling value from the same source.\n4. No. There are no doubles; the test imports the real `server` module.\n5. Yes. Only the module docstring changed in this round. Imports, names and helpers are untouched, and the line count is the same (the edit replaced one line with one line), so the 49 cases (9 + 40) are unchanged.\n6. Yes. Every premise the expectations rest on comes from the earlier probe run (Python 3.14.7): urlsplit's ValueError on `http://[::1`, the surrogate encode failure, the `re.match`/`$` behaviour, the unhashable list, bool being an int, and the length counts. This round adds no new expected values.\n7. Yes. The earlier red run gave 49 failed, all with `AttributeError: module 'server' has no attribute '_validate_analytics_event'`. This round's edit was prose inside the docstring only, so it cannot affect collection or the import. I did not run the test again; the workflow's run will confirm it. Separately, the earlier probe file tests/tmp/probe_18_phase2_premises.py is still on disk and needs deleting, because I have no delete tool.\n\nNothing was rewritten in response to these questions, because none came out yes.\n</answers>",
    "self_check:tests/tmp/test_18_about_outbound_click_tracking_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase2.py:103 \u2014 `client_server._validate_analytics_event(body) == expected` across 9 VALID cases (lines 45-53). Five are outbound_click: the baseline; unknown keys `ip`/`session` with an http href and timestamp 0; track_id and page_path at length 1; track_id 64, href 2048 and page_path 256 at the upper bounds; and `HTTPS://Example.ORG/Path` returned unchanged. Four are page_view: track_id and href absent, both null, track_id null with href absent, and href null with unknown keys.</assertion>\n<expected>For outbound_click, the exact 4-tuple `(\"outbound_click\", track_id, href, page_path)` with each value as sent, e.g. `(\"outbound_click\", \"about_patreon\", \"https://www.patreon.com/x\", \"/about\")`. For page_view, `(\"page_view\", None, None, page_path)`. These values are the plan's contract (plan line 817, docstring line 820). They could not be observed because the function does not exist yet: the run shows `AttributeError: module 'server' has no attribute '_validate_analytics_event'` at line 103 for all 9 cases. The probe confirmed the input premises: lengths 2048/64/256, and `urlsplit('HTTPS://Example.ORG/Path')` parses with scheme `https`.</expected>\n<wrong_implementation>Each of these goes red at line 103: a stub or hard-coded tuple (only one case matches); a validator that lower-cases or normalises href (the upper-case case reads `https://example.org/Path`); a `<` instead of `<=` on a length cap (the max-lengths case returns an error string); rejecting unknown keys (both unknown-key cases return a str); treating a present-but-null track_id/href on page_view as a violation (view-both-null returns a str); and returning the body's null values or a different order instead of `(type, None, None, page_path)`.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110 \u2014 `isinstance(result, str) and result` across 40 INVALID bodies (lines 57-96), each passed directly at line 109, so any raise fails the test. Each body is the C1 baseline (`_click()`/`_view()`, which line 103 asserts valid) with one key changed or dropped. The cases cover type (missing, unknown, wrong case, list), track_id (missing, null on click, upper-case, empty, 65 chars, hyphen, trailing `\\n`, int), href (missing, null on click, mailto, javascript, `https://`, relative, `http://[::1`, 2049, 2052, int, lone surrogate), page_path (missing, empty, no slash, 257, int, lone surrogate, no slash on page_view), timestamp (missing, str, float, bool, -1, null, missing on page_view), and page_view carrying a track_id or an href.</assertion>\n<expected>A non-empty `str` (the plan's error message) for every one of the 40 bodies, with no exception. This could not be observed against production because the function does not exist yet: the run shows the same AttributeError at line 109 for all 40. The probe observed the premises that make these cases discriminating. `urlsplit('http://[::1')` raises `ValueError: Invalid IPv6 URL`. `urlsplit` accepts `'https://x.y/\\ud800'`, but sqlite3 binding it raises `UnicodeEncodeError ... surrogates not allowed` (likewise for `'/\\ud800'`). `re.match(r'^[a-z0-9_]{1,64}$', 'abc\\n')` is True while `fullmatch` is False. `isinstance(True, int)` is True. `'https://'`, `'mailto:a@b.c'`, `'javascript:alert(1)'` and `'/relative'` all give hostname None. The lengths are 2049, 2052, 257 and 65.</expected>\n<wrong_implementation>Each of these goes red at line 109 or 110: accepting everything (returns a tuple, not a str); checking set membership before the str check (the list-type case raises TypeError); calling urlsplit without catching ValueError (`http://[::1` raises); `match` with `$` (`abc\\n` returns a tuple); letting bool through as int (`timestamp=True` returns a tuple); an off-by-one on a cap (the 65/2049/257 cases return a tuple); no UTF-8 safety check (the surrogate cases return a tuple, which would later crash the sqlite bind); skipping the extra-field check on page_view (view-with-track-id/href return a tuple); and returning an empty string or None as the error (`result` is falsy or not a str).</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The module docstring makes two claims, and both are carried. The valid-body claim, including the length bounds, the upper-case scheme, unknown keys and the page_view absent/null combinations, is carried at line 103 by VALID lines 45-53. The invalid-body claim, including the list type, both lone surrogates, `http://[::1` and each bound plus one, is carried at line 110 by INVALID lines 57-96. The claim that \"the baseline is itself asserted valid\" holds: `_click()` is the click-baseline case (line 45) and `_view()` is view-absent (line 50).\n2. No. The C2 test makes a positive assertion (the result is a non-empty str), not an absence. \"Does not raise\" is enforced by calling the function directly at line 109, and the str check proves the call returned. The baseline bodies the invalid cases are built from are asserted valid at line 103, so each rejection is down to the one changed key.\n3. No. Each expected tuple is written out by hand, and the validator's job is to return the values verbatim. The max-lengths case builds input and expected from the same literal expression (`\"z9_\" * 21 + \"a\"` and so on), which is the identity contract and not a copy of production's transformation. Deleting `return event_type, track_id, href, page_path` (plan line 844) or `return event_type, None, None, page_path` (line 839) turns line 103 red. Deleting any one rejection branch (lines 824-843) turns line 110 red for its cases.\n4. No. C1 is read at 9 inputs across both event types and C2 at 40 inputs. Nothing is pinned against a sibling from the same source.\n5. No. There are no doubles. The real `server` module is imported from client/backend, the same way tests/active/conftest.py does it.\n6. No problem. `import server` resolves: the failures are AttributeError on the attribute, not an ImportError at import. `json`, `sys`, `Path`, `Any` and `pytest` are all used and bound. The run reported `collected 49 items`, which matches 9 VALID + 40 INVALID. The supplied `--collect-only -q` summary printed \"no tests\" with exit 0, but the real run collected all 49, so I take that to be the summary formatter's rendering of collect-only and not missing tests.\n7. Yes, the premises were not yet observed, so I ran tests/tmp/probe_phase2_premises.py and read its output. All the premises the inputs rely on held, so the checkpoint needed no rewrite: `lens 2048 2049 2052 64 256 257 65`; `urlsplit` accepts `'https://x.y/\\ud800'` while sqlite raises `UnicodeEncodeError ... surrogates not allowed` for both surrogate values; `urlsplit raises 'http://[::1' ValueError Invalid IPv6 URL`; `'https://'`, mailto, javascript and `/relative` give hostname None; `dollar-newline True False`; `bool-is-int True`. The function's return values can't be observed because it doesn't exist yet, so the expected tuples are the plan's contract (plan line 817), labelled as such in the rows. I have no delete tool, so the probe file tests/tmp/probe_phase2_premises.py is still there for removal. It asserts False on purpose and only holds observations.\n8. Yes, it is red. `ValidateTests tests/tmp/test_18_about_outbound_click_tracking_phase2.py`: exit status 1, `collected 49 items`, `49 failed in 0.15s`.\n9. Yes, it is red for the right reason. All 51 `^E`/summary lines are accounted for: the 49 `E` lines are each `AttributeError: module 'server' has no attribute '_validate_analytics_event'`, at line 103 (`tests/tmp/test_18_about_outbound_click_tracking_phase2.py:103: AttributeError`, 9 VALID cases) and line 109 (`...:109: AttributeError`, 40 INVALID cases). The function is exactly what phase 2 adds. Import, collection and parametrization all worked, and there is no control assertion that could fail first.\n10. The run doesn't contradict any row. It stops at the missing function, so neither row's return value could be observed. The rows say so and give the plan's contract as the expected value. Every premise in the rows (lengths, the urlsplit/sqlite surrogate behaviour, the IPv6 ValueError, match vs fullmatch, bool as int) comes from the probe run quoted in answer 7.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `client/backend/server.py`\n- New imports: `re`, and `urlsplit` added to the existing `urllib.parse` import.\n- Four new constants after `BLOCK_REFERENCE_MAX_LENGTH`, in the style of the ones around them: `ANALYTICS_EVENT_TYPES = frozenset((\"outbound_click\", \"page_view\"))`, `ANALYTICS_TRACK_ID_PATTERN = re.compile(r\"[a-z0-9_]{1,64}\")`, `ANALYTICS_HREF_MAX_LENGTH = 2048` and `ANALYTICS_PAGE_PATH_MAX_LENGTH = 256`.\n- New pure function `_validate_analytics_event(body)`, placed after `_parse_client_likes` and taken from the plan's settled code. It returns `(type, track_id, href, page_path)` for a valid event, or an error message for a 400. It never raises. The checks run in this order:\n  - `type` must be a `str` in the two-value set. The `str` check comes first because a list `type` can't be hashed for the set lookup.\n  - `page_path` must be a `str` of 1\u2013256 characters that starts with `/` and can be encoded as UTF-8.\n  - `timestamp` must be a non-negative `int`. `bool` and `float` are rejected. The value is checked and then thrown away.\n  - On a `page_view`, `track_id` and `href` must be absent or null, and the result is `(page_view, None, None, page_path)`.\n  - On an `outbound_click`, `track_id` must match the pattern with `fullmatch`, so a trailing newline is rejected, and `href` must pass `_analytics_href_ok`.\n  - Valid values come back exactly as sent, and unknown keys are ignored.\n- New `_analytics_href_ok(href)`: `href` must be a `str` of at most 2048 characters that encodes as UTF-8. `urlsplit` must give a scheme of `http` or `https` and a non-empty `hostname`. The scheme check ignores case because `urlsplit` lowercases it, but the original `href` is what gets stored. A `ValueError` from `urlsplit` or `.hostname` (for example `http://[::1`) makes it return False.\n- New `_utf8_safe(value)`: returns False when `str.encode(\"utf-8\")` raises `UnicodeEncodeError`. That catches lone surrogates from `json.loads`, which sqlite3 cannot bind.\n- The route, handler method and `insert_analytics_event` import are not added here. They belong to a later phase.\n\n### `tests/active/test_analytics_events.py`\nNot created and not edited. It doesn't exist in the worktree: Phase 1 left it unwritten and recorded that. This step asks for production code only, and the checkpoint in `tests/tmp/` covers this phase. The durable test is still waiting to be written or promoted from the checkpoints.\n\nI did not run the checkpoint, because the workflow's run is the one that counts.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_18_about_outbound_click_tracking_phase3.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D15b\">\n<disposition>justified</disposition>\n<what>I narrowed the prose to what the test asserts. The module docstring's third bullet (line 5) used to say \"Under the production 90-per-60 s route limiter\". It now says \"Under the production route limiter (90 requests per address within its window, whose length is not asserted here)\". The window is still taken from `client_server.RATE_LIMIT_WINDOW_SECONDS` at :79, and no assertion depends on it, because all 91 posts land well inside any realistic window. The docstring no longer claims a 60 s value. The 90-request count stays carried by :148-:150. Only the text of line 5 changed, so no line numbers moved and no assertion changed.</what>\n</item>\n</items>\n\n<findings_addressed>\nNeither auditor raised a CRITICAL. Claim recommendation 1 (D15b, docstring \"90-per-60 s\"): taken. I narrowed the line 5 docstring to \"90 requests per address within its window, whose length is not asserted here\" instead of pinning the window constant. Pinning it would be the hardcoded-spec-mirror form the shape audit warns about. Claim recommendations 2 and 3 (length-boundary and negative/float timestamp cases, a request with no Content-Type, a body-supplied user_agent/referer) are left as they are. They do not block, and they would add cases this ledger does not list. Shape recommendations 1 (the GET regression test is green before phase 3) and 2 (the literal 90 against RATE_LIMIT_MAX_REQUESTS) are also left. The GET test is already labelled as a regression line with no clause. The literal 90 is the docstring's stated production limit, and a wrong limiter fails either way.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:121 \u2014 (status, body) == (204, b\"\") for an outbound_click or page_view sent as application/json, text/plain;charset=UTF-8 or application/x-www-form-urlencoded</assertion>\n<expected>(204, b\"\") in all 5 ACCEPTED cases</expected>\n<wrong_implementation>A route that accepts only application/json, or that answers 200/201 with a body, reads (400 or 415, ...) on the text/plain and form cases, or (200, b\"{...}\").</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:123 \u2014 len(rows) == 1 on a fresh per-test database</assertion>\n<expected>1</expected>\n<wrong_implementation>A route that returns 204 without inserting reads 0; a double insert reads 2.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:125 \u2014 (type, track_id, href, page_path, user_agent, referer) == expected</assertion>\n<expected>The fields as sent; track_id/href NULL on a page_view; user_agent/referer equal to the headers, and None when a header is sent as \"\" or not sent</expected>\n<wrong_implementation>Storing the raw empty header reads \"\" instead of None (param :94). Storing a default UA reads a string where None is expected (:95). Swapping UA and referer reads (REFERER, USER_AGENT) or (None, USER_AGENT) on :96. Handling only one event type fails the other type's cases.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:126-127 \u2014 created_at is an int within [now_ms() before, now_ms() after] and != CLIENT_TIMESTAMP (1)</assertion>\n<expected>An integer ms stamp taken by the server during the request</expected>\n<wrong_implementation>Copying the body timestamp stores 1, which falls outside the window and equals CLIENT_TIMESTAMP.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:134-137 \u2014 each of the 12 REJECTED bodies gets status 400, a JSON non-empty string error, and _rows == []; armed by the :138-:139 control, where a following valid event gets (204, b\"\") and 1 row</assertion>\n<expected>400, a non-empty str error, [] rows, then 1 row after the control post</expected>\n<wrong_implementation>Inserting before validating reads a non-empty table at :137. Accepting a malformed body reads 204 at :134. Crashing reads 500. A route that never writes fails the control at :138-:139.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:148-150 \u2014 after 90 posts from 203.0.113.18 each get 204 (:149), the 91st gets (429, {\"error\": \"Rate limit exceeded\"}) (:148), and the row count is 90 (:150); :151-:152 show 203.0.113.19 is still stored</assertion>\n<expected>429 with that body; 90 rows; then 204 and 91 rows for the other address</expected>\n<wrong_implementation>No limiter on the route reads 204 at :148. Inserting before the limit check reads 91 rows at :150. A global, not per-address, limit, or a stopped server, reads 429 or an error at :151.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Each negative assertion has a positive control: :137 is armed by :138-:139, and :150 is armed by :149 and :151-:152. The GET test (:158-:159) is absence-only, but it claims no clause and is labelled a regression line. Deleting the route makes the C1 and C2 tests fail.\n2. No. Expected values are literals from the spec (204, 429 and the error body, field values sent in the request) or the server's clock window. No assertion repeats production's transformation. Deleting the route branch in `_serve_post` turns :121, :134 and :148 red.\n3. No. Header handling is read across sent, empty and absent headers, both event types and three Content-Types. Refusal is read across 12 bodies.\n4. No doubles. The test uses a real ClientBackendServer over a socket with a real sqlite database.\n5. Yes. Imports and names are unchanged from the run that collected 19 tests (18 failed, 1 passed). This edit only touched docstring text on line 5.\n6. Yes. Header absence, empty headers and urllib's Content-Type defaulting were observed in the probe run. Today's 404 behaviour was observed too. The only edit this round is prose.\n7. Yes. Only the docstring changed. The earlier run showed each failure stopping at its first status assertion with a 404, because the route is missing, while the GET regression test passes.\nNothing needed a rewrite. The only edit was narrowing the docstring for D15b. The probe file tests/tmp/test_probe_18_p3.py is still in the tree, because I have no delete tool, and needs removing.\n</answers>",
    "self_check:tests/tmp/test_18_about_outbound_click_tracking_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:121 \u2014 `(status, body) == (204, b\"\")` for each of the 5 ACCEPTED cases: outbound_click and page_view, sent as application/json, text/plain;charset=UTF-8 and application/x-www-form-urlencoded</assertion>\n<expected>(204, b'') for every case. The probe saw `respond_bytes(self, 204, b\"\")` return exactly (204, b'') on /api/profile/delete. Today the run reads (404, b'{\\n  \"error\": \"Not found\"\\n}') at line 121, in all 5 cases.</expected>\n<wrong_implementation>A handler that parses the body only when Content-Type is application/json (the browser sendBeacon text/plain and form posts get 400 or 415), or a handler that answers 200 with a JSON echo. Either way at least one parametrized case reads (400, \u2026), (415, \u2026) or (200, b'{\u2026}').</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:123 \u2014 `len(rows) == 1` after a single accepted POST</assertion>\n<expected>1. The 5 ACCEPTED cases each run against a fresh client_backend database, so before the request the table is empty.</expected>\n<wrong_implementation>The handler never calls `insert_analytics_event` (it validates and returns 204), so the length is 0. Or it inserts and also retries or double-writes, so the length is 2.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:125 \u2014 `(type, track_id, href, page_path, user_agent, referer) == expected` across five header shapes: UA and Referer sent, both sent empty, both absent, UA only</assertion>\n<expected>The fields as sent. track_id and href are None on a page_view. user_agent and referer equal 'Mozilla/5.0 analytics-test' and 'https://example.org/about' when sent, and None when sent empty or absent. Observed by probe: this header-free opener delivers no User-Agent or Referer at all (the server's headers.get gives None), an empty header arrives as '', and a '' written through insert_analytics_event reads back as '' and not None.</expected>\n<wrong_implementation>A handler storing `self.headers.get(\"User-Agent\")` without mapping '' to None reads ('outbound_click', \u2026, '', '') in the click-text-plain-headers-empty case. A handler taking user_agent and referer from the JSON body (which carries neither) reads None in the headers-sent cases. A handler storing urllib's default UA would be caught too, but this opener sends none.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:126-127 \u2014 created_at is an int with now_ms() before the request \u2264 created_at \u2264 now_ms() after it, and created_at != CLIENT_TIMESTAMP (1)</assertion>\n<expected>An int millisecond stamp inside the request window. The probe saw an int created_at round-trip through insert_analytics_event as int.</expected>\n<wrong_implementation>A handler stamping created_at from the body's `timestamp` stores 1, which is outside the window and equal to CLIENT_TIMESTAMP. One stamping in seconds (time.time()) stores a value about 1000\u00d7 below `before`. One storing a float or ISO string fails the isinstance check.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:134,136,137 \u2014 for each of the 12 REJECTED bodies: status == 400, the body is JSON with a non-empty string `error`, and `_rows(...) == []`. Lines 138-139 are positive controls with no row: a valid VIEW posted afterwards gets (204, b'') and the table then holds 1 row.</assertion>\n<expected>400, a non-empty string error, and []. Today the run reads 404 at line 134 in all 12 cases (\"assert 404 == 400\").</expected>\n<wrong_implementation>A handler that inserts before validating, or catches the validation failure after the insert and still answers 400, reads [(row\u2026)] at line 137. A handler missing one check (e.g. accepting `timestamp: true` since bool is an int, accepting a mailto: href, accepting a page_view with a track_id, or letting a lone-surrogate href through) reads 204 at line 134 for that case. A handler that 400s with an empty body fails json.loads at line 135.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:148,150 \u2014 under the production limiter (RATE_LIMIT_MAX_REQUESTS 90 per 60 s), the 91st POST from 203.0.113.18 reads (429, {\"error\": \"Rate limit exceeded\"}) and the table holds 90 rows. Lines 149, 151 and 152 are controls with no row: all 90 earlier requests got 204, and 203.0.113.19 still gets (204, b'') and makes 91 rows.</assertion>\n<expected>(429, {'error': 'Rate limit exceeded'}) then 90. The probe observed, on /api/profile/blocks under the same limiter with X-Forwarded-For keying from 127.0.0.1: 90 requests passed, the 91st got (429, b'{\\n  \"error\": \"Rate limit exceeded\"\\n}'), and another address was not limited. Today the run reads (404, {'error': 'Not found'}) at line 148, because unknown paths are never limited (the probe's 92nd request to the event path was still 404).</expected>\n<wrong_implementation>A route registered without `_rate_limit_check` stores the 91st with 204, so line 148 reads (204, \u2026) and line 150 would read 91. A handler that inserts and then runs the limit check answers 429 but line 150 reads 91.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 no gap. C1 (either type, any Content-Type, 204, one row, server-sourced created_at, user_agent and referer) is carried at lines 121, 123, 125 and 126-127 over 5 cases: both types, all three Content-Types, and the UA/Referer headers sent, empty and absent. C2 (a 400 or a 429 adds no row) is carried at lines 134, 136 and 137 over 12 refused bodies, and at lines 148 and 150 for the limiter. The module and test docstrings were updated to the reordered tests below.\n2. Absence only \u2014 yes in the previous version, but only in effect: the controls ran before the refusal and were the lines that failed (see 9). Rewritten: every negative now comes before its positive control in the same test. The empty table at line 137 is armed by a valid POST on the same server storing a row (lines 138-139). The count of 90 at line 150 is armed by the 90 \u00d7 204 at line 149 and by another address still storing at lines 151-152.\n3. Echoed literal \u2014 no. The expected tuples are request inputs compared with what the server wrote to SQLite, read back over a separate connection. Production lines whose deletion turns the test red: the handler's insert_analytics_event call (lines 123 and 125 go red), its now_ms() stamp (126-127), its ''\u2192None header mapping (125, empty-headers case), the validator's checks (134), and its `_rate_limit_check` call (148).\n4. One value \u2014 no. Accepted: 5 inputs over both types and 3 Content-Types. user_agent and referer are each read set, empty and absent. Refused: 12 bodies. created_at is pinned to an independent clock window plus an independent client value, not to a sibling.\n5. The double \u2014 no. The server is the real ClientBackendServer and handler on a socket, with a real SQLite file and the production RateLimiter constants. CLOSED_ENGINE is a closed port for the Engine, a layer this route never calls, and the conftest fixture uses it the same way.\n6. It collects \u2014 yes. The run printed \"collected 19 items\" (5 + 12 + 1 + 1, matching what I wrote), and all imports bind (conftest exports CLOSED_ENGINE, RateLimiter, client_backend, client_server and ensure_user_schema; lib.time_utils.now_ms). The handed-in collect-only summary said \"no tests\" with exit 0, but the real run collected 19.\n7. Observed, not predicted \u2014 I wrote a probe (tests/tmp/probe_18_phase3_seams.py, run with -s) through routes and helpers that exist today. It printed: `PROBE headers: [(None, None, 'application/json'), ('', '', 'text/plain;charset=UTF-8'), ('UA', 'https://r/', 'application/json')]`, `PROBE 90 statuses: [401] 90`, `PROBE 91st: (429, b'{\\n  \"error\": \"Rate limit exceeded\"\\n}')`, `PROBE other address: 401`, `PROBE unknown path 92nd: (404, b'{\\n  \"error\": \"Not found\"\\n}')`, `PROBE delete: (204, b'')`, `PROBE row: [('page_view', None, None, '/about.html', 1234567890123, None, '')]`. Every premise the test builds on is therefore observed: the opener sends no UA or Referer, an empty header arrives as '', the 429 body is exact and keyed per address, the empty 204 body, and int/None round-trips. Only one thing could not be observed: the new route's own 204 and 400 output, because the route does not exist yet. That is the phase's claim, and implementing the phase is what would confirm it. The probe's content has been emptied, but the file itself (`tests/tmp/probe_18_phase3_seams.py`) is still there, because I have no tool to delete it; it should be removed.\n8. Red, not green \u2014 yes, red. ValidateTests: \"18 failed, 1 passed\", [exit status 1]. The one pass is the GET regression line (404 Not found), which is true already and carries no clause.\n9. Red for the right reason \u2014 the first run, no: the 400 and 429 tests failed on CONTROL assertions. Line 133, `assert _send(... _body(VIEW) ...) == (204, b\"\")` (# C1: control), failed with (404, \u2026) != (204, b''). Line 147, the 90 \u00d7 204 control, failed with [404, 404, \u2026] != [204, \u2026]. So the assertions they are judged on never ran. Rewritten so the refusal is sent and judged first. Re-run, [exit status 1], 18 failed, 1 passed, and every failure is on an assertion the test is judged on, all on 404 from the route not existing. Line 121: `assert (404, b'{\\n  ...ot found\"\\n}') == (204, b'')` \u00d7 5. Line 134: `assert 404 == 400` \u00d7 12. Line 148: `AssertionError: assert (404, {'error': 'Not found'}) == (429, {'error...it exceeded'})`. There is no import, typo, path or harness failure: the server served the passing GET test, the table exists (users_store.py:67), and the probe drove the same server builder.\n10. Observed expected output \u2014 the run contradicts no row. The run's actuals are all the 404 \"Not found\" of the unrouted path, which is exactly the unimplemented phase. Each row's expected value rests on what the probe observed for its seam (the 204 empty body, the 429 body and keying, header delivery, row types). The route's own 204 and 400 values are the phase's claim, still to be confirmed by implementing it, as stated in 7.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `client/backend/server.py`\n- `_serve_post` now has a `POST /api/analytics/event` route. Like the other write routes, it checks `_rate_limit_check(url.path)` first. That limiter allows 90 requests per address in 60 s, and the address comes from `X-Forwarded-For` behind a trusted proxy. A request over the limit gets 429 `{\"error\": \"Rate limit exceeded\"}` before the body is read. A GET of the path still falls through to the existing 404.\n- New `ClientBackendHandler._handle_analytics_event`, which works in four steps:\n  - It reads the body with the shared `read_json_body`. That function ignores Content-Type, so `application/json`, `text/plain;charset=UTF-8` and form-encoded `sendBeacon` bodies are all accepted.\n  - If the body fails to parse (invalid JSON, a non-object, or non-UTF-8, since `UnicodeDecodeError` is a `ValueError`), it answers 400 with the parse error. An empty body parses to `{}`, which the validator then refuses.\n  - It runs the existing `_validate_analytics_event`. A refused event gets 400 with that function's message, and no row is written.\n  - A valid event is stored as one row through `insert_analytics_event` inside a `with self.server.user_db:` transaction, and the answer is 204 with an empty body. The server sets `created_at = now_ms()`; the client `timestamp` is validated but never stored. `user_agent` and `referer` come from the request headers, and are NULL when the header is empty or missing.\n- `insert_analytics_event` was added to the `lib.users_store` import.\n\n### `tests/active/test_analytics_events.py`, `.un/skills/devsecops/config.json`\nNot changed. This step asked for production code only. The checkpoint gates from `tests/tmp/`, and `tests/active/test_analytics_events.py` does not exist in the worktree yet. That file and its `test_groups` entry belong to the promotion of the phase checkpoints, not to this implementation step.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_18_about_outbound_click_tracking_phase4.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"C1b\">\n<disposition>fixed</disposition>\n<what>The runner now clicks five targets: the untracked link, the Text-like node, a span inside `a[data-track-id=\"about_patreon\"]`, a second anchor `a[data-track-id=\"about_github\"]` with href `https://github.com/y`, and the patreon span a second time. :147 asserts exactly four sends to the event URL. :148 asserts the bodies are exactly `[page_view, patreon, github, patreon]` in that order. A module-level \"already sent\" flag, a once-only listener or a self-removing listener sends one outbound_click and fails at :147. De-duplication by `track_id` sends patreon and github but not the repeat, gives three sends and fails at :147. The probe observed both failures in all four modes.</what>\n</item>\n<item id=\"D5b\">\n<disposition>fixed</disposition>\n<what>The runner keeps an ordered `calls` log. The bound `sendBeacon` stub pushes \"beacon\" after its this-check and before it returns or throws, and `fetch` pushes \"fetch\". This log replaces the old `beaconCalls` counter. :153 asserts `report[\"calls\"] == TRANSPORTS[mode] * 4`: `[\"beacon\"]` for true, `[\"beacon\",\"fetch\"]` for false and throws, and `[\"fetch\"]` for missing. Beacon-before-fetch is now observed per event. The probe built a variant that issues fetch first and attempts the beacon afterwards; it fails :153 in false and throws. A detached `sendBeacon` also fails :153 in false and throws, so D5a carries here too. The module docstring now says \"in that order per event\".</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim CRITICAL 1 (whole-claim, C1 \"per tracked click\" proved by a single click): the runner now clicks a second tracked link (`about_github`) and then the first tracked link again. :147 asserts four sends and :148 asserts the exact `[page_view, patreon, github, patreon]` bodies. The probe observed a once-per-page flag and once-per-id de-duplication both failing at :147 in all modes. Because the count changed, the test is renamed `test_import_and_tracked_clicks_send_one_event_each_by_beacon_or_keepalive_fetch`, and its docstring and the module docstring now say four events, one per tracked click.\nShape CRITICAL 1 (single-value-pin on `track_id`/`href` at :140): a second tracked anchor with a different `data-track-id` (`about_github`) and a different href (`OTHER_HREF`) is clicked between two patreon clicks. :148 expects each outbound_click to carry its own link's id and href. The probe observed a module that sends a hard-coded `track_id: \"about_patreon\"` failing at :148 in all four modes.\nClaim RECOMMENDATION 1 (D5b, order never observed): taken. A new ordered `calls` log replaces `beaconCalls`, and :153 asserts the per-mode beacon-then-fetch sequence for each of the four events.\nClaim RECOMMENDATION 2 (empty `data-track-id`, anchor with no href): not taken. The plan's module sends an empty or malformed id as-is and leaves rejection to the server's validation, which phase 3 tests. The client has no specified behaviour at that edge for this test to pin.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:147: in every sendBeacon mode exactly four sends are made, all to `http://api.test/api/analytics/event`.</assertion>\n<expected>`[EVENT_URL] * 4`: one page_view plus three outbound_clicks for the three tracked clicks. The untracked link and the Text-like target send nothing.</expected>\n<wrong_implementation>A once-per-page sent flag or a self-removing listener gives two URLs. De-duplication by track_id gives three. `closest(\"a\")` gives five. `base + \"/api/...\"` gives `http://api.test//api/...`, and a URL from `location.origin` gives `http://page.test/...`. All of these were observed failing here.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:148: the decoded bodies equal exactly `[page_view, patreon, github, patreon]` as whole dicts.</assertion>\n<expected>`{type: page_view, page_path, timestamp: 1700000000123}`, then outbound_click bodies with `about_patreon` and `https://www.patreon.com/x`, then `about_github` and `https://github.com/y`, then `about_patreon` again. Every `page_path` is the mode's stubbed pathname (`/about` or `/about.html`). This was observed under the reference module.</expected>\n<wrong_implementation>A hard-coded `track_id: \"about_patreon\"` reads `about_patreon` for the github click. A hard-coded `page_path: \"/about\"` is wrong in the false and throws modes. Reading the target's own attributes without `closest` misses the span clicks.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:150 (mode true): every send is a beacon carrying an `application/json` Blob, and no fetch is recorded.</assertion>\n<expected>`[(\"beacon\", \"application/json\")] * 4`</expected>\n<wrong_implementation>Sending by fetch when the beacon succeeds, an untyped or string beacon body, or a detached `sendBeacon` (the stub throws Illegal invocation, so everything falls to fetch). The detached case was observed failing here.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:152 (modes false, missing, throws): every send is a fetch with POST, `keepalive: true` and `Content-Type: application/json`.</assertion>\n<expected>`[(\"fetch\", \"POST\", True, \"application/json\")] * 4`</expected>\n<wrong_implementation>Dropping the event when sendBeacon is missing, ignoring sendBeacon's false return, or letting its throw end the send all give fewer than four fetch entries. A fetch without keepalive or without the JSON header gives the wrong tuple.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:153: the ordered transport log equals `TRANSPORTS[mode] * 4`.</assertion>\n<expected>true gives `[\"beacon\"]*4`. false and throws give `[\"beacon\",\"fetch\"]*4`, observed under the reference module. missing gives `[\"fetch\"]*4`.</expected>\n<wrong_implementation>Fetch issued before the beacon attempt gives `fetch, beacon, ...`. A detached `sendBeacon` never reaches the push and gives `fetch` only. Both were observed failing here in false and throws.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:154-156: exactly one `click` listener is on document, no handler throws, and no unhandled rejection occurs.</assertion>\n<expected>`[\"click\"]`, `[]` and `[]`.</expected>\n<wrong_implementation>No `typeof closest` guard throws on the Text-like target, so errors is non-empty. A fetch with no `.catch` puts `TypeError: offline` in rejections. Both were observed last round. Several listeners, or a listener of another type, fail :154.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:169: the vite-built `dev-pages/about.template.html` has at least one `<script ... src=\"/assets/*.js\">`.</assertion>\n<expected>A non-empty list, e.g. `[\"/assets/about-<hash>.js\"]`. This was observed from a tmp copy with the reference module and template script.</expected>\n<wrong_implementation>A template edit that is missing or drops the script tag gives `[]`. That is the current tree, observed failing here.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:170: one of those script files contains `/api/analytics/event`.</assertion>\n<expected>True: the entry chunk the page names carries the route literal. This was observed in the tmp-copy build.</expected>\n<wrong_implementation>The template loads some other script (e.g. an unrelated page entry) that does not bundle the analytics module, so no listed asset contains the route.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every empty-list assertion (:155 errors, :156 rejections) sits beside the positive controls :147, :148 and :153. Those prove the module ran, both listeners fired and fetch was actually called. Deleting the module leaves esbuild unable to resolve it, so the fixture errors; observed on this run.\n2. No. Expected values are literals or env inputs fed to stubs, and the module has to read them back from the DOM (`track_id`, `href`, `pathname`). Deleting `link.getAttribute(\"data-track-id\")` turns :148 red. Deleting the beacon-first branch turns :150 and :153 red. `TRANSPORTS` is the test's own per-mode expectation and does not copy any production table.\n3. Before the edit, yes: `track_id`/`href` were read at one input only (shape CRITICAL), and the per-click count rested on one click. Rewritten: two tracked links with different ids and hrefs, plus a repeat click. `page_path` already varied by mode, and the transport varies across four modes.\n4. No. The stubs are browser and node globals (`navigator`, `document`, `location`, `fetch`, `Date.now`). `about-analytics.ts` and its `api-base` import are bundled for real.\n5. Yes. The probe imported the edited file and called the renamed test function. `OTHER_HREF` and `TRANSPORTS` are bound, and the runner's `calls` and `OTHER_HREF` env are wired through `_run`. ValidateTests collected 5 items (4 parametrised plus 1 build test), as written.\n6. Yes. The `calls` log shape, the four-body sequence and `prevented` with 5 entries were observed by running the reference module from the plan's draft under the edited RUNNER. ref false gave `calls: [\"beacon\",\"fetch\"]*4` and bodies page_view, patreon, github, patreon. The probe also observed once_per_page and once_per_id failing at :147, hardcoded_id at :148, fetch_then_beacon at :147 (true) and :153 (false, throws), and detached at :150 and :153.\n7. Yes. ValidateTests on the file after the edits: the 4 node cases ERROR at the fixture with esbuild `Could not resolve .../src/about-analytics.ts`, and the build test FAILs at :169 on `assert []` because the built About page has no script. The probe tests/tmp/probe_18_phase4.py was emptied to a docstring and still needs deleting, as does tests/tmp/test_probe_18_p4_selfcheck.py, also an emptied leftover. I have no delete tool.\n</answers>",
    "self_check:tests/tmp/test_18_about_outbound_click_tracking_phase4.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:139 \u2014 in every sendBeacon mode exactly two sends are made, both to `http://api.test/api/analytics/event`</assertion>\n<expected>`[\"http://api.test/api/analytics/event\", \"http://api.test/api/analytics/event\"]` in all four modes. The probe run of the planned module showed this, e.g. mode false: `'url': 'http://api.test/api/analytics/event'` on both sends.</expected>\n<wrong_implementation>Probe-observed. Concatenating `resolveClientApiBase() + \"/api/analytics/event\"` gives `http://api.test//api/...`. Building the URL on `window.location.origin` gives `http://page.test/...`. Using `target.matches` instead of `closest` misses the span inside the link and gives one send. Using `closest(\"a\")` also counts the untracked link and gives three. Each of these is red at line 139 in all four modes.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:140 \u2014 the bodies are exactly `{type: page_view, page_path, timestamp: NOW}`, then `{type: outbound_click, track_id: about_patreon, href: https://www.patreon.com/x, page_path, timestamp: NOW}`. `page_path` is the stubbed `location.pathname`: `/about` in modes true/missing, `/about.html` in false/throws.</assertion>\n<expected>Probe run, mode false: `{\"type\":\"page_view\",\"page_path\":\"/about.html\",\"timestamp\":1700000000123}` then `{\"type\":\"outbound_click\",\"track_id\":\"about_patreon\",\"href\":\"https://www.patreon.com/x\",\"page_path\":\"/about.html\",\"timestamp\":1700000000123}`.</expected>\n<wrong_implementation>Probe-observed: hardcoding `page_path: \"/about\"` instead of reading `location.pathname` is red at line 140 in modes false and throws. Two other cases reach this line only if the send count is right: a body with an extra key such as `ip`, or missing `timestamp`/`href`. Either fails the exact dict equality.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:142 \u2014 mode true: both sends are beacons carrying an `application/json` Blob, and fetch is never called</assertion>\n<expected>`[(\"beacon\", \"application/json\"), (\"beacon\", \"application/json\")]` (the reference passed in mode true).</expected>\n<wrong_implementation>Probe-observed: calling `sendBeacon` detached from `navigator` throws \"Illegal invocation\" in the stub, as browsers do, and falls through to fetch. The observable reads `[('fetch', None), ('fetch', None)]`, red at line 142. Sending a string body instead of a typed Blob would give a `blobType` of `None`.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:144 \u2014 modes false, missing and throws: both sends go by fetch with POST, `keepalive: true` and `Content-Type: application/json`</assertion>\n<expected>`[(\"fetch\", \"POST\", True, \"application/json\")] * 2`. Probe run, mode false: `'method': 'POST', 'keepalive': True, 'contentType': 'application/json'`.</expected>\n<wrong_implementation>Probe-observed: leaving out `keepalive` gives `False`, and leaving out the header gives `contentType` of `None`. Both are red at line 144 in false, missing and throws. Not wrapping the `sendBeacon` call in try lets the throw reach the outer catch, so in mode throws no fetch is made and line 139 goes red first.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:145 \u2014 the bound `navigator.sendBeacon` is called once per event (2) whenever it exists, and 0 times when it is missing</assertion>\n<expected>2 in modes true/false/throws and 0 in mode missing. Probe run, mode false: `'beaconCalls': 2`.</expected>\n<wrong_implementation>Probe-observed: a detached `sendBeacon` call reads 0, red at line 145 in false and throws. Going straight to fetch without trying the beacon would also read 0.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:146 \u2014 exactly one `click` listener is registered on `document`</assertion>\n<expected>`[\"click\"]` (probe run: `'listeners': ['click']`).</expected>\n<wrong_implementation>Registering a listener per link or adding a second document listener (e.g. `auxclick`) gives a list other than `[\"click\"]`. Registering on `window` instead of `document` gives `[]`, and then lines 139/140 also show only the page_view. Not separately run as a mutant; the exact list makes each of these red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:147 \u2014 no click handler throws for the untracked link, the Text-like target or the tracked click</assertion>\n<expected>`[]`. The tracked click's send at line 140 is the positive control showing the handler ran.</expected>\n<wrong_implementation>Probe-observed: dropping the `typeof target.closest === \"function\"` guard throws `TypeError: ... is not a function` on the Text-like target. Red at line 147 in all four modes.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:148 \u2014 zero unhandled rejections, although the stubbed fetch always rejects</assertion>\n<expected>`[]`. Line 144 is the positive control: it shows a rejecting fetch was actually called in modes false, missing and throws.</expected>\n<wrong_implementation>Probe-observed: dropping the `.catch(() => undefined)` on the fetch promise gives `['TypeError: offline', ...]`. Red at line 148 in false, missing and throws.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:161 \u2014 the built `dev-pages/about.template.html` loads at least one `/assets/*.js` script</assertion>\n<expected>Observed in a probe vite build of a copied frontend with the planned script tag and module added: `<script type=\"module\" crossorigin src=\"/assets/about-BGG45oE3.js\"></script>` is matched, giving `['/assets/about-BGG45oE3.js']`.</expected>\n<wrong_implementation>Template left without the `<script type=\"module\" src=\"/src/about-analytics.ts\">` tag. The built page has only the CSS link, so `scripts == []`. This is what the checkpoint run showed against the current tree, red at line 161.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:162 \u2014 one of those script files contains `/api/analytics/event`</assertion>\n<expected>True. In the probe build, `/assets/about-*.js` contained `new URL(\"/api/analytics/event\",i())`, with api-base split into a `modulepreload` chunk.</expected>\n<wrong_implementation>A template script pointing at some other entry (e.g. the videos page module), or a module that never builds the event route, gives a bundled script without the literal: `any(...)` is False.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. C1's parts are each carried. Exactly two sends to the event URL: line 139. Page_view then outbound_click, exact bodies, untracked and Text-like targets sending nothing: 140. Beacon only when it returns true: 142. Keepalive JSON POST fallback for false/missing/throws: 144. Bound beacon tried first: 145. One document click listener: 146. No throw: 147. No unhandled rejection: 148. C2: lines 161-162. The docstring's no-preventDefault line, 149, is marked as a regression line, not a clause.\n2. Absence only: no. Lines 147/148/149 are negative, but lines 139/140 show the handlers ran and the tracked click sent, and line 144 shows a rejecting fetch was really called in the modes where 148 can bite. The probe confirmed that each negative line goes red under its mutant (missing guard \u2192 147, missing `.catch` \u2192 148).\n3. Echoed literal: no. EVENT_URL is a literal that differs from what concatenation or the page origin would produce. Deleting the production `new URL(\"/api/analytics/event\", resolveClientApiBase())` turns line 139 red. Deleting the `.catch` turns 148 red, deleting `keepalive: true` turns 144 red, and deleting the `closest` guard turns 147 red, all seen in the probe.\n4. One value: yes, so I rewrote. `page_path` was read at only one pathname, `/about`, so a module hardcoding `page_path: \"/about\"` passed. The test now sets the stubbed `location.pathname` per mode from PAGE_PATHS: `/about` for true/missing and `/about.html` for false/throws. Both are paths the About page is served at. The probe showed the hardcoded-path mutant red at line 140 in false and throws. The API base and page origin are separate on purpose, so URL construction is not pinned against a sibling value from the same source.\n5. The double: no. The stubs are browser globals (navigator, fetch, document, location, window) and the clock, all system boundaries. The project's `src/data/api-base.ts` is bundled for real, and C2 runs the real vite build.\n6. It collects: yes. The run printed `collected 5 items` (4 parametrized modes plus 1 vite test), which matches what I wrote. It imports only json, os, re, subprocess, pathlib and pytest. The `runner` fixture and `_run` arguments exist.\n7. Observed, not predicted: before this turn, no. Nothing in the RUNNER harness had been run: the only earlier probe file was empty, and the C1 test errors at setup before it reaches the runner. Now yes. I wrote the probe `tests/tmp/test_probe_18_p4_selfcheck.py`. It bundled the plan's design module with the same esbuild flags (importing the real api-base.ts), ran the checkpoint's RUNNER and test function, and passed in all four modes. Ten mutants each went red at the line given in the rows. It also ran a vite build of a copied frontend with the planned script tag. That showed `<script type=\"module\" crossorigin src=\"/assets/about-BGG45oE3.js\">`, which the test's regex matches, and the about chunk containing `/api/analytics/event`. The probe is emptied now, with a delete-me docstring.\n8. Red, not green: yes, it is red. ValidateTests exit status 1, `1 failed, 4 error`: FAILED test_built_about_page_loads_a_bundled_asset_with_the_event_route, and ERROR for test_import_and_tracked_click_send_two_events_by_beacon_or_keepalive_fetch[true/false/missing/throws].\n9. Red for the right reason: yes. The four C1 cases stop at the bundling step, line 116 `assert result.returncode == 0, result.stderr`, with `\u2718 [ERROR] Could not resolve \".../client/frontend/src/about-analytics.ts\"`. That file is the phase's own NEW deliverable (plan Phase 4 Files touched: `client/frontend/src/about-analytics.ts (NEW)`), so the missing path is the phase not being built, not a typo. The probe shows the same harness reaches and passes every judging assertion once a module with the planned design exists. C2 got past its controls: line 158 vite returncode 0, and line 159 read the built about.template.html. It then failed at the judging line 161 `assert scripts, page` with `assert []`. The built page has only `<link rel=\"stylesheet\" crossorigin href=\"/assets/videos-udwJkO0e.css\">` and no script, because the template does not load the module yet.\n10. Observed expected output: yes. Every `expected` value is from a run. C1 values come from the probe's report against the reference module, e.g. mode false: urls `http://api.test/api/analytics/event`, bodies with `page_path \"/about.html\"` and `timestamp 1700000000123`, `beaconCalls 2`, `listeners ['click']`, `errors []`, `rejections []`. The C2 tag shape and literal come from the probe vite build. The checkpoint run itself confirms the current red values: `assert []` at line 161, and the esbuild resolve failure at 116.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:4": "<changes>\n### `client/frontend/src/about-analytics.ts` (NEW)\n- New module, written from the plan's settled draft. It has no exports and does its work when imported.\n- **Page view.** On import it sends one `{type: \"page_view\", page_path: window.location.pathname, timestamp: Date.now()}`.\n- **Click listener.** On import it also adds one delegated `click` listener on `document`. The listener:\n  - ignores a target that has no `closest`, such as a Text node or the document;\n  - resolves `target.closest(\"a[data-track-id]\")`;\n  - for a match, sends `{type: \"outbound_click\", track_id: <data-track-id attribute>, href: link.href, page_path: window.location.pathname, timestamp: Date.now()}`;\n  - sends nothing when the link's `href` is not a string, as on an SVG `<a>`;\n  - never calls `preventDefault`.\n- **URL.** `sendAnalyticsEvent` builds the URL as `new URL(\"/api/analytics/event\", resolveClientApiBase())`.\n  - It passes no argument, so `?api=` is never read.\n  - Using `new URL` means a base that ends in `/` does not produce `//api`.\n- **Transport.** It first tries `navigator.sendBeacon(url, Blob[JSON], type application/json)`, called on `navigator` itself so the browser does not throw \"Illegal invocation\".\n  - If `sendBeacon` is missing, returns false or throws, it sends `fetch(url, {method: \"POST\", body, headers: {\"Content-Type\": \"application/json\"}, keepalive: true})` instead.\n  - The fetch has a no-op `.catch`, and an outer try/catch covers anything thrown synchronously, so nothing reaches the visitor as an error or an unhandled rejection.\n\n### `client/frontend/dev-pages/about.template.html` (EDITED)\n- Added `<script type=\"module\" src=\"/src/about-analytics.ts\"></script>` before `</body>`. Like `videos.html`, it uses a root-absolute path, so vite bundles it into an `/assets/*.js` entry for the built About page. No About URL or dev-pages file name changed.\n\n### `tests/active/test_analytics_events.py` (EDITED in the files list)\n- Not changed. The file still does not exist in the worktree; Phases 1\u20133 recorded the same thing.\n- This step asks for production code only, and the checkpoint `tests/tmp/test_18_about_outbound_click_tracking_phase4.py` gates the phase.\n- The durable file and its `.un/skills/devsecops/config.json` `test_groups` entry are still to be written or promoted from the phase checkpoints.\n\nI did not run the checkpoint; the workflow's run is the one that counts.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nclient/backend/server.py: `_handle_analytics_event` now binds `conn = self.server.user_db` once and uses it for both the transaction and the `insert_analytics_event` call, the same way `_handle_likes_import` and `_store_reaction` do. Behaviour is unchanged.\nclient/backend/server.py: replaced the placeholder docstring summary of `_validate_analytics_event` (\"Handle validate analytics event.\") with one saying what it does: it checks a decoded body against the settled rules, never raises, and ignores unknown keys. The `:returns:` line is unchanged.\n</refactors>\n\n<left_out>\nI left the per-route rate-limit block in `_serve_post` (check, then 429, then return) as it is. The analytics route copies the pattern every other route already uses, and pulling it into a helper would change code that existed before this build.\nI left users_store.py, about-analytics.ts and about.template.html alone. They already match the plan's settled code and the style of the files they sit in, and I found nothing that could be refactored without changing behaviour.\nI did not write the durable test `tests/active/test_analytics_events.py` or add its `test_groups` entry to `.un/skills/devsecops/config.json`. That is not a refactor. All four phases list the file (NEW, then EDITED), and Phase 3 lists config.json, but it still does not exist: each phase gated only on its checkpoint in `tests/tmp/test_18_about_outbound_click_tracking_phase{1..4}.py`. The checkpoints still need promoting, or the analytics code is left with no durable test or test group.\nI deleted none of the probe files in `tests/tmp/` (`probe_18_*`, `test_probe_18_*`). They are outside the files this step names; they should go when the checkpoints are promoted.\nI did not run anything. The two edits only touch a local variable and a docstring, so this step's run of the Phase 2/3 checkpoints is what confirms them.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nAll four phases' code already matched the plan and the style of the surrounding files, so the pass made just two behaviour-neutral tidy-ups in server.py. The real gap is the durable test `tests/active/test_analytics_events.py` and its `test_groups` entry: neither exists yet, and promoting the checkpoints into them is still to do.\n</observation>",
    "step_8_triage:0": "<failures>\n### tests.active.test_frontend_blocks::test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches\n\n**What happened.** The test failed during setup and never reached the frontend module or the Client backend. `_seed_and_targets` (line 108) calls the conftest helper `upnext_pool`. That helper posts straight to the **Engine** (`engine.request`, conftest.py:263) to list the seed's `/recommendations` pool. One of those listing requests, sent with a long `exclude` list, got 500 `{\"error\": \"Recommendations request failed\"}`.\n\n**The test is sound.** It expects a seeded up-next listing on the Engine to return 200, which is a fair expectation. Nothing it relies on was changed by this build, and it does not conflict with any clause. It was re-selected only because `client/backend/server.py` changed. I ran a replay probe (`tests/tmp/probe_18_engine_log.py`) that starts a fresh session Engine through the conftest fixtures and calls the test's own `_seed_and_targets` four times, then the whole test body once:\n- All 32 Engine requests returned 200.\n- The full test passed.\n- The Engine log had 0 ERROR or traceback lines.\n\nThe test is not retired and was not edited.\n\n**This build did not cause it.** The four phases changed only Client-side files: `users_store.py` (the new `analytics_events` table and its insert), `client/backend/server.py` (the validator and the `POST /api/analytics/event` route), `about-analytics.ts` and the About template. The failing request goes from the test process directly to the Engine process, whose code (`engine/`) this build did not touch. None of these files is on that request's path. No Engine file references analytics or `users_store`.\n\n**What I observed.**\n- **Only one path gives this body.** It is the fixed body from `_handle_similar`'s generic exception handler (`SIMILAR_FAILED_MESSAGE`, engine/server/api/handlers/similar.py). Per `engine/server/README.md:31` and the 19-11 and 22-36 triage records, a request that runs past the Engine's 5 s statement deadline also gets this 500, not the 503 `Query time limit exceeded`.\n- **On an idle machine the late listing pages are already slow.** In isolation, the requests carrying 362\u2013433 `exclude` entries took 0.73\u20132.50 s each. The ones carrying 0\u2013266 entries took 0.01\u20130.37 s. The slowest is half the 5 s budget with no other load.\n- **The suite run was heavily loaded.** It ran 9 lanes in parallel. `test_dislikes` took 117.6 s and `test_blocks` 72.9 s, and each starts and drives its own Engine.\n\n**Not confirmed.** The failing lane's Engine log (`/tmp/pytest-of-enduser/pytest-8531/engine0/engine.log`) was already gone when the probe looked for it, so I could not see the actual exception. The most likely cause is a statement-deadline overrun on a late listing page under suite load (`sqlite3.OperationalError: interrupted`). That is an inference from the timings and the earlier records, not something I observed. Any other load-dependent sqlite error caught by the same generic handler would give the same 500. To confirm it, read the failing lane's `engine0/engine.log` on the next red run before pytest's basetemp retention removes it, and check whether the `server error` record ends in `OperationalError: interrupted`.\n\n**Conclusion.** This is a load-dependent failure of a correctly written test. It is the third time this has happened (after builds 19-11 and 22-36), and it is not a regression from the analytics work. No implementation change was made.\n</failures>\n\n<checkpoint_gaps>\nnone. I found no fault from this build for a checkpoint to have missed. The failing request runs only through the Engine, and no phase touched it: Phases 1\u20133 changed the Client backend's `users.db` schema and a new Client route, and Phase 4 changed the About page's frontend. Two older problems are behind it, and no phase of this build was asked to change either. The Engine answers a statement-deadline overrun with a generic 500 instead of a 503. The conftest pool-listing helper sends requests with 400+ `exclude` entries, which take about 2.5 s at idle against the 5 s budget.\n</checkpoint_gaps>\n\n<correction>\n- **Production code and tests:** No production code changed. No test was edited, weakened or retired, and no checkpoint was touched.\n- **Durable tests checked:** I searched `tests/active` for anything that conflicts with the confirmed requirements: the `analytics_events` table, `POST /api/analytics/event` or the About template's new script. Nothing there references them. The `sqlite_master` table and index checks found only look at Engine databases, not `users.db`, so no durable test is retired.\n- **Diagnosis:** I found that the cause was the Engine, not this build, by replaying the failing setup in isolation with a throwaway probe (`tests/tmp/probe_18_engine_log.py`). I can't delete files, so that probe is now a one-line spent stub with no tests; it should be deleted.\n- **Recommended next step:** Re-run `validate_tests.py --compare` for `test_frontend_blocks.py`. If it is red again, read that lane's `engine0/engine.log` before its basetemp is removed. This has now happened in three builds. I recommend an issue for the operator (in `docs/project/issues/`, not filed by me because it is outside this step's files) covering two things: the Engine's `_handle_similar` turns a statement-deadline interrupt into a generic 500 instead of the 503 `Query time limit exceeded`, and the conftest `upnext_pool` listing sends requests with 400+ `exclude` entries that take about 2.5 s even at idle.\n</correction>",
    "step_9_triage": "<docs>\n<doc path=\"DEPLOYMENT.md\" update=\"yes\">\n- **Line 258** (\"Follow an About visit\" caveat) is now false. It says counting human visits needs a client-side pageview beacon, at `docs/project/issues/18-about-outbound-click-tracking.md`. The beacon now exists: `client/frontend/src/about-analytics.ts` sends a `page_view` on every About load to `POST /api/analytics/event`. Rewrite it to say the beacon exists and that its counts are queried in the new subsection. Point the issue path at `docs/project/issues/archive/18-about-outbound-click-tracking.md`.\n- **Line 241** (\"The page's own API calls are new requests\") is now incomplete. The template page made no API calls before. Every About view now produces a `POST /api/analytics/event` `request.start` from the visitor's address, plus one per tracked click. Add one sentence on this.\n- **Lines 404-406** (\"There is no browser-facing event publish route\") need a clarification. `POST /api/analytics/event` is a browser-facing, keyless Client route that stores rows in users.db `analytics_events` and publishes nothing to the Engine. The keyed-route list at line 410 is unchanged.\n- **New Triage subsection \"Count About analytics events\"**, between \"Follow an About visit\" and \"Follow one request\". It holds:\n  - the `sqlite3 -readonly <root>/client/backend/db/users.db` invocation;\n  - fenced `sql` blocks for total and daily (UTC, from `created_at` ms) `outbound_click` counts per `track_id`;\n  - total and daily `page_view` counts, optionally per `page_path`;\n  - the `user_agent` bot-filter variants.\n- **Caveats for the new subsection:**\n  - counts are forgeable within 90/min per address;\n  - retention is unbounded;\n  - the UA filter is a heuristic;\n  - Referer is often reduced;\n  - middle-click and context-menu opens are not counted;\n  - non-http(s) tracked links are rejected with 400;\n  - a shared or misresolved client address (ADR-0002) silently undercounts;\n  - dev cross-origin beacons may be lost (ADR-0004);\n  - the inherited shared-`user_db`-connection race.\n- **Line 70.** The users.db description should say it now holds `analytics_events`, which grows unpruned and matters for backups.\n- **Line 523.** The \"every visitor shares one bucket\" note should cross-reference the analytics undercount.\n- **Verify section.** Optionally add a POST check, noting that it writes a real row.\n- **Line 465.** The rat-tail cites `tests/active/test_static_page_visit_logs.py`, which does not exist. Flag it to the operator; do not silently rewrite it.\n</doc>\n<doc path=\"client/README.md\" update=\"yes\">\n- **Backend Responsibilities.** Lists the Client backend's routes but has no `POST /api/analytics/event`. Add a bullet covering:\n  - the `outbound_click` and `page_view` types and their fields;\n  - 204 on success, 400 on a validation failure, 429 over the rate limit;\n  - Content-Type is ignored;\n  - no key is needed;\n  - rows go to users.db `analytics_events` with a server-stamped `created_at`, plus User-Agent and Referer;\n  - nothing IP-derived is stored;\n  - nothing is published to the Engine.\n- **Boundary Contract (line 41).** Its write/profile route list must gain the route.\n- **Optional.**\n  - Widen the \"write/profile API service\" wording at lines 6 and 10.\n  - Add a dev cross-origin beacon note beside `CLIENT_CORS_ORIGINS` at line 71.\n</doc>\n<doc path=\"client/frontend/README.md\" update=\"yes\">\n- **\"Local About Overrides\".** Says nothing about analytics, so an override built from it sends no events. Document what an override adds:\n  - `<script type=\"module\" src=\"/src/about-analytics.ts\"></script>`, root-absolute;\n  - `data-track-id=\"<id matching [a-z0-9_]{1,64}>\"` on each outbound link to count;\n  - only http(s) links count;\n  - middle-click and context-menu opens are not counted;\n  - an override without the tag sends nothing.\n- **\"What it does\".** Needs a bullet for the About `page_view`/`outbound_click` beacons, sent through the Client API base with sendBeacon and a keepalive fetch fallback.\n- **Line 24 (`npm run dev`).** Beacons are cross-origin there. They need `CLIENT_CORS_ORIGINS` and may be lost.\n</doc>\n<doc path=\"README.md\" update=\"yes\">\n- **Line 50.** The boundary table lists the Client backend's browser-facing write/profile routes. Add `/api/analytics/event`, or a row for Client analytics events.\n- **Line 24.** \"`engine/`: read/analytics workspace\" refers to Engine analytics. It stays true and needs no change.\n</doc>\n<doc path=\"CONTEXT.md\" update=\"yes\">\n- The glossary has no **Analytics event** term. Add one entry in the `- **Term** \u2014 ...` style, near **Interaction event**. An analytics event:\n  - is an anonymous browser event of type `outbound_click` or `page_view`;\n  - is owned by the Client backend, stored in users.db `analytics_events`, and never sent to the Engine;\n  - has nothing derived from the client address stored;\n  - is distinct from an **Interaction event**, which feeds the Engine.\n- **Client address** (line 9) stays true.\n</doc>\n<doc path=\"docs/project/issues/18-about-outbound-click-tracking.md\" update=\"yes\">\n- **Status.** The issue is delivered. Set `Status: enhancement, complete`.\n- **Delivery comment.** Append one in the style of archive/21:31, naming plan `docs/project/plans/23-18-about-outbound-click-tracking.md` and the departures from the issue text:\n  - the route is `POST /api/analytics/event`, not `/outbound-click`;\n  - the table is `analytics_events`, not `outbound_click_events`;\n  - validation is by shape, not an allowlist;\n  - there is no `ip_hash`;\n  - the template and the override docs changed, not `client/frontend/about.html`.\n- **Follow-ups for the comment to name:**\n  - the shared `user_db` connection race;\n  - the missing `tests/active/test_static_page_visit_logs.py` and its config.json group;\n  - the missing durable `tests/active/test_analytics_events.py`, if the harvest has not promoted it by then.\n- **Prod note.** State that prod sends beacons only after the next `scripts/sync.sh` rebuilds `dist/`.\n- **Move.** Move the file to `docs/project/issues/archive/`, and update the DEPLOYMENT.md:258 link in the same change.\n</doc>\n<doc path=\"docs/project/issues/plan.md\" update=\"yes\">\n- **Line 42 (P5 row).** Says \"19, 20 and 21 are delivered, and 18 remains\", which is now false. Mark all four delivered.\n- **Line 98 (lane 5c).** Mark 18 delivered, with the plan path `docs/project/plans/23-18-about-outbound-click-tracking.md`, or its `archive/` path if the plan moves.\n</doc>\n<doc path=\".un/skills/devsecops/config.json\" update=\"no\">\nNot a prose document, and the harvest turn owns it: it rewrites the group map when it promotes the phase checkpoints. The durable `tests/active/test_analytics_events.py` does not exist yet (every phase and the refactor pass record this), so there is no file to map a `test_groups` entry to. The new group belongs in the harvest, along with the note that the existing `test_static_page_visit_logs.py` group (lines 263-268) points at a missing file.\n</doc>\n<doc path=\"docs/project/plans/23-18-about-outbound-click-tracking.md\" update=\"no\">\nThe workflow renders this plan, so it is not hand-edited here. Its link to issue 18's current path is handled when the workflow archives the plan, per issue-tracker.md:29.\n</doc>\n<doc path=\"docs/project/issues/archive/21-static-page-visit-logs.md\" update=\"no\">\n- **Line 27.** Refers to 18 by slug only, and that stays correct.\n- **Line 31.** A dated delivery record of what issue 21 scoped out. It describes the beacon as the runbook's upgrade path, which was true at its delivery. It is history, not a current-state claim, and its slug reference still resolves.\n</doc>\n<doc path=\"docs/project/issues/21-static-page-visit-logs.md\" update=\"no\">\n- This is the stale non-archive duplicate. It mentions 18 by slug only (line 27), which stays correct.\n- Removing it is tracker hygiene outside this build's change. Mention it in the delivery notes.\n</doc>\n<doc path=\"engine/server/README.md\" update=\"no\">\nLines 4 and 18-19 say the Engine owns read/analytics APIs and no browser-facing write/profile routes. Both stay true: `/api/analytics/event` belongs to the Client backend, and \"analytics\" there means Engine read analytics.\n</doc>\n<doc path=\"docs/project/adr/0002-trusted-proxy-client-address.md\" update=\"no\">\nThe analytics route resolves the client address through the existing `_rate_limit_check` \u2192 `_get_client_ip` path, as the ADR decides. The only consequence (a misconfigured proxy now also undercounts analytics) is a caveat for DEPLOYMENT.md, not an amendment.\n</doc>\n<doc path=\"docs/project/adr/0004-cors-opt-in-by-origin.md\" update=\"no\">\nThe build adds no CORS headers, no credentials header and no `*`, so origin opt-in is unchanged. The possible loss of dev cross-origin beacons follows from this ADR and is documented as a caveat in DEPLOYMENT.md and client/frontend/README.md.\n</doc>\n<doc path=\"docs/project/adr/0005-raw-event-retention-keeps-ids.md\" update=\"no\">\n- Its scope is the Engine's `interaction_raw_events`.\n- `analytics_events` is a separate Client-side table of anonymous rows, kept unpruned by a settled requirement. It stores no `actor_id`, no caller payload and nothing from the client address, so the ADR's retention decision does not cover it and is not contradicted.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:DEPLOYMENT.md": "<changes>\nDEPLOYMENT.md: new Triage subsection \"Count About analytics events\" with ready-to-run sqlite3 queries and caveats; the About-visit caveat, users.db, section 5 and section 6 now account for `POST /api/analytics/event`.\n\n- **New Triage subsection \"Count About analytics events\"**, between \"Follow an About visit\" and \"Follow one request\".\n  - What it covers: what the beacon sends, what one `analytics_events` row holds, and that nothing derived from the client address is stored. It points to `client/README.md` for the request body and validation, and to `client/frontend/README.md` for what an override needs.\n  - The queries: the `sqlite3 -readonly <project>/client/backend/db/users.db` invocation, then fenced `sql` blocks for total and daily (UTC, `date(created_at / 1000, 'unixepoch')`) `outbound_click` counts per `track_id`, and total, daily, per-`page_path` and daily per-`page_path` `page_view` counts. A `user_agent` bot-filter variant follows, with a note that it can be added to any query.\n  - The caveats: counts can be forged at up to 90/60 s per address; retention is unbounded; the UA filter is a heuristic; Referer is often reduced; middle-click and context-menu opens are not counted; non-http(s) tracked links get a 400; a shared or misresolved address (ADR-0002) silently undercounts through 429s; dev cross-origin beacons need `CLIENT_CORS_ORIGINS` and may be lost (ADR-0004); and all requests share one `users.db` connection with no lock (checked: one `connect_db` connection on a `ThreadingHTTPServer`).\n- **\"Follow an About visit\".**\n  - The last caveat no longer says a beacon is needed. It says the page's beacon counts views that ran its JavaScript, points to the new subsection, and links `docs/project/issues/archive/18-about-outbound-click-tracking.md`.\n  - The \"own API calls\" paragraph adds that an About view sends one `POST /api/analytics/event` page view, plus one request per tracked click.\n- **Section 1, users.db:** it holds `analytics_events`, which nothing prunes; size backups for it.\n- **Section 5:** after the \"no browser-facing event publish route\" paragraph, a new paragraph says `POST /api/analytics/event` is browser-facing and keyless, stores rows in users.db, and publishes nothing to the Engine. The boundary-contract list is unchanged.\n- **Section 6:**\n  - The \"every visitor shares one bucket\" sentence now points to the analytics undercount.\n  - Verify gained a `curl --data \u2026 /api/analytics/event` check expecting 204. Its comment notes that it stores a real row with a `curl/` user agent, which the bot filter excludes.\n\n**For the operator:**\n- **Missing test file.** The rat-tail comment in the section 6 nginx block cites `tests/active/test_static_page_visit_logs.py`, and that file does not exist in the worktree (Glob finds nothing). I left it unchanged as instructed.\n- **Broken link until the move.** The new archive link only resolves once the issue-18 turn moves the file. Right now it is still at `docs/project/issues/18-about-outbound-click-tracking.md`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:client/README.md": "<changes>\nclient/README.md now covers `POST /api/analytics/event`: what it accepts and answers, where it stores events, and that it is a browser-facing Client route.\n\n- **Workspace intro (line 6).** The backend is now described as a \"write/profile and analytics API service that publishes interaction events to Engine\".\n- **Backend Responsibilities.** Added a top-level bullet after the profile route list. It covers:\n  - the body shapes of the two types, `outbound_click` and `page_view`, and the rule for each field;\n  - a `page_view` must not carry `track_id` or `href`, and unknown keys are ignored;\n  - the body is parsed as JSON whatever the Content-Type, and no key is needed;\n  - a valid event answers 204 and adds one row to `analytics_events` in `users.db`, with `created_at` from the server's clock and `User-Agent`/`Referer` each NULL when empty;\n  - the client `timestamp` is checked but not stored;\n  - nothing derived from the client address is stored, and nothing is published to the Engine;\n  - an invalid body answers 400 and stores nothing;\n  - over the shared 90-per-60-s limit it answers 429 before the body is read.\n  - The bullet points to **Analytics event** in `CONTEXT.md` and to \"Count About analytics events\" in `DEPLOYMENT.md` rather than repeating them.\n- **Boundary Contract.** Added `analytics: /api/analytics/event` to the browser-facing ownership list.\n- **`CLIENT_CORS_ORIGINS`.** Added one sentence: in the Vite dev setup the About page's analytics beacons are cross-origin too. It points to `client/frontend/README.md`, which carries the details.\n\nI checked these claims against the code: `server.py` (the `_serve_post` route, `_handle_analytics_event`, `_validate_analytics_event`, `_analytics_href_ok`, and the `RATE_LIMIT_*` constants) and `lib/http_utils.py` (`read_json_body`). Nothing was run.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:client/frontend/README.md": "<changes>\nAdded About analytics to `client/frontend/README.md`: what the beacon module does, the dev cross-origin caveat, and what a local override needs in order to send events.\n\n- **\"What it does\":** one new bullet.\n  - `src/about-analytics.ts` sends one `page_view` when the page loads, and one `outbound_click` for each click on an `a[data-track-id]` link.\n  - Events go to `POST /api/analytics/event` on the Client API base.\n  - It sends with `navigator.sendBeacon`, and falls back to a `keepalive` `fetch` when `sendBeacon` is missing, returns false or throws.\n  - A failed send never shows an error to the visitor, and a click is never stopped from navigating.\n  - What the route accepts and stores is pointed at `client/README.md`, not repeated here.\n- **\"Boundary Contract\":** one new bullet saying analytics events are also cross-origin under `npm run dev`.\n  - They reach the backend only when the page's origin is in `CLIENT_CORS_ORIGINS`.\n  - Even then the browser can drop them (pointer to ADR-0004), so dev counts are not reliable.\n- **\"Local About Overrides\":** two new bullets.\n  - The template's tag is `<script type=\"module\" src=\"/src/about-analytics.ts\"></script>`. An override sends events only if it has the same root-absolute tag; without it, it sends nothing. Vite bundles the tag because the override is the `about` build input.\n  - Links to count need `data-track-id` with an id that fully matches `[a-z0-9_]{1,64}`. Only `http` and `https` links are counted. Middle-click and context-menu opens fire no `click` event, so they are not counted.\n- **Checked against the code:**\n  - `about-analytics.ts`: send order, fallback conditions, silent failure, no `preventDefault`.\n  - The template's script tag at line 37.\n  - The `about` input in `vite.config.ts`.\n  - `resolveClientApiBase` in `api-base.ts`.\n  - That `docs/project/adr/0004-cors-opt-in-by-origin.md` exists.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:README.md": "<changes>\nI added a row for Client analytics events to the boundary contract table in `README.md`.\n\n- **New row** in \"Canonical Engine/Client boundary contract\", placed after the write/profile row:\n  - **Concern:** browser-facing analytics events, meaning `POST /api/analytics/event`, which carries the About page's page views and outbound clicks.\n  - **Owner:** the Client backend.\n  - **Contract:** only the Client backend exposes the route. Events are stored in the Client's `users.db` and never published to the Engine.\n  - **Forbidden coupling:** sending analytics events to Engine ingest or to Engine handlers.\n- **Pointer instead of a restatement:** the row sends readers to **Analytics event** in `CONTEXT.md` and doesn't repeat what event types, fields or storage columns exist.\n- **Checked against the code:** the route is at `server.py:502`. `_handle_analytics_event` (`server.py:1059\u20131078`) writes only through `insert_analytics_event` into `self.server.user_db` and makes no call to the Engine.\n- **Left as is:** the line 24 component entry (\"`engine/`: read/analytics workspace\") is about Engine analytics and is still true.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:CONTEXT.md": "<changes>\nAdded an **Analytics event** glossary entry to `CONTEXT.md`, directly after **Interaction event**.\n\n- **What it covers:** an analytics event is an anonymous About-page browser event, either a `page_view` or an `outbound_click` on a link with `data-track-id`. It is sent to the Client backend's `POST /api/analytics/event`. Each one is stored as a row in `users.db` `analytics_events` and is never sent to the Engine. Nothing derived from the client address is stored. It is distinct from an interaction event, which feeds the Engine.\n- **What it points to instead of repeating:** for querying the counts it points at `DEPLOYMENT.md`. Field-level validation rules are left to `client/README.md`.\n- **Checked against the code:** the `analytics_events` schema and `insert_analytics_event` in `client/backend/lib/users_store.py`, and the route in `_serve_post` at `client/backend/server.py:502`.\n- **Unchanged:** the **Client address** entry, which is still accurate.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/18-about-outbound-click-tracking.md": "<changes>\nIssue 18 is closed as delivered: its status is `enhancement, complete`, it has a delivery comment, and a copy now sits in `archive/`. The old file is still in place because I have no way to delete files.\n\n- **Where it is now:** the updated issue is at `docs/project/issues/archive/18-about-outbound-click-tracking.md`. I had no shell, so `docs/project/issues/18-about-outbound-click-tracking.md` still exists and needs deleting (`git rm`) for the move to be complete.\n- **Status line:** changed from `enhancement, needs-triage` to `enhancement, complete`.\n- **Rest of the issue:** the Problem, Proposed solution, Validation, Related and the existing issue-21 comment are unchanged.\n- **New comment, \"Delivered\" (one paragraph, in the style of archive/21):**\n  - It names the delivering plan, `docs/project/plans/23-18-about-outbound-click-tracking.md`.\n  - It says what was built in one sentence per part: the Client backend owns the endpoint, `about-analytics.ts` sends the `page_view` and `outbound_click` events, and they are stored in `users.db`. Issue 21's nginx pages log is unchanged.\n  - It points at the other documents rather than repeating them: the route contract in `client/README.md`, what an About override adds in `client/frontend/README.md`, and the count queries in `DEPLOYMENT.md` \"Count About analytics events\".\n  - **Departures from the issue text:**\n    - one route, `POST /api/analytics/event`, instead of `/outbound-click`;\n    - the table is `analytics_events` (with a `type` column) instead of `outbound_click_events`;\n    - events are checked by shape instead of an allowlist, with the reason;\n    - no `ip_hash`, and the rate limit is the shared per-address limiter;\n    - the template and the override docs changed instead of `client/frontend/about.html`.\n  - **Prod note:** beacons start only after the next `scripts/sync.sh` rebuilds `dist/`.\n  - **Follow-ups named:**\n    - all handler threads share one `user_db` connection (I confirmed `ThreadingHTTPServer` and `check_same_thread=False` in `server.py`);\n    - `tests/active/test_static_page_visit_logs.py` does not exist, and neither does its config.json group;\n    - `tests/active/test_analytics_events.py` does not exist (confirmed by glob), so the only coverage is the phase checkpoints in `tests/tmp/`. That follow-up needs removing if the harvest promotes the test.\n</changes>\n\n<not_on_checklist>\nnone. Two related changes belong to other turns or need a shell: (1) deleting the old `docs/project/issues/18-about-outbound-click-tracking.md`; (2) the `DEPLOYMENT.md` link to issue 18 (line 258) must point at the `archive/` path, which is part of that document's own update.\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/plan.md": "<changes>\nI updated `docs/project/issues/plan.md` to show issue 18 as delivered, in both the P5 priority row and the wave 5 lane 5c row.\n\n- **Line 42 (P5 row):** \"Why this tier\" said \"19, 20 and 21 are delivered, and 18 remains\". It now says \"All four are delivered.\" I dropped the \"None of these block other work\" sentence because nothing in the tier is left to schedule.\n- **Line 98 (lane 5c):**\n  - Added \"18 delivered, see `docs/project/plans/23-18-about-outbound-click-tracking.md`.\" The plan file exists at that path, not under `plans/archive/`.\n  - In the Main files cell, I replaced \"the About template, one Client endpoint\" with the files the build actually touched: `dev-pages/about.template.html`, `client/frontend/src/about-analytics.ts`, `POST /api/analytics/event` in `client/backend/server.py`, and `analytics_events` in `client/backend/lib/users_store.py`.\n\nIssue 18 currently exists twice: at `docs/project/issues/18-about-outbound-click-tracking.md` and at `docs/project/issues/archive/18-...`. The move is the issue-18 item's job, and the original should be deleted there. This file does not link to the issue path, so it is unaffected either way.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>"
  },
  "requirements": "### Purpose\n\nCount real human interest on the About page as explicit browser events, not by reading nginx logs. The events are outbound link clicks and page views. The nginx pages log added by issue 21 (`docs/project/issues/archive/21-static-page-visit-logs.md`) mixes in bots, crawlers, HEAD requests and malformed requests. An event sent by the page's own JavaScript is a much cleaner signal of a person who loaded the page or clicked a link. This build delivers issue `docs/project/issues/18-about-outbound-click-tracking.md`. It also delivers the client-side pageview beacon that issue 21 and `DEPLOYMENT.md` (\"Follow an About visit\") name as their upgrade path. This is event analytics. Issue 21's nginx pages log is request-log visibility, stays as it is, and is not duplicated or changed.\n\n### Ownership and routing (decided)\n\n- The Client backend (`client/backend/server.py`, port 7072 in prod) owns the endpoint. The Engine is not touched.\n- Reasons from the tree: prod nginx (`DEPLOYMENT.md` \u00a76) already proxies every `/api/` path to the Client backend. The boundary contract (`DEPLOYMENT.md` \u00a75) requires frontend reads and writes to use the Client API base, never the Engine. The Client backend already owns its own SQLite (`client/backend/db/users.db`), an in-memory per-key `RateLimiter` (`client/backend/lib/http_utils.py`), and client-address resolution (ADR-0002, `TRUSTED_PROXIES`).\n- No nginx or gateway change is needed: `location /api/` already covers the route. The vite dev server already proxies `/api`.\n- The CSP header `connect-src 'self'` already allows a same-origin beacon. No CSP change.\n\n### Endpoint\n\n- One route, `POST /api/analytics/event`, for both event types. There is no separate `/api/analytics/outbound-click`.\n- The body is JSON, read with the existing `read_json_body`. `navigator.sendBeacon` with a JSON `Blob` sends `Content-Type: application/json`. The route must not reject a request because of its Content-Type: it parses the body as JSON whatever the header says, so a `text/plain` beacon is also accepted.\n- `outbound_click` body: `{\"type\": \"outbound_click\", \"track_id\": <str>, \"href\": <str>, \"page_path\": <str>, \"timestamp\": <int ms>}`.\n- `page_view` body: `{\"type\": \"page_view\", \"page_path\": <str>, \"timestamp\": <int ms>}`.\n- Success answers `204` with an empty body (`respond_bytes(self, 204, b\"\")`, as `/api/profile/delete` does).\n- A body that fails validation answers `400` with a JSON `{\"error\": ...}`, and nothing is stored. Invalid JSON, a non-object body and a missing or wrong-typed field all count as failures.\n- Rate limit: the route goes through the existing `_rate_limit_check(url.path)` before any parsing. That is the shared `RateLimiter` at `RATE_LIMIT_MAX_REQUESTS` = 90 per `RATE_LIMIT_WINDOW_SECONDS` = 60, keyed `<client address>:<path>`. Over the limit it answers `429 {\"error\": \"Rate limit exceeded\"}`, as the other routes do. No new limiter is added.\n- The request is wrapped in the existing `_run_request`, so it gets `request.start`/`request.end` log records like every other route.\n- Unknown paths keep answering 404. `GET /api/analytics/event` is not a route.\n\n### Validation rules (no track_id allowlist)\n\nThe operator chose shape validation instead of an id/host allowlist, because the real About page is an untracked local override whose links the repository cannot know.\n- `type`: exactly `\"outbound_click\"` or `\"page_view\"`. Anything else is rejected.\n- `track_id`: required for `outbound_click` and must fully match `[a-z0-9_]{1,64}`. Examples: `about_patreon`, `about_github`, `about_youtube`. For `page_view` it must be absent or null; it is stored as NULL.\n- `href`: required for `outbound_click`. It must be a string of at most 2048 characters that parses (`urllib.parse`) as an absolute URL with scheme `http` or `https` and a non-empty host. For `page_view` it must be absent or null; it is stored as NULL.\n- `page_path`: required for both types. It must be a string of 1 to 256 characters that starts with `/`. It is stored as sent, so `/about`, `/about/` and `/about.html` stay distinguishable.\n- `timestamp`: the client's `Date.now()`. It is required and must be a JSON integer (not a bool) that is at least 0. It is shape-checked only and not stored, because a client clock is not trusted. The stored time is the server's receive time.\n- Extra unknown keys in the body are ignored.\n\n### Storage\n\n- A new table in the Client backend's existing SQLite database `users.db` (`DEFAULT_USERS_DB_PATH`). It is created idempotently with `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` alongside the existing tables in `ensure_user_schema` (`client/backend/lib/users_store.py`), or in an equivalent schema function that runs at the same startup point.\n- Schema: `analytics_events(id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK (type IN ('outbound_click', 'page_view')), track_id TEXT, href TEXT, page_path TEXT NOT NULL, created_at INTEGER NOT NULL, user_agent TEXT, referer TEXT)`.\n- `created_at` is server time in epoch milliseconds (`now_ms()` from `lib/time_utils.py`, the convention of the other tables).\n- `user_agent` is the request's `User-Agent` header and `referer` is its `Referer` header. Each is stored as NULL when absent or empty, so bots can be filtered in queries.\n- Index: `(type, track_id, created_at)`, which serves the per-track_id daily and total queries and the page_view counts.\n- Privacy: no raw IP, no `ip_hash` and no value derived from the client address is stored. The rate limit uses the client address in memory only.\n- Retention: every raw row is kept. Nothing prunes the table.\n- One accepted request inserts exactly one row.\n\n### Frontend\n\n- A bundled module, e.g. `client/frontend/src/about-analytics.ts` (exact name and location are for the design step). Inline script is not an option: the server CSP `script-src 'self'` blocks inline JS, and it is the About page's only CSP.\n- On page load it sends one `page_view` event with `page_path = location.pathname`.\n- It installs one delegated `click` listener on `document` for `a[data-track-id]`. When a click resolves (via `closest`) to such a link, it sends one `outbound_click` event: `track_id` from the attribute, `href` from the link's resolved `href`, `page_path = location.pathname`, `timestamp = Date.now()`. It never calls `preventDefault`, so navigation is unaffected. A click on a link without `data-track-id` sends nothing.\n- Transport: `navigator.sendBeacon(url, new Blob([JSON.stringify(payload)], {type: \"application/json\"}))`. If `sendBeacon` is missing or returns false, it falls back to `fetch(url, {method: \"POST\", body, headers: {\"Content-Type\": \"application/json\"}, keepalive: true})`. Failures are swallowed and never surface to the visitor.\n- The URL is built from the existing Client API base (`client/frontend/src/data/api-base.ts`), never an Engine base.\n- `client/frontend/dev-pages/about.template.html` gets the module's `<script type=\"module\" src=\"/src/...\">` tag with a root-absolute URL, so the default About page sends page views. The template has no outbound links, so it sends no clicks.\n- The local override `client/frontend/dev-pages/about.html` is untracked and is not edited. `client/frontend/README.md` (\"Local About Overrides\") documents what an override adds: the same root-absolute `<script type=\"module\">` tag, and a `data-track-id=\"<id matching [a-z0-9_]{1,64}>\"` attribute on each outbound link to count. Vite bundles the tag because the override is the `about` build input in `vite.config.ts`.\n\n### Reporting\n\n- No new code, HTTP endpoint or CLI. `DEPLOYMENT.md` gets a Triage runbook section with ready-to-run `sqlite3` queries against the Client backend's `users.db` for:\n  - total `outbound_click` count per `track_id`;\n  - daily `outbound_click` count per `track_id`, with the day in UTC from `created_at` ms;\n  - total and daily `page_view` count, optionally per `page_path`;\n  - the same queries with a `user_agent` filter shown as the way to exclude obvious bots.\n- The existing \"Follow an About visit\" caveat in `DEPLOYMENT.md` points at issue 18 as the pageview upgrade path. Update it to say the pageview beacon now exists and where its counts are queried. Fix the issue path there and in related docs if issue 18 moves to `docs/project/issues/archive/`.\n- The `/api/analytics/event` route is added wherever `DEPLOYMENT.md` or `client/README.md` lists the Client backend's public routes.\n\n### Tracker housekeeping\n\n- When delivered, issue 18's `Status:` becomes `enhancement, complete`, a delivery comment is added in the style of issue 21's, and the file moves to `docs/project/issues/archive/` (see `docs/project/triage-labels.md`, `docs/project/issue-tracker.md`).\n- `CONTEXT.md` gets one glossary entry for **Analytics event**: what it is and its two types, that it is the Client backend's and not the Engine's, and that it is distinct from an Interaction event, which feeds the Engine.\n\n### Validation (acceptance)\n\n- Click dispatch: clicking an `a[data-track-id]` sends exactly one beacon to `/api/analytics/event` with `type`, `track_id`, `href`, `page_path` and `timestamp` correct. Clicking a link without the attribute sends none. Page load sends exactly one `page_view` with `page_path` and `timestamp`. When `sendBeacon` is unavailable or returns false, the `fetch` keepalive fallback is used.\n- A valid `outbound_click` and a valid `page_view` each answer 204 and add exactly one row with the expected columns. `created_at` is server time, `user_agent` and `referer` come from the headers, and nothing IP-derived is stored.\n- Each invalid case answers 400 and stores nothing: unknown `type`, bad `track_id` shape, non-http(s) or hostless or over-long `href`, bad `page_path`, missing or non-integer `timestamp`, invalid JSON, and a `track_id` or `href` on a `page_view`.\n- Exceeding the rate limit for one client address answers 429 and stores nothing for the rejected requests.\n- Counter: repeated valid clicks for one `track_id` raise its count in the DB, measured by the documented total and daily queries. The tracked template has no outbound links, so this is exercised through the endpoint or a test fixture page, not the template.\n- The built About page, from the template, includes the bundled analytics script, so a page load beacons a `page_view`.\n\n### Test locations and baseline suite state\n\n- New gating tests go in `tests/active`, with working files in `tests/tmp`. Archived tests are in `tests/archive`. Plans go in `docs/project/plans`. The run record is `tests/last_test_validation.json` and the output is `tests/last_test_output.txt`. The project dir is `/home/enduser/code/PeerTube-browser/.worktrees/18`.\n- Baseline before the build: the suite passes (exit code 0, not a variant run). Any red test after the build is caused by the build.\n- `tests/active/test_static_page_visit_logs.py` compares the nginx About locations with `vite.config.ts`. The build must keep it green: no About URL or dev-pages name changes.",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nI read `client/backend/server.py` (the `_serve_post` router, `_run_request`, `_rate_limit_check`, startup at line 1308), `lib/http_utils.py` (`read_json_body`, `respond_bytes`), `vite.config.ts`, `dev-pages/about.template.html`, `src/data/api-base.ts` and the existing esbuild-in-node frontend tests (`tests/active/test_frontend_profile.py`). The settled design fits the tree as it stands. Nothing needs new infrastructure: no dependency, no new limiter, no nginx, CSP or Engine change.\n\n**Backend route.** `_serve_post` gets one new branch for `/api/analytics/event`, placed before the final 404 and shaped like its neighbours:\n- `_rate_limit_check(url.path)` runs first, and a refusal answers `429 {\"error\": \"Rate limit exceeded\"}`.\n- The body is read with `read_json_body`. That function never looks at Content-Type, so the `text/plain` acceptance requirement is met without any extra code. It already raises `ValueError` for invalid JSON, a non-object body, invalid UTF-8 (`UnicodeDecodeError` is a `ValueError`), a non-numeric Content-Length and a body over 1 MB. All of these map to `400 {\"error\": ...}`. An empty or missing body comes back as `{}` and then fails validation on the missing `type`, so it is also a 400.\n- A valid event gets one row inserted and the answer `respond_bytes(self, 204, b\"\")`.\n\nThe route already sits inside `do_POST` \u2192 `_run_request`, so it gets `request.start`/`request.end` for free. `GET /api/analytics/event` matches no GET branch and keeps answering 404, as does every other unknown path.\n\n**Validation.** One pure module-level function in `server.py`. It takes the parsed dict and returns either the row values or an error string, so the route stays a thin branch and the rules can be tested directly. It applies the rules exactly as settled:\n- `type` must be in the two-value set.\n- `track_id` must pass `re.fullmatch` against `[a-z0-9_]{1,64}`. That is `fullmatch`, not `match` with `$`, because `$` accepts a trailing newline. It is required for `outbound_click` and must be absent or `None` for `page_view`.\n- `href` must be a `str` of at most 2048 characters. `urllib.parse.urlsplit` must give a scheme of `http` or `https` and a non-empty `hostname`. The `ValueError` that `urlsplit` raises on a malformed bracketed host is caught and becomes a 400. The same absent-or-null rule as `track_id` applies on `page_view`.\n- `page_path` must be a `str` of 1 to 256 characters starting with `/`, and is stored verbatim.\n- `timestamp` must be an `int` that is not a `bool` and is `>= 0`. It is checked and then discarded.\n- Unknown keys are ignored.\n\nThe handler adds the server-side values: `now_ms()`, plus the `User-Agent` and `Referer` headers, each turned into `None` when absent or empty after stripping. Nothing derived from `_get_client_ip()` reaches the row.\n\n**Storage.** `ensure_user_schema` in `lib/users_store.py` gains the `analytics_events` `CREATE TABLE IF NOT EXISTS` with the settled columns and CHECK, and the `(type, track_id, created_at)` `CREATE INDEX IF NOT EXISTS`. It already runs at startup (`server.py:1311`), and it is the literal option the requirements name, so existing databases pick up the table on the next restart. The same module gets a small `insert_analytics_event(conn, ...)` that does one `INSERT`, called inside `with self.server.user_db:` the way the other writes are, so one accepted request is one committed row.\n\n**Frontend.** A new module, `client/frontend/src/about-analytics.ts`. When it runs it:\n- builds the URL once as `resolveClientApiBase()` plus `/api/analytics/event`. It is called without an argument, so `?api=` is never read; in a prod build it is the page origin;\n- sends one `page_view` (`page_path = location.pathname`, `timestamp = Date.now()`);\n- adds one delegated `click` listener on `document`. The listener resolves `event.target.closest(\"a[data-track-id]\")`, guarding a target that has no `closest`, and for a match sends `outbound_click` with the attribute value, `link.href` (the browser-resolved absolute URL), the pathname and `Date.now()`. It never calls `preventDefault`.\n\nOne `send` helper does the transport: `sendBeacon` with a JSON `Blob`. If `sendBeacon` is missing, returns false or throws, the helper falls back to `fetch` with `keepalive: true`. It wraps everything in try/catch and attaches a no-op `.catch` to the fetch promise, so nothing reaches the console as an unhandled rejection. The template gets `<script type=\"module\" src=\"/src/about-analytics.ts\"></script>`, the same root-absolute style as its `/src/videos.css` link. No About URL, input name or dev-pages filename changes, so `test_static_page_visit_logs.py` stays green.\n\n**Reporting and docs.** No new code.\n- **`DEPLOYMENT.md`**:\n  - A new Triage subsection, \"Count About analytics events\". It holds a `sqlite3 -readonly <root>/client/backend/db/users.db` invocation and fenced `sql` blocks: total clicks per `track_id`; daily clicks per `track_id` using `date(created_at / 1000, 'unixepoch')`, which is UTC; total and daily `page_view`, optionally grouped by `page_path`; and the same queries with a `user_agent IS NOT NULL AND user_agent NOT LIKE '%bot%' AND \u2026 '%crawl%' AND \u2026 '%spider%'` filter shown as the bot exclusion.\n  - The \"Follow an About visit\" caveat at line 258 is rewritten to say the beacon exists and to point at the new subsection, with the issue path changed to `archive/`.\n  - The public-route prose near line 405 gets the route.\n- **`client/README.md`**: the route list at line 41 gets the route, and the API bullets get one line describing it.\n- **`client/frontend/README.md`**: \"Local About Overrides\" gets the script tag and the `data-track-id` convention. It also notes that only http(s) links can be counted.\n- **`CONTEXT.md`**: one **Analytics event** entry.\n- **Tracker**: issue 18 gets its status, a delivery comment and the move to the archive. Lane 5c in `docs/project/issues/plan.md` gets a path and delivery fix.\n\n**Tests (gating, `tests/active`).**\n- **Backend.** The `client_backend` fixture over a socket covers: each valid type gives 204 and exactly one row with the expected columns, with `created_at` inside the request window rather than equal to the client timestamp, and UA/Referer taken from the headers. A `PRAGMA table_info` assertion checks there is no IP-like column. Each invalid case gives 400 and zero rows, as does a `text/plain` valid beacon, which must be accepted. The rate-limit test sends 91 posts from one address: the extras get 429 and add no rows. `GET` answers 404.\n- **Counter.** The test posts N clicks for one `track_id` and runs the SQL blocks extracted from the new `DEPLOYMENT.md` subsection against the fixture's DB, using Python `sqlite3` so the test does not depend on the CLI binary.\n- **Frontend.** The module is bundled with the project's esbuild, as `test_frontend_profile.py` does. It runs in node against stubbed `document`, `location`, `navigator.sendBeacon` and `fetch`, and the test asserts one `page_view` on load, one correct `outbound_click` per tracked click, none for an untracked link, and the fetch keepalive fallback when `sendBeacon` is undefined or returns false.\n- **Built page.** `vite build --outDir tests/tmp/...` is run and the test asserts that the built `dev-pages/about.template.html` references a bundled `/assets/*.js` whose contents include `/api/analytics/event`.\n\n### Alternatives considered\n\n- **Validation in a new `lib/analytics_events.py` (schema, validate, insert).** Rejected. It adds a file and a second schema call site at startup for about 40 lines of code. `users_store.py` already owns `users.db`'s schema, and `server.py` already holds the route-level checks.\n- **Validation inside `users_store.py`.** Rejected. The store module takes trusted values and HTTP-shaped validation does not belong there.\n- **A separate SQLite file for analytics.** Rejected: the requirement says `users.db`, and a second file means a second connection, startup step and backup path.\n- **Per-day aggregate counters instead of raw rows.** Rejected: the bot filter on `user_agent` would be impossible after aggregation, and the requirement keeps raw rows.\n- **Transport:** `fetch` alone can be cancelled by the navigation an outbound click causes. A GET image pixel would need a GET route and puts the payload in URLs and logs. `sendBeacon` alone has no fallback for browsers or privacy settings that disable it. The settled `sendBeacon` plus `fetch keepalive` combination covers all three.\n- **Per-link listeners instead of one delegated listener.** Rejected: they miss links inserted later and need a query at load time. The delegated listener is the settled choice as well.\n- **Built-page check by reading the template source only.** Rejected as the sole check: it proves the tag is there, not that vite bundles it. The real build is the acceptance criterion.\n\n### Risks, gotchas and limitations\n\n- **Local override and the built-page test.** `vite.config.ts` builds `dev-pages/about.html` when it exists. On a checkout with an untracked override, the build produces the override, not the template. The test will skip with an explicit reason in that case rather than assert on the wrong file. The worktree normally has no override, so the gate runs. The ceiling is that an operator's override without the tag sends nothing, which the README documents.\n- **Non-http(s) tracked links.** A `mailto:` or `tel:` link with `data-track-id` is beaconed and rejected with 400 by the shape rule, so it is never counted. The README says so. Widening the rule is the upgrade path if that is ever wanted.\n- **Clicks the `click` event does not see.** Middle-click opens a tab through `auxclick`, not `click`, and the context-menu \"Open in new tab\" fires nothing, so neither is counted. Ctrl/Cmd-click and keyboard Enter do fire `click` and are counted. This is a deliberate simplification: listening for `auxclick` as well is a one-line upgrade, but it is outside the settled spec.\n- **Cross-origin dev base.** If `VITE_CLIENT_API_BASE` points at a different origin, a `sendBeacon` with an `application/json` Blob is a non-CORS-safelisted request, and some browsers throw or refuse it. The try/catch then falls through to `fetch`, which preflights through the existing `respond_options` CORS handling. In prod the base is same-origin and none of this applies.\n- **Forgeable counts.** The endpoint is anonymous and accepts any well-formed body. A script can inflate counts at up to 90 per minute per address, roughly 130k rows a day per address. Retention is unbounded by requirement, so a sustained abuser grows `users.db` without limit. The per-address limiter is the only control. Both are named in the DEPLOYMENT section, and a prune or a per-address daily cap is the upgrade path.\n- **Header storage.** `User-Agent` and `Referer` are stored as sent. `http.server` caps a header line at 64 KiB, which bounds each row, but there is no tighter truncation because the spec does not ask for one.\n- **Shared SQLite connection.** Analytics writes share the connection and transaction pattern of the profile writes, so a burst of beacons briefly serialises with like and dislike writes. At the 90/min/address rate this is negligible.\n- **The bot filter is a heuristic.** The UA can be forged. The documented `NOT LIKE` filter removes honest crawlers only. That is said in the docs, consistent with the issue-21 caveat.\n- **Referer is often reduced.** The default `strict-origin-when-cross-origin` policy usually leaves `Referer` as the About URL itself. It is mostly useful as a has-or-hasn't signal.\n\n### Tradeoffs the operator is asked to accept\n\n- The built-page gate skips rather than fails on a checkout that has a local `about.html` override.\n- Middle-click and context-menu opens are not counted.\n- Tracked non-http(s) links are silently not counted.\n- Counts are best-effort human signals: anonymous, forgeable within the rate limit, and growing without pruning.",
  "conflicts": "none",
  "impacts": "<impacts>\n<impact path=\"client/backend/server.py\" element=\"module imports (lines 5-41) and module constants (lines 46-73)\">\n**What changes.**\n- `re` is not imported today (lines 5-23).\n- `urllib.parse` imports only `parse_qs, urlencode, urlparse` (line 20), so the plan's `urlsplit` must be added there.\n- `insert_analytics_event` joins the wrapped, alphabetised `from lib.users_store import (...)` block at lines 39-41, between `get_or_create_user` and `load_liked_keys`.\n- New constants follow the style of `USER_ACTIONS = frozenset((...))` (line 62) and `BLOCK_REFERENCE_MAX_LENGTH = 200` (line 68): a two-value event-type frozenset, a `[a-z0-9_]{1,64}` pattern, a 2048 href cap and a 256 page_path cap.\n\n**What depends on it.** `tests/active/conftest.py:43` imports the module as `client_server`, and `tests/active/test_server.py:161` re-imports from conftest. Every Client-backend test therefore loads it at collection time.\n\n**Regression risk.** Low. An import or name error fails the whole active suite loudly at collection.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"ClientBackendHandler._serve_post (lines 437-501): new `/api/analytics/event` branch and its handler method\">\n**What changes.**\n- A new `if url.path == \"/api/analytics/event\":` branch goes before the comment at 497-500 and the final 404 at 501.\n- It is shaped like `/api/user-action` (464-469): `_rate_limit_check(url.path)`, then 429 `{\"error\": \"Rate limit exceeded\"}`, then a `_handle_analytics_event()` method.\n- That method reads the body with `try: read_json_body(self) except ValueError as exc: respond_json(self, 400, {\"error\": str(exc)})`, the exact idiom at 1014-1018 and 1050-1054. It then validates, writes with `with self.server.user_db: insert_analytics_event(...)` (the idiom at 410 and 1119), and answers `respond_bytes(self, 204, b\"\")` like `/api/profile/delete` (line 462).\n\n**What depends on it.**\n- `do_POST` \u2192 `_run_request` (377-379, 339-357) gives `request.start`/`request.end` with no extra code. `request.start` already logs `ip` and `user_agent`, but that is a log, not storage.\n- `_serve_get` (381-435) is untouched, so `GET /api/analytics/event` falls to the 404 at 435.\n- `do_OPTIONS` (369-371) answers `respond_options` for any path, so a CORS preflight to the new path already gets 204.\n- In prod, nginx's `location /api/` (DEPLOYMENT.md:486-493) already proxies the path to 7072, so no nginx change is needed.\n\n**Regression risk.** Low for existing routes, since the match is on the exact path.\n- A branch placed after line 501 never runs.\n- The limiter key is `<ip>:/api/analytics/event` (`_rate_limit_check`, 514-517), so analytics has its own 90/min bucket and does not drain `/api/user-action`'s.\n- A 429 or a validation 400 leaves part of the body unread. That is harmless only because nothing in `client/backend` sets `protocol_version` or `close_connection` (I grepped), so each connection is HTTP/1.0 and closes.\n- No socket timeout is set, so a `Content-Length` larger than the bytes actually sent blocks a thread in `rfile.read`. Every POST route already has this, but this route is anonymous and hit on every About view.\n- `str(exc)` for a `UnicodeDecodeError` is a long codec message rather than \"Invalid JSON body\". It is still a 400, but tests should assert the status, not the text.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"new module-level validator (e.g. `_validate_analytics_event(body)`), near `_parse_client_likes` (lines 1236-1252)\">\n**What changes.** A new pure function that returns the row values or an error string, in the sibling style: a `_` prefix and a `\"\"\"Handle ...`/`:returns:` docstring.\n\n**What depends on it.** The route handler, and the backend tests, which can call it directly as `client_server._validate_...`.\n\n**Regression risk.** Medium. An exception that escapes the validator does not become a 400. It goes to socketserver's `handle_error`, the client gets no response, and `request.end` logs status `-`. The cases:\n- **Type checks first.** `re.fullmatch` on an int raises `TypeError`, and `len`, `.startswith` and `urlsplit` also fail on non-strings. Check `isinstance(..., str)` before each.\n- **`bool` is an `int`.** `timestamp: true` must be rejected. `1.0` arrives as a `float` from `json.loads` and must be rejected too.\n- **Lone surrogates.** `json.loads('\"\\ud800\"')` gives a `str` that sqlite3 cannot bind (`UnicodeEncodeError` at INSERT, after validation). `href` and `page_path` therefore need an encodability check. `track_id` is safe because of its regex.\n- **`urlsplit` details.**\n  - `\"https://\"` gives `hostname=None`, which must be rejected.\n  - `\"http://[::1\"` raises `ValueError`, which must be caught.\n  - `.hostname` itself can raise on a malformed bracketed netloc, so the catch must cover the attribute read as well as the call.\n  - The scheme comes back lowercased, so `HTTPS://` passes.\n- **Null handling.** An explicit `null` `track_id` or `href` is accepted on `page_view` and rejected on `outbound_click`.\n- **`page_path`.** `//host` passes the leading-slash rule. That is acceptable because the value is stored, never followed.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"User-Agent / Referer capture in the new handler, and `_get_client_ip` (lines 326-329)\">\n**What changes.** The handler reads `self.headers.get(\"User-Agent\")` and `self.headers.get(\"Referer\")`, strips each, and stores `None` when the result is empty. That is the same idiom as `_run_request` at 347-349. `_get_client_ip` is reached only through `_rate_limit_check`.\n\n**What depends on it.** The \"nothing IP-derived stored\" requirement and the `PRAGMA table_info` test.\n\n**Regression risk.** Low.\n- nginx sets `X-Real-IP` and `X-Forwarded-For` on `/api/` (DEPLOYMENT.md:489-490), and neither may reach the row.\n- Headers are stored up to http.server's 64 KiB line cap, which the plan accepts. http.server decodes headers as latin-1, so they always bind in sqlite.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"connect_db (lines 230-234) and the single shared `user_db` connection used by every handler thread\">\n**What changes.** No code change. The new route adds writes on this connection.\n\n**What depends on it.** Every profile write: `_store_reaction`'s `with conn:` blocks (974, 991, 999), the likes import (1027), reset and blocks (1119, 1135), `lib/blocks.py:56,80` and `lib/profiles.py:74`.\n\n**Regression risk.** Medium, and the plan understates it as \"serialises briefly\".\n- There is one `sqlite3.Connection` (`check_same_thread=False`) shared by all `ThreadingHTTPServer` threads, with no lock. I grepped: the only lock is `RateLimiter.lock`.\n- `with conn:` commits or rolls back the connection's single open transaction. A beacon commit on one thread can commit another thread's half-done multi-statement write, and a rollback elsewhere can drop a beacon insert.\n- The race exists today. This is the first anonymous write route allowed 90/min per address on every About view, so it is hit far more often.\n- Name it as an inherited limitation and open a follow-up issue (a write lock or per-thread connections). The plan does not fix it.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"main(): `ensure_user_schema(user_db)` (line 1311)\">\n**What changes.** No edit. Existing databases get the table and index on the next restart.\n\n**What depends on it.** Prod and dev upgrades. There is no migration step, consistent with DEPLOYMENT.md:408.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"ensure_user_schema (lines 10-71): docstring and script\">\n**What changes.**\n- Add `CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK (type IN ('outbound_click','page_view')), track_id TEXT, href TEXT, page_path TEXT NOT NULL, created_at INTEGER NOT NULL, user_agent TEXT, referer TEXT)`.\n- Add `CREATE INDEX IF NOT EXISTS <name>_idx ON analytics_events (type, track_id, created_at)`, named like `likes_user_updated_idx` (line 27).\n- Both go before the `local-user` cleanup DELETEs (67-69).\n- The docstring on line 11 enumerates the tables the function creates, so it must gain the analytics events table.\n\n**What depends on it.** `server.py:1311`, `tests/active/conftest.py:77` and `:169`, and `tests/active/test_server.py:398`, `:834` and `:997`.\n\n**Regression risk.** Low. No active test enumerates users.db tables: the `sqlite_master`/`table_info` hits are in Engine-DB tests. `test_profiles.py:103` byte-scans `users.db*` for key material, and an empty new table adds none.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"new insert_analytics_event(conn, ...)\">\n**What changes.** A new function that runs one parameterised INSERT. It must not call `conn.commit()`, because the handler's `with self.server.user_db:` owns the transaction.\n\nThe module is inconsistent on this point. `get_or_create_user`, `record_like` and `clear_likes` commit internally, while `remove_like` and `close_like` say \"inside the caller's transaction\" (lines 192, 216). Follow the latter, docstring phrase included.\n\n**What depends on it.** The route, and the counter test that reads the rows back.\n\n**Regression risk.** Low. `created_at` must come from the handler's single `now_ms()` (lib/time_utils), so that the test's before/after window holds.\n</impact>\n<impact path=\"client/backend/lib/http_utils.py\" element=\"read_json_body (lines 78-95)\">\n**What changes.** Nothing. I confirmed by reading it that the plan's assumptions hold:\n- Content-Type is never read, so `text/plain` is accepted.\n- `int()` on a non-numeric length raises `ValueError`.\n- A length over 1,000,000 raises `ValueError`.\n- `.decode(\"utf-8\")` raises `UnicodeDecodeError`, which is a `ValueError`.\n- A non-dict body raises `ValueError`.\n- A length of 0 or less, a missing length, or a whitespace-only body returns `{}`.\n\n**What depends on it.** Every JSON POST route.\n\n**Regression risk.** None, provided it is not edited.\n</impact>\n<impact path=\"client/backend/lib/http_utils.py\" element=\"_send_cors_headers / respond_options / ALLOWED_REQUEST_HEADERS (lines 12-44, 71-75)\">\n**What changes.** Nothing.\n\n**What depends on it.** Cross-origin dev beacons, and `respond_bytes`' CORS headers on the 204.\n\n**Regression risk.** No backend regression. There is a frontend consequence the plan's cross-origin note understates:\n- No `Access-Control-Allow-Credentials` is ever sent.\n- `navigator.sendBeacon` uses credentials mode `include`, and an `application/json` Blob is not CORS-safelisted, so cross-origin it is preflighted, and a credentialed preflight without Allow-Credentials fails.\n- Whether a browser then throws, which reaches the fetch fallback, or returns `true` and drops the event silently varies. I could not verify this from the tree. Treat dev cross-origin beacon loss as possible.\n- Prod is same-origin and unaffected.\n</impact>\n<impact path=\"client/backend/lib/http_utils.py\" element=\"RateLimiter (lines 98-124)\">\n**What changes.** Nothing.\n\n**What depends on it.** The new 429, and the forgeability ceiling.\n\n**Regression risk.** Low.\n- Buckets are never evicted, so each distinct address adds a deque until restart. This route grows the map faster than the others.\n- `max_requests <= 0` disables limiting.\n- A 429 is invisible to `sendBeacon`, so behind a shared or misresolved address, counts silently cap at 90/min.\n</impact>\n<impact path=\"client/backend/lib/profiles.py\" element=\"delete_profile\">\n**What changes.** Nothing. Analytics rows carry no profile id, so profile deletion neither touches them nor needs to. client/README.md:13 (\"everything keyed to it\") stays true.\n\n**What depends on it.** Nothing new.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"client/frontend/src/about-analytics.ts\" element=\"new module (whole file)\">\n**What changes.** A new module that imports `resolveClientApiBase` from `./data/api-base`. On import it sends one `page_view` and installs one delegated `document` click listener. A `send` helper tries `navigator.sendBeacon(url, Blob)` and falls back to `fetch(url, {method: \"POST\", keepalive: true, ...})` with a no-op `.catch`.\n\n**What depends on it.** Five things must all name the same path:\n- the template's script tag;\n- the README override instructions;\n- the node test;\n- the built-page test;\n- the new config.json test group.\n\n**Regression risk.** Medium, because every failure is silent by design.\n- **URL construction.** Every sibling builds URLs as `new URL(\"/api/...\", base)` (user-actions.ts:20, reactions.ts:34/68, blocks.ts:57, profile.ts:88, user-profile.ts:23/43/61). None concatenates, and plain concatenation produces `//api/...` when `VITE_CLIENT_API_BASE` ends in `/`. Use `new URL`, inside the try, since it throws on a bad base.\n- **Placement.** The page entries live at `src/pages/<page>/index.ts` (channels, likes, search, video-page, videos). The plan's `src/about-analytics.ts` at the src root departs from that convention. Either is workable, but decide it at design.\n- **`sendBeacon` binding.** It must be called as `navigator.sendBeacon(...)`. A detached reference throws \"Illegal invocation\", the catch swallows it, and every event goes through fetch.\n- **`event.target`.** It can be a Text or non-Element node with no `closest`.\n- **SVG links.** An SVG `<a>`'s `.href` is an `SVGAnimatedString`, so read `getAttribute`/`href` defensively or accept a 400.\n- **Module script.** A module script is deferred, so no DOMContentLoaded wait is needed.\n- **Import-time read.** api-base.ts:5 reads `window.location.origin` at import.\n- **`fetch` failures.** `fetch` can throw synchronously (a keepalive body over 64 KiB) as well as reject, so it needs both the try and the `.catch`.\n- **No type gate.** The build script is plain `vite build` (package.json:9), so TS type errors do not fail the build.\n- **Gateway scan.** `tests/check-frontend-client-gateway.sh` scans `src`. It passes provided no Engine base, `127.0.0.1:707x` or `/internal/*` literal appears.\n</impact>\n<impact path=\"client/frontend/src/data/api-base.ts\" element=\"resolveClientApiBase (lines 18-33), DEFAULT_CLIENT_API_BASE (line 5)\">\n**What changes.** Nothing. The new module calls it with no argument, so `?api=` is never read and prod returns `window.location.origin`.\n\n**What depends on it.** Every data module and the new one.\n\n**Regression risk.** Low.\n- Line 5 runs at import, so the node test must define `globalThis.window.location.origin` before `await import(bundle)`, as test_frontend_profile.py:30 does.\n- `normalizeApiBase` keeps a trailing slash. This is harmless with `new URL`.\n- Bundling it into the About entry may move it into a shared chunk and change other pages' asset hashes. That is harmless.\n</impact>\n<impact path=\"client/frontend/dev-pages/about.template.html\" element=\"new `<script type=\\\"module\\\" src=\\\"/src/about-analytics.ts\\\">` tag\">\n**What changes.** One line. It is root-absolute like the `/src/videos.css` link on line 8, as client/frontend/README.md:41 requires. Today the template has no script at all, so it becomes the About page's first JS.\n\n**What depends on it.**\n- `vite.config.ts` uses it as the `about` input when no override exists, which is the case in this worktree: Glob finds only the template.\n- nginx serves the built copy from `dev-pages/` (DEPLOYMENT.md:467-483, 519).\n- `.un/skills/devsecops/config.json:263-268` maps it to a test that does not exist.\n- `tests/tmp/test_21_static_page_visit_logs_phase{1,2,3}.py` read the template bytes into nginx. They are non-gating.\n\n**Regression risk.** Low.\n- The server CSP (DEPLOYMENT.md:459) has `script-src 'self'` and `connect-src 'self' https:`, which allow the bundled `/assets/*.js` and a same-origin beacon. An inline script would be blocked.\n- The template's text (line 30) tells operators to replace it with an override, so the override docs carry the real instruction burden.\n</impact>\n<impact path=\"client/frontend/vite.config.ts\" element=\"aboutSourcePath (16-18), build.rollupOptions.input.about (91-93), server.proxy['/api'] (27-32)\">\n**What changes.** Nothing.\n\n**What depends on it.** The built-page test, and dev beacons.\n\n**Regression risk.** Medium for test design.\n- **Override switch.** `existsSync(devAboutPath)` switches the input to an untracked override (`.gitignore:29-30`). The plan skips the test in that case.\n- **Output location.** The built page lands at `<outDir>/dev-pages/about.template.html`. The `/api/analytics/event` literal sits in the About entry chunk, while api-base may land in a shared chunk. The assertion must follow the page's `<script src>`, not assume a single file.\n- **Output directory.**\n  - `tests/tmp` is not gitignored (I grepped `.gitignore`), so `--outDir tests/tmp/...` leaves untracked build output in the tree. Prefer pytest's `tmp_path`, passed as an absolute path.\n  - An outDir outside the root needs `--emptyOutDir` or a fresh directory.\n  - Never write into the committed `client/frontend/dist/`.\n- **First vite test.** No active test runs vite today. Eight tests run `node_modules/.bin/esbuild`. `vite` is a devDependency (package.json:18). `node_modules` is outside the sandbox, so I could not confirm `.bin/vite` exists.\n- **Dev proxy.** `server.proxy['/api']` makes plain `npx vite` same-origin.\n</impact>\n<impact path=\"client/frontend/scripts/dev.mjs\" element=\"VITE_CLIENT_API_BASE default (lines 15, 46, 104)\">\n**What changes.** Nothing.\n\n**What depends on it.** `npm run dev` always sets a cross-origin base (`http://127.0.0.1:7172`), so dev beacons need `CLIENT_CORS_ORIGINS` and are subject to the credentialed-sendBeacon uncertainty above.\n\n**Regression risk.** Dev-only event loss, not a regression. Document it.\n</impact>\n<impact path=\"client/frontend/dist/dev-pages/about.template.html\" element=\"committed build output (and dist/assets)\">\n**What changes.** Not in the plan. Today it holds only the CSS link (line 8) and no script, and it lags the source until a rebuild.\n\n**What depends on it.** Prod gets the beacon only after `scripts/sync.sh` runs `npm run build` (sync.sh:19).\n\n**Regression risk.** Low. State in the delivery comment that prod sends nothing until the next sync. The built-page test must not write here.\n</impact>\n<impact path=\"scripts/sync.sh\" element=\"build-then-rsync (line 19 onward)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is the only path by which the beacon reaches prod.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"client_backend fixture (73-93) and ClientBackend.request (55-70)\">\n**What changes.** Nothing, unless a helper is added.\n\n**What depends on it.** The new backend tests.\n\n**Regression risk.** Medium for test design.\n- The fixture uses `RateLimiter(1000, 60)` (line 84), so the plan's \"91 posts \u2192 429\" test cannot run on it. It needs its own server with `RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS)`.\n- `ClientBackend.request` always sets `content-type: application/json` and JSON-encodes the body. The `text/plain`, invalid-JSON, non-UTF-8, empty-body and custom UA/Referer cases need raw `urllib.request`.\n- A 204's empty body comes back as `None`, which is fine.\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"_serving (383-391), _client_backend(tmp_path, engine_base, rate_limiter) (394-403), _status (406-414), test_route_limiter_buckets_by_last_hop (417)\">\n**What changes.** Nothing, unless the new tests live here or copy these helpers.\n\n**What depends on it.** It is the precedent for the rate-limit test: `_client_backend(..., RateLimiter(...))` builds a server with a chosen limiter. The peer 127.0.0.1 is a trusted proxy by default, so `X-Forwarded-For` can model a fresh address per test.\n\n**Regression risk.** Low. No existing test enumerates POST routes or uses the new path.\n</impact>\n<impact path=\"tests/active/test_frontend_profile.py\" element=\"esbuild-in-node pattern (ESBUILD line 21, RUNNER 23-43, _bundle 46-62)\">\n**What changes.** Nothing. It is the template for the node test. The `--define:import.meta.env.VITE_CLIENT_API_BASE=...` and `--define:import.meta.env.DEV=false` flags (56-57) are required, or `import.meta.env` is undefined in node.\n\n**What depends on it.** The new frontend test. `test_frontend_video_page.py:105,117,133` and `test_frontend_videos_page.py:57,65,80` are the precedents for `globalThis.document`/`fetch` stubs and `unhandledRejection` capture.\n\n**Regression risk.** For the new test:\n- No active test stubs `navigator`. On Node 21 and later `globalThis.navigator` is a getter, so plain assignment may not take. Use `Object.defineProperty(globalThis, \"navigator\", {value, configurable: true})`.\n- Every stub, `window` and `location` included, must be installed before `import()`, because the module acts at import.\n- The Blob payload is read with `await blob.text()`.\n- `document.addEventListener` must capture the handler so the test can dispatch synthetic events with a `target.closest` stub.\n</impact>\n<impact path=\"tests/active/test_analytics_events.py\" element=\"new gating test file(s) (name for the design step)\">\n**What changes.** New tests covering the backend endpoint, the counter that runs SQL taken from DEPLOYMENT.md, the node frontend test and the vite built-page test.\n\n**What depends on it.** The suite gate, and new config.json groups.\n\n**Regression risk.** Medium.\n- **SQL extraction.** Pin the subsection heading and assert the expected number of `sql` blocks, so an empty extraction cannot pass vacuously.\n- **Timestamps.** Bound `created_at` by `now_ms()` taken before and after the request.\n- **Columns.** Assert the exact `PRAGMA table_info(analytics_events)` column list, not just the absence of an IP column.\n- **Build output.** Run the vite build in `tmp_path` with a generous timeout. Skip with a reason only when `dev-pages/about.html` exists.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups (lines 14-269)\">\n**What changes.** A new `test_groups` entry for each new test file. It maps the file to:\n- `client/backend/server.py`\n- `client/backend/lib/users_store.py`\n- `client/backend/lib/http_utils.py`\n- the new frontend module\n- `client/frontend/src/data/api-base.ts`\n- `client/frontend/dev-pages/about.template.html`\n- `client/frontend/vite.config.ts`\n- `DEPLOYMENT.md`, for the SQL extraction\n\n**What depends on it.** The validator that selects re-runs. These existing groups claim server.py and/or users_store.py and will re-run:\n- `test_profiles`\n- `test_dislikes`\n- `test_frontend_profile`\n- `test_server`\n- `test_blocks`\n- `test_frontend_blocks`\n- `test_frontend_reactions`\n- `test_frontend_upnext_pager`\n\n**Regression risk.** Medium. Without a group, the new tests are not selected when these files change.\n\nLines 263-268 are pre-existing drift. They map `test_static_page_visit_logs.py`, which does not exist, onto `DEPLOYMENT.md`, `vite.config.ts`, `about.template.html` and `server.py`, all four of which this build edits.\n</impact>\n<impact path=\"tests/active/test_static_page_visit_logs.py\" element=\"(does not exist)\">\n**What changes.** Nothing. Glob for `**/test_static_page_visit_logs*` finds no file. Issue 21's plan said the test step would write it; it was never written.\n\n**What depends on it.** Four places claim it as a guard:\n- the plan (\"stays green\");\n- DEPLOYMENT.md:465's rat-tail comment;\n- config.json:263;\n- issue 21's delivery.\n\n**Regression risk.** No regression, since no About URL or dev-pages name changes, but the claimed guard is absent. Drop the \"stays green\" wording, name the gap in the delivery comment, and open a follow-up issue.\n</impact>\n<impact path=\"tests/tmp/test_21_static_page_visit_logs_phase1.py\" element=\"template reads (phase1/2/3 working files)\">\n**What changes.** Nothing.\n\n**What depends on it.** These working files serve the template bytes through a real nginx.\n\n**Regression risk.** None for the gate: they are not gating. The extra tag lengthens the template, which keeps any template-versus-override length difference true.\n</impact>\n<impact path=\"tests/active/test_profiles.py\" element=\"users.db byte scan (line 103)\">\n**What changes.** Nothing.\n\n**What depends on it.** The users.db contents.\n\n**Regression risk.** None. The new table holds no key material.\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"Client route smoke checks (lines 548-617)\">\n**What changes.** Nothing is planned. A 204 check here would write a real row into the target users.db.\n\n**What depends on it.** Nothing.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"tests/check-frontend-client-gateway.sh\" element=\"forbidden-pattern scan of client/frontend/src (lines 22-38)\">\n**What changes.** Nothing.\n\n**What depends on it.** It will scan the new module.\n\n**Regression risk.** None, provided the module routes through `resolveClientApiBase` and hardcodes no Engine host or internal route.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"per-group records\">\n**What changes.** The run regenerates it. Never hand-edit it.\n\n**What depends on it.** The validator.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage: new subsection \\\"Count About analytics events\\\" between \\\"Follow an About visit\\\" (232-258) and \\\"Follow one request\\\" (260)\">\n**What changes.** A new subsection with:\n- the `sqlite3 -readonly <root>/client/backend/db/users.db` invocation;\n- fenced `sql` blocks: total clicks per `track_id`, daily clicks per `track_id` in UTC, total and daily `page_view` (optionally per `page_path`), and the bot-filtered variants.\n\nIts caveats:\n- counts are forgeable at 90/min per address;\n- retention is unbounded;\n- the UA filter is a heuristic;\n- Referer is often reduced;\n- middle-click and context-menu opens are not counted;\n- non-http(s) tracked links are rejected;\n- a shared or misresolved address silently undercounts;\n- dev cross-origin beacons may be lost;\n- the shared-connection limitation, if it is documented here.\n\n**What depends on it.** The counter test extracts its SQL from here.\n\n**Regression risk.** Medium, through that coupling. Renaming the heading or changing a fence breaks the gate.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\\\"Follow an About visit\\\": recipe prose (line 241) and caveat (line 258)\">\n**What changes.**\n- **Line 258.** Say the pageview beacon exists, point to the new subsection, and change the path to `docs/project/issues/archive/18-about-outbound-click-tracking.md`.\n- **Line 241.** It says \"The page's own API calls are new requests\". Until now the template page made none. Every view now produces a `POST /api/analytics/event` `request.start` from the visitor's `ip`, plus one per tracked click, so the 242-250 recipe always prints at least the beacon. Add one sentence.\n- **Line 254.** The caveat stays true, because the beacon does not carry the pages-log request id.\n\n**What depends on it.** Runbook readers.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a75 route prose (lines 404-410)\">\n**What changes.** Lines 404-406 say \"There is no browser-facing event publish route\". Clarify that `POST /api/analytics/event` is browser-facing and keyless, stores Client-side rows in users.db, and publishes nothing to the Engine. The keyed-route list on line 410 is unchanged.\n\n**What depends on it.** Readers of the boundary contract.\n\n**Regression risk.** Low. The line 408 phrasing \"creates at startup, so there is no migration step\" also covers the new table.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a71 users.db list (70), \u00a76 CSP (459) and prose (515, 519), rat-tail (465), X-Forwarded-For prose (523), Verify (533-541), Triage CORS row (209)\">\n**What changes.**\n- **70.** Optionally note that users.db now holds `analytics_events`, which grows without pruning and matters for backups.\n- **459, 515, 519.** No change. `script-src 'self'` and `connect-src 'self' https:` already cover the bundle and the beacon, and 519's \"template carries no `<meta>` CSP\" stays true.\n- **465.** It cites the non-existent test. Flag it; do not silently rewrite it.\n- **523.** \"Omit the lines and every visitor shares one bucket\" now also means a silent analytics undercount. Cross-reference it.\n- **533-541.** Optionally add a POST check, noting that it writes a real row.\n- **209.** The dev CORS row also covers dev beacons.\n\n**What depends on it.** Operators.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"client/README.md\" element=\"Backend Responsibilities (10-23), Boundary Contract (41), scope wording (6, 10), CLIENT_CORS_ORIGINS (71)\">\n**What changes.**\n- **New bullet** for `POST /api/analytics/event`, covering:\n  - the two types and their fields;\n  - 204/400/429;\n  - Content-Type ignored;\n  - no key needed;\n  - rows in users.db `analytics_events`;\n  - nothing IP-derived stored;\n  - no Engine publish.\n- **Line 41.** The \"write/profile\" list gets the route, or an \"analytics\" line is added.\n- **Lines 6 and 10.** \"write/profile API service\" is now slightly narrow; optionally widen it.\n- **Line 71.** Optionally add the dev beacon note.\n- **Lines 13 and 69.** Both stay true.\n\n**What depends on it.** Readers.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"client/frontend/README.md\" element=\"\\\"Local About Overrides\\\" (36-42), \\\"What it does\\\" (7-19), Boundary Contract (24)\">\n**What changes.**\n- **Overrides.** Add the module's root-absolute `<script type=\"module\" src=\"/src/...\">` tag and `data-track-id=\"<[a-z0-9_]{1,64}>\"` on each outbound link. Only http(s) links count, and middle-click and context-menu opens are not counted. An override without the tag sends nothing.\n- **\"What it does\".** Add a bullet for the About `page_view`/`outbound_click` beacons.\n- **Line 24.** Under `npm run dev`, beacons are cross-origin and need `CLIENT_CORS_ORIGINS`, and may be lost.\n\n**What depends on it.** Owners of the untracked override.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"README.md\" element=\"boundary table row (line 50)\">\n**What changes.** Line 50 lists the Client backend's browser-facing write/profile routes. Add `/api/analytics/event`, or a new row for it. The plan omits this file, but the requirement \"wherever ... lists the Client backend's public routes\" covers it.\n\n**What depends on it.** Readers.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"lines 4 and 19 (Engine does not own browser-facing write/profile routes)\">\n**What changes.** Optional. The Engine does not own `/api/analytics/event` either. Both lines stay true without an edit.\n\n**What depends on it.** Nothing.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"new **Analytics event** entry, near **Interaction event** (line 6); **Client address** (line 9) unchanged\">\n**What changes.** One line in the `- **Term** \u2014 ...` style. An analytics event:\n- has the types `outbound_click` and `page_view`;\n- is owned by the Client backend (users.db `analytics_events`) and never sent to the Engine;\n- is anonymous, with nothing derived from the address stored;\n- is distinct from an **Interaction event**.\n\nLine 9 (\"keys every rate limiter\") stays true.\n\n**What depends on it.** Domain docs.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"docs/project/issues/18-about-outbound-click-tracking.md\" element=\"Status (line 3), `## Comments`, file location\">\n**What changes.**\n- Set `Status: enhancement, complete`.\n- Append a delivery comment in the style of archive/21:31. It names the plan and the departures from the issue text:\n  - the route is `/api/analytics/event`, not `/outbound-click`;\n  - the table is `analytics_events`, not `outbound_click_events`;\n  - validation is by shape, not an allowlist (line 15);\n  - there is no `ip_hash` (line 16);\n  - the template and the override docs changed, not `client/frontend/about.html` (line 14), which does not exist.\n- The comment also names the follow-ups: the shared-connection race and the missing static-page test.\n- Move the file to `docs/project/issues/archive/` (issue-tracker.md:21).\n\n**What depends on it.** Links to the current path at DEPLOYMENT.md:258 and in plan 23.\n\n**Regression risk.** Low. Update those links in the same change. Slug-only references (archive/21:27,31, plan 22) need no change.\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"P5 row (line 42), lane 5c (line 98)\">\n**What changes.**\n- **Line 42.** \"19, 20 and 21 are delivered, and 18 remains\" becomes all four delivered.\n- **Line 98.** Mark 18 delivered, with the plan path.\n\n**What depends on it.** The tracker.\n\n**Regression risk.** None. The plan names only lane 5c, but line 42 needs the change too.\n</impact>\n<impact path=\"docs/project/issues/21-static-page-visit-logs.md\" element=\"stale non-archive duplicate of delivered issue 21\">\n**What changes.** Nothing is planned. It sits beside its `archive/` copy: issue 21's delivery recorded that it could not delete it. Its line 27 mentions 18 by slug only.\n\n**What depends on it.** Tracker hygiene.\n\n**Regression risk.** None. Mention it in the delivery notes.\n</impact>\n<impact path=\"docs/project/plans/23-18-about-outbound-click-tracking.md\" element=\"the plan document\">\n**What changes.** The workflow renders it, so do not hand-edit it. Per issue-tracker.md:29, a delivered plan moves to `docs/project/plans/archive/`, and links from plan.md:98 and the issue-18 comment must follow if it moves.\n\n**What depends on it.** Those links.\n\n**Regression risk.** Low.\n</impact>\n<impact path=\"docs/project/adr/0004-cors-opt-in-by-origin.md\" element=\"CORS opt-in decision\">\n**What changes.** Nothing. The build sends no credentials header and no `*`. The dev beacon caveat follows from this ADR, so cite it there.\n\n**What depends on it.** Nothing new.\n\n**Regression risk.** None.\n</impact>\n<impact path=\"docs/project/adr/0002-trusted-proxy-client-address.md\" element=\"client address resolution\">\n**What changes.** Nothing. The analytics limiter keys on this address, so a misconfiguration now also undercounts analytics silently.\n\n**What depends on it.** Counting accuracy.\n\n**Regression risk.** None from the code. It needs a docs caveat only.\n</impact>\n</impacts>",
  "docs_checklist": "- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: new Triage subsection \"Count About analytics events\" with ready-to-run sqlite3 queries and caveats; the About-visit caveat, users.db, section 5 and section 6 now account for `POST /api/analytics/event`.\n- [x] `client/README.md` - updated: client/README.md now covers `POST /api/analytics/event`: what it accepts and answers, where it stores events, and that it is a browser-facing Client route.\n- [x] `client/frontend/README.md` - updated: Added About analytics to `client/frontend/README.md`: what the beacon module does, the dev cross-origin caveat, and what a local override needs in order to send events.\n- [x] `README.md` - updated: I added a row for Client analytics events to the boundary contract table in `README.md`.\n- [x] `CONTEXT.md` - updated: Added an **Analytics event** glossary entry to `CONTEXT.md`, directly after **Interaction event**.\n- [x] `docs/project/issues/18-about-outbound-click-tracking.md` - updated: Issue 18 is closed as delivered: its status is `enhancement, complete`, it has a delivery comment, and a copy now sits in `archive/`. The old file is still in place because I have no way to delete files.\n- [x] `docs/project/issues/plan.md` - updated: I updated `docs/project/issues/plan.md` to show issue 18 as delivered, in both the P5 priority row and the wave 5 lane 5c row.\n- [x] `.un/skills/devsecops/config.json` - out of scope: Not a prose document, and the harvest turn owns it: it rewrites the group map when it promotes the phase checkpoints. The durable `tests/active/test_analytics_events.py` does not exist yet (every phase and the refactor pass record this), so there is no file to map a `test_groups` entry to. The new group belongs in the harvest, along with the note that the existing `test_static_page_visit_logs.py` group (lines 263-268) points at a missing file.\n- [x] `docs/project/plans/23-18-about-outbound-click-tracking.md` - out of scope: The workflow renders this plan, so it is not hand-edited here. Its link to issue 18's current path is handled when the workflow archives the plan, per issue-tracker.md:29.\n- [x] `docs/project/issues/archive/21-static-page-visit-logs.md` - out of scope: - **Line 27.** Refers to 18 by slug only, and that stays correct.\n- [x] `docs/project/issues/21-static-page-visit-logs.md` - out of scope: - This is the stale non-archive duplicate. It mentions 18 by slug only (line 27), which stays correct.\n- [x] `engine/server/README.md` - out of scope: Lines 4 and 18-19 say the Engine owns read/analytics APIs and no browser-facing write/profile routes. Both stay true: `/api/analytics/event` belongs to the Client backend, and \"analytics\" there means Engine read analytics.\n- [x] `docs/project/adr/0002-trusted-proxy-client-address.md` - out of scope: The analytics route resolves the client address through the existing `_rate_limit_check` \u2192 `_get_client_ip` path, as the ADR decides. The only consequence (a misconfigured proxy now also undercounts analytics) is a caveat for DEPLOYMENT.md, not an amendment.\n- [x] `docs/project/adr/0004-cors-opt-in-by-origin.md` - out of scope: The build adds no CORS headers, no credentials header and no `*`, so origin opt-in is unchanged. The possible loss of dev cross-origin beacons follows from this ADR and is documented as a caveat in DEPLOYMENT.md and client/frontend/README.md.\n- [x] `docs/project/adr/0005-raw-event-retention-keeps-ids.md` - out of scope: - Its scope is the Engine's `interaction_raw_events`.",
  "docs": [
    {
      "path": "DEPLOYMENT.md",
      "note": "- **New Triage subsection \"Count About analytics events\"**, between \"Follow an About visit\" and \"Follow one request\". It holds:\n  - the `sqlite3 -readonly` invocation;\n  - fenced `sql` blocks for total and daily (UTC) clicks per `track_id`, total and daily `page_view` (optionally per `page_path`), and the bot-filter variants;\n  - its caveats: forgeable within 90/min per address, unbounded retention, a heuristic UA filter, reduced Referer, middle-click and context-menu not counted, non-http(s) links rejected, a shared or misresolved address undercounts, and dev cross-origin beacons may be lost.\n- **Line 241.** One sentence: each About view now produces its own beacon `request.start`.\n- **Line 258.** The beacon exists; point to the new subsection and change the issue path to `archive/`.\n- **Lines 404-406.** The new keyless browser-facing route, which publishes nothing to the Engine.\n- **Optional.**\n  - 70: users.db holds `analytics_events` and grows unpruned;\n  - 523: cross-reference to the undercount;\n  - Verify: a POST that writes a row.\n- **Line 465.** Flag that it names the non-existent `tests/active/test_static_page_visit_logs.py`."
    },
    {
      "path": "client/README.md",
      "note": "- **Backend Responsibilities.** A new bullet for `POST /api/analytics/event`, covering:\n  - the two types and their fields;\n  - 204/400/429;\n  - Content-Type ignored;\n  - no key needed;\n  - users.db `analytics_events`;\n  - nothing IP-derived stored;\n  - no Engine publish.\n- **Boundary Contract, line 41.** Add the route.\n- **Optional.** Widen lines 6 and 10, and add a dev beacon note at line 71."
    },
    {
      "path": "client/frontend/README.md",
      "note": "- **\"Local About Overrides\".**\n  - the module's root-absolute script tag;\n  - the `data-track-id` convention (`[a-z0-9_]{1,64}`);\n  - only http(s) links count, and middle-click and context-menu opens do not;\n  - an override without the tag sends nothing.\n- **\"What it does\".** A bullet for the About beacons.\n- **Line 24.** Under `npm run dev`, beacons are cross-origin, need `CLIENT_CORS_ORIGINS`, and may be lost."
    },
    {
      "path": "README.md",
      "note": "Line 50 boundary table: add `/api/analytics/event` to the Client backend's browser-facing routes, or add a row for it."
    },
    {
      "path": "CONTEXT.md",
      "note": "A new **Analytics event** entry:\n- the two types;\n- owned by the Client backend in users.db, never sent to the Engine;\n- anonymous;\n- distinct from an **Interaction event**."
    },
    {
      "path": "docs/project/issues/18-about-outbound-click-tracking.md",
      "note": "- Set `Status: enhancement, complete`.\n- Add a delivery comment that names the plan and the departures from the issue text: the route, the table, no allowlist, no ip_hash, and the template plus override docs rather than `about.html`.\n- Name the follow-ups: the shared-connection race and the missing static-page test with its config.json group.\n- Note that prod gets the beacon only after the next `scripts/sync.sh`.\n- Move the file to `docs/project/issues/archive/` and update the link at DEPLOYMENT.md:258."
    },
    {
      "path": "docs/project/issues/plan.md",
      "note": "- Line 42 (P5 row): mark 18 delivered.\n- Line 98 (lane 5c): mark 18 delivered and give the plan path."
    },
    {
      "path": ".un/skills/devsecops/config.json",
      "note": "- Add a `test_groups` entry for each new test file, mapping it to:\n  - `server.py`\n  - `users_store.py`\n  - `http_utils.py`\n  - the new frontend module\n  - `api-base.ts`\n  - `about.template.html`\n  - `vite.config.ts`\n  - `DEPLOYMENT.md`\n- Note that the existing `test_static_page_visit_logs.py` group points at a missing file."
    }
  ],
  "reassessments": 3,
  "draft": "## Draft: About analytics events (issue 18)\n\nBefore writing this I read: `server.py` (imports, constants, the `_run_request` / `_serve_post` / `_rate_limit_check` handler methods, `_handle_likes_import`, `_read_block_body`, `_parse_client_likes`), `lib/users_store.py`, `src/data/api-base.ts`, `src/data/user-actions.ts`, `dev-pages/about.template.html`, `videos.html`, `vite.config.ts`, `tests/active/conftest.py`, the `test_server.py` server helpers, `test_frontend_profile.py`, DEPLOYMENT.md 228-263, archive issue 21 and the `config.json` test groups.\n\n**Template defect.** The step's \"ladder the draft is written against\" arrived as the literal placeholder `{rat_tail_ladder}`. No ladder was rendered, so this draft is checked against the high-level plan, the requirements, the settled impacts and the settled doc list only.\n\n### What the build must prove (test inventory first)\n\n1. **Valid events.** A valid `outbound_click` and a valid `page_view` (with `track_id`/`href` either absent or `null`) each answer 204 with an empty body and add exactly one row.\n   - `created_at` falls between the server `now_ms()` readings taken before and after the request. It is not the client `timestamp`.\n   - `user_agent` and `referer` are copied from the headers. Empty or absent values are stored as NULL.\n2. **Content-Type is ignored.** A `text/plain` body carrying a valid event gets 204.\n3. **Exact schema.** `PRAGMA table_info(analytics_events)` returns exactly `id, type, track_id, href, page_path, created_at, user_agent, referer`, so no IP-derived column exists.\n4. **Invalid bodies.** Every invalid body gets 400 with a JSON `error` and leaves zero rows. That includes bodies that would crash a naive validator (unhashable `type`, lone surrogates, a malformed IPv6 host).\n5. **Rate limit.** Under the production limiter (90/60 s), the 91st POST from one address gets 429 and the row count stays at 90.\n6. **Unknown method.** `GET /api/analytics/event` gets 404.\n7. **Counting queries.** The SQL blocks taken from DEPLOYMENT.md's new subsection, run read-only against the fixture DB, return the expected counts after N posted clicks and views.\n8. **Browser behaviour (node).**\n   - Import sends exactly one `page_view`.\n   - A tracked click sends one correct `outbound_click`.\n   - An untracked click, or a click on a Text node, sends nothing.\n   - `fetch` with `keepalive` is used when `sendBeacon` is missing, returns false, or throws.\n   - No unhandled rejection occurs when `fetch` rejects.\n9. **Built page.** A real `vite build` of the template references a bundled `/assets/*.js` entry that contains `/api/analytics/event`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `client/backend/server.py` | imports `re` and `urlsplit`; imports `insert_analytics_event`; 4 constants; one `_serve_post` branch; `_handle_analytics_event` method; module functions `_validate_analytics_event`, `_analytics_href_ok`, `_utf8_safe` |\n| `client/backend/lib/users_store.py` | table + index in `ensure_user_schema` and its docstring; new `insert_analytics_event` |\n| `client/frontend/src/about-analytics.ts` | new module (whole file below) |\n| `client/frontend/dev-pages/about.template.html` | one script tag |\n| `tests/active/test_analytics_events.py` | new gating file (backend, counter, node, vite build) |\n| `.un/skills/devsecops/config.json` | one `test_groups` entry |\n| docs | DEPLOYMENT.md, client/README.md, client/frontend/README.md, README.md, CONTEXT.md, issue 18 (moved to archive), plan.md, two new follow-up issues 42 and 43 |\n\n**Placement decision.** The impacts asked for the module's location to be decided at design. It stays at `src/about-analytics.ts`, as every settled impact and doc entry names it.\n- It is not a page entry: About has no page logic, so `src/pages/about/index.ts` would claim a convention that doesn't apply.\n- Keeping it means the template tag, the README, the test and config.json all name one path.\n\n### Backend: `client/backend/server.py`\n\n**Imports.**\n- `import re` is added between `import random` and `import signal`.\n- Line 20 becomes `from urllib.parse import parse_qs, urlencode, urlparse, urlsplit`.\n- The users_store import block becomes:\n```python\nfrom lib.users_store import (clear_likes, close_like, ensure_user_schema, fetch_recent_likes,\n                             get_or_create_user, insert_analytics_event, load_liked_keys,\n                             record_like, remove_like, video_reaction)\n```\n\n**Constants.** These go after `BLOCK_REFERENCE_MAX_LENGTH = 200`:\n```python\nANALYTICS_EVENT_TYPES = frozenset((\"outbound_click\", \"page_view\"))\n# fullmatch only: `$` would accept a trailing newline.\nANALYTICS_TRACK_ID_PATTERN = re.compile(r\"[a-z0-9_]{1,64}\")\nANALYTICS_HREF_MAX_LENGTH = 2048\nANALYTICS_PAGE_PATH_MAX_LENGTH = 256\n```\n\n**Route.** The new branch goes in `_serve_post`, after the blocks branch and before the `/client/events/publish` comment and the final 404:\n```python\n        if url.path == \"/api/analytics/event\":\n            if not self._rate_limit_check(url.path):\n                respond_json(self, 429, {\"error\": \"Rate limit exceeded\"})\n                return\n            self._handle_analytics_event()\n            return\n```\n- The rate-limit check runs before any parsing.\n- The limiter key is `<ip>:/api/analytics/event`, so analytics gets its own 90/min bucket.\n\n**Handler method.** It sits next to `_handle_likes_import`:\n```python\n    def _handle_analytics_event(self) -> None:\n        \"\"\"Store one About page analytics event; the client address is never stored, only rate-limited on.\"\"\"\n        try:\n            body = read_json_body(self)\n        except ValueError as exc:\n            respond_json(self, 400, {\"error\": str(exc)})\n            return\n        event = _validate_analytics_event(body)\n        if isinstance(event, str):\n            respond_json(self, 400, {\"error\": event})\n            return\n        event_type, track_id, href, page_path = event\n        user_agent = self.headers.get(\"User-Agent\", \"\").strip() or None\n        referer = self.headers.get(\"Referer\", \"\").strip() or None\n        with self.server.user_db:\n            insert_analytics_event(self.server.user_db, event_type, track_id, href, page_path, now_ms(), user_agent, referer)\n        respond_bytes(self, 204, b\"\")\n```\n- **Content-Type.** Never read, because `read_json_body` ignores it.\n- **Empty body.** It parses to `{}` and fails on `type`, so it gets 400.\n- **Errors from `read_json_body`.** It raises `ValueError` for invalid JSON, a non-object body, non-UTF-8 bytes (`UnicodeDecodeError`), and a bad or over-1 MB length. Each becomes 400.\n- **Headers.** They arrive latin-1 decoded, so they always bind in SQLite.\n- **One clock read.** `now_ms()` is read exactly once per row.\n\n**Validator.** These are module-level functions placed after `_parse_client_likes`. They are pure and never raise on any JSON-decoded dict.\n```python\ndef _validate_analytics_event(body: dict[str, Any]) -> tuple[str, str | None, str | None, str] | str:\n    \"\"\"Handle validate analytics event.\n\n    :returns: `(type, track_id, href, page_path)` to store, or the error message for a 400.\n    \"\"\"\n    event_type = body.get(\"type\")\n    # Checked as a str first: a list or dict `type` is unhashable and would raise in the set lookup.\n    if not isinstance(event_type, str) or event_type not in ANALYTICS_EVENT_TYPES:\n        return \"type must be outbound_click or page_view\"\n    page_path = body.get(\"page_path\")\n    if (not isinstance(page_path, str) or not 1 <= len(page_path) <= ANALYTICS_PAGE_PATH_MAX_LENGTH\n            or not page_path.startswith(\"/\") or not _utf8_safe(page_path)):\n        return \"page_path must be a path of 1 to 256 characters starting with /\"\n    timestamp = body.get(\"timestamp\")\n    # bool is an int subclass; a JSON 1.0 arrives as float and is rejected too. Checked, then discarded.\n    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0:\n        return \"timestamp must be a non-negative integer\"\n    track_id = body.get(\"track_id\")\n    href = body.get(\"href\")\n    if event_type == \"page_view\":\n        if track_id is not None or href is not None:\n            return \"page_view takes no track_id or href\"\n        return event_type, None, None, page_path\n    if not isinstance(track_id, str) or not ANALYTICS_TRACK_ID_PATTERN.fullmatch(track_id):\n        return \"track_id must match [a-z0-9_]{1,64}\"\n    if not _analytics_href_ok(href):\n        return \"href must be an absolute http or https URL of at most 2048 characters\"\n    return event_type, track_id, href, page_path\n\n\ndef _analytics_href_ok(href: Any) -> bool:\n    \"\"\"Return whether `href` is an absolute http(s) URL with a host, short enough and storable.\"\"\"\n    if not isinstance(href, str) or len(href) > ANALYTICS_HREF_MAX_LENGTH or not _utf8_safe(href):\n        return False\n    try:\n        # `.hostname` re-parses the netloc and can raise on a malformed bracketed host, so it sits inside the try.\n        parts = urlsplit(href)\n        hostname = parts.hostname\n    except ValueError:\n        return False\n    return parts.scheme in (\"http\", \"https\") and bool(hostname)\n\n\ndef _utf8_safe(value: str) -> bool:\n    \"\"\"Return whether `value` encodes as UTF-8; a JSON lone surrogate decodes to a str sqlite3 cannot bind.\"\"\"\n    try:\n        value.encode(\"utf-8\")\n    except UnicodeEncodeError:\n        return False\n    return True\n```\n\nInvariants:\n- **Return shape.** The result is either a 4-tuple whose values are safe to bind, or an error string.\n- **`track_id` encoding.** It needs no UTF-8 check because its regex is ASCII-only.\n- **Scheme case.** `urlsplit` lowercases the scheme, so `HTTPS://x.y` passes.\n- **Rejected `href` shapes.** `https://` (hostname None), `http://[::1` (ValueError), `mailto:` and `/relative` all fail.\n- **`page_path` is stored verbatim.** `//host` passes, which is acceptable because the value is never followed.\n- **Known looseness.** `urlsplit` silently drops tab and newline characters when it parses, so an `href` containing them passes and is stored verbatim. Browsers never produce such a resolved `href`. There is no extra rule because the spec does not ask for one.\n\n### Storage: `client/backend/lib/users_store.py`\n\n**Docstring.** Line 11 becomes `\"\"\"Create the users, likes, like generation, profile, block, dislike and analytics event tables if missing.\"\"\"`.\n\n**Schema.** Inserted after the `like_generations` table and before the `-- Every visitor's actions\u2026` cleanup:\n```sql\n        CREATE TABLE IF NOT EXISTS analytics_events (\n          id INTEGER PRIMARY KEY,\n          type TEXT NOT NULL CHECK (type IN ('outbound_click', 'page_view')),\n          track_id TEXT,\n          href TEXT,\n          page_path TEXT NOT NULL,\n          created_at INTEGER NOT NULL,\n          user_agent TEXT,\n          referer TEXT\n        );\n        CREATE INDEX IF NOT EXISTS analytics_events_type_track_created_idx\n          ON analytics_events (type, track_id, created_at);\n```\n\n**Insert function.** New, placed after `video_reaction`. It does not commit: the handler's `with self.server.user_db:` owns the transaction, following `remove_like`/`close_like`.\n```python\ndef insert_analytics_event(conn: sqlite3.Connection, event_type: str, track_id: str | None, href: str | None,\n                           page_path: str, created_at: int, user_agent: str | None, referer: str | None) -> None:\n    \"\"\"Insert one analytics event, inside the caller's transaction.\"\"\"\n    conn.execute(\n        \"INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES (?, ?, ?, ?, ?, ?, ?)\",\n        (event_type, track_id, href, page_path, created_at, user_agent, referer),\n    )\n```\n\n**Startup.** No edit: `server.py:1311` already calls `ensure_user_schema`, so existing DBs gain the table on restart.\n\n### Frontend: `client/frontend/src/about-analytics.ts`\n\n```ts\n/**\n * Module `client/frontend/src/about-analytics.ts`: send the About page's analytics events (one page view, one event per tracked outbound click).\n */\n\nimport { resolveClientApiBase } from \"./data/api-base\";\n\ntype AnalyticsEvent =\n  | { type: \"page_view\"; page_path: string; timestamp: number }\n  | { type: \"outbound_click\"; track_id: string; href: string; page_path: string; timestamp: number };\n\n/**\n * Handle send analytics event. Never throws and never rejects: analytics must not surface to the visitor.\n */\nfunction sendAnalyticsEvent(event: AnalyticsEvent): void {\n  try {\n    // No argument, so `?api=` is never read; built with `new URL` like every sibling, so a base ending in `/` gives no `//api`.\n    const url = new URL(\"/api/analytics/event\", resolveClientApiBase()).toString();\n    const body = JSON.stringify(event);\n    try {\n      // Called on `navigator` itself: a detached reference throws \"Illegal invocation\".\n      if (typeof navigator !== \"undefined\" && typeof navigator.sendBeacon === \"function\"\n        && navigator.sendBeacon(url, new Blob([body], { type: \"application/json\" }))) {\n        return;\n      }\n    } catch {\n      // A refused cross-origin beacon can throw; fetch gets one more try.\n    }\n    fetch(url, { method: \"POST\", body, headers: { \"Content-Type\": \"application/json\" }, keepalive: true }).catch(() => undefined);\n  } catch {\n    // A bad base, a missing fetch or an over-64 KiB keepalive body throws synchronously; swallowed.\n  }\n}\n\n/**\n * Handle document click: one outbound_click per click that resolves to an `a[data-track-id]`.\n */\nfunction handleDocumentClick(event: Event): void {\n  const target = event.target as Element | null;\n  // A Text node or the document itself has no `closest`.\n  if (!target || typeof target.closest !== \"function\") {\n    return;\n  }\n  const link = target.closest(\"a[data-track-id]\");\n  if (!link) {\n    return;\n  }\n  // An SVG <a>'s `href` is an SVGAnimatedString; the server would reject it, so nothing is sent.\n  const href = (link as HTMLAnchorElement).href;\n  if (typeof href !== \"string\") {\n    return;\n  }\n  sendAnalyticsEvent({\n    type: \"outbound_click\",\n    track_id: link.getAttribute(\"data-track-id\") ?? \"\",\n    href,\n    page_path: window.location.pathname,\n    timestamp: Date.now()\n  });\n}\n\nsendAnalyticsEvent({ type: \"page_view\", page_path: window.location.pathname, timestamp: Date.now() });\ndocument.addEventListener(\"click\", handleDocumentClick);\n```\n- **No exports.** The module acts on import. A module script is deferred, so `document` is parsed by the time it runs and there is no DOMContentLoaded wait.\n- **No `preventDefault`,** so navigation is untouched.\n- **A malformed `data-track-id`** (for example uppercase) is still sent and gets 400. That is the shape-validation contract, and the README documents the pattern.\n- **Gateway scan.** There is no Engine base, no `127.0.0.1:707x` literal and no `/internal/` path, so `check-frontend-client-gateway.sh` passes.\n\n### Template: `client/frontend/dev-pages/about.template.html`\n\nOne line goes before `</body>`, as in `videos.html:65`:\n```html\n    <script type=\"module\" src=\"/src/about-analytics.ts\"></script>\n```\nNo About URL or dev-pages filename changes.\n\n### Tests: `tests/active/test_analytics_events.py`\n\nOne file holds everything, so one config.json group maps it to all eight settled paths (the \"fewest files\" choice).\n\n**Constants and helpers:**\n- `FRONTEND`, `ESBUILD` and `VITE` (`node_modules/.bin/vite`).\n- `_post(base, raw: bytes, headers: dict) -> (status, body)` over raw `urllib.request`. This is needed for `text/plain`, invalid JSON, non-UTF-8 and custom/empty UA. Setting `User-Agent: \"\"` overrides urllib's default.\n- `_rows(db_path)` reads all rows as dicts.\n- `_event(**overrides)` builds a valid click body.\n- `_serving_limited(tmp_path)` is a contextmanager. It builds `ClientBackendServer` exactly as conftest does, but with `RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS)`.\n\n**Backend tests (they use the conftest `client_backend` fixture unless stated):**\n- `test_outbound_click_stores_one_row`:\n  - Setup: take `before = now_ms()`, then POST a click with `timestamp: 1`, `User-Agent: Mozilla/5.0 analytics-test`, `Referer: https://example.org/about`.\n  - Expect a 204 with an empty body.\n  - Expect exactly one row with the expected `type`, `track_id`, `href` and `page_path`, `before <= created_at <= now_ms()`, `created_at != 1`, and UA and Referer equal to the headers.\n- `test_page_view_stores_one_row`: parametrized over `track_id`/`href` absent vs explicit `null`. Expect 204, one row with NULL `track_id` and `href`.\n- `test_text_plain_beacon_accepted`: send `Content-Type: text/plain;charset=UTF-8`. Expect 204 and one row.\n- `test_missing_headers_store_null`: send `User-Agent: \"\"` and no Referer. Both columns are NULL.\n- `test_schema_has_no_address_column`: the `PRAGMA table_info` names equal the exact 8-column list.\n- `test_invalid_event_rejected` is parametrized over raw bodies. Each case expects 400, a JSON `error` key and zero rows. Status is asserted, not message text. The cases:\n  - **body:** `b\"\"`, `b\"{\"`, `b\"[]\"`, `b\"\\xff\"`;\n  - **type:** missing, `\"click\"`, `[\"page_view\"]`;\n  - **track_id:** missing on a click, `null` on a click, `\"About_Patreon\"`, `\"\"`, 65\u00d7`a`, `\"a-b\"`, `\"abc\\n\"`, `5`;\n  - **href:** missing, `\"mailto:a@b.c\"`, `\"javascript:alert(1)\"`, `\"https://\"`, `\"/relative\"`, `\"http://[::1\"`, `\"https://x.y/\" + \"a\"*2040`, `42`, `json.dumps(\"https://x.y/\\ud800\")`;\n  - **page_path:** missing, `\"\"`, `\"about\"`, `\"/\" + \"a\"*256`, `7`, `\"/\\ud800\"`;\n  - **timestamp:** missing, `\"1\"`, `1.0`, `true`, `-1`, `null`;\n  - **page_view:** with `track_id: \"about_x\"`, and with `href: \"https://x.y\"`.\n- `test_get_is_not_a_route`: `GET` gives 404.\n- `test_rate_limit_rejects_and_stores_nothing`: uses `_serving_limited`, with `X-Forwarded-For: 203.0.113.18` (127.0.0.1 is a trusted proxy by default). 90 valid posts each give 204. The 91st gives 429 with `{\"error\": \"Rate limit exceeded\"}`, and the row count is 90.\n\n**Counter test (`test_documented_queries_count_events`):**\n- **Extraction.**\n  - The DEPLOYMENT.md text is sliced from `### Count About analytics events` to the next `\\n### `.\n  - Blocks are found with `re.findall(r\"```sql\\n(.*?)```\", section, re.S)`.\n  - The test asserts `len(blocks) == 7`, so the extraction can't pass vacuously.\n- **Posted events:**\n  - 3 clicks `about_test`;\n  - 1 click `about_other`;\n  - 1 click `about_test` with UA `Googlebot/2.1`;\n  - 1 click `about_test` with empty UA;\n  - page views: 2 on `/about` and 1 on `/about.html`, plus 1 on `/about` with UA `bingbot`.\n- **Connection.** The DB is opened with `sqlite3.connect(f\"file:{db}?mode=ro\", uri=True)`, matching `-readonly`.\n- **Expected results.** `day` is computed from the stored `created_at` rather than from the wall clock, so the test is midnight-safe. Each block in order must return:\n  1. `{about_test: 5, about_other: 1}`\n  2. `[(day, about_other, 1), (day, about_test, 5)]`\n  3. `4`\n  4. `[(day, 4)]`\n  5. `{/about: 3, /about.html: 1}`\n  6. `{about_test: 3, about_other: 1}`\n  7. `[(day, 3)]`\n- The clicks for one `track_id` are counted, which is the counter acceptance criterion.\n\n**Node test (`test_beacon_dispatch`):**\n- **Bundling.** `src/about-analytics.ts` is bundled with esbuild using `--define:import.meta.env.VITE_CLIENT_API_BASE=\"http://api.test/\"` (trailing slash on purpose) and `--define:import.meta.env.DEV=false`.\n- **Runner stubs, all installed before `await import(BUNDLE)`:**\n  - `globalThis.window = {location: {origin: \"http://page.test\", pathname: \"/about\"}}`;\n  - `Object.defineProperty(globalThis, \"navigator\", {value: {...}, configurable: true})`, with `sendBeacon` per `MODE`: `true` returns true, `false` returns false, `missing` is undefined, `throws` throws;\n  - `globalThis.document = {addEventListener: (t, h) => handlers.push([t, h])}`;\n  - `globalThis.fetch` records the call and returns `Promise.reject(new Error(\"offline\"))`;\n  - a `process.on(\"unhandledRejection\")` counter.\n- **Runner actions.** After the import, the runner:\n  - dispatches the captured click handler with three targets: a tracked target whose `closest` returns `{href: \"https://www.patreon.com/x\", getAttribute: () => \"about_patreon\"}`, an untracked target whose `closest` returns null, and a Text-like `{}`;\n  - awaits `blob.text()` for each beacon and lets microtasks drain;\n  - prints JSON of `{sent: [{via, url, body, keepalive, contentType}], rejections}`.\n- **Assertions,** parametrized over the four MODEs:\n  - exactly 2 sends;\n  - every `url == \"http://api.test/api/analytics/event\"`;\n  - the first is `page_view` with `page_path \"/about\"` and an int `timestamp`;\n  - the second is `outbound_click` with `about_patreon`, the href, `/about` and an int `timestamp`;\n  - `via` is `beacon` only in mode `true`, otherwise `fetch` with `keepalive: true` and `Content-Type: application/json`;\n  - `rejections == 0`;\n  - exactly one `click` listener is installed.\n\n**Built-page test (`test_built_about_page_bundles_beacon`):**\n- **Skip.** It runs `pytest.skip` with a reason when `FRONTEND / \"dev-pages/about.html\"` exists, because a local override would be built instead of the template.\n- **Build.** `[VITE, \"build\", \"--outDir\", str(tmp_path / \"dist\"), \"--emptyOutDir\"]` runs with `cwd=FRONTEND`, an env without `VITE_CLIENT_API_BASE`, and `timeout=300`. It never writes into `client/frontend/dist` or `tests/tmp`.\n- **Assertions.**\n  - `dist/dev-pages/about.template.html` contains a `src=\"(/assets/[^\"]+\\.js)\"` script.\n  - That entry file contains `/api/analytics/event`. The literal lives in the module, which is the About entry chunk, while `api-base` may be split into a shared chunk.\n\n### `.un/skills/devsecops/config.json`\n\nA new entry is added before `test_static_page_visit_logs.py`. That existing entry is left in place and flagged in issue 43.\n```json\n    \"test_analytics_events.py\": [\n      \"client/backend/server.py\",\n      \"client/backend/lib/users_store.py\",\n      \"client/backend/lib/http_utils.py\",\n      \"client/frontend/src/about-analytics.ts\",\n      \"client/frontend/src/data/api-base.ts\",\n      \"client/frontend/dev-pages/about.template.html\",\n      \"client/frontend/vite.config.ts\",\n      \"DEPLOYMENT.md\"\n    ],\n```\n\n### Docs (content drafted, one paragraph per line in the files)\n\n**DEPLOYMENT.md, new `### Count About analytics events`.** It goes between \"Follow an About visit\" and \"Follow one request\".\n- **Lead paragraph.** The About page's own script sends a `page_view` per load and an `outbound_click` per click on an `a[data-track-id]` to `POST /api/analytics/event`. The Client backend stores each as one row of `analytics_events` in `users.db`, with server time in `created_at` (epoch ms), `user_agent` and `referer`, and no address. The queries below count them.\n- **Invocation.** `sudo sqlite3 -readonly <root>/client/backend/db/users.db`.\n- **The seven `sql` blocks,** one statement each and in this order. The order is pinned by the counter test.\n  1. `SELECT track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' GROUP BY track_id ORDER BY clicks DESC;`\n  2. `SELECT date(created_at / 1000, 'unixepoch') AS day, track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' GROUP BY day, track_id ORDER BY day, track_id;`\n  3. `SELECT COUNT(*) AS views FROM analytics_events WHERE type = 'page_view';`\n  4. `SELECT date(created_at / 1000, 'unixepoch') AS day, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY day ORDER BY day;`\n  5. `SELECT page_path, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY page_path ORDER BY views DESC;`\n  6. Block 1 with `AND user_agent IS NOT NULL AND user_agent NOT LIKE '%bot%' AND user_agent NOT LIKE '%crawl%' AND user_agent NOT LIKE '%spider%'` added to the `WHERE`.\n  7. Block 4 with the same filter.\n- **Prose around the blocks.**\n  - Days are UTC.\n  - Add `page_path` to block 4's SELECT and GROUP BY to split daily views by path.\n  - Add the four filter conditions to any query to exclude obvious bots. `LIKE` is ASCII case-insensitive.\n- **Caveats** (one bullet each):\n  - **Forgeable counts.** The endpoint is anonymous and accepts up to 90 per minute per address.\n  - **Unbounded retention.** Rows are never pruned, so `users.db` grows. It matters for backups.\n  - **The UA filter is a heuristic.** It removes honest crawlers only.\n  - **Referer is often reduced** to the About URL by the default referrer policy.\n  - **Clicks not counted.** Middle-click and context-menu \"open in new tab\" are not counted. Ctrl/Cmd-click and keyboard activation are.\n  - **Non-http(s) tracked links** (`mailto:`, `tel:`) are rejected and never counted.\n  - **Silent undercount.** A shared or misresolved client address caps a whole population at 90/min. `sendBeacon` never sees the 429. See `TRUSTED_PROXIES`, ADR-0002 and section 6's `X-Forwarded-For` lines.\n  - **Dev beacons may be lost.** Under `npm run dev` the API base is cross-origin. A credentialed `application/json` beacon's preflight gets no `Access-Control-Allow-Credentials` (ADR-0004), so dev beacons may be lost.\n  - **Shared connection.** Analytics writes share the single unlocked `users.db` connection with profile writes (issue 42).\n  - **Prod rollout.** Prod sends nothing until `scripts/sync.sh` rebuilds `dist/`.\n\n**DEPLOYMENT.md, edits elsewhere:**\n- **241.** Append: \"Every About view now also makes one `POST /api/analytics/event` (and one per tracked click), so the window always shows at least that beacon's `request.start`.\"\n- **258.** Second sentence becomes: \"Counting human visits uses the page's own pageview beacon: see \"Count About analytics events\" and `docs/project/issues/archive/18-about-outbound-click-tracking.md`.\"\n- **404-406.** Add: \"`POST /api/analytics/event` is browser-facing and needs no key: it stores About analytics rows in the Client's `users.db` and publishes nothing to the Engine.\"\n- **465.** Add a parenthesis to the rat-tail comment: \"(`tests/active/test_static_page_visit_logs.py` does not exist yet; issue 43)\".\n- **Optional lines taken:**\n  - **70:** \"`analytics_events`, unpruned\".\n  - **523:** \"\u2026and About analytics undercounts silently\".\n- **Skipped as optional.** The Verify POST is left out, because it would write a real row into prod `users.db`.\n\n**client/README.md:**\n- **New Backend Responsibilities bullet:** \"`POST /api/analytics/event`: anonymous About analytics. Body `{type: \"page_view\", page_path, timestamp}` or `{type: \"outbound_click\", track_id, href, page_path, timestamp}`. Answers 204, 400 on any invalid field, 429 over the route limit. Content-Type is ignored and no profile key is needed. One row per event in `users.db` `analytics_events`. Nothing derived from the client address is stored, and nothing is published to the Engine.\"\n- **Line 41.** The route list gains `/api/analytics/event`.\n- **Line 71.** Gains: \"also needed for dev About beacons, which may still be lost (credentialed beacon).\"\n\n**client/frontend/README.md:**\n- **\"What it does\"** gains a bullet: \"About sends one anonymous `page_view` per load and one `outbound_click` per click on an `a[data-track-id]` link to the Client backend (`src/about-analytics.ts`).\"\n- **\"Local About Overrides\"** gains a paragraph. An override adds `<script type=\"module\" src=\"/src/about-analytics.ts\"></script>` (root-absolute, like the stylesheet) and `data-track-id=\"about_<name>\"` on each outbound link to count, matching `[a-z0-9_]{1,64}`. The paragraph also says:\n  - only http(s) links count;\n  - middle-click and context-menu opens are not counted;\n  - an override without the tag sends nothing, not even page views.\n- **Line 24.** Gains the dev cross-origin note: needs `CLIENT_CORS_ORIGINS`, may be lost.\n\n**README.md line 50.** `/api/analytics/event` is added to the Client backend's browser-facing routes cell.\n\n**CONTEXT.md, after Interaction event:** \"- **Analytics event** \u2014 an anonymous `page_view` or `outbound_click` the About page's own script sends to the Client backend, which stores it in `users.db` `analytics_events` with nothing derived from the client address and never sends it to the Engine; unlike an **Interaction event**, it does not feed ranking.\"\n\n**Issue 18:**\n- `Status: enhancement, complete`.\n- `git mv` to `docs/project/issues/archive/`.\n- A comment in the style of archive/21:31, covering:\n  - which plan delivered it;\n  - the route and table names chosen, and that no allowlist or `ip_hash` was used;\n  - that the template and override docs changed, not the non-existent `client/frontend/about.html`;\n  - the follow-ups, issues 42 and 43;\n  - that prod beacons start after the next `scripts/sync.sh`;\n  - that the stale non-archive `21-static-page-visit-logs.md` duplicate remains.\n\nDraft wording:\n> Delivered by `docs/project/plans/23-18-about-outbound-click-tracking.md`, as one route `POST /api/analytics/event` for both `page_view` and `outbound_click` (not `/outbound-click`), one table `analytics_events` (not `outbound_click_events`), shape validation instead of an allowlist (the real About page is an untracked override), and no `ip_hash` or other address-derived value. The tracked template `dev-pages/about.template.html` and the override docs changed; `client/frontend/about.html` does not exist. Counts are queried with the \"Count About analytics events\" runbook in `DEPLOYMENT.md`. Prod sends nothing until the next `scripts/sync.sh`. Follow-ups: `42-users-db-shared-connection-race`, `43-static-page-visit-logs-test-missing`. The stale `docs/project/issues/21-static-page-visit-logs.md` duplicate is still beside its archive copy.\n\n**plan.md:**\n- **Line 42.** \"19, 20, 21 and 18 are delivered\".\n- **Line 98.** \"18 delivered by `docs/project/plans/23-18-about-outbound-click-tracking.md`\". The plan document itself is workflow-rendered and not hand-edited. If it moves to `plans/archive/`, this link and the issue comment follow.\n\n**New follow-up issues (`Status: bug, needs-triage`):**\n- **`42-users-db-shared-connection-race.md`.** One `check_same_thread=False` connection is shared by all handler threads without a lock. A `with conn:` on one thread commits or rolls back another's transaction. The anonymous analytics route raises the write rate. Fix with a write lock or per-thread connections.\n- **`43-static-page-visit-logs-test-missing.md`.** Issue 21's guard `tests/active/test_static_page_visit_logs.py` was never written. It is still cited at DEPLOYMENT.md:465 and config.json:263.\n\n### Check against plan and requirements\n\n**Pass 1 found and fixed these gaps:**\n- **Unhashable `type`.** `type` as a list raised `TypeError` in the frozenset lookup, which drops the connection. It is now checked as a str first.\n- **SVG links.** An SVG link sent a non-string `href`. It now sends nothing.\n- **Missing `navigator`.** A missing `navigator` threw before the fallback. It is now guarded.\n- **Rate-limit fixture.** The rate-limit test could not use the fixture's 1000/60 limiter, so it has its own server.\n- **Header in a test.** One test also needed an empty UA header.\n\n**Pass 2: every requirement maps to code or a test:**\n- **Endpoint.** Route, 204/400/429, Content-Type ignored, `_run_request` wrapping, GET 404.\n- **Validation.** Every validation rule and the unknown-keys rule.\n- **Schema and storage.** Exact schema, CHECK and index, created at startup, `now_ms`, UA/Referer\u2192NULL, no address, one row per request, no pruning.\n- **Frontend.** Module behaviour, transport and fallback, swallowed failures, Client API base, template tag, override docs.\n- **Docs and tracker.** Reporting queries including the bot filter, doc route lists, CONTEXT entry, tracker housekeeping.\n- **Acceptance tests.** One for each acceptance bullet.\n\nNothing remains unmet. It converged on pass 2.\n\n**Limitations the operator accepts** (from the plan, all documented):\n- **Override checkouts.** The built-page gate skips on a checkout with a local override.\n- **Uncounted opens.** Middle-click and context-menu opens are not counted.\n- **Non-http(s) links.** Tracked non-http(s) links are not counted.\n- **Best-effort counts.** Counts are best-effort: forgeable within 90/min/address, unpruned, with a heuristic bot filter.\n- **Dev beacons.** Dev cross-origin beacons may be lost.\n- **Shared connection.** The shared-connection race is inherited, and filed as issue 42 rather than fixed here.\n- **Missing guard.** `test_static_page_visit_logs.py` does not exist, so the plan's \"stays green\" wording is dropped and issue 43 is filed instead.\n",
  "coordination": "none. No credential, live endpoint or manual step is needed. Phase 4 needs `client/frontend/node_modules` (esbuild and vite) installed, which `test_frontend_profile.py` already requires. Its built-page check skips on a checkout that has an untracked `dev-pages/about.html` override.",
  "tests": {
    "tests/tmp/test_18_about_outbound_click_tracking_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase1.py:42 \u2014 `[row[1] for row in PRAGMA table_info(analytics_events)] == COLUMNS`, after ensure_user_schema has run twice",
          "expected": "[\"id\", \"type\", \"track_id\", \"href\", \"page_path\", \"created_at\", \"user_agent\", \"referer\"]. The probe showed exactly this for the plan's settled DDL run twice through executescript. Against the current code the run shows `[]` because the table does not exist yet.",
          "wrong_implementation": "A table that also has an `ip_hash` or `client_ip` column (the address-derived column the issue first proposed) reads a nine-item list. One missing a column (for example no `referer`) or in a different order also fails, and so does an ensure_user_schema that never creates the table, which reads `[]`."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase1.py:43 \u2014 `(name, type, notnull, pk)` for each column from PRAGMA table_info == COLUMN_DEFS",
          "expected": "[(\"id\",\"INTEGER\",0,1), (\"type\",\"TEXT\",1,0), (\"track_id\",\"TEXT\",0,0), (\"href\",\"TEXT\",0,0), (\"page_path\",\"TEXT\",1,0), (\"created_at\",\"INTEGER\",1,0), (\"user_agent\",\"TEXT\",0,0), (\"referer\",\"TEXT\",0,0)]. Observed in the probe as `(0, 'id', 'INTEGER', 0, None, 1), (1, 'type', 'TEXT', 1, None, 0), \u2026`.",
          "wrong_implementation": "Getting the column names right but not the declarations fails here. Examples: `page_path TEXT` without NOT NULL reads notnull 0, `created_at TEXT` reads 'TEXT', and `id INTEGER` that is not the primary key reads pk 0."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase1.py:44 \u2014 the ordered column lists of every index on analytics_events == [[\"type\",\"track_id\",\"created_at\"]]",
          "expected": "[[\"type\", \"track_id\", \"created_at\"]]. The probe saw a single index, analytics_events_type_track_created_idx, whose index_info is (type, track_id, created_at). INTEGER PRIMARY KEY adds no autoindex.",
          "wrong_implementation": "Leaving out the CREATE INDEX reads `[]`. An index in a different order, such as (created_at, type, track_id), or an extra UNIQUE constraint that brings an autoindex, reads a different list."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase1.py:49-51 \u2014 inserting type 'click' raises sqlite3.IntegrityError matching \"CHECK\"",
          "expected": "IntegrityError(\"CHECK constraint failed: type IN ('outbound_click', 'page_view')\"), as observed in the probe.",
          "wrong_implementation": "A `type TEXT NOT NULL` with no CHECK accepts 'click'. pytest.raises then fails with DID NOT RAISE, and line 52 would also see a second row."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase1.py:52 \u2014 after a row is written and ensure_user_schema runs a third time, STORED reads exactly that one row",
          "expected": "[(\"page_view\", None, None, \"/about\", 1, None, None)]. CREATE TABLE IF NOT EXISTS keeps the row, and the probe showed the CHECK-refused insert is rolled back by `with conn:`.",
          "wrong_implementation": "A schema function that does `DROP TABLE IF EXISTS analytics_events` before creating it, or plain CREATE TABLE inside a try/except that recreates the table, reads `[]` here. Plain CREATE TABLE without IF NOT EXISTS raises \"table already exists\" at line 40."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase1.py:71 \u2014 after one insert_analytics_event inside a completed `with conn:`, a second connection reads STORED == the passed values",
          "expected": "[(\"outbound_click\", \"about_patreon\", \"https://www.patreon.com/x\", \"/about.html\", 1767225600123, \"Mozilla/5.0 analytics-test\", \"https://example.org/about\")]. The probe showed this row read back through a second connection after the equivalent INSERT committed. Against the current code the run fails earlier, with AttributeError at line 62.",
          "wrong_implementation": "Several plausible bugs fail here. Swapping parameters (href into track_id, or user_agent and referer reversed) shows the value in the wrong column. Writing two rows (for example once per type) reads a two-row list. Stamping created_at with now_ms() instead of the passed value reads a different integer. A no-op insert reads `[]`."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase1.py:65 \u2014 after insert_analytics_event inside a `with conn:` that raises, a second connection reads STORED == []",
          "expected": "[]. The probe showed in_transaction True after the INSERT and `[]` from a reader after the rollback. Line 71 (a written, committed row) is what proves the function writes at all.",
          "wrong_implementation": "An insert_analytics_event that calls conn.commit() itself, the way record_like and get_or_create_user do, persists the row before the raise. The reader then sees [(\"page_view\", None, None, \"/rolled-back\", 1, None, None)]."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "After `ensure_user_schema`, `analytics_events` has exactly the eight settled columns and none derived from the client address."
        },
        {
          "id": "C2",
          "text": "One `insert_analytics_event` call inside `with conn:` commits exactly one row with the given values."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_18_about_outbound_click_tracking_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_18_about_outbound_click_tracking_phase1.py  2 failed                               0.0s\n  ---------------------------------------------------------\n  total                                                      2 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_18_about_outbound_click_tracking_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase2.py:103 \u2014 `client_server._validate_analytics_event(body) == expected` over the 9 VALID params (5 outbound_click, 4 page_view), with the expected tuples written out by hand.",
          "expected": "The exact 4-tuple for each case. For example, (\"outbound_click\", \"about_patreon\", \"https://www.patreon.com/x\", \"/about\") for the baseline, (\"outbound_click\", \"about_patreon\", \"HTTPS://Example.ORG/Path\", \"/about\") for the upper-case scheme, and (\"page_view\", None, None, \"/about\") for the page_view with both keys absent.",
          "wrong_implementation": "A validator that lower-cases the scheme returns \"https://Example.ORG/Path\". One with an off-by-one cap returns an error string at track_id 64, href 2048 or page_path 256. One that rejects unknown keys returns an error string on the `ip`/`session` and `referrer`/`extra` cases. One that indexes body[\"track_id\"] on a page_view raises KeyError. A hard-coded tuple matches at most one case. Every one of these reads != expected."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110 \u2014 `isinstance(result, str) and result` over the 40 INVALID params. Each is called directly, so a raise fails the case.",
          "expected": "A non-empty str for every invalid body.",
          "wrong_implementation": "Missing the str check before the set lookup raises TypeError on `[\"page_view\"]`. Not catching urlsplit's error raises ValueError on `http://[::1`. Skipping the UTF-8 check returns the tuple for lone surrogates. Using `re.match` with `$` accepts `abc\\n`. Letting bool through as int accepts `true`. A cap that is one too loose accepts 65, 2049 or 257 characters. Skipping the checks on page_view accepts a page_view that carries a track_id or href. Accept-all returns tuples. Each of these reads a tuple, or raises, where a str is required."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Each valid event body yields its `(type, track_id, href, page_path)` tuple."
        },
        {
          "id": "C2",
          "text": "Each invalid event body yields an error string without raising."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_18_about_outbound_click_tracking_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_18_about_outbound_click_tracking_phase2.py  49 failed                              0.0s\n  ---------------------------------------------------------\n  total                                                      49 failed                              0.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_18_about_outbound_click_tracking_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase3.py:121 \u2014 (status, body) == (204, b\"\") for an outbound_click or page_view sent as application/json, text/plain;charset=UTF-8 or application/x-www-form-urlencoded",
          "expected": "(204, b\"\") in all 5 ACCEPTED cases",
          "wrong_implementation": "A route that accepts only application/json, or that answers 200/201 with a body, reads (400 or 415, ...) on the text/plain and form cases, or (200, b\"{...}\")."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase3.py:123 \u2014 len(rows) == 1 on a fresh per-test database",
          "expected": "1",
          "wrong_implementation": "A route that returns 204 without inserting reads 0; a double insert reads 2."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase3.py:125 \u2014 (type, track_id, href, page_path, user_agent, referer) == expected",
          "expected": "The fields as sent; track_id/href NULL on a page_view; user_agent/referer equal to the headers, and None when a header is sent as \"\" or not sent",
          "wrong_implementation": "Storing the raw empty header reads \"\" instead of None (param :94). Storing a default UA reads a string where None is expected (:95). Swapping UA and referer reads (REFERER, USER_AGENT) or (None, USER_AGENT) on :96. Handling only one event type fails the other type's cases."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase3.py:126-127 \u2014 created_at is an int within [now_ms() before, now_ms() after] and != CLIENT_TIMESTAMP (1)",
          "expected": "An integer ms stamp taken by the server during the request",
          "wrong_implementation": "Copying the body timestamp stores 1, which falls outside the window and equals CLIENT_TIMESTAMP."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase3.py:134-137 \u2014 each of the 12 REJECTED bodies gets status 400, a JSON non-empty string error, and _rows == []; armed by the :138-:139 control, where a following valid event gets (204, b\"\") and 1 row",
          "expected": "400, a non-empty str error, [] rows, then 1 row after the control post",
          "wrong_implementation": "Inserting before validating reads a non-empty table at :137. Accepting a malformed body reads 204 at :134. Crashing reads 500. A route that never writes fails the control at :138-:139."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase3.py:148-150 \u2014 after 90 posts from 203.0.113.18 each get 204 (:149), the 91st gets (429, {\"error\": \"Rate limit exceeded\"}) (:148), and the row count is 90 (:150); :151-:152 show 203.0.113.19 is still stored",
          "expected": "429 with that body; 90 rows; then 204 and 91 rows for the other address",
          "wrong_implementation": "No limiter on the route reads 204 at :148. Inserting before the limit check reads 91 rows at :150. A global, not per-address, limit, or a stopped server, reads 429 or an error at :151."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A valid event of either type, with any Content-Type, gets 204 and adds one row whose `created_at`, `user_agent` and `referer` come from the server."
        },
        {
          "id": "C2",
          "text": "A refused POST, whether 400 for an invalid body or 429 over the route limit, adds no row."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_18_about_outbound_click_tracking_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_18_about_outbound_click_tracking_phase3.py  18 failed, 1 passed                    0.0s\n  ---------------------------------------------------------\n  total                                                      18 failed, 1 passed                    9.8s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_18_about_outbound_click_tracking_phase4.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase4.py:147: in every sendBeacon mode exactly four sends are made, all to `http://api.test/api/analytics/event`.",
          "expected": "`[EVENT_URL] * 4`: one page_view plus three outbound_clicks for the three tracked clicks. The untracked link and the Text-like target send nothing.",
          "wrong_implementation": "A once-per-page sent flag or a self-removing listener gives two URLs. De-duplication by track_id gives three. `closest(\"a\")` gives five. `base + \"/api/...\"` gives `http://api.test//api/...`, and a URL from `location.origin` gives `http://page.test/...`. All of these were observed failing here."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase4.py:148: the decoded bodies equal exactly `[page_view, patreon, github, patreon]` as whole dicts.",
          "expected": "`{type: page_view, page_path, timestamp: 1700000000123}`, then outbound_click bodies with `about_patreon` and `https://www.patreon.com/x`, then `about_github` and `https://github.com/y`, then `about_patreon` again. Every `page_path` is the mode's stubbed pathname (`/about` or `/about.html`). This was observed under the reference module.",
          "wrong_implementation": "A hard-coded `track_id: \"about_patreon\"` reads `about_patreon` for the github click. A hard-coded `page_path: \"/about\"` is wrong in the false and throws modes. Reading the target's own attributes without `closest` misses the span clicks."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase4.py:150 (mode true): every send is a beacon carrying an `application/json` Blob, and no fetch is recorded.",
          "expected": "`[(\"beacon\", \"application/json\")] * 4`",
          "wrong_implementation": "Sending by fetch when the beacon succeeds, an untyped or string beacon body, or a detached `sendBeacon` (the stub throws Illegal invocation, so everything falls to fetch). The detached case was observed failing here."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase4.py:152 (modes false, missing, throws): every send is a fetch with POST, `keepalive: true` and `Content-Type: application/json`.",
          "expected": "`[(\"fetch\", \"POST\", True, \"application/json\")] * 4`",
          "wrong_implementation": "Dropping the event when sendBeacon is missing, ignoring sendBeacon's false return, or letting its throw end the send all give fewer than four fetch entries. A fetch without keepalive or without the JSON header gives the wrong tuple."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase4.py:153: the ordered transport log equals `TRANSPORTS[mode] * 4`.",
          "expected": "true gives `[\"beacon\"]*4`. false and throws give `[\"beacon\",\"fetch\"]*4`, observed under the reference module. missing gives `[\"fetch\"]*4`.",
          "wrong_implementation": "Fetch issued before the beacon attempt gives `fetch, beacon, ...`. A detached `sendBeacon` never reaches the push and gives `fetch` only. Both were observed failing here in false and throws."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase4.py:154-156: exactly one `click` listener is on document, no handler throws, and no unhandled rejection occurs.",
          "expected": "`[\"click\"]`, `[]` and `[]`.",
          "wrong_implementation": "No `typeof closest` guard throws on the Text-like target, so errors is non-empty. A fetch with no `.catch` puts `TypeError: offline` in rejections. Both were observed last round. Several listeners, or a listener of another type, fail :154."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase4.py:169: the vite-built `dev-pages/about.template.html` has at least one `<script ... src=\"/assets/*.js\">`.",
          "expected": "A non-empty list, e.g. `[\"/assets/about-<hash>.js\"]`. This was observed from a tmp copy with the reference module and template script.",
          "wrong_implementation": "A template edit that is missing or drops the script tag gives `[]`. That is the current tree, observed failing here."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_18_about_outbound_click_tracking_phase4.py:170: one of those script files contains `/api/analytics/event`.",
          "expected": "True: the entry chunk the page names carries the route literal. This was observed in the tmp-copy build.",
          "wrong_implementation": "The template loads some other script (e.g. an unrelated page entry) that does not bundle the analytics module, so no listed asset contains the route."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Importing the module sends one `page_view` and one `outbound_click` per tracked click, falling back to keepalive `fetch` when `sendBeacon` is unavailable, refuses or throws."
        },
        {
          "id": "C2",
          "text": "A vite build of the About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_18_about_outbound_click_tracking_phase4.py",
        "code": 1,
        "output": "  tests/tmp/test_18_about_outbound_click_tracking_phase4.py  1 failed, 4 error                      0.0s\n  ---------------------------------------------------------\n  total                                                      1 failed, 4 error                      0.6s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_18_about_outbound_click_tracking_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_ensure_user_schema_creates_settled_analytics_events_idempotently fails at line 42:\n`PRAGMA table_info(analytics_events)` returns no rows, because ensure_user_schema\n(client/backend/lib/users_store.py:10-71) creates no analytics_events table, so\n`[] == COLUMNS` is false. test_insert_analytics_event_writes_one_row_in_callers_transaction\nerrors at line 62 with AttributeError, because lib.users_store defines no\ninsert_analytics_event. AttributeError is not RuntimeError, so the error is not caught\nby `pytest.raises(RuntimeError, match=\"abort\")` at line 60.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_analytics_events.py (NEW). That path does\n   not resolve, so it was not read. The verdict comes from the test file and\n   client/backend/lib/users_store.py only.\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`,\n   so no conftest was needed and none was looked for.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 5 must_prove, 10 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | after `ensure_user_schema`, `analytics_events` has \"exactly the eight settled columns\" | :42 | a missing, renamed, reordered or extra column (the column list must match exactly) | CARRIED |\n| C1b | must_prove | \"none derived from the client address\" | :42 | an added `ip` / `ip_hash` / address-derived column, because any ninth column breaks the exact match | CARRIED |\n| C2a | must_prove | one `insert_analytics_event` call inside `with conn:` commits | :71 | a write that a second connection can't see after the block completes | CARRIED |\n| C2b | must_prove | \"exactly one row\" | :71 | a duplicate write, or a write plus a companion row, because the full result list is compared | CARRIED |\n| C2c | must_prove | \"with the given values\" | :71 | arguments swapped between columns, `created_at` stamped from the clock instead of the passed value, or a value dropped. All seven values are distinct | CARRIED |\n| D1 | docstring | module and :36: each column's \"types, NOT NULLs and primary key\" as settled | :43 | a wrong declared type, a missing NOT NULL on type/page_path/created_at, or a primary key on the wrong column | CARRIED |\n| D2 | docstring | module and :36: \"its CHECK refuses an unknown type\" | :49-51 | a table with no CHECK, or one that also admits `'click'` | CARRIED |\n| D3 | docstring | module and :36: \"indexed on (type, track_id, created_at)\" | :44 | no index, the wrong column order, or extra indexes | CARRIED |\n| D4 | docstring | :36: \"run twice\" still leaves the settled table | :42-44 (after :39-40) | a CREATE without IF NOT EXISTS (the second run would raise), or a second run that changes the shape | CARRIED |\n| D5 | docstring | module \"a second ensure_user_schema keeps the table and its rows\" / :36 \"a third run keeps a row written before it\" | :52 | ensure dropping and recreating the table, or deleting its rows | CARRIED |\n| D6 | docstring | :52 comment / implied by D2: \"the refused insert left none\" | :52 | a CHECK that fails after a partial write commits | CARRIED |\n| D7 | docstring | module and :56: \"`with conn:` block raises leaves nothing\" | :65 | `insert_analytics_event` calling `conn.commit()` itself, so the row survives the rollback | CARRIED |\n| D8 | docstring | module and :56: \"completes \u2026 exactly one row with the passed values\" | :71 | same as C2a\u2013C2c | CARRIED |\n| D9 | docstring | module and :56: \"read through a second connection\" | :64-65, :70-71 | a check that only sees uncommitted state on the writing connection | CARRIED |\n| D10 | docstring | module: \"Called directly on a tmp users.db; no server is involved\" | :37, :57 (setup, by construction) | a description of the harness, not a behaviour; the file only calls `users_store` against `tmp_path` | CARRIED |\n| N1 | name | `ensure_user_schema_creates_settled_analytics_events` | :42-44 | a missing or unsettled table | CARRIED |\n| N2 | name | `idempotently` | :42-44, :52 | a second or third run raising, reshaping the table or losing rows | CARRIED |\n| N3 | name | `insert_analytics_event_writes_one_row` | :71 | zero or several rows | CARRIED |\n| N4 | name | `in_callers_transaction` | :65 | a self-committing insert, which survives the rollback | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase1.py:68\n   `insert_analytics_event(conn, \"outbound_click\", \"about_patreon\", \"https://www.patreon.com/x\", \"/about.html\", 1767225600123, \"Mozilla/5.0 analytics-test\", \"https://example.org/about\")`\n   The only committed write through the function fills every nullable field. Two edge cases are untested:\n   - `None` for `track_id`, `href`, `user_agent` or `referer`, read back as NULL, is never committed through `insert_analytics_event`. The all-NULL call at :62 is rolled back and never read. The NULL round-trip at :47 uses raw SQL, not the function.\n   - A NULL `page_path` or `created_at`, which the NOT NULL constraints should refuse, is never tried.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase1.py:51\n   `conn.execute(\"INSERT INTO analytics_events (type, page_path, created_at) VALUES ('click', '/about', 2)\")`\n   Only raw SQL tests the unknown-type refusal. `insert_analytics_event` never gets an unknown type, so the function's own failure mode (raising `IntegrityError` and leaving no row) has no test. It is untested whether the function passes the constraint error through or swallows it.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_analytics_events.py (NEW), which does not exist. Nothing from it was read.\n2. client/backend/lib/users_store.py, as read, defines neither an `analytics_events` table in `ensure_user_schema` nor an `insert_analytics_event` function. A repo-wide Grep finds both names only in docs/project/plans/, tests/tmp/ and test output files. Bounds and the abnormal path were therefore judged from the test and the clause text, not from the inputs the code accepts or how it is meant to fail. The \"eight settled columns\" and their types were taken as the test states them. They were not checked against any implementation or approved DDL.\n3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. The only conftest found, tests/active/conftest.py, does not cover tests/tmp/, so no fixture went unread.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_ensure_user_schema_creates_settled_analytics_events_idempotently fails at line 42:\n`PRAGMA table_info(analytics_events)` returns no rows, because ensure_user_schema\n(client/backend/lib/users_store.py:10-71) creates no analytics_events table, so\n`[] == COLUMNS` is false. test_insert_analytics_event_writes_one_row_in_callers_transaction\nerrors at line 62 with AttributeError, because lib.users_store defines no\ninsert_analytics_event. AttributeError is not RuntimeError, so the error is not caught\nby `pytest.raises(RuntimeError, match=\"abort\")` at line 60.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_analytics_events.py (NEW). That path does\n   not resolve, so it was not read. The verdict comes from the test file and\n   client/backend/lib/users_store.py only.\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`,\n   so no conftest was needed and none was looked for.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 5 must_prove, 10 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | after `ensure_user_schema`, `analytics_events` has \"exactly the eight settled columns\" | :42 | a missing, renamed, reordered or extra column (the column list must match exactly) | CARRIED |\n| C1b | must_prove | \"none derived from the client address\" | :42 | an added `ip` / `ip_hash` / address-derived column, because any ninth column breaks the exact match | CARRIED |\n| C2a | must_prove | one `insert_analytics_event` call inside `with conn:` commits | :71 | a write that a second connection can't see after the block completes | CARRIED |\n| C2b | must_prove | \"exactly one row\" | :71 | a duplicate write, or a write plus a companion row, because the full result list is compared | CARRIED |\n| C2c | must_prove | \"with the given values\" | :71 | arguments swapped between columns, `created_at` stamped from the clock instead of the passed value, or a value dropped. All seven values are distinct | CARRIED |\n| D1 | docstring | module and :36: each column's \"types, NOT NULLs and primary key\" as settled | :43 | a wrong declared type, a missing NOT NULL on type/page_path/created_at, or a primary key on the wrong column | CARRIED |\n| D2 | docstring | module and :36: \"its CHECK refuses an unknown type\" | :49-51 | a table with no CHECK, or one that also admits `'click'` | CARRIED |\n| D3 | docstring | module and :36: \"indexed on (type, track_id, created_at)\" | :44 | no index, the wrong column order, or extra indexes | CARRIED |\n| D4 | docstring | :36: \"run twice\" still leaves the settled table | :42-44 (after :39-40) | a CREATE without IF NOT EXISTS (the second run would raise), or a second run that changes the shape | CARRIED |\n| D5 | docstring | module \"a second ensure_user_schema keeps the table and its rows\" / :36 \"a third run keeps a row written before it\" | :52 | ensure dropping and recreating the table, or deleting its rows | CARRIED |\n| D6 | docstring | :52 comment / implied by D2: \"the refused insert left none\" | :52 | a CHECK that fails after a partial write commits | CARRIED |\n| D7 | docstring | module and :56: \"`with conn:` block raises leaves nothing\" | :65 | `insert_analytics_event` calling `conn.commit()` itself, so the row survives the rollback | CARRIED |\n| D8 | docstring | module and :56: \"completes \u2026 exactly one row with the passed values\" | :71 | same as C2a\u2013C2c | CARRIED |\n| D9 | docstring | module and :56: \"read through a second connection\" | :64-65, :70-71 | a check that only sees uncommitted state on the writing connection | CARRIED |\n| D10 | docstring | module: \"Called directly on a tmp users.db; no server is involved\" | :37, :57 (setup, by construction) | a description of the harness, not a behaviour; the file only calls `users_store` against `tmp_path` | CARRIED |\n| N1 | name | `ensure_user_schema_creates_settled_analytics_events` | :42-44 | a missing or unsettled table | CARRIED |\n| N2 | name | `idempotently` | :42-44, :52 | a second or third run raising, reshaping the table or losing rows | CARRIED |\n| N3 | name | `insert_analytics_event_writes_one_row` | :71 | zero or several rows | CARRIED |\n| N4 | name | `in_callers_transaction` | :65 | a self-committing insert, which survives the rollback | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase1.py:68\n   `insert_analytics_event(conn, \"outbound_click\", \"about_patreon\", \"https://www.patreon.com/x\", \"/about.html\", 1767225600123, \"Mozilla/5.0 analytics-test\", \"https://example.org/about\")`\n   The only committed write through the function fills every nullable field. Two edge cases are untested:\n   - `None` for `track_id`, `href`, `user_agent` or `referer`, read back as NULL, is never committed through `insert_analytics_event`. The all-NULL call at :62 is rolled back and never read. The NULL round-trip at :47 uses raw SQL, not the function.\n   - A NULL `page_path` or `created_at`, which the NOT NULL constraints should refuse, is never tried.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase1.py:51\n   `conn.execute(\"INSERT INTO analytics_events (type, page_path, created_at) VALUES ('click', '/about', 2)\")`\n   Only raw SQL tests the unknown-type refusal. `insert_analytics_event` never gets an unknown type, so the function's own failure mode (raising `IntegrityError` and leaving no row) has no test. It is untested whether the function passes the constraint error through or swallows it.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_analytics_events.py (NEW), which does not exist. Nothing from it was read.\n2. client/backend/lib/users_store.py, as read, defines neither an `analytics_events` table in `ensure_user_schema` nor an `insert_analytics_event` function. A repo-wide Grep finds both names only in docs/project/plans/, tests/tmp/ and test output files. Bounds and the abnormal path were therefore judged from the test and the clause text, not from the inputs the code accepts or how it is meant to fail. The \"eight settled columns\" and their types were taken as the test states them. They were not checked against any implementation or approved DDL.\n3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. The only conftest found, tests/active/conftest.py, does not cover tests/tmp/, so no fixture went unread.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "after `ensure_user_schema`, `analytics_events` has \"exactly the eight settled columns\"",
            "assertion": ":42",
            "excludes": "a missing, renamed, reordered or extra column (the column list must match exactly)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"none derived from the client address\"",
            "assertion": ":42",
            "excludes": "an added `ip` / `ip_hash` / address-derived column, because any ninth column breaks the exact match",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "one `insert_analytics_event` call inside `with conn:` commits",
            "assertion": ":71",
            "excludes": "a write that a second connection can't see after the block completes",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"exactly one row\"",
            "assertion": ":71",
            "excludes": "a duplicate write, or a write plus a companion row, because the full result list is compared",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"with the given values\"",
            "assertion": ":71",
            "excludes": "arguments swapped between columns, `created_at` stamped from the clock instead of the passed value, or a value dropped. All seven values are distinct",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "module and :36: each column's \"types, NOT NULLs and primary key\" as settled",
            "assertion": ":43",
            "excludes": "a wrong declared type, a missing NOT NULL on type/page_path/created_at, or a primary key on the wrong column",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "module and :36: \"its CHECK refuses an unknown type\"",
            "assertion": ":49-51",
            "excludes": "a table with no CHECK, or one that also admits `'click'`",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "module and :36: \"indexed on (type, track_id, created_at)\"",
            "assertion": ":44",
            "excludes": "no index, the wrong column order, or extra indexes",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": ":36: \"run twice\" still leaves the settled table",
            "assertion": ":42-44 (after :39-40)",
            "excludes": "a CREATE without IF NOT EXISTS (the second run would raise), or a second run that changes the shape",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "module \"a second ensure_user_schema keeps the table and its rows\" / :36 \"a third run keeps a row written before it\"",
            "assertion": ":52",
            "excludes": "ensure dropping and recreating the table, or deleting its rows",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": ":52 comment / implied by D2: \"the refused insert left none\"",
            "assertion": ":52",
            "excludes": "a CHECK that fails after a partial write commits",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "module and :56: \"`with conn:` block raises leaves nothing\"",
            "assertion": ":65",
            "excludes": "`insert_analytics_event` calling `conn.commit()` itself, so the row survives the rollback",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "module and :56: \"completes \u2026 exactly one row with the passed values\"",
            "assertion": ":71",
            "excludes": "same as C2a\u2013C2c",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "module and :56: \"read through a second connection\"",
            "assertion": ":64-65, :70-71",
            "excludes": "a check that only sees uncommitted state on the writing connection",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "module: \"Called directly on a tmp users.db; no server is involved\"",
            "assertion": ":37, :57 (setup, by construction)",
            "excludes": "a description of the harness, not a behaviour; the file only calls `users_store` against `tmp_path`",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`ensure_user_schema_creates_settled_analytics_events`",
            "assertion": ":42-44",
            "excludes": "a missing or unsettled table",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`idempotently`",
            "assertion": ":42-44, :52",
            "excludes": "a second or third run raising, reshaping the table or losing rows",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "`insert_analytics_event_writes_one_row`",
            "assertion": ":71",
            "excludes": "zero or several rows",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "`in_callers_transaction`",
            "assertion": ":65",
            "excludes": "a self-committing insert, which survives the rollback",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_18_about_outbound_click_tracking_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this, per the `<constraints>` fallback (rules/shape.md). Nearest is `absence-only-assertion <how_to_spot>` bullet 3. Located at tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110\n   assert isinstance(result, str) and result  # C2\n   This assertion is positive, so `absence-only-assertion` does not apply as written. Even so, `test_invalid_event_returns_error_string` on its own goes green on a stub that rejects every body (`return \"not implemented\"`). The positive control is the `click-baseline` / `view-absent` cases at :45 and :50, which run in a different test function (:103). The file as a whole still fails that stub, because C1 goes red. But if the C2 function is ever run or kept on its own, it is no longer a gate. You could assert the baseline is accepted inside the C2 function as well, before the rejection, so the control stays with it.\n\nPREDICTED FAILURE\nAll 49 cases fail with `AttributeError: module 'server' has no attribute '_validate_analytics_event'`, because `client/backend/server.py` does not define that symbol yet. The 9 VALID cases fail at line 103 on `client_server._validate_analytics_event(body) == expected`. The 40 INVALID cases fail at line 109 on `result = client_server._validate_analytics_event(body)`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist on disk, so it was not read. This test does not import it.\n2. `client/backend/server.py` was searched for `_validate_analytics_event` and analytics symbols, with no match. It was not otherwise read. The stub question was answered from the assertion form at :103 and :110 against the 9 VALID and 40 INVALID cases written out by hand:\n   - A hard-coded tuple matches at most one VALID case.\n   - Accept-all fails C2.\n   - Reject-all fails C1.\n   - The uppercase-scheme and max-length cases separate normalising and off-by-one implementations.\n3. Anti-pattern pass (rules/shape.md): no `.md` is read and no section is extracted, so `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep` do not apply. Expected values are literals checked against a production call, not a constant or a re-derivation, so `hardcoded-spec-mirror` and `tautological-assertion` do not apply. A production symbol sits between input and expected value, so `echoed-literal` does not apply. There are many differing inputs, so `single-value-pin` does not apply. Ladder pass: the test is at rung 1 (it calls the function directly), which is the highest rung, so no downshift comment is needed.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 2 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | each valid body yields its `(type, track_id, href, page_path)` tuple | :103 | a wrong field, wrong order, a missing member, a changed value (e.g. lower-cased scheme), or an error string on a valid body | CARRIED |\n| C2 | must_prove | each invalid body yields an error string without raising | :110 | raising (pytest fails the case), returning a tuple or None, returning `\"\"` | CARRIED |\n| D1 | docstring | valid outbound_click returns \"exactly its (type, track_id, href, page_path) as sent\" | :103 | a validator that normalises or reorders values | CARRIED |\n| D2 | docstring | \"at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256)\" | :103 (params :47, :48) | an off-by-one cap that rejects a value at the limit. :48 gives track_id 64, href 12+2036=2048 and page_path 256 chars | CARRIED |\n| D3 | docstring | \"with an upper-case scheme\" | :103 (param :49) | a case-sensitive scheme check, or a scheme folded to lower case | CARRIED |\n| D4 | docstring | click \"with unknown keys present\" | :103 (param :46) | rejecting extra keys such as `ip` or `session` | CARRIED |\n| D5 | docstring | page_view returns (page_view, None, None, page_path) with track_id/href \"absent, both null, or one of each\" | :103 (params :50\u2013:53) | a KeyError on absent keys, rejecting explicit nulls, or echoing a value where None belongs | CARRIED |\n| D6 | docstring | page_view \"with unknown keys present\" | :103 (param :53) | rejecting `referrer` or `extra` on a page_view | CARRIED |\n| D7 | docstring | a body breaking one rule (type, track_id, href, page_path, timestamp, page_view with track_id/href) \"returns a non-empty error string and does not raise\" | :110 | accepting any listed violation, or raising on it | CARRIED |\n| D8 | docstring | \"includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one\" | :110 (params :61, :80, :86, :76, :66, :77, :84) | an unhashable-type crash, an unchecked surrogate, urlsplit's ValueError escaping, or caps that are one too loose | CARRIED |\n| D9 | docstring | \"the baseline is itself asserted valid\" | :103 (params :45, :50) | a baseline that would be rejected anyway, which would make each rejection meaningless | CARRIED |\n| D10 | docstring | \"Each invalid body is the valid baseline with one key changed or removed \u2026 every rejection is down to that one key\" | :110 | holds for 39 of the 40 INVALID params. `{}` at :57 is not a one-key change, so for that case the sentence claims something the data does not do | UNCARRIED |\n| D11 | docstring (:102) | \"with track_id and href None on a page_view\" | :103 | a page_view returning a supplied or default track_id or href | CARRIED |\n| D12 | docstring (:108) | \"rather than raising or returning values\" | :110 | returning the tuple, or raising | CARRIED |\n| N1 | name | \"valid event returns its storable values\" | :103 | anything other than the exact 4-tuple | CARRIED |\n| N2 | name | \"invalid event returns error string\" | :110 | a non-string or empty result | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:57\n   `pytest.param({}, id=\"empty-object\"),`\n   D10 is UNCARRIED for this case. The module docstring (:6) says every invalid body is the baseline with one key changed or removed. `{}` removes every key, so this rejection cannot be traced to one key. Either move the empty object out from under that sentence, or narrow the sentence to name it as the exception.\n2. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:56\n   The module docstring (:1) frames the input as \"JSON-decoded event bodies\". json.loads can also return a non-object (`null`, a list, a string or a number), and no such body is tested. Whether the function must handle one depends on a contract that cannot be read, because the function does not exist yet (see NOT ASSESSED). If the caller passes json.loads output straight in, add a non-object body to INVALID.\n3. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:87\n   For a page_view, the only page_path edge tested is the missing slash. The minimum (`\"/\"`), 257 characters and a lone surrogate are tested only on outbound_click (:47, :84, :86). This matters if the page_view path is validated by a separate branch.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `client/backend/server.py` does not define `_validate_analytics_event` (Grep found no match, and the file has no analytics, outbound or page_view code at all). That means:\n   - The bounds and abnormal-path checks were judged from the test's docstring alone, not from the accepted-input contract in code.\n   - Whether the symbol named at :103 and :110 will exist could not be checked.\n2. `code_under_test` lists `tests/active/test_analytics_events.py`. That path does not resolve (FileNotFoundError), so it was not read.\n3. The phase's `<checkpoint>` seam text was not supplied. The surface pass checked that the test makes real functional assertions on the return value of the function `must_prove` describes. It did not check that this function is the seam the phase named.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this, per the `<constraints>` fallback (rules/shape.md). Nearest is `absence-only-assertion <how_to_spot>` bullet 3. Located at tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110\n   assert isinstance(result, str) and result  # C2\n   This assertion is positive, so `absence-only-assertion` does not apply as written. Even so, `test_invalid_event_returns_error_string` on its own goes green on a stub that rejects every body (`return \"not implemented\"`). The positive control is the `click-baseline` / `view-absent` cases at :45 and :50, which run in a different test function (:103). The file as a whole still fails that stub, because C1 goes red. But if the C2 function is ever run or kept on its own, it is no longer a gate. You could assert the baseline is accepted inside the C2 function as well, before the rejection, so the control stays with it.\n\nPREDICTED FAILURE\nAll 49 cases fail with `AttributeError: module 'server' has no attribute '_validate_analytics_event'`, because `client/backend/server.py` does not define that symbol yet. The 9 VALID cases fail at line 103 on `client_server._validate_analytics_event(body) == expected`. The 40 INVALID cases fail at line 109 on `result = client_server._validate_analytics_event(body)`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist on disk, so it was not read. This test does not import it.\n2. `client/backend/server.py` was searched for `_validate_analytics_event` and analytics symbols, with no match. It was not otherwise read. The stub question was answered from the assertion form at :103 and :110 against the 9 VALID and 40 INVALID cases written out by hand:\n   - A hard-coded tuple matches at most one VALID case.\n   - Accept-all fails C2.\n   - Reject-all fails C1.\n   - The uppercase-scheme and max-length cases separate normalising and off-by-one implementations.\n3. Anti-pattern pass (rules/shape.md): no `.md` is read and no section is extracted, so `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep` do not apply. Expected values are literals checked against a production call, not a constant or a re-derivation, so `hardcoded-spec-mirror` and `tautological-assertion` do not apply. A production symbol sits between input and expected value, so `echoed-literal` does not apply. There are many differing inputs, so `single-value-pin` does not apply. Ladder pass: the test is at rung 1 (it calls the function directly), which is the highest rung, so no downshift comment is needed.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 2 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | each valid body yields its `(type, track_id, href, page_path)` tuple | :103 | a wrong field, wrong order, a missing member, a changed value (e.g. lower-cased scheme), or an error string on a valid body | CARRIED |\n| C2 | must_prove | each invalid body yields an error string without raising | :110 | raising (pytest fails the case), returning a tuple or None, returning `\"\"` | CARRIED |\n| D1 | docstring | valid outbound_click returns \"exactly its (type, track_id, href, page_path) as sent\" | :103 | a validator that normalises or reorders values | CARRIED |\n| D2 | docstring | \"at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256)\" | :103 (params :47, :48) | an off-by-one cap that rejects a value at the limit. :48 gives track_id 64, href 12+2036=2048 and page_path 256 chars | CARRIED |\n| D3 | docstring | \"with an upper-case scheme\" | :103 (param :49) | a case-sensitive scheme check, or a scheme folded to lower case | CARRIED |\n| D4 | docstring | click \"with unknown keys present\" | :103 (param :46) | rejecting extra keys such as `ip` or `session` | CARRIED |\n| D5 | docstring | page_view returns (page_view, None, None, page_path) with track_id/href \"absent, both null, or one of each\" | :103 (params :50\u2013:53) | a KeyError on absent keys, rejecting explicit nulls, or echoing a value where None belongs | CARRIED |\n| D6 | docstring | page_view \"with unknown keys present\" | :103 (param :53) | rejecting `referrer` or `extra` on a page_view | CARRIED |\n| D7 | docstring | a body breaking one rule (type, track_id, href, page_path, timestamp, page_view with track_id/href) \"returns a non-empty error string and does not raise\" | :110 | accepting any listed violation, or raising on it | CARRIED |\n| D8 | docstring | \"includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one\" | :110 (params :61, :80, :86, :76, :66, :77, :84) | an unhashable-type crash, an unchecked surrogate, urlsplit's ValueError escaping, or caps that are one too loose | CARRIED |\n| D9 | docstring | \"the baseline is itself asserted valid\" | :103 (params :45, :50) | a baseline that would be rejected anyway, which would make each rejection meaningless | CARRIED |\n| D10 | docstring | \"Each invalid body is the valid baseline with one key changed or removed \u2026 every rejection is down to that one key\" | :110 | holds for 39 of the 40 INVALID params. `{}` at :57 is not a one-key change, so for that case the sentence claims something the data does not do | UNCARRIED |\n| D11 | docstring (:102) | \"with track_id and href None on a page_view\" | :103 | a page_view returning a supplied or default track_id or href | CARRIED |\n| D12 | docstring (:108) | \"rather than raising or returning values\" | :110 | returning the tuple, or raising | CARRIED |\n| N1 | name | \"valid event returns its storable values\" | :103 | anything other than the exact 4-tuple | CARRIED |\n| N2 | name | \"invalid event returns error string\" | :110 | a non-string or empty result | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:57\n   `pytest.param({}, id=\"empty-object\"),`\n   D10 is UNCARRIED for this case. The module docstring (:6) says every invalid body is the baseline with one key changed or removed. `{}` removes every key, so this rejection cannot be traced to one key. Either move the empty object out from under that sentence, or narrow the sentence to name it as the exception.\n2. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:56\n   The module docstring (:1) frames the input as \"JSON-decoded event bodies\". json.loads can also return a non-object (`null`, a list, a string or a number), and no such body is tested. Whether the function must handle one depends on a contract that cannot be read, because the function does not exist yet (see NOT ASSESSED). If the caller passes json.loads output straight in, add a non-object body to INVALID.\n3. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:87\n   For a page_view, the only page_path edge tested is the missing slash. The minimum (`\"/\"`), 257 characters and a lone surrogate are tested only on outbound_click (:47, :84, :86). This matters if the page_view path is validated by a separate branch.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `client/backend/server.py` does not define `_validate_analytics_event` (Grep found no match, and the file has no analytics, outbound or page_view code at all). That means:\n   - The bounds and abnormal-path checks were judged from the test's docstring alone, not from the accepted-input contract in code.\n   - Whether the symbol named at :103 and :110 will exist could not be checked.\n2. `code_under_test` lists `tests/active/test_analytics_events.py`. That path does not resolve (FileNotFoundError), so it was not read.\n3. The phase's `<checkpoint>` seam text was not supplied. The surface pass checked that the test makes real functional assertions on the return value of the function `must_prove` describes. It did not check that this function is the seam the phase named.",
        "map": [
          {
            "id": "C1",
            "source": "must_prove",
            "clause": "each valid body yields its `(type, track_id, href, page_path)` tuple",
            "assertion": ":103",
            "excludes": "a wrong field, wrong order, a missing member, a changed value (e.g. lower-cased scheme), or an error string on a valid body",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "each invalid body yields an error string without raising",
            "assertion": ":110",
            "excludes": "raising (pytest fails the case), returning a tuple or None, returning `\"\"`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "valid outbound_click returns \"exactly its (type, track_id, href, page_path) as sent\"",
            "assertion": ":103",
            "excludes": "a validator that normalises or reorders values",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256)\"",
            "assertion": ":103 (params :47, :48)",
            "excludes": "an off-by-one cap that rejects a value at the limit. :48 gives track_id 64, href 12+2036=2048 and page_path 256 chars",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"with an upper-case scheme\"",
            "assertion": ":103 (param :49)",
            "excludes": "a case-sensitive scheme check, or a scheme folded to lower case",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "click \"with unknown keys present\"",
            "assertion": ":103 (param :46)",
            "excludes": "rejecting extra keys such as `ip` or `session`",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "page_view returns (page_view, None, None, page_path) with track_id/href \"absent, both null, or one of each\"",
            "assertion": ":103 (params :50\u2013:53)",
            "excludes": "a KeyError on absent keys, rejecting explicit nulls, or echoing a value where None belongs",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "page_view \"with unknown keys present\"",
            "assertion": ":103 (param :53)",
            "excludes": "rejecting `referrer` or `extra` on a page_view",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "a body breaking one rule (type, track_id, href, page_path, timestamp, page_view with track_id/href) \"returns a non-empty error string and does not raise\"",
            "assertion": ":110",
            "excludes": "accepting any listed violation, or raising on it",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one\"",
            "assertion": ":110 (params :61, :80, :86, :76, :66, :77, :84)",
            "excludes": "an unhashable-type crash, an unchecked surrogate, urlsplit's ValueError escaping, or caps that are one too loose",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"the baseline is itself asserted valid\"",
            "assertion": ":103 (params :45, :50)",
            "excludes": "a baseline that would be rejected anyway, which would make each rejection meaningless",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Each invalid body is the valid baseline with one key changed or removed \u2026 every rejection is down to that one key\"",
            "assertion": ":110",
            "excludes": "holds for 39 of the 40 INVALID params. `{}` at :57 is not a one-key change, so for that case the sentence claims something the data does not do",
            "status": "UNCARRIED"
          },
          {
            "id": "D11",
            "source": "docstring (:102)",
            "clause": "\"with track_id and href None on a page_view\"",
            "assertion": ":103",
            "excludes": "a page_view returning a supplied or default track_id or href",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring (:108)",
            "clause": "\"rather than raising or returning values\"",
            "assertion": ":110",
            "excludes": "returning the tuple, or raising",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"valid event returns its storable values\"",
            "assertion": ":103",
            "excludes": "anything other than the exact 4-tuple",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"invalid event returns error string\"",
            "assertion": ":110",
            "excludes": "a non-string or empty result",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this; the nearest is absence-only-assertion <how_to_spot>, third bullet\n   (rules/shape.md). tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110\n   assert isinstance(result, str) and result  # C2\n   This assertion checks for something rather than its absence, so the anti-pattern does\n   not apply. But test_invalid_event_returns_error_string alone passes against a stub that\n   always returns the same string (e.g. `return \"invalid\"`). Nothing in this test\n   function shows that any one of the INVALID bodies was rejected for its changed key.\n   That proof comes from test_valid_event_returns_its_storable_values (line 103), which\n   checks the click-baseline and view-absent bodies are valid. As a file the gate holds:\n   that stub fails every VALID case. If the test is ever run alone with `-k` or split\n   across files, the C2 gate would pass on a stub. Consider asserting the valid baseline\n   inside the C2 test too, or tying each error string to the key that caused it.\n\nPREDICTED FAILURE\nEvery parametrized case fails at line 103 (C1) and line 109 (C2) with\nAttributeError: module 'server' has no attribute '_validate_analytics_event'.\nclient/backend/server.py does not yet define that symbol: grepping for\n`_validate_analytics_event` and `analytics` finds nothing.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_analytics_events.py, but that path does not\n   exist and was not read.\n2. client/backend/server.py exists but does not yet define `_validate_analytics_event`.\n   So the stub question was answered from the assertion form alone. In brief:\n   - Rung 1 is right: the test calls the function directly and compares against literal\n     tuples.\n   - The outputs vary with the inputs across several track_id, href and page_path values,\n     so a hard-coded return fails.\n   - Each length limit is tested both at the limit, which must pass, and one past it,\n     which must fail, so an off-by-one fails.\n   - A pass-through implementation with no validation returns a tuple, not a string, for\n     every INVALID body, so it fails C2.\n   - A stub that raises NotImplementedError fails both tests.\n3. No fixtures_path was supplied. The test defines its own helpers and uses no pytest\n   fixtures. The only conftest found is tests/active/conftest.py, which does not cover\n   tests/tmp/.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 2 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | each valid body yields its `(type, track_id, href, page_path)` tuple | :103 | a wrong field, a wrong order, a missing member, a changed value (e.g. a lower-cased scheme), or an error string on a valid body. The 9 expected tuples at :45\u2013:53 are written out by hand | CARRIED |\n| C2 | must_prove | each invalid body yields an error string without raising | :110 | raising (pytest errors the case), returning a tuple or None, or returning `\"\"` | CARRIED |\n| D1 | docstring | valid outbound_click returns \"exactly its (type, track_id, href, page_path) as sent\" | :103 | a validator that normalises or reorders values | CARRIED |\n| D2 | docstring | \"at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256)\" | :103 (params :47, :48) | an off-by-one cap that rejects a value at the limit. At :48, `\"z9_\"*21+\"a\"` is 64 chars, `\"https://x.y/\"+\"a\"*2036` is 2048 and `\"/\"+\"b\"*255` is 256. At :47, track_id and page_path are 1 char | CARRIED |\n| D3 | docstring | \"with an upper-case scheme\" | :103 (param :49) | a case-sensitive scheme check, or a scheme folded to lower case in the returned href | CARRIED |\n| D4 | docstring | click \"with unknown keys present\" | :103 (param :46) | rejecting extra keys such as `ip` or `session` | CARRIED |\n| D5 | docstring | page_view returns (page_view, None, None, page_path) with track_id/href \"absent, both null, or one of each\" | :103 (params :50\u2013:53) | a KeyError on absent keys, rejecting explicit nulls, or echoing a value where None belongs | CARRIED |\n| D6 | docstring | page_view \"with unknown keys present\" | :103 (param :53) | rejecting `referrer` or `extra` on a page_view | CARRIED |\n| D7 | docstring | a body breaking one rule (type, track_id, href, page_path, timestamp, page_view with track_id/href) \"returns a non-empty error string and does not raise\" | :110 | accepting any listed violation, or raising on it | CARRIED |\n| D8 | docstring | \"includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one\" | :110 (params :61, :80, :86, :76, :66, :77, :84) | a crash on an unhashable type, an unchecked surrogate, urlsplit's ValueError escaping, or caps that are one too loose (65, 2049, 257) | CARRIED |\n| D9 | docstring | \"the baseline is itself asserted valid\" | :103 (params :45, :50) | a baseline that would be rejected anyway, which would make each rejection meaningless | CARRIED |\n| D10 | docstring | \"Each invalid body except the empty object `{}` is the valid baseline with one key changed or removed \u2026 every such rejection is down to that one key\" (narrowed at :6) | :110 | the 39 params at :58\u2013:96 are each `_click(...)` or `_view(...)` with exactly one override, so a validator that rejects for a reason other than that key can only do so by also rejecting a baseline, and :103 catches that. `{}` at :57 is now excluded by the sentence itself | CARRIED |\n| D11 | docstring (:102) | \"with track_id and href None on a page_view\" | :103 | a page_view returning a supplied or default track_id or href | CARRIED |\n| D12 | docstring (:108) | \"rather than raising or returning values\" | :110 | returning the tuple, or raising | CARRIED |\n| N1 | name | \"valid event returns its storable values\" | :103 | anything other than the exact 4-tuple | CARRIED |\n| N2 | name | \"invalid event returns error string\" | :110 | a non-string or empty result | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:6\n   D10 moved from UNCARRIED to CARRIED because the author narrowed the prose. No assertion was added. The sentence now carves out `{}`. Nothing in the test changed: no assertion and no param. The record should show it this way.\n2. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:6\n   The narrowing added a new sentence that no ledger row names: \"`{}` lacks every key at once and only shows that a body with nothing in it is rejected.\" The `{}` param at :57 carries it through :110. This is recorded only, not a defect.\n3. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:95-96\n   The D10 wording says \"one key changed or removed\". `view-with-track-id` (:95) and `view-with-href` (:96) *add* a key that the page_view baseline at :39 does not have. The one-key reasoning still holds, but the wording does not name additions. If the prose is touched again, \"changed, added or removed\" would match the data.\n4. `client_server._validate_analytics_event` is not defined anywhere in client/backend/server.py: Grep found no match, and the file has no analytics symbols at all. The test asserts against a symbol that does not exist yet. That fits a red-first checkpoint, but it means the claim audit cannot check the test's bounds against the code's actual caps or its contract for abnormal input (see NOT ASSESSED).\n\nNOT ASSESSED\n1. client/backend/server.py does not define `_validate_analytics_event`, so I could not read the input domain and failure behaviour of the code under test. The bounds and normal-and-abnormal-paths judgements (the 64/2048/256 caps, the timestamp rules and the scheme set) come from the test's own docstring and params only. They were not checked against the implementation.\n2. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist on disk, so I did not read it. The test under audit does not import it.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this; the nearest is absence-only-assertion <how_to_spot>, third bullet\n   (rules/shape.md). tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110\n   assert isinstance(result, str) and result  # C2\n   This assertion checks for something rather than its absence, so the anti-pattern does\n   not apply. But test_invalid_event_returns_error_string alone passes against a stub that\n   always returns the same string (e.g. `return \"invalid\"`). Nothing in this test\n   function shows that any one of the INVALID bodies was rejected for its changed key.\n   That proof comes from test_valid_event_returns_its_storable_values (line 103), which\n   checks the click-baseline and view-absent bodies are valid. As a file the gate holds:\n   that stub fails every VALID case. If the test is ever run alone with `-k` or split\n   across files, the C2 gate would pass on a stub. Consider asserting the valid baseline\n   inside the C2 test too, or tying each error string to the key that caused it.\n\nPREDICTED FAILURE\nEvery parametrized case fails at line 103 (C1) and line 109 (C2) with\nAttributeError: module 'server' has no attribute '_validate_analytics_event'.\nclient/backend/server.py does not yet define that symbol: grepping for\n`_validate_analytics_event` and `analytics` finds nothing.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_analytics_events.py, but that path does not\n   exist and was not read.\n2. client/backend/server.py exists but does not yet define `_validate_analytics_event`.\n   So the stub question was answered from the assertion form alone. In brief:\n   - Rung 1 is right: the test calls the function directly and compares against literal\n     tuples.\n   - The outputs vary with the inputs across several track_id, href and page_path values,\n     so a hard-coded return fails.\n   - Each length limit is tested both at the limit, which must pass, and one past it,\n     which must fail, so an off-by-one fails.\n   - A pass-through implementation with no validation returns a tuple, not a string, for\n     every INVALID body, so it fails C2.\n   - A stub that raises NotImplementedError fails both tests.\n3. No fixtures_path was supplied. The test defines its own helpers and uses no pytest\n   fixtures. The only conftest found is tests/active/conftest.py, which does not cover\n   tests/tmp/.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 2 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | each valid body yields its `(type, track_id, href, page_path)` tuple | :103 | a wrong field, a wrong order, a missing member, a changed value (e.g. a lower-cased scheme), or an error string on a valid body. The 9 expected tuples at :45\u2013:53 are written out by hand | CARRIED |\n| C2 | must_prove | each invalid body yields an error string without raising | :110 | raising (pytest errors the case), returning a tuple or None, or returning `\"\"` | CARRIED |\n| D1 | docstring | valid outbound_click returns \"exactly its (type, track_id, href, page_path) as sent\" | :103 | a validator that normalises or reorders values | CARRIED |\n| D2 | docstring | \"at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256)\" | :103 (params :47, :48) | an off-by-one cap that rejects a value at the limit. At :48, `\"z9_\"*21+\"a\"` is 64 chars, `\"https://x.y/\"+\"a\"*2036` is 2048 and `\"/\"+\"b\"*255` is 256. At :47, track_id and page_path are 1 char | CARRIED |\n| D3 | docstring | \"with an upper-case scheme\" | :103 (param :49) | a case-sensitive scheme check, or a scheme folded to lower case in the returned href | CARRIED |\n| D4 | docstring | click \"with unknown keys present\" | :103 (param :46) | rejecting extra keys such as `ip` or `session` | CARRIED |\n| D5 | docstring | page_view returns (page_view, None, None, page_path) with track_id/href \"absent, both null, or one of each\" | :103 (params :50\u2013:53) | a KeyError on absent keys, rejecting explicit nulls, or echoing a value where None belongs | CARRIED |\n| D6 | docstring | page_view \"with unknown keys present\" | :103 (param :53) | rejecting `referrer` or `extra` on a page_view | CARRIED |\n| D7 | docstring | a body breaking one rule (type, track_id, href, page_path, timestamp, page_view with track_id/href) \"returns a non-empty error string and does not raise\" | :110 | accepting any listed violation, or raising on it | CARRIED |\n| D8 | docstring | \"includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one\" | :110 (params :61, :80, :86, :76, :66, :77, :84) | a crash on an unhashable type, an unchecked surrogate, urlsplit's ValueError escaping, or caps that are one too loose (65, 2049, 257) | CARRIED |\n| D9 | docstring | \"the baseline is itself asserted valid\" | :103 (params :45, :50) | a baseline that would be rejected anyway, which would make each rejection meaningless | CARRIED |\n| D10 | docstring | \"Each invalid body except the empty object `{}` is the valid baseline with one key changed or removed \u2026 every such rejection is down to that one key\" (narrowed at :6) | :110 | the 39 params at :58\u2013:96 are each `_click(...)` or `_view(...)` with exactly one override, so a validator that rejects for a reason other than that key can only do so by also rejecting a baseline, and :103 catches that. `{}` at :57 is now excluded by the sentence itself | CARRIED |\n| D11 | docstring (:102) | \"with track_id and href None on a page_view\" | :103 | a page_view returning a supplied or default track_id or href | CARRIED |\n| D12 | docstring (:108) | \"rather than raising or returning values\" | :110 | returning the tuple, or raising | CARRIED |\n| N1 | name | \"valid event returns its storable values\" | :103 | anything other than the exact 4-tuple | CARRIED |\n| N2 | name | \"invalid event returns error string\" | :110 | a non-string or empty result | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:6\n   D10 moved from UNCARRIED to CARRIED because the author narrowed the prose. No assertion was added. The sentence now carves out `{}`. Nothing in the test changed: no assertion and no param. The record should show it this way.\n2. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:6\n   The narrowing added a new sentence that no ledger row names: \"`{}` lacks every key at once and only shows that a body with nothing in it is rejected.\" The `{}` param at :57 carries it through :110. This is recorded only, not a defect.\n3. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:95-96\n   The D10 wording says \"one key changed or removed\". `view-with-track-id` (:95) and `view-with-href` (:96) *add* a key that the page_view baseline at :39 does not have. The one-key reasoning still holds, but the wording does not name additions. If the prose is touched again, \"changed, added or removed\" would match the data.\n4. `client_server._validate_analytics_event` is not defined anywhere in client/backend/server.py: Grep found no match, and the file has no analytics symbols at all. The test asserts against a symbol that does not exist yet. That fits a red-first checkpoint, but it means the claim audit cannot check the test's bounds against the code's actual caps or its contract for abnormal input (see NOT ASSESSED).\n\nNOT ASSESSED\n1. client/backend/server.py does not define `_validate_analytics_event`, so I could not read the input domain and failure behaviour of the code under test. The bounds and normal-and-abnormal-paths judgements (the 64/2048/256 caps, the timestamp rules and the scheme set) come from the test's own docstring and params only. They were not checked against the implementation.\n2. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist on disk, so I did not read it. The test under audit does not import it.",
        "map": [
          {
            "id": "C1",
            "source": "must_prove",
            "clause": "each valid body yields its `(type, track_id, href, page_path)` tuple",
            "assertion": ":103",
            "excludes": "a wrong field, a wrong order, a missing member, a changed value (e.g. a lower-cased scheme), or an error string on a valid body. The 9 expected tuples at :45\u2013:53 are written out by hand",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "each invalid body yields an error string without raising",
            "assertion": ":110",
            "excludes": "raising (pytest errors the case), returning a tuple or None, or returning `\"\"`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "valid outbound_click returns \"exactly its (type, track_id, href, page_path) as sent\"",
            "assertion": ":103",
            "excludes": "a validator that normalises or reorders values",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256)\"",
            "assertion": ":103 (params :47, :48)",
            "excludes": "an off-by-one cap that rejects a value at the limit. At :48, `\"z9_\"*21+\"a\"` is 64 chars, `\"https://x.y/\"+\"a\"*2036` is 2048 and `\"/\"+\"b\"*255` is 256. At :47, track_id and page_path are 1 char",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"with an upper-case scheme\"",
            "assertion": ":103 (param :49)",
            "excludes": "a case-sensitive scheme check, or a scheme folded to lower case in the returned href",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "click \"with unknown keys present\"",
            "assertion": ":103 (param :46)",
            "excludes": "rejecting extra keys such as `ip` or `session`",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "page_view returns (page_view, None, None, page_path) with track_id/href \"absent, both null, or one of each\"",
            "assertion": ":103 (params :50\u2013:53)",
            "excludes": "a KeyError on absent keys, rejecting explicit nulls, or echoing a value where None belongs",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "page_view \"with unknown keys present\"",
            "assertion": ":103 (param :53)",
            "excludes": "rejecting `referrer` or `extra` on a page_view",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "a body breaking one rule (type, track_id, href, page_path, timestamp, page_view with track_id/href) \"returns a non-empty error string and does not raise\"",
            "assertion": ":110",
            "excludes": "accepting any listed violation, or raising on it",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one\"",
            "assertion": ":110 (params :61, :80, :86, :76, :66, :77, :84)",
            "excludes": "a crash on an unhashable type, an unchecked surrogate, urlsplit's ValueError escaping, or caps that are one too loose (65, 2049, 257)",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"the baseline is itself asserted valid\"",
            "assertion": ":103 (params :45, :50)",
            "excludes": "a baseline that would be rejected anyway, which would make each rejection meaningless",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Each invalid body except the empty object `{}` is the valid baseline with one key changed or removed \u2026 every such rejection is down to that one key\" (narrowed at :6)",
            "assertion": ":110",
            "excludes": "the 39 params at :58\u2013:96 are each `_click(...)` or `_view(...)` with exactly one override, so a validator that rejects for a reason other than that key can only do so by also rejecting a baseline, and :103 catches that. `{}` at :57 is now excluded by the sentence itself",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring (:102)",
            "clause": "\"with track_id and href None on a page_view\"",
            "assertion": ":103",
            "excludes": "a page_view returning a supplied or default track_id or href",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring (:108)",
            "clause": "\"rather than raising or returning values\"",
            "assertion": ":110",
            "excludes": "returning the tuple, or raising",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"valid event returns its storable values\"",
            "assertion": ":103",
            "excludes": "anything other than the exact 4-tuple",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"invalid event returns error string\"",
            "assertion": ":110",
            "excludes": "a non-string or empty result",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_18_about_outbound_click_tracking_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. absence-only-assertion (rules/shape.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:158-159\n   assert (status, json.loads(body)) == (404, {\"error\": \"Not found\"})  # regression line, no clause\n   assert _rows(client_backend.db_path) == []  # regression line, no clause\n   This test fits the entry's \"delete the code under test entirely\" check. The 404 comes from the existing fallthrough at server.py:440, and the empty table needs no new code, so the test is green before phase 3 exists. It claims no `must_prove` clause and says it is a regression line, so it gates nothing. That is why this is a Recommendation and not a Critical finding. Don't count it as evidence for C1 or C2.\n2. hardcoded-spec-mirror (rules/shape.md), partial match \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:146, 149, 150\n   accepted = [_send(base, \"POST\", _body(CLICK), limited)[0] for _ in range(90)]\n   The limiter is built from `client_server.RATE_LIMIT_MAX_REQUESTS` (line 79), but the count is the literal 90 in three places. This meets the entry's fourth <how_to_spot> bullet: change the constant and the test file has to change too. It does not meet the first bullet, because nothing asserts the constant equals a literal. So no entry fully covers it. A wrong limiter still fails the test either way, so this does not block.\n\nPREDICTED FAILURE\n`test_accepted_event_stores_one_server_stamped_row` fails at line 121 on `(status, body) == (204, b\"\")`. The POST gets 404 `{\"error\": \"Not found\"}` because `_serve_post` (server.py:442-506) has no `/api/analytics/event` branch. The same cause fails `test_invalid_body_gets_400_and_stores_nothing` at line 134 (`status == 400`, got 404) and `test_91st_post_from_one_address_gets_429_and_stores_nothing` at line 148 (got `(404, {\"error\": \"Not found\"})`). `test_get_of_event_path_is_not_a_route` passes.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist (FileNotFoundError). Nothing in it was assessed.\n2. `fixtures_path` was not supplied. I read `client_backend`, `RateLimiter`, `ensure_user_schema` and `CLOSED_ENGINE` in tests/active/conftest.py and client/backend/lib/users_store.py. The `analytics_events` table exists there (users_store.py:67), so `_rows` will run against the schema. I did not read the `ClientBackend` helper's methods in conftest past its fields `base` and `db_path`.\n3. I answered the stub question from the assertion form; nothing was run. These assertions fail against a stub:\n   - A route that returns 204 without storing fails at line 123.\n   - Copying the body's `timestamp` into `created_at` fails at lines 126-127.\n   - A constant user_agent or referer fails the empty-header and absent-header cases at line 125.\n   - A route that always returns 400 fails its own control at line 138.\n   - A missing or post-insert rate-limit check fails at line 148 or line 150.\n   The loopback peer is trusted by default (server.py:52), so `X-Forwarded-For` resolves as the 429 test assumes.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (39 clauses: 11 must_prove, 21 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a valid event of either type\" is accepted | :125 | a route that stores only `outbound_click` or only `page_view` (both types are in `ACCEPTED` and `type` is compared) | CARRIED |\n| C1b | must_prove | \"with any Content-Type\" | :121 | a route that accepts only `application/json` (`text/plain;charset=UTF-8` and form-urlencoded must also get 204) | CARRIED |\n| C1c | must_prove | \"gets 204\" | :121 | a 200/201 or a body-bearing success response | CARRIED |\n| C1d | must_prove | \"adds one row\" | :123 | no insert, or a double insert (fresh db per test, so the count must be exactly 1) | CARRIED |\n| C1e | must_prove | `created_at` comes from the server | :126, :127 | storing the body `timestamp` (1, far outside the [before, after] window) | CARRIED |\n| C1f | must_prove | `user_agent` comes from the server | :125 | ignoring the header, storing `\"\"` instead of NULL, or swapping it with referer (params :92-:96) | CARRIED |\n| C1g | must_prove | `referer` comes from the server | :125 | ignoring the header, storing `\"\"` instead of NULL, or swapping it with user_agent (params :92-:96) | CARRIED |\n| C2a | must_prove | \"400 for an invalid body\" | :134 | accepting, or failing with 500, on each of the 12 `REJECTED` bodies | CARRIED |\n| C2b | must_prove | the 400 \"adds no row\" | :137, :138-:139 | inserting before validating; the control rules out a route that never writes | CARRIED |\n| C2c | must_prove | \"429 over the route limit\" | :148, :149 | no limiter on the route, or a limit other than 90 (hardcoded 90 \u00d7 204 then 429) | CARRIED |\n| C2d | must_prove | the 429 \"adds no row\" | :150 | inserting before the limit check (a 91st row) | CARRIED |\n| D1 | docstring | \"204 with an empty body\" | :121 | a non-empty success body | CARRIED |\n| D2 | docstring | \"exactly one row\" | :123 | zero or two rows | CARRIED |\n| D3 | docstring | \"type, track_id, href and page_path as sent\" | :125 | a field that is dropped, rewritten or normalised | CARRIED |\n| D4 | docstring | \"track_id and href NULL on a page_view\" | :125 | storing `\"\"` or the explicit-null keys as anything but NULL (params :93, :95, :96) | CARRIED |\n| D5 | docstring | json, text/plain;charset=UTF-8 and form-urlencoded all accepted | :121 | a Content-Type gate | CARRIED |\n| D6 | docstring | \"created_at inside the [before, after] now_ms() window\" | :126 | a stale or non-integer stamp | CARRIED |\n| D7 | docstring | \"not the client timestamp 1\" | :127 | storing the body timestamp | CARRIED |\n| D8 | docstring | \"user_agent and referer equal to the request headers\" | :125 | a header that is not read | CARRIED |\n| D9 | docstring | \"NULL when that header was sent empty\" | :125 | storing `\"\"` (param :94) | CARRIED |\n| D10 | docstring | \"NULL when ... not sent at all\" | :125 | storing a default string (params :95, :96; `OPENER.addheaders = []` at :34) | CARRIED |\n| D11 | docstring | each listed refused body gets 400 | :134 | accepting any of empty, `{`, `[]`, `\\xff`, a bad type, track_id, href (mailto, lone surrogate), page_path or timestamp, or a page_view with a track_id | CARRIED |\n| D12 | docstring | \"a JSON string `error`\" | :135-:136 | an empty, non-JSON or non-string error body | CARRIED |\n| D13 | docstring | \"leaves the table empty\" | :137 | an insert on refusal | CARRIED |\n| D14 | docstring | \"a valid event posted after it on the same server is stored\" | :138-:139 | a route that never writes, or a server left unable to write by the refusal | CARRIED |\n| D15a | docstring | \"production 90-per-...\" limiter | :149, :148 | a limit other than 90 | CARRIED |\n| D15b | docstring | \"...-per-60 s\" window | none | nothing: the window is taken from `RATE_LIMIT_WINDOW_SECONDS` at :79 and no assertion depends on its value | UNCARRIED |\n| D16 | docstring | 91st gets 429 `{\"error\": \"Rate limit exceeded\"}` | :148 | a different status or body | CARRIED |\n| D17 | docstring | \"the 90 before it each got 204\" | :149 | an early 429 | CARRIED |\n| D18 | docstring | \"the table holds those 90 rows only\" | :150 | the 91st being stored | CARRIED |\n| D19 | docstring | \"203.0.113.19 is still stored\" | :151-:152 | a global (not per-address) limit, or a stopped server | CARRIED |\n| D20 | docstring | GET is 404 `{\"error\": \"Not found\"}` | :158 | GET serving the route | CARRIED |\n| D21 | docstring | GET \"stores nothing\" | :159 | GET inserting | CARRIED |\n| N1 | name | \"accepted event\" (204) | :121 | a refusal of a valid event | CARRIED |\n| N2 | name | \"stores one ... row\" | :123 | zero or duplicate rows | CARRIED |\n| N3 | name | \"server_stamped\" | :125-:127 | client-supplied stamps | CARRIED |\n| N4 | name | \"invalid body gets 400\" | :134 | accepting a malformed body | CARRIED |\n| N5 | name | \"and stores nothing\" (400) | :137 | an insert on refusal | CARRIED |\n| N6 | name | \"91st post from one address gets 429\" | :148-:149 | a missing or mis-set limit | CARRIED |\n| N7 | name | \"and stores nothing\" (429) / \"GET ... is not a route\" | :150, :158 | an insert past the limit; GET being served | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:5\n   D15b is UNCARRIED. The docstring claims a \"90-per-60 s route limiter\", but the window comes from `client_server.RATE_LIMIT_WINDOW_SECONDS` at :79 and no assertion depends on its value. A 600 s or 1 s window passes the same way. This is a docstring-only clause, so it does not block. Fix it by narrowing the sentence to \"90-request\" or by asserting the window value.\n2. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:99-112\n   `REJECTED` covers only malformed values. No case sits at or one past the length limits the code accepts: `track_id` 64 characters (`[a-z0-9_]{1,64}`), `page_path` 256, `href` 2048. A negative `timestamp` (refused at `timestamp < 0`) and a float timestamp are also untested. On the accepted side, nothing tests a request sent with no Content-Type header at all, which C1's \"any Content-Type\" covers.\n3. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:91-97\n   No accepted body carries its own `user_agent` or `referer` key. So C1f and C1g rule out an implementation that ignores the headers, but not one where a client-supplied body value takes priority over the header. No rule requires that case beyond the edge-of-input principle. `created_at` already gets the equivalent check through `CLIENT_TIMESTAMP`.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists `.un/skills/devsecops/config.json` and `tests/active/test_analytics_events.py`. I did not read either, because the test under audit does not import or exercise them.\n2. I could not find a handler that routes `/api/analytics/event` in `_serve_post` of client/backend/server.py (:442-:506), so I could not see how the route reads the body, Content-Type and headers. I judged bounds against `_validate_analytics_event` (:1260), the `ANALYTICS_*` constants (:70-:73) and the `analytics_events` schema in client/backend/lib/users_store.py.\n3. `fixtures_path` was not supplied. I read `client_backend` from tests/active/conftest.py:73-93; it uses a fresh `tmp_path` database per test.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. absence-only-assertion (rules/shape.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:158-159\n   assert (status, json.loads(body)) == (404, {\"error\": \"Not found\"})  # regression line, no clause\n   assert _rows(client_backend.db_path) == []  # regression line, no clause\n   This test fits the entry's \"delete the code under test entirely\" check. The 404 comes from the existing fallthrough at server.py:440, and the empty table needs no new code, so the test is green before phase 3 exists. It claims no `must_prove` clause and says it is a regression line, so it gates nothing. That is why this is a Recommendation and not a Critical finding. Don't count it as evidence for C1 or C2.\n2. hardcoded-spec-mirror (rules/shape.md), partial match \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:146, 149, 150\n   accepted = [_send(base, \"POST\", _body(CLICK), limited)[0] for _ in range(90)]\n   The limiter is built from `client_server.RATE_LIMIT_MAX_REQUESTS` (line 79), but the count is the literal 90 in three places. This meets the entry's fourth <how_to_spot> bullet: change the constant and the test file has to change too. It does not meet the first bullet, because nothing asserts the constant equals a literal. So no entry fully covers it. A wrong limiter still fails the test either way, so this does not block.\n\nPREDICTED FAILURE\n`test_accepted_event_stores_one_server_stamped_row` fails at line 121 on `(status, body) == (204, b\"\")`. The POST gets 404 `{\"error\": \"Not found\"}` because `_serve_post` (server.py:442-506) has no `/api/analytics/event` branch. The same cause fails `test_invalid_body_gets_400_and_stores_nothing` at line 134 (`status == 400`, got 404) and `test_91st_post_from_one_address_gets_429_and_stores_nothing` at line 148 (got `(404, {\"error\": \"Not found\"})`). `test_get_of_event_path_is_not_a_route` passes.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist (FileNotFoundError). Nothing in it was assessed.\n2. `fixtures_path` was not supplied. I read `client_backend`, `RateLimiter`, `ensure_user_schema` and `CLOSED_ENGINE` in tests/active/conftest.py and client/backend/lib/users_store.py. The `analytics_events` table exists there (users_store.py:67), so `_rows` will run against the schema. I did not read the `ClientBackend` helper's methods in conftest past its fields `base` and `db_path`.\n3. I answered the stub question from the assertion form; nothing was run. These assertions fail against a stub:\n   - A route that returns 204 without storing fails at line 123.\n   - Copying the body's `timestamp` into `created_at` fails at lines 126-127.\n   - A constant user_agent or referer fails the empty-header and absent-header cases at line 125.\n   - A route that always returns 400 fails its own control at line 138.\n   - A missing or post-insert rate-limit check fails at line 148 or line 150.\n   The loopback peer is trusted by default (server.py:52), so `X-Forwarded-For` resolves as the 429 test assumes.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (39 clauses: 11 must_prove, 21 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a valid event of either type\" is accepted | :125 | a route that stores only `outbound_click` or only `page_view` (both types are in `ACCEPTED` and `type` is compared) | CARRIED |\n| C1b | must_prove | \"with any Content-Type\" | :121 | a route that accepts only `application/json` (`text/plain;charset=UTF-8` and form-urlencoded must also get 204) | CARRIED |\n| C1c | must_prove | \"gets 204\" | :121 | a 200/201 or a body-bearing success response | CARRIED |\n| C1d | must_prove | \"adds one row\" | :123 | no insert, or a double insert (fresh db per test, so the count must be exactly 1) | CARRIED |\n| C1e | must_prove | `created_at` comes from the server | :126, :127 | storing the body `timestamp` (1, far outside the [before, after] window) | CARRIED |\n| C1f | must_prove | `user_agent` comes from the server | :125 | ignoring the header, storing `\"\"` instead of NULL, or swapping it with referer (params :92-:96) | CARRIED |\n| C1g | must_prove | `referer` comes from the server | :125 | ignoring the header, storing `\"\"` instead of NULL, or swapping it with user_agent (params :92-:96) | CARRIED |\n| C2a | must_prove | \"400 for an invalid body\" | :134 | accepting, or failing with 500, on each of the 12 `REJECTED` bodies | CARRIED |\n| C2b | must_prove | the 400 \"adds no row\" | :137, :138-:139 | inserting before validating; the control rules out a route that never writes | CARRIED |\n| C2c | must_prove | \"429 over the route limit\" | :148, :149 | no limiter on the route, or a limit other than 90 (hardcoded 90 \u00d7 204 then 429) | CARRIED |\n| C2d | must_prove | the 429 \"adds no row\" | :150 | inserting before the limit check (a 91st row) | CARRIED |\n| D1 | docstring | \"204 with an empty body\" | :121 | a non-empty success body | CARRIED |\n| D2 | docstring | \"exactly one row\" | :123 | zero or two rows | CARRIED |\n| D3 | docstring | \"type, track_id, href and page_path as sent\" | :125 | a field that is dropped, rewritten or normalised | CARRIED |\n| D4 | docstring | \"track_id and href NULL on a page_view\" | :125 | storing `\"\"` or the explicit-null keys as anything but NULL (params :93, :95, :96) | CARRIED |\n| D5 | docstring | json, text/plain;charset=UTF-8 and form-urlencoded all accepted | :121 | a Content-Type gate | CARRIED |\n| D6 | docstring | \"created_at inside the [before, after] now_ms() window\" | :126 | a stale or non-integer stamp | CARRIED |\n| D7 | docstring | \"not the client timestamp 1\" | :127 | storing the body timestamp | CARRIED |\n| D8 | docstring | \"user_agent and referer equal to the request headers\" | :125 | a header that is not read | CARRIED |\n| D9 | docstring | \"NULL when that header was sent empty\" | :125 | storing `\"\"` (param :94) | CARRIED |\n| D10 | docstring | \"NULL when ... not sent at all\" | :125 | storing a default string (params :95, :96; `OPENER.addheaders = []` at :34) | CARRIED |\n| D11 | docstring | each listed refused body gets 400 | :134 | accepting any of empty, `{`, `[]`, `\\xff`, a bad type, track_id, href (mailto, lone surrogate), page_path or timestamp, or a page_view with a track_id | CARRIED |\n| D12 | docstring | \"a JSON string `error`\" | :135-:136 | an empty, non-JSON or non-string error body | CARRIED |\n| D13 | docstring | \"leaves the table empty\" | :137 | an insert on refusal | CARRIED |\n| D14 | docstring | \"a valid event posted after it on the same server is stored\" | :138-:139 | a route that never writes, or a server left unable to write by the refusal | CARRIED |\n| D15a | docstring | \"production 90-per-...\" limiter | :149, :148 | a limit other than 90 | CARRIED |\n| D15b | docstring | \"...-per-60 s\" window | none | nothing: the window is taken from `RATE_LIMIT_WINDOW_SECONDS` at :79 and no assertion depends on its value | UNCARRIED |\n| D16 | docstring | 91st gets 429 `{\"error\": \"Rate limit exceeded\"}` | :148 | a different status or body | CARRIED |\n| D17 | docstring | \"the 90 before it each got 204\" | :149 | an early 429 | CARRIED |\n| D18 | docstring | \"the table holds those 90 rows only\" | :150 | the 91st being stored | CARRIED |\n| D19 | docstring | \"203.0.113.19 is still stored\" | :151-:152 | a global (not per-address) limit, or a stopped server | CARRIED |\n| D20 | docstring | GET is 404 `{\"error\": \"Not found\"}` | :158 | GET serving the route | CARRIED |\n| D21 | docstring | GET \"stores nothing\" | :159 | GET inserting | CARRIED |\n| N1 | name | \"accepted event\" (204) | :121 | a refusal of a valid event | CARRIED |\n| N2 | name | \"stores one ... row\" | :123 | zero or duplicate rows | CARRIED |\n| N3 | name | \"server_stamped\" | :125-:127 | client-supplied stamps | CARRIED |\n| N4 | name | \"invalid body gets 400\" | :134 | accepting a malformed body | CARRIED |\n| N5 | name | \"and stores nothing\" (400) | :137 | an insert on refusal | CARRIED |\n| N6 | name | \"91st post from one address gets 429\" | :148-:149 | a missing or mis-set limit | CARRIED |\n| N7 | name | \"and stores nothing\" (429) / \"GET ... is not a route\" | :150, :158 | an insert past the limit; GET being served | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:5\n   D15b is UNCARRIED. The docstring claims a \"90-per-60 s route limiter\", but the window comes from `client_server.RATE_LIMIT_WINDOW_SECONDS` at :79 and no assertion depends on its value. A 600 s or 1 s window passes the same way. This is a docstring-only clause, so it does not block. Fix it by narrowing the sentence to \"90-request\" or by asserting the window value.\n2. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:99-112\n   `REJECTED` covers only malformed values. No case sits at or one past the length limits the code accepts: `track_id` 64 characters (`[a-z0-9_]{1,64}`), `page_path` 256, `href` 2048. A negative `timestamp` (refused at `timestamp < 0`) and a float timestamp are also untested. On the accepted side, nothing tests a request sent with no Content-Type header at all, which C1's \"any Content-Type\" covers.\n3. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:91-97\n   No accepted body carries its own `user_agent` or `referer` key. So C1f and C1g rule out an implementation that ignores the headers, but not one where a client-supplied body value takes priority over the header. No rule requires that case beyond the edge-of-input principle. `created_at` already gets the equivalent check through `CLIENT_TIMESTAMP`.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists `.un/skills/devsecops/config.json` and `tests/active/test_analytics_events.py`. I did not read either, because the test under audit does not import or exercise them.\n2. I could not find a handler that routes `/api/analytics/event` in `_serve_post` of client/backend/server.py (:442-:506), so I could not see how the route reads the body, Content-Type and headers. I judged bounds against `_validate_analytics_event` (:1260), the `ANALYTICS_*` constants (:70-:73) and the `analytics_events` schema in client/backend/lib/users_store.py.\n3. `fixtures_path` was not supplied. I read `client_backend` from tests/active/conftest.py:73-93; it uses a fresh `tmp_path` database per test.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a valid event of either type\" is accepted",
            "assertion": ":125",
            "excludes": "a route that stores only `outbound_click` or only `page_view` (both types are in `ACCEPTED` and `type` is compared)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"with any Content-Type\"",
            "assertion": ":121",
            "excludes": "a route that accepts only `application/json` (`text/plain;charset=UTF-8` and form-urlencoded must also get 204)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"gets 204\"",
            "assertion": ":121",
            "excludes": "a 200/201 or a body-bearing success response",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"adds one row\"",
            "assertion": ":123",
            "excludes": "no insert, or a double insert (fresh db per test, so the count must be exactly 1)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "`created_at` comes from the server",
            "assertion": ":126, :127",
            "excludes": "storing the body `timestamp` (1, far outside the [before, after] window)",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "`user_agent` comes from the server",
            "assertion": ":125",
            "excludes": "ignoring the header, storing `\"\"` instead of NULL, or swapping it with referer (params :92-:96)",
            "status": "CARRIED"
          },
          {
            "id": "C1g",
            "source": "must_prove",
            "clause": "`referer` comes from the server",
            "assertion": ":125",
            "excludes": "ignoring the header, storing `\"\"` instead of NULL, or swapping it with user_agent (params :92-:96)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"400 for an invalid body\"",
            "assertion": ":134",
            "excludes": "accepting, or failing with 500, on each of the 12 `REJECTED` bodies",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "the 400 \"adds no row\"",
            "assertion": ":137, :138-:139",
            "excludes": "inserting before validating; the control rules out a route that never writes",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"429 over the route limit\"",
            "assertion": ":148, :149",
            "excludes": "no limiter on the route, or a limit other than 90 (hardcoded 90 \u00d7 204 then 429)",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "the 429 \"adds no row\"",
            "assertion": ":150",
            "excludes": "inserting before the limit check (a 91st row)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"204 with an empty body\"",
            "assertion": ":121",
            "excludes": "a non-empty success body",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"exactly one row\"",
            "assertion": ":123",
            "excludes": "zero or two rows",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"type, track_id, href and page_path as sent\"",
            "assertion": ":125",
            "excludes": "a field that is dropped, rewritten or normalised",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"track_id and href NULL on a page_view\"",
            "assertion": ":125",
            "excludes": "storing `\"\"` or the explicit-null keys as anything but NULL (params :93, :95, :96)",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "json, text/plain;charset=UTF-8 and form-urlencoded all accepted",
            "assertion": ":121",
            "excludes": "a Content-Type gate",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"created_at inside the [before, after] now_ms() window\"",
            "assertion": ":126",
            "excludes": "a stale or non-integer stamp",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"not the client timestamp 1\"",
            "assertion": ":127",
            "excludes": "storing the body timestamp",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"user_agent and referer equal to the request headers\"",
            "assertion": ":125",
            "excludes": "a header that is not read",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"NULL when that header was sent empty\"",
            "assertion": ":125",
            "excludes": "storing `\"\"` (param :94)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"NULL when ... not sent at all\"",
            "assertion": ":125",
            "excludes": "storing a default string (params :95, :96; `OPENER.addheaders = []` at :34)",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "each listed refused body gets 400",
            "assertion": ":134",
            "excludes": "accepting any of empty, `{`, `[]`, `\\xff`, a bad type, track_id, href (mailto, lone surrogate), page_path or timestamp, or a page_view with a track_id",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"a JSON string `error`\"",
            "assertion": ":135-:136",
            "excludes": "an empty, non-JSON or non-string error body",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"leaves the table empty\"",
            "assertion": ":137",
            "excludes": "an insert on refusal",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"a valid event posted after it on the same server is stored\"",
            "assertion": ":138-:139",
            "excludes": "a route that never writes, or a server left unable to write by the refusal",
            "status": "CARRIED"
          },
          {
            "id": "D15a",
            "source": "docstring",
            "clause": "\"production 90-per-...\" limiter",
            "assertion": ":149, :148",
            "excludes": "a limit other than 90",
            "status": "CARRIED"
          },
          {
            "id": "D15b",
            "source": "docstring",
            "clause": "\"...-per-60 s\" window",
            "assertion": "none",
            "excludes": "nothing: the window is taken from `RATE_LIMIT_WINDOW_SECONDS` at :79 and no assertion depends on its value",
            "status": "UNCARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "91st gets 429 `{\"error\": \"Rate limit exceeded\"}`",
            "assertion": ":148",
            "excludes": "a different status or body",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"the 90 before it each got 204\"",
            "assertion": ":149",
            "excludes": "an early 429",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"the table holds those 90 rows only\"",
            "assertion": ":150",
            "excludes": "the 91st being stored",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "\"203.0.113.19 is still stored\"",
            "assertion": ":151-:152",
            "excludes": "a global (not per-address) limit, or a stopped server",
            "status": "CARRIED"
          },
          {
            "id": "D20",
            "source": "docstring",
            "clause": "GET is 404 `{\"error\": \"Not found\"}`",
            "assertion": ":158",
            "excludes": "GET serving the route",
            "status": "CARRIED"
          },
          {
            "id": "D21",
            "source": "docstring",
            "clause": "GET \"stores nothing\"",
            "assertion": ":159",
            "excludes": "GET inserting",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"accepted event\" (204)",
            "assertion": ":121",
            "excludes": "a refusal of a valid event",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"stores one ... row\"",
            "assertion": ":123",
            "excludes": "zero or duplicate rows",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"server_stamped\"",
            "assertion": ":125-:127",
            "excludes": "client-supplied stamps",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"invalid body gets 400\"",
            "assertion": ":134",
            "excludes": "accepting a malformed body",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"and stores nothing\" (400)",
            "assertion": ":137",
            "excludes": "an insert on refusal",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"91st post from one address gets 429\"",
            "assertion": ":148-:149",
            "excludes": "a missing or mis-set limit",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"and stores nothing\" (429) / \"GET ... is not a route\"",
            "assertion": ":150, :158",
            "excludes": "an insert past the limit; GET being served",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:158-159\n   `assert (status, json.loads(body)) == (404, {\"error\": \"Not found\"})  # regression line, no clause`\n   `assert _rows(client_backend.db_path) == []  # regression line, no clause`\n   The current code already passes this test, because `_serve_get` ends at the 404 fallthrough at client/backend/server.py:440. If the code under test were deleted, the `absence-only-assertion <how_to_spot>` check would still pass. That entry does not fire, though: line 158 is a positive assertion on an exact status and body, and the test gates no clause in `must_prove`. As a regression guard it is correctly shaped. It adds nothing to the checkpoint's red, so it should not be counted as evidence for C1 or C2.\n\nPREDICTED FAILURE\n`/api/analytics/event` has no branch in `_serve_post` (client/backend/server.py:442-506), so every POST gets the 404 fallthrough at line 506. This produces four results:\n- Every `test_accepted_event_stores_one_server_stamped_row` case fails at line 121: `(404, b'{\"error\": \"Not found\"}') != (204, b\"\")`.\n- Every `test_invalid_body_gets_400_and_stores_nothing` case fails at line 134: `404 != 400`.\n- `test_91st_post_from_one_address_gets_429_and_stores_nothing` fails at line 148: `(404, {\"error\": \"Not found\"}) != (429, {\"error\": \"Rate limit exceeded\"})`.\n- `test_get_of_event_path_is_not_a_route` passes.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_analytics_events.py. That file does not exist in the worktree, so it was not read. It plays no part in this test's assertions.\n2. `fixtures_path` was not supplied. I read `client_backend`, `CLOSED_ENGINE`, `RateLimiter` and `ensure_user_schema` from tests/active/conftest.py instead, which the test imports at line 27. I read `analytics_events`, used by `_rows`, only as far as its schema and insert statement (client/backend/lib/users_store.py:67, 98).\n\nBasis for the passes (not findings):\n- **Anti-patterns:**\n  - `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep`: none. The test reads no `.md` file.\n  - `hardcoded-spec-mirror`: no code constant is compared to a literal. The limiter comes from `client_server.RATE_LIMIT_*` (line 79). The `90` at lines 146-150 is the route's behaviour seen over HTTP, not a constant's value.\n  - `tautological-assertion`: every expected value is a written-down literal (lines 92-96, 148). `created_at` is checked against an independent `now_ms()` window (line 126).\n  - `absence-only-assertion`: in the C2 tests, each empty-table claim has a positive control in the same test (lines 138-139, 149, 151-152).\n  - `echoed-literal`: server code sits between the request headers and body and the stored row. Deleting the insert or the header read turns lines 123-125 red.\n  - `single-value-pin`: user_agent and referer are each read in three states: sent, empty and absent (lines 92-96). Content-Type is read in three forms. `created_at` is pinned against `CLIENT_TIMESTAMP = 1` (lines 126-127). The limit is checked from both sides (lines 148-149), and against a second address (line 151).\n- **Ladder:** rung 1 with rung 3 side effects. The test drives a real `ClientBackendServer` over a socket and asserts on status, body and `analytics_events` rows. That is the highest rung these behavioural invariants support. It is not the anti-rung, and there is no downshift, so no comment is required.\n- **Stub question:** each plausible wrong implementation turns a specific line red:\n  - Returning 204 without writing fails at line 123.\n  - Storing the body's `timestamp` fails at lines 126-127.\n  - Ignoring headers, or storing `\"\"`, fails at line 125.\n  - Returning 400 for everything fails the control at line 138.\n  - Writing the row and then returning 400 fails at line 137.\n  - Skipping the limiter fails at line 148.\n  - An off-by-one in the limit fails at line 148 or line 149.\n  - One shared bucket instead of per-address limits fails at line 151. Loopback is in `DEFAULT_TRUSTED_PROXIES`, so the server honours the test's `X-Forwarded-For` header (server.py:52, 334).",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (40 clauses: 11 must_prove, 22 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a valid event of either type\" is accepted | :125 | a route that stores only `outbound_click` or only `page_view` (both types are in `ACCEPTED` and `type` is compared) | CARRIED |\n| C1b | must_prove | \"with any Content-Type\" | :121 | a route that accepts only `application/json` (`text/plain;charset=UTF-8` and form-urlencoded must also get 204, params :93-:96) | CARRIED |\n| C1c | must_prove | \"gets 204\" | :121 | a 200/201 or a success response with a body | CARRIED |\n| C1d | must_prove | \"adds one row\" | :123 | no insert, or a double insert (each test gets a fresh db through `tmp_path`) | CARRIED |\n| C1e | must_prove | `created_at` comes from the server | :126, :127 | storing the body `timestamp` (1, far outside the [before, after] window) | CARRIED |\n| C1f | must_prove | `user_agent` comes from the server | :125 | ignoring the header, storing `\"\"` instead of NULL, or swapping it with referer (params :92-:96) | CARRIED |\n| C1g | must_prove | `referer` comes from the server | :125 | ignoring the header, storing `\"\"` instead of NULL, or swapping it with user_agent (params :92-:96) | CARRIED |\n| C2a | must_prove | \"400 for an invalid body\" | :134 | accepting, or failing with 500, on any of the 12 `REJECTED` bodies | CARRIED |\n| C2b | must_prove | the 400 \"adds no row\" | :137, :138-:139 | inserting before validating; the control rules out a route that never writes | CARRIED |\n| C2c | must_prove | \"429 over the route limit\" | :148, :149 | no limiter on the route, or a limit other than 90 (90 \u00d7 204 then a 429, hardcoded) | CARRIED |\n| C2d | must_prove | the 429 \"adds no row\" | :150 | inserting before the limit check (a 91st row) | CARRIED |\n| D1 | docstring | \"204 with an empty body\" | :121 | a success response with a body | CARRIED |\n| D2 | docstring | \"exactly one row\" | :123 | zero or two rows | CARRIED |\n| D3 | docstring | \"type, track_id, href and page_path as sent\" | :125 | a field that is dropped, rewritten or normalised | CARRIED |\n| D4 | docstring | \"track_id and href NULL on a page_view\" | :125 | storing `\"\"`, or storing the explicit-null keys as anything but NULL (params :93, :95, :96) | CARRIED |\n| D5 | docstring | json, text/plain;charset=UTF-8 and form-urlencoded all accepted | :121 | a check that gates on Content-Type | CARRIED |\n| D6 | docstring | \"created_at inside the [before, after] now_ms() window\" | :126 | a stale stamp or one that is not an integer | CARRIED |\n| D7 | docstring | \"not the client timestamp 1\" | :127 | storing the body timestamp | CARRIED |\n| D8 | docstring | \"user_agent and referer equal to the request headers\" | :125 | a header that is never read | CARRIED |\n| D9 | docstring | \"NULL when that header was sent empty\" | :125 | storing `\"\"` (param :94) | CARRIED |\n| D10 | docstring | \"NULL when ... not sent at all\" | :125 | storing a default string (params :95, :96; `OPENER.addheaders = []` at :34) | CARRIED |\n| D11 | docstring | each listed refused body gets 400 | :134 | accepting any of: empty, `{`, `[]`, `\\xff`, a bad type, a bad track_id, a bad href (mailto, lone surrogate), a bad page_path or timestamp, or a page_view with a track_id | CARRIED |\n| D12 | docstring | \"a JSON string `error`\" | :135-:136 | an error body that is empty, not JSON, or not a string | CARRIED |\n| D13 | docstring | \"leaves the table empty\" | :137 | an insert on refusal | CARRIED |\n| D14 | docstring | \"a valid event posted after it on the same server is stored\" | :138-:139 | a route that never writes, or a refusal that leaves the server unable to write | CARRIED |\n| D15a | docstring | \"production ... 90 requests per address\" limiter | :149, :148 | a limit other than 90 | CARRIED |\n| D15b | docstring | withdrawn | n/a | n/a | CARRIED |\n| D16 | docstring | the 91st gets 429 `{\"error\": \"Rate limit exceeded\"}` | :148 | a different status or body | CARRIED |\n| D17 | docstring | \"the 90 before it each got 204\" | :149 | an early 429 | CARRIED |\n| D18 | docstring | \"the table holds those 90 rows only\" | :150 | storing the 91st | CARRIED |\n| D19 | docstring | \"203.0.113.19 is still stored\" | :151-:152 | a limit that is global rather than per address, or a server that has stopped (loopback is a trusted proxy, `server.py:52`, so `X-Forwarded-For` is honoured) | CARRIED |\n| D20 | docstring | GET is 404 `{\"error\": \"Not found\"}` | :158 | GET serving the route | CARRIED |\n| D21 | docstring | GET \"stores nothing\" | :159 | GET inserting | CARRIED |\n| N1 | name | \"accepted event\" (204) | :121 | refusing a valid event | CARRIED |\n| N2 | name | \"stores one ... row\" | :123 | zero or duplicate rows | CARRIED |\n| N3 | name | \"server_stamped\" | :125-:127 | stamps taken from the client | CARRIED |\n| N4 | name | \"invalid body gets 400\" | :134 | accepting a malformed body | CARRIED |\n| N5 | name | \"and stores nothing\" (400) | :137 | an insert on refusal | CARRIED |\n| N6 | name | \"91st post from one address gets 429\" | :148-:149 | a limit that is missing or set wrong | CARRIED |\n| N7 | name | \"and stores nothing\" (429) / \"GET ... is not a route\" | :150, :158 | an insert past the limit; GET being served | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:5\n   D15b was resolved by narrowing the prose, not by adding an assertion. The module docstring no longer claims \"90-per-60 s\". It now reads \"90 requests per address within its window, whose length is not asserted here\". The window length stays untested. The limiter at :79 still takes it from `RATE_LIMIT_WINDOW_SECONDS`, and no assertion depends on its value.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:92-96\n   C1 says \"with any Content-Type\". The test sends three declared types: application/json, text/plain;charset=UTF-8 and form-urlencoded. No case sends a POST with the Content-Type header left out, or with a fourth type. A route that refuses a request with no Content-Type would still pass. No ledger row names this, so it does not block.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:99-112\n   The validator has limits: page_path 1 to 256 characters, href at most 2048, track_id `[a-z0-9_]{1,64}`, timestamp \u2265 0. None of them is tested at max or one past max. A negative timestamp and a float timestamp are not tested either. `REJECTED` only covers malformed values and values of the wrong kind. No ledger row names this, so it does not block.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The `client_backend` fixture is imported from tests/active/conftest.py (:27). I judged independence from the parts of that file I found by search, :74-:89: a fresh `users.db` under `tmp_path` and `RateLimiter(1000, 60)`. I did not read the whole file.\n2. `code_under_test` lists tests/active/test_analytics_events.py and .un/skills/devsecops/config.json. I did not read either, because this test does not use them. The row insert helper (client/backend/lib/users_store.py:98) is not in `code_under_test` and was only found by search.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:158-159\n   `assert (status, json.loads(body)) == (404, {\"error\": \"Not found\"})  # regression line, no clause`\n   `assert _rows(client_backend.db_path) == []  # regression line, no clause`\n   The current code already passes this test, because `_serve_get` ends at the 404 fallthrough at client/backend/server.py:440. If the code under test were deleted, the `absence-only-assertion <how_to_spot>` check would still pass. That entry does not fire, though: line 158 is a positive assertion on an exact status and body, and the test gates no clause in `must_prove`. As a regression guard it is correctly shaped. It adds nothing to the checkpoint's red, so it should not be counted as evidence for C1 or C2.\n\nPREDICTED FAILURE\n`/api/analytics/event` has no branch in `_serve_post` (client/backend/server.py:442-506), so every POST gets the 404 fallthrough at line 506. This produces four results:\n- Every `test_accepted_event_stores_one_server_stamped_row` case fails at line 121: `(404, b'{\"error\": \"Not found\"}') != (204, b\"\")`.\n- Every `test_invalid_body_gets_400_and_stores_nothing` case fails at line 134: `404 != 400`.\n- `test_91st_post_from_one_address_gets_429_and_stores_nothing` fails at line 148: `(404, {\"error\": \"Not found\"}) != (429, {\"error\": \"Rate limit exceeded\"})`.\n- `test_get_of_event_path_is_not_a_route` passes.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_analytics_events.py. That file does not exist in the worktree, so it was not read. It plays no part in this test's assertions.\n2. `fixtures_path` was not supplied. I read `client_backend`, `CLOSED_ENGINE`, `RateLimiter` and `ensure_user_schema` from tests/active/conftest.py instead, which the test imports at line 27. I read `analytics_events`, used by `_rows`, only as far as its schema and insert statement (client/backend/lib/users_store.py:67, 98).\n\nBasis for the passes (not findings):\n- **Anti-patterns:**\n  - `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep`: none. The test reads no `.md` file.\n  - `hardcoded-spec-mirror`: no code constant is compared to a literal. The limiter comes from `client_server.RATE_LIMIT_*` (line 79). The `90` at lines 146-150 is the route's behaviour seen over HTTP, not a constant's value.\n  - `tautological-assertion`: every expected value is a written-down literal (lines 92-96, 148). `created_at` is checked against an independent `now_ms()` window (line 126).\n  - `absence-only-assertion`: in the C2 tests, each empty-table claim has a positive control in the same test (lines 138-139, 149, 151-152).\n  - `echoed-literal`: server code sits between the request headers and body and the stored row. Deleting the insert or the header read turns lines 123-125 red.\n  - `single-value-pin`: user_agent and referer are each read in three states: sent, empty and absent (lines 92-96). Content-Type is read in three forms. `created_at` is pinned against `CLIENT_TIMESTAMP = 1` (lines 126-127). The limit is checked from both sides (lines 148-149), and against a second address (line 151).\n- **Ladder:** rung 1 with rung 3 side effects. The test drives a real `ClientBackendServer` over a socket and asserts on status, body and `analytics_events` rows. That is the highest rung these behavioural invariants support. It is not the anti-rung, and there is no downshift, so no comment is required.\n- **Stub question:** each plausible wrong implementation turns a specific line red:\n  - Returning 204 without writing fails at line 123.\n  - Storing the body's `timestamp` fails at lines 126-127.\n  - Ignoring headers, or storing `\"\"`, fails at line 125.\n  - Returning 400 for everything fails the control at line 138.\n  - Writing the row and then returning 400 fails at line 137.\n  - Skipping the limiter fails at line 148.\n  - An off-by-one in the limit fails at line 148 or line 149.\n  - One shared bucket instead of per-address limits fails at line 151. Loopback is in `DEFAULT_TRUSTED_PROXIES`, so the server honours the test's `X-Forwarded-For` header (server.py:52, 334).\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (40 clauses: 11 must_prove, 22 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a valid event of either type\" is accepted | :125 | a route that stores only `outbound_click` or only `page_view` (both types are in `ACCEPTED` and `type` is compared) | CARRIED |\n| C1b | must_prove | \"with any Content-Type\" | :121 | a route that accepts only `application/json` (`text/plain;charset=UTF-8` and form-urlencoded must also get 204, params :93-:96) | CARRIED |\n| C1c | must_prove | \"gets 204\" | :121 | a 200/201 or a success response with a body | CARRIED |\n| C1d | must_prove | \"adds one row\" | :123 | no insert, or a double insert (each test gets a fresh db through `tmp_path`) | CARRIED |\n| C1e | must_prove | `created_at` comes from the server | :126, :127 | storing the body `timestamp` (1, far outside the [before, after] window) | CARRIED |\n| C1f | must_prove | `user_agent` comes from the server | :125 | ignoring the header, storing `\"\"` instead of NULL, or swapping it with referer (params :92-:96) | CARRIED |\n| C1g | must_prove | `referer` comes from the server | :125 | ignoring the header, storing `\"\"` instead of NULL, or swapping it with user_agent (params :92-:96) | CARRIED |\n| C2a | must_prove | \"400 for an invalid body\" | :134 | accepting, or failing with 500, on any of the 12 `REJECTED` bodies | CARRIED |\n| C2b | must_prove | the 400 \"adds no row\" | :137, :138-:139 | inserting before validating; the control rules out a route that never writes | CARRIED |\n| C2c | must_prove | \"429 over the route limit\" | :148, :149 | no limiter on the route, or a limit other than 90 (90 \u00d7 204 then a 429, hardcoded) | CARRIED |\n| C2d | must_prove | the 429 \"adds no row\" | :150 | inserting before the limit check (a 91st row) | CARRIED |\n| D1 | docstring | \"204 with an empty body\" | :121 | a success response with a body | CARRIED |\n| D2 | docstring | \"exactly one row\" | :123 | zero or two rows | CARRIED |\n| D3 | docstring | \"type, track_id, href and page_path as sent\" | :125 | a field that is dropped, rewritten or normalised | CARRIED |\n| D4 | docstring | \"track_id and href NULL on a page_view\" | :125 | storing `\"\"`, or storing the explicit-null keys as anything but NULL (params :93, :95, :96) | CARRIED |\n| D5 | docstring | json, text/plain;charset=UTF-8 and form-urlencoded all accepted | :121 | a check that gates on Content-Type | CARRIED |\n| D6 | docstring | \"created_at inside the [before, after] now_ms() window\" | :126 | a stale stamp or one that is not an integer | CARRIED |\n| D7 | docstring | \"not the client timestamp 1\" | :127 | storing the body timestamp | CARRIED |\n| D8 | docstring | \"user_agent and referer equal to the request headers\" | :125 | a header that is never read | CARRIED |\n| D9 | docstring | \"NULL when that header was sent empty\" | :125 | storing `\"\"` (param :94) | CARRIED |\n| D10 | docstring | \"NULL when ... not sent at all\" | :125 | storing a default string (params :95, :96; `OPENER.addheaders = []` at :34) | CARRIED |\n| D11 | docstring | each listed refused body gets 400 | :134 | accepting any of: empty, `{`, `[]`, `\\xff`, a bad type, a bad track_id, a bad href (mailto, lone surrogate), a bad page_path or timestamp, or a page_view with a track_id | CARRIED |\n| D12 | docstring | \"a JSON string `error`\" | :135-:136 | an error body that is empty, not JSON, or not a string | CARRIED |\n| D13 | docstring | \"leaves the table empty\" | :137 | an insert on refusal | CARRIED |\n| D14 | docstring | \"a valid event posted after it on the same server is stored\" | :138-:139 | a route that never writes, or a refusal that leaves the server unable to write | CARRIED |\n| D15a | docstring | \"production ... 90 requests per address\" limiter | :149, :148 | a limit other than 90 | CARRIED |\n| D15b | docstring | withdrawn | n/a | n/a | CARRIED |\n| D16 | docstring | the 91st gets 429 `{\"error\": \"Rate limit exceeded\"}` | :148 | a different status or body | CARRIED |\n| D17 | docstring | \"the 90 before it each got 204\" | :149 | an early 429 | CARRIED |\n| D18 | docstring | \"the table holds those 90 rows only\" | :150 | storing the 91st | CARRIED |\n| D19 | docstring | \"203.0.113.19 is still stored\" | :151-:152 | a limit that is global rather than per address, or a server that has stopped (loopback is a trusted proxy, `server.py:52`, so `X-Forwarded-For` is honoured) | CARRIED |\n| D20 | docstring | GET is 404 `{\"error\": \"Not found\"}` | :158 | GET serving the route | CARRIED |\n| D21 | docstring | GET \"stores nothing\" | :159 | GET inserting | CARRIED |\n| N1 | name | \"accepted event\" (204) | :121 | refusing a valid event | CARRIED |\n| N2 | name | \"stores one ... row\" | :123 | zero or duplicate rows | CARRIED |\n| N3 | name | \"server_stamped\" | :125-:127 | stamps taken from the client | CARRIED |\n| N4 | name | \"invalid body gets 400\" | :134 | accepting a malformed body | CARRIED |\n| N5 | name | \"and stores nothing\" (400) | :137 | an insert on refusal | CARRIED |\n| N6 | name | \"91st post from one address gets 429\" | :148-:149 | a limit that is missing or set wrong | CARRIED |\n| N7 | name | \"and stores nothing\" (429) / \"GET ... is not a route\" | :150, :158 | an insert past the limit; GET being served | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:5\n   D15b was resolved by narrowing the prose, not by adding an assertion. The module docstring no longer claims \"90-per-60 s\". It now reads \"90 requests per address within its window, whose length is not asserted here\". The window length stays untested. The limiter at :79 still takes it from `RATE_LIMIT_WINDOW_SECONDS`, and no assertion depends on its value.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:92-96\n   C1 says \"with any Content-Type\". The test sends three declared types: application/json, text/plain;charset=UTF-8 and form-urlencoded. No case sends a POST with the Content-Type header left out, or with a fourth type. A route that refuses a request with no Content-Type would still pass. No ledger row names this, so it does not block.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase3.py:99-112\n   The validator has limits: page_path 1 to 256 characters, href at most 2048, track_id `[a-z0-9_]{1,64}`, timestamp \u2265 0. None of them is tested at max or one past max. A negative timestamp and a float timestamp are not tested either. `REJECTED` only covers malformed values and values of the wrong kind. No ledger row names this, so it does not block.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The `client_backend` fixture is imported from tests/active/conftest.py (:27). I judged independence from the parts of that file I found by search, :74-:89: a fresh `users.db` under `tmp_path` and `RateLimiter(1000, 60)`. I did not read the whole file.\n2. `code_under_test` lists tests/active/test_analytics_events.py and .un/skills/devsecops/config.json. I did not read either, because this test does not use them. The row insert helper (client/backend/lib/users_store.py:98) is not in `code_under_test` and was only found by search.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a valid event of either type\" is accepted",
            "assertion": ":125",
            "excludes": "a route that stores only `outbound_click` or only `page_view` (both types are in `ACCEPTED` and `type` is compared)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"with any Content-Type\"",
            "assertion": ":121",
            "excludes": "a route that accepts only `application/json` (`text/plain;charset=UTF-8` and form-urlencoded must also get 204, params :93-:96)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"gets 204\"",
            "assertion": ":121",
            "excludes": "a 200/201 or a success response with a body",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"adds one row\"",
            "assertion": ":123",
            "excludes": "no insert, or a double insert (each test gets a fresh db through `tmp_path`)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "`created_at` comes from the server",
            "assertion": ":126, :127",
            "excludes": "storing the body `timestamp` (1, far outside the [before, after] window)",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "`user_agent` comes from the server",
            "assertion": ":125",
            "excludes": "ignoring the header, storing `\"\"` instead of NULL, or swapping it with referer (params :92-:96)",
            "status": "CARRIED"
          },
          {
            "id": "C1g",
            "source": "must_prove",
            "clause": "`referer` comes from the server",
            "assertion": ":125",
            "excludes": "ignoring the header, storing `\"\"` instead of NULL, or swapping it with user_agent (params :92-:96)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"400 for an invalid body\"",
            "assertion": ":134",
            "excludes": "accepting, or failing with 500, on any of the 12 `REJECTED` bodies",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "the 400 \"adds no row\"",
            "assertion": ":137, :138-:139",
            "excludes": "inserting before validating; the control rules out a route that never writes",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"429 over the route limit\"",
            "assertion": ":148, :149",
            "excludes": "no limiter on the route, or a limit other than 90 (90 \u00d7 204 then a 429, hardcoded)",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "the 429 \"adds no row\"",
            "assertion": ":150",
            "excludes": "inserting before the limit check (a 91st row)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"204 with an empty body\"",
            "assertion": ":121",
            "excludes": "a success response with a body",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"exactly one row\"",
            "assertion": ":123",
            "excludes": "zero or two rows",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"type, track_id, href and page_path as sent\"",
            "assertion": ":125",
            "excludes": "a field that is dropped, rewritten or normalised",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"track_id and href NULL on a page_view\"",
            "assertion": ":125",
            "excludes": "storing `\"\"`, or storing the explicit-null keys as anything but NULL (params :93, :95, :96)",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "json, text/plain;charset=UTF-8 and form-urlencoded all accepted",
            "assertion": ":121",
            "excludes": "a check that gates on Content-Type",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"created_at inside the [before, after] now_ms() window\"",
            "assertion": ":126",
            "excludes": "a stale stamp or one that is not an integer",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"not the client timestamp 1\"",
            "assertion": ":127",
            "excludes": "storing the body timestamp",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"user_agent and referer equal to the request headers\"",
            "assertion": ":125",
            "excludes": "a header that is never read",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"NULL when that header was sent empty\"",
            "assertion": ":125",
            "excludes": "storing `\"\"` (param :94)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"NULL when ... not sent at all\"",
            "assertion": ":125",
            "excludes": "storing a default string (params :95, :96; `OPENER.addheaders = []` at :34)",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "each listed refused body gets 400",
            "assertion": ":134",
            "excludes": "accepting any of: empty, `{`, `[]`, `\\xff`, a bad type, a bad track_id, a bad href (mailto, lone surrogate), a bad page_path or timestamp, or a page_view with a track_id",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"a JSON string `error`\"",
            "assertion": ":135-:136",
            "excludes": "an error body that is empty, not JSON, or not a string",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"leaves the table empty\"",
            "assertion": ":137",
            "excludes": "an insert on refusal",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"a valid event posted after it on the same server is stored\"",
            "assertion": ":138-:139",
            "excludes": "a route that never writes, or a refusal that leaves the server unable to write",
            "status": "CARRIED"
          },
          {
            "id": "D15a",
            "source": "docstring",
            "clause": "\"production ... 90 requests per address\" limiter",
            "assertion": ":149, :148",
            "excludes": "a limit other than 90",
            "status": "CARRIED"
          },
          {
            "id": "D15b",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "the 91st gets 429 `{\"error\": \"Rate limit exceeded\"}`",
            "assertion": ":148",
            "excludes": "a different status or body",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"the 90 before it each got 204\"",
            "assertion": ":149",
            "excludes": "an early 429",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"the table holds those 90 rows only\"",
            "assertion": ":150",
            "excludes": "storing the 91st",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "\"203.0.113.19 is still stored\"",
            "assertion": ":151-:152",
            "excludes": "a limit that is global rather than per address, or a server that has stopped (loopback is a trusted proxy, `server.py:52`, so `X-Forwarded-For` is honoured)",
            "status": "CARRIED"
          },
          {
            "id": "D20",
            "source": "docstring",
            "clause": "GET is 404 `{\"error\": \"Not found\"}`",
            "assertion": ":158",
            "excludes": "GET serving the route",
            "status": "CARRIED"
          },
          {
            "id": "D21",
            "source": "docstring",
            "clause": "GET \"stores nothing\"",
            "assertion": ":159",
            "excludes": "GET inserting",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"accepted event\" (204)",
            "assertion": ":121",
            "excludes": "refusing a valid event",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"stores one ... row\"",
            "assertion": ":123",
            "excludes": "zero or duplicate rows",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"server_stamped\"",
            "assertion": ":125-:127",
            "excludes": "stamps taken from the client",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"invalid body gets 400\"",
            "assertion": ":134",
            "excludes": "accepting a malformed body",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"and stores nothing\" (400)",
            "assertion": ":137",
            "excludes": "an insert on refusal",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"91st post from one address gets 429\"",
            "assertion": ":148-:149",
            "excludes": "a limit that is missing or set wrong",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"and stores nothing\" (429) / \"GET ... is not a route\"",
            "assertion": ":150, :158",
            "excludes": "an insert past the limit; GET being served",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_18_about_outbound_click_tracking_phase4.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:140\n   assert [json.loads(send[\"body\"]) for send in sends] == [{\"type\": \"page_view\", ...}, {\"type\": \"outbound_click\", \"track_id\": \"about_patreon\", \"href\": TRACKED_HREF, ...}]\n   The rule wants the output checked at two inputs that must give different readings, so the test can tell that the output follows the input. This test runs the click feature at one value only. Line 83 builds the only tracked element with `\"data-track-id\": \"about_patreon\"`, and line 140 expects that same literal back. Nowhere in the file is there a second tracked anchor with a different id. A module that finds `closest(\"a[data-track-id]\")` and then sends a hard-coded `track_id: \"about_patreon\"` passes all four parametrised modes, which is the entry's first `<how_to_spot>` bullet. `page_path` avoids this: line 28 varies it by mode. Fix: add a second tracked anchor with a different `data-track-id`, click it too, and assert both outbound_click bodies in order.\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll four parametrised cases of `test_import_and_tracked_click_send_two_events_by_beacon_or_keepalive_fetch` should error in fixture setup. `client/frontend/src/about-analytics.ts` doesn't exist, so esbuild fails and `assert result.returncode == 0, result.stderr` at line 116 fails with esbuild's could-not-resolve error. `test_built_about_page_loads_a_bundled_asset_with_the_event_route` should fail at line 161 on `assert scripts, page`. No local `dev-pages/about.html` exists, so the skip at line 155 doesn't trigger. The template the build uses has no `<script src>`, and nothing in `client/frontend` contains `/api/analytics/event` yet.\n\nNOT ASSESSED\n1. `code_under_test` listed client/frontend/src/about-analytics.ts, which does not resolve. I answered the stub question from the assertion form and the runner stubs alone.\n2. `code_under_test` listed tests/active/test_analytics_events.py, which does not resolve. I could not read or assess it.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (20 clauses: 7 must_prove, 11 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"importing the module sends one `page_view`\" | :140 | no page_view on import, a page_view with extra or missing fields, or a page_view that isn't sent first | CARRIED |\n| C1b | must_prove | \"one `outbound_click` per tracked click\" | :140 | nothing per-click: only one tracked target is clicked (:85), so a module-level \"already sent\" flag or a once-only listener also passes | UNCARRIED |\n| C1c | must_prove | sends by beacon when `sendBeacon` accepts | :142 | sending by fetch when beacon would do, a beacon body that isn't JSON-typed, or a fetch beside the beacon (the count at :139 catches that) | CARRIED |\n| C1d | must_prove | falls back to keepalive `fetch` when `sendBeacon` is unavailable | :144 (mode `missing`), :145 | dropping the event when there is no beacon, or a fetch without keepalive, POST or JSON | CARRIED |\n| C1e | must_prove | falls back when `sendBeacon` refuses (returns false) | :144 (mode `false`), :145 | ignoring the false return and sending nothing | CARRIED |\n| C1f | must_prove | falls back when `sendBeacon` throws | :144 (mode `throws`), :147 | letting the throw escape, or no fetch after the throw | CARRIED |\n| C2 | must_prove | vite build of About template references a bundled `/assets/*.js` entry containing `/api/analytics/event` | :161, :162 | a template with no script, or a script that doesn't bundle the event route (the route isn't in `src/` now, so nothing else supplies it) | CARRIED |\n| D1 | docstring | untracked link, Text-like target and span-in-tracked-link send \"exactly two events\" to the event URL | :139 | an event for the untracked or Text-like target, a URL built from `location.origin` (PAGE_ORIGIN is different), `//api` from joining the strings | CARRIED |\n| D2 | docstring | body shapes, \"with nothing else in either body\" | :140 | extra fields or wrong field values (whole-dict equality) | CARRIED |\n| D3 | docstring | `page_path` is the stubbed `location.pathname` by mode | :140 | `page_path` hardcoded to `/about` or to `/about.html` (the modes change it) | CARRIED |\n| D4 | docstring | sendBeacon true \u2192 `application/json` Blob beacons, \"`fetch` is never called\" | :142, :139 | an untyped or string beacon, any fetch call (it would be a third send) | CARRIED |\n| D5a | docstring | false/throws: \"each is first offered to the bound `navigator.sendBeacon`\" | :145 | skipping the beacon, a detached `sendBeacon` (the stub throws Illegal invocation, which leaves beacons at 0) | CARRIED |\n| D5b | docstring | \"first ... and then posted by `fetch`\" \u2014 beacon before fetch | none | nothing: :144/:145 count beacon and fetch calls separately and never compare their order | UNCARRIED |\n| D6 | docstring | \"as they are when `sendBeacon` is missing\" | :144, :145 | beacon count at 0, fetch shape the same as the fallback modes | CARRIED |\n| D7 | docstring | \"exactly one `click` listener is on `document`\" | :146 | no listener, several listeners, or listeners of another type | CARRIED |\n| D8 | docstring | \"no handler throws\" | :147 | a throw on the Text-like target (no `closest`) or on the untracked link | CARRIED |\n| D9 | docstring | \"no default is prevented\" | :149 | `preventDefault` on any of the three clicks | CARRIED |\n| D10 | docstring | \"no rejection goes unhandled\" | :148 | a fetch with no `.catch` on the rejecting stub | CARRIED |\n| N1 | name | \"import and tracked click send two events by beacon or keepalive fetch\" | :139, :140, :142, :144 | wrong count, wrong order or wrong transport | CARRIED |\n| N2 | name | \"built about page loads a bundled asset with the event route\" | :161, :162 | no script asset, or an asset without the route | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:85 / :140\n   `const targets = [element(\"a\", { href: \"https://example.org/untracked\" }, body), { nodeType: 3, ... }, element(\"span\", {}, tracked)];`\n   `assert [json.loads(send[\"body\"]) for send in sends] == [{\"type\": \"page_view\", ...}, {\"type\": \"outbound_click\", ...}]`\n   C1 claims one `outbound_click` per tracked click, which is an \"X per Y\" claim. The test clicks a tracked target only once, so it proves that one click sends one event, not that every click does. An implementation that sends `outbound_click` only once per page load passes all four modes. That covers a module-level sent flag, de-duplication by `track_id`, and a listener that removes itself after its first tracked hit. The rule requires a second Y: click the tracked target again (or a second tracked link) and assert two `outbound_click` bodies.\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:3\n   D5b is UNCARRIED. The module docstring says each event is \"first offered to the bound `navigator.sendBeacon` and then posted by `fetch`\". :144 and :145 count the two transports separately, so the order is never observed. Either record beacon attempts in the same ordered `sends` log as the fetches, or narrow the sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:83\n   The tracked link always has a non-empty `data-track-id` and an `href`. Nothing tests an empty `data-track-id=\"\"` or a tracked anchor with no `href`, which are the edges of what the click handler accepts.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed `client/frontend/src/about-analytics.ts` (NEW), which does not exist. Bounds and the abnormal path were judged from the test, the `must_prove` text and the runner stub alone. The module's real input handling was not read.\n2. `code_under_test` listed `tests/active/test_analytics_events.py` (EDITED), which does not exist. Its edits were not assessed.\n3. `client/frontend/dev-pages/about.template.html` as it stands has no `<script>`, so the EDITED version was not available. C2 was judged against `vite.config.ts` and the test. No `dev-pages/about.html` override exists right now, so the skip at :154 does not fire here.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:140\n   assert [json.loads(send[\"body\"]) for send in sends] == [{\"type\": \"page_view\", ...}, {\"type\": \"outbound_click\", \"track_id\": \"about_patreon\", \"href\": TRACKED_HREF, ...}]\n   The rule wants the output checked at two inputs that must give different readings, so the test can tell that the output follows the input. This test runs the click feature at one value only. Line 83 builds the only tracked element with `\"data-track-id\": \"about_patreon\"`, and line 140 expects that same literal back. Nowhere in the file is there a second tracked anchor with a different id. A module that finds `closest(\"a[data-track-id]\")` and then sends a hard-coded `track_id: \"about_patreon\"` passes all four parametrised modes, which is the entry's first `<how_to_spot>` bullet. `page_path` avoids this: line 28 varies it by mode. Fix: add a second tracked anchor with a different `data-track-id`, click it too, and assert both outbound_click bodies in order.\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll four parametrised cases of `test_import_and_tracked_click_send_two_events_by_beacon_or_keepalive_fetch` should error in fixture setup. `client/frontend/src/about-analytics.ts` doesn't exist, so esbuild fails and `assert result.returncode == 0, result.stderr` at line 116 fails with esbuild's could-not-resolve error. `test_built_about_page_loads_a_bundled_asset_with_the_event_route` should fail at line 161 on `assert scripts, page`. No local `dev-pages/about.html` exists, so the skip at line 155 doesn't trigger. The template the build uses has no `<script src>`, and nothing in `client/frontend` contains `/api/analytics/event` yet.\n\nNOT ASSESSED\n1. `code_under_test` listed client/frontend/src/about-analytics.ts, which does not resolve. I answered the stub question from the assertion form and the runner stubs alone.\n2. `code_under_test` listed tests/active/test_analytics_events.py, which does not resolve. I could not read or assess it.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (20 clauses: 7 must_prove, 11 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"importing the module sends one `page_view`\" | :140 | no page_view on import, a page_view with extra or missing fields, or a page_view that isn't sent first | CARRIED |\n| C1b | must_prove | \"one `outbound_click` per tracked click\" | :140 | nothing per-click: only one tracked target is clicked (:85), so a module-level \"already sent\" flag or a once-only listener also passes | UNCARRIED |\n| C1c | must_prove | sends by beacon when `sendBeacon` accepts | :142 | sending by fetch when beacon would do, a beacon body that isn't JSON-typed, or a fetch beside the beacon (the count at :139 catches that) | CARRIED |\n| C1d | must_prove | falls back to keepalive `fetch` when `sendBeacon` is unavailable | :144 (mode `missing`), :145 | dropping the event when there is no beacon, or a fetch without keepalive, POST or JSON | CARRIED |\n| C1e | must_prove | falls back when `sendBeacon` refuses (returns false) | :144 (mode `false`), :145 | ignoring the false return and sending nothing | CARRIED |\n| C1f | must_prove | falls back when `sendBeacon` throws | :144 (mode `throws`), :147 | letting the throw escape, or no fetch after the throw | CARRIED |\n| C2 | must_prove | vite build of About template references a bundled `/assets/*.js` entry containing `/api/analytics/event` | :161, :162 | a template with no script, or a script that doesn't bundle the event route (the route isn't in `src/` now, so nothing else supplies it) | CARRIED |\n| D1 | docstring | untracked link, Text-like target and span-in-tracked-link send \"exactly two events\" to the event URL | :139 | an event for the untracked or Text-like target, a URL built from `location.origin` (PAGE_ORIGIN is different), `//api` from joining the strings | CARRIED |\n| D2 | docstring | body shapes, \"with nothing else in either body\" | :140 | extra fields or wrong field values (whole-dict equality) | CARRIED |\n| D3 | docstring | `page_path` is the stubbed `location.pathname` by mode | :140 | `page_path` hardcoded to `/about` or to `/about.html` (the modes change it) | CARRIED |\n| D4 | docstring | sendBeacon true \u2192 `application/json` Blob beacons, \"`fetch` is never called\" | :142, :139 | an untyped or string beacon, any fetch call (it would be a third send) | CARRIED |\n| D5a | docstring | false/throws: \"each is first offered to the bound `navigator.sendBeacon`\" | :145 | skipping the beacon, a detached `sendBeacon` (the stub throws Illegal invocation, which leaves beacons at 0) | CARRIED |\n| D5b | docstring | \"first ... and then posted by `fetch`\" \u2014 beacon before fetch | none | nothing: :144/:145 count beacon and fetch calls separately and never compare their order | UNCARRIED |\n| D6 | docstring | \"as they are when `sendBeacon` is missing\" | :144, :145 | beacon count at 0, fetch shape the same as the fallback modes | CARRIED |\n| D7 | docstring | \"exactly one `click` listener is on `document`\" | :146 | no listener, several listeners, or listeners of another type | CARRIED |\n| D8 | docstring | \"no handler throws\" | :147 | a throw on the Text-like target (no `closest`) or on the untracked link | CARRIED |\n| D9 | docstring | \"no default is prevented\" | :149 | `preventDefault` on any of the three clicks | CARRIED |\n| D10 | docstring | \"no rejection goes unhandled\" | :148 | a fetch with no `.catch` on the rejecting stub | CARRIED |\n| N1 | name | \"import and tracked click send two events by beacon or keepalive fetch\" | :139, :140, :142, :144 | wrong count, wrong order or wrong transport | CARRIED |\n| N2 | name | \"built about page loads a bundled asset with the event route\" | :161, :162 | no script asset, or an asset without the route | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:85 / :140\n   `const targets = [element(\"a\", { href: \"https://example.org/untracked\" }, body), { nodeType: 3, ... }, element(\"span\", {}, tracked)];`\n   `assert [json.loads(send[\"body\"]) for send in sends] == [{\"type\": \"page_view\", ...}, {\"type\": \"outbound_click\", ...}]`\n   C1 claims one `outbound_click` per tracked click, which is an \"X per Y\" claim. The test clicks a tracked target only once, so it proves that one click sends one event, not that every click does. An implementation that sends `outbound_click` only once per page load passes all four modes. That covers a module-level sent flag, de-duplication by `track_id`, and a listener that removes itself after its first tracked hit. The rule requires a second Y: click the tracked target again (or a second tracked link) and assert two `outbound_click` bodies.\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:3\n   D5b is UNCARRIED. The module docstring says each event is \"first offered to the bound `navigator.sendBeacon` and then posted by `fetch`\". :144 and :145 count the two transports separately, so the order is never observed. Either record beacon attempts in the same ordered `sends` log as the fetches, or narrow the sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:83\n   The tracked link always has a non-empty `data-track-id` and an `href`. Nothing tests an empty `data-track-id=\"\"` or a tracked anchor with no `href`, which are the edges of what the click handler accepts.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed `client/frontend/src/about-analytics.ts` (NEW), which does not exist. Bounds and the abnormal path were judged from the test, the `must_prove` text and the runner stub alone. The module's real input handling was not read.\n2. `code_under_test` listed `tests/active/test_analytics_events.py` (EDITED), which does not exist. Its edits were not assessed.\n3. `client/frontend/dev-pages/about.template.html` as it stands has no `<script>`, so the EDITED version was not available. C2 was judged against `vite.config.ts` and the test. No `dev-pages/about.html` override exists right now, so the skip at :154 does not fire here.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"importing the module sends one `page_view`\"",
            "assertion": ":140",
            "excludes": "no page_view on import, a page_view with extra or missing fields, or a page_view that isn't sent first",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"one `outbound_click` per tracked click\"",
            "assertion": ":140",
            "excludes": "nothing per-click: only one tracked target is clicked (:85), so a module-level \"already sent\" flag or a once-only listener also passes",
            "status": "UNCARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "sends by beacon when `sendBeacon` accepts",
            "assertion": ":142",
            "excludes": "sending by fetch when beacon would do, a beacon body that isn't JSON-typed, or a fetch beside the beacon (the count at :139 catches that)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "falls back to keepalive `fetch` when `sendBeacon` is unavailable",
            "assertion": ":144 (mode `missing`), :145",
            "excludes": "dropping the event when there is no beacon, or a fetch without keepalive, POST or JSON",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "falls back when `sendBeacon` refuses (returns false)",
            "assertion": ":144 (mode `false`), :145",
            "excludes": "ignoring the false return and sending nothing",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "falls back when `sendBeacon` throws",
            "assertion": ":144 (mode `throws`), :147",
            "excludes": "letting the throw escape, or no fetch after the throw",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "vite build of About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`",
            "assertion": ":161, :162",
            "excludes": "a template with no script, or a script that doesn't bundle the event route (the route isn't in `src/` now, so nothing else supplies it)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "untracked link, Text-like target and span-in-tracked-link send \"exactly two events\" to the event URL",
            "assertion": ":139",
            "excludes": "an event for the untracked or Text-like target, a URL built from `location.origin` (PAGE_ORIGIN is different), `//api` from joining the strings",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "body shapes, \"with nothing else in either body\"",
            "assertion": ":140",
            "excludes": "extra fields or wrong field values (whole-dict equality)",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "`page_path` is the stubbed `location.pathname` by mode",
            "assertion": ":140",
            "excludes": "`page_path` hardcoded to `/about` or to `/about.html` (the modes change it)",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "sendBeacon true \u2192 `application/json` Blob beacons, \"`fetch` is never called\"",
            "assertion": ":142, :139",
            "excludes": "an untyped or string beacon, any fetch call (it would be a third send)",
            "status": "CARRIED"
          },
          {
            "id": "D5a",
            "source": "docstring",
            "clause": "false/throws: \"each is first offered to the bound `navigator.sendBeacon`\"",
            "assertion": ":145",
            "excludes": "skipping the beacon, a detached `sendBeacon` (the stub throws Illegal invocation, which leaves beacons at 0)",
            "status": "CARRIED"
          },
          {
            "id": "D5b",
            "source": "docstring",
            "clause": "\"first ... and then posted by `fetch`\" \u2014 beacon before fetch",
            "assertion": "none",
            "excludes": "nothing: :144/:145 count beacon and fetch calls separately and never compare their order",
            "status": "UNCARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"as they are when `sendBeacon` is missing\"",
            "assertion": ":144, :145",
            "excludes": "beacon count at 0, fetch shape the same as the fallback modes",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"exactly one `click` listener is on `document`\"",
            "assertion": ":146",
            "excludes": "no listener, several listeners, or listeners of another type",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"no handler throws\"",
            "assertion": ":147",
            "excludes": "a throw on the Text-like target (no `closest`) or on the untracked link",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"no default is prevented\"",
            "assertion": ":149",
            "excludes": "`preventDefault` on any of the three clicks",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"no rejection goes unhandled\"",
            "assertion": ":148",
            "excludes": "a fetch with no `.catch` on the rejecting stub",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"import and tracked click send two events by beacon or keepalive fetch\"",
            "assertion": ":139, :140, :142, :144",
            "excludes": "wrong count, wrong order or wrong transport",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"built about page loads a bundled asset with the event route\"",
            "assertion": ":161, :162",
            "excludes": "no script asset, or an asset without the route",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:170\n   assert any(\"/api/analytics/event\" in (out / src.lstrip(\"/\")).read_text() for src in scripts), scripts\n   This is a rung-3 check on build output, then a substring check on a minified JS asset.\n   It is not prose and not a .md file, so no anti_pattern entry applies. Its weakness: it\n   passes for any script on the built page that carries the route string. The About module\n   does not have to be the one wired in. Today no file under client/frontend carries\n   `/api/analytics/event`, so the check can tell a wired build from an unwired one. If a\n   shared module later picks up the route, this assertion stays green whether or not the\n   About entry is wired. Behaviour (C1) is gated separately by the first test, so this is\n   recorded, not blocking.\n\nPREDICTED FAILURE\ntest_import_and_tracked_clicks_send_one_event_each_by_beacon_or_keepalive_fetch fails in\nall four modes at line 122 of the module-scoped `runner` fixture. The assertion\n`assert result.returncode == 0, result.stderr` fails on esbuild's resolve error, because\nclient/frontend/src/about-analytics.ts does not exist. test_built_about_page_loads_a_bundled_asset_with_the_event_route\nfails at line 169, `assert scripts, page`, because dev-pages/about.template.html has no\n<script src> tag, so the built page lists no /assets/*.js. If a local dev-pages/about.html\nexists, this test is skipped at line 163 instead.\n\nNOT ASSESSED\n1. `code_under_test` listed client/frontend/src/about-analytics.ts, which does not resolve.\n   The anti-pattern, ladder and stub passes were answered from the test's assertion form\n   and its runner alone. The stub check: the four transport modes, two page paths, two\n   distinct ids and hrefs, a page origin different from the API base, a bound-`this`\n   sendBeacon stub and an ordered call log. Together these separate a hard-coded payload,\n   a fetch-only or beacon-only stub, an unbound sendBeacon, and a once-per-page or\n   once-per-id send from a correct implementation.\n2. `code_under_test` listed tests/active/test_analytics_events.py (EDITED), which does not\n   resolve. Its edits were not read.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (20 clauses: 7 must_prove, 11 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"importing the module sends one `page_view`\" | :148 | no page_view on import, a page_view with extra or missing fields, or a page_view that is not sent first | CARRIED |\n| C1b | must_prove | \"one `outbound_click` per tracked click\" | :148 | a module-level \"already sent\" flag, a once-only listener, or a once-per-id send. Three tracked clicks (patreon, github, patreon again; runner :91) must give three outbound_clicks, in order, each with its own id and href | CARRIED |\n| C1c | must_prove | sends by beacon when `sendBeacon` accepts | :150, :153 | sending by fetch when beacon would do, a beacon body without the JSON type, or a fetch beside the beacon (`calls == [\"beacon\"]*4`) | CARRIED |\n| C1d | must_prove | falls back to keepalive `fetch` when `sendBeacon` is unavailable | :152, :153 (mode `missing`) | dropping the event when there is no beacon, or a fetch without keepalive, POST or JSON | CARRIED |\n| C1e | must_prove | falls back when `sendBeacon` refuses (returns false) | :152, :153 (mode `false`) | ignoring the false return and sending nothing, or never offering the beacon | CARRIED |\n| C1f | must_prove | falls back when `sendBeacon` throws | :152, :153, :155 (mode `throws`) | letting the throw escape, or no fetch after the throw | CARRIED |\n| C2 | must_prove | vite build of About template references a bundled `/assets/*.js` entry containing `/api/analytics/event` | :169, :170 | a template with no script, or a script that does not bundle the event route (nothing under `src/` holds the route today, Grep confirmed) | CARRIED |\n| D1 | docstring | send \"exactly four events\" to the event URL (widened from \"exactly two\"), none for the untracked or Text-like target | :147 | an event for the untracked or Text-like target, a URL built from `location.origin`, or `//api` from joining the strings | CARRIED |\n| D2 | docstring | body shapes, \"with nothing else in any body\" | :148 | extra fields or wrong field values (the whole dict is compared) | CARRIED |\n| D3 | docstring | `page_path` is the stubbed `location.pathname` by mode | :148 | `page_path` hardcoded to `/about` or to `/about.html` | CARRIED |\n| D4 | docstring | sendBeacon true \u2192 `application/json` Blob beacons, \"`fetch` is never called\" | :150, :153 | an untyped or string beacon, or any fetch call | CARRIED |\n| D5a | docstring | false/throws: \"first offered to the bound `navigator.sendBeacon`\" | :153 | skipping the beacon, or a detached `sendBeacon` (the stub throws before `calls.push`, so no \"beacon\" entry is recorded) | CARRIED |\n| D5b | docstring | \"and then posted by `fetch`, in that order per event\" | :153 | fetch before beacon, or all beacons batched before all fetches. `calls` is one ordered list compared to `[\"beacon\",\"fetch\"]*4` | CARRIED |\n| D6 | docstring | \"as they are when `sendBeacon` is missing\" | :152, :153 | the beacon tried when missing, or a fetch shape that differs from the other fallback modes | CARRIED |\n| D7 | docstring | \"exactly one `click` listener is on `document`\" | :154 | no listener, several listeners, or listeners of another type | CARRIED |\n| D8 | docstring | \"no handler throws\" | :155 | a throw on the Text-like target (it has no `closest`) or on the untracked link | CARRIED |\n| D9 | docstring | \"no default is prevented\" | :157 | `preventDefault` on any of the five clicks | CARRIED |\n| D10 | docstring | \"no rejection goes unhandled\" | :156 | a fetch with no `.catch` on the rejecting stub | CARRIED |\n| N1 | name | \"import and tracked clicks send one event each by beacon or keepalive fetch\" | :147, :148, :150, :152 | wrong count, wrong order, or wrong transport | CARRIED |\n| N2 | name | \"built about page loads a bundled asset with the event route\" | :169, :170 | no script asset, or an asset without the route | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:3, :91, :148\n   The prose was widened, not narrowed. The module docstring went from \"exactly two events\" to \"exactly four events\" over five targets, and the test function was renamed (`..._tracked_clicks_send_one_event_each_...`). A matching assertion now carries each widened sentence: :91 adds a second tracked link and a repeat click, and :148 / :153 compare the full ordered lists. For the record, rows C1b and D5b were fixed by adding assertions. No prose was withdrawn to clear them.\n2. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:141\n   The function docstring has clauses that no ledger row names: \"carrying the clicked link's own id and href\" and \"after the bound sendBeacon was tried\". Both are carried, at :148 and :153 in that order. Recorded for completeness. Neither is a finding.\n3. surfaces / checkpoint_definition (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:162-163\n   `pytest.skip` when `dev-pages/about.html` exists. On a machine with a local override, C2 is never exercised and the checkpoint still goes green. There is no override in this worktree (Glob shows only `about.template.html`), so the test runs here. No ledger row names this, so it does not block.\n4. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:157\n   The inline comment calls this line a \"regression line, not a clause\". The docstring still claims \"no default is prevented\" (D9), and :157 carries it. The comment and the docstring disagree about whether this is a clause.\n\nNOT ASSESSED\n1. `code_under_test` client/frontend/src/about-analytics.ts (NEW) does not resolve. The module is not written yet. Bounds and the abnormal path were judged from the test's runner stubs and `must_prove` alone.\n2. `code_under_test` tests/active/test_analytics_events.py (EDITED) does not resolve. Its contents were not checked.\n3. client/frontend/dev-pages/about.template.html has no `<script>` yet. C2's exclusion argument rests on the Grep showing `/api/analytics/event` absent from `client/frontend` outside `node_modules`. Which entry the edited template will reference could not be checked.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule covers this (rules/shape.md) \u2014 tests/tmp/test_18_about_outbound_click_tracking_phase4.py:170\n   assert any(\"/api/analytics/event\" in (out / src.lstrip(\"/\")).read_text() for src in scripts), scripts\n   This is a rung-3 check on build output, then a substring check on a minified JS asset.\n   It is not prose and not a .md file, so no anti_pattern entry applies. Its weakness: it\n   passes for any script on the built page that carries the route string. The About module\n   does not have to be the one wired in. Today no file under client/frontend carries\n   `/api/analytics/event`, so the check can tell a wired build from an unwired one. If a\n   shared module later picks up the route, this assertion stays green whether or not the\n   About entry is wired. Behaviour (C1) is gated separately by the first test, so this is\n   recorded, not blocking.\n\nPREDICTED FAILURE\ntest_import_and_tracked_clicks_send_one_event_each_by_beacon_or_keepalive_fetch fails in\nall four modes at line 122 of the module-scoped `runner` fixture. The assertion\n`assert result.returncode == 0, result.stderr` fails on esbuild's resolve error, because\nclient/frontend/src/about-analytics.ts does not exist. test_built_about_page_loads_a_bundled_asset_with_the_event_route\nfails at line 169, `assert scripts, page`, because dev-pages/about.template.html has no\n<script src> tag, so the built page lists no /assets/*.js. If a local dev-pages/about.html\nexists, this test is skipped at line 163 instead.\n\nNOT ASSESSED\n1. `code_under_test` listed client/frontend/src/about-analytics.ts, which does not resolve.\n   The anti-pattern, ladder and stub passes were answered from the test's assertion form\n   and its runner alone. The stub check: the four transport modes, two page paths, two\n   distinct ids and hrefs, a page origin different from the API base, a bound-`this`\n   sendBeacon stub and an ordered call log. Together these separate a hard-coded payload,\n   a fetch-only or beacon-only stub, an unbound sendBeacon, and a once-per-page or\n   once-per-id send from a correct implementation.\n2. `code_under_test` listed tests/active/test_analytics_events.py (EDITED), which does not\n   resolve. Its edits were not read.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (20 clauses: 7 must_prove, 11 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"importing the module sends one `page_view`\" | :148 | no page_view on import, a page_view with extra or missing fields, or a page_view that is not sent first | CARRIED |\n| C1b | must_prove | \"one `outbound_click` per tracked click\" | :148 | a module-level \"already sent\" flag, a once-only listener, or a once-per-id send. Three tracked clicks (patreon, github, patreon again; runner :91) must give three outbound_clicks, in order, each with its own id and href | CARRIED |\n| C1c | must_prove | sends by beacon when `sendBeacon` accepts | :150, :153 | sending by fetch when beacon would do, a beacon body without the JSON type, or a fetch beside the beacon (`calls == [\"beacon\"]*4`) | CARRIED |\n| C1d | must_prove | falls back to keepalive `fetch` when `sendBeacon` is unavailable | :152, :153 (mode `missing`) | dropping the event when there is no beacon, or a fetch without keepalive, POST or JSON | CARRIED |\n| C1e | must_prove | falls back when `sendBeacon` refuses (returns false) | :152, :153 (mode `false`) | ignoring the false return and sending nothing, or never offering the beacon | CARRIED |\n| C1f | must_prove | falls back when `sendBeacon` throws | :152, :153, :155 (mode `throws`) | letting the throw escape, or no fetch after the throw | CARRIED |\n| C2 | must_prove | vite build of About template references a bundled `/assets/*.js` entry containing `/api/analytics/event` | :169, :170 | a template with no script, or a script that does not bundle the event route (nothing under `src/` holds the route today, Grep confirmed) | CARRIED |\n| D1 | docstring | send \"exactly four events\" to the event URL (widened from \"exactly two\"), none for the untracked or Text-like target | :147 | an event for the untracked or Text-like target, a URL built from `location.origin`, or `//api` from joining the strings | CARRIED |\n| D2 | docstring | body shapes, \"with nothing else in any body\" | :148 | extra fields or wrong field values (the whole dict is compared) | CARRIED |\n| D3 | docstring | `page_path` is the stubbed `location.pathname` by mode | :148 | `page_path` hardcoded to `/about` or to `/about.html` | CARRIED |\n| D4 | docstring | sendBeacon true \u2192 `application/json` Blob beacons, \"`fetch` is never called\" | :150, :153 | an untyped or string beacon, or any fetch call | CARRIED |\n| D5a | docstring | false/throws: \"first offered to the bound `navigator.sendBeacon`\" | :153 | skipping the beacon, or a detached `sendBeacon` (the stub throws before `calls.push`, so no \"beacon\" entry is recorded) | CARRIED |\n| D5b | docstring | \"and then posted by `fetch`, in that order per event\" | :153 | fetch before beacon, or all beacons batched before all fetches. `calls` is one ordered list compared to `[\"beacon\",\"fetch\"]*4` | CARRIED |\n| D6 | docstring | \"as they are when `sendBeacon` is missing\" | :152, :153 | the beacon tried when missing, or a fetch shape that differs from the other fallback modes | CARRIED |\n| D7 | docstring | \"exactly one `click` listener is on `document`\" | :154 | no listener, several listeners, or listeners of another type | CARRIED |\n| D8 | docstring | \"no handler throws\" | :155 | a throw on the Text-like target (it has no `closest`) or on the untracked link | CARRIED |\n| D9 | docstring | \"no default is prevented\" | :157 | `preventDefault` on any of the five clicks | CARRIED |\n| D10 | docstring | \"no rejection goes unhandled\" | :156 | a fetch with no `.catch` on the rejecting stub | CARRIED |\n| N1 | name | \"import and tracked clicks send one event each by beacon or keepalive fetch\" | :147, :148, :150, :152 | wrong count, wrong order, or wrong transport | CARRIED |\n| N2 | name | \"built about page loads a bundled asset with the event route\" | :169, :170 | no script asset, or an asset without the route | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:3, :91, :148\n   The prose was widened, not narrowed. The module docstring went from \"exactly two events\" to \"exactly four events\" over five targets, and the test function was renamed (`..._tracked_clicks_send_one_event_each_...`). A matching assertion now carries each widened sentence: :91 adds a second tracked link and a repeat click, and :148 / :153 compare the full ordered lists. For the record, rows C1b and D5b were fixed by adding assertions. No prose was withdrawn to clear them.\n2. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:141\n   The function docstring has clauses that no ledger row names: \"carrying the clicked link's own id and href\" and \"after the bound sendBeacon was tried\". Both are carried, at :148 and :153 in that order. Recorded for completeness. Neither is a finding.\n3. surfaces / checkpoint_definition (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:162-163\n   `pytest.skip` when `dev-pages/about.html` exists. On a machine with a local override, C2 is never exercised and the checkpoint still goes green. There is no override in this worktree (Glob shows only `about.template.html`), so the test runs here. No ledger row names this, so it does not block.\n4. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:157\n   The inline comment calls this line a \"regression line, not a clause\". The docstring still claims \"no default is prevented\" (D9), and :157 carries it. The comment and the docstring disagree about whether this is a clause.\n\nNOT ASSESSED\n1. `code_under_test` client/frontend/src/about-analytics.ts (NEW) does not resolve. The module is not written yet. Bounds and the abnormal path were judged from the test's runner stubs and `must_prove` alone.\n2. `code_under_test` tests/active/test_analytics_events.py (EDITED) does not resolve. Its contents were not checked.\n3. client/frontend/dev-pages/about.template.html has no `<script>` yet. C2's exclusion argument rests on the Grep showing `/api/analytics/event` absent from `client/frontend` outside `node_modules`. Which entry the edited template will reference could not be checked.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"importing the module sends one `page_view`\"",
            "assertion": ":148",
            "excludes": "no page_view on import, a page_view with extra or missing fields, or a page_view that is not sent first",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"one `outbound_click` per tracked click\"",
            "assertion": ":148",
            "excludes": "a module-level \"already sent\" flag, a once-only listener, or a once-per-id send. Three tracked clicks (patreon, github, patreon again; runner :91) must give three outbound_clicks, in order, each with its own id and href",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "sends by beacon when `sendBeacon` accepts",
            "assertion": ":150, :153",
            "excludes": "sending by fetch when beacon would do, a beacon body without the JSON type, or a fetch beside the beacon (`calls == [\"beacon\"]*4`)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "falls back to keepalive `fetch` when `sendBeacon` is unavailable",
            "assertion": ":152, :153 (mode `missing`)",
            "excludes": "dropping the event when there is no beacon, or a fetch without keepalive, POST or JSON",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "falls back when `sendBeacon` refuses (returns false)",
            "assertion": ":152, :153 (mode `false`)",
            "excludes": "ignoring the false return and sending nothing, or never offering the beacon",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "falls back when `sendBeacon` throws",
            "assertion": ":152, :153, :155 (mode `throws`)",
            "excludes": "letting the throw escape, or no fetch after the throw",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "vite build of About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`",
            "assertion": ":169, :170",
            "excludes": "a template with no script, or a script that does not bundle the event route (nothing under `src/` holds the route today, Grep confirmed)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "send \"exactly four events\" to the event URL (widened from \"exactly two\"), none for the untracked or Text-like target",
            "assertion": ":147",
            "excludes": "an event for the untracked or Text-like target, a URL built from `location.origin`, or `//api` from joining the strings",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "body shapes, \"with nothing else in any body\"",
            "assertion": ":148",
            "excludes": "extra fields or wrong field values (the whole dict is compared)",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "`page_path` is the stubbed `location.pathname` by mode",
            "assertion": ":148",
            "excludes": "`page_path` hardcoded to `/about` or to `/about.html`",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "sendBeacon true \u2192 `application/json` Blob beacons, \"`fetch` is never called\"",
            "assertion": ":150, :153",
            "excludes": "an untyped or string beacon, or any fetch call",
            "status": "CARRIED"
          },
          {
            "id": "D5a",
            "source": "docstring",
            "clause": "false/throws: \"first offered to the bound `navigator.sendBeacon`\"",
            "assertion": ":153",
            "excludes": "skipping the beacon, or a detached `sendBeacon` (the stub throws before `calls.push`, so no \"beacon\" entry is recorded)",
            "status": "CARRIED"
          },
          {
            "id": "D5b",
            "source": "docstring",
            "clause": "\"and then posted by `fetch`, in that order per event\"",
            "assertion": ":153",
            "excludes": "fetch before beacon, or all beacons batched before all fetches. `calls` is one ordered list compared to `[\"beacon\",\"fetch\"]*4`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"as they are when `sendBeacon` is missing\"",
            "assertion": ":152, :153",
            "excludes": "the beacon tried when missing, or a fetch shape that differs from the other fallback modes",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"exactly one `click` listener is on `document`\"",
            "assertion": ":154",
            "excludes": "no listener, several listeners, or listeners of another type",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"no handler throws\"",
            "assertion": ":155",
            "excludes": "a throw on the Text-like target (it has no `closest`) or on the untracked link",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"no default is prevented\"",
            "assertion": ":157",
            "excludes": "`preventDefault` on any of the five clicks",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"no rejection goes unhandled\"",
            "assertion": ":156",
            "excludes": "a fetch with no `.catch` on the rejecting stub",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"import and tracked clicks send one event each by beacon or keepalive fetch\"",
            "assertion": ":147, :148, :150, :152",
            "excludes": "wrong count, wrong order, or wrong transport",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"built about page loads a bundled asset with the event route\"",
            "assertion": ":169, :170",
            "excludes": "no script asset, or an asset without the route",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nclient/backend/server.py: `_handle_analytics_event` now binds `conn = self.server.user_db` once and uses it for both the transaction and the `insert_analytics_event` call, the same way `_handle_likes_import` and `_store_reaction` do. Behaviour is unchanged.\nclient/backend/server.py: replaced the placeholder docstring summary of `_validate_analytics_event` (\"Handle validate analytics event.\") with one saying what it does: it checks a decoded body against the settled rules, never raises, and ignores unknown keys. The `:returns:` line is unchanged.\n</refactors>\n\n<left_out>\nI left the per-route rate-limit block in `_serve_post` (check, then 429, then return) as it is. The analytics route copies the pattern every other route already uses, and pulling it into a helper would change code that existed before this build.\nI left users_store.py, about-analytics.ts and about.template.html alone. They already match the plan's settled code and the style of the files they sit in, and I found nothing that could be refactored without changing behaviour.\nI did not write the durable test `tests/active/test_analytics_events.py` or add its `test_groups` entry to `.un/skills/devsecops/config.json`. That is not a refactor. All four phases list the file (NEW, then EDITED), and Phase 3 lists config.json, but it still does not exist: each phase gated only on its checkpoint in `tests/tmp/test_18_about_outbound_click_tracking_phase{1..4}.py`. The checkpoints still need promoting, or the analytics code is left with no durable test or test group.\nI deleted none of the probe files in `tests/tmp/` (`probe_18_*`, `test_probe_18_*`). They are outside the files this step names; they should go when the checkpoints are promoted.\nI did not run anything. The two edits only touch a local variable and a docstring, so this step's run of the Phase 2/3 checkpoints is what confirms them.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nAll four phases' code already matched the plan and the style of the surrounding files, so the pass made just two behaviour-neutral tidy-ups in server.py. The real gap is the durable test `tests/active/test_analytics_events.py` and its `test_groups` entry: neither exists yet, and promoting the checkpoints into them is still to do.\n</observation>"
}
```
dev-flow:state -->

## 2026-10-02 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/18",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 46 test groups (45 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.2s
  ---------------------
  total                  10 passed                              2.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Purpose

Count real human interest on the About page as explicit browser events, not by reading nginx logs. The events are outbound link clicks and page views. The nginx pages log added by issue 21 (`docs/project/issues/archive/21-static-page-visit-logs.md`) mixes in bots, crawlers, HEAD requests and malformed requests. An event sent by the page's own JavaScript is a much cleaner signal of a person who loaded the page or clicked a link. This build delivers issue `docs/project/issues/18-about-outbound-click-tracking.md`. It also delivers the client-side pageview beacon that issue 21 and `DEPLOYMENT.md` ("Follow an About visit") name as their upgrade path. This is event analytics. Issue 21's nginx pages log is request-log visibility, stays as it is, and is not duplicated or changed.

### Ownership and routing (decided)

- The Client backend (`client/backend/server.py`, port 7072 in prod) owns the endpoint. The Engine is not touched.
- Reasons from the tree: prod nginx (`DEPLOYMENT.md` §6) already proxies every `/api/` path to the Client backend. The boundary contract (`DEPLOYMENT.md` §5) requires frontend reads and writes to use the Client API base, never the Engine. The Client backend already owns its own SQLite (`client/backend/db/users.db`), an in-memory per-key `RateLimiter` (`client/backend/lib/http_utils.py`), and client-address resolution (ADR-0002, `TRUSTED_PROXIES`).
- No nginx or gateway change is needed: `location /api/` already covers the route. The vite dev server already proxies `/api`.
- The CSP header `connect-src 'self'` already allows a same-origin beacon. No CSP change.

### Endpoint

- One route, `POST /api/analytics/event`, for both event types. There is no separate `/api/analytics/outbound-click`.
- The body is JSON, read with the existing `read_json_body`. `navigator.sendBeacon` with a JSON `Blob` sends `Content-Type: application/json`. The route must not reject a request because of its Content-Type: it parses the body as JSON whatever the header says, so a `text/plain` beacon is also accepted.
- `outbound_click` body: `{"type": "outbound_click", "track_id": <str>, "href": <str>, "page_path": <str>, "timestamp": <int ms>}`.
- `page_view` body: `{"type": "page_view", "page_path": <str>, "timestamp": <int ms>}`.
- Success answers `204` with an empty body (`respond_bytes(self, 204, b"")`, as `/api/profile/delete` does).
- A body that fails validation answers `400` with a JSON `{"error": ...}`, and nothing is stored. Invalid JSON, a non-object body and a missing or wrong-typed field all count as failures.
- Rate limit: the route goes through the existing `_rate_limit_check(url.path)` before any parsing. That is the shared `RateLimiter` at `RATE_LIMIT_MAX_REQUESTS` = 90 per `RATE_LIMIT_WINDOW_SECONDS` = 60, keyed `<client address>:<path>`. Over the limit it answers `429 {"error": "Rate limit exceeded"}`, as the other routes do. No new limiter is added.
- The request is wrapped in the existing `_run_request`, so it gets `request.start`/`request.end` log records like every other route.
- Unknown paths keep answering 404. `GET /api/analytics/event` is not a route.

### Validation rules (no track_id allowlist)

The operator chose shape validation instead of an id/host allowlist, because the real About page is an untracked local override whose links the repository cannot know.
- `type`: exactly `"outbound_click"` or `"page_view"`. Anything else is rejected.
- `track_id`: required for `outbound_click` and must fully match `[a-z0-9_]{1,64}`. Examples: `about_patreon`, `about_github`, `about_youtube`. For `page_view` it must be absent or null; it is stored as NULL.
- `href`: required for `outbound_click`. It must be a string of at most 2048 characters that parses (`urllib.parse`) as an absolute URL with scheme `http` or `https` and a non-empty host. For `page_view` it must be absent or null; it is stored as NULL.
- `page_path`: required for both types. It must be a string of 1 to 256 characters that starts with `/`. It is stored as sent, so `/about`, `/about/` and `/about.html` stay distinguishable.
- `timestamp`: the client's `Date.now()`. It is required and must be a JSON integer (not a bool) that is at least 0. It is shape-checked only and not stored, because a client clock is not trusted. The stored time is the server's receive time.
- Extra unknown keys in the body are ignored.

### Storage

- A new table in the Client backend's existing SQLite database `users.db` (`DEFAULT_USERS_DB_PATH`). It is created idempotently with `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` alongside the existing tables in `ensure_user_schema` (`client/backend/lib/users_store.py`), or in an equivalent schema function that runs at the same startup point.
- Schema: `analytics_events(id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK (type IN ('outbound_click', 'page_view')), track_id TEXT, href TEXT, page_path TEXT NOT NULL, created_at INTEGER NOT NULL, user_agent TEXT, referer TEXT)`.
- `created_at` is server time in epoch milliseconds (`now_ms()` from `lib/time_utils.py`, the convention of the other tables).
- `user_agent` is the request's `User-Agent` header and `referer` is its `Referer` header. Each is stored as NULL when absent or empty, so bots can be filtered in queries.
- Index: `(type, track_id, created_at)`, which serves the per-track_id daily and total queries and the page_view counts.
- Privacy: no raw IP, no `ip_hash` and no value derived from the client address is stored. The rate limit uses the client address in memory only.
- Retention: every raw row is kept. Nothing prunes the table.
- One accepted request inserts exactly one row.

### Frontend

- A bundled module, e.g. `client/frontend/src/about-analytics.ts` (exact name and location are for the design step). Inline script is not an option: the server CSP `script-src 'self'` blocks inline JS, and it is the About page's only CSP.
- On page load it sends one `page_view` event with `page_path = location.pathname`.
- It installs one delegated `click` listener on `document` for `a[data-track-id]`. When a click resolves (via `closest`) to such a link, it sends one `outbound_click` event: `track_id` from the attribute, `href` from the link's resolved `href`, `page_path = location.pathname`, `timestamp = Date.now()`. It never calls `preventDefault`, so navigation is unaffected. A click on a link without `data-track-id` sends nothing.
- Transport: `navigator.sendBeacon(url, new Blob([JSON.stringify(payload)], {type: "application/json"}))`. If `sendBeacon` is missing or returns false, it falls back to `fetch(url, {method: "POST", body, headers: {"Content-Type": "application/json"}, keepalive: true})`. Failures are swallowed and never surface to the visitor.
- The URL is built from the existing Client API base (`client/frontend/src/data/api-base.ts`), never an Engine base.
- `client/frontend/dev-pages/about.template.html` gets the module's `<script type="module" src="/src/...">` tag with a root-absolute URL, so the default About page sends page views. The template has no outbound links, so it sends no clicks.
- The local override `client/frontend/dev-pages/about.html` is untracked and is not edited. `client/frontend/README.md` ("Local About Overrides") documents what an override adds: the same root-absolute `<script type="module">` tag, and a `data-track-id="<id matching [a-z0-9_]{1,64}>"` attribute on each outbound link to count. Vite bundles the tag because the override is the `about` build input in `vite.config.ts`.

### Reporting

- No new code, HTTP endpoint or CLI. `DEPLOYMENT.md` gets a Triage runbook section with ready-to-run `sqlite3` queries against the Client backend's `users.db` for:
  - total `outbound_click` count per `track_id`;
  - daily `outbound_click` count per `track_id`, with the day in UTC from `created_at` ms;
  - total and daily `page_view` count, optionally per `page_path`;
  - the same queries with a `user_agent` filter shown as the way to exclude obvious bots.
- The existing "Follow an About visit" caveat in `DEPLOYMENT.md` points at issue 18 as the pageview upgrade path. Update it to say the pageview beacon now exists and where its counts are queried. Fix the issue path there and in related docs if issue 18 moves to `docs/project/issues/archive/`.
- The `/api/analytics/event` route is added wherever `DEPLOYMENT.md` or `client/README.md` lists the Client backend's public routes.

### Tracker housekeeping

- When delivered, issue 18's `Status:` becomes `enhancement, complete`, a delivery comment is added in the style of issue 21's, and the file moves to `docs/project/issues/archive/` (see `docs/project/triage-labels.md`, `docs/project/issue-tracker.md`).
- `CONTEXT.md` gets one glossary entry for **Analytics event**: what it is and its two types, that it is the Client backend's and not the Engine's, and that it is distinct from an Interaction event, which feeds the Engine.

### Validation (acceptance)

- Click dispatch: clicking an `a[data-track-id]` sends exactly one beacon to `/api/analytics/event` with `type`, `track_id`, `href`, `page_path` and `timestamp` correct. Clicking a link without the attribute sends none. Page load sends exactly one `page_view` with `page_path` and `timestamp`. When `sendBeacon` is unavailable or returns false, the `fetch` keepalive fallback is used.
- A valid `outbound_click` and a valid `page_view` each answer 204 and add exactly one row with the expected columns. `created_at` is server time, `user_agent` and `referer` come from the headers, and nothing IP-derived is stored.
- Each invalid case answers 400 and stores nothing: unknown `type`, bad `track_id` shape, non-http(s) or hostless or over-long `href`, bad `page_path`, missing or non-integer `timestamp`, invalid JSON, and a `track_id` or `href` on a `page_view`.
- Exceeding the rate limit for one client address answers 429 and stores nothing for the rejected requests.
- Counter: repeated valid clicks for one `track_id` raise its count in the DB, measured by the documented total and daily queries. The tracked template has no outbound links, so this is exercised through the endpoint or a test fixture page, not the template.
- The built About page, from the template, includes the bundled analytics script, so a page load beacons a `page_view`.

### Test locations and baseline suite state

- New gating tests go in `tests/active`, with working files in `tests/tmp`. Archived tests are in `tests/archive`. Plans go in `docs/project/plans`. The run record is `tests/last_test_validation.json` and the output is `tests/last_test_output.txt`. The project dir is `/home/enduser/code/PeerTube-browser/.worktrees/18`.
- Baseline before the build: the suite passes (exit code 0, not a variant run). Any red test after the build is caused by the build.
- `tests/active/test_static_page_visit_logs.py` compares the nginx About locations with `vite.config.ts`. The build must keep it green: no About URL or dev-pages name changes.

### conflicts

Issue 18 places `data-track-id` on links in `client/frontend/about.html`, but that file does not exist in the tree: About is built from the tracked placeholder `client/frontend/dev-pages/about.template.html`, which has no outbound links, or from the operator's untracked `dev-pages/about.html`. The tracked change is therefore the script tag in the template plus documentation for overrides.
Issue 18 says to validate against an allowlist of known ids/hosts and reject unknown `track_id`, but the operator decided on no allowlist, only shape validation of `track_id` (`[a-z0-9_]{1,64}`) and of `href` (absolute http(s) URL with a host).
Issue 18 specifies `POST /api/analytics/outbound-click` and table `outbound_click_events`, but the issue's own comment from issue 21, and the operator, want page views on the same endpoint now. The route is `POST /api/analytics/event` with a `type` field, and the table is `analytics_events` with nullable `track_id`/`href`.
Issue 18 lists an optional `ip_hash` column, but the operator chose to store no IP-derived value. A plain SHA-256 of an IPv4 address is reversible.
Issue 18 lists the `timestamp` payload field and `created_at` without saying whose clock is used. The requirements store the server's receive time and only shape-check the client timestamp.
Issue 18's validation "Clicking About links increases the counter in the DB" cannot run against the tracked template, which has no links. It is exercised through the endpoint or a fixture page.
Issue 18 leaves the endpoint's owner undecided, but the tree decides it: nginx proxies `/api/` to the Client backend, and the boundary contract in `DEPLOYMENT.md` §5 forbids UI calls to the Engine. So the Client backend owns it and no gateway route is added.

## 2026-10-02 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

I read `client/backend/server.py` (the `_serve_post` router, `_run_request`, `_rate_limit_check`, startup at line 1308), `lib/http_utils.py` (`read_json_body`, `respond_bytes`), `vite.config.ts`, `dev-pages/about.template.html`, `src/data/api-base.ts` and the existing esbuild-in-node frontend tests (`tests/active/test_frontend_profile.py`). The settled design fits the tree as it stands. Nothing needs new infrastructure: no dependency, no new limiter, no nginx, CSP or Engine change.

**Backend route.** `_serve_post` gets one new branch for `/api/analytics/event`, placed before the final 404 and shaped like its neighbours:
- `_rate_limit_check(url.path)` runs first, and a refusal answers `429 {"error": "Rate limit exceeded"}`.
- The body is read with `read_json_body`. That function never looks at Content-Type, so the `text/plain` acceptance requirement is met without any extra code. It already raises `ValueError` for invalid JSON, a non-object body, invalid UTF-8 (`UnicodeDecodeError` is a `ValueError`), a non-numeric Content-Length and a body over 1 MB. All of these map to `400 {"error": ...}`. An empty or missing body comes back as `{}` and then fails validation on the missing `type`, so it is also a 400.
- A valid event gets one row inserted and the answer `respond_bytes(self, 204, b"")`.

The route already sits inside `do_POST` → `_run_request`, so it gets `request.start`/`request.end` for free. `GET /api/analytics/event` matches no GET branch and keeps answering 404, as does every other unknown path.

**Validation.** One pure module-level function in `server.py`. It takes the parsed dict and returns either the row values or an error string, so the route stays a thin branch and the rules can be tested directly. It applies the rules exactly as settled:
- `type` must be in the two-value set.
- `track_id` must pass `re.fullmatch` against `[a-z0-9_]{1,64}`. That is `fullmatch`, not `match` with `$`, because `$` accepts a trailing newline. It is required for `outbound_click` and must be absent or `None` for `page_view`.
- `href` must be a `str` of at most 2048 characters. `urllib.parse.urlsplit` must give a scheme of `http` or `https` and a non-empty `hostname`. The `ValueError` that `urlsplit` raises on a malformed bracketed host is caught and becomes a 400. The same absent-or-null rule as `track_id` applies on `page_view`.
- `page_path` must be a `str` of 1 to 256 characters starting with `/`, and is stored verbatim.
- `timestamp` must be an `int` that is not a `bool` and is `>= 0`. It is checked and then discarded.
- Unknown keys are ignored.

The handler adds the server-side values: `now_ms()`, plus the `User-Agent` and `Referer` headers, each turned into `None` when absent or empty after stripping. Nothing derived from `_get_client_ip()` reaches the row.

**Storage.** `ensure_user_schema` in `lib/users_store.py` gains the `analytics_events` `CREATE TABLE IF NOT EXISTS` with the settled columns and CHECK, and the `(type, track_id, created_at)` `CREATE INDEX IF NOT EXISTS`. It already runs at startup (`server.py:1311`), and it is the literal option the requirements name, so existing databases pick up the table on the next restart. The same module gets a small `insert_analytics_event(conn, ...)` that does one `INSERT`, called inside `with self.server.user_db:` the way the other writes are, so one accepted request is one committed row.

**Frontend.** A new module, `client/frontend/src/about-analytics.ts`. When it runs it:
- builds the URL once as `resolveClientApiBase()` plus `/api/analytics/event`. It is called without an argument, so `?api=` is never read; in a prod build it is the page origin;
- sends one `page_view` (`page_path = location.pathname`, `timestamp = Date.now()`);
- adds one delegated `click` listener on `document`. The listener resolves `event.target.closest("a[data-track-id]")`, guarding a target that has no `closest`, and for a match sends `outbound_click` with the attribute value, `link.href` (the browser-resolved absolute URL), the pathname and `Date.now()`. It never calls `preventDefault`.

One `send` helper does the transport: `sendBeacon` with a JSON `Blob`. If `sendBeacon` is missing, returns false or throws, the helper falls back to `fetch` with `keepalive: true`. It wraps everything in try/catch and attaches a no-op `.catch` to the fetch promise, so nothing reaches the console as an unhandled rejection. The template gets `<script type="module" src="/src/about-analytics.ts"></script>`, the same root-absolute style as its `/src/videos.css` link. No About URL, input name or dev-pages filename changes, so `test_static_page_visit_logs.py` stays green.

**Reporting and docs.** No new code.
- **`DEPLOYMENT.md`**:
  - A new Triage subsection, "Count About analytics events". It holds a `sqlite3 -readonly <root>/client/backend/db/users.db` invocation and fenced `sql` blocks: total clicks per `track_id`; daily clicks per `track_id` using `date(created_at / 1000, 'unixepoch')`, which is UTC; total and daily `page_view`, optionally grouped by `page_path`; and the same queries with a `user_agent IS NOT NULL AND user_agent NOT LIKE '%bot%' AND … '%crawl%' AND … '%spider%'` filter shown as the bot exclusion.
  - The "Follow an About visit" caveat at line 258 is rewritten to say the beacon exists and to point at the new subsection, with the issue path changed to `archive/`.
  - The public-route prose near line 405 gets the route.
- **`client/README.md`**: the route list at line 41 gets the route, and the API bullets get one line describing it.
- **`client/frontend/README.md`**: "Local About Overrides" gets the script tag and the `data-track-id` convention. It also notes that only http(s) links can be counted.
- **`CONTEXT.md`**: one **Analytics event** entry.
- **Tracker**: issue 18 gets its status, a delivery comment and the move to the archive. Lane 5c in `docs/project/issues/plan.md` gets a path and delivery fix.

**Tests (gating, `tests/active`).**
- **Backend.** The `client_backend` fixture over a socket covers: each valid type gives 204 and exactly one row with the expected columns, with `created_at` inside the request window rather than equal to the client timestamp, and UA/Referer taken from the headers. A `PRAGMA table_info` assertion checks there is no IP-like column. Each invalid case gives 400 and zero rows, as does a `text/plain` valid beacon, which must be accepted. The rate-limit test sends 91 posts from one address: the extras get 429 and add no rows. `GET` answers 404.
- **Counter.** The test posts N clicks for one `track_id` and runs the SQL blocks extracted from the new `DEPLOYMENT.md` subsection against the fixture's DB, using Python `sqlite3` so the test does not depend on the CLI binary.
- **Frontend.** The module is bundled with the project's esbuild, as `test_frontend_profile.py` does. It runs in node against stubbed `document`, `location`, `navigator.sendBeacon` and `fetch`, and the test asserts one `page_view` on load, one correct `outbound_click` per tracked click, none for an untracked link, and the fetch keepalive fallback when `sendBeacon` is undefined or returns false.
- **Built page.** `vite build --outDir tests/tmp/...` is run and the test asserts that the built `dev-pages/about.template.html` references a bundled `/assets/*.js` whose contents include `/api/analytics/event`.

### Alternatives considered

- **Validation in a new `lib/analytics_events.py` (schema, validate, insert).** Rejected. It adds a file and a second schema call site at startup for about 40 lines of code. `users_store.py` already owns `users.db`'s schema, and `server.py` already holds the route-level checks.
- **Validation inside `users_store.py`.** Rejected. The store module takes trusted values and HTTP-shaped validation does not belong there.
- **A separate SQLite file for analytics.** Rejected: the requirement says `users.db`, and a second file means a second connection, startup step and backup path.
- **Per-day aggregate counters instead of raw rows.** Rejected: the bot filter on `user_agent` would be impossible after aggregation, and the requirement keeps raw rows.
- **Transport:** `fetch` alone can be cancelled by the navigation an outbound click causes. A GET image pixel would need a GET route and puts the payload in URLs and logs. `sendBeacon` alone has no fallback for browsers or privacy settings that disable it. The settled `sendBeacon` plus `fetch keepalive` combination covers all three.
- **Per-link listeners instead of one delegated listener.** Rejected: they miss links inserted later and need a query at load time. The delegated listener is the settled choice as well.
- **Built-page check by reading the template source only.** Rejected as the sole check: it proves the tag is there, not that vite bundles it. The real build is the acceptance criterion.

### Risks, gotchas and limitations

- **Local override and the built-page test.** `vite.config.ts` builds `dev-pages/about.html` when it exists. On a checkout with an untracked override, the build produces the override, not the template. The test will skip with an explicit reason in that case rather than assert on the wrong file. The worktree normally has no override, so the gate runs. The ceiling is that an operator's override without the tag sends nothing, which the README documents.
- **Non-http(s) tracked links.** A `mailto:` or `tel:` link with `data-track-id` is beaconed and rejected with 400 by the shape rule, so it is never counted. The README says so. Widening the rule is the upgrade path if that is ever wanted.
- **Clicks the `click` event does not see.** Middle-click opens a tab through `auxclick`, not `click`, and the context-menu "Open in new tab" fires nothing, so neither is counted. Ctrl/Cmd-click and keyboard Enter do fire `click` and are counted. This is a deliberate simplification: listening for `auxclick` as well is a one-line upgrade, but it is outside the settled spec.
- **Cross-origin dev base.** If `VITE_CLIENT_API_BASE` points at a different origin, a `sendBeacon` with an `application/json` Blob is a non-CORS-safelisted request, and some browsers throw or refuse it. The try/catch then falls through to `fetch`, which preflights through the existing `respond_options` CORS handling. In prod the base is same-origin and none of this applies.
- **Forgeable counts.** The endpoint is anonymous and accepts any well-formed body. A script can inflate counts at up to 90 per minute per address, roughly 130k rows a day per address. Retention is unbounded by requirement, so a sustained abuser grows `users.db` without limit. The per-address limiter is the only control. Both are named in the DEPLOYMENT section, and a prune or a per-address daily cap is the upgrade path.
- **Header storage.** `User-Agent` and `Referer` are stored as sent. `http.server` caps a header line at 64 KiB, which bounds each row, but there is no tighter truncation because the spec does not ask for one.
- **Shared SQLite connection.** Analytics writes share the connection and transaction pattern of the profile writes, so a burst of beacons briefly serialises with like and dislike writes. At the 90/min/address rate this is negligible.
- **The bot filter is a heuristic.** The UA can be forged. The documented `NOT LIKE` filter removes honest crawlers only. That is said in the docs, consistent with the issue-21 caveat.
- **Referer is often reduced.** The default `strict-origin-when-cross-origin` policy usually leaves `Referer` as the About URL itself. It is mostly useful as a has-or-hasn't signal.

### Tradeoffs the operator is asked to accept

- The built-page gate skips rather than fails on a checkout that has a local `about.html` override.
- Middle-click and context-menu opens are not counted.
- Tracked non-http(s) links are silently not counted.
- Counts are best-effort human signals: anonymous, forgeable within the rate limit, and growing without pruning.

### conflicts

none

## 2026-10-02 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impact path="client/backend/server.py" element="module imports (lines 5-41) and module constants (lines 62-65)">
**What changes.** `re` is not imported today (lines 5-23), and `urllib.parse` gives only `parse_qs, urlencode, urlparse` (line 20). The plan's `re.fullmatch` and `urlsplit` need `import re` and `urlsplit` added to line 20. Using the `urlparse` already imported would also work, since `.hostname` raises the same `ValueError` on a bad bracketed host. `insert_analytics_event` joins the `from lib.users_store import (...)` block at lines 39-41. That block is wrapped and alphabetised, and the new name has to keep that order. The new constants should match `USER_ACTIONS = frozenset((...))` (line 62): something like `ANALYTICS_EVENT_TYPES = frozenset(("outbound_click", "page_view"))`, a compiled `[a-z0-9_]{1,64}` pattern, `ANALYTICS_HREF_MAX_LENGTH = 2048` and `ANALYTICS_PAGE_PATH_MAX_LENGTH = 256`. Each constant is one line, with a one-line comment where the value needs explaining.
**What depends on it.** `tests/active/conftest.py:43` imports `server` as `client_server`, and every test that uses the backend imports this module. An import error breaks the whole active suite.
**Regression risk.** Low. The only real risk is a misspelt import, which fails at collection time, not silently.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._serve_post (lines 437-501): new `/api/analytics/event` branch">
**What changes.** A new `if url.path == "/api/analytics/event":` branch, placed before the comment block at lines 497-500 and the final `respond_json(self, 404, ...)` at line 501. It has the same shape as `/api/user-action` (lines 464-469): `_rate_limit_check(url.path)`, then 429 `{"error": "Rate limit exceeded"}`, then a call to a `_handle_analytics_event()` method. That method sits next to `_handle_user_profile_reset` and the other handlers. It does `read_json_body` in `try/except ValueError` → 400 `{"error": str(exc)}`, the same as `_handle_likes_import` (lines 1014-1018). Then it validates, then runs `with self.server.user_db: insert_analytics_event(...)`, then `respond_bytes(self, 204, b"")` as `/api/profile/delete` does at line 462.
**What depends on it.** `do_POST` → `_run_request` (lines 339-379) wraps it. `request.start` already logs `user_agent` and `ip`, and that is log-only, so it is not storage. `_serve_get` (lines 381-435) is unchanged, so `GET /api/analytics/event` still falls to 404 at line 435. `OPTIONS` goes through `respond_options` for any path, so a preflight to the new path already answers 204.
**Regression risk.** Low for the existing routes: the new branch is checked only on an exact path match. Points to check:
- The rate limit runs before the body is read. A 429 leaves the body unread on the socket. That is harmless only because the handler never sets `protocol_version`, so it is HTTP/1.0 and closes every connection. Nothing in `client/backend` sets `protocol_version` or `close_connection`, which I checked.
- Placement must stay before line 501. A branch placed after it never runs.
- The limiter key is `<ip>:/api/analytics/event`, so analytics has its own 90/min bucket. It does not eat into `/api/user-action`'s bucket for the same visitor, and the reverse holds too.
</impact>
<impact path="client/backend/server.py" element="new module-level validation function (e.g. `_validate_analytics_event(body) -> tuple[...] | str`), placed near `_parse_client_likes` (lines 1236-1252)">
**What changes.** A new pure function. Its siblings `_parse_int` and `_parse_client_likes` have the same `"""Handle ...."""`/`:returns:` docstring style, and private helpers there use the `_` prefix.
**What depends on it.** The route handler and the new backend tests. The plan has the tests call it directly as `client_server._validate_...`.
**Regression risk.** Medium. The failures are crashes that skip the 400, not silent acceptance:
- **Type guards before use.** Every field has to be checked with `isinstance(..., str)` before `re.fullmatch`, `len`, `.startswith` or `urlsplit`. For example, `re.fullmatch(p, 123)` raises `TypeError`, and `urlsplit(None)` returns bytes-ish results. Any exception that escapes goes to `_run_request`'s `finally` and then to socketserver's `handle_error`. The client gets no response, and `request.end` logs status `-`. That is not a 400.
- **`bool` is a subclass of `int`.** `timestamp: true` must be rejected, which the plan states. A float such as `1.0` must also be rejected, because `json.loads` gives `float` for it.
- **`$` versus `fullmatch`.** The plan already handles this.
- **Lone surrogates.** `json.loads('"\\ud800"')` gives a `str` that Python's `sqlite3` cannot bind (`UnicodeEncodeError: surrogates not allowed`). It escapes at INSERT time, as an unhandled 500 or dropped connection rather than a 400. `href` and `page_path` both accept arbitrary strings, so validation should reject strings that fail `.encode("utf-8")`. `track_id` is safe because of its regex. The headers are safe because http.server decodes them as latin-1. NUL characters do store fine.
- **`urlsplit` details.** `urlsplit("https://")` gives `hostname=None`. `urlsplit("http://[::1")` raises `ValueError`, which the plan catches. The scheme comes back lowercased, so `HTTPS://x` passes. `hostname` is lowercased, but `href` is stored verbatim.
- **`page_path`.** `//evil.example` passes, because it starts with `/`. That is fine because it is stored verbatim and never followed.
- **Explicit nulls.** On an `outbound_click`, `track_id: null` or `href: null` must be rejected. On a `page_view` they must be accepted.
</impact>
<impact path="client/backend/server.py" element="header capture for the row (`self.headers.get('User-Agent')`, `self.headers.get('Referer')`) and `_get_client_ip` (lines 326-329)">
**What changes.** The handler reads `User-Agent` and `Referer`, strips each, and turns empty into `None`. That mirrors what `_run_request` does at lines 347-349 for the log. `_get_client_ip` is used only through `_rate_limit_check`.
**What depends on it.** The "nothing IP-derived stored" requirement and the `PRAGMA table_info` test.
**Regression risk.** Low. Two caveats:
- The UA and Referer are stored up to http.server's 64 KiB per-line limit. The plan accepts that.
- `X-Forwarded-For` and `X-Real-IP` must not be read into the row. nginx sets `X-Real-IP` on `/api/` (DEPLOYMENT.md:489), and a careless "store all headers" approach would leak it.
</impact>
<impact path="client/backend/server.py" element="connect_db (lines 230-234) and the single shared `user_db` connection on ClientBackendServer (line 311)">
**What changes.** Nothing in the code. The route adds writes on this connection.
**What depends on it.** Every profile write: `_store_reaction` (lines 961-1003), the likes import, blocks, reset, mint, rotate and delete.
**Regression risk.** Medium, and it is not stated in the plan's "shared SQLite connection" risk. There is one `sqlite3.Connection` with `check_same_thread=False`, shared by all `ThreadingHTTPServer` threads, and there is no lock anywhere in `client/backend` (the grep found only `RateLimiter.lock`). `with conn:` commits or rolls back the connection's transaction, not a per-thread one. A beacon's commit on thread A can therefore commit a half-done multi-statement transaction from thread B, for example `remove_like` + `close_like` + `write_dislike` at lines 991-994. A rollback on B can also undo A's insert.

This is a race that already exists, but today every write route is either profile-keyed or limited to 5/hour (mint). This route is the first anonymous, high-rate write route, at 90/min per address with unlimited addresses, so it makes the window far more likely to be hit. A server-level `threading.Lock` around analytics writes would not fix the others. This is worth stating as a known, inherited limitation, or fixing with a lock or a per-thread connection in a separate issue.
</impact>
<impact path="client/backend/server.py" element="main() startup: `ensure_user_schema(user_db)` (line 1311)">
**What changes.** No edit. The new table and index are created on the next restart through the existing call.
**What depends on it.** Prod and dev upgrades. There is no migration step, matching DEPLOYMENT.md:408 ("which it creates at startup, so there is no migration step").
**Regression risk.** Low. `executescript` issues a COMMIT before it runs. That is harmless at startup.
</impact>
<impact path="client/backend/lib/users_store.py" element="ensure_user_schema (lines 10-71): docstring and script">
**What changes.** The script gains `CREATE TABLE IF NOT EXISTS analytics_events (...)` with the settled columns and `CHECK (type IN ('outbound_click', 'page_view'))`, plus `CREATE INDEX IF NOT EXISTS <name> ON analytics_events (type, track_id, created_at)`. The index name should follow `likes_user_updated_idx` (line 27), e.g. `analytics_events_type_track_created_idx`. Both statements must go before the `local-user` DELETE lines (67-69), or at least inside the same script. The docstring on line 11 lists the tables it creates ("users, likes, like generation, profile, block and dislike tables"), so it must add "analytics event".
**What depends on it.** `server.py:1311`, `tests/active/conftest.py:45/77/169` (every `client_backend`, `engine_client` and `unpublished_client` fixture), `tests/active/test_server.py:398` (`_client_backend`), and any test that counts tables.
**Regression risk.** Low. I searched for `sqlite_master` and `table_info` in tests/active. None of the hits enumerate users.db's tables: test_moderation, test_similarity_cache, test_precompute_similar_ann, test_videos and test_whitelist_migrations all target other DBs. `test_profiles.py:103` scans users.db bytes for a plaintext key, and the new empty table does not affect that.
</impact>
<impact path="client/backend/lib/users_store.py" element="new insert_analytics_event(conn, event_type, track_id, href, page_path, created_at, user_agent, referer)">
**What changes.** A new function: one parameterised `INSERT INTO analytics_events (...) VALUES (?, ...)`. It must not call `conn.commit()` itself, so that `with self.server.user_db:` in the handler owns the transaction. The module is inconsistent here: `get_or_create_user`, `record_like` and `clear_likes` commit inside, while `remove_like` and `close_like` document "inside the caller's transaction". Following the latter matches the plan.
**What depends on it.** The route, and the counter test, which reads rows back.
**Regression risk.** Low. `created_at` should be passed in from the handler's `now_ms()` (or computed here with the module's `from .time_utils import now_ms`, line 7). Either way, there must be one source of truth so the test's request window holds.
</impact>
<impact path="client/backend/lib/http_utils.py" element="read_json_body (lines 78-95)">
**What changes.** Nothing. It is relied on as is.
**What depends on it.** Every JSON POST route.
**Regression risk.** None from an edit. Behaviour the plan relies on, confirmed by reading the code:
- It ignores Content-Type, so `text/plain` is accepted.
- `int("abc")` → `ValueError` → 400.
- A size over 1,000,000 → `ValueError`.
- `.decode("utf-8")` raises `UnicodeDecodeError`, a `ValueError` subclass.
- A non-dict → `ValueError`.
- A length of 0, a missing length, or a whitespace-only body → `{}`.

One case the plan does not mention: a `Content-Length` larger than the bytes actually sent makes `rfile.read(size)` block until the socket times out. That is inherited by every route and not new.
</impact>
<impact path="client/backend/lib/http_utils.py" element="_send_cors_headers / respond_options / ALLOWED_REQUEST_HEADERS (lines 12-44, 71-75)">
**What changes.** Nothing.
**What depends on it.** The cross-origin dev path of the beacon.
**Regression risk.** This affects the frontend design rather than causing a backend regression. The server never sends `Access-Control-Allow-Credentials`, and DEPLOYMENT.md:620 says "credentials are never sent". `navigator.sendBeacon` always uses credentials mode `include`. A beacon whose Blob type is `application/json` is not CORS-safelisted, so cross-origin it needs a preflight, and a credentialed preflight without `Allow-Credentials` fails. `sendBeacon` has already returned `true` (queued) by then, so the plan's fallback never runs and the event is lost silently. Some engines throw synchronously instead, and the plan's try/catch covers that case.

`npm run dev` is always cross-origin (scripts/dev.mjs:15/104, client/frontend/README.md:24), so in dev most `sendBeacon` events can vanish while the backend tests pass. Prod is same-origin and unaffected. The mitigation is a `text/plain` Blob, which is safelisted, needs no preflight, and is already accepted by the server, either always or when the API base origin differs from `location.origin`. That departs from the requirement's literal `application/json`, so it is for the design step to decide.
</impact>
<impact path="client/backend/lib/http_utils.py" element="RateLimiter (lines 98-124)">
**What changes.** Nothing.
**What depends on it.** The 429 behaviour of the new route.
**Regression risk.** Low. Notes:
- Buckets are never evicted. Each new `<ip>:/api/analytics/event` key adds a deque that lives for the whole process. This already happens on every route, but an anonymous beacon route seen by every About visitor adds one key per distinct visitor address, so memory grows slowly until restart.
- `max_requests <= 0` disables the limiter.
</impact>
<impact path="client/backend/lib/profiles.py" element="delete_profile (lines 69-81)">
**What changes.** Nothing. Analytics rows carry no profile id, so profile deletion does not and cannot remove them. That is consistent with "nothing IP- or identity-derived is stored".
**What depends on it.** client/README.md:13 says delete removes "everything keyed to it". That stays true.
**Regression risk.** None.
</impact>
<impact path="client/frontend/src/about-analytics.ts" element="new module (whole file)">
**What changes.** New file. It imports `resolveClientApiBase` from `./data/api-base`. On load it sends `page_view`, then installs one delegated `click` listener on `document`, and a `send()` helper does `sendBeacon` with a fallback to `fetch(..., {keepalive: true})`. Style should follow the other modules: a `/** Module \`client/frontend/src/...\`: ... */` header, as in api-base.ts:1-3, and a `/** Handle ... */` JSDoc on each function.

On placement: every other page entry lives at `src/pages/<page>/index.ts`, imported from the HTML. The plan's `src/about-analytics.ts` at the src root breaks that convention, and `src/pages/about/index.ts` (or `src/pages/about/analytics.ts`) would match it. The choice belongs to the design step, but the HTML tag and the README text must name the same path.

**What depends on it.** The template's script tag, the README override instructions, the frontend node test and the built-page test.

**Regression risk.** Medium, because these failures are silent by design:
- **Detached `sendBeacon`.** `const b = navigator.sendBeacon; b(url, blob)` throws "Illegal invocation". The catch then hides it and every event takes the fetch path. It must be called as `navigator.sendBeacon(...)`.
- **`closest` on non-elements.** `event.target` can be a Text node, which has no `closest`. The plan guards this.
- **`link.href` on an SVG `<a>`.** It is an `SVGAnimatedString`, not a string. It serialises to `"[object SVGAnimatedString]"`, which the server rejects.
- **Import-time `window` read.** api-base.ts:5 reads `window.location.origin` when it is imported.
- **Load-time side effects.** The module does its work at import, so the node test must install its stubs before `import()`.
- **`location.pathname` in a module script.** Module scripts are deferred, so `document` is parsed by then, and the listener on `document` needs no DOMContentLoaded wait.
- **Async fetch rejection.** `fetch` can reject asynchronously, which needs the `.catch`, and it can throw synchronously, for example on a keepalive body over 64 KiB, which needs the try. The plan covers both.
</impact>
<impact path="client/frontend/src/data/api-base.ts" element="resolveClientApiBase (lines 18-33), DEFAULT_CLIENT_API_BASE (line 5)">
**What changes.** Nothing. It is called with no argument, so `?api=` is never consulted.
**What depends on it.** The new module, and every data module.
**Regression risk.** Low. The base can carry a trailing slash if `VITE_CLIENT_API_BASE` has one, which would make `.../` + `/api/analytics/event` a double slash. The other modules concatenate the same way, so the behaviour is consistent, but `_serve_post` would 404 on a `//api/...` path. Prod uses `window.location.origin`, which has no trailing slash.
</impact>
<impact path="client/frontend/src/vite-env.d.ts" element="ImportMetaEnv">
**What changes.** Nothing, unless the module reads a new env var, which the plan does not.
**What depends on it.** TypeScript typing of `import.meta.env`.
**Regression risk.** None.
</impact>
<impact path="client/frontend/dev-pages/about.template.html" element="`<head>`/`<body>`: new `<script type="module" src="/src/...">`">
**What changes.** One line. The other pages put the module tag at the end of `<body>` (index.html:65, channels.html:106 and the rest). The template has its stylesheet in `<head>` at line 8. Either placement works for a deferred module, but end-of-body matches the sibling pages.
**What depends on it.** `vite.config.ts` uses this file as the `about` input when no override exists. nginx serves the built copy (DEPLOYMENT.md §6). `tests/tmp/test_21_static_page_visit_logs_phase3.py:27/237` reads the template bytes into a real nginx run, and an extra tag leaves its log assertions unchanged.
**Regression risk.** Low. The URL must be root-absolute (client/frontend/README.md:41), because `/about/` would resolve a relative URL under `/about/`. The page's only CSP is `script-src 'self'`, which allows the bundled `/assets/*.js`.
</impact>
<impact path="client/frontend/vite.config.ts" element="build.rollupOptions.input.about (lines 91-93), aboutSourcePath (lines 16-18)">
**What changes.** Nothing.
**What depends on it.** The built-page test.
**Regression risk.** Medium for the test design:
- **Override switch.** `existsSync(devAboutPath)` switches the input to an untracked override (`.gitignore:29-30` ignores `dev-pages/*` except the template). The plan's skip-on-override handles it.
- **`--outDir` resolution.** Vite resolves `--outDir` against the config root, `client/frontend`, so `tests/tmp/...` must be passed as an absolute path. Otherwise it lands in `client/frontend/tests/tmp/`.
- **`--emptyOutDir`.** An outDir outside the root is not emptied without `--emptyOutDir`.
- **Built-file location.** The built About page is `<outDir>/dev-pages/about.template.html`, as in the committed `dist/dev-pages/about.template.html`.
- **No `node_modules` in this worktree.** A Glob for `client/frontend/node_modules` found nothing (`.gitignore:1` says worktrees hold it as a symlink). `node_modules/.bin/vite` and `esbuild` must therefore be resolvable where the gate runs, or the test should skip or fail with a clear reason, as the other frontend tests implicitly assume.
- **Shared chunks.** Rollup may split `api-base` into a shared chunk. The literal `/api/analytics/event` stays in the about entry chunk, so asserting on "some referenced `/assets/*.js`" stays sound, but the hashes of other pages' chunks can change.
</impact>
<impact path="client/frontend/dist/dev-pages/about.template.html" element="committed build output (and dist/assets/*)">
**What changes.** Not in the plan. The committed `dist/` lags the source (DEPLOYMENT.md:444). Until someone runs `npm run build`/`scripts/sync.sh`, the served About page has no beacon.
**What depends on it.** Prod deploy via `scripts/sync.sh`.
**Regression risk.** Low. It should be named in the delivery comment, or as a checklist item like issue 40's "`dist/` is rebuilt". The built-page test must not write into `dist/`.
</impact>
<impact path="client/frontend/scripts/dev.mjs" element="VITE_CLIENT_API_BASE default (lines 15, 46-49, 104)">
**What changes.** Nothing.
**What depends on it.** It makes the dev About page cross-origin to `127.0.0.1:7172`, so the beacon depends on `CLIENT_CORS_ORIGINS` and is exposed to the `sendBeacon` preflight and credentials issue described under http_utils.
**Regression risk.** The plan's "cross-origin dev base" risk treats this as an edge case. It is the default dev setup.
</impact>
<impact path="tests/active/conftest.py" element="client_backend fixture (lines 73-93), ClientBackend.request (lines 55-70)">
**What changes.** Nothing, though new tests may add a helper.
**What depends on it.** The new backend tests.
**Regression risk.** Medium for the planned tests:
- The fixture builds `RateLimiter(1000, 60)` (line 84), not 90/60, so "91 posts → extras get 429" cannot be done on `client_backend`. Use `test_server.py`'s `_client_backend(tmp_path, CLOSED_ENGINE, RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS))` (test_server.py:394-403), or a dedicated limiter.
- `ClientBackend.request` always sets `content-type: application/json` and JSON-encodes `body`. The `text/plain`, invalid-JSON, empty-body and UA/Referer-header cases need raw `urllib.request` calls, like `_status` in test_server.py:406-414, or a small raw helper.
- The fixture's DB is `db_path`. Reading it with a second `sqlite3.connect` while the server holds a connection is fine for reads after a 204.
</impact>
<impact path="tests/active/test_server.py" element="`_client_backend`/`_serving`/`_status` helpers (lines 383-414) and route-level tests">
**What changes.** Nothing, unless the new tests are added here.
**What depends on it.** The rate-limit test can import these helpers.
**Regression risk.** Low. Existing 404 tests use other paths (line 1349 and others), and none enumerate POST routes.
</impact>
<impact path="tests/active/test_frontend_profile.py" element="esbuild-in-node pattern (_bundle, RUNNER, lines 21-62)">
**What changes.** Nothing. It is the template for the new frontend test.
**What depends on it.** The new test copies its `--define:import.meta.env.VITE_CLIENT_API_BASE=...` and `--define:import.meta.env.DEV=false` flags, and the `globalThis.window = {location: {origin}}` stub.
**Regression risk.** For the new test:
- Since Node 21, `navigator` is a read-only getter on `globalThis`. In an ESM runner, `globalThis.navigator = {...}` throws a TypeError, so the stub needs `Object.defineProperty(globalThis, "navigator", {value: ..., configurable: true})`. No existing active test stubs `navigator`, which I checked by grep.
- `Blob` and `fetch` are globals in Node ≥18. The stub must replace `fetch`, and the test must read the Blob body back (`await blob.text()`) to assert the payload.
- `location` must be stubbed both as `window.location` and as bare `location`, if the module uses the bare global.
</impact>
<impact path="tests/active/test_analytics_events.py" element="new gating test file(s) (name for the design step)">
**What changes.** New test files: backend endpoint tests, the counter test that runs SQL from the DEPLOYMENT.md subsection, the node frontend test, and the vite built-page test. They could be one file or several.
**What depends on it.** The suite gate, and `tests/last_test_validation.json` groups.
**Regression risk.** Medium:
- The counter test parses fenced `sql` blocks out of DEPLOYMENT.md, which ties the test to that section's heading and fence layout. The heading text must be pinned and the block count asserted, so an empty extraction cannot pass vacuously.
- The `created_at` window check must take `now_ms()` before and after the request.
- `PRAGMA table_info(analytics_events)` should assert the exact column list, not just that no IP column exists.
- The built-page vite build is slow, so give it a generous timeout.
</impact>
<impact path="tests/active/test_static_page_visit_logs.py" element="(does not exist)">
**What changes.** Nothing can, because the file is not in the tree. The requirements ("must keep it green") and the DEPLOYMENT.md:465 rat-tail comment both name it. Glob finds only `tests/tmp/test_21_static_page_visit_logs_phase{1,2,3}.py`.
**What depends on it.** The plan's claim that the About mapping is guarded.
**Regression risk.** There is no gate today for "no About URL or dev-pages name changes". The plan does not change those names, so there is no regression. But the claimed guard is absent, and the DEPLOYMENT.md comment points at a missing file. This is pre-existing drift from issue 21's delivery, and should be named in the delivery comment or opened as a follow-up issue, not fixed silently here.
</impact>
<impact path="tests/tmp/test_21_static_page_visit_logs_phase3.py" element="TEMPLATE read (lines 27, 237)">
**What changes.** Nothing.
**What depends on it.** It serves the template bytes through a real nginx.
**Regression risk.** None. A script tag does not change the pages-log lines. These are working files, not gating tests.
</impact>
<impact path="tests/active/test_profiles.py" element="plaintext-key byte scan (line 103)">
**What changes.** Nothing.
**What depends on it.** users.db contents.
**Regression risk.** None. The new table is empty in those tests.
</impact>
<impact path="tests/last_test_validation.json" element="per-group digests (e.g. lines 46-60)">
**What changes.** It is regenerated by the run. Groups that claim `client/backend/server.py` or `users_store.py` re-run, including test_blocks, test_dislikes and test_profiles. New test files become new groups.
**What depends on it.** The test validator.
**Regression risk.** Low. The record has to be regenerated, not hand-edited.
</impact>
<impact path="DEPLOYMENT.md" element="§2 Triage: new subsection \"Count About analytics events\" (after \"Follow an About visit\", lines 232-258, before \"Follow one request\", line 260)">
**What changes.** New subsection:
- the `sqlite3 -readonly <root>/client/backend/db/users.db` invocation;
- fenced `sql` blocks for total and daily clicks per `track_id` (UTC, `date(created_at / 1000, 'unixepoch')`), total and daily `page_view` optionally per `page_path`, and the bot-filtered variants;
- caveats: forgeable within 90/min per address, unbounded retention, the bot filter is a heuristic, Referer is often reduced, middle-click and context-menu opens are not counted, non-http(s) tracked links are rejected, and the `sendBeacon` cross-origin dev caveat.
**What depends on it.** The counter test extracts the SQL from here. Line 116's §2 prose already links to "Follow an About visit".
**Regression risk.** Medium, because of the coupling with the test. A prose edit that renames the heading or changes the fences breaks the gate. `sqlite3 -readonly` against a live WAL-less DB is safe. The DB is not in WAL mode, since `connect_db` sets no `journal_mode`, so a long reader can briefly block writers. That is worth one sentence.
</impact>
<impact path="DEPLOYMENT.md" element="\"Follow an About visit\" caveat (line 258)">
**What changes.** Rewrite it to say the pageview beacon now exists and to point at the new subsection, with the issue path changed to `docs/project/issues/archive/18-about-outbound-click-tracking.md`.
**What depends on it.** Readers of the runbook.
**Regression risk.** Low.
</impact>
<impact path="DEPLOYMENT.md" element="§5 route prose (lines 404-414)">
**What changes.** Lines 404-406 say "There is no browser-facing event publish route". That needs a clarifying sentence: `POST /api/analytics/event` is browser-facing but stores Client-side analytics rows only and publishes nothing to the Engine. Otherwise the new route reads as a contradiction of that line. Line 410's list of profile routes is unaffected, because the route needs no key.
**What depends on it.** The boundary contract readers.
**Regression risk.** Low.
</impact>
<impact path="DEPLOYMENT.md" element="§1 users.db note (lines 69-70), §6 CSP and prose (lines 459, 515, 519), §6 rat-tail comment (line 465), §6 Verify (lines 533-539), §7 Verify (lines 622-627)">
**What changes.**
- Lines 69-70: optionally note that users.db now also holds `analytics_events`, which is relevant to backups and size growth.
- Lines 459/515/519: no change, because `connect-src 'self'` covers a same-origin beacon. They are listed to confirm that nothing is needed.
- Line 465: it names `tests/active/test_static_page_visit_logs.py`, which does not exist (see that entry). This build touches the file anyway, so it should flag the drift. Fixing it is out of scope unless the operator agrees.
- §6/§7 Verify: optionally add a `curl -s -o /dev/null -w '%{http_code}' -X POST -d '{"type":"page_view","page_path":"/about","timestamp":0}' http://localhost/api/analytics/event` returning 204. Such a check writes a real row, so if it is added it must say so.
**What depends on it.** Operators.
**Regression risk.** Low.
</impact>
<impact path="client/README.md" element="Backend Responsibilities route list (lines 10-23) and Boundary Contract list (line 41)">
**What changes.**
- A new bullet for `POST /api/analytics/event`: the two types, the body fields, 204/400/429, Content-Type ignored, no key, stores to `analytics_events` in users.db, nothing IP-derived, and nothing published to the Engine.
- Line 41's "write/profile" list gets the route, or a new "analytics" line.
- Line 6 ("write/profile API service that publishes events to Engine") and line 10 ("Owns user write/profile endpoints") are slightly narrower than the truth once this lands. Adding "and the About analytics endpoint" there is optional.
- Line 69 (`TRUSTED_PROXIES` "keys the rate limiters") stays true.
**What depends on it.** Readers.
**Regression risk.** Low.
</impact>
<impact path="client/frontend/README.md" element="\"Local About Overrides\" (lines 36-42); \"What it does\" (lines 7-19); Boundary Contract (lines 21-24)">
**What changes.**
- "Local About Overrides": an override adds the same root-absolute `<script type="module" src="/src/...">` tag, plus `data-track-id="<[a-z0-9_]{1,64}>"` on each outbound link. Only http(s) links count. Middle-click and context-menu opens are not counted.
- "What it does": a bullet saying the About page sends a `page_view` on load and an `outbound_click` per tracked link click to the Client API base.
- Boundary: line 24's cross-origin dev note should mention that beacons from the dev About page need `CLIENT_CORS_ORIGINS` and are subject to the `sendBeacon` preflight caveat.
**What depends on it.** The operators who own the untracked override.
**Regression risk.** Low.
</impact>
<impact path="README.md" element="ownership table row for browser-facing write/profile API (line 50)">
**What changes.** The plan does not list this file, but line 50 enumerates the Client backend's browser-facing write routes (`/api/user-action`, `/api/user-profile/*`, `/api/profile*`). The requirement "added wherever ... lists the Client backend's public routes" covers it. Add `/api/analytics/event` to that row, or add a new row "About analytics events | Client backend".
**What depends on it.** Readers.
**Regression risk.** Low.
</impact>
<impact path="CONTEXT.md" element="glossary: new **Analytics event** entry (near **Interaction event**, line 6)">
**What changes.** One line in the existing style (`- **Term** — ...`): what an analytics event is, its two types (`outbound_click`, `page_view`), that it belongs to the Client backend (users.db `analytics_events`) and not the Engine, and that it is distinct from an **Interaction event**, which feeds the Engine. It is anonymous, and nothing derived from the client address is stored.
**What depends on it.** The domain docs.
**Regression risk.** None.
</impact>
<impact path="docs/project/issues/18-about-outbound-click-tracking.md" element="Status line (line 3), `## Comments`, file location">
**What changes.**
- `Status: enhancement, needs-triage` → `Status: enhancement, complete`.
- Append a delivery comment in the style of archive/21's line 31. It should name the plan, and say that the endpoint became `/api/analytics/event` (not `/outbound-click`), the table `analytics_events` (not `outbound_click_events`), shape validation instead of an allowlist, the target file `dev-pages/about.template.html` (line 14 names a non-existent `client/frontend/about.html`), and no `ip_hash`. It should also list what was scoped out.
- Move the file to `docs/project/issues/archive/`, per docs/project/issue-tracker.md:21.
**What depends on it.** DEPLOYMENT.md:258, plan.md and plan 23's links to the old path.
**Regression risk.** Low. The links have to be updated together with the move.
</impact>
<impact path="docs/project/issues/plan.md" element="P5 row (line 42) and lane 5c (line 98)">
**What changes.**
- Line 42 ("19, 20 and 21 are delivered, and 18 remains"): mark 18 delivered.
- Line 98: mark 18 delivered with the plan path `docs/project/plans/23-18-about-outbound-click-tracking.md`.
**What depends on it.** The tracker.
**Regression risk.** None. The plan names only lane 5c, but line 42 also needs updating.
</impact>
<impact path="docs/project/issues/21-static-page-visit-logs.md" element="stale non-archive duplicate of the delivered issue 21">
**What changes.** Nothing is planned. Both `docs/project/issues/21-static-page-visit-logs.md` and `archive/21-static-page-visit-logs.md` exist. The non-archive copy is left over from issue 21's delivery, and its line 27 still references 18.
**What depends on it.** Tracker hygiene.
**Regression risk.** None. Mention it in the delivery notes. Deleting it is outside this issue unless the operator agrees.
</impact>
<impact path="docs/project/issues/archive/21-static-page-visit-logs.md" element="delivery comment (line 31)">
**What changes.** Nothing is required. It refers to issue 18 by slug (`18-about-outbound-click-tracking`), not by path, so the move does not break it. Optionally append a note that the beacon was delivered by plan 23.
**What depends on it.** Nothing.
**Regression risk.** None.
</impact>
<impact path="docs/project/roadmap.md" element="line 157 (\"Logging: 19 -> 20 -> 21; 18 is orthogonal\")">
**What changes.** Nothing is required. It is a sequencing note and stays true.
**What depends on it.** Nothing.
**Regression risk.** None.
</impact>
<impact path="engine/server/README.md" element="line 19 (Engine does not own browser-facing write/profile routes)">
**What changes.** Optional. The Engine also does not own `/api/analytics/event`. Nothing is wrong if this is left as is.
**What depends on it.** Nothing.
**Regression risk.** None.
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="Client route smoke checks (around line 560)">
**What changes.** Nothing is planned. A smoke check for `POST /api/analytics/event` answering 204 could be added, but it would write a row into the target users.db. Leave it out unless asked.
**What depends on it.** Nothing.
**Regression risk.** None.
</impact>
<impact path="docs/project/plans/23-18-about-outbound-click-tracking.md" element="the plan document">
**What changes.** The workflow renders it, so it is not hand-edited. Per issue-tracker.md:29, a delivered feature plan moves to `docs/project/plans/archive/`. If the move happens, the plan path in plan.md and in issue 18's delivery comment must follow it.
**What depends on it.** Links from plan.md:98 and the issue comment.
**Regression risk.** Low.
</impact>


### docs_checklist


<doc path="DEPLOYMENT.md">
- New Triage subsection "Count About analytics events", placed between "Follow an About visit" and "Follow one request". It holds the `sqlite3 -readonly` invocation, the `sql` blocks for total and daily clicks per `track_id`, the total and daily `page_view` queries optionally per `page_path`, and the bot-filter variants, plus caveats: forgeable within 90/min per address, unbounded retention, the heuristic bot filter, reduced Referer, uncounted middle-click and context-menu opens, the cross-origin `sendBeacon` loss in dev, and readers briefly blocking writers.
- Line 258: rewrite the caveat to say the beacon exists and point at the new subsection, with the issue path changed to `archive/`.
- Lines 404-406: clarify that `POST /api/analytics/event` is browser-facing but publishes nothing to the Engine.
- Optional: lines 69-70, note that users.db now holds `analytics_events`.
- Optional: a §6 Verify line, noting that it writes a row.
- Line 465: flag that it names the non-existent `tests/active/test_static_page_visit_logs.py`. This is pre-existing drift.
</doc>
<doc path="client/README.md">
- Backend Responsibilities (lines 10-23): a new bullet for `POST /api/analytics/event` covering its types and fields, 204/400/429, Content-Type ignored, no key, storage in users.db `analytics_events`, nothing IP-derived, and no Engine publish.
- Boundary Contract (line 41): add the route.
- Optional: widen the wording at lines 6 and 10.
</doc>
<doc path="client/frontend/README.md">
- "Local About Overrides": the module script tag (root-absolute) and the `data-track-id` convention, `[a-z0-9_]{1,64}`. Only http(s) links count, and middle-click and context-menu opens are not counted.
- "What it does": a bullet for the About page beacon.
- Line 24: dev cross-origin beacons need `CLIENT_CORS_ORIGINS`, plus the `sendBeacon` caveat.
</doc>
<doc path="README.md">
Line 50 ownership table: add `/api/analytics/event` to the Client backend's browser-facing routes, or add a row for it. The plan misses this file.
</doc>
<doc path="CONTEXT.md">
New glossary entry **Analytics event**: its two types, that it belongs to the Client backend (users.db), its anonymity, and how it differs from an **Interaction event**.
</doc>
<doc path="docs/project/issues/18-about-outbound-click-tracking.md">
`Status: enhancement, complete`. Add a delivery comment stating the departures from the issue text: the route name, the table name, no allowlist, no ip_hash, and the template path. Move the file to `docs/project/issues/archive/`.
</doc>
<doc path="docs/project/issues/plan.md">
Line 42 (P5 row): mark 18 delivered. Line 98 (lane 5c): mark 18 delivered with the plan path.
</doc>


### highest_risk


client/backend/server.py `connect_db`/the shared `user_db` (lines 230-234, 311): every handler thread uses one `sqlite3` connection with `check_same_thread=False` and no lock. `with conn:` commits or rolls back whatever is in flight on that connection, so a beacon's commit can commit half of a concurrent `_store_reaction` transaction, and a rollback elsewhere can drop the beacon's row. The race exists today, but this is the first anonymous, high-rate (90/min/address) write route, which makes it far more likely to be hit.
client/backend/server.py new validation function: anything that is not shape-checked before use crashes the request instead of answering 400. A non-str field reaching `re`/`len`/`urlsplit` raises `TypeError`, and a lone-surrogate string from `json.loads` in `href`/`page_path` raises `UnicodeEncodeError` at the INSERT. Either one escapes `_run_request`, leaving no response and `request.end status=-`, and the planned "each invalid case gives 400" tests do not cover them unless added.
client/frontend/src/about-analytics.ts transport: `sendBeacon` with an `application/json` Blob cross-origin needs a credentialed preflight. The backend never sends `Access-Control-Allow-Credentials` (ADR-0004), so the beacon is dropped after `sendBeacon` has already returned true, and the fetch fallback never runs. `npm run dev` is always cross-origin (scripts/dev.mjs), so dev page views and clicks can vanish silently while every node-stubbed test passes. A detached `sendBeacon` call ("Illegal invocation") and Node ≥21's read-only `globalThis.navigator` in the test runner are the matching implementation and test traps.

## 2026-10-02 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

I checked the inventory against the files at its paths. I read `client/backend/server.py` (imports, `_serve_get`/`_serve_post`, `_rate_limit_check`, `_store_reaction`, `_handle_likes_import`, `connect_db`, startup), `lib/http_utils.py`, `lib/users_store.py`, `tests/active/conftest.py`, `tests/active/test_server.py:383-414`, `tests/active/test_frontend_profile.py`, `vite.config.ts`, `scripts/dev.mjs`, `dev-pages/about.template.html`, `src/data/api-base.ts`, `client/frontend/README.md`, DEPLOYMENT.md §2 "Follow an About visit", §6 nginx and §6 CORS, `README.md:50`, `CONTEXT.md`, `docs/project/issues/plan.md`, issue 18 and `.gitignore`. Every factual claim I could reach holds. One claim I could not confirm (node_modules), and I found three things the inventory does not carry. None of them breaks the settled plan. Two change what the docs must say about how accurate the counts are, and one changes the cheapest fix for the dev-only beacon loss the inventory already raised.
<question id="1">Yes, in production. nginx's `location /api/` (DEPLOYMENT.md:486-493) already proxies the new path to the Client backend. The server CSP's `connect-src 'self' https:` allows a same-origin beacon. `read_json_body` ignores Content-Type and raises `ValueError` on every malformed input the plan lists. `_serve_post` has room for one more exact-match branch before line 501. `ensure_user_schema` runs at startup (server.py:1311).

It works only if three implementation details already in the inventory are honoured. First, every field is type-guarded before `re`/`len`/`urlsplit`, and strings that cannot be encoded as UTF-8 (lone surrogates) are rejected, or they escape as an unhandled error at INSERT rather than a 400. Second, the rate-limit test runs on a 90/60 limiter, because conftest's `client_backend` uses `RateLimiter(1000, 60)` (line 84). Third, the raw-body and header cases use raw `urllib` requests, because `ClientBackend.request` forces JSON. In dev under `npm run dev` it does not reliably work: the page is cross-origin (dev.mjs:104), `sendBeacon` is credentialed, and the server never sends `Access-Control-Allow-Credentials` (DEPLOYMENT.md:620). An `application/json` beacon is therefore preflighted and dropped after `sendBeacon` has already returned true, so the fallback never runs.</question>
<question id="2">
- **Shared connection.** The Client backend gains its first anonymous, high-rate write route on the one shared `sqlite3.Connection`, which has no lock (only `RateLimiter.lock` exists). `with conn:` from a beacon thread can therefore commit or roll back another thread's in-flight `_store_reaction` transaction. The race exists today, but this route makes it much more likely to be hit.
- **Rate limit undercounts silently.** Counting accuracy is now tied to client-address resolution. Behind an unlisted CDN or proxy, or a shared NAT, all those visitors share one 90/min bucket. Extra beacons get 429, which `sendBeacon` never sees, so counts silently under-report rather than error.
- **Every About visit now reaches the Client backend.** Each view adds a `request.start`/`request.end` pair to the Client journal and a line to nginx's main access log, and each tracked click adds another. This changes what the "Follow an About visit" recipe prints.
- **users.db grows.** It now grows without bound and holds the UA and Referer (up to 64 KiB each per row).
- **Committed `dist/`.** It lags until the next `scripts/sync.sh`, so prod has no beacon until that runs.</question>
<question id="3">Beyond what the plan lists, existing functionality also needs these:
- **Validation strictness.** Reject non-`str` fields before use, `bool` and `float` timestamps, and strings that fail `.encode("utf-8")`, so no request ends without a response.
- **Placement and transaction ownership.** Keep the new branch before server.py:501. `insert_analytics_event` must not commit internally.
- **Docs the plan omits.**
  - `README.md:50`: the route list.
  - `docs/project/issues/plan.md:42`: the P5 row, not only lane 5c at line 98.
  - DEPLOYMENT.md:404-406: a sentence saying the new browser-facing route publishes nothing to the Engine, so "There is no browser-facing event publish route" stays true.
  - DEPLOYMENT.md:241-251: the visit recipe now always shows the beacon.
  - The analytics caveats: undercounting under a shared address.
- **Tracker.** Move issue 18 to `archive/` and update DEPLOYMENT.md:258's link in the same change.
- **Tests that fail rather than pass vacuously.**
  - Pin the DEPLOYMENT heading and assert the SQL block count.
  - Pass the built-page test an absolute `--outDir` with `--emptyOutDir`, and never write into `dist/`.
- **Missing guard.** Name the absent `tests/active/test_static_page_visit_logs.py` instead of claiming it stays green.</question>
<question id="4">
- **Backend.** The Client backend gains a browser-facing anonymous write endpoint. Its 404-for-unknown-POST surface shrinks by one path, while `GET /api/analytics/event` still answers 404. users.db gains one table and one index. No existing route, response shape, limiter bucket (the key is `<ip>:<path>`, so the new route has its own bucket) or Engine contract changes.
- **About page.** It goes from zero JavaScript (the template has no script) to loading one module that sends a request on load and on each tracked click. It still renders the same with JS off or the beacon failing, because the listener never calls `preventDefault`.
- **Runbook.** The "Follow an About visit" recipe now finds at least one app request per visit where a template visit used to find none.</question>

New impacts:
client/frontend/vite.config.ts — `server.proxy['/api']` (lines 27-32) already forwards dev `/api` to `127.0.0.1:7172`. When `VITE_CLIENT_API_BASE` is unset (plain `npx vite`), `resolveClientApiBase()` returns the page origin and the beacon is same-origin through this proxy, so the credentialed-`sendBeacon` loss is specific to `npm run dev` (dev.mjs:104 always sets a cross-origin base), not to all dev. That narrows the inventory's dev.mjs/http_utils entries and gives a doc-only mitigation (run About checks with `npx vite`, or `--client-api-base` set to the page's own origin) besides the `text/plain` Blob change.
DEPLOYMENT.md — §6 X-Forwarded-For/TRUSTED_PROXIES prose (line 523): "Omit the lines and every visitor shares one bucket" now also means every About visitor shares one 90/min analytics bucket. Beacons past it get 429, which `sendBeacon` never surfaces, so counts silently saturate. The same holds for visitors behind one NAT. The new "Count About analytics events" caveats must name this undercount, which differs from the forgeable-overcount risk the plan already names.
DEPLOYMENT.md — §2 "Follow an About visit" recipe (lines 241-251): every About view now produces its own `POST /api/analytics/event` `request.start` from the visitor's `ip` seconds after the pages line, plus one per tracked click. The recipe's output changes, from nothing on a template visit to at least the beacon. The beacon is the visit's most reliable address-and-time anchor, but it still does not carry the pages-log request id, so the line-254 caveat stays true. The plan rewrites only line 258, and this paragraph needs a sentence too.

Inventory entries that did not hold up:
client/frontend/vite.config.ts entry, "No `node_modules` in this worktree. A Glob for `client/frontend/node_modules` found nothing": I could not confirm this. My Glob of `client/frontend/node_modules/.bin/*` was refused by the sandbox as leaving the project directory, which suggests `node_modules` exists as a symlink pointing outside the worktree. That fits `.gitignore:1-2` ("worktrees hold these as symlinks"). `vite` and `esbuild` are then probably resolvable the same way `test_frontend_profile.py`'s `ESBUILD` path is. The entry's conclusion (fail or skip with a clear reason if they are missing) still stands, but its premise that they are absent is unverified and probably wrong. Every other entry matched its file.

Conflicts: none

Recommendations: 1. **Reject unencodable strings.** In the validator, return a 400 for any `href` or `page_path` that fails `.encode("utf-8")`, and add one test case with `"\ud800"`. Cost: about 2 lines and 1 test. Without it, a crafted body ends with an unhandled exception and no response instead of a 400.
2. **Decide the dev beacon behaviour (operator's call).**
   - (a) Docs only: the frontend README and the new DEPLOYMENT subsection say `npm run dev` loses `sendBeacon` events cross-origin, and that `npx vite` (same-origin via the existing `/api` proxy) or the fetch path is the way to check locally. Cost: two sentences. Prod unaffected.
   - (b) Send a `text/plain` Blob when the API base's origin differs from `location.origin`. Cost: about 3 lines and 1 node-test case, plus a departure from the requirement's literal `application/json`, cross-origin only.

   I recommend (a): it stays inside the settled spec, and the server accepts `text/plain` anyway if (b) is wanted later.
3. **Undercount caveat.** Add it to the new DEPLOYMENT subsection: a shared or misresolved client address caps counting at 90 beacons/min for everyone behind it, and the drops are silent. Cost: one line.
4. **Visit recipe sentence.** Add one sentence to "Follow an About visit" (lines 241-251) saying the visit's own beacon shows up in the window. Cost: one line.
5. **Docs the plan omits.** Add `README.md:50`'s route list, `plan.md:42`, and a clarifying sentence at DEPLOYMENT.md:404-406. Cost: three small edits. Skipping them leaves docs that understate or contradict the route surface.
6. **Shared-connection race.** Do not fix it in this build. Name it in the delivery comment and open a follow-up issue (a write lock or per-thread connection for `users.db`). Cost: one issue file. Fixing it here would change every write route's concurrency and widen the build's scope.
7. **Missing guard file.** Do not claim `test_static_page_visit_logs.py` stays green, because it does not exist. Name it, together with the DEPLOYMENT.md:465 rat-tail that cites it and the stale `docs/project/issues/21-static-page-visit-logs.md` duplicate, in the delivery comment, and open a follow-up issue. Cost: wording plus one issue.
8. **Module placement.** Put the module at `src/pages/about/index.ts` to match the five existing `src/pages/*/index.ts` entries. Cost: none, but the script tag, the README and both tests must name the same path.
9. **Test tooling.** In the gating tests, resolve `vite`/`esbuild` from `client/frontend/node_modules/.bin` as `test_frontend_profile.py` does, and fail with a clear message rather than skip when they are missing, so a missing toolchain cannot quietly hollow out the gate. Use an absolute `--outDir` under `tests/tmp/` with `--emptyOutDir`. Cost: none beyond the planned test.

## 2026-10-02 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impact path="client/backend/server.py" element="module imports (lines 5-41) and module constants (lines 46-73)">
**What changes.**
- `re` is not imported today (lines 5-23). `urllib.parse` gives only `parse_qs, urlencode, urlparse` (line 20). The plan's `re.fullmatch` and `urlsplit` therefore need `import re` and `urlsplit` added to line 20. The `urlparse` already imported would also work: `.hostname` raises the same `ValueError` on a malformed bracketed host.
- `insert_analytics_event` joins the wrapped, alphabetised `from lib.users_store import (...)` block at lines 39-41, between `get_or_create_user` and `load_liked_keys`.
- New constants go in the style of `USER_ACTIONS = frozenset((...))` (line 62) and `BLOCK_REFERENCE_MAX_LENGTH = 200` (line 68): a two-value type frozenset, a compiled `[a-z0-9_]{1,64}` pattern, a 2048 href cap and a 256 page_path cap. Each is one line, with a one-line comment where the value needs explaining.

**What depends on it.**
- `tests/active/conftest.py:43` imports this module as `client_server`.
- `test_server.py:161` re-imports from conftest.
- Every test that uses the Client backend imports it.

**Regression risk.** Low. An import or name error fails the whole active suite at collection time, so it is loud, not silent.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._serve_post (lines 437-501): new `/api/analytics/event` branch">
**What changes.**
- A new `if url.path == "/api/analytics/event":` branch goes before the comment at lines 497-500 and the final `respond_json(self, 404, ...)` at line 501.
- Its shape is identical to `/api/user-action` (464-469): `_rate_limit_check(url.path)`, then 429 `{"error": "Rate limit exceeded"}`, then `self._handle_analytics_event()`.
- That handler reads the body with `read_json_body` inside `try/except ValueError`, answering 400 `{"error": str(exc)}`, exactly as `_handle_likes_import` (1014-1018) and `_read_block_body` (1050-1054) do.
- It then validates, runs `with self.server.user_db: insert_analytics_event(...)`, and answers `respond_bytes(self, 204, b"")` as `/api/profile/delete` does (line 462).

**What depends on it.**
- `do_POST` → `_run_request` (339-379) wraps it, so `request.start`/`request.end` come for free. `request.start` already logs `ip` and `user_agent`; that is log only, not storage.
- `_serve_get` (381-435) is untouched, so `GET /api/analytics/event` still falls to the 404 at line 435.
- `do_OPTIONS` answers `respond_options` for any path, so a CORS preflight to the new path already gets 204.

**Regression risk.** Low for existing routes, since the match is on the exact path. Points to watch:
- **Body left unread on 429.** The rate check runs before the body is read, so a 429 leaves the body on the socket. That is harmless only because nothing in `client/backend` sets `protocol_version` or `close_connection` (I grepped). The server stays HTTP/1.0 and closes each connection.
- **Placement.** A branch placed after line 501 never runs.
- **Bucket key.** It is `<ip>:/api/analytics/event`, so analytics has its own 90/min bucket and does not consume `/api/user-action`'s.
- **No socket timeout.** The handler sets no `timeout`, so a `Content-Length` larger than the bytes actually sent blocks the thread in `rfile.read` indefinitely. This is inherited from every POST route, but this one is anonymous and called on every About visit.
</impact>
<impact path="client/backend/server.py" element="new module-level validator (e.g. `_validate_analytics_event(body)`), placed near `_parse_client_likes` (lines 1236-1252)">
**What changes.** A new pure function in the style of its siblings: a `_` prefix and a `"""Handle ...` / `:returns:` docstring.

**What depends on it.** The route handler, and the backend tests, which can call it directly as `client_server._validate_...`.

**Regression risk.** Medium. Each failure below is an escaped exception rather than a silent accept: it ends at socketserver's `handle_error`, the client gets no response, and `request.end` logs status `-`. That is not the required 400.
- **Type guards.** Check every field with `isinstance(..., str)` before `re.fullmatch` (which raises `TypeError` on an int), `len`, `.startswith` or `urlsplit`.
- **`bool` is an `int`.** `timestamp: true` must be rejected, and so must `1.0`, because `json.loads` returns a `float` for it.
- **Lone surrogates.** `json.loads('"\ud800"')` yields a `str` that sqlite3 cannot bind (`UnicodeEncodeError`). It escapes at INSERT time, so `href` and `page_path` should be rejected when `.encode("utf-8")` fails. `track_id` is safe because of its regex. The headers are safe because http.server decodes them as latin-1.
- **`urlsplit` details.**
  - `urlsplit("https://")` gives `hostname=None`, which must be rejected.
  - `urlsplit("http://[::1")` raises `ValueError`, which must be caught.
  - The scheme comes back lowercased, so `HTTPS://x` passes.
  - `href` is stored verbatim.
- **Null handling.** An explicit `null` `track_id` or `href` must be rejected on `outbound_click` and accepted on `page_view`.
- **`page_path`.** `//evil.example` passes the leading-slash rule. That is acceptable because the value is stored and never followed.
</impact>
<impact path="client/backend/server.py" element="row header capture (`self.headers.get('User-Agent')`, `self.headers.get('Referer')`) and `_get_client_ip` (lines 326-329)">
**What changes.** The handler strips each of the two headers and stores `None` when the result is empty. That mirrors `_run_request` at lines 347-349. `_get_client_ip` is reached only through `_rate_limit_check`.

**What depends on it.** The "nothing IP-derived stored" requirement, and the `PRAGMA table_info` test.

**Regression risk.** Low.
- Values are stored up to http.server's 64 KiB line cap, which the plan accepts.
- `X-Forwarded-For` and `X-Real-IP` must never reach the row. nginx sets both on `/api/` (DEPLOYMENT.md:489-490).
</impact>
<impact path="client/backend/server.py" element="connect_db (lines 230-234) and the single shared `user_db` connection (line 311)">
**What changes.** No code change. The new route adds writes on this connection.

**What depends on it.** Every profile write: `_store_reaction` (961-1003, multi-statement `with conn:` blocks at 974, 991 and 999), the likes import, blocks, reset, mint, rotate and delete.

**Regression risk.** Medium. The plan names this only as "serialises briefly", and it is more than that.
- There is one `sqlite3.Connection` with `check_same_thread=False`, shared by every `ThreadingHTTPServer` thread. There is no lock: I grepped, and the only lock is `RateLimiter.lock`.
- `with conn:` commits or rolls back the connection's single transaction. A beacon's commit on one thread can therefore commit another thread's half-done `remove_like` + `close_like` + `write_dislike`, and a rollback elsewhere can undo a beacon insert.
- The race already exists. This is the first anonymous write route allowed 90/min per address, so it makes the race far more likely to be hit.
- Name it as an inherited limitation and open a follow-up issue (a write lock or per-thread connection). Do not fix it in this build.
</impact>
<impact path="client/backend/server.py" element="main() startup: `ensure_user_schema(user_db)` (line 1311)">
**What changes.** No edit. The table and index are created on the next restart through this existing call.

**What depends on it.** Prod and dev upgrades. There is no migration step, consistent with DEPLOYMENT.md:408.

**Regression risk.** Low. `executescript` COMMITs first, which is harmless at startup.
</impact>
<impact path="client/backend/lib/users_store.py" element="ensure_user_schema (lines 10-71): docstring and script">
**What changes.**
- Add `CREATE TABLE IF NOT EXISTS analytics_events (...)` with the settled columns and `CHECK (type IN ('outbound_click', 'page_view'))`.
- Add `CREATE INDEX IF NOT EXISTS ... ON analytics_events (type, track_id, created_at)`, named like `likes_user_updated_idx` (line 27).
- Both go before the `local-user` cleanup DELETEs (67-69).
- The docstring on line 11 lists the tables the function creates, so it must gain "analytics event".

**What depends on it.**
- `server.py:1311`.
- `tests/active/conftest.py:77` and `:169`.
- `tests/active/test_server.py:398`, `:834` and `:997`.

**Regression risk.** Low. I grepped tests/active for `sqlite_master` and `table_info`. No hit enumerates the tables in users.db: test_moderation, test_similarity_cache, test_precompute_similar_ann, test_videos, test_videos_worker and test_whitelist_migrations all target other databases.
</impact>
<impact path="client/backend/lib/users_store.py" element="new insert_analytics_event(conn, event_type, track_id, href, page_path, created_at, user_agent, referer)">
**What changes.** A new function that runs one parameterised INSERT.
- It must not call `conn.commit()`: the handler's `with self.server.user_db:` owns the transaction.
- The module is inconsistent on this point. `get_or_create_user`, `record_like` and `clear_likes` commit internally, while `remove_like` and `close_like` say "inside the caller's transaction" (lines 192, 216). Follow `remove_like`/`close_like`, including that docstring phrase.

**What depends on it.** The route, and the counter test that reads the rows back.

**Regression risk.** Low. Take `created_at` from a single source, the handler's `now_ms()`, so the test's request window holds.
</impact>
<impact path="client/backend/lib/http_utils.py" element="read_json_body (lines 78-95)">
**What changes.** Nothing.

**What depends on it.** Every JSON POST route.

**Regression risk.** None from an edit. I confirmed by reading it that it behaves as the plan expects:
- It never reads Content-Type, so a `text/plain` body is accepted.
- A non-numeric `Content-Length` raises `ValueError` from `int()`.
- A body over 1,000,000 bytes raises `ValueError`.
- `.decode("utf-8")` raises `UnicodeDecodeError`, which is a `ValueError`.
- A non-dict body raises `ValueError`.
- A length of 0 or less, a missing length, or a whitespace-only body returns `{}`.
</impact>
<impact path="client/backend/lib/http_utils.py" element="_send_cors_headers / respond_options / ALLOWED_REQUEST_HEADERS (lines 12-44, 71-75)">
**What changes.** Nothing.

**What depends on it.** The cross-origin dev beacon.

**Regression risk.** No backend regression, but there is a frontend consequence the plan's "cross-origin dev base" risk understates.
- No `Access-Control-Allow-Credentials` header is ever sent (lines 38-44, and DEPLOYMENT.md:620).
- `navigator.sendBeacon` always uses credentials mode `include`. An `application/json` Blob is not CORS-safelisted, so cross-origin it is preflighted, and a credentialed preflight without Allow-Credentials fails.
- By then `sendBeacon` has already returned `true`, so the fetch fallback never runs and the event is lost silently.
- Prod is same-origin and unaffected.
- A `text/plain` Blob is safelisted and the server accepts it. Using one would depart from the requirement's literal `application/json`.
</impact>
<impact path="client/backend/lib/http_utils.py" element="RateLimiter (lines 98-124)">
**What changes.** Nothing.

**What depends on it.** The new route's 429.

**Regression risk.** Low.
- Buckets are never evicted. A beacon route hit by every About visitor adds one deque per distinct address until restart. This happens on every route already, but this route grows it faster.
- `max_requests <= 0` disables the limiter.
- A 429 is invisible to `sendBeacon`. Behind a shared or misresolved address, counts silently saturate at 90/min.
</impact>
<impact path="client/backend/lib/profiles.py" element="delete_profile">
**What changes.** Nothing. Analytics rows carry no profile id, so profile deletion neither touches them nor needs to.

**What depends on it.** `client/README.md:13` ("everything keyed to it"), which stays true.

**Regression risk.** None.
</impact>
<impact path="client/frontend/src/about-analytics.ts" element="new module (whole file); placement alternative `src/pages/about/index.ts`">
**What changes.** A new module that imports `resolveClientApiBase` from `./data/api-base`.
- On load it sends one `page_view`. It installs one delegated `click` listener on `document`. A `send()` helper tries `sendBeacon` and falls back to `fetch(..., {keepalive: true})`.
- Style: a `/** Module \`client/frontend/src/...\`: ... */` header (api-base.ts:1-3) and a `/** Handle ... */` JSDoc on each function.
- **URL construction.** Every sibling builds URLs as `new URL("/api/...", resolveClientApiBase(...))` (user-actions.ts:20, reactions.ts:34/68, blocks.ts:57, profile.ts:88). None concatenates, so the earlier inventory's "the other modules concatenate the same way" was wrong.
  - The plan's "base plus `/api/analytics/event`" should follow `new URL`. That also removes the double-slash 404 when `VITE_CLIENT_API_BASE` has a trailing slash.
  - `new URL` throws on an invalid base, so that call goes inside the try.
- **Placement.** The other five page entries live at `src/pages/<page>/index.ts`. `src/pages/about/index.ts` would match that convention; the plan's `src/about-analytics.ts` at the src root breaks it.

**What depends on it.**
- The template's script tag.
- The README override instructions.
- The node test and the built-page test.
- The new test group in `.un/skills/devsecops/config.json`.
All of these must name the same path.

**Regression risk.** Medium, because every failure is silent by design:
- `navigator.sendBeacon` must be called as a method. A detached call throws "Illegal invocation", the catch swallows it, and every event goes through fetch.
- `event.target` can be a Text node, which has no `closest`.
- An SVG `<a>`'s `.href` is an `SVGAnimatedString`, which the server rejects.
- api-base.ts:5 reads `window.location.origin` at import time.
- The work happens at import, so the node test must install its stubs before `import()`.
- A module script is deferred, so the `document` listener needs no DOMContentLoaded wait.
- `fetch` can throw synchronously (a keepalive body over 64 KiB) as well as reject asynchronously, so it needs both the try and the `.catch`.
</impact>
<impact path="client/frontend/src/data/api-base.ts" element="resolveClientApiBase (lines 18-33), DEFAULT_CLIENT_API_BASE (line 5)">
**What changes.** Nothing. It is called with no argument, so `?api=` is never read. In prod it returns `window.location.origin`.

**What depends on it.** The new module and every data module.

**Regression risk.** Low.
- `normalizeApiBase` keeps a trailing slash. That is harmless only if the new module uses `new URL(path, base)` as its siblings do.
- If a build bundles it into a shared chunk that the About entry now also imports, the other pages' asset hashes may change. That is harmless.
</impact>
<impact path="client/frontend/src/vite-env.d.ts" element="ImportMetaEnv">
**What changes.** Nothing. No new env var is read.

**What depends on it.** The typing of `import.meta.env`.

**Regression risk.** None.
</impact>
<impact path="client/frontend/dev-pages/about.template.html" element="new `<script type=\"module\" src=\"/src/...\">` tag">
**What changes.** One line.
- The sibling pages put the tag at the end of `<body>`: index.html:65, channels.html:106, likes.html:35, search.html:63, video-page.html:146.
- Vite moves it into `<head>` as `<script type="module" crossorigin src="/assets/...">` in the built output, as dist/channels.html:12 shows.
- The URL must be root-absolute (client/frontend/README.md:41).

**What depends on it.**
- `vite.config.ts` uses this file as the `about` input when no override exists.
- nginx serves the built copy (DEPLOYMENT.md §6).
- `.un/skills/devsecops/config.json:263-268` maps it to the non-existent `test_static_page_visit_logs.py`.
- `tests/tmp/test_21_static_page_visit_logs_phase{1,2,3}.py` read the template bytes into a real nginx. Phase1:131 asserts only that the template's length differs from a fixed override's.

**Regression risk.** Low.
- The page goes from zero JS to one module.
- The CSP `script-src 'self'` allows `/assets/*.js`, and `connect-src 'self'` allows a same-origin beacon.
- The tmp tests are not gating.
</impact>
<impact path="client/frontend/vite.config.ts" element="build.rollupOptions.input.about (lines 91-93), aboutSourcePath (16-18), server.proxy['/api'] (27-32)">
**What changes.** Nothing.

**What depends on it.** The built-page test, and dev beacons.

**Regression risk.** Medium for test design:
- **Override switch.** `existsSync(devAboutPath)` switches the build to an untracked override (`.gitignore:29-30`). The plan skips in that case.
- **`--outDir`.** It resolves against `client/frontend`, so pass an absolute path under `tests/tmp`, together with `--emptyOutDir`. Never write into the committed `dist/`.
- **Where the output lands.** The built page is `<outDir>/dev-pages/about.template.html`. The literal `/api/analytics/event` sits in the About entry chunk, while `api-base` may be split into a shared chunk.
- **No vite precedent.** No active test runs vite today; this is the first. Seven tests already run `FRONTEND/node_modules/.bin/esbuild`, and `test_frontend_profile` passed in the baseline record (`tests/last_test_validation.json:46-49`), so `node_modules` resolves in the gate environment. Glob does not follow the worktree's symlink, so I could not list `.bin/vite` directly. `vite` is a devDependency (package.json:18), so it should be there. If it is missing, fail with a clear message rather than skip.
- **Dev proxy.** `server.proxy['/api']` forwards to `127.0.0.1:7172`. Under plain `npx vite` (no `VITE_CLIENT_API_BASE`) the beacon is therefore same-origin and works. The credentialed-`sendBeacon` loss applies only to `npm run dev`, which always sets a cross-origin base.
</impact>
<impact path="client/frontend/scripts/dev.mjs" element="VITE_CLIENT_API_BASE default (lines 15, 46-49, 104)">
**What changes.** Nothing.

**What depends on it.** It makes the `npm run dev` About page cross-origin to `127.0.0.1:7172`. Beacons then need `CLIENT_CORS_ORIGINS`, and `application/json` sendBeacons are lost (see the http_utils CORS entry).

**Regression risk.** Not a regression: dev-only loss of events. Document it, or decide on a `text/plain` Blob.
</impact>
<impact path="client/frontend/dist/dev-pages/about.template.html" element="committed build output (and dist/assets/*)">
**What changes.** Not in the plan. The committed `dist/` lags the source (DEPLOYMENT.md:444). Today it has no script tag.

**What depends on it.** Prod deploys through `scripts/sync.sh`, which runs `npm run build` first (sync.sh:19).

**Regression risk.** Low. Prod has no beacon until sync runs. Say so in the delivery comment. The built-page test must not write here.
</impact>
<impact path="scripts/sync.sh" element="build-then-rsync (lines 19-23)">
**What changes.** Nothing.

**What depends on it.** It is the only path by which the beacon reaches prod.

**Regression risk.** None.
</impact>
<impact path="tests/active/conftest.py" element="client_backend fixture (lines 73-93), ClientBackend.request (55-70)">
**What changes.** Nothing, unless the tests add a helper.

**What depends on it.** The new backend tests.

**Regression risk.** Medium for test design:
- The fixture uses `RateLimiter(1000, 60)` (line 84), so the 91-post test cannot run on it.
- `ClientBackend.request` always sets `content-type: application/json` and JSON-encodes the body. The `text/plain`, invalid-JSON, empty-body and UA/Referer cases need raw `urllib` requests.
- Reading `db_path` with a second `sqlite3.connect` after a 204 is fine.
</impact>
<impact path="tests/active/test_server.py" element="`_client_backend` (394-403), `_serving` (383-391), `_status` (406-414)">
**What changes.** Nothing, unless the new tests live here or import these helpers.

**What depends on it.** The rate-limit test.
- It can use `_client_backend(tmp_path, CLOSED_ENGINE, RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS))`.
- The peer 127.0.0.1 is a trusted proxy by default, so `X-Forwarded-For` can model distinct addresses. `test_route_limiter_buckets_by_last_hop` (417) is the precedent.

**Regression risk.** Low. No existing test enumerates POST routes or uses this path.
</impact>
<impact path="tests/active/test_frontend_profile.py" element="esbuild-in-node pattern (ESBUILD line 21, RUNNER 23-43, _bundle 46-62, _node_path 89)">
**What changes.** Nothing. It is the template for the new node test. `test_frontend_video_page.py:105-134` adds the `globalThis.document`/`fetch` stub and `unhandledRejection` capture precedent.

**What depends on it.** The new test copies:
- the `--define:import.meta.env.VITE_CLIENT_API_BASE=...` and `--define:import.meta.env.DEV=false` flags;
- the `globalThis.window = {location: {origin}}` stub, set before `await import`.

**Regression risk.** For the new test:
- On Node ≥21, `globalThis.navigator` is a read-only getter, so the stub needs `Object.defineProperty(..., {configurable: true})`. No active test stubs `navigator` today (I grepped).
- Bare `location` must be stubbed alongside `window.location` if the module uses it.
- The beacon Blob must be read back with `await blob.text()`.
- `fetch` must be replaced to observe the keepalive fallback.
</impact>
<impact path="tests/active/test_analytics_events.py" element="new gating test file(s); name for the design step">
**What changes.** New tests: the backend endpoint, the counter that runs SQL from DEPLOYMENT.md, the node frontend test, and the vite built-page test. They can be one file or several.

**What depends on it.** The suite gate, and a new group in `.un/skills/devsecops/config.json`.

**Regression risk.** Medium:
- **SQL extraction.** The counter test parses the fenced `sql` blocks from the new DEPLOYMENT subsection. Pin the heading and assert the block count, so an empty extraction cannot pass vacuously.
- **Timestamps.** Take `now_ms()` before and after the request to bound `created_at`.
- **Columns.** Assert the exact `PRAGMA table_info(analytics_events)` column list, not merely the absence of an IP column.
- **Speed.** The vite build is slow, so give it a generous timeout.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (lines 14-269)">
**What changes.** A new `test_groups` entry is required for each new test file. It maps the file to:
- `client/backend/server.py`
- `client/backend/lib/users_store.py`
- `client/backend/lib/http_utils.py`
- the new frontend module
- `client/frontend/src/data/api-base.ts`
- `client/frontend/dev-pages/about.template.html`
- `client/frontend/vite.config.ts`
- `DEPLOYMENT.md`, for the SQL-block test

**What depends on it.**
- The validator that decides which groups re-run.
- The existing groups `test_profiles`, `test_dislikes`, `test_frontend_profile`, `test_server`, `test_blocks`, `test_frontend_blocks`, `test_frontend_reactions` and `test_frontend_upnext_pager` already claim `server.py` and/or `users_store.py`, so they re-run.

**Regression risk.** Medium. Without a group, the new tests may not be selected when these files change.
- Pre-existing drift: lines 263-268 map `test_static_page_visit_logs.py`, which does not exist in the tree and has no entry in `tests/last_test_validation.json`.
- That group claims `about.template.html` and `server.py`, both of which this build edits.
- The baseline still passed, so the missing file is tolerated, but it guards nothing.
</impact>
<impact path="tests/active/test_static_page_visit_logs.py" element="(does not exist)">
**What changes.** Nothing can, because the file is not in the tree (a Glob for `**/test_static_page*` finds nothing). The requirements ("must keep it green"), the plan, DEPLOYMENT.md:465's rat-tail and config.json:263 all name it.

**What depends on it.** The claim that the About URL mapping is guarded.

**Regression risk.** No regression, because the build changes no About URL or dev-pages name. But the claimed guard is absent.
- The plan's "stays green" wording must be dropped.
- The drift should be named in the delivery comment, plus a follow-up issue.
</impact>
<impact path="tests/tmp/test_21_static_page_visit_logs_phase1.py" element="TEMPLATE reads (lines 24, 130-131); same in phase2.py:23/162/175 and phase3.py:27/237">
**What changes.** Nothing.

**What depends on it.** These working files serve the template bytes through a real nginx.

**Regression risk.** None for the gate: they are not gating. Phase1:131 asserts only that the template's and the override's lengths differ, which the extra tag keeps true.
</impact>
<impact path="tests/active/test_profiles.py" element="users.db byte scan (line 103), deletion row counts (line 75)">
**What changes.** Nothing.

**What depends on it.** The contents of users.db.

**Regression risk.** None. The new table is empty in these tests and holds no key material.
</impact>
<impact path="tests/last_test_validation.json" element="per-group records">
**What changes.** The run regenerates it. Groups claiming `server.py` or `users_store.py` re-run, and the new test files appear as new groups.

**What depends on it.** The validator.

**Regression risk.** Low. Regenerate it; never hand-edit it.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="forbidden-pattern scan of client/frontend/src (lines 22-38)">
**What changes.** Nothing.

**What depends on it.** It scans the new module's source.

**Regression risk.** None, provided the module uses `resolveClientApiBase` and hardcodes no `127.0.0.1:707x` or `/internal/*` path.
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="Client route smoke checks (around lines 560-592)">
**What changes.** Nothing is planned. A 204 check would write a real row into the target users.db.

**What depends on it.** Nothing.

**Regression risk.** None.
</impact>
<impact path="DEPLOYMENT.md" element="Triage: new subsection \"Count About analytics events\" (between \"Follow an About visit\", 232-258, and \"Follow one request\", 260)">
**What changes.** A new subsection with:
- the `sqlite3 -readonly <root>/client/backend/db/users.db` invocation;
- fenced `sql` blocks for total and daily (UTC, `date(created_at / 1000, 'unixepoch')`) clicks per `track_id`, and total and daily `page_view`, optionally per `page_path`;
- the bot-filtered variants.

It also carries these caveats:
- Counts are forgeable at up to 90/min per address.
- Retention is unbounded.
- The UA filter is a heuristic.
- Referer is often reduced.
- Middle-click and context-menu opens are not counted, and non-http(s) tracked links are rejected.
- Undercount: a shared or misresolved client address caps everyone behind it at 90 beacons/min, and the 429s are invisible to the browser.
- `npm run dev` sendBeacon loss.
- A long `sqlite3` reader briefly blocks writers, because `connect_db` sets no WAL.

**What depends on it.** The counter test extracts its SQL from here. Line 116's §2 pointer could mention it.

**Regression risk.** Medium, through its coupling to the test: renaming the heading or changing the fences breaks the gate.
</impact>
<impact path="DEPLOYMENT.md" element="\"Follow an About visit\" recipe prose (line 241) and caveat (line 258)">
**What changes.**
- Rewrite line 258: the pageview beacon now exists, point to the new subsection, and change the issue path to `docs/project/issues/archive/18-about-outbound-click-tracking.md`.
- Line 241 says "The page's own API calls are new requests". On the template page there were none until now. Every view now produces its own `POST /api/analytics/event` `request.start` from the visitor's `ip` within seconds, plus one per tracked click.
- So the recipe (lines 242-250) now prints at least the beacon. Add one sentence. The line-254 caveat stays true, because the beacon does not carry the pages-log request id.

**What depends on it.** Readers of the runbook.

**Regression risk.** Low.
</impact>
<impact path="DEPLOYMENT.md" element="§5 route prose (lines 404-410)">
**What changes.** Lines 404-406 say "There is no browser-facing event publish route". Add that `POST /api/analytics/event` is browser-facing, needs no key, stores only Client-side rows and publishes nothing to the Engine. Line 410's list of keyed routes stays unchanged.

**What depends on it.** Readers of the boundary contract.

**Regression risk.** Low.
</impact>
<impact path="DEPLOYMENT.md" element="§1 users.db note (69-70), §2 pointer paragraph (116), §6 CSP and prose (459, 515, 519), rat-tail (465), X-Forwarded-For prose (523), Verify (533-541), CORS dev prose (620), §7 page list (627)">
**What changes.**
- **69-70:** optionally note that users.db now holds `analytics_events` and grows without pruning, which matters for backups.
- **116:** optionally add a pointer to the new subsection.
- **459/515/519:** no change. `connect-src 'self'` and `script-src 'self'` already cover the beacon and the bundled script. Note that 519 says About "carries no `<meta>` CSP", which stays true.
- **465:** cites the non-existent test. Flag it; do not silently fix it.
- **523:** "Omit the lines and every visitor shares one bucket" now also means a silent analytics undercount. Cross-reference it from the new caveats.
- **533-541 Verify:** optionally add a POST that answers 204, stating that it writes a real row.
- **620:** optionally add that `npm run dev` beacons are subject to the credentialed-sendBeacon loss, and that `npx vite` uses the same-origin `/api` proxy.

**What depends on it.** Operators.

**Regression risk.** Low.
</impact>
<impact path="client/README.md" element="lines 6 and 10 (scope wording), Backend Responsibilities list (11-23), Boundary Contract (41), TRUSTED_PROXIES (69), CLIENT_CORS_ORIGINS (71)">
**What changes.**
- Add a bullet for `POST /api/analytics/event` covering:
  - the two types and their fields;
  - 204/400/429;
  - Content-Type is ignored;
  - no key is needed;
  - rows go to users.db `analytics_events`;
  - nothing IP-derived is stored;
  - no Engine publish.
- Line 41's "write/profile" list gets the route, or a new "analytics" line.
- Lines 6 and 10 ("write/profile API service", "Owns user write/profile endpoints") are slightly narrower than the truth; optionally widen them.
- Line 71 could mention the dev beacon caveat.
- Line 69 ("keys the rate limiters") stays true.

**What depends on it.** Readers.

**Regression risk.** Low.
</impact>
<impact path="client/frontend/README.md" element="\"Local About Overrides\" (36-42), \"What it does\" (7-19), Boundary Contract (21-24)">
**What changes.**
- **Overrides section:** an override adds the same root-absolute `<script type="module" src="/src/...">` tag, plus `data-track-id="<[a-z0-9_]{1,64}>"` on each outbound link. Only http(s) links count, and middle-click and context-menu opens do not.
- **"What it does":** add a bullet for the About page's `page_view` and `outbound_click` beacons.
- **Line 24:** dev cross-origin beacons need `CLIENT_CORS_ORIGINS`, and `application/json` sendBeacons are lost under `npm run dev`. `npx vite` is same-origin through the `/api` proxy.

**What depends on it.** Operators who own the untracked override.

**Regression risk.** Low.
</impact>
<impact path="README.md" element="ownership table row (line 50)">
**What changes.** Line 50 lists the Client backend's browser-facing write routes. Add `/api/analytics/event` there, or add a row "About analytics events | Client backend". The plan omits this file, but the requirement "wherever ... lists the Client backend's public routes" covers it.

**What depends on it.** Readers.

**Regression risk.** Low.
</impact>
<impact path="CONTEXT.md" element="new **Analytics event** glossary entry (near **Interaction event**, line 6); **Client address** (line 9) unchanged">
**What changes.** One line in the `- **Term** — ...` style, saying that an Analytics event:
- has two types, `outbound_click` and `page_view`;
- belongs to the Client backend (users.db `analytics_events`), not the Engine;
- is anonymous, with nothing derived from the address stored;
- is distinct from an **Interaction event**, which feeds the Engine.

Line 9 ("keys every rate limiter") stays true.

**What depends on it.** The domain docs.

**Regression risk.** None.
</impact>
<impact path="docs/project/issues/18-about-outbound-click-tracking.md" element="Status (line 3), `## Comments`, file location">
**What changes.**
- Change `Status: enhancement, needs-triage` to `Status: enhancement, complete`.
- Add a delivery comment in the style of archive/21:31. It names the plan and states the departures from the issue text:
  - the route is `/api/analytics/event`, not `/api/analytics/outbound-click`;
  - the table is `analytics_events`;
  - validation is by shape, not an allowlist;
  - there is no `ip_hash`;
  - the change is to the template and override docs, not to `client/frontend/about.html` (which does not exist, see line 14).
  - It also names what was scoped out and the follow-ups: the shared connection and the missing static-page test.
- Move the file to `docs/project/issues/archive/` (issue-tracker.md:21).

**What depends on it.** DEPLOYMENT.md:258, plan.md:98 and plan 23 link to the current path.

**Regression risk.** Low. Update the links in the same change.
</impact>
<impact path="docs/project/issues/plan.md" element="P5 row (line 42) and lane 5c (line 98)">
**What changes.**
- **Line 42:** "19, 20 and 21 are delivered, and 18 remains" becomes all delivered.
- **Line 98:** mark 18 delivered and give the plan path.

**What depends on it.** The tracker.

**Regression risk.** None. The plan names only lane 5c, but line 42 needs the update too.
</impact>
<impact path="docs/project/issues/21-static-page-visit-logs.md" element="stale non-archive duplicate of delivered issue 21 (line 27 mentions 18)">
**What changes.** Nothing is planned. It sits alongside its `archive/` copy, left over from issue 21's delivery (the issue-20 duplicate `20-request-lifecycle-logs.md` is the same kind of leftover).

**What depends on it.** Tracker hygiene.

**Regression risk.** None. Mention it in the delivery notes.
</impact>
<impact path="docs/project/issues/archive/21-static-page-visit-logs.md" element="delivery comment (line 31)">
**What changes.** Nothing is required. It cites issue 18 by slug, not by path, so the move breaks nothing.

**What depends on it.** Nothing.

**Regression risk.** None.
</impact>
<impact path="docs/project/roadmap.md" element="line 157 (\"Logging: 19 -> 20 -> 21; 18 is orthogonal\")">
**What changes.** Nothing. The line stays true.

**What depends on it.** Nothing.

**Regression risk.** None.
</impact>
<impact path="docs/project/plans/23-18-about-outbound-click-tracking.md" element="the plan document">
**What changes.** The workflow renders it, so do not hand-edit it. Per issue-tracker.md:29, a delivered plan moves to `docs/project/plans/archive/`. If it moves, the links in plan.md:98 and in the issue 18 comment must follow.

**What depends on it.** Those links.

**Regression risk.** Low.
</impact>
<impact path="docs/project/adr/0004-cors-opt-in-by-origin.md" element="CORS opt-in decision">
**What changes.** Nothing. The build does not contradict it: no credentials and no `*`. The dev sendBeacon loss follows from it, so cite it in the docs that describe that loss.

**What depends on it.** Nothing new.

**Regression risk.** None.
</impact>
<impact path="docs/project/adr/0002-trusted-proxy-client-address.md" element="client address resolution">
**What changes.** Nothing. The analytics limiter keys on this address. A misconfiguration now also undercounts analytics silently.

**What depends on it.** Counting accuracy.

**Regression risk.** None from the code. Docs caveat only.
</impact>
<impact path="engine/server/README.md" element="line 19 (Engine does not own browser-facing write/profile routes)">
**What changes.** Optional. The Engine does not own `/api/analytics/event` either.

**What depends on it.** Nothing.

**Regression risk.** None.
</impact>
<impact path="docs/project/security-audit/run-2/architecture.md" element="endpoint inventory of a past audit run">
**What changes.** Nothing. It is a dated audit snapshot, not living documentation. The next audit run will pick up the new anonymous write route.

**What depends on it.** Nothing.

**Regression risk.** None.
</impact>


### docs_checklist


<doc path="DEPLOYMENT.md">
- **New Triage subsection "Count About analytics events"**, placed between "Follow an About visit" and "Follow one request". It holds:
  - the `sqlite3 -readonly` invocation;
  - `sql` blocks for total and daily (UTC) clicks per `track_id`, and total and daily `page_view`, optionally per `page_path`;
  - the bot-filter variants.
- **Its caveats:**
  - counts are forgeable within 90/min per address;
  - retention is unbounded;
  - the UA filter is a heuristic;
  - Referer is often reduced;
  - middle-click and context-menu opens are not counted;
  - non-http(s) links are rejected;
  - a shared or misresolved address silently undercounts;
  - `npm run dev` loses sendBeacon events;
  - a reader briefly blocks writers.
- **Line 241:** add a sentence that each About view now produces its own beacon `request.start`.
- **Line 258:** say the beacon exists, point to the new subsection, and change the issue path to `archive/`.
- **Lines 404-406:** the new route is browser-facing but publishes nothing to the Engine.
- **Optional:**
  - 69-70: users.db holds `analytics_events`;
  - 116: a pointer to the new subsection;
  - 523: a cross-reference to the undercount;
  - 620: the dev beacon caveat;
  - a Verify POST that notes it writes a row.
- **Line 465:** flag that it names the non-existent `tests/active/test_static_page_visit_logs.py`.
</doc>
<doc path="client/README.md">
- **Backend Responsibilities:** a new bullet for `POST /api/analytics/event`, covering:
  - the two types and their fields;
  - 204/400/429;
  - Content-Type is ignored;
  - no key is needed;
  - users.db `analytics_events`;
  - nothing IP-derived is stored;
  - no Engine publish.
- **Boundary Contract line 41:** add the route.
- **Optional:** widen lines 6 and 10, and add the dev beacon note at line 71.
</doc>
<doc path="client/frontend/README.md">
- **"Local About Overrides":** the module's root-absolute script tag and the `data-track-id` convention (`[a-z0-9_]{1,64}`). Only http(s) links count, and middle-click and context-menu opens do not.
- **"What it does":** add a bullet for the About beacons.
- **Line 24:** dev beacons need `CLIENT_CORS_ORIGINS`, `npm run dev` loses `application/json` sendBeacons, and `npx vite` is same-origin through the `/api` proxy.
</doc>
<doc path="README.md">
Line 50 ownership table: add `/api/analytics/event` to the Client backend's browser-facing routes, or add a row for it.
</doc>
<doc path="CONTEXT.md">
New **Analytics event** entry:
- its two types;
- it belongs to the Client backend (users.db), not the Engine;
- it is anonymous;
- it is distinct from an **Interaction event**.
</doc>
<doc path="docs/project/issues/18-about-outbound-click-tracking.md">
- Set `Status: enhancement, complete`.
- Add a delivery comment. It names the plan and the departures from the issue text: the route, the table, no allowlist, no ip_hash, and the template path. It also names the follow-ups: the shared-connection race and the missing static-page test with its config.json group.
- Move the file to `docs/project/issues/archive/`, and update the links to it in DEPLOYMENT.md and plan.md.
</doc>
<doc path="docs/project/issues/plan.md">
- Line 42 (P5 row): mark 18 delivered.
- Line 98 (lane 5c): mark 18 delivered and give the plan path.
</doc>
<doc path=".un/skills/devsecops/config.json">
- Add a `test_groups` entry for each new test file, mapping it to:
  - `server.py`
  - `users_store.py`
  - `http_utils.py`
  - the new frontend module
  - `api-base.ts`
  - `about.template.html`
  - `vite.config.ts`
  - `DEPLOYMENT.md`
- Note the existing `test_static_page_visit_logs.py` group: it points at a missing file.
</doc>


### highest_risk


client/backend/server.py `connect_db` and the shared `user_db` connection: one unlocked `sqlite3.Connection` serves every handler thread. The new route is the first anonymous write allowed 90/min per address, so its `with conn:` commit or rollback is much more likely to land in the middle of another thread's multi-statement profile transaction (`_store_reaction`, lines 974/991/999). That race is inherited; this route makes it far more likely to be hit.
client/backend/server.py new validator: any non-`str` field, `bool` or `float` timestamp, or lone-surrogate string that is not rejected up front escapes as an exception at `re`, `urlsplit` or the sqlite INSERT. The request then ends with no response instead of the required 400, and `request.end` logs status `-`.
.un/skills/devsecops/config.json together with tests/active (new test files): the new tests need their own `test_groups` entries or they will not be selected. The existing `test_static_page_visit_logs.py` group points at a file that does not exist, so the "keep the About mapping green" guard the plan relies on is absent. And the built-page vite test is the first in the suite to invoke vite, which needs an absolute `--outDir` with `--emptyOutDir` and must never touch the committed `dist/`.

## 2026-10-02 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: YES.

I checked the inventory against the files it names: `server.py` (imports, constants, `_serve_post`, `_rate_limit_check`, `_store_reaction`, `_handle_likes_import`, `_read_block_body`, `_parse_client_likes`, `main`), `http_utils.py` in full, `users_store.py`, `conftest.py`, `test_server.py` helpers, `test_frontend_profile.py`, `vite.config.ts`, `api-base.ts`, `about.template.html`, the data modules' URL construction, the `DEPLOYMENT.md` nginx block and §5 prose, `client/README.md`, root `README.md`, issue 18, `plan.md` and `config.json`. The inventory is accurate with one small slip: the CSP it quotes is shorter than the real one, and its conclusion still holds. The plan works in production as designed. There are two new impacts, both small and both fixable inside the plan without reopening anything: a deeply nested JSON body escapes as `RecursionError` rather than becoming the 400 the plan promises, and About page views are recorded under three different `page_path` values for the same page.
<question id="1">
Yes, in production. The route sits before the final 404 (`server.py:501`) and the bucket key is `<ip>:/api/analytics/event` (`server.py:516`). `read_json_body` never looks at Content-Type. `ensure_user_schema` runs at startup (`server.py:1311`), and nginx proxies `/api/` on the same origin with a CSP whose `connect-src 'self' https:` and `script-src 'self'` allow both the beacon and the bundled module. It falls short in three places. (a) A body nested past Python's recursion limit makes `json.loads` raise `RecursionError`, which `read_json_body` does not turn into a `ValueError`. The request then ends in `handle_error` with no response, breaking the plan's "all of these map to 400". (b) Under `npm run dev`, which uses a cross-origin base, the plan's "try/catch falls through to fetch" does not happen. `sendBeacon` returns `true` and its credentialed preflight then fails, so dev events are lost silently; the inventory already carries this. (c) The tracked template has no outbound links, so out of the box the build counts page views only. Click counts depend on an operator override that carries `data-track-id`, and that is the documented design.
</question>
<question id="2">
`users.db` gains the first anonymous, keyless write route. It is limited to 90 per minute per address and its retention is unbounded. That raises the odds of hitting the existing race on the shared unlocked connection with a cross-thread `with conn:` commit or rollback (inventory entry, confirmed: `connect_db` uses `check_same_thread=False` and `RateLimiter.lock` is the only lock). The About page goes from no JS to one module, and nginx keeps its CSP as it is. Every About view now writes one `request.start`/`request.end` pair for `POST /api/analytics/event` to the Client log, which changes what the "Follow an About visit" recipe prints. This is the first active test that runs vite. Page-view counts split across `/about`, `/about/` and `/about.html`, because all three are live About URLs (nginx at `DEPLOYMENT.md:467-484`, vite at `rewriteToAbout`, `vite.config.ts:22`) and `page_path` is `location.pathname`.
</question>
<question id="3">
For existing functionality, nothing beyond what the inventory lists. No existing route, schema, test or page behaviour depends on the new code: the route matches its exact path, `ensure_user_schema` gains only `IF NOT EXISTS` statements, and no active test counts the tables in `users.db`. The work that must still happen is the following. Add the new test groups to `.un/skills/devsecops/config.json`. Make the analytics handler turn every malformed-body failure into a 400, which includes catching `RecursionError`. Bring the docs in line: the `DEPLOYMENT.md` caveat at line 258 and the §5 sentence at line 404 ("There is no browser-facing event publish route"), `client/README.md` line 41, root `README.md` line 50, and issue 18's archive move together with `plan.md` lines 42 and 98. The repo `dist/` must not be written to, and production gets the beacon only after `scripts/sync.sh` runs.
</question>
<question id="4">
Existing routes, the profile flows and the Engine contract behave exactly as before. The About page now sends a `page_view` beacon on every load, and an `outbound_click` beacon for each tracked link in an override. `users.db` grows with every About visit. The runbook's statement that counting human visits needs a beacon that does not yet exist becomes false and is rewritten. The §5 statement that there is no browser-facing event route gets the qualification that this route publishes nothing to the Engine. `GET /api/analytics/event` and every other unknown path still answer 404. Profile deletion is unaffected because analytics rows carry no profile id.
</question>

New impacts:
client/backend/lib/http_utils.py — `read_json_body` (lines 86-95) only catches `json.JSONDecodeError`. A body under the 1 MB cap that is nested deeper than the interpreter's recursion limit (for example `{"a":[[[[…]]]]}` or a bare `[[[…`) makes `json.loads` raise `RecursionError`, which is not a `ValueError`. The plan's `try/except ValueError` therefore lets it escape to socketserver's `handle_error`: the client gets no response and `request.end` logs `-`. Every JSON POST route already has this problem, but this route is anonymous and its gating tests assert that every malformed body gets a 400. The fix belongs in the new handler, `except (ValueError, RecursionError)`, and the invalid-body test cases should include a deeply nested body.
DEPLOYMENT.md (new "Count About analytics events" SQL) and tests/active/test_analytics_events.py — About is served at three URLs: nginx `location = /about`, `= /about/` and `= /about.html` (`DEPLOYMENT.md:467-484`), and the vite `rewriteToAbout` set (`vite.config.ts:22`). `page_path = location.pathname` therefore records one page under three values. The documented "page_view grouped by page_path" query splits About counts three ways, and any query that filters on `page_path = '/about'` undercounts. The total page_view query must not filter on page_path. The per-page query needs a note, or should fold the three About paths together with a `CASE` expression. The counter test should post page_views under more than one About path, so a filtered query cannot pass.

Inventory entries that did not hold up:
client/frontend/dev-pages/about.template.html entry (and the DEPLOYMENT.md §6 entry for 459/515/519): it says "`connect-src 'self'` allows a same-origin beacon". The header at `DEPLOYMENT.md:459` is actually `connect-src 'self' https:`. Same-origin is still allowed, so the conclusion holds; only the quoted value is wrong.

Conflicts: none

Recommendations: 1. Catch `RecursionError` with `ValueError` in the analytics handler and add a deeply nested body to the 400 cases. Cost: one tuple in one `except` and one test case. Fixing it inside `read_json_body` would also repair every other POST route, but that is outside this build's scope and re-runs every group that claims `http_utils.py`, so record it as a follow-up issue rather than doing it here.
2. In the new DEPLOYMENT subsection, state that About page_views appear under `/about`, `/about/` and `/about.html`, and either give the per-page query a `CASE` that folds them together or say that totals must be summed across them. Have the counter test post under at least two of those paths. Cost: a few lines of SQL and prose, and one more posting loop in the test.
3. Take the inventory's corrections as implementation detail inside the settled plan, at no design cost. Build the URL with `new URL("/api/analytics/event", resolveClientApiBase())` inside the try, as the sibling modules do. Call `navigator.sendBeacon(...)` as a method. Use raw `urllib` for the text/plain, invalid-JSON, empty-body and header cases. Run the 91-post test on a server built with `RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)` through `test_server._client_backend`, because the `client_backend` fixture uses `RateLimiter(1000, 60)`. Stub `navigator` with `Object.defineProperty` before `import()`. Pass vite an absolute `--outDir` under `tests/tmp` plus `--emptyOutDir`.
4. Correct the plan's cross-origin-dev risk in the docs rather than in the code. Under `npm run dev`, `sendBeacon` returns `true` and the event is lost; the try/catch never sees it. `npx vite`, which goes through the same-origin `/api` proxy, works. Cost: two README/DEPLOYMENT sentences. A `text/plain` Blob would remove the loss, but it departs from the requirement's literal `application/json`, so only the operator can choose it, by reopening requirements.
5. Keep the settled module path `src/about-analytics.ts`. `src/pages/about/index.ts` would match the other page entries, but changing it means revisiting the settled plan for a cosmetic gain.
6. In the delivery comment and in follow-up issues, record the following. The shared-connection transaction race was made more likely by this build and is not fixed here. `tests/active/test_static_page_visit_logs.py` does not exist, although `config.json:263` and `DEPLOYMENT.md:465` cite it, so the requirement's "keep it green" is satisfied only vacuously. The stale non-archive copies of issues 20 and 21 remain. Cost: writing the tracker entries; no code.

## 2026-10-02 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impacts>
<impact path="client/backend/server.py" element="module imports (lines 5-41) and module constants (lines 46-73)">
**What changes.**
- `re` is not imported today (lines 5-23).
- `urllib.parse` imports only `parse_qs, urlencode, urlparse` (line 20), so the plan's `urlsplit` must be added there.
- `insert_analytics_event` joins the wrapped, alphabetised `from lib.users_store import (...)` block at lines 39-41, between `get_or_create_user` and `load_liked_keys`.
- New constants follow the style of `USER_ACTIONS = frozenset((...))` (line 62) and `BLOCK_REFERENCE_MAX_LENGTH = 200` (line 68): a two-value event-type frozenset, a `[a-z0-9_]{1,64}` pattern, a 2048 href cap and a 256 page_path cap.

**What depends on it.** `tests/active/conftest.py:43` imports the module as `client_server`, and `tests/active/test_server.py:161` re-imports from conftest. Every Client-backend test therefore loads it at collection time.

**Regression risk.** Low. An import or name error fails the whole active suite loudly at collection.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._serve_post (lines 437-501): new `/api/analytics/event` branch and its handler method">
**What changes.**
- A new `if url.path == "/api/analytics/event":` branch goes before the comment at 497-500 and the final 404 at 501.
- It is shaped like `/api/user-action` (464-469): `_rate_limit_check(url.path)`, then 429 `{"error": "Rate limit exceeded"}`, then a `_handle_analytics_event()` method.
- That method reads the body with `try: read_json_body(self) except ValueError as exc: respond_json(self, 400, {"error": str(exc)})`, the exact idiom at 1014-1018 and 1050-1054. It then validates, writes with `with self.server.user_db: insert_analytics_event(...)` (the idiom at 410 and 1119), and answers `respond_bytes(self, 204, b"")` like `/api/profile/delete` (line 462).

**What depends on it.**
- `do_POST` → `_run_request` (377-379, 339-357) gives `request.start`/`request.end` with no extra code. `request.start` already logs `ip` and `user_agent`, but that is a log, not storage.
- `_serve_get` (381-435) is untouched, so `GET /api/analytics/event` falls to the 404 at 435.
- `do_OPTIONS` (369-371) answers `respond_options` for any path, so a CORS preflight to the new path already gets 204.
- In prod, nginx's `location /api/` (DEPLOYMENT.md:486-493) already proxies the path to 7072, so no nginx change is needed.

**Regression risk.** Low for existing routes, since the match is on the exact path.
- A branch placed after line 501 never runs.
- The limiter key is `<ip>:/api/analytics/event` (`_rate_limit_check`, 514-517), so analytics has its own 90/min bucket and does not drain `/api/user-action`'s.
- A 429 or a validation 400 leaves part of the body unread. That is harmless only because nothing in `client/backend` sets `protocol_version` or `close_connection` (I grepped), so each connection is HTTP/1.0 and closes.
- No socket timeout is set, so a `Content-Length` larger than the bytes actually sent blocks a thread in `rfile.read`. Every POST route already has this, but this route is anonymous and hit on every About view.
- `str(exc)` for a `UnicodeDecodeError` is a long codec message rather than "Invalid JSON body". It is still a 400, but tests should assert the status, not the text.
</impact>
<impact path="client/backend/server.py" element="new module-level validator (e.g. `_validate_analytics_event(body)`), near `_parse_client_likes` (lines 1236-1252)">
**What changes.** A new pure function that returns the row values or an error string, in the sibling style: a `_` prefix and a `"""Handle ...`/`:returns:` docstring.

**What depends on it.** The route handler, and the backend tests, which can call it directly as `client_server._validate_...`.

**Regression risk.** Medium. An exception that escapes the validator does not become a 400. It goes to socketserver's `handle_error`, the client gets no response, and `request.end` logs status `-`. The cases:
- **Type checks first.** `re.fullmatch` on an int raises `TypeError`, and `len`, `.startswith` and `urlsplit` also fail on non-strings. Check `isinstance(..., str)` before each.
- **`bool` is an `int`.** `timestamp: true` must be rejected. `1.0` arrives as a `float` from `json.loads` and must be rejected too.
- **Lone surrogates.** `json.loads('"\ud800"')` gives a `str` that sqlite3 cannot bind (`UnicodeEncodeError` at INSERT, after validation). `href` and `page_path` therefore need an encodability check. `track_id` is safe because of its regex.
- **`urlsplit` details.**
  - `"https://"` gives `hostname=None`, which must be rejected.
  - `"http://[::1"` raises `ValueError`, which must be caught.
  - `.hostname` itself can raise on a malformed bracketed netloc, so the catch must cover the attribute read as well as the call.
  - The scheme comes back lowercased, so `HTTPS://` passes.
- **Null handling.** An explicit `null` `track_id` or `href` is accepted on `page_view` and rejected on `outbound_click`.
- **`page_path`.** `//host` passes the leading-slash rule. That is acceptable because the value is stored, never followed.
</impact>
<impact path="client/backend/server.py" element="User-Agent / Referer capture in the new handler, and `_get_client_ip` (lines 326-329)">
**What changes.** The handler reads `self.headers.get("User-Agent")` and `self.headers.get("Referer")`, strips each, and stores `None` when the result is empty. That is the same idiom as `_run_request` at 347-349. `_get_client_ip` is reached only through `_rate_limit_check`.

**What depends on it.** The "nothing IP-derived stored" requirement and the `PRAGMA table_info` test.

**Regression risk.** Low.
- nginx sets `X-Real-IP` and `X-Forwarded-For` on `/api/` (DEPLOYMENT.md:489-490), and neither may reach the row.
- Headers are stored up to http.server's 64 KiB line cap, which the plan accepts. http.server decodes headers as latin-1, so they always bind in sqlite.
</impact>
<impact path="client/backend/server.py" element="connect_db (lines 230-234) and the single shared `user_db` connection used by every handler thread">
**What changes.** No code change. The new route adds writes on this connection.

**What depends on it.** Every profile write: `_store_reaction`'s `with conn:` blocks (974, 991, 999), the likes import (1027), reset and blocks (1119, 1135), `lib/blocks.py:56,80` and `lib/profiles.py:74`.

**Regression risk.** Medium, and the plan understates it as "serialises briefly".
- There is one `sqlite3.Connection` (`check_same_thread=False`) shared by all `ThreadingHTTPServer` threads, with no lock. I grepped: the only lock is `RateLimiter.lock`.
- `with conn:` commits or rolls back the connection's single open transaction. A beacon commit on one thread can commit another thread's half-done multi-statement write, and a rollback elsewhere can drop a beacon insert.
- The race exists today. This is the first anonymous write route allowed 90/min per address on every About view, so it is hit far more often.
- Name it as an inherited limitation and open a follow-up issue (a write lock or per-thread connections). The plan does not fix it.
</impact>
<impact path="client/backend/server.py" element="main(): `ensure_user_schema(user_db)` (line 1311)">
**What changes.** No edit. Existing databases get the table and index on the next restart.

**What depends on it.** Prod and dev upgrades. There is no migration step, consistent with DEPLOYMENT.md:408.

**Regression risk.** Low.
</impact>
<impact path="client/backend/lib/users_store.py" element="ensure_user_schema (lines 10-71): docstring and script">
**What changes.**
- Add `CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK (type IN ('outbound_click','page_view')), track_id TEXT, href TEXT, page_path TEXT NOT NULL, created_at INTEGER NOT NULL, user_agent TEXT, referer TEXT)`.
- Add `CREATE INDEX IF NOT EXISTS <name>_idx ON analytics_events (type, track_id, created_at)`, named like `likes_user_updated_idx` (line 27).
- Both go before the `local-user` cleanup DELETEs (67-69).
- The docstring on line 11 enumerates the tables the function creates, so it must gain the analytics events table.

**What depends on it.** `server.py:1311`, `tests/active/conftest.py:77` and `:169`, and `tests/active/test_server.py:398`, `:834` and `:997`.

**Regression risk.** Low. No active test enumerates users.db tables: the `sqlite_master`/`table_info` hits are in Engine-DB tests. `test_profiles.py:103` byte-scans `users.db*` for key material, and an empty new table adds none.
</impact>
<impact path="client/backend/lib/users_store.py" element="new insert_analytics_event(conn, ...)">
**What changes.** A new function that runs one parameterised INSERT. It must not call `conn.commit()`, because the handler's `with self.server.user_db:` owns the transaction.

The module is inconsistent on this point. `get_or_create_user`, `record_like` and `clear_likes` commit internally, while `remove_like` and `close_like` say "inside the caller's transaction" (lines 192, 216). Follow the latter, docstring phrase included.

**What depends on it.** The route, and the counter test that reads the rows back.

**Regression risk.** Low. `created_at` must come from the handler's single `now_ms()` (lib/time_utils), so that the test's before/after window holds.
</impact>
<impact path="client/backend/lib/http_utils.py" element="read_json_body (lines 78-95)">
**What changes.** Nothing. I confirmed by reading it that the plan's assumptions hold:
- Content-Type is never read, so `text/plain` is accepted.
- `int()` on a non-numeric length raises `ValueError`.
- A length over 1,000,000 raises `ValueError`.
- `.decode("utf-8")` raises `UnicodeDecodeError`, which is a `ValueError`.
- A non-dict body raises `ValueError`.
- A length of 0 or less, a missing length, or a whitespace-only body returns `{}`.

**What depends on it.** Every JSON POST route.

**Regression risk.** None, provided it is not edited.
</impact>
<impact path="client/backend/lib/http_utils.py" element="_send_cors_headers / respond_options / ALLOWED_REQUEST_HEADERS (lines 12-44, 71-75)">
**What changes.** Nothing.

**What depends on it.** Cross-origin dev beacons, and `respond_bytes`' CORS headers on the 204.

**Regression risk.** No backend regression. There is a frontend consequence the plan's cross-origin note understates:
- No `Access-Control-Allow-Credentials` is ever sent.
- `navigator.sendBeacon` uses credentials mode `include`, and an `application/json` Blob is not CORS-safelisted, so cross-origin it is preflighted, and a credentialed preflight without Allow-Credentials fails.
- Whether a browser then throws, which reaches the fetch fallback, or returns `true` and drops the event silently varies. I could not verify this from the tree. Treat dev cross-origin beacon loss as possible.
- Prod is same-origin and unaffected.
</impact>
<impact path="client/backend/lib/http_utils.py" element="RateLimiter (lines 98-124)">
**What changes.** Nothing.

**What depends on it.** The new 429, and the forgeability ceiling.

**Regression risk.** Low.
- Buckets are never evicted, so each distinct address adds a deque until restart. This route grows the map faster than the others.
- `max_requests <= 0` disables limiting.
- A 429 is invisible to `sendBeacon`, so behind a shared or misresolved address, counts silently cap at 90/min.
</impact>
<impact path="client/backend/lib/profiles.py" element="delete_profile">
**What changes.** Nothing. Analytics rows carry no profile id, so profile deletion neither touches them nor needs to. client/README.md:13 ("everything keyed to it") stays true.

**What depends on it.** Nothing new.

**Regression risk.** None.
</impact>
<impact path="client/frontend/src/about-analytics.ts" element="new module (whole file)">
**What changes.** A new module that imports `resolveClientApiBase` from `./data/api-base`. On import it sends one `page_view` and installs one delegated `document` click listener. A `send` helper tries `navigator.sendBeacon(url, Blob)` and falls back to `fetch(url, {method: "POST", keepalive: true, ...})` with a no-op `.catch`.

**What depends on it.** Five things must all name the same path:
- the template's script tag;
- the README override instructions;
- the node test;
- the built-page test;
- the new config.json test group.

**Regression risk.** Medium, because every failure is silent by design.
- **URL construction.** Every sibling builds URLs as `new URL("/api/...", base)` (user-actions.ts:20, reactions.ts:34/68, blocks.ts:57, profile.ts:88, user-profile.ts:23/43/61). None concatenates, and plain concatenation produces `//api/...` when `VITE_CLIENT_API_BASE` ends in `/`. Use `new URL`, inside the try, since it throws on a bad base.
- **Placement.** The page entries live at `src/pages/<page>/index.ts` (channels, likes, search, video-page, videos). The plan's `src/about-analytics.ts` at the src root departs from that convention. Either is workable, but decide it at design.
- **`sendBeacon` binding.** It must be called as `navigator.sendBeacon(...)`. A detached reference throws "Illegal invocation", the catch swallows it, and every event goes through fetch.
- **`event.target`.** It can be a Text or non-Element node with no `closest`.
- **SVG links.** An SVG `<a>`'s `.href` is an `SVGAnimatedString`, so read `getAttribute`/`href` defensively or accept a 400.
- **Module script.** A module script is deferred, so no DOMContentLoaded wait is needed.
- **Import-time read.** api-base.ts:5 reads `window.location.origin` at import.
- **`fetch` failures.** `fetch` can throw synchronously (a keepalive body over 64 KiB) as well as reject, so it needs both the try and the `.catch`.
- **No type gate.** The build script is plain `vite build` (package.json:9), so TS type errors do not fail the build.
- **Gateway scan.** `tests/check-frontend-client-gateway.sh` scans `src`. It passes provided no Engine base, `127.0.0.1:707x` or `/internal/*` literal appears.
</impact>
<impact path="client/frontend/src/data/api-base.ts" element="resolveClientApiBase (lines 18-33), DEFAULT_CLIENT_API_BASE (line 5)">
**What changes.** Nothing. The new module calls it with no argument, so `?api=` is never read and prod returns `window.location.origin`.

**What depends on it.** Every data module and the new one.

**Regression risk.** Low.
- Line 5 runs at import, so the node test must define `globalThis.window.location.origin` before `await import(bundle)`, as test_frontend_profile.py:30 does.
- `normalizeApiBase` keeps a trailing slash. This is harmless with `new URL`.
- Bundling it into the About entry may move it into a shared chunk and change other pages' asset hashes. That is harmless.
</impact>
<impact path="client/frontend/dev-pages/about.template.html" element="new `<script type=\"module\" src=\"/src/about-analytics.ts\">` tag">
**What changes.** One line. It is root-absolute like the `/src/videos.css` link on line 8, as client/frontend/README.md:41 requires. Today the template has no script at all, so it becomes the About page's first JS.

**What depends on it.**
- `vite.config.ts` uses it as the `about` input when no override exists, which is the case in this worktree: Glob finds only the template.
- nginx serves the built copy from `dev-pages/` (DEPLOYMENT.md:467-483, 519).
- `.un/skills/devsecops/config.json:263-268` maps it to a test that does not exist.
- `tests/tmp/test_21_static_page_visit_logs_phase{1,2,3}.py` read the template bytes into nginx. They are non-gating.

**Regression risk.** Low.
- The server CSP (DEPLOYMENT.md:459) has `script-src 'self'` and `connect-src 'self' https:`, which allow the bundled `/assets/*.js` and a same-origin beacon. An inline script would be blocked.
- The template's text (line 30) tells operators to replace it with an override, so the override docs carry the real instruction burden.
</impact>
<impact path="client/frontend/vite.config.ts" element="aboutSourcePath (16-18), build.rollupOptions.input.about (91-93), server.proxy['/api'] (27-32)">
**What changes.** Nothing.

**What depends on it.** The built-page test, and dev beacons.

**Regression risk.** Medium for test design.
- **Override switch.** `existsSync(devAboutPath)` switches the input to an untracked override (`.gitignore:29-30`). The plan skips the test in that case.
- **Output location.** The built page lands at `<outDir>/dev-pages/about.template.html`. The `/api/analytics/event` literal sits in the About entry chunk, while api-base may land in a shared chunk. The assertion must follow the page's `<script src>`, not assume a single file.
- **Output directory.**
  - `tests/tmp` is not gitignored (I grepped `.gitignore`), so `--outDir tests/tmp/...` leaves untracked build output in the tree. Prefer pytest's `tmp_path`, passed as an absolute path.
  - An outDir outside the root needs `--emptyOutDir` or a fresh directory.
  - Never write into the committed `client/frontend/dist/`.
- **First vite test.** No active test runs vite today. Eight tests run `node_modules/.bin/esbuild`. `vite` is a devDependency (package.json:18). `node_modules` is outside the sandbox, so I could not confirm `.bin/vite` exists.
- **Dev proxy.** `server.proxy['/api']` makes plain `npx vite` same-origin.
</impact>
<impact path="client/frontend/scripts/dev.mjs" element="VITE_CLIENT_API_BASE default (lines 15, 46, 104)">
**What changes.** Nothing.

**What depends on it.** `npm run dev` always sets a cross-origin base (`http://127.0.0.1:7172`), so dev beacons need `CLIENT_CORS_ORIGINS` and are subject to the credentialed-sendBeacon uncertainty above.

**Regression risk.** Dev-only event loss, not a regression. Document it.
</impact>
<impact path="client/frontend/dist/dev-pages/about.template.html" element="committed build output (and dist/assets)">
**What changes.** Not in the plan. Today it holds only the CSS link (line 8) and no script, and it lags the source until a rebuild.

**What depends on it.** Prod gets the beacon only after `scripts/sync.sh` runs `npm run build` (sync.sh:19).

**Regression risk.** Low. State in the delivery comment that prod sends nothing until the next sync. The built-page test must not write here.
</impact>
<impact path="scripts/sync.sh" element="build-then-rsync (line 19 onward)">
**What changes.** Nothing.

**What depends on it.** It is the only path by which the beacon reaches prod.

**Regression risk.** None.
</impact>
<impact path="tests/active/conftest.py" element="client_backend fixture (73-93) and ClientBackend.request (55-70)">
**What changes.** Nothing, unless a helper is added.

**What depends on it.** The new backend tests.

**Regression risk.** Medium for test design.
- The fixture uses `RateLimiter(1000, 60)` (line 84), so the plan's "91 posts → 429" test cannot run on it. It needs its own server with `RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS)`.
- `ClientBackend.request` always sets `content-type: application/json` and JSON-encodes the body. The `text/plain`, invalid-JSON, non-UTF-8, empty-body and custom UA/Referer cases need raw `urllib.request`.
- A 204's empty body comes back as `None`, which is fine.
</impact>
<impact path="tests/active/test_server.py" element="_serving (383-391), _client_backend(tmp_path, engine_base, rate_limiter) (394-403), _status (406-414), test_route_limiter_buckets_by_last_hop (417)">
**What changes.** Nothing, unless the new tests live here or copy these helpers.

**What depends on it.** It is the precedent for the rate-limit test: `_client_backend(..., RateLimiter(...))` builds a server with a chosen limiter. The peer 127.0.0.1 is a trusted proxy by default, so `X-Forwarded-For` can model a fresh address per test.

**Regression risk.** Low. No existing test enumerates POST routes or uses the new path.
</impact>
<impact path="tests/active/test_frontend_profile.py" element="esbuild-in-node pattern (ESBUILD line 21, RUNNER 23-43, _bundle 46-62)">
**What changes.** Nothing. It is the template for the node test. The `--define:import.meta.env.VITE_CLIENT_API_BASE=...` and `--define:import.meta.env.DEV=false` flags (56-57) are required, or `import.meta.env` is undefined in node.

**What depends on it.** The new frontend test. `test_frontend_video_page.py:105,117,133` and `test_frontend_videos_page.py:57,65,80` are the precedents for `globalThis.document`/`fetch` stubs and `unhandledRejection` capture.

**Regression risk.** For the new test:
- No active test stubs `navigator`. On Node 21 and later `globalThis.navigator` is a getter, so plain assignment may not take. Use `Object.defineProperty(globalThis, "navigator", {value, configurable: true})`.
- Every stub, `window` and `location` included, must be installed before `import()`, because the module acts at import.
- The Blob payload is read with `await blob.text()`.
- `document.addEventListener` must capture the handler so the test can dispatch synthetic events with a `target.closest` stub.
</impact>
<impact path="tests/active/test_analytics_events.py" element="new gating test file(s) (name for the design step)">
**What changes.** New tests covering the backend endpoint, the counter that runs SQL taken from DEPLOYMENT.md, the node frontend test and the vite built-page test.

**What depends on it.** The suite gate, and new config.json groups.

**Regression risk.** Medium.
- **SQL extraction.** Pin the subsection heading and assert the expected number of `sql` blocks, so an empty extraction cannot pass vacuously.
- **Timestamps.** Bound `created_at` by `now_ms()` taken before and after the request.
- **Columns.** Assert the exact `PRAGMA table_info(analytics_events)` column list, not just the absence of an IP column.
- **Build output.** Run the vite build in `tmp_path` with a generous timeout. Skip with a reason only when `dev-pages/about.html` exists.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (lines 14-269)">
**What changes.** A new `test_groups` entry for each new test file. It maps the file to:
- `client/backend/server.py`
- `client/backend/lib/users_store.py`
- `client/backend/lib/http_utils.py`
- the new frontend module
- `client/frontend/src/data/api-base.ts`
- `client/frontend/dev-pages/about.template.html`
- `client/frontend/vite.config.ts`
- `DEPLOYMENT.md`, for the SQL extraction

**What depends on it.** The validator that selects re-runs. These existing groups claim server.py and/or users_store.py and will re-run:
- `test_profiles`
- `test_dislikes`
- `test_frontend_profile`
- `test_server`
- `test_blocks`
- `test_frontend_blocks`
- `test_frontend_reactions`
- `test_frontend_upnext_pager`

**Regression risk.** Medium. Without a group, the new tests are not selected when these files change.

Lines 263-268 are pre-existing drift. They map `test_static_page_visit_logs.py`, which does not exist, onto `DEPLOYMENT.md`, `vite.config.ts`, `about.template.html` and `server.py`, all four of which this build edits.
</impact>
<impact path="tests/active/test_static_page_visit_logs.py" element="(does not exist)">
**What changes.** Nothing. Glob for `**/test_static_page_visit_logs*` finds no file. Issue 21's plan said the test step would write it; it was never written.

**What depends on it.** Four places claim it as a guard:
- the plan ("stays green");
- DEPLOYMENT.md:465's rat-tail comment;
- config.json:263;
- issue 21's delivery.

**Regression risk.** No regression, since no About URL or dev-pages name changes, but the claimed guard is absent. Drop the "stays green" wording, name the gap in the delivery comment, and open a follow-up issue.
</impact>
<impact path="tests/tmp/test_21_static_page_visit_logs_phase1.py" element="template reads (phase1/2/3 working files)">
**What changes.** Nothing.

**What depends on it.** These working files serve the template bytes through a real nginx.

**Regression risk.** None for the gate: they are not gating. The extra tag lengthens the template, which keeps any template-versus-override length difference true.
</impact>
<impact path="tests/active/test_profiles.py" element="users.db byte scan (line 103)">
**What changes.** Nothing.

**What depends on it.** The users.db contents.

**Regression risk.** None. The new table holds no key material.
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="Client route smoke checks (lines 548-617)">
**What changes.** Nothing is planned. A 204 check here would write a real row into the target users.db.

**What depends on it.** Nothing.

**Regression risk.** None.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="forbidden-pattern scan of client/frontend/src (lines 22-38)">
**What changes.** Nothing.

**What depends on it.** It will scan the new module.

**Regression risk.** None, provided the module routes through `resolveClientApiBase` and hardcodes no Engine host or internal route.
</impact>
<impact path="tests/last_test_validation.json" element="per-group records">
**What changes.** The run regenerates it. Never hand-edit it.

**What depends on it.** The validator.

**Regression risk.** Low.
</impact>
<impact path="DEPLOYMENT.md" element="Triage: new subsection \"Count About analytics events\" between \"Follow an About visit\" (232-258) and \"Follow one request\" (260)">
**What changes.** A new subsection with:
- the `sqlite3 -readonly <root>/client/backend/db/users.db` invocation;
- fenced `sql` blocks: total clicks per `track_id`, daily clicks per `track_id` in UTC, total and daily `page_view` (optionally per `page_path`), and the bot-filtered variants.

Its caveats:
- counts are forgeable at 90/min per address;
- retention is unbounded;
- the UA filter is a heuristic;
- Referer is often reduced;
- middle-click and context-menu opens are not counted;
- non-http(s) tracked links are rejected;
- a shared or misresolved address silently undercounts;
- dev cross-origin beacons may be lost;
- the shared-connection limitation, if it is documented here.

**What depends on it.** The counter test extracts its SQL from here.

**Regression risk.** Medium, through that coupling. Renaming the heading or changing a fence breaks the gate.
</impact>
<impact path="DEPLOYMENT.md" element="\"Follow an About visit\": recipe prose (line 241) and caveat (line 258)">
**What changes.**
- **Line 258.** Say the pageview beacon exists, point to the new subsection, and change the path to `docs/project/issues/archive/18-about-outbound-click-tracking.md`.
- **Line 241.** It says "The page's own API calls are new requests". Until now the template page made none. Every view now produces a `POST /api/analytics/event` `request.start` from the visitor's `ip`, plus one per tracked click, so the 242-250 recipe always prints at least the beacon. Add one sentence.
- **Line 254.** The caveat stays true, because the beacon does not carry the pages-log request id.

**What depends on it.** Runbook readers.

**Regression risk.** Low.
</impact>
<impact path="DEPLOYMENT.md" element="§5 route prose (lines 404-410)">
**What changes.** Lines 404-406 say "There is no browser-facing event publish route". Clarify that `POST /api/analytics/event` is browser-facing and keyless, stores Client-side rows in users.db, and publishes nothing to the Engine. The keyed-route list on line 410 is unchanged.

**What depends on it.** Readers of the boundary contract.

**Regression risk.** Low. The line 408 phrasing "creates at startup, so there is no migration step" also covers the new table.
</impact>
<impact path="DEPLOYMENT.md" element="§1 users.db list (70), §6 CSP (459) and prose (515, 519), rat-tail (465), X-Forwarded-For prose (523), Verify (533-541), Triage CORS row (209)">
**What changes.**
- **70.** Optionally note that users.db now holds `analytics_events`, which grows without pruning and matters for backups.
- **459, 515, 519.** No change. `script-src 'self'` and `connect-src 'self' https:` already cover the bundle and the beacon, and 519's "template carries no `<meta>` CSP" stays true.
- **465.** It cites the non-existent test. Flag it; do not silently rewrite it.
- **523.** "Omit the lines and every visitor shares one bucket" now also means a silent analytics undercount. Cross-reference it.
- **533-541.** Optionally add a POST check, noting that it writes a real row.
- **209.** The dev CORS row also covers dev beacons.

**What depends on it.** Operators.

**Regression risk.** Low.
</impact>
<impact path="client/README.md" element="Backend Responsibilities (10-23), Boundary Contract (41), scope wording (6, 10), CLIENT_CORS_ORIGINS (71)">
**What changes.**
- **New bullet** for `POST /api/analytics/event`, covering:
  - the two types and their fields;
  - 204/400/429;
  - Content-Type ignored;
  - no key needed;
  - rows in users.db `analytics_events`;
  - nothing IP-derived stored;
  - no Engine publish.
- **Line 41.** The "write/profile" list gets the route, or an "analytics" line is added.
- **Lines 6 and 10.** "write/profile API service" is now slightly narrow; optionally widen it.
- **Line 71.** Optionally add the dev beacon note.
- **Lines 13 and 69.** Both stay true.

**What depends on it.** Readers.

**Regression risk.** Low.
</impact>
<impact path="client/frontend/README.md" element="\"Local About Overrides\" (36-42), \"What it does\" (7-19), Boundary Contract (24)">
**What changes.**
- **Overrides.** Add the module's root-absolute `<script type="module" src="/src/...">` tag and `data-track-id="<[a-z0-9_]{1,64}>"` on each outbound link. Only http(s) links count, and middle-click and context-menu opens are not counted. An override without the tag sends nothing.
- **"What it does".** Add a bullet for the About `page_view`/`outbound_click` beacons.
- **Line 24.** Under `npm run dev`, beacons are cross-origin and need `CLIENT_CORS_ORIGINS`, and may be lost.

**What depends on it.** Owners of the untracked override.

**Regression risk.** Low.
</impact>
<impact path="README.md" element="boundary table row (line 50)">
**What changes.** Line 50 lists the Client backend's browser-facing write/profile routes. Add `/api/analytics/event`, or a new row for it. The plan omits this file, but the requirement "wherever ... lists the Client backend's public routes" covers it.

**What depends on it.** Readers.

**Regression risk.** Low.
</impact>
<impact path="engine/server/README.md" element="lines 4 and 19 (Engine does not own browser-facing write/profile routes)">
**What changes.** Optional. The Engine does not own `/api/analytics/event` either. Both lines stay true without an edit.

**What depends on it.** Nothing.

**Regression risk.** None.
</impact>
<impact path="CONTEXT.md" element="new **Analytics event** entry, near **Interaction event** (line 6); **Client address** (line 9) unchanged">
**What changes.** One line in the `- **Term** — ...` style. An analytics event:
- has the types `outbound_click` and `page_view`;
- is owned by the Client backend (users.db `analytics_events`) and never sent to the Engine;
- is anonymous, with nothing derived from the address stored;
- is distinct from an **Interaction event**.

Line 9 ("keys every rate limiter") stays true.

**What depends on it.** Domain docs.

**Regression risk.** None.
</impact>
<impact path="docs/project/issues/18-about-outbound-click-tracking.md" element="Status (line 3), `## Comments`, file location">
**What changes.**
- Set `Status: enhancement, complete`.
- Append a delivery comment in the style of archive/21:31. It names the plan and the departures from the issue text:
  - the route is `/api/analytics/event`, not `/outbound-click`;
  - the table is `analytics_events`, not `outbound_click_events`;
  - validation is by shape, not an allowlist (line 15);
  - there is no `ip_hash` (line 16);
  - the template and the override docs changed, not `client/frontend/about.html` (line 14), which does not exist.
- The comment also names the follow-ups: the shared-connection race and the missing static-page test.
- Move the file to `docs/project/issues/archive/` (issue-tracker.md:21).

**What depends on it.** Links to the current path at DEPLOYMENT.md:258 and in plan 23.

**Regression risk.** Low. Update those links in the same change. Slug-only references (archive/21:27,31, plan 22) need no change.
</impact>
<impact path="docs/project/issues/plan.md" element="P5 row (line 42), lane 5c (line 98)">
**What changes.**
- **Line 42.** "19, 20 and 21 are delivered, and 18 remains" becomes all four delivered.
- **Line 98.** Mark 18 delivered, with the plan path.

**What depends on it.** The tracker.

**Regression risk.** None. The plan names only lane 5c, but line 42 needs the change too.
</impact>
<impact path="docs/project/issues/21-static-page-visit-logs.md" element="stale non-archive duplicate of delivered issue 21">
**What changes.** Nothing is planned. It sits beside its `archive/` copy: issue 21's delivery recorded that it could not delete it. Its line 27 mentions 18 by slug only.

**What depends on it.** Tracker hygiene.

**Regression risk.** None. Mention it in the delivery notes.
</impact>
<impact path="docs/project/plans/23-18-about-outbound-click-tracking.md" element="the plan document">
**What changes.** The workflow renders it, so do not hand-edit it. Per issue-tracker.md:29, a delivered plan moves to `docs/project/plans/archive/`, and links from plan.md:98 and the issue-18 comment must follow if it moves.

**What depends on it.** Those links.

**Regression risk.** Low.
</impact>
<impact path="docs/project/adr/0004-cors-opt-in-by-origin.md" element="CORS opt-in decision">
**What changes.** Nothing. The build sends no credentials header and no `*`. The dev beacon caveat follows from this ADR, so cite it there.

**What depends on it.** Nothing new.

**Regression risk.** None.
</impact>
<impact path="docs/project/adr/0002-trusted-proxy-client-address.md" element="client address resolution">
**What changes.** Nothing. The analytics limiter keys on this address, so a misconfiguration now also undercounts analytics silently.

**What depends on it.** Counting accuracy.

**Regression risk.** None from the code. It needs a docs caveat only.
</impact>
</impacts>

### docs_checklist

<doc path="DEPLOYMENT.md">
- **New Triage subsection "Count About analytics events"**, between "Follow an About visit" and "Follow one request". It holds:
  - the `sqlite3 -readonly` invocation;
  - fenced `sql` blocks for total and daily (UTC) clicks per `track_id`, total and daily `page_view` (optionally per `page_path`), and the bot-filter variants;
  - its caveats: forgeable within 90/min per address, unbounded retention, a heuristic UA filter, reduced Referer, middle-click and context-menu not counted, non-http(s) links rejected, a shared or misresolved address undercounts, and dev cross-origin beacons may be lost.
- **Line 241.** One sentence: each About view now produces its own beacon `request.start`.
- **Line 258.** The beacon exists; point to the new subsection and change the issue path to `archive/`.
- **Lines 404-406.** The new keyless browser-facing route, which publishes nothing to the Engine.
- **Optional.**
  - 70: users.db holds `analytics_events` and grows unpruned;
  - 523: cross-reference to the undercount;
  - Verify: a POST that writes a row.
- **Line 465.** Flag that it names the non-existent `tests/active/test_static_page_visit_logs.py`.
</doc>
<doc path="client/README.md">
- **Backend Responsibilities.** A new bullet for `POST /api/analytics/event`, covering:
  - the two types and their fields;
  - 204/400/429;
  - Content-Type ignored;
  - no key needed;
  - users.db `analytics_events`;
  - nothing IP-derived stored;
  - no Engine publish.
- **Boundary Contract, line 41.** Add the route.
- **Optional.** Widen lines 6 and 10, and add a dev beacon note at line 71.
</doc>
<doc path="client/frontend/README.md">
- **"Local About Overrides".**
  - the module's root-absolute script tag;
  - the `data-track-id` convention (`[a-z0-9_]{1,64}`);
  - only http(s) links count, and middle-click and context-menu opens do not;
  - an override without the tag sends nothing.
- **"What it does".** A bullet for the About beacons.
- **Line 24.** Under `npm run dev`, beacons are cross-origin, need `CLIENT_CORS_ORIGINS`, and may be lost.
</doc>
<doc path="README.md">
Line 50 boundary table: add `/api/analytics/event` to the Client backend's browser-facing routes, or add a row for it.
</doc>
<doc path="CONTEXT.md">
A new **Analytics event** entry:
- the two types;
- owned by the Client backend in users.db, never sent to the Engine;
- anonymous;
- distinct from an **Interaction event**.
</doc>
<doc path="docs/project/issues/18-about-outbound-click-tracking.md">
- Set `Status: enhancement, complete`.
- Add a delivery comment that names the plan and the departures from the issue text: the route, the table, no allowlist, no ip_hash, and the template plus override docs rather than `about.html`.
- Name the follow-ups: the shared-connection race and the missing static-page test with its config.json group.
- Note that prod gets the beacon only after the next `scripts/sync.sh`.
- Move the file to `docs/project/issues/archive/` and update the link at DEPLOYMENT.md:258.
</doc>
<doc path="docs/project/issues/plan.md">
- Line 42 (P5 row): mark 18 delivered.
- Line 98 (lane 5c): mark 18 delivered and give the plan path.
</doc>
<doc path=".un/skills/devsecops/config.json">
- Add a `test_groups` entry for each new test file, mapping it to:
  - `server.py`
  - `users_store.py`
  - `http_utils.py`
  - the new frontend module
  - `api-base.ts`
  - `about.template.html`
  - `vite.config.ts`
  - `DEPLOYMENT.md`
- Note that the existing `test_static_page_visit_logs.py` group points at a missing file.
</doc>

### highest_risk

client/backend/server.py (new analytics validator): any unguarded type escapes as an exception and gives no response instead of the required 400. The cases are a non-str field into `re.fullmatch`/`urlsplit`, `bool`/`float` timestamps, lone-surrogate strings that fail at INSERT, and `.hostname` raising on a malformed bracketed host.
client/backend/server.py (connect_db and the shared `user_db` connection): one unlocked sqlite3 connection is shared by every handler thread. `with conn:` commits or rolls back whatever is open, so a 90/min anonymous beacon route makes cross-thread commits or rollbacks of half-done profile writes far more likely. It is inherited, but this build is the first to amplify it.
tests/active/conftest.py (client_backend fixture and request helper), together with the vite and node test setup. The fixture's `RateLimiter(1000, 60)` cannot produce the planned 91st-request 429, and `ClientBackend.request` forces JSON. `navigator` must be stubbed with defineProperty before import. A `vite build` into the untracked-but-not-ignored `tests/tmp` leaves artifacts. Any of these makes the gating tests wrong or vacuous rather than red.

## 2026-10-02 - Step 4 - Reassess the implementation plan (pass 3)

Pass 3. New impacts: YES.

I read the files the inventory points at: `server.py` (imports, constants, `connect_db`, the handler, `_serve_get`/`_serve_post`, `_rate_limit_check`, the read-body idiom at 1014-1018 and 1050-1054), `http_utils.py`, `users_store.py`, `api-base.ts`, `vite.config.ts`, `about.template.html`, `conftest.py`, the `test_server.py` limiter helpers, `test_frontend_profile.py`, `config.json`, `.gitignore`, `package.json`, the DEPLOYMENT.md sections it cites, README.md, CONTEXT.md and plan.md. Every inventory claim I checked matches the tree. The plan holds. I found four small things the inventory does not carry: a body the JSON parser cannot handle without a 400, how `page_path` splits the About counts, the fact that `config.json` is not tracked in git, and one more README line.
<question id="1">
Yes. The route slots into `_serve_post` before line 501 with the same rate-limit-then-handler shape as its neighbours. `read_json_body` (http_utils.py:78-95) never reads Content-Type, and every parse failure it raises is a `ValueError` that the 1014-1018 idiom turns into a 400. `ensure_user_schema` runs at startup, `respond_bytes(self, 204, b"")` is already used at line 462, `resolveClientApiBase()` with no argument returns the env base or `window.location.origin`, and the vite `about` input picks up the template's module script. Things that would break it if done carelessly, all already listed as impacts: build URLs with `new URL`, not string concatenation; check `isinstance(str)` before every string operation in the validator; and the rate-limit test needs its own server (`conftest.py:84` uses `RateLimiter(1000, 60)`). One edge the plan misses (new impact 1): a body nested deeply enough to raise `RecursionError` inside `json.loads` gets no response at all instead of a 400. Every JSON route already has this, so it does not stop the build from working.
</question>
<question id="2">
- **First About JS.** The About page gets its first JavaScript and the Client gets its first anonymous write route that every page view hits.
- **`users.db` growth.** The database grows without bound, and the RateLimiter map gains an entry per distinct address.
- **Shared connection.** Writes now go through the unlocked shared `user_db` connection far more often than before (`connect_db`, line 232, `check_same_thread=False`, no lock).
- **Visit tracing.** The "Follow an About visit" recipe will always show at least the beacon's `request.start`.
- **Prod timing.** Prod sends nothing until `scripts/sync.sh` rebuilds `dist/`.
- **Split page counts.** nginx serves About at `/about`, `/about/` and `/about.html` (DEPLOYMENT.md:467-484), and vite rewrites the same three. `location.pathname` keeps whichever one the visitor used, and `page_path` is stored verbatim, so per-`page_path` page_view counts for the one About page come out as three rows (new impact 2).
- **Test groups.** The new test groups go into `.un/skills/devsecops/config.json`, which `.gitignore:32` excludes, so they never reach the commit (new impact 3).
</question>
<question id="3">
Code: nothing beyond the plan. Existing routes are untouched because the match is on the exact path. GET still answers 404, `do_OPTIONS` already answers any path, and nginx `location /api/` already proxies the route.

Docs and tracker, which the inventory already lists:
- the line 241/258 and line 404-406 DEPLOYMENT.md edits;
- README.md:50;
- the plan.md:42 and :98 rows;
- moving issue 18 to the archive and fixing its links;
- the config.json test groups.

Two additions here: README.md:28 says "client write/profile API that publishes normalized events to Engine", which is now slightly narrow (new impact 4). And because config.json is untracked, its edit has to be made in the working tree that runs the validator, not only in the commit.
</question>
<question id="4">
- **Existing behaviour.** Nothing existing changes. Every current route, status code, CORS header and schema table stays the same. `ensure_user_schema` adds one table and one index, and its docstring grows.
- **About page.** It changes from a static page with no script to one that POSTs on load and on clicks of tracked links. It never calls `preventDefault`, so navigation is unchanged. CSP `script-src 'self'` / `connect-src 'self'` already allow this.
- **DEPLOYMENT.md:404 "no browser-facing event publish route".** The statement stays literally true, since nothing is published to the Engine, but it needs the clarifying sentence the inventory already lists.
- **Rate limits.** Analytics gets its own 90/min bucket per address (the key is `ip:path`, line 516), so it does not use up the other routes' budgets.
</question>

New impacts:
client/backend/lib/http_utils.py — `read_json_body` (lines 89-92) catches only `json.JSONDecodeError`. A body nested deeply enough (e.g. 100k `[` within the 1 MB cap) makes `json.loads` raise `RecursionError`, which is not a `ValueError`. It slips past both `read_json_body` and the handler's `except ValueError` and reaches socketserver's `handle_error`. The client gets no response and `request.end` logs status `-`, so the plan's "invalid JSON → 400" fails for that input. The flaw is shared by every JSON route but now sits on an anonymous route hit on every page view. Cost to cover: catch `RecursionError` alongside `ValueError` in the new handler, one line, or add it to `read_json_body`, which changes a shared helper that the inventory says to leave alone. An oversized integer literal raises `ValueError` (the int-digits limit) and is correctly a 400.
DEPLOYMENT.md — the new "Count About analytics events" subsection's per-`page_path` page_view queries. nginx (467-484) and vite's `rewriteToAbout` serve About at `/about`, `/about/` and `/about.html`, `location.pathname` keeps whichever one the visitor used, and `page_path` is stored verbatim, so one page appears as up to three groups. The doc should either say so or show a query that folds them (e.g. `rtrim(replace(page_path, '.html', ''), '/')`). The counter test should seed at least two variants if a folded query is documented.
.un/skills/devsecops/config.json — `.gitignore:32` ignores `.un/`, so the new `test_groups` entries (and any fix to the stale 263-268 entry) are local-only and do not ship with the commit. Re-run selection for the new tests exists only in working trees that carry this file.
README.md — line 28's component summary ("client write/profile API that publishes normalized events to Engine") is narrow now that the backend also stores analytics events it never publishes. It is a separate element from the line-50 boundary row already in the inventory. Optional one-phrase widening.

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Catch `RecursionError` in `_handle_analytics_event`'s body read alongside `ValueError`, answer 400, and add a test with a deeply nested body.** Costs: about two lines and one test case. Keep `read_json_body` itself unchanged, as the inventory advises. A shared-helper fix for the other routes belongs in a follow-up issue rather than this build.
2. **Fold the three About URLs in the documented per-`page_path` page_view queries, or state the split in a caveat.** Costs: one SQL expression or one bullet. If folded, the counter test seeds `/about` and `/about.html` and asserts one group. Normalising on the server instead would change the settled rule that `page_path` is stored verbatim, so I do not recommend it.
3. **Make the `config.json` test-group edits in the working tree that runs the validator, and say in the delivery comment that they are local (`.un/` is gitignored).** Costs: nothing extra. The alternative, moving the config into git, is out of scope.
4. **Take the inventory's design-stage items as given:**
   - `new URL` for the endpoint;
   - an `isinstance(str)` check before each string rule;
   - a surrogate-encodability check on `href` and `page_path`;
   - catching `ValueError` around both `urlsplit` and `.hostname`;
   - a dedicated server for the 91-post limiter test (the `_client_backend` helper in test_server.py);
   - raw `urllib` for the text/plain and bad-body cases;
   - a `tmp_path` vite outDir with `--emptyOutDir`;
   - `Object.defineProperty` for `navigator`;
   - stubbing `window`, `location` and `document` before import;
   - following the built page's `<script src>`, not a fixed asset name.

   Costs: none beyond the planned tests.
5. **Open follow-up issues for the unlocked shared `user_db` connection, the missing `test_static_page_visit_logs.py`, and optionally `auxclick` counting and an analytics prune.** Costs: tracker entries only. Fixing the connection race in this build would widen its scope beyond the settled plan.
6. **Optional: widen README.md:28 alongside the line-50 row.** Costs: one phrase.

## 2026-10-02 - Step 4 - Reassess the implementation plan - ceiling reached

3 passes each surfaced new impacts and the loop stops here; the build proceeds on the inventory as it stands. What the 3th pass was still finding:

client/backend/lib/http_utils.py — `read_json_body` (lines 89-92) catches only `json.JSONDecodeError`. A body nested deeply enough (e.g. 100k `[` within the 1 MB cap) makes `json.loads` raise `RecursionError`, which is not a `ValueError`. It slips past both `read_json_body` and the handler's `except ValueError` and reaches socketserver's `handle_error`. The client gets no response and `request.end` logs status `-`, so the plan's "invalid JSON → 400" fails for that input. The flaw is shared by every JSON route but now sits on an anonymous route hit on every page view. Cost to cover: catch `RecursionError` alongside `ValueError` in the new handler, one line, or add it to `read_json_body`, which changes a shared helper that the inventory says to leave alone. An oversized integer literal raises `ValueError` (the int-digits limit) and is correctly a 400.
DEPLOYMENT.md — the new "Count About analytics events" subsection's per-`page_path` page_view queries. nginx (467-484) and vite's `rewriteToAbout` serve About at `/about`, `/about/` and `/about.html`, `location.pathname` keeps whichever one the visitor used, and `page_path` is stored verbatim, so one page appears as up to three groups. The doc should either say so or show a query that folds them (e.g. `rtrim(replace(page_path, '.html', ''), '/')`). The counter test should seed at least two variants if a folded query is documented.
.un/skills/devsecops/config.json — `.gitignore:32` ignores `.un/`, so the new `test_groups` entries (and any fix to the stale 263-268 entry) are local-only and do not ship with the commit. Re-run selection for the new tests exists only in working trees that carry this file.
README.md — line 28's component summary ("client write/profile API that publishes normalized events to Engine") is narrow now that the backend also stores analytics events it never publishes. It is a separate element from the line-50 boundary row already in the inventory. Optional one-phrase widening.

## 2026-10-02 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Draft: About analytics events (issue 18)

Before writing this I read: `server.py` (imports, constants, the `_run_request` / `_serve_post` / `_rate_limit_check` handler methods, `_handle_likes_import`, `_read_block_body`, `_parse_client_likes`), `lib/users_store.py`, `src/data/api-base.ts`, `src/data/user-actions.ts`, `dev-pages/about.template.html`, `videos.html`, `vite.config.ts`, `tests/active/conftest.py`, the `test_server.py` server helpers, `test_frontend_profile.py`, DEPLOYMENT.md 228-263, archive issue 21 and the `config.json` test groups.

**Template defect.** The step's "ladder the draft is written against" arrived as the literal placeholder `{rat_tail_ladder}`. No ladder was rendered, so this draft is checked against the high-level plan, the requirements, the settled impacts and the settled doc list only.

### What the build must prove (test inventory first)

1. **Valid events.** A valid `outbound_click` and a valid `page_view` (with `track_id`/`href` either absent or `null`) each answer 204 with an empty body and add exactly one row.
   - `created_at` falls between the server `now_ms()` readings taken before and after the request. It is not the client `timestamp`.
   - `user_agent` and `referer` are copied from the headers. Empty or absent values are stored as NULL.
2. **Content-Type is ignored.** A `text/plain` body carrying a valid event gets 204.
3. **Exact schema.** `PRAGMA table_info(analytics_events)` returns exactly `id, type, track_id, href, page_path, created_at, user_agent, referer`, so no IP-derived column exists.
4. **Invalid bodies.** Every invalid body gets 400 with a JSON `error` and leaves zero rows. That includes bodies that would crash a naive validator (unhashable `type`, lone surrogates, a malformed IPv6 host).
5. **Rate limit.** Under the production limiter (90/60 s), the 91st POST from one address gets 429 and the row count stays at 90.
6. **Unknown method.** `GET /api/analytics/event` gets 404.
7. **Counting queries.** The SQL blocks taken from DEPLOYMENT.md's new subsection, run read-only against the fixture DB, return the expected counts after N posted clicks and views.
8. **Browser behaviour (node).**
   - Import sends exactly one `page_view`.
   - A tracked click sends one correct `outbound_click`.
   - An untracked click, or a click on a Text node, sends nothing.
   - `fetch` with `keepalive` is used when `sendBeacon` is missing, returns false, or throws.
   - No unhandled rejection occurs when `fetch` rejects.
9. **Built page.** A real `vite build` of the template references a bundled `/assets/*.js` entry that contains `/api/analytics/event`.

### Module map

| File | Change |
|---|---|
| `client/backend/server.py` | imports `re` and `urlsplit`; imports `insert_analytics_event`; 4 constants; one `_serve_post` branch; `_handle_analytics_event` method; module functions `_validate_analytics_event`, `_analytics_href_ok`, `_utf8_safe` |
| `client/backend/lib/users_store.py` | table + index in `ensure_user_schema` and its docstring; new `insert_analytics_event` |
| `client/frontend/src/about-analytics.ts` | new module (whole file below) |
| `client/frontend/dev-pages/about.template.html` | one script tag |
| `tests/active/test_analytics_events.py` | new gating file (backend, counter, node, vite build) |
| `.un/skills/devsecops/config.json` | one `test_groups` entry |
| docs | DEPLOYMENT.md, client/README.md, client/frontend/README.md, README.md, CONTEXT.md, issue 18 (moved to archive), plan.md, two new follow-up issues 42 and 43 |

**Placement decision.** The impacts asked for the module's location to be decided at design. It stays at `src/about-analytics.ts`, as every settled impact and doc entry names it.
- It is not a page entry: About has no page logic, so `src/pages/about/index.ts` would claim a convention that doesn't apply.
- Keeping it means the template tag, the README, the test and config.json all name one path.

### Backend: `client/backend/server.py`

**Imports.**
- `import re` is added between `import random` and `import signal`.
- Line 20 becomes `from urllib.parse import parse_qs, urlencode, urlparse, urlsplit`.
- The users_store import block becomes:
```python
from lib.users_store import (clear_likes, close_like, ensure_user_schema, fetch_recent_likes,
                             get_or_create_user, insert_analytics_event, load_liked_keys,
                             record_like, remove_like, video_reaction)
```

**Constants.** These go after `BLOCK_REFERENCE_MAX_LENGTH = 200`:
```python
ANALYTICS_EVENT_TYPES = frozenset(("outbound_click", "page_view"))
# fullmatch only: `$` would accept a trailing newline.
ANALYTICS_TRACK_ID_PATTERN = re.compile(r"[a-z0-9_]{1,64}")
ANALYTICS_HREF_MAX_LENGTH = 2048
ANALYTICS_PAGE_PATH_MAX_LENGTH = 256
```

**Route.** The new branch goes in `_serve_post`, after the blocks branch and before the `/client/events/publish` comment and the final 404:
```python
        if url.path == "/api/analytics/event":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_analytics_event()
            return
```
- The rate-limit check runs before any parsing.
- The limiter key is `<ip>:/api/analytics/event`, so analytics gets its own 90/min bucket.

**Handler method.** It sits next to `_handle_likes_import`:
```python
    def _handle_analytics_event(self) -> None:
        """Store one About page analytics event; the client address is never stored, only rate-limited on."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        event = _validate_analytics_event(body)
        if isinstance(event, str):
            respond_json(self, 400, {"error": event})
            return
        event_type, track_id, href, page_path = event
        user_agent = self.headers.get("User-Agent", "").strip() or None
        referer = self.headers.get("Referer", "").strip() or None
        with self.server.user_db:
            insert_analytics_event(self.server.user_db, event_type, track_id, href, page_path, now_ms(), user_agent, referer)
        respond_bytes(self, 204, b"")
```
- **Content-Type.** Never read, because `read_json_body` ignores it.
- **Empty body.** It parses to `{}` and fails on `type`, so it gets 400.
- **Errors from `read_json_body`.** It raises `ValueError` for invalid JSON, a non-object body, non-UTF-8 bytes (`UnicodeDecodeError`), and a bad or over-1 MB length. Each becomes 400.
- **Headers.** They arrive latin-1 decoded, so they always bind in SQLite.
- **One clock read.** `now_ms()` is read exactly once per row.

**Validator.** These are module-level functions placed after `_parse_client_likes`. They are pure and never raise on any JSON-decoded dict.
```python
def _validate_analytics_event(body: dict[str, Any]) -> tuple[str, str | None, str | None, str] | str:
    """Handle validate analytics event.

    :returns: `(type, track_id, href, page_path)` to store, or the error message for a 400.
    """
    event_type = body.get("type")
    # Checked as a str first: a list or dict `type` is unhashable and would raise in the set lookup.
    if not isinstance(event_type, str) or event_type not in ANALYTICS_EVENT_TYPES:
        return "type must be outbound_click or page_view"
    page_path = body.get("page_path")
    if (not isinstance(page_path, str) or not 1 <= len(page_path) <= ANALYTICS_PAGE_PATH_MAX_LENGTH
            or not page_path.startswith("/") or not _utf8_safe(page_path)):
        return "page_path must be a path of 1 to 256 characters starting with /"
    timestamp = body.get("timestamp")
    # bool is an int subclass; a JSON 1.0 arrives as float and is rejected too. Checked, then discarded.
    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0:
        return "timestamp must be a non-negative integer"
    track_id = body.get("track_id")
    href = body.get("href")
    if event_type == "page_view":
        if track_id is not None or href is not None:
            return "page_view takes no track_id or href"
        return event_type, None, None, page_path
    if not isinstance(track_id, str) or not ANALYTICS_TRACK_ID_PATTERN.fullmatch(track_id):
        return "track_id must match [a-z0-9_]{1,64}"
    if not _analytics_href_ok(href):
        return "href must be an absolute http or https URL of at most 2048 characters"
    return event_type, track_id, href, page_path


def _analytics_href_ok(href: Any) -> bool:
    """Return whether `href` is an absolute http(s) URL with a host, short enough and storable."""
    if not isinstance(href, str) or len(href) > ANALYTICS_HREF_MAX_LENGTH or not _utf8_safe(href):
        return False
    try:
        # `.hostname` re-parses the netloc and can raise on a malformed bracketed host, so it sits inside the try.
        parts = urlsplit(href)
        hostname = parts.hostname
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(hostname)


def _utf8_safe(value: str) -> bool:
    """Return whether `value` encodes as UTF-8; a JSON lone surrogate decodes to a str sqlite3 cannot bind."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True
```

Invariants:
- **Return shape.** The result is either a 4-tuple whose values are safe to bind, or an error string.
- **`track_id` encoding.** It needs no UTF-8 check because its regex is ASCII-only.
- **Scheme case.** `urlsplit` lowercases the scheme, so `HTTPS://x.y` passes.
- **Rejected `href` shapes.** `https://` (hostname None), `http://[::1` (ValueError), `mailto:` and `/relative` all fail.
- **`page_path` is stored verbatim.** `//host` passes, which is acceptable because the value is never followed.
- **Known looseness.** `urlsplit` silently drops tab and newline characters when it parses, so an `href` containing them passes and is stored verbatim. Browsers never produce such a resolved `href`. There is no extra rule because the spec does not ask for one.

### Storage: `client/backend/lib/users_store.py`

**Docstring.** Line 11 becomes `"""Create the users, likes, like generation, profile, block, dislike and analytics event tables if missing."""`.

**Schema.** Inserted after the `like_generations` table and before the `-- Every visitor's actions…` cleanup:
```sql
        CREATE TABLE IF NOT EXISTS analytics_events (
          id INTEGER PRIMARY KEY,
          type TEXT NOT NULL CHECK (type IN ('outbound_click', 'page_view')),
          track_id TEXT,
          href TEXT,
          page_path TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          user_agent TEXT,
          referer TEXT
        );
        CREATE INDEX IF NOT EXISTS analytics_events_type_track_created_idx
          ON analytics_events (type, track_id, created_at);
```

**Insert function.** New, placed after `video_reaction`. It does not commit: the handler's `with self.server.user_db:` owns the transaction, following `remove_like`/`close_like`.
```python
def insert_analytics_event(conn: sqlite3.Connection, event_type: str, track_id: str | None, href: str | None,
                           page_path: str, created_at: int, user_agent: str | None, referer: str | None) -> None:
    """Insert one analytics event, inside the caller's transaction."""
    conn.execute(
        "INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_type, track_id, href, page_path, created_at, user_agent, referer),
    )
```

**Startup.** No edit: `server.py:1311` already calls `ensure_user_schema`, so existing DBs gain the table on restart.

### Frontend: `client/frontend/src/about-analytics.ts`

```ts
/**
 * Module `client/frontend/src/about-analytics.ts`: send the About page's analytics events (one page view, one event per tracked outbound click).
 */

import { resolveClientApiBase } from "./data/api-base";

type AnalyticsEvent =
  | { type: "page_view"; page_path: string; timestamp: number }
  | { type: "outbound_click"; track_id: string; href: string; page_path: string; timestamp: number };

/**
 * Handle send analytics event. Never throws and never rejects: analytics must not surface to the visitor.
 */
function sendAnalyticsEvent(event: AnalyticsEvent): void {
  try {
    // No argument, so `?api=` is never read; built with `new URL` like every sibling, so a base ending in `/` gives no `//api`.
    const url = new URL("/api/analytics/event", resolveClientApiBase()).toString();
    const body = JSON.stringify(event);
    try {
      // Called on `navigator` itself: a detached reference throws "Illegal invocation".
      if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function"
        && navigator.sendBeacon(url, new Blob([body], { type: "application/json" }))) {
        return;
      }
    } catch {
      // A refused cross-origin beacon can throw; fetch gets one more try.
    }
    fetch(url, { method: "POST", body, headers: { "Content-Type": "application/json" }, keepalive: true }).catch(() => undefined);
  } catch {
    // A bad base, a missing fetch or an over-64 KiB keepalive body throws synchronously; swallowed.
  }
}

/**
 * Handle document click: one outbound_click per click that resolves to an `a[data-track-id]`.
 */
function handleDocumentClick(event: Event): void {
  const target = event.target as Element | null;
  // A Text node or the document itself has no `closest`.
  if (!target || typeof target.closest !== "function") {
    return;
  }
  const link = target.closest("a[data-track-id]");
  if (!link) {
    return;
  }
  // An SVG <a>'s `href` is an SVGAnimatedString; the server would reject it, so nothing is sent.
  const href = (link as HTMLAnchorElement).href;
  if (typeof href !== "string") {
    return;
  }
  sendAnalyticsEvent({
    type: "outbound_click",
    track_id: link.getAttribute("data-track-id") ?? "",
    href,
    page_path: window.location.pathname,
    timestamp: Date.now()
  });
}

sendAnalyticsEvent({ type: "page_view", page_path: window.location.pathname, timestamp: Date.now() });
document.addEventListener("click", handleDocumentClick);
```
- **No exports.** The module acts on import. A module script is deferred, so `document` is parsed by the time it runs and there is no DOMContentLoaded wait.
- **No `preventDefault`,** so navigation is untouched.
- **A malformed `data-track-id`** (for example uppercase) is still sent and gets 400. That is the shape-validation contract, and the README documents the pattern.
- **Gateway scan.** There is no Engine base, no `127.0.0.1:707x` literal and no `/internal/` path, so `check-frontend-client-gateway.sh` passes.

### Template: `client/frontend/dev-pages/about.template.html`

One line goes before `</body>`, as in `videos.html:65`:
```html
    <script type="module" src="/src/about-analytics.ts"></script>
```
No About URL or dev-pages filename changes.

### Tests: `tests/active/test_analytics_events.py`

One file holds everything, so one config.json group maps it to all eight settled paths (the "fewest files" choice).

**Constants and helpers:**
- `FRONTEND`, `ESBUILD` and `VITE` (`node_modules/.bin/vite`).
- `_post(base, raw: bytes, headers: dict) -> (status, body)` over raw `urllib.request`. This is needed for `text/plain`, invalid JSON, non-UTF-8 and custom/empty UA. Setting `User-Agent: ""` overrides urllib's default.
- `_rows(db_path)` reads all rows as dicts.
- `_event(**overrides)` builds a valid click body.
- `_serving_limited(tmp_path)` is a contextmanager. It builds `ClientBackendServer` exactly as conftest does, but with `RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS)`.

**Backend tests (they use the conftest `client_backend` fixture unless stated):**
- `test_outbound_click_stores_one_row`:
  - Setup: take `before = now_ms()`, then POST a click with `timestamp: 1`, `User-Agent: Mozilla/5.0 analytics-test`, `Referer: https://example.org/about`.
  - Expect a 204 with an empty body.
  - Expect exactly one row with the expected `type`, `track_id`, `href` and `page_path`, `before <= created_at <= now_ms()`, `created_at != 1`, and UA and Referer equal to the headers.
- `test_page_view_stores_one_row`: parametrized over `track_id`/`href` absent vs explicit `null`. Expect 204, one row with NULL `track_id` and `href`.
- `test_text_plain_beacon_accepted`: send `Content-Type: text/plain;charset=UTF-8`. Expect 204 and one row.
- `test_missing_headers_store_null`: send `User-Agent: ""` and no Referer. Both columns are NULL.
- `test_schema_has_no_address_column`: the `PRAGMA table_info` names equal the exact 8-column list.
- `test_invalid_event_rejected` is parametrized over raw bodies. Each case expects 400, a JSON `error` key and zero rows. Status is asserted, not message text. The cases:
  - **body:** `b""`, `b"{"`, `b"[]"`, `b"\xff"`;
  - **type:** missing, `"click"`, `["page_view"]`;
  - **track_id:** missing on a click, `null` on a click, `"About_Patreon"`, `""`, 65×`a`, `"a-b"`, `"abc\n"`, `5`;
  - **href:** missing, `"mailto:a@b.c"`, `"javascript:alert(1)"`, `"https://"`, `"/relative"`, `"http://[::1"`, `"https://x.y/" + "a"*2040`, `42`, `json.dumps("https://x.y/\ud800")`;
  - **page_path:** missing, `""`, `"about"`, `"/" + "a"*256`, `7`, `"/\ud800"`;
  - **timestamp:** missing, `"1"`, `1.0`, `true`, `-1`, `null`;
  - **page_view:** with `track_id: "about_x"`, and with `href: "https://x.y"`.
- `test_get_is_not_a_route`: `GET` gives 404.
- `test_rate_limit_rejects_and_stores_nothing`: uses `_serving_limited`, with `X-Forwarded-For: 203.0.113.18` (127.0.0.1 is a trusted proxy by default). 90 valid posts each give 204. The 91st gives 429 with `{"error": "Rate limit exceeded"}`, and the row count is 90.

**Counter test (`test_documented_queries_count_events`):**
- **Extraction.**
  - The DEPLOYMENT.md text is sliced from `### Count About analytics events` to the next `\n### `.
  - Blocks are found with `re.findall(r"```sql\n(.*?)```", section, re.S)`.
  - The test asserts `len(blocks) == 7`, so the extraction can't pass vacuously.
- **Posted events:**
  - 3 clicks `about_test`;
  - 1 click `about_other`;
  - 1 click `about_test` with UA `Googlebot/2.1`;
  - 1 click `about_test` with empty UA;
  - page views: 2 on `/about` and 1 on `/about.html`, plus 1 on `/about` with UA `bingbot`.
- **Connection.** The DB is opened with `sqlite3.connect(f"file:{db}?mode=ro", uri=True)`, matching `-readonly`.
- **Expected results.** `day` is computed from the stored `created_at` rather than from the wall clock, so the test is midnight-safe. Each block in order must return:
  1. `{about_test: 5, about_other: 1}`
  2. `[(day, about_other, 1), (day, about_test, 5)]`
  3. `4`
  4. `[(day, 4)]`
  5. `{/about: 3, /about.html: 1}`
  6. `{about_test: 3, about_other: 1}`
  7. `[(day, 3)]`
- The clicks for one `track_id` are counted, which is the counter acceptance criterion.

**Node test (`test_beacon_dispatch`):**
- **Bundling.** `src/about-analytics.ts` is bundled with esbuild using `--define:import.meta.env.VITE_CLIENT_API_BASE="http://api.test/"` (trailing slash on purpose) and `--define:import.meta.env.DEV=false`.
- **Runner stubs, all installed before `await import(BUNDLE)`:**
  - `globalThis.window = {location: {origin: "http://page.test", pathname: "/about"}}`;
  - `Object.defineProperty(globalThis, "navigator", {value: {...}, configurable: true})`, with `sendBeacon` per `MODE`: `true` returns true, `false` returns false, `missing` is undefined, `throws` throws;
  - `globalThis.document = {addEventListener: (t, h) => handlers.push([t, h])}`;
  - `globalThis.fetch` records the call and returns `Promise.reject(new Error("offline"))`;
  - a `process.on("unhandledRejection")` counter.
- **Runner actions.** After the import, the runner:
  - dispatches the captured click handler with three targets: a tracked target whose `closest` returns `{href: "https://www.patreon.com/x", getAttribute: () => "about_patreon"}`, an untracked target whose `closest` returns null, and a Text-like `{}`;
  - awaits `blob.text()` for each beacon and lets microtasks drain;
  - prints JSON of `{sent: [{via, url, body, keepalive, contentType}], rejections}`.
- **Assertions,** parametrized over the four MODEs:
  - exactly 2 sends;
  - every `url == "http://api.test/api/analytics/event"`;
  - the first is `page_view` with `page_path "/about"` and an int `timestamp`;
  - the second is `outbound_click` with `about_patreon`, the href, `/about` and an int `timestamp`;
  - `via` is `beacon` only in mode `true`, otherwise `fetch` with `keepalive: true` and `Content-Type: application/json`;
  - `rejections == 0`;
  - exactly one `click` listener is installed.

**Built-page test (`test_built_about_page_bundles_beacon`):**
- **Skip.** It runs `pytest.skip` with a reason when `FRONTEND / "dev-pages/about.html"` exists, because a local override would be built instead of the template.
- **Build.** `[VITE, "build", "--outDir", str(tmp_path / "dist"), "--emptyOutDir"]` runs with `cwd=FRONTEND`, an env without `VITE_CLIENT_API_BASE`, and `timeout=300`. It never writes into `client/frontend/dist` or `tests/tmp`.
- **Assertions.**
  - `dist/dev-pages/about.template.html` contains a `src="(/assets/[^"]+\.js)"` script.
  - That entry file contains `/api/analytics/event`. The literal lives in the module, which is the About entry chunk, while `api-base` may be split into a shared chunk.

### `.un/skills/devsecops/config.json`

A new entry is added before `test_static_page_visit_logs.py`. That existing entry is left in place and flagged in issue 43.
```json
    "test_analytics_events.py": [
      "client/backend/server.py",
      "client/backend/lib/users_store.py",
      "client/backend/lib/http_utils.py",
      "client/frontend/src/about-analytics.ts",
      "client/frontend/src/data/api-base.ts",
      "client/frontend/dev-pages/about.template.html",
      "client/frontend/vite.config.ts",
      "DEPLOYMENT.md"
    ],
```

### Docs (content drafted, one paragraph per line in the files)

**DEPLOYMENT.md, new `### Count About analytics events`.** It goes between "Follow an About visit" and "Follow one request".
- **Lead paragraph.** The About page's own script sends a `page_view` per load and an `outbound_click` per click on an `a[data-track-id]` to `POST /api/analytics/event`. The Client backend stores each as one row of `analytics_events` in `users.db`, with server time in `created_at` (epoch ms), `user_agent` and `referer`, and no address. The queries below count them.
- **Invocation.** `sudo sqlite3 -readonly <root>/client/backend/db/users.db`.
- **The seven `sql` blocks,** one statement each and in this order. The order is pinned by the counter test.
  1. `SELECT track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' GROUP BY track_id ORDER BY clicks DESC;`
  2. `SELECT date(created_at / 1000, 'unixepoch') AS day, track_id, COUNT(*) AS clicks FROM analytics_events WHERE type = 'outbound_click' GROUP BY day, track_id ORDER BY day, track_id;`
  3. `SELECT COUNT(*) AS views FROM analytics_events WHERE type = 'page_view';`
  4. `SELECT date(created_at / 1000, 'unixepoch') AS day, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY day ORDER BY day;`
  5. `SELECT page_path, COUNT(*) AS views FROM analytics_events WHERE type = 'page_view' GROUP BY page_path ORDER BY views DESC;`
  6. Block 1 with `AND user_agent IS NOT NULL AND user_agent NOT LIKE '%bot%' AND user_agent NOT LIKE '%crawl%' AND user_agent NOT LIKE '%spider%'` added to the `WHERE`.
  7. Block 4 with the same filter.
- **Prose around the blocks.**
  - Days are UTC.
  - Add `page_path` to block 4's SELECT and GROUP BY to split daily views by path.
  - Add the four filter conditions to any query to exclude obvious bots. `LIKE` is ASCII case-insensitive.
- **Caveats** (one bullet each):
  - **Forgeable counts.** The endpoint is anonymous and accepts up to 90 per minute per address.
  - **Unbounded retention.** Rows are never pruned, so `users.db` grows. It matters for backups.
  - **The UA filter is a heuristic.** It removes honest crawlers only.
  - **Referer is often reduced** to the About URL by the default referrer policy.
  - **Clicks not counted.** Middle-click and context-menu "open in new tab" are not counted. Ctrl/Cmd-click and keyboard activation are.
  - **Non-http(s) tracked links** (`mailto:`, `tel:`) are rejected and never counted.
  - **Silent undercount.** A shared or misresolved client address caps a whole population at 90/min. `sendBeacon` never sees the 429. See `TRUSTED_PROXIES`, ADR-0002 and section 6's `X-Forwarded-For` lines.
  - **Dev beacons may be lost.** Under `npm run dev` the API base is cross-origin. A credentialed `application/json` beacon's preflight gets no `Access-Control-Allow-Credentials` (ADR-0004), so dev beacons may be lost.
  - **Shared connection.** Analytics writes share the single unlocked `users.db` connection with profile writes (issue 42).
  - **Prod rollout.** Prod sends nothing until `scripts/sync.sh` rebuilds `dist/`.

**DEPLOYMENT.md, edits elsewhere:**
- **241.** Append: "Every About view now also makes one `POST /api/analytics/event` (and one per tracked click), so the window always shows at least that beacon's `request.start`."
- **258.** Second sentence becomes: "Counting human visits uses the page's own pageview beacon: see "Count About analytics events" and `docs/project/issues/archive/18-about-outbound-click-tracking.md`."
- **404-406.** Add: "`POST /api/analytics/event` is browser-facing and needs no key: it stores About analytics rows in the Client's `users.db` and publishes nothing to the Engine."
- **465.** Add a parenthesis to the rat-tail comment: "(`tests/active/test_static_page_visit_logs.py` does not exist yet; issue 43)".
- **Optional lines taken:**
  - **70:** "`analytics_events`, unpruned".
  - **523:** "…and About analytics undercounts silently".
- **Skipped as optional.** The Verify POST is left out, because it would write a real row into prod `users.db`.

**client/README.md:**
- **New Backend Responsibilities bullet:** "`POST /api/analytics/event`: anonymous About analytics. Body `{type: "page_view", page_path, timestamp}` or `{type: "outbound_click", track_id, href, page_path, timestamp}`. Answers 204, 400 on any invalid field, 429 over the route limit. Content-Type is ignored and no profile key is needed. One row per event in `users.db` `analytics_events`. Nothing derived from the client address is stored, and nothing is published to the Engine."
- **Line 41.** The route list gains `/api/analytics/event`.
- **Line 71.** Gains: "also needed for dev About beacons, which may still be lost (credentialed beacon)."

**client/frontend/README.md:**
- **"What it does"** gains a bullet: "About sends one anonymous `page_view` per load and one `outbound_click` per click on an `a[data-track-id]` link to the Client backend (`src/about-analytics.ts`)."
- **"Local About Overrides"** gains a paragraph. An override adds `<script type="module" src="/src/about-analytics.ts"></script>` (root-absolute, like the stylesheet) and `data-track-id="about_<name>"` on each outbound link to count, matching `[a-z0-9_]{1,64}`. The paragraph also says:
  - only http(s) links count;
  - middle-click and context-menu opens are not counted;
  - an override without the tag sends nothing, not even page views.
- **Line 24.** Gains the dev cross-origin note: needs `CLIENT_CORS_ORIGINS`, may be lost.

**README.md line 50.** `/api/analytics/event` is added to the Client backend's browser-facing routes cell.

**CONTEXT.md, after Interaction event:** "- **Analytics event** — an anonymous `page_view` or `outbound_click` the About page's own script sends to the Client backend, which stores it in `users.db` `analytics_events` with nothing derived from the client address and never sends it to the Engine; unlike an **Interaction event**, it does not feed ranking."

**Issue 18:**
- `Status: enhancement, complete`.
- `git mv` to `docs/project/issues/archive/`.
- A comment in the style of archive/21:31, covering:
  - which plan delivered it;
  - the route and table names chosen, and that no allowlist or `ip_hash` was used;
  - that the template and override docs changed, not the non-existent `client/frontend/about.html`;
  - the follow-ups, issues 42 and 43;
  - that prod beacons start after the next `scripts/sync.sh`;
  - that the stale non-archive `21-static-page-visit-logs.md` duplicate remains.

Draft wording:
> Delivered by `docs/project/plans/23-18-about-outbound-click-tracking.md`, as one route `POST /api/analytics/event` for both `page_view` and `outbound_click` (not `/outbound-click`), one table `analytics_events` (not `outbound_click_events`), shape validation instead of an allowlist (the real About page is an untracked override), and no `ip_hash` or other address-derived value. The tracked template `dev-pages/about.template.html` and the override docs changed; `client/frontend/about.html` does not exist. Counts are queried with the "Count About analytics events" runbook in `DEPLOYMENT.md`. Prod sends nothing until the next `scripts/sync.sh`. Follow-ups: `42-users-db-shared-connection-race`, `43-static-page-visit-logs-test-missing`. The stale `docs/project/issues/21-static-page-visit-logs.md` duplicate is still beside its archive copy.

**plan.md:**
- **Line 42.** "19, 20, 21 and 18 are delivered".
- **Line 98.** "18 delivered by `docs/project/plans/23-18-about-outbound-click-tracking.md`". The plan document itself is workflow-rendered and not hand-edited. If it moves to `plans/archive/`, this link and the issue comment follow.

**New follow-up issues (`Status: bug, needs-triage`):**
- **`42-users-db-shared-connection-race.md`.** One `check_same_thread=False` connection is shared by all handler threads without a lock. A `with conn:` on one thread commits or rolls back another's transaction. The anonymous analytics route raises the write rate. Fix with a write lock or per-thread connections.
- **`43-static-page-visit-logs-test-missing.md`.** Issue 21's guard `tests/active/test_static_page_visit_logs.py` was never written. It is still cited at DEPLOYMENT.md:465 and config.json:263.

### Check against plan and requirements

**Pass 1 found and fixed these gaps:**
- **Unhashable `type`.** `type` as a list raised `TypeError` in the frozenset lookup, which drops the connection. It is now checked as a str first.
- **SVG links.** An SVG link sent a non-string `href`. It now sends nothing.
- **Missing `navigator`.** A missing `navigator` threw before the fallback. It is now guarded.
- **Rate-limit fixture.** The rate-limit test could not use the fixture's 1000/60 limiter, so it has its own server.
- **Header in a test.** One test also needed an empty UA header.

**Pass 2: every requirement maps to code or a test:**
- **Endpoint.** Route, 204/400/429, Content-Type ignored, `_run_request` wrapping, GET 404.
- **Validation.** Every validation rule and the unknown-keys rule.
- **Schema and storage.** Exact schema, CHECK and index, created at startup, `now_ms`, UA/Referer→NULL, no address, one row per request, no pruning.
- **Frontend.** Module behaviour, transport and fallback, swallowed failures, Client API base, template tag, override docs.
- **Docs and tracker.** Reporting queries including the bot filter, doc route lists, CONTEXT entry, tracker housekeeping.
- **Acceptance tests.** One for each acceptance bullet.

Nothing remains unmet. It converged on pass 2.

**Limitations the operator accepts** (from the plan, all documented):
- **Override checkouts.** The built-page gate skips on a checkout with a local override.
- **Uncounted opens.** Middle-click and context-menu opens are not counted.
- **Non-http(s) links.** Tracked non-http(s) links are not counted.
- **Best-effort counts.** Counts are best-effort: forgeable within 90/min/address, unpruned, with a heuristic bot filter.
- **Dev beacons.** Dev cross-origin beacons may be lost.
- **Shared connection.** The shared-connection race is inherited, and filed as issue 42 rather than fixed here.
- **Missing guard.** `test_static_page_visit_logs.py` does not exist, so the plan's "stays green" wording is dropped and issue 43 is filed instead.

## 2026-10-02 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Analytics storage [code]

**Files touched.** client/backend/lib/users_store.py (EDITED), tests/active/test_analytics_events.py (NEW)

**Checkpoint.** Seam: `lib/users_store.py` called directly on a tmp `sqlite3` connection. No server is involved. Assert two things. First, after `ensure_user_schema(conn)` (run twice, to show it is idempotent), `[r[1] for r in conn.execute("PRAGMA table_info(analytics_events)")]` equals exactly `["id","type","track_id","href","page_path","created_at","user_agent","referer"]`. Second, one `insert_analytics_event(...)` inside `with conn:` leaves exactly one row with the passed values, read back through a second connection to the same file.

**Intent.** `users.db` gains an `analytics_events` table, created by `ensure_user_schema` with the settled columns, CHECK and index. `lib/users_store.py` gains an `insert_analytics_event` that writes one row inside the caller's transaction.

- C1 - After `ensure_user_schema`, `analytics_events` has exactly the eight settled columns and none derived from the client address.
- C2 - One `insert_analytics_event` call inside `with conn:` commits exactly one row with the given values.

**Outcome.** _pending_

#### Phase 2 - Event validator [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_analytics_events.py (EDITED)

**Checkpoint.** Seam: the pure module function `client_server._validate_analytics_event(dict)`, imported the way `test_server.py` imports server internals. Assert that valid `outbound_click` and `page_view` bodies return the expected `(type, track_id, href, page_path)` tuple, including `track_id`/`href` absent versus `null` and unknown keys ignored. Assert that every invalid body in the draft's case list (`type`, `track_id`, `href`, `page_path`, `timestamp` and the page_view-with-extras cases, including the list `type`, lone surrogates and `http://[::1`) returns a `str` and does not raise. The parametrization is taken from the draft's list.

**Intent.** `server.py` gains a pure `_validate_analytics_event` (with `_analytics_href_ok` and `_utf8_safe`) that turns any JSON-decoded dict into either the four storable values or an error message, following the settled rules.

- C1 - Each valid event body yields its `(type, track_id, href, page_path)` tuple.
- C2 - Each invalid event body yields an error string without raising.

**Outcome.** _pending_

#### Phase 3 - Analytics route [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_analytics_events.py (EDITED), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: real HTTP over a socket to `ClientBackendServer`, through the conftest `client_backend` fixture, with raw `urllib.request` POSTs (the `test_server.py` precedent). The 429 case uses a `_serving_limited` server built like conftest but with the production `RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)` and `X-Forwarded-For: 203.0.113.18`. For accepted events, assert 204 with an empty body and exactly one row. `created_at` must be within the [before, after] `now_ms()` window and not equal the client `timestamp`. UA and Referer must be copied from the headers, and empty or absent values must be NULL. This holds for `application/json` and `text/plain`. For refused POSTs, assert the row count is unchanged: a sample of invalid bodies (empty, `{`, `[]`, `\xff` and one per field) gets 400 with a JSON `error`, and the 91st of 91 gets 429 with `{"error":"Rate limit exceeded"}` and 90 rows. A `GET` of the path gets 404 as a regression line, not as a clause.

**Intent.** `POST /api/analytics/event` in `_serve_post` stores each accepted event as one server-stamped row in `analytics_events`, and stores nothing for a request it refuses.

- C1 - A valid event of either type, with any Content-Type, gets 204 and adds one row whose `created_at`, `user_agent` and `referer` come from the server.
- C2 - A refused POST, whether 400 for an invalid body or 429 over the route limit, adds no row.

**Outcome.** _pending_

#### Phase 4 - About beacon [code]

**Files touched.** client/frontend/src/about-analytics.ts (NEW), client/frontend/dev-pages/about.template.html (EDITED), tests/active/test_analytics_events.py (EDITED)

**Checkpoint.** There are two seams. (a) `src/about-analytics.ts` is bundled with the project's esbuild into node, the same harness as `tests/active/test_frontend_profile.py`, with `VITE_CLIENT_API_BASE="http://api.test/"` defined. Stubbed `window`, `navigator`, `document` and a rejecting `fetch` are installed before the import. The test is parametrized over the sendBeacon modes true, false, missing and throws. It asserts exactly 2 sends to `http://api.test/api/analytics/event`: a `page_view` for `/about` and then an `outbound_click` with `about_patreon` and its href, where the untracked target and the Text-like target send nothing. It also asserts beacon delivery only in mode true and otherwise fetch with `keepalive: true` and `Content-Type: application/json`, 0 unhandled rejections, and one `click` listener. (b) A real `node_modules/.bin/vite build --outDir <tmp_path>/dist` run from `client/frontend`. It asserts that `dist/dev-pages/about.template.html` has a `src="/assets/*.js"` script whose file contains `/api/analytics/event`. It skips with a reason if `dev-pages/about.html` exists.

**Intent.** The About page template loads a new `src/about-analytics.ts`, which on import sends one `page_view` and then one `outbound_click` per click on an `a[data-track-id]`. Delivery is `sendBeacon` with a keepalive `fetch` fallback, and the built page ships it as a bundled asset.

- C1 - Importing the module sends one `page_view` and one `outbound_click` per tracked click, falling back to keepalive `fetch` when `sendBeacon` is unavailable, refuses or throws.
- C2 - A vite build of the About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`.

**Outcome.** _pending_


Needs coordination: none. No credential, live endpoint or manual step is needed. Phase 4 needs `client/frontend/node_modules` (esbuild and vite) installed, which `test_frontend_profile.py` already requires. Its built-page check skips on a checkout that has an untracked `dev-pages/about.html` override.

Rationale: The build splits along the dependency chain, so each slice can be checked before the next one exists. Storage (P1) is tested on a bare sqlite connection. The validator (P2) is a pure function and gets the large invalid-case matrix without a server. The route (P3) puts them together over a socket and only needs a sample of invalid bodies plus the rate limit. The frontend (P4) depends on nothing in the backend and is proven in node and through a real vite build.

Each phase's Intent reduces to two clauses. Phase 3's second clause is one fact, "a refused request stores nothing", parametrized over the two refusal causes (400 and 429). GET→404 is not a clause because unknown routes already answer 404. It stays in the P3 test only as a regression line.

The counter test (`test_documented_queries_count_events`) extracts its SQL from DEPLOYMENT.md. Documentation gets no phase, so the operator approved moving that test to Step 9, where it is added together with the "Count About analytics events" subsection and gated by the full-suite-green close. The config.json test group lands in P3, where the test file starts covering `server.py`.

All other documentation and tracker edits are left to Step 9 as well: DEPLOYMENT.md, both READMEs, README.md, CONTEXT.md, the move of issue 18, plan.md and issues 42 and 43. There is no prose phase, because no agent-facing text changes.

Template defect: `{principles}`, `{shape_ladder-ladder}` and `{tdd_seams}` arrived unrendered. Seams were therefore chosen from the existing harnesses: the conftest `client_backend` fixture, `test_server.py`-style raw POSTs, and `test_frontend_profile.py`'s esbuild-in-node runner. All three exist in the tree.

## 2026-10-02 - Step 7 - Phase 1 (Analytics storage) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`users.db` gains an `analytics_events` table, created by `ensure_user_schema` with the settled columns, CHECK and index. `lib/users_store.py` gains an `insert_analytics_event` that writes one row inside the caller's transaction.

- C1 - After `ensure_user_schema`, `analytics_events` has exactly the eight settled columns and none derived from the client address.
- C2 - One `insert_analytics_event` call inside `with conn:` commits exactly one row with the given values.

must_prove:
- C1 - After `ensure_user_schema`, `analytics_events` has exactly the eight settled columns and none derived from the client address.
- C2 - One `insert_analytics_event` call inside `with conn:` commits exactly one row with the given values.

## 2026-10-02 - Step 7 - Phase 1 (Analytics storage) - self-check (audit round 1, send-back 0)

`tests/tmp/test_18_about_outbound_click_tracking_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase1.py:42 — `[row[1] for row in PRAGMA table_info(analytics_events)] == COLUMNS`, after ensure_user_schema has run twice - expected: ["id", "type", "track_id", "href", "page_path", "created_at", "user_agent", "referer"]. The probe showed exactly this for the plan's settled DDL run twice through executescript. Against the current code the run shows `[]` because the table does not exist yet. - excludes: A table that also has an `ip_hash` or `client_ip` column (the address-derived column the issue first proposed) reads a nine-item list. One missing a column (for example no `referer`) or in a different order also fails, and so does an ensure_user_schema that never creates the table, which reads `[]`.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase1.py:43 — `(name, type, notnull, pk)` for each column from PRAGMA table_info == COLUMN_DEFS - expected: [("id","INTEGER",0,1), ("type","TEXT",1,0), ("track_id","TEXT",0,0), ("href","TEXT",0,0), ("page_path","TEXT",1,0), ("created_at","INTEGER",1,0), ("user_agent","TEXT",0,0), ("referer","TEXT",0,0)]. Observed in the probe as `(0, 'id', 'INTEGER', 0, None, 1), (1, 'type', 'TEXT', 1, None, 0), …`. - excludes: Getting the column names right but not the declarations fails here. Examples: `page_path TEXT` without NOT NULL reads notnull 0, `created_at TEXT` reads 'TEXT', and `id INTEGER` that is not the primary key reads pk 0.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase1.py:44 — the ordered column lists of every index on analytics_events == [["type","track_id","created_at"]] - expected: [["type", "track_id", "created_at"]]. The probe saw a single index, analytics_events_type_track_created_idx, whose index_info is (type, track_id, created_at). INTEGER PRIMARY KEY adds no autoindex. - excludes: Leaving out the CREATE INDEX reads `[]`. An index in a different order, such as (created_at, type, track_id), or an extra UNIQUE constraint that brings an autoindex, reads a different list.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase1.py:49-51 — inserting type 'click' raises sqlite3.IntegrityError matching "CHECK" - expected: IntegrityError("CHECK constraint failed: type IN ('outbound_click', 'page_view')"), as observed in the probe. - excludes: A `type TEXT NOT NULL` with no CHECK accepts 'click'. pytest.raises then fails with DID NOT RAISE, and line 52 would also see a second row.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase1.py:52 — after a row is written and ensure_user_schema runs a third time, STORED reads exactly that one row - expected: [("page_view", None, None, "/about", 1, None, None)]. CREATE TABLE IF NOT EXISTS keeps the row, and the probe showed the CHECK-refused insert is rolled back by `with conn:`. - excludes: A schema function that does `DROP TABLE IF EXISTS analytics_events` before creating it, or plain CREATE TABLE inside a try/except that recreates the table, reads `[]` here. Plain CREATE TABLE without IF NOT EXISTS raises "table already exists" at line 40.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase1.py:71 — after one insert_analytics_event inside a completed `with conn:`, a second connection reads STORED == the passed values - expected: [("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about.html", 1767225600123, "Mozilla/5.0 analytics-test", "https://example.org/about")]. The probe showed this row read back through a second connection after the equivalent INSERT committed. Against the current code the run fails earlier, with AttributeError at line 62. - excludes: Several plausible bugs fail here. Swapping parameters (href into track_id, or user_agent and referer reversed) shows the value in the wrong column. Writing two rows (for example once per type) reads a two-row list. Stamping created_at with now_ms() instead of the passed value reads a different integer. A no-op insert reads `[]`.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase1.py:65 — after insert_analytics_event inside a `with conn:` that raises, a second connection reads STORED == [] - expected: []. The probe showed in_transaction True after the INSERT and `[]` from a reader after the rollback. Line 71 (a written, committed row) is what proves the function writes at all. - excludes: An insert_analytics_event that calls conn.commit() itself, the way record_like and get_or_create_user do, persists the row before the raise. The reader then sees [("page_view", None, None, "/rolled-back", 1, None, None)].

<assertions>
tests/tmp/test_18_about_outbound_click_tracking_phase1.py:42 — after two ensure_user_schema runs, the PRAGMA table_info(analytics_events) names equal exactly ["id","type","track_id","href","page_path","created_at","user_agent","referer"], so an ip_hash or any other address-derived column fails it (current code: [] — observed red here) — C1
tests/tmp/test_18_about_outbound_click_tracking_phase1.py:43 — each column's (name, declared type, notnull, pk) matches the settled DDL: id INTEGER pk, type/page_path/created_at NOT NULL, created_at INTEGER, the rest nullable TEXT (catches a nullable page_path) — C1
tests/tmp/test_18_about_outbound_click_tracking_phase1.py:44 — the table's only index covers ["type","track_id","created_at"] in that order. The index name is not asserted because it is not part of the settled contract — C1
tests/tmp/test_18_about_outbound_click_tracking_phase1.py:49-51 — a raw INSERT with type 'click' raises sqlite3.IntegrityError matching "CHECK" — C1
tests/tmp/test_18_about_outbound_click_tracking_phase1.py:52 — a row written before a third ensure_user_schema run is still the only row afterwards: the run neither drops nor recreates the table, and the refused CHECK insert left nothing — C1 (idempotence)
tests/tmp/test_18_about_outbound_click_tracking_phase1.py:65 — insert_analytics_event inside a `with conn:` that raises leaves zero rows, seen through a second connection. This proves the write is part of the caller's transaction, so an implementation that calls conn.commit() itself fails here (current code: AttributeError, no insert_analytics_event — observed red) — C2
tests/tmp/test_18_about_outbound_click_tracking_phase1.py:71 — one insert_analytics_event inside a completed `with conn:` leaves exactly one row, read through a fresh second connection, equal to the seven passed values in their own columns. Every value is distinct and non-null, so swapping two columns (e.g. user_agent and referer) fails it — C2
</assertions>

<probes>
1) tests/tmp/test_probe_18_p1.py (first version), run as ValidateTests ["tests/tmp/test_probe_18_p1.py","-s"]. It applied the plan's settled DDL twice to a tmp sqlite file (sqlite 3.53.4, Python 3.14.7) and printed:
- `lib.users_store` imports from tests/tmp via sys.path at client/backend; `insert_analytics_event` is absent today; the current ensure_user_schema gives table_info(analytics_events) = [].
- table_info: [(0,'id','INTEGER',0,None,1),(1,'type','TEXT',1,None,0),(2,'track_id','TEXT',0,None,0),(3,'href','TEXT',0,None,0),(4,'page_path','TEXT',1,None,0),(5,'created_at','INTEGER',1,None,0),(6,'user_agent','TEXT',0,None,0),(7,'referer','TEXT',0,None,0)].
- index_list: [(0,'analytics_events_type_track_created_idx',0,'c',0)]; index_info: [(0,1,'type'),(1,2,'track_id'),(2,5,'created_at')].
- A 'click' insert raises "IntegrityError CHECK constraint failed: type IN ('outbound_click', 'page_view')".
- After a rolled-back `with conn:` and then a committed one, a second connection saw only the committed row.

2) The same file, rewritten as a self-check, run as ValidateTests ["tests/tmp/test_probe_18_p1.py","-s","-v"] and then with "-k planned". It monkeypatched users_store and called the checkpoint's two test functions:
- Against the planned DDL plus a plain INSERT (no commit), both pass.
- Against mutants, each one fails at the expected assertion:
  - ip_hash column → names mismatch;
  - nullable page_path → defs mismatch;
  - no index → [] vs expected;
  - no CHECK → "DID NOT RAISE IntegrityError";
  - DROP+CREATE → [] vs surviving row;
  - insert that commits itself → rolled-back row still present;
  - user_agent/referer swapped → value mismatch.

3) The checkpoint against the current tree, ValidateTests ["tests/tmp/test_18_about_outbound_click_tracking_phase1.py"]: 2 failed, at line 42 (`assert [] == ['id','type',...]`) and line 62 (AttributeError: no insert_analytics_event). After that run I edited only the line-52 comment ("second run" → "third run"); no assertion changed.

I have no delete tool, so tests/tmp/test_probe_18_p1.py is still there. It is a throwaway and can be removed once this checkpoint is accepted.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_18_about_outbound_click_tracking_phase1.py` - 4989 characters, inlined in full

```
"""users.db's analytics_events table from ensure_user_schema, and insert_analytics_event writing one row inside the caller's transaction.

- After ensure_user_schema, analytics_events has exactly the eight settled columns with their types, NOT NULLs and primary key; its CHECK refuses an unknown type; it is indexed on (type, track_id, created_at); a second ensure_user_schema keeps the table and its rows.
- An insert_analytics_event whose `with conn:` block raises leaves nothing; one inside a `with conn:` that completes leaves exactly one row with the passed values, read through a second connection.

Called directly on a tmp users.db; no server is involved.
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import lib.users_store as users_store  # noqa: E402

COLUMNS = ["id", "type", "track_id", "href", "page_path", "created_at", "user_agent", "referer"]
# (name, declared type, notnull, pk) as PRAGMA table_info reports the settled DDL.
COLUMN_DEFS = [("id", "INTEGER", 0, 1), ("type", "TEXT", 1, 0), ("track_id", "TEXT", 0, 0), ("href", "TEXT", 0, 0), ("page_path", "TEXT", 1, 0), ("created_at", "INTEGER", 1, 0), ("user_agent", "TEXT", 0, 0), ("referer", "TEXT", 0, 0)]
STORED = "SELECT type, track_id, href, page_path, created_at, user_agent, referer FROM analytics_events ORDER BY id"


def _index_columns(conn: sqlite3.Connection) -> list[list[str]]:
    """Each index on analytics_events as its ordered column names; the index name is not part of the contract."""
    return [[info[2] for info in conn.execute(f"PRAGMA index_info({index[1]})")] for index in conn.execute("PRAGMA index_list(analytics_events)")]


def test_ensure_user_schema_creates_settled_analytics_events_idempotently(tmp_path: Path) -> None:
    """ensure_user_schema, run twice, leaves analytics_events with exactly id, type, track_id, href, page_path, created_at, user_agent, referer (types, NOT NULLs and pk as settled) and an index on (type, track_id, created_at); a third run keeps a row written before it; the CHECK refuses an unknown type."""
    db = tmp_path / "users.db"
    with closing(sqlite3.connect(db)) as conn:
        users_store.ensure_user_schema(conn)
        users_store.ensure_user_schema(conn)

        assert [row[1] for row in conn.execute("PRAGMA table_info(analytics_events)")] == COLUMNS  # C1: exactly the eight settled columns, so no address-derived one
        assert [(row[1], row[2], row[3], row[5]) for row in conn.execute("PRAGMA table_info(analytics_events)")] == COLUMN_DEFS  # C1: each settled column as declared
        assert _index_columns(conn) == [["type", "track_id", "created_at"]]  # C1: the settled index, and only it

        with conn:
            conn.execute("INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES ('page_view', NULL, NULL, '/about', 1, NULL, NULL)")
        users_store.ensure_user_schema(conn)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            with conn:
                conn.execute("INSERT INTO analytics_events (type, page_path, created_at) VALUES ('click', '/about', 2)")  # C1: the CHECK refuses a type outside the two
        assert conn.execute(STORED).fetchall() == [("page_view", None, None, "/about", 1, None, None)]  # C1: the third run neither dropped the table nor its row, and the refused insert left none


def test_insert_analytics_event_writes_one_row_in_callers_transaction(tmp_path: Path) -> None:
    """insert_analytics_event inside a `with conn:` that raises leaves no row; inside one that completes it leaves exactly one row with the passed values, read through a second connection."""
    db = tmp_path / "users.db"
    with closing(sqlite3.connect(db)) as conn:
        users_store.ensure_user_schema(conn)
        with pytest.raises(RuntimeError, match="abort"):
            with conn:
                users_store.insert_analytics_event(conn, "page_view", None, None, "/rolled-back", 1, None, None)
                raise RuntimeError("abort")
        with closing(sqlite3.connect(db)) as reader:
            assert reader.execute(STORED).fetchall() == []  # C2: the insert is the caller's transaction, so a rollback takes it back

        with conn:
            users_store.insert_analytics_event(conn, "outbound_click", "about_patreon", "https://www.patreon.com/x", "/about.html", 1767225600123, "Mozilla/5.0 analytics-test", "https://example.org/about")

    with closing(sqlite3.connect(db)) as reader:
        assert reader.execute(STORED).fetchall() == [("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about.html", 1767225600123, "Mozilla/5.0 analytics-test", "https://example.org/about")]  # C2: exactly one committed row, each value in its own column

```


Gate: satisfied

## 2026-10-02 - Step 7 - Phase 1 (Analytics storage) - red (audit round 1)

`tests/tmp/test_18_about_outbound_click_tracking_phase1.py` exited 1.

```
  tests/tmp/test_18_about_outbound_click_tracking_phase1.py  2 failed                               0.0s
  ---------------------------------------------------------
  total                                                      2 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 1 (Analytics storage) - audit (round 1)

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
test_ensure_user_schema_creates_settled_analytics_events_idempotently fails at line 42:
`PRAGMA table_info(analytics_events)` returns no rows, because ensure_user_schema
(client/backend/lib/users_store.py:10-71) creates no analytics_events table, so
`[] == COLUMNS` is false. test_insert_analytics_event_writes_one_row_in_callers_transaction
errors at line 62 with AttributeError, because lib.users_store defines no
insert_analytics_event. AttributeError is not RuntimeError, so the error is not caught
by `pytest.raises(RuntimeError, match="abort")` at line 60.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_analytics_events.py (NEW). That path does
   not resolve, so it was not read. The verdict comes from the test file and
   client/backend/lib/users_store.py only.
2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`,
   so no conftest was needed and none was looked for.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 5 must_prove, 10 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | after `ensure_user_schema`, `analytics_events` has "exactly the eight settled columns" | :42 | a missing, renamed, reordered or extra column (the column list must match exactly) | CARRIED |
| C1b | must_prove | "none derived from the client address" | :42 | an added `ip` / `ip_hash` / address-derived column, because any ninth column breaks the exact match | CARRIED |
| C2a | must_prove | one `insert_analytics_event` call inside `with conn:` commits | :71 | a write that a second connection can't see after the block completes | CARRIED |
| C2b | must_prove | "exactly one row" | :71 | a duplicate write, or a write plus a companion row, because the full result list is compared | CARRIED |
| C2c | must_prove | "with the given values" | :71 | arguments swapped between columns, `created_at` stamped from the clock instead of the passed value, or a value dropped. All seven values are distinct | CARRIED |
| D1 | docstring | module and :36: each column's "types, NOT NULLs and primary key" as settled | :43 | a wrong declared type, a missing NOT NULL on type/page_path/created_at, or a primary key on the wrong column | CARRIED |
| D2 | docstring | module and :36: "its CHECK refuses an unknown type" | :49-51 | a table with no CHECK, or one that also admits `'click'` | CARRIED |
| D3 | docstring | module and :36: "indexed on (type, track_id, created_at)" | :44 | no index, the wrong column order, or extra indexes | CARRIED |
| D4 | docstring | :36: "run twice" still leaves the settled table | :42-44 (after :39-40) | a CREATE without IF NOT EXISTS (the second run would raise), or a second run that changes the shape | CARRIED |
| D5 | docstring | module "a second ensure_user_schema keeps the table and its rows" / :36 "a third run keeps a row written before it" | :52 | ensure dropping and recreating the table, or deleting its rows | CARRIED |
| D6 | docstring | :52 comment / implied by D2: "the refused insert left none" | :52 | a CHECK that fails after a partial write commits | CARRIED |
| D7 | docstring | module and :56: "`with conn:` block raises leaves nothing" | :65 | `insert_analytics_event` calling `conn.commit()` itself, so the row survives the rollback | CARRIED |
| D8 | docstring | module and :56: "completes … exactly one row with the passed values" | :71 | same as C2a–C2c | CARRIED |
| D9 | docstring | module and :56: "read through a second connection" | :64-65, :70-71 | a check that only sees uncommitted state on the writing connection | CARRIED |
| D10 | docstring | module: "Called directly on a tmp users.db; no server is involved" | :37, :57 (setup, by construction) | a description of the harness, not a behaviour; the file only calls `users_store` against `tmp_path` | CARRIED |
| N1 | name | `ensure_user_schema_creates_settled_analytics_events` | :42-44 | a missing or unsettled table | CARRIED |
| N2 | name | `idempotently` | :42-44, :52 | a second or third run raising, reshaping the table or losing rows | CARRIED |
| N3 | name | `insert_analytics_event_writes_one_row` | :71 | zero or several rows | CARRIED |
| N4 | name | `in_callers_transaction` | :65 | a self-committing insert, which survives the rollback | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_18_about_outbound_click_tracking_phase1.py:68
   `insert_analytics_event(conn, "outbound_click", "about_patreon", "https://www.patreon.com/x", "/about.html", 1767225600123, "Mozilla/5.0 analytics-test", "https://example.org/about")`
   The only committed write through the function fills every nullable field. Two edge cases are untested:
   - `None` for `track_id`, `href`, `user_agent` or `referer`, read back as NULL, is never committed through `insert_analytics_event`. The all-NULL call at :62 is rolled back and never read. The NULL round-trip at :47 uses raw SQL, not the function.
   - A NULL `page_path` or `created_at`, which the NOT NULL constraints should refuse, is never tried.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_18_about_outbound_click_tracking_phase1.py:51
   `conn.execute("INSERT INTO analytics_events (type, page_path, created_at) VALUES ('click', '/about', 2)")`
   Only raw SQL tests the unknown-type refusal. `insert_analytics_event` never gets an unknown type, so the function's own failure mode (raising `IntegrityError` and leaving no row) has no test. It is untested whether the function passes the constraint error through or swallows it.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_analytics_events.py (NEW), which does not exist. Nothing from it was read.
2. client/backend/lib/users_store.py, as read, defines neither an `analytics_events` table in `ensure_user_schema` nor an `insert_analytics_event` function. A repo-wide Grep finds both names only in docs/project/plans/, tests/tmp/ and test output files. Bounds and the abnormal path were therefore judged from the test and the clause text, not from the inputs the code accepts or how it is meant to fail. The "eight settled columns" and their types were taken as the test states them. They were not checked against any implementation or approved DDL.
3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. The only conftest found, tests/active/conftest.py, does not cover tests/tmp/, so no fixture went unread.

## 2026-10-02 - Step 7 - Phase 1 (Analytics storage) - checkpoint outcome (run 1)

`tests/tmp/test_18_about_outbound_click_tracking_phase1.py` exited 0 after the phase landed.

<changes>
### `client/backend/lib/users_store.py`
- `ensure_user_schema` now also creates `analytics_events` with `CREATE TABLE IF NOT EXISTS`. Its columns are `id INTEGER PRIMARY KEY`, `type TEXT NOT NULL CHECK (type IN ('page_view', 'outbound_click'))`, `track_id TEXT`, `href TEXT`, `page_path TEXT NOT NULL`, `created_at INTEGER NOT NULL`, `user_agent TEXT` and `referer TEXT`. No column comes from the client's address.
- It also creates the index `analytics_events_type_track_created_idx` on `(type, track_id, created_at)` with `CREATE INDEX IF NOT EXISTS`. Running it again leaves the table, the index and the rows alone. The docstring now lists the analytics event table.
- New `insert_analytics_event(conn, event_type, track_id, href, page_path, created_at, user_agent, referer)` runs one parameterised `INSERT` and does not commit, so the row belongs to the caller's transaction, the same way `remove_like` and `close_like` work.
- The event-type argument is called `event_type` so it doesn't shadow the built-in `type`. It goes into the `type` column.

### `tests/active/test_analytics_events.py`
Not created. This step was to write production code only, and the checkpoint in `tests/tmp/` already covers the phase. The phase's files list names this durable test as NEW, so it is still waiting to be written or promoted from the checkpoint.

I did not run the checkpoint: the workflow's run is the one that counts.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_18_about_outbound_click_tracking_phase1.py  2 passed                               0.0s
  ---------------------------------------------------------
  total                                                      2 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 2 (Event validator) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`server.py` gains a pure `_validate_analytics_event` (with `_analytics_href_ok` and `_utf8_safe`) that turns any JSON-decoded dict into either the four storable values or an error message, following the settled rules.

- C1 - Each valid event body yields its `(type, track_id, href, page_path)` tuple.
- C2 - Each invalid event body yields an error string without raising.

must_prove:
- C1 - Each valid event body yields its `(type, track_id, href, page_path)` tuple.
- C2 - Each invalid event body yields an error string without raising.

## 2026-10-02 - Step 7 - Phase 2 (Event validator) - self-check (audit round 1, send-back 0)

`tests/tmp/test_18_about_outbound_click_tracking_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase2.py:103 — `client_server._validate_analytics_event(body) == expected` across 9 VALID cases (lines 45-53). Five are outbound_click: the baseline; unknown keys `ip`/`session` with an http href and timestamp 0; track_id and page_path at length 1; track_id 64, href 2048 and page_path 256 at the upper bounds; and `HTTPS://Example.ORG/Path` returned unchanged. Four are page_view: track_id and href absent, both null, track_id null with href absent, and href null with unknown keys. - expected: For outbound_click, the exact 4-tuple `("outbound_click", track_id, href, page_path)` with each value as sent, e.g. `("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about")`. For page_view, `("page_view", None, None, page_path)`. These values are the plan's contract (plan line 817, docstring line 820). They could not be observed because the function does not exist yet: the run shows `AttributeError: module 'server' has no attribute '_validate_analytics_event'` at line 103 for all 9 cases. The probe confirmed the input premises: lengths 2048/64/256, and `urlsplit('HTTPS://Example.ORG/Path')` parses with scheme `https`. - excludes: Each of these goes red at line 103: a stub or hard-coded tuple (only one case matches); a validator that lower-cases or normalises href (the upper-case case reads `https://example.org/Path`); a `<` instead of `<=` on a length cap (the max-lengths case returns an error string); rejecting unknown keys (both unknown-key cases return a str); treating a present-but-null track_id/href on page_view as a violation (view-both-null returns a str); and returning the body's null values or a different order instead of `(type, None, None, page_path)`.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110 — `isinstance(result, str) and result` across 40 INVALID bodies (lines 57-96), each passed directly at line 109, so any raise fails the test. Each body is the C1 baseline (`_click()`/`_view()`, which line 103 asserts valid) with one key changed or dropped. The cases cover type (missing, unknown, wrong case, list), track_id (missing, null on click, upper-case, empty, 65 chars, hyphen, trailing `\n`, int), href (missing, null on click, mailto, javascript, `https://`, relative, `http://[::1`, 2049, 2052, int, lone surrogate), page_path (missing, empty, no slash, 257, int, lone surrogate, no slash on page_view), timestamp (missing, str, float, bool, -1, null, missing on page_view), and page_view carrying a track_id or an href. - expected: A non-empty `str` (the plan's error message) for every one of the 40 bodies, with no exception. This could not be observed against production because the function does not exist yet: the run shows the same AttributeError at line 109 for all 40. The probe observed the premises that make these cases discriminating. `urlsplit('http://[::1')` raises `ValueError: Invalid IPv6 URL`. `urlsplit` accepts `'https://x.y/\ud800'`, but sqlite3 binding it raises `UnicodeEncodeError ... surrogates not allowed` (likewise for `'/\ud800'`). `re.match(r'^[a-z0-9_]{1,64}$', 'abc\n')` is True while `fullmatch` is False. `isinstance(True, int)` is True. `'https://'`, `'mailto:a@b.c'`, `'javascript:alert(1)'` and `'/relative'` all give hostname None. The lengths are 2049, 2052, 257 and 65. - excludes: Each of these goes red at line 109 or 110: accepting everything (returns a tuple, not a str); checking set membership before the str check (the list-type case raises TypeError); calling urlsplit without catching ValueError (`http://[::1` raises); `match` with `$` (`abc\n` returns a tuple); letting bool through as int (`timestamp=True` returns a tuple); an off-by-one on a cap (the 65/2049/257 cases return a tuple); no UTF-8 safety check (the surrogate cases return a tuple, which would later crash the sqlite bind); skipping the extra-field check on page_view (view-with-track-id/href return a tuple); and returning an empty string or None as the error (`result` is falsy or not a str).

<assertions>
tests/tmp/test_18_about_outbound_click_tracking_phase2.py:103 - `client_server._validate_analytics_event(body) == expected` over 9 literal cases. Five are outbound_click: the baseline; unknown keys plus an http href and timestamp 0; track_id and page_path at length 1; track_id 64, href 2048 and page_path 256 at the length bounds; an upper-case `HTTPS://` href returned unchanged. Four are page_view: track_id/href both absent, both null, null+absent, and null with unknown keys, each giving `(page_view, None, None, page_path)`. The expected tuples are written out by hand, not computed. A stub, a hard-coded tuple, a validator that normalises href or page_path, or one rejecting an exact bound or an extra key fails here - C1
tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110 - `isinstance(result, str) and result` over 40 invalid bodies, each called directly, so a raise fails the test. Each body is the C1 baseline with one key changed or dropped, so the C1 baseline case proves every rejection is down to that one key. The cases: `{}`; type missing, `"click"`, `"PAGE_VIEW"` and `["page_view"]`. track_id missing, null on a click, upper-case, empty, 65 chars, `a-b`, `abc\n` and int. href missing, null on a click, mailto, javascript, `https://`, `/relative`, `http://[::1`, 2049 chars, 2052 chars, int and a lone surrogate. page_path missing, empty, `about`, 257 chars, int, a lone surrogate, and a page_view without a leading slash. timestamp missing, `"1"`, `1.0`, `true`, `-1`, null, and missing on a page_view. A page_view carrying a track_id, and one carrying an href. A validator that accepts everything, uses `match`+`$`, skips the str check before the set lookup, does not catch urlsplit's ValueError, lets bool through as int, is off by one on a length bound, or skips the checks on page_view fails here - C2
</assertions>

<probes>
tests/tmp/probe_18_phase2_premises.py run with ValidateTests ["tests/tmp/probe_18_phase2_premises.py", "-s"]; output read from tests/last_test_output.txt (Python 3.14.7). It printed:
- `urlsplit('http://[::1')` and its `.hostname` both RAISE ValueError "Invalid IPv6 URL".
- `urlsplit('https://').hostname` is None.
- `urlsplit('HTTPS://x.y')` gives ('https', 'x.y').
- mailto gives ('mailto', None), javascript gives ('javascript', None) and `/relative` gives ('', None).
- `json.loads('"https://x.y/\\ud800"')` is a 13-char str; urlsplit accepts it as ('https', 'x.y'), but `.encode('utf-8')` RAISES UnicodeEncodeError. So only the UTF-8 check can reject it. `json.loads('"/\\ud800"')` also RAISES on encode.
- `re.fullmatch('[a-z0-9_]{1,64}', 'abc\n')` is None, while `re.match(...'$', 'abc\n')` matches.
- `['page_view'] in frozenset(...)` RAISES TypeError (unhashable).
- JSON `1.0` decodes as float, and JSON `true` is an instance of int.
- The lengths are 2048, 2049, 2052 (the draft's href) and 257.
Checkpoint red run: ValidateTests ["tests/tmp/test_18_about_outbound_click_tracking_phase2.py"] gave 49 failed. Every failure is `AttributeError: module 'server' has no attribute '_validate_analytics_event'`, so collection and the import work and the red comes from the missing code alone. The probe file tests/tmp/probe_18_phase2_premises.py is still on disk: I have no delete tool, so it needs removing.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_18_about_outbound_click_tracking_phase2.py` - 7101 characters, inlined in full

```
"""server._validate_analytics_event over JSON-decoded event bodies.

- A valid outbound_click returns exactly its (type, track_id, href, page_path) as sent, at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256), with an upper-case scheme and with unknown keys present; a valid page_view returns (page_view, None, None, page_path) with track_id and href absent, both null, or one of each, and with unknown keys present.
- Each body that breaks one rule (type, track_id, href, page_path, timestamp, or a page_view carrying a track_id or href) returns a non-empty error string and does not raise; that includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one.

Each invalid body is the valid baseline with one key changed or removed; the baseline is itself asserted valid, so every rejection is down to that one key.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402

MISSING = object()
# Lone surrogates as json.loads yields them from a beacon body: str values that urlsplit accepts but sqlite3 cannot bind.
SURROGATE_HREF = json.loads('"https://x.y/\\ud800"')
SURROGATE_PATH = json.loads('"/\\ud800"')


def _click(**overrides: Any) -> dict[str, Any]:
    """A valid outbound_click body with `overrides` applied; MISSING drops the key."""
    body = {"type": "outbound_click", "track_id": "about_patreon", "href": "https://www.patreon.com/x", "page_path": "/about", "timestamp": 1767225600123}
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not MISSING}


def _view(**overrides: Any) -> dict[str, Any]:
    """A valid page_view body with `overrides` applied; MISSING drops the key."""
    body = {"type": "page_view", "page_path": "/about", "timestamp": 1767225600123}
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not MISSING}


VALID = [
    pytest.param(_click(), ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about"), id="click-baseline"),
    pytest.param(_click(track_id="about_github", href="http://github.com/peertube-browser?tab=repositories", page_path="/about.html", timestamp=0, ip="203.0.113.18", session={"id": 1}), ("outbound_click", "about_github", "http://github.com/peertube-browser?tab=repositories", "/about.html"), id="click-unknown-keys-http-timestamp-0"),
    pytest.param(_click(track_id="a", page_path="/"), ("outbound_click", "a", "https://www.patreon.com/x", "/"), id="click-min-lengths"),
    pytest.param(_click(track_id="z9_" * 21 + "a", href="https://x.y/" + "a" * 2036, page_path="/" + "b" * 255), ("outbound_click", "z9_" * 21 + "a", "https://x.y/" + "a" * 2036, "/" + "b" * 255), id="click-max-lengths"),
    pytest.param(_click(href="HTTPS://Example.ORG/Path"), ("outbound_click", "about_patreon", "HTTPS://Example.ORG/Path", "/about"), id="click-uppercase-scheme-verbatim"),
    pytest.param(_view(), ("page_view", None, None, "/about"), id="view-absent"),
    pytest.param(_view(track_id=None, href=None, page_path="/about/"), ("page_view", None, None, "/about/"), id="view-both-null"),
    pytest.param(_view(track_id=None, page_path="/about.html"), ("page_view", None, None, "/about.html"), id="view-track-id-null-href-absent"),
    pytest.param(_view(href=None, referrer="https://example.org/", extra=[1]), ("page_view", None, None, "/about"), id="view-href-null-unknown-keys"),
]

INVALID = [
    pytest.param({}, id="empty-object"),
    pytest.param(_click(type=MISSING), id="type-missing"),
    pytest.param(_click(type="click"), id="type-unknown"),
    pytest.param(_click(type="PAGE_VIEW"), id="type-wrong-case"),
    pytest.param(_click(type=["page_view"]), id="type-list"),
    pytest.param(_click(track_id=MISSING), id="track-id-missing"),
    pytest.param(_click(track_id=None), id="track-id-null-on-click"),
    pytest.param(_click(track_id="About_Patreon"), id="track-id-uppercase"),
    pytest.param(_click(track_id=""), id="track-id-empty"),
    pytest.param(_click(track_id="a" * 65), id="track-id-65"),
    pytest.param(_click(track_id="a-b"), id="track-id-hyphen"),
    pytest.param(_click(track_id="abc\n"), id="track-id-trailing-newline"),
    pytest.param(_click(track_id=5), id="track-id-int"),
    pytest.param(_click(href=MISSING), id="href-missing"),
    pytest.param(_click(href=None), id="href-null-on-click"),
    pytest.param(_click(href="mailto:a@b.c"), id="href-mailto"),
    pytest.param(_click(href="javascript:alert(1)"), id="href-javascript"),
    pytest.param(_click(href="https://"), id="href-no-host"),
    pytest.param(_click(href="/relative"), id="href-relative"),
    pytest.param(_click(href="http://[::1"), id="href-malformed-ipv6"),
    pytest.param(_click(href="https://x.y/" + "a" * 2037), id="href-2049"),
    pytest.param(_click(href="https://x.y/" + "a" * 2040), id="href-2052"),
    pytest.param(_click(href=42), id="href-int"),
    pytest.param(_click(href=SURROGATE_HREF), id="href-lone-surrogate"),
    pytest.param(_click(page_path=MISSING), id="page-path-missing"),
    pytest.param(_click(page_path=""), id="page-path-empty"),
    pytest.param(_click(page_path="about"), id="page-path-no-slash"),
    pytest.param(_click(page_path="/" + "a" * 256), id="page-path-257"),
    pytest.param(_click(page_path=7), id="page-path-int"),
    pytest.param(_click(page_path=SURROGATE_PATH), id="page-path-lone-surrogate"),
    pytest.param(_view(page_path="about"), id="view-page-path-no-slash"),
    pytest.param(_click(timestamp=MISSING), id="timestamp-missing"),
    pytest.param(_click(timestamp="1"), id="timestamp-str"),
    pytest.param(_click(timestamp=1.0), id="timestamp-float"),
    pytest.param(_click(timestamp=True), id="timestamp-bool"),
    pytest.param(_click(timestamp=-1), id="timestamp-negative"),
    pytest.param(_click(timestamp=None), id="timestamp-null"),
    pytest.param(_view(timestamp=MISSING), id="view-timestamp-missing"),
    pytest.param(_view(track_id="about_x"), id="view-with-track-id"),
    pytest.param(_view(href="https://x.y"), id="view-with-href"),
]


@pytest.mark.parametrize(("body", "expected"), VALID)
def test_valid_event_returns_its_storable_values(body: dict[str, Any], expected: tuple[str, str | None, str | None, str]) -> None:
    """A valid outbound_click or page_view body returns exactly (type, track_id, href, page_path), with track_id and href None on a page_view."""
    assert client_server._validate_analytics_event(body) == expected  # C1


@pytest.mark.parametrize("body", INVALID)
def test_invalid_event_returns_error_string(body: dict[str, Any]) -> None:
    """A body breaking one validation rule returns a non-empty error string rather than raising or returning values."""
    result = client_server._validate_analytics_event(body)
    assert isinstance(result, str) and result  # C2

```


Gate: satisfied

## 2026-10-02 - Step 7 - Phase 2 (Event validator) - red (audit round 1)

`tests/tmp/test_18_about_outbound_click_tracking_phase2.py` exited 1.

```
  tests/tmp/test_18_about_outbound_click_tracking_phase2.py  49 failed                              0.0s
  ---------------------------------------------------------
  total                                                      49 failed                              0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 2 (Event validator) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D10

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this, per the `<constraints>` fallback (rules/shape.md). Nearest is `absence-only-assertion <how_to_spot>` bullet 3. Located at tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110
   assert isinstance(result, str) and result  # C2
   This assertion is positive, so `absence-only-assertion` does not apply as written. Even so, `test_invalid_event_returns_error_string` on its own goes green on a stub that rejects every body (`return "not implemented"`). The positive control is the `click-baseline` / `view-absent` cases at :45 and :50, which run in a different test function (:103). The file as a whole still fails that stub, because C1 goes red. But if the C2 function is ever run or kept on its own, it is no longer a gate. You could assert the baseline is accepted inside the C2 function as well, before the rejection, so the control stays with it.

PREDICTED FAILURE
All 49 cases fail with `AttributeError: module 'server' has no attribute '_validate_analytics_event'`, because `client/backend/server.py` does not define that symbol yet. The 9 VALID cases fail at line 103 on `client_server._validate_analytics_event(body) == expected`. The 40 INVALID cases fail at line 109 on `result = client_server._validate_analytics_event(body)`.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist on disk, so it was not read. This test does not import it.
2. `client/backend/server.py` was searched for `_validate_analytics_event` and analytics symbols, with no match. It was not otherwise read. The stub question was answered from the assertion form at :103 and :110 against the 9 VALID and 40 INVALID cases written out by hand:
   - A hard-coded tuple matches at most one VALID case.
   - Accept-all fails C2.
   - Reject-all fails C1.
   - The uppercase-scheme and max-length cases separate normalising and off-by-one implementations.
3. Anti-pattern pass (rules/shape.md): no `.md` is read and no section is extracted, so `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep` do not apply. Expected values are literals checked against a production call, not a constant or a re-derivation, so `hardcoded-spec-mirror` and `tautological-assertion` do not apply. A production symbol sits between input and expected value, so `echoed-literal` does not apply. There are many differing inputs, so `single-value-pin` does not apply. Ladder pass: the test is at rung 1 (it calls the function directly), which is the highest rung, so no downshift comment is needed.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (16 clauses: 2 must_prove, 12 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1 | must_prove | each valid body yields its `(type, track_id, href, page_path)` tuple | :103 | a wrong field, wrong order, a missing member, a changed value (e.g. lower-cased scheme), or an error string on a valid body | CARRIED |
| C2 | must_prove | each invalid body yields an error string without raising | :110 | raising (pytest fails the case), returning a tuple or None, returning `""` | CARRIED |
| D1 | docstring | valid outbound_click returns "exactly its (type, track_id, href, page_path) as sent" | :103 | a validator that normalises or reorders values | CARRIED |
| D2 | docstring | "at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256)" | :103 (params :47, :48) | an off-by-one cap that rejects a value at the limit. :48 gives track_id 64, href 12+2036=2048 and page_path 256 chars | CARRIED |
| D3 | docstring | "with an upper-case scheme" | :103 (param :49) | a case-sensitive scheme check, or a scheme folded to lower case | CARRIED |
| D4 | docstring | click "with unknown keys present" | :103 (param :46) | rejecting extra keys such as `ip` or `session` | CARRIED |
| D5 | docstring | page_view returns (page_view, None, None, page_path) with track_id/href "absent, both null, or one of each" | :103 (params :50–:53) | a KeyError on absent keys, rejecting explicit nulls, or echoing a value where None belongs | CARRIED |
| D6 | docstring | page_view "with unknown keys present" | :103 (param :53) | rejecting `referrer` or `extra` on a page_view | CARRIED |
| D7 | docstring | a body breaking one rule (type, track_id, href, page_path, timestamp, page_view with track_id/href) "returns a non-empty error string and does not raise" | :110 | accepting any listed violation, or raising on it | CARRIED |
| D8 | docstring | "includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one" | :110 (params :61, :80, :86, :76, :66, :77, :84) | an unhashable-type crash, an unchecked surrogate, urlsplit's ValueError escaping, or caps that are one too loose | CARRIED |
| D9 | docstring | "the baseline is itself asserted valid" | :103 (params :45, :50) | a baseline that would be rejected anyway, which would make each rejection meaningless | CARRIED |
| D10 | docstring | "Each invalid body is the valid baseline with one key changed or removed … every rejection is down to that one key" | :110 | holds for 39 of the 40 INVALID params. `{}` at :57 is not a one-key change, so for that case the sentence claims something the data does not do | UNCARRIED |
| D11 | docstring (:102) | "with track_id and href None on a page_view" | :103 | a page_view returning a supplied or default track_id or href | CARRIED |
| D12 | docstring (:108) | "rather than raising or returning values" | :110 | returning the tuple, or raising | CARRIED |
| N1 | name | "valid event returns its storable values" | :103 | anything other than the exact 4-tuple | CARRIED |
| N2 | name | "invalid event returns error string" | :110 | a non-string or empty result | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:57
   `pytest.param({}, id="empty-object"),`
   D10 is UNCARRIED for this case. The module docstring (:6) says every invalid body is the baseline with one key changed or removed. `{}` removes every key, so this rejection cannot be traced to one key. Either move the empty object out from under that sentence, or narrow the sentence to name it as the exception.
2. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:56
   The module docstring (:1) frames the input as "JSON-decoded event bodies". json.loads can also return a non-object (`null`, a list, a string or a number), and no such body is tested. Whether the function must handle one depends on a contract that cannot be read, because the function does not exist yet (see NOT ASSESSED). If the caller passes json.loads output straight in, add a non-object body to INVALID.
3. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:87
   For a page_view, the only page_path edge tested is the missing slash. The minimum (`"/"`), 257 characters and a lone surrogate are tested only on outbound_click (:47, :84, :86). This matters if the page_view path is validated by a separate branch.

OBSERVATIONS
none

NOT ASSESSED
1. `client/backend/server.py` does not define `_validate_analytics_event` (Grep found no match, and the file has no analytics, outbound or page_view code at all). That means:
   - The bounds and abnormal-path checks were judged from the test's docstring alone, not from the accepted-input contract in code.
   - Whether the symbol named at :103 and :110 will exist could not be checked.
2. `code_under_test` lists `tests/active/test_analytics_events.py`. That path does not resolve (FileNotFoundError), so it was not read.
3. The phase's `<checkpoint>` seam text was not supplied. The surface pass checked that the test makes real functional assertions on the return value of the function `must_prove` describes. It did not check that this function is the seam the phase named.

## 2026-10-02 - Step 7 - Phase 2 (Event validator) - self-check (audit round 2, send-back 0)

`tests/tmp/test_18_about_outbound_click_tracking_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase2.py:103 — `client_server._validate_analytics_event(body) == expected` over the 9 VALID params (5 outbound_click, 4 page_view), with the expected tuples written out by hand. - expected: The exact 4-tuple for each case. For example, ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about") for the baseline, ("outbound_click", "about_patreon", "HTTPS://Example.ORG/Path", "/about") for the upper-case scheme, and ("page_view", None, None, "/about") for the page_view with both keys absent. - excludes: A validator that lower-cases the scheme returns "https://Example.ORG/Path". One with an off-by-one cap returns an error string at track_id 64, href 2048 or page_path 256. One that rejects unknown keys returns an error string on the `ip`/`session` and `referrer`/`extra` cases. One that indexes body["track_id"] on a page_view raises KeyError. A hard-coded tuple matches at most one case. Every one of these reads != expected.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110 — `isinstance(result, str) and result` over the 40 INVALID params. Each is called directly, so a raise fails the case. - expected: A non-empty str for every invalid body. - excludes: Missing the str check before the set lookup raises TypeError on `["page_view"]`. Not catching urlsplit's error raises ValueError on `http://[::1`. Skipping the UTF-8 check returns the tuple for lone surrogates. Using `re.match` with `$` accepts `abc\n`. Letting bool through as int accepts `true`. A cap that is one too loose accepts 65, 2049 or 257 characters. Skipping the checks on page_view accepts a page_view that carries a track_id or href. Accept-all returns tuples. Each of these reads a tuple, or raises, where a str is required.

<exemptions>
none
</exemptions>

<items>
<item id="D10">
<disposition>justified</disposition>
<what>I narrowed the prose to what the data does. The module docstring at :6 now reads: "Each invalid body except the empty object `{}` is the valid baseline with one key changed or removed; the baseline is itself asserted valid, so every such rejection is down to that one key. `{}` lacks every key at once and only shows that a body with nothing in it is rejected." The one-key claim now covers only the 39 params that are one-key changes. The `{}` case at :57 stays in INVALID and is described for what it is: a whole-body rejection, still carried by :110 (`isinstance(result, str) and result`), which fails a validator that raises KeyError on an empty dict or accepts it. No assertion or param changed.</what>
</item>
</items>

<findings_addressed>
Neither auditor raised a CRITICAL. Claim recommendation 1 (D10, `{}` at :57): taken. I narrowed the docstring sentence at :6 to name `{}` as the exception (see item D10). Claim recommendation 2 (non-object JSON bodies): not taken. The caller's contract for whether non-dict json.loads output reaches this function is not written yet, so adding a case now would mean guessing it. Claim recommendation 3 (page_view page_path edges): not taken. The ledger does not name it, and the C2 params already cover page_path bounds on outbound_click and the missing slash on page_view. Shape recommendation 1 (positive control inside the C2 function): not taken. C1's baseline cases at :45 and :50 run in the same file and gate together with it, and a reject-all stub turns those red.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase2.py:103 — `client_server._validate_analytics_event(body) == expected` over the 9 VALID params (5 outbound_click, 4 page_view), with the expected tuples written out by hand.</assertion>
<expected>The exact 4-tuple for each case. For example, ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about") for the baseline, ("outbound_click", "about_patreon", "HTTPS://Example.ORG/Path", "/about") for the upper-case scheme, and ("page_view", None, None, "/about") for the page_view with both keys absent.</expected>
<wrong_implementation>A validator that lower-cases the scheme returns "https://Example.ORG/Path". One with an off-by-one cap returns an error string at track_id 64, href 2048 or page_path 256. One that rejects unknown keys returns an error string on the `ip`/`session` and `referrer`/`extra` cases. One that indexes body["track_id"] on a page_view raises KeyError. A hard-coded tuple matches at most one case. Every one of these reads != expected.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110 — `isinstance(result, str) and result` over the 40 INVALID params. Each is called directly, so a raise fails the case.</assertion>
<expected>A non-empty str for every invalid body.</expected>
<wrong_implementation>Missing the str check before the set lookup raises TypeError on `["page_view"]`. Not catching urlsplit's error raises ValueError on `http://[::1`. Skipping the UTF-8 check returns the tuple for lone surrogates. Using `re.match` with `$` accepts `abc\n`. Letting bool through as int accepts `true`. A cap that is one too loose accepts 65, 2049 or 257 characters. Skipping the checks on page_view accepts a page_view that carries a track_id or href. Accept-all returns tuples. Each of these reads a tuple, or raises, where a str is required.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Both assertions are positive. :103 requires an exact tuple, so deleting the code under test turns all 9 cases red. :110 requires a non-empty str, so a deleted function fails all 40 cases with AttributeError. A reject-all stub is caught by :103.
2. No. Every expected tuple is a hand-written literal compared against the production call. The test does no normalising or validation of its own. Deleting the scheme or length handling in `_validate_analytics_event` (the function does not exist yet, so I cannot cite a line) turns :103 red. Deleting any single rule check turns its :110 case red.
3. No. There are 9 valid and 40 invalid inputs, and nothing is pinned against a sibling value from the same source.
4. No. There are no doubles; the test imports the real `server` module.
5. Yes. Only the module docstring changed in this round. Imports, names and helpers are untouched, and the line count is the same (the edit replaced one line with one line), so the 49 cases (9 + 40) are unchanged.
6. Yes. Every premise the expectations rest on comes from the earlier probe run (Python 3.14.7): urlsplit's ValueError on `http://[::1`, the surrogate encode failure, the `re.match`/`$` behaviour, the unhashable list, bool being an int, and the length counts. This round adds no new expected values.
7. Yes. The earlier red run gave 49 failed, all with `AttributeError: module 'server' has no attribute '_validate_analytics_event'`. This round's edit was prose inside the docstring only, so it cannot affect collection or the import. I did not run the test again; the workflow's run will confirm it. Separately, the earlier probe file tests/tmp/probe_18_phase2_premises.py is still on disk and needs deleting, because I have no delete tool.

Nothing was rewritten in response to these questions, because none came out yes.
</answers>

Gate: satisfied

## 2026-10-02 - Step 7 - Phase 2 (Event validator) - red (audit round 2)

`tests/tmp/test_18_about_outbound_click_tracking_phase2.py` exited 1.

```
  tests/tmp/test_18_about_outbound_click_tracking_phase2.py  49 failed                              0.0s
  ---------------------------------------------------------
  total                                                      49 failed                              0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 2 (Event validator) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this; the nearest is absence-only-assertion <how_to_spot>, third bullet
   (rules/shape.md). tests/tmp/test_18_about_outbound_click_tracking_phase2.py:110
   assert isinstance(result, str) and result  # C2
   This assertion checks for something rather than its absence, so the anti-pattern does
   not apply. But test_invalid_event_returns_error_string alone passes against a stub that
   always returns the same string (e.g. `return "invalid"`). Nothing in this test
   function shows that any one of the INVALID bodies was rejected for its changed key.
   That proof comes from test_valid_event_returns_its_storable_values (line 103), which
   checks the click-baseline and view-absent bodies are valid. As a file the gate holds:
   that stub fails every VALID case. If the test is ever run alone with `-k` or split
   across files, the C2 gate would pass on a stub. Consider asserting the valid baseline
   inside the C2 test too, or tying each error string to the key that caused it.

PREDICTED FAILURE
Every parametrized case fails at line 103 (C1) and line 109 (C2) with
AttributeError: module 'server' has no attribute '_validate_analytics_event'.
client/backend/server.py does not yet define that symbol: grepping for
`_validate_analytics_event` and `analytics` finds nothing.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_analytics_events.py, but that path does not
   exist and was not read.
2. client/backend/server.py exists but does not yet define `_validate_analytics_event`.
   So the stub question was answered from the assertion form alone. In brief:
   - Rung 1 is right: the test calls the function directly and compares against literal
     tuples.
   - The outputs vary with the inputs across several track_id, href and page_path values,
     so a hard-coded return fails.
   - Each length limit is tested both at the limit, which must pass, and one past it,
     which must fail, so an off-by-one fails.
   - A pass-through implementation with no validation returns a tuple, not a string, for
     every INVALID body, so it fails C2.
   - A stub that raises NotImplementedError fails both tests.
3. No fixtures_path was supplied. The test defines its own helpers and uses no pytest
   fixtures. The only conftest found is tests/active/conftest.py, which does not cover
   tests/tmp/.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (16 clauses: 2 must_prove, 12 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1 | must_prove | each valid body yields its `(type, track_id, href, page_path)` tuple | :103 | a wrong field, a wrong order, a missing member, a changed value (e.g. a lower-cased scheme), or an error string on a valid body. The 9 expected tuples at :45–:53 are written out by hand | CARRIED |
| C2 | must_prove | each invalid body yields an error string without raising | :110 | raising (pytest errors the case), returning a tuple or None, or returning `""` | CARRIED |
| D1 | docstring | valid outbound_click returns "exactly its (type, track_id, href, page_path) as sent" | :103 | a validator that normalises or reorders values | CARRIED |
| D2 | docstring | "at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256)" | :103 (params :47, :48) | an off-by-one cap that rejects a value at the limit. At :48, `"z9_"*21+"a"` is 64 chars, `"https://x.y/"+"a"*2036` is 2048 and `"/"+"b"*255` is 256. At :47, track_id and page_path are 1 char | CARRIED |
| D3 | docstring | "with an upper-case scheme" | :103 (param :49) | a case-sensitive scheme check, or a scheme folded to lower case in the returned href | CARRIED |
| D4 | docstring | click "with unknown keys present" | :103 (param :46) | rejecting extra keys such as `ip` or `session` | CARRIED |
| D5 | docstring | page_view returns (page_view, None, None, page_path) with track_id/href "absent, both null, or one of each" | :103 (params :50–:53) | a KeyError on absent keys, rejecting explicit nulls, or echoing a value where None belongs | CARRIED |
| D6 | docstring | page_view "with unknown keys present" | :103 (param :53) | rejecting `referrer` or `extra` on a page_view | CARRIED |
| D7 | docstring | a body breaking one rule (type, track_id, href, page_path, timestamp, page_view with track_id/href) "returns a non-empty error string and does not raise" | :110 | accepting any listed violation, or raising on it | CARRIED |
| D8 | docstring | "includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one" | :110 (params :61, :80, :86, :76, :66, :77, :84) | a crash on an unhashable type, an unchecked surrogate, urlsplit's ValueError escaping, or caps that are one too loose (65, 2049, 257) | CARRIED |
| D9 | docstring | "the baseline is itself asserted valid" | :103 (params :45, :50) | a baseline that would be rejected anyway, which would make each rejection meaningless | CARRIED |
| D10 | docstring | "Each invalid body except the empty object `{}` is the valid baseline with one key changed or removed … every such rejection is down to that one key" (narrowed at :6) | :110 | the 39 params at :58–:96 are each `_click(...)` or `_view(...)` with exactly one override, so a validator that rejects for a reason other than that key can only do so by also rejecting a baseline, and :103 catches that. `{}` at :57 is now excluded by the sentence itself | CARRIED |
| D11 | docstring (:102) | "with track_id and href None on a page_view" | :103 | a page_view returning a supplied or default track_id or href | CARRIED |
| D12 | docstring (:108) | "rather than raising or returning values" | :110 | returning the tuple, or raising | CARRIED |
| N1 | name | "valid event returns its storable values" | :103 | anything other than the exact 4-tuple | CARRIED |
| N2 | name | "invalid event returns error string" | :110 | a non-string or empty result | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:6
   D10 moved from UNCARRIED to CARRIED because the author narrowed the prose. No assertion was added. The sentence now carves out `{}`. Nothing in the test changed: no assertion and no param. The record should show it this way.
2. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:6
   The narrowing added a new sentence that no ledger row names: "`{}` lacks every key at once and only shows that a body with nothing in it is rejected." The `{}` param at :57 carries it through :110. This is recorded only, not a defect.
3. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase2.py:95-96
   The D10 wording says "one key changed or removed". `view-with-track-id` (:95) and `view-with-href` (:96) *add* a key that the page_view baseline at :39 does not have. The one-key reasoning still holds, but the wording does not name additions. If the prose is touched again, "changed, added or removed" would match the data.
4. `client_server._validate_analytics_event` is not defined anywhere in client/backend/server.py: Grep found no match, and the file has no analytics symbols at all. The test asserts against a symbol that does not exist yet. That fits a red-first checkpoint, but it means the claim audit cannot check the test's bounds against the code's actual caps or its contract for abnormal input (see NOT ASSESSED).

NOT ASSESSED
1. client/backend/server.py does not define `_validate_analytics_event`, so I could not read the input domain and failure behaviour of the code under test. The bounds and normal-and-abnormal-paths judgements (the 64/2048/256 caps, the timestamp rules and the scheme set) come from the test's own docstring and params only. They were not checked against the implementation.
2. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist on disk, so I did not read it. The test under audit does not import it.

## 2026-10-02 - Step 7 - Phase 2 (Event validator) - checkpoint outcome (run 1)

`tests/tmp/test_18_about_outbound_click_tracking_phase2.py` exited 0 after the phase landed.

<changes>
### `client/backend/server.py`
- New imports: `re`, and `urlsplit` added to the existing `urllib.parse` import.
- Four new constants after `BLOCK_REFERENCE_MAX_LENGTH`, in the style of the ones around them: `ANALYTICS_EVENT_TYPES = frozenset(("outbound_click", "page_view"))`, `ANALYTICS_TRACK_ID_PATTERN = re.compile(r"[a-z0-9_]{1,64}")`, `ANALYTICS_HREF_MAX_LENGTH = 2048` and `ANALYTICS_PAGE_PATH_MAX_LENGTH = 256`.
- New pure function `_validate_analytics_event(body)`, placed after `_parse_client_likes` and taken from the plan's settled code. It returns `(type, track_id, href, page_path)` for a valid event, or an error message for a 400. It never raises. The checks run in this order:
  - `type` must be a `str` in the two-value set. The `str` check comes first because a list `type` can't be hashed for the set lookup.
  - `page_path` must be a `str` of 1–256 characters that starts with `/` and can be encoded as UTF-8.
  - `timestamp` must be a non-negative `int`. `bool` and `float` are rejected. The value is checked and then thrown away.
  - On a `page_view`, `track_id` and `href` must be absent or null, and the result is `(page_view, None, None, page_path)`.
  - On an `outbound_click`, `track_id` must match the pattern with `fullmatch`, so a trailing newline is rejected, and `href` must pass `_analytics_href_ok`.
  - Valid values come back exactly as sent, and unknown keys are ignored.
- New `_analytics_href_ok(href)`: `href` must be a `str` of at most 2048 characters that encodes as UTF-8. `urlsplit` must give a scheme of `http` or `https` and a non-empty `hostname`. The scheme check ignores case because `urlsplit` lowercases it, but the original `href` is what gets stored. A `ValueError` from `urlsplit` or `.hostname` (for example `http://[::1`) makes it return False.
- New `_utf8_safe(value)`: returns False when `str.encode("utf-8")` raises `UnicodeEncodeError`. That catches lone surrogates from `json.loads`, which sqlite3 cannot bind.
- The route, handler method and `insert_analytics_event` import are not added here. They belong to a later phase.

### `tests/active/test_analytics_events.py`
Not created and not edited. It doesn't exist in the worktree: Phase 1 left it unwritten and recorded that. This step asks for production code only, and the checkpoint in `tests/tmp/` covers this phase. The durable test is still waiting to be written or promoted from the checkpoints.

I did not run the checkpoint, because the workflow's run is the one that counts.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_18_about_outbound_click_tracking_phase2.py  49 passed                              0.0s
  ---------------------------------------------------------
  total                                                      49 passed                              0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 3 (Analytics route) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`POST /api/analytics/event` in `_serve_post` stores each accepted event as one server-stamped row in `analytics_events`, and stores nothing for a request it refuses.

- C1 - A valid event of either type, with any Content-Type, gets 204 and adds one row whose `created_at`, `user_agent` and `referer` come from the server.
- C2 - A refused POST, whether 400 for an invalid body or 429 over the route limit, adds no row.

must_prove:
- C1 - A valid event of either type, with any Content-Type, gets 204 and adds one row whose `created_at`, `user_agent` and `referer` come from the server.
- C2 - A refused POST, whether 400 for an invalid body or 429 over the route limit, adds no row.

## 2026-10-02 - Step 7 - Phase 3 (Analytics route) - self-check (audit round 1, send-back 0)

`tests/tmp/test_18_about_outbound_click_tracking_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:121 — `(status, body) == (204, b"")` for each of the 5 ACCEPTED cases: outbound_click and page_view, sent as application/json, text/plain;charset=UTF-8 and application/x-www-form-urlencoded - expected: (204, b'') for every case. The probe saw `respond_bytes(self, 204, b"")` return exactly (204, b'') on /api/profile/delete. Today the run reads (404, b'{\n  "error": "Not found"\n}') at line 121, in all 5 cases. - excludes: A handler that parses the body only when Content-Type is application/json (the browser sendBeacon text/plain and form posts get 400 or 415), or a handler that answers 200 with a JSON echo. Either way at least one parametrized case reads (400, …), (415, …) or (200, b'{…}').
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:123 — `len(rows) == 1` after a single accepted POST - expected: 1. The 5 ACCEPTED cases each run against a fresh client_backend database, so before the request the table is empty. - excludes: The handler never calls `insert_analytics_event` (it validates and returns 204), so the length is 0. Or it inserts and also retries or double-writes, so the length is 2.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:125 — `(type, track_id, href, page_path, user_agent, referer) == expected` across five header shapes: UA and Referer sent, both sent empty, both absent, UA only - expected: The fields as sent. track_id and href are None on a page_view. user_agent and referer equal 'Mozilla/5.0 analytics-test' and 'https://example.org/about' when sent, and None when sent empty or absent. Observed by probe: this header-free opener delivers no User-Agent or Referer at all (the server's headers.get gives None), an empty header arrives as '', and a '' written through insert_analytics_event reads back as '' and not None. - excludes: A handler storing `self.headers.get("User-Agent")` without mapping '' to None reads ('outbound_click', …, '', '') in the click-text-plain-headers-empty case. A handler taking user_agent and referer from the JSON body (which carries neither) reads None in the headers-sent cases. A handler storing urllib's default UA would be caught too, but this opener sends none.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:126-127 — created_at is an int with now_ms() before the request ≤ created_at ≤ now_ms() after it, and created_at != CLIENT_TIMESTAMP (1) - expected: An int millisecond stamp inside the request window. The probe saw an int created_at round-trip through insert_analytics_event as int. - excludes: A handler stamping created_at from the body's `timestamp` stores 1, which is outside the window and equal to CLIENT_TIMESTAMP. One stamping in seconds (time.time()) stores a value about 1000× below `before`. One storing a float or ISO string fails the isinstance check.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:134,136,137 — for each of the 12 REJECTED bodies: status == 400, the body is JSON with a non-empty string `error`, and `_rows(...) == []`. Lines 138-139 are positive controls with no row: a valid VIEW posted afterwards gets (204, b'') and the table then holds 1 row. - expected: 400, a non-empty string error, and []. Today the run reads 404 at line 134 in all 12 cases ("assert 404 == 400"). - excludes: A handler that inserts before validating, or catches the validation failure after the insert and still answers 400, reads [(row…)] at line 137. A handler missing one check (e.g. accepting `timestamp: true` since bool is an int, accepting a mailto: href, accepting a page_view with a track_id, or letting a lone-surrogate href through) reads 204 at line 134 for that case. A handler that 400s with an empty body fails json.loads at line 135.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:148,150 — under the production limiter (RATE_LIMIT_MAX_REQUESTS 90 per 60 s), the 91st POST from 203.0.113.18 reads (429, {"error": "Rate limit exceeded"}) and the table holds 90 rows. Lines 149, 151 and 152 are controls with no row: all 90 earlier requests got 204, and 203.0.113.19 still gets (204, b'') and makes 91 rows. - expected: (429, {'error': 'Rate limit exceeded'}) then 90. The probe observed, on /api/profile/blocks under the same limiter with X-Forwarded-For keying from 127.0.0.1: 90 requests passed, the 91st got (429, b'{\n  "error": "Rate limit exceeded"\n}'), and another address was not limited. Today the run reads (404, {'error': 'Not found'}) at line 148, because unknown paths are never limited (the probe's 92nd request to the event path was still 404). - excludes: A route registered without `_rate_limit_check` stores the 91st with 204, so line 148 reads (204, …) and line 150 would read 91. A handler that inserts and then runs the limit check answers 429 but line 150 reads 91.

<assertions>
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:121: an accepted event gets exactly (204, b"") back, over 5 cases: click as application/json, page_view as text/plain;charset=UTF-8, click as text/plain with empty UA and Referer, page_view as application/json with neither header, page_view with explicit null track_id/href as application/x-www-form-urlencoded with UA only. C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:123: exactly one analytics_events row after the accepted request, read through a separate sqlite3 connection. C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:125: the row's (type, track_id, href, page_path, user_agent, referer) matches the expected tuple: fields as sent, track_id and href NULL on a page_view, UA and Referer copied from the headers, and NULL when a header was sent empty ("") or not sent. C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:126: created_at is an int with now_ms() taken before the request <= created_at <= now_ms() taken after the response. C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:127: created_at != the client body timestamp (1). C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:133: control in the 400 test: a valid page_view posted first gets (204, b""), so the route is shown to store and an unchanged table later is down to the refusal. C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:135: control: exactly 1 row is stored before the refused POST. C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:137: a refused body gets status 400, over 12 cases: b"", b"{", b"[]", b"\xff", and the valid baseline with type "click", track_id "About_Patreon", href "mailto:a@b.c", href with a lone surrogate, page_path "about", timestamp missing, timestamp true, and a page_view carrying track_id. C2
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:139: the 400 body is JSON whose "error" is a non-empty str. C2
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:140: after the refusal the stored rows equal the pre-refusal rows exactly (no row added, none changed). C2
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:147: control in the 429 test, on a server with the production RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS): 90 valid clicks with X-Forwarded-For 203.0.113.18 each get 204. C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:148: control: 90 rows after those 90 posts. C1
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:150: the 91st valid post from the same address gets 429 with body exactly {"error": "Rate limit exceeded"}. C2
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:151: the row count is still 90 after the 429. C2
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:152: control: a post from 203.0.113.19 still gets (204, b""), so the 429 is the per-address limit and not a stopped server. C2
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:153: control: the row count is then 91. C2
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:159: regression line, no clause: GET of the path is 404 with {"error": "Not found"}.
tests/tmp/test_18_about_outbound_click_tracking_phase3.py:160: regression line, no clause: the GET leaves the table empty.
</assertions>

<probes>
Probe tests/tmp/test_probe_18_p3.py, run with ValidateTests ["tests/tmp/test_probe_18_p3.py", "-s"]. It posted to a recording BaseHTTPRequestHandler and then to the real conftest client_backend. What it printed:
(1) build_opener().addheaders defaults to [('User-agent', 'Python-urllib/3.14')]. With addheaders = [] the server saw User-Agent None and Referer None, so both headers are truly absent.
(2) Adding User-Agent "" and Referer "" made the server see both as present with value "". So "empty" is a separate case from "absent", and an implementation that stores the raw header gets caught.
(3) data=b"" was sent with Content-Length: 0 and an empty body.
(4) Data sent without a Content-Type had urllib add application/x-www-form-urlencoded, so every checkpoint request now sets its Content-Type explicitly.
(5) On today's code, a valid POST, a `{` POST and a GET of /api/analytics/event all got 404 with body {"error": "Not found"}.
Then the checkpoint itself, run with ValidateTests ["tests/tmp/test_18_about_outbound_click_tracking_phase3.py"]: 18 failed, 1 passed. Each failure stops at its first status assertion with "assert (404, ...) == (204, b'')" (lines 121 and 133, and the 90×204 control at 147), so it is red because the route is missing and not because of harness setup. The passing test is the GET 404 regression line, which is expected.
now_ms was read, not probed: lib/time_utils.now_ms is int(time() * 1000), and the test brackets the request with that same function.
I have no delete tool, so the probe file tests/tmp/test_probe_18_p3.py is still in the tree and needs removing. It carries no assertions the checkpoint depends on.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_18_about_outbound_click_tracking_phase3.py` - 10194 characters, inlined in full

```
"""POST /api/analytics/event on a real ClientBackendServer over a socket: one server-stamped row per accepted event, none per refused request.

- A valid outbound_click or page_view, sent as application/json, text/plain;charset=UTF-8 or application/x-www-form-urlencoded, gets 204 with an empty body and leaves exactly one row: its type, track_id, href and page_path as sent (track_id and href NULL on a page_view), created_at inside the [before, after] now_ms() window around the request and not the client timestamp 1, and user_agent and referer equal to the request headers, each NULL when that header was sent empty or not sent at all.
- After one valid event is stored, each refused body (empty, `{`, `[]`, `\\xff`, and the valid baseline with one of type, track_id, href (a non-http scheme, a lone surrogate), page_path or timestamp broken, or a page_view carrying a track_id) gets 400 with a JSON string `error` and leaves the stored rows exactly as they were.
- Under the production 90-per-60 s route limiter, 90 valid posts from 203.0.113.18 each get 204 and store 90 rows; the 91st gets 429 `{"error": "Rate limit exceeded"}` and the count stays 90, while 203.0.113.19 is still stored.
- Regression line, not a clause: GET of the path is 404 `{"error": "Not found"}` and stores nothing.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import pytest

ACTIVE_DIR = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))

# client_backend is the conftest fixture itself, imported so pytest serves it here as it does under tests/active.
from conftest import CLOSED_ENGINE, RateLimiter, client_backend, client_server, ensure_user_schema  # noqa: E402,F401
from lib.time_utils import now_ms  # noqa: E402

EVENT_PATH = "/api/analytics/event"
STORED = "SELECT type, track_id, href, page_path, created_at, user_agent, referer FROM analytics_events ORDER BY id"
# No default headers: urllib otherwise adds `User-agent: Python-urllib/3.x`; observed, this opener sends neither User-Agent nor Referer unless a test adds one.
OPENER = urllib.request.build_opener()
OPENER.addheaders = []
MISSING = object()
# Far outside any request window, so a row stamped from the body is told apart from one stamped by the server.
CLIENT_TIMESTAMP = 1
USER_AGENT = "Mozilla/5.0 analytics-test"
REFERER = "https://example.org/about"
JSON_HEADERS = {"Content-Type": "application/json"}
TEXT_HEADERS = {"Content-Type": "text/plain;charset=UTF-8"}
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
LIMITED_ADDRESS = "203.0.113.18"
OTHER_ADDRESS = "203.0.113.19"
CLICK = {"type": "outbound_click", "track_id": "about_patreon", "href": "https://www.patreon.com/x", "page_path": "/about", "timestamp": CLIENT_TIMESTAMP}
VIEW = {"type": "page_view", "page_path": "/about.html", "timestamp": CLIENT_TIMESTAMP}


def _body(event: dict[str, Any], **overrides: Any) -> bytes:
    """`event` with `overrides` applied as JSON bytes; MISSING drops the key."""
    merged = {**event, **overrides}
    return json.dumps({key: value for key, value in merged.items() if value is not MISSING}).encode("utf-8")


def _send(base: str, method: str, raw: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
    """Send one request with exactly `headers`; return the status and the raw response body."""
    req = urllib.request.Request(base + EVENT_PATH, data=raw, method=method)
    for name, value in headers.items():
        req.add_header(name, value)
    try:
        with OPENER.open(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _rows(db_path: Path) -> list[tuple]:
    """Every analytics_events row, read through a connection of its own."""
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(STORED).fetchall()


@contextmanager
def _serving_limited(tmp_path: Path):
    """A Client backend built as conftest's `client_backend` is, but with the production route limiter."""
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, CLOSED_ENGINE, "bridge", RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", db_path
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()


# Body, request headers, and the row's (type, track_id, href, page_path, user_agent, referer).
ACCEPTED = [
    pytest.param(CLICK, {**JSON_HEADERS, "User-Agent": USER_AGENT, "Referer": REFERER}, ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about", USER_AGENT, REFERER), id="click-json-headers-sent"),
    pytest.param(VIEW, {**TEXT_HEADERS, "User-Agent": USER_AGENT, "Referer": REFERER}, ("page_view", None, None, "/about.html", USER_AGENT, REFERER), id="view-text-plain-headers-sent"),
    pytest.param(CLICK, {**TEXT_HEADERS, "User-Agent": "", "Referer": ""}, ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about", None, None), id="click-text-plain-headers-empty"),
    pytest.param(VIEW, JSON_HEADERS, ("page_view", None, None, "/about.html", None, None), id="view-json-headers-absent"),
    pytest.param({**VIEW, "track_id": None, "href": None}, {**FORM_HEADERS, "User-Agent": USER_AGENT}, ("page_view", None, None, "/about.html", USER_AGENT, None), id="view-form-nulls-referer-absent"),
]

REJECTED = [
    pytest.param(b"", id="empty-body"),
    pytest.param(b"{", id="invalid-json"),
    pytest.param(b"[]", id="non-object"),
    pytest.param(b"\xff", id="non-utf8"),
    pytest.param(_body(CLICK, type="click"), id="type-unknown"),
    pytest.param(_body(CLICK, track_id="About_Patreon"), id="track-id-uppercase"),
    pytest.param(_body(CLICK, href="mailto:a@b.c"), id="href-mailto"),
    pytest.param(_body(CLICK, href="https://x.y/\ud800"), id="href-lone-surrogate"),
    pytest.param(_body(CLICK, page_path="about"), id="page-path-no-slash"),
    pytest.param(_body(CLICK, timestamp=MISSING), id="timestamp-missing"),
    pytest.param(_body(CLICK, timestamp=True), id="timestamp-bool"),
    pytest.param(_body(VIEW, track_id="about_x"), id="view-with-track-id"),
]


@pytest.mark.parametrize(("event", "headers", "expected"), ACCEPTED)
def test_accepted_event_stores_one_server_stamped_row(client_backend, event: dict[str, Any], headers: dict[str, str], expected: tuple) -> None:
    """A valid event under any Content-Type gets 204 with an empty body and exactly one row: its fields as sent, created_at in the request's now_ms() window and not the client timestamp, user_agent and referer from the headers or NULL when empty or absent."""
    before = now_ms()
    status, body = _send(client_backend.base, "POST", json.dumps(event).encode("utf-8"), headers)
    after = now_ms()
    assert (status, body) == (204, b"")  # C1
    rows = _rows(client_backend.db_path)
    assert len(rows) == 1  # C1: exactly one row per accepted request
    event_type, track_id, href, page_path, created_at, user_agent, referer = rows[0]
    assert (event_type, track_id, href, page_path, user_agent, referer) == expected  # C1: fields as sent, UA and Referer from the headers, NULL when empty or absent
    assert isinstance(created_at, int) and before <= created_at <= after  # C1: server receive time
    assert created_at != CLIENT_TIMESTAMP  # C1: not the client's clock


@pytest.mark.parametrize("raw", REJECTED)
def test_invalid_body_gets_400_and_stores_nothing(client_backend, raw: bytes) -> None:
    """With one valid event already stored, a refused body gets 400 with a JSON string `error` and leaves the stored rows exactly as they were."""
    assert _send(client_backend.base, "POST", _body(VIEW), JSON_HEADERS) == (204, b"")  # C1: control, the route stores, so an unchanged table below is the refusal
    stored = _rows(client_backend.db_path)
    assert len(stored) == 1  # C1: control
    status, body = _send(client_backend.base, "POST", raw, JSON_HEADERS)
    assert status == 400  # C2
    error = json.loads(body)["error"]
    assert isinstance(error, str) and error  # C2: a JSON error message, not an empty body
    assert _rows(client_backend.db_path) == stored  # C2: no row added


def test_91st_post_from_one_address_gets_429_and_stores_nothing(tmp_path: Path) -> None:
    """Under the production limiter, 90 valid posts from one address each get 204 and store 90 rows; the 91st gets 429 `{"error": "Rate limit exceeded"}` and the count stays 90; another address is still stored."""
    limited = {**JSON_HEADERS, "X-Forwarded-For": LIMITED_ADDRESS}
    with _serving_limited(tmp_path) as (base, db_path):
        assert [_send(base, "POST", _body(CLICK), limited)[0] for _ in range(90)] == [204] * 90  # C1: control, all 90 within the limit are accepted
        assert len(_rows(db_path)) == 90  # C1: control
        status, body = _send(base, "POST", _body(CLICK), limited)
        assert (status, json.loads(body)) == (429, {"error": "Rate limit exceeded"})  # C2
        assert len(_rows(db_path)) == 90  # C2: the refused 91st added no row
        assert _send(base, "POST", _body(CLICK), {**JSON_HEADERS, "X-Forwarded-For": OTHER_ADDRESS}) == (204, b"")  # C2: control, the 429 is the per-address limit, not a stopped server
        assert len(_rows(db_path)) == 91  # C2: control


def test_get_of_event_path_is_not_a_route(client_backend) -> None:
    """GET of the event path is 404 `{"error": "Not found"}` and stores nothing."""
    status, body = _send(client_backend.base, "GET", None, {})
    assert (status, json.loads(body)) == (404, {"error": "Not found"})  # regression line, no clause
    assert _rows(client_backend.db_path) == []  # regression line, no clause

```


Gate: satisfied

## 2026-10-02 - Step 7 - Phase 3 (Analytics route) - red (audit round 1)

`tests/tmp/test_18_about_outbound_click_tracking_phase3.py` exited 1.

```
  tests/tmp/test_18_about_outbound_click_tracking_phase3.py  18 failed, 1 passed                    0.0s
  ---------------------------------------------------------
  total                                                      18 failed, 1 passed                    9.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 3 (Analytics route) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D15b

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. absence-only-assertion (rules/shape.md) — tests/tmp/test_18_about_outbound_click_tracking_phase3.py:158-159
   assert (status, json.loads(body)) == (404, {"error": "Not found"})  # regression line, no clause
   assert _rows(client_backend.db_path) == []  # regression line, no clause
   This test fits the entry's "delete the code under test entirely" check. The 404 comes from the existing fallthrough at server.py:440, and the empty table needs no new code, so the test is green before phase 3 exists. It claims no `must_prove` clause and says it is a regression line, so it gates nothing. That is why this is a Recommendation and not a Critical finding. Don't count it as evidence for C1 or C2.
2. hardcoded-spec-mirror (rules/shape.md), partial match — tests/tmp/test_18_about_outbound_click_tracking_phase3.py:146, 149, 150
   accepted = [_send(base, "POST", _body(CLICK), limited)[0] for _ in range(90)]
   The limiter is built from `client_server.RATE_LIMIT_MAX_REQUESTS` (line 79), but the count is the literal 90 in three places. This meets the entry's fourth <how_to_spot> bullet: change the constant and the test file has to change too. It does not meet the first bullet, because nothing asserts the constant equals a literal. So no entry fully covers it. A wrong limiter still fails the test either way, so this does not block.

PREDICTED FAILURE
`test_accepted_event_stores_one_server_stamped_row` fails at line 121 on `(status, body) == (204, b"")`. The POST gets 404 `{"error": "Not found"}` because `_serve_post` (server.py:442-506) has no `/api/analytics/event` branch. The same cause fails `test_invalid_body_gets_400_and_stores_nothing` at line 134 (`status == 400`, got 404) and `test_91st_post_from_one_address_gets_429_and_stores_nothing` at line 148 (got `(404, {"error": "Not found"})`). `test_get_of_event_path_is_not_a_route` passes.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_analytics_events.py, which does not exist (FileNotFoundError). Nothing in it was assessed.
2. `fixtures_path` was not supplied. I read `client_backend`, `RateLimiter`, `ensure_user_schema` and `CLOSED_ENGINE` in tests/active/conftest.py and client/backend/lib/users_store.py. The `analytics_events` table exists there (users_store.py:67), so `_rows` will run against the schema. I did not read the `ClientBackend` helper's methods in conftest past its fields `base` and `db_path`.
3. I answered the stub question from the assertion form; nothing was run. These assertions fail against a stub:
   - A route that returns 204 without storing fails at line 123.
   - Copying the body's `timestamp` into `created_at` fails at lines 126-127.
   - A constant user_agent or referer fails the empty-header and absent-header cases at line 125.
   - A route that always returns 400 fails its own control at line 138.
   - A missing or post-insert rate-limit check fails at line 148 or line 150.
   The loopback peer is trusted by default (server.py:52), so `X-Forwarded-For` resolves as the 429 test assumes.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (39 clauses: 11 must_prove, 21 docstring, 7 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a valid event of either type" is accepted | :125 | a route that stores only `outbound_click` or only `page_view` (both types are in `ACCEPTED` and `type` is compared) | CARRIED |
| C1b | must_prove | "with any Content-Type" | :121 | a route that accepts only `application/json` (`text/plain;charset=UTF-8` and form-urlencoded must also get 204) | CARRIED |
| C1c | must_prove | "gets 204" | :121 | a 200/201 or a body-bearing success response | CARRIED |
| C1d | must_prove | "adds one row" | :123 | no insert, or a double insert (fresh db per test, so the count must be exactly 1) | CARRIED |
| C1e | must_prove | `created_at` comes from the server | :126, :127 | storing the body `timestamp` (1, far outside the [before, after] window) | CARRIED |
| C1f | must_prove | `user_agent` comes from the server | :125 | ignoring the header, storing `""` instead of NULL, or swapping it with referer (params :92-:96) | CARRIED |
| C1g | must_prove | `referer` comes from the server | :125 | ignoring the header, storing `""` instead of NULL, or swapping it with user_agent (params :92-:96) | CARRIED |
| C2a | must_prove | "400 for an invalid body" | :134 | accepting, or failing with 500, on each of the 12 `REJECTED` bodies | CARRIED |
| C2b | must_prove | the 400 "adds no row" | :137, :138-:139 | inserting before validating; the control rules out a route that never writes | CARRIED |
| C2c | must_prove | "429 over the route limit" | :148, :149 | no limiter on the route, or a limit other than 90 (hardcoded 90 × 204 then 429) | CARRIED |
| C2d | must_prove | the 429 "adds no row" | :150 | inserting before the limit check (a 91st row) | CARRIED |
| D1 | docstring | "204 with an empty body" | :121 | a non-empty success body | CARRIED |
| D2 | docstring | "exactly one row" | :123 | zero or two rows | CARRIED |
| D3 | docstring | "type, track_id, href and page_path as sent" | :125 | a field that is dropped, rewritten or normalised | CARRIED |
| D4 | docstring | "track_id and href NULL on a page_view" | :125 | storing `""` or the explicit-null keys as anything but NULL (params :93, :95, :96) | CARRIED |
| D5 | docstring | json, text/plain;charset=UTF-8 and form-urlencoded all accepted | :121 | a Content-Type gate | CARRIED |
| D6 | docstring | "created_at inside the [before, after] now_ms() window" | :126 | a stale or non-integer stamp | CARRIED |
| D7 | docstring | "not the client timestamp 1" | :127 | storing the body timestamp | CARRIED |
| D8 | docstring | "user_agent and referer equal to the request headers" | :125 | a header that is not read | CARRIED |
| D9 | docstring | "NULL when that header was sent empty" | :125 | storing `""` (param :94) | CARRIED |
| D10 | docstring | "NULL when ... not sent at all" | :125 | storing a default string (params :95, :96; `OPENER.addheaders = []` at :34) | CARRIED |
| D11 | docstring | each listed refused body gets 400 | :134 | accepting any of empty, `{`, `[]`, `\xff`, a bad type, track_id, href (mailto, lone surrogate), page_path or timestamp, or a page_view with a track_id | CARRIED |
| D12 | docstring | "a JSON string `error`" | :135-:136 | an empty, non-JSON or non-string error body | CARRIED |
| D13 | docstring | "leaves the table empty" | :137 | an insert on refusal | CARRIED |
| D14 | docstring | "a valid event posted after it on the same server is stored" | :138-:139 | a route that never writes, or a server left unable to write by the refusal | CARRIED |
| D15a | docstring | "production 90-per-..." limiter | :149, :148 | a limit other than 90 | CARRIED |
| D15b | docstring | "...-per-60 s" window | none | nothing: the window is taken from `RATE_LIMIT_WINDOW_SECONDS` at :79 and no assertion depends on its value | UNCARRIED |
| D16 | docstring | 91st gets 429 `{"error": "Rate limit exceeded"}` | :148 | a different status or body | CARRIED |
| D17 | docstring | "the 90 before it each got 204" | :149 | an early 429 | CARRIED |
| D18 | docstring | "the table holds those 90 rows only" | :150 | the 91st being stored | CARRIED |
| D19 | docstring | "203.0.113.19 is still stored" | :151-:152 | a global (not per-address) limit, or a stopped server | CARRIED |
| D20 | docstring | GET is 404 `{"error": "Not found"}` | :158 | GET serving the route | CARRIED |
| D21 | docstring | GET "stores nothing" | :159 | GET inserting | CARRIED |
| N1 | name | "accepted event" (204) | :121 | a refusal of a valid event | CARRIED |
| N2 | name | "stores one ... row" | :123 | zero or duplicate rows | CARRIED |
| N3 | name | "server_stamped" | :125-:127 | client-supplied stamps | CARRIED |
| N4 | name | "invalid body gets 400" | :134 | accepting a malformed body | CARRIED |
| N5 | name | "and stores nothing" (400) | :137 | an insert on refusal | CARRIED |
| N6 | name | "91st post from one address gets 429" | :148-:149 | a missing or mis-set limit | CARRIED |
| N7 | name | "and stores nothing" (429) / "GET ... is not a route" | :150, :158 | an insert past the limit; GET being served | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:5
   D15b is UNCARRIED. The docstring claims a "90-per-60 s route limiter", but the window comes from `client_server.RATE_LIMIT_WINDOW_SECONDS` at :79 and no assertion depends on its value. A 600 s or 1 s window passes the same way. This is a docstring-only clause, so it does not block. Fix it by narrowing the sentence to "90-request" or by asserting the window value.
2. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:99-112
   `REJECTED` covers only malformed values. No case sits at or one past the length limits the code accepts: `track_id` 64 characters (`[a-z0-9_]{1,64}`), `page_path` 256, `href` 2048. A negative `timestamp` (refused at `timestamp < 0`) and a float timestamp are also untested. On the accepted side, nothing tests a request sent with no Content-Type header at all, which C1's "any Content-Type" covers.
3. bounds (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase3.py:91-97
   No accepted body carries its own `user_agent` or `referer` key. So C1f and C1g rule out an implementation that ignores the headers, but not one where a client-supplied body value takes priority over the header. No rule requires that case beyond the edge-of-input principle. `created_at` already gets the equivalent check through `CLIENT_TIMESTAMP`.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists `.un/skills/devsecops/config.json` and `tests/active/test_analytics_events.py`. I did not read either, because the test under audit does not import or exercise them.
2. I could not find a handler that routes `/api/analytics/event` in `_serve_post` of client/backend/server.py (:442-:506), so I could not see how the route reads the body, Content-Type and headers. I judged bounds against `_validate_analytics_event` (:1260), the `ANALYTICS_*` constants (:70-:73) and the `analytics_events` schema in client/backend/lib/users_store.py.
3. `fixtures_path` was not supplied. I read `client_backend` from tests/active/conftest.py:73-93; it uses a fresh `tmp_path` database per test.

## 2026-10-02 - Step 7 - Phase 3 (Analytics route) - self-check (audit round 2, send-back 0)

`tests/tmp/test_18_about_outbound_click_tracking_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:121 — (status, body) == (204, b"") for an outbound_click or page_view sent as application/json, text/plain;charset=UTF-8 or application/x-www-form-urlencoded - expected: (204, b"") in all 5 ACCEPTED cases - excludes: A route that accepts only application/json, or that answers 200/201 with a body, reads (400 or 415, ...) on the text/plain and form cases, or (200, b"{...}").
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:123 — len(rows) == 1 on a fresh per-test database - expected: 1 - excludes: A route that returns 204 without inserting reads 0; a double insert reads 2.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:125 — (type, track_id, href, page_path, user_agent, referer) == expected - expected: The fields as sent; track_id/href NULL on a page_view; user_agent/referer equal to the headers, and None when a header is sent as "" or not sent - excludes: Storing the raw empty header reads "" instead of None (param :94). Storing a default UA reads a string where None is expected (:95). Swapping UA and referer reads (REFERER, USER_AGENT) or (None, USER_AGENT) on :96. Handling only one event type fails the other type's cases.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:126-127 — created_at is an int within [now_ms() before, now_ms() after] and != CLIENT_TIMESTAMP (1) - expected: An integer ms stamp taken by the server during the request - excludes: Copying the body timestamp stores 1, which falls outside the window and equals CLIENT_TIMESTAMP.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:134-137 — each of the 12 REJECTED bodies gets status 400, a JSON non-empty string error, and _rows == []; armed by the :138-:139 control, where a following valid event gets (204, b"") and 1 row - expected: 400, a non-empty str error, [] rows, then 1 row after the control post - excludes: Inserting before validating reads a non-empty table at :137. Accepting a malformed body reads 204 at :134. Crashing reads 500. A route that never writes fails the control at :138-:139.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase3.py:148-150 — after 90 posts from 203.0.113.18 each get 204 (:149), the 91st gets (429, {"error": "Rate limit exceeded"}) (:148), and the row count is 90 (:150); :151-:152 show 203.0.113.19 is still stored - expected: 429 with that body; 90 rows; then 204 and 91 rows for the other address - excludes: No limiter on the route reads 204 at :148. Inserting before the limit check reads 91 rows at :150. A global, not per-address, limit, or a stopped server, reads 429 or an error at :151.

<exemptions>
none
</exemptions>

<items>
<item id="D15b">
<disposition>justified</disposition>
<what>I narrowed the prose to what the test asserts. The module docstring's third bullet (line 5) used to say "Under the production 90-per-60 s route limiter". It now says "Under the production route limiter (90 requests per address within its window, whose length is not asserted here)". The window is still taken from `client_server.RATE_LIMIT_WINDOW_SECONDS` at :79, and no assertion depends on it, because all 91 posts land well inside any realistic window. The docstring no longer claims a 60 s value. The 90-request count stays carried by :148-:150. Only the text of line 5 changed, so no line numbers moved and no assertion changed.</what>
</item>
</items>

<findings_addressed>
Neither auditor raised a CRITICAL. Claim recommendation 1 (D15b, docstring "90-per-60 s"): taken. I narrowed the line 5 docstring to "90 requests per address within its window, whose length is not asserted here" instead of pinning the window constant. Pinning it would be the hardcoded-spec-mirror form the shape audit warns about. Claim recommendations 2 and 3 (length-boundary and negative/float timestamp cases, a request with no Content-Type, a body-supplied user_agent/referer) are left as they are. They do not block, and they would add cases this ledger does not list. Shape recommendations 1 (the GET regression test is green before phase 3) and 2 (the literal 90 against RATE_LIMIT_MAX_REQUESTS) are also left. The GET test is already labelled as a regression line with no clause. The literal 90 is the docstring's stated production limit, and a wrong limiter fails either way.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:121 — (status, body) == (204, b"") for an outbound_click or page_view sent as application/json, text/plain;charset=UTF-8 or application/x-www-form-urlencoded</assertion>
<expected>(204, b"") in all 5 ACCEPTED cases</expected>
<wrong_implementation>A route that accepts only application/json, or that answers 200/201 with a body, reads (400 or 415, ...) on the text/plain and form cases, or (200, b"{...}").</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:123 — len(rows) == 1 on a fresh per-test database</assertion>
<expected>1</expected>
<wrong_implementation>A route that returns 204 without inserting reads 0; a double insert reads 2.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:125 — (type, track_id, href, page_path, user_agent, referer) == expected</assertion>
<expected>The fields as sent; track_id/href NULL on a page_view; user_agent/referer equal to the headers, and None when a header is sent as "" or not sent</expected>
<wrong_implementation>Storing the raw empty header reads "" instead of None (param :94). Storing a default UA reads a string where None is expected (:95). Swapping UA and referer reads (REFERER, USER_AGENT) or (None, USER_AGENT) on :96. Handling only one event type fails the other type's cases.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:126-127 — created_at is an int within [now_ms() before, now_ms() after] and != CLIENT_TIMESTAMP (1)</assertion>
<expected>An integer ms stamp taken by the server during the request</expected>
<wrong_implementation>Copying the body timestamp stores 1, which falls outside the window and equals CLIENT_TIMESTAMP.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:134-137 — each of the 12 REJECTED bodies gets status 400, a JSON non-empty string error, and _rows == []; armed by the :138-:139 control, where a following valid event gets (204, b"") and 1 row</assertion>
<expected>400, a non-empty str error, [] rows, then 1 row after the control post</expected>
<wrong_implementation>Inserting before validating reads a non-empty table at :137. Accepting a malformed body reads 204 at :134. Crashing reads 500. A route that never writes fails the control at :138-:139.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase3.py:148-150 — after 90 posts from 203.0.113.18 each get 204 (:149), the 91st gets (429, {"error": "Rate limit exceeded"}) (:148), and the row count is 90 (:150); :151-:152 show 203.0.113.19 is still stored</assertion>
<expected>429 with that body; 90 rows; then 204 and 91 rows for the other address</expected>
<wrong_implementation>No limiter on the route reads 204 at :148. Inserting before the limit check reads 91 rows at :150. A global, not per-address, limit, or a stopped server, reads 429 or an error at :151.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Each negative assertion has a positive control: :137 is armed by :138-:139, and :150 is armed by :149 and :151-:152. The GET test (:158-:159) is absence-only, but it claims no clause and is labelled a regression line. Deleting the route makes the C1 and C2 tests fail.
2. No. Expected values are literals from the spec (204, 429 and the error body, field values sent in the request) or the server's clock window. No assertion repeats production's transformation. Deleting the route branch in `_serve_post` turns :121, :134 and :148 red.
3. No. Header handling is read across sent, empty and absent headers, both event types and three Content-Types. Refusal is read across 12 bodies.
4. No doubles. The test uses a real ClientBackendServer over a socket with a real sqlite database.
5. Yes. Imports and names are unchanged from the run that collected 19 tests (18 failed, 1 passed). This edit only touched docstring text on line 5.
6. Yes. Header absence, empty headers and urllib's Content-Type defaulting were observed in the probe run. Today's 404 behaviour was observed too. The only edit this round is prose.
7. Yes. Only the docstring changed. The earlier run showed each failure stopping at its first status assertion with a 404, because the route is missing, while the GET regression test passes.
Nothing needed a rewrite. The only edit was narrowing the docstring for D15b. The probe file tests/tmp/test_probe_18_p3.py is still in the tree, because I have no delete tool, and needs removing.
</answers>

Gate: satisfied

## 2026-10-02 - Step 7 - Phase 3 (Analytics route) - red (audit round 2)

`tests/tmp/test_18_about_outbound_click_tracking_phase3.py` exited 1.

```
  tests/tmp/test_18_about_outbound_click_tracking_phase3.py  18 failed, 1 passed                    0.0s
  ---------------------------------------------------------
  total                                                      18 failed, 1 passed                    9.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 3 (Analytics route) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this (rules/shape.md) — tests/tmp/test_18_about_outbound_click_tracking_phase3.py:158-159
   `assert (status, json.loads(body)) == (404, {"error": "Not found"})  # regression line, no clause`
   `assert _rows(client_backend.db_path) == []  # regression line, no clause`
   The current code already passes this test, because `_serve_get` ends at the 404 fallthrough at client/backend/server.py:440. If the code under test were deleted, the `absence-only-assertion <how_to_spot>` check would still pass. That entry does not fire, though: line 158 is a positive assertion on an exact status and body, and the test gates no clause in `must_prove`. As a regression guard it is correctly shaped. It adds nothing to the checkpoint's red, so it should not be counted as evidence for C1 or C2.

PREDICTED FAILURE
`/api/analytics/event` has no branch in `_serve_post` (client/backend/server.py:442-506), so every POST gets the 404 fallthrough at line 506. This produces four results:
- Every `test_accepted_event_stores_one_server_stamped_row` case fails at line 121: `(404, b'{"error": "Not found"}') != (204, b"")`.
- Every `test_invalid_body_gets_400_and_stores_nothing` case fails at line 134: `404 != 400`.
- `test_91st_post_from_one_address_gets_429_and_stores_nothing` fails at line 148: `(404, {"error": "Not found"}) != (429, {"error": "Rate limit exceeded"})`.
- `test_get_of_event_path_is_not_a_route` passes.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_analytics_events.py. That file does not exist in the worktree, so it was not read. It plays no part in this test's assertions.
2. `fixtures_path` was not supplied. I read `client_backend`, `CLOSED_ENGINE`, `RateLimiter` and `ensure_user_schema` from tests/active/conftest.py instead, which the test imports at line 27. I read `analytics_events`, used by `_rows`, only as far as its schema and insert statement (client/backend/lib/users_store.py:67, 98).

Basis for the passes (not findings):
- **Anti-patterns:**
  - `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep`: none. The test reads no `.md` file.
  - `hardcoded-spec-mirror`: no code constant is compared to a literal. The limiter comes from `client_server.RATE_LIMIT_*` (line 79). The `90` at lines 146-150 is the route's behaviour seen over HTTP, not a constant's value.
  - `tautological-assertion`: every expected value is a written-down literal (lines 92-96, 148). `created_at` is checked against an independent `now_ms()` window (line 126).
  - `absence-only-assertion`: in the C2 tests, each empty-table claim has a positive control in the same test (lines 138-139, 149, 151-152).
  - `echoed-literal`: server code sits between the request headers and body and the stored row. Deleting the insert or the header read turns lines 123-125 red.
  - `single-value-pin`: user_agent and referer are each read in three states: sent, empty and absent (lines 92-96). Content-Type is read in three forms. `created_at` is pinned against `CLIENT_TIMESTAMP = 1` (lines 126-127). The limit is checked from both sides (lines 148-149), and against a second address (line 151).
- **Ladder:** rung 1 with rung 3 side effects. The test drives a real `ClientBackendServer` over a socket and asserts on status, body and `analytics_events` rows. That is the highest rung these behavioural invariants support. It is not the anti-rung, and there is no downshift, so no comment is required.
- **Stub question:** each plausible wrong implementation turns a specific line red:
  - Returning 204 without writing fails at line 123.
  - Storing the body's `timestamp` fails at lines 126-127.
  - Ignoring headers, or storing `""`, fails at line 125.
  - Returning 400 for everything fails the control at line 138.
  - Writing the row and then returning 400 fails at line 137.
  - Skipping the limiter fails at line 148.
  - An off-by-one in the limit fails at line 148 or line 149.
  - One shared bucket instead of per-address limits fails at line 151. Loopback is in `DEFAULT_TRUSTED_PROXIES`, so the server honours the test's `X-Forwarded-For` header (server.py:52, 334).

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (40 clauses: 11 must_prove, 22 docstring, 7 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a valid event of either type" is accepted | :125 | a route that stores only `outbound_click` or only `page_view` (both types are in `ACCEPTED` and `type` is compared) | CARRIED |
| C1b | must_prove | "with any Content-Type" | :121 | a route that accepts only `application/json` (`text/plain;charset=UTF-8` and form-urlencoded must also get 204, params :93-:96) | CARRIED |
| C1c | must_prove | "gets 204" | :121 | a 200/201 or a success response with a body | CARRIED |
| C1d | must_prove | "adds one row" | :123 | no insert, or a double insert (each test gets a fresh db through `tmp_path`) | CARRIED |
| C1e | must_prove | `created_at` comes from the server | :126, :127 | storing the body `timestamp` (1, far outside the [before, after] window) | CARRIED |
| C1f | must_prove | `user_agent` comes from the server | :125 | ignoring the header, storing `""` instead of NULL, or swapping it with referer (params :92-:96) | CARRIED |
| C1g | must_prove | `referer` comes from the server | :125 | ignoring the header, storing `""` instead of NULL, or swapping it with user_agent (params :92-:96) | CARRIED |
| C2a | must_prove | "400 for an invalid body" | :134 | accepting, or failing with 500, on any of the 12 `REJECTED` bodies | CARRIED |
| C2b | must_prove | the 400 "adds no row" | :137, :138-:139 | inserting before validating; the control rules out a route that never writes | CARRIED |
| C2c | must_prove | "429 over the route limit" | :148, :149 | no limiter on the route, or a limit other than 90 (90 × 204 then a 429, hardcoded) | CARRIED |
| C2d | must_prove | the 429 "adds no row" | :150 | inserting before the limit check (a 91st row) | CARRIED |
| D1 | docstring | "204 with an empty body" | :121 | a success response with a body | CARRIED |
| D2 | docstring | "exactly one row" | :123 | zero or two rows | CARRIED |
| D3 | docstring | "type, track_id, href and page_path as sent" | :125 | a field that is dropped, rewritten or normalised | CARRIED |
| D4 | docstring | "track_id and href NULL on a page_view" | :125 | storing `""`, or storing the explicit-null keys as anything but NULL (params :93, :95, :96) | CARRIED |
| D5 | docstring | json, text/plain;charset=UTF-8 and form-urlencoded all accepted | :121 | a check that gates on Content-Type | CARRIED |
| D6 | docstring | "created_at inside the [before, after] now_ms() window" | :126 | a stale stamp or one that is not an integer | CARRIED |
| D7 | docstring | "not the client timestamp 1" | :127 | storing the body timestamp | CARRIED |
| D8 | docstring | "user_agent and referer equal to the request headers" | :125 | a header that is never read | CARRIED |
| D9 | docstring | "NULL when that header was sent empty" | :125 | storing `""` (param :94) | CARRIED |
| D10 | docstring | "NULL when ... not sent at all" | :125 | storing a default string (params :95, :96; `OPENER.addheaders = []` at :34) | CARRIED |
| D11 | docstring | each listed refused body gets 400 | :134 | accepting any of: empty, `{`, `[]`, `\xff`, a bad type, a bad track_id, a bad href (mailto, lone surrogate), a bad page_path or timestamp, or a page_view with a track_id | CARRIED |
| D12 | docstring | "a JSON string `error`" | :135-:136 | an error body that is empty, not JSON, or not a string | CARRIED |
| D13 | docstring | "leaves the table empty" | :137 | an insert on refusal | CARRIED |
| D14 | docstring | "a valid event posted after it on the same server is stored" | :138-:139 | a route that never writes, or a refusal that leaves the server unable to write | CARRIED |
| D15a | docstring | "production ... 90 requests per address" limiter | :149, :148 | a limit other than 90 | CARRIED |
| D15b | docstring | withdrawn | n/a | n/a | CARRIED |
| D16 | docstring | the 91st gets 429 `{"error": "Rate limit exceeded"}` | :148 | a different status or body | CARRIED |
| D17 | docstring | "the 90 before it each got 204" | :149 | an early 429 | CARRIED |
| D18 | docstring | "the table holds those 90 rows only" | :150 | storing the 91st | CARRIED |
| D19 | docstring | "203.0.113.19 is still stored" | :151-:152 | a limit that is global rather than per address, or a server that has stopped (loopback is a trusted proxy, `server.py:52`, so `X-Forwarded-For` is honoured) | CARRIED |
| D20 | docstring | GET is 404 `{"error": "Not found"}` | :158 | GET serving the route | CARRIED |
| D21 | docstring | GET "stores nothing" | :159 | GET inserting | CARRIED |
| N1 | name | "accepted event" (204) | :121 | refusing a valid event | CARRIED |
| N2 | name | "stores one ... row" | :123 | zero or duplicate rows | CARRIED |
| N3 | name | "server_stamped" | :125-:127 | stamps taken from the client | CARRIED |
| N4 | name | "invalid body gets 400" | :134 | accepting a malformed body | CARRIED |
| N5 | name | "and stores nothing" (400) | :137 | an insert on refusal | CARRIED |
| N6 | name | "91st post from one address gets 429" | :148-:149 | a limit that is missing or set wrong | CARRIED |
| N7 | name | "and stores nothing" (429) / "GET ... is not a route" | :150, :158 | an insert past the limit; GET being served | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_18_about_outbound_click_tracking_phase3.py:5
   D15b was resolved by narrowing the prose, not by adding an assertion. The module docstring no longer claims "90-per-60 s". It now reads "90 requests per address within its window, whose length is not asserted here". The window length stays untested. The limiter at :79 still takes it from `RATE_LIMIT_WINDOW_SECONDS`, and no assertion depends on its value.
2. whole-claim (rules/testing.md) — tests/tmp/test_18_about_outbound_click_tracking_phase3.py:92-96
   C1 says "with any Content-Type". The test sends three declared types: application/json, text/plain;charset=UTF-8 and form-urlencoded. No case sends a POST with the Content-Type header left out, or with a fourth type. A route that refuses a request with no Content-Type would still pass. No ledger row names this, so it does not block.
3. bounds (rules/testing.md) — tests/tmp/test_18_about_outbound_click_tracking_phase3.py:99-112
   The validator has limits: page_path 1 to 256 characters, href at most 2048, track_id `[a-z0-9_]{1,64}`, timestamp ≥ 0. None of them is tested at max or one past max. A negative timestamp and a float timestamp are not tested either. `REJECTED` only covers malformed values and values of the wrong kind. No ledger row names this, so it does not block.

NOT ASSESSED
1. `fixtures_path` was not supplied. The `client_backend` fixture is imported from tests/active/conftest.py (:27). I judged independence from the parts of that file I found by search, :74-:89: a fresh `users.db` under `tmp_path` and `RateLimiter(1000, 60)`. I did not read the whole file.
2. `code_under_test` lists tests/active/test_analytics_events.py and .un/skills/devsecops/config.json. I did not read either, because this test does not use them. The row insert helper (client/backend/lib/users_store.py:98) is not in `code_under_test` and was only found by search.

## 2026-10-02 - Step 7 - Phase 3 (Analytics route) - checkpoint outcome (run 1)

`tests/tmp/test_18_about_outbound_click_tracking_phase3.py` exited 0 after the phase landed.

<changes>
### `client/backend/server.py`
- `_serve_post` now has a `POST /api/analytics/event` route. Like the other write routes, it checks `_rate_limit_check(url.path)` first. That limiter allows 90 requests per address in 60 s, and the address comes from `X-Forwarded-For` behind a trusted proxy. A request over the limit gets 429 `{"error": "Rate limit exceeded"}` before the body is read. A GET of the path still falls through to the existing 404.
- New `ClientBackendHandler._handle_analytics_event`, which works in four steps:
  - It reads the body with the shared `read_json_body`. That function ignores Content-Type, so `application/json`, `text/plain;charset=UTF-8` and form-encoded `sendBeacon` bodies are all accepted.
  - If the body fails to parse (invalid JSON, a non-object, or non-UTF-8, since `UnicodeDecodeError` is a `ValueError`), it answers 400 with the parse error. An empty body parses to `{}`, which the validator then refuses.
  - It runs the existing `_validate_analytics_event`. A refused event gets 400 with that function's message, and no row is written.
  - A valid event is stored as one row through `insert_analytics_event` inside a `with self.server.user_db:` transaction, and the answer is 204 with an empty body. The server sets `created_at = now_ms()`; the client `timestamp` is validated but never stored. `user_agent` and `referer` come from the request headers, and are NULL when the header is empty or missing.
- `insert_analytics_event` was added to the `lib.users_store` import.

### `tests/active/test_analytics_events.py`, `.un/skills/devsecops/config.json`
Not changed. This step asked for production code only. The checkpoint gates from `tests/tmp/`, and `tests/active/test_analytics_events.py` does not exist in the worktree yet. That file and its `test_groups` entry belong to the promotion of the phase checkpoints, not to this implementation step.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_18_about_outbound_click_tracking_phase3.py  19 passed                              0.0s
  ---------------------------------------------------------
  total                                                      19 passed                              9.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 4 (About beacon) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The About page template loads a new `src/about-analytics.ts`, which on import sends one `page_view` and then one `outbound_click` per click on an `a[data-track-id]`. Delivery is `sendBeacon` with a keepalive `fetch` fallback, and the built page ships it as a bundled asset.

- C1 - Importing the module sends one `page_view` and one `outbound_click` per tracked click, falling back to keepalive `fetch` when `sendBeacon` is unavailable, refuses or throws.
- C2 - A vite build of the About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`.

must_prove:
- C1 - Importing the module sends one `page_view` and one `outbound_click` per tracked click, falling back to keepalive `fetch` when `sendBeacon` is unavailable, refuses or throws.
- C2 - A vite build of the About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`.

## 2026-10-02 - Step 7 - Phase 4 (About beacon) - self-check (audit round 1, send-back 0)

`tests/tmp/test_18_about_outbound_click_tracking_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:139 — in every sendBeacon mode exactly two sends are made, both to `http://api.test/api/analytics/event` - expected: `["http://api.test/api/analytics/event", "http://api.test/api/analytics/event"]` in all four modes. The probe run of the planned module showed this, e.g. mode false: `'url': 'http://api.test/api/analytics/event'` on both sends. - excludes: Probe-observed. Concatenating `resolveClientApiBase() + "/api/analytics/event"` gives `http://api.test//api/...`. Building the URL on `window.location.origin` gives `http://page.test/...`. Using `target.matches` instead of `closest` misses the span inside the link and gives one send. Using `closest("a")` also counts the untracked link and gives three. Each of these is red at line 139 in all four modes.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:140 — the bodies are exactly `{type: page_view, page_path, timestamp: NOW}`, then `{type: outbound_click, track_id: about_patreon, href: https://www.patreon.com/x, page_path, timestamp: NOW}`. `page_path` is the stubbed `location.pathname`: `/about` in modes true/missing, `/about.html` in false/throws. - expected: Probe run, mode false: `{"type":"page_view","page_path":"/about.html","timestamp":1700000000123}` then `{"type":"outbound_click","track_id":"about_patreon","href":"https://www.patreon.com/x","page_path":"/about.html","timestamp":1700000000123}`. - excludes: Probe-observed: hardcoding `page_path: "/about"` instead of reading `location.pathname` is red at line 140 in modes false and throws. Two other cases reach this line only if the send count is right: a body with an extra key such as `ip`, or missing `timestamp`/`href`. Either fails the exact dict equality.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:142 — mode true: both sends are beacons carrying an `application/json` Blob, and fetch is never called - expected: `[("beacon", "application/json"), ("beacon", "application/json")]` (the reference passed in mode true). - excludes: Probe-observed: calling `sendBeacon` detached from `navigator` throws "Illegal invocation" in the stub, as browsers do, and falls through to fetch. The observable reads `[('fetch', None), ('fetch', None)]`, red at line 142. Sending a string body instead of a typed Blob would give a `blobType` of `None`.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:144 — modes false, missing and throws: both sends go by fetch with POST, `keepalive: true` and `Content-Type: application/json` - expected: `[("fetch", "POST", True, "application/json")] * 2`. Probe run, mode false: `'method': 'POST', 'keepalive': True, 'contentType': 'application/json'`. - excludes: Probe-observed: leaving out `keepalive` gives `False`, and leaving out the header gives `contentType` of `None`. Both are red at line 144 in false, missing and throws. Not wrapping the `sendBeacon` call in try lets the throw reach the outer catch, so in mode throws no fetch is made and line 139 goes red first.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:145 — the bound `navigator.sendBeacon` is called once per event (2) whenever it exists, and 0 times when it is missing - expected: 2 in modes true/false/throws and 0 in mode missing. Probe run, mode false: `'beaconCalls': 2`. - excludes: Probe-observed: a detached `sendBeacon` call reads 0, red at line 145 in false and throws. Going straight to fetch without trying the beacon would also read 0.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:146 — exactly one `click` listener is registered on `document` - expected: `["click"]` (probe run: `'listeners': ['click']`). - excludes: Registering a listener per link or adding a second document listener (e.g. `auxclick`) gives a list other than `["click"]`. Registering on `window` instead of `document` gives `[]`, and then lines 139/140 also show only the page_view. Not separately run as a mutant; the exact list makes each of these red.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:147 — no click handler throws for the untracked link, the Text-like target or the tracked click - expected: `[]`. The tracked click's send at line 140 is the positive control showing the handler ran. - excludes: Probe-observed: dropping the `typeof target.closest === "function"` guard throws `TypeError: ... is not a function` on the Text-like target. Red at line 147 in all four modes.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:148 — zero unhandled rejections, although the stubbed fetch always rejects - expected: `[]`. Line 144 is the positive control: it shows a rejecting fetch was actually called in modes false, missing and throws. - excludes: Probe-observed: dropping the `.catch(() => undefined)` on the fetch promise gives `['TypeError: offline', ...]`. Red at line 148 in false, missing and throws.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:161 — the built `dev-pages/about.template.html` loads at least one `/assets/*.js` script - expected: Observed in a probe vite build of a copied frontend with the planned script tag and module added: `<script type="module" crossorigin src="/assets/about-BGG45oE3.js"></script>` is matched, giving `['/assets/about-BGG45oE3.js']`. - excludes: Template left without the `<script type="module" src="/src/about-analytics.ts">` tag. The built page has only the CSS link, so `scripts == []`. This is what the checkpoint run showed against the current tree, red at line 161.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:162 — one of those script files contains `/api/analytics/event` - expected: True. In the probe build, `/assets/about-*.js` contained `new URL("/api/analytics/event",i())`, with api-base split into a `modulepreload` chunk. - excludes: A template script pointing at some other entry (e.g. the videos page module), or a module that never builds the event route, gives a bundled script without the literal: `any(...)` is False.

<assertions>
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:138 - in each sendBeacon mode (true/false/missing/throws) exactly two sends are made, both to `http://api.test/api/analytics/event`. The API base was defined with a trailing slash and the page origin is `http://page.test`, so concatenation and a page-origin URL both fail - C1
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:139 - the bodies are exactly `{type: page_view, page_path: /about, timestamp: NOW}` and then `{type: outbound_click, track_id: about_patreon, href: https://www.patreon.com/x, page_path: /about, timestamp: NOW}`, with `Date.now` fixed. The untracked `<a>` and the Text-like target add nothing, and the tracked click targets a span inside the link, so only a `closest` walk finds it - C1
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:141 - in mode true, both are beacons carrying an `application/json` Blob, and fetch is never called - C1
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:143 - in modes false, missing and throws, both go by fetch with method POST, `keepalive: true` and `Content-Type: application/json` - C1
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:144 - `navigator.sendBeacon` is called bound to navigator once per event (2) whenever it exists, and 0 times when missing, so the fallback follows a tried beacon. The stub throws "Illegal invocation" on a detached call, as browsers do - C1
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:145 - exactly one `click` listener is registered on `document` - C1
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:146 - no click handler throws for the untracked link, the Text-like target without `closest`, or the tracked click - C1
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:147 - zero unhandled rejections, although the stubbed fetch always rejects - C1
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:148 - `preventDefault` is never called on any of the three clicks - regression line, not a clause
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:160 - a real `vite build --outDir <tmp_path>/dist --emptyOutDir` from client/frontend writes `dev-pages/about.template.html` with at least one `<script ... src="/assets/*.js">`. The test skips with a reason when `dev-pages/about.html` exists - C2
tests/tmp/test_18_about_outbound_click_tracking_phase4.py:161 - one of those script files contains `/api/analytics/event` - C2
</assertions>

<probes>
1. Probe file tests/tmp/probe_18_phase4.py, run with ValidateTests ["tests/tmp/probe_18_phase4.py", "-s"]. Observed:
- node is v22.22.2. `globalThis.navigator` has get/set/enumerable/configurable, and plain assignment throws "TypeError: Cannot set property navigator of #<Object> which has only a getter". I then ran `Object.defineProperty(globalThis, "navigator", {value, configurable: true, writable: true})`, and it took.
- `new Blob(['{"a":1}'], {type: "application/json"})` gives type `application/json`, `.text()` gives `{"a":1}`, and `instanceof Blob` is true.
- `typeof globalThis.location` is `undefined`, so the runner defines it and sets `window = globalThis`.
- With an `unhandledRejection` handler installed, one uncaught `Promise.reject` and one `.catch`ed one gave a count of 1 after a 20 ms timer.
- `node_modules/.bin/esbuild` and `.bin/vite` both exist, and `dev-pages/about.html` does not.
- `vite build --outDir <tmp>/dist --emptyOutDir` from client/frontend exits 0 in about 0.4 s and writes `dev-pages/about.template.html` plus `assets/*.js`. Script tags have the form `<script type="module" crossorigin src="/assets/<name>-<hash>.js">`. Today's built About page has only the CSS link and no script.
2. Same probe file, rewritten. I bundled a reference implementation (the plan's draft) and seven wrong variants from tmp entry files with the checkpoint's own esbuild flags and RUNNER, then called the checkpoint test function for each mode. Results:
- ref: PASS in all four modes.
- concat (`base + "/api/..."`, which gives `//api`): FAIL in all modes.
- page_origin (URL built from `window.location.origin`): FAIL in all modes.
- nocatch (no `.catch` on the fetch): FAIL in false, missing and throws, on rejections `['TypeError: offline', ...]`.
- noguard (no `typeof closest` check): FAIL in all modes, on errors `TypeError ... not a function`.
- direct (reads `target`'s attribute without `closest`): FAIL in all modes, with one send.
- anylink (`closest("a")`): FAIL in all modes, with three sends.
- ignore_return (sendBeacon's false result ignored): FAIL in false.
- detached (sendBeacon called detached): FAIL in true, false and throws. It first failed with a KeyError on `blobType`, so I changed the transport comprehensions to `.get(...)` and it now fails as a readable assertion.
- ref, mode false, gave this report: `{"sends": [fetch POST keepalive true application/json to http://api.test/api/analytics/event with body page_view /about 1700000000123, the same with outbound_click about_patreon https://www.patreon.com/x], "beaconCalls": 2, "listeners": ["click"], "errors": [], "rejections": [], "prevented": [false, false, false]}`.
3. Same probe file, rewritten. I copied client/frontend to tmp (node_modules symlinked, dist excluded), added the reference `src/about-analytics.ts` and the template's `<script type="module" src="/src/about-analytics.ts">`, then ran the checkpoint's build test against the copy. It passed. The built page had `<script type="module" crossorigin src="/assets/about-BoAnQv2t.js">` plus `<link rel="modulepreload" crossorigin href="/assets/api-base-ouyYHZ10.js">`, so api-base lands in its own chunk and the literal is in the entry the page's script names.
4. ValidateTests ["tests/tmp/test_18_about_outbound_click_tracking_phase4.py"] on the current tree:
- the 4 node cases ERROR at the fixture with esbuild `Could not resolve ".../client/frontend/src/about-analytics.ts"`;
- the build test FAILs at line 160 with `assert []`, showing the built page has no script.
Both are red for the right reason.
Outside the named path: the probe file tests/tmp/probe_18_phase4.py could not be deleted, because I have no delete tool. I overwrote it as an empty file, so it collects nothing, but it still needs removing.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_18_about_outbound_click_tracking_phase4.py` - 10885 characters, inlined in full

```
"""The About beacon module in node, and the About page as vite builds it.

- Bundled by the project's esbuild with `VITE_CLIENT_API_BASE` "http://api.test/" and run in node under a browser-shaped global (window is globalThis, a stubbed `location`, `document`, `navigator` and a rejecting `fetch`, `Date.now` fixed), importing `src/about-analytics.ts` and then clicking an untracked link, a Text-like target and a span inside an `a[data-track-id="about_patreon"]` sends exactly two events to `http://api.test/api/analytics/event`: first `{type: page_view, page_path: /about, timestamp}`, then `{type: outbound_click, track_id: about_patreon, href, page_path: /about, timestamp}`, with nothing else in either body. With `sendBeacon` returning true both go as `application/json` Blob beacons and `fetch` is never called; with it returning false or throwing, each is first offered to the bound `navigator.sendBeacon` and then posted by `fetch` with `keepalive: true` and `Content-Type: application/json`, as they are when `sendBeacon` is missing. In every mode exactly one `click` listener is on `document`, no handler throws, no default is prevented and no rejection goes unhandled.
- A real `vite build` into a tmp outDir writes `dev-pages/about.template.html` with a `/assets/*.js` script whose file contains `/api/analytics/event`; skipped when a local `dev-pages/about.html` override would be built instead.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
VITE = FRONTEND / "node_modules" / ".bin" / "vite"
MODULE = FRONTEND / "src" / "about-analytics.ts"
# Trailing slash on purpose: plain concatenation would give `//api`.
API_BASE = "http://api.test/"
EVENT_URL = "http://api.test/api/analytics/event"
# The page's own origin differs from the API base, so a URL built from `window.location.origin` shows.
PAGE_ORIGIN = "http://page.test"
NOW = 1700000000123
TRACKED_HREF = "https://www.patreon.com/x"
PAGE_VIEW = {"type": "page_view", "page_path": "/about", "timestamp": NOW}
OUTBOUND_CLICK = {"type": "outbound_click", "track_id": "about_patreon", "href": TRACKED_HREF, "page_path": "/about", "timestamp": NOW}

RUNNER = """
const MODE = process.env.MODE;
const NOW = Number(process.env.NOW);
// The clock is a system boundary: fixed, so the timestamp sent is known.
Date.now = () => NOW;
const sends = [];
const pending = [];
const errors = [];
const rejections = [];
const listeners = [];
let beaconCalls = 0;
process.on("unhandledRejection", (reason) => { rejections.push(String(reason)); });
const read = async (data) => (typeof data === "string" ? data : await data.text());
// Recorded in call order; the payload is read afterwards, since a Blob only reads asynchronously.
const record = (entry, data) => { sends.push(entry); pending.push(read(data).then((body) => { entry.body = body; })); };
const nav = { userAgent: "node-runner" };
if (MODE !== "missing") {
  nav.sendBeacon = function (url, data) {
    // A browser throws "Illegal invocation" on a sendBeacon detached from its navigator; the stub does too.
    if (this !== nav) throw new TypeError("Illegal invocation");
    beaconCalls += 1;
    if (MODE === "throws") throw new TypeError("beacon refused");
    if (MODE === "false") return false;
    record({ via: "beacon", url: String(url), blobType: data?.type ?? null }, data);
    return true;
  };
}
// Node 22's navigator is a getter-only global: assignment throws, defineProperty replaces it.
Object.defineProperty(globalThis, "navigator", { value: nav, configurable: true, writable: true });
const contentType = (headers) => (headers instanceof Headers ? headers.get("content-type") : Object.entries(headers ?? {}).find(([name]) => name.toLowerCase() === "content-type")?.[1] ?? null);
globalThis.fetch = (url, init = {}) => {
  record({ via: "fetch", url: String(url), method: init.method ?? "GET", keepalive: init.keepalive ?? false, contentType: contentType(init.headers) }, init.body ?? "");
  return Promise.reject(new TypeError("offline"));
};
globalThis.location = { origin: process.env.PAGE_ORIGIN, pathname: "/about", href: process.env.PAGE_ORIGIN + "/about" };
globalThis.document = { nodeType: 9, addEventListener: (type, listener) => { listeners.push({ type, listener }); }, removeEventListener() {} };
globalThis.window = globalThis;
const element = (tag, attrs, parent) => {
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), parentElement: parent, href: attrs.href,
    dataset: "data-track-id" in attrs ? { trackId: attrs["data-track-id"] } : {},
    getAttribute: (name) => attrs[name] ?? null, hasAttribute: (name) => name in attrs,
    matches: (selector) => {
      const m = /^([a-z]+)?(?:\\[([a-z-]+)\\])?$/.exec(selector);
      if (!m || (!m[1] && !m[2])) throw new Error(`runner stub matches only tag and [attribute] selectors, got ${selector}`);
      return (!m[1] || m[1] === tag) && (!m[2] || m[2] in attrs);
    },
    closest: (selector) => { for (let node = el; node; node = node.parentElement) if (node.matches(selector)) return node; return null; },
  };
  return el;
};
await import(process.env.BUNDLE);
const body = element("body", {}, null);
const tracked = element("a", { href: process.env.TRACKED_HREF, "data-track-id": "about_patreon" }, body);
// An untracked link, a Text-like node without `closest`, then a span inside the tracked link so only a `closest` walk finds it.
const targets = [element("a", { href: "https://example.org/untracked" }, body), { nodeType: 3, textContent: "Patreon", parentElement: null }, element("span", {}, tracked)];
const prevented = [];
for (const target of targets) {
  const event = { type: "click", target, currentTarget: globalThis.document, button: 0, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; } };
  for (const { type, listener } of listeners) {
    if (type !== "click") continue;
    try { typeof listener === "function" ? listener.call(globalThis.document, event) : listener.handleEvent(event); } catch (error) { errors.push(String(error)); }
  }
  prevented.push(event.defaultPrevented);
}
const settle = async () => { for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
await settle();
await Promise.all(pending);
// unhandledRejection is reported a tick after the rejection, so the count is read only once timers have run.
await settle();
process.stdout.write(JSON.stringify({ sends, beaconCalls, listeners: listeners.map(({ type }) => type), errors, rejections, prevented }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def runner(tmp_path_factory) -> Path:
    """The module bundled for node as `test_frontend_profile.py` bundles its modules, beside the runner script."""
    tmp_path = tmp_path_factory.mktemp("about_beacon")
    bundle = tmp_path / "bundle.mjs"
    result = subprocess.run(
        [str(ESBUILD), str(MODULE), "--bundle", "--format=esm", "--platform=node", f"--outfile={bundle}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(API_BASE)}",
         "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    script = tmp_path / "runner.mjs"
    script.write_text(RUNNER)
    return script


def _run(runner: Path, mode: str) -> dict:
    """Import the bundle under sendBeacon `mode`, click the three targets, and return what the runner observed."""
    result = subprocess.run(
        ["node", str(runner)], capture_output=True, text=True, timeout=60,
        env={"PATH": os.environ.get("PATH", ""), "BUNDLE": str(runner.parent / "bundle.mjs"), "MODE": mode,
             "NOW": str(NOW), "PAGE_ORIGIN": PAGE_ORIGIN, "TRACKED_HREF": TRACKED_HREF},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("mode", ["true", "false", "missing", "throws"])
def test_import_and_tracked_click_send_two_events_by_beacon_or_keepalive_fetch(runner: Path, mode: str) -> None:
    """One page_view on import and one outbound_click for the tracked click, none for the untracked or Text-like target, to the API base's event URL; by beacon only when sendBeacon returns true, otherwise by keepalive JSON fetch after the bound sendBeacon was tried; one document click listener, no throw, no prevented default, no unhandled rejection."""
    report = _run(runner, mode)
    sends = report["sends"]
    assert [send["url"] for send in sends] == [EVENT_URL, EVENT_URL]  # C1: exactly two sends, both to the Client API base's event route
    assert [json.loads(send["body"]) for send in sends] == [PAGE_VIEW, OUTBOUND_CLICK]  # C1: page_view on import, then one outbound_click for the tracked click only
    if mode == "true":
        assert [(send["via"], send.get("blobType")) for send in sends] == [("beacon", "application/json")] * 2  # C1: delivered by beacon, fetch never called
    else:
        assert [(send["via"], send.get("method"), send.get("keepalive"), send.get("contentType")) for send in sends] == [("fetch", "POST", True, "application/json")] * 2  # C1: keepalive fetch fallback
    assert report["beaconCalls"] == (0 if mode == "missing" else 2)  # C1: each event offered to the bound navigator.sendBeacon first when it exists
    assert report["listeners"] == ["click"]  # C1: one delegated click listener on document
    assert report["errors"] == []  # C1: the untracked and Text-like targets are handled without a throw
    assert report["rejections"] == []  # C1: the rejecting fetch never surfaces as an unhandled rejection
    assert report["prevented"] == [False, False, False]  # regression line, not a clause: navigation is never prevented


def test_built_about_page_loads_a_bundled_asset_with_the_event_route(tmp_path: Path) -> None:
    """A real vite build writes the About template with a /assets/*.js script whose file contains /api/analytics/event."""
    if (FRONTEND / "dev-pages" / "about.html").exists():
        pytest.skip("a local dev-pages/about.html override exists; vite.config.ts builds it as the about input instead of the template")
    out = tmp_path / "dist"
    result = subprocess.run([str(VITE), "build", "--outDir", str(out), "--emptyOutDir"], cwd=FRONTEND, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    page = (out / "dev-pages" / "about.template.html").read_text()
    scripts = re.findall(r'<script\b[^>]*\bsrc="(/assets/[^"]+\.js)"', page)
    assert scripts, page  # C2: the built page loads a bundled asset
    assert any("/api/analytics/event" in (out / src.lstrip("/")).read_text() for src in scripts), scripts  # C2: one of them carries the event route

```


Gate: satisfied

## 2026-10-02 - Step 7 - Phase 4 (About beacon) - red (audit round 1)

`tests/tmp/test_18_about_outbound_click_tracking_phase4.py` exited 1.

```
  tests/tmp/test_18_about_outbound_click_tracking_phase4.py  1 failed, 4 error                      0.0s
  ---------------------------------------------------------
  total                                                      1 failed, 4 error                      0.6s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 4 (About beacon) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - BLOCK
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 2 UNCARRIED clause(s) - C1b, D5b; devsecops-test-shape-auditor: critical; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: BLOCK

CRITICAL
1. single-value-pin (rules/shape.md) — tests/tmp/test_18_about_outbound_click_tracking_phase4.py:140
   assert [json.loads(send["body"]) for send in sends] == [{"type": "page_view", ...}, {"type": "outbound_click", "track_id": "about_patreon", "href": TRACKED_HREF, ...}]
   The rule wants the output checked at two inputs that must give different readings, so the test can tell that the output follows the input. This test runs the click feature at one value only. Line 83 builds the only tracked element with `"data-track-id": "about_patreon"`, and line 140 expects that same literal back. Nowhere in the file is there a second tracked anchor with a different id. A module that finds `closest("a[data-track-id]")` and then sends a hard-coded `track_id: "about_patreon"` passes all four parametrised modes, which is the entry's first `<how_to_spot>` bullet. `page_path` avoids this: line 28 varies it by mode. Fix: add a second tracked anchor with a different `data-track-id`, click it too, and assert both outbound_click bodies in order.

RECOMMENDATIONS
none

PREDICTED FAILURE
All four parametrised cases of `test_import_and_tracked_click_send_two_events_by_beacon_or_keepalive_fetch` should error in fixture setup. `client/frontend/src/about-analytics.ts` doesn't exist, so esbuild fails and `assert result.returncode == 0, result.stderr` at line 116 fails with esbuild's could-not-resolve error. `test_built_about_page_loads_a_bundled_asset_with_the_event_route` should fail at line 161 on `assert scripts, page`. No local `dev-pages/about.html` exists, so the skip at line 155 doesn't trigger. The template the build uses has no `<script src>`, and nothing in `client/frontend` contains `/api/analytics/event` yet.

NOT ASSESSED
1. `code_under_test` listed client/frontend/src/about-analytics.ts, which does not resolve. I answered the stub question from the assertion form and the runner stubs alone.
2. `code_under_test` listed tests/active/test_analytics_events.py, which does not resolve. I could not read or assess it.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (20 clauses: 7 must_prove, 11 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "importing the module sends one `page_view`" | :140 | no page_view on import, a page_view with extra or missing fields, or a page_view that isn't sent first | CARRIED |
| C1b | must_prove | "one `outbound_click` per tracked click" | :140 | nothing per-click: only one tracked target is clicked (:85), so a module-level "already sent" flag or a once-only listener also passes | UNCARRIED |
| C1c | must_prove | sends by beacon when `sendBeacon` accepts | :142 | sending by fetch when beacon would do, a beacon body that isn't JSON-typed, or a fetch beside the beacon (the count at :139 catches that) | CARRIED |
| C1d | must_prove | falls back to keepalive `fetch` when `sendBeacon` is unavailable | :144 (mode `missing`), :145 | dropping the event when there is no beacon, or a fetch without keepalive, POST or JSON | CARRIED |
| C1e | must_prove | falls back when `sendBeacon` refuses (returns false) | :144 (mode `false`), :145 | ignoring the false return and sending nothing | CARRIED |
| C1f | must_prove | falls back when `sendBeacon` throws | :144 (mode `throws`), :147 | letting the throw escape, or no fetch after the throw | CARRIED |
| C2 | must_prove | vite build of About template references a bundled `/assets/*.js` entry containing `/api/analytics/event` | :161, :162 | a template with no script, or a script that doesn't bundle the event route (the route isn't in `src/` now, so nothing else supplies it) | CARRIED |
| D1 | docstring | untracked link, Text-like target and span-in-tracked-link send "exactly two events" to the event URL | :139 | an event for the untracked or Text-like target, a URL built from `location.origin` (PAGE_ORIGIN is different), `//api` from joining the strings | CARRIED |
| D2 | docstring | body shapes, "with nothing else in either body" | :140 | extra fields or wrong field values (whole-dict equality) | CARRIED |
| D3 | docstring | `page_path` is the stubbed `location.pathname` by mode | :140 | `page_path` hardcoded to `/about` or to `/about.html` (the modes change it) | CARRIED |
| D4 | docstring | sendBeacon true → `application/json` Blob beacons, "`fetch` is never called" | :142, :139 | an untyped or string beacon, any fetch call (it would be a third send) | CARRIED |
| D5a | docstring | false/throws: "each is first offered to the bound `navigator.sendBeacon`" | :145 | skipping the beacon, a detached `sendBeacon` (the stub throws Illegal invocation, which leaves beacons at 0) | CARRIED |
| D5b | docstring | "first ... and then posted by `fetch`" — beacon before fetch | none | nothing: :144/:145 count beacon and fetch calls separately and never compare their order | UNCARRIED |
| D6 | docstring | "as they are when `sendBeacon` is missing" | :144, :145 | beacon count at 0, fetch shape the same as the fallback modes | CARRIED |
| D7 | docstring | "exactly one `click` listener is on `document`" | :146 | no listener, several listeners, or listeners of another type | CARRIED |
| D8 | docstring | "no handler throws" | :147 | a throw on the Text-like target (no `closest`) or on the untracked link | CARRIED |
| D9 | docstring | "no default is prevented" | :149 | `preventDefault` on any of the three clicks | CARRIED |
| D10 | docstring | "no rejection goes unhandled" | :148 | a fetch with no `.catch` on the rejecting stub | CARRIED |
| N1 | name | "import and tracked click send two events by beacon or keepalive fetch" | :139, :140, :142, :144 | wrong count, wrong order or wrong transport | CARRIED |
| N2 | name | "built about page loads a bundled asset with the event route" | :161, :162 | no script asset, or an asset without the route | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md) — tests/tmp/test_18_about_outbound_click_tracking_phase4.py:85 / :140
   `const targets = [element("a", { href: "https://example.org/untracked" }, body), { nodeType: 3, ... }, element("span", {}, tracked)];`
   `assert [json.loads(send["body"]) for send in sends] == [{"type": "page_view", ...}, {"type": "outbound_click", ...}]`
   C1 claims one `outbound_click` per tracked click, which is an "X per Y" claim. The test clicks a tracked target only once, so it proves that one click sends one event, not that every click does. An implementation that sends `outbound_click` only once per page load passes all four modes. That covers a module-level sent flag, de-duplication by `track_id`, and a listener that removes itself after its first tracked hit. The rule requires a second Y: click the tracked target again (or a second tracked link) and assert two `outbound_click` bodies.

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_18_about_outbound_click_tracking_phase4.py:3
   D5b is UNCARRIED. The module docstring says each event is "first offered to the bound `navigator.sendBeacon` and then posted by `fetch`". :144 and :145 count the two transports separately, so the order is never observed. Either record beacon attempts in the same ordered `sends` log as the fetches, or narrow the sentence.
2. bounds (rules/testing.md) — tests/tmp/test_18_about_outbound_click_tracking_phase4.py:83
   The tracked link always has a non-empty `data-track-id` and an `href`. Nothing tests an empty `data-track-id=""` or a tracked anchor with no `href`, which are the edges of what the click handler accepts.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` listed `client/frontend/src/about-analytics.ts` (NEW), which does not exist. Bounds and the abnormal path were judged from the test, the `must_prove` text and the runner stub alone. The module's real input handling was not read.
2. `code_under_test` listed `tests/active/test_analytics_events.py` (EDITED), which does not exist. Its edits were not assessed.
3. `client/frontend/dev-pages/about.template.html` as it stands has no `<script>`, so the EDITED version was not available. C2 was judged against `vite.config.ts` and the test. No `dev-pages/about.html` override exists right now, so the skip at :154 does not fire here.

## 2026-10-02 - Step 7 - Phase 4 (About beacon) - self-check (audit round 2, send-back 0)

`tests/tmp/test_18_about_outbound_click_tracking_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:147: in every sendBeacon mode exactly four sends are made, all to `http://api.test/api/analytics/event`. - expected: `[EVENT_URL] * 4`: one page_view plus three outbound_clicks for the three tracked clicks. The untracked link and the Text-like target send nothing. - excludes: A once-per-page sent flag or a self-removing listener gives two URLs. De-duplication by track_id gives three. `closest("a")` gives five. `base + "/api/..."` gives `http://api.test//api/...`, and a URL from `location.origin` gives `http://page.test/...`. All of these were observed failing here.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:148: the decoded bodies equal exactly `[page_view, patreon, github, patreon]` as whole dicts. - expected: `{type: page_view, page_path, timestamp: 1700000000123}`, then outbound_click bodies with `about_patreon` and `https://www.patreon.com/x`, then `about_github` and `https://github.com/y`, then `about_patreon` again. Every `page_path` is the mode's stubbed pathname (`/about` or `/about.html`). This was observed under the reference module. - excludes: A hard-coded `track_id: "about_patreon"` reads `about_patreon` for the github click. A hard-coded `page_path: "/about"` is wrong in the false and throws modes. Reading the target's own attributes without `closest` misses the span clicks.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:150 (mode true): every send is a beacon carrying an `application/json` Blob, and no fetch is recorded. - expected: `[("beacon", "application/json")] * 4` - excludes: Sending by fetch when the beacon succeeds, an untyped or string beacon body, or a detached `sendBeacon` (the stub throws Illegal invocation, so everything falls to fetch). The detached case was observed failing here.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:152 (modes false, missing, throws): every send is a fetch with POST, `keepalive: true` and `Content-Type: application/json`. - expected: `[("fetch", "POST", True, "application/json")] * 4` - excludes: Dropping the event when sendBeacon is missing, ignoring sendBeacon's false return, or letting its throw end the send all give fewer than four fetch entries. A fetch without keepalive or without the JSON header gives the wrong tuple.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:153: the ordered transport log equals `TRANSPORTS[mode] * 4`. - expected: true gives `["beacon"]*4`. false and throws give `["beacon","fetch"]*4`, observed under the reference module. missing gives `["fetch"]*4`. - excludes: Fetch issued before the beacon attempt gives `fetch, beacon, ...`. A detached `sendBeacon` never reaches the push and gives `fetch` only. Both were observed failing here in false and throws.
- C1 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:154-156: exactly one `click` listener is on document, no handler throws, and no unhandled rejection occurs. - expected: `["click"]`, `[]` and `[]`. - excludes: No `typeof closest` guard throws on the Text-like target, so errors is non-empty. A fetch with no `.catch` puts `TypeError: offline` in rejections. Both were observed last round. Several listeners, or a listener of another type, fail :154.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:169: the vite-built `dev-pages/about.template.html` has at least one `<script ... src="/assets/*.js">`. - expected: A non-empty list, e.g. `["/assets/about-<hash>.js"]`. This was observed from a tmp copy with the reference module and template script. - excludes: A template edit that is missing or drops the script tag gives `[]`. That is the current tree, observed failing here.
- C2 - tests/tmp/test_18_about_outbound_click_tracking_phase4.py:170: one of those script files contains `/api/analytics/event`. - expected: True: the entry chunk the page names carries the route literal. This was observed in the tmp-copy build. - excludes: The template loads some other script (e.g. an unrelated page entry) that does not bundle the analytics module, so no listed asset contains the route.

<exemptions>
none
</exemptions>

<items>
<item id="C1b">
<disposition>fixed</disposition>
<what>The runner now clicks five targets: the untracked link, the Text-like node, a span inside `a[data-track-id="about_patreon"]`, a second anchor `a[data-track-id="about_github"]` with href `https://github.com/y`, and the patreon span a second time. :147 asserts exactly four sends to the event URL. :148 asserts the bodies are exactly `[page_view, patreon, github, patreon]` in that order. A module-level "already sent" flag, a once-only listener or a self-removing listener sends one outbound_click and fails at :147. De-duplication by `track_id` sends patreon and github but not the repeat, gives three sends and fails at :147. The probe observed both failures in all four modes.</what>
</item>
<item id="D5b">
<disposition>fixed</disposition>
<what>The runner keeps an ordered `calls` log. The bound `sendBeacon` stub pushes "beacon" after its this-check and before it returns or throws, and `fetch` pushes "fetch". This log replaces the old `beaconCalls` counter. :153 asserts `report["calls"] == TRANSPORTS[mode] * 4`: `["beacon"]` for true, `["beacon","fetch"]` for false and throws, and `["fetch"]` for missing. Beacon-before-fetch is now observed per event. The probe built a variant that issues fetch first and attempts the beacon afterwards; it fails :153 in false and throws. A detached `sendBeacon` also fails :153 in false and throws, so D5a carries here too. The module docstring now says "in that order per event".</what>
</item>
</items>

<findings_addressed>
Claim CRITICAL 1 (whole-claim, C1 "per tracked click" proved by a single click): the runner now clicks a second tracked link (`about_github`) and then the first tracked link again. :147 asserts four sends and :148 asserts the exact `[page_view, patreon, github, patreon]` bodies. The probe observed a once-per-page flag and once-per-id de-duplication both failing at :147 in all modes. Because the count changed, the test is renamed `test_import_and_tracked_clicks_send_one_event_each_by_beacon_or_keepalive_fetch`, and its docstring and the module docstring now say four events, one per tracked click.
Shape CRITICAL 1 (single-value-pin on `track_id`/`href` at :140): a second tracked anchor with a different `data-track-id` (`about_github`) and a different href (`OTHER_HREF`) is clicked between two patreon clicks. :148 expects each outbound_click to carry its own link's id and href. The probe observed a module that sends a hard-coded `track_id: "about_patreon"` failing at :148 in all four modes.
Claim RECOMMENDATION 1 (D5b, order never observed): taken. A new ordered `calls` log replaces `beaconCalls`, and :153 asserts the per-mode beacon-then-fetch sequence for each of the four events.
Claim RECOMMENDATION 2 (empty `data-track-id`, anchor with no href): not taken. The plan's module sends an empty or malformed id as-is and leaves rejection to the server's validation, which phase 3 tests. The client has no specified behaviour at that edge for this test to pin.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:147: in every sendBeacon mode exactly four sends are made, all to `http://api.test/api/analytics/event`.</assertion>
<expected>`[EVENT_URL] * 4`: one page_view plus three outbound_clicks for the three tracked clicks. The untracked link and the Text-like target send nothing.</expected>
<wrong_implementation>A once-per-page sent flag or a self-removing listener gives two URLs. De-duplication by track_id gives three. `closest("a")` gives five. `base + "/api/..."` gives `http://api.test//api/...`, and a URL from `location.origin` gives `http://page.test/...`. All of these were observed failing here.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:148: the decoded bodies equal exactly `[page_view, patreon, github, patreon]` as whole dicts.</assertion>
<expected>`{type: page_view, page_path, timestamp: 1700000000123}`, then outbound_click bodies with `about_patreon` and `https://www.patreon.com/x`, then `about_github` and `https://github.com/y`, then `about_patreon` again. Every `page_path` is the mode's stubbed pathname (`/about` or `/about.html`). This was observed under the reference module.</expected>
<wrong_implementation>A hard-coded `track_id: "about_patreon"` reads `about_patreon` for the github click. A hard-coded `page_path: "/about"` is wrong in the false and throws modes. Reading the target's own attributes without `closest` misses the span clicks.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:150 (mode true): every send is a beacon carrying an `application/json` Blob, and no fetch is recorded.</assertion>
<expected>`[("beacon", "application/json")] * 4`</expected>
<wrong_implementation>Sending by fetch when the beacon succeeds, an untyped or string beacon body, or a detached `sendBeacon` (the stub throws Illegal invocation, so everything falls to fetch). The detached case was observed failing here.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:152 (modes false, missing, throws): every send is a fetch with POST, `keepalive: true` and `Content-Type: application/json`.</assertion>
<expected>`[("fetch", "POST", True, "application/json")] * 4`</expected>
<wrong_implementation>Dropping the event when sendBeacon is missing, ignoring sendBeacon's false return, or letting its throw end the send all give fewer than four fetch entries. A fetch without keepalive or without the JSON header gives the wrong tuple.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:153: the ordered transport log equals `TRANSPORTS[mode] * 4`.</assertion>
<expected>true gives `["beacon"]*4`. false and throws give `["beacon","fetch"]*4`, observed under the reference module. missing gives `["fetch"]*4`.</expected>
<wrong_implementation>Fetch issued before the beacon attempt gives `fetch, beacon, ...`. A detached `sendBeacon` never reaches the push and gives `fetch` only. Both were observed failing here in false and throws.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:154-156: exactly one `click` listener is on document, no handler throws, and no unhandled rejection occurs.</assertion>
<expected>`["click"]`, `[]` and `[]`.</expected>
<wrong_implementation>No `typeof closest` guard throws on the Text-like target, so errors is non-empty. A fetch with no `.catch` puts `TypeError: offline` in rejections. Both were observed last round. Several listeners, or a listener of another type, fail :154.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:169: the vite-built `dev-pages/about.template.html` has at least one `<script ... src="/assets/*.js">`.</assertion>
<expected>A non-empty list, e.g. `["/assets/about-<hash>.js"]`. This was observed from a tmp copy with the reference module and template script.</expected>
<wrong_implementation>A template edit that is missing or drops the script tag gives `[]`. That is the current tree, observed failing here.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_18_about_outbound_click_tracking_phase4.py:170: one of those script files contains `/api/analytics/event`.</assertion>
<expected>True: the entry chunk the page names carries the route literal. This was observed in the tmp-copy build.</expected>
<wrong_implementation>The template loads some other script (e.g. an unrelated page entry) that does not bundle the analytics module, so no listed asset contains the route.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every empty-list assertion (:155 errors, :156 rejections) sits beside the positive controls :147, :148 and :153. Those prove the module ran, both listeners fired and fetch was actually called. Deleting the module leaves esbuild unable to resolve it, so the fixture errors; observed on this run.
2. No. Expected values are literals or env inputs fed to stubs, and the module has to read them back from the DOM (`track_id`, `href`, `pathname`). Deleting `link.getAttribute("data-track-id")` turns :148 red. Deleting the beacon-first branch turns :150 and :153 red. `TRANSPORTS` is the test's own per-mode expectation and does not copy any production table.
3. Before the edit, yes: `track_id`/`href` were read at one input only (shape CRITICAL), and the per-click count rested on one click. Rewritten: two tracked links with different ids and hrefs, plus a repeat click. `page_path` already varied by mode, and the transport varies across four modes.
4. No. The stubs are browser and node globals (`navigator`, `document`, `location`, `fetch`, `Date.now`). `about-analytics.ts` and its `api-base` import are bundled for real.
5. Yes. The probe imported the edited file and called the renamed test function. `OTHER_HREF` and `TRANSPORTS` are bound, and the runner's `calls` and `OTHER_HREF` env are wired through `_run`. ValidateTests collected 5 items (4 parametrised plus 1 build test), as written.
6. Yes. The `calls` log shape, the four-body sequence and `prevented` with 5 entries were observed by running the reference module from the plan's draft under the edited RUNNER. ref false gave `calls: ["beacon","fetch"]*4` and bodies page_view, patreon, github, patreon. The probe also observed once_per_page and once_per_id failing at :147, hardcoded_id at :148, fetch_then_beacon at :147 (true) and :153 (false, throws), and detached at :150 and :153.
7. Yes. ValidateTests on the file after the edits: the 4 node cases ERROR at the fixture with esbuild `Could not resolve .../src/about-analytics.ts`, and the build test FAILs at :169 on `assert []` because the built About page has no script. The probe tests/tmp/probe_18_phase4.py was emptied to a docstring and still needs deleting, as does tests/tmp/test_probe_18_p4_selfcheck.py, also an emptied leftover. I have no delete tool.
</answers>

Gate: satisfied

## 2026-10-02 - Step 7 - Phase 4 (About beacon) - red (audit round 2)

`tests/tmp/test_18_about_outbound_click_tracking_phase4.py` exited 1.

```
  tests/tmp/test_18_about_outbound_click_tracking_phase4.py  1 failed, 4 error                      0.0s
  ---------------------------------------------------------
  total                                                      1 failed, 4 error                      0.6s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 4 (About beacon) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule covers this (rules/shape.md) — tests/tmp/test_18_about_outbound_click_tracking_phase4.py:170
   assert any("/api/analytics/event" in (out / src.lstrip("/")).read_text() for src in scripts), scripts
   This is a rung-3 check on build output, then a substring check on a minified JS asset.
   It is not prose and not a .md file, so no anti_pattern entry applies. Its weakness: it
   passes for any script on the built page that carries the route string. The About module
   does not have to be the one wired in. Today no file under client/frontend carries
   `/api/analytics/event`, so the check can tell a wired build from an unwired one. If a
   shared module later picks up the route, this assertion stays green whether or not the
   About entry is wired. Behaviour (C1) is gated separately by the first test, so this is
   recorded, not blocking.

PREDICTED FAILURE
test_import_and_tracked_clicks_send_one_event_each_by_beacon_or_keepalive_fetch fails in
all four modes at line 122 of the module-scoped `runner` fixture. The assertion
`assert result.returncode == 0, result.stderr` fails on esbuild's resolve error, because
client/frontend/src/about-analytics.ts does not exist. test_built_about_page_loads_a_bundled_asset_with_the_event_route
fails at line 169, `assert scripts, page`, because dev-pages/about.template.html has no
<script src> tag, so the built page lists no /assets/*.js. If a local dev-pages/about.html
exists, this test is skipped at line 163 instead.

NOT ASSESSED
1. `code_under_test` listed client/frontend/src/about-analytics.ts, which does not resolve.
   The anti-pattern, ladder and stub passes were answered from the test's assertion form
   and its runner alone. The stub check: the four transport modes, two page paths, two
   distinct ids and hrefs, a page origin different from the API base, a bound-`this`
   sendBeacon stub and an ordered call log. Together these separate a hard-coded payload,
   a fetch-only or beacon-only stub, an unbound sendBeacon, and a once-per-page or
   once-per-id send from a correct implementation.
2. `code_under_test` listed tests/active/test_analytics_events.py (EDITED), which does not
   resolve. Its edits were not read.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (20 clauses: 7 must_prove, 11 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "importing the module sends one `page_view`" | :148 | no page_view on import, a page_view with extra or missing fields, or a page_view that is not sent first | CARRIED |
| C1b | must_prove | "one `outbound_click` per tracked click" | :148 | a module-level "already sent" flag, a once-only listener, or a once-per-id send. Three tracked clicks (patreon, github, patreon again; runner :91) must give three outbound_clicks, in order, each with its own id and href | CARRIED |
| C1c | must_prove | sends by beacon when `sendBeacon` accepts | :150, :153 | sending by fetch when beacon would do, a beacon body without the JSON type, or a fetch beside the beacon (`calls == ["beacon"]*4`) | CARRIED |
| C1d | must_prove | falls back to keepalive `fetch` when `sendBeacon` is unavailable | :152, :153 (mode `missing`) | dropping the event when there is no beacon, or a fetch without keepalive, POST or JSON | CARRIED |
| C1e | must_prove | falls back when `sendBeacon` refuses (returns false) | :152, :153 (mode `false`) | ignoring the false return and sending nothing, or never offering the beacon | CARRIED |
| C1f | must_prove | falls back when `sendBeacon` throws | :152, :153, :155 (mode `throws`) | letting the throw escape, or no fetch after the throw | CARRIED |
| C2 | must_prove | vite build of About template references a bundled `/assets/*.js` entry containing `/api/analytics/event` | :169, :170 | a template with no script, or a script that does not bundle the event route (nothing under `src/` holds the route today, Grep confirmed) | CARRIED |
| D1 | docstring | send "exactly four events" to the event URL (widened from "exactly two"), none for the untracked or Text-like target | :147 | an event for the untracked or Text-like target, a URL built from `location.origin`, or `//api` from joining the strings | CARRIED |
| D2 | docstring | body shapes, "with nothing else in any body" | :148 | extra fields or wrong field values (the whole dict is compared) | CARRIED |
| D3 | docstring | `page_path` is the stubbed `location.pathname` by mode | :148 | `page_path` hardcoded to `/about` or to `/about.html` | CARRIED |
| D4 | docstring | sendBeacon true → `application/json` Blob beacons, "`fetch` is never called" | :150, :153 | an untyped or string beacon, or any fetch call | CARRIED |
| D5a | docstring | false/throws: "first offered to the bound `navigator.sendBeacon`" | :153 | skipping the beacon, or a detached `sendBeacon` (the stub throws before `calls.push`, so no "beacon" entry is recorded) | CARRIED |
| D5b | docstring | "and then posted by `fetch`, in that order per event" | :153 | fetch before beacon, or all beacons batched before all fetches. `calls` is one ordered list compared to `["beacon","fetch"]*4` | CARRIED |
| D6 | docstring | "as they are when `sendBeacon` is missing" | :152, :153 | the beacon tried when missing, or a fetch shape that differs from the other fallback modes | CARRIED |
| D7 | docstring | "exactly one `click` listener is on `document`" | :154 | no listener, several listeners, or listeners of another type | CARRIED |
| D8 | docstring | "no handler throws" | :155 | a throw on the Text-like target (it has no `closest`) or on the untracked link | CARRIED |
| D9 | docstring | "no default is prevented" | :157 | `preventDefault` on any of the five clicks | CARRIED |
| D10 | docstring | "no rejection goes unhandled" | :156 | a fetch with no `.catch` on the rejecting stub | CARRIED |
| N1 | name | "import and tracked clicks send one event each by beacon or keepalive fetch" | :147, :148, :150, :152 | wrong count, wrong order, or wrong transport | CARRIED |
| N2 | name | "built about page loads a bundled asset with the event route" | :169, :170 | no script asset, or an asset without the route | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:3, :91, :148
   The prose was widened, not narrowed. The module docstring went from "exactly two events" to "exactly four events" over five targets, and the test function was renamed (`..._tracked_clicks_send_one_event_each_...`). A matching assertion now carries each widened sentence: :91 adds a second tracked link and a repeat click, and :148 / :153 compare the full ordered lists. For the record, rows C1b and D5b were fixed by adding assertions. No prose was withdrawn to clear them.
2. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:141
   The function docstring has clauses that no ledger row names: "carrying the clicked link's own id and href" and "after the bound sendBeacon was tried". Both are carried, at :148 and :153 in that order. Recorded for completeness. Neither is a finding.
3. surfaces / checkpoint_definition (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:162-163
   `pytest.skip` when `dev-pages/about.html` exists. On a machine with a local override, C2 is never exercised and the checkpoint still goes green. There is no override in this worktree (Glob shows only `about.template.html`), so the test runs here. No ledger row names this, so it does not block.
4. whole-claim (rules/testing.md): tests/tmp/test_18_about_outbound_click_tracking_phase4.py:157
   The inline comment calls this line a "regression line, not a clause". The docstring still claims "no default is prevented" (D9), and :157 carries it. The comment and the docstring disagree about whether this is a clause.

NOT ASSESSED
1. `code_under_test` client/frontend/src/about-analytics.ts (NEW) does not resolve. The module is not written yet. Bounds and the abnormal path were judged from the test's runner stubs and `must_prove` alone.
2. `code_under_test` tests/active/test_analytics_events.py (EDITED) does not resolve. Its contents were not checked.
3. client/frontend/dev-pages/about.template.html has no `<script>` yet. C2's exclusion argument rests on the Grep showing `/api/analytics/event` absent from `client/frontend` outside `node_modules`. Which entry the edited template will reference could not be checked.

## 2026-10-02 - Step 7 - Phase 4 (About beacon) - checkpoint outcome (run 1)

`tests/tmp/test_18_about_outbound_click_tracking_phase4.py` exited 0 after the phase landed.

<changes>
### `client/frontend/src/about-analytics.ts` (NEW)
- New module, written from the plan's settled draft. It has no exports and does its work when imported.
- **Page view.** On import it sends one `{type: "page_view", page_path: window.location.pathname, timestamp: Date.now()}`.
- **Click listener.** On import it also adds one delegated `click` listener on `document`. The listener:
  - ignores a target that has no `closest`, such as a Text node or the document;
  - resolves `target.closest("a[data-track-id]")`;
  - for a match, sends `{type: "outbound_click", track_id: <data-track-id attribute>, href: link.href, page_path: window.location.pathname, timestamp: Date.now()}`;
  - sends nothing when the link's `href` is not a string, as on an SVG `<a>`;
  - never calls `preventDefault`.
- **URL.** `sendAnalyticsEvent` builds the URL as `new URL("/api/analytics/event", resolveClientApiBase())`.
  - It passes no argument, so `?api=` is never read.
  - Using `new URL` means a base that ends in `/` does not produce `//api`.
- **Transport.** It first tries `navigator.sendBeacon(url, Blob[JSON], type application/json)`, called on `navigator` itself so the browser does not throw "Illegal invocation".
  - If `sendBeacon` is missing, returns false or throws, it sends `fetch(url, {method: "POST", body, headers: {"Content-Type": "application/json"}, keepalive: true})` instead.
  - The fetch has a no-op `.catch`, and an outer try/catch covers anything thrown synchronously, so nothing reaches the visitor as an error or an unhandled rejection.

### `client/frontend/dev-pages/about.template.html` (EDITED)
- Added `<script type="module" src="/src/about-analytics.ts"></script>` before `</body>`. Like `videos.html`, it uses a root-absolute path, so vite bundles it into an `/assets/*.js` entry for the built About page. No About URL or dev-pages file name changed.

### `tests/active/test_analytics_events.py` (EDITED in the files list)
- Not changed. The file still does not exist in the worktree; Phases 1–3 recorded the same thing.
- This step asks for production code only, and the checkpoint `tests/tmp/test_18_about_outbound_click_tracking_phase4.py` gates the phase.
- The durable file and its `.un/skills/devsecops/config.json` `test_groups` entry are still to be written or promoted from the phase checkpoints.

I did not run the checkpoint; the workflow's run is the one that counts.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_18_about_outbound_click_tracking_phase4.py  5 passed                               0.0s
  ---------------------------------------------------------
  total                                                      5 passed                               1.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_18_about_outbound_click_tracking_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_18_about_outbound_click_tracking_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_18_about_outbound_click_tracking_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_18_about_outbound_click_tracking_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_18_about_outbound_click_tracking_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_18_about_outbound_click_tracking_phase3.py`
- P4C1 - carried - rests on: the last audit of `tests/tmp/test_18_about_outbound_click_tracking_phase4.py`
- P4C2 - carried - rests on: the last audit of `tests/tmp/test_18_about_outbound_click_tracking_phase4.py`

## 2026-10-02 - Step 8 - refactor pass

<refactors>
client/backend/server.py: `_handle_analytics_event` now binds `conn = self.server.user_db` once and uses it for both the transaction and the `insert_analytics_event` call, the same way `_handle_likes_import` and `_store_reaction` do. Behaviour is unchanged.
client/backend/server.py: replaced the placeholder docstring summary of `_validate_analytics_event` ("Handle validate analytics event.") with one saying what it does: it checks a decoded body against the settled rules, never raises, and ignores unknown keys. The `:returns:` line is unchanged.
</refactors>

<left_out>
I left the per-route rate-limit block in `_serve_post` (check, then 429, then return) as it is. The analytics route copies the pattern every other route already uses, and pulling it into a helper would change code that existed before this build.
I left users_store.py, about-analytics.ts and about.template.html alone. They already match the plan's settled code and the style of the files they sit in, and I found nothing that could be refactored without changing behaviour.
I did not write the durable test `tests/active/test_analytics_events.py` or add its `test_groups` entry to `.un/skills/devsecops/config.json`. That is not a refactor. All four phases list the file (NEW, then EDITED), and Phase 3 lists config.json, but it still does not exist: each phase gated only on its checkpoint in `tests/tmp/test_18_about_outbound_click_tracking_phase{1..4}.py`. The checkpoints still need promoting, or the analytics code is left with no durable test or test group.
I deleted none of the probe files in `tests/tmp/` (`probe_18_*`, `test_probe_18_*`). They are outside the files this step names; they should go when the checkpoints are promoted.
I did not run anything. The two edits only touch a local variable and a docstring, so this step's run of the Phase 2/3 checkpoints is what confirms them.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
All four phases' code already matched the plan and the style of the surrounding files, so the pass made just two behaviour-neutral tidy-ups in server.py. The real gap is the durable test `tests/active/test_analytics_events.py` and its `test_groups` entry: neither exists yet, and promoting the checkpoints into them is still to do.
</observation>

## 2026-10-02 - Step 8 - suite comparison (attempt 1)

`--compare` exited 1.

```
selected 9 of 46 test groups (37 unchanged):
  test_blocks.py — changed
  test_dislikes.py — changed
  test_frontend_blocks.py — changed
  test_frontend_profile.py — changed
  test_frontend_reactions.py — changed
  test_frontend_upnext_pager.py — changed
  test_profiles.py — changed
  test_search_fusion.py — no map entry
  test_server.py — changed
  test_blocks.py                 7 passed                              72.9s
  test_dislikes.py               10 passed                            117.6s
  test_frontend_blocks.py        1 failed, 1 passed                    17.1s
  test_frontend_profile.py       2 passed                               1.3s
  test_frontend_reactions.py     7 passed                              37.6s
  test_frontend_upnext_pager.py  1 passed                              20.1s
  test_profiles.py               11 passed                             22.8s
  test_search_fusion.py          10 passed                              2.5s
  test_server.py                 99 passed                             47.3s
  -----------------------------
  total                          148 passed, 1 failed                 117.9s wall, 9 lanes

moved against the previous record:
        new red  tests.active.test_frontend_blocks::test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 8 - red triage (attempt 1)

<failures>
### tests.active.test_frontend_blocks::test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches

**What happened.** The test failed during setup and never reached the frontend module or the Client backend. `_seed_and_targets` (line 108) calls the conftest helper `upnext_pool`. That helper posts straight to the **Engine** (`engine.request`, conftest.py:263) to list the seed's `/recommendations` pool. One of those listing requests, sent with a long `exclude` list, got 500 `{"error": "Recommendations request failed"}`.

**The test is sound.** It expects a seeded up-next listing on the Engine to return 200, which is a fair expectation. Nothing it relies on was changed by this build, and it does not conflict with any clause. It was re-selected only because `client/backend/server.py` changed. I ran a replay probe (`tests/tmp/probe_18_engine_log.py`) that starts a fresh session Engine through the conftest fixtures and calls the test's own `_seed_and_targets` four times, then the whole test body once:
- All 32 Engine requests returned 200.
- The full test passed.
- The Engine log had 0 ERROR or traceback lines.

The test is not retired and was not edited.

**This build did not cause it.** The four phases changed only Client-side files: `users_store.py` (the new `analytics_events` table and its insert), `client/backend/server.py` (the validator and the `POST /api/analytics/event` route), `about-analytics.ts` and the About template. The failing request goes from the test process directly to the Engine process, whose code (`engine/`) this build did not touch. None of these files is on that request's path. No Engine file references analytics or `users_store`.

**What I observed.**
- **Only one path gives this body.** It is the fixed body from `_handle_similar`'s generic exception handler (`SIMILAR_FAILED_MESSAGE`, engine/server/api/handlers/similar.py). Per `engine/server/README.md:31` and the 19-11 and 22-36 triage records, a request that runs past the Engine's 5 s statement deadline also gets this 500, not the 503 `Query time limit exceeded`.
- **On an idle machine the late listing pages are already slow.** In isolation, the requests carrying 362–433 `exclude` entries took 0.73–2.50 s each. The ones carrying 0–266 entries took 0.01–0.37 s. The slowest is half the 5 s budget with no other load.
- **The suite run was heavily loaded.** It ran 9 lanes in parallel. `test_dislikes` took 117.6 s and `test_blocks` 72.9 s, and each starts and drives its own Engine.

**Not confirmed.** The failing lane's Engine log (`/tmp/pytest-of-enduser/pytest-8531/engine0/engine.log`) was already gone when the probe looked for it, so I could not see the actual exception. The most likely cause is a statement-deadline overrun on a late listing page under suite load (`sqlite3.OperationalError: interrupted`). That is an inference from the timings and the earlier records, not something I observed. Any other load-dependent sqlite error caught by the same generic handler would give the same 500. To confirm it, read the failing lane's `engine0/engine.log` on the next red run before pytest's basetemp retention removes it, and check whether the `server error` record ends in `OperationalError: interrupted`.

**Conclusion.** This is a load-dependent failure of a correctly written test. It is the third time this has happened (after builds 19-11 and 22-36), and it is not a regression from the analytics work. No implementation change was made.
</failures>

<checkpoint_gaps>
none. I found no fault from this build for a checkpoint to have missed. The failing request runs only through the Engine, and no phase touched it: Phases 1–3 changed the Client backend's `users.db` schema and a new Client route, and Phase 4 changed the About page's frontend. Two older problems are behind it, and no phase of this build was asked to change either. The Engine answers a statement-deadline overrun with a generic 500 instead of a 503. The conftest pool-listing helper sends requests with 400+ `exclude` entries, which take about 2.5 s at idle against the 5 s budget.
</checkpoint_gaps>

<correction>
- **Production code and tests:** No production code changed. No test was edited, weakened or retired, and no checkpoint was touched.
- **Durable tests checked:** I searched `tests/active` for anything that conflicts with the confirmed requirements: the `analytics_events` table, `POST /api/analytics/event` or the About template's new script. Nothing there references them. The `sqlite_master` table and index checks found only look at Engine databases, not `users.db`, so no durable test is retired.
- **Diagnosis:** I found that the cause was the Engine, not this build, by replaying the failing setup in isolation with a throwaway probe (`tests/tmp/probe_18_engine_log.py`). I can't delete files, so that probe is now a one-line spent stub with no tests; it should be deleted.
- **Recommended next step:** Re-run `validate_tests.py --compare` for `test_frontend_blocks.py`. If it is red again, read that lane's `engine0/engine.log` before its basetemp is removed. This has now happened in three builds. I recommend an issue for the operator (in `docs/project/issues/`, not filed by me because it is outside this step's files) covering two things: the Engine's `_handle_similar` turns a statement-deadline interrupt into a generic 500 instead of the 503 `Query time limit exceeded`, and the conftest `upnext_pool` listing sends requests with 400+ `exclude` entries that take about 2.5 s even at idle.
</correction>

## 2026-10-02 - Step 8 - suite comparison (attempt 2)

`--compare` exited 0.

```
selected 2 of 46 test groups (44 unchanged):
  test_frontend_blocks.py — not green
  test_search_fusion.py — no map entry
  test_frontend_blocks.py  2 passed                              19.2s
  test_search_fusion.py    10 passed                              2.4s
  -----------------------
  total                    12 passed                             19.4s wall, 2 lanes

moved against the previous record:
  no longer red  tests.active.test_frontend_blocks::test_a_channel_blocked_through_the_module_leaves_the_upnext_and_search_rows_it_fetches

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 9 - document triage

- [ ] `DEPLOYMENT.md` - - **Line 258** ("Follow an About visit" caveat) is now false. It says counting human visits needs a client-side pageview beacon, at `docs/project/issues/18-about-outbound-click-tracking.md`. The beacon now exists: `client/frontend/src/about-analytics.ts` sends a `page_view` on every About load to `POST /api/analytics/event`. Rewrite it to say the beacon exists and that its counts are queried in the new subsection. Point the issue path at `docs/project/issues/archive/18-about-outbound-click-tracking.md`.
- **Line 241** ("The page's own API calls are new requests") is now incomplete. The template page made no API calls before. Every About view now produces a `POST /api/analytics/event` `request.start` from the visitor's address, plus one per tracked click. Add one sentence on this.
- **Lines 404-406** ("There is no browser-facing event publish route") need a clarification. `POST /api/analytics/event` is a browser-facing, keyless Client route that stores rows in users.db `analytics_events` and publishes nothing to the Engine. The keyed-route list at line 410 is unchanged.
- **New Triage subsection "Count About analytics events"**, between "Follow an About visit" and "Follow one request". It holds:
  - the `sqlite3 -readonly <root>/client/backend/db/users.db` invocation;
  - fenced `sql` blocks for total and daily (UTC, from `created_at` ms) `outbound_click` counts per `track_id`;
  - total and daily `page_view` counts, optionally per `page_path`;
  - the `user_agent` bot-filter variants.
- **Caveats for the new subsection:**
  - counts are forgeable within 90/min per address;
  - retention is unbounded;
  - the UA filter is a heuristic;
  - Referer is often reduced;
  - middle-click and context-menu opens are not counted;
  - non-http(s) tracked links are rejected with 400;
  - a shared or misresolved client address (ADR-0002) silently undercounts;
  - dev cross-origin beacons may be lost (ADR-0004);
  - the inherited shared-`user_db`-connection race.
- **Line 70.** The users.db description should say it now holds `analytics_events`, which grows unpruned and matters for backups.
- **Line 523.** The "every visitor shares one bucket" note should cross-reference the analytics undercount.
- **Verify section.** Optionally add a POST check, noting that it writes a real row.
- **Line 465.** The rat-tail cites `tests/active/test_static_page_visit_logs.py`, which does not exist. Flag it to the operator; do not silently rewrite it.
- [ ] `client/README.md` - - **Backend Responsibilities.** Lists the Client backend's routes but has no `POST /api/analytics/event`. Add a bullet covering:
  - the `outbound_click` and `page_view` types and their fields;
  - 204 on success, 400 on a validation failure, 429 over the rate limit;
  - Content-Type is ignored;
  - no key is needed;
  - rows go to users.db `analytics_events` with a server-stamped `created_at`, plus User-Agent and Referer;
  - nothing IP-derived is stored;
  - nothing is published to the Engine.
- **Boundary Contract (line 41).** Its write/profile route list must gain the route.
- **Optional.**
  - Widen the "write/profile API service" wording at lines 6 and 10.
  - Add a dev cross-origin beacon note beside `CLIENT_CORS_ORIGINS` at line 71.
- [ ] `client/frontend/README.md` - - **"Local About Overrides".** Says nothing about analytics, so an override built from it sends no events. Document what an override adds:
  - `<script type="module" src="/src/about-analytics.ts"></script>`, root-absolute;
  - `data-track-id="<id matching [a-z0-9_]{1,64}>"` on each outbound link to count;
  - only http(s) links count;
  - middle-click and context-menu opens are not counted;
  - an override without the tag sends nothing.
- **"What it does".** Needs a bullet for the About `page_view`/`outbound_click` beacons, sent through the Client API base with sendBeacon and a keepalive fetch fallback.
- **Line 24 (`npm run dev`).** Beacons are cross-origin there. They need `CLIENT_CORS_ORIGINS` and may be lost.
- [ ] `README.md` - - **Line 50.** The boundary table lists the Client backend's browser-facing write/profile routes. Add `/api/analytics/event`, or a row for Client analytics events.
- **Line 24.** "`engine/`: read/analytics workspace" refers to Engine analytics. It stays true and needs no change.
- [ ] `CONTEXT.md` - - The glossary has no **Analytics event** term. Add one entry in the `- **Term** — ...` style, near **Interaction event**. An analytics event:
  - is an anonymous browser event of type `outbound_click` or `page_view`;
  - is owned by the Client backend, stored in users.db `analytics_events`, and never sent to the Engine;
  - has nothing derived from the client address stored;
  - is distinct from an **Interaction event**, which feeds the Engine.
- **Client address** (line 9) stays true.
- [ ] `docs/project/issues/18-about-outbound-click-tracking.md` - - **Status.** The issue is delivered. Set `Status: enhancement, complete`.
- **Delivery comment.** Append one in the style of archive/21:31, naming plan `docs/project/plans/23-18-about-outbound-click-tracking.md` and the departures from the issue text:
  - the route is `POST /api/analytics/event`, not `/outbound-click`;
  - the table is `analytics_events`, not `outbound_click_events`;
  - validation is by shape, not an allowlist;
  - there is no `ip_hash`;
  - the template and the override docs changed, not `client/frontend/about.html`.
- **Follow-ups for the comment to name:**
  - the shared `user_db` connection race;
  - the missing `tests/active/test_static_page_visit_logs.py` and its config.json group;
  - the missing durable `tests/active/test_analytics_events.py`, if the harvest has not promoted it by then.
- **Prod note.** State that prod sends beacons only after the next `scripts/sync.sh` rebuilds `dist/`.
- **Move.** Move the file to `docs/project/issues/archive/`, and update the DEPLOYMENT.md:258 link in the same change.
- [ ] `docs/project/issues/plan.md` - - **Line 42 (P5 row).** Says "19, 20 and 21 are delivered, and 18 remains", which is now false. Mark all four delivered.
- **Line 98 (lane 5c).** Mark 18 delivered, with the plan path `docs/project/plans/23-18-about-outbound-click-tracking.md`, or its `archive/` path if the plan moves.

Out of scope:
- [ ] `.un/skills/devsecops/config.json` - Not a prose document, and the harvest turn owns it: it rewrites the group map when it promotes the phase checkpoints. The durable `tests/active/test_analytics_events.py` does not exist yet (every phase and the refactor pass record this), so there is no file to map a `test_groups` entry to. The new group belongs in the harvest, along with the note that the existing `test_static_page_visit_logs.py` group (lines 263-268) points at a missing file.
- [ ] `docs/project/plans/23-18-about-outbound-click-tracking.md` - The workflow renders this plan, so it is not hand-edited here. Its link to issue 18's current path is handled when the workflow archives the plan, per issue-tracker.md:29.
- [ ] `docs/project/issues/archive/21-static-page-visit-logs.md` - - **Line 27.** Refers to 18 by slug only, and that stays correct.
- **Line 31.** A dated delivery record of what issue 21 scoped out. It describes the beacon as the runbook's upgrade path, which was true at its delivery. It is history, not a current-state claim, and its slug reference still resolves.
- [ ] `docs/project/issues/21-static-page-visit-logs.md` - - This is the stale non-archive duplicate. It mentions 18 by slug only (line 27), which stays correct.
- Removing it is tracker hygiene outside this build's change. Mention it in the delivery notes.
- [ ] `engine/server/README.md` - Lines 4 and 18-19 say the Engine owns read/analytics APIs and no browser-facing write/profile routes. Both stay true: `/api/analytics/event` belongs to the Client backend, and "analytics" there means Engine read analytics.
- [ ] `docs/project/adr/0002-trusted-proxy-client-address.md` - The analytics route resolves the client address through the existing `_rate_limit_check` → `_get_client_ip` path, as the ADR decides. The only consequence (a misconfigured proxy now also undercounts analytics) is a caveat for DEPLOYMENT.md, not an amendment.
- [ ] `docs/project/adr/0004-cors-opt-in-by-origin.md` - The build adds no CORS headers, no credentials header and no `*`, so origin opt-in is unchanged. The possible loss of dev cross-origin beacons follows from this ADR and is documented as a caveat in DEPLOYMENT.md and client/frontend/README.md.
- [ ] `docs/project/adr/0005-raw-event-retention-keeps-ids.md` - - Its scope is the Engine's `interaction_raw_events`.
- `analytics_events` is a separate Client-side table of anonymous rows, kept unpruned by a settled requirement. It stores no `actor_id`, no caller payload and nothing from the client address, so the ADR's retention decision does not cover it and is not contradicted.

ADR conflicts: none

## 2026-10-02 - Step 9 - Update documentation

- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: new Triage subsection "Count About analytics events" with ready-to-run sqlite3 queries and caveats; the About-visit caveat, users.db, section 5 and section 6 now account for `POST /api/analytics/event`.
- [x] `client/README.md` - updated: client/README.md now covers `POST /api/analytics/event`: what it accepts and answers, where it stores events, and that it is a browser-facing Client route.
- [x] `client/frontend/README.md` - updated: Added About analytics to `client/frontend/README.md`: what the beacon module does, the dev cross-origin caveat, and what a local override needs in order to send events.
- [x] `README.md` - updated: I added a row for Client analytics events to the boundary contract table in `README.md`.
- [x] `CONTEXT.md` - updated: Added an **Analytics event** glossary entry to `CONTEXT.md`, directly after **Interaction event**.
- [x] `docs/project/issues/18-about-outbound-click-tracking.md` - updated: Issue 18 is closed as delivered: its status is `enhancement, complete`, it has a delivery comment, and a copy now sits in `archive/`. The old file is still in place because I have no way to delete files.
- [x] `docs/project/issues/plan.md` - updated: I updated `docs/project/issues/plan.md` to show issue 18 as delivered, in both the P5 priority row and the wave 5 lane 5c row.
- [x] `.un/skills/devsecops/config.json` - out of scope: Not a prose document, and the harvest turn owns it: it rewrites the group map when it promotes the phase checkpoints. The durable `tests/active/test_analytics_events.py` does not exist yet (every phase and the refactor pass record this), so there is no file to map a `test_groups` entry to. The new group belongs in the harvest, along with the note that the existing `test_static_page_visit_logs.py` group (lines 263-268) points at a missing file.
- [x] `docs/project/plans/23-18-about-outbound-click-tracking.md` - out of scope: The workflow renders this plan, so it is not hand-edited here. Its link to issue 18's current path is handled when the workflow archives the plan, per issue-tracker.md:29.
- [x] `docs/project/issues/archive/21-static-page-visit-logs.md` - out of scope: - **Line 27.** Refers to 18 by slug only, and that stays correct.
- [x] `docs/project/issues/21-static-page-visit-logs.md` - out of scope: - This is the stale non-archive duplicate. It mentions 18 by slug only (line 27), which stays correct.
- [x] `engine/server/README.md` - out of scope: Lines 4 and 18-19 say the Engine owns read/analytics APIs and no browser-facing write/profile routes. Both stay true: `/api/analytics/event` belongs to the Client backend, and "analytics" there means Engine read analytics.
- [x] `docs/project/adr/0002-trusted-proxy-client-address.md` - out of scope: The analytics route resolves the client address through the existing `_rate_limit_check` → `_get_client_ip` path, as the ADR decides. The only consequence (a misconfigured proxy now also undercounts analytics) is a caveat for DEPLOYMENT.md, not an amendment.
- [x] `docs/project/adr/0004-cors-opt-in-by-origin.md` - out of scope: The build adds no CORS headers, no credentials header and no `*`, so origin opt-in is unchanged. The possible loss of dev cross-origin beacons follows from this ADR and is documented as a caveat in DEPLOYMENT.md and client/frontend/README.md.
- [x] `docs/project/adr/0005-raw-event-retention-keeps-ids.md` - out of scope: - Its scope is the Engine's `interaction_raw_events`.

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** - while updating `docs/project/issues/18-about-outbound-click-tracking.md`: none. Two related changes belong to other turns or need a shell: (1) deleting the old `docs/project/issues/18-about-outbound-click-tracking.md`; (2) the `DEPLOYMENT.md` link to issue 18 (line 258) must point at the `archive/` path, which is part of that document's own update.

**ADR conflicts.** none

### `DEPLOYMENT.md`

<changes>
DEPLOYMENT.md: new Triage subsection "Count About analytics events" with ready-to-run sqlite3 queries and caveats; the About-visit caveat, users.db, section 5 and section 6 now account for `POST /api/analytics/event`.

- **New Triage subsection "Count About analytics events"**, between "Follow an About visit" and "Follow one request".
  - What it covers: what the beacon sends, what one `analytics_events` row holds, and that nothing derived from the client address is stored. It points to `client/README.md` for the request body and validation, and to `client/frontend/README.md` for what an override needs.
  - The queries: the `sqlite3 -readonly <project>/client/backend/db/users.db` invocation, then fenced `sql` blocks for total and daily (UTC, `date(created_at / 1000, 'unixepoch')`) `outbound_click` counts per `track_id`, and total, daily, per-`page_path` and daily per-`page_path` `page_view` counts. A `user_agent` bot-filter variant follows, with a note that it can be added to any query.
  - The caveats: counts can be forged at up to 90/60 s per address; retention is unbounded; the UA filter is a heuristic; Referer is often reduced; middle-click and context-menu opens are not counted; non-http(s) tracked links get a 400; a shared or misresolved address (ADR-0002) silently undercounts through 429s; dev cross-origin beacons need `CLIENT_CORS_ORIGINS` and may be lost (ADR-0004); and all requests share one `users.db` connection with no lock (checked: one `connect_db` connection on a `ThreadingHTTPServer`).
- **"Follow an About visit".**
  - The last caveat no longer says a beacon is needed. It says the page's beacon counts views that ran its JavaScript, points to the new subsection, and links `docs/project/issues/archive/18-about-outbound-click-tracking.md`.
  - The "own API calls" paragraph adds that an About view sends one `POST /api/analytics/event` page view, plus one request per tracked click.
- **Section 1, users.db:** it holds `analytics_events`, which nothing prunes; size backups for it.
- **Section 5:** after the "no browser-facing event publish route" paragraph, a new paragraph says `POST /api/analytics/event` is browser-facing and keyless, stores rows in users.db, and publishes nothing to the Engine. The boundary-contract list is unchanged.
- **Section 6:**
  - The "every visitor shares one bucket" sentence now points to the analytics undercount.
  - Verify gained a `curl --data … /api/analytics/event` check expecting 204. Its comment notes that it stores a real row with a `curl/` user agent, which the bot filter excludes.

**For the operator:**
- **Missing test file.** The rat-tail comment in the section 6 nginx block cites `tests/active/test_static_page_visit_logs.py`, and that file does not exist in the worktree (Glob finds nothing). I left it unchanged as instructed.
- **Broken link until the move.** The new archive link only resolves once the issue-18 turn moves the file. Right now it is still at `docs/project/issues/18-about-outbound-click-tracking.md`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `client/README.md`

<changes>
client/README.md now covers `POST /api/analytics/event`: what it accepts and answers, where it stores events, and that it is a browser-facing Client route.

- **Workspace intro (line 6).** The backend is now described as a "write/profile and analytics API service that publishes interaction events to Engine".
- **Backend Responsibilities.** Added a top-level bullet after the profile route list. It covers:
  - the body shapes of the two types, `outbound_click` and `page_view`, and the rule for each field;
  - a `page_view` must not carry `track_id` or `href`, and unknown keys are ignored;
  - the body is parsed as JSON whatever the Content-Type, and no key is needed;
  - a valid event answers 204 and adds one row to `analytics_events` in `users.db`, with `created_at` from the server's clock and `User-Agent`/`Referer` each NULL when empty;
  - the client `timestamp` is checked but not stored;
  - nothing derived from the client address is stored, and nothing is published to the Engine;
  - an invalid body answers 400 and stores nothing;
  - over the shared 90-per-60-s limit it answers 429 before the body is read.
  - The bullet points to **Analytics event** in `CONTEXT.md` and to "Count About analytics events" in `DEPLOYMENT.md` rather than repeating them.
- **Boundary Contract.** Added `analytics: /api/analytics/event` to the browser-facing ownership list.
- **`CLIENT_CORS_ORIGINS`.** Added one sentence: in the Vite dev setup the About page's analytics beacons are cross-origin too. It points to `client/frontend/README.md`, which carries the details.

I checked these claims against the code: `server.py` (the `_serve_post` route, `_handle_analytics_event`, `_validate_analytics_event`, `_analytics_href_ok`, and the `RATE_LIMIT_*` constants) and `lib/http_utils.py` (`read_json_body`). Nothing was run.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `client/frontend/README.md`

<changes>
Added About analytics to `client/frontend/README.md`: what the beacon module does, the dev cross-origin caveat, and what a local override needs in order to send events.

- **"What it does":** one new bullet.
  - `src/about-analytics.ts` sends one `page_view` when the page loads, and one `outbound_click` for each click on an `a[data-track-id]` link.
  - Events go to `POST /api/analytics/event` on the Client API base.
  - It sends with `navigator.sendBeacon`, and falls back to a `keepalive` `fetch` when `sendBeacon` is missing, returns false or throws.
  - A failed send never shows an error to the visitor, and a click is never stopped from navigating.
  - What the route accepts and stores is pointed at `client/README.md`, not repeated here.
- **"Boundary Contract":** one new bullet saying analytics events are also cross-origin under `npm run dev`.
  - They reach the backend only when the page's origin is in `CLIENT_CORS_ORIGINS`.
  - Even then the browser can drop them (pointer to ADR-0004), so dev counts are not reliable.
- **"Local About Overrides":** two new bullets.
  - The template's tag is `<script type="module" src="/src/about-analytics.ts"></script>`. An override sends events only if it has the same root-absolute tag; without it, it sends nothing. Vite bundles the tag because the override is the `about` build input.
  - Links to count need `data-track-id` with an id that fully matches `[a-z0-9_]{1,64}`. Only `http` and `https` links are counted. Middle-click and context-menu opens fire no `click` event, so they are not counted.
- **Checked against the code:**
  - `about-analytics.ts`: send order, fallback conditions, silent failure, no `preventDefault`.
  - The template's script tag at line 37.
  - The `about` input in `vite.config.ts`.
  - `resolveClientApiBase` in `api-base.ts`.
  - That `docs/project/adr/0004-cors-opt-in-by-origin.md` exists.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `README.md`

<changes>
I added a row for Client analytics events to the boundary contract table in `README.md`.

- **New row** in "Canonical Engine/Client boundary contract", placed after the write/profile row:
  - **Concern:** browser-facing analytics events, meaning `POST /api/analytics/event`, which carries the About page's page views and outbound clicks.
  - **Owner:** the Client backend.
  - **Contract:** only the Client backend exposes the route. Events are stored in the Client's `users.db` and never published to the Engine.
  - **Forbidden coupling:** sending analytics events to Engine ingest or to Engine handlers.
- **Pointer instead of a restatement:** the row sends readers to **Analytics event** in `CONTEXT.md` and doesn't repeat what event types, fields or storage columns exist.
- **Checked against the code:** the route is at `server.py:502`. `_handle_analytics_event` (`server.py:1059–1078`) writes only through `insert_analytics_event` into `self.server.user_db` and makes no call to the Engine.
- **Left as is:** the line 24 component entry ("`engine/`: read/analytics workspace") is about Engine analytics and is still true.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `CONTEXT.md`

<changes>
Added an **Analytics event** glossary entry to `CONTEXT.md`, directly after **Interaction event**.

- **What it covers:** an analytics event is an anonymous About-page browser event, either a `page_view` or an `outbound_click` on a link with `data-track-id`. It is sent to the Client backend's `POST /api/analytics/event`. Each one is stored as a row in `users.db` `analytics_events` and is never sent to the Engine. Nothing derived from the client address is stored. It is distinct from an interaction event, which feeds the Engine.
- **What it points to instead of repeating:** for querying the counts it points at `DEPLOYMENT.md`. Field-level validation rules are left to `client/README.md`.
- **Checked against the code:** the `analytics_events` schema and `insert_analytics_event` in `client/backend/lib/users_store.py`, and the route in `_serve_post` at `client/backend/server.py:502`.
- **Unchanged:** the **Client address** entry, which is still accurate.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/18-about-outbound-click-tracking.md`

<changes>
Issue 18 is closed as delivered: its status is `enhancement, complete`, it has a delivery comment, and a copy now sits in `archive/`. The old file is still in place because I have no way to delete files.

- **Where it is now:** the updated issue is at `docs/project/issues/archive/18-about-outbound-click-tracking.md`. I had no shell, so `docs/project/issues/18-about-outbound-click-tracking.md` still exists and needs deleting (`git rm`) for the move to be complete.
- **Status line:** changed from `enhancement, needs-triage` to `enhancement, complete`.
- **Rest of the issue:** the Problem, Proposed solution, Validation, Related and the existing issue-21 comment are unchanged.
- **New comment, "Delivered" (one paragraph, in the style of archive/21):**
  - It names the delivering plan, `docs/project/plans/23-18-about-outbound-click-tracking.md`.
  - It says what was built in one sentence per part: the Client backend owns the endpoint, `about-analytics.ts` sends the `page_view` and `outbound_click` events, and they are stored in `users.db`. Issue 21's nginx pages log is unchanged.
  - It points at the other documents rather than repeating them: the route contract in `client/README.md`, what an About override adds in `client/frontend/README.md`, and the count queries in `DEPLOYMENT.md` "Count About analytics events".
  - **Departures from the issue text:**
    - one route, `POST /api/analytics/event`, instead of `/outbound-click`;
    - the table is `analytics_events` (with a `type` column) instead of `outbound_click_events`;
    - events are checked by shape instead of an allowlist, with the reason;
    - no `ip_hash`, and the rate limit is the shared per-address limiter;
    - the template and the override docs changed instead of `client/frontend/about.html`.
  - **Prod note:** beacons start only after the next `scripts/sync.sh` rebuilds `dist/`.
  - **Follow-ups named:**
    - all handler threads share one `user_db` connection (I confirmed `ThreadingHTTPServer` and `check_same_thread=False` in `server.py`);
    - `tests/active/test_static_page_visit_logs.py` does not exist, and neither does its config.json group;
    - `tests/active/test_analytics_events.py` does not exist (confirmed by glob), so the only coverage is the phase checkpoints in `tests/tmp/`. That follow-up needs removing if the harvest promotes the test.
</changes>

<not_on_checklist>
none. Two related changes belong to other turns or need a shell: (1) deleting the old `docs/project/issues/18-about-outbound-click-tracking.md`; (2) the `DEPLOYMENT.md` link to issue 18 (line 258) must point at the `archive/` path, which is part of that document's own update.
</not_on_checklist>

### `docs/project/issues/plan.md`

<changes>
I updated `docs/project/issues/plan.md` to show issue 18 as delivered, in both the P5 priority row and the wave 5 lane 5c row.

- **Line 42 (P5 row):** "Why this tier" said "19, 20 and 21 are delivered, and 18 remains". It now says "All four are delivered." I dropped the "None of these block other work" sentence because nothing in the tier is left to schedule.
- **Line 98 (lane 5c):**
  - Added "18 delivered, see `docs/project/plans/23-18-about-outbound-click-tracking.md`." The plan file exists at that path, not under `plans/archive/`.
  - In the Main files cell, I replaced "the About template, one Client endpoint" with the files the build actually touched: `dev-pages/about.template.html`, `client/frontend/src/about-analytics.ts`, `POST /api/analytics/event` in `client/backend/server.py`, and `analytics_events` in `client/backend/lib/users_store.py`.

Issue 18 currently exists twice: at `docs/project/issues/18-about-outbound-click-tracking.md` and at `docs/project/issues/archive/18-...`. The move is the issue-18 item's job, and the original should be deleted there. This file does not link to the issue path, so it is unaffected either way.
</changes>

<not_on_checklist>
none
</not_on_checklist>

## 2026-10-02 - Step 10 - stopped

Harvest tests did not complete. The entries above carry what the step established before it stopped; the gate it failed is the last of them.

