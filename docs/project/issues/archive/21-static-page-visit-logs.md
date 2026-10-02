# Static page visit logs for About and informational pages

Status: enhancement, complete
Origin: task 43, [M7][F4]

## Problem

Visits to static informational pages (including About) are served as static files by nginx, so they are not visible in app request logs.

## Proposed solution

A dedicated logging path for static page visits, correlated with request tracing where possible.

- Dedicated nginx logging for informational static routes: client IP, method, URL, status, response time, user-agent; a separate stream or an explicit marker field.
- Preserve/propagate `X-Request-ID` in those nginx logs when available.
- A runbook comparing static page visits from nginx logs with API traces from app logs.
- Optional: a client-side pageview beacon for cleaner human-intent tracking.

## Validation (from the original task)

- Visiting informational pages produces entries with the expected fields.
- Correlation by request id/time window works against app traces.

## Related

- After `20-request-lifecycle-logs`.
- `18-about-outbound-click-tracking` instruments the same page as event analytics; do not duplicate.

## Comments

- Delivered by `docs/project/plans/22-21-static-page-visit-logs.md`, as nginx configuration and documentation only, with no app or frontend change. Prod nginx serves About at `/about`, `/about/` and `/about.html` through three exact locations in `DEPLOYMENT.md` §6, which 404ed in prod before. Each About request writes one line in the `peertube_browser_pages` format to `/var/log/nginx/peertube-browser.pages.access.log`, carrying the `page=about` marker and the incoming `X-Request-ID` (`-` when absent), plus its usual line in the main access log, joined by nginx's `$request_id`. The "Follow an About visit" Triage runbook in `DEPLOYMENT.md` lists visits and ties one to the visitor's Client `request.start` records by client IP and a time window. No request id is shared with app records, so that match is probabilistic. For the fields, the commands and the caveats see `DEPLOYMENT.md`. Scoped out: pages other than About, which make API calls that already reach the app logs, and the client-side pageview beacon, which the runbook names as the upgrade path on the beacon endpoint of `18-about-outbound-click-tracking`.
