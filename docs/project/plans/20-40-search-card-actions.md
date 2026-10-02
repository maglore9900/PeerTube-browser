# 40-search-card-actions

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/20-40-search-card-actions.record.md`._

## Requirements

### Purpose

An operator reported: "blocks and likes and such do not work on the video cards in search". Home feed cards have Like, Dislike, Block channel and Block account controls. Search result cards have none, so a visitor has to open the video page to react to or block a search result. This build gives search cards the same four controls and finishes the search-grid half of roadmap item F13-M2 ("Block controls on video cards (feed and search grids) and on the channels page"). The feed-grid half is already in the tree. The issue is `docs/project/issues/40-search-card-actions.md`.

### Current state (verified in the tree)

- `client/frontend/src/components/video-card.ts`: `renderVideoCard(row, options)` draws `.card-actions` only when `options.actions` is true and the row has a video key (`resolveVideoKey` = `host::id`). The block holds buttons with `data-card-action` = `like`, `dislike`, `channel`, `account` and a `<span class="card-action-status" role="status">`. The Like button has `aria-pressed="${reaction === "liked"}"`. The Dislike button has no `aria-pressed`. The card root is `<article class="video-card [liked|disliked]" data-video-key="...">`, and the disliked mark is the `stat dislikes active` class plus a visually-hidden "You disliked this".
- `client/frontend/src/pages/search/index.ts`: `renderRows` calls `renderVideoCard(row, { apiParam, reaction: cardReaction(row) })` with no `actions` and keeps no array of loaded rows. `#search-results` has no click handler. Paging is page-numbered (`state.page`, `PAGE_SIZE = 24`). `state.loadedRows` counts fetched rows, and both `hasMore` and the "Showing N of M matched videos." status use it. `fillViewport()` fetches more while the sentinel is in view. `ProfileKeyRejectedError` from `fetchSearchResults` replaces the grid with `keyRejectedNotice`.
- `client/frontend/src/pages/videos/index.ts` (home): a delegated click handler on `#video-cards` finds the row in `state.sample` by `data-video-key` and calls `runCardAction(button, card, row)`. That function shows `"<Disliking|Blocking> needs a profile. Create one from the Profile button."` when a non-like action has no key. It disables the button while running and clears the status line. Like sends `undo_like` or `like` depending on `cardReaction(row) === "liked"`, sets `row.reaction`, and replaces `card.outerHTML`. Dislike sends `dislike` and removes the row. Block calls `blockVideoSource`, then `sendReaction("dislike")`. If the dislike fails it says `Blocked <label|action>, but the dislike failed: <message>` and removes nothing; otherwise it removes rows matching `instance_domain`+`channel_id` (channel) or `account_url` (account). Any error goes to the status line, and the button is re-enabled in `finally`.
- `client/frontend/src/data/reactions.ts`: `sendReaction(apiBase, action, { uuid, host })` supports `like`, `undo_like`, `dislike`, `undo_dislike`, and without a key records local likes and un-likes. `cardReaction(row)` returns `row.reaction` with a key, and the local-like state without one.
- `client/frontend/src/data/blocks.ts`: `blockVideoSource(apiBase, kind, uuid, host)` returns a `Block` with `kind`, `instance_domain`, `channel_id`, `account_url` and `label`.
- `sendUserAction` and the blocks `request` throw a plain `Error` on any non-OK status, 401 included. Neither throws `ProfileKeyRejectedError`.
- Client backend `_filter_payload` (`client/backend/server.py`) filters blocked rows out of each Engine page after the Engine has paged and marks `reaction`. Search is never filtered by dislikes (plan 08, D6). Because filtering happens per page, a block never shifts later page numbers.

### Functional requirements

1. **Controls rendered.** The search page passes `actions: true` to `renderVideoCard` for every row, on the first page and on every appended page. Every search card with a video key shows Like, Dislike, Block channel, Block account and the `.card-action-status` line. A card without a video key shows none, as on home.
2. **Row lookup.** The search page keeps the rows it has rendered, in order, in page state. A reset (new search, sort change, popstate, retry after key rejection, idle) clears them. One delegated click listener on `#search-results` resolves `[data-card-action]` → closest `.video-card` → `data-video-key` → the stored row, matching by `resolveVideoKey`, the way home does. A click that resolves no row does nothing.
3. **Like.** It works with or without a profile key. If `cardReaction(row) === "liked"` it sends `undo_like` and the row's reaction becomes `null`. Otherwise it sends `like` and the reaction becomes `"liked"`, which also covers a disliked card: the like replaces the dislike. The card is re-rendered in place through the same `renderVideoCard` options search uses (`apiParam`, `reaction: cardReaction(row)`, `actions: true`) and stays on the page.
4. **Dislike (search only: toggle, card stays).** It needs a profile key. If `cardReaction(row) === "disliked"` it sends `undo_dislike` and the reaction becomes `null`. Otherwise it sends `dislike` and the reaction becomes `"disliked"`, which also covers a liked card: the dislike replaces the like. The card is re-rendered in place and stays. A disliked card shows the disliked mark and its Dislike button has `aria-pressed="true"`. A neutral or liked card's Dislike button has `aria-pressed="false"`.
5. **Block channel / Block account.** It needs a profile key and matches home. Call `blockVideoSource(apiBase, "channel"|"account", uuid, host)`, then `sendReaction(apiBase, "dislike", { uuid, host })`. If the dislike fails, the status line reads `Blocked <block.label || action>, but the dislike failed: <message>` and no cards are removed. Otherwise every loaded search row and card is removed where `instance_domain` + `channel_id` equal the block's (channel), or where `account_url` equals the block's (account).
6. **No profile key.** Dislike, Block channel and Block account write the same text home writes, `"Disliking needs a profile. Create one from the Profile button."` or `"Blocking needs a profile. Create one from the Profile button."`, into that card's status line and send no request.
7. **Errors.** The button is disabled while its action runs and re-enabled afterwards, whether the action succeeded or failed. A failed request writes its `Error.message` (fallback `"Action failed"`) into that card's status line. **Operator decision:** a rejected profile key during a card action goes the same way, as a status-line message like home's. It does not replace the grid with `keyRejectedNotice`, and the data layer (`user-actions.ts`, `blocks.ts`, `reactions.ts`) is not changed to throw `ProfileKeyRejectedError`. The search page's existing `ProfileKeyRejectedError` handling for search reads is unchanged.
8. **Paging after actions.** Infinite scroll keeps working after any action, and cards appended by later pages carry the controls and are clickable. `state.page`, `state.loadedRows`, `hasMore` and the "Showing N of M matched videos." status keep counting fetched rows, not rows still on screen. **Deliberate simplification:** after a block the count may overstate what is visible. Paging is still correct because the Client filters per Engine page, so page numbers do not shift. The upgrade path, if wanted later, is a separate visible-count. After a block removes cards, the page calls `fillViewport()` so a grid that became too short fetches the next page.
9. **Shared markup change.** The Dislike button in `renderVideoCard`'s action markup gets `aria-pressed="${reaction === "disliked"}"`, mirroring Like. That is the only change to the shared component's output.
10. **Home unchanged.** Home's dislike still removes the card and has no undo. Home's block still removes the matching cards. Home's like, no-key prompt and error handling stay as they are. Any helper shared between the two pages must keep that behaviour exactly. Mirroring home's handler inside the search page is acceptable, and so is extracting a shared helper, provided home's behaviour is unchanged.
11. **Build.** `dist/` is rebuilt with `npm run build` in `client/frontend` so the served bundle carries the change.

### Acceptance criteria

- A search results page renders Like, Dislike, Block channel and Block account buttons on every card that has a video key, including cards loaded by later pages.
- With a profile key, Dislike on a search card sends `dislike`. The card stays on the page with the disliked mark and a Dislike button with `aria-pressed="true"`. Rerunning the same search shows the video still present with `reaction: "disliked"`.
- Dislike on a disliked search card sends `undo_dislike`. The card shows no mark, and a rerun of the search carries no `reaction` on that row.
- Like on a search card toggles between `like` and `undo_like`. A like on a disliked card leaves it marked liked, not disliked.
- Block channel on a search card removes every loaded card of that channel, and the video is disliked. A rerun of the same search contains no row from that channel. Block account does the same by `account_url`.
- Without a profile key, Dislike and the two Block buttons show the profile prompt in the card's status line and send no request.
- A failed action shows its message in that card's status line and the button is re-enabled.
- Home feed card behaviour is unchanged: dislike and block still remove cards, and home has no undo-dislike.
- `dist/` is rebuilt (`npm run build`) so the served bundle carries the change.

### Out of scope

- Filtering search results by dislikes (D6 stands).
- Follow controls on any card.
- Action controls on the video page's similar/up-next cards, the likes page or the channels page.
- Changing home feed card behaviour, beyond the pressed state on its Dislike button.
- Any Client backend or Engine change, or any change to the frontend data layer's error types.

### Baseline suite state

The pre-build suite exited 0 (variant: false): 1 of 46 test groups selected (`test_search_fusion.py`, 10 passed). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`. The existing frontend tests touching this area are `tests/active/test_frontend_blocks.py` and `tests/active/test_frontend_reactions.py`.

## High-level plan

### Approach

The change touches two source files and then a rebuild. `pages/search/index.ts` gets its own card-action handler, written to match home's. `components/video-card.ts` gets one attribute.

I read the tree to confirm the premises. Search rows from `engine/server/data/search.py` carry `channel_id` and `account_url`, so block matching can use the same fields home uses. `sendReaction`, `blockVideoSource` and `sendUserAction` all pass their `apiBase` argument through `resolveClientApiBase`, so search can pass `apiParam ?? ""`, the same way it already calls `importLocalLikes`. `videos.css`, where `.card-actions` is styled, is already imported by the search page, so no CSS work is needed.

1. **Controls rendered (req 1).** One small search-page function renders a row with `apiParam`, `reaction: cardReaction(row)` and `actions: true`. It is search's version of home's `renderFeedCard`. `renderRows` uses it for both the first page and appended pages, so every keyed card gets the controls and keyless cards still get none.
2. **Row lookup (req 2).** Page state gains a `rows` array. `renderRows` appends each page's rows to it in order. Every reset path empties it: `loadPage(..., reset=true)` covers new search, sort change, popstate and the retry from `keyRejectedNotice`, and `showIdle` covers idle. One delegated `click` listener on `#search-results` does what home's listener on `#video-cards` does: `closest("[data-card-action]")`, then `closest(".video-card")`, then `dataset.videoKey`, then `state.rows.find` by `resolveVideoKey`. If any step finds nothing, the click does nothing. Because the listener sits on the container, cards appended by later pages are clickable without extra wiring (req 8).
3. **Action runner (reqs 3–7).** A search-page `runCardAction(button, card, row)` takes uuid and host from `resolveVideoId` and `resolveInstanceDomain`, as home does.
   - **No key (req 6):** if the action is not `like` and `getProfileKey()` is empty, it writes home's exact "Disliking/Blocking needs a profile. Create one from the Profile button." text into the card's status line and returns without a request.
   - **Running:** it disables the button and clears the status line.
   - **Like (req 3):** sends `undo_like` if `cardReaction(row) === "liked"`, otherwise `like`. It sets `row.reaction` to `null` or `"liked"` and replaces `card.outerHTML` with the search render. With no key, `sendReaction` has already updated the local likes, so `cardReaction` reads them correctly. With a key, the server's rule that a like and a dislike replace each other makes `"liked"` right for a card that was disliked.
   - **Dislike (req 4):** sends `undo_dislike` if `cardReaction(row) === "disliked"`, otherwise `dislike`. It sets `row.reaction` to `null` or `"disliked"` and re-renders the card in place.
   - **Block (req 5):** calls `blockVideoSource`, then `sendReaction("dislike")` with the same promise-to-message handling home uses. If the dislike failed, the status line reads `Blocked <label|action>, but the dislike failed: <msg>` and nothing is removed.
   - **Errors (req 7):** any thrown error writes `error.message`, or "Action failed", into the status line. A `finally` re-enables the button. No `ProfileKeyRejectedError` path is added, which is the operator's decision.
4. **Removal after a block (reqs 5, 8).** A search-page `removeRows(match)` filters `state.rows`. It removes from the grid each child `.video-card` whose `dataset.videoKey` belongs to a removed row; it walks the children and compares the dataset values, so no selector escaping is needed. It then calls `fillViewport()`. It does not touch `state.page`, `state.loadedRows`, `hasMore` or the status text, so those keep counting fetched rows, as the requirement's deliberate simplification states.
5. **Shared markup (req 9).** The Dislike button in `renderVideoCard` gains `aria-pressed="${reaction === "disliked"}"`, written the same way as Like's. Nothing else in the component changes.
6. **Home unchanged (req 10).** Home's code is not edited. Its only visible difference is the new `aria-pressed="false"` on its Dislike button. Home never shows a disliked card, because its dislike removes the card and the feed filters dislikes.
7. **Build (req 11).** Run `npm run build` in `client/frontend` so `dist/` carries the change.

### Alternatives considered

- **A shared `runCardAction` helper extracted from home, with callbacks for re-rendering, removing rows and choosing dislike mode.** Rejected. The two pages' dislike behaviour differs in the important way: home removes the card with no undo, while search toggles and keeps the card. A shared helper would therefore need a mode switch or a strategy callback just to serve two callers. It would also mean editing home's working handler, and home must stay exactly as it is. Mirroring costs about 45 lines in one file and carries no risk to home. The duplication is deliberate: a third page that needs card actions is the point to extract a helper.
- **Re-render the whole search grid from `state.rows` after a removal, the way home's `removeRows` calls `renderCards(true)`.** Rejected. It would wipe other cards' status lines and the keyboard focus, and repaint up to N×24 cards to remove a handful. Removing the matching DOM nodes is smaller and touches only what changed.
- **Track a separate visible count so the status line drops after a block.** Rejected for now. The requirements name it as the upgrade path. Paging stays correct without it.
- **Mapping a 401 on a card action to `keyRejectedNotice`.** Ruled out by the operator's decision in req 7 and by the out-of-scope rule on data-layer error types.

### Gotchas and risks

- **A reset while an action is running.** A new search, sort change or popstate can replace the grid while a request is in flight. The clicked card is then detached, and setting `outerHTML` on an element with no parent throws. So the re-render is guarded with `card.isConnected`. A block that finishes after a reset filters the new `state.rows` by that block's channel or account, which is the right result because those rows are blocked anyway. Re-enabling the button in `finally` on a detached node is harmless.
- **The same video on two loaded pages.** If the Engine's candidate pool ever returns a video twice, the lookup finds the first row, and a like or dislike re-renders only the clicked card. The other copy shows the old mark until the next search. Removal after a block matches by key and field, so it clears every copy.
- **Keyless dislike.** `cardReaction` ignores `row.reaction` when there is no key, but the no-key guard stops Dislike before any request, so no mismatch can appear.
- **Stale reactions after a profile change in another tab.** These are not handled. The rendered mark comes from the last search response, as it does on home.
- **The search fetch's `ProfileKeyRejectedError` handling is not touched.** A key rejected during a card action shows only as that card's status message, by the operator's decision. The next search read then shows the notice.

### Tradeoffs the operator is asked to accept

- The card-action handler exists twice, once in home and once in search, with intentionally different dislike semantics, instead of one shared helper.
- After a block, "Showing N of M matched videos." may overstate what is on screen until the next reset. This is the deliberate simplification in req 8, and its upgrade path is a separate visible count.
- Home's Dislike button gains an `aria-pressed="false"` attribute. Nothing else on home changes.

## Impacts

<impacts>
<impact path="client/frontend/src/pages/search/index.ts" element="module-level imports (lines 11-20)">
**What changes:** the imports grow, keeping the file's style (a multi-line brace list once a list gets long, as at lines 12-16).
- `../../components/video-card` (line 11) adds `resolveInstanceDomain`, `resolveVideoId` and `resolveVideoKey`. They are exported at video-card.ts lines 65, 72 and 80.
- `../../data/reactions` (line 18) adds `sendReaction`.
- `../../data/profile` (line 17) adds `getProfileKey` (profile.ts line 20).
- New import: `blockVideoSource` from `../../data/blocks` (blocks.ts line 33).

**What depends on it:** Rollup's chunk graph. Today the built search entry (`dist/assets/search-0tNFtc30.js`) imports safe-url, video-card, cache, reactions and key-rejected, but not blocks. See the dist entry for what the new import does to chunking.

**Risk:** low. `npm run build` is just `vite build` (package.json line 9), and Vite does not type-check, although tsconfig.json has `strict: true`. A wrong named import or a type error therefore passes the build. Run `npx tsc --noEmit` in client/frontend, or bundle with esbuild as the tests do.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="module docstring (lines 1-7)">
**What changes:** today it describes only URL state and infinite paging. Add one or two sentences:
- cards carry Like, Dislike, Block channel and Block account;
- Dislike toggles and the card stays, unlike home, because search is not filtered by dislikes (D6);
- a block removes the loaded cards of that channel or account, while "Showing N of M" keeps counting fetched rows.

**What depends on it:** nothing at runtime.

**Risk:** none at runtime. Without it, the code never says why search's handler differs from home's.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="state object (lines 49-60): new `rows` field">
**What changes:** add `rows: [] as VideoRow[]`, in the form home uses (videos/index.ts line 85), with a `/** ... */` comment like the ones on `hasMore` and `requestSeq`. `VideoRow` is already a type import at line 20.

**What depends on it:**
- the new click listener (`state.rows.find`);
- `renderRows`, which pushes onto it;
- `removeRows`, which reassigns it;
- `runCardAction`, through the row reference it holds and mutates (`row.reaction`).

**Risk:** moderate.
- A reset path that does not clear it lets a fresh card's key resolve to a stale row object with an old `reaction`, so the toggle sends the wrong action.
- Rows must be pushed only after the `seq` check at line 182. Otherwise a stale response adds rows that were never rendered.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="loadPage() reset block (lines 151-154) and the paths into it: startSearch (line 138), popstate (line 103), initial load (line 108), keyRejectedNotice retry (line 174)">
**What changes:** add `state.rows = []` in `if (reset)`, next to `results.innerHTML = ""` and `state.loadedRows = 0`. This one line covers new search, sort change (through `startSearch`), popstate, initial load and the "Forget key" retry.

**What depends on it:** the row lookup (req 2), and the plan's reset-during-action gotcha. A block that finishes after a reset filters the new `state.rows`.

**Risk:** low in this block. Clearing in `renderRows`' reset branch instead would leave stale rows behind a reset whose fetch failed (SearchUnavailable, ProfileKeyRejected or network). The grid is empty in that case, so no card could reach them, but the reset block is the cleaner place.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="loadPage() catch branch, ProfileKeyRejectedError (lines 172-174), and an appended-page failure">
**What changes:** nothing, per req 7.

**Interaction:** if an appended page (`reset=false`) fails with a rejected key, `results.replaceChildren(keyRejectedNotice(...))` wipes the grid but `state.rows` keeps the old rows. No `.video-card` is left, so no click resolves to a row and `removeRows` finds no node. The retry `loadPage(1, true)` clears the rows.

**What depends on it:** 401s from `/api/user-action` (user-actions.ts lines 33-37) and `/api/profile/blocks` (blocks.ts lines 64-66) come back as plain `Error`, so they show in the card's status line and never reach this branch.

**Risk:** no regression. The plan intentionally departs from issue 40 line 40 ("A rejected key is handled as the search page already handles `ProfileKeyRejectedError`"). The operator's decision is recorded in the record's step-1 conflicts.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="renderRows() (lines 204-214) and a new search card renderer (the counterpart of home's renderFeedCard, videos/index.ts lines 386-394)">
**What changes:**
- A new function, for example `renderSearchCard(row)`, returns `renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true })` and has a one-line `/** ... */` docstring.
- `renderRows` maps through it on both the `innerHTML` (reset) path and the `insertAdjacentHTML("beforeend")` path, and pushes the page's rows onto `state.rows`.
- `runCardAction` uses the same function for in-place re-renders, so the first render and a re-render cannot drift apart.

**What depends on it:**
- `.card-actions` is emitted only when `options.actions && videoKey` (video-card.ts line 352), so keyless rows stay bare.
- Cards remain direct children of `#search-results`, which `removeRows` relies on.

**Risk:** low. Each card gains a row of buttons and gets taller, so the sentinel sits further down and `fillViewport` (line 125) fetches fewer pages for the same viewport. That is a visual change, not a functional one.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new delegated click listener on `results` (#search-results)">
**What changes:** a top-level `results.addEventListener("click", ...)` next to the form and sort listeners (lines 70-83). It mirrors home's listener (videos/index.ts lines 135-141), except that the lookup is `state.rows.find((candidate) => resolveVideoKey(candidate) === key)` and not `state.sample`.

**What depends on it:**
- Cards on appended pages need no extra wiring (req 8).
- The `keyRejectedNotice` "Forget key" button (key-rejected.ts lines 17-24) also lives in `#search-results`. It has no `data-card-action`, so the listener ignores it.
- `.card-actions` sits outside `<a class="video-link">` (video-card.ts line 351), so buttons do not navigate.

**Risk:** low.
- `event.target` may be an SVG `<path>` inside a button; `closest` handles that, as on home.
- A disabled button dispatches no click, so double-clicking during an action does nothing.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new runCardAction(button, card, row)">
**What changes:** new code modelled on home's (videos/index.ts lines 400-447).

**Same as home:**
- the `say` helper into `.card-action-status`;
- the no-key guard and its exact text (line 409);
- `button.disabled = true` and `say("")` before the request, and re-enable in `finally`;
- Like toggles on `cardReaction(row) === "liked"`;
- Block is `blockVideoSource`, then `sendReaction("dislike").then(() => null, err => message)`, then the "Blocked … but the dislike failed" early return;
- the predicate at lines 434-440;
- the `"Action failed"` fallback.

**Different from home:**
- `apiBase` is `apiParam ?? ""`. Home passes an already-resolved URL from `resolveApiBase(similarQuery)` (videos/index.ts line 79, data/videos.ts line 92). All the data functions run their argument through `resolveClientApiBase`, so both forms work.
- Dislike sends `undo_dislike` when `cardReaction(row) === "disliked"` and `dislike` otherwise, sets `row.reaction`, and re-renders in place without removing the card.
- Both re-renders are guarded with `card.isConnected`.

**What depends on it:** `sendReaction` and `cardReaction` (reactions.ts), `blockVideoSource` (blocks.ts), `getProfileKey` (profile.ts), and the `data-card-action` values and the status span in video-card.ts lines 354-359. On the server, `_store_reaction` (client/backend/server.py lines 871-901) makes a like and a dislike replace each other, and `undo_dislike` takes the delete path. That confirms the `row.reaction` values the plan sets.

**Risk:** medium.
1. `outerHTML` on a detached card throws. Without the guard on both paths, the catch then writes into a dead node.
2. `row.reaction` must be set before the re-render, because `cardReaction` reads it when a key is held (reactions.ts line 53).
3. Search users can now reach the dislike cap (a 400 "Dislike limit reached") and the 502 for a centroid failure. Both show as the card's message.
4. The `outerHTML` swap drops keyboard focus. Home's Like already does this; search's Dislike now does too.
5. The handler is duplicated by hand from home's.
6. There is no `ProfileKeyRejectedError` branch, by decision.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new removeRows(match)">
**What changes:**
- Filter `state.rows`.
- Collect `resolveVideoKey` of the removed rows into a Set.
- Walk `Array.from(results.children)` and `.remove()` each element whose `dataset.videoKey` is in the Set.
- Call `fillViewport()`.
- Leave `state.page`, `loadedRows`, `total`, `hasMore` and the status text untouched (req 8).

**What depends on it:** the block path. `fillViewport` leads to `loadNextPage` (line 116), which returns early while `state.loading` is set or `hasMore` is false.

**Risk:** low to medium.
1. The predicate must equal home's exactly. Search rows carry `instance_domain`, `channel_id` and `account_url` (engine/server/data/search.py lines 56, 57 and 63).
2. A next page already in flight when the block lands was filtered server-side before the block existed, so it can bring that channel back. Home has the same race.
3. If a block empties the grid with `hasMore` false, "Showing N of M" stays and no "No results" appears. This is the accepted simplification.
4. The attribute is escaped with `escapeHtml` but `dataset` reads it back unescaped, so it compares directly with raw `resolveVideoKey` and needs no CSS escaping.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="showIdle() (lines 219-228)">
**What changes:** add `state.rows = []` next to `state.loadedRows = 0`.

**What depends on it:** an empty submit (line 74) and a popstate to a URL with no `q` (line 100).

**Risk:** low. If it is missed, the leftover rows are unreachable because the grid is emptied. A block that finishes after idle filters them, and `fillViewport` returns early because `hasMore` is false.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="no-key prompt text (req 6) and the search page's chrome">
**What changes:** search shows home's exact text: "Disliking/Blocking needs a profile. Create one from the Profile button."

**What depends on it:** search.html. Its nav (lines 21-27) has no Profile button and no profile modal. A grep for "profile" across the HTML sources matches only index.html and videos.html.

**Risk:** a UX copy mismatch, not a regression. On search, the prompt points at a button the page does not have. Req 6 demands the exact text, so the operator should rule on the wording rather than the implementer quietly changing it.
</impact>
<impact path="client/frontend/search.html" element="#search-results (line 58), #search-status (line 55), header nav (lines 21-27), CSP meta (line 8)">
**What changes:** nothing.

**What depends on it:**
- The listener is attached to `#search-results` (class `cards-grid`).
- Each card's `.card-action-status` is a separate `role="status"` region, apart from `#search-status`.
- The CSP (`script-src 'self'`) is unaffected, because the new code adds no inline script and no inline handler.

**Risk:** none.
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="renderVideoCard() action markup, Dislike button (line 356)">
**What changes:** insert `aria-pressed="${reaction === "disliked"}"` after `data-card-action="dislike"`, in the same form as Like's attribute on line 355. No other change to the component.

**What depends on it:**
- `renderVideoCard` has two callers: home's `renderFeedCard` (videos/index.ts line 387) and search's `renderRows` (search/index.ts line 208).
- likes/index.ts line 9 imports only `channelName`, `escapeHtml`, `thumbnailUrl` and `videoPageUrl`. The video page does not import video-card.ts at all (imports at video-page/index.ts lines 5-20).
- `.card-action[aria-pressed="true"] svg` (videos.css line 664) is generic, so a pressed Dislike fills its icon with no CSS change.

**Risk:** low.
- Home's Dislike is now announced as a "not pressed" toggle even though it is a one-shot remove there. Issue 40 line 43 allows this.
- `"true"` cannot appear on home, because feeds drop disliked rows (server.py line 469) and home's Dislike removes the card.
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="VideoCardOptions comments (lines 34-37) and module docstring (lines 1-12)">
**What changes:** nothing is required; both stay accurate. Optionally, the `reaction` comment at line 34 could say that it also sets `aria-pressed` on the Like and Dislike buttons.

**Risk:** none.
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="home click listener (lines 135-141), renderFeedCard (lines 386-394), runCardAction (lines 400-447), removeRows (lines 452-457)">
**What changes:** nothing (req 10). This is the reference that search copies.

**What depends on it:** the acceptance criterion that home's dislike and block still remove cards and home has no undo-dislike.

**Risk:**
- Only the shared markup reaches home, and home never reads `aria-pressed`.
- The implementer must not "tidy" home while copying from it, for example by adding an `isConnected` guard or `undo_dislike` there.
</impact>
<impact path="client/frontend/src/data/reactions.ts" element="sendReaction() (lines 89-100), cardReaction() (lines 52-57), AFTER (lines 20-25)">
**What changes:** nothing. Search calls `sendReaction` for the first time.

**What depends on it:**
- A keyless like or undo-like is written to `localLikes:v1` before `sendReaction` resolves (lines 95-98), so a keyless re-render reads it correctly.
- `undo_dislike` is a valid `ReactionAction` (line 16).

**Known gap, inherited from home and not introduced here:**
- Keyless, the like is stored under `resolveVideoId(row)`, which falls back to `video_id` when `video_uuid` is null (video-card.ts lines 72-75). `cardReaction` (lines 54-56) checks only `video_uuid`/`videoUuid`.
- So a keyless Like on a row with a null `video_uuid` (the column is nullable in engine/crawler/schema.sql) succeeds but never shows as liked, and the next click sends `like` again.
- Fixing it is out of scope for this build, because it would change `reactions.ts` and home with it.

**Risk:** none to the module. The gap is a low risk on the search page.
</impact>
<impact path="client/frontend/src/data/blocks.ts" element="blockVideoSource() (lines 33-41) and request() (lines 51-68)">
**What changes:** nothing.

**What depends on it:** search's block path.
- Every non-OK answer, 401 included, throws a plain `Error(payload.error ?? "Block request failed (N)")`, which fits req 7.
- `Block` has `kind`, `instance_domain`, `channel_id`, `account_url` and `label` (lines 13-20).

**Risk:** none. A reply without `kind` would fall into the account branch on both pages.
</impact>
<impact path="client/frontend/src/data/user-actions.ts" element="sendUserAction() (lines 18-38)">
**What changes:** nothing.

**What depends on it:** every Like and Dislike on search, through `sendReaction`. On any non-OK status it throws `Error(body.error ?? "Failed to send action")`. That text, including the server's messages for the dislike cap and for a missing key, is what reaches the card's status line.

**Risk:** none.
</impact>
<impact path="client/frontend/src/data/api-base.ts" element="resolveClientApiBase() (lines 18-33)">
**What changes:** nothing.

**What depends on it:** search passes `apiParam ?? ""`. Resolution order is `VITE_CLIENT_API_BASE` first, then `?api=` in DEV only, then `window.location.origin`. In production, `?api=` is ignored, so passing `apiParam` cannot redirect card actions.

**Risk:** none.
</impact>
<impact path="client/frontend/src/data/profile.ts" element="getProfileKey() (lines 20-26)">
**What changes:** nothing. Search imports it for the first time, for the no-key guard.

**What depends on it:** the guard. It reads `localStorage` `profileKey:v1` on each call, so a key created in another tab takes effect on the next click.

**Risk:** none.
</impact>
<impact path="client/frontend/src/data/search.ts" element="fetchSearchResults(): keyed no-store branch (lines 68-76) and keyless sessionStorage cache (lines 78-90)">
**What changes:** nothing.

**What depends on it:** the "rerun the same search" acceptance checks.
- With a key, the fetch is `cache: "no-store"`, so a rerun shows a dislike, an undo or a block at once.
- Without a key, results are cached for 30 s, but cache.ts re-parses from sessionStorage on every read (cache.ts lines 44-58), so mutating `row.reaction` in place never leaks into the cache.
- Keyless actions are limited to Like, whose mark comes from `localLikes:v1`.

**Risk:** none. Rerun checks must use a key.
</impact>
<impact path="client/frontend/src/data/cache.ts" element="fetchJsonWithCache / readCache / writeCache">
**What changes:** nothing.

**What depends on it:** the keyless search path. `writeCache` stores `JSON.stringify(payload)` before the rows are handed to the page, and `readCache` parses fresh objects, so search's in-place `row.reaction` writes cannot corrupt cached pages.

**Risk:** none.
</impact>
<impact path="client/frontend/src/types/videos.ts" element="VideoRow: channel_id (line 10), account_url (line 15), reaction (lines 51-52)">
**What changes:** nothing.

**What depends on it:** search's block predicate and the `row.reaction` assignments. The type is `"liked" | "disliked" | null`.

**Risk:** none.
</impact>
<impact path="client/frontend/src/components/key-rejected.ts" element="keyRejectedNotice(onForget)">
**What changes:** nothing.

**What depends on it:** its retry calls `loadPage(1, true)`, a reset path that must clear `state.rows`. Its button sits inside `#search-results` and has no `data-card-action`, so the new listener ignores it.

**Risk:** none.
</impact>
<impact path="client/frontend/src/videos.css" element=".stat.active (lines 616-623), .card-actions … .card-action-status:empty (lines 625-676), .visually-hidden (lines 678-685), :root variables (lines 5-8)">
**What changes:** nothing. Search already imports it (search/index.ts line 9), and the variables the card actions use (`--line`, `--accent-strong`, `--muted`) are defined in this file.

**What depends on it:**
- the action row layout;
- the filled icon for a pressed Dislike (line 664);
- the disliked stat mark;
- the hidden "Like" and "Dislike" labels.

**Risk:** low.
- There is no `.video-card.disliked` rule, so the root class has no visual effect.
- Search cards get taller; check this visually.
</impact>
<impact path="client/frontend/src/search.css" element="whole file, including its own .visually-hidden (lines 69-79)">
**What changes:** nothing. No rule targets `.card-action*` or `.video-card`. The header comment (lines 1-3) says the cards reuse videos.css.

**What depends on it:** `.visually-hidden` is defined both here and in videos.css with the same specificity. The built search.html loads search CSS before videos CSS (dist/search.html lines 18-19), so for overlapping properties the videos.css copy wins. Both hide the button labels, so this is not a regression.

**Risk:** none.
</impact>
<impact path="client/backend/server.py" element="FEED_ROUTES/FILTERED_ROUTES (lines 71-72), _profile_filter dropped rule (line 469), _store_reaction (lines 871-901), _filter_payload (lines 1096-1122)">
**What changes:** nothing; this is out of scope.

**What depends on it:**
- Search is filtered by blocks but never by dislikes (D6), so the card can stay after a Dislike, and a rerun returns the row with `reaction: "disliked"`.
- `reaction` is keyed on `(video_id, instance_domain)`.
- Like/dislike replacement and `undo_dislike` (lines 871-901) are what search's toggle relies on.
- `total` is not adjusted after filtering, which is why the req 8 count is honest only about fetched rows.

**Risk:** none from this build. If D6 is ever reversed, search's toggle and keep-card behaviour need revisiting.
</impact>
<impact path="engine/server/data/search.py" element="VIDEO_ROW_SQL (lines 51-79)">
**What changes:** nothing.

**What depends on it:** search's key, its toggle and its block predicate use `video_id` (53), `video_uuid` (54), `instance_domain` (56), `channel_id` (57) and `account_url` (63). All are present.

**Risk:** none.
</impact>
<impact path="client/frontend/vite.config.ts" element="build.rollupOptions.input (lines 84-94)">
**What changes:** nothing. `search.html` is already an entry (line 87).

**What depends on it:** the rebuild. The `about` entry uses `dev-pages/about.html` if that file exists. Only `about.template.html` is present today.

**Risk:** none, unless a local `about.html` appears before the build.
</impact>
<impact path="client/frontend/package.json" element="scripts.build (line 9) and the frontend toolchain">
**What changes:** nothing. Req 11 runs `npm run build` (that is, `vite build`).

**What depends on it:** the dist rebuild and any esbuild-based test. Uncertain: a Glob of `client/frontend/node_modules/.bin/*` in this worktree returned nothing, and the Read was blocked by the sandbox. node_modules may be missing here or symlinked from outside the project. If it is missing, `npm ci` is needed in the worktree first. `tests/active/test_frontend_*.py` also resolve `FRONTEND/node_modules/.bin/esbuild`.

**Risk:** low, but the build or the tests can fail for environment reasons rather than code reasons.
</impact>
<impact path="client/frontend/dist/" element="built bundle: *.html and assets/*">
**What changes:** `npm run build` regenerates it, and `dist/` is tracked. Correcting the earlier inventory, these are the actual importers:
- **video-card chunk** (`video-card-C4VEive-.js`): imported by `index-OsZsLoAr.js`, `likes-xsQYeXe5.js` and `search-0tNFtc30.js`, and referenced by index.html, videos.html, likes.html and search.html. channels and video-page do not import it.
- **The chunk named `blocks-DRgP8l-1.js` is a merged chunk.** It holds data/videos.ts (createFeedPager, buildSimilarUrl, resolveApiBase) as well as blocks.ts. index and video import it; video-page.html, index.html and videos.html reference it.
- **Effect of search importing blocks.ts:** blocks.ts will be shared by three entries while data/videos.ts stays shared by two. Rollup will likely split them, which means a new chunk file, a changed blocks chunk, and new hashes for `index-*.js`, `video-*.js` and their HTML pages as well as search and likes. This is a prediction, not verified.

Old hashed files are deleted.

**What depends on it:** the served site. scripts/sync.sh line 19 builds, then rsyncs with `--delete` (line 22). DEPLOYMENT.md line 390 says the committed dist lags the source.

**Risk:** medium for the commit, low for the code.
- Run the build once, after both source edits.
- Commit the whole dist diff, added and deleted files included. A partial commit leaves HTML pointing at missing chunks.
- Skipping the build fails the acceptance criterion.
</impact>
<impact path="tests/active/test_frontend_reactions.py" element="cards step of RUNNER (lines 86-99) and _bundle (lines 106-124)">
**What changes:** nothing needed. It renders `renderVideoCard(row, { reaction })` without `actions`, so the new attribute is never emitted, and its regexes target only `class="stat likes active"` and `class="stat dislikes active"`.

**Risk:** none. It remains the guard for `cardReaction` over search rows.
</impact>
<impact path="tests/active/test_frontend_videos_page.py" element="home runner and fake DOM (lines 22-90)">
**What changes:** nothing needed. It asserts only the `data-video-key` values in `#video-cards` (line 89), so the extra `aria-pressed` on home's markup does not affect it.

**Risk:**
- None to this test.
- It does not guard card actions: its fake element has `closest: () => null` (line 51) and no `outerHTML`, `isConnected` or `dataset`.
- Its esbuild bundling of a page entry is the template for a search-page test.
</impact>
<impact path="tests/active/test_frontend_blocks.py" element="block runner steps">
**What changes:** nothing.

**What depends on it:** it pins the `Block` shape that search consumes.

**Risk:** none.
</impact>
<impact path="tests/active/ (new search-page card-action test; filename to be decided, drafted in tests/tmp first)">
**What changes:** a grep for `pages/search`, `search.html`, `search-results` and `video-card` under tests/ and tests/tmp finds no test that loads the search page, so every acceptance criterion here is unguarded.

**Candidate test:** bundle `src/pages/search/index.ts` with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`), as test_frontend_videos_page.py does. Assert that:
- appended pages render the buttons;
- Dislike sends `dislike` then `undo_dislike`, and `aria-pressed` flips between true and false;
- no request is made without a key;
- a block removes the matching cards and calls `fillViewport`;
- a re-render after a reset does not throw.

Rerun checks need a key, against `engine_client` or `unpublished_client`.

**Risk:** the fake DOM needs `closest`, `outerHTML`, `isConnected`, `dataset`, element children and `remove`. That is a richer fake than any existing test has.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="frontend gateway boundary grep">
**What changes:** nothing. The new code calls only Client routes (`/api/user-action`, `/api/profile/blocks`), through the existing data modules.

**Risk:** none.
</impact>
<impact path="client/frontend/README.md" element="'What it does' list, line 16 (reaction marks)">
**What changes:** documentation; see the checklist. Line 16 covers the reaction marks, but no bullet describes the card action buttons on either feed or search. The feed-grid controls are undocumented too.

**Risk:** none at runtime.
</impact>
<impact path="docs/project/roadmap.md" element="F13-M2 (line 54) and the Delivered section (lines 7-25)">
**What changes:** after this build, the feed-grid and search-grid halves of F13-M2 are in the tree and only the channels page remains. No Delivered entry exists for the feed-grid half either; the archived plan 07 line 33 only defers it. Which change delivered it could not be established from the docs.

**Risk:** none at runtime; traceability only.
</impact>
<impact path="docs/project/issues/40-search-card-actions.md" element="Status line (line 3), Comments, location">
**What changes:** on delivery, per issue-tracker.md line 21:
- set `Status: enhancement, complete`;
- append a comment that names the plan and records the req 7 decision, which departs from the brief at line 40;
- move the file to `docs/project/issues/archive/`.

**Risk:** traceability only.
</impact>
<impact path="docs/project/plans/20-40-search-card-actions.md" element="Impacts and Documentation sections">
**What changes:** the workflow re-renders them from the run state; the header at line 3 says manual edits are overwritten. At delivery the plan moves to `docs/project/plans/archive/` (issue-tracker.md line 29).

**Risk:** none at runtime.
</impact>
<impact path="client/README.md" element="user-action and gateway filtering (lines 19, 24-25)">
**What changes:** nothing. It already says the dislike actions need a key, a like and a dislike replace each other, search is not filtered by dislikes, and rows carry `reaction`.

**Risk:** none.
</impact>
<impact path="DEPLOYMENT.md" element="likes and dislikes paragraph (line 360), dist sync note (lines 386-390)">
**What changes:** nothing. "Search is not filtered by dislikes" and "which the frontend shows on the card" both still hold. The sync note is the deploy step that follows req 11.

**Risk:** none.
</impact>
<impact path="CONTEXT.md" element="glossary: Dislike (line 4), Block (line 11)">
**What changes:** nothing. The Dislike entry says a dislike removes the video from feeds, not from search, which matches search keeping the card. No new term is introduced.

**Risk:** none.
</impact>
</impacts>

## Documentation to update

- [x] `client/frontend/README.md` - updated: Added two "What it does" bullets on the card action buttons (Like, Dislike, Block channel, Block account) on home feed and search cards.
- [x] `docs/project/roadmap.md` - updated: Added a Delivered entry for the F13-M2 search card controls (issue `40`) and cut F13-M2 down to the channels-page block controls.
- [x] `docs/project/issues/40-search-card-actions.md` - updated: Closed issue 40 as delivered: set the Status line to `enhancement, complete`, added a delivery comment and wrote the file to `docs/project/issues/archive/`, but the original is still in `issues/` and has to be deleted by hand.
- [x] `docs/project/plans/20-40-search-card-actions.md` - updated: I made no edit to the plan's content, and I could not move the file: it is still at `docs/project/plans/20-40-search-card-actions.md` and needs a `git mv` into `docs/project/plans/archive/`.

## Implementation plan

## Draft implementation — issue 40, search card actions

### Module map

| File | Change |
|---|---|
| `client/frontend/src/components/video-card.ts` | Line 356: the Dislike button gains `aria-pressed="${reaction === "disliked"}"`, written exactly like Like's on line 355. Nothing else changes. |
| `client/frontend/src/pages/search/index.ts` | Changes: imports, docstring, `state.rows`, the reset in `loadPage`, `showIdle`, `renderRows`, a new `renderSearchCard`, a delegated click listener, `runCardAction` and `removeRows`. |
| `client/frontend/src/pages/videos/index.ts` | Not touched (req 10). |
| `client/frontend/dist/` | Rebuilt once with `npm run build` after both source edits. The whole diff is committed, including added and deleted chunks. |
| `tests/tmp/test_frontend_search_card_actions.py` | New test, drafted here and promoted to `tests/active/` (see "What has to be tested"). |

There is no new shared module. Home's handler is copied into search on purpose (plan, Alternatives §1).

### `components/video-card.ts`, line 356

```ts
        <button type="button" class="card-action" data-card-action="dislike" aria-pressed="${reaction === "disliked"}" title="Dislike">${iconThumbDown()}<span class="visually-hidden">Dislike</span></button>
```

Invariant: `aria-pressed` is `"true"` only when `options.reaction === "disliked"`. Home never passes that value, because its feeds drop disliked rows, so home always renders `"false"`.

### `pages/search/index.ts`

**Docstring (lines 1-7)**: add a paragraph:

```ts
 *
 * Each card carries Like, Dislike, Block channel and Block account. Unlike home, Dislike toggles and
 * the card stays, because search is not filtered by dislikes (D6). A block removes the loaded cards of
 * that channel or account, while "Showing N of M" keeps counting fetched rows.
```

**Imports (lines 11-18)**:

```ts
import {
  renderVideoCard,
  resolveInstanceDomain,
  resolveVideoId,
  resolveVideoKey
} from "../../components/video-card";
import {
  fetchSearchResults,
  SearchUnavailableError,
  type SearchSort
} from "../../data/search";
import { getProfileKey, ProfileKeyRejectedError } from "../../data/profile";
import { cardReaction, importLocalLikes, sendReaction } from "../../data/reactions";
import { blockVideoSource } from "../../data/blocks";
import { keyRejectedNotice } from "../../components/key-rejected";
import type { SearchPayload, VideoRow } from "../../types/videos";
```

**State (lines 49-60)**: add after `total`:

```ts
  /** Rows rendered into the grid, in order; card actions find their row here by video key. */
  rows: [] as VideoRow[],
```

**Click listener**: placed after the `sortSelect` listener (after line 83), mirroring home's listener at videos/index.ts lines 135-141:

```ts
results.addEventListener("click", (event) => {
  const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>("[data-card-action]");
  const card = button?.closest<HTMLElement>(".video-card");
  const key = card?.dataset.videoKey;
  const row = key ? state.rows.find((candidate) => resolveVideoKey(candidate) === key) : undefined;
  if (button && card && row) void runCardAction(button, card, row);
});
```

Invariant: a click resolves to a row only when the button, the card, the key and a stored row all exist. Anything else does nothing, including the keyRejectedNotice "Forget key" button, which has no `data-card-action`.

**`loadPage` reset block (lines 151-154)**:

```ts
  if (reset) {
    results.innerHTML = "";
    state.loadedRows = 0;
    state.rows = [];
  }
```

This one line covers new search, sort change, popstate, initial load and the key-rejected retry. `renderRows` is called only after the `seq` check at line 182, so a stale response can never push rows.

**`renderRows` (lines 207-214)** and the new renderer:

```ts
/**
 * Render rows into the grid through the shared card component and remember them for card actions.
 */
function renderRows(rows: VideoRow[], reset: boolean) {
  const markup = rows.map(renderSearchCard).join("");
  state.rows.push(...rows);
  if (reset) {
    results.innerHTML = markup;
    return;
  }
  results.insertAdjacentHTML("beforeend", markup);
}

/**
 * Render one search card with its action controls; used for first renders and in-place re-renders.
 */
function renderSearchCard(row: VideoRow) {
  return renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true });
}
```

Invariant: `state.rows` holds the rendered rows in DOM order, and each keyed row has exactly one `article.video-card[data-video-key]` as a direct child of `#search-results`. `rows.map(renderSearchCard)` is safe because `map`'s index argument lands nowhere: `renderSearchCard` takes one parameter.

**`runCardAction`**: a copy of home's lines 400-447 with only the differences the plan names:

```ts
/**
 * Like, dislike or block from a card; a block dislikes the video too. Like and Dislike toggle and the
 * card stays, marked; a block takes every loaded card of that channel or account off the page.
 */
async function runCardAction(button: HTMLButtonElement, card: HTMLElement, row: VideoRow) {
  const action = button.dataset.cardAction ?? "";
  const apiBase = apiParam ?? "";
  const uuid = resolveVideoId(row);
  const host = resolveInstanceDomain(row);
  const status = card.querySelector<HTMLElement>(".card-action-status");
  const say = (text: string) => {
    if (status) status.textContent = text;
  };
  if (action !== "like" && !getProfileKey()) {
    say(`${action === "dislike" ? "Disliking" : "Blocking"} needs a profile. Create one from the Profile button.`);
    return;
  }
  button.disabled = true;
  say("");
  try {
    if (action === "like") {
      const liked = cardReaction(row) === "liked";
      await sendReaction(apiBase, liked ? "undo_like" : "like", { uuid, host });
      row.reaction = liked ? null : "liked";
      // A reset during the request detaches the card; outerHTML on a detached node throws.
      if (card.isConnected) card.outerHTML = renderSearchCard(row);
    } else if (action === "dislike") {
      const disliked = cardReaction(row) === "disliked";
      await sendReaction(apiBase, disliked ? "undo_dislike" : "dislike", { uuid, host });
      row.reaction = disliked ? null : "disliked";
      if (card.isConnected) card.outerHTML = renderSearchCard(row);
    } else if (action === "channel" || action === "account") {
      const block = await blockVideoSource(apiBase, action, uuid, host);
      // Blocking also dislikes the video, as on home.
      const disliked = await sendReaction(apiBase, "dislike", { uuid, host }).then(
        () => null,
        (error: unknown) => (error instanceof Error ? error.message : "Dislike failed")
      );
      if (disliked !== null) {
        say(`Blocked ${block.label || action}, but the dislike failed: ${disliked}`);
        return;
      }
      removeRows(
        block.kind === "channel"
          ? (candidate) =>
              String(candidate.instance_domain ?? "") === block.instance_domain &&
              String(candidate.channel_id ?? "") === block.channel_id
          : (candidate) => String(candidate.account_url ?? "") === block.account_url
      );
    }
  } catch (error) {
    say(error instanceof Error ? error.message : "Action failed");
  } finally {
    button.disabled = false;
  }
}
```

Invariants:
- `row.reaction` is assigned only after the request resolves. A failure leaves both the row and the card unchanged, and the message appears in the old card's status line, which is still attached.
- `row.reaction` is assigned before the re-render, because `cardReaction` reads it when a key is held.
- After a successful Like or Dislike, `button` and `status` belong to the replaced, detached node. The `finally` re-enables that detached button, which is harmless, and the new card renders enabled. This matches home's Like.
- No branch for `ProfileKeyRejectedError` (req 7, operator decision). A 401 arrives as a plain `Error` and is shown with `say`.
- The block predicate is home's lines 434-440, character for character.

**`removeRows`**:

```ts
/**
 * Drop matching rows and their cards in place, then refill the viewport. Paging counters keep
 * counting fetched rows: the Client filters each Engine page, so page numbers do not shift.
 */
function removeRows(match: (row: VideoRow) => boolean) {
  const removed = new Set(state.rows.filter(match).map((row) => resolveVideoKey(row)));
  state.rows = state.rows.filter((row) => !match(row));
  for (const element of Array.from(results.children) as HTMLElement[]) {
    const key = element.dataset.videoKey;
    if (key && removed.has(key)) element.remove();
  }
  fillViewport();
}
```

Invariant: `state.page`, `loadedRows`, `total`, `hasMore` and the status text are not touched (req 8, deliberate simplification). `dataset.videoKey` gives back the unescaped key, so it compares directly with `resolveVideoKey`, with no selector escaping. Keyless rows never have a card with controls and cannot be the clicked row. If a keyless row matched a block, it would be dropped from `state.rows`, but its card has no `data-video-key` and stays on the page. That is harmless and inert. `fillViewport` returns early while a page is loading or `hasMore` is false.

**`showIdle` (lines 219-228)**: add `state.rows = [];` after `state.loadedRows = 0;`.

### Requirement trace (check pass 1 — converged)

| Req | Where it is met |
|---|---|
| 1 Controls | `renderSearchCard` passes `actions: true`, and `renderRows` uses it on both paths. Keyless rows get no controls because of video-card.ts line 352. |
| 2 Row lookup | `state.rows`, the resets in `loadPage(reset)` and `showIdle`, and the delegated listener. |
| 3 Like | The toggle on `cardReaction(row) === "liked"`, followed by an in-place `renderSearchCard`. |
| 4 Dislike toggle | The `undo_dislike`/`dislike` branch, the in-place re-render, and the `aria-pressed` added in video-card.ts. |
| 5 Block | `blockVideoSource`, then `sendReaction("dislike")`. A failed dislike gets the early return with the message; otherwise `removeRows` runs with home's predicate. |
| 6 No key | Home's guard and its exact text. No request is sent. |
| 7 Errors | Disabled button, `say(message \|\| "Action failed")`, re-enable in `finally`. No change to the data layer. |
| 8 Paging | The listener is on the container. Counters are untouched. `removeRows` calls `fillViewport()`. |
| 9 Markup | One attribute on line 356. |
| 10 Home | `videos/index.ts` is not edited. |
| 11 Build | `npm run build`, preceded by `npx tsc --noEmit`, because Vite does not type-check. |

I checked the plan's risks as well: the reset during an action is handled by `isConnected`; a block landing after a reset filters the new rows, which is correct; a duplicate video is handled because `removeRows` is key-based and clears every copy. One copy concern remains, below.

**Flag, not a fix:** search.html has no Profile button, so the required text "…Create one from the Profile button." points at nothing on this page. Req 6 requires the exact text, so the draft keeps it. The issue 40 delivery comment should record that the wording was kept, as the documentation checklist asks.

### What has to be tested

`tests/tmp/test_frontend_search_card_actions.py`. It bundles `src/pages/search/index.ts` with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`), modelled on `test_frontend_videos_page.py`. It runs under node with a fake DOM that supports `closest`, `dataset`, `children`, `remove`, `outerHTML` (re-parsed into a new node) and `isConnected`, a stub `fetch` that records method, path and body, and an `IntersectionObserver` stub. Cases:

1. Page 1 plus an appended page 2: every keyed card has four `[data-card-action]` buttons, and a keyless row has none.
2. With a key, Dislike sends `dislike`, and the card re-renders with `stat dislikes active` and Dislike `aria-pressed="true"`. A second click sends `undo_dislike` and the mark clears (`aria-pressed="false"`).
3. Like on a disliked card sends `like` and the card shows liked, not disliked. A second click sends `undo_like`.
4. Without a key, Dislike, Block channel and Block account each write the exact prompt and make no fetch. Keyless Like sends `like` and stores it in `localLikes:v1`.
5. Block channel: `POST /api/profile/blocks`, then `dislike`. Every loaded card with the same `instance_domain`+`channel_id` is removed, including on page 2, and `fillViewport` runs (the sentinel is in view, so page 3 is fetched). The status text is unchanged. Block account works the same way through `account_url`.
6. Block where the dislike returns 500: the status line reads `Blocked <label>, but the dislike failed: <msg>` and no card is removed.
7. A failed request (400 "Dislike limit reached"): the message appears in the status line, the button is re-enabled, and `row.reaction` is unchanged.
8. A reset while an action is in flight (a new search resolves first): no exception, and `state.rows` holds only the new rows.
9. The rendered markup of `renderVideoCard(row, { actions: true, reaction: null })` has Dislike `aria-pressed="false"`. This is home's case.

The acceptance reruns (a keyed rerun of the search shows `reaction: "disliked"`, no reaction after undo, and no blocked-channel rows) are backend facts, already covered by D6 and `_filter_payload`. They are checked manually against a live Client with a key, or by `engine_client` if the test is extended. The existing `test_frontend_reactions.py`, `test_frontend_blocks.py` and `test_frontend_videos_page.py` must stay green unchanged.


### Phases

#### Phase 1 - Dislike pressed state in the shared card [code]

**Files touched.** client/frontend/src/components/video-card.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (NEW)

**Checkpoint.** Seam: `renderVideoCard` in `client/frontend/src/components/video-card.ts`, called directly from a small esbuild bundle that re-exports it. This follows the precedent in `tests/active/test_frontend_reactions.py` (line 112 re-exports `renderVideoCard` from the component and asserts on the returned markup). The test lives in `tests/tmp/test_frontend_search_card_actions.py` and renders a keyed row with `{ actions: true, reaction: "disliked" }`, `{ actions: true, reaction: null }` (home's case) and `{ actions: true, reaction: "liked" }`. On the `[data-card-action="dislike"]` button it asserts `aria-pressed="true"` for the first and `aria-pressed="false"` for the other two. `npx tsc --noEmit` passes in `client/frontend`.

**Intent.** `renderVideoCard` in `components/video-card.ts` now reports the Dislike button's pressed state from `options.reaction`, the same way it already does for Like.

- C1 - The Dislike button has `aria-pressed="true"` when `options.reaction` is `"disliked"`, and `aria-pressed="false"` otherwise.

**Outcome.** ### client/frontend/src/components/video-card.ts
In `renderVideoCard`, the Dislike action button (`data-card-action="dislike"`) now has `aria-pressed="${reaction === "disliked"}"`, which follows how the Like button already does it. It renders `"true"` when `options.reaction` is `"disliked"` and `"false"` in every other case: `null`, `"liked"`, or the option left out. `reaction` already falls back to `null`, so the attribute is always present. No other markup changed.

**Beyond the files named.** none. One note: the phase's file list names `tests/tmp/test_frontend_search_card_actions.py (NEW)`, but the gating checkpoint is `tests/tmp/test_40_search_card_actions_phase1.py`, and that already exists. I did not create the listed file because the checkpoint covers this phase. If the build expects that path to exist, it is still missing.

#### Phase 2 - Search card controls and Like/Dislike toggles [code]

**Files touched.** client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED)

**Checkpoint.** Seam: the search page entry, `client/frontend/src/pages/search/index.ts`. It is bundled with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`) and run under node with a stub `fetch` that records method, path and body, plus an `IntersectionObserver` stub. This follows `tests/active/test_frontend_videos_page.py`. That harness's fake DOM stubs `closest` to return null, so this phase builds a richer fake DOM in the new test file, and phases 3 and 4 reuse it. The new DOM supports `closest`, `dataset`, `children`, `remove`, an `outerHTML` setter that re-parses into a new node, and `isConnected`. Assertions, all made through the DOM and the recorded fetches:
(a) After page 1 and an appended page 2, every keyed `.video-card` under `#search-results` has four `[data-card-action]` buttons, and a keyless row's card has none.
(b) With a key, clicking Dislike sends `dislike`, and the card re-renders with `stat dislikes active` and `aria-pressed="true"`. A second click sends `undo_dislike` and the mark clears. Like on a disliked card sends `like` and the card shows liked, not disliked. A second Like sends `undo_like`. Without a key, Like sends `like` and the like is stored in `localLikes:v1`.
(c) If a new search resolves while a Like is in flight, nothing throws, and the grid and `state.rows` (observed through a following click) hold only the new search's rows.

**Intent.** In `pages/search/index.ts`, keyed search cards on every loaded page carry the card actions, and a Like or Dislike click on one toggles that reaction through the reactions API and re-renders the card in place.

- C1 - Every keyed card on the first page and on an appended page has the four `[data-card-action]` controls, and a keyless card has none.
- C2 - A Like or Dislike click sends the toggled reaction and re-renders that card in place with the new mark, without throwing when a reset replaced the grid mid-request.

**Outcome.** ### client/frontend/src/pages/search/index.ts
- **Docstring.** One paragraph added: each card carries Like, Dislike, Block channel and Block account, and unlike home, Dislike toggles and the card stays marked, because search is not filtered by dislikes (D6). The sentence about blocks removing cards is left for phase 3, which adds that behaviour.
- **Imports.** `resolveInstanceDomain`, `resolveVideoId` and `resolveVideoKey` now come from `../../components/video-card` (the import became a multi-line list, as the file already does for `data/search`), and `sendReaction` from `../../data/reactions`. `getProfileKey` and `blockVideoSource` are not imported yet; phases 3 and 4 need them.
- **`state.rows`.** A new field, `rows: [] as VideoRow[]`, holds the rendered rows in order so a card action can find its row by video key. It is cleared in `loadPage`'s `if (reset)` block, which covers a new search, a sort change, popstate, the first load and the key-rejected retry. It is also cleared in `showIdle`.
- **`renderRows`.** It now maps through the new `renderSearchCard` on both the reset path and the append path, and adds the page's rows to `state.rows`. It still runs only after the `seq` check, so a stale response adds no rows.
- **`renderSearchCard(row)`.** New. It returns `renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true })`. The first render and every in-place re-render use it, so they cannot drift apart.
- **Click handler.** One click listener on `#search-results`, copied from home's: from the clicked element up to the `[data-card-action]` button, then the `.video-card`, then `dataset.videoKey`, then `state.rows.find` by `resolveVideoKey`. If any step finds nothing, the click does nothing.
- **`runCardAction(button, card, row)`.** New, modelled on home's. It disables the button and clears the card's status line.
  - **Like** sends `undo_like` if `cardReaction(row) === "liked"`, otherwise `like`.
  - **Dislike** sends `undo_dislike` if `cardReaction(row) === "disliked"`, otherwise `dislike`.
  - Either way it then sets `row.reaction`, and replaces `card.outerHTML` with `renderSearchCard(row)` only if `card.isConnected`. Setting `outerHTML` on a card that a reset has detached would throw.
  - A thrown error goes to the card's status line (fallback `"Action failed"`), and `finally` re-enables the button.
  - There is no branch yet for `channel` and `account`, so clicking those buttons sends nothing until phase 3. The no-key guard comes in phase 4.

**Not run:** I have not run the checkpoint; the workflow runs it on hand-in. What I did run was a type check: `tsc --noEmit` in `client/frontend` reports no error in `src/pages/search/index.ts`. Its only errors are in three files already broken before this build (`channels`, `video-page`, `videos`).

**Leftover file:** that type check was a throwaway probe, `tests/tmp/test_probe_40_p2_impl.py`. My tools cannot delete files, so it is still there and can be deleted.

**Beyond the files named.** none. The phase also lists `tests/tmp/test_frontend_search_card_actions.py (EDITED)`, but that file does not exist. The checkpoint gating this phase is `tests/tmp/test_40_search_card_actions_phase2.py` (phase 1 had the same mismatch), so I did not create it.

#### Phase 3 - Block removes the source's loaded cards [code]

**Files touched.** client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED)

**Checkpoint.** Seam: the same search page bundle and fake DOM as phase 2, driven by clicks on the `[data-card-action="channel"]` and `[data-card-action="account"]` buttons. Assertions:
(a) With a key, Block channel sends `POST /api/profile/blocks` and then a `dislike` reaction, in that order. Every loaded card whose row shares `instance_domain`+`channel_id` is removed from `#search-results`, including cards on page 2. With the sentinel in view, the next page is fetched, which shows that `fillViewport` ran. `#search-status` text is unchanged. Block account does the same, matching on `account_url`.
(b) When the follow-up `dislike` returns 500, the clicked card's `.card-action-status` reads `Blocked <label>, but the dislike failed: <msg>` and no card is removed.

**Intent.** In `pages/search/index.ts`, blocking a channel or account from a search card removes every loaded card of that source, unless the dislike that follows the block fails.

- C1 - A successful block followed by a successful dislike removes every loaded card of that channel or account, refills the viewport and leaves the status text unchanged.
- C2 - A block whose dislike fails reports `Blocked <label|action>, but the dislike failed: <msg>` and removes no card.

**Outcome.** ### `client/frontend/src/pages/search/index.ts`
- Imports `blockVideoSource` from `../../data/blocks`.
- `runCardAction` now handles the `channel` and `account` actions, the same way the home feed (`pages/videos/index.ts`) does. It calls `blockVideoSource(apiBase, action, uuid, host)` and then sends a `dislike` for the video.
  - **Dislike fails:** the card's `.card-action-status` reads `Blocked <block.label || action>, but the dislike failed: <message>`, and the handler returns without touching the grid (C2).
  - **Dislike succeeds:** a channel block matches rows on `instance_domain` + `channel_id`, and an account block matches on `account_url`. The matching rows go through `removeRows` (C1).
  - **Block request fails:** the existing catch shows its error on the card.
- New `removeRows(match)`:
  - It filters `state.rows`, redraws the grid from the rows that are left, and calls `fillViewport()` to fetch the next page if the end of the results is now on screen.
  - The redraw is done from `state.rows` rather than by deleting nodes, because keyless cards have no `data-video-key` but still have to go when their source matches.
  - `state.loadedRows` is deliberately left alone, so `Showing N of M` and the `hasMore` paging check keep counting what the Engine returned.
- Updated the doc comment on `runCardAction` to cover blocking.

### `tests/tmp/test_frontend_search_card_actions.py`
Not touched. This file is on the phase's files list but doesn't exist in the worktree. No change in this phase needed it.

#### Phase 4 - No-key guard, failures and dist rebuild [code]

**Files touched.** client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED), client/frontend/dist/ (REBUILT)

**Checkpoint.** Seam: the same search page bundle and fake DOM as phase 2. Assertions:
(a) With no profile key, clicking Dislike, Block channel and Block account each writes home's exact "Disliking/Blocking needs a profile. Create one from the Profile button." text into the card's `.card-action-status`, and the stub fetch records no request.
(b) With a key, a Dislike that gets a 400 with "Dislike limit reached" puts that message in the status line. The button is enabled again (`disabled` is false), and the card keeps its previous mark, so a second click still sends `dislike`, not `undo_dislike`.
Then `npx tsc --noEmit` and `npm run build` run in `client/frontend`. `tests/active/test_frontend_reactions.py`, `test_frontend_blocks.py` and `test_frontend_videos_page.py` stay green unchanged, and the new test is promoted to `tests/active/`.

**Intent.** In `pages/search/index.ts`, a card action that cannot or does not succeed leaves the card's reaction as it was and explains why in that card's status line.

- C1 - Without a profile key, Dislike, Block channel and Block account each write home's exact profile prompt and send no request.
- C2 - A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged.

**Outcome.** ### client/frontend/src/pages/search/index.ts
- `runCardAction` now starts with home's no-key guard, word for word. If there is no profile key, Dislike, Block channel and Block account write `Disliking needs a profile. Create one from the Profile button.` or `Blocking needs a profile. Create one from the Profile button.` into the card's `.card-action-status`. They then return before the button is disabled and before any request is sent. Like is not guarded, as on home.
- `getProfileKey` is now imported next to `ProfileKeyRejectedError` from `../../data/profile`.
- C2 needed no new code. The existing order already covers it: send the request, set `row.reaction` and redraw only after it resolves, show `error.message` in the `catch`, and set `button.disabled = false` in the `finally`. A rejected request leaves the row's reaction alone. A block that fails never reaches `removeRows`, so the card stays on the grid.

### client/frontend/dist/
Not rebuilt in this turn because I have no shell. The operator chose to rebuild it by hand with `cd client/frontend && npm run build`. The checkpoint bundles from `src` and never reads `dist`, so it does not wait on the rebuild. Until the rebuild is done, the served `dist/assets/search-*.js` lacks this guard and the phase-3 card actions.

### tests/tmp/test_frontend_search_card_actions.py
Not touched. It does not exist in the worktree, and the phase-4 checkpoint covers both clauses.


