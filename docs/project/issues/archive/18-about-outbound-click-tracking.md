# About page outbound links: proper click tracking

Status: enhancement, complete
Origin: task 8c, [M3][F6] (marker was wrong in the old tracker: F6-M3 is the search API)

## Problem

Clicks on external links from `about.html` are visible only indirectly in nginx logs, and are noisy because bots and malformed requests are mixed in.

## Proposed solution

Explicit client event tracking for outbound link clicks on the About page, stored in an API database.

- **Client:** `data-track-id` on each outbound link in `client/frontend/about.html` (e.g. `about_patreon`, `about_github`, `about_youtube`); one delegated click handler for `a[data-track-id]`; send with `navigator.sendBeacon()` to `/api/analytics/outbound-click` (fallback `fetch(..., { keepalive: true })`); payload `track_id`, `href`, `page_path`, `timestamp`.
- **API:** `POST /api/analytics/outbound-click`; validate payload against an allowlist of known ids/hosts; append a row to SQLite.
- **Schema:** `outbound_click_events(id INTEGER PRIMARY KEY, track_id TEXT NOT NULL, href TEXT NOT NULL, page_path TEXT NOT NULL, created_at INTEGER NOT NULL)`, optional `ip_hash`, `user_agent`, `referer`; index on `(track_id, created_at)`.
- **Reporting:** aggregated counts by `track_id`, daily and total; raw events kept.
- **Abuse/noise:** per-IP rate limit; reject unknown `track_id`; no raw IP stored.

Which service owns the endpoint (Client backend vs Engine) and its gateway route is not decided in the original task and must be, given the Client/Engine boundary.

## Validation (from the original task)

- Click dispatch sends the correct payload.
- A valid event is stored; an invalid one is rejected.
- Clicking About links increases the counter in the DB.

## Related

- `21-static-page-visit-logs` also instruments the About page: keep this as event analytics and that as request-log visibility.

## Comments

### Issue 21 names this endpoint as its pageview upgrade path

Issue 21 (`docs/project/issues/archive/21-static-page-visit-logs.md`) logs About visits in nginx and adds no endpoint, so the two issues do not overlap. Its runbook ("Follow an About visit" in `DEPLOYMENT.md`) notes that bots and crawlers appear in the nginx pages log. Counting human visits would need a client-side pageview beacon sent to this issue's endpoint. That endpoint is planned above as click-specific (`/api/analytics/outbound-click`, `outbound_click_events`). Its design should also accept a page-view event type, so pageviews do not need a second endpoint.

### Delivered

Delivered by `docs/project/plans/23-18-about-outbound-click-tracking.md`. The Client backend owns the endpoint, and the Engine is untouched. `client/frontend/src/about-analytics.ts` sends one `page_view` when the About page loads and one `outbound_click` per click on an `a[data-track-id]` link, by `sendBeacon` with a keepalive `fetch` fallback. `POST /api/analytics/event` stores each valid event as one row in `users.db`. Issue 21's nginx pages log is unchanged. For the route's contract see `client/README.md`, for what an About override adds see `client/frontend/README.md`, and for the count queries and their caveats see "Count About analytics events" in `DEPLOYMENT.md`. Departures from the text above: one route, `POST /api/analytics/event`, takes both event types instead of `/api/analytics/outbound-click`; the table is `analytics_events`, with a `type` column, instead of `outbound_click_events`; events are validated by shape (`track_id` matching `[a-z0-9_]{1,64}`, an absolute http(s) `href`) instead of an allowlist of ids and hosts, because the real About page is an untracked local override whose links the repository cannot know; no `ip_hash` or other value derived from the client address is stored, and the rate limit is the shared in-memory per-address limiter; `client/frontend/dev-pages/about.template.html` and the override documentation changed, not `client/frontend/about.html`. Prod sends beacons only after the next `scripts/sync.sh` rebuilds `dist/`. Follow-ups: every handler thread shares one `user_db` connection (`check_same_thread=False`), a race this route inherits from the other write routes; `tests/active/test_static_page_visit_logs.py`, which `DEPLOYMENT.md` cites, does not exist and has no group in `.un/skills/devsecops/config.json`; the durable `tests/active/test_analytics_events.py` and its group do not exist, and the build's coverage is only its phase checkpoints in `tests/tmp/`.
