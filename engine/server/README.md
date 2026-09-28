# Engine Server

Engine API for PeerTube Browser recommendations and video metadata. It is read-only apart from the per-request video metadata write-back described under `/api/video` below.
This service does not own user write/profile endpoints.

## What it does
- `/recommendations` recommendations.
- `/videos/{id}/similar` and `/videos/similar` read aliases.
- `/api/video` metadata for the video page, looked up by `id` (or `video_id`) and optional `host` (or `instance_domain`); a missing id answers 400 `Missing video id` and an unknown video 404 `Video not found`. It reads the DB row, then fetches live metadata from the source instance (the video detail `/api/v1/videos/{id}`, then its channel, each with an 8 s socket timeout and outside `db_lock`) and merges it over the row field by field: title, description, stats, tags, category, language, nsfw, duration and thumbnail. A field the source leaves absent, null or invalid keeps its DB value. Besides the title, channel, account, URL and stats keys, the response carries `tags` (list), `category`, `language`, `nsfw` (bool or null), `duration` (seconds or null) and `thumbnailUrl`. Category and language are stored as PeerTube ids and codes and answered as PeerTube's default labels (`data/peertube_labels.py`), or as the raw id or code when there is no default label. The route needs a `whitelist.db` migrated by `db/jobs/migrate-whitelist.py`, which adds `videos.language`; without it every request fails with `no such column: v.language`. For the upgrade order see `DATA_BUILD.md`.
- `/api/video/refresh` gives the same answer in the same shape as `/api/video`. It is the route the Client proxies with its own budget; for that budget see `client/README.md`.
- Both video metadata routes write the merge back only when the instance's video detail call answered with a non-empty JSON object: the `videos` UPDATE (including `language`, `duration`, `thumbnail_url` and `last_checked_at`), the `channels` UPDATE when the row has a channel, and the reset of `instances.last_error`/`last_error_at`/`last_error_source`. The write runs under its own statement deadline, and a `sqlite3.OperationalError` is logged without failing the response. A detail call that failed, was unreachable or answered a malformed, empty or non-object body writes nothing, and the response then carries the DB values.
- `/internal/videos/resolve` internal read lookup for Client (`video_id/uuid + host`).
- `/internal/videos/metadata` internal metadata batch lookup for Client likes/profile. Entries are `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, and one body may mix both; an entry with a non-empty `video_id` counts as the id form even when it also carries `video_uuid`. The uuid match is exact and case-sensitive, and where several videos share a `(video_uuid, instance_domain)` the lowest `video_id` wins. All entries are answered under a single `db_lock` hold, with one row per video in the order of the first entry that matches it. Unembedded videos are never returned. Videos at or over the error-count threshold are left out for both entry forms.
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
- `debug=1` on `/recommendations`, `/videos/similar` and `GET /videos/{id}/similar` works only when the Engine starts with `RECOMMENDATIONS_DEBUG` set to `1`, `true` or `yes`; otherwise it answers 403 `Debug mode is disabled`. For where to set it see `DEPLOYMENT.md` section 7.
- `seed=<int>` on `/recommendations?id=`, `/videos/similar` and `GET /videos/{id}/similar` makes an up-next draw reproducible: a non-negative integer returns the same page for the same pool. Without it, each up-next request draws a different page. A missing, negative or non-integer value gives a random draw, not a 400. The Client gateway does not forward it and answers 400 `Unknown query parameter: seed`, so it works only on requests sent straight to the Engine. For how the page is drawn see `engine/server/api/recommendations/docs/OVERVIEW.md`.
- The Engine sends no CORS headers on any response, and OPTIONS answers a bare 204 (`docs/project/adr/0004-cors-opt-in-by-origin.md`).
- An unexpected failure answers a fixed 500 with no exception text: `Recommendations request failed` from the recommendations/similar routes, including any `ValueError` other than the three seed-resolution texts that answer 400, and `Event ingest failed` from `/internal/events/ingest`. The exception goes to the Engine log, where `EngineJsonFormatter` adds a `traceback` key to any record that carries exception info.
- Recommendation ranking does not depend on local users likes DB; likes, dislike
  centroids and the videos a paging client excludes are read from request-scoped client
  input, and write-derived signals are consumed from aggregated `interaction_signals`.
- Test docs:
  - `engine/server/db/jobs/docs/MODERATION_INTEGRATION_TEST.md`
  - `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`
