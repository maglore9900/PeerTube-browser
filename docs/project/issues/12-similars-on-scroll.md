# Similars on scroll

Status: enhancement, needs-triage
Origin: task 2, [M2][F1]

## Problem

Only 8 similar videos are shown; users want to see more.

## Proposed solution

Remove the separate "similar videos" page and load similars directly on the video page, like the home page: the server returns N similars and the client renders them progressively on scroll.

- The server returns a full batch of similars at once (e.g. `BATCH_SIZE = 48`) in a single response.
- The client keeps the batch in memory and reveals it in chunks as the user nears the bottom.

## Related

- After `09-similars-diversity` and `11-fast-similars-response`.

## Comments

### Up-next responses are random draws (from `09-similars-diversity`)

Plan this issue against what 09 delivered:

- **Each response is a draw, not a fixed page.** A limit-48 request scores the seed's pool (at most `SIMILAR_VIDEO_TOP_K` = 300 rows), takes the top min(4 × 48 = 192, pool size) rows as the window, and draws 48 of them by score-weighted sampling. Two identical requests return different pages. For the draw itself see `engine/server/api/recommendations/docs/OVERVIEW.md`.
- **Scroll paging must exclude shown rows.** A second batch fetched without `exclude` can repeat rows from the first, so paging has to send every row already shown, as `createFeedPager` (`client/frontend/src/data/videos.ts`) does. The Engine removes excluded rows while it builds the pool, so the next batch is drawn from rows not yet shown.
- **No test covers the pager.** `test_frontend_videos.py`, which checked that the pager never repeats a row and stops after an empty batch, was retired to `tests/archive/upnext_random_draw/`. Issue 35 (`35-upnext-tests-retired-by-random-draw.md`) tracks its replacement, which matters most for this issue.
