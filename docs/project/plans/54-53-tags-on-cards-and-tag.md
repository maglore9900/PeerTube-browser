# 53-tags-on-cards-and-tag

_Steps 0-6 were run by the `dev-flow` workflow; their gate evidence is in `docs/project/plans/54-53-tags-on-cards-and-tag.record.md`. The workflow refuses a plan of more than 4 phases, so from Step 7 the build continues by hand under `workflows/dev_flow.md` and this file is edited directly._

## Requirements

### Source issue

`docs/project/issues/42-tags-on-cards-and-tag-search.md` (Status: enhancement, needs-triage). It asks for three things: tags on video cards in the feeds, up-next and search; narrowing a feed or search to one or more tags; and an advanced search that takes tag criteria alongside the text query. The measured catalogue figures (2026-10-02) are in the issue under "What the catalogue holds". This plan covers only part of the issue (see Scope), and the operator expects the issue to need more than one plan.

### Purpose

Two goals, from the operator (2026-10-04):

- **More of the same:** a visitor who sees the tags on a video they like can click one to find more videos like it.
- **Narrower results:** filtering results by a tag gets the visitor more of what they are looking for.

### Scope

All set by the operator, 2026-10-04.

- **In this plan:** every video card shows the video's tags. Clicking a tag opens search results narrowed to the videos carrying that exact tag. This needs a new exact-tag filter (`tag` parameter) on the Engine's search route `/api/v1/search/videos`.
- **Cards that show tags:** feed cards and search cards (`renderVideoCard` in `client/frontend/src/components/video-card.ts`, shared by `pages/videos` and `pages/search`) and up-next cards on the video page (`renderSimilarCard` in `client/frontend/src/pages/video-page/index.ts`). Both renderers change.
- **Tag matching:** two tags are the same when they are equal after trimming and lowercasing, so 'Linux', ' linux ' and 'LINUX' all match. The same normalisation applies to the requested tag and to every stored tag. Language variants such as 'music' and 'musique' stay distinct, and no variant map is kept.
- **Which tags show:** every tag on the video, as the uploader wrote it. There is no use-count cutoff and no stoplist, so clicking a tag used only once returns only the video it came from.
- **Tags per card:** as many chips as fit on one line, in the uploader's order, followed by a `+N` marker counting the tags that did not fit. The video page already lists every tag.
- **Clickable tags:** a tag chip on a feed card, search card, up-next card or the video page opens the exact-tag results for that tag.
- **Tag results:** a tag click opens the search page with the tag in its URL and no text query. The page names the tag and lists the videos carrying it, newest first. Its existing sort menu switches the order to views or popularity.
- **Leaving tag results:** submitting the search box from the tag results runs an ordinary text search and removes the tag from the URL. Text and tag never combine in this plan.
- **Storage:** route Rt1, the FTS prefilter plus an exact check, with no new table (see Chosen route).
- **Later plans, not this one:** a filter control for narrowing any search by tags; tag filtering in the home feeds (Trending, Recent, Popular, the Recommendations mix) and in up-next; advanced search.
- **Out of scope:** category on cards or as a filter; per-tag counts; fetching tags for the 44,100 videos whose `tags_json` is NULL (that belongs to the dataset build's tags stage). A video with NULL tags shows no tags and appears in no tag results.

### Chosen route: Rt1, FTS prefilter plus exact check, no new storage

A tag request runs an FTS5 column match on `videos_fts.tags_json` (`tags_json : "<tag>"`, with the tag quoted as a string literal so it cannot inject FTS operators, following `sanitize_query` in `engine/server/data/search.py`) to get candidates. It keeps only the rows whose `tags_json` list holds the tag after trimming and lowercasing (a `json_each` comparison), and orders them by the requested sort. A tag that yields no FTS token (no word character, such as `???`, `:'(` or an emoji) falls back to a full `json_each` scan with no prefilter. That scan was measured at 0.71 s for `linux` with a warm cache, inside the Engine's 5 s statement deadline (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`, `engine/server/api/server_config.py`). The new query sits in the data layer beside `lexical_candidates` in `engine/server/data/search.py`, and it reuses that module's `LEXICAL_SORTS` orderings and its NSFW clause (`NSFW_ALLOWED_SQL`).

Rejected alternatives: Rt2, a normalised `video_tags` table, which needs a migration and a second derived copy of `tags_json`, and which this plan's speed target does not need (it may come back with the later facet and filter plans); Rt3, `LIKE` over `tags_json`, which matches JSON escapes and needs a full scan; Rt4, a tag click running `q=<tag>`, which the operator rejected in favour of exact-tag results.

Known risk: the prefilter depends on how the FTS tokenizer splits tags, which this code does not control. It gives no per-tag counts.

### Measured evidence (2026-10-04, read-only, dev `engine/server/db/whitelist.db`, 909,004 videos, warm cache, scripts in `.scratch/tags-on-cards-and-tag-search/`)

- `tag_match_timing.py`: the prefilter plus the exact check took 0.01–0.03 s for `linux` (6,243 videos), `music` (4,525), `pco` (17,464) and `partido da causa operária` (15,630), including newest-first with `LIMIT 24`. The full `json_each` scan with no prefilter took 0.71 s for `linux`.
- `fts_miss.py`: for `linux`, every video the full scan finds is among the FTS candidates. The FTS triggers in `engine/server/db/jobs/sync-whitelist.py` keep `videos_fts.tags_json` current on every insert, update or delete of a `videos` row, including the `/api/video` refresh.
- 24 of 1,731,904 tag uses contain no word character, so the tokenizer gives them no token and the prefilter cannot find them.
- `sqlite_lower_probe.py`: in the Engine's Python environment, SQLite `lower('MÚSICA')` gives `música`, the same as Python. Accented and Cyrillic tags match as FTS tokens.
- `tag_lengths.py`: the longest stored tag is 30 characters.

### Acceptance criteria

- **AC1:** every video row the Engine returns from search, from every home feed mode and from up-next carries a `tags` field: the video's tags as strings, in the uploader's order. It is `[]` when the stored `tags_json` is NULL, empty, invalid JSON or not a list. The rows go through `stable_video_rows` / `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py`, around line 106), which do not carry tags today, although the data-layer queries (`data/search.py`, `data/random_videos.py`, `data/metadata.py`) already select `tags_json`. The Client gateway passes `tags` through unchanged.
- **AC2:** feed, search and up-next cards show the tags as chips on one line. Tags that do not fit are dropped from the end and counted in a `+N` marker. A card with no tags shows no tag line. Each chip's text is set as text, never as markup, because tags come from remote instances. How many chips fit depends on the rendered layout, so it is measured after the card is in the DOM and again when the card's width changes.
- **AC3:** clicking a chip on any card, or on the video page, opens the search page for that tag at `/search.html?tag=<tag>`, with the tag URL-encoded, and does not also open the video. `/search.html` is the path every nav link uses; the client backend does not rewrite `/search`, and only the Vite dev server does. Clicking anywhere else on a card behaves as it does today.
- **AC4:** `GET /api/v1/search/videos?tag=<tag>` with no `q` returns the videos whose tag list holds `<tag>` once both sides are trimmed and lowercased, newest first (`published_at DESC, video_id DESC`). `sort=views` and `sort=popularity` reorder them using the `LEXICAL_SORTS` orderings. `sort=relevance`, `sort=published_at` or no sort means newest. Any other sort answers 400, as text search does.
- **AC5:** tag results page through every matching video, using the existing `page` and `limit` parameters and the existing `SEARCH_MAX_LIMIT` cap. `total` is the exact count of matches the `nsfw` setting allows, counted the same way as text search's `total`: before the Engine's `apply_serving_moderation_filters` and the gateway's profile blocks remove rows, so a page can hold fewer rows than `total` implies. Text search stays capped at its 200-candidate pool (`SEARCH_CANDIDATE_POOL`).
- **AC6:** tag results obey the `nsfw` parameter the same way text search does (ADR-0007: flagged videos are filtered out unless `nsfw=1`), with `include_nsfw` passed from the request edge (`_parse_include_nsfw`). The Engine applies `apply_serving_moderation_filters` to them, as it does for text search. The gateway applies the profile's blocks, dislike marks and like marks to them, as it does for text search (`/api/v1/search/videos` is in `FILTERED_ROUTES` in `client/backend/server.py`).
- **AC7:** the Engine answers 400 with a JSON `error` to a request carrying both `q` and `tag`, to a `tag` that is empty after trimming, and to a `tag` longer than 64 characters. A request with neither `q` nor `tag` still answers 400, as it does today.
- **AC8:** the tag results page names the tag and offers the newest, views and popularity sorts (relevance is not offered). It keeps `tag` and `sort` in its URL, so the back button, reload and shared links restore the same results; the newest sort leaves `sort` out of the URL. Changing the sort menu re-runs the tag search (today the menu does nothing when there is no `q`). The page's title and `popstate` handling cover tag mode as well as text mode. Submitting the search box runs an ordinary text search and removes `tag` from the URL. The gateway allowlist (`PROXY_ALLOWED_QUERY_PARAMS["/api/v1/search/videos"]` in `client/backend/server.py`) gains `tag`.
- **AC9:** a tag with no word character, such as `???` or an emoji, still returns its exact matches, through the full-scan fallback.

### Card structure (operator-approved resolution, 2026-10-04)

- **Feed and search cards (`renderVideoCard`):** the chip row is rendered outside the card's `<a class="video-link">`, inside the `<article class="video-card">`, in the same way the `card-actions` buttons sit outside it today ("a button inside an <a> would also navigate"). The card body inside the link is unchanged.
- **Up-next cards (`renderSimilarCard`):** today the whole card is one `<a class="similar-card-item">`. It becomes a container element holding the existing link and, beside it, a chip row outside the link. The `data-video-key` attribute and the existing click and stats behaviour keep working. CSS for `.similar-card-item` in `client/frontend/src/video.css` is adjusted to match.
- **Video page:** the existing tag chips (`client/frontend/src/pages/video-page/index.ts`, around line 290: `span.tag-chip` built with `textContent`) become links to `/search.html?tag=<tag>`, still built from text.
- **Chips:** reuse the video page's `tag-chip` treatment. Each chip is a real link (`<a href="/search.html?tag=...">`), so middle-click and open-in-new-tab work. In string-built card markup every interpolated value passes through `escapeHtml`, the chip href is built with `URLSearchParams`, and the dev-only `?api=` propagation follows `videoPageUrl`'s rule.

### Consistency constraints

- Card markup keeps `renderVideoCard`'s rule that every interpolated value passes through `escapeHtml` (and every external URL through `safeExternalUrl`). DOM-built chips use `textContent`.
- The new `tag` parameter follows the search route's existing style: the Engine rejects bad input with a 400 and a JSON `error`, and the gateway forwards only allowlisted parameters.
- A new listing path passes `include_nsfw` from the request edge (ADR-0007, Consequences).
- New code matches the style of the file it lands in. Smallest change that works: no new table, no new dependency, no new module unless a renderer needs a shared chip helper used by both card renderers.

### Checked in the tree (2026-10-04)

- `renderVideoCard` wraps the whole card body in one `<a class="video-link">`. The like, dislike, block and follow buttons sit outside it. The channel link is an `<a>` nested inside the card link (invalid HTML today, but left as it is in this plan).
- `renderSimilarCard` renders each up-next card as one `<a class="similar-card-item">`.
- `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py:106`) has no `tags_json`, `tags` or `category`.
- `_handle_search` (`similar.py:420`) takes `q` (required), `sort` (`relevance` or a `LEXICAL_SORTS` key), `limit`, `page` and `nsfw`. It has no tag or category parameter.
- The gateway allowlist for `/api/v1/search/videos` is `q`, `page`, `limit`, `sort`, `nsfw`.
- The search page (`client/frontend/src/pages/search/index.ts`) keeps `q` and `sort` in its URL. Its sorts are `relevance`, `published_at`, `views` and `popularity`. Its sort-change handler and `popstate` handler do nothing without a `q`.
- No Engine handler, data-layer query or frontend module filters by tag or category today.

### Baseline suite state

The pre-build baseline suite run exited with code 0 (all passing, no variant). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`. Record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.

## High-level plan

### Approach

The work has three layers: the Engine, the gateway and the frontend. Each layer gets the smallest change that meets the acceptance criteria. There is no new table, no new dependency and no new Python module. The frontend gains a shared chip helper in the existing `components/video-card.ts`, and one small stylesheet that the helper imports.

**Engine: tags on every row (AC1).** `stable_video_row` in `handlers/similar.py` adds a `tags` key to each projected row. The value is the stored `tags_json` parsed by `tags_from_json`, which already exists in `handlers/video.py` and already gives `[]` when the value is NULL, empty, invalid JSON or not a list. It also keeps the uploader's order. `video.py` imports nothing from `similar.py`, so importing it the other way creates no cycle. Search uses this projection (`similar.py:484`), and so do the feed modes and up-next (`similar.py:611`). The row sources (`data/search.py`, `data/random_videos.py`, `data/metadata.py`) already select `tags_json`. The build should still check each feed mode's row source, including Following, and a test per mode should assert `tags` is present. `STABLE_VIDEO_FIELDS` itself does not change: `tags` is derived and does not exist as a stored field. The gateway's `_filter_payload` round-trips each row as a dict, so `tags` passes through it untouched.

**Engine: the `tag` parameter (AC4, AC5, AC6, AC7, AC9).** `_handle_search` keeps its `SEARCH_ENABLED` gate and then branches on which parameter is present:
- Both `q` and `tag`: 400.
- A `tag` that is empty after trimming: 400.
- A `tag` longer than 64 characters after trimming: 400.
- Neither: the existing "Missing query parameter q" 400. `parse_qs` drops a bare `?tag=` and the gateway drops blank values, so `?tag=` reaches this branch and still gets a 400.

Every 400 uses the existing `respond_json(self, 400, {"error": ...})` form. In tag mode the sort is checked the same way as now (relevance or a `LEXICAL_SORTS` key, anything else 400). Relevance and no sort both resolve to `published_at`. `limit`, `page`, `SEARCH_MAX_LIMIT` and `_parse_include_nsfw` are parsed exactly as text search parses them. The tag branch calls a new function in `data/search.py`, placed beside `lexical_candidates`. It returns `(rows, total)` like `search_videos`, so everything after it is shared: `apply_serving_moderation_filters`, `stable_video_rows` and the same response shape. In tag mode the response's `sort` field echoes the resolved sort and `vectorSearch` is false. Text search is untouched and keeps its `SEARCH_CANDIDATE_POOL` cap.

**What the new data-layer function does.** It works under `search_connection`'s lock and `search_deadline`, and raises `SearchIndexMissing` when `videos_fts` is absent, as text search does.
- **Prefilter.** It splits the tag with the module's `_TOKEN_SPLIT`. If at least one word token survives, it builds an FTS5 column filter on `tags_json` holding one quoted phrase. Quotes are doubled, as in `sanitize_query`, so the tag cannot inject operators. It joins `videos_fts` to `videos` the way `lexical_candidates` does.
- **Fallback (AC9).** If no token survives, there is no FTS join and the query scans `videos` directly.
- **Exact check (both paths).** A `json_each` membership test compares `lower(trim(element))` with `lower(trim(?))`. The requested tag is normalised in SQL as well as the stored tags, so both sides go through one function, which is what the requirements ask for. The trim names an explicit whitespace set (space, tab, CR, LF), because SQLite's default `trim` removes only spaces while the gateway's `strip()` removes all whitespace.
- **Filtering and ordering.** It adds the `NSFW_ALLOWED_SQL` clause when `include_nsfw` is false. It orders by the `LEXICAL_SORTS` entry for the resolved sort, and pages with `LIMIT ? OFFSET ?` from `page` and `limit`.
- **Total (AC5).** A second `COUNT(*)` statement with the same FROM/WHERE runs under the same lock and deadline. So `total` counts every match the NSFW setting allows, before moderation and before the profile filters, which matches what text search's `total` counts.

**Gateway (AC6, AC8).** `tag` is added to `PROXY_ALLOWED_QUERY_PARAMS["/api/v1/search/videos"]`. That route is already in `FILTERED_ROUTES`, so blocks, dislike marks and like marks apply to tag results with no further change. The gateway strips the value, and the Engine re-trims it anyway.

**Frontend: shared chip helper (AC2, AC3).** `components/video-card.ts` gains three exports, each used by more than one caller:
- `tagSearchUrl(tag, apiParam)` builds `/search.html?tag=…` with `URLSearchParams`. It adds `api` only in a dev build, by the same rule as `videoPageUrl`.
- `renderTagChips(tags, apiParam)` returns the chip row as a string: a `.card-tags` container of `<a class="tag-chip">` links, every value through `escapeHtml`, then a hidden `+N` marker. It returns an empty string when there are no tags, so a card with no tags has no tag line.
- `observeTagRows(container)` is called once per grid container: the feed `cards`, the search `results` and the up-next `similarCards`. It installs one `MutationObserver` that finds `.card-tags` rows as they are added (by `innerHTML`, `insertAdjacentHTML` or `outerHTML` re-renders) and registers them with one shared `ResizeObserver`. The ResizeObserver's first callback runs the fit after layout, and later callbacks re-fit when the card's width changes. Removed rows are unobserved.

The fit itself: un-hide every chip and the marker, then hide chips from the end until the last visible chip plus the marker fits the row's width. The marker reads `+N` and is shown only when N > 0. The row is a no-wrap flex line with hidden overflow, so before the fit runs the worst case is a clipped chip, never a second line.

**Frontend: the cards (AC2, AC3).**
- **Feed and search cards.** `renderVideoCard` appends the chip row inside the `<article>`, after the `<a class="video-link">` and beside `card-actions`. Both pages' delegated click handlers only act on `[data-card-action]`, so a chip click is an ordinary link to the tag results and never also opens the video.
- **Up-next cards.** `renderSimilarCard` changes its outer `<a class="similar-card-item">` to a `<div class="similar-card-item">` that keeps `data-video-key`. Inside it are the existing body as `<a class="similar-card-link">` and, beside it, the chip row. The stats update at `index.ts:1613` finds the card by `[data-video-key]` and the stat spans inside it, so it keeps working.
- **CSS for up-next.** In `video.css`, the border, background and hover rules stay on `.similar-card-item`. The link takes the flex column, `color: inherit` and no underline.
- **Chip styles.** `.tag-chip` moves out of `video.css` into a small stylesheet that `video-card.ts` imports, together with the `.card-tags` row rules. That stylesheet loads on the feed, search and video pages, and there is still only one copy of the chip style.

**Frontend: the video page (AC3).** The existing chips stay DOM-built with `textContent` but become `<a class="tag-chip">` elements whose `href` comes from `tagSearchUrl`.

**Frontend: the search page in tag mode (AC8).**
- **Data module.** `data/search.ts`'s `fetchSearchResults` takes either `q` or `tag` and sets only the one given. The cache key is the URL, so tag pages are cached apart from text pages.
- **State and loading.** The page's state gains `tag`. When the URL has a `tag` and no `q`, the page runs in tag mode: the input is empty, and a heading (a new element in `search.html`, filled with `textContent`) names the tag. The title becomes "<tag> - Tag - Search - PeerTube - Browser". The status line says "Showing X of Y videos tagged …" or "No videos tagged …".
- **Sort menu.** In tag mode the relevance option is hidden and disabled, and the default sort is `published_at`. `pushUrl` leaves `sort` out when the sort is the mode's default (relevance for text, `published_at` for tag) and writes `tag` when in tag mode.
- **Handlers.** The sort-change handler and the `popstate` handler both handle tag mode as well as text mode.
- **Leaving tag mode.** A form submit clears `tag`, restores the relevance option and runs `startSearch` as now, so `tag` leaves the URL. The chosen sort is carried over (`published_at`, views and popularity are all valid text sorts).
- **URL with both `q` and `tag`.** Such a URL can only be hand-made. The page prefers `q` and drops `tag` with `replaceState`, so it never sends the combination the Engine would refuse.
- **Paging.** Infinite scroll keeps its existing `page`/`total` logic. Tag results page through the whole match set because `total` is now exact.

### Alternatives considered

- **Window `COUNT(*) OVER ()` instead of a second count statement.** Rejected. It saves one statement on the cheap path, but a page past the end returns no rows and therefore no total, which breaks AC5. The count costs about 0.01–0.03 s on the prefilter path, and about 0.7 s more on the full-scan fallback, which only affects the rare tags with no word character.
- **Normalising the requested tag in Python and the stored tags in SQL.** Rejected. Python's `lower`/`strip` and SQLite's `lower`/`trim` disagree on whitespace and on a few Unicode cases (for example `İ`). Running both sides through the same SQL expression is how the "same normalisation on both sides" requirement holds by construction.
- **Calling a fit function after each render site instead of a `MutationObserver`.** Rejected. The three pages insert cards from about nine places (reset, append, in-place `outerHTML` re-renders after a like, dislike or block, and `removeRows`), and every new insertion path would have to remember to call it. One observer per container covers all of them with three call sites.
- **CSS-only truncation.** Rejected. CSS can clip the line but cannot count the hidden chips for `+N`.
- **Putting the chips inside `.video-link` and stopping propagation.** Rejected. It nests an `<a>` inside an `<a>` and breaks middle-click, and the operator approved the outside-the-link structure.
- **Importing `videos.css` on the video page, or copying `.tag-chip` into it.** Rejected. Importing it would bring in feed styles that could collide; copying it would give two copies to keep in step.
- **A separate `_handle_tag_search` route or handler.** Rejected. AC4 puts tag search on `/api/v1/search/videos`. Branching inside `_handle_search` shares the moderation, projection and response code instead of duplicating it.
- **Falling back to a full scan whenever the FTS prefilter returns nothing.** Rejected. It would hide tokenizer mismatches, but every search for a tag nobody uses would cost a 0.7 s scan, which is an easy load amplifier. The fallback stays tied to "no word token", as the settled route says.

### Gotchas and risks

- **`json_each` and bad `tags_json`.** `json_each` raises on malformed JSON, which would turn a single bad row into a 500 for the whole tag query. It also iterates an object's values, which would wrongly match a non-list. The exact check therefore feeds `json_each` a CASE that substitutes `'[]'` unless `tags_json` is valid JSON and of type `array`, and it compares only `text` elements. A guard in a separate AND term is not enough, because SQLite does not promise evaluation order.
- **Tokenizer mismatch (the known risk of Rt1).** The prefilter's phrase comes from Python's `\w` split, but the index was built by FTS5's `unicode61`. Where the two disagree, matches are missed and the gap is not reported. One example is a tag stored with a JSON escape inside it (`a\nb` is indexed as `a`, `nb`). Another is a character Python counts as a word character but `unicode61` treats as a separator. `to_tags_json` writes raw UTF-8, and `fts_miss.py` showed no misses for `linux`, so the expected gap is a handful of edge-case rows. Rt2 is the upgrade path if it ever matters.
- **Superset matches are fine.** `unicode61` removes diacritics and folds case, and a phrase can run across adjacent tags. Both only widen the candidate set, and the exact check discards the extras.
- **SQLite `lower()` on the search connection.** The probe showed Unicode-aware `lower()` in the Engine's environment. Tests should run an accented tag (`MÚSICA` vs `música`) through the real search connection, so a build without that behaviour fails loudly instead of quietly matching ASCII only.
- **Deep pages.** With an exact `total`, a visitor can scroll deep into `pco` (17,464 rows). `OFFSET` paging gets slower linearly with depth but stayed well inside the deadline at the measured sizes. The fallback scan costs about 1.4 s per page (page plus count), which is also inside the 5 s deadline.
- **Short pages stop scrolling.** The gateway and moderation can remove every row on a page. The page's existing `rows.length > 0` stop condition then ends scrolling early. Text search already behaves this way, and AC5 accepts short pages.
- **Rows past the end of a pool.** The `+N` fit needs layout. The ResizeObserver's initial callback provides it, and until that callback runs the row is clipped, not wrapped. Hidden chips leave the accessibility tree, and the marker carries an `aria-label` ("N more tags").
- **Up-next markup change breaks a test.** `tests/active/test_frontend_video_page_similars.py` asserts on `similar-card-item`, so it has to change in this build. The built bundle under `client/frontend/dist` is regenerated output and is not edited by hand.

### Tradeoffs the operator is asked to accept

- A tag search costs two statements per page (rows plus count) in exchange for an exact `total`.
- Rare tokenizer-mismatch tags can return fewer videos than they carry. This is the accepted Rt1 risk, and Rt2 is the upgrade path.
- The `+N` marker is plain text, not a control. To see every tag, the visitor opens the video, whose page lists them all.
- The chip row adds one line of height to every card that has tags. Cards without tags are unchanged, so card heights in a grid can differ.
- A hand-made URL carrying both `q` and `tag` is silently reduced to the text search.

## Impacts

Note on the tree: `/home/enduser/code/PeerTube-browser/.worktrees/55` does not exist (rg: "No such file or directory"; Glob finds nothing under `.worktrees/`), although `tests/config.json:3` names it as `project_dir`. Every file below was opened in the main checkout `/home/enduser/code/PeerTube-browser`, and paths are relative to the repo root. An earlier pass of this step is already written into `docs/project/plans/54-53-tags-on-cards-and-tag.md`. I re-checked its claims against the source and they hold. Below I add what it lacks: stored blank or over-64 tags producing dead chips, the absence of any custom SQLite `lower()`, `test_similar`'s group missing `handlers/video.py`, the existing nested `channel-link` anchor, and `popstate` pushing history through `showIdle`.

<impact path="engine/server/api/handlers/similar.py" element="stable_video_row (129-131) / stable_video_rows (134-136); new import of tags_from_json">
**What changes:** `stable_video_row` returns `{field: row.get(field) for field in STABLE_VIDEO_FIELDS}` plus `"tags": tags_from_json(row.get("tags_json"))`. `STABLE_VIDEO_FIELDS` (106-126, with the `INCLUDE_DYNAMIC_STATS` tail at 125-126) is unchanged. A new import line is added: `from handlers.video import tags_from_json`.

**What depends on it:**
- Exactly two callers: `_handle_search` (484) and `_respond_rows` (611). `_respond_rows` serves every feed mode (random, ordered trending/popular/recent, following, home mix and its fallback), up-next, the raw-vector route and seed-random.
- `maybe_attach_debug` (139) spreads the stable row, so `tags` survives in debug mode.
- Row sources that carry `tags_json` (verified):
  - `data/search.py:66` (`VIDEO_ROW_SQL`)
  - `data/metadata.py:49,91,198` (`fetch_metadata`, which up-next and vector search use)
  - `data/random_videos.py:59,115,160,204,248`
  - `_ordered_row` (`random_videos.py:292`), which serves `fetch_ordered_page` and Following's `fetch_followed_page` (417)
- `apply_serving_moderation_filters` (`data/serving_moderation.py:14-48`) returns the row dicts it was given and does not rebuild them.

**Import cycle:** none. `router.py:44` already imports `handlers.video`, and `similar.py:85` imports `router`, so `handlers.video` is always loaded before `similar.py` finishes importing. `video.py` imports only `data.*`, `http_utils` and `server_config` (9-21).

**Regression risk: low.** The change is additive and `tags_from_json` never raises. No test pins the exact key set of an Engine listing row: `test_random_videos.py:591` checks a subset, and `test_metadata.py:40` and `test_internal_client_reads.py:27` check data-layer rows. `tags` is remote-controlled text that now reaches every listing payload and the `innerHTML`/`insertAdjacentHTML`/`outerHTML` sinks on three pages.
</impact>

<impact path="engine/server/api/handlers/similar.py" element="_handle_search (420-486); import line 27; module docstring (3) and method docstring (421)">
**What changes**
- After the `SEARCH_ENABLED` gate (426-428), read `tag` beside `q` (430). Validation: `q`+`tag` → 400; a tag that strips to empty → 400; a stripped tag longer than 64 → 400; neither → the existing `"Missing query parameter q"` (431-433).
- The sort check (435-438) stays. In tag mode only, `relevance` or a missing sort resolves to `published_at`. Text mode must keep `relevance` as its default, because `search_videos` branches on `sort == "relevance"` for the vector half (`data/search.py:293`).
- `limit` and `page` (440-446) stay shared.
- The tag call must sit inside the same `except SearchIndexMissing` → 503 handler (464-467) and pass `include_nsfw=_parse_include_nsfw(...)` (defined at 1089).
- Moderation and `stable_video_rows` (468-484) stay shared.
- The response echoes the resolved `sort`, and `vectorSearch` is `False` in tag mode (today 483 derives it from the encoder).
- Line 27 gains the new function name. The docstrings at 3 and 421 say "hybrid video search".

**Detail:** Python `strip()` removes all Unicode whitespace, while the planned SQL trim removes only space, tab, CR and LF. Bind the Python-stripped value, so a direct Engine call with NBSP padding still matches.

**No named constant exists for 64.** `SEARCH_MAX_TOKEN_LENGTH = 64` (`server_config.py:460`) is the per-FTS-token cap, a different limit.

**What depends on it:**
- `router.py:98-100` (`parse_qs`, no `keep_blank_values`).
- The rate-limit gate.
- `_serve` (410-418): an interrupted statement becomes 503 "Query time limit exceeded" (400).
- Live text-search tests: `test_similar.py:140,142`, `test_frontend_follows.py:83`, plus the gateway-driven tests in the blocks, reactions and upnext-pager files.

**Regression risk: medium.** The branch sits in front of the text path. Resolving relevance→published_at outside tag mode silently disables vector fusion for text search, and mis-reading `tag` lets `q`+`tag` through.
</impact>

<impact path="engine/server/data/search.py" element="new tag-search function beside lexical_candidates (134-168); module docstring (1-10); search_videos docstring (271-277)">
**What changes:** a new function returning `(rows, total)`.
- It copies the shape of `search_videos` 283-290: `search_connection` (32-43) → `with lock:` → `with search_deadline(server):` (46-49) → `fts_available` (121-131) → `SearchIndexMissing`.
- **Prefilter:** split with `_TOKEN_SPLIT` (25) and build one quoted phrase on the `tags_json` column, doubling quotes as at 112. It joins `videos_fts f JOIN videos v ON v.rowid = f.rowid LEFT JOIN channels c ...` as at 157-160.
- **Fallback:** `FROM videos v LEFT JOIN channels c`.
- **Exact check:** `EXISTS(SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) AND json_type(v.tags_json)='array' THEN v.tags_json ELSE '[]' END) j WHERE j.type='text' AND lower(trim(j.value, set)) = lower(trim(?, set)))`.
- **NSFW:** `AND {NSFW_ALLOWED_SQL}` when the flag is False; it is already imported (20).
- **Order:** `LEXICAL_SORTS[sort]` (83-87).
- **Paging:** `LIMIT ? OFFSET ?`.
- **Total:** a second `COUNT(*)` with the same FROM/WHERE.
- Rows reuse `VIDEO_ROW_SQL`, as the text path does. There is no `video_embeddings` join and no error threshold, the same as text search (`test_search.py:27`).
- Default `include_nsfw=True`, per ADR-0007 decision 1.
- The module docstring (1-10) and the `search_videos` docstring (271-277, "fused candidate set") describe only hybrid search.

**Facts checked against files**
- No custom SQL function is registered on any Engine connection. Grep for `create_function` finds only `ann_id_of` in the jobs (`sync-whitelist.py:510`, `whitelist_migrations.py:407`), and `connect_readonly_db` (`data/db.py:85`) adds none. Unicode-aware `lower()` therefore depends entirely on the SQLite build (ICU) in the Engine's pixi env. SQLite core `lower()` folds ASCII only. I cannot confirm the plan's probe from files; tests must run on `ENGINE_PY`.
- FTS5 tokenizes the phrase string with the table's own `unicode61` tokenizer. A Python token like `foo_bar` is therefore re-split into the phrase `foo bar`, which narrows the Rt1 gap rather than widening it.

**What depends on it:** `_handle_search`; `tests/active/test_search.py`.

**Regression risk: medium-high, all in SQL semantics**
- `json_each` raises on malformed JSON, so the guard must sit inside its argument.
- The trim set and the `lower()` build behaviour must be handled as above.
- The FTS phrase must stay a quoted literal.
- `OFFSET` cost grows with depth.
- The `views` sort has no index (only `idx_videos_published` and `idx_videos_popularity`, `sync-whitelist.py:402-405`), so a views-sorted fallback scan sorts the whole match set.
</impact>

<impact path="engine/server/api/handlers/video.py" element="tags_from_json (164-174); to_tags_json (156-161)">
**What changes:** no change to either body. `tags_from_json` gains a second importer.

**What depends on it:**
- `/api/video`'s `tags` (345), and now every listing row.
- `to_tags_json` writes `ensure_ascii=False` (160), as does the crawler's `toTagsJson` (`engine/crawler/src/videos-worker.ts:820-824`, `JSON.stringify`). Stored tags are therefore raw UTF-8, which keeps the Rt1 gap small.
- Neither writer filters empty, whitespace-only or long strings, so stored tags can be `""`, `"  "` or longer than 64 characters (see the video-card entry).

**Regression risk: low.** A future change here now changes every listing as well as `/api/video`.
</impact>

<impact path="engine/server/api/server_config.py" element="SEARCH_* block (450-470)">
**What changes:** optional. Add `SEARCH_MAX_TAG_LENGTH = 64` beside `SEARCH_MAX_TOKEN_LENGTH` (460) and import it in `similar.py` (37-64). The plan names neither the constant nor a literal.

**What depends on it:** many test groups list this file (for example `test_similar.py`, `test_dislike_profile.py`, `test_internal_translate.py`), and `test_similar.py:130-135` execs it.

**Regression risk: low.**
</impact>

<impact path="engine/server/api/router.py" element="module docstring route list (11); _search (98-100)">
**What changes:** line 11 reads `GET /api/v1/search/videos: hybrid video search. [rate-limit gate]` and should mention the exact-tag mode. `_search` is unchanged, since it forwards every parsed parameter.

**What depends on it:** nothing new.

**Regression risk: none.**
</impact>

<impact path="engine/server/db/jobs/sync-whitelist.py" element="videos_fts DDL (393-401) and triggers (275-290): read-only dependency">
**What changes:** nothing.

**What depends on it:** the prefilter depends on `videos_fts` keeping its `tags_json` column under the default `unicode61` tokenizer, and on the AI/AD/AU triggers keeping it in step, including `/api/video/refresh` writes (`video.py:391`).

**Regression risk:** none from this build. A future tokenizer or column change would silently drop tag matches.
</impact>

<impact path="client/backend/server.py" element="PROXY_ALLOWED_QUERY_PARAMS['/api/v1/search/videos'] (104); _sanitize_query (138-154); _handle_engine_read_proxy_get (595-604); _filter_payload (1393-1419)">
**What changes:** line 104 becomes `{"q", "page", "limit", "sort", "nsfw", "tag"}`.

**Inherited behaviour**
- `tag` is stripped, because it is not in `PROXY_UNSTRIPPED_QUERY_PARAMS` (120), and dropped when empty. A repeated `tag` gets the gateway's own 400.
- The query is re-encoded with `urlencode` (752).
- The route is in `FILTERED_ROUTES` (83) and `PROXY_READ_GET_ROUTES` (95-97), so keyed tag results get blocks and reaction marks. It is not in `FEED_ROUTES`, so there is no over-fetch and no dislike removal.
- `_filter_payload` round-trips row dicts, so `tags` passes. It re-encodes with default `ensure_ascii` (1419), so non-ASCII tags arrive `\u`-escaped, which is equivalent JSON.

**What depends on it:**
- `client/frontend/src/data/search.ts` (its docstring says "exactly five").
- `test_server.py:1549` pins only the `nsfw` allowlist on `/api/video`.
- No test asserts that `tag` is unknown.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/components/video-card.ts" element="new exports tagSearchUrl / renderTagChips / observeTagRows; renderVideoCard (341-419); new side-effect CSS import; module docstring (1-12)">
**What changes**
- **`tagSearchUrl`:** mirrors `videoPageUrl`'s DEV-only `api` rule (330).
- **`renderTagChips`:**
  - Returns `""` for a missing, non-array or empty list. Rows cached before the deploy lack `tags`.
  - Escapes every value with `escapeHtml` (67-84).
  - The `+N` marker starts `hidden` and carries an `aria-label`.
  - It must not emit `style="..."`, because every page's CSP is `style-src 'self'` (`search.html:8`). The precedent comment is at `video.css:62`.
- **`observeTagRows`:** one `MutationObserver` plus one shared `ResizeObserver`. Neither may be constructed at module level, and calling it where `MutationObserver` is undefined throws, which matters for the node harnesses below.
- **`renderVideoCard`:** puts the row after `</a>` at 416, beside `actionsMarkup`.

**Gaps the plan does not settle**
- **Dead chips.** Stored tags can be blank, whitespace-only or longer than 64 characters, since neither writer caps them (see the `video.py` entry):
  - A chip for `""` or `"  "` links to `?tag=` or `?tag=%20`. The gateway drops the value and the Engine answers "Missing query parameter q", or the search page sees no tag and shows idle.
  - A chip for a tag longer than 64 characters links to a guaranteed 400.
  - The helper should skip blank tags. Whether to skip over-length tags or link them anyway is an open decision.
- **Existing nested anchor.** The card already nests `<a class="channel-link">` inside `<a class="video-link">` (402). The plan's "no nested `<a>`" applies only to the chips.

**What depends on it**
- `pages/videos/index.ts:36-51`: the home feed and the `/videos.html?id=` similar view.
- `pages/search/index.ts:14-20`.
- `pages/likes/index.ts:9`: helpers only, but it now pulls in the CSS chunk.
- `pages/video-page/index.ts:29`.
- `test_frontend_video_card.py:39` (with `--loader:.css=empty`).
- `test_frontend_reactions.py:106-121`, which bundles without a CSS loader flag.

**Regression risk: medium.** The risks are an XSS sink if any interpolation is missed, a `ReferenceError` in harnesses, and the CSP silently dropping inline styles.
</impact>

<impact path="client/frontend/src/tags.css (new file; name to be chosen)" element="new shared sheet: .tag-chip moved from video.css 408-415, plus .card-tags row and +N marker rules">
**What changes**
- `.tag-chip` moves here, using `--line` and `--ink` from `base.css`.
- Chips become `<a>`, so the sheet needs `text-decoration: none` and an explicit colour. There is no global `a` rule; `.video-link` is scoped (`videos.css:297`).
- `.card-tags` is a no-wrap flex row with `overflow: hidden` and `min-width: 0`.
- A `[hidden] { display: none }` override is needed for any element given a display value. The precedents are `video.css:388,486`.

**Build hazard**
- `video-card` is already its own Vite chunk (`dist/assets/video-card-DWtpz1-l.js`). Vite has no `manualChunks` or `cssCodeSplit` override (`vite.config.ts:82-96`), so a CSS import there emits a separate `video-card-*.css` linked from index, videos, likes, search and video-page.
- `test_frontend_base_css.py:100` asserts that the linked bundles are exactly `["channels","search","video","videos"]`.
- 105-115 require every linked bundle to open with the full built base and contain no `@import`.
- The new bundle fails both checks unless the sheet `@import`s `./base.css`, which duplicates base. Search already loads base twice, through `videos.css` and `search.css`.

**What depends on it:** the `tests/config.json` groups for base-css (355-362) and dist (363-412).

**Regression risk: high** (build and test contract).
</impact>

<impact path="client/frontend/src/video.css" element=".tag-list (402-406), .tag-chip (408-415), .similar-card-item (528-539) and :hover (541-544)">
**What changes**
- Remove `.tag-chip`.
- `.similar-card-item` keeps its padding, border, radius, background, transition, hover, and a flex column so the link and the chip row stack. `text-decoration` and `color` move to a new `.similar-card-link`, which takes `display:flex; flex-direction:column; gap:0.5rem` to keep the inner spacing.
- The `.similar-thumb`, `.similar-title`, `.similar-channel`, `.similar-meta` (546-602) and `.similar-reaction` selectors still match inside the link.
- `.tag-list` (the video page's full list) must stay wrapping.
- `.similar-card` (36) is a different selector (the section panel).

**What depends on it:** `test_frontend_base_css.py`, `test_frontend_dist.py`, and the `test_frontend_video_page.py` group (`tests/config.json:230`).

**Regression risk: low-medium** (visual, on the `.similar-grid` at 522-526).
</impact>

<impact path="client/frontend/src/videos.css" element=".video-card (281), .video-link (297), .card-actions (496-502)">
**What changes:** probably none, since the new sheet supplies the row. The chip row becomes a direct child of `.video-card`, after `.video-link`.

**What depends on it:** `.cards-grid` (257) on the feed and search pages.

**Regression risk: low.** Cards with tags grow by one line, which is an accepted tradeoff.
</impact>

<impact path="client/frontend/src/pages/video-page/index.ts" element="tag chips (290-304); import (29)">
**What changes:** `createElement("span")` (295) becomes `createElement("a")`, keeping `className="tag-chip"` and `textContent`, and gaining `href = tagSearchUrl(tag, params.get("api"))`. `params` is at line 82. Add `tagSearchUrl` to the import at 29. The "No tags" branch (302) stays.

**What depends on it:** `test_frontend_video_page.py:4-5,189,306-330` reads the children's `textContent` and the `tag-chip` class. The recording element has an `href` accessor (86-87).

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/pages/video-page/index.ts" element="renderSimilarCard (1688-1721); applySimilarStatsToDom (1610-1617); similarCards render sites 357, 369, 375, 384, 388, 708; local videoPageUrl (1655-1676)">
**What changes**
- The outer `<a class="similar-card-item" href=…${keyAttribute}>` (1710) becomes `<div class="similar-card-item"${keyAttribute}>` wrapping `<a class="similar-card-link" href=…>`, plus `renderTagChips(row.tags, params.get("api"))`.
- The page keeps its own `escapeHtml` and `videoPageUrl`; the local one adds no `api`.
- `observeTagRows(similarCards)` is called once. `similarCards` is nullable (61), so the call goes after the null check, for example in `loadSimilarVideos` after 343, guarded so it runs only once.
- `applySimilarStatsToDom` still finds `[data-video-key]` (now on the div) and `[data-stat="views"]`.

**Render sites:** 375 (`innerHTML`) and 708 (`insertAdjacentHTML`).

**What depends on it:** `test_frontend_video_page_similars.py` (see that entry). Middle-click now targets only the inner link, so the card padding is no longer clickable.

**Regression risk: medium.**
</impact>

<impact path="client/frontend/src/pages/videos/index.ts" element="cards container (55-68); renderCards (390-409); renderFeedCard (414-423); runCardAction outerHTML (457); click delegation (151-157)">
**What changes:** call `observeTagRows(cards)` once after the guard at 66-68. `renderFeedCard` already passes `apiParam` (84, 418). The click handler acts only on `[data-card-action]`. `existingCount` counts `.video-card` (403), so the new row does not affect it.

**What depends on it:** `test_frontend_videos_page.py`.
- The `HOME_RUNNER` harness (33-66) defines `IntersectionObserver` only.
- The second harness (315-316) defines `IntersectionObserver` and `ResizeObserver`.
- Neither defines `MutationObserver`.

**Regression risk: medium.** An unguarded observer fails every case at import.
</impact>

<impact path="client/frontend/src/pages/search/index.ts" element="state (60-73); init (75-76, 139-144); submit (95-103); sort change (105-108); popstate (126-137); startSearch (165-172); loadPage (180-236); showIdle (342-352); pushUrl (357-368); resolveSort (381-384); module docstring (1-10)">
**What changes**
- **State and load:** add `state.tag`. A URL with `tag` and no `q` means tag mode. `q`+`tag` means `q` wins and `pushUrl(true)` drops `tag` with `replaceState`.
- **The idle path pushes history at load.** 143 → `showIdle()` → `pushUrl()` (351) → `pushState`. Tag mode needs its own branch before that.
- **Popstate:** it reads only `q` and `sort` and calls `showIdle()` when `q` is empty, which pushes a new entry during `popstate`. Without changes, back-navigation into a tag page becomes idle and destroys forward history.
- **Sort change:** it returns early on `!state.query` (106).
- **`resolveSort`:** it defaults to `relevance` (383) and needs a mode-aware default.
- **Submit:** it clears `tag` and restores the relevance option. Its empty-submit path (98-100) goes through `showIdle`, which must also clear `state.tag`.
- **`pushUrl`:** writes `tag` in tag mode and omits `sort` at the mode default.
- **`loadPage`:** passes `tag` or `q` (193-199).
- **Status lines:** 226 and 233 change for tag mode. The comment at 231-232 ("fused candidate pool") is false in tag mode.
- **Titles:** `document.title` at 140 and 170.
- **Errors:** an Engine 400 (a hand-made tag over 64 characters) shows "Search failed. The Engine may be unavailable." (210). Any 503, including the deadline 503, shows the no-index message (205).
- Call `observeTagRows(results)` once. The `outerHTML` re-renders (290, 295), `removeRows` (335) and the reset (185) are covered by the observer.
- **Docstring:** line 6.
- **Paging:** `hasMore` (234) uses `loadedRows < total && rows.length > 0`. With blocks removing rows, `loadedRows` never reaches the exact `total`, so paging stops only on an empty page. That costs one extra request at the end and is harmless.

**What depends on it:** no harness bundles this page. `tests/config.json:405` lists it only for dist.

**Regression risk: medium.** It is an untested multi-handler state machine.
</impact>

<impact path="client/frontend/search.html" element="new tag heading in .search-controls (31-56); #search-sort relevance option (47); CSP (8)">
**What changes:** a new heading element (`hidden` by default). The relevance option is toggled from script. The CSP stays as it is and rules out inline chip styles.

**What depends on it:** `requireElement` (39-45) throws on a missing id; the dist byte-comparison test.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/search.css" element="optional heading rule">
**What changes:** optional styling for the tag heading.

**What depends on it:** `test_frontend_base_css.py`: the search bundle must still open with base.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/data/search.ts" element="FetchSearchOptions (24-31); fetchSearchResults (57-91); docstring (1-9)">
**What changes:** `q` becomes optional and `tag?: string` is added. 60-61 always sets `q` today, and the function must set exactly one of the two. The cache key `search:${url}` (80) separates tag pages from text pages. The docstring's "exactly five" becomes six.

**What depends on it:** callers passing `{q}`:
- `pages/search/index.ts:193`
- `test_frontend_blocks.py:68`
- `test_frontend_feed_params.py:329` (checks the built URL)
- `test_frontend_reactions.py:113`

**Regression risk: low**, provided `q` behaves exactly as before and an empty `tag` is never set.
</impact>

<impact path="client/frontend/src/types/videos.ts" element="VideoRow (5-62); SearchPayload docstring (70-75)">
**What changes:** add `tags?: string[] | null`. The `SearchPayload` docstring says `total` is the fused pool; in tag mode it is the exact match count.

**What depends on it:** type-only.

**Regression risk: none.**
</impact>

<impact path="client/frontend/dist/" element="committed build output: seven HTML pages and assets/">
**What changes:** regenerate with `vite build` with no local `dev-pages/about.html`, and commit. The new CSS chunk adds a `<link>` to five pages.

**What depends on it:** `test_frontend_dist.py:24-25` compares asset names and page bytes with a fresh build.

**Regression risk: medium.** A stale dist is a certain red.
</impact>

<impact path="tests/active/test_frontend_base_css.py" element="test at 97-115 (control at 100; base-prefix checks 105-115); docstring 1-3">
**What changes:** it fails as soon as `video-card.ts` imports a sheet. The two ways out:
- Amend it to admit exactly one component bundle, and update the docstring.
- Change the design, for example chip rules in `base.css` or imported from each page sheet. Either needs the operator's approval.

**Regression risk: high.**
</impact>

<impact path="tests/active/test_frontend_dist.py" element="test at 17-25">
**What changes:** no code change. It passes only after a rebuilt and committed dist.

**Regression risk: high** if the rebuild is forgotten.
</impact>

<impact path="tests/active/test_frontend_video_page_similars.py" element="_keys regex (140-142); first-batch regex (153); docstring (4-5); RUNNER globals (75-80)">
**What changes**
- Both regexes match `<a … similar-card-item …>`. Retarget them to the div, or to `similar-card-link` and the key on the div.
- The docstring says "anchors".
- The harness has `ResizeObserver` (75) but no `MutationObserver`, and its `querySelectorAll` returns `[]`. Add a stub.

**Regression risk: high** (a known, certain break).
</impact>

<impact path="tests/active/test_frontend_video_page.py" element="RUNNER globals (116), PAGE_RUNNER globals (660-661), tag assertions (4-5, 189, 306-330)">
**What changes:** add `MutationObserver` stubs to both harnesses, and add an `href` assertion (`/search.html?tag=…`, no `api` with DEV false).

**Regression risk: medium** (an import-time `ReferenceError` fails every case).
</impact>

<impact path="tests/active/test_frontend_translate.py" element="video-page harnesses (globals 158 and 479; bundles 228 and 550)">
**What changes:** both bundle `pages/video-page/index.ts` and lack `MutationObserver`, so add stubs.

**Regression risk: medium.**
</impact>

<impact path="tests/active/test_frontend_videos_page.py" element="HOME_RUNNER globals (63-66); second harness globals (315-316)">
**What changes:** add `MutationObserver` stubs to both harnesses, and `ResizeObserver` to the first. Optionally assert that one observer watches `video-cards`.

**Regression risk: medium.**
</impact>

<impact path="tests/active/test_frontend_reactions.py" element="_bundle (106-124)">
**What changes:** it bundles `video-card.ts` with no `--loader:.css=empty` (115-121). esbuild then writes `bundle.css` beside the JS and the import must resolve. Adding the flag gives parity with the other bundlers.

**Regression risk: low.**
</impact>

<impact path="tests/active/test_frontend_video_card.py" element="card assertions; bundle (39)">
**What changes:** none is required, since its rows carry no tags. It is the natural home for `renderTagChips` and `tagSearchUrl` unit cases: escaping, empty and missing lists, skipped blank tags, the hidden `+N` marker, DEV-only `api`, and no `style=`.

**Regression risk: low.**
</impact>

<impact path="tests/active/test_search.py" element="_statements fixture (36-54); _CHILD runner (57-83)">
**What changes:** this is where the data-layer tag tests go, on `ENGINE_PY` (18). The INSERT (49) sets no `tags_json`, so the fixture needs it or a sibling file is needed. The `server` namespace (68) has no `statement_timeout_seconds`, so the deadline is 0. Cases to cover:
- the token path and the fallback path
- malformed, object and NULL `tags_json`
- trim and case, including `MÚSICA`/`música`
- the NSFW `total`
- paging past the end
- the sorts

**Regression risk: low.**
</impact>

<impact path="tests/active/test_similar.py" element="_rows (138-153); test_every_row_carries_the_channel_and_account_the_dataset_holds (156-166)">
**What changes:** AC1 needs `tags` on every mode. The parametrisation covers home, random, upnext and search; add trending, popular, recent and following (with a `follows` body). Live tag-route cases go here: the four 400s, the sort echo, `vectorSearch` false, the exact `total`, and NSFW.

**Regression risk: low.**
</impact>

<impact path="tests/active/conftest.py" element="identity_of (305-312)">
**What changes:** a per-mode `tags` comparison needs the stored `tags_json`. Every caller (`test_similar.py:161`, `test_frontend_follows.py:86,89`) reads by key, so adding a key or a sibling helper is safe.

**Regression risk: low.**
</impact>

<impact path="tests/config.json" element="test_groups: test_similar.py (55+), test_search.py (261-264), test_frontend_video_page.py (228-233), test_frontend_video_page_similars.py (238-241), test_frontend_translate.py (427-435), test_frontend_base_css.py (355-362), test_frontend_dist.py (363-412)">
**What changes**
- Add `engine/server/api/handlers/video.py` to `test_similar.py`'s group, since `similar.py` now uses `tags_from_json`.
- Add `components/video-card.ts` to the video-page, similars and translate groups.
- Add the new sheet to the base-css and dist groups.
- Add `server_config.py` to `test_search.py` if the constant is added.
- Map any new test file.

**Regression risk: low.** A missed mapping only means a test is not reselected on edit.
</impact>

<impact path="docs/project/adr/0007-nsfw-filter-default-at-request-edge.md" element="Decisions 1-2 (8-17)">
**What changes:** nothing is required. The ADR constrains the build: the new function defaults `include_nsfw=True`, and `_handle_search` passes the parsed flag. Decision 2 (17) names only `search_videos`; amending it is optional.

**Regression risk:** forgetting the flag serves NSFW tag results to every visitor.
</impact>

## Documentation to update

- [ ] `engine/server/README.md` - "What it does" (6-28) has no bullet for `GET /api/v1/search/videos`; only line 53 mentions it, for `nsfw`. Add one covering:
- `q` text search.
- The exclusive `tag` mode: an exact match after trimming and lowercasing both sides.
- The 400s: both parameters, a blank tag, a tag over 64 characters, and neither.
- Sort: relevance or none means newest in tag mode; views and popularity reorder; anything else is 400.
- `page` and `limit` with the `SEARCH_MAX_LIMIT` cap.
- `total`: exact and pre-moderation in tag mode, against the 200-candidate pool in text mode.
- `vectorSearch` is false in tag mode.
- Every listing row now carries `tags`: in the uploader's order, `[]` for NULL, invalid or non-list values.

Extend line 53 so the NSFW filter also covers tag search.
- [ ] `client/README.md` - - Line 34: `/api/v1/search/videos` also allowlists `tag`, which is stripped and dropped when empty.
- Line 29: blocks and reaction marks apply to tag results (no dislike removal, no over-fetch).
- [ ] `client/frontend/README.md` - - Feed, search and up-next cards show tag chips linking to `/search.html?tag=…`, fitted to one line with a `+N` marker. Video-page tags become links.
- The search page's tag mode:
  - the heading and the title format
  - the "Showing X of Y videos tagged …" and "No videos tagged …" status lines
  - relevance hidden, with `published_at` as the default
  - `tag` and `sort` kept in the URL
  - a submit leaving tag mode
  - a URL with both `q` and `tag` reduced to `q`
- Line 18: "Showing N of M matched videos." applies to text search only.
- Line 8: the gateway routes list is unchanged.
- [ ] `client/frontend/src/data/search.ts` - The module docstring (1-9) says the gateway allowlists "exactly five query parameters". It becomes six, with `tag`, and the function sends exactly one of `q` and `tag`.
- [ ] `CONTEXT.md` - Add a glossary entry for **Tag** / **tag search**:
- the uploader's tags as stored in `videos.tags_json`
- two tags are the same after trimming and lowercasing; language variants stay distinct
- tag search is the exact-tag mode of the search route, distinct from the full-text match on the `tags_json` FTS column
- [ ] `docs/project/roadmap.md` - After delivery, add a DONE line for issue 42's first plan (tags on cards and exact-tag search) pointing at `docs/project/plans/54-53-tags-on-cards-and-tag.md`. Note that multi-tag narrowing, feed and up-next tag filters, and advanced search remain open.
- [ ] `docs/project/issues/42-tags-on-cards-and-tag-search.md` - Record what this plan delivered and what stays open. The issue stays open (`Status: enhancement, needs-triage` at line 3), because the operator expects more plans.
- [ ] `docs/project/adr/0007-nsfw-filter-default-at-request-edge.md` - Optional: in Decision 2 (line 17), name the new tag-search function as a second `include_nsfw` callee of `_handle_search`.

## Implementation plan

## Draft implementation: tags on cards and exact-tag search (issue 42, plan 54)

I read these files before drafting: `data/search.py`, `handlers/similar.py` (1-160, 400-500), `handlers/video.py` (`to_tags_json` and `tags_from_json`), `server_config.py` (the SEARCH block), `client/backend/server.py` (the allowlist), `components/video-card.ts`, `pages/search/index.ts`, `search.html`, `data/search.ts`, `types/videos.ts`, `video.css` (380-609), `videos.css` (`.video-card`, `.video-link`, `.card-actions`), `base.css`, `pages/video-page/index.ts` (tags 290-304, `loadSimilarVideos`, `renderSimilarCard`, `applySimilarStatsToDom`), `pages/videos/index.ts` (55-68), `test_frontend_base_css.py`, `test_search.py`, `test_similar.py` (100-170), `test_frontend_video_page_similars.py` (130-169), and `conftest.identity_of`. The harness grep confirmed that no harness defines `MutationObserver`.

### Decisions that differ from the high-level plan (named)

1. **Chip CSS lives in `base.css`, not in a sheet imported by `video-card.ts`.** The operator approved this on 2026-10-04 via AskUser. A sheet imported from the component would make Vite emit a fifth `video-card-*.css` bundle, which breaks the pinned contract in `test_frontend_base_css.py:100,105-115`. Putting the rules in `base.css` still leaves one copy. It needs no new file and no new bundle, and the test needs no change: `base.css` is already inlined at the head of `videos.css`, `video.css` and `search.css`, and so of every page that shows chips. The channels page also carries about 25 unused lines. As a consequence, `video-card.ts` imports no CSS, and `test_frontend_reactions.py` needs no `--loader:.css=empty`.
2. **`observeTagRows` does nothing when `MutationObserver` or `ResizeObserver` is undefined.** Every supported browser has both, and only the node harnesses lack them. This replaces adding stubs to five harnesses: `test_frontend_video_page.py` (two harnesses), `test_frontend_video_page_similars.py`, `test_frontend_translate.py` (two harnesses) and `test_frontend_videos_page.py` (two harnesses). Ceiling: no harness exercises the fit. The fit is covered by a dedicated unit case in `test_frontend_video_card.py` that stubs both observers. Upgrade path: stub the observers in a page harness if a page-level fit test is ever wanted.
3. **Unlinkable stored tags.** A tag that is blank after trimming, or longer than 64 code points, would link to a guaranteed 400 (or to idle). `tagSearchUrl` returns `null` for such a tag.
   - Cards skip it.
   - The video page still lists it, as a plain `span.tag-chip` with no link, so the video page keeps listing every tag.
   - Today no stored tag is over 64 characters (the longest is 30), so in practice only blank tags are affected.
4. **The `total` count statement leaves out the `channels` LEFT JOIN.** That join cannot remove a row. It could only duplicate one if `channels` held duplicate keys, so leaving it out counts distinct matching videos. The page statement keeps the join, exactly as `lexical_candidates` does.
5. **The FTS phrase is the `_TOKEN_SPLIT` tokens joined with spaces and quoted as one string literal, as the settled route says.** FTS5 re-tokenizes the literal with the table's own `unicode61` tokenizer, so tokens such as `foo_bar` are split again and the gap with the index shrinks. If every Python token turns out to be a separator to `unicode61`, the phrase is empty and matches nothing. That is the accepted Rt1 risk.
6. **A popstate into the idle state no longer pushes a history entry.** `showIdle` gains a `updateUrl = true` parameter, and `popstate` passes `false`. This is a pre-existing bug, but the tag-mode `popstate` path runs through the same function, and leaving it in would destroy forward history after back-navigation.

### Module map

| File | Change |
|---|---|
| `engine/server/api/server_config.py` | + `SEARCH_MAX_TAG_LENGTH = 64` |
| `engine/server/data/search.py` | + `TAG_TRIM_SQL`, `TAG_MATCH_SQL`, `tag_match_expression`, `search_videos_by_tag`; docstrings |
| `engine/server/api/handlers/similar.py` | `stable_video_row` adds `tags`; `_handle_search` tag branch; imports; docstrings |
| `engine/server/api/router.py` | docstring line 11 only |
| `client/backend/server.py` | allowlist line 104 gains `"tag"` |
| `client/frontend/src/base.css` | + `.tag-chip`, `a.tag-chip:hover`, `.card-tags`, `.card-tags > *`, `.tag-more` |
| `client/frontend/src/video.css` | − `.tag-chip`; `.similar-card-item` loses link styling; + `.similar-card-link` |
| `client/frontend/src/videos.css` | + `.video-card > .card-tags` padding |
| `client/frontend/src/search.css` | + `.search-tag` |
| `client/frontend/search.html` | + `<h2 id="search-tag" class="search-tag" hidden></h2>` |
| `client/frontend/src/components/video-card.ts` | + `tagSearchUrl`, `renderTagChips`, `observeTagRows` (private `fitTagRow`); `renderVideoCard` appends the chip row |
| `client/frontend/src/types/videos.ts` | `VideoRow.tags?: string[] \| null`; `SearchPayload` docstring |
| `client/frontend/src/data/search.ts` | `q?`, `tag?`; sends exactly one; docstring says six parameters |
| `client/frontend/src/pages/search/index.ts` | tag mode |
| `client/frontend/src/pages/videos/index.ts` | `observeTagRows(cards)` |
| `client/frontend/src/pages/video-page/index.ts` | linked tag chips; `renderSimilarCard` div + link + chips; `observeTagRows(similarCards)` |
| `client/frontend/dist/` | rebuilt with `vite build` (no local `dev-pages/about.html`) and committed |

No new module, table or dependency.

### Engine

**`server_config.py`**, after line 460:

```python
SEARCH_MAX_TOKEN_LENGTH = 64
# Longest tag the exact-tag mode accepts, in characters after trimming; the longest stored tag is 30.
SEARCH_MAX_TAG_LENGTH = 64
```

**`data/search.py`**, beside `lexical_candidates`:

```python
# Whitespace both sides of a tag comparison lose. SQLite's one-argument trim() removes only spaces.
TAG_TRIM_SQL = "' ' || char(9, 10, 13)"

# True when the row's tag list holds the bound tag once both are trimmed and lowercased. The same SQL
# expression normalises both sides, so they cannot disagree. CASE short-circuits, so json_type and
# json_each never see malformed JSON (json_each would raise and fail the whole query); non-arrays
# become an empty list, and only string elements compare.
TAG_MATCH_SQL = f"""EXISTS (
  SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) THEN CASE json_type(v.tags_json) WHEN 'array' THEN v.tags_json ELSE '[]' END ELSE '[]' END) j
  WHERE j.type = 'text' AND lower(trim(j.value, {TAG_TRIM_SQL})) = lower(trim(?, {TAG_TRIM_SQL}))
)"""


def tag_match_expression(tag: str) -> str:
    """Build the FTS5 prefilter for one tag: a column filter on tags_json holding one quoted phrase.

    The phrase is a string literal with its quotes doubled, as in :func:`sanitize_query`, so a tag
    cannot inject operators. Empty when the tag has no word character, which sends the caller to
    the full-scan fallback.
    """
    tokens = [token for token in _TOKEN_SPLIT.split(tag) if token]
    if not tokens:
        return ""
    return 'tags_json : "' + " ".join(tokens).replace('"', '""') + '"'


def search_videos_by_tag(
    server: Any,
    tag: str,
    page: int,
    limit: int,
    sort: str = "published_at",
    include_nsfw: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of the videos carrying ``tag`` exactly, plus the exact match count.

    FTS narrows to the rows whose tags_json holds the tag's words, and :data:`TAG_MATCH_SQL` keeps
    only true tag matches. A tag with no word character has no FTS token, so it scans every row
    (about 0.7 s on the full dataset). `total` counts every allowed match, so the page can draw
    exact paging.

    :param tag: Tag as the caller sent it, already stripped.
    :param sort: A key of :data:`LEXICAL_SORTS`.
    :param include_nsfw: False leaves NSFW-flagged rows out of the page and the count.
    :returns: ``(rows_for_page, total_matches)``.
    """
    match_expression = tag_match_expression(tag)
    if match_expression:
        source = "videos_fts f JOIN videos v ON v.rowid = f.rowid"
        where = f"videos_fts MATCH ? AND {TAG_MATCH_SQL}"
        args: list[Any] = [match_expression, tag]
    else:
        source = "videos v"
        where = TAG_MATCH_SQL
        args = [tag]
    if not include_nsfw:
        where += f" AND {NSFW_ALLOWED_SQL}"
    order_by = LEXICAL_SORTS[sort]
    offset = max(0, (page - 1) * limit)

    conn, lock = search_connection(server)
    with lock:
        with search_deadline(server):
            if not fts_available(conn):
                raise SearchIndexMissing(
                    "videos_fts is not present in this database; run the dataset build's "
                    "sync stage to create it."
                )
            query = conn.execute(
                f"""
                SELECT
                {VIDEO_ROW_SQL}
                FROM {source}
                LEFT JOIN channels c
                  ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
                WHERE {where}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                (*args, limit, offset),
            )
            rows = [dict(row) for row in query]
            total = conn.execute(f"SELECT COUNT(*) FROM {source} WHERE {where}", args).fetchone()[0]

    logging.info("[search] tag prefilter=%s rows=%d total=%d sort=%s", bool(match_expression), len(rows), total, sort)
    return rows, int(total)
```

Invariants:
- Every caller value is bound as a parameter. Only module constants are formatted into the SQL.
- The tag is bound already Python-stripped and the SQL trims it again, so NBSP padding on a direct Engine call still matches and stored tags are normalised the same way.
- `sort` must be a `LEXICAL_SORTS` key; the handler guarantees this.
- The function defaults to `include_nsfw=True`, as ADR-0007 decision 1 requires.

Docstrings:
- The module docstring gains one paragraph: "The exact-tag mode (`search_videos_by_tag`) is not ranked: it filters to one tag and orders by date, views or popularity."
- The `search_videos` docstring says it covers text search only.

**`handlers/similar.py`**
- Line 27 becomes `from data.search import LEXICAL_SORTS, SearchIndexMissing, search_videos, search_videos_by_tag`.
- Add `SEARCH_MAX_TAG_LENGTH` to the `server_config` import.
- Add `from handlers.video import tags_from_json`. There is no cycle: `router` already imports `handlers.video`, and `video.py` imports only `data.*`, `http_utils` and `server_config`.
- Docstring line 3: "hybrid video search" becomes "video search (hybrid text, or exact tag)".

```python
def stable_video_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project a row to stable fields returned to clients, plus its tags parsed from tags_json."""
    stable = {field: row.get(field) for field in STABLE_VIDEO_FIELDS}
    stable["tags"] = tags_from_json(row.get("tags_json"))
    return stable
```

`_handle_search`. The docstring becomes: "Answer a video search request: hybrid text search on `q`, or exact-tag search on `tag`; the two never combine." After the `SEARCH_ENABLED` gate:

```python
        raw_query = (params.get("q", [""])[0] or "").strip()
        tag = (params.get("tag", [""])[0] or "").strip()
        tag_mode = "tag" in params
        if tag_mode and "q" in params:
            respond_json(self, 400, {"error": "Use either q or tag, not both"})
            return
        if tag_mode and not tag:
            respond_json(self, 400, {"error": "Empty tag parameter"})
            return
        if len(tag) > SEARCH_MAX_TAG_LENGTH:
            respond_json(self, 400, {"error": f"Tag longer than {SEARCH_MAX_TAG_LENGTH} characters"})
            return
        if not tag_mode and not raw_query:
            respond_json(self, 400, {"error": "Missing query parameter q"})
            return

        sort = params.get("sort", ["relevance"])[0] or "relevance"
        if sort not in LEXICAL_SORTS and sort != "relevance":
            respond_json(self, 400, {"error": "Unsupported sort"})
            return
        # Tag results have no relevance to rank by; text search keeps relevance, which switches on its vector half.
        if tag_mode and sort == "relevance":
            sort = "published_at"

        # limit / page parsing unchanged

        # Search never enters _handle_similar, so no request context carries the flag here.
        include_nsfw = _parse_include_nsfw(params.get("nsfw", [None])[0])
        try:
            if tag_mode:
                rows, total = search_videos_by_tag(self.server, tag, page=page, limit=limit, sort=sort, include_nsfw=include_nsfw)
            else:
                rows, total = search_videos(
                    self.server,
                    raw_query,
                    # ... the arguments are unchanged ...
                    include_nsfw=include_nsfw,
                )
        except SearchIndexMissing as exc:
            # unchanged
        # moderation unchanged
        encoder = getattr(self.server, "query_encoder", None)
        respond_json(self, 200, {
            # ...
            "sort": sort,
            "vectorSearch": bool(not tag_mode and encoder is not None and encoder.enabled),
            "rows": stable_video_rows(filtered_rows),
        })
```

Notes on the handler:
- `parse_qs` drops blank values, so `?tag=` is absent and reaches the "Missing query parameter q" branch. `?tag=%20` is present, strips to empty, and gets "Empty tag parameter".
- `?q=%20&tag=x` carries both and gets a 400.
- The length check runs on the stripped value and counts code points (Python `len`).
- Text mode is byte-for-byte the previous behaviour.

**`router.py` line 11:** `GET /api/v1/search/videos: hybrid text search (q) or exact-tag search (tag). [rate-limit gate]`

### Gateway

`client/backend/server.py:104` becomes `"/api/v1/search/videos": {"q", "page", "limit", "sort", "nsfw", "tag"},`. Everything else is inherited:
- `tag` is stripped, and dropped when empty.
- Because the route is in `FILTERED_ROUTES`, blocks and reaction marks apply.
- `_filter_payload` passes `tags` through.

### Frontend

**`base.css`** (appended after `.visually-hidden`):

```css
/* Tag chips: the video page's full list and every card's one-line row. Chips are links, so the link look is reset here. */
.tag-chip {
  padding: 0.12rem 0.55rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.6);
  color: var(--ink);
  font-size: 0.8rem;
  text-decoration: none;
  white-space: nowrap;
}

a.tag-chip:hover {
  border-color: var(--accent);
}

/* One line on a card. observeTagRows in components/video-card.ts hides the chips that do not fit, from the end, and counts them in .tag-more. */
.card-tags {
  display: flex;
  gap: 0.35rem;
  align-items: center;
  overflow: hidden;
  min-width: 0;
}

/* Only flex-shrink, never display, so the hidden attribute still hides a chip. */
.card-tags > * {
  flex-shrink: 0;
}

.tag-more {
  color: var(--muted);
  font-size: 0.8rem;
  white-space: nowrap;
}
```

Before the fit runs, the row is clipped by `overflow: hidden` and never wraps. No `[hidden]` override is needed, because no chip rule sets `display`.

**`video.css`:**
- Delete `.tag-chip` (408-415).
- `.tag-list` stays as it is, with `flex-wrap: wrap`.
- `.similar-card-item` keeps `display:flex; flex-direction:column; gap:0.5rem; padding; border-radius; border; background; transition` and loses `text-decoration` and `color`.
- `.similar-card-item:hover` is unchanged.
- New rule:
  ```css
  .similar-card-link {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    text-decoration: none;
    color: inherit;
  }
  ```

**`videos.css`**, after `.card-actions`: `.video-card > .card-tags { padding: 0 1.05rem 0.9rem; }`. This matches the inset of `.card-actions`.

**`search.css`:** `.search-tag { margin: 0 0 0.6rem; font-size: 1.2rem; }`. The sheet still opens with `@import "./base.css"`.

**`search.html`:** `<h2 id="search-tag" class="search-tag" hidden></h2>` as the first child of `<section class="search-controls">`. The CSP is unchanged, and no inline style is emitted anywhere.

**`types/videos.ts`:**
- Add `/** The uploader's tags, in their order; absent on rows cached before the Engine sent them. */ tags?: string[] | null;` to `VideoRow`.
- The `SearchPayload` docstring now says: "In text search, `total` counts the fused candidate pool; in tag search it is the exact count of matching videos before moderation and profile filters."

**`components/video-card.ts`.** The module docstring gains: "It also renders the tag chip row every card shows, and fits it to one line." New code goes after `videoPageUrl`:

```ts
/** Longest tag the Engine's tag search accepts (SEARCH_MAX_TAG_LENGTH); a longer one would link to a 400. */
const TAG_MAX_LENGTH = 64;

/**
 * Build the link to the search page's results for one tag, or null when the tag cannot be searched (blank, or longer than the Engine accepts).
 *
 * `apiParam` is propagated only in a dev build, by the rule of `videoPageUrl`.
 */
export function tagSearchUrl(tag: string, apiParam?: string | null) {
  const value = tag.trim();
  // Counted in code points, as the Engine's len() counts them.
  if (!value || Array.from(value).length > TAG_MAX_LENGTH) return null;
  const params = new URLSearchParams();
  params.set("tag", value);
  if (apiParam && import.meta.env.DEV) params.set("api", apiParam);
  return `/search.html?${params.toString()}`;
}

/**
 * Render a card's tag row: one link per searchable tag in the uploader's order, then a hidden `+N` marker that observeTagRows fills.
 *
 * Returns "" when there is no tag to show, so a card without tags has no tag line. Tags come from remote instances, so every value is escaped.
 */
export function renderTagChips(tags: VideoRow["tags"], apiParam?: string | null) {
  if (!Array.isArray(tags)) return "";
  const chips = tags.flatMap((tag) => {
    if (typeof tag !== "string") return [];
    const href = tagSearchUrl(tag, apiParam);
    return href ? [`<a class="tag-chip" href="${escapeHtml(href)}">${escapeHtml(tag)}</a>`] : [];
  });
  if (!chips.length) return "";
  return `<div class="card-tags">${chips.join("")}<span class="tag-more" hidden></span></div>`;
}

/**
 * Show every chip, then hide chips from the end until the rest and the `+N` marker fit the row's width.
 */
function fitTagRow(row: HTMLElement) {
  const chips = Array.from(row.querySelectorAll<HTMLElement>(".tag-chip"));
  const more = row.querySelector<HTMLElement>(".tag-more");
  if (!more) return;
  for (const chip of chips) chip.hidden = false;
  more.hidden = true;
  let hidden = 0;
  while (hidden < chips.length && row.scrollWidth > row.clientWidth) {
    hidden += 1;
    chips[chips.length - hidden].hidden = true;
    more.textContent = `+${hidden}`;
    more.setAttribute("aria-label", `${hidden} more ${hidden === 1 ? "tag" : "tags"}`);
    more.hidden = false;
  }
}

let tagRowResizer: ResizeObserver | null = null;
/** The width each row was last fitted at, so a height-only change does not re-fit it. */
const fittedWidths = new WeakMap<Element, number>();

/**
 * Fit every card tag row that enters `container`, now or later, once it has a layout and again whenever its width changes.
 *
 * Cards reach the grids by innerHTML, insertAdjacentHTML and outerHTML from many places, so one observer per container finds them instead of a call after each render. Outside a browser (the node test harnesses) the observers are absent and this does nothing.
 */
export function observeTagRows(container: HTMLElement) {
  if (typeof MutationObserver === "undefined" || typeof ResizeObserver === "undefined") return;
  tagRowResizer ??= new ResizeObserver((entries) => {
    for (const entry of entries) {
      const width = entry.contentRect.width;
      if (fittedWidths.get(entry.target) === width) continue;
      fittedWidths.set(entry.target, width);
      fitTagRow(entry.target as HTMLElement);
    }
  });
  const resizer = tagRowResizer;
  const rowsIn = (node: Node) =>
    node instanceof HTMLElement
      ? node.matches(".card-tags") ? [node] : Array.from(node.querySelectorAll<HTMLElement>(".card-tags"))
      : [];
  for (const row of rowsIn(container)) resizer.observe(row);
  new MutationObserver((records) => {
    for (const record of records) {
      record.addedNodes.forEach((node) => rowsIn(node).forEach((row) => resizer.observe(row)));
      record.removedNodes.forEach((node) => rowsIn(node).forEach((row) => resizer.unobserve(row)));
    }
  }).observe(container, { childList: true, subtree: true });
}
```

Why the observers cannot loop:
- `hidden` toggles are attribute mutations, which the `childList` observer ignores.
- The marker's text-node change yields no `.card-tags` row.
- The width memo stops a re-fit after the fit's own height change.

Observer lifetime: there is one shared `ResizeObserver` per page, created lazily, never at module level. The `MutationObserver`s are not stored, because their containers live as long as the page.

`renderVideoCard`: line 416 becomes `</a>${renderTagChips(row.tags, options.apiParam)}${actionsMarkup}`. The chip row sits outside the link, as the sibling just before `card-actions`. The card body is unchanged.

**`pages/videos/index.ts`:** add `observeTagRows` to the import. After the guard at 66-68, add `observeTagRows(cards);`. The delegated click handler acts only on `[data-card-action]`, so a chip click is a plain link.

**`pages/video-page/index.ts`:**
- Import `observeTagRows`, `renderTagChips` and `tagSearchUrl` from `../../components/video-card`.
- After the `params` declaration (82): `if (similarCards) observeTagRows(similarCards);`
- Tag chips (290-300):

```ts
      // Tags come from remote instances, so each chip is built from text, never from markup; a tag the search cannot take stays a plain chip.
      tagsEl.replaceChildren(
        ...tags.map((tag) => {
          const href = tagSearchUrl(tag, params.get("api"));
          const chip = document.createElement(href ? "a" : "span");
          chip.className = "tag-chip";
          chip.textContent = tag;
          if (href) (chip as HTMLAnchorElement).href = href;
          return chip;
        })
      );
```

`renderSimilarCard`:

```ts
  return `
    <div class="similar-card-item"${keyAttribute}>
      <a class="similar-card-link" href="${escapeHtml(videoPageUrl(row))}">
        <div class="similar-thumb">
          ${thumbMarkup}
          <span class="duration">${escapeHtml(duration)}</span>
        </div>
        <h4 class="similar-title">${escapeHtml(title)}</h4>
        <p class="similar-channel">${escapeHtml(channel)}</p>
        <p class="similar-meta"><span data-stat="views">${formatStatValue(views)}</span> views${escapeHtml(timeSuffix)}</p>
        ${reactionMarkup}
      </a>
      ${renderTagChips(row.tags, params.get("api"))}
    </div>
  `;
```

`applySimilarStatsToDom` still finds `[data-video-key]` (now on the div) and the `data-stat="views"` span inside it.

**`data/search.ts`:**
- Docstring: "exactly six query parameters (`q`, `tag`, `page`, `limit`, `sort`, `nsfw`)". It now also says: "A request carries exactly one of `q` and `tag`."
- `FetchSearchOptions` becomes `q?: string; tag?: string;`.
- In `fetchSearchResults`:

```ts
  const tag = (options.tag ?? "").trim();
  // Exactly one of the two: the Engine answers 400 to both. Without a tag, q is sent exactly as before.
  if (tag) url.searchParams.set("tag", tag);
  else url.searchParams.set("q", (options.q ?? "").trim());
```

The cache key `search:${url}` keeps tag pages apart from text pages.

**`pages/search/index.ts`** (tag mode):
- The module docstring line 6 becomes: "...until the Engine's candidate pool (text) or match set (tag) is exhausted. A `tag` in the URL, with no `q`, lists the videos carrying that exact tag; submitting the box leaves tag mode."
- New elements and the `TAG_DEFAULT_SORT` constant:

```ts
const tagHeading = requireElement<HTMLElement>("search-tag");
const relevanceOption = sortSelect.querySelector<HTMLOptionElement>('option[value="relevance"]');
if (!relevanceOption) throw new Error("Missing search page element: relevance sort option");
const TAG_DEFAULT_SORT: SearchSort = "published_at";
```

- `state`:
  - `query: (params.get("q") ?? "").trim()`
  - new `tag: ""`
  - `sort: "relevance" as SearchSort`
  - After the declaration: `state.tag = state.query ? "" : (params.get("tag") ?? "").trim(); state.sort = resolveSort(params.get("sort"), Boolean(state.tag));`. A URL carrying both keeps `q`.
- Remove `input.value = …; sortSelect.value = …;` (75-76). `applyMode()` does both.
- Submit: `startSearch(next, "", state.sort);`. The relevance option comes back through `applyMode`. A tag-mode sort (published_at, views or popularity) is valid in text mode too. An empty submit calls `showIdle()`, which also clears `tag`.
- Sort change:

```ts
sortSelect.addEventListener("change", () => {
  if (!state.query && !state.tag) return;
  startSearch(state.query, state.tag, resolveSort(sortSelect.value, Boolean(state.tag)));
});
```

- After the results click listener: `observeTagRows(results);`. This covers the reset, appends, `outerHTML` re-renders and `removeRows`.
- `popstate`:

```ts
window.addEventListener("popstate", () => {
  const current = new URLSearchParams(window.location.search);
  state.query = (current.get("q") ?? "").trim();
  state.tag = state.query ? "" : (current.get("tag") ?? "").trim();
  state.sort = resolveSort(current.get("sort"), Boolean(state.tag));
  if (!state.query && !state.tag) {
    // The address bar already holds this entry; pushing would drop the forward history.
    showIdle(false);
    return;
  }
  applyMode();
  void loadPage(1, true);
});
```

- Initial load:

```ts
if (state.query || state.tag) {
  applyMode();
  // A hand-made URL carrying both keeps q; drop tag so the Engine never sees the pair it refuses.
  if (state.query && params.has("tag")) pushUrl(true);
  void loadPage(1, true);
} else {
  showIdle();
}
```

- `startSearch(query: string, tag: string, sort: SearchSort)` sets `query`, `tag`, `sort` and `page = 1`, then runs `applyMode(); pushUrl(); void loadPage(1, true);`.
- New `applyMode()`:

```ts
/**
 * Show the mode the state is in: the tag heading, the sort menu (no relevance for tag results), the box and the title.
 */
function applyMode() {
  const tagMode = Boolean(state.tag);
  relevanceOption.hidden = tagMode;
  relevanceOption.disabled = tagMode;
  tagHeading.hidden = !tagMode;
  tagHeading.textContent = tagMode ? `Videos tagged "${state.tag}"` : "";
  input.value = state.query;
  sortSelect.value = state.sort;
  document.title = tagMode
    ? `${state.tag} - Tag - Search - PeerTube - Browser`
    : state.query
      ? `${state.query} - Search - PeerTube - Browser`
      : "Search - PeerTube - Browser";
}
```

- `loadPage`:
  - Fetch with `fetchSearchResults({ q: state.query, tag: state.tag, page, limit: PAGE_SIZE, sort: state.sort, apiBase: apiParam })`.
  - Empty result: `setStatus(state.tag ? \`No videos tagged "${state.tag}".\` : \`No results for "${state.query}".\`);`.
  - Results: `setStatus(state.tag ? \`Showing ${state.loadedRows} of ${state.total} videos tagged "${state.tag}".\` : \`Showing ${state.loadedRows} of ${state.total} matched videos.\`);`.
  - The comment at 231-232 becomes: "In text search `total` is the fused candidate pool, not a corpus count; in tag search it is the exact match count before moderation and blocks."
  - `hasMore` is unchanged.
  - All status text goes through `textContent`.
- `showIdle(updateUrl = true)`:
  - Also clears `state.tag`.
  - Calls `applyMode()` in place of the title line. Its `sort` is kept as `state.sort` when valid in text mode, which is always.
  - Calls `pushUrl()` only when `updateUrl` is true.
- `pushUrl`:

```ts
  if (state.query) next.set("q", state.query);
  else if (state.tag) next.set("tag", state.tag);
  if (state.sort !== (state.tag ? TAG_DEFAULT_SORT : "relevance")) next.set("sort", state.sort);
```

- `resolveSort(value, tagMode = false)`:

```ts
function resolveSort(value: string | null, tagMode = false): SearchSort {
  const candidate = (value ?? "").trim() as SearchSort;
  // Tag results have no relevance; it means newest there, as the Engine reads it.
  if (!SORTS.includes(candidate) || (tagMode && candidate === "relevance")) return tagMode ? TAG_DEFAULT_SORT : "relevance";
  return candidate;
}
```

Limitation (named): a hand-made tag over 64 characters reaches the Engine, gets a 400, and the page shows the generic "Search failed" line.

### What the build must test

Engine data layer: extend `tests/active/test_search.py`, or add a sibling `test_search_tags.py` with its own fixture. Either way the reads run on `ENGINE_PY` through the real `sqlite3`.
- The fixture holds rows whose `tags_json` is:
  - `["Linux"," linux ","x"]`
  - `["LINUX"]`
  - `["linuxmint"]`
  - `["MÚSICA"]` against `["música"]`
  - `["???"]`
  - `["\t???\n"]`
  - malformed `[`
  - an object `{"a":"linux"}`
  - `[1, "linux"]` with a non-text element
  - NULL
  - an NSFW row tagged linux
  - a row whose description says linux but whose tags do not
- Cases:
  1. `linux` matches exactly the rows carrying linux under trim and case. `linuxmint`, description-only, malformed, object and NULL rows are absent, and the malformed row raises nothing.
  2. `música` matches `MÚSICA`, which is the Unicode `lower()` check. If it fails, the SQLite build folds ASCII only.
  3. `???` takes the fallback (assert `tag_match_expression("???") == ""`) and matches both stored forms.
  4. Default order is `published_at DESC, video_id DESC`, and `views` and `popularity` follow `LEXICAL_SORTS`.
  5. With `include_nsfw=False`, the NSFW row is missing from both the rows and `total`.
  6. Paging: pages cover the match set with no overlap; a page past the end gives `[]` and the full `total`.
  7. With no `videos_fts`, the function raises `SearchIndexMissing`.
  8. `tag_match_expression('a"b')` quotes safely.

Engine route (`test_similar.py`, live Engine):
- AC1:
  - Extend the `route` parametrisation to trending, popular, recent and following (with a `follows` body) as well as home, random, upnext and search.
  - Every row has `tags` as a list of strings equal to `tags_from_json` of the stored `tags_json`.
  - Add a `tags_json` read beside `identity_of` in `conftest.py`.
- AC7: 400 with a JSON `error` for:
  - `q`+`tag`
  - `tag=%20`
  - a 65-character tag
  - no parameter (`?tag=` included)
- AC4: a stored tag fetched with `?tag=<Upper-cased>`:
  - every row carries it
  - `sort` echoes `published_at` for none and relevance
  - `views` reorders
  - `sort=bogus` gives 400
  - `vectorSearch` is false
- AC5: `total` equals a direct `COUNT` on `whitelist.db` under `nsfw` off, and text search's `total` stays ≤ 200.

Gateway (`test_server.py` or the blocks test): `tag` is forwarded, and a blocked channel's video is missing from tag results.

Frontend unit (`test_frontend_video_card.py`):
- `tagSearchUrl`:
  - encoding (`a b&c` gives `tag=a+b%26c`)
  - `api` present only with DEV
  - `null` for a blank tag and for a 65-code-point tag
- `renderTagChips`:
  - `""` for undefined, null, `[]` and blank-only lists
  - `<script>` arrives escaped
  - there is no `style=`
  - the marker is `hidden`
  - chip order is the uploader's
- `renderVideoCard`: the `.card-tags` row sits after `</a>` and never inside `video-link`.
- Fit (stub `ResizeObserver`/`MutationObserver` and widths): five chips with room for two give two visible chips, `+3` and `aria-label="3 more tags"`; a wider row re-fits.

Frontend pages:
- `test_frontend_video_page.py`: the chips are `a.tag-chip` with `href=/search.html?tag=…` and no `api` when DEV is false.
- `test_frontend_video_page_similars.py`:
  - Retarget both regexes to `<div … similar-card-item …>`, which still carries `data-video-key`.
  - The docstring's "anchors" becomes "cards".

Build:
- `test_frontend_base_css.py` and `test_frontend_dist.py` pass unchanged after `dist` is rebuilt.
- There is no search-page harness. Tag mode is checked by hand: load, sort, back, reload, submit, and a `q`+`tag` URL.

`tests/config.json` mappings:
- `engine/server/api/handlers/video.py` → the `test_similar.py` group.
- `components/video-card.ts` → the video-page, similars and translate groups.
- `src/base.css` → already in base-css and dist; confirm.
- `server_config.py` → `test_search.py`.
- Any new test file gets its own mapping.

### Check against the plan and the requirements

| Item | Met by |
|---|---|
| AC1 | `stable_video_row` + `tags_from_json`; both callers (search, `_respond_rows`) |
| AC2 | `renderTagChips` + `observeTagRows`/`fitTagRow`; escape; `""` on no tags; measured after insertion and on width change |
| AC3 | `a.tag-chip` outside every video link; `/search.html?tag=` via `URLSearchParams`; DEV-only `api` |
| AC4 | `TAG_MATCH_SQL` normalises both sides in SQL; relevance/none → `published_at`; bad sort 400 |
| AC5 | `LIMIT/OFFSET` + `COUNT(*)` before moderation; text pool untouched |
| AC6 | `include_nsfw` from `_parse_include_nsfw`; shared moderation; route already in `FILTERED_ROUTES` |
| AC7 | four 400 branches |
| AC8 | heading, title, relevance hidden, URL `tag`/`sort` with newest omitted, sort and popstate in tag mode, submit leaves tag mode, allowlist |
| AC9 | `tag_match_expression` → `""` → full scan |
| Consistency | `escapeHtml` on every interpolation; `textContent` for DOM chips; no new table, dependency or module |

Converged in one pass. The deviations are the six decisions named at the top; only the first changes an approved design, and the operator approved it.

### Documentation the build updates

These are the settled items. With chips in `base.css`, `client/frontend/README.md` gains a line saying the chip rules live in the shared base.
- `engine/server/README.md`:
  - a search route bullet (`q`/`tag`, the 400s, sorts, `total`, `vectorSearch`, `tags` on every row)
  - line 53 extended to say the NSFW filter covers tag search
- `client/README.md`, lines 29 and 34.
- `client/frontend/README.md`:
  - card chips, linked video-page chips, search tag mode
  - line 18 scoped to text search
- `data/search.ts` docstring (above).
- `CONTEXT.md`: a **Tag** / **tag search** entry.
- `docs/project/roadmap.md`: a DONE line plus the open items.
- `docs/project/issues/42-…md`: what was delivered and what stays open; the status is unchanged.
- ADR-0007 Decision 2 (optional): name `search_videos_by_tag`.


### Phases

#### Phase 1 — Engine exact-tag data layer

**Kind:** code

**Intent:** `engine/server/data/search.py` gains `search_videos_by_tag`. It returns one page of the videos whose `tags_json` holds the requested tag, with the same SQL trim-and-lowercase applied to both the stored tags and the requested one, together with the exact count of the matches the NSFW setting allows.

**Clauses:**

- `C1` The rows `search_videos_by_tag` returns are exactly the videos that carry the tag once both sides are trimmed and lowercased by the same SQL expression. This holds whether the FTS prefilter or the no-token full scan finds them.
- `C2` The `total` that `search_videos_by_tag` returns counts every match the NSFW setting allows, whatever page is requested.

**Checkpoint and seam:** Seam: `search_videos_by_tag` in `engine/server/data/search.py`, called on `ENGINE_PY` through the real `sqlite3` (rung 1). It follows the subprocess harness in `tests/active/test_search.py` (`_statements` + `_CHILD` run via `subprocess.run([ENGINE_PY, "-c", ...])`), in a sibling `tests/active/test_search_tags.py` that has its own fixture. The fixture's rows have these `tags_json` values: `["Linux"," linux ","x"]`, `["LINUX"]`, `["linuxmint"]`, `["MÚSICA"]`, `["???"]`, `["\t???\n"]`, malformed `[`, the object `{"a":"linux"}`, `[1,"linux"]`, NULL, an NSFW row tagged linux, and a row with linux only in its description. It also has a `videos_fts` built over them.

For C1:
- `linux` returns exactly the rows that carry it after trimming and lowercasing, `[1,"linux"]` included through its text element. The linuxmint, description-only, malformed, object and NULL rows are absent, and the malformed row raises nothing.
- `música` returns the `MÚSICA` row through the real search connection. If it fails, the SQLite build only folds ASCII.
- `tag_match_expression("???") == ""`, and `???` returns both the `["???"]` row and the `["\t???\n"]` row through the full-scan fallback.
- `tag_match_expression('a"b')` holds the doubled quote inside one phrase, and the query runs without an FTS syntax error.

For C2:
- `total` equals the number of matching rows on page 1, on a later page, and on a page past the end (which returns `[]`).
- Walking every page covers the match set with no overlap.
- With `include_nsfw=False`, the NSFW row is missing from both the rows and `total`.

Inner unit, by exception: with no `videos_fts`, the function raises `SearchIndexMissing`.

**Files:** engine/server/api/server_config.py (EDITED), engine/server/data/search.py (EDITED), tests/active/test_search_tags.py (NEW), tests/config.json (EDITED)

**Checkpoint file:** `tests/tmp/test_search_tags.py` (every build test goes in `working`; the harvest moves it to `tests/active`). Scaffolding landed first: `tag_match_expression` and `search_videos_by_tag` in `data/search.py` raise `NotImplementedError`, so the red is on behaviour, not on a missing symbol.

**Deviations from the Step 6 checkpoint text, from observation** (probe `tests/tmp/probe_tag_sql.py`, run on `ENGINE_PY`):
- The probe showed a JSON-escaped `\t` in stored `tags_json` is indexed by FTS as the token `tlinux`, so a `["\tlinux "]` row is invisible to the prefilter (the accepted Rt1 tokenizer risk). The FTS-path trim row is `["  linux "]`; the tab trim is exercised on the full-scan path by `["\t???\n"]`.
- `["linux","mint"]` carries `linux` exactly, so it is a match for `linux`; it is the near-miss for `linux mint` instead, where the probe showed FTS returns it alongside `["linux mint"]`.
- The malformed row is the unterminated `["linux"` rather than `[`: it is an FTS candidate for `linux`, and the probe showed a bare `json_each` over it raises `OperationalError('malformed JSON')`.
- `tag_match_expression('a"b')`: `_TOKEN_SPLIT` removes the quote, so no doubled quote survives to assert on. The case is asserted by behaviour instead: the tag returns only its own row, with no FTS error.
- The `SearchIndexMissing` inner unit is deferred to 7.5, where it is written only if the checkpoint cannot express it.

**Self-check rows:**
- `C1` — `test_search_tags.py:121`, the sorted rows for `linux` — expected: `L1, MIX, NS, SPLIT, TRIM, UPPER` — under the FTS prefilter alone (no exact check): `BAD, L1, MIX, NS, OBJ, PHRASE, SPLIT, TRIM, UPPER` (observed); under an exact check without trim: `TRIM` missing; under `json_each` without the CASE guard: an `OperationalError` entry.
- `C1` — `:122`, the rows for `linux mint` — expected: `PHRASE` — under the prefilter alone: `PHRASE, SPLIT` (observed).
- `C1` — `:124` and `:125`, the rows for `música` and for `MÚSICA` — expected: `MU_LO, MU_UP` both times — under ASCII-only lowering, or lowering only one side: one row.
- `C1` — `:128`, the rows for `???` — expected: `Q1, Q2` — with no full-scan fallback: `[]`; with SQLite's default space-only `trim`: `Q1` only.
- `C2` — `:136`-`:138`, the walk and `total` at limit 2 — expected: rows `L1, TRIM, NS, UPPER, MIX, SPLIT`, `total` 6 on pages 1-3 and on page 4 (empty) — under `total = len(page rows)`: `2, 2, 2` and `0`; under unpaged rows: the walk repeats.
- `C2` — `:140`-`:142`, the same with `include_nsfw=False` — expected: rows without `NS`, `total` 5 on every page and past the end — under a count that ignores the NSFW clause: 6.

**Self-check answers:**
1. Whole claim: C1 is asserted on both paths (`:121`-`:125` prefilter, `:128` full scan) and for exactness both ways (members present, near-misses absent, no duplicates via list equality). C2 is asserted on the first, middle, last and past-the-end page, with and without NSFW.
2. Absence only: no. Every exclusion is inside an equality that also requires the positive members.
3. Echoed literal: no. Every expected list is a hand-written literal; the rows come from `search_videos_by_tag`. Deleting the exact check turns `:121` red; deleting the fallback turns `:128` red; deleting the count statement turns `:137` red.
4. One value: no. Case is read on both sides (`música`, `MÚSICA`), trim on both paths, `total` on four pages and two NSFW settings.
5. The double: none. The child calls the real module on a real SQLite connection; `server` is a namespace holding that connection, as in `test_search.py`.
6. It collects: 2 tests collected (`--collect-only -q`).
7. Observed: every expected value matches `tests/tmp/probe_tag_sql.py` run against the drafted SQL on this fixture; two predictions the probe contradicted were rewritten (see Deviations).
8. Red: exit 1, both tests fail.
9. Right reason: `:121` fails on `[{'error': 'NotImplementedError()'}] == ['L1', 'MIX', ...]`, and `:136` on `[{'error': 'NotImplementedError()'}] == ['L1', 'TRIM', ...]`. Both are clause assertions failing because the function is the phase's unimplemented scaffold; the harness ran, the child built the database and reported per call.
10. Observed expected output: yes, each row's expected value is what the probe printed.

**Audit round 1:**
- `AUDIT: devsecops-test-shape-auditor — BLOCK: (1) single-value-pin at :127, tag_match_expression read only at "???", so an always-empty expression sends linux down the full scan and passes; (2) single-value-pin at :136/:140, rows were stored oldest first so rowid DESC equalled published_at DESC.` Predicted failure: line 121 and line 136, on the `NotImplementedError` entries.
- `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim at :111, no request carries padding, so trimming only the stored side passes.` Frozen ledger: 26 rows, UNCARRIED `C1e` (query-side trim), `D11` (docstring "FTS prefilter path" unasserted), `D12` (docstring "both trimmed" on the query side), `N2b` (name "after trim on both sides").

**Remediation 1:**
- `C1e` fixed — `:112` sends `"\t LINUX \n"`, asserted at `:127` equal to the six `linux` rows. Excludes trimming only the stored side (the padded request then matches nothing).
- `D12` fixed — by the same assertion.
- `N2b` fixed — by the same assertion.
- `D11` fixed — `:125` asserts `tag_match_expression("linux")` is non-empty, so `linux` is on the prefilter path. Excludes an always-empty expression.
- Shape Critical 1 — fixed by the `:125` assertion above, which reads the expression at a second input that must be non-empty.
- Shape Critical 2 — fixed: rows are inserted in the order `(rank * 5) % 17`. The probe showed rowid order for the `linux` matches is `NS, SPLIT, L1, UPPER, TRIM, MIX`, which matches neither direction of `published_at DESC`.
- Claim recommendation 5 taken — `:135` asserts the `???` full-scan `total` is 2 (`C2`). Excludes a count taken from the prefilter only.
- Claim recommendation 3 (empty tag, page 0, limit 0) not taken: the route refuses a blank tag at Phase 2 and parses `page`/`limit` as text search does; the data function's contract is a stripped non-empty tag.
- Claim recommendation 4 (`SearchIndexMissing`) not taken here: it is no clause; it is the planned inner unit, decided at 7.5.
- Claim recommendation 6 does not hold for this environment: the probe on `ENGINE_PY` (SQLite 3.53.4) printed `lower('MÚSICA') = 'música'`, as the 2026-10-04 measurement did. The assertion is the intended guard against a build that folds ASCII only (Gotchas, "SQLite `lower()` on the search connection").

**Self-check rows (round 2):**
- `C1` — `:123`, sorted rows for `linux` — expected: `L1, MIX, NS, SPLIT, TRIM, UPPER` — under the prefilter alone: adds `BAD, OBJ, PHRASE` (observed); without the CASE guard: an `OperationalError` entry; without stored-side trim: `TRIM` missing.
- `C1` — `:127`, sorted rows for `"\t LINUX \n"` — expected: the same six (observed) — trimming or lowering only the stored side: `[]`.
- `C1` — `:128`, rows for `linux mint` — expected: `PHRASE` — under the prefilter alone: `SPLIT, PHRASE` (observed).
- `C1` — `:130`, `:131`, rows for `música`, `MÚSICA` — expected: `MU_LO, MU_UP` — ASCII-only or one-sided lowering: one row.
- `C1` — `:134`, rows for `???` — expected: `Q1, Q2` — no fallback: `[]`; space-only trim: `Q1`.
- `C2` — `:135`, `???` total — expected: 2 — count from the prefilter only: 0.
- `C2` — `:143`-`:145`, walk and totals at limit 2 — expected: `L1, TRIM, NS, UPPER, MIX, SPLIT`; totals `6, 6, 6`, and `{rows: [], total: 6}` past the end — `total = len(page)`: `2, 2, 2`, `0`; ordering by rowid: `NS, SPLIT, L1, …`.
- `C2` — `:146`-`:149`, the same with `include_nsfw=False` — expected: no `NS`; totals `5, 5, 5`, and 5 past the end — count ignoring NSFW: 6.

**Self-check answers (round 2):** 1-5 as round 1, plus the padded request and the second expression input. 6: 2 tests collect. 7: every new expected value was printed by the probe (padded request, rowid order). 8: exit 1. 9: `:123` fails on `[{'error': 'NotImplementedError()'}] == ['L1', 'MIX', …]` and `:143` on `[{'error': 'NotImplementedError()'}] == ['L1', 'TRIM', …]`, both clause assertions against the scaffold; the supporting expression assertion was moved after `:123` so no supporting assertion fails first. 10: yes.

**Auditor verdicts:**
- `AUDIT: devsecops-test-shape-auditor — BLOCK: single-value-pin at :127 (expression read at one input) and at :136/:140 (rowid order coincided with the sort). Fixed: a second expression input (:125) and a scrambled insertion order (:60). Re-audit: PASS. Predicted failure: line 123 on the NotImplementedError entry for linux, and line 143 on three error dicts in walked.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim, query-side trim unasserted (C1e, D12, N2b) and the prefilter path unasserted (D11). Fixed: padded request at :112/:127 and the linux expression at :113/:125. Re-audit: PASS, every ledger row CARRIED.` Observation (non-blocking): nothing ties the `linux` call to the prefilter at runtime; C1 claims the rows on either path, not the routing.

**Changes:**
- `engine/server/api/server_config.py` — `SEARCH_MAX_TAG_LENGTH = 64` after `SEARCH_MAX_TOKEN_LENGTH` (used by Phase 2's handler).
- `engine/server/data/search.py` — `TAG_TRIM_SQL`, `TAG_MATCH_SQL`, `tag_match_expression` and `search_videos_by_tag` beside `lexical_candidates`, as drafted; a module-docstring paragraph on the exact-tag mode; `search_videos`'s docstring says "text search".
- `tests/config.json` — not edited: `dev_flow.md` Step 1 says a build never edits `test_groups`; the harvest maps `test_search_tags.py`.

**Inner unit:** `tests/tmp/test_search_tags_index_missing.py` — `search_videos_by_tag` raises `SearchIndexMissing` with no `videos_fts`, and returns a total of 6 on the same fixture with it. Reason: the checkpoint's fixture always builds the index, so it cannot reach that branch.

**Checkpoint outcome:** PASS — `tests/tmp/test_search_tags.py` 2 passed; the inner unit 1 passed; `tests/active/test_search.py` (text search, same module) re-run after the change.

#### Phase 2 — Engine tags on rows and tag route

**Kind:** code

**Intent:** `stable_video_row` in `handlers/similar.py` gives every row the Engine serves a `tags` list. `_handle_search` answers a lone, well-formed `tag` on `/api/v1/search/videos` from `search_videos_by_tag`, and refuses any other tag request with a 400.

**Clauses:**

- `C1` Every row that upnext, search and each feed mode serve carries `tags` equal to its stored `tags_json` as parsed by `tags_from_json`.
- `C2` `/api/v1/search/videos` answers a lone, non-blank `tag` of at most 64 characters with the videos carrying that tag in the resolved sort, and answers every other tag request with a 400.

**Checkpoint and seam:** Seam: the live Engine over HTTP, through the `engine` and `dataset` fixtures in `tests/active/test_similar.py` (rung 2). It follows `test_every_row_carries_the_channel_and_account_the_dataset_holds` (line 156) and its `identity_of` read in `conftest.py`, which gains a `tags_json` read beside it.

For C1:
- The route parametrisation is upnext and search plus every mode in the production `FEED_MODES`, read at run time as the existing `UNORDERED`/`ORDERED` readers do. Following sends a `follows` body.
- Every row on every route has `tags` as a list of strings equal to `tags_from_json` of that video's stored `tags_json`.

For C2, the positive half: a stored tag is requested as `?tag=<upper-cased>`.
- Every row carries the tag after trimming and case-folding.
- `sort` echoes `published_at` with no sort given and with `sort=relevance`.
- `sort=views` returns the rows in views order.
- `vectorSearch` is false.
- With nsfw off, `total` equals a direct `COUNT` on `whitelist.db`.
- Text search's `total` stays at or below 200.

For C2, the negative half: each of these gets a 400 whose JSON body has an `error`: `q`+`tag`, `tag=%20`, a 65-character tag, no parameter, `?tag=` and `sort=bogus` with a tag.

The existing route tests have to stay green.

**Files:** engine/server/api/handlers/similar.py (EDITED), engine/server/api/router.py (EDITED), tests/active/test_similar.py (EDITED), tests/active/conftest.py (EDITED), tests/config.json (EDITED)

**Checkpoint file:** `tests/tmp/test_similar_tags.py`. It imports the `engine`, `dataset`, `trending_seed` and `shared_trending_before` fixtures from `tests/active/conftest.py` by path, as earlier builds' `tests/tmp` files did. The harvest decides whether its cases fold into `test_similar.py`; `conftest.py` and `test_similar.py` are therefore not edited in this phase.

**Deviations from the Step 6 checkpoint text, from observation:**
- "Text search's `total` stays at or below 200" is false today: `q=music` reported `total` 396 on the first run, because the fused set takes up to `SEARCH_CANDIDATE_POOL` (200) from each half. The guard is now `text total ≤ 2 × SEARCH_CANDIDATE_POOL < tag total` for the same word (read from `server_config` at collection), as a supporting assertion inside the tag test, since a separate test would be green before the phase.
- The stored `tags_json` comparison does not call `tags_from_json`: the expected list is the stdlib `json.loads` of the stored value (rows whose stored value is a JSON list of strings), `[]` for NULL, and a list of strings otherwise. Calling the production parser would make the expectation tautological.
- "The direct `COUNT` on `whitelist.db`" is a Python count (`LIKE` narrowing, then `json.loads` and `strip(" \t\r\n").lower()`), not SQL mirroring the Engine's. The probe `tests/tmp/probe_54_p2_counts.py` showed it equals Phase 1's `search_videos_by_tag` total on the dev dataset: `linux` 6236, `music` 4515.
- Each 400 is paired with the request one defect away answering 200, because four of the six refusals already answer 400 today ("Missing query parameter q"); the pair makes each case red before the phase and pins the boundary (64 vs 65 characters, padded vs blank).

**Self-check rows:**
- `C1` — `:101`, a row whose stored `tags_json` is NULL — expected: `tags == []` — with no `tags` key (today): `None`; observed red on `upnext`, `recent`, `following`.
- `C1` — `:104`, a row whose stored value is a JSON list of strings — expected: `tags` equal to that list, same order — with no `tags` key: `None` (observed red on `search`, `recommendations`, `trending`, `random`, `popular`); with the raw string passed through: a `str`; sorted or deduplicated: a different list where the uploader's order is unsorted.
- `C1` — `:108`, at least one row per route with a non-empty stored list — expected: true — under `tags = []` everywhere: false (and `:104` red).
- `C2` — `:138`/`:141`, `?tag=LINUX` and `?tag=MUSIC` — expected: 200, every row carrying the tag — today: 400 `Missing query parameter q` (observed).
- `C2` — `:143`/`:144`, default order and echo — expected: `published_at` descending, `sort` `published_at` — echoing the raw `relevance` default: `relevance`.
- `C2` — `:145`, `vectorSearch` — expected: false — with the text-mode expression: true whenever the encoder is up.
- `C2` — `:146`, `total` — expected: the Python count (6236, 4515 observed) — a page length: 50; the text pool: ≤ 400.
- `C2` — `:151`/`:152`, `sort=relevance` — expected: `published_at`, the same rows — passing relevance through: an echo of `relevance`.
- `C2` — `:155`/`:158`, `sort=views` — expected: `views` echoed and views descending — ignoring sort: the newest page, which `:160` shows is not in views order (probe: `views_sorted: false` for both tags).
- `C2` — `:173`, the request one defect away — expected: 200 with a `rows` list — today: 400 (observed on all six); with the 64 check before trimming or as `>= 64`: 400 on the padded 64-character tag.
- `C2` — `:175`/`:176`, the refused request — expected: 400 with a non-empty JSON `error` — accepting `q`+`tag` (today: 200 on `q`), or accepting `sort=bogus`, a blank or a 65-character tag in tag mode: 200.

**Self-check answers:**
1. Whole claim: C1 over every route the clause names, with the route set read from production `FEED_MODES` at collection; C2's positive half (rows, sort, echo, `vectorSearch`, `total`) and negative half (six refusals) each asserted.
2. Absence only: no. Every 400 is preceded in the same test by the 200 its neighbour gets; `:108` guards the empty-list case.
3. Echoed literal: no. Expected tags come from `whitelist.db` via the stdlib; the total from a Python count; nothing the test sends comes back as the expectation except the tag, which is sent upper-cased and checked case-folded on stored tags.
4. One value: no. Two tags with different totals; two sorts beside the default; refusal on both sides of each boundary.
5. The double: none. The live Engine and the read-only dataset.
6. It collects: 16 items.
7. Observed: the totals, the views order and the following channel were read by `tests/tmp/probe_54_p2_counts.py`; the 396 text total by the first run, which rewrote that premise.
8. Red: exit 1, 16 failed.
9. Right reason: C1 at `:101`/`:104` on rows with no `tags` key (e.g. `('search', 'e9ab482d-…', '["Digitale Kirche",…]')`); C2 at `:138` on `{'error': 'Missing query parameter q'}`; refusals at `:173` on `('tag=linux', 400, {'error': 'Missing query parameter q'})`. All are clause assertions against the unbuilt route.
10. Observed expected output: yes; the one premise the run contradicted (text total ≤ 200) was rewritten.

**Audit round 1:**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 104 (or 101 on a NULL-stored first row) on rows with no tags; line 138 on the 400 "Missing query parameter q"; line 173 on each accepted control.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK.` Frozen ledger: 42 rows; UNCARRIED `C1f` (stored values other than NULL or a clean string list checked only for type), `C2d` (default page checked for date order, not for being the newest matches), `C2g` (views page checked for order, not for being the most-viewed matches), `C2o` (two `tag` parameters not refused), `D16` (control "answers 200 with rows" accepted `[]`).

**Remediation 1:**
- `C1f` fixed — `:107`-`:109` compare `tags` for equality with `[]` for empty, malformed or non-list storage and with the string members of a mixed list. Excludes `[]` for `["a", 1]` and `["{bad"]` for malformed text. Recommendation 1 (the live dataset may serve no such row) is recorded, not fixable at this seam: the branch is covered where it occurs.
- `C2d` fixed — `:162` requires the default page to be the 50 newest of all Python-found matches, in order, less rows moderation removed (`_is_ordered_subset`). Excludes a date-sorted page of some other subset.
- `C2g` fixed — `:178` requires the views page to be the 50 most-viewed matches in order; `:179` (control) shows that page is not drawn from the newest page. Excludes the newest page re-sorted by views.
- `C2o` fixed — case `tag=linux&tag=music` (`:184`), refused against `tag=linux`. Excludes reading `params["tag"][0]`. This needs a two-tag refusal the draft handler lacks; it lands at 7.5 within C2 ("lone").
- `D16` fixed — `:194` requires non-empty rows on every control with matches and empty rows on the 64-character one. Excludes an untrimmed lookup answering the padded tag with nothing.
- Probe `tests/tmp/probe_54_p2_counts.py` (Phase 1's function on the dev dataset): for both tags the Engine total equals the Python count, the newest and views pages equal `_leading(...)` exactly, and the views page is not a subset of the newest page.

**Self-check rows (round 2):** as round 1, with these changed or added:
- `C1` — `:109`, other stored values — expected: `[]`, or the string members of a mixed list — a type-only check would accept `["{bad"]`.
- `C2` — `:162`, default page — expected: an ordered subset of the 50 newest matches (observed exact on Phase 1) — a date-sorted other subset: not a subset.
- `C2` — `:178`, views page — expected: an ordered subset of the 50 most-viewed matches (observed exact) — the newest page re-sorted: not a subset, which `:179` arms.
- `C2` — `:184`/`:196`, two tags — expected: 400 — `params["tag"][0]`: 200.
- `C2` — `:194`, control rows — expected: non-empty except for the 64-character tag — an untrimmed lookup on `tag=%20linux%20`: `[]`.

**Self-check answers (round 2):** 1-5 as round 1. 6: 17 items collect. 7: every new expected value was observed by the probe. 8: exit 1, 17 failed. 9: the same reasons as round 1 (`:101`/`:104` no `tags`; `:156` and `:193` on `{'error': 'Missing query parameter q'}`), all clause assertions. 10: yes.

**Auditor verdicts:**
- `AUDIT: devsecops-test-shape-auditor — PASS (rounds 1 and 2). Predicted failure: per-row equality at line 101, 104 or 109 on rows with no tags; line 156 on the 400 "Missing query parameter q"; line 193 on the accepted control.` Recommendation (non-blocking, recorded): `:108` restates `tags_from_json`'s contract for odd stored values; kept, because C1 names that parse as the expectation and the gated code is each route attaching `tags`.
- `AUDIT: devsecops-test-claim-auditor — BLOCK: C1f, C2d, C2g, C2o, D16 uncarried. Fixed: see Remediation 1. Re-audit: PASS, every ledger row CARRIED.` Observations (non-blocking, recorded for Step 8): `_is_ordered_subset` bounds no shortfall below the 10-row floor; the odd-stored-value branch runs only if the served pages hold such a row.

**Changes:**
- `engine/server/api/handlers/similar.py`:
  - imports `search_videos_by_tag`, `SEARCH_MAX_TAG_LENGTH` and `handlers.video.tags_from_json`;
  - `stable_video_row` adds `tags`;
  - `_handle_search` gains the tag branch as drafted, plus a 400 for more than one `tag` parameter ("Only one tag parameter is allowed"), which the round-1 claim audit (`C2o`) showed "lone" needs. In tag mode relevance resolves to `published_at` and `vectorSearch` is false;
  - the module docstring names both search modes.
- `engine/server/api/router.py` — the search route's docstring line names `q` and `tag`.

**First run after implementing:** 15 passed, 2 failed, both at the supporting floor (`:110` then) "no row carried a non-empty stored tag list", on `mode=recent` and `mode=following`. Each row's own `tags` check passed. Cause, read from `whitelist.db` (`.scratch/probe_recent_tags.py`): the newest 2000+ videos have NULL `tags_json`, the dataset build's tags-stage backlog. The followed channel `play.cotv.org.br/7` likewise has untagged newest videos.

**Test alteration after gating (operator-approved 2026-10-06, AskUser "Fix both premises"):** `_followed_channel` now picks a channel whose newest embedded video is tagged. The non-empty floor skips `mode=recent` only (`NO_TAGGED_ROW_ROUTES`), with the reason in a comment. The docstring is narrowed to match. Re-armed by mutation: with `stable["tags"] = []`, 7 routes fail (Following included) and only Recent passes. Restored with `sleep 1; touch`, then 17 passed.
- `AUDIT: devsecops-test-shape-auditor — round 3 PASS.` Recommendation (deferred): Recent's floor is off unconditionally; give the skip an expiry once the tags stage catches up.
- `AUDIT: devsecops-test-claim-auditor — round 3 PASS, C1a-C1e CARRIED` (Recent is covered on the shared ordered path through trending and popular). Observation (deferred): arm Recent's floor whenever a served Recent row has a non-NULL `tags_json`.

**Checkpoint outcome:** PASS — `tests/tmp/test_similar_tags.py` 17 passed. No inner unit test.

**Product note for the operator:** because of the same backlog, the Recent feed's first pages will show no tag chips until the tags stage fills `tags_json` for the newest videos.

#### Phase 3 — Gateway forwards tag search

**Kind:** code

**Intent:** The read gateway in `client/backend/server.py` forwards `tag` on `/api/v1/search/videos`, so a profile's tag search reaches the Engine and comes back with that profile's blocks applied.

**Clauses:**

- `C1` A tag search sent through the read gateway returns the videos carrying the tag, minus those of a channel the profile blocks.

**Checkpoint and seam:** Seam: the read gateway, through the `engine_client` fixture in `tests/active/test_blocks.py` (rung 2). It follows `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page`, which already runs over the search surface `SEARCH`.

A tag is picked that is carried by at least two channels' videos, read from the dataset at run time.
- A profile that blocks one of those channels sends `GET /api/v1/search/videos?tag=<tag>` through the gateway. It gets 200 with rows that all carry the tag (taken from each row's `tags`) and none from the blocked channel.
- A second profile without the block sends the same request and gets the blocked channel's video. This proves that `tag` was forwarded and that the block, not the query, removed the row.
- Without `tag` in the allowlist, the gateway would drop it and the Engine would answer 400, so the 200 with tagged rows is the forwarding assertion.

**Files:** client/backend/server.py (EDITED), tests/active/test_blocks.py (EDITED)

**Checkpoint file:** `tests/tmp/test_blocks_tags.py` (the `engine_client` and `engine` fixtures imported from `tests/active/conftest.py` by path). `test_blocks.py` is not edited in this phase; the harvest decides where the case lands.

**Deviation from the Step 6 text, from observation:** the gateway does not drop an unknown parameter, it answers `400 {'error': 'Unknown query parameter: tag'}` (first run). The forwarding assertion is the same 200, with the reason corrected. The tag is `linux`; `.scratch/probe_linux_channels.py` showed its newest 50 matches span 29 channels, the first holding 7.

**Self-check rows:**
- `C1` — `test_blocks_tags.py:28`, the gateway's status for a tag search — expected: 200 — without `tag` in the allowlist: 400 `Unknown query parameter: tag` (observed).
- `C1` — `:45`, keyless rows all carry the tag — expected: true — under a gateway forwarding a different parameter, or a `_filter_payload` that drops `tags`: false.
- `C1` — `:57`, the blocker's rows — expected: the keyless rows less the first channel's 7, in order — under a gateway that skips blocks on this route: the keyless rows; under an over-broad filter: fewer rows.
- `C1` — `:58`, the blocked channel is absent for the blocker — expected: absent — skipping blocks: present.
- `C1` — `:61`, the bystander's rows all carry the tag — expected: true — under `tags` dropped on the filtered path: false.

**Self-check answers:**
1. Whole claim: "returns the videos carrying the tag" at `:45`/`:61`; "minus those of a channel the profile blocks" at `:57`/`:58`, with the bystander control at `:60`.
2. Absence only: no. `:58` pairs with `:57`'s exact list and `:60`'s presence control.
3. Echoed literal: no. Every expectation is read from the keyless response.
4. One value: two profiles with different blocks; the blocker's list is compared row for row.
5. The double: none. A real Client gateway in-process (`engine_client`) over the session Engine.
6. It collects: 1 test.
7. Observed: the 400 body by the run; the channel spread by the probe.
8. Red: exit 1.
9. Right reason: `:28` in `_tag_rows`, called from `:45`, fails on `{'error': 'Unknown query parameter: tag'}`, `assert 400 == 200`: the gateway allowlist lacks `tag`, which is this phase.
10. Observed expected output: yes.

**Audit round 1:**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 48 via line 31, 400 against 200, because the allowlist at server.py:104 lacks tag.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim, the test checks every returned row is tagged but not that the page is the tagged set.` Frozen ledger: 17 rows, with `C1c` ("the videos carrying the tag", the set) and `N2` (name "returns the tagged videos") UNCARRIED.

**Remediation 1:**
- `C1c` fixed — `:74` requires the keyless page to be the 50 newest `linux` videos found in Python over `whitelist.db` (`_newest_tagged`), in order, less at most 5 removed by moderation. Excludes a truncated subset, a match on one tag position only, and a search that drops instances. Probe `tests/tmp/probe_54_p3_page.py`: the session Engine serves all 50, equal to the reference.
- `N2` fixed — by the same assertion.
- Recommendation 1 taken — `:86` makes the bystander's page exactly the keyless rows less the bystander's own blocked channel.
- Recommendations 2-4 (other tag values, 401/502 paths, the name) not taken: the edges of the tag parameter are Phase 2's C2. The gateway's key and Engine-failure paths are unchanged by this phase and are covered by `test_blocks.py`/`test_server.py`.

**Self-check rows (round 2):** as round 1, plus:
- `C1` — `:74`, the keyless page — expected: the 50 newest matches in order (observed) — a truncated or partial search: fewer than 45 rows or out of order.
- `C1` — `:86`, the bystander page — expected: the keyless rows less the unrelated channel — a block applied to every profile: the first channel missing as well.

**Self-check answers (round 2):** 1-5 as round 1. 6: 1 test. 7: the page size and order observed by the probe. 8: exit 1. 9: `:51` in `_tag_rows`, called from `:68`, `{'error': 'Unknown query parameter: tag'}`: the allowlist. 10: yes.

**Auditor verdicts:**
- `AUDIT: devsecops-test-shape-auditor — PASS (rounds 1 and 2). Predicted failure: line 68 via line 51, 400 "Unknown query parameter: tag" against 200.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: C1c and N2 uncarried (page not shown to be the tagged set). Fixed: :74 against the independent newest-tagged set. Re-audit: PASS, every ledger row CARRIED.` Observation (deferred): `:74` allows up to five missing newest rows without showing they were moderated.

**Changes:**
- `client/backend/server.py` — `PROXY_ALLOWED_QUERY_PARAMS["/api/v1/search/videos"]` gains `"tag"`.

**Checkpoint outcome:** PASS — `tests/tmp/test_blocks_tags.py` 1 passed. No inner unit test.

#### Phase 4 — Linked tag chips and one-line fit

**Kind:** code

**Intent:** Every tag chip shown on the feed, search, up-next and video pages is an `a.tag-chip` linking to `/search.html?tag=…` outside any video link, and `observeTagRows` fits each card's chip row to one line, hiding chips from the end behind a `+N` marker.

**Clauses:**

- `C1` Every tag chip shown on feed, search, up-next cards and on the video page is a link to its `tagSearchUrl` and is never inside a video link.
- `C2` A card's chip row hides chips from the end until the rest and a `+N` marker fit its width, and it re-fits when that width changes.

**Checkpoint and seam:** Seam: `components/video-card.ts`, bundled by esbuild and run in node (rung 1). It follows `tests/active/test_frontend_video_card.py` and its `bundle` fixture, which has `--define:import.meta.env.DEV=false`; a second bundle uses `DEV=true`. The page-level placement extends the existing node harnesses `test_frontend_video_page.py` and `test_frontend_video_page_similars.py`.

For C1:
- `tagSearchUrl("a b&c")` gives `/search.html?tag=a+b%26c`, and `api` is present only in the DEV bundle.
- `tagSearchUrl` returns null for a blank tag and for a 65-code-point tag.
- `renderTagChips` returns `""` for undefined, null, `[]` and a blank-only list.
- A `<script>` tag arrives escaped, and there is no `style=`.
- Chips come in the uploader's order, and each `href` equals `tagSearchUrl` of its tag.
- An unsearchable tag gets no chip on a card.
- The `+N` marker is present and `hidden`.
- In `renderVideoCard`, the `.card-tags` row comes after the closing `</a>` of `video-link`, with no chip inside the link.
- In the similars harness, the `.card-tags` row is a sibling after `a.similar-card-link` inside `div.similar-card-item`, which still carries `data-video-key`. Both regexes are retargeted to the div.
- In the video-page harness, the tags are `a.tag-chip` elements with `href=/search.html?tag=…` and no `api` when DEV is false. A blank stored tag is a `span.tag-chip`.

For C2:
- `ResizeObserver` and `MutationObserver` are stubbed, along with `scrollWidth` and `clientWidth`.
- A row of five chips with room for two shows two chips and the marker reading `+3`, with `aria-label="3 more tags"`.
- Widening the row re-fits it to more visible chips with a smaller `+N`.
- A row where everything fits keeps the marker hidden.

**Files:** client/frontend/src/components/video-card.ts (EDITED), client/frontend/src/types/videos.ts (EDITED), client/frontend/src/base.css (EDITED), client/frontend/src/video.css (EDITED), client/frontend/src/videos.css (EDITED), client/frontend/src/pages/videos/index.ts (EDITED), client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_card.py (EDITED), tests/active/test_frontend_video_page.py (EDITED), tests/active/test_frontend_video_page_similars.py (EDITED), tests/config.json (EDITED)

**Checkpoint file:** `tests/tmp/test_frontend_tag_chips.py`, 10 tests, authored by a `dev-flow-builder` subagent from the Step 6 seam. It bundles `video-card.ts` twice (DEV false and true) and the video page once, and reports a missing export as data, so each red is on a clause assertion. Its page runners are cut-down copies of the two active video-page harnesses. Its fit runner is the active suite's recording DOM plus stubbed `MutationObserver`/`ResizeObserver` and a stub layout (row = card width, chip 50px, marker 30px, hidden = 0). Observation: the draft's code fences were applied to a temporary copy of `client/frontend/src`; all 10 pass there, and 14 single-point wrong variants each turn at least one clause line red (`tests/tmp/probe_54_p4_vs_draft.py`).

**Not asserted at this seam (recorded):** `applySimilarStatsToDom` inside the new up-next div (the copied harness's `querySelector` returns null). The page wiring was added at remediation 1 (below). The edits to the three active tests named in Files are implementation-step work, made at 7.5 where those tests break.

**Self-check rows** (full table in the builder's report; one row per clause line):
- `C1` — `:486`-`:492`, `tagSearchUrl("a b&c")` in the prod and dev bundles — expected: `/search.html?tag=a+b%26c`, `api` only in dev with an apiParam — missing export: `{error}`; `encodeURIComponent`: `a%20b%26c`; api always: `&api=…`.
- `C1` — `:499`-`:505`, the bounds — expected: a link at 64 code points (including 64 emoji), null for blank and 65 — a `.length` limit: null for 64 emoji; no trim: `?tag=+++`.
- `C1` — `:512`-`:538`, `renderTagChips` — expected: `""` for none or blank-only; `<a>` chips in the uploader's order with hrefs equal to `tagSearchUrl`, unsearchable tags dropped, one hidden marker — sorted, untrimmed or unlimited variants: wrong list (observed by the probe); marker shown: `[False]`.
- `C1` — `:548`-`:552`, escaping — expected: `<script>` and a quote breakout read back as text, no `style` attribute — unescaped: a script element or attribute.
- `C1` — `:564`-`:572`, feed card — expected: chips with no `<a>` ancestor, after `a.video-link` — today: `[]` (observed); row inside the link: `[["video-link"],…]`.
- `C1` — `:587`-`:598`, up-next — expected: keyed `div` holding `a.similar-card-link` then `div.card-tags`, chips outside the link with no `api` — today: `("a", True)` (observed).
- `C1` — `:612`-`:614`, video page — expected: `A` with `/search.html?tag=…` for searchable tags, `SPAN` for blank and 65 — today: `("SPAN", None)` (observed).
- `C2` — `:631`-`:639`, five chips — expected: `[t1,t2]` and `+3`/"3 more tags" at 160px, `[t1..t3]` and `+2` at 210px, all five with the marker hidden at 300px, back to `+3` at 160px — hide from the start, a marker placed after the loop (`+2`), or no unhide before a re-fit: each differs (observed).
- `C2` — `:648`-`:651`, a fitting row beside an overflowing one — expected: overflowing marker shown, fitting row all chips with the marker hidden — always showing the marker, or always hiding a chip: differs.

**Self-check answers:**
1. Whole claim: C1 is asserted on each surface it names (feed via `renderVideoCard`, up-next, video page; search shares `renderVideoCard`), for both link and placement. C2 is asserted for hiding from the end, the marker, and re-fit on widen and narrow.
2. Absence only: no. Every "not inside a link" assertion follows a positive count of chips; the hidden-marker assertion at `:651` sits beside the shown one at `:648`.
3. Echoed literal: no. Hrefs are parsed with `urllib.parse`; texts are read from rendered markup or the recording DOM.
4. One value: no. Two bundles, several tags, three widths plus a return to the first.
5. The double: only browser APIs (`MutationObserver`, `ResizeObserver`, layout widths) and the page's `fetch`. No project module is stood in for.
6. It collects: 10.
7. Observed: every expected value matched a run of the draft on a temporary copy; the one disagreement was in the builder's own copy of the draft and became a named wrong variant.
8. Red: exit 1, 10 failed.
9. Right reason: each test's first failure is a clause line (`:486`, `:499`, `:512`, `:526`, `:548`, `:564`, `:587`, `:612`, `:631`, `:648`), on a missing export or today's markup (`('a', True)`, `('SPAN', None)`). None is a control.
10. Observed expected output: yes.

**Audit round 1:**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: the first new-behaviour assertion of each test (:486, :499, :512, :526, :548, :564, :587, :612, :631, :648).`
- `AUDIT: devsecops-test-claim-auditor — BLOCK.` Frozen ledger: 47 rows. UNCARRIED:
  - `C2e`: an appended card's row is fitted. The only appended card fits unfitted.
  - `C2f`: the pages wire the fit. The runner called `observeTagRows` itself.
  - `D21`: the same gap as `C2e`.
  - `N5`: the marker ends the row; its position was never read.

  Recommendation 2: exact-boundary widths and an all-hidden width.

**Remediation 1** (by the builder; nothing under `client/`, `engine/` or `tests/active` edited):
- `C2e`, `D21` fixed — an appended five-chip card at 160px must read `[t1,t2]` and `+3` (`:710`). Excludes a fit that reaches only first-render rows: the `first-batch-only` variant is red there. N11 is still carried at `:712`-`:713`.
- `C2f` fixed — `PAGE_FIT_RUNNER` drives the real `pages/videos/index.ts` (`#video-cards`), `pages/search/index.ts` at `?q=x` (`#search-results`) and the video page (`#similar-videos`) with recording observers and a stubbed `fetch`. For each page, the card's row reads `[t1,t2]`/`+3` at 160px (`:738`) and all five with the marker hidden at 300px (`:740`). Excludes a page that never calls `observeTagRows`: the `feed-not-wired`, `search-not-wired` and `upnext-not-wired` variants are each red on their own page only. The search wiring lives in `pages/search/index.ts`, which the Phase 4 Files list does not name; that is recorded as an inventory gap at 7.5.
- `N5` fixed — `:592` reads the row's children as four chips then the marker. The `marker-first` variant is red.
- Recommendation 2 taken (`:722`-`:726`). Observed on the draft:
  - at 130px, `t1,t2` and `+3`;
  - at 180px, `t1..t3` and `+2`;
  - at 250px, all five with the marker hidden;
  - at 70px, none and `+5`.
  
  A fit that sums widths with `<` is red at the exact widths (`sum-lt`); one that always keeps a chip is red at 70 (`keep-one`).
- Draft probe re-run: the draft passes all 14; every old and new variant is red on a clause line.

**Self-check (round 2):** 14 tests collect; exit 1, 14 failed. First failures are `:538`, `:551`, `:564`, `:578`, `:602`, `:618`, `:641`, `:666`, `:691`, `:708`, `:722`, and `:738` for each of the three pages, all clause lines, none a control. Questions 2-5 and 7 are unchanged: the page runner stubs only browser APIs and `fetch`, and each new expected value was observed against the draft.

**Auditor verdicts:**
- `AUDIT: devsecops-test-shape-auditor — PASS (rounds 1 and 2). Predicted failure: each test's first new-behaviour assertion (:538 … :738), on a missing export or today's markup.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: C2e, C2f, D21, N5 uncarried. Fixed: see Remediation 1. Re-audit: PASS, every ledger row CARRIED.` Observations, deferred: D21's prose was narrowed, with the appended-row claim moved to the LATE card at `:710`. The feed and search pages' own markup is not checked for chip `href` and ancestry; `renderVideoCard`'s output is checked instead.

**Changes** (implemented by the builder from the draft without deviation):
- `components/video-card.ts`:
  - `TAG_MAX_LENGTH`, `tagSearchUrl` (trimmed, ≤ 64 code points, `api` only in DEV) and `renderTagChips` (escaped `a.tag-chip` links, then a hidden `span.tag-more`);
  - the private `fitTagRow` and `observeTagRows` (one shared `ResizeObserver`, one `MutationObserver` per container, re-fit only on a width change, a no-op without the observers);
  - `renderVideoCard` places the row after `</a>`, before the card actions.
- `types/videos.ts` — `VideoRow.tags?: string[] | null`; the `SearchPayload` docstring covers the tag-mode `total`.
- `base.css` — `.tag-chip`, `a.tag-chip:hover`, `.card-tags`, `.card-tags > *`, `.tag-more`.
- `video.css` — the old `.tag-chip` is removed; `.similar-card-item` loses its link styling; `.similar-card-link` is new.
- `videos.css` — `.video-card > .card-tags` padding.
- `pages/videos/index.ts` — `observeTagRows(cards)`.
- `pages/video-page/index.ts`:
  - searchable tags become `a.tag-chip` links; unsearchable ones stay `span.tag-chip`;
  - `renderSimilarCard` returns `div.similar-card-item` (still keyed), holding `a.similar-card-link` then the chip row;
  - `observeTagRows(similarCards)`.
- `pages/search/index.ts` — **inventory gap** (not in this phase's Files): the import plus `observeTagRows(results)`, which `C2f` requires.
- `tests/active/test_frontend_video_page_similars.py` — as the plan approved: both regexes now match `<div … similar-card-item …>`, and the docstring says "cards" for "anchors". Nothing else changed. Before the fix it failed `len(cards) == SHOWN` (0 vs 8) on the approved markup change.
- Not edited: `tests/active/test_frontend_video_card.py` and `test_frontend_video_page.py` stayed green, and the checkpoint covers the cases the plan suggested adding to them. `tests/config.json` is left to the harvest (Step 1: a build never edits `test_groups`).

**Known limitation carried from Step 4's third pass:** the chip's blank check uses JS `trim()`, which leaves U+0085 and `\x1c`-`\x1f`, both of which Python's `strip()` removes. A tag made only of those characters would render a chip whose search the gateway strips to nothing. No such stored tag has been measured.

**Checkpoint outcome:** PASS — `tests/tmp/test_frontend_tag_chips.py` 14 passed. Each run alone, all green: `test_frontend_video_card` 1, `test_frontend_video_page` 18, `test_frontend_video_page_similars` 2, `test_frontend_videos_page` 7, `test_frontend_translate` 63, `test_frontend_reactions` 7, `test_frontend_base_css` 1, `test_frontend_blocks` 2, `test_frontend_upnext_pager` 4. No inner unit test.

#### Phase 5 — Search page tag mode

**Kind:** code

**Intent:** `pages/search/index.ts` runs a URL that carries a `tag` and no `q` in tag mode, through `fetchSearchResults` sending only `tag`, and a `q`, whether submitted from the box or present in the URL, always replaces tag mode with a text search.

**Clauses:**

- `C1` A load, a sort change or a back-navigation into a tag URL shows that tag's results in tag mode, requested with `tag` and without `q`.
- `C2` Whenever a `q` is present, whether submitted from the box or in the URL, the page runs a text search and `tag` leaves both the request and the URL.

**Checkpoint and seam:** Seam: `pages/search/index.ts`, bundled with `data/search.ts` and run in node on recording elements with a stub `fetch` and a recording `history` (`pushState`/`replaceState`) (rung 1/2). This goes in a NEW `tests/active/test_frontend_search_page.py`, following `HOME_RUNNER` and its element factory in `tests/active/test_frontend_videos_page.py`. It replaces the draft's manual check, which the operator approved.

For C1, each of three entries into tag mode is checked:
- the initial load of `?tag=Linux`
- a sort change to `views` while in tag mode
- a `popstate` into `?tag=Linux&sort=views` from a text-search entry

For each entry:
- The request URL carries `tag=Linux` and no `q`.
- `#search-tag` is shown and its text names the tag.
- `document.title` is `Linux - Tag - Search - PeerTube - Browser`.
- The relevance option is both `hidden` and `disabled`.
- The pushed URL leaves `sort` out at `published_at` and writes `sort=views` after the change.
- The status line reads `Showing X of Y videos tagged "Linux".`. An empty answer reads `No videos tagged "Linux".`.
- A `popstate` to a bare `/search.html` pushes no history entry.

For C2:
- A box submit from tag mode sends a request carrying `q` and no `tag`, pushes a URL with no `tag`, re-enables and shows the relevance option, and hides the heading.
- A load of `?q=music&tag=Linux` sends `q=music` with no `tag`, and calls `replaceState` with a URL that has no `tag`.

After `dist` is rebuilt, `test_frontend_base_css.py` and `test_frontend_dist.py` pass unchanged.

**Files:** client/frontend/src/pages/search/index.ts (EDITED), client/frontend/src/data/search.ts (EDITED), client/frontend/src/types/videos.ts (EDITED), client/frontend/search.html (EDITED), client/frontend/src/search.css (EDITED), client/frontend/dist/ (REBUILT), tests/active/test_frontend_search_page.py (NEW), tests/config.json (EDITED)

**Checkpoint file:** `tests/tmp/test_frontend_search_page.py`, 5 tests, authored by a `dev-flow-builder` subagent. It bundles `pages/search/index.ts` with `data/search.ts` (production build) and runs them in node on a recording DOM parsed from the real `search.html` body. `fetch` answers from a script, `history` is recording, and `popstate` steps fire the window's listeners. Observation: the draft applied to a temporary copy of `client/frontend` passes all 5, and 14 wrong variants each turn a clause line red (`tests/tmp/probe_54_p5_draft.py`).

**Deviations from the Step 6 text:**
- A load pushes nothing under the draft, so "leaves `sort` out at `published_at`" is asserted on a sort-change push. The sort test loads at `popularity`, changes to `views`, then to `published_at`.
- The empty-answer status is asserted once, on the sort-change entry.
- The heading is asserted as shown and naming the tag, not by its exact wording.
- Added after the builder's report (before audit): `:247` asserts the page found every element in the real `search.html` (`missing == []`). The harness creates an absent id on demand, so without this line a build that never adds `#search-tag` would pass here and throw in production.

**Self-check rows** (full table in the builder's report):
- `C1` — `:239`, load request — expected: `tag=Linux`, no `q`, `sort=published_at` — today: no request (observed); `q=` beside the tag: `q` present; a relevance default: `sort=relevance`.
- `C1` — `:240`-`:247`, load state — expected: heading shown naming Linux, the tag title, relevance hidden and disabled, `Showing 2 of 5 videos tagged "Linux".`, nothing missing from `search.html` — today: the text title and `missing == ['search-tag']`; relevance only hidden: `disabled: False`.
- `C1` — `:255`-`:268`, sort change — expected: tag requests at `views` then `published_at`, a push carrying `sort=views`, then one without `sort`; `No videos tagged "Linux".` on the empty answer — `sort` left out only at relevance: `sort=published_at` pushed.
- `C1` — `:279`-`:289`, popstate — expected: a tag request at `views`, no history call into the tag URL, and none to bare `/search.html` — `showIdle()` pushing: one push.
- `C2` — `:301`-`:306`, box submit from tag mode — expected: `q=music` with no `tag`, one push without `tag`, relevance shown and enabled, heading hidden — the tag kept: `?q=music&tag=Linux`.
- `C2` — `:315`-`:318`, `?q=music&tag=Linux` — expected: `q=music` with no `tag`, exactly one `replace` without `tag` — not rewritten: `[]`; pushed: `push`.

**Self-check answers:**
1. Whole claim: C1's three entries (load, sort change, back-navigation) each assert the request and the tag-mode state. C2's two sources of `q` (box, URL) each assert the request and the URL.
2. Absence only: no. Each "no `q`" is in the same tuple as `tag=Linux`, and each "no `tag`" sits with `q=music`. The "no history" assertions follow a positive request or idle line.
3. Echoed literal: no. Every expectation is read from the page's requests, history calls and DOM.
4. One value: three entries, two sorts plus the default, two `q` sources.
5. The double: only `fetch`, `history`/`location`, the DOM and timers. No project module is stood in for.
6. It collects: 5.
7. Observed: every literal matched the draft's run on a temporary copy.
8. Red: exit 1, 5 failed.
9. Right reason: first failures `:239`, `:255`, `:279`, `:298` (C1, no tag request today) and `:317` (C2, no `replaceState`). All are clause lines; the one control at `:277` passes.
10. Observed expected output: yes.

**Audit round 1:**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 239 (no tag request today), the same at 255, 279, 298, and 317 for test 5.` Recommendation: one tag value throughout; add a second.
- `AUDIT: devsecops-test-claim-auditor — BLOCK.` Frozen ledger: 46 rows. UNCARRIED:
  - `C1g`, "shows that tag's results": the grid was never read.
  - `C2g`, "whenever a `q` is in the URL": only a load carried `q`+`tag`, never a back-navigation.
  - `D2`: the same gap as `C2g`.

**Remediation 1** (by the builder):
- `C1g` fixed — the runner records the keyed cards in `#search-results` per phase, and every answer has distinct ids. The grid holds exactly that phase's rows at `:244`, `:261`/`:265`, `:291`, `:341`, `:345` and `:354`, and is empty after the empty answer at `:277`. Excludes a tag branch that sets the status without rendering, and a popstate that keeps the old grid.
- `C2g` and `D2` fixed — a new test (`:333`) goes from tag mode on `a b&c` back into `/search.html?q=music&tag=Linux`. It asserts `q=music` with no `tag` (`:356`), text mode (`:358`-`:359`), an address without `tag` (`:361`), and exactly one `replace` (`:363`). Excludes a popstate that reads `tag` before `q`, or that leaves `tag` in the address.
- Shape recommendation taken — the same test loads `Linux` and goes back to `a b&c`. The request decodes to `a b&c` (`:343`), and a re-sort pushes `tag=a b&c` (`:353`). Excludes a page keeping its first tag, and unencoded URLs.
- Claim recommendation 3 taken there — `:347` asserts the heading names `a b&c` and not `Linux`.
- Not taken: failure-path and blank-tag edges, since blank tags are refused upstream at Phase 2.
- **Draft defect the observation found:** the draft's `popstate` handler runs the text search for a `q`+`tag` URL but leaves `tag` in the address. The probe's copy of the draft adds `if (state.query && current.has("tag")) pushUrl(true);` before `loadPage`, and the draft then passes all 6 tests. This is recorded for 7.5 as a deviation from the draft that C2 requires.
- Probe: the amended draft passes all 6. Every requested variant is red on a clause line: a branch that never renders cards, popstate keeping the old grid, tag read before `q`, the first tag kept. So are five extra variants and all earlier ones.

**Self-check (round 2):** 6 tests collect; exit 1, 6 failed. First failures: `:242`, `:260`, `:289`, `:310` and `:340` (C1, no tag request today) and `:329` (C2, no history call). All are clause lines; `:340` was a control in the builder's first pass and was made a clause line, since loading a tag URL is C1 behaviour. Questions 2-5 and 7 are unchanged.

**Auditor verdicts:**
- `AUDIT: devsecops-test-shape-auditor — PASS (rounds 1 and 2). Predicted failure: lines 242, 260, 289, 310 and 340 on no tag request today; line 329 on no history call.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: C1g, C2g, D2 uncarried. Fixed: see Remediation 1. Re-audit: PASS, every ledger row CARRIED.` Observation (deferred): the three text-search phases do not read the grid.

**Changes** (source by the builder, `dist` by the main session):
- `data/search.ts` — `q?`/`tag?`; sends `tag` when one is given, else `q`; the docstring says six allowlisted parameters, exactly one of `q` and `tag`.
- `pages/search/index.ts` — tag mode as drafted:
  - `state.tag`, a tag read only when there is no `q`, `TAG_DEFAULT_SORT`;
  - `applyMode()`, `startSearch(query, tag, sort)`, tag status lines, `showIdle(updateUrl = true)`;
  - `pushUrl` writes `q` or `tag` and omits the mode's default sort; `resolveSort(value, tagMode)`.
  
  Two deviations from the draft:
  - the `popstate` `replaceState` fix found at Remediation 1, which C2 requires;
  - the relevance option is found by id through the file's existing `requireElement`, not `querySelector` plus a top-level throw. `tsc --noEmit` reported TS18047 on the draft's version, because the null check does not carry into `applyMode`.
- `search.html` — `<h2 id="search-tag" class="search-tag" hidden></h2>`, and `id="search-sort-relevance"` on the relevance option.
- `search.css` — `.search-tag`.
- `types/videos.ts` — no change here; Phase 4 already carried it.
- `client/frontend/dist/` — rebuilt with `npm run build` (`vite build`), with no local `dev-pages/about.html`. Old hashed assets are replaced by new ones, and the seven pages plus `dev-pages/about.template.html` are regenerated.

**Checkpoint outcome:** PASS — `tests/tmp/test_frontend_search_page.py` 6 passed. Also green, each run alone: `tests/tmp/test_frontend_tag_chips.py` 14, `test_frontend_feed_params` 35, `test_frontend_blocks` 2, `test_frontend_base_css` 1 (after the rebuild), `test_frontend_follows` 3, `test_frontend_dist` 1 (after the rebuild). No inner unit test.

### Step 8 — Close on green

**Refactor pass:** none made. The Engine handler diff is the drafted tag branch with no duplication or hard-coding. The frontend landed from the draft as written, apart from the two deviations recorded under Phase 5. Nothing turned out to need new behaviour.

**Inner unit review:** `tests/tmp/test_search_tags_index_missing.py`. It asserts the exception by name with a positive control (the same call answers 6 once the index exists), and the reason it exists is recorded under Phase 1. No change.

**Clause accounting:** each clause is carried in the last clean audit of its checkpoint:
- `P1C1`, `P1C2`: `test_search_tags.py`
- `P2C1`, `P2C2`: `test_similar_tags.py`, round 3 after the operator-approved post-gate change
- `P3C1`: `test_blocks_tags.py`
- `P4C1`, `P4C2`: `test_frontend_tag_chips.py`
- `P5C1`, `P5C2`: `test_frontend_search_page.py`

No exemptions. No operator overrides of an audit.

**`--compare`:** `validate_tests.py --compare` re-ran the 20 groups the change touched, and 709 passed in 125.5 s over 20 lanes. The frontend groups were green from their per-phase runs, including `test_frontend_dist` and `test_frontend_base_css` after the rebuild. Result: "nothing moved against the previous record". Green against the green baseline.

**Deferred audit observations, for the harvest or follow-on work:**
- P2: the Recent floor skip has no expiry.
- P2: `_is_ordered_subset` bounds no shortfall.
- P3: the up-to-five moderation allowance is unproven.
- P4: the pages' own chip markup is not checked.
- P5: the text phases do not read the grid.

### Step 9 — Documentation

Written from the Phase 1-5 **Changes** and checked against `data/search.py`, `handlers/similar.py`, `handlers/video.py`, `server_config.py`, `router.py`, `client/backend/server.py`, `components/video-card.ts`, `pages/search/index.ts`, `pages/video-page/index.ts` and `data/search.ts`. Facts that differ from the plan and are written as observed: text search's `total` is the fused set (up to 200 from each half under relevance, so up to 400; 396 observed for `music`), not ≤ 200; the Engine also refuses more than one `tag`; the gateway answers an unknown parameter with 400 rather than dropping it; the chip CSS is in `base.css`.

**Checklist ("Documentation to update" and "Documentation the build updates"):**
- `engine/server/README.md` — **updated**: a "What it does" bullet for `GET /api/v1/search/videos` (the `q` and `tag` modes, the match rule, the no-token full scan, sorts, paging, every 400 including more than one `tag`, the 503, and `total` per mode as the fused set up to 400 or the exact tag count, both before moderation and profile filters, `vectorSearch` false in tag mode); a Notes bullet that every served row carries `tags`; the `nsfw` note names search in both modes.
- `client/README.md` — **updated**: the read-gateway filter bullet names text and tag search; a new bullet gives the search route's six allowed parameters, the gateway's 400s for an unknown or repeated key, `tag` stripped and dropped when empty, and `tags` passing through.
- `client/frontend/README.md` — **updated**: the status-line sentence covers both modes; new bullets for card chips (one line, `+N`, outside the video link, the up-next card structure, chip CSS in `base.css`), chip links and unlinkable tags (`span.tag-chip` on the video page), and the search page's tag mode (heading, title, status lines, sorts, URL, submit, `q`+`tag` reduced to `q` on load and back-navigation).
- `client/frontend/src/data/search.ts` — **no update**: Phase 5 already wrote the docstring (six allowlisted parameters, exactly one of `q` and `tag`), and it matches the code.
- `CONTEXT.md` — **updated**: a **Tag** entry defining tag and tag search (trim-and-lowercase sameness, distinct variants, exact mode never combined with text, distinct from the FTS word match, NULL tags in no tag search).
- `docs/project/roadmap.md` — **updated**: a DONE line for issue 42's first plan, naming what the issue keeps open.
- `docs/project/issues/42-tags-on-cards-and-tag-search.md` — **updated**: "Delivered by plan 54" and "Still open" sections, the pre-build tree check dated, and the tags-stage backlog (newest 2,000+ NULL, Recent's first pages chipless) added under Coverage. Status line unchanged.
- `docs/project/adr/0007-nsfw-filter-default-at-request-edge.md` — **updated** (optional item, a pure addition): Decision 2 names `search_videos_by_tag` as the second callee `_handle_search` passes the flag to. `search_videos_by_tag` defaults to `include_nsfw=True`, as Decision 1 requires, so the build does not contradict the ADR.

**Found in 9.1:**
- `docs/wiki/` — **no update**: the directory does not exist.
- `docs/project/adr/` other ADRs — **no update**: none covers search, tags, the gateway allowlist or card markup.
- `README.md` (root) and `DEPLOYMENT.md` — **no update**: their search sentences (gateway route list, blocks filter search, short search pages) stay true.
- `engine/server/data/search.py`, `handlers/similar.py`, `router.py`, `types/videos.ts`, `pages/search/index.ts` docstrings — **no update**: written in Phases 1-5 and accurate.

**Inventory gap:** none. Every document updated is on the checklist.

**ADR conflict:** none.

#### Coordination

none

#### Rationale for the split

There are five phases where the rule allows four, and the operator approved this through AskUser. The build crosses three layers, and every phase is kept to one seam that an existing harness already enters. The data layer needs its own fixture for the edge cases (malformed, object and non-text `tags_json`, Unicode `lower`, the no-token fallback), and the live dataset cannot provide that, so it is split from the route, which is checked against the live Engine in `test_similar.py`. The gateway's change is one allowlist entry, but its proof (forwarding plus blocks) enters a different boundary, `engine_client` in `test_blocks.py`. Folding it into P2 would have given P2 a third fact and a second seam. The frontend splits on its own seam: the chip helper and card placement (the `video-card.ts` node bundle plus the existing page harnesses) and the search page's tag mode. The draft planned to check the search page by hand. Instead it gets a new node harness following `HOME_RUNNER` in `test_frontend_videos_page.py`, so tag mode becomes an executable checkpoint rather than an unverifiable clause. P1 to P3 go in dependency order (data, then route, then gateway), and P4 only needs P2's `tags`. The `dist` rebuild sits in P5, the last frontend phase, so it is built once. The universal "every feed mode" in P2 is parametrised over the production `FEED_MODES` at run time, as the existing readers in `test_similar.py` do. Documentation (READMEs, `CONTEXT.md`, the roadmap, the issue, ADR-0007) gets no phase and is left to Step 9. The `dev-flow` workflow refuses more than 4 phases outright, so on 2026-10-06 the operator approved the five phases again and directed the build to continue by hand under `workflows/dev_flow.md` from Step 7.

