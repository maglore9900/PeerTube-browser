# Batch like resolution into a single Engine call

Status: bug, needs-triage
Origin: task 83, SI3-M1 — security audit run 1, finding F8

## Problem

`resolve_videos_by_uuid_host` in `client/backend/lib/engine_api_client.py` issues one sequential Engine POST per submitted like, up to 200 per request (`MAX_CLIENT_LIKES`), each taking the Engine `db_lock`.

## Proposed solution

Use the existing batch metadata endpoint.

1. Replace the per-entry loop in `resolve_videos_by_uuid_host` with one batched Engine call.
2. Lower `MAX_CLIENT_LIKES` to a value justified by the frontend's actual usage.
3. Confirm the likes page renders the same rows as before the change.

## Related

- Touches the same profile/likes request path as `07-profile-key-identity`. The old order landed 07 first so the batched resolution is written against the resolved profile identity rather than a caller-supplied `user_id`.

## Comments
