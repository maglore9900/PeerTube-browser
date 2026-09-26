# About page outbound links: proper click tracking

Status: enhancement, needs-triage
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
