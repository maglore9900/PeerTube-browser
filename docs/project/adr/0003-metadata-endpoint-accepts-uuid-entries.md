# ADR-0003: `/internal/videos/metadata` resolves browser likes by (uuid, host) in one call

Status: accepted
Date: decided in triage of issue 03 (batch like resolution)

## Context

Browser likes identify a video by `(video_uuid, instance_domain)`. The Client backend resolved each one to the canonical `(video_id, instance_domain)` with its own `/internal/videos/resolve` call — up to 200 sequential calls per request, each holding the Engine's global `db_lock` — and then fetched metadata with a second, batched call.

## Decision

1. `/internal/videos/metadata` accepts entries keyed **either** by `{video_id, instance_domain}` **or** by `{video_uuid, instance_domain}`, mixed in one body, and answers them under a single `db_lock` hold. The Client backend's likes page and likes import both use it; the per-like resolve loop is removed.
2. A request body carries at most **50** like entries (`MAX_CLIENT_LIKES`, the browser's own local-likes limit), on the likes page, the import, and the `/recommendations` proxy alike. Entries past the cap are dropped, not rejected.

A separate batch-resolve endpoint that kept resolve's exact semantics was considered and not taken: it costs the likes page a second Engine call for no benefit to that page.

## Consequences

- Likes import now inherits the metadata endpoint's filtering: a video at or over the Engine's error-count threshold is not imported. Before, it was.
- `/internal/videos/resolve` stays for single-video lookups (user actions).
