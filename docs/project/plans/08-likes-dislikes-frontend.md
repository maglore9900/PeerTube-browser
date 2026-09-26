# Likes and dislikes: frontend

Status: planned, not approved. The frontend half of the likes and dislikes feature, split from `docs/project/plans/03-like-dislike.md` at that build's Step 2 (T1, operator-approved) to keep each build within four phases. A build re-confirms these requirements at dev_flow Steps 1 and 2.

Depends on: plan 03 (delivered server side). The routes this build calls exist and are described in `client/README.md`.

## Requirements

### What was asked

Plan 03's confirmed criteria that need the browser (L1-L7, D1-D3), carried here unchanged in meaning. Plan 03 holds the full text and the decisions behind them (Q1-Q6).

### Acceptance criteria

- **L1.** On load, the video page shows the like as active when the video is liked: from `GET /api/profile/reaction` with a key, from `localLikes:v1` without one.
- **L2.** An active like is unmistakable: a filled icon and a label change ("Liked"), plus an in-flight state while the request is outstanding.
- **L3.** A like whose request fails leaves the button inactive, shows an error on the page, and stores nothing (today `handleLikeAction` stores in `finally`, `client/frontend/src/pages/video-page/index.ts`).
- **L4.** Clicking an active like sends `undo_like` and, without a key, removes the video from `localLikes:v1` (a `removeLocalLike` in `data/local-likes.ts`, where every mutation of that store lives).
- **L5.** With a key, `fetchSimilarVideosPayload` sends no `likes`; the Client supplies the profile's.
- **L6.** When a key is present and `localLikes:v1` holds entries, the frontend sends them once to `POST /api/profile/likes/import`, then clears the local store.
- **L7.** The My likes modal lists the profile's likes (`GET /api/user-profile/likes`) with a key and `localLikes:v1` without one, and each card has a remove control that behaves as L4 (issue 15).
- **D1 (page half).** Without a key, the dislike control prompts the visitor to create a profile, as the block controls do.
- **D2.** The video page offers dislike and un-dislike (`dislike`, `undo_dislike`); the active state survives reload (from the reaction route) and follows L2 and L3.
- **V1. Card indicator (requested after plan 03 closed).** A video card shows whether the visitor has liked or disliked that video, using the same visual language as the video page's active state (L2). With a key, the Client marks each feed and search row it returns with the profile's reaction, so no per-card request is made. Without a key, liked state comes from `localLikes:v1`. A disliked mark can only appear in search results, because feeds already leave disliked videos out. This needs a small Client backend change, so it is not frontend-only.
- **D3 (page half).** Liking a disliked video, or disliking a liked one, updates both buttons, since the server replaced one with the other.

### Consistency constraints

As plan 03: `data/*.ts` fetch through `resolveClientApiBase` and `profileHeaders`; every rendered value is escaped or set with `textContent`; the existing `ghost-button` and modal markup; `dist/` rebuilt with `npm run build`.

## High-level plan

_Filled at build Step 2._
