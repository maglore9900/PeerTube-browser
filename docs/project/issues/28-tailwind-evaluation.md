# Shared base stylesheet and card class renames (was: Evaluate Tailwind CSS)

Status: enhancement, ready-for-agent
Origin: task 8, [M2][F1]

## Problem

Styles are fragmented and hard to maintain.

## Proposed solution

Evaluate Tailwind and adopt it if needed, starting with new blocks and gradually replacing repeated styles.

## Related

- Overlaps roadmap features F5-M2 to F7-M2 (frontend refactor, component architecture, design system). Probably belongs inside one of them rather than standing alone.

## Comments

### Triage (2026-10-02): rescoped from a Tailwind evaluation to the duplication behind it

Tailwind is not part of this issue anymore. Choosing a CSS framework depends on the framework and component decisions of F6-M2 and F7-M2, which have not been made. It is deferred, not rejected, so there is no `docs/project/rejected/` entry. The maintainer rescoped the issue to the concrete problem the triage found.

Findings at triage:

- Neither Tailwind nor PostCSS is in the frontend. The build is vite and TypeScript only.
- The frontend has five page stylesheets: `about.css`, `channels.css`, `search.css`, `video.css` and `videos.css`, about 2,080 lines in total. There is no shared base, and each page loads its own sheet.
- Ten rules are byte-identical in every sheet that declares them. Five are in channels, video and videos: `:root` (colour tokens), `*`, `body`, `.header-nav` and `.eyebrow`. Five are in two sheets each: `.videos-header`, `.summary`, `.summary-meta`, `.key-rejected` and `.ghost-link`.
- Eight rules differ between sheets, and they fall into three kinds:
  - **One name used for different components:**
    - `.video-title`: the page heading on the video page, a 2-line-clamped card title on the feed pages.
    - `.channel-avatar`: 46px with an image on the video page, 34px with initials on cards.
    - `.channel-meta`: a name/subscriber column on the video page, an avatar/name row on cards, and the instance domain text on a channels row.
    
    They do not collide today, because the video page does not render the shared video card. They will collide once a card appears on another page; F13-M2 already plans cards on the channels page. The maintainer decided to rename them.
  - **Near-identical rules where one page adds a little:**
    - `.nav-link`: videos adds `position`, `display` and `align-items`.
    - `.ghost-button`: channels adds `align-self: end`, and video also transitions `background`.
    - `.subtitle`: 38ch, or 48ch on the video page.
    - `.empty`: 2rem padding, or 2.5rem on channels.
    
    The maintainer decided on base plus overrides: the shared part goes in the base, and each page keeps only its own difference.
  - **Two versions of `.visually-hidden`:** the complete one in `search.css` and a shorter one in `videos.css`. The maintainer decided the complete one goes in the base.
- Load-order facts the change must respect:
  - The search page loads `search.css` before `videos.css`, so for any selector both sheets declare, the `videos.css` rule wins there.
  - The About page has no script and links the feed stylesheet directly. A local `about.html` override may do the same.
  - The committed build output (`dist/`) carries one CSS bundle per page.

Not delegated to this issue: the roadmap line F7-M2 still names issue 28 as its Tailwind link. Edit that line when this lands.

## Agent Brief

**Category:** enhancement
**Summary:** Move the frontend's copied page styles into one shared base stylesheet and rename the shared video card's colliding classes, with no visible change on any page.

**Current behavior:**
Every page of the frontend gets its styles from its own page stylesheet: the feed sheet (home, videos, likes and search pages, and the About page), the video page sheet, the channels page sheet, and the search sheet, which the search page loads alongside the feed sheet. The feed, video and channels sheets each carry their own copy of the colour tokens (`:root`), the global box-sizing and `body` rules, the fixed header navigation (`.header-nav`, `.nav-link`), `.eyebrow`, `.subtitle` and `.ghost-button`. Several smaller rules are copied between two sheets. Some copies are byte-identical. Others differ by one or two declarations.

The shared video card component, which renders feed, search and likes cards, uses the class names `video-title`, `channel-meta` and `channel-avatar`. The video page uses the same three names for different elements: its page heading, its channel name and subscriber column, and its channel avatar. The channels page uses `channel-meta` for the instance domain text in a channel row. Each pair is styled differently, and the rules only avoid colliding because no page loads two of these sheets.

**Desired behavior:**

1. **One shared base stylesheet** holds every rule that is now copied byte-identically between page stylesheets: the colour tokens, `*`, `body`, `.header-nav` (including its narrow-screen media rule where that is identical), `.eyebrow`, `.videos-header`, `.summary`, `.summary-meta`, `.key-rejected` and `.ghost-link`. Every copy is removed from the page sheets.
2. **Near-identical rules use base plus override.** For `.nav-link`, `.ghost-button`, `.subtitle` and `.empty`, the declarations every declaring sheet shares go in the base. Each page sheet keeps a rule with only the declarations where it differs. The page's own values must still win on that page, so the base has to load before the page sheet.
3. **`.visually-hidden`** is defined once, in the base, using the complete form: `position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0`. No page sheet defines it.
4. **The shared video card's classes are renamed:**
   - `video-title` → `card-title`
   - `channel-meta` → `card-channel`
   - `channel-avatar` → `card-avatar`, including its descendant `img` rule
   
   Rename the markup the component emits and the feed sheet's rules together. The channels page's `channel-meta` becomes `channel-domain` in its row markup and its sheet. The video page keeps `video-title`, `channel-meta` and `channel-avatar` unchanged, as classes and as element ids.
5. **The base reaches every page that loads a page stylesheet,** including a page with no script that links a page stylesheet directly. The About page and a local About override are the cases that exist. Whatever loads a page sheet loads the base before it, without any change to the page's HTML.
6. **The committed build output is regenerated,** so the served pages use the new stylesheets.

**Key interfaces:**
- The shared video card component's rendered markup: the class attributes on the card title, the channel row and the avatar change as in item 4. Its function signatures and everything else it emits stay the same.
- The channels page's row rendering: only the class on the instance domain element changes.
- Stylesheet load order per page: the base first, then the page sheets in their current relative order. The search page keeps the search sheet before the feed sheet.

**Acceptance criteria:**
- [ ] No class rule that the base stylesheet holds is also declared in any page stylesheet, except the override rules from item 2, which carry only their differing declarations.
- [ ] For every built page (index, videos, likes, search, video page, channels, and About from the template), apply that page's stylesheets in load order, last rule wins, and list the declarations that end up on each selector. With the renamed selectors mapped back to their old names, this list is identical before and after the change. One exception is allowed: `.visually-hidden` on the feed, likes and search pages, which gains `padding: 0`, `margin: -1px` and `border: 0`.
- [ ] The shared video card's output contains `card-title`, `card-channel` and `card-avatar`, and none of `video-title`, `channel-meta` or `channel-avatar`.
- [ ] The channels page row contains `channel-domain` and not `channel-meta`.
- [ ] The video page's HTML and script still use `video-title`, `channel-meta` and `channel-avatar`, and its element ids are unchanged.
- [ ] The About template, built with no override present, loads the base rules: its colour tokens and body styles are as they were.
- [ ] The committed build output is rebuilt from the changed sources, and every existing frontend test passes.

**Out of scope:**
- Tailwind, or any CSS framework, preprocessor or PostCSS plugin. That belongs to roadmap F6-M2 and F7-M2.
- Changing any page's appearance. That includes unifying the near-identical rules to one value: where pages differ today, they still differ afterwards.
- `about.css` and its rules, other than the About page receiving the base.
- Renaming the video page's classes, or any class not named in item 4.
- Other cleanup inside the page stylesheets, such as dead rules or reordering beyond what the move needs.
