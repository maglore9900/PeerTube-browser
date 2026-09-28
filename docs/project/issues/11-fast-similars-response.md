# Fast response with similars on the video page

Status: enhancement, needs-triage
Origin: task 1, [M2][F1]

## Problem

Until the server receives a response from the source instance, the client shows an empty page; some instances respond slowly.

## Proposed solution

Show similar videos first (fast, from the local DB), then load the current video's metadata when it arrives.

- Opening the video page starts two independent requests in parallel: similars, and metadata for the current video.
- The server answers the similars request immediately from local cache/DB, without waiting for the instance.
- Metadata refresh goes through a separate request to the instance, is saved to the DB, and updates the UI.

## Related

- After `09-similars-diversity`; before `12-similars-on-scroll`.

## Comments

### First plan delivered (`docs/project/plans/19-11-fast-similars-response.md`)

The operator chose the two-phase metadata reading: the panel renders immediately from the Engine's DB row, and a separate refresh request fetches live metadata from the instance, persists it, and updates the page when it arrives. The first of two plans is in place. The issue stays open because the page still renders nothing until `/api/video` returns from the instance.

**Delivered:**
- **Refresh route.** The Engine answers `GET /api/video/refresh` (`handle_video_refresh_request` in `engine/server/api/handlers/video.py`) with the instance's live values merged over the DB row field by field, in the same shape as `/api/video`. `/api/video` currently runs the same handler.
- **Persist only on instance success.** The `videos`/`channels` UPDATE and the `instances.last_error*` reset run only when the instance's video detail call answered, under their own statement deadline. This is an accepted behaviour change and already applies to `/api/video`: a failed instance fetch no longer writes, bumps `last_checked_at` or clears `instances.last_error*`.
- **Client proxy budget.** `client/backend/server.py` proxies the refresh with a 20 s timeout and no retry. Every other proxied read keeps 10 s and one retry.
- **Similars not delayed.** The refresh's instance calls run outside `db_lock`, which is held only for the row read and the write, so a slow refresh leaves the similars route answering.

**Still to do, in the follow-up plan:**
- `/api/video` answering from the DB only, with no instance call and no write (R1).
- The page coordinator: three independent requests on load, with the refresh winning in either arrival order (R3).
- A first render that waits on no instance request, including `/api/v1/config` (R4).
- Rendering from URL params when the Engine has no row (R5).
- The re-render guards: embed `src`, button listeners, reaction fetch (R6).
