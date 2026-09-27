# Engine Server

Read-only Engine API for PeerTube Browser recommendations and video metadata.
This service does not own user write/profile endpoints.

## What it does
- `/recommendations` recommendations.
- `/videos/{id}/similar` and `/videos/similar` read aliases.
- `/api/video` metadata for the video page.
- `/internal/videos/resolve` internal read lookup for Client (`video_id/uuid + host`).
- `/internal/videos/metadata` internal metadata batch lookup for Client likes/profile. Entries are `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, and one body may mix both; an entry with a non-empty `video_id` counts as the id form even when it also carries `video_uuid`. The uuid match is exact and case-sensitive, and where several videos share a `(video_uuid, instance_domain)` the lowest `video_id` wins. All entries are answered under a single `db_lock` hold, with one row per video in the order of the first entry that matches it. Unembedded videos are never returned. Uuid entries leave out videos at or over the error-count threshold; for id entries the threshold applies only to the last pair of each 450-entry chunk.
- `/internal/dislikes/centroids` clusters a set of disliked videos into up to four taste centroids for the Client; nothing is stored. It takes only `{video_id, instance_domain}` entries.
- `/internal/events/ingest` temporary trusted bridge ingest for normalized events (`ENGINE_INGEST_MODE=bridge`). A successful ingest also runs the raw-event retention strip, at most once an hour: events older than `INTERACTION_RAW_RETENTION_DAYS` (default 30) lose their actor, payload and source instance but keep their ids (`docs/project/adr/0005-raw-event-retention-keeps-ids.md`). For setting the window see `DEPLOYMENT.md`.

## Boundary Contract (Engine-side)
- Engine owns read/analytics APIs and internal read/ingest contracts.
- Engine does not own browser-facing write/profile routes (`/api/user-action`, `/api/user-profile/*`).
- Engine runtime must not depend on `engine/server/db/users.db` for recommendation ranking.
- Client backend integration with Engine must go through HTTP contracts, not direct Engine module or DB coupling.

## Notes
- Reads from `DEFAULT_DB_PATH` and FAISS index.
- POST `/recommendations` and POST `/videos/similar` validate the client `likes` list the same way and answer 400 when it is too long or holds a malformed entry. For the limit and the error bodies see `engine/server/api/recommendations/docs/OVERVIEW.md`.
- Recommendation ranking does not depend on local users likes DB; likes, dislike
  centroids and the videos a paging client excludes are read from request-scoped client
  input, and write-derived signals are consumed from aggregated `interaction_signals`.
- Test docs:
  - `engine/server/db/jobs/docs/MODERATION_INTEGRATION_TEST.md`
  - `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`
