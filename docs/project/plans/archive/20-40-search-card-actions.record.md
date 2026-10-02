# Build record - 40-search-card-actions

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/20-40-search-card-actions.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Like, dislike and block controls on search result cards\n\nStatus: enhancement, ready-for-agent\nOrigin: operator report: \"blocks and likes and such do not work on the video cards in search\"\n\n## Problem\n\nThe home feed's video cards carry Like, Dislike, Block channel and Block account buttons. The search page's cards carry none of them, so a visitor cannot like, dislike or block from a search result and has to open the video page first.\n\nBoth pages render cards through the shared `renderVideoCard`, which draws the buttons only when its caller passes `actions: true`. The home feed passes it and handles the buttons' `data-card-action` clicks itself (`runCardAction` in the feed page). The search page passes only `apiParam` and `reaction`, and has no click handler, so the buttons are never drawn. The built bundle matches the source.\n\nThis is the search-grid half of roadmap item F13-M2 (\"Block controls on video cards (feed and search grids) and on the channels page\"). The feed grid half is already in the tree.\n\n## Comments\n\n**Triage (operator decisions):**\n\n- A dislike from a search card keeps the card and marks it disliked. Search stays unfiltered by dislikes (plan 08, D6), so the page shows what a rerun of the same search would show.\n- Dislike on a search card toggles, as Like does: pressing it on a disliked card sends `undo_dislike`.\n- A block from a search card behaves as it does on home: block, dislike the clicked video, and remove every loaded card of that channel or account.\n- Only the four controls home cards have. Follow on cards is not part of this issue.\n\n## Agent Brief\n\n**Category:** enhancement\n**Summary:** Give search result cards the same Like, Dislike, Block channel and Block account controls as home feed cards\n\n**Current behavior:**\nThe shared card renderer `renderVideoCard(row, options)` draws a row of action buttons (`data-card-action` = `like`, `dislike`, `channel`, `account`, plus a `.card-action-status` line) only when `options.actions` is true. The home feed page sets it, and a delegated click handler on its grid runs each action through `sendReaction` and `blockVideoSource`. The search page renders cards with `apiParam` and `reaction` only and has no click handler, so search cards have no action buttons.\n\nSearch rows from a keyed request already arrive marked with `reaction` (`\"liked\"` or `\"disliked\"`). The Client's read proxy removes blocked channels and accounts from search, and deliberately never removes disliked videos (D6).\n\n**Desired behavior:**\nEvery search result card shows the four controls home cards show, and they act as follows:\n\n- **Like**: toggles exactly as on home. Like sends `like`; on a liked card it sends `undo_like`. A like on a disliked card replaces the dislike. The card re-renders in its new state and stays on the page.\n- **Dislike**: needs a profile. It sends `dislike` and the card **stays**, re-rendered with the disliked mark, and the Dislike button reads pressed (`aria-pressed=\"true\"`). Pressing it on a disliked card sends `undo_dislike` and the card returns to neutral. A dislike on a liked card replaces the like.\n- **Block channel / Block account**: needs a profile. Same as home: block the clicked video's channel or account, then dislike the clicked video, then remove every currently loaded search card from that channel (`instance_domain` + `channel_id`) or account (`account_url`). If the block succeeds and the dislike fails, say so in the card's status line, as home does.\n- **Without a profile key**: Dislike and Block show the same \"needs a profile\" prompt in the card's status line that home shows. Like works without a key the way it does on home.\n- **Errors**: a failed action shows its message in that card's status line, and the button is re-enabled. A rejected key is handled as the search page already handles `ProfileKeyRejectedError`.\n- Paging continues normally after any action. Cards appended by later pages get the controls too.\n\nIf the home feed shares the same dislike-button markup, giving it `aria-pressed` for a disliked card is fine, but home's dislike behaviour (remove the card, no undo) must not change.\n\n**Key interfaces:**\n- `VideoCardOptions.actions` on `renderVideoCard`: the search page passes `true`.\n- The Dislike button in the card's action markup: it needs a pressed state for a disliked card, the way the Like button already has one for a liked card.\n- `sendReaction(apiBase, action, { uuid, host })` with actions `like`, `undo_like`, `dislike`, `undo_dislike`; `blockVideoSource(apiBase, kind, uuid, host)` returning the block's `kind`, `instance_domain`/`channel_id` or `account_url`, and `label`; `cardReaction(row)` for the current mark.\n- Home's card-action handling, which may be shared with search or mirrored. A shared helper must leave home's behaviour unchanged.\n\n**Acceptance criteria:**\n- [ ] A search results page renders Like, Dislike, Block channel and Block account buttons on every card that has a video key, including cards loaded by later pages.\n- [ ] With a profile key, Dislike on a search card sends `dislike`, and the card stays on the page with the disliked mark and a pressed Dislike button. Rerunning the same search shows that video still present and marked disliked.\n- [ ] Dislike on a disliked search card sends `undo_dislike`. The card shows no mark, and a rerun of the search carries no `reaction` on that row.\n- [ ] Like on a search card toggles between `like` and `undo_like`, and a like on a disliked card leaves it marked liked, not disliked.\n- [ ] Block channel on a search card removes every loaded card of that channel, and the video is disliked. A rerun of the same search contains no row from that channel. Block account does the same by `account_url`.\n- [ ] Without a profile key, Dislike and the two Block buttons show the profile prompt in the card's status line and send no request.\n- [ ] Home feed card behaviour is unchanged: dislike and block still remove cards, and home has no undo-dislike.\n- [ ] `dist/` is rebuilt (`npm run build`) so the served bundle carries the change.\n\n**Out of scope:**\n- Filtering search results by dislikes (D6 stands).\n- Follow controls on any card.\n- Action controls on the video page's similar/up-next cards, the likes page or the channels page.\n- Changing home feed card behaviour, beyond an optional pressed state on its Dislike button.\n- Any Client backend or Engine change. The routes and filtering this needs already exist.",
  "request_source": "read from docs/project/issues/40-search-card-actions.md",
  "slug": "40-search-card-actions",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Dislike pressed state in the shared card",
      "checkpoint": "Seam: `renderVideoCard` in `client/frontend/src/components/video-card.ts`, called directly from a small esbuild bundle that re-exports it. This follows the precedent in `tests/active/test_frontend_reactions.py` (line 112 re-exports `renderVideoCard` from the component and asserts on the returned markup). The test lives in `tests/tmp/test_frontend_search_card_actions.py` and renders a keyed row with `{ actions: true, reaction: \"disliked\" }`, `{ actions: true, reaction: null }` (home's case) and `{ actions: true, reaction: \"liked\" }`. On the `[data-card-action=\"dislike\"]` button it asserts `aria-pressed=\"true\"` for the first and `aria-pressed=\"false\"` for the other two. `npx tsc --noEmit` passes in `client/frontend`.",
      "intent": "`renderVideoCard` in `components/video-card.ts` now reports the Dislike button's pressed state from `options.reaction`, the same way it already does for Like.",
      "clauses": [
        {
          "id": "C1",
          "text": "The Dislike button has `aria-pressed=\"true\"` when `options.reaction` is `\"disliked\"`, and `aria-pressed=\"false\"` otherwise."
        }
      ],
      "files": [
        "client/frontend/src/components/video-card.ts (EDITED)",
        "tests/tmp/test_frontend_search_card_actions.py (NEW)"
      ],
      "done": true,
      "outcome": "### client/frontend/src/components/video-card.ts\nIn `renderVideoCard`, the Dislike action button (`data-card-action=\"dislike\"`) now has `aria-pressed=\"${reaction === \"disliked\"}\"`, which follows how the Like button already does it. It renders `\"true\"` when `options.reaction` is `\"disliked\"` and `\"false\"` in every other case: `null`, `\"liked\"`, or the option left out. `reaction` already falls back to `null`, so the attribute is always present. No other markup changed.",
      "beyond": "none. One note: the phase's file list names `tests/tmp/test_frontend_search_card_actions.py (NEW)`, but the gating checkpoint is `tests/tmp/test_40_search_card_actions_phase1.py`, and that already exists. I did not create the listed file because the checkpoint covers this phase. If the build expects that path to exist, it is still missing."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Search card controls and Like/Dislike toggles",
      "checkpoint": "Seam: the search page entry, `client/frontend/src/pages/search/index.ts`. It is bundled with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`) and run under node with a stub `fetch` that records method, path and body, plus an `IntersectionObserver` stub. This follows `tests/active/test_frontend_videos_page.py`. That harness's fake DOM stubs `closest` to return null, so this phase builds a richer fake DOM in the new test file, and phases 3 and 4 reuse it. The new DOM supports `closest`, `dataset`, `children`, `remove`, an `outerHTML` setter that re-parses into a new node, and `isConnected`. Assertions, all made through the DOM and the recorded fetches:\n(a) After page 1 and an appended page 2, every keyed `.video-card` under `#search-results` has four `[data-card-action]` buttons, and a keyless row's card has none.\n(b) With a key, clicking Dislike sends `dislike`, and the card re-renders with `stat dislikes active` and `aria-pressed=\"true\"`. A second click sends `undo_dislike` and the mark clears. Like on a disliked card sends `like` and the card shows liked, not disliked. A second Like sends `undo_like`. Without a key, Like sends `like` and the like is stored in `localLikes:v1`.\n(c) If a new search resolves while a Like is in flight, nothing throws, and the grid and `state.rows` (observed through a following click) hold only the new search's rows.",
      "intent": "In `pages/search/index.ts`, keyed search cards on every loaded page carry the card actions, and a Like or Dislike click on one toggles that reaction through the reactions API and re-renders the card in place.",
      "clauses": [
        {
          "id": "C1",
          "text": "Every keyed card on the first page and on an appended page has the four `[data-card-action]` controls, and a keyless card has none."
        },
        {
          "id": "C2",
          "text": "A Like or Dislike click sends the toggled reaction and re-renders that card in place with the new mark, without throwing when a reset replaced the grid mid-request."
        }
      ],
      "files": [
        "client/frontend/src/pages/search/index.ts (EDITED)",
        "tests/tmp/test_frontend_search_card_actions.py (EDITED)"
      ],
      "done": true,
      "outcome": "### client/frontend/src/pages/search/index.ts\n- **Docstring.** One paragraph added: each card carries Like, Dislike, Block channel and Block account, and unlike home, Dislike toggles and the card stays marked, because search is not filtered by dislikes (D6). The sentence about blocks removing cards is left for phase 3, which adds that behaviour.\n- **Imports.** `resolveInstanceDomain`, `resolveVideoId` and `resolveVideoKey` now come from `../../components/video-card` (the import became a multi-line list, as the file already does for `data/search`), and `sendReaction` from `../../data/reactions`. `getProfileKey` and `blockVideoSource` are not imported yet; phases 3 and 4 need them.\n- **`state.rows`.** A new field, `rows: [] as VideoRow[]`, holds the rendered rows in order so a card action can find its row by video key. It is cleared in `loadPage`'s `if (reset)` block, which covers a new search, a sort change, popstate, the first load and the key-rejected retry. It is also cleared in `showIdle`.\n- **`renderRows`.** It now maps through the new `renderSearchCard` on both the reset path and the append path, and adds the page's rows to `state.rows`. It still runs only after the `seq` check, so a stale response adds no rows.\n- **`renderSearchCard(row)`.** New. It returns `renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true })`. The first render and every in-place re-render use it, so they cannot drift apart.\n- **Click handler.** One click listener on `#search-results`, copied from home's: from the clicked element up to the `[data-card-action]` button, then the `.video-card`, then `dataset.videoKey`, then `state.rows.find` by `resolveVideoKey`. If any step finds nothing, the click does nothing.\n- **`runCardAction(button, card, row)`.** New, modelled on home's. It disables the button and clears the card's status line.\n  - **Like** sends `undo_like` if `cardReaction(row) === \"liked\"`, otherwise `like`.\n  - **Dislike** sends `undo_dislike` if `cardReaction(row) === \"disliked\"`, otherwise `dislike`.\n  - Either way it then sets `row.reaction`, and replaces `card.outerHTML` with `renderSearchCard(row)` only if `card.isConnected`. Setting `outerHTML` on a card that a reset has detached would throw.\n  - A thrown error goes to the card's status line (fallback `\"Action failed\"`), and `finally` re-enables the button.\n  - There is no branch yet for `channel` and `account`, so clicking those buttons sends nothing until phase 3. The no-key guard comes in phase 4.\n\n**Not run:** I have not run the checkpoint; the workflow runs it on hand-in. What I did run was a type check: `tsc --noEmit` in `client/frontend` reports no error in `src/pages/search/index.ts`. Its only errors are in three files already broken before this build (`channels`, `video-page`, `videos`).\n\n**Leftover file:** that type check was a throwaway probe, `tests/tmp/test_probe_40_p2_impl.py`. My tools cannot delete files, so it is still there and can be deleted.",
      "beyond": "none. The phase also lists `tests/tmp/test_frontend_search_card_actions.py (EDITED)`, but that file does not exist. The checkpoint gating this phase is `tests/tmp/test_40_search_card_actions_phase2.py` (phase 1 had the same mismatch), so I did not create it."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Block removes the source's loaded cards",
      "checkpoint": "Seam: the same search page bundle and fake DOM as phase 2, driven by clicks on the `[data-card-action=\"channel\"]` and `[data-card-action=\"account\"]` buttons. Assertions:\n(a) With a key, Block channel sends `POST /api/profile/blocks` and then a `dislike` reaction, in that order. Every loaded card whose row shares `instance_domain`+`channel_id` is removed from `#search-results`, including cards on page 2. With the sentinel in view, the next page is fetched, which shows that `fillViewport` ran. `#search-status` text is unchanged. Block account does the same, matching on `account_url`.\n(b) When the follow-up `dislike` returns 500, the clicked card's `.card-action-status` reads `Blocked <label>, but the dislike failed: <msg>` and no card is removed.",
      "intent": "In `pages/search/index.ts`, blocking a channel or account from a search card removes every loaded card of that source, unless the dislike that follows the block fails.",
      "clauses": [
        {
          "id": "C1",
          "text": "A successful block followed by a successful dislike removes every loaded card of that channel or account, refills the viewport and leaves the status text unchanged."
        },
        {
          "id": "C2",
          "text": "A block whose dislike fails reports `Blocked <label|action>, but the dislike failed: <msg>` and removes no card."
        }
      ],
      "files": [
        "client/frontend/src/pages/search/index.ts (EDITED)",
        "tests/tmp/test_frontend_search_card_actions.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `client/frontend/src/pages/search/index.ts`\n- Imports `blockVideoSource` from `../../data/blocks`.\n- `runCardAction` now handles the `channel` and `account` actions, the same way the home feed (`pages/videos/index.ts`) does. It calls `blockVideoSource(apiBase, action, uuid, host)` and then sends a `dislike` for the video.\n  - **Dislike fails:** the card's `.card-action-status` reads `Blocked <block.label || action>, but the dislike failed: <message>`, and the handler returns without touching the grid (C2).\n  - **Dislike succeeds:** a channel block matches rows on `instance_domain` + `channel_id`, and an account block matches on `account_url`. The matching rows go through `removeRows` (C1).\n  - **Block request fails:** the existing catch shows its error on the card.\n- New `removeRows(match)`:\n  - It filters `state.rows`, redraws the grid from the rows that are left, and calls `fillViewport()` to fetch the next page if the end of the results is now on screen.\n  - The redraw is done from `state.rows` rather than by deleting nodes, because keyless cards have no `data-video-key` but still have to go when their source matches.\n  - `state.loadedRows` is deliberately left alone, so `Showing N of M` and the `hasMore` paging check keep counting what the Engine returned.\n- Updated the doc comment on `runCardAction` to cover blocking.\n\n### `tests/tmp/test_frontend_search_card_actions.py`\nNot touched. This file is on the phase's files list but doesn't exist in the worktree. No change in this phase needed it."
    },
    {
      "n": "4",
      "kind": "code",
      "name": "No-key guard, failures and dist rebuild",
      "checkpoint": "Seam: the same search page bundle and fake DOM as phase 2. Assertions:\n(a) With no profile key, clicking Dislike, Block channel and Block account each writes home's exact \"Disliking/Blocking needs a profile. Create one from the Profile button.\" text into the card's `.card-action-status`, and the stub fetch records no request.\n(b) With a key, a Dislike that gets a 400 with \"Dislike limit reached\" puts that message in the status line. The button is enabled again (`disabled` is false), and the card keeps its previous mark, so a second click still sends `dislike`, not `undo_dislike`.\nThen `npx tsc --noEmit` and `npm run build` run in `client/frontend`. `tests/active/test_frontend_reactions.py`, `test_frontend_blocks.py` and `test_frontend_videos_page.py` stay green unchanged, and the new test is promoted to `tests/active/`.",
      "intent": "In `pages/search/index.ts`, a card action that cannot or does not succeed leaves the card's reaction as it was and explains why in that card's status line.",
      "clauses": [
        {
          "id": "C1",
          "text": "Without a profile key, Dislike, Block channel and Block account each write home's exact profile prompt and send no request."
        },
        {
          "id": "C2",
          "text": "A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged."
        }
      ],
      "files": [
        "client/frontend/src/pages/search/index.ts (EDITED)",
        "tests/tmp/test_frontend_search_card_actions.py (EDITED)",
        "client/frontend/dist/ (REBUILT)"
      ],
      "done": true,
      "outcome": "### client/frontend/src/pages/search/index.ts\n- `runCardAction` now starts with home's no-key guard, word for word. If there is no profile key, Dislike, Block channel and Block account write `Disliking needs a profile. Create one from the Profile button.` or `Blocking needs a profile. Create one from the Profile button.` into the card's `.card-action-status`. They then return before the button is disabled and before any request is sent. Like is not guarded, as on home.\n- `getProfileKey` is now imported next to `ProfileKeyRejectedError` from `../../data/profile`.\n- C2 needed no new code. The existing order already covers it: send the request, set `row.reaction` and redraw only after it resolves, show `error.message` in the `catch`, and set `button.disabled = false` in the `finally`. A rejected request leaves the row's reaction alone. A block that fails never reaches `removeRows`, so the card stays on the grid.\n\n### client/frontend/dist/\nNot rebuilt in this turn because I have no shell. The operator chose to rebuild it by hand with `cd client/frontend && npm run build`. The checkpoint bundles from `src` and never reads `dist`, so it does not wait on the rebuild. Until the rebuild is done, the served `dist/assets/search-*.js` lacks this guard and the phase-3 card actions.\n\n### tests/tmp/test_frontend_search_card_actions.py\nNot touched. It does not exist in the worktree, and the phase-4 checkpoint covers both clauses."
    }
  ],
  "digests": {
    "tests/tmp/test_40_search_card_actions_phase1.py": "2cc9e3d0447480811de0519d482135ead88f5fbb7001fce8dbf27c248e3aabd9",
    "tests/tmp/test_40_search_card_actions_phase2.py": "a812e1a4f880300d14c7a92b4da1fdfe59bc4436ce649196b3137afc3d240e17",
    "tests/tmp/test_40_search_card_actions_phase3.py": "3fd0f8c04ec9a53f7ff3f6bcec47a6f2d56f685aacebd1e256603d2b661e3f2c",
    "tests/tmp/test_40_search_card_actions_phase4.py": "16694de9e3ec9eb1e9709c965ef665ae1868ff329d7526c7a71e6c8d526bba4b"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/40",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261001T175912-5834-dev-flow"
  ],
  "plan": "docs/project/plans/20-40-search-card-actions.md",
  "record": "docs/project/plans/20-40-search-card-actions.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nAn operator reported: \"blocks and likes and such do not work on the video cards in search\". Home feed cards have Like, Dislike, Block channel and Block account controls. Search result cards have none, so a visitor has to open the video page to react to or block a search result. This build gives search cards the same four controls and finishes the search-grid half of roadmap item F13-M2 (\"Block controls on video cards (feed and search grids) and on the channels page\"). The feed-grid half is already in the tree. The issue is `docs/project/issues/40-search-card-actions.md`.\n\n### Current state (verified in the tree)\n\n- `client/frontend/src/components/video-card.ts`: `renderVideoCard(row, options)` draws `.card-actions` only when `options.actions` is true and the row has a video key (`resolveVideoKey` = `host::id`). The block holds buttons with `data-card-action` = `like`, `dislike`, `channel`, `account` and a `<span class=\"card-action-status\" role=\"status\">`. The Like button has `aria-pressed=\"${reaction === \"liked\"}\"`. The Dislike button has no `aria-pressed`. The card root is `<article class=\"video-card [liked|disliked]\" data-video-key=\"...\">`, and the disliked mark is the `stat dislikes active` class plus a visually-hidden \"You disliked this\".\n- `client/frontend/src/pages/search/index.ts`: `renderRows` calls `renderVideoCard(row, { apiParam, reaction: cardReaction(row) })` with no `actions` and keeps no array of loaded rows. `#search-results` has no click handler. Paging is page-numbered (`state.page`, `PAGE_SIZE = 24`). `state.loadedRows` counts fetched rows, and both `hasMore` and the \"Showing N of M matched videos.\" status use it. `fillViewport()` fetches more while the sentinel is in view. `ProfileKeyRejectedError` from `fetchSearchResults` replaces the grid with `keyRejectedNotice`.\n- `client/frontend/src/pages/videos/index.ts` (home): a delegated click handler on `#video-cards` finds the row in `state.sample` by `data-video-key` and calls `runCardAction(button, card, row)`. That function shows `\"<Disliking|Blocking> needs a profile. Create one from the Profile button.\"` when a non-like action has no key. It disables the button while running and clears the status line. Like sends `undo_like` or `like` depending on `cardReaction(row) === \"liked\"`, sets `row.reaction`, and replaces `card.outerHTML`. Dislike sends `dislike` and removes the row. Block calls `blockVideoSource`, then `sendReaction(\"dislike\")`. If the dislike fails it says `Blocked <label|action>, but the dislike failed: <message>` and removes nothing; otherwise it removes rows matching `instance_domain`+`channel_id` (channel) or `account_url` (account). Any error goes to the status line, and the button is re-enabled in `finally`.\n- `client/frontend/src/data/reactions.ts`: `sendReaction(apiBase, action, { uuid, host })` supports `like`, `undo_like`, `dislike`, `undo_dislike`, and without a key records local likes and un-likes. `cardReaction(row)` returns `row.reaction` with a key, and the local-like state without one.\n- `client/frontend/src/data/blocks.ts`: `blockVideoSource(apiBase, kind, uuid, host)` returns a `Block` with `kind`, `instance_domain`, `channel_id`, `account_url` and `label`.\n- `sendUserAction` and the blocks `request` throw a plain `Error` on any non-OK status, 401 included. Neither throws `ProfileKeyRejectedError`.\n- Client backend `_filter_payload` (`client/backend/server.py`) filters blocked rows out of each Engine page after the Engine has paged and marks `reaction`. Search is never filtered by dislikes (plan 08, D6). Because filtering happens per page, a block never shifts later page numbers.\n\n### Functional requirements\n\n1. **Controls rendered.** The search page passes `actions: true` to `renderVideoCard` for every row, on the first page and on every appended page. Every search card with a video key shows Like, Dislike, Block channel, Block account and the `.card-action-status` line. A card without a video key shows none, as on home.\n2. **Row lookup.** The search page keeps the rows it has rendered, in order, in page state. A reset (new search, sort change, popstate, retry after key rejection, idle) clears them. One delegated click listener on `#search-results` resolves `[data-card-action]` \u2192 closest `.video-card` \u2192 `data-video-key` \u2192 the stored row, matching by `resolveVideoKey`, the way home does. A click that resolves no row does nothing.\n3. **Like.** It works with or without a profile key. If `cardReaction(row) === \"liked\"` it sends `undo_like` and the row's reaction becomes `null`. Otherwise it sends `like` and the reaction becomes `\"liked\"`, which also covers a disliked card: the like replaces the dislike. The card is re-rendered in place through the same `renderVideoCard` options search uses (`apiParam`, `reaction: cardReaction(row)`, `actions: true`) and stays on the page.\n4. **Dislike (search only: toggle, card stays).** It needs a profile key. If `cardReaction(row) === \"disliked\"` it sends `undo_dislike` and the reaction becomes `null`. Otherwise it sends `dislike` and the reaction becomes `\"disliked\"`, which also covers a liked card: the dislike replaces the like. The card is re-rendered in place and stays. A disliked card shows the disliked mark and its Dislike button has `aria-pressed=\"true\"`. A neutral or liked card's Dislike button has `aria-pressed=\"false\"`.\n5. **Block channel / Block account.** It needs a profile key and matches home. Call `blockVideoSource(apiBase, \"channel\"|\"account\", uuid, host)`, then `sendReaction(apiBase, \"dislike\", { uuid, host })`. If the dislike fails, the status line reads `Blocked <block.label || action>, but the dislike failed: <message>` and no cards are removed. Otherwise every loaded search row and card is removed where `instance_domain` + `channel_id` equal the block's (channel), or where `account_url` equals the block's (account).\n6. **No profile key.** Dislike, Block channel and Block account write the same text home writes, `\"Disliking needs a profile. Create one from the Profile button.\"` or `\"Blocking needs a profile. Create one from the Profile button.\"`, into that card's status line and send no request.\n7. **Errors.** The button is disabled while its action runs and re-enabled afterwards, whether the action succeeded or failed. A failed request writes its `Error.message` (fallback `\"Action failed\"`) into that card's status line. **Operator decision:** a rejected profile key during a card action goes the same way, as a status-line message like home's. It does not replace the grid with `keyRejectedNotice`, and the data layer (`user-actions.ts`, `blocks.ts`, `reactions.ts`) is not changed to throw `ProfileKeyRejectedError`. The search page's existing `ProfileKeyRejectedError` handling for search reads is unchanged.\n8. **Paging after actions.** Infinite scroll keeps working after any action, and cards appended by later pages carry the controls and are clickable. `state.page`, `state.loadedRows`, `hasMore` and the \"Showing N of M matched videos.\" status keep counting fetched rows, not rows still on screen. **Deliberate simplification:** after a block the count may overstate what is visible. Paging is still correct because the Client filters per Engine page, so page numbers do not shift. The upgrade path, if wanted later, is a separate visible-count. After a block removes cards, the page calls `fillViewport()` so a grid that became too short fetches the next page.\n9. **Shared markup change.** The Dislike button in `renderVideoCard`'s action markup gets `aria-pressed=\"${reaction === \"disliked\"}\"`, mirroring Like. That is the only change to the shared component's output.\n10. **Home unchanged.** Home's dislike still removes the card and has no undo. Home's block still removes the matching cards. Home's like, no-key prompt and error handling stay as they are. Any helper shared between the two pages must keep that behaviour exactly. Mirroring home's handler inside the search page is acceptable, and so is extracting a shared helper, provided home's behaviour is unchanged.\n11. **Build.** `dist/` is rebuilt with `npm run build` in `client/frontend` so the served bundle carries the change.\n\n### Acceptance criteria\n\n- A search results page renders Like, Dislike, Block channel and Block account buttons on every card that has a video key, including cards loaded by later pages.\n- With a profile key, Dislike on a search card sends `dislike`. The card stays on the page with the disliked mark and a Dislike button with `aria-pressed=\"true\"`. Rerunning the same search shows the video still present with `reaction: \"disliked\"`.\n- Dislike on a disliked search card sends `undo_dislike`. The card shows no mark, and a rerun of the search carries no `reaction` on that row.\n- Like on a search card toggles between `like` and `undo_like`. A like on a disliked card leaves it marked liked, not disliked.\n- Block channel on a search card removes every loaded card of that channel, and the video is disliked. A rerun of the same search contains no row from that channel. Block account does the same by `account_url`.\n- Without a profile key, Dislike and the two Block buttons show the profile prompt in the card's status line and send no request.\n- A failed action shows its message in that card's status line and the button is re-enabled.\n- Home feed card behaviour is unchanged: dislike and block still remove cards, and home has no undo-dislike.\n- `dist/` is rebuilt (`npm run build`) so the served bundle carries the change.\n\n### Out of scope\n\n- Filtering search results by dislikes (D6 stands).\n- Follow controls on any card.\n- Action controls on the video page's similar/up-next cards, the likes page or the channels page.\n- Changing home feed card behaviour, beyond the pressed state on its Dislike button.\n- Any Client backend or Engine change, or any change to the frontend data layer's error types.\n\n### Baseline suite state\n\nThe pre-build suite exited 0 (variant: false): 1 of 46 test groups selected (`test_search_fusion.py`, 10 passed). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`. The existing frontend tests touching this area are `tests/active/test_frontend_blocks.py` and `tests/active/test_frontend_reactions.py`.\n</requirements>\n\n<conflicts>\nThe brief says \"A rejected key is handled as the search page already handles ProfileKeyRejectedError\", but in the tree `sendUserAction` (user-actions.ts) and blocks.ts `request` throw a plain Error on 401, never ProfileKeyRejectedError, and home's runCardAction shows that message in the card status line. The operator resolved this: card actions show the rejected-key error in the card's status line, as home does, and the data layer is unchanged.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe change touches two source files and then a rebuild. `pages/search/index.ts` gets its own card-action handler, written to match home's. `components/video-card.ts` gets one attribute.\n\nI read the tree to confirm the premises. Search rows from `engine/server/data/search.py` carry `channel_id` and `account_url`, so block matching can use the same fields home uses. `sendReaction`, `blockVideoSource` and `sendUserAction` all pass their `apiBase` argument through `resolveClientApiBase`, so search can pass `apiParam ?? \"\"`, the same way it already calls `importLocalLikes`. `videos.css`, where `.card-actions` is styled, is already imported by the search page, so no CSS work is needed.\n\n1. **Controls rendered (req 1).** One small search-page function renders a row with `apiParam`, `reaction: cardReaction(row)` and `actions: true`. It is search's version of home's `renderFeedCard`. `renderRows` uses it for both the first page and appended pages, so every keyed card gets the controls and keyless cards still get none.\n2. **Row lookup (req 2).** Page state gains a `rows` array. `renderRows` appends each page's rows to it in order. Every reset path empties it: `loadPage(..., reset=true)` covers new search, sort change, popstate and the retry from `keyRejectedNotice`, and `showIdle` covers idle. One delegated `click` listener on `#search-results` does what home's listener on `#video-cards` does: `closest(\"[data-card-action]\")`, then `closest(\".video-card\")`, then `dataset.videoKey`, then `state.rows.find` by `resolveVideoKey`. If any step finds nothing, the click does nothing. Because the listener sits on the container, cards appended by later pages are clickable without extra wiring (req 8).\n3. **Action runner (reqs 3\u20137).** A search-page `runCardAction(button, card, row)` takes uuid and host from `resolveVideoId` and `resolveInstanceDomain`, as home does.\n   - **No key (req 6):** if the action is not `like` and `getProfileKey()` is empty, it writes home's exact \"Disliking/Blocking needs a profile. Create one from the Profile button.\" text into the card's status line and returns without a request.\n   - **Running:** it disables the button and clears the status line.\n   - **Like (req 3):** sends `undo_like` if `cardReaction(row) === \"liked\"`, otherwise `like`. It sets `row.reaction` to `null` or `\"liked\"` and replaces `card.outerHTML` with the search render. With no key, `sendReaction` has already updated the local likes, so `cardReaction` reads them correctly. With a key, the server's rule that a like and a dislike replace each other makes `\"liked\"` right for a card that was disliked.\n   - **Dislike (req 4):** sends `undo_dislike` if `cardReaction(row) === \"disliked\"`, otherwise `dislike`. It sets `row.reaction` to `null` or `\"disliked\"` and re-renders the card in place.\n   - **Block (req 5):** calls `blockVideoSource`, then `sendReaction(\"dislike\")` with the same promise-to-message handling home uses. If the dislike failed, the status line reads `Blocked <label|action>, but the dislike failed: <msg>` and nothing is removed.\n   - **Errors (req 7):** any thrown error writes `error.message`, or \"Action failed\", into the status line. A `finally` re-enables the button. No `ProfileKeyRejectedError` path is added, which is the operator's decision.\n4. **Removal after a block (reqs 5, 8).** A search-page `removeRows(match)` filters `state.rows`. It removes from the grid each child `.video-card` whose `dataset.videoKey` belongs to a removed row; it walks the children and compares the dataset values, so no selector escaping is needed. It then calls `fillViewport()`. It does not touch `state.page`, `state.loadedRows`, `hasMore` or the status text, so those keep counting fetched rows, as the requirement's deliberate simplification states.\n5. **Shared markup (req 9).** The Dislike button in `renderVideoCard` gains `aria-pressed=\"${reaction === \"disliked\"}\"`, written the same way as Like's. Nothing else in the component changes.\n6. **Home unchanged (req 10).** Home's code is not edited. Its only visible difference is the new `aria-pressed=\"false\"` on its Dislike button. Home never shows a disliked card, because its dislike removes the card and the feed filters dislikes.\n7. **Build (req 11).** Run `npm run build` in `client/frontend` so `dist/` carries the change.\n\n### Alternatives considered\n\n- **A shared `runCardAction` helper extracted from home, with callbacks for re-rendering, removing rows and choosing dislike mode.** Rejected. The two pages' dislike behaviour differs in the important way: home removes the card with no undo, while search toggles and keeps the card. A shared helper would therefore need a mode switch or a strategy callback just to serve two callers. It would also mean editing home's working handler, and home must stay exactly as it is. Mirroring costs about 45 lines in one file and carries no risk to home. The duplication is deliberate: a third page that needs card actions is the point to extract a helper.\n- **Re-render the whole search grid from `state.rows` after a removal, the way home's `removeRows` calls `renderCards(true)`.** Rejected. It would wipe other cards' status lines and the keyboard focus, and repaint up to N\u00d724 cards to remove a handful. Removing the matching DOM nodes is smaller and touches only what changed.\n- **Track a separate visible count so the status line drops after a block.** Rejected for now. The requirements name it as the upgrade path. Paging stays correct without it.\n- **Mapping a 401 on a card action to `keyRejectedNotice`.** Ruled out by the operator's decision in req 7 and by the out-of-scope rule on data-layer error types.\n\n### Gotchas and risks\n\n- **A reset while an action is running.** A new search, sort change or popstate can replace the grid while a request is in flight. The clicked card is then detached, and setting `outerHTML` on an element with no parent throws. So the re-render is guarded with `card.isConnected`. A block that finishes after a reset filters the new `state.rows` by that block's channel or account, which is the right result because those rows are blocked anyway. Re-enabling the button in `finally` on a detached node is harmless.\n- **The same video on two loaded pages.** If the Engine's candidate pool ever returns a video twice, the lookup finds the first row, and a like or dislike re-renders only the clicked card. The other copy shows the old mark until the next search. Removal after a block matches by key and field, so it clears every copy.\n- **Keyless dislike.** `cardReaction` ignores `row.reaction` when there is no key, but the no-key guard stops Dislike before any request, so no mismatch can appear.\n- **Stale reactions after a profile change in another tab.** These are not handled. The rendered mark comes from the last search response, as it does on home.\n- **The search fetch's `ProfileKeyRejectedError` handling is not touched.** A key rejected during a card action shows only as that card's status message, by the operator's decision. The next search read then shows the notice.\n\n### Tradeoffs the operator is asked to accept\n\n- The card-action handler exists twice, once in home and once in search, with intentionally different dislike semantics, instead of one shared helper.\n- After a block, \"Showing N of M matched videos.\" may overstate what is on screen until the next reset. This is the deliberate simplification in req 8, and its upgrade path is a separate visible count.\n- Home's Dislike button gains an `aria-pressed=\"false\"` attribute. Nothing else on home changes.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n<impacts>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"module-level imports (lines 11-20)\">\n**What changes:** the imports grow, keeping the file's style (a multi-line brace list once a list gets long, as at lines 12-16).\n- `../../components/video-card` (line 11) adds `resolveInstanceDomain`, `resolveVideoId` and `resolveVideoKey`. They are exported at video-card.ts lines 65, 72 and 80.\n- `../../data/reactions` (line 18) adds `sendReaction`.\n- `../../data/profile` (line 17) adds `getProfileKey` (profile.ts line 20).\n- New import: `blockVideoSource` from `../../data/blocks` (blocks.ts line 33).\n\n**What depends on it:** Rollup's chunk graph. Today the built search entry (`dist/assets/search-0tNFtc30.js`) imports safe-url, video-card, cache, reactions and key-rejected, but not blocks. See the dist entry for what the new import does to chunking.\n\n**Risk:** low. `npm run build` is just `vite build` (package.json line 9), and Vite does not type-check, although tsconfig.json has `strict: true`. A wrong named import or a type error therefore passes the build. Run `npx tsc --noEmit` in client/frontend, or bundle with esbuild as the tests do.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"module docstring (lines 1-7)\">\n**What changes:** today it describes only URL state and infinite paging. Add one or two sentences:\n- cards carry Like, Dislike, Block channel and Block account;\n- Dislike toggles and the card stays, unlike home, because search is not filtered by dislikes (D6);\n- a block removes the loaded cards of that channel or account, while \"Showing N of M\" keeps counting fetched rows.\n\n**What depends on it:** nothing at runtime.\n\n**Risk:** none at runtime. Without it, the code never says why search's handler differs from home's.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"state object (lines 49-60): new `rows` field\">\n**What changes:** add `rows: [] as VideoRow[]`, in the form home uses (videos/index.ts line 85), with a `/** ... */` comment like the ones on `hasMore` and `requestSeq`. `VideoRow` is already a type import at line 20.\n\n**What depends on it:**\n- the new click listener (`state.rows.find`);\n- `renderRows`, which pushes onto it;\n- `removeRows`, which reassigns it;\n- `runCardAction`, through the row reference it holds and mutates (`row.reaction`).\n\n**Risk:** moderate.\n- A reset path that does not clear it lets a fresh card's key resolve to a stale row object with an old `reaction`, so the toggle sends the wrong action.\n- Rows must be pushed only after the `seq` check at line 182. Otherwise a stale response adds rows that were never rendered.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"loadPage() reset block (lines 151-154) and the paths into it: startSearch (line 138), popstate (line 103), initial load (line 108), keyRejectedNotice retry (line 174)\">\n**What changes:** add `state.rows = []` in `if (reset)`, next to `results.innerHTML = \"\"` and `state.loadedRows = 0`. This one line covers new search, sort change (through `startSearch`), popstate, initial load and the \"Forget key\" retry.\n\n**What depends on it:** the row lookup (req 2), and the plan's reset-during-action gotcha. A block that finishes after a reset filters the new `state.rows`.\n\n**Risk:** low in this block. Clearing in `renderRows`' reset branch instead would leave stale rows behind a reset whose fetch failed (SearchUnavailable, ProfileKeyRejected or network). The grid is empty in that case, so no card could reach them, but the reset block is the cleaner place.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"loadPage() catch branch, ProfileKeyRejectedError (lines 172-174), and an appended-page failure\">\n**What changes:** nothing, per req 7.\n\n**Interaction:** if an appended page (`reset=false`) fails with a rejected key, `results.replaceChildren(keyRejectedNotice(...))` wipes the grid but `state.rows` keeps the old rows. No `.video-card` is left, so no click resolves to a row and `removeRows` finds no node. The retry `loadPage(1, true)` clears the rows.\n\n**What depends on it:** 401s from `/api/user-action` (user-actions.ts lines 33-37) and `/api/profile/blocks` (blocks.ts lines 64-66) come back as plain `Error`, so they show in the card's status line and never reach this branch.\n\n**Risk:** no regression. The plan intentionally departs from issue 40 line 40 (\"A rejected key is handled as the search page already handles `ProfileKeyRejectedError`\"). The operator's decision is recorded in the record's step-1 conflicts.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"renderRows() (lines 204-214) and a new search card renderer (the counterpart of home's renderFeedCard, videos/index.ts lines 386-394)\">\n**What changes:**\n- A new function, for example `renderSearchCard(row)`, returns `renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true })` and has a one-line `/** ... */` docstring.\n- `renderRows` maps through it on both the `innerHTML` (reset) path and the `insertAdjacentHTML(\"beforeend\")` path, and pushes the page's rows onto `state.rows`.\n- `runCardAction` uses the same function for in-place re-renders, so the first render and a re-render cannot drift apart.\n\n**What depends on it:**\n- `.card-actions` is emitted only when `options.actions && videoKey` (video-card.ts line 352), so keyless rows stay bare.\n- Cards remain direct children of `#search-results`, which `removeRows` relies on.\n\n**Risk:** low. Each card gains a row of buttons and gets taller, so the sentinel sits further down and `fillViewport` (line 125) fetches fewer pages for the same viewport. That is a visual change, not a functional one.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"new delegated click listener on `results` (#search-results)\">\n**What changes:** a top-level `results.addEventListener(\"click\", ...)` next to the form and sort listeners (lines 70-83). It mirrors home's listener (videos/index.ts lines 135-141), except that the lookup is `state.rows.find((candidate) => resolveVideoKey(candidate) === key)` and not `state.sample`.\n\n**What depends on it:**\n- Cards on appended pages need no extra wiring (req 8).\n- The `keyRejectedNotice` \"Forget key\" button (key-rejected.ts lines 17-24) also lives in `#search-results`. It has no `data-card-action`, so the listener ignores it.\n- `.card-actions` sits outside `<a class=\"video-link\">` (video-card.ts line 351), so buttons do not navigate.\n\n**Risk:** low.\n- `event.target` may be an SVG `<path>` inside a button; `closest` handles that, as on home.\n- A disabled button dispatches no click, so double-clicking during an action does nothing.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"new runCardAction(button, card, row)\">\n**What changes:** new code modelled on home's (videos/index.ts lines 400-447).\n\n**Same as home:**\n- the `say` helper into `.card-action-status`;\n- the no-key guard and its exact text (line 409);\n- `button.disabled = true` and `say(\"\")` before the request, and re-enable in `finally`;\n- Like toggles on `cardReaction(row) === \"liked\"`;\n- Block is `blockVideoSource`, then `sendReaction(\"dislike\").then(() => null, err => message)`, then the \"Blocked \u2026 but the dislike failed\" early return;\n- the predicate at lines 434-440;\n- the `\"Action failed\"` fallback.\n\n**Different from home:**\n- `apiBase` is `apiParam ?? \"\"`. Home passes an already-resolved URL from `resolveApiBase(similarQuery)` (videos/index.ts line 79, data/videos.ts line 92). All the data functions run their argument through `resolveClientApiBase`, so both forms work.\n- Dislike sends `undo_dislike` when `cardReaction(row) === \"disliked\"` and `dislike` otherwise, sets `row.reaction`, and re-renders in place without removing the card.\n- Both re-renders are guarded with `card.isConnected`.\n\n**What depends on it:** `sendReaction` and `cardReaction` (reactions.ts), `blockVideoSource` (blocks.ts), `getProfileKey` (profile.ts), and the `data-card-action` values and the status span in video-card.ts lines 354-359. On the server, `_store_reaction` (client/backend/server.py lines 871-901) makes a like and a dislike replace each other, and `undo_dislike` takes the delete path. That confirms the `row.reaction` values the plan sets.\n\n**Risk:** medium.\n1. `outerHTML` on a detached card throws. Without the guard on both paths, the catch then writes into a dead node.\n2. `row.reaction` must be set before the re-render, because `cardReaction` reads it when a key is held (reactions.ts line 53).\n3. Search users can now reach the dislike cap (a 400 \"Dislike limit reached\") and the 502 for a centroid failure. Both show as the card's message.\n4. The `outerHTML` swap drops keyboard focus. Home's Like already does this; search's Dislike now does too.\n5. The handler is duplicated by hand from home's.\n6. There is no `ProfileKeyRejectedError` branch, by decision.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"new removeRows(match)\">\n**What changes:**\n- Filter `state.rows`.\n- Collect `resolveVideoKey` of the removed rows into a Set.\n- Walk `Array.from(results.children)` and `.remove()` each element whose `dataset.videoKey` is in the Set.\n- Call `fillViewport()`.\n- Leave `state.page`, `loadedRows`, `total`, `hasMore` and the status text untouched (req 8).\n\n**What depends on it:** the block path. `fillViewport` leads to `loadNextPage` (line 116), which returns early while `state.loading` is set or `hasMore` is false.\n\n**Risk:** low to medium.\n1. The predicate must equal home's exactly. Search rows carry `instance_domain`, `channel_id` and `account_url` (engine/server/data/search.py lines 56, 57 and 63).\n2. A next page already in flight when the block lands was filtered server-side before the block existed, so it can bring that channel back. Home has the same race.\n3. If a block empties the grid with `hasMore` false, \"Showing N of M\" stays and no \"No results\" appears. This is the accepted simplification.\n4. The attribute is escaped with `escapeHtml` but `dataset` reads it back unescaped, so it compares directly with raw `resolveVideoKey` and needs no CSS escaping.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"showIdle() (lines 219-228)\">\n**What changes:** add `state.rows = []` next to `state.loadedRows = 0`.\n\n**What depends on it:** an empty submit (line 74) and a popstate to a URL with no `q` (line 100).\n\n**Risk:** low. If it is missed, the leftover rows are unreachable because the grid is emptied. A block that finishes after idle filters them, and `fillViewport` returns early because `hasMore` is false.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"no-key prompt text (req 6) and the search page's chrome\">\n**What changes:** search shows home's exact text: \"Disliking/Blocking needs a profile. Create one from the Profile button.\"\n\n**What depends on it:** search.html. Its nav (lines 21-27) has no Profile button and no profile modal. A grep for \"profile\" across the HTML sources matches only index.html and videos.html.\n\n**Risk:** a UX copy mismatch, not a regression. On search, the prompt points at a button the page does not have. Req 6 demands the exact text, so the operator should rule on the wording rather than the implementer quietly changing it.\n</impact>\n<impact path=\"client/frontend/search.html\" element=\"#search-results (line 58), #search-status (line 55), header nav (lines 21-27), CSP meta (line 8)\">\n**What changes:** nothing.\n\n**What depends on it:**\n- The listener is attached to `#search-results` (class `cards-grid`).\n- Each card's `.card-action-status` is a separate `role=\"status\"` region, apart from `#search-status`.\n- The CSP (`script-src 'self'`) is unaffected, because the new code adds no inline script and no inline handler.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/components/video-card.ts\" element=\"renderVideoCard() action markup, Dislike button (line 356)\">\n**What changes:** insert `aria-pressed=\"${reaction === \"disliked\"}\"` after `data-card-action=\"dislike\"`, in the same form as Like's attribute on line 355. No other change to the component.\n\n**What depends on it:**\n- `renderVideoCard` has two callers: home's `renderFeedCard` (videos/index.ts line 387) and search's `renderRows` (search/index.ts line 208).\n- likes/index.ts line 9 imports only `channelName`, `escapeHtml`, `thumbnailUrl` and `videoPageUrl`. The video page does not import video-card.ts at all (imports at video-page/index.ts lines 5-20).\n- `.card-action[aria-pressed=\"true\"] svg` (videos.css line 664) is generic, so a pressed Dislike fills its icon with no CSS change.\n\n**Risk:** low.\n- Home's Dislike is now announced as a \"not pressed\" toggle even though it is a one-shot remove there. Issue 40 line 43 allows this.\n- `\"true\"` cannot appear on home, because feeds drop disliked rows (server.py line 469) and home's Dislike removes the card.\n</impact>\n<impact path=\"client/frontend/src/components/video-card.ts\" element=\"VideoCardOptions comments (lines 34-37) and module docstring (lines 1-12)\">\n**What changes:** nothing is required; both stay accurate. Optionally, the `reaction` comment at line 34 could say that it also sets `aria-pressed` on the Like and Dislike buttons.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/pages/videos/index.ts\" element=\"home click listener (lines 135-141), renderFeedCard (lines 386-394), runCardAction (lines 400-447), removeRows (lines 452-457)\">\n**What changes:** nothing (req 10). This is the reference that search copies.\n\n**What depends on it:** the acceptance criterion that home's dislike and block still remove cards and home has no undo-dislike.\n\n**Risk:**\n- Only the shared markup reaches home, and home never reads `aria-pressed`.\n- The implementer must not \"tidy\" home while copying from it, for example by adding an `isConnected` guard or `undo_dislike` there.\n</impact>\n<impact path=\"client/frontend/src/data/reactions.ts\" element=\"sendReaction() (lines 89-100), cardReaction() (lines 52-57), AFTER (lines 20-25)\">\n**What changes:** nothing. Search calls `sendReaction` for the first time.\n\n**What depends on it:**\n- A keyless like or undo-like is written to `localLikes:v1` before `sendReaction` resolves (lines 95-98), so a keyless re-render reads it correctly.\n- `undo_dislike` is a valid `ReactionAction` (line 16).\n\n**Known gap, inherited from home and not introduced here:**\n- Keyless, the like is stored under `resolveVideoId(row)`, which falls back to `video_id` when `video_uuid` is null (video-card.ts lines 72-75). `cardReaction` (lines 54-56) checks only `video_uuid`/`videoUuid`.\n- So a keyless Like on a row with a null `video_uuid` (the column is nullable in engine/crawler/schema.sql) succeeds but never shows as liked, and the next click sends `like` again.\n- Fixing it is out of scope for this build, because it would change `reactions.ts` and home with it.\n\n**Risk:** none to the module. The gap is a low risk on the search page.\n</impact>\n<impact path=\"client/frontend/src/data/blocks.ts\" element=\"blockVideoSource() (lines 33-41) and request() (lines 51-68)\">\n**What changes:** nothing.\n\n**What depends on it:** search's block path.\n- Every non-OK answer, 401 included, throws a plain `Error(payload.error ?? \"Block request failed (N)\")`, which fits req 7.\n- `Block` has `kind`, `instance_domain`, `channel_id`, `account_url` and `label` (lines 13-20).\n\n**Risk:** none. A reply without `kind` would fall into the account branch on both pages.\n</impact>\n<impact path=\"client/frontend/src/data/user-actions.ts\" element=\"sendUserAction() (lines 18-38)\">\n**What changes:** nothing.\n\n**What depends on it:** every Like and Dislike on search, through `sendReaction`. On any non-OK status it throws `Error(body.error ?? \"Failed to send action\")`. That text, including the server's messages for the dislike cap and for a missing key, is what reaches the card's status line.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/data/api-base.ts\" element=\"resolveClientApiBase() (lines 18-33)\">\n**What changes:** nothing.\n\n**What depends on it:** search passes `apiParam ?? \"\"`. Resolution order is `VITE_CLIENT_API_BASE` first, then `?api=` in DEV only, then `window.location.origin`. In production, `?api=` is ignored, so passing `apiParam` cannot redirect card actions.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/data/profile.ts\" element=\"getProfileKey() (lines 20-26)\">\n**What changes:** nothing. Search imports it for the first time, for the no-key guard.\n\n**What depends on it:** the guard. It reads `localStorage` `profileKey:v1` on each call, so a key created in another tab takes effect on the next click.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/data/search.ts\" element=\"fetchSearchResults(): keyed no-store branch (lines 68-76) and keyless sessionStorage cache (lines 78-90)\">\n**What changes:** nothing.\n\n**What depends on it:** the \"rerun the same search\" acceptance checks.\n- With a key, the fetch is `cache: \"no-store\"`, so a rerun shows a dislike, an undo or a block at once.\n- Without a key, results are cached for 30 s, but cache.ts re-parses from sessionStorage on every read (cache.ts lines 44-58), so mutating `row.reaction` in place never leaks into the cache.\n- Keyless actions are limited to Like, whose mark comes from `localLikes:v1`.\n\n**Risk:** none. Rerun checks must use a key.\n</impact>\n<impact path=\"client/frontend/src/data/cache.ts\" element=\"fetchJsonWithCache / readCache / writeCache\">\n**What changes:** nothing.\n\n**What depends on it:** the keyless search path. `writeCache` stores `JSON.stringify(payload)` before the rows are handed to the page, and `readCache` parses fresh objects, so search's in-place `row.reaction` writes cannot corrupt cached pages.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/types/videos.ts\" element=\"VideoRow: channel_id (line 10), account_url (line 15), reaction (lines 51-52)\">\n**What changes:** nothing.\n\n**What depends on it:** search's block predicate and the `row.reaction` assignments. The type is `\"liked\" | \"disliked\" | null`.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/components/key-rejected.ts\" element=\"keyRejectedNotice(onForget)\">\n**What changes:** nothing.\n\n**What depends on it:** its retry calls `loadPage(1, true)`, a reset path that must clear `state.rows`. Its button sits inside `#search-results` and has no `data-card-action`, so the new listener ignores it.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/videos.css\" element=\".stat.active (lines 616-623), .card-actions \u2026 .card-action-status:empty (lines 625-676), .visually-hidden (lines 678-685), :root variables (lines 5-8)\">\n**What changes:** nothing. Search already imports it (search/index.ts line 9), and the variables the card actions use (`--line`, `--accent-strong`, `--muted`) are defined in this file.\n\n**What depends on it:**\n- the action row layout;\n- the filled icon for a pressed Dislike (line 664);\n- the disliked stat mark;\n- the hidden \"Like\" and \"Dislike\" labels.\n\n**Risk:** low.\n- There is no `.video-card.disliked` rule, so the root class has no visual effect.\n- Search cards get taller; check this visually.\n</impact>\n<impact path=\"client/frontend/src/search.css\" element=\"whole file, including its own .visually-hidden (lines 69-79)\">\n**What changes:** nothing. No rule targets `.card-action*` or `.video-card`. The header comment (lines 1-3) says the cards reuse videos.css.\n\n**What depends on it:** `.visually-hidden` is defined both here and in videos.css with the same specificity. The built search.html loads search CSS before videos CSS (dist/search.html lines 18-19), so for overlapping properties the videos.css copy wins. Both hide the button labels, so this is not a regression.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"FEED_ROUTES/FILTERED_ROUTES (lines 71-72), _profile_filter dropped rule (line 469), _store_reaction (lines 871-901), _filter_payload (lines 1096-1122)\">\n**What changes:** nothing; this is out of scope.\n\n**What depends on it:**\n- Search is filtered by blocks but never by dislikes (D6), so the card can stay after a Dislike, and a rerun returns the row with `reaction: \"disliked\"`.\n- `reaction` is keyed on `(video_id, instance_domain)`.\n- Like/dislike replacement and `undo_dislike` (lines 871-901) are what search's toggle relies on.\n- `total` is not adjusted after filtering, which is why the req 8 count is honest only about fetched rows.\n\n**Risk:** none from this build. If D6 is ever reversed, search's toggle and keep-card behaviour need revisiting.\n</impact>\n<impact path=\"engine/server/data/search.py\" element=\"VIDEO_ROW_SQL (lines 51-79)\">\n**What changes:** nothing.\n\n**What depends on it:** search's key, its toggle and its block predicate use `video_id` (53), `video_uuid` (54), `instance_domain` (56), `channel_id` (57) and `account_url` (63). All are present.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/vite.config.ts\" element=\"build.rollupOptions.input (lines 84-94)\">\n**What changes:** nothing. `search.html` is already an entry (line 87).\n\n**What depends on it:** the rebuild. The `about` entry uses `dev-pages/about.html` if that file exists. Only `about.template.html` is present today.\n\n**Risk:** none, unless a local `about.html` appears before the build.\n</impact>\n<impact path=\"client/frontend/package.json\" element=\"scripts.build (line 9) and the frontend toolchain\">\n**What changes:** nothing. Req 11 runs `npm run build` (that is, `vite build`).\n\n**What depends on it:** the dist rebuild and any esbuild-based test. Uncertain: a Glob of `client/frontend/node_modules/.bin/*` in this worktree returned nothing, and the Read was blocked by the sandbox. node_modules may be missing here or symlinked from outside the project. If it is missing, `npm ci` is needed in the worktree first. `tests/active/test_frontend_*.py` also resolve `FRONTEND/node_modules/.bin/esbuild`.\n\n**Risk:** low, but the build or the tests can fail for environment reasons rather than code reasons.\n</impact>\n<impact path=\"client/frontend/dist/\" element=\"built bundle: *.html and assets/*\">\n**What changes:** `npm run build` regenerates it, and `dist/` is tracked. Correcting the earlier inventory, these are the actual importers:\n- **video-card chunk** (`video-card-C4VEive-.js`): imported by `index-OsZsLoAr.js`, `likes-xsQYeXe5.js` and `search-0tNFtc30.js`, and referenced by index.html, videos.html, likes.html and search.html. channels and video-page do not import it.\n- **The chunk named `blocks-DRgP8l-1.js` is a merged chunk.** It holds data/videos.ts (createFeedPager, buildSimilarUrl, resolveApiBase) as well as blocks.ts. index and video import it; video-page.html, index.html and videos.html reference it.\n- **Effect of search importing blocks.ts:** blocks.ts will be shared by three entries while data/videos.ts stays shared by two. Rollup will likely split them, which means a new chunk file, a changed blocks chunk, and new hashes for `index-*.js`, `video-*.js` and their HTML pages as well as search and likes. This is a prediction, not verified.\n\nOld hashed files are deleted.\n\n**What depends on it:** the served site. scripts/sync.sh line 19 builds, then rsyncs with `--delete` (line 22). DEPLOYMENT.md line 390 says the committed dist lags the source.\n\n**Risk:** medium for the commit, low for the code.\n- Run the build once, after both source edits.\n- Commit the whole dist diff, added and deleted files included. A partial commit leaves HTML pointing at missing chunks.\n- Skipping the build fails the acceptance criterion.\n</impact>\n<impact path=\"tests/active/test_frontend_reactions.py\" element=\"cards step of RUNNER (lines 86-99) and _bundle (lines 106-124)\">\n**What changes:** nothing needed. It renders `renderVideoCard(row, { reaction })` without `actions`, so the new attribute is never emitted, and its regexes target only `class=\"stat likes active\"` and `class=\"stat dislikes active\"`.\n\n**Risk:** none. It remains the guard for `cardReaction` over search rows.\n</impact>\n<impact path=\"tests/active/test_frontend_videos_page.py\" element=\"home runner and fake DOM (lines 22-90)\">\n**What changes:** nothing needed. It asserts only the `data-video-key` values in `#video-cards` (line 89), so the extra `aria-pressed` on home's markup does not affect it.\n\n**Risk:**\n- None to this test.\n- It does not guard card actions: its fake element has `closest: () => null` (line 51) and no `outerHTML`, `isConnected` or `dataset`.\n- Its esbuild bundling of a page entry is the template for a search-page test.\n</impact>\n<impact path=\"tests/active/test_frontend_blocks.py\" element=\"block runner steps\">\n**What changes:** nothing.\n\n**What depends on it:** it pins the `Block` shape that search consumes.\n\n**Risk:** none.\n</impact>\n<impact path=\"tests/active/ (new search-page card-action test; filename to be decided, drafted in tests/tmp first)\">\n**What changes:** a grep for `pages/search`, `search.html`, `search-results` and `video-card` under tests/ and tests/tmp finds no test that loads the search page, so every acceptance criterion here is unguarded.\n\n**Candidate test:** bundle `src/pages/search/index.ts` with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`), as test_frontend_videos_page.py does. Assert that:\n- appended pages render the buttons;\n- Dislike sends `dislike` then `undo_dislike`, and `aria-pressed` flips between true and false;\n- no request is made without a key;\n- a block removes the matching cards and calls `fillViewport`;\n- a re-render after a reset does not throw.\n\nRerun checks need a key, against `engine_client` or `unpublished_client`.\n\n**Risk:** the fake DOM needs `closest`, `outerHTML`, `isConnected`, `dataset`, element children and `remove`. That is a richer fake than any existing test has.\n</impact>\n<impact path=\"tests/check-frontend-client-gateway.sh\" element=\"frontend gateway boundary grep\">\n**What changes:** nothing. The new code calls only Client routes (`/api/user-action`, `/api/profile/blocks`), through the existing data modules.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/README.md\" element=\"'What it does' list, line 16 (reaction marks)\">\n**What changes:** documentation; see the checklist. Line 16 covers the reaction marks, but no bullet describes the card action buttons on either feed or search. The feed-grid controls are undocumented too.\n\n**Risk:** none at runtime.\n</impact>\n<impact path=\"docs/project/roadmap.md\" element=\"F13-M2 (line 54) and the Delivered section (lines 7-25)\">\n**What changes:** after this build, the feed-grid and search-grid halves of F13-M2 are in the tree and only the channels page remains. No Delivered entry exists for the feed-grid half either; the archived plan 07 line 33 only defers it. Which change delivered it could not be established from the docs.\n\n**Risk:** none at runtime; traceability only.\n</impact>\n<impact path=\"docs/project/issues/40-search-card-actions.md\" element=\"Status line (line 3), Comments, location\">\n**What changes:** on delivery, per issue-tracker.md line 21:\n- set `Status: enhancement, complete`;\n- append a comment that names the plan and records the req 7 decision, which departs from the brief at line 40;\n- move the file to `docs/project/issues/archive/`.\n\n**Risk:** traceability only.\n</impact>\n<impact path=\"docs/project/plans/20-40-search-card-actions.md\" element=\"Impacts and Documentation sections\">\n**What changes:** the workflow re-renders them from the run state; the header at line 3 says manual edits are overwritten. At delivery the plan moves to `docs/project/plans/archive/` (issue-tracker.md line 29).\n\n**Risk:** none at runtime.\n</impact>\n<impact path=\"client/README.md\" element=\"user-action and gateway filtering (lines 19, 24-25)\">\n**What changes:** nothing. It already says the dislike actions need a key, a like and a dislike replace each other, search is not filtered by dislikes, and rows carry `reaction`.\n\n**Risk:** none.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"likes and dislikes paragraph (line 360), dist sync note (lines 386-390)\">\n**What changes:** nothing. \"Search is not filtered by dislikes\" and \"which the frontend shows on the card\" both still hold. The sync note is the deploy step that follows req 11.\n\n**Risk:** none.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"glossary: Dislike (line 4), Block (line 11)\">\n**What changes:** nothing. The Dislike entry says a dislike removes the video from feeds, not from search, which matches search keeping the card. No new term is introduced.\n\n**Risk:** none.\n</impact>\n</impacts>\n</impacts>\n\n<docs_checklist>\n<doc path=\"client/frontend/README.md\">\nAdd a \"What it does\" bullet after line 16. Home and search cards carry Like, Dislike, Block channel and Block account. Like works without a key; Dislike and Block need a key and otherwise show the \"needs a profile\" prompt on the card. On home, Dislike or Block removes the affected cards, with no undo. On search, Dislike toggles `dislike`/`undo_dislike` and the card stays marked, because search is not filtered by dislikes. A Block removes every loaded card of that channel or account, while \"Showing N of M\" keeps counting fetched rows. A failed action, a rejected key included, shows in that card's status line. Like and Dislike both carry `aria-pressed`.\n</doc>\n<doc path=\"docs/project/roadmap.md\">\nUpdate F13-M2 (line 54): the feed and search grids are delivered, and only the channels page remains. Add a Delivered entry naming issue `40` and its plan, at the plan's archive path once moved. Also note that the feed-grid half had no Delivered entry before this change.\n</doc>\n<doc path=\"docs/project/issues/40-search-card-actions.md\">\nOn delivery, set `Status: enhancement, complete` and append a comment naming the delivering plan. In that comment, record that a rejected key during a card action shows as the card's status message, not `keyRejectedNotice`, which overrides the brief's Errors bullet at line 40. Also record whether the \"Profile button\" wording of the no-key prompt was kept on search, which has no such button. Then move the file to `docs/project/issues/archive/`.\n</doc>\n<doc path=\"docs/project/plans/20-40-search-card-actions.md\">\nThe workflow re-renders the Impacts and Documentation sections from this inventory. On delivery, move the plan to `docs/project/plans/archive/`.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nclient/frontend/src/pages/search/index.ts runCardAction: a hand-copied handler whose dislike semantics differ from home's on purpose. If the `card.isConnected` guard is missing on either the Like or the Dislike re-render, an action that finishes after a reset throws. If `row.reaction` is set after the re-render, the toggle reads the wrong state. No existing test loads the search page.\nclient/frontend/src/pages/search/index.ts state.rows lifecycle (loadPage reset block at lines 151-154, showIdle, renderRows after the seq check at line 182): if a reset path does not clear it, or a stale response pushes rows onto it, a fresh card's key resolves to an old row object with a stale `reaction`, and the card sends the wrong toggle action.\nclient/frontend/dist/: search's new import of blocks.ts changes Rollup's chunking. `blocks-DRgP8l-1.js` is a merged chunk that also holds data/videos.ts, so the build will likely split it and re-hash index, video, likes and search, along with their HTML. A partial commit of the added and deleted hashed files ships pages that reference chunks that no longer exist, and `sync.sh` rsyncs with `--delete`.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the files it names: search/index.ts, videos/index.ts (home), video-card.ts, reactions.ts, blocks.ts, user-actions.ts, api-base.ts, profile.ts, search.html, server.py `_store_reaction`, issue 40, the dist asset list, and test_frontend_videos_page.py. Every line reference and every behavioural claim I checked matched. The plan holds. It has one gap the inventory does not carry: two different buttons on the same card can be in flight at once. Because the plan re-renders through the captured `card` node behind an `isConnected` guard, that case leaves a stale card on screen with no error.\n<question id=\"1\">\nYes. The search rows carry every field the key, the toggle and the block predicate need. `sendReaction`, `blockVideoSource` and `sendUserAction` all resolve `apiParam ?? \"\"` through `resolveClientApiBase`. `_store_reaction` (server.py 871-901) confirms the values the plan writes to `row.reaction`: like and dislike replace each other, and `undo_dislike` takes the delete path. The delegated listener on `#search-results` covers appended pages. Clearing `state.rows` in `loadPage`'s reset block and in `showIdle` covers every reset path. One edge needs a small change: in-place re-rendering has to stay correct when two different action buttons on the same card are clicked before the first one finishes (see new_impacts).\n</question>\n<question id=\"2\">\n- Search cards get taller, so `fillViewport` fetches fewer pages per screen.\n- Search users can now reach the dislike cap (400) and the centroid 502. Both appear as the card's message.\n- A key rejected during a card action shows only in the card's status line. This departs from issue 40 line 40, by the operator's decision.\n- The no-key prompt names a Profile button that search.html does not have.\n- The `outerHTML` swap drops keyboard focus.\n- The handler is duplicated from home by hand.\n- Search's entry now imports blocks.ts, so the dist chunk graph probably changes, along with hashes on pages other than search.\n- \"Showing N of M\" overstates after a block, as accepted.\n</question>\n<question id=\"3\">\n- Clear `state.rows` on every reset: the `loadPage` reset block and `showIdle`.\n- Push rows only after the `seq` check.\n- Set `row.reaction` before re-rendering.\n- Make the re-render safe when the captured card has already been replaced (see new_impacts).\n- Leave home's code untouched.\n- Run `npx tsc --noEmit`, because `vite build` does not type-check.\n- Rebuild `dist/` once, after both source edits, and commit the whole dist diff, added and deleted files included.\n- Make sure `node_modules` exists in the worktree before building or running the esbuild-based tests.\n</question>\n<question id=\"4\">\n- Search cards gain Like, Dislike, Block channel and Block account controls.\n- Dislike on search toggles and keeps the card.\n- A block removes the loaded cards of that channel or account.\n- The shared Dislike button gains `aria-pressed`. On home it is always `\"false\"`, which is announced as a toggle that is never pressed. Home's behaviour is otherwise unchanged.\n- No other page renders action controls.\n</question>\n</summary>\n\n<new_impacts>\nclient/frontend/src/pages/search/index.ts (new runCardAction): only the clicked button is disabled, so a second button on the same card can be clicked while the first request is still running. Example: Like, then Dislike before Like returns. Like's re-render swaps the card's `outerHTML`, so the `card` node captured by the Dislike call is detached. When Dislike resolves, it sets `row.reaction = \"disliked\"`, but the `card.isConnected` guard skips its re-render. The page then shows \"liked\" while `row.reaction` and the server both say \"disliked\", and the next Dislike click sends `undo_dislike` on a card that does not look disliked. Errors are also written into the detached card's status span, so they are never seen. Home does not hit this, because its dislike and block re-render the whole grid from state; search's in-place re-render is what introduces it.\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. Fix the gap from new_impacts in one of two ways. Either changes only search/index.ts, and neither touches home or the settled plan's shape.\n   - (a) Recommended. Re-render through the live node, not the captured one. After setting `row.reaction`, find each child of `results` whose `dataset.videoKey` equals `resolveVideoKey(row)`, using the same walk `removeRows` does, and replace its `outerHTML`. Write the status message into the live card's `.card-action-status` too. This replaces the `isConnected` guard: after a reset there is no match, so nothing is touched. As a side effect it also updates the duplicate copy the plan's \"same video on two loaded pages\" gotcha leaves stale. Cost: about 6-8 lines, plus a fake-DOM test case for it.\n   - (b) Disable every `.card-action` in the card for the duration of an action, instead of only the clicked button. Cost: about 2 lines. It does not fix the duplicate-copy case, and it departs further from home's handler.\n2. In the new search-page test, cover a second action started while the first is in flight, and a re-render after a reset. Cost: the richer fake DOM the inventory already anticipates.\n3. Before building, run `npx tsc --noEmit` and confirm `node_modules` exists. Cost: a minute, plus `npm ci` if node_modules is missing.\n4. Get an operator ruling on the no-key prompt's \"Profile button\" wording on search. Cost: none to implement either way. Req 6 currently fixes the exact text.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation \u2014 issue 40, search card actions\n\n### Module map\n\n| File | Change |\n|---|---|\n| `client/frontend/src/components/video-card.ts` | Line 356: the Dislike button gains `aria-pressed=\"${reaction === \"disliked\"}\"`, written exactly like Like's on line 355. Nothing else changes. |\n| `client/frontend/src/pages/search/index.ts` | Changes: imports, docstring, `state.rows`, the reset in `loadPage`, `showIdle`, `renderRows`, a new `renderSearchCard`, a delegated click listener, `runCardAction` and `removeRows`. |\n| `client/frontend/src/pages/videos/index.ts` | Not touched (req 10). |\n| `client/frontend/dist/` | Rebuilt once with `npm run build` after both source edits. The whole diff is committed, including added and deleted chunks. |\n| `tests/tmp/test_frontend_search_card_actions.py` | New test, drafted here and promoted to `tests/active/` (see \"What has to be tested\"). |\n\nThere is no new shared module. Home's handler is copied into search on purpose (plan, Alternatives \u00a71).\n\n### `components/video-card.ts`, line 356\n\n```ts\n        <button type=\"button\" class=\"card-action\" data-card-action=\"dislike\" aria-pressed=\"${reaction === \"disliked\"}\" title=\"Dislike\">${iconThumbDown()}<span class=\"visually-hidden\">Dislike</span></button>\n```\n\nInvariant: `aria-pressed` is `\"true\"` only when `options.reaction === \"disliked\"`. Home never passes that value, because its feeds drop disliked rows, so home always renders `\"false\"`.\n\n### `pages/search/index.ts`\n\n**Docstring (lines 1-7)**: add a paragraph:\n\n```ts\n *\n * Each card carries Like, Dislike, Block channel and Block account. Unlike home, Dislike toggles and\n * the card stays, because search is not filtered by dislikes (D6). A block removes the loaded cards of\n * that channel or account, while \"Showing N of M\" keeps counting fetched rows.\n```\n\n**Imports (lines 11-18)**:\n\n```ts\nimport {\n  renderVideoCard,\n  resolveInstanceDomain,\n  resolveVideoId,\n  resolveVideoKey\n} from \"../../components/video-card\";\nimport {\n  fetchSearchResults,\n  SearchUnavailableError,\n  type SearchSort\n} from \"../../data/search\";\nimport { getProfileKey, ProfileKeyRejectedError } from \"../../data/profile\";\nimport { cardReaction, importLocalLikes, sendReaction } from \"../../data/reactions\";\nimport { blockVideoSource } from \"../../data/blocks\";\nimport { keyRejectedNotice } from \"../../components/key-rejected\";\nimport type { SearchPayload, VideoRow } from \"../../types/videos\";\n```\n\n**State (lines 49-60)**: add after `total`:\n\n```ts\n  /** Rows rendered into the grid, in order; card actions find their row here by video key. */\n  rows: [] as VideoRow[],\n```\n\n**Click listener**: placed after the `sortSelect` listener (after line 83), mirroring home's listener at videos/index.ts lines 135-141:\n\n```ts\nresults.addEventListener(\"click\", (event) => {\n  const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>(\"[data-card-action]\");\n  const card = button?.closest<HTMLElement>(\".video-card\");\n  const key = card?.dataset.videoKey;\n  const row = key ? state.rows.find((candidate) => resolveVideoKey(candidate) === key) : undefined;\n  if (button && card && row) void runCardAction(button, card, row);\n});\n```\n\nInvariant: a click resolves to a row only when the button, the card, the key and a stored row all exist. Anything else does nothing, including the keyRejectedNotice \"Forget key\" button, which has no `data-card-action`.\n\n**`loadPage` reset block (lines 151-154)**:\n\n```ts\n  if (reset) {\n    results.innerHTML = \"\";\n    state.loadedRows = 0;\n    state.rows = [];\n  }\n```\n\nThis one line covers new search, sort change, popstate, initial load and the key-rejected retry. `renderRows` is called only after the `seq` check at line 182, so a stale response can never push rows.\n\n**`renderRows` (lines 207-214)** and the new renderer:\n\n```ts\n/**\n * Render rows into the grid through the shared card component and remember them for card actions.\n */\nfunction renderRows(rows: VideoRow[], reset: boolean) {\n  const markup = rows.map(renderSearchCard).join(\"\");\n  state.rows.push(...rows);\n  if (reset) {\n    results.innerHTML = markup;\n    return;\n  }\n  results.insertAdjacentHTML(\"beforeend\", markup);\n}\n\n/**\n * Render one search card with its action controls; used for first renders and in-place re-renders.\n */\nfunction renderSearchCard(row: VideoRow) {\n  return renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true });\n}\n```\n\nInvariant: `state.rows` holds the rendered rows in DOM order, and each keyed row has exactly one `article.video-card[data-video-key]` as a direct child of `#search-results`. `rows.map(renderSearchCard)` is safe because `map`'s index argument lands nowhere: `renderSearchCard` takes one parameter.\n\n**`runCardAction`**: a copy of home's lines 400-447 with only the differences the plan names:\n\n```ts\n/**\n * Like, dislike or block from a card; a block dislikes the video too. Like and Dislike toggle and the\n * card stays, marked; a block takes every loaded card of that channel or account off the page.\n */\nasync function runCardAction(button: HTMLButtonElement, card: HTMLElement, row: VideoRow) {\n  const action = button.dataset.cardAction ?? \"\";\n  const apiBase = apiParam ?? \"\";\n  const uuid = resolveVideoId(row);\n  const host = resolveInstanceDomain(row);\n  const status = card.querySelector<HTMLElement>(\".card-action-status\");\n  const say = (text: string) => {\n    if (status) status.textContent = text;\n  };\n  if (action !== \"like\" && !getProfileKey()) {\n    say(`${action === \"dislike\" ? \"Disliking\" : \"Blocking\"} needs a profile. Create one from the Profile button.`);\n    return;\n  }\n  button.disabled = true;\n  say(\"\");\n  try {\n    if (action === \"like\") {\n      const liked = cardReaction(row) === \"liked\";\n      await sendReaction(apiBase, liked ? \"undo_like\" : \"like\", { uuid, host });\n      row.reaction = liked ? null : \"liked\";\n      // A reset during the request detaches the card; outerHTML on a detached node throws.\n      if (card.isConnected) card.outerHTML = renderSearchCard(row);\n    } else if (action === \"dislike\") {\n      const disliked = cardReaction(row) === \"disliked\";\n      await sendReaction(apiBase, disliked ? \"undo_dislike\" : \"dislike\", { uuid, host });\n      row.reaction = disliked ? null : \"disliked\";\n      if (card.isConnected) card.outerHTML = renderSearchCard(row);\n    } else if (action === \"channel\" || action === \"account\") {\n      const block = await blockVideoSource(apiBase, action, uuid, host);\n      // Blocking also dislikes the video, as on home.\n      const disliked = await sendReaction(apiBase, \"dislike\", { uuid, host }).then(\n        () => null,\n        (error: unknown) => (error instanceof Error ? error.message : \"Dislike failed\")\n      );\n      if (disliked !== null) {\n        say(`Blocked ${block.label || action}, but the dislike failed: ${disliked}`);\n        return;\n      }\n      removeRows(\n        block.kind === \"channel\"\n          ? (candidate) =>\n              String(candidate.instance_domain ?? \"\") === block.instance_domain &&\n              String(candidate.channel_id ?? \"\") === block.channel_id\n          : (candidate) => String(candidate.account_url ?? \"\") === block.account_url\n      );\n    }\n  } catch (error) {\n    say(error instanceof Error ? error.message : \"Action failed\");\n  } finally {\n    button.disabled = false;\n  }\n}\n```\n\nInvariants:\n- `row.reaction` is assigned only after the request resolves. A failure leaves both the row and the card unchanged, and the message appears in the old card's status line, which is still attached.\n- `row.reaction` is assigned before the re-render, because `cardReaction` reads it when a key is held.\n- After a successful Like or Dislike, `button` and `status` belong to the replaced, detached node. The `finally` re-enables that detached button, which is harmless, and the new card renders enabled. This matches home's Like.\n- No branch for `ProfileKeyRejectedError` (req 7, operator decision). A 401 arrives as a plain `Error` and is shown with `say`.\n- The block predicate is home's lines 434-440, character for character.\n\n**`removeRows`**:\n\n```ts\n/**\n * Drop matching rows and their cards in place, then refill the viewport. Paging counters keep\n * counting fetched rows: the Client filters each Engine page, so page numbers do not shift.\n */\nfunction removeRows(match: (row: VideoRow) => boolean) {\n  const removed = new Set(state.rows.filter(match).map((row) => resolveVideoKey(row)));\n  state.rows = state.rows.filter((row) => !match(row));\n  for (const element of Array.from(results.children) as HTMLElement[]) {\n    const key = element.dataset.videoKey;\n    if (key && removed.has(key)) element.remove();\n  }\n  fillViewport();\n}\n```\n\nInvariant: `state.page`, `loadedRows`, `total`, `hasMore` and the status text are not touched (req 8, deliberate simplification). `dataset.videoKey` gives back the unescaped key, so it compares directly with `resolveVideoKey`, with no selector escaping. Keyless rows never have a card with controls and cannot be the clicked row. If a keyless row matched a block, it would be dropped from `state.rows`, but its card has no `data-video-key` and stays on the page. That is harmless and inert. `fillViewport` returns early while a page is loading or `hasMore` is false.\n\n**`showIdle` (lines 219-228)**: add `state.rows = [];` after `state.loadedRows = 0;`.\n\n### Requirement trace (check pass 1 \u2014 converged)\n\n| Req | Where it is met |\n|---|---|\n| 1 Controls | `renderSearchCard` passes `actions: true`, and `renderRows` uses it on both paths. Keyless rows get no controls because of video-card.ts line 352. |\n| 2 Row lookup | `state.rows`, the resets in `loadPage(reset)` and `showIdle`, and the delegated listener. |\n| 3 Like | The toggle on `cardReaction(row) === \"liked\"`, followed by an in-place `renderSearchCard`. |\n| 4 Dislike toggle | The `undo_dislike`/`dislike` branch, the in-place re-render, and the `aria-pressed` added in video-card.ts. |\n| 5 Block | `blockVideoSource`, then `sendReaction(\"dislike\")`. A failed dislike gets the early return with the message; otherwise `removeRows` runs with home's predicate. |\n| 6 No key | Home's guard and its exact text. No request is sent. |\n| 7 Errors | Disabled button, `say(message \\|\\| \"Action failed\")`, re-enable in `finally`. No change to the data layer. |\n| 8 Paging | The listener is on the container. Counters are untouched. `removeRows` calls `fillViewport()`. |\n| 9 Markup | One attribute on line 356. |\n| 10 Home | `videos/index.ts` is not edited. |\n| 11 Build | `npm run build`, preceded by `npx tsc --noEmit`, because Vite does not type-check. |\n\nI checked the plan's risks as well: the reset during an action is handled by `isConnected`; a block landing after a reset filters the new rows, which is correct; a duplicate video is handled because `removeRows` is key-based and clears every copy. One copy concern remains, below.\n\n**Flag, not a fix:** search.html has no Profile button, so the required text \"\u2026Create one from the Profile button.\" points at nothing on this page. Req 6 requires the exact text, so the draft keeps it. The issue 40 delivery comment should record that the wording was kept, as the documentation checklist asks.\n\n### What has to be tested\n\n`tests/tmp/test_frontend_search_card_actions.py`. It bundles `src/pages/search/index.ts` with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`), modelled on `test_frontend_videos_page.py`. It runs under node with a fake DOM that supports `closest`, `dataset`, `children`, `remove`, `outerHTML` (re-parsed into a new node) and `isConnected`, a stub `fetch` that records method, path and body, and an `IntersectionObserver` stub. Cases:\n\n1. Page 1 plus an appended page 2: every keyed card has four `[data-card-action]` buttons, and a keyless row has none.\n2. With a key, Dislike sends `dislike`, and the card re-renders with `stat dislikes active` and Dislike `aria-pressed=\"true\"`. A second click sends `undo_dislike` and the mark clears (`aria-pressed=\"false\"`).\n3. Like on a disliked card sends `like` and the card shows liked, not disliked. A second click sends `undo_like`.\n4. Without a key, Dislike, Block channel and Block account each write the exact prompt and make no fetch. Keyless Like sends `like` and stores it in `localLikes:v1`.\n5. Block channel: `POST /api/profile/blocks`, then `dislike`. Every loaded card with the same `instance_domain`+`channel_id` is removed, including on page 2, and `fillViewport` runs (the sentinel is in view, so page 3 is fetched). The status text is unchanged. Block account works the same way through `account_url`.\n6. Block where the dislike returns 500: the status line reads `Blocked <label>, but the dislike failed: <msg>` and no card is removed.\n7. A failed request (400 \"Dislike limit reached\"): the message appears in the status line, the button is re-enabled, and `row.reaction` is unchanged.\n8. A reset while an action is in flight (a new search resolves first): no exception, and `state.rows` holds only the new rows.\n9. The rendered markup of `renderVideoCard(row, { actions: true, reaction: null })` has Dislike `aria-pressed=\"false\"`. This is home's case.\n\nThe acceptance reruns (a keyed rerun of the search shows `reaction: \"disliked\"`, no reaction after undo, and no blocked-channel rows) are backend facts, already covered by D6 and `_filter_payload`. They are checked manually against a live Client with a key, or by `engine_client` if the test is extended. The existing `test_frontend_reactions.py`, `test_frontend_blocks.py` and `test_frontend_videos_page.py` must stay green unchanged.\n\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: `renderVideoCard` in `client/frontend/src/components/video-card.ts`, called directly from a small esbuild bundle that re-exports it. This follows the precedent in `tests/active/test_frontend_reactions.py` (line 112 re-exports `renderVideoCard` from the component and asserts on the returned markup). The test lives in `tests/tmp/test_frontend_search_card_actions.py` and renders a keyed row with `{ actions: true, reaction: \"disliked\" }`, `{ actions: true, reaction: null }` (home's case) and `{ actions: true, reaction: \"liked\" }`. On the `[data-card-action=\"dislike\"]` button it asserts `aria-pressed=\"true\"` for the first and `aria-pressed=\"false\"` for the other two. `npx tsc --noEmit` passes in `client/frontend`.</checkpoint>\n<name>Dislike pressed state in the shared card</name>\n<intent>`renderVideoCard` in `components/video-card.ts` now reports the Dislike button's pressed state from `options.reaction`, the same way it already does for Like.</intent>\n<clause_1>The Dislike button has `aria-pressed=\"true\"` when `options.reaction` is `\"disliked\"`, and `aria-pressed=\"false\"` otherwise.</clause_1>\n<files>client/frontend/src/components/video-card.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (NEW)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the search page entry, `client/frontend/src/pages/search/index.ts`. It is bundled with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`) and run under node with a stub `fetch` that records method, path and body, plus an `IntersectionObserver` stub. This follows `tests/active/test_frontend_videos_page.py`. That harness's fake DOM stubs `closest` to return null, so this phase builds a richer fake DOM in the new test file, and phases 3 and 4 reuse it. The new DOM supports `closest`, `dataset`, `children`, `remove`, an `outerHTML` setter that re-parses into a new node, and `isConnected`. Assertions, all made through the DOM and the recorded fetches:\n(a) After page 1 and an appended page 2, every keyed `.video-card` under `#search-results` has four `[data-card-action]` buttons, and a keyless row's card has none.\n(b) With a key, clicking Dislike sends `dislike`, and the card re-renders with `stat dislikes active` and `aria-pressed=\"true\"`. A second click sends `undo_dislike` and the mark clears. Like on a disliked card sends `like` and the card shows liked, not disliked. A second Like sends `undo_like`. Without a key, Like sends `like` and the like is stored in `localLikes:v1`.\n(c) If a new search resolves while a Like is in flight, nothing throws, and the grid and `state.rows` (observed through a following click) hold only the new search's rows.</checkpoint>\n<name>Search card controls and Like/Dislike toggles</name>\n<intent>In `pages/search/index.ts`, keyed search cards on every loaded page carry the card actions, and a Like or Dislike click on one toggles that reaction through the reactions API and re-renders the card in place.</intent>\n<clause_1>Every keyed card on the first page and on an appended page has the four `[data-card-action]` controls, and a keyless card has none.</clause_1>\n<clause_2>A Like or Dislike click sends the toggled reaction and re-renders that card in place with the new mark, without throwing when a reset replaced the grid mid-request.</clause_2>\n<files>client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the same search page bundle and fake DOM as phase 2, driven by clicks on the `[data-card-action=\"channel\"]` and `[data-card-action=\"account\"]` buttons. Assertions:\n(a) With a key, Block channel sends `POST /api/profile/blocks` and then a `dislike` reaction, in that order. Every loaded card whose row shares `instance_domain`+`channel_id` is removed from `#search-results`, including cards on page 2. With the sentinel in view, the next page is fetched, which shows that `fillViewport` ran. `#search-status` text is unchanged. Block account does the same, matching on `account_url`.\n(b) When the follow-up `dislike` returns 500, the clicked card's `.card-action-status` reads `Blocked <label>, but the dislike failed: <msg>` and no card is removed.</checkpoint>\n<name>Block removes the source's loaded cards</name>\n<intent>In `pages/search/index.ts`, blocking a channel or account from a search card removes every loaded card of that source, unless the dislike that follows the block fails.</intent>\n<clause_1>A successful block followed by a successful dislike removes every loaded card of that channel or account, refills the viewport and leaves the status text unchanged.</clause_1>\n<clause_2>A block whose dislike fails reports `Blocked <label|action>, but the dislike failed: <msg>` and removes no card.</clause_2>\n<files>client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>Seam: the same search page bundle and fake DOM as phase 2. Assertions:\n(a) With no profile key, clicking Dislike, Block channel and Block account each writes home's exact \"Disliking/Blocking needs a profile. Create one from the Profile button.\" text into the card's `.card-action-status`, and the stub fetch records no request.\n(b) With a key, a Dislike that gets a 400 with \"Dislike limit reached\" puts that message in the status line. The button is enabled again (`disabled` is false), and the card keeps its previous mark, so a second click still sends `dislike`, not `undo_dislike`.\nThen `npx tsc --noEmit` and `npm run build` run in `client/frontend`. `tests/active/test_frontend_reactions.py`, `test_frontend_blocks.py` and `test_frontend_videos_page.py` stay green unchanged, and the new test is promoted to `tests/active/`.</checkpoint>\n<name>No-key guard, failures and dist rebuild</name>\n<intent>In `pages/search/index.ts`, a card action that cannot or does not succeed leaves the card's reaction as it was and explains why in that card's status line.</intent>\n<clause_1>Without a profile key, Dislike, Block channel and Block account each write home's exact profile prompt and send no request.</clause_1>\n<clause_2>A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged.</clause_2>\n<files>client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED), client/frontend/dist/ (REBUILT)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone. Every checkpoint runs offline under node, with a stub fetch. The plan's acceptance reruns need a live Client with a profile key: a keyed rerun of the search showing `reaction: \"disliked\"`, no reaction after undo, and no blocked-channel rows. Those are backend facts already covered by D6 and `_filter_payload`, so they gate no phase. They are an optional manual check for the operator.\n</needs_coordination>\n\n<rationale>\nThe phases follow observable behaviour, smallest first.\n\nP1 is the one-attribute change to the shared component. It has its own seam (`renderVideoCard` called directly, as `test_frontend_reactions.py` already does), and it is the only change home can see (req 9/10), so it lands and is proved separately.\n\nP2 to P4 split `pages/search/index.ts` into three slices that can each be checked on their own:\n- P2 covers rendering and the reversible actions. It also covers the row lookup and the reset-during-action robustness these actions need: the `isConnected` guard and `state.rows` reset sit on the same Like/Dislike path. Reqs 1\u20134 and 8 are met here.\n- P3 covers block-and-remove, the one action that changes the grid. Its two outcomes, removal and a failed follow-up dislike, are its two clauses (req 5, and req 8's untouched counters).\n- P4 covers the paths where an action is refused or fails (reqs 6, 7). The `dist/` rebuild (req 11) goes in P4 as a closing build step, not a clause, because no checkpoint can usefully prove that a bundle was regenerated. `npx tsc --noEmit` is run in every code phase because Vite does not type-check.\n\nSeams: P2 needs a richer fake DOM than `test_frontend_videos_page.py`, because that harness's `closest` returns null. P2 builds it once in the new test file, and P3 and P4 reuse it. This is the only new test infrastructure.\n\nThere is no prose phase. The delivery note about the \"Profile button\" wording on a page that has no Profile button is documentation, so Step 9 handles it.\n\nThe operator approved this breakdown. One caveat: this step's `{principles}`, `{shape_ladder-ladder}` and `{tdd_seams}` placeholders were unfilled, so the seams were chosen from the existing frontend test precedents, not from those documents.\n</rationale>",
    "author:tests/tmp/test_40_search_card_actions_phase1.py": "<assertions>\ntests/tmp/test_40_search_card_actions_phase1.py:65 - control: each of the four renders (reaction \"disliked\", null, \"liked\", omitted; actions true; keyed row) has exactly one `[data-card-action=\"dislike\"]` button, so the C1 assertions read a real button - control\ntests/tmp/test_40_search_card_actions_phase1.py:67 - the Dislike button has aria-pressed == \"true\" when reaction is \"disliked\". Against today's code it reads None, which is the observed red - C1\ntests/tmp/test_40_search_card_actions_phase1.py:68 - the Dislike button has aria-pressed == \"false\" when reaction is null (home's case) - C1\ntests/tmp/test_40_search_card_actions_phase1.py:69 - the Dislike button has aria-pressed == \"false\" when reaction is \"liked\", so a pressed state that tracks any reaction fails - C1\ntests/tmp/test_40_search_card_actions_phase1.py:70 - the Dislike button has aria-pressed == \"false\" when the reaction option is left out entirely (the \"otherwise\" edge) - C1\ntests/tmp/test_40_search_card_actions_phase1.py:71 - control: the Like button still has aria-pressed == \"true\" when reaction is \"liked\" - control\ntests/tmp/test_40_search_card_actions_phase1.py:72 - control: the Like button has aria-pressed == \"false\" when reaction is \"disliked\", so swapping the two buttons' states fails - control\ntests/tmp/test_40_search_card_actions_phase1.py:77 - `npx tsc --noEmit` in client/frontend exits 0 or 2. 2 means it reported diagnostics; any other code means it did not check - control for the type-check clause in the Step 6 seam\ntests/tmp/test_40_search_card_actions_phase1.py:78 - no line of tsc output names src/components/video-card.ts. The operator chose this scoped form over a whole-project pass - Step 6 seam (tsc), scoped per the operator\n</assertions>\n\n<probes>\ntests/tmp/test_probe_40_p1.py (first version), via ValidateTests [\"tests/tmp/test_probe_40_p1.py\", \"-s\"]: I bundled video-card.ts with esbuild (--platform=node, --define:import.meta.env.DEV=false) and rendered row {video_uuid:\"u1\", instance_domain:\"h.example\"} with actions:true. For reaction \"disliked\" and for null it printed the like button with aria-pressed=\"false\" and the dislike button as `<button type=\"button\" class=\"card-action\" data-card-action=\"dislike\" title=\"Dislike\">`, with no aria-pressed. For \"liked\" it printed the like button with aria-pressed=\"true\" and the dislike button again with no aria-pressed. A row with no key rendered no card-action at all (`nokey false`), which is why the test uses a keyed row. Same probe, second version: `npx tsc --noEmit` in client/frontend printed exit code 2 and 37 lines. Every error was in src/pages/channels/index.ts, src/pages/video-page/index.ts or src/pages/videos/index.ts, and there were 0 lines naming video-card. The real checkpoint, via ValidateTests [\"tests/tmp/test_40_search_card_actions_phase1.py\"]: 1 failed, 1 passed. The aria-pressed test fails at line 67 with `assert None == 'true'` after the line-65 control passed. The tsc test passes on the current code. Cleanup: I have no delete tool, so tests/tmp/test_probe_40_p1.py is still on disk and ends in `assert False`; it needs deleting.\n</probes>\n\n<unassertable>\nThe Step 6 seam called for `npx tsc --noEmit` to pass in client/frontend, but a whole-project pass cannot be asserted. It already exits 2 because of 37 lines of errors in three page files this phase does not touch (channels, video-page, videos). I asked, and the operator chose to scope the check: the test asserts tsc runs (exit 0 or 2) and reports no error in src/components/video-card.ts. One other difference: the test is at tests/tmp/test_40_search_card_actions_phase1.py, the path this step names, not the tests/tmp/test_frontend_search_card_actions.py the Intent mentions.\n</unassertable>",
    "self_check:tests/tmp/test_40_search_card_actions_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase1.py:67 \u2014 with `reaction: \"disliked\"`, the `[data-card-action=\"dislike\"]` button's `aria-pressed` attribute is the string \"true\"</assertion>\n<expected>\"true\" \u2014 the same `aria-pressed=\"${boolean}\"` interpolation the Like button already uses, which the probe saw render as 'true' for the liked card's Like button. Under the current code the run shows None (no attribute), `assert None == 'true'` at line 67.</expected>\n<wrong_implementation>The current code: a Dislike button with no `aria-pressed` reads None. It also rules out copying the Like line unchanged (`reaction === \"liked\"`), which reads \"false\" here.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase1.py:68, :69, :70 \u2014 with `reaction: null`, `reaction: \"liked\"`, and no `reaction` key, the Dislike button's `aria-pressed` is the string \"false\"</assertion>\n<expected>\"false\" in all three cases. The probe saw the current code give None for all three (dislike: [None] for null, liked and omitted), so these lines are red as well, behind line 67.</expected>\n<wrong_implementation>An `aria-pressed` written only when the reaction is disliked (`${reaction === \"disliked\" ? ' aria-pressed=\"true\"' : \"\"}`) reads None here. The Like line copied unchanged (`reaction === \"liked\"`) reads \"true\" at line 69. A hard-coded `aria-pressed=\"true\"` reads \"true\" in all three.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 yes, it is all tested. The docstring's first bullet is C1 at four inputs: disliked at line 67, and null, liked and omitted at lines 68\u201370. The second bullet, the scoped `tsc --noEmit` check, is lines 75\u201378. Every claim in the docstring has an assertion.\n2. Absence only \u2014 no. None of the C1 assertions checks for absence. Each one compares against a present string, \"true\" or \"false\". The control at line 65 shows a Dislike button rendered in all four cards before anything is read from it. Line 77 shows tsc actually ran (exit 0 or 2) before line 78 checks that the file has no diagnostics.\n3. Echoed literal \u2014 no. The test never computes `reaction === \"disliked\"` itself. It reads the attribute from HTML that the real module produced in node. Deleting the `aria-pressed` interpolation on the dislike button at video-card.ts line 356 turns lines 67\u201370 red. That is exactly the state of the code now.\n4. One value \u2014 no. C1 is read at four inputs: disliked, null, liked and omitted. Each is a separate render, and none is pinned against a sibling value from the same source. The Like-button lines 71\u201372 are controls only.\n5. The double \u2014 no. Nothing is doubled. esbuild bundles the real `src/components/video-card.ts`, and node runs it.\n6. It collects \u2014 yes. The `--collect-only` summary says \"no tests\" only because the summary counts outcomes. The real run printed \"collected 2 items\", which matches the 2 tests written. Every name binds: `renderVideoCard`, `HTMLParser.handle_starttag`, and `tmp_path`.\n7. Observed, not predicted \u2014 yes, all observed. I ran a probe, tests/tmp/test_probe_40_p1_render.py, which rendered all four cards. Its output: \"PROBE disliked {'like': ['false'], 'dislike': [None], ...}\", \"PROBE null {'like': ['false'], 'dislike': [None], ...}\", \"PROBE liked {'like': ['true'], 'dislike': [None], ...}\", \"PROBE omitted {'like': ['false'], 'dislike': [None], ...}\". So the Like controls at lines 71\u201372 ('true' when liked, 'false' when disliked) are observed. The \"true\"/\"false\" spelling C1 expects is the observed output of the same boolean interpolation. The tsc premise came from the earlier probe tests/tmp/test_probe_40_p1.py: tsc ran, reported errors only in three unrelated page files, and none in video-card. No delete tool is available to me, so both probe files are still in tests/tmp/ for cleanup. Nothing needed rewriting: all of 1\u20137 are clean.\n8. Red, not green \u2014 yes, it fails. ValidateTests on the checkpoint: \"1 failed, 1 passed\", exit status 1. The C1 test fails. The tsc test passes, as expected: it is a supporting check that the change adds no type error, not the phase's claim.\n9. Red for the right reason \u2014 yes. The control at line 65 (one Dislike button per card) passed. The failure is the C1 assertion itself: \"tests/tmp/test_40_search_card_actions_phase1.py:67: AssertionError \u2026 assert None == 'true'\", where the parsed dislike button is {'type': 'button', 'class': 'card-action', 'data-card-action': 'dislike', 'title': 'Dislike'}. It has no `aria-pressed`, because the phase is not built. There was no typo, import, path or harness failure: esbuild bundled and node exited 0 (line 58 passed).\n10. Observed expected output \u2014 yes. The run shows None where both rows expect a value, which is the unimplemented state. The probe saw None for null, liked and omitted too, so lines 68\u201370 are also red behind line 67. The expected \"true\"/\"false\" strings match how the Like button's identical interpolation was seen to render. Nothing the run showed contradicts a row.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### client/frontend/src/components/video-card.ts\nIn `renderVideoCard`, the Dislike action button (`data-card-action=\"dislike\"`) now has `aria-pressed=\"${reaction === \"disliked\"}\"`, which follows how the Like button already does it. It renders `\"true\"` when `options.reaction` is `\"disliked\"` and `\"false\"` in every other case: `null`, `\"liked\"`, or the option left out. `reaction` already falls back to `null`, so the attribute is always present. No other markup changed.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone. One note: the phase's file list names `tests/tmp/test_frontend_search_card_actions.py (NEW)`, but the gating checkpoint is `tests/tmp/test_40_search_card_actions_phase1.py`, and that already exists. I did not create the listed file because the checkpoint covers this phase. If the build expects that path to exist, it is still missing.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_40_search_card_actions_phase2.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"C2f\">\n<disposition>fixed</disposition>\n<what>The reset test is now parametrized over `(\"action\", \"mark\")`, with values `(\"like\", LIKED)` and `(\"dislike\", DISLIKED)`, and is renamed `test_a_like_or_dislike_resolving_after_a_new_search_replaced_the_grid_leaves_the_new_cards_and_rows_alone`. The runner reads the reaction from a new `ACTION` env, which `_run(..., action=)` passes through. It uses that reaction for the held click (:224) and for the following click (:235). This means the Dislike case holds a `dislike` response while the second search replaces the grid. In that case :357 (`errors == []`) and :358 (the clicked card's status line is `\"\"`) carry \"a Dislike does not throw\". The control at :354 shows the card is detached when the Dislike resolves, and the control at :351 shows the Dislike was sent and its response was held. The wrong implementation this excludes is a page that guards the Like branch with `card.isConnected` but sets `card.outerHTML` unguarded in the Dislike branch. I observed it in a probe bundle (plan draft with only the Dislike guard removed): the `[dislike]` case failed at :358 with status \"NoModificationAllowedError: This element has no parent node.\", and the `[like]` case passed. The docstring bullet now says \"a Like, or in a second run a Dislike\" and \"sends `like` or `dislike`, not the `undo_like` or `undo_dislike`\", so it matches what the test asserts.</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim CRITICAL 1 (whole-claim: the reset scenario clicks only Like, so C2f is uncarried): the reset test is now parametrized over Like and Dislike. In the `[dislike]` case, :357 and :358 assert that no error escaped and the clicked card's status is empty after a Dislike held across a reset. A probe showed a Dislike-branch-only missing guard fails `[dislike]` at :358 while `[like]` passes, and the reverse mutant fails only `[like]`. Recommendations 1\u20133 were not taken: they do not block, and the refused-request and no-profile-Dislike cases are phase 4's checkpoint.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase2.py:306 \u2014 every keyed card on page 1 and on the appended page 2 has exactly the [data-card-action] buttons like, dislike, channel, account. Also :307 \u2014 the keyless card on each page has none. The keyless-visitor render at :332 and the fresh-search render at :349 (both parametrized cases) show the same.</assertion>\n<expected>{a1, a2, b1, b2 keys: [\"like\",\"dislike\",\"channel\",\"account\"]} at :306; [[], []] for k1 and k2 at :307.</expected>\n<wrong_implementation>The current page (renderRows with no `actions`): every list reads [] and the test fails at :306, observed. A page that passes `actions` only on the reset path leaves b1 and b2 with [] at :306. A page that draws controls on keyless rows gives a non-empty list at :307.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase2.py:316 \u2014 each of Dislike, Dislike, Dislike, Like, Like on page-2 card b2 sends one POST /api/user-action with that click's toggled action and b2's uuid and host. :318 \u2014 after each click the card shows the new mark (stat active + aria-pressed). :319 \u2014 the redrawn card keeps its four controls. :321 and :322 \u2014 card order is unchanged and no other card changes (in place). :335, :336 and :337 \u2014 a keyless Like sends `like`, is stored in localLikes:v1 and shows liked. :357 and :358 in both the `[like]` and `[dislike]` cases of the reset test \u2014 after a Like or a Dislike whose response resolved after a new search detached the card, no error escaped and the clicked card's status line is \"\". :360 and :361 \u2014 the new grid is the second search's cards, all unmarked. :363 and :364 \u2014 the following same-reaction click sends `like`/`dislike` and the card shows LIKED/DISLIKED.</assertion>\n<expected>Toggle actions: dislike, undo_dislike, dislike, like, undo_like. Marks: DISLIKED, NEUTRAL, DISLIKED, LIKED, NEUTRAL. Grid order and the other cards are unchanged. Reset case, for each of like and dislike: errors [], status \"\", afterRelease c1/a2/c2 all NEUTRAL, next sent [like] or [dislike] with mark LIKED or DISLIKED (observed under the plan's draft bundle).</expected>\n<wrong_implementation>An always-`dislike` Dislike fails :316 at step 2. A Like that sends `undo_like` on a disliked card fails :316 at step 4. Sending without redrawing keeps the old mark and fails :318. A redraw that appends the card moves it and fails :321. A Dislike branch that sets `card.outerHTML` without an `isConnected` guard, while the Like branch has one, fails `[dislike]` at :358 with status \"NoModificationAllowedError: This element has no parent node.\" (observed; `[like]` passes). The mirror mutant fails only `[like]` at :358 (observed). A reset that does not clear `state.rows` makes the next click send `undo_like` or `undo_dislike` and fails :363 in both cases (observed).</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Each negative assertion has a positive control. :357 and :358 (no error, empty status) are armed by :351, which shows the reaction was sent and is still held, and by :354, which shows the card is detached when it resolves. The probe confirmed that removing either branch's guard turns :358 red for its own case. :361 (all unmarked) sits next to :363 and :364, which show the next click sends and marks. :307 is armed by :306 and :304.\n2. No. Expected actions and marks are literal toggles (`_sent(action, shared)`, LIKED/DISLIKED). Nothing is computed by reproducing production logic. Deleting the `isConnected` guard on the Dislike branch turns `[dislike]`:358 red. Deleting `state.rows = []` in loadPage's reset turns :363 red in both cases.\n3. No. The reset path is now read for both members of the {Like, Dislike} set. The paged toggle is read across five steps that cover every transition.\n4. No. Fetch, IntersectionObserver and the DOM are stubbed at the browser boundary. The project's own modules (video-card, reactions, user-actions, search data) are bundled in for real.\n5. Yes, it collects. `_run` gained an `action` keyword with a default, so the paged and keyless callers are unchanged. The parametrize names match the function parameters. Running the file collects 4 tests (2 + the 2 reset cases), as written.\n6. Yes, every expected value comes from a run. The new `[dislike]` values (held sent [dislike], heldOpen 1, clicked {connected false, status \"\"}, afterRelease all NEUTRAL, next sent [dislike] with marks (False,'false',True,'true')) were observed in a probe that bundled the plan's draft into a symlinked copy of src. The same probe ran the current page and three mutants. The probe file is now emptied with a delete-me note. Still not observed, as in the previous round: whether a real browser throws on outerHTML of a detached element. Running `document.createElement(\"div\").outerHTML = \"<p>\"` in Chrome would confirm it.\n7. Yes, it is still red for its own reason. Against the current tree there are 4 failures: paged at :306, keyless at :332, and both reset cases at :349. All are the C1 controls-missing assertion, because renderRows passes no `actions`. Under the plan's draft, both reset cases pass.\n</answers>",
    "self_check:tests/tmp/test_40_search_card_actions_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_40_search_card_actions_phase2.py:306 \u2014 after page 1 and the observer-appended page 2, with a key, every keyed card's `[data-card-action]` list maps to [\"like\",\"dislike\",\"channel\",\"account\"]</assertion>\n<expected>{a1, a2, b1, b2 keys: [\"like\",\"dislike\",\"channel\",\"account\"]}. The probe saw this list on a real `renderVideoCard(row, {actions: true})` card parsed by the fake DOM. The run as it stands shows [] for all four.</expected>\n<wrong_implementation>The current renderRows never passes `actions: true`, so every list reads [] (seen in the run). A page that passes actions only on the reset/innerHTML path leaves b1 and b2 at [] and fails the same way.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_40_search_card_actions_phase2.py:307 \u2014 the keyless card on page 1 and the one on page 2 both have empty action lists</assertion>\n<expected>[[], []]. The probe saw a keyless row rendered with actions:true give actions [] and key null.</expected>\n<wrong_implementation>A page that adds its own buttons around every card, or keys cards by title, reads a non-empty list for k1/k2.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_40_search_card_actions_phase2.py:332 \u2014 without a profile key, the grid reads [(a1 key, ACTIONS), (None, []), (a2 key, ACTIONS)]</assertion>\n<expected>Keyed cards have the four controls and the keyless card has none. The run as it stands shows [] for a1 and a2.</expected>\n<wrong_implementation>A page that sets `actions` only when `getProfileKey()` is set reads [] for a1 and a2.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_40_search_card_actions_phase2.py:348 \u2014 the first search's reset-rendered grid reads [(a1,ACTIONS),(a2,ACTIONS),(a3,ACTIONS)]</assertion>\n<expected>All three cards carry the four controls. The run as it stands shows [] for each.</expected>\n<wrong_implementation>A page that passes actions only on the append (insertAdjacentHTML) path reads [] here.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_40_search_card_actions_phase2.py:316 \u2014 each of Dislike, Dislike, Dislike, Like, Like on page-2 card b2 sends exactly one POST /api/user-action with that step's action for uuid-b2@peer.example</assertion>\n<expected>dislike, undo_dislike, dislike, like, undo_like, one request per click. The probe saw the request shape {method POST, action, uuid, host} come from the real sendReaction.</expected>\n<wrong_implementation>A port of the videos page's handler always sends `dislike` for Dislike, which reads dislike at step 2 instead of undo_dislike. A Like toggle that checks only `liked` sends undo_like on a disliked card. A handler that does nothing sends [].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_40_search_card_actions_phase2.py:318 \u2014 after each click the card's (likesActive, likePressed, dislikesActive, dislikePressed) equals DISLIKED, NEUTRAL, DISLIKED, LIKED, NEUTRAL in turn</assertion>\n<expected>(False,\"false\",True,\"true\") \u2192 (False,\"false\",False,\"false\") \u2192 DISLIKED \u2192 (True,\"true\",False,\"false\") \u2192 NEUTRAL. The probe saw exactly these tuples for real cards rendered with reaction disliked, null and liked.</expected>\n<wrong_implementation>A page that sends but does not redraw keeps NEUTRAL after step 1. One that does not update row.reaction redraws the stale mark. One that removes the card on Dislike, as the videos page does, gives card None.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_40_search_card_actions_phase2.py:319 \u2014 after each click the redrawn card still has [\"like\",\"dislike\",\"channel\",\"account\"]</assertion>\n<expected>ACTIONS on every step</expected>\n<wrong_implementation>A redraw through renderVideoCard without `actions: true` reads [].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_40_search_card_actions_phase2.py:321 and :322 \u2014 after each click the grid's key order is unchanged, and every card other than b2 equals its pre-click state</assertion>\n<expected>The same 6-key order as the initial grid, and the other five card states are identical to `others`.</expected>\n<wrong_implementation>A redraw that re-renders the whole grid from page 1 rows only drops the page-2 cards. Appending the new card instead of replacing it moves b2 to the end. Removing on dislike shortens the list.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_40_search_card_actions_phase2.py:335, :336, :337 \u2014 without a key, Like on a1 sends `like`, localLikes:v1 becomes [{video_uuid:\"uuid-a1\", instance_domain:\"peer.example\"}], and the card reads LIKED</assertion>\n<expected>[POST like uuid-a1@peer.example]; the stored JSON is exactly that one entry; marks (True,\"true\",False,\"false\"). The probe saw sendReaction without a key store `[{\"video_uuid\":\"uuid-n\",\"instance_domain\":\"peer.example\"}]` and cardReaction then return \"liked\".</expected>\n<wrong_implementation>A page that asks for a profile before any action sends [] and stores null. One that redraws from row.reaction instead of cardReaction shows NEUTRAL without a key.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_40_search_card_actions_phase2.py:356 and :357 \u2014 once the held Like resolves after a new search replaced the grid, no error is recorded and the clicked (detached) card's status text is \"\"</assertion>\n<expected>errors == [] and status == \"\". The probe saw that setting outerHTML on a detached card throws \"NoModificationAllowedError: This element has no parent node.\", and that the real card's status span reads \"\".</expected>\n<wrong_implementation>The videos page's `card.outerHTML = \u2026` without an isConnected check throws. Its catch then writes that message into the status line (status != \"\"), or the error escapes (errors non-empty).</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_40_search_card_actions_phase2.py:359 and :360 \u2014 after the release, the grid still holds c1, a2, c2 of the second search, all NEUTRAL</assertion>\n<expected>[c1, a2, c2] keys, all (False,\"false\",False,\"false\")</expected>\n<wrong_implementation>A redraw that looks the card up again by key in the live grid repaints the second search's a2 as LIKED.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_40_search_card_actions_phase2.py:362 and :363 \u2014 a following Like on a2 in the new grid sends `like` and the card reads LIKED</assertion>\n<expected>[POST like uuid-a2@peer.example], marks LIKED</expected>\n<wrong_implementation>A row list the reset did not clear still holds the first search's a2, marked liked by the late response. The lookup finds that row first and sends undo_like, and the card reads NEUTRAL.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, so I rewrote it. The C1 assertions read only the keyed visitor's grid in test 1. I added C1 assertions at :332 (keyless visitor, keyed and keyless cards) and :348 (the reset-rendered first search), and extended the docstring bullets to match. Second pass: every docstring bullet and every C2 sub-claim (sends the toggled reaction, redraws in place with the new mark, no throw when a reset replaced the grid) now has an assertion.\n2. Absence only: no. The negatives are errors == [] (:323, :338, :356), clicked status == \"\" (:357), and the keyless cards' [] lists (:307). Each has a positive control. Before :356/:357, the Like is shown to have left and been held (:350, heldOpen == 1) and the clicked card is shown detached (:353). The status span exists (status is \"\" not None; the probe saw \"\" on a real card). :307 sits next to :306, which requires the keyed cards on the same pages to have ACTIONS.\n3. Echoed literal: no. Expected values are literal tuples (NEUTRAL/LIKED/DISLIKED) and request dicts built from the row fixtures. The test performs no transformation production does. These deletions turn it red: the `actions: true` the phase adds to renderRows (:306/:332/:348); the redraw `card.outerHTML = \u2026` (:318); the toggle choice of undo_dislike/undo_like (:316); the isConnected guard (:356/:357); clearing the row list on reset (:362).\n4. One value: no. C1 is read on page 1 and page 2, with and without a key, on reset and append renders, and on keyed and keyless rows. C2 is read across five successive clicks with different start states, a keyless Like, and the reset race. The marks are compared against literal constants, not against a sibling from the same source.\n5. The double: no. fetch, IntersectionObserver, localStorage and the DOM are browser/network layers. The real search page, video-card, reactions, local-likes, user-actions and search data modules are all bundled by esbuild and run unmodified.\n6. It collects: yes, every import and name resolves. The pasted --collect-only text said \"no tests\", but my ValidateTests runs collected 3 items (\"collected 3 items\", FFF), which matches the three tests written. The helpers read only keys the runner emits (searches, grid, steps, storedBefore, like, stored, firstGrid, held, heldOpen, beforeRelease, afterRelease, clicked, next, errors).\n7. Observed, not predicted: these now come from a run. I wrote tests/tmp/probe_search_harness.py, which loads the test's own fake DOM prelude and a bundle of the real renderVideoCard/sendReaction/cardReaction. It showed: the cardState of real actions:true cards for reactions null/liked/disliked (exactly the NEUTRAL/LIKED/DISLIKED tuples); a keyless row giving actions [] and key null; the like button containing SVG>PATH (the click target); a click on the path bubbling to closest(\"[data-card-action]\") = \"dislike\"; a detached card reporting isConnected false and outerHTML throwing \"NoModificationAllowedError: This element has no parent node.\"; the status span reading \"\"; the keyless like storing [{\"video_uuid\":\"uuid-n\",\"instance_domain\":\"peer.example\"}] with cardReaction then \"liked\"; and the request shape POST /api/user-action {action, uuid, host}. The page-load controls (searches and the key/title grid at :303-:304) passed in the run. I have no delete tool, so I emptied the probe to zero bytes instead of removing it; someone should delete the file.\n8. Red, not green: yes. `ValidateTests tests/tmp/test_40_search_card_actions_phase2.py` printed \"3 failed\", [exit status 1].\n9. Red for the right reason: yes, after a rewrite. In the first run, tests 2 and 3 failed on CONTROL assertions. Test 2 failed at :331 `page[\"like\"][\"pressed\"] is True` (\"assert False is True\"). Test 3 failed at :347 on the held-Like control (sent [] vs [like]). Both are the case where nothing gets measured. I put the phase's C1 claim ahead of those controls. Re-run: test 1 fails at :306 (C1), \"{'peer.example::uuid-a1': []} != {'peer.example::uuid-a1': ['like', 'dislike', 'channel', 'account']}\" for a1, a2, b1, b2. Test 2 fails at :332 (C1), \"At index 0 diff: ('peer.example::uuid-a1', []) != ('peer.example::uuid-a1', ['like', 'dislike', 'channel', 'account'])\". Test 3 fails at :348 (C1), the same index-0 diff. In every case the controls ahead of it passed, including searches and grid keys/titles at :303-:304. The cause is the unbuilt phase: renderRows passes no `actions`. The C2 assertions are not reached until C1 holds, so I armed their premises with the probe in 7.\n10. Observed expected output: the C1 rows' expected lists are the ones the probe read off real actions:true cards; the run shows [] in their place under the current code, as the wrong_implementation columns say. The C2 rows' mark tuples, request shapes, localLikes JSON and detached-outerHTML behaviour are the values the probe printed. Nothing in the run contradicted a row.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### client/frontend/src/pages/search/index.ts\n- **Docstring.** One paragraph added: each card carries Like, Dislike, Block channel and Block account, and unlike home, Dislike toggles and the card stays marked, because search is not filtered by dislikes (D6). The sentence about blocks removing cards is left for phase 3, which adds that behaviour.\n- **Imports.** `resolveInstanceDomain`, `resolveVideoId` and `resolveVideoKey` now come from `../../components/video-card` (the import became a multi-line list, as the file already does for `data/search`), and `sendReaction` from `../../data/reactions`. `getProfileKey` and `blockVideoSource` are not imported yet; phases 3 and 4 need them.\n- **`state.rows`.** A new field, `rows: [] as VideoRow[]`, holds the rendered rows in order so a card action can find its row by video key. It is cleared in `loadPage`'s `if (reset)` block, which covers a new search, a sort change, popstate, the first load and the key-rejected retry. It is also cleared in `showIdle`.\n- **`renderRows`.** It now maps through the new `renderSearchCard` on both the reset path and the append path, and adds the page's rows to `state.rows`. It still runs only after the `seq` check, so a stale response adds no rows.\n- **`renderSearchCard(row)`.** New. It returns `renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true })`. The first render and every in-place re-render use it, so they cannot drift apart.\n- **Click handler.** One click listener on `#search-results`, copied from home's: from the clicked element up to the `[data-card-action]` button, then the `.video-card`, then `dataset.videoKey`, then `state.rows.find` by `resolveVideoKey`. If any step finds nothing, the click does nothing.\n- **`runCardAction(button, card, row)`.** New, modelled on home's. It disables the button and clears the card's status line.\n  - **Like** sends `undo_like` if `cardReaction(row) === \"liked\"`, otherwise `like`.\n  - **Dislike** sends `undo_dislike` if `cardReaction(row) === \"disliked\"`, otherwise `dislike`.\n  - Either way it then sets `row.reaction`, and replaces `card.outerHTML` with `renderSearchCard(row)` only if `card.isConnected`. Setting `outerHTML` on a card that a reset has detached would throw.\n  - A thrown error goes to the card's status line (fallback `\"Action failed\"`), and `finally` re-enables the button.\n  - There is no branch yet for `channel` and `account`, so clicking those buttons sends nothing until phase 3. The no-key guard comes in phase 4.\n\n**Not run:** I have not run the checkpoint; the workflow runs it on hand-in. What I did run was a type check: `tsc --noEmit` in `client/frontend` reports no error in `src/pages/search/index.ts`. Its only errors are in three files already broken before this build (`channels`, `video-page`, `videos`).\n\n**Leftover file:** that type check was a throwaway probe, `tests/tmp/test_probe_40_p2_impl.py`. My tools cannot delete files, so it is still there and can be deleted.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone. The phase also lists `tests/tmp/test_frontend_search_card_actions.py (EDITED)`, but that file does not exist. The checkpoint gating this phase is `tests/tmp/test_40_search_card_actions_phase2.py` (phase 1 had the same mismatch), so I did not create it.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_40_search_card_actions_phase3.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D5\">\n<disposition>justified</disposition>\n<what>I narrowed the docstring to what the test actually asserts. Line 3 used to end \"so a page fetched after the click was asked for by the page itself once the cards were gone.\" It now ends \"so a page fetched after the click was asked for by the page itself; nothing here shows whether that fetch came before or after the cards were removed.\" The fake sentinel reports itself in view because of the click, not because of what the grid holds, so the test cannot show the refill came after the removal. The docstring no longer claims it does. What :290 does carry stays in the docstring: the page-3 GET happened and the page sent it itself (C1d/D4). No assertion changed.</what>\n</item>\n</items>\n\n<findings_addressed>\nNeither auditor raised a CRITICAL. I took claim Recommendation 2 (D5) by narrowing the docstring sentence on line 3, as described in the D5 item. I did not take Recommendations 1, 3 and 4: none of them blocks, and the ledger does not name them.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:290 \u2014 the requests sent after the click, in order: POST /api/profile/blocks {kind, uuid, host}, then POST /api/user-action dislike for that video, then GET search page 3</assertion>\n<expected>[[\"POST\",\"/api/profile/blocks\",{\"kind\":kind,\"uuid\":\"uuid-a1\",\"host\":\"peer.example\"}],[\"POST\",\"/api/user-action\",{\"action\":\"dislike\",\"uuid\":\"uuid-a1\",\"host\":\"peer.example\"}],[\"GET\",\"/api/v1/search/videos\",\"music\",\"3\"]]</expected>\n<wrong_implementation>A page with no fillViewport() after the removal has no page-3 GET in its calls (seen in the no_fill probe). A page that skips the dislike, or sends it before the block, gives the wrong sequence. The current page with no Block branch sends [].</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:292 \u2014 the titles left in the grid after the removal</assertion>\n<expected>channel: [\"video a2\",\"video k1\",\"video a3\",\"video b2\"]; account: [\"video k1\",\"video a3\",\"video b2\"]</expected>\n<wrong_implementation>Removing only the clicked card leaves b1 and k2 in the grid. Matching on channel_id without instance_domain also removes a3. Matching a channel block on account removes a2. Matching an account block on channel keeps a2.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:294 \u2014 #search-status after the removal and the empty page-3 refill</assertion>\n<expected>\"Showing 7 of 9 matched videos.\"</expected>\n<wrong_implementation>Recounting the status from the cards left reads \"Showing 4 of 9 matched videos.\" (channel) and \"Showing 3 of 9 matched videos.\" (account), both seen in the recount probe. Writing the block result into #search-status also changes the text.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:304 \u2014 the clicked card's .card-action-status text when the dislike answers 500</assertion>\n<expected>channel with label \"Alice's channel\": \"Blocked Alice's channel, but the dislike failed: reaction store unavailable\"; account with empty label: \"Blocked account, but the dislike failed: reaction store unavailable\"</expected>\n<wrong_implementation>Showing only the dislike error, showing nothing (the current page reads \"\"), showing a generic message in place of the server's error, or rendering \"Blocked , but the dislike failed: ...\" when the label is empty.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:308 \u2014 the grid after the failed dislike, armed by :306, which shows the block and the failing dislike were both sent</assertion>\n<expected>[\"video a1\",\"video a2\",\"video k1\",\"video a3\",\"video b1\",\"video b2\",\"video k2\"]</expected>\n<wrong_implementation>Removing the source's cards whatever the dislike returned leaves the channel-block grid as [a2,k1,a3,b2] and the account-block grid as [k1,a3,b2].</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every negative check has a positive control. :308 (nothing removed) is armed by :306, which shows the block and the failing dislike were both sent, and by _control_before, which shows all 7 cards were loaded and the button was there. If the code under test is deleted, :290 and :304 go red.\n2. No. Every expected value is a fixture literal or an observed output; the test never computes production's result itself. Deleting the Block branch in runCardAction turns :290 and :304 red. Deleting the row filter turns :292 red. Deleting the fillViewport() call turns :290 red.\n3. No. The removal is checked for both kinds, with cards that differ on domain, channel and account (a2, a3, b1, k2). The failure message is checked with a label and without one. One gap remains: each kind is tested with only one label state (claim Recommendation 1). It does not block, and I did not take it.\n4. No. The fetch, the DOM and IntersectionObserver are doubles for browser and network layers. pages/search/index.ts and video-card.ts are bundled and run for real.\n5. Yes, it collects. My only edit is to the docstring, so imports, names and helpers are unchanged. There are still 4 parametrised cases.\n6. Yes. The expected values were seen in the earlier ValidateTests runs: the control values against the current page, and the grid, status, calls and cardStatus against the reference probe copies. This round adds no new expected value.\n7. Yes. Before this edit the whole file ran 4 failed: every case got past the before-click controls and failed on its first clause assertion with after.calls == [] / cardStatus == \"\", because the Block branch is missing. The only change since then is to docstring text, so that failure still stands. I did not re-run it.\nNo rewrite was needed.\n</answers>",
    "self_check:tests/tmp/test_40_search_card_actions_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:290 \u2014 after the click on Block channel/account of card a1, the requests sent are exactly POST /api/profile/blocks {kind, uuid-a1, peer.example}, then POST /api/user-action {dislike, uuid-a1, peer.example}, then GET /api/v1/search/videos q=music page=3</assertion>\n<expected>[[\"POST\",\"/api/profile/blocks\",{\"kind\":kind,\"uuid\":\"uuid-a1\",\"host\":\"peer.example\"}],[\"POST\",\"/api/user-action\",{\"action\":\"dislike\",\"uuid\":\"uuid-a1\",\"host\":\"peer.example\"}],[\"GET\",\"/api/v1/search/videos\",\"music\",\"3\"]]. In the current run it reads [], because the click sends nothing yet.</expected>\n<wrong_implementation>No Block branch in the click handler: reads [] (seen in this run). Block with no dislike, or the dislike sent first: the sequence is short or out of order. Removal with no refill check: page 3 is missing even though the sentinel is in view. The run showed that turning the sentinel visible does not fetch page 3 by itself.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:292 \u2014 the grid titles after the block are the loaded cards not of that source, in order</assertion>\n<expected>channel: [\"video a2\",\"video k1\",\"video a3\",\"video b2\"]; account: [\"video k1\",\"video a3\",\"video b2\"]. In the current run all 7 titles are still there.</expected>\n<wrong_implementation>Removing only the clicked card keeps b1 and k2. Matching on channel_id alone also drops a3 (other.example, channel 7). Using the wrong field for the kind keeps a2 under account, or drops it under channel. Skipping keyless cards keeps k2.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:294 \u2014 #search-status after the block and the empty page-3 refill</assertion>\n<expected>\"Showing 7 of 9 matched videos.\", the value observed before the click in this run (control at _control_before)</expected>\n<wrong_implementation>Recounting the status from the cards left gives \"Showing 4 of 9\u2026\" or \"Showing 3 of 9\u2026\". Writing a block message into the status line replaces the text. Lines 290 and 292 above show the block path ran, so this check cannot pass because nothing happened.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:295 \u2014 no listener threw and no rejection went unhandled</assertion>\n<expected>[]</expected>\n<wrong_implementation>Rendering into a removed card through outerHTML throws NoModificationAllowedError in the fake DOM, as Chromium does. A refill that awaits a rejected promise records an unhandled rejection.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:304 \u2014 the clicked card's .card-action-status text when the dislike returns 500</assertion>\n<expected>\"Blocked Alice's channel, but the dislike failed: reaction store unavailable\" (label given); \"Blocked account, but the dislike failed: reaction store unavailable\" (empty label). In the current run it reads \"\".</expected>\n<wrong_implementation>Reporting only the dislike error gives \"reaction store unavailable\". Reporting nothing gives \"\" (this run). Using the empty label as-is gives \"Blocked , but\u2026\". Treating the 500 as a block failure gives a different message.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:308 \u2014 the grid after the failed dislike, which line 306 shows was sent after an accepted block</assertion>\n<expected>[\"video a1\",\"video a2\",\"video k1\",\"video a3\",\"video b1\",\"video b2\",\"video k2\"]</expected>\n<wrong_implementation>Removing the source's cards whatever the dislike returned leaves 4 cards (channel) or 3 (account). Removing only the clicked card drops \"video a1\".</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase3.py:309 \u2014 no listener threw and no rejection went unhandled on the failure path</assertion>\n<expected>[]</expected>\n<wrong_implementation>Letting the dislike's error escape the click handler, instead of writing it on the card, shows up as an unhandled rejection or uncaught exception here.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes for C1 and C2. C1: removal by channel or account, including page-2 and keyless cards (292); the refill, as a page-3 fetch that only the page itself can trigger after the click (290); the status left unchanged (294). C2: the message, including the empty-label fallback to the action name (304); no card removed (308).\n2. Absence only: the first draft had a problem, now fixed. The \"control\" request-sequence assertion came before the C2 message assertion, so it was the line that failed and the judging assertions were never reached. I moved the message assertion (304) first. The grid-unchanged assertion (308) is negative, and two positive checks arm it: the message at 304 and the block-then-dislike sequence at 306. The C1 status-unchanged (294) and errors == [] (295) are armed by the calls and grid changes at 290 and 292.\n3. Echoed literal: no. Every expected value is a fixture literal or a spec template filled with fixture inputs. Deleting the Block branch in the click handler turns 290, 292 and 304 red; deleting the dislike-failure message turns 304 red; deleting the source filter turns 292 red.\n4. One value: no. Two kinds (channel, account) for the success path, a labelled and an empty label for the failure path, and decoy rows that discriminate the match fields (a2 same account and other channel, a3 same channel_id on another instance, k1 unrelated keyless, k2 keyless of the source, b1/b2 on page 2).\n5. The double: no owned module is doubled. The DOM, fetch, IntersectionObserver and storage are browser/network layers. pages/search/index.ts and its imports are bundled and run for real.\n6. It collects: yes. The provided --collect-only summary printed \"no tests\", but the actual run reports \"collected 4 items\" and runs all 4 (2 kinds \u00d7 2 tests). The imports resolve and the bundle builds (search_bundle fixture, esbuild exit 0).\n7. Observed, not predicted: the before-state values are observed from the run: both page fetches, all 7 titles, STATUS \"Showing 7 of 9 matched videos.\", pressed True, and cardStatus \"\". Also observed: putting the sentinel in view without a working block fetches nothing (after.calls == []), so a page-3 fetch can only come from the block path. The after-state values for the unbuilt phase come from the must_prove clauses; they cannot be observed until the phase exists.\n8. Red, not green: yes. The ValidateTests run on the rewritten file exited 1 with \"4 failed\".\n9. Red for the right reason: yes. The success tests fail at line 290 (C1 carrier), `assert [] == [['POST', '/a...'music', '3']]`, \"Right contains 3 more items, first extra item: ['POST', '/api/profile/blocks', {'kind': 'channel', ...}]\", because the click sends nothing. The failure tests fail at line 304 (C2 carrier), `assert '' == 'Blocked Alic...e unavailable'` and `assert '' == 'Blocked acco...e unavailable'`. All _control_before assertions passed (calls, grid, status, pressed). No control failed after the reorder; before it, line 304 was the control and failed on calls == [].\n10. Observed expected output: the run agrees with every row's current reading: calls [], grid unchanged, cardStatus \"\", status \"Showing 7 of 9 matched videos.\", errors []. No row's expected value is contradicted by what the run showed. The post-phase values are stated as the clause requires.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `client/frontend/src/pages/search/index.ts`\n- Imports `blockVideoSource` from `../../data/blocks`.\n- `runCardAction` now handles the `channel` and `account` actions, the same way the home feed (`pages/videos/index.ts`) does. It calls `blockVideoSource(apiBase, action, uuid, host)` and then sends a `dislike` for the video.\n  - **Dislike fails:** the card's `.card-action-status` reads `Blocked <block.label || action>, but the dislike failed: <message>`, and the handler returns without touching the grid (C2).\n  - **Dislike succeeds:** a channel block matches rows on `instance_domain` + `channel_id`, and an account block matches on `account_url`. The matching rows go through `removeRows` (C1).\n  - **Block request fails:** the existing catch shows its error on the card.\n- New `removeRows(match)`:\n  - It filters `state.rows`, redraws the grid from the rows that are left, and calls `fillViewport()` to fetch the next page if the end of the results is now on screen.\n  - The redraw is done from `state.rows` rather than by deleting nodes, because keyless cards have no `data-video-key` but still have to go when their source matches.\n  - `state.loadedRows` is deliberately left alone, so `Showing N of M` and the `hasMore` paging check keep counting what the Engine returned.\n- Updated the doc comment on `runCardAction` to cover blocking.\n\n### `tests/tmp/test_frontend_search_card_actions.py`\nNot touched. This file is on the phase's files list but doesn't exist in the worktree. No change in this phase needed it.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_40_search_card_actions_phase4.py": "<items>\n<item id=\"C2e\">\n<disposition>fixed</disposition>\n<what>The rejected scenario is now parametrized over the action as well as the starting reaction: like, dislike, channel and account, each on a neutral card and on a liked one, so 8 cases. Each action is rejected with the Client backend's own body for that action: Like gets 404 \"Video not found in Engine\" (server.py:794), Dislike gets 400 \"Dislike limit reached (1000)\" (:816), and a Block gets 400 \"Block limit reached (1000)\" (:992). To make that possible the runner's stub now answers `/api/profile/blocks` as well as `/api/user-action` with ACTION_STATUS/ACTION_ERROR, holds whichever of the two comes first, and presses `process.env.ACTION` instead of a hard-coded \"dislike\". The three facts are carried for every action. :326 checks that the card status equals that action's error, which excludes a generic or missing message on any path. :328 checks the clicked button's `disabled` is false; :321 shows it was true while the response was held. Together they exclude a Like or Block path that only re-enables on success. :330 checks the mark is unchanged, which excludes an optimistic like or dislike redraw. :324 checks the card is still on the grid, which excludes a Block that removes the source's cards before it is accepted. :333 checks what a following Dislike then Like send: `dislike` then `like` from neutral, `dislike` then `undo_like` from liked. That excludes any optimistic change to `row.reaction` on any action's path. Probe runs against mutants: an optimistic like fails at :333 in both like cases, an optimistic like redraw fails at :326, a block that flips the row to disliked first fails at :333 in all four block cases, a block that removes rows first fails at :324 in all four, no re-enable fails at :328 in all 8, and a generic message fails at :326 in all 8. The test name became `test_a_rejected_card_action_shows_the_error_re_enables_the_button_and_keeps_the_reaction`. Its second docstring bullet now names all four actions and their errors.</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim CRITICAL 1 (whole-claim, :209 rejected scenario only presses dislike): fixed. The runner presses `process.env.ACTION`, the stub rejects both the reaction route and the block route, and the test is parametrized over like/dislike/channel/account \u00d7 neutral/liked. That puts all four members of the set under :324/:326/:328/:330/:333. Mutant probes confirm Like-path and Block-path wrong implementations now fail.\nClaim RECOMMENDATION 1 (C2d misses a liked row cleared to null): taken. After the rejection the test now presses Dislike and then Like, and :333 requires the Like to send `undo_like` from a liked card. A mutant that sets `row.reaction = null` in the catch passed before. It now fails at :333 in all four liked cases and still passes the neutral ones, which is correct.\nClaim RECOMMENDATION 2 (empty or malformed stored key): not taken. C1 is about the absent-key path that home guards. How an empty string or a malformed key should behave is not a clause of this phase.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase4.py:294 \u2014 for each of dislike, channel and account with no profile key, the click adds no request to the stub's log. Also :296 \u2014 the clicked card's `.card-action-status` equals home's exact prompt. The control at :298 shows the stub records a keyless Like in the same run.</assertion>\n<expected>:294 `[]`. :296 \"Disliking needs a profile. Create one from the Profile button.\" for dislike, and \"Blocking needs a profile. Create one from the Profile button.\" for channel and account.</expected>\n<wrong_implementation>The current unguarded page sends `[\"POST\",\"/api/user-action\",{\"action\":\"dislike\",...}]` for dislike and `[\"POST\",\"/api/profile/blocks\",{\"kind\":...}]` plus the follow-up dislike for a block, and fails :294 in all three cases (observed). A guard on Dislike only fails the channel and account cases at :294. One prompt hard-coded for every action, or the server's error shown instead, fails :296.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase4.py:324/:326/:328/:330/:333/:334, over like/dislike/channel/account \u00d7 neutral/liked, after that action's request is rejected. :324 the card is still on the grid. :326 the status line equals the action's error. :328 the clicked button is enabled; :321 shows it was disabled while held. :330 the card's like/dislike marks are as they were. :333 a following Dislike then Like send `dislike` then `like` (neutral) or `dislike` then `undo_like` (liked). :334 no error escapes.</assertion>\n<expected>Status \"Video not found in Engine\" for like, \"Dislike limit reached (1000)\" for dislike, \"Block limit reached (1000)\" for channel and account. `disabled` False. Marks NEUTRAL or LIKED as the run started. :333 gives `[[dislike],[like]]` from neutral and `[[dislike],[undo_like]]` from liked.</expected>\n<wrong_implementation>Each observed with a mutant probe. Setting `row.reaction` before the like request fails :333 in both like cases. Redrawing the like before the request fails :326, because the redraw wipes the status. Flipping the row to disliked before a block fails :333 in all block cases. Removing the source's rows before the block is accepted fails :324. Dropping the re-enable in `finally` fails :328 in all 8 cases. A generic \"Action failed\" fails :326 in all 8. Clearing a liked row to null on rejection fails :333 in the liked cases. Setting the row to disliked before the dislike request fails :333.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The only negative, :294, is paired with :296 (prompt written) and :298 (the stub records a keyless Like). :324 is a presence check, not an absence.\n2. No. The error texts go into the stub's response body and come back through `sendUserAction`/`blocks.request` and the catch at index.ts:290. Deleting that `say(error.message)` turns :326 red, which the \"generic\" mutant confirmed. The expected first request at :313 is chosen from the parametrize literals and only feeds the control at :320. It does not reproduce the C2 behaviour.\n3. No. C2's observables are read across 4 actions \u00d7 2 starting reactions with three distinct error texts. C1 is read across 3 actions with two distinct prompts.\n4. No. The doubles are fetch at the network edge and a fake DOM. pages/search/index.ts and every data module it imports (reactions, user-actions, blocks, profile) run for real from the esbuild bundle.\n5. Yes. The run collected 11 items: 3 C1 cases and 8 C2 cases. All names bind: `_blocked`, BLOCK_LIMIT_ERROR, NOT_FOUND_ERROR, and the runner env ACTION/ACTION_STATUS/ACTION_ERROR.\n6. Yes. I ran the test on the current tree: the C1 cases fail at :294, and all 8 C2 cases pass. Their request shapes come from that run: the held block request has the `/api/profile/blocks` body `{kind, uuid, host}`. I also ran the probe with ten mutants (results under C2 in rows). The error strings come from the backend source (server.py:794/:816/:992) and are fed in by the stub. That they show up in the status line was observed.\n7. Yes. C1 is still red only at :294, because the page has no key guard: the keyless dislike and block are sent. With home's guard spliced in, all 11 pass. As before, C2 passes on the current tree because the catch/finally path already holds, so for this phase it guards against regression. Housekeeping: I had no delete tool, so tests/tmp/test_probe_40_p4.py (rewritten for this round) and the earlier test_probe_40_* files are still on disk and need removing.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_40_search_card_actions_phase4.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase4.py:288 \u2014 `page[\"prompt\"][\"sent\"] == []`: with no profile key, the Dislike / Block channel / Block account click (one per parametrized case) adds no request to the stub fetch's record.</assertion>\n<expected>`[]` for all three actions. This was observed under the probe's \"guarded\" mutant (index.ts with a `!getProfileKey()` guard ahead of `button.disabled = true`), where all three C1 cases pass.</expected>\n<wrong_implementation>The current index.ts has no key guard. The run observed one extra request for each case: `['POST', '/api/user-action', {'action': 'dislike', 'uuid': 'uuid-a1', 'host': 'peer.example'}]` for dislike, and `['POST', '/api/profile/blocks', {'kind': 'channel'|'account', 'uuid': 'uuid-a1', 'host': 'peer.example'}]` for the two blocks. A page that guards only Dislike still sends the two block requests, so the channel and account cases fail.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_40_search_card_actions_phase4.py:290 \u2014 `page[\"prompt\"][\"card\"][\"status\"] == prompt`: the clicked card's `.card-action-status` text equals home's exact prompt (videos/index.ts:409). That is \"Disliking needs a profile. Create one from the Profile button.\" for dislike and \"Blocking needs a profile. Create one from the Profile button.\" for both blocks.</assertion>\n<expected>The exact prompt string for each action. All three cases pass this line under the probe's \"guarded\" mutant. Against the current code the line is not reached, because :288 fails first.</expected>\n<wrong_implementation>A page that sends the request leaves the status empty (the stub answers 200) or shows the server's error. A page using the video page's wording (\"...from the Profile button on the home page.\") shows a different string. A page that guards but writes nothing leaves `\"\"`. I did not run a mutant for the wording or empty-status cases; the string comparison is what excludes them.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase4.py:311 \u2014 `page[\"rejected\"][\"card\"][\"status\"] == LIMIT_ERROR`: after the held 400 is released, the card's status line reads \"Dislike limit reached (1000)\".</assertion>\n<expected>\"Dislike limit reached (1000)\", for both the neutral card and the liked card. Observed in the run: both C2 cases pass.</expected>\n<wrong_implementation>Observed in the probe: the \"generic\" mutant (`say(\"Action failed\")`) fails at :311 in both cases. The \"optimistic_redraw\" mutant (row set and card redrawn before the request) also fails at :311, because say() writes into the detached old status element and the new card's status stays empty.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase4.py:313 \u2014 `page[\"rejected\"][\"disabled\"] is False`: the clicked Dislike button is enabled again once the rejection lands. The control at :308 showed it was `True` while the response was held.</assertion>\n<expected>`False`, for both cases. Observed in the run: both pass.</expected>\n<wrong_implementation>Observed in the probe: the \"no_reenable\" mutant (empty `finally`, so the button is re-enabled only on success) fails at :313 in both cases.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase4.py:315 \u2014 `_marks(page[\"rejected\"][\"card\"]) == mark`: after the rejection, the card's (likes active, like aria-pressed, dislikes active, dislike aria-pressed) equals the mark it had before the click.</assertion>\n<expected>`(False, \"false\", False, \"false\")` for the neutral card and `(True, \"true\", False, \"false\")` for the liked card. Observed in the run: both pass.</expected>\n<wrong_implementation>Observed in the probe: the \"optimistic_mark\" mutant (toggles `.stat.dislikes` active before the request and never takes it back) fails at :315 in both cases, because the dislikes stat reads active.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_40_search_card_actions_phase4.py:318 \u2014 `page[\"again\"][\"sent\"] == [_sent(\"dislike\", target)]`: a second Dislike on the same card after the rejection sends `dislike`, not `undo_dislike`. That shows the row's reaction was not left as disliked. :319 adds that no listener threw.</assertion>\n<expected>`[[\"POST\", \"/api/user-action\", {\"action\": \"dislike\", \"uuid\": \"uuid-a1\", \"host\": \"peer.example\"}]]`, for both cases. Observed in the run: both pass.</expected>\n<wrong_implementation>Observed in the probe: the \"optimistic\" mutant (`row.reaction = \"disliked\"` set before `await sendReaction`, with no redraw) passes :311-:315 but fails at :318 in both cases, because the second click sends `undo_dislike`.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. C1 runs once per action (dislike, channel, account), and each run checks both \"sends nothing\" (:288) and \"exact home prompt\" (:290). The prompt strings match home's videos/index.ts:409 character for character. C2's three parts are each asserted: error message (:311), button re-enabled (:313), reaction unchanged (:315 mark, :318 the next click sends `dislike`). C2 says \"a rejected card-action request\", but the test drives only a rejected Dislike. That is the scope plan 20-40 Phase 4 checkpoint (b) sets, and every action shares the same catch/finally in runCardAction (index.ts:289-293). Fix: the comments at :314 and :316 named wrong implementations the run contradicted. The optimistic row-set mutant passes :315 and fails at :318, and the redraw-before-request mutant fails at :311. I rewrote both comments to name the mutants that actually fail on those lines (optimistic_mark at :315, optimistic row.reaction at :318).\n2. Absence only: no. :288 (`sent == []`) is armed in the same run by :292, a keyless Like that is sent and recorded. :285 shows the click landed on a real button. :313 (`disabled is False`) is armed by :308, which showed `True` while the response was held.\n3. Echoed literal: no. Deleting `button.disabled = false` (index.ts:292) turns :313 red. Replacing the `error.message` in index.ts:290 turns :311 red. Moving `row.reaction = ...` (index.ts:268) ahead of the await turns :318 red. All three were observed by mutants in tests/tmp/test_probe_40_p4.py. C1's carrier is the guard this phase adds, and a page without it is red now.\n4. One value: no. C1 runs over three actions. C2 runs over two starting marks (neutral and liked), so \"keeps the mark\" cannot pass by always showing neutral.\n5. The double: no. Only the browser layer is stood in for: a fake DOM, storage, IntersectionObserver and a stub fetch at the HTTP boundary. The project's own index.ts, data/profile and sendReaction/blockVideoSource are bundled and run for real by esbuild.\n6. It collects: yes. The `--collect-only` summary printed \"no tests\", but the actual run printed \"collected 5 items\" (3 C1 parametrizations + 2 C2), which is what I wrote. Every name binds and the run reached the assertions.\n7. Observed, not predicted: yes. Every expected value comes from a run. Marks, request shapes and the C1 failures come from the checkpoint run. Pass under a guard, and which line each wrong implementation fails on, come from tests/tmp/test_probe_40_p4.py. That probe bundles mutants of index.ts from stdin, so the source is untouched, and runs the checkpoint's own test functions. Observed per mutant: current C1 FAIL :288 / C2 pass; guarded all pass; optimistic C2 FAIL :318; optimistic_redraw C2 FAIL :311; optimistic_mark C2 FAIL :315; no_reenable C2 FAIL :313; generic C2 FAIL :311. I kept the probe because it is the mutant evidence for the auditors.\n8. Red, not green: yes, it is red. ValidateTests after the edit: \"3 failed, 2 passed\", [exit status 1]. Disclosure: the two C2 cases pass against the code as it stands. Phase 3's runCardAction already has the catch/finally that shows the error and re-enables the button, and it sets row.reaction only after the request succeeds. So C2 is already true. Its assertions guard against a regression rather than prove phase 4 built it. The mutants above show each C2 assertion discriminates. The red that gates this phase is C1, the phase's new no-key guard.\n9. Red for the right reason: yes. All three failures are the C1 assertion `tests/tmp/test_40_search_card_actions_phase4.py:288: AssertionError`, `assert page[\"prompt\"][\"sent\"] == []`. \"Left contains one more item\": `['POST', '/api/user-action', {'action': 'dislike', 'uuid': 'uuid-a1', 'host': 'peer.example'}]` for dislike, and `['POST', '/api/profile/blocks', {'kind': 'channel'|'account', 'uuid': 'uuid-a1', 'host': 'peer.example'}]` for the blocks, with errors `[]`. The controls at :283-:285 passed: page 1 fetched, four controls, neutral mark, button pressed. So the failure is the missing key guard, not the harness.\n10. Observed expected output: yes. The run's messages agree with each row's expected value: the C1 sends at :288, and the C2 values passing at :311/:313/:315/:318 for both marks. Where the run disagreed with me, on which line the optimistic mutants fail, I corrected the comments to the observed lines and re-ran: still \"3 failed, 2 passed\", exit 1, with the same :288 failures.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:4": "<changes>\n### client/frontend/src/pages/search/index.ts\n- `runCardAction` now starts with home's no-key guard, word for word. If there is no profile key, Dislike, Block channel and Block account write `Disliking needs a profile. Create one from the Profile button.` or `Blocking needs a profile. Create one from the Profile button.` into the card's `.card-action-status`. They then return before the button is disabled and before any request is sent. Like is not guarded, as on home.\n- `getProfileKey` is now imported next to `ProfileKeyRejectedError` from `../../data/profile`.\n- C2 needed no new code. The existing order already covers it: send the request, set `row.reaction` and redraw only after it resolves, show `error.message` in the `catch`, and set `button.disabled = false` in the `finally`. A rejected request leaves the row's reaction alone. A block that fails never reaches `removeRows`, so the card stays on the grid.\n\n### client/frontend/dist/\nNot rebuilt in this turn because I have no shell. The operator chose to rebuild it by hand with `cd client/frontend && npm run build`. The checkpoint bundles from `src` and never reads `dist`, so it does not wait on the rebuild. Until the rebuild is done, the served `dist/assets/search-*.js` lacks this guard and the phase-3 card actions.\n\n### tests/tmp/test_frontend_search_card_actions.py\nNot touched. It does not exist in the worktree, and the phase-4 checkpoint covers both clauses.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nclient/frontend/src/pages/search/index.ts \u2014 in `runCardAction`, renamed the local `status` (the card's `.card-action-status` element) to `cardStatus`. It was shadowing the module-level `status` (`#search-status`) that `setStatus` writes to. Behaviour is unchanged: the only uses are the declaration and the `say` closure, and grep shows no other `status` reference inside the function.\n</refactors>\n\n<left_out>\nMerging the like and dislike branches in `runCardAction` into one toggle branch: the two branches copy home's structure in `pages/videos/index.ts` line for line, and the merge would build the action as `undo_${action}`, which has to type-check against `ReactionAction`. I have not run tsc to confirm that, so I left it. Pulling the parts shared with home's `runCardAction` (the no-key guard, the `say` helper, the block-follow-up dislike and the channel/account match predicate) into a shared module: that would touch `pages/videos/index.ts` and add a new file, both outside this build's files. It is a candidate for its own issue. video-card.ts: phase 1 only added the Dislike `aria-pressed` attribute, which matches the Like button and needed no refactor. The older duplication in `videoPageUrl` (channel label resolution, `resolveVideoId` order) and the unused `replace` argument of `pushUrl` were there before this build, so I left them alone. client/frontend/dist/ was not rebuilt (I have no shell); `cd client/frontend && npm run build` is still owed. tests/tmp/test_probe_40_p2_impl.py from phase 2 is still there and should be deleted. The pass rules slot in the step prompt came through as a literal `{rat_tail_rules}` placeholder. I worked to the role's rat-tail rule instead: this build makes no deliberate simplifications, so no `rat-tail:` comment is owed.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nRead against the code, the four phases' changes are already minimal and follow home's card-action pattern; the only safe refactor in scope was removing a variable that shadowed the module-level `status`. I have not run the checkpoints or tsc after the rename; the workflow's run will confirm it.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"client/frontend/README.md\" update=\"yes\">\nThe \"What it does\" list has no bullet on the card action buttons for either grid; line 16 only covers the reaction marks. Add a bullet after line 16 that describes what was delivered. Home feed and search cards with a video key carry Like, Dislike, Block channel and Block account. Like works without a profile key. Dislike and the Block buttons need one, and without it they write \"Disliking/Blocking needs a profile. Create one from the Profile button.\" into the card's status line and send no request. On home, Dislike or Block removes the affected cards and there is no undo. On search, Dislike toggles between `dislike` and `undo_dislike` and the card stays on the page, marked, because search is not filtered by dislikes; a like replaces a dislike and a dislike replaces a like. A Block on search removes every loaded card from that channel (`instance_domain` + `channel_id`) or account (`account_url`) and fetches the next page if the grid has become too short. \"Showing N of M matched videos.\" keeps counting fetched rows. If the dislike that follows a block fails, the card says so and no cards are removed. A failed action, a rejected profile key included, shows its message in that card's status line and the button is re-enabled. Like and Dislike both carry `aria-pressed`.\n</doc>\n<doc path=\"docs/project/roadmap.md\" update=\"yes\">\nF13-M2 (line 54) still reads as fully open. Its feed-grid and search-grid parts are now in the tree, so reword it to leave only the channels-page block controls open. Add a Delivered entry (section starting at line 7) that names issue `40` and plan `20-40-search-card-actions` at its archive path, `docs/project/plans/archive/20-40-search-card-actions.md`, for the search-grid controls (Like, Dislike toggle, Block channel/account). Also note that the feed-grid controls were already present with no Delivered entry; the delivering change could not be traced from the docs.\n</doc>\n<doc path=\"docs/project/issues/40-search-card-actions.md\" update=\"yes\">\nSet the Status line to `Status: enhancement, complete`. Append a comment that names the delivering plan `20-40-search-card-actions` and records two things. First, a rejected profile key during a card action shows as that card's status-line message, not `keyRejectedNotice`, and the data layer was left unchanged; this is the operator's decision and overrides the brief's Errors bullet at line 40. Second, the no-key prompt keeps home's exact \"Create one from the Profile button.\" wording even though search.html has no Profile button. Then move the file to `docs/project/issues/archive/`.\n</doc>\n<doc path=\"docs/project/plans/20-40-search-card-actions.md\" update=\"yes\">\nThe workflow re-renders its Impacts and Documentation sections from the run state, so it needs no hand edits; its header says manual edits are overwritten. On delivery, move it to `docs/project/plans/archive/` (issue-tracker.md line 29) so the roadmap's Delivered entry and the issue comment point at the archived path.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:client/frontend/README.md": "<changes>\nAdded two \"What it does\" bullets on the card action buttons (Like, Dislike, Block channel, Block account) on home feed and search cards.\n\n- **First bullet (shared by both grids):**\n  - Which cards get the buttons: those with a video key.\n  - `aria-pressed` on Like and Dislike.\n  - Like works without a profile key and toggles between `like` and `undo_like`.\n  - Dislike and both Block buttons need a key. Without one they send no request and show home's exact \"Disliking/Blocking needs a profile. Create one from the Profile button.\" text.\n  - A Block also dislikes the video. If that dislike fails, the card says \"Blocked \u2026, but the dislike failed: \u2026\" and no cards are removed. Otherwise the block removes every loaded card from the channel (`instance_domain` + `channel_id`) or account (`account_url`).\n  - A failed action, including a rejected profile key, shows its message in that card's status line, and the button is disabled while the request runs and re-enabled after.\n- **Second bullet (how the two pages differ):**\n  - On home, Dislike removes the card and has no undo.\n  - On search, Dislike toggles between `dislike` and `undo_dislike` and the card stays marked, because search is not filtered by dislikes. A like replaces a dislike and the reverse.\n  - After a search block removes cards, the next page is fetched if the end of the results is now on screen.\n  - \"Showing N of M matched videos.\" keeps counting fetched rows, removed ones included.\n\nI checked every claim against `pages/search/index.ts` (`runCardAction`, `removeRows`, `renderSearchCard`), `pages/videos/index.ts` (`runCardAction`, `removeRows`) and `components/video-card.ts` (lines 355\u2013356). For what each reaction mark looks like, the bullets rely on the reaction-display bullet that comes before them. Roadmap and issue status are left to their own documents.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/roadmap.md": "<changes>\nAdded a Delivered entry for the F13-M2 search card controls (issue `40`) and cut F13-M2 down to the channels-page block controls.\n\n- **Delivered:** a new F13-M2 entry under issue `40` (Like, Dislike, Block channel, Block account on search cards). It says that on search, Dislike toggles and the card stays, and that a block removes the source's loaded cards. For the behaviour details it points to `client/frontend/README.md` instead of repeating them, and it links the plan at its archive path, `docs/project/plans/archive/20-40-search-card-actions.md`. It also says the home feed card controls were already in the tree and that the docs don't record which change delivered them.\n- **M2, F13-M2:** now reads \"Block controls on the channels page. Card controls on the feed and search grids (issue `40`) are delivered.\" I removed the plan 07 clause (\"puts them only on the video page and in the profile modal\"); it described the gap the feed and search controls have now filled.\n- **Checked against the code:** `pages/search/index.ts` and `pages/videos/index.ts` both render cards with `actions: true` and call `blockVideoSource`. `video-card.ts` sets `aria-pressed` on both Like and Dislike. `pages/channels` has no block code, so the channels-page part is still open.\n- **Path the entry depends on:** the plan is still at `docs/project/plans/20-40-search-card-actions.md` until its own checklist item moves it to `archive/`. The link only works once that move is done.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/40-search-card-actions.md": "<changes>\nClosed issue 40 as delivered: set the Status line to `enhancement, complete`, added a delivery comment and wrote the file to `docs/project/issues/archive/`, but the original is still in `issues/` and has to be deleted by hand.\n\n- **Status line:** `Status: enhancement, ready-for-agent` is now `Status: enhancement, complete`.\n- **Delivery comment:** added under `## Comments` after the triage decisions. It uses the same \"**Delivered** by `<archived plan path>`\" form as the other archived issues and names `docs/project/plans/archive/20-40-search-card-actions.md`. For what the card controls do, it points to `client/frontend/README.md` instead of repeating it. It records two things:\n  - **Rejected profile key:** a key rejected during a card action shows as a message in that card's status line. It does not trigger `keyRejectedNotice`, and the data layer was not changed. This is marked as the operator's decision, overriding the brief's Errors bullet. I checked the code: the `catch` in `runCardAction` writes `error.message` to the card status (`pages/search/index.ts:294`). `ProfileKeyRejectedError` is only handled for search reads (line 192).\n  - **No-key prompt:** it uses home's exact \"Create one from the Profile button.\" wording, even though `search.html` has no Profile button. I checked the code: the wording is at line 257, and only `index.html` and `videos.html` have `#show-profile-header`.\n- **Brief and acceptance criteria:** left as written, because they record what was asked for.\n- **Move to archive:** I wrote the full updated file to `docs/project/issues/archive/40-search-card-actions.md`. My tools cannot delete files, so `docs/project/issues/40-search-card-actions.md` still exists, unedited, and needs to be deleted to finish the move.\n- **`dist/` rebuild:** done. The served `dist/assets/search-DE7Xdm7K.js` contains the no-key prompt.\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/archive/40-search-card-actions.md: new file, the archive location the checklist moves this issue to (issue-tracker.md line 21). docs/project/issues/40-search-card-actions.md: still needs deleting to finish the move; my tools can't delete files.\n</not_on_checklist>",
    "step_9_i2_update:docs/project/plans/20-40-search-card-actions.md": "<changes>\nI made no edit to the plan's content, and I could not move the file: it is still at `docs/project/plans/20-40-search-card-actions.md` and needs a `git mv` into `docs/project/plans/archive/`.\n\n**Content.** The file's header says the `dev-flow` workflow re-renders it from the run state and overwrites any manual edit. The checklist entry also says it needs no hand edits. I changed nothing in its text.\n\n**Why it isn't moved.** I can write files but cannot delete or move them, and I have no shell. If I wrote a copy under `archive/`, there would be two plan files, and the copy would go stale the next time the workflow re-renders the original.\n\n**The move, for whoever holds a shell (the harvester turn or you).** Move the plan and its record together, because every archived plan sits next to its `.record.md` (for example `22-36-nsfw-filter.md` and `22-36-nsfw-filter.record.md`):\n\n```\ngit mv docs/project/plans/20-40-search-card-actions.md docs/project/plans/archive/20-40-search-card-actions.md\ngit mv docs/project/plans/20-40-search-card-actions.record.md docs/project/plans/archive/20-40-search-card-actions.record.md\n```\n\n**Do it as the last step.** Once moved, the roadmap's Delivered entry and the issue 40 comment point at the right path, `docs/project/plans/archive/20-40-search-card-actions.md`. But if the workflow re-renders the plan after the move, it will write a new file at the old path. So move it after the workflow's final render.\n\n**One leftover after the move.** The header line names the record at `docs/project/plans/20-40-search-card-actions.record.md`. The workflow writes that line, so after the move it only gets fixed by a final re-render, or by a hand edit once the workflow is done with the file.\n</changes>\n\n<not_on_checklist>\ndocs/project/plans/20-40-search-card-actions.record.md \u2014 I did not touch it. It has to go to `docs/project/plans/archive/` together with the plan, as every archived plan has its record beside it, but the checklist does not list it.\n</not_on_checklist>"
  },
  "requirements": "### Purpose\n\nAn operator reported: \"blocks and likes and such do not work on the video cards in search\". Home feed cards have Like, Dislike, Block channel and Block account controls. Search result cards have none, so a visitor has to open the video page to react to or block a search result. This build gives search cards the same four controls and finishes the search-grid half of roadmap item F13-M2 (\"Block controls on video cards (feed and search grids) and on the channels page\"). The feed-grid half is already in the tree. The issue is `docs/project/issues/40-search-card-actions.md`.\n\n### Current state (verified in the tree)\n\n- `client/frontend/src/components/video-card.ts`: `renderVideoCard(row, options)` draws `.card-actions` only when `options.actions` is true and the row has a video key (`resolveVideoKey` = `host::id`). The block holds buttons with `data-card-action` = `like`, `dislike`, `channel`, `account` and a `<span class=\"card-action-status\" role=\"status\">`. The Like button has `aria-pressed=\"${reaction === \"liked\"}\"`. The Dislike button has no `aria-pressed`. The card root is `<article class=\"video-card [liked|disliked]\" data-video-key=\"...\">`, and the disliked mark is the `stat dislikes active` class plus a visually-hidden \"You disliked this\".\n- `client/frontend/src/pages/search/index.ts`: `renderRows` calls `renderVideoCard(row, { apiParam, reaction: cardReaction(row) })` with no `actions` and keeps no array of loaded rows. `#search-results` has no click handler. Paging is page-numbered (`state.page`, `PAGE_SIZE = 24`). `state.loadedRows` counts fetched rows, and both `hasMore` and the \"Showing N of M matched videos.\" status use it. `fillViewport()` fetches more while the sentinel is in view. `ProfileKeyRejectedError` from `fetchSearchResults` replaces the grid with `keyRejectedNotice`.\n- `client/frontend/src/pages/videos/index.ts` (home): a delegated click handler on `#video-cards` finds the row in `state.sample` by `data-video-key` and calls `runCardAction(button, card, row)`. That function shows `\"<Disliking|Blocking> needs a profile. Create one from the Profile button.\"` when a non-like action has no key. It disables the button while running and clears the status line. Like sends `undo_like` or `like` depending on `cardReaction(row) === \"liked\"`, sets `row.reaction`, and replaces `card.outerHTML`. Dislike sends `dislike` and removes the row. Block calls `blockVideoSource`, then `sendReaction(\"dislike\")`. If the dislike fails it says `Blocked <label|action>, but the dislike failed: <message>` and removes nothing; otherwise it removes rows matching `instance_domain`+`channel_id` (channel) or `account_url` (account). Any error goes to the status line, and the button is re-enabled in `finally`.\n- `client/frontend/src/data/reactions.ts`: `sendReaction(apiBase, action, { uuid, host })` supports `like`, `undo_like`, `dislike`, `undo_dislike`, and without a key records local likes and un-likes. `cardReaction(row)` returns `row.reaction` with a key, and the local-like state without one.\n- `client/frontend/src/data/blocks.ts`: `blockVideoSource(apiBase, kind, uuid, host)` returns a `Block` with `kind`, `instance_domain`, `channel_id`, `account_url` and `label`.\n- `sendUserAction` and the blocks `request` throw a plain `Error` on any non-OK status, 401 included. Neither throws `ProfileKeyRejectedError`.\n- Client backend `_filter_payload` (`client/backend/server.py`) filters blocked rows out of each Engine page after the Engine has paged and marks `reaction`. Search is never filtered by dislikes (plan 08, D6). Because filtering happens per page, a block never shifts later page numbers.\n\n### Functional requirements\n\n1. **Controls rendered.** The search page passes `actions: true` to `renderVideoCard` for every row, on the first page and on every appended page. Every search card with a video key shows Like, Dislike, Block channel, Block account and the `.card-action-status` line. A card without a video key shows none, as on home.\n2. **Row lookup.** The search page keeps the rows it has rendered, in order, in page state. A reset (new search, sort change, popstate, retry after key rejection, idle) clears them. One delegated click listener on `#search-results` resolves `[data-card-action]` \u2192 closest `.video-card` \u2192 `data-video-key` \u2192 the stored row, matching by `resolveVideoKey`, the way home does. A click that resolves no row does nothing.\n3. **Like.** It works with or without a profile key. If `cardReaction(row) === \"liked\"` it sends `undo_like` and the row's reaction becomes `null`. Otherwise it sends `like` and the reaction becomes `\"liked\"`, which also covers a disliked card: the like replaces the dislike. The card is re-rendered in place through the same `renderVideoCard` options search uses (`apiParam`, `reaction: cardReaction(row)`, `actions: true`) and stays on the page.\n4. **Dislike (search only: toggle, card stays).** It needs a profile key. If `cardReaction(row) === \"disliked\"` it sends `undo_dislike` and the reaction becomes `null`. Otherwise it sends `dislike` and the reaction becomes `\"disliked\"`, which also covers a liked card: the dislike replaces the like. The card is re-rendered in place and stays. A disliked card shows the disliked mark and its Dislike button has `aria-pressed=\"true\"`. A neutral or liked card's Dislike button has `aria-pressed=\"false\"`.\n5. **Block channel / Block account.** It needs a profile key and matches home. Call `blockVideoSource(apiBase, \"channel\"|\"account\", uuid, host)`, then `sendReaction(apiBase, \"dislike\", { uuid, host })`. If the dislike fails, the status line reads `Blocked <block.label || action>, but the dislike failed: <message>` and no cards are removed. Otherwise every loaded search row and card is removed where `instance_domain` + `channel_id` equal the block's (channel), or where `account_url` equals the block's (account).\n6. **No profile key.** Dislike, Block channel and Block account write the same text home writes, `\"Disliking needs a profile. Create one from the Profile button.\"` or `\"Blocking needs a profile. Create one from the Profile button.\"`, into that card's status line and send no request.\n7. **Errors.** The button is disabled while its action runs and re-enabled afterwards, whether the action succeeded or failed. A failed request writes its `Error.message` (fallback `\"Action failed\"`) into that card's status line. **Operator decision:** a rejected profile key during a card action goes the same way, as a status-line message like home's. It does not replace the grid with `keyRejectedNotice`, and the data layer (`user-actions.ts`, `blocks.ts`, `reactions.ts`) is not changed to throw `ProfileKeyRejectedError`. The search page's existing `ProfileKeyRejectedError` handling for search reads is unchanged.\n8. **Paging after actions.** Infinite scroll keeps working after any action, and cards appended by later pages carry the controls and are clickable. `state.page`, `state.loadedRows`, `hasMore` and the \"Showing N of M matched videos.\" status keep counting fetched rows, not rows still on screen. **Deliberate simplification:** after a block the count may overstate what is visible. Paging is still correct because the Client filters per Engine page, so page numbers do not shift. The upgrade path, if wanted later, is a separate visible-count. After a block removes cards, the page calls `fillViewport()` so a grid that became too short fetches the next page.\n9. **Shared markup change.** The Dislike button in `renderVideoCard`'s action markup gets `aria-pressed=\"${reaction === \"disliked\"}\"`, mirroring Like. That is the only change to the shared component's output.\n10. **Home unchanged.** Home's dislike still removes the card and has no undo. Home's block still removes the matching cards. Home's like, no-key prompt and error handling stay as they are. Any helper shared between the two pages must keep that behaviour exactly. Mirroring home's handler inside the search page is acceptable, and so is extracting a shared helper, provided home's behaviour is unchanged.\n11. **Build.** `dist/` is rebuilt with `npm run build` in `client/frontend` so the served bundle carries the change.\n\n### Acceptance criteria\n\n- A search results page renders Like, Dislike, Block channel and Block account buttons on every card that has a video key, including cards loaded by later pages.\n- With a profile key, Dislike on a search card sends `dislike`. The card stays on the page with the disliked mark and a Dislike button with `aria-pressed=\"true\"`. Rerunning the same search shows the video still present with `reaction: \"disliked\"`.\n- Dislike on a disliked search card sends `undo_dislike`. The card shows no mark, and a rerun of the search carries no `reaction` on that row.\n- Like on a search card toggles between `like` and `undo_like`. A like on a disliked card leaves it marked liked, not disliked.\n- Block channel on a search card removes every loaded card of that channel, and the video is disliked. A rerun of the same search contains no row from that channel. Block account does the same by `account_url`.\n- Without a profile key, Dislike and the two Block buttons show the profile prompt in the card's status line and send no request.\n- A failed action shows its message in that card's status line and the button is re-enabled.\n- Home feed card behaviour is unchanged: dislike and block still remove cards, and home has no undo-dislike.\n- `dist/` is rebuilt (`npm run build`) so the served bundle carries the change.\n\n### Out of scope\n\n- Filtering search results by dislikes (D6 stands).\n- Follow controls on any card.\n- Action controls on the video page's similar/up-next cards, the likes page or the channels page.\n- Changing home feed card behaviour, beyond the pressed state on its Dislike button.\n- Any Client backend or Engine change, or any change to the frontend data layer's error types.\n\n### Baseline suite state\n\nThe pre-build suite exited 0 (variant: false): 1 of 46 test groups selected (`test_search_fusion.py`, 10 passed). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`. The existing frontend tests touching this area are `tests/active/test_frontend_blocks.py` and `tests/active/test_frontend_reactions.py`.",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe change touches two source files and then a rebuild. `pages/search/index.ts` gets its own card-action handler, written to match home's. `components/video-card.ts` gets one attribute.\n\nI read the tree to confirm the premises. Search rows from `engine/server/data/search.py` carry `channel_id` and `account_url`, so block matching can use the same fields home uses. `sendReaction`, `blockVideoSource` and `sendUserAction` all pass their `apiBase` argument through `resolveClientApiBase`, so search can pass `apiParam ?? \"\"`, the same way it already calls `importLocalLikes`. `videos.css`, where `.card-actions` is styled, is already imported by the search page, so no CSS work is needed.\n\n1. **Controls rendered (req 1).** One small search-page function renders a row with `apiParam`, `reaction: cardReaction(row)` and `actions: true`. It is search's version of home's `renderFeedCard`. `renderRows` uses it for both the first page and appended pages, so every keyed card gets the controls and keyless cards still get none.\n2. **Row lookup (req 2).** Page state gains a `rows` array. `renderRows` appends each page's rows to it in order. Every reset path empties it: `loadPage(..., reset=true)` covers new search, sort change, popstate and the retry from `keyRejectedNotice`, and `showIdle` covers idle. One delegated `click` listener on `#search-results` does what home's listener on `#video-cards` does: `closest(\"[data-card-action]\")`, then `closest(\".video-card\")`, then `dataset.videoKey`, then `state.rows.find` by `resolveVideoKey`. If any step finds nothing, the click does nothing. Because the listener sits on the container, cards appended by later pages are clickable without extra wiring (req 8).\n3. **Action runner (reqs 3\u20137).** A search-page `runCardAction(button, card, row)` takes uuid and host from `resolveVideoId` and `resolveInstanceDomain`, as home does.\n   - **No key (req 6):** if the action is not `like` and `getProfileKey()` is empty, it writes home's exact \"Disliking/Blocking needs a profile. Create one from the Profile button.\" text into the card's status line and returns without a request.\n   - **Running:** it disables the button and clears the status line.\n   - **Like (req 3):** sends `undo_like` if `cardReaction(row) === \"liked\"`, otherwise `like`. It sets `row.reaction` to `null` or `\"liked\"` and replaces `card.outerHTML` with the search render. With no key, `sendReaction` has already updated the local likes, so `cardReaction` reads them correctly. With a key, the server's rule that a like and a dislike replace each other makes `\"liked\"` right for a card that was disliked.\n   - **Dislike (req 4):** sends `undo_dislike` if `cardReaction(row) === \"disliked\"`, otherwise `dislike`. It sets `row.reaction` to `null` or `\"disliked\"` and re-renders the card in place.\n   - **Block (req 5):** calls `blockVideoSource`, then `sendReaction(\"dislike\")` with the same promise-to-message handling home uses. If the dislike failed, the status line reads `Blocked <label|action>, but the dislike failed: <msg>` and nothing is removed.\n   - **Errors (req 7):** any thrown error writes `error.message`, or \"Action failed\", into the status line. A `finally` re-enables the button. No `ProfileKeyRejectedError` path is added, which is the operator's decision.\n4. **Removal after a block (reqs 5, 8).** A search-page `removeRows(match)` filters `state.rows`. It removes from the grid each child `.video-card` whose `dataset.videoKey` belongs to a removed row; it walks the children and compares the dataset values, so no selector escaping is needed. It then calls `fillViewport()`. It does not touch `state.page`, `state.loadedRows`, `hasMore` or the status text, so those keep counting fetched rows, as the requirement's deliberate simplification states.\n5. **Shared markup (req 9).** The Dislike button in `renderVideoCard` gains `aria-pressed=\"${reaction === \"disliked\"}\"`, written the same way as Like's. Nothing else in the component changes.\n6. **Home unchanged (req 10).** Home's code is not edited. Its only visible difference is the new `aria-pressed=\"false\"` on its Dislike button. Home never shows a disliked card, because its dislike removes the card and the feed filters dislikes.\n7. **Build (req 11).** Run `npm run build` in `client/frontend` so `dist/` carries the change.\n\n### Alternatives considered\n\n- **A shared `runCardAction` helper extracted from home, with callbacks for re-rendering, removing rows and choosing dislike mode.** Rejected. The two pages' dislike behaviour differs in the important way: home removes the card with no undo, while search toggles and keeps the card. A shared helper would therefore need a mode switch or a strategy callback just to serve two callers. It would also mean editing home's working handler, and home must stay exactly as it is. Mirroring costs about 45 lines in one file and carries no risk to home. The duplication is deliberate: a third page that needs card actions is the point to extract a helper.\n- **Re-render the whole search grid from `state.rows` after a removal, the way home's `removeRows` calls `renderCards(true)`.** Rejected. It would wipe other cards' status lines and the keyboard focus, and repaint up to N\u00d724 cards to remove a handful. Removing the matching DOM nodes is smaller and touches only what changed.\n- **Track a separate visible count so the status line drops after a block.** Rejected for now. The requirements name it as the upgrade path. Paging stays correct without it.\n- **Mapping a 401 on a card action to `keyRejectedNotice`.** Ruled out by the operator's decision in req 7 and by the out-of-scope rule on data-layer error types.\n\n### Gotchas and risks\n\n- **A reset while an action is running.** A new search, sort change or popstate can replace the grid while a request is in flight. The clicked card is then detached, and setting `outerHTML` on an element with no parent throws. So the re-render is guarded with `card.isConnected`. A block that finishes after a reset filters the new `state.rows` by that block's channel or account, which is the right result because those rows are blocked anyway. Re-enabling the button in `finally` on a detached node is harmless.\n- **The same video on two loaded pages.** If the Engine's candidate pool ever returns a video twice, the lookup finds the first row, and a like or dislike re-renders only the clicked card. The other copy shows the old mark until the next search. Removal after a block matches by key and field, so it clears every copy.\n- **Keyless dislike.** `cardReaction` ignores `row.reaction` when there is no key, but the no-key guard stops Dislike before any request, so no mismatch can appear.\n- **Stale reactions after a profile change in another tab.** These are not handled. The rendered mark comes from the last search response, as it does on home.\n- **The search fetch's `ProfileKeyRejectedError` handling is not touched.** A key rejected during a card action shows only as that card's status message, by the operator's decision. The next search read then shows the notice.\n\n### Tradeoffs the operator is asked to accept\n\n- The card-action handler exists twice, once in home and once in search, with intentionally different dislike semantics, instead of one shared helper.\n- After a block, \"Showing N of M matched videos.\" may overstate what is on screen until the next reset. This is the deliberate simplification in req 8, and its upgrade path is a separate visible count.\n- Home's Dislike button gains an `aria-pressed=\"false\"` attribute. Nothing else on home changes.",
  "conflicts": "none",
  "impacts": "<impacts>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"module-level imports (lines 11-20)\">\n**What changes:** the imports grow, keeping the file's style (a multi-line brace list once a list gets long, as at lines 12-16).\n- `../../components/video-card` (line 11) adds `resolveInstanceDomain`, `resolveVideoId` and `resolveVideoKey`. They are exported at video-card.ts lines 65, 72 and 80.\n- `../../data/reactions` (line 18) adds `sendReaction`.\n- `../../data/profile` (line 17) adds `getProfileKey` (profile.ts line 20).\n- New import: `blockVideoSource` from `../../data/blocks` (blocks.ts line 33).\n\n**What depends on it:** Rollup's chunk graph. Today the built search entry (`dist/assets/search-0tNFtc30.js`) imports safe-url, video-card, cache, reactions and key-rejected, but not blocks. See the dist entry for what the new import does to chunking.\n\n**Risk:** low. `npm run build` is just `vite build` (package.json line 9), and Vite does not type-check, although tsconfig.json has `strict: true`. A wrong named import or a type error therefore passes the build. Run `npx tsc --noEmit` in client/frontend, or bundle with esbuild as the tests do.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"module docstring (lines 1-7)\">\n**What changes:** today it describes only URL state and infinite paging. Add one or two sentences:\n- cards carry Like, Dislike, Block channel and Block account;\n- Dislike toggles and the card stays, unlike home, because search is not filtered by dislikes (D6);\n- a block removes the loaded cards of that channel or account, while \"Showing N of M\" keeps counting fetched rows.\n\n**What depends on it:** nothing at runtime.\n\n**Risk:** none at runtime. Without it, the code never says why search's handler differs from home's.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"state object (lines 49-60): new `rows` field\">\n**What changes:** add `rows: [] as VideoRow[]`, in the form home uses (videos/index.ts line 85), with a `/** ... */` comment like the ones on `hasMore` and `requestSeq`. `VideoRow` is already a type import at line 20.\n\n**What depends on it:**\n- the new click listener (`state.rows.find`);\n- `renderRows`, which pushes onto it;\n- `removeRows`, which reassigns it;\n- `runCardAction`, through the row reference it holds and mutates (`row.reaction`).\n\n**Risk:** moderate.\n- A reset path that does not clear it lets a fresh card's key resolve to a stale row object with an old `reaction`, so the toggle sends the wrong action.\n- Rows must be pushed only after the `seq` check at line 182. Otherwise a stale response adds rows that were never rendered.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"loadPage() reset block (lines 151-154) and the paths into it: startSearch (line 138), popstate (line 103), initial load (line 108), keyRejectedNotice retry (line 174)\">\n**What changes:** add `state.rows = []` in `if (reset)`, next to `results.innerHTML = \"\"` and `state.loadedRows = 0`. This one line covers new search, sort change (through `startSearch`), popstate, initial load and the \"Forget key\" retry.\n\n**What depends on it:** the row lookup (req 2), and the plan's reset-during-action gotcha. A block that finishes after a reset filters the new `state.rows`.\n\n**Risk:** low in this block. Clearing in `renderRows`' reset branch instead would leave stale rows behind a reset whose fetch failed (SearchUnavailable, ProfileKeyRejected or network). The grid is empty in that case, so no card could reach them, but the reset block is the cleaner place.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"loadPage() catch branch, ProfileKeyRejectedError (lines 172-174), and an appended-page failure\">\n**What changes:** nothing, per req 7.\n\n**Interaction:** if an appended page (`reset=false`) fails with a rejected key, `results.replaceChildren(keyRejectedNotice(...))` wipes the grid but `state.rows` keeps the old rows. No `.video-card` is left, so no click resolves to a row and `removeRows` finds no node. The retry `loadPage(1, true)` clears the rows.\n\n**What depends on it:** 401s from `/api/user-action` (user-actions.ts lines 33-37) and `/api/profile/blocks` (blocks.ts lines 64-66) come back as plain `Error`, so they show in the card's status line and never reach this branch.\n\n**Risk:** no regression. The plan intentionally departs from issue 40 line 40 (\"A rejected key is handled as the search page already handles `ProfileKeyRejectedError`\"). The operator's decision is recorded in the record's step-1 conflicts.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"renderRows() (lines 204-214) and a new search card renderer (the counterpart of home's renderFeedCard, videos/index.ts lines 386-394)\">\n**What changes:**\n- A new function, for example `renderSearchCard(row)`, returns `renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true })` and has a one-line `/** ... */` docstring.\n- `renderRows` maps through it on both the `innerHTML` (reset) path and the `insertAdjacentHTML(\"beforeend\")` path, and pushes the page's rows onto `state.rows`.\n- `runCardAction` uses the same function for in-place re-renders, so the first render and a re-render cannot drift apart.\n\n**What depends on it:**\n- `.card-actions` is emitted only when `options.actions && videoKey` (video-card.ts line 352), so keyless rows stay bare.\n- Cards remain direct children of `#search-results`, which `removeRows` relies on.\n\n**Risk:** low. Each card gains a row of buttons and gets taller, so the sentinel sits further down and `fillViewport` (line 125) fetches fewer pages for the same viewport. That is a visual change, not a functional one.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"new delegated click listener on `results` (#search-results)\">\n**What changes:** a top-level `results.addEventListener(\"click\", ...)` next to the form and sort listeners (lines 70-83). It mirrors home's listener (videos/index.ts lines 135-141), except that the lookup is `state.rows.find((candidate) => resolveVideoKey(candidate) === key)` and not `state.sample`.\n\n**What depends on it:**\n- Cards on appended pages need no extra wiring (req 8).\n- The `keyRejectedNotice` \"Forget key\" button (key-rejected.ts lines 17-24) also lives in `#search-results`. It has no `data-card-action`, so the listener ignores it.\n- `.card-actions` sits outside `<a class=\"video-link\">` (video-card.ts line 351), so buttons do not navigate.\n\n**Risk:** low.\n- `event.target` may be an SVG `<path>` inside a button; `closest` handles that, as on home.\n- A disabled button dispatches no click, so double-clicking during an action does nothing.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"new runCardAction(button, card, row)\">\n**What changes:** new code modelled on home's (videos/index.ts lines 400-447).\n\n**Same as home:**\n- the `say` helper into `.card-action-status`;\n- the no-key guard and its exact text (line 409);\n- `button.disabled = true` and `say(\"\")` before the request, and re-enable in `finally`;\n- Like toggles on `cardReaction(row) === \"liked\"`;\n- Block is `blockVideoSource`, then `sendReaction(\"dislike\").then(() => null, err => message)`, then the \"Blocked \u2026 but the dislike failed\" early return;\n- the predicate at lines 434-440;\n- the `\"Action failed\"` fallback.\n\n**Different from home:**\n- `apiBase` is `apiParam ?? \"\"`. Home passes an already-resolved URL from `resolveApiBase(similarQuery)` (videos/index.ts line 79, data/videos.ts line 92). All the data functions run their argument through `resolveClientApiBase`, so both forms work.\n- Dislike sends `undo_dislike` when `cardReaction(row) === \"disliked\"` and `dislike` otherwise, sets `row.reaction`, and re-renders in place without removing the card.\n- Both re-renders are guarded with `card.isConnected`.\n\n**What depends on it:** `sendReaction` and `cardReaction` (reactions.ts), `blockVideoSource` (blocks.ts), `getProfileKey` (profile.ts), and the `data-card-action` values and the status span in video-card.ts lines 354-359. On the server, `_store_reaction` (client/backend/server.py lines 871-901) makes a like and a dislike replace each other, and `undo_dislike` takes the delete path. That confirms the `row.reaction` values the plan sets.\n\n**Risk:** medium.\n1. `outerHTML` on a detached card throws. Without the guard on both paths, the catch then writes into a dead node.\n2. `row.reaction` must be set before the re-render, because `cardReaction` reads it when a key is held (reactions.ts line 53).\n3. Search users can now reach the dislike cap (a 400 \"Dislike limit reached\") and the 502 for a centroid failure. Both show as the card's message.\n4. The `outerHTML` swap drops keyboard focus. Home's Like already does this; search's Dislike now does too.\n5. The handler is duplicated by hand from home's.\n6. There is no `ProfileKeyRejectedError` branch, by decision.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"new removeRows(match)\">\n**What changes:**\n- Filter `state.rows`.\n- Collect `resolveVideoKey` of the removed rows into a Set.\n- Walk `Array.from(results.children)` and `.remove()` each element whose `dataset.videoKey` is in the Set.\n- Call `fillViewport()`.\n- Leave `state.page`, `loadedRows`, `total`, `hasMore` and the status text untouched (req 8).\n\n**What depends on it:** the block path. `fillViewport` leads to `loadNextPage` (line 116), which returns early while `state.loading` is set or `hasMore` is false.\n\n**Risk:** low to medium.\n1. The predicate must equal home's exactly. Search rows carry `instance_domain`, `channel_id` and `account_url` (engine/server/data/search.py lines 56, 57 and 63).\n2. A next page already in flight when the block lands was filtered server-side before the block existed, so it can bring that channel back. Home has the same race.\n3. If a block empties the grid with `hasMore` false, \"Showing N of M\" stays and no \"No results\" appears. This is the accepted simplification.\n4. The attribute is escaped with `escapeHtml` but `dataset` reads it back unescaped, so it compares directly with raw `resolveVideoKey` and needs no CSS escaping.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"showIdle() (lines 219-228)\">\n**What changes:** add `state.rows = []` next to `state.loadedRows = 0`.\n\n**What depends on it:** an empty submit (line 74) and a popstate to a URL with no `q` (line 100).\n\n**Risk:** low. If it is missed, the leftover rows are unreachable because the grid is emptied. A block that finishes after idle filters them, and `fillViewport` returns early because `hasMore` is false.\n</impact>\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"no-key prompt text (req 6) and the search page's chrome\">\n**What changes:** search shows home's exact text: \"Disliking/Blocking needs a profile. Create one from the Profile button.\"\n\n**What depends on it:** search.html. Its nav (lines 21-27) has no Profile button and no profile modal. A grep for \"profile\" across the HTML sources matches only index.html and videos.html.\n\n**Risk:** a UX copy mismatch, not a regression. On search, the prompt points at a button the page does not have. Req 6 demands the exact text, so the operator should rule on the wording rather than the implementer quietly changing it.\n</impact>\n<impact path=\"client/frontend/search.html\" element=\"#search-results (line 58), #search-status (line 55), header nav (lines 21-27), CSP meta (line 8)\">\n**What changes:** nothing.\n\n**What depends on it:**\n- The listener is attached to `#search-results` (class `cards-grid`).\n- Each card's `.card-action-status` is a separate `role=\"status\"` region, apart from `#search-status`.\n- The CSP (`script-src 'self'`) is unaffected, because the new code adds no inline script and no inline handler.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/components/video-card.ts\" element=\"renderVideoCard() action markup, Dislike button (line 356)\">\n**What changes:** insert `aria-pressed=\"${reaction === \"disliked\"}\"` after `data-card-action=\"dislike\"`, in the same form as Like's attribute on line 355. No other change to the component.\n\n**What depends on it:**\n- `renderVideoCard` has two callers: home's `renderFeedCard` (videos/index.ts line 387) and search's `renderRows` (search/index.ts line 208).\n- likes/index.ts line 9 imports only `channelName`, `escapeHtml`, `thumbnailUrl` and `videoPageUrl`. The video page does not import video-card.ts at all (imports at video-page/index.ts lines 5-20).\n- `.card-action[aria-pressed=\"true\"] svg` (videos.css line 664) is generic, so a pressed Dislike fills its icon with no CSS change.\n\n**Risk:** low.\n- Home's Dislike is now announced as a \"not pressed\" toggle even though it is a one-shot remove there. Issue 40 line 43 allows this.\n- `\"true\"` cannot appear on home, because feeds drop disliked rows (server.py line 469) and home's Dislike removes the card.\n</impact>\n<impact path=\"client/frontend/src/components/video-card.ts\" element=\"VideoCardOptions comments (lines 34-37) and module docstring (lines 1-12)\">\n**What changes:** nothing is required; both stay accurate. Optionally, the `reaction` comment at line 34 could say that it also sets `aria-pressed` on the Like and Dislike buttons.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/pages/videos/index.ts\" element=\"home click listener (lines 135-141), renderFeedCard (lines 386-394), runCardAction (lines 400-447), removeRows (lines 452-457)\">\n**What changes:** nothing (req 10). This is the reference that search copies.\n\n**What depends on it:** the acceptance criterion that home's dislike and block still remove cards and home has no undo-dislike.\n\n**Risk:**\n- Only the shared markup reaches home, and home never reads `aria-pressed`.\n- The implementer must not \"tidy\" home while copying from it, for example by adding an `isConnected` guard or `undo_dislike` there.\n</impact>\n<impact path=\"client/frontend/src/data/reactions.ts\" element=\"sendReaction() (lines 89-100), cardReaction() (lines 52-57), AFTER (lines 20-25)\">\n**What changes:** nothing. Search calls `sendReaction` for the first time.\n\n**What depends on it:**\n- A keyless like or undo-like is written to `localLikes:v1` before `sendReaction` resolves (lines 95-98), so a keyless re-render reads it correctly.\n- `undo_dislike` is a valid `ReactionAction` (line 16).\n\n**Known gap, inherited from home and not introduced here:**\n- Keyless, the like is stored under `resolveVideoId(row)`, which falls back to `video_id` when `video_uuid` is null (video-card.ts lines 72-75). `cardReaction` (lines 54-56) checks only `video_uuid`/`videoUuid`.\n- So a keyless Like on a row with a null `video_uuid` (the column is nullable in engine/crawler/schema.sql) succeeds but never shows as liked, and the next click sends `like` again.\n- Fixing it is out of scope for this build, because it would change `reactions.ts` and home with it.\n\n**Risk:** none to the module. The gap is a low risk on the search page.\n</impact>\n<impact path=\"client/frontend/src/data/blocks.ts\" element=\"blockVideoSource() (lines 33-41) and request() (lines 51-68)\">\n**What changes:** nothing.\n\n**What depends on it:** search's block path.\n- Every non-OK answer, 401 included, throws a plain `Error(payload.error ?? \"Block request failed (N)\")`, which fits req 7.\n- `Block` has `kind`, `instance_domain`, `channel_id`, `account_url` and `label` (lines 13-20).\n\n**Risk:** none. A reply without `kind` would fall into the account branch on both pages.\n</impact>\n<impact path=\"client/frontend/src/data/user-actions.ts\" element=\"sendUserAction() (lines 18-38)\">\n**What changes:** nothing.\n\n**What depends on it:** every Like and Dislike on search, through `sendReaction`. On any non-OK status it throws `Error(body.error ?? \"Failed to send action\")`. That text, including the server's messages for the dislike cap and for a missing key, is what reaches the card's status line.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/data/api-base.ts\" element=\"resolveClientApiBase() (lines 18-33)\">\n**What changes:** nothing.\n\n**What depends on it:** search passes `apiParam ?? \"\"`. Resolution order is `VITE_CLIENT_API_BASE` first, then `?api=` in DEV only, then `window.location.origin`. In production, `?api=` is ignored, so passing `apiParam` cannot redirect card actions.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/data/profile.ts\" element=\"getProfileKey() (lines 20-26)\">\n**What changes:** nothing. Search imports it for the first time, for the no-key guard.\n\n**What depends on it:** the guard. It reads `localStorage` `profileKey:v1` on each call, so a key created in another tab takes effect on the next click.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/data/search.ts\" element=\"fetchSearchResults(): keyed no-store branch (lines 68-76) and keyless sessionStorage cache (lines 78-90)\">\n**What changes:** nothing.\n\n**What depends on it:** the \"rerun the same search\" acceptance checks.\n- With a key, the fetch is `cache: \"no-store\"`, so a rerun shows a dislike, an undo or a block at once.\n- Without a key, results are cached for 30 s, but cache.ts re-parses from sessionStorage on every read (cache.ts lines 44-58), so mutating `row.reaction` in place never leaks into the cache.\n- Keyless actions are limited to Like, whose mark comes from `localLikes:v1`.\n\n**Risk:** none. Rerun checks must use a key.\n</impact>\n<impact path=\"client/frontend/src/data/cache.ts\" element=\"fetchJsonWithCache / readCache / writeCache\">\n**What changes:** nothing.\n\n**What depends on it:** the keyless search path. `writeCache` stores `JSON.stringify(payload)` before the rows are handed to the page, and `readCache` parses fresh objects, so search's in-place `row.reaction` writes cannot corrupt cached pages.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/types/videos.ts\" element=\"VideoRow: channel_id (line 10), account_url (line 15), reaction (lines 51-52)\">\n**What changes:** nothing.\n\n**What depends on it:** search's block predicate and the `row.reaction` assignments. The type is `\"liked\" | \"disliked\" | null`.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/components/key-rejected.ts\" element=\"keyRejectedNotice(onForget)\">\n**What changes:** nothing.\n\n**What depends on it:** its retry calls `loadPage(1, true)`, a reset path that must clear `state.rows`. Its button sits inside `#search-results` and has no `data-card-action`, so the new listener ignores it.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/src/videos.css\" element=\".stat.active (lines 616-623), .card-actions \u2026 .card-action-status:empty (lines 625-676), .visually-hidden (lines 678-685), :root variables (lines 5-8)\">\n**What changes:** nothing. Search already imports it (search/index.ts line 9), and the variables the card actions use (`--line`, `--accent-strong`, `--muted`) are defined in this file.\n\n**What depends on it:**\n- the action row layout;\n- the filled icon for a pressed Dislike (line 664);\n- the disliked stat mark;\n- the hidden \"Like\" and \"Dislike\" labels.\n\n**Risk:** low.\n- There is no `.video-card.disliked` rule, so the root class has no visual effect.\n- Search cards get taller; check this visually.\n</impact>\n<impact path=\"client/frontend/src/search.css\" element=\"whole file, including its own .visually-hidden (lines 69-79)\">\n**What changes:** nothing. No rule targets `.card-action*` or `.video-card`. The header comment (lines 1-3) says the cards reuse videos.css.\n\n**What depends on it:** `.visually-hidden` is defined both here and in videos.css with the same specificity. The built search.html loads search CSS before videos CSS (dist/search.html lines 18-19), so for overlapping properties the videos.css copy wins. Both hide the button labels, so this is not a regression.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"FEED_ROUTES/FILTERED_ROUTES (lines 71-72), _profile_filter dropped rule (line 469), _store_reaction (lines 871-901), _filter_payload (lines 1096-1122)\">\n**What changes:** nothing; this is out of scope.\n\n**What depends on it:**\n- Search is filtered by blocks but never by dislikes (D6), so the card can stay after a Dislike, and a rerun returns the row with `reaction: \"disliked\"`.\n- `reaction` is keyed on `(video_id, instance_domain)`.\n- Like/dislike replacement and `undo_dislike` (lines 871-901) are what search's toggle relies on.\n- `total` is not adjusted after filtering, which is why the req 8 count is honest only about fetched rows.\n\n**Risk:** none from this build. If D6 is ever reversed, search's toggle and keep-card behaviour need revisiting.\n</impact>\n<impact path=\"engine/server/data/search.py\" element=\"VIDEO_ROW_SQL (lines 51-79)\">\n**What changes:** nothing.\n\n**What depends on it:** search's key, its toggle and its block predicate use `video_id` (53), `video_uuid` (54), `instance_domain` (56), `channel_id` (57) and `account_url` (63). All are present.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/vite.config.ts\" element=\"build.rollupOptions.input (lines 84-94)\">\n**What changes:** nothing. `search.html` is already an entry (line 87).\n\n**What depends on it:** the rebuild. The `about` entry uses `dev-pages/about.html` if that file exists. Only `about.template.html` is present today.\n\n**Risk:** none, unless a local `about.html` appears before the build.\n</impact>\n<impact path=\"client/frontend/package.json\" element=\"scripts.build (line 9) and the frontend toolchain\">\n**What changes:** nothing. Req 11 runs `npm run build` (that is, `vite build`).\n\n**What depends on it:** the dist rebuild and any esbuild-based test. Uncertain: a Glob of `client/frontend/node_modules/.bin/*` in this worktree returned nothing, and the Read was blocked by the sandbox. node_modules may be missing here or symlinked from outside the project. If it is missing, `npm ci` is needed in the worktree first. `tests/active/test_frontend_*.py` also resolve `FRONTEND/node_modules/.bin/esbuild`.\n\n**Risk:** low, but the build or the tests can fail for environment reasons rather than code reasons.\n</impact>\n<impact path=\"client/frontend/dist/\" element=\"built bundle: *.html and assets/*\">\n**What changes:** `npm run build` regenerates it, and `dist/` is tracked. Correcting the earlier inventory, these are the actual importers:\n- **video-card chunk** (`video-card-C4VEive-.js`): imported by `index-OsZsLoAr.js`, `likes-xsQYeXe5.js` and `search-0tNFtc30.js`, and referenced by index.html, videos.html, likes.html and search.html. channels and video-page do not import it.\n- **The chunk named `blocks-DRgP8l-1.js` is a merged chunk.** It holds data/videos.ts (createFeedPager, buildSimilarUrl, resolveApiBase) as well as blocks.ts. index and video import it; video-page.html, index.html and videos.html reference it.\n- **Effect of search importing blocks.ts:** blocks.ts will be shared by three entries while data/videos.ts stays shared by two. Rollup will likely split them, which means a new chunk file, a changed blocks chunk, and new hashes for `index-*.js`, `video-*.js` and their HTML pages as well as search and likes. This is a prediction, not verified.\n\nOld hashed files are deleted.\n\n**What depends on it:** the served site. scripts/sync.sh line 19 builds, then rsyncs with `--delete` (line 22). DEPLOYMENT.md line 390 says the committed dist lags the source.\n\n**Risk:** medium for the commit, low for the code.\n- Run the build once, after both source edits.\n- Commit the whole dist diff, added and deleted files included. A partial commit leaves HTML pointing at missing chunks.\n- Skipping the build fails the acceptance criterion.\n</impact>\n<impact path=\"tests/active/test_frontend_reactions.py\" element=\"cards step of RUNNER (lines 86-99) and _bundle (lines 106-124)\">\n**What changes:** nothing needed. It renders `renderVideoCard(row, { reaction })` without `actions`, so the new attribute is never emitted, and its regexes target only `class=\"stat likes active\"` and `class=\"stat dislikes active\"`.\n\n**Risk:** none. It remains the guard for `cardReaction` over search rows.\n</impact>\n<impact path=\"tests/active/test_frontend_videos_page.py\" element=\"home runner and fake DOM (lines 22-90)\">\n**What changes:** nothing needed. It asserts only the `data-video-key` values in `#video-cards` (line 89), so the extra `aria-pressed` on home's markup does not affect it.\n\n**Risk:**\n- None to this test.\n- It does not guard card actions: its fake element has `closest: () => null` (line 51) and no `outerHTML`, `isConnected` or `dataset`.\n- Its esbuild bundling of a page entry is the template for a search-page test.\n</impact>\n<impact path=\"tests/active/test_frontend_blocks.py\" element=\"block runner steps\">\n**What changes:** nothing.\n\n**What depends on it:** it pins the `Block` shape that search consumes.\n\n**Risk:** none.\n</impact>\n<impact path=\"tests/active/ (new search-page card-action test; filename to be decided, drafted in tests/tmp first)\">\n**What changes:** a grep for `pages/search`, `search.html`, `search-results` and `video-card` under tests/ and tests/tmp finds no test that loads the search page, so every acceptance criterion here is unguarded.\n\n**Candidate test:** bundle `src/pages/search/index.ts` with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`), as test_frontend_videos_page.py does. Assert that:\n- appended pages render the buttons;\n- Dislike sends `dislike` then `undo_dislike`, and `aria-pressed` flips between true and false;\n- no request is made without a key;\n- a block removes the matching cards and calls `fillViewport`;\n- a re-render after a reset does not throw.\n\nRerun checks need a key, against `engine_client` or `unpublished_client`.\n\n**Risk:** the fake DOM needs `closest`, `outerHTML`, `isConnected`, `dataset`, element children and `remove`. That is a richer fake than any existing test has.\n</impact>\n<impact path=\"tests/check-frontend-client-gateway.sh\" element=\"frontend gateway boundary grep\">\n**What changes:** nothing. The new code calls only Client routes (`/api/user-action`, `/api/profile/blocks`), through the existing data modules.\n\n**Risk:** none.\n</impact>\n<impact path=\"client/frontend/README.md\" element=\"'What it does' list, line 16 (reaction marks)\">\n**What changes:** documentation; see the checklist. Line 16 covers the reaction marks, but no bullet describes the card action buttons on either feed or search. The feed-grid controls are undocumented too.\n\n**Risk:** none at runtime.\n</impact>\n<impact path=\"docs/project/roadmap.md\" element=\"F13-M2 (line 54) and the Delivered section (lines 7-25)\">\n**What changes:** after this build, the feed-grid and search-grid halves of F13-M2 are in the tree and only the channels page remains. No Delivered entry exists for the feed-grid half either; the archived plan 07 line 33 only defers it. Which change delivered it could not be established from the docs.\n\n**Risk:** none at runtime; traceability only.\n</impact>\n<impact path=\"docs/project/issues/40-search-card-actions.md\" element=\"Status line (line 3), Comments, location\">\n**What changes:** on delivery, per issue-tracker.md line 21:\n- set `Status: enhancement, complete`;\n- append a comment that names the plan and records the req 7 decision, which departs from the brief at line 40;\n- move the file to `docs/project/issues/archive/`.\n\n**Risk:** traceability only.\n</impact>\n<impact path=\"docs/project/plans/20-40-search-card-actions.md\" element=\"Impacts and Documentation sections\">\n**What changes:** the workflow re-renders them from the run state; the header at line 3 says manual edits are overwritten. At delivery the plan moves to `docs/project/plans/archive/` (issue-tracker.md line 29).\n\n**Risk:** none at runtime.\n</impact>\n<impact path=\"client/README.md\" element=\"user-action and gateway filtering (lines 19, 24-25)\">\n**What changes:** nothing. It already says the dislike actions need a key, a like and a dislike replace each other, search is not filtered by dislikes, and rows carry `reaction`.\n\n**Risk:** none.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"likes and dislikes paragraph (line 360), dist sync note (lines 386-390)\">\n**What changes:** nothing. \"Search is not filtered by dislikes\" and \"which the frontend shows on the card\" both still hold. The sync note is the deploy step that follows req 11.\n\n**Risk:** none.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"glossary: Dislike (line 4), Block (line 11)\">\n**What changes:** nothing. The Dislike entry says a dislike removes the video from feeds, not from search, which matches search keeping the card. No new term is introduced.\n\n**Risk:** none.\n</impact>\n</impacts>",
  "docs_checklist": "- [x] `client/frontend/README.md` - updated: Added two \"What it does\" bullets on the card action buttons (Like, Dislike, Block channel, Block account) on home feed and search cards.\n- [x] `docs/project/roadmap.md` - updated: Added a Delivered entry for the F13-M2 search card controls (issue `40`) and cut F13-M2 down to the channels-page block controls.\n- [x] `docs/project/issues/40-search-card-actions.md` - updated: Closed issue 40 as delivered: set the Status line to `enhancement, complete`, added a delivery comment and wrote the file to `docs/project/issues/archive/`, but the original is still in `issues/` and has to be deleted by hand.\n- [x] `docs/project/plans/20-40-search-card-actions.md` - updated: I made no edit to the plan's content, and I could not move the file: it is still at `docs/project/plans/20-40-search-card-actions.md` and needs a `git mv` into `docs/project/plans/archive/`.",
  "docs": [
    {
      "path": "client/frontend/README.md",
      "note": "Add a \"What it does\" bullet after line 16. Home and search cards carry Like, Dislike, Block channel and Block account. Like works without a key; Dislike and Block need a key and otherwise show the \"needs a profile\" prompt on the card. On home, Dislike or Block removes the affected cards, with no undo. On search, Dislike toggles `dislike`/`undo_dislike` and the card stays marked, because search is not filtered by dislikes. A Block removes every loaded card of that channel or account, while \"Showing N of M\" keeps counting fetched rows. A failed action, a rejected key included, shows in that card's status line. Like and Dislike both carry `aria-pressed`."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "Update F13-M2 (line 54): the feed and search grids are delivered, and only the channels page remains. Add a Delivered entry naming issue `40` and its plan, at the plan's archive path once moved. Also note that the feed-grid half had no Delivered entry before this change."
    },
    {
      "path": "docs/project/issues/40-search-card-actions.md",
      "note": "On delivery, set `Status: enhancement, complete` and append a comment naming the delivering plan. In that comment, record that a rejected key during a card action shows as the card's status message, not `keyRejectedNotice`, which overrides the brief's Errors bullet at line 40. Also record whether the \"Profile button\" wording of the no-key prompt was kept on search, which has no such button. Then move the file to `docs/project/issues/archive/`."
    },
    {
      "path": "docs/project/plans/20-40-search-card-actions.md",
      "note": "The workflow re-renders the Impacts and Documentation sections from this inventory. On delivery, move the plan to `docs/project/plans/archive/`."
    }
  ],
  "reassessments": 3,
  "draft": "## Draft implementation \u2014 issue 40, search card actions\n\n### Module map\n\n| File | Change |\n|---|---|\n| `client/frontend/src/components/video-card.ts` | Line 356: the Dislike button gains `aria-pressed=\"${reaction === \"disliked\"}\"`, written exactly like Like's on line 355. Nothing else changes. |\n| `client/frontend/src/pages/search/index.ts` | Changes: imports, docstring, `state.rows`, the reset in `loadPage`, `showIdle`, `renderRows`, a new `renderSearchCard`, a delegated click listener, `runCardAction` and `removeRows`. |\n| `client/frontend/src/pages/videos/index.ts` | Not touched (req 10). |\n| `client/frontend/dist/` | Rebuilt once with `npm run build` after both source edits. The whole diff is committed, including added and deleted chunks. |\n| `tests/tmp/test_frontend_search_card_actions.py` | New test, drafted here and promoted to `tests/active/` (see \"What has to be tested\"). |\n\nThere is no new shared module. Home's handler is copied into search on purpose (plan, Alternatives \u00a71).\n\n### `components/video-card.ts`, line 356\n\n```ts\n        <button type=\"button\" class=\"card-action\" data-card-action=\"dislike\" aria-pressed=\"${reaction === \"disliked\"}\" title=\"Dislike\">${iconThumbDown()}<span class=\"visually-hidden\">Dislike</span></button>\n```\n\nInvariant: `aria-pressed` is `\"true\"` only when `options.reaction === \"disliked\"`. Home never passes that value, because its feeds drop disliked rows, so home always renders `\"false\"`.\n\n### `pages/search/index.ts`\n\n**Docstring (lines 1-7)**: add a paragraph:\n\n```ts\n *\n * Each card carries Like, Dislike, Block channel and Block account. Unlike home, Dislike toggles and\n * the card stays, because search is not filtered by dislikes (D6). A block removes the loaded cards of\n * that channel or account, while \"Showing N of M\" keeps counting fetched rows.\n```\n\n**Imports (lines 11-18)**:\n\n```ts\nimport {\n  renderVideoCard,\n  resolveInstanceDomain,\n  resolveVideoId,\n  resolveVideoKey\n} from \"../../components/video-card\";\nimport {\n  fetchSearchResults,\n  SearchUnavailableError,\n  type SearchSort\n} from \"../../data/search\";\nimport { getProfileKey, ProfileKeyRejectedError } from \"../../data/profile\";\nimport { cardReaction, importLocalLikes, sendReaction } from \"../../data/reactions\";\nimport { blockVideoSource } from \"../../data/blocks\";\nimport { keyRejectedNotice } from \"../../components/key-rejected\";\nimport type { SearchPayload, VideoRow } from \"../../types/videos\";\n```\n\n**State (lines 49-60)**: add after `total`:\n\n```ts\n  /** Rows rendered into the grid, in order; card actions find their row here by video key. */\n  rows: [] as VideoRow[],\n```\n\n**Click listener**: placed after the `sortSelect` listener (after line 83), mirroring home's listener at videos/index.ts lines 135-141:\n\n```ts\nresults.addEventListener(\"click\", (event) => {\n  const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>(\"[data-card-action]\");\n  const card = button?.closest<HTMLElement>(\".video-card\");\n  const key = card?.dataset.videoKey;\n  const row = key ? state.rows.find((candidate) => resolveVideoKey(candidate) === key) : undefined;\n  if (button && card && row) void runCardAction(button, card, row);\n});\n```\n\nInvariant: a click resolves to a row only when the button, the card, the key and a stored row all exist. Anything else does nothing, including the keyRejectedNotice \"Forget key\" button, which has no `data-card-action`.\n\n**`loadPage` reset block (lines 151-154)**:\n\n```ts\n  if (reset) {\n    results.innerHTML = \"\";\n    state.loadedRows = 0;\n    state.rows = [];\n  }\n```\n\nThis one line covers new search, sort change, popstate, initial load and the key-rejected retry. `renderRows` is called only after the `seq` check at line 182, so a stale response can never push rows.\n\n**`renderRows` (lines 207-214)** and the new renderer:\n\n```ts\n/**\n * Render rows into the grid through the shared card component and remember them for card actions.\n */\nfunction renderRows(rows: VideoRow[], reset: boolean) {\n  const markup = rows.map(renderSearchCard).join(\"\");\n  state.rows.push(...rows);\n  if (reset) {\n    results.innerHTML = markup;\n    return;\n  }\n  results.insertAdjacentHTML(\"beforeend\", markup);\n}\n\n/**\n * Render one search card with its action controls; used for first renders and in-place re-renders.\n */\nfunction renderSearchCard(row: VideoRow) {\n  return renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true });\n}\n```\n\nInvariant: `state.rows` holds the rendered rows in DOM order, and each keyed row has exactly one `article.video-card[data-video-key]` as a direct child of `#search-results`. `rows.map(renderSearchCard)` is safe because `map`'s index argument lands nowhere: `renderSearchCard` takes one parameter.\n\n**`runCardAction`**: a copy of home's lines 400-447 with only the differences the plan names:\n\n```ts\n/**\n * Like, dislike or block from a card; a block dislikes the video too. Like and Dislike toggle and the\n * card stays, marked; a block takes every loaded card of that channel or account off the page.\n */\nasync function runCardAction(button: HTMLButtonElement, card: HTMLElement, row: VideoRow) {\n  const action = button.dataset.cardAction ?? \"\";\n  const apiBase = apiParam ?? \"\";\n  const uuid = resolveVideoId(row);\n  const host = resolveInstanceDomain(row);\n  const status = card.querySelector<HTMLElement>(\".card-action-status\");\n  const say = (text: string) => {\n    if (status) status.textContent = text;\n  };\n  if (action !== \"like\" && !getProfileKey()) {\n    say(`${action === \"dislike\" ? \"Disliking\" : \"Blocking\"} needs a profile. Create one from the Profile button.`);\n    return;\n  }\n  button.disabled = true;\n  say(\"\");\n  try {\n    if (action === \"like\") {\n      const liked = cardReaction(row) === \"liked\";\n      await sendReaction(apiBase, liked ? \"undo_like\" : \"like\", { uuid, host });\n      row.reaction = liked ? null : \"liked\";\n      // A reset during the request detaches the card; outerHTML on a detached node throws.\n      if (card.isConnected) card.outerHTML = renderSearchCard(row);\n    } else if (action === \"dislike\") {\n      const disliked = cardReaction(row) === \"disliked\";\n      await sendReaction(apiBase, disliked ? \"undo_dislike\" : \"dislike\", { uuid, host });\n      row.reaction = disliked ? null : \"disliked\";\n      if (card.isConnected) card.outerHTML = renderSearchCard(row);\n    } else if (action === \"channel\" || action === \"account\") {\n      const block = await blockVideoSource(apiBase, action, uuid, host);\n      // Blocking also dislikes the video, as on home.\n      const disliked = await sendReaction(apiBase, \"dislike\", { uuid, host }).then(\n        () => null,\n        (error: unknown) => (error instanceof Error ? error.message : \"Dislike failed\")\n      );\n      if (disliked !== null) {\n        say(`Blocked ${block.label || action}, but the dislike failed: ${disliked}`);\n        return;\n      }\n      removeRows(\n        block.kind === \"channel\"\n          ? (candidate) =>\n              String(candidate.instance_domain ?? \"\") === block.instance_domain &&\n              String(candidate.channel_id ?? \"\") === block.channel_id\n          : (candidate) => String(candidate.account_url ?? \"\") === block.account_url\n      );\n    }\n  } catch (error) {\n    say(error instanceof Error ? error.message : \"Action failed\");\n  } finally {\n    button.disabled = false;\n  }\n}\n```\n\nInvariants:\n- `row.reaction` is assigned only after the request resolves. A failure leaves both the row and the card unchanged, and the message appears in the old card's status line, which is still attached.\n- `row.reaction` is assigned before the re-render, because `cardReaction` reads it when a key is held.\n- After a successful Like or Dislike, `button` and `status` belong to the replaced, detached node. The `finally` re-enables that detached button, which is harmless, and the new card renders enabled. This matches home's Like.\n- No branch for `ProfileKeyRejectedError` (req 7, operator decision). A 401 arrives as a plain `Error` and is shown with `say`.\n- The block predicate is home's lines 434-440, character for character.\n\n**`removeRows`**:\n\n```ts\n/**\n * Drop matching rows and their cards in place, then refill the viewport. Paging counters keep\n * counting fetched rows: the Client filters each Engine page, so page numbers do not shift.\n */\nfunction removeRows(match: (row: VideoRow) => boolean) {\n  const removed = new Set(state.rows.filter(match).map((row) => resolveVideoKey(row)));\n  state.rows = state.rows.filter((row) => !match(row));\n  for (const element of Array.from(results.children) as HTMLElement[]) {\n    const key = element.dataset.videoKey;\n    if (key && removed.has(key)) element.remove();\n  }\n  fillViewport();\n}\n```\n\nInvariant: `state.page`, `loadedRows`, `total`, `hasMore` and the status text are not touched (req 8, deliberate simplification). `dataset.videoKey` gives back the unescaped key, so it compares directly with `resolveVideoKey`, with no selector escaping. Keyless rows never have a card with controls and cannot be the clicked row. If a keyless row matched a block, it would be dropped from `state.rows`, but its card has no `data-video-key` and stays on the page. That is harmless and inert. `fillViewport` returns early while a page is loading or `hasMore` is false.\n\n**`showIdle` (lines 219-228)**: add `state.rows = [];` after `state.loadedRows = 0;`.\n\n### Requirement trace (check pass 1 \u2014 converged)\n\n| Req | Where it is met |\n|---|---|\n| 1 Controls | `renderSearchCard` passes `actions: true`, and `renderRows` uses it on both paths. Keyless rows get no controls because of video-card.ts line 352. |\n| 2 Row lookup | `state.rows`, the resets in `loadPage(reset)` and `showIdle`, and the delegated listener. |\n| 3 Like | The toggle on `cardReaction(row) === \"liked\"`, followed by an in-place `renderSearchCard`. |\n| 4 Dislike toggle | The `undo_dislike`/`dislike` branch, the in-place re-render, and the `aria-pressed` added in video-card.ts. |\n| 5 Block | `blockVideoSource`, then `sendReaction(\"dislike\")`. A failed dislike gets the early return with the message; otherwise `removeRows` runs with home's predicate. |\n| 6 No key | Home's guard and its exact text. No request is sent. |\n| 7 Errors | Disabled button, `say(message \\|\\| \"Action failed\")`, re-enable in `finally`. No change to the data layer. |\n| 8 Paging | The listener is on the container. Counters are untouched. `removeRows` calls `fillViewport()`. |\n| 9 Markup | One attribute on line 356. |\n| 10 Home | `videos/index.ts` is not edited. |\n| 11 Build | `npm run build`, preceded by `npx tsc --noEmit`, because Vite does not type-check. |\n\nI checked the plan's risks as well: the reset during an action is handled by `isConnected`; a block landing after a reset filters the new rows, which is correct; a duplicate video is handled because `removeRows` is key-based and clears every copy. One copy concern remains, below.\n\n**Flag, not a fix:** search.html has no Profile button, so the required text \"\u2026Create one from the Profile button.\" points at nothing on this page. Req 6 requires the exact text, so the draft keeps it. The issue 40 delivery comment should record that the wording was kept, as the documentation checklist asks.\n\n### What has to be tested\n\n`tests/tmp/test_frontend_search_card_actions.py`. It bundles `src/pages/search/index.ts` with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`), modelled on `test_frontend_videos_page.py`. It runs under node with a fake DOM that supports `closest`, `dataset`, `children`, `remove`, `outerHTML` (re-parsed into a new node) and `isConnected`, a stub `fetch` that records method, path and body, and an `IntersectionObserver` stub. Cases:\n\n1. Page 1 plus an appended page 2: every keyed card has four `[data-card-action]` buttons, and a keyless row has none.\n2. With a key, Dislike sends `dislike`, and the card re-renders with `stat dislikes active` and Dislike `aria-pressed=\"true\"`. A second click sends `undo_dislike` and the mark clears (`aria-pressed=\"false\"`).\n3. Like on a disliked card sends `like` and the card shows liked, not disliked. A second click sends `undo_like`.\n4. Without a key, Dislike, Block channel and Block account each write the exact prompt and make no fetch. Keyless Like sends `like` and stores it in `localLikes:v1`.\n5. Block channel: `POST /api/profile/blocks`, then `dislike`. Every loaded card with the same `instance_domain`+`channel_id` is removed, including on page 2, and `fillViewport` runs (the sentinel is in view, so page 3 is fetched). The status text is unchanged. Block account works the same way through `account_url`.\n6. Block where the dislike returns 500: the status line reads `Blocked <label>, but the dislike failed: <msg>` and no card is removed.\n7. A failed request (400 \"Dislike limit reached\"): the message appears in the status line, the button is re-enabled, and `row.reaction` is unchanged.\n8. A reset while an action is in flight (a new search resolves first): no exception, and `state.rows` holds only the new rows.\n9. The rendered markup of `renderVideoCard(row, { actions: true, reaction: null })` has Dislike `aria-pressed=\"false\"`. This is home's case.\n\nThe acceptance reruns (a keyed rerun of the search shows `reaction: \"disliked\"`, no reaction after undo, and no blocked-channel rows) are backend facts, already covered by D6 and `_filter_payload`. They are checked manually against a live Client with a key, or by `engine_client` if the test is extended. The existing `test_frontend_reactions.py`, `test_frontend_blocks.py` and `test_frontend_videos_page.py` must stay green unchanged.\n",
  "coordination": "none. Every checkpoint runs offline under node, with a stub fetch. The plan's acceptance reruns need a live Client with a profile key: a keyed rerun of the search showing `reaction: \"disliked\"`, no reaction after undo, and no blocked-channel rows. Those are backend facts already covered by D6 and `_filter_payload`, so they gate no phase. They are an optional manual check for the operator.",
  "tests": {
    "tests/tmp/test_40_search_card_actions_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_40_search_card_actions_phase1.py:67 \u2014 with `reaction: \"disliked\"`, the `[data-card-action=\"dislike\"]` button's `aria-pressed` attribute is the string \"true\"",
          "expected": "\"true\" \u2014 the same `aria-pressed=\"${boolean}\"` interpolation the Like button already uses, which the probe saw render as 'true' for the liked card's Like button. Under the current code the run shows None (no attribute), `assert None == 'true'` at line 67.",
          "wrong_implementation": "The current code: a Dislike button with no `aria-pressed` reads None. It also rules out copying the Like line unchanged (`reaction === \"liked\"`), which reads \"false\" here."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_40_search_card_actions_phase1.py:68, :69, :70 \u2014 with `reaction: null`, `reaction: \"liked\"`, and no `reaction` key, the Dislike button's `aria-pressed` is the string \"false\"",
          "expected": "\"false\" in all three cases. The probe saw the current code give None for all three (dislike: [None] for null, liked and omitted), so these lines are red as well, behind line 67.",
          "wrong_implementation": "An `aria-pressed` written only when the reaction is disliked (`${reaction === \"disliked\" ? ' aria-pressed=\"true\"' : \"\"}`) reads None here. The Like line copied unchanged (`reaction === \"liked\"`) reads \"true\" at line 69. A hard-coded `aria-pressed=\"true\"` reads \"true\" in all three."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "The Dislike button has `aria-pressed=\"true\"` when `options.reaction` is `\"disliked\"`, and `aria-pressed=\"false\"` otherwise."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_40_search_card_actions_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_40_search_card_actions_phase1.py  1 failed, 1 passed                     0.0s\n  -----------------------------------------------\n  total                                            1 failed, 1 passed                     0.9s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_40_search_card_actions_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_40_search_card_actions_phase2.py:306 \u2014 every keyed card on page 1 and on the appended page 2 has exactly the [data-card-action] buttons like, dislike, channel, account. Also :307 \u2014 the keyless card on each page has none. The keyless-visitor render at :332 and the fresh-search render at :349 (both parametrized cases) show the same.",
          "expected": "{a1, a2, b1, b2 keys: [\"like\",\"dislike\",\"channel\",\"account\"]} at :306; [[], []] for k1 and k2 at :307.",
          "wrong_implementation": "The current page (renderRows with no `actions`): every list reads [] and the test fails at :306, observed. A page that passes `actions` only on the reset path leaves b1 and b2 with [] at :306. A page that draws controls on keyless rows gives a non-empty list at :307."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_40_search_card_actions_phase2.py:316 \u2014 each of Dislike, Dislike, Dislike, Like, Like on page-2 card b2 sends one POST /api/user-action with that click's toggled action and b2's uuid and host. :318 \u2014 after each click the card shows the new mark (stat active + aria-pressed). :319 \u2014 the redrawn card keeps its four controls. :321 and :322 \u2014 card order is unchanged and no other card changes (in place). :335, :336 and :337 \u2014 a keyless Like sends `like`, is stored in localLikes:v1 and shows liked. :357 and :358 in both the `[like]` and `[dislike]` cases of the reset test \u2014 after a Like or a Dislike whose response resolved after a new search detached the card, no error escaped and the clicked card's status line is \"\". :360 and :361 \u2014 the new grid is the second search's cards, all unmarked. :363 and :364 \u2014 the following same-reaction click sends `like`/`dislike` and the card shows LIKED/DISLIKED.",
          "expected": "Toggle actions: dislike, undo_dislike, dislike, like, undo_like. Marks: DISLIKED, NEUTRAL, DISLIKED, LIKED, NEUTRAL. Grid order and the other cards are unchanged. Reset case, for each of like and dislike: errors [], status \"\", afterRelease c1/a2/c2 all NEUTRAL, next sent [like] or [dislike] with mark LIKED or DISLIKED (observed under the plan's draft bundle).",
          "wrong_implementation": "An always-`dislike` Dislike fails :316 at step 2. A Like that sends `undo_like` on a disliked card fails :316 at step 4. Sending without redrawing keeps the old mark and fails :318. A redraw that appends the card moves it and fails :321. A Dislike branch that sets `card.outerHTML` without an `isConnected` guard, while the Like branch has one, fails `[dislike]` at :358 with status \"NoModificationAllowedError: This element has no parent node.\" (observed; `[like]` passes). The mirror mutant fails only `[like]` at :358 (observed). A reset that does not clear `state.rows` makes the next click send `undo_like` or `undo_dislike` and fails :363 in both cases (observed)."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Every keyed card on the first page and on an appended page has the four `[data-card-action]` controls, and a keyless card has none."
        },
        {
          "id": "C2",
          "text": "A Like or Dislike click sends the toggled reaction and re-renders that card in place with the new mark, without throwing when a reset replaced the grid mid-request."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_40_search_card_actions_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_40_search_card_actions_phase2.py  4 failed                               0.0s\n  -----------------------------------------------\n  total                                            4 failed                               2.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_40_search_card_actions_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_40_search_card_actions_phase3.py:290 \u2014 the requests sent after the click, in order: POST /api/profile/blocks {kind, uuid, host}, then POST /api/user-action dislike for that video, then GET search page 3",
          "expected": "[[\"POST\",\"/api/profile/blocks\",{\"kind\":kind,\"uuid\":\"uuid-a1\",\"host\":\"peer.example\"}],[\"POST\",\"/api/user-action\",{\"action\":\"dislike\",\"uuid\":\"uuid-a1\",\"host\":\"peer.example\"}],[\"GET\",\"/api/v1/search/videos\",\"music\",\"3\"]]",
          "wrong_implementation": "A page with no fillViewport() after the removal has no page-3 GET in its calls (seen in the no_fill probe). A page that skips the dislike, or sends it before the block, gives the wrong sequence. The current page with no Block branch sends []."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_40_search_card_actions_phase3.py:292 \u2014 the titles left in the grid after the removal",
          "expected": "channel: [\"video a2\",\"video k1\",\"video a3\",\"video b2\"]; account: [\"video k1\",\"video a3\",\"video b2\"]",
          "wrong_implementation": "Removing only the clicked card leaves b1 and k2 in the grid. Matching on channel_id without instance_domain also removes a3. Matching a channel block on account removes a2. Matching an account block on channel keeps a2."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_40_search_card_actions_phase3.py:294 \u2014 #search-status after the removal and the empty page-3 refill",
          "expected": "\"Showing 7 of 9 matched videos.\"",
          "wrong_implementation": "Recounting the status from the cards left reads \"Showing 4 of 9 matched videos.\" (channel) and \"Showing 3 of 9 matched videos.\" (account), both seen in the recount probe. Writing the block result into #search-status also changes the text."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_40_search_card_actions_phase3.py:304 \u2014 the clicked card's .card-action-status text when the dislike answers 500",
          "expected": "channel with label \"Alice's channel\": \"Blocked Alice's channel, but the dislike failed: reaction store unavailable\"; account with empty label: \"Blocked account, but the dislike failed: reaction store unavailable\"",
          "wrong_implementation": "Showing only the dislike error, showing nothing (the current page reads \"\"), showing a generic message in place of the server's error, or rendering \"Blocked , but the dislike failed: ...\" when the label is empty."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_40_search_card_actions_phase3.py:308 \u2014 the grid after the failed dislike, armed by :306, which shows the block and the failing dislike were both sent",
          "expected": "[\"video a1\",\"video a2\",\"video k1\",\"video a3\",\"video b1\",\"video b2\",\"video k2\"]",
          "wrong_implementation": "Removing the source's cards whatever the dislike returned leaves the channel-block grid as [a2,k1,a3,b2] and the account-block grid as [k1,a3,b2]."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A successful block followed by a successful dislike removes every loaded card of that channel or account, refills the viewport and leaves the status text unchanged."
        },
        {
          "id": "C2",
          "text": "A block whose dislike fails reports `Blocked <label|action>, but the dislike failed: <msg>` and removes no card."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_40_search_card_actions_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_40_search_card_actions_phase3.py  4 failed                               0.0s\n  -----------------------------------------------\n  total                                            4 failed                               1.6s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_40_search_card_actions_phase4.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_40_search_card_actions_phase4.py:294 \u2014 for each of dislike, channel and account with no profile key, the click adds no request to the stub's log. Also :296 \u2014 the clicked card's `.card-action-status` equals home's exact prompt. The control at :298 shows the stub records a keyless Like in the same run.",
          "expected": ":294 `[]`. :296 \"Disliking needs a profile. Create one from the Profile button.\" for dislike, and \"Blocking needs a profile. Create one from the Profile button.\" for channel and account.",
          "wrong_implementation": "The current unguarded page sends `[\"POST\",\"/api/user-action\",{\"action\":\"dislike\",...}]` for dislike and `[\"POST\",\"/api/profile/blocks\",{\"kind\":...}]` plus the follow-up dislike for a block, and fails :294 in all three cases (observed). A guard on Dislike only fails the channel and account cases at :294. One prompt hard-coded for every action, or the server's error shown instead, fails :296."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_40_search_card_actions_phase4.py:324/:326/:328/:330/:333/:334, over like/dislike/channel/account \u00d7 neutral/liked, after that action's request is rejected. :324 the card is still on the grid. :326 the status line equals the action's error. :328 the clicked button is enabled; :321 shows it was disabled while held. :330 the card's like/dislike marks are as they were. :333 a following Dislike then Like send `dislike` then `like` (neutral) or `dislike` then `undo_like` (liked). :334 no error escapes.",
          "expected": "Status \"Video not found in Engine\" for like, \"Dislike limit reached (1000)\" for dislike, \"Block limit reached (1000)\" for channel and account. `disabled` False. Marks NEUTRAL or LIKED as the run started. :333 gives `[[dislike],[like]]` from neutral and `[[dislike],[undo_like]]` from liked.",
          "wrong_implementation": "Each observed with a mutant probe. Setting `row.reaction` before the like request fails :333 in both like cases. Redrawing the like before the request fails :326, because the redraw wipes the status. Flipping the row to disliked before a block fails :333 in all block cases. Removing the source's rows before the block is accepted fails :324. Dropping the re-enable in `finally` fails :328 in all 8 cases. A generic \"Action failed\" fails :326 in all 8. Clearing a liked row to null on rejection fails :333 in the liked cases. Setting the row to disliked before the dislike request fails :333."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Without a profile key, Dislike, Block channel and Block account each write home's exact profile prompt and send no request."
        },
        {
          "id": "C2",
          "text": "A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_40_search_card_actions_phase4.py",
        "code": 1,
        "output": "  tests/tmp/test_40_search_card_actions_phase4.py  3 failed, 8 passed                     0.0s\n  -----------------------------------------------\n  total                                            3 failed, 8 passed                     5.7s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_40_search_card_actions_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. absence-only-assertion (rules/shape.md), but not at Critical severity \u2014 tests/tmp/test_40_search_card_actions_phase1.py:78\n   assert [line for line in proc.stdout.splitlines() if \"src/components/video-card.ts\" in line] == []\n   The test's only claim about the changed file is a negative one, so it passes on the code as it stands. If the Dislike change is never written, it stays green, which means it does not gate C1. It is not Critical because line 77 pairs it with a positive control (`proc.returncode in (0, 2)`), showing tsc actually ran and checked. That is what the entry's `<alternatives>` asks for: \"assert what DID happen\". Treat it as a regression guard that comes with this test, not as evidence for C1.\n\nPREDICTED FAILURE\n`test_the_dislike_button_is_pressed_only_when_the_reaction_is_disliked` fails at line 67: `cards[\"disliked\"][\"dislike\"][0].get(\"aria-pressed\")` returns `None`, not `\"true\"`, because the Dislike button at video-card.ts:356 has no `aria-pressed` attribute. The line-65 control passes first, because ROW has both `video_uuid` and `instance_domain`, so `videoKey` resolves and the actions markup renders. `test_the_type_check_reports_no_error_in_the_video_card_component` is expected to pass.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py, which does not exist (FileNotFoundError), so it was not read. The audit used client/frontend/src/components/video-card.ts only.\n2. Whether `client/frontend/node_modules/.bin/esbuild` and `node` exist was not checked. If either is missing, the test fails at line 51 or line 58 instead of the predicted line 67. Running the test would show this, and the auditor does not run tests.\n\nLadder pass (no finding): test 1 calls `renderVideoCard` directly through a Node bundle and parses the returned HTML with `HTMLParser` before asserting on attribute values. That puts it at rung 1, with no substring-in-prose and no downshift. Test 2 is rung 2: it runs tsc as a subprocess and asserts on the exit code and stdout.\n\nStub question (no finding): test 1 checks the Dislike button with four inputs and asserts the difference between them. `\"true\"` is expected only for `\"disliked\"`; `\"false\"` is expected for `null`, `\"liked\"` and an omitted reaction. A hard-coded `\"true\"` fails line 68. A hard-coded `\"false\"` or a missing attribute fails line 67. Copying the Like button's `reaction === \"liked\"` expression fails lines 67 and 69. Lines 71\u201372 check that the Like button still reports its own state.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (12 clauses: 4 must_prove, 5 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | Dislike button has `aria-pressed=\"true\"` when `options.reaction` is `\"disliked\"` | :67 | a Dislike button with no `aria-pressed`, or one that never reads `\"true\"` (returns `None` or `\"false\"`) | CARRIED |\n| C1b | must_prove | `aria-pressed=\"false\"` otherwise: reaction `null` | :68 | the attribute missing on a null reaction, or always set to `\"true\"` | CARRIED |\n| C1c | must_prove | `aria-pressed=\"false\"` otherwise: reaction `\"liked\"` | :69 | Dislike pressed by any non-null reaction (`!!reaction`), or wired to the like state | CARRIED |\n| C1d | must_prove | `aria-pressed=\"false\"` otherwise: `reaction` omitted | :70 | an undefined reaction producing a missing attribute or `\"undefined\"` and not `\"false\"` | CARRIED |\n| D1 | docstring | \"with `actions: true` on a keyed row, the `[data-card-action=\"dislike\"]` button\" is rendered | :65 | no Dislike button, or a duplicate, in any of the four renders | CARRIED |\n| D2 | docstring | \"carries `aria-pressed=\"true\"` when `reaction` is `\"disliked\"`\" | :67 | same as C1a | CARRIED |\n| D3 | docstring | \"`aria-pressed=\"false\"` when it is `null`, `\"liked\"` or omitted\" | :68, :69, :70 | each of the three \"otherwise\" values asserted separately, as in C1b\u2013C1d | CARRIED |\n| D4 | docstring | \"`npx tsc --noEmit` ... reports no error in `src/components/video-card.ts`\" | :78 | a type error in the changed file, such as a non-string attribute interpolation | CARRIED |\n| D5 | docstring | the type check \"is scoped to the changed file\" and really ran | :77, :78 | tsc failing to start (an exit code other than 0 or 2) being read as clean; errors in unrelated pages failing the test | CARRIED |\n| N1 | name | \"the dislike button is pressed ... when the reaction is disliked\" | :67 | an unpressed or attribute-less Dislike button under `\"disliked\"` | CARRIED |\n| N2 | name | \"only\" when disliked | :68, :69, :70 | pressed under null, liked or omitted | CARRIED |\n| N3 | name | \"the type check reports no error in the video card component\" | :78 | any tsc diagnostic line naming `src/components/video-card.ts` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase1.py:22\n   Every render uses `actions: true` on a keyed `ROW`. Nothing checks the case where no button should exist: `actions` false or omitted, or a row with no `instance_domain`/`video_uuid`, so `resolveVideoKey` returns null. A Dislike button leaking onto those cards with any `aria-pressed` value would not fail this test. C1 does not require that case, so this is not a Critical.\n2. checkpoint_definition (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase1.py:75\n   `test_the_type_check_reports_no_error_in_the_video_card_component` is a compiler/lint run. `<checkpoint_definition>` says that kind of check is not checkpoint evidence. It carries no `must_prove` clause, and C1 is fully carried by the functional test at :62. So the checkpoint does meet the definition, but this second test should not be counted as gating evidence for the phase.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py (NEW), which does not exist at that path. Whatever that file was meant to contribute was not assessed. The audit used the test file and client/frontend/src/components/video-card.ts.\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines no other fixture, so no conftest was needed for the independence check.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. absence-only-assertion (rules/shape.md), but not at Critical severity \u2014 tests/tmp/test_40_search_card_actions_phase1.py:78\n   assert [line for line in proc.stdout.splitlines() if \"src/components/video-card.ts\" in line] == []\n   The test's only claim about the changed file is a negative one, so it passes on the code as it stands. If the Dislike change is never written, it stays green, which means it does not gate C1. It is not Critical because line 77 pairs it with a positive control (`proc.returncode in (0, 2)`), showing tsc actually ran and checked. That is what the entry's `<alternatives>` asks for: \"assert what DID happen\". Treat it as a regression guard that comes with this test, not as evidence for C1.\n\nPREDICTED FAILURE\n`test_the_dislike_button_is_pressed_only_when_the_reaction_is_disliked` fails at line 67: `cards[\"disliked\"][\"dislike\"][0].get(\"aria-pressed\")` returns `None`, not `\"true\"`, because the Dislike button at video-card.ts:356 has no `aria-pressed` attribute. The line-65 control passes first, because ROW has both `video_uuid` and `instance_domain`, so `videoKey` resolves and the actions markup renders. `test_the_type_check_reports_no_error_in_the_video_card_component` is expected to pass.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py, which does not exist (FileNotFoundError), so it was not read. The audit used client/frontend/src/components/video-card.ts only.\n2. Whether `client/frontend/node_modules/.bin/esbuild` and `node` exist was not checked. If either is missing, the test fails at line 51 or line 58 instead of the predicted line 67. Running the test would show this, and the auditor does not run tests.\n\nLadder pass (no finding): test 1 calls `renderVideoCard` directly through a Node bundle and parses the returned HTML with `HTMLParser` before asserting on attribute values. That puts it at rung 1, with no substring-in-prose and no downshift. Test 2 is rung 2: it runs tsc as a subprocess and asserts on the exit code and stdout.\n\nStub question (no finding): test 1 checks the Dislike button with four inputs and asserts the difference between them. `\"true\"` is expected only for `\"disliked\"`; `\"false\"` is expected for `null`, `\"liked\"` and an omitted reaction. A hard-coded `\"true\"` fails line 68. A hard-coded `\"false\"` or a missing attribute fails line 67. Copying the Like button's `reaction === \"liked\"` expression fails lines 67 and 69. Lines 71\u201372 check that the Like button still reports its own state.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (12 clauses: 4 must_prove, 5 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | Dislike button has `aria-pressed=\"true\"` when `options.reaction` is `\"disliked\"` | :67 | a Dislike button with no `aria-pressed`, or one that never reads `\"true\"` (returns `None` or `\"false\"`) | CARRIED |\n| C1b | must_prove | `aria-pressed=\"false\"` otherwise: reaction `null` | :68 | the attribute missing on a null reaction, or always set to `\"true\"` | CARRIED |\n| C1c | must_prove | `aria-pressed=\"false\"` otherwise: reaction `\"liked\"` | :69 | Dislike pressed by any non-null reaction (`!!reaction`), or wired to the like state | CARRIED |\n| C1d | must_prove | `aria-pressed=\"false\"` otherwise: `reaction` omitted | :70 | an undefined reaction producing a missing attribute or `\"undefined\"` and not `\"false\"` | CARRIED |\n| D1 | docstring | \"with `actions: true` on a keyed row, the `[data-card-action=\"dislike\"]` button\" is rendered | :65 | no Dislike button, or a duplicate, in any of the four renders | CARRIED |\n| D2 | docstring | \"carries `aria-pressed=\"true\"` when `reaction` is `\"disliked\"`\" | :67 | same as C1a | CARRIED |\n| D3 | docstring | \"`aria-pressed=\"false\"` when it is `null`, `\"liked\"` or omitted\" | :68, :69, :70 | each of the three \"otherwise\" values asserted separately, as in C1b\u2013C1d | CARRIED |\n| D4 | docstring | \"`npx tsc --noEmit` ... reports no error in `src/components/video-card.ts`\" | :78 | a type error in the changed file, such as a non-string attribute interpolation | CARRIED |\n| D5 | docstring | the type check \"is scoped to the changed file\" and really ran | :77, :78 | tsc failing to start (an exit code other than 0 or 2) being read as clean; errors in unrelated pages failing the test | CARRIED |\n| N1 | name | \"the dislike button is pressed ... when the reaction is disliked\" | :67 | an unpressed or attribute-less Dislike button under `\"disliked\"` | CARRIED |\n| N2 | name | \"only\" when disliked | :68, :69, :70 | pressed under null, liked or omitted | CARRIED |\n| N3 | name | \"the type check reports no error in the video card component\" | :78 | any tsc diagnostic line naming `src/components/video-card.ts` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase1.py:22\n   Every render uses `actions: true` on a keyed `ROW`. Nothing checks the case where no button should exist: `actions` false or omitted, or a row with no `instance_domain`/`video_uuid`, so `resolveVideoKey` returns null. A Dislike button leaking onto those cards with any `aria-pressed` value would not fail this test. C1 does not require that case, so this is not a Critical.\n2. checkpoint_definition (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase1.py:75\n   `test_the_type_check_reports_no_error_in_the_video_card_component` is a compiler/lint run. `<checkpoint_definition>` says that kind of check is not checkpoint evidence. It carries no `must_prove` clause, and C1 is fully carried by the functional test at :62. So the checkpoint does meet the definition, but this second test should not be counted as gating evidence for the phase.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py (NEW), which does not exist at that path. Whatever that file was meant to contribute was not assessed. The audit used the test file and client/frontend/src/components/video-card.ts.\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines no other fixture, so no conftest was needed for the independence check.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "Dislike button has `aria-pressed=\"true\"` when `options.reaction` is `\"disliked\"`",
            "assertion": ":67",
            "excludes": "a Dislike button with no `aria-pressed`, or one that never reads `\"true\"` (returns `None` or `\"false\"`)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "`aria-pressed=\"false\"` otherwise: reaction `null`",
            "assertion": ":68",
            "excludes": "the attribute missing on a null reaction, or always set to `\"true\"`",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "`aria-pressed=\"false\"` otherwise: reaction `\"liked\"`",
            "assertion": ":69",
            "excludes": "Dislike pressed by any non-null reaction (`!!reaction`), or wired to the like state",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "`aria-pressed=\"false\"` otherwise: `reaction` omitted",
            "assertion": ":70",
            "excludes": "an undefined reaction producing a missing attribute or `\"undefined\"` and not `\"false\"`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"with `actions: true` on a keyed row, the `[data-card-action=\"dislike\"]` button\" is rendered",
            "assertion": ":65",
            "excludes": "no Dislike button, or a duplicate, in any of the four renders",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"carries `aria-pressed=\"true\"` when `reaction` is `\"disliked\"`\"",
            "assertion": ":67",
            "excludes": "same as C1a",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"`aria-pressed=\"false\"` when it is `null`, `\"liked\"` or omitted\"",
            "assertion": ":68, :69, :70",
            "excludes": "each of the three \"otherwise\" values asserted separately, as in C1b\u2013C1d",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"`npx tsc --noEmit` ... reports no error in `src/components/video-card.ts`\"",
            "assertion": ":78",
            "excludes": "a type error in the changed file, such as a non-string attribute interpolation",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "the type check \"is scoped to the changed file\" and really ran",
            "assertion": ":77, :78",
            "excludes": "tsc failing to start (an exit code other than 0 or 2) being read as clean; errors in unrelated pages failing the test",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"the dislike button is pressed ... when the reaction is disliked\"",
            "assertion": ":67",
            "excludes": "an unpressed or attribute-less Dislike button under `\"disliked\"`",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"only\" when disliked",
            "assertion": ":68, :69, :70",
            "excludes": "pressed under null, liked or omitted",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"the type check reports no error in the video card component\"",
            "assertion": ":78",
            "excludes": "any tsc diagnostic line naming `src/components/video-card.ts`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_40_search_card_actions_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_keyed_cards_on_both_pages_carry_the_controls_and_like_and_dislike_toggle_and_redraw_the_card_in_place` fails at line 306 (`assert {c[\"key\"]: c[\"actions\"] for c in page[\"grid\"] if c[\"key\"]} == {_key(r): ACTIONS ...}`). The keyed cards' `actions` lists come back `[]`, because `renderRows` in `pages/search/index.ts:208` calls `renderVideoCard(row, { apiParam, reaction: cardReaction(row) })` without `actions: true`. The other two tests fail on the same cause: the second at line 332 and the third at line 348.\n\nNOT ASSESSED\n1. `code_under_test` listed `tests/tmp/test_frontend_search_card_actions.py`, which does not exist. Nothing the test under audit uses depends on it. The stub question was answered from `pages/search/index.ts`, `components/video-card.ts` and the test's own runner.\n2. `fixtures_path` was not supplied. The only fixture the test uses, `search_bundle`, is defined in the test file itself (lines 253\u2013255), so no conftest was needed.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (34 clauses: 9 must_prove, 17 docstring, 8 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | every keyed card on the first page has the four `[data-card-action]` controls | :306 | the page passing no `actions`, or a card missing any of like/dislike/channel/account (exact ordered list per key) | CARRIED |\n| C1b | must_prove | every keyed card on an appended page has the four controls | :306 | actions passed only on the reset path, so page-2 cards from `insertAdjacentHTML` stay bare (b1, b2 keys in the expected map; :303 shows page 2 was appended) | CARRIED |\n| C1c | must_prove | a keyless card has none | :307 | controls rendered on a card with no video key, on either page | CARRIED |\n| C2a | must_prove | a Like click sends the toggled reaction | :316 | always sending `like`; sending `undo_like` on a disliked card (step 4 expects `like`, step 5 `undo_like`) | CARRIED |\n| C2b | must_prove | a Dislike click sends the toggled reaction | :316 | always sending `dislike` (step 2 expects `undo_dislike`), or the wrong uuid/host | CARRIED |\n| C2c | must_prove | re-renders that card with the new mark | :318 | sending without redrawing (the previous mark stays); redrawing from a stale reaction | CARRIED |\n| C2d | must_prove | in place | :321, :322 | the redrawn card appended at the end or moved; a neighbouring card's state changed | CARRIED |\n| C2e | must_prove | a Like does not throw when a reset replaced the grid mid-request | :356 (control :353) | `outerHTML` set on the detached card, which the fake throws on at :108 | CARRIED |\n| C2f | must_prove | a Dislike does not throw when a reset replaced the grid mid-request | none | nothing: the reset scenario clicks only Like (:224, :235) | UNCARRIED |\n| D1 | docstring | \"carry the card controls on every loaded page\" | :306 | page-2 cards without controls | CARRIED |\n| D2 | docstring | \"Like and Dislike on one toggle the reaction and redraw that card in place\" | :316, :318, :321 | a non-toggling send, no redraw, a moved card | CARRIED |\n| D3 | docstring | \"every keyed card has the like, dislike, channel and account buttons, and the keyless card on each page has none\" | :306, :307 | any member of the set missing; controls on keyless cards k1/k2 | CARRIED |\n| D4 | docstring | \"Dislike\u00d73, Like\u00d72 send dislike, undo_dislike, dislike, like, undo_like for that video\" | :316 | a wrong action at any step, or the wrong video | CARRIED |\n| D5 | docstring | \"disliked \u2026 then neutral, then disliked, then liked and not disliked, then neutral\" (stat active + aria-pressed) | :318 | a missing stat class or aria-pressed; liked and disliked both set | CARRIED |\n| D6 | docstring | \"stays at its position with its four controls\" | :321, :319 | a reorder; a redraw that drops `actions` | CARRIED |\n| D7 | docstring | \"no other card changes\" | :322 | a change to any other card's key, title, controls or marks | CARRIED |\n| D8 | docstring | \"Without a key, the keyed cards carry the same four controls and the keyless card none\" | :332 | controls only for a profile holder | CARRIED |\n| D9 | docstring | \"Like sends `like`\" (no key) | :335 | asking for a profile and sending nothing | CARRIED |\n| D10 | docstring | \"`localLikes:v1` then holds the video\" | :336 (control :330) | not storing, or storing the wrong video | CARRIED |\n| D11 | docstring | \"the card shows liked\" (no key) | :337 | no redraw from the local likes | CARRIED |\n| D12 | docstring | \"the first search's cards carry the four controls\" | :348 | the reset render without actions | CARRIED |\n| D13 | docstring | \"resolves without an error escaping\" | :356 | a throw from the detached-card redraw | CARRIED |\n| D14 | docstring | \"without writing an error into the clicked card's status line\" | :357 | catching the throw and reporting it on the card | CARRIED |\n| D15 | docstring | \"The grid holds the new search's cards, all unmarked\" | :359, :360 | the resolved Like redrawing into, or marking, the new grid | CARRIED |\n| D16 | docstring | \"a following Like on the shared video sends `like`, not `undo_like`\" | :362, :363 | a row list the reset did not clear | CARRIED |\n| D17 | docstring | \"The fake DOM throws when outerHTML is set on an element with no parent\" | :108 (harness) | a statement about the harness, made true by construction | CARRIED |\n| N1 | name | \"keyed cards on both pages carry the controls\" | :306 | page-2 cards without controls | CARRIED |\n| N2 | name | \"like and dislike toggle\" | :316 | a non-toggling send | CARRIED |\n| N3 | name | \"and redraw the card in place\" | :318, :321, :322 | no redraw; a moved card | CARRIED |\n| N4 | name | \"a keyless like is sent\" | :335 | nothing sent without a profile | CARRIED |\n| N5 | name | \"stored in the local likes\" | :336 | no local store write | CARRIED |\n| N6 | name | \"and shown on the card\" | :337 | the card left unmarked | CARRIED |\n| N7 | name | \"a like resolving after a new search replaced the grid leaves the new cards \u2026 alone\" | :359, :360 | the stale Like marking or replacing a new card | CARRIED |\n| N8 | name | \"\u2026 and rows alone\" | :362 | a leftover first-search row causing `undo_like` | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:224\n   `report.held = await step(target, \"like\");`\n   C2 says \"A Like **or Dislike** click \u2026 without throwing when a reset replaced the grid mid-request\". That names a set of two, and the whole-claim principle says a set gets an assertion for every member. The reset scenario only sends a Like, at :224 and again at :235, so :356 and :357 cover only the Like path. Some wrong implementations would still pass. One is a page whose Dislike branch redraws through `card.outerHTML` without checking whether the card is still connected, while its Like branch does check. That shape is realistic: the precedent `pages/videos/index.ts:415-422` handles like and dislike in separate branches. To cover C2f, the test needs a Dislike held across a reset, with errors and the clicked card's status asserted the same way. The other option is an operator exemption for C2f.\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:166-169\n   The stub always returns 200 for `/api/user-action`. A refused reaction request is never tested: what the card shows, what the status line says, and whether the mark stays unchanged. The same goes for a visitor with no profile key pressing Dislike. `must_prove` does not claim either case, so neither blocks.\n2. bounds (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:272-274\n   The only keyless row has neither a uuid nor an id. The other ways a row can lack a key are untested: a uuid with no `instance_domain`, or a `video_id` with no `video_uuid`. `resolveVideoKey` treats the second one as keyed, and `_key` at :277-278 would not.\n3. name-as-sentence (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:326\n   In this name, \"keyless\" means a visitor with no profile key. At :307 and in C1, \"keyless\" means a card whose row has no video key. A failure in the runner output would read ambiguously; \"a like without a profile key \u2026\" would not.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not resolve (no match under tests/). Nothing in it was assessed.\n2. The supplied client/frontend/src/pages/search/index.ts contains no card-action handler. I judged what the page's markup and actions would be from the shared `components/video-card.ts`, `data/reactions.ts`, and the `pages/videos/index.ts` precedent.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_keyed_cards_on_both_pages_carry_the_controls_and_like_and_dislike_toggle_and_redraw_the_card_in_place` fails at line 306 (`assert {c[\"key\"]: c[\"actions\"] for c in page[\"grid\"] if c[\"key\"]} == {_key(r): ACTIONS ...}`). The keyed cards' `actions` lists come back `[]`, because `renderRows` in `pages/search/index.ts:208` calls `renderVideoCard(row, { apiParam, reaction: cardReaction(row) })` without `actions: true`. The other two tests fail on the same cause: the second at line 332 and the third at line 348.\n\nNOT ASSESSED\n1. `code_under_test` listed `tests/tmp/test_frontend_search_card_actions.py`, which does not exist. Nothing the test under audit uses depends on it. The stub question was answered from `pages/search/index.ts`, `components/video-card.ts` and the test's own runner.\n2. `fixtures_path` was not supplied. The only fixture the test uses, `search_bundle`, is defined in the test file itself (lines 253\u2013255), so no conftest was needed.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (34 clauses: 9 must_prove, 17 docstring, 8 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | every keyed card on the first page has the four `[data-card-action]` controls | :306 | the page passing no `actions`, or a card missing any of like/dislike/channel/account (exact ordered list per key) | CARRIED |\n| C1b | must_prove | every keyed card on an appended page has the four controls | :306 | actions passed only on the reset path, so page-2 cards from `insertAdjacentHTML` stay bare (b1, b2 keys in the expected map; :303 shows page 2 was appended) | CARRIED |\n| C1c | must_prove | a keyless card has none | :307 | controls rendered on a card with no video key, on either page | CARRIED |\n| C2a | must_prove | a Like click sends the toggled reaction | :316 | always sending `like`; sending `undo_like` on a disliked card (step 4 expects `like`, step 5 `undo_like`) | CARRIED |\n| C2b | must_prove | a Dislike click sends the toggled reaction | :316 | always sending `dislike` (step 2 expects `undo_dislike`), or the wrong uuid/host | CARRIED |\n| C2c | must_prove | re-renders that card with the new mark | :318 | sending without redrawing (the previous mark stays); redrawing from a stale reaction | CARRIED |\n| C2d | must_prove | in place | :321, :322 | the redrawn card appended at the end or moved; a neighbouring card's state changed | CARRIED |\n| C2e | must_prove | a Like does not throw when a reset replaced the grid mid-request | :356 (control :353) | `outerHTML` set on the detached card, which the fake throws on at :108 | CARRIED |\n| C2f | must_prove | a Dislike does not throw when a reset replaced the grid mid-request | none | nothing: the reset scenario clicks only Like (:224, :235) | UNCARRIED |\n| D1 | docstring | \"carry the card controls on every loaded page\" | :306 | page-2 cards without controls | CARRIED |\n| D2 | docstring | \"Like and Dislike on one toggle the reaction and redraw that card in place\" | :316, :318, :321 | a non-toggling send, no redraw, a moved card | CARRIED |\n| D3 | docstring | \"every keyed card has the like, dislike, channel and account buttons, and the keyless card on each page has none\" | :306, :307 | any member of the set missing; controls on keyless cards k1/k2 | CARRIED |\n| D4 | docstring | \"Dislike\u00d73, Like\u00d72 send dislike, undo_dislike, dislike, like, undo_like for that video\" | :316 | a wrong action at any step, or the wrong video | CARRIED |\n| D5 | docstring | \"disliked \u2026 then neutral, then disliked, then liked and not disliked, then neutral\" (stat active + aria-pressed) | :318 | a missing stat class or aria-pressed; liked and disliked both set | CARRIED |\n| D6 | docstring | \"stays at its position with its four controls\" | :321, :319 | a reorder; a redraw that drops `actions` | CARRIED |\n| D7 | docstring | \"no other card changes\" | :322 | a change to any other card's key, title, controls or marks | CARRIED |\n| D8 | docstring | \"Without a key, the keyed cards carry the same four controls and the keyless card none\" | :332 | controls only for a profile holder | CARRIED |\n| D9 | docstring | \"Like sends `like`\" (no key) | :335 | asking for a profile and sending nothing | CARRIED |\n| D10 | docstring | \"`localLikes:v1` then holds the video\" | :336 (control :330) | not storing, or storing the wrong video | CARRIED |\n| D11 | docstring | \"the card shows liked\" (no key) | :337 | no redraw from the local likes | CARRIED |\n| D12 | docstring | \"the first search's cards carry the four controls\" | :348 | the reset render without actions | CARRIED |\n| D13 | docstring | \"resolves without an error escaping\" | :356 | a throw from the detached-card redraw | CARRIED |\n| D14 | docstring | \"without writing an error into the clicked card's status line\" | :357 | catching the throw and reporting it on the card | CARRIED |\n| D15 | docstring | \"The grid holds the new search's cards, all unmarked\" | :359, :360 | the resolved Like redrawing into, or marking, the new grid | CARRIED |\n| D16 | docstring | \"a following Like on the shared video sends `like`, not `undo_like`\" | :362, :363 | a row list the reset did not clear | CARRIED |\n| D17 | docstring | \"The fake DOM throws when outerHTML is set on an element with no parent\" | :108 (harness) | a statement about the harness, made true by construction | CARRIED |\n| N1 | name | \"keyed cards on both pages carry the controls\" | :306 | page-2 cards without controls | CARRIED |\n| N2 | name | \"like and dislike toggle\" | :316 | a non-toggling send | CARRIED |\n| N3 | name | \"and redraw the card in place\" | :318, :321, :322 | no redraw; a moved card | CARRIED |\n| N4 | name | \"a keyless like is sent\" | :335 | nothing sent without a profile | CARRIED |\n| N5 | name | \"stored in the local likes\" | :336 | no local store write | CARRIED |\n| N6 | name | \"and shown on the card\" | :337 | the card left unmarked | CARRIED |\n| N7 | name | \"a like resolving after a new search replaced the grid leaves the new cards \u2026 alone\" | :359, :360 | the stale Like marking or replacing a new card | CARRIED |\n| N8 | name | \"\u2026 and rows alone\" | :362 | a leftover first-search row causing `undo_like` | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:224\n   `report.held = await step(target, \"like\");`\n   C2 says \"A Like **or Dislike** click \u2026 without throwing when a reset replaced the grid mid-request\". That names a set of two, and the whole-claim principle says a set gets an assertion for every member. The reset scenario only sends a Like, at :224 and again at :235, so :356 and :357 cover only the Like path. Some wrong implementations would still pass. One is a page whose Dislike branch redraws through `card.outerHTML` without checking whether the card is still connected, while its Like branch does check. That shape is realistic: the precedent `pages/videos/index.ts:415-422` handles like and dislike in separate branches. To cover C2f, the test needs a Dislike held across a reset, with errors and the clicked card's status asserted the same way. The other option is an operator exemption for C2f.\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:166-169\n   The stub always returns 200 for `/api/user-action`. A refused reaction request is never tested: what the card shows, what the status line says, and whether the mark stays unchanged. The same goes for a visitor with no profile key pressing Dislike. `must_prove` does not claim either case, so neither blocks.\n2. bounds (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:272-274\n   The only keyless row has neither a uuid nor an id. The other ways a row can lack a key are untested: a uuid with no `instance_domain`, or a `video_id` with no `video_uuid`. `resolveVideoKey` treats the second one as keyed, and `_key` at :277-278 would not.\n3. name-as-sentence (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:326\n   In this name, \"keyless\" means a visitor with no profile key. At :307 and in C1, \"keyless\" means a card whose row has no video key. A failure in the runner output would read ambiguously; \"a like without a profile key \u2026\" would not.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not resolve (no match under tests/). Nothing in it was assessed.\n2. The supplied client/frontend/src/pages/search/index.ts contains no card-action handler. I judged what the page's markup and actions would be from the shared `components/video-card.ts`, `data/reactions.ts`, and the `pages/videos/index.ts` precedent.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "every keyed card on the first page has the four `[data-card-action]` controls",
            "assertion": ":306",
            "excludes": "the page passing no `actions`, or a card missing any of like/dislike/channel/account (exact ordered list per key)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "every keyed card on an appended page has the four controls",
            "assertion": ":306",
            "excludes": "actions passed only on the reset path, so page-2 cards from `insertAdjacentHTML` stay bare (b1, b2 keys in the expected map; :303 shows page 2 was appended)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "a keyless card has none",
            "assertion": ":307",
            "excludes": "controls rendered on a card with no video key, on either page",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a Like click sends the toggled reaction",
            "assertion": ":316",
            "excludes": "always sending `like`; sending `undo_like` on a disliked card (step 4 expects `like`, step 5 `undo_like`)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "a Dislike click sends the toggled reaction",
            "assertion": ":316",
            "excludes": "always sending `dislike` (step 2 expects `undo_dislike`), or the wrong uuid/host",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "re-renders that card with the new mark",
            "assertion": ":318",
            "excludes": "sending without redrawing (the previous mark stays); redrawing from a stale reaction",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "in place",
            "assertion": ":321, :322",
            "excludes": "the redrawn card appended at the end or moved; a neighbouring card's state changed",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "a Like does not throw when a reset replaced the grid mid-request",
            "assertion": ":356 (control :353)",
            "excludes": "`outerHTML` set on the detached card, which the fake throws on at :108",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "a Dislike does not throw when a reset replaced the grid mid-request",
            "assertion": "none",
            "excludes": "nothing: the reset scenario clicks only Like (:224, :235)",
            "status": "UNCARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"carry the card controls on every loaded page\"",
            "assertion": ":306",
            "excludes": "page-2 cards without controls",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"Like and Dislike on one toggle the reaction and redraw that card in place\"",
            "assertion": ":316, :318, :321",
            "excludes": "a non-toggling send, no redraw, a moved card",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"every keyed card has the like, dislike, channel and account buttons, and the keyless card on each page has none\"",
            "assertion": ":306, :307",
            "excludes": "any member of the set missing; controls on keyless cards k1/k2",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"Dislike\u00d73, Like\u00d72 send dislike, undo_dislike, dislike, like, undo_like for that video\"",
            "assertion": ":316",
            "excludes": "a wrong action at any step, or the wrong video",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"disliked \u2026 then neutral, then disliked, then liked and not disliked, then neutral\" (stat active + aria-pressed)",
            "assertion": ":318",
            "excludes": "a missing stat class or aria-pressed; liked and disliked both set",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"stays at its position with its four controls\"",
            "assertion": ":321, :319",
            "excludes": "a reorder; a redraw that drops `actions`",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"no other card changes\"",
            "assertion": ":322",
            "excludes": "a change to any other card's key, title, controls or marks",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"Without a key, the keyed cards carry the same four controls and the keyless card none\"",
            "assertion": ":332",
            "excludes": "controls only for a profile holder",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"Like sends `like`\" (no key)",
            "assertion": ":335",
            "excludes": "asking for a profile and sending nothing",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"`localLikes:v1` then holds the video\"",
            "assertion": ":336 (control :330)",
            "excludes": "not storing, or storing the wrong video",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"the card shows liked\" (no key)",
            "assertion": ":337",
            "excludes": "no redraw from the local likes",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the first search's cards carry the four controls\"",
            "assertion": ":348",
            "excludes": "the reset render without actions",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"resolves without an error escaping\"",
            "assertion": ":356",
            "excludes": "a throw from the detached-card redraw",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"without writing an error into the clicked card's status line\"",
            "assertion": ":357",
            "excludes": "catching the throw and reporting it on the card",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"The grid holds the new search's cards, all unmarked\"",
            "assertion": ":359, :360",
            "excludes": "the resolved Like redrawing into, or marking, the new grid",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"a following Like on the shared video sends `like`, not `undo_like`\"",
            "assertion": ":362, :363",
            "excludes": "a row list the reset did not clear",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"The fake DOM throws when outerHTML is set on an element with no parent\"",
            "assertion": ":108 (harness)",
            "excludes": "a statement about the harness, made true by construction",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"keyed cards on both pages carry the controls\"",
            "assertion": ":306",
            "excludes": "page-2 cards without controls",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"like and dislike toggle\"",
            "assertion": ":316",
            "excludes": "a non-toggling send",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and redraw the card in place\"",
            "assertion": ":318, :321, :322",
            "excludes": "no redraw; a moved card",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a keyless like is sent\"",
            "assertion": ":335",
            "excludes": "nothing sent without a profile",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"stored in the local likes\"",
            "assertion": ":336",
            "excludes": "no local store write",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"and shown on the card\"",
            "assertion": ":337",
            "excludes": "the card left unmarked",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"a like resolving after a new search replaced the grid leaves the new cards \u2026 alone\"",
            "assertion": ":359, :360",
            "excludes": "the stale Like marking or replacing a new card",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "\"\u2026 and rows alone\"",
            "assertion": ":362",
            "excludes": "a leftover first-search row causing `undo_like`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_keyed_cards_on_both_pages_carry_the_controls_and_like_and_dislike_toggle_and_redraw_the_card_in_place` fails at line 306 on the `{c[\"key\"]: c[\"actions\"] ...} == {_key(r): ACTIONS ...}` assertion. Every keyed card's `actions` list is `[]`, because `renderRows` in `client/frontend/src/pages/search/index.ts:208` calls `renderVideoCard` without `actions: true`. The keyless test fails at line 332 and both reset parametrizations fail at line 349, all for that same reason.\n\nNOT ASSESSED\n1. `code_under_test` listed `tests/tmp/test_frontend_search_card_actions.py`, which does not resolve. The stub question was answered from `index.ts`, `components/video-card.ts`, `data/reactions.ts` and the test's own assertions.\n2. Notes on the passes, with no finding raised:\n   - **Anti-pattern pass.** No `.md` file is read, so `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep` don't apply.\n   - **`hardcoded-spec-mirror`.** The `ACTIONS`, `NEUTRAL`, `LIKED` and `DISLIKED` literals are checked against the DOM the page renders, not against a code constant.\n   - **`tautological-assertion`.** The test's `_key` (line 277) writes out the `host::uuid` format itself. It doesn't import or call `resolveVideoKey`, so a change to the production format would turn the test red.\n   - **`absence-only-assertion`.** The negative assertions each sit in the same test as a positive control: lines 307 and 306, line 357 and line 351, lines 358/361 and lines 363\u2013364.\n   - **`echoed-literal`.** Each `_sent(...)` expectation is only met if the page's click handler builds and sends the request. If that handler is missing, lines 316, 335, 351 and 363 go red.\n   - **`single-value-pin`.** The toggle runs through five steps (dislike, undo, dislike, like, undo) and two reset parametrizations, so the observed marks have to follow each input.\n   - **Ladder pass.** The test runs the real bundle in node and asserts on outgoing requests, localStorage and the redrawn DOM. That is direct behaviour invocation (rung 1), the highest rung for a browser page. There is no downshift, so no comment is needed, and the test is not on the anti-rung.\n   - **Stub question.** Each wrong implementation fails a specific assertion:\n     - Controls rendered with no click handler: line 316.\n     - A Dislike that always sends `dislike`: step 2 at line 316.\n     - A request sent but the card not redrawn: line 318.\n     - A redraw that moves the card or touches other cards: lines 321\u2013322.\n     - An `outerHTML` redraw with no detached check: line 357.\n     - A row list the reset didn't clear: line 363.\n     - The code as it stands: line 306.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (34 clauses: 9 must_prove, 17 docstring, 8 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | every keyed card on the first page has the four `[data-card-action]` controls | :306 | the page passing no `actions`, or a card missing any of like/dislike/channel/account (exact ordered list per key) | CARRIED |\n| C1b | must_prove | every keyed card on an appended page has the four controls | :306 (control :303) | actions passed only on the reset path, so page-2 cards from `insertAdjacentHTML` stay bare (b1, b2 in the expected map) | CARRIED |\n| C1c | must_prove | a keyless card has none | :307 | controls rendered on a card with no video key, on either page | CARRIED |\n| C2a | must_prove | a Like click sends the toggled reaction | :316 | always sending `like`; sending `undo_like` on a disliked card (step 4 expects `like`, step 5 `undo_like`) | CARRIED |\n| C2b | must_prove | a Dislike click sends the toggled reaction | :316 | always sending `dislike` (step 2 expects `undo_dislike`), or the wrong uuid/host | CARRIED |\n| C2c | must_prove | re-renders that card with the new mark | :318 | sending without redrawing (the previous mark stays); redrawing from a stale reaction | CARRIED |\n| C2d | must_prove | in place | :321, :322 | the redrawn card appended at the end or moved; a neighbouring card's state changed | CARRIED |\n| C2e | must_prove | a Like does not throw when a reset replaced the grid mid-request | :357 `[like]` (control :354) | `outerHTML` set on the detached card, which the fake throws on at :108 | CARRIED |\n| C2f | must_prove | a Dislike does not throw when a reset replaced the grid mid-request | :357 `[dislike]` (control :351, :354) | an unguarded redraw on the Dislike branch: the parametrisation at :341 now drives `ACTION=dislike` through the reset scenario (:224, :235), so a throw reaches `errors` | CARRIED |\n| D1 | docstring | \"carry the card controls on every loaded page\" | :306 | page-2 cards without controls | CARRIED |\n| D2 | docstring | \"Like and Dislike on one toggle the reaction and redraw that card in place\" | :316, :318, :321 | a non-toggling send, no redraw, a moved card | CARRIED |\n| D3 | docstring | \"every keyed card has the like, dislike, channel and account buttons, and the keyless card on each page has none\" | :306, :307 | any member of the set missing; controls on keyless cards k1/k2 | CARRIED |\n| D4 | docstring | \"Dislike\u00d73, Like\u00d72 send dislike, undo_dislike, dislike, like, undo_like for that video\" | :316 | a wrong action at any step, or the wrong video | CARRIED |\n| D5 | docstring | \"disliked \u2026 then neutral, then disliked, then liked and not disliked, then neutral\" (stat active + aria-pressed) | :318 | a missing stat class or aria-pressed; liked and disliked both set | CARRIED |\n| D6 | docstring | \"stays at its position with its four controls\" | :321, :319 | a reorder; a redraw that drops `actions` | CARRIED |\n| D7 | docstring | \"no other card changes\" | :322 | a change to any other card's key, title, controls or marks | CARRIED |\n| D8 | docstring | \"Without a key, the keyed cards carry the same four controls and the keyless card none\" | :332 | controls only for a profile holder | CARRIED |\n| D9 | docstring | \"Like sends `like`\" (no key) | :335 | asking for a profile and sending nothing | CARRIED |\n| D10 | docstring | \"`localLikes:v1` then holds the video\" | :336 (control :330) | not storing, or storing the wrong video | CARRIED |\n| D11 | docstring | \"the card shows liked\" (no key) | :337 | no redraw from the local likes | CARRIED |\n| D12 | docstring | \"the first search's cards carry the four controls\" | :349 | the reset render without actions | CARRIED |\n| D13 | docstring | \"resolves without an error escaping\" (now \"a Like, or in a second run a Dislike\") | :357 | a throw from the detached-card redraw, on either branch | CARRIED |\n| D14 | docstring | \"without writing an error into the clicked card's status line\" | :358 | catching the throw and reporting it on the card | CARRIED |\n| D15 | docstring | \"The grid holds the new search's cards, all unmarked\" | :360, :361 | the resolved reaction redrawing into, or marking, the new grid | CARRIED |\n| D16 | docstring | \"a following click of the same reaction \u2026 sends `like` or `dislike`, not the `undo_like` or `undo_dislike`\" | :363, :364 | a row list the reset did not clear | CARRIED |\n| D17 | docstring | \"The fake DOM throws when outerHTML is set on an element with no parent\" | :108 (harness) | a statement about the harness, made true by construction | CARRIED |\n| N1 | name | \"keyed cards on both pages carry the controls\" | :306 | page-2 cards without controls | CARRIED |\n| N2 | name | \"like and dislike toggle\" | :316 | a non-toggling send | CARRIED |\n| N3 | name | \"and redraw the card in place\" | :318, :321, :322 | no redraw; a moved card | CARRIED |\n| N4 | name | \"a keyless like is sent\" | :335 | nothing sent without a profile | CARRIED |\n| N5 | name | \"stored in the local likes\" | :336 | no local store write | CARRIED |\n| N6 | name | \"and shown on the card\" | :337 | the card left unmarked | CARRIED |\n| N7 | name | \"a like (now: like or dislike) resolving after a new search replaced the grid leaves the new cards \u2026 alone\" | :360, :361 | the stale reaction marking or replacing a new card | CARRIED |\n| N8 | name | \"\u2026 and rows alone\" | :363 | a leftover first-search row causing `undo_like` / `undo_dislike` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase2.py:341\n   The author resolved C2f by adding an assertion, not by narrowing the prose. The reset test is now parametrised over `(\"like\", LIKED), (\"dislike\", DISLIKED)`, and :357 runs under each. The docstring (:8) and the test name (:342) were widened to match: D13\u2013D16 and N7\u2013N8 now claim both reactions, and the parametrisation carries each of them for both.\n2. bounds / normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase2.py:326\n   The keyless scenario clicks only Like. No test covers Dislike without a profile key. No docstring sentence and no `must_prove` clause claims that path, so nothing here is uncarried. This is a gap in coverage, not a claim defect, and no ledger row names it.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not resolve (Glob found no match). Nothing was judged against it.\n2. The click wiring, the `actions` option and the `.card-action-status` element are not in client/frontend/src/pages/search/index.ts as read. They would come from `components/video-card` and `data/reactions`, and those were not supplied in `code_under_test` or read. The excludes column was judged from the test and its fake DOM harness, not from those modules.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_keyed_cards_on_both_pages_carry_the_controls_and_like_and_dislike_toggle_and_redraw_the_card_in_place` fails at line 306 on the `{c[\"key\"]: c[\"actions\"] ...} == {_key(r): ACTIONS ...}` assertion. Every keyed card's `actions` list is `[]`, because `renderRows` in `client/frontend/src/pages/search/index.ts:208` calls `renderVideoCard` without `actions: true`. The keyless test fails at line 332 and both reset parametrizations fail at line 349, all for that same reason.\n\nNOT ASSESSED\n1. `code_under_test` listed `tests/tmp/test_frontend_search_card_actions.py`, which does not resolve. The stub question was answered from `index.ts`, `components/video-card.ts`, `data/reactions.ts` and the test's own assertions.\n2. Notes on the passes, with no finding raised:\n   - **Anti-pattern pass.** No `.md` file is read, so `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep` don't apply.\n   - **`hardcoded-spec-mirror`.** The `ACTIONS`, `NEUTRAL`, `LIKED` and `DISLIKED` literals are checked against the DOM the page renders, not against a code constant.\n   - **`tautological-assertion`.** The test's `_key` (line 277) writes out the `host::uuid` format itself. It doesn't import or call `resolveVideoKey`, so a change to the production format would turn the test red.\n   - **`absence-only-assertion`.** The negative assertions each sit in the same test as a positive control: lines 307 and 306, line 357 and line 351, lines 358/361 and lines 363\u2013364.\n   - **`echoed-literal`.** Each `_sent(...)` expectation is only met if the page's click handler builds and sends the request. If that handler is missing, lines 316, 335, 351 and 363 go red.\n   - **`single-value-pin`.** The toggle runs through five steps (dislike, undo, dislike, like, undo) and two reset parametrizations, so the observed marks have to follow each input.\n   - **Ladder pass.** The test runs the real bundle in node and asserts on outgoing requests, localStorage and the redrawn DOM. That is direct behaviour invocation (rung 1), the highest rung for a browser page. There is no downshift, so no comment is needed, and the test is not on the anti-rung.\n   - **Stub question.** Each wrong implementation fails a specific assertion:\n     - Controls rendered with no click handler: line 316.\n     - A Dislike that always sends `dislike`: step 2 at line 316.\n     - A request sent but the card not redrawn: line 318.\n     - A redraw that moves the card or touches other cards: lines 321\u2013322.\n     - An `outerHTML` redraw with no detached check: line 357.\n     - A row list the reset didn't clear: line 363.\n     - The code as it stands: line 306.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (34 clauses: 9 must_prove, 17 docstring, 8 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | every keyed card on the first page has the four `[data-card-action]` controls | :306 | the page passing no `actions`, or a card missing any of like/dislike/channel/account (exact ordered list per key) | CARRIED |\n| C1b | must_prove | every keyed card on an appended page has the four controls | :306 (control :303) | actions passed only on the reset path, so page-2 cards from `insertAdjacentHTML` stay bare (b1, b2 in the expected map) | CARRIED |\n| C1c | must_prove | a keyless card has none | :307 | controls rendered on a card with no video key, on either page | CARRIED |\n| C2a | must_prove | a Like click sends the toggled reaction | :316 | always sending `like`; sending `undo_like` on a disliked card (step 4 expects `like`, step 5 `undo_like`) | CARRIED |\n| C2b | must_prove | a Dislike click sends the toggled reaction | :316 | always sending `dislike` (step 2 expects `undo_dislike`), or the wrong uuid/host | CARRIED |\n| C2c | must_prove | re-renders that card with the new mark | :318 | sending without redrawing (the previous mark stays); redrawing from a stale reaction | CARRIED |\n| C2d | must_prove | in place | :321, :322 | the redrawn card appended at the end or moved; a neighbouring card's state changed | CARRIED |\n| C2e | must_prove | a Like does not throw when a reset replaced the grid mid-request | :357 `[like]` (control :354) | `outerHTML` set on the detached card, which the fake throws on at :108 | CARRIED |\n| C2f | must_prove | a Dislike does not throw when a reset replaced the grid mid-request | :357 `[dislike]` (control :351, :354) | an unguarded redraw on the Dislike branch: the parametrisation at :341 now drives `ACTION=dislike` through the reset scenario (:224, :235), so a throw reaches `errors` | CARRIED |\n| D1 | docstring | \"carry the card controls on every loaded page\" | :306 | page-2 cards without controls | CARRIED |\n| D2 | docstring | \"Like and Dislike on one toggle the reaction and redraw that card in place\" | :316, :318, :321 | a non-toggling send, no redraw, a moved card | CARRIED |\n| D3 | docstring | \"every keyed card has the like, dislike, channel and account buttons, and the keyless card on each page has none\" | :306, :307 | any member of the set missing; controls on keyless cards k1/k2 | CARRIED |\n| D4 | docstring | \"Dislike\u00d73, Like\u00d72 send dislike, undo_dislike, dislike, like, undo_like for that video\" | :316 | a wrong action at any step, or the wrong video | CARRIED |\n| D5 | docstring | \"disliked \u2026 then neutral, then disliked, then liked and not disliked, then neutral\" (stat active + aria-pressed) | :318 | a missing stat class or aria-pressed; liked and disliked both set | CARRIED |\n| D6 | docstring | \"stays at its position with its four controls\" | :321, :319 | a reorder; a redraw that drops `actions` | CARRIED |\n| D7 | docstring | \"no other card changes\" | :322 | a change to any other card's key, title, controls or marks | CARRIED |\n| D8 | docstring | \"Without a key, the keyed cards carry the same four controls and the keyless card none\" | :332 | controls only for a profile holder | CARRIED |\n| D9 | docstring | \"Like sends `like`\" (no key) | :335 | asking for a profile and sending nothing | CARRIED |\n| D10 | docstring | \"`localLikes:v1` then holds the video\" | :336 (control :330) | not storing, or storing the wrong video | CARRIED |\n| D11 | docstring | \"the card shows liked\" (no key) | :337 | no redraw from the local likes | CARRIED |\n| D12 | docstring | \"the first search's cards carry the four controls\" | :349 | the reset render without actions | CARRIED |\n| D13 | docstring | \"resolves without an error escaping\" (now \"a Like, or in a second run a Dislike\") | :357 | a throw from the detached-card redraw, on either branch | CARRIED |\n| D14 | docstring | \"without writing an error into the clicked card's status line\" | :358 | catching the throw and reporting it on the card | CARRIED |\n| D15 | docstring | \"The grid holds the new search's cards, all unmarked\" | :360, :361 | the resolved reaction redrawing into, or marking, the new grid | CARRIED |\n| D16 | docstring | \"a following click of the same reaction \u2026 sends `like` or `dislike`, not the `undo_like` or `undo_dislike`\" | :363, :364 | a row list the reset did not clear | CARRIED |\n| D17 | docstring | \"The fake DOM throws when outerHTML is set on an element with no parent\" | :108 (harness) | a statement about the harness, made true by construction | CARRIED |\n| N1 | name | \"keyed cards on both pages carry the controls\" | :306 | page-2 cards without controls | CARRIED |\n| N2 | name | \"like and dislike toggle\" | :316 | a non-toggling send | CARRIED |\n| N3 | name | \"and redraw the card in place\" | :318, :321, :322 | no redraw; a moved card | CARRIED |\n| N4 | name | \"a keyless like is sent\" | :335 | nothing sent without a profile | CARRIED |\n| N5 | name | \"stored in the local likes\" | :336 | no local store write | CARRIED |\n| N6 | name | \"and shown on the card\" | :337 | the card left unmarked | CARRIED |\n| N7 | name | \"a like (now: like or dislike) resolving after a new search replaced the grid leaves the new cards \u2026 alone\" | :360, :361 | the stale reaction marking or replacing a new card | CARRIED |\n| N8 | name | \"\u2026 and rows alone\" | :363 | a leftover first-search row causing `undo_like` / `undo_dislike` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase2.py:341\n   The author resolved C2f by adding an assertion, not by narrowing the prose. The reset test is now parametrised over `(\"like\", LIKED), (\"dislike\", DISLIKED)`, and :357 runs under each. The docstring (:8) and the test name (:342) were widened to match: D13\u2013D16 and N7\u2013N8 now claim both reactions, and the parametrisation carries each of them for both.\n2. bounds / normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase2.py:326\n   The keyless scenario clicks only Like. No test covers Dislike without a profile key. No docstring sentence and no `must_prove` clause claims that path, so nothing here is uncarried. This is a gap in coverage, not a claim defect, and no ledger row names it.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not resolve (Glob found no match). Nothing was judged against it.\n2. The click wiring, the `actions` option and the `.card-action-status` element are not in client/frontend/src/pages/search/index.ts as read. They would come from `components/video-card` and `data/reactions`, and those were not supplied in `code_under_test` or read. The excludes column was judged from the test and its fake DOM harness, not from those modules.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "every keyed card on the first page has the four `[data-card-action]` controls",
            "assertion": ":306",
            "excludes": "the page passing no `actions`, or a card missing any of like/dislike/channel/account (exact ordered list per key)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "every keyed card on an appended page has the four controls",
            "assertion": ":306 (control :303)",
            "excludes": "actions passed only on the reset path, so page-2 cards from `insertAdjacentHTML` stay bare (b1, b2 in the expected map)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "a keyless card has none",
            "assertion": ":307",
            "excludes": "controls rendered on a card with no video key, on either page",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a Like click sends the toggled reaction",
            "assertion": ":316",
            "excludes": "always sending `like`; sending `undo_like` on a disliked card (step 4 expects `like`, step 5 `undo_like`)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "a Dislike click sends the toggled reaction",
            "assertion": ":316",
            "excludes": "always sending `dislike` (step 2 expects `undo_dislike`), or the wrong uuid/host",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "re-renders that card with the new mark",
            "assertion": ":318",
            "excludes": "sending without redrawing (the previous mark stays); redrawing from a stale reaction",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "in place",
            "assertion": ":321, :322",
            "excludes": "the redrawn card appended at the end or moved; a neighbouring card's state changed",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "a Like does not throw when a reset replaced the grid mid-request",
            "assertion": ":357 `[like]` (control :354)",
            "excludes": "`outerHTML` set on the detached card, which the fake throws on at :108",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "a Dislike does not throw when a reset replaced the grid mid-request",
            "assertion": ":357 `[dislike]` (control :351, :354)",
            "excludes": "an unguarded redraw on the Dislike branch: the parametrisation at :341 now drives `ACTION=dislike` through the reset scenario (:224, :235), so a throw reaches `errors`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"carry the card controls on every loaded page\"",
            "assertion": ":306",
            "excludes": "page-2 cards without controls",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"Like and Dislike on one toggle the reaction and redraw that card in place\"",
            "assertion": ":316, :318, :321",
            "excludes": "a non-toggling send, no redraw, a moved card",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"every keyed card has the like, dislike, channel and account buttons, and the keyless card on each page has none\"",
            "assertion": ":306, :307",
            "excludes": "any member of the set missing; controls on keyless cards k1/k2",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"Dislike\u00d73, Like\u00d72 send dislike, undo_dislike, dislike, like, undo_like for that video\"",
            "assertion": ":316",
            "excludes": "a wrong action at any step, or the wrong video",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"disliked \u2026 then neutral, then disliked, then liked and not disliked, then neutral\" (stat active + aria-pressed)",
            "assertion": ":318",
            "excludes": "a missing stat class or aria-pressed; liked and disliked both set",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"stays at its position with its four controls\"",
            "assertion": ":321, :319",
            "excludes": "a reorder; a redraw that drops `actions`",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"no other card changes\"",
            "assertion": ":322",
            "excludes": "a change to any other card's key, title, controls or marks",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"Without a key, the keyed cards carry the same four controls and the keyless card none\"",
            "assertion": ":332",
            "excludes": "controls only for a profile holder",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"Like sends `like`\" (no key)",
            "assertion": ":335",
            "excludes": "asking for a profile and sending nothing",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"`localLikes:v1` then holds the video\"",
            "assertion": ":336 (control :330)",
            "excludes": "not storing, or storing the wrong video",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"the card shows liked\" (no key)",
            "assertion": ":337",
            "excludes": "no redraw from the local likes",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the first search's cards carry the four controls\"",
            "assertion": ":349",
            "excludes": "the reset render without actions",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"resolves without an error escaping\" (now \"a Like, or in a second run a Dislike\")",
            "assertion": ":357",
            "excludes": "a throw from the detached-card redraw, on either branch",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"without writing an error into the clicked card's status line\"",
            "assertion": ":358",
            "excludes": "catching the throw and reporting it on the card",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"The grid holds the new search's cards, all unmarked\"",
            "assertion": ":360, :361",
            "excludes": "the resolved reaction redrawing into, or marking, the new grid",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"a following click of the same reaction \u2026 sends `like` or `dislike`, not the `undo_like` or `undo_dislike`\"",
            "assertion": ":363, :364",
            "excludes": "a row list the reset did not clear",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"The fake DOM throws when outerHTML is set on an element with no parent\"",
            "assertion": ":108 (harness)",
            "excludes": "a statement about the harness, made true by construction",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"keyed cards on both pages carry the controls\"",
            "assertion": ":306",
            "excludes": "page-2 cards without controls",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"like and dislike toggle\"",
            "assertion": ":316",
            "excludes": "a non-toggling send",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and redraw the card in place\"",
            "assertion": ":318, :321, :322",
            "excludes": "no redraw; a moved card",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a keyless like is sent\"",
            "assertion": ":335",
            "excludes": "nothing sent without a profile",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"stored in the local likes\"",
            "assertion": ":336",
            "excludes": "no local store write",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"and shown on the card\"",
            "assertion": ":337",
            "excludes": "the card left unmarked",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"a like (now: like or dislike) resolving after a new search replaced the grid leaves the new cards \u2026 alone\"",
            "assertion": ":360, :361",
            "excludes": "the stale reaction marking or replacing a new card",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "\"\u2026 and rows alone\"",
            "assertion": ":363",
            "excludes": "a leftover first-search row causing `undo_like` / `undo_dislike`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_40_search_card_actions_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nIn both `channel` and `account` cases of `test_a_block_whose_dislike_succeeds_removes_every_loaded_card_of_the_source_and_refills_the_grid`, the test should fail at line 290 (`assert page[\"after\"][\"calls\"] == _block_then_dislike(kind) + [...]`). The click sends no request, so `after.calls` is `[]`, because `runCardAction` in `client/frontend/src/pages/search/index.ts:246-275` has only `like` and `dislike` branches. In both cases of `test_a_block_whose_dislike_fails_says_so_on_the_card_and_removes_nothing`, the test should fail at line 304 (`assert page[\"after\"][\"cardStatus\"] == f\"Blocked {shown}, but the dislike failed: ...\"`). The card status reads `\"\"` because `say(\"\")` runs and no branch follows it.\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/tmp/test_frontend_search_card_actions.py`, and that path does not exist (Glob found no match). Nothing it might contain was checked. The checks above used the test file, `client/frontend/src/pages/search/index.ts`, and `client/frontend/src/components/video-card.ts`. I read `video-card.ts` to confirm the symbols the test relies on: `data-card-action=\"channel\"`/`\"account\"`, `.card-action-status`, and the `data-video-key` format `host::uuid`.\n2. `fixtures_path` was not supplied. The only fixture the test uses, `search_bundle`, is defined in the test file at lines 217-219, so this left nothing out.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 8 must_prove, 14 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a successful block followed by a successful dislike\" | :290 | a page that skips the dislike, sends it before the block, or sends either for the wrong uuid/host/kind; the list is compared exactly, in order | CARRIED |\n| C1b | must_prove | \"removes every loaded card of that channel\" | :292 (kind=channel) | removing only the clicked card (b1 and k2 would stay); matching on channel_id alone (a3 would go); matching on account (a2 would go); breaking the order | CARRIED |\n| C1c | must_prove | \"...or account\" | :292 (kind=account) | Block account matching on channel instead of account_url (a2 would stay) | CARRIED |\n| C1d | must_prove | \"refills the viewport\" | :290 | a page that never asks for more after removing cards. After the click no observer fires, so the page 3 GET can only come from the page itself | CARRIED |\n| C1e | must_prove | \"leaves the status text unchanged\" | :294 against :276 | recounting the status from the cards left, or writing the block result into `#search-status` | CARRIED |\n| C2a | must_prove | reports `Blocked <label>, but the dislike failed: <msg>` | :304 (channel, \"Alice's channel\") | reporting only the dislike error, reporting nothing, or a generic message in place of the server's `error` | CARRIED |\n| C2b | must_prove | `<action>` used when the label is empty | :304 (account, \"\") | rendering `Blocked , but the dislike failed: ...`. It does not exclude a fixed fallback string or a label/action choice made by kind (see Recommendation 1) | CARRIED |\n| C2c | must_prove | \"removes no card\" | :308, armed by :306 | removing the source's cards whatever the dislike returned. :306 shows the failing dislike was actually reached | CARRIED |\n| D1 | docstring | \"block the source and dislike the video\" | :290 | dislike or block missing from the sequence | CARRIED |\n| D2 | docstring | \"take every loaded card of that source off the grid and refill it\" | :292, :290 | partial removal; no refill fetch | CARRIED |\n| D3 | docstring | \"a block whose dislike fails says so on the card and removes nothing\" | :304, :308 | no message on the card; cards removed anyway | CARRIED |\n| D4 | docstring | \"a page fetched after the click was asked for by the page itself\" | :290 | a fetch caused by the harness. Observers are only called before the click (runner line 190) | CARRIED |\n| D5 | docstring | \"...once the cards were gone\" | none | the sentinel's in-view state depends on the click, not on what is in the grid, so a refill sent before the removal passes the same way | UNCARRIED |\n| D6 | docstring | \"sends POST /api/profile/blocks for that video, then a dislike for it, then fetches page 3\" | :290 | wrong order, wrong body, or a missing step | CARRIED |\n| D7 | docstring | \"the cards left are exactly the loaded ones not on that instance_domain+channel_id, in order\" | :292 | dropping or reordering a card that should stay | CARRIED |\n| D8 | docstring | \"page-2 cards and a keyless card of the channel go\" | :292 | removing only cards that have a video key, or only page-1 cards (b1 and k2 would stay) | CARRIED |\n| D9 | docstring | \"a card on the same channel_id of another instance and a card of the same account on another channel stay\" | :292 (channel) | matching on channel_id without the domain (a3 goes); matching on account (a2 goes) | CARRIED |\n| D10 | docstring | \"Block account does the same on account_url, so that same-account card goes too\" | :290, :292 (account) | Block account sending the wrong kind, or matching on channel | CARRIED |\n| D11 | docstring | \"Page 3 comes back empty, so #search-status reads as it did before the click\" | :294 against :276 | the status changing after removal | CARRIED |\n| D12 | docstring | \"`.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`\" | :304 | wrong text, or text on the wrong element | CARRIED |\n| D13 | docstring | \"with the action name in place of an empty label\" | :304 (account, \"\") | showing an empty label | CARRIED |\n| D14 | docstring | \"every card is still in the grid, in order\" | :308 | any card removed or reordered | CARRIED |\n| N1 | name | \"a block whose dislike succeeds\" | :290 | the dislike not being sent after the block | CARRIED |\n| N2 | name | \"removes every loaded card of the source\" | :292 | partial or wrong-field removal | CARRIED |\n| N3 | name | \"and refills the grid\" | :290 | no fetch of the next page | CARRIED |\n| N4 | name | \"a block whose dislike fails says so on the card\" | :304 | no message, or the wrong message, on the clicked card | CARRIED |\n| N5 | name | \"and removes nothing\" | :308 | cards removed on the failure path | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase3.py:298\n   `[(\"channel\", \"Alice's channel\", \"Alice's channel\"), (\"account\", \"\", \"account\")]`\n   The parametrisation ties the kind to whether the label is empty. The channel case always has a label and the account case never does. An implementation that writes `Blocked ${action === \"channel\" ? block.label : action}`, or falls back to a fixed `\"account\"`, passes both cases. C2b is CARRIED because it excludes the empty-label rendering. Under \"X per Y needs a second Y\", though, the label-or-action choice is only half shown. Adding a case with a channel block and an empty label (expect `channel`), or an account block with a label, separates them.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase3.py:3\n   D5 is UNCARRIED. The docstring says the page 3 fetch was asked for \"once the cards were gone\". The fake sentinel reports itself in view because of the click (runner line 194), not because of what the grid holds. So nothing shows the refill came after the removal. Either narrow the sentence or tie the stub's in-view state to the grid's contents.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase3.py:256\n   Page 3 always comes back empty. The refill is therefore only seen as a request, and rows the refill returns are never shown landing in the grid. The case where removal empties the grid completely is also untested.\n4. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase3.py:299\n   The only failure path tested is the dislike failing. A failing `POST /api/profile/blocks` (does the page skip the dislike, show a message, keep the cards?) is never exercised. That clause is not in `must_prove`, so this is not blocking.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not exist. Nothing in this test depends on it, and it was not assessed.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nIn both `channel` and `account` cases of `test_a_block_whose_dislike_succeeds_removes_every_loaded_card_of_the_source_and_refills_the_grid`, the test should fail at line 290 (`assert page[\"after\"][\"calls\"] == _block_then_dislike(kind) + [...]`). The click sends no request, so `after.calls` is `[]`, because `runCardAction` in `client/frontend/src/pages/search/index.ts:246-275` has only `like` and `dislike` branches. In both cases of `test_a_block_whose_dislike_fails_says_so_on_the_card_and_removes_nothing`, the test should fail at line 304 (`assert page[\"after\"][\"cardStatus\"] == f\"Blocked {shown}, but the dislike failed: ...\"`). The card status reads `\"\"` because `say(\"\")` runs and no branch follows it.\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/tmp/test_frontend_search_card_actions.py`, and that path does not exist (Glob found no match). Nothing it might contain was checked. The checks above used the test file, `client/frontend/src/pages/search/index.ts`, and `client/frontend/src/components/video-card.ts`. I read `video-card.ts` to confirm the symbols the test relies on: `data-card-action=\"channel\"`/`\"account\"`, `.card-action-status`, and the `data-video-key` format `host::uuid`.\n2. `fixtures_path` was not supplied. The only fixture the test uses, `search_bundle`, is defined in the test file at lines 217-219, so this left nothing out.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 8 must_prove, 14 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a successful block followed by a successful dislike\" | :290 | a page that skips the dislike, sends it before the block, or sends either for the wrong uuid/host/kind; the list is compared exactly, in order | CARRIED |\n| C1b | must_prove | \"removes every loaded card of that channel\" | :292 (kind=channel) | removing only the clicked card (b1 and k2 would stay); matching on channel_id alone (a3 would go); matching on account (a2 would go); breaking the order | CARRIED |\n| C1c | must_prove | \"...or account\" | :292 (kind=account) | Block account matching on channel instead of account_url (a2 would stay) | CARRIED |\n| C1d | must_prove | \"refills the viewport\" | :290 | a page that never asks for more after removing cards. After the click no observer fires, so the page 3 GET can only come from the page itself | CARRIED |\n| C1e | must_prove | \"leaves the status text unchanged\" | :294 against :276 | recounting the status from the cards left, or writing the block result into `#search-status` | CARRIED |\n| C2a | must_prove | reports `Blocked <label>, but the dislike failed: <msg>` | :304 (channel, \"Alice's channel\") | reporting only the dislike error, reporting nothing, or a generic message in place of the server's `error` | CARRIED |\n| C2b | must_prove | `<action>` used when the label is empty | :304 (account, \"\") | rendering `Blocked , but the dislike failed: ...`. It does not exclude a fixed fallback string or a label/action choice made by kind (see Recommendation 1) | CARRIED |\n| C2c | must_prove | \"removes no card\" | :308, armed by :306 | removing the source's cards whatever the dislike returned. :306 shows the failing dislike was actually reached | CARRIED |\n| D1 | docstring | \"block the source and dislike the video\" | :290 | dislike or block missing from the sequence | CARRIED |\n| D2 | docstring | \"take every loaded card of that source off the grid and refill it\" | :292, :290 | partial removal; no refill fetch | CARRIED |\n| D3 | docstring | \"a block whose dislike fails says so on the card and removes nothing\" | :304, :308 | no message on the card; cards removed anyway | CARRIED |\n| D4 | docstring | \"a page fetched after the click was asked for by the page itself\" | :290 | a fetch caused by the harness. Observers are only called before the click (runner line 190) | CARRIED |\n| D5 | docstring | \"...once the cards were gone\" | none | the sentinel's in-view state depends on the click, not on what is in the grid, so a refill sent before the removal passes the same way | UNCARRIED |\n| D6 | docstring | \"sends POST /api/profile/blocks for that video, then a dislike for it, then fetches page 3\" | :290 | wrong order, wrong body, or a missing step | CARRIED |\n| D7 | docstring | \"the cards left are exactly the loaded ones not on that instance_domain+channel_id, in order\" | :292 | dropping or reordering a card that should stay | CARRIED |\n| D8 | docstring | \"page-2 cards and a keyless card of the channel go\" | :292 | removing only cards that have a video key, or only page-1 cards (b1 and k2 would stay) | CARRIED |\n| D9 | docstring | \"a card on the same channel_id of another instance and a card of the same account on another channel stay\" | :292 (channel) | matching on channel_id without the domain (a3 goes); matching on account (a2 goes) | CARRIED |\n| D10 | docstring | \"Block account does the same on account_url, so that same-account card goes too\" | :290, :292 (account) | Block account sending the wrong kind, or matching on channel | CARRIED |\n| D11 | docstring | \"Page 3 comes back empty, so #search-status reads as it did before the click\" | :294 against :276 | the status changing after removal | CARRIED |\n| D12 | docstring | \"`.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`\" | :304 | wrong text, or text on the wrong element | CARRIED |\n| D13 | docstring | \"with the action name in place of an empty label\" | :304 (account, \"\") | showing an empty label | CARRIED |\n| D14 | docstring | \"every card is still in the grid, in order\" | :308 | any card removed or reordered | CARRIED |\n| N1 | name | \"a block whose dislike succeeds\" | :290 | the dislike not being sent after the block | CARRIED |\n| N2 | name | \"removes every loaded card of the source\" | :292 | partial or wrong-field removal | CARRIED |\n| N3 | name | \"and refills the grid\" | :290 | no fetch of the next page | CARRIED |\n| N4 | name | \"a block whose dislike fails says so on the card\" | :304 | no message, or the wrong message, on the clicked card | CARRIED |\n| N5 | name | \"and removes nothing\" | :308 | cards removed on the failure path | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase3.py:298\n   `[(\"channel\", \"Alice's channel\", \"Alice's channel\"), (\"account\", \"\", \"account\")]`\n   The parametrisation ties the kind to whether the label is empty. The channel case always has a label and the account case never does. An implementation that writes `Blocked ${action === \"channel\" ? block.label : action}`, or falls back to a fixed `\"account\"`, passes both cases. C2b is CARRIED because it excludes the empty-label rendering. Under \"X per Y needs a second Y\", though, the label-or-action choice is only half shown. Adding a case with a channel block and an empty label (expect `channel`), or an account block with a label, separates them.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase3.py:3\n   D5 is UNCARRIED. The docstring says the page 3 fetch was asked for \"once the cards were gone\". The fake sentinel reports itself in view because of the click (runner line 194), not because of what the grid holds. So nothing shows the refill came after the removal. Either narrow the sentence or tie the stub's in-view state to the grid's contents.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase3.py:256\n   Page 3 always comes back empty. The refill is therefore only seen as a request, and rows the refill returns are never shown landing in the grid. The case where removal empties the grid completely is also untested.\n4. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase3.py:299\n   The only failure path tested is the dislike failing. A failing `POST /api/profile/blocks` (does the page skip the dislike, show a message, keep the cards?) is never exercised. That clause is not in `must_prove`, so this is not blocking.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not exist. Nothing in this test depends on it, and it was not assessed.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a successful block followed by a successful dislike\"",
            "assertion": ":290",
            "excludes": "a page that skips the dislike, sends it before the block, or sends either for the wrong uuid/host/kind; the list is compared exactly, in order",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"removes every loaded card of that channel\"",
            "assertion": ":292 (kind=channel)",
            "excludes": "removing only the clicked card (b1 and k2 would stay); matching on channel_id alone (a3 would go); matching on account (a2 would go); breaking the order",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"...or account\"",
            "assertion": ":292 (kind=account)",
            "excludes": "Block account matching on channel instead of account_url (a2 would stay)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"refills the viewport\"",
            "assertion": ":290",
            "excludes": "a page that never asks for more after removing cards. After the click no observer fires, so the page 3 GET can only come from the page itself",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"leaves the status text unchanged\"",
            "assertion": ":294 against :276",
            "excludes": "recounting the status from the cards left, or writing the block result into `#search-status`",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "reports `Blocked <label>, but the dislike failed: <msg>`",
            "assertion": ":304 (channel, \"Alice's channel\")",
            "excludes": "reporting only the dislike error, reporting nothing, or a generic message in place of the server's `error`",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "`<action>` used when the label is empty",
            "assertion": ":304 (account, \"\")",
            "excludes": "rendering `Blocked , but the dislike failed: ...`. It does not exclude a fixed fallback string or a label/action choice made by kind (see Recommendation 1)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"removes no card\"",
            "assertion": ":308, armed by :306",
            "excludes": "removing the source's cards whatever the dislike returned. :306 shows the failing dislike was actually reached",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"block the source and dislike the video\"",
            "assertion": ":290",
            "excludes": "dislike or block missing from the sequence",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"take every loaded card of that source off the grid and refill it\"",
            "assertion": ":292, :290",
            "excludes": "partial removal; no refill fetch",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"a block whose dislike fails says so on the card and removes nothing\"",
            "assertion": ":304, :308",
            "excludes": "no message on the card; cards removed anyway",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"a page fetched after the click was asked for by the page itself\"",
            "assertion": ":290",
            "excludes": "a fetch caused by the harness. Observers are only called before the click (runner line 190)",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"...once the cards were gone\"",
            "assertion": "none",
            "excludes": "the sentinel's in-view state depends on the click, not on what is in the grid, so a refill sent before the removal passes the same way",
            "status": "UNCARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"sends POST /api/profile/blocks for that video, then a dislike for it, then fetches page 3\"",
            "assertion": ":290",
            "excludes": "wrong order, wrong body, or a missing step",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the cards left are exactly the loaded ones not on that instance_domain+channel_id, in order\"",
            "assertion": ":292",
            "excludes": "dropping or reordering a card that should stay",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"page-2 cards and a keyless card of the channel go\"",
            "assertion": ":292",
            "excludes": "removing only cards that have a video key, or only page-1 cards (b1 and k2 would stay)",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"a card on the same channel_id of another instance and a card of the same account on another channel stay\"",
            "assertion": ":292 (channel)",
            "excludes": "matching on channel_id without the domain (a3 goes); matching on account (a2 goes)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Block account does the same on account_url, so that same-account card goes too\"",
            "assertion": ":290, :292 (account)",
            "excludes": "Block account sending the wrong kind, or matching on channel",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Page 3 comes back empty, so #search-status reads as it did before the click\"",
            "assertion": ":294 against :276",
            "excludes": "the status changing after removal",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"`.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`\"",
            "assertion": ":304",
            "excludes": "wrong text, or text on the wrong element",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"with the action name in place of an empty label\"",
            "assertion": ":304 (account, \"\")",
            "excludes": "showing an empty label",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"every card is still in the grid, in order\"",
            "assertion": ":308",
            "excludes": "any card removed or reordered",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a block whose dislike succeeds\"",
            "assertion": ":290",
            "excludes": "the dislike not being sent after the block",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"removes every loaded card of the source\"",
            "assertion": ":292",
            "excludes": "partial or wrong-field removal",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and refills the grid\"",
            "assertion": ":290",
            "excludes": "no fetch of the next page",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a block whose dislike fails says so on the card\"",
            "assertion": ":304",
            "excludes": "no message, or the wrong message, on the clicked card",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"and removes nothing\"",
            "assertion": ":308",
            "excludes": "cards removed on the failure path",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nBoth parametrised cases of `test_a_block_whose_dislike_succeeds_removes_every_loaded_card_of_the_source_and_refills_the_grid` fail at tests/tmp/test_40_search_card_actions_phase3.py:290. The reason is that `runCardAction` in client/frontend/src/pages/search/index.ts has no `channel`/`account` branch. So `page[\"after\"][\"calls\"]` is `[]`, where the test expects the block POST, then the dislike POST, then the page-3 GET. Both cases of `test_a_block_whose_dislike_fails_says_so_on_the_card_and_removes_nothing` fail at line 304. There the action status is cleared by `say(\"\")` and never set again, so `page[\"after\"][\"cardStatus\"]` is `\"\"` (or `null` if the card renders no `.card-action-status`) instead of `Blocked Alice's channel, but the dislike failed: reaction store unavailable` / `Blocked account, but the dislike failed: reaction store unavailable`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which is a test file and not code this test exercises. This test neither imports it nor runs it, so it was not read as part of the shape assessment.\n2. I did not read client/frontend/src/components/video-card.ts in full; I only grepped it to confirm the `data-card-action=\"channel\"`/`\"account\"` buttons exist. Whether it renders `.card-action-status` on keyed cards was not confirmed. That affects only whether the line-304 red reads `\"\"` or `null`, not where the test fails.\n3. Passes 4 and 5 and the stub question, as covered by `rules/shape.md`:\n   - **Anti-patterns (pass 4):** none match.\n     - **`absence-only-assertion`:** line 308 (`grid == ALL_TITLES`) is paired in the same test with positive assertions at lines 304 and 306.\n     - **`echoed-literal`:** `DISLIKE_ERROR` and the label go in through the stub server and only reach the card through the page's error and label handling.\n     - **`tautological-assertion`:** `_block_then_dislike` builds its expectation from fixture rows, not from production logic.\n     - **`single-value-pin`:** the label is run at two values (`\"Alice's channel\"` and `\"\"`, which falls back to the action name), and the kind is run at two values with different expected grids.\n   - **Ladder (pass 5):** the test drives the bundled page and asserts on the requests it sends, the grid and the status it renders. That is rung 1 (direct behaviour invocation with observable side effects), the highest rung, so there is no downshift to justify.\n   - **Stub question:** the exact request sequence at line 290 and the fixtures at lines 244\u2013254 together reject:\n     - a stub with no Block branch\n     - removing only the clicked card\n     - matching on `channel_id` alone\n     - matching on the wrong field\n     - skipping the refill\n\n     A stub that removes cards whatever the dislike returns fails line 308.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 8 must_prove, 14 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a successful block followed by a successful dislike\" | :290 | Rules out skipping the dislike, sending it before the block, or sending either one with the wrong uuid/host/kind. The list is compared exactly and in order | CARRIED |\n| C1b | must_prove | \"removes every loaded card of that channel\" | :292 (kind=channel) | Rules out removing only the clicked card (b1 and k2 would stay), matching on channel_id alone (a3 would go), matching on account (a2 would go), and breaking the order | CARRIED |\n| C1c | must_prove | \"...or account\" | :292 (kind=account) | Rules out Block account matching on channel instead of account_url (a2 would stay) | CARRIED |\n| C1d | must_prove | \"refills the viewport\" | :290 | Rules out a page that never asks for more after removing cards. The sentinel is only in view from the click on (runner :194), and observers are only called before it (:190), so the page 3 GET can only come from the page | CARRIED |\n| C1e | must_prove | \"leaves the status text unchanged\" | :294 against :276 | Rules out recounting the status from the cards left, and rules out writing the block result into `#search-status` | CARRIED |\n| C2a | must_prove | reports `Blocked <label>, but the dislike failed: <msg>` | :304 (channel, \"Alice's channel\") | Rules out reporting only the dislike error, reporting nothing, or showing a generic message instead of the server's `error` | CARRIED |\n| C2b | must_prove | `<action>` used when the label is empty | :304 (account, \"\") | Rules out rendering `Blocked , but the dislike failed: ...`. Does not rule out a fixed fallback string or a choice made by kind (Recommendation 1) | CARRIED |\n| C2c | must_prove | \"removes no card\" | :308, armed by :306 | Rules out removing the source's cards whatever the dislike returned. :306 shows the failing dislike was reached | CARRIED |\n| D1 | docstring | \"block the source and dislike the video\" | :290 | Rules out a sequence missing the block or the dislike | CARRIED |\n| D2 | docstring | \"take every loaded card of that source off the grid and refill it\" | :292, :290 | Rules out partial removal and a missing refill fetch | CARRIED |\n| D3 | docstring | \"a block whose dislike fails says so on the card and removes nothing\" | :304, :308 | Rules out no message on the card, and rules out cards being removed anyway | CARRIED |\n| D4 | docstring | \"a page fetched after the click was asked for by the page itself\" | :290 | Rules out a fetch caused by the harness. Observers are only called before the click (runner :190) | CARRIED |\n| D5 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D6 | docstring | \"sends POST /api/profile/blocks for that video, then a dislike for it, then fetches page 3\" | :290 | Rules out the wrong order, the wrong body, or a missing step | CARRIED |\n| D7 | docstring | \"the cards left are exactly the loaded ones not on that instance_domain+channel_id, in order\" | :292 | Rules out dropping or reordering a card that should stay | CARRIED |\n| D8 | docstring | \"page-2 cards and a keyless card of the channel go\" | :292 | Rules out removing only cards with a video key, or only page-1 cards (b1 and k2 would stay) | CARRIED |\n| D9 | docstring | \"a card on the same channel_id of another instance and a card of the same account on another channel stay\" | :292 (channel) | Rules out matching on channel_id without the domain (a3 goes) and matching on account (a2 goes) | CARRIED |\n| D10 | docstring | \"Block account does the same on account_url, so that same-account card goes too\" | :290, :292 (account) | Rules out Block account sending the wrong kind or matching on channel | CARRIED |\n| D11 | docstring | \"Page 3 comes back empty, so #search-status reads as it did before the click\" | :294 against :276 | Rules out the status changing after removal | CARRIED |\n| D12 | docstring | \"`.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`\" | :304 | Rules out the wrong text, or text on the wrong element | CARRIED |\n| D13 | docstring | \"with the action name in place of an empty label\" | :304 (account, \"\") | Rules out showing an empty label | CARRIED |\n| D14 | docstring | \"every card is still in the grid, in order\" | :308 | Rules out any card being removed or reordered | CARRIED |\n| N1 | name | \"a block whose dislike succeeds\" | :290 | Rules out the dislike not being sent after the block | CARRIED |\n| N2 | name | \"removes every loaded card of the source\" | :292 | Rules out partial removal or removal on the wrong field | CARRIED |\n| N3 | name | \"and refills the grid\" | :290 | Rules out no fetch of the next page | CARRIED |\n| N4 | name | \"a block whose dislike fails says so on the card\" | :304 | Rules out no message, or the wrong message, on the clicked card | CARRIED |\n| N5 | name | \"and removes nothing\" | :308 | Rules out cards being removed on the failure path | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase3.py:298\n   `@pytest.mark.parametrize((\"kind\", \"label\", \"shown\"), [(\"channel\", \"Alice's channel\", \"Alice's channel\"), (\"account\", \"\", \"account\")])`\n   The empty-label case only runs for `account`, where the action name and the kind are the same string. A page that always falls back to the literal \"account\", or chooses label or action by kind, still passes. A `channel` case with an empty label (shown \"channel\") would rule both out. This is the gap already recorded in the C2b `excludes` cell, and it does not block.\n\nOBSERVATIONS\n1. D5 (whole-claim, rules/testing.md): tests/tmp/test_40_search_card_actions_phase3.py:3\n   The docstring was narrowed, and no assertion was added. On round 1, \"...once the cards were gone\" was UNCARRIED. The docstring now says \"nothing here shows whether that fetch came before or after the cards were removed\". So the test still does not show that the removal happens before the refill. It now says so openly instead of claiming it.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py, which does not exist (rg: No such file or directory). It was not read. The test under audit does not import it.\n2. `fixtures_path` was \"none found\". The test defines its only fixture, `search_bundle`, at :217, so independence was judged from the test file alone.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nBoth parametrised cases of `test_a_block_whose_dislike_succeeds_removes_every_loaded_card_of_the_source_and_refills_the_grid` fail at tests/tmp/test_40_search_card_actions_phase3.py:290. The reason is that `runCardAction` in client/frontend/src/pages/search/index.ts has no `channel`/`account` branch. So `page[\"after\"][\"calls\"]` is `[]`, where the test expects the block POST, then the dislike POST, then the page-3 GET. Both cases of `test_a_block_whose_dislike_fails_says_so_on_the_card_and_removes_nothing` fail at line 304. There the action status is cleared by `say(\"\")` and never set again, so `page[\"after\"][\"cardStatus\"]` is `\"\"` (or `null` if the card renders no `.card-action-status`) instead of `Blocked Alice's channel, but the dislike failed: reaction store unavailable` / `Blocked account, but the dislike failed: reaction store unavailable`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which is a test file and not code this test exercises. This test neither imports it nor runs it, so it was not read as part of the shape assessment.\n2. I did not read client/frontend/src/components/video-card.ts in full; I only grepped it to confirm the `data-card-action=\"channel\"`/`\"account\"` buttons exist. Whether it renders `.card-action-status` on keyed cards was not confirmed. That affects only whether the line-304 red reads `\"\"` or `null`, not where the test fails.\n3. Passes 4 and 5 and the stub question, as covered by `rules/shape.md`:\n   - **Anti-patterns (pass 4):** none match.\n     - **`absence-only-assertion`:** line 308 (`grid == ALL_TITLES`) is paired in the same test with positive assertions at lines 304 and 306.\n     - **`echoed-literal`:** `DISLIKE_ERROR` and the label go in through the stub server and only reach the card through the page's error and label handling.\n     - **`tautological-assertion`:** `_block_then_dislike` builds its expectation from fixture rows, not from production logic.\n     - **`single-value-pin`:** the label is run at two values (`\"Alice's channel\"` and `\"\"`, which falls back to the action name), and the kind is run at two values with different expected grids.\n   - **Ladder (pass 5):** the test drives the bundled page and asserts on the requests it sends, the grid and the status it renders. That is rung 1 (direct behaviour invocation with observable side effects), the highest rung, so there is no downshift to justify.\n   - **Stub question:** the exact request sequence at line 290 and the fixtures at lines 244\u2013254 together reject:\n     - a stub with no Block branch\n     - removing only the clicked card\n     - matching on `channel_id` alone\n     - matching on the wrong field\n     - skipping the refill\n\n     A stub that removes cards whatever the dislike returns fails line 308.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 8 must_prove, 14 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a successful block followed by a successful dislike\" | :290 | Rules out skipping the dislike, sending it before the block, or sending either one with the wrong uuid/host/kind. The list is compared exactly and in order | CARRIED |\n| C1b | must_prove | \"removes every loaded card of that channel\" | :292 (kind=channel) | Rules out removing only the clicked card (b1 and k2 would stay), matching on channel_id alone (a3 would go), matching on account (a2 would go), and breaking the order | CARRIED |\n| C1c | must_prove | \"...or account\" | :292 (kind=account) | Rules out Block account matching on channel instead of account_url (a2 would stay) | CARRIED |\n| C1d | must_prove | \"refills the viewport\" | :290 | Rules out a page that never asks for more after removing cards. The sentinel is only in view from the click on (runner :194), and observers are only called before it (:190), so the page 3 GET can only come from the page | CARRIED |\n| C1e | must_prove | \"leaves the status text unchanged\" | :294 against :276 | Rules out recounting the status from the cards left, and rules out writing the block result into `#search-status` | CARRIED |\n| C2a | must_prove | reports `Blocked <label>, but the dislike failed: <msg>` | :304 (channel, \"Alice's channel\") | Rules out reporting only the dislike error, reporting nothing, or showing a generic message instead of the server's `error` | CARRIED |\n| C2b | must_prove | `<action>` used when the label is empty | :304 (account, \"\") | Rules out rendering `Blocked , but the dislike failed: ...`. Does not rule out a fixed fallback string or a choice made by kind (Recommendation 1) | CARRIED |\n| C2c | must_prove | \"removes no card\" | :308, armed by :306 | Rules out removing the source's cards whatever the dislike returned. :306 shows the failing dislike was reached | CARRIED |\n| D1 | docstring | \"block the source and dislike the video\" | :290 | Rules out a sequence missing the block or the dislike | CARRIED |\n| D2 | docstring | \"take every loaded card of that source off the grid and refill it\" | :292, :290 | Rules out partial removal and a missing refill fetch | CARRIED |\n| D3 | docstring | \"a block whose dislike fails says so on the card and removes nothing\" | :304, :308 | Rules out no message on the card, and rules out cards being removed anyway | CARRIED |\n| D4 | docstring | \"a page fetched after the click was asked for by the page itself\" | :290 | Rules out a fetch caused by the harness. Observers are only called before the click (runner :190) | CARRIED |\n| D5 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D6 | docstring | \"sends POST /api/profile/blocks for that video, then a dislike for it, then fetches page 3\" | :290 | Rules out the wrong order, the wrong body, or a missing step | CARRIED |\n| D7 | docstring | \"the cards left are exactly the loaded ones not on that instance_domain+channel_id, in order\" | :292 | Rules out dropping or reordering a card that should stay | CARRIED |\n| D8 | docstring | \"page-2 cards and a keyless card of the channel go\" | :292 | Rules out removing only cards with a video key, or only page-1 cards (b1 and k2 would stay) | CARRIED |\n| D9 | docstring | \"a card on the same channel_id of another instance and a card of the same account on another channel stay\" | :292 (channel) | Rules out matching on channel_id without the domain (a3 goes) and matching on account (a2 goes) | CARRIED |\n| D10 | docstring | \"Block account does the same on account_url, so that same-account card goes too\" | :290, :292 (account) | Rules out Block account sending the wrong kind or matching on channel | CARRIED |\n| D11 | docstring | \"Page 3 comes back empty, so #search-status reads as it did before the click\" | :294 against :276 | Rules out the status changing after removal | CARRIED |\n| D12 | docstring | \"`.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`\" | :304 | Rules out the wrong text, or text on the wrong element | CARRIED |\n| D13 | docstring | \"with the action name in place of an empty label\" | :304 (account, \"\") | Rules out showing an empty label | CARRIED |\n| D14 | docstring | \"every card is still in the grid, in order\" | :308 | Rules out any card being removed or reordered | CARRIED |\n| N1 | name | \"a block whose dislike succeeds\" | :290 | Rules out the dislike not being sent after the block | CARRIED |\n| N2 | name | \"removes every loaded card of the source\" | :292 | Rules out partial removal or removal on the wrong field | CARRIED |\n| N3 | name | \"and refills the grid\" | :290 | Rules out no fetch of the next page | CARRIED |\n| N4 | name | \"a block whose dislike fails says so on the card\" | :304 | Rules out no message, or the wrong message, on the clicked card | CARRIED |\n| N5 | name | \"and removes nothing\" | :308 | Rules out cards being removed on the failure path | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase3.py:298\n   `@pytest.mark.parametrize((\"kind\", \"label\", \"shown\"), [(\"channel\", \"Alice's channel\", \"Alice's channel\"), (\"account\", \"\", \"account\")])`\n   The empty-label case only runs for `account`, where the action name and the kind are the same string. A page that always falls back to the literal \"account\", or chooses label or action by kind, still passes. A `channel` case with an empty label (shown \"channel\") would rule both out. This is the gap already recorded in the C2b `excludes` cell, and it does not block.\n\nOBSERVATIONS\n1. D5 (whole-claim, rules/testing.md): tests/tmp/test_40_search_card_actions_phase3.py:3\n   The docstring was narrowed, and no assertion was added. On round 1, \"...once the cards were gone\" was UNCARRIED. The docstring now says \"nothing here shows whether that fetch came before or after the cards were removed\". So the test still does not show that the removal happens before the refill. It now says so openly instead of claiming it.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py, which does not exist (rg: No such file or directory). It was not read. The test under audit does not import it.\n2. `fixtures_path` was \"none found\". The test defines its only fixture, `search_bundle`, at :217, so independence was judged from the test file alone.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a successful block followed by a successful dislike\"",
            "assertion": ":290",
            "excludes": "Rules out skipping the dislike, sending it before the block, or sending either one with the wrong uuid/host/kind. The list is compared exactly and in order",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"removes every loaded card of that channel\"",
            "assertion": ":292 (kind=channel)",
            "excludes": "Rules out removing only the clicked card (b1 and k2 would stay), matching on channel_id alone (a3 would go), matching on account (a2 would go), and breaking the order",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"...or account\"",
            "assertion": ":292 (kind=account)",
            "excludes": "Rules out Block account matching on channel instead of account_url (a2 would stay)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"refills the viewport\"",
            "assertion": ":290",
            "excludes": "Rules out a page that never asks for more after removing cards. The sentinel is only in view from the click on (runner :194), and observers are only called before it (:190), so the page 3 GET can only come from the page",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"leaves the status text unchanged\"",
            "assertion": ":294 against :276",
            "excludes": "Rules out recounting the status from the cards left, and rules out writing the block result into `#search-status`",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "reports `Blocked <label>, but the dislike failed: <msg>`",
            "assertion": ":304 (channel, \"Alice's channel\")",
            "excludes": "Rules out reporting only the dislike error, reporting nothing, or showing a generic message instead of the server's `error`",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "`<action>` used when the label is empty",
            "assertion": ":304 (account, \"\")",
            "excludes": "Rules out rendering `Blocked , but the dislike failed: ...`. Does not rule out a fixed fallback string or a choice made by kind (Recommendation 1)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"removes no card\"",
            "assertion": ":308, armed by :306",
            "excludes": "Rules out removing the source's cards whatever the dislike returned. :306 shows the failing dislike was reached",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"block the source and dislike the video\"",
            "assertion": ":290",
            "excludes": "Rules out a sequence missing the block or the dislike",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"take every loaded card of that source off the grid and refill it\"",
            "assertion": ":292, :290",
            "excludes": "Rules out partial removal and a missing refill fetch",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"a block whose dislike fails says so on the card and removes nothing\"",
            "assertion": ":304, :308",
            "excludes": "Rules out no message on the card, and rules out cards being removed anyway",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"a page fetched after the click was asked for by the page itself\"",
            "assertion": ":290",
            "excludes": "Rules out a fetch caused by the harness. Observers are only called before the click (runner :190)",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"sends POST /api/profile/blocks for that video, then a dislike for it, then fetches page 3\"",
            "assertion": ":290",
            "excludes": "Rules out the wrong order, the wrong body, or a missing step",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the cards left are exactly the loaded ones not on that instance_domain+channel_id, in order\"",
            "assertion": ":292",
            "excludes": "Rules out dropping or reordering a card that should stay",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"page-2 cards and a keyless card of the channel go\"",
            "assertion": ":292",
            "excludes": "Rules out removing only cards with a video key, or only page-1 cards (b1 and k2 would stay)",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"a card on the same channel_id of another instance and a card of the same account on another channel stay\"",
            "assertion": ":292 (channel)",
            "excludes": "Rules out matching on channel_id without the domain (a3 goes) and matching on account (a2 goes)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Block account does the same on account_url, so that same-account card goes too\"",
            "assertion": ":290, :292 (account)",
            "excludes": "Rules out Block account sending the wrong kind or matching on channel",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Page 3 comes back empty, so #search-status reads as it did before the click\"",
            "assertion": ":294 against :276",
            "excludes": "Rules out the status changing after removal",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"`.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`\"",
            "assertion": ":304",
            "excludes": "Rules out the wrong text, or text on the wrong element",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"with the action name in place of an empty label\"",
            "assertion": ":304 (account, \"\")",
            "excludes": "Rules out showing an empty label",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"every card is still in the grid, in order\"",
            "assertion": ":308",
            "excludes": "Rules out any card being removed or reordered",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a block whose dislike succeeds\"",
            "assertion": ":290",
            "excludes": "Rules out the dislike not being sent after the block",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"removes every loaded card of the source\"",
            "assertion": ":292",
            "excludes": "Rules out partial removal or removal on the wrong field",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and refills the grid\"",
            "assertion": ":290",
            "excludes": "Rules out no fetch of the next page",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a block whose dislike fails says so on the card\"",
            "assertion": ":304",
            "excludes": "Rules out no message, or the wrong message, on the clicked card",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"and removes nothing\"",
            "assertion": ":308",
            "excludes": "Rules out cards being removed on the failure path",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_40_search_card_actions_phase4.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll three cases of `test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing` should fail at line 288, `assert page[\"prompt\"][\"sent\"] == []`, because `runCardAction` in `client/frontend/src/pages/search/index.ts:247-293` has no profile-key guard. For `dislike`, the list holds `[\"POST\", \"/api/user-action\", {\"action\": \"dislike\", ...}]`. For `channel` and `account`, it holds `[\"POST\", \"/api/profile/blocks\", {\"kind\": ..., \"uuid\": \"uuid-a1\", \"host\": \"peer.example\"}]`. Both cases of `test_a_dislike_rejected_with_400_shows_the_error_re_enables_the_button_and_keeps_the_card_mark` look likely to pass on the code as it stands, for three reasons:\n- the catch at index.ts:289-290 shows `error.message`, which is the `{error}` body that `sendUserAction` passes on;\n- `finally` re-enables the button at index.ts:292;\n- `row.reaction` is set only after the awaited send succeeds (index.ts:268).\n\nNOT ASSESSED\n1. `client/frontend/dist/` was not read. The test bundles `client/frontend/src/pages/search/index.ts` with esbuild and never loads the built output, so dist is outside the test's path.\n2. `tests/tmp/test_frontend_search_card_actions.py`, which `code_under_test` lists, was not read. The test under audit does not import it or rely on it.\n3. I couldn't tell from the files which behaviour came before this phase, so I couldn't confirm whether C2 was red before the phase. The stub question for C2 was answered from the assertion form: each C2 assertion fails against a named wrong implementation.\n   - Line 311 catches a page that shows a generic message or nothing. `LIMIT_ERROR` differs from every default in the code (\"Failed to send action\", \"Action failed\", \"Dislike failed\").\n   - Line 313 catches a page that re-enables the button only on success. Line 308 confirms the button was disabled while the response was held.\n   - Line 315 catches optimistic marking. It runs at two reactions (NEUTRAL, LIKED), so resetting the card to neutral also fails.\n   - Line 318 catches a page that sets `row.reaction` before the request.\n\n   For C1:\n   - A do-nothing stub fails at line 290, where the prompt text is required, and at line 292, where the keyless Like must be sent.\n   - A guard on Dislike alone fails the `channel` and `account` cases at line 288.\n   - One prompt hard-coded for all three actions fails line 290, because the Disliking and Blocking prompts differ.\n\n   No `<anti_pattern>` entry matched:\n   - The negative at line 288 is paired with the positive assertions at lines 290 and 292.\n   - `LIMIT_ERROR` is set at line 300 and asserted at line 311, but `sendUserAction` and `runCardAction`'s catch handle it in between, so it is not an echoed literal.\n\n   The test sits at rung 1: production code runs in node, and the test asserts on DOM state and recorded requests. There is no downshift.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | without a key, Dislike, Block channel and Block account \"each write home's exact profile prompt\" | :290 | a guard on Dislike only, the server's error shown instead of the prompt, or a prompt worded differently from home's (`pages/videos/index.ts:409`); exact equality, one parametrize case per action | CARRIED |\n| C1b | must_prove | \"send no request\" for each of the three | :288 | an unguarded page sending the dislike or block; :292 shows the stub does record requests | CARRIED |\n| C2a | must_prove | a rejected card-action request \"shows its error message\" | :311 | a generic failure text, or nothing, in the card's status line | CARRIED |\n| C2b | must_prove | \"re-enables the button\" | :313 (with :308, :318) | re-enabling only on success; :308 shows the button was disabled first | CARRIED |\n| C2c | must_prove | \"leaves the row's reaction unchanged\": the card mark | :315 | an optimistic dislike mark left in place, or a revert that redraws to neutral on the liked run | CARRIED |\n| C2d | must_prove | \"leaves the row's reaction unchanged\": the row state behind later actions | :318 | `row.reaction` set to `disliked` before the request, which would send `undo_dislike`. It does not exclude a liked row's reaction cleared to `null` without a redraw | CARRIED |\n| C2e | must_prove | the same three facts for a rejected Like, Block channel or Block account request | none | nothing. The rejected scenario only ever presses `dislike` (runner :209) | UNCARRIED |\n| D1 | docstring | \"a search-card Dislike or Block without a profile key asks for a profile on the card\" | :290 | prompt written to the page status line instead of the clicked card's `.card-action-status` | CARRIED |\n| D2 | docstring | \"and sends nothing\" | :288 | any request on the keyless path | CARRIED |\n| D3 | docstring | \"A keyless Like in the same run is sent\" | :292 | a fetch stub that records nothing, or a guard that also blocks Like | CARRIED |\n| D4 | docstring | \"on a neutral card, and in a second run on a liked one\" | :304 | a fixture that does not render the starting mark it claims | CARRIED |\n| D5 | docstring | \"The button is disabled while the response is held\" | :308 | no in-flight disable | CARRIED |\n| D6 | docstring | \"that message is in the card's status line\" | :311 | a generic or missing message | CARRIED |\n| D7 | docstring | \"the clicked button's `disabled` is false\" | :313 | a button left disabled on failure | CARRIED |\n| D8 | docstring | \"the card shows the mark it had before\" | :315 | an unreverted optimistic mark | CARRIED |\n| D9 | docstring | \"a second Dislike sends `dislike`, not `undo_dislike`\" | :318 | the row flipped to disliked before the request | CARRIED |\n| D10 | docstring | \"Clicks land on the icon inside an icon button, or on a text button\" | :307, :292 | a handler that matches only when `event.target` is the button itself, so nothing is sent | CARRIED |\n| N1 | name | \"without a key\" | :283 | a run where a key leaked into storage; the control asserts the keyless page-1 fetch | CARRIED |\n| N2 | name | \"dislike and block write the profile prompt on the card\" | :290 | wrong or missing prompt on the card | CARRIED |\n| N3 | name | \"and send nothing\" | :288 | a request sent | CARRIED |\n| N4 | name | \"a dislike rejected with 400 shows the error\" | :311 | a generic or missing error | CARRIED |\n| N5 | name | \"re-enables the button\" | :313 | a button left disabled | CARRIED |\n| N6 | name | \"keeps the card mark\" | :315 | an unreverted mark | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase4.py:209\n   `const button = press(target, \"dislike\");`\n   - **What C2 claims:** \"A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged.\" A card has four actions: like, dislike, channel and account (`ACTIONS`, :23).\n   - **What the test does:** the rejected scenario hard-codes Dislike as the only action it rejects. The test at :297 is parametrized over the starting reaction only, never over the action.\n   - **What gets through:** a page whose Like path changes `row.reaction` or redraws the card before the request is sent, or whose Block path loses the error or leaves its button disabled, passes this test.\n   - **What the rule requires:** \"a claim naming a set\" asserts every member of the set. Here only one of the four rejected actions is asserted. That is C2e.\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase4.py:318\n   C2d is carried only against a flip to `disliked`. On the `liked` run, a page that clears `row.reaction` to `null` on rejection without redrawing still passes:\n   - :315 still sees the old DOM.\n   - :318 still sends `dislike`, which is the same request from liked or from neutral.\n\n   A Like pressed after the rejection would tell these apart: `undo_like` versus `like`.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase4.py:280\n   \"Without a profile key\" is exercised only as an absent storage entry (`{}`). A stored empty string or a malformed key under `profileKey:v1` is untested.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py. That path does not resolve, so it was not read.\n2. `code_under_test` listed client/frontend/dist/ (REBUILT). It was not read: the test bundles `src/pages/search/index.ts` directly with esbuild (:19, :224), so dist is not exercised by this test.\n3. `fixtures_path` was not supplied. The only fixture, `search_bundle` (:233), is defined in the test file. No conftest was needed to judge independence.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll three cases of `test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing` should fail at line 288, `assert page[\"prompt\"][\"sent\"] == []`, because `runCardAction` in `client/frontend/src/pages/search/index.ts:247-293` has no profile-key guard. For `dislike`, the list holds `[\"POST\", \"/api/user-action\", {\"action\": \"dislike\", ...}]`. For `channel` and `account`, it holds `[\"POST\", \"/api/profile/blocks\", {\"kind\": ..., \"uuid\": \"uuid-a1\", \"host\": \"peer.example\"}]`. Both cases of `test_a_dislike_rejected_with_400_shows_the_error_re_enables_the_button_and_keeps_the_card_mark` look likely to pass on the code as it stands, for three reasons:\n- the catch at index.ts:289-290 shows `error.message`, which is the `{error}` body that `sendUserAction` passes on;\n- `finally` re-enables the button at index.ts:292;\n- `row.reaction` is set only after the awaited send succeeds (index.ts:268).\n\nNOT ASSESSED\n1. `client/frontend/dist/` was not read. The test bundles `client/frontend/src/pages/search/index.ts` with esbuild and never loads the built output, so dist is outside the test's path.\n2. `tests/tmp/test_frontend_search_card_actions.py`, which `code_under_test` lists, was not read. The test under audit does not import it or rely on it.\n3. I couldn't tell from the files which behaviour came before this phase, so I couldn't confirm whether C2 was red before the phase. The stub question for C2 was answered from the assertion form: each C2 assertion fails against a named wrong implementation.\n   - Line 311 catches a page that shows a generic message or nothing. `LIMIT_ERROR` differs from every default in the code (\"Failed to send action\", \"Action failed\", \"Dislike failed\").\n   - Line 313 catches a page that re-enables the button only on success. Line 308 confirms the button was disabled while the response was held.\n   - Line 315 catches optimistic marking. It runs at two reactions (NEUTRAL, LIKED), so resetting the card to neutral also fails.\n   - Line 318 catches a page that sets `row.reaction` before the request.\n\n   For C1:\n   - A do-nothing stub fails at line 290, where the prompt text is required, and at line 292, where the keyless Like must be sent.\n   - A guard on Dislike alone fails the `channel` and `account` cases at line 288.\n   - One prompt hard-coded for all three actions fails line 290, because the Disliking and Blocking prompts differ.\n\n   No `<anti_pattern>` entry matched:\n   - The negative at line 288 is paired with the positive assertions at lines 290 and 292.\n   - `LIMIT_ERROR` is set at line 300 and asserted at line 311, but `sendUserAction` and `runCardAction`'s catch handle it in between, so it is not an echoed literal.\n\n   The test sits at rung 1: production code runs in node, and the test asserts on DOM state and recorded requests. There is no downshift.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | without a key, Dislike, Block channel and Block account \"each write home's exact profile prompt\" | :290 | a guard on Dislike only, the server's error shown instead of the prompt, or a prompt worded differently from home's (`pages/videos/index.ts:409`); exact equality, one parametrize case per action | CARRIED |\n| C1b | must_prove | \"send no request\" for each of the three | :288 | an unguarded page sending the dislike or block; :292 shows the stub does record requests | CARRIED |\n| C2a | must_prove | a rejected card-action request \"shows its error message\" | :311 | a generic failure text, or nothing, in the card's status line | CARRIED |\n| C2b | must_prove | \"re-enables the button\" | :313 (with :308, :318) | re-enabling only on success; :308 shows the button was disabled first | CARRIED |\n| C2c | must_prove | \"leaves the row's reaction unchanged\": the card mark | :315 | an optimistic dislike mark left in place, or a revert that redraws to neutral on the liked run | CARRIED |\n| C2d | must_prove | \"leaves the row's reaction unchanged\": the row state behind later actions | :318 | `row.reaction` set to `disliked` before the request, which would send `undo_dislike`. It does not exclude a liked row's reaction cleared to `null` without a redraw | CARRIED |\n| C2e | must_prove | the same three facts for a rejected Like, Block channel or Block account request | none | nothing. The rejected scenario only ever presses `dislike` (runner :209) | UNCARRIED |\n| D1 | docstring | \"a search-card Dislike or Block without a profile key asks for a profile on the card\" | :290 | prompt written to the page status line instead of the clicked card's `.card-action-status` | CARRIED |\n| D2 | docstring | \"and sends nothing\" | :288 | any request on the keyless path | CARRIED |\n| D3 | docstring | \"A keyless Like in the same run is sent\" | :292 | a fetch stub that records nothing, or a guard that also blocks Like | CARRIED |\n| D4 | docstring | \"on a neutral card, and in a second run on a liked one\" | :304 | a fixture that does not render the starting mark it claims | CARRIED |\n| D5 | docstring | \"The button is disabled while the response is held\" | :308 | no in-flight disable | CARRIED |\n| D6 | docstring | \"that message is in the card's status line\" | :311 | a generic or missing message | CARRIED |\n| D7 | docstring | \"the clicked button's `disabled` is false\" | :313 | a button left disabled on failure | CARRIED |\n| D8 | docstring | \"the card shows the mark it had before\" | :315 | an unreverted optimistic mark | CARRIED |\n| D9 | docstring | \"a second Dislike sends `dislike`, not `undo_dislike`\" | :318 | the row flipped to disliked before the request | CARRIED |\n| D10 | docstring | \"Clicks land on the icon inside an icon button, or on a text button\" | :307, :292 | a handler that matches only when `event.target` is the button itself, so nothing is sent | CARRIED |\n| N1 | name | \"without a key\" | :283 | a run where a key leaked into storage; the control asserts the keyless page-1 fetch | CARRIED |\n| N2 | name | \"dislike and block write the profile prompt on the card\" | :290 | wrong or missing prompt on the card | CARRIED |\n| N3 | name | \"and send nothing\" | :288 | a request sent | CARRIED |\n| N4 | name | \"a dislike rejected with 400 shows the error\" | :311 | a generic or missing error | CARRIED |\n| N5 | name | \"re-enables the button\" | :313 | a button left disabled | CARRIED |\n| N6 | name | \"keeps the card mark\" | :315 | an unreverted mark | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase4.py:209\n   `const button = press(target, \"dislike\");`\n   - **What C2 claims:** \"A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged.\" A card has four actions: like, dislike, channel and account (`ACTIONS`, :23).\n   - **What the test does:** the rejected scenario hard-codes Dislike as the only action it rejects. The test at :297 is parametrized over the starting reaction only, never over the action.\n   - **What gets through:** a page whose Like path changes `row.reaction` or redraws the card before the request is sent, or whose Block path loses the error or leaves its button disabled, passes this test.\n   - **What the rule requires:** \"a claim naming a set\" asserts every member of the set. Here only one of the four rejected actions is asserted. That is C2e.\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase4.py:318\n   C2d is carried only against a flip to `disliked`. On the `liked` run, a page that clears `row.reaction` to `null` on rejection without redrawing still passes:\n   - :315 still sees the old DOM.\n   - :318 still sends `dislike`, which is the same request from liked or from neutral.\n\n   A Like pressed after the rejection would tell these apart: `undo_like` versus `like`.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_40_search_card_actions_phase4.py:280\n   \"Without a profile key\" is exercised only as an absent storage entry (`{}`). A stored empty string or a malformed key under `profileKey:v1` is untested.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py. That path does not resolve, so it was not read.\n2. `code_under_test` listed client/frontend/dist/ (REBUILT). It was not read: the test bundles `src/pages/search/index.ts` directly with esbuild (:19, :224), so dist is not exercised by this test.\n3. `fixtures_path` was not supplied. The only fixture, `search_bundle` (:233), is defined in the test file. No conftest was needed to judge independence.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "without a key, Dislike, Block channel and Block account \"each write home's exact profile prompt\"",
            "assertion": ":290",
            "excludes": "a guard on Dislike only, the server's error shown instead of the prompt, or a prompt worded differently from home's (`pages/videos/index.ts:409`); exact equality, one parametrize case per action",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"send no request\" for each of the three",
            "assertion": ":288",
            "excludes": "an unguarded page sending the dislike or block; :292 shows the stub does record requests",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a rejected card-action request \"shows its error message\"",
            "assertion": ":311",
            "excludes": "a generic failure text, or nothing, in the card's status line",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"re-enables the button\"",
            "assertion": ":313 (with :308, :318)",
            "excludes": "re-enabling only on success; :308 shows the button was disabled first",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"leaves the row's reaction unchanged\": the card mark",
            "assertion": ":315",
            "excludes": "an optimistic dislike mark left in place, or a revert that redraws to neutral on the liked run",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "\"leaves the row's reaction unchanged\": the row state behind later actions",
            "assertion": ":318",
            "excludes": "`row.reaction` set to `disliked` before the request, which would send `undo_dislike`. It does not exclude a liked row's reaction cleared to `null` without a redraw",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "the same three facts for a rejected Like, Block channel or Block account request",
            "assertion": "none",
            "excludes": "nothing. The rejected scenario only ever presses `dislike` (runner :209)",
            "status": "UNCARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"a search-card Dislike or Block without a profile key asks for a profile on the card\"",
            "assertion": ":290",
            "excludes": "prompt written to the page status line instead of the clicked card's `.card-action-status`",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"and sends nothing\"",
            "assertion": ":288",
            "excludes": "any request on the keyless path",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"A keyless Like in the same run is sent\"",
            "assertion": ":292",
            "excludes": "a fetch stub that records nothing, or a guard that also blocks Like",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"on a neutral card, and in a second run on a liked one\"",
            "assertion": ":304",
            "excludes": "a fixture that does not render the starting mark it claims",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"The button is disabled while the response is held\"",
            "assertion": ":308",
            "excludes": "no in-flight disable",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"that message is in the card's status line\"",
            "assertion": ":311",
            "excludes": "a generic or missing message",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the clicked button's `disabled` is false\"",
            "assertion": ":313",
            "excludes": "a button left disabled on failure",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"the card shows the mark it had before\"",
            "assertion": ":315",
            "excludes": "an unreverted optimistic mark",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"a second Dislike sends `dislike`, not `undo_dislike`\"",
            "assertion": ":318",
            "excludes": "the row flipped to disliked before the request",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Clicks land on the icon inside an icon button, or on a text button\"",
            "assertion": ":307, :292",
            "excludes": "a handler that matches only when `event.target` is the button itself, so nothing is sent",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"without a key\"",
            "assertion": ":283",
            "excludes": "a run where a key leaked into storage; the control asserts the keyless page-1 fetch",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"dislike and block write the profile prompt on the card\"",
            "assertion": ":290",
            "excludes": "wrong or missing prompt on the card",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and send nothing\"",
            "assertion": ":288",
            "excludes": "a request sent",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a dislike rejected with 400 shows the error\"",
            "assertion": ":311",
            "excludes": "a generic or missing error",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"re-enables the button\"",
            "assertion": ":313",
            "excludes": "a button left disabled",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"keeps the card mark\"",
            "assertion": ":315",
            "excludes": "an unreverted mark",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll three parametrizations of `test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing` should fail at line 294, `assert page[\"prompt\"][\"sent\"] == []`. `runCardAction` in `client/frontend/src/pages/search/index.ts:247-293` never checks for a profile key. Without a key, `dislike` sends `[\"POST\", \"/api/user-action\", {...}]` through `sendReaction`, and `channel` and `account` send `[\"POST\", \"/api/profile/blocks\", {...}]` through `blockVideoSource`. The eight cases of `test_a_rejected_card_action_shows_the_error_re_enables_the_button_and_keeps_the_reaction` should pass as the code stands. The `catch` at index.ts:289-290 puts the thrown `payload.error` in `.card-action-status`. The `finally` at index.ts:291-292 turns the button back on. The card is only redrawn after the request is accepted. So a green C2 here is expected, and it is not evidence of a stub.\n\nAnti-patterns pass (rules/shape.md):\n- **doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep:** don't apply. The test reads no `.md` file and no extracted section. Every assertion is on the JSON report the bundled page emits.\n- **hardcoded-spec-mirror:** doesn't apply. The prompt literals at lines 279-281 and `ACTIONS` at line 23 are compared against rendered card state (lines 290, 296), not against a code constant.\n- **tautological-assertion:** doesn't apply. `_sent` and `_blocked` (lines 257-262) build the expected requests from the test's own row fixture. They do not re-derive the page's logic.\n- **absence-only-assertion:** doesn't apply. The empty list at line 294 comes with a positive assertion on the prompt text (line 296) and a control in the same run (line 298) where a keyless Like is recorded.\n- **echoed-literal:** doesn't apply. `ACTION_ERROR` goes into the stub fetch and shows up at line 326 only after passing through `sendUserAction`/`blockVideoSource` parsing and the page's `catch`/`say`. Deleting index.ts:290 turns it red.\n- **single-value-pin:** doesn't apply. There are three different error strings across four actions, two different prompts, and two starting reactions. Each starting reaction expects a different follow-up request (`like` vs `undo_like`, line 333). The disabled-false assertion at line 328 is set against a held-request check at line 321 that requires the button to be disabled.\n\nLadder pass (rules/shape.md `<ladder>`):\n- **Rung:** the test bundles the real entry point, runs it as a node subprocess, drives clicks and asserts on observed side effects (requests sent, status text, `disabled`, card marks). That is rung 1/2 behaviour invocation, the highest rung this invariant supports.\n- **Anti-rung and downshift:** the test is not on the anti-rung and does not downshift.\n\nStub question:\n- **Keyless guard on Dislike only:** fails the `channel` and `account` cases at line 294.\n- **Page that sends nothing for any action:** fails the control at line 298.\n- **Hard-coded or generic error message:** fails line 326 for at least one parametrization.\n- **Re-enabling only on success:** fails line 328.\n- **Marking the card optimistically, or changing the row's reaction:** fails line 330 or line 333.\n\nNOT ASSESSED\n1. `client/frontend/dist/ (REBUILT)` was not read. The test bundles `src/pages/search/index.ts` with esbuild itself (lines 222-235) and never loads `dist/`.\n2. `tests/tmp/test_frontend_search_card_actions.py`, listed in `code_under_test`, was not read. The audited test does not import from it or rely on it.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | without a key, Dislike, Block channel and Block account \"each write home's exact profile prompt\" | :296 | a guard on Dislike only; the server's error shown instead of the prompt; a prompt worded differently from home's (`pages/videos/index.ts:409`). Exact equality, one parametrize case per action (:278-282) | CARRIED |\n| C1b | must_prove | \"send no request\" for each of the three | :294 | an unguarded page sending the dislike or block. :298 shows the stub records requests | CARRIED |\n| C2a | must_prove | a rejected card-action request \"shows its error message\" | :326 | a generic failure text, or nothing, in the card's status line | CARRIED |\n| C2b | must_prove | \"re-enables the button\" | :328 (with :321) | re-enabling only on success. :321 shows the button was disabled while the response was held | CARRIED |\n| C2c | must_prove | \"leaves the row's reaction unchanged\": the card mark | :330 | an optimistic mark left in place, or a redraw to neutral on the liked run | CARRIED |\n| C2d | must_prove | \"leaves the row's reaction unchanged\": the row state behind later actions | :333 | a row left `disliked` (sends `undo_dislike`); a liked row cleared to `null` (sends `like`, not `undo_like`); a neutral row left `liked` (sends `undo_like`). This closes the gap noted on round one | CARRIED |\n| C2e | must_prove | the same three facts for a rejected Like, Block channel or Block account request | :326, :328, :330, :333 under the :302-307 parametrize | a revert, re-enable or error display wired only on the Dislike branch. Every action now runs through all four assertions, on a neutral row and on a liked one | CARRIED |\n| D1 | docstring | \"a search-card Dislike or Block without a profile key asks for a profile on the card\" | :296 | the prompt written to the page status line instead of the clicked card's `.card-action-status` | CARRIED |\n| D2 | docstring | \"and sends nothing\" | :294 | any request on the keyless path | CARRIED |\n| D3 | docstring | \"A keyless Like in the same run is sent\" | :298 | a fetch stub that records nothing, or a guard that also blocks Like | CARRIED |\n| D4 | docstring | \"on a neutral card and in a second run on a liked one\" | :317 (with the :308 parametrize) | a fixture that does not render the starting mark it claims | CARRIED |\n| D5 | docstring | \"The button is disabled while the response is held\" | :321 (with :319) | no in-flight disable | CARRIED |\n| D6 | docstring | \"that message is in the card's status line\" | :326 | a generic or missing message | CARRIED |\n| D7 | docstring | \"the clicked button's `disabled` is false\" | :328 | a button left disabled on failure | CARRIED |\n| D8 | docstring | \"the card ... showing the mark it had before\" | :330 | an unreverted optimistic mark | CARRIED |\n| D9 | docstring | \"a Dislike then a Like on it send `dislike` then `like` from a neutral card, `dislike` then `undo_like` from a liked one\" (reworded and widened from round one's \"a second Dislike sends `dislike`\") | :333 | a row reaction moved before the request, or cleared on failure | CARRIED |\n| D10 | docstring | \"Clicks land on the icon inside an icon button, or on a text button itself\" | :320, :298 (runner :196 clicks the `path` when one exists) | a handler that matches only when `event.target` is the button itself, so nothing is sent | CARRIED |\n| N1 | name | \"without a key\" | :296 (setup :286 passes empty storage) | a run where a key reached storage. That run would send the request rather than show the prompt. The :289 control does not separate keyed from keyless (see OBSERVATIONS) | CARRIED |\n| N2 | name | \"dislike and block write the profile prompt on the card\" | :296 | a wrong or missing prompt on the card | CARRIED |\n| N3 | name | \"and send nothing\" | :294 | a request sent | CARRIED |\n| N4 | name | \"a rejected card action shows the error\" (widened from \"a dislike rejected with 400\") | :326 | a generic or missing error, for any of the four actions | CARRIED |\n| N5 | name | \"re-enables the button\" | :328 | a button left disabled | CARRIED |\n| N6 | name | \"keeps the reaction\" (widened from \"keeps the card mark\") | :330, :333 | an unreverted mark, or a row reaction changed behind an unchanged mark | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase4.py:289\n   `assert page[\"searches\"] == SEARCH_PAGE_1` is labelled as the keyless control, but the keyed test asserts the same value at :316. `calls()` (runner :195) records only method, path and body, with no headers. So this line cannot tell a keyless page from a keyed one. N1 is still carried by :296, because the prompt only appears on the keyless path. The comment at :288 overstates what :289 shows.\n2. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase4.py:6\n   The docstring says each rejection is \"the Client backend's own error\". The test supplies those strings itself through the stub (:273-275, runner :165). Nothing here checks them against the backend, so this phrase describes the fixture, not a fact the test proves. No ledger row covers it.\n3. Prose changes since round one. N4, N6 and D9 were all reworded to widen them, not narrow them, and each widened clause has an assertion that carries it (:326, :330, :333). No row was withdrawn. The docstring adds \"the card is still on the grid\", which :324 carries.\n\nNOT ASSESSED\n1. `code_under_test` lists client/frontend/dist/ (rebuilt output). The test bundles `src/pages/search/index.ts` directly (:19, :224), so the dist output was not read.\n2. tests/tmp/test_frontend_search_card_actions.py is listed in `code_under_test` but this test does not exercise it. It was not read.\n3. `renderVideoCard` and `sendReaction` / `blockVideoSource` (imported modules) were not read. Which buttons hold an icon `path` is taken from runner :196 and not confirmed against the markup.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll three parametrizations of `test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing` should fail at line 294, `assert page[\"prompt\"][\"sent\"] == []`. `runCardAction` in `client/frontend/src/pages/search/index.ts:247-293` never checks for a profile key. Without a key, `dislike` sends `[\"POST\", \"/api/user-action\", {...}]` through `sendReaction`, and `channel` and `account` send `[\"POST\", \"/api/profile/blocks\", {...}]` through `blockVideoSource`. The eight cases of `test_a_rejected_card_action_shows_the_error_re_enables_the_button_and_keeps_the_reaction` should pass as the code stands. The `catch` at index.ts:289-290 puts the thrown `payload.error` in `.card-action-status`. The `finally` at index.ts:291-292 turns the button back on. The card is only redrawn after the request is accepted. So a green C2 here is expected, and it is not evidence of a stub.\n\nAnti-patterns pass (rules/shape.md):\n- **doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep:** don't apply. The test reads no `.md` file and no extracted section. Every assertion is on the JSON report the bundled page emits.\n- **hardcoded-spec-mirror:** doesn't apply. The prompt literals at lines 279-281 and `ACTIONS` at line 23 are compared against rendered card state (lines 290, 296), not against a code constant.\n- **tautological-assertion:** doesn't apply. `_sent` and `_blocked` (lines 257-262) build the expected requests from the test's own row fixture. They do not re-derive the page's logic.\n- **absence-only-assertion:** doesn't apply. The empty list at line 294 comes with a positive assertion on the prompt text (line 296) and a control in the same run (line 298) where a keyless Like is recorded.\n- **echoed-literal:** doesn't apply. `ACTION_ERROR` goes into the stub fetch and shows up at line 326 only after passing through `sendUserAction`/`blockVideoSource` parsing and the page's `catch`/`say`. Deleting index.ts:290 turns it red.\n- **single-value-pin:** doesn't apply. There are three different error strings across four actions, two different prompts, and two starting reactions. Each starting reaction expects a different follow-up request (`like` vs `undo_like`, line 333). The disabled-false assertion at line 328 is set against a held-request check at line 321 that requires the button to be disabled.\n\nLadder pass (rules/shape.md `<ladder>`):\n- **Rung:** the test bundles the real entry point, runs it as a node subprocess, drives clicks and asserts on observed side effects (requests sent, status text, `disabled`, card marks). That is rung 1/2 behaviour invocation, the highest rung this invariant supports.\n- **Anti-rung and downshift:** the test is not on the anti-rung and does not downshift.\n\nStub question:\n- **Keyless guard on Dislike only:** fails the `channel` and `account` cases at line 294.\n- **Page that sends nothing for any action:** fails the control at line 298.\n- **Hard-coded or generic error message:** fails line 326 for at least one parametrization.\n- **Re-enabling only on success:** fails line 328.\n- **Marking the card optimistically, or changing the row's reaction:** fails line 330 or line 333.\n\nNOT ASSESSED\n1. `client/frontend/dist/ (REBUILT)` was not read. The test bundles `src/pages/search/index.ts` with esbuild itself (lines 222-235) and never loads `dist/`.\n2. `tests/tmp/test_frontend_search_card_actions.py`, listed in `code_under_test`, was not read. The audited test does not import from it or rely on it.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | without a key, Dislike, Block channel and Block account \"each write home's exact profile prompt\" | :296 | a guard on Dislike only; the server's error shown instead of the prompt; a prompt worded differently from home's (`pages/videos/index.ts:409`). Exact equality, one parametrize case per action (:278-282) | CARRIED |\n| C1b | must_prove | \"send no request\" for each of the three | :294 | an unguarded page sending the dislike or block. :298 shows the stub records requests | CARRIED |\n| C2a | must_prove | a rejected card-action request \"shows its error message\" | :326 | a generic failure text, or nothing, in the card's status line | CARRIED |\n| C2b | must_prove | \"re-enables the button\" | :328 (with :321) | re-enabling only on success. :321 shows the button was disabled while the response was held | CARRIED |\n| C2c | must_prove | \"leaves the row's reaction unchanged\": the card mark | :330 | an optimistic mark left in place, or a redraw to neutral on the liked run | CARRIED |\n| C2d | must_prove | \"leaves the row's reaction unchanged\": the row state behind later actions | :333 | a row left `disliked` (sends `undo_dislike`); a liked row cleared to `null` (sends `like`, not `undo_like`); a neutral row left `liked` (sends `undo_like`). This closes the gap noted on round one | CARRIED |\n| C2e | must_prove | the same three facts for a rejected Like, Block channel or Block account request | :326, :328, :330, :333 under the :302-307 parametrize | a revert, re-enable or error display wired only on the Dislike branch. Every action now runs through all four assertions, on a neutral row and on a liked one | CARRIED |\n| D1 | docstring | \"a search-card Dislike or Block without a profile key asks for a profile on the card\" | :296 | the prompt written to the page status line instead of the clicked card's `.card-action-status` | CARRIED |\n| D2 | docstring | \"and sends nothing\" | :294 | any request on the keyless path | CARRIED |\n| D3 | docstring | \"A keyless Like in the same run is sent\" | :298 | a fetch stub that records nothing, or a guard that also blocks Like | CARRIED |\n| D4 | docstring | \"on a neutral card and in a second run on a liked one\" | :317 (with the :308 parametrize) | a fixture that does not render the starting mark it claims | CARRIED |\n| D5 | docstring | \"The button is disabled while the response is held\" | :321 (with :319) | no in-flight disable | CARRIED |\n| D6 | docstring | \"that message is in the card's status line\" | :326 | a generic or missing message | CARRIED |\n| D7 | docstring | \"the clicked button's `disabled` is false\" | :328 | a button left disabled on failure | CARRIED |\n| D8 | docstring | \"the card ... showing the mark it had before\" | :330 | an unreverted optimistic mark | CARRIED |\n| D9 | docstring | \"a Dislike then a Like on it send `dislike` then `like` from a neutral card, `dislike` then `undo_like` from a liked one\" (reworded and widened from round one's \"a second Dislike sends `dislike`\") | :333 | a row reaction moved before the request, or cleared on failure | CARRIED |\n| D10 | docstring | \"Clicks land on the icon inside an icon button, or on a text button itself\" | :320, :298 (runner :196 clicks the `path` when one exists) | a handler that matches only when `event.target` is the button itself, so nothing is sent | CARRIED |\n| N1 | name | \"without a key\" | :296 (setup :286 passes empty storage) | a run where a key reached storage. That run would send the request rather than show the prompt. The :289 control does not separate keyed from keyless (see OBSERVATIONS) | CARRIED |\n| N2 | name | \"dislike and block write the profile prompt on the card\" | :296 | a wrong or missing prompt on the card | CARRIED |\n| N3 | name | \"and send nothing\" | :294 | a request sent | CARRIED |\n| N4 | name | \"a rejected card action shows the error\" (widened from \"a dislike rejected with 400\") | :326 | a generic or missing error, for any of the four actions | CARRIED |\n| N5 | name | \"re-enables the button\" | :328 | a button left disabled | CARRIED |\n| N6 | name | \"keeps the reaction\" (widened from \"keeps the card mark\") | :330, :333 | an unreverted mark, or a row reaction changed behind an unchanged mark | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase4.py:289\n   `assert page[\"searches\"] == SEARCH_PAGE_1` is labelled as the keyless control, but the keyed test asserts the same value at :316. `calls()` (runner :195) records only method, path and body, with no headers. So this line cannot tell a keyless page from a keyed one. N1 is still carried by :296, because the prompt only appears on the keyless path. The comment at :288 overstates what :289 shows.\n2. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase4.py:6\n   The docstring says each rejection is \"the Client backend's own error\". The test supplies those strings itself through the stub (:273-275, runner :165). Nothing here checks them against the backend, so this phrase describes the fixture, not a fact the test proves. No ledger row covers it.\n3. Prose changes since round one. N4, N6 and D9 were all reworded to widen them, not narrow them, and each widened clause has an assertion that carries it (:326, :330, :333). No row was withdrawn. The docstring adds \"the card is still on the grid\", which :324 carries.\n\nNOT ASSESSED\n1. `code_under_test` lists client/frontend/dist/ (rebuilt output). The test bundles `src/pages/search/index.ts` directly (:19, :224), so the dist output was not read.\n2. tests/tmp/test_frontend_search_card_actions.py is listed in `code_under_test` but this test does not exercise it. It was not read.\n3. `renderVideoCard` and `sendReaction` / `blockVideoSource` (imported modules) were not read. Which buttons hold an icon `path` is taken from runner :196 and not confirmed against the markup.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "without a key, Dislike, Block channel and Block account \"each write home's exact profile prompt\"",
            "assertion": ":296",
            "excludes": "a guard on Dislike only; the server's error shown instead of the prompt; a prompt worded differently from home's (`pages/videos/index.ts:409`). Exact equality, one parametrize case per action (:278-282)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"send no request\" for each of the three",
            "assertion": ":294",
            "excludes": "an unguarded page sending the dislike or block. :298 shows the stub records requests",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a rejected card-action request \"shows its error message\"",
            "assertion": ":326",
            "excludes": "a generic failure text, or nothing, in the card's status line",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"re-enables the button\"",
            "assertion": ":328 (with :321)",
            "excludes": "re-enabling only on success. :321 shows the button was disabled while the response was held",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"leaves the row's reaction unchanged\": the card mark",
            "assertion": ":330",
            "excludes": "an optimistic mark left in place, or a redraw to neutral on the liked run",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "\"leaves the row's reaction unchanged\": the row state behind later actions",
            "assertion": ":333",
            "excludes": "a row left `disliked` (sends `undo_dislike`); a liked row cleared to `null` (sends `like`, not `undo_like`); a neutral row left `liked` (sends `undo_like`). This closes the gap noted on round one",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "the same three facts for a rejected Like, Block channel or Block account request",
            "assertion": ":326, :328, :330, :333 under the :302-307 parametrize",
            "excludes": "a revert, re-enable or error display wired only on the Dislike branch. Every action now runs through all four assertions, on a neutral row and on a liked one",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"a search-card Dislike or Block without a profile key asks for a profile on the card\"",
            "assertion": ":296",
            "excludes": "the prompt written to the page status line instead of the clicked card's `.card-action-status`",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"and sends nothing\"",
            "assertion": ":294",
            "excludes": "any request on the keyless path",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"A keyless Like in the same run is sent\"",
            "assertion": ":298",
            "excludes": "a fetch stub that records nothing, or a guard that also blocks Like",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"on a neutral card and in a second run on a liked one\"",
            "assertion": ":317 (with the :308 parametrize)",
            "excludes": "a fixture that does not render the starting mark it claims",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"The button is disabled while the response is held\"",
            "assertion": ":321 (with :319)",
            "excludes": "no in-flight disable",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"that message is in the card's status line\"",
            "assertion": ":326",
            "excludes": "a generic or missing message",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the clicked button's `disabled` is false\"",
            "assertion": ":328",
            "excludes": "a button left disabled on failure",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"the card ... showing the mark it had before\"",
            "assertion": ":330",
            "excludes": "an unreverted optimistic mark",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"a Dislike then a Like on it send `dislike` then `like` from a neutral card, `dislike` then `undo_like` from a liked one\" (reworded and widened from round one's \"a second Dislike sends `dislike`\")",
            "assertion": ":333",
            "excludes": "a row reaction moved before the request, or cleared on failure",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Clicks land on the icon inside an icon button, or on a text button itself\"",
            "assertion": ":320, :298 (runner :196 clicks the `path` when one exists)",
            "excludes": "a handler that matches only when `event.target` is the button itself, so nothing is sent",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"without a key\"",
            "assertion": ":296 (setup :286 passes empty storage)",
            "excludes": "a run where a key reached storage. That run would send the request rather than show the prompt. The :289 control does not separate keyed from keyless (see OBSERVATIONS)",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"dislike and block write the profile prompt on the card\"",
            "assertion": ":296",
            "excludes": "a wrong or missing prompt on the card",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and send nothing\"",
            "assertion": ":294",
            "excludes": "a request sent",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a rejected card action shows the error\" (widened from \"a dislike rejected with 400\")",
            "assertion": ":326",
            "excludes": "a generic or missing error, for any of the four actions",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"re-enables the button\"",
            "assertion": ":328",
            "excludes": "a button left disabled",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"keeps the reaction\" (widened from \"keeps the card mark\")",
            "assertion": ":330, :333",
            "excludes": "an unreverted mark, or a row reaction changed behind an unchanged mark",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nclient/frontend/src/pages/search/index.ts \u2014 in `runCardAction`, renamed the local `status` (the card's `.card-action-status` element) to `cardStatus`. It was shadowing the module-level `status` (`#search-status`) that `setStatus` writes to. Behaviour is unchanged: the only uses are the declaration and the `say` closure, and grep shows no other `status` reference inside the function.\n</refactors>\n\n<left_out>\nMerging the like and dislike branches in `runCardAction` into one toggle branch: the two branches copy home's structure in `pages/videos/index.ts` line for line, and the merge would build the action as `undo_${action}`, which has to type-check against `ReactionAction`. I have not run tsc to confirm that, so I left it. Pulling the parts shared with home's `runCardAction` (the no-key guard, the `say` helper, the block-follow-up dislike and the channel/account match predicate) into a shared module: that would touch `pages/videos/index.ts` and add a new file, both outside this build's files. It is a candidate for its own issue. video-card.ts: phase 1 only added the Dislike `aria-pressed` attribute, which matches the Like button and needed no refactor. The older duplication in `videoPageUrl` (channel label resolution, `resolveVideoId` order) and the unused `replace` argument of `pushUrl` were there before this build, so I left them alone. client/frontend/dist/ was not rebuilt (I have no shell); `cd client/frontend && npm run build` is still owed. tests/tmp/test_probe_40_p2_impl.py from phase 2 is still there and should be deleted. The pass rules slot in the step prompt came through as a literal `{rat_tail_rules}` placeholder. I worked to the role's rat-tail rule instead: this build makes no deliberate simplifications, so no `rat-tail:` comment is owed.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nRead against the code, the four phases' changes are already minimal and follow home's card-action pattern; the only safe refactor in scope was removing a variable that shadowed the module-level `status`. I have not run the checkpoints or tsc after the rename; the workflow's run will confirm it.\n</observation>"
}
```
dev-flow:state -->

## 2026-10-01 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/40",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 46 test groups (45 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.0s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

The brief says "A rejected key is handled as the search page already handles ProfileKeyRejectedError", but in the tree `sendUserAction` (user-actions.ts) and blocks.ts `request` throw a plain Error on 401, never ProfileKeyRejectedError, and home's runCardAction shows that message in the card status line. The operator resolved this: card actions show the rejected-key error in the card's status line, as home does, and the data layer is unchanged.

## 2026-10-01 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-10-01 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impacts>
<impact path="client/frontend/src/pages/search/index.ts" element="module-level imports (lines 11-20)">
**What changes:** the import list grows.
- `../../components/video-card` adds `resolveInstanceDomain`, `resolveVideoId` and `resolveVideoKey` next to `renderVideoCard`.
- `../../data/reactions` adds `sendReaction` next to `cardReaction` and `importLocalLikes`.
- `../../data/profile` adds `getProfileKey` next to `ProfileKeyRejectedError`.
- A new import of `blockVideoSource` comes from `../../data/blocks`.

**What depends on it:** Vite chunking. `blocks.ts` is already a shared chunk (`dist/assets/blocks-*.js`, imported by home), so the search entry gains one more chunk import and pulls in nothing new.

**Risk:** low.
- `npm run build` is `vite build`, which has no `tsc` step (package.json line 9). A wrong or missing named import, or a type error, is not caught at build time. A missing import fails at runtime, and only on the first click. The implementer should run `npx tsc --noEmit -p client/frontend`, or bundle with esbuild as the tests do, to catch it.
- The style is one import per module, with braces split over lines when the list grows; follow it.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="module docstring (lines 1-7)">
**What changes:** the header describes only query/sort-in-URL and paging. It should gain one or two sentences saying:
- result cards carry Like, Dislike, Block channel and Block account;
- Dislike toggles and the card stays, unlike home;
- a block removes the loaded cards of that channel or account, while the status count keeps counting fetched rows.

**What depends on it:** nothing at runtime.

**Risk:** none at runtime. The risk is documentation drift if it is left out. This is the place a future reader learns why search's handler differs from home's.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="state object (lines 49-60): new `rows: [] as VideoRow[]`">
**What changes:** `state` gains `rows`, typed the way home declares it (`rows: [] as VideoRow[]`, videos/index.ts line 85). Add a `/** ... */` field comment, matching `hasMore` and `requestSeq`.

**What depends on it:**
- the new click listener (`state.rows.find`);
- `runCardAction`, through the row reference it holds;
- `removeRows`, which reassigns `state.rows`;
- `renderRows`, which appends to it.

**Risk:** moderate.
- If `rows` is not cleared on every reset path, a click on a fresh card could resolve to a stale row object from the previous query that has the same key. That row would carry a stale `reaction` and could toggle the wrong way.
- The order must match DOM order. Appending page rows in `renderRows`, after the `seq` check, keeps them in step.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="loadPage() reset branch (lines 151-154) and its callers: startSearch, popstate handler, initial load, keyRejectedNotice retry (line 174)">
**What changes:** the `if (reset)` block, which already clears `results.innerHTML` and `state.loadedRows`, also sets `state.rows = []`. One place covers new search, sort change (through `startSearch`), popstate, the initial load and the "Forget key" retry, since `keyRejectedNotice(() => void loadPage(1, true))` re-enters here.

**Alternatives:** clearing in `renderRows`' `reset` branch would also work. It would leave a stale `rows` while the grid is empty during the fetch, which is harmless because no cards exist then. It would also leave `rows` uncleared when the reset fetch fails.

**Recommendation:** clear in the `loadPage` reset block, next to `loadedRows`, so that a failed reset (SearchUnavailable, ProfileKeyRejected, network) leaves no orphan rows.

**What depends on it:** row lookup (req 2) and the race guard described in the plan's gotchas.

**Risk:** low, provided it is placed in the reset block. Placed only in `renderRows`, it would leave stale rows after a failed reset. They are unreachable because the grid holds no cards, so the result is cosmetic.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="loadPage() error branch for ProfileKeyRejectedError (lines 172-174)">
**What changes:** nothing, per req 7.

**Interaction to be aware of:** on an appended page (`reset=false`), a rejected key replaces the whole grid with `keyRejectedNotice` but does not clear `state.rows`. After that the grid has no `.video-card`, so no click can resolve a row and `removeRows` finds no DOM nodes to remove. The stale rows are harmless and are cleared by the retry's `loadPage(1, true)`.

**What depends on it:** the operator decision (req 7). A 401 from `/api/user-action` or `/api/profile/blocks` surfaces as a plain `Error` (see user-actions.ts and blocks.ts) whose message goes into the card's status line. It does not route here.

**Risk:**
- Regression risk is none.
- Behavioural note: the issue brief (docs/project/issues/40, "Errors" bullet) says "A rejected key is handled as the search page already handles `ProfileKeyRejectedError`". The plan's req 7 records a different operator decision, so the reviewer should confirm that the plan's text is the one that governs.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="renderRows() (lines 204-214) and a new card-render function (search's counterpart to home's renderFeedCard)">
**What changes:**
- A new function renders one row through `renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true })`. A name such as `renderSearchCard` fits, with a one-line `/** ... */` docstring in the file's style.
- `renderRows` maps rows through it on both the reset and append paths, and appends the rows to `state.rows`.
- `runCardAction` reuses the same function for the in-place re-render, so the first render and the re-render cannot diverge (req 3 says "through the same `renderVideoCard` options search uses").

**What depends on it:**
- Every card on the search page now carries `.card-actions` when `resolveVideoKey(row)` is non-null. Cards without a key still get none, which the component enforces with `options.actions && videoKey`.
- The `insertAdjacentHTML("beforeend")` append path keeps cards as direct children of `#search-results`. `removeRows` relies on that.

**Risk:** low.
- Card height grows by one row of buttons. The sentinel moves down, so `fillViewport` fetches fewer pages for the same viewport. This is visual only.
- `renderRows` is called after the `seq` check (line 182), so rows from a stale response are never appended. Keep the `state.rows` push inside `renderRows`, or immediately after the call, and not before line 182.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new delegated click listener on `results` (#search-results)">
**What changes:** one `results.addEventListener("click", ...)` is registered at module top level, next to the existing form and sort listeners. It mirrors videos/index.ts lines 135-141 almost word for word:
1. `closest<HTMLButtonElement>("[data-card-action]")`
2. `closest<HTMLElement>(".video-card")`
3. `dataset.videoKey`
4. `state.rows.find((candidate) => resolveVideoKey(candidate) === key)`
5. `void runCardAction(...)` if all three resolve.

**What depends on it:**
- Cards appended by later pages (req 8) need no extra wiring.
- The `keyRejectedNotice` "Forget key" button lives inside `#search-results`. Its click bubbles to this listener, finds no `[data-card-action]`, and does nothing, which is correct.
- The card's main `<a class="video-link">` and the channel link are not inside `[data-card-action]`, so navigation is unaffected. The component puts `.card-actions` outside the `<a>`, as the comment at video-card.ts line 351 says.

**Risk:** low.
- `event.target` can be the SVG `<path>` inside the Like or Dislike button. `Element.closest` works on SVG elements, the same as on home.
- A double click while the button is disabled: disabled buttons do not dispatch click, so nothing happens.
- A fast click on another card's button while the first card's action is in flight is independent, the same as on home.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new runCardAction(button, card, row)">
**What changes:** this is new code, modelled on home's `runCardAction` (videos/index.ts lines 400-447).

**Same as home:**
- the `say` helper writing to `.card-action-status`;
- the no-key guard, with the exact text ``${action === "dislike" ? "Disliking" : "Blocking"} needs a profile. Create one from the Profile button.``;
- disable and clear before the request, and `finally` re-enables;
- Like toggles on `cardReaction(row) === "liked"`;
- the block path is `blockVideoSource`, then a `sendReaction("dislike")` `.then(() => null, err => message)`, then "Blocked … but the dislike failed" with an early return;
- the error message falls back to "Action failed".

**Different from home:**
- `apiBase` is `apiParam ?? ""`, because search has no `apiBase` const; `sendReaction` and `blockVideoSource` take `string`.
- Dislike toggles: `undo_dislike` when `cardReaction(row) === "disliked"`. It sets `row.reaction` and re-renders in place instead of calling `removeRows`.
- Both re-renders are guarded with `card.isConnected` before `card.outerHTML = ...`.

**What depends on it:**
- `sendReaction` and `cardReaction` (reactions.ts), `blockVideoSource` (blocks.ts), `getProfileKey` (profile.ts);
- the `.card-action-status` span and `data-card-action` values in the video-card markup.

**Risk:** medium, the highest of the page changes.
1. **Lost re-render:** `outerHTML` on a detached node throws, and that error would land in `catch` and `say` on a dead node. The `isConnected` guard prevents this, and it must be there for both Like and Dislike.
2. **Mutated row:** the reaction is set on the same row object the lookup returns. Row identity comes from `state.rows`, and the re-render reads `cardReaction(row)`. With a key it reads `row.reaction`, and without one the local likes that `sendReaction` already updated, so the row must be mutated before the re-render.
3. **Keyed like where the server stored but answered non-OK:** for example 502 from an unpublished Client, which stores the like and then fails to publish (test_frontend_reactions.py lines 404-409). `sendReaction` throws, so `row.reaction` is not updated even though the profile holds the like. The card shows the error, and the mark is stale until the next search. This is the same as home and pre-existing.
4. **Keyboard focus:** the `outerHTML` replacement drops focus from the button the user just pressed. This is the same on home's Like, but it now also applies to Dislike on search.
5. **Behaviour drift from home:** any later fix to one handler must be made in both. This is an accepted tradeoff.
6. **No `ProfileKeyRejectedError` branch,** by decision.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new removeRows(match)">
**What changes:**
- `state.rows` is filtered.
- Iterate `Array.from(results.children)`, which gives elements only and skips the whitespace text nodes left by the template literal. For each `.video-card` whose `dataset.videoKey` is in the set of `resolveVideoKey` values of the removed rows, call `.remove()`.
- Then call `fillViewport()`.
- `state.page`, `state.loadedRows`, `state.total`, `state.hasMore` and the status text are not touched.

**What depends on it:** the block path of `runCardAction`, `fillViewport` → `loadNextPage`, and the guard on `state.loading || !state.hasMore`.

**Risk:** low to medium.
1. **Matching:** match fields with `String(candidate.instance_domain ?? "") === block.instance_domain && String(candidate.channel_id ?? "") === block.channel_id`, or `String(candidate.account_url ?? "") === block.account_url`, exactly as home does. Search rows carry `channel_id` and `account_url` (engine/server/data/search.py lines 57 and 63). The Client's block record stores the same `(instance_domain, channel_id)` and `account_url` (client/README.md line 17), so the values line up.
2. **Block removes every visible card:** if `hasMore` is false, the grid is left empty while the status still reads "Showing N of M matched videos.", with no "No results" message. This follows from the deliberate simplification in req 8.
3. **Block completes after a reset:** it filters the new result set by the block's fields, which the plan's gotcha section judges correct.
4. **Rows without a key:** they have no card and no `data-video-key`. Filtering them out of `state.rows` is harmless.
5. **Escaping:** `dataset.videoKey` returns the unescaped attribute value, and `resolveVideoKey` returns the raw `host::id`, so the comparison is consistent. This is why the plan avoids building a CSS selector.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="showIdle() (lines 219-228)">
**What changes:** add `state.rows = []` next to `state.loadedRows = 0`.

**What depends on it:** the idle transition from submitting an empty query or popstate to a URL without `q`. The grid is cleared by `results.innerHTML = ""`.

**Risk:**
- Low.
- If omitted, the result is cosmetic only: no cards remain to click.
- If an in-flight block finishes after idle, `removeRows` filters an empty array, finds no cards, and calls `fillViewport` → `loadNextPage`, which returns early because `hasMore` is false.
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="renderVideoCard() action markup, Dislike button (line 356)">
**What changes:** `aria-pressed="${reaction === "disliked"}"` is inserted after `data-card-action="dislike"`, in the same position and style as Like's on line 355. Nothing else changes.

**What depends on it:**
- `renderVideoCard` has exactly two callers, found by grep: home's `renderFeedCard` (videos/index.ts line 387) and search's `renderRows` (search/index.ts line 208). The video page and likes page do not call it.
- The action markup only renders when `options.actions && videoKey`, so `tests/active/test_frontend_reactions.py`, which renders without `actions` and tests the `class="stat likes active"` and `class="stat dislikes active"` regexes, is unaffected.
- `tests/active/test_frontend_videos_page.py` reads only the `data-video-key` values and is unaffected.
- The CSS rule `.card-action[aria-pressed="true"] svg { fill: currentColor; }` (videos.css line 664) is generic, so a pressed Dislike fills its icon automatically.

**Risk:** low.
- Home's Dislike now announces as a toggle button, "not pressed", although on home it is a one-shot remove with no undo. The issue explicitly allows this. It is a small semantic mismatch for screen-reader users on home.
- Home never renders a disliked card: feeds filter dislikes server-side (client/backend/server.py line 469), and home's dislike removes the card. So `aria-pressed="true"` cannot appear on home.
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="VideoCardOptions.actions doc comment (line 36) and module docstring (lines 1-12)">
**What changes:** probably nothing. "Render like, dislike and block buttons; the page handles their `data-card-action` clicks." stays true with two pages. Optionally, note that the Like and Dislike buttons carry `aria-pressed` from `reaction`.

**What depends on it:** documentation only.

**Risk:** none.
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="home's click listener (135-141), renderFeedCard (386-394), runCardAction (400-447), removeRows (452-457)">
**What changes:** nothing, per req 10. This is the reference implementation that search mirrors.

**What depends on it:** home's acceptance criterion ("dislike and block still remove cards, home has no undo-dislike").

**Risks:**
- Regression risk comes only from the shared markup change. Home's handler reads `button.dataset.cardAction` and never reads `aria-pressed`, so the added attribute cannot change its behaviour.
- The implementer must not "tidy" home while copying from it, for example by adding an `isConnected` guard or changing the message text. Req 10 forbids that.
</impact>
<impact path="client/frontend/src/data/reactions.ts" element="sendReaction(), cardReaction(), AFTER table">
**What changes:** nothing. It is used by search for the first time for actions; search previously used only `cardReaction` and `importLocalLikes`.

**What depends on it:**
- Search's Like and Dislike rely on `sendReaction` recording keyless like and undo-like in `localLikes:v1` before resolving (lines 95-98), so a re-render through `cardReaction` reads the new state.
- `cardReaction` returns `row.reaction` only when keyed (line 53), so mutating `row.reaction` affects keyed rendering only.
- `undo_dislike` is a supported `ReactionAction` (line 16), and the server accepts it with a key (client/README.md line 19).

**Risk:**
- None for this module.
- Search depends on the AFTER semantics ("a like and a dislike replace each other") matching what the server does. `test_frontend_reactions.py` covers that.
</impact>
<impact path="client/frontend/src/data/blocks.ts" element="blockVideoSource() and request()">
**What changes:** nothing.

**What depends on it:** search's block path.

**Behaviour to note:**
- `request` throws a plain `Error(payload.error ?? "Block request failed (<status>)")` on any non-OK status, 401 included. It has no `ProfileKeyRejectedError` (lines 64-66).
- A rejected key therefore shows as a status-line message on the card, which matches req 7.
- The returned `Block` carries `kind`, `instance_domain`, `channel_id`, `account_url` and `label` (lines 13-20), which search's `removeRows` predicate and its "Blocked <label>" message use.

**Risk:**
- None to the module.
- If the server ever returned `block` without `kind`, both pages would fall into the account branch. That would be a pre-existing issue shared with home.
</impact>
<impact path="client/frontend/src/data/user-actions.ts" element="sendUserAction()">
**What changes:** nothing.

**What depends on it:** `sendReaction`, and through it every search Like and Dislike.

**Behaviour to note:**
- It throws `Error(body.error ?? "Failed to send action")` for any non-OK status. That message is what search writes into the card's status line.
- `apiBase` goes through `resolveClientApiBase`, which honours `?api=` only in DEV (api-base.ts lines 18-33). So `apiParam ?? ""` is safe in production.

**Risk:** none.
</impact>
<impact path="client/frontend/src/data/profile.ts" element="getProfileKey()">
**What changes:** nothing. It is newly imported by search for the no-key guard (req 6).

**What depends on it:** the guard in search's `runCardAction`, and `cardReaction`.

**Risk:** none.
</impact>
<impact path="client/frontend/src/data/search.ts" element="fetchSearchResults(): keyed no-store branch vs keyless sessionStorage cache">
**What changes:** nothing.

**What depends on it:** the "rerun the same search" acceptance checks.
- With a key, the fetch is `cache: "no-store"` and goes through the Client's per-profile filter (lines 68-75). A rerun therefore reflects a new dislike, undo-dislike or block at once, and the acceptance criteria are reachable.
- Without a key, results are cached in `sessionStorage` for 30 s (DEFAULT_CACHE_TTL_MS). Keyless actions are limited to Like, whose mark comes from `localLikes:v1` and not from the row, so the cache does not show a stale mark.
- `readCache` returns a freshly `JSON.parse`d object (cache.ts lines 44-57), so mutating `row.reaction` on the page never writes back into the cache.

**Risk:** none for this build. Any test of "rerun after action" must use a key to avoid the keyless 30 s cache.
</impact>
<impact path="client/frontend/src/types/videos.ts" element="VideoRow: channel_id (line 10), account_url (line 15), reaction (lines 51-52)">
**What changes:** nothing.

**What depends on it:**
- Search's `removeRows` predicate and the `row.reaction` assignment. `reaction` is typed `"liked" | "disliked" | null`, so assigning `null`, `"liked"` or `"disliked"` type-checks.

**Risk:** none.
</impact>
<impact path="client/frontend/src/videos.css" element=".card-actions / .card-action / .card-action[aria-pressed=&quot;true&quot;] svg / .card-action-status (lines 625-676)">
**What changes:** nothing. search/index.ts already imports `../../videos.css` (line 9).

**What depends on it:**
- The visual pressed state of the Dislike button: the existing generic `[aria-pressed="true"] svg` rule fills it.
- The disliked mark on the stats line through `.stat.active` (lines 616-623).

**Risk:**
- Low.
- No `.video-card.disliked` or `.video-card.liked` rule exists, so the extra root class has no styling effect. That is the same as today.
- Visual check: the cards on the search grid are now taller.
</impact>
<impact path="client/frontend/src/search.css" element="search-page-only styles">
**What changes:** nothing. Its header comment says the grid and cards reuse videos.css. Grep found no card or `card-action` rules here, so nothing overrides the action row.

**What depends on it:** search layout.

**Risk:** none.
</impact>
<impact path="client/frontend/search.html" element="#search-results section (line 58), #search-status (line 55)">
**What changes:** nothing.

**What depends on it:**
- The delegated listener attaches to `#search-results`.
- `removeRows` relies on cards being direct children of it, which is true for both `innerHTML` and `insertAdjacentHTML("beforeend")`.
- Each card's `.card-action-status` has its own `role="status"`, separate from the page's `#search-status` (`aria-live="polite"`), so the per-card messages do not overwrite the page status.

**Risk:** none.
</impact>
<impact path="client/frontend/src/components/key-rejected.ts" element="keyRejectedNotice(onForget)">
**What changes:** nothing.

**What depends on it:** the search retry path `() => void loadPage(1, true)`, which is the reset path that must clear `state.rows`.

**Risk:** none. Its button sits inside `#search-results`, and its clicks are ignored by the new listener because there is no `[data-card-action]`.
</impact>
<impact path="client/backend/server.py" element="_filter_payload() (lines 1096-1122) and the dropped/FEED_ROUTES rule (line 469)">
**What changes:** nothing (out of scope).

**What depends on it:**
- `dropped = disliked if path in FEED_ROUTES else set()` means search is never filtered by dislikes (D6). That is why a search card can and must stay after Dislike, while home's cards vanish.
- Rows are marked `reaction` by `(video_id, instance_domain)`.
- Blocked rows are filtered per Engine page. Page numbers therefore do not shift after a block, which is the basis for req 8's "paging stays correct".

**Risk:** none from this build. If D6 were ever reversed, search's toggle semantics would need revisiting.
</impact>
<impact path="engine/server/data/search.py" element="search row SELECT (v.channel_id line 57, v.account_url line 63)">
**What changes:** nothing.

**What depends on it:** search's block-removal predicate needs `channel_id`, `instance_domain` and `account_url` on every row. They are present.

**Risk:** none.
</impact>
<impact path="client/frontend/vite.config.ts" element="build.rollupOptions.input.search">
**What changes:** nothing. `search.html` is already an entry.

**What depends on it:** `npm run build` producing `dist/search.html` and `dist/assets/search-*.js`.

**Risk:** none.
</impact>
<impact path="client/frontend/dist/" element="the built bundle: search.html, assets/search-*.js, assets/video-card-*.js, assets/index-*.js and any chunk whose hash changes">
**What changes:** `npm run build` (req 11) regenerates it. `dist/` is tracked (no .gitignore entry, and the files exist in the tree).

What the rebuild produces:
- `video-card-*.js` gets a new hash because of the Dislike attribute.
- `search-*.js` gets a new hash.
- The entry that imports video-card may get a new hash too: `index-*.js`, home's built entry, references `./video-card-<hash>.js`.
- Old hashed files are deleted, so the diff shows renames.

**What depends on it:**
- The served site.
- scripts/sync.sh references the frontend dist; it deploys whatever is there.

**Risks:**
- Low, provided the build is run once after both source edits and the whole `dist/` diff is committed.
- Forgetting the rebuild leaves production without the change, which is the acceptance criterion.
- Building from a tree with a local `dev-pages/about.html` would bake that override into `dist/`, because vite.config.ts lines 91-93 select it if it exists. Check that `client/frontend/dev-pages/about.html` is absent before building.
</impact>
<impact path="tests/active/test_frontend_reactions.py" element="cards test (lines 396-421) and its esbuild bundle of video-card.ts">
**What changes:** nothing needed. It renders `renderVideoCard(row, { reaction })` without `actions`, so the action markup, including the new attribute, is never emitted. Its regexes target the `.stat` classes.

**What depends on it:** the reaction-mark contract that search's re-render relies on.

**Risk:** none. It remains the baseline guard for `cardReaction`.
</impact>
<impact path="tests/active/test_frontend_videos_page.py" element="HOME_RUNNER bundling pages/videos/index.ts">
**What changes:** nothing needed. It bundles home, which imports video-card, and asserts only on `data-video-key` values in `#video-cards` innerHTML.

**What depends on it:** the home regression check (req 10) at module level.

**Risk:** none. Its fake element has `closest: () => null` and no `outerHTML`, so it cannot exercise card actions. It is not a guard for them.
</impact>
<impact path="tests/active/test_frontend_blocks.py" element="blockVideoSource runner step (line 46)">
**What changes:** nothing.

**What depends on it:** the `Block` shape search consumes.

**Risk:** none.
</impact>
<impact path="tests/active/ (new search-page card-action test, location to be decided at Step 4/5)">
**What changes:** no existing test bundles `pages/search/index.ts`; grep found no `pages/search` in tests/. The acceptance criteria are therefore unguarded. Likely candidates:
- Bundle search/index.ts with esbuild, as test_frontend_videos_page.py does with home, using `--loader:.css=empty` and `--define:import.meta.env.DEV=false`. Run it against a stub fetch and fake DOM elements, and assert:
  - the action buttons are present on appended pages;
  - Dislike sends `dislike` and then `undo_dislike`, and the card keeps `aria-pressed="true"` and then `"false"`;
  - no request is made without a key;
  - block removes matching cards.
- Or an integration run against `engine_client` or `unpublished_client` for "rerun shows reaction: disliked".

**Risk to note:** the existing fake-DOM harness lacks `closest`, `outerHTML`, `isConnected`, `children`, `remove` and `dataset` population from HTML. A search-page test needs a richer fake, or should assert at the data and markup level. Per the baseline note, tests go through `tests/tmp`, then `tests/active`.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="frontend boundary grep">
**What changes:** nothing. The new code uses only Client routes through the existing data modules and introduces no Engine base, host or port, or internal route.

**Risk:** none.
</impact>
<impact path="client/frontend/README.md" element="'What it does' list, line 16 (reaction marks) and missing card-controls bullet">
**What changes:** documentation; see the docs checklist. The README currently says cards show a reaction mark on feed, search and similar cards, but does not mention the card action buttons on either feed or search.

**What depends on it:** readers and the docs gate.

**Risk:** none at runtime.
</impact>
<impact path="docs/project/roadmap.md" element="F13-M2 line (line 54) and Delivered section">
**What changes:** documentation. F13-M2's feed-grid and search-grid halves are both delivered after this build; the channels page remains.

**Risk:** none at runtime.
</impact>
<impact path="docs/project/issues/40-search-card-actions.md" element="Status line and file location">
**What changes:** on delivery, per docs/project/issue-tracker.md lines 20-21:
- set `Status: enhancement, complete`;
- append a comment naming the delivering plan;
- `git mv` the file to `docs/project/issues/archive/`.

The brief's "Errors" bullet says a rejected key is "handled as the search page already handles `ProfileKeyRejectedError`". The plan's req 7 records the operator decision otherwise, so the closing comment should record that decision.

**Risk:** none at runtime. There is a traceability risk if the brief and the delivered behaviour silently disagree.
</impact>
<impact path="client/README.md" element="read gateway filtering (line 25), user-action and block routes (lines 17, 19)">
**What changes:** nothing. Server behaviour is unchanged, and the text already states that search is filtered by blocks and not by dislikes, and that rows are marked `reaction`.

**Risk:** none. Listed because it is the documented basis for search's keep-the-card dislike.
</impact>
<impact path="DEPLOYMENT.md" element="likes/dislikes paragraph (line 360)">
**What changes:** nothing. It states "Search is not filtered by dislikes" and that the frontend shows `reaction` on the card, which remains true.

**Risk:** none.
</impact>
<impact path="CONTEXT.md" element="Block glossary entry (line 11)">
**What changes:** nothing. No new domain term is introduced, and Block, dislike and NSFW stay as defined.

**Risk:** none.
</impact>
</impacts>

### docs_checklist

<doc path="client/frontend/README.md">
Add a "What it does" bullet next to line 16. It should say that feed and search cards carry Like, Dislike, Block channel and Block account buttons, and cover:
- Like works without a key, while Dislike and the Block buttons need a profile key and otherwise show a "needs a profile" prompt on the card.
- On the home feed, a dislike or block removes the affected cards, with no undo.
- On search, Dislike toggles (`dislike` / `undo_dislike`) and the card stays marked, because search is not filtered by dislikes. A block removes every loaded card of that channel or account.
- After a block, search's "Showing N of M" keeps counting fetched rows.
- A failed action, including a rejected key, shows on that card's status line.
- Both the Like and Dislike buttons carry `aria-pressed`.
</doc>
<doc path="docs/project/roadmap.md">
Update F13-M2 (line 54). Its feed-grid and search-grid halves are delivered: the feed grid already, the search grid by `docs/project/plans/20-40-search-card-actions.md` (issue `40`). Only the channels page remains. Add or extend a Delivered entry pointing at the plan, which will be in archive once moved.
</doc>
<doc path="docs/project/issues/40-search-card-actions.md">
On delivery:
- set `Status: enhancement, complete`;
- append a comment naming the plan that delivered it, and record the operator decision that a rejected key during a card action shows as a card status message and not the `keyRejectedNotice` (this diverges from the brief's "Errors" bullet);
- move the file to `docs/project/issues/archive/`.
</doc>

### highest_risk

client/frontend/src/pages/search/index.ts runCardAction(): new and deliberately divergent from home. If the `card.isConnected` guard is missing, `outerHTML` throws on a card detached by a reset mid-action. `row.reaction` must be set on the looked-up row before the re-render, or `cardReaction` reads the old state with a key. `vite build` does no type check, so a missing import (`sendReaction`, `blockVideoSource`, `getProfileKey`, `resolveVideoId`) surfaces only on the first click.
client/frontend/src/pages/search/index.ts state.rows lifecycle (loadPage reset block, showIdle, renderRows, removeRows): every reset path must empty it, and appends must happen after the `requestSeq` check, or a click resolves a stale row from a previous query with the same key and toggles from the wrong reaction. Clearing belongs in loadPage's `if (reset)` block, beside `loadedRows`, so a failed reset leaves no orphan rows.
client/frontend/src/components/video-card.ts renderVideoCard() Dislike button: the only shared-code edit. It reaches home's cards too, where it adds an `aria-pressed="false"` toggle semantic to a one-shot, no-undo button. It also drives the pressed styling through the generic `.card-action[aria-pressed="true"] svg` rule. Any markup change beyond the single attribute would also change home, which req 10 forbids.

## 2026-10-01 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

The plan holds against the inventory and the tree. I opened the files the plan relies on: `pages/search/index.ts`, home's handler in `pages/videos/index.ts` (lines 135-141 and 386-457), `video-card.ts` (lines 317-361), `reactions.ts`, `blocks.ts`, `vite.config.ts`, `package.json`, the test harnesses, `server.py`'s FEED_ROUTES/FILTERED_ROUTES and the issue brief. Every premise the plan states is in the code. `sendReaction` and `blockVideoSource` take a `string` apiBase that passes through `resolveClientApiBase`. `cardReaction` reads `row.reaction` only when a key is held (line 53). Keyless like and undo-like are written to the local likes before `sendReaction` resolves (lines 95-98). `/api/v1/search/videos` is in FILTERED_ROUTES but not FEED_ROUTES, so it is filtered by blocks and never by dislikes. The Dislike button at video-card.ts line 356 has no `aria-pressed`, and Like's at line 355 shows the form to copy. `renderVideoCard` has exactly two callers. Search's `loadPage` reset block (lines 151-154) and `showIdle` (lines 219-228) are where `rows` must be cleared. I found one interaction the inventory does not carry: a block that lands while the next page is being fetched can bring that channel's cards back. It is small and the same on home today. One inventory line is imprecise: home's listener looks rows up in `state.sample`, not `state.rows`. Neither changes the plan.
<question id="1">
Yes. Every card on every loaded page gets the controls, because `renderRows` handles both the first page and appended pages and the listener is delegated on `#search-results`. The lookup by `resolveVideoKey` against `state.rows` works because `dataset.videoKey` and `resolveVideoKey` both give the raw `host::id`. Like and Dislike toggle correctly because the row is updated before the card is re-rendered, and `cardReaction` reads the right source with or without a key. Block removes matching cards by field and calls `fillViewport`. The no-key guard, the error messages and the `finally` re-enable are copied exactly from home. With a key, the search fetch uses `no-store` (data/search.ts line 71), so the "rerun shows the reaction" acceptance check can be met.
</question>
<question id="2">
- The search page now writes to the profile: likes, dislikes and blocks. Before, it only showed reaction marks.
- Search cards are one button row taller, so `fillViewport` fetches fewer pages to fill the screen.
- The card-action logic now exists twice, and any later fix must be made on both pages.
- After a block the status line can overstate what is shown, as the requirements accept.
- Re-rendering a card with `outerHTML` drops keyboard focus after Like or Dislike.
- A page fetch that is already running when a block completes can append cards from the blocked source (see new impacts).
- On home, the Dislike button now announces as a toggle button that is not pressed.
</question>
<question id="3">
- `state.rows` must be cleared in the `loadPage` reset block and in `showIdle`.
- Rows must be added to `state.rows` only after the `seq` check, inside `renderRows`.
- Both re-renders need the `isConnected` guard.
- Home's code must not be touched while copying from it.
- After both source edits, run `npm run build` once, check that `dev-pages/about.html` is absent, and commit the whole `dist/` diff.
- Because `vite build` does not type-check, run `npx tsc --noEmit -p client/frontend` (tsconfig.json exists) or an esbuild bundle to catch a missing named import.

Nothing in the data modules, the backend or the CSS needs to change.
</question>
<question id="4">
- Search cards gain Like, Dislike, Block channel and Block account.
- On search, Dislike toggles and the card stays, while on home it removes the card.
- A block removes the loaded cards of that channel or account from the search grid.
- On home, the only change is `aria-pressed="false"` on the Dislike button. Home never renders a disliked card, so `"true"` cannot appear there, and home's handler never reads the attribute.
- The search fetch, its paging and its `ProfileKeyRejectedError` handling are otherwise unchanged.
</question>


New impacts:
client/frontend/src/pages/search/index.ts — a block racing an in-flight page append: `loadPage(page+1, false)` may already be in flight (`state.loading` true) when a block completes. `removeRows` → `fillViewport` → `loadNextPage` then returns early. If that request was filtered before the block was stored, its response can append cards from the source just blocked, and they stay until the next reset or until the user blocks again. Home has the same pre-existing window in `loadMoreVideos`. Risk is low and the result is cosmetic; the server filters every later page.

Inventory entries that did not hold up:
The entry for the new delegated click listener on `results` says it mirrors videos/index.ts lines 135-141 "almost word for word" with `state.rows.find`. Home's line 139 actually looks up in `state.sample.find`, because home's `rows` and `sample` differ. Search has no sample, so `state.rows` is the right source for search; only the "word for word" description is off. Every other entry matched its file, including the vite.config.ts lines 91-93 dev-pages override, package.json line 9 `vite build`, video-card.ts lines 351-356, reactions.ts lines 53 and 95-98, blocks.ts lines 13-20 and 64-66, and server.py line 469.

Conflicts: none

Recommendations: 1. Accept the block-versus-append race and record it as a known limitation in the search module docstring, which the inventory already adds sentences to. Cost: one clause of documentation and no code. The alternative is to keep the blocks made this session in `state` and filter by them in `renderRows`. That costs a second piece of state, a predicate list that must be cleared on reset, and behaviour that differs further from home, all for a short-lived cosmetic glitch, so I do not recommend it.
2. Make `npx tsc --noEmit -p client/frontend` part of verifying this build, since `vite build` does not type-check. Cost: one command. If the tree already has type errors in other files, they must be told apart from new ones.
3. Write the search card-action test at the data and markup level, or extend the richer fake DOM from test_frontend_video_page_similars.py, rather than the bare fake in test_frontend_videos_page.py, which returns `closest: () => null`. Cost: a larger test fixture.
4. When the issue is closed, its comment should note that req 7 replaces the brief's "Errors" bullet, as the inventory already says. Cost: one line.

## 2026-10-01 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impact path="client/frontend/src/pages/search/index.ts" element="module-level imports (lines 11-20)">
**What changes:** the imports grow.
- `../../components/video-card` (line 11) now also gives `resolveInstanceDomain`, `resolveVideoId` and `resolveVideoKey`, all exported at video-card.ts lines 65, 72 and 80.
- `../../data/reactions` (line 18) adds `sendReaction` to `cardReaction` and `importLocalLikes`.
- `../../data/profile` (line 17) adds `getProfileKey` (profile.ts line 20) to `ProfileKeyRejectedError`.
- There is a new import, `blockVideoSource` from `../../data/blocks`.

**What depends on it:** Vite chunking. `blocks.ts` is already a shared chunk (`dist/assets/blocks-DRgP8l-1.js`). The current built search entry imports safe-url, video-card, cache, reactions and key-rejected but not blocks, so the rebuilt search entry gains one chunk import.

**Risk:** low, with one gap. `npm run build` is `vite build` (package.json line 9) and runs no `tsc`, even though tsconfig.json has `strict: true`. A bad named import or a type error is therefore not caught at build time. Run `npx tsc --noEmit` in client/frontend, or bundle with esbuild as the tests do. When a list grows, follow the file's style of braces split over lines, as at lines 12-16.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="module docstring (lines 1-7)">
**What changes:** it currently describes only query and sort in the URL, and paging. It should gain a sentence or two:
- cards carry Like, Dislike, Block channel and Block account;
- Dislike toggles and the card stays, unlike home;
- a block removes the loaded cards of that channel or account, while "Showing N of M" keeps counting fetched rows.

**What depends on it:** nothing at runtime.

**Risk:** none at runtime. If it is skipped, the reason search's handler differs from home's is recorded nowhere in the code.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="state object (lines 49-60): new `rows` field">
**What changes:** add `rows: [] as VideoRow[]`, declared as home does (videos/index.ts line 85), with a `/** ... */` comment like the ones on `hasMore` and `requestSeq`. `VideoRow` is already imported as a type at line 20.

**What depends on it:**
- the new click listener (`state.rows.find`);
- `renderRows`, which appends to it;
- `removeRows`, which reassigns it;
- `runCardAction`, through the row reference it holds.

**Risk:** moderate.
- If any reset path leaves it uncleared, a click on a fresh card can resolve to a stale row with the same key and a stale `reaction`. That card would then toggle the wrong way.
- Its order must match DOM order, so append only after the `seq` check at line 182.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="loadPage() reset block (lines 151-154) and every path into it: startSearch (138), popstate (103), initial load (108), keyRejectedNotice retry (174)">
**What changes:** add `state.rows = []` in the `if (reset)` block, beside `results.innerHTML = ""` and `state.loadedRows = 0`. That one line covers new search, sort change (through `startSearch`), popstate, initial load and the "Forget key" retry.

**Alternative:** clearing in `renderRows`' reset branch would leave stale rows when a reset fetch fails (SearchUnavailable, ProfileKeyRejected or a network error). They would be unreachable, because the grid is empty, so the effect is cosmetic. The reset block is still the better place.

**What depends on it:** the row lookup (req 2) and the reset-during-action gotcha.

**Risk:** low if it goes in the reset block.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="loadPage() catch branch, ProfileKeyRejectedError (lines 172-174), and the appended-page failure path">
**What changes:** nothing (req 7).

**Interaction:** when an appended page (`reset=false`) fails with a rejected key, `results.replaceChildren(keyRejectedNotice(...))` wipes the grid but `state.rows` keeps the old rows. No `.video-card` is left, so no click resolves and `removeRows` finds no DOM node to remove. The retry `loadPage(1, true)` clears them.

**What depends on it:** the operator decision in req 7. A 401 from `/api/user-action` (user-actions.ts lines 33-37) or `/api/profile/blocks` (blocks.ts lines 64-66) arrives as a plain `Error`, so it shows in the card's status line and never reaches this branch.

**Risk:** no regression. The plan diverges from the issue brief's "Errors" bullet (issue 40, line 40: "A rejected key is handled as the search page already handles `ProfileKeyRejectedError`"). The reviewer must accept that the plan's req 7 governs.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="renderRows() (lines 204-214) and a new search card renderer (counterpart of home's renderFeedCard, videos/index.ts 386-394)">
**What changes:**
- A new function, for example `renderSearchCard(row)`, returns `renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true })` and carries a one-line `/** ... */` docstring.
- `renderRows` maps through it on both the reset and the append path, and pushes the page's rows onto `state.rows`.
- `runCardAction` reuses it for in-place re-renders, so the first render and a re-render cannot drift apart.

**What depends on it:**
- Every keyed card gets `.card-actions`. Rows with no `resolveVideoKey` get none (video-card.ts line 352, `options.actions && videoKey`).
- Cards stay direct children of `#search-results` on both the `innerHTML` and `insertAdjacentHTML("beforeend")` paths, which `removeRows` relies on.

**Risk:** low.
- Cards grow taller by one row of buttons, so the sentinel moves and `fillViewport` fetches fewer pages for the same viewport. The effect is visual only.
- `renderRows` is called after the `seq` check (line 182), so a stale response never pushes rows.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new delegated click listener on `results` (#search-results)">
**What changes:** add a top-level `results.addEventListener("click", ...)` next to the form and sort listeners (lines 70-83), mirroring videos/index.ts lines 135-141. The one difference is the lookup: home searches `state.sample`, search uses `state.rows.find(...resolveVideoKey...)`.

**What depends on it:**
- Appended pages need no extra wiring (req 8).
- The `keyRejectedNotice` button also sits inside `#search-results`. It has no `[data-card-action]`, so its clicks are ignored.
- The `<a class="video-link">` and the channel link are outside `.card-actions` (video-card.ts line 351 comment), so navigation is unaffected.

**Risk:** low.
- `event.target` can be the SVG `<path>` inside a button; `closest` handles that, as it does on home.
- A disabled button dispatches no click, so a double click while an action runs does nothing.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new runCardAction(button, card, row)">
**What changes:** new code modelled on home's `runCardAction` (videos/index.ts lines 400-447).

**Same as home:**
- the `say` helper writing into `.card-action-status`;
- the no-key guard text;
- disable the button and clear the status line before the request, and re-enable in `finally`;
- Like toggles on `cardReaction(row) === "liked"`;
- Block runs `blockVideoSource`, then `sendReaction("dislike")` with `.then(() => null, err => message)`, then the "Blocked … but the dislike failed" early return;
- the error falls back to "Action failed".

**Different from home:**
- `apiBase` is `apiParam ?? ""`, because search has no `apiBase` const. Home's comes from `resolveApiBase(similarQuery)` (line 79). Both end in `resolveClientApiBase` (api-base.ts), which honours `?api=` only in DEV.
- Dislike toggles to `undo_dislike` when `cardReaction(row) === "disliked"`, sets `row.reaction`, and re-renders instead of removing the card.
- Both re-renders are guarded with `card.isConnected`.

**What depends on it:** `sendReaction` and `cardReaction` (reactions.ts), `blockVideoSource` (blocks.ts), `getProfileKey` (profile.ts), and the `data-card-action` values and the `.card-action-status` span in video-card.ts.

**Risk:** medium, the highest of the page changes.
1. `outerHTML` on a detached card throws. Without the guard on both the Like and the Dislike path, the error is caught and written to a dead node.
2. `row.reaction` must be set before the re-render. Keyless, `cardReaction` reads `localLikes:v1`, which `sendReaction` updates (reactions.ts lines 95-98).
3. If the server stores a reaction but answers non-OK (for example a 502 on publish), the mark stays stale. This already happens on home.
4. The `outerHTML` swap drops keyboard focus. Home's Like does this already, and now search's Dislike does too.
5. Fixes to one handler must be copied to the other, which is the accepted tradeoff.
6. There is no `ProfileKeyRejectedError` branch, by decision.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="new removeRows(match)">
**What changes:**
- Filter `state.rows`.
- Collect the `resolveVideoKey` values of the removed rows.
- Walk `Array.from(results.children)` (elements only) and `.remove()` each `.video-card` whose `dataset.videoKey` is in that set.
- Call `fillViewport()`.
- Leave `state.page`, `loadedRows`, `total`, `hasMore` and the status text alone.

**What depends on it:** the block path, and `fillViewport` → `loadNextPage`, which returns early while `state.loading` is set or `hasMore` is false.

**Risk:** low to medium.
1. **Predicate:** it must match home's exactly, by `instance_domain` + `channel_id`, or by `account_url`. Search rows carry those fields (engine/server/data/search.py lines 56, 57 and 63).
2. **Block lands mid-fetch:** if it lands while the next page is in flight, that page was filtered before the block existed and can bring the channel back. Home has the same race.
3. **Grid emptied:** if a block removes every card and `hasMore` is false, the grid is empty while the status still says "Showing N of M", with no "No results". This is req 8's simplification.
4. **Escaping:** `dataset.videoKey` gives the unescaped value, and `resolveVideoKey` gives the raw `host::id`, so they compare cleanly without a CSS selector.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="showIdle() (lines 219-228)">
**What changes:** add `state.rows = []` beside `state.loadedRows = 0`.

**What depends on it:** the idle transitions, an empty submit (line 74) and popstate to a URL with no `q` (line 100).

**Risk:** low. If it is omitted, the rows are unreachable and the effect is cosmetic. A block that finishes after idle filters an empty array, and `fillViewport` returns early because `hasMore` is false.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="no-key prompt text vs search page chrome (req 6)">
**What changes:** search shows home's exact text, "Disliking/Blocking needs a profile. Create one from the Profile button."

**What depends on it:** `search.html`, whose nav (lines 21-27) has no Profile button. Only index.html and videos.html have `#show-profile-header` and the profile modal.

**Risk:** a UX/copy mismatch, not a regression. On search the prompt points at a button that is not on the page, and the user has to go to Home. Req 6 asks for the exact text, so flag this for the operator rather than silently rewording. Changing it would break the "exact text" parity with home.
</impact>
<impact path="client/frontend/search.html" element="#search-results (line 58), #search-status (line 55), header nav (lines 21-27)">
**What changes:** nothing.

**What depends on it:**
- The listener attaches to `#search-results`.
- `removeRows` relies on the cards being direct children of it.
- Each card's `.card-action-status` has its own `role="status"`, separate from `#search-status` (`aria-live="polite"`).
- The nav has no Profile button (see the prompt entry above).

**Risk:** none from the markup itself.
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="renderVideoCard() action markup, Dislike button (line 356)">
**What changes:** insert `aria-pressed="${reaction === "disliked"}"` after `data-card-action="dislike"`, in the same form as Like's on line 355. Nothing else changes.

**What depends on it:**
- `renderVideoCard` has exactly two callers: home's `renderFeedCard` (videos/index.ts line 387) and search's `renderRows` (line 208). likes/index.ts imports only helpers, and video-page does not import this module.
- `.card-action[aria-pressed="true"] svg` (videos.css line 664) is generic, so a pressed Dislike fills its icon with no CSS change.

**Risk:** low.
- Home's Dislike now announces as a toggle, "not pressed", although on home it is a one-shot remove. The issue (line 43) allows this.
- `aria-pressed="true"` never appears on home, because feeds drop disliked rows (client/backend/server.py line 469) and home's dislike removes the card.
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="VideoCardOptions.actions comment (line 36), module docstring (lines 1-12)">
**What changes:** probably nothing; both stay accurate. Optionally note on `reaction` (line 34) that it also drives `aria-pressed` on the Like and Dislike buttons.

**What depends on it:** documentation only.

**Risk:** none.
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="home click listener (135-141), renderFeedCard (386-394), runCardAction (400-447), removeRows (452-457)">
**What changes:** nothing (req 10). This is the reference implementation search copies.

**What depends on it:** the acceptance criterion "dislike and block still remove cards, home has no undo-dislike".

**Risk:**
- Regression can come only from the shared markup, and home never reads `aria-pressed`.
- The implementer must not "tidy" home while copying from it, for example by adding an `isConnected` guard or `undo_dislike`.
</impact>
<impact path="client/frontend/src/data/reactions.ts" element="sendReaction(), cardReaction(), AFTER table">
**What changes:** nothing. Search calls `sendReaction` for the first time.

**What depends on it:**
- A keyless like or undo-like is written to the local likes before `sendReaction` resolves (lines 95-98).
- `cardReaction` reads `row.reaction` only with a key (line 53), and reads `video_uuid` and `instance_domain` when keyless. Search rows carry `video_uuid` (search.py line 54).
- `undo_dislike` is a valid `ReactionAction` (line 16).

**Risk:** none to this module. Search assumes the AFTER rule "like and dislike replace each other", which `test_frontend_reactions.py` covers on the server side.
</impact>
<impact path="client/frontend/src/data/blocks.ts" element="blockVideoSource() and request()">
**What changes:** nothing.

**What depends on it:** search's block path.
- Any non-OK answer, 401 included, throws a plain `Error` (lines 64-66), which fits req 7.
- The returned `Block` has `kind`, `instance_domain`, `channel_id`, `account_url` and `label` (lines 13-20).

**Risk:** none. A server reply without `kind` would fall into the account branch on both pages, which is already the case.
</impact>
<impact path="client/frontend/src/data/user-actions.ts" element="sendUserAction()">
**What changes:** nothing.

**What depends on it:** every search Like and Dislike, through `sendReaction`. It throws `Error(body.error ?? "Failed to send action")`, and that text is what lands in the card's status line.

**Risk:** none.
</impact>
<impact path="client/frontend/src/data/api-base.ts" element="resolveClientApiBase()">
**What changes:** nothing.

**What depends on it:** search passes `apiParam ?? ""`. `VITE_CLIENT_API_BASE` wins, then `?api=` in DEV only, then the origin. In production `?api=` is ignored, so passing `apiParam` is safe.

**Risk:** none.
</impact>
<impact path="client/frontend/src/data/profile.ts" element="getProfileKey()">
**What changes:** nothing; search imports it for the first time, for the no-key guard.

**What depends on it:** the guard in search's `runCardAction`.

**Risk:** none.
</impact>
<impact path="client/frontend/src/data/search.ts" element="fetchSearchResults(): keyed no-store branch vs keyless sessionStorage cache">
**What changes:** nothing.

**What depends on it:** the "rerun the same search" acceptance checks.
- With a key the fetch uses `cache: "no-store"` (line 71), so a rerun reflects a dislike, an undo or a block at once.
- Keyless results are cached for 30 s (line 17). Keyless actions are limited to Like, whose mark comes from `localLikes:v1` and not from the row, so the cache cannot show a stale mark.

**Risk:** none. A rerun test must use a key.
</impact>
<impact path="client/frontend/src/types/videos.ts" element="VideoRow: channel_id (line 10), account_url (line 15), reaction (lines 51-52)">
**What changes:** nothing.

**What depends on it:** search's predicates and the `row.reaction` assignments. `reaction` is typed `"liked" | "disliked" | null`.

**Risk:** none.
</impact>
<impact path="client/frontend/src/videos.css" element=".stat.active (616-623), .card-actions … .card-action-status (625-676), .visually-hidden (678)">
**What changes:** nothing. Search already imports it (search/index.ts line 9).

**What depends on it:** the action row layout, the pressed Dislike icon (line 664) and the disliked stat mark.

**Risk:** low.
- No `.video-card.disliked` rule exists, so the root class has no style effect.
- Search cards become visibly taller; check this visually.
</impact>
<impact path="client/frontend/src/search.css" element="search-page styles">
**What changes:** nothing. A grep for `card` finds only the header comment, which says the cards reuse videos.css, so no rule overrides `.card-actions`.

**Risk:** none.
</impact>
<impact path="client/frontend/src/components/key-rejected.ts" element="keyRejectedNotice(onForget)">
**What changes:** nothing.

**What depends on it:** the retry `loadPage(1, true)`, a reset path that must clear `state.rows`. Its button is inside `#search-results` but carries no `data-card-action`, so the new listener ignores it.

**Risk:** none.
</impact>
<impact path="client/backend/server.py" element="FEED_ROUTES/FILTERED_ROUTES (lines 71-72), dropped rule (line 469), _filter_payload (lines 1096-1122)">
**What changes:** nothing; it is out of scope.

**What depends on it:**
- Search is filtered by blocks but never by dislikes (D6), so a search card can stay after Dislike.
- `reaction` is keyed on `(video_id, instance_domain)`.
- The `total` field is not adjusted after filtering, so pages can come back short. That is existing behaviour, and the reason req 8's count stays honest only about fetched rows.

**Risk:** none from this build. If D6 is ever reversed, search's dislike toggle needs revisiting.
</impact>
<impact path="engine/server/data/search.py" element="VIDEO_ROW_SQL (lines 51-74)">
**What changes:** nothing.

**What depends on it:** search needs `video_uuid` (54), `instance_domain` (56), `channel_id` (57) and `account_url` (63), which the key, the toggle and the block predicate use. All are present.

**Risk:** none.
</impact>
<impact path="client/frontend/vite.config.ts" element="build.rollupOptions.input (lines 84-94)">
**What changes:** nothing. `search.html` is already an entry (line 87).

**What depends on it:** the rebuild. The `about` entry picks `dev-pages/about.html` if that file exists (lines 91-93). Today only `about.template.html` exists, so the build is clean.

**Risk:** none, unless a local `about.html` appears before the build.
</impact>
<impact path="client/frontend/dist/" element="built bundle: search.html, assets/search-0tNFtc30.js, assets/video-card-C4VEive-.js, assets/index-OsZsLoAr.js, assets/video-jelp15kj.js and any importer whose hash shifts">
**What changes:** `npm run build` (req 11) regenerates it. `dist/` is tracked; `.gitignore` has no `dist` entry.
- `video-card-*.js` gets a new hash.
- `search-*.js` gets a new hash and now imports `blocks-*.js`.
- Every chunk that imports video-card gets a new hash: index, likes, video and channels, along with their HTML references. Grep showed index, likes, channels, video and search all referencing hashed sibling chunks.
- Old hashed files disappear.

**What depends on it:** the served site. scripts/sync.sh (lines 16-19) builds and rsyncs this directory. DEPLOYMENT.md line 390 says the committed `dist/` lags the source.

**Risk:**
- Low if the build runs once, after both source edits, and the whole `dist/` diff is committed.
- Skipping the rebuild fails the acceptance criterion.
</impact>
<impact path="tests/active/test_frontend_reactions.py" element="cards step of RUNNER (lines 86-98) and _bundle (106-124)">
**What changes:** nothing needed. It renders `renderVideoCard(row, { reaction })` without `actions`, so the new attribute is never emitted, and its regexes target `stat likes active` and `stat dislikes active`.

**Risk:** none. It remains the guard for `cardReaction`.
</impact>
<impact path="tests/active/test_frontend_videos_page.py" element="HOME_RUNNER and home_bundle (bundles pages/videos/index.ts)">
**What changes:** nothing needed. It asserts only on `data-video-key` values in `#video-cards` (line 89).

**Risk:**
- None to the test.
- It does not guard card actions: its fake element has `closest: () => null` and no `outerHTML`, `isConnected` or `dataset` population (line 51).
</impact>
<impact path="tests/active/test_frontend_video_page_similars.py" element="data-video-key regexes (lines 142, 155)">
**What changes:** nothing. The video page does not import video-card.ts, so the shared markup change cannot reach it.

**Risk:** none.
</impact>
<impact path="tests/active/test_frontend_blocks.py" element="block runner step (line 46)">
**What changes:** nothing.

**What depends on it:** the `Block` shape that search consumes.

**Risk:** none.
</impact>
<impact path="tests/active/ (new search-page card-action test; file to be decided)">
**What changes:** grep finds no `pages/search` or `search/index` anywhere under tests/, so every acceptance criterion here is unguarded. Candidate: bundle `pages/search/index.ts` with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`), as test_frontend_videos_page.py does, against a stub fetch. Assert:
- buttons are present on an appended page;
- Dislike sends `dislike` then `undo_dislike`, with `aria-pressed` reading true then false;
- no request is made without a key;
- a block removes the matching cards;
- a re-render after a reset does not throw.

A rerun-after-action check can run against `engine_client` or `unpublished_client` with a key.

**Risk:** the existing fake DOM lacks `closest`, `outerHTML`, `isConnected`, child elements parsed from HTML, `remove` and `dataset`. A richer fake is needed, or assertions on markup and requests only. Tests go through tests/tmp before tests/active.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="frontend boundary grep">
**What changes:** nothing. The new code reaches only Client routes, through the existing data modules.

**Risk:** none.
</impact>
<impact path="client/frontend/README.md" element="'What it does' list, line 16 (reaction marks); no bullet on card controls">
**What changes:** documentation; see the docs checklist. Line 16 covers the reaction marks but no card action buttons, on either feed or search.

**Risk:** none at runtime.
</impact>
<impact path="docs/project/roadmap.md" element="F13-M2 (line 54) and Delivered section (lines 7-25)">
**What changes:** F13-M2's feed-grid and search-grid halves are delivered; the channels page remains. Add a Delivered entry pointing at the plan.

**Risk:** none at runtime.
</impact>
<impact path="docs/project/issues/40-search-card-actions.md" element="Status line (line 3), Comments, file location">
**What changes:** on delivery, per issue-tracker.md line 21:
- set `Status: enhancement, complete`;
- append a comment naming the plan, and record the req 7 decision, which differs from the brief's Errors bullet at line 40;
- move the file to `docs/project/issues/archive/`.

**Risk:** traceability only.
</impact>
<impact path="docs/project/plans/20-40-search-card-actions.md" element="Impacts / Documentation sections">
**What changes:** this inventory replaces the plan's existing Impacts section (lines 102-492) and docs list (494-507). Additions over that version:
- the no-key prompt pointing at a Profile button that search lacks;
- the full list of chunks re-hashed by the build;
- `api-base.ts`;
- `test_frontend_video_page_similars.py`.

At delivery the plan moves to `plans/archive/`.

**Risk:** none at runtime.
</impact>
<impact path="client/README.md" element="user-action and gateway filtering (lines 19, 24-25)">
**What changes:** nothing. It already states that dislike actions need a key, that search is not filtered by dislikes, and that rows carry `reaction`.

**Risk:** none.
</impact>
<impact path="DEPLOYMENT.md" element="profiles/blocks/likes paragraphs (356-360), dist sync note (386-390)">
**What changes:** nothing. "Search is not filtered by dislikes" and the reaction marking still hold. The sync note is the deploy step for req 11.

**Risk:** none.
</impact>
<impact path="CONTEXT.md" element="glossary (Block, NSFW filter entries)">
**What changes:** nothing; no new domain term.

**Risk:** none.
</impact>


### docs_checklist

<doc path="client/frontend/README.md">
Add a "What it does" bullet after line 16 covering:
- home and search cards carry Like, Dislike, Block channel and Block account;
- Like works without a key, while Dislike and the Block buttons need one and otherwise show the "needs a profile" prompt on the card;
- on home, Dislike or Block removes the affected cards, with no undo;
- on search, Dislike toggles `dislike`/`undo_dislike` and the card stays marked, because search is not filtered by dislikes;
- a Block removes every loaded card of that channel or account, and "Showing N of M" keeps counting fetched rows;
- a failed action, including a rejected key, shows in that card's status line;
- both Like and Dislike carry `aria-pressed`.
</doc>
<doc path="docs/project/roadmap.md">
Update F13-M2 (line 54): the feed and search grids are delivered, and only the channels page remains. Add a Delivered entry naming issue `40` and its plan, at the plan's archive path once moved.
</doc>
<doc path="docs/project/issues/40-search-card-actions.md">
On delivery:
- set `Status: enhancement, complete`;
- append a comment naming the delivering plan;
- record that a rejected key during a card action shows as a card status message, not `keyRejectedNotice`, overriding the brief's Errors bullet (line 40);
- record whether the no-key prompt's "Profile button" wording was kept on search, which has none;
- move the file to `docs/project/issues/archive/`.
</doc>
<doc path="docs/project/plans/20-40-search-card-actions.md">
Replace the Impacts and Documentation sections with this inventory, and move the plan to `docs/project/plans/archive/` on delivery.
</doc>

### highest_risk

client/frontend/src/pages/search/index.ts runCardAction: a new card action handler, kept in step with home's by hand. If the in-place `outerHTML` re-render is not guarded with `isConnected` on both the Like and Dislike paths, it throws on a card detached by a reset. If `row.reaction` is set in the wrong order, the toggle reads the wrong state, and no existing test bundles the search page.
client/frontend/src/pages/search/index.ts state.rows lifecycle (loadPage reset block, showIdle, renderRows): a reset path that misses clearing it lets a click on a fresh card resolve to a stale row with the same key and the old reaction, so the card toggles the wrong way. Rows pushed before the seq check at line 182 would also drift out of DOM order.
client/frontend/dist/: the build changes the hash of video-card, which renames every chunk and HTML page that imports it (index, likes, video, channels, search). A partial commit, or no rebuild, ships production without the change or with broken chunk references.

## 2026-10-01 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: YES.

The plan holds. I opened the files the inventory names and checked its claims against them: `pages/search/index.ts` in full, home's listener, `renderFeedCard`, `runCardAction` and `removeRows` in `pages/videos/index.ts` (lines 135-141 and 386-457), `video-card.ts` (lines 20-99 and 300-393), `reactions.ts`, `blocks.ts`, `user-actions.ts`, `api-base.ts`, `data/search.ts`, `types/videos.ts`, `search.html`, `videos.css` (lines 612-683), `vite.config.ts`, `package.json`, `tsconfig.json`, the server's row filter, `_filter_payload` and `_store_reaction` (`client/backend/server.py` lines 450-475, 795-901 and 1096-1122), the Engine's `VIDEO_ROW_SQL`, the `dist/assets` listing, the home-page test's fake DOM, and the README, roadmap and DEPLOYMENT lines cited. Every line reference and behavioural claim I checked matches the code. The server confirms the plan's central assumption (`_store_reaction`, lines 871-901): a like on a disliked video deletes the dislike and records the like, a dislike removes the like, and `undo_dislike` takes the shared delete path. Search is in FILTERED_ROUTES but not FEED_ROUTES (lines 71-72 and 469), so it is filtered by blocks and marked with `reaction`, but never filtered by dislikes. The cap on dislikes comes back as a 400 with `{"error": "Dislike limit reached (N)"}` (line 816), and the plan's generic status-line path already shows that. I found one behaviour the inventory does not carry. The column `video_uuid` can be NULL (`engine/crawler/schema.sql` line 31, `video_uuid TEXT`). Keyless, `sendReaction` saves the like under the ID from `resolveVideoId`, which uses `video_id` when there is no `video_uuid`. `cardReaction`, however, only checks `video_uuid`. So a search card with no `video_uuid` can be liked but never shows as liked, and never toggles back. Home behaves exactly the same today. It does not change the plan.
<question id="1">
Yes. `renderRows` is the only render path for the first page and for later pages, so passing `actions: true` through one search card renderer puts the buttons on every keyed card. `video-card.ts` line 352 still leaves keyless rows without them. The click listener sits on `#search-results`, which `search.html` line 58 declares, so cards added by later pages need no extra wiring. Lookup by key works because the attribute holds the escaped `host::id` and `dataset.videoKey` reads it back unescaped. Like and Dislike toggle correctly because `row.reaction` is set before the card is redrawn. With a key, `cardReaction` reads `row.reaction` (`reactions.ts` line 53). Without a key it reads `localLikes:v1`, and `sendReaction` has already updated that store (lines 95-98), with the one exception noted in the summary for rows that have no `video_uuid`. A block uses the same fields as home's matching rule, and search rows carry them (`search.py` lines 56, 57 and 63). The no-key guard stops Dislike and Block before any request is sent. The `card.isConnected` check covers the one way this can throw: an action finishing after a reset.
</question>
<question id="2">
- Search cards grow by one row of buttons, so each viewport-fill needs fewer page fetches.
- The search bundle now pulls in the existing `blocks` chunk.
- The rebuild changes the hash of `video-card-*.js` and of every chunk that imports it: `index`, `likes`, `video`, `channels` and `search`. Their HTML references change too. `dist/` is tracked in git, so all of this lands in the diff.
- Search gains a second copy of the card-action handler. Its dislike semantics differ from home's on purpose, and any fix to one copy has to be carried to the other by hand.
- After a block, "Showing N of M" overstates what is on screen until the next reset.
- A keyed dislike or undo-dislike on search makes the Engine recompute the dislike centroids, as it does on home. A user can now reach the dislike cap from search and will see its message on the card.
- A key rejected during a card action shows only as that card's error message, by the operator's decision.
</question>
<question id="3">
In `pages/search/index.ts`, `state.rows` must be cleared in two places: the `if (reset)` block at lines 151-154, and `showIdle` at lines 219-228. Rows must be added only after the sequence check at line 182. Both redraws need the `card.isConnected` guard. The block-match rule must be copied exactly from home's lines 434-440. Home's code is not touched; in particular, home must not gain `isConnected` or `undo_dislike`. Run `npm run build` once, after both source edits, and commit the whole `dist/` diff. `vite build` does not type-check, so a separate `npx tsc --noEmit` in `client/frontend` is the only compile check.
</question>
<question id="4">
- **Search:** cards gain Like, Dislike, Block channel and Block account.
  - Dislike toggles between `dislike` and `undo_dislike`, and the card stays on the page with its mark.
  - A block removes every loaded card of that channel or account.
  - The status count keeps counting fetched rows, not the cards still on screen.
  - Paging, URL state and the handling of `ProfileKeyRejectedError` on search reads do not change.
- **Home:** the only change is `aria-pressed="false"` on the Dislike button. Home never shows a disliked card, so `"true"` cannot appear there, and home's handler never reads the attribute.
</question>


New impacts:
client/frontend/src/data/reactions.ts with engine/crawler/schema.sql line 31: `video_uuid` is a nullable column. Without a key, `sendReaction` saves the like under `resolveVideoId(row)` (`video_uuid`, then `videoUuid`, then `video_id`; video-card.ts lines 72-75). `cardReaction` (reactions.ts lines 54-56) only checks `video_uuid` and `videoUuid`. So on a search row whose `video_uuid` is null, a keyless Like succeeds but the redrawn card shows no like, and the next click sends `like` again rather than `undo_like`. Home does exactly the same today, and the plan copies home. Low risk: no data is wrong and only the mark on the card is affected. Neither this build's requirements nor its out-of-scope rules touch `reactions.ts`, so fixing it belongs to a separate change.

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Accept the null-`video_uuid` Like behaviour in this build, since home already behaves the same way, and record it as a follow-up issue. The fix is a one-line change in `cardReaction`: use `resolveVideoId`, or the same fallback chain. Cost now: nothing. Cost of the follow-up: one line, and a test case in `test_frontend_reactions.py`. Fixing it inside this build would edit `reactions.ts`, which this build leaves alone, and it would change home too.
2. Add `npx tsc --noEmit` in `client/frontend` to the build phase's checks. `vite build` does not type-check. Cost: one command, a few seconds.
3. Ask the operator to rule on the no-key prompt's wording on search: "Create one from the Profile button." points at a button that `search.html` does not have. Keeping it costs nothing and keeps exact parity with home, which req 6 asks for. Rewording it on search alone would break that parity, and req 6 would need to change.
4. Add the planned search-page card-action test under `tests/tmp`, then move it to `tests/active`. It needs a fake DOM richer than the home test's (`closest`, `outerHTML`, `isConnected`, `dataset`, child elements, `remove`). Cost: roughly one new test file of home-test size. It is the only guard for search's acceptance criteria.

## 2026-10-01 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

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

### docs_checklist

<doc path="client/frontend/README.md">
Add a "What it does" bullet after line 16. Home and search cards carry Like, Dislike, Block channel and Block account. Like works without a key; Dislike and Block need a key and otherwise show the "needs a profile" prompt on the card. On home, Dislike or Block removes the affected cards, with no undo. On search, Dislike toggles `dislike`/`undo_dislike` and the card stays marked, because search is not filtered by dislikes. A Block removes every loaded card of that channel or account, while "Showing N of M" keeps counting fetched rows. A failed action, a rejected key included, shows in that card's status line. Like and Dislike both carry `aria-pressed`.
</doc>
<doc path="docs/project/roadmap.md">
Update F13-M2 (line 54): the feed and search grids are delivered, and only the channels page remains. Add a Delivered entry naming issue `40` and its plan, at the plan's archive path once moved. Also note that the feed-grid half had no Delivered entry before this change.
</doc>
<doc path="docs/project/issues/40-search-card-actions.md">
On delivery, set `Status: enhancement, complete` and append a comment naming the delivering plan. In that comment, record that a rejected key during a card action shows as the card's status message, not `keyRejectedNotice`, which overrides the brief's Errors bullet at line 40. Also record whether the "Profile button" wording of the no-key prompt was kept on search, which has no such button. Then move the file to `docs/project/issues/archive/`.
</doc>
<doc path="docs/project/plans/20-40-search-card-actions.md">
The workflow re-renders the Impacts and Documentation sections from this inventory. On delivery, move the plan to `docs/project/plans/archive/`.
</doc>

### highest_risk

client/frontend/src/pages/search/index.ts runCardAction: a hand-copied handler whose dislike semantics differ from home's on purpose. If the `card.isConnected` guard is missing on either the Like or the Dislike re-render, an action that finishes after a reset throws. If `row.reaction` is set after the re-render, the toggle reads the wrong state. No existing test loads the search page.
client/frontend/src/pages/search/index.ts state.rows lifecycle (loadPage reset block at lines 151-154, showIdle, renderRows after the seq check at line 182): if a reset path does not clear it, or a stale response pushes rows onto it, a fresh card's key resolves to an old row object with a stale `reaction`, and the card sends the wrong toggle action.
client/frontend/dist/: search's new import of blocks.ts changes Rollup's chunking. `blocks-DRgP8l-1.js` is a merged chunk that also holds data/videos.ts, so the build will likely split it and re-hash index, video, likes and search, along with their HTML. A partial commit of the added and deleted hashed files ships pages that reference chunks that no longer exist, and `sync.sh` rsyncs with `--delete`.

## 2026-10-01 - Step 4 - Reassess the implementation plan (pass 3)

Pass 3. New impacts: YES.

I checked the inventory against the files it names: search/index.ts, videos/index.ts (home), video-card.ts, reactions.ts, blocks.ts, user-actions.ts, api-base.ts, profile.ts, search.html, server.py `_store_reaction`, issue 40, the dist asset list, and test_frontend_videos_page.py. Every line reference and every behavioural claim I checked matched. The plan holds. It has one gap the inventory does not carry: two different buttons on the same card can be in flight at once. Because the plan re-renders through the captured `card` node behind an `isConnected` guard, that case leaves a stale card on screen with no error.
<question id="1">
Yes. The search rows carry every field the key, the toggle and the block predicate need. `sendReaction`, `blockVideoSource` and `sendUserAction` all resolve `apiParam ?? ""` through `resolveClientApiBase`. `_store_reaction` (server.py 871-901) confirms the values the plan writes to `row.reaction`: like and dislike replace each other, and `undo_dislike` takes the delete path. The delegated listener on `#search-results` covers appended pages. Clearing `state.rows` in `loadPage`'s reset block and in `showIdle` covers every reset path. One edge needs a small change: in-place re-rendering has to stay correct when two different action buttons on the same card are clicked before the first one finishes (see new_impacts).
</question>
<question id="2">
- Search cards get taller, so `fillViewport` fetches fewer pages per screen.
- Search users can now reach the dislike cap (400) and the centroid 502. Both appear as the card's message.
- A key rejected during a card action shows only in the card's status line. This departs from issue 40 line 40, by the operator's decision.
- The no-key prompt names a Profile button that search.html does not have.
- The `outerHTML` swap drops keyboard focus.
- The handler is duplicated from home by hand.
- Search's entry now imports blocks.ts, so the dist chunk graph probably changes, along with hashes on pages other than search.
- "Showing N of M" overstates after a block, as accepted.
</question>
<question id="3">
- Clear `state.rows` on every reset: the `loadPage` reset block and `showIdle`.
- Push rows only after the `seq` check.
- Set `row.reaction` before re-rendering.
- Make the re-render safe when the captured card has already been replaced (see new_impacts).
- Leave home's code untouched.
- Run `npx tsc --noEmit`, because `vite build` does not type-check.
- Rebuild `dist/` once, after both source edits, and commit the whole dist diff, added and deleted files included.
- Make sure `node_modules` exists in the worktree before building or running the esbuild-based tests.
</question>
<question id="4">
- Search cards gain Like, Dislike, Block channel and Block account controls.
- Dislike on search toggles and keeps the card.
- A block removes the loaded cards of that channel or account.
- The shared Dislike button gains `aria-pressed`. On home it is always `"false"`, which is announced as a toggle that is never pressed. Home's behaviour is otherwise unchanged.
- No other page renders action controls.
</question>

New impacts:
client/frontend/src/pages/search/index.ts (new runCardAction): only the clicked button is disabled, so a second button on the same card can be clicked while the first request is still running. Example: Like, then Dislike before Like returns. Like's re-render swaps the card's `outerHTML`, so the `card` node captured by the Dislike call is detached. When Dislike resolves, it sets `row.reaction = "disliked"`, but the `card.isConnected` guard skips its re-render. The page then shows "liked" while `row.reaction` and the server both say "disliked", and the next Dislike click sends `undo_dislike` on a card that does not look disliked. Errors are also written into the detached card's status span, so they are never seen. Home does not hit this, because its dislike and block re-render the whole grid from state; search's in-place re-render is what introduces it.

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Fix the gap from new_impacts in one of two ways. Either changes only search/index.ts, and neither touches home or the settled plan's shape.
   - (a) Recommended. Re-render through the live node, not the captured one. After setting `row.reaction`, find each child of `results` whose `dataset.videoKey` equals `resolveVideoKey(row)`, using the same walk `removeRows` does, and replace its `outerHTML`. Write the status message into the live card's `.card-action-status` too. This replaces the `isConnected` guard: after a reset there is no match, so nothing is touched. As a side effect it also updates the duplicate copy the plan's "same video on two loaded pages" gotcha leaves stale. Cost: about 6-8 lines, plus a fake-DOM test case for it.
   - (b) Disable every `.card-action` in the card for the duration of an action, instead of only the clicked button. Cost: about 2 lines. It does not fix the duplicate-copy case, and it departs further from home's handler.
2. In the new search-page test, cover a second action started while the first is in flight, and a re-render after a reset. Cost: the richer fake DOM the inventory already anticipates.
3. Before building, run `npx tsc --noEmit` and confirm `node_modules` exists. Cost: a minute, plus `npm ci` if node_modules is missing.
4. Get an operator ruling on the no-key prompt's "Profile button" wording on search. Cost: none to implement either way. Req 6 currently fixes the exact text.

## 2026-10-01 - Step 4 - Reassess the implementation plan - ceiling reached

3 passes each surfaced new impacts and the loop stops here; the build proceeds on the inventory as it stands. What the 3th pass was still finding:

client/frontend/src/pages/search/index.ts (new runCardAction): only the clicked button is disabled, so a second button on the same card can be clicked while the first request is still running. Example: Like, then Dislike before Like returns. Like's re-render swaps the card's `outerHTML`, so the `card` node captured by the Dislike call is detached. When Dislike resolves, it sets `row.reaction = "disliked"`, but the `card.isConnected` guard skips its re-render. The page then shows "liked" while `row.reaction` and the server both say "disliked", and the next Dislike click sends `undo_dislike` on a card that does not look disliked. Errors are also written into the detached card's status span, so they are never seen. Home does not hit this, because its dislike and block re-render the whole grid from state; search's in-place re-render is what introduces it.

## 2026-10-01 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-10-01 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Dislike pressed state in the shared card [code]

**Files touched.** client/frontend/src/components/video-card.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (NEW)

**Checkpoint.** Seam: `renderVideoCard` in `client/frontend/src/components/video-card.ts`, called directly from a small esbuild bundle that re-exports it. This follows the precedent in `tests/active/test_frontend_reactions.py` (line 112 re-exports `renderVideoCard` from the component and asserts on the returned markup). The test lives in `tests/tmp/test_frontend_search_card_actions.py` and renders a keyed row with `{ actions: true, reaction: "disliked" }`, `{ actions: true, reaction: null }` (home's case) and `{ actions: true, reaction: "liked" }`. On the `[data-card-action="dislike"]` button it asserts `aria-pressed="true"` for the first and `aria-pressed="false"` for the other two. `npx tsc --noEmit` passes in `client/frontend`.

**Intent.** `renderVideoCard` in `components/video-card.ts` now reports the Dislike button's pressed state from `options.reaction`, the same way it already does for Like.

- C1 - The Dislike button has `aria-pressed="true"` when `options.reaction` is `"disliked"`, and `aria-pressed="false"` otherwise.

**Outcome.** _pending_

#### Phase 2 - Search card controls and Like/Dislike toggles [code]

**Files touched.** client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED)

**Checkpoint.** Seam: the search page entry, `client/frontend/src/pages/search/index.ts`. It is bundled with esbuild (`--loader:.css=empty`, `--define:import.meta.env.DEV=false`) and run under node with a stub `fetch` that records method, path and body, plus an `IntersectionObserver` stub. This follows `tests/active/test_frontend_videos_page.py`. That harness's fake DOM stubs `closest` to return null, so this phase builds a richer fake DOM in the new test file, and phases 3 and 4 reuse it. The new DOM supports `closest`, `dataset`, `children`, `remove`, an `outerHTML` setter that re-parses into a new node, and `isConnected`. Assertions, all made through the DOM and the recorded fetches:
(a) After page 1 and an appended page 2, every keyed `.video-card` under `#search-results` has four `[data-card-action]` buttons, and a keyless row's card has none.
(b) With a key, clicking Dislike sends `dislike`, and the card re-renders with `stat dislikes active` and `aria-pressed="true"`. A second click sends `undo_dislike` and the mark clears. Like on a disliked card sends `like` and the card shows liked, not disliked. A second Like sends `undo_like`. Without a key, Like sends `like` and the like is stored in `localLikes:v1`.
(c) If a new search resolves while a Like is in flight, nothing throws, and the grid and `state.rows` (observed through a following click) hold only the new search's rows.

**Intent.** In `pages/search/index.ts`, keyed search cards on every loaded page carry the card actions, and a Like or Dislike click on one toggles that reaction through the reactions API and re-renders the card in place.

- C1 - Every keyed card on the first page and on an appended page has the four `[data-card-action]` controls, and a keyless card has none.
- C2 - A Like or Dislike click sends the toggled reaction and re-renders that card in place with the new mark, without throwing when a reset replaced the grid mid-request.

**Outcome.** _pending_

#### Phase 3 - Block removes the source's loaded cards [code]

**Files touched.** client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED)

**Checkpoint.** Seam: the same search page bundle and fake DOM as phase 2, driven by clicks on the `[data-card-action="channel"]` and `[data-card-action="account"]` buttons. Assertions:
(a) With a key, Block channel sends `POST /api/profile/blocks` and then a `dislike` reaction, in that order. Every loaded card whose row shares `instance_domain`+`channel_id` is removed from `#search-results`, including cards on page 2. With the sentinel in view, the next page is fetched, which shows that `fillViewport` ran. `#search-status` text is unchanged. Block account does the same, matching on `account_url`.
(b) When the follow-up `dislike` returns 500, the clicked card's `.card-action-status` reads `Blocked <label>, but the dislike failed: <msg>` and no card is removed.

**Intent.** In `pages/search/index.ts`, blocking a channel or account from a search card removes every loaded card of that source, unless the dislike that follows the block fails.

- C1 - A successful block followed by a successful dislike removes every loaded card of that channel or account, refills the viewport and leaves the status text unchanged.
- C2 - A block whose dislike fails reports `Blocked <label|action>, but the dislike failed: <msg>` and removes no card.

**Outcome.** _pending_

#### Phase 4 - No-key guard, failures and dist rebuild [code]

**Files touched.** client/frontend/src/pages/search/index.ts (EDITED), tests/tmp/test_frontend_search_card_actions.py (EDITED), client/frontend/dist/ (REBUILT)

**Checkpoint.** Seam: the same search page bundle and fake DOM as phase 2. Assertions:
(a) With no profile key, clicking Dislike, Block channel and Block account each writes home's exact "Disliking/Blocking needs a profile. Create one from the Profile button." text into the card's `.card-action-status`, and the stub fetch records no request.
(b) With a key, a Dislike that gets a 400 with "Dislike limit reached" puts that message in the status line. The button is enabled again (`disabled` is false), and the card keeps its previous mark, so a second click still sends `dislike`, not `undo_dislike`.
Then `npx tsc --noEmit` and `npm run build` run in `client/frontend`. `tests/active/test_frontend_reactions.py`, `test_frontend_blocks.py` and `test_frontend_videos_page.py` stay green unchanged, and the new test is promoted to `tests/active/`.

**Intent.** In `pages/search/index.ts`, a card action that cannot or does not succeed leaves the card's reaction as it was and explains why in that card's status line.

- C1 - Without a profile key, Dislike, Block channel and Block account each write home's exact profile prompt and send no request.
- C2 - A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged.

**Outcome.** _pending_


Needs coordination: none. Every checkpoint runs offline under node, with a stub fetch. The plan's acceptance reruns need a live Client with a profile key: a keyed rerun of the search showing `reaction: "disliked"`, no reaction after undo, and no blocked-channel rows. Those are backend facts already covered by D6 and `_filter_payload`, so they gate no phase. They are an optional manual check for the operator.

Rationale: The phases follow observable behaviour, smallest first.

P1 is the one-attribute change to the shared component. It has its own seam (`renderVideoCard` called directly, as `test_frontend_reactions.py` already does), and it is the only change home can see (req 9/10), so it lands and is proved separately.

P2 to P4 split `pages/search/index.ts` into three slices that can each be checked on their own:
- P2 covers rendering and the reversible actions. It also covers the row lookup and the reset-during-action robustness these actions need: the `isConnected` guard and `state.rows` reset sit on the same Like/Dislike path. Reqs 1–4 and 8 are met here.
- P3 covers block-and-remove, the one action that changes the grid. Its two outcomes, removal and a failed follow-up dislike, are its two clauses (req 5, and req 8's untouched counters).
- P4 covers the paths where an action is refused or fails (reqs 6, 7). The `dist/` rebuild (req 11) goes in P4 as a closing build step, not a clause, because no checkpoint can usefully prove that a bundle was regenerated. `npx tsc --noEmit` is run in every code phase because Vite does not type-check.

Seams: P2 needs a richer fake DOM than `test_frontend_videos_page.py`, because that harness's `closest` returns null. P2 builds it once in the new test file, and P3 and P4 reuse it. This is the only new test infrastructure.

There is no prose phase. The delivery note about the "Profile button" wording on a page that has no Profile button is documentation, so Step 9 handles it.

The operator approved this breakdown. One caveat: this step's `{principles}`, `{shape_ladder-ladder}` and `{tdd_seams}` placeholders were unfilled, so the seams were chosen from the existing frontend test precedents, not from those documents.

## 2026-10-01 - Step 7 - Phase 1 (Dislike pressed state in the shared card) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`renderVideoCard` in `components/video-card.ts` now reports the Dislike button's pressed state from `options.reaction`, the same way it already does for Like.

- C1 - The Dislike button has `aria-pressed="true"` when `options.reaction` is `"disliked"`, and `aria-pressed="false"` otherwise.

must_prove:
- C1 - The Dislike button has `aria-pressed="true"` when `options.reaction` is `"disliked"`, and `aria-pressed="false"` otherwise.

## 2026-10-01 - Step 7 - Phase 1 (Dislike pressed state in the shared card) - self-check (audit round 1, send-back 0)

`tests/tmp/test_40_search_card_actions_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_40_search_card_actions_phase1.py:67 — with `reaction: "disliked"`, the `[data-card-action="dislike"]` button's `aria-pressed` attribute is the string "true" - expected: "true" — the same `aria-pressed="${boolean}"` interpolation the Like button already uses, which the probe saw render as 'true' for the liked card's Like button. Under the current code the run shows None (no attribute), `assert None == 'true'` at line 67. - excludes: The current code: a Dislike button with no `aria-pressed` reads None. It also rules out copying the Like line unchanged (`reaction === "liked"`), which reads "false" here.
- C1 - tests/tmp/test_40_search_card_actions_phase1.py:68, :69, :70 — with `reaction: null`, `reaction: "liked"`, and no `reaction` key, the Dislike button's `aria-pressed` is the string "false" - expected: "false" in all three cases. The probe saw the current code give None for all three (dislike: [None] for null, liked and omitted), so these lines are red as well, behind line 67. - excludes: An `aria-pressed` written only when the reaction is disliked (`${reaction === "disliked" ? ' aria-pressed="true"' : ""}`) reads None here. The Like line copied unchanged (`reaction === "liked"`) reads "true" at line 69. A hard-coded `aria-pressed="true"` reads "true" in all three.

<assertions>
tests/tmp/test_40_search_card_actions_phase1.py:65 - control: each of the four renders (reaction "disliked", null, "liked", omitted; actions true; keyed row) has exactly one `[data-card-action="dislike"]` button, so the C1 assertions read a real button - control
tests/tmp/test_40_search_card_actions_phase1.py:67 - the Dislike button has aria-pressed == "true" when reaction is "disliked". Against today's code it reads None, which is the observed red - C1
tests/tmp/test_40_search_card_actions_phase1.py:68 - the Dislike button has aria-pressed == "false" when reaction is null (home's case) - C1
tests/tmp/test_40_search_card_actions_phase1.py:69 - the Dislike button has aria-pressed == "false" when reaction is "liked", so a pressed state that tracks any reaction fails - C1
tests/tmp/test_40_search_card_actions_phase1.py:70 - the Dislike button has aria-pressed == "false" when the reaction option is left out entirely (the "otherwise" edge) - C1
tests/tmp/test_40_search_card_actions_phase1.py:71 - control: the Like button still has aria-pressed == "true" when reaction is "liked" - control
tests/tmp/test_40_search_card_actions_phase1.py:72 - control: the Like button has aria-pressed == "false" when reaction is "disliked", so swapping the two buttons' states fails - control
tests/tmp/test_40_search_card_actions_phase1.py:77 - `npx tsc --noEmit` in client/frontend exits 0 or 2. 2 means it reported diagnostics; any other code means it did not check - control for the type-check clause in the Step 6 seam
tests/tmp/test_40_search_card_actions_phase1.py:78 - no line of tsc output names src/components/video-card.ts. The operator chose this scoped form over a whole-project pass - Step 6 seam (tsc), scoped per the operator
</assertions>

<probes>
tests/tmp/test_probe_40_p1.py (first version), via ValidateTests ["tests/tmp/test_probe_40_p1.py", "-s"]: I bundled video-card.ts with esbuild (--platform=node, --define:import.meta.env.DEV=false) and rendered row {video_uuid:"u1", instance_domain:"h.example"} with actions:true. For reaction "disliked" and for null it printed the like button with aria-pressed="false" and the dislike button as `<button type="button" class="card-action" data-card-action="dislike" title="Dislike">`, with no aria-pressed. For "liked" it printed the like button with aria-pressed="true" and the dislike button again with no aria-pressed. A row with no key rendered no card-action at all (`nokey false`), which is why the test uses a keyed row. Same probe, second version: `npx tsc --noEmit` in client/frontend printed exit code 2 and 37 lines. Every error was in src/pages/channels/index.ts, src/pages/video-page/index.ts or src/pages/videos/index.ts, and there were 0 lines naming video-card. The real checkpoint, via ValidateTests ["tests/tmp/test_40_search_card_actions_phase1.py"]: 1 failed, 1 passed. The aria-pressed test fails at line 67 with `assert None == 'true'` after the line-65 control passed. The tsc test passes on the current code. Cleanup: I have no delete tool, so tests/tmp/test_probe_40_p1.py is still on disk and ends in `assert False`; it needs deleting.
</probes>

<unassertable>
The Step 6 seam called for `npx tsc --noEmit` to pass in client/frontend, but a whole-project pass cannot be asserted. It already exits 2 because of 37 lines of errors in three page files this phase does not touch (channels, video-page, videos). I asked, and the operator chose to scope the check: the test asserts tsc runs (exit 0 or 2) and reports no error in src/components/video-card.ts. One other difference: the test is at tests/tmp/test_40_search_card_actions_phase1.py, the path this step names, not the tests/tmp/test_frontend_search_card_actions.py the Intent mentions.
</unassertable>

### `tests/tmp/test_40_search_card_actions_phase1.py` - 4090 characters, inlined in full

```
"""`renderVideoCard` (`components/video-card.ts`) reports the Dislike button's pressed state, run in node.

- With `actions: true` on a keyed row, the `[data-card-action="dislike"]` button carries `aria-pressed="true"` when `reaction` is `"disliked"`, and `aria-pressed="false"` when it is `null`, `"liked"` or omitted.
- `npx tsc --noEmit` in client/frontend reports no error in `src/components/video-card.ts`. The project already has type errors in three unrelated page files, so the check is scoped to the changed file.
"""
from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
ROW = {"video_uuid": "9c1f6a2e-0000-4000-8000-000000000040", "instance_domain": "videos.example", "title": "A video"}

RUNNER = """
const m = await import(process.env.BUNDLE);
const row = JSON.parse(process.env.ROW);
const out = {};
for (const [name, reaction] of [["disliked", "disliked"], ["null", null], ["liked", "liked"]]) out[name] = m.renderVideoCard(row, { actions: true, reaction });
out.omitted = m.renderVideoCard(row, { actions: true });
process.stdout.write(JSON.stringify(out));
"""


class _Buttons(HTMLParser):
    """Collect the attributes of every `data-card-action` button, keyed by its action."""

    def __init__(self) -> None:
        super().__init__()
        self.found: dict[str, list[dict]] = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "button" and "data-card-action" in attributes:
            self.found.setdefault(attributes["data-card-action"], []).append(attributes)


def _buttons(html: str) -> dict[str, list[dict]]:
    parser = _Buttons()
    parser.feed(html)
    return parser.found


def _render(tmp_path: Path) -> dict[str, str]:
    entry = tmp_path / "entry.ts"
    entry.write_text(f'export {{ renderVideoCard }} from "{FRONTEND}/src/components/video-card.ts";\n')
    bundle = tmp_path / "bundle.mjs"
    subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", f"--outfile={bundle}", "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    runner = tmp_path / "runner.mjs"
    runner.write_text(RUNNER)
    proc = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=60, env={"BUNDLE": str(bundle), "ROW": json.dumps(ROW), "PATH": os.environ.get("PATH", "")})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_dislike_button_is_pressed_only_when_the_reaction_is_disliked(tmp_path):
    cards = {name: _buttons(html) for name, html in _render(tmp_path).items()}
    for name, buttons in cards.items():
        assert len(buttons.get("dislike", [])) == 1, (name, buttons)  # control: the keyed row renders one Dislike button

    assert cards["disliked"]["dislike"][0].get("aria-pressed") == "true", cards["disliked"]  # C1
    assert cards["null"]["dislike"][0].get("aria-pressed") == "false", cards["null"]  # C1: home's case
    assert cards["liked"]["dislike"][0].get("aria-pressed") == "false", cards["liked"]  # C1: a like is not a dislike
    assert cards["omitted"]["dislike"][0].get("aria-pressed") == "false", cards["omitted"]  # C1: no reaction option at all
    assert cards["liked"]["like"][0].get("aria-pressed") == "true"  # control: the Like button still reports its own state
    assert cards["disliked"]["like"][0].get("aria-pressed") == "false"  # control: the dislike does not press Like


def test_the_type_check_reports_no_error_in_the_video_card_component():
    proc = subprocess.run(["npx", "tsc", "--noEmit"], cwd=FRONTEND, capture_output=True, text=True, timeout=600)
    assert proc.returncode in (0, 2), (proc.returncode, proc.stdout, proc.stderr)  # 0 clean, 2 diagnostics reported; anything else means tsc did not check
    assert [line for line in proc.stdout.splitlines() if "src/components/video-card.ts" in line] == []

```


Gate: satisfied

## 2026-10-01 - Step 7 - Phase 1 (Dislike pressed state in the shared card) - red (audit round 1)

`tests/tmp/test_40_search_card_actions_phase1.py` exited 1.

```
  tests/tmp/test_40_search_card_actions_phase1.py  1 failed, 1 passed                     0.0s
  -----------------------------------------------
  total                                            1 failed, 1 passed                     0.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 1 (Dislike pressed state in the shared card) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. absence-only-assertion (rules/shape.md), but not at Critical severity — tests/tmp/test_40_search_card_actions_phase1.py:78
   assert [line for line in proc.stdout.splitlines() if "src/components/video-card.ts" in line] == []
   The test's only claim about the changed file is a negative one, so it passes on the code as it stands. If the Dislike change is never written, it stays green, which means it does not gate C1. It is not Critical because line 77 pairs it with a positive control (`proc.returncode in (0, 2)`), showing tsc actually ran and checked. That is what the entry's `<alternatives>` asks for: "assert what DID happen". Treat it as a regression guard that comes with this test, not as evidence for C1.

PREDICTED FAILURE
`test_the_dislike_button_is_pressed_only_when_the_reaction_is_disliked` fails at line 67: `cards["disliked"]["dislike"][0].get("aria-pressed")` returns `None`, not `"true"`, because the Dislike button at video-card.ts:356 has no `aria-pressed` attribute. The line-65 control passes first, because ROW has both `video_uuid` and `instance_domain`, so `videoKey` resolves and the actions markup renders. `test_the_type_check_reports_no_error_in_the_video_card_component` is expected to pass.

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py, which does not exist (FileNotFoundError), so it was not read. The audit used client/frontend/src/components/video-card.ts only.
2. Whether `client/frontend/node_modules/.bin/esbuild` and `node` exist was not checked. If either is missing, the test fails at line 51 or line 58 instead of the predicted line 67. Running the test would show this, and the auditor does not run tests.

Ladder pass (no finding): test 1 calls `renderVideoCard` directly through a Node bundle and parses the returned HTML with `HTMLParser` before asserting on attribute values. That puts it at rung 1, with no substring-in-prose and no downshift. Test 2 is rung 2: it runs tsc as a subprocess and asserts on the exit code and stdout.

Stub question (no finding): test 1 checks the Dislike button with four inputs and asserts the difference between them. `"true"` is expected only for `"disliked"`; `"false"` is expected for `null`, `"liked"` and an omitted reaction. A hard-coded `"true"` fails line 68. A hard-coded `"false"` or a missing attribute fails line 67. Copying the Like button's `reaction === "liked"` expression fails lines 67 and 69. Lines 71–72 check that the Like button still reports its own state.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (12 clauses: 4 must_prove, 5 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | Dislike button has `aria-pressed="true"` when `options.reaction` is `"disliked"` | :67 | a Dislike button with no `aria-pressed`, or one that never reads `"true"` (returns `None` or `"false"`) | CARRIED |
| C1b | must_prove | `aria-pressed="false"` otherwise: reaction `null` | :68 | the attribute missing on a null reaction, or always set to `"true"` | CARRIED |
| C1c | must_prove | `aria-pressed="false"` otherwise: reaction `"liked"` | :69 | Dislike pressed by any non-null reaction (`!!reaction`), or wired to the like state | CARRIED |
| C1d | must_prove | `aria-pressed="false"` otherwise: `reaction` omitted | :70 | an undefined reaction producing a missing attribute or `"undefined"` and not `"false"` | CARRIED |
| D1 | docstring | "with `actions: true` on a keyed row, the `[data-card-action="dislike"]` button" is rendered | :65 | no Dislike button, or a duplicate, in any of the four renders | CARRIED |
| D2 | docstring | "carries `aria-pressed="true"` when `reaction` is `"disliked"`" | :67 | same as C1a | CARRIED |
| D3 | docstring | "`aria-pressed="false"` when it is `null`, `"liked"` or omitted" | :68, :69, :70 | each of the three "otherwise" values asserted separately, as in C1b–C1d | CARRIED |
| D4 | docstring | "`npx tsc --noEmit` ... reports no error in `src/components/video-card.ts`" | :78 | a type error in the changed file, such as a non-string attribute interpolation | CARRIED |
| D5 | docstring | the type check "is scoped to the changed file" and really ran | :77, :78 | tsc failing to start (an exit code other than 0 or 2) being read as clean; errors in unrelated pages failing the test | CARRIED |
| N1 | name | "the dislike button is pressed ... when the reaction is disliked" | :67 | an unpressed or attribute-less Dislike button under `"disliked"` | CARRIED |
| N2 | name | "only" when disliked | :68, :69, :70 | pressed under null, liked or omitted | CARRIED |
| N3 | name | "the type check reports no error in the video card component" | :78 | any tsc diagnostic line naming `src/components/video-card.ts` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase1.py:22
   Every render uses `actions: true` on a keyed `ROW`. Nothing checks the case where no button should exist: `actions` false or omitted, or a row with no `instance_domain`/`video_uuid`, so `resolveVideoKey` returns null. A Dislike button leaking onto those cards with any `aria-pressed` value would not fail this test. C1 does not require that case, so this is not a Critical.
2. checkpoint_definition (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase1.py:75
   `test_the_type_check_reports_no_error_in_the_video_card_component` is a compiler/lint run. `<checkpoint_definition>` says that kind of check is not checkpoint evidence. It carries no `must_prove` clause, and C1 is fully carried by the functional test at :62. So the checkpoint does meet the definition, but this second test should not be counted as gating evidence for the phase.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py (NEW), which does not exist at that path. Whatever that file was meant to contribute was not assessed. The audit used the test file and client/frontend/src/components/video-card.ts.
2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines no other fixture, so no conftest was needed for the independence check.

## 2026-10-01 - Step 7 - Phase 1 (Dislike pressed state in the shared card) - checkpoint outcome (run 1)

`tests/tmp/test_40_search_card_actions_phase1.py` exited 0 after the phase landed.

<changes>
### client/frontend/src/components/video-card.ts
In `renderVideoCard`, the Dislike action button (`data-card-action="dislike"`) now has `aria-pressed="${reaction === "disliked"}"`, which follows how the Like button already does it. It renders `"true"` when `options.reaction` is `"disliked"` and `"false"` in every other case: `null`, `"liked"`, or the option left out. `reaction` already falls back to `null`, so the attribute is always present. No other markup changed.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none. One note: the phase's file list names `tests/tmp/test_frontend_search_card_actions.py (NEW)`, but the gating checkpoint is `tests/tmp/test_40_search_card_actions_phase1.py`, and that already exists. I did not create the listed file because the checkpoint covers this phase. If the build expects that path to exist, it is still missing.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_40_search_card_actions_phase1.py  2 passed                               0.0s
  -----------------------------------------------
  total                                            2 passed                               0.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 2 (Search card controls and Like/Dislike toggles) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
In `pages/search/index.ts`, keyed search cards on every loaded page carry the card actions, and a Like or Dislike click on one toggles that reaction through the reactions API and re-renders the card in place.

- C1 - Every keyed card on the first page and on an appended page has the four `[data-card-action]` controls, and a keyless card has none.
- C2 - A Like or Dislike click sends the toggled reaction and re-renders that card in place with the new mark, without throwing when a reset replaced the grid mid-request.

must_prove:
- C1 - Every keyed card on the first page and on an appended page has the four `[data-card-action]` controls, and a keyless card has none.
- C2 - A Like or Dislike click sends the toggled reaction and re-renders that card in place with the new mark, without throwing when a reset replaced the grid mid-request.

## 2026-10-01 - Step 7 - Phase 2 (Search card controls and Like/Dislike toggles) - self-check (audit round 1, send-back 0)

`tests/tmp/test_40_search_card_actions_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_40_search_card_actions_phase2.py:306 — after page 1 and the observer-appended page 2, with a key, every keyed card's `[data-card-action]` list maps to ["like","dislike","channel","account"] - expected: {a1, a2, b1, b2 keys: ["like","dislike","channel","account"]}. The probe saw this list on a real `renderVideoCard(row, {actions: true})` card parsed by the fake DOM. The run as it stands shows [] for all four. - excludes: The current renderRows never passes `actions: true`, so every list reads [] (seen in the run). A page that passes actions only on the reset/innerHTML path leaves b1 and b2 at [] and fails the same way.
- C1 - test_40_search_card_actions_phase2.py:307 — the keyless card on page 1 and the one on page 2 both have empty action lists - expected: [[], []]. The probe saw a keyless row rendered with actions:true give actions [] and key null. - excludes: A page that adds its own buttons around every card, or keys cards by title, reads a non-empty list for k1/k2.
- C1 - test_40_search_card_actions_phase2.py:332 — without a profile key, the grid reads [(a1 key, ACTIONS), (None, []), (a2 key, ACTIONS)] - expected: Keyed cards have the four controls and the keyless card has none. The run as it stands shows [] for a1 and a2. - excludes: A page that sets `actions` only when `getProfileKey()` is set reads [] for a1 and a2.
- C1 - test_40_search_card_actions_phase2.py:348 — the first search's reset-rendered grid reads [(a1,ACTIONS),(a2,ACTIONS),(a3,ACTIONS)] - expected: All three cards carry the four controls. The run as it stands shows [] for each. - excludes: A page that passes actions only on the append (insertAdjacentHTML) path reads [] here.
- C2 - test_40_search_card_actions_phase2.py:316 — each of Dislike, Dislike, Dislike, Like, Like on page-2 card b2 sends exactly one POST /api/user-action with that step's action for uuid-b2@peer.example - expected: dislike, undo_dislike, dislike, like, undo_like, one request per click. The probe saw the request shape {method POST, action, uuid, host} come from the real sendReaction. - excludes: A port of the videos page's handler always sends `dislike` for Dislike, which reads dislike at step 2 instead of undo_dislike. A Like toggle that checks only `liked` sends undo_like on a disliked card. A handler that does nothing sends [].
- C2 - test_40_search_card_actions_phase2.py:318 — after each click the card's (likesActive, likePressed, dislikesActive, dislikePressed) equals DISLIKED, NEUTRAL, DISLIKED, LIKED, NEUTRAL in turn - expected: (False,"false",True,"true") → (False,"false",False,"false") → DISLIKED → (True,"true",False,"false") → NEUTRAL. The probe saw exactly these tuples for real cards rendered with reaction disliked, null and liked. - excludes: A page that sends but does not redraw keeps NEUTRAL after step 1. One that does not update row.reaction redraws the stale mark. One that removes the card on Dislike, as the videos page does, gives card None.
- C2 - test_40_search_card_actions_phase2.py:319 — after each click the redrawn card still has ["like","dislike","channel","account"] - expected: ACTIONS on every step - excludes: A redraw through renderVideoCard without `actions: true` reads [].
- C2 - test_40_search_card_actions_phase2.py:321 and :322 — after each click the grid's key order is unchanged, and every card other than b2 equals its pre-click state - expected: The same 6-key order as the initial grid, and the other five card states are identical to `others`. - excludes: A redraw that re-renders the whole grid from page 1 rows only drops the page-2 cards. Appending the new card instead of replacing it moves b2 to the end. Removing on dislike shortens the list.
- C2 - test_40_search_card_actions_phase2.py:335, :336, :337 — without a key, Like on a1 sends `like`, localLikes:v1 becomes [{video_uuid:"uuid-a1", instance_domain:"peer.example"}], and the card reads LIKED - expected: [POST like uuid-a1@peer.example]; the stored JSON is exactly that one entry; marks (True,"true",False,"false"). The probe saw sendReaction without a key store `[{"video_uuid":"uuid-n","instance_domain":"peer.example"}]` and cardReaction then return "liked". - excludes: A page that asks for a profile before any action sends [] and stores null. One that redraws from row.reaction instead of cardReaction shows NEUTRAL without a key.
- C2 - test_40_search_card_actions_phase2.py:356 and :357 — once the held Like resolves after a new search replaced the grid, no error is recorded and the clicked (detached) card's status text is "" - expected: errors == [] and status == "". The probe saw that setting outerHTML on a detached card throws "NoModificationAllowedError: This element has no parent node.", and that the real card's status span reads "". - excludes: The videos page's `card.outerHTML = …` without an isConnected check throws. Its catch then writes that message into the status line (status != ""), or the error escapes (errors non-empty).
- C2 - test_40_search_card_actions_phase2.py:359 and :360 — after the release, the grid still holds c1, a2, c2 of the second search, all NEUTRAL - expected: [c1, a2, c2] keys, all (False,"false",False,"false") - excludes: A redraw that looks the card up again by key in the live grid repaints the second search's a2 as LIKED.
- C2 - test_40_search_card_actions_phase2.py:362 and :363 — a following Like on a2 in the new grid sends `like` and the card reads LIKED - expected: [POST like uuid-a2@peer.example], marks LIKED - excludes: A row list the reset did not clear still holds the first search's a2, marked liked by the late response. The lookup finds that row first and sends undo_like, and the card reads NEUTRAL.

<assertions>
tests/tmp/test_40_search_card_actions_phase2.py:303 - control: the search fetches were page 1 on load, then page 2 once the observer reported the sentinel in view
tests/tmp/test_40_search_card_actions_phase2.py:304 - control: the grid holds page 1's cards followed by page 2's, in row order, and the keyless rows' cards have no data-video-key
tests/tmp/test_40_search_card_actions_phase2.py:306 - every keyed card on page 1 and on the appended page 2 has exactly the [data-card-action] buttons like, dislike, channel, account (C1)
tests/tmp/test_40_search_card_actions_phase2.py:307 - the keyless card on each page has no [data-card-action] button (C1)
tests/tmp/test_40_search_card_actions_phase2.py:308 - control: no keyed card starts liked or disliked
tests/tmp/test_40_search_card_actions_phase2.py:314 - control: before each click, the icon to click exists on the current page-2 card
tests/tmp/test_40_search_card_actions_phase2.py:316 - clicking Dislike, Dislike, Dislike, Like, Like on the page-2 card sends POST /api/user-action with dislike, undo_dislike, dislike, like, undo_like, each carrying that card's uuid and host (C2)
tests/tmp/test_40_search_card_actions_phase2.py:318 - after each click the card shows disliked (dislikes stat active, Dislike aria-pressed="true"), then neutral, then disliked, then liked and not disliked (likes stat active, Like aria-pressed="true", Dislike aria-pressed="false"), then neutral (C2)
tests/tmp/test_40_search_card_actions_phase2.py:319 - the redrawn card still has its four controls (C2)
tests/tmp/test_40_search_card_actions_phase2.py:321 - the grid's card order is unchanged after each click, so the card was redrawn in place (C2)
tests/tmp/test_40_search_card_actions_phase2.py:322 - every other card is unchanged after each click (C2)
tests/tmp/test_40_search_card_actions_phase2.py:323 - no error escaped during paging and the toggles (C2)
tests/tmp/test_40_search_card_actions_phase2.py:330 - control: before the keyless click, localLikes:v1 is empty
tests/tmp/test_40_search_card_actions_phase2.py:331 - control: the keyless visitor's keyed card has a Like button to click
tests/tmp/test_40_search_card_actions_phase2.py:333 - without a key, Like sends one POST like for that video (C2)
tests/tmp/test_40_search_card_actions_phase2.py:334 - localLikes:v1 then holds exactly that video's uuid and host (C2)
tests/tmp/test_40_search_card_actions_phase2.py:335 - the card is redrawn liked: likes stat active and Like aria-pressed="true" (C2)
tests/tmp/test_40_search_card_actions_phase2.py:336 - no error escaped during the keyless Like (C2)
tests/tmp/test_40_search_card_actions_phase2.py:347 - control: the Like on a2 was sent and its response is still held when the new search starts
tests/tmp/test_40_search_card_actions_phase2.py:348 - control: the second search was fetched
tests/tmp/test_40_search_card_actions_phase2.py:349 - control: before the Like resolves, the grid already holds the second search's cards
tests/tmp/test_40_search_card_actions_phase2.py:350 - control: the clicked card is detached when the Like resolves
tests/tmp/test_40_search_card_actions_phase2.py:353 - no unhandled rejection, uncaught exception or listener throw is recorded (C2)
tests/tmp/test_40_search_card_actions_phase2.py:354 - the clicked card's status line is empty, so the redraw did not throw into the action's error path (C2)
tests/tmp/test_40_search_card_actions_phase2.py:356 - after the Like resolves, the grid holds exactly the second search's cards (C2)
tests/tmp/test_40_search_card_actions_phase2.py:357 - every card in that grid is unmarked; the resolved Like did not reach the new a2 card (C2)
tests/tmp/test_40_search_card_actions_phase2.py:359 - a following Like on the new a2 card sends like, not undo_like, so state.rows holds the new search's row and not the first search's stale liked one (C2)
tests/tmp/test_40_search_card_actions_phase2.py:360 - that new a2 card is then redrawn liked (C2)
</assertions>

<probes>
Probe file: tests/tmp/test_probe_40_p2.py, run with ValidateTests ["tests/tmp/test_probe_40_p2.py"] (it is now emptied with a delete-me note, because no tool here can delete a file). It ran the checkpoint's scenarios and its three test functions against four bundles. Output:
- `node --version`: v22.22.2, so `findLastIndex` is available to the fake DOM.
- CURRENT (the unmodified search page): page 1, then page 2 after the observer callback (`[["music","1"],["music","2"]]`). Grid order is a1, keyless k1, a2, b1, b2, keyless k2, with keys null on the keyless cards. Every card has `actions: []`, every press finds no icon, and nothing is sent. Result: the paged test fails at C1 (line 306). The keyless test fails at its pressed control (line 331), and the reset test at its held-Like control (line 347). Both fail there because the current page has no buttons to click.
- PLAN (the current file patched with the plan's draft `state.rows`, the reset clear, `renderSearchCard`, the click listener and the Like/Dislike branches of `runCardAction`, with the `isConnected` guard):
  - Paged steps sent dislike, undo_dislike, dislike, like, undo_like for uuid-b2 on peer.example. The marks were (False,'false',True,'true'), (False,'false',False,'false'), (False,'false',True,'true'), (True,'true',False,'false'), (False,'false',False,'false').
  - Keyless: storedBefore None, then stored `[{"video_uuid":"uuid-a1","instance_domain":"peer.example"}]`, sent [like], card liked.
  - Reset: heldOpen 1, clicked `{connected: false, status: ""}`, afterRelease c1/a2/c2 all unliked, the next Like sent `like` and showed the card liked, errors [].
  - All three tests PASS.
- NOGUARD (the plan's draft with `if (true)` in place of `card.isConnected`): the reset test FAILS at line 354. The clicked status reads "NoModificationAllowedError: This element has no parent node.", and errors stay [] because runCardAction's catch swallows the throw. So line 354 is the observable that carries "without throwing".
- NOCLEAR (the plan's draft without `state.rows = []` in the loadPage reset): the reset test FAILS at line 359. The following Like sends `undo_like`, because the find hits the first search's a2 row, which the resolved Like marked liked.
- Final run of the checkpoint (ValidateTests ["tests/tmp/test_40_search_card_actions_phase2.py"]): 3 failed against the current tree.

Not observed: the fake DOM's outerHTML setter throws on an element with no parent. That follows the plan's premise and Chromium's `Element::setOuterHTML` as I recall it ("This element has no parent node."). I did not run this in a browser. The DOM Parsing spec, and I believe Firefox, return silently instead. Running `document.createElement("div").outerHTML = "<p>"` in Chrome would confirm it. If browsers do not throw, line 354 checks only the plan's guard and not a real crash.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_40_search_card_actions_phase2.py` - 23582 characters, inlined in full

```
"""Search result cards carry the card controls on every loaded page, and Like and Dislike on one toggle the reaction and redraw that card in place.

`pages/search/index.ts` is bundled and run in node against a fake DOM that parses the markup it is given, a stub fetch that records each request, and an IntersectionObserver stub that loads page 2 when told the sentinel is in view. Clicks land on the icon inside the button, as a user's would.

- With a key, after page 1 and the appended page 2, every keyed card has the `like`, `dislike`, `channel` and `account` buttons, and the keyless card on each page has none.
- On a page-2 card, Dislike, Dislike, Dislike, Like, Like send `dislike`, `undo_dislike`, `dislike`, `like`, `undo_like` for that video. After each click, the card shows disliked (dislikes stat active, Dislike `aria-pressed="true"`), then neutral, then disliked, then liked and not disliked, then neutral. It stays at its position with its four controls, and no other card changes.
- Without a key, Like sends `like`, `localLikes:v1` then holds the video, and the card shows liked.
- With a key, a Like whose response is held while a new search replaces the grid resolves without an error escaping and without writing an error into the clicked card's status line. The grid holds the new search's cards, all unmarked, and a following Like on the card of a video both searches returned sends `like`, not the `undo_like` a leftover row from the first search would cause.

The fake DOM throws when outerHTML is set on an element with no parent, as Chromium does. The card's other markup, and the Block buttons' behaviour, are not asserted here.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
ENTRY = FRONTEND / "src" / "pages" / "search" / "index.ts"
BASE = "http://client.test"
PROFILE_KEY = "profileKey:v1"
KEY = "K" * 43
ACTIONS = ["like", "dislike", "channel", "account"]

# The search page runs against a fake DOM that parses the markup it is given, so cards, their buttons and their marks are elements the page can walk with closest/querySelector and replace through outerHTML. Elements fetched by id hang off document.body, which is what isConnected walks to.
RUNNER = r"""
const memory = (seed) => { const s = new Map(Object.entries(seed)); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory(JSON.parse(process.env.STORAGE));
globalThis.sessionStorage = memory({});
globalThis.window = { location: { origin: process.env.BASE, pathname: "/search.html", search: process.env.SEARCH }, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage,
  innerHeight: 800, scrollY: 0, history: { pushState() {}, replaceState() {} }, addEventListener() {} };

const VOID = new Set(["area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: "\"", "#39": "'" };
const decode = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (_m, e) => ENTITIES[e]);
const escapeText = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" })[c]);
const TOKEN = /<\/([\w-]+)\s*>|<([\w-]+)((?:\s+[^\s=/>]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g;
const ATTR = /([^\s=/>]+)(?:="([^"]*)")?/g;
const kebab = (k) => k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
const detach = (n) => { const p = n.parentElement; if (p) p.childNodes.splice(p.childNodes.indexOf(n), 1); n.parentElement = null; };
const text = (v) => ({ nodeType: 3, data: String(v), parentElement: null, get textContent() { return this.data; } });
const serialize = (n) => {
  if (n.nodeType === 3) return escapeText(n.data);
  const tag = n.tagName.toLowerCase();
  const attrs = Object.entries(n.attrs).map(([k, v]) => ` ${k}="${escapeText(v)}"`).join("");
  return VOID.has(tag) ? `<${tag}${attrs}>` : `<${tag}${attrs}>${n.childNodes.map(serialize).join("")}</${tag}>`;
};
const parse = (html) => {
  const root = element("template");
  const open = [root];
  for (const [, close, tag, attrs, selfClose, txt] of String(html).matchAll(TOKEN)) {
    const top = open[open.length - 1];
    if (txt !== undefined) top.append(text(decode(txt)));
    else if (close) { const i = open.findLastIndex((n) => n.tagName === close.toUpperCase()); if (i > 0) open.length = i; }
    else {
      const el = element(tag);
      for (const [, name, value] of attrs.matchAll(ATTR)) el.setAttribute(name, decode(value ?? ""));
      top.append(el);
      if (!selfClose && !VOID.has(tag.toLowerCase())) open.push(el);
    }
  }
  const nodes = [...root.childNodes];
  nodes.forEach(detach);
  return nodes;
};
// Simple and compound selectors, joined by descendant combinators or commas; anything else throws so an unsupported query fails loudly instead of matching nothing.
const COMPOUND = /^([\w-]+|\*)?((?:\.[\w-]+|\[[\w-]+(?:="[^"]*")?\])*)$/;
const matchesCompound = (el, compound) => {
  const m = COMPOUND.exec(compound);
  if (!m || !compound) throw new Error(`fake DOM: unsupported selector ${compound}`);
  if (m[1] && m[1] !== "*" && el.tagName !== m[1].toUpperCase()) return false;
  for (const [, cls, attr, value] of m[2].matchAll(/\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g)) {
    if (cls && !el.classList.contains(cls)) return false;
    if (attr && (!(attr in el.attrs) || (value !== undefined && el.attrs[attr] !== value))) return false;
  }
  return true;
};
const matches = (el, selector) => selector.split(",").some((part) => {
  const steps = part.trim().split(/\s+/);
  if (!matchesCompound(el, steps[steps.length - 1])) return false;
  let node = el.parentElement;
  for (let i = steps.length - 2; i >= 0; i -= 1) {
    while (node && !matchesCompound(node, steps[i])) node = node.parentElement;
    if (!node) return false;
    node = node.parentElement;
  }
  return true;
});
const descend = (n) => n.children.flatMap((c) => [c, ...descend(c)]);
const element = (tag) => {
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), attrs: {}, childNodes: [], parentElement: null, listeners: {}, disabled: false, value: "", style: {},
    get children() { return el.childNodes.filter((n) => n.nodeType === 1); },
    get className() { return el.attrs.class ?? ""; }, set className(v) { el.attrs.class = String(v); },
    get textContent() { return el.childNodes.map((n) => n.textContent).join(""); },
    set textContent(v) { el.replaceChildren(...(v == null || v === "" ? [] : [text(v)])); },
    get innerHTML() { return el.childNodes.map(serialize).join(""); },
    set innerHTML(v) { el.replaceChildren(...parse(v)); },
    get outerHTML() { return serialize(el); },
    // Chromium throws here for an element with no parent (NoModificationAllowedError), which is the case a detached card meets.
    set outerHTML(v) {
      const parent = el.parentElement;
      if (!parent) throw new Error("NoModificationAllowedError: This element has no parent node.");
      const nodes = parse(v);
      parent.childNodes.splice(parent.childNodes.indexOf(el), 1, ...nodes);
      for (const n of nodes) n.parentElement = parent;
      el.parentElement = null;
    },
    get isConnected() { let n = el; while (n.parentElement) n = n.parentElement; return n === document.body; },
    dataset: new Proxy({}, { get: (_t, k) => el.attrs[`data-${kebab(String(k))}`], set: (_t, k, v) => { el.attrs[`data-${kebab(String(k))}`] = String(v); return true; } }),
    classList: {
      contains: (c) => el.className.split(/\s+/).includes(c),
      add: (...cs) => { el.className = [...new Set([...el.className.split(/\s+/).filter(Boolean), ...cs])].join(" "); },
      remove: (...cs) => { el.className = el.className.split(/\s+/).filter((c) => c && !cs.includes(c)).join(" "); },
      toggle: (c, force) => { const on = force ?? !el.classList.contains(c); if (on) el.classList.add(c); else el.classList.remove(c); return on; },
    },
    append: (...items) => { for (const item of items) { const node = typeof item === "string" ? text(item) : item; detach(node); node.parentElement = el; el.childNodes.push(node); } },
    appendChild: (node) => { el.append(node); return node; },
    replaceChildren: (...items) => { for (const n of el.childNodes) n.parentElement = null; el.childNodes = []; el.append(...items); },
    remove: () => detach(el),
    insertAdjacentHTML: (position, html) => {
      const nodes = parse(html);
      if (position === "beforeend") el.append(...nodes);
      else if (position === "afterbegin") { el.childNodes.unshift(...nodes); for (const n of nodes) n.parentElement = el; }
      else throw new Error(`fake DOM: unsupported insertAdjacentHTML position ${position}`);
    },
    setAttribute: (n, v) => { el.attrs[n] = String(v); if (n === "disabled") el.disabled = true; },
    getAttribute: (n) => el.attrs[n] ?? null, hasAttribute: (n) => n in el.attrs,
    removeAttribute: (n) => { delete el.attrs[n]; if (n === "disabled") el.disabled = false; },
    addEventListener: (type, l) => { (el.listeners[type] ??= []).push(l); },
    removeEventListener: (type, l) => { el.listeners[type] = (el.listeners[type] ?? []).filter((x) => x !== l); },
    matches: (s) => matches(el, s),
    closest: (s) => { for (let n = el; n; n = n.parentElement) if (matches(n, s)) return n; return null; },
    querySelector: (s) => descend(el).find((n) => matches(n, s)) ?? null,
    querySelectorAll: (s) => descend(el).filter((n) => matches(n, s)),
    // The sentinel sits far below the viewport, so pages load only when the observer reports it in view.
    getBoundingClientRect: () => ({ top: 100000, bottom: 100000, left: 0, right: 0, width: 0, height: 0 }),
    focus() {}, select() {},
  };
  return el;
};
const byId = new Map();
globalThis.document = { title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) { const el = element("div"); el.attrs.id = id; document.body.append(el); byId.set(id, el); } return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (v) => text(v), querySelector: (s) => document.body.querySelector(s), querySelectorAll: (s) => document.body.querySelectorAll(s), addEventListener() {} };
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { observers.push(callback); } observe() {} unobserve() {} disconnect() {} };

const pages = JSON.parse(process.env.PAGES);
const requests = [];
const holds = [];
let holdNextAction = process.env.HOLD_ACTION === "1";
globalThis.fetch = async (input, init = {}) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: String(init.method ?? "GET").toUpperCase(), path: url.pathname, query: Object.fromEntries(url.searchParams), body: init.body == null ? null : JSON.parse(String(init.body)) });
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/v1/search/videos") {
    const page = pages[url.searchParams.get("q")]?.[Number(url.searchParams.get("page") ?? "1") - 1];
    return new Response(JSON.stringify(page ?? { rows: [], total: 0 }), { status: 200, headers });
  }
  if (url.pathname === "/api/user-action") {
    if (holdNextAction) { holdNextAction = false; await new Promise((resolve) => holds.push(resolve)); }
    return new Response("{}", { status: 200, headers });
  }
  return new Response(JSON.stringify({ error: "unexpected route" }), { status: 404, headers });
};
const errors = [];
process.on("unhandledRejection", (r) => { errors.push(String(r && r.stack || r)); });
process.on("uncaughtException", (e) => { errors.push(String(e && e.stack || e)); });
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 10)); };
// Events bubble through parentElement; a listener that throws is recorded, as a browser would report it.
const fire = (target, type) => {
  const event = { type, target, bubbles: true, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() { event.stopped = true; } };
  for (let node = target; node && !event.stopped; node = node.parentElement) {
    event.currentTarget = node;
    for (const l of [...(node.listeners[type] ?? [])]) { try { l.call(node, event); } catch (e) { errors.push(String(e && e.stack || e)); } }
  }
};
// A user clicks the icon inside an icon-only button; a disabled button dispatches no click.
const click = (target) => { for (let n = target; n; n = n.parentElement) if (n.tagName === "BUTTON" && n.disabled) return; fire(target, "click"); };
const grid = () => byId.get("search-results");
const cardOf = (key) => grid().children.find((c) => c.dataset.videoKey === key) ?? null;
const cardState = (card) => ({
  key: card.dataset.videoKey ?? null,
  title: card.querySelector(".video-title")?.textContent ?? null,
  actions: card.querySelectorAll("[data-card-action]").map((b) => b.dataset.cardAction),
  likesActive: card.querySelector(".stat.likes")?.classList.contains("active") ?? null,
  likePressed: card.querySelector("[data-card-action=\"like\"]")?.getAttribute("aria-pressed") ?? null,
  dislikesActive: card.querySelector(".stat.dislikes")?.classList.contains("active") ?? null,
  dislikePressed: card.querySelector("[data-card-action=\"dislike\"]")?.getAttribute("aria-pressed") ?? null,
});
const cards = () => grid().children.map(cardState);
const searches = () => requests.filter((r) => r.path === "/api/v1/search/videos").map((r) => [r.query.q, r.query.page ?? "1"]);
const sent = () => requests.filter((r) => r.path === "/api/user-action").map((r) => ({ method: r.method, action: r.body?.action, uuid: r.body?.uuid, host: r.body?.host }));
const press = (key, action) => { const icon = cardOf(key)?.querySelector(`[data-card-action="${action}"] path`); if (icon) click(icon); return Boolean(icon); };
const step = async (key, action) => { const before = sent().length; const pressed = press(key, action); await settle(); const card = cardOf(key); return { action, pressed, sent: sent().slice(before), card: card && cardState(card), grid: cards() }; };

await import(process.env.BUNDLE);
await settle();
const target = process.env.TARGET;
const report = {};
if (process.env.SCENARIO === "paged") {
  for (const callback of observers) callback([{ isIntersecting: true }]);
  await settle();
  report.searches = searches();
  report.grid = cards();
  report.steps = [];
  for (const action of ["dislike", "dislike", "dislike", "like", "like"]) report.steps.push(await step(target, action));
}
if (process.env.SCENARIO === "keyless") {
  report.grid = cards();
  report.storedBefore = localStorage.getItem("localLikes:v1");
  report.like = await step(target, "like");
  report.stored = localStorage.getItem("localLikes:v1");
}
if (process.env.SCENARIO === "reset") {
  const clicked = cardOf(target);
  report.firstGrid = cards();
  report.held = await step(target, "like");
  report.heldOpen = holds.length;
  byId.get("search-input").value = process.env.NEXT_QUERY;
  fire(byId.get("search-form"), "submit");
  await settle();
  report.searches = searches();
  report.beforeRelease = cards();
  for (const release of holds.splice(0)) release();
  await settle();
  report.afterRelease = cards();
  report.clicked = clicked && { connected: clicked.isConnected, status: clicked.querySelector(".card-action-status")?.textContent ?? null };
  report.next = await step(target, "like");
}
report.errors = errors;
process.stdout.write(JSON.stringify(report) + "\n", () => process.exit(0));
"""


def _bundle(entry: Path, out: Path) -> Path:
    run = subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    (out / "runner.mjs").write_text(RUNNER)
    return out


@pytest.fixture(scope="module")
def search_bundle(tmp_path_factory) -> Path:
    return _bundle(ENTRY, tmp_path_factory.mktemp("search"))


def _run(bundle: Path, scenario: str, storage: dict, query: str, pages: dict, target: str, next_query: str = "") -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "STORAGE": json.dumps(storage), "SEARCH": f"?q={query}",
             "PAGES": json.dumps(pages), "SCENARIO": scenario, "TARGET": target, "NEXT_QUERY": next_query, "HOLD_ACTION": "1" if scenario == "reset" else "0"},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


def _row(tag: str) -> dict:
    return {"video_id": tag, "video_uuid": f"uuid-{tag}", "instance_domain": "peer.example", "title": f"video {tag}"}


def _keyless(tag: str) -> dict:
    # No uuid and no id: the row has no video key, so the card has nothing to act on.
    return {"video_id": None, "video_uuid": None, "instance_domain": "peer.example", "title": f"keyless {tag}"}


def _key(row: dict) -> str | None:
    return f"{row['instance_domain']}::{row['video_uuid']}" if row["video_uuid"] else None


def _sent(action: str, row: dict) -> dict:
    return {"method": "POST", "action": action, "uuid": row["video_uuid"], "host": row["instance_domain"]}


def _marks(card: dict) -> tuple:
    return card["likesActive"], card["likePressed"], card["dislikesActive"], card["dislikePressed"]


NEUTRAL = (False, "false", False, "false")
LIKED = (True, "true", False, "false")
DISLIKED = (False, "false", True, "true")
QUERY = "music"
PAGE_1 = [_row("a1"), _keyless("k1"), _row("a2")]
PAGE_2 = [_row("b1"), _row("b2"), _keyless("k2")]
TOTAL = len(PAGE_1) + len(PAGE_2)


def test_keyed_cards_on_both_pages_carry_the_controls_and_like_and_dislike_toggle_and_redraw_the_card_in_place(search_bundle):
    target = PAGE_2[1]
    page = _run(search_bundle, "paged", {PROFILE_KEY: KEY}, QUERY, {QUERY: [{"rows": PAGE_1, "total": TOTAL}, {"rows": PAGE_2, "total": TOTAL}]}, _key(target))

    # control: page 1 loaded on its own and page 2 only when the sentinel came into view, and both pages' cards are in the grid in row order with the keyless rows carrying no key
    assert page["searches"] == [[QUERY, "1"], [QUERY, "2"]], page["searches"]
    assert [(c["key"], c["title"]) for c in page["grid"]] == [(_key(r), r["title"]) for r in PAGE_1 + PAGE_2], page["grid"]
    # A page that renders without actions leaves every list empty; one that passes actions only on the reset path leaves page 2's empty.
    assert {c["key"]: c["actions"] for c in page["grid"] if c["key"]} == {_key(r): ACTIONS for r in PAGE_1 + PAGE_2 if _key(r)}, page["grid"]  # C1
    assert [c["actions"] for c in page["grid"] if not c["key"]] == [[], []], page["grid"]  # C1: keyless cards on both pages stay bare
    assert all(_marks(c) == NEUTRAL for c in page["grid"] if c["key"]), page["grid"]  # control: no card starts marked

    # Dislike, Dislike, Dislike, Like, Like on a page-2 card: each click sends the toggle of the card's current mark and the card is redrawn with the new mark.
    expected = [("dislike", DISLIKED), ("undo_dislike", NEUTRAL), ("dislike", DISLIKED), ("like", LIKED), ("undo_like", NEUTRAL)]
    others = [c for c in page["grid"] if c["key"] != _key(target)]
    for step, (action, marks) in zip(page["steps"], expected, strict=True):
        assert step["pressed"] is True, step  # control: the icon to click exists on the current card
        # A Dislike that always sends dislike, or a Like on a disliked card that sends undo_like, fails here.
        assert step["sent"] == [_sent(action, target)], (step, page["errors"])  # C2
        # A page that sends but does not redraw keeps the previous mark; one that redraws from a stale reaction shows the wrong one.
        assert _marks(step["card"]) == marks, (step["action"], step["card"], page["errors"])  # C2
        assert step["card"]["actions"] == ACTIONS, step["card"]  # C2: the redraw keeps the controls
        # In place: same position in the grid, and no other card changed.
        assert [c["key"] for c in step["grid"]] == [c["key"] for c in page["grid"]], step["grid"]  # C2
        assert [c for c in step["grid"] if c["key"] != _key(target)] == others, step["grid"]  # C2
    assert page["errors"] == [], page["errors"]


def test_a_keyless_like_is_sent_stored_in_the_local_likes_and_shown_on_the_card(search_bundle):
    target = PAGE_1[0]
    page = _run(search_bundle, "keyless", {}, QUERY, {QUERY: [{"rows": PAGE_1, "total": len(PAGE_1)}]}, _key(target))

    assert page["storedBefore"] is None, page  # control: the browser holds no like before the click
    assert page["like"]["pressed"] is True, page["grid"]  # control: a keyless visitor's keyed card has a Like button
    # A page that asks for a profile before liking sends nothing.
    assert page["like"]["sent"] == [_sent("like", target)], (page["like"], page["errors"])  # C2
    assert json.loads(page["stored"] or "null") == [{"video_uuid": target["video_uuid"], "instance_domain": target["instance_domain"]}], page["stored"]  # C2
    assert _marks(page["like"]["card"]) == LIKED, page["like"]["card"]  # C2: redrawn from the local likes
    assert page["errors"] == [], page["errors"]


def test_a_like_resolving_after_a_new_search_replaced_the_grid_leaves_the_new_cards_and_rows_alone(search_bundle):
    first = [_row("a1"), _row("a2"), _row("a3")]
    second = [_row("c1"), _row("a2"), _row("c2")]  # a2 is in both searches
    shared = first[1]
    page = _run(search_bundle, "reset", {PROFILE_KEY: KEY}, "first",
                {"first": [{"rows": first, "total": len(first)}], "second": [{"rows": second, "total": len(second)}]}, _key(shared), next_query="second")

    # control: the Like left, and its response is held while the second search loads and replaces the grid
    assert page["held"]["sent"] == [_sent("like", shared)] and page["heldOpen"] == 1, (page["held"], page["errors"])
    assert page["searches"] == [["first", "1"], ["second", "1"]], page["searches"]
    assert [c["key"] for c in page["beforeRelease"]] == [_key(r) for r in second], page["beforeRelease"]
    assert page["clicked"]["connected"] is False, page["clicked"]  # control: the clicked card is detached when the Like resolves

    # Redrawing the detached card throws; a page that does not check for that reports the error on the clicked card or lets it escape.
    assert page["errors"] == [], page["errors"]  # C2
    assert page["clicked"]["status"] == "", page["clicked"]  # C2
    # The resolved Like does not reach the new grid: it holds the second search's cards, a2 unmarked as that search returned it.
    assert [c["key"] for c in page["afterRelease"]] == [_key(r) for r in second], page["afterRelease"]  # C2
    assert all(_marks(c) == NEUTRAL for c in page["afterRelease"]), page["afterRelease"]  # C2
    # A row list the reset did not clear still holds the first search's a2, now marked liked, which the lookup finds first and so sends undo_like.
    assert page["next"]["sent"] == [_sent("like", shared)], (page["next"], page["errors"])  # C2
    assert _marks(page["next"]["card"]) == LIKED, page["next"]["card"]  # C2

```


Gate: satisfied

## 2026-10-01 - Step 7 - Phase 2 (Search card controls and Like/Dislike toggles) - red (audit round 1)

`tests/tmp/test_40_search_card_actions_phase2.py` exited 1.

```
  tests/tmp/test_40_search_card_actions_phase2.py  3 failed                               0.0s
  -----------------------------------------------
  total                                            3 failed                               1.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 2 (Search card controls and Like/Dislike toggles) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 1 UNCARRIED clause(s) - C2f; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
`test_keyed_cards_on_both_pages_carry_the_controls_and_like_and_dislike_toggle_and_redraw_the_card_in_place` fails at line 306 (`assert {c["key"]: c["actions"] for c in page["grid"] if c["key"]} == {_key(r): ACTIONS ...}`). The keyed cards' `actions` lists come back `[]`, because `renderRows` in `pages/search/index.ts:208` calls `renderVideoCard(row, { apiParam, reaction: cardReaction(row) })` without `actions: true`. The other two tests fail on the same cause: the second at line 332 and the third at line 348.

NOT ASSESSED
1. `code_under_test` listed `tests/tmp/test_frontend_search_card_actions.py`, which does not exist. Nothing the test under audit uses depends on it. The stub question was answered from `pages/search/index.ts`, `components/video-card.ts` and the test's own runner.
2. `fixtures_path` was not supplied. The only fixture the test uses, `search_bundle`, is defined in the test file itself (lines 253–255), so no conftest was needed.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (34 clauses: 9 must_prove, 17 docstring, 8 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | every keyed card on the first page has the four `[data-card-action]` controls | :306 | the page passing no `actions`, or a card missing any of like/dislike/channel/account (exact ordered list per key) | CARRIED |
| C1b | must_prove | every keyed card on an appended page has the four controls | :306 | actions passed only on the reset path, so page-2 cards from `insertAdjacentHTML` stay bare (b1, b2 keys in the expected map; :303 shows page 2 was appended) | CARRIED |
| C1c | must_prove | a keyless card has none | :307 | controls rendered on a card with no video key, on either page | CARRIED |
| C2a | must_prove | a Like click sends the toggled reaction | :316 | always sending `like`; sending `undo_like` on a disliked card (step 4 expects `like`, step 5 `undo_like`) | CARRIED |
| C2b | must_prove | a Dislike click sends the toggled reaction | :316 | always sending `dislike` (step 2 expects `undo_dislike`), or the wrong uuid/host | CARRIED |
| C2c | must_prove | re-renders that card with the new mark | :318 | sending without redrawing (the previous mark stays); redrawing from a stale reaction | CARRIED |
| C2d | must_prove | in place | :321, :322 | the redrawn card appended at the end or moved; a neighbouring card's state changed | CARRIED |
| C2e | must_prove | a Like does not throw when a reset replaced the grid mid-request | :356 (control :353) | `outerHTML` set on the detached card, which the fake throws on at :108 | CARRIED |
| C2f | must_prove | a Dislike does not throw when a reset replaced the grid mid-request | none | nothing: the reset scenario clicks only Like (:224, :235) | UNCARRIED |
| D1 | docstring | "carry the card controls on every loaded page" | :306 | page-2 cards without controls | CARRIED |
| D2 | docstring | "Like and Dislike on one toggle the reaction and redraw that card in place" | :316, :318, :321 | a non-toggling send, no redraw, a moved card | CARRIED |
| D3 | docstring | "every keyed card has the like, dislike, channel and account buttons, and the keyless card on each page has none" | :306, :307 | any member of the set missing; controls on keyless cards k1/k2 | CARRIED |
| D4 | docstring | "Dislike×3, Like×2 send dislike, undo_dislike, dislike, like, undo_like for that video" | :316 | a wrong action at any step, or the wrong video | CARRIED |
| D5 | docstring | "disliked … then neutral, then disliked, then liked and not disliked, then neutral" (stat active + aria-pressed) | :318 | a missing stat class or aria-pressed; liked and disliked both set | CARRIED |
| D6 | docstring | "stays at its position with its four controls" | :321, :319 | a reorder; a redraw that drops `actions` | CARRIED |
| D7 | docstring | "no other card changes" | :322 | a change to any other card's key, title, controls or marks | CARRIED |
| D8 | docstring | "Without a key, the keyed cards carry the same four controls and the keyless card none" | :332 | controls only for a profile holder | CARRIED |
| D9 | docstring | "Like sends `like`" (no key) | :335 | asking for a profile and sending nothing | CARRIED |
| D10 | docstring | "`localLikes:v1` then holds the video" | :336 (control :330) | not storing, or storing the wrong video | CARRIED |
| D11 | docstring | "the card shows liked" (no key) | :337 | no redraw from the local likes | CARRIED |
| D12 | docstring | "the first search's cards carry the four controls" | :348 | the reset render without actions | CARRIED |
| D13 | docstring | "resolves without an error escaping" | :356 | a throw from the detached-card redraw | CARRIED |
| D14 | docstring | "without writing an error into the clicked card's status line" | :357 | catching the throw and reporting it on the card | CARRIED |
| D15 | docstring | "The grid holds the new search's cards, all unmarked" | :359, :360 | the resolved Like redrawing into, or marking, the new grid | CARRIED |
| D16 | docstring | "a following Like on the shared video sends `like`, not `undo_like`" | :362, :363 | a row list the reset did not clear | CARRIED |
| D17 | docstring | "The fake DOM throws when outerHTML is set on an element with no parent" | :108 (harness) | a statement about the harness, made true by construction | CARRIED |
| N1 | name | "keyed cards on both pages carry the controls" | :306 | page-2 cards without controls | CARRIED |
| N2 | name | "like and dislike toggle" | :316 | a non-toggling send | CARRIED |
| N3 | name | "and redraw the card in place" | :318, :321, :322 | no redraw; a moved card | CARRIED |
| N4 | name | "a keyless like is sent" | :335 | nothing sent without a profile | CARRIED |
| N5 | name | "stored in the local likes" | :336 | no local store write | CARRIED |
| N6 | name | "and shown on the card" | :337 | the card left unmarked | CARRIED |
| N7 | name | "a like resolving after a new search replaced the grid leaves the new cards … alone" | :359, :360 | the stale Like marking or replacing a new card | CARRIED |
| N8 | name | "… and rows alone" | :362 | a leftover first-search row causing `undo_like` | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:224
   `report.held = await step(target, "like");`
   C2 says "A Like **or Dislike** click … without throwing when a reset replaced the grid mid-request". That names a set of two, and the whole-claim principle says a set gets an assertion for every member. The reset scenario only sends a Like, at :224 and again at :235, so :356 and :357 cover only the Like path. Some wrong implementations would still pass. One is a page whose Dislike branch redraws through `card.outerHTML` without checking whether the card is still connected, while its Like branch does check. That shape is realistic: the precedent `pages/videos/index.ts:415-422` handles like and dislike in separate branches. To cover C2f, the test needs a Dislike held across a reset, with errors and the clicked card's status asserted the same way. The other option is an operator exemption for C2f.

RECOMMENDATIONS
1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:166-169
   The stub always returns 200 for `/api/user-action`. A refused reaction request is never tested: what the card shows, what the status line says, and whether the mark stays unchanged. The same goes for a visitor with no profile key pressing Dislike. `must_prove` does not claim either case, so neither blocks.
2. bounds (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:272-274
   The only keyless row has neither a uuid nor an id. The other ways a row can lack a key are untested: a uuid with no `instance_domain`, or a `video_id` with no `video_uuid`. `resolveVideoKey` treats the second one as keyed, and `_key` at :277-278 would not.
3. name-as-sentence (rules/testing.md): tests/tmp/test_40_search_card_actions_phase2.py:326
   In this name, "keyless" means a visitor with no profile key. At :307 and in C1, "keyless" means a card whose row has no video key. A failure in the runner output would read ambiguously; "a like without a profile key …" would not.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not resolve (no match under tests/). Nothing in it was assessed.
2. The supplied client/frontend/src/pages/search/index.ts contains no card-action handler. I judged what the page's markup and actions would be from the shared `components/video-card.ts`, `data/reactions.ts`, and the `pages/videos/index.ts` precedent.

## 2026-10-01 - Step 7 - Phase 2 (Search card controls and Like/Dislike toggles) - self-check (audit round 2, send-back 0)

`tests/tmp/test_40_search_card_actions_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_40_search_card_actions_phase2.py:306 — every keyed card on page 1 and on the appended page 2 has exactly the [data-card-action] buttons like, dislike, channel, account. Also :307 — the keyless card on each page has none. The keyless-visitor render at :332 and the fresh-search render at :349 (both parametrized cases) show the same. - expected: {a1, a2, b1, b2 keys: ["like","dislike","channel","account"]} at :306; [[], []] for k1 and k2 at :307. - excludes: The current page (renderRows with no `actions`): every list reads [] and the test fails at :306, observed. A page that passes `actions` only on the reset path leaves b1 and b2 with [] at :306. A page that draws controls on keyless rows gives a non-empty list at :307.
- C2 - tests/tmp/test_40_search_card_actions_phase2.py:316 — each of Dislike, Dislike, Dislike, Like, Like on page-2 card b2 sends one POST /api/user-action with that click's toggled action and b2's uuid and host. :318 — after each click the card shows the new mark (stat active + aria-pressed). :319 — the redrawn card keeps its four controls. :321 and :322 — card order is unchanged and no other card changes (in place). :335, :336 and :337 — a keyless Like sends `like`, is stored in localLikes:v1 and shows liked. :357 and :358 in both the `[like]` and `[dislike]` cases of the reset test — after a Like or a Dislike whose response resolved after a new search detached the card, no error escaped and the clicked card's status line is "". :360 and :361 — the new grid is the second search's cards, all unmarked. :363 and :364 — the following same-reaction click sends `like`/`dislike` and the card shows LIKED/DISLIKED. - expected: Toggle actions: dislike, undo_dislike, dislike, like, undo_like. Marks: DISLIKED, NEUTRAL, DISLIKED, LIKED, NEUTRAL. Grid order and the other cards are unchanged. Reset case, for each of like and dislike: errors [], status "", afterRelease c1/a2/c2 all NEUTRAL, next sent [like] or [dislike] with mark LIKED or DISLIKED (observed under the plan's draft bundle). - excludes: An always-`dislike` Dislike fails :316 at step 2. A Like that sends `undo_like` on a disliked card fails :316 at step 4. Sending without redrawing keeps the old mark and fails :318. A redraw that appends the card moves it and fails :321. A Dislike branch that sets `card.outerHTML` without an `isConnected` guard, while the Like branch has one, fails `[dislike]` at :358 with status "NoModificationAllowedError: This element has no parent node." (observed; `[like]` passes). The mirror mutant fails only `[like]` at :358 (observed). A reset that does not clear `state.rows` makes the next click send `undo_like` or `undo_dislike` and fails :363 in both cases (observed).

<exemptions>
none
</exemptions>

<items>
<item id="C2f">
<disposition>fixed</disposition>
<what>The reset test is now parametrized over `("action", "mark")`, with values `("like", LIKED)` and `("dislike", DISLIKED)`, and is renamed `test_a_like_or_dislike_resolving_after_a_new_search_replaced_the_grid_leaves_the_new_cards_and_rows_alone`. The runner reads the reaction from a new `ACTION` env, which `_run(..., action=)` passes through. It uses that reaction for the held click (:224) and for the following click (:235). This means the Dislike case holds a `dislike` response while the second search replaces the grid. In that case :357 (`errors == []`) and :358 (the clicked card's status line is `""`) carry "a Dislike does not throw". The control at :354 shows the card is detached when the Dislike resolves, and the control at :351 shows the Dislike was sent and its response was held. The wrong implementation this excludes is a page that guards the Like branch with `card.isConnected` but sets `card.outerHTML` unguarded in the Dislike branch. I observed it in a probe bundle (plan draft with only the Dislike guard removed): the `[dislike]` case failed at :358 with status "NoModificationAllowedError: This element has no parent node.", and the `[like]` case passed. The docstring bullet now says "a Like, or in a second run a Dislike" and "sends `like` or `dislike`, not the `undo_like` or `undo_dislike`", so it matches what the test asserts.</what>
</item>
</items>

<findings_addressed>
Claim CRITICAL 1 (whole-claim: the reset scenario clicks only Like, so C2f is uncarried): the reset test is now parametrized over Like and Dislike. In the `[dislike]` case, :357 and :358 assert that no error escaped and the clicked card's status is empty after a Dislike held across a reset. A probe showed a Dislike-branch-only missing guard fails `[dislike]` at :358 while `[like]` passes, and the reverse mutant fails only `[like]`. Recommendations 1–3 were not taken: they do not block, and the refused-request and no-profile-Dislike cases are phase 4's checkpoint.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_40_search_card_actions_phase2.py:306 — every keyed card on page 1 and on the appended page 2 has exactly the [data-card-action] buttons like, dislike, channel, account. Also :307 — the keyless card on each page has none. The keyless-visitor render at :332 and the fresh-search render at :349 (both parametrized cases) show the same.</assertion>
<expected>{a1, a2, b1, b2 keys: ["like","dislike","channel","account"]} at :306; [[], []] for k1 and k2 at :307.</expected>
<wrong_implementation>The current page (renderRows with no `actions`): every list reads [] and the test fails at :306, observed. A page that passes `actions` only on the reset path leaves b1 and b2 with [] at :306. A page that draws controls on keyless rows gives a non-empty list at :307.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_40_search_card_actions_phase2.py:316 — each of Dislike, Dislike, Dislike, Like, Like on page-2 card b2 sends one POST /api/user-action with that click's toggled action and b2's uuid and host. :318 — after each click the card shows the new mark (stat active + aria-pressed). :319 — the redrawn card keeps its four controls. :321 and :322 — card order is unchanged and no other card changes (in place). :335, :336 and :337 — a keyless Like sends `like`, is stored in localLikes:v1 and shows liked. :357 and :358 in both the `[like]` and `[dislike]` cases of the reset test — after a Like or a Dislike whose response resolved after a new search detached the card, no error escaped and the clicked card's status line is "". :360 and :361 — the new grid is the second search's cards, all unmarked. :363 and :364 — the following same-reaction click sends `like`/`dislike` and the card shows LIKED/DISLIKED.</assertion>
<expected>Toggle actions: dislike, undo_dislike, dislike, like, undo_like. Marks: DISLIKED, NEUTRAL, DISLIKED, LIKED, NEUTRAL. Grid order and the other cards are unchanged. Reset case, for each of like and dislike: errors [], status "", afterRelease c1/a2/c2 all NEUTRAL, next sent [like] or [dislike] with mark LIKED or DISLIKED (observed under the plan's draft bundle).</expected>
<wrong_implementation>An always-`dislike` Dislike fails :316 at step 2. A Like that sends `undo_like` on a disliked card fails :316 at step 4. Sending without redrawing keeps the old mark and fails :318. A redraw that appends the card moves it and fails :321. A Dislike branch that sets `card.outerHTML` without an `isConnected` guard, while the Like branch has one, fails `[dislike]` at :358 with status "NoModificationAllowedError: This element has no parent node." (observed; `[like]` passes). The mirror mutant fails only `[like]` at :358 (observed). A reset that does not clear `state.rows` makes the next click send `undo_like` or `undo_dislike` and fails :363 in both cases (observed).</wrong_implementation>
</row>
</rows>

<answers>
1. No. Each negative assertion has a positive control. :357 and :358 (no error, empty status) are armed by :351, which shows the reaction was sent and is still held, and by :354, which shows the card is detached when it resolves. The probe confirmed that removing either branch's guard turns :358 red for its own case. :361 (all unmarked) sits next to :363 and :364, which show the next click sends and marks. :307 is armed by :306 and :304.
2. No. Expected actions and marks are literal toggles (`_sent(action, shared)`, LIKED/DISLIKED). Nothing is computed by reproducing production logic. Deleting the `isConnected` guard on the Dislike branch turns `[dislike]`:358 red. Deleting `state.rows = []` in loadPage's reset turns :363 red in both cases.
3. No. The reset path is now read for both members of the {Like, Dislike} set. The paged toggle is read across five steps that cover every transition.
4. No. Fetch, IntersectionObserver and the DOM are stubbed at the browser boundary. The project's own modules (video-card, reactions, user-actions, search data) are bundled in for real.
5. Yes, it collects. `_run` gained an `action` keyword with a default, so the paged and keyless callers are unchanged. The parametrize names match the function parameters. Running the file collects 4 tests (2 + the 2 reset cases), as written.
6. Yes, every expected value comes from a run. The new `[dislike]` values (held sent [dislike], heldOpen 1, clicked {connected false, status ""}, afterRelease all NEUTRAL, next sent [dislike] with marks (False,'false',True,'true')) were observed in a probe that bundled the plan's draft into a symlinked copy of src. The same probe ran the current page and three mutants. The probe file is now emptied with a delete-me note. Still not observed, as in the previous round: whether a real browser throws on outerHTML of a detached element. Running `document.createElement("div").outerHTML = "<p>"` in Chrome would confirm it.
7. Yes, it is still red for its own reason. Against the current tree there are 4 failures: paged at :306, keyless at :332, and both reset cases at :349. All are the C1 controls-missing assertion, because renderRows passes no `actions`. Under the plan's draft, both reset cases pass.
</answers>

Gate: satisfied

## 2026-10-01 - Step 7 - Phase 2 (Search card controls and Like/Dislike toggles) - red (audit round 2)

`tests/tmp/test_40_search_card_actions_phase2.py` exited 1.

```
  tests/tmp/test_40_search_card_actions_phase2.py  4 failed                               0.0s
  -----------------------------------------------
  total                                            4 failed                               2.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 2 (Search card controls and Like/Dislike toggles) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
`test_keyed_cards_on_both_pages_carry_the_controls_and_like_and_dislike_toggle_and_redraw_the_card_in_place` fails at line 306 on the `{c["key"]: c["actions"] ...} == {_key(r): ACTIONS ...}` assertion. Every keyed card's `actions` list is `[]`, because `renderRows` in `client/frontend/src/pages/search/index.ts:208` calls `renderVideoCard` without `actions: true`. The keyless test fails at line 332 and both reset parametrizations fail at line 349, all for that same reason.

NOT ASSESSED
1. `code_under_test` listed `tests/tmp/test_frontend_search_card_actions.py`, which does not resolve. The stub question was answered from `index.ts`, `components/video-card.ts`, `data/reactions.ts` and the test's own assertions.
2. Notes on the passes, with no finding raised:
   - **Anti-pattern pass.** No `.md` file is read, so `doc-lint-grep`, `section-scoped-substring-grep` and `whole-file-source-name-grep` don't apply.
   - **`hardcoded-spec-mirror`.** The `ACTIONS`, `NEUTRAL`, `LIKED` and `DISLIKED` literals are checked against the DOM the page renders, not against a code constant.
   - **`tautological-assertion`.** The test's `_key` (line 277) writes out the `host::uuid` format itself. It doesn't import or call `resolveVideoKey`, so a change to the production format would turn the test red.
   - **`absence-only-assertion`.** The negative assertions each sit in the same test as a positive control: lines 307 and 306, line 357 and line 351, lines 358/361 and lines 363–364.
   - **`echoed-literal`.** Each `_sent(...)` expectation is only met if the page's click handler builds and sends the request. If that handler is missing, lines 316, 335, 351 and 363 go red.
   - **`single-value-pin`.** The toggle runs through five steps (dislike, undo, dislike, like, undo) and two reset parametrizations, so the observed marks have to follow each input.
   - **Ladder pass.** The test runs the real bundle in node and asserts on outgoing requests, localStorage and the redrawn DOM. That is direct behaviour invocation (rung 1), the highest rung for a browser page. There is no downshift, so no comment is needed, and the test is not on the anti-rung.
   - **Stub question.** Each wrong implementation fails a specific assertion:
     - Controls rendered with no click handler: line 316.
     - A Dislike that always sends `dislike`: step 2 at line 316.
     - A request sent but the card not redrawn: line 318.
     - A redraw that moves the card or touches other cards: lines 321–322.
     - An `outerHTML` redraw with no detached check: line 357.
     - A row list the reset didn't clear: line 363.
     - The code as it stands: line 306.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (34 clauses: 9 must_prove, 17 docstring, 8 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | every keyed card on the first page has the four `[data-card-action]` controls | :306 | the page passing no `actions`, or a card missing any of like/dislike/channel/account (exact ordered list per key) | CARRIED |
| C1b | must_prove | every keyed card on an appended page has the four controls | :306 (control :303) | actions passed only on the reset path, so page-2 cards from `insertAdjacentHTML` stay bare (b1, b2 in the expected map) | CARRIED |
| C1c | must_prove | a keyless card has none | :307 | controls rendered on a card with no video key, on either page | CARRIED |
| C2a | must_prove | a Like click sends the toggled reaction | :316 | always sending `like`; sending `undo_like` on a disliked card (step 4 expects `like`, step 5 `undo_like`) | CARRIED |
| C2b | must_prove | a Dislike click sends the toggled reaction | :316 | always sending `dislike` (step 2 expects `undo_dislike`), or the wrong uuid/host | CARRIED |
| C2c | must_prove | re-renders that card with the new mark | :318 | sending without redrawing (the previous mark stays); redrawing from a stale reaction | CARRIED |
| C2d | must_prove | in place | :321, :322 | the redrawn card appended at the end or moved; a neighbouring card's state changed | CARRIED |
| C2e | must_prove | a Like does not throw when a reset replaced the grid mid-request | :357 `[like]` (control :354) | `outerHTML` set on the detached card, which the fake throws on at :108 | CARRIED |
| C2f | must_prove | a Dislike does not throw when a reset replaced the grid mid-request | :357 `[dislike]` (control :351, :354) | an unguarded redraw on the Dislike branch: the parametrisation at :341 now drives `ACTION=dislike` through the reset scenario (:224, :235), so a throw reaches `errors` | CARRIED |
| D1 | docstring | "carry the card controls on every loaded page" | :306 | page-2 cards without controls | CARRIED |
| D2 | docstring | "Like and Dislike on one toggle the reaction and redraw that card in place" | :316, :318, :321 | a non-toggling send, no redraw, a moved card | CARRIED |
| D3 | docstring | "every keyed card has the like, dislike, channel and account buttons, and the keyless card on each page has none" | :306, :307 | any member of the set missing; controls on keyless cards k1/k2 | CARRIED |
| D4 | docstring | "Dislike×3, Like×2 send dislike, undo_dislike, dislike, like, undo_like for that video" | :316 | a wrong action at any step, or the wrong video | CARRIED |
| D5 | docstring | "disliked … then neutral, then disliked, then liked and not disliked, then neutral" (stat active + aria-pressed) | :318 | a missing stat class or aria-pressed; liked and disliked both set | CARRIED |
| D6 | docstring | "stays at its position with its four controls" | :321, :319 | a reorder; a redraw that drops `actions` | CARRIED |
| D7 | docstring | "no other card changes" | :322 | a change to any other card's key, title, controls or marks | CARRIED |
| D8 | docstring | "Without a key, the keyed cards carry the same four controls and the keyless card none" | :332 | controls only for a profile holder | CARRIED |
| D9 | docstring | "Like sends `like`" (no key) | :335 | asking for a profile and sending nothing | CARRIED |
| D10 | docstring | "`localLikes:v1` then holds the video" | :336 (control :330) | not storing, or storing the wrong video | CARRIED |
| D11 | docstring | "the card shows liked" (no key) | :337 | no redraw from the local likes | CARRIED |
| D12 | docstring | "the first search's cards carry the four controls" | :349 | the reset render without actions | CARRIED |
| D13 | docstring | "resolves without an error escaping" (now "a Like, or in a second run a Dislike") | :357 | a throw from the detached-card redraw, on either branch | CARRIED |
| D14 | docstring | "without writing an error into the clicked card's status line" | :358 | catching the throw and reporting it on the card | CARRIED |
| D15 | docstring | "The grid holds the new search's cards, all unmarked" | :360, :361 | the resolved reaction redrawing into, or marking, the new grid | CARRIED |
| D16 | docstring | "a following click of the same reaction … sends `like` or `dislike`, not the `undo_like` or `undo_dislike`" | :363, :364 | a row list the reset did not clear | CARRIED |
| D17 | docstring | "The fake DOM throws when outerHTML is set on an element with no parent" | :108 (harness) | a statement about the harness, made true by construction | CARRIED |
| N1 | name | "keyed cards on both pages carry the controls" | :306 | page-2 cards without controls | CARRIED |
| N2 | name | "like and dislike toggle" | :316 | a non-toggling send | CARRIED |
| N3 | name | "and redraw the card in place" | :318, :321, :322 | no redraw; a moved card | CARRIED |
| N4 | name | "a keyless like is sent" | :335 | nothing sent without a profile | CARRIED |
| N5 | name | "stored in the local likes" | :336 | no local store write | CARRIED |
| N6 | name | "and shown on the card" | :337 | the card left unmarked | CARRIED |
| N7 | name | "a like (now: like or dislike) resolving after a new search replaced the grid leaves the new cards … alone" | :360, :361 | the stale reaction marking or replacing a new card | CARRIED |
| N8 | name | "… and rows alone" | :363 | a leftover first-search row causing `undo_like` / `undo_dislike` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase2.py:341
   The author resolved C2f by adding an assertion, not by narrowing the prose. The reset test is now parametrised over `("like", LIKED), ("dislike", DISLIKED)`, and :357 runs under each. The docstring (:8) and the test name (:342) were widened to match: D13–D16 and N7–N8 now claim both reactions, and the parametrisation carries each of them for both.
2. bounds / normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase2.py:326
   The keyless scenario clicks only Like. No test covers Dislike without a profile key. No docstring sentence and no `must_prove` clause claims that path, so nothing here is uncarried. This is a gap in coverage, not a claim defect, and no ledger row names it.

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not resolve (Glob found no match). Nothing was judged against it.
2. The click wiring, the `actions` option and the `.card-action-status` element are not in client/frontend/src/pages/search/index.ts as read. They would come from `components/video-card` and `data/reactions`, and those were not supplied in `code_under_test` or read. The excludes column was judged from the test and its fake DOM harness, not from those modules.

## 2026-10-01 - Step 7 - Phase 2 (Search card controls and Like/Dislike toggles) - checkpoint outcome (run 1)

`tests/tmp/test_40_search_card_actions_phase2.py` exited 0 after the phase landed.

<changes>
### client/frontend/src/pages/search/index.ts
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none. The phase also lists `tests/tmp/test_frontend_search_card_actions.py (EDITED)`, but that file does not exist. The checkpoint gating this phase is `tests/tmp/test_40_search_card_actions_phase2.py` (phase 1 had the same mismatch), so I did not create it.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_40_search_card_actions_phase2.py  4 passed                               0.0s
  -----------------------------------------------
  total                                            4 passed                               2.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 3 (Block removes the source's loaded cards) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
In `pages/search/index.ts`, blocking a channel or account from a search card removes every loaded card of that source, unless the dislike that follows the block fails.

- C1 - A successful block followed by a successful dislike removes every loaded card of that channel or account, refills the viewport and leaves the status text unchanged.
- C2 - A block whose dislike fails reports `Blocked <label|action>, but the dislike failed: <msg>` and removes no card.

must_prove:
- C1 - A successful block followed by a successful dislike removes every loaded card of that channel or account, refills the viewport and leaves the status text unchanged.
- C2 - A block whose dislike fails reports `Blocked <label|action>, but the dislike failed: <msg>` and removes no card.

## 2026-10-01 - Step 7 - Phase 3 (Block removes the source's loaded cards) - self-check (audit round 1, send-back 0)

`tests/tmp/test_40_search_card_actions_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_40_search_card_actions_phase3.py:290 — after the click on Block channel/account of card a1, the requests sent are exactly POST /api/profile/blocks {kind, uuid-a1, peer.example}, then POST /api/user-action {dislike, uuid-a1, peer.example}, then GET /api/v1/search/videos q=music page=3 - expected: [["POST","/api/profile/blocks",{"kind":kind,"uuid":"uuid-a1","host":"peer.example"}],["POST","/api/user-action",{"action":"dislike","uuid":"uuid-a1","host":"peer.example"}],["GET","/api/v1/search/videos","music","3"]]. In the current run it reads [], because the click sends nothing yet. - excludes: No Block branch in the click handler: reads [] (seen in this run). Block with no dislike, or the dislike sent first: the sequence is short or out of order. Removal with no refill check: page 3 is missing even though the sentinel is in view. The run showed that turning the sentinel visible does not fetch page 3 by itself.
- C1 - tests/tmp/test_40_search_card_actions_phase3.py:292 — the grid titles after the block are the loaded cards not of that source, in order - expected: channel: ["video a2","video k1","video a3","video b2"]; account: ["video k1","video a3","video b2"]. In the current run all 7 titles are still there. - excludes: Removing only the clicked card keeps b1 and k2. Matching on channel_id alone also drops a3 (other.example, channel 7). Using the wrong field for the kind keeps a2 under account, or drops it under channel. Skipping keyless cards keeps k2.
- C1 - tests/tmp/test_40_search_card_actions_phase3.py:294 — #search-status after the block and the empty page-3 refill - expected: "Showing 7 of 9 matched videos.", the value observed before the click in this run (control at _control_before) - excludes: Recounting the status from the cards left gives "Showing 4 of 9…" or "Showing 3 of 9…". Writing a block message into the status line replaces the text. Lines 290 and 292 above show the block path ran, so this check cannot pass because nothing happened.
- C1 - tests/tmp/test_40_search_card_actions_phase3.py:295 — no listener threw and no rejection went unhandled - expected: [] - excludes: Rendering into a removed card through outerHTML throws NoModificationAllowedError in the fake DOM, as Chromium does. A refill that awaits a rejected promise records an unhandled rejection.
- C2 - tests/tmp/test_40_search_card_actions_phase3.py:304 — the clicked card's .card-action-status text when the dislike returns 500 - expected: "Blocked Alice's channel, but the dislike failed: reaction store unavailable" (label given); "Blocked account, but the dislike failed: reaction store unavailable" (empty label). In the current run it reads "". - excludes: Reporting only the dislike error gives "reaction store unavailable". Reporting nothing gives "" (this run). Using the empty label as-is gives "Blocked , but…". Treating the 500 as a block failure gives a different message.
- C2 - tests/tmp/test_40_search_card_actions_phase3.py:308 — the grid after the failed dislike, which line 306 shows was sent after an accepted block - expected: ["video a1","video a2","video k1","video a3","video b1","video b2","video k2"] - excludes: Removing the source's cards whatever the dislike returned leaves 4 cards (channel) or 3 (account). Removing only the clicked card drops "video a1".
- C2 - tests/tmp/test_40_search_card_actions_phase3.py:309 — no listener threw and no rejection went unhandled on the failure path - expected: [] - excludes: Letting the dislike's error escape the click handler, instead of writing it on the card, shows up as an unhandled rejection or uncaught exception here.

<assertions>
tests/tmp/test_40_search_card_actions_phase3.py:274-277 — control (`_control_before`, run by every test): before the click, only search pages 1 and 2 have been fetched, the grid holds all 7 loaded cards (a1 a2 k1 a3 b1 b2 k2) in order, `#search-status` reads `Showing 7 of 9 matched videos.`, and the clicked card has the button for the action — control
tests/tmp/test_40_search_card_actions_phase3.py:290 — after Block channel or Block account on page-1 card a1, the requests in order are exactly: `POST /api/profile/blocks` {kind, uuid, host}, then `POST /api/user-action` with `dislike` for that video, then `GET` search page 3. The sentinel only counts as in view from the click on, so the page-3 fetch shows the page refilled itself after the removal — C1
tests/tmp/test_40_search_card_actions_phase3.py:292 — the grid ends up as exactly the cards outside the source, in order. For a channel block that is a2 k1 a3 b2: page-2 card b1 and keyless card k2 are gone; a3 (same channel_id, other instance) and a2 (same account, other channel) stay. For an account block it is k1 a3 b2, so a2 is gone too — C1
tests/tmp/test_40_search_card_actions_phase3.py:294 — `#search-status` still reads `Showing 7 of 9 matched videos.` after the removal and the refill (page 3 comes back empty) — C1
tests/tmp/test_40_search_card_actions_phase3.py:295 — no error was thrown or rejected without being handled — C1
tests/tmp/test_40_search_card_actions_phase3.py:304 — control: when the dislike answers 500, the block request and the dislike request were both still sent, in that order — control
tests/tmp/test_40_search_card_actions_phase3.py:306 — the clicked card's `.card-action-status` reads `Blocked Alice's channel, but the dislike failed: reaction store unavailable`. When the label is empty it reads `Blocked account, but the dislike failed: reaction store unavailable` — C2
tests/tmp/test_40_search_card_actions_phase3.py:308 — after the failed dislike, all 7 cards are still in the grid, in their original order — C2
tests/tmp/test_40_search_card_actions_phase3.py:309 — no error was thrown or rejected without being handled — C2
</assertions>

<probes>
Command: `ValidateTests tests/tmp/test_40_search_card_actions_phase3.py`, run against the current `pages/search/index.ts`. It printed 4 failed. The control values held as written: before.calls = [[GET, /api/v1/search/videos, music, 1], [GET, …, music, 2]], before.grid = [video a1, video a2, video k1, video a3, video b1, video b2, video k2], before.status = "Showing 7 of 9 matched videos.", pressed = true. Every run failed on the first clause assertion with after.calls = [], because the page has no Block branch yet. That confirms the red comes from the missing behaviour and not from the test's own setup.
Command: `ValidateTests tests/tmp/test_probe_40_p3.py`. This probe bundled three temporary copies of index.ts, each with a Block branch added. The reference copy follows the home page: block, then dislike, then filter `state.rows` by the block's instance_domain+channel_id or account_url, re-render, then `fillViewport()`. Printed: reference channel → after.calls = [POST /api/profile/blocks {kind: channel, uuid: uuid-a1, host: peer.example}, POST /api/user-action {action: dislike, uuid: uuid-a1, host: peer.example}, GET search music 3], grid = [video a2, video k1, video a3, video b2], status = "Showing 7 of 9 matched videos.", errors = []. reference account → the same calls with kind account, grid = [video k1, video a3, video b2], same status. reference account with a 500 dislike and an empty label → calls = [blocks, user-action], grid unchanged (all 7), cardStatus = "Blocked account, but the dislike failed: reaction store unavailable". no_fill copy (no `fillViewport()` call) → after.calls has no page-3 GET, so line 290 fails. recount copy (rewrites loadedRows and the status from the cards left) → status = "Showing 4 of 9 matched videos." for channel and "Showing 3 of 9 matched videos." for account, so line 294 fails. I emptied the probe file afterwards; this tool set has no delete.
</probes>

<unassertable>
One choice to note on C1's "status text unchanged". The page-3 fetch that shows `fillViewport` ran also rewrites `#search-status`: it shows "Loading more..." while the fetch is open, then "Showing <loaded> of <total>". To check the agreed "unchanged" text after the refill, page 3 comes back as `{rows: [], total: 9}`. That way the text only stays the same if the page did not recount or rewrite the status when it removed the cards. A page 3 that returned rows would have changed the text for a correct implementation too. Everything else in C1 and C2 is asserted as agreed.
</unassertable>

### `tests/tmp/test_40_search_card_actions_phase3.py` - 19865 characters, inlined in full

```
"""Block channel and Block account on a search card block the source and dislike the video, then take every loaded card of that source off the grid and refill it; a block whose dislike fails says so on the card and removes nothing.

`pages/search/index.ts` is bundled and run in node against a fake DOM that parses the markup it is given, a stub fetch that records each request, and an IntersectionObserver stub that loads page 2 when told the sentinel is in view. The sentinel reports itself in view only from the click on, so a page fetched after the click was asked for by the page itself once the cards were gone.

- With a key, Block channel on a page-1 card sends `POST /api/profile/blocks` for that video, then a `dislike` for it, then fetches page 3. The cards left are exactly the loaded ones not on that `instance_domain`+`channel_id`, in order: page-2 cards and a keyless card of the channel go, a card on the same `channel_id` of another instance and a card of the same account on another channel stay. Block account does the same on `account_url`, so that same-account card goes too. Page 3 comes back empty, so `#search-status` reads as it did before the click.
- When the `dislike` after the block answers 500, the clicked card's `.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`, with the action name in place of an empty label, and every card is still in the grid, in order.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
ENTRY = FRONTEND / "src" / "pages" / "search" / "index.ts"
BASE = "http://client.test"
PROFILE_KEY = "profileKey:v1"
KEY = "K" * 43

# The phase-2 fake DOM, with a sentinel that can be put in view and stub routes for the block and a failing dislike.
RUNNER = r"""
const memory = (seed) => { const s = new Map(Object.entries(seed)); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory(JSON.parse(process.env.STORAGE));
globalThis.sessionStorage = memory({});
globalThis.window = { location: { origin: process.env.BASE, pathname: "/search.html", search: process.env.SEARCH }, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage,
  innerHeight: 800, scrollY: 0, history: { pushState() {}, replaceState() {} }, addEventListener() {} };

const VOID = new Set(["area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: "\"", "#39": "'" };
const decode = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (_m, e) => ENTITIES[e]);
const escapeText = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" })[c]);
const TOKEN = /<\/([\w-]+)\s*>|<([\w-]+)((?:\s+[^\s=/>]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g;
const ATTR = /([^\s=/>]+)(?:="([^"]*)")?/g;
const kebab = (k) => k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
const detach = (n) => { const p = n.parentElement; if (p) p.childNodes.splice(p.childNodes.indexOf(n), 1); n.parentElement = null; };
const text = (v) => ({ nodeType: 3, data: String(v), parentElement: null, get textContent() { return this.data; } });
const serialize = (n) => {
  if (n.nodeType === 3) return escapeText(n.data);
  const tag = n.tagName.toLowerCase();
  const attrs = Object.entries(n.attrs).map(([k, v]) => ` ${k}="${escapeText(v)}"`).join("");
  return VOID.has(tag) ? `<${tag}${attrs}>` : `<${tag}${attrs}>${n.childNodes.map(serialize).join("")}</${tag}>`;
};
const parse = (html) => {
  const root = element("template");
  const open = [root];
  for (const [, close, tag, attrs, selfClose, txt] of String(html).matchAll(TOKEN)) {
    const top = open[open.length - 1];
    if (txt !== undefined) top.append(text(decode(txt)));
    else if (close) { const i = open.findLastIndex((n) => n.tagName === close.toUpperCase()); if (i > 0) open.length = i; }
    else {
      const el = element(tag);
      for (const [, name, value] of attrs.matchAll(ATTR)) el.setAttribute(name, decode(value ?? ""));
      top.append(el);
      if (!selfClose && !VOID.has(tag.toLowerCase())) open.push(el);
    }
  }
  const nodes = [...root.childNodes];
  nodes.forEach(detach);
  return nodes;
};
// Simple and compound selectors, joined by descendant combinators or commas; anything else throws so an unsupported query fails loudly instead of matching nothing.
const COMPOUND = /^([\w-]+|\*)?((?:\.[\w-]+|\[[\w-]+(?:="[^"]*")?\])*)$/;
const matchesCompound = (el, compound) => {
  const m = COMPOUND.exec(compound);
  if (!m || !compound) throw new Error(`fake DOM: unsupported selector ${compound}`);
  if (m[1] && m[1] !== "*" && el.tagName !== m[1].toUpperCase()) return false;
  for (const [, cls, attr, value] of m[2].matchAll(/\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g)) {
    if (cls && !el.classList.contains(cls)) return false;
    if (attr && (!(attr in el.attrs) || (value !== undefined && el.attrs[attr] !== value))) return false;
  }
  return true;
};
const matches = (el, selector) => selector.split(",").some((part) => {
  const steps = part.trim().split(/\s+/);
  if (!matchesCompound(el, steps[steps.length - 1])) return false;
  let node = el.parentElement;
  for (let i = steps.length - 2; i >= 0; i -= 1) {
    while (node && !matchesCompound(node, steps[i])) node = node.parentElement;
    if (!node) return false;
    node = node.parentElement;
  }
  return true;
});
const descend = (n) => n.children.flatMap((c) => [c, ...descend(c)]);
// Off screen until the runner says otherwise; only the sentinel can come into view.
let sentinelInView = false;
const element = (tag) => {
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), attrs: {}, childNodes: [], parentElement: null, listeners: {}, disabled: false, value: "", style: {},
    get children() { return el.childNodes.filter((n) => n.nodeType === 1); },
    get className() { return el.attrs.class ?? ""; }, set className(v) { el.attrs.class = String(v); },
    get textContent() { return el.childNodes.map((n) => n.textContent).join(""); },
    set textContent(v) { el.replaceChildren(...(v == null || v === "" ? [] : [text(v)])); },
    get innerHTML() { return el.childNodes.map(serialize).join(""); },
    set innerHTML(v) { el.replaceChildren(...parse(v)); },
    get outerHTML() { return serialize(el); },
    // Chromium throws here for an element with no parent (NoModificationAllowedError), which is the case a detached card meets.
    set outerHTML(v) {
      const parent = el.parentElement;
      if (!parent) throw new Error("NoModificationAllowedError: This element has no parent node.");
      const nodes = parse(v);
      parent.childNodes.splice(parent.childNodes.indexOf(el), 1, ...nodes);
      for (const n of nodes) n.parentElement = parent;
      el.parentElement = null;
    },
    get isConnected() { let n = el; while (n.parentElement) n = n.parentElement; return n === document.body; },
    dataset: new Proxy({}, { get: (_t, k) => el.attrs[`data-${kebab(String(k))}`], set: (_t, k, v) => { el.attrs[`data-${kebab(String(k))}`] = String(v); return true; } }),
    classList: {
      contains: (c) => el.className.split(/\s+/).includes(c),
      add: (...cs) => { el.className = [...new Set([...el.className.split(/\s+/).filter(Boolean), ...cs])].join(" "); },
      remove: (...cs) => { el.className = el.className.split(/\s+/).filter((c) => c && !cs.includes(c)).join(" "); },
      toggle: (c, force) => { const on = force ?? !el.classList.contains(c); if (on) el.classList.add(c); else el.classList.remove(c); return on; },
    },
    append: (...items) => { for (const item of items) { const node = typeof item === "string" ? text(item) : item; detach(node); node.parentElement = el; el.childNodes.push(node); } },
    appendChild: (node) => { el.append(node); return node; },
    replaceChildren: (...items) => { for (const n of el.childNodes) n.parentElement = null; el.childNodes = []; el.append(...items); },
    remove: () => detach(el),
    insertAdjacentHTML: (position, html) => {
      const nodes = parse(html);
      if (position === "beforeend") el.append(...nodes);
      else if (position === "afterbegin") { el.childNodes.unshift(...nodes); for (const n of nodes) n.parentElement = el; }
      else throw new Error(`fake DOM: unsupported insertAdjacentHTML position ${position}`);
    },
    setAttribute: (n, v) => { el.attrs[n] = String(v); if (n === "disabled") el.disabled = true; },
    getAttribute: (n) => el.attrs[n] ?? null, hasAttribute: (n) => n in el.attrs,
    removeAttribute: (n) => { delete el.attrs[n]; if (n === "disabled") el.disabled = false; },
    addEventListener: (type, l) => { (el.listeners[type] ??= []).push(l); },
    removeEventListener: (type, l) => { el.listeners[type] = (el.listeners[type] ?? []).filter((x) => x !== l); },
    matches: (s) => matches(el, s),
    closest: (s) => { for (let n = el; n; n = n.parentElement) if (matches(n, s)) return n; return null; },
    querySelector: (s) => descend(el).find((n) => matches(n, s)) ?? null,
    querySelectorAll: (s) => descend(el).filter((n) => matches(n, s)),
    getBoundingClientRect: () => { const top = sentinelInView && el.attrs.id === "search-sentinel" ? 0 : 100000; return { top, bottom: top, left: 0, right: 0, width: 0, height: 0 }; },
    focus() {}, select() {},
  };
  return el;
};
const byId = new Map();
globalThis.document = { title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) { const el = element("div"); el.attrs.id = id; document.body.append(el); byId.set(id, el); } return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (v) => text(v), querySelector: (s) => document.body.querySelector(s), querySelectorAll: (s) => document.body.querySelectorAll(s), addEventListener() {} };
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { observers.push(callback); } observe() {} unobserve() {} disconnect() {} };

const pages = JSON.parse(process.env.PAGES);
const requests = [];
globalThis.fetch = async (input, init = {}) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: String(init.method ?? "GET").toUpperCase(), path: url.pathname, query: Object.fromEntries(url.searchParams), body: init.body == null ? null : JSON.parse(String(init.body)) });
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/v1/search/videos") {
    const page = pages[url.searchParams.get("q")]?.[Number(url.searchParams.get("page") ?? "1") - 1];
    return new Response(JSON.stringify(page ?? { rows: [], total: 0 }), { status: 200, headers });
  }
  if (url.pathname === "/api/profile/blocks" && init.method === "POST") {
    return new Response(JSON.stringify({ block: JSON.parse(process.env.BLOCK) }), { status: 200, headers });
  }
  if (url.pathname === "/api/user-action") {
    const status = Number(process.env.DISLIKE_STATUS);
    return new Response(JSON.stringify(status === 200 ? {} : { error: process.env.DISLIKE_ERROR }), { status, headers });
  }
  return new Response(JSON.stringify({ error: "unexpected route" }), { status: 404, headers });
};
const errors = [];
process.on("unhandledRejection", (r) => { errors.push(String(r && r.stack || r)); });
process.on("uncaughtException", (e) => { errors.push(String(e && e.stack || e)); });
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 10)); };
// Events bubble through parentElement; a listener that throws is recorded, as a browser would report it.
const fire = (target, type) => {
  const event = { type, target, bubbles: true, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() { event.stopped = true; } };
  for (let node = target; node && !event.stopped; node = node.parentElement) {
    event.currentTarget = node;
    for (const l of [...(node.listeners[type] ?? [])]) { try { l.call(node, event); } catch (e) { errors.push(String(e && e.stack || e)); } }
  }
};
const grid = () => byId.get("search-results");
const cardOf = (key) => grid().children.find((c) => c.dataset.videoKey === key) ?? null;
const cards = () => grid().children.map((card) => card.querySelector(".video-title")?.textContent ?? null);
const status = () => byId.get("search-status").textContent;
const calls = (from) => requests.slice(from).map((r) => r.path === "/api/v1/search/videos" ? [r.method, r.path, r.query.q, r.query.page ?? "1"]
  : r.path === "/api/user-action" ? [r.method, r.path, { action: r.body?.action, uuid: r.body?.uuid, host: r.body?.host }] : [r.method, r.path, r.body]);

await import(process.env.BUNDLE);
await settle();
for (const callback of observers) callback([{ isIntersecting: true }]);
await settle();
const report = { before: { calls: calls(0), grid: cards(), status: status() } };
const sentBefore = requests.length;
sentinelInView = true;
const button = cardOf(process.env.TARGET)?.querySelector(`[data-card-action="${process.env.ACTION}"]`);
report.pressed = Boolean(button);
if (button) fire(button, "click");
await settle();
const clicked = cardOf(process.env.TARGET);
report.after = { calls: calls(sentBefore), grid: cards(), status: status(), cardStatus: clicked?.querySelector(".card-action-status")?.textContent ?? null };
report.errors = errors;
process.stdout.write(JSON.stringify(report) + "\n", () => process.exit(0));
"""


def _bundle(entry: Path, out: Path) -> Path:
    run = subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    (out / "runner.mjs").write_text(RUNNER)
    return out


@pytest.fixture(scope="module")
def search_bundle(tmp_path_factory) -> Path:
    return _bundle(ENTRY, tmp_path_factory.mktemp("search"))


def _run(bundle: Path, action: str, block: dict, dislike_status: int, dislike_error: str = "") -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "STORAGE": json.dumps({PROFILE_KEY: KEY}), "SEARCH": f"?q={QUERY}",
             "PAGES": json.dumps(PAGES), "TARGET": _key(TARGET), "ACTION": action, "BLOCK": json.dumps(block), "DISLIKE_STATUS": str(dislike_status), "DISLIKE_ERROR": dislike_error},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


def _row(tag: str, domain: str, channel: str, account: str, keyed: bool = True) -> dict:
    # A keyless row has no uuid and no id, so its card has no video key and no controls of its own.
    return {"video_id": tag if keyed else None, "video_uuid": f"uuid-{tag}" if keyed else None, "instance_domain": domain, "channel_id": channel, "account_url": account, "title": f"video {tag}"}


def _key(row: dict) -> str:
    return f"{row['instance_domain']}::{row['video_uuid']}"


ALICE = "https://peer.example/accounts/alice"
QUERY = "music"
TARGET = _row("a1", "peer.example", "7", ALICE)
PAGE_1 = [
    TARGET,
    _row("a2", "peer.example", "8", ALICE),  # same account, another channel
    _row("k1", "peer.example", "9", "https://peer.example/accounts/carol", keyed=False),
    _row("a3", "other.example", "7", "https://other.example/accounts/dave"),  # same channel_id on another instance
]
PAGE_2 = [
    _row("b1", "peer.example", "7", ALICE),  # same channel and account, on page 2
    _row("b2", "peer.example", "10", "https://peer.example/accounts/erin"),
    _row("k2", "peer.example", "7", ALICE, keyed=False),  # same channel and account, keyless
]
TOTAL = 9  # more than the 7 loaded, so a third page exists; it comes back empty, which leaves the status line's counts as they were
PAGES = {QUERY: [{"rows": PAGE_1, "total": TOTAL}, {"rows": PAGE_2, "total": TOTAL}, {"rows": [], "total": TOTAL}]}
ALL_TITLES = ["video a1", "video a2", "video k1", "video a3", "video b1", "video b2", "video k2"]
STATUS = "Showing 7 of 9 matched videos."
BLOCK = {"kind": "channel", "instance_domain": "peer.example", "channel_id": "7", "account_url": ALICE, "label": "Alice's channel"}
DISLIKE_ERROR = "reaction store unavailable"


def _block(kind: str, label: str) -> dict:
    return {**BLOCK, "kind": kind, "label": label}


def _block_then_dislike(kind: str) -> list:
    return [["POST", "/api/profile/blocks", {"kind": kind, "uuid": TARGET["video_uuid"], "host": TARGET["instance_domain"]}],
            ["POST", "/api/user-action", {"action": "dislike", "uuid": TARGET["video_uuid"], "host": TARGET["instance_domain"]}]]


def _control_before(page: dict) -> None:
    # control: page 1 loaded, page 2 only when the observer reported the sentinel, page 3 not yet, and every row is a card
    assert page["before"]["calls"] == [["GET", "/api/v1/search/videos", QUERY, "1"], ["GET", "/api/v1/search/videos", QUERY, "2"]], page["before"]
    assert page["before"]["grid"] == ALL_TITLES, page["before"]
    assert page["before"]["status"] == STATUS, page["before"]
    assert page["pressed"] is True, page["before"]  # control: the clicked card carries the button


@pytest.mark.parametrize(("kind", "left"), [
    # a2 shares the account but not the channel; a3 shares the channel_id but not the instance.
    ("channel", ["video a2", "video k1", "video a3", "video b2"]),
    ("account", ["video k1", "video a3", "video b2"]),
])
def test_a_block_whose_dislike_succeeds_removes_every_loaded_card_of_the_source_and_refills_the_grid(search_bundle, kind, left):
    page = _run(search_bundle, kind, _block(kind, "Alice"), 200)
    _control_before(page)

    # A page with no Block branch sends nothing; one that skips or reorders the dislike, or never refills, fails on the sequence.
    assert page["after"]["calls"] == _block_then_dislike(kind) + [["GET", "/api/v1/search/videos", QUERY, "3"]], (page["after"], page["errors"])  # C1
    # A page that removes only the clicked card keeps b1 and k2; one that matches on channel_id alone drops a3; one that matches the wrong field keeps or drops a2.
    assert page["after"]["grid"] == left, page["after"]  # C1
    # A page that recounts the status from the cards left, or writes the block into it, changes it.
    assert page["after"]["status"] == STATUS, page["after"]  # C1
    assert page["errors"] == [], page["errors"]  # C1


@pytest.mark.parametrize(("kind", "label", "shown"), [("channel", "Alice's channel", "Alice's channel"), ("account", "", "account")])
def test_a_block_whose_dislike_fails_says_so_on_the_card_and_removes_nothing(search_bundle, kind, label, shown):
    page = _run(search_bundle, kind, _block(kind, label), 500, DISLIKE_ERROR)
    _control_before(page)

    # control: the block was accepted and the dislike that followed it was the request that failed
    assert page["after"]["calls"][:2] == _block_then_dislike(kind), (page["after"], page["errors"])
    # A page that reports only the dislike error, or reports nothing, fails here; an empty label falls back to the action.
    assert page["after"]["cardStatus"] == f"Blocked {shown}, but the dislike failed: {DISLIKE_ERROR}", (page["after"], page["errors"])  # C2
    # A page that removes the source's cards whatever the dislike returned leaves fewer.
    assert page["after"]["grid"] == ALL_TITLES, page["after"]  # C2
    assert page["errors"] == [], page["errors"]  # C2

```


Gate: satisfied

## 2026-10-01 - Step 7 - Phase 3 (Block removes the source's loaded cards) - red (audit round 1)

`tests/tmp/test_40_search_card_actions_phase3.py` exited 1.

```
  tests/tmp/test_40_search_card_actions_phase3.py  4 failed                               0.0s
  -----------------------------------------------
  total                                            4 failed                               1.6s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 3 (Block removes the source's loaded cards) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D5

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
In both `channel` and `account` cases of `test_a_block_whose_dislike_succeeds_removes_every_loaded_card_of_the_source_and_refills_the_grid`, the test should fail at line 290 (`assert page["after"]["calls"] == _block_then_dislike(kind) + [...]`). The click sends no request, so `after.calls` is `[]`, because `runCardAction` in `client/frontend/src/pages/search/index.ts:246-275` has only `like` and `dislike` branches. In both cases of `test_a_block_whose_dislike_fails_says_so_on_the_card_and_removes_nothing`, the test should fail at line 304 (`assert page["after"]["cardStatus"] == f"Blocked {shown}, but the dislike failed: ..."`). The card status reads `""` because `say("")` runs and no branch follows it.

NOT ASSESSED
1. `code_under_test` lists `tests/tmp/test_frontend_search_card_actions.py`, and that path does not exist (Glob found no match). Nothing it might contain was checked. The checks above used the test file, `client/frontend/src/pages/search/index.ts`, and `client/frontend/src/components/video-card.ts`. I read `video-card.ts` to confirm the symbols the test relies on: `data-card-action="channel"`/`"account"`, `.card-action-status`, and the `data-video-key` format `host::uuid`.
2. `fixtures_path` was not supplied. The only fixture the test uses, `search_bundle`, is defined in the test file at lines 217-219, so this left nothing out.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (27 clauses: 8 must_prove, 14 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a successful block followed by a successful dislike" | :290 | a page that skips the dislike, sends it before the block, or sends either for the wrong uuid/host/kind; the list is compared exactly, in order | CARRIED |
| C1b | must_prove | "removes every loaded card of that channel" | :292 (kind=channel) | removing only the clicked card (b1 and k2 would stay); matching on channel_id alone (a3 would go); matching on account (a2 would go); breaking the order | CARRIED |
| C1c | must_prove | "...or account" | :292 (kind=account) | Block account matching on channel instead of account_url (a2 would stay) | CARRIED |
| C1d | must_prove | "refills the viewport" | :290 | a page that never asks for more after removing cards. After the click no observer fires, so the page 3 GET can only come from the page itself | CARRIED |
| C1e | must_prove | "leaves the status text unchanged" | :294 against :276 | recounting the status from the cards left, or writing the block result into `#search-status` | CARRIED |
| C2a | must_prove | reports `Blocked <label>, but the dislike failed: <msg>` | :304 (channel, "Alice's channel") | reporting only the dislike error, reporting nothing, or a generic message in place of the server's `error` | CARRIED |
| C2b | must_prove | `<action>` used when the label is empty | :304 (account, "") | rendering `Blocked , but the dislike failed: ...`. It does not exclude a fixed fallback string or a label/action choice made by kind (see Recommendation 1) | CARRIED |
| C2c | must_prove | "removes no card" | :308, armed by :306 | removing the source's cards whatever the dislike returned. :306 shows the failing dislike was actually reached | CARRIED |
| D1 | docstring | "block the source and dislike the video" | :290 | dislike or block missing from the sequence | CARRIED |
| D2 | docstring | "take every loaded card of that source off the grid and refill it" | :292, :290 | partial removal; no refill fetch | CARRIED |
| D3 | docstring | "a block whose dislike fails says so on the card and removes nothing" | :304, :308 | no message on the card; cards removed anyway | CARRIED |
| D4 | docstring | "a page fetched after the click was asked for by the page itself" | :290 | a fetch caused by the harness. Observers are only called before the click (runner line 190) | CARRIED |
| D5 | docstring | "...once the cards were gone" | none | the sentinel's in-view state depends on the click, not on what is in the grid, so a refill sent before the removal passes the same way | UNCARRIED |
| D6 | docstring | "sends POST /api/profile/blocks for that video, then a dislike for it, then fetches page 3" | :290 | wrong order, wrong body, or a missing step | CARRIED |
| D7 | docstring | "the cards left are exactly the loaded ones not on that instance_domain+channel_id, in order" | :292 | dropping or reordering a card that should stay | CARRIED |
| D8 | docstring | "page-2 cards and a keyless card of the channel go" | :292 | removing only cards that have a video key, or only page-1 cards (b1 and k2 would stay) | CARRIED |
| D9 | docstring | "a card on the same channel_id of another instance and a card of the same account on another channel stay" | :292 (channel) | matching on channel_id without the domain (a3 goes); matching on account (a2 goes) | CARRIED |
| D10 | docstring | "Block account does the same on account_url, so that same-account card goes too" | :290, :292 (account) | Block account sending the wrong kind, or matching on channel | CARRIED |
| D11 | docstring | "Page 3 comes back empty, so #search-status reads as it did before the click" | :294 against :276 | the status changing after removal | CARRIED |
| D12 | docstring | "`.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`" | :304 | wrong text, or text on the wrong element | CARRIED |
| D13 | docstring | "with the action name in place of an empty label" | :304 (account, "") | showing an empty label | CARRIED |
| D14 | docstring | "every card is still in the grid, in order" | :308 | any card removed or reordered | CARRIED |
| N1 | name | "a block whose dislike succeeds" | :290 | the dislike not being sent after the block | CARRIED |
| N2 | name | "removes every loaded card of the source" | :292 | partial or wrong-field removal | CARRIED |
| N3 | name | "and refills the grid" | :290 | no fetch of the next page | CARRIED |
| N4 | name | "a block whose dislike fails says so on the card" | :304 | no message, or the wrong message, on the clicked card | CARRIED |
| N5 | name | "and removes nothing" | :308 | cards removed on the failure path | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase3.py:298
   `[("channel", "Alice's channel", "Alice's channel"), ("account", "", "account")]`
   The parametrisation ties the kind to whether the label is empty. The channel case always has a label and the account case never does. An implementation that writes `Blocked ${action === "channel" ? block.label : action}`, or falls back to a fixed `"account"`, passes both cases. C2b is CARRIED because it excludes the empty-label rendering. Under "X per Y needs a second Y", though, the label-or-action choice is only half shown. Adding a case with a channel block and an empty label (expect `channel`), or an account block with a label, separates them.
2. whole-claim (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase3.py:3
   D5 is UNCARRIED. The docstring says the page 3 fetch was asked for "once the cards were gone". The fake sentinel reports itself in view because of the click (runner line 194), not because of what the grid holds. So nothing shows the refill came after the removal. Either narrow the sentence or tie the stub's in-view state to the grid's contents.
3. bounds (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase3.py:256
   Page 3 always comes back empty. The refill is therefore only seen as a request, and rows the refill returns are never shown landing in the grid. The case where removal empties the grid completely is also untested.
4. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase3.py:299
   The only failure path tested is the dislike failing. A failing `POST /api/profile/blocks` (does the page skip the dislike, show a message, keep the cards?) is never exercised. That clause is not in `must_prove`, so this is not blocking.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which does not exist. Nothing in this test depends on it, and it was not assessed.

## 2026-10-01 - Step 7 - Phase 3 (Block removes the source's loaded cards) - self-check (audit round 2, send-back 0)

`tests/tmp/test_40_search_card_actions_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_40_search_card_actions_phase3.py:290 — the requests sent after the click, in order: POST /api/profile/blocks {kind, uuid, host}, then POST /api/user-action dislike for that video, then GET search page 3 - expected: [["POST","/api/profile/blocks",{"kind":kind,"uuid":"uuid-a1","host":"peer.example"}],["POST","/api/user-action",{"action":"dislike","uuid":"uuid-a1","host":"peer.example"}],["GET","/api/v1/search/videos","music","3"]] - excludes: A page with no fillViewport() after the removal has no page-3 GET in its calls (seen in the no_fill probe). A page that skips the dislike, or sends it before the block, gives the wrong sequence. The current page with no Block branch sends [].
- C1 - tests/tmp/test_40_search_card_actions_phase3.py:292 — the titles left in the grid after the removal - expected: channel: ["video a2","video k1","video a3","video b2"]; account: ["video k1","video a3","video b2"] - excludes: Removing only the clicked card leaves b1 and k2 in the grid. Matching on channel_id without instance_domain also removes a3. Matching a channel block on account removes a2. Matching an account block on channel keeps a2.
- C1 - tests/tmp/test_40_search_card_actions_phase3.py:294 — #search-status after the removal and the empty page-3 refill - expected: "Showing 7 of 9 matched videos." - excludes: Recounting the status from the cards left reads "Showing 4 of 9 matched videos." (channel) and "Showing 3 of 9 matched videos." (account), both seen in the recount probe. Writing the block result into #search-status also changes the text.
- C2 - tests/tmp/test_40_search_card_actions_phase3.py:304 — the clicked card's .card-action-status text when the dislike answers 500 - expected: channel with label "Alice's channel": "Blocked Alice's channel, but the dislike failed: reaction store unavailable"; account with empty label: "Blocked account, but the dislike failed: reaction store unavailable" - excludes: Showing only the dislike error, showing nothing (the current page reads ""), showing a generic message in place of the server's error, or rendering "Blocked , but the dislike failed: ..." when the label is empty.
- C2 - tests/tmp/test_40_search_card_actions_phase3.py:308 — the grid after the failed dislike, armed by :306, which shows the block and the failing dislike were both sent - expected: ["video a1","video a2","video k1","video a3","video b1","video b2","video k2"] - excludes: Removing the source's cards whatever the dislike returned leaves the channel-block grid as [a2,k1,a3,b2] and the account-block grid as [k1,a3,b2].

<exemptions>
none
</exemptions>

<items>
<item id="D5">
<disposition>justified</disposition>
<what>I narrowed the docstring to what the test actually asserts. Line 3 used to end "so a page fetched after the click was asked for by the page itself once the cards were gone." It now ends "so a page fetched after the click was asked for by the page itself; nothing here shows whether that fetch came before or after the cards were removed." The fake sentinel reports itself in view because of the click, not because of what the grid holds, so the test cannot show the refill came after the removal. The docstring no longer claims it does. What :290 does carry stays in the docstring: the page-3 GET happened and the page sent it itself (C1d/D4). No assertion changed.</what>
</item>
</items>

<findings_addressed>
Neither auditor raised a CRITICAL. I took claim Recommendation 2 (D5) by narrowing the docstring sentence on line 3, as described in the D5 item. I did not take Recommendations 1, 3 and 4: none of them blocks, and the ledger does not name them.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_40_search_card_actions_phase3.py:290 — the requests sent after the click, in order: POST /api/profile/blocks {kind, uuid, host}, then POST /api/user-action dislike for that video, then GET search page 3</assertion>
<expected>[["POST","/api/profile/blocks",{"kind":kind,"uuid":"uuid-a1","host":"peer.example"}],["POST","/api/user-action",{"action":"dislike","uuid":"uuid-a1","host":"peer.example"}],["GET","/api/v1/search/videos","music","3"]]</expected>
<wrong_implementation>A page with no fillViewport() after the removal has no page-3 GET in its calls (seen in the no_fill probe). A page that skips the dislike, or sends it before the block, gives the wrong sequence. The current page with no Block branch sends [].</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_40_search_card_actions_phase3.py:292 — the titles left in the grid after the removal</assertion>
<expected>channel: ["video a2","video k1","video a3","video b2"]; account: ["video k1","video a3","video b2"]</expected>
<wrong_implementation>Removing only the clicked card leaves b1 and k2 in the grid. Matching on channel_id without instance_domain also removes a3. Matching a channel block on account removes a2. Matching an account block on channel keeps a2.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_40_search_card_actions_phase3.py:294 — #search-status after the removal and the empty page-3 refill</assertion>
<expected>"Showing 7 of 9 matched videos."</expected>
<wrong_implementation>Recounting the status from the cards left reads "Showing 4 of 9 matched videos." (channel) and "Showing 3 of 9 matched videos." (account), both seen in the recount probe. Writing the block result into #search-status also changes the text.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_40_search_card_actions_phase3.py:304 — the clicked card's .card-action-status text when the dislike answers 500</assertion>
<expected>channel with label "Alice's channel": "Blocked Alice's channel, but the dislike failed: reaction store unavailable"; account with empty label: "Blocked account, but the dislike failed: reaction store unavailable"</expected>
<wrong_implementation>Showing only the dislike error, showing nothing (the current page reads ""), showing a generic message in place of the server's error, or rendering "Blocked , but the dislike failed: ..." when the label is empty.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_40_search_card_actions_phase3.py:308 — the grid after the failed dislike, armed by :306, which shows the block and the failing dislike were both sent</assertion>
<expected>["video a1","video a2","video k1","video a3","video b1","video b2","video k2"]</expected>
<wrong_implementation>Removing the source's cards whatever the dislike returned leaves the channel-block grid as [a2,k1,a3,b2] and the account-block grid as [k1,a3,b2].</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every negative check has a positive control. :308 (nothing removed) is armed by :306, which shows the block and the failing dislike were both sent, and by _control_before, which shows all 7 cards were loaded and the button was there. If the code under test is deleted, :290 and :304 go red.
2. No. Every expected value is a fixture literal or an observed output; the test never computes production's result itself. Deleting the Block branch in runCardAction turns :290 and :304 red. Deleting the row filter turns :292 red. Deleting the fillViewport() call turns :290 red.
3. No. The removal is checked for both kinds, with cards that differ on domain, channel and account (a2, a3, b1, k2). The failure message is checked with a label and without one. One gap remains: each kind is tested with only one label state (claim Recommendation 1). It does not block, and I did not take it.
4. No. The fetch, the DOM and IntersectionObserver are doubles for browser and network layers. pages/search/index.ts and video-card.ts are bundled and run for real.
5. Yes, it collects. My only edit is to the docstring, so imports, names and helpers are unchanged. There are still 4 parametrised cases.
6. Yes. The expected values were seen in the earlier ValidateTests runs: the control values against the current page, and the grid, status, calls and cardStatus against the reference probe copies. This round adds no new expected value.
7. Yes. Before this edit the whole file ran 4 failed: every case got past the before-click controls and failed on its first clause assertion with after.calls == [] / cardStatus == "", because the Block branch is missing. The only change since then is to docstring text, so that failure still stands. I did not re-run it.
No rewrite was needed.
</answers>

Gate: satisfied

## 2026-10-01 - Step 7 - Phase 3 (Block removes the source's loaded cards) - red (audit round 2)

`tests/tmp/test_40_search_card_actions_phase3.py` exited 1.

```
  tests/tmp/test_40_search_card_actions_phase3.py  4 failed                               0.0s
  -----------------------------------------------
  total                                            4 failed                               1.6s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 3 (Block removes the source's loaded cards) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Both parametrised cases of `test_a_block_whose_dislike_succeeds_removes_every_loaded_card_of_the_source_and_refills_the_grid` fail at tests/tmp/test_40_search_card_actions_phase3.py:290. The reason is that `runCardAction` in client/frontend/src/pages/search/index.ts has no `channel`/`account` branch. So `page["after"]["calls"]` is `[]`, where the test expects the block POST, then the dislike POST, then the page-3 GET. Both cases of `test_a_block_whose_dislike_fails_says_so_on_the_card_and_removes_nothing` fail at line 304. There the action status is cleared by `say("")` and never set again, so `page["after"]["cardStatus"]` is `""` (or `null` if the card renders no `.card-action-status`) instead of `Blocked Alice's channel, but the dislike failed: reaction store unavailable` / `Blocked account, but the dislike failed: reaction store unavailable`.

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_frontend_search_card_actions.py, which is a test file and not code this test exercises. This test neither imports it nor runs it, so it was not read as part of the shape assessment.
2. I did not read client/frontend/src/components/video-card.ts in full; I only grepped it to confirm the `data-card-action="channel"`/`"account"` buttons exist. Whether it renders `.card-action-status` on keyed cards was not confirmed. That affects only whether the line-304 red reads `""` or `null`, not where the test fails.
3. Passes 4 and 5 and the stub question, as covered by `rules/shape.md`:
   - **Anti-patterns (pass 4):** none match.
     - **`absence-only-assertion`:** line 308 (`grid == ALL_TITLES`) is paired in the same test with positive assertions at lines 304 and 306.
     - **`echoed-literal`:** `DISLIKE_ERROR` and the label go in through the stub server and only reach the card through the page's error and label handling.
     - **`tautological-assertion`:** `_block_then_dislike` builds its expectation from fixture rows, not from production logic.
     - **`single-value-pin`:** the label is run at two values (`"Alice's channel"` and `""`, which falls back to the action name), and the kind is run at two values with different expected grids.
   - **Ladder (pass 5):** the test drives the bundled page and asserts on the requests it sends, the grid and the status it renders. That is rung 1 (direct behaviour invocation with observable side effects), the highest rung, so there is no downshift to justify.
   - **Stub question:** the exact request sequence at line 290 and the fixtures at lines 244–254 together reject:
     - a stub with no Block branch
     - removing only the clicked card
     - matching on `channel_id` alone
     - matching on the wrong field
     - skipping the refill

     A stub that removes cards whatever the dislike returns fails line 308.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (27 clauses: 8 must_prove, 14 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a successful block followed by a successful dislike" | :290 | Rules out skipping the dislike, sending it before the block, or sending either one with the wrong uuid/host/kind. The list is compared exactly and in order | CARRIED |
| C1b | must_prove | "removes every loaded card of that channel" | :292 (kind=channel) | Rules out removing only the clicked card (b1 and k2 would stay), matching on channel_id alone (a3 would go), matching on account (a2 would go), and breaking the order | CARRIED |
| C1c | must_prove | "...or account" | :292 (kind=account) | Rules out Block account matching on channel instead of account_url (a2 would stay) | CARRIED |
| C1d | must_prove | "refills the viewport" | :290 | Rules out a page that never asks for more after removing cards. The sentinel is only in view from the click on (runner :194), and observers are only called before it (:190), so the page 3 GET can only come from the page | CARRIED |
| C1e | must_prove | "leaves the status text unchanged" | :294 against :276 | Rules out recounting the status from the cards left, and rules out writing the block result into `#search-status` | CARRIED |
| C2a | must_prove | reports `Blocked <label>, but the dislike failed: <msg>` | :304 (channel, "Alice's channel") | Rules out reporting only the dislike error, reporting nothing, or showing a generic message instead of the server's `error` | CARRIED |
| C2b | must_prove | `<action>` used when the label is empty | :304 (account, "") | Rules out rendering `Blocked , but the dislike failed: ...`. Does not rule out a fixed fallback string or a choice made by kind (Recommendation 1) | CARRIED |
| C2c | must_prove | "removes no card" | :308, armed by :306 | Rules out removing the source's cards whatever the dislike returned. :306 shows the failing dislike was reached | CARRIED |
| D1 | docstring | "block the source and dislike the video" | :290 | Rules out a sequence missing the block or the dislike | CARRIED |
| D2 | docstring | "take every loaded card of that source off the grid and refill it" | :292, :290 | Rules out partial removal and a missing refill fetch | CARRIED |
| D3 | docstring | "a block whose dislike fails says so on the card and removes nothing" | :304, :308 | Rules out no message on the card, and rules out cards being removed anyway | CARRIED |
| D4 | docstring | "a page fetched after the click was asked for by the page itself" | :290 | Rules out a fetch caused by the harness. Observers are only called before the click (runner :190) | CARRIED |
| D5 | docstring | withdrawn | n/a | n/a | CARRIED |
| D6 | docstring | "sends POST /api/profile/blocks for that video, then a dislike for it, then fetches page 3" | :290 | Rules out the wrong order, the wrong body, or a missing step | CARRIED |
| D7 | docstring | "the cards left are exactly the loaded ones not on that instance_domain+channel_id, in order" | :292 | Rules out dropping or reordering a card that should stay | CARRIED |
| D8 | docstring | "page-2 cards and a keyless card of the channel go" | :292 | Rules out removing only cards with a video key, or only page-1 cards (b1 and k2 would stay) | CARRIED |
| D9 | docstring | "a card on the same channel_id of another instance and a card of the same account on another channel stay" | :292 (channel) | Rules out matching on channel_id without the domain (a3 goes) and matching on account (a2 goes) | CARRIED |
| D10 | docstring | "Block account does the same on account_url, so that same-account card goes too" | :290, :292 (account) | Rules out Block account sending the wrong kind or matching on channel | CARRIED |
| D11 | docstring | "Page 3 comes back empty, so #search-status reads as it did before the click" | :294 against :276 | Rules out the status changing after removal | CARRIED |
| D12 | docstring | "`.card-action-status` reads `Blocked <label>, but the dislike failed: <error>`" | :304 | Rules out the wrong text, or text on the wrong element | CARRIED |
| D13 | docstring | "with the action name in place of an empty label" | :304 (account, "") | Rules out showing an empty label | CARRIED |
| D14 | docstring | "every card is still in the grid, in order" | :308 | Rules out any card being removed or reordered | CARRIED |
| N1 | name | "a block whose dislike succeeds" | :290 | Rules out the dislike not being sent after the block | CARRIED |
| N2 | name | "removes every loaded card of the source" | :292 | Rules out partial removal or removal on the wrong field | CARRIED |
| N3 | name | "and refills the grid" | :290 | Rules out no fetch of the next page | CARRIED |
| N4 | name | "a block whose dislike fails says so on the card" | :304 | Rules out no message, or the wrong message, on the clicked card | CARRIED |
| N5 | name | "and removes nothing" | :308 | Rules out cards being removed on the failure path | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase3.py:298
   `@pytest.mark.parametrize(("kind", "label", "shown"), [("channel", "Alice's channel", "Alice's channel"), ("account", "", "account")])`
   The empty-label case only runs for `account`, where the action name and the kind are the same string. A page that always falls back to the literal "account", or chooses label or action by kind, still passes. A `channel` case with an empty label (shown "channel") would rule both out. This is the gap already recorded in the C2b `excludes` cell, and it does not block.

OBSERVATIONS
1. D5 (whole-claim, rules/testing.md): tests/tmp/test_40_search_card_actions_phase3.py:3
   The docstring was narrowed, and no assertion was added. On round 1, "...once the cards were gone" was UNCARRIED. The docstring now says "nothing here shows whether that fetch came before or after the cards were removed". So the test still does not show that the removal happens before the refill. It now says so openly instead of claiming it.

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py, which does not exist (rg: No such file or directory). It was not read. The test under audit does not import it.
2. `fixtures_path` was "none found". The test defines its only fixture, `search_bundle`, at :217, so independence was judged from the test file alone.

## 2026-10-01 - Step 7 - Phase 3 (Block removes the source's loaded cards) - checkpoint outcome (run 1)

`tests/tmp/test_40_search_card_actions_phase3.py` exited 0 after the phase landed.

<changes>
### `client/frontend/src/pages/search/index.ts`
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_40_search_card_actions_phase3.py  4 passed                               0.0s
  -----------------------------------------------
  total                                            4 passed                               1.6s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 4 (No-key guard, failures and dist rebuild) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
In `pages/search/index.ts`, a card action that cannot or does not succeed leaves the card's reaction as it was and explains why in that card's status line.

- C1 - Without a profile key, Dislike, Block channel and Block account each write home's exact profile prompt and send no request.
- C2 - A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged.

must_prove:
- C1 - Without a profile key, Dislike, Block channel and Block account each write home's exact profile prompt and send no request.
- C2 - A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged.

## 2026-10-01 - Step 7 - Phase 4 (No-key guard, failures and dist rebuild) - self-check (audit round 1, send-back 0)

`tests/tmp/test_40_search_card_actions_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_40_search_card_actions_phase4.py:288 — `page["prompt"]["sent"] == []`: with no profile key, the Dislike / Block channel / Block account click (one per parametrized case) adds no request to the stub fetch's record. - expected: `[]` for all three actions. This was observed under the probe's "guarded" mutant (index.ts with a `!getProfileKey()` guard ahead of `button.disabled = true`), where all three C1 cases pass. - excludes: The current index.ts has no key guard. The run observed one extra request for each case: `['POST', '/api/user-action', {'action': 'dislike', 'uuid': 'uuid-a1', 'host': 'peer.example'}]` for dislike, and `['POST', '/api/profile/blocks', {'kind': 'channel'|'account', 'uuid': 'uuid-a1', 'host': 'peer.example'}]` for the two blocks. A page that guards only Dislike still sends the two block requests, so the channel and account cases fail.
- C1 - tests/tmp/test_40_search_card_actions_phase4.py:290 — `page["prompt"]["card"]["status"] == prompt`: the clicked card's `.card-action-status` text equals home's exact prompt (videos/index.ts:409). That is "Disliking needs a profile. Create one from the Profile button." for dislike and "Blocking needs a profile. Create one from the Profile button." for both blocks. - expected: The exact prompt string for each action. All three cases pass this line under the probe's "guarded" mutant. Against the current code the line is not reached, because :288 fails first. - excludes: A page that sends the request leaves the status empty (the stub answers 200) or shows the server's error. A page using the video page's wording ("...from the Profile button on the home page.") shows a different string. A page that guards but writes nothing leaves `""`. I did not run a mutant for the wording or empty-status cases; the string comparison is what excludes them.
- C2 - tests/tmp/test_40_search_card_actions_phase4.py:311 — `page["rejected"]["card"]["status"] == LIMIT_ERROR`: after the held 400 is released, the card's status line reads "Dislike limit reached (1000)". - expected: "Dislike limit reached (1000)", for both the neutral card and the liked card. Observed in the run: both C2 cases pass. - excludes: Observed in the probe: the "generic" mutant (`say("Action failed")`) fails at :311 in both cases. The "optimistic_redraw" mutant (row set and card redrawn before the request) also fails at :311, because say() writes into the detached old status element and the new card's status stays empty.
- C2 - tests/tmp/test_40_search_card_actions_phase4.py:313 — `page["rejected"]["disabled"] is False`: the clicked Dislike button is enabled again once the rejection lands. The control at :308 showed it was `True` while the response was held. - expected: `False`, for both cases. Observed in the run: both pass. - excludes: Observed in the probe: the "no_reenable" mutant (empty `finally`, so the button is re-enabled only on success) fails at :313 in both cases.
- C2 - tests/tmp/test_40_search_card_actions_phase4.py:315 — `_marks(page["rejected"]["card"]) == mark`: after the rejection, the card's (likes active, like aria-pressed, dislikes active, dislike aria-pressed) equals the mark it had before the click. - expected: `(False, "false", False, "false")` for the neutral card and `(True, "true", False, "false")` for the liked card. Observed in the run: both pass. - excludes: Observed in the probe: the "optimistic_mark" mutant (toggles `.stat.dislikes` active before the request and never takes it back) fails at :315 in both cases, because the dislikes stat reads active.
- C2 - tests/tmp/test_40_search_card_actions_phase4.py:318 — `page["again"]["sent"] == [_sent("dislike", target)]`: a second Dislike on the same card after the rejection sends `dislike`, not `undo_dislike`. That shows the row's reaction was not left as disliked. :319 adds that no listener threw. - expected: `[["POST", "/api/user-action", {"action": "dislike", "uuid": "uuid-a1", "host": "peer.example"}]]`, for both cases. Observed in the run: both pass. - excludes: Observed in the probe: the "optimistic" mutant (`row.reaction = "disliked"` set before `await sendReaction`, with no redraw) passes :311-:315 but fails at :318 in both cases, because the second click sends `undo_dislike`.

<assertions>
tests/tmp/test_40_search_card_actions_phase4.py:288 - for each of Dislike, Block channel and Block account with no profile key, the click adds no request to the stub fetch's log (any route) - C1
tests/tmp/test_40_search_card_actions_phase4.py:290 - the clicked card's `.card-action-status` equals home's exact text: "Disliking needs a profile. Create one from the Profile button." for dislike, "Blocking needs a profile. Create one from the Profile button." for channel and account - C1
tests/tmp/test_40_search_card_actions_phase4.py:291 - control (no clause): in the same keyless run a Like is sent as `like` for that video, so the empty log at :288 comes from a stub that does record requests
tests/tmp/test_40_search_card_actions_phase4.py:302-307 - controls (no clause): page 1 fetched, the target card has the four controls and starts with the mark the search returned; while the dislike's response is held, exactly that `dislike` has been sent and the clicked button's `disabled` is true, so :313 checks the button being re-enabled
tests/tmp/test_40_search_card_actions_phase4.py:311 - after the 400 `{"error": "Dislike limit reached (1000)"}` lands, the card's `.card-action-status` equals "Dislike limit reached (1000)" - C2
tests/tmp/test_40_search_card_actions_phase4.py:313 - the clicked button's `disabled` is False - C2
tests/tmp/test_40_search_card_actions_phase4.py:315 - the card shows the mark it had before the click (likes/dislikes `active` and both `aria-pressed`): neutral in one run, liked in the other - C2
tests/tmp/test_40_search_card_actions_phase4.py:318 - a second Dislike on the same card sends `dislike`, not `undo_dislike`, which shows the row's reaction was not changed - C2
tests/tmp/test_40_search_card_actions_phase4.py:319 - no error escapes the page during the rejected run - C2
</assertions>

<probes>
1. `ValidateTests tests/tmp/test_40_search_card_actions_phase4.py -rA --tb=line` against the current tree (phase 3 done, no key guard yet). All three C1 cases fail at :288 for the intended reason. Keyless Dislike sends `["POST","/api/user-action",{"action":"dislike","uuid":"uuid-a1","host":"peer.example"}]`. Keyless Block channel and Block account each send `["POST","/api/profile/blocks",{"kind":<kind>,"uuid":"uuid-a1","host":"peer.example"}]`. Every control before :288 passed. The search fetch maps to `[["GET","/api/v1/search/videos",None]]`, which is the value SEARCH_PAGE_1 uses. Both C2 cases (neutral and liked) pass already, because the existing catch/finally covers that path; for this phase C2 guards against regression.
2. `ValidateTests tests/tmp/test_probe_40_p4.py -s`. This bundles mutants of pages/search/index.ts through esbuild stdin (cwd = the search dir, so the source tree was not touched) and runs both checkpoint tests against each. Results, as `{case: result}`:
- current: C1 x3 FAIL:282 (the assertion now at :288), C2 x2 pass.
- guarded (home's guard `if (action !== "like" && !getProfileKey()) { say(...); return; }` added): everything passes.
- optimistic (row.reaction set before the await): C2 x2 fail at the second-click assertion (now :318).
- no_reenable (finally does not re-enable): C2 x2 fail at the disabled assertion (now :313).
- generic (`say("Action failed")`): C2 x2 fail at the status assertion (now :311).
The line numbers in that run were from before the docstring was written; the assertions moved 6 lines down. A final re-run after the docstring shows the C1 failures at :288. The probe file tests/tmp/test_probe_40_p4.py is still on disk: I have no delete tool, so it needs removing alongside the earlier test_probe_40_* files.
</probes>

<unassertable>
none. The checkpoint's other items are not test assertions: running `npx tsc --noEmit` and `npm run build`, keeping test_frontend_reactions/blocks/videos_page green, and promoting the test to tests/active/. Those are workflow runs for after implementation.
</unassertable>

### `tests/tmp/test_40_search_card_actions_phase4.py` - 20492 characters, inlined in full

```
"""A search-card Dislike or Block without a profile key asks for a profile on the card and sends nothing; a Dislike the Client rejects shows its error, gives the button back and leaves the card's reaction as it was.

`pages/search/index.ts` is bundled and run in node against the phase-2 fake DOM, with a stub fetch that records every request. Clicks land on the icon inside an icon button, or on a text button itself.

- Without a key, Dislike, Block channel and Block account each leave the stub fetch with no new request and put home's exact "Disliking needs a profile. Create one from the Profile button." or "Blocking needs a profile. Create one from the Profile button." in the clicked card's `.card-action-status`. A keyless Like in the same run is sent, so the stub does record requests.
- With a key, a Dislike on a neutral card, and in a second run on a liked one, gets a 400 `Dislike limit reached (1000)`. The button is disabled while the response is held. Once it lands, that message is in the card's status line, the clicked button's `disabled` is false, the card shows the mark it had before, and a second Dislike sends `dislike`, not `undo_dislike`.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
ENTRY = FRONTEND / "src" / "pages" / "search" / "index.ts"
BASE = "http://client.test"
PROFILE_KEY = "profileKey:v1"
KEY = "K" * 43
ACTIONS = ["like", "dislike", "channel", "account"]

# The phase-2 fake DOM, with a stub fetch that answers every reaction with USER_ACTION_STATUS and can hold the first one open.
RUNNER = r"""
const memory = (seed) => { const s = new Map(Object.entries(seed)); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)), removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory(JSON.parse(process.env.STORAGE));
globalThis.sessionStorage = memory({});
globalThis.window = { location: { origin: process.env.BASE, pathname: "/search.html", search: process.env.SEARCH }, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage,
  innerHeight: 800, scrollY: 0, history: { pushState() {}, replaceState() {} }, addEventListener() {} };

const VOID = new Set(["area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: "\"", "#39": "'" };
const decode = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (_m, e) => ENTITIES[e]);
const escapeText = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" })[c]);
const TOKEN = /<\/([\w-]+)\s*>|<([\w-]+)((?:\s+[^\s=/>]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g;
const ATTR = /([^\s=/>]+)(?:="([^"]*)")?/g;
const kebab = (k) => k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
const detach = (n) => { const p = n.parentElement; if (p) p.childNodes.splice(p.childNodes.indexOf(n), 1); n.parentElement = null; };
const text = (v) => ({ nodeType: 3, data: String(v), parentElement: null, get textContent() { return this.data; } });
const serialize = (n) => {
  if (n.nodeType === 3) return escapeText(n.data);
  const tag = n.tagName.toLowerCase();
  const attrs = Object.entries(n.attrs).map(([k, v]) => ` ${k}="${escapeText(v)}"`).join("");
  return VOID.has(tag) ? `<${tag}${attrs}>` : `<${tag}${attrs}>${n.childNodes.map(serialize).join("")}</${tag}>`;
};
const parse = (html) => {
  const root = element("template");
  const open = [root];
  for (const [, close, tag, attrs, selfClose, txt] of String(html).matchAll(TOKEN)) {
    const top = open[open.length - 1];
    if (txt !== undefined) top.append(text(decode(txt)));
    else if (close) { const i = open.findLastIndex((n) => n.tagName === close.toUpperCase()); if (i > 0) open.length = i; }
    else {
      const el = element(tag);
      for (const [, name, value] of attrs.matchAll(ATTR)) el.setAttribute(name, decode(value ?? ""));
      top.append(el);
      if (!selfClose && !VOID.has(tag.toLowerCase())) open.push(el);
    }
  }
  const nodes = [...root.childNodes];
  nodes.forEach(detach);
  return nodes;
};
// Simple and compound selectors, joined by descendant combinators or commas; anything else throws so an unsupported query fails loudly instead of matching nothing.
const COMPOUND = /^([\w-]+|\*)?((?:\.[\w-]+|\[[\w-]+(?:="[^"]*")?\])*)$/;
const matchesCompound = (el, compound) => {
  const m = COMPOUND.exec(compound);
  if (!m || !compound) throw new Error(`fake DOM: unsupported selector ${compound}`);
  if (m[1] && m[1] !== "*" && el.tagName !== m[1].toUpperCase()) return false;
  for (const [, cls, attr, value] of m[2].matchAll(/\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g)) {
    if (cls && !el.classList.contains(cls)) return false;
    if (attr && (!(attr in el.attrs) || (value !== undefined && el.attrs[attr] !== value))) return false;
  }
  return true;
};
const matches = (el, selector) => selector.split(",").some((part) => {
  const steps = part.trim().split(/\s+/);
  if (!matchesCompound(el, steps[steps.length - 1])) return false;
  let node = el.parentElement;
  for (let i = steps.length - 2; i >= 0; i -= 1) {
    while (node && !matchesCompound(node, steps[i])) node = node.parentElement;
    if (!node) return false;
    node = node.parentElement;
  }
  return true;
});
const descend = (n) => n.children.flatMap((c) => [c, ...descend(c)]);
const element = (tag) => {
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), attrs: {}, childNodes: [], parentElement: null, listeners: {}, disabled: false, value: "", style: {},
    get children() { return el.childNodes.filter((n) => n.nodeType === 1); },
    get className() { return el.attrs.class ?? ""; }, set className(v) { el.attrs.class = String(v); },
    get textContent() { return el.childNodes.map((n) => n.textContent).join(""); },
    set textContent(v) { el.replaceChildren(...(v == null || v === "" ? [] : [text(v)])); },
    get innerHTML() { return el.childNodes.map(serialize).join(""); },
    set innerHTML(v) { el.replaceChildren(...parse(v)); },
    get outerHTML() { return serialize(el); },
    // Chromium throws here for an element with no parent (NoModificationAllowedError), which is the case a detached card meets.
    set outerHTML(v) {
      const parent = el.parentElement;
      if (!parent) throw new Error("NoModificationAllowedError: This element has no parent node.");
      const nodes = parse(v);
      parent.childNodes.splice(parent.childNodes.indexOf(el), 1, ...nodes);
      for (const n of nodes) n.parentElement = parent;
      el.parentElement = null;
    },
    get isConnected() { let n = el; while (n.parentElement) n = n.parentElement; return n === document.body; },
    dataset: new Proxy({}, { get: (_t, k) => el.attrs[`data-${kebab(String(k))}`], set: (_t, k, v) => { el.attrs[`data-${kebab(String(k))}`] = String(v); return true; } }),
    classList: {
      contains: (c) => el.className.split(/\s+/).includes(c),
      add: (...cs) => { el.className = [...new Set([...el.className.split(/\s+/).filter(Boolean), ...cs])].join(" "); },
      remove: (...cs) => { el.className = el.className.split(/\s+/).filter((c) => c && !cs.includes(c)).join(" "); },
      toggle: (c, force) => { const on = force ?? !el.classList.contains(c); if (on) el.classList.add(c); else el.classList.remove(c); return on; },
    },
    append: (...items) => { for (const item of items) { const node = typeof item === "string" ? text(item) : item; detach(node); node.parentElement = el; el.childNodes.push(node); } },
    appendChild: (node) => { el.append(node); return node; },
    replaceChildren: (...items) => { for (const n of el.childNodes) n.parentElement = null; el.childNodes = []; el.append(...items); },
    remove: () => detach(el),
    insertAdjacentHTML: (position, html) => {
      const nodes = parse(html);
      if (position === "beforeend") el.append(...nodes);
      else if (position === "afterbegin") { el.childNodes.unshift(...nodes); for (const n of nodes) n.parentElement = el; }
      else throw new Error(`fake DOM: unsupported insertAdjacentHTML position ${position}`);
    },
    setAttribute: (n, v) => { el.attrs[n] = String(v); if (n === "disabled") el.disabled = true; },
    getAttribute: (n) => el.attrs[n] ?? null, hasAttribute: (n) => n in el.attrs,
    removeAttribute: (n) => { delete el.attrs[n]; if (n === "disabled") el.disabled = false; },
    addEventListener: (type, l) => { (el.listeners[type] ??= []).push(l); },
    removeEventListener: (type, l) => { el.listeners[type] = (el.listeners[type] ?? []).filter((x) => x !== l); },
    matches: (s) => matches(el, s),
    closest: (s) => { for (let n = el; n; n = n.parentElement) if (matches(n, s)) return n; return null; },
    querySelector: (s) => descend(el).find((n) => matches(n, s)) ?? null,
    querySelectorAll: (s) => descend(el).filter((n) => matches(n, s)),
    // The sentinel sits far below the viewport, so pages load only when the observer reports it in view.
    getBoundingClientRect: () => ({ top: 100000, bottom: 100000, left: 0, right: 0, width: 0, height: 0 }),
    focus() {}, select() {},
  };
  return el;
};
const byId = new Map();
globalThis.document = { title: "", body: element("body"),
  getElementById: (id) => { if (!byId.has(id)) { const el = element("div"); el.attrs.id = id; document.body.append(el); byId.set(id, el); } return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (v) => text(v), querySelector: (s) => document.body.querySelector(s), querySelectorAll: (s) => document.body.querySelectorAll(s), addEventListener() {} };
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { observers.push(callback); } observe() {} unobserve() {} disconnect() {} };

const pages = JSON.parse(process.env.PAGES);
const requests = [];
const holds = [];
let holdNextAction = process.env.HOLD_ACTION === "1";
globalThis.fetch = async (input, init = {}) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: String(init.method ?? "GET").toUpperCase(), path: url.pathname, query: Object.fromEntries(url.searchParams), body: init.body == null ? null : JSON.parse(String(init.body)) });
  const headers = { "content-type": "application/json" };
  if (url.pathname === "/api/v1/search/videos") {
    const page = pages[url.searchParams.get("q")]?.[Number(url.searchParams.get("page") ?? "1") - 1];
    return new Response(JSON.stringify(page ?? { rows: [], total: 0 }), { status: 200, headers });
  }
  if (url.pathname === "/api/user-action") {
    if (holdNextAction) { holdNextAction = false; await new Promise((resolve) => holds.push(resolve)); }
    const status = Number(process.env.USER_ACTION_STATUS);
    return new Response(JSON.stringify(status === 200 ? {} : { error: process.env.USER_ACTION_ERROR }), { status, headers });
  }
  return new Response(JSON.stringify({ error: "unexpected route" }), { status: 404, headers });
};
const errors = [];
process.on("unhandledRejection", (r) => { errors.push(String(r && r.stack || r)); });
process.on("uncaughtException", (e) => { errors.push(String(e && e.stack || e)); });
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 10)); };
// Events bubble through parentElement; a listener that throws is recorded, as a browser would report it.
const fire = (target, type) => {
  const event = { type, target, bubbles: true, defaultPrevented: false, preventDefault() { event.defaultPrevented = true; }, stopPropagation() { event.stopped = true; } };
  for (let node = target; node && !event.stopped; node = node.parentElement) {
    event.currentTarget = node;
    for (const l of [...(node.listeners[type] ?? [])]) { try { l.call(node, event); } catch (e) { errors.push(String(e && e.stack || e)); } }
  }
};
// A user clicks the icon inside an icon-only button, or the label of a text button; a disabled button dispatches no click.
const click = (target) => { for (let n = target; n; n = n.parentElement) if (n.tagName === "BUTTON" && n.disabled) return; fire(target, "click"); };
const grid = () => byId.get("search-results");
const cardOf = (key) => grid().children.find((c) => c.dataset.videoKey === key) ?? null;
const buttonOf = (key, action) => cardOf(key)?.querySelector(`[data-card-action="${action}"]`) ?? null;
const cardState = (card) => card && ({
  key: card.dataset.videoKey ?? null,
  actions: card.querySelectorAll("[data-card-action]").map((b) => b.dataset.cardAction),
  likesActive: card.querySelector(".stat.likes")?.classList.contains("active") ?? null,
  likePressed: card.querySelector("[data-card-action=\"like\"]")?.getAttribute("aria-pressed") ?? null,
  dislikesActive: card.querySelector(".stat.dislikes")?.classList.contains("active") ?? null,
  dislikePressed: card.querySelector("[data-card-action=\"dislike\"]")?.getAttribute("aria-pressed") ?? null,
  status: card.querySelector(".card-action-status")?.textContent ?? null,
});
const calls = (from) => requests.slice(from).map((r) => r.path === "/api/user-action" ? [r.method, r.path, { action: r.body?.action, uuid: r.body?.uuid, host: r.body?.host }] : [r.method, r.path, r.body]);
const press = (key, action) => { const button = buttonOf(key, action); if (button) click(button.querySelector("path") ?? button); return button; };
const step = async (key, action) => { const before = requests.length; const button = press(key, action); await settle(); return { action, pressed: Boolean(button), sent: calls(before), card: cardState(cardOf(key)) }; };

await import(process.env.BUNDLE);
await settle();
const target = process.env.TARGET;
const report = { searches: calls(0), card: cardState(cardOf(target)) };
if (process.env.SCENARIO === "keyless") {
  report.prompt = await step(target, process.env.ACTION);
  report.like = await step(target, "like");
}
if (process.env.SCENARIO === "rejected") {
  const before = requests.length;
  const button = press(target, "dislike");
  await settle();
  report.held = { pressed: Boolean(button), open: holds.length, disabled: button?.disabled ?? null, sent: calls(before) };
  for (const release of holds.splice(0)) release();
  await settle();
  report.rejected = { disabled: button?.disabled ?? null, connected: button?.isConnected ?? null, sent: calls(before), card: cardState(cardOf(target)) };
  report.again = await step(target, "dislike");
}
report.errors = errors;
process.stdout.write(JSON.stringify(report) + "\n", () => process.exit(0));
"""


def _bundle(entry: Path, out: Path) -> Path:
    run = subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"],
        capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    (out / "runner.mjs").write_text(RUNNER)
    return out


@pytest.fixture(scope="module")
def search_bundle(tmp_path_factory) -> Path:
    return _bundle(ENTRY, tmp_path_factory.mktemp("search"))


def _run(bundle: Path, scenario: str, storage: dict, rows: list, target: dict, action: str = "", status: int = 200, error: str = "") -> dict:
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""), "STORAGE": json.dumps(storage), "SEARCH": f"?q={QUERY}",
             "PAGES": json.dumps({QUERY: [{"rows": rows, "total": len(rows)}]}), "SCENARIO": scenario, "TARGET": _key(target), "ACTION": action,
             "USER_ACTION_STATUS": str(status), "USER_ACTION_ERROR": error, "HOLD_ACTION": "1" if scenario == "rejected" else "0"},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


def _row(tag: str, reaction: str | None = None) -> dict:
    return {"video_id": tag, "video_uuid": f"uuid-{tag}", "instance_domain": "peer.example", "channel_id": "7", "account_url": "https://peer.example/accounts/alice", "title": f"video {tag}", "reaction": reaction}


def _key(row: dict) -> str:
    return f"{row['instance_domain']}::{row['video_uuid']}"


def _sent(action: str, row: dict) -> list:
    return ["POST", "/api/user-action", {"action": action, "uuid": row["video_uuid"], "host": row["instance_domain"]}]


def _marks(card: dict) -> tuple:
    return card["likesActive"], card["likePressed"], card["dislikesActive"], card["dislikePressed"]


NEUTRAL = (False, "false", False, "false")
LIKED = (True, "true", False, "false")
QUERY = "music"
SEARCH_PAGE_1 = [["GET", "/api/v1/search/videos", None]]
LIMIT_ERROR = "Dislike limit reached (1000)"  # the Client backend's 400 body for the dislike cap


@pytest.mark.parametrize(("action", "prompt"), [
    ("dislike", "Disliking needs a profile. Create one from the Profile button."),
    ("channel", "Blocking needs a profile. Create one from the Profile button."),
    ("account", "Blocking needs a profile. Create one from the Profile button."),
])
def test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing(search_bundle, action, prompt):
    target = _row("a1")
    rows = [target, _row("a2")]
    page = _run(search_bundle, "keyless", {}, rows, target, action=action)

    # control: no key, so only page 1 was fetched and the target card carries the four controls, unmarked
    assert page["searches"] == SEARCH_PAGE_1, page["searches"]
    assert page["card"]["actions"] == ACTIONS and _marks(page["card"]) == NEUTRAL, page["card"]
    assert page["prompt"]["pressed"] is True, page["card"]

    # A page with no key guard sends the dislike or the block; one that guards only Dislike sends the block.
    assert page["prompt"]["sent"] == [], (page["prompt"], page["errors"])  # C1
    # A page that sends and shows the server's error, or a prompt worded differently from home's, fails here.
    assert page["prompt"]["card"]["status"] == prompt, (page["prompt"], page["errors"])  # C1
    # control: in the same run, a keyless Like is sent and recorded, so the empty list above is not a fetch stub that records nothing
    assert page["like"]["sent"] == [_sent("like", target)], (page["like"], page["errors"])
    assert page["errors"] == [], page["errors"]


@pytest.mark.parametrize(("reaction", "mark"), [(None, NEUTRAL), ("liked", LIKED)])
def test_a_dislike_rejected_with_400_shows_the_error_re_enables_the_button_and_keeps_the_card_mark(search_bundle, reaction, mark):
    target = _row("a1", reaction)
    rows = [_row("a0"), target, _row("a2")]
    page = _run(search_bundle, "rejected", {PROFILE_KEY: KEY}, rows, target, status=400, error=LIMIT_ERROR)

    # control: page 1 was fetched and the target card shows the mark the search returned
    assert page["searches"] == SEARCH_PAGE_1, page["searches"]
    assert page["card"]["actions"] == ACTIONS and _marks(page["card"]) == mark, page["card"]
    # control: the dislike left and, while its response is held, the button is disabled, so "enabled" below is the button coming back
    assert page["held"]["pressed"] is True and page["held"]["open"] == 1, page["held"]
    assert page["held"]["sent"] == [_sent("dislike", target)], (page["held"], page["errors"])
    assert page["held"]["disabled"] is True, page["held"]

    # A page that shows a generic failure, or nothing, fails here.
    assert page["rejected"]["card"]["status"] == LIMIT_ERROR, (page["rejected"], page["errors"])  # C2
    # A page that re-enables only on success leaves the clicked button disabled.
    assert page["rejected"]["disabled"] is False, page["rejected"]  # C2
    # A page that marks the row before the request, or redraws the card from a reaction it set, shows disliked or neutral here.
    assert _marks(page["rejected"]["card"]) == mark, page["rejected"]["card"]  # C2
    # The row's reaction is unchanged: a row left marked disliked would make this click send undo_dislike.
    assert page["again"]["pressed"] is True, page["again"]  # control: the card still has its Dislike button
    assert page["again"]["sent"] == [_sent("dislike", target)], (page["again"], page["errors"])  # C2
    assert page["errors"] == [], page["errors"]  # C2

```


Gate: satisfied

## 2026-10-01 - Step 7 - Phase 4 (No-key guard, failures and dist rebuild) - red (audit round 1)

`tests/tmp/test_40_search_card_actions_phase4.py` exited 1.

```
  tests/tmp/test_40_search_card_actions_phase4.py  3 failed, 2 passed                     0.0s
  -----------------------------------------------
  total                                            3 failed, 2 passed                     2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 4 (No-key guard, failures and dist rebuild) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 1 UNCARRIED clause(s) - C2e; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
All three cases of `test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing` should fail at line 288, `assert page["prompt"]["sent"] == []`, because `runCardAction` in `client/frontend/src/pages/search/index.ts:247-293` has no profile-key guard. For `dislike`, the list holds `["POST", "/api/user-action", {"action": "dislike", ...}]`. For `channel` and `account`, it holds `["POST", "/api/profile/blocks", {"kind": ..., "uuid": "uuid-a1", "host": "peer.example"}]`. Both cases of `test_a_dislike_rejected_with_400_shows_the_error_re_enables_the_button_and_keeps_the_card_mark` look likely to pass on the code as it stands, for three reasons:
- the catch at index.ts:289-290 shows `error.message`, which is the `{error}` body that `sendUserAction` passes on;
- `finally` re-enables the button at index.ts:292;
- `row.reaction` is set only after the awaited send succeeds (index.ts:268).

NOT ASSESSED
1. `client/frontend/dist/` was not read. The test bundles `client/frontend/src/pages/search/index.ts` with esbuild and never loads the built output, so dist is outside the test's path.
2. `tests/tmp/test_frontend_search_card_actions.py`, which `code_under_test` lists, was not read. The test under audit does not import it or rely on it.
3. I couldn't tell from the files which behaviour came before this phase, so I couldn't confirm whether C2 was red before the phase. The stub question for C2 was answered from the assertion form: each C2 assertion fails against a named wrong implementation.
   - Line 311 catches a page that shows a generic message or nothing. `LIMIT_ERROR` differs from every default in the code ("Failed to send action", "Action failed", "Dislike failed").
   - Line 313 catches a page that re-enables the button only on success. Line 308 confirms the button was disabled while the response was held.
   - Line 315 catches optimistic marking. It runs at two reactions (NEUTRAL, LIKED), so resetting the card to neutral also fails.
   - Line 318 catches a page that sets `row.reaction` before the request.

   For C1:
   - A do-nothing stub fails at line 290, where the prompt text is required, and at line 292, where the keyless Like must be sent.
   - A guard on Dislike alone fails the `channel` and `account` cases at line 288.
   - One prompt hard-coded for all three actions fails line 290, because the Disliking and Blocking prompts differ.

   No `<anti_pattern>` entry matched:
   - The negative at line 288 is paired with the positive assertions at lines 290 and 292.
   - `LIMIT_ERROR` is set at line 300 and asserted at line 311, but `sendUserAction` and `runCardAction`'s catch handle it in between, so it is not an echoed literal.

   The test sits at rung 1: production code runs in node, and the test asserts on DOM state and recorded requests. There is no downshift.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | without a key, Dislike, Block channel and Block account "each write home's exact profile prompt" | :290 | a guard on Dislike only, the server's error shown instead of the prompt, or a prompt worded differently from home's (`pages/videos/index.ts:409`); exact equality, one parametrize case per action | CARRIED |
| C1b | must_prove | "send no request" for each of the three | :288 | an unguarded page sending the dislike or block; :292 shows the stub does record requests | CARRIED |
| C2a | must_prove | a rejected card-action request "shows its error message" | :311 | a generic failure text, or nothing, in the card's status line | CARRIED |
| C2b | must_prove | "re-enables the button" | :313 (with :308, :318) | re-enabling only on success; :308 shows the button was disabled first | CARRIED |
| C2c | must_prove | "leaves the row's reaction unchanged": the card mark | :315 | an optimistic dislike mark left in place, or a revert that redraws to neutral on the liked run | CARRIED |
| C2d | must_prove | "leaves the row's reaction unchanged": the row state behind later actions | :318 | `row.reaction` set to `disliked` before the request, which would send `undo_dislike`. It does not exclude a liked row's reaction cleared to `null` without a redraw | CARRIED |
| C2e | must_prove | the same three facts for a rejected Like, Block channel or Block account request | none | nothing. The rejected scenario only ever presses `dislike` (runner :209) | UNCARRIED |
| D1 | docstring | "a search-card Dislike or Block without a profile key asks for a profile on the card" | :290 | prompt written to the page status line instead of the clicked card's `.card-action-status` | CARRIED |
| D2 | docstring | "and sends nothing" | :288 | any request on the keyless path | CARRIED |
| D3 | docstring | "A keyless Like in the same run is sent" | :292 | a fetch stub that records nothing, or a guard that also blocks Like | CARRIED |
| D4 | docstring | "on a neutral card, and in a second run on a liked one" | :304 | a fixture that does not render the starting mark it claims | CARRIED |
| D5 | docstring | "The button is disabled while the response is held" | :308 | no in-flight disable | CARRIED |
| D6 | docstring | "that message is in the card's status line" | :311 | a generic or missing message | CARRIED |
| D7 | docstring | "the clicked button's `disabled` is false" | :313 | a button left disabled on failure | CARRIED |
| D8 | docstring | "the card shows the mark it had before" | :315 | an unreverted optimistic mark | CARRIED |
| D9 | docstring | "a second Dislike sends `dislike`, not `undo_dislike`" | :318 | the row flipped to disliked before the request | CARRIED |
| D10 | docstring | "Clicks land on the icon inside an icon button, or on a text button" | :307, :292 | a handler that matches only when `event.target` is the button itself, so nothing is sent | CARRIED |
| N1 | name | "without a key" | :283 | a run where a key leaked into storage; the control asserts the keyless page-1 fetch | CARRIED |
| N2 | name | "dislike and block write the profile prompt on the card" | :290 | wrong or missing prompt on the card | CARRIED |
| N3 | name | "and send nothing" | :288 | a request sent | CARRIED |
| N4 | name | "a dislike rejected with 400 shows the error" | :311 | a generic or missing error | CARRIED |
| N5 | name | "re-enables the button" | :313 | a button left disabled | CARRIED |
| N6 | name | "keeps the card mark" | :315 | an unreverted mark | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase4.py:209
   `const button = press(target, "dislike");`
   - **What C2 claims:** "A rejected card-action request shows its error message, re-enables the button and leaves the row's reaction unchanged." A card has four actions: like, dislike, channel and account (`ACTIONS`, :23).
   - **What the test does:** the rejected scenario hard-codes Dislike as the only action it rejects. The test at :297 is parametrized over the starting reaction only, never over the action.
   - **What gets through:** a page whose Like path changes `row.reaction` or redraws the card before the request is sent, or whose Block path loses the error or leaves its button disabled, passes this test.
   - **What the rule requires:** "a claim naming a set" asserts every member of the set. Here only one of the four rejected actions is asserted. That is C2e.

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase4.py:318
   C2d is carried only against a flip to `disliked`. On the `liked` run, a page that clears `row.reaction` to `null` on rejection without redrawing still passes:
   - :315 still sees the old DOM.
   - :318 still sends `dislike`, which is the same request from liked or from neutral.

   A Like pressed after the rejection would tell these apart: `undo_like` versus `like`.
2. bounds (rules/testing.md) — tests/tmp/test_40_search_card_actions_phase4.py:280
   "Without a profile key" is exercised only as an absent storage entry (`{}`). A stored empty string or a malformed key under `profileKey:v1` is untested.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_frontend_search_card_actions.py. That path does not resolve, so it was not read.
2. `code_under_test` listed client/frontend/dist/ (REBUILT). It was not read: the test bundles `src/pages/search/index.ts` directly with esbuild (:19, :224), so dist is not exercised by this test.
3. `fixtures_path` was not supplied. The only fixture, `search_bundle` (:233), is defined in the test file. No conftest was needed to judge independence.

## 2026-10-01 - Step 7 - Phase 4 (No-key guard, failures and dist rebuild) - self-check (audit round 2, send-back 0)

`tests/tmp/test_40_search_card_actions_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_40_search_card_actions_phase4.py:294 — for each of dislike, channel and account with no profile key, the click adds no request to the stub's log. Also :296 — the clicked card's `.card-action-status` equals home's exact prompt. The control at :298 shows the stub records a keyless Like in the same run. - expected: :294 `[]`. :296 "Disliking needs a profile. Create one from the Profile button." for dislike, and "Blocking needs a profile. Create one from the Profile button." for channel and account. - excludes: The current unguarded page sends `["POST","/api/user-action",{"action":"dislike",...}]` for dislike and `["POST","/api/profile/blocks",{"kind":...}]` plus the follow-up dislike for a block, and fails :294 in all three cases (observed). A guard on Dislike only fails the channel and account cases at :294. One prompt hard-coded for every action, or the server's error shown instead, fails :296.
- C2 - tests/tmp/test_40_search_card_actions_phase4.py:324/:326/:328/:330/:333/:334, over like/dislike/channel/account × neutral/liked, after that action's request is rejected. :324 the card is still on the grid. :326 the status line equals the action's error. :328 the clicked button is enabled; :321 shows it was disabled while held. :330 the card's like/dislike marks are as they were. :333 a following Dislike then Like send `dislike` then `like` (neutral) or `dislike` then `undo_like` (liked). :334 no error escapes. - expected: Status "Video not found in Engine" for like, "Dislike limit reached (1000)" for dislike, "Block limit reached (1000)" for channel and account. `disabled` False. Marks NEUTRAL or LIKED as the run started. :333 gives `[[dislike],[like]]` from neutral and `[[dislike],[undo_like]]` from liked. - excludes: Each observed with a mutant probe. Setting `row.reaction` before the like request fails :333 in both like cases. Redrawing the like before the request fails :326, because the redraw wipes the status. Flipping the row to disliked before a block fails :333 in all block cases. Removing the source's rows before the block is accepted fails :324. Dropping the re-enable in `finally` fails :328 in all 8 cases. A generic "Action failed" fails :326 in all 8. Clearing a liked row to null on rejection fails :333 in the liked cases. Setting the row to disliked before the dislike request fails :333.

<items>
<item id="C2e">
<disposition>fixed</disposition>
<what>The rejected scenario is now parametrized over the action as well as the starting reaction: like, dislike, channel and account, each on a neutral card and on a liked one, so 8 cases. Each action is rejected with the Client backend's own body for that action: Like gets 404 "Video not found in Engine" (server.py:794), Dislike gets 400 "Dislike limit reached (1000)" (:816), and a Block gets 400 "Block limit reached (1000)" (:992). To make that possible the runner's stub now answers `/api/profile/blocks` as well as `/api/user-action` with ACTION_STATUS/ACTION_ERROR, holds whichever of the two comes first, and presses `process.env.ACTION` instead of a hard-coded "dislike". The three facts are carried for every action. :326 checks that the card status equals that action's error, which excludes a generic or missing message on any path. :328 checks the clicked button's `disabled` is false; :321 shows it was true while the response was held. Together they exclude a Like or Block path that only re-enables on success. :330 checks the mark is unchanged, which excludes an optimistic like or dislike redraw. :324 checks the card is still on the grid, which excludes a Block that removes the source's cards before it is accepted. :333 checks what a following Dislike then Like send: `dislike` then `like` from neutral, `dislike` then `undo_like` from liked. That excludes any optimistic change to `row.reaction` on any action's path. Probe runs against mutants: an optimistic like fails at :333 in both like cases, an optimistic like redraw fails at :326, a block that flips the row to disliked first fails at :333 in all four block cases, a block that removes rows first fails at :324 in all four, no re-enable fails at :328 in all 8, and a generic message fails at :326 in all 8. The test name became `test_a_rejected_card_action_shows_the_error_re_enables_the_button_and_keeps_the_reaction`. Its second docstring bullet now names all four actions and their errors.</what>
</item>
</items>

<findings_addressed>
Claim CRITICAL 1 (whole-claim, :209 rejected scenario only presses dislike): fixed. The runner presses `process.env.ACTION`, the stub rejects both the reaction route and the block route, and the test is parametrized over like/dislike/channel/account × neutral/liked. That puts all four members of the set under :324/:326/:328/:330/:333. Mutant probes confirm Like-path and Block-path wrong implementations now fail.
Claim RECOMMENDATION 1 (C2d misses a liked row cleared to null): taken. After the rejection the test now presses Dislike and then Like, and :333 requires the Like to send `undo_like` from a liked card. A mutant that sets `row.reaction = null` in the catch passed before. It now fails at :333 in all four liked cases and still passes the neutral ones, which is correct.
Claim RECOMMENDATION 2 (empty or malformed stored key): not taken. C1 is about the absent-key path that home guards. How an empty string or a malformed key should behave is not a clause of this phase.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_40_search_card_actions_phase4.py:294 — for each of dislike, channel and account with no profile key, the click adds no request to the stub's log. Also :296 — the clicked card's `.card-action-status` equals home's exact prompt. The control at :298 shows the stub records a keyless Like in the same run.</assertion>
<expected>:294 `[]`. :296 "Disliking needs a profile. Create one from the Profile button." for dislike, and "Blocking needs a profile. Create one from the Profile button." for channel and account.</expected>
<wrong_implementation>The current unguarded page sends `["POST","/api/user-action",{"action":"dislike",...}]` for dislike and `["POST","/api/profile/blocks",{"kind":...}]` plus the follow-up dislike for a block, and fails :294 in all three cases (observed). A guard on Dislike only fails the channel and account cases at :294. One prompt hard-coded for every action, or the server's error shown instead, fails :296.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_40_search_card_actions_phase4.py:324/:326/:328/:330/:333/:334, over like/dislike/channel/account × neutral/liked, after that action's request is rejected. :324 the card is still on the grid. :326 the status line equals the action's error. :328 the clicked button is enabled; :321 shows it was disabled while held. :330 the card's like/dislike marks are as they were. :333 a following Dislike then Like send `dislike` then `like` (neutral) or `dislike` then `undo_like` (liked). :334 no error escapes.</assertion>
<expected>Status "Video not found in Engine" for like, "Dislike limit reached (1000)" for dislike, "Block limit reached (1000)" for channel and account. `disabled` False. Marks NEUTRAL or LIKED as the run started. :333 gives `[[dislike],[like]]` from neutral and `[[dislike],[undo_like]]` from liked.</expected>
<wrong_implementation>Each observed with a mutant probe. Setting `row.reaction` before the like request fails :333 in both like cases. Redrawing the like before the request fails :326, because the redraw wipes the status. Flipping the row to disliked before a block fails :333 in all block cases. Removing the source's rows before the block is accepted fails :324. Dropping the re-enable in `finally` fails :328 in all 8 cases. A generic "Action failed" fails :326 in all 8. Clearing a liked row to null on rejection fails :333 in the liked cases. Setting the row to disliked before the dislike request fails :333.</wrong_implementation>
</row>
</rows>

<answers>
1. No. The only negative, :294, is paired with :296 (prompt written) and :298 (the stub records a keyless Like). :324 is a presence check, not an absence.
2. No. The error texts go into the stub's response body and come back through `sendUserAction`/`blocks.request` and the catch at index.ts:290. Deleting that `say(error.message)` turns :326 red, which the "generic" mutant confirmed. The expected first request at :313 is chosen from the parametrize literals and only feeds the control at :320. It does not reproduce the C2 behaviour.
3. No. C2's observables are read across 4 actions × 2 starting reactions with three distinct error texts. C1 is read across 3 actions with two distinct prompts.
4. No. The doubles are fetch at the network edge and a fake DOM. pages/search/index.ts and every data module it imports (reactions, user-actions, blocks, profile) run for real from the esbuild bundle.
5. Yes. The run collected 11 items: 3 C1 cases and 8 C2 cases. All names bind: `_blocked`, BLOCK_LIMIT_ERROR, NOT_FOUND_ERROR, and the runner env ACTION/ACTION_STATUS/ACTION_ERROR.
6. Yes. I ran the test on the current tree: the C1 cases fail at :294, and all 8 C2 cases pass. Their request shapes come from that run: the held block request has the `/api/profile/blocks` body `{kind, uuid, host}`. I also ran the probe with ten mutants (results under C2 in rows). The error strings come from the backend source (server.py:794/:816/:992) and are fed in by the stub. That they show up in the status line was observed.
7. Yes. C1 is still red only at :294, because the page has no key guard: the keyless dislike and block are sent. With home's guard spliced in, all 11 pass. As before, C2 passes on the current tree because the catch/finally path already holds, so for this phase it guards against regression. Housekeeping: I had no delete tool, so tests/tmp/test_probe_40_p4.py (rewritten for this round) and the earlier test_probe_40_* files are still on disk and need removing.
</answers>

<exemptions>
none
</exemptions>

Gate: satisfied

## 2026-10-01 - Step 7 - Phase 4 (No-key guard, failures and dist rebuild) - red (audit round 2)

`tests/tmp/test_40_search_card_actions_phase4.py` exited 1.

```
  tests/tmp/test_40_search_card_actions_phase4.py  3 failed, 8 passed                     0.0s
  -----------------------------------------------
  total                                            3 failed, 8 passed                     5.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 4 (No-key guard, failures and dist rebuild) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
All three parametrizations of `test_without_a_key_dislike_and_block_write_the_profile_prompt_on_the_card_and_send_nothing` should fail at line 294, `assert page["prompt"]["sent"] == []`. `runCardAction` in `client/frontend/src/pages/search/index.ts:247-293` never checks for a profile key. Without a key, `dislike` sends `["POST", "/api/user-action", {...}]` through `sendReaction`, and `channel` and `account` send `["POST", "/api/profile/blocks", {...}]` through `blockVideoSource`. The eight cases of `test_a_rejected_card_action_shows_the_error_re_enables_the_button_and_keeps_the_reaction` should pass as the code stands. The `catch` at index.ts:289-290 puts the thrown `payload.error` in `.card-action-status`. The `finally` at index.ts:291-292 turns the button back on. The card is only redrawn after the request is accepted. So a green C2 here is expected, and it is not evidence of a stub.

Anti-patterns pass (rules/shape.md):
- **doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep:** don't apply. The test reads no `.md` file and no extracted section. Every assertion is on the JSON report the bundled page emits.
- **hardcoded-spec-mirror:** doesn't apply. The prompt literals at lines 279-281 and `ACTIONS` at line 23 are compared against rendered card state (lines 290, 296), not against a code constant.
- **tautological-assertion:** doesn't apply. `_sent` and `_blocked` (lines 257-262) build the expected requests from the test's own row fixture. They do not re-derive the page's logic.
- **absence-only-assertion:** doesn't apply. The empty list at line 294 comes with a positive assertion on the prompt text (line 296) and a control in the same run (line 298) where a keyless Like is recorded.
- **echoed-literal:** doesn't apply. `ACTION_ERROR` goes into the stub fetch and shows up at line 326 only after passing through `sendUserAction`/`blockVideoSource` parsing and the page's `catch`/`say`. Deleting index.ts:290 turns it red.
- **single-value-pin:** doesn't apply. There are three different error strings across four actions, two different prompts, and two starting reactions. Each starting reaction expects a different follow-up request (`like` vs `undo_like`, line 333). The disabled-false assertion at line 328 is set against a held-request check at line 321 that requires the button to be disabled.

Ladder pass (rules/shape.md `<ladder>`):
- **Rung:** the test bundles the real entry point, runs it as a node subprocess, drives clicks and asserts on observed side effects (requests sent, status text, `disabled`, card marks). That is rung 1/2 behaviour invocation, the highest rung this invariant supports.
- **Anti-rung and downshift:** the test is not on the anti-rung and does not downshift.

Stub question:
- **Keyless guard on Dislike only:** fails the `channel` and `account` cases at line 294.
- **Page that sends nothing for any action:** fails the control at line 298.
- **Hard-coded or generic error message:** fails line 326 for at least one parametrization.
- **Re-enabling only on success:** fails line 328.
- **Marking the card optimistically, or changing the row's reaction:** fails line 330 or line 333.

NOT ASSESSED
1. `client/frontend/dist/ (REBUILT)` was not read. The test bundles `src/pages/search/index.ts` with esbuild itself (lines 222-235) and never loads `dist/`.
2. `tests/tmp/test_frontend_search_card_actions.py`, listed in `code_under_test`, was not read. The audited test does not import from it or rely on it.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | without a key, Dislike, Block channel and Block account "each write home's exact profile prompt" | :296 | a guard on Dislike only; the server's error shown instead of the prompt; a prompt worded differently from home's (`pages/videos/index.ts:409`). Exact equality, one parametrize case per action (:278-282) | CARRIED |
| C1b | must_prove | "send no request" for each of the three | :294 | an unguarded page sending the dislike or block. :298 shows the stub records requests | CARRIED |
| C2a | must_prove | a rejected card-action request "shows its error message" | :326 | a generic failure text, or nothing, in the card's status line | CARRIED |
| C2b | must_prove | "re-enables the button" | :328 (with :321) | re-enabling only on success. :321 shows the button was disabled while the response was held | CARRIED |
| C2c | must_prove | "leaves the row's reaction unchanged": the card mark | :330 | an optimistic mark left in place, or a redraw to neutral on the liked run | CARRIED |
| C2d | must_prove | "leaves the row's reaction unchanged": the row state behind later actions | :333 | a row left `disliked` (sends `undo_dislike`); a liked row cleared to `null` (sends `like`, not `undo_like`); a neutral row left `liked` (sends `undo_like`). This closes the gap noted on round one | CARRIED |
| C2e | must_prove | the same three facts for a rejected Like, Block channel or Block account request | :326, :328, :330, :333 under the :302-307 parametrize | a revert, re-enable or error display wired only on the Dislike branch. Every action now runs through all four assertions, on a neutral row and on a liked one | CARRIED |
| D1 | docstring | "a search-card Dislike or Block without a profile key asks for a profile on the card" | :296 | the prompt written to the page status line instead of the clicked card's `.card-action-status` | CARRIED |
| D2 | docstring | "and sends nothing" | :294 | any request on the keyless path | CARRIED |
| D3 | docstring | "A keyless Like in the same run is sent" | :298 | a fetch stub that records nothing, or a guard that also blocks Like | CARRIED |
| D4 | docstring | "on a neutral card and in a second run on a liked one" | :317 (with the :308 parametrize) | a fixture that does not render the starting mark it claims | CARRIED |
| D5 | docstring | "The button is disabled while the response is held" | :321 (with :319) | no in-flight disable | CARRIED |
| D6 | docstring | "that message is in the card's status line" | :326 | a generic or missing message | CARRIED |
| D7 | docstring | "the clicked button's `disabled` is false" | :328 | a button left disabled on failure | CARRIED |
| D8 | docstring | "the card ... showing the mark it had before" | :330 | an unreverted optimistic mark | CARRIED |
| D9 | docstring | "a Dislike then a Like on it send `dislike` then `like` from a neutral card, `dislike` then `undo_like` from a liked one" (reworded and widened from round one's "a second Dislike sends `dislike`") | :333 | a row reaction moved before the request, or cleared on failure | CARRIED |
| D10 | docstring | "Clicks land on the icon inside an icon button, or on a text button itself" | :320, :298 (runner :196 clicks the `path` when one exists) | a handler that matches only when `event.target` is the button itself, so nothing is sent | CARRIED |
| N1 | name | "without a key" | :296 (setup :286 passes empty storage) | a run where a key reached storage. That run would send the request rather than show the prompt. The :289 control does not separate keyed from keyless (see OBSERVATIONS) | CARRIED |
| N2 | name | "dislike and block write the profile prompt on the card" | :296 | a wrong or missing prompt on the card | CARRIED |
| N3 | name | "and send nothing" | :294 | a request sent | CARRIED |
| N4 | name | "a rejected card action shows the error" (widened from "a dislike rejected with 400") | :326 | a generic or missing error, for any of the four actions | CARRIED |
| N5 | name | "re-enables the button" | :328 | a button left disabled | CARRIED |
| N6 | name | "keeps the reaction" (widened from "keeps the card mark") | :330, :333 | an unreverted mark, or a row reaction changed behind an unchanged mark | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase4.py:289
   `assert page["searches"] == SEARCH_PAGE_1` is labelled as the keyless control, but the keyed test asserts the same value at :316. `calls()` (runner :195) records only method, path and body, with no headers. So this line cannot tell a keyless page from a keyed one. N1 is still carried by :296, because the prompt only appears on the keyless path. The comment at :288 overstates what :289 shows.
2. whole-claim (rules/testing.md): tests/tmp/test_40_search_card_actions_phase4.py:6
   The docstring says each rejection is "the Client backend's own error". The test supplies those strings itself through the stub (:273-275, runner :165). Nothing here checks them against the backend, so this phrase describes the fixture, not a fact the test proves. No ledger row covers it.
3. Prose changes since round one. N4, N6 and D9 were all reworded to widen them, not narrow them, and each widened clause has an assertion that carries it (:326, :330, :333). No row was withdrawn. The docstring adds "the card is still on the grid", which :324 carries.

NOT ASSESSED
1. `code_under_test` lists client/frontend/dist/ (rebuilt output). The test bundles `src/pages/search/index.ts` directly (:19, :224), so the dist output was not read.
2. tests/tmp/test_frontend_search_card_actions.py is listed in `code_under_test` but this test does not exercise it. It was not read.
3. `renderVideoCard` and `sendReaction` / `blockVideoSource` (imported modules) were not read. Which buttons hold an icon `path` is taken from runner :196 and not confirmed against the markup.

## 2026-10-01 - Step 7 - Phase 4 (No-key guard, failures and dist rebuild) - checkpoint outcome (run 1)

`tests/tmp/test_40_search_card_actions_phase4.py` exited 0 after the phase landed.

<changes>
### client/frontend/src/pages/search/index.ts
- `runCardAction` now starts with home's no-key guard, word for word. If there is no profile key, Dislike, Block channel and Block account write `Disliking needs a profile. Create one from the Profile button.` or `Blocking needs a profile. Create one from the Profile button.` into the card's `.card-action-status`. They then return before the button is disabled and before any request is sent. Like is not guarded, as on home.
- `getProfileKey` is now imported next to `ProfileKeyRejectedError` from `../../data/profile`.
- C2 needed no new code. The existing order already covers it: send the request, set `row.reaction` and redraw only after it resolves, show `error.message` in the `catch`, and set `button.disabled = false` in the `finally`. A rejected request leaves the row's reaction alone. A block that fails never reaches `removeRows`, so the card stays on the grid.

### client/frontend/dist/
Not rebuilt in this turn because I have no shell. The operator chose to rebuild it by hand with `cd client/frontend && npm run build`. The checkpoint bundles from `src` and never reads `dist`, so it does not wait on the rebuild. Until the rebuild is done, the served `dist/assets/search-*.js` lacks this guard and the phase-3 card actions.

### tests/tmp/test_frontend_search_card_actions.py
Not touched. It does not exist in the worktree, and the phase-4 checkpoint covers both clauses.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_40_search_card_actions_phase4.py  11 passed                              0.0s
  -----------------------------------------------
  total                                            11 passed                              5.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_40_search_card_actions_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_40_search_card_actions_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_40_search_card_actions_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_40_search_card_actions_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_40_search_card_actions_phase3.py`
- P4C1 - carried - rests on: the last audit of `tests/tmp/test_40_search_card_actions_phase4.py`
- P4C2 - carried - rests on: the last audit of `tests/tmp/test_40_search_card_actions_phase4.py`

## 2026-10-01 - Step 8 - refactor pass

<refactors>
client/frontend/src/pages/search/index.ts — in `runCardAction`, renamed the local `status` (the card's `.card-action-status` element) to `cardStatus`. It was shadowing the module-level `status` (`#search-status`) that `setStatus` writes to. Behaviour is unchanged: the only uses are the declaration and the `say` closure, and grep shows no other `status` reference inside the function.
</refactors>

<left_out>
Merging the like and dislike branches in `runCardAction` into one toggle branch: the two branches copy home's structure in `pages/videos/index.ts` line for line, and the merge would build the action as `undo_${action}`, which has to type-check against `ReactionAction`. I have not run tsc to confirm that, so I left it. Pulling the parts shared with home's `runCardAction` (the no-key guard, the `say` helper, the block-follow-up dislike and the channel/account match predicate) into a shared module: that would touch `pages/videos/index.ts` and add a new file, both outside this build's files. It is a candidate for its own issue. video-card.ts: phase 1 only added the Dislike `aria-pressed` attribute, which matches the Like button and needed no refactor. The older duplication in `videoPageUrl` (channel label resolution, `resolveVideoId` order) and the unused `replace` argument of `pushUrl` were there before this build, so I left them alone. client/frontend/dist/ was not rebuilt (I have no shell); `cd client/frontend && npm run build` is still owed. tests/tmp/test_probe_40_p2_impl.py from phase 2 is still there and should be deleted. The pass rules slot in the step prompt came through as a literal `{rat_tail_rules}` placeholder. I worked to the role's rat-tail rule instead: this build makes no deliberate simplifications, so no `rat-tail:` comment is owed.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
Read against the code, the four phases' changes are already minimal and follow home's card-action pattern; the only safe refactor in scope was removing a variable that shadowed the module-level `status`. I have not run the checkpoints or tsc after the rename; the workflow's run will confirm it.
</observation>

## 2026-10-01 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 2 of 46 test groups (44 unchanged):
  test_frontend_reactions.py — changed
  test_search_fusion.py — no map entry
  test_frontend_reactions.py  7 passed                              25.0s
  test_search_fusion.py       10 passed                              2.4s
  --------------------------
  total                       17 passed                             25.2s wall, 2 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 9 - document triage

- [ ] `client/frontend/README.md` - The "What it does" list has no bullet on the card action buttons for either grid; line 16 only covers the reaction marks. Add a bullet after line 16 that describes what was delivered. Home feed and search cards with a video key carry Like, Dislike, Block channel and Block account. Like works without a profile key. Dislike and the Block buttons need one, and without it they write "Disliking/Blocking needs a profile. Create one from the Profile button." into the card's status line and send no request. On home, Dislike or Block removes the affected cards and there is no undo. On search, Dislike toggles between `dislike` and `undo_dislike` and the card stays on the page, marked, because search is not filtered by dislikes; a like replaces a dislike and a dislike replaces a like. A Block on search removes every loaded card from that channel (`instance_domain` + `channel_id`) or account (`account_url`) and fetches the next page if the grid has become too short. "Showing N of M matched videos." keeps counting fetched rows. If the dislike that follows a block fails, the card says so and no cards are removed. A failed action, a rejected profile key included, shows its message in that card's status line and the button is re-enabled. Like and Dislike both carry `aria-pressed`.
- [ ] `docs/project/roadmap.md` - F13-M2 (line 54) still reads as fully open. Its feed-grid and search-grid parts are now in the tree, so reword it to leave only the channels-page block controls open. Add a Delivered entry (section starting at line 7) that names issue `40` and plan `20-40-search-card-actions` at its archive path, `docs/project/plans/archive/20-40-search-card-actions.md`, for the search-grid controls (Like, Dislike toggle, Block channel/account). Also note that the feed-grid controls were already present with no Delivered entry; the delivering change could not be traced from the docs.
- [ ] `docs/project/issues/40-search-card-actions.md` - Set the Status line to `Status: enhancement, complete`. Append a comment that names the delivering plan `20-40-search-card-actions` and records two things. First, a rejected profile key during a card action shows as that card's status-line message, not `keyRejectedNotice`, and the data layer was left unchanged; this is the operator's decision and overrides the brief's Errors bullet at line 40. Second, the no-key prompt keeps home's exact "Create one from the Profile button." wording even though search.html has no Profile button. Then move the file to `docs/project/issues/archive/`.
- [ ] `docs/project/plans/20-40-search-card-actions.md` - The workflow re-renders its Impacts and Documentation sections from the run state, so it needs no hand edits; its header says manual edits are overwritten. On delivery, move it to `docs/project/plans/archive/` (issue-tracker.md line 29) so the roadmap's Delivered entry and the issue comment point at the archived path.

Out of scope:
_none - this build changes no documented behaviour._

ADR conflicts: none

## 2026-10-01 - Step 9 - Update documentation

- [x] `client/frontend/README.md` - updated: Added two "What it does" bullets on the card action buttons (Like, Dislike, Block channel, Block account) on home feed and search cards.
- [x] `docs/project/roadmap.md` - updated: Added a Delivered entry for the F13-M2 search card controls (issue `40`) and cut F13-M2 down to the channels-page block controls.
- [x] `docs/project/issues/40-search-card-actions.md` - updated: Closed issue 40 as delivered: set the Status line to `enhancement, complete`, added a delivery comment and wrote the file to `docs/project/issues/archive/`, but the original is still in `issues/` and has to be deleted by hand.
- [x] `docs/project/plans/20-40-search-card-actions.md` - updated: I made no edit to the plan's content, and I could not move the file: it is still at `docs/project/plans/20-40-search-card-actions.md` and needs a `git mv` into `docs/project/plans/archive/`.

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** - while updating `docs/project/issues/40-search-card-actions.md`: docs/project/issues/archive/40-search-card-actions.md: new file, the archive location the checklist moves this issue to (issue-tracker.md line 21). docs/project/issues/40-search-card-actions.md: still needs deleting to finish the move; my tools can't delete files.
- while updating `docs/project/plans/20-40-search-card-actions.md`: docs/project/plans/20-40-search-card-actions.record.md — I did not touch it. It has to go to `docs/project/plans/archive/` together with the plan, as every archived plan has its record beside it, but the checklist does not list it.

**ADR conflicts.** none

### `client/frontend/README.md`

<changes>
Added two "What it does" bullets on the card action buttons (Like, Dislike, Block channel, Block account) on home feed and search cards.

- **First bullet (shared by both grids):**
  - Which cards get the buttons: those with a video key.
  - `aria-pressed` on Like and Dislike.
  - Like works without a profile key and toggles between `like` and `undo_like`.
  - Dislike and both Block buttons need a key. Without one they send no request and show home's exact "Disliking/Blocking needs a profile. Create one from the Profile button." text.
  - A Block also dislikes the video. If that dislike fails, the card says "Blocked …, but the dislike failed: …" and no cards are removed. Otherwise the block removes every loaded card from the channel (`instance_domain` + `channel_id`) or account (`account_url`).
  - A failed action, including a rejected profile key, shows its message in that card's status line, and the button is disabled while the request runs and re-enabled after.
- **Second bullet (how the two pages differ):**
  - On home, Dislike removes the card and has no undo.
  - On search, Dislike toggles between `dislike` and `undo_dislike` and the card stays marked, because search is not filtered by dislikes. A like replaces a dislike and the reverse.
  - After a search block removes cards, the next page is fetched if the end of the results is now on screen.
  - "Showing N of M matched videos." keeps counting fetched rows, removed ones included.

I checked every claim against `pages/search/index.ts` (`runCardAction`, `removeRows`, `renderSearchCard`), `pages/videos/index.ts` (`runCardAction`, `removeRows`) and `components/video-card.ts` (lines 355–356). For what each reaction mark looks like, the bullets rely on the reaction-display bullet that comes before them. Roadmap and issue status are left to their own documents.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/roadmap.md`

<changes>
Added a Delivered entry for the F13-M2 search card controls (issue `40`) and cut F13-M2 down to the channels-page block controls.

- **Delivered:** a new F13-M2 entry under issue `40` (Like, Dislike, Block channel, Block account on search cards). It says that on search, Dislike toggles and the card stays, and that a block removes the source's loaded cards. For the behaviour details it points to `client/frontend/README.md` instead of repeating them, and it links the plan at its archive path, `docs/project/plans/archive/20-40-search-card-actions.md`. It also says the home feed card controls were already in the tree and that the docs don't record which change delivered them.
- **M2, F13-M2:** now reads "Block controls on the channels page. Card controls on the feed and search grids (issue `40`) are delivered." I removed the plan 07 clause ("puts them only on the video page and in the profile modal"); it described the gap the feed and search controls have now filled.
- **Checked against the code:** `pages/search/index.ts` and `pages/videos/index.ts` both render cards with `actions: true` and call `blockVideoSource`. `video-card.ts` sets `aria-pressed` on both Like and Dislike. `pages/channels` has no block code, so the channels-page part is still open.
- **Path the entry depends on:** the plan is still at `docs/project/plans/20-40-search-card-actions.md` until its own checklist item moves it to `archive/`. The link only works once that move is done.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/40-search-card-actions.md`

<changes>
Closed issue 40 as delivered: set the Status line to `enhancement, complete`, added a delivery comment and wrote the file to `docs/project/issues/archive/`, but the original is still in `issues/` and has to be deleted by hand.

- **Status line:** `Status: enhancement, ready-for-agent` is now `Status: enhancement, complete`.
- **Delivery comment:** added under `## Comments` after the triage decisions. It uses the same "**Delivered** by `<archived plan path>`" form as the other archived issues and names `docs/project/plans/archive/20-40-search-card-actions.md`. For what the card controls do, it points to `client/frontend/README.md` instead of repeating it. It records two things:
  - **Rejected profile key:** a key rejected during a card action shows as a message in that card's status line. It does not trigger `keyRejectedNotice`, and the data layer was not changed. This is marked as the operator's decision, overriding the brief's Errors bullet. I checked the code: the `catch` in `runCardAction` writes `error.message` to the card status (`pages/search/index.ts:294`). `ProfileKeyRejectedError` is only handled for search reads (line 192).
  - **No-key prompt:** it uses home's exact "Create one from the Profile button." wording, even though `search.html` has no Profile button. I checked the code: the wording is at line 257, and only `index.html` and `videos.html` have `#show-profile-header`.
- **Brief and acceptance criteria:** left as written, because they record what was asked for.
- **Move to archive:** I wrote the full updated file to `docs/project/issues/archive/40-search-card-actions.md`. My tools cannot delete files, so `docs/project/issues/40-search-card-actions.md` still exists, unedited, and needs to be deleted to finish the move.
- **`dist/` rebuild:** done. The served `dist/assets/search-DE7Xdm7K.js` contains the no-key prompt.
</changes>

<not_on_checklist>
docs/project/issues/archive/40-search-card-actions.md: new file, the archive location the checklist moves this issue to (issue-tracker.md line 21). docs/project/issues/40-search-card-actions.md: still needs deleting to finish the move; my tools can't delete files.
</not_on_checklist>

### `docs/project/plans/20-40-search-card-actions.md`

<changes>
I made no edit to the plan's content, and I could not move the file: it is still at `docs/project/plans/20-40-search-card-actions.md` and needs a `git mv` into `docs/project/plans/archive/`.

**Content.** The file's header says the `dev-flow` workflow re-renders it from the run state and overwrites any manual edit. The checklist entry also says it needs no hand edits. I changed nothing in its text.

**Why it isn't moved.** I can write files but cannot delete or move them, and I have no shell. If I wrote a copy under `archive/`, there would be two plan files, and the copy would go stale the next time the workflow re-renders the original.

**The move, for whoever holds a shell (the harvester turn or you).** Move the plan and its record together, because every archived plan sits next to its `.record.md` (for example `22-36-nsfw-filter.md` and `22-36-nsfw-filter.record.md`):

```
git mv docs/project/plans/20-40-search-card-actions.md docs/project/plans/archive/20-40-search-card-actions.md
git mv docs/project/plans/20-40-search-card-actions.record.md docs/project/plans/archive/20-40-search-card-actions.record.md
```

**Do it as the last step.** Once moved, the roadmap's Delivered entry and the issue 40 comment point at the right path, `docs/project/plans/archive/20-40-search-card-actions.md`. But if the workflow re-renders the plan after the move, it will write a new file at the old path. So move it after the workflow's final render.

**One leftover after the move.** The header line names the record at `docs/project/plans/20-40-search-card-actions.record.md`. The workflow writes that line, so after the move it only gets fixed by a final re-render, or by a hand edit once the workflow is done with the file.
</changes>

<not_on_checklist>
docs/project/plans/20-40-search-card-actions.record.md — I did not touch it. It has to go to `docs/project/plans/archive/` together with the plan, as every archived plan has its record beside it, but the checklist does not list it.
</not_on_checklist>

## 2026-10-01 - Step 10 - stopped

Harvest tests did not complete. The entries above carry what the step established before it stopped; the gate it failed is the last of them.

