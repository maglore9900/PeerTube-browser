# 12-similars-on-scroll

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/19-12-similars-on-scroll.record.md`._

## Requirements

### Purpose

Users keep browsing from the video page, and today it shows only 8 similar videos (`limit: "8"` in `loadSimilarVideos`, `client/frontend/src/pages/video-page/index.ts`). To see more, they must follow a link to a second page: the home feed in its up-next mode, `/videos.html?id=…&host=…` (`useSimilar` in `client/frontend/src/pages/videos/index.ts`). This build makes the video page itself offer a long list of up-next videos that loads as the user scrolls, the way the home page does, so they no longer need to leave it.

### Context delivered by earlier builds (not to be changed)

- Issue 09 (similars diversity) made every up-next response a random draw. A limit-48 request scores the seed's pool (at most `SIMILAR_VIDEO_TOP_K` = 300 rows), takes the top min(4 × 48 = 192, pool size) rows as the window, and draws 48 of them by score-weighted sampling. Two identical requests return different pages. The draw is described in `engine/server/api/recommendations/docs/OVERVIEW.md`. The Engine drops rows named in the request's `exclude` while it builds the pool, so a batch that excludes the rows already shown is drawn only from rows not yet shown.
- The Client backend (`client/backend/server.py`) caps a feed request's page size at `FEED_PAGE_SIZE` = 48 (`min(limit or 48, 48)`) and forwards `limit = page_size * FEED_OVERFETCH_FACTOR` (2) to the Engine, so it can refill a page after removing blocked rows. The Engine caps `limit` at 2 × `default_limit`. The Client refuses a feed request that excludes more than `MAX_FEED_EXCLUDE` = 500 videos.
- `createFeedPager` in `client/frontend/src/data/videos.ts` already pages a feed. Each batch excludes the last 500 rows shown (keyed by `video_id` + `instance_domain`) and drops any row the Engine repeats anyway. After a batch that adds no new row, or that fails, `exhausted` is set and `next()` makes no further request. `fetchSimilarVideosPayload(query, exclude)` is the fetch the home page gives it.
- Issue 11 (fast similars response) is archived. The video page already requests similars in parallel with the video's metadata.

### R1 — One full batch per request

- The video page requests up-next similars with `limit` 48 (the Client's `FEED_PAGE_SIZE`, equal to the Engine's `BATCH_SIZE`) instead of 8, through `fetchSimilarVideosPayload` with the seed's `id`, `host` and `apiBase`, as today.
- No server change is required: the Client and Engine already serve a 48-row draw in a single response.

### R2 — Progressive reveal from memory

- The page keeps every row it has fetched in memory and renders only a revealed prefix of them into `#similar-videos`.
- After the first batch arrives it reveals 8 cards, the same count the page shows today.
- Each time the user nears the bottom of the page, it reveals the next 8 rows, appending cards and not re-rendering the ones already shown. "Near the bottom" works as on the home page (`client/frontend/src/pages/videos/index.ts`): an `IntersectionObserver` on a sentinel element placed after the grid, with `rootMargin: "200px"`, plus a passive `scroll` listener and a `resize` listener as a fallback (near bottom = `innerHeight + scrollY >= scrollHeight - 240`).
- While the document is too short to scroll (`scrollHeight <= innerHeight + 120`) and unrevealed rows remain, it keeps revealing chunks until the page can scroll (bounded by a safety counter, as `maybeFillViewport` does on the home page).
- Live view counts (`queueSimilarStats`) are requested only for the cards being revealed, not for the whole in-memory batch.

### R3 — Paging past the first batch

- Fetching goes through `createFeedPager` (one pager per page load), passing a function that calls `fetchSimilarVideosPayload` with the seed query and the pager's `exclude` list. Every later batch therefore excludes the rows already shown (up to the last 500), and rows the Engine repeats are dropped.
- When a reveal finds no unrevealed rows left, the page asks the pager for the next batch, unless the pager is exhausted or a fetch is already in flight. New rows are appended to the in-memory list, and revealing continues. Because the sentinel may still be in view, it reveals at once and runs the fill-viewport step after appending, as the home page's `loadMoreVideos` does.
- Paging ends for this page view at the first batch that adds no new row or that fails. A failure on any batch after the first leaves the cards already shown in place and is only logged with `console.warn`. No error replaces the grid.

### R4 — Behaviour that stays as it is

- The first similars request still waits for the local-likes import (`localLikesImported`) before it is sent.
- If the first batch returns no rows, the grid shows `No similar videos found.`.
- If the first batch fails, the grid shows the error's message (fallback text `Failed to load similar videos`), HTML-escaped.
- If the first batch fails with `ProfileKeyRejectedError`, the grid shows `keyRejectedNotice` with a retry that reloads the similars from scratch, with a fresh pager and nothing shown.
- Without a `seedId`, `#similar-section` stays hidden and nothing is fetched.
- Cards keep today's markup and behaviour (`renderSimilarCard`): thumbnail, duration, title, channel, views and age, the liked or disliked badge from `cardReaction`, `data-video-key`, and a link to `/video-page.html?…` for that row.
- The metadata, reactions, block buttons and description behaviour of the page are untouched.

### R5 — Remove the links to the separate similar-videos page

- Remove the header nav link `<a id="similar-link" …>Similar videos</a>` and the section header link `<a id="similar-link-inline" …>Open full list</a>` from `client/frontend/video-page.html`, together with the code in `client/frontend/src/pages/video-page/index.ts` that looks them up and sets their `href`.
- The section keeps its `Similar videos` heading.
- `/videos.html?id=…&host=…` (the home page's `useSimilar` mode) stays working as it is, so old bookmarks still open. Nothing in the app links to it any more. This is a deliberate choice by the operator: links only, no removal of the mode and no redirect.
- `client/frontend/dist/` is build output and is not edited by hand.

### R6 — Replacement pager test

- Add a durable test in `tests/active` that replaces the retired `tests/archive/upnext_random_draw/test_frontend_videos.py`. Like the retired file, it bundles `client/frontend/src/data/videos.ts` with esbuild and runs it in node against the real Client and Engine, with minimal in-memory `window`, `localStorage` and `sessionStorage`.
- It drives `createFeedPager` over `fetchSimilarVideosPayload` for an up-next seed at limit 48, where the first batch has `seed.mode == "upnext"`, and asserts two things. First, no batch repeats a row (`video_id`, `instance_domain`) of any earlier batch, and the second batch is non-empty. Second, once a batch comes back empty, no later `next()` call makes a request, counted on the fetch function handed to the pager.
- It must hold under 09's random draw. There is no control asserting that two plain fetches return the same page. The seed and batch budget must actually reach an empty batch: a seed pool is at most 300 rows, so at 48 per batch about 7 batches exhaust it. Otherwise the test has to show that its seed's pool ends within the budget.
- Map the new test in `.un/skills/devsecops/config.json` to `client/frontend/src/data/videos.ts` (and to `client/backend/server.py`, which it runs through).
- Update `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` to record that the `test_frontend_videos` item is covered by this build, leaving its other five tests open.

### Baseline suite state

Before the build, the active suite (`tests/active`) passes: exit code 0, not a variant run. Record and output go to `tests/last_test_validation.json` and `tests/last_test_output.txt`. Working tests go in `tests/tmp`, retired ones in `tests/archive`, plans in `docs/project/plans`.

### Out of scope

- Any Engine or Client backend change to the up-next route, batch size, draw or exclude handling.
- Removing or redirecting the `/videos.html?id=` mode.
- The other five retired up-next tests tracked by issue 35.

## High-level plan

### Approach

The change is confined to the video page module (`client/frontend/src/pages/video-page/index.ts`), its HTML (`client/frontend/video-page.html`), one CSS rule in `client/frontend/src/video.css`, one new active test, one config entry and one issue note. No server file changes, and `createFeedPager` and `fetchSimilarVideosPayload` in `data/videos.ts` are used as they are.

**R1, one full batch per request.** `loadSimilarVideos` stops calling `fetchSimilarVideosPayload` directly with `limit: "8"`. It builds one pager per page load with `createFeedPager`, and the pager's fetch function calls `fetchSimilarVideosPayload` with `{ id: seedId, host: seedHost, limit: "48", apiBase }` and the `exclude` list the pager passes in. The Client caps the page at 48 and over-fetches 96 from the Engine, so each response is one full 48-row draw, as R1 states.

**R2, progressive reveal from memory.** The page keeps a small amount of module state next to the existing `similarStatsCache`: the rows fetched so far, how many are revealed, a `loading` flag for the first batch, a `fetchingMore` flag, and the current pager. One reveal function (the counterpart of the home page's `loadNextChunk`) moves the revealed count forward by 8 (a `SIMILAR_CHUNK` constant). It renders only the newly revealed slice with `renderSimilarCard`, appends it to `#similar-videos` with `insertAdjacentHTML("beforeend", …)` so earlier cards are never re-rendered, and calls `queueSimilarStats` on that slice only. The first render after the first batch uses `innerHTML` for the first 8 cards, which replaces the `Loading...` placeholder. The bottom is detected the same way as on the home page. A new `<div id="similar-sentinel" class="similar-sentinel" aria-hidden="true">` is placed right after `#similar-videos` inside `#similar-section`, watched by an `IntersectionObserver` with `rootMargin: "200px"`. A passive `scroll` listener and a `resize` listener run the same check (`innerHeight + scrollY >= scrollHeight - 240`), and resize also runs fill-viewport. The fill-viewport function copies `maybeFillViewport`: while unrevealed rows remain and `scrollHeight <= innerHeight + 120`, it reveals chunks, stopping at 50 or when a reveal changes nothing. It runs after the first render and after every appended batch. `video.css` gets a 1px-height `.similar-sentinel` rule, because the home page's `.feed-sentinel` rule lives in `videos.css`, which this page does not import.

**R3, paging past the first batch.** When the reveal function finds no unrevealed row, it calls a `loadMoreSimilar` modelled on the home page's `loadMoreVideos`. That function returns early while the first batch is loading, while a fetch is already running, or when `pager.exhausted` is set. Otherwise it awaits `pager.next()`, checks that the pager is still the current one, and appends the new rows to memory. On success it reveals right away and then runs fill-viewport, because the sentinel may still be in view and the observer would not fire again. On failure it calls `console.warn` and leaves the grid alone. The pager itself handles the stop rule: a batch with no new row, or a failed batch, sets `exhausted`, and after that no request is made.

**R4, unchanged behaviour.** The first `pager.next()` still runs after `await localLikesImported`. An empty first batch shows `No similar videos found.`. A failed first batch shows the escaped message or `Failed to load similar videos`. `ProfileKeyRejectedError` passes through the pager unchanged (it rethrows), so the `keyRejectedNotice` path stays. Its retry calls `loadSimilarVideos` again, and that function now starts by resetting the in-memory rows and the revealed count, setting `loading`, putting `Loading...` back in the grid and creating a fresh pager. With no `seedId`, the section is hidden and the function returns before any pager, observer or listener exists. `renderSimilarCard`, the stats helpers, metadata, reactions, block buttons and description code stay as they are.

**R5, link removal.** In the HTML I delete `<a id="similar-link">` from the header nav and `<a id="similar-link-inline">` from `.section-header`, and keep the `<h3>Similar videos</h3>`. In the module I delete the two `getElementById` constants, the top-level block that sets `similarLink.href`, and the block inside `loadSimilarVideos` that sets `similarLinkInline.href`. `pages/videos/index.ts` is not touched, so `/videos.html?id=…&host=…` keeps working. `dist/` is not edited.

**R6, replacement test.** A new `tests/active/test_frontend_upnext_pager.py` follows the retired file's harness: an esbuild ESM bundle of `createFeedPager` and `fetchSimilarVideosPayload` from `data/videos.ts`, a node runner with in-memory `window`, `localStorage` and `sessionStorage`, the `engine_client` fixture, and the `linux` search seed. Changes from the old file: the page size is `"48"`; the two plain-fetch control runs are removed, and the first pager batch's `seed.mode` is reported and checked to be `upnext` instead; the budget is `MAX_BATCHES = 10`. The assertions are: the first and second batches are non-empty and share no row; no batch repeats a `(video_id, instance_domain)` row from any earlier batch; an empty batch appears before the last call in the budget, which is what shows this seed's pool ends within the budget; the counted calls go 1…k up to the empty batch and do not increase after it. `.un/skills/devsecops/config.json` gets an entry mapping the test to `client/frontend/src/data/videos.ts` and `client/backend/server.py`. Issue 35 gets a comment saying the `test_frontend_videos` item is covered by this build's test, and its list item is marked as covered; the other five items stay open.

**Why the budget is 10.** From `engine/server/data/similarity_candidates.py`: `_build_rows` takes the top `SIMILAR_VIDEO_TOP_K` (300) rows of the score-ranked candidates first, and only then drops excluded rows. Excluding shown rows therefore shrinks one fixed top-300 pool and does not bring in deeper ANN hits. At 48 per batch the pool runs out by about batch 7 (the author cap makes it shallower), so batch 8 comes back empty. Ten batches leave slack for rows a higher-nprobe fallback step turns up. Ten also keeps the exclude list at 480 or fewer entries, under the 500 cap, so the Engine always sees every row already shown within the budget.

### Alternatives considered

- **Pull the home page's infinite-scroll code into a shared helper used by both pages.** Rejected for this build. It would change `pages/videos/index.ts`, whose state layout (sample, shuffle, modes) is different, and the scope says to leave that page alone. The copy is about 40 lines. This is deliberate duplication: if a third paged surface shows up, that is the point to extract the helper.
- **Page by requesting 8 rows at a time from the server.** Rejected by R1, and each request rebuilds and scores the pool, so eight times the requests for the same rows.
- **Render all 48 rows as soon as they arrive.** Rejected by R2. It would also fire live-stats requests for 48 cards the user may never scroll to.
- **Switch to the home page's `video-card` component.** Rejected by R4, which keeps `renderSimilarCard` markup.
- **Set up the observer and listeners at module load, as the home page does.** Rejected. See the first risk below. They are created once, the first time a first batch returns rows.

### Gotchas and risks

- **Existing test environment.** `tests/active/test_frontend_video_page.py` imports the real page module in node, with no `IntersectionObserver`, no `document.documentElement` and no `innerHeight`, and it answers `/recommendations` with `{}`. If the observer or listeners were created at module load, or on an empty first batch, that test would break. Creating them only after a non-empty first batch keeps it passing unchanged. The test's `window.addEventListener` stub already exists.
- **Rows without a `video_id` or host** are dropped by the pager and were not dropped before. The Engine always sets both, so in practice nothing changes. I'm noting it, not handling it.
- **Later batches can be slower.** Once exclusions shrink the cached pool below 48 rows, the Engine runs its live ANN fallback. Nothing shows while that fetch runs (the home page has no indicator either). The cards already shown stay usable.
- **The test's empty-batch assertion depends on the Engine's current pool rule** (top 300, then exclude). If that rule changes to refill from deeper hits, the test fails loudly, printing the batch sizes. It does not pass vacuously.
- **Test runtime.** About 8 Client→Engine round trips, some running the fallback. The runner keeps the retired file's 300 s timeout.
- **Layout.** Where the similar section sits below a tall player, the page is usually scrollable already, so fill-viewport rarely runs. It matters on very tall screens and after a resize.

### Tradeoffs asked of the operator

- The list ends quietly when the seed's pool runs out (about 300 rows at most, often fewer), with no "end of list" marker. This matches the home page.
- A failure on a later batch is only a `console.warn`. The user sees paging stop with no message, as R3 specifies.
- Up to a few hundred cards can build up in the DOM during one page view. There is no windowing or virtualisation. That is a deliberate simplification; windowing is the upgrade path if it ever matters.
- The scroll code is copied from the home page rather than shared, as described under the first alternative.

## Impacts


<impacts>
<impact path="client/frontend/src/pages/video-page/index.ts" element="import line 6 (`fetchSimilarVideosPayload, resolveApiBase` from ../../data/videos) and line 20 (`type { VideoRow }`)">
**What changes.** Line 6 adds `createFeedPager` and the type `FeedPager` (and `ExcludedVideo` if the fetch closure gets an annotation). `fetchSimilarVideosPayload` is still imported, but it is only called inside the pager's fetch closure. The type import at line 20 may need `VideosPayload` if module state or return types name it (`client/frontend/src/types/videos.ts:86`).

**What depends on it.** esbuild's bundle of this module in `tests/active/test_frontend_video_page.py:92` and the vite build (`vite.config.ts:89`). `data/videos.ts` already imports `./cache`, `./local-likes`, `./api-base` and `./profile`, so the bundle graph does not grow.

**Risk: low.** A misspelt named import fails `npm run build` and the esbuild step of test_frontend_video_page, whose `check=True` turns a failure into a fixture error.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="element lookups: `similarLink` (line 43) and `similarLinkInline` (line 51) removed; new `#similar-sentinel` lookup added beside `similarSection`/`similarCards` (49-50)">
**What changes.** Two `getElementById` constants are deleted and one is added (e.g. `similarSentinel`).

**What depends on it.**
- A grep for `similarLink` in `client/frontend/src` finds only lines 43, 51, 75-80 and 296-300, so nothing else reads the removed constants.
- The test stub's `getElementById` creates an element for any id (`test_frontend_video_page.py:63`), so a new lookup is harmless there.

**Risk: low.** If any reference is left behind, tsc and vite fail to compile, which gives a loud failure rather than a silent one.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="top-level block `if (similarLink && seedId) { … similarLink.href = `/videos.html?…` }` (lines 75-80)">
**What changes.** The block is deleted (R5).

**What depends on it.** Nothing else. The description-toggle block (82-90) and `localLikesImported` (93-95) directly below it are independent of it. The archived plan 19-14 describes the description block as "next to the `similarLink` wiring" (`docs/project/plans/archive/19-14-collapsible-description.md:567`). That wording is historical and archived, so no edit is needed.

**Risk: none.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="module state next to `similarStatsCache`/`similarStatsLoading` (lines 72-73): new `SIMILAR_CHUNK = 8`, rows, revealed count, `loading`, `fetchingMore`, current pager, observer/listeners-attached flags">
**What changes.** New `let`/`const` module state is added in the file's style. `statsNumberFormat` and `DESCRIPTION_CLAMP_LINES` (55-57) set the precedent for module constants.

**Home-page counterparts.** `pages/videos/index.ts:84-97` holds the equivalents: `state.loading`, `pager`, `fetchingMore`, `feedObserver`, `fallbackListenersAttached`. That file's `CHUNK_SIZE` is 6 (line 69); this page uses 8 per R2.

**Ordering constraint.** The module calls `void loadSimilarVideos()` at line 98, before most function declarations. Functions hoist, but `let`/`const` state does not: any state that `loadSimilarVideos` touches synchronously (before its first `await`) must be declared above line 98, or it throws a TDZ ReferenceError at import. The plan's reset of rows, revealed count, `loading` and the `Loading...` placeholder happens synchronously at the top of `loadSimilarVideos`, so this constraint applies to it directly.

**What depends on it.** The new reveal, load-more and fill functions, and `loadSimilarVideos`.

**Risk: medium.** A TDZ error would break the whole page module, and it would also make `test_frontend_video_page.py` exit non-zero. That test would catch it, which is good.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadSimilarVideos() (lines 290-325)">
**What changes.**
1. The early returns stay: missing elements, and no `seedId` (the section is hidden, R4).
2. The `similarLinkInline` block (296-301) is deleted.
3. New reset step: clear rows, set revealed = 0, set `loading = true`, put `<div class="loading">Loading...</div>` back into `similarCards`, and create a fresh `createFeedPager((exclude) => fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: "48", apiBase }, exclude))`.
4. `await localLikesImported` stays before the first `pager.next()`.
5. The success path clears `loading`, stores the rows, renders the first 8 via `innerHTML` and `queueSimilarStats` on that slice only, sets up the observer and listeners once, then runs fill-viewport.
6. An empty result keeps `No similar videos found.`.
7. The catch keeps the `ProfileKeyRejectedError` → `keyRejectedNotice(() => void loadSimilarVideos())` branch and the escaped message with the `Failed to load similar videos` fallback. `loading` must also be cleared on the error path.

**What depends on it.**
- The module-load call at line 98.
- The `keyRejectedNotice` retry, via `client/frontend/src/components/key-rejected.ts:11`, whose `onForget` callback is what re-invokes it.
- `test_frontend_video_page.py`, which answers `/recommendations` with `{}`. `createFeedPager` then returns `{rows: []}` and sets `exhausted` (`data/videos.ts:57-66`), so the page takes the "No similar videos found." branch and no observer is created. The test asserts nothing about similars but needs the process to exit 0.

**Behaviour deltas.**
- **Row filter.** The pager drops rows lacking `video_id` or `instance_domain` (`data/videos.ts:58-61`). The old code rendered them.
- **`seedHost` null.** `fetchSimilarVideosPayload` omits `host`, as before (`buildSimilarUrl`, lines 101-102).
- **Stale pager.** On retry, a stale in-flight `loadMoreSimilar` must see `current !== pager` and drop its result, as the home page does (`pages/videos/index.ts:239`).
- **Double run.** If `loadSimilarVideos` were entered twice concurrently, which only the retry can do, the older call's result would overwrite the grid. The home page has the same shape and does not guard it. Low likelihood, since the retry button appears only after the first call has finished.

**Risk: medium.** This is the core behaviour change. The R4 paths (empty, error, key-rejected, no seed) have no automated coverage beyond test_frontend_video_page's exit code.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="new functions: reveal-next-chunk (counterpart of `loadNextChunk`), `loadMoreSimilar` (counterpart of `loadMoreVideos`), fill-viewport (counterpart of `maybeFillViewport`), scroll check (counterpart of `maybeLoadOnScroll`), observer/listener setup (counterpart of `setupInfiniteScroll`)">
**What changes.** About 40 new lines, copied from `client/frontend/src/pages/videos/index.ts:232-375`, with these differences:
- **Append-only render.** The reveal appends only the new slice via `similarCards.insertAdjacentHTML("beforeend", slice.map(renderSimilarCard).join(""))` and calls `queueSimilarStats(slice)`. The home page's `renderCards` re-renders the grid instead.
- **Load-more trigger.** Reveal returns false and calls `void loadMoreSimilar()` when nothing is left to reveal.
- **`loadMoreSimilar` guards.** It returns on `loading || fetchingMore || pager.exhausted`, checks `current !== pager` after the await, and appends rows. It logs `console.warn` on failure and never touches the grid. On success it reveals, then runs fill-viewport.
- **Fill-viewport.** It is bounded by a safety counter of 50, the condition `scrollHeight <= innerHeight + 120`, and stops when a reveal changes nothing.
- **Scroll check.** `innerHeight + scrollY >= document.documentElement.scrollHeight - 240`.
- **Observer and listeners.** `IntersectionObserver` with `rootMargin: "200px"` on `#similar-sentinel`, a passive `scroll` listener, and a `resize` listener that runs both the scroll check and fill-viewport. All are created only after a non-empty first batch, and attached once (a flag like `fallbackListenersAttached`).

**What depends on it.**
- **Stats.** `applySimilarStatsToDom` (1090-1097) finds cards by `data-video-key` inside `similarCards`, so appended cards receive stats. `queueSimilarStats` skips keys already cached or loading (989-990), so revealing in slices causes no duplicate fetches.
- **Retry reuse.** On a retry the observer and listeners are reused and keep calling the reveal, which reads the current module state. The home page instead disconnects the observer and re-creates it (352-356). Either works, as long as the reveal is a no-op while `loading`.

**Environment.** `IntersectionObserver`, `document.documentElement` and `window.innerHeight` are absent in the test_frontend_video_page stub (lines 24-76). Any call at module load, or on the empty-first-batch path, throws in node.

**Loading guard.** The observer can fire right after `observe()` if the sentinel is within 200px of the viewport. The reveal must be a no-op, or at most a reveal from memory, while `loading`.

**Later-batch key rejection.** A `ProfileKeyRejectedError` on a later batch is swallowed by the warn path. Paging stops silently and no notice is shown. This is consistent with R3 (only the first batch shows errors), but it differs from the first-batch path.

**Risk: medium.** None of this is exercised by any automated test: node has no layout, and no browser harness exists. The maintainer's browser check is the only verification of reveal, append, observer and fill.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="renderSimilarCard (1168-1201), queueSimilarStats (973-1000), fetchSimilarStatsForHost/fetchViewsIndividually/fetchBatchViews/fetchSingleViews (1005-1085), applySimilarStatsToDom (1090-1097), resolveSimilarKey/resolveSimilarStats (936-953), videoPageUrl (1135-1156)">
**What changes.** Nothing (R4).

**What depends on them.** The new reveal function. `queueSimilarStats` now runs per 8-card slice. Each slice groups by host and issues one PeerTube `/api/v1/videos?id=…` batch per host, so live-stats requests to remote instances grow with scrolling: at most about 300 cards over a long page view. `fetchBatchViews` puts every id in the URL query. At 8 per slice the URL stays short.

**Risk: low.**
</impact>
<impact path="client/frontend/video-page.html" element="header nav `<a id=\"similar-link\" class=\"nav-link\" href=\"/\">Similar videos</a>` (line 22)">
**What changes.** The link is deleted (R5). The nav keeps Home, Likes, Search and About.

**What depends on it.** `.header-nav` in `video.css` is a fixed flex pill, so one fewer link only narrows it. No script reads the element once lines 43 and 75-80 are gone.

**Risk: low.**
</impact>
<impact path="client/frontend/video-page.html" element="`#similar-section` (lines 124-132): `<a id=\"similar-link-inline\" …>Open full list</a>` removed from `.section-header`; new `<div id=\"similar-sentinel\" class=\"similar-sentinel\" aria-hidden=\"true\"></div>` after `#similar-videos`">
**What changes.**
- The inline link is deleted, and the `<h3>Similar videos</h3>` stays. `.section-header` (`video.css:521-527`, `justify-content: space-between`) then holds a single h3, which renders left-aligned. No CSS change is needed.
- The sentinel sits inside `#similar-section`, after the grid. It is hidden along with the section when there is no seed.

**What depends on it.**
- The module's sentinel lookup and observer.
- `.un/skills/devsecops/config.json:148-152` maps test_frontend_video_page to this file, so the edit reselects that test.

**Risk: low.** The static `Loading...` placeholder (line 130) is kept, and the module rewrites it on a retry.
</impact>
<impact path="client/frontend/src/video.css" element="new `.similar-sentinel { height: 1px; }` rule, near `.similar-grid` (534-538) / `.similar-grid .loading, .error` (616-620)">
**What changes.** One new rule, mirroring `.feed-sentinel` in `client/frontend/src/videos.css:132-134`. The video page imports only `video.css` (`pages/video-page/index.ts:5`), and a grep finds no `@import` in either stylesheet, so the plan's reason for the new rule holds.

**What depends on it.** The sentinel element. test_frontend_video_page loads CSS as `--loader:.css=empty`, so the test is unaffected, though the config mapping reselects it.

**Risk: none.**
</impact>
<impact path="client/frontend/src/videos.css" element=".feed-sentinel (132-134)">
**What changes.** Nothing. It is the model for the new rule.

**Risk: none.**
</impact>
<impact path="client/frontend/src/data/videos.ts" element="createFeedPager (37-70), MAX_FEED_EXCLUDE (28), fetchSimilarVideosPayload (130-157), buildSimilarUrl (98-107)">
**What changes.** Nothing. The file gains a second production consumer, the video page, alongside `pages/videos/index.ts:94,181`.

**Facts the page relies on.**
- `next()` rethrows the fetch error after setting `exhausted` (51-55), so `ProfileKeyRejectedError` from a 401 (143-145) reaches the page's catch unchanged.
- Rows are keyed `video_id::instance_domain`, and rows without either are dropped.
- Each call sends the last 500 shown as `exclude`.
- A keyless body carries `getRandomLikes()` on every batch (line 133), so each batch may be personalised with a different random likes sample. The home page does the same.

**What depends on it.** test_frontend_blocks (mapped at `config.json:75-81`) and the new test, which bundles `createFeedPager` and `fetchSimilarVideosPayload`.

**Risk: none to the file.** Any future edit to it now affects two pages and two tests.
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="useSimilar mode (78, 212-214), loadVideos/loadMoreVideos/loadNextChunk/maybeFillViewport/maybeLoadOnScroll/setupInfiniteScroll (171-375)">
**What changes.** Nothing (R5, and the rejected alternative). `/videos.html?id=…&host=…` keeps working for bookmarks, and nothing in the app links to it any more.

**Why it matters.** It is the source of the copied scroll code, so the two copies now drift independently (the deliberate duplication).

**Doc impact.** `docs/project/issues/plan.md:91` lists "the `?id=` mode of `pages/videos/index.ts`" among this issue's files. That is no longer true under the operator's links-only decision.

**Risk: none.**
</impact>
<impact path="client/frontend/src/types/videos.ts" element="SimilarSeed (64-68), VideosPayload (86-91)">
**What changes.** Nothing.

**Why it matters.** `SimilarSeed` has no `mode` field. The new test reads `payload.seed?.mode` in plain JS in the runner, so this is not a type issue. If the page ever typed that read, it would need the field. The page itself does not read `seed`.

**Risk: none.**
</impact>
<impact path="client/frontend/src/components/key-rejected.ts" element="keyRejectedNotice(onForget) (line 11)">
**What changes.** Nothing. Its callback re-invokes `loadSimilarVideos`, which now resets state and builds a fresh pager.

**Risk: low.** The retry must not leave `loading` stuck at true. If it did, the observer and scroll checks would stay dead after a successful retry.
</impact>
<impact path="client/frontend/dist/video-page.html" element="built HTML and `dist/assets/video-*.js` / `video-*.css`">
**What changes.** Nothing by hand (R5). They go stale until `npm run build`, and still contain both links and the `limit:"8"` call (grep confirms at dist lines 28 and 109 and in the asset). A deploy needs a build followed by the rsync described in the archived plan 19-14.

**Risk: low (operational).** Deploying without a build ships the old page.
</impact>
<impact path="tests/active/test_frontend_video_page.py" element="RUNNER stubs (24-85) and the three taxonomy tests">
**What changes.** Nothing. It must keep passing as it is.

**What the runner provides.**
- `window` has `location`, the storages and `addEventListener() {}`, but no `innerHeight` or `scrollY`.
- `document` has no `documentElement`, and there is no `IntersectionObserver`.
- Elements have a no-op `insertAdjacentHTML`.
- `fetch` answers `{}` for every path except `/api/video`.

**Why it still passes.** The first batch is empty, so the page takes the "No similar videos found." path and never reaches observer or listener code. The test waits only 5×10 ms. The similars path is independent of the assertions, but an unhandled rejection or synchronous throw at import would fail it (non-zero exit, or a missing stdout line).

**Reselection.** `config.json:148-152` maps it to all three changed frontend files, so it is reselected.

**Risk: medium.** It is the only automated guard on the page module, and it guards only against crashes.
</impact>
<impact path="tests/active/test_frontend_upnext_pager.py" element="new test module (R6)">
**What changes.** A new file following the retired file's harness (`tests/archive/upnext_random_draw/test_frontend_videos.py:30-89`):
- `FRONTEND = parents[2]` (active depth; the archive uses `parents[3]`), `PAGE = "48"`, `MAX_BATCHES = 10`.
- A runner without the two plain-fetch control runs (archive lines 47-50). It reports `seed.mode` of the first pager batch instead.
- The `engine_client` fixture, the `linux` seed via `GET /api/v1/search/videos?q=linux&limit=1`, and a 300 s timeout.
- The runner's `window` in the archive lacks `sessionStorage` (line 41). The plan says to add it, as `test_frontend_video_page.py` does.

**Assertions.** Batches 1 and 2 are non-empty and disjoint. No batch repeats an earlier row. An empty batch exists at an index below the last. Calls count 1…k up to the empty batch and stay flat after it. The archive's `assert all("error" not in b …)` is presumably kept.

**Dependencies.**
- **Client.** `client/backend/server.py`: the `FEED_PAGE_SIZE` cap (69, 457) and the exclude validation (524-535).
- **Engine pool rule.** `get_upnext_candidates` in `engine/server/data/similarity_candidates.py:119-179` / `_upnext_rows` (182-197), which exclude after `_build_rows(top_k=300)`, plus `seed.mode = "upnext"` in `engine/server/api/handlers/similar.py:857-858`. The empty-pool branch (867+) answers without `mode`, but that affects only batches after the first.

**Flake exposure.**
1. Later batches drive the pool below `SIMILAR_VIDEO_TARGET_MIN_POOL` (48), so each runs the ANN fallback, up to 3 FAISS searches reaching nprobe 128 / k 20000. The Engine's 5 s deadline turns an overrun into a 500 (`DEPLOYMENT.md:260`). The Client's proxy timeout is 10 s (`server.py:77-79`). A 500 or 502 throws in `next()`, which sets `exhausted` and fails the no-error assertion. That is a timing-dependent failure.
2. A higher-nprobe fallback can surface new high-scoring hits into the top 300. The pool is therefore not strictly fixed, which is the plan's "slack" (batches 8-9).
3. The Engine's own limiter is `DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60` per 60 s (`engine/server/api/server_config.py:450-451`). The fixture relaxes only the Client limiter (`conftest.py:175`). The session Engine is shared with test_similar's many `/recommendations` calls when they run in one pytest process. I did not check how lanes split groups, so whether ~10 more requests can hit a 429 is unverified.

**Existing coverage.** `tests/active/test_similar.py` already shows that the linux seed fills a 48-row page (the `…fills_a_48_row_page…[linux]` test in `tests/last_test_validation.json`), so batch 1 at 48 is non-empty.

**Risk: medium-high (flakiness).** The file is new; it breaks nothing existing.
</impact>
<impact path="tests/archive/upnext_random_draw/test_frontend_videos.py" element="retired pager test (whole file)">
**What changes.** Nothing. It stays skipped (`pytestmark` at line 28) and serves as the template. Its docstring still says "issue 35 tracks a replacement", which is historical. It could gain a pointer to the new file, but that is optional.

**Risk: none.**
</impact>
<impact path="tests/active/conftest.py" element="engine (105-145, session-scoped, RECOMMENDATIONS_DEBUG=1) and engine_client (148-150 → _engine_client 164-184, Client RateLimiter(100000, 60))">
**What changes.** Nothing.

**Why it matters.** The new test uses `engine_client`, whose `.base` is the Client URL (line 180). The Client's limiter is relaxed there; the Engine's is not (see the new-test entry).

**Risk: none to the file.**
</impact>
<impact path="client/backend/server.py" element="FEED_PAGE_SIZE=48 / FEED_OVERFETCH_FACTOR=2 (69-70), _profile_filter (442-473), exclude validation (524-535), ENGINE_PROXY_TIMEOUT_SECONDS=10 (77-79), RATE_LIMIT_MAX_REQUESTS=90 per 60 s (62-63)">
**What changes.** Nothing (out of scope).

**Correction to the plan.** The plan says "the Client caps the page at 48 and over-fetches 96". The code over-fetches (limit = 96) only for a keyed request whose profile has blocks or dislikes (line 471). Keyless requests, and the new test, send `limit=48` to the Engine.

**Other facts.**
- The 500-entry exclude cap is never reached within the test budget (at most 9 × 48 = 432) or in a real page view, since the pool is ≤ 300.
- A browser scrolling to the pool's end makes about 7 `/recommendations` requests per page view, well under the production limiter's 90 per minute.

**Risk: none to the file.** Mapped as a dependency of the new test.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="get_upnext_candidates (119-179), _upnext_rows (182-197)">
**What changes.** Nothing.

**Why it matters.**
- It confirms the plan's budget reasoning: `_build_rows(..., policy.top_k)` (300) runs before the exclude filter (192-195), and "an excluded row does not free its channel's slot".
- The fallback runs when `len(rows) < target_min_pool` (48) (line 151). Once a page view has shown enough rows, every later batch pays up to 3 live searches.

**What depends on it.** The new test's empty-batch assertion. It is not mapped to the new test in the plan's config entry (see config.json).

**Risk: none to the file.** A future change to refill from deeper hits fails the new test.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_similar limit cap (941-947: max 2 × default_limit), mode stamp (1006, 857-858), empty-pool 200 branch (867+)">
**What changes.** Nothing.

**Why it matters.**
- `limit=48` is accepted.
- The first non-empty batch carries `seed.mode == "upnext"`, which the new test asserts.
- An empty batch comes back as 200 with no rows, which the pager turns into `exhausted`.

**Risk: none.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups: new `test_frontend_upnext_pager.py` entry (after line 152)">
**What changes.** A new entry mapping to `client/frontend/src/data/videos.ts` and `client/backend/server.py`, per the plan. No stale `test_frontend_videos.py` entry exists (grep finds none), so none needs dropping.

**Gap.** The test's empty-batch and no-repeat assertions depend on Engine behaviour: `engine/server/data/similarity_candidates.py` and `engine/server/api/handlers/similar.py`. Issue 35 line 26 itself recommends mapping those to the frontend tests. Without them, an Engine-only change will not reselect this test. I suggest adding both; this is a deviation from the plan's two-file list and needs the operator's OK.

**Risk: low.**
</impact>
<impact path="tests/last_test_validation.json" element="groups / tests record">
**What changes.** It is regenerated by the validation run. It will gain a `test_frontend_upnext_pager.py` group and new digests for `test_frontend_video_page.py`. Not hand-edited.

**Risk: none.**
</impact>
<impact path="docs/project/issues/35-upnext-tests-retired-by-random-draw.md" element="coverage list item `test_frontend_videos` (line 17), Proposed solution (26), Comments (33)">
**What changes.**
- A comment under `## Comments` saying the pager coverage is restored by `tests/active/test_frontend_upnext_pager.py` from build 12. Include what changed from the retired file: 48-row batches, no plain-fetch control, `MAX_BATCHES = 10`, and the empty batch reached because the Engine takes the top 300 before excluding.
- Line 17 is marked covered. The list items are bullets, not checkboxes, so this has to be text such as "(covered by …)".
- Line 26's "drop the `test_frontend_videos.py` entry until a replacement exists" is already satisfied and could note that.
- The other five items stay open, and the Status stays `needs-triage`.

**Risk: none.**
</impact>
<impact path="docs/project/issues/12-similars-on-scroll.md" element="whole issue">
**What changes, at harvest.** `Status: enhancement, complete` and a move to `docs/project/issues/archive/`, per the triage labels. Also add a delivery comment covering:
- the operator's links-only decision (`/videos.html?id=` kept);
- the 48-row batch revealed 8 at a time;
- that the list ends when the seed's pool (≤ 300) runs out;
- that later-batch failures are console-only.

**Risk: none.**
</impact>
</impacts>


## Documentation to update

- [ ] `client/frontend/README.md` - Under "What it does", after line 13, add a bullet: the video page's similar section fetches one 48-row up-next batch through `createFeedPager`, reveals 8 cards at a time as scrolling nears the bottom, and fetches the next batch, excluding the rows already shown, when the revealed rows run out. Paging ends after an empty or failed batch, and a later failure is only logged. Line 9 ("similar to one video") can stay, since `/videos.html?id=` still works. Line 10's feed-paging bullet can say that the video page uses the same pager.
- [ ] `DEPLOYMENT.md` - In "Up-next logs and load" (lines 253-260), note that one video page view now sends a sequence of up-next requests as the visitor scrolls: a 48-row batch each, carrying `exclude`, up to about 7 before a 300-row pool runs out. Once the unshown pool drops below 48 rows, each of these runs the ANN fallback. That multiplies the per-page-view `index_lock` load that the capacity paragraph describes.
- [ ] `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` - Add a comment recording that `tests/active/test_frontend_upnext_pager.py` from build 12 replaces the `test_frontend_videos` item: 48-row batches, no plain-fetch control, 10-batch budget, empty batch reached because the Engine takes the top 300 before excluding. Mark line 17 as covered and leave the other five items and the status open.
- [ ] `docs/project/issues/12-similars-on-scroll.md` - At harvest: set `Status: enhancement, complete`, add a delivery comment (links removed and the `/videos.html?id=` mode kept by operator decision, 48-row batch revealed 8 at a time, list ends at the pool's end with no marker, later-batch failure is console-only, no DOM windowing), then move the file to `docs/project/issues/archive/`.
- [ ] `docs/project/issues/plan.md` - Line 42 (P2 row): strike 12 as delivered. Line 91 (row 4a): mark it delivered and correct the file list. The `?id=` mode of `pages/videos/index.ts` and the similar route limit were not changed. The files are `pages/video-page/index.ts`, `video-page.html`, `video.css` and the new test.
- [ ] `docs/project/roadmap.md` - In the delivered list (lines 14-20), add an entry for issue `12`, similars on scroll: the video page pages up-next similars on scroll, 48 per request and revealed 8 at a time, and no longer links to the separate similar-videos page. Point it at `docs/project/plans/19-12-similars-on-scroll.md`, or its archived path after harvest.

## Implementation plan

# Draft — 12 similars on scroll

## Module map

| File | Change |
|---|---|
| `client/frontend/src/pages/video-page/index.ts` | Change the import; drop the two link lookups and the top-level href block; add a sentinel lookup and module paging state above `void loadSimilarVideos()`; rewrite `loadSimilarVideos`; add `revealSimilarChunk`, `loadMoreSimilar`, `fillSimilarViewport`, `maybeRevealSimilarOnScroll`, `setupSimilarScroll`. |
| `client/frontend/video-page.html` | Remove `#similar-link` (line 22) and `#similar-link-inline` (line 127); add `#similar-sentinel` after `#similar-videos`. |
| `client/frontend/src/video.css` | Add `.similar-sentinel { height: 1px; }` after `.similar-grid .loading, .similar-grid .error` (616-620). |
| `tests/active/test_frontend_upnext_pager.py` | New (R6). |
| `.un/skills/devsecops/config.json` | New `test_frontend_upnext_pager.py` entry with four files (the operator approved the two Engine files). |
| `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` | Line 17 marked covered, plus a comment. |

Nothing else changes: `data/videos.ts`, `pages/videos/index.ts`, the server files, the render and stats helpers, and `dist/`.

## What the build needs to test

- **Pager contract (R3, R6), automated by the new test.** These run against the real Client and Engine at limit 48:
  - the first batch has `seed.mode == "upnext"`;
  - batches 1 and 2 are non-empty and disjoint;
  - no batch repeats an earlier row;
  - an empty batch arrives within 10 batches;
  - requests stop after the empty batch.
- **Page module still imports and runs in node (TDZ, empty-first-batch path), automated.** `test_frontend_video_page.py` runs unchanged. Its `{}` answer to `/recommendations` takes the "No similar videos found." branch and must never reach `IntersectionObserver`, `document.documentElement` or `innerHeight`.
- **Reveal, append, observer and fill-viewport (R2), plus later-batch paging in a real layout: manual browser check only.** No harness exists, and node has no layout. The maintainer checks:
  - 8 cards on load;
  - +8 cards per scroll to the bottom;
  - a second `/recommendations` POST carrying `exclude` after 48 cards;
  - requests stop at the pool's end;
  - no link to `/videos.html`.

## `pages/video-page/index.ts`

### Imports (lines 6 and 20)

```ts
import { createFeedPager, fetchSimilarVideosPayload, resolveApiBase, type FeedPager } from "../../data/videos";
```

Line 20 stays `import type { VideoRow } from "../../types/videos";`. No other type is named. `ExcludedVideo` is inferred from `createFeedPager`'s parameter, so the closure needs no annotation.

### Element lookups

- Delete line 43 (`similarLink`) and line 51 (`similarLinkInline`).
- Add after `similarCards` (line 50):

```ts
const similarSentinel = document.getElementById("similar-sentinel");
```

### Module state

This goes directly after `similarStatsLoading` (line 73), which is above `void loadSimilarVideos()`, so the synchronous reset in `loadSimilarVideos` hits no TDZ error.

```ts
// The similar list shows this many cards at first and adds this many per scroll to the bottom.
const SIMILAR_CHUNK = 8;
// Every row fetched so far; only the first similarRevealed of them are in the grid.
let similarRows: VideoRow[] = [];
let similarRevealed = 0;
let similarLoading = false;
// One pager per load, so a retry starts with nothing shown and drops a replaced pager's result.
let similarPager: FeedPager | null = null;
let similarFetchingMore = false;
let similarScrollAttached = false;
```

- `similarPager` starts at `null`, not at a module-load `createFeedPager`. The no-seed path must never build one (R4).
- Invariant: `0 <= similarRevealed <= similarRows.length`.
- Invariant: the grid holds exactly `similarRows.slice(0, similarRevealed)` as cards, whenever `similarLoading` is false and the first batch was non-empty.

### Top-level href block (lines 75-80)

Deleted. The description-toggle block and `localLikesImported` stay where they are.

### `loadSimilarVideos` (replaces lines 287-325)

```ts
/**
 * Load the first up-next batch through a fresh pager and reveal its first chunk.
 */
async function loadSimilarVideos() {
  if (!similarSection || !similarCards) return;
  if (!seedId) {
    similarSection.setAttribute("hidden", "true");
    return;
  }
  similarRows = [];
  similarRevealed = 0;
  similarLoading = true;
  similarCards.innerHTML = `<div class="loading">Loading...</div>`;
  const current = createFeedPager((exclude) =>
    fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: "48", apiBase }, exclude)
  );
  similarPager = current;
  try {
    await localLikesImported;
    const payload = await current.next();
    if (current !== similarPager) return;
    similarLoading = false;
    const rows = payload.rows ?? [];
    if (!rows.length) {
      similarCards.innerHTML = `<div class="error">No similar videos found.</div>`;
      return;
    }
    similarRows = rows.slice();
    const first = similarRows.slice(0, SIMILAR_CHUNK);
    similarRevealed = first.length;
    similarCards.innerHTML = first.map((row) => renderSimilarCard(row)).join("");
    queueSimilarStats(first);
    setupSimilarScroll();
    fillSimilarViewport();
  } catch (error) {
    if (current !== similarPager) return;
    similarLoading = false;
    if (error instanceof ProfileKeyRejectedError) {
      similarCards.replaceChildren(keyRejectedNotice(() => void loadSimilarVideos()));
      return;
    }
    const message = error instanceof Error ? error.message : "Failed to load similar videos";
    similarCards.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
  }
}
```

**Decisions:**
- `limit: "48"` is literal. It equals `FEED_PAGE_SIZE`, and the Client caps it there anyway.
- `await localLikesImported` still comes before the first request. The pager's fetch runs only inside `next()`, so creating the pager earlier sends nothing.
- **Stale guard.** The `current !== similarPager` checks cost two lines and close the "double run" gap the impact names. A superseded call cannot overwrite the grid or clear `similarLoading` for the newer call. This is a small addition over the home page, which does not guard.
- `similarLoading` is cleared on every path of the current call: empty, success, key-rejected and error. A retry therefore never leaves the scroll handlers dead.
- The observer and listeners are set up only after a non-empty first batch. `test_frontend_video_page.py` never reaches them.

### New functions (placed after `loadSimilarVideos`)

```ts
/**
 * Append the next chunk of fetched rows to the grid; with none left, ask the pager for more.
 */
function revealSimilarChunk() {
  if (similarLoading || !similarCards) return false;
  const nextCount = Math.min(similarRows.length, similarRevealed + SIMILAR_CHUNK);
  if (nextCount <= similarRevealed) {
    void loadMoreSimilar();
    return false;
  }
  const slice = similarRows.slice(similarRevealed, nextCount);
  similarRevealed = nextCount;
  // Appending leaves the cards already shown, and their fetched stats, in place.
  similarCards.insertAdjacentHTML("beforeend", slice.map((row) => renderSimilarCard(row)).join(""));
  queueSimilarStats(slice);
  return true;
}

/**
 * Fetch the next up-next batch once the revealed rows reach the end of the ones fetched.
 */
async function loadMoreSimilar() {
  const current = similarPager;
  if (!current || similarLoading || similarFetchingMore || current.exhausted) return;
  similarFetchingMore = true;
  let appended = false;
  try {
    const payload = await current.next();
    if (current !== similarPager || !payload.rows?.length) return;
    similarRows.push(...payload.rows);
    appended = true;
  } catch (error) {
    console.warn("[similar] loading more failed; paging stops for this page view", error);
  } finally {
    similarFetchingMore = false;
  }
  // The sentinel may still be in view, so the observer will not fire again: reveal until it scrolls.
  if (appended) {
    revealSimilarChunk();
    fillSimilarViewport();
  }
}

/**
 * While the page is too short to scroll, keep revealing chunks until it can.
 */
function fillSimilarViewport() {
  if (similarLoading) return;
  let safety = 0;
  while (document.documentElement.scrollHeight <= window.innerHeight + 120 && safety < 50) {
    if (!revealSimilarChunk()) break;
    safety += 1;
  }
}

/**
 * Reveal the next chunk once the page is scrolled near its bottom.
 */
function maybeRevealSimilarOnScroll() {
  if (similarLoading) return;
  const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 240;
  if (nearBottom) revealSimilarChunk();
}

/**
 * Watch the sentinel after the grid, with scroll and resize as a fallback; attached once per page view.
 */
function setupSimilarScroll() {
  if (similarScrollAttached) return;
  similarScrollAttached = true;
  if (similarSentinel) {
    new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        revealSimilarChunk();
      },
      { rootMargin: "200px" }
    ).observe(similarSentinel);
  }
  window.addEventListener("scroll", maybeRevealSimilarOnScroll, { passive: true });
  window.addEventListener("resize", () => {
    maybeRevealSimilarOnScroll();
    fillSimilarViewport();
  });
}
```

**Invariants and decisions:**

- **`revealSimilarChunk`**
  - It is a no-op returning `false` while `similarLoading`. The observer can fire right after `observe()`, and on a retry the reused listeners fire into a grid that shows `Loading...`.
  - It returns `true` exactly when it appended cards.
  - Stats are queued only for the appended slice (R2). `queueSimilarStats` already skips cached and in-flight keys.
- **`loadMoreSimilar`**
  - At most one fetch is in flight (`similarFetchingMore`).
  - The pager owns the stop rule: `exhausted` after an empty or failed batch, after which the early return means no request is made (R3).
  - A later-batch failure, `ProfileKeyRejectedError` included, is only warned about. The grid is never touched (R3, as the impact notes).
- **`fillSimilarViewport` (deliberate difference from `maybeFillViewport`).** The loop does not also require `similarRevealed < similarRows.length`. It stops as soon as a reveal changes nothing, and that final reveal is the one that calls `loadMoreSimilar`.
  - Why: on a very tall screen where all 48 rows fit, the page still asks for the next batch. On the home page the fill loop would stop there, and the sentinel observer would not fire again.
  - It stays bounded: the safety counter is 50, `loadMoreSimilar` is guarded, and the pager exhausts within ~7 batches.
  - R2's rule ("while short and unrevealed rows remain, keep revealing") still holds. This only adds R3's "a reveal that finds none left asks the pager".
- **`setupSimilarScroll`**
  - The observer and listeners are created once and reused across retries. They read module state, so no disconnect is needed.
  - If `#similar-sentinel` is missing, scroll and resize still work.

### Unchanged

`renderSimilarCard`, `queueSimilarStats` and the stats fetchers, `applySimilarStatsToDom`, `videoPageUrl`, and all metadata, reaction, block and description code.

## `video-page.html`

The nav loses line 22:

```html
        <nav class="header-nav">
          <a class="nav-link" href="/">Home</a>
          <a class="nav-link" href="/likes.html">Likes</a>
          <a class="nav-link" href="/search.html">Search</a>
          <a class="nav-link" href="/about.html">About</a>
        </nav>
```

The similar section:

```html
        <section id="similar-section" class="similar-card">
          <div class="section-header">
            <h3>Similar videos</h3>
          </div>
          <div id="similar-videos" class="similar-grid">
            <div class="loading">Loading...</div>
          </div>
          <div id="similar-sentinel" class="similar-sentinel" aria-hidden="true"></div>
        </section>
```

## `video.css`

Added after line 620:

```css
.similar-sentinel {
  height: 1px;
}
```

## `tests/active/test_frontend_upnext_pager.py`

```python
"""The frontend's feed pager over up-next similars, run in node against the real Client and Engine at the video page's 48-row batch: its batches never repeat a row, and it stops asking once a batch adds nothing.

- For the linux seed, the pager's first batch is an up-next page (`seed.mode == "upnext"`), its second batch holds rows and none of the first batch's, and no later batch repeats a row of an earlier one. Each batch is a random draw (build 09), so no two pages are compared for equality.
- The pager is driven for MAX_BATCHES calls and reaches an empty batch before the last: the Engine takes a seed's top 300 rows before it drops excluded ones, so at 48 a batch the pool runs out in about 7. No call after the empty batch makes a request, counted on the fetch function the pager is given (a pass-through to `fetchSimilarVideosPayload`).

Replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). `window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner supplies minimal in-memory ones, as `test_frontend_video_page.py` does.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
PAGE = "48"
MAX_BATCHES = 10

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage,
  sessionStorage: globalThis.sessionStorage };
const m = await import(process.env.BUNDLE);
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\\n");
const keys = (rows) => (rows ?? []).map((r) => [r.video_id, r.instance_domain]);
const query = { id: process.env.SEED_UUID, host: process.env.SEED_HOST, limit: process.env.PAGE,
  apiBase: process.env.BASE };
let calls = 0;
try {
  const pager = m.createFeedPager((exclude) => { calls += 1; return m.fetchSimilarVideosPayload(query, exclude); });
  for (let i = 0; i < Number(process.env.MAX_BATCHES); i += 1) {
    const payload = await pager.next();
    say({ rows: keys(payload.rows), mode: payload.seed?.mode ?? null, calls });
  }
} catch (e) { say({ error: String(e), calls }); }
process.exit(0);
"""


def _run(tmp_path: Path, base: str, seed: dict) -> list[dict]:
    entry = tmp_path / "entry.ts"
    entry.write_text(f'export {{ createFeedPager, fetchSimilarVideosPayload }} from "{FRONTEND}/src/data/videos.ts";\n')
    subprocess.run(
        [str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node",
         f"--outfile={tmp_path / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    runner = tmp_path / "runner.mjs"
    runner.write_text(RUNNER)
    proc = subprocess.run(
        ["node", str(runner)], capture_output=True, text=True, timeout=300,
        env={"BASE": base, "BUNDLE": str(tmp_path / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "SEED_UUID": seed["video_uuid"], "SEED_HOST": seed["instance_domain"],
             "PAGE": PAGE, "MAX_BATCHES": str(MAX_BATCHES)},
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def _seed(client) -> dict:
    # A seed whose up-next pool fills a 48-row page (test_similar's fills_a_48_row_page case).
    status, body = client.request("GET", "/api/v1/search/videos?q=linux&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(
        engine_client, tmp_path):
    batches = _run(tmp_path, engine_client.base, _seed(engine_client))
    assert all("error" not in b for b in batches), batches
    assert len(batches) == MAX_BATCHES, batches
    assert batches[0]["mode"] == "upnext", batches[0]  # control: the seed resolves to up-next

    first, second = (set(map(tuple, b["rows"])) for b in batches[:2])
    assert first, "the first batch is empty"
    assert second, "the second batch is empty"
    assert not first & second, first & second
    seen: set[tuple] = set()
    for batch in batches:  # and no later batch repeats a row of any earlier one
        rows = set(map(tuple, batch["rows"]))
        assert not rows & seen, (rows & seen, [len(b["rows"]) for b in batches])
        seen |= rows

    empty = next((i for i, b in enumerate(batches) if not b["rows"]), None)
    # the seed's pool ends within the budget, with at least one call after it to count
    assert empty is not None and empty + 1 < len(batches), [len(b["rows"]) for b in batches]
    # control: up to the empty batch, every batch was one request through the given fetch
    assert [b["calls"] for b in batches[:empty + 1]] == list(range(1, empty + 2)), batches
    assert all(b["calls"] == batches[empty]["calls"] for b in batches[empty + 1:]), batches
```

**Changes from the retired file:**
- `parents[2]`, `PAGE = "48"`, `MAX_BATCHES = 10`.
- `window.sessionStorage` is added.
- The plain-fetch controls are gone. `mode` comes from the first pager batch; the pager spreads `payload`, so `seed` survives.
- The error line carries `calls`.
- `len(batches) == MAX_BATCHES` is checked, so a crash partway through fails.
- The failure messages print batch sizes, so an Engine pool-rule change fails with a readable message rather than passing vacuously.

**Known flake exposure (not handled in the draft):**
- An Engine 5 s deadline overrun in a fallback batch.
- The Engine's 60/min limiter shared with `test_similar`.

Both show up as an `error` line and fail the first assertion. If they bite in validation, the fix is in the harness (lane or grouping), not a weaker assertion.

## `.un/skills/devsecops/config.json`

Inserted after the `test_frontend_video_page.py` entry (after line 152):

```json
    "test_frontend_upnext_pager.py": [
      "client/frontend/src/data/videos.ts",
      "client/backend/server.py",
      "engine/server/data/similarity_candidates.py",
      "engine/server/api/handlers/similar.py"
    ],
```

The operator approved the two Engine files at this step: the empty-batch and no-repeat assertions depend on them (issue 35 line 26).

## Issue 35

Line 17 becomes:

```markdown
- **test_frontend_videos** (the whole file): the frontend pager never repeats a row and stops asking after an empty batch. Covered by `tests/active/test_frontend_upnext_pager.py` (build 12).
```

Line 26 gets an appended sentence: "The `test_frontend_videos.py` entry is gone; its replacement is mapped as `test_frontend_upnext_pager.py`."

Comment under `## Comments`:

```markdown
- Build 12 (similars on scroll): `tests/active/test_frontend_upnext_pager.py` replaces `test_frontend_videos`. It drives `createFeedPager` over `fetchSimilarVideosPayload` for the linux seed at 48 rows per batch, with no plain-fetch control (each page is a random draw), a 10-batch budget, and the first batch's `seed.mode` checked as `upnext`. The empty batch is reached because the Engine takes a seed's top 300 rows before dropping excluded ones. It is mapped to `data/videos.ts`, `server.py`, `similarity_candidates.py` and `handlers/similar.py`. The other five items stay open.
```

Status stays `enhancement, needs-triage`.

## Check against plan and requirements (pass 1, converged)

| Item | Where met |
|---|---|
| R1 limit 48 via `fetchSimilarVideosPayload` with id/host/apiBase | pager closure in `loadSimilarVideos` |
| R2 memory + revealed prefix, first 8, +8 appended, stats per slice | `similarRows`/`similarRevealed`, `revealSimilarChunk` |
| R2 sentinel observer 200px, passive scroll, resize, −240 / +120 thresholds, safety 50 | `setupSimilarScroll`, `maybeRevealSimilarOnScroll`, `fillSimilarViewport` |
| R3 one pager per load, exclude via pager, load-more guards, reveal + fill after append, console.warn only | `loadSimilarVideos`, `loadMoreSimilar` |
| R4 likes import first, empty / error / key-rejected / no-seed paths, card markup | `loadSimilarVideos`; helpers untouched |
| R5 both links and their code removed, heading kept, `useSimilar` untouched, no dist edit | HTML, deleted lines 43/51/75-80/296-301 |
| R6 test, mapping, issue 35 | above |
| Impact: TDZ ordering | state declared above line 98 |
| Impact: `loading` cleared on all paths, stale pager dropped | `loadSimilarVideos`, `loadMoreSimilar` |
| Impact: no observer or listener in the node stub's empty path | set up only after a non-empty first batch |

**Named deviations from the plan:**
1. `fillSimilarViewport` also asks for the next batch once all fetched rows fit the viewport.
2. `loadSimilarVideos` guards against a superseded call.
3. The config entry has four files, not two (operator-approved).

**Simplifications, carried from the plan:**
- No end-of-list marker.
- Later-batch errors go to the console only.
- No DOM windowing. This caps out at the pool size of about 300 cards; the upgrade path is windowing.
- The scroll code is copied from the home page rather than shared. The upgrade path is extracting it when a third paged surface appears.

### Phases

#### Phase 1 - Up-next pager contract test [code]

**Files touched.** tests/active/test_frontend_upnext_pager.py (NEW), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: the frontend data layer's `createFeedPager` over `fetchSimilarVideosPayload`, bundled with esbuild (ESM, node platform) and run in node against the live Client and Engine that the `engine_client` fixture starts locally. This follows the harness of the retired `tests/archive/upnext_random_draw/test_frontend_videos.py`. The checkpoint is the new `tests/active/test_frontend_upnext_pager.py` itself, as drafted, going green. For the linux search seed at limit "48": the first batch's `seed.mode == "upnext"`; batches 1 and 2 are non-empty and disjoint; no batch repeats a `(video_id, instance_domain)` row from any earlier batch; an empty batch comes before the last of `MAX_BATCHES = 10` calls; the counted fetch calls go 1..k up to the empty batch and do not increase after it. This is characterization: `data/videos.ts` does not change, so the test is green once written.

**Intent.** `tests/active/test_frontend_upnext_pager.py` holds the frontend feed pager's contract over up-next similars at the video page's 48-row batch, in place of the retired `test_frontend_videos.py`.

- C1 - Across 48-row batches from the linux seed, no row repeats, an empty batch arrives within 10 batches, and no request is made after it.

**Outcome.** ### `tests/active/test_frontend_upnext_pager.py` (NEW)
This is the durable up-next pager contract test. It replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). It bundles `data/videos.ts` with esbuild and runs `createFeedPager` in node against the live Client and Engine (`engine_client` fixture). The linux seed is used, with 48-row batches and MAX_BATCHES = 10. The test checks C1:
- the first batch comes back in up-next mode (a control)
- the second batch is non-empty and shares no rows with the first
- no batch repeats a row of an earlier one
- an empty batch arrives before the last call
- every batch before the last non-empty one holds exactly 48 rows, and that one holds 1–48
- calls count 1..n up to the empty batch and stay flat after it

The runner and helpers follow the retired file's structure, with `sessionStorage` added to `window`.

It does **not** repeat the checkpoint's limit-20 run ("the batch size follows the limit sent"). The checkpoint swaps `_run` for a function that returns one fixed set of 48-row batches on every call. A second `_run` asking for 20 would get those 48-row batches back, so the durable test would fail even the good case. As a result, that check lives only in the Phase 1 checkpoint, which is temporary. `_run` and `_seed` are called with positional arguments, and the one test takes `(engine_client, tmp_path)`, because the checkpoint's replacement functions expect exactly those.

### `.un/skills/devsecops/config.json` (EDITED)
Added a `test_groups` entry for `test_frontend_upnext_pager.py`. It maps to `client/frontend/src/data/videos.ts`, `client/backend/server.py`, `engine/server/data/similarity_candidates.py` and `engine/server/api/handlers/similar.py`, so the group is reselected when any of them changes.

### `tests/tmp/probe_upnext_durable.py` (probe; please delete)
This probe re-imports the checkpoint's two offline tests: the one that feeds fixed batches to the durable file, and the one that checks the config mapping. Both passed when run through `ValidateTests`. The checkpoint's live test was not run. I have no tool that can delete files, so it is still there and should be removed.

**Beyond the files named.** tests/tmp/probe_upnext_durable.py — a probe that could not be deleted with the tools available; it holds no phase code and should be removed.

#### Phase 2 - First similar batch through the pager [code]

**Files touched.** client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page_similars.py (NEW)

**Checkpoint.** Seam: the real page module `client/frontend/src/pages/video-page/index.ts`, bundled with esbuild (`--loader:.css=empty`) and imported in node under the recording-element runner copied from `tests/active/test_frontend_video_page.py`. It lives in a new `tests/active/test_frontend_video_page_similars.py`. The runner adds stubs: an `IntersectionObserver` whose callback and observed element are captured; `document.documentElement.scrollHeight` large and `window.innerHeight` small, so fill-viewport never loops; `window.scrollY`. `fetch` records the method, path and JSON body of each request. It answers POST `/recommendations` with 48 distinct rows (each with `video_id` and `instance_domain`) and `seed.mode: "upnext"`, and answers `{}` elsewhere. Asserts: exactly one `/recommendations` request was made, and its body's limit is "48"; the `#similar-videos` element's innerHTML holds exactly 8 `similar-card-item` anchors. Control: `/api/video` was requested. `tests/active/test_frontend_video_page.py` must still pass unchanged, which covers the empty first batch and the no-observer path.

**Intent.** `loadSimilarVideos` in `pages/video-page/index.ts` fetches its first batch through a fresh feed pager asking `/recommendations` for 48 rows, and puts only the first 8 of them into `#similar-videos`.

- C1 - The first `/recommendations` request the page makes carries limit 48.
- C2 - From a 48-row answer, `#similar-videos` holds exactly 8 cards.

**Outcome.** ### `client/frontend/src/pages/video-page/index.ts` (EDITED)
- The import from `../../data/videos` now also brings in `createFeedPager`.
- Added a module constant `SIMILAR_CHUNK = 8` next to `similarStatsCache`/`similarStatsLoading`. It sits above `void loadSimilarVideos()`, so reading it cannot hit a TDZ error.
- `loadSimilarVideos` no longer calls `fetchSimilarVideosPayload` directly with `limit: "8"`. After `await localLikesImported` it creates a fresh pager on each call (`createFeedPager((exclude) => fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: "48", apiBase }, exclude))`), so a key-rejected retry starts with nothing shown and nothing excluded. It then awaits `pager.next()` and renders only `rows.slice(0, SIMILAR_CHUNK)` into `#similar-videos` with `renderSimilarCard`. `queueSimilarStats` runs on those 8 rows only.
- Unchanged: the empty-batch message (`No similar videos found.`), the `ProfileKeyRejectedError` → `keyRejectedNotice` retry, the escaped error message, the no-seed path and the similar-link blocks. The last are removed in phase 4.
- The pager is a local here. The module state from the plan (all fetched rows, revealed count, loading/fetching flags, the current pager) and the scroll code belong to phase 3, which is the first phase that reads them.

### `tests/active/test_frontend_video_page_similars.py` (NEW)
- The durable home of this phase's checkpoint, as the plan names it. It has the same runner, fixture and single test as `tests/tmp/test_12_similars_on_scroll_phase2.py`, with the clause tags removed and the runner comment reworded for a file that phases 3 and 4 will extend.
- It bundles the real page module with esbuild and imports it in node. It checks that exactly one `/recommendations` POST was made, with `limit=48` in the query. From a 48-row answer, `#similar-videos` must hold exactly 8 `similar-card-item` anchors, and they must be rows v0–v7 in order. Control: `/api/video` was requested.

### Observation
- I ran the checkpoint `tests/tmp/test_12_similars_on_scroll_phase2.py` once through `ValidateTests` against this code: 1 passed.
- That tool call wrote `tests/last_test_validation.json` / `tests/last_test_output.txt` for that one tmp path. I did not run anything under `tests/active` myself, including the new durable file and `test_frontend_video_page.py`.
- `test_frontend_video_page.py` answers `/recommendations` with `{}`, so I expect it to take the pager's empty-batch path to `No similar videos found.`. That is a prediction; I did not observe it.

#### Phase 3 - Reveal and page on scroll [code]

**Files touched.** client/frontend/src/pages/video-page/index.ts (EDITED), client/frontend/video-page.html (EDITED), client/frontend/src/video.css (EDITED), tests/active/test_frontend_video_page_similars.py (EDITED)

**Checkpoint.** Seam: the same node harness and file as phase 2 (`tests/active/test_frontend_video_page_similars.py`), after the first batch has rendered. The runner also records each `insertAdjacentHTML` call on `#similar-videos`, and invokes the captured `IntersectionObserver` callback with `[{ isIntersecting: true }]`. Fetch answers a second `/recommendations` POST with a disjoint batch. Asserts: one intersection adds exactly one `insertAdjacentHTML("beforeend", …)` call holding 8 `similar-card-item` anchors, and the grid's innerHTML is still the first 8 cards, not rewritten. After five further intersections have revealed all 48 rows, the next intersection sends a second `/recommendations` POST, and its exclude list holds exactly the 48 `(video_id, instance_domain)` pairs of the first batch. Control: the observer was constructed with the `#similar-sentinel` element.

**Intent.** Once the first similar batch is shown, each sentinel intersection appends the next 8 fetched rows to `#similar-videos`, and an intersection that finds no unrevealed row asks the pager for the next batch, excluding the rows already shown.

- C1 - A sentinel intersection appends the next 8 cards, and the cards already shown stay in place.
- C2 - An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown.

**Outcome.** ### `client/frontend/src/pages/video-page/index.ts`
- The import from `../../data/videos` now also brings in `type FeedPager`.
- Added a `similarSentinel` lookup (`#similar-sentinel`) next to `similarSection` and `similarCards`.
- Added module paging state next to `SIMILAR_CHUNK` (8), placed above the module-load `void loadSimilarVideos()` call so the synchronous reset in that function does not hit a temporal-dead-zone (TDZ) error: `similarRows`, `similarRevealed`, `similarLoading`, `similarPager` (starts null), `similarFetchingMore` and `similarScrollAttached`. The `SIMILAR_CHUNK` comment now says it is both the first count and the per-scroll step.
- `loadSimilarVideos`:
  - It first resets the rows, the revealed count and `similarLoading = true`, and puts `Loading...` back in the grid, so a key-rejected retry starts from nothing.
  - It stores the fresh pager in `similarPager`.
  - After the first batch arrives, it drops a superseded call's result with `current !== similarPager`, on both the success and the error path.
  - It clears `similarLoading` on every path, stores the rows and renders the first 8 through `innerHTML` as before.
  - Only after a non-empty first batch does it call `setupSimilarScroll()` and then `fillSimilarViewport()`. On the empty path (which `tests/active/test_frontend_video_page.py` takes, answering `{}`), `IntersectionObserver`, `document.documentElement` and `innerHeight` are never touched.
  - The `similarLinkInline` block stays; removing it is phase 4.
- New `revealSimilarChunk()`:
  - Does nothing while `similarLoading`.
  - Appends the next up-to-8 fetched rows with `similarCards.insertAdjacentHTML("beforeend", …)` using the unchanged `renderSimilarCard`, and queues stats for that slice only.
  - When no fetched row is left, it calls `void loadMoreSimilar()` and returns false.
- New `loadMoreSimilar()`:
  - Returns early without a pager, while loading, while a fetch is running, or when `pager.exhausted` is set.
  - Otherwise awaits `pager.next()`; the pager supplies the `exclude` list of every row fetched so far.
  - Drops a stale pager's result and appends new rows to memory.
  - On failure it only calls `console.warn` and leaves the grid alone.
  - After appending, it reveals once and runs fill-viewport, because the sentinel may still be in view.
- New `fillSimilarViewport()`: while `scrollHeight <= innerHeight + 120`, it reveals chunks, up to 50 times, and stops at the first reveal that changes nothing. As the draft deliberately specifies, it does not also require unrevealed rows. The reveal that finds none left is the one that asks for the next batch; a comment says why.
- New `maybeRevealSimilarOnScroll()`: reveals when `innerHeight + scrollY >= scrollHeight - 240`.
- New `setupSimilarScroll()`: attached once per page view. It creates an `IntersectionObserver` (`rootMargin: "200px"`) on `#similar-sentinel` when the element exists, a passive `scroll` listener, and a `resize` listener that runs the scroll check and then fill-viewport.

### `client/frontend/video-page.html`
- Added `<div id="similar-sentinel" class="similar-sentinel" aria-hidden="true"></div>` right after `#similar-videos`, inside `#similar-section`. It is hidden together with the section when there is no seed. Both links stay in place for phase 4.

### `client/frontend/src/video.css`
- Added a `.similar-sentinel { height: 1px; }` rule after `.similar-grid .loading, .similar-grid .error`. The home page's `.feed-sentinel` lives in `videos.css`, which this page does not import.

### `tests/active/test_frontend_video_page_similars.py`
- Not touched. It has already gated as phase 2's durable test, and it still holds as the code stands: its observer is never fired, and its tall document keeps fill-viewport from looping. The phase 3 checkpoint in `tests/tmp/` is the one this phase is gated on, and moving it into the active file is left to checkpoint promotion.

### Not changed
- `client/frontend/dist/` is not rebuilt. It stays stale until `npm run build`, as the impact inventory records.

#### Phase 4 - Remove the see-all links [code]

**Files touched.** client/frontend/video-page.html (EDITED), client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page_similars.py (EDITED)

**Checkpoint.** Seam, two boundaries. First, the served HTML file `client/frontend/video-page.html`, parsed with stdlib `html.parser`: no `a` element has an `href` containing `/videos.html`, and no element has id `similar-link` or `similar-link-inline`. Second, the phase 2 node runner in `tests/active/test_frontend_video_page_similars.py`, which reports every id passed to `document.getElementById`: neither `similar-link` nor `similar-link-inline` is among them after the page has loaded. Control: `similar-videos` is among them.

**Intent.** The video page no longer offers a link to `/videos.html`: the anchor is gone from its HTML, and the module no longer looks up the link elements.

- C1 - `video-page.html` contains no anchor to `/videos.html`.
- C2 - The page module never looks up `#similar-link` or `#similar-link-inline`.

**Outcome.** _pending_


