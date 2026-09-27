# Batch like resolution into a single Engine call

Status: bug, complete
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

**Triage.** Confirmed against the code. `resolve_videos_by_uuid_host` makes one sequential `/internal/videos/resolve` call per submitted like, each under the Engine's `db_lock`. It serves the unauthenticated `POST /api/user-profile/likes` (the likes page, via `USE_LOCAL_LIKES_PROFILE`) and the profile-gated `POST /api/profile/likes/import`, both capped at `MAX_CLIENT_LIKES = 200`. Step 1 cannot use the metadata endpoint as it stands: that endpoint keys on `(video_id, instance_domain)`, while browser likes carry `(uuid, host)`, so the Engine side changes too. The ordering note under Related is already met: `07-profile-key-identity` is delivered and archived. No existing implementation, no prior rejection.

Decisions (recorded in `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`):

- Extend `/internal/videos/metadata` to accept `{video_uuid, instance_domain}` entries; the likes page becomes one Engine call. Accepted consequence: likes import no longer imports videos at or over the Engine's error-count threshold.
- `MAX_CLIENT_LIKES` is a **per-request** cap on like entries in one body. It becomes 50 (the browser's local-likes limit) everywhere it applies, and excess entries are still dropped silently.

**Delivered** by `docs/project/plans/archive/16-14-batch-like-resolution.md` (adopted from `docs/project/plans/archive/14-batch-like-resolution.md`).

- `/internal/videos/metadata` parses its entries with `_parse_metadata_entries` (`engine/server/api/handlers/internal_client_reads.py`), which accepts `{video_id, instance_domain}` and `{video_uuid, instance_domain}` in one body. It answers both forms under one `db_lock` hold, through `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` (`engine/server/data/metadata.py`), and emits each video once, at its first matching entry. `/internal/dislikes/centroids` keeps `_parse_entries` and accepts only `video_id` entries.
- `POST /api/user-profile/likes` and `POST /api/profile/likes/import` each resolve a request's likes with one `fetch_metadata_for_entries` call. Import records a like from each returned row that the profile has not disliked.
- `resolve_videos_by_uuid_host` is removed from `client/backend/lib/engine_api_client.py`. `resolve_video_seed` and `/internal/videos/resolve` remain for user actions and block-add.
- `MAX_CLIENT_LIKES` is 50 in `client/backend/server.py`, bounding the likes page, the import and the `/recommendations`/`/videos/similar` proxy `likes` list.
- How the uuid path differs from the old resolve (lowest `video_id` wins on a shared pair, no embedding-blob check) is recorded in ADR-0003's Consequences.

## Agent Brief

**Category:** bug
**Summary:** Resolve a batch of browser likes with one Engine call instead of one call per like, and cap a request at 50 like entries

**Current behavior:**
When the Client backend receives browser likes as `(uuid, host)` pairs — on the likes page endpoint (`POST /api/user-profile/likes`, no profile required) and on likes import (`POST /api/profile/likes/import`) — it resolves each pair with its own sequential Engine `/internal/videos/resolve` call. Each call takes the Engine's global database lock. The likes page then makes one more batched `/internal/videos/metadata` call for the resolved `(video_id, instance_domain)` entries. One request may carry up to 200 likes (`MAX_CLIENT_LIKES`), so a single anonymous POST costs up to 201 Engine round trips and 201 lock acquisitions. The same 200 cap trims the `likes` list on the `/recommendations` proxy.

**Desired behavior:**
- **Engine.** `/internal/videos/metadata` accepts each entry either as `{video_id, instance_domain}` (today's form) or as `{video_uuid, instance_domain}`. An entry with both uses `video_id`. Malformed entries are skipped as today, and duplicates within each form are collapsed. Every entry in a request is answered under one `db_lock` hold, with SQL batched like the existing id lookup (chunked; no per-entry query). Rows come back in the order of their first matching entry. A video reached by both forms appears once. The error-count threshold filter applies to both forms. Existing id-keyed callers see no change.
- **Client backend.** The per-like resolve loop is gone. The likes page sends the deduplicated `(video_uuid, instance_domain)` entries in one metadata call and returns its rows. Likes import makes the same one call and records a like for each returned row, using the row's `video_id`, `video_uuid`, `instance_domain`, skipping disliked videos as today.
- **Cap.** `MAX_CLIENT_LIKES` is 50. It bounds like entries per request body on the likes page, the import, and the `/recommendations` proxy likes list. Entries past 50 are dropped, not rejected, and responses are otherwise unchanged.
- The likes page returns the same rows, in the same order, as before the change, for any request of 50 or fewer likes whose videos are all resolvable.

**Key interfaces:**
- Engine `/internal/videos/metadata` request body: `{"entries": [{"video_id"| "video_uuid": str, "instance_domain": str}, ...]}`; response shape unchanged (`{"ok", "count", "rows"}`).
- Engine entry parser (currently `_parse_entries`, shared with `/internal/dislikes/centroids`): the centroids endpoint must keep accepting only `video_id` entries. Either give metadata its own parser or make uuid acceptance opt-in.
- Engine metadata data function (currently `fetch_metadata_by_ids`): gains a uuid-keyed batch path, or a sibling function. `fetch_seed_embeddings_for_likes` shows an existing `(video_uuid, instance_domain) IN (...)` batch query to follow.
- Client `resolve_videos_by_uuid_host`: removed, or reimplemented as one metadata call; `fetch_metadata_for_entries` is the call to use.
- Client constant `MAX_CLIENT_LIKES`: 200 → 50.

**Acceptance criteria:**
- [ ] A likes-page request with N (≤ 50) likes causes exactly one Engine HTTP call, and one `db_lock` acquisition on the Engine.
- [ ] A likes-import request with N likes causes exactly one Engine HTTP call and records a like for each resolvable, non-disliked, non-errored video.
- [ ] A request with 60 like entries processes only the first 50 and returns 200.
- [ ] The likes page returns rows in submitted order, deduplicated, and a like whose video is unknown to the Engine is omitted without an error.
- [ ] `/internal/videos/metadata` with id-keyed entries returns the same rows as before; mixed id and uuid entries in one body both resolve.
- [ ] `/internal/dislikes/centroids` rejects or ignores uuid-keyed entries as it does today.
- [ ] The `/recommendations` proxy forwards at most 50 likes.
- [ ] Existing Client backend and Engine test suites pass.

**Out of scope:**
- The single-video `/internal/videos/resolve` endpoint and the user-action path that uses it.
- The profile's stored-likes limit (`MAX_LIKES = 100`) and the browser's local-likes limit.
- Rate limiting of these endpoints (issue 02).
- The `USE_LOCAL_LIKES_PROFILE` switch or any frontend change.
