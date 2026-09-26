# Likes and dislikes: frontend

Status: delivered (Steps 1-9 closed; Step 10 harvest below). The frontend half of the likes and dislikes feature, split from `docs/project/plans/03-like-dislike.md` at that build's Step 2 (T1, operator-approved) to keep each build within four phases.

Depends on: plan 03 (delivered server side). The routes this build calls exist and are described in `client/README.md`.

## Requirements

### What was asked

"Execute a development task under the DevSecOps flow: docs/project/plans/08-likes-dislikes-frontend.md". The criteria are plan 03's confirmed criteria that need the browser (L1-L7, D1-D3), plus V1 (card indicator), which was requested after plan 03 closed. Plan 03 holds the decisions behind them (Q1-Q6).

### Purpose

Make the like and dislike state honest and visible in the browser, and move a profile holder's likes off the browser: with a key, `users.db` is the source of truth, and the browser neither stores likes locally nor sends them in feed requests.

### Current state (read at Step 1)

- `client/frontend/src/pages/video-page/index.ts`:
  - Line 68: the like handler toggles the `active` class before any request is made. The dislike handler (line 75) only toggles the class.
  - Line 1068: `handleLikeAction` sends `like` and stores in `localLikes:v1` in `finally`, so a failure is also stored, and the failure goes only to `console.warn`.
  - Clicking an active like sends nothing. On load, neither button reflects the stored state.
- `client/frontend/src/data/user-actions.ts`: `sendUserAction`'s `action` type is `"like"` only.
- `client/frontend/src/data/videos.ts:80`: `fetchSimilarVideosPayload` sends `getRandomLikes()` in every body, keyed or not.
- `client/frontend/src/data/user-profile.ts`: `USE_LOCAL_LIKES_PROFILE = true` always reads `localLikes:v1`, via `POST /api/user-profile/likes`.
- `client/frontend/src/pages/videos/index.ts` `renderLikes`: the My likes cards have no remove control.
- `client/frontend/src/data/local-likes.ts`: there is no `removeLocalLike`.
- The server routes this build uses:
  - `GET /api/profile/reaction?uuid=&host=` answers `{liked, disliked}` and needs a key.
  - `POST /api/profile/likes/import` answers `{imported}` and needs a key.
  - `POST /api/user-action` accepts `like`, `undo_like`, `dislike`, `undo_dislike`. The dislike actions need a key.
  - `GET /api/user-profile/likes` needs a key and returns rows with metadata.
- Neither the Client proxy (`client/backend/server.py` `_profile_filter`, `_filter_payload`) nor any card renderer marks a row with the visitor's reaction.

### Acceptance criteria

- **L1.** On load, the video page shows the like as active when the video is liked. The state comes from `GET /api/profile/reaction` with a key and from `localLikes:v1` without one.
- **L2.** An active like is unmistakable: a filled icon and a label change ("Like" → "Liked"), plus an in-flight state while the request is outstanding.
- **L3.** A like whose request fails leaves the button in its previous state, shows an error on the page, and stores nothing.
- **L4.** Clicking an active like sends `undo_like`. Without a key, it also removes the video from `localLikes:v1` through a new `removeLocalLike` in `data/local-likes.ts`, where every mutation of that store lives.
- **L5.** With a key, `fetchSimilarVideosPayload` sends no `likes`; the Client supplies the profile's.
- **L6.** On load of every page (feed, video, search), when a key is present and `localLikes:v1` holds entries, the frontend sends them to `POST /api/profile/likes/import` before the page's first keyed read. It clears the local store only after a successful import (operator, Step 1).
- **L7.** The My likes modal lists the profile's likes (`GET /api/user-profile/likes`) with a key, and `localLikes:v1` without one. Each card has a remove control that behaves as L4 (issue 15).
- **L8. Keyed likes stay on the server** (operator, Step 1). With a key, a like or un-like never writes `localLikes:v1`. Without a key, `localLikes:v1` is written only after a successful request.
- **D1 (page half).** Without a key, the dislike control prompts the visitor to create a profile, as the block controls do, and sends no request.
- **D2.** The video page offers dislike and un-dislike (`dislike`, `undo_dislike`). The active state survives reload (read from the reaction route) and follows L2 ("Dislike" → "Disliked") and L3.
- **D3 (page half).** Liking a disliked video, or disliking a liked one, updates both buttons, because the server replaced one reaction with the other.
- **V1. Card indicator.**
  - A video card shows whether the visitor has liked or disliked that video, in the same visual language as the video page's active state (L2).
  - It covers the shared cards (feed and search, `renderVideoCard`) and the video page's "Similar videos" cards (`renderSimilarCard`) (operator, Step 1).
  - With a key, the Client marks each feed and search row it returns with the profile's reaction, so no per-card request is made.
  - Without a key, liked state comes from `localLikes:v1`.
  - A disliked mark can only appear in search results, because feeds already leave disliked videos out.
  - This needs a small Client backend change.

### Amendment at Step 7 (operator: "fix everything we have talked about in this session in this build")

Found during Phase 1's red runs:
- An unconditional withdraw sent four anonymous `UndoLike`s for a never-liked video into the live `whitelist.db`.
- Explaining the effect exposed a counting fault in the Engine. Ingest keeps `interaction_signals.likes_count` net of undos (`engine/server/data/interaction_events.py:200-215`; contract test `engine/server/db/jobs/tests/test-interaction-events.py:95`, "likes_count should account for undo").
- But `engine/server/data/random_videos.py:45` (the `likes` of random rows) and `:248` (the popular-order tiebreak) subtract `undo_likes_count` again, so a like followed by its un-like leaves a video one like below where it started.
- `tests/run-installers-smoke.sh:525-537` rebuilds `interaction_signals` with a gross `likes_count`, which contradicts ingest.

- **E1.** A like that is undone is neutral in the Engine. After a `Like` and its `UndoLike` are ingested for a video, the `likes` that `fetch_random_rows` reports and the popular order's likes tiebreak equal what they are with no events. The operator's words: "if I like an already liked video it should unlike and become neutral".
- **E2.** The installer smoke's signal rebuild writes `likes_count` net of undos, as ingest does.
- **E3 (data, not code).** The four stray anonymous `UndoLike` rows this build's red runs wrote for `fd640a96-d208-454d-9892-2872cb33a6bb@yt.orokoro.ru` are removed from the live `interaction_raw_events`. That video's `interaction_signals` row, which holds only their effect (`likes_count 0, undo_likes_count 4, signal_score 0.0`), is deleted, returning it to "no events".
- **O1 stands.** Checkpoints still publish `Like`/`UndoLike` pairs, which after E1 are neutral.

### In scope / out of scope

In scope:
- Frontend: `data/local-likes.ts`, `data/user-actions.ts`, `data/user-profile.ts`, `data/videos.ts`, a new reaction/import data function, `components/video-card.ts`, `pages/video-page/index.ts`, `pages/videos/index.ts`, `pages/search/index.ts`, `video-page.html`, the CSS, and `dist/` rebuilt with `npm run build`.
- Client backend: the reaction mark on proxied feed and search rows (`server.py`, and a users-store read of liked keys).

Out of scope:
- Any change to what the Engine ranks or returns.
- The upstream like and dislike counts shown beside the buttons, which stay the instance's numbers.
- Issue 01.
- Sending likes to the source instance.

### Consistency constraints

- `data/*.ts` fetch through `resolveClientApiBase` and `profileHeaders`, and read errors as the neighbouring modules do.
- Every rendered value is escaped or set with `textContent`.
- The UI uses the existing `ghost-button` / `icon-button` and modal markup, and a `role="status"` element beside the buttons, as `block-status` is.
- Every `localLikes:v1` mutation lives in `data/local-likes.ts`.
- The Client backend follows plan 03's style.
- New code matches existing style (args, names, structure). Backwards compatibility is not required.

### Conflicts

- **L3 "stores nothing" against today's `finally` store.** Replaced by this build.
- **V1 "frontend" against a backend change.** Accepted in the plan text: the Client marks rows.
- None open.

### Test trees for this build

- `active`: `tests/active`
- `working`: `tests/tmp`

### Baseline suite state

Step 0, `scripts/validate_tests.py` bare run: "unchanged since 2026-09-26T10:17:34-04:00 — every fingerprint still holds", 48 passed (56.0 s). Reused from the banked record. Green.

Bootstrap: `defaulted` is empty and `conflicts` is empty. The install-step comparison of `agents/` and `commands/` could not run, because reading `.un/agents` is blocked by permissions. Both auditors are available as Task subagents.

## High-level plan

### Approach

- **A1. Reaction data (L1, L3, L4, L8, D2).** The logic moves out of the page into `data/` modules, so a page only renders what they return.
  - `data/user-actions.ts` accepts all four actions.
  - A new `data/reactions.ts` holds three functions:
    - `fetchReaction`: with a key it reads `GET /api/profile/reaction`. Without a key, liked is whether `localLikes:v1` holds the video, and disliked is false.
    - `sendReaction`: sends the action, and only after success, and only without a key, updates `localLikes:v1` (`addLocalLike` for `like`, the new `removeLocalLike` for `undo_like`). A failure throws and stores nothing.
    - `importLocalLikes`: L6, below.
- **A2. Import (L6).** `importLocalLikes` does nothing without a key or with an empty store. Otherwise it posts the store to `POST /api/profile/likes/import` and clears it only on a 200. Each page entry (feed, video, search) awaits it before its first keyed read. A failed import is reported with `console.warn`, and the page continues, keeping the store for the next load.
- **A3. Feed body (L5).** `fetchSimilarVideosPayload` sends `{}` when a key is held, and `{likes}` from `localLikes:v1` only without one.
- **A4. Video page controls (L1-L3, D1-D3).**
  - On load, after the import and once the video's uuid and host are known, the page reads `fetchReaction` and sets both buttons.
  - A click puts the clicked button in flight (disabled, `aria-busy`) and sends the action. The action is `like`/`undo_like` or `dislike`/`undo_dislike`, depending on whether the button is active.
  - On success the page sets both buttons from the result. An active like clears the dislike and vice versa, which is D3's server rule mirrored.
  - On failure both buttons keep their previous state, and the error text goes into a new `role="status"` element beside the buttons.
  - Without a key, dislike writes the profile prompt there and sends nothing.
  - An active button carries `active`, a filled icon (CSS `fill` on `.active svg`), and the label "Liked" / "Disliked". The count beside it stays the instance's count.
- **A5. My likes (L7).**
  - `fetchUserProfileLikes` reads `GET /api/user-profile/likes` with the key and `POST /api/user-profile/likes` from `localLikes:v1` without one. The `USE_LOCAL_LIKES_PROFILE` switch goes.
  - Each modal card gains a "Remove" button, a sibling of the card's link, since a button cannot sit inside an anchor. It calls `sendReaction(undo_like)` and drops the card on success, or shows the error on the card on failure.
- **A6. Card mark (V1).**
  - **Client.** For a keyed request on a filtered route (feeds and search), `_profile_filter` also loads the profile's liked `(video_id, instance_domain)` keys. The row pass in `_filter_payload` sets `reaction: "liked"` or `"disliked"` on matching rows, after filtering, so on feeds only liked rows can carry a mark. A keyed page is therefore rewritten whenever the profile holds likes, dislikes or blocks.
  - **Browser.** One function, `cardReaction(row)`, returns `row.reaction` when a key is held, and `"liked"` when no key is held and `localLikes:v1` holds the row.
  - `renderVideoCard` and the video page's `renderSimilarCard` render the mark as the likes (or dislikes) stat carrying `active` with the filled icon, plus an accessible label, in the same visual language as A4.
- **A7. Build.** `dist/` is rebuilt with `npm run build`.
- **A8. Engine like figure (E1, Step 7 amendment).** `random_videos.py` computes the like figure as `v.likes + COALESCE(sig.likes_count, 0)` in both places, since `likes_count` is already net. **Alternative rejected:** making ingest keep `likes_count` gross. It contradicts the ingest contract test, and the per-event `MAX(0, …)` clamp only makes sense for a net count. **Effect on live rows:** every video with ingested undos shows its like figure raised by its `undo_likes_count`, which is the correct value.
- **A9. Smoke rebuild (E2).** The embedded rebuild writes `likes_count = max(0, likes − undos)`.
- **A10. Stray rows (E3).** A one-off `DELETE` on the live `whitelist.db`, done once and recorded under Phase 1.

### Alternatives

- **Page logic tested through a DOM library (jsdom) added as a dev dependency.** Rejected for now: it adds a dependency, and the behaviour that matters (what is sent, what is stored, what is read) lives in `data/` modules, which the existing node harness already runs against the real Client. It is reconsidered at Step 6 if a clause needs the DOM.
- **V1 marked in the browser from a list of the profile's likes.** Rejected: V1 asks the Client to mark rows. Also, there is no dislike list route, and the likes list route resolves metadata through the Engine on every call.
- **V1 per-card reaction requests.** Rejected by V1 ("no per-card request").
- **Import inside `fetchSimilarVideosPayload`.** Rejected: a hidden write inside a read, and it would miss the video and search pages' own reads.
- **Import blocking the page on failure.** Rejected: a Client or Engine hiccup would blank every page for a keyed visitor with local likes.
- **Optimistic toggling (today's pattern), rolled back on failure.** Rejected: L3 wants the failed state never shown as active. An in-flight state followed by the result is simpler and honest.

### Risks

- **R1. The DOM half is not covered by an automated test.** Button classes, labels, the status line, the modal's remove button and the card mark rendering run only in a browser. They are verified by the operator in their browser with a recipe at Step 8.
- **R2. A keyless un-like publishes an anonymous `UndoLike`.** This happens from the video page and from the My likes modal, as a keyless `like` publishes an anonymous `Like` today. Accepted as plan 03's T4 rule.
- **R3. Keyed feed and search responses are parsed and re-encoded** whenever the profile holds any like. Plan 03's R6 already accepts this cost for blocks and dislikes.
- **R4. The video page's id may not be a uuid.** The reaction route and `localLikes:v1` key on uuid, so the reaction read waits for metadata and uses `resolveLikeUuid`, as the like store does today. A video with no resolvable uuid shows both buttons inactive.
- **R5. The liked mark rarely shows on keyed feeds.** The Engine excludes the five sampled seed likes from the page. A liked video appears on a feed only when it was not among the five sampled.

### Tradeoffs

- **T1.** The data-layer behaviour is gated by node checkpoints against the real Client. The DOM rendering is checked by the operator in a browser (R1).
- **T2.** A failed import never blocks a page. It retries on the next load.
- **T3.** With a key, the browser holds no copy of its likes. A lost key loses them, as plan 03's R4 records.

Approved by the operator at Step 2 ("Approve").

## Impacts

### I1 Local likes store
- **path:** `client/frontend/src/data/local-likes.ts`
- **Changes:** `removeLocalLike(videoUuid, instanceDomain)`, the one new mutation, beside `addLocalLike`. `hasLocalLike(videoUuid, instanceDomain)` is a read for L1 and V1.
- **Depends on it:** `pages/video-page` (today `addLocalLike`), `pages/videos` (`clearLocalLikes`), `data/videos.ts` (`getRandomLikes`), `data/user-profile.ts` (`getStoredLikes`), and the new `data/reactions.ts`.
- **Regression risk:** low. It adds functions and changes none.

### I2 User action sender
- **path:** `client/frontend/src/data/user-actions.ts`
- **Changes:** the `action` type widens to `"like" | "undo_like" | "dislike" | "undo_dislike"`. An optional `uuid` is sent beside `video_id` and `host` (Step 4, pass 1).
- **Depends on it:** `pages/video-page` (`handleLikeAction`) and the new `data/reactions.ts`.
- **Regression risk:** low.

### I3 Reactions data module (NEW)
- **path:** `client/frontend/src/data/reactions.ts`
- **Changes:** new. `fetchReaction`, `sendReaction`, `importLocalLikes` and `cardReaction`, as A1, A2 and A6 describe.
- **Depends on it:** the three page entries and both card renderers.
- **Regression risk:** medium. It owns the keyed/keyless split (L8) and the import's clear-on-success rule.

### I4 Feed fetch
- **path:** `client/frontend/src/data/videos.ts` (`fetchSimilarVideosPayload`, line 78)
- **Changes:** the body is `{}` with a key and `{likes}` without one.
- **Depends on it:** `pages/videos` (home, random, similar), `pages/video-page` (similar list), `tests/active/test_frontend_blocks.py` (bundles it and runs it keyed; its assertions are about blocked channels, not the body).
- **Regression risk:** low. The Client already replaces keyed likes, so the Engine's input is unchanged.

### I5 My likes data
- **path:** `client/frontend/src/data/user-profile.ts` (`fetchUserProfileLikes`, `USE_LOCAL_LIKES_PROFILE`)
- **Changes:** with a key, `GET /api/user-profile/likes` with `profileHeaders()`. Without one, today's POST of `localLikes:v1`. The constant goes.
- **Depends on it:** `pages/videos` (both "My likes" and "Profile" buttons, the latter swallowing a failure into `[]`). `tests/active/test_frontend_profile.py` bundles `resetUserProfileLikes` from this module only.
- **Regression risk:** low. A 401 on the keyed GET surfaces as an error, and the "Profile" button still opens.

### I6 Shared video card
- **path:** `client/frontend/src/components/video-card.ts` (`renderVideoCard`)
- **Changes:**
  - A reaction option (`options.reaction: "liked" | "disliked" | null`).
  - The likes or dislikes stat carries `active`, and an `aria-label` / `title` "You liked this" / "You disliked this".
  - The article carries a `liked`/`disliked` class.
  - The component stays free of page state: the caller passes `cardReaction(row)`.
- **Depends on it:** `pages/videos` (`renderFeedCard`) and `pages/search` (`renderRows`).
- **Regression risk:** low. Markup is only added, and every value stays escaped.

### I7 Feed page
- **path:** `client/frontend/src/pages/videos/index.ts`
- **Changes:**
  - `loadVideos` awaits `importLocalLikes` once before its first fetch.
  - `renderFeedCard` passes `cardReaction(row)`.
  - `renderLikes` gains a Remove button per card, a sibling of the link, handled by delegation on `profileModalBody`, which calls `sendReaction(undo_like)`.
  - The card goes on success. On failure the error shows on the card.
- **Depends on it:** `index.html` and `videos.html` (both load this entry).
- **Regression risk:** medium. The modal's markup is built with `innerHTML` from remote titles; the new button carries only escaped uuid/host data attributes.

### I8 Search page
- **path:** `client/frontend/src/pages/search/index.ts`
- **Changes:** awaits `importLocalLikes` before its first `loadPage`. `renderRows` passes `cardReaction(row)`.
- **Regression risk:** low.

### I9 Video page
- **path:** `client/frontend/src/pages/video-page/index.ts`
- **Changes:**
  - `toggleReaction` and `handleLikeAction` are replaced by a reaction controller: a load-time `fetchReaction` after metadata and the import, click → in-flight → `sendReaction` → set both buttons, error or prompt in the status element.
  - `applyActionIcons` also inserts a label span.
  - `loadSimilarVideos` awaits the import.
  - `renderSimilarCard` renders the mark from `cardReaction(row)`.
- **Depends on it:** `video-page.html`.
- **Regression risk:** medium. It is the only page wiring both buttons, and R4's uuid resolution is here.

### I10 Video page markup
- **path:** `client/frontend/video-page.html` (lines 74-85)
- **Changes:** a `<span class="reaction-label">` inside each button (text "Like"/"Dislike") and a `<span id="reaction-status" class="block-status" role="status">` after the buttons.
- **Regression risk:** low.

### I11 Video page styles
- **path:** `client/frontend/src/video.css` (`.ghost-button.active`, `.icon-button svg`, `.similar-card-item`)
- **Changes:**
  - `.icon-button.active svg` is filled.
  - `[aria-busy="true"]` is dimmed.
  - The similar card's mark style is added.
- **Regression risk:** low.

### I12 Feed/search styles
- **path:** `client/frontend/src/videos.css` (`.stat`, `.like-card`)
- **Changes:** `.stat.active` is filled and accented, and the like-card remove button is laid out. `search.html` imports `videos.css` (`pages/search/index.ts:9`), so both pages share it.
- **Regression risk:** low.

### I13 Built assets
- **path:** `client/frontend/dist/`
- **Changes:** rebuilt with `npm run build`, as plans 06 and 07 did.
- **Regression risk:** low. It is generated.

### I14 Client read proxy: reaction mark
- **path:** `client/backend/server.py` (`_profile_filter` lines 370-397, `_filter_payload` line 999, `RowFilter` line 66)
- **Changes:**
  - `_profile_filter` also loads the profile's liked `(video_id, instance_domain)` keys for every filtered route, and returns a filter whenever blocks, dislikes or likes exist.
  - `RowFilter` gains the liked keys.
  - `_filter_payload` sets `reaction` on the rows it keeps: `"liked"` for liked keys, and `"disliked"` for disliked keys on search. Feeds drop disliked rows first, and search loads dislikes for the mark only.
  - Today `disliked` is loaded on feeds only. It is now loaded on search too, and used there only to mark, never to filter (D6 unchanged).
- **Depends on it:**
  - every keyed feed and search request;
  - `tests/active/test_blocks.py`, `test_dislikes.py` and `test_profiles.py`, which compare row membership, never whole-row equality (checked: no `==` on rows);
  - `tests/active/test_frontend_blocks.py`.
- **Regression risk:** high. Every keyed read passes through it, and D6 (search unfiltered by dislikes) must hold while search now loads dislikes.

### I15 Client users store: liked keys
- **path:** `client/backend/lib/users_store.py`
- **Changes:** `load_liked_keys(conn, profile_id) -> set[tuple[str, str]]`, the `(video_id, instance_domain)` of the profile's likes, following `load_disliked_keys`.
- **Depends on it:** I14.
- **Regression risk:** low.

### I16 Existing durable tests
- **path:** `tests/active/test_frontend_blocks.py`, `tests/active/test_frontend_profile.py`, `tests/active/test_blocks.py`, `tests/active/test_dislikes.py`, `tests/active/test_profiles.py`
- **Changes:** none planned. They are the regression net for I4, I5 and I14.
- **Regression risk:** medium through I14.

### I17 Boundary check
- **path:** `tests/check-frontend-client-gateway.sh`
- **Changes:** none. The new `data/reactions.ts` fetches Client routes through `resolveClientApiBase`, which the check allows. Run at Step 8.
- **Regression risk:** low.

### I18 Documentation
- **path:** `client/frontend/README.md` (line 10, "Stores likes locally in the browser (temporary profile)", made incomplete by L6/L8), `client/README.md` (line 25, the read gateway; V1 adds the `reaction` mark), `DEPLOYMENT.md` (line 260, keyed feed paragraph; the mark), `CONTEXT.md` (Profile: likes held by the browser without a key), `docs/project/roadmap.md` (lines 14, 41, 135: F12-M2 frontend half delivered), `docs/project/issues/15-remove-single-like.md` (closes with this plan; moves to `archive/` as `complete`).

### I19 Engine random and popular reads (Step 7 amendment)
- **path:** `engine/server/data/random_videos.py` (`fetch_random_rows` line 45, `fetch_popular_videos` line 248)
- **Changes:** drop `- COALESCE(sig.undo_likes_count, 0)` from both expressions.
- **Depends on it:** the random cache and random feed rows (`likes`), and the popular pool's order. Only the tiebreak after `popularity + signal_score` changes.
- **Regression risk:** low. Two expressions; `signal_score` ordering is untouched.

### I20 Installer smoke signal rebuild (Step 7 amendment)
- **path:** `tests/run-installers-smoke.sh` (lines 522-537)
- **Changes:** `likes_count` written net of undos (`max(0, likes − undos)`), matching ingest. `signal_score` is unchanged.
- **Regression risk:** low. It only runs in the installer smoke's cleanup.

### Highest risk

- **I14 read proxy.** Every keyed read passes through it. It now rewrites pages for profiles holding only likes, and it loads dislikes on search while D6 forbids filtering search by them.
- **I3 reactions module.** It owns L8's keyed/keyless split and L6's clear-only-on-success rule. A wrong branch either leaks keyed likes into `localLikes:v1` or loses local likes on a failed import.
- **I9 video page.** It carries every button state rule (L1-L3, D1-D3), and no automated test reaches it (R1).

### Reassessment

#### Pass 1

**1. Will it still work as intended?** Yes, with two corrections to entries (below). Every route the plan calls exists with the shape assumed:
- `/api/profile/reaction` takes `uuid`/`host` and matches on `video_uuid` (`users_store.py:163`).
- `/api/profile/likes/import` is idempotent through `record_like`'s `ON CONFLICT` (`users_store.py:96-98`), so a retried import after a partial failure double-counts nothing.
- `/api/user-action` accepts `uuid` + `host` as well as `video_id` (`server.py:674-695`; `tests/active/test_dislikes.py:52` sends `{action, uuid, host}`).

**2. Ramifications.**
- A keyed profile holding only likes now has every feed and search page parsed and re-encoded (R3).
- Search loads the profile's dislikes, for the mark only.
- Keyed browsers stop sending `likes` in feed bodies, which the Client discarded anyway.
- A keyless un-like publishes an anonymous `UndoLike` (R2).

**3. What else must happen for existing functionality to keep working.**
- The feed over-fetch must stay conditional on blocks or dislikes. A profile with likes only is marked, never over-fetched, so its pages keep today's Engine limit.
- Search must never drop a disliked row (D6).
- `test_blocks.py`, `test_dislikes.py`, `test_profiles.py` and `test_frontend_blocks.py` assert membership of rows, never whole-row equality, so an added `reaction` key breaks none of them (checked by grep: no row `==`).

**4. How the original functionality is altered.**
- The like button no longer toggles before the request.
- A keyed like no longer writes `localLikes:v1`.
- A failed like is no longer stored.
- The My likes modal reads the server with a key.
- The dislike button sends requests.
- Keyed rows carry a `reaction` field.

**Entries the files did not bear out.**
- **I2** said the request shape is unchanged. The reaction flow is keyed on uuid, while `sendUserAction` sends only `video_id` (the page's `id` parameter, which `videoPageUrl` fills from `row.video_id`). Corrected: I2 gains an optional `uuid`, sent when known, as the server accepts.
- **I14** said a filter is returned whenever likes exist, without saying the over-fetch must not follow. Corrected in the entry's changes below.

**Approved changes (pending operator):**
- **I2 amended.** `UserActionInput` gains `uuid?: string`, sent as `uuid` beside `video_id`/`host`. `sendReaction` always sends uuid and host.
- **I14 amended.** `RowFilter` becomes `(block_keys, drop_disliked, liked, disliked)`. `drop_disliked` is the disliked set on feeds and empty on search. `liked` and `disliked` drive the mark on every filtered route. The over-fetch applies only when blocks or `drop_disliked` are non-empty.

**New impacts.** None: both corrections sit inside existing entries.

#### Pass 2

I2, I3, I9 and I14 were re-read against the amendments:
- `resolve_video_seed` is called with `uuid` from the body (`server.py:690-695`), so a uuid-keyed action resolves the same video the reaction route reads.
- `_filter_payload`'s only caller is `_proxy_engine_request` (`server.py:526`), which receives `RowFilter` from `_profile_filter`; the tuple change stays inside `server.py`.

No new impact and no unconfirmed entry. Steps 3-4 converged.

### Documentation to update

Step 9, each against what landed:
- [x] `client/frontend/README.md` — **updated.** The "Stores likes locally (temporary profile)" line is replaced by where likes live with and without a key (written only after acceptance; the per-page import; no likes in keyed feed requests). A line describes the video page's buttons and the card mark, pointing at `src/data/reactions.ts`.
- [x] `client/README.md` — **updated.** The read-gateway bullet: over-fetch only with blocks or dislikes, and keyed rows marked `reaction` `liked`/`disliked`.
- [x] `DEPLOYMENT.md` — **updated.** The likes-and-dislikes paragraph gains the `reaction` mark on keyed feed and search rows, and notes that marking alone does not over-fetch. There was no likes-in-browser statement to correct.
- [x] `CONTEXT.md` — **no update.** "Likes kept server-side … belong to a profile" stays true, and the Interaction signal entry says nothing about the like figure. The file is also being edited by concurrent work outside this build (see below).
- [x] `docs/project/roadmap.md` — **updated.** Delivered gains "F12-M2, likes and dislikes frontend half"; the M2 F12-M2 line is removed (delivered); Implementation order drops the plan-08 step and renumbers.
- [x] `docs/project/issues/15-remove-single-like.md` — **updated.** `Status: enhancement, complete`, and a comment names what delivered it. Moved to `docs/project/issues/archive/15-remove-single-like.md`.
- [x] `docs/project/issues/01-deterministic-event-ids.md` — **updated** (**inventory gap**, found at 9.1). Its out-of-scope list named "the secondary `likes_count - undo_likes_count` tiebreaker", which P5 removed; it now names the tiebreaker as `likes + likes_count`, net of undos.
- **No update, with reasons:**
  - `README.md` line 47 already names reactions and the likes import.
  - `docs/project/security-audit/run-1/*` are historical reports.
  - `docs/project/plans/03-like-dislike.md` is a closed build's record.
  - `docs/project/plans/04-feed-parameter-panel.md` line 27 references `localLikes:v1`'s conventions, which are unchanged.
  - There is no `docs/wiki/`.
- **ADRs:** `docs/project/adr/0001-0005` were read. None is contradicted. ADR-0001 caps `signal_score` in the popular ordering, and P5 changes only the likes tiebreak after it. ADR-0001's derived ids are not yet implemented (`server.py:740` still uses `uuid4`), which is why the checkpoints' anonymous events were stored per event.
- **Concurrent work in the tree, not this build's:** `git status` shows `CONTEXT.md`, issues 01-06 and a new `docs/project/adr/` changed by other work. This build touched only the one issue-01 sentence above.

Approved by the operator at Step 4 ("Approve").

## Implementation plan

### Draft (Step 5)

#### What this build must test

- **F1.** Without a key, `sendReaction` `like` puts the video in `localLikes:v1` and `fetchReaction` reads it liked. `undo_like` takes it out again.
- **F2.** A like whose request fails throws and leaves `localLikes:v1` as it was.
- **F3.** With a key, `sendReaction` changes what `fetchReaction` reads from the profile (like, dislike replacing it, undo), and `localLikes:v1` stays empty.
- **F4.** With a key, `fetchSimilarVideosPayload` sends no `likes`.
- **F5.** `importLocalLikes` records the local likes in the profile and empties the store. A refused import keeps the store.
- **F6.** With a key, `fetchUserProfileLikes` lists the profile's likes, not the local store.
- **F7.** The Client marks keyed feed and search rows with `reaction`: `liked` on both, `disliked` on search, which keeps the row. Keyless rows are unmarked.
- **F8.** `renderVideoCard`, given `cardReaction(row)`, renders the likes or dislikes stat active for a marked row with a key, and for a locally liked row without one.
- **Not reachable in node:** the video page's button states, labels, status line and similar-card mark, and the modal's Remove button wiring. These are DOM behaviour, verified by the operator in a browser (R1, T1).

#### Frontend

`client/frontend/src/types/videos.ts` — `VideoRow` gains `reaction?: "liked" | "disliked" | null`.

`client/frontend/src/data/local-likes.ts`
```ts
export function removeLocalLike(videoUuid: string, instanceDomain: string): void
  // loadLikes() without the matching normalized entry; saveLikes() only when something was removed.
export function hasLocalLike(videoUuid: string, instanceDomain: string): boolean
```

`client/frontend/src/data/user-actions.ts`
```ts
interface UserActionInput {
  videoId: string;
  uuid?: string | null;          // sent as `uuid`; the server resolves either
  host?: string | null;
  action: "like" | "undo_like" | "dislike" | "undo_dislike";
}
// body: { video_id, uuid, host, action }
```

`client/frontend/src/data/reactions.ts` (NEW)
```ts
/** Module docstring: the visitor's reaction to a video. With a profile key the Client backend
 *  holds it; without one only likes exist, in localLikes:v1, written after the server accepted them. */
export type Reaction = { liked: boolean; disliked: boolean };
export type ReactionAction = "like" | "undo_like" | "dislike" | "undo_dislike";
export type ReactionVideo = { uuid: string; host: string };

// The state each accepted action leaves, per the server's rules (a like and a dislike replace each other).
const AFTER: Record<ReactionAction, Reaction> = {
  like: { liked: true, disliked: false },
  undo_like: { liked: false, disliked: false },
  dislike: { liked: false, disliked: true },
  undo_dislike: { liked: false, disliked: false }
};

export async function fetchReaction(apiBase: string, video: ReactionVideo): Promise<Reaction>
  // keyless: { liked: hasLocalLike(uuid, host), disliked: false }
  // keyed: GET /api/profile/reaction?uuid=&host= with profileHeaders(); 401 → ProfileKeyRejectedError;
  //        other !ok → Error(server's error)
export async function sendReaction(apiBase: string, action: ReactionAction, video: ReactionVideo): Promise<Reaction>
  // await sendUserAction(apiBase, { videoId: uuid, uuid, host, action })  — throws on !ok, nothing stored
  // keyless only: like → addLocalLike, undo_like → removeLocalLike
  // returns AFTER[action]
export async function importLocalLikes(apiBase: string): Promise<number>
  // no key or empty store → 0, no request
  // POST /api/profile/likes/import {likes: [{uuid, host}]} with profileHeaders(); !ok → throw (store kept)
  // ok → clearLocalLikes(); return body.imported
export function cardReaction(row: VideoRow): "liked" | "disliked" | null
  // keyed: row.reaction ?? null; keyless: hasLocalLike(uuid, host) ? "liked" : null
```

`client/frontend/src/data/videos.ts` — `body: JSON.stringify(getProfileKey() ? {} : { likes: getRandomLikes() })`.

`client/frontend/src/data/user-profile.ts` — `fetchUserProfileLikes`: with `getProfileKey()`, `GET /api/user-profile/likes` with `profileHeaders()`; otherwise the existing POST of `getStoredLikes()`. `USE_LOCAL_LIKES_PROFILE` and the unreachable branch go.

`client/frontend/src/components/video-card.ts` — `VideoCardOptions.reaction?: "liked" | "disliked" | null`. Rendering:
- The likes stat becomes `stat likes active` with `title`/`aria-label` "You liked this" when the reaction is liked, and likewise for dislikes.
- The article carries a `liked` or `disliked` class.

`client/frontend/src/pages/videos/index.ts`
- A top-level `const localLikesImported = importLocalLikes(apiBase).catch(warnImportFailed)`. `loadVideos` awaits it before `fetchVideosPayload`.
- `renderFeedCard` passes `reaction: cardReaction(row)`.
- `renderLikes`:
  - Each like is `<article class="like-card">` holding `<a class="like-link">` (today's content) and `<button class="ghost-button like-remove" data-uuid data-host>Remove</button>`, both attributes escaped.
  - A delegated `click` on `profileModalBody` calls `sendReaction(apiBase, "undo_like", {uuid, host})`.
  - On success it removes the article, and renders "No likes yet." when none are left.
  - On failure it puts the error in the button's `title` and in a `.like-error` line with `textContent`.

`client/frontend/src/pages/search/index.ts` — the same import promise, awaited in `loadPage` before `fetchSearchResults`. `renderRows` passes `reaction: cardReaction(row)`.

`client/frontend/src/pages/video-page/index.ts`
- Removed: `toggleReaction`, `handleLikeAction`, the `addLocalLike` import, and the click listeners at lines 68-76.
- A top-level `localLikesImported` promise as above. `loadSimilarVideos` awaits it. `renderSimilarCard` adds `<span class="similar-reaction liked|disliked">` (filled thumb icon and "Liked"/"Disliked") when `cardReaction(row)` is set.
- The reaction controller:
```ts
const reactionStatusEl = document.getElementById("reaction-status");
let reaction: Reaction = { liked: false, disliked: false };
// after loadVideo resolves metadata:
async function loadReaction() {
  const video = reactionVideo();            // { uuid: resolveLikeUuid(...), host: resolveLikeHost(...) } or null
  if (!video) return;                       // no uuid: buttons stay disabled, R4
  await localLikesImported;
  try { renderReaction(await fetchReaction(apiBase, video)); }
  catch (error) { setReactionStatus(errorText) }
  enableReactionButtons(video);             // wires once, like enableBlockButtons
}
// like click:    react(likeButton, reaction.liked ? "undo_like" : "like", video)
// dislike click: no key → setReactionStatus("Disliking needs a profile. Create one from the Profile button on the home page."); return
//                else react(dislikeButton, reaction.disliked ? "undo_dislike" : "dislike", video)
async function react(button, action, video) {
  button.disabled = true; button.setAttribute("aria-busy", "true"); setReactionStatus("");
  try { renderReaction(await sendReaction(apiBase, action, video)); }
  catch (error) { setReactionStatus(error instanceof Error ? error.message : "Reaction failed"); }
  finally { button.disabled = false; button.removeAttribute("aria-busy"); }
}
function renderReaction(state: Reaction) {
  reaction = state;
  setReactionButton(likeButton, state.liked, "Like", "Liked");
  setReactionButton(dislikeButton, state.disliked, "Dislike", "Disliked");
}
// setReactionButton: classList.toggle("active"), aria-pressed, `.reaction-label` textContent
```

`client/frontend/video-page.html` — both buttons get `disabled` and a `<span class="reaction-label">Like</span>` / `Dislike`. `<span id="reaction-status" class="block-status" role="status"></span>` goes after the dislike button.

`client/frontend/src/video.css`
- `.icon-button.active svg { fill: var(--accent-strong); }`
- `.icon-button[aria-busy="true"] { opacity: 0.6; cursor: progress; }`
- `.similar-reaction` (pill; `svg` filled).

`client/frontend/src/videos.css`
- `.stat.active { background: rgba(180, 87, 55, 0.22); color: var(--accent-strong); }` and `.stat.active svg { fill: var(--accent-strong); }`.
- `.like-card` becomes the article: grid, gap. `.like-link` takes today's link styles. `.like-remove` and `.like-error` are added.

#### Client backend

`client/backend/lib/users_store.py`
```python
def load_liked_keys(conn: sqlite3.Connection, profile_id: str) -> set[tuple[str, str]]:
    """Return the profile's liked videos as `(video_id, instance_domain)` pairs."""
    # SELECT video_id, instance_domain FROM likes WHERE user_id = ?
```

`client/backend/server.py`
```python
# A profile's blocked channels and accounts, the disliked videos a feed drops, and the liked and
# disliked `(video_id, instance_domain)`s its rows are marked with.
RowFilter = tuple[BlockKeys, set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]

# _profile_filter, after resolving the profile:
block_keys = load_block_keys(conn, profile_id)
disliked = load_disliked_keys(conn, profile_id)
liked = load_liked_keys(conn, profile_id)
drop = disliked if path in FEED_ROUTES else set()   # search is never filtered by dislikes
if not (block_keys[0] or block_keys[1] or disliked or liked):
    return True, None, None, profile_id
if page_size is not None and (block_keys[0] or block_keys[1] or drop):
    query["limit"] = str(page_size * FEED_OVERFETCH_FACTOR)
return True, (block_keys, drop, liked, disliked), page_size, profile_id

# _filter_payload:
block_keys, drop, liked, disliked = row_filter
rows = filter_disliked(filter_blocked(rows, block_keys), drop)
...
for row in rows:
    key = (str(row.get("video_id") or ""), str(row.get("instance_domain") or ""))
    if key in liked:
        row["reaction"] = "liked"
    elif key in disliked:
        row["reaction"] = "disliked"
```
Invariant: a keyless request, or a keyed one whose profile holds nothing, passes the Engine's bytes through untouched, as today.

#### Check against plan and requirements (pass 1)

- L1 → `fetchReaction` + `loadReaction`. L2 → `setReactionButton`, CSS fill, `aria-busy`. L3 → `sendReaction` stores after success; `react` keeps the state on a throw. L4 → `undo_like` + `removeLocalLike`. L5 → `videos.ts` body. L6 → `importLocalLikes` awaited by the three pages. L7 → `fetchUserProfileLikes` + Remove. L8 → `sendReaction` writes locally only without a key. D1 → the dislike click without a key. D2 → dislike/undo_dislike through `react`. D3 → `AFTER` sets both flags. V1 → `_filter_payload` mark + `cardReaction` + both renderers.
- **Miss found and fixed in the draft:** a click before the reaction was read would send `like` for a liked video. Fixed: the buttons are `disabled` in the markup and enabled only after `loadReaction`, following `enableBlockButtons`.
- **Miss found and fixed in the draft:** `sendReaction` returning `AFTER[action]` rather than re-reading the server. It is correct because the server's rules are exactly `AFTER` (a like removes a dislike, a dislike removes a like; `tests/active/test_dislikes.py:68` covers them). A re-read would add a request per click. Kept as `AFTER`.
- Converged in one pass.

### Phases

#### Common seam

- **Harness.** The precedent is `tests/active/test_frontend_blocks.py` and `test_frontend_profile.py`: the frontend's own `src/data/*.ts` (and, in P4, `components/video-card.ts`) bundled by the project's esbuild and run in node against a real Client backend wired to the real Engine.
  - The runner supplies only what node lacks: an in-memory `localStorage`/`sessionStorage` and `window.location.origin`.
  - Each step prints one JSON line.
  - `tests/tmp/conftest.py` is a copy of `tests/active/conftest.py` (the `engine` session fixture, `engine_client`, `unpublished_client`, `dataset`), as plan 03's checkpoints used.
- **Publishing (operator, Step 6: "O1").** A checkpoint that needs a like the Client accepts uses `engine_client` (`bridge`), which writes into the live `whitelist.db`. Every test that publishes a `Like` ends with the `undo_like` that withdraws it. A test that needs no accepted like uses `unpublished_client`.
- **Videos** come from `whitelist.db` read-only (embedded, `error_count = 0`), as `tests/active/test_dislikes.py` `_videos` does. A video the Engine cannot resolve is a well-formed uuid absent from the dataset.
- **Reading state back.** Profile state is read through the Client's routes (`GET /api/profile/reaction`), never from `users.db`. Browser state is read through the module's own readers (`getStoredLikes`, `fetchReaction`).

#### Phase 1 — A keyless visitor's likes are kept only once accepted

- **Kind:** code
- **Files:**
  - EDITED: `client/frontend/src/data/local-likes.ts`, `client/frontend/src/data/user-actions.ts`.
  - NEW: `client/frontend/src/data/reactions.ts` (`fetchReaction`, `sendReaction`, `Reaction` and the action types).
  - NEW: `tests/tmp/conftest.py` (common seam), `tests/tmp/test_frontend_keyless_likes.py` (checkpoint).
- **Intent (post-phase state):** A visitor without a profile key can like a video through `sendReaction` and see it read back as liked by `fetchReaction`, and un-like it the same way. A like the Client does not accept leaves the browser's like store as it was.
- **Clauses:**
  - `C1` — Without a key, `fetchReaction` reads a video as liked after an accepted `like` through `sendReaction`, and as not liked after the `undo_like` that follows.
  - `C2` — Without a key, a `like` the Client refuses makes `sendReaction` throw and leaves `getStoredLikes()` equal to what it returned before the call.
- **Checkpoint and seam:**
  - Node runner, `engine_client` (O1). C1 reads `fetchReaction` for the liked video and, as a control, for a second video never liked.
  - C2 is refused two ways: a uuid the Engine does not know (404 from the Client), and a real video on `unpublished_client` (502, publish not sent). Both run against a store pre-seeded with another like, so "unchanged" is a non-empty value.
  - Red: the scaffold (`reactions.ts` with bodies throwing `Error("not implemented")`) lands first, so the red is behavioural.

**Probe (7.1, observed)** — `tests/tmp/probe_keyless.py`. A keyless `like` of a well-formed unknown uuid through `engine_client` answers `404 {'error': 'Video not found in Engine'}`. A keyless `like` of a real video through `unpublished_client` answers `502` with no `error` field (`bridge_error: 'CLIENT_PUBLISH_MODE=activitypub is not implemented yet'`), which `sendUserAction` reports as `Failed to send action`.

**Self-check (dispatch 1)** — `tests/tmp/test_frontend_keyless_likes.py`

- `C1 — test_frontend_keyless_likes.py:110, fetchReaction after an accepted keyless like — expected: liked True — under a sendReaction that does not store, or a fetchReaction that does not read localLikes:v1: False; under the scaffold: {'error': 'not implemented'} (observed).`
- `C1 — test_frontend_keyless_likes.py:113, fetchReaction after the following undo_like — expected: liked False — under an undo that leaves the store (no removeLocalLike): True.`
- `C2 — test_frontend_keyless_likes.py:134, sendReaction's outcome for an unknown video — expected: throws "Video not found in Engine" — under a sendReaction that swallows the failure: an ok result; under the scaffold: "not implemented" (observed).`
- `C2 — test_frontend_keyless_likes.py:135, getStoredLikes after that refusal — expected: [[kept]] — under a store written in finally (today's handleLikeAction) or before the request: [[unknown], [kept]].`
- `C2 — test_frontend_keyless_likes.py:146-147, the 502 path (unpublished Client) — expected: throws "Failed to send action", store [[kept]] — under store-in-finally: [[video], [kept]].`

Supporting (no row):
- line 111, another video reads not liked, which excludes a fetchReaction answering liked for everything;
- line 112, the undo was accepted;
- line 133, the seeded store is non-empty;
- lines 136-137, the same store takes an accepted like, so "unchanged" means declined, not never-writes.

1. **Whole claim** — C1: liked after the like, not liked after the undo. C2: the throw, pinned to the Client's message, and the unchanged store, on two refusal paths. Name and docstring: every sentence has an assertion (the other video at 111, the accepted like at 136-137).
2. **Absence only** — 113 is armed by 110; 135 and 147 by 134/146 (the request ran and was refused) and 136-137 (the store does take a like).
3. **Echoed literal** — no. "liked" is produced by `sendReaction` writing and `fetchReaction` reading; deleting either production line turns 110 red. The error strings come from the Client.
4. **One value** — two videos, like then undo, two refusal causes.
5. **The double** — none: real Client and Engine; the in-memory `localStorage` is the platform node lacks, as in the precedent.
6. **It collects** — 2 node ids.
7. **Observed** — the probe above.
8. **Red** — exit 1, 2 failed.
9. **Right reason** — line 110, `{'error': 'not implemented'}`, and line 134, `'not implemented' == 'Video not found in Engine'`: the scaffold's bodies. The first run failed at the harness (`_run`'s returncode, line 74, the scaffold's throw crashing node); the runner now reports read errors and the C1 assertion comes first. Control at line 133 passed.
10. **Observed expected output** — yes.

**Checkpoint audit (dispatch 1)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at line 110 (fetchReaction throws, after_like is {"error": "not implemented"}); test 2 passes line 133 and fails at line 134 (sendReaction throws "not implemented").`
- `AUDIT: devsecops-test-claim-auditor — PASS.` The frozen ledger has 18 rows: 17 CARRIED and 1 UNCARRIED. The open row is D9: the docstring says "every Like a test publishes is withdrawn by an undo_like", and `_withdraw` discarded its status.

**Remediation (7.4)**
- **D9 — fixed.**
  - `_withdraw` asserts `status == 200`.
  - Found while fixing it: the first `finally` withdrew unconditionally, so the red runs (the scaffold never published) sent four unmatched anonymous `UndoLike`s for `fd640a96-…@yt.orokoro.ru` into the live `whitelist.db`, and test 1 would also have sent a second `UndoLike` after its own.
  - Withdraw now runs only when a `Like` was accepted and not already undone (lines 111, 138).
  - The docstring says "withdrawn by an accepted undo_like".
- **Recommendation 2 — taken.** Line 115 asserts test 1's `sendReaction` returned.
- **Recommendation 3 — taken.** Lines 157-158 assert that a refused `undo_like` (unpublished Client) throws and keeps the like in the store. This is the "previous state" half of L3 for an un-like.
- **Recommendation 4 — not taken.** `addLocalLike`'s bounds (duplicate, the cap of 50) belong to a function this build does not change.
- **Consequence, handled with the operator.**
  - The stray rows exposed the Engine counting fault, and the operator widened the build (Requirements amendment, Phase 5).
  - **E3 done:** the approved `DELETE` removed 4 rows from `interaction_raw_events` and 1 row from `interaction_signals`. 0 of either remain for that video (observed).

**Self-check (dispatch 2)** — rows re-lined:
- `C1 — :114, fetchReaction after an accepted keyless like — expected: liked True — as dispatch 1 (observed red: {'error': 'not implemented'}).`
- `C1 — :118, after the following undo_like — expected: liked False — under no removeLocalLike: True.`
- `C2 — :141, refusal for an unknown video — expected: throws "Video not found in Engine" — under a swallowing sendReaction: ok; scaffold: "not implemented" (observed).`
- `C2 — :142, store after that refusal — expected: [[kept]] — under store-in-finally: [[unknown], [kept]].`
- `C2 — :154-155, the 502 path — expected: "Failed to send action", [[kept]] — under store-in-finally: [[video], [kept]].`

Supporting (no row):
- 115, sendReaction returned;
- 116, another video not liked;
- 117, the undo accepted;
- 140, the store seeded;
- 143-144, an accepted like is stored;
- 157-158, a refused undo keeps the like.

Answers 2-7 walked again. 2: 118 is armed by 114; 142/155 by 141/154 and 143-144; 158 by 157. 3: no echo. 4: unchanged. 5: no double. 6: 2 node ids. 7: the probe; the refused undo takes the same handler and publish branch as the refused like.
**Still red for its own reason:** exit 1, 2 failed at line 114 (`{'error': 'not implemented'}`) and line 141 (`'not implemented'`). Control at 140 passed. The run published nothing: 0 raw events for either test video (observed).

**Checkpoint audit (dispatch 2)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at line 114 (scaffold throws; after_like.get("liked") is None); test 2 passes line 140 and fails at line 141 ("not implemented" instead of "Video not found in Engine").` Recommendation, taken: line 115's comment claimed "accepted, not merely stored", but `ok` comes from the runner. The comment now reads "sendReaction returned rather than threw". Acceptance by the Client is carried by 141/154/157 in the second test.
- `AUDIT: devsecops-test-claim-auditor — PASS.` This is the bounded re-audit of the frozen ledger. D9, UNCARRIED in round 1, is now CARRIED (`_withdraw` asserts 200, and the withdraw is guarded to accepted Likes). All 18 rows are CARRIED.
  - Observation 1, not taken: if `_run` itself raises (a node timeout or crash) after a Like was published, the guard sees `{}` and skips the withdraw. The runner catches every step's error, so only a hard crash or timeout reaches this path. It is recorded as a known gap.
  - Observation 2: the new refused-undo sentence is carried at 157-158.

**Changes**
- `client/frontend/src/data/local-likes.ts` — `removeLocalLike`, which writes only when an entry went, and `hasLocalLike`.
- `client/frontend/src/data/user-actions.ts` — `action` takes all four actions, and an optional `uuid` is sent.
- `client/frontend/src/data/reactions.ts` (NEW, from its scaffold):
  - `AFTER`, the state each accepted action leaves.
  - `fetchReaction` reads `localLikes:v1`.
  - `sendReaction` sends through `sendUserAction` (uuid and host) and records `like`/`undo_like` in `localLikes:v1` only after the request succeeded.
  - No key handling yet: that is Phase 2's clause.
- `tests/tmp/conftest.py` (NEW, a copy of the active one); `tests/tmp/probe_keyless.py` (probe).
- **Inventory gaps:** none.
- **Live data:** the green run published `Like`, `UndoLike`, `Like`, `UndoLike` for `fd640a96-…@yt.orokoro.ru`, which is matched (O1). Its signals row reads `likes_count 0, undo_likes_count 2`; after Phase 5 that is neutral.

**Checkpoint outcome** — PASS: `test_frontend_keyless_likes.py` 2 passed (11.9 s).

#### Phase 2 — A profile holder's reactions live in the profile

- **Kind:** code
- **Files:**
  - EDITED: `client/frontend/src/data/reactions.ts`, `client/frontend/src/pages/video-page/index.ts`, `client/frontend/video-page.html`, `client/frontend/src/video.css`.
  - NEW: `tests/tmp/test_frontend_keyed_reactions.py` (checkpoint).
- **Intent (post-phase state):** A visitor with a profile key likes, dislikes and un-dislikes a video through `sendReaction`, and `fetchReaction` reads back the state the profile holds. The browser keeps no copy of those likes. The video page shows that state on its two buttons.
- **Clauses:**
  - `C1` — With a key, `fetchReaction` reads the profile's state after each `sendReaction` action: liked after `like`, disliked and not liked after `dislike` on the liked video, neither after `undo_dislike`, and liked and not disliked after `like` on a disliked video.
  - `C2` — With a key, an accepted `like` through `sendReaction` leaves the video out of `getStoredLikes()`.
- **Checkpoint and seam:**
  - Node runner, `engine_client` (O1); the test ends with `undo_like`.
  - C1's expectations are cross-checked by a direct `GET /api/profile/reaction` from Python with the same key, so a `fetchReaction` that answered from memory or from the local store disagrees.
  - C2 is armed by the same `like` without a key in another runner, which does store it (P1's behaviour).
  - The page wiring (buttons, labels, status, prompt) is in this phase's files but outside node's reach (below).

**Self-check (dispatch 1)** — `tests/tmp/test_frontend_keyed_reactions.py`. The steps pause at `wait` (the `_Node` stdin pattern of `tests/active/test_frontend_profile.py`), so Python reads the Client's reaction route between them.

- `C1 — :147, fetchReaction after a keyed like — expected: (True, False) — under a fetchReaction that still reads only localLikes:v1 once sendReaction stops storing keyed likes: (False, False).`
- `C1 — :148, after dislike on the liked video — expected: (False, True) — under a fetchReaction reading localLikes:v1 (the Phase 1 code): (True, False) (observed).`
- `C1 — :149, after undo_dislike — expected: (False, False) — under a fetchReaction that never reads the dislike (keyless reading, a stale like): (True, False).`
- `C1 — :150, after like on a disliked video — expected: (True, False) — under a module-side AFTER state that is never read back while the server kept the dislike: the server pair differs at :152.`
- `C1 — :152, at every step the Client's GET /api/profile/reaction (asked by Python with the same key) equals what fetchReaction read — expected: equal — under a fetchReaction answering from memory or from the local store: differs at step 2 (observed: the module (True, False), the profile (False, True)).`
- `C2 — :180, getStoredLikes after a keyed like — expected: the video absent — under the Phase 1 sendReaction, which stores regardless of the key: present (observed).`

Supporting (no row):
- 141 and 181, the closing un-likes returned;
- 166-167, the same like without a key is stored (arms 180);
- 179, the keyed `sendReaction` returned.

1. **Whole claim** — C1: all four transitions, each also against the profile's own route. C2: the keyed like is absent, armed by the keyless like being present. Name and docstring: each sentence has an assertion.
2. **Absence only** — 180 is armed by 167 (same like, no key, stored) and 179 (the call ran and returned).
3. **Echoed literal** — no. The expected pairs are the server's rules, written as literals, and 152 compares against an independent route.
4. **One value** — four states, two key conditions.
5. **The double** — none.
6. **It collects** — 2 node ids.
7. **Observed** — this run: the profile's reaction at each step (the server list in the failure output), and the Client accepting all four actions in bridge mode.
8. **Red** — exit 1, 2 failed.
9. **Right reason** — C1 at line 148: `(True, False) == (False, True)` fails, because `fetchReaction` read `localLikes:v1` while the profile held a dislike. C2 at line 180: the keyed like was stored. Controls at 147, 166-167 passed.
10. **Observed expected output** — yes.
- **Live data:** this run's events for the test video are matched. The totals across P1 and P2 are 6 `Like`, 6 `UndoLike`, `likes_count 0` (observed).

**Checkpoint audit (dispatch 1)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 148, (True, False) not (False, True), because fetchReaction reads hasLocalLike; line 180, because sendReaction calls addLocalLike regardless of key.` Recommendation: change the profile out of band so a local mirror of `AFTER` cannot pass.
- `AUDIT: devsecops-test-claim-auditor — BLOCK.` The frozen ledger has 21 rows, 8 UNCARRIED: C1e, C1f, C2a, D2, D8, N2, N3, N4.
  - Critical 1 (C1f/D2/N2): a `fetchReaction` mirroring `sendReaction`'s results passes, since the profile only changes through the module.
  - Critical 2 (C1e): the dislike before "like on a disliked video" is unchecked.
  - Critical 3 (C2a/N4): "accepted" was never checked against the profile.

**Remediation (7.4)**
- **C1f, D2, N2 — fixed.** At a pause, Python dislikes the video through the Client with the key (`_act`, outside the module). `fetchReaction` must then read `(False, True)` (line 167). A browser-side mirror of `AFTER` reads `(False, False)` there.
- **C1e — fixed.** That out-of-band dislike is the "disliked video" the next `like` acts on. Its state is read at 167 before the like, and 168 reads `(True, False)` after.
- **C2a, N4 — fixed.** At a pause, Python reads the profile after the keyed like: `(True, False)` (line 212). The name says "a like the profile holds".
- **D8 — fixed.** Line 171 asserts every module action returned, including the dislike whose `UndoLike` withdraws the first `Like`.
- **N3 — fixed.** The closing `undo_like` is read back as `(False, False)` (line 169).
- **Recommendation 3 (N5) — taken.** Line 214: no `localStorage`/`sessionStorage` entry other than the profile key holds the video's uuid.
- **Recommendation 4 — taken in part.** A key the Client refuses makes `fetchReaction` throw `ProfileKeyRejectedError` (line 181). A refused keyed `sendReaction` recording nothing is moot: a keyed action records nothing locally in any case (C2).
- **Recommendation 5 — not taken.** An unknown video and a malformed key are the Client's validation, covered by `tests/active/test_dislikes.py` and `test_profiles.py`.

**Self-check (dispatch 2)**
- `C1 — :164, after a keyed like — expected: (True, False) — under a fetchReaction reading only localLikes:v1 once keyed likes are not stored: (False, False).`
- `C1 — :165, after dislike on the liked video — expected: (False, True) — under the Phase 1 fetchReaction: (True, False) (observed).`
- `C1 — :166, after undo_dislike — expected: (False, False) — under a keyless read: (True, False).`
- `C1 — :167, after a dislike made through the Client directly — expected: (False, True) — under a fetchReaction answering from a browser-side record of sendReaction: (False, False).`
- `C1 — :168, after like on that disliked video — expected: (True, False) — under a like that leaves the dislike: (True, True).`
- `C1 — :169, after undo_like — expected: (False, False) — under a stale mirror or local store: (True, False).`
- `C1 — :170, the Client's reaction route at each of the six steps equals what fetchReaction read — expected: equal — under any module-side answer: differs at step 2 or 4.`
- `C2 — :213, getStoredLikes after a keyed like the profile holds — expected: absent — under the Phase 1 sendReaction: present (observed).`

(Line numbers corrected against the file: the C1 rows are 164-170, 171 is "every action accepted", 181 is the refused key, 212 is the profile holding the like, 214 is the whole-browser check.)

Supporting (no row):
- 171, every action accepted;
- 181, a refused key throws `ProfileKeyRejectedError`;
- 199-200, the keyless like is stored (arms 213);
- 211, the keyed call returned;
- 212, the profile holds the like;
- 214, no other storage entry holds the video;
- 215, the undo returned.

Answers 2-7 walked again. 2: 213 and 214 are armed by 200 and 212. 3: 167 reads a state the module never wrote. 4: six states, an out-of-band change, two key conditions, a refused key. 5: no double. 6: 2 node ids. 7: this run; the out-of-band dislike and the profile states were observed through the route.
**Still red for its own reason:** exit 1, 2 failed at line 165 (`(True, False) == (False, True)`) and line 213 (the keyed like stored). Controls at 164, 211 and 212 passed. Live events stay matched: 10 `Like`, 10 `UndoLike` in total (observed).

**Checkpoint audit (dispatch 2)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 165, (True, False), because fetchReaction returns hasLocalLike with disliked false and the dislike never removes the local like; line 213, because sendReaction calls addLocalLike whether or not a key is present.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim (C1f/D2/N2 local mirror, C1e unchecked dislike, C2a/N4 unchecked acceptance). Fixed: out-of-band dislike read back, profile read at each pause, action results asserted. Re-audit: PASS.` All 21 rows of the frozen ledger are CARRIED.
  - Observation 1: the step-0 `Like` is withdrawn by the dislike's implicit `UndoLike`, whose 200 does not distinguish publish from no publish. Covered outside the test: the live `whitelist.db` counts are read after every run and stay matched (10/10).
  - Observation 3: a keyed `sendReaction` with a refused key is not exercised. It is recorded; the page shows the thrown message.

**Changes**
- `client/frontend/src/data/reactions.ts`:
  - `fetchReaction` with a key reads `GET /api/profile/reaction` (`cache: "no-store"`), throwing `ProfileKeyRejectedError` on 401 and the Client's error otherwise.
  - `sendReaction` records in `localLikes:v1` only without a key.
- `client/frontend/src/pages/video-page/index.ts`:
  - `toggleReaction`, `handleLikeAction` and the optimistic listeners are gone.
  - `loadReaction` runs after metadata: it reads `fetchReaction`, then enables and wires the buttons once.
  - `react` handles the in-flight state (`disabled`, `aria-busy`); a failure writes to `#reaction-status` and leaves both buttons as shown.
  - `renderReaction` / `setReactionButton` set `active`, `aria-pressed` and the "Like/Liked", "Dislike/Disliked" label.
  - A keyless dislike shows the profile prompt and sends nothing.
  - `reactionVideo` uses `resolveLikeUuid` / `resolveLikeHost`.
  - `applyActionIcons` uses the typed button elements.
- `client/frontend/video-page.html` — both buttons start `disabled` with `aria-pressed="false"` and a `.reaction-label` span. The `aria-label`s went, since the visible label now names the button. `#reaction-status` (`role="status"`) follows the buttons.
- `client/frontend/src/video.css` — `.icon-button.active svg` filled; `[aria-busy="true"]` dimmed; the disabled cursor.
- **Type check:** `tsc --noEmit -p client/frontend` reports 37 errors, all pre-existing. None are in code this build wrote; the 4 in `video-page/index.ts` are `resolveAssetCandidate` and `views_count`, untouched.
- **Inventory gaps:** none.

**Checkpoint outcome** — PASS: `test_frontend_keyed_reactions.py` 2 passed, with Phase 1's `test_frontend_keyless_likes.py` 2 passed (17.5 s). The DOM wiring is for the Step 8 browser recipe.

#### Phase 3 — Local likes move into the profile

- **Kind:** code
- **Files:**
  - EDITED: `client/frontend/src/data/reactions.ts` (`importLocalLikes`), `client/frontend/src/data/videos.ts` (L5), `client/frontend/src/data/user-profile.ts` (L7), `client/frontend/src/pages/videos/index.ts` (import, My likes Remove), `client/frontend/src/pages/search/index.ts` (import), `client/frontend/src/pages/video-page/index.ts` (import), `client/frontend/src/videos.css`.
  - NEW: `tests/tmp/test_frontend_likes_import.py` (checkpoint).
- **Intent (post-phase state):** When a browser holding local likes has a profile key, `importLocalLikes` records those likes in the profile and empties the browser's store. When the Client refuses the import, the browser keeps its likes for the next attempt.
- **Clauses:**
  - `C1` — With a key, after `importLocalLikes` the profile reads every video that `localLikes:v1` held as liked, and `getStoredLikes()` is empty.
  - `C2` — When the Client refuses the import, `getStoredLikes()` returns the same likes it returned before.
- **Checkpoint and seam:**
  - Node runner, `unpublished_client` (the import publishes nothing).
  - C1 seeds three local likes and reads the profile through `GET /api/profile/reaction`; a fourth, never-held video stays unliked.
  - C2 uses a well-formed unknown key (401).
  - Red: `importLocalLikes` is a scaffold throwing until the phase lands.

**Self-check (dispatch 1)** — `tests/tmp/test_frontend_likes_import.py` (`unpublished_client`; the import publishes nothing)
- `C1 — :107, each of three held videos reads liked through GET /api/profile/reaction after importLocalLikes — expected: all liked — under an import that sends nothing, or only the first entry: not all (observed under the scaffold: none).`
- `C1 — :109, getStoredLikes after a successful import — expected: [] — under an import that never clears: the three held entries.`
- `C2 — :120, importLocalLikes with a key the Client does not know — expected: throws ProfileKeyRejectedError — under an import that swallows the 401: an imported count; under a generic Error: rejected False (observed under the scaffold: rejected False).`
- `C2 — :121, getStoredLikes after the refusal — expected: the two held entries — under a clear before or regardless of the response: [].`

Supporting (no row):
- 108, a fourth, never-held video stays unliked, which excludes an import that likes everything;
- 119, the store is seeded before the refusal.

1. **Whole claim** — C1: every held video liked, and the store empty. C2: the refusal (pinned to `ProfileKeyRejectedError`) and the store unchanged.
2. **Absence only** — 108 is armed by 107; 121 by 120.
3. **Echoed literal** — the held list is seeded and compared at 121. The production line whose deletion turns it red is the clear-only-on-success guard: a clear that ignores the response empties it. 107 reads the profile through the Client, not the seed.
4. **One value** — three videos imported, two held on refusal, one never held.
5. **The double** — none.
6. **It collects** — 2 node ids.
7. **Observed** — the Client's import and its 401 were observed in plan 03 (`tests/active/test_profiles.py:237-251`; plan 03 Step 8, "401s").
8. **Red** — exit 1, 2 failed.
9. **Right reason** — line 107: no held video is liked (the import never ran), `{'error': 'not implemented'}`. Line 120: `rejected: False`, the scaffold's error, not the Client's 401.
10. **Observed expected output** — yes.

**Checkpoint audit (dispatch 1)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 107, the scaffold throws before any POST, so the reaction route gives liked false; line 120, a plain Error, rejected false.` Recommendation, not taken: test 2 alone would pass a stub throwing `ProfileKeyRejectedError` without a request. The auditor notes the file excludes it at 107.
- `AUDIT: devsecops-test-claim-auditor — PASS.` The frozen ledger has 18 rows: 17 CARRIED, 1 UNCARRIED (D8, "The import publishes nothing", which cannot be observed with an unpublished Client).

**Remediation (7.4)**
- **D8 — justified by narrowing.** The sentence now says why the fixture was chosen ("nothing these tests do can reach the live whitelist.db").
- **Bounds recommendation — taken for the empty store.** A second import after the store emptied answers `{imported: 0}` (line 112).
- **Bounds recommendation — not taken:** a store at 50 or above `MAX_CLIENT_LIKES`. Those bounds are `addLocalLike`'s and `_parse_client_likes`'s, both unchanged.

**Self-check (dispatch 2)** — rows re-lined: `C1 — :109` (each held video liked), `C1 — :111` (store empty), `C2 — :123` (ProfileKeyRejectedError), `C2 — :124` (store unchanged). Expected and wrong-implementation values are as dispatch 1. Supporting: 110 (the never-held video unliked), 112 (the empty re-import returns 0), 122 (the seeded store). Questions 2-7 are unchanged; the new 112 reads the module's return for a state the test did not write.
**Still red for its own reason:** exit 1, 2 failed. Line 109: `{'error': 'not implemented', 'rejected': False}`, no held video liked. Line 123: `rejected` False, the scaffold's plain `Error`. Control 122 passed.

**Checkpoint audit (dispatch 2)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 109 (the scaffold throws before any import POST, so the first held video reads not liked); test 2 passes 122 and fails at 123 (rejected false).` Recommendation not taken, as in dispatch 1: pinning the refusal to the 401 has no observable beyond the error class our own module chooses. Line 109 excludes a stub that throws without a request.
- `AUDIT: devsecops-test-claim-auditor — PASS.` This is the bounded re-audit; all 18 ledger rows are CARRIED (D8 by narrowing).
  - Observation 1: "no publish on import" is asserted nowhere. It is the Client's behaviour (plan 03's `_handle_likes_import`) and is not a clause of this phase.

**Changes**
- `client/frontend/src/data/reactions.ts` — `importLocalLikes`. With a key and a non-empty store, it posts `localLikes:v1` to `/api/profile/likes/import`: 401 raises `ProfileKeyRejectedError`, another failure raises the Client's error, and only a success calls `clearLocalLikes()`. It returns `imported`.
- `client/frontend/src/data/videos.ts` — `fetchSimilarVideosPayload` sends `{}` with a key and `{likes}` without (L5).
- `client/frontend/src/data/user-profile.ts` — `fetchUserProfileLikes`: `GET /api/user-profile/likes` with `profileHeaders()` when a key is held, otherwise the local-likes POST. `USE_LOCAL_LIKES_PROFILE` is gone (L7).
- `client/frontend/src/pages/videos/index.ts`:
  - A module-level `localLikesImported` (the failure is logged with `console.warn` and the page continues; the store is kept). `loadVideos` awaits it.
  - `renderLikes` cards are `<article class="like-card">` with `.like-link`, a Remove button (`data-uuid` and `data-host` escaped) and a `.like-error` status.
  - A delegated click calls `removeLike`, which sends `undo_like` via `sendReaction`, removes the card on success (and shows "No likes yet." when none are left), or shows the error and re-enables the button.
- `client/frontend/src/pages/search/index.ts` — the same import promise, awaited in `loadPage`.
- `client/frontend/src/pages/video-page/index.ts` — the same import promise, awaited in `loadSimilarVideos` and `loadReaction`.
- `client/frontend/src/videos.css` — `.like-card` as the article, plus `.like-link`, `.like-remove` and `.like-error`.
- **Type check:** 37 errors, the same pre-existing set.
- **Inventory gaps:** none.

**Checkpoint outcome** — PASS: `test_frontend_likes_import.py` 2 passed. With P1 and P2 and the durable `test_frontend_blocks.py` and `test_frontend_profile.py`: 10 passed (34.7 s).

#### Phase 4 — Cards show the visitor's reaction

- **Kind:** code
- **Files:**
  - EDITED: `client/backend/lib/users_store.py` (`load_liked_keys`), `client/backend/server.py` (`RowFilter`, `_profile_filter`, `_filter_payload`), `client/frontend/src/types/videos.ts`, `client/frontend/src/data/reactions.ts` (`cardReaction`), `client/frontend/src/components/video-card.ts`, `client/frontend/src/pages/videos/index.ts`, `client/frontend/src/pages/search/index.ts`, `client/frontend/src/pages/video-page/index.ts` (`renderSimilarCard`), `client/frontend/src/videos.css`, `client/frontend/src/video.css`.
  - NEW: `tests/tmp/test_card_reactions.py` (checkpoint).
- **Intent (post-phase state):** A profile holder's search and feed rows arrive from the Client marked with the profile's reaction. A card rendered from any row shows the visitor's like or dislike in the active style, with no request per card.
- **Clauses:**
  - `C1` — A keyed search through the Client returns the profile's liked video with `reaction` `liked` and its disliked video, still present, with `reaction` `disliked`, where the keyless search for the same query carries no `reaction` on either.
  - `C2` — `renderVideoCard` with `reaction: cardReaction(row)` renders the likes stat active for a row the Client marked liked (with a key) and for a row held in `localLikes:v1` (without a key), and renders no active stat for an unmarked row.
- **Checkpoint and seam:**
  - C1: HTTP to the real Client and Engine, as `tests/active/test_blocks.py` does (`unpublished_client`: the keyed `like` is stored before its publish is answered 502, and the `dislike` of a second video publishes nothing). The liked and disliked videos are taken from the keyless search page for the query, so their presence there is the control.
  - C2: the node runner calls `fetchSearchResults`, `cardReaction` and `renderVideoCard` from the bundle, and asserts on the rendered markup of each target row's card, located by its `data-video-key`.
  - Red: `reaction` is absent from rows today, and `renderVideoCard` has no reaction option.

**Self-check (dispatch 1)** — `tests/tmp/test_card_reactions.py` (`unpublished_client`; the scaffold `cardReaction` throws)
- `C1 — :124, the liked video's row in a keyed search — expected: reaction "liked" — under a proxy that marks nothing: None (observed).`
- `C1 — :125-126, the disliked video's row in a keyed search — expected: present with reaction "disliked" — under marking likes only: None; under search filtered by dislikes (D6 broken): absent.`
- `C1 — :129, the keyless search's rows for all three videos — expected: no reaction key — under marks applied regardless of the key, or a keyed page reused for a keyless request: present.`
- `C2 — :142, the liked row's card with a key — expected: {likes: True, dislikes: False} — under a renderVideoCard that ignores the reaction, or a cardReaction that is not wired: likes False (observed: the scaffold's error).`
- `C2 — :144, the neutral row's card with a key — expected: no active stat — under a renderer that marks every card: likes True.`
- `C2 — :148, the neutral row's card without a key, the row held in localLikes:v1 — expected: likes True — under a cardReaction reading only row.reaction: False.`
- `C2 — :149, the liked row's card without a key (the profile's like, not held locally) — expected: no active stat — under a cardReaction that ignores which store applies: likes True.`

Supporting (no row):
- 127, the keyed neutral row is unmarked;
- 130, the keyless page still holds the liked video;
- 143, the disliked card's dislikes stat is active (the dislike half of V1's visual language);
- the setup's pinned statuses: the like 502 after storing, the dislike 200.

1. **Whole claim** — C1: liked, disliked and still present, and keyless unmarked. C2: the keyed mark, the local mark, and no mark on an unmarked row, each in both key states.
2. **Absence only** — 127 and 144 are armed by 124 and 142; 129 by 124 and 130; 149 by 148.
3. **Echoed literal** — the reaction strings come from the Client's proxy; the card flags come from the rendered markup. Deleting the mark in `_filter_payload` turns 124 red; deleting the `active` class in `renderVideoCard` turns 142 and 148 red.
4. **One value** — three rows, two key states, both reactions.
5. **The double** — none.
6. **It collects** — 2 node ids.
7. **Observed** — this run: the three rows are on both pages, the like is answered 502 and stored, the dislike 200.
8. **Red** — exit 1, 2 failed.
9. **Right reason** — line 124: `None == 'liked'`, the keyed row carries no reaction (the proxy does not mark). Line 142: `{'error': 'not implemented'}`, the scaffold `cardReaction`. The setup's pinned statuses passed.
10. **Observed expected output** — yes.

**Checkpoint audit (dispatch 1)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 124 (no mark, reaction None); line 142 (cardReaction throws, {"error": "not implemented"}).`
- `AUDIT: devsecops-test-claim-auditor — PASS.` The frozen ledger has 24 rows: 23 CARRIED and 1 UNCARRIED (D11, "the dislike publishes nothing, so nothing reaches the live whitelist.db").

**Remediation (7.4)**
- **D11 — justified by narrowing.** The sentence is now setup rationale: "so these tests publish nothing to the live whitelist.db".
- **Recommendation 2 — taken.**
  - Every other keyed row is unmarked (line 128).
  - No keyless row carries a reaction (line 131).
  - Every other card renders no active stat in both runs (lines 153, 158, via `_unmarked`).
- **Recommendation 3 — taken.** Test 2's name now names the dislike: `…the_like_or_dislike_the_client_marked_or_the_like_the_browser_holds_and_nothing_else`.
- **Recommendation 4 — taken in part.** The keyed run starts with a stale `localLikes:v1` entry for the neutral row, which must not mark (line 153); this is L8's half of `cardReaction`. Empty, malformed and alternate-spelling stores are `parseLocalLikesStorageValue`'s, unchanged.
- **Recommendation 5 — not taken.** A refused key on search is `fetchSearchResults`' existing `ProfileKeyRejectedError`, covered by `tests/active/test_frontend_blocks.py`.

**Self-check (dispatch 2)**
- `C1 — :124` (liked row "liked"), `:125-126` (disliked row present, "disliked"), `:131` (no keyless row carries a reaction) — values as dispatch 1.
- `C2 — :151` (keyed liked card likes active), `:153` (every other keyed card inactive, including the neutral row held stale in localLikes:v1 — under a cardReaction that consults the local store while keyed: the neutral card likes True), `:157` (keyless local-liked card active), `:158` (every other keyless card inactive).

Supporting: 128 (other keyed rows unmarked), 130 (the keyless page holds both), 152 (the disliked card's dislikes stat).
Answers 2-7 walked again; nothing changed except the sets widened to the whole page and the stale local entry.
**Still red for its own reason:** exit 1, 2 failed at line 124 (`None == 'liked'`) and line 151 (`{'error': 'not implemented'}`).

**Checkpoint audit (dispatch 2)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 124 (search rows pass through with no reaction key; line 125 passes first, since search does not filter dislikes); line 151 (cardReaction throws, the card is {"error": "not implemented"}).`
  - Recommendation, not taken: the runner matches the exact class string `stat likes active`. The markup is this build's own and emits exactly that order.
- `AUDIT: devsecops-test-claim-auditor — PASS.` This is the bounded re-audit; all 24 ledger rows are CARRIED (D11 by the reworded sentence, backed by the pinned statuses at line 108).
  - Observation 3, not taken: line 128 reads a missing `reaction` and a `reaction: null` alike. The proxy never writes null (it sets the key only on a match).

**Changes**
- `client/backend/lib/users_store.py` — `load_liked_keys`, the profile's `(video_id, instance_domain)` likes.
- `client/backend/server.py`:
  - `RowFilter` becomes `(block_keys, dropped, liked, disliked)`.
  - `_profile_filter` loads dislikes and likes on every filtered route. It drops dislikes on feeds only (search is unfiltered, D6), returns a filter whenever the profile has blocks, dislikes or likes, and over-fetches only when a block or a dropped dislike can remove rows.
  - `_filter_payload` sets `reaction` `liked`/`disliked` on the rows it keeps.
- `client/frontend/src/types/videos.ts` — `VideoRow.reaction`.
- `client/frontend/src/data/reactions.ts` — `cardReaction`: with a key, the row's `reaction`; without one, `"liked"` when `localLikes:v1` holds the row.
- `client/frontend/src/components/video-card.ts` — `VideoCardOptions.reaction`: the likes or dislikes stat takes `active`, the article takes a `liked`/`disliked` class, and a visually hidden "You liked this" / "You disliked this" label is added.
- `client/frontend/src/pages/videos/index.ts` (`renderFeedCard`) and `pages/search/index.ts` (`renderRows`) pass `reaction: cardReaction(row)`.
- `client/frontend/src/pages/video-page/index.ts` — `renderSimilarCard` adds a `.similar-reaction` pill (filled thumb icon and "Liked"/"Disliked").
- `client/frontend/src/videos.css` — `.stat.active` (filled icon, stronger background) and `.visually-hidden`. `client/frontend/src/video.css` — `.similar-reaction`.
- **Type check:** 37 errors, the same pre-existing set; none in `data/`, `components/`, `types/` or the search page.
- **Inventory gaps:** none.

**Checkpoint outcome** — PASS: `test_card_reactions.py` 2 passed. All four checkpoints together: 8 passed (28.6 s). Active suite (the 5 groups `server.py` feeds): 31 passed.

#### Phase 5 — A like that is undone is neutral in the Engine (Step 7 amendment)

- **Kind:** code
- **Files:**
  - EDITED: `engine/server/data/random_videos.py`, `tests/run-installers-smoke.sh`.
  - NEW: `tests/tmp/test_undone_like_neutral.py` (checkpoint).
- **Intent (post-phase state):** A video whose `Like` has been undone reads in the Engine's random and popular reads as it did before either event: its reported likes and its place in the popular order are those of a video with no events.
- **Clauses:**
  - `C1` — After a `Like` and its `UndoLike` are ingested for a video, `fetch_random_rows` reports that video's `likes` equal to its crawled `likes`.
  - `C2` — `fetch_popular_videos` places a video with more views ahead of one tied with it on popularity and crawled likes, whether or not a `Like` of the higher-viewed video has been undone.
- **Checkpoint and seam:**
  - Rung 1, in-process, as `tests/active/test_db.py` imports `engine/server/data`.
  - A temp database is built from two real videos copied out of `whitelist.db` (read-only `ATTACH`) with their embeddings and channels. The two are set to equal popularity and crawled likes, with distinct views.
  - Events go through the real `ingest_interaction_event`.
  - C1's expected value is the crawled `likes` read from the copied row. C2 compares the order with no events against the order after the pair.
  - Red: the double subtraction gives `likes − 1` and puts the undone video second.
- **E2 (smoke rebuild)** has no clause. It is checked at Step 8 by running the rebuild snippet against a temp database holding a `Like` and an `UndoLike`, and reading `likes_count` 0.
- _Name corrected at 7.1:_ the random read is `fetch_random_rows` (`random_videos.py:12-102`), not `fetch_random_videos` as E1 and C1 first said. The meaning is unchanged.

**Self-check (dispatch 1)** — `tests/tmp/test_undone_like_neutral.py`
- Seam: rung 1, in-process, importing `engine/server/data` as `tests/active/test_db.py` does, plus `engine/server/api` on the path (`data.metadata` imports `recommendations`, as the Engine's `server.py` runs it).
- The database is a temp copy of two real videos (`ATTACH` of `whitelist.db` read-only), set to popularity 3.0, crawled likes 7, and views 1000 and 10.
- `C1 — :90, fetch_random_rows' likes after Like then UndoLike — expected: 7 — under the double subtraction: 6 (observed).`
- `C2 — :101, fetch_popular_videos' order after Like then UndoLike on the higher-viewed video — expected: [high, low] — under the double subtraction: [low, high] (observed).`
- Supporting: 84 (7 before any event), 87 (8 after the Like alone), 91, 96.
- Answers: 1-2 as below; 5 no double; 6 2 node ids (the first collection failed on `recommendations`, fixed by the path). 7: the first run failed its own control (96) on a duplicated channel row, because both copied videos share channel 1. Fixed with `SELECT DISTINCT`, observed by a probe. 8-9: red at 90 (`6 == 7`) and 101 (`[low, high]`), the `- undo_likes_count` term; controls passed. 10: yes.

**Checkpoint audit (dispatch 1)**
- `AUDIT: devsecops-test-shape-auditor — BLOCK: absence-only-assertion, line 101. The post-undo order equals the pre-event order, and test 2 had no control that its events reached the popular read (an ingest no-op, or dropping the likes term, passes).`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim, line 96. Views always went to the lower rowid, so an order without a views term passes C2's "more views ahead" wherever published_at or video_id agree.` The frozen ledger has 13 rows, 3 UNCARRIED: C2a, D4 (views not isolated), D6b (popularity and views set, never read back).

**Remediation (7.4)**
- **Shape Critical — fixed.** After the `Like` and before the undo, test 2 asserts that `fetch_popular_videos` reports `interaction_signal_score` 1.0 for the liked video and 0 for the other (line 119). The unchanged order at 122 now means "the undo was neutral", not "no event reached the read".
- **C2a, D4 — fixed.** The tie runs both ways. With views 1000/10 on rows 1/2 the order is [1, 2] (line 112). With the views swapped it is [2, 1] (line 114). So views decide, not row order. The undone `Like` is then on row 2, first only through its views.
- **D6b — fixed.** Line 111 reads popularity and crawled likes back from the popular rows: both are (3.0, 7). The docstring drops "different views" as a separate claim; 112 and 114 carry it.
- **Shape recommendation — taken.** The other video's likes are checked right after the `Like` (line 99), not after the net-zero pair.
- **Claim recommendation 2 — taken in part.** A later `Like` after the pair reads 8 (line 105).
- **Claim recommendation 2 — not taken:** an unmatched `UndoLike` and a redelivered `event_id` are ingest behaviour this phase does not change; idempotency is the ingest contract test's.
- **Claim recommendation 3 (failure paths) — not taken.** The phase changes two read expressions; its expected failure is the double subtraction, which C1 and C2 exclude.
- **Claim recommendation 4 — answered by the shape fix** (line 119).

**Self-check (dispatch 2)**
- `C1 — :102, fetch_random_rows' likes after Like then UndoLike — expected: 7 — under the double subtraction: 6 (observed).`
- `C2 — :112/:114, the tie order with views on row 1, then on row 2 — expected: [1, 2] then [2, 1] — under an order with no views term: the same order both times.`
- `C2 — :122, the order after Like then UndoLike on the view-leading video — expected: [high, low] — under the double subtraction: [low, high] (observed).`

Supporting:
- 94, 7 before events;
- 98-99, 8 after the Like, the other video still 7;
- 105, a later Like reads 8;
- 111, tied on popularity and likes;
- 119, the popular read sees the Like.

Answers 2-7 walked again. 2: 122 is armed by 119 and 114. 3: 7 and 3.0 are written into the copy; the production term decides 102. 4: two view orientations, three event states. 5: none. 6: 2 node ids. 7: this run.
**Still red for its own reason:** exit 1, 2 failed at line 102 (`6 == 7`) and line 122 (`[low, high]`). Controls 94, 98, 99, 111, 112, 114 and 119 passed.

**Checkpoint audit (dispatch 2)**
- `AUDIT: devsecops-test-shape-auditor — BLOCK: absence-only-assertion at line 101 (no in-test control that the events reached the popular read). Fixed: line 119 asserts interaction_signal_score 1.0/0 after the Like. Re-audit: PASS. Predicted failure: line 102 (6, not 7); line 122 ([low, high]); lines 94, 98, 111, 112, 114, 119 pass first.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim at line 96 (views not isolated from row order). Fixed: the tie is run both ways (112, 114); popularity and likes are read back (111). Re-audit: PASS.` All 13 rows of the frozen ledger are CARRIED.
  - Observation 3, not taken: an `UndoLike` with no prior `Like` leaves `undo_likes_count` above 0 with `likes_count` at 0. After this phase neither read uses `undo_likes_count`, so it no longer shifts anything.

**Changes**
- `engine/server/data/random_videos.py` — `fetch_random_rows`' `likes` and `fetch_popular_videos`' likes tiebreak are `v.likes + COALESCE(sig.likes_count, 0)`; the second `- undo_likes_count` is gone (lines 45, 248).
- `tests/run-installers-smoke.sh` (the cleanup's signal rebuild) — `likes_count` is written net, `max(0, like_events − undo_likes_count)`, as ingest keeps it. `signal_score` is unchanged.
- **Inventory gaps:** none.

**Checkpoint outcome** — PASS: `test_undone_like_neutral.py` 2 passed (0.2 s). The Engine's ingest contract script `engine/server/db/jobs/tests/test-interaction-events.py` passes ("ok").

#### Acceptance items without a clause (checked at Step 8)

- **L5** — with a key, the feed request body carries no `likes`. A runner probe records the body `fetchSimilarVideosPayload` sends (a `fetch` wrapper that passes every call through), keyed and keyless.
- **L7 (data)** — with a key, `fetchUserProfileLikes` lists the profile's likes. A runner probe.
- **Keyed feed marking and D6** — a keyed up-next page marks a liked row. A liked-only profile's feed request is not over-fetched, and search still carries a disliked row (C1 covers the latter). Probe plus the durable `test_blocks.py`/`test_dislikes.py`.
- **Browser (operator, per the Step 2 T1 and the standing memory):** L2 (filled icon, "Liked"/"Disliked", in-flight), L3's on-page error, D1's prompt, D3's two-button update, L1 on reload, L7's Remove control, the V1 mark on feed, search and similar cards, and L6 running on each page. A recipe is handed over at Step 8.

#### Coordination

- O1: P1 and P2 publish `Like`/`UndoLike` pairs into the live `whitelist.db` through the test Engine.
- Step 8: the operator runs the browser recipe after `npm run build` and a restart of the Client (`scripts/run-services.sh restart`).

#### Rationale

- Four phases, two clauses each, one Intent each, split along who holds a like: the keyless browser (P1), the keyed profile (P2), the move from one to the other (P3), and showing it on cards (P4, the one phase touching the backend).
- The DOM half of each phase is not reachable by a node checkpoint. The operator approved verifying it by hand (Step 2, T1). Adding jsdom was the rejected alternative.
- L5 and L7's data half are one-branch changes checked by Step 8 probes, rather than taking the clause the import's failure path needs (data loss).
- **Five phases (reason recorded).** The operator widened the build at Step 7 to fix the Engine counting fault that Phase 1's red runs exposed ("fix everything we have talked about in this session in this build"). The fix has its own seam (the Engine's data layer) and its own Intent, so it is a phase of its own, not a fold into P1-P4.

## Inner unit tests

None. Every phase's data-layer behaviour was expressible at its checkpoint. The DOM half is covered by the operator's browser recipe (T1), not by inner tests.

## Close

### Refactors

- None made. Considered and left:
  - The three-line import promise repeated in the three page entries. It is three similar lines, and moving its `catch` into `reactions.ts` would swallow the failure inside the data layer.
  - The text-then-JSON response read in `reactions.ts`, which mirrors `blocks.ts` and `profile.ts`.
  - The two card renderers' reaction markup, which differ because the cards differ.
- Nothing needed new behaviour.

### Clause accounting

- `P1C1`, `P1C2` — carried; dispatch 2 of `test_frontend_keyless_likes.py` (both PASS, 18 rows CARRIED).
- `P2C1`, `P2C2` — carried; dispatch 2 of `test_frontend_keyed_reactions.py` (both PASS, 21 rows CARRIED).
- `P3C1`, `P3C2` — carried; dispatch 2 of `test_frontend_likes_import.py` (both PASS, 18 rows CARRIED).
- `P4C1`, `P4C2` — carried; dispatch 2 of `test_card_reactions.py` (both PASS, 24 rows CARRIED).
- `P5C1`, `P5C2` — carried; dispatch 2 of `test_undone_like_neutral.py` (both PASS, 13 rows CARRIED).

### Acceptance items without a clause (checked at Step 8)

`tests/tmp/probe_step8_checks.py` (real Engine, `unpublished_client`):
- **L5:** the keyless feed body is `{"likes":[{uuid, host}]}`; the keyed body is `{}`.
- **L7 (data):** keyless, `fetchUserProfileLikes` lists the local seed. Keyed, it lists the profile's like, not the local entry.
- **Keyed feed marking:** a keyed `/recommendations` page for a profile holding one like returned that video marked `reaction: "liked"`.
- **Over-fetch:** that liked-only profile's request asked the Engine for `limit` 16 (no over-fetch). After a dislike it asked for 32, and the page stayed 16 rows.
- **`_filter_payload` on a feed-shaped filter:** it drops the disliked row and marks the liked one.
- **D6:** search keeps a disliked row (P4C1, line 125).
- **E2:** the smoke's signal rebuild, run on a temp database holding Like, UndoLike, Like by others, writes `likes_count` 1 and `signal_score` 1.0.
- **Boundaries:** `tests/check-frontend-client-gateway.sh` and `tests/check-client-engine-boundary.sh` PASS.
- **Type check:** `tsc --noEmit -p client/frontend` has 37 errors, the same pre-existing set, none in code this build wrote.
- **Build:** `npm run build` in `client/frontend` built `dist/` (vite 5.4.21, 29 modules).
- **Live data (O1):** since the build started, the test Engine published 34 `Like` and 34 `UndoLike` on one test video (`fd640a96-…@yt.orokoro.ru`), all matched. After P5 they leave its likes and popular order unchanged. The 4 stray `UndoLike`s from the first red runs were deleted (E3).

### Suite

- `--compare`: "unchanged since 2026-09-26T11:27:28-04:00 — every fingerprint still holds", 48 passed; "nothing moved against the previous record". The baseline was 48 passed.
- `engine/server/data/random_videos.py` is in no group's `test_groups` entry, so the bare run did not re-run the Engine-backed groups after P5. Each was run explicitly, one invocation per group: `test_similar` 6, `test_dislike_profile` 9, `test_dislikes` 10, `test_frontend_blocks` 2, `test_blocks` 7, `test_profiles` 10, `test_frontend_profile` 2, `test_db` 2, which is 48 passed.
- **Red diagnosed, not a regression:** passing all eight files to one invocation runs them in one lane against one Engine. That gave 5 failures, all `{'error': 'Rate limit exceeded'}` from the Engine's per-address limit (60 a minute, recorded in plan 03), or a `KeyError` downstream of it. Test first: the tests are unchanged and pass in their own lanes. The failure is the harness invocation. No checkpoint gap.
- Phase checkpoints together: `tests/tmp` 10 passed. The Engine ingest contract script passes.

### Browser recipe (operator; not verified here — this environment has no browser)

After `scripts/run-services.sh restart` (the rebuilt `dist/` and the Client change), in a private window:
1. **Without a profile**:
   - Open any video page. Both buttons should read "Like" and "Dislike" and become clickable once the page loads.
   - Click Like: the button goes briefly dim (in flight), then reads "Liked" with a filled thumb.
   - Reload: it is still "Liked".
   - Click it again: it reads "Like".
   - Click Dislike: the status line beside the buttons says disliking needs a profile, and nothing else changes.
2. **Card mark without a profile**: like a video, then find it in search (or in a video page's "Similar videos"). Its card shows the filled, highlighted thumbs-up stat (search) or a "Liked" pill (similar).
3. **Import**: with that local like still held, open the home page, Profile → Create profile, save the key, and reload. Open My likes: the video is listed (it now comes from the profile). In devtools, `localStorage.getItem("localLikes:v1")` is `null`.
4. **With a profile**:
   - On a liked video, click Dislike: it reads "Disliked" filled, and Like returns to "Like" (D3).
   - Reload: still "Disliked".
   - Search for that video: its card shows the filled thumbs-down stat.
   - Click Like: both buttons swap back.
5. **Failure (L3)**: stop the Client (or go offline in devtools) and click Like. The button returns to its previous state, and the status line shows the error.
6. **My likes Remove**:
   - In My likes, click Remove on a card: it disappears, and "No likes yet." shows when none are left.
   - Reopen the video: it reads "Like".

### Harvest (Step 10)

- **Record:** `docs/project/plans/harvest-08-likes-dislikes-frontend-plan.md`.
- **Moved (operator-approved), all 10 checkpoint tests DURABLE:**
  - the frontend reaction tests into `tests/active/test_frontend_reactions.py` (NEW; the four runners merged into one);
  - the keyed-search mark test into `tests/active/test_profiles.py`;
  - the Engine tests into `tests/active/test_random_videos.py` (NEW).
  - `test_groups` gained both new groups, and `test_profiles.py` gained `lib/dislikes.py`. `--audit-map` exits 0.
- **Mutations:** each of the 10 felled its assertion, and each restore was `diff`-clean and green again. One attempt was discarded: its Edit was refused as stale and the test ran unmutated.
- **Disposed:** `tests/tmp` to `delete_me/plan08-tmp/`, and the mutation backups to `delete_me/`.
- **Suite:** 58 passed. `--compare` moved only the 10 appearances.
