# Static page visit logs for About and informational pages

Status: enhancement, needs-triage
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
