# Frontend

Static web UI for PeerTube Browser. It renders recommendations and video pages
using data from the backend API. The client stays UI‑only: no database access and
no ranking logic.

## What it does
- Fetches Client-backend gateway routes (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`).
- Renders feeds (recommendations, random, and similar to one video) and the video page.
- The feed page loads another batch when scrolling reaches the end of the rows fetched so far. Each batch excludes the 500 most recently shown videos, rows already shown are dropped, and paging ends for that page view after a batch that adds nothing or fails (`createFeedPager` in `src/data/videos.ts`). A reload starts over.
- Without a profile key, keeps likes in the browser (`localLikes:v1`), written only after the Client backend accepted them. With a key, likes and dislikes live in the profile: on load each page moves any local likes into it (`POST /api/profile/likes/import`) and clears them once imported, and feed requests carry no likes.
- Shows the visitor's reaction: the video page's Like and Dislike buttons (read from `GET /api/profile/reaction` with a key), and a mark on feed, search and similar-video cards (the Client's `reaction` row field with a key, `localLikes:v1` without). The reaction data lives in `src/data/reactions.ts`.

## Boundary Contract (Frontend-side)
- Frontend must use Client API base (`window.location.origin` or `VITE_CLIENT_API_BASE`) for reads.
- Frontend must not use direct Engine API base or Engine internal endpoints.

## Build
```
npm install
npm run build
```

## Local About Overrides
- Default production source is `client/frontend/dev-pages/about.template.html`.
- Local developer overrides can be placed in:
  - `client/frontend/dev-pages/about.html`
