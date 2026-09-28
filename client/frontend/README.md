# Frontend

Static web UI for PeerTube Browser. It renders recommendations and video pages
using data from the backend API. The client stays UI‑only: no database access and
no ranking logic.

## What it does
- Fetches Client-backend gateway routes (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`). The video page also reads the source PeerTube instance's API directly: the video metadata fallback, `/api/v1/config`, channels, similar-video view counts and comments.
- Renders feeds (recommendations, random, and similar to one video) and the video page.
- The feed page loads another batch when scrolling reaches the end of the rows fetched so far. Each batch excludes the 500 most recently shown videos, rows already shown are dropped, and paging ends for that page view after a batch that adds nothing or fails (`createFeedPager` in `src/data/videos.ts`). A reload starts over.
- Without a profile key, keeps likes in the browser (`localLikes:v1`), written only after the Client backend accepted them. With a key, likes and dislikes live in the profile: on load each page moves any local likes into it (`POST /api/profile/likes/import`) and clears them once imported, and feed requests carry no likes.
- Shows the visitor's reaction: the video page's Like and Dislike buttons (read from `GET /api/profile/reaction` with a key), and a mark on feed, search and similar-video cards (the Client's `reaction` row field with a key, `localLikes:v1` without). The reaction data lives in `src/data/reactions.ts`.
- Clips the video page's description to 4 lines. A "Show more"/"Show less" button (`#description-toggle`, with `aria-expanded`) appears only while the text is taller than 4 lines, and is re-checked when the width changes. The expanded state lasts for that page view only and is stored nowhere. The text is set with `textContent`.
- Shows the video's comments from its source instance, read-only, in `#comments-section` between the video details and "Similar videos". The browser fetches threads from `https://{host}/api/v1/videos/{id}/comment-threads?start=…&count=20&sort=-createdAt`, newest first, 20 per "Load more comments", which hides once every thread has arrived. "Show N replies" fetches that thread's reply tree once from `/comment-threads/{threadId}` and shows it 20 rows at a time ("Show more replies"), indented by depth; "Hide replies" collapses it and expanding again makes no new request. Only when the first batch has `total` 0 does the page ask `/api/v1/videos/{id}` whether comments are disabled.
- The comments heading reads "Comments (N)" after the first batch. An empty list shows "No comments yet."; a failed first request, disabled comments or no resolvable host/id show "Comments are unavailable on {host}." with a link to the original video. A failed "Load more" or reply load logs one `console.warn`, keeps what is already rendered and leaves the button enabled so a click retries; there is no inline error message. Remote text is set only as text: federated HTML is reduced to plain text with its line breaks kept, links are not clickable and Markdown is shown raw.

## Boundary Contract (Frontend-side)
- Frontend must use Client API base (`window.location.origin` or `VITE_CLIENT_API_BASE`) for Client and Engine data. The video page reads source PeerTube instances directly (see "What it does").
- Frontend must not use direct Engine API base or Engine internal endpoints.
- A `VITE_CLIENT_API_BASE` on another origin than the page works only when the Client backend lists the page's exact origin in `CLIENT_CORS_ORIGINS`; otherwise the browser blocks every API call. `npm run dev` always sets `VITE_CLIENT_API_BASE` (default `http://127.0.0.1:7172`, see `scripts/dev.mjs`), so the dev page is cross-origin. For the variable's syntax see `DEPLOYMENT.md` section 6.

## Debug view
`/videos.html?debug=1` shows each row's ranking metrics. It needs the Engine to run with `RECOMMENDATIONS_DEBUG=1`; otherwise the page shows `Debug mode is disabled`. See `DEPLOYMENT.md` section 7.

## Build
```
npm install
npm run build
```

## Local About Overrides
- Default production source is `client/frontend/dev-pages/about.template.html`.
- Local developer overrides can be placed in:
  - `client/frontend/dev-pages/about.html`
