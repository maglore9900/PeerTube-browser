# Collapsible video description

Status: enhancement, complete
Origin: task 9, [M2][F1]

## Problem

Long video descriptions take up too much space.

## Proposed solution

- Limit the description height and show a "Show more / Collapse" button.
- On click, toggle the expanded/collapsed state and keep it in the UI.

## Comments

### Triage

**Established:**

- **Not built yet.** The video page shows the whole description in one block with `white-space: pre-wrap`, filled as text, with no height limit and no toggle.
- **The problem is real.** Measured on the live `whitelist.db`:
  - Stored descriptions are not held to the crawler's 200-character cap: 402,442 of 890,052 are longer than 200, and the longest is 2,803.
  - 36,006 descriptions have 8 or more line breaks, and the most has 89.
  - The page also reads descriptions straight from the instance API, which has no cap. Under `pre-wrap` each line break takes a full line.
- **Maintainer decisions:**
  - The expanded/collapsed state lasts for the current page view only. Nothing is stored.
  - A collapsed description shows 4 rendered lines.
  - The toggle appears only when the text overflows those 4 lines.
  - The build goes to an agent. The maintainer verifies it in a real browser, because the test harness has no layout engine.
- **Related:** roadmap F5-M2 (frontend refactor) will rewrite this page. Issue 13 (comments) touches the same page.

### Delivered

Delivered by `docs/project/plans/archive/19-14-collapsible-description.md`, commit `<pending>`.

- **Labels.** The toggle reads "Show more" and "Show less", as the operator approved, not the Problem section's "Show more / Collapse".
- **Clip.** `-webkit-line-clamp: 4` on `.video-description.description-collapsed` in `client/frontend/src/video.css`. The element keeps its full text, still set with `textContent`.
- **Toggle.** `#description-toggle` is shown only while the description's text is taller than four lines, and never for the "No description available." placeholder. A `ResizeObserver` on the description measures it again whenever its size changes.
- **State.** Each page view starts collapsed. Nothing is stored.

## Agent Brief

**Category:** enhancement
**Summary:** Collapse long video descriptions on the video page to 4 lines, with a "Show more" / "Show less" toggle that appears only when the description overflows.

**Current behavior:**
The video page's description element shows the full description as plain text. Line breaks are preserved (`pre-wrap`) and nothing limits its height. A description with dozens of lines pushes the similar-videos section far down the page. When there is no description, the element shows "No description available."

**Desired behavior:**
- **Collapsed by default.** On load, the description shows at most 4 rendered lines, counting wrapped lines and preserved line breaks alike. The clip is visual only: the full text stays in the element, is still set as text (never as HTML), and keeps its line breaks.
- **Toggle only on overflow.** When the full description is taller than 4 lines, a toggle button labelled "Show more" appears below it. Clicking it shows the whole description and relabels it "Show less". Clicking again collapses it. A description of 4 lines or fewer, and the "No description available." placeholder, show no button.
- **Resize.** Overflow is re-evaluated when the page width changes. A description that starts or stops overflowing gains or loses the button. An expanded description stays expanded while it still overflows.
- **Per page view.** Each video page load starts collapsed. Nothing is written to localStorage, cookies, the URL or the server.
- **Accessible.** The toggle is a real `<button>`, reachable and operable by keyboard. It carries `aria-expanded` matching the state and `aria-controls` pointing at the description element.
- **Matches the page.** The button uses the page's existing small-button styling rather than a new visual language.

**Key interfaces:**
- The description element (`id="video-description"`, class `video-description`) in the video page markup, its stylesheet rule, and the code that fills it with the metadata's `description` string. The collapsed state can be a class on that element. The button sits beside it in the markup.
- No change to the metadata shape, the Engine, the Client backend, or the description text itself.

**Acceptance criteria:**
- [ ] `npm run build` in `client/frontend` succeeds, and the existing frontend and active test suites stay green.
- [ ] The description is still set with text, not HTML. No new `innerHTML` path carries description content.
- [ ] Browser check by the maintainer, after `sudo rsync -a --delete client/frontend/dist/ /var/www/peertube-browser/` and a hard reload. The agent's hand-off includes this recipe, with a way to find a qualifying video (for example a `whitelist.db` query):
  - [ ] A video whose description has 8 or more line breaks opens showing 4 lines and a "Show more" button. Clicking shows the whole text and "Show less". Clicking again returns to 4 lines.
  - [ ] A video with a 1- or 2-line description, or no description, shows no button.
  - [ ] Narrowing the window until a short description wraps past 4 lines makes the button appear. Widening it back makes the button go away.
  - [ ] Opening another video starts collapsed, whatever state the previous one was left in.
  - [ ] Tabbing reaches the button, Enter or Space toggles it, and `aria-expanded` changes with it.

**Out of scope:**
- Rendering links or markdown in descriptions (the text stays plain).
- Remembering the state across videos or sessions.
- Fetching a fuller description (the PeerTube description endpoint) or changing the crawler's text cap.
- The wider frontend refactor (F5-M2) and the comments section (issue 13).
