# 28-tailwind-evaluation

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/21-28-tailwind-evaluation.record.md`._

## Requirements

### Purpose

Styles in the frontend (`client/frontend`) are fragmented. The feed, video and channels page stylesheets each carry their own copy of the same base rules, and three class names mean different components on different pages. This build moves the copied rules into one shared base stylesheet and renames the shared video card's colliding classes. Nothing should change visually on any page. The point is to get the codebase ready for later card reuse: roadmap F13-M2 plans cards on the channels page, and those cards would collide with the current names. The build also leaves one place for future design-system work (F6-M2, F7-M2). Tailwind, or any CSS framework, is deferred to F6-M2/F7-M2. It is not rejected.

### Current state (verified in the tree)

- The build is vite plus TypeScript only, with no PostCSS or Tailwind. `client/frontend/vite.config.ts` has these entries: index.html, videos.html, search.html, likes.html, video-page.html, channels.html, and About. About is `dev-pages/about.html` when that file exists, otherwise `dev-pages/about.template.html`.
- There are five page stylesheets in `client/frontend/src/`: `about.css`, `channels.css`, `search.css`, `video.css` and `videos.css`.
- Each page gets its stylesheets through imports in its script:
  - `src/pages/videos/index.ts` and `src/pages/likes/index.ts` import `../../videos.css`. The index page uses the same feed bundle.
  - `src/pages/search/index.ts` imports `../../videos.css`, then `../../search.css`. The built `dist/search.html` nevertheless links the search CSS bundle before the videos CSS bundle, so for a selector both sheets declare, the `videos.css` rule wins on the search page.
  - `src/pages/video-page/index.ts` imports `../../video.css`.
  - `src/pages/channels/index.ts` imports `../../channels.css`.
- The About page has no script. `dev-pages/about.template.html` links `<link rel="stylesheet" href="/src/videos.css" />` directly. A local `dev-pages/about.html` override may do the same; `client/frontend/README.md` line 43 documents that overrides use root-absolute URLs such as `/src/videos.css`. The built output is `dist/dev-pages/about.template.html`, which links the videos CSS bundle.
- The committed build output `client/frontend/dist/` has one CSS bundle per page: `channels-*.css`, `search-*.css`, `video-*.css` and `videos-*.css`.
- Rules that are byte-identical wherever they are declared:
  - In channels, video and videos: `:root` (colour tokens plus font-family/color/background), `*` (box-sizing), `body`, `.header-nav`, and its `@media (max-width: 720px)` `.header-nav` rule.
  - In video and videos: `.videos-header` and `.ghost-link`.
  - In channels and videos: `.summary` and `.summary-meta`.
  - In video and videos: `.key-rejected`.
  - `.eyebrow` is in all three.
- Media blocks: in `video.css` the 720px media block also holds `.videos-header{padding-top:5rem}`, and in `channels.css` it holds `.channels-header`, `.summary` and `.pager` overrides. These page-specific overrides are not part of the base, and they only keep working if the base loads before the page sheet.
- `channels.css` has `button, input, select, textarea { font: inherit; }`. It is unique to channels and stays there.
- Near-identical rules:
  - `.nav-link`: videos adds `position: relative; display: inline-flex; align-items: center`. Channels and video are identical to each other.
  - `.ghost-button`: channels adds `align-self: end`. Video's `transition` is `border-color 0.2s ease, color 0.2s ease, background 0.2s ease`; the others use `border-color 0.2s ease, color 0.2s ease`.
  - `.subtitle`: `max-width: 38ch` in channels and videos, `48ch` in video.
  - `.empty` (channels and videos only): `padding: 2rem 1rem` in videos, `2.5rem 1rem` in channels.
- `.visually-hidden` has two versions:
  - `search.css` line 69, complete: `position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0`.
  - `videos.css` line 678, short: `position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap`.
- Colliding class names:
  - The shared video card, `src/components/video-card.ts` (around lines 371-374), emits `<h3 class="video-title">`, `<div class="channel-meta">` and `<div class="channel-avatar" aria-hidden="true">`. They are styled in `videos.css`: `.video-title` at line 485, `.channel-meta` at 520, `.channel-avatar` at 526 and `.channel-avatar img` at 542.
  - The video page (`video-page.html` lines 40-43, `video.css` lines 156, 168, 181 and 203) uses `video-title`, `channel-avatar` and `channel-meta` for its heading, its avatar and its channel name/subscriber column. It also uses the element ids `video-title` and `channel-avatar`, which are read in `src/pages/video-page/index.ts` and in `tests/active/test_frontend_video_page.py`.
  - The channels page row (`src/pages/channels/index.ts` line 279) emits `<div class="channel-meta">` for the instance domain, styled in `channels.css` line 327.

### Desired behaviour

1. **One shared base stylesheet** holds every rule that is now copied byte-identically between page stylesheets:
   - the colour tokens (`:root`), `*` and `body`;
   - `.header-nav`, plus its narrow-screen `@media (max-width: 720px)` `.header-nav` rule where it is identical;
   - `.eyebrow`, `.videos-header`, `.summary`, `.summary-meta`, `.key-rejected` and `.ghost-link`.

   Every copy is removed from the page sheets. Page-specific rules inside shared media blocks stay in their page sheets, for example video's `.videos-header{padding-top:5rem}` and channels' `.summary` override.
2. **Near-identical rules use base plus override.** For `.nav-link`, `.ghost-button`, `.subtitle` and `.empty`, the base holds the declarations that every declaring sheet shares. Each page sheet keeps a rule with only the declarations where it differs. The page's own values must still win on that page, so the base loads before the page sheet. A rule in a sheet that already matches the shared form is removed from that sheet completely.
3. **`.visually-hidden`** is defined once, in the base, in the complete form: `position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0`. No page sheet defines it, so both the `search.css` and the `videos.css` copies are removed.
4. **The shared video card's classes are renamed.** The markup the component emits and the `videos.css` rules are renamed together:
   - `video-title` becomes `card-title`.
   - `channel-meta` becomes `card-channel`.
   - `channel-avatar` becomes `card-avatar`, including its descendant `img` rule.

   The channels page's `channel-meta` becomes `channel-domain`, in the row markup in `src/pages/channels/index.ts` and in `channels.css`. The video page keeps `video-title`, `channel-meta` and `channel-avatar` unchanged, both as classes and as element ids, in `video-page.html`, `video.css` and its script.
5. **The base reaches every page that loads a page stylesheet.** That includes a page with no script that links a page stylesheet directly: the About template, and a local About override that links `/src/videos.css`. Whatever loads a page sheet loads the base before it, with no change to any page's HTML.
6. **The committed build output in `client/frontend/dist/` is regenerated** from the changed sources, so the served pages use the new stylesheets.

### Key interfaces

- The shared video card component (`src/components/video-card.ts`): only the class attributes on the card title, the channel row and the avatar change, as in item 4. Its function signatures and the rest of its markup stay the same.
- The channels page row rendering: only the class on the instance-domain element changes, to `channel-domain`.
- Stylesheet load order per page: the base comes first, then the page sheets in their current relative order. The search page keeps the search sheet before the feed sheet, as in the current built output.

### Acceptance criteria

- [ ] No rule that the base stylesheet holds is also declared in any page stylesheet, except the item 2 override rules, which carry only their differing declarations.
- [ ] Final declarations per page. For every built page (index, videos, likes, search, video page, channels, and About built from the template):
  - Apply that page's stylesheets in load order, last rule wins, and list the declarations that end up on each selector, renamed selectors mapped back to their old names.
  - Every selector the page had before the change has an identical declaration list afterwards.
  - A selector that is new to a page, because the base now carries a rule that page's sheets never declared, is allowed only if nothing in that page's HTML or script uses it. The expected additions are `.videos-header`, `.ghost-link`, `.key-rejected` and `.visually-hidden` on channels, and `.summary`, `.summary-meta`, `.empty` and `.visually-hidden` on the video page.
  - The only allowed change to an existing selector is `.visually-hidden`. On index, videos, likes and About it gains `padding: 0`, `margin: -1px` and `border: 0`, and its `clip` changes from `rect(0 0 0 0)` to `rect(0, 0, 0, 0)`. On search only the `clip` spelling changes, from `rect(0 0 0 0)` to `rect(0, 0, 0, 0)`; it renders the same.
- [ ] The shared video card's output contains `card-title`, `card-channel` and `card-avatar`, and none of `video-title`, `channel-meta` or `channel-avatar`.
- [ ] The channels page row contains `channel-domain` and not `channel-meta`.
- [ ] The video page's HTML and script still use `video-title`, `channel-meta` and `channel-avatar`, and its element ids are unchanged.
- [ ] The About template, built with no override present, loads the base rules: its colour tokens and body styles are as they were.
- [ ] The committed build output is rebuilt from the changed sources, and every existing frontend test passes, including `tests/active/test_frontend_video_page.py`.

### Out of scope

- Tailwind, or any CSS framework, preprocessor or PostCSS plugin. That belongs to roadmap F6-M2/F7-M2.
- Changing any page's appearance. That includes unifying the near-identical rules to one value: where pages differ today, they still differ afterwards.
- `about.css` and its rules, apart from the About page receiving the base.
- Renaming the video page's classes, or any class not named in item 4.
- Other cleanup inside the page stylesheets, such as dead rules, or reordering beyond what the move needs.
- Editing the F7-M2 roadmap line that still names issue 28 as its Tailwind link. The triage says not to delegate that to this issue; it is done when this lands, outside the build.

### Baseline suite state

The pre-build run selected 2 of 47 test groups: `test_blocks.py` (7 passed) and `test_search_fusion.py` (10 passed), 17 passed with no failing tests. The exit code was 1 because of the selection variant, not because of failures. The operator approved this baseline.

## High-level plan

### Approach

Add one new stylesheet, `client/frontend/src/base.css`. It opens with a short header comment in the style of `search.css`. Each page sheet pulls it in with a CSS `@import "./base.css";` as its first line. Vite 5 inlines CSS `@import` on its own, with no PostCSS config or plugin, so each built CSS bundle still has one file per page. Each bundle starts with the base rules and then has that page's own rules. Nothing about load order is left to Vite's chunk ordering. The base comes before the page rules because it is physically first in the same bundle.

The `@import` goes into `videos.css`, `video.css`, `channels.css` and `search.css`. `about.css` is out of scope and nothing loads it today, so it gets no import.

The tree confirms that `dev-pages/about.template.html` links only `/src/videos.css`, and that no local `about.html` override exists right now.

How each requirement is met:

- **Item 1 (shared base).** These rules move into `base.css` once and are deleted from every page sheet:
  - `:root`, `*` and `body`
  - `.header-nav` and its `@media (max-width: 720px)` `.header-nav` rule
  - `.eyebrow`, `.videos-header`, `.summary`, `.summary-meta`, `.key-rejected` and `.ghost-link`

  Page-specific rules inside the shared 720px media blocks stay in their page sheets, each still wrapped in its own `@media (max-width: 720px)` block:
  - video: `.videos-header{padding-top:5rem}`
  - channels: `.channels-header`, `.summary` and `.pager`
  - videos: `.videos-header` and `.summary`

  Item 1 says "every rule that is now copied byte-identically". Reading the sheets shows four companion rules that are byte-identical but missing from the enumerated list: `.nav-link.active, .nav-link:hover` (all three sheets), `.ghost-button:hover` (all three), `.videos-header h1` (video and videos) and `.ghost-link:hover` (video and videos). I take the "every" clause literally and move them too. All four have higher specificity than, or no overlap with, the rules that stay behind, so moving them earlier is cascade-neutral.
- **Item 2 (base plus override).** For `.nav-link`, `.ghost-button`, `.subtitle` and `.empty`, the base rule holds exactly the declarations that every declaring sheet shares, with the same values. Each page sheet keeps a rule for that selector with only the declarations that are not in the base. A sheet whose rule then has nothing left loses it entirely:
  - `.nav-link`: the base takes the channels/video form. channels and video drop the rule. videos keeps `position: relative; display: inline-flex; align-items: center`.
  - `.ghost-button`: the base takes border, background, padding, border-radius, cursor, font-size and color. All three sheets keep a `transition` line, because the three values are not all the same. channels also keeps `align-self: end`.
  - `.subtitle`: the base takes `margin` and `color`. Each of the three sheets keeps its own `max-width`.
  - `.empty`: the base takes the shared declarations. channels and videos each keep their own `padding`.

  Because the base is inlined ahead of the page rules, the page value wins wherever the specificity is the same.
- **Item 3 (`.visually-hidden`).** The complete form goes into the base once. The copies in `search.css` (line 69) and `videos.css` (line 678) are deleted.
- **Item 4 (renames).**
  - In `src/components/video-card.ts` (lines 371-374), only the three class attribute values change: `card-title`, `card-channel` and `card-avatar`.
  - In `videos.css`, `.video-title` (485), `.channel-meta` (520), `.channel-avatar` (526) and `.channel-avatar img` (542) are renamed to match.
  - In `src/pages/channels/index.ts` (line 279) and `channels.css` (line 327), `channel-meta` becomes `channel-domain`.
  - `video-page.html`, `video.css` and `src/pages/video-page/index.ts` are not touched for these names.
  - I checked that none of the new names already exists anywhere in the tree, and that no other file emits or styles the old card names.
- **Item 5 (base reaches every page with no HTML change).** Every route to a page sheet now gets the base: the script imports, the About template's `<link href="/src/videos.css">`, and any local About override that links `/src/videos.css`. In a build, Vite inlines the `@import`. In dev, Vite serves the processed CSS. Even an unprocessed `/src/videos.css` would make the browser fetch `/src/base.css` relative to it, which Vite serves. No HTML file changes.
- **Item 6 (dist).** Run `npm run build` in `client/frontend` with no `dev-pages/about.html` present, so the About entry is built from the template. Commit the whole `dist/` diff: the new hashed CSS and JS assets, the updated HTML links, and the deleted old hashes. Vite empties `outDir` before building, so no orphans should remain, but check the diff for them anyway.

The final file count is one new file (`base.css`) and edits to four CSS files, two TS files and the rebuilt `dist/`.

### Alternatives considered

- **Import `base.css` from each page script ahead of its page sheet.** Rejected. It cannot reach the About page, which has no script, without editing its HTML, and item 5 forbids that. It would also make `base.css` a module shared by many entries, which Rollup would put in a shared chunk. Its position among the `<link>` tags would then depend on Vite's chunk ordering. That ordering already produces the surprising search-before-videos order today, so the guarantee that the base comes first would rest on Vite internals.
- **A small Vite plugin that injects a base `<link>` into every HTML entry.** Rejected. It adds build machinery to do what one standard CSS `@import` line already does. It also changes the HTML output and does not cover the About override in dev.
- **Leave out the `@import` in `search.css`, since the search page already gets the base through `videos.css`.** Considered and rejected. On search, the order would be search, then base, then videos. Today the cascade would come out the same, because after its `.visually-hidden` is removed `search.css` declares nothing the base declares. But it breaks the settled rule that whatever loads a page sheet loads the base before it.
- **Put the majority value into the base for `.ghost-button` transition and `.subtitle` max-width, so only video overrides.** Rejected. Item 2 defines the base as the declarations every declaring sheet shares, and these values are not shared by all three. The result is a few one-line override rules. The final declarations are identical either way.
- **A CSS framework or PostCSS.** Out of scope; deferred to F6-M2/F7-M2.

### Gotchas and risks

- **The base is loaded twice on the search page.** The order becomes base, search, base, videos. This adds about 2 KB to that page and has no cascade effect today. Limit: in future, any rule in `search.css` that overrides a base selector would lose to the second copy of the base, in the same way that `videos.css` already wins over `search.css` today. The upgrade path, if that ever matters, is one Vite-managed base chunk once F6-M2/F7-M2 revisits the CSS build.
- **Source order moves, not just selectors.** Moving a rule into the base puts it before every page rule, where before it sat somewhere in the middle of the page sheet. The per-selector acceptance comparison cannot see one specific case: an element that matches both a moved rule and an earlier page rule with the same specificity, where both set the same property, could now resolve differently. I checked the obvious cases and found nothing:
  - The `.key-rejected` notice also carries `.error`, and `.error` already came after it.
  - The `.visually-hidden` spans carry no other class.
  - The video page's `.ghost-link` anchors have no competing class rule.

  The verification step should still repeat this check for each moved rule against the elements that use it, not rely on the selector-level comparison alone.
- **Override rules must keep the same selector text and specificity as the base rule.** The cascade then falls back to source order, which the inlining guarantees.
- **Media blocks are split.** The shared `.header-nav` 720px rule goes to the base. The remaining 720px rules stay in a page-sheet media block, which stays after the page's base-level rules, as before.
- **Minifier differences.** esbuild's CSS minifier rewrites values in the bundles, for example `rgba` to hex and an added `-webkit-backdrop-filter`. When comparing the old and new final declarations, compare minified against minified, from the committed old `dist/` and the newly built `dist/`, so that minifier rewrites do not show up as differences.
- **Building with a local About override.** If a developer has a local `dev-pages/about.html` when building, `dist/` gets that file instead of the template. The build for this change has to be run without one; there is none in the tree today.
- **Tests.**
  - The frontend tests bundle scripts with esbuild using `--loader:.css=empty`, so the CSS changes cannot break them.
  - `tests/active/test_frontend_video_page.py` reads the element id `video-title`, which is unchanged.
  - `tests/config.json` maps `test_frontend_video_page.py` to `video.css`, so that test will be selected and has to pass.

### Tradeoffs the operator is asked to accept

- About 2 KB of base CSS is duplicated on the search page (base, search, base, videos). In return, the requirement that the base comes first holds without relying on Vite chunk-ordering internals.
- The base is also inlined into each page bundle rather than cached once across pages. That is the same byte cost as today's copied rules, so it is no regression, but it is no caching gain either. A single cached base file belongs to the F6-M2/F7-M2 build work.
- The strict intersection rule leaves small leftover overrides (`.ghost-button` transition, `.subtitle` max-width), even where two of the three pages agree. Collapsing them would change nothing visually, but it goes beyond what item 2 permits.
- Four byte-identical companion rules that the enumerated list does not name (`.nav-link.active, .nav-link:hover`, `.ghost-button:hover`, `.ghost-link:hover`, `.videos-header h1`) also move into the base, under the "every rule that is copied byte-identically" clause of item 1. If the operator wants the base limited strictly to the enumerated list, they stay where they are, and visually nothing differs either way.

## Impacts


<impact path="client/frontend/src/base.css" element="new file: the shared base stylesheet">
**What changes:** a new file. It opens with a block comment in the style of `search.css` lines 1-4, e.g. "Rules shared by every page sheet. Each page sheet pulls this in with `@import "./base.css";` so the base is inlined ahead of its own rules." It holds, in this order (the order inside the base matters wherever two moved rules have the same specificity and match the same element):

- `:root` (copy of videos.css 1-16), `*` (18-20) and `body` (22-25).
- `.header-nav`, with its comment "Pinned to the viewport…" (videos.css 61-75), then the `@media (max-width: 720px) { .header-nav {…} }` block (videos.css 77-84). The media rule has to come after the plain `.header-nav` rule: both are (0,1,0), and it overrides `right` and `border-radius`.
- `.nav-link` with only the channels/video declarations: `text-decoration`, `padding`, `border`, `border-radius`, `color`, `font-size` and `transition: border-color 0.2s ease, transform 0.2s ease`. Then `.nav-link.active, .nav-link:hover`.
- `.eyebrow`, `.videos-header`, `.videos-header h1`, and `.subtitle { margin: 0; color: var(--muted); }`.
- `.summary`, `.summary-meta` and `.key-rejected`.
- `.ghost-button`: `border`, `background`, `padding`, `border-radius`, `cursor`, `font-size` and `color`, with no `transition`. Then `.ghost-button:hover`.
- `.ghost-link` and `.ghost-link:hover`.
- `.empty { text-align: center; color: var(--muted); }`.
- `.visually-hidden` in the complete form from search.css 69-79.

`.ghost-button:hover` must come after `.ghost-button`, and `.nav-link.active,…` after `.nav-link`. Nothing else is order-sensitive.

**What depends on it:** every page bundle, through the `@import` in videos.css, video.css, channels.css and search.css. The search page gets it twice (in the search bundle and again in the videos bundle). Pages that gain selectors they never declared:
- channels: `.videos-header`, `.videos-header h1`, `.ghost-link`, `.key-rejected`, `.visually-hidden`.
- video page: `.summary`, `.summary-meta`, `.empty`, `.visually-hidden`.

I checked that none of these appear in channels.html, `pages/channels/index.ts`, video-page.html or `pages/video-page/index.ts`. Channels does not import `key-rejected.ts`, and the video page uses no `empty`, `summary` or `visually-hidden` class.

**Risk:** medium. A declaration copied with any byte difference, for example the `rgba(246, 242, 234, 0.92)` background or the gradient, changes every page. So does an `@media` rule placed before its base rule. No other `base.css` exists in the tree. Vite is 5.4.21 (package-lock.json line 1007), and its built-in postcss-import inlines a relative `@import` without a PostCSS config. There is no postcss/tailwind config in `client/frontend`.
</impact>
<impact path="client/frontend/src/videos.css" element="whole sheet: @import, removed base rules, residual overrides, card renames, .visually-hidden">
**What changes:**
- Line 1 becomes `@import "./base.css";`.
- **Removed:** `:root` 1-16, `*` 18-20, `body` 22-25, `.videos-header` 33-40, `.eyebrow` 42-48, `.videos-header h1` 50-53, the header-nav comment and rule 61-75, the whole `@media (max-width: 720px)` header-nav block 77-84 (it contains nothing else in this sheet), `.nav-link.active, .nav-link:hover` 99-103, `.summary` 112-118, `.summary-meta` 127-130, `.ghost-button:hover` 147-150, `.ghost-link` 165-169, `.ghost-link:hover` 171-173, `.key-rejected` 294-298 and `.visually-hidden` 678-685.
- **Reduced to residual overrides, in place:**
  - `.subtitle` 55-59 keeps only `max-width: 38ch`.
  - `.nav-link` 86-97 keeps only `position: relative; display: inline-flex; align-items: center`.
  - `.ghost-button` 136-145 keeps only `transition: border-color 0.2s ease, color 0.2s ease`.
  - `.empty` 380-384 keeps only `padding: 2rem 1rem`.
- **Renamed:** `.video-title` 485 → `.card-title`, `.channel-meta` 520 → `.card-channel`, `.channel-avatar` 526 → `.card-avatar`, `.channel-avatar img` 542 → `.card-avatar img`.
- **Kept unchanged:** the 900px block 695-701 and the 720px block 703-712 (`.videos-header` padding-top, `.summary`). Also `.channel-link`, `.channel-text`, `.video-meta` and the rest of the card rules (item 4 renames only three).

**What depends on it:** the index, videos, likes and search pages (script imports in `pages/videos/index.ts:5`, `pages/likes/index.ts:8` and `pages/search/index.ts:12`), and About through `<link href="/src/videos.css">` in `dev-pages/about.template.html:8`.

Multi-class elements I checked against the source-order shift:
- `nav-link nav-button` (index.html:27, videos.html:27): `.nav-button` 224 sets `font: inherit` and still comes after `.nav-link`, so `font-size` resolves the same.
- `ghost-button like-remove` (likes/index.ts:72): `.like-remove` 336 comes after either way.
- `video-debug empty` (videos/index.ts:474): `.video-debug` 570 already beat `.empty` on `color`, and the residual `padding` stays at 380, before 570.
- `error key-rejected` (key-rejected.ts:13): `.error` 687 comes after either way.
- `.feed-modes .ghost-button[aria-pressed="true"]` is (0,3,0), so it is unaffected.

**Risk:** high. This sheet feeds five pages. If the residual rules move instead of staying in place, or the renamed selectors and the card markup get out of step, card titles lose their 2-line clamp and avatars lose their 34px size. `.visually-hidden` intentionally gains `padding: 0; margin: -1px; border: 0` and the `clip` respelling (the allowed exception). Leftover rules that duplicate base selectors would fail the "no class rule that the base holds is also declared" criterion.

Note: `.videos-header` and `.summary` remain declared inside the page's 720px and 900px media blocks. Those are page-specific responsive rules. The next step should confirm that the acceptance criterion is read as top-level duplicates only.
</impact>
<impact path="client/frontend/src/video.css" element="whole sheet: @import, removed base rules, residual overrides; video-page names untouched">
**What changes:**
- Line 1 becomes `@import "./base.css";`.
- **Removed:** `:root` 1-16, `*` 18-20, `body` 22-25, `.videos-header` 33-40, `.eyebrow` 42-48, `.videos-header h1` 50-53, the header-nav comment and rule 70-84, the whole `.nav-link` rule 99-107 (identical to the base form), `.nav-link.active,…` 109-113, `.key-rejected` 292-296, `.ghost-button:hover` 360-363, `.ghost-link` 424-428 and `.ghost-link:hover` 430-432.
- **Media block 86-97:** only the `.header-nav` rule goes. `@media (max-width: 720px) { .videos-header { padding-top: 5rem; } }` stays where it is.
- **Residual overrides:**
  - `.subtitle` 55-59 keeps `max-width: 48ch`.
  - `.ghost-button` 349-358 keeps `transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease`.
- **Kept:** `.subtitle a` and `.subtitle a:hover` 61-68 (video-only selectors). `.video-title` 156, `.channel-avatar` 168, `.channel-avatar img` 181 and `.channel-meta` 203 stay unrenamed (item 4).

**What depends on it:** video-page.html through `pages/video-page/index.ts:5`.

Multi-class elements checked:
- `ghost-button icon-button` (video-page.html:76, 82): `.icon-button` 371 comes after.
- `ghost-button description-toggle`: no `.description-toggle` rule exists.
- `ghost-button comments-more`: `.comments-more` 618 comes after.
- `ghost-button comment-replies-toggle/more` (index.ts:529, 539): rule at 601, after.
- `.ghost-button.active` 365 vs the moved `.ghost-button:hover`: both (0,2,0), and `:hover` stays earlier, so `.active` still wins on `color`.

The ghost-link anchor (index.ts:442) has no other class.

**Risk:** medium. The obvious mistake is renaming the video page's `.video-title`, `.channel-avatar` or `.channel-meta` here, which would break the page's heading and avatar, and the acceptance criterion that the video page keeps these names. Removing the whole 720px block would lose the `padding-top: 5rem`. This file is mapped to `test_frontend_video_page.py` in tests/config.json:168-172, so that test is selected.
</impact>
<impact path="client/frontend/src/channels.css" element="whole sheet: @import, removed base rules, residual overrides, .channel-meta → .channel-domain">
**What changes:**
- Line 1 becomes `@import "./base.css";`.
- **Removed:** `:root` 1-16, `*` 18-20, `body` 29-32, `.eyebrow` 49-55, the header-nav comment and rule 68-82, the whole 720px header-nav block 84-91, `.nav-link` 93-101 (entire), `.nav-link.active,…` 103-107, `.ghost-button:hover` 168-171, `.summary` 173-179 and `.summary-meta` 211-214.
- **Kept, channels-only:** `button, input, select, textarea { font: inherit; }` at 22-27. It is not in the other sheets, so it is not a base rule.
- **Residual overrides:**
  - `.subtitle` 62-66 keeps `max-width: 38ch`.
  - `.ghost-button` 156-166 keeps `align-self: end` and `transition: border-color 0.2s ease, color 0.2s ease`.
  - `.empty` 342-346 keeps `padding: 2.5rem 1rem`.
- **Renamed:** `.channel-meta` 327 → `.channel-domain`.
- **Kept:** `.channels-header`, `.channels-header h1`, and the 900px block 348-359 and 720px block 361-375 (`.channels-header`, `.summary`, `.pager`).

**What depends on it:** channels.html through `pages/channels/index.ts:5`.

The `.empty` cells are `<td class="empty">` (index.ts:207, 248, 256), and `.channels-table td` (0,1,1) already overrode their `padding` and `text-align`. That is unchanged.

The only `.summary` element is `<section class="summary">` (channels.html:57). The ghost buttons (32, 63, 65) carry no other class.

**Risk:** medium. Moving the `button,input,select,textarea` rule into the base would change form fonts on the feed and video pages. Leaving `.channel-meta` here while index.ts emits `channel-domain` loses the 0.85rem muted styling.
</impact>
<impact path="client/frontend/src/search.css" element="@import line, header comment, .visually-hidden (69-79)">
**What changes:**
- Add `@import "./base.css";`. CSS allows it either as line 1 or after the block comment 1-4, as long as no rule precedes it.
- Delete `.visually-hidden` 69-79.
- The header comment still holds ("cards reuse videos.css"). One optional clause could note that the base comes via the import.

**What depends on it:** search.html through `pages/search/index.ts:13`. The built `dist/search.html` links the search CSS before the videos CSS (lines 18-19), so the effective order becomes base, search, base, videos.

None of search.css's selectors (`.search-controls`, `.search-form`, `.search-field*`, `.search-sort*`, `.search-status*`) is a base selector. The second copy of the base therefore overrides nothing from search.css today.

**Risk:** low today. The latent risk is that any future search.css rule on a base selector silently loses to the second base copy. The plan accepts this tradeoff.
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="renderVideoCard() markup, lines 371-374">
**What changes:** only three class attribute values change:
- line 371: `<h3 class="video-title">` → `card-title`
- line 373: `<div class="channel-meta">` → `card-channel`
- line 374: `<div class="channel-avatar" aria-hidden="true">` → `card-avatar`

Nothing else changes, including `channel-text`, `channel-link`, `visually-hidden` and the `stat` classes.

**What depends on it:**
- `renderVideoCard` callers: `pages/videos/index.ts:387` (index, videos) and `pages/search/index.ts:241`. Likes does not call it, although its bundle preloads the video-card chunk.
- The styling in videos.css 485/520/526/542.
- `tests/active/test_frontend_reactions.py`, which bundles this module (line 112) and only regex-matches `class="stat likes active"` and `class="stat dislikes active"`. It is selected through tests/config.json:97-103 and needs the live Engine/Client fixtures.

No TS code or test selects `.video-title`, `.channel-meta` or `.channel-avatar` on cards. Grep found no `querySelector` on these names in `src/`, and the only test hit is the video page's `#video-title` id.

**Risk:** low-medium. A partial rename (markup without CSS, or the reverse) leaves card titles unclamped or avatars unsized. There is no visual test, so only the dist and CSS comparison catches it.
</impact>
<impact path="client/frontend/src/pages/channels/index.ts" element="row template in render, line 279">
**What changes:** `<div class="channel-meta">` → `<div class="channel-domain">`. Nothing else changes.

**What depends on it:** the renamed `.channel-domain` rule in channels.css. No test bundles the channels page, and no channels test exists in tests/config.json.

**Risk:** low, provided it changes together with channels.css:327.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="getElementById('video-title'), ('channel-avatar') at lines 22, 24; ghost-link at 442; ghost-button classes at 529, 539">
**What changes:** nothing. It is listed because item 4 and the acceptance criteria require it to stay as it is.

**What depends on it:** the base now supplies `.ghost-link` and the shared `.ghost-button` declarations to the elements it creates. `tests/active/test_frontend_video_page.py:184` and `:223` read the `video-title` id.

**Risk:** low. The risk is an over-eager rename that reaches this file.
</impact>
<impact path="client/frontend/video-page.html" element="heading, channel row (lines 40-43), header (15-25)">
**What changes:** nothing. It keeps `class="video-title"`, `channel-avatar` and `channel-meta`, and the ids `video-title` and `channel-avatar`.

**What depends on it:** video.css 156/168/181/203. It is in the `test_frontend_video_page.py` group in tests/config.json.

**Risk:** low.
</impact>
<impact path="client/frontend/dev-pages/about.template.html" element="<link rel=stylesheet href=/src/videos.css> (line 8)">
**What changes:** nothing (item 5 forbids HTML changes).
- In dev: Vite serves `/src/videos.css` with the `@import` inlined. Even unprocessed, the import resolves to `/src/base.css`, which Vite serves.
- In the build: Vite turns the link into the hashed videos CSS asset, with the base inlined.

**What depends on it:**
- `tests/active/test_static_page_visit_logs.py` reads this file's bytes (line 31). That test only checks serving and logs, not the CSS. It is mapped to this file, but the file is unchanged, so the test is not selected.
- `dist/dev-pages/about.template.html`.

The page uses `.videos-header`, `.eyebrow`, `.subtitle`, `.header-nav`, `.nav-link`, `.summary` and `.summary-meta`, all of which now come from the base.

**Risk:** low. The `dev-pages/*` directory is gitignored except the template (.gitignore:29-30), so a local `about.html` override could exist on a developer machine and would hijack the build (vite.config.ts:91-93). None exists in this worktree.
</impact>
<impact path="client/frontend/vite.config.ts" element="build.rollupOptions.input and the About override switch">
**What changes:** nothing.

**What depends on it:** the build of item 6. The `about` input is `dev-pages/about.html` when that file exists, otherwise the template. The build must run with no override present.

**Risk:** low. The plan explicitly needs no plugin or PostCSS config. Adding either would contradict the out-of-scope list.
</impact>
<impact path="client/frontend/src/about.css" element="whole file">
**What changes:** nothing. No `@import` is added, because it is out of scope and nothing loads it: grep finds no import or link of `about.css`.

**Risk:** none. A local override that links `/src/about.css` would not get the base from it, but such an override would also link `/src/videos.css` (README.md:43), which does.
</impact>
<impact path="client/frontend/src/pages/search/index.ts" element="CSS imports, lines 12-13">
**What changes:** nothing. It keeps `import "../../videos.css"` then `import "../../search.css"`.

**What depends on it:** the CSS link order in dist/search.html, which is search before videos today. The rebuild should keep that relative order (an acceptance requirement). Verify it in the new dist/search.html.

**Risk:** low.
</impact>
<impact path="client/frontend/src/pages/likes/index.ts" element="videos.css import (line 8), .empty (52), ghost-button like-remove (72)">
**What changes:** nothing.

**What depends on it:** the likes page now gets `.empty` as base (text-align, color) plus the residual `padding: 2rem 1rem` in videos.css. The Unlike button gets its ghost-button declarations from the base, and `.like-remove` still wins on `padding` and `font-size`.

**Risk:** low.
</impact>
<impact path="client/frontend/src/components/key-rejected.ts" element="keyRejectedNotice(): 'error key-rejected' and 'ghost-button'">
**What changes:** nothing. `.key-rejected` and `.ghost-button` now come from the base.

**What depends on it:** the feed, search and video pages. In videos.css, `.error` (687) still comes after `.key-rejected`. In video.css only `.similar-grid .error` (0,2,0) exists. Their declarations do not overlap anyway.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/assets/videos-udwJkO0e.css" element="feed CSS bundle (index, videos, likes, search, About)">
**What changes:** it is replaced by a new hashed `videos-*.css`, whose content starts with the minified base and then the reduced videos rules. The old file is deleted.

**What depends on it:**
- The `<link>` in dist index.html:19, videos.html:19, likes.html:17, search.html:19 and dev-pages/about.template.html:8.
- The before/after cascade comparison, which must compare this old minified file against the new one, so that esbuild's rgba→hex and `-webkit-backdrop-filter` rewrites cancel out.

**Risk:** medium. If the `@import` were left uninlined, the bundle would contain `@import` of a non-existent `/assets/base.css`. Check that the new bundle contains `--paper:` and no `@import`.
</impact>
<impact path="client/frontend/dist/assets/video-DLlne6b9.css" element="video page CSS bundle">
**What changes:** replaced by a new hashed `video-*.css` (base plus reduced video rules). The old file is deleted.

**What depends on it:** the dist/video-page.html:17 link.

**Risk:** medium. Same inlining check as the feed bundle. The 720px `.videos-header{padding-top:5rem}` must survive.
</impact>
<impact path="client/frontend/dist/assets/channels-pv_Nqftv.css" element="channels CSS bundle">
**What changes:** replaced by a new hashed `channels-*.css`. The old file is deleted. `.channel-meta` becomes `.channel-domain`, and `button,input,select,textarea{font:inherit}` must remain.

**What depends on it:** the dist/channels.html:15 link.

**Risk:** medium.
</impact>
<impact path="client/frontend/dist/assets/search-C3DxrC0L.css" element="search CSS bundle">
**What changes:** replaced by a new hashed `search-*.css` that now contains the base plus the search rules, minus `.visually-hidden`. It grows by about 2 KB. The old file is deleted.

**What depends on it:** the dist/search.html:18 link.

**Risk:** low-medium. The duplicated base on the search page is accepted.
</impact>
<impact path="client/frontend/dist/assets/video-card-Bbk6pnxz.js" element="shared video-card chunk">
**What changes:** the content changes (lines 26-29 carry the class names), so there is a new hash and the old file is deleted.

**What depends on it:** the static imports in index-BazsEiFh.js, likes-WMFZsH1C.js and search-DE7Xdm7K.js, and the modulepreload or script tags in dist index.html:17, videos.html:17, likes.html:14 and search.html:14.

**Risk:** low-medium. A stale reference in an entry chunk would 404 the whole page script. Committing the full dist diff covers this.
</impact>
<impact path="client/frontend/dist/assets/index-BazsEiFh.js" element="index/videos entry chunk">
**What changes:** its import specifier for the video-card chunk changes, so it gets a new hash. The old file is deleted.

**What depends on it:** dist/index.html:18 and dist/videos.html:18.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/assets/likes-WMFZsH1C.js" element="likes entry chunk">
**What changes:** it imports the video-card chunk, so it gets a new hash. The old file is deleted.

**What depends on it:** dist/likes.html:12.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/assets/search-DE7Xdm7K.js" element="search entry chunk">
**What changes:** it imports the video-card chunk, so it gets a new hash. The old file is deleted.

**What depends on it:** dist/search.html:12.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/assets/channels-J9faLXVD.js" element="channels entry chunk">
**What changes:** line 7 `channel-meta` becomes `channel-domain`, so it gets a new hash. The old file is deleted.

**What depends on it:** dist/channels.html:12.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/assets/video-BOyHIrkb.js" element="video page entry chunk">
**What changes:** expected to be unchanged. Its source and its imports (safe-url, videos, reactions, key-rejected) do not change. If its hash moves anyway, take the rebuilt file as is.

**Risk:** none expected. A changed hash here is a signal to check that nothing in video-page sources was touched.
</impact>
<impact path="client/frontend/dist/index.html" element="script and stylesheet tags (lines 12-19)">
**What changes:** the video-card and index chunk hashes and the videos CSS hash change. Nothing else changes.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/videos.html" element="script and stylesheet tags (lines 12-19)">
**What changes:** the same hash updates as dist/index.html.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/likes.html" element="script, modulepreload and stylesheet tags (12-17)">
**What changes:** the likes entry, video-card and videos CSS hashes change.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/search.html" element="script, modulepreload and stylesheet tags (12-19)">
**What changes:** the search entry, video-card, search CSS and videos CSS hashes change.

**What depends on it:** the relative order, search CSS (18) before videos CSS (19), must be preserved (an acceptance requirement).

**Risk:** low-medium. The ordering comes from Vite internals. The plan does not depend on it for correctness, but the acceptance comparison does.
</impact>
<impact path="client/frontend/dist/video-page.html" element="stylesheet link (line 17)">
**What changes:** only the video CSS hash. The markup keeps `video-title`, `channel-avatar` and `channel-meta`.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/channels.html" element="script and stylesheet tags (12-15)">
**What changes:** the channels JS and CSS hashes.

**Risk:** low.
</impact>
<impact path="client/frontend/dist/dev-pages/about.template.html" element="stylesheet link (line 8)">
**What changes:** the videos CSS hash. It must still be the template build: no `dist/dev-pages/about.html` may appear.

**What depends on it:** nginx `try_files` for /about (DEPLOYMENT.md:467-483).

**Risk:** low.
</impact>
<impact path="tests/active/test_frontend_video_page.py" element="whole test (selected via video.css and video-page group)">
**What changes:** nothing. It bundles with `--loader:.css=empty` (line 202) and reads the `video-title` id (184, 223), so the CSS and the renames cannot affect it. It is selected by tests/config.json:168-172 because video.css changes, and it has to pass.

**Risk:** low.
</impact>
<impact path="tests/active/test_frontend_reactions.py" element="card rendering test (selected via video-card.ts)">
**What changes:** nothing. It bundles video-card.ts with no CSS involved and asserts only the `stat likes active` and `stat dislikes active` regexes (93-94). It is selected through tests/config.json:97-103 and needs the live `engine_client` and `unpublished_client` fixtures.

**Risk:** low.
</impact>
<impact path="tests/config.json" element="test_groups">
**What changes:** no change required. Uncertain point: no test group maps videos.css, channels.css, search.css, `pages/channels/index.ts` or the new base.css, so nothing is selected for them. That is consistent with how CSS has been handled (only video.css is mapped). Adding base.css to a group would be optional and is not asked for.

**Risk:** none.
</impact>
<impact path="DEPLOYMENT.md" element="section 3 (build), section 6 (rsync and nginx About locations)">
**What changes:** nothing. The build command, the output directory, the page list and the About-under-`dev-pages` behaviour are unchanged.

**Risk:** none.
</impact>


## Documentation to update

- [ ] `docs/project/issues/28-tailwind-evaluation.md` - When delivered:
- Set `Status: enhancement, complete`.
- Append a comment under `## Comments` naming what delivered it: plan `docs/project/plans/21-28-tailwind-evaluation.md`, `src/base.css`, and the card/channel renames.
- Move the file to `docs/project/issues/archive/` (issue-tracker.md:21).
- [ ] `docs/project/roadmap.md` - Line 51, `F7-M2 — Unified design system. Related: issue 28-tailwind-evaluation.`: the issue says this line must be edited when this lands (issue line 49). Once issue 28 is archived, the line should say that the shared base stylesheet (`client/frontend/src/base.css`, issue 28) is delivered and that the CSS framework or Tailwind choice is still open under F6-M2/F7-M2. The issue's "Not delegated to this issue" wording is ambiguous about whose job the edit is. Flagging it rather than omitting it.
- [ ] `client/frontend/README.md` - Add a short note, either a "Styles" section or a bullet near "Build":
- `src/base.css` holds the colour tokens and the shared header, nav, button and summary rules.
- Each page sheet (`videos.css`, `video.css`, `channels.css`, `search.css`) starts with `@import "./base.css";`, and a new page sheet must do the same.
- Page sheets keep only their own declarations, as overrides of the base.
- The shared video card uses `card-title`, `card-channel` and `card-avatar`, which are distinct from the video page's `video-title`, `channel-meta` and `channel-avatar`.

Line 43 (an override links `/src/videos.css`) stays correct, because that link now also brings the base.
- [ ] `docs/project/plans/21-28-tailwind-evaluation.md` - This is the build's working plan file. It receives the impact inventory and the per-phase checkpoint outcomes. Its current-state notes (lines 39-41, 125-129) remain accurate as pre-change line references.
- [ ] `docs/project/issues/plan.md` - Uncertain, optional. Row P8 (line 45, "28 should not be built (see triage)") and line 127 ("28 (Tailwind): wontfix…") are now stale, because 28 was rescoped and is being built. Update them if this sequencing doc is kept current, or leave them as a historical snapshot.

## Implementation plan

## Draft implementation: shared `base.css` and the card/channel class renames

### What has to be tested (this decides the draft's shape)

1. **Card markup.** `renderVideoCard()` output contains `class="card-title"`, `class="card-channel"` and `class="card-avatar"`, and none of `video-title`, `channel-meta` or `channel-avatar`. The existing `test_frontend_reactions.py` still has to pass, and it only matches `stat likes|dislikes active`.
2. **Channels row.** The output contains `class="channel-domain"` and no `channel-meta`.
3. **Video page untouched.** `video-page.html`, `video.css` (156/168/181/203) and `pages/video-page/index.ts` still carry `video-title`, `channel-avatar` and `channel-meta`, ids included. `test_frontend_video_page.py` is selected through video.css and has to pass.
4. **Built bundles.** Each new `dist/assets/{videos,video,channels,search}-*.css` contains `--paper:` and no `@import`. `dist/search.html` still links search CSS before videos CSS. No `dist/dev-pages/about.html` exists.
5. **Per-page final declarations.** Compare minified old dist against minified new dist for index, videos, likes, search, video page, channels and About. The only existing-selector change allowed is `.visually-hidden`. New selectors are allowed only as listed in the acceptance criteria.
6. **Source-level duplicates.** No top-level rule in a page sheet repeats a base selector, apart from the four residual overrides.

No new test file is drafted. Items 1–3 are already exercised by the selected tests or are greps. Items 4–6 are checks on build output for the verification step, because there is no CSS test harness. Adding one would be speculative (ladder rung 1).

### Module map

| File | Change |
|---|---|
| `client/frontend/src/base.css` | **new**: header comment and the shared rules, in the order below |
| `client/frontend/src/videos.css` | line 1 `@import`; base rules deleted; 4 residuals in place; 4 card selectors renamed |
| `client/frontend/src/video.css` | line 1 `@import`; base rules deleted; 2 residuals in place; the 720px block keeps only `.videos-header` |
| `client/frontend/src/channels.css` | line 1 `@import`; base rules deleted; 3 residuals in place; `.channel-meta` → `.channel-domain` |
| `client/frontend/src/search.css` | `@import` after the header comment; `.visually-hidden` deleted |
| `client/frontend/src/components/video-card.ts` | lines 371, 373, 374: class values only |
| `client/frontend/src/pages/channels/index.ts` | line 279: class value only |
| `client/frontend/dist/**` | regenerated with `npm run build`, with no `dev-pages/about.html` present |

No HTML, no `vite.config.ts`, no `about.css`, no PostCSS config. Vite 5.4's built-in `@import` inlining is the mechanism (ladder rung 4: a native platform feature).

### `client/frontend/src/base.css` (full content)

Every declaration is copied byte-for-byte from `videos.css` (or from `search.css` for `.visually-hidden`), so minified output is identical. Order matters in three places: the media `.header-nav` comes after the plain `.header-nav`, `.nav-link.active,…` after `.nav-link`, and `.ghost-button:hover` after `.ghost-button`.

```css
/**
 * Rules shared by every page sheet. Each page sheet pulls this in with `@import "./base.css";`
 * so the base is inlined ahead of its own rules; a page sheet only adds or overrides.
 */

:root {
  --paper: #f6f2ea;
  --paper-strong: #f0e9dc;
  --ink: #1f1b16;
  --muted: rgba(31, 27, 22, 0.65);
  --accent: #b45737;
  --accent-strong: #8a3b24;
  --line: rgba(31, 27, 22, 0.12);
  --shadow: rgba(27, 20, 14, 0.12);
  font-family: "Roboto", "Noto Sans", Arial, sans-serif;
  color: var(--ink);
  background:
    radial-gradient(circle at 10% 10%, rgba(180, 87, 55, 0.16), transparent 45%),
    radial-gradient(circle at 90% 0%, rgba(31, 27, 22, 0.1), transparent 40%),
    linear-gradient(140deg, var(--paper), var(--paper-strong));
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
}

/* Pinned to the viewport so the page links stay reachable at any scroll depth. */
.header-nav {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  position: fixed;
  top: 1rem;
  right: 3rem;
  z-index: 20;
  padding: 0.35rem;
  border-radius: 999px;
  background: rgba(246, 242, 234, 0.92);
  backdrop-filter: blur(6px);
  box-shadow: 0 8px 24px var(--shadow);
}

@media (max-width: 720px) {
  .header-nav {
    left: 1rem;
    right: 1rem;
    justify-content: center;
    border-radius: 18px;
  }
}

.nav-link {
  text-decoration: none;
  padding: 0.45rem 1rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--ink);
  font-size: 0.9rem;
  transition: border-color 0.2s ease, transform 0.2s ease;
}

.nav-link.active,
.nav-link:hover {
  border-color: var(--accent);
  transform: translateY(-1px);
}

.eyebrow {
  margin: 0 0 0.4rem;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  font-size: 0.7rem;
  color: var(--muted);
}

.videos-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1.5rem;
  padding: 2rem 3rem 1.5rem;
}

.videos-header h1 {
  margin: 0 0 0.35rem;
  font-size: clamp(1.8rem, 2.8vw + 1rem, 3rem);
}

.subtitle {
  margin: 0;
  color: var(--muted);
}

.summary {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
  font-size: 0.95rem;
}

.summary-meta {
  color: var(--muted);
  font-size: 0.85rem;
}

.key-rejected {
  display: grid;
  gap: 0.6rem;
  justify-items: start;
}

.ghost-button {
  border: 1px dashed var(--line);
  background: transparent;
  padding: 0.6rem 1rem;
  border-radius: 12px;
  cursor: pointer;
  font-size: 0.9rem;
  color: var(--accent-strong);
}

.ghost-button:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.ghost-link {
  color: var(--accent-strong);
  text-decoration: none;
  font-size: 0.9rem;
}

.ghost-link:hover {
  text-decoration: underline;
}

.empty {
  text-align: center;
  color: var(--muted);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

### `client/frontend/src/videos.css`

- **New line 1:** `@import "./base.css";`, followed by a blank line, then `.videos-app` (it was at 27).
- **Deleted:**
  - lines 1-25 (`:root`, `*`, `body`), 33-40 (`.videos-header`), 42-48 (`.eyebrow`) and 50-53 (`.videos-header h1`)
  - 61-84: the header-nav comment, the rule, and the whole 720px header-nav media block, which holds nothing else
  - 99-103 (`.nav-link.active,…`), 112-118 (`.summary`) and 127-130 (`.summary-meta`)
  - 147-150 (`.ghost-button:hover`), 165-173 (`.ghost-link` and `:hover`), 294-298 (`.key-rejected`) and 678-685 (`.visually-hidden`)
- **Residual overrides, each left at its current position:**

```css
.subtitle {
  max-width: 38ch;
}
```
```css
.nav-link {
  position: relative;
  display: inline-flex;
  align-items: center;
}
```
```css
.ghost-button {
  transition: border-color 0.2s ease, color 0.2s ease;
}
```
```css
.empty {
  padding: 2rem 1rem;
}
```

- **Renamed selectors** (declarations unchanged): `.video-title` → `.card-title` (485), `.channel-meta` → `.card-channel` (520), `.channel-avatar` → `.card-avatar` (526), `.channel-avatar img` → `.card-avatar img` (542).
- **Unchanged:** the 1100/720px `.cards-grid` blocks, the 900px block 695-701, and the 720px block 703-712 (`.videos-header { padding-top: 5rem; /* … */ }`, `.summary`). These are page-specific responsive rules (item 1). I read the duplicate criterion as covering top-level rules only.

### `client/frontend/src/video.css`

- **New line 1:** `@import "./base.css";`, followed by a blank line, then `.video-page`.
- **Deleted:**
  - 1-25, 33-40 (`.videos-header`), 42-48 (`.eyebrow`) and 50-53 (`.videos-header h1`)
  - 70-84 (the header-nav comment and rule)
  - the `.header-nav` rule inside the 86-97 media block
  - 99-113 (`.nav-link` entire, plus `.nav-link.active,…`)
  - 292-296 (`.key-rejected`), 360-363 (`.ghost-button:hover`) and 424-432 (`.ghost-link` and `:hover`)
- **Media block after the edit**, at the same position:

```css
@media (max-width: 720px) {
  .videos-header {
    padding-top: 5rem;
  }
}
```

- **Residual overrides, in place:**

```css
.subtitle {
  max-width: 48ch;
}
```
```css
.ghost-button {
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease;
}
```

- **Untouched:** `.subtitle a`/`:hover`, `.video-title`, `.channel-avatar`, `.channel-avatar img`, `.channel-meta`, `.ghost-button.active` (still after `:hover`, so it still wins on `color`), `textarea` and the 900px block.

### `client/frontend/src/channels.css`

- **New line 1:** `@import "./base.css";`, followed by a blank line, then the kept `button, input, select, textarea { font: inherit; }`.
- **Deleted:**
  - 1-20 (`:root`, `*`) and 29-32 (`body`)
  - 49-55 (`.eyebrow`), 68-91 (the header-nav comment, rule and whole 720px header-nav block) and 93-107 (`.nav-link` entire, plus `.nav-link.active,…`)
  - 168-171 (`.ghost-button:hover`), 173-179 (`.summary`) and 211-214 (`.summary-meta`)
- **Residual overrides, in place:**

```css
.subtitle {
  max-width: 38ch;
}
```
```css
.ghost-button {
  align-self: end;
  transition: border-color 0.2s ease, color 0.2s ease;
}
```
```css
.empty {
  padding: 2.5rem 1rem;
}
```

- **Renamed:** `.channel-meta` → `.channel-domain` (327). Declarations are unchanged.
- **Unchanged:** `.channels-header` and its `h1`, the 900px block, and the 720px block (`.channels-header`, `.summary`, `.pager`).

### `client/frontend/src/search.css`

Insert after the header comment (lines 1-4). The comment gains one clause:

```css
/**
 * Controls specific to the search page. The results grid and the cards themselves reuse
 * `videos.css`, because they are the same component the feed renders; the shared base comes from `base.css`.
 */

@import "./base.css";
```

Delete `.visually-hidden` (69-79) and the blank line before it.

### `client/frontend/src/components/video-card.ts` (lines 371-374)

```ts
          <h3 class="card-title">${escapeHtml(title)}</h3>
          <div class="video-footer">
            <div class="card-channel">
              <div class="card-avatar" aria-hidden="true">${avatarMarkup}</div>
```

### `client/frontend/src/pages/channels/index.ts` (line 279)

```ts
              <div class="channel-domain">${escapeHtml(row.instance_domain ?? "")} ${errorTag}</div>
```

### Build (item 6)

1. Confirm `client/frontend/dev-pages/about.html` is absent.
2. Run `cd client/frontend && npm run build`.
3. Commit the whole `dist/` diff: new hashed CSS for videos, video, channels and search; new hashed JS for video-card, index, likes, search and channels; the updated HTML links; the deleted old hashes.
4. `video-BOyHIrkb.js` is expected to keep its hash. If it moves, check that no video-page source was touched.
5. Check that each new CSS bundle starts `:root{--paper:` and contains no `@import`.
6. Check that `dist/search.html` links `search-*.css` before `videos-*.css`.

### Cascade decisions, re-checked against the code

- **Base before page, always.** The inlined `@import` sits at the head of each bundle, so a residual with the same selector (same specificity) wins on its own declarations. Residuals stay where they are in the sheet, so their position relative to other page rules does not change.
- **Final declaration sets are unchanged**, as base ∪ residual:

| Selector | Page | Base + residual = original? |
|---|---|---|
| `.nav-link` | videos | base 7 declarations + residual 3 → same as original 86-97 |
| `.nav-link` | channels, video | base only → same as their originals |
| `.ghost-button` | videos, channels, video | base 7 declarations + each page's `transition` (+ `align-self` on channels) → same |
| `.subtitle` | all three | base 2 declarations + that page's `max-width` → same |
| `.empty` | videos, channels | base 2 declarations + that page's `padding` → same |

- **Multi-class elements.** None of them change: `nav-link nav-button`, `ghost-button like-remove`, `video-debug empty`, `error key-rejected`, `ghost-button icon-button|comments-more|comment-replies-*`, `.ghost-button.active`, `.feed-modes .ghost-button[aria-pressed]`, and `<td class="empty">` under `.channels-table td`. In every case the competing page rule was already after the moved rule, or has higher specificity.
- **Search page.** Load order becomes base, search, base, videos. `search.css` no longer declares any base selector, so the second base copy overrides nothing. `.visually-hidden` there ends with the complete form, with only the `clip` spelling changed, which is the allowed exception. On index, videos, likes and About, `.visually-hidden` gains `padding: 0`, `margin: -1px` and `border: 0`, plus the `clip` respelling, also the allowed exception.

### Passes against plan and requirements

- **Pass 1.**
  - Items 1–6: each maps to a section above.
  - Item 1's "every byte-identical rule" includes the four companion rules (`.nav-link.active,…`, `.ghost-button:hover`, `.ghost-link:hover`, `.videos-header h1`), as the plan says.
  - Item 2's strict intersection gives the residuals listed.
  - Item 3: one complete `.visually-hidden`.
  - Item 4: renames in markup and CSS together; video page untouched.
  - Item 5: `@import` in every page sheet that something loads, so the About template and override links get the base with no HTML change.
  - Item 6: build steps.
  - Load-order requirement: base first; search before videos is kept by the unchanged `pages/search/index.ts` and checked in dist.
- **Out of scope respected:** no PostCSS or plugin, `about.css` untouched, no value unification, no reordering beyond deletions.
- **One open point** carried from the inventory: the 720/900px media `.videos-header` and `.summary` rules stay in the page sheets. That follows item 1's explicit instruction, so the duplicate criterion is read as top-level only.
- Converged on the first pass.

### Docs (settled list, done when it lands)

- **`client/frontend/README.md`:** a short "Styles" note:
  - `src/base.css` holds the tokens and the shared header, nav, button and summary rules.
  - Every page sheet starts with `@import "./base.css";`, and new sheets must too.
  - Page sheets hold only their own rules or overrides.
  - Card classes are `card-title`, `card-channel` and `card-avatar`, distinct from the video page's names.
- **Issue 28:** `Status: enhancement, complete`, a closing comment, and a move to `docs/project/issues/archive/`.
- **`roadmap.md` line 51:** say the base stylesheet is delivered and the framework choice is still open under F6-M2/F7-M2. This is flagged, since the issue says it is not delegated to the build.
- **Plan file:** receives the checkpoints.
- **`docs/project/issues/plan.md` P8 and line 127:** optional staleness fix.

### Accepted limitations (from the plan)

- About 2 KB of base CSS is duplicated on the search page.
- The base is inlined per bundle rather than cached once.
- The residual overrides are kept even where two of the three pages agree.

The upgrade path for all three is a single Vite-managed base chunk under F6-M2/F7-M2.

### Phases

#### Phase 1 - Card and channel-row class renames [code]

**Files touched.** client/frontend/src/components/video-card.ts (EDITED), client/frontend/src/pages/channels/index.ts (EDITED), client/frontend/src/videos.css (EDITED), client/frontend/src/channels.css (EDITED), tests/active/test_frontend_class_renames.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the exported `renderVideoCard` in `client/frontend/src/components/video-card.ts`, plus the channels page module `client/frontend/src/pages/channels/index.ts` as the browser runs it. Both run in node at rung 1. For the card, follow `tests/active/test_frontend_reactions.py` `_bundle`: bundle with esbuild (`--bundle --format=esm --platform=node`) and call `renderVideoCard` on one fixture row, with no live Client. For the channels row, follow `tests/active/test_frontend_video_page.py`: bundle the page module with `--loader:.css=empty`, stub `document` with recording elements for the ids the module requires (`channels-body`, `summary-counts`, `summary-meta`, `page-status`) and `window.location`, stub `fetch` to answer the channels request with a one-row payload, settle, then read `#channels-body` innerHTML. Clause 1 assertions: the card HTML contains each of `class="card-title"`, `class="card-channel"` and `class="card-avatar"`, three separate assertions, and contains none of `video-title`, `channel-meta` and `channel-avatar`, also three. The channels row contains `class="channel-domain"` and does not contain `channel-meta`. Control: the row's channel name and instance domain text are present, so an empty table cannot pass. Clause 2 assertions: parse `videos.css` and `channels.css` into (selector → declarations) with a small stdlib brace tokenizer. Assert that `.card-title`, `.card-channel`, `.card-avatar` and `.card-avatar img` in videos.css, and `.channel-domain` in channels.css, each have the declarations that `.video-title`, `.channel-meta`, `.channel-avatar`, `.channel-avatar img` and channels' `.channel-meta` had in the pre-change sheets. Read those with `git show <pre-change sha>:client/frontend/src/...`, with the sha pinned in the test. Then assert that none of the old selectors remains in videos.css or channels.css. The video page staying untouched is proved by the existing `test_frontend_video_page.py`, selected through video.css, staying green; this phase adds no assertion for it.

**Intent.** The feed card rendered by `renderVideoCard` and the channels page's table row carry their own class names (`card-title`, `card-channel`, `card-avatar`; `channel-domain`) in place of the video page's names, and `videos.css`/`channels.css` style those new names with the rules that styled the old ones.

- C1 - The markup produced by `renderVideoCard` and by the channels page's table row carries the new class names and none of the old ones.
- C2 - Each new class is styled in its page sheet with the same declarations its old name had before the change.

**Outcome.** ### `client/frontend/src/components/video-card.ts`
In `renderVideoCard`'s markup, three class names changed. The title `<h3>` now has `class="card-title"` instead of `video-title`, the channel wrapper has `class="card-channel"` instead of `channel-meta`, and the avatar element has `class="card-avatar"` instead of `channel-avatar`. The avatar `<img>` or initials `<span>` still sits inside the renamed avatar element. Nothing else in the module changed.

### `client/frontend/src/pages/channels/index.ts`
In `renderTable`, the element under the channel name that shows the instance domain and the error pill now has `class="channel-domain"` instead of `channel-meta`.

### `client/frontend/src/videos.css`
Four selectors were renamed and their declarations left byte-for-byte as they were: `.video-title` → `.card-title`, `.channel-meta` → `.card-channel`, `.channel-avatar` → `.card-avatar`, and `.channel-avatar img` → `.card-avatar img`. No selector in the sheet names the old classes any more.

### `client/frontend/src/channels.css`
`.channel-meta` was renamed to `.channel-domain` with its declarations unchanged (`font-size: 0.85rem; color: var(--muted)`).

### Not changed
The video page keeps its own names. `video-page.html`, `pages/video-page/index.ts` (which looks up the `video-title` and `channel-avatar` ids) and `video.css` (`.video-title`, `.channel-avatar`, `.channel-meta`) are untouched. I searched `client/frontend/src` for the old names afterwards: every remaining hit belongs to the video page. The phase also lists the new durable test `tests/active/test_frontend_class_renames.py` and `tests/config.json`. I touched neither, because this step asked only for production code. Moving the checkpoint into those files is left to the workflow.

#### Phase 2 - Shared base.css inlined into every page sheet [code]

**Files touched.** client/frontend/src/base.css (NEW), client/frontend/src/videos.css (EDITED), client/frontend/src/video.css (EDITED), client/frontend/src/channels.css (EDITED), client/frontend/src/search.css (EDITED), tests/active/test_frontend_base_css.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the Vite build of the page sheets (rung 2 and rung 3). There is no CSS test harness in the suite. The nearest precedent is the subprocess pattern of the existing frontend tests, which run tools from `client/frontend/node_modules/.bin`. The test runs `node_modules/.bin/vite build --outDir <tmp>` in `client/frontend` as a subprocess and asserts exit 0. It refuses to run if `dev-pages/about.html` exists. Clause 1 assertions: for each built `assets/{videos,video,channels,search}-*.css`, parametrized over the bundles found in the tmp build's HTML links rather than a hard-coded list, the bundle's leading rule sequence (selector and declarations, media blocks included) equals base.css's own rule sequence, also taken from the build. The first rule is `:root` containing `--paper`. The bundle contains no `@import`. Control: each bundle has rules after the base prefix, so a bundle that is only the base fails. Clause 2 assertions (rung 4): parse `base.css` and each page sheet into top-level (selector, property) pairs with the stdlib tokenizer, then intersect each page sheet's pairs with the base's. The intersection is empty. The only base selectors that still appear at top level in a page sheet are `.nav-link`, `.ghost-button`, `.subtitle` and `.empty`, checked against the exact per-sheet residual set in the draft (videos: all four; video: `.subtitle`, `.ghost-button`; channels: `.subtitle`, `.ghost-button`, `.empty`; search: none). Media-block page rules are excluded, as the draft decides.

**Intent.** The shared rules live once, in `client/frontend/src/base.css`, and the built CSS of every page sheet (videos, video, channels, search) opens with them through a leading `@import "./base.css";`.

- C1 - Each built page CSS bundle begins with base.css's rules and contains no `@import`.
- C2 - No top-level rule in a page sheet repeats a declaration that base.css makes; only the residual override selectors reappear, and only with declarations the base lacks.

**Outcome.** ### `client/frontend/src/base.css` (new)
This is the shared base stylesheet, laid out as in the draft. It opens with a block comment in the style of `search.css`, then has these rules in order:
- `:root` (colour tokens, font-family, color, background), `*`, `body`.
- `.header-nav` with its "Pinned to the viewport" comment, then its `@media (max-width: 720px)` override.
- `.nav-link` in the channels/video form, then `.nav-link.active, .nav-link:hover`.
- `.eyebrow`, `.videos-header`, `.videos-header h1`, and `.subtitle` with `margin` and `color` only.
- `.summary`, `.summary-meta`, `.key-rejected`.
- `.ghost-button` with border, background, padding, border-radius, cursor, font-size and color, but no `transition`; then `.ghost-button:hover`.
- `.ghost-link`, `.ghost-link:hover`.
- `.empty` with `text-align` and `color`.
- `.visually-hidden` in the complete nine-declaration form, with `clip: rect(0, 0, 0, 0)`.

Every declaration is copied byte-for-byte from the page sheets: `videos.css`, or `search.css` for `.visually-hidden`.

### `client/frontend/src/videos.css`
- Line 1 is now `@import "./base.css";`.
- **Removed:** `:root`, `*`, `body`, `.videos-header`, `.eyebrow`, `.videos-header h1`, the header-nav comment and rule, the whole 720px header-nav media block, `.nav-link.active, .nav-link:hover`, `.summary`, `.summary-meta`, `.ghost-button:hover`, `.ghost-link`, `.ghost-link:hover`, `.key-rejected` and `.visually-hidden`.
- **Left in place as overrides holding only what the base lacks:**
  - `.subtitle { max-width: 38ch }`
  - `.nav-link { position: relative; display: inline-flex; align-items: center }`
  - `.ghost-button { transition: border-color 0.2s ease, color 0.2s ease }`
  - `.empty { padding: 2rem 1rem }`
- **Untouched:** the phase-1 `card-*` rules, the 900px block, and the 720px block with `.videos-header` padding-top and `.summary`.

### `client/frontend/src/video.css`
- Line 1 is now `@import "./base.css";`.
- **Removed:** `:root`, `*`, `body`, `.videos-header`, `.eyebrow`, `.videos-header h1`, the header-nav comment and rule, the whole `.nav-link` rule (it matched the base), `.nav-link.active, .nav-link:hover`, `.key-rejected`, `.ghost-button:hover`, `.ghost-link` and `.ghost-link:hover`.
- **720px media block:** it lost only its `.header-nav` rule. It stays where it was, holding `.videos-header { padding-top: 5rem }`.
- **Overrides left in place:**
  - `.subtitle { max-width: 48ch }`
  - `.ghost-button { transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease }`
- **Untouched:** `.ghost-button.active` (still after the base `:hover`), and the video page's own `.video-title`, `.channel-avatar` and `.channel-meta`.

### `client/frontend/src/channels.css`
- Line 1 is now `@import "./base.css";`, followed by the channels-only `button, input, select, textarea { font: inherit; }`.
- **Removed:** `:root`, `*`, `body`, `.eyebrow`, the header-nav comment and rule, the whole 720px header-nav block, `.nav-link` (it matched the base), `.nav-link.active, .nav-link:hover`, `.ghost-button:hover`, `.summary` and `.summary-meta`.
- **Overrides left in place:**
  - `.subtitle { max-width: 38ch }`
  - `.ghost-button { align-self: end; transition: border-color 0.2s ease, color 0.2s ease }`
  - `.empty { padding: 2.5rem 1rem }`
- **Untouched:** `.channel-domain`, `.channels-header` and its `h1`, the 900px block, and the 720px block (`.channels-header`, `.summary`, `.pager`).

### `client/frontend/src/search.css`
- The header comment gained the clause "the shared base comes from `base.css`".
- `@import "./base.css";` now follows the header comment.
- `.visually-hidden` is removed; the base now carries it.

### Not changed
I did not touch `tests/active/test_frontend_base_css.py` or `tests/config.json`, although this phase's file list names them. This step asked only for production code, and phase 1 did the same; moving the checkpoint into those files is left to the workflow.

### Verified by probe, before handing in
The probe was `tests/tmp/test_probe_28_phase2_impl.py`, now emptied to a "spent probe, safe to delete" docstring, since I have no tool to delete a file. It used the checkpoint's own helpers.
- **Vite build:** `vite build` to a temp dir exited 0.
- **Linked bundles:** the built HTML links exactly the four bundles: channels, search, video and videos.
- **Base built alone:** 20 rules, opening on `:root`.
- **Bundle contents:** all four bundles have no `@import`, open with those 20 rules with no mismatch, and continue with their own page rules: `button, input, select, textarea`, `.search-controls`, `.video-page` and `.videos-app` respectively. So the minifier did not merge anything across the base/page boundary.
- **C2:** only `.empty`, `.ghost-button` and `.subtitle` are declared in more than one sheet, and in each case the declaring sheets share no declaration. No sheet repeats a property the base sets on the same selector. The overrides left in each sheet are exactly the residual set the draft lists.

#### Phase 3 - Regenerated dist with an unchanged cascade [code]

**Files touched.** client/frontend/dist/** (EDITED, regenerated by `npm run build`), tests/active/test_frontend_dist_cascade.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the committed `client/frontend/dist/` as served (rung 3), compared with the pre-change dist read through `git show <pre-change sha>:client/frontend/dist/...`, with the sha pinned in the test for the life of the build. Controls: a fresh `vite build --outDir <tmp>`, run with no `dev-pages/about.html`, produces the same set of asset file names as the committed dist, which proves dist is current. `dist/dev-pages/about.html` does not exist. Clause 1 assertions: for each HTML entry, parametrized over the entries found in both dists (index, videos, likes, search, video page, channels, About; the test asserts these seven are present), collect the `<link rel="stylesheet">` bundles in document order. Resolve each (media, selector) to its final property→value map, last occurrence winning. Assert it equals the pre-change map for every selector, with two exceptions. First, the phase-1 renames are compared under their old names. Second, on every page that has `.visually-hidden`, the new map must hold exactly the nine declarations of the complete form (position, width, height, padding, margin, overflow, clip, white-space, border), asserted member by member, instead of the old map. Both sides are minified by the same esbuild, so minifier rewrites cancel out. Clause 2 assertion: in the committed `dist/search.html`, the index of the `search-*.css` link is lower than the index of the `videos-*.css` link, and both are present. The known limit is that the comparison works per selector. A moved rule that now competes on the same element with a different selector of equal specificity is invisible to it, so that check stays with the verification step, as the plan's gotcha says.

**Intent.** The committed `client/frontend/dist/` is a build of the new tree, and every page in it resolves its styles to the same declarations as the pre-change dist, apart from the completed `.visually-hidden`.

- C1 - On every page, each selector in the committed dist resolves to the declarations it resolved to in the pre-change dist, except `.visually-hidden`, which holds the complete form.
- C2 - The committed `dist/search.html` links the search CSS before the videos CSS.

**Outcome.** ### client/frontend/dist/**
Not regenerated yet. I couldn't run the build myself (details under awaiting_operator), so the operator runs `npm run build` before the checkpoint does. I didn't hand-write any dist files: the asset names carry content hashes, and the stale hashed assets have to be deleted, which only the build's own empty-out step can do.

I did check that the source is already right, with a probe under `tests/tmp/`. It built the current tree into a temp directory with `vite build --outDir <tmp>`, then ran the checkpoint's own test functions against that output by pointing its `DIST` at the temp directory:
- **Build:** exit status 0.
- **Pages:** exactly the seven pages, with the About page built from `about.template.html`.
- **C2:** `search.html` links `search-*.css` before `videos-*.css`.
- **C1:** the cascade check passes on all seven pages, including the complete `.visually-hidden`.

So the regenerated dist needs no production source change.

The fresh build emits 16 assets. The 4 stylesheets and 7 of the 12 scripts get new hashes: `channels-CYXphrhS.css`, `search-DRNaw0N3.css`, `videos-BQf5BBvB.css`, `video-B-QbQv--.css`, `channels-pIfWw09I.js`, `index-BonFqyib.js`, `likes-C8fnujRE.js`, `search-BIVLGu4U.js`, `video-CwHmsZfK.js`, `video-card-CEp_y-w5.js`. The other 5 scripts keep their names: `cache`, `safe-url`, `user-profile`, `videos`, `key-rejected` and `reactions`. These replace the stale `*-J9faLXVD`, `*-pv_Nqftv`, `*-BazsEiFh`, `*-WMFZsH1C`, `*-C3DxrC0L`, `*-DE7Xdm7K`, `*-BOyHIrkb`, `*-DLlne6b9`, `*-Bbk6pnxz` and `*-udwJkO0e` files.

### tests/active/test_frontend_dist_cascade.py, tests/config.json
Not touched. These two promote the checkpoint into the durable suite and add its test group, which is not production code for this phase.

**Beyond the files named.** tests/tmp/probe_28_fresh_build.py — a throwaway probe that builds into a temp directory and runs the checkpoint's checks there. My tools can't delete files, so it is still in the tree; removing it is step 3 under awaiting_operator.


