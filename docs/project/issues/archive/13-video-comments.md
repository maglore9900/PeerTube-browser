# Read-only comments under the video

Status: enhancement, complete
Origin: task 4, [M2][F1]

## Problem

Comments are not displayed under the video.

## Proposed solution

The server or client requests comments from the source instance and renders them under the video description.

- Fetch via the instance API (or a server proxy) and render below the description block.
- Placeholder/loader, pagination and batch limits so the page is not overloaded.
- No comment input (view-only).
- First verify on a specific video which request fetches comments, and render from that response structure.

## Related

- Depends only on the comments enrichment of the dataset build; may land any time after it.

## Comments

### Delivered

Delivered by `docs/project/plans/archive/19-13-video-comments.md`. What the section shows and which requests it makes is described in `client/frontend/README.md`.

- **No proxy.** The browser fetches comments straight from the source instance, as the video page already does for its metadata fallback. Nothing was added to the Client backend or the Engine.
- **Dependency not needed.** The comments enrichment (`npm run crawl:videos:comments`) stores only `videos.comments_count`, not comment content. The page reads comments from the instance when the video is viewed, so the build did not use it.
- **Unconfirmed constant.** `COMMENTS_POLICY_DISABLED = 2` in `client/frontend/src/pages/video-page/index.ts` is expected to be PeerTube's `VideoCommentPolicy.DISABLED` value, but the plan's live check against a real instance (R3) was never run. If that check gives a different value, only this constant and its test fixture change.
