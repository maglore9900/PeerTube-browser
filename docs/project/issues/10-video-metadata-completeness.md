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

**Write path in place (from `11-fast-similars-response`).** The single write path this issue extends is `persist_video_metadata` in `engine/server/api/handlers/video.py`, reached through `handle_video_refresh_request`, which both `/api/video` and `/api/video/refresh` run today. It already writes `title`, `description`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw` and `last_checked_at` to `videos`, and the channel's name, display name and followers to `channels`; `language`, `duration`, `thumbnail_url` and the response fields for tags/category are not there yet.

The robustness rule above is current behaviour, not only a requirement. `fetch_instance_video_dynamic` returns `{}` when the video detail call fails or answers empty or non-object JSON, and the DB update and the `instances.last_error*` reset then do not run, so a failed fetch leaves `last_checked_at` untouched too. The write runs under its own statement deadline, so time spent waiting on the instance does not cut it short.

The field-by-field fallback lives in `merge_video_metadata`. Title, description and the channel names fall back to the row when empty (`or`); counts, `tags_json`, `category` and `nsfw` fall back only when missing (`pick_present`, an `is None` test), so a supplied `0` is kept. New fields belong in the same two functions.

The integration check "reflected after the next `/api/video` request" holds for either route today. Once the follow-up plan of issue 11 makes `/api/video` answer from the DB only, it holds only for `/api/video/refresh`.
