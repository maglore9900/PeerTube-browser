# Like, dislike and block controls on search result cards

Status: enhancement, complete
Origin: operator report: "blocks and likes and such do not work on the video cards in search"

## Problem

The home feed's video cards carry Like, Dislike, Block channel and Block account buttons. The search page's cards carry none of them, so a visitor cannot like, dislike or block from a search result and has to open the video page first.

Both pages render cards through the shared `renderVideoCard`, which draws the buttons only when its caller passes `actions: true`. The home feed passes it and handles the buttons' `data-card-action` clicks itself (`runCardAction` in the feed page). The search page passes only `apiParam` and `reaction`, and has no click handler, so the buttons are never drawn. The built bundle matches the source.

This is the search-grid half of roadmap item F13-M2 ("Block controls on video cards (feed and search grids) and on the channels page"). The feed grid half is already in the tree.

## Comments

**Triage (operator decisions):**

- A dislike from a search card keeps the card and marks it disliked. Search stays unfiltered by dislikes (plan 08, D6), so the page shows what a rerun of the same search would show.
- Dislike on a search card toggles, as Like does: pressing it on a disliked card sends `undo_dislike`.
- A block from a search card behaves as it does on home: block, dislike the clicked video, and remove every loaded card of that channel or account.
- Only the four controls home cards have. Follow on cards is not part of this issue.

**Delivered** by `docs/project/plans/archive/20-40-search-card-actions.md`. What the card controls do on each page is described in `client/frontend/README.md`.

- **Rejected profile key (operator decision, overrides the brief's Errors bullet).** A key rejected during a card action shows its message in that card's status line, as on home. It does not replace the grid with `keyRejectedNotice`, and the data layer (`user-actions.ts`, `blocks.ts`, `reactions.ts`) still throws a plain `Error` for it. `ProfileKeyRejectedError` handling for search reads is unchanged.
- **No-key prompt wording.** Search cards use home's exact text, "Disliking/Blocking needs a profile. Create one from the Profile button.", although `search.html` has no Profile button.

## Agent Brief

**Category:** enhancement
**Summary:** Give search result cards the same Like, Dislike, Block channel and Block account controls as home feed cards

**Current behavior:**
The shared card renderer `renderVideoCard(row, options)` draws a row of action buttons (`data-card-action` = `like`, `dislike`, `channel`, `account`, plus a `.card-action-status` line) only when `options.actions` is true. The home feed page sets it, and a delegated click handler on its grid runs each action through `sendReaction` and `blockVideoSource`. The search page renders cards with `apiParam` and `reaction` only and has no click handler, so search cards have no action buttons.

Search rows from a keyed request already arrive marked with `reaction` (`"liked"` or `"disliked"`). The Client's read proxy removes blocked channels and accounts from search, and deliberately never removes disliked videos (D6).

**Desired behavior:**
Every search result card shows the four controls home cards show, and they act as follows:

- **Like**: toggles exactly as on home. Like sends `like`; on a liked card it sends `undo_like`. A like on a disliked card replaces the dislike. The card re-renders in its new state and stays on the page.
- **Dislike**: needs a profile. It sends `dislike` and the card **stays**, re-rendered with the disliked mark, and the Dislike button reads pressed (`aria-pressed="true"`). Pressing it on a disliked card sends `undo_dislike` and the card returns to neutral. A dislike on a liked card replaces the like.
- **Block channel / Block account**: needs a profile. Same as home: block the clicked video's channel or account, then dislike the clicked video, then remove every currently loaded search card from that channel (`instance_domain` + `channel_id`) or account (`account_url`). If the block succeeds and the dislike fails, say so in the card's status line, as home does.
- **Without a profile key**: Dislike and Block show the same "needs a profile" prompt in the card's status line that home shows. Like works without a key the way it does on home.
- **Errors**: a failed action shows its message in that card's status line, and the button is re-enabled. A rejected key is handled as the search page already handles `ProfileKeyRejectedError`.
- Paging continues normally after any action. Cards appended by later pages get the controls too.

If the home feed shares the same dislike-button markup, giving it `aria-pressed` for a disliked card is fine, but home's dislike behaviour (remove the card, no undo) must not change.

**Key interfaces:**
- `VideoCardOptions.actions` on `renderVideoCard`: the search page passes `true`.
- The Dislike button in the card's action markup: it needs a pressed state for a disliked card, the way the Like button already has one for a liked card.
- `sendReaction(apiBase, action, { uuid, host })` with actions `like`, `undo_like`, `dislike`, `undo_dislike`; `blockVideoSource(apiBase, kind, uuid, host)` returning the block's `kind`, `instance_domain`/`channel_id` or `account_url`, and `label`; `cardReaction(row)` for the current mark.
- Home's card-action handling, which may be shared with search or mirrored. A shared helper must leave home's behaviour unchanged.

**Acceptance criteria:**
- [ ] A search results page renders Like, Dislike, Block channel and Block account buttons on every card that has a video key, including cards loaded by later pages.
- [ ] With a profile key, Dislike on a search card sends `dislike`, and the card stays on the page with the disliked mark and a pressed Dislike button. Rerunning the same search shows that video still present and marked disliked.
- [ ] Dislike on a disliked search card sends `undo_dislike`. The card shows no mark, and a rerun of the search carries no `reaction` on that row.
- [ ] Like on a search card toggles between `like` and `undo_like`, and a like on a disliked card leaves it marked liked, not disliked.
- [ ] Block channel on a search card removes every loaded card of that channel, and the video is disliked. A rerun of the same search contains no row from that channel. Block account does the same by `account_url`.
- [ ] Without a profile key, Dislike and the two Block buttons show the profile prompt in the card's status line and send no request.
- [ ] Home feed card behaviour is unchanged: dislike and block still remove cards, and home has no undo-dislike.
- [ ] `dist/` is rebuilt (`npm run build`) so the served bundle carries the change.

**Out of scope:**
- Filtering search results by dislikes (D6 stands).
- Follow controls on any card.
- Action controls on the video page's similar/up-next cards, the likes page or the channels page.
- Changing home feed card behaviour, beyond an optional pressed state on its Dislike button.
- Any Client backend or Engine change. The routes and filtering this needs already exist.
