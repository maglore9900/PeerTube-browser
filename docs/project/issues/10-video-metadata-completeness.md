# Video page metadata completeness: show tags/category and refresh mutable fields

Status: enhancement, needs-triage
Origin: task 3, [M2][F1]

## Problem

The video page does not show all useful metadata (especially tags and category), and the per-request metadata refresh focuses on dynamic stats (views/likes) while other fields may also change.

## Proposed solution

Render tags and category on the video page, and extend the per-request refresh to update mutable video fields from the source instance.

- **UI:** visible blocks for `category` (or its label) and `tags` (chips, with an empty state); compact and consistent with the existing metadata area.
- **Refresh on video request:** keep the `views`/`likes` refresh; also refresh `title`, `description`, `tags`, `category`, and optionally `language`, `nsfw`, `duration`, `thumbnail_url`; one write path with clear mapping rules.
- **Data model:** tags/category stored in the schema `/api/video` reads; a numeric source category maps to a display label consistently.
- **Robustness — keep the current fallback** in `engine/server/api/handlers/video.py`: instance fetch with `timeout=8` catching `HTTPError`/`URLError`/`TimeoutError`; on failure the response falls back field by field to the DB; the DB update and `instances.last_error` reset run only on a successful refresh. Document it in tests.

## Validation (from the original task)

- Manual: tags/category render on the video page.
- Integration: a source metadata change is reflected after the next `/api/video` request.
- DB persistence on a test DB mirroring the production schema: success and instance-fail fixtures; assert saved `title/description/views/likes/dislikes/tags_json/category/nsfw/last_checked_at`; assert no overwrite on the failed path.
- Regression: stats refresh does not wipe tags/category on partial responses.

## Comments
