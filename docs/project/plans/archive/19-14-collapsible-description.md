# 14-collapsible-description

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-14-collapsible-description.record.md`._

## Requirements

### Purpose

Long video descriptions push the rest of the video page (the similar-videos section) far down. Stored descriptions are not held to the crawler's 200-character cap: 402,442 of 890,052 are over 200 characters, the longest is 2,803, 36,006 have 8 or more line breaks, and the most has 89. The page also reads descriptions directly from the PeerTube instance API, which has no cap. Under `white-space: pre-wrap` every line break takes a full line. The goal is to keep the page compact by default while the full text stays one click away. Origin: task 9, [M2][F1]. Category: enhancement.

### Current state (verified in the tree)

- Markup: `client/frontend/video-page.html` line 96 is `<div id="video-description" class="video-description"></div>`. It is the last child of the `.player-info` column (a flex column with `gap: 0.6rem`), right after `.video-meta-row` and inside the player card. The similar-videos `<section>` comes after the player card.
- Filling: `client/frontend/src/pages/video-page/index.ts` gets `descriptionEl` by id at line 34. In the render function (around line 104 `const description = metadata?.description ?? "";` and lines 209-211) it sets `descriptionEl.textContent = description ? description : "No description available.";`. The render function runs once per page load, after metadata resolves.
- Style: `client/frontend/src/video.css` line 450, `.video-description { padding: 0.8rem 1rem; border-radius: 12px; background: rgba(255,255,255,0.65); border: 1px solid var(--line); color: var(--ink); white-space: pre-wrap; line-height: 1.45; }`.
- The page's existing small-button style is `.ghost-button`, a dashed border with accent colour, used by `#block-channel`, `#block-account`, `#like-button` and `#dislike-button`, all with `type="button"`.
- Opening another video is a full page navigation. Links are plain `/video-page.html?...` hrefs, and the video page has no pushState or popstate. Each video view is therefore a fresh page load.
- Build: `npm run build` (`vite build`) in `client/frontend`. The frontend is TypeScript and Vite with no UI framework. Dependencies are only graphology and sigma.
- Tests: `tests/active/test_frontend_*.py` (videos, reactions, blocks, profile) bundle data modules with esbuild and run them in node with minimal stubbed `window` and storage. They have no DOM layout engine, so rendered-line overflow cannot be tested automatically.

### Functional requirements

1. **Collapsed by default.** On every load, `#video-description` shows at most 4 rendered lines. Wrapped lines and preserved line breaks both count as lines. The clip is visual only: the element keeps the full text, set via `textContent` (never `innerHTML`), with `pre-wrap` line breaks kept. The collapsed state is a class on the description element, and the 4-line height comes from CSS based on the element's line height (1.45).
2. **Toggle only on overflow.** When the full description is taller than 4 lines, a toggle `<button type="button">` labelled "Show more" is visible directly below the description. Clicking it shows the full description (removes the clip) and changes the label to "Show less". Clicking again collapses it back to 4 lines and "Show more". When the description is 4 lines or fewer, or shows the placeholder "No description available.", no button is visible.
3. **Resize.** Overflow is re-evaluated when the page width changes. A description that starts overflowing gains the button, and one that stops overflowing loses it. An expanded description stays expanded while it still overflows. The overflow check must measure the full text's height against the 4-line limit, so that it works while expanded too.
4. **Per page view only.** Each video page load starts collapsed. Nothing is written to localStorage, sessionStorage, cookies, the URL or the server.
5. **Accessible.** The toggle is a real `<button>`, in the tab order and operable with Enter and Space. It carries `aria-expanded` (`"false"` when collapsed, `"true"` when expanded), kept in sync with the state, and `aria-controls="video-description"`.
6. **Visual consistency.** The button uses the existing `.ghost-button` class, with at most minimal layout-only additions such as alignment or spacing. It adds no new visual language.

### Constraints

- Change only the video page's markup (`client/frontend/video-page.html`), stylesheet (`client/frontend/src/video.css`) and page script (`client/frontend/src/pages/video-page/index.ts`). New code follows the style of those files.
- No new dependency. Use platform APIs only (a resize listener or `ResizeObserver`, and `scrollHeight`/`clientHeight` or equivalent measurement).
- No change to the metadata shape, the Engine, the Client backend, or the description text itself. The description stays plain text, and no new `innerHTML` path carries description content.
- Do not edit `client/frontend/dist/` by hand. It is build output.

### Out of scope

- Rendering links or markdown in descriptions.
- Remembering the state across videos or sessions.
- Fetching a fuller description (the PeerTube description endpoint) or changing the crawler's text cap.
- The wider frontend refactor (roadmap F5-M2), which will rewrite this page, and the comments section (issue 13), which touches the same page.

### Acceptance criteria

- `npm run build` in `client/frontend` succeeds.
- The existing frontend tests and the whole `tests/active` suite stay green (baseline: exit code 0).
- The description is still set with `textContent`, and no new `innerHTML` path carries description content.
- A browser check by the maintainer (the test harness has no layout engine). The agent's hand-off must include this recipe:
  - Deploy: `cd client/frontend && npm run build`, then `sudo rsync -a --delete client/frontend/dist/ /var/www/peertube-browser/` from the repo root, then a hard reload.
  - Find qualifying videos in `engine/server/db/whitelist.db` (table `videos`, columns `video_uuid`, `instance_domain`, `title`, `description`). For example, for 8 or more line breaks: `sqlite3 engine/server/db/whitelist.db "SELECT video_uuid, instance_domain, title FROM videos WHERE length(description) - length(replace(description, char(10), '')) >= 8 LIMIT 5;"`. Use a similar query for a short description (0-1 line breaks, short length) and for an empty or NULL description. The hand-off must also say how to open a given video on the page (the `/video-page.html?id=...&host=...` URL shape the page uses).
  - A video with 8 or more line breaks opens showing 4 lines and a "Show more" button. Clicking shows the whole text and "Show less". Clicking again returns to 4 lines.
  - A video with a 1- or 2-line description, or no description, shows no button.
  - Narrowing the window until a short description wraps past 4 lines makes the button appear. Widening it back makes the button go away.
  - Opening another video starts collapsed, whatever state the previous one was left in.
  - Tabbing reaches the button, Enter or Space toggles it, and `aria-expanded` changes with it.

### Baseline suite state

Pre-build baseline for the active tests (`tests/active`): exit code 0, no variant. The suite is green before the build starts, and it must be green after.

### Test directories

- Active: `tests/active`. Working: `tests/tmp`. Archive: `tests/archive`. Plans: `docs/project/plans`. Delete-me: `delete_me`. Record: `tests/last_test_validation.json`. Output: `tests/last_test_output.txt`. Project dir: `/home/enduser/code/PeerTube-browser`.

## High-level plan

### Approach

The change touches the three files the constraints allow and adds nothing else: one button in the markup, two small rules in the stylesheet, and about thirty lines of page script. There is no new dependency, no new module and no helper abstraction.

**Markup (`video-page.html`).** The description `div` gets the collapsed class, `description-collapsed`, in the static markup. The page therefore renders collapsed from first paint, before metadata resolves. Directly after it, still inside `.player-info`, sits a new `<button type="button" id="description-toggle" class="ghost-button description-toggle" aria-controls="video-description" aria-expanded="false" hidden>Show more</button>`. Because it is a static real button, it is in the tab order and responds to Enter and Space natively once it is unhidden, with no key handling of our own (req. 5). The `.player-info` column's existing `gap: 0.6rem` puts it directly below the description.

**Style (`video.css`).** `.video-description.description-collapsed` gets `overflow: hidden` and a `max-height` computed from the line height. The stylesheet sets `* { box-sizing: border-box }` globally (line 19), so the height has to include the box's vertical padding and border as well as the text. It is four lines at the element's own `1.45em` line height, plus `1.6rem` of padding, plus `2px` of border. Since the unit is exactly one line box, the clip falls on a line boundary. It counts wrapped lines and preserved `pre-wrap` breaks alike, because both are just line boxes (req. 1). `.description-toggle` gets only `align-self: flex-start`, so it does not stretch across the flex column. All visuals come from `.ghost-button` (req. 6). `.ghost-button` sets no `display`, so the UA `[hidden]` rule hides the button without an extra rule.

**Script (`index.ts`).** There are three module-level pieces, written in the file's existing style: a `document.getElementById` constant next to `descriptionEl`, and two small functions with the file's `/** Handle ... */` doc comments.

- `setDescriptionExpanded(expanded)`: toggles the collapsed class on the description, sets the button's `aria-expanded` to `"true"`/`"false"` and sets its label to "Show less"/"Show more". This is the only place that state changes, so the class, the label and ARIA cannot drift apart (req. 2, 5).
- `updateDescriptionToggle()`: measures and shows or hides the button. The overflow test works the same in both states. It takes the full content height as `scrollHeight` minus the computed top and bottom padding; `scrollHeight` reports the whole text even while clipped, and equals the natural height while expanded. It compares that against four times the computed `lineHeight` in px, with a 1px tolerance for sub-pixel rounding (1.45 × 16px = 92.8px). If the text overflows, the button is shown. If it does not, the button is hidden and the state is reset to collapsed. The reset means a description that later starts overflowing again (after the window narrows) comes back as collapsed with "Show more" and `aria-expanded="false"`, never as a stale expanded state. An expanded description that still overflows is left expanded (req. 3). When the placeholder is showing, the function hides the button and does nothing else (req. 2).
- In `loadVideo`, the existing `textContent` line stays exactly as it is (acceptance criterion). Right after it, the script records whether the placeholder was used, calls `setDescriptionExpanded(false)` and starts a single `ResizeObserver` on `descriptionEl` that calls `updateDescriptionToggle`. The observer's first callback runs after layout, so it also does the first measurement after the text is set. The button's click listener is wired once at module level and calls `setDescriptionExpanded` with the opposite of the current state.

Per page view (req. 4): state lives only in the class on the element. Nothing is written to storage, cookies, the URL or the server. Every video is a full page load, so every video starts collapsed.

### Alternatives considered

- **`-webkit-line-clamp: 4`** (already used for `.similar-title` in this file). It adds a trailing ellipsis for free, but it needs `display: -webkit-box`. How it treats blank `pre-wrap` lines is less predictable across engines. And the requirement asks for a height derived from the line height. Rejected in favour of `max-height`, which is plain and predictable.
- **The `lh` unit (`max-height: 4lh`).** It is the cleanest expression, but it needs Firefox 120+ and Safari 16.4+. `calc` with `em` gives the same number with no support risk.
- **A window `resize` listener instead of `ResizeObserver`.** It is simpler to reason about, but it misses width changes that are not window resizes: a web font finishing loading and reflowing the text, or a vertical scrollbar appearing when the similar-videos grid fills in and narrowing the column. `ResizeObserver` catches all of these, also gives the first post-layout measurement, and is a platform API. It also fires when the element's own height changes on toggle. That is harmless, because the measurement does not depend on state and changing the button's visibility does not resize the description, so there is no feedback loop.
- **Building the button in script and inserting it.** This keeps the HTML untouched but splits the page's structure across two files and adds DOM construction code. Static markup with `hidden` matches how the page already declares `#block-channel` and the reaction buttons.
- **Counting `\n` in the text instead of measuring.** It cannot see wrapped lines, so it fails the resize requirement and the "narrow window" check. Rejected.
- **Inline `style` for the height.** The page's CSP is `style-src 'self'`, and the rest of the file drives visuals through classes. A class keeps all of it in CSS.

### Risks and gotchas

- **Box sizing.** Leaving the padding and border out of `max-height` would clip to about 2.7 lines under `border-box`. The calc must include them. This is the most likely off-by-one, and the browser check covers it.
- **Rounding.** `scrollHeight` is an integer and the line height is fractional, so the comparison uses a 1px tolerance. Otherwise an exactly-4-line description could flicker a button in at some zoom levels.
- **Measuring before layout.** A measurement taken synchronously after setting `textContent` is valid, because reading layout forces it. The observer's first callback re-measures anyway, so there is no dependence on timing.
- **No automated coverage of the behaviour.** The node/esbuild harness has no layout engine, and no active test imports the video page script (checked: nothing in `tests/active` references `video-page`, `video.css` or `video-description`). The suite should stay green without changes, and the behaviour is verified only by the maintainer's browser check.
- **Focus on collapse.** The button sits below the description and does not move when the text collapses, so focus stays on it and the page does not jump focus. The viewport can shift upward when a long description collapses. That is inherent to the pattern and accepted.

### Tradeoffs the operator is asked to accept

- **A hard clip, not a fade or ellipsis.** The 4th line is cut cleanly at its bottom edge with no "…" or gradient. This is a deliberate simplification. The upgrade path is a single `::after` gradient rule on the collapsed class, with no script change.
- **No debounce on the observer.** The measurement is two property reads per resize frame on one element, which is too cheap to be worth a timer.
- **The feature is short-lived.** Roadmap F5-M2 will rewrite this page, and issue 13 touches it too. The change is kept small and self-contained (one class, one button, two functions) so that either can lift it or replace it without disentangling anything.

### Hand-off recipe (to be included by the implementer)

Deploy: `cd client/frontend && npm run build`, then from the repo root `sudo rsync -a --delete client/frontend/dist/ /var/www/peertube-browser/`, then do a hard reload.

Finding test videos in `engine/server/db/whitelist.db`:
- Long, 8 or more line breaks: `SELECT video_uuid, instance_domain, title FROM videos WHERE length(description) - length(replace(description, char(10), '')) >= 8 LIMIT 5;`
- Short: the same select with `WHERE length(description) BETWEEN 1 AND 80 AND length(description) - length(replace(description, char(10), '')) <= 1`.
- Empty: `WHERE description IS NULL OR trim(description) = ''`.

To open a result, go to `/video-page.html?id=<video_uuid>&host=<instance_domain>`. That is the shape `videoPageUrl` builds, and it resolves metadata from `id` and `host` alone. Then run the checks listed in the acceptance criteria.

## Impacts


<impact path="client/frontend/video-page.html" element="#video-description div (line 96)">
**What changes:** the static class list goes from `video-description` to `video-description description-collapsed`. The page therefore paints collapsed before `loadVideo` fills the text.

**What depends on it:**
- `index.ts:34` looks it up by id. The id is unchanged.
- `video.css:450` `.video-description` gives the base box: `padding: 0.8rem 1rem`, 1px border, `line-height: 1.45`, `pre-wrap`.
- The new `aria-controls` on the toggle points at this id.

**Regression risk: low.**
- The text arrives only through script (`textContent` at `index.ts:210`). So a script failure before `loadVideo` leaves an empty box, not clipped content with no way to expand it. No no-JS content is lost.
- An empty collapsed box is just padding plus border, the same as today.
- The id and base class must stay byte-identical, because the `aria-controls` value and `getElementById` both key on `video-description`.
</impact>
<impact path="client/frontend/video-page.html" element="new #description-toggle button, inserted after line 96 inside .player-info (lines 39-97)">
**What changes:** a new `<button type="button" id="description-toggle" class="ghost-button description-toggle" aria-controls="video-description" aria-expanded="false" hidden>Show more</button>` becomes the last child of `.player-info`, after the description and before `</div>` at line 97.

**What depends on it:** the new `getElementById` constant in `index.ts`, and the `.ghost-button` rules at `video.css:349-369`.

**How it compares to existing buttons:** the other ghost buttons on this page (`#block-channel` and `#block-account` at lines 62-63, `#like-button` and `#dislike-button` at lines 76-89) also carry `type="button"`, but they use `disabled`, not `hidden`. Plan step 2 says they are declared with `hidden`, which is slightly inaccurate. The pattern is still consistent: static markup, script-enabled.

**Regression risk: low.**
- A hidden button is `display: none`, so it adds no flex `gap` to `.player-info` and the layout of pages with short descriptions is unchanged.
- Placement matters for issue 13: comments render "below the description block" (`docs/project/issues/13-video-comments.md:12-14`), so that lane must insert after the toggle, not between it and the description.
- The CSP at line 8 (`style-src 'self'`) is untouched. The markup carries no inline style.
</impact>
<impact path="client/frontend/src/video.css" element=".video-description rule (lines 450-458) and new .video-description.description-collapsed rule">
**What changes:** the base rule is unchanged. A new compound rule adds `overflow: hidden` and a `max-height` along the lines of `calc(4 * 1.45em + 1.6rem + 2px)`.

**What the calc depends on:** it reproduces the base rule's `line-height: 1.45`, vertical padding `0.8rem` × 2 and border `1px` × 2, under the global `* { box-sizing: border-box }` (lines 18-20).
- The element sets no `font-size`, so `em` resolves against the inherited 16px default: 4 × 23.2 = 92.8px of text plus 25.6px padding plus 2px border.
- The calc hard-codes three values that live in the base rule. If anyone later changes the padding, border or line-height (F5-M2 or issue 13), the collapsed rule silently clips at the wrong line.
- The implementer should place the new rule directly after lines 450-458 so the coupling is visible.

**What else depends on it:** only the video page. `video.css` is imported solely by `src/pages/video-page/index.ts:5`. The other pages use `videos.css` and `channels.css`, which define their own `.ghost-button`.

**Regression risk: medium.** This calc is the most likely off-by-one. Leaving out the padding would clip at about 2.7 lines. Only the maintainer's browser check covers it.
</impact>
<impact path="client/frontend/src/video.css" element="new .description-toggle rule, and reliance on .ghost-button (lines 349-369)">
**What changes:** a new rule `.description-toggle { align-self: flex-start; }`.

**Checked against the tree:**
- `.ghost-button` in `video.css` sets no `display`, so the UA `[hidden]` rule hides the button without extra CSS.
- `video.css` has no `[hidden]` override anywhere. The grep for `\[hidden\]` found no match in this file, unlike `videos.css`, which has `.modal[hidden]`.
- `.icon-button` (line 371) sets `display: inline-flex` and must not be added to this button, or `hidden` would stop working.
- `video.css` has no `button { font: inherit }` (`channels.css` does), so the toggle gets the UA button font. That matches the other ghost buttons on this page.

**Regression risk: low.** It is a new selector with no other users. Existing ghost buttons are unaffected.
</impact>
<impact path="client/frontend/src/video.css" element="global * { box-sizing: border-box } (lines 18-20)">
**What changes:** nothing. This is a dependency.

It is why the `max-height` must include padding and border. If a future refactor (F5-M2) switches to content-box, the collapsed height grows by 27.6px, about 1.2 extra lines.

**Regression risk: none now.** It is recorded so the coupling is known.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="module-level element constants and state (lines 22-51)">
**What changes:**
- A new constant next to `descriptionEl` (line 34): `const descriptionToggle = document.getElementById("description-toggle") as HTMLButtonElement | null;`. The cast follows the style of lines 38-39 and 46-47.
- A module-level flag for "placeholder shown". `updateDescriptionToggle` runs from the ResizeObserver callback, outside `loadVideo`'s scope, so the flag must live at module level. It belongs as a `let` beside `currentMetadata` and `reaction` (lines 50-51), or it could be derived from the element state instead.

**What depends on it:** the two new functions, the click listener and the ResizeObserver callback.

**Regression risk: low. One trap:** `void loadVideo()` runs at line 79, before most of the module has evaluated. Any new `const` or `let` declared below line 79 is in the temporal dead zone if touched synchronously. `loadVideo` awaits `fetchVideoMetadata()` first, so it is safe today. Declaring the new state up with lines 22-51 removes the dependency on that timing.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="new function setDescriptionExpanded(expanded)">
**What changes:** a new function. It toggles `description-collapsed` on `descriptionEl`, sets `aria-expanded` to `"true"`/`"false"`, and sets the button's `textContent` to "Show less"/"Show more".

**Style:** it mirrors `setReactionButton` (lines 366-372): `classList.toggle`, `setAttribute(..., String(...))`, a label set via `textContent`. It needs a `/** Handle ... */` or descriptive doc comment, like its neighbours.

**What depends on it:** `loadVideo`, `updateDescriptionToggle` (the reset path) and the click listener. It must be the only writer of the class, the label and ARIA.

**Regression risk: low.**
- Both `descriptionEl` and the button are nullable, so both need null guards, as every other writer in the file has.
- `classList.toggle(cls, !expanded)`: the inverted boolean is an easy place to invert the logic by mistake.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="new function updateDescriptionToggle()">
**What changes:** a new function.
- It measures `descriptionEl.scrollHeight − paddingTop − paddingBottom` (from `getComputedStyle`), compares it with `4 × parseFloat(lineHeight) + 1`, and sets `descriptionToggle.hidden`.
- When the text does not overflow, it calls `setDescriptionExpanded(false)`.
- With the placeholder showing, it hides the button and returns.

**Checked assumptions:**
- `line-height: 1.45` is unitless, so the computed value is a px string (`"23.2px"`).
- The element sets `white-space: pre-wrap` on a plain block, so `scrollHeight` covers the full text while clipped.
- If an engine left bottom padding out of `scrollHeight`, the content would be underestimated by 12.8px. The test stays correct, because one line is 23.2px: 5 lines is 116 − 12.8 = 103.2px, still above 93.8px.

**ResizeObserver loop:** the callback can change layout. Showing or hiding the button changes page height, which can toggle the viewport scrollbar and so the description's width, all within the same frame. That produces the benign console error "ResizeObserver loop completed with undelivered notifications". The state still converges, because both directions are monotone. The plan's "no feedback loop" claim holds for state but not strictly for the notification. The only `error` listener in the file is on avatar images (lines 428-435), so nothing reacts to that error.

**Regression risk: medium.** No test can exercise it (no layout engine), and `vite build` does not type-check, so a typo in the `getComputedStyle` property names fails only at runtime.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadVideo(), description block (lines 209-211)">
**What changes:**
- Line 210 (`descriptionEl.textContent = description ? description : "No description available.";`) must stay verbatim. That is an acceptance criterion, and it is the only description sink, with no `innerHTML`.
- Right after it, inside the same `if (descriptionEl)` block:
  1. set the placeholder flag from `!description`;
  2. call `setDescriptionExpanded(false)`;
  3. create a single `ResizeObserver` on `descriptionEl` whose callback calls `updateDescriptionToggle`.

**What depends on it:** `loadVideo` is called once, at line 79, per page load, and navigating to another video is a full page load (`videoPageUrl` at lines 1065-1086 builds plain hrefs), so there is one observer per page.
- If issue 11 or 12 (`docs/project/issues/plan.md` lanes 3a and 4a, "video page load flow") later makes `loadVideo` re-entrant, observers would stack. Creating the observer once, or guarding it (the file already uses the `dataset.wired` idiom at lines 282-283 and 327-328), avoids that.

**Other `loadVideo` paths:** the `channelEl`, `instanceAvatarEl`, `accountAvatarEl` and `viewsEl` `innerHTML` writes are untouched.

**Regression risk: low to medium.**
- Ordering: the observer's first callback fires after layout, so it covers the initial measurement even if fonts load late.
- A metadata failure (`fetchVideoMetadata` returns null) leads to `description = ""`, then the placeholder, and the button stays hidden. That is correct.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="new module-level click listener on #description-toggle">
**What changes:** a new module-level `descriptionToggle?.addEventListener("click", ...)` that calls `setDescriptionExpanded` with the opposite of `descriptionEl.classList.contains("description-collapsed")`.

**Placement:** module level, wired once, like `applyActionIcons()` at line 1226. It must not live inside `loadVideo`, or a re-entrant `loadVideo` would double-bind it, making each click toggle twice and appear dead.

**Keyboard:** Enter and Space come from the native `<button>`, so there is no key handling to write.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="local videoPageUrl() (lines 1065-1086), relied on by the hand-off recipe">
**What changes:** nothing.

**Recipe accuracy:** the recipe says `/video-page.html?id=<video_uuid>&host=<instance_domain>` is "the shape `videoPageUrl` builds". It is not quite right: `videoPageUrl` puts `row.video_id ?? row.video_uuid` into `id`, and also sets `title`, `channel`, `channelUrl`, `embed` and `url`. The same holds for the exported copy in `client/frontend/src/components/video-card.ts:286-308`.

**Why the recipe still works:**
- The Engine's `/api/video` handler matches `v.video_id = :id OR v.video_uuid = :id` (`engine/server/api/handlers/video.py:63`), and the Client allowlist forwards `id` and `host` (`client/backend/server.py:88`).
- The instance fallback (`fetchVideoMetadataFromInstance`, line 562) accepts a uuid.
- A uuid-only URL therefore resolves.

The implementer may want to drop the phrase "that is the shape `videoPageUrl` builds" from the recipe.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="exported videoPageUrl() (lines 286-308)">
**What changes:** nothing. It builds the links from the feed, search and likes pages into the video page. Those are full navigations, which is what gives "every video starts collapsed" (req. 4) for free.

**Regression risk: none.** It is recorded because req. 4 depends on navigation staying a full page load.
</impact>
<impact path="client/frontend/dist/video-page.html" element="build output: dist/video-page.html, dist/assets/video-*.js, dist/assets/video-*.css">
**What changes:** `npm run build` regenerates these files with new content hashes (today `video-gjYm1MC8.js` and `video-ypOuFwNw.css`). Vite's default `emptyOutDir` rewrites the whole `dist/`.

**Tracking status:** the root `.gitignore` does not list `dist`, so `client/frontend/dist/` appears to be tracked, and the build will show up as a diff under `dist/`. I could not run git to confirm it is committed.

**Constraints:** never hand-edit `dist/`. Whether to commit the rebuilt `dist/` with this change is the operator's call.

**Deployment:** the hand-off's `rsync -a --delete` deploys this output.

**Regression risk: low.** Other entries keep their hashes unless shared chunks change, and this change touches no shared module.
</impact>
<impact path="client/frontend/vite.config.ts" element="build.rollupOptions.input.video (line 89)">
**What changes:** nothing. `video-page.html` is already a build input, and no new page or entry is added, so `DEPLOYMENT.md` lines 205-209 (the page list) stay accurate.

**Regression risk: none.**
</impact>
<impact path="client/frontend/tsconfig.json" element="compilerOptions (target ES2022, no explicit lib)">
**What changes:** nothing. With no `lib`, the default for ES2022 includes DOM, so `ResizeObserver` and `getComputedStyle` are typed.

**Build gate:** the `build` script in `package.json` is plain `vite build`, with no `tsc`. Type errors in the new code will not fail the acceptance-criterion build. They surface only in an editor or through a manual `npx tsc --noEmit`.

**Regression risk:** none from the config itself. The weaker gate is noted.
</impact>
<impact path="client/frontend/package.json" element="dependencies / scripts">
**What changes:** nothing. The plan adds no dependency, and `ResizeObserver` is a platform API.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_frontend_videos.py" element="frontend node/esbuild suites (also test_frontend_reactions.py, test_frontend_blocks.py, test_frontend_profile.py)">
**What changes:** nothing. These tests bundle only `src/data/*.ts` and `src/components/video-card.ts` entry exports (for example `test_frontend_reactions.py:107-113`, `test_frontend_blocks.py:58-63`).

**Checked:** a grep of `tests/active` for `video-page`, `video.css` and the description id found no frontend reference. The only matches are `description` DB-column tuples in Python backend tests, which are unrelated.

**Regression risk: none.** There is also no coverage of the new behaviour.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="grep scan of client/frontend/src/**/*.ts">
**What changes:** nothing. The new code falls inside the scan (`TARGET_DIR=client/frontend/src`). It must not contain the forbidden patterns: Engine base names, `127.0.0.1` or `localhost` with ports 7070-7072 or 7171, or `/internal/...` routes. The planned code contains none of them.

**Regression risk: none.**
</impact>
<impact path=".worktrees/10/client/frontend/src/pages/video-page/index.ts" element="concurrent lane 2b (issue 10, metadata completeness) worktree copy of the page script">
**What changes:** nothing in this build.

**Why it matters:** lane 2b lists "video page metadata block" and "Depends on 14 (same page)" (`docs/project/issues/plan.md:71`). Its worktree copy still has the original description block at lines 209-210.

**Regression risk:** merge conflict, not runtime. Keeping line 210 verbatim and adding the new lines only after it reduces the conflict to an insertion.
</impact>
<impact path="docs/project/issues/13-video-comments.md" element="planned comments section under the description">
**What changes:** nothing now.

Issue 13 will render comments "below the description block". After this build, the element directly below the description is `#description-toggle`, so issue 13 must insert after the button.

**Regression risk:** none now. This is a future-integration note.
</impact>


## Documentation to update

- [x] `docs/project/issues/14-collapsible-description.md` - updated: Issue 14 is marked `complete` with a Delivered comment and written to `docs/project/issues/archive/`, but the original still has to be deleted by hand.
- [x] `docs/project/issues/plan.md` - updated: Wave 1 lane 1d (issue 14, collapsible description) is now marked "Delivered."
- [x] `docs/project/plans/19-14-collapsible-description.md` - updated: Not moved: the plan and its `.record.md` still need moving to `docs/project/plans/archive/`, by a step that has a shell, after the run's last render.
- [x] `client/frontend/README.md` - updated: Added one "What it does" bullet in `client/frontend/README.md` covering the video page's 4-line description clip and its Show more/Show less toggle.
- [x] `docs/project/roadmap.md` - updated: Added a Delivered line to the roadmap for issue `14`, the collapsible video description, pointing at the archived plan.
- [x] `docs/project/issues/13-video-comments.md` - out of scope: It says comments render "under the video description" and "below the description block". Both are still true, because the new toggle sits inside the same `.player-info` column directly after the description and belongs to that block. That lane 5b must insert after `#description-toggle` is an implementation detail for that build's own discovery. It does not make a claim in this issue false.
- [x] `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md` - out of scope: This is the only ADR near this area. It covers what the metadata endpoint accepts, and this build changes neither the endpoint nor the metadata shape. The browser-check recipe's uuid-only `/video-page.html?id=...&host=...` URL depends on it and agrees with it. ADRs 0001, 0002, 0004, 0005 and 0006 cover backend event IDs, proxies, CORS, retention and ANN IDs, none of which this build touched.

## Implementation plan

## What this build has to test

The node/esbuild harness has no layout engine, and no active test imports the video page script. So there is no new automated test. The gates are:

| Gate | How | Covers |
|---|---|---|
| Build | `cd client/frontend && npm run build` exits 0 | markup and CSS parse, and the script bundles |
| Type check (advisory) | `cd client/frontend && npx tsc --noEmit` | typos in `getComputedStyle` properties and in the `ResizeObserver` and `HTMLButtonElement` types, which `vite build` does not check |
| Suite | whole `tests/active` suite exits 0, as in the baseline | nothing regresses, including the gateway grep scan over `client/frontend/src` |
| Sink check | grep the diff for `innerHTML` near `description` and find none; line 210 byte-identical | acceptance criterion on `textContent` |
| Browser check (maintainer) | the hand-off recipe below | req. 1-6: clip at 4 lines, toggle only on overflow, resize, fresh state per load, keyboard and `aria-expanded`, ghost-button look |

## Module map

Three files change. No new file, no dependency, no `dist/` edits.

| File | Change |
|---|---|
| `client/frontend/video-page.html` | line 96 gains class `description-collapsed`; a new button is added after it as the last child of `.player-info` |
| `client/frontend/src/video.css` | two new rules placed directly after `.video-description` (lines 450-458), so the calc sits next to the values it copies |
| `client/frontend/src/pages/video-page/index.ts` | one constant and one `let` in the header block (lines 22-51); four lines after line 210; two functions and a module-level listener next to `applyActionIcons` (around line 1218) |

## Markup: `video-page.html`

```html
            <div id="video-description" class="video-description description-collapsed"></div>
            <button id="description-toggle" class="ghost-button description-toggle" type="button" aria-controls="video-description" aria-expanded="false" hidden>Show more</button>
          </div>
```

- The attribute order (`id`, `class`, `type`, then state) follows the block buttons at lines 62-63.
- The id and the base class of the description stay byte-identical.
- The button is `hidden` until the script measures overflow. `.ghost-button` sets no `display`, so the UA `[hidden]` rule applies.
- `icon-button` is deliberately left off: its `display: inline-flex` would defeat `hidden`.

## Style: `video.css`, inserted after line 458

```css
/* Keep in step with .video-description: 4 lines of its line-height, plus its vertical padding and border (box-sizing is border-box). */
.video-description.description-collapsed {
  max-height: calc(4 * 1.45em + 1.6rem + 2px);
  overflow: hidden;
}

.description-toggle {
  align-self: flex-start;
}
```

- With the inherited 16px font, the height is 92.8px of text + 25.6px of padding + 2px of border = 120.4px.
- The clip is a hard cut at the bottom of line 4. That is a named simplification. Its upgrade path is an `::after` gradient on the collapsed class, with no script change.
- The coupling comment is the only safeguard against the calc drifting if F5-M2 or issue 13 changes the base padding, border or line-height.

## Script: `index.ts`

### Header block (after line 34, and after line 51)

```ts
const descriptionEl = document.getElementById("video-description");
const descriptionToggle = document.getElementById("description-toggle") as HTMLButtonElement | null;
```

```ts
let currentMetadata: VideoMetadata | null = null;
let reaction: Reaction = { liked: false, disliked: false };
let descriptionIsPlaceholder = false;
```

- Both are declared above `void loadVideo()` at line 79, so they are out of the temporal dead zone whatever the timing of `loadVideo`'s first await.
- The flag is at module level because the `ResizeObserver` callback runs outside `loadVideo`'s scope.

### `loadVideo`: the description block (lines 209-211)

```ts
  if (descriptionEl) {
    descriptionEl.textContent = description ? description : "No description available.";
    descriptionIsPlaceholder = !description;
    setDescriptionExpanded(false);
    if (!descriptionEl.dataset.wired) {
      descriptionEl.dataset.wired = "true";
      new ResizeObserver(() => updateDescriptionToggle()).observe(descriptionEl);
    }
  }
```

- Line 210 is unchanged. The new lines are pure insertions after it, so a merge with lane 2b (issue 10) is an insertion, not a conflict.
- The `dataset.wired` guard uses the file's own idiom (lines 282-283, 327-328). There is only one observer per element even if issue 11 or 12 makes `loadVideo` re-entrant.
- The observer's first callback runs after layout, so it performs the initial measurement. No synchronous measure call is needed.
- On a re-entrant `loadVideo`, the text change resizes the element, so the existing observer measures again.
- `setDescriptionExpanded(false)` makes the class, label and ARIA consistent with the static markup, and it resets a re-entrant load to collapsed.

### New functions and wiring (inserted before `applyActionIcons`, around line 1218)

```ts
/**
 * Handle set description expanded: the only writer of the collapsed class, the toggle label and aria-expanded.
 */
function setDescriptionExpanded(expanded: boolean) {
  descriptionEl?.classList.toggle("description-collapsed", !expanded);
  if (!descriptionToggle) return;
  descriptionToggle.setAttribute("aria-expanded", String(expanded));
  descriptionToggle.textContent = expanded ? "Show less" : "Show more";
}

/**
 * Handle update description toggle: show the toggle only while the full text is taller than the 4-line clip.
 */
function updateDescriptionToggle() {
  if (!descriptionEl || !descriptionToggle) return;
  if (descriptionIsPlaceholder) {
    descriptionToggle.hidden = true;
    return;
  }
  // scrollHeight is the full text plus padding whether clipped or not, so this works in both states.
  const style = getComputedStyle(descriptionEl);
  const textHeight = descriptionEl.scrollHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
  // 1px tolerance: scrollHeight is an integer and 4 lines of 1.45 are fractional (92.8px at 16px).
  const overflows = textHeight > 4 * parseFloat(style.lineHeight) + 1;
  descriptionToggle.hidden = !overflows;
  if (!overflows) setDescriptionExpanded(false);
}

descriptionToggle?.addEventListener("click", () => {
  setDescriptionExpanded(descriptionEl?.classList.contains("description-collapsed") ?? false);
});
```

**Invariants**

- **`setDescriptionExpanded`** is the only place the class, the label and `aria-expanded` change, so they cannot drift apart.
  - The inverted boolean is intentional: `expanded` means the class is absent, hence `toggle(cls, !expanded)`.
- **The click handler** passes "is currently collapsed" as the new `expanded` value.
  - Collapsed → expand; expanded → collapse.
  - If `descriptionEl` is null it passes `false`, which is harmless because the button is never shown in that case.
- **`updateDescriptionToggle`**
  - It never expands.
  - It collapses only when the text no longer overflows. An expanded, still-overflowing description stays expanded (req. 3).
  - A description that overflows again later returns collapsed, with "Show more" and `aria-expanded="false"`.
- **Placeholder text** always keeps the button hidden (req. 2).
- **The listener** is wired once at module level. It is never inside `loadVideo`, so a re-entrant load cannot double-bind it.
- **Script-side placement.** It is a top-level statement next to `applyActionIcons();`. It runs during module evaluation, after the header constants exist, and it calls only hoisted function declarations.
- **Page-view state only.** The class on the element is the only state: no storage, cookies, URL or server write (req. 4). Every video is a full page load, via plain hrefs from `videoPageUrl`, so every video starts collapsed from the static class.
- **Keyboard.** Enter and Space come from the native `<button>`; there is no key handling (req. 5).

### Measurement notes

- `line-height: 1.45` is unitless, so the computed `lineHeight` is a px string (`"23.2px"`) and `parseFloat` is exact.
  - This depends on the rule never becoming `normal`; `normal` would give `NaN` and keep the button hidden. The coupling comment in the CSS covers this.
- Even if an engine left the bottom padding out of `scrollHeight`, a 5-line text still measures 116 − 12.8 = 103.2px. That is above the 93.8px limit, so the test holds.
- **ResizeObserver loop.**
  - Showing or hiding the button can toggle the page scrollbar and so the description's width in the same frame. The browser may then log the benign "ResizeObserver loop completed with undelivered notifications".
  - State still converges, because both transitions are monotone in width, and nothing in the file listens for window `error`.
  - The plan's "no feedback loop" holds for state, not strictly for that console notice.
- No debounce: the callback is two layout reads on one element.

## Check against the plan and the requirements (pass 1, converged)

| Req | Where it is met |
|---|---|
| 1. Collapsed, 4 lines, `textContent`, class-driven, CSS height from line-height | static class plus the `.description-collapsed` calc; line 210 unchanged |
| 2. Toggle only on overflow, labels, placeholder has no button | `updateDescriptionToggle` sets `hidden`; `setDescriptionExpanded` sets the label; placeholder flag |
| 3. Resize re-evaluation, stays expanded while overflowing, works expanded | `ResizeObserver`; the `scrollHeight` measurement is state-independent; collapse happens only on no-overflow |
| 4. Per page view | no persistence; static collapsed class on every load |
| 5. Accessible | real `<button type="button">`; `aria-controls`; `aria-expanded` synced in the single writer |
| 6. Visual consistency | `.ghost-button`, plus layout-only `align-self` |
| Constraints | three files only, platform APIs only, no metadata, Engine or backend change, no new `innerHTML`, no `dist/` edit, no gateway-forbidden strings |

**Deviations from the plan**

- The plan's `setDescriptionExpanded(false)` + observer sequence is kept.
- The observer creation is guarded with `dataset.wired`, following the impact inventory's recommendation. It changes nothing on today's single-load path.
- The placeholder flag is an explicit `let`, one of the two options the inventory allows.

## Hand-off recipe (the implementer copies this into the hand-off)

**Deploy:** `cd client/frontend && npm run build`, then from the repo root `sudo rsync -a --delete client/frontend/dist/ /var/www/peertube-browser/`, then do a hard reload.

**Find test videos:**
- Long (8 or more line breaks): `sqlite3 engine/server/db/whitelist.db "SELECT video_uuid, instance_domain, title FROM videos WHERE length(description) - length(replace(description, char(10), '')) >= 8 LIMIT 5;"`
- Short: `sqlite3 engine/server/db/whitelist.db "SELECT video_uuid, instance_domain, title FROM videos WHERE length(description) BETWEEN 1 AND 80 AND length(description) - length(replace(description, char(10), '')) <= 1 LIMIT 5;"`
- Empty: `sqlite3 engine/server/db/whitelist.db "SELECT video_uuid, instance_domain, title FROM videos WHERE description IS NULL OR trim(description) = '' LIMIT 5;"`

**Open a result:** `/video-page.html?id=<video_uuid>&host=<instance_domain>`.
- The page resolves metadata from `id` and `host` alone: the Engine matches `video_id` or `video_uuid`, and the instance fallback accepts a uuid.
- The phrase "the shape `videoPageUrl` builds" is dropped. That function also adds `title`, `channel`, `embed` and other parameters.

**Checks:**
- A long video opens showing 4 lines and "Show more". Click: the full text shows and the label reads "Show less". Click again: 4 lines.
- Short and empty descriptions show no button.
- Narrow the window until a short description wraps past 4 lines: the button appears. Widen it again: the button goes away.
- Open another video: it starts collapsed.
- Tab reaches the button, Enter or Space toggles it, and `aria-expanded` flips (inspect it in devtools).

## Tradeoffs carried from the plan

- Hard clip with no ellipsis or fade.
- No debounce on the resize measurement.
- The feature is deliberately self-contained (one class, one button, two functions) so that F5-M2 or issue 13 can lift it out.
- Issue 13 must insert comments after `#description-toggle`.
- Whether to commit the rebuilt `dist/` is the operator's call.

### Phases

#### Phase 1 - Static 4-line clip and hidden toggle [code]

**Files touched.** client/frontend/video-page.html (EDITED), client/frontend/src/video.css (EDITED)

**Checkpoint.** No automated seam exists. The node/esbuild harness in tests/active/test_frontend_*.py bundles data modules only and has no layout engine, and the settled draft adds no test. Gates: `cd client/frontend && npm run build` exits 0, and the whole tests/active suite exits 0 as in the baseline, which includes the gateway grep scan over client/frontend/src. Maintainer browser check: deploy per the hand-off recipe, hard reload, and open a long-description video (≥8 line breaks, from the hand-off query). It must show exactly 4 whole lines with the cut on the bottom edge of line 4 and no partial 5th line, which checks that the border-box calc includes padding and border. No toggle is visible. In devtools Elements, #description-toggle sits directly after #video-description inside .player-info with type="button", class ghost-button description-toggle, aria-controls="video-description", aria-expanded="false" and the hidden attribute.

**Intent.** video-page.html renders #video-description with the description-collapsed class, which video.css clips at the bottom of its fourth line box, and follows it with a hidden ghost-button #description-toggle.

- C1 - A description longer than four lines renders exactly four lines, cut at the bottom edge of the fourth line box.
- C2 - A hidden native button #description-toggle, styled as ghost-button and controlling video-description with aria-expanded="false", follows the description inside .player-info.

**Outcome.** ### `client/frontend/video-page.html`
- `#video-description` now has the class `description-collapsed` as well as `video-description`.
- A new `<button id="description-toggle" class="ghost-button description-toggle" type="button" aria-controls="video-description" aria-expanded="false" hidden>Show more</button>` sits directly after `#video-description`, still inside `.player-info`. It is formatted over several lines, like `#dislike-button`. It stays hidden until Phase 2 wires it up.

### `client/frontend/src/video.css`
- New rule `.video-description.description-collapsed`. It cuts the description at the bottom of its fourth line using `display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 4; overflow: hidden`. Counting lines rather than using a fixed `max-height` means a line made taller by an emoji or a fallback font does not shift the cut.
- The same rule stops the fifth line showing through the bottom padding, which it otherwise would because `overflow` clips at the edge of the padding. The padding is set to `0`, and its space becomes a transparent border: `border-width: calc(0.8rem + 1px) calc(1rem + 1px)`. The 1px frame is redrawn as `outline: 1px solid var(--line); outline-offset: -1px`. The collapsed box is the same size as the uncollapsed one, and the text wraps the same. The background still fills the whole box, because a background paints under a transparent border by default.
- A `rat-tail:` comment records the limit: the outline follows the rounded corners only in browsers that support that (Safari 16.4+). The upgrade path is `overflow-clip-margin: content-box`, which would let the real padding and border come back.
- The line clamp adds an ellipsis at the end of line 4 when text is cut. A description of four lines or fewer looks as it did before.
- No rule for `.description-toggle` was added. It is hidden in this phase, and `.ghost-button` sets no `display` that would override `hidden`.

#### Phase 2 - Overflow-driven toggle [code]

**Files touched.** client/frontend/src/pages/video-page/index.ts (EDITED)

**Checkpoint.** No automated seam exists. The video page script is a page entry with DOM side effects, no active test imports it, and the harness has no layout engine. Gates: `npm run build` exits 0; `npx tsc --noEmit` is advisory and catches getComputedStyle, ResizeObserver and HTMLButtonElement typos; the tests/active suite exits 0; the sink check greps the diff and finds no new innerHTML near the description, with the textContent line at 210 byte-identical. Maintainer browser check per the hand-off recipe. A long video shows "Show more", and a click expands it to "Show less" and a second click collapses it. Short and empty (placeholder) descriptions show no button. Narrowing the window until a short description wraps past 4 lines makes the button appear, and widening removes it. Another video opens collapsed. Tab reaches the button, Enter and Space toggle it, and aria-expanded flips in devtools.

**Intent.** index.ts shows #description-toggle exactly while the real description's text is taller than four lines, re-measuring on every resize, and activating the toggle flips the collapsed class, its label and aria-expanded together.

- C1 - The toggle is visible only while the non-placeholder description text is taller than four lines at the current width.
- C2 - Activating the toggle switches between four lines with "Show more" and aria-expanded="false" and the full text with "Show less" and aria-expanded="true".

**Outcome.** ### `client/frontend/src/pages/video-page/index.ts`
- Looks up `#description-toggle` as `descriptionToggle`, next to `descriptionEl`. Adds a constant `DESCRIPTION_CLAMP_LINES = 4`, with a comment that it matches the `-webkit-line-clamp` of `.description-collapsed` in video.css.
- New function `updateDescriptionToggle()`, which decides whether the toggle shows (C1):
  - It hides the toggle when there is no real description (`currentMetadata?.description` is empty), so the placeholder never gets one.
  - Otherwise it measures the text height as `scrollHeight` minus the computed top and bottom padding. That works collapsed (no padding, clipped lines still counted) and expanded (0.8rem padding).
  - It rounds that height to whole lines using the computed `line-height`, and shows the toggle only when the result is more than `DESCRIPTION_CLAMP_LINES`. Rounding stops `scrollHeight`'s whole-pixel rounding from making exactly four lines look taller.
- `loadVideo` calls `updateDescriptionToggle()` right after it writes the description text.
- A block at module load (next to the `similarLink` wiring) sets up two things when both elements exist:
  - A click listener on the toggle (C2). It flips `description-collapsed` on the description, then sets the label to "Show more" or "Show less" and `aria-expanded` to `false` or `true` to match.
  - A `ResizeObserver` on the description that calls `updateDescriptionToggle()` on every size change, so a new width re-measures it.
- Nothing else in the file changed. The description keeps its full text; the clip is CSS only.


