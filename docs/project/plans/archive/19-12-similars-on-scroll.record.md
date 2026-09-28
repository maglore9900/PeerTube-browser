# Build record - 12-similars-on-scroll

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/19-12-similars-on-scroll.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Similars on scroll\n\nStatus: enhancement, needs-triage\nOrigin: task 2, [M2][F1]\n\n## Problem\n\nOnly 8 similar videos are shown; users want to see more.\n\n## Proposed solution\n\nRemove the separate \"similar videos\" page and load similars directly on the video page, like the home page: the server returns N similars and the client renders them progressively on scroll.\n\n- The server returns a full batch of similars at once (e.g. `BATCH_SIZE = 48`) in a single response.\n- The client keeps the batch in memory and reveals it in chunks as the user nears the bottom.\n\n## Related\n\n- After `09-similars-diversity` and `11-fast-similars-response`.\n\n## Comments\n\n### Up-next responses are random draws (from `09-similars-diversity`)\n\nPlan this issue against what 09 delivered:\n\n- **Each response is a draw, not a fixed page.** A limit-48 request scores the seed's pool (at most `SIMILAR_VIDEO_TOP_K` = 300 rows), takes the top min(4 \u00d7 48 = 192, pool size) rows as the window, and draws 48 of them by score-weighted sampling. Two identical requests return different pages. For the draw itself see `engine/server/api/recommendations/docs/OVERVIEW.md`.\n- **Scroll paging must exclude shown rows.** A second batch fetched without `exclude` can repeat rows from the first, so paging has to send every row already shown, as `createFeedPager` (`client/frontend/src/data/videos.ts`) does. The Engine removes excluded rows while it builds the pool, so the next batch is drawn from rows not yet shown.\n- **No test covers the pager.** `test_frontend_videos.py`, which checked that the pager never repeats a row and stops after an empty batch, was retired to `tests/archive/upnext_random_draw/`. Issue 35 (`35-upnext-tests-retired-by-random-draw.md`) tracks its replacement, which matters most for this issue.",
  "request_source": "read from docs/project/issues/12-similars-on-scroll.md",
  "slug": "12-similars-on-scroll",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Up-next pager contract test",
      "checkpoint": "Seam: the frontend data layer's `createFeedPager` over `fetchSimilarVideosPayload`, bundled with esbuild (ESM, node platform) and run in node against the live Client and Engine that the `engine_client` fixture starts locally. This follows the harness of the retired `tests/archive/upnext_random_draw/test_frontend_videos.py`. The checkpoint is the new `tests/active/test_frontend_upnext_pager.py` itself, as drafted, going green. For the linux search seed at limit \"48\": the first batch's `seed.mode == \"upnext\"`; batches 1 and 2 are non-empty and disjoint; no batch repeats a `(video_id, instance_domain)` row from any earlier batch; an empty batch comes before the last of `MAX_BATCHES = 10` calls; the counted fetch calls go 1..k up to the empty batch and do not increase after it. This is characterization: `data/videos.ts` does not change, so the test is green once written.",
      "intent": "`tests/active/test_frontend_upnext_pager.py` holds the frontend feed pager's contract over up-next similars at the video page's 48-row batch, in place of the retired `test_frontend_videos.py`.",
      "clauses": [
        {
          "id": "C1",
          "text": "Across 48-row batches from the linux seed, no row repeats, an empty batch arrives within 10 batches, and no request is made after it."
        }
      ],
      "files": [
        "tests/active/test_frontend_upnext_pager.py (NEW)",
        ".un/skills/devsecops/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### `tests/active/test_frontend_upnext_pager.py` (NEW)\nThis is the durable up-next pager contract test. It replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). It bundles `data/videos.ts` with esbuild and runs `createFeedPager` in node against the live Client and Engine (`engine_client` fixture). The linux seed is used, with 48-row batches and MAX_BATCHES = 10. The test checks C1:\n- the first batch comes back in up-next mode (a control)\n- the second batch is non-empty and shares no rows with the first\n- no batch repeats a row of an earlier one\n- an empty batch arrives before the last call\n- every batch before the last non-empty one holds exactly 48 rows, and that one holds 1\u201348\n- calls count 1..n up to the empty batch and stay flat after it\n\nThe runner and helpers follow the retired file's structure, with `sessionStorage` added to `window`.\n\nIt does **not** repeat the checkpoint's limit-20 run (\"the batch size follows the limit sent\"). The checkpoint swaps `_run` for a function that returns one fixed set of 48-row batches on every call. A second `_run` asking for 20 would get those 48-row batches back, so the durable test would fail even the good case. As a result, that check lives only in the Phase 1 checkpoint, which is temporary. `_run` and `_seed` are called with positional arguments, and the one test takes `(engine_client, tmp_path)`, because the checkpoint's replacement functions expect exactly those.\n\n### `.un/skills/devsecops/config.json` (EDITED)\nAdded a `test_groups` entry for `test_frontend_upnext_pager.py`. It maps to `client/frontend/src/data/videos.ts`, `client/backend/server.py`, `engine/server/data/similarity_candidates.py` and `engine/server/api/handlers/similar.py`, so the group is reselected when any of them changes.\n\n### `tests/tmp/probe_upnext_durable.py` (probe; please delete)\nThis probe re-imports the checkpoint's two offline tests: the one that feeds fixed batches to the durable file, and the one that checks the config mapping. Both passed when run through `ValidateTests`. The checkpoint's live test was not run. I have no tool that can delete files, so it is still there and should be removed.",
      "beyond": "tests/tmp/probe_upnext_durable.py \u2014 a probe that could not be deleted with the tools available; it holds no phase code and should be removed."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "First similar batch through the pager",
      "checkpoint": "Seam: the real page module `client/frontend/src/pages/video-page/index.ts`, bundled with esbuild (`--loader:.css=empty`) and imported in node under the recording-element runner copied from `tests/active/test_frontend_video_page.py`. It lives in a new `tests/active/test_frontend_video_page_similars.py`. The runner adds stubs: an `IntersectionObserver` whose callback and observed element are captured; `document.documentElement.scrollHeight` large and `window.innerHeight` small, so fill-viewport never loops; `window.scrollY`. `fetch` records the method, path and JSON body of each request. It answers POST `/recommendations` with 48 distinct rows (each with `video_id` and `instance_domain`) and `seed.mode: \"upnext\"`, and answers `{}` elsewhere. Asserts: exactly one `/recommendations` request was made, and its body's limit is \"48\"; the `#similar-videos` element's innerHTML holds exactly 8 `similar-card-item` anchors. Control: `/api/video` was requested. `tests/active/test_frontend_video_page.py` must still pass unchanged, which covers the empty first batch and the no-observer path.",
      "intent": "`loadSimilarVideos` in `pages/video-page/index.ts` fetches its first batch through a fresh feed pager asking `/recommendations` for 48 rows, and puts only the first 8 of them into `#similar-videos`.",
      "clauses": [
        {
          "id": "C1",
          "text": "The first `/recommendations` request the page makes carries limit 48."
        },
        {
          "id": "C2",
          "text": "From a 48-row answer, `#similar-videos` holds exactly 8 cards."
        }
      ],
      "files": [
        "client/frontend/src/pages/video-page/index.ts (EDITED)",
        "tests/active/test_frontend_video_page_similars.py (NEW)"
      ],
      "done": true,
      "outcome": "### `client/frontend/src/pages/video-page/index.ts` (EDITED)\n- The import from `../../data/videos` now also brings in `createFeedPager`.\n- Added a module constant `SIMILAR_CHUNK = 8` next to `similarStatsCache`/`similarStatsLoading`. It sits above `void loadSimilarVideos()`, so reading it cannot hit a TDZ error.\n- `loadSimilarVideos` no longer calls `fetchSimilarVideosPayload` directly with `limit: \"8\"`. After `await localLikesImported` it creates a fresh pager on each call (`createFeedPager((exclude) => fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: \"48\", apiBase }, exclude))`), so a key-rejected retry starts with nothing shown and nothing excluded. It then awaits `pager.next()` and renders only `rows.slice(0, SIMILAR_CHUNK)` into `#similar-videos` with `renderSimilarCard`. `queueSimilarStats` runs on those 8 rows only.\n- Unchanged: the empty-batch message (`No similar videos found.`), the `ProfileKeyRejectedError` \u2192 `keyRejectedNotice` retry, the escaped error message, the no-seed path and the similar-link blocks. The last are removed in phase 4.\n- The pager is a local here. The module state from the plan (all fetched rows, revealed count, loading/fetching flags, the current pager) and the scroll code belong to phase 3, which is the first phase that reads them.\n\n### `tests/active/test_frontend_video_page_similars.py` (NEW)\n- The durable home of this phase's checkpoint, as the plan names it. It has the same runner, fixture and single test as `tests/tmp/test_12_similars_on_scroll_phase2.py`, with the clause tags removed and the runner comment reworded for a file that phases 3 and 4 will extend.\n- It bundles the real page module with esbuild and imports it in node. It checks that exactly one `/recommendations` POST was made, with `limit=48` in the query. From a 48-row answer, `#similar-videos` must hold exactly 8 `similar-card-item` anchors, and they must be rows v0\u2013v7 in order. Control: `/api/video` was requested.\n\n### Observation\n- I ran the checkpoint `tests/tmp/test_12_similars_on_scroll_phase2.py` once through `ValidateTests` against this code: 1 passed.\n- That tool call wrote `tests/last_test_validation.json` / `tests/last_test_output.txt` for that one tmp path. I did not run anything under `tests/active` myself, including the new durable file and `test_frontend_video_page.py`.\n- `test_frontend_video_page.py` answers `/recommendations` with `{}`, so I expect it to take the pager's empty-batch path to `No similar videos found.`. That is a prediction; I did not observe it."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Reveal and page on scroll",
      "checkpoint": "Seam: the same node harness and file as phase 2 (`tests/active/test_frontend_video_page_similars.py`), after the first batch has rendered. The runner also records each `insertAdjacentHTML` call on `#similar-videos`, and invokes the captured `IntersectionObserver` callback with `[{ isIntersecting: true }]`. Fetch answers a second `/recommendations` POST with a disjoint batch. Asserts: one intersection adds exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call holding 8 `similar-card-item` anchors, and the grid's innerHTML is still the first 8 cards, not rewritten. After five further intersections have revealed all 48 rows, the next intersection sends a second `/recommendations` POST, and its exclude list holds exactly the 48 `(video_id, instance_domain)` pairs of the first batch. Control: the observer was constructed with the `#similar-sentinel` element.",
      "intent": "Once the first similar batch is shown, each sentinel intersection appends the next 8 fetched rows to `#similar-videos`, and an intersection that finds no unrevealed row asks the pager for the next batch, excluding the rows already shown.",
      "clauses": [
        {
          "id": "C1",
          "text": "A sentinel intersection appends the next 8 cards, and the cards already shown stay in place."
        },
        {
          "id": "C2",
          "text": "An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown."
        }
      ],
      "files": [
        "client/frontend/src/pages/video-page/index.ts (EDITED)",
        "client/frontend/video-page.html (EDITED)",
        "client/frontend/src/video.css (EDITED)",
        "tests/active/test_frontend_video_page_similars.py (EDITED)"
      ],
      "done": false,
      "outcome": "### `client/frontend/src/pages/video-page/index.ts`\n- The import from `../../data/videos` now also brings in `type FeedPager`.\n- Added a `similarSentinel` lookup (`#similar-sentinel`) next to `similarSection` and `similarCards`.\n- Added module paging state next to `SIMILAR_CHUNK` (8), placed above the module-load `void loadSimilarVideos()` call so the synchronous reset in that function does not hit a temporal-dead-zone (TDZ) error: `similarRows`, `similarRevealed`, `similarLoading`, `similarPager` (starts null), `similarFetchingMore` and `similarScrollAttached`. The `SIMILAR_CHUNK` comment now says it is both the first count and the per-scroll step.\n- `loadSimilarVideos`:\n  - It first resets the rows, the revealed count and `similarLoading = true`, and puts `Loading...` back in the grid, so a key-rejected retry starts from nothing.\n  - It stores the fresh pager in `similarPager`.\n  - After the first batch arrives, it drops a superseded call's result with `current !== similarPager`, on both the success and the error path.\n  - It clears `similarLoading` on every path, stores the rows and renders the first 8 through `innerHTML` as before.\n  - Only after a non-empty first batch does it call `setupSimilarScroll()` and then `fillSimilarViewport()`. On the empty path (which `tests/active/test_frontend_video_page.py` takes, answering `{}`), `IntersectionObserver`, `document.documentElement` and `innerHeight` are never touched.\n  - The `similarLinkInline` block stays; removing it is phase 4.\n- New `revealSimilarChunk()`:\n  - Does nothing while `similarLoading`.\n  - Appends the next up-to-8 fetched rows with `similarCards.insertAdjacentHTML(\"beforeend\", \u2026)` using the unchanged `renderSimilarCard`, and queues stats for that slice only.\n  - When no fetched row is left, it calls `void loadMoreSimilar()` and returns false.\n- New `loadMoreSimilar()`:\n  - Returns early without a pager, while loading, while a fetch is running, or when `pager.exhausted` is set.\n  - Otherwise awaits `pager.next()`; the pager supplies the `exclude` list of every row fetched so far.\n  - Drops a stale pager's result and appends new rows to memory.\n  - On failure it only calls `console.warn` and leaves the grid alone.\n  - After appending, it reveals once and runs fill-viewport, because the sentinel may still be in view.\n- New `fillSimilarViewport()`: while `scrollHeight <= innerHeight + 120`, it reveals chunks, up to 50 times, and stops at the first reveal that changes nothing. As the draft deliberately specifies, it does not also require unrevealed rows. The reveal that finds none left is the one that asks for the next batch; a comment says why.\n- New `maybeRevealSimilarOnScroll()`: reveals when `innerHeight + scrollY >= scrollHeight - 240`.\n- New `setupSimilarScroll()`: attached once per page view. It creates an `IntersectionObserver` (`rootMargin: \"200px\"`) on `#similar-sentinel` when the element exists, a passive `scroll` listener, and a `resize` listener that runs the scroll check and then fill-viewport.\n\n### `client/frontend/video-page.html`\n- Added `<div id=\"similar-sentinel\" class=\"similar-sentinel\" aria-hidden=\"true\"></div>` right after `#similar-videos`, inside `#similar-section`. It is hidden together with the section when there is no seed. Both links stay in place for phase 4.\n\n### `client/frontend/src/video.css`\n- Added a `.similar-sentinel { height: 1px; }` rule after `.similar-grid .loading, .similar-grid .error`. The home page's `.feed-sentinel` lives in `videos.css`, which this page does not import.\n\n### `tests/active/test_frontend_video_page_similars.py`\n- Not touched. It has already gated as phase 2's durable test, and it still holds as the code stands: its observer is never fired, and its tall document keeps fill-viewport from looping. The phase 3 checkpoint in `tests/tmp/` is the one this phase is gated on, and moving it into the active file is left to checkpoint promotion.\n\n### Not changed\n- `client/frontend/dist/` is not rebuilt. It stays stale until `npm run build`, as the impact inventory records."
    },
    {
      "n": "4",
      "kind": "code",
      "name": "Remove the see-all links",
      "checkpoint": "Seam, two boundaries. First, the served HTML file `client/frontend/video-page.html`, parsed with stdlib `html.parser`: no `a` element has an `href` containing `/videos.html`, and no element has id `similar-link` or `similar-link-inline`. Second, the phase 2 node runner in `tests/active/test_frontend_video_page_similars.py`, which reports every id passed to `document.getElementById`: neither `similar-link` nor `similar-link-inline` is among them after the page has loaded. Control: `similar-videos` is among them.",
      "intent": "The video page no longer offers a link to `/videos.html`: the anchor is gone from its HTML, and the module no longer looks up the link elements.",
      "clauses": [
        {
          "id": "C1",
          "text": "`video-page.html` contains no anchor to `/videos.html`."
        },
        {
          "id": "C2",
          "text": "The page module never looks up `#similar-link` or `#similar-link-inline`."
        }
      ],
      "files": [
        "client/frontend/video-page.html (EDITED)",
        "client/frontend/src/pages/video-page/index.ts (EDITED)",
        "tests/active/test_frontend_video_page_similars.py (EDITED)"
      ],
      "done": false
    }
  ],
  "digests": {
    "tests/tmp/test_12_similars_on_scroll_phase1.py": "b7ef0065171296ab09257fda4d2afcc9a27b3e21592724a6fc00017e1cc3661e",
    "tests/tmp/test_12_similars_on_scroll_phase2.py": "3fb92b6eb1fd150059f8002515d6b90c92658e11f95fde3e3daeb86344d5e5eb",
    "tests/tmp/test_12_similars_on_scroll_phase3.py": "3ea7c3ba8f6a7fea4ea2959c101118c409f88c392f690837eb847b0d1a80116a"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/12",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260928T081901-4996-dev-flow"
  ],
  "plan": "docs/project/plans/19-12-similars-on-scroll.md",
  "record": "docs/project/plans/19-12-similars-on-scroll.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nUsers keep browsing from the video page, and today it shows only 8 similar videos (`limit: \"8\"` in `loadSimilarVideos`, `client/frontend/src/pages/video-page/index.ts`). To see more, they must follow a link to a second page: the home feed in its up-next mode, `/videos.html?id=\u2026&host=\u2026` (`useSimilar` in `client/frontend/src/pages/videos/index.ts`). This build makes the video page itself offer a long list of up-next videos that loads as the user scrolls, the way the home page does, so they no longer need to leave it.\n\n### Context delivered by earlier builds (not to be changed)\n\n- Issue 09 (similars diversity) made every up-next response a random draw. A limit-48 request scores the seed's pool (at most `SIMILAR_VIDEO_TOP_K` = 300 rows), takes the top min(4 \u00d7 48 = 192, pool size) rows as the window, and draws 48 of them by score-weighted sampling. Two identical requests return different pages. The draw is described in `engine/server/api/recommendations/docs/OVERVIEW.md`. The Engine drops rows named in the request's `exclude` while it builds the pool, so a batch that excludes the rows already shown is drawn only from rows not yet shown.\n- The Client backend (`client/backend/server.py`) caps a feed request's page size at `FEED_PAGE_SIZE` = 48 (`min(limit or 48, 48)`) and forwards `limit = page_size * FEED_OVERFETCH_FACTOR` (2) to the Engine, so it can refill a page after removing blocked rows. The Engine caps `limit` at 2 \u00d7 `default_limit`. The Client refuses a feed request that excludes more than `MAX_FEED_EXCLUDE` = 500 videos.\n- `createFeedPager` in `client/frontend/src/data/videos.ts` already pages a feed. Each batch excludes the last 500 rows shown (keyed by `video_id` + `instance_domain`) and drops any row the Engine repeats anyway. After a batch that adds no new row, or that fails, `exhausted` is set and `next()` makes no further request. `fetchSimilarVideosPayload(query, exclude)` is the fetch the home page gives it.\n- Issue 11 (fast similars response) is archived. The video page already requests similars in parallel with the video's metadata.\n\n### R1 \u2014 One full batch per request\n\n- The video page requests up-next similars with `limit` 48 (the Client's `FEED_PAGE_SIZE`, equal to the Engine's `BATCH_SIZE`) instead of 8, through `fetchSimilarVideosPayload` with the seed's `id`, `host` and `apiBase`, as today.\n- No server change is required: the Client and Engine already serve a 48-row draw in a single response.\n\n### R2 \u2014 Progressive reveal from memory\n\n- The page keeps every row it has fetched in memory and renders only a revealed prefix of them into `#similar-videos`.\n- After the first batch arrives it reveals 8 cards, the same count the page shows today.\n- Each time the user nears the bottom of the page, it reveals the next 8 rows, appending cards and not re-rendering the ones already shown. \"Near the bottom\" works as on the home page (`client/frontend/src/pages/videos/index.ts`): an `IntersectionObserver` on a sentinel element placed after the grid, with `rootMargin: \"200px\"`, plus a passive `scroll` listener and a `resize` listener as a fallback (near bottom = `innerHeight + scrollY >= scrollHeight - 240`).\n- While the document is too short to scroll (`scrollHeight <= innerHeight + 120`) and unrevealed rows remain, it keeps revealing chunks until the page can scroll (bounded by a safety counter, as `maybeFillViewport` does on the home page).\n- Live view counts (`queueSimilarStats`) are requested only for the cards being revealed, not for the whole in-memory batch.\n\n### R3 \u2014 Paging past the first batch\n\n- Fetching goes through `createFeedPager` (one pager per page load), passing a function that calls `fetchSimilarVideosPayload` with the seed query and the pager's `exclude` list. Every later batch therefore excludes the rows already shown (up to the last 500), and rows the Engine repeats are dropped.\n- When a reveal finds no unrevealed rows left, the page asks the pager for the next batch, unless the pager is exhausted or a fetch is already in flight. New rows are appended to the in-memory list, and revealing continues. Because the sentinel may still be in view, it reveals at once and runs the fill-viewport step after appending, as the home page's `loadMoreVideos` does.\n- Paging ends for this page view at the first batch that adds no new row or that fails. A failure on any batch after the first leaves the cards already shown in place and is only logged with `console.warn`. No error replaces the grid.\n\n### R4 \u2014 Behaviour that stays as it is\n\n- The first similars request still waits for the local-likes import (`localLikesImported`) before it is sent.\n- If the first batch returns no rows, the grid shows `No similar videos found.`.\n- If the first batch fails, the grid shows the error's message (fallback text `Failed to load similar videos`), HTML-escaped.\n- If the first batch fails with `ProfileKeyRejectedError`, the grid shows `keyRejectedNotice` with a retry that reloads the similars from scratch, with a fresh pager and nothing shown.\n- Without a `seedId`, `#similar-section` stays hidden and nothing is fetched.\n- Cards keep today's markup and behaviour (`renderSimilarCard`): thumbnail, duration, title, channel, views and age, the liked or disliked badge from `cardReaction`, `data-video-key`, and a link to `/video-page.html?\u2026` for that row.\n- The metadata, reactions, block buttons and description behaviour of the page are untouched.\n\n### R5 \u2014 Remove the links to the separate similar-videos page\n\n- Remove the header nav link `<a id=\"similar-link\" \u2026>Similar videos</a>` and the section header link `<a id=\"similar-link-inline\" \u2026>Open full list</a>` from `client/frontend/video-page.html`, together with the code in `client/frontend/src/pages/video-page/index.ts` that looks them up and sets their `href`.\n- The section keeps its `Similar videos` heading.\n- `/videos.html?id=\u2026&host=\u2026` (the home page's `useSimilar` mode) stays working as it is, so old bookmarks still open. Nothing in the app links to it any more. This is a deliberate choice by the operator: links only, no removal of the mode and no redirect.\n- `client/frontend/dist/` is build output and is not edited by hand.\n\n### R6 \u2014 Replacement pager test\n\n- Add a durable test in `tests/active` that replaces the retired `tests/archive/upnext_random_draw/test_frontend_videos.py`. Like the retired file, it bundles `client/frontend/src/data/videos.ts` with esbuild and runs it in node against the real Client and Engine, with minimal in-memory `window`, `localStorage` and `sessionStorage`.\n- It drives `createFeedPager` over `fetchSimilarVideosPayload` for an up-next seed at limit 48, where the first batch has `seed.mode == \"upnext\"`, and asserts two things. First, no batch repeats a row (`video_id`, `instance_domain`) of any earlier batch, and the second batch is non-empty. Second, once a batch comes back empty, no later `next()` call makes a request, counted on the fetch function handed to the pager.\n- It must hold under 09's random draw. There is no control asserting that two plain fetches return the same page. The seed and batch budget must actually reach an empty batch: a seed pool is at most 300 rows, so at 48 per batch about 7 batches exhaust it. Otherwise the test has to show that its seed's pool ends within the budget.\n- Map the new test in `.un/skills/devsecops/config.json` to `client/frontend/src/data/videos.ts` (and to `client/backend/server.py`, which it runs through).\n- Update `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` to record that the `test_frontend_videos` item is covered by this build, leaving its other five tests open.\n\n### Baseline suite state\n\nBefore the build, the active suite (`tests/active`) passes: exit code 0, not a variant run. Record and output go to `tests/last_test_validation.json` and `tests/last_test_output.txt`. Working tests go in `tests/tmp`, retired ones in `tests/archive`, plans in `docs/project/plans`.\n\n### Out of scope\n\n- Any Engine or Client backend change to the up-next route, batch size, draw or exclude handling.\n- Removing or redirecting the `/videos.html?id=` mode.\n- The other five retired up-next tests tracked by issue 35.\n</requirements>\n\n<conflicts>\nThe issue asks to \"remove the separate similar videos page\", but the operator chose links only (R5): `/videos.html?id=\u2026` (`useSimilar` in `client/frontend/src/pages/videos/index.ts`) keeps working, and only the two links to it are removed. This is resolved by the operator's decision and recorded here so later steps do not delete the mode.\nThe retired `test_frontend_videos.py` paged 8-row batches and asserted that two plain fetches return the same page (its line 97). Under 09's random draw and a pool of up to 300 rows, that control fails and 6 batches of 8 never reach an empty batch. R6's replacement must drop that control and size its batch budget for 48-row batches.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe change is confined to the video page module (`client/frontend/src/pages/video-page/index.ts`), its HTML (`client/frontend/video-page.html`), one CSS rule in `client/frontend/src/video.css`, one new active test, one config entry and one issue note. No server file changes, and `createFeedPager` and `fetchSimilarVideosPayload` in `data/videos.ts` are used as they are.\n\n**R1, one full batch per request.** `loadSimilarVideos` stops calling `fetchSimilarVideosPayload` directly with `limit: \"8\"`. It builds one pager per page load with `createFeedPager`, and the pager's fetch function calls `fetchSimilarVideosPayload` with `{ id: seedId, host: seedHost, limit: \"48\", apiBase }` and the `exclude` list the pager passes in. The Client caps the page at 48 and over-fetches 96 from the Engine, so each response is one full 48-row draw, as R1 states.\n\n**R2, progressive reveal from memory.** The page keeps a small amount of module state next to the existing `similarStatsCache`: the rows fetched so far, how many are revealed, a `loading` flag for the first batch, a `fetchingMore` flag, and the current pager. One reveal function (the counterpart of the home page's `loadNextChunk`) moves the revealed count forward by 8 (a `SIMILAR_CHUNK` constant). It renders only the newly revealed slice with `renderSimilarCard`, appends it to `#similar-videos` with `insertAdjacentHTML(\"beforeend\", \u2026)` so earlier cards are never re-rendered, and calls `queueSimilarStats` on that slice only. The first render after the first batch uses `innerHTML` for the first 8 cards, which replaces the `Loading...` placeholder. The bottom is detected the same way as on the home page. A new `<div id=\"similar-sentinel\" class=\"similar-sentinel\" aria-hidden=\"true\">` is placed right after `#similar-videos` inside `#similar-section`, watched by an `IntersectionObserver` with `rootMargin: \"200px\"`. A passive `scroll` listener and a `resize` listener run the same check (`innerHeight + scrollY >= scrollHeight - 240`), and resize also runs fill-viewport. The fill-viewport function copies `maybeFillViewport`: while unrevealed rows remain and `scrollHeight <= innerHeight + 120`, it reveals chunks, stopping at 50 or when a reveal changes nothing. It runs after the first render and after every appended batch. `video.css` gets a 1px-height `.similar-sentinel` rule, because the home page's `.feed-sentinel` rule lives in `videos.css`, which this page does not import.\n\n**R3, paging past the first batch.** When the reveal function finds no unrevealed row, it calls a `loadMoreSimilar` modelled on the home page's `loadMoreVideos`. That function returns early while the first batch is loading, while a fetch is already running, or when `pager.exhausted` is set. Otherwise it awaits `pager.next()`, checks that the pager is still the current one, and appends the new rows to memory. On success it reveals right away and then runs fill-viewport, because the sentinel may still be in view and the observer would not fire again. On failure it calls `console.warn` and leaves the grid alone. The pager itself handles the stop rule: a batch with no new row, or a failed batch, sets `exhausted`, and after that no request is made.\n\n**R4, unchanged behaviour.** The first `pager.next()` still runs after `await localLikesImported`. An empty first batch shows `No similar videos found.`. A failed first batch shows the escaped message or `Failed to load similar videos`. `ProfileKeyRejectedError` passes through the pager unchanged (it rethrows), so the `keyRejectedNotice` path stays. Its retry calls `loadSimilarVideos` again, and that function now starts by resetting the in-memory rows and the revealed count, setting `loading`, putting `Loading...` back in the grid and creating a fresh pager. With no `seedId`, the section is hidden and the function returns before any pager, observer or listener exists. `renderSimilarCard`, the stats helpers, metadata, reactions, block buttons and description code stay as they are.\n\n**R5, link removal.** In the HTML I delete `<a id=\"similar-link\">` from the header nav and `<a id=\"similar-link-inline\">` from `.section-header`, and keep the `<h3>Similar videos</h3>`. In the module I delete the two `getElementById` constants, the top-level block that sets `similarLink.href`, and the block inside `loadSimilarVideos` that sets `similarLinkInline.href`. `pages/videos/index.ts` is not touched, so `/videos.html?id=\u2026&host=\u2026` keeps working. `dist/` is not edited.\n\n**R6, replacement test.** A new `tests/active/test_frontend_upnext_pager.py` follows the retired file's harness: an esbuild ESM bundle of `createFeedPager` and `fetchSimilarVideosPayload` from `data/videos.ts`, a node runner with in-memory `window`, `localStorage` and `sessionStorage`, the `engine_client` fixture, and the `linux` search seed. Changes from the old file: the page size is `\"48\"`; the two plain-fetch control runs are removed, and the first pager batch's `seed.mode` is reported and checked to be `upnext` instead; the budget is `MAX_BATCHES = 10`. The assertions are: the first and second batches are non-empty and share no row; no batch repeats a `(video_id, instance_domain)` row from any earlier batch; an empty batch appears before the last call in the budget, which is what shows this seed's pool ends within the budget; the counted calls go 1\u2026k up to the empty batch and do not increase after it. `.un/skills/devsecops/config.json` gets an entry mapping the test to `client/frontend/src/data/videos.ts` and `client/backend/server.py`. Issue 35 gets a comment saying the `test_frontend_videos` item is covered by this build's test, and its list item is marked as covered; the other five items stay open.\n\n**Why the budget is 10.** From `engine/server/data/similarity_candidates.py`: `_build_rows` takes the top `SIMILAR_VIDEO_TOP_K` (300) rows of the score-ranked candidates first, and only then drops excluded rows. Excluding shown rows therefore shrinks one fixed top-300 pool and does not bring in deeper ANN hits. At 48 per batch the pool runs out by about batch 7 (the author cap makes it shallower), so batch 8 comes back empty. Ten batches leave slack for rows a higher-nprobe fallback step turns up. Ten also keeps the exclude list at 480 or fewer entries, under the 500 cap, so the Engine always sees every row already shown within the budget.\n\n### Alternatives considered\n\n- **Pull the home page's infinite-scroll code into a shared helper used by both pages.** Rejected for this build. It would change `pages/videos/index.ts`, whose state layout (sample, shuffle, modes) is different, and the scope says to leave that page alone. The copy is about 40 lines. This is deliberate duplication: if a third paged surface shows up, that is the point to extract the helper.\n- **Page by requesting 8 rows at a time from the server.** Rejected by R1, and each request rebuilds and scores the pool, so eight times the requests for the same rows.\n- **Render all 48 rows as soon as they arrive.** Rejected by R2. It would also fire live-stats requests for 48 cards the user may never scroll to.\n- **Switch to the home page's `video-card` component.** Rejected by R4, which keeps `renderSimilarCard` markup.\n- **Set up the observer and listeners at module load, as the home page does.** Rejected. See the first risk below. They are created once, the first time a first batch returns rows.\n\n### Gotchas and risks\n\n- **Existing test environment.** `tests/active/test_frontend_video_page.py` imports the real page module in node, with no `IntersectionObserver`, no `document.documentElement` and no `innerHeight`, and it answers `/recommendations` with `{}`. If the observer or listeners were created at module load, or on an empty first batch, that test would break. Creating them only after a non-empty first batch keeps it passing unchanged. The test's `window.addEventListener` stub already exists.\n- **Rows without a `video_id` or host** are dropped by the pager and were not dropped before. The Engine always sets both, so in practice nothing changes. I'm noting it, not handling it.\n- **Later batches can be slower.** Once exclusions shrink the cached pool below 48 rows, the Engine runs its live ANN fallback. Nothing shows while that fetch runs (the home page has no indicator either). The cards already shown stay usable.\n- **The test's empty-batch assertion depends on the Engine's current pool rule** (top 300, then exclude). If that rule changes to refill from deeper hits, the test fails loudly, printing the batch sizes. It does not pass vacuously.\n- **Test runtime.** About 8 Client\u2192Engine round trips, some running the fallback. The runner keeps the retired file's 300 s timeout.\n- **Layout.** Where the similar section sits below a tall player, the page is usually scrollable already, so fill-viewport rarely runs. It matters on very tall screens and after a resize.\n\n### Tradeoffs asked of the operator\n\n- The list ends quietly when the seed's pool runs out (about 300 rows at most, often fewer), with no \"end of list\" marker. This matches the home page.\n- A failure on a later batch is only a `console.warn`. The user sees paging stop with no message, as R3 specifies.\n- Up to a few hundred cards can build up in the DOM during one page view. There is no windowing or virtualisation. That is a deliberate simplification; windowing is the upgrade path if it ever matters.\n- The scroll code is copied from the home page rather than shared, as described under the first alternative.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impacts>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"import line 6 (`fetchSimilarVideosPayload, resolveApiBase` from ../../data/videos) and line 20 (`type { VideoRow }`)\">\n**What changes.** Line 6 adds `createFeedPager` and the type `FeedPager` (and `ExcludedVideo` if the fetch closure gets an annotation). `fetchSimilarVideosPayload` is still imported, but it is only called inside the pager's fetch closure. The type import at line 20 may need `VideosPayload` if module state or return types name it (`client/frontend/src/types/videos.ts:86`).\n\n**What depends on it.** esbuild's bundle of this module in `tests/active/test_frontend_video_page.py:92` and the vite build (`vite.config.ts:89`). `data/videos.ts` already imports `./cache`, `./local-likes`, `./api-base` and `./profile`, so the bundle graph does not grow.\n\n**Risk: low.** A misspelt named import fails `npm run build` and the esbuild step of test_frontend_video_page, whose `check=True` turns a failure into a fixture error.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"element lookups: `similarLink` (line 43) and `similarLinkInline` (line 51) removed; new `#similar-sentinel` lookup added beside `similarSection`/`similarCards` (49-50)\">\n**What changes.** Two `getElementById` constants are deleted and one is added (e.g. `similarSentinel`).\n\n**What depends on it.**\n- A grep for `similarLink` in `client/frontend/src` finds only lines 43, 51, 75-80 and 296-300, so nothing else reads the removed constants.\n- The test stub's `getElementById` creates an element for any id (`test_frontend_video_page.py:63`), so a new lookup is harmless there.\n\n**Risk: low.** If any reference is left behind, tsc and vite fail to compile, which gives a loud failure rather than a silent one.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"top-level block `if (similarLink && seedId) { \u2026 similarLink.href = `/videos.html?\u2026` }` (lines 75-80)\">\n**What changes.** The block is deleted (R5).\n\n**What depends on it.** Nothing else. The description-toggle block (82-90) and `localLikesImported` (93-95) directly below it are independent of it. The archived plan 19-14 describes the description block as \"next to the `similarLink` wiring\" (`docs/project/plans/archive/19-14-collapsible-description.md:567`). That wording is historical and archived, so no edit is needed.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"module state next to `similarStatsCache`/`similarStatsLoading` (lines 72-73): new `SIMILAR_CHUNK = 8`, rows, revealed count, `loading`, `fetchingMore`, current pager, observer/listeners-attached flags\">\n**What changes.** New `let`/`const` module state is added in the file's style. `statsNumberFormat` and `DESCRIPTION_CLAMP_LINES` (55-57) set the precedent for module constants.\n\n**Home-page counterparts.** `pages/videos/index.ts:84-97` holds the equivalents: `state.loading`, `pager`, `fetchingMore`, `feedObserver`, `fallbackListenersAttached`. That file's `CHUNK_SIZE` is 6 (line 69); this page uses 8 per R2.\n\n**Ordering constraint.** The module calls `void loadSimilarVideos()` at line 98, before most function declarations. Functions hoist, but `let`/`const` state does not: any state that `loadSimilarVideos` touches synchronously (before its first `await`) must be declared above line 98, or it throws a TDZ ReferenceError at import. The plan's reset of rows, revealed count, `loading` and the `Loading...` placeholder happens synchronously at the top of `loadSimilarVideos`, so this constraint applies to it directly.\n\n**What depends on it.** The new reveal, load-more and fill functions, and `loadSimilarVideos`.\n\n**Risk: medium.** A TDZ error would break the whole page module, and it would also make `test_frontend_video_page.py` exit non-zero. That test would catch it, which is good.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"loadSimilarVideos() (lines 290-325)\">\n**What changes.**\n1. The early returns stay: missing elements, and no `seedId` (the section is hidden, R4).\n2. The `similarLinkInline` block (296-301) is deleted.\n3. New reset step: clear rows, set revealed = 0, set `loading = true`, put `<div class=\"loading\">Loading...</div>` back into `similarCards`, and create a fresh `createFeedPager((exclude) => fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: \"48\", apiBase }, exclude))`.\n4. `await localLikesImported` stays before the first `pager.next()`.\n5. The success path clears `loading`, stores the rows, renders the first 8 via `innerHTML` and `queueSimilarStats` on that slice only, sets up the observer and listeners once, then runs fill-viewport.\n6. An empty result keeps `No similar videos found.`.\n7. The catch keeps the `ProfileKeyRejectedError` \u2192 `keyRejectedNotice(() => void loadSimilarVideos())` branch and the escaped message with the `Failed to load similar videos` fallback. `loading` must also be cleared on the error path.\n\n**What depends on it.**\n- The module-load call at line 98.\n- The `keyRejectedNotice` retry, via `client/frontend/src/components/key-rejected.ts:11`, whose `onForget` callback is what re-invokes it.\n- `test_frontend_video_page.py`, which answers `/recommendations` with `{}`. `createFeedPager` then returns `{rows: []}` and sets `exhausted` (`data/videos.ts:57-66`), so the page takes the \"No similar videos found.\" branch and no observer is created. The test asserts nothing about similars but needs the process to exit 0.\n\n**Behaviour deltas.**\n- **Row filter.** The pager drops rows lacking `video_id` or `instance_domain` (`data/videos.ts:58-61`). The old code rendered them.\n- **`seedHost` null.** `fetchSimilarVideosPayload` omits `host`, as before (`buildSimilarUrl`, lines 101-102).\n- **Stale pager.** On retry, a stale in-flight `loadMoreSimilar` must see `current !== pager` and drop its result, as the home page does (`pages/videos/index.ts:239`).\n- **Double run.** If `loadSimilarVideos` were entered twice concurrently, which only the retry can do, the older call's result would overwrite the grid. The home page has the same shape and does not guard it. Low likelihood, since the retry button appears only after the first call has finished.\n\n**Risk: medium.** This is the core behaviour change. The R4 paths (empty, error, key-rejected, no seed) have no automated coverage beyond test_frontend_video_page's exit code.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"new functions: reveal-next-chunk (counterpart of `loadNextChunk`), `loadMoreSimilar` (counterpart of `loadMoreVideos`), fill-viewport (counterpart of `maybeFillViewport`), scroll check (counterpart of `maybeLoadOnScroll`), observer/listener setup (counterpart of `setupInfiniteScroll`)\">\n**What changes.** About 40 new lines, copied from `client/frontend/src/pages/videos/index.ts:232-375`, with these differences:\n- **Append-only render.** The reveal appends only the new slice via `similarCards.insertAdjacentHTML(\"beforeend\", slice.map(renderSimilarCard).join(\"\"))` and calls `queueSimilarStats(slice)`. The home page's `renderCards` re-renders the grid instead.\n- **Load-more trigger.** Reveal returns false and calls `void loadMoreSimilar()` when nothing is left to reveal.\n- **`loadMoreSimilar` guards.** It returns on `loading || fetchingMore || pager.exhausted`, checks `current !== pager` after the await, and appends rows. It logs `console.warn` on failure and never touches the grid. On success it reveals, then runs fill-viewport.\n- **Fill-viewport.** It is bounded by a safety counter of 50, the condition `scrollHeight <= innerHeight + 120`, and stops when a reveal changes nothing.\n- **Scroll check.** `innerHeight + scrollY >= document.documentElement.scrollHeight - 240`.\n- **Observer and listeners.** `IntersectionObserver` with `rootMargin: \"200px\"` on `#similar-sentinel`, a passive `scroll` listener, and a `resize` listener that runs both the scroll check and fill-viewport. All are created only after a non-empty first batch, and attached once (a flag like `fallbackListenersAttached`).\n\n**What depends on it.**\n- **Stats.** `applySimilarStatsToDom` (1090-1097) finds cards by `data-video-key` inside `similarCards`, so appended cards receive stats. `queueSimilarStats` skips keys already cached or loading (989-990), so revealing in slices causes no duplicate fetches.\n- **Retry reuse.** On a retry the observer and listeners are reused and keep calling the reveal, which reads the current module state. The home page instead disconnects the observer and re-creates it (352-356). Either works, as long as the reveal is a no-op while `loading`.\n\n**Environment.** `IntersectionObserver`, `document.documentElement` and `window.innerHeight` are absent in the test_frontend_video_page stub (lines 24-76). Any call at module load, or on the empty-first-batch path, throws in node.\n\n**Loading guard.** The observer can fire right after `observe()` if the sentinel is within 200px of the viewport. The reveal must be a no-op, or at most a reveal from memory, while `loading`.\n\n**Later-batch key rejection.** A `ProfileKeyRejectedError` on a later batch is swallowed by the warn path. Paging stops silently and no notice is shown. This is consistent with R3 (only the first batch shows errors), but it differs from the first-batch path.\n\n**Risk: medium.** None of this is exercised by any automated test: node has no layout, and no browser harness exists. The maintainer's browser check is the only verification of reveal, append, observer and fill.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"renderSimilarCard (1168-1201), queueSimilarStats (973-1000), fetchSimilarStatsForHost/fetchViewsIndividually/fetchBatchViews/fetchSingleViews (1005-1085), applySimilarStatsToDom (1090-1097), resolveSimilarKey/resolveSimilarStats (936-953), videoPageUrl (1135-1156)\">\n**What changes.** Nothing (R4).\n\n**What depends on them.** The new reveal function. `queueSimilarStats` now runs per 8-card slice. Each slice groups by host and issues one PeerTube `/api/v1/videos?id=\u2026` batch per host, so live-stats requests to remote instances grow with scrolling: at most about 300 cards over a long page view. `fetchBatchViews` puts every id in the URL query. At 8 per slice the URL stays short.\n\n**Risk: low.**\n</impact>\n<impact path=\"client/frontend/video-page.html\" element=\"header nav `<a id=\\\"similar-link\\\" class=\\\"nav-link\\\" href=\\\"/\\\">Similar videos</a>` (line 22)\">\n**What changes.** The link is deleted (R5). The nav keeps Home, Likes, Search and About.\n\n**What depends on it.** `.header-nav` in `video.css` is a fixed flex pill, so one fewer link only narrows it. No script reads the element once lines 43 and 75-80 are gone.\n\n**Risk: low.**\n</impact>\n<impact path=\"client/frontend/video-page.html\" element=\"`#similar-section` (lines 124-132): `<a id=\\\"similar-link-inline\\\" \u2026>Open full list</a>` removed from `.section-header`; new `<div id=\\\"similar-sentinel\\\" class=\\\"similar-sentinel\\\" aria-hidden=\\\"true\\\"></div>` after `#similar-videos`\">\n**What changes.**\n- The inline link is deleted, and the `<h3>Similar videos</h3>` stays. `.section-header` (`video.css:521-527`, `justify-content: space-between`) then holds a single h3, which renders left-aligned. No CSS change is needed.\n- The sentinel sits inside `#similar-section`, after the grid. It is hidden along with the section when there is no seed.\n\n**What depends on it.**\n- The module's sentinel lookup and observer.\n- `.un/skills/devsecops/config.json:148-152` maps test_frontend_video_page to this file, so the edit reselects that test.\n\n**Risk: low.** The static `Loading...` placeholder (line 130) is kept, and the module rewrites it on a retry.\n</impact>\n<impact path=\"client/frontend/src/video.css\" element=\"new `.similar-sentinel { height: 1px; }` rule, near `.similar-grid` (534-538) / `.similar-grid .loading, .error` (616-620)\">\n**What changes.** One new rule, mirroring `.feed-sentinel` in `client/frontend/src/videos.css:132-134`. The video page imports only `video.css` (`pages/video-page/index.ts:5`), and a grep finds no `@import` in either stylesheet, so the plan's reason for the new rule holds.\n\n**What depends on it.** The sentinel element. test_frontend_video_page loads CSS as `--loader:.css=empty`, so the test is unaffected, though the config mapping reselects it.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/videos.css\" element=\".feed-sentinel (132-134)\">\n**What changes.** Nothing. It is the model for the new rule.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/data/videos.ts\" element=\"createFeedPager (37-70), MAX_FEED_EXCLUDE (28), fetchSimilarVideosPayload (130-157), buildSimilarUrl (98-107)\">\n**What changes.** Nothing. The file gains a second production consumer, the video page, alongside `pages/videos/index.ts:94,181`.\n\n**Facts the page relies on.**\n- `next()` rethrows the fetch error after setting `exhausted` (51-55), so `ProfileKeyRejectedError` from a 401 (143-145) reaches the page's catch unchanged.\n- Rows are keyed `video_id::instance_domain`, and rows without either are dropped.\n- Each call sends the last 500 shown as `exclude`.\n- A keyless body carries `getRandomLikes()` on every batch (line 133), so each batch may be personalised with a different random likes sample. The home page does the same.\n\n**What depends on it.** test_frontend_blocks (mapped at `config.json:75-81`) and the new test, which bundles `createFeedPager` and `fetchSimilarVideosPayload`.\n\n**Risk: none to the file.** Any future edit to it now affects two pages and two tests.\n</impact>\n<impact path=\"client/frontend/src/pages/videos/index.ts\" element=\"useSimilar mode (78, 212-214), loadVideos/loadMoreVideos/loadNextChunk/maybeFillViewport/maybeLoadOnScroll/setupInfiniteScroll (171-375)\">\n**What changes.** Nothing (R5, and the rejected alternative). `/videos.html?id=\u2026&host=\u2026` keeps working for bookmarks, and nothing in the app links to it any more.\n\n**Why it matters.** It is the source of the copied scroll code, so the two copies now drift independently (the deliberate duplication).\n\n**Doc impact.** `docs/project/issues/plan.md:91` lists \"the `?id=` mode of `pages/videos/index.ts`\" among this issue's files. That is no longer true under the operator's links-only decision.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/types/videos.ts\" element=\"SimilarSeed (64-68), VideosPayload (86-91)\">\n**What changes.** Nothing.\n\n**Why it matters.** `SimilarSeed` has no `mode` field. The new test reads `payload.seed?.mode` in plain JS in the runner, so this is not a type issue. If the page ever typed that read, it would need the field. The page itself does not read `seed`.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/components/key-rejected.ts\" element=\"keyRejectedNotice(onForget) (line 11)\">\n**What changes.** Nothing. Its callback re-invokes `loadSimilarVideos`, which now resets state and builds a fresh pager.\n\n**Risk: low.** The retry must not leave `loading` stuck at true. If it did, the observer and scroll checks would stay dead after a successful retry.\n</impact>\n<impact path=\"client/frontend/dist/video-page.html\" element=\"built HTML and `dist/assets/video-*.js` / `video-*.css`\">\n**What changes.** Nothing by hand (R5). They go stale until `npm run build`, and still contain both links and the `limit:\"8\"` call (grep confirms at dist lines 28 and 109 and in the asset). A deploy needs a build followed by the rsync described in the archived plan 19-14.\n\n**Risk: low (operational).** Deploying without a build ships the old page.\n</impact>\n<impact path=\"tests/active/test_frontend_video_page.py\" element=\"RUNNER stubs (24-85) and the three taxonomy tests\">\n**What changes.** Nothing. It must keep passing as it is.\n\n**What the runner provides.**\n- `window` has `location`, the storages and `addEventListener() {}`, but no `innerHeight` or `scrollY`.\n- `document` has no `documentElement`, and there is no `IntersectionObserver`.\n- Elements have a no-op `insertAdjacentHTML`.\n- `fetch` answers `{}` for every path except `/api/video`.\n\n**Why it still passes.** The first batch is empty, so the page takes the \"No similar videos found.\" path and never reaches observer or listener code. The test waits only 5\u00d710 ms. The similars path is independent of the assertions, but an unhandled rejection or synchronous throw at import would fail it (non-zero exit, or a missing stdout line).\n\n**Reselection.** `config.json:148-152` maps it to all three changed frontend files, so it is reselected.\n\n**Risk: medium.** It is the only automated guard on the page module, and it guards only against crashes.\n</impact>\n<impact path=\"tests/active/test_frontend_upnext_pager.py\" element=\"new test module (R6)\">\n**What changes.** A new file following the retired file's harness (`tests/archive/upnext_random_draw/test_frontend_videos.py:30-89`):\n- `FRONTEND = parents[2]` (active depth; the archive uses `parents[3]`), `PAGE = \"48\"`, `MAX_BATCHES = 10`.\n- A runner without the two plain-fetch control runs (archive lines 47-50). It reports `seed.mode` of the first pager batch instead.\n- The `engine_client` fixture, the `linux` seed via `GET /api/v1/search/videos?q=linux&limit=1`, and a 300 s timeout.\n- The runner's `window` in the archive lacks `sessionStorage` (line 41). The plan says to add it, as `test_frontend_video_page.py` does.\n\n**Assertions.** Batches 1 and 2 are non-empty and disjoint. No batch repeats an earlier row. An empty batch exists at an index below the last. Calls count 1\u2026k up to the empty batch and stay flat after it. The archive's `assert all(\"error\" not in b \u2026)` is presumably kept.\n\n**Dependencies.**\n- **Client.** `client/backend/server.py`: the `FEED_PAGE_SIZE` cap (69, 457) and the exclude validation (524-535).\n- **Engine pool rule.** `get_upnext_candidates` in `engine/server/data/similarity_candidates.py:119-179` / `_upnext_rows` (182-197), which exclude after `_build_rows(top_k=300)`, plus `seed.mode = \"upnext\"` in `engine/server/api/handlers/similar.py:857-858`. The empty-pool branch (867+) answers without `mode`, but that affects only batches after the first.\n\n**Flake exposure.**\n1. Later batches drive the pool below `SIMILAR_VIDEO_TARGET_MIN_POOL` (48), so each runs the ANN fallback, up to 3 FAISS searches reaching nprobe 128 / k 20000. The Engine's 5 s deadline turns an overrun into a 500 (`DEPLOYMENT.md:260`). The Client's proxy timeout is 10 s (`server.py:77-79`). A 500 or 502 throws in `next()`, which sets `exhausted` and fails the no-error assertion. That is a timing-dependent failure.\n2. A higher-nprobe fallback can surface new high-scoring hits into the top 300. The pool is therefore not strictly fixed, which is the plan's \"slack\" (batches 8-9).\n3. The Engine's own limiter is `DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60` per 60 s (`engine/server/api/server_config.py:450-451`). The fixture relaxes only the Client limiter (`conftest.py:175`). The session Engine is shared with test_similar's many `/recommendations` calls when they run in one pytest process. I did not check how lanes split groups, so whether ~10 more requests can hit a 429 is unverified.\n\n**Existing coverage.** `tests/active/test_similar.py` already shows that the linux seed fills a 48-row page (the `\u2026fills_a_48_row_page\u2026[linux]` test in `tests/last_test_validation.json`), so batch 1 at 48 is non-empty.\n\n**Risk: medium-high (flakiness).** The file is new; it breaks nothing existing.\n</impact>\n<impact path=\"tests/archive/upnext_random_draw/test_frontend_videos.py\" element=\"retired pager test (whole file)\">\n**What changes.** Nothing. It stays skipped (`pytestmark` at line 28) and serves as the template. Its docstring still says \"issue 35 tracks a replacement\", which is historical. It could gain a pointer to the new file, but that is optional.\n\n**Risk: none.**\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"engine (105-145, session-scoped, RECOMMENDATIONS_DEBUG=1) and engine_client (148-150 \u2192 _engine_client 164-184, Client RateLimiter(100000, 60))\">\n**What changes.** Nothing.\n\n**Why it matters.** The new test uses `engine_client`, whose `.base` is the Client URL (line 180). The Client's limiter is relaxed there; the Engine's is not (see the new-test entry).\n\n**Risk: none to the file.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"FEED_PAGE_SIZE=48 / FEED_OVERFETCH_FACTOR=2 (69-70), _profile_filter (442-473), exclude validation (524-535), ENGINE_PROXY_TIMEOUT_SECONDS=10 (77-79), RATE_LIMIT_MAX_REQUESTS=90 per 60 s (62-63)\">\n**What changes.** Nothing (out of scope).\n\n**Correction to the plan.** The plan says \"the Client caps the page at 48 and over-fetches 96\". The code over-fetches (limit = 96) only for a keyed request whose profile has blocks or dislikes (line 471). Keyless requests, and the new test, send `limit=48` to the Engine.\n\n**Other facts.**\n- The 500-entry exclude cap is never reached within the test budget (at most 9 \u00d7 48 = 432) or in a real page view, since the pool is \u2264 300.\n- A browser scrolling to the pool's end makes about 7 `/recommendations` requests per page view, well under the production limiter's 90 per minute.\n\n**Risk: none to the file.** Mapped as a dependency of the new test.\n</impact>\n<impact path=\"engine/server/data/similarity_candidates.py\" element=\"get_upnext_candidates (119-179), _upnext_rows (182-197)\">\n**What changes.** Nothing.\n\n**Why it matters.**\n- It confirms the plan's budget reasoning: `_build_rows(..., policy.top_k)` (300) runs before the exclude filter (192-195), and \"an excluded row does not free its channel's slot\".\n- The fallback runs when `len(rows) < target_min_pool` (48) (line 151). Once a page view has shown enough rows, every later batch pays up to 3 live searches.\n\n**What depends on it.** The new test's empty-batch assertion. It is not mapped to the new test in the plan's config entry (see config.json).\n\n**Risk: none to the file.** A future change to refill from deeper hits fails the new test.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"_handle_similar limit cap (941-947: max 2 \u00d7 default_limit), mode stamp (1006, 857-858), empty-pool 200 branch (867+)\">\n**What changes.** Nothing.\n\n**Why it matters.**\n- `limit=48` is accepted.\n- The first non-empty batch carries `seed.mode == \"upnext\"`, which the new test asserts.\n- An empty batch comes back as 200 with no rows, which the pager turns into `exhausted`.\n\n**Risk: none.**\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups: new `test_frontend_upnext_pager.py` entry (after line 152)\">\n**What changes.** A new entry mapping to `client/frontend/src/data/videos.ts` and `client/backend/server.py`, per the plan. No stale `test_frontend_videos.py` entry exists (grep finds none), so none needs dropping.\n\n**Gap.** The test's empty-batch and no-repeat assertions depend on Engine behaviour: `engine/server/data/similarity_candidates.py` and `engine/server/api/handlers/similar.py`. Issue 35 line 26 itself recommends mapping those to the frontend tests. Without them, an Engine-only change will not reselect this test. I suggest adding both; this is a deviation from the plan's two-file list and needs the operator's OK.\n\n**Risk: low.**\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"groups / tests record\">\n**What changes.** It is regenerated by the validation run. It will gain a `test_frontend_upnext_pager.py` group and new digests for `test_frontend_video_page.py`. Not hand-edited.\n\n**Risk: none.**\n</impact>\n<impact path=\"docs/project/issues/35-upnext-tests-retired-by-random-draw.md\" element=\"coverage list item `test_frontend_videos` (line 17), Proposed solution (26), Comments (33)\">\n**What changes.**\n- A comment under `## Comments` saying the pager coverage is restored by `tests/active/test_frontend_upnext_pager.py` from build 12. Include what changed from the retired file: 48-row batches, no plain-fetch control, `MAX_BATCHES = 10`, and the empty batch reached because the Engine takes the top 300 before excluding.\n- Line 17 is marked covered. The list items are bullets, not checkboxes, so this has to be text such as \"(covered by \u2026)\".\n- Line 26's \"drop the `test_frontend_videos.py` entry until a replacement exists\" is already satisfied and could note that.\n- The other five items stay open, and the Status stays `needs-triage`.\n\n**Risk: none.**\n</impact>\n<impact path=\"docs/project/issues/12-similars-on-scroll.md\" element=\"whole issue\">\n**What changes, at harvest.** `Status: enhancement, complete` and a move to `docs/project/issues/archive/`, per the triage labels. Also add a delivery comment covering:\n- the operator's links-only decision (`/videos.html?id=` kept);\n- the 48-row batch revealed 8 at a time;\n- that the list ends when the seed's pool (\u2264 300) runs out;\n- that later-batch failures are console-only.\n\n**Risk: none.**\n</impact>\n</impacts>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"client/frontend/README.md\">\nUnder \"What it does\", after line 13, add a bullet: the video page's similar section fetches one 48-row up-next batch through `createFeedPager`, reveals 8 cards at a time as scrolling nears the bottom, and fetches the next batch, excluding the rows already shown, when the revealed rows run out. Paging ends after an empty or failed batch, and a later failure is only logged. Line 9 (\"similar to one video\") can stay, since `/videos.html?id=` still works. Line 10's feed-paging bullet can say that the video page uses the same pager.\n</doc>\n<doc path=\"DEPLOYMENT.md\">\nIn \"Up-next logs and load\" (lines 253-260), note that one video page view now sends a sequence of up-next requests as the visitor scrolls: a 48-row batch each, carrying `exclude`, up to about 7 before a 300-row pool runs out. Once the unshown pool drops below 48 rows, each of these runs the ANN fallback. That multiplies the per-page-view `index_lock` load that the capacity paragraph describes.\n</doc>\n<doc path=\"docs/project/issues/35-upnext-tests-retired-by-random-draw.md\">\nAdd a comment recording that `tests/active/test_frontend_upnext_pager.py` from build 12 replaces the `test_frontend_videos` item: 48-row batches, no plain-fetch control, 10-batch budget, empty batch reached because the Engine takes the top 300 before excluding. Mark line 17 as covered and leave the other five items and the status open.\n</doc>\n<doc path=\"docs/project/issues/12-similars-on-scroll.md\">\nAt harvest: set `Status: enhancement, complete`, add a delivery comment (links removed and the `/videos.html?id=` mode kept by operator decision, 48-row batch revealed 8 at a time, list ends at the pool's end with no marker, later-batch failure is console-only, no DOM windowing), then move the file to `docs/project/issues/archive/`.\n</doc>\n<doc path=\"docs/project/issues/plan.md\">\nLine 42 (P2 row): strike 12 as delivered. Line 91 (row 4a): mark it delivered and correct the file list. The `?id=` mode of `pages/videos/index.ts` and the similar route limit were not changed. The files are `pages/video-page/index.ts`, `video-page.html`, `video.css` and the new test.\n</doc>\n<doc path=\"docs/project/roadmap.md\">\nIn the delivered list (lines 14-20), add an entry for issue `12`, similars on scroll: the video page pages up-next similars on scroll, 48 per request and revealed 8 at a time, and no longer links to the separate similar-videos page. Point it at `docs/project/plans/19-12-similars-on-scroll.md`, or its archived path after harvest.\n</doc>\n</docs_checklist>\n\n<highest_risk>\n`tests/active/test_frontend_upnext_pager.py` (new): later batches drive the unshown pool below 48, so each runs up to three live ANN searches (nprobe up to 128, k up to 20000) under the Engine's 5 s deadline and the Client's 10 s proxy timeout (`client/backend/server.py:77`). A 500 or 502 makes `next()` throw and fails the no-error assertion. The session Engine's own 60/60 s per-path limiter (`engine/server/api/server_config.py:450`) is not relaxed by the fixture. Whether this test shares that bucket with test_similar's many `/recommendations` calls in one pytest process is unverified. Both can cause timing-dependent failures.\n`client/frontend/src/pages/video-page/index.ts` `loadSimilarVideos` plus the new module state: `void loadSimilarVideos()` runs at line 98, before later declarations, so any `let`/`const` state it touches before its first `await` must be declared above line 98 or the module throws a TDZ error at import. The observer and listeners (and `IntersectionObserver`, `document.documentElement`, `innerHeight`) must not be touched on the empty-first-batch path, which is exactly what `tests/active/test_frontend_video_page.py` exercises with `{}`. `loading` must be cleared on every exit path, or scrolling stays dead after a key-rejected retry.\nThe scroll, reveal and paging code in `client/frontend/src/pages/video-page/index.ts` has no automated coverage beyond a crash check. Append-only reveal via `insertAdjacentHTML`, the fill-viewport loop, observer re-fire after an appended batch, and the stale-pager check are verified only by the maintainer's browser check, and `client/frontend/dist/` stays stale until `npm run build`.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the files at its paths. The plan holds and the inventory is essentially complete. I read the page module (imports, the element lookups at 43/51, the link block at 75-80, `loadSimilarVideos` at 290-325, the stats helpers, `renderSimilarCard`), `data/videos.ts`, the home page's scroll code (`pages/videos/index.ts:84-97, 171-375`), `test_frontend_video_page.py`, the retired pager test, `video-page.html`, `video.css`, `conftest.py`, the Client's `_profile_filter` and exclude validation, `similarity_candidates.py`, the Engine handler (`similar.py` 760-874, 941-947, 1100-1124), the Engine rate limiter, `config.json`, issue 35, issue 12 and `plan.md:91`. Every entry held except one partial claim about when the ANN fallback runs, listed under unconfirmed. The inventory left one question open (can the Engine limiter 429 the new test), and the tree answers it: under `validate_tests.py` each test group runs in its own pytest subprocess, which starts its own session-scoped Engine. The limiter is keyed `ip:path` at 60 per 60 s (`similar.py:592-599`, `http_utils.py:59-84`). The new test makes at most 10 `/recommendations` calls plus one search, which sits on a different path. So there is no 429 under the validator. Only a bare single-process `pytest tests/active` run, where `test_similar` also calls `/recommendations` many times, could hit one. A repo-wide grep finds no other reference to `similar-link`, \"Open full list\" or `videos.html?id` outside `dist/`, a `delete_me/` backup directory and this build's own plan files.\n<question id=\"1\">\nYes. **Pager and page wiring.** `createFeedPager` (`data/videos.ts:37-70`) does what R1/R3 need: it excludes every row shown so far (the last 500), drops repeats, sets `exhausted` on an empty or failed batch and rethrows errors. `ProfileKeyRejectedError` therefore reaches the page's catch as the plan says. Cards are plain `<a>` markup with no per-card listeners (`renderSimilarCard`, 1168-1201). `applySimilarStatsToDom` looks cards up by `data-video-key` inside `similarCards` (1090-1097), so appended cards work and receive stats. `.similar-grid` is an auto-fit CSS grid and `.video-main` is a single column that scrolls the window. There is no inner scroll container, so window-based bottom detection is correct. `video.css` has no sentinel rule, which confirms the need for the new one.\n\n**Budget reasoning.** `_upnext_rows` runs `_build_rows(..., top_k=300)` before the exclude filter (`similarity_candidates.py:190-195`). `_draw_page` draws 48 from a window of at most 4\u00d748 (`similar.py:834, 1100-1124`). At 48 per batch the pool runs out in about 7 batches, and `MAX_BATCHES = 10` leaves slack for fallback escalation.\n\n**Existing test.** `test_frontend_video_page.py` answers `/recommendations` with `{}`. The pager returns no rows, so the page takes the \"No similar videos found.\" path and never reaches observer code. The test keeps passing as long as the new module state is declared above line 98 (the TDZ constraint the inventory records).\n</question>\n<question id=\"2\">\nThe ramifications are those in the inventory:\n- **Second consumer of `data/videos.ts`.** Any edit to the pager now affects two pages and two tests.\n- **Deliberate duplication.** The home page's scroll code is copied (about 40 lines).\n- **Live-stats traffic.** Stats requests grow with scrolling, one PeerTube batch per host per 8-card slice.\n- **DOM growth.** Up to about 300 cards per page view, with no windowing.\n- **Silent later failures.** A later-batch failure, including a key rejection, stops paging with only a console warning.\n- **Stale links.** `/videos.html?id=` keeps working but nothing in the app links to it.\n- **Stale `dist/`.** It stays stale until a build.\n- **New test is timing-exposed.** Every batch runs the ANN fallback under the Engine's 5 s statement deadline and the Client's 10 s proxy timeout. A 500 or 502 on any batch fails its no-error assertion.\n</question>\n<question id=\"3\">\nNothing outside the plan's file list has to change. Inside it, these must hold:\n- **TDZ.** All new `let`/`const` state that `loadSimilarVideos` touches before its first `await` is declared above the `void loadSimilarVideos()` call at line 98.\n- **`loading` flag.** It is cleared on the success, empty and error paths (a `finally`, or both branches), so a successful key-rejected retry does not leave the reveal and scroll checks dead.\n- **Observer and listeners.** They are created only after a non-empty first batch, and only once.\n- **Stale pager.** `loadMoreSimilar` drops the result of a pager that has since been replaced.\n- **Reveal during load.** The reveal is a no-op while `loading`.\n- **Deploy.** It needs `npm run build` before the rsync.\n</question>\n<question id=\"4\">\n- **List length.** The similar section is no longer a fixed 8 cards. It shows 8, then reveals 8 more at a time from a 48-row batch in memory, and fetches further 48-row batches with exclusions until the seed's pool runs out (at most about 300 rows, often fewer).\n- **Links.** The header \"Similar videos\" link and the inline \"Open full list\" link are gone.\n- **Rows without id or host.** Rows lacking `video_id` or `instance_domain` are now dropped. The Engine always sets both.\n- **Error display.** Later-batch errors are not shown. First-batch behaviour (empty, error, key-rejected, no seed) is unchanged.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nTwo entries imply only later batches pay the ANN fallback: the `tests/active/test_frontend_upnext_pager.py` entry (flake exposure item 1: \"Later batches drive the pool below `SIMILAR_VIDEO_TARGET_MIN_POOL` (48), so each runs the ANN fallback\") and the `engine/server/data/similarity_candidates.py` entry (\"Once a page view has shown enough rows, every later batch pays up to 3 live searches\"). The plan's risk \"Later batches can be slower\" makes the same assumption. What is true: the fallback condition is `len(rows) < policy.target_min_pool or not cache_hit` (`similarity_candidates.py:151`), and `DEPLOYMENT.md:260` states the similarity cache holds 20 candidates per seed, \"so nearly every up-next request runs the fallback\". The first batch runs at least one live FAISS search too. Later batches differ only in escalating to more steps, up to nprobe 128 / k 20000. So the timing-dependent 500/502 exposure in the new test covers every batch, including batch 1, not just the later ones. The conclusions (medium-high flake risk, 300 s timeout) are unchanged.\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Map the new test to the two Engine files as well.** Add `engine/server/data/similarity_candidates.py` and `engine/server/api/handlers/similar.py` to the new test's `config.json` entry, next to the plan's `data/videos.ts` and `server.py`. This is the inventory's gap, and issue 35 line 26 asks for the same mapping for the other up-next tests. It changes the plan's two-file list, so it needs the operator's OK. Cost: the new test (about 8 fallback-running round trips) is reselected on every edit to those two Engine files. Without it, a change to the pool rule the empty-batch assertion depends on goes unnoticed until something else reselects the test.\n2. **Put the new module state in one block above line 98, next to `similarStatsCache`/`similarStatsLoading` (72-73).** Clear `loading` in a `finally` inside `loadSimilarVideos`. Cost: none. It removes the only medium-risk crash path, the TDZ error, which would also turn `test_frontend_video_page` red.\n3. **Record the rate-limit answer in the new test's docstring.** It is one line: each validator group gets its own Engine, the limiter allows 60 per 60 s per `ip:path`, and the test makes at most 10 calls, so a bare single-process `pytest tests/active` run is the only 429 exposure. Cost: one line.\n4. **Optionally add a one-line pointer in the retired `tests/archive/upnext_random_draw/test_frontend_videos.py` docstring to the new file.** Cost: one line. It stops a reader from thinking the coverage is still missing.\n5. **No change to the settled plan is needed.** Its \"over-fetches 96\" wording is only true for keyed profiles with blocks or dislikes (`server.py:471-472`), as the inventory already notes. Neither the page nor the test depends on it.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n# Draft \u2014 12 similars on scroll\n\n## Module map\n\n| File | Change |\n|---|---|\n| `client/frontend/src/pages/video-page/index.ts` | Change the import; drop the two link lookups and the top-level href block; add a sentinel lookup and module paging state above `void loadSimilarVideos()`; rewrite `loadSimilarVideos`; add `revealSimilarChunk`, `loadMoreSimilar`, `fillSimilarViewport`, `maybeRevealSimilarOnScroll`, `setupSimilarScroll`. |\n| `client/frontend/video-page.html` | Remove `#similar-link` (line 22) and `#similar-link-inline` (line 127); add `#similar-sentinel` after `#similar-videos`. |\n| `client/frontend/src/video.css` | Add `.similar-sentinel { height: 1px; }` after `.similar-grid .loading, .similar-grid .error` (616-620). |\n| `tests/active/test_frontend_upnext_pager.py` | New (R6). |\n| `.un/skills/devsecops/config.json` | New `test_frontend_upnext_pager.py` entry with four files (the operator approved the two Engine files). |\n| `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` | Line 17 marked covered, plus a comment. |\n\nNothing else changes: `data/videos.ts`, `pages/videos/index.ts`, the server files, the render and stats helpers, and `dist/`.\n\n## What the build needs to test\n\n- **Pager contract (R3, R6), automated by the new test.** These run against the real Client and Engine at limit 48:\n  - the first batch has `seed.mode == \"upnext\"`;\n  - batches 1 and 2 are non-empty and disjoint;\n  - no batch repeats an earlier row;\n  - an empty batch arrives within 10 batches;\n  - requests stop after the empty batch.\n- **Page module still imports and runs in node (TDZ, empty-first-batch path), automated.** `test_frontend_video_page.py` runs unchanged. Its `{}` answer to `/recommendations` takes the \"No similar videos found.\" branch and must never reach `IntersectionObserver`, `document.documentElement` or `innerHeight`.\n- **Reveal, append, observer and fill-viewport (R2), plus later-batch paging in a real layout: manual browser check only.** No harness exists, and node has no layout. The maintainer checks:\n  - 8 cards on load;\n  - +8 cards per scroll to the bottom;\n  - a second `/recommendations` POST carrying `exclude` after 48 cards;\n  - requests stop at the pool's end;\n  - no link to `/videos.html`.\n\n## `pages/video-page/index.ts`\n\n### Imports (lines 6 and 20)\n\n```ts\nimport { createFeedPager, fetchSimilarVideosPayload, resolveApiBase, type FeedPager } from \"../../data/videos\";\n```\n\nLine 20 stays `import type { VideoRow } from \"../../types/videos\";`. No other type is named. `ExcludedVideo` is inferred from `createFeedPager`'s parameter, so the closure needs no annotation.\n\n### Element lookups\n\n- Delete line 43 (`similarLink`) and line 51 (`similarLinkInline`).\n- Add after `similarCards` (line 50):\n\n```ts\nconst similarSentinel = document.getElementById(\"similar-sentinel\");\n```\n\n### Module state\n\nThis goes directly after `similarStatsLoading` (line 73), which is above `void loadSimilarVideos()`, so the synchronous reset in `loadSimilarVideos` hits no TDZ error.\n\n```ts\n// The similar list shows this many cards at first and adds this many per scroll to the bottom.\nconst SIMILAR_CHUNK = 8;\n// Every row fetched so far; only the first similarRevealed of them are in the grid.\nlet similarRows: VideoRow[] = [];\nlet similarRevealed = 0;\nlet similarLoading = false;\n// One pager per load, so a retry starts with nothing shown and drops a replaced pager's result.\nlet similarPager: FeedPager | null = null;\nlet similarFetchingMore = false;\nlet similarScrollAttached = false;\n```\n\n- `similarPager` starts at `null`, not at a module-load `createFeedPager`. The no-seed path must never build one (R4).\n- Invariant: `0 <= similarRevealed <= similarRows.length`.\n- Invariant: the grid holds exactly `similarRows.slice(0, similarRevealed)` as cards, whenever `similarLoading` is false and the first batch was non-empty.\n\n### Top-level href block (lines 75-80)\n\nDeleted. The description-toggle block and `localLikesImported` stay where they are.\n\n### `loadSimilarVideos` (replaces lines 287-325)\n\n```ts\n/**\n * Load the first up-next batch through a fresh pager and reveal its first chunk.\n */\nasync function loadSimilarVideos() {\n  if (!similarSection || !similarCards) return;\n  if (!seedId) {\n    similarSection.setAttribute(\"hidden\", \"true\");\n    return;\n  }\n  similarRows = [];\n  similarRevealed = 0;\n  similarLoading = true;\n  similarCards.innerHTML = `<div class=\"loading\">Loading...</div>`;\n  const current = createFeedPager((exclude) =>\n    fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: \"48\", apiBase }, exclude)\n  );\n  similarPager = current;\n  try {\n    await localLikesImported;\n    const payload = await current.next();\n    if (current !== similarPager) return;\n    similarLoading = false;\n    const rows = payload.rows ?? [];\n    if (!rows.length) {\n      similarCards.innerHTML = `<div class=\"error\">No similar videos found.</div>`;\n      return;\n    }\n    similarRows = rows.slice();\n    const first = similarRows.slice(0, SIMILAR_CHUNK);\n    similarRevealed = first.length;\n    similarCards.innerHTML = first.map((row) => renderSimilarCard(row)).join(\"\");\n    queueSimilarStats(first);\n    setupSimilarScroll();\n    fillSimilarViewport();\n  } catch (error) {\n    if (current !== similarPager) return;\n    similarLoading = false;\n    if (error instanceof ProfileKeyRejectedError) {\n      similarCards.replaceChildren(keyRejectedNotice(() => void loadSimilarVideos()));\n      return;\n    }\n    const message = error instanceof Error ? error.message : \"Failed to load similar videos\";\n    similarCards.innerHTML = `<div class=\"error\">${escapeHtml(message)}</div>`;\n  }\n}\n```\n\n**Decisions:**\n- `limit: \"48\"` is literal. It equals `FEED_PAGE_SIZE`, and the Client caps it there anyway.\n- `await localLikesImported` still comes before the first request. The pager's fetch runs only inside `next()`, so creating the pager earlier sends nothing.\n- **Stale guard.** The `current !== similarPager` checks cost two lines and close the \"double run\" gap the impact names. A superseded call cannot overwrite the grid or clear `similarLoading` for the newer call. This is a small addition over the home page, which does not guard.\n- `similarLoading` is cleared on every path of the current call: empty, success, key-rejected and error. A retry therefore never leaves the scroll handlers dead.\n- The observer and listeners are set up only after a non-empty first batch. `test_frontend_video_page.py` never reaches them.\n\n### New functions (placed after `loadSimilarVideos`)\n\n```ts\n/**\n * Append the next chunk of fetched rows to the grid; with none left, ask the pager for more.\n */\nfunction revealSimilarChunk() {\n  if (similarLoading || !similarCards) return false;\n  const nextCount = Math.min(similarRows.length, similarRevealed + SIMILAR_CHUNK);\n  if (nextCount <= similarRevealed) {\n    void loadMoreSimilar();\n    return false;\n  }\n  const slice = similarRows.slice(similarRevealed, nextCount);\n  similarRevealed = nextCount;\n  // Appending leaves the cards already shown, and their fetched stats, in place.\n  similarCards.insertAdjacentHTML(\"beforeend\", slice.map((row) => renderSimilarCard(row)).join(\"\"));\n  queueSimilarStats(slice);\n  return true;\n}\n\n/**\n * Fetch the next up-next batch once the revealed rows reach the end of the ones fetched.\n */\nasync function loadMoreSimilar() {\n  const current = similarPager;\n  if (!current || similarLoading || similarFetchingMore || current.exhausted) return;\n  similarFetchingMore = true;\n  let appended = false;\n  try {\n    const payload = await current.next();\n    if (current !== similarPager || !payload.rows?.length) return;\n    similarRows.push(...payload.rows);\n    appended = true;\n  } catch (error) {\n    console.warn(\"[similar] loading more failed; paging stops for this page view\", error);\n  } finally {\n    similarFetchingMore = false;\n  }\n  // The sentinel may still be in view, so the observer will not fire again: reveal until it scrolls.\n  if (appended) {\n    revealSimilarChunk();\n    fillSimilarViewport();\n  }\n}\n\n/**\n * While the page is too short to scroll, keep revealing chunks until it can.\n */\nfunction fillSimilarViewport() {\n  if (similarLoading) return;\n  let safety = 0;\n  while (document.documentElement.scrollHeight <= window.innerHeight + 120 && safety < 50) {\n    if (!revealSimilarChunk()) break;\n    safety += 1;\n  }\n}\n\n/**\n * Reveal the next chunk once the page is scrolled near its bottom.\n */\nfunction maybeRevealSimilarOnScroll() {\n  if (similarLoading) return;\n  const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 240;\n  if (nearBottom) revealSimilarChunk();\n}\n\n/**\n * Watch the sentinel after the grid, with scroll and resize as a fallback; attached once per page view.\n */\nfunction setupSimilarScroll() {\n  if (similarScrollAttached) return;\n  similarScrollAttached = true;\n  if (similarSentinel) {\n    new IntersectionObserver(\n      (entries) => {\n        if (!entries.some((entry) => entry.isIntersecting)) return;\n        revealSimilarChunk();\n      },\n      { rootMargin: \"200px\" }\n    ).observe(similarSentinel);\n  }\n  window.addEventListener(\"scroll\", maybeRevealSimilarOnScroll, { passive: true });\n  window.addEventListener(\"resize\", () => {\n    maybeRevealSimilarOnScroll();\n    fillSimilarViewport();\n  });\n}\n```\n\n**Invariants and decisions:**\n\n- **`revealSimilarChunk`**\n  - It is a no-op returning `false` while `similarLoading`. The observer can fire right after `observe()`, and on a retry the reused listeners fire into a grid that shows `Loading...`.\n  - It returns `true` exactly when it appended cards.\n  - Stats are queued only for the appended slice (R2). `queueSimilarStats` already skips cached and in-flight keys.\n- **`loadMoreSimilar`**\n  - At most one fetch is in flight (`similarFetchingMore`).\n  - The pager owns the stop rule: `exhausted` after an empty or failed batch, after which the early return means no request is made (R3).\n  - A later-batch failure, `ProfileKeyRejectedError` included, is only warned about. The grid is never touched (R3, as the impact notes).\n- **`fillSimilarViewport` (deliberate difference from `maybeFillViewport`).** The loop does not also require `similarRevealed < similarRows.length`. It stops as soon as a reveal changes nothing, and that final reveal is the one that calls `loadMoreSimilar`.\n  - Why: on a very tall screen where all 48 rows fit, the page still asks for the next batch. On the home page the fill loop would stop there, and the sentinel observer would not fire again.\n  - It stays bounded: the safety counter is 50, `loadMoreSimilar` is guarded, and the pager exhausts within ~7 batches.\n  - R2's rule (\"while short and unrevealed rows remain, keep revealing\") still holds. This only adds R3's \"a reveal that finds none left asks the pager\".\n- **`setupSimilarScroll`**\n  - The observer and listeners are created once and reused across retries. They read module state, so no disconnect is needed.\n  - If `#similar-sentinel` is missing, scroll and resize still work.\n\n### Unchanged\n\n`renderSimilarCard`, `queueSimilarStats` and the stats fetchers, `applySimilarStatsToDom`, `videoPageUrl`, and all metadata, reaction, block and description code.\n\n## `video-page.html`\n\nThe nav loses line 22:\n\n```html\n        <nav class=\"header-nav\">\n          <a class=\"nav-link\" href=\"/\">Home</a>\n          <a class=\"nav-link\" href=\"/likes.html\">Likes</a>\n          <a class=\"nav-link\" href=\"/search.html\">Search</a>\n          <a class=\"nav-link\" href=\"/about.html\">About</a>\n        </nav>\n```\n\nThe similar section:\n\n```html\n        <section id=\"similar-section\" class=\"similar-card\">\n          <div class=\"section-header\">\n            <h3>Similar videos</h3>\n          </div>\n          <div id=\"similar-videos\" class=\"similar-grid\">\n            <div class=\"loading\">Loading...</div>\n          </div>\n          <div id=\"similar-sentinel\" class=\"similar-sentinel\" aria-hidden=\"true\"></div>\n        </section>\n```\n\n## `video.css`\n\nAdded after line 620:\n\n```css\n.similar-sentinel {\n  height: 1px;\n}\n```\n\n## `tests/active/test_frontend_upnext_pager.py`\n\n```python\n\"\"\"The frontend's feed pager over up-next similars, run in node against the real Client and Engine at the video page's 48-row batch: its batches never repeat a row, and it stops asking once a batch adds nothing.\n\n- For the linux seed, the pager's first batch is an up-next page (`seed.mode == \"upnext\"`), its second batch holds rows and none of the first batch's, and no later batch repeats a row of an earlier one. Each batch is a random draw (build 09), so no two pages are compared for equality.\n- The pager is driven for MAX_BATCHES calls and reaches an empty batch before the last: the Engine takes a seed's top 300 rows before it drops excluded ones, so at 48 a batch the pool runs out in about 7. No call after the empty batch makes a request, counted on the fetch function the pager is given (a pass-through to `fetchSimilarVideosPayload`).\n\nReplaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). `window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner supplies minimal in-memory ones, as `test_frontend_video_page.py` does.\n\"\"\"\nfrom __future__ import annotations\n\nimport json\nimport os\nimport subprocess\nfrom pathlib import Path\n\nFRONTEND = Path(__file__).resolve().parents[2] / \"client\" / \"frontend\"\nESBUILD = FRONTEND / \"node_modules\" / \".bin\" / \"esbuild\"\nPAGE = \"48\"\nMAX_BATCHES = 10\n\nRUNNER = \"\"\"\nconst memory = () => { const s = new Map(); return {\n  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),\n  removeItem: (k) => s.delete(k) }; };\nglobalThis.localStorage = memory();\nglobalThis.sessionStorage = memory();\nglobalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage,\n  sessionStorage: globalThis.sessionStorage };\nconst m = await import(process.env.BUNDLE);\nconst say = (obj) => process.stdout.write(JSON.stringify(obj) + \"\\\\n\");\nconst keys = (rows) => (rows ?? []).map((r) => [r.video_id, r.instance_domain]);\nconst query = { id: process.env.SEED_UUID, host: process.env.SEED_HOST, limit: process.env.PAGE,\n  apiBase: process.env.BASE };\nlet calls = 0;\ntry {\n  const pager = m.createFeedPager((exclude) => { calls += 1; return m.fetchSimilarVideosPayload(query, exclude); });\n  for (let i = 0; i < Number(process.env.MAX_BATCHES); i += 1) {\n    const payload = await pager.next();\n    say({ rows: keys(payload.rows), mode: payload.seed?.mode ?? null, calls });\n  }\n} catch (e) { say({ error: String(e), calls }); }\nprocess.exit(0);\n\"\"\"\n\n\ndef _run(tmp_path: Path, base: str, seed: dict) -> list[dict]:\n    entry = tmp_path / \"entry.ts\"\n    entry.write_text(f'export {{ createFeedPager, fetchSimilarVideosPayload }} from \"{FRONTEND}/src/data/videos.ts\";\\n')\n    subprocess.run(\n        [str(ESBUILD), str(entry), \"--bundle\", \"--format=esm\", \"--platform=node\",\n         f\"--outfile={tmp_path / 'bundle.mjs'}\",\n         f\"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base)}\",\n         \"--define:import.meta.env.DEV=false\"],\n        check=True, capture_output=True,\n    )\n    runner = tmp_path / \"runner.mjs\"\n    runner.write_text(RUNNER)\n    proc = subprocess.run(\n        [\"node\", str(runner)], capture_output=True, text=True, timeout=300,\n        env={\"BASE\": base, \"BUNDLE\": str(tmp_path / \"bundle.mjs\"), \"PATH\": os.environ.get(\"PATH\", \"\"),\n             \"SEED_UUID\": seed[\"video_uuid\"], \"SEED_HOST\": seed[\"instance_domain\"],\n             \"PAGE\": PAGE, \"MAX_BATCHES\": str(MAX_BATCHES)},\n    )\n    assert proc.returncode == 0, proc.stderr\n    return [json.loads(line) for line in proc.stdout.splitlines()]\n\n\ndef _seed(client) -> dict:\n    # A seed whose up-next pool fills a 48-row page (test_similar's fills_a_48_row_page case).\n    status, body = client.request(\"GET\", \"/api/v1/search/videos?q=linux&limit=1\")\n    assert status == 200 and body[\"rows\"], body\n    return body[\"rows\"][0]\n\n\ndef test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(\n        engine_client, tmp_path):\n    batches = _run(tmp_path, engine_client.base, _seed(engine_client))\n    assert all(\"error\" not in b for b in batches), batches\n    assert len(batches) == MAX_BATCHES, batches\n    assert batches[0][\"mode\"] == \"upnext\", batches[0]  # control: the seed resolves to up-next\n\n    first, second = (set(map(tuple, b[\"rows\"])) for b in batches[:2])\n    assert first, \"the first batch is empty\"\n    assert second, \"the second batch is empty\"\n    assert not first & second, first & second\n    seen: set[tuple] = set()\n    for batch in batches:  # and no later batch repeats a row of any earlier one\n        rows = set(map(tuple, batch[\"rows\"]))\n        assert not rows & seen, (rows & seen, [len(b[\"rows\"]) for b in batches])\n        seen |= rows\n\n    empty = next((i for i, b in enumerate(batches) if not b[\"rows\"]), None)\n    # the seed's pool ends within the budget, with at least one call after it to count\n    assert empty is not None and empty + 1 < len(batches), [len(b[\"rows\"]) for b in batches]\n    # control: up to the empty batch, every batch was one request through the given fetch\n    assert [b[\"calls\"] for b in batches[:empty + 1]] == list(range(1, empty + 2)), batches\n    assert all(b[\"calls\"] == batches[empty][\"calls\"] for b in batches[empty + 1:]), batches\n```\n\n**Changes from the retired file:**\n- `parents[2]`, `PAGE = \"48\"`, `MAX_BATCHES = 10`.\n- `window.sessionStorage` is added.\n- The plain-fetch controls are gone. `mode` comes from the first pager batch; the pager spreads `payload`, so `seed` survives.\n- The error line carries `calls`.\n- `len(batches) == MAX_BATCHES` is checked, so a crash partway through fails.\n- The failure messages print batch sizes, so an Engine pool-rule change fails with a readable message rather than passing vacuously.\n\n**Known flake exposure (not handled in the draft):**\n- An Engine 5 s deadline overrun in a fallback batch.\n- The Engine's 60/min limiter shared with `test_similar`.\n\nBoth show up as an `error` line and fail the first assertion. If they bite in validation, the fix is in the harness (lane or grouping), not a weaker assertion.\n\n## `.un/skills/devsecops/config.json`\n\nInserted after the `test_frontend_video_page.py` entry (after line 152):\n\n```json\n    \"test_frontend_upnext_pager.py\": [\n      \"client/frontend/src/data/videos.ts\",\n      \"client/backend/server.py\",\n      \"engine/server/data/similarity_candidates.py\",\n      \"engine/server/api/handlers/similar.py\"\n    ],\n```\n\nThe operator approved the two Engine files at this step: the empty-batch and no-repeat assertions depend on them (issue 35 line 26).\n\n## Issue 35\n\nLine 17 becomes:\n\n```markdown\n- **test_frontend_videos** (the whole file): the frontend pager never repeats a row and stops asking after an empty batch. Covered by `tests/active/test_frontend_upnext_pager.py` (build 12).\n```\n\nLine 26 gets an appended sentence: \"The `test_frontend_videos.py` entry is gone; its replacement is mapped as `test_frontend_upnext_pager.py`.\"\n\nComment under `## Comments`:\n\n```markdown\n- Build 12 (similars on scroll): `tests/active/test_frontend_upnext_pager.py` replaces `test_frontend_videos`. It drives `createFeedPager` over `fetchSimilarVideosPayload` for the linux seed at 48 rows per batch, with no plain-fetch control (each page is a random draw), a 10-batch budget, and the first batch's `seed.mode` checked as `upnext`. The empty batch is reached because the Engine takes a seed's top 300 rows before dropping excluded ones. It is mapped to `data/videos.ts`, `server.py`, `similarity_candidates.py` and `handlers/similar.py`. The other five items stay open.\n```\n\nStatus stays `enhancement, needs-triage`.\n\n## Check against plan and requirements (pass 1, converged)\n\n| Item | Where met |\n|---|---|\n| R1 limit 48 via `fetchSimilarVideosPayload` with id/host/apiBase | pager closure in `loadSimilarVideos` |\n| R2 memory + revealed prefix, first 8, +8 appended, stats per slice | `similarRows`/`similarRevealed`, `revealSimilarChunk` |\n| R2 sentinel observer 200px, passive scroll, resize, \u2212240 / +120 thresholds, safety 50 | `setupSimilarScroll`, `maybeRevealSimilarOnScroll`, `fillSimilarViewport` |\n| R3 one pager per load, exclude via pager, load-more guards, reveal + fill after append, console.warn only | `loadSimilarVideos`, `loadMoreSimilar` |\n| R4 likes import first, empty / error / key-rejected / no-seed paths, card markup | `loadSimilarVideos`; helpers untouched |\n| R5 both links and their code removed, heading kept, `useSimilar` untouched, no dist edit | HTML, deleted lines 43/51/75-80/296-301 |\n| R6 test, mapping, issue 35 | above |\n| Impact: TDZ ordering | state declared above line 98 |\n| Impact: `loading` cleared on all paths, stale pager dropped | `loadSimilarVideos`, `loadMoreSimilar` |\n| Impact: no observer or listener in the node stub's empty path | set up only after a non-empty first batch |\n\n**Named deviations from the plan:**\n1. `fillSimilarViewport` also asks for the next batch once all fetched rows fit the viewport.\n2. `loadSimilarVideos` guards against a superseded call.\n3. The config entry has four files, not two (operator-approved).\n\n**Simplifications, carried from the plan:**\n- No end-of-list marker.\n- Later-batch errors go to the console only.\n- No DOM windowing. This caps out at the pool size of about 300 cards; the upgrade path is windowing.\n- The scroll code is copied from the home page rather than shared. The upgrade path is extracting it when a third paged surface appears.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the frontend data layer's `createFeedPager` over `fetchSimilarVideosPayload`, bundled with esbuild (ESM, node platform) and run in node against the live Client and Engine that the `engine_client` fixture starts locally. This follows the harness of the retired `tests/archive/upnext_random_draw/test_frontend_videos.py`. The checkpoint is the new `tests/active/test_frontend_upnext_pager.py` itself, as drafted, going green. For the linux search seed at limit \"48\": the first batch's `seed.mode == \"upnext\"`; batches 1 and 2 are non-empty and disjoint; no batch repeats a `(video_id, instance_domain)` row from any earlier batch; an empty batch comes before the last of `MAX_BATCHES = 10` calls; the counted fetch calls go 1..k up to the empty batch and do not increase after it. This is characterization: `data/videos.ts` does not change, so the test is green once written.</checkpoint>\n<name>Up-next pager contract test</name>\n<intent>`tests/active/test_frontend_upnext_pager.py` holds the frontend feed pager's contract over up-next similars at the video page's 48-row batch, in place of the retired `test_frontend_videos.py`.</intent>\n<clause_1>Across 48-row batches from the linux seed, no row repeats, an empty batch arrives within 10 batches, and no request is made after it.</clause_1>\n<files>tests/active/test_frontend_upnext_pager.py (NEW), .un/skills/devsecops/config.json (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the real page module `client/frontend/src/pages/video-page/index.ts`, bundled with esbuild (`--loader:.css=empty`) and imported in node under the recording-element runner copied from `tests/active/test_frontend_video_page.py`. It lives in a new `tests/active/test_frontend_video_page_similars.py`. The runner adds stubs: an `IntersectionObserver` whose callback and observed element are captured; `document.documentElement.scrollHeight` large and `window.innerHeight` small, so fill-viewport never loops; `window.scrollY`. `fetch` records the method, path and JSON body of each request. It answers POST `/recommendations` with 48 distinct rows (each with `video_id` and `instance_domain`) and `seed.mode: \"upnext\"`, and answers `{}` elsewhere. Asserts: exactly one `/recommendations` request was made, and its body's limit is \"48\"; the `#similar-videos` element's innerHTML holds exactly 8 `similar-card-item` anchors. Control: `/api/video` was requested. `tests/active/test_frontend_video_page.py` must still pass unchanged, which covers the empty first batch and the no-observer path.</checkpoint>\n<name>First similar batch through the pager</name>\n<intent>`loadSimilarVideos` in `pages/video-page/index.ts` fetches its first batch through a fresh feed pager asking `/recommendations` for 48 rows, and puts only the first 8 of them into `#similar-videos`.</intent>\n<clause_1>The first `/recommendations` request the page makes carries limit 48.</clause_1>\n<clause_2>From a 48-row answer, `#similar-videos` holds exactly 8 cards.</clause_2>\n<files>client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page_similars.py (NEW)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the same node harness and file as phase 2 (`tests/active/test_frontend_video_page_similars.py`), after the first batch has rendered. The runner also records each `insertAdjacentHTML` call on `#similar-videos`, and invokes the captured `IntersectionObserver` callback with `[{ isIntersecting: true }]`. Fetch answers a second `/recommendations` POST with a disjoint batch. Asserts: one intersection adds exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call holding 8 `similar-card-item` anchors, and the grid's innerHTML is still the first 8 cards, not rewritten. After five further intersections have revealed all 48 rows, the next intersection sends a second `/recommendations` POST, and its exclude list holds exactly the 48 `(video_id, instance_domain)` pairs of the first batch. Control: the observer was constructed with the `#similar-sentinel` element.</checkpoint>\n<name>Reveal and page on scroll</name>\n<intent>Once the first similar batch is shown, each sentinel intersection appends the next 8 fetched rows to `#similar-videos`, and an intersection that finds no unrevealed row asks the pager for the next batch, excluding the rows already shown.</intent>\n<clause_1>A sentinel intersection appends the next 8 cards, and the cards already shown stay in place.</clause_1>\n<clause_2>An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown.</clause_2>\n<files>client/frontend/src/pages/video-page/index.ts (EDITED), client/frontend/video-page.html (EDITED), client/frontend/src/video.css (EDITED), tests/active/test_frontend_video_page_similars.py (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>Seam, two boundaries. First, the served HTML file `client/frontend/video-page.html`, parsed with stdlib `html.parser`: no `a` element has an `href` containing `/videos.html`, and no element has id `similar-link` or `similar-link-inline`. Second, the phase 2 node runner in `tests/active/test_frontend_video_page_similars.py`, which reports every id passed to `document.getElementById`: neither `similar-link` nor `similar-link-inline` is among them after the page has loaded. Control: `similar-videos` is among them.</checkpoint>\n<name>Remove the see-all links</name>\n<intent>The video page no longer offers a link to `/videos.html`: the anchor is gone from its HTML, and the module no longer looks up the link elements.</intent>\n<clause_1>`video-page.html` contains no anchor to `/videos.html`.</clause_1>\n<clause_2>The page module never looks up `#similar-link` or `#similar-link-inline`.</clause_2>\n<files>client/frontend/video-page.html (EDITED), client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page_similars.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nPhase 1: its checkpoint needs the live local Client and Engine that the `engine_client` fixture starts (the engine pixi env and its local data). It makes about 8 round trips, some of which run the ANN fallback, under a 300 s timeout. It shares the Engine's 60/min limiter with `test_similar`. No credential is needed. Phases 2-3, manual step: node has no layout, so the maintainer checks in a real browser what no checkpoint can: fill-viewport on a very tall screen, the scroll and resize fallbacks at the -240/+120 thresholds, and requests stopping at the pool's end in a real layout.\n</needs_coordination>\n\n<rationale>\nThe phases follow the draft's own seams. Phase 1 is the R6 test, which is independent of the page and green by itself because `data/videos.ts` does not change. The config mapping goes in with it as plumbing, not as a separate clause: a test that reads the entry back would only verify that the entry was pasted. Phase 2 covers R1 and the first part of R2: the pager at 48 and the first 8 cards. Phase 3 covers the rest of R2 and R3: append on intersection and the second batch with exclude. They are split because each phase's Intent has two observable facts, and together they have four. R5, link removal, is separate and small, and goes last so phase 4 can reuse the phase 2 runner's getElementById log. The operator approved a change from the draft's \"manual only\" for R2/R3. A new `test_frontend_video_page_similars.py` reuses the recording-element runner of `test_frontend_video_page.py` with stubbed IntersectionObserver, scroll metrics and fetch. It checks the request limit, the card counts and the exclude contents at the module boundary without a layout engine. Only real-layout behaviour stays manual: fill-viewport and the scroll and resize thresholds. R4 (unchanged empty, error, no-seed and key-rejected paths) is covered by `test_frontend_video_page.py` staying green, plus the full suite. The issue 35 note is documentation, so it has no phase; Step 9 writes it.\n</rationale>",
    "author:tests/tmp/test_12_similars_on_scroll_phase1.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D1\">\n<disposition>fixed</disposition>\n<what>Two assertions now carry this. :136 requires exactly 48 rows in every batch before the last non-empty one, and 1 to 48 rows in that one. The new :142 runs the same seed a second time at limit \"20\" for 2 batches and requires sizes [20, 20]. I observed [20, 20] this turn, with calls [1, 2] and mode upnext on both. Because the similars default is 48, a pager or query that drops `limit` or hardcodes 48 now reads [48, 48] at :142 and fails. A pager that merges or trims pages fails :136. I rewrote docstring bullet 3 to describe the second run.</what>\n</item>\n<item id=\"D8\">\n<disposition>fixed</disposition>\n<what>A new test at :145-162 checks the durable file's behaviour, not only its registration. :146 requires tests/active/test_frontend_upnext_pager.py to exist. The test then loads that file and swaps its own `_run`/`_seed` for canned batches. Control at :151: the batch shape the live run observed (48 x 6, 12, 0, 0, 0; calls 1..8, 8, 8) must pass. :162: each of six wrong-pager batch sets must make the durable test raise AssertionError. The six are: a row of batch 0 repeated in batch 3, a feed that never runs dry, calls 9 and 10 after the empty batch, mode \"random\", an empty second batch, and a crash partway. I observed this turn: the plan's drafted durable file (plan :683-778) passes the whole test, a durable file whose test body is `pass` fails at :162, and the absent file fails at :146. I rewrote docstring bullet 4 to match and removed the \"left to review of that file\" sentence.</what>\n</item>\n<item id=\"N1\">\n<disposition>fixed</disposition>\n<what>The name's \"48-row batches\" is carried by :136 (exactly 48 per full batch, 1..48 for the last non-empty one). :142 (limit 20 gives [20, 20]) shows the size comes from the limit sent and not the 48 default. It excludes merged or trimmed pages, a wrong limit, and a dropped or hardcoded limit.</what>\n</item>\n<item id=\"N5b\">\n<disposition>justified</disposition>\n<what>The name is narrowed to `test_the_durable_pager_group_is_fingerprinted_over_videos_ts_the_client_server_and_both_engine_similars_files` (:165), which names exactly the four `SUBJECTS` that :174 checks. The docstring says that `data/videos.ts`'s imports (`cache`, `local-likes`, `api-base`, `profile`) are not in the plan's mapping and are not checked. I did not widen `SUBJECTS`, because the operator-approved mapping at plan :800-805 lists only these four.</what>\n</item>\n</items>\n\n<findings_addressed>\nShape CRITICAL 1 (stub question: an empty or `pass` durable file passed): fixed with a new test at :145-162. It loads tests/active/test_frontend_upnext_pager.py and swaps its `_run`/`_seed` for canned batches. It requires the durable test to pass the batch shape the live run observed (:151) and to raise AssertionError on each of six wrong-pager batch sets (:162). Observed this turn: the plan's draft passes, a `pass`-body stub fails at :162, and the missing file fails at :146.\nShape CRITICAL 2 (single-value pin at 48, which is also the default): fixed. :142 runs the same seed again at limit \"20\" for 2 batches and requires [20, 20] (observed [20, 20] this turn). A dropped or hardcoded limit now reads 48 and fails. This costs 2 extra Engine requests, not a second full run.\nShape REC 1 (stale line numbers in the C1 exemption): not re-asked, because the exemption stands. With this edit, the current C1 carriers are :124, :125, :129, :134, :136, :139, :142, :146, :162, :173 and :174, with controls at :118-120, :123, :138, :148, :151, :169 and :171.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:124, :125, :129: batch 2 is non-empty, batches 1 and 2 share no (video_id, instance_domain) row, and no batch repeats a row from any earlier batch, across all 10 batches.</assertion>\n<expected>Observed batch sizes 48 x 6, 12, 0, 0, 0 with no overlaps, so all three hold.</expected>\n<wrong_implementation>A pager that stops sending `exclude` and does not dedup gets repeated rows from the Engine's random draw, so :125/:129 read a non-empty intersection. A pager that excludes only the previous batch fails :129 on a later batch.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:134: an empty batch arrives before the last of the 10 calls. Controls: :119 (exactly 10 batches reported) and :118 (no error line).</assertion>\n<expected>The first empty batch is at index 7.</expected>\n<wrong_implementation>A feed that never runs dry, or runs dry only at index 9: `empty` is None or 9, and the assertion fails.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:136 and :142: every batch before the last non-empty one has exactly 48 rows and the last non-empty one has 1..48; a second run of the same seed at limit \"20\" for 2 batches has sizes [20, 20].</assertion>\n<expected>sizes[:6] == [48]*6 and sizes[6] == 12, and the limit-20 run reads [20, 20] (observed this turn).</expected>\n<wrong_implementation>A pager that merges two fetches (96 rows) or trims a full page fails :136. A query that drops `limit` or hardcodes 48 comes back at the 48 default, so :142 reads [48, 48] and fails.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:139: every `next()` after the empty batch leaves the counted fetch calls unchanged. Control :138: calls go 1..8 up to and including the empty batch.</assertion>\n<expected>calls [1..8, 8, 8].</expected>\n<wrong_implementation>A pager that never sets `exhausted` keeps calling the fetch, so calls read 9, 10 and the assertion fails.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:146, :162: the durable tests/active/test_frontend_upnext_pager.py exists. With its `_run` swapped for canned batches, its test raises AssertionError on each of six wrong-pager sets: repeats a row of an earlier batch, never runs dry, keeps asking after the empty batch, mode other than upnext, empty second batch, crash partway. Controls: :148 (it defines a test) and :151 (the observed batch shape passes).</assertion>\n<expected>After the phase lands, :162 reads [] (observed against the plan's drafted file this turn). Before the phase, :146 fails because the file is absent (observed).</expected>\n<wrong_implementation>A durable file that is empty, has a `pass` body, or drops any of the pager assertions (no-repeat, empty-within-budget, no-calls-after, upnext mode, crash guard). The labels of the sets it does not fail on appear in :162's list. Observed: a `pass` stub fails here.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:173, :174: `claimed` discovers a group `test_frontend_upnext_pager.py`, and its files include all four SUBJECTS. Controls: :169 (an existing group carries its mapping) and :171 (all four subjects exist).</assertion>\n<expected>After the phase, `covered` contains videos.ts, server.py, similarity_candidates.py and handlers/similar.py. Before it, covered is None.</expected>\n<wrong_implementation>A phase that adds no durable file fails :173. A config.json entry missing any of the four files fails :174, which lists the missing file.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every absence assertion has a positive control. :125/:129 are armed by :123/:124 and :119. :139 is armed by :138 and :134. :162 (the durable test fails on each wrong set) is armed by :151 (it passes the good set), so a durable test that always raises cannot pass, and one that never raises fails :162.\n2. No. :136/:142 compare observed batch lengths with the limit that was sent. :162 feeds canned batches into the durable file's own assertions and does not recompute anything production does. Deleting the `limit` param in buildSimilarUrl turns :142 red ([48, 48]). Deleting any pager assertion from the durable file turns :162 red.\n3. Fixed. Batch size is now read at two inputs, 48 (:136) and 20 (:142), and 20 is not the default. The durable test is driven with one passing input and six failing ones.\n4. No. The runner shims only the browser platform objects. In the new test, the doubles replace the durable file's own `_run`/`_seed` helpers. The subject there is the durable test's assertions, and the live pager is exercised by the first test.\n5. Yes, it collects. This turn a probe loaded the module and called the new test: it bound, and it ran against the absent file, the plan's draft and a stub. `types` is imported. `_load` replaces the inline harness loading in the last test.\n6. Yes, all observed this turn. Limit 20 x 2 gave [20, 20] with calls [1, 2], mode upnext. The plan's draft passes the good set and fails all six wrong sets, each with an AssertionError. A `pass` stub fails at :162. The 48 x 6/12/0 shape and calls 1..8, 8, 8 are from last turn's live probe.\n7. Yes. Before the phase, the pager test is green (characterization, under the standing C1 exemption). The new test fails at :146 because the durable file is absent (observed), and the group test fails at :173 with covered None. Both are red for the phase's reason. I emptied the probe files tests/tmp/probe_12_durable.py, draft_upnext_pager.py and draft_stub_pager.py so they collect nothing. I have no delete tool, so they still need removing, along with last turn's emptied probes.\n</answers>",
    "self_check:tests/tmp/test_12_similars_on_scroll_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_12_similars_on_scroll_phase1.py:95, :96, :100 \u2014 the second 48-row batch holds rows, it shares none with the first, and no batch across all 10 shares a (video_id, instance_domain) with any earlier batch</assertion>\n<expected>Green. The probe run showed batch sizes 48, 48, 48, 48, 48, 48, 12, 0, 0, 0, all with mode \"upnext\" until the empty batch, and no row repeated.</expected>\n<wrong_implementation>A pager that stops putting the rows it has shown into `exclude` (drop `shown.push`). Every fetch is then a fresh random 48 from the same 300-row pool. Its own key filter hides repeats, but the pool never runs dry within 10 calls, so :105 goes red. A pager that drops the key filter and the exclude list together hands back repeated rows, and :96/:100 go red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_12_similars_on_scroll_phase1.py:105 and :108 \u2014 an empty batch arrives at index < 9 (within the 10-batch budget, with calls after it), and every batch after it reports the same fetch-call count as the empty one</assertion>\n<expected>Green. The probe showed the empty batch at index 7 (batch 8) and calls at 1..8 then 8, 8. The control at :107 (calls == 1..empty+1) passed.</expected>\n<wrong_implementation>A pager that does not set `exhausted` when a batch adds no row, or that ignores it in `next()`, keeps fetching: calls read 9 and 10 after the empty batch and :108 goes red. A pager that never excludes shown rows never reaches an empty batch within 10, and :105 goes red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_12_similars_on_scroll_phase1.py:121 \u2014 `claimed(ROOT, load_config())` from validate_tests.py has a group `test_frontend_upnext_pager.py`, i.e. the durable test that gates these behaviours exists in tests/active</assertion>\n<expected>Red before the phase: the run printed `AssertionError: ['test_blocks.py', ... ] / assert None is not None` at line 121. Green once the durable test is written.</expected>\n<wrong_implementation>A phase that leaves the claim only in this tmp checkpoint, or files the durable test under a name or place the harness does not discover (e.g. archive/ or a `_`-prefixed name). Then `claims.get(...)` is None and nothing gates C1 after the build.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_12_similars_on_scroll_phase1.py:122 \u2014 the files the harness fingerprints that group over include videos.ts, client/backend/server.py, similarity_candidates.py and handlers/similar.py</assertion>\n<expected>An empty list, once the phase lands with the test_groups entry. It is not reached in the current run because :121 fails first.</expected>\n<wrong_implementation>A test_groups entry that is missing, leaves out one of these subjects, or names a mistyped path (`walk` silently drops a missing root). The list then names the uncovered subject, and an edit to that file would not reselect the durable test.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, one gap, now fixed. The docstring said the durable test is \"reselected when any of them changes\", but the old test only compared config.json's raw list to a literal. A mistyped path in that list would pass the old test even though `walk` drops it and no reselection happens. I rewrote the second test to ask validate_tests.py's own `claimed()` which files the group is fingerprinted over (lines 111-122). Each docstring clause now has an assertion: up-next control :91, second batch non-empty :95, disjoint :96, no later repeat :100, empty batch within budget :105, no request after it :108, durable group exists :121, covers the four subjects :122. I dropped the word \"exactly\" from the docstring. The claim is coverage, and pinning the full list was the hardcoded-spec-mirror form.\n2. Absence only: no. The disjointness checks (:96, :100) are armed by non-empty batches (:94, :95). The no-request-after-empty check (:108) is armed by the calls == 1..empty+1 control (:107), so the counter is proven to count. The membership check (:122) is armed by the video-page group control (:117, a known mapped file shows up in `claimed`) and by the subjects-exist control (:119). I removed the old unarmed `\"test_frontend_videos.py\" not in groups`.\n3. Echoed literal: no. The pager assertions read rows and call counts produced by the real videos.ts in node against the real Client and Engine. Deleting `if (!fresh.length) exhausted = true;` (videos.ts:66) turns :108 red. Deleting `shown.push({ id, host });` (videos.ts:63) turns :105 red. :121/:122 read the harness's computed claim, not a copy of config.json.\n4. One value: no. The linux seed and 48-row batch are fixed by C1 itself. No-repeat is checked across all 10 batches, not one pair. No observable is compared with a sibling from the same source.\n5. The double: no. Only the browser platform node lacks is supplied (window/localStorage/sessionStorage), plus a pass-through wrapper around the real `fetchSimilarVideosPayload` that counts calls. The Client (`ClientBackendServer`) and the Engine subprocess are real, via conftest `engine_client`. validate_tests.py is imported for real.\n6. It collects: yes. The run printed \"collected 2 items\", which matches the two tests. `importlib.util` is imported. `claimed(project, config)` and `load_config()` exist with those signatures (validate_tests.py:616, :439). The earlier `--collect-only` line said \"no tests\" only because nothing ran; pytest itself collected 2.\n7. Observed, not predicted: yes, from runs. A probe (tests/tmp/probe_12_pager_lengths.py) printed `[(48,'upnext',1),(48,..,2)\u2026(12,'upnext',7),(0,None,8),(0,None,8),(0,None,8)]`, which confirms the seed comment (48 x 6, then 12, then empty at batch 8) and the call counts. A second probe (tests/tmp/probe_12_claimed.py) showed `claimed` returns absolute `ROOT/...` Paths with the group's own test file first, lists `test_frontend_video_page.py` with `client/frontend/src/pages/video-page/index.ts`, and returns None for `test_frontend_upnext_pager.py`. The :117 control and the Path form in :122 are built from that. I have no delete tool, so both probe files are still in tests/tmp and need removing. Each ends in `assert False`.\n8. Red, not green: yes. `ValidateTests tests/tmp/test_12_similars_on_scroll_phase1.py` \u2192 \"1 failed, 1 passed\", \"[exit status 1]\". The pager test passes, as the docstring says it does before the phase lands. The durable-group test fails.\n9. Red for the right reason: yes. Both controls passed (:117 video-page claim, :119 subjects exist). The failure is at the phase assertion: \"tests/tmp/test_12_similars_on_scroll_phase1.py:121: AssertionError \u2026 assert None is not None\", listing the discovered groups with no `test_frontend_upnext_pager.py`. The durable test this phase writes does not exist yet. That is not a typo, a bad import, or a harness limit.\n10. Observed expected output: each row's `expected` comes from the runs. The pager rows are green in the checkpoint run, with values from the probe output quoted in 7. The :121 row quotes the red line above. The :122 row is not reached in this run because :121 fails first. Its expected empty list stands on the probe showing `claimed` lists mapped files as `ROOT / path`.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `tests/active/test_frontend_upnext_pager.py` (NEW)\nThis is the durable up-next pager contract test. It replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). It bundles `data/videos.ts` with esbuild and runs `createFeedPager` in node against the live Client and Engine (`engine_client` fixture). The linux seed is used, with 48-row batches and MAX_BATCHES = 10. The test checks C1:\n- the first batch comes back in up-next mode (a control)\n- the second batch is non-empty and shares no rows with the first\n- no batch repeats a row of an earlier one\n- an empty batch arrives before the last call\n- every batch before the last non-empty one holds exactly 48 rows, and that one holds 1\u201348\n- calls count 1..n up to the empty batch and stay flat after it\n\nThe runner and helpers follow the retired file's structure, with `sessionStorage` added to `window`.\n\nIt does **not** repeat the checkpoint's limit-20 run (\"the batch size follows the limit sent\"). The checkpoint swaps `_run` for a function that returns one fixed set of 48-row batches on every call. A second `_run` asking for 20 would get those 48-row batches back, so the durable test would fail even the good case. As a result, that check lives only in the Phase 1 checkpoint, which is temporary. `_run` and `_seed` are called with positional arguments, and the one test takes `(engine_client, tmp_path)`, because the checkpoint's replacement functions expect exactly those.\n\n### `.un/skills/devsecops/config.json` (EDITED)\nAdded a `test_groups` entry for `test_frontend_upnext_pager.py`. It maps to `client/frontend/src/data/videos.ts`, `client/backend/server.py`, `engine/server/data/similarity_candidates.py` and `engine/server/api/handlers/similar.py`, so the group is reselected when any of them changes.\n\n### `tests/tmp/probe_upnext_durable.py` (probe; please delete)\nThis probe re-imports the checkpoint's two offline tests: the one that feeds fixed batches to the durable file, and the one that checks the config mapping. Both passed when run through `ValidateTests`. The checkpoint's live test was not run. I have no tool that can delete files, so it is still there and should be removed.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_upnext_durable.py \u2014 a probe that could not be deleted with the tools available; it holds no phase code and should be removed.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_12_similars_on_scroll_phase2.py": "<assertions>\ntests/tmp/test_12_similars_on_scroll_phase2.py:110 - control: `/api/video` is among the requested paths, so the page module ran its loads and a missing similars request is the page's fault, not the runner's. No clause.\ntests/tmp/test_12_similars_on_scroll_phase2.py:124 - exactly one request to `/recommendations` was made; a second eager or fill-viewport batch fails this. C1\ntests/tmp/test_12_similars_on_scroll_phase2.py:125 - that request is a POST and its URL's `limit` query parameter is \"48\". The unchanged page sends \"8\" and fails here, as observed. With the operator's approval this is the query string, not the body. C1\ntests/tmp/test_12_similars_on_scroll_phase2.py:129 - `#similar-videos` markup holds exactly 8 `similar-card-item` anchors, counted by regex over what `innerHTML` sets plus what `insertAdjacentHTML` adds. The unchanged page renders all 48 (observed). C2\ntests/tmp/test_12_similars_on_scroll_phase2.py:131 - those 8 cards are rows v0..v7 of the 48-row answer, in order, read from each card's `data-video-key`; rendering the last 8 or a reordered 8 fails. C2\n</assertions>\n\n<probes>\n1. `ValidateTests tests/tmp/probe_12_phase2_request.py` ran the unchanged page under the recording runner, with `/recommendations` answering 48 rows. It printed `REQ {'method': 'POST', 'path': '/recommendations', 'search': '?id=v1&host=peer.example&limit=8', 'body': '{\"likes\":[]}'}` and `CARDS 48`. So the limit travels in the query string, never the body. client/backend/server.py:89 also reads `limit` as a query param. The Step-6 seam said \"body's limit\"; I raised this with AskUser and the operator answered \"Assert the query-string limit\".\n2. `ValidateTests tests/tmp/test_12_similars_on_scroll_phase2.py` against the unchanged page failed at line 125 with `'limit': '8'` vs '48'. Before that, the control (`/api/video` requested) and the single-request assertion both passed, so it is red for the right reason.\n3. `ValidateTests tests/tmp/probe_12_phase2_cards.py` ran this file's own `_page` plus its card and id regexes over the unchanged page's real markup. It printed `COUNT 48 IDS ['v0', ... 'v9'] ['v46', 'v47'] OBSERVED []`, so the regexes read real cards and ids in order, and C2 fails on the old behaviour (48 \u2260 8).\nNo delete tool is available: tests/tmp/probe_12_phase2_request.py and tests/tmp/probe_12_phase2_cards.py are still on disk and should be removed; the checkpoint now carries what they showed.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_12_similars_on_scroll_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase2.py:124 \u2014 exactly one request reached `/recommendations`. Then :125 \u2014 that request is a POST and its `limit` query parameter is \"48\".</assertion>\n<expected>One request, `{'method': 'POST', 'path': '/recommendations', 'query': {..., 'limit': '48'}, ...}`. The run confirmed the shape: a single POST that carries `limit` in the query string. Today its value is '8'.</expected>\n<wrong_implementation>Case 1: the page keeps today's `limit: \"8\"` at index.ts:307. The run read `'limit': '8'`, so :125 fails ('8' == '48'). Case 2: the first batch is split into an 8-row request plus a follow-up at mount. That gives two `/recommendations` entries, so :124 fails.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase2.py:129 \u2014 `#similar-videos` holds exactly 8 `similar-card-item` anchors. Then :131 \u2014 their `data-video-key` ids are v0..v7, in order.</assertion>\n<expected>8 anchors with keys `videos.example::v0` \u2026 `videos.example::v7`.</expected>\n<wrong_implementation>Case 1: the page renders every row it gets back (index.ts:315, `rows.map(renderSimilarCard)` with no cap). Given the 48-row answer, the probe counted 48 anchors, ids v0..v47, so :129 fails. Case 2: the page caps at 8 but takes the wrong slice (last 8, or skips already-seen rows). The count is 8 but the ids are not v0..v7, so :131 fails.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Yes, and I rewrote the docstring. Its first bullet said \"the JSON body carries only likes and exclusions\". Nothing asserted that, and the run contradicts it: the body is `{'likes': []}` with no exclusions. I cut the parenthetical down to \"(the limit travels in the query string)\", which :125 does assert. The other claims each have an assertion: exactly one request (:124), POST with limit \"48\" (:125), exactly 8 anchors (:129), and the answer's first 8 rows in order (:131).\n2. No. There is no absence assertion. Every assertion is a count or an equality. The controls at :113 (node exit 0) and :116 (`/api/video` was requested) show the page module ran its loads.\n3. No. The expected values are test literals (48, 8, v0..v7). The test does not re-derive them. The run caught index.ts:307 (`limit: \"8\"`) sending '8', so that line drives :125. Deleting the cap the phase adds before index.ts:315 (`similarCards.innerHTML = rows.map(...)`) would render 48 again and turn :129 red.\n4. No. Each clause is read at one input, but the expected value is neither a fixed point nor today's default. C2's input is 48 rows and the expected output is 8; today's code gives 48, so the input size and the answer differ. C1's expected '48' is not the shipped '8'. The ids v0..v7 also rule out a slice of the wrong 8.\n5. No. The doubles are `fetch` (the network seam), a minimal DOM, storage, and IntersectionObserver/ResizeObserver (browser APIs). The real page module, `src/pages/video-page/index.ts`, is bundled by esbuild and runs unmodified. No module the project owns is replaced.\n6. It collects. The pytest run printed \"collected 1 item\" for the one test in the file. The fixture `bundle`, the helper `_page`, and the constants all bind.\n7. Yes, from runs. The request shape comes from the checkpoint run: `{'method': 'POST', 'path': '/recommendations', 'query': {'id': 'v1', 'host': 'peer.example', 'limit': '8'}, 'body': {'likes': []}}`. The anchor/`data-video-key` format and the rendering of all rows today come from probe_12_phase2_cards.py: \"COUNT 48 IDS ['v0', ... 'v9'] ['v46', 'v47'] OBSERVED []\". The values 48 and 8 are the phase's target, which cannot be observed before it is built; the fields they are read from were all seen.\n8. Yes, it fails. After the rewrite, ValidateTests exit status 1: \"FAILED tests/tmp/test_12_similars_on_scroll_phase2.py::test_the_first_batch_is_one_recommendations_request_for_48_rows_of_which_the_first_8_are_shown\".\n9. Yes, it is red for the right reason. The failing assertion is the C1 judge at :125: \"AssertionError: [{'method': 'POST', 'path': '/recommendations', 'query': {'id': 'v1', 'host': 'peer.example', 'limit': '8'}, 'body': {'likes': []}}] \u2026 POST and '8' == '48'\". This is not a control failure. The run got past :113, :116 and :124, so node exited 0, `/api/video` was requested, and exactly one `/recommendations` request was made. Failing on limit '8' is the unbuilt phase. The C2 assertions (:129/:131) sit after :125 and did not run here. The same runner in the probe showed 48 anchors, so they would also be red today.\n10. Yes. The C1 row gives the shape the run showed (single POST, `limit` in the query) and the value it read today ('8'). The C2 row's wrong-implementation reading (48 anchors, v0..v47) is what the probe printed. Nothing in either row is contradicted by a run. The leftover probes under tests/tmp/ (probe_12_phase2_cards.py, probe_12_phase2_request.py) still need deleting; I have no delete tool this turn.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `client/frontend/src/pages/video-page/index.ts` (EDITED)\n- The import from `../../data/videos` now also brings in `createFeedPager`.\n- Added a module constant `SIMILAR_CHUNK = 8` next to `similarStatsCache`/`similarStatsLoading`. It sits above `void loadSimilarVideos()`, so reading it cannot hit a TDZ error.\n- `loadSimilarVideos` no longer calls `fetchSimilarVideosPayload` directly with `limit: \"8\"`. After `await localLikesImported` it creates a fresh pager on each call (`createFeedPager((exclude) => fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: \"48\", apiBase }, exclude))`), so a key-rejected retry starts with nothing shown and nothing excluded. It then awaits `pager.next()` and renders only `rows.slice(0, SIMILAR_CHUNK)` into `#similar-videos` with `renderSimilarCard`. `queueSimilarStats` runs on those 8 rows only.\n- Unchanged: the empty-batch message (`No similar videos found.`), the `ProfileKeyRejectedError` \u2192 `keyRejectedNotice` retry, the escaped error message, the no-seed path and the similar-link blocks. The last are removed in phase 4.\n- The pager is a local here. The module state from the plan (all fetched rows, revealed count, loading/fetching flags, the current pager) and the scroll code belong to phase 3, which is the first phase that reads them.\n\n### `tests/active/test_frontend_video_page_similars.py` (NEW)\n- The durable home of this phase's checkpoint, as the plan names it. It has the same runner, fixture and single test as `tests/tmp/test_12_similars_on_scroll_phase2.py`, with the clause tags removed and the runner comment reworded for a file that phases 3 and 4 will extend.\n- It bundles the real page module with esbuild and imports it in node. It checks that exactly one `/recommendations` POST was made, with `limit=48` in the query. From a 48-row answer, `#similar-videos` must hold exactly 8 `similar-card-item` anchors, and they must be rows v0\u2013v7 in order. Control: `/api/video` was requested.\n\n### Observation\n- I ran the checkpoint `tests/tmp/test_12_similars_on_scroll_phase2.py` once through `ValidateTests` against this code: 1 passed.\n- That tool call wrote `tests/last_test_validation.json` / `tests/last_test_output.txt` for that one tmp path. I did not run anything under `tests/active` myself, including the new durable file and `test_frontend_video_page.py`.\n- `test_frontend_video_page.py` answers `/recommendations` with `{}`, so I expect it to take the pager's empty-batch path to `No similar videos found.`. That is a prediction; I did not observe it.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_12_similars_on_scroll_phase3.py": "<items>\n<item id=\"C1b\">\n<disposition>fixed</disposition>\n<what>Added a per-intersection loop at :160-162. For each intersection k = 2..5, :162 asserts that exactly one insert happened on that step and that the grid after it shows exactly v0..v(8(k+1)-1) in order. A page that shows all 32 remaining rows on the second intersection fails at k=2, because the grid holds 48 keys where 24 are expected. A page that appends nothing on a later step fails on the insert delta and on the key list.</what>\n</item>\n<item id=\"D1b\">\n<disposition>fixed</disposition>\n<what>The docstring's \"each\" is now carried by :162 (the new loop over intersections 2-5), which checks each step's own chunk: one insert per step, and a grid that grows by exactly the next 8 rows in order. Together with :152/:155 for the first intersection, every one of the five revealing intersections is checked on its own.</what>\n</item>\n<item id=\"N1b\">\n<disposition>fixed</disposition>\n<what>The test name's \"each \u2026 appends the next 8 rows\" is now carried by :152/:155 for intersection 1 and by :162 for intersections 2-5. :162 checks per step that the insert count rises by exactly 1 and the grid is v0..v(8(k+1)-1), so a larger, smaller or skipped chunk at any step fails.</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim CRITICAL 1 (whole-claim, :161 checks only the total): added the loop at :160-162, which checks intersections 2-5 one at a time (insert delta == 1 and grid keys == v0..v(8(k+1)-1) after step k), built from the already-captured page[\"snapshots\"]. A page that dumps the remaining 32 rows on the second intersection now fails at k=2.\nClaim RECOMMENDATION 3 (D1b/N1b uncarried): resolved by the same assertion at :162.\nRecommendations 1 (non-intersecting callback) and 2 (partial final chunk / short or empty answers) not taken: both need new runner inputs and cover cases outside this phase's C1/C2 clauses.\nShape audit: no CRITICAL. The new assertion compares against row-id ranges from the fixture input, not against a production table.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:152, :154, :155 \u2014 the first intersection makes exactly one insertAdjacentHTML call on #similar-videos, at \"beforeend\", holding the similar-card-item anchors for rows v8-v15 in order</assertion>\n<expected>insert delta 1, position \"beforeend\", keys [\"v8\", \u2026, \"v15\"]</expected>\n<wrong_implementation>A page that re-renders the grid, prepends, or inserts the wrong slice: the delta reads 0 or more than 1, the position reads \"afterbegin\", or the keys are not v8-v15.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:162 \u2014 for each intersection k = 2..5, exactly one insert is made on that step, and the grid then shows v0..v(8(k+1)-1) in order</assertion>\n<expected>For k=2,3,4,5: insert delta 1, and the grid keys are v0-v23, v0-v31, v0-v39, v0-v47</expected>\n<wrong_implementation>A page that shows all 32 remaining rows on the second intersection and nothing after it: at k=2 the grid reads v0-v47 where v0-v23 is expected. A page that appends a wrong-sized chunk or skips a step fails the key list or the insert delta at that k.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:156, :157, :166, :167 \u2014 innerHTML writes do not change through the first and fifth intersections; the grid still begins with the first 8 cards' markup; after five intersections it shows v0-v47 in order</assertion>\n<expected>writes unchanged; first[\"similar\"] starts with the loaded markup; keys v0..v47</expected>\n<wrong_implementation>A page that rebuilds the grid through innerHTML with the accumulated rows: the writes count goes up, and if the earlier cards' markup changes, the startswith check fails.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:168 \u2014 after five intersections there has still been only one /recommendations request</assertion>\n<expected>1</expected>\n<wrong_implementation>A page that prefetches the next batch on an intersection that still has unrevealed rows reads 2 or more.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:171, :173 \u2014 the sixth intersection sends a second /recommendations request, and it is a POST</assertion>\n<expected>request count 2; method \"POST\"</expected>\n<wrong_implementation>A page that stops once the fetched rows run out reads a count of 1. A page that refetches with GET reads \"GET\".</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:175 \u2014 the second request's body.exclude has exactly 48 entries, and as a set they equal the {id, host} pairs v0-v47 / videos.example</assertion>\n<expected>48 entries: {id: \"v0\"..\"v47\", host: \"videos.example\"}</expected>\n<wrong_implementation>A refetch with no exclude, with only the last chunk, with duplicates, or with video_id/instance_domain keys: the length or the pair set differs.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The negative assertions (writes unchanged at :156/:167, request count still 1 at :168) are armed by positive observables of the same run: the control at :149 and the append checks at :152/:155/:162. With the code under test deleted, the test fails at :152 (observed: inserts 0 -> 0).\n2. No. Expected values are row-id ranges built from the fixture input (v0..v47), not a copy of production's transformation. Deleting the page's sentinel append path turns :152 and :162 red, and deleting the exclude construction turns :175 red.\n3. No. The chunk is now checked at five separate intersections (:152/:155 for the first, :162 for k=2..5), and the exclude is checked against all 48 input rows.\n4. No. The doubles stand in for DOM, fetch, storage and IntersectionObserver, which are browser/network layers. The real page module and data modules run from the esbuild bundle.\n5. Yes, it collects. The new loop uses only names already bound (page, ROWS, SHOWN, _keys), and snapshots has INTERSECTIONS+1 = 7 entries, so indices 1..5 exist. The run collected and executed 1 test.\n6. Yes. The snapshot and key format was observed on the loaded grid (control :149 passed), and the exclude wire shape was observed in the earlier probe. The appended markup's format is phase 3's output and cannot be observed until the phase is built. It is read with the same _keys used at :155, which matches the card markup the page already renders.\n7. Yes. Rerun after the edit: ValidateTests [\"tests/tmp/test_12_similars_on_scroll_phase3.py\"] fails at :152 with \"{'inserts': (0, 0), 'sentinel observers': 0} / assert (0 - 0) == 1\". The control at :149 passes first, so the test is red because no observer is on the sentinel yet, not because of a harness fault.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_12_similars_on_scroll_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:152 \u2014 one sentinel intersection adds exactly one `insertAdjacentHTML` call on `#similar-videos` (the failure message also reports how many observers watch `#similar-sentinel`)</assertion>\n<expected>1 once phase 3 is built. Today's run shows `{'inserts': (0, 0), 'sentinel observers': 0}`, which is the red.</expected>\n<wrong_implementation>No observer on the sentinel, or one on another element (the runner fires only observers watching `#similar-sentinel`): 0. One insert per card: 8.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:154-155 \u2014 that insert's position is \"beforeend\", and its markup holds `similar-card-item` anchors keyed v8..v15, in that order</assertion>\n<expected>\"beforeend\"; [\"v8\", \u2026, \"v15\"]. The key format `videos.example::vN` in `renderSimilarCard` markup was seen in this run: the line-149 control passed on it.</expected>\n<wrong_implementation>Prepending (\"afterbegin\") fails the position check. Re-sending rows 0-7, sending all 48 at once, or skipping to 16-23 gives the wrong key list.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:156-157 and 162 \u2014 the grid's `innerHTML` write count does not change after the first intersection or through the fifth, and after the first intersection the grid's markup still begins with the first 8 cards exactly as they were</assertion>\n<expected>The write count equals the value at load after 1 and after 5 intersections. The markup is the loaded markup plus the appended part.</expected>\n<wrole_implementation_placeholder_removed/>\n<wrong_implementation>Re-rendering the whole grid with `innerHTML = rows.slice(0, revealed)` (the home page's `renderCards` shape) raises the write count at 156/162. Inserting before the existing cards fails the prefix check at 157.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:161 \u2014 after five intersections the grid shows v0..v47, in order</assertion>\n<expected>[\"v0\", \u2026, \"v47\"]</expected>\n<wrong_implementation>A reveal that fires only once, or that stops after a fixed count (for example a guard that treats the first reveal as the last), leaves 16 or fewer cards. A reveal that asks the pager too early leaves some rows unrevealed.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:163 and 166 \u2014 still 1 `/recommendations` request after five intersections, and 2 after the sixth</assertion>\n<expected>1, then 2</expected>\n<wrong_implementation>Asking the pager on every intersection gives more than 1 at line 163. Never asking once the fetched rows are used up (the home page's fill loop stopping when nothing is left) leaves 1 at line 166. Asking again while a fetch is still in flight gives 3.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:168 and 170 \u2014 the second `/recommendations` request is a POST whose `exclude` holds exactly the 48 {id, host} pairs (v0..v47, videos.example)</assertion>\n<expected>\"POST\"; 48 entries shaped `{'id': 'v0', 'host': 'videos.example'}`. This shape was seen in tests/tmp/probe_pager_exclude_body.py, where the real `createFeedPager` drove `fetchSimilarVideosPayload` and the second request printed `METHOD POST \u2026 KEYS ['exclude', 'likes'] N 48 FIRST3 [{'id': 'v0', 'host': 'videos.example'}, \u2026]`.</expected>\n<wrong_implementation>A new pager per load-more, or a direct call to `fetchSimilarVideosPayload` without the pager's list, sends no `exclude` (empty list here). Excluding only the 8 revealed-at-once rows, or the rows of one chunk, gives a count other than 48.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, before the fix, and it is now fixed. The docstring said `innerHTML` \"is never set again\", but the test only checked the write count after the first intersection. I added line 162, which checks the count is unchanged after the fifth intersection, and narrowed the docstring to \"not set again through the five intersections that reveal all 48 rows\". The docstring's old \"Control: an IntersectionObserver watches #similar-sentinel\" is reworded (see 9). Every docstring bullet now has an assertion: the insert count, position and keys (152-155), the write count and prefix (156-157, 162), all 48 rows in order (161), no second request through five intersections (163), the sixth sends one (166), and it is a POST whose exclude holds exactly the 48 pairs (168, 170).\n2. Absence only: no. The negatives are 156/162 (write count unchanged) and 163 (still 1 request). 156 is armed by 152-155 on the same snapshot: an insert of v8..v15 happened. 162 and 163 are armed by 161 on the same snapshot: all 48 rows are showing, so five intersections ran. 163 is also paired with the positive 2 at 166.\n3. Echoed literal: no. Each expected value is either a fixture literal (v-rows) or a count from the recording stubs, and the test re-implements none of production's logic. Deleting the phase's `similarCards.insertAdjacentHTML(\"beforeend\", \u2026)` in `revealSimilarChunk` turns 152 red. Deleting `void loadMoreSimilar()` turns 166 red. Replacing the pager with a direct fetch turns 170 red.\n4. One value: no. The grid is read at three points (load, 1 intersection, 5 intersections), and the request count at 5 and 6. The appended keys and the exclude list are each compared against 8 and 48 distinct fixture rows, not against another value from the same source.\n5. The double: no. Only severed layers are stubbed: the DOM element objects, `IntersectionObserver` (fired by hand), and `fetch` (the network). The page module, `createFeedPager`, `fetchSimilarVideosPayload` and `renderSimilarCard` are the real code, bundled by esbuild.\n6. It collects: yes. `--collect-only` exited 0, and the real run printed \"collected 1 item\", which matches the one test written. All names bind: ROWS, SHOWN, INTERSECTIONS, _page, _keys and bundle, and the snapshot keys similar/writes/inserts/recommendations are the ones the runner emits.\n7. Observed, not predicted: yes, now. The first 8 cards' markup and the `videos.example::vN` key regex were seen in this run: the line-149 control passed on them. The second request's shape (POST to /recommendations, body `exclude` as 48 `{id, host}` dicts) was seen in probe tests/tmp/probe_pager_exclude_body.py, which runs the real pager over the real fetch function. It printed `METHOD POST PATH /recommendations KEYS ['exclude', 'likes'] N 48 FIRST3 [{'id': 'v0', 'host': 'videos.example'}, \u2026]`. One thing is still a prediction: that the phase's appended html is `renderSimilarCard` output like the first 8. The code that produces it does not exist yet, so the Phase 3 build run is what confirms it. I have no tool that deletes files, so the probe is still in tests/tmp and should be removed. It holds no phase code.\n8. Red, not green: yes, it is red. Final run: `[exit status 1]`, \"1 failed\".\n9. Red for the right reason: yes, after a rewrite. The first run failed on a CONTROL: line 151, `assert page[\"sentinelObservers\"] >= 1` \u2192 `AssertionError: 0`. So that run never reached a C1/C2 assertion and measured nothing. The sentinel observer is itself this phase's work, so it cannot serve as a precondition. I removed it as a control. The runner only fires observers watching `#similar-sentinel`, so a passing line 152 already shows the observer is on the sentinel. The observer count now goes into line 152's failure message. The re-run passes the line-149 control (8 cards v0..v7, one request) and fails the C1 assertion at line 152: `AssertionError: {'inserts': (0, 0), 'sentinel observers': 0}` / `assert (0 - 0) == 1`. The phase is not implemented: there is no observer and no append.\n10. Observed expected output: the run did not contradict any row. The only value it showed for a row is at line 152, where the unbuilt code gives 0 and the row's expected under the right implementation is 1. The C2 exclude shape in the rows comes from the probe output quoted in 7. The key format comes from the control that passed at line 149.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `client/frontend/src/pages/video-page/index.ts`\n- The import from `../../data/videos` now also brings in `type FeedPager`.\n- Added a `similarSentinel` lookup (`#similar-sentinel`) next to `similarSection` and `similarCards`.\n- Added module paging state next to `SIMILAR_CHUNK` (8), placed above the module-load `void loadSimilarVideos()` call so the synchronous reset in that function does not hit a temporal-dead-zone (TDZ) error: `similarRows`, `similarRevealed`, `similarLoading`, `similarPager` (starts null), `similarFetchingMore` and `similarScrollAttached`. The `SIMILAR_CHUNK` comment now says it is both the first count and the per-scroll step.\n- `loadSimilarVideos`:\n  - It first resets the rows, the revealed count and `similarLoading = true`, and puts `Loading...` back in the grid, so a key-rejected retry starts from nothing.\n  - It stores the fresh pager in `similarPager`.\n  - After the first batch arrives, it drops a superseded call's result with `current !== similarPager`, on both the success and the error path.\n  - It clears `similarLoading` on every path, stores the rows and renders the first 8 through `innerHTML` as before.\n  - Only after a non-empty first batch does it call `setupSimilarScroll()` and then `fillSimilarViewport()`. On the empty path (which `tests/active/test_frontend_video_page.py` takes, answering `{}`), `IntersectionObserver`, `document.documentElement` and `innerHeight` are never touched.\n  - The `similarLinkInline` block stays; removing it is phase 4.\n- New `revealSimilarChunk()`:\n  - Does nothing while `similarLoading`.\n  - Appends the next up-to-8 fetched rows with `similarCards.insertAdjacentHTML(\"beforeend\", \u2026)` using the unchanged `renderSimilarCard`, and queues stats for that slice only.\n  - When no fetched row is left, it calls `void loadMoreSimilar()` and returns false.\n- New `loadMoreSimilar()`:\n  - Returns early without a pager, while loading, while a fetch is running, or when `pager.exhausted` is set.\n  - Otherwise awaits `pager.next()`; the pager supplies the `exclude` list of every row fetched so far.\n  - Drops a stale pager's result and appends new rows to memory.\n  - On failure it only calls `console.warn` and leaves the grid alone.\n  - After appending, it reveals once and runs fill-viewport, because the sentinel may still be in view.\n- New `fillSimilarViewport()`: while `scrollHeight <= innerHeight + 120`, it reveals chunks, up to 50 times, and stops at the first reveal that changes nothing. As the draft deliberately specifies, it does not also require unrevealed rows. The reveal that finds none left is the one that asks for the next batch; a comment says why.\n- New `maybeRevealSimilarOnScroll()`: reveals when `innerHeight + scrollY >= scrollHeight - 240`.\n- New `setupSimilarScroll()`: attached once per page view. It creates an `IntersectionObserver` (`rootMargin: \"200px\"`) on `#similar-sentinel` when the element exists, a passive `scroll` listener, and a `resize` listener that runs the scroll check and then fill-viewport.\n\n### `client/frontend/video-page.html`\n- Added `<div id=\"similar-sentinel\" class=\"similar-sentinel\" aria-hidden=\"true\"></div>` right after `#similar-videos`, inside `#similar-section`. It is hidden together with the section when there is no seed. Both links stay in place for phase 4.\n\n### `client/frontend/src/video.css`\n- Added a `.similar-sentinel { height: 1px; }` rule after `.similar-grid .loading, .similar-grid .error`. The home page's `.feed-sentinel` lives in `videos.css`, which this page does not import.\n\n### `tests/active/test_frontend_video_page_similars.py`\n- Not touched. It has already gated as phase 2's durable test, and it still holds as the code stands: its observer is never fired, and its tall document keeps fill-viewport from looping. The phase 3 checkpoint in `tests/tmp/` is the one this phase is gated on, and moving it into the active file is left to checkpoint promotion.\n\n### Not changed\n- `client/frontend/dist/` is not rebuilt. It stays stale until `npm run build`, as the impact inventory records.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>"
  },
  "requirements": "### Purpose\n\nUsers keep browsing from the video page, and today it shows only 8 similar videos (`limit: \"8\"` in `loadSimilarVideos`, `client/frontend/src/pages/video-page/index.ts`). To see more, they must follow a link to a second page: the home feed in its up-next mode, `/videos.html?id=\u2026&host=\u2026` (`useSimilar` in `client/frontend/src/pages/videos/index.ts`). This build makes the video page itself offer a long list of up-next videos that loads as the user scrolls, the way the home page does, so they no longer need to leave it.\n\n### Context delivered by earlier builds (not to be changed)\n\n- Issue 09 (similars diversity) made every up-next response a random draw. A limit-48 request scores the seed's pool (at most `SIMILAR_VIDEO_TOP_K` = 300 rows), takes the top min(4 \u00d7 48 = 192, pool size) rows as the window, and draws 48 of them by score-weighted sampling. Two identical requests return different pages. The draw is described in `engine/server/api/recommendations/docs/OVERVIEW.md`. The Engine drops rows named in the request's `exclude` while it builds the pool, so a batch that excludes the rows already shown is drawn only from rows not yet shown.\n- The Client backend (`client/backend/server.py`) caps a feed request's page size at `FEED_PAGE_SIZE` = 48 (`min(limit or 48, 48)`) and forwards `limit = page_size * FEED_OVERFETCH_FACTOR` (2) to the Engine, so it can refill a page after removing blocked rows. The Engine caps `limit` at 2 \u00d7 `default_limit`. The Client refuses a feed request that excludes more than `MAX_FEED_EXCLUDE` = 500 videos.\n- `createFeedPager` in `client/frontend/src/data/videos.ts` already pages a feed. Each batch excludes the last 500 rows shown (keyed by `video_id` + `instance_domain`) and drops any row the Engine repeats anyway. After a batch that adds no new row, or that fails, `exhausted` is set and `next()` makes no further request. `fetchSimilarVideosPayload(query, exclude)` is the fetch the home page gives it.\n- Issue 11 (fast similars response) is archived. The video page already requests similars in parallel with the video's metadata.\n\n### R1 \u2014 One full batch per request\n\n- The video page requests up-next similars with `limit` 48 (the Client's `FEED_PAGE_SIZE`, equal to the Engine's `BATCH_SIZE`) instead of 8, through `fetchSimilarVideosPayload` with the seed's `id`, `host` and `apiBase`, as today.\n- No server change is required: the Client and Engine already serve a 48-row draw in a single response.\n\n### R2 \u2014 Progressive reveal from memory\n\n- The page keeps every row it has fetched in memory and renders only a revealed prefix of them into `#similar-videos`.\n- After the first batch arrives it reveals 8 cards, the same count the page shows today.\n- Each time the user nears the bottom of the page, it reveals the next 8 rows, appending cards and not re-rendering the ones already shown. \"Near the bottom\" works as on the home page (`client/frontend/src/pages/videos/index.ts`): an `IntersectionObserver` on a sentinel element placed after the grid, with `rootMargin: \"200px\"`, plus a passive `scroll` listener and a `resize` listener as a fallback (near bottom = `innerHeight + scrollY >= scrollHeight - 240`).\n- While the document is too short to scroll (`scrollHeight <= innerHeight + 120`) and unrevealed rows remain, it keeps revealing chunks until the page can scroll (bounded by a safety counter, as `maybeFillViewport` does on the home page).\n- Live view counts (`queueSimilarStats`) are requested only for the cards being revealed, not for the whole in-memory batch.\n\n### R3 \u2014 Paging past the first batch\n\n- Fetching goes through `createFeedPager` (one pager per page load), passing a function that calls `fetchSimilarVideosPayload` with the seed query and the pager's `exclude` list. Every later batch therefore excludes the rows already shown (up to the last 500), and rows the Engine repeats are dropped.\n- When a reveal finds no unrevealed rows left, the page asks the pager for the next batch, unless the pager is exhausted or a fetch is already in flight. New rows are appended to the in-memory list, and revealing continues. Because the sentinel may still be in view, it reveals at once and runs the fill-viewport step after appending, as the home page's `loadMoreVideos` does.\n- Paging ends for this page view at the first batch that adds no new row or that fails. A failure on any batch after the first leaves the cards already shown in place and is only logged with `console.warn`. No error replaces the grid.\n\n### R4 \u2014 Behaviour that stays as it is\n\n- The first similars request still waits for the local-likes import (`localLikesImported`) before it is sent.\n- If the first batch returns no rows, the grid shows `No similar videos found.`.\n- If the first batch fails, the grid shows the error's message (fallback text `Failed to load similar videos`), HTML-escaped.\n- If the first batch fails with `ProfileKeyRejectedError`, the grid shows `keyRejectedNotice` with a retry that reloads the similars from scratch, with a fresh pager and nothing shown.\n- Without a `seedId`, `#similar-section` stays hidden and nothing is fetched.\n- Cards keep today's markup and behaviour (`renderSimilarCard`): thumbnail, duration, title, channel, views and age, the liked or disliked badge from `cardReaction`, `data-video-key`, and a link to `/video-page.html?\u2026` for that row.\n- The metadata, reactions, block buttons and description behaviour of the page are untouched.\n\n### R5 \u2014 Remove the links to the separate similar-videos page\n\n- Remove the header nav link `<a id=\"similar-link\" \u2026>Similar videos</a>` and the section header link `<a id=\"similar-link-inline\" \u2026>Open full list</a>` from `client/frontend/video-page.html`, together with the code in `client/frontend/src/pages/video-page/index.ts` that looks them up and sets their `href`.\n- The section keeps its `Similar videos` heading.\n- `/videos.html?id=\u2026&host=\u2026` (the home page's `useSimilar` mode) stays working as it is, so old bookmarks still open. Nothing in the app links to it any more. This is a deliberate choice by the operator: links only, no removal of the mode and no redirect.\n- `client/frontend/dist/` is build output and is not edited by hand.\n\n### R6 \u2014 Replacement pager test\n\n- Add a durable test in `tests/active` that replaces the retired `tests/archive/upnext_random_draw/test_frontend_videos.py`. Like the retired file, it bundles `client/frontend/src/data/videos.ts` with esbuild and runs it in node against the real Client and Engine, with minimal in-memory `window`, `localStorage` and `sessionStorage`.\n- It drives `createFeedPager` over `fetchSimilarVideosPayload` for an up-next seed at limit 48, where the first batch has `seed.mode == \"upnext\"`, and asserts two things. First, no batch repeats a row (`video_id`, `instance_domain`) of any earlier batch, and the second batch is non-empty. Second, once a batch comes back empty, no later `next()` call makes a request, counted on the fetch function handed to the pager.\n- It must hold under 09's random draw. There is no control asserting that two plain fetches return the same page. The seed and batch budget must actually reach an empty batch: a seed pool is at most 300 rows, so at 48 per batch about 7 batches exhaust it. Otherwise the test has to show that its seed's pool ends within the budget.\n- Map the new test in `.un/skills/devsecops/config.json` to `client/frontend/src/data/videos.ts` (and to `client/backend/server.py`, which it runs through).\n- Update `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` to record that the `test_frontend_videos` item is covered by this build, leaving its other five tests open.\n\n### Baseline suite state\n\nBefore the build, the active suite (`tests/active`) passes: exit code 0, not a variant run. Record and output go to `tests/last_test_validation.json` and `tests/last_test_output.txt`. Working tests go in `tests/tmp`, retired ones in `tests/archive`, plans in `docs/project/plans`.\n\n### Out of scope\n\n- Any Engine or Client backend change to the up-next route, batch size, draw or exclude handling.\n- Removing or redirecting the `/videos.html?id=` mode.\n- The other five retired up-next tests tracked by issue 35.",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6"
  ],
  "initial_solution": "### Approach\n\nThe change is confined to the video page module (`client/frontend/src/pages/video-page/index.ts`), its HTML (`client/frontend/video-page.html`), one CSS rule in `client/frontend/src/video.css`, one new active test, one config entry and one issue note. No server file changes, and `createFeedPager` and `fetchSimilarVideosPayload` in `data/videos.ts` are used as they are.\n\n**R1, one full batch per request.** `loadSimilarVideos` stops calling `fetchSimilarVideosPayload` directly with `limit: \"8\"`. It builds one pager per page load with `createFeedPager`, and the pager's fetch function calls `fetchSimilarVideosPayload` with `{ id: seedId, host: seedHost, limit: \"48\", apiBase }` and the `exclude` list the pager passes in. The Client caps the page at 48 and over-fetches 96 from the Engine, so each response is one full 48-row draw, as R1 states.\n\n**R2, progressive reveal from memory.** The page keeps a small amount of module state next to the existing `similarStatsCache`: the rows fetched so far, how many are revealed, a `loading` flag for the first batch, a `fetchingMore` flag, and the current pager. One reveal function (the counterpart of the home page's `loadNextChunk`) moves the revealed count forward by 8 (a `SIMILAR_CHUNK` constant). It renders only the newly revealed slice with `renderSimilarCard`, appends it to `#similar-videos` with `insertAdjacentHTML(\"beforeend\", \u2026)` so earlier cards are never re-rendered, and calls `queueSimilarStats` on that slice only. The first render after the first batch uses `innerHTML` for the first 8 cards, which replaces the `Loading...` placeholder. The bottom is detected the same way as on the home page. A new `<div id=\"similar-sentinel\" class=\"similar-sentinel\" aria-hidden=\"true\">` is placed right after `#similar-videos` inside `#similar-section`, watched by an `IntersectionObserver` with `rootMargin: \"200px\"`. A passive `scroll` listener and a `resize` listener run the same check (`innerHeight + scrollY >= scrollHeight - 240`), and resize also runs fill-viewport. The fill-viewport function copies `maybeFillViewport`: while unrevealed rows remain and `scrollHeight <= innerHeight + 120`, it reveals chunks, stopping at 50 or when a reveal changes nothing. It runs after the first render and after every appended batch. `video.css` gets a 1px-height `.similar-sentinel` rule, because the home page's `.feed-sentinel` rule lives in `videos.css`, which this page does not import.\n\n**R3, paging past the first batch.** When the reveal function finds no unrevealed row, it calls a `loadMoreSimilar` modelled on the home page's `loadMoreVideos`. That function returns early while the first batch is loading, while a fetch is already running, or when `pager.exhausted` is set. Otherwise it awaits `pager.next()`, checks that the pager is still the current one, and appends the new rows to memory. On success it reveals right away and then runs fill-viewport, because the sentinel may still be in view and the observer would not fire again. On failure it calls `console.warn` and leaves the grid alone. The pager itself handles the stop rule: a batch with no new row, or a failed batch, sets `exhausted`, and after that no request is made.\n\n**R4, unchanged behaviour.** The first `pager.next()` still runs after `await localLikesImported`. An empty first batch shows `No similar videos found.`. A failed first batch shows the escaped message or `Failed to load similar videos`. `ProfileKeyRejectedError` passes through the pager unchanged (it rethrows), so the `keyRejectedNotice` path stays. Its retry calls `loadSimilarVideos` again, and that function now starts by resetting the in-memory rows and the revealed count, setting `loading`, putting `Loading...` back in the grid and creating a fresh pager. With no `seedId`, the section is hidden and the function returns before any pager, observer or listener exists. `renderSimilarCard`, the stats helpers, metadata, reactions, block buttons and description code stay as they are.\n\n**R5, link removal.** In the HTML I delete `<a id=\"similar-link\">` from the header nav and `<a id=\"similar-link-inline\">` from `.section-header`, and keep the `<h3>Similar videos</h3>`. In the module I delete the two `getElementById` constants, the top-level block that sets `similarLink.href`, and the block inside `loadSimilarVideos` that sets `similarLinkInline.href`. `pages/videos/index.ts` is not touched, so `/videos.html?id=\u2026&host=\u2026` keeps working. `dist/` is not edited.\n\n**R6, replacement test.** A new `tests/active/test_frontend_upnext_pager.py` follows the retired file's harness: an esbuild ESM bundle of `createFeedPager` and `fetchSimilarVideosPayload` from `data/videos.ts`, a node runner with in-memory `window`, `localStorage` and `sessionStorage`, the `engine_client` fixture, and the `linux` search seed. Changes from the old file: the page size is `\"48\"`; the two plain-fetch control runs are removed, and the first pager batch's `seed.mode` is reported and checked to be `upnext` instead; the budget is `MAX_BATCHES = 10`. The assertions are: the first and second batches are non-empty and share no row; no batch repeats a `(video_id, instance_domain)` row from any earlier batch; an empty batch appears before the last call in the budget, which is what shows this seed's pool ends within the budget; the counted calls go 1\u2026k up to the empty batch and do not increase after it. `.un/skills/devsecops/config.json` gets an entry mapping the test to `client/frontend/src/data/videos.ts` and `client/backend/server.py`. Issue 35 gets a comment saying the `test_frontend_videos` item is covered by this build's test, and its list item is marked as covered; the other five items stay open.\n\n**Why the budget is 10.** From `engine/server/data/similarity_candidates.py`: `_build_rows` takes the top `SIMILAR_VIDEO_TOP_K` (300) rows of the score-ranked candidates first, and only then drops excluded rows. Excluding shown rows therefore shrinks one fixed top-300 pool and does not bring in deeper ANN hits. At 48 per batch the pool runs out by about batch 7 (the author cap makes it shallower), so batch 8 comes back empty. Ten batches leave slack for rows a higher-nprobe fallback step turns up. Ten also keeps the exclude list at 480 or fewer entries, under the 500 cap, so the Engine always sees every row already shown within the budget.\n\n### Alternatives considered\n\n- **Pull the home page's infinite-scroll code into a shared helper used by both pages.** Rejected for this build. It would change `pages/videos/index.ts`, whose state layout (sample, shuffle, modes) is different, and the scope says to leave that page alone. The copy is about 40 lines. This is deliberate duplication: if a third paged surface shows up, that is the point to extract the helper.\n- **Page by requesting 8 rows at a time from the server.** Rejected by R1, and each request rebuilds and scores the pool, so eight times the requests for the same rows.\n- **Render all 48 rows as soon as they arrive.** Rejected by R2. It would also fire live-stats requests for 48 cards the user may never scroll to.\n- **Switch to the home page's `video-card` component.** Rejected by R4, which keeps `renderSimilarCard` markup.\n- **Set up the observer and listeners at module load, as the home page does.** Rejected. See the first risk below. They are created once, the first time a first batch returns rows.\n\n### Gotchas and risks\n\n- **Existing test environment.** `tests/active/test_frontend_video_page.py` imports the real page module in node, with no `IntersectionObserver`, no `document.documentElement` and no `innerHeight`, and it answers `/recommendations` with `{}`. If the observer or listeners were created at module load, or on an empty first batch, that test would break. Creating them only after a non-empty first batch keeps it passing unchanged. The test's `window.addEventListener` stub already exists.\n- **Rows without a `video_id` or host** are dropped by the pager and were not dropped before. The Engine always sets both, so in practice nothing changes. I'm noting it, not handling it.\n- **Later batches can be slower.** Once exclusions shrink the cached pool below 48 rows, the Engine runs its live ANN fallback. Nothing shows while that fetch runs (the home page has no indicator either). The cards already shown stay usable.\n- **The test's empty-batch assertion depends on the Engine's current pool rule** (top 300, then exclude). If that rule changes to refill from deeper hits, the test fails loudly, printing the batch sizes. It does not pass vacuously.\n- **Test runtime.** About 8 Client\u2192Engine round trips, some running the fallback. The runner keeps the retired file's 300 s timeout.\n- **Layout.** Where the similar section sits below a tall player, the page is usually scrollable already, so fill-viewport rarely runs. It matters on very tall screens and after a resize.\n\n### Tradeoffs asked of the operator\n\n- The list ends quietly when the seed's pool runs out (about 300 rows at most, often fewer), with no \"end of list\" marker. This matches the home page.\n- A failure on a later batch is only a `console.warn`. The user sees paging stop with no message, as R3 specifies.\n- Up to a few hundred cards can build up in the DOM during one page view. There is no windowing or virtualisation. That is a deliberate simplification; windowing is the upgrade path if it ever matters.\n- The scroll code is copied from the home page rather than shared, as described under the first alternative.",
  "conflicts": "none",
  "impacts": "\n<impacts>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"import line 6 (`fetchSimilarVideosPayload, resolveApiBase` from ../../data/videos) and line 20 (`type { VideoRow }`)\">\n**What changes.** Line 6 adds `createFeedPager` and the type `FeedPager` (and `ExcludedVideo` if the fetch closure gets an annotation). `fetchSimilarVideosPayload` is still imported, but it is only called inside the pager's fetch closure. The type import at line 20 may need `VideosPayload` if module state or return types name it (`client/frontend/src/types/videos.ts:86`).\n\n**What depends on it.** esbuild's bundle of this module in `tests/active/test_frontend_video_page.py:92` and the vite build (`vite.config.ts:89`). `data/videos.ts` already imports `./cache`, `./local-likes`, `./api-base` and `./profile`, so the bundle graph does not grow.\n\n**Risk: low.** A misspelt named import fails `npm run build` and the esbuild step of test_frontend_video_page, whose `check=True` turns a failure into a fixture error.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"element lookups: `similarLink` (line 43) and `similarLinkInline` (line 51) removed; new `#similar-sentinel` lookup added beside `similarSection`/`similarCards` (49-50)\">\n**What changes.** Two `getElementById` constants are deleted and one is added (e.g. `similarSentinel`).\n\n**What depends on it.**\n- A grep for `similarLink` in `client/frontend/src` finds only lines 43, 51, 75-80 and 296-300, so nothing else reads the removed constants.\n- The test stub's `getElementById` creates an element for any id (`test_frontend_video_page.py:63`), so a new lookup is harmless there.\n\n**Risk: low.** If any reference is left behind, tsc and vite fail to compile, which gives a loud failure rather than a silent one.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"top-level block `if (similarLink && seedId) { \u2026 similarLink.href = `/videos.html?\u2026` }` (lines 75-80)\">\n**What changes.** The block is deleted (R5).\n\n**What depends on it.** Nothing else. The description-toggle block (82-90) and `localLikesImported` (93-95) directly below it are independent of it. The archived plan 19-14 describes the description block as \"next to the `similarLink` wiring\" (`docs/project/plans/archive/19-14-collapsible-description.md:567`). That wording is historical and archived, so no edit is needed.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"module state next to `similarStatsCache`/`similarStatsLoading` (lines 72-73): new `SIMILAR_CHUNK = 8`, rows, revealed count, `loading`, `fetchingMore`, current pager, observer/listeners-attached flags\">\n**What changes.** New `let`/`const` module state is added in the file's style. `statsNumberFormat` and `DESCRIPTION_CLAMP_LINES` (55-57) set the precedent for module constants.\n\n**Home-page counterparts.** `pages/videos/index.ts:84-97` holds the equivalents: `state.loading`, `pager`, `fetchingMore`, `feedObserver`, `fallbackListenersAttached`. That file's `CHUNK_SIZE` is 6 (line 69); this page uses 8 per R2.\n\n**Ordering constraint.** The module calls `void loadSimilarVideos()` at line 98, before most function declarations. Functions hoist, but `let`/`const` state does not: any state that `loadSimilarVideos` touches synchronously (before its first `await`) must be declared above line 98, or it throws a TDZ ReferenceError at import. The plan's reset of rows, revealed count, `loading` and the `Loading...` placeholder happens synchronously at the top of `loadSimilarVideos`, so this constraint applies to it directly.\n\n**What depends on it.** The new reveal, load-more and fill functions, and `loadSimilarVideos`.\n\n**Risk: medium.** A TDZ error would break the whole page module, and it would also make `test_frontend_video_page.py` exit non-zero. That test would catch it, which is good.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"loadSimilarVideos() (lines 290-325)\">\n**What changes.**\n1. The early returns stay: missing elements, and no `seedId` (the section is hidden, R4).\n2. The `similarLinkInline` block (296-301) is deleted.\n3. New reset step: clear rows, set revealed = 0, set `loading = true`, put `<div class=\"loading\">Loading...</div>` back into `similarCards`, and create a fresh `createFeedPager((exclude) => fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: \"48\", apiBase }, exclude))`.\n4. `await localLikesImported` stays before the first `pager.next()`.\n5. The success path clears `loading`, stores the rows, renders the first 8 via `innerHTML` and `queueSimilarStats` on that slice only, sets up the observer and listeners once, then runs fill-viewport.\n6. An empty result keeps `No similar videos found.`.\n7. The catch keeps the `ProfileKeyRejectedError` \u2192 `keyRejectedNotice(() => void loadSimilarVideos())` branch and the escaped message with the `Failed to load similar videos` fallback. `loading` must also be cleared on the error path.\n\n**What depends on it.**\n- The module-load call at line 98.\n- The `keyRejectedNotice` retry, via `client/frontend/src/components/key-rejected.ts:11`, whose `onForget` callback is what re-invokes it.\n- `test_frontend_video_page.py`, which answers `/recommendations` with `{}`. `createFeedPager` then returns `{rows: []}` and sets `exhausted` (`data/videos.ts:57-66`), so the page takes the \"No similar videos found.\" branch and no observer is created. The test asserts nothing about similars but needs the process to exit 0.\n\n**Behaviour deltas.**\n- **Row filter.** The pager drops rows lacking `video_id` or `instance_domain` (`data/videos.ts:58-61`). The old code rendered them.\n- **`seedHost` null.** `fetchSimilarVideosPayload` omits `host`, as before (`buildSimilarUrl`, lines 101-102).\n- **Stale pager.** On retry, a stale in-flight `loadMoreSimilar` must see `current !== pager` and drop its result, as the home page does (`pages/videos/index.ts:239`).\n- **Double run.** If `loadSimilarVideos` were entered twice concurrently, which only the retry can do, the older call's result would overwrite the grid. The home page has the same shape and does not guard it. Low likelihood, since the retry button appears only after the first call has finished.\n\n**Risk: medium.** This is the core behaviour change. The R4 paths (empty, error, key-rejected, no seed) have no automated coverage beyond test_frontend_video_page's exit code.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"new functions: reveal-next-chunk (counterpart of `loadNextChunk`), `loadMoreSimilar` (counterpart of `loadMoreVideos`), fill-viewport (counterpart of `maybeFillViewport`), scroll check (counterpart of `maybeLoadOnScroll`), observer/listener setup (counterpart of `setupInfiniteScroll`)\">\n**What changes.** About 40 new lines, copied from `client/frontend/src/pages/videos/index.ts:232-375`, with these differences:\n- **Append-only render.** The reveal appends only the new slice via `similarCards.insertAdjacentHTML(\"beforeend\", slice.map(renderSimilarCard).join(\"\"))` and calls `queueSimilarStats(slice)`. The home page's `renderCards` re-renders the grid instead.\n- **Load-more trigger.** Reveal returns false and calls `void loadMoreSimilar()` when nothing is left to reveal.\n- **`loadMoreSimilar` guards.** It returns on `loading || fetchingMore || pager.exhausted`, checks `current !== pager` after the await, and appends rows. It logs `console.warn` on failure and never touches the grid. On success it reveals, then runs fill-viewport.\n- **Fill-viewport.** It is bounded by a safety counter of 50, the condition `scrollHeight <= innerHeight + 120`, and stops when a reveal changes nothing.\n- **Scroll check.** `innerHeight + scrollY >= document.documentElement.scrollHeight - 240`.\n- **Observer and listeners.** `IntersectionObserver` with `rootMargin: \"200px\"` on `#similar-sentinel`, a passive `scroll` listener, and a `resize` listener that runs both the scroll check and fill-viewport. All are created only after a non-empty first batch, and attached once (a flag like `fallbackListenersAttached`).\n\n**What depends on it.**\n- **Stats.** `applySimilarStatsToDom` (1090-1097) finds cards by `data-video-key` inside `similarCards`, so appended cards receive stats. `queueSimilarStats` skips keys already cached or loading (989-990), so revealing in slices causes no duplicate fetches.\n- **Retry reuse.** On a retry the observer and listeners are reused and keep calling the reveal, which reads the current module state. The home page instead disconnects the observer and re-creates it (352-356). Either works, as long as the reveal is a no-op while `loading`.\n\n**Environment.** `IntersectionObserver`, `document.documentElement` and `window.innerHeight` are absent in the test_frontend_video_page stub (lines 24-76). Any call at module load, or on the empty-first-batch path, throws in node.\n\n**Loading guard.** The observer can fire right after `observe()` if the sentinel is within 200px of the viewport. The reveal must be a no-op, or at most a reveal from memory, while `loading`.\n\n**Later-batch key rejection.** A `ProfileKeyRejectedError` on a later batch is swallowed by the warn path. Paging stops silently and no notice is shown. This is consistent with R3 (only the first batch shows errors), but it differs from the first-batch path.\n\n**Risk: medium.** None of this is exercised by any automated test: node has no layout, and no browser harness exists. The maintainer's browser check is the only verification of reveal, append, observer and fill.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"renderSimilarCard (1168-1201), queueSimilarStats (973-1000), fetchSimilarStatsForHost/fetchViewsIndividually/fetchBatchViews/fetchSingleViews (1005-1085), applySimilarStatsToDom (1090-1097), resolveSimilarKey/resolveSimilarStats (936-953), videoPageUrl (1135-1156)\">\n**What changes.** Nothing (R4).\n\n**What depends on them.** The new reveal function. `queueSimilarStats` now runs per 8-card slice. Each slice groups by host and issues one PeerTube `/api/v1/videos?id=\u2026` batch per host, so live-stats requests to remote instances grow with scrolling: at most about 300 cards over a long page view. `fetchBatchViews` puts every id in the URL query. At 8 per slice the URL stays short.\n\n**Risk: low.**\n</impact>\n<impact path=\"client/frontend/video-page.html\" element=\"header nav `<a id=\\\"similar-link\\\" class=\\\"nav-link\\\" href=\\\"/\\\">Similar videos</a>` (line 22)\">\n**What changes.** The link is deleted (R5). The nav keeps Home, Likes, Search and About.\n\n**What depends on it.** `.header-nav` in `video.css` is a fixed flex pill, so one fewer link only narrows it. No script reads the element once lines 43 and 75-80 are gone.\n\n**Risk: low.**\n</impact>\n<impact path=\"client/frontend/video-page.html\" element=\"`#similar-section` (lines 124-132): `<a id=\\\"similar-link-inline\\\" \u2026>Open full list</a>` removed from `.section-header`; new `<div id=\\\"similar-sentinel\\\" class=\\\"similar-sentinel\\\" aria-hidden=\\\"true\\\"></div>` after `#similar-videos`\">\n**What changes.**\n- The inline link is deleted, and the `<h3>Similar videos</h3>` stays. `.section-header` (`video.css:521-527`, `justify-content: space-between`) then holds a single h3, which renders left-aligned. No CSS change is needed.\n- The sentinel sits inside `#similar-section`, after the grid. It is hidden along with the section when there is no seed.\n\n**What depends on it.**\n- The module's sentinel lookup and observer.\n- `.un/skills/devsecops/config.json:148-152` maps test_frontend_video_page to this file, so the edit reselects that test.\n\n**Risk: low.** The static `Loading...` placeholder (line 130) is kept, and the module rewrites it on a retry.\n</impact>\n<impact path=\"client/frontend/src/video.css\" element=\"new `.similar-sentinel { height: 1px; }` rule, near `.similar-grid` (534-538) / `.similar-grid .loading, .error` (616-620)\">\n**What changes.** One new rule, mirroring `.feed-sentinel` in `client/frontend/src/videos.css:132-134`. The video page imports only `video.css` (`pages/video-page/index.ts:5`), and a grep finds no `@import` in either stylesheet, so the plan's reason for the new rule holds.\n\n**What depends on it.** The sentinel element. test_frontend_video_page loads CSS as `--loader:.css=empty`, so the test is unaffected, though the config mapping reselects it.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/videos.css\" element=\".feed-sentinel (132-134)\">\n**What changes.** Nothing. It is the model for the new rule.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/data/videos.ts\" element=\"createFeedPager (37-70), MAX_FEED_EXCLUDE (28), fetchSimilarVideosPayload (130-157), buildSimilarUrl (98-107)\">\n**What changes.** Nothing. The file gains a second production consumer, the video page, alongside `pages/videos/index.ts:94,181`.\n\n**Facts the page relies on.**\n- `next()` rethrows the fetch error after setting `exhausted` (51-55), so `ProfileKeyRejectedError` from a 401 (143-145) reaches the page's catch unchanged.\n- Rows are keyed `video_id::instance_domain`, and rows without either are dropped.\n- Each call sends the last 500 shown as `exclude`.\n- A keyless body carries `getRandomLikes()` on every batch (line 133), so each batch may be personalised with a different random likes sample. The home page does the same.\n\n**What depends on it.** test_frontend_blocks (mapped at `config.json:75-81`) and the new test, which bundles `createFeedPager` and `fetchSimilarVideosPayload`.\n\n**Risk: none to the file.** Any future edit to it now affects two pages and two tests.\n</impact>\n<impact path=\"client/frontend/src/pages/videos/index.ts\" element=\"useSimilar mode (78, 212-214), loadVideos/loadMoreVideos/loadNextChunk/maybeFillViewport/maybeLoadOnScroll/setupInfiniteScroll (171-375)\">\n**What changes.** Nothing (R5, and the rejected alternative). `/videos.html?id=\u2026&host=\u2026` keeps working for bookmarks, and nothing in the app links to it any more.\n\n**Why it matters.** It is the source of the copied scroll code, so the two copies now drift independently (the deliberate duplication).\n\n**Doc impact.** `docs/project/issues/plan.md:91` lists \"the `?id=` mode of `pages/videos/index.ts`\" among this issue's files. That is no longer true under the operator's links-only decision.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/types/videos.ts\" element=\"SimilarSeed (64-68), VideosPayload (86-91)\">\n**What changes.** Nothing.\n\n**Why it matters.** `SimilarSeed` has no `mode` field. The new test reads `payload.seed?.mode` in plain JS in the runner, so this is not a type issue. If the page ever typed that read, it would need the field. The page itself does not read `seed`.\n\n**Risk: none.**\n</impact>\n<impact path=\"client/frontend/src/components/key-rejected.ts\" element=\"keyRejectedNotice(onForget) (line 11)\">\n**What changes.** Nothing. Its callback re-invokes `loadSimilarVideos`, which now resets state and builds a fresh pager.\n\n**Risk: low.** The retry must not leave `loading` stuck at true. If it did, the observer and scroll checks would stay dead after a successful retry.\n</impact>\n<impact path=\"client/frontend/dist/video-page.html\" element=\"built HTML and `dist/assets/video-*.js` / `video-*.css`\">\n**What changes.** Nothing by hand (R5). They go stale until `npm run build`, and still contain both links and the `limit:\"8\"` call (grep confirms at dist lines 28 and 109 and in the asset). A deploy needs a build followed by the rsync described in the archived plan 19-14.\n\n**Risk: low (operational).** Deploying without a build ships the old page.\n</impact>\n<impact path=\"tests/active/test_frontend_video_page.py\" element=\"RUNNER stubs (24-85) and the three taxonomy tests\">\n**What changes.** Nothing. It must keep passing as it is.\n\n**What the runner provides.**\n- `window` has `location`, the storages and `addEventListener() {}`, but no `innerHeight` or `scrollY`.\n- `document` has no `documentElement`, and there is no `IntersectionObserver`.\n- Elements have a no-op `insertAdjacentHTML`.\n- `fetch` answers `{}` for every path except `/api/video`.\n\n**Why it still passes.** The first batch is empty, so the page takes the \"No similar videos found.\" path and never reaches observer or listener code. The test waits only 5\u00d710 ms. The similars path is independent of the assertions, but an unhandled rejection or synchronous throw at import would fail it (non-zero exit, or a missing stdout line).\n\n**Reselection.** `config.json:148-152` maps it to all three changed frontend files, so it is reselected.\n\n**Risk: medium.** It is the only automated guard on the page module, and it guards only against crashes.\n</impact>\n<impact path=\"tests/active/test_frontend_upnext_pager.py\" element=\"new test module (R6)\">\n**What changes.** A new file following the retired file's harness (`tests/archive/upnext_random_draw/test_frontend_videos.py:30-89`):\n- `FRONTEND = parents[2]` (active depth; the archive uses `parents[3]`), `PAGE = \"48\"`, `MAX_BATCHES = 10`.\n- A runner without the two plain-fetch control runs (archive lines 47-50). It reports `seed.mode` of the first pager batch instead.\n- The `engine_client` fixture, the `linux` seed via `GET /api/v1/search/videos?q=linux&limit=1`, and a 300 s timeout.\n- The runner's `window` in the archive lacks `sessionStorage` (line 41). The plan says to add it, as `test_frontend_video_page.py` does.\n\n**Assertions.** Batches 1 and 2 are non-empty and disjoint. No batch repeats an earlier row. An empty batch exists at an index below the last. Calls count 1\u2026k up to the empty batch and stay flat after it. The archive's `assert all(\"error\" not in b \u2026)` is presumably kept.\n\n**Dependencies.**\n- **Client.** `client/backend/server.py`: the `FEED_PAGE_SIZE` cap (69, 457) and the exclude validation (524-535).\n- **Engine pool rule.** `get_upnext_candidates` in `engine/server/data/similarity_candidates.py:119-179` / `_upnext_rows` (182-197), which exclude after `_build_rows(top_k=300)`, plus `seed.mode = \"upnext\"` in `engine/server/api/handlers/similar.py:857-858`. The empty-pool branch (867+) answers without `mode`, but that affects only batches after the first.\n\n**Flake exposure.**\n1. Later batches drive the pool below `SIMILAR_VIDEO_TARGET_MIN_POOL` (48), so each runs the ANN fallback, up to 3 FAISS searches reaching nprobe 128 / k 20000. The Engine's 5 s deadline turns an overrun into a 500 (`DEPLOYMENT.md:260`). The Client's proxy timeout is 10 s (`server.py:77-79`). A 500 or 502 throws in `next()`, which sets `exhausted` and fails the no-error assertion. That is a timing-dependent failure.\n2. A higher-nprobe fallback can surface new high-scoring hits into the top 300. The pool is therefore not strictly fixed, which is the plan's \"slack\" (batches 8-9).\n3. The Engine's own limiter is `DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60` per 60 s (`engine/server/api/server_config.py:450-451`). The fixture relaxes only the Client limiter (`conftest.py:175`). The session Engine is shared with test_similar's many `/recommendations` calls when they run in one pytest process. I did not check how lanes split groups, so whether ~10 more requests can hit a 429 is unverified.\n\n**Existing coverage.** `tests/active/test_similar.py` already shows that the linux seed fills a 48-row page (the `\u2026fills_a_48_row_page\u2026[linux]` test in `tests/last_test_validation.json`), so batch 1 at 48 is non-empty.\n\n**Risk: medium-high (flakiness).** The file is new; it breaks nothing existing.\n</impact>\n<impact path=\"tests/archive/upnext_random_draw/test_frontend_videos.py\" element=\"retired pager test (whole file)\">\n**What changes.** Nothing. It stays skipped (`pytestmark` at line 28) and serves as the template. Its docstring still says \"issue 35 tracks a replacement\", which is historical. It could gain a pointer to the new file, but that is optional.\n\n**Risk: none.**\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"engine (105-145, session-scoped, RECOMMENDATIONS_DEBUG=1) and engine_client (148-150 \u2192 _engine_client 164-184, Client RateLimiter(100000, 60))\">\n**What changes.** Nothing.\n\n**Why it matters.** The new test uses `engine_client`, whose `.base` is the Client URL (line 180). The Client's limiter is relaxed there; the Engine's is not (see the new-test entry).\n\n**Risk: none to the file.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"FEED_PAGE_SIZE=48 / FEED_OVERFETCH_FACTOR=2 (69-70), _profile_filter (442-473), exclude validation (524-535), ENGINE_PROXY_TIMEOUT_SECONDS=10 (77-79), RATE_LIMIT_MAX_REQUESTS=90 per 60 s (62-63)\">\n**What changes.** Nothing (out of scope).\n\n**Correction to the plan.** The plan says \"the Client caps the page at 48 and over-fetches 96\". The code over-fetches (limit = 96) only for a keyed request whose profile has blocks or dislikes (line 471). Keyless requests, and the new test, send `limit=48` to the Engine.\n\n**Other facts.**\n- The 500-entry exclude cap is never reached within the test budget (at most 9 \u00d7 48 = 432) or in a real page view, since the pool is \u2264 300.\n- A browser scrolling to the pool's end makes about 7 `/recommendations` requests per page view, well under the production limiter's 90 per minute.\n\n**Risk: none to the file.** Mapped as a dependency of the new test.\n</impact>\n<impact path=\"engine/server/data/similarity_candidates.py\" element=\"get_upnext_candidates (119-179), _upnext_rows (182-197)\">\n**What changes.** Nothing.\n\n**Why it matters.**\n- It confirms the plan's budget reasoning: `_build_rows(..., policy.top_k)` (300) runs before the exclude filter (192-195), and \"an excluded row does not free its channel's slot\".\n- The fallback runs when `len(rows) < target_min_pool` (48) (line 151). Once a page view has shown enough rows, every later batch pays up to 3 live searches.\n\n**What depends on it.** The new test's empty-batch assertion. It is not mapped to the new test in the plan's config entry (see config.json).\n\n**Risk: none to the file.** A future change to refill from deeper hits fails the new test.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"_handle_similar limit cap (941-947: max 2 \u00d7 default_limit), mode stamp (1006, 857-858), empty-pool 200 branch (867+)\">\n**What changes.** Nothing.\n\n**Why it matters.**\n- `limit=48` is accepted.\n- The first non-empty batch carries `seed.mode == \"upnext\"`, which the new test asserts.\n- An empty batch comes back as 200 with no rows, which the pager turns into `exhausted`.\n\n**Risk: none.**\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups: new `test_frontend_upnext_pager.py` entry (after line 152)\">\n**What changes.** A new entry mapping to `client/frontend/src/data/videos.ts` and `client/backend/server.py`, per the plan. No stale `test_frontend_videos.py` entry exists (grep finds none), so none needs dropping.\n\n**Gap.** The test's empty-batch and no-repeat assertions depend on Engine behaviour: `engine/server/data/similarity_candidates.py` and `engine/server/api/handlers/similar.py`. Issue 35 line 26 itself recommends mapping those to the frontend tests. Without them, an Engine-only change will not reselect this test. I suggest adding both; this is a deviation from the plan's two-file list and needs the operator's OK.\n\n**Risk: low.**\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"groups / tests record\">\n**What changes.** It is regenerated by the validation run. It will gain a `test_frontend_upnext_pager.py` group and new digests for `test_frontend_video_page.py`. Not hand-edited.\n\n**Risk: none.**\n</impact>\n<impact path=\"docs/project/issues/35-upnext-tests-retired-by-random-draw.md\" element=\"coverage list item `test_frontend_videos` (line 17), Proposed solution (26), Comments (33)\">\n**What changes.**\n- A comment under `## Comments` saying the pager coverage is restored by `tests/active/test_frontend_upnext_pager.py` from build 12. Include what changed from the retired file: 48-row batches, no plain-fetch control, `MAX_BATCHES = 10`, and the empty batch reached because the Engine takes the top 300 before excluding.\n- Line 17 is marked covered. The list items are bullets, not checkboxes, so this has to be text such as \"(covered by \u2026)\".\n- Line 26's \"drop the `test_frontend_videos.py` entry until a replacement exists\" is already satisfied and could note that.\n- The other five items stay open, and the Status stays `needs-triage`.\n\n**Risk: none.**\n</impact>\n<impact path=\"docs/project/issues/12-similars-on-scroll.md\" element=\"whole issue\">\n**What changes, at harvest.** `Status: enhancement, complete` and a move to `docs/project/issues/archive/`, per the triage labels. Also add a delivery comment covering:\n- the operator's links-only decision (`/videos.html?id=` kept);\n- the 48-row batch revealed 8 at a time;\n- that the list ends when the seed's pool (\u2264 300) runs out;\n- that later-batch failures are console-only.\n\n**Risk: none.**\n</impact>\n</impacts>\n",
  "docs_checklist": "- [ ] `client/frontend/README.md` - Under \"What it does\", after line 13, add a bullet: the video page's similar section fetches one 48-row up-next batch through `createFeedPager`, reveals 8 cards at a time as scrolling nears the bottom, and fetches the next batch, excluding the rows already shown, when the revealed rows run out. Paging ends after an empty or failed batch, and a later failure is only logged. Line 9 (\"similar to one video\") can stay, since `/videos.html?id=` still works. Line 10's feed-paging bullet can say that the video page uses the same pager.\n- [ ] `DEPLOYMENT.md` - In \"Up-next logs and load\" (lines 253-260), note that one video page view now sends a sequence of up-next requests as the visitor scrolls: a 48-row batch each, carrying `exclude`, up to about 7 before a 300-row pool runs out. Once the unshown pool drops below 48 rows, each of these runs the ANN fallback. That multiplies the per-page-view `index_lock` load that the capacity paragraph describes.\n- [ ] `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` - Add a comment recording that `tests/active/test_frontend_upnext_pager.py` from build 12 replaces the `test_frontend_videos` item: 48-row batches, no plain-fetch control, 10-batch budget, empty batch reached because the Engine takes the top 300 before excluding. Mark line 17 as covered and leave the other five items and the status open.\n- [ ] `docs/project/issues/12-similars-on-scroll.md` - At harvest: set `Status: enhancement, complete`, add a delivery comment (links removed and the `/videos.html?id=` mode kept by operator decision, 48-row batch revealed 8 at a time, list ends at the pool's end with no marker, later-batch failure is console-only, no DOM windowing), then move the file to `docs/project/issues/archive/`.\n- [ ] `docs/project/issues/plan.md` - Line 42 (P2 row): strike 12 as delivered. Line 91 (row 4a): mark it delivered and correct the file list. The `?id=` mode of `pages/videos/index.ts` and the similar route limit were not changed. The files are `pages/video-page/index.ts`, `video-page.html`, `video.css` and the new test.\n- [ ] `docs/project/roadmap.md` - In the delivered list (lines 14-20), add an entry for issue `12`, similars on scroll: the video page pages up-next similars on scroll, 48 per request and revealed 8 at a time, and no longer links to the separate similar-videos page. Point it at `docs/project/plans/19-12-similars-on-scroll.md`, or its archived path after harvest.",
  "docs": [
    {
      "path": "client/frontend/README.md",
      "note": "Under \"What it does\", after line 13, add a bullet: the video page's similar section fetches one 48-row up-next batch through `createFeedPager`, reveals 8 cards at a time as scrolling nears the bottom, and fetches the next batch, excluding the rows already shown, when the revealed rows run out. Paging ends after an empty or failed batch, and a later failure is only logged. Line 9 (\"similar to one video\") can stay, since `/videos.html?id=` still works. Line 10's feed-paging bullet can say that the video page uses the same pager."
    },
    {
      "path": "DEPLOYMENT.md",
      "note": "In \"Up-next logs and load\" (lines 253-260), note that one video page view now sends a sequence of up-next requests as the visitor scrolls: a 48-row batch each, carrying `exclude`, up to about 7 before a 300-row pool runs out. Once the unshown pool drops below 48 rows, each of these runs the ANN fallback. That multiplies the per-page-view `index_lock` load that the capacity paragraph describes."
    },
    {
      "path": "docs/project/issues/35-upnext-tests-retired-by-random-draw.md",
      "note": "Add a comment recording that `tests/active/test_frontend_upnext_pager.py` from build 12 replaces the `test_frontend_videos` item: 48-row batches, no plain-fetch control, 10-batch budget, empty batch reached because the Engine takes the top 300 before excluding. Mark line 17 as covered and leave the other five items and the status open."
    },
    {
      "path": "docs/project/issues/12-similars-on-scroll.md",
      "note": "At harvest: set `Status: enhancement, complete`, add a delivery comment (links removed and the `/videos.html?id=` mode kept by operator decision, 48-row batch revealed 8 at a time, list ends at the pool's end with no marker, later-batch failure is console-only, no DOM windowing), then move the file to `docs/project/issues/archive/`."
    },
    {
      "path": "docs/project/issues/plan.md",
      "note": "Line 42 (P2 row): strike 12 as delivered. Line 91 (row 4a): mark it delivered and correct the file list. The `?id=` mode of `pages/videos/index.ts` and the similar route limit were not changed. The files are `pages/video-page/index.ts`, `video-page.html`, `video.css` and the new test."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "In the delivered list (lines 14-20), add an entry for issue `12`, similars on scroll: the video page pages up-next similars on scroll, 48 per request and revealed 8 at a time, and no longer links to the separate similar-videos page. Point it at `docs/project/plans/19-12-similars-on-scroll.md`, or its archived path after harvest."
    }
  ],
  "reassessments": 1,
  "draft": "# Draft \u2014 12 similars on scroll\n\n## Module map\n\n| File | Change |\n|---|---|\n| `client/frontend/src/pages/video-page/index.ts` | Change the import; drop the two link lookups and the top-level href block; add a sentinel lookup and module paging state above `void loadSimilarVideos()`; rewrite `loadSimilarVideos`; add `revealSimilarChunk`, `loadMoreSimilar`, `fillSimilarViewport`, `maybeRevealSimilarOnScroll`, `setupSimilarScroll`. |\n| `client/frontend/video-page.html` | Remove `#similar-link` (line 22) and `#similar-link-inline` (line 127); add `#similar-sentinel` after `#similar-videos`. |\n| `client/frontend/src/video.css` | Add `.similar-sentinel { height: 1px; }` after `.similar-grid .loading, .similar-grid .error` (616-620). |\n| `tests/active/test_frontend_upnext_pager.py` | New (R6). |\n| `.un/skills/devsecops/config.json` | New `test_frontend_upnext_pager.py` entry with four files (the operator approved the two Engine files). |\n| `docs/project/issues/35-upnext-tests-retired-by-random-draw.md` | Line 17 marked covered, plus a comment. |\n\nNothing else changes: `data/videos.ts`, `pages/videos/index.ts`, the server files, the render and stats helpers, and `dist/`.\n\n## What the build needs to test\n\n- **Pager contract (R3, R6), automated by the new test.** These run against the real Client and Engine at limit 48:\n  - the first batch has `seed.mode == \"upnext\"`;\n  - batches 1 and 2 are non-empty and disjoint;\n  - no batch repeats an earlier row;\n  - an empty batch arrives within 10 batches;\n  - requests stop after the empty batch.\n- **Page module still imports and runs in node (TDZ, empty-first-batch path), automated.** `test_frontend_video_page.py` runs unchanged. Its `{}` answer to `/recommendations` takes the \"No similar videos found.\" branch and must never reach `IntersectionObserver`, `document.documentElement` or `innerHeight`.\n- **Reveal, append, observer and fill-viewport (R2), plus later-batch paging in a real layout: manual browser check only.** No harness exists, and node has no layout. The maintainer checks:\n  - 8 cards on load;\n  - +8 cards per scroll to the bottom;\n  - a second `/recommendations` POST carrying `exclude` after 48 cards;\n  - requests stop at the pool's end;\n  - no link to `/videos.html`.\n\n## `pages/video-page/index.ts`\n\n### Imports (lines 6 and 20)\n\n```ts\nimport { createFeedPager, fetchSimilarVideosPayload, resolveApiBase, type FeedPager } from \"../../data/videos\";\n```\n\nLine 20 stays `import type { VideoRow } from \"../../types/videos\";`. No other type is named. `ExcludedVideo` is inferred from `createFeedPager`'s parameter, so the closure needs no annotation.\n\n### Element lookups\n\n- Delete line 43 (`similarLink`) and line 51 (`similarLinkInline`).\n- Add after `similarCards` (line 50):\n\n```ts\nconst similarSentinel = document.getElementById(\"similar-sentinel\");\n```\n\n### Module state\n\nThis goes directly after `similarStatsLoading` (line 73), which is above `void loadSimilarVideos()`, so the synchronous reset in `loadSimilarVideos` hits no TDZ error.\n\n```ts\n// The similar list shows this many cards at first and adds this many per scroll to the bottom.\nconst SIMILAR_CHUNK = 8;\n// Every row fetched so far; only the first similarRevealed of them are in the grid.\nlet similarRows: VideoRow[] = [];\nlet similarRevealed = 0;\nlet similarLoading = false;\n// One pager per load, so a retry starts with nothing shown and drops a replaced pager's result.\nlet similarPager: FeedPager | null = null;\nlet similarFetchingMore = false;\nlet similarScrollAttached = false;\n```\n\n- `similarPager` starts at `null`, not at a module-load `createFeedPager`. The no-seed path must never build one (R4).\n- Invariant: `0 <= similarRevealed <= similarRows.length`.\n- Invariant: the grid holds exactly `similarRows.slice(0, similarRevealed)` as cards, whenever `similarLoading` is false and the first batch was non-empty.\n\n### Top-level href block (lines 75-80)\n\nDeleted. The description-toggle block and `localLikesImported` stay where they are.\n\n### `loadSimilarVideos` (replaces lines 287-325)\n\n```ts\n/**\n * Load the first up-next batch through a fresh pager and reveal its first chunk.\n */\nasync function loadSimilarVideos() {\n  if (!similarSection || !similarCards) return;\n  if (!seedId) {\n    similarSection.setAttribute(\"hidden\", \"true\");\n    return;\n  }\n  similarRows = [];\n  similarRevealed = 0;\n  similarLoading = true;\n  similarCards.innerHTML = `<div class=\"loading\">Loading...</div>`;\n  const current = createFeedPager((exclude) =>\n    fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: \"48\", apiBase }, exclude)\n  );\n  similarPager = current;\n  try {\n    await localLikesImported;\n    const payload = await current.next();\n    if (current !== similarPager) return;\n    similarLoading = false;\n    const rows = payload.rows ?? [];\n    if (!rows.length) {\n      similarCards.innerHTML = `<div class=\"error\">No similar videos found.</div>`;\n      return;\n    }\n    similarRows = rows.slice();\n    const first = similarRows.slice(0, SIMILAR_CHUNK);\n    similarRevealed = first.length;\n    similarCards.innerHTML = first.map((row) => renderSimilarCard(row)).join(\"\");\n    queueSimilarStats(first);\n    setupSimilarScroll();\n    fillSimilarViewport();\n  } catch (error) {\n    if (current !== similarPager) return;\n    similarLoading = false;\n    if (error instanceof ProfileKeyRejectedError) {\n      similarCards.replaceChildren(keyRejectedNotice(() => void loadSimilarVideos()));\n      return;\n    }\n    const message = error instanceof Error ? error.message : \"Failed to load similar videos\";\n    similarCards.innerHTML = `<div class=\"error\">${escapeHtml(message)}</div>`;\n  }\n}\n```\n\n**Decisions:**\n- `limit: \"48\"` is literal. It equals `FEED_PAGE_SIZE`, and the Client caps it there anyway.\n- `await localLikesImported` still comes before the first request. The pager's fetch runs only inside `next()`, so creating the pager earlier sends nothing.\n- **Stale guard.** The `current !== similarPager` checks cost two lines and close the \"double run\" gap the impact names. A superseded call cannot overwrite the grid or clear `similarLoading` for the newer call. This is a small addition over the home page, which does not guard.\n- `similarLoading` is cleared on every path of the current call: empty, success, key-rejected and error. A retry therefore never leaves the scroll handlers dead.\n- The observer and listeners are set up only after a non-empty first batch. `test_frontend_video_page.py` never reaches them.\n\n### New functions (placed after `loadSimilarVideos`)\n\n```ts\n/**\n * Append the next chunk of fetched rows to the grid; with none left, ask the pager for more.\n */\nfunction revealSimilarChunk() {\n  if (similarLoading || !similarCards) return false;\n  const nextCount = Math.min(similarRows.length, similarRevealed + SIMILAR_CHUNK);\n  if (nextCount <= similarRevealed) {\n    void loadMoreSimilar();\n    return false;\n  }\n  const slice = similarRows.slice(similarRevealed, nextCount);\n  similarRevealed = nextCount;\n  // Appending leaves the cards already shown, and their fetched stats, in place.\n  similarCards.insertAdjacentHTML(\"beforeend\", slice.map((row) => renderSimilarCard(row)).join(\"\"));\n  queueSimilarStats(slice);\n  return true;\n}\n\n/**\n * Fetch the next up-next batch once the revealed rows reach the end of the ones fetched.\n */\nasync function loadMoreSimilar() {\n  const current = similarPager;\n  if (!current || similarLoading || similarFetchingMore || current.exhausted) return;\n  similarFetchingMore = true;\n  let appended = false;\n  try {\n    const payload = await current.next();\n    if (current !== similarPager || !payload.rows?.length) return;\n    similarRows.push(...payload.rows);\n    appended = true;\n  } catch (error) {\n    console.warn(\"[similar] loading more failed; paging stops for this page view\", error);\n  } finally {\n    similarFetchingMore = false;\n  }\n  // The sentinel may still be in view, so the observer will not fire again: reveal until it scrolls.\n  if (appended) {\n    revealSimilarChunk();\n    fillSimilarViewport();\n  }\n}\n\n/**\n * While the page is too short to scroll, keep revealing chunks until it can.\n */\nfunction fillSimilarViewport() {\n  if (similarLoading) return;\n  let safety = 0;\n  while (document.documentElement.scrollHeight <= window.innerHeight + 120 && safety < 50) {\n    if (!revealSimilarChunk()) break;\n    safety += 1;\n  }\n}\n\n/**\n * Reveal the next chunk once the page is scrolled near its bottom.\n */\nfunction maybeRevealSimilarOnScroll() {\n  if (similarLoading) return;\n  const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 240;\n  if (nearBottom) revealSimilarChunk();\n}\n\n/**\n * Watch the sentinel after the grid, with scroll and resize as a fallback; attached once per page view.\n */\nfunction setupSimilarScroll() {\n  if (similarScrollAttached) return;\n  similarScrollAttached = true;\n  if (similarSentinel) {\n    new IntersectionObserver(\n      (entries) => {\n        if (!entries.some((entry) => entry.isIntersecting)) return;\n        revealSimilarChunk();\n      },\n      { rootMargin: \"200px\" }\n    ).observe(similarSentinel);\n  }\n  window.addEventListener(\"scroll\", maybeRevealSimilarOnScroll, { passive: true });\n  window.addEventListener(\"resize\", () => {\n    maybeRevealSimilarOnScroll();\n    fillSimilarViewport();\n  });\n}\n```\n\n**Invariants and decisions:**\n\n- **`revealSimilarChunk`**\n  - It is a no-op returning `false` while `similarLoading`. The observer can fire right after `observe()`, and on a retry the reused listeners fire into a grid that shows `Loading...`.\n  - It returns `true` exactly when it appended cards.\n  - Stats are queued only for the appended slice (R2). `queueSimilarStats` already skips cached and in-flight keys.\n- **`loadMoreSimilar`**\n  - At most one fetch is in flight (`similarFetchingMore`).\n  - The pager owns the stop rule: `exhausted` after an empty or failed batch, after which the early return means no request is made (R3).\n  - A later-batch failure, `ProfileKeyRejectedError` included, is only warned about. The grid is never touched (R3, as the impact notes).\n- **`fillSimilarViewport` (deliberate difference from `maybeFillViewport`).** The loop does not also require `similarRevealed < similarRows.length`. It stops as soon as a reveal changes nothing, and that final reveal is the one that calls `loadMoreSimilar`.\n  - Why: on a very tall screen where all 48 rows fit, the page still asks for the next batch. On the home page the fill loop would stop there, and the sentinel observer would not fire again.\n  - It stays bounded: the safety counter is 50, `loadMoreSimilar` is guarded, and the pager exhausts within ~7 batches.\n  - R2's rule (\"while short and unrevealed rows remain, keep revealing\") still holds. This only adds R3's \"a reveal that finds none left asks the pager\".\n- **`setupSimilarScroll`**\n  - The observer and listeners are created once and reused across retries. They read module state, so no disconnect is needed.\n  - If `#similar-sentinel` is missing, scroll and resize still work.\n\n### Unchanged\n\n`renderSimilarCard`, `queueSimilarStats` and the stats fetchers, `applySimilarStatsToDom`, `videoPageUrl`, and all metadata, reaction, block and description code.\n\n## `video-page.html`\n\nThe nav loses line 22:\n\n```html\n        <nav class=\"header-nav\">\n          <a class=\"nav-link\" href=\"/\">Home</a>\n          <a class=\"nav-link\" href=\"/likes.html\">Likes</a>\n          <a class=\"nav-link\" href=\"/search.html\">Search</a>\n          <a class=\"nav-link\" href=\"/about.html\">About</a>\n        </nav>\n```\n\nThe similar section:\n\n```html\n        <section id=\"similar-section\" class=\"similar-card\">\n          <div class=\"section-header\">\n            <h3>Similar videos</h3>\n          </div>\n          <div id=\"similar-videos\" class=\"similar-grid\">\n            <div class=\"loading\">Loading...</div>\n          </div>\n          <div id=\"similar-sentinel\" class=\"similar-sentinel\" aria-hidden=\"true\"></div>\n        </section>\n```\n\n## `video.css`\n\nAdded after line 620:\n\n```css\n.similar-sentinel {\n  height: 1px;\n}\n```\n\n## `tests/active/test_frontend_upnext_pager.py`\n\n```python\n\"\"\"The frontend's feed pager over up-next similars, run in node against the real Client and Engine at the video page's 48-row batch: its batches never repeat a row, and it stops asking once a batch adds nothing.\n\n- For the linux seed, the pager's first batch is an up-next page (`seed.mode == \"upnext\"`), its second batch holds rows and none of the first batch's, and no later batch repeats a row of an earlier one. Each batch is a random draw (build 09), so no two pages are compared for equality.\n- The pager is driven for MAX_BATCHES calls and reaches an empty batch before the last: the Engine takes a seed's top 300 rows before it drops excluded ones, so at 48 a batch the pool runs out in about 7. No call after the empty batch makes a request, counted on the fetch function the pager is given (a pass-through to `fetchSimilarVideosPayload`).\n\nReplaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). `window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner supplies minimal in-memory ones, as `test_frontend_video_page.py` does.\n\"\"\"\nfrom __future__ import annotations\n\nimport json\nimport os\nimport subprocess\nfrom pathlib import Path\n\nFRONTEND = Path(__file__).resolve().parents[2] / \"client\" / \"frontend\"\nESBUILD = FRONTEND / \"node_modules\" / \".bin\" / \"esbuild\"\nPAGE = \"48\"\nMAX_BATCHES = 10\n\nRUNNER = \"\"\"\nconst memory = () => { const s = new Map(); return {\n  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),\n  removeItem: (k) => s.delete(k) }; };\nglobalThis.localStorage = memory();\nglobalThis.sessionStorage = memory();\nglobalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage,\n  sessionStorage: globalThis.sessionStorage };\nconst m = await import(process.env.BUNDLE);\nconst say = (obj) => process.stdout.write(JSON.stringify(obj) + \"\\\\n\");\nconst keys = (rows) => (rows ?? []).map((r) => [r.video_id, r.instance_domain]);\nconst query = { id: process.env.SEED_UUID, host: process.env.SEED_HOST, limit: process.env.PAGE,\n  apiBase: process.env.BASE };\nlet calls = 0;\ntry {\n  const pager = m.createFeedPager((exclude) => { calls += 1; return m.fetchSimilarVideosPayload(query, exclude); });\n  for (let i = 0; i < Number(process.env.MAX_BATCHES); i += 1) {\n    const payload = await pager.next();\n    say({ rows: keys(payload.rows), mode: payload.seed?.mode ?? null, calls });\n  }\n} catch (e) { say({ error: String(e), calls }); }\nprocess.exit(0);\n\"\"\"\n\n\ndef _run(tmp_path: Path, base: str, seed: dict) -> list[dict]:\n    entry = tmp_path / \"entry.ts\"\n    entry.write_text(f'export {{ createFeedPager, fetchSimilarVideosPayload }} from \"{FRONTEND}/src/data/videos.ts\";\\n')\n    subprocess.run(\n        [str(ESBUILD), str(entry), \"--bundle\", \"--format=esm\", \"--platform=node\",\n         f\"--outfile={tmp_path / 'bundle.mjs'}\",\n         f\"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(base)}\",\n         \"--define:import.meta.env.DEV=false\"],\n        check=True, capture_output=True,\n    )\n    runner = tmp_path / \"runner.mjs\"\n    runner.write_text(RUNNER)\n    proc = subprocess.run(\n        [\"node\", str(runner)], capture_output=True, text=True, timeout=300,\n        env={\"BASE\": base, \"BUNDLE\": str(tmp_path / \"bundle.mjs\"), \"PATH\": os.environ.get(\"PATH\", \"\"),\n             \"SEED_UUID\": seed[\"video_uuid\"], \"SEED_HOST\": seed[\"instance_domain\"],\n             \"PAGE\": PAGE, \"MAX_BATCHES\": str(MAX_BATCHES)},\n    )\n    assert proc.returncode == 0, proc.stderr\n    return [json.loads(line) for line in proc.stdout.splitlines()]\n\n\ndef _seed(client) -> dict:\n    # A seed whose up-next pool fills a 48-row page (test_similar's fills_a_48_row_page case).\n    status, body = client.request(\"GET\", \"/api/v1/search/videos?q=linux&limit=1\")\n    assert status == 200 and body[\"rows\"], body\n    return body[\"rows\"][0]\n\n\ndef test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(\n        engine_client, tmp_path):\n    batches = _run(tmp_path, engine_client.base, _seed(engine_client))\n    assert all(\"error\" not in b for b in batches), batches\n    assert len(batches) == MAX_BATCHES, batches\n    assert batches[0][\"mode\"] == \"upnext\", batches[0]  # control: the seed resolves to up-next\n\n    first, second = (set(map(tuple, b[\"rows\"])) for b in batches[:2])\n    assert first, \"the first batch is empty\"\n    assert second, \"the second batch is empty\"\n    assert not first & second, first & second\n    seen: set[tuple] = set()\n    for batch in batches:  # and no later batch repeats a row of any earlier one\n        rows = set(map(tuple, batch[\"rows\"]))\n        assert not rows & seen, (rows & seen, [len(b[\"rows\"]) for b in batches])\n        seen |= rows\n\n    empty = next((i for i, b in enumerate(batches) if not b[\"rows\"]), None)\n    # the seed's pool ends within the budget, with at least one call after it to count\n    assert empty is not None and empty + 1 < len(batches), [len(b[\"rows\"]) for b in batches]\n    # control: up to the empty batch, every batch was one request through the given fetch\n    assert [b[\"calls\"] for b in batches[:empty + 1]] == list(range(1, empty + 2)), batches\n    assert all(b[\"calls\"] == batches[empty][\"calls\"] for b in batches[empty + 1:]), batches\n```\n\n**Changes from the retired file:**\n- `parents[2]`, `PAGE = \"48\"`, `MAX_BATCHES = 10`.\n- `window.sessionStorage` is added.\n- The plain-fetch controls are gone. `mode` comes from the first pager batch; the pager spreads `payload`, so `seed` survives.\n- The error line carries `calls`.\n- `len(batches) == MAX_BATCHES` is checked, so a crash partway through fails.\n- The failure messages print batch sizes, so an Engine pool-rule change fails with a readable message rather than passing vacuously.\n\n**Known flake exposure (not handled in the draft):**\n- An Engine 5 s deadline overrun in a fallback batch.\n- The Engine's 60/min limiter shared with `test_similar`.\n\nBoth show up as an `error` line and fail the first assertion. If they bite in validation, the fix is in the harness (lane or grouping), not a weaker assertion.\n\n## `.un/skills/devsecops/config.json`\n\nInserted after the `test_frontend_video_page.py` entry (after line 152):\n\n```json\n    \"test_frontend_upnext_pager.py\": [\n      \"client/frontend/src/data/videos.ts\",\n      \"client/backend/server.py\",\n      \"engine/server/data/similarity_candidates.py\",\n      \"engine/server/api/handlers/similar.py\"\n    ],\n```\n\nThe operator approved the two Engine files at this step: the empty-batch and no-repeat assertions depend on them (issue 35 line 26).\n\n## Issue 35\n\nLine 17 becomes:\n\n```markdown\n- **test_frontend_videos** (the whole file): the frontend pager never repeats a row and stops asking after an empty batch. Covered by `tests/active/test_frontend_upnext_pager.py` (build 12).\n```\n\nLine 26 gets an appended sentence: \"The `test_frontend_videos.py` entry is gone; its replacement is mapped as `test_frontend_upnext_pager.py`.\"\n\nComment under `## Comments`:\n\n```markdown\n- Build 12 (similars on scroll): `tests/active/test_frontend_upnext_pager.py` replaces `test_frontend_videos`. It drives `createFeedPager` over `fetchSimilarVideosPayload` for the linux seed at 48 rows per batch, with no plain-fetch control (each page is a random draw), a 10-batch budget, and the first batch's `seed.mode` checked as `upnext`. The empty batch is reached because the Engine takes a seed's top 300 rows before dropping excluded ones. It is mapped to `data/videos.ts`, `server.py`, `similarity_candidates.py` and `handlers/similar.py`. The other five items stay open.\n```\n\nStatus stays `enhancement, needs-triage`.\n\n## Check against plan and requirements (pass 1, converged)\n\n| Item | Where met |\n|---|---|\n| R1 limit 48 via `fetchSimilarVideosPayload` with id/host/apiBase | pager closure in `loadSimilarVideos` |\n| R2 memory + revealed prefix, first 8, +8 appended, stats per slice | `similarRows`/`similarRevealed`, `revealSimilarChunk` |\n| R2 sentinel observer 200px, passive scroll, resize, \u2212240 / +120 thresholds, safety 50 | `setupSimilarScroll`, `maybeRevealSimilarOnScroll`, `fillSimilarViewport` |\n| R3 one pager per load, exclude via pager, load-more guards, reveal + fill after append, console.warn only | `loadSimilarVideos`, `loadMoreSimilar` |\n| R4 likes import first, empty / error / key-rejected / no-seed paths, card markup | `loadSimilarVideos`; helpers untouched |\n| R5 both links and their code removed, heading kept, `useSimilar` untouched, no dist edit | HTML, deleted lines 43/51/75-80/296-301 |\n| R6 test, mapping, issue 35 | above |\n| Impact: TDZ ordering | state declared above line 98 |\n| Impact: `loading` cleared on all paths, stale pager dropped | `loadSimilarVideos`, `loadMoreSimilar` |\n| Impact: no observer or listener in the node stub's empty path | set up only after a non-empty first batch |\n\n**Named deviations from the plan:**\n1. `fillSimilarViewport` also asks for the next batch once all fetched rows fit the viewport.\n2. `loadSimilarVideos` guards against a superseded call.\n3. The config entry has four files, not two (operator-approved).\n\n**Simplifications, carried from the plan:**\n- No end-of-list marker.\n- Later-batch errors go to the console only.\n- No DOM windowing. This caps out at the pool size of about 300 cards; the upgrade path is windowing.\n- The scroll code is copied from the home page rather than shared. The upgrade path is extracting it when a third paged surface appears.",
  "coordination": "Phase 1: its checkpoint needs the live local Client and Engine that the `engine_client` fixture starts (the engine pixi env and its local data). It makes about 8 round trips, some of which run the ANN fallback, under a 300 s timeout. It shares the Engine's 60/min limiter with `test_similar`. No credential is needed. Phases 2-3, manual step: node has no layout, so the maintainer checks in a real browser what no checkpoint can: fill-viewport on a very tall screen, the scroll and resize fallbacks at the -240/+120 thresholds, and requests stopping at the pool's end in a real layout.",
  "tests": {
    "tests/tmp/test_12_similars_on_scroll_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase1.py:124, :125, :129: batch 2 is non-empty, batches 1 and 2 share no (video_id, instance_domain) row, and no batch repeats a row from any earlier batch, across all 10 batches.",
          "expected": "Observed batch sizes 48 x 6, 12, 0, 0, 0 with no overlaps, so all three hold.",
          "wrong_implementation": "A pager that stops sending `exclude` and does not dedup gets repeated rows from the Engine's random draw, so :125/:129 read a non-empty intersection. A pager that excludes only the previous batch fails :129 on a later batch."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase1.py:134: an empty batch arrives before the last of the 10 calls. Controls: :119 (exactly 10 batches reported) and :118 (no error line).",
          "expected": "The first empty batch is at index 7.",
          "wrong_implementation": "A feed that never runs dry, or runs dry only at index 9: `empty` is None or 9, and the assertion fails."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase1.py:136 and :142: every batch before the last non-empty one has exactly 48 rows and the last non-empty one has 1..48; a second run of the same seed at limit \"20\" for 2 batches has sizes [20, 20].",
          "expected": "sizes[:6] == [48]*6 and sizes[6] == 12, and the limit-20 run reads [20, 20] (observed this turn).",
          "wrong_implementation": "A pager that merges two fetches (96 rows) or trims a full page fails :136. A query that drops `limit` or hardcodes 48 comes back at the 48 default, so :142 reads [48, 48] and fails."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase1.py:139: every `next()` after the empty batch leaves the counted fetch calls unchanged. Control :138: calls go 1..8 up to and including the empty batch.",
          "expected": "calls [1..8, 8, 8].",
          "wrong_implementation": "A pager that never sets `exhausted` keeps calling the fetch, so calls read 9, 10 and the assertion fails."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase1.py:146, :162: the durable tests/active/test_frontend_upnext_pager.py exists. With its `_run` swapped for canned batches, its test raises AssertionError on each of six wrong-pager sets: repeats a row of an earlier batch, never runs dry, keeps asking after the empty batch, mode other than upnext, empty second batch, crash partway. Controls: :148 (it defines a test) and :151 (the observed batch shape passes).",
          "expected": "After the phase lands, :162 reads [] (observed against the plan's drafted file this turn). Before the phase, :146 fails because the file is absent (observed).",
          "wrong_implementation": "A durable file that is empty, has a `pass` body, or drops any of the pager assertions (no-repeat, empty-within-budget, no-calls-after, upnext mode, crash guard). The labels of the sets it does not fail on appear in :162's list. Observed: a `pass` stub fails here."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase1.py:173, :174: `claimed` discovers a group `test_frontend_upnext_pager.py`, and its files include all four SUBJECTS. Controls: :169 (an existing group carries its mapping) and :171 (all four subjects exist).",
          "expected": "After the phase, `covered` contains videos.ts, server.py, similarity_candidates.py and handlers/similar.py. Before it, covered is None.",
          "wrong_implementation": "A phase that adds no durable file fails :173. A config.json entry missing any of the four files fails :174, which lists the missing file."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Across 48-row batches from the linux seed, no row repeats, an empty batch arrives within 10 batches, and no request is made after it."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_12_similars_on_scroll_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_12_similars_on_scroll_phase1.py  2 failed, 1 passed                     0.0s\n  ----------------------------------------------\n  total                                           2 failed, 1 passed                     7.9s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_12_similars_on_scroll_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase2.py:124 \u2014 exactly one request reached `/recommendations`. Then :125 \u2014 that request is a POST and its `limit` query parameter is \"48\".",
          "expected": "One request, `{'method': 'POST', 'path': '/recommendations', 'query': {..., 'limit': '48'}, ...}`. The run confirmed the shape: a single POST that carries `limit` in the query string. Today its value is '8'.",
          "wrong_implementation": "Case 1: the page keeps today's `limit: \"8\"` at index.ts:307. The run read `'limit': '8'`, so :125 fails ('8' == '48'). Case 2: the first batch is split into an 8-row request plus a follow-up at mount. That gives two `/recommendations` entries, so :124 fails."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase2.py:129 \u2014 `#similar-videos` holds exactly 8 `similar-card-item` anchors. Then :131 \u2014 their `data-video-key` ids are v0..v7, in order.",
          "expected": "8 anchors with keys `videos.example::v0` \u2026 `videos.example::v7`.",
          "wrong_implementation": "Case 1: the page renders every row it gets back (index.ts:315, `rows.map(renderSimilarCard)` with no cap). Given the 48-row answer, the probe counted 48 anchors, ids v0..v47, so :129 fails. Case 2: the page caps at 8 but takes the wrong slice (last 8, or skips already-seen rows). The count is 8 but the ids are not v0..v7, so :131 fails."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "The first `/recommendations` request the page makes carries limit 48."
        },
        {
          "id": "C2",
          "text": "From a 48-row answer, `#similar-videos` holds exactly 8 cards."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_12_similars_on_scroll_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_12_similars_on_scroll_phase2.py  1 failed                               0.0s\n  ----------------------------------------------\n  total                                           1 failed                               0.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_12_similars_on_scroll_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase3.py:152, :154, :155 \u2014 the first intersection makes exactly one insertAdjacentHTML call on #similar-videos, at \"beforeend\", holding the similar-card-item anchors for rows v8-v15 in order",
          "expected": "insert delta 1, position \"beforeend\", keys [\"v8\", \u2026, \"v15\"]",
          "wrong_implementation": "A page that re-renders the grid, prepends, or inserts the wrong slice: the delta reads 0 or more than 1, the position reads \"afterbegin\", or the keys are not v8-v15."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase3.py:162 \u2014 for each intersection k = 2..5, exactly one insert is made on that step, and the grid then shows v0..v(8(k+1)-1) in order",
          "expected": "For k=2,3,4,5: insert delta 1, and the grid keys are v0-v23, v0-v31, v0-v39, v0-v47",
          "wrong_implementation": "A page that shows all 32 remaining rows on the second intersection and nothing after it: at k=2 the grid reads v0-v47 where v0-v23 is expected. A page that appends a wrong-sized chunk or skips a step fails the key list or the insert delta at that k."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase3.py:156, :157, :166, :167 \u2014 innerHTML writes do not change through the first and fifth intersections; the grid still begins with the first 8 cards' markup; after five intersections it shows v0-v47 in order",
          "expected": "writes unchanged; first[\"similar\"] starts with the loaded markup; keys v0..v47",
          "wrong_implementation": "A page that rebuilds the grid through innerHTML with the accumulated rows: the writes count goes up, and if the earlier cards' markup changes, the startswith check fails."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase3.py:168 \u2014 after five intersections there has still been only one /recommendations request",
          "expected": "1",
          "wrong_implementation": "A page that prefetches the next batch on an intersection that still has unrevealed rows reads 2 or more."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase3.py:171, :173 \u2014 the sixth intersection sends a second /recommendations request, and it is a POST",
          "expected": "request count 2; method \"POST\"",
          "wrong_implementation": "A page that stops once the fetched rows run out reads a count of 1. A page that refetches with GET reads \"GET\"."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_12_similars_on_scroll_phase3.py:175 \u2014 the second request's body.exclude has exactly 48 entries, and as a set they equal the {id, host} pairs v0-v47 / videos.example",
          "expected": "48 entries: {id: \"v0\"..\"v47\", host: \"videos.example\"}",
          "wrong_implementation": "A refetch with no exclude, with only the last chunk, with duplicates, or with video_id/instance_domain keys: the length or the pair set differs."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A sentinel intersection appends the next 8 cards, and the cards already shown stay in place."
        },
        {
          "id": "C2",
          "text": "An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_12_similars_on_scroll_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_12_similars_on_scroll_phase3.py  1 failed                               0.0s\n  ----------------------------------------------\n  total                                           1 failed                               0.9s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_12_similars_on_scroll_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. EXEMPT C1: stub question, \"previous behaviour left unchanged\" (rules/shape.md <ladder> / stub question) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:86\n   def test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(\n   This test passes on the unchanged client/frontend/src/data/videos.ts. The builder's reason\n   concedes exactly that. The exemption holds up on the shape: the test does not pass on a stub.\n   - A pager that returns nothing fails :94.\n   - A pager that sends no exclude list, so the Engine's random draw repeats rows, fails :100,\n     or fails :105 if it drops the repeats itself, because no empty batch arrives.\n   - A pager that never sets `exhausted` fails :108, where the call count keeps rising after\n     the empty batch.\n   The line numbers in the exemption are out of date. It cites :91, :92, :96, :101, :104 for the\n   C1 lines and :85-87, :90, :103 for the controls. In the file the C1 tags are at\n   :95, :96, :100, :105, :108 and the controls at :89-:91 and :107. The gate record should\n   point at the current lines.\n\nPREDICTED FAILURE\ntest_the_durable_pager_test_is_a_group_fingerprinted_over_the_files_it_runs_through fails at\nline 121 on `assert covered is not None`. tests/active/test_frontend_upnext_pager.py does not\nexist, so `harness.groups()` never finds it and `claims.get(\"test_frontend_upnext_pager.py\")`\nreturns None. The config.json `test_groups` map has no entry for it either, so :122 would fail\nnext. The first test (:86) is predicted green by design, per the C1 exemption.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py (NEW). It does not exist\n   yet, so it was not read. The stub question for the second test was answered from its assertion\n   form and from `claimed()` in .un/skills/devsecops/scripts/validate_tests.py:616.\n2. `fixtures_path` was not supplied. The `engine` and `engine_client` fixtures come from\n   tests/active/conftest.py (:106, :149), which was read up to the `_engine_client` helper\n   (:164-184). The rest of that file (:1-99, :190-233) was not read.\n3. The claim at :80 and in the docstring that the linux seed's pool runs out at about batch 8\n   depends on the Engine's data. It was not checked, because no Engine source was in\n   `code_under_test`.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 8 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"48-row batches from the linux seed\" | none (setup only: `PAGE` at :27/:73, `q=linux` at :81) | nothing asserts any batch's length. A query that drops `limit` still passes | EXEMPT |\n| C1b | must_prove | \"no row repeats\" across batches | :96, :100 | a pager that neither sends `exclude` nor drops a row it has already seen | EXEMPT |\n| C1c | must_prove | \"an empty batch arrives within 10 batches\" | :105 (control :90) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |\n| C1d | must_prove | \"no request is made after it\" | :108 (control :107) | a pager that keeps fetching once `exhausted` should be set | EXEMPT |\n| D1 | docstring | runs \"at the video page's 48-row batch\" | none | nothing: no assertion bounds `len(rows)` at 48 | UNCARRIED |\n| D2 | docstring | \"first batch is an up-next page (`seed.mode == \"upnext\"`)\" | :91 | a seed that resolves to a random or other mode | CARRIED |\n| D3 | docstring | \"second batch holds rows and none of the first batch's\" | :95, :96 | an empty second page, and a second page that repeats the first | CARRIED |\n| D4 | docstring | \"no later batch repeats a row of an earlier one\" | :100 | a pager that only excludes the batch just before, not every earlier one | CARRIED |\n| D5 | docstring | \"driven for MAX_BATCHES calls and reaches an empty batch before the last\" | :90, :105 | a crashed run that stops early, and an empty batch only at index 9 or never | CARRIED |\n| D6 | docstring | \"No call after the empty batch makes a request, counted on the fetch function\" | :108 | a `next()` that calls `fetchBatch` after the feed is exhausted | CARRIED |\n| D7 | docstring | \"`test_frontend_upnext_pager.py` is a test group\" | :121 | a durable file missing from `tests/active` | CARRIED |\n| D8 | docstring | \"the durable test itself\": the pager test, made durable | none | nothing: :121 accepts any file with that name, including one that asserts nothing about the pager | UNCARRIED |\n| D9 | docstring | claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`, so it is reselected when any of them changes\" | :122 (control :119) | a `test_groups` entry that leaves out any of the four | CARRIED |\n| N1 | name | \"the pager's 48-row batches\" | none | nothing: batch size is never asserted | UNCARRIED |\n| N2 | name | \"never repeat a row\" | :100 | a pager that lets an Engine repeat through | CARRIED |\n| N3 | name | \"it stops asking after an empty batch\" | :108 | a pager that still fetches after an empty batch | CARRIED |\n| N4 | name | \"the durable pager test is a group\" | :121 | the group is absent | CARRIED |\n| N5a | name | \"fingerprinted over the files it runs through\": the four named subjects | :122 | a mapping missing one of the four | CARRIED |\n| N5b | name | \"the files it runs through\": the rest of the path it exercises | none | nothing: `videos.ts` imports `./cache`, `./local-likes`, `./api-base` and `./profile`, and `fetchSimilarVideosPayload` calls `getRandomLikes`/`profileHeaders` on every request. None of them is in `SUBJECTS` (:30) | UNCARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:1, :86\n   D1 and N1 are UNCARRIED. The docstring and the name both say \"48-row batches\", but the test only passes `limit=48` (:43, :73) and never asserts a batch's size. A client that ignored `limit` would pass.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:5, :121\n   D8 is UNCARRIED. The docstring says the phase delivers \"the durable test itself\". `assert covered is not None` shows only that a file of that name is a group. It does not show that the file carries the pager assertions.\n3. name-as-sentence / whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:111\n   N5b is UNCARRIED. The name claims \"the files it runs through\", but :122 checks only the four files in `SUBJECTS` (:30). Other files on the exercised path (`data/profile.ts`, `data/local-likes.ts`, `data/api-base.ts`, `data/cache.ts`) are not checked. Either narrow the name or widen `SUBJECTS`.\n4. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:89\n   Only the success path runs. `createFeedPager` also ends the feed when a batch fails: it sets `exhausted` and rethrows (videos.ts:52-54). No test checks that a fetch error stops later requests. :89 treats any error as a failed test.\n5. bounds (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:81\n   Only one seed and one page size are tested. Edges are untested: a seed whose pool is smaller than one batch, which would come back empty on the first or second batch, and a page size at or past the exclude cap `MAX_FEED_EXCLUDE = 500`.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve. I could not check that the durable copy matches this test, so D8 was judged from this file alone.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. EXEMPT C1: stub question, \"previous behaviour left unchanged\" (rules/shape.md <ladder> / stub question) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:86\n   def test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(\n   This test passes on the unchanged client/frontend/src/data/videos.ts. The builder's reason\n   concedes exactly that. The exemption holds up on the shape: the test does not pass on a stub.\n   - A pager that returns nothing fails :94.\n   - A pager that sends no exclude list, so the Engine's random draw repeats rows, fails :100,\n     or fails :105 if it drops the repeats itself, because no empty batch arrives.\n   - A pager that never sets `exhausted` fails :108, where the call count keeps rising after\n     the empty batch.\n   The line numbers in the exemption are out of date. It cites :91, :92, :96, :101, :104 for the\n   C1 lines and :85-87, :90, :103 for the controls. In the file the C1 tags are at\n   :95, :96, :100, :105, :108 and the controls at :89-:91 and :107. The gate record should\n   point at the current lines.\n\nPREDICTED FAILURE\ntest_the_durable_pager_test_is_a_group_fingerprinted_over_the_files_it_runs_through fails at\nline 121 on `assert covered is not None`. tests/active/test_frontend_upnext_pager.py does not\nexist, so `harness.groups()` never finds it and `claims.get(\"test_frontend_upnext_pager.py\")`\nreturns None. The config.json `test_groups` map has no entry for it either, so :122 would fail\nnext. The first test (:86) is predicted green by design, per the C1 exemption.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py (NEW). It does not exist\n   yet, so it was not read. The stub question for the second test was answered from its assertion\n   form and from `claimed()` in .un/skills/devsecops/scripts/validate_tests.py:616.\n2. `fixtures_path` was not supplied. The `engine` and `engine_client` fixtures come from\n   tests/active/conftest.py (:106, :149), which was read up to the `_engine_client` helper\n   (:164-184). The rest of that file (:1-99, :190-233) was not read.\n3. The claim at :80 and in the docstring that the linux seed's pool runs out at about batch 8\n   depends on the Engine's data. It was not checked, because no Engine source was in\n   `code_under_test`.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 8 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"48-row batches from the linux seed\" | none (setup only: `PAGE` at :27/:73, `q=linux` at :81) | nothing asserts any batch's length. A query that drops `limit` still passes | EXEMPT |\n| C1b | must_prove | \"no row repeats\" across batches | :96, :100 | a pager that neither sends `exclude` nor drops a row it has already seen | EXEMPT |\n| C1c | must_prove | \"an empty batch arrives within 10 batches\" | :105 (control :90) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |\n| C1d | must_prove | \"no request is made after it\" | :108 (control :107) | a pager that keeps fetching once `exhausted` should be set | EXEMPT |\n| D1 | docstring | runs \"at the video page's 48-row batch\" | none | nothing: no assertion bounds `len(rows)` at 48 | UNCARRIED |\n| D2 | docstring | \"first batch is an up-next page (`seed.mode == \"upnext\"`)\" | :91 | a seed that resolves to a random or other mode | CARRIED |\n| D3 | docstring | \"second batch holds rows and none of the first batch's\" | :95, :96 | an empty second page, and a second page that repeats the first | CARRIED |\n| D4 | docstring | \"no later batch repeats a row of an earlier one\" | :100 | a pager that only excludes the batch just before, not every earlier one | CARRIED |\n| D5 | docstring | \"driven for MAX_BATCHES calls and reaches an empty batch before the last\" | :90, :105 | a crashed run that stops early, and an empty batch only at index 9 or never | CARRIED |\n| D6 | docstring | \"No call after the empty batch makes a request, counted on the fetch function\" | :108 | a `next()` that calls `fetchBatch` after the feed is exhausted | CARRIED |\n| D7 | docstring | \"`test_frontend_upnext_pager.py` is a test group\" | :121 | a durable file missing from `tests/active` | CARRIED |\n| D8 | docstring | \"the durable test itself\": the pager test, made durable | none | nothing: :121 accepts any file with that name, including one that asserts nothing about the pager | UNCARRIED |\n| D9 | docstring | claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`, so it is reselected when any of them changes\" | :122 (control :119) | a `test_groups` entry that leaves out any of the four | CARRIED |\n| N1 | name | \"the pager's 48-row batches\" | none | nothing: batch size is never asserted | UNCARRIED |\n| N2 | name | \"never repeat a row\" | :100 | a pager that lets an Engine repeat through | CARRIED |\n| N3 | name | \"it stops asking after an empty batch\" | :108 | a pager that still fetches after an empty batch | CARRIED |\n| N4 | name | \"the durable pager test is a group\" | :121 | the group is absent | CARRIED |\n| N5a | name | \"fingerprinted over the files it runs through\": the four named subjects | :122 | a mapping missing one of the four | CARRIED |\n| N5b | name | \"the files it runs through\": the rest of the path it exercises | none | nothing: `videos.ts` imports `./cache`, `./local-likes`, `./api-base` and `./profile`, and `fetchSimilarVideosPayload` calls `getRandomLikes`/`profileHeaders` on every request. None of them is in `SUBJECTS` (:30) | UNCARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:1, :86\n   D1 and N1 are UNCARRIED. The docstring and the name both say \"48-row batches\", but the test only passes `limit=48` (:43, :73) and never asserts a batch's size. A client that ignored `limit` would pass.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:5, :121\n   D8 is UNCARRIED. The docstring says the phase delivers \"the durable test itself\". `assert covered is not None` shows only that a file of that name is a group. It does not show that the file carries the pager assertions.\n3. name-as-sentence / whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:111\n   N5b is UNCARRIED. The name claims \"the files it runs through\", but :122 checks only the four files in `SUBJECTS` (:30). Other files on the exercised path (`data/profile.ts`, `data/local-likes.ts`, `data/api-base.ts`, `data/cache.ts`) are not checked. Either narrow the name or widen `SUBJECTS`.\n4. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:89\n   Only the success path runs. `createFeedPager` also ends the feed when a batch fails: it sets `exhausted` and rethrows (videos.ts:52-54). No test checks that a fetch error stops later requests. :89 treats any error as a failed test.\n5. bounds (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:81\n   Only one seed and one page size are tested. Edges are untested: a seed whose pool is smaller than one batch, which would come back empty on the first or second batch, and a page size at or past the exclude cap `MAX_FEED_EXCLUDE = 500`.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve. I could not check that the durable copy matches this test, so D8 was judged from this file alone.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"48-row batches from the linux seed\"",
            "assertion": "none (setup only: `PAGE` at :27/:73, `q=linux` at :81)",
            "excludes": "nothing asserts any batch's length. A query that drops `limit` still passes",
            "status": "EXEMPT"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"no row repeats\" across batches",
            "assertion": ":96, :100",
            "excludes": "a pager that neither sends `exclude` nor drops a row it has already seen",
            "status": "EXEMPT"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"an empty batch arrives within 10 batches\"",
            "assertion": ":105 (control :90)",
            "excludes": "a feed that never runs dry, or runs dry only on the last call",
            "status": "EXEMPT"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"no request is made after it\"",
            "assertion": ":108 (control :107)",
            "excludes": "a pager that keeps fetching once `exhausted` should be set",
            "status": "EXEMPT"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "runs \"at the video page's 48-row batch\"",
            "assertion": "none",
            "excludes": "nothing: no assertion bounds `len(rows)` at 48",
            "status": "UNCARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"first batch is an up-next page (`seed.mode == \"upnext\"`)\"",
            "assertion": ":91",
            "excludes": "a seed that resolves to a random or other mode",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"second batch holds rows and none of the first batch's\"",
            "assertion": ":95, :96",
            "excludes": "an empty second page, and a second page that repeats the first",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"no later batch repeats a row of an earlier one\"",
            "assertion": ":100",
            "excludes": "a pager that only excludes the batch just before, not every earlier one",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"driven for MAX_BATCHES calls and reaches an empty batch before the last\"",
            "assertion": ":90, :105",
            "excludes": "a crashed run that stops early, and an empty batch only at index 9 or never",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"No call after the empty batch makes a request, counted on the fetch function\"",
            "assertion": ":108",
            "excludes": "a `next()` that calls `fetchBatch` after the feed is exhausted",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"`test_frontend_upnext_pager.py` is a test group\"",
            "assertion": ":121",
            "excludes": "a durable file missing from `tests/active`",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"the durable test itself\": the pager test, made durable",
            "assertion": "none",
            "excludes": "nothing: :121 accepts any file with that name, including one that asserts nothing about the pager",
            "status": "UNCARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`, so it is reselected when any of them changes\"",
            "assertion": ":122 (control :119)",
            "excludes": "a `test_groups` entry that leaves out any of the four",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"the pager's 48-row batches\"",
            "assertion": "none",
            "excludes": "nothing: batch size is never asserted",
            "status": "UNCARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"never repeat a row\"",
            "assertion": ":100",
            "excludes": "a pager that lets an Engine repeat through",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"it stops asking after an empty batch\"",
            "assertion": ":108",
            "excludes": "a pager that still fetches after an empty batch",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"the durable pager test is a group\"",
            "assertion": ":121",
            "excludes": "the group is absent",
            "status": "CARRIED"
          },
          {
            "id": "N5a",
            "source": "name",
            "clause": "\"fingerprinted over the files it runs through\": the four named subjects",
            "assertion": ":122",
            "excludes": "a mapping missing one of the four",
            "status": "CARRIED"
          },
          {
            "id": "N5b",
            "source": "name",
            "clause": "\"the files it runs through\": the rest of the path it exercises",
            "assertion": "none",
            "excludes": "nothing: `videos.ts` imports `./cache`, `./local-likes`, `./api-base` and `./profile`, and `fetchSimilarVideosPayload` calls `getRandomLikes`/`profileHeaders` on every request. None of them is in `SUBJECTS` (:30)",
            "status": "UNCARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. Stub question (agent spec, `<verdict>`) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:124-125\n   assert covered is not None, sorted(claims)  # C1\n   assert [s for s in SUBJECTS if ROOT / s not in covered] == [], covered  # C1\n   The phase's only output is the durable copy at tests/active/test_frontend_upnext_pager.py.\n   This test checks that the durable file is registered and mapped in config.json. It does not\n   check what the file contains. `claimed()` (validate_tests.py:643-648) adds a group for any\n   `test_*.py` it finds under tests/active, whatever that file holds. So an empty\n   `test_frontend_upnext_pager.py`, or one whose test body is only `pass`, plus the four config\n   entries, turns both lines green. The module docstring (line 6) says so itself: \"That the\n   durable file carries the pager assertions above is not checked here.\" For the stub question\n   to pass, the checkpoint has to test the phase's output directly, not something next to it.\n   The exemption does not cover this. The builder's reason gives up only the red-before-build\n   requirement on the pager assertions (\"its coverage\" is explicitly kept). It does not accept a\n   durable copy that can be empty.\n\n2. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:108\n   assert sizes[:empty - 1] == [int(PAGE)] * (empty - 1) and 0 < sizes[empty - 1] <= int(PAGE), sizes  # C1\n   The test sends `PAGE = \"48\"` (line 28) and checks for 48 coming back. The docstring (line 5)\n   says 48 is also the similars default (\"a run with no `limit` came back 48 x 6, 12\"). That\n   matches the fourth `<how_to_spot>` bullet: \"The expected result equals the shipped default,\n   so returning the default unchanged passes.\" A pager or fetch that drops `limit` passes this\n   line. The rule requires the size reading to change with the input. Here one input is used and\n   it matches the default.\n\nRECOMMENDATIONS\n1. EXEMPT C1: the exemption's line citations do not match the file (agent spec, `<verdict>`,\n   `exempted_clauses`) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:96-125\n   The builder's reason cites the C1 carriers as :91, :92, :96, :101, :104 and the controls as\n   :85-87, :90, :103. In the file, the lines tagged `# C1` are 96, 97, 101, 106, 108, 111, 124 and\n   125. Line 104 is the `empty = next(...)` computation, not an assertion. Lines 85-87 are the\n   `_seed` return and blank lines. Lines 91 and 92 are the batch-count check and the up-next\n   control. As written, the exemption does not point at the assertions it claims to cover. The\n   operator should re-confirm it against the real line numbers.\n\nPREDICTED FAILURE\nFails at line 124 on `assert covered is not None`, because tests/active/test_frontend_upnext_pager.py\ndoes not exist, so `claimed()` returns no `test_frontend_upnext_pager.py` group. The first test\n(lines 87-111) is expected to pass before the phase, as the exemption concedes.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve (it\n   is the phase's NEW file). Nothing in it could be checked.\n2. client/frontend/src/data/videos.ts (`createFeedPager`, `fetchSimilarVideosPayload`) was not in\n   `code_under_test` and was not read. The stub question for the pager test (lines 87-111) was\n   answered from the assertion form alone. Apart from finding 2, the positive controls at lines\n   95-96, 106 and 110 would turn a stub pager red.\n3. `fixtures_path` was not supplied. The `engine` and `engine_client` fixtures were resolved from\n   tests/active/conftest.py, which the test imports explicitly at line 24.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 9 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"48-row batches from the linux seed\" | :108 (seed from `q=linux` at :82) | batches of any size other than 48 before the last non-empty one. It does not catch a query that drops `limit`, because the default is also 48 | EXEMPT |\n| C1b | must_prove | \"no row repeats\" across batches | :97, :101 | a pager that neither sends `exclude` nor drops a row it has already seen | EXEMPT |\n| C1c | must_prove | \"an empty batch arrives within 10 batches\" | :106 (control :91) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |\n| C1d | must_prove | \"no request is made after it\" | :111 (control :110) | a pager that keeps fetching after it should have set `exhausted` | EXEMPT |\n| D1 | docstring | runs \"at the video page's 48-row batch\" | :108 | a pager or query that returns batches of a size other than 48 before the last non-empty one | CARRIED |\n| D2 | docstring | \"first batch is an up-next page (`seed.mode == \"upnext\"`)\" | :92 | a seed that resolves to a random mode or some other mode | CARRIED |\n| D3 | docstring | \"second batch holds rows and none of the first batch's\" | :96, :97 | an empty second page, and a second page that repeats the first | CARRIED |\n| D4 | docstring | \"no later batch repeats a row of an earlier one\" | :101 | a pager that excludes only the batch just before, not every earlier one | CARRIED |\n| D5 | docstring | \"driven for MAX_BATCHES calls and reaches an empty batch before the last\" | :91, :106 | a crashed run that stops early, and an empty batch that comes only at index 9 or never | CARRIED |\n| D6 | docstring | \"No call after the empty batch makes a request, counted on the fetch function\" | :111 | a `next()` that calls the given fetch after the feed is exhausted | CARRIED |\n| D7 | docstring | \"`test_frontend_upnext_pager.py` is discovered in tests/active\" as a test group | :124 | a durable file missing from `tests/active`. `groups()` rglobs `active` (validate_tests.py:604-613) | CARRIED |\n| D8 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D9 | docstring | claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`\" | :125 (controls :120, :122) | a `test_groups` entry that leaves out any of the four | CARRIED |\n| N1 | name | \"the pager's 48-row batches\" | :108 | a pager that yields batches of a size other than 48 | CARRIED |\n| N2 | name | \"never repeat a row\" | :101 | a pager that lets an Engine repeat through | CARRIED |\n| N3 | name | \"it stops asking after an empty batch\" | :111 | a pager that still fetches after an empty batch | CARRIED |\n| N4 | name | \"the durable pager group\" exists | :124 | a group that is absent | CARRIED |\n| N5a | name | \"fingerprinted over videos_ts, the client server and both engine similars files\" | :125 | a mapping that is missing one of the four | CARRIED |\n| N5b | name | withdrawn | n/a | n/a | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): D8 was withdrawn, not carried. tests/tmp/test_12_similars_on_scroll_phase1.py:6\n   The docstring was narrowed rather than an assertion added. It now says: \"That the durable file carries the pager assertions above is not checked here; it is left to review of that file.\"\n   The first ledger's \"the durable test itself\" clause is gone.\n   :124 still accepts a `test_frontend_upnext_pager.py` that asserts nothing about the pager.\n2. whole-claim (rules/testing.md): N5b was withdrawn, not carried. tests/tmp/test_12_similars_on_scroll_phase1.py:114\n   The name changed from \"fingerprinted over the files it runs through\" to \"fingerprinted over videos_ts, the client server and both engine similars files\".\n   The docstring at :6 now says outright that `cache`, `local-likes`, `api-base` and `profile` are not checked. So the name was narrowed rather than the mapping widened.\n3. surfaces / checkpoint_definition (rules/testing.md), no ledger row: tests/tmp/test_12_similars_on_scroll_phase1.py:124-125\n   By the docstring's own account (:6), the phase's output is a durable copy of this test plus its config mapping.\n   The only assertions that cover that output check the group's name and its claimed files. None checks the durable file's content. So the checkpoint proves the slice was registered, not that it behaves as C1 claims.\n   The docstring now discloses this, and C1 is exempted, so this does not block. It is recorded for whoever reads the gate.\n4. EXEMPT rows C1a-C1d: the operator exempted C1. The builder's reason says it is carried at \":91, :92, :96, :101 and :104, with controls at :85-87, :90 and :103\". Those line numbers are stale.\n   In the test as it now reads, C1 is carried at :97, :101, :106, :108 and :111, with controls at :83, :91, :92 and :110. The exemption is not wrong on substance, because C1 has assertions at this seam. The citation is out of date.\n5. whole-claim (rules/testing.md): C1a/D1/N1, tests/tmp/test_12_similars_on_scroll_phase1.py:108\n   The size bound excludes batches of any size other than 48. It cannot tell a sent `limit=48` from a dropped one, because the endpoint's default is also 48. The docstring at :5 says so.\n   No rule requires more than the bound, so this goes on the record only.\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/active/test_frontend_upnext_pager.py`, which does not resolve (FileNotFoundError). Its contents could not be read, so nothing here bears on what that file asserts.\n2. `code_under_test` does not include `client/frontend/src/data/videos.ts` (`createFeedPager`, `fetchSimilarVideosPayload`), and it was not read. Bounds and the abnormal path of the pager were judged from the test alone.\n3. `fixtures_path` was none. `engine_client` and `engine` are imported from `tests/active/conftest.py:24`. Only their scope was checked: `engine` is session-scoped at :105, `engine_client` is function-scoped at :148. Their bodies were not read.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. Stub question (agent spec, `<verdict>`) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:124-125\n   assert covered is not None, sorted(claims)  # C1\n   assert [s for s in SUBJECTS if ROOT / s not in covered] == [], covered  # C1\n   The phase's only output is the durable copy at tests/active/test_frontend_upnext_pager.py.\n   This test checks that the durable file is registered and mapped in config.json. It does not\n   check what the file contains. `claimed()` (validate_tests.py:643-648) adds a group for any\n   `test_*.py` it finds under tests/active, whatever that file holds. So an empty\n   `test_frontend_upnext_pager.py`, or one whose test body is only `pass`, plus the four config\n   entries, turns both lines green. The module docstring (line 6) says so itself: \"That the\n   durable file carries the pager assertions above is not checked here.\" For the stub question\n   to pass, the checkpoint has to test the phase's output directly, not something next to it.\n   The exemption does not cover this. The builder's reason gives up only the red-before-build\n   requirement on the pager assertions (\"its coverage\" is explicitly kept). It does not accept a\n   durable copy that can be empty.\n\n2. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:108\n   assert sizes[:empty - 1] == [int(PAGE)] * (empty - 1) and 0 < sizes[empty - 1] <= int(PAGE), sizes  # C1\n   The test sends `PAGE = \"48\"` (line 28) and checks for 48 coming back. The docstring (line 5)\n   says 48 is also the similars default (\"a run with no `limit` came back 48 x 6, 12\"). That\n   matches the fourth `<how_to_spot>` bullet: \"The expected result equals the shipped default,\n   so returning the default unchanged passes.\" A pager or fetch that drops `limit` passes this\n   line. The rule requires the size reading to change with the input. Here one input is used and\n   it matches the default.\n\nRECOMMENDATIONS\n1. EXEMPT C1: the exemption's line citations do not match the file (agent spec, `<verdict>`,\n   `exempted_clauses`) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:96-125\n   The builder's reason cites the C1 carriers as :91, :92, :96, :101, :104 and the controls as\n   :85-87, :90, :103. In the file, the lines tagged `# C1` are 96, 97, 101, 106, 108, 111, 124 and\n   125. Line 104 is the `empty = next(...)` computation, not an assertion. Lines 85-87 are the\n   `_seed` return and blank lines. Lines 91 and 92 are the batch-count check and the up-next\n   control. As written, the exemption does not point at the assertions it claims to cover. The\n   operator should re-confirm it against the real line numbers.\n\nPREDICTED FAILURE\nFails at line 124 on `assert covered is not None`, because tests/active/test_frontend_upnext_pager.py\ndoes not exist, so `claimed()` returns no `test_frontend_upnext_pager.py` group. The first test\n(lines 87-111) is expected to pass before the phase, as the exemption concedes.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve (it\n   is the phase's NEW file). Nothing in it could be checked.\n2. client/frontend/src/data/videos.ts (`createFeedPager`, `fetchSimilarVideosPayload`) was not in\n   `code_under_test` and was not read. The stub question for the pager test (lines 87-111) was\n   answered from the assertion form alone. Apart from finding 2, the positive controls at lines\n   95-96, 106 and 110 would turn a stub pager red.\n3. `fixtures_path` was not supplied. The `engine` and `engine_client` fixtures were resolved from\n   tests/active/conftest.py, which the test imports explicitly at line 24.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 9 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"48-row batches from the linux seed\" | :108 (seed from `q=linux` at :82) | batches of any size other than 48 before the last non-empty one. It does not catch a query that drops `limit`, because the default is also 48 | EXEMPT |\n| C1b | must_prove | \"no row repeats\" across batches | :97, :101 | a pager that neither sends `exclude` nor drops a row it has already seen | EXEMPT |\n| C1c | must_prove | \"an empty batch arrives within 10 batches\" | :106 (control :91) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |\n| C1d | must_prove | \"no request is made after it\" | :111 (control :110) | a pager that keeps fetching after it should have set `exhausted` | EXEMPT |\n| D1 | docstring | runs \"at the video page's 48-row batch\" | :108 | a pager or query that returns batches of a size other than 48 before the last non-empty one | CARRIED |\n| D2 | docstring | \"first batch is an up-next page (`seed.mode == \"upnext\"`)\" | :92 | a seed that resolves to a random mode or some other mode | CARRIED |\n| D3 | docstring | \"second batch holds rows and none of the first batch's\" | :96, :97 | an empty second page, and a second page that repeats the first | CARRIED |\n| D4 | docstring | \"no later batch repeats a row of an earlier one\" | :101 | a pager that excludes only the batch just before, not every earlier one | CARRIED |\n| D5 | docstring | \"driven for MAX_BATCHES calls and reaches an empty batch before the last\" | :91, :106 | a crashed run that stops early, and an empty batch that comes only at index 9 or never | CARRIED |\n| D6 | docstring | \"No call after the empty batch makes a request, counted on the fetch function\" | :111 | a `next()` that calls the given fetch after the feed is exhausted | CARRIED |\n| D7 | docstring | \"`test_frontend_upnext_pager.py` is discovered in tests/active\" as a test group | :124 | a durable file missing from `tests/active`. `groups()` rglobs `active` (validate_tests.py:604-613) | CARRIED |\n| D8 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D9 | docstring | claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`\" | :125 (controls :120, :122) | a `test_groups` entry that leaves out any of the four | CARRIED |\n| N1 | name | \"the pager's 48-row batches\" | :108 | a pager that yields batches of a size other than 48 | CARRIED |\n| N2 | name | \"never repeat a row\" | :101 | a pager that lets an Engine repeat through | CARRIED |\n| N3 | name | \"it stops asking after an empty batch\" | :111 | a pager that still fetches after an empty batch | CARRIED |\n| N4 | name | \"the durable pager group\" exists | :124 | a group that is absent | CARRIED |\n| N5a | name | \"fingerprinted over videos_ts, the client server and both engine similars files\" | :125 | a mapping that is missing one of the four | CARRIED |\n| N5b | name | withdrawn | n/a | n/a | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): D8 was withdrawn, not carried. tests/tmp/test_12_similars_on_scroll_phase1.py:6\n   The docstring was narrowed rather than an assertion added. It now says: \"That the durable file carries the pager assertions above is not checked here; it is left to review of that file.\"\n   The first ledger's \"the durable test itself\" clause is gone.\n   :124 still accepts a `test_frontend_upnext_pager.py` that asserts nothing about the pager.\n2. whole-claim (rules/testing.md): N5b was withdrawn, not carried. tests/tmp/test_12_similars_on_scroll_phase1.py:114\n   The name changed from \"fingerprinted over the files it runs through\" to \"fingerprinted over videos_ts, the client server and both engine similars files\".\n   The docstring at :6 now says outright that `cache`, `local-likes`, `api-base` and `profile` are not checked. So the name was narrowed rather than the mapping widened.\n3. surfaces / checkpoint_definition (rules/testing.md), no ledger row: tests/tmp/test_12_similars_on_scroll_phase1.py:124-125\n   By the docstring's own account (:6), the phase's output is a durable copy of this test plus its config mapping.\n   The only assertions that cover that output check the group's name and its claimed files. None checks the durable file's content. So the checkpoint proves the slice was registered, not that it behaves as C1 claims.\n   The docstring now discloses this, and C1 is exempted, so this does not block. It is recorded for whoever reads the gate.\n4. EXEMPT rows C1a-C1d: the operator exempted C1. The builder's reason says it is carried at \":91, :92, :96, :101 and :104, with controls at :85-87, :90 and :103\". Those line numbers are stale.\n   In the test as it now reads, C1 is carried at :97, :101, :106, :108 and :111, with controls at :83, :91, :92 and :110. The exemption is not wrong on substance, because C1 has assertions at this seam. The citation is out of date.\n5. whole-claim (rules/testing.md): C1a/D1/N1, tests/tmp/test_12_similars_on_scroll_phase1.py:108\n   The size bound excludes batches of any size other than 48. It cannot tell a sent `limit=48` from a dropped one, because the endpoint's default is also 48. The docstring at :5 says so.\n   No rule requires more than the bound, so this goes on the record only.\n\nNOT ASSESSED\n1. `code_under_test` lists `tests/active/test_frontend_upnext_pager.py`, which does not resolve (FileNotFoundError). Its contents could not be read, so nothing here bears on what that file asserts.\n2. `code_under_test` does not include `client/frontend/src/data/videos.ts` (`createFeedPager`, `fetchSimilarVideosPayload`), and it was not read. Bounds and the abnormal path of the pager were judged from the test alone.\n3. `fixtures_path` was none. `engine_client` and `engine` are imported from `tests/active/conftest.py:24`. Only their scope was checked: `engine` is session-scoped at :105, `engine_client` is function-scoped at :148. Their bodies were not read.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"48-row batches from the linux seed\"",
            "assertion": ":108 (seed from `q=linux` at :82)",
            "excludes": "batches of any size other than 48 before the last non-empty one. It does not catch a query that drops `limit`, because the default is also 48",
            "status": "EXEMPT"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"no row repeats\" across batches",
            "assertion": ":97, :101",
            "excludes": "a pager that neither sends `exclude` nor drops a row it has already seen",
            "status": "EXEMPT"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"an empty batch arrives within 10 batches\"",
            "assertion": ":106 (control :91)",
            "excludes": "a feed that never runs dry, or runs dry only on the last call",
            "status": "EXEMPT"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"no request is made after it\"",
            "assertion": ":111 (control :110)",
            "excludes": "a pager that keeps fetching after it should have set `exhausted`",
            "status": "EXEMPT"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "runs \"at the video page's 48-row batch\"",
            "assertion": ":108",
            "excludes": "a pager or query that returns batches of a size other than 48 before the last non-empty one",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"first batch is an up-next page (`seed.mode == \"upnext\"`)\"",
            "assertion": ":92",
            "excludes": "a seed that resolves to a random mode or some other mode",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"second batch holds rows and none of the first batch's\"",
            "assertion": ":96, :97",
            "excludes": "an empty second page, and a second page that repeats the first",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"no later batch repeats a row of an earlier one\"",
            "assertion": ":101",
            "excludes": "a pager that excludes only the batch just before, not every earlier one",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"driven for MAX_BATCHES calls and reaches an empty batch before the last\"",
            "assertion": ":91, :106",
            "excludes": "a crashed run that stops early, and an empty batch that comes only at index 9 or never",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"No call after the empty batch makes a request, counted on the fetch function\"",
            "assertion": ":111",
            "excludes": "a `next()` that calls the given fetch after the feed is exhausted",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"`test_frontend_upnext_pager.py` is discovered in tests/active\" as a test group",
            "assertion": ":124",
            "excludes": "a durable file missing from `tests/active`. `groups()` rglobs `active` (validate_tests.py:604-613)",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`\"",
            "assertion": ":125 (controls :120, :122)",
            "excludes": "a `test_groups` entry that leaves out any of the four",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"the pager's 48-row batches\"",
            "assertion": ":108",
            "excludes": "a pager that yields batches of a size other than 48",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"never repeat a row\"",
            "assertion": ":101",
            "excludes": "a pager that lets an Engine repeat through",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"it stops asking after an empty batch\"",
            "assertion": ":111",
            "excludes": "a pager that still fetches after an empty batch",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"the durable pager group\" exists",
            "assertion": ":124",
            "excludes": "a group that is absent",
            "status": "CARRIED"
          },
          {
            "id": "N5a",
            "source": "name",
            "clause": "\"fingerprinted over videos_ts, the client server and both engine similars files\"",
            "assertion": ":125",
            "excludes": "a mapping that is missing one of the four",
            "status": "CARRIED"
          },
          {
            "id": "N5b",
            "source": "name",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. EXEMPT C1: stub question (rules/shape.md `<ladder>` / stub question) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:118-142\n   `assert sizes[:empty - 1] == [int(PAGE)] * (empty - 1) and 0 < sizes[empty - 1] <= int(PAGE), sizes  # C1`\n   The first test passes against the code as it stands, which is \"the previous behaviour left unchanged\". That is the red-before-build concession the builder's reason describes. Its assertion form is still sound. Rung 2 fits: the pager is TypeScript run as a node subprocess over the real bundle. Line 120 is a positive control. Lines 124, 125 and 129 check that no row repeats across batches. Lines 138-139 count calls up to the empty batch and after it. Lines 141-142 run a second input (limit 20 against the default 48), so a pager that ignores `limit` goes red, which avoids `single-value-pin`. The exemption itself looks right. One problem: the reason cites :91, :92, :96, :101, :104 and controls at :85-87, :90, :103. In this file those lines are helper bodies (`_load`, `_canned`, `_fails`, `_seed`). The C1 assertions are at 124-142, with controls at 118-120 and 138. The gate record should fix those line references so they point at the assertions.\n\nPREDICTED FAILURE\nFails at line 146 on `assert DURABLE.is_file(), DURABLE`, because tests/active/test_frontend_upnext_pager.py does not exist yet. It also fails at line 173 on `assert covered is not None, sorted(claims)`: with no file there, `groups()` finds no `test_frontend_upnext_pager.py` group, and config.json's `test_groups` has no entry for it. The controls at 169 and 171 hold: `test_frontend_video_page.py` is mapped to `video-page/index.ts`, and all four SUBJECTS exist. The first test (lines 116-142) is expected green, as the exemption says.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not exist yet. The stub question for the second test was answered from its own form only. Line 151 checks that a pager meeting the contract passes, line 162 checks that six wrong pagers fail, and together they make an always-pass or always-fail durable test go red. How the durable file itself will be shaped was not assessed.\n2. `fixtures_path` was not supplied. The fixture `engine_client` is imported from tests/active/conftest.py (line 25). I grepped that file for `engine`, `engine_client` and `.base` but did not read it in full, and I did not verify the fixture's `request()` return shape.\n3. The first test's live behaviour: nothing was executed. My view that it is green on current code rests on the exemption's account and on `createFeedPager` and `fetchSimilarVideosPayload` both being in client/frontend/src/data/videos.ts (:37, :130).",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 9 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"48-row batches from the linux seed\" | :136, :142 (setup `q=linux` :84) | a batch that is not 48 before the last non-empty one; a query that drops `limit` (the default is also 48, so the limit-20 run would come back 48 x 2) | EXEMPT |\n| C1b | must_prove | \"no row repeats\" across batches | :125, :129 | a pager that neither sends `exclude` nor drops a row from any earlier batch | EXEMPT |\n| C1c | must_prove | \"an empty batch arrives within 10 batches\" | :134 (control :119) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |\n| C1d | must_prove | \"no request is made after it\" | :139 (control :138) | a `next()` that calls the fetch function once the feed is exhausted | EXEMPT |\n| D1 | docstring | runs \"at the video page's 48-row batch\" | :136, :142 | a batch size other than 48; a batch size that ignores the `limit` sent | CARRIED |\n| D2 | docstring | \"first batch is an up-next page (`seed.mode == \"upnext\"`)\" | :120 | a seed that resolves to random or another mode | CARRIED |\n| D3 | docstring | \"second batch holds rows and none of the first batch's\" | :124, :125 | an empty second page; a second page that repeats the first | CARRIED |\n| D4 | docstring | \"no later batch repeats a row of an earlier one\" | :129 | a pager that excludes only the batch just before, not every earlier one (`seen` is cumulative) | CARRIED |\n| D5 | docstring | \"driven for MAX_BATCHES calls and reaches an empty batch before the last\" | :119, :134 | a run that crashed and stopped early; an empty batch only at index 9, or never | CARRIED |\n| D6 | docstring | \"No call after the empty batch makes a request, counted on the fetch function\" | :139 | a `next()` that calls the `createFeedPager` fetch argument after exhaustion | CARRIED |\n| D7 | docstring | \"A test group named `test_frontend_upnext_pager.py` is discovered in tests/active\" | :173 (control :169) | a durable file missing from `tests/active`. `claimed()` keys only on groups that `groups()` rglobs from `active` | CARRIED |\n| D8 | docstring | \"the durable test itself\": passes contract batches, and fails with AssertionError on repeat / never dry / keeps asking / other mode / empty second / crash | :146, :148, :151, :162 | a missing durable file; a durable file with no `test_*`; a durable test that asserts nothing (fails :162); one that checks only adjacent batches (repeat planted at batch 3 vs 0, :153) | CARRIED |\n| D9 | docstring | claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`\" | :174 (control :171) | a `test_groups` entry that leaves out any of the four | CARRIED |\n| N1 | name | \"the pager's 48-row batches\" | :136, :142 | a batch size other than 48, or one that does not follow `limit` | CARRIED |\n| N2 | name | \"never repeat a row\" | :129 | a pager that lets an Engine repeat through | CARRIED |\n| N3 | name | \"it stops asking after an empty batch\" | :139 | a pager that still fetches after an empty batch | CARRIED |\n| N4 | name | \"the durable pager test is a group\" | :173 | the group is absent from discovery | CARRIED |\n| N5a | name | \"fingerprinted over\" the four named subjects | :174 | a mapping missing one of the four | CARRIED |\n| N5b | name | withdrawn | n/a | n/a | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. re-audit, N5b (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:165\n   The name used to say \"the files it runs through\". It now names only \"videos_ts the client server and both engine similars files\". The docstring at :6 now says outright that `cache`, `local-likes`, `api-base` and `profile` \"are not in the plan's mapping and are not checked\". The prose was narrowed; no assertion was added. The row is closed by withdrawal.\n2. re-audit, D8 (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:6, :151, :162\n   Two things changed here. Assertions were added (:151 control, :162 six wrong batch sets). The prose was also narrowed: \"The batches are canned, so the durable file's live run is not repeated here\". What is proved is that the durable file's assertions reject the listed wrong batch sets. Nothing proves that its live `_run` drives the real pager.\n3. Not a ledger row (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:104, :151\n   `_fails` replaces `durable._run` with `lambda *args: batches`. Every call therefore returns the same 48 x 6, 12 batches. A durable test that repeats this file's limit-20 check (:141\u2013142) would fail the control at :151. None of the wrong sets at :154\u2013161 has a wrong batch size. So neither the control nor the mutations require the durable copy to carry C1a. That clause is EXEMPT here, and the durable copy may legitimately be weaker than this test on batch size.\n4. Exemption record. The builder's reason cites :91, :92, :96, :101, :104 and controls :85-87, :90, :103. None of those lines matches the file as it now reads. C1 is currently carried at :120, :124, :125, :129, :134, :136, :139 and :142, with controls at :119 and :138. The exemption is not wrong: every C1 sub-clause is asserted anyway. Only the citations are stale.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve. The durable file's contents were not read. D7, D8 and N4 were judged only by what this test asserts about that file, not by what the file does.\n2. `fixtures_path` was not supplied. The test imports `engine` and `engine_client` from tests/active/conftest.py (:25). Their definitions were found at conftest.py:106 and :149 by search. Their bodies were not read in full.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. EXEMPT C1: stub question (rules/shape.md `<ladder>` / stub question) \u2014 tests/tmp/test_12_similars_on_scroll_phase1.py:118-142\n   `assert sizes[:empty - 1] == [int(PAGE)] * (empty - 1) and 0 < sizes[empty - 1] <= int(PAGE), sizes  # C1`\n   The first test passes against the code as it stands, which is \"the previous behaviour left unchanged\". That is the red-before-build concession the builder's reason describes. Its assertion form is still sound. Rung 2 fits: the pager is TypeScript run as a node subprocess over the real bundle. Line 120 is a positive control. Lines 124, 125 and 129 check that no row repeats across batches. Lines 138-139 count calls up to the empty batch and after it. Lines 141-142 run a second input (limit 20 against the default 48), so a pager that ignores `limit` goes red, which avoids `single-value-pin`. The exemption itself looks right. One problem: the reason cites :91, :92, :96, :101, :104 and controls at :85-87, :90, :103. In this file those lines are helper bodies (`_load`, `_canned`, `_fails`, `_seed`). The C1 assertions are at 124-142, with controls at 118-120 and 138. The gate record should fix those line references so they point at the assertions.\n\nPREDICTED FAILURE\nFails at line 146 on `assert DURABLE.is_file(), DURABLE`, because tests/active/test_frontend_upnext_pager.py does not exist yet. It also fails at line 173 on `assert covered is not None, sorted(claims)`: with no file there, `groups()` finds no `test_frontend_upnext_pager.py` group, and config.json's `test_groups` has no entry for it. The controls at 169 and 171 hold: `test_frontend_video_page.py` is mapped to `video-page/index.ts`, and all four SUBJECTS exist. The first test (lines 116-142) is expected green, as the exemption says.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not exist yet. The stub question for the second test was answered from its own form only. Line 151 checks that a pager meeting the contract passes, line 162 checks that six wrong pagers fail, and together they make an always-pass or always-fail durable test go red. How the durable file itself will be shaped was not assessed.\n2. `fixtures_path` was not supplied. The fixture `engine_client` is imported from tests/active/conftest.py (line 25). I grepped that file for `engine`, `engine_client` and `.base` but did not read it in full, and I did not verify the fixture's `request()` return shape.\n3. The first test's live behaviour: nothing was executed. My view that it is green on current code rests on the exemption's account and on `createFeedPager` and `fetchSimilarVideosPayload` both being in client/frontend/src/data/videos.ts (:37, :130).\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 4 must_prove, 9 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"48-row batches from the linux seed\" | :136, :142 (setup `q=linux` :84) | a batch that is not 48 before the last non-empty one; a query that drops `limit` (the default is also 48, so the limit-20 run would come back 48 x 2) | EXEMPT |\n| C1b | must_prove | \"no row repeats\" across batches | :125, :129 | a pager that neither sends `exclude` nor drops a row from any earlier batch | EXEMPT |\n| C1c | must_prove | \"an empty batch arrives within 10 batches\" | :134 (control :119) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |\n| C1d | must_prove | \"no request is made after it\" | :139 (control :138) | a `next()` that calls the fetch function once the feed is exhausted | EXEMPT |\n| D1 | docstring | runs \"at the video page's 48-row batch\" | :136, :142 | a batch size other than 48; a batch size that ignores the `limit` sent | CARRIED |\n| D2 | docstring | \"first batch is an up-next page (`seed.mode == \"upnext\"`)\" | :120 | a seed that resolves to random or another mode | CARRIED |\n| D3 | docstring | \"second batch holds rows and none of the first batch's\" | :124, :125 | an empty second page; a second page that repeats the first | CARRIED |\n| D4 | docstring | \"no later batch repeats a row of an earlier one\" | :129 | a pager that excludes only the batch just before, not every earlier one (`seen` is cumulative) | CARRIED |\n| D5 | docstring | \"driven for MAX_BATCHES calls and reaches an empty batch before the last\" | :119, :134 | a run that crashed and stopped early; an empty batch only at index 9, or never | CARRIED |\n| D6 | docstring | \"No call after the empty batch makes a request, counted on the fetch function\" | :139 | a `next()` that calls the `createFeedPager` fetch argument after exhaustion | CARRIED |\n| D7 | docstring | \"A test group named `test_frontend_upnext_pager.py` is discovered in tests/active\" | :173 (control :169) | a durable file missing from `tests/active`. `claimed()` keys only on groups that `groups()` rglobs from `active` | CARRIED |\n| D8 | docstring | \"the durable test itself\": passes contract batches, and fails with AssertionError on repeat / never dry / keeps asking / other mode / empty second / crash | :146, :148, :151, :162 | a missing durable file; a durable file with no `test_*`; a durable test that asserts nothing (fails :162); one that checks only adjacent batches (repeat planted at batch 3 vs 0, :153) | CARRIED |\n| D9 | docstring | claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`\" | :174 (control :171) | a `test_groups` entry that leaves out any of the four | CARRIED |\n| N1 | name | \"the pager's 48-row batches\" | :136, :142 | a batch size other than 48, or one that does not follow `limit` | CARRIED |\n| N2 | name | \"never repeat a row\" | :129 | a pager that lets an Engine repeat through | CARRIED |\n| N3 | name | \"it stops asking after an empty batch\" | :139 | a pager that still fetches after an empty batch | CARRIED |\n| N4 | name | \"the durable pager test is a group\" | :173 | the group is absent from discovery | CARRIED |\n| N5a | name | \"fingerprinted over\" the four named subjects | :174 | a mapping missing one of the four | CARRIED |\n| N5b | name | withdrawn | n/a | n/a | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. re-audit, N5b (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:165\n   The name used to say \"the files it runs through\". It now names only \"videos_ts the client server and both engine similars files\". The docstring at :6 now says outright that `cache`, `local-likes`, `api-base` and `profile` \"are not in the plan's mapping and are not checked\". The prose was narrowed; no assertion was added. The row is closed by withdrawal.\n2. re-audit, D8 (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:6, :151, :162\n   Two things changed here. Assertions were added (:151 control, :162 six wrong batch sets). The prose was also narrowed: \"The batches are canned, so the durable file's live run is not repeated here\". What is proved is that the durable file's assertions reject the listed wrong batch sets. Nothing proves that its live `_run` drives the real pager.\n3. Not a ledger row (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:104, :151\n   `_fails` replaces `durable._run` with `lambda *args: batches`. Every call therefore returns the same 48 x 6, 12 batches. A durable test that repeats this file's limit-20 check (:141\u2013142) would fail the control at :151. None of the wrong sets at :154\u2013161 has a wrong batch size. So neither the control nor the mutations require the durable copy to carry C1a. That clause is EXEMPT here, and the durable copy may legitimately be weaker than this test on batch size.\n4. Exemption record. The builder's reason cites :91, :92, :96, :101, :104 and controls :85-87, :90, :103. None of those lines matches the file as it now reads. C1 is currently carried at :120, :124, :125, :129, :134, :136, :139 and :142, with controls at :119 and :138. The exemption is not wrong: every C1 sub-clause is asserted anyway. Only the citations are stale.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve. The durable file's contents were not read. D7, D8 and N4 were judged only by what this test asserts about that file, not by what the file does.\n2. `fixtures_path` was not supplied. The test imports `engine` and `engine_client` from tests/active/conftest.py (:25). Their definitions were found at conftest.py:106 and :149 by search. Their bodies were not read in full.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"48-row batches from the linux seed\"",
            "assertion": ":136, :142 (setup `q=linux` :84)",
            "excludes": "a batch that is not 48 before the last non-empty one; a query that drops `limit` (the default is also 48, so the limit-20 run would come back 48 x 2)",
            "status": "EXEMPT"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"no row repeats\" across batches",
            "assertion": ":125, :129",
            "excludes": "a pager that neither sends `exclude` nor drops a row from any earlier batch",
            "status": "EXEMPT"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"an empty batch arrives within 10 batches\"",
            "assertion": ":134 (control :119)",
            "excludes": "a feed that never runs dry, or runs dry only on the last call",
            "status": "EXEMPT"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"no request is made after it\"",
            "assertion": ":139 (control :138)",
            "excludes": "a `next()` that calls the fetch function once the feed is exhausted",
            "status": "EXEMPT"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "runs \"at the video page's 48-row batch\"",
            "assertion": ":136, :142",
            "excludes": "a batch size other than 48; a batch size that ignores the `limit` sent",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"first batch is an up-next page (`seed.mode == \"upnext\"`)\"",
            "assertion": ":120",
            "excludes": "a seed that resolves to random or another mode",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"second batch holds rows and none of the first batch's\"",
            "assertion": ":124, :125",
            "excludes": "an empty second page; a second page that repeats the first",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"no later batch repeats a row of an earlier one\"",
            "assertion": ":129",
            "excludes": "a pager that excludes only the batch just before, not every earlier one (`seen` is cumulative)",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"driven for MAX_BATCHES calls and reaches an empty batch before the last\"",
            "assertion": ":119, :134",
            "excludes": "a run that crashed and stopped early; an empty batch only at index 9, or never",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"No call after the empty batch makes a request, counted on the fetch function\"",
            "assertion": ":139",
            "excludes": "a `next()` that calls the `createFeedPager` fetch argument after exhaustion",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"A test group named `test_frontend_upnext_pager.py` is discovered in tests/active\"",
            "assertion": ":173 (control :169)",
            "excludes": "a durable file missing from `tests/active`. `claimed()` keys only on groups that `groups()` rglobs from `active`",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"the durable test itself\": passes contract batches, and fails with AssertionError on repeat / never dry / keeps asking / other mode / empty second / crash",
            "assertion": ":146, :148, :151, :162",
            "excludes": "a missing durable file; a durable file with no `test_*`; a durable test that asserts nothing (fails :162); one that checks only adjacent batches (repeat planted at batch 3 vs 0, :153)",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "claimed files \"include `data/videos.ts`, \u2026 `server.py`, \u2026 `similarity_candidates.py` and `handlers/similar.py`\"",
            "assertion": ":174 (control :171)",
            "excludes": "a `test_groups` entry that leaves out any of the four",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"the pager's 48-row batches\"",
            "assertion": ":136, :142",
            "excludes": "a batch size other than 48, or one that does not follow `limit`",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"never repeat a row\"",
            "assertion": ":129",
            "excludes": "a pager that lets an Engine repeat through",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"it stops asking after an empty batch\"",
            "assertion": ":139",
            "excludes": "a pager that still fetches after an empty batch",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"the durable pager test is a group\"",
            "assertion": ":173",
            "excludes": "the group is absent from discovery",
            "status": "CARRIED"
          },
          {
            "id": "N5a",
            "source": "name",
            "clause": "\"fingerprinted over\" the four named subjects",
            "assertion": ":174",
            "excludes": "a mapping missing one of the four",
            "status": "CARRIED"
          },
          {
            "id": "N5b",
            "source": "name",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_12_similars_on_scroll_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_12_similars_on_scroll_phase2.py:125. The single `/recommendations` POST has `recommendations[0][\"query\"].get(\"limit\") == \"8\"`, not `\"48\"`, because `loadSimilarVideos` in client/frontend/src/pages/video-page/index.ts:307 still passes `limit: \"8\"` to `fetchSimilarVideosPayload`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_frontend_video_page_similars.py (NEW), which does not resolve. Nothing in the test under audit imports it, so the audit covered only the test file, client/frontend/src/pages/video-page/index.ts, and `buildSimilarUrl`/`fetchSimilarVideosPayload` in client/frontend/src/data/videos.ts.\n2. The runner's docstring (lines 6\u20137) says it copies the harness from tests/active/test_frontend_video_page.py. That file was not read. The runner used here is defined inline at lines 24\u201389, and that inline copy was assessed.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (15 clauses: 2 must_prove, 9 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | the first `/recommendations` request is the one checked (no earlier or extra one) | :124 | a page that sends a second batch request, e.g. the old limit-8 call plus a new limit-48 call | CARRIED |\n| C1b | must_prove | that request \"carries limit 48\" | :125 | a request with `limit=8` (the current value), no limit, or the limit sent somewhere else | CARRIED |\n| C2 | must_prove | \"from a 48-row answer, `#similar-videos` holds exactly 8 cards\" | :129 | a page that renders all 48 rows, or fewer than 8, into `#similar-videos` | CARRIED |\n| D1 | docstring | \"run in node with the real page module\" | :116 | a runner where the bundled page never ran its loads, so a missing request reads as the page's fault | CARRIED |\n| D2 | docstring | \"its first batch is one `/recommendations` request for 48 rows\" | :124, :125 | several requests, or one request for a different number of rows | CARRIED |\n| D3 | docstring | \"of which only the first 8 are shown\" | :129, :131 | showing all rows, or showing 8 that are not the first 8 | CARRIED |\n| D4 | docstring | \"exactly one `/recommendations` request\" | :124 | two or more requests, or none | CARRIED |\n| D5 | docstring | \"a POST\" | :125 | a GET to `/recommendations` | CARRIED |\n| D6 | docstring | \"whose `limit` query parameter is \\\"48\\\" (the limit travels in the query string)\" | :125 | the limit sent only in the JSON body, or a different value in the query | CARRIED |\n| D7 | docstring | \"answered with 48 distinct rows in up-next mode, \u2026 exactly 8 `similar-card-item` anchors\" | :129 | a count of anything other than 8 anchors of that class | CARRIED |\n| D8 | docstring | \"they are the answer's first 8 rows in order\" | :131 | the last 8 rows, 8 rows in a shuffled order, or anchors with no `data-video-key` | CARRIED |\n| D9 | docstring | harness: \"filling the viewport never asks for more\" | :124 | a fill-viewport pass that sends a second batch request would fail the single-request check | CARRIED |\n| D10 | docstring | harness: `fetch` \"records each request's method, path, query and JSON body, answers `/recommendations` with the 48 rows and `{}` elsewhere\" | :116, :125 | a stub that records nothing: the control and the method/query checks read what it recorded | CARRIED |\n| N1 | name | \"the first batch\" | :124 | a page that has already requested a later batch by the time the test reads | CARRIED |\n| N2 | name | \"is one recommendations request\" | :124 | more than one request, or none | CARRIED |\n| N3 | name | \"for 48 rows\" | :125 | a limit other than 48 | CARRIED |\n| N4 | name | \"of which the first 8 are shown\" | :129, :131 | the wrong count, or the right count taken from the wrong rows | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase2.py:107\n   `rows = [... for i in range(ROWS)]`: the only answer tried has 48 rows. Nothing tests an answer at or below the display count: 0 rows (the code's `No similar videos found.` branch), 1 row, exactly 8, or 7. An implementation that pads to 8 or breaks on a short answer is not excluded.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase2.py:81\n   `fetch` always returns 200, so only the success path runs. The failure the page is built to handle is untested: a non-OK `/recommendations` response rendering the `.error` block, and a 401 rendering the key-rejected notice.\n3. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase2.py:87\n   The runner writes out `observed` (the observer targets) and records each request's `body`, and no assertion reads either. No rule is broken because the docstring does not claim anything from them. This is noted only because captured-but-unasserted output reads like coverage.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_video_page_similars.py (NEW), and that path does not resolve. Nothing in it could be read.\n2. `fixtures_path` was not supplied. The test uses only its own module fixture `bundle` (:92) and pytest's built-in `tmp_path_factory`, so no conftest was needed to judge independence.\n3. The docstring (:6) says the runner is \"the one in `tests/active/test_frontend_video_page.py`\". That file was not compared with `RUNNER`. It is a provenance claim, not a behavioural clause.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_12_similars_on_scroll_phase2.py:125. The single `/recommendations` POST has `recommendations[0][\"query\"].get(\"limit\") == \"8\"`, not `\"48\"`, because `loadSimilarVideos` in client/frontend/src/pages/video-page/index.ts:307 still passes `limit: \"8\"` to `fetchSimilarVideosPayload`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_frontend_video_page_similars.py (NEW), which does not resolve. Nothing in the test under audit imports it, so the audit covered only the test file, client/frontend/src/pages/video-page/index.ts, and `buildSimilarUrl`/`fetchSimilarVideosPayload` in client/frontend/src/data/videos.ts.\n2. The runner's docstring (lines 6\u20137) says it copies the harness from tests/active/test_frontend_video_page.py. That file was not read. The runner used here is defined inline at lines 24\u201389, and that inline copy was assessed.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (15 clauses: 2 must_prove, 9 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | the first `/recommendations` request is the one checked (no earlier or extra one) | :124 | a page that sends a second batch request, e.g. the old limit-8 call plus a new limit-48 call | CARRIED |\n| C1b | must_prove | that request \"carries limit 48\" | :125 | a request with `limit=8` (the current value), no limit, or the limit sent somewhere else | CARRIED |\n| C2 | must_prove | \"from a 48-row answer, `#similar-videos` holds exactly 8 cards\" | :129 | a page that renders all 48 rows, or fewer than 8, into `#similar-videos` | CARRIED |\n| D1 | docstring | \"run in node with the real page module\" | :116 | a runner where the bundled page never ran its loads, so a missing request reads as the page's fault | CARRIED |\n| D2 | docstring | \"its first batch is one `/recommendations` request for 48 rows\" | :124, :125 | several requests, or one request for a different number of rows | CARRIED |\n| D3 | docstring | \"of which only the first 8 are shown\" | :129, :131 | showing all rows, or showing 8 that are not the first 8 | CARRIED |\n| D4 | docstring | \"exactly one `/recommendations` request\" | :124 | two or more requests, or none | CARRIED |\n| D5 | docstring | \"a POST\" | :125 | a GET to `/recommendations` | CARRIED |\n| D6 | docstring | \"whose `limit` query parameter is \\\"48\\\" (the limit travels in the query string)\" | :125 | the limit sent only in the JSON body, or a different value in the query | CARRIED |\n| D7 | docstring | \"answered with 48 distinct rows in up-next mode, \u2026 exactly 8 `similar-card-item` anchors\" | :129 | a count of anything other than 8 anchors of that class | CARRIED |\n| D8 | docstring | \"they are the answer's first 8 rows in order\" | :131 | the last 8 rows, 8 rows in a shuffled order, or anchors with no `data-video-key` | CARRIED |\n| D9 | docstring | harness: \"filling the viewport never asks for more\" | :124 | a fill-viewport pass that sends a second batch request would fail the single-request check | CARRIED |\n| D10 | docstring | harness: `fetch` \"records each request's method, path, query and JSON body, answers `/recommendations` with the 48 rows and `{}` elsewhere\" | :116, :125 | a stub that records nothing: the control and the method/query checks read what it recorded | CARRIED |\n| N1 | name | \"the first batch\" | :124 | a page that has already requested a later batch by the time the test reads | CARRIED |\n| N2 | name | \"is one recommendations request\" | :124 | more than one request, or none | CARRIED |\n| N3 | name | \"for 48 rows\" | :125 | a limit other than 48 | CARRIED |\n| N4 | name | \"of which the first 8 are shown\" | :129, :131 | the wrong count, or the right count taken from the wrong rows | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase2.py:107\n   `rows = [... for i in range(ROWS)]`: the only answer tried has 48 rows. Nothing tests an answer at or below the display count: 0 rows (the code's `No similar videos found.` branch), 1 row, exactly 8, or 7. An implementation that pads to 8 or breaks on a short answer is not excluded.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase2.py:81\n   `fetch` always returns 200, so only the success path runs. The failure the page is built to handle is untested: a non-OK `/recommendations` response rendering the `.error` block, and a 401 rendering the key-rejected notice.\n3. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase2.py:87\n   The runner writes out `observed` (the observer targets) and records each request's `body`, and no assertion reads either. No rule is broken because the docstring does not claim anything from them. This is noted only because captured-but-unasserted output reads like coverage.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_frontend_video_page_similars.py (NEW), and that path does not resolve. Nothing in it could be read.\n2. `fixtures_path` was not supplied. The test uses only its own module fixture `bundle` (:92) and pytest's built-in `tmp_path_factory`, so no conftest was needed to judge independence.\n3. The docstring (:6) says the runner is \"the one in `tests/active/test_frontend_video_page.py`\". That file was not compared with `RUNNER`. It is a provenance claim, not a behavioural clause.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "the first `/recommendations` request is the one checked (no earlier or extra one)",
            "assertion": ":124",
            "excludes": "a page that sends a second batch request, e.g. the old limit-8 call plus a new limit-48 call",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "that request \"carries limit 48\"",
            "assertion": ":125",
            "excludes": "a request with `limit=8` (the current value), no limit, or the limit sent somewhere else",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "\"from a 48-row answer, `#similar-videos` holds exactly 8 cards\"",
            "assertion": ":129",
            "excludes": "a page that renders all 48 rows, or fewer than 8, into `#similar-videos`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"run in node with the real page module\"",
            "assertion": ":116",
            "excludes": "a runner where the bundled page never ran its loads, so a missing request reads as the page's fault",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"its first batch is one `/recommendations` request for 48 rows\"",
            "assertion": ":124, :125",
            "excludes": "several requests, or one request for a different number of rows",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"of which only the first 8 are shown\"",
            "assertion": ":129, :131",
            "excludes": "showing all rows, or showing 8 that are not the first 8",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"exactly one `/recommendations` request\"",
            "assertion": ":124",
            "excludes": "two or more requests, or none",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"a POST\"",
            "assertion": ":125",
            "excludes": "a GET to `/recommendations`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"whose `limit` query parameter is \\\"48\\\" (the limit travels in the query string)\"",
            "assertion": ":125",
            "excludes": "the limit sent only in the JSON body, or a different value in the query",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"answered with 48 distinct rows in up-next mode, \u2026 exactly 8 `similar-card-item` anchors\"",
            "assertion": ":129",
            "excludes": "a count of anything other than 8 anchors of that class",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"they are the answer's first 8 rows in order\"",
            "assertion": ":131",
            "excludes": "the last 8 rows, 8 rows in a shuffled order, or anchors with no `data-video-key`",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "harness: \"filling the viewport never asks for more\"",
            "assertion": ":124",
            "excludes": "a fill-viewport pass that sends a second batch request would fail the single-request check",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "harness: `fetch` \"records each request's method, path, query and JSON body, answers `/recommendations` with the 48 rows and `{}` elsewhere\"",
            "assertion": ":116, :125",
            "excludes": "a stub that records nothing: the control and the method/query checks read what it recorded",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"the first batch\"",
            "assertion": ":124",
            "excludes": "a page that has already requested a later batch by the time the test reads",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"is one recommendations request\"",
            "assertion": ":124",
            "excludes": "more than one request, or none",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"for 48 rows\"",
            "assertion": ":125",
            "excludes": "a limit other than 48",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"of which the first 8 are shown\"",
            "assertion": ":129, :131",
            "excludes": "the wrong count, or the right count taken from the wrong rows",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_12_similars_on_scroll_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:121\n   return [{\"video_id\": f\"{prefix}{i}\", \"instance_domain\": \"videos.example\"} for i in range(ROWS)]\n   Two values in this fixture are always equal, so the C2 checks cannot tell them apart. The fixture returns ROWS = 48 rows per batch (line 21). The page requests `limit: \"48\"` (client/frontend/src/pages/video-page/index.ts:308). So the number of rows fetched always equals the number requested. C2 says a refetch happens \"after all fetched rows are revealed\". The checks at lines 161 and 164 (`revealed[\"recommendations\"] == 1` then `len(recommendations) == 2`) and the exclude check at line 168 would also pass for a wrong implementation that refetches once it has shown the requested limit of 48, or after a fixed six intersections (48 / 8). This matches the entry's `<how_to_spot>` bullet \"A fixture whose two relevant values coincide\". The rule requires a batch whose row count differs from the requested limit, for example 20 rows. With 20 rows, the refetch must come after the second intersection and not the sixth. The exclude list at line 168 has the same gap: all 48 fetched rows are shown when it is checked, so \"rows shown\" and \"rows fetched\" cannot be told apart there either.\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 151, `assert first[\"inserts\"] - loaded[\"inserts\"] == 1`, with a difference of 0 and `sentinelObservers` 0. `loadSimilarVideos` (index.ts:292-327) renders the first 8 cards through `innerHTML` and never creates an IntersectionObserver on `#similar-sentinel`. So the runner has no observer to fire, and nothing is appended.\n\nNOT ASSESSED\n1. `code_under_test` lists client/frontend/video-page.html, client/frontend/src/video.css and tests/active/test_frontend_video_page_similars.py. I did not read these. The test inlines its own runner and does not import from the other test file, so the shape verdict does not depend on them.\n2. For `createFeedPager` in client/frontend/src/data/videos.ts, I only grepped for its signature and its exclude handling and did not read its full body. The exclude question was answered from the pager's documented contract (lines 31-38 and 130-134) together with the test's assertion form.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (17 clauses: 4 must_prove, 10 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a sentinel intersection appends the next 8 cards\" | :151, :153, :154 | no append on intersection; prepending (`afterbegin`); appending wrong rows, the wrong count, or the first 8 again | CARRIED |\n| C1b | must_prove | \"the cards already shown stay in place\" | :155, :156 | re-rendering the grid through `innerHTML`; reordering or replacing the first 8 cards | CARRIED |\n| C2a | must_prove | \"an intersection after all fetched rows are revealed sends another `/recommendations` request\" | :161, :164 | never fetching on exhaustion; fetching early, before all 48 are revealed | CARRIED |\n| C2b | must_prove | \"whose exclude list holds the rows already shown\" | :168 | a missing or empty `exclude`; a partial list (the 8 first shown); wrong ids or hosts; duplicates (length is pinned at 48) | CARRIED |\n| D1 | docstring | \"each sentinel intersection appends the next 8 of the fetched rows\" | :154, :160 | :154 checks only the first intersection. :160 checks only the total after five. Intersections 2\u20135 appending uneven chunks (8, 16, 16) or rewriting `innerHTML` still pass | UNCARRIED |\n| D2 | docstring | \"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\" | :161, :164, :168 | early fetch; no fetch; wrong exclude | CARRIED |\n| D3 | docstring | \"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\" | :151, :153 | zero or several inserts; the wrong position | CARRIED |\n| D4 | docstring | \"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\" | :154 | the wrong rows, count or order in the inserted markup | CARRIED |\n| D5 | docstring | \"`innerHTML` is never set again\" (scoped to the one-intersection bullet) | :155 | an `innerHTML` rewrite on the first intersection | CARRIED |\n| D6 | docstring | \"still begins with the first 8 cards unchanged\" | :156 | the first 8 cards changed or moved | CARRIED |\n| D7 | docstring | \"five intersections show all 48 rows\" | :160 | rows missing, duplicated or out of order after five | CARRIED |\n| D8 | docstring | \"without a second `/recommendations` request\" | :161 | fetching before all 48 are revealed | CARRIED |\n| D9 | docstring | \"the sixth sends one, a POST\" | :164, :166 | no second request; more than one; a GET | CARRIED |\n| D10 | docstring | \"whose `exclude` is exactly the first answer's 48 `{id, host}` pairs\" | :168 | a superset, subset or wrong pairs | CARRIED |\n| N1 | name | \"each sentinel intersection appends the next 8 rows\" | :154, :160 | same gap as D1: only the first intersection's append is pinned | UNCARRIED |\n| N2 | name | \"the one after all 48 asks for a batch\" | :161, :164 | an early or missing batch request | CARRIED |\n| N3 | name | \"excluding them\" | :168 | a wrong or missing exclude | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:160\n   `assert _keys(revealed[\"similar\"]) == [f\"v{i}\" for i in range(ROWS)]`\n   D1 and N1 say *each* intersection appends the next 8, which is an \"X per Y\" claim. Only the first intersection is checked per step (:151\u2013:156). Line 160 checks the total after five intersections, so it misses two things: intersections 2\u20135 appending uneven chunks, and a later intersection rewriting `innerHTML`. Checking inserts, writes and keys for every snapshot in `page[\"snapshots\"][1:6]` would carry the claim. Another fix is to narrow the name and docstring to the first intersection. The `must_prove` clause C1 is singular and is carried, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:21\n   Only a full 48-row batch, a multiple of 8, runs. Nothing covers a final chunk with fewer than 8 rows (for example 44 rows), a first batch of 8 or fewer, or an intersection when nothing remains to reveal.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:84\n   The runner configures a third answer with `{ rows: [] }`, but no test reaches it. Nothing covers what an intersection does after a batch that returns no rows, or after a failed `/recommendations` fetch. The shown cards should stay and no further requests should follow. Only the success path is covered.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `client/frontend/video-page.html` and `client/frontend/src/video.css` (both in `code_under_test`) were not read. The runner makes up any element id on demand (:66) and loads CSS with an empty loader (:111), so neither file reaches the test's assertions.\n2. `tests/active/test_frontend_video_page_similars.py` (in `code_under_test`) was not read. The docstring (:6) says this test's runner is based on that one, but this test has its own copy (:25\u2013:103), and that copy is what was judged. How faithful it is to the other file was not checked.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:121\n   return [{\"video_id\": f\"{prefix}{i}\", \"instance_domain\": \"videos.example\"} for i in range(ROWS)]\n   Two values in this fixture are always equal, so the C2 checks cannot tell them apart. The fixture returns ROWS = 48 rows per batch (line 21). The page requests `limit: \"48\"` (client/frontend/src/pages/video-page/index.ts:308). So the number of rows fetched always equals the number requested. C2 says a refetch happens \"after all fetched rows are revealed\". The checks at lines 161 and 164 (`revealed[\"recommendations\"] == 1` then `len(recommendations) == 2`) and the exclude check at line 168 would also pass for a wrong implementation that refetches once it has shown the requested limit of 48, or after a fixed six intersections (48 / 8). This matches the entry's `<how_to_spot>` bullet \"A fixture whose two relevant values coincide\". The rule requires a batch whose row count differs from the requested limit, for example 20 rows. With 20 rows, the refetch must come after the second intersection and not the sixth. The exclude list at line 168 has the same gap: all 48 fetched rows are shown when it is checked, so \"rows shown\" and \"rows fetched\" cannot be told apart there either.\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 151, `assert first[\"inserts\"] - loaded[\"inserts\"] == 1`, with a difference of 0 and `sentinelObservers` 0. `loadSimilarVideos` (index.ts:292-327) renders the first 8 cards through `innerHTML` and never creates an IntersectionObserver on `#similar-sentinel`. So the runner has no observer to fire, and nothing is appended.\n\nNOT ASSESSED\n1. `code_under_test` lists client/frontend/video-page.html, client/frontend/src/video.css and tests/active/test_frontend_video_page_similars.py. I did not read these. The test inlines its own runner and does not import from the other test file, so the shape verdict does not depend on them.\n2. For `createFeedPager` in client/frontend/src/data/videos.ts, I only grepped for its signature and its exclude handling and did not read its full body. The exclude question was answered from the pager's documented contract (lines 31-38 and 130-134) together with the test's assertion form.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (17 clauses: 4 must_prove, 10 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a sentinel intersection appends the next 8 cards\" | :151, :153, :154 | no append on intersection; prepending (`afterbegin`); appending wrong rows, the wrong count, or the first 8 again | CARRIED |\n| C1b | must_prove | \"the cards already shown stay in place\" | :155, :156 | re-rendering the grid through `innerHTML`; reordering or replacing the first 8 cards | CARRIED |\n| C2a | must_prove | \"an intersection after all fetched rows are revealed sends another `/recommendations` request\" | :161, :164 | never fetching on exhaustion; fetching early, before all 48 are revealed | CARRIED |\n| C2b | must_prove | \"whose exclude list holds the rows already shown\" | :168 | a missing or empty `exclude`; a partial list (the 8 first shown); wrong ids or hosts; duplicates (length is pinned at 48) | CARRIED |\n| D1 | docstring | \"each sentinel intersection appends the next 8 of the fetched rows\" | :154, :160 | :154 checks only the first intersection. :160 checks only the total after five. Intersections 2\u20135 appending uneven chunks (8, 16, 16) or rewriting `innerHTML` still pass | UNCARRIED |\n| D2 | docstring | \"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\" | :161, :164, :168 | early fetch; no fetch; wrong exclude | CARRIED |\n| D3 | docstring | \"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\" | :151, :153 | zero or several inserts; the wrong position | CARRIED |\n| D4 | docstring | \"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\" | :154 | the wrong rows, count or order in the inserted markup | CARRIED |\n| D5 | docstring | \"`innerHTML` is never set again\" (scoped to the one-intersection bullet) | :155 | an `innerHTML` rewrite on the first intersection | CARRIED |\n| D6 | docstring | \"still begins with the first 8 cards unchanged\" | :156 | the first 8 cards changed or moved | CARRIED |\n| D7 | docstring | \"five intersections show all 48 rows\" | :160 | rows missing, duplicated or out of order after five | CARRIED |\n| D8 | docstring | \"without a second `/recommendations` request\" | :161 | fetching before all 48 are revealed | CARRIED |\n| D9 | docstring | \"the sixth sends one, a POST\" | :164, :166 | no second request; more than one; a GET | CARRIED |\n| D10 | docstring | \"whose `exclude` is exactly the first answer's 48 `{id, host}` pairs\" | :168 | a superset, subset or wrong pairs | CARRIED |\n| N1 | name | \"each sentinel intersection appends the next 8 rows\" | :154, :160 | same gap as D1: only the first intersection's append is pinned | UNCARRIED |\n| N2 | name | \"the one after all 48 asks for a batch\" | :161, :164 | an early or missing batch request | CARRIED |\n| N3 | name | \"excluding them\" | :168 | a wrong or missing exclude | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:160\n   `assert _keys(revealed[\"similar\"]) == [f\"v{i}\" for i in range(ROWS)]`\n   D1 and N1 say *each* intersection appends the next 8, which is an \"X per Y\" claim. Only the first intersection is checked per step (:151\u2013:156). Line 160 checks the total after five intersections, so it misses two things: intersections 2\u20135 appending uneven chunks, and a later intersection rewriting `innerHTML`. Checking inserts, writes and keys for every snapshot in `page[\"snapshots\"][1:6]` would carry the claim. Another fix is to narrow the name and docstring to the first intersection. The `must_prove` clause C1 is singular and is carried, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:21\n   Only a full 48-row batch, a multiple of 8, runs. Nothing covers a final chunk with fewer than 8 rows (for example 44 rows), a first batch of 8 or fewer, or an intersection when nothing remains to reveal.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:84\n   The runner configures a third answer with `{ rows: [] }`, but no test reaches it. Nothing covers what an intersection does after a batch that returns no rows, or after a failed `/recommendations` fetch. The shown cards should stay and no further requests should follow. Only the success path is covered.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `client/frontend/video-page.html` and `client/frontend/src/video.css` (both in `code_under_test`) were not read. The runner makes up any element id on demand (:66) and loads CSS with an empty loader (:111), so neither file reaches the test's assertions.\n2. `tests/active/test_frontend_video_page_similars.py` (in `code_under_test`) was not read. The docstring (:6) says this test's runner is based on that one, but this test has its own copy (:25\u2013:103), and that copy is what was judged. How faithful it is to the other file was not checked.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a sentinel intersection appends the next 8 cards\"",
            "assertion": ":151, :153, :154",
            "excludes": "no append on intersection; prepending (`afterbegin`); appending wrong rows, the wrong count, or the first 8 again",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"the cards already shown stay in place\"",
            "assertion": ":155, :156",
            "excludes": "re-rendering the grid through `innerHTML`; reordering or replacing the first 8 cards",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"an intersection after all fetched rows are revealed sends another `/recommendations` request\"",
            "assertion": ":161, :164",
            "excludes": "never fetching on exhaustion; fetching early, before all 48 are revealed",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"whose exclude list holds the rows already shown\"",
            "assertion": ":168",
            "excludes": "a missing or empty `exclude`; a partial list (the 8 first shown); wrong ids or hosts; duplicates (length is pinned at 48)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"each sentinel intersection appends the next 8 of the fetched rows\"",
            "assertion": ":154, :160",
            "excludes": ":154 checks only the first intersection. :160 checks only the total after five. Intersections 2\u20135 appending uneven chunks (8, 16, 16) or rewriting `innerHTML` still pass",
            "status": "UNCARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\"",
            "assertion": ":161, :164, :168",
            "excludes": "early fetch; no fetch; wrong exclude",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\"",
            "assertion": ":151, :153",
            "excludes": "zero or several inserts; the wrong position",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\"",
            "assertion": ":154",
            "excludes": "the wrong rows, count or order in the inserted markup",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"`innerHTML` is never set again\" (scoped to the one-intersection bullet)",
            "assertion": ":155",
            "excludes": "an `innerHTML` rewrite on the first intersection",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"still begins with the first 8 cards unchanged\"",
            "assertion": ":156",
            "excludes": "the first 8 cards changed or moved",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"five intersections show all 48 rows\"",
            "assertion": ":160",
            "excludes": "rows missing, duplicated or out of order after five",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"without a second `/recommendations` request\"",
            "assertion": ":161",
            "excludes": "fetching before all 48 are revealed",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"the sixth sends one, a POST\"",
            "assertion": ":164, :166",
            "excludes": "no second request; more than one; a GET",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"whose `exclude` is exactly the first answer's 48 `{id, host}` pairs\"",
            "assertion": ":168",
            "excludes": "a superset, subset or wrong pairs",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"each sentinel intersection appends the next 8 rows\"",
            "assertion": ":154, :160",
            "excludes": "same gap as D1: only the first intersection's append is pinned",
            "status": "UNCARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"the one after all 48 asks for a batch\"",
            "assertion": ":161, :164",
            "excludes": "an early or missing batch request",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"excluding them\"",
            "assertion": ":168",
            "excludes": "a wrong or missing exclude",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test should fail at tests/tmp/test_12_similars_on_scroll_phase3.py:152, on `assert first[\"inserts\"] - loaded[\"inserts\"] == 1`, with a difference of 0 and `\"sentinel observers\": 0`. index.ts has no `IntersectionObserver` and no `similar-sentinel`, so `watching` is empty and the first intersection never appends. The control assertions at :135 and :149 should pass first: `loadSimilarVideos` already sends one `/recommendations` POST and renders v0\u2013v7, with keys `videos.example::v0\u2026`, through `innerHTML`.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The only fixture used, `bundle`, is defined in the test file at :107\u2013118, so nothing is missing.\n2. client/frontend/src/video.css was checked only for \"similar\" (14 matches), not read in full. It is loaded through `--loader:.css=empty` and no assertion touches it.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (20 clauses: 6 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a sentinel intersection appends the next 8 cards\" (first intersection) | :152, :154, :155 | a re-render in place of an append, a prepend, a chunk other than rows v8-v15, more than one insert | CARRIED |\n| C1b | must_prove | the same holds for each later intersection: every one adds the next 8 (8 per intersection, second case) | none | :161 checks only the total after five intersections, so a page that shows all 32 remaining rows on the second intersection, and nothing on the third to fifth, still passes | UNCARRIED |\n| C1c | must_prove | \"the cards already shown stay in place\" | :156, :157, :161, :162 | the grid rebuilt through `innerHTML`, first 8 cards changed or reordered, earlier cards lost by the time all 48 show | CARRIED |\n| C2a | must_prove | the request comes only \"after all fetched rows are revealed\" | :163 | fetching the next batch before all 48 rows are shown | CARRIED |\n| C2b | must_prove | that intersection \"sends another `/recommendations` request\" | :166 | no fetch on the intersection after all rows are shown | CARRIED |\n| C2c | must_prove | \"whose exclude list holds the rows already shown\" | :170 | an empty or missing exclude, a partial list, wrong id/host fields, extra entries | CARRIED |\n| D1a | docstring | \"each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`\" (first) | :155 | a wrong or wrong-sized first chunk | CARRIED |\n| D1b | docstring | \"each\" (intersections 2-5 each add 8) | none | only the total is checked (:161), so the chunk size is never checked after the first intersection | UNCARRIED |\n| D2 | docstring | \"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\" | :166, :170 | no refetch, or a refetch without the shown rows excluded | CARRIED |\n| D3 | docstring | \"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\" | :152, :154 | several inserts, \"afterbegin\" | CARRIED |\n| D4 | docstring | \"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\" | :155 | wrong count, wrong rows, wrong order | CARRIED |\n| D5 | docstring | \"`innerHTML` is not set again through the five intersections\" | :156, :162 | any `innerHTML` rewrite of the grid through snapshot 5 | CARRIED |\n| D6 | docstring | \"after the first it still begins with the first 8 cards unchanged\" | :157 | first 8 cards replaced or altered | CARRIED |\n| D7 | docstring | \"Five intersections show all 48 rows in order\" | :161 | missing, repeated or out-of-order rows after five | CARRIED |\n| D8 | docstring | \"without a second `/recommendations` request\" | :163 | early prefetch | CARRIED |\n| D9 | docstring | \"the sixth sends one, a POST\" | :166, :168 | no sixth-intersection request; a GET | CARRIED |\n| D10 | docstring | \"`exclude` is exactly the first answer's 48 `{id, host}` pairs\" | :170 | wrong length, duplicates, wrong key names, wrong values | CARRIED |\n| D11 | docstring | \"Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel\" | :152 (with runner :92-98) | an observer on some other element, which is never fired, so no append | CARRIED |\n| N1a | name | \"each sentinel intersection appends the next 8 rows\" (first) | :155 | wrong first chunk | CARRIED |\n| N1b | name | \"each\" (every intersection adds exactly 8) | none | only the total is checked (:161) | UNCARRIED |\n| N2 | name | \"the one after all 48 asks for a batch excluding them\" | :166, :170 | no refetch; exclude not equal to the 48 shown | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:161\n   assert _keys(revealed[\"similar\"]) == [f\"v{i}\" for i in range(ROWS)], _keys(revealed[\"similar\"])  # C1\n   C1 is a per-intersection claim: each sentinel intersection adds the next 8 cards. `<whole-claim>` says a claim of the form \"X per Y needs a second Y or it proves only X\". The test checks the chunk for the first intersection only (:155). For intersections 2-5 it checks just the combined grid after the fifth (:161), plus no `innerHTML` writes (:162) and one request so far (:163). A page that shows all 32 remaining rows on the second intersection and nothing on the third to fifth passes all of those. The rule requires the second and later intersections to be checked one at a time. `page[\"snapshots\"][2..5]` and `page[\"inserts\"]` are already captured, but nothing checks each step's 8 keys.\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:98\n   The runner only ever fires `[{ isIntersecting: true }]`. A page that appends on any observer callback, including the sentinel leaving view (`isIntersecting: false`), passes. No test covers the non-intersecting path.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:122\n   The first answer is always 48 rows, an exact multiple of 8. A final partial chunk (e.g. 45 rows), a first answer shorter than 8, and an empty second answer are all untested. The runner feeds a second answer (w0-w47, docstring :7), but nothing checks what happens with it.\n3. whole-claim / name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:144, :1\n   D1b and N1b are UNCARRIED for the reason given in Critical 1. Both the name and the docstring say \"each\", and only the first intersection is checked on its own.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `client/frontend/src/pages/video-page/index.ts` and `client/frontend/video-page.html` as read have no `similar-sentinel` element, no `IntersectionObserver`, and no append path. `loadSimilarVideos` sets `innerHTML` once with the first 8 rows and stops. The clauses were judged against what the test asserts. Whether it currently runs red was not checked, because nothing was executed.\n2. `client/frontend/src/video.css` was not read. It has no bearing on the claim criteria.\n3. `fixtures_path` was not supplied. The only fixture, `bundle`, is defined in the test file (:107), so no conftest was needed.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test should fail at tests/tmp/test_12_similars_on_scroll_phase3.py:152, on `assert first[\"inserts\"] - loaded[\"inserts\"] == 1`, with a difference of 0 and `\"sentinel observers\": 0`. index.ts has no `IntersectionObserver` and no `similar-sentinel`, so `watching` is empty and the first intersection never appends. The control assertions at :135 and :149 should pass first: `loadSimilarVideos` already sends one `/recommendations` POST and renders v0\u2013v7, with keys `videos.example::v0\u2026`, through `innerHTML`.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The only fixture used, `bundle`, is defined in the test file at :107\u2013118, so nothing is missing.\n2. client/frontend/src/video.css was checked only for \"similar\" (14 matches), not read in full. It is loaded through `--loader:.css=empty` and no assertion touches it.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (20 clauses: 6 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a sentinel intersection appends the next 8 cards\" (first intersection) | :152, :154, :155 | a re-render in place of an append, a prepend, a chunk other than rows v8-v15, more than one insert | CARRIED |\n| C1b | must_prove | the same holds for each later intersection: every one adds the next 8 (8 per intersection, second case) | none | :161 checks only the total after five intersections, so a page that shows all 32 remaining rows on the second intersection, and nothing on the third to fifth, still passes | UNCARRIED |\n| C1c | must_prove | \"the cards already shown stay in place\" | :156, :157, :161, :162 | the grid rebuilt through `innerHTML`, first 8 cards changed or reordered, earlier cards lost by the time all 48 show | CARRIED |\n| C2a | must_prove | the request comes only \"after all fetched rows are revealed\" | :163 | fetching the next batch before all 48 rows are shown | CARRIED |\n| C2b | must_prove | that intersection \"sends another `/recommendations` request\" | :166 | no fetch on the intersection after all rows are shown | CARRIED |\n| C2c | must_prove | \"whose exclude list holds the rows already shown\" | :170 | an empty or missing exclude, a partial list, wrong id/host fields, extra entries | CARRIED |\n| D1a | docstring | \"each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`\" (first) | :155 | a wrong or wrong-sized first chunk | CARRIED |\n| D1b | docstring | \"each\" (intersections 2-5 each add 8) | none | only the total is checked (:161), so the chunk size is never checked after the first intersection | UNCARRIED |\n| D2 | docstring | \"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\" | :166, :170 | no refetch, or a refetch without the shown rows excluded | CARRIED |\n| D3 | docstring | \"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\" | :152, :154 | several inserts, \"afterbegin\" | CARRIED |\n| D4 | docstring | \"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\" | :155 | wrong count, wrong rows, wrong order | CARRIED |\n| D5 | docstring | \"`innerHTML` is not set again through the five intersections\" | :156, :162 | any `innerHTML` rewrite of the grid through snapshot 5 | CARRIED |\n| D6 | docstring | \"after the first it still begins with the first 8 cards unchanged\" | :157 | first 8 cards replaced or altered | CARRIED |\n| D7 | docstring | \"Five intersections show all 48 rows in order\" | :161 | missing, repeated or out-of-order rows after five | CARRIED |\n| D8 | docstring | \"without a second `/recommendations` request\" | :163 | early prefetch | CARRIED |\n| D9 | docstring | \"the sixth sends one, a POST\" | :166, :168 | no sixth-intersection request; a GET | CARRIED |\n| D10 | docstring | \"`exclude` is exactly the first answer's 48 `{id, host}` pairs\" | :170 | wrong length, duplicates, wrong key names, wrong values | CARRIED |\n| D11 | docstring | \"Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel\" | :152 (with runner :92-98) | an observer on some other element, which is never fired, so no append | CARRIED |\n| N1a | name | \"each sentinel intersection appends the next 8 rows\" (first) | :155 | wrong first chunk | CARRIED |\n| N1b | name | \"each\" (every intersection adds exactly 8) | none | only the total is checked (:161) | UNCARRIED |\n| N2 | name | \"the one after all 48 asks for a batch excluding them\" | :166, :170 | no refetch; exclude not equal to the 48 shown | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:161\n   assert _keys(revealed[\"similar\"]) == [f\"v{i}\" for i in range(ROWS)], _keys(revealed[\"similar\"])  # C1\n   C1 is a per-intersection claim: each sentinel intersection adds the next 8 cards. `<whole-claim>` says a claim of the form \"X per Y needs a second Y or it proves only X\". The test checks the chunk for the first intersection only (:155). For intersections 2-5 it checks just the combined grid after the fifth (:161), plus no `innerHTML` writes (:162) and one request so far (:163). A page that shows all 32 remaining rows on the second intersection and nothing on the third to fifth passes all of those. The rule requires the second and later intersections to be checked one at a time. `page[\"snapshots\"][2..5]` and `page[\"inserts\"]` are already captured, but nothing checks each step's 8 keys.\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:98\n   The runner only ever fires `[{ isIntersecting: true }]`. A page that appends on any observer callback, including the sentinel leaving view (`isIntersecting: false`), passes. No test covers the non-intersecting path.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:122\n   The first answer is always 48 rows, an exact multiple of 8. A final partial chunk (e.g. 45 rows), a first answer shorter than 8, and an empty second answer are all untested. The runner feeds a second answer (w0-w47, docstring :7), but nothing checks what happens with it.\n3. whole-claim / name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_12_similars_on_scroll_phase3.py:144, :1\n   D1b and N1b are UNCARRIED for the reason given in Critical 1. Both the name and the docstring say \"each\", and only the first intersection is checked on its own.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `client/frontend/src/pages/video-page/index.ts` and `client/frontend/video-page.html` as read have no `similar-sentinel` element, no `IntersectionObserver`, and no append path. `loadSimilarVideos` sets `innerHTML` once with the first 8 rows and stops. The clauses were judged against what the test asserts. Whether it currently runs red was not checked, because nothing was executed.\n2. `client/frontend/src/video.css` was not read. It has no bearing on the claim criteria.\n3. `fixtures_path` was not supplied. The only fixture, `bundle`, is defined in the test file (:107), so no conftest was needed.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a sentinel intersection appends the next 8 cards\" (first intersection)",
            "assertion": ":152, :154, :155",
            "excludes": "a re-render in place of an append, a prepend, a chunk other than rows v8-v15, more than one insert",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the same holds for each later intersection: every one adds the next 8 (8 per intersection, second case)",
            "assertion": "none",
            "excludes": ":161 checks only the total after five intersections, so a page that shows all 32 remaining rows on the second intersection, and nothing on the third to fifth, still passes",
            "status": "UNCARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"the cards already shown stay in place\"",
            "assertion": ":156, :157, :161, :162",
            "excludes": "the grid rebuilt through `innerHTML`, first 8 cards changed or reordered, earlier cards lost by the time all 48 show",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "the request comes only \"after all fetched rows are revealed\"",
            "assertion": ":163",
            "excludes": "fetching the next batch before all 48 rows are shown",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "that intersection \"sends another `/recommendations` request\"",
            "assertion": ":166",
            "excludes": "no fetch on the intersection after all rows are shown",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"whose exclude list holds the rows already shown\"",
            "assertion": ":170",
            "excludes": "an empty or missing exclude, a partial list, wrong id/host fields, extra entries",
            "status": "CARRIED"
          },
          {
            "id": "D1a",
            "source": "docstring",
            "clause": "\"each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`\" (first)",
            "assertion": ":155",
            "excludes": "a wrong or wrong-sized first chunk",
            "status": "CARRIED"
          },
          {
            "id": "D1b",
            "source": "docstring",
            "clause": "\"each\" (intersections 2-5 each add 8)",
            "assertion": "none",
            "excludes": "only the total is checked (:161), so the chunk size is never checked after the first intersection",
            "status": "UNCARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\"",
            "assertion": ":166, :170",
            "excludes": "no refetch, or a refetch without the shown rows excluded",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\"",
            "assertion": ":152, :154",
            "excludes": "several inserts, \"afterbegin\"",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\"",
            "assertion": ":155",
            "excludes": "wrong count, wrong rows, wrong order",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"`innerHTML` is not set again through the five intersections\"",
            "assertion": ":156, :162",
            "excludes": "any `innerHTML` rewrite of the grid through snapshot 5",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"after the first it still begins with the first 8 cards unchanged\"",
            "assertion": ":157",
            "excludes": "first 8 cards replaced or altered",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"Five intersections show all 48 rows in order\"",
            "assertion": ":161",
            "excludes": "missing, repeated or out-of-order rows after five",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"without a second `/recommendations` request\"",
            "assertion": ":163",
            "excludes": "early prefetch",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"the sixth sends one, a POST\"",
            "assertion": ":166, :168",
            "excludes": "no sixth-intersection request; a GET",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"`exclude` is exactly the first answer's 48 `{id, host}` pairs\"",
            "assertion": ":170",
            "excludes": "wrong length, duplicates, wrong key names, wrong values",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel\"",
            "assertion": ":152 (with runner :92-98)",
            "excludes": "an observer on some other element, which is never fired, so no append",
            "status": "CARRIED"
          },
          {
            "id": "N1a",
            "source": "name",
            "clause": "\"each sentinel intersection appends the next 8 rows\" (first)",
            "assertion": ":155",
            "excludes": "wrong first chunk",
            "status": "CARRIED"
          },
          {
            "id": "N1b",
            "source": "name",
            "clause": "\"each\" (every intersection adds exactly 8)",
            "assertion": "none",
            "excludes": "only the total is checked (:161)",
            "status": "UNCARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"the one after all 48 asks for a batch excluding them\"",
            "assertion": ":166, :170",
            "excludes": "no refetch; exclude not equal to the 48 shown",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 152 on `assert first[\"inserts\"] - loaded[\"inserts\"] == 1`, with inserts\n(n, n) and \"sentinel observers\": 0. index.ts has no `similar-sentinel` and no\n`IntersectionObserver`, so the runner has no observer to fire and nothing is appended\nto `#similar-videos`.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The only fixture the test uses, `bundle`\n   (tests/tmp/test_12_similars_on_scroll_phase3.py:107), is defined in the file, so no\n   conftest was needed.\n2. client/frontend/video-page.html, client/frontend/src/video.css and\n   tests/active/test_frontend_video_page_similars.py in `code_under_test` were not read.\n   The test does not load the HTML or CSS: the bundle loads `.css` as empty, and\n   `getElementById` makes up elements. The test copies the other file's runner inline\n   instead of importing it. The stub question was answered from index.ts and\n   src/data/videos.ts (createFeedPager, fetchSimilarVideosPayload, MAX_FEED_EXCLUDE = 500).\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (21 clauses: 6 must_prove, 12 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a sentinel intersection appends the next 8 cards\" (first intersection) | :152, :154, :155 | a re-render instead of an append, a prepend, a chunk other than rows v8-v15, more than one insert | CARRIED |\n| C1b | must_prove | the same holds for each later intersection: every one adds the next 8 (8 per intersection, second case) | :162 | for k = 2..5, a step with other than one insert, or whose grid is not exactly v0..v(8(k+1)-1). So a page that shows all 32 remaining rows at step 2, or any chunk other than 8, fails at that step | CARRIED |\n| C1c | must_prove | \"the cards already shown stay in place\" | :156, :157, :162, :166, :167 | the grid rebuilt through `innerHTML` at any point up to snapshot 5 (the write counter only goes up), the first 8 cards changed or reordered, earlier cards lost or reordered at any step | CARRIED |\n| C2a | must_prove | the request comes only \"after all fetched rows are revealed\" | :168 | fetching the next batch before all 48 rows are shown | CARRIED |\n| C2b | must_prove | that intersection \"sends another `/recommendations` request\" | :171 | no fetch on the sixth intersection | CARRIED |\n| C2c | must_prove | \"whose exclude list holds the rows already shown\" | :175 | an empty or missing exclude, a partial list, duplicates (length is pinned at 48), wrong `id`/`host` fields, extra entries | CARRIED |\n| D1a | docstring | \"each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`\" (first) | :155 | a wrong or wrong-sized first chunk | CARRIED |\n| D1b | docstring | \"each\" (intersections 2-5 each add 8) | :162 | a chunk size other than 8 at any step from 2 to 5 | CARRIED |\n| D2 | docstring | \"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\" | :171, :175 | no refetch, or a refetch without the shown rows excluded | CARRIED |\n| D3 | docstring | \"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\" | :152, :154 | several inserts, \"afterbegin\" | CARRIED |\n| D4 | docstring | \"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\" | :155 | wrong count, wrong rows, wrong order | CARRIED |\n| D5 | docstring | \"`innerHTML` is not set again through the five intersections\" | :156, :167 | any `innerHTML` rewrite of the grid through snapshot 5 | CARRIED |\n| D6 | docstring | \"after the first it still begins with the first 8 cards unchanged\" | :157 | first 8 cards replaced or altered | CARRIED |\n| D7 | docstring | \"Five intersections show all 48 rows in order\" | :166 | missing, repeated or out-of-order rows after five | CARRIED |\n| D8 | docstring | \"without a second `/recommendations` request\" | :168 | an early prefetch | CARRIED |\n| D9 | docstring | \"the sixth sends one, a POST\" | :171, :173 | no request on the sixth intersection; a GET | CARRIED |\n| D10 | docstring | \"`exclude` is exactly the first answer's 48 `{id, host}` pairs\" | :175 | wrong length, duplicates, wrong key names, wrong values | CARRIED |\n| D11 | docstring | \"Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel\" | :152 (with runner :92-98) | an observer on some other element, which is never fired, so no append happens | CARRIED |\n| N1a | name | \"each sentinel intersection appends the next 8 rows\" (first) | :155 | a wrong first chunk | CARRIED |\n| N1b | name | \"each\" (every intersection adds exactly 8) | :162 | a chunk other than 8 at steps 2-5 | CARRIED |\n| N2 | name | \"the one after all 48 asks for a batch excluding them\" | :171, :175 | no refetch; exclude not equal to the 48 shown | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. C1b, D1b and N1b are now carried by a new assertion at tests/tmp/test_12_similars_on_scroll_phase3.py:162, which checks each step from 2 to 5. The author added an assertion; the prose was not narrowed.\n2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_12_similars_on_scroll_phase3.py:171-175. Only the success path of the refetch runs. The runner's docstring says a third request gets an empty answer (:7), but only six intersections run, so it is never reached. A failed or empty second `/recommendations` answer is never exercised, and neither is what the sentinel does after one. No ledger row names this, so it does not block.\n3. bounds (rules/testing.md): tests/tmp/test_12_similars_on_scroll_phase3.py:22. `ROWS = 48` is a multiple of `SHOWN = 8`, so every chunk is full. A batch whose last chunk is short, such as 44 rows, is never exercised. The same goes for a batch of 8 or fewer rows, where the first intersection has no row left to reveal and should go straight to the refetch. No ledger row names this, so it does not block.\n\nNOT ASSESSED\n1. client/frontend/video-page.html, client/frontend/src/video.css and tests/active/test_frontend_video_page_similars.py from `code_under_test` were not read. The runner copied from the last of these is inlined in the test (:26-104) and was judged there. In index.ts only the similars loader (:289-327) was read, plus a search for the names the test depends on. `createFeedPager` and `fetchSimilarVideosPayload` in client/frontend/src/data/videos.ts were located but not read, so the exclude payload's key names (`id`/`host`) were taken from the docstring and :175 rather than checked against the code.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 152 on `assert first[\"inserts\"] - loaded[\"inserts\"] == 1`, with inserts\n(n, n) and \"sentinel observers\": 0. index.ts has no `similar-sentinel` and no\n`IntersectionObserver`, so the runner has no observer to fire and nothing is appended\nto `#similar-videos`.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The only fixture the test uses, `bundle`\n   (tests/tmp/test_12_similars_on_scroll_phase3.py:107), is defined in the file, so no\n   conftest was needed.\n2. client/frontend/video-page.html, client/frontend/src/video.css and\n   tests/active/test_frontend_video_page_similars.py in `code_under_test` were not read.\n   The test does not load the HTML or CSS: the bundle loads `.css` as empty, and\n   `getElementById` makes up elements. The test copies the other file's runner inline\n   instead of importing it. The stub question was answered from index.ts and\n   src/data/videos.ts (createFeedPager, fetchSimilarVideosPayload, MAX_FEED_EXCLUDE = 500).\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (21 clauses: 6 must_prove, 12 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"a sentinel intersection appends the next 8 cards\" (first intersection) | :152, :154, :155 | a re-render instead of an append, a prepend, a chunk other than rows v8-v15, more than one insert | CARRIED |\n| C1b | must_prove | the same holds for each later intersection: every one adds the next 8 (8 per intersection, second case) | :162 | for k = 2..5, a step with other than one insert, or whose grid is not exactly v0..v(8(k+1)-1). So a page that shows all 32 remaining rows at step 2, or any chunk other than 8, fails at that step | CARRIED |\n| C1c | must_prove | \"the cards already shown stay in place\" | :156, :157, :162, :166, :167 | the grid rebuilt through `innerHTML` at any point up to snapshot 5 (the write counter only goes up), the first 8 cards changed or reordered, earlier cards lost or reordered at any step | CARRIED |\n| C2a | must_prove | the request comes only \"after all fetched rows are revealed\" | :168 | fetching the next batch before all 48 rows are shown | CARRIED |\n| C2b | must_prove | that intersection \"sends another `/recommendations` request\" | :171 | no fetch on the sixth intersection | CARRIED |\n| C2c | must_prove | \"whose exclude list holds the rows already shown\" | :175 | an empty or missing exclude, a partial list, duplicates (length is pinned at 48), wrong `id`/`host` fields, extra entries | CARRIED |\n| D1a | docstring | \"each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`\" (first) | :155 | a wrong or wrong-sized first chunk | CARRIED |\n| D1b | docstring | \"each\" (intersections 2-5 each add 8) | :162 | a chunk size other than 8 at any step from 2 to 5 | CARRIED |\n| D2 | docstring | \"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\" | :171, :175 | no refetch, or a refetch without the shown rows excluded | CARRIED |\n| D3 | docstring | \"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\" | :152, :154 | several inserts, \"afterbegin\" | CARRIED |\n| D4 | docstring | \"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\" | :155 | wrong count, wrong rows, wrong order | CARRIED |\n| D5 | docstring | \"`innerHTML` is not set again through the five intersections\" | :156, :167 | any `innerHTML` rewrite of the grid through snapshot 5 | CARRIED |\n| D6 | docstring | \"after the first it still begins with the first 8 cards unchanged\" | :157 | first 8 cards replaced or altered | CARRIED |\n| D7 | docstring | \"Five intersections show all 48 rows in order\" | :166 | missing, repeated or out-of-order rows after five | CARRIED |\n| D8 | docstring | \"without a second `/recommendations` request\" | :168 | an early prefetch | CARRIED |\n| D9 | docstring | \"the sixth sends one, a POST\" | :171, :173 | no request on the sixth intersection; a GET | CARRIED |\n| D10 | docstring | \"`exclude` is exactly the first answer's 48 `{id, host}` pairs\" | :175 | wrong length, duplicates, wrong key names, wrong values | CARRIED |\n| D11 | docstring | \"Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel\" | :152 (with runner :92-98) | an observer on some other element, which is never fired, so no append happens | CARRIED |\n| N1a | name | \"each sentinel intersection appends the next 8 rows\" (first) | :155 | a wrong first chunk | CARRIED |\n| N1b | name | \"each\" (every intersection adds exactly 8) | :162 | a chunk other than 8 at steps 2-5 | CARRIED |\n| N2 | name | \"the one after all 48 asks for a batch excluding them\" | :171, :175 | no refetch; exclude not equal to the 48 shown | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. C1b, D1b and N1b are now carried by a new assertion at tests/tmp/test_12_similars_on_scroll_phase3.py:162, which checks each step from 2 to 5. The author added an assertion; the prose was not narrowed.\n2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_12_similars_on_scroll_phase3.py:171-175. Only the success path of the refetch runs. The runner's docstring says a third request gets an empty answer (:7), but only six intersections run, so it is never reached. A failed or empty second `/recommendations` answer is never exercised, and neither is what the sentinel does after one. No ledger row names this, so it does not block.\n3. bounds (rules/testing.md): tests/tmp/test_12_similars_on_scroll_phase3.py:22. `ROWS = 48` is a multiple of `SHOWN = 8`, so every chunk is full. A batch whose last chunk is short, such as 44 rows, is never exercised. The same goes for a batch of 8 or fewer rows, where the first intersection has no row left to reveal and should go straight to the refetch. No ledger row names this, so it does not block.\n\nNOT ASSESSED\n1. client/frontend/video-page.html, client/frontend/src/video.css and tests/active/test_frontend_video_page_similars.py from `code_under_test` were not read. The runner copied from the last of these is inlined in the test (:26-104) and was judged there. In index.ts only the similars loader (:289-327) was read, plus a search for the names the test depends on. `createFeedPager` and `fetchSimilarVideosPayload` in client/frontend/src/data/videos.ts were located but not read, so the exclude payload's key names (`id`/`host`) were taken from the docstring and :175 rather than checked against the code.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"a sentinel intersection appends the next 8 cards\" (first intersection)",
            "assertion": ":152, :154, :155",
            "excludes": "a re-render instead of an append, a prepend, a chunk other than rows v8-v15, more than one insert",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the same holds for each later intersection: every one adds the next 8 (8 per intersection, second case)",
            "assertion": ":162",
            "excludes": "for k = 2..5, a step with other than one insert, or whose grid is not exactly v0..v(8(k+1)-1). So a page that shows all 32 remaining rows at step 2, or any chunk other than 8, fails at that step",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"the cards already shown stay in place\"",
            "assertion": ":156, :157, :162, :166, :167",
            "excludes": "the grid rebuilt through `innerHTML` at any point up to snapshot 5 (the write counter only goes up), the first 8 cards changed or reordered, earlier cards lost or reordered at any step",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "the request comes only \"after all fetched rows are revealed\"",
            "assertion": ":168",
            "excludes": "fetching the next batch before all 48 rows are shown",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "that intersection \"sends another `/recommendations` request\"",
            "assertion": ":171",
            "excludes": "no fetch on the sixth intersection",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"whose exclude list holds the rows already shown\"",
            "assertion": ":175",
            "excludes": "an empty or missing exclude, a partial list, duplicates (length is pinned at 48), wrong `id`/`host` fields, extra entries",
            "status": "CARRIED"
          },
          {
            "id": "D1a",
            "source": "docstring",
            "clause": "\"each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`\" (first)",
            "assertion": ":155",
            "excludes": "a wrong or wrong-sized first chunk",
            "status": "CARRIED"
          },
          {
            "id": "D1b",
            "source": "docstring",
            "clause": "\"each\" (intersections 2-5 each add 8)",
            "assertion": ":162",
            "excludes": "a chunk size other than 8 at any step from 2 to 5",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"an intersection once all 48 are shown asks for the next batch, excluding the rows shown\"",
            "assertion": ":171, :175",
            "excludes": "no refetch, or a refetch without the shown rows excluded",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"exactly one `insertAdjacentHTML(\"beforeend\", \u2026)` call on `#similar-videos`\"",
            "assertion": ":152, :154",
            "excludes": "several inserts, \"afterbegin\"",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer\"",
            "assertion": ":155",
            "excludes": "wrong count, wrong rows, wrong order",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"`innerHTML` is not set again through the five intersections\"",
            "assertion": ":156, :167",
            "excludes": "any `innerHTML` rewrite of the grid through snapshot 5",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"after the first it still begins with the first 8 cards unchanged\"",
            "assertion": ":157",
            "excludes": "first 8 cards replaced or altered",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"Five intersections show all 48 rows in order\"",
            "assertion": ":166",
            "excludes": "missing, repeated or out-of-order rows after five",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"without a second `/recommendations` request\"",
            "assertion": ":168",
            "excludes": "an early prefetch",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"the sixth sends one, a POST\"",
            "assertion": ":171, :173",
            "excludes": "no request on the sixth intersection; a GET",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"`exclude` is exactly the first answer's 48 `{id, host}` pairs\"",
            "assertion": ":175",
            "excludes": "wrong length, duplicates, wrong key names, wrong values",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel\"",
            "assertion": ":152 (with runner :92-98)",
            "excludes": "an observer on some other element, which is never fired, so no append happens",
            "status": "CARRIED"
          },
          {
            "id": "N1a",
            "source": "name",
            "clause": "\"each sentinel intersection appends the next 8 rows\" (first)",
            "assertion": ":155",
            "excludes": "a wrong first chunk",
            "status": "CARRIED"
          },
          {
            "id": "N1b",
            "source": "name",
            "clause": "\"each\" (every intersection adds exactly 8)",
            "assertion": ":162",
            "excludes": "a chunk other than 8 at steps 2-5",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"the one after all 48 asks for a batch excluding them\"",
            "assertion": ":171, :175",
            "excludes": "no refetch; exclude not equal to the 48 shown",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  }
}
```
dev-flow:state -->

## Entries from earlier runs of this build

## 2026-09-28 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/12",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 25 test groups (24 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.0s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

The issue asks to "remove the separate similar videos page", but the operator chose links only (R5): `/videos.html?id=…` (`useSimilar` in `client/frontend/src/pages/videos/index.ts`) keeps working, and only the two links to it are removed. This is resolved by the operator's decision and recorded here so later steps do not delete the mode.
The retired `test_frontend_videos.py` paged 8-row batches and asserted that two plain fetches return the same page (its line 97). Under 09's random draw and a pool of up to 300 rows, that control fails and 6 batches of 8 never reach an empty batch. R6's replacement must drop that control and size its batch budget for 48-row batches.

## 2026-09-28 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-09-28 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


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


### docs_checklist

<doc path="client/frontend/README.md">
Under "What it does", after line 13, add a bullet: the video page's similar section fetches one 48-row up-next batch through `createFeedPager`, reveals 8 cards at a time as scrolling nears the bottom, and fetches the next batch, excluding the rows already shown, when the revealed rows run out. Paging ends after an empty or failed batch, and a later failure is only logged. Line 9 ("similar to one video") can stay, since `/videos.html?id=` still works. Line 10's feed-paging bullet can say that the video page uses the same pager.
</doc>
<doc path="DEPLOYMENT.md">
In "Up-next logs and load" (lines 253-260), note that one video page view now sends a sequence of up-next requests as the visitor scrolls: a 48-row batch each, carrying `exclude`, up to about 7 before a 300-row pool runs out. Once the unshown pool drops below 48 rows, each of these runs the ANN fallback. That multiplies the per-page-view `index_lock` load that the capacity paragraph describes.
</doc>
<doc path="docs/project/issues/35-upnext-tests-retired-by-random-draw.md">
Add a comment recording that `tests/active/test_frontend_upnext_pager.py` from build 12 replaces the `test_frontend_videos` item: 48-row batches, no plain-fetch control, 10-batch budget, empty batch reached because the Engine takes the top 300 before excluding. Mark line 17 as covered and leave the other five items and the status open.
</doc>
<doc path="docs/project/issues/12-similars-on-scroll.md">
At harvest: set `Status: enhancement, complete`, add a delivery comment (links removed and the `/videos.html?id=` mode kept by operator decision, 48-row batch revealed 8 at a time, list ends at the pool's end with no marker, later-batch failure is console-only, no DOM windowing), then move the file to `docs/project/issues/archive/`.
</doc>
<doc path="docs/project/issues/plan.md">
Line 42 (P2 row): strike 12 as delivered. Line 91 (row 4a): mark it delivered and correct the file list. The `?id=` mode of `pages/videos/index.ts` and the similar route limit were not changed. The files are `pages/video-page/index.ts`, `video-page.html`, `video.css` and the new test.
</doc>
<doc path="docs/project/roadmap.md">
In the delivered list (lines 14-20), add an entry for issue `12`, similars on scroll: the video page pages up-next similars on scroll, 48 per request and revealed 8 at a time, and no longer links to the separate similar-videos page. Point it at `docs/project/plans/19-12-similars-on-scroll.md`, or its archived path after harvest.
</doc>

### highest_risk

`tests/active/test_frontend_upnext_pager.py` (new): later batches drive the unshown pool below 48, so each runs up to three live ANN searches (nprobe up to 128, k up to 20000) under the Engine's 5 s deadline and the Client's 10 s proxy timeout (`client/backend/server.py:77`). A 500 or 502 makes `next()` throw and fails the no-error assertion. The session Engine's own 60/60 s per-path limiter (`engine/server/api/server_config.py:450`) is not relaxed by the fixture. Whether this test shares that bucket with test_similar's many `/recommendations` calls in one pytest process is unverified. Both can cause timing-dependent failures.
`client/frontend/src/pages/video-page/index.ts` `loadSimilarVideos` plus the new module state: `void loadSimilarVideos()` runs at line 98, before later declarations, so any `let`/`const` state it touches before its first `await` must be declared above line 98 or the module throws a TDZ error at import. The observer and listeners (and `IntersectionObserver`, `document.documentElement`, `innerHeight`) must not be touched on the empty-first-batch path, which is exactly what `tests/active/test_frontend_video_page.py` exercises with `{}`. `loading` must be cleared on every exit path, or scrolling stays dead after a key-rejected retry.
The scroll, reveal and paging code in `client/frontend/src/pages/video-page/index.ts` has no automated coverage beyond a crash check. Append-only reveal via `insertAdjacentHTML`, the fill-viewport loop, observer re-fire after an appended batch, and the stale-pager check are verified only by the maintainer's browser check, and `client/frontend/dist/` stays stale until `npm run build`.

## 2026-09-28 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I checked the inventory against the files at its paths. The plan holds and the inventory is essentially complete. I read the page module (imports, the element lookups at 43/51, the link block at 75-80, `loadSimilarVideos` at 290-325, the stats helpers, `renderSimilarCard`), `data/videos.ts`, the home page's scroll code (`pages/videos/index.ts:84-97, 171-375`), `test_frontend_video_page.py`, the retired pager test, `video-page.html`, `video.css`, `conftest.py`, the Client's `_profile_filter` and exclude validation, `similarity_candidates.py`, the Engine handler (`similar.py` 760-874, 941-947, 1100-1124), the Engine rate limiter, `config.json`, issue 35, issue 12 and `plan.md:91`. Every entry held except one partial claim about when the ANN fallback runs, listed under unconfirmed. The inventory left one question open (can the Engine limiter 429 the new test), and the tree answers it: under `validate_tests.py` each test group runs in its own pytest subprocess, which starts its own session-scoped Engine. The limiter is keyed `ip:path` at 60 per 60 s (`similar.py:592-599`, `http_utils.py:59-84`). The new test makes at most 10 `/recommendations` calls plus one search, which sits on a different path. So there is no 429 under the validator. Only a bare single-process `pytest tests/active` run, where `test_similar` also calls `/recommendations` many times, could hit one. A repo-wide grep finds no other reference to `similar-link`, "Open full list" or `videos.html?id` outside `dist/`, a `delete_me/` backup directory and this build's own plan files.
<question id="1">
Yes. **Pager and page wiring.** `createFeedPager` (`data/videos.ts:37-70`) does what R1/R3 need: it excludes every row shown so far (the last 500), drops repeats, sets `exhausted` on an empty or failed batch and rethrows errors. `ProfileKeyRejectedError` therefore reaches the page's catch as the plan says. Cards are plain `<a>` markup with no per-card listeners (`renderSimilarCard`, 1168-1201). `applySimilarStatsToDom` looks cards up by `data-video-key` inside `similarCards` (1090-1097), so appended cards work and receive stats. `.similar-grid` is an auto-fit CSS grid and `.video-main` is a single column that scrolls the window. There is no inner scroll container, so window-based bottom detection is correct. `video.css` has no sentinel rule, which confirms the need for the new one.

**Budget reasoning.** `_upnext_rows` runs `_build_rows(..., top_k=300)` before the exclude filter (`similarity_candidates.py:190-195`). `_draw_page` draws 48 from a window of at most 4×48 (`similar.py:834, 1100-1124`). At 48 per batch the pool runs out in about 7 batches, and `MAX_BATCHES = 10` leaves slack for fallback escalation.

**Existing test.** `test_frontend_video_page.py` answers `/recommendations` with `{}`. The pager returns no rows, so the page takes the "No similar videos found." path and never reaches observer code. The test keeps passing as long as the new module state is declared above line 98 (the TDZ constraint the inventory records).
</question>
<question id="2">
The ramifications are those in the inventory:
- **Second consumer of `data/videos.ts`.** Any edit to the pager now affects two pages and two tests.
- **Deliberate duplication.** The home page's scroll code is copied (about 40 lines).
- **Live-stats traffic.** Stats requests grow with scrolling, one PeerTube batch per host per 8-card slice.
- **DOM growth.** Up to about 300 cards per page view, with no windowing.
- **Silent later failures.** A later-batch failure, including a key rejection, stops paging with only a console warning.
- **Stale links.** `/videos.html?id=` keeps working but nothing in the app links to it.
- **Stale `dist/`.** It stays stale until a build.
- **New test is timing-exposed.** Every batch runs the ANN fallback under the Engine's 5 s statement deadline and the Client's 10 s proxy timeout. A 500 or 502 on any batch fails its no-error assertion.
</question>
<question id="3">
Nothing outside the plan's file list has to change. Inside it, these must hold:
- **TDZ.** All new `let`/`const` state that `loadSimilarVideos` touches before its first `await` is declared above the `void loadSimilarVideos()` call at line 98.
- **`loading` flag.** It is cleared on the success, empty and error paths (a `finally`, or both branches), so a successful key-rejected retry does not leave the reveal and scroll checks dead.
- **Observer and listeners.** They are created only after a non-empty first batch, and only once.
- **Stale pager.** `loadMoreSimilar` drops the result of a pager that has since been replaced.
- **Reveal during load.** The reveal is a no-op while `loading`.
- **Deploy.** It needs `npm run build` before the rsync.
</question>
<question id="4">
- **List length.** The similar section is no longer a fixed 8 cards. It shows 8, then reveals 8 more at a time from a 48-row batch in memory, and fetches further 48-row batches with exclusions until the seed's pool runs out (at most about 300 rows, often fewer).
- **Links.** The header "Similar videos" link and the inline "Open full list" link are gone.
- **Rows without id or host.** Rows lacking `video_id` or `instance_domain` are now dropped. The Engine always sets both.
- **Error display.** Later-batch errors are not shown. First-batch behaviour (empty, error, key-rejected, no seed) is unchanged.
</question>

New impacts:
none

Inventory entries that did not hold up:
Two entries imply only later batches pay the ANN fallback: the `tests/active/test_frontend_upnext_pager.py` entry (flake exposure item 1: "Later batches drive the pool below `SIMILAR_VIDEO_TARGET_MIN_POOL` (48), so each runs the ANN fallback") and the `engine/server/data/similarity_candidates.py` entry ("Once a page view has shown enough rows, every later batch pays up to 3 live searches"). The plan's risk "Later batches can be slower" makes the same assumption. What is true: the fallback condition is `len(rows) < policy.target_min_pool or not cache_hit` (`similarity_candidates.py:151`), and `DEPLOYMENT.md:260` states the similarity cache holds 20 candidates per seed, "so nearly every up-next request runs the fallback". The first batch runs at least one live FAISS search too. Later batches differ only in escalating to more steps, up to nprobe 128 / k 20000. So the timing-dependent 500/502 exposure in the new test covers every batch, including batch 1, not just the later ones. The conclusions (medium-high flake risk, 300 s timeout) are unchanged.

Conflicts: none

Recommendations: 1. **Map the new test to the two Engine files as well.** Add `engine/server/data/similarity_candidates.py` and `engine/server/api/handlers/similar.py` to the new test's `config.json` entry, next to the plan's `data/videos.ts` and `server.py`. This is the inventory's gap, and issue 35 line 26 asks for the same mapping for the other up-next tests. It changes the plan's two-file list, so it needs the operator's OK. Cost: the new test (about 8 fallback-running round trips) is reselected on every edit to those two Engine files. Without it, a change to the pool rule the empty-batch assertion depends on goes unnoticed until something else reselects the test.
2. **Put the new module state in one block above line 98, next to `similarStatsCache`/`similarStatsLoading` (72-73).** Clear `loading` in a `finally` inside `loadSimilarVideos`. Cost: none. It removes the only medium-risk crash path, the TDZ error, which would also turn `test_frontend_video_page` red.
3. **Record the rate-limit answer in the new test's docstring.** It is one line: each validator group gets its own Engine, the limiter allows 60 per 60 s per `ip:path`, and the test makes at most 10 calls, so a bare single-process `pytest tests/active` run is the only 429 exposure. Cost: one line.
4. **Optionally add a one-line pointer in the retired `tests/archive/upnext_random_draw/test_frontend_videos.py` docstring to the new file.** Cost: one line. It stops a reader from thinking the coverage is still missing.
5. **No change to the settled plan is needed.** Its "over-fetches 96" wording is only true for keyed profiles with blocks or dislikes (`server.py:471-472`), as the inventory already notes. Neither the page nor the test depends on it.

## 2026-09-28 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-09-28 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Up-next pager contract test [code]

**Files touched.** tests/active/test_frontend_upnext_pager.py (NEW), .un/skills/devsecops/config.json (EDITED)

**Checkpoint.** Seam: the frontend data layer's `createFeedPager` over `fetchSimilarVideosPayload`, bundled with esbuild (ESM, node platform) and run in node against the live Client and Engine that the `engine_client` fixture starts locally. This follows the harness of the retired `tests/archive/upnext_random_draw/test_frontend_videos.py`. The checkpoint is the new `tests/active/test_frontend_upnext_pager.py` itself, as drafted, going green. For the linux search seed at limit "48": the first batch's `seed.mode == "upnext"`; batches 1 and 2 are non-empty and disjoint; no batch repeats a `(video_id, instance_domain)` row from any earlier batch; an empty batch comes before the last of `MAX_BATCHES = 10` calls; the counted fetch calls go 1..k up to the empty batch and do not increase after it. This is characterization: `data/videos.ts` does not change, so the test is green once written.

**Intent.** `tests/active/test_frontend_upnext_pager.py` holds the frontend feed pager's contract over up-next similars at the video page's 48-row batch, in place of the retired `test_frontend_videos.py`.

- C1 - Across 48-row batches from the linux seed, no row repeats, an empty batch arrives within 10 batches, and no request is made after it.

**Outcome.** _pending_

#### Phase 2 - First similar batch through the pager [code]

**Files touched.** client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page_similars.py (NEW)

**Checkpoint.** Seam: the real page module `client/frontend/src/pages/video-page/index.ts`, bundled with esbuild (`--loader:.css=empty`) and imported in node under the recording-element runner copied from `tests/active/test_frontend_video_page.py`. It lives in a new `tests/active/test_frontend_video_page_similars.py`. The runner adds stubs: an `IntersectionObserver` whose callback and observed element are captured; `document.documentElement.scrollHeight` large and `window.innerHeight` small, so fill-viewport never loops; `window.scrollY`. `fetch` records the method, path and JSON body of each request. It answers POST `/recommendations` with 48 distinct rows (each with `video_id` and `instance_domain`) and `seed.mode: "upnext"`, and answers `{}` elsewhere. Asserts: exactly one `/recommendations` request was made, and its body's limit is "48"; the `#similar-videos` element's innerHTML holds exactly 8 `similar-card-item` anchors. Control: `/api/video` was requested. `tests/active/test_frontend_video_page.py` must still pass unchanged, which covers the empty first batch and the no-observer path.

**Intent.** `loadSimilarVideos` in `pages/video-page/index.ts` fetches its first batch through a fresh feed pager asking `/recommendations` for 48 rows, and puts only the first 8 of them into `#similar-videos`.

- C1 - The first `/recommendations` request the page makes carries limit 48.
- C2 - From a 48-row answer, `#similar-videos` holds exactly 8 cards.

**Outcome.** _pending_

#### Phase 3 - Reveal and page on scroll [code]

**Files touched.** client/frontend/src/pages/video-page/index.ts (EDITED), client/frontend/video-page.html (EDITED), client/frontend/src/video.css (EDITED), tests/active/test_frontend_video_page_similars.py (EDITED)

**Checkpoint.** Seam: the same node harness and file as phase 2 (`tests/active/test_frontend_video_page_similars.py`), after the first batch has rendered. The runner also records each `insertAdjacentHTML` call on `#similar-videos`, and invokes the captured `IntersectionObserver` callback with `[{ isIntersecting: true }]`. Fetch answers a second `/recommendations` POST with a disjoint batch. Asserts: one intersection adds exactly one `insertAdjacentHTML("beforeend", …)` call holding 8 `similar-card-item` anchors, and the grid's innerHTML is still the first 8 cards, not rewritten. After five further intersections have revealed all 48 rows, the next intersection sends a second `/recommendations` POST, and its exclude list holds exactly the 48 `(video_id, instance_domain)` pairs of the first batch. Control: the observer was constructed with the `#similar-sentinel` element.

**Intent.** Once the first similar batch is shown, each sentinel intersection appends the next 8 fetched rows to `#similar-videos`, and an intersection that finds no unrevealed row asks the pager for the next batch, excluding the rows already shown.

- C1 - A sentinel intersection appends the next 8 cards, and the cards already shown stay in place.
- C2 - An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown.

**Outcome.** _pending_

#### Phase 4 - Remove the see-all links [code]

**Files touched.** client/frontend/video-page.html (EDITED), client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_page_similars.py (EDITED)

**Checkpoint.** Seam, two boundaries. First, the served HTML file `client/frontend/video-page.html`, parsed with stdlib `html.parser`: no `a` element has an `href` containing `/videos.html`, and no element has id `similar-link` or `similar-link-inline`. Second, the phase 2 node runner in `tests/active/test_frontend_video_page_similars.py`, which reports every id passed to `document.getElementById`: neither `similar-link` nor `similar-link-inline` is among them after the page has loaded. Control: `similar-videos` is among them.

**Intent.** The video page no longer offers a link to `/videos.html`: the anchor is gone from its HTML, and the module no longer looks up the link elements.

- C1 - `video-page.html` contains no anchor to `/videos.html`.
- C2 - The page module never looks up `#similar-link` or `#similar-link-inline`.

**Outcome.** _pending_


Needs coordination: Phase 1: its checkpoint needs the live local Client and Engine that the `engine_client` fixture starts (the engine pixi env and its local data). It makes about 8 round trips, some of which run the ANN fallback, under a 300 s timeout. It shares the Engine's 60/min limiter with `test_similar`. No credential is needed. Phases 2-3, manual step: node has no layout, so the maintainer checks in a real browser what no checkpoint can: fill-viewport on a very tall screen, the scroll and resize fallbacks at the -240/+120 thresholds, and requests stopping at the pool's end in a real layout.

Rationale: The phases follow the draft's own seams. Phase 1 is the R6 test, which is independent of the page and green by itself because `data/videos.ts` does not change. The config mapping goes in with it as plumbing, not as a separate clause: a test that reads the entry back would only verify that the entry was pasted. Phase 2 covers R1 and the first part of R2: the pager at 48 and the first 8 cards. Phase 3 covers the rest of R2 and R3: append on intersection and the second batch with exclude. They are split because each phase's Intent has two observable facts, and together they have four. R5, link removal, is separate and small, and goes last so phase 4 can reuse the phase 2 runner's getElementById log. The operator approved a change from the draft's "manual only" for R2/R3. A new `test_frontend_video_page_similars.py` reuses the recording-element runner of `test_frontend_video_page.py` with stubbed IntersectionObserver, scroll metrics and fetch. It checks the request limit, the card counts and the exclude contents at the module boundary without a layout engine. Only real-layout behaviour stays manual: fill-viewport and the scroll and resize thresholds. R4 (unchanged empty, error, no-seed and key-rejected paths) is covered by `test_frontend_video_page.py` staying green, plus the full suite. The issue 35 note is documentation, so it has no phase; Step 9 writes it.

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`tests/active/test_frontend_upnext_pager.py` holds the frontend feed pager's contract over up-next similars at the video page's 48-row batch, in place of the retired `test_frontend_videos.py`.

- C1 - Across 48-row batches from the linux seed, no row repeats, an empty batch arrives within 10 batches, and no request is made after it.

must_prove:
- C1 - Across 48-row batches from the linux seed, no row repeats, an empty batch arrives within 10 batches, and no request is made after it.

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - self-check (audit round 1, send-back 0)

`tests/tmp/test_12_similars_on_scroll_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:91, :92 and :96: batch 2 is non-empty and shares no (video_id, instance_domain) with batch 1, and no batch among the 10 repeats a row from any earlier batch. :101: an empty batch exists at an index below the last of the 10 calls. :104: every batch after the empty one reports the same counted fetch calls as the empty batch did. :103 is the positive control that arms :104 (calls go 1..k up to the empty batch) and has no row of its own. - expected: Observed by the probe run on the same harness: batch sizes [48, 48, 48, 48, 48, 48, 12, 0, 0, 0], counted calls [1, 2, 3, 4, 5, 6, 7, 8, 8, 8], first-batch mode 'upnext', no error lines. So batch 2 has 48 rows and none are shared, there are no repeats across the 300 rows, the first empty batch is at index 7 (7 + 1 < 10), and calls stay at 8 for indexes 8 and 9. - excludes: (a) A pager that ignores `exhausted` in `next()` (delete `if (exhausted) return { rows: [] };`, videos.ts:48), or one that never sets it on an empty batch (delete videos.ts:66). Either keeps calling the fetch, so indexes 8 and 9 read calls 9 and 10 instead of 8, and :104 goes red. (b) A pager that drops both the exclude list it sends and its own `keys.has` dedup (videos.ts:61-63). The Engine's random draws then overlap, so batch 2 shares rows with batch 1 and :92/:96 go red. (c) An Engine that refills an excluded pool from deeper ANN hits instead of shrinking a fixed top-300. Every batch then stays at 48 rows, no empty batch arrives, and :101 goes red, printing the ten sizes.

Exemptions the operator granted, verified against the agent's own transcript: C1

<assertions>
tests/tmp/test_12_similars_on_scroll_phase1.py:85 — control: no batch reports an error (a 500/502/429 from the Client or Engine would throw in `next()`, set `exhausted`, and be reported here, not mistaken for an empty batch) — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:86 — control: the runner reports exactly MAX_BATCHES = 10 batches, so a crash partway through cannot shorten the list the later assertions read — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:87 — control: the first batch's `seed.mode == "upnext"`, so the linux seed resolves to up-next similars and not to the home or random feed — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:90 — control: batch 1 is non-empty — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:91 — batch 2 is non-empty, so paging past the first 48-row batch returns rows — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:92 — batches 1 and 2 share no (video_id, instance_domain) row — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:96 — no batch repeats a (video_id, instance_domain) row from any earlier batch, checked over all 10 batches — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:101 — an empty batch appears at an index below the last of the 10 calls, so the seed's pool ends within the budget and at least one call follows it to count; the failure message prints the batch sizes — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:103 — control: up to and including the empty batch, the calls counted on the fetch function handed to the pager are exactly 1..k, one request per `next()` — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:104 — every `next()` after the empty batch leaves the counted calls where they were at the empty batch, so no request is made after it — C1
</assertions>

<probes>
tests/tmp/probe_12_pager.py, run with ValidateTests ["tests/tmp/probe_12_pager.py", "-s"] against the `engine_client` fixture (imported from tests/active/conftest.py by sys.path, as earlier tests/tmp checkpoints did). It used the same esbuild bundle and node runner as the checkpoint, with limit "48", 12 `next()` calls, and a fetch pass-through that counted calls and recorded each exclude length. What it printed:
- search: 200. The linux seed is 2020b23c-0367-4d64-99ff-73dc6bc7b91e@tube.undernet.uy. rc 0, empty stderr.
- Batches 1–6: 48 rows each, mode 'upnext', seed keys [video_id, instance_domain, channel_id, title, mode]. Calls went 1→6, and each call sent the rows already shown as its exclude (0, 48, 96, 144, 192, 240). About 190 ms per batch.
- Batch 7: 12 rows, mode 'upnext', calls 7, exclude 288. Took 807 ms (the ANN fallback runs here).
- Batch 8: 0 rows, mode None (the empty-pool branch answers without `mode`), calls 8, exclude 300, exhausted True.
- Batches 9–12: 0 rows, calls still 8, 0 ms each, so no request was made.
- Across all batches, "repeats_earlier 0" and "total distinct 300".
So the empty batch arrives at index 7 of 10, and the plan's top-300-then-exclude reasoning holds as observed.

Checkpoint run: ValidateTests ["tests/tmp/test_12_similars_on_scroll_phase1.py"] gave "1 passed" and exit 0, as expected: this phase is characterization and data/videos.ts is unchanged.

I emptied the probe file because I have no delete tool, and it collects zero tests. tests/tmp/probe_12_pager.py still needs removing.
</probes>

<unassertable>
none. The checkpoint asserts all three parts of C1: no row repeats (:91, :92, :96), an empty batch within 10 (:101), and no request after it (:104).

Two notes, neither a gap in C1:
1. This checkpoint is green from the moment it is written. It is characterization of an unchanged data/videos.ts, as Step 6 agreed, so there is no red run.
2. The test cannot tell apart two wrong pagers: one that keeps its client-side dedup but stops sending `exclude`, and one that sends `exclude` but drops the dedup. Either way no row repeats. A pager that sends no `exclude` is still caught at :101. Each unexcluded request re-draws 48 rows from the same top-192 window, so a batch with no new row is very unlikely within 10 calls (roughly 0.75^20 per draw once 20 rows remain unseen). That estimate is my reasoning, not an observation. Asserting the exclude length per call would pin that down (the probe saw 0, 48, …, 300), but it is not in the agreed checkpoint or in C1, so I left it out.
</unassertable>

### `tests/tmp/test_12_similars_on_scroll_phase1.py` - 5515 characters, inlined in full

```
"""The frontend's feed pager over up-next similars, run in node against the real Client and Engine at the video page's 48-row batch: its batches never repeat a row, and it stops asking once a batch adds nothing.

- For the linux seed, the pager's first batch is an up-next page (`seed.mode == "upnext"`), its second batch holds rows and none of the first batch's, and no later batch repeats a row of an earlier one. Each batch is a random draw (build 09), so no two pages are compared for equality.
- The pager is driven for MAX_BATCHES calls and reaches an empty batch before the last: the Engine takes a seed's top 300 rows before it drops excluded ones, so at 48 a batch the pool runs out in about 7. No call after the empty batch makes a request, counted on the fetch function the pager is given (a pass-through to `fetchSimilarVideosPayload`).

Replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). `window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner supplies minimal in-memory ones, as `test_frontend_video_page.py` does.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))

from conftest import engine, engine_client  # noqa: E402,F401

FRONTEND = ROOT / "client" / "frontend"
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
    # A seed whose up-next pool is the full 300: at 48 a batch it came back 48 x 6, then 12, then empty at batch 8.
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
    assert second, "the second batch is empty"  # C1
    assert not first & second, first & second  # C1
    seen: set[tuple] = set()
    for batch in batches:  # and no later batch repeats a row of any earlier one
        rows = set(map(tuple, batch["rows"]))
        assert not rows & seen, (rows & seen, [len(b["rows"]) for b in batches])  # C1
        seen |= rows

    empty = next((i for i, b in enumerate(batches) if not b["rows"]), None)
    # the seed's pool ends within the budget, with at least one call after it to count
    assert empty is not None and empty + 1 < len(batches), [len(b["rows"]) for b in batches]  # C1
    # control: up to the empty batch, every batch was one request through the given fetch
    assert [b["calls"] for b in batches[:empty + 1]] == list(range(1, empty + 2)), batches
    assert all(b["calls"] == batches[empty]["calls"] for b in batches[empty + 1:]), batches  # C1

```


Gate: satisfied

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - NOT RED (send-back 1)

`tests/tmp/test_12_similars_on_scroll_phase1.py` passed before the work was done, so it measures nothing.

```
  tests/tmp/test_12_similars_on_scroll_phase1.py  1 passed                               0.0s
  ----------------------------------------------
  total                                           1 passed                               7.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - self-check (audit round 1, send-back 1)

`tests/tmp/test_12_similars_on_scroll_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_12_similars_on_scroll_phase1.py:95, :96, :100 — the second 48-row batch holds rows, it shares none with the first, and no batch across all 10 shares a (video_id, instance_domain) with any earlier batch - expected: Green. The probe run showed batch sizes 48, 48, 48, 48, 48, 48, 12, 0, 0, 0, all with mode "upnext" until the empty batch, and no row repeated. - excludes: A pager that stops putting the rows it has shown into `exclude` (drop `shown.push`). Every fetch is then a fresh random 48 from the same 300-row pool. Its own key filter hides repeats, but the pool never runs dry within 10 calls, so :105 goes red. A pager that drops the key filter and the exclude list together hands back repeated rows, and :96/:100 go red.
- C1 - test_12_similars_on_scroll_phase1.py:105 and :108 — an empty batch arrives at index < 9 (within the 10-batch budget, with calls after it), and every batch after it reports the same fetch-call count as the empty one - expected: Green. The probe showed the empty batch at index 7 (batch 8) and calls at 1..8 then 8, 8. The control at :107 (calls == 1..empty+1) passed. - excludes: A pager that does not set `exhausted` when a batch adds no row, or that ignores it in `next()`, keeps fetching: calls read 9 and 10 after the empty batch and :108 goes red. A pager that never excludes shown rows never reaches an empty batch within 10, and :105 goes red.
- C1 - test_12_similars_on_scroll_phase1.py:121 — `claimed(ROOT, load_config())` from validate_tests.py has a group `test_frontend_upnext_pager.py`, i.e. the durable test that gates these behaviours exists in tests/active - expected: Red before the phase: the run printed `AssertionError: ['test_blocks.py', ... ] / assert None is not None` at line 121. Green once the durable test is written. - excludes: A phase that leaves the claim only in this tmp checkpoint, or files the durable test under a name or place the harness does not discover (e.g. archive/ or a `_`-prefixed name). Then `claims.get(...)` is None and nothing gates C1 after the build.
- C1 - test_12_similars_on_scroll_phase1.py:122 — the files the harness fingerprints that group over include videos.ts, client/backend/server.py, similarity_candidates.py and handlers/similar.py - expected: An empty list, once the phase lands with the test_groups entry. It is not reached in the current run because :121 fails first. - excludes: A test_groups entry that is missing, leaves out one of these subjects, or names a mistyped path (`walk` silently drops a missing root). The list then names the uncovered subject, and an edit to that file would not reselect the durable test.

Exemptions the operator granted, verified against the agent's own transcript: C1

<assertions>
tests/tmp/test_12_similars_on_scroll_phase1.py:86 — control: no batch reports an error. A 500/502/429 from the Client or Engine would throw in `next()` and be reported, not mistaken for an empty batch. — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:87 — control: exactly MAX_BATCHES = 10 batches are reported. — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:88 — control: the first batch's `seed.mode == "upnext"`, so the linux seed resolves to up-next similars. — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:91 — control: batch 1 is non-empty. — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:92 — batch 2 is non-empty. — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:93 — batches 1 and 2 share no (video_id, instance_domain) row. — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:97 — no batch repeats a (video_id, instance_domain) row from any earlier batch, checked over all 10 batches. — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:102 — an empty batch arrives before the last of the 10 calls. — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:104 — control: the counted fetch calls go exactly 1..k up to and including the empty batch. — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:105 — every `next()` after the empty batch leaves the counted calls unchanged, so no request is made after it. — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:110 — control: config.json's test_groups has no `test_frontend_videos.py` entry, so the mapping checked below is not the retired one. — C1 (control)
tests/tmp/test_12_similars_on_scroll_phase1.py:111 — `tests/active/test_frontend_upnext_pager.py` exists. This is the artifact gate the operator approved. It is RED now: the file is missing. — C1
tests/tmp/test_12_similars_on_scroll_phase1.py:112 — config.json's test_groups maps `test_frontend_upnext_pager.py` to exactly {client/frontend/src/data/videos.ts, client/backend/server.py, engine/server/data/similarity_candidates.py, engine/server/api/handlers/similar.py}, the plan's entry. It is red now because the entry is absent (`.get` returns []). A missing file, an extra file, or a wrong file would also fail. — C1
</assertions>

<probes>
Earlier probe (unchanged from my previous reply): tests/tmp/probe_12_pager.py, run with ValidateTests ["tests/tmp/probe_12_pager.py", "-s"] against `engine_client`, printed the following:
- The linux seed is 2020b23c-0367-4d64-99ff-73dc6bc7b91e@tube.undernet.uy.
- Batches 1–6 had 48 rows each, mode 'upnext', and calls 1→6 with exclude lengths 0, 48, 96, 144, 192, 240.
- Batch 7 had 12 rows and took 807 ms.
- Batch 8 had 0 rows, mode None, calls 8, and set exhausted True.
- Batches 9–12 had 0 rows and calls stayed at 8.
- repeats_earlier was 0 and total distinct was 300.

This turn: I read .un/skills/devsecops/config.json. test_groups has no `test_frontend_upnext_pager.py` entry and no `test_frontend_videos.py` entry, and `tests/active/test_frontend_upnext_pager.py` is absent. The expected mapping is taken verbatim from plan docs/project/plans/19-12-similars-on-scroll.md:800-805.

Checkpoint run: ValidateTests ["tests/tmp/test_12_similars_on_scroll_phase1.py"] gave "1 failed, 1 passed" and exit 1. The pager test passes, as characterization. The artifact test fails at :111 with `assert (ACTIVE_DIR / "test_frontend_upnext_pager.py").is_file()`, AssertionError: assert False. That is red for the intended reason.

tests/tmp/probe_12_pager.py still exists. It is empty and collects no tests, and I have no delete tool, so it still needs removing.
</probes>

<unassertable>
The pager behaviour in C1 cannot be red for this phase. data/videos.ts does not change, so the pager test (:86–:105) is characterization and passes both before and after. I put this to the operator with AskUser. They chose "Add a red artifact gate": keep the behavioural assertions, and add structural assertions that go red→green with this phase's actual output. Those are the active test file existing (:111) and its config.json mapping (:112). The artifact gate shows the durable test and its reselection mapping were delivered. It does not show that the active file's assertions match the draft; that is left to review of the file itself.

Still open from before: the test cannot tell apart a pager that keeps client-side dedup but stops sending `exclude` from one that sends `exclude` but drops the dedup. A pager with no `exclude` would very likely still be caught at :102, but that is my reasoning, not an observation. Asserting the exclude length per call (the probe saw 0, 48, …, 300) would pin it down. That is outside the agreed checkpoint and C1.
</unassertable>

### `tests/tmp/test_12_similars_on_scroll_phase1.py` - 6621 characters, inlined in full

```
"""The frontend's feed pager over up-next similars, run in node against the real Client and Engine at the video page's 48-row batch: its batches never repeat a row, and it stops asking once a batch adds nothing.

- For the linux seed, the pager's first batch is an up-next page (`seed.mode == "upnext"`), its second batch holds rows and none of the first batch's, and no later batch repeats a row of an earlier one. Each batch is a random draw (build 09), so no two pages are compared for equality.
- The pager is driven for MAX_BATCHES calls and reaches an empty batch before the last: the Engine takes a seed's top 300 rows before it drops excluded ones, so at 48 a batch the pool runs out in about 7. No call after the empty batch makes a request, counted on the fetch function the pager is given (a pass-through to `fetchSimilarVideosPayload`).
- The pager assertions above characterise an unchanged `data/videos.ts` and are green before this phase lands. What this phase delivers is the durable test itself: `tests/active/test_frontend_upnext_pager.py` exists, and config.json's test_groups maps it to exactly `data/videos.ts`, the Client's `server.py`, and the Engine's `similarity_candidates.py` and `handlers/similar.py`, so it is reselected when any of them changes.

Replaces `tests/archive/upnext_random_draw/test_frontend_videos.py` (issue 35). `window`, `localStorage` and `sessionStorage` are the browser platform node lacks; the runner supplies minimal in-memory ones, as `test_frontend_video_page.py` does.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))

from conftest import engine, engine_client  # noqa: E402,F401

FRONTEND = ROOT / "client" / "frontend"
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
    # A seed whose up-next pool is the full 300: at 48 a batch it came back 48 x 6, then 12, then empty at batch 8.
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
    assert second, "the second batch is empty"  # C1
    assert not first & second, first & second  # C1
    seen: set[tuple] = set()
    for batch in batches:  # and no later batch repeats a row of any earlier one
        rows = set(map(tuple, batch["rows"]))
        assert not rows & seen, (rows & seen, [len(b["rows"]) for b in batches])  # C1
        seen |= rows

    empty = next((i for i, b in enumerate(batches) if not b["rows"]), None)
    # the seed's pool ends within the budget, with at least one call after it to count
    assert empty is not None and empty + 1 < len(batches), [len(b["rows"]) for b in batches]  # C1
    # control: up to the empty batch, every batch was one request through the given fetch
    assert [b["calls"] for b in batches[:empty + 1]] == list(range(1, empty + 2)), batches
    assert all(b["calls"] == batches[empty]["calls"] for b in batches[empty + 1:]), batches  # C1


def test_the_pager_contract_is_an_active_test_mapped_to_the_files_it_runs_through():
    groups = json.loads((ROOT / ".un" / "skills" / "devsecops" / "config.json").read_text())["test_groups"]
    assert "test_frontend_videos.py" not in groups  # control: the retired entry is not what is being mapped
    assert (ACTIVE_DIR / "test_frontend_upnext_pager.py").is_file()  # C1
    assert sorted(groups.get("test_frontend_upnext_pager.py", [])) == sorted([  # C1
        "client/frontend/src/data/videos.ts", "client/backend/server.py",
        "engine/server/data/similarity_candidates.py", "engine/server/api/handlers/similar.py"]), groups.get("test_frontend_upnext_pager.py")

```


Gate: satisfied

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - red (audit round 1)

`tests/tmp/test_12_similars_on_scroll_phase1.py` exited 1.

```
  tests/tmp/test_12_similars_on_scroll_phase1.py  1 failed, 1 passed                     0.0s
  ----------------------------------------------
  total                                           1 failed, 1 passed                     7.6s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 4 UNCARRIED clause(s) - D1, D8, N1, N5b

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. EXEMPT C1: stub question, "previous behaviour left unchanged" (rules/shape.md <ladder> / stub question) — tests/tmp/test_12_similars_on_scroll_phase1.py:86
   def test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch(
   This test passes on the unchanged client/frontend/src/data/videos.ts. The builder's reason
   concedes exactly that. The exemption holds up on the shape: the test does not pass on a stub.
   - A pager that returns nothing fails :94.
   - A pager that sends no exclude list, so the Engine's random draw repeats rows, fails :100,
     or fails :105 if it drops the repeats itself, because no empty batch arrives.
   - A pager that never sets `exhausted` fails :108, where the call count keeps rising after
     the empty batch.
   The line numbers in the exemption are out of date. It cites :91, :92, :96, :101, :104 for the
   C1 lines and :85-87, :90, :103 for the controls. In the file the C1 tags are at
   :95, :96, :100, :105, :108 and the controls at :89-:91 and :107. The gate record should
   point at the current lines.

PREDICTED FAILURE
test_the_durable_pager_test_is_a_group_fingerprinted_over_the_files_it_runs_through fails at
line 121 on `assert covered is not None`. tests/active/test_frontend_upnext_pager.py does not
exist, so `harness.groups()` never finds it and `claims.get("test_frontend_upnext_pager.py")`
returns None. The config.json `test_groups` map has no entry for it either, so :122 would fail
next. The first test (:86) is predicted green by design, per the C1 exemption.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py (NEW). It does not exist
   yet, so it was not read. The stub question for the second test was answered from its assertion
   form and from `claimed()` in .un/skills/devsecops/scripts/validate_tests.py:616.
2. `fixtures_path` was not supplied. The `engine` and `engine_client` fixtures come from
   tests/active/conftest.py (:106, :149), which was read up to the `_engine_client` helper
   (:164-184). The rest of that file (:1-99, :190-233) was not read.
3. The claim at :80 and in the docstring that the linux seed's pool runs out at about batch 8
   depends on the Engine's data. It was not checked, because no Engine source was in
   `code_under_test`.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 4 must_prove, 8 docstring, 7 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "48-row batches from the linux seed" | none (setup only: `PAGE` at :27/:73, `q=linux` at :81) | nothing asserts any batch's length. A query that drops `limit` still passes | EXEMPT |
| C1b | must_prove | "no row repeats" across batches | :96, :100 | a pager that neither sends `exclude` nor drops a row it has already seen | EXEMPT |
| C1c | must_prove | "an empty batch arrives within 10 batches" | :105 (control :90) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |
| C1d | must_prove | "no request is made after it" | :108 (control :107) | a pager that keeps fetching once `exhausted` should be set | EXEMPT |
| D1 | docstring | runs "at the video page's 48-row batch" | none | nothing: no assertion bounds `len(rows)` at 48 | UNCARRIED |
| D2 | docstring | "first batch is an up-next page (`seed.mode == "upnext"`)" | :91 | a seed that resolves to a random or other mode | CARRIED |
| D3 | docstring | "second batch holds rows and none of the first batch's" | :95, :96 | an empty second page, and a second page that repeats the first | CARRIED |
| D4 | docstring | "no later batch repeats a row of an earlier one" | :100 | a pager that only excludes the batch just before, not every earlier one | CARRIED |
| D5 | docstring | "driven for MAX_BATCHES calls and reaches an empty batch before the last" | :90, :105 | a crashed run that stops early, and an empty batch only at index 9 or never | CARRIED |
| D6 | docstring | "No call after the empty batch makes a request, counted on the fetch function" | :108 | a `next()` that calls `fetchBatch` after the feed is exhausted | CARRIED |
| D7 | docstring | "`test_frontend_upnext_pager.py` is a test group" | :121 | a durable file missing from `tests/active` | CARRIED |
| D8 | docstring | "the durable test itself": the pager test, made durable | none | nothing: :121 accepts any file with that name, including one that asserts nothing about the pager | UNCARRIED |
| D9 | docstring | claimed files "include `data/videos.ts`, … `server.py`, … `similarity_candidates.py` and `handlers/similar.py`, so it is reselected when any of them changes" | :122 (control :119) | a `test_groups` entry that leaves out any of the four | CARRIED |
| N1 | name | "the pager's 48-row batches" | none | nothing: batch size is never asserted | UNCARRIED |
| N2 | name | "never repeat a row" | :100 | a pager that lets an Engine repeat through | CARRIED |
| N3 | name | "it stops asking after an empty batch" | :108 | a pager that still fetches after an empty batch | CARRIED |
| N4 | name | "the durable pager test is a group" | :121 | the group is absent | CARRIED |
| N5a | name | "fingerprinted over the files it runs through": the four named subjects | :122 | a mapping missing one of the four | CARRIED |
| N5b | name | "the files it runs through": the rest of the path it exercises | none | nothing: `videos.ts` imports `./cache`, `./local-likes`, `./api-base` and `./profile`, and `fetchSimilarVideosPayload` calls `getRandomLikes`/`profileHeaders` on every request. None of them is in `SUBJECTS` (:30) | UNCARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase1.py:1, :86
   D1 and N1 are UNCARRIED. The docstring and the name both say "48-row batches", but the test only passes `limit=48` (:43, :73) and never asserts a batch's size. A client that ignored `limit` would pass.
2. whole-claim (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase1.py:5, :121
   D8 is UNCARRIED. The docstring says the phase delivers "the durable test itself". `assert covered is not None` shows only that a file of that name is a group. It does not show that the file carries the pager assertions.
3. name-as-sentence / whole-claim (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase1.py:111
   N5b is UNCARRIED. The name claims "the files it runs through", but :122 checks only the four files in `SUBJECTS` (:30). Other files on the exercised path (`data/profile.ts`, `data/local-likes.ts`, `data/api-base.ts`, `data/cache.ts`) are not checked. Either narrow the name or widen `SUBJECTS`.
4. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase1.py:89
   Only the success path runs. `createFeedPager` also ends the feed when a batch fails: it sets `exhausted` and rethrows (videos.ts:52-54). No test checks that a fetch error stops later requests. :89 treats any error as a failed test.
5. bounds (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase1.py:81
   Only one seed and one page size are tested. Edges are untested: a seed whose pool is smaller than one batch, which would come back empty on the first or second batch, and a page size at or past the exclude cap `MAX_FEED_EXCLUDE = 500`.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve. I could not check that the durable copy matches this test, so D8 was judged from this file alone.

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - self-check (audit round 2, send-back 1)

`tests/tmp/test_12_similars_on_scroll_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:96, :97, :101 — batch 2 is non-empty, batches 1 and 2 share no (video_id, instance_domain) row, and no batch repeats a row from any earlier batch, over all 10 batches. - expected: Observed batch sizes 48 x 6, 12, 0, 0, 0 with 300 distinct rows and no overlaps, so all three hold. - excludes: A pager that stops sending `exclude` and does not dedup gets the Engine's random draw repeating rows, and :97/:101 read a non-empty intersection. A pager that excludes only the previous batch fails :101 on a later batch.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:106 — an empty batch arrives before the last of the 10 calls (control :91: exactly 10 batches reported; :90: no error line). - expected: The first empty batch is at index 7 (the 8th call). - excludes: A feed that never runs dry (a pager that dedups client-side without sending `exclude`, so it keeps drawing), or one that runs dry only at index 9: `empty` is None or equals 9, and the assertion fails.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:108 — every batch before the last non-empty one has exactly int(PAGE)=48 rows, and the last non-empty one has 1..48. - expected: sizes[:6] == [48]*6 and sizes[6] == 12. - excludes: A pager that merges two fetches per `next()` (96 rows), one that trims or dedups rows out of a full page (fewer than 48 while the pool remains), or a query that sends the wrong `limit` (observed: limit=20 gives 20-row batches) fails. A dropped `limit` is NOT excluded, because the observed default is 48.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:111 — every `next()` after the empty batch leaves the counted fetch calls unchanged (control :110: calls go 1..8 up to and including the empty batch). - expected: calls [1..8, 8, 8], so they stay at 8 after the empty batch. - excludes: A pager that never sets `exhausted` keeps calling `fetchBatch`, so calls read 9, 10 and :111 fails.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:124, :125 — a group `test_frontend_upnext_pager.py` is discovered by validate_tests.py's `claimed`, and its claimed files include all four SUBJECTS (control :120: an existing group carries its mapping; :122: all four subjects exist). - expected: Once the phase lands, `covered` is non-None and contains videos.ts, server.py, similarity_candidates.py and handlers/similar.py. It is RED now: covered is None, observed at :124. - excludes: A phase that does not add tests/active/test_frontend_upnext_pager.py fails :124. A config.json entry missing any of the four files fails :125, which lists the missing one.

Exemptions the operator granted, verified against the agent's own transcript: C1

<exemptions>
none
</exemptions>

<items>
<item id="D1">
<disposition>fixed</disposition>
<what>New assertion at :108: `sizes[:empty - 1] == [48] * (empty - 1) and 0 < sizes[empty - 1] <= 48`. Every batch before the last non-empty one must hold exactly 48 rows, and the last non-empty one must hold 1 to 48 (the observed sizes were 48 x 6, then 12). It fails for a pager or client that returns more than one page per batch (for example two merged fetches giving 96), one that trims or dedups rows out of a full batch (fewer than 48 while the pool still has rows), and a `limit` sent as the wrong number (a run at limit=20 came back 20 x 10). One case it cannot catch: dropping `limit` altogether. I observed that a run with no limit also came back 48 x 6, 12, 0, 0, 0, so the default is 48 too. I added a docstring bullet that says so, so the prose claims only what :108 checks.</what>
</item>
<item id="D8">
<disposition>justified</disposition>
<what>I narrowed the docstring (bullet 3). It no longer says the phase "delivers the durable test itself". It now says: "What this test checks of the phase is that the durable copy is registered: a test group named `test_frontend_upnext_pager.py` is discovered in tests/active …". It also says that whether the durable file carries the pager assertions "is not checked here; it is left to review of that file". The prose now matches :124, which only checks that a group of that name exists. I did not add a check on the durable file's contents: that would mean either grepping its source or running pytest on a tests/active file from inside this test, and the second would bank a fingerprint in the middle of the build.</what>
</item>
<item id="N1">
<disposition>fixed</disposition>
<what>The name's "48-row batches" is now carried by :108, which requires exactly 48 rows in every batch before the last non-empty one and at most 48 in that one. It fails for merged pages, trimmed pages, or a wrong `limit` value. It does not catch a dropped `limit`, because the observed default is also 48, and the docstring says so.</what>
</item>
<item id="N5b">
<disposition>justified</disposition>
<what>I narrowed the name from `..._fingerprinted_over_the_files_it_runs_through` to `test_the_durable_pager_group_is_fingerprinted_over_videos_ts_the_client_server_and_both_engine_similars_files` (:114). It now names exactly the four `SUBJECTS` that :125 checks. The docstring also now says that `data/videos.ts`'s imports (`cache`, `local-likes`, `api-base`, `profile`) are not in the plan's mapping and are not checked. I did not widen `SUBJECTS`. The operator-approved config.json entry in plan docs/project/plans/19-12-similars-on-scroll.md:800-805 lists only these four files, so asserting more would make the test demand a mapping the plan does not deliver.</what>
</item>
</items>

<findings_addressed>
Claim audit CRITICAL: none. Shape audit CRITICAL: none.
Claim REC 1 (D1/N1, batch size never asserted): taken. Added :108 bounding every batch at exactly 48 before the last non-empty one and 1..48 for that one. The docstring now says a dropped `limit` is indistinguishable, because the observed default is also 48.
Claim REC 2 (D8): taken by narrowing the docstring. It now claims only that the durable group is registered and its mapping; the durable file's contents are left to review.
Claim REC 3 (N5b): taken by narrowing the test name to the four files :125 checks. `SUBJECTS` is not widened, since the plan's approved mapping (plan :800-805) has these four.
Shape REC 1 (stale line numbers in the C1 exemption): noted, not re-asked, because the exemption stands. The current lines are: C1-tagged assertions :96, :97, :101, :106, :108, :111, :124, :125; controls :90-:92, :95, :110, :120, :122.
Claim REC 4 (fetch-error path) and REC 5 (small pool / exclude cap bounds): not taken. They are outside the agreed C1 checkpoint and this phase does not change `createFeedPager`.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:96, :97, :101 — batch 2 is non-empty, batches 1 and 2 share no (video_id, instance_domain) row, and no batch repeats a row from any earlier batch, over all 10 batches.</assertion>
<expected>Observed batch sizes 48 x 6, 12, 0, 0, 0 with 300 distinct rows and no overlaps, so all three hold.</expected>
<wrong_implementation>A pager that stops sending `exclude` and does not dedup gets the Engine's random draw repeating rows, and :97/:101 read a non-empty intersection. A pager that excludes only the previous batch fails :101 on a later batch.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:106 — an empty batch arrives before the last of the 10 calls (control :91: exactly 10 batches reported; :90: no error line).</assertion>
<expected>The first empty batch is at index 7 (the 8th call).</expected>
<wrong_implementation>A feed that never runs dry (a pager that dedups client-side without sending `exclude`, so it keeps drawing), or one that runs dry only at index 9: `empty` is None or equals 9, and the assertion fails.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:108 — every batch before the last non-empty one has exactly int(PAGE)=48 rows, and the last non-empty one has 1..48.</assertion>
<expected>sizes[:6] == [48]*6 and sizes[6] == 12.</expected>
<wrong_implementation>A pager that merges two fetches per `next()` (96 rows), one that trims or dedups rows out of a full page (fewer than 48 while the pool remains), or a query that sends the wrong `limit` (observed: limit=20 gives 20-row batches) fails. A dropped `limit` is NOT excluded, because the observed default is 48.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:111 — every `next()` after the empty batch leaves the counted fetch calls unchanged (control :110: calls go 1..8 up to and including the empty batch).</assertion>
<expected>calls [1..8, 8, 8], so they stay at 8 after the empty batch.</expected>
<wrong_implementation>A pager that never sets `exhausted` keeps calling `fetchBatch`, so calls read 9, 10 and :111 fails.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:124, :125 — a group `test_frontend_upnext_pager.py` is discovered by validate_tests.py's `claimed`, and its claimed files include all four SUBJECTS (control :120: an existing group carries its mapping; :122: all four subjects exist).</assertion>
<expected>Once the phase lands, `covered` is non-None and contains videos.ts, server.py, similarity_candidates.py and handlers/similar.py. It is RED now: covered is None, observed at :124.</expected>
<wrong_implementation>A phase that does not add tests/active/test_frontend_upnext_pager.py fails :124. A config.json entry missing any of the four files fails :125, which lists the missing one.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every absence assertion has a positive control. :97/:101 (no overlap) are armed by :95/:96 (both batches non-empty) and :91 (10 batches ran). :111 (no calls after empty) is armed by :110 (calls rose 1..8) and :106 (a call after the empty batch exists). A deleted pager makes the bundle import fail, so there is an error line or a non-zero exit, and the test fails.
2. No. :108 compares observed batch lengths against the input PAGE; it does not recompute anything production does. Breaking the pager's pass-through of `payload.rows`, or the Engine's limit slicing, turns it red. A deleted `limit` param in buildSimilarUrl (videos.ts:103) would NOT turn it red, because the observed default is also 48. The docstring says so.
3. Partly, and disclosed. Batch size is asserted at one page size, 48, which is the claim. A probe at limit=20 observed 20 x 10 and a probe with no limit observed 48 x 6, 12, which is why the docstring concedes the dropped-limit case. I did not add a second page-size run: it would double the Engine traffic against the shared 60/min limiter, which the plan (:791) names as a flake exposure.
4. No. The runner shims only `window`, `localStorage` and `sessionStorage`, which are browser platform objects node lacks. The pager, fetch, Client and Engine are all real.
5. Yes, it collects. The checkpoint run collected 2 tests, "1 failed, 1 passed". `sizes`, `empty` and `PAGE` are bound before use at :108.
6. Yes. The 48 x 6 / 12 / 0 sizes and calls [1..8, 8, 8] come from the probe run this turn (tests/tmp/probe_pager_sizes.py). The limit-dropped (48 x 6, 12) and limit=20 (20 x 10) readings come from tests/tmp/probe_12_nolimit.py this turn. The claim mapping comes from the plan text (:800-805), and its current absence was observed as `None` at :124.
7. Yes. The checkpoint run this turn: the pager test passes (characterization, per the standing C1 exemption), and the group test fails at :124 with `assert None is not None`, because tests/active/test_frontend_upnext_pager.py and its test_groups entry do not exist yet. That is red for the phase's own reason. Housekeeping: the probe files tests/tmp/probe_12_nolimit.py, probe_pager_sizes.py, probe_12_pager_lengths.py, probe_12_claimed.py and probe_12_pager.py are emptied, so they collect nothing. I have no delete tool, so they still need removing.
</answers>

Gate: satisfied

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - red (audit round 2)

`tests/tmp/test_12_similars_on_scroll_phase1.py` exited 1.

```
  tests/tmp/test_12_similars_on_scroll_phase1.py  1 failed, 1 passed                     0.0s
  ----------------------------------------------
  total                                           1 failed, 1 passed                     7.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - BLOCK
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: devsecops-test-shape-auditor: critical

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: BLOCK

CRITICAL
1. Stub question (agent spec, `<verdict>`) — tests/tmp/test_12_similars_on_scroll_phase1.py:124-125
   assert covered is not None, sorted(claims)  # C1
   assert [s for s in SUBJECTS if ROOT / s not in covered] == [], covered  # C1
   The phase's only output is the durable copy at tests/active/test_frontend_upnext_pager.py.
   This test checks that the durable file is registered and mapped in config.json. It does not
   check what the file contains. `claimed()` (validate_tests.py:643-648) adds a group for any
   `test_*.py` it finds under tests/active, whatever that file holds. So an empty
   `test_frontend_upnext_pager.py`, or one whose test body is only `pass`, plus the four config
   entries, turns both lines green. The module docstring (line 6) says so itself: "That the
   durable file carries the pager assertions above is not checked here." For the stub question
   to pass, the checkpoint has to test the phase's output directly, not something next to it.
   The exemption does not cover this. The builder's reason gives up only the red-before-build
   requirement on the pager assertions ("its coverage" is explicitly kept). It does not accept a
   durable copy that can be empty.

2. single-value-pin (rules/shape.md) — tests/tmp/test_12_similars_on_scroll_phase1.py:108
   assert sizes[:empty - 1] == [int(PAGE)] * (empty - 1) and 0 < sizes[empty - 1] <= int(PAGE), sizes  # C1
   The test sends `PAGE = "48"` (line 28) and checks for 48 coming back. The docstring (line 5)
   says 48 is also the similars default ("a run with no `limit` came back 48 x 6, 12"). That
   matches the fourth `<how_to_spot>` bullet: "The expected result equals the shipped default,
   so returning the default unchanged passes." A pager or fetch that drops `limit` passes this
   line. The rule requires the size reading to change with the input. Here one input is used and
   it matches the default.

RECOMMENDATIONS
1. EXEMPT C1: the exemption's line citations do not match the file (agent spec, `<verdict>`,
   `exempted_clauses`) — tests/tmp/test_12_similars_on_scroll_phase1.py:96-125
   The builder's reason cites the C1 carriers as :91, :92, :96, :101, :104 and the controls as
   :85-87, :90, :103. In the file, the lines tagged `# C1` are 96, 97, 101, 106, 108, 111, 124 and
   125. Line 104 is the `empty = next(...)` computation, not an assertion. Lines 85-87 are the
   `_seed` return and blank lines. Lines 91 and 92 are the batch-count check and the up-next
   control. As written, the exemption does not point at the assertions it claims to cover. The
   operator should re-confirm it against the real line numbers.

PREDICTED FAILURE
Fails at line 124 on `assert covered is not None`, because tests/active/test_frontend_upnext_pager.py
does not exist, so `claimed()` returns no `test_frontend_upnext_pager.py` group. The first test
(lines 87-111) is expected to pass before the phase, as the exemption concedes.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve (it
   is the phase's NEW file). Nothing in it could be checked.
2. client/frontend/src/data/videos.ts (`createFeedPager`, `fetchSimilarVideosPayload`) was not in
   `code_under_test` and was not read. The stub question for the pager test (lines 87-111) was
   answered from the assertion form alone. Apart from finding 2, the positive controls at lines
   95-96, 106 and 110 would turn a stub pager red.
3. `fixtures_path` was not supplied. The `engine` and `engine_client` fixtures were resolved from
   tests/active/conftest.py, which the test imports explicitly at line 24.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 4 must_prove, 9 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "48-row batches from the linux seed" | :108 (seed from `q=linux` at :82) | batches of any size other than 48 before the last non-empty one. It does not catch a query that drops `limit`, because the default is also 48 | EXEMPT |
| C1b | must_prove | "no row repeats" across batches | :97, :101 | a pager that neither sends `exclude` nor drops a row it has already seen | EXEMPT |
| C1c | must_prove | "an empty batch arrives within 10 batches" | :106 (control :91) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |
| C1d | must_prove | "no request is made after it" | :111 (control :110) | a pager that keeps fetching after it should have set `exhausted` | EXEMPT |
| D1 | docstring | runs "at the video page's 48-row batch" | :108 | a pager or query that returns batches of a size other than 48 before the last non-empty one | CARRIED |
| D2 | docstring | "first batch is an up-next page (`seed.mode == "upnext"`)" | :92 | a seed that resolves to a random mode or some other mode | CARRIED |
| D3 | docstring | "second batch holds rows and none of the first batch's" | :96, :97 | an empty second page, and a second page that repeats the first | CARRIED |
| D4 | docstring | "no later batch repeats a row of an earlier one" | :101 | a pager that excludes only the batch just before, not every earlier one | CARRIED |
| D5 | docstring | "driven for MAX_BATCHES calls and reaches an empty batch before the last" | :91, :106 | a crashed run that stops early, and an empty batch that comes only at index 9 or never | CARRIED |
| D6 | docstring | "No call after the empty batch makes a request, counted on the fetch function" | :111 | a `next()` that calls the given fetch after the feed is exhausted | CARRIED |
| D7 | docstring | "`test_frontend_upnext_pager.py` is discovered in tests/active" as a test group | :124 | a durable file missing from `tests/active`. `groups()` rglobs `active` (validate_tests.py:604-613) | CARRIED |
| D8 | docstring | withdrawn | n/a | n/a | CARRIED |
| D9 | docstring | claimed files "include `data/videos.ts`, … `server.py`, … `similarity_candidates.py` and `handlers/similar.py`" | :125 (controls :120, :122) | a `test_groups` entry that leaves out any of the four | CARRIED |
| N1 | name | "the pager's 48-row batches" | :108 | a pager that yields batches of a size other than 48 | CARRIED |
| N2 | name | "never repeat a row" | :101 | a pager that lets an Engine repeat through | CARRIED |
| N3 | name | "it stops asking after an empty batch" | :111 | a pager that still fetches after an empty batch | CARRIED |
| N4 | name | "the durable pager group" exists | :124 | a group that is absent | CARRIED |
| N5a | name | "fingerprinted over videos_ts, the client server and both engine similars files" | :125 | a mapping that is missing one of the four | CARRIED |
| N5b | name | withdrawn | n/a | n/a | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): D8 was withdrawn, not carried. tests/tmp/test_12_similars_on_scroll_phase1.py:6
   The docstring was narrowed rather than an assertion added. It now says: "That the durable file carries the pager assertions above is not checked here; it is left to review of that file."
   The first ledger's "the durable test itself" clause is gone.
   :124 still accepts a `test_frontend_upnext_pager.py` that asserts nothing about the pager.
2. whole-claim (rules/testing.md): N5b was withdrawn, not carried. tests/tmp/test_12_similars_on_scroll_phase1.py:114
   The name changed from "fingerprinted over the files it runs through" to "fingerprinted over videos_ts, the client server and both engine similars files".
   The docstring at :6 now says outright that `cache`, `local-likes`, `api-base` and `profile` are not checked. So the name was narrowed rather than the mapping widened.
3. surfaces / checkpoint_definition (rules/testing.md), no ledger row: tests/tmp/test_12_similars_on_scroll_phase1.py:124-125
   By the docstring's own account (:6), the phase's output is a durable copy of this test plus its config mapping.
   The only assertions that cover that output check the group's name and its claimed files. None checks the durable file's content. So the checkpoint proves the slice was registered, not that it behaves as C1 claims.
   The docstring now discloses this, and C1 is exempted, so this does not block. It is recorded for whoever reads the gate.
4. EXEMPT rows C1a-C1d: the operator exempted C1. The builder's reason says it is carried at ":91, :92, :96, :101 and :104, with controls at :85-87, :90 and :103". Those line numbers are stale.
   In the test as it now reads, C1 is carried at :97, :101, :106, :108 and :111, with controls at :83, :91, :92 and :110. The exemption is not wrong on substance, because C1 has assertions at this seam. The citation is out of date.
5. whole-claim (rules/testing.md): C1a/D1/N1, tests/tmp/test_12_similars_on_scroll_phase1.py:108
   The size bound excludes batches of any size other than 48. It cannot tell a sent `limit=48` from a dropped one, because the endpoint's default is also 48. The docstring at :5 says so.
   No rule requires more than the bound, so this goes on the record only.

NOT ASSESSED
1. `code_under_test` lists `tests/active/test_frontend_upnext_pager.py`, which does not resolve (FileNotFoundError). Its contents could not be read, so nothing here bears on what that file asserts.
2. `code_under_test` does not include `client/frontend/src/data/videos.ts` (`createFeedPager`, `fetchSimilarVideosPayload`), and it was not read. Bounds and the abnormal path of the pager were judged from the test alone.
3. `fixtures_path` was none. `engine_client` and `engine` are imported from `tests/active/conftest.py:24`. Only their scope was checked: `engine` is session-scoped at :105, `engine_client` is function-scoped at :148. Their bodies were not read.

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - self-check (audit round 3, send-back 1)

`tests/tmp/test_12_similars_on_scroll_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:124, :125, :129: batch 2 is non-empty, batches 1 and 2 share no (video_id, instance_domain) row, and no batch repeats a row from any earlier batch, across all 10 batches. - expected: Observed batch sizes 48 x 6, 12, 0, 0, 0 with no overlaps, so all three hold. - excludes: A pager that stops sending `exclude` and does not dedup gets repeated rows from the Engine's random draw, so :125/:129 read a non-empty intersection. A pager that excludes only the previous batch fails :129 on a later batch.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:134: an empty batch arrives before the last of the 10 calls. Controls: :119 (exactly 10 batches reported) and :118 (no error line). - expected: The first empty batch is at index 7. - excludes: A feed that never runs dry, or runs dry only at index 9: `empty` is None or 9, and the assertion fails.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:136 and :142: every batch before the last non-empty one has exactly 48 rows and the last non-empty one has 1..48; a second run of the same seed at limit "20" for 2 batches has sizes [20, 20]. - expected: sizes[:6] == [48]*6 and sizes[6] == 12, and the limit-20 run reads [20, 20] (observed this turn). - excludes: A pager that merges two fetches (96 rows) or trims a full page fails :136. A query that drops `limit` or hardcodes 48 comes back at the 48 default, so :142 reads [48, 48] and fails.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:139: every `next()` after the empty batch leaves the counted fetch calls unchanged. Control :138: calls go 1..8 up to and including the empty batch. - expected: calls [1..8, 8, 8]. - excludes: A pager that never sets `exhausted` keeps calling the fetch, so calls read 9, 10 and the assertion fails.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:146, :162: the durable tests/active/test_frontend_upnext_pager.py exists. With its `_run` swapped for canned batches, its test raises AssertionError on each of six wrong-pager sets: repeats a row of an earlier batch, never runs dry, keeps asking after the empty batch, mode other than upnext, empty second batch, crash partway. Controls: :148 (it defines a test) and :151 (the observed batch shape passes). - expected: After the phase lands, :162 reads [] (observed against the plan's drafted file this turn). Before the phase, :146 fails because the file is absent (observed). - excludes: A durable file that is empty, has a `pass` body, or drops any of the pager assertions (no-repeat, empty-within-budget, no-calls-after, upnext mode, crash guard). The labels of the sets it does not fail on appear in :162's list. Observed: a `pass` stub fails here.
- C1 - tests/tmp/test_12_similars_on_scroll_phase1.py:173, :174: `claimed` discovers a group `test_frontend_upnext_pager.py`, and its files include all four SUBJECTS. Controls: :169 (an existing group carries its mapping) and :171 (all four subjects exist). - expected: After the phase, `covered` contains videos.ts, server.py, similarity_candidates.py and handlers/similar.py. Before it, covered is None. - excludes: A phase that adds no durable file fails :173. A config.json entry missing any of the four files fails :174, which lists the missing file.

Exemptions the operator granted, verified against the agent's own transcript: C1

<exemptions>
none
</exemptions>

<items>
<item id="D1">
<disposition>fixed</disposition>
<what>Two assertions now carry this. :136 requires exactly 48 rows in every batch before the last non-empty one, and 1 to 48 rows in that one. The new :142 runs the same seed a second time at limit "20" for 2 batches and requires sizes [20, 20]. I observed [20, 20] this turn, with calls [1, 2] and mode upnext on both. Because the similars default is 48, a pager or query that drops `limit` or hardcodes 48 now reads [48, 48] at :142 and fails. A pager that merges or trims pages fails :136. I rewrote docstring bullet 3 to describe the second run.</what>
</item>
<item id="D8">
<disposition>fixed</disposition>
<what>A new test at :145-162 checks the durable file's behaviour, not only its registration. :146 requires tests/active/test_frontend_upnext_pager.py to exist. The test then loads that file and swaps its own `_run`/`_seed` for canned batches. Control at :151: the batch shape the live run observed (48 x 6, 12, 0, 0, 0; calls 1..8, 8, 8) must pass. :162: each of six wrong-pager batch sets must make the durable test raise AssertionError. The six are: a row of batch 0 repeated in batch 3, a feed that never runs dry, calls 9 and 10 after the empty batch, mode "random", an empty second batch, and a crash partway. I observed this turn: the plan's drafted durable file (plan :683-778) passes the whole test, a durable file whose test body is `pass` fails at :162, and the absent file fails at :146. I rewrote docstring bullet 4 to match and removed the "left to review of that file" sentence.</what>
</item>
<item id="N1">
<disposition>fixed</disposition>
<what>The name's "48-row batches" is carried by :136 (exactly 48 per full batch, 1..48 for the last non-empty one). :142 (limit 20 gives [20, 20]) shows the size comes from the limit sent and not the 48 default. It excludes merged or trimmed pages, a wrong limit, and a dropped or hardcoded limit.</what>
</item>
<item id="N5b">
<disposition>justified</disposition>
<what>The name is narrowed to `test_the_durable_pager_group_is_fingerprinted_over_videos_ts_the_client_server_and_both_engine_similars_files` (:165), which names exactly the four `SUBJECTS` that :174 checks. The docstring says that `data/videos.ts`'s imports (`cache`, `local-likes`, `api-base`, `profile`) are not in the plan's mapping and are not checked. I did not widen `SUBJECTS`, because the operator-approved mapping at plan :800-805 lists only these four.</what>
</item>
</items>

<findings_addressed>
Shape CRITICAL 1 (stub question: an empty or `pass` durable file passed): fixed with a new test at :145-162. It loads tests/active/test_frontend_upnext_pager.py and swaps its `_run`/`_seed` for canned batches. It requires the durable test to pass the batch shape the live run observed (:151) and to raise AssertionError on each of six wrong-pager batch sets (:162). Observed this turn: the plan's draft passes, a `pass`-body stub fails at :162, and the missing file fails at :146.
Shape CRITICAL 2 (single-value pin at 48, which is also the default): fixed. :142 runs the same seed again at limit "20" for 2 batches and requires [20, 20] (observed [20, 20] this turn). A dropped or hardcoded limit now reads 48 and fails. This costs 2 extra Engine requests, not a second full run.
Shape REC 1 (stale line numbers in the C1 exemption): not re-asked, because the exemption stands. With this edit, the current C1 carriers are :124, :125, :129, :134, :136, :139, :142, :146, :162, :173 and :174, with controls at :118-120, :123, :138, :148, :151, :169 and :171.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:124, :125, :129: batch 2 is non-empty, batches 1 and 2 share no (video_id, instance_domain) row, and no batch repeats a row from any earlier batch, across all 10 batches.</assertion>
<expected>Observed batch sizes 48 x 6, 12, 0, 0, 0 with no overlaps, so all three hold.</expected>
<wrong_implementation>A pager that stops sending `exclude` and does not dedup gets repeated rows from the Engine's random draw, so :125/:129 read a non-empty intersection. A pager that excludes only the previous batch fails :129 on a later batch.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:134: an empty batch arrives before the last of the 10 calls. Controls: :119 (exactly 10 batches reported) and :118 (no error line).</assertion>
<expected>The first empty batch is at index 7.</expected>
<wrong_implementation>A feed that never runs dry, or runs dry only at index 9: `empty` is None or 9, and the assertion fails.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:136 and :142: every batch before the last non-empty one has exactly 48 rows and the last non-empty one has 1..48; a second run of the same seed at limit "20" for 2 batches has sizes [20, 20].</assertion>
<expected>sizes[:6] == [48]*6 and sizes[6] == 12, and the limit-20 run reads [20, 20] (observed this turn).</expected>
<wrong_implementation>A pager that merges two fetches (96 rows) or trims a full page fails :136. A query that drops `limit` or hardcodes 48 comes back at the 48 default, so :142 reads [48, 48] and fails.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:139: every `next()` after the empty batch leaves the counted fetch calls unchanged. Control :138: calls go 1..8 up to and including the empty batch.</assertion>
<expected>calls [1..8, 8, 8].</expected>
<wrong_implementation>A pager that never sets `exhausted` keeps calling the fetch, so calls read 9, 10 and the assertion fails.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:146, :162: the durable tests/active/test_frontend_upnext_pager.py exists. With its `_run` swapped for canned batches, its test raises AssertionError on each of six wrong-pager sets: repeats a row of an earlier batch, never runs dry, keeps asking after the empty batch, mode other than upnext, empty second batch, crash partway. Controls: :148 (it defines a test) and :151 (the observed batch shape passes).</assertion>
<expected>After the phase lands, :162 reads [] (observed against the plan's drafted file this turn). Before the phase, :146 fails because the file is absent (observed).</expected>
<wrong_implementation>A durable file that is empty, has a `pass` body, or drops any of the pager assertions (no-repeat, empty-within-budget, no-calls-after, upnext mode, crash guard). The labels of the sets it does not fail on appear in :162's list. Observed: a `pass` stub fails here.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase1.py:173, :174: `claimed` discovers a group `test_frontend_upnext_pager.py`, and its files include all four SUBJECTS. Controls: :169 (an existing group carries its mapping) and :171 (all four subjects exist).</assertion>
<expected>After the phase, `covered` contains videos.ts, server.py, similarity_candidates.py and handlers/similar.py. Before it, covered is None.</expected>
<wrong_implementation>A phase that adds no durable file fails :173. A config.json entry missing any of the four files fails :174, which lists the missing file.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every absence assertion has a positive control. :125/:129 are armed by :123/:124 and :119. :139 is armed by :138 and :134. :162 (the durable test fails on each wrong set) is armed by :151 (it passes the good set), so a durable test that always raises cannot pass, and one that never raises fails :162.
2. No. :136/:142 compare observed batch lengths with the limit that was sent. :162 feeds canned batches into the durable file's own assertions and does not recompute anything production does. Deleting the `limit` param in buildSimilarUrl turns :142 red ([48, 48]). Deleting any pager assertion from the durable file turns :162 red.
3. Fixed. Batch size is now read at two inputs, 48 (:136) and 20 (:142), and 20 is not the default. The durable test is driven with one passing input and six failing ones.
4. No. The runner shims only the browser platform objects. In the new test, the doubles replace the durable file's own `_run`/`_seed` helpers. The subject there is the durable test's assertions, and the live pager is exercised by the first test.
5. Yes, it collects. This turn a probe loaded the module and called the new test: it bound, and it ran against the absent file, the plan's draft and a stub. `types` is imported. `_load` replaces the inline harness loading in the last test.
6. Yes, all observed this turn. Limit 20 x 2 gave [20, 20] with calls [1, 2], mode upnext. The plan's draft passes the good set and fails all six wrong sets, each with an AssertionError. A `pass` stub fails at :162. The 48 x 6/12/0 shape and calls 1..8, 8, 8 are from last turn's live probe.
7. Yes. Before the phase, the pager test is green (characterization, under the standing C1 exemption). The new test fails at :146 because the durable file is absent (observed), and the group test fails at :173 with covered None. Both are red for the phase's reason. I emptied the probe files tests/tmp/probe_12_durable.py, draft_upnext_pager.py and draft_stub_pager.py so they collect nothing. I have no delete tool, so they still need removing, along with last turn's emptied probes.
</answers>

Gate: satisfied

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - red (audit round 3)

`tests/tmp/test_12_similars_on_scroll_phase1.py` exited 1.

```
  tests/tmp/test_12_similars_on_scroll_phase1.py  2 failed, 1 passed                     0.0s
  ----------------------------------------------
  total                                           2 failed, 1 passed                     7.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - audit (round 3)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. EXEMPT C1: stub question (rules/shape.md `<ladder>` / stub question) — tests/tmp/test_12_similars_on_scroll_phase1.py:118-142
   `assert sizes[:empty - 1] == [int(PAGE)] * (empty - 1) and 0 < sizes[empty - 1] <= int(PAGE), sizes  # C1`
   The first test passes against the code as it stands, which is "the previous behaviour left unchanged". That is the red-before-build concession the builder's reason describes. Its assertion form is still sound. Rung 2 fits: the pager is TypeScript run as a node subprocess over the real bundle. Line 120 is a positive control. Lines 124, 125 and 129 check that no row repeats across batches. Lines 138-139 count calls up to the empty batch and after it. Lines 141-142 run a second input (limit 20 against the default 48), so a pager that ignores `limit` goes red, which avoids `single-value-pin`. The exemption itself looks right. One problem: the reason cites :91, :92, :96, :101, :104 and controls at :85-87, :90, :103. In this file those lines are helper bodies (`_load`, `_canned`, `_fails`, `_seed`). The C1 assertions are at 124-142, with controls at 118-120 and 138. The gate record should fix those line references so they point at the assertions.

PREDICTED FAILURE
Fails at line 146 on `assert DURABLE.is_file(), DURABLE`, because tests/active/test_frontend_upnext_pager.py does not exist yet. It also fails at line 173 on `assert covered is not None, sorted(claims)`: with no file there, `groups()` finds no `test_frontend_upnext_pager.py` group, and config.json's `test_groups` has no entry for it. The controls at 169 and 171 hold: `test_frontend_video_page.py` is mapped to `video-page/index.ts`, and all four SUBJECTS exist. The first test (lines 116-142) is expected green, as the exemption says.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not exist yet. The stub question for the second test was answered from its own form only. Line 151 checks that a pager meeting the contract passes, line 162 checks that six wrong pagers fail, and together they make an always-pass or always-fail durable test go red. How the durable file itself will be shaped was not assessed.
2. `fixtures_path` was not supplied. The fixture `engine_client` is imported from tests/active/conftest.py (line 25). I grepped that file for `engine`, `engine_client` and `.base` but did not read it in full, and I did not verify the fixture's `request()` return shape.
3. The first test's live behaviour: nothing was executed. My view that it is green on current code rests on the exemption's account and on `createFeedPager` and `fetchSimilarVideosPayload` both being in client/frontend/src/data/videos.ts (:37, :130).

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 4 must_prove, 9 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "48-row batches from the linux seed" | :136, :142 (setup `q=linux` :84) | a batch that is not 48 before the last non-empty one; a query that drops `limit` (the default is also 48, so the limit-20 run would come back 48 x 2) | EXEMPT |
| C1b | must_prove | "no row repeats" across batches | :125, :129 | a pager that neither sends `exclude` nor drops a row from any earlier batch | EXEMPT |
| C1c | must_prove | "an empty batch arrives within 10 batches" | :134 (control :119) | a feed that never runs dry, or runs dry only on the last call | EXEMPT |
| C1d | must_prove | "no request is made after it" | :139 (control :138) | a `next()` that calls the fetch function once the feed is exhausted | EXEMPT |
| D1 | docstring | runs "at the video page's 48-row batch" | :136, :142 | a batch size other than 48; a batch size that ignores the `limit` sent | CARRIED |
| D2 | docstring | "first batch is an up-next page (`seed.mode == "upnext"`)" | :120 | a seed that resolves to random or another mode | CARRIED |
| D3 | docstring | "second batch holds rows and none of the first batch's" | :124, :125 | an empty second page; a second page that repeats the first | CARRIED |
| D4 | docstring | "no later batch repeats a row of an earlier one" | :129 | a pager that excludes only the batch just before, not every earlier one (`seen` is cumulative) | CARRIED |
| D5 | docstring | "driven for MAX_BATCHES calls and reaches an empty batch before the last" | :119, :134 | a run that crashed and stopped early; an empty batch only at index 9, or never | CARRIED |
| D6 | docstring | "No call after the empty batch makes a request, counted on the fetch function" | :139 | a `next()` that calls the `createFeedPager` fetch argument after exhaustion | CARRIED |
| D7 | docstring | "A test group named `test_frontend_upnext_pager.py` is discovered in tests/active" | :173 (control :169) | a durable file missing from `tests/active`. `claimed()` keys only on groups that `groups()` rglobs from `active` | CARRIED |
| D8 | docstring | "the durable test itself": passes contract batches, and fails with AssertionError on repeat / never dry / keeps asking / other mode / empty second / crash | :146, :148, :151, :162 | a missing durable file; a durable file with no `test_*`; a durable test that asserts nothing (fails :162); one that checks only adjacent batches (repeat planted at batch 3 vs 0, :153) | CARRIED |
| D9 | docstring | claimed files "include `data/videos.ts`, … `server.py`, … `similarity_candidates.py` and `handlers/similar.py`" | :174 (control :171) | a `test_groups` entry that leaves out any of the four | CARRIED |
| N1 | name | "the pager's 48-row batches" | :136, :142 | a batch size other than 48, or one that does not follow `limit` | CARRIED |
| N2 | name | "never repeat a row" | :129 | a pager that lets an Engine repeat through | CARRIED |
| N3 | name | "it stops asking after an empty batch" | :139 | a pager that still fetches after an empty batch | CARRIED |
| N4 | name | "the durable pager test is a group" | :173 | the group is absent from discovery | CARRIED |
| N5a | name | "fingerprinted over" the four named subjects | :174 | a mapping missing one of the four | CARRIED |
| N5b | name | withdrawn | n/a | n/a | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. re-audit, N5b (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:165
   The name used to say "the files it runs through". It now names only "videos_ts the client server and both engine similars files". The docstring at :6 now says outright that `cache`, `local-likes`, `api-base` and `profile` "are not in the plan's mapping and are not checked". The prose was narrowed; no assertion was added. The row is closed by withdrawal.
2. re-audit, D8 (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:6, :151, :162
   Two things changed here. Assertions were added (:151 control, :162 six wrong batch sets). The prose was also narrowed: "The batches are canned, so the durable file's live run is not repeated here". What is proved is that the durable file's assertions reject the listed wrong batch sets. Nothing proves that its live `_run` drives the real pager.
3. Not a ledger row (rules/testing.md whole-claim). tests/tmp/test_12_similars_on_scroll_phase1.py:104, :151
   `_fails` replaces `durable._run` with `lambda *args: batches`. Every call therefore returns the same 48 x 6, 12 batches. A durable test that repeats this file's limit-20 check (:141–142) would fail the control at :151. None of the wrong sets at :154–161 has a wrong batch size. So neither the control nor the mutations require the durable copy to carry C1a. That clause is EXEMPT here, and the durable copy may legitimately be weaker than this test on batch size.
4. Exemption record. The builder's reason cites :91, :92, :96, :101, :104 and controls :85-87, :90, :103. None of those lines matches the file as it now reads. C1 is currently carried at :120, :124, :125, :129, :134, :136, :139 and :142, with controls at :119 and :138. The exemption is not wrong: every C1 sub-clause is asserted anyway. Only the citations are stale.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_frontend_upnext_pager.py, which does not resolve. The durable file's contents were not read. D7, D8 and N4 were judged only by what this test asserts about that file, not by what the file does.
2. `fixtures_path` was not supplied. The test imports `engine` and `engine_client` from tests/active/conftest.py (:25). Their definitions were found at conftest.py:106 and :149 by search. Their bodies were not read in full.

## 2026-09-28 - Step 7 - Phase 1 (Up-next pager contract test) - checkpoint outcome (run 1)

`tests/tmp/test_12_similars_on_scroll_phase1.py` exited 0 after the phase landed.

<changes>
### `tests/active/test_frontend_upnext_pager.py` (NEW)
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_upnext_durable.py — a probe that could not be deleted with the tools available; it holds no phase code and should be removed.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_12_similars_on_scroll_phase1.py  3 passed                               0.0s
  ----------------------------------------------
  total                                           3 passed                               7.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 2 (First similar batch through the pager) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`loadSimilarVideos` in `pages/video-page/index.ts` fetches its first batch through a fresh feed pager asking `/recommendations` for 48 rows, and puts only the first 8 of them into `#similar-videos`.

- C1 - The first `/recommendations` request the page makes carries limit 48.
- C2 - From a 48-row answer, `#similar-videos` holds exactly 8 cards.

must_prove:
- C1 - The first `/recommendations` request the page makes carries limit 48.
- C2 - From a 48-row answer, `#similar-videos` holds exactly 8 cards.

## 2026-09-28 - Step 7 - Phase 2 (First similar batch through the pager) - self-check (audit round 1, send-back 0)

`tests/tmp/test_12_similars_on_scroll_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_12_similars_on_scroll_phase2.py:124 — exactly one request reached `/recommendations`. Then :125 — that request is a POST and its `limit` query parameter is "48". - expected: One request, `{'method': 'POST', 'path': '/recommendations', 'query': {..., 'limit': '48'}, ...}`. The run confirmed the shape: a single POST that carries `limit` in the query string. Today its value is '8'. - excludes: Case 1: the page keeps today's `limit: "8"` at index.ts:307. The run read `'limit': '8'`, so :125 fails ('8' == '48'). Case 2: the first batch is split into an 8-row request plus a follow-up at mount. That gives two `/recommendations` entries, so :124 fails.
- C2 - tests/tmp/test_12_similars_on_scroll_phase2.py:129 — `#similar-videos` holds exactly 8 `similar-card-item` anchors. Then :131 — their `data-video-key` ids are v0..v7, in order. - expected: 8 anchors with keys `videos.example::v0` … `videos.example::v7`. - excludes: Case 1: the page renders every row it gets back (index.ts:315, `rows.map(renderSimilarCard)` with no cap). Given the 48-row answer, the probe counted 48 anchors, ids v0..v47, so :129 fails. Case 2: the page caps at 8 but takes the wrong slice (last 8, or skips already-seen rows). The count is 8 but the ids are not v0..v7, so :131 fails.

<assertions>
tests/tmp/test_12_similars_on_scroll_phase2.py:110 - control: `/api/video` is among the requested paths, so the page module ran its loads and a missing similars request is the page's fault, not the runner's. No clause.
tests/tmp/test_12_similars_on_scroll_phase2.py:124 - exactly one request to `/recommendations` was made; a second eager or fill-viewport batch fails this. C1
tests/tmp/test_12_similars_on_scroll_phase2.py:125 - that request is a POST and its URL's `limit` query parameter is "48". The unchanged page sends "8" and fails here, as observed. With the operator's approval this is the query string, not the body. C1
tests/tmp/test_12_similars_on_scroll_phase2.py:129 - `#similar-videos` markup holds exactly 8 `similar-card-item` anchors, counted by regex over what `innerHTML` sets plus what `insertAdjacentHTML` adds. The unchanged page renders all 48 (observed). C2
tests/tmp/test_12_similars_on_scroll_phase2.py:131 - those 8 cards are rows v0..v7 of the 48-row answer, in order, read from each card's `data-video-key`; rendering the last 8 or a reordered 8 fails. C2
</assertions>

<probes>
1. `ValidateTests tests/tmp/probe_12_phase2_request.py` ran the unchanged page under the recording runner, with `/recommendations` answering 48 rows. It printed `REQ {'method': 'POST', 'path': '/recommendations', 'search': '?id=v1&host=peer.example&limit=8', 'body': '{"likes":[]}'}` and `CARDS 48`. So the limit travels in the query string, never the body. client/backend/server.py:89 also reads `limit` as a query param. The Step-6 seam said "body's limit"; I raised this with AskUser and the operator answered "Assert the query-string limit".
2. `ValidateTests tests/tmp/test_12_similars_on_scroll_phase2.py` against the unchanged page failed at line 125 with `'limit': '8'` vs '48'. Before that, the control (`/api/video` requested) and the single-request assertion both passed, so it is red for the right reason.
3. `ValidateTests tests/tmp/probe_12_phase2_cards.py` ran this file's own `_page` plus its card and id regexes over the unchanged page's real markup. It printed `COUNT 48 IDS ['v0', ... 'v9'] ['v46', 'v47'] OBSERVED []`, so the regexes read real cards and ids in order, and C2 fails on the old behaviour (48 ≠ 8).
No delete tool is available: tests/tmp/probe_12_phase2_request.py and tests/tmp/probe_12_phase2_cards.py are still on disk and should be removed; the checkpoint now carries what they showed.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_12_similars_on_scroll_phase2.py` - 8497 characters, inlined in full

```
"""The video page's similars, run in node with the real page module: its first batch is one `/recommendations` request for 48 rows, of which only the first 8 are shown.

- The page makes exactly one `/recommendations` request, a POST whose `limit` query parameter is "48" (the limit travels in the query string; the JSON body carries only likes and exclusions).
- Answered with 48 distinct rows in up-next mode, `#similar-videos` holds exactly 8 `similar-card-item` anchors, and they are the answer's first 8 rows in order.

The runner is the one in `tests/active/test_frontend_video_page.py`, plus an `IntersectionObserver` that never fires, a document taller than the window so filling the viewport never asks for more, and element markup that keeps what `insertAdjacentHTML` adds as well as what `innerHTML` sets. `fetch` records each request's method, path, query and JSON body, answers `/recommendations` with the 48 rows and `{}` elsewhere.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
ROWS = 48
SHOWN = 8

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
// The document is far taller than the window and nothing has scrolled, so a fill-viewport pass never asks for another batch.
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: "?id=v1&host=peer.example" },
  localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage, innerHeight: 800, scrollY: 0,
  addEventListener() {}, removeEventListener() {} };
const text = (value) => ({ nodeType: 3, textContent: String(value) });
const nodes = (items) => items.map((n) => (typeof n === "string" ? text(n) : n));
const element = (tag, hidden = false) => {
  const classes = new Set();
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), hidden, children: [], dataset: {}, style: {}, attrs: {}, parentElement: null,
    get textContent() { return el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.children = v == null || v === "" ? [] : [text(v)]; },
    // Markup is kept opaque: text only reaches a report through textContent or a text node.
    get innerHTML() { return el.children.map((c) => c.html ?? (c.nodeType === 1 ? c.outerHTML : "")).join(""); },
    set innerHTML(v) { el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
    get outerHTML() { return `<${tag} class="${el.className}">${el.innerHTML}</${tag}>`; },
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); String(v).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    classList: { add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c), toggle: (c, force) => { const on = force ?? !classes.has(c); if (on) classes.add(c); else classes.delete(c); return on; } },
    append: (...items) => { el.children.push(...nodes(items)); },
    appendChild: (child) => { el.children.push(child); return child; },
    replaceChildren: (...items) => { el.children = nodes(items); },
    setAttribute: (name, value) => { if (name === "hidden") el.hidden = true; else if (name === "class") el.className = value; else el.attrs[name] = String(value); },
    removeAttribute: (name) => { if (name === "hidden") el.hidden = false; else delete el.attrs[name]; },
    toggleAttribute: (name, force) => { const on = force ?? !(name === "hidden" ? el.hidden : name in el.attrs); el[on ? "setAttribute" : "removeAttribute"](name, ""); return on; },
    getAttribute: (name) => (name === "hidden" ? (el.hidden ? "" : null) : el.attrs[name] ?? null),
    getBoundingClientRect: () => ({ top: 10000, bottom: 10000, left: 0, right: 0, width: 0, height: 0 }),
    closest: () => null, querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, remove() {},
    insertAdjacentHTML: (position, html) => { const node = { nodeType: 0, textContent: "", html: String(html) }; if (position === "afterbegin") el.children.unshift(node); else el.children.push(node); },
  };
  return el;
};
const byId = new Map();
globalThis.document = {
  title: "", body: element("body"), documentElement: { scrollHeight: 10000, clientHeight: 800 },
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, element("div")); return byId.get(id); },
  createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
// Captured and never fired: this checkpoint covers the first batch only, before any scroll.
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.observed = []; observers.push(this); }
  observe(target) { this.observed.push(target); } unobserve() {} disconnect() {} };
const requests = [];
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: init?.method ?? "GET", path: url.pathname, query: Object.fromEntries(url.searchParams), body: init?.body ? JSON.parse(init.body) : null });
  const body = url.pathname === "/recommendations" ? process.env.RECOMMENDATIONS_BODY : "{}";
  return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
};
await import(process.env.BUNDLE);
// Every stubbed fetch resolves at once, so the page's loads have settled within a few macrotasks.
for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
process.stdout.write(JSON.stringify({ requests, similar: byId.get("similar-videos")?.innerHTML ?? null, observed: observers.map((o) => o.observed.length) }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_similars")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _page(bundle: Path) -> dict:
    rows = [{"video_id": f"v{i}", "instance_domain": "videos.example"} for i in range(ROWS)]
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "RECOMMENDATIONS_BODY": json.dumps({"rows": rows, "seed": {"mode": "upnext"}})},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page module ran its loads, so a missing similars request below is the page's, not the runner's
    assert "/api/video" in [r["path"] for r in page["requests"]], page["requests"]
    return page


def test_the_first_batch_is_one_recommendations_request_for_48_rows_of_which_the_first_8_are_shown(bundle):
    page = _page(bundle)

    recommendations = [r for r in page["requests"] if r["path"] == "/recommendations"]
    assert len(recommendations) == 1, recommendations  # C1
    assert recommendations[0]["method"] == "POST" and recommendations[0]["query"].get("limit") == str(ROWS), recommendations  # C1

    markup = page["similar"] or ""
    cards = re.findall(r'<a\b[^>]*\bclass="[^"]*\bsimilar-card-item\b[^"]*"[^>]*>', markup)
    assert len(cards) == SHOWN, (len(cards), markup[:400])  # C2
    shown = [re.search(r'data-video-key="videos\.example::(v\d+)"', card) for card in cards]
    assert [m.group(1) if m else None for m in shown] == [f"v{i}" for i in range(SHOWN)], cards  # C2

```


Gate: satisfied

## 2026-09-28 - Step 7 - Phase 2 (First similar batch through the pager) - red (audit round 1)

`tests/tmp/test_12_similars_on_scroll_phase2.py` exited 1.

```
  tests/tmp/test_12_similars_on_scroll_phase2.py  1 failed                               0.0s
  ----------------------------------------------
  total                                           1 failed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 2 (First similar batch through the pager) - audit (round 1)

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
Fails at tests/tmp/test_12_similars_on_scroll_phase2.py:125. The single `/recommendations` POST has `recommendations[0]["query"].get("limit") == "8"`, not `"48"`, because `loadSimilarVideos` in client/frontend/src/pages/video-page/index.ts:307 still passes `limit: "8"` to `fetchSimilarVideosPayload`.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_frontend_video_page_similars.py (NEW), which does not resolve. Nothing in the test under audit imports it, so the audit covered only the test file, client/frontend/src/pages/video-page/index.ts, and `buildSimilarUrl`/`fetchSimilarVideosPayload` in client/frontend/src/data/videos.ts.
2. The runner's docstring (lines 6–7) says it copies the harness from tests/active/test_frontend_video_page.py. That file was not read. The runner used here is defined inline at lines 24–89, and that inline copy was assessed.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (15 clauses: 2 must_prove, 9 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | the first `/recommendations` request is the one checked (no earlier or extra one) | :124 | a page that sends a second batch request, e.g. the old limit-8 call plus a new limit-48 call | CARRIED |
| C1b | must_prove | that request "carries limit 48" | :125 | a request with `limit=8` (the current value), no limit, or the limit sent somewhere else | CARRIED |
| C2 | must_prove | "from a 48-row answer, `#similar-videos` holds exactly 8 cards" | :129 | a page that renders all 48 rows, or fewer than 8, into `#similar-videos` | CARRIED |
| D1 | docstring | "run in node with the real page module" | :116 | a runner where the bundled page never ran its loads, so a missing request reads as the page's fault | CARRIED |
| D2 | docstring | "its first batch is one `/recommendations` request for 48 rows" | :124, :125 | several requests, or one request for a different number of rows | CARRIED |
| D3 | docstring | "of which only the first 8 are shown" | :129, :131 | showing all rows, or showing 8 that are not the first 8 | CARRIED |
| D4 | docstring | "exactly one `/recommendations` request" | :124 | two or more requests, or none | CARRIED |
| D5 | docstring | "a POST" | :125 | a GET to `/recommendations` | CARRIED |
| D6 | docstring | "whose `limit` query parameter is \"48\" (the limit travels in the query string)" | :125 | the limit sent only in the JSON body, or a different value in the query | CARRIED |
| D7 | docstring | "answered with 48 distinct rows in up-next mode, … exactly 8 `similar-card-item` anchors" | :129 | a count of anything other than 8 anchors of that class | CARRIED |
| D8 | docstring | "they are the answer's first 8 rows in order" | :131 | the last 8 rows, 8 rows in a shuffled order, or anchors with no `data-video-key` | CARRIED |
| D9 | docstring | harness: "filling the viewport never asks for more" | :124 | a fill-viewport pass that sends a second batch request would fail the single-request check | CARRIED |
| D10 | docstring | harness: `fetch` "records each request's method, path, query and JSON body, answers `/recommendations` with the 48 rows and `{}` elsewhere" | :116, :125 | a stub that records nothing: the control and the method/query checks read what it recorded | CARRIED |
| N1 | name | "the first batch" | :124 | a page that has already requested a later batch by the time the test reads | CARRIED |
| N2 | name | "is one recommendations request" | :124 | more than one request, or none | CARRIED |
| N3 | name | "for 48 rows" | :125 | a limit other than 48 | CARRIED |
| N4 | name | "of which the first 8 are shown" | :129, :131 | the wrong count, or the right count taken from the wrong rows | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase2.py:107
   `rows = [... for i in range(ROWS)]`: the only answer tried has 48 rows. Nothing tests an answer at or below the display count: 0 rows (the code's `No similar videos found.` branch), 1 row, exactly 8, or 7. An implementation that pads to 8 or breaks on a short answer is not excluded.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase2.py:81
   `fetch` always returns 200, so only the success path runs. The failure the page is built to handle is untested: a non-OK `/recommendations` response rendering the `.error` block, and a 401 rendering the key-rejected notice.
3. whole-claim (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase2.py:87
   The runner writes out `observed` (the observer targets) and records each request's `body`, and no assertion reads either. No rule is broken because the docstring does not claim anything from them. This is noted only because captured-but-unasserted output reads like coverage.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_frontend_video_page_similars.py (NEW), and that path does not resolve. Nothing in it could be read.
2. `fixtures_path` was not supplied. The test uses only its own module fixture `bundle` (:92) and pytest's built-in `tmp_path_factory`, so no conftest was needed to judge independence.
3. The docstring (:6) says the runner is "the one in `tests/active/test_frontend_video_page.py`". That file was not compared with `RUNNER`. It is a provenance claim, not a behavioural clause.

## 2026-09-28 - Step 7 - Phase 2 (First similar batch through the pager) - checkpoint outcome (run 1)

`tests/tmp/test_12_similars_on_scroll_phase2.py` exited 0 after the phase landed.

<changes>
### `client/frontend/src/pages/video-page/index.ts` (EDITED)
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
  tests/tmp/test_12_similars_on_scroll_phase2.py  1 passed                               0.0s
  ----------------------------------------------
  total                                           1 passed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
Once the first similar batch is shown, each sentinel intersection appends the next 8 fetched rows to `#similar-videos`, and an intersection that finds no unrevealed row asks the pager for the next batch, excluding the rows already shown.

- C1 - A sentinel intersection appends the next 8 cards, and the cards already shown stay in place.
- C2 - An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown.

must_prove:
- C1 - A sentinel intersection appends the next 8 cards, and the cards already shown stay in place.
- C2 - An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown.

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - self-check (audit round 1, send-back 0)

`tests/tmp/test_12_similars_on_scroll_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_12_similars_on_scroll_phase3.py:151 — one sentinel intersection adds exactly one `insertAdjacentHTML` call on `#similar-videos`; :153 — that call's position is "beforeend"; :154 — its markup holds exactly the `similar-card-item` anchors of rows v8..v15, in order; :155 — the grid's `innerHTML` setter was not called during the intersection; :156 — the grid markup still starts with the first-8-card markup (pinned to v0..v7 by the :148 control); :160 — after five intersections the grid shows v0..v47 in order - expected: One insert, position "beforeend", keys v8..v15, writes unchanged, prefix kept, and v0..v47 after five intersections. A correct stand-in page (real `createFeedPager` from data/videos.ts, an IntersectionObserver on `getElementById("similar-sentinel")`, `insertAdjacentHTML("beforeend", …)` per 8-row slice), run under this exact runner and test function, PASSED. Against the current code the run reads `(0, 0, 0)` at :151: no observer watches the sentinel and no insert happened. - excludes: Today's page, where nothing watches the sentinel: :151 reads (0, 0, 0) (observed). A reveal that re-renders the grid through `innerHTML` instead of appending: :151 reads (1, 0, 0), i.e. no insert (observed in the stand-in probe), and :155 would catch the extra write. An "afterbegin" insert fails :153. A chunk other than 8, or a slice repeating v0..v7, fails :154. A reveal that stops early or skips rows fails :160.
- C2 - tests/tmp/test_12_similars_on_scroll_phase3.py:161 — after five intersections, with all 48 rows revealed, still only one `/recommendations` request; :164 — after the sixth intersection exactly two `/recommendations` requests; :166 — the second is a POST; :168 — its body's `exclude` has exactly 48 entries whose (id, host) pairs are exactly (v0..v47, videos.example) - expected: 1 request at the fifth snapshot, 2 in total after the sixth, the second a POST with `exclude` = the 48 `{id, host}` pairs of the first answer. The correct stand-in passed all four under this runner. The `{id, host}` shape of `exclude` came from the earlier probe of `createFeedPager` over `fetchSimilarVideosPayload`, which printed `"exclude":[{"id":"v0","host":"videos.example"},…]`. Against the current code the run stops at :151 before reaching these lines. - excludes: A page that sends the pager an empty exclude list: :168 reads [] (observed in the stand-in probe). One that excludes only the first 8 shown rows fails :168 on the length and the pairs. One that prefetches the next batch before every row is shown makes :161 read 2. One that never asks for more, or asks twice, fails :164.

<assertions>
tests/tmp/test_12_similars_on_scroll_phase3.py:148 — control: before any intersection, `#similar-videos` shows the first answer's first 8 cards (v0–v7) and exactly one `/recommendations` request has gone out. This shows the harness reaches the page (the phase-2 state). — control
tests/tmp/test_12_similars_on_scroll_phase3.py:149 — control: at least one IntersectionObserver watches the element whose id is `similar-sentinel`. Without it, the fired intersections could not reach the page. — control
tests/tmp/test_12_similars_on_scroll_phase3.py:151 — one intersection adds exactly one `insertAdjacentHTML` call on `#similar-videos`. — C1
tests/tmp/test_12_similars_on_scroll_phase3.py:153 — that call's position is "beforeend". — C1
tests/tmp/test_12_similars_on_scroll_phase3.py:154 — that call's markup holds exactly 8 `similar-card-item` anchors, and they are rows v8–v15 in order (the next 8, not a repeat of v0–v7). — C1
tests/tmp/test_12_similars_on_scroll_phase3.py:155 — the grid's `innerHTML` setter was not called again during the intersection (the grid was not rewritten). — C1
tests/tmp/test_12_similars_on_scroll_phase3.py:156 — after the intersection, the grid's markup still starts with the unchanged first-8-card markup. — C1
tests/tmp/test_12_similars_on_scroll_phase3.py:160 — after five intersections, the grid shows all 48 rows, v0–v47, in order. — C1
tests/tmp/test_12_similars_on_scroll_phase3.py:161 — negative case: while unrevealed rows remain (through the fifth intersection), no second `/recommendations` request is sent. — C2
tests/tmp/test_12_similars_on_scroll_phase3.py:164 — after the sixth intersection (every fetched row already shown), exactly two `/recommendations` requests have been sent. — C2
tests/tmp/test_12_similars_on_scroll_phase3.py:166 — the second request is a POST. — C2
tests/tmp/test_12_similars_on_scroll_phase3.py:168 — the second request's body `exclude` has exactly 48 entries, and their (id, host) pairs are exactly (v0–v47, videos.example): the first batch's rows, with no duplicates and nothing extra. — C2
</assertions>

<probes>
1. Shape of the pager's exclude body. Command: ValidateTests ["tests/tmp/probe_12_phase3_exclude.py", "-s"]. The probe bundled `client/frontend/src/data/videos.ts` and called `createFeedPager(fetchSimilarVideosPayload)` twice with a stubbed fetch (first call returned rows v0–v2). It printed: [{"url":"http://client.test/recommendations?id=v1&host=peer.example&limit=48","method":"POST","body":{"likes":[]}},{"url":"http://client.test/recommendations?id=v1&host=peer.example&limit=48","method":"POST","body":{"likes":[],"exclude":[{"id":"v0","host":"videos.example"},{"id":"v1","host":"videos.example"},{"id":"v2","host":"videos.example"}]}}]. So `exclude` is a list of {id, host} objects, keyed by video_id and instance_domain, and the first request has no exclude key. The assertion at line 168 is written against this shape.
2. The checkpoint against the current code. Command: ValidateTests ["tests/tmp/test_12_similars_on_scroll_phase3.py"]. Result: 1 failed. The first-batch control at line 148 passed (the harness reaches the page), and the test failed at line 149 with `AssertionError: 0 / assert 0 >= 1`, because phase 3 has no sentinel observer yet.
3. The runner's mechanics and whether wrong implementations fail. Command: ValidateTests ["tests/tmp/probe_12_phase3_fake.py", "-s"]. The probe ran this test's own RUNNER and test function against small hand-written stand-in bundles (not the real page), one correct and five wrong. It printed:
   - good: PASSED
   - afterbegin: FAILED "afterbegin" (line 153)
   - rewrite: FAILED (0, 0) — `innerHTML` rewritten instead of inserted (line 151)
   - per_card: FAILED (0, 8) — 8 separate inserts instead of one (line 151)
   - no_exclude: FAILED [] (line 168)
   - exclude_8: FAILED, the exclude list held only v0–v7 (line 168)
Both probe files have been emptied (my tools cannot delete files), the same way the existing `probe_12_pager.py` was left.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_12_similars_on_scroll_phase3.py` - 11189 characters, inlined in full

```
"""The video page's similars, run in node with the real page module: each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`, and an intersection once all 48 are shown asks for the next batch, excluding the rows shown.

- One intersection makes exactly one `insertAdjacentHTML("beforeend", …)` call on `#similar-videos`, holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer; `innerHTML` is never set again and still begins with the first 8 cards unchanged.
- Five intersections show all 48 rows without a second `/recommendations` request; the sixth sends one, a POST whose `exclude` is exactly the first answer's 48 `{id, host}` pairs.

The runner is the one in `tests/active/test_frontend_video_page_similars.py`, plus: each element counts its `innerHTML` writes and records its `insertAdjacentHTML` calls, `getElementById` tags the element with its id, and after the page has settled the runner fires every observer watching `#similar-sentinel` with `[{ isIntersecting: true }]`, six times, settling after each. `fetch` answers the first `/recommendations` POST with rows v0-v47, the second with the disjoint w0-w47, and any later one with no rows.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
ROWS = 48
SHOWN = 8
INTERSECTIONS = 6

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
// The document is far taller than the window and nothing has scrolled, so a fill-viewport pass never asks for another batch.
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: "?id=v1&host=peer.example" },
  localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage, innerHeight: 800, scrollY: 0,
  addEventListener() {}, removeEventListener() {} };
const text = (value) => ({ nodeType: 3, textContent: String(value) });
const nodes = (items) => items.map((n) => (typeof n === "string" ? text(n) : n));
const element = (tag, hidden = false) => {
  const classes = new Set();
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), hidden, children: [], dataset: {}, style: {}, attrs: {}, parentElement: null, writes: 0, inserts: [],
    get textContent() { return el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.children = v == null || v === "" ? [] : [text(v)]; },
    // Markup is kept opaque: text only reaches a report through textContent or a text node.
    get innerHTML() { return el.children.map((c) => c.html ?? (c.nodeType === 1 ? c.outerHTML : "")).join(""); },
    set innerHTML(v) { el.writes += 1; el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
    get outerHTML() { return `<${tag} class="${el.className}">${el.innerHTML}</${tag}>`; },
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); String(v).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    classList: { add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c), toggle: (c, force) => { const on = force ?? !classes.has(c); if (on) classes.add(c); else classes.delete(c); return on; } },
    append: (...items) => { el.children.push(...nodes(items)); },
    appendChild: (child) => { el.children.push(child); return child; },
    replaceChildren: (...items) => { el.children = nodes(items); },
    setAttribute: (name, value) => { if (name === "hidden") el.hidden = true; else if (name === "class") el.className = value; else el.attrs[name] = String(value); },
    removeAttribute: (name) => { if (name === "hidden") el.hidden = false; else delete el.attrs[name]; },
    toggleAttribute: (name, force) => { const on = force ?? !(name === "hidden" ? el.hidden : name in el.attrs); el[on ? "setAttribute" : "removeAttribute"](name, ""); return on; },
    getAttribute: (name) => (name === "hidden" ? (el.hidden ? "" : null) : el.attrs[name] ?? null),
    getBoundingClientRect: () => ({ top: 10000, bottom: 10000, left: 0, right: 0, width: 0, height: 0 }),
    closest: () => null, querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, remove() {},
    insertAdjacentHTML: (position, html) => { el.inserts.push({ position, html: String(html) }); const node = { nodeType: 0, textContent: "", html: String(html) }; if (position === "afterbegin") el.children.unshift(node); else el.children.push(node); },
  };
  return el;
};
const byId = new Map();
const getElementById = (id) => { if (!byId.has(id)) { const el = element("div"); el.id = id; byId.set(id, el); } return byId.get(id); };
globalThis.document = {
  title: "", body: element("body"), documentElement: { scrollHeight: 10000, clientHeight: 800 },
  getElementById, createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: (selector) => (/^#[\\w-]+$/.test(selector) ? getElementById(selector.slice(1)) : null), querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
// Captured, then fired by hand below as if the sentinel had scrolled into view.
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.observed = []; observers.push(this); }
  observe(target) { this.observed.push(target); } unobserve() {} disconnect() {} };
const requests = [];
const answers = JSON.parse(process.env.RECOMMENDATIONS_BODIES);
let answered = 0;
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: init?.method ?? "GET", path: url.pathname, query: Object.fromEntries(url.searchParams), body: init?.body ? JSON.parse(init.body) : null });
  const body = url.pathname === "/recommendations" ? JSON.stringify(answers[answered++] ?? { rows: [] }) : "{}";
  return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
};
// Every stubbed fetch resolves at once, so the page's work has settled within a few macrotasks.
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
await import(process.env.BUNDLE);
await settle();
const isSentinel = (target) => target?.id === "similar-sentinel" || target?.attrs?.id === "similar-sentinel";
const watching = observers.filter((o) => o.observed.some(isSentinel));
const grid = getElementById("similar-videos");
const snapshot = () => ({ similar: grid.innerHTML, writes: grid.writes, inserts: grid.inserts.length, recommendations: requests.filter((r) => r.path === "/recommendations").length });
const snapshots = [snapshot()];
for (let i = 0; i < Number(process.env.INTERSECTIONS); i += 1) {
  for (const o of watching) o.callback([{ isIntersecting: true, target: o.observed.find(isSentinel) }], o);
  await settle();
  snapshots.push(snapshot());
}
process.stdout.write(JSON.stringify({ requests, sentinelObservers: watching.length, snapshots, inserts: grid.inserts }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_similars_scroll")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _rows(prefix: str) -> list[dict]:
    return [{"video_id": f"{prefix}{i}", "instance_domain": "videos.example"} for i in range(ROWS)]


def _page(bundle: Path) -> dict:
    answers = [{"rows": _rows("v"), "seed": {"mode": "upnext"}}, {"rows": _rows("w"), "seed": {"mode": "upnext"}}]
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "RECOMMENDATIONS_BODIES": json.dumps(answers), "INTERSECTIONS": str(INTERSECTIONS)},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page module ran its loads, so a missing similars request below is the page's, not the runner's
    assert "/api/video" in [r["path"] for r in page["requests"]], page["requests"]
    return page


def _keys(markup: str) -> list[str | None]:
    cards = re.findall(r'<a\b[^>]*\bclass="[^"]*\bsimilar-card-item\b[^"]*"[^>]*>', markup)
    return [m.group(1) if (m := re.search(r'data-video-key="videos\.example::(\w+)"', card)) else None for card in cards]


def test_each_sentinel_intersection_appends_the_next_8_rows_and_the_one_after_all_48_asks_for_a_batch_excluding_them(bundle):
    page = _page(bundle)
    loaded, first = page["snapshots"][:2]

    # control: the first batch rendered as phase 2 left it, and something watches the sentinel, so the intersections below reach the page
    assert _keys(loaded["similar"]) == [f"v{i}" for i in range(SHOWN)] and loaded["recommendations"] == 1, loaded
    assert page["sentinelObservers"] >= 1, page["sentinelObservers"]

    assert first["inserts"] - loaded["inserts"] == 1, (loaded["inserts"], first["inserts"])  # C1
    appended = page["inserts"][loaded["inserts"]]
    assert appended["position"] == "beforeend", appended["position"]  # C1
    assert _keys(appended["html"]) == [f"v{i}" for i in range(SHOWN, 2 * SHOWN)], appended["html"][:400]  # C1
    assert first["writes"] == loaded["writes"], (loaded["writes"], first["writes"])  # C1
    assert first["similar"].startswith(loaded["similar"]), first["similar"][:400]  # C1

    # the 40 rows after the first 8 take five intersections
    revealed = page["snapshots"][(ROWS - SHOWN) // SHOWN]
    assert _keys(revealed["similar"]) == [f"v{i}" for i in range(ROWS)], _keys(revealed["similar"])  # C1
    assert revealed["recommendations"] == 1, revealed["recommendations"]  # C2

    recommendations = [r for r in page["requests"] if r["path"] == "/recommendations"]
    assert len(recommendations) == 2, recommendations  # C2
    second = recommendations[1]
    assert second["method"] == "POST", second  # C2
    exclude = (second["body"] or {}).get("exclude") or []
    assert len(exclude) == ROWS and sorted((str(e.get("id")), str(e.get("host"))) for e in exclude) == sorted((f"v{i}", "videos.example") for i in range(ROWS)), exclude  # C2

```


Gate: satisfied

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - red (audit round 1)

`tests/tmp/test_12_similars_on_scroll_phase3.py` exited 1.

```
  tests/tmp/test_12_similars_on_scroll_phase3.py  1 failed                               0.0s
  ----------------------------------------------
  total                                           1 failed                               1.0s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - BLOCK
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 2 UNCARRIED clause(s) - D1, N1; devsecops-test-shape-auditor: critical

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: BLOCK

CRITICAL
1. single-value-pin (rules/shape.md) — tests/tmp/test_12_similars_on_scroll_phase3.py:121
   return [{"video_id": f"{prefix}{i}", "instance_domain": "videos.example"} for i in range(ROWS)]
   Two values in this fixture are always equal, so the C2 checks cannot tell them apart. The fixture returns ROWS = 48 rows per batch (line 21). The page requests `limit: "48"` (client/frontend/src/pages/video-page/index.ts:308). So the number of rows fetched always equals the number requested. C2 says a refetch happens "after all fetched rows are revealed". The checks at lines 161 and 164 (`revealed["recommendations"] == 1` then `len(recommendations) == 2`) and the exclude check at line 168 would also pass for a wrong implementation that refetches once it has shown the requested limit of 48, or after a fixed six intersections (48 / 8). This matches the entry's `<how_to_spot>` bullet "A fixture whose two relevant values coincide". The rule requires a batch whose row count differs from the requested limit, for example 20 rows. With 20 rows, the refetch must come after the second intersection and not the sixth. The exclude list at line 168 has the same gap: all 48 fetched rows are shown when it is checked, so "rows shown" and "rows fetched" cannot be told apart there either.

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at line 151, `assert first["inserts"] - loaded["inserts"] == 1`, with a difference of 0 and `sentinelObservers` 0. `loadSimilarVideos` (index.ts:292-327) renders the first 8 cards through `innerHTML` and never creates an IntersectionObserver on `#similar-sentinel`. So the runner has no observer to fire, and nothing is appended.

NOT ASSESSED
1. `code_under_test` lists client/frontend/video-page.html, client/frontend/src/video.css and tests/active/test_frontend_video_page_similars.py. I did not read these. The test inlines its own runner and does not import from the other test file, so the shape verdict does not depend on them.
2. For `createFeedPager` in client/frontend/src/data/videos.ts, I only grepped for its signature and its exclude handling and did not read its full body. The exclude question was answered from the pager's documented contract (lines 31-38 and 130-134) together with the test's assertion form.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (17 clauses: 4 must_prove, 10 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a sentinel intersection appends the next 8 cards" | :151, :153, :154 | no append on intersection; prepending (`afterbegin`); appending wrong rows, the wrong count, or the first 8 again | CARRIED |
| C1b | must_prove | "the cards already shown stay in place" | :155, :156 | re-rendering the grid through `innerHTML`; reordering or replacing the first 8 cards | CARRIED |
| C2a | must_prove | "an intersection after all fetched rows are revealed sends another `/recommendations` request" | :161, :164 | never fetching on exhaustion; fetching early, before all 48 are revealed | CARRIED |
| C2b | must_prove | "whose exclude list holds the rows already shown" | :168 | a missing or empty `exclude`; a partial list (the 8 first shown); wrong ids or hosts; duplicates (length is pinned at 48) | CARRIED |
| D1 | docstring | "each sentinel intersection appends the next 8 of the fetched rows" | :154, :160 | :154 checks only the first intersection. :160 checks only the total after five. Intersections 2–5 appending uneven chunks (8, 16, 16) or rewriting `innerHTML` still pass | UNCARRIED |
| D2 | docstring | "an intersection once all 48 are shown asks for the next batch, excluding the rows shown" | :161, :164, :168 | early fetch; no fetch; wrong exclude | CARRIED |
| D3 | docstring | "exactly one `insertAdjacentHTML("beforeend", …)` call on `#similar-videos`" | :151, :153 | zero or several inserts; the wrong position | CARRIED |
| D4 | docstring | "holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer" | :154 | the wrong rows, count or order in the inserted markup | CARRIED |
| D5 | docstring | "`innerHTML` is never set again" (scoped to the one-intersection bullet) | :155 | an `innerHTML` rewrite on the first intersection | CARRIED |
| D6 | docstring | "still begins with the first 8 cards unchanged" | :156 | the first 8 cards changed or moved | CARRIED |
| D7 | docstring | "five intersections show all 48 rows" | :160 | rows missing, duplicated or out of order after five | CARRIED |
| D8 | docstring | "without a second `/recommendations` request" | :161 | fetching before all 48 are revealed | CARRIED |
| D9 | docstring | "the sixth sends one, a POST" | :164, :166 | no second request; more than one; a GET | CARRIED |
| D10 | docstring | "whose `exclude` is exactly the first answer's 48 `{id, host}` pairs" | :168 | a superset, subset or wrong pairs | CARRIED |
| N1 | name | "each sentinel intersection appends the next 8 rows" | :154, :160 | same gap as D1: only the first intersection's append is pinned | UNCARRIED |
| N2 | name | "the one after all 48 asks for a batch" | :161, :164 | an early or missing batch request | CARRIED |
| N3 | name | "excluding them" | :168 | a wrong or missing exclude | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase3.py:160
   `assert _keys(revealed["similar"]) == [f"v{i}" for i in range(ROWS)]`
   D1 and N1 say *each* intersection appends the next 8, which is an "X per Y" claim. Only the first intersection is checked per step (:151–:156). Line 160 checks the total after five intersections, so it misses two things: intersections 2–5 appending uneven chunks, and a later intersection rewriting `innerHTML`. Checking inserts, writes and keys for every snapshot in `page["snapshots"][1:6]` would carry the claim. Another fix is to narrow the name and docstring to the first intersection. The `must_prove` clause C1 is singular and is carried, so this does not block.
2. bounds (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase3.py:21
   Only a full 48-row batch, a multiple of 8, runs. Nothing covers a final chunk with fewer than 8 rows (for example 44 rows), a first batch of 8 or fewer, or an intersection when nothing remains to reveal.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase3.py:84
   The runner configures a third answer with `{ rows: [] }`, but no test reaches it. Nothing covers what an intersection does after a batch that returns no rows, or after a failed `/recommendations` fetch. The shown cards should stay and no further requests should follow. Only the success path is covered.

OBSERVATIONS
none

NOT ASSESSED
1. `client/frontend/video-page.html` and `client/frontend/src/video.css` (both in `code_under_test`) were not read. The runner makes up any element id on demand (:66) and loads CSS with an empty loader (:111), so neither file reaches the test's assertions.
2. `tests/active/test_frontend_video_page_similars.py` (in `code_under_test`) was not read. The docstring (:6) says this test's runner is based on that one, but this test has its own copy (:25–:103), and that copy is what was judged. How faithful it is to the other file was not checked.

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
Once the first similar batch is shown, each sentinel intersection appends the next 8 fetched rows to `#similar-videos`, and an intersection that finds no unrevealed row asks the pager for the next batch, excluding the rows already shown.

- C1 - A sentinel intersection appends the next 8 cards, and the cards already shown stay in place.
- C2 - An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown.

must_prove:
- C1 - A sentinel intersection appends the next 8 cards, and the cards already shown stay in place.
- C2 - An intersection after all fetched rows are revealed sends another `/recommendations` request whose exclude list holds the rows already shown.

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - self-check (audit round 1, send-back 0)

`tests/tmp/test_12_similars_on_scroll_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_12_similars_on_scroll_phase3.py:152 — one sentinel intersection adds exactly one `insertAdjacentHTML` call on `#similar-videos` (the failure message also reports how many observers watch `#similar-sentinel`) - expected: 1 once phase 3 is built. Today's run shows `{'inserts': (0, 0), 'sentinel observers': 0}`, which is the red. - excludes: No observer on the sentinel, or one on another element (the runner fires only observers watching `#similar-sentinel`): 0. One insert per card: 8.
- C1 - tests/tmp/test_12_similars_on_scroll_phase3.py:154-155 — that insert's position is "beforeend", and its markup holds `similar-card-item` anchors keyed v8..v15, in that order - expected: "beforeend"; ["v8", …, "v15"]. The key format `videos.example::vN` in `renderSimilarCard` markup was seen in this run: the line-149 control passed on it. - excludes: Prepending ("afterbegin") fails the position check. Re-sending rows 0-7, sending all 48 at once, or skipping to 16-23 gives the wrong key list.
- C1 - tests/tmp/test_12_similars_on_scroll_phase3.py:156-157 and 162 — the grid's `innerHTML` write count does not change after the first intersection or through the fifth, and after the first intersection the grid's markup still begins with the first 8 cards exactly as they were - expected: The write count equals the value at load after 1 and after 5 intersections. The markup is the loaded markup plus the appended part. - excludes: Re-rendering the whole grid with `innerHTML = rows.slice(0, revealed)` (the home page's `renderCards` shape) raises the write count at 156/162. Inserting before the existing cards fails the prefix check at 157.
- C1 - tests/tmp/test_12_similars_on_scroll_phase3.py:161 — after five intersections the grid shows v0..v47, in order - expected: ["v0", …, "v47"] - excludes: A reveal that fires only once, or that stops after a fixed count (for example a guard that treats the first reveal as the last), leaves 16 or fewer cards. A reveal that asks the pager too early leaves some rows unrevealed.
- C2 - tests/tmp/test_12_similars_on_scroll_phase3.py:163 and 166 — still 1 `/recommendations` request after five intersections, and 2 after the sixth - expected: 1, then 2 - excludes: Asking the pager on every intersection gives more than 1 at line 163. Never asking once the fetched rows are used up (the home page's fill loop stopping when nothing is left) leaves 1 at line 166. Asking again while a fetch is still in flight gives 3.
- C2 - tests/tmp/test_12_similars_on_scroll_phase3.py:168 and 170 — the second `/recommendations` request is a POST whose `exclude` holds exactly the 48 {id, host} pairs (v0..v47, videos.example) - expected: "POST"; 48 entries shaped `{'id': 'v0', 'host': 'videos.example'}`. This shape was seen in tests/tmp/probe_pager_exclude_body.py, where the real `createFeedPager` drove `fetchSimilarVideosPayload` and the second request printed `METHOD POST … KEYS ['exclude', 'likes'] N 48 FIRST3 [{'id': 'v0', 'host': 'videos.example'}, …]`. - excludes: A new pager per load-more, or a direct call to `fetchSimilarVideosPayload` without the pager's list, sends no `exclude` (empty list here). Excluding only the 8 revealed-at-once rows, or the rows of one chunk, gives a count other than 48.

<assertions>
tests/tmp/test_12_similars_on_scroll_phase3.py:149 control: before any intersection, #similar-videos holds cards v0-v7 and exactly one /recommendations request was made (the state phase 2 leaves)
tests/tmp/test_12_similars_on_scroll_phase3.py:151 control: at least one IntersectionObserver observes the #similar-sentinel element (matched by id, id attribute or querySelector("#similar-sentinel"))
tests/tmp/test_12_similars_on_scroll_phase3.py:153 one sentinel intersection makes exactly one insertAdjacentHTML call on #similar-videos (C1)
tests/tmp/test_12_similars_on_scroll_phase3.py:155 that call's position is "beforeend" (C1)
tests/tmp/test_12_similars_on_scroll_phase3.py:156 the inserted markup holds exactly 8 similar-card-item anchors, and they are rows v8-v15 of the first answer, in order (C1)
tests/tmp/test_12_similars_on_scroll_phase3.py:157 the intersection writes innerHTML zero times, so the grid is not rewritten (C1)
tests/tmp/test_12_similars_on_scroll_phase3.py:158 after the intersection the grid's innerHTML still begins with the first 8 cards' markup, unchanged (C1)
tests/tmp/test_12_similars_on_scroll_phase3.py:162 after five intersections the grid shows all 48 rows v0-v47 in order (C1)
tests/tmp/test_12_similars_on_scroll_phase3.py:163 intersections that still find unrevealed rows send no second /recommendations request: the count is still 1 after five (C2, negative path)
tests/tmp/test_12_similars_on_scroll_phase3.py:166 the sixth intersection, with no unrevealed row left, sends the second /recommendations request: the count becomes 2 (C2)
tests/tmp/test_12_similars_on_scroll_phase3.py:168 the second request is a POST (C2)
tests/tmp/test_12_similars_on_scroll_phase3.py:170 the second request's body.exclude has exactly 48 entries, and as a set they are exactly the (video_id, instance_domain) pairs v0-v47 / videos.example of the first batch (C2)
</assertions>

<probes>
1) The exclude wire shape. I bundled client/frontend/src/data/videos.ts with esbuild into a node entry that used the real createFeedPager + fetchSimilarVideosPayload and a stub fetch answering the first call with rows v0-v2 @ videos.example. I called next() twice. Run: ValidateTests ["tests/tmp/test_probe_12_phase3_runner.py", "-s"]. Printed: [{"url":"http://client.test/recommendations?id=v1&host=peer.example&limit=48","method":"POST","body":{"likes":[]}},{"url":"http://client.test/recommendations?id=v1&host=peer.example&limit=48","method":"POST","body":{"likes":[],"exclude":[{"id":"v0","host":"videos.example"},{"id":"v1","host":"videos.example"},{"id":"v2","host":"videos.example"}]}}]. So exclude entries are {id: video_id, host: instance_domain}, and the first request has no exclude key. The first attempt failed with "ReferenceError: window is not defined" because the static import was hoisted above the globals; switching to a dynamic import fixed it. The probe file is now emptied and marked for deletion.
2) The checkpoint against the unchanged (phase-2) page. Run: ValidateTests ["tests/tmp/test_12_similars_on_scroll_phase3.py"]. On the first run the first-batch control at line 149 passed (8 cards v0-v7, 1 request), and the C1 insert count was (sentinelObservers=0, inserts 0 -> 0). After adding the sentinel control, the run fails at line 151: "AssertionError: 0 / assert 0 >= 1". It is red because nothing observes #similar-sentinel yet, not because of a harness fault.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_12_similars_on_scroll_phase3.py` - 11491 characters, inlined in full

```
"""The video page's similars, run in node with the real page module: each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`, and an intersection once all 48 are shown asks for the next batch, excluding the rows shown.

- One intersection makes exactly one `insertAdjacentHTML("beforeend", …)` call on `#similar-videos`, holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer; `innerHTML` is never set again and still begins with the first 8 cards unchanged.
- Five intersections show all 48 rows in order without a second `/recommendations` request; the sixth sends one, a POST whose `exclude` is exactly the first answer's 48 `{id, host}` pairs (`video_id`, `instance_domain`).
- Control: at least one `IntersectionObserver` watches `#similar-sentinel`.

The runner is the one in `tests/active/test_frontend_video_page_similars.py`, plus: each element counts its `innerHTML` writes and records its `insertAdjacentHTML` calls, `getElementById` tags the element with its id, and after the page has settled the runner fires every observer watching `#similar-sentinel` with `[{ isIntersecting: true }]`, six times, settling after each. `fetch` answers the first `/recommendations` POST with rows v0-v47, the second with the disjoint w0-w47, and any later one with no rows.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
ROWS = 48
SHOWN = 8
INTERSECTIONS = 6

RUNNER = """
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
globalThis.sessionStorage = memory();
// The document is far taller than the window and nothing has scrolled, so a fill-viewport pass never asks for another batch.
globalThis.window = { location: { origin: process.env.BASE, pathname: "/video-page.html", search: "?id=v1&host=peer.example" },
  localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage, innerHeight: 800, scrollY: 0,
  addEventListener() {}, removeEventListener() {} };
const text = (value) => ({ nodeType: 3, textContent: String(value) });
const nodes = (items) => items.map((n) => (typeof n === "string" ? text(n) : n));
const element = (tag, hidden = false) => {
  const classes = new Set();
  const el = {
    nodeType: 1, tagName: tag.toUpperCase(), hidden, children: [], dataset: {}, style: {}, attrs: {}, parentElement: null, writes: 0, inserts: [],
    get textContent() { return el.children.map((c) => c.textContent).join(""); },
    set textContent(v) { el.children = v == null || v === "" ? [] : [text(v)]; },
    // Markup is kept opaque: text only reaches a report through textContent or a text node.
    get innerHTML() { return el.children.map((c) => c.html ?? (c.nodeType === 1 ? c.outerHTML : "")).join(""); },
    set innerHTML(v) { el.writes += 1; el.children = v ? [{ nodeType: 0, textContent: "", html: String(v) }] : []; },
    get outerHTML() { return `<${tag} class="${el.className}">${el.innerHTML}</${tag}>`; },
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); String(v).split(/\\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    classList: { add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c), toggle: (c, force) => { const on = force ?? !classes.has(c); if (on) classes.add(c); else classes.delete(c); return on; } },
    append: (...items) => { el.children.push(...nodes(items)); },
    appendChild: (child) => { el.children.push(child); return child; },
    replaceChildren: (...items) => { el.children = nodes(items); },
    setAttribute: (name, value) => { if (name === "hidden") el.hidden = true; else if (name === "class") el.className = value; else el.attrs[name] = String(value); },
    removeAttribute: (name) => { if (name === "hidden") el.hidden = false; else delete el.attrs[name]; },
    toggleAttribute: (name, force) => { const on = force ?? !(name === "hidden" ? el.hidden : name in el.attrs); el[on ? "setAttribute" : "removeAttribute"](name, ""); return on; },
    getAttribute: (name) => (name === "hidden" ? (el.hidden ? "" : null) : el.attrs[name] ?? null),
    getBoundingClientRect: () => ({ top: 10000, bottom: 10000, left: 0, right: 0, width: 0, height: 0 }),
    closest: () => null, querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, remove() {},
    insertAdjacentHTML: (position, html) => { el.inserts.push({ position, html: String(html) }); const node = { nodeType: 0, textContent: "", html: String(html) }; if (position === "afterbegin") el.children.unshift(node); else el.children.push(node); },
  };
  return el;
};
const byId = new Map();
const getElementById = (id) => { if (!byId.has(id)) { const el = element("div"); el.id = id; byId.set(id, el); } return byId.get(id); };
globalThis.document = {
  title: "", body: element("body"), documentElement: { scrollHeight: 10000, clientHeight: 800 },
  getElementById, createElement: (tag) => element(tag), createTextNode: (value) => text(value),
  querySelector: (selector) => (/^#[\\w-]+$/.test(selector) ? getElementById(selector.slice(1)) : null), querySelectorAll: () => [], addEventListener() {},
};
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", lineHeight: "20" });
// Captured, then fired by hand below as if the sentinel had scrolled into view.
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.observed = []; observers.push(this); }
  observe(target) { this.observed.push(target); } unobserve() {} disconnect() {} };
const requests = [];
const answers = JSON.parse(process.env.RECOMMENDATIONS_BODIES);
let answered = 0;
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  requests.push({ method: init?.method ?? "GET", path: url.pathname, query: Object.fromEntries(url.searchParams), body: init?.body ? JSON.parse(init.body) : null });
  const body = url.pathname === "/recommendations" ? JSON.stringify(answers[answered++] ?? { rows: [] }) : "{}";
  return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
};
// Every stubbed fetch resolves at once, so the page's work has settled within a few macrotasks.
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10)); };
await import(process.env.BUNDLE);
await settle();
const isSentinel = (target) => target?.id === "similar-sentinel" || target?.attrs?.id === "similar-sentinel";
const watching = observers.filter((o) => o.observed.some(isSentinel));
const grid = getElementById("similar-videos");
const snapshot = () => ({ similar: grid.innerHTML, writes: grid.writes, inserts: grid.inserts.length, recommendations: requests.filter((r) => r.path === "/recommendations").length });
const snapshots = [snapshot()];
for (let i = 0; i < Number(process.env.INTERSECTIONS); i += 1) {
  for (const o of watching) o.callback([{ isIntersecting: true, target: o.observed.find(isSentinel) }], o);
  await settle();
  snapshots.push(snapshot());
}
process.stdout.write(JSON.stringify({ requests, sentinelObservers: watching.length, snapshots, inserts: grid.inserts }) + "\\n");
process.exit(0);
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_similars_scroll")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "pages" / "video-page" / "index.ts"), "--bundle", "--format=esm", "--platform=node",
         "--loader:.css=empty", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(RUNNER)
    return out


def _rows(prefix: str) -> list[dict]:
    return [{"video_id": f"{prefix}{i}", "instance_domain": "videos.example"} for i in range(ROWS)]


def _page(bundle: Path) -> dict:
    answers = [{"rows": _rows("v"), "seed": {"mode": "upnext"}}, {"rows": _rows("w"), "seed": {"mode": "upnext"}}]
    proc = subprocess.run(
        ["node", str(bundle / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(bundle / "bundle.mjs"), "PATH": os.environ.get("PATH", ""),
             "RECOMMENDATIONS_BODIES": json.dumps(answers), "INTERSECTIONS": str(INTERSECTIONS)},
    )
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    # control: the page module ran its loads, so a missing similars request below is the page's, not the runner's
    assert "/api/video" in [r["path"] for r in page["requests"]], page["requests"]
    return page


def _keys(markup: str) -> list[str | None]:
    cards = re.findall(r'<a\b[^>]*\bclass="[^"]*\bsimilar-card-item\b[^"]*"[^>]*>', markup)
    return [m.group(1) if (m := re.search(r'data-video-key="videos\.example::(\w+)"', card)) else None for card in cards]


def test_each_sentinel_intersection_appends_the_next_8_rows_and_the_one_after_all_48_asks_for_a_batch_excluding_them(bundle):
    page = _page(bundle)
    loaded, first = page["snapshots"][:2]

    # control: the first batch rendered as phase 2 left it, so the intersections below start from 8 cards and one request
    assert _keys(loaded["similar"]) == [f"v{i}" for i in range(SHOWN)] and loaded["recommendations"] == 1, loaded
    # control: an IntersectionObserver watches #similar-sentinel, so the intersections below reach the page's callback
    assert page["sentinelObservers"] >= 1, page["sentinelObservers"]

    assert first["inserts"] - loaded["inserts"] == 1, (loaded["inserts"], first["inserts"])  # C1
    appended = page["inserts"][loaded["inserts"]]
    assert appended["position"] == "beforeend", appended["position"]  # C1
    assert _keys(appended["html"]) == [f"v{i}" for i in range(SHOWN, 2 * SHOWN)], appended["html"][:400]  # C1
    assert first["writes"] == loaded["writes"], (loaded["writes"], first["writes"])  # C1
    assert first["similar"].startswith(loaded["similar"]), first["similar"][:400]  # C1

    # the 40 rows after the first 8 take five intersections
    revealed = page["snapshots"][(ROWS - SHOWN) // SHOWN]
    assert _keys(revealed["similar"]) == [f"v{i}" for i in range(ROWS)], _keys(revealed["similar"])  # C1
    assert revealed["recommendations"] == 1, revealed["recommendations"]  # C2

    # the sixth intersection finds no unrevealed row
    assert page["snapshots"][INTERSECTIONS]["recommendations"] == 2, page["snapshots"][INTERSECTIONS]["recommendations"]  # C2
    second = [r for r in page["requests"] if r["path"] == "/recommendations"][1]
    assert second["method"] == "POST", second  # C2
    exclude = (second["body"] or {}).get("exclude") or []
    assert len(exclude) == ROWS and sorted((str(e.get("id")), str(e.get("host"))) for e in exclude) == sorted((f"v{i}", "videos.example") for i in range(ROWS)), exclude  # C2

```


Gate: satisfied

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - red (audit round 1)

`tests/tmp/test_12_similars_on_scroll_phase3.py` exited 1.

```
  tests/tmp/test_12_similars_on_scroll_phase3.py  1 failed                               0.0s
  ----------------------------------------------
  total                                           1 failed                               0.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 3 UNCARRIED clause(s) - C1b, D1b, N1b; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
The test should fail at tests/tmp/test_12_similars_on_scroll_phase3.py:152, on `assert first["inserts"] - loaded["inserts"] == 1`, with a difference of 0 and `"sentinel observers": 0`. index.ts has no `IntersectionObserver` and no `similar-sentinel`, so `watching` is empty and the first intersection never appends. The control assertions at :135 and :149 should pass first: `loadSimilarVideos` already sends one `/recommendations` POST and renders v0–v7, with keys `videos.example::v0…`, through `innerHTML`.

NOT ASSESSED
1. `fixtures_path` was not supplied. The only fixture used, `bundle`, is defined in the test file at :107–118, so nothing is missing.
2. client/frontend/src/video.css was checked only for "similar" (14 matches), not read in full. It is loaded through `--loader:.css=empty` and no assertion touches it.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (20 clauses: 6 must_prove, 12 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a sentinel intersection appends the next 8 cards" (first intersection) | :152, :154, :155 | a re-render in place of an append, a prepend, a chunk other than rows v8-v15, more than one insert | CARRIED |
| C1b | must_prove | the same holds for each later intersection: every one adds the next 8 (8 per intersection, second case) | none | :161 checks only the total after five intersections, so a page that shows all 32 remaining rows on the second intersection, and nothing on the third to fifth, still passes | UNCARRIED |
| C1c | must_prove | "the cards already shown stay in place" | :156, :157, :161, :162 | the grid rebuilt through `innerHTML`, first 8 cards changed or reordered, earlier cards lost by the time all 48 show | CARRIED |
| C2a | must_prove | the request comes only "after all fetched rows are revealed" | :163 | fetching the next batch before all 48 rows are shown | CARRIED |
| C2b | must_prove | that intersection "sends another `/recommendations` request" | :166 | no fetch on the intersection after all rows are shown | CARRIED |
| C2c | must_prove | "whose exclude list holds the rows already shown" | :170 | an empty or missing exclude, a partial list, wrong id/host fields, extra entries | CARRIED |
| D1a | docstring | "each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`" (first) | :155 | a wrong or wrong-sized first chunk | CARRIED |
| D1b | docstring | "each" (intersections 2-5 each add 8) | none | only the total is checked (:161), so the chunk size is never checked after the first intersection | UNCARRIED |
| D2 | docstring | "an intersection once all 48 are shown asks for the next batch, excluding the rows shown" | :166, :170 | no refetch, or a refetch without the shown rows excluded | CARRIED |
| D3 | docstring | "exactly one `insertAdjacentHTML("beforeend", …)` call on `#similar-videos`" | :152, :154 | several inserts, "afterbegin" | CARRIED |
| D4 | docstring | "holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer" | :155 | wrong count, wrong rows, wrong order | CARRIED |
| D5 | docstring | "`innerHTML` is not set again through the five intersections" | :156, :162 | any `innerHTML` rewrite of the grid through snapshot 5 | CARRIED |
| D6 | docstring | "after the first it still begins with the first 8 cards unchanged" | :157 | first 8 cards replaced or altered | CARRIED |
| D7 | docstring | "Five intersections show all 48 rows in order" | :161 | missing, repeated or out-of-order rows after five | CARRIED |
| D8 | docstring | "without a second `/recommendations` request" | :163 | early prefetch | CARRIED |
| D9 | docstring | "the sixth sends one, a POST" | :166, :168 | no sixth-intersection request; a GET | CARRIED |
| D10 | docstring | "`exclude` is exactly the first answer's 48 `{id, host}` pairs" | :170 | wrong length, duplicates, wrong key names, wrong values | CARRIED |
| D11 | docstring | "Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel" | :152 (with runner :92-98) | an observer on some other element, which is never fired, so no append | CARRIED |
| N1a | name | "each sentinel intersection appends the next 8 rows" (first) | :155 | wrong first chunk | CARRIED |
| N1b | name | "each" (every intersection adds exactly 8) | none | only the total is checked (:161) | UNCARRIED |
| N2 | name | "the one after all 48 asks for a batch excluding them" | :166, :170 | no refetch; exclude not equal to the 48 shown | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase3.py:161
   assert _keys(revealed["similar"]) == [f"v{i}" for i in range(ROWS)], _keys(revealed["similar"])  # C1
   C1 is a per-intersection claim: each sentinel intersection adds the next 8 cards. `<whole-claim>` says a claim of the form "X per Y needs a second Y or it proves only X". The test checks the chunk for the first intersection only (:155). For intersections 2-5 it checks just the combined grid after the fifth (:161), plus no `innerHTML` writes (:162) and one request so far (:163). A page that shows all 32 remaining rows on the second intersection and nothing on the third to fifth passes all of those. The rule requires the second and later intersections to be checked one at a time. `page["snapshots"][2..5]` and `page["inserts"]` are already captured, but nothing checks each step's 8 keys.

RECOMMENDATIONS
1. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase3.py:98
   The runner only ever fires `[{ isIntersecting: true }]`. A page that appends on any observer callback, including the sentinel leaving view (`isIntersecting: false`), passes. No test covers the non-intersecting path.
2. bounds (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase3.py:122
   The first answer is always 48 rows, an exact multiple of 8. A final partial chunk (e.g. 45 rows), a first answer shorter than 8, and an empty second answer are all untested. The runner feeds a second answer (w0-w47, docstring :7), but nothing checks what happens with it.
3. whole-claim / name-as-sentence (rules/testing.md) — tests/tmp/test_12_similars_on_scroll_phase3.py:144, :1
   D1b and N1b are UNCARRIED for the reason given in Critical 1. Both the name and the docstring say "each", and only the first intersection is checked on its own.

OBSERVATIONS
none

NOT ASSESSED
1. `client/frontend/src/pages/video-page/index.ts` and `client/frontend/video-page.html` as read have no `similar-sentinel` element, no `IntersectionObserver`, and no append path. `loadSimilarVideos` sets `innerHTML` once with the first 8 rows and stops. The clauses were judged against what the test asserts. Whether it currently runs red was not checked, because nothing was executed.
2. `client/frontend/src/video.css` was not read. It has no bearing on the claim criteria.
3. `fixtures_path` was not supplied. The only fixture, `bundle`, is defined in the test file (:107), so no conftest was needed.

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - self-check (audit round 2, send-back 0)

`tests/tmp/test_12_similars_on_scroll_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_12_similars_on_scroll_phase3.py:152, :154, :155 — the first intersection makes exactly one insertAdjacentHTML call on #similar-videos, at "beforeend", holding the similar-card-item anchors for rows v8-v15 in order - expected: insert delta 1, position "beforeend", keys ["v8", …, "v15"] - excludes: A page that re-renders the grid, prepends, or inserts the wrong slice: the delta reads 0 or more than 1, the position reads "afterbegin", or the keys are not v8-v15.
- C1 - tests/tmp/test_12_similars_on_scroll_phase3.py:162 — for each intersection k = 2..5, exactly one insert is made on that step, and the grid then shows v0..v(8(k+1)-1) in order - expected: For k=2,3,4,5: insert delta 1, and the grid keys are v0-v23, v0-v31, v0-v39, v0-v47 - excludes: A page that shows all 32 remaining rows on the second intersection and nothing after it: at k=2 the grid reads v0-v47 where v0-v23 is expected. A page that appends a wrong-sized chunk or skips a step fails the key list or the insert delta at that k.
- C1 - tests/tmp/test_12_similars_on_scroll_phase3.py:156, :157, :166, :167 — innerHTML writes do not change through the first and fifth intersections; the grid still begins with the first 8 cards' markup; after five intersections it shows v0-v47 in order - expected: writes unchanged; first["similar"] starts with the loaded markup; keys v0..v47 - excludes: A page that rebuilds the grid through innerHTML with the accumulated rows: the writes count goes up, and if the earlier cards' markup changes, the startswith check fails.
- C2 - tests/tmp/test_12_similars_on_scroll_phase3.py:168 — after five intersections there has still been only one /recommendations request - expected: 1 - excludes: A page that prefetches the next batch on an intersection that still has unrevealed rows reads 2 or more.
- C2 - tests/tmp/test_12_similars_on_scroll_phase3.py:171, :173 — the sixth intersection sends a second /recommendations request, and it is a POST - expected: request count 2; method "POST" - excludes: A page that stops once the fetched rows run out reads a count of 1. A page that refetches with GET reads "GET".
- C2 - tests/tmp/test_12_similars_on_scroll_phase3.py:175 — the second request's body.exclude has exactly 48 entries, and as a set they equal the {id, host} pairs v0-v47 / videos.example - expected: 48 entries: {id: "v0".."v47", host: "videos.example"} - excludes: A refetch with no exclude, with only the last chunk, with duplicates, or with video_id/instance_domain keys: the length or the pair set differs.

<items>
<item id="C1b">
<disposition>fixed</disposition>
<what>Added a per-intersection loop at :160-162. For each intersection k = 2..5, :162 asserts that exactly one insert happened on that step and that the grid after it shows exactly v0..v(8(k+1)-1) in order. A page that shows all 32 remaining rows on the second intersection fails at k=2, because the grid holds 48 keys where 24 are expected. A page that appends nothing on a later step fails on the insert delta and on the key list.</what>
</item>
<item id="D1b">
<disposition>fixed</disposition>
<what>The docstring's "each" is now carried by :162 (the new loop over intersections 2-5), which checks each step's own chunk: one insert per step, and a grid that grows by exactly the next 8 rows in order. Together with :152/:155 for the first intersection, every one of the five revealing intersections is checked on its own.</what>
</item>
<item id="N1b">
<disposition>fixed</disposition>
<what>The test name's "each … appends the next 8 rows" is now carried by :152/:155 for intersection 1 and by :162 for intersections 2-5. :162 checks per step that the insert count rises by exactly 1 and the grid is v0..v(8(k+1)-1), so a larger, smaller or skipped chunk at any step fails.</what>
</item>
</items>

<findings_addressed>
Claim CRITICAL 1 (whole-claim, :161 checks only the total): added the loop at :160-162, which checks intersections 2-5 one at a time (insert delta == 1 and grid keys == v0..v(8(k+1)-1) after step k), built from the already-captured page["snapshots"]. A page that dumps the remaining 32 rows on the second intersection now fails at k=2.
Claim RECOMMENDATION 3 (D1b/N1b uncarried): resolved by the same assertion at :162.
Recommendations 1 (non-intersecting callback) and 2 (partial final chunk / short or empty answers) not taken: both need new runner inputs and cover cases outside this phase's C1/C2 clauses.
Shape audit: no CRITICAL. The new assertion compares against row-id ranges from the fixture input, not against a production table.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:152, :154, :155 — the first intersection makes exactly one insertAdjacentHTML call on #similar-videos, at "beforeend", holding the similar-card-item anchors for rows v8-v15 in order</assertion>
<expected>insert delta 1, position "beforeend", keys ["v8", …, "v15"]</expected>
<wrong_implementation>A page that re-renders the grid, prepends, or inserts the wrong slice: the delta reads 0 or more than 1, the position reads "afterbegin", or the keys are not v8-v15.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:162 — for each intersection k = 2..5, exactly one insert is made on that step, and the grid then shows v0..v(8(k+1)-1) in order</assertion>
<expected>For k=2,3,4,5: insert delta 1, and the grid keys are v0-v23, v0-v31, v0-v39, v0-v47</expected>
<wrong_implementation>A page that shows all 32 remaining rows on the second intersection and nothing after it: at k=2 the grid reads v0-v47 where v0-v23 is expected. A page that appends a wrong-sized chunk or skips a step fails the key list or the insert delta at that k.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:156, :157, :166, :167 — innerHTML writes do not change through the first and fifth intersections; the grid still begins with the first 8 cards' markup; after five intersections it shows v0-v47 in order</assertion>
<expected>writes unchanged; first["similar"] starts with the loaded markup; keys v0..v47</expected>
<wrong_implementation>A page that rebuilds the grid through innerHTML with the accumulated rows: the writes count goes up, and if the earlier cards' markup changes, the startswith check fails.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:168 — after five intersections there has still been only one /recommendations request</assertion>
<expected>1</expected>
<wrong_implementation>A page that prefetches the next batch on an intersection that still has unrevealed rows reads 2 or more.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:171, :173 — the sixth intersection sends a second /recommendations request, and it is a POST</assertion>
<expected>request count 2; method "POST"</expected>
<wrong_implementation>A page that stops once the fetched rows run out reads a count of 1. A page that refetches with GET reads "GET".</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_12_similars_on_scroll_phase3.py:175 — the second request's body.exclude has exactly 48 entries, and as a set they equal the {id, host} pairs v0-v47 / videos.example</assertion>
<expected>48 entries: {id: "v0".."v47", host: "videos.example"}</expected>
<wrong_implementation>A refetch with no exclude, with only the last chunk, with duplicates, or with video_id/instance_domain keys: the length or the pair set differs.</wrong_implementation>
</row>
</rows>

<answers>
1. No. The negative assertions (writes unchanged at :156/:167, request count still 1 at :168) are armed by positive observables of the same run: the control at :149 and the append checks at :152/:155/:162. With the code under test deleted, the test fails at :152 (observed: inserts 0 -> 0).
2. No. Expected values are row-id ranges built from the fixture input (v0..v47), not a copy of production's transformation. Deleting the page's sentinel append path turns :152 and :162 red, and deleting the exclude construction turns :175 red.
3. No. The chunk is now checked at five separate intersections (:152/:155 for the first, :162 for k=2..5), and the exclude is checked against all 48 input rows.
4. No. The doubles stand in for DOM, fetch, storage and IntersectionObserver, which are browser/network layers. The real page module and data modules run from the esbuild bundle.
5. Yes, it collects. The new loop uses only names already bound (page, ROWS, SHOWN, _keys), and snapshots has INTERSECTIONS+1 = 7 entries, so indices 1..5 exist. The run collected and executed 1 test.
6. Yes. The snapshot and key format was observed on the loaded grid (control :149 passed), and the exclude wire shape was observed in the earlier probe. The appended markup's format is phase 3's output and cannot be observed until the phase is built. It is read with the same _keys used at :155, which matches the card markup the page already renders.
7. Yes. Rerun after the edit: ValidateTests ["tests/tmp/test_12_similars_on_scroll_phase3.py"] fails at :152 with "{'inserts': (0, 0), 'sentinel observers': 0} / assert (0 - 0) == 1". The control at :149 passes first, so the test is red because no observer is on the sentinel yet, not because of a harness fault.
</answers>

<exemptions>
none
</exemptions>

Gate: satisfied

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - red (audit round 2)

`tests/tmp/test_12_similars_on_scroll_phase3.py` exited 1.

```
  tests/tmp/test_12_similars_on_scroll_phase3.py  1 failed                               0.0s
  ----------------------------------------------
  total                                           1 failed                               0.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at line 152 on `assert first["inserts"] - loaded["inserts"] == 1`, with inserts
(n, n) and "sentinel observers": 0. index.ts has no `similar-sentinel` and no
`IntersectionObserver`, so the runner has no observer to fire and nothing is appended
to `#similar-videos`.

NOT ASSESSED
1. `fixtures_path` was not supplied. The only fixture the test uses, `bundle`
   (tests/tmp/test_12_similars_on_scroll_phase3.py:107), is defined in the file, so no
   conftest was needed.
2. client/frontend/video-page.html, client/frontend/src/video.css and
   tests/active/test_frontend_video_page_similars.py in `code_under_test` were not read.
   The test does not load the HTML or CSS: the bundle loads `.css` as empty, and
   `getElementById` makes up elements. The test copies the other file's runner inline
   instead of importing it. The stub question was answered from index.ts and
   src/data/videos.ts (createFeedPager, fetchSimilarVideosPayload, MAX_FEED_EXCLUDE = 500).
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (21 clauses: 6 must_prove, 12 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "a sentinel intersection appends the next 8 cards" (first intersection) | :152, :154, :155 | a re-render instead of an append, a prepend, a chunk other than rows v8-v15, more than one insert | CARRIED |
| C1b | must_prove | the same holds for each later intersection: every one adds the next 8 (8 per intersection, second case) | :162 | for k = 2..5, a step with other than one insert, or whose grid is not exactly v0..v(8(k+1)-1). So a page that shows all 32 remaining rows at step 2, or any chunk other than 8, fails at that step | CARRIED |
| C1c | must_prove | "the cards already shown stay in place" | :156, :157, :162, :166, :167 | the grid rebuilt through `innerHTML` at any point up to snapshot 5 (the write counter only goes up), the first 8 cards changed or reordered, earlier cards lost or reordered at any step | CARRIED |
| C2a | must_prove | the request comes only "after all fetched rows are revealed" | :168 | fetching the next batch before all 48 rows are shown | CARRIED |
| C2b | must_prove | that intersection "sends another `/recommendations` request" | :171 | no fetch on the sixth intersection | CARRIED |
| C2c | must_prove | "whose exclude list holds the rows already shown" | :175 | an empty or missing exclude, a partial list, duplicates (length is pinned at 48), wrong `id`/`host` fields, extra entries | CARRIED |
| D1a | docstring | "each sentinel intersection appends the next 8 of the fetched rows to `#similar-videos`" (first) | :155 | a wrong or wrong-sized first chunk | CARRIED |
| D1b | docstring | "each" (intersections 2-5 each add 8) | :162 | a chunk size other than 8 at any step from 2 to 5 | CARRIED |
| D2 | docstring | "an intersection once all 48 are shown asks for the next batch, excluding the rows shown" | :171, :175 | no refetch, or a refetch without the shown rows excluded | CARRIED |
| D3 | docstring | "exactly one `insertAdjacentHTML("beforeend", …)` call on `#similar-videos`" | :152, :154 | several inserts, "afterbegin" | CARRIED |
| D4 | docstring | "holding 8 `similar-card-item` anchors that are rows 8-15 of the first answer" | :155 | wrong count, wrong rows, wrong order | CARRIED |
| D5 | docstring | "`innerHTML` is not set again through the five intersections" | :156, :167 | any `innerHTML` rewrite of the grid through snapshot 5 | CARRIED |
| D6 | docstring | "after the first it still begins with the first 8 cards unchanged" | :157 | first 8 cards replaced or altered | CARRIED |
| D7 | docstring | "Five intersections show all 48 rows in order" | :166 | missing, repeated or out-of-order rows after five | CARRIED |
| D8 | docstring | "without a second `/recommendations` request" | :168 | an early prefetch | CARRIED |
| D9 | docstring | "the sixth sends one, a POST" | :171, :173 | no request on the sixth intersection; a GET | CARRIED |
| D10 | docstring | "`exclude` is exactly the first answer's 48 `{id, host}` pairs" | :175 | wrong length, duplicates, wrong key names, wrong values | CARRIED |
| D11 | docstring | "Only observers watching `#similar-sentinel` are fired, so an append at all shows the page's observer is on the sentinel" | :152 (with runner :92-98) | an observer on some other element, which is never fired, so no append happens | CARRIED |
| N1a | name | "each sentinel intersection appends the next 8 rows" (first) | :155 | a wrong first chunk | CARRIED |
| N1b | name | "each" (every intersection adds exactly 8) | :162 | a chunk other than 8 at steps 2-5 | CARRIED |
| N2 | name | "the one after all 48 asks for a batch excluding them" | :171, :175 | no refetch; exclude not equal to the 48 shown | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. C1b, D1b and N1b are now carried by a new assertion at tests/tmp/test_12_similars_on_scroll_phase3.py:162, which checks each step from 2 to 5. The author added an assertion; the prose was not narrowed.
2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_12_similars_on_scroll_phase3.py:171-175. Only the success path of the refetch runs. The runner's docstring says a third request gets an empty answer (:7), but only six intersections run, so it is never reached. A failed or empty second `/recommendations` answer is never exercised, and neither is what the sentinel does after one. No ledger row names this, so it does not block.
3. bounds (rules/testing.md): tests/tmp/test_12_similars_on_scroll_phase3.py:22. `ROWS = 48` is a multiple of `SHOWN = 8`, so every chunk is full. A batch whose last chunk is short, such as 44 rows, is never exercised. The same goes for a batch of 8 or fewer rows, where the first intersection has no row left to reveal and should go straight to the refetch. No ledger row names this, so it does not block.

NOT ASSESSED
1. client/frontend/video-page.html, client/frontend/src/video.css and tests/active/test_frontend_video_page_similars.py from `code_under_test` were not read. The runner copied from the last of these is inlined in the test (:26-104) and was judged there. In index.ts only the similars loader (:289-327) was read, plus a search for the names the test depends on. `createFeedPager` and `fetchSimilarVideosPayload` in client/frontend/src/data/videos.ts were located but not read, so the exclude payload's key names (`id`/`host`) were taken from the docstring and :175 rather than checked against the code.

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - checkpoint outcome (run 1)

`tests/tmp/test_12_similars_on_scroll_phase3.py` exited 1 after the phase landed.

<changes>
### `client/frontend/src/pages/video-page/index.ts`
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
  tests/tmp/test_12_similars_on_scroll_phase3.py  1 failed                               0.0s
  ----------------------------------------------
  total                                           1 failed                               0.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - Phase 3 (Reveal and page on scroll) - checkpoint outcome (run 2)

`tests/tmp/test_12_similars_on_scroll_phase3.py` exited 1 after the phase landed.

<changes>
### `client/frontend/src/pages/video-page/index.ts`
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
  tests/tmp/test_12_similars_on_scroll_phase3.py  1 failed                               0.0s
  ----------------------------------------------
  total                                           1 failed                               0.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-28 - Step 7 - stopped

Implement the plan did not complete. The entries above carry what the step established before it stopped; the gate it failed is the last of them.

