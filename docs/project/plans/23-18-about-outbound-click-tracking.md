# 18-about-outbound-click-tracking

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/23-18-about-outbound-click-tracking.record.md`._

## Requirements

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

## High-level plan

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

## Impacts

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

## Documentation to update

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

## Implementation plan

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


### Phases

#### Phase 1 - Analytics storage [code]

**Files touched.** client/backend/lib/users_store.py (EDITED), tests/active/test_analytics_events.py (NEW)

**Checkpoint.** Seam: `lib/users_store.py` called directly on a tmp `sqlite3` connection. No server is involved. Assert two things. First, after `ensure_user_schema(conn)` (run twice, to show it is idempotent), `[r[1] for r in conn.execute("PRAGMA table_info(analytics_events)")]` equals exactly `["id","type","track_id","href","page_path","created_at","user_agent","referer"]`. Second, one `insert_analytics_event(...)` inside `with conn:` leaves exactly one row with the passed values, read back through a second connection to the same file.

**Intent.** `users.db` gains an `analytics_events` table, created by `ensure_user_schema` with the settled columns, CHECK and index. `lib/users_store.py` gains an `insert_analytics_event` that writes one row inside the caller's transaction.

- C1 - After `ensure_user_schema`, `analytics_events` has exactly the eight settled columns and none derived from the client address.
- C2 - One `insert_analytics_event` call inside `with conn:` commits exactly one row with the given values.

**Outcome.** ### `client/backend/lib/users_store.py`
- `ensure_user_schema` now also creates `analytics_events` with `CREATE TABLE IF NOT EXISTS`. Its columns are `id INTEGER PRIMARY KEY`, `type TEXT NOT NULL CHECK (type IN ('page_view', 'outbound_click'))`, `track_id TEXT`, `href TEXT`, `page_path TEXT NOT NULL`, `created_at INTEGER NOT NULL`, `user_agent TEXT` and `referer TEXT`. No column comes from the client's address.
- It also creates the index `analytics_events_type_track_created_idx` on `(type, track_id, created_at)` with `CREATE INDEX IF NOT EXISTS`. Running it again leaves the table, the index and the rows alone. The docstring now lists the analytics event table.
- New `insert_analytics_event(conn, event_type, track_id, href, page_path, created_at, user_agent, referer)` runs one parameterised `INSERT` and does not commit, so the row belongs to the caller's transaction, the same way `remove_like` and `close_like` work.
- The event-type argument is called `event_type` so it doesn't shadow the built-in `type`. It goes into the `type` column.

### `tests/active/test_analytics_events.py`
Not created. This step was to write production code only, and the checkpoint in `tests/tmp/` already covers the phase. The phase's files list names this durable test as NEW, so it is still waiting to be written or promoted from the checkpoint.

I did not run the checkpoint: the workflow's run is the one that counts.

#### Phase 2 - Event validator [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_analytics_events.py (EDITED)

**Checkpoint.** Seam: the pure module function `client_server._validate_analytics_event(dict)`, imported the way `test_server.py` imports server internals. Assert that valid `outbound_click` and `page_view` bodies return the expected `(type, track_id, href, page_path)` tuple, including `track_id`/`href` absent versus `null` and unknown keys ignored. Assert that every invalid body in the draft's case list (`type`, `track_id`, `href`, `page_path`, `timestamp` and the page_view-with-extras cases, including the list `type`, lone surrogates and `http://[::1`) returns a `str` and does not raise. The parametrization is taken from the draft's list.

**Intent.** `server.py` gains a pure `_validate_analytics_event` (with `_analytics_href_ok` and `_utf8_safe`) that turns any JSON-decoded dict into either the four storable values or an error message, following the settled rules.

- C1 - Each valid event body yields its `(type, track_id, href, page_path)` tuple.
- C2 - Each invalid event body yields an error string without raising.

**Outcome.** ### `client/backend/server.py`
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

#### Phase 3 - Analytics route [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_analytics_events.py (EDITED), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: real HTTP over a socket to `ClientBackendServer`, through the conftest `client_backend` fixture, with raw `urllib.request` POSTs (the `test_server.py` precedent). The 429 case uses a `_serving_limited` server built like conftest but with the production `RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)` and `X-Forwarded-For: 203.0.113.18`. For accepted events, assert 204 with an empty body and exactly one row. `created_at` must be within the [before, after] `now_ms()` window and not equal the client `timestamp`. UA and Referer must be copied from the headers, and empty or absent values must be NULL. This holds for `application/json` and `text/plain`. For refused POSTs, assert the row count is unchanged: a sample of invalid bodies (empty, `{`, `[]`, `\xff` and one per field) gets 400 with a JSON `error`, and the 91st of 91 gets 429 with `{"error":"Rate limit exceeded"}` and 90 rows. A `GET` of the path gets 404 as a regression line, not as a clause.

**Intent.** `POST /api/analytics/event` in `_serve_post` stores each accepted event as one server-stamped row in `analytics_events`, and stores nothing for a request it refuses.

- C1 - A valid event of either type, with any Content-Type, gets 204 and adds one row whose `created_at`, `user_agent` and `referer` come from the server.
- C2 - A refused POST, whether 400 for an invalid body or 429 over the route limit, adds no row.

**Outcome.** ### `client/backend/server.py`
- `_serve_post` now has a `POST /api/analytics/event` route. Like the other write routes, it checks `_rate_limit_check(url.path)` first. That limiter allows 90 requests per address in 60 s, and the address comes from `X-Forwarded-For` behind a trusted proxy. A request over the limit gets 429 `{"error": "Rate limit exceeded"}` before the body is read. A GET of the path still falls through to the existing 404.
- New `ClientBackendHandler._handle_analytics_event`, which works in four steps:
  - It reads the body with the shared `read_json_body`. That function ignores Content-Type, so `application/json`, `text/plain;charset=UTF-8` and form-encoded `sendBeacon` bodies are all accepted.
  - If the body fails to parse (invalid JSON, a non-object, or non-UTF-8, since `UnicodeDecodeError` is a `ValueError`), it answers 400 with the parse error. An empty body parses to `{}`, which the validator then refuses.
  - It runs the existing `_validate_analytics_event`. A refused event gets 400 with that function's message, and no row is written.
  - A valid event is stored as one row through `insert_analytics_event` inside a `with self.server.user_db:` transaction, and the answer is 204 with an empty body. The server sets `created_at = now_ms()`; the client `timestamp` is validated but never stored. `user_agent` and `referer` come from the request headers, and are NULL when the header is empty or missing.
- `insert_analytics_event` was added to the `lib.users_store` import.

### `tests/active/test_analytics_events.py`, `.un/skills/devsecops/config.json`
Not changed. This step asked for production code only. The checkpoint gates from `tests/tmp/`, and `tests/active/test_analytics_events.py` does not exist in the worktree yet. That file and its `test_groups` entry belong to the promotion of the phase checkpoints, not to this implementation step.

#### Phase 4 - About beacon [code]

**Files touched.** client/frontend/src/about-analytics.ts (NEW), client/frontend/dev-pages/about.template.html (EDITED), tests/active/test_analytics_events.py (EDITED)

**Checkpoint.** There are two seams. (a) `src/about-analytics.ts` is bundled with the project's esbuild into node, the same harness as `tests/active/test_frontend_profile.py`, with `VITE_CLIENT_API_BASE="http://api.test/"` defined. Stubbed `window`, `navigator`, `document` and a rejecting `fetch` are installed before the import. The test is parametrized over the sendBeacon modes true, false, missing and throws. It asserts exactly 2 sends to `http://api.test/api/analytics/event`: a `page_view` for `/about` and then an `outbound_click` with `about_patreon` and its href, where the untracked target and the Text-like target send nothing. It also asserts beacon delivery only in mode true and otherwise fetch with `keepalive: true` and `Content-Type: application/json`, 0 unhandled rejections, and one `click` listener. (b) A real `node_modules/.bin/vite build --outDir <tmp_path>/dist` run from `client/frontend`. It asserts that `dist/dev-pages/about.template.html` has a `src="/assets/*.js"` script whose file contains `/api/analytics/event`. It skips with a reason if `dev-pages/about.html` exists.

**Intent.** The About page template loads a new `src/about-analytics.ts`, which on import sends one `page_view` and then one `outbound_click` per click on an `a[data-track-id]`. Delivery is `sendBeacon` with a keepalive `fetch` fallback, and the built page ships it as a bundled asset.

- C1 - Importing the module sends one `page_view` and one `outbound_click` per tracked click, falling back to keepalive `fetch` when `sendBeacon` is unavailable, refuses or throws.
- C2 - A vite build of the About template references a bundled `/assets/*.js` entry containing `/api/analytics/event`.

**Outcome.** ### `client/frontend/src/about-analytics.ts` (NEW)
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


