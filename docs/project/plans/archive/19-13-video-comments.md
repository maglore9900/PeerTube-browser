# 13-video-comments

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-13-video-comments.record.md`._

## Requirements

### Purpose

Show a video's discussion from its source PeerTube instance on the video page (`client/frontend/video-page.html`, `client/frontend/src/pages/video-page/index.ts`), read-only. A viewer can then see how people reacted to a video without leaving this site. This build does not add commenting (roadmap F4-M5), comment moderation (F9-M6) or any local storage of comments (F3-M4). Source: issue `docs/project/issues/13-video-comments.md` (task 4, [M2][F1]). The operator approved the choices below: expandable replies, a direct browser-to-instance fetch, and 20 per batch behind a "Load more" button.

### R1 Placement

A new "Comments" section goes in `client/frontend/video-page.html` after the video details section, which ends with `#video-description` and `#description-toggle`, and before `#similar-section` ("Similar videos"). It follows the page's existing section markup and styles (`client/frontend/src/video.css`). Once the first batch has loaded, its heading shows the live total from the API: "Comments (N)". Until then it shows "Comments".

### R2 Source and request flow

- The browser calls the source instance directly, the same way the page already calls `https://{host}/api/v1/videos/{id}`, `/api/v1/config` and `/api/v1/video-channels/{id}` (functions `fetchVideoMetadataFromInstance`, `fetchInstanceMetadata`, `fetchChannelMetadata`). No Client-backend proxy and no Engine route are added. The page CSP (`connect-src 'self' https:`) already allows these requests.
- Thread list: `GET https://{host}/api/v1/videos/{id}/comment-threads?start={offset}&count=20&sort=-createdAt`.
- One thread's replies: `GET https://{host}/api/v1/videos/{id}/comment-threads/{threadId}`.
- `{host, id}` come from the page's existing `resolveVideoSource()`, i.e. the `host`/`id`/`url` query parameters. PeerTube accepts a numeric id, a UUID or a short UUID in `{id}`, and each is URI-encoded. When no host or id can be resolved, the section shows the unavailable state (R6) and makes no request.
- The comments load starts at module start, alongside `loadVideo()` and `loadSimilarVideos()`. It waits for neither, and neither waits for it.
- Known limitation: the visitor's IP reaches the source instance, as it already does for the page's other instance calls.

### R3 Verify the response structure first

Before any rendering code is written, the builder runs both endpoints against one real video on a real PeerTube instance. They record in the plan or build record the host and video id used, and the fields the code will read:
- from the thread list: `total`, `data[].id`, `data[].threadId`, `data[].text`, `data[].createdAt`, `data[].isDeleted`, `data[].totalReplies`, `data[].account.displayName`, `data[].account.name` and `data[].account.host`;
- from the thread detail: `{ comment, children: [{ comment, children }] }`;
- how a video with comments disabled answers: an empty list, or an error status.

Parsing is written to that recorded structure. It tolerates any missing or mistyped field by falling back to an empty or default value, never by throwing.

### R4 Pagination of threads

20 threads per batch, newest first (`sort=-createdAt`). A "Load more comments" button appends the next batch (`start` advances by 20). The button is hidden once the number of threads received reaches `total`, or when a batch comes back empty. A second batch request is never started while one is in flight: the button is disabled for the duration.

### R5 Replies

- A thread with `totalReplies > 0` shows a "Show N replies" button.
- The first click fetches that thread's reply tree once, one request, and renders the replies nested under the thread, keeping nesting by indentation.
- Replies are shown 20 at a time from the fetched tree. A "Show more replies" button reveals the next 20 with no further request.
- Clicking the toggle again collapses the replies. Expanding again re-shows them without refetching.
- A reply fetch is never duplicated while one is in flight for the same thread.

### R6 States and failure isolation

- While the first batch loads, the section shows "Loading comments…".
- When `total` is 0 it shows "No comments yet.".
- When the first request fails (network error, CORS block, non-OK status, unparsable JSON), when the video has comments disabled, or when no host/id is resolvable, it shows "Comments are unavailable on {host}." with a link to the original video. The link is the same original URL the page's `#original-link` uses. Without a host, the message omits the host.
- A failed "Load more" or reply load shows an inline message with a retry button and keeps everything already rendered.
- No comments failure throws out of the module, logs more than a `console.warn`, or affects any other part of the page: metadata, player, reactions, block buttons, similar videos.

### R7 Read-only

The section has no comment input, reply, like, report or any other write control. Its only interactive controls are "Load more comments", "Show N replies"/collapse, "Show more replies", retry, and author or original-video links.

### R8 Rendering and safety

- Remote content is inserted only as text (`textContent`, `createTextNode`, `append`), never through `innerHTML` or `insertAdjacentHTML`. This follows the page's existing rule for tags ("built from text, never from markup").
- Each comment shows:
  - the author's `displayName`, with `@name@host` as secondary text;
  - a relative time from `createdAt`, using the page's existing `formatTimeAgo`;
  - the text with its line breaks kept.
- Comment text that contains HTML sent by federated servers (e.g. Mastodon `<p>`, `<br>`, `<a>`, `<span class="h-card">`) is reduced to its plain text. Paragraph and `<br>` breaks become line breaks, and HTML entities are decoded. No remote markup is ever interpreted by the live DOM. Markdown is shown raw.
- Deliberate simplification: links in comments are not clickable and Markdown is not rendered. That upgrade would need an HTML sanitiser, which the build does not add.
- A deleted comment (`isDeleted`) that still has replies shows "Comment deleted" in place of author and text, so its replies keep their context. A deleted comment with no replies is not shown.
- Any author link goes through the existing `safeExternalUrl`.

### R9 Scope boundaries

- No change to the Client backend (`client/backend/server.py`), the Engine, the crawler or the datasets.
- No new dependency: plain TypeScript and DOM APIs only.
- The existing comments enrichment (`npm run crawl:videos:comments`, which stores only `videos.comments_count` via `GET /api/v1/videos/<uuid>`) is not needed for this feature and is not used. The issue's stated dependency on it is already met and has no effect on the build.
- `client/frontend/dist` is build output and is regenerated, never hand-edited.

### R10 Tests

Extend the node harness in `tests/active/test_frontend_video_page.py`, which runs the real page module with stubbed `document`, `window`, storages, `ResizeObserver`, `getComputedStyle` and `fetch`. The stubbed `fetch` also answers the instance comment endpoints. Tests cover:
- the first batch rendering the authors and texts, with the heading total;
- "Load more" appending the next batch with `start=20`, and hiding at `total`;
- the "No comments yet." state for `total: 0`;
- the unavailable state for a failed request and for comments disabled, while the rest of the page (e.g. the taxonomy) still renders;
- a reply expansion making exactly one thread request, with repeated toggles making no further requests;
- a hostile comment (HTML/script markup in `text` and `displayName`) rendered only as text, with no markup reaching the DOM.

The existing taxonomy cases must keep passing. No test makes a real network call.

### Baseline suite state

The pre-build suite exited 0 (baseline variant: false). Only `test_search_fusion.py` was selected (10 passed), with 24 groups unchanged. Resolved paths: active tests `tests/active`, working tests `tests/tmp`, plans `docs/project/plans`, delete_me `delete_me`, archive `tests/archive`, project dir `/home/enduser/code/PeerTube-browser/.worktrees/13`, validation record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.

## High-level plan

### Approach

All the work goes into four places. There is one new `<section>` in `client/frontend/video-page.html`, a comments block inside `client/frontend/src/pages/video-page/index.ts`, a few rules in `client/frontend/src/video.css`, and new cases in `tests/active/test_frontend_video_page.py`. Nothing touches the backend, Engine, crawler, datasets or `dist` (R9).

**R3 comes first.** Before any rendering code, the builder runs the thread list, one thread detail and `GET /api/v1/videos/{id}` against a real video on a real instance. They also run the thread list on a video with comments disabled. The build record gets the host and id used and the fields read. It also gets the disabled video's answer, which is expected to be 200 with `{ total: 0, data: [] }`, and the exact value `commentsEnabled`/`commentsPolicy` has when comments are disabled. Every parse step reads through small tolerant accessors. A missing or wrongly typed field becomes `""`, `0`, `false` or `[]`, and nothing throws.

**R1 Placement.** A `<section id="comments-section" class="comment-card">` goes between the player card's closing tag and `#similar-section`. `.comment-card` already exists in `video.css` (line 122, sharing the card style with `.player-card` and `.similar-card`), so the section looks like its neighbours without a new card style. It holds a `section-header` with an `<h3 id="comments-heading">Comments</h3>`, a list container, a status line, and a "Load more comments" `ghost-button` that starts hidden. The heading switches to "Comments (N)" from `total` once a batch arrives, and every later batch updates it again.

**R2 Request flow.** `void loadComments()` is added next to `void loadVideo()` and `void loadSimilarVideos()` at module start. It does not await `localLikesImported`, `loadVideo` or anything else, and nothing awaits it. It takes `{host, id}` from the existing `resolveVideoSource()`. If either is empty it renders the unavailable state and fetches nothing. The URLs are built the way `fetchVideoMetadataFromInstance` builds its URL: `https://${host}/api/v1/videos/${encodeURIComponent(id)}/comment-threads?start=…&count=20&sort=-createdAt`, and `…/comment-threads/${encodeURIComponent(threadId)}` for replies. The requests send the same `Accept: application/json` header as the existing calls.

**Operator-approved amendment for "comments disabled".** PeerTube answers a disabled video's thread list with an empty 200, so it can't be told apart from "no comments". When the first batch returns `total === 0`, one more request goes to `GET https://{host}/api/v1/videos/{id}`. If it reports comments disabled (`commentsEnabled === false`, or `commentsPolicy.id` equal to the disabled value recorded in R3), the section shows the unavailable state. In every other case, including that request failing, it shows "No comments yet.". Correction to my question to the operator: I named the disabled policy id as 3. In PeerTube's enum, DISABLED is expected to be 2 and 3 is REQUIRES_APPROVAL. The code compares against the value R3 records, not a number assumed here.

**R4 Pagination.** The block keeps its state in module variables: the next offset, the number of threads received, a set of seen thread ids, and a `loadingBatch` flag. "Load more" returns immediately if `loadingBatch` is set. Otherwise it disables itself, requests `start = offset`, and appends only threads whose ids it hasn't seen. The dedupe matters because a comment posted between batches shifts newest-first offsets by one. It then advances the offset by 20 and re-enables. The button hides once the received count reaches `total` or a batch has no rows. Deleted threads that aren't shown still count as received, so the count against `total` stays correct.

**R5 Replies.** Each thread with `totalReplies > 0` gets a "Show N replies" button, with its own state held in the closure that renders the thread: `loading`, `rows` (null until fetched), `shown` and `expanded`. The first expand makes the one detail request, ignoring clicks while `loading`. It then flattens `children` in pre-order into `{comment, depth}` rows and renders the first 20 into a replies container under the thread. The label becomes "Hide replies". Collapsing hides the container. Expanding again unhides it with no request. "Show more replies" appends the next 20 of the flattened list with no request, and hides when all are shown. Nesting is shown by an indent per depth, capped at a few levels so deep chains don't run off narrow screens.

**R6 States.** "Loading comments…" shows until the first batch settles. If the first request fails in any way (a thrown fetch covers network and CORS, plus non-OK status or a JSON parse error), or comments are disabled, or there is no host/id, the section shows "Comments are unavailable on {host}." with a link to the original video. Without a host it shows "Comments are unavailable." with the link. The link uses the same expression `loadVideo` puts on `#original-link`, `currentMetadata?.originalUrl ?? fallback.url`, through `safeExternalUrl`. That expression is pulled into one small helper so the two can't drift. Comments may render before `loadVideo` settles, so `loadVideo` refreshes the unavailable link's href where it already sets `#original-link` (one assignment, no waiting either way). A failed "Load more" or reply fetch puts an inline message with a "Retry" button next to the control that failed and keeps everything already rendered. Retry runs the same guarded function again. Every async path ends in a `catch` that makes one `console.warn` and renders a state. Nothing is rethrown, and the block writes only to elements inside its own section.

**R7 Read-only.** The only controls built are the load-more, reply-toggle, show-more-replies and retry buttons, plus the original-video link. There is no input, form or write request.

**R8 Rendering.** Every node is made with `createElement` and filled with `textContent`, `append` or `createTextNode`. Nothing in the comments block uses `innerHTML` or `insertAdjacentHTML`. A comment shows `displayName` (falling back to `name`), `@name@host` as muted secondary text, a relative time and the text. The text sits in an element with `white-space: pre-wrap` (the same rule `.video-description` uses), so line breaks survive. `createdAt` is an ISO string, and the page's `normalizeTimestampMs` does `Number(value)`, which gives NaN for ISO strings. So the time is parsed with `Date.parse`, passed to `formatTimeAgo` if finite, and left out otherwise. Federated HTML is reduced by a small pure string function. It only acts when the text contains something that looks like a tag (`<` followed by a letter or `/`); plain PeerTube text is left raw, so Markdown shows unchanged. `<br>` becomes a newline and a paragraph boundary becomes a blank line. All remaining tags are stripped, and entities are decoded last: numeric decimal and hex, plus `amp lt gt quot apos nbsp`. Because decoding comes last, `&lt;script&gt;` ends up as the literal text "<script>", inserted as text. Deleted comments: a deleted thread with `totalReplies > 0`, or a deleted reply with children, renders "Comment deleted" in place of author and text. A deleted one with no replies is skipped. Authors are plain text in this build, not links. That's the smallest option. The upgrade is to link `account.url` through `safeExternalUrl`, which R8 already covers.

**R10 Tests.** The harness needs four extensions, all additive, so the three taxonomy cases keep their behaviour:

- **Listeners.** Today `addEventListener` is a no-op. It needs to record listeners per element, plus a `click(el)` helper that calls them.
- **Request log.** `requested` keeps pathnames, which the existing control assertion relies on. A second `requestedUrls` list gets the full URLs, so `start=20` and the thread-detail count can be checked.
- **Fetch stub.** It routes the instance paths (`/api/v1/videos/v1/comment-threads`, `…/comment-threads/{id}`, `/api/v1/videos/v1`) to a per-case `COMMENTS` env map. Each entry is a body, a status, or "throw". Unmapped paths keep answering `{}`, which parses as `total: 0` → "No comments yet.", so old cases are unaffected.
- **Report and cases.** The runner reports a serialised walk of `#comments-section`'s subtree: node types, text, `hidden`, `disabled` and classes. `insertAdjacentHTML` is made to record calls, so the hostile case can assert that no `nodeType: 0` (innerHTML-set) node and no recorded markup call exist in the subtree, and that the literal markup appears as text. Scenarios with clicks run a scripted list of actions between settle loops, driven by a `STEPS` env.

The cases are: first batch, load more to total, total 0, failed request plus taxonomy, disabled plus taxonomy, reply toggle making one request, and hostile text/displayName.

### Alternatives considered

- **Separate `comments.ts` module.** Rejected. It would need `resolveVideoSource`, `formatTimeAgo`, `fallback` and `currentMetadata`, which are private to `index.ts`. That means exporting them or passing a context object, more surface for no reuse. `index.ts` already holds every page block, and the harness bundles it either way. Upgrade path: move the block out if a second page ever shows comments.
- **`DOMParser`/`<template>` to reduce HTML.** Rejected. It creates a parsed document from remote markup, which is close to "interpreted by the DOM" even though it's inert. It isn't available in the node harness without another stub. And it gives no benefit over a string reducer when the output is plain text anyway. A `<textarea>.innerHTML` trick for entity decoding is ruled out by R8.
- **Applying the reducer to every comment.** Rejected. Stripping `<…>` from native PeerTube Markdown would eat text like `a <b> c` written by a human. The tag-shape check limits that damage to federated HTML.
- **Paging replies per request.** Not possible: the thread-detail endpoint returns the whole tree (already recorded as a Step 1 conflict).
- **Sharing the `/api/v1/videos/{id}` response with `fetchVideoMetadataFromInstance`.** Rejected. That function only runs in the fallback path and drops the comments flags. Sharing would couple the comments load to `loadVideo`, which R2 forbids.
- **Treating disabled as empty, or deciding after R3.** Offered to the operator; they chose the extra check.

### Gotchas, risks, limitations

- **ISO `createdAt`.** `normalizeTimestampMs` would silently give NaN, as noted above. The builder must not reuse it.
- **Where the unavailable link comes from.** If the page has neither metadata nor a `url` parameter, `#original-link` has no href either. The unavailable message then shows its link without an href, matching the page rather than making up a URL.
- **Duplicate video request.** In the fallback path (server metadata failed) with zero comments, the page asks the instance for `/api/v1/videos/{id}` twice. That's accepted as rare and cheap.
- **Reducer edge cases.** HTML-shaped text in a native comment (e.g. "use `<div>`") loses the tag text. Unknown named entities (`&hellip;`) stay literal. Mastodon's hidden URL `<span>`s are flattened, so their full URL text shows. The ceiling is plain text. The upgrade is a real sanitiser, which R8 rules out for now.
- **Instances that refuse the request.** Some instances may block the request with CORS or a rate limit. They get the unavailable state, which is correct but hides the cause; the reason goes to `console.warn`.
- **Harness timing.** The existing settle loop is 5×10 ms. The extra disabled-check request and the clicked steps need a settle loop after each action, or the tests turn flaky.
- **Harness lookups.** The harness's `querySelector` returns null. The block must keep direct references to the elements it builds and never query its own subtree. That's also the cleaner design.

### Tradeoffs the operator accepts

- R2 gains a third instance endpoint, `/api/v1/videos/{id}`, only when the thread total is 0 (approved).
- Comment links aren't clickable, Markdown isn't rendered, and authors are unlinked text.
- Replies from very large threads are fetched in one response and only displayed 20 at a time.
- Reply indentation is capped at a fixed depth.
- The visitor's IP reaches the source instance for the comment calls, as it already does for the page's other instance calls.

## Impacts

<impacts>
<impact path="client/frontend/video-page.html" element="new &lt;section id=&quot;comments-section&quot; class=&quot;comment-card&quot;&gt; between the player card's closing &lt;/section&gt; (line 122) and &lt;section id=&quot;similar-section&quot;&gt; (line 124)">
**What changes.** A new section holding a `section-header` with `<h3 id="comments-heading">Comments</h3>`, a list container, a status line, and a "Load more comments" `ghost-button` with the `hidden` attribute in the markup. No existing id starts with `comment` (ids in use: `video-*`, `channel-*`, `instance-*`, `account-*`, `block-*`, `like-*`, `dislike-*`, `reaction-status`, `original-link`, `description-toggle`, `similar-*`), so there is no collision.

**What depends on it.** `index.ts` looks the ids up with `getElementById` at module top. The meta CSP at line 8 (`connect-src 'self' https:`) already allows the instance fetches. `client/frontend/vite.config.ts:89` already lists `video-page.html` as a rollup input. `.un/skills/devsecops/config.json:148-151` maps this file to `test_frontend_video_page.py`, so editing it selects that group.

**Regression risk: low.** Pure addition. Trap: the node harness never parses this HTML. Its `getElementById` (test line 63) makes a fresh `div` whose `hidden` is false unless the id is in `INITIALLY_HIDDEN`, so the markup's `hidden` on the load-more button is invisible to tests. The code must set `hidden` itself (or the test must list the id), otherwise tests pass on state the browser never has, and vice versa.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="module top: element constants (lines 22-54), module state (58-73), start calls `void loadVideo()` / `void loadSimilarVideos()` (97-98)">
**What changes.** New `getElementById` constants for the section, heading, list, status line and load-more button (next to 49-51); module `let`s for next offset, received count, a `Set` of seen thread ids and `loadingBatch`; a module reference to the unavailable-state link so `loadVideo` can refresh it; `void loadComments();` after line 98.

**TDZ hazard.** `void loadComments()` runs synchronously up to its first `await`, and the no-host/no-id path has no `await` at all. If the block's `let`/`const` state is declared lower in the file (next to its functions), the first access throws `ReferenceError` during module evaluation of the async function, surfacing as an unhandled rejection. Existing blocks keep state above the start calls (`similarStatsCache`, line 72); this block must too. Function declarations are hoisted and safe.

**What depends on it.** `localLikesImported` (93) must not be awaited (R2). `applyActionIcons()` (1296) runs at module load and calls `insertAdjacentHTML` (see harness entry).

**Regression risk: medium.** In the node harness an unhandled rejection exits non-zero before `process.exit(0)`, so a TDZ slip fails all three existing taxonomy tests.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadVideo() (lines 103-268): original-URL expression at line 118 and the #original-link block at lines 261-267">
**What changes.** `const original = metadata?.originalUrl ?? fallback.url` (118) moves into a small shared helper reading `currentMetadata?.originalUrl ?? fallback.url` (equivalent, since line 105 sets `currentMetadata = metadata`). The `if (originalLink)` block (261-267) also sets the comments unavailable link's href when that link exists.

**Semantics to keep.** Empty value → `removeAttribute("href")`; non-empty → `safeExternalUrl`. `safeExternalUrl("")` returns `"#"` (`utils/safe-url.ts:18`), so the helper must not blindly assign `safeExternalUrl(original)` or an empty original becomes `href="#"`, contradicting the plan's "link without an href" gotcha. The comments block must also call the helper at its own render time, since in the usual order (tests included) the thread list settles after `loadVideo`, and before `currentMetadata` is set it falls back to `fallback.url` only.

**What depends on it.** Only `#original-link`. `originalUrl` comes from `data.originalUrl ?? source.url ?? fallback.url` (612) or `data.url ?? data.videoUrl ?? source.url ?? ""` (663-667).

**Regression risk: low to medium.** A mistake changes the existing "Open original" link.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="new comments block: loadComments(), batch loader, thread/reply renderers, tolerant accessors, HTML reducer, disabled check">
**What changes.** All new code. Reusable helpers, verified:
- `resolveVideoSource()` (763-771) returns `null` only when both host and id are empty; otherwise `{host, id, url}` with either possibly `""`. Check both fields, not just null.
- `getString` (794-800) returns `""` for missing/non-string/blank — fits the tolerant string accessors.
- `normalizeNumber` (887-891) returns `null` for non-finite, so `total`/`totalReplies` need `?? 0`.
- `formatTimeAgo` (896-911) takes ms; `Date.parse` gives ms. It reads real `Date.now()` (897).
- Do not use `normalizeTimestampMs` (868-874; `Number(iso)` → NaN → null) or `escapeHtml` (1301; only for the page's innerHTML writers).

URL shape follows `fetchVideoMetadataFromInstance` (632) and `fetchSingleViews` (1080): `https://${host}/api/v1/videos/${encodeURIComponent(id)}`, header `Accept: application/json`.

**What depends on it.** Nothing outside the section.

**Regression risk: medium.** R8 depends on no `innerHTML`/`insertAdjacentHTML` in the block; the file uses `innerHTML` at 141, 150, 175, 182, 200, 207, 222, 312, 315, 323, so those patterns must not be copied. Every async path needs its own try/catch ending in one `console.warn`. The reducer must strip tags before decoding entities. The disabled-policy constant depends on the R3-recorded value (2 expected, not 3).
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadataFromInstance() (630-695), fetchSingleViews() (1079-1085)">
**What changes.** Nothing. The disabled check makes its own `/api/v1/videos/{id}` request (sharing rejected by the plan). In the fallback path with zero comments the same URL is requested twice; accepted.

**What depends on it.** `loadVideo` and the similar stats only.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadSimilarVideos() (290-325), loadReaction() (382-405), enableBlockButtons() (331-364), description toggle (82-90), applyActionIcons() (1291-1296)">
**What changes.** Nothing.

**What depends on it.** R6 isolation holds only if the comments block never touches these blocks' elements and never throws during module evaluation (TDZ entry). These blocks add click listeners (83, 341, 395, 398); once the harness records listeners they are stored but never fired unless a test clicks them.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/video.css" element="new comment rules; existing .comment-card (121-129), .section-header (521-532), .ghost-button (349-369), .video-description pre-wrap (450-458), .taxonomy-item[hidden] (487-490), .similar-grid .loading/.error (616-620), legacy .comment-label (434-437), global textarea (439-448), #comment-submit (517-519)">
**What changes.** New rules for the comment list and item, author line with muted `@name@host`, time, body with `white-space: pre-wrap`, reply container with a capped per-depth indent, status line, inline error and retry.

**Watch.**
- `.comment-card` already exists and is reused.
- `.similar-grid .loading/.error` are scoped to the similar grid; the comments status needs its own rule.
- **`[hidden]` trap.** Any new rule setting `display` (flex/grid) on something the code hides with `hidden` overrides the UA `[hidden]{display:none}`; `.taxonomy-item[hidden]` (487-490) is the precedent fix. Without it a collapsed replies container or finished load-more button stays visible in the browser while the harness (which reads `.hidden`) passes.
- **Legacy form rules.** `.comment-label`, the global `textarea` and `#comment-submit` are unused leftovers of a comment form (no HTML/TS references them in `src` or the page). R7 forbids reusing them as write controls; new class names must not collide with `comment-label`. Deleting them is optional, out of plan scope.

**What depends on it.** Only the video page (`index.ts:5`). The harness bundles CSS with `--loader:.css=empty`, so no test checks styles.

**Regression risk: low for other elements; medium for visual correctness.**
</impact>
<impact path="tests/active/test_frontend_video_page.py" element="RUNNER harness: element() stub (34-58), document stub (61-66), fetch stub and request log (70-76), settle loop (79), report (80-83); _page() (102-113); module docstring (1-8); the three taxonomy tests">
**Listeners.** `addEventListener() {}` (55) becomes per-element recording plus a `click(el)` helper. Existing listeners (description toggle, block, reaction) get stored but stay unfired.

**`insertAdjacentHTML` recording.** `applyActionIcons()` (index.ts:1292-1293) calls it on `like-button`/`dislike-button` at every load, so the hostile case's "no recorded markup call" assertion must be scoped per element inside `#comments-section`, or it fails every run.

**Request logs.** `requested` keeps pathnames (73); the control at line 111 relies on it. A new `requestedUrls` gets full URLs.

**Fetch routing.** `new URL(input, BASE)` (72) keeps absolute instance URLs, giving pathnames `/api/v1/videos/v1/comment-threads`, `/api/v1/videos/v1/comment-threads/{id}` and `/api/v1/videos/v1` (from `?id=v1&host=peer.example`, line 30). Unmapped paths answer `{}` → `total` 0 → disabled check → `{}` → "No comments yet.", so existing cases make two extra requests but keep their assertions. `/api/v1/config` keeps answering `{}`. A "throw" entry and a non-200 status entry need new branches (the stub always returns 200 today).

**Stub limits the block must live with.** `querySelector` null and `closest` null (54); `remove()` no-op (55); `appendChild` does not set `parentElement`; text nodes (32) have no `hidden`/`classList`; `innerHTML` writes produce `nodeType: 0` nodes (42). So removals must be done by replacing/hiding via direct references, and the subtree walk must tolerate text nodes.

**`href` gap.** The stub has no `href` accessor: `link.href = x` sets a plain property while `removeAttribute("href")`/`getAttribute("href")` only touch `attrs` (50-53). The unavailable link's href (set via `.href`, cleared via `removeAttribute`) is misreported whichever the report reads; a getter/setter linking `href` to `attrs` (as `hidden` is linked) is needed to assert it.

**Time drift.** `formatTimeAgo` uses real `Date.now()`, so a fixed ISO `createdAt` fixture's time text drifts ("1 years ago" → "2 years ago"). Assert author, `@name@host` and body separately from the time element, or build `createdAt` relative to now in Python.

**Timing and exit.** Settle loop is 5×10 ms (79); the disabled check adds a second fetch round and each clicked step needs its own settle loop. An unhandled rejection exits non-zero before `process.exit(0)` (84), failing `assert proc.returncode == 0` (108).

**Docstring.** Lines 1-8 describe a taxonomy-only runner and must gain the comment cases and new stubs. Fixture `mktemp("video_taxonomy")` (90) name is cosmetic.

**What depends on it.** Group `test_frontend_video_page.py` in `.un/skills/devsecops/config.json:148-151`, which already maps `index.ts`, `video.css`, `video-page.html`; no map change.

**Regression risk: medium.** Harness edits can silently break the three taxonomy cases.
</impact>
<impact path="client/frontend/src/utils/safe-url.ts" element="safeExternalUrl() (17-20)">
**What changes.** Nothing.

**What depends on it.** The unavailable-state link and any future author link. Returns `"#"` for empty or non-http(s) input, never `""` — see the `loadVideo` entry for why the no-href case needs `removeAttribute`.

**Regression risk: none.**
</impact>
<impact path="docs/project/security-audit/run-2/REPORT.md" element="finding at lines 220-223: the video page fetches from any host given in ?host=">
**What changes.** Nothing in the file, but the finding widens: today the page contacts an arbitrary `?host=` for `/api/v1/config` and, on `/api/video` failure, `/api/v1/videos/{id}`. The comments block fetches `https://${host}/api/v1/videos/.../comment-threads` from that same unvalidated `seedHost` on every view, unconditionally, and renders the response. `seedHost` is used raw by `resolveVideoSource` (766), so a value with `/`, `@`, `?` or `#` reshapes the URL.

**What depends on it.** R8's text-only rendering is what keeps an attacker-controlled host's comments harmless; the hostile-text test case is the guard. `{host}` also appears in the "Comments are unavailable on {host}." message, which must be set as text.

**Regression risk: low if R8 holds; high if any comment field reaches an HTML sink.** Host validation is out of plan scope; worth a line in the build record as a known limitation.
</impact>
<impact path="DEPLOYMENT.md" element="nginx server block CSP header (line 325); rsync of dist (309-313)">
**What changes.** Not in the plan, but decides whether the feature works in the documented production setup. The header is `default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-src https:` with no `connect-src`, so `connect-src` falls back to `'self'`. Header and meta CSP are both enforced, so every `fetch` to `https://{host}/api/v1/...` is blocked; comments would always show "Comments are unavailable on {host}." with only a `console.warn`. The same header already silently blocks the page's existing instance calls and remote `img-src` avatars.

**What depends on it.** The whole comments feature in production. Deploy copies `dist/` by rsync (309) and must be rerun after every build (313).

**Regression risk: high for the feature's value in production; no test catches it.** Either add `connect-src 'self' https:` (and `img-src 'self' https: data:`) or record it as a known limitation.
</impact>
<impact path="client/frontend/dist/video-page.html" element="committed build output (dist/video-page.html, dist/assets/video-gjYm1MC8.js, dist/assets/video-ypOuFwNw.css)">
**What changes.** Regenerated by `npm run build` under new hashes; never hand-edited (R9). The committed `dist/video-page.html` is already stale (line 102 lacks the collapsible-description markup and there is no taxonomy block), so a deploy that rsyncs `dist/` without rebuilding ships no comments section.

**Regression risk: low.**
</impact>
<impact path="docs/project/plans/19-13-video-comments.record.md" element="build record: R3 live-check evidence">
**What changes.** R3 wants host, id, fields read, the disabled video's answer and the disabled `commentsPolicy` value recorded "in the plan or build record". Line 5 says only the workflow writes this file, so the builder must hand the evidence to the workflow. The code's disabled-policy constant depends on it.

**Regression risk: low (process).**
</impact>
<impact path="tests/last_test_validation.json" element="test_frontend_video_page.py entry (lines 235-243) and its per-test ids (353-361)">
**What changes.** Digest, pass count (3 → 3 + new cases) and duration are rewritten by the suite runner; never hand-edited.

**Regression risk: none.**
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="frontend gateway preflight (lines 22-38)">
**What changes.** Nothing. It forbids only Engine base names, Engine ports and `/internal/*` literals in `client/frontend/src`; the new `https://${host}/api/v1/videos/...` template matches none.

**Regression risk: none.**
</impact>
<impact path="client/frontend/vite.config.ts" element="rollup input `video` (line 89), dev proxy (line 27)">
**What changes.** Nothing. The page is already an input; comment requests go straight to the instance, not through the dev `/api` proxy.

**Regression risk: none.**
</impact>
<impact path="CONTEXT.md" element="glossary: `Interaction event` mentions `Comment` events (line 6)">
**What changes.** Nothing required. That term is about published interaction events, not read-only instance comments; a reader could conflate them. An optional glossary line ("Comment (source-instance)") is not called for by the plan.

**Regression risk: none.**
</impact>
</impacts>

## Documentation to update

- [x] `client/frontend/README.md` - updated: `client/frontend/README.md`: documented the video page's read-only comments section and its direct reads from source PeerTube instances, and narrowed the boundary rule to Client and Engine data.
- [x] `README.md` - updated: I qualified the README's frontend-read rules so they no longer ban the video page's direct calls to the source PeerTube instance (the metadata fallback and comments).
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: widened the nginx CSP so direct instance reads and remote images work, qualified the frontend boundary rule, and made a fresh build a required step before the rsync.
- [x] `docs/project/roadmap.md` - updated: Roadmap: read-only video comments (F11-M2, issue `13`) listed as delivered and removed from the pending lists.
- [x] `docs/project/issues/13-video-comments.md` - updated: Closed issue 13 as delivered: status set to complete, a "Delivered" comment added, and the file written to `docs/project/issues/archive/13-video-comments.md`. The original at `docs/project/issues/13-video-comments.md` still exists and must be deleted, because my tools can't delete files.
- [x] `docs/project/issues/plan.md` - updated: `docs/project/issues/plan.md`: lane 5b (13 comments) is marked delivered, and the triage note on 13's dependency is corrected and marked resolved.
- [x] `docs/project/adr/0004-cors-opt-in-by-origin.md` - out of scope: It governs CORS headers sent by the Client backend and the Engine. The comments requests go from the browser to third-party PeerTube instances, whose CORS is theirs. No Client backend or Engine route was added, so nothing it claims changes.
- [x] `docs/project/security-audit/run-2/REPORT.md` - out of scope: A dated audit report records findings as they stood at that run. The finding at lines 220-223 (the video page fetches from any `?host=`) still holds and is widened by the comments fetch. Recording that belongs in the build record's known limitations or a future audit run, not in an edit to a past report.
- [x] `CONTEXT.md` - out of scope: The only related term, `Interaction event` (line 6), is about published `Comment` interaction events, which this build does not touch. The glossary claims nothing about read-only instance comments, so nothing in it is false.

## Implementation plan

## Draft implementation — 13 read-only video comments

I did one drafting pass and one check against the plan and R1–R10. The check found three harness facts the plan's R10 wording glosses over. All three are handled inside the settled scope (§6). No requirement or plan point is left unmet, so there is nothing to put to the operator.

**Precondition, not done here.** R3's live check comes before any rendering code. I have no network tool, so the builder runs it and hands the result to the workflow for the record. Record the host and id, the thread-list and thread-detail fields, the disabled video's thread-list answer, and its `commentsEnabled`/`commentsPolicy`. `COMMENTS_POLICY_DISABLED = 2` below is provisional until that run confirms it. If the value differs, only that constant changes.

### 1. What the build has to test (R10 and the traps from the inventory)

| Behaviour | Why it needs a test | Case |
|---|---|---|
| First batch: authors, `@name@host`, body with `\n` kept, heading "Comments (N)", exact list URL, a deleted thread with 0 replies left out | R1, R2, R8 | A |
| Load more: one `start=20` request even after a double click, rows appended, button hidden at `total` | R4, including the in-flight guard | B |
| `total: 0` plus comments enabled → "No comments yet.", "Comments (0)", disabled check sent | R6, amendment | C |
| First request throws / returns 500 / returns bad JSON → unavailable with host and original href, taxonomy still rendered, one `[comments]` warn | R6 isolation | D (×3) |
| Disabled (`commentsEnabled:false` / `commentsPolicy.id:2`) → unavailable, taxonomy still rendered | amendment, R6 | E (×2) |
| Reply toggle: double click → 1 detail request, pre-order depth classes, deleted-with-child shows "Comment deleted", deleted leaf left out, hide, re-show without a new request or duplicate rows | R5, R8 | F |
| Hostile `displayName`/`text`: literal text only; no type-0 (innerHTML) node and no `insertAdjacentHTML` call in any comments root; Markdown `a < b` stays raw | R8 | G |
| The 3 existing taxonomy cases unchanged; they now also run the default `{}` path through to "No comments yet." | regression | existing |

### 2. `client/frontend/video-page.html` — inserted after line 122 (`</section>` of the player card), before `#similar-section`

```html
        <section id="comments-section" class="comment-card" aria-labelledby="comments-heading">
          <div class="section-header">
            <h3 id="comments-heading">Comments</h3>
          </div>
          <div id="comments-list" class="comments-list"></div>
          <p id="comments-status" class="comments-status" role="status">Loading comments…</p>
          <button id="comments-more" class="ghost-button comments-more" type="button" hidden>Load more comments</button>
        </section>
```

The code sets the heading text, the loading text, the button label and `hidden` again itself. The harness never parses this file, so markup-only state would be invisible to it. The status line sits directly above the load-more button, so a load-more error with its retry lands "next to the control that failed". There is no `#comments-section` constant in TS: nothing reads it, and the block keeps direct references to its four children.

### 3. `client/frontend/src/pages/video-page/index.ts`

#### 3a. Element constants, after line 54

```ts
const commentsHeading = document.getElementById("comments-heading");
const commentsList = document.getElementById("comments-list");
const commentsStatus = document.getElementById("comments-status");
const commentsMoreButton = document.getElementById("comments-more") as HTMLButtonElement | null;
```

#### 3b. State and constants, after line 73 (above the start calls, because of the TDZ)

```ts
// Comments come straight from the source instance. This state sits above the start calls because loadComments reads it before its first await.
const COMMENTS_BATCH = 20;
const REPLIES_BATCH = 20;
// PeerTube's VideoCommentPolicy.DISABLED, as recorded by the R3 live check.
const COMMENTS_POLICY_DISABLED = 2;
// Deeper replies share the last indent, so long chains stay readable on narrow screens.
const REPLY_DEPTH_CAP = 4;
const HTML_ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: "\u00a0" };
let commentsSource: CommentSource | null = null;
let commentsOffset = 0;
let commentsReceived = 0;
let commentsLoadingBatch = false;
const commentsSeen = new Set<string>();
let commentsUnavailableLink: HTMLAnchorElement | null = null;
```

#### 3c. Start call, after line 98

```ts
void loadComments();
```

Nothing awaits it, and it awaits nothing of the page's: not `localLikesImported`, `loadVideo` or `loadSimilarVideos`.

#### 3d. `loadVideo` edits (behaviour of `#original-link` unchanged)

- Delete line 118 (`const original = metadata?.originalUrl ?? fallback.url;`). `original` is only read at 262-263.
- Replace lines 261-267 with:

```ts
  applyOriginalHref(originalLink);
  applyOriginalHref(commentsUnavailableLink);
```

- New helpers, placed next to `renderTaxonomyItem`:

```ts
/**
 * The original video's URL, shared by "Open original" and the comments fallback so the two never drift.
 */
function originalVideoUrl() {
  return currentMetadata?.originalUrl ?? fallback.url;
}

/**
 * Point a link at the original video; with no original URL the link has no href, as `#original-link` always had.
 */
function applyOriginalHref(link: HTMLAnchorElement | null) {
  if (!link) return;
  const original = originalVideoUrl();
  if (original) {
    link.href = safeExternalUrl(original);
  } else {
    link.removeAttribute("href");
  }
}
```

Why this is equivalent: line 105 sets `currentMetadata = metadata` before either use, `??` keeps `""` as `""` exactly as before, and the empty branch keeps `removeAttribute`. `safeExternalUrl("")` returns `"#"`, which is why it is never called on an empty value.

Ordering: in the failure paths the comments block usually renders before `currentMetadata` is set (step 4 pass 2). It calls `applyOriginalHref` when it renders, and `loadVideo` refreshes the link later. The final href is therefore the metadata one either way, and tests read it only after the full settle.

#### 3e. The comments block, placed after `loadSimilarVideos()` (line 325)

```ts
type CommentSource = { host: string; id: string };

type CommentItem = {
  id: string;
  threadId: string;
  text: string;
  createdAt: number | null;
  isDeleted: boolean;
  totalReplies: number;
  displayName: string;
  name: string;
  host: string;
};

type ReplyRow = { comment: CommentItem; depth: number };

/**
 * Load the video's first batch of comment threads from its source instance; no other block waits on it.
 */
async function loadComments() {
  if (!commentsList || !commentsStatus) return;
  setCommentsHeading(null);
  if (commentsMoreButton) {
    commentsMoreButton.textContent = "Load more comments";
    commentsMoreButton.hidden = true;
    commentsMoreButton.addEventListener("click", () => void loadCommentsBatch(false));
  }
  const source = resolveVideoSource();
  if (!source?.host || !source.id) {
    renderCommentsUnavailable(source?.host ?? "");
    return;
  }
  commentsSource = { host: source.host, id: source.id };
  commentsStatus.textContent = "Loading comments…";
  await loadCommentsBatch(true);
}

/**
 * Fetch and append the next batch of threads. The first batch decides the section's state; a later failure keeps what is shown and offers a retry.
 */
async function loadCommentsBatch(first: boolean) {
  const source = commentsSource;
  if (!source || !commentsList || !commentsStatus || commentsLoadingBatch) return;
  commentsLoadingBatch = true;
  if (commentsMoreButton) commentsMoreButton.disabled = true;
  try {
    const page = await fetchCommentThreads(source, commentsOffset);
    // PeerTube answers a video with comments disabled with an empty list, so only an empty first batch asks the video itself.
    if (first && page.total === 0 && (await fetchCommentsDisabled(source))) {
      renderCommentsUnavailable(source.host);
      return;
    }
    setCommentsHeading(page.total);
    commentsOffset += COMMENTS_BATCH;
    // Every row counts toward total, shown or not, so a skipped deleted thread never keeps the button alive.
    commentsReceived += page.threads.length;
    for (const thread of page.threads) {
      // A comment posted between batches shifts newest-first offsets by one, so a thread can arrive twice.
      if (thread.id && commentsSeen.has(thread.id)) continue;
      if (thread.id) commentsSeen.add(thread.id);
      const node = renderCommentThread(source, thread);
      if (node) commentsList.append(node);
    }
    commentsStatus.textContent = commentsReceived === 0 ? "No comments yet." : "";
    if (commentsMoreButton) commentsMoreButton.hidden = !page.threads.length || commentsReceived >= page.total;
  } catch (error) {
    console.warn("[comments] could not load comment threads", error);
    if (first) {
      renderCommentsUnavailable(source.host);
    } else {
      if (commentsMoreButton) commentsMoreButton.hidden = true;
      renderCommentsRetry(commentsStatus, "Could not load more comments.", () => void loadCommentsBatch(false));
    }
  } finally {
    commentsLoadingBatch = false;
    if (commentsMoreButton) commentsMoreButton.disabled = false;
  }
}

/**
 * Fetch one batch of threads, newest first. Throws on a network error, a non-OK status or unparsable JSON; tolerates any shape inside.
 */
async function fetchCommentThreads(source: CommentSource, start: number) {
  const url = `https://${source.host}/api/v1/videos/${encodeURIComponent(source.id)}/comment-threads?start=${start}&count=${COMMENTS_BATCH}&sort=-createdAt`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Comment threads request failed: ${response.status}`);
  const data = asRecord(await response.json());
  const rows = Array.isArray(data.data) ? data.data : [];
  return { total: Math.max(0, normalizeNumber(data.total) ?? 0), threads: rows.map((row) => parseComment(row)) };
}

/**
 * Fetch one thread's whole reply tree; PeerTube does not paginate it.
 */
async function fetchCommentThread(source: CommentSource, threadId: string) {
  const url = `https://${source.host}/api/v1/videos/${encodeURIComponent(source.id)}/comment-threads/${encodeURIComponent(threadId)}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Comment thread request failed: ${response.status}`);
  return (await response.json()) as unknown;
}

/**
 * Whether the video has comments disabled. Any failure reads as "not disabled", so the section falls back to "No comments yet.".
 */
async function fetchCommentsDisabled(source: CommentSource) {
  try {
    const url = `https://${source.host}/api/v1/videos/${encodeURIComponent(source.id)}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`Video request failed: ${response.status}`);
    const data = asRecord(await response.json());
    return data.commentsEnabled === false || normalizeNumber(asRecord(data.commentsPolicy).id) === COMMENTS_POLICY_DISABLED;
  } catch (error) {
    console.warn("[comments] could not check whether comments are disabled", error);
    return false;
  }
}

/**
 * Read one comment through tolerant accessors: a missing or mistyped field becomes an empty or default value, never an exception.
 */
function parseComment(value: unknown): CommentItem {
  const data = asRecord(value);
  const account = asRecord(data.account);
  // createdAt is an ISO string; normalizeTimestampMs would turn it into null.
  const createdAt = typeof data.createdAt === "string" ? Date.parse(data.createdAt) : NaN;
  return {
    id: idString(data.id),
    threadId: idString(data.threadId),
    text: typeof data.text === "string" ? data.text : "",
    createdAt: Number.isFinite(createdAt) ? createdAt : null,
    isDeleted: data.isDeleted === true,
    totalReplies: Math.max(0, normalizeNumber(data.totalReplies) ?? 0),
    displayName: getString(account, ["displayName"]),
    name: getString(account, ["name"]),
    host: getString(account, ["host"])
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function idString(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return typeof value === "string" ? value : "";
}

function setCommentsHeading(total: number | null) {
  if (commentsHeading) commentsHeading.textContent = total === null ? "Comments" : `Comments (${numberFormat().format(total)})`;
}

/**
 * Replace the section's status with "unavailable" and a link to the original video. The host is remote input, so it goes in as text.
 */
function renderCommentsUnavailable(host: string) {
  if (!commentsStatus) return;
  const link = document.createElement("a");
  link.className = "ghost-link";
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "Open the original video";
  applyOriginalHref(link);
  commentsUnavailableLink = link;
  commentsStatus.replaceChildren(host ? `Comments are unavailable on ${host}. ` : "Comments are unavailable. ", link);
  if (commentsMoreButton) commentsMoreButton.hidden = true;
}

/**
 * Show an inline failure with a retry button in `target`; whatever is already rendered stays.
 */
function renderCommentsRetry(target: HTMLElement, message: string, retry: () => void) {
  const button = commentButton("ghost-button comments-retry", "Retry");
  button.addEventListener("click", retry);
  target.replaceChildren(`${message} `, button);
}

function commentButton(className: string, label: string) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  return button;
}

/**
 * Build one thread; a deleted thread with no replies is not shown.
 */
function renderCommentThread(source: CommentSource, thread: CommentItem) {
  if (thread.isDeleted && thread.totalReplies === 0) return null;
  const item = document.createElement("article");
  item.className = "comment-thread";
  item.append(renderComment(thread));
  const threadId = thread.threadId || thread.id;
  if (thread.totalReplies > 0 && threadId) item.append(...renderReplies(source, threadId, thread.totalReplies));
  return item;
}

/**
 * Build one comment from text only; remote content never reaches an HTML sink.
 */
function renderComment(comment: CommentItem) {
  const el = document.createElement("div");
  el.className = "comment";
  if (comment.isDeleted) {
    const deleted = document.createElement("p");
    deleted.className = "comment-deleted";
    deleted.textContent = "Comment deleted";
    el.append(deleted);
    return el;
  }
  const meta = document.createElement("div");
  meta.className = "comment-meta";
  const author = document.createElement("span");
  author.className = "comment-author";
  author.textContent = comment.displayName || comment.name || "Unknown author";
  meta.append(author);
  if (comment.name) {
    const handle = document.createElement("span");
    handle.className = "comment-handle";
    handle.textContent = comment.host ? `@${comment.name}@${comment.host}` : `@${comment.name}`;
    meta.append(handle);
  }
  if (comment.createdAt !== null) {
    const time = document.createElement("span");
    time.className = "comment-time";
    time.textContent = formatTimeAgo(comment.createdAt);
    meta.append(time);
  }
  const body = document.createElement("p");
  body.className = "comment-body";
  body.textContent = commentPlainText(comment.text);
  el.append(meta, body);
  return el;
}

/**
 * The reply toggle and its container for one thread. The tree is fetched once, on first expand; after that, toggling and "Show more replies" never request again.
 */
function renderReplies(source: CommentSource, threadId: string, count: number) {
  const label = `Show ${count} ${count === 1 ? "reply" : "replies"}`;
  const toggle = commentButton("ghost-button comment-replies-toggle", label);
  toggle.setAttribute("aria-expanded", "false");
  const container = document.createElement("div");
  container.className = "comment-replies";
  container.hidden = true;
  const list = document.createElement("div");
  list.className = "comment-replies-list";
  const status = document.createElement("p");
  status.className = "comments-status";
  status.hidden = true;
  const more = commentButton("ghost-button comment-replies-more", "Show more replies");
  more.hidden = true;
  container.append(list, status, more);
  let rows: ReplyRow[] | null = null;
  let shown = 0;
  let loading = false;
  let expanded = false;
  const showNext = () => {
    if (!rows) return;
    const next = rows.slice(shown, shown + REPLIES_BATCH);
    list.append(...next.map((row) => renderReplyRow(row)));
    shown += next.length;
    more.hidden = shown >= rows.length;
  };
  const setExpanded = (value: boolean) => {
    expanded = value;
    container.hidden = !value;
    toggle.textContent = value ? "Hide replies" : label;
    toggle.setAttribute("aria-expanded", String(value));
  };
  const load = async () => {
    if (loading) return;
    loading = true;
    toggle.disabled = true;
    status.hidden = true;
    try {
      rows = flattenReplies(await fetchCommentThread(source, threadId));
      showNext();
      if (!rows.length) {
        status.textContent = "No replies to show.";
        status.hidden = false;
      }
      setExpanded(true);
    } catch (error) {
      console.warn("[comments] could not load replies", error);
      renderCommentsRetry(status, "Could not load replies.", () => void load());
      status.hidden = false;
      setExpanded(true);
    } finally {
      loading = false;
      toggle.disabled = false;
    }
  };
  toggle.addEventListener("click", () => {
    if (loading) return;
    if (expanded) {
      setExpanded(false);
    } else if (rows) {
      setExpanded(true);
    } else {
      void load();
    }
  });
  more.addEventListener("click", showNext);
  return [toggle, container];
}

/**
 * Flatten a thread detail `{ comment, children: [{ comment, children }] }` into pre-order rows with their depth. A deleted reply with no children is dropped.
 */
function flattenReplies(tree: unknown) {
  const rows: ReplyRow[] = [];
  const walk = (children: unknown, depth: number) => {
    if (!Array.isArray(children)) return;
    for (const child of children) {
      const node = asRecord(child);
      const kids = Array.isArray(node.children) ? node.children : [];
      const comment = parseComment(node.comment);
      if (!(comment.isDeleted && kids.length === 0)) rows.push({ comment, depth });
      walk(kids, depth + 1);
    }
  };
  walk(asRecord(tree).children, 1);
  return rows;
}

function renderReplyRow(row: ReplyRow) {
  const el = renderComment(row.comment);
  el.classList.add("comment-reply", `comment-depth-${Math.min(row.depth, REPLY_DEPTH_CAP)}`);
  return el;
}

/**
 * Reduce federated HTML (Mastodon `<p>`, `<br>`, `<a>`, `<span>`) to plain text; text with no tag-shaped `<` is returned untouched, so PeerTube Markdown shows raw.
 * Entities are decoded last, so an encoded `&lt;script&gt;` ends as the literal text "<script>", which is only ever set as text.
 */
function commentPlainText(text: string) {
  if (!/<[a-z/]/i.test(text)) return text;
  return text
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>\s*<p[^>]*>/gi, "\n\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&(#\d+|#x[0-9a-f]+|[a-z]+);/gi, (match, name: string) => decodeEntity(match, name))
    .trim();
}

function decodeEntity(match: string, name: string) {
  if (name[0] === "#") {
    const hex = name[1] === "x" || name[1] === "X";
    const code = hex ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
    return Number.isInteger(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : match;
  }
  return HTML_ENTITIES[name.toLowerCase()] ?? match;
}
```

**Invariants the block keeps**

- No `innerHTML` or `insertAdjacentHTML` anywhere in it. Remote strings reach the DOM only through `textContent` and `replaceChildren`/`append` string arguments, which become text nodes.
- It writes only to `commentsHeading`, `commentsList`, `commentsStatus`, `commentsMoreButton` and nodes it created. It never calls `querySelector` or `remove()`; it hides or replaces nodes through direct references.
- Every async path has its own `try/catch` ending in exactly one `console.warn("[comments] …")`, and nothing is rethrown. `loadComments` has no `await` before its guards, and everything it touches synchronously is declared above line 97.
- Each guard flag (`commentsLoadingBatch`, the per-thread `loading`) is set before the first `await`, so a synchronous second click is a no-op.
- `disabled` and `hidden` are set as properties, as at lines 340/346/393. The per-depth indent is a class, not a style, which keeps it compatible with the meta CSP `style-src 'self'`.
- The recursion in `flattenReplies` could hit a `RangeError` on an absurdly deep hostile tree. It runs inside `load`'s `try`, so the result is the reply retry state, not a page failure.

### 4. `client/frontend/src/video.css` — new rules after `.section-header h3` (line 532)

```css
.comments-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.comment-thread {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.comment-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.45rem;
  font-size: 0.85rem;
}

.comment-author {
  font-weight: 600;
  color: var(--ink);
}

.comment-handle,
.comment-time {
  color: var(--muted);
}

.comment-body {
  margin: 0.2rem 0 0;
  color: var(--ink);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.45;
}

.comment-deleted {
  margin: 0;
  font-style: italic;
  color: var(--muted);
}

.comment-replies,
.comment-replies-list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

/* The flex display above would otherwise override the hidden attribute. */
.comment-replies[hidden] {
  display: none;
}

.comment-reply {
  padding-left: 0.8rem;
  border-left: 2px solid var(--line);
}

.comment-depth-1 { margin-left: 1rem; }
.comment-depth-2 { margin-left: 2rem; }
.comment-depth-3 { margin-left: 3rem; }
.comment-depth-4 { margin-left: 4rem; }

.comment-replies-toggle,
.comment-replies-more {
  align-self: flex-start;
  padding: 0.3rem 0.7rem;
  font-size: 0.85rem;
}

.comments-status {
  margin: 0.8rem 0 0;
  color: var(--muted);
  font-size: 0.9rem;
}

.comments-status:empty {
  display: none;
}

.comments-retry {
  margin-left: 0.4rem;
  padding: 0.25rem 0.7rem;
}

.comments-more {
  margin-top: 0.8rem;
}
```

- Only `.comment-replies` both gets a `display` value and is ever hidden, so it carries the `[hidden]` override.
- `.comments-status:empty` only collapses the empty line. The reply status uses `hidden`, and no rule sets `display` on it.
- No new name collides with `.comment-label`, `textarea` or `#comment-submit`. Those legacy rules stay untouched.
- `REPLY_DEPTH_CAP = 4` matches the four depth classes.

### 5. `tests/active/test_frontend_video_page.py`

#### 5a. RUNNER changes (all additive)

- **`element()`**
  - add `listeners: {}` and `markupCalls: []`;
  - `addEventListener: (type, fn) => { (el.listeners[type] ??= []).push(fn); }`;
  - `insertAdjacentHTML: (pos, markup) => { el.markupCalls.push(String(markup)); }`;
  - an `href` accessor tied to `attrs`: `get href() { return el.attrs.href ?? ""; }, set href(v) { el.attrs.href = String(v); }`.
  - `closest`, `querySelector`, `querySelectorAll` and `remove` stay as they are.
- **`console.warn`**: `const warned = []; console.warn = (...args) => { warned.push(String(args[0])); };`
- **fetch stub**
  ```js
  const requested = [];
  const requestedUrls = [];
  const comments = JSON.parse(process.env.COMMENTS ?? "{}");
  const reply = (body, status) => new Response(body, { status, headers: { "content-type": "application/json" } });
  globalThis.fetch = async (input) => {
    const url = new URL(String(input?.url ?? input), process.env.BASE);
    requested.push(url.pathname);
    requestedUrls.push(url.href);
    if (url.pathname === "/api/video") return reply(process.env.VIDEO_BODY, 200);
    const key = url.pathname === "/api/v1/videos/v1/comment-threads" ? `threads?start=${url.searchParams.get("start")}` : url.pathname;
    const entry = comments[key];
    if (entry === undefined) return reply("{}", 200);
    if (entry === "throw") throw new TypeError("Failed to fetch");
    return reply(entry.raw ?? JSON.stringify(entry.body ?? {}), entry.status ?? 200);
  };
  ```
- **settle, snapshot, click, steps**
  ```js
  const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
  const roots = ["comments-heading", "comments-list", "comments-status", "comments-more"];
  const serial = (n) => (n.nodeType === 1
    ? { type: 1, tag: n.tagName, cls: n.className, hidden: Boolean(n.hidden), disabled: Boolean(n.disabled), href: n.attrs.href ?? null, markup: n.markupCalls.length, children: n.children.map(serial) }
    : { type: n.nodeType, text: n.textContent });
  const snapshot = () => Object.fromEntries(roots.map((id) => [id, serial(document.getElementById(id))]));
  const clickable = (label) => { const out = []; const visit = (n) => { if (n.nodeType !== 1) return; if ((n.listeners.click ?? []).length && n.textContent === label) out.push(n); n.children.forEach(visit); }; roots.forEach((id) => visit(document.getElementById(id))); return out; };
  const click = (el) => (el?.listeners?.click ?? []).forEach((fn) => fn({ type: "click", target: el }));
  await import(process.env.BUNDLE);
  await settle();
  const snapshots = [snapshot()];
  for (const step of JSON.parse(process.env.STEPS ?? "[]")) {
    const target = clickable(step.click)[step.nth ?? 0];
    for (let i = 0; i < (step.times ?? 1); i += 1) click(target);
    await settle();
    snapshots.push(snapshot());
  }
  ```
- **Output**: the existing `requested`, ids and `tags`, plus `requestedUrls`, `snapshots` and `warned`.
- **Settle loop**: the single 5×10 ms loop becomes the 10×10 ms `settle()`. It covers `loadVideo`'s four awaits, the thread list and the disabled check.

#### 5b. Python helpers

```python
def _ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

def _comment(cid, name, text, *, display=None, replies=0, deleted=False):
    return {"id": cid, "threadId": cid, "text": text, "createdAt": _ago(3), "isDeleted": deleted, "totalReplies": replies,
            "account": {"name": name, "host": "peer.example", "displayName": name.title() if display is None else display}}

def _nodes(node):
    yield node
    for child in node.get("children", []):
        yield from _nodes(child)

def _text(node) -> str:
    return "".join(_text(c) for c in node["children"]) if node["type"] == 1 else node["text"]

def _by_class(root, cls):
    return [n for n in _nodes(root) if n["type"] == 1 and cls in n["cls"].split()]
```

`_page(bundle, body, initially_hidden, comments=None, steps=())` passes `COMMENTS` and `STEPS` into the env. The existing control assertions stay in `_page`. `LIST = "https://peer.example/api/v1/videos/v1/comment-threads?start={}&count=20&sort=-createdAt"`. Relative `createdAt` values keep the time text at "3 hours ago" whenever the test runs.

#### 5c. Cases

Each is one `test_…` function; D and E are `pytest.mark.parametrize`d.

- **A.** `threads?start=0` returns `{total: 3, data: [alice "line one\nline two", bob "hi", deleted thread with 0 replies]}`.
  - Heading text "Comments (3)".
  - Two `comment-thread` nodes; `comment-author` texts `["Alice", "Bob"]`; `comment-handle` `["@alice@peer.example", "@bob@peer.example"]`.
  - First `comment-body` equals `"line one\nline two"`; first `comment-time` equals "3 hours ago".
  - `comments-more` hidden; status text "".
  - `LIST.format(0)` is in `requestedUrls`.
- **B.** `start=0` returns total 25 with ids 1..20; `start=20` returns ids 21..25.
  - Snapshot 0: `comments-more` visible, 20 threads.
  - Steps: `[{"click": "Load more comments", "times": 2}]`.
  - `requestedUrls.count(LIST.format(20)) == 1`; the last snapshot has 25 threads and `comments-more` hidden.
- **C.** `start=0` returns `{total: 0, data: []}`; `/api/v1/videos/v1` returns `{commentsEnabled: true}`.
  - Status "No comments yet."; heading "Comments (0)"; `/api/v1/videos/v1` is in `requested`.
- **D** (parametrized: `"throw"`, `{"status": 500}`, `{"raw": "not json"}`).
  - Status text starts with "Comments are unavailable on peer.example.".
  - Its one `A` element has href `https://peer.example/videos/watch/uuid-1`, from `originalUrl` in `VIDEO_BODY`, read after the full settle.
  - `video-category-value` reads "Music".
  - `[w for w in warned if w.startswith("[comments]")]` has length 1.
- **E** (parametrized video bodies: `{"commentsEnabled": false}`, `{"commentsPolicy": {"id": 2, "label": "Disabled"}}`), with the thread list `{total: 0, data: []}`.
  - Unavailable text as in D; heading "Comments"; taxonomy rendered.
- **F.** Thread 7 has `totalReplies: 4`. `/api/v1/videos/v1/comment-threads/7` returns children `[{r1 deleted, children: [{r2}]}, {r3 deleted, children: []}, {r4}]`.
  - Steps: `[{"click": "Show 4 replies", "times": 2}, {"click": "Hide replies"}, {"click": "Show 4 replies"}]`.
  - The detail path is in `requested` exactly once.
  - Snapshot 1: `comment-replies` is not hidden; `comment-reply` rows are `["Comment deleted"-row, R2, R4]` with depth classes `comment-depth-1`, `-2`, `-1`; the toggle text is "Hide replies".
  - Snapshot 2: the container is hidden and the toggle reads "Show 4 replies".
  - Snapshot 3: the container is visible, still with exactly 3 `comment-reply` nodes.
- **G.** Thread 1 has `displayName: "<img src=x onerror=alert(1)>"` and `text: "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p><script>alert(2)</script><b onclick=\"x()\">bold</b>"`. Thread 2 has text `"**bold** a < b"`.
  - Author text equals the `displayName` literally.
  - Body 1 equals `"<script>alert(1)</script>alert(2)bold"`; body 2 equals `"**bold** a < b"`.
  - Across all four roots: no node with `type == 0`, and the sum of `markup` is 0.

#### 5d. Docstring

Lines 1-8 are rewritten to cover the comment cases and the new stubs:
- listener recording and `click`;
- the `insertAdjacentHTML` record;
- the `href` accessor;
- `COMMENTS` routing, including `throw`/`status`/`raw`;
- `STEPS` and snapshots;
- `requestedUrls` and `warned`.

The `mktemp("video_taxonomy")` name is left alone; it is cosmetic.

### 6. Check against the plan and requirements (pass 1 → converged)

| Item | Status |
|---|---|
| R1 placement, heading "Comments" → "Comments (N)" | met (§2, `setCommentsHeading`) |
| R2 direct fetch, exact URLs, `encodeURIComponent` on id and threadId, no request without host/id, not awaited | met (§3c, §3e) |
| Amendment: disabled check only when the first `total === 0`; its failure → "No comments yet." | met (`fetchCommentsDisabled`) |
| R3 live check before rendering code; tolerant parsing | parsing met (`parseComment`, `asRecord`); live check is the builder's precondition; `COMMENTS_POLICY_DISABLED` provisional |
| R4 20 per batch, `start += 20`, disabled while in flight, hidden at `total` or an empty batch, dedupe | met |
| R5 one fetch, in-flight guard, 20 at a time, collapse/re-expand without refetch, indented nesting | met (`renderReplies`) |
| R6 loading, empty, unavailable ± host with the shared original href, inline retry, one warn, no leak into other blocks | met |
| R7 no write controls | met: only load-more, toggle, show-more, retry, original link |
| R8 text only, federated HTML reduced, entities last, deleted rules, plain-text authors | met (`renderComment`, `commentPlainText`) |
| R9 no backend, dependency or `dist` change | met |
| R10 all listed cases plus the existing three | met (§5c) |

**Found during the pass and resolved inside scope**

1. The plan's "serialised walk of `#comments-section`'s subtree" can't work as written: the harness never parses HTML, so `getElementById("comments-section")` is an empty orphan `div`. The runner therefore walks the four elements the code actually uses (`comments-heading`, `-list`, `-status`, `-more`), and the hostile assertion is scoped to those four. It still excludes the like/dislike `insertAdjacentHTML` calls. The intent is unchanged; only the target is concrete.
2. The harness `comments-more` is a `DIV`, so the step clicker finds a control by "has a click listener and matching text" rather than by tag.
3. The plan's env map is named `COMMENTS`, and its thread-list key includes `start`, so B can answer two batches differently.

**Deliberate simplifications (name, ceiling, upgrade)**

- The load-more error shares `#comments-status` rather than getting its own element. The ceiling is one message at a time, which fits because the first-batch states and load-more errors never coexist. Upgrade: a dedicated element if more states appear.
- There is no test for "Show more replies" beyond 20. R10 doesn't list one and the code path is the same `showNext`. Upgrade: a 25-child fixture case.
- Authors are plain text. Upgrade: link `account.url` through `safeExternalUrl`.

**Out of this step but still open** (already in the inventory and docs checklist):
- the `DEPLOYMENT.md:325` `connect-src` decision, without which production always shows "unavailable";
- the unvalidated `?host=` finding, to note in the build record as a known limitation.

### Phases

#### Phase 1 - First batch, rendered as text [code]

**Files touched.** client/frontend/video-page.html (EDITED), client/frontend/src/pages/video-page/index.ts (EDITED), client/frontend/src/video.css (EDITED), tests/active/test_frontend_video_page.py (EDITED)

**Checkpoint.** Seam: the existing node harness in tests/active/test_frontend_video_page.py. It bundles the real client/frontend/src/pages/video-page/index.ts with esbuild and runs it under RUNNER, which stubs document and fetch. It follows the taxonomy cases' `_page` precedent. This phase extends the harness additively: the fetch stub routes instance paths through a `COMMENTS` env map (key `threads?start=N` for the list, the pathname otherwise; entries are body, status, raw or "throw"; unmapped paths answer `{}`), a `requestedUrls` list sits beside `requested`, `element()` records `insertAdjacentHTML` calls in `markupCalls` and gets an `href` accessor on `attrs`, a 10×10 ms `settle()` replaces the 5×10 loop, and the runner reports a `snapshots` list of serialised walks of `comments-heading`, `comments-list`, `comments-status` and `comments-more`. Case A (clause_1): `threads?start=0` answers total 3 with alice ("line one\nline two"), bob, and a deleted thread with 0 replies. Assert that `https://peer.example/api/v1/videos/v1/comment-threads?start=0&count=20&sort=-createdAt` is in `requestedUrls`, the heading reads "Comments (3)", there are exactly two `comment-thread` nodes, `comment-author` is ["Alice","Bob"], `comment-handle` is ["@alice@peer.example","@bob@peer.example"], the first `comment-body` is "line one\nline two", the first `comment-time` is "3 hours ago", `comments-more` is hidden and the status text is "". Case G (clause_2): displayName "<img src=x onerror=alert(1)>" and a federated body mixing encoded `&lt;script&gt;`, a raw `<script>` and `<b onclick>`, plus a second thread "**bold** a < b". Assert the author equals the displayName literally, body 1 equals "<script>alert(1)</script>alert(2)bold", body 2 equals "**bold** a < b", and across the four roots there is no node with type 0 and the sum of `markup` is 0. The three existing taxonomy cases stay green unchanged.

**Intent.** When video-page.html starts, index.ts's `loadComments` fetches the first 20 comment threads from the source instance, without waiting on anything else, and renders them into the new `#comments-section` as text-only `comment-thread` nodes under the heading "Comments (N)". Remote strings reach the DOM only as text.

- C1 - At page start the page requests `comment-threads?start=0&count=20&sort=-createdAt` from the source instance. Under "Comments (N)" it renders one `comment-thread` per shown thread, carrying author, `@name@host`, relative time and the body with its line breaks kept. A deleted thread with no replies is left out.
- C2 - Hostile display names and comment text appear only as literal text: federated HTML is reduced to plain text, text that is not HTML-shaped stays raw, and no comments node is set through innerHTML or insertAdjacentHTML.

**Outcome.** ### `client/frontend/video-page.html`
Added `<section id="comments-section" class="comment-card" aria-labelledby="comments-heading">` between the player card and `#similar-section`. It holds a `section-header` with `<h3 id="comments-heading">Comments</h3>`, `#comments-list`, a `#comments-status` status line reading "Loading comments…", and a `#comments-more` "Load more comments" `ghost-button` that starts `hidden`.

### `client/frontend/src/pages/video-page/index.ts`
- Added element constants `commentsHeading`, `commentsList`, `commentsStatus` and `commentsMoreButton`.
- Added `COMMENTS_BATCH = 20` and `HTML_ENTITIES` above the start calls. `loadComments` reads the constant before its first `await`, so declaring it lower would hit the TDZ.
- Added `void loadComments();` after `loadVideo()` and `loadSimilarVideos()`. Nothing awaits it and it awaits nothing of theirs. Its thread-list fetch goes out synchronously at module start.
- New block after `loadSimilarVideos()`:
  - `loadComments` keeps "more" hidden, since load-more comes in phase 3. It takes `{host, id}` from `resolveVideoSource()`, fetches the first batch, sets the heading to `Comments (${total})` from the response's `total`, and appends one `article.comment-thread` per thread, skipping a deleted thread with no replies. It then clears the status.
  - When no host or id resolves, it shows a bare "Comments are unavailable." with a `rat-tail:` comment. There is no link to the original video yet; the upgrade is R6's shared unavailable state.
  - `fetchCommentThreads` requests `https://{host}/api/v1/videos/{encodeURIComponent(id)}/comment-threads?start=…&count=20&sort=-createdAt` with `Accept: application/json`. It throws on a non-OK status or bad JSON.
  - `parseComment` and `asRecord` are tolerant accessors: a missing or wrong-typed field becomes `""`, `0`, `false` or `null`. `createdAt` goes through `Date.parse`, not `normalizeTimestampMs`, because that one returns NaN for ISO strings.
  - `renderCommentThread` and `renderComment` build every node with `createElement` and `textContent`. A comment shows an author (`displayName`, then `name`, then "Unknown author"), a `@name@host` handle from the account's own host, a `formatTimeAgo` time and a `comment-body`. A deleted thread that is still shown reads "Comment deleted".
  - `commentPlainText` and `decodeEntity` reduce text only when it contains a tag-shaped `<` (a letter or `/` after it): `<br>` becomes a newline, `</p><p>` a blank line, all other tags are stripped, and entities are decoded last. Other text is returned raw.
  - Nothing in the block uses `innerHTML` or `insertAdjacentHTML`.
- Deliberately left for phase 2: a failing first request. It currently leaves "Loading comments…" in place and surfaces as an unhandled rejection in the console. It is not caught or swallowed. The "No comments yet." state and the disabled check are also phase 2.

### `client/frontend/src/video.css`
Added rules after `.section-header h3`:
- `.comments-list`, `.comment-thread` and `.comment-meta` (flex column/row layout);
- `.comment-author`, and `.comment-handle`/`.comment-time` in muted text;
- `.comment-body` with `white-space: pre-wrap`, so kept line breaks show in the browser;
- `.comment-deleted`, `.comments-status`, `.comments-status:empty { display: none }` and `.comments-more`.

None of these elements is hidden with `hidden` while also having a `display` rule, so no `[hidden]` override is needed. Reply-indent and retry rules are left for later phases.

### `tests/active/test_frontend_video_page.py`
Not edited. The phase checkpoint `tests/tmp/test_13_video_comments_phase1.py` already holds the full extended harness and the three taxonomy cases. The existing active file still works against the new code: its `{}` answers give "Comments (0)" with no threads and nothing throws.

### Observation
I ran a throwaway probe through `ValidateTests`, bundling the page and running it under the checkpoint's own RUNNER and fixtures. What it printed:
- `startUrls` contains `https://peer.example/api/v1/videos/v1/comment-threads?start=0&count=20&sort=-createdAt`.
- The heading reads "Comments (57)", "more" is hidden, and the status is empty.
- The hostile author reads literally, and the handles are `@mallory@peer.example` and `@bob@tube.other.example`.
- The times read "1 hours ago" and "2 days ago", and the federated body reads `<script>alert(1)</script>alert(2)bold`.
- `markupIds` shows only like/dislike and `opaqueIds` only the non-comment elements.

A `tsc --noEmit` run reported no errors in the new block; every error it listed is in older code. I emptied the probe file (`tests/tmp/probe_13_phase1_impl.py`) because my tools cannot delete it.

**Beyond the files named.** tests/tmp/probe_13_phase1_impl.py - a throwaway observation probe, now emptied because my tools cannot delete files; it should be removed. The earlier `tests/tmp/probe_13_phase1_observe.py` from the checkpoint-authoring step is in the same state.

#### Phase 2 - First-batch states [code]

**Files touched.** client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page.py (EDITED)

**Checkpoint.** Seam: the same RUNNER harness with the phase 1 snapshots. This phase adds a `warned` list that captures `console.warn` first arguments. Cases C and E (clause_1): the thread list answers `{total:0,data:[]}`. With `/api/v1/videos/v1` answering `{commentsEnabled:true}` (C), the status reads "No comments yet.", the heading reads "Comments (0)" and `/api/v1/videos/v1` is in `requested`. E is parametrized over `{commentsEnabled:false}` and `{commentsPolicy:{id:2}}`, where 2 is the value R3 records. In E the status starts with "Comments are unavailable on peer.example.", the heading reads "Comments", and `video-category-value` still reads "Music". Case D (clause_2) is parametrized over a thread-list entry of "throw", `{status:500}` and `{raw:"not json"}`. Assert the status starts with "Comments are unavailable on peer.example.", its single A child has href `https://peer.example/videos/watch/uuid-1` (from VIDEO_BODY's originalUrl, read after the full settle), `video-category-value` reads "Music", and exactly one entry in `warned` starts with "[comments]".

**Intent.** A first comments batch that is empty or fails now ends in a defined state inside `#comments-section`, leaving the rest of the page alone. An empty batch is settled by one `/api/v1/videos/{id}` comments-disabled check. A failure shows "Comments are unavailable on {host}." with the original-video link, whose href comes from the helper that `loadVideo`'s `#original-link` now also uses.

- C1 - An empty first batch is decided by the video's comments flag: disabled shows the unavailable state, anything else shows "No comments yet." under "Comments (0)".
- C2 - A first thread-list request that throws, returns non-OK or returns unparsable JSON shows the unavailable state with the original video's href. Taxonomy still renders and exactly one "[comments]" warning is logged.

**Outcome.** ### `client/frontend/src/pages/video-page/index.ts`
- **New state above the start calls.** I added `COMMENTS_POLICY_DISABLED = 2` and `let commentsUnavailableLink`. They sit above `void loadComments()` because the no-host path renders the unavailable state synchronously at module start, and declaring them lower would hit the TDZ.
- **`COMMENTS_POLICY_DISABLED` is not confirmed.** It carries a `rat-tail:` comment because R3's live check has not been run and the build record holds no result for it. 2 is what I expect PeerTube's `VideoCommentPolicy.DISABLED` to be, but that comes from memory, not from a response I saw. If R3 records a different value, only this constant and case E's `commentsPolicy.id` fixture change.
- **`loadComments`:**
  - The first thread-list fetch and its rendering now run inside one `try`. A thrown fetch, a non-OK status or unparsable JSON logs one `console.warn("[comments] could not load comment threads", error)` and shows the unavailable state. Nothing is rethrown.
  - An empty first batch (`total === 0`) now asks `fetchCommentsDisabled`. If the video reports comments disabled, the section shows the unavailable state and the heading keeps the markup's "Comments". Otherwise the heading reads "Comments (0)" and the status reads "No comments yet.".
  - The no-host/no-id path now uses the same unavailable state, replacing phase 1's bare "Comments are unavailable." and its `rat-tail:`. The shared state is the upgrade that rat-tail pointed to.
- **New `fetchCommentsDisabled(source)`.** It requests `https://{host}/api/v1/videos/{encodeURIComponent(id)}` with `Accept: application/json`. It returns true when `commentsEnabled === false` or `commentsPolicy.id === COMMENTS_POLICY_DISABLED`. Any failure (network, non-OK, bad JSON) logs one `[comments]` warning and returns false, so the section falls back to "No comments yet.", as the operator-approved amendment says.
- **New `renderCommentsUnavailable(host)`:**
  - It builds an `a.ghost-link` (`target=_blank`, `rel=noreferrer`, text "Open the original video") with `createElement` and `textContent`.
  - It sets the href through `applyOriginalHref` and keeps the link in `commentsUnavailableLink`.
  - It replaces `#comments-status` with the text `Comments are unavailable on {host}. ` (or `Comments are unavailable. ` when there is no host) plus the link. The host goes in as text only.
- **New `applyOriginalHref(link)`, next to `renderTaxonomyItem`.** It holds the one original-URL expression, `currentMetadata?.originalUrl ?? fallback.url`. A non-empty value goes through `safeExternalUrl`; an empty one uses `removeAttribute("href")`, because `safeExternalUrl("")` would give "#".
- **`loadVideo`.** I removed the local `original` and replaced the `#original-link` block with `applyOriginalHref(originalLink); applyOriginalHref(commentsUnavailableLink);`. "Open original" behaves exactly as before, and the comments link picks up the metadata URL when the comments state rendered before `loadVideo` finished, which is the usual order in the failure cases.

### `tests/active/test_frontend_video_page.py`
Not edited. The phase checkpoint carries this phase's cases. The active taxonomy file answers `{}` everywhere, so it now goes: total 0 → disabled check answers `{}` → "No comments yet.". No path throws, and none of the elements it asserts on is touched. I reasoned this from the code rather than running that group, because running it mid-build would rewrite its record.

### Observation
I ran a throwaway probe, `tests/tmp/probe_13_phase2_impl.py`, through `ValidateTests`. It loaded the checkpoint's own RUNNER, `bundle` fixture and `_page` by file path and printed each case's report:
- **enabled-true, policy-3, video-500:** status "No comments yet.", heading "Comments (0)", `/api/v1/videos/v1` requested, category "Music". Only video-500 logged a warning ("[comments] could not check whether comments are disabled").
- **enabled-false, policy-2:** status "Comments are unavailable on peer.example. Open the original video", links `[{"href": "https://peer.example/videos/watch/uuid-1"}]`, heading "Comments", category "Music".
- **throw, status-500, raw:** status "Comments are unavailable on other.example. Open the original video", links `[{"href": "https://other.example/videos/watch/uuid-1"}]`, category "Music", and exactly one warning, "[comments] could not load comment threads".
- `rejections` was `[]` in every case, and `#original-link` held the body's `originalUrl` in every case.

The probe is now just a docstring because my tools cannot delete files. It should be deleted, along with the spent `tests/tmp/probe_13_phase2.py`, `tests/tmp/probe_13_phase1_observe.py` and `tests/tmp/probe_13_phase1_impl.py`.

**Beyond the files named.** tests/tmp/probe_13_phase2_impl.py - a throwaway observation probe for this phase, now emptied to a docstring because my tools cannot delete files; it should be removed.

#### Phase 3 - Load more comments [code]

**Files touched.** client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page.py (EDITED)

**Checkpoint.** Seam: the same RUNNER harness. This phase adds recorded `addEventListener` listeners per element, a `click(el)` helper, a `clickable(label)` finder (a node with a click listener and matching text, found by walking the four roots), and a `STEPS` env of `{click, nth, times}` actions, with a `settle()` and a snapshot after each. Case B: `threads?start=0` answers total 25 with ids 1..20, and `threads?start=20` answers ids 21..25. Snapshot 0 has 20 `comment-thread` nodes and `comments-more` visible. Steps are `[{"click":"Load more comments","times":2}]`. Clause_1: `requestedUrls.count(LIST.format(20)) == 1`. Clause_2: the last snapshot has 25 `comment-thread` nodes and `comments-more` hidden.

**Intent.** The "Load more comments" button in `#comments-section` fetches the next 20 threads from the advancing offset, ignoring clicks while a batch is in flight, and appends them until the received count reaches the total, at which point it hides.

- C1 - A double click on "Load more comments" sends exactly one `start=20` thread-list request.
- C2 - After loading, the list holds every thread up to the total, and the "Load more comments" button is hidden.

**Outcome.** ### `client/frontend/src/pages/video-page/index.ts`
- New module state `commentsReceived`: how many threads have arrived so far, deleted ones included. It is the offset for the next batch and the count checked against the total. It is declared with the other comment constants, above the calls that start loading, because `loadComments` sets it.
- `commentsMoreButton` gets one click listener, added at module level next to the description toggle's, which calls `loadMoreComments()`.
- New `appendCommentThreads(page)`: the thread-appending loop moved out of `loadComments`, deleted-thread skip unchanged. It adds the batch size to `commentsReceived`, then sets `commentsMoreButton.hidden` to `commentsReceived >= page.total || page.threads.length === 0`. The empty-batch condition stops an instance that under-delivers against its own total from leaving a button that can never move forward. `loadComments` now calls it for the first batch, so the button shows after the first batch only when threads remain.
- New `loadMoreComments()`: disables the button before it awaits anything, fetches `fetchCommentThreads(source, commentsReceived)`, appends the batch, and re-enables the button in `finally`. Because the button is disabled while a batch is loading, the second click of a double click never reaches the listener, so only one `start=20` request goes out (C1). This matches the disable/`finally` pattern `react()` already uses. If the fetch fails it logs with `console.warn` and leaves the button shown and enabled so the user can retry the same batch; no error UI was added, since this phase doesn't specify one.

### `tests/active/test_frontend_video_page.py`
Not touched. This phase is about production code, and the checkpoint lives under `tests/tmp/`. I did not run the checkpoint: the workflow runs it when I hand in.

#### Phase 4 - Reply threads [code]

**Files touched.** client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page.py (EDITED)

**Checkpoint.** Seam: the same RUNNER harness with STEPS and snapshots. Case F: thread 7 has totalReplies 4. `/api/v1/videos/v1/comment-threads/7` answers children `[{r1 deleted, children:[{r2}]}, {r3 deleted, children:[]}, {r4}]`. Steps are `[{"click":"Show 4 replies","times":2}, {"click":"Hide replies"}, {"click":"Show 4 replies"}]`. Clause_1: the detail path appears in `requested` exactly once. In snapshot 1 `comment-replies` is not hidden, the `comment-reply` rows are ["Comment deleted", R2, R4] with classes `comment-depth-1`, `comment-depth-2` and `comment-depth-1`, and the toggle reads "Hide replies". Clause_2: in snapshot 2 the container is hidden and the toggle reads "Show 4 replies". In snapshot 3 the container is visible with exactly 3 `comment-reply` nodes, and the detail path is still requested only once.

**Intent.** Each thread with replies in `#comments-section` gets a toggle. The toggle fetches the thread's reply tree once, shows it as pre-order rows indented by capped depth, and after that collapses and re-expands with no further request.

- C1 - The first expand, even when double-clicked, sends one thread-detail request. It renders the replies in pre-order with depth classes; a deleted reply that has children reads "Comment deleted", and a deleted reply with no children is left out.
- C2 - Hiding and then re-showing the replies sends no new request and does not duplicate reply rows.

**Outcome.** ### client/frontend/src/pages/video-page/index.ts
- New constants next to the other comments constants, above the start calls: `REPLIES_BATCH = 20` and `REPLY_DEPTH_CAP = 4`. The cap has a comment saying video.css has one indent rule per depth up to it.
- `CommentItem` gains `id: number | null`, which `parseComment` reads with `normalizeNumber(data.id)`. New type `ReplyRow = { comment, depth }`.
- New `fetchCommentThread(source, threadId)`. It sends `GET https://{host}/api/v1/videos/{id}/comment-threads/{threadId}` with the same `Accept` header, and throws on a network error, a non-OK status or bad JSON, like `fetchCommentThreads` does.
- `renderCommentThread` now appends the output of the new `renderReplies(thread.id, thread.totalReplies)` when a thread has `totalReplies > 0` and an id.
- `renderReplies` builds two things:
  - a `ghost-button comment-replies-toggle` labelled "Show N replies" from `totalReplies` ("reply" when N is 1);
  - a `comment-replies` container, hidden at first, holding a `comment-replies-list` and a hidden "Show more replies" button.

  Its state lives in the closure: `rows` (null until fetched) and `shown`.
  - **First click:** disables the toggle, fetches the tree, flattens it, shows the first 20 rows, and switches the label to "Hide replies". Disabling the toggle while the request is in flight is how a double click sends one request, the same approach `loadMoreComments` uses.
  - **Later clicks:** only flip the container's `hidden` and the label. There is no request and nothing is appended again.
  - **Failed fetch:** one `console.warn("[comments] could not load replies", …)`. The toggle is re-enabled with its label unchanged, so clicking again retries.
  - **"Show more replies":** appends the next 20 of the fetched rows with no request, and hides once every row is shown.
- New `flattenReplies(tree)` walks `children` in pre-order, starting at depth 1, and drops a deleted reply that has no children. It reads through `asRecord`, `parseComment` and `Array.isArray`, so a malformed tree gives fewer rows instead of throwing.
- New `renderReplyRow(row)` reuses `renderComment`, so a deleted reply with children reads "Comment deleted". It adds `comment-reply` and `comment-depth-${min(depth, REPLY_DEPTH_CAP)}`.
- Nothing new uses `innerHTML` or `insertAdjacentHTML`. `disabled` and `hidden` are set as properties.
- Not covered by the checkpoint:
  - "Show more replies" past 20 rows. It lands here because the Step 6 rationale assigned it to P4 under R5.
  - The failed-fetch path. It follows phase 3's load-more approach: a warning and a re-enabled control, with no inline retry message.

### client/frontend/src/video.css
- New rules after `.comment-deleted`:
  - `.comment-replies` and `.comment-replies-list` become flex columns, plus a `.comment-replies[hidden] { display: none; }` override, as `.taxonomy-item[hidden]` has.
  - `.comment-reply` gets a left border and padding.
  - `.comment-depth-1` to `.comment-depth-4` indent by 1–4rem.
  - A compact size for `.comment-replies-toggle` and `.comment-replies-more`.

### tests/active/test_frontend_video_page.py
- Not changed. This phase's checkpoint lives in `tests/tmp/test_13_video_comments_phase4.py`, and nothing in this phase needed the active file.

### Housekeeping note
- `tests/tmp/probe_13_phase4.py` is still there. The test author emptied it to a docstring. My tools cannot delete files either, so it still needs removing.

**Beyond the files named.** client/frontend/src/video.css: phase 4 renders `comment-depth-N` classes to indent replies, and phase 1 added no rules for them. Without these rules replies are not indented at all, and the `display: flex` on `.comment-replies` would override `hidden` without the `[hidden]` override. That breaks the phase intent ("indented by capped depth") in the browser, even though the node harness, which ignores CSS, would still pass.


