# Video page metadata completeness: show tags/category and refresh mutable fields

Status: enhancement, complete
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

### Delivered

Delivered by the build plan `docs/project/plans/19-10-video-metadata-completeness.md`.

- **Refresh.** After merging with issue 11, both `/api/video` and `/api/video/refresh` run `handle_video_refresh_request` in `engine/server/api/handlers/video.py`. It writes to `whitelist.db` (`persist_video_metadata`) only when the `/api/v1/videos/{id}` fetch returns a non-empty JSON object; an empty `{}` counts as a failure (issue 11's rule, chosen at merge). `merge_video_metadata` merges source over DB for title, description, stats, tags, category, language, nsfw, duration and thumbnail, and one merged set feeds both the response and the UPDATE. A failed, unreachable, malformed or empty source runs no UPDATE, and the response comes from the DB row. The route's behaviour is described in `engine/server/README.md`.
- **Language column.** `videos.language` holds the PeerTube language code in `crawl.db` (crawler) and `whitelist.db` (`migrate-whitelist.py`). The upgrade order is in `DATA_BUILD.md`.
- **Labels.** `/api/video` returns `category` and `language` as display labels from `engine/server/data/peertube_labels.py`. The stored values stay raw ids and codes.
- **Video page.** The `video-taxonomy` block in `client/frontend/video-page.html` shows category, language and tag chips, with "No tags" when the list is empty.
- **Tests.** The gating checkpoints are `tests/tmp/test_10_video_metadata_completeness_phase1.py` to `phase4.py`, which the harvest moves into `tests/active`.

**Accepted limits:**

- Labels cover PeerTube's default categories and languages only. A plugin-added or renamed entry shows its raw id or code.
- PeerTube's unset category is stored and shown as "Unknown", because the instance sends it as a label.
- Removing a language or a description at the source does not propagate: a null language or an empty description keeps the stored value.
- Refreshes stored in `whitelist.db` are replaced at the next sync, which reloads content tables from `crawl.db`.
- Once issue 11's follow-up plan makes `/api/video` answer from the DB only, a source change shows up after the next `/api/video/refresh`, not after the next `/api/video`.
- The video page's instance-direct fallback (`fetchVideoMetadataFromInstance`) does not map category, language or tags, which diverges from R6. On that path both items stay hidden and the tag list reads "No tags".

**Still owed on main:**

- `engine/crawler/dist/db.js` and `dist/videos-worker.js` were edited by hand. Run `cd engine/crawler && npm install && npm run build` and review the dist diff before merge.
- `client/frontend/dist` is not rebuilt. Run `cd client/frontend && npm run build` and delete the orphaned `dist/assets/video-*` files before merge.
- Manual check: tags, category and language render on the video page, and "No tags" shows for a video without tags.
