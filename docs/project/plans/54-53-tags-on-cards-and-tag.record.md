# Build record - 53-tags-on-cards-and-tag

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/54-53-tags-on-cards-and-tag.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Tags on cards and tag search\n\n_Status: DRAFT_\n\n## Requirements\n\n### Source issue\n\n`docs/project/issues/42-tags-on-cards-and-tag-search.md`. It asks for three things: tags on video cards in the feeds, up-next and search; narrowing a feed or search to one or more tags; and an advanced search that takes tag criteria alongside the text query. Its measured catalogue figures (2026-10-02) are not repeated here. Read them from the issue.\n\n### Purpose\n\nTwo goals, from the operator (2026-10-04):\n\n- **More of the same:** a visitor who sees the tags on a video they like can use a tag to find more videos like it.\n- **Narrower results:** filtering results by a tag gets the visitor more of what they are looking for.\n\nThe operator expects issue 42 to need more than one plan. What this plan covers is set under Scope.\n\n### Scope\n\nSet by the operator (2026-10-04):\n\n- **In this plan:** each video card shows the video's tags, and clicking a tag opens search results narrowed to videos carrying that exact tag. This means a new exact-tag filter on the Engine's search route.\n- **Cards that show tags:** feed cards, search cards and up-next cards on the video page, so both `renderVideoCard` and `renderSimilarCard` change (operator, 2026-10-04).\n- **Tag matching:** two tags are the same when they are equal after trimming and lowercasing ('Linux', ' linux ' and 'LINUX' match each other). Language variants such as 'music' and 'musique' stay distinct, and no variant map is kept (operator, 2026-10-04).\n- **Which tags show:** every tag on the video, as the uploader wrote it. There is no use-count cutoff and no stoplist, so clicking a tag used only once returns only the video it came from (operator, 2026-10-04).\n- **Tags per card:** as many chips as fit on one line, in the uploader's order, followed by a `+N` marker counting the tags that did not fit. Opening the video shows all of them: the video page already lists every tag (operator, 2026-10-04).\n- **Clickable tags:** a tag chip on a feed card, a search card, an up-next card or the video page opens the exact-tag results for that tag (operator, 2026-10-04).\n- **Tag results:** a tag click opens the search page with the tag in its URL and no text query. The page names the tag and lists the videos carrying it, newest first. Its existing sort menu switches the order to views or popularity (operator, 2026-10-04).\n- **Leaving tag results:** submitting the search box from the tag results runs an ordinary text search and removes the tag from the URL. Text and tag never combine in this plan (operator, 2026-10-04).\n- **Storage:** Rt1, the FTS prefilter plus an exact check, with no new table (operator, 2026-10-04; see Routes).\n- **Later plans:** a filter control for narrowing any search by tags, filtering in the home feeds (Trending, Recent, Popular, the Recommendations mix) and up-next, and advanced search.\n- **Out of scope:** category on cards or as a filter; per-tag counts; fetching tags for the 44,100 videos whose `tags_json` is NULL (the dataset build's tags stage). A NULL-tag video shows no tags and appears in no tag results.\n\n### Acceptance criteria\n\n- **AC1:** every video row the Engine returns from search, every home feed mode and up-next carries `tags`: the video's tags as strings, in the uploader's order. It is `[]` when the stored `tags_json` is NULL, empty, invalid JSON or not a list. The Client gateway passes it through unchanged.\n- **AC2:** feed, search and up-next cards show the tags as chips on one line. Tags that do not fit are dropped from the end and counted in a `+N` marker. A card with no tags shows no tag line. Each chip's text is set as text, never as markup, because tags come from remote instances.\n- **AC3:** clicking a chip on any card, or on the video page, opens the search page for that tag (`/search?tag=<tag>`) and does not also open the video. Clicking anywhere else on a card behaves as it does today.\n- **AC4:** `GET /api/v1/search/videos?tag=<tag>` with no `q` returns the videos whose tag list holds `<tag>` once both are trimmed and lowercased, newest first. `sort=views` and `sort=popularity` reorder them. `sort=relevance` or no sort reads as newest.\n- **AC5:** tag results page through every matching video, and `total` is the exact count of matches. Text search stays capped at its 200-candidate pool.\n- **AC6:** tag results obey the `nsfw` parameter in the same way as text search (ADR-0007: filtered unless `nsfw=1`). The gateway applies the profile's blocks, dislikes and reaction marks to them, as it does for text search.\n- **AC7:** the Engine answers 400 to a request carrying both `q` and `tag`, to a `tag` that is empty after trimming, and to a `tag` longer than 64 characters. The longest stored tag is 30 characters (`tag_lengths.py`).\n- **AC8:** the tag results page names the tag, offers newest, views and popularity sorts (relevance is not offered), and keeps `tag` and `sort` in its URL so the back button and links work. Submitting the search box runs an ordinary text search and removes `tag` from the URL.\n- **AC9:** a tag with no word character (for example `???` or an emoji) still returns its exact matches.\n\n### Consistency constraints\n\n- Tag chips reuse the video page's chip treatment (`tag-chip`, built with `textContent`), and card markup keeps `renderVideoCard`'s rule that every interpolated value passes through `escapeHtml`.\n- The new parameter follows the search route's existing style: the Engine rejects bad input with a 400 and a JSON `error`, and the gateway forwards only allowlisted parameters.\n- A new listing path passes `include_nsfw` from the request edge (ADR-0007, Consequences).\n\n### Conflicts\n\n- **A clickable chip inside the card link:** the operator wants chips clickable on every card, but each card is a single `<a>` to the video page, and the existing comment rules out controls inside it. Proposed resolution, for the operator to confirm: put the chips outside the card's link, as the action buttons already are.\n\n### Checked in the tree (2026-10-04)\n\n- Feed and search cards come from one renderer, `renderVideoCard` in `client/frontend/src/components/video-card.ts`, which `pages/videos` and `pages/search` share. The whole card body sits inside one `<a class=\"video-link\">` pointing at the video page. The like, dislike and block buttons sit outside it for that reason (\"a button inside an <a> would also navigate\"). The channel link is the exception: it is an `<a>` nested inside the card link today.\n- Up-next cards on the video page come from a separate renderer, `renderSimilarCard` in `client/frontend/src/pages/video-page/index.ts`. The whole of each card is one `<a class=\"similar-card-item\">`.\n- Every row the Engine returns from search, the feeds and up-next is reduced by `stable_video_rows` to `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py:101`). That tuple has no `tags_json` or `category`, although the data-layer queries (`data/search.py`, `data/random_videos.py`, `data/metadata.py`) already select `tags_json`.\n- `_handle_search` takes `q`, `sort`, `limit`, `page` and `nsfw`. It has no tag or category parameter.\n- The frontend reaches search through the Client gateway at `/api/v1/search/videos`. The gateway forwards only the query parameters listed for that route in `PROXY_ALLOWED_QUERY_PARAMS` (`client/backend/server.py`): `q`, `page`, `limit`, `sort`, `nsfw`. It also applies the profile's blocks, dislikes and reaction marks to search rows (`FILTERED_ROUTES`).\n- The search page keeps `q` and `sort` in its URL. Its sorts are `relevance`, `published_at`, `views` and `popularity` (`LEXICAL_SORTS` plus relevance).\n- No Engine handler, data-layer query or frontend module filters by tag or category.\n- The video page renders tags as text-built chips and category and language as taxonomy items.\n\n### Measured for the storage question (2026-10-04)\n\nThese were run read-only against the dev `engine/server/db/whitelist.db` (909,004 videos) with the scripts in `.scratch/tags-on-cards-and-tag-search/`. The cache was warm, and I did not measure cold timings.\n\n- **FTS prefilter plus an exact check** (`tag_match_timing.py`): `videos_fts MATCH 'tags_json : \"<tag>\"'` narrows the candidates, and a `json_each` comparison after trim and lowercase keeps exact matches only. This took 0.01\u20130.03 s for `linux` (6,243 videos), `music` (4,525), `pco` (17,464) and `partido da causa oper\u00e1ria` (15,630), including newest-first with `LIMIT 24`.\n- **Full scan with `json_each`, no prefilter:** 0.71 s for `linux`.\n- **The prefilter misses nothing for `linux`** (`fts_miss.py`): every video the full scan finds is in the FTS candidates. The FTS triggers in `sync-whitelist.py` keep `videos_fts.tags_json` current whenever a `videos` row is inserted, updated or deleted, including by the `/api/video` refresh.\n- **Tags FTS cannot prefilter:** 24 of 1,731,904 tag uses contain no word character (`???`, `:'(`, emoji). The tokenizer gives them no token.\n- **Case folding** (`sqlite_lower_probe.py`): in the Engine's Python environment, SQLite `lower('M\u00daSICA')` gives `m\u00fasica`, the same as Python. Accented and Cyrillic tags match as FTS tokens.\n\n## Routes\n\n### Rt1: FTS prefilter plus exact check, no new storage (recommended)\n\nA tag request runs the FTS column match on `tags_json` to get candidates, keeps the rows whose tag list holds the tag after trim and lowercase, and orders them by the requested sort. A tag with no word character falls back to the full `json_each` scan under the statement deadline.\n\n- **Evidence:** measured above at 0.01\u20130.05 s. The existing triggers keep it current.\n- **Cost:** one new data-layer query beside `lexical_candidates`, a `tag` parameter on `/api/v1/search/videos` in the Engine and in the gateway allowlist, and the two tag fields added to returned rows.\n- **Risk:** it depends on how the FTS tokenizer splits tags, which nothing controls. It gives no per-tag counts, which the later facet and filter plans will probably want.\n\n### Rt2: a normalised `video_tags` table\n\nA `video_tags(tag, video rowid)` table indexed on the tag, filled by the sync stage and a migration, and kept current by triggers like those on `videos_fts`.\n\n- **Evidence:** not prototyped. About 1.7 M rows.\n- **Cost:** a whitelist migration, changes to the sync stage and the triggers, and tests on the build path.\n- **Risk:** a second derived copy of `tags_json` to keep in step. It is not needed for the speed this plan wants. Its benefit is reuse by later plans (per-tag counts, facets, feed filtering).\n\n### Rt3: `LIKE` over `tags_json` (rejected)\n\nThis would match JSON text with escapes in it (`\\u00e9`, `\\\"`) and needs the same full scan as the slowest case of Rt1.\n\n### Rt4: clicking a tag runs `q=<tag>` (rejected by scope)\n\nThe operator chose exact-tag results.\n\n## High-level plan\n\n_Not started: waiting for the route to be chosen._",
  "request_source": "read from docs/project/plans/53-tags-on-cards-and-tag-search.md",
  "slug": "53-tags-on-cards-and-tag",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done"
  },
  "phases": [],
  "digests": {},
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/55",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261006T081446-bd06-dev-flow"
  ],
  "snapshot": {
    "tree": "735491f39f21a2cc67a11d6825721c977707610b",
    "at": "2026-10-06T09:15:51-04:00"
  },
  "plan": "docs/project/plans/54-53-tags-on-cards-and-tag.md",
  "record": "docs/project/plans/54-53-tags-on-cards-and-tag.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Source issue\n\n`docs/project/issues/42-tags-on-cards-and-tag-search.md` (Status: enhancement, needs-triage). It asks for three things: tags on video cards in the feeds, up-next and search; narrowing a feed or search to one or more tags; and an advanced search that takes tag criteria alongside the text query. The measured catalogue figures (2026-10-02) are in the issue under \"What the catalogue holds\". This plan covers only part of the issue (see Scope), and the operator expects the issue to need more than one plan.\n\n### Purpose\n\nTwo goals, from the operator (2026-10-04):\n\n- **More of the same:** a visitor who sees the tags on a video they like can click one to find more videos like it.\n- **Narrower results:** filtering results by a tag gets the visitor more of what they are looking for.\n\n### Scope\n\nAll set by the operator, 2026-10-04.\n\n- **In this plan:** every video card shows the video's tags. Clicking a tag opens search results narrowed to the videos carrying that exact tag. This needs a new exact-tag filter (`tag` parameter) on the Engine's search route `/api/v1/search/videos`.\n- **Cards that show tags:** feed cards and search cards (`renderVideoCard` in `client/frontend/src/components/video-card.ts`, shared by `pages/videos` and `pages/search`) and up-next cards on the video page (`renderSimilarCard` in `client/frontend/src/pages/video-page/index.ts`). Both renderers change.\n- **Tag matching:** two tags are the same when they are equal after trimming and lowercasing, so 'Linux', ' linux ' and 'LINUX' all match. The same normalisation applies to the requested tag and to every stored tag. Language variants such as 'music' and 'musique' stay distinct, and no variant map is kept.\n- **Which tags show:** every tag on the video, as the uploader wrote it. There is no use-count cutoff and no stoplist, so clicking a tag used only once returns only the video it came from.\n- **Tags per card:** as many chips as fit on one line, in the uploader's order, followed by a `+N` marker counting the tags that did not fit. The video page already lists every tag.\n- **Clickable tags:** a tag chip on a feed card, search card, up-next card or the video page opens the exact-tag results for that tag.\n- **Tag results:** a tag click opens the search page with the tag in its URL and no text query. The page names the tag and lists the videos carrying it, newest first. Its existing sort menu switches the order to views or popularity.\n- **Leaving tag results:** submitting the search box from the tag results runs an ordinary text search and removes the tag from the URL. Text and tag never combine in this plan.\n- **Storage:** route Rt1, the FTS prefilter plus an exact check, with no new table (see Chosen route).\n- **Later plans, not this one:** a filter control for narrowing any search by tags; tag filtering in the home feeds (Trending, Recent, Popular, the Recommendations mix) and in up-next; advanced search.\n- **Out of scope:** category on cards or as a filter; per-tag counts; fetching tags for the 44,100 videos whose `tags_json` is NULL (that belongs to the dataset build's tags stage). A video with NULL tags shows no tags and appears in no tag results.\n\n### Chosen route: Rt1, FTS prefilter plus exact check, no new storage\n\nA tag request runs an FTS5 column match on `videos_fts.tags_json` (`tags_json : \"<tag>\"`, with the tag quoted as a string literal so it cannot inject FTS operators, following `sanitize_query` in `engine/server/data/search.py`) to get candidates. It keeps only the rows whose `tags_json` list holds the tag after trimming and lowercasing (a `json_each` comparison), and orders them by the requested sort. A tag that yields no FTS token (no word character, such as `???`, `:'(` or an emoji) falls back to a full `json_each` scan with no prefilter. That scan was measured at 0.71 s for `linux` with a warm cache, inside the Engine's 5 s statement deadline (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`, `engine/server/api/server_config.py`). The new query sits in the data layer beside `lexical_candidates` in `engine/server/data/search.py`, and it reuses that module's `LEXICAL_SORTS` orderings and its NSFW clause (`NSFW_ALLOWED_SQL`).\n\nRejected alternatives: Rt2, a normalised `video_tags` table, which needs a migration and a second derived copy of `tags_json`, and which this plan's speed target does not need (it may come back with the later facet and filter plans); Rt3, `LIKE` over `tags_json`, which matches JSON escapes and needs a full scan; Rt4, a tag click running `q=<tag>`, which the operator rejected in favour of exact-tag results.\n\nKnown risk: the prefilter depends on how the FTS tokenizer splits tags, which this code does not control. It gives no per-tag counts.\n\n### Measured evidence (2026-10-04, read-only, dev `engine/server/db/whitelist.db`, 909,004 videos, warm cache, scripts in `.scratch/tags-on-cards-and-tag-search/`)\n\n- `tag_match_timing.py`: the prefilter plus the exact check took 0.01\u20130.03 s for `linux` (6,243 videos), `music` (4,525), `pco` (17,464) and `partido da causa oper\u00e1ria` (15,630), including newest-first with `LIMIT 24`. The full `json_each` scan with no prefilter took 0.71 s for `linux`.\n- `fts_miss.py`: for `linux`, every video the full scan finds is among the FTS candidates. The FTS triggers in `engine/server/db/jobs/sync-whitelist.py` keep `videos_fts.tags_json` current on every insert, update or delete of a `videos` row, including the `/api/video` refresh.\n- 24 of 1,731,904 tag uses contain no word character, so the tokenizer gives them no token and the prefilter cannot find them.\n- `sqlite_lower_probe.py`: in the Engine's Python environment, SQLite `lower('M\u00daSICA')` gives `m\u00fasica`, the same as Python. Accented and Cyrillic tags match as FTS tokens.\n- `tag_lengths.py`: the longest stored tag is 30 characters.\n\n### Acceptance criteria\n\n- **AC1:** every video row the Engine returns from search, from every home feed mode and from up-next carries a `tags` field: the video's tags as strings, in the uploader's order. It is `[]` when the stored `tags_json` is NULL, empty, invalid JSON or not a list. The rows go through `stable_video_rows` / `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py`, around line 106), which do not carry tags today, although the data-layer queries (`data/search.py`, `data/random_videos.py`, `data/metadata.py`) already select `tags_json`. The Client gateway passes `tags` through unchanged.\n- **AC2:** feed, search and up-next cards show the tags as chips on one line. Tags that do not fit are dropped from the end and counted in a `+N` marker. A card with no tags shows no tag line. Each chip's text is set as text, never as markup, because tags come from remote instances. How many chips fit depends on the rendered layout, so it is measured after the card is in the DOM and again when the card's width changes.\n- **AC3:** clicking a chip on any card, or on the video page, opens the search page for that tag at `/search.html?tag=<tag>`, with the tag URL-encoded, and does not also open the video. `/search.html` is the path every nav link uses; the client backend does not rewrite `/search`, and only the Vite dev server does. Clicking anywhere else on a card behaves as it does today.\n- **AC4:** `GET /api/v1/search/videos?tag=<tag>` with no `q` returns the videos whose tag list holds `<tag>` once both sides are trimmed and lowercased, newest first (`published_at DESC, video_id DESC`). `sort=views` and `sort=popularity` reorder them using the `LEXICAL_SORTS` orderings. `sort=relevance`, `sort=published_at` or no sort means newest. Any other sort answers 400, as text search does.\n- **AC5:** tag results page through every matching video, using the existing `page` and `limit` parameters and the existing `SEARCH_MAX_LIMIT` cap. `total` is the exact count of matches the `nsfw` setting allows, counted the same way as text search's `total`: before the Engine's `apply_serving_moderation_filters` and the gateway's profile blocks remove rows, so a page can hold fewer rows than `total` implies. Text search stays capped at its 200-candidate pool (`SEARCH_CANDIDATE_POOL`).\n- **AC6:** tag results obey the `nsfw` parameter the same way text search does (ADR-0007: flagged videos are filtered out unless `nsfw=1`), with `include_nsfw` passed from the request edge (`_parse_include_nsfw`). The Engine applies `apply_serving_moderation_filters` to them, as it does for text search. The gateway applies the profile's blocks, dislike marks and like marks to them, as it does for text search (`/api/v1/search/videos` is in `FILTERED_ROUTES` in `client/backend/server.py`).\n- **AC7:** the Engine answers 400 with a JSON `error` to a request carrying both `q` and `tag`, to a `tag` that is empty after trimming, and to a `tag` longer than 64 characters. A request with neither `q` nor `tag` still answers 400, as it does today.\n- **AC8:** the tag results page names the tag and offers the newest, views and popularity sorts (relevance is not offered). It keeps `tag` and `sort` in its URL, so the back button, reload and shared links restore the same results; the newest sort leaves `sort` out of the URL. Changing the sort menu re-runs the tag search (today the menu does nothing when there is no `q`). The page's title and `popstate` handling cover tag mode as well as text mode. Submitting the search box runs an ordinary text search and removes `tag` from the URL. The gateway allowlist (`PROXY_ALLOWED_QUERY_PARAMS[\"/api/v1/search/videos\"]` in `client/backend/server.py`) gains `tag`.\n- **AC9:** a tag with no word character, such as `???` or an emoji, still returns its exact matches, through the full-scan fallback.\n\n### Card structure (operator-approved resolution, 2026-10-04)\n\n- **Feed and search cards (`renderVideoCard`):** the chip row is rendered outside the card's `<a class=\"video-link\">`, inside the `<article class=\"video-card\">`, in the same way the `card-actions` buttons sit outside it today (\"a button inside an <a> would also navigate\"). The card body inside the link is unchanged.\n- **Up-next cards (`renderSimilarCard`):** today the whole card is one `<a class=\"similar-card-item\">`. It becomes a container element holding the existing link and, beside it, a chip row outside the link. The `data-video-key` attribute and the existing click and stats behaviour keep working. CSS for `.similar-card-item` in `client/frontend/src/video.css` is adjusted to match.\n- **Video page:** the existing tag chips (`client/frontend/src/pages/video-page/index.ts`, around line 290: `span.tag-chip` built with `textContent`) become links to `/search.html?tag=<tag>`, still built from text.\n- **Chips:** reuse the video page's `tag-chip` treatment. Each chip is a real link (`<a href=\"/search.html?tag=...\">`), so middle-click and open-in-new-tab work. In string-built card markup every interpolated value passes through `escapeHtml`, the chip href is built with `URLSearchParams`, and the dev-only `?api=` propagation follows `videoPageUrl`'s rule.\n\n### Consistency constraints\n\n- Card markup keeps `renderVideoCard`'s rule that every interpolated value passes through `escapeHtml` (and every external URL through `safeExternalUrl`). DOM-built chips use `textContent`.\n- The new `tag` parameter follows the search route's existing style: the Engine rejects bad input with a 400 and a JSON `error`, and the gateway forwards only allowlisted parameters.\n- A new listing path passes `include_nsfw` from the request edge (ADR-0007, Consequences).\n- New code matches the style of the file it lands in. Smallest change that works: no new table, no new dependency, no new module unless a renderer needs a shared chip helper used by both card renderers.\n\n### Checked in the tree (2026-10-04)\n\n- `renderVideoCard` wraps the whole card body in one `<a class=\"video-link\">`. The like, dislike, block and follow buttons sit outside it. The channel link is an `<a>` nested inside the card link (invalid HTML today, but left as it is in this plan).\n- `renderSimilarCard` renders each up-next card as one `<a class=\"similar-card-item\">`.\n- `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py:106`) has no `tags_json`, `tags` or `category`.\n- `_handle_search` (`similar.py:420`) takes `q` (required), `sort` (`relevance` or a `LEXICAL_SORTS` key), `limit`, `page` and `nsfw`. It has no tag or category parameter.\n- The gateway allowlist for `/api/v1/search/videos` is `q`, `page`, `limit`, `sort`, `nsfw`.\n- The search page (`client/frontend/src/pages/search/index.ts`) keeps `q` and `sort` in its URL. Its sorts are `relevance`, `published_at`, `views` and `popularity`. Its sort-change handler and `popstate` handler do nothing without a `q`.\n- No Engine handler, data-layer query or frontend module filters by tag or category today.\n\n### Baseline suite state\n\nThe pre-build baseline suite run exited with code 0 (all passing, no variant). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`. Record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.\n</requirements>\n\n<conflicts>\nThe operator wants chips clickable on every card (Scope), but `renderVideoCard` wraps the card in one `<a class=\"video-link\">` and its comment rules out controls inside it, and `renderSimilarCard` is a single `<a>`. The operator approved the fix on 2026-10-04: chips go outside the card link, and the up-next card is wrapped in a container.\nThe draft's tag URL `/search?tag=<tag>` conflicts with the tree: every nav link uses `/search.html`, and only the Vite dev server rewrites `/search`. The operator approved `/search.html?tag=<tag>` on 2026-10-04.\nThe draft's AC5 says `total` is \"the exact count of matches\", but `_handle_search` counts `total` before `apply_serving_moderation_filters`, and the gateway removes blocked rows afterwards. The operator approved defining `total` as the count of NSFW-allowed matches before moderation and profile blocks, matching text search, on 2026-10-04.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe work has three layers: the Engine, the gateway and the frontend. Each layer gets the smallest change that meets the acceptance criteria. There is no new table, no new dependency and no new Python module. The frontend gains a shared chip helper in the existing `components/video-card.ts`, and one small stylesheet that the helper imports.\n\n**Engine: tags on every row (AC1).** `stable_video_row` in `handlers/similar.py` adds a `tags` key to each projected row. The value is the stored `tags_json` parsed by `tags_from_json`, which already exists in `handlers/video.py` and already gives `[]` when the value is NULL, empty, invalid JSON or not a list. It also keeps the uploader's order. `video.py` imports nothing from `similar.py`, so importing it the other way creates no cycle. Search uses this projection (`similar.py:484`), and so do the feed modes and up-next (`similar.py:611`). The row sources (`data/search.py`, `data/random_videos.py`, `data/metadata.py`) already select `tags_json`. The build should still check each feed mode's row source, including Following, and a test per mode should assert `tags` is present. `STABLE_VIDEO_FIELDS` itself does not change: `tags` is derived and does not exist as a stored field. The gateway's `_filter_payload` round-trips each row as a dict, so `tags` passes through it untouched.\n\n**Engine: the `tag` parameter (AC4, AC5, AC6, AC7, AC9).** `_handle_search` keeps its `SEARCH_ENABLED` gate and then branches on which parameter is present:\n- Both `q` and `tag`: 400.\n- A `tag` that is empty after trimming: 400.\n- A `tag` longer than 64 characters after trimming: 400.\n- Neither: the existing \"Missing query parameter q\" 400. `parse_qs` drops a bare `?tag=` and the gateway drops blank values, so `?tag=` reaches this branch and still gets a 400.\n\nEvery 400 uses the existing `respond_json(self, 400, {\"error\": ...})` form. In tag mode the sort is checked the same way as now (relevance or a `LEXICAL_SORTS` key, anything else 400). Relevance and no sort both resolve to `published_at`. `limit`, `page`, `SEARCH_MAX_LIMIT` and `_parse_include_nsfw` are parsed exactly as text search parses them. The tag branch calls a new function in `data/search.py`, placed beside `lexical_candidates`. It returns `(rows, total)` like `search_videos`, so everything after it is shared: `apply_serving_moderation_filters`, `stable_video_rows` and the same response shape. In tag mode the response's `sort` field echoes the resolved sort and `vectorSearch` is false. Text search is untouched and keeps its `SEARCH_CANDIDATE_POOL` cap.\n\n**What the new data-layer function does.** It works under `search_connection`'s lock and `search_deadline`, and raises `SearchIndexMissing` when `videos_fts` is absent, as text search does.\n- **Prefilter.** It splits the tag with the module's `_TOKEN_SPLIT`. If at least one word token survives, it builds an FTS5 column filter on `tags_json` holding one quoted phrase. Quotes are doubled, as in `sanitize_query`, so the tag cannot inject operators. It joins `videos_fts` to `videos` the way `lexical_candidates` does.\n- **Fallback (AC9).** If no token survives, there is no FTS join and the query scans `videos` directly.\n- **Exact check (both paths).** A `json_each` membership test compares `lower(trim(element))` with `lower(trim(?))`. The requested tag is normalised in SQL as well as the stored tags, so both sides go through one function, which is what the requirements ask for. The trim names an explicit whitespace set (space, tab, CR, LF), because SQLite's default `trim` removes only spaces while the gateway's `strip()` removes all whitespace.\n- **Filtering and ordering.** It adds the `NSFW_ALLOWED_SQL` clause when `include_nsfw` is false. It orders by the `LEXICAL_SORTS` entry for the resolved sort, and pages with `LIMIT ? OFFSET ?` from `page` and `limit`.\n- **Total (AC5).** A second `COUNT(*)` statement with the same FROM/WHERE runs under the same lock and deadline. So `total` counts every match the NSFW setting allows, before moderation and before the profile filters, which matches what text search's `total` counts.\n\n**Gateway (AC6, AC8).** `tag` is added to `PROXY_ALLOWED_QUERY_PARAMS[\"/api/v1/search/videos\"]`. That route is already in `FILTERED_ROUTES`, so blocks, dislike marks and like marks apply to tag results with no further change. The gateway strips the value, and the Engine re-trims it anyway.\n\n**Frontend: shared chip helper (AC2, AC3).** `components/video-card.ts` gains three exports, each used by more than one caller:\n- `tagSearchUrl(tag, apiParam)` builds `/search.html?tag=\u2026` with `URLSearchParams`. It adds `api` only in a dev build, by the same rule as `videoPageUrl`.\n- `renderTagChips(tags, apiParam)` returns the chip row as a string: a `.card-tags` container of `<a class=\"tag-chip\">` links, every value through `escapeHtml`, then a hidden `+N` marker. It returns an empty string when there are no tags, so a card with no tags has no tag line.\n- `observeTagRows(container)` is called once per grid container: the feed `cards`, the search `results` and the up-next `similarCards`. It installs one `MutationObserver` that finds `.card-tags` rows as they are added (by `innerHTML`, `insertAdjacentHTML` or `outerHTML` re-renders) and registers them with one shared `ResizeObserver`. The ResizeObserver's first callback runs the fit after layout, and later callbacks re-fit when the card's width changes. Removed rows are unobserved.\n\nThe fit itself: un-hide every chip and the marker, then hide chips from the end until the last visible chip plus the marker fits the row's width. The marker reads `+N` and is shown only when N > 0. The row is a no-wrap flex line with hidden overflow, so before the fit runs the worst case is a clipped chip, never a second line.\n\n**Frontend: the cards (AC2, AC3).**\n- **Feed and search cards.** `renderVideoCard` appends the chip row inside the `<article>`, after the `<a class=\"video-link\">` and beside `card-actions`. Both pages' delegated click handlers only act on `[data-card-action]`, so a chip click is an ordinary link to the tag results and never also opens the video.\n- **Up-next cards.** `renderSimilarCard` changes its outer `<a class=\"similar-card-item\">` to a `<div class=\"similar-card-item\">` that keeps `data-video-key`. Inside it are the existing body as `<a class=\"similar-card-link\">` and, beside it, the chip row. The stats update at `index.ts:1613` finds the card by `[data-video-key]` and the stat spans inside it, so it keeps working.\n- **CSS for up-next.** In `video.css`, the border, background and hover rules stay on `.similar-card-item`. The link takes the flex column, `color: inherit` and no underline.\n- **Chip styles.** `.tag-chip` moves out of `video.css` into a small stylesheet that `video-card.ts` imports, together with the `.card-tags` row rules. That stylesheet loads on the feed, search and video pages, and there is still only one copy of the chip style.\n\n**Frontend: the video page (AC3).** The existing chips stay DOM-built with `textContent` but become `<a class=\"tag-chip\">` elements whose `href` comes from `tagSearchUrl`.\n\n**Frontend: the search page in tag mode (AC8).**\n- **Data module.** `data/search.ts`'s `fetchSearchResults` takes either `q` or `tag` and sets only the one given. The cache key is the URL, so tag pages are cached apart from text pages.\n- **State and loading.** The page's state gains `tag`. When the URL has a `tag` and no `q`, the page runs in tag mode: the input is empty, and a heading (a new element in `search.html`, filled with `textContent`) names the tag. The title becomes \"<tag> - Tag - Search - PeerTube - Browser\". The status line says \"Showing X of Y videos tagged \u2026\" or \"No videos tagged \u2026\".\n- **Sort menu.** In tag mode the relevance option is hidden and disabled, and the default sort is `published_at`. `pushUrl` leaves `sort` out when the sort is the mode's default (relevance for text, `published_at` for tag) and writes `tag` when in tag mode.\n- **Handlers.** The sort-change handler and the `popstate` handler both handle tag mode as well as text mode.\n- **Leaving tag mode.** A form submit clears `tag`, restores the relevance option and runs `startSearch` as now, so `tag` leaves the URL. The chosen sort is carried over (`published_at`, views and popularity are all valid text sorts).\n- **URL with both `q` and `tag`.** Such a URL can only be hand-made. The page prefers `q` and drops `tag` with `replaceState`, so it never sends the combination the Engine would refuse.\n- **Paging.** Infinite scroll keeps its existing `page`/`total` logic. Tag results page through the whole match set because `total` is now exact.\n\n### Alternatives considered\n\n- **Window `COUNT(*) OVER ()` instead of a second count statement.** Rejected. It saves one statement on the cheap path, but a page past the end returns no rows and therefore no total, which breaks AC5. The count costs about 0.01\u20130.03 s on the prefilter path, and about 0.7 s more on the full-scan fallback, which only affects the rare tags with no word character.\n- **Normalising the requested tag in Python and the stored tags in SQL.** Rejected. Python's `lower`/`strip` and SQLite's `lower`/`trim` disagree on whitespace and on a few Unicode cases (for example `\u0130`). Running both sides through the same SQL expression is how the \"same normalisation on both sides\" requirement holds by construction.\n- **Calling a fit function after each render site instead of a `MutationObserver`.** Rejected. The three pages insert cards from about nine places (reset, append, in-place `outerHTML` re-renders after a like, dislike or block, and `removeRows`), and every new insertion path would have to remember to call it. One observer per container covers all of them with three call sites.\n- **CSS-only truncation.** Rejected. CSS can clip the line but cannot count the hidden chips for `+N`.\n- **Putting the chips inside `.video-link` and stopping propagation.** Rejected. It nests an `<a>` inside an `<a>` and breaks middle-click, and the operator approved the outside-the-link structure.\n- **Importing `videos.css` on the video page, or copying `.tag-chip` into it.** Rejected. Importing it would bring in feed styles that could collide; copying it would give two copies to keep in step.\n- **A separate `_handle_tag_search` route or handler.** Rejected. AC4 puts tag search on `/api/v1/search/videos`. Branching inside `_handle_search` shares the moderation, projection and response code instead of duplicating it.\n- **Falling back to a full scan whenever the FTS prefilter returns nothing.** Rejected. It would hide tokenizer mismatches, but every search for a tag nobody uses would cost a 0.7 s scan, which is an easy load amplifier. The fallback stays tied to \"no word token\", as the settled route says.\n\n### Gotchas and risks\n\n- **`json_each` and bad `tags_json`.** `json_each` raises on malformed JSON, which would turn a single bad row into a 500 for the whole tag query. It also iterates an object's values, which would wrongly match a non-list. The exact check therefore feeds `json_each` a CASE that substitutes `'[]'` unless `tags_json` is valid JSON and of type `array`, and it compares only `text` elements. A guard in a separate AND term is not enough, because SQLite does not promise evaluation order.\n- **Tokenizer mismatch (the known risk of Rt1).** The prefilter's phrase comes from Python's `\\w` split, but the index was built by FTS5's `unicode61`. Where the two disagree, matches are missed and the gap is not reported. One example is a tag stored with a JSON escape inside it (`a\\nb` is indexed as `a`, `nb`). Another is a character Python counts as a word character but `unicode61` treats as a separator. `to_tags_json` writes raw UTF-8, and `fts_miss.py` showed no misses for `linux`, so the expected gap is a handful of edge-case rows. Rt2 is the upgrade path if it ever matters.\n- **Superset matches are fine.** `unicode61` removes diacritics and folds case, and a phrase can run across adjacent tags. Both only widen the candidate set, and the exact check discards the extras.\n- **SQLite `lower()` on the search connection.** The probe showed Unicode-aware `lower()` in the Engine's environment. Tests should run an accented tag (`M\u00daSICA` vs `m\u00fasica`) through the real search connection, so a build without that behaviour fails loudly instead of quietly matching ASCII only.\n- **Deep pages.** With an exact `total`, a visitor can scroll deep into `pco` (17,464 rows). `OFFSET` paging gets slower linearly with depth but stayed well inside the deadline at the measured sizes. The fallback scan costs about 1.4 s per page (page plus count), which is also inside the 5 s deadline.\n- **Short pages stop scrolling.** The gateway and moderation can remove every row on a page. The page's existing `rows.length > 0` stop condition then ends scrolling early. Text search already behaves this way, and AC5 accepts short pages.\n- **Rows past the end of a pool.** The `+N` fit needs layout. The ResizeObserver's initial callback provides it, and until that callback runs the row is clipped, not wrapped. Hidden chips leave the accessibility tree, and the marker carries an `aria-label` (\"N more tags\").\n- **Up-next markup change breaks a test.** `tests/active/test_frontend_video_page_similars.py` asserts on `similar-card-item`, so it has to change in this build. The built bundle under `client/frontend/dist` is regenerated output and is not edited by hand.\n\n### Tradeoffs the operator is asked to accept\n\n- A tag search costs two statements per page (rows plus count) in exchange for an exact `total`.\n- Rare tokenizer-mismatch tags can return fewer videos than they carry. This is the accepted Rt1 risk, and Rt2 is the upgrade path.\n- The `+N` marker is plain text, not a control. To see every tag, the visitor opens the video, whose page lists them all.\n- The chip row adds one line of height to every card that has tags. Cards without tags are unchanged, so card heights in a grid can differ.\n- A hand-made URL carrying both `q` and `tag` is silently reduced to the text search.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\nNote on the tree: `/home/enduser/code/PeerTube-browser/.worktrees/55` does not exist (rg: \"No such file or directory\"; Glob finds nothing under `.worktrees/`), although `tests/config.json:3` names it as `project_dir`. Every file below was opened in the main checkout `/home/enduser/code/PeerTube-browser`, and paths are relative to the repo root. An earlier pass of this step is already written into `docs/project/plans/54-53-tags-on-cards-and-tag.md`. I re-checked its claims against the source and they hold. Below I add what it lacks: stored blank or over-64 tags producing dead chips, the absence of any custom SQLite `lower()`, `test_similar`'s group missing `handlers/video.py`, the existing nested `channel-link` anchor, and `popstate` pushing history through `showIdle`.\n\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"stable_video_row (129-131) / stable_video_rows (134-136); new import of tags_from_json\">\n**What changes:** `stable_video_row` returns `{field: row.get(field) for field in STABLE_VIDEO_FIELDS}` plus `\"tags\": tags_from_json(row.get(\"tags_json\"))`. `STABLE_VIDEO_FIELDS` (106-126, with the `INCLUDE_DYNAMIC_STATS` tail at 125-126) is unchanged. A new import line is added: `from handlers.video import tags_from_json`.\n\n**What depends on it:**\n- Exactly two callers: `_handle_search` (484) and `_respond_rows` (611). `_respond_rows` serves every feed mode (random, ordered trending/popular/recent, following, home mix and its fallback), up-next, the raw-vector route and seed-random.\n- `maybe_attach_debug` (139) spreads the stable row, so `tags` survives in debug mode.\n- Row sources that carry `tags_json` (verified):\n  - `data/search.py:66` (`VIDEO_ROW_SQL`)\n  - `data/metadata.py:49,91,198` (`fetch_metadata`, which up-next and vector search use)\n  - `data/random_videos.py:59,115,160,204,248`\n  - `_ordered_row` (`random_videos.py:292`), which serves `fetch_ordered_page` and Following's `fetch_followed_page` (417)\n- `apply_serving_moderation_filters` (`data/serving_moderation.py:14-48`) returns the row dicts it was given and does not rebuild them.\n\n**Import cycle:** none. `router.py:44` already imports `handlers.video`, and `similar.py:85` imports `router`, so `handlers.video` is always loaded before `similar.py` finishes importing. `video.py` imports only `data.*`, `http_utils` and `server_config` (9-21).\n\n**Regression risk: low.** The change is additive and `tags_from_json` never raises. No test pins the exact key set of an Engine listing row: `test_random_videos.py:591` checks a subset, and `test_metadata.py:40` and `test_internal_client_reads.py:27` check data-layer rows. `tags` is remote-controlled text that now reaches every listing payload and the `innerHTML`/`insertAdjacentHTML`/`outerHTML` sinks on three pages.\n</impact>\n\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"_handle_search (420-486); import line 27; module docstring (3) and method docstring (421)\">\n**What changes**\n- After the `SEARCH_ENABLED` gate (426-428), read `tag` beside `q` (430). Validation: `q`+`tag` \u2192 400; a tag that strips to empty \u2192 400; a stripped tag longer than 64 \u2192 400; neither \u2192 the existing `\"Missing query parameter q\"` (431-433).\n- The sort check (435-438) stays. In tag mode only, `relevance` or a missing sort resolves to `published_at`. Text mode must keep `relevance` as its default, because `search_videos` branches on `sort == \"relevance\"` for the vector half (`data/search.py:293`).\n- `limit` and `page` (440-446) stay shared.\n- The tag call must sit inside the same `except SearchIndexMissing` \u2192 503 handler (464-467) and pass `include_nsfw=_parse_include_nsfw(...)` (defined at 1089).\n- Moderation and `stable_video_rows` (468-484) stay shared.\n- The response echoes the resolved `sort`, and `vectorSearch` is `False` in tag mode (today 483 derives it from the encoder).\n- Line 27 gains the new function name. The docstrings at 3 and 421 say \"hybrid video search\".\n\n**Detail:** Python `strip()` removes all Unicode whitespace, while the planned SQL trim removes only space, tab, CR and LF. Bind the Python-stripped value, so a direct Engine call with NBSP padding still matches.\n\n**No named constant exists for 64.** `SEARCH_MAX_TOKEN_LENGTH = 64` (`server_config.py:460`) is the per-FTS-token cap, a different limit.\n\n**What depends on it:**\n- `router.py:98-100` (`parse_qs`, no `keep_blank_values`).\n- The rate-limit gate.\n- `_serve` (410-418): an interrupted statement becomes 503 \"Query time limit exceeded\" (400).\n- Live text-search tests: `test_similar.py:140,142`, `test_frontend_follows.py:83`, plus the gateway-driven tests in the blocks, reactions and upnext-pager files.\n\n**Regression risk: medium.** The branch sits in front of the text path. Resolving relevance\u2192published_at outside tag mode silently disables vector fusion for text search, and mis-reading `tag` lets `q`+`tag` through.\n</impact>\n\n<impact path=\"engine/server/data/search.py\" element=\"new tag-search function beside lexical_candidates (134-168); module docstring (1-10); search_videos docstring (271-277)\">\n**What changes:** a new function returning `(rows, total)`.\n- It copies the shape of `search_videos` 283-290: `search_connection` (32-43) \u2192 `with lock:` \u2192 `with search_deadline(server):` (46-49) \u2192 `fts_available` (121-131) \u2192 `SearchIndexMissing`.\n- **Prefilter:** split with `_TOKEN_SPLIT` (25) and build one quoted phrase on the `tags_json` column, doubling quotes as at 112. It joins `videos_fts f JOIN videos v ON v.rowid = f.rowid LEFT JOIN channels c ...` as at 157-160.\n- **Fallback:** `FROM videos v LEFT JOIN channels c`.\n- **Exact check:** `EXISTS(SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) AND json_type(v.tags_json)='array' THEN v.tags_json ELSE '[]' END) j WHERE j.type='text' AND lower(trim(j.value, set)) = lower(trim(?, set)))`.\n- **NSFW:** `AND {NSFW_ALLOWED_SQL}` when the flag is False; it is already imported (20).\n- **Order:** `LEXICAL_SORTS[sort]` (83-87).\n- **Paging:** `LIMIT ? OFFSET ?`.\n- **Total:** a second `COUNT(*)` with the same FROM/WHERE.\n- Rows reuse `VIDEO_ROW_SQL`, as the text path does. There is no `video_embeddings` join and no error threshold, the same as text search (`test_search.py:27`).\n- Default `include_nsfw=True`, per ADR-0007 decision 1.\n- The module docstring (1-10) and the `search_videos` docstring (271-277, \"fused candidate set\") describe only hybrid search.\n\n**Facts checked against files**\n- No custom SQL function is registered on any Engine connection. Grep for `create_function` finds only `ann_id_of` in the jobs (`sync-whitelist.py:510`, `whitelist_migrations.py:407`), and `connect_readonly_db` (`data/db.py:85`) adds none. Unicode-aware `lower()` therefore depends entirely on the SQLite build (ICU) in the Engine's pixi env. SQLite core `lower()` folds ASCII only. I cannot confirm the plan's probe from files; tests must run on `ENGINE_PY`.\n- FTS5 tokenizes the phrase string with the table's own `unicode61` tokenizer. A Python token like `foo_bar` is therefore re-split into the phrase `foo bar`, which narrows the Rt1 gap rather than widening it.\n\n**What depends on it:** `_handle_search`; `tests/active/test_search.py`.\n\n**Regression risk: medium-high, all in SQL semantics**\n- `json_each` raises on malformed JSON, so the guard must sit inside its argument.\n- The trim set and the `lower()` build behaviour must be handled as above.\n- The FTS phrase must stay a quoted literal.\n- `OFFSET` cost grows with depth.\n- The `views` sort has no index (only `idx_videos_published` and `idx_videos_popularity`, `sync-whitelist.py:402-405`), so a views-sorted fallback scan sorts the whole match set.\n</impact>\n\n<impact path=\"engine/server/api/handlers/video.py\" element=\"tags_from_json (164-174); to_tags_json (156-161)\">\n**What changes:** no change to either body. `tags_from_json` gains a second importer.\n\n**What depends on it:**\n- `/api/video`'s `tags` (345), and now every listing row.\n- `to_tags_json` writes `ensure_ascii=False` (160), as does the crawler's `toTagsJson` (`engine/crawler/src/videos-worker.ts:820-824`, `JSON.stringify`). Stored tags are therefore raw UTF-8, which keeps the Rt1 gap small.\n- Neither writer filters empty, whitespace-only or long strings, so stored tags can be `\"\"`, `\"  \"` or longer than 64 characters (see the video-card entry).\n\n**Regression risk: low.** A future change here now changes every listing as well as `/api/video`.\n</impact>\n\n<impact path=\"engine/server/api/server_config.py\" element=\"SEARCH_* block (450-470)\">\n**What changes:** optional. Add `SEARCH_MAX_TAG_LENGTH = 64` beside `SEARCH_MAX_TOKEN_LENGTH` (460) and import it in `similar.py` (37-64). The plan names neither the constant nor a literal.\n\n**What depends on it:** many test groups list this file (for example `test_similar.py`, `test_dislike_profile.py`, `test_internal_translate.py`), and `test_similar.py:130-135` execs it.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"engine/server/api/router.py\" element=\"module docstring route list (11); _search (98-100)\">\n**What changes:** line 11 reads `GET /api/v1/search/videos: hybrid video search. [rate-limit gate]` and should mention the exact-tag mode. `_search` is unchanged, since it forwards every parsed parameter.\n\n**What depends on it:** nothing new.\n\n**Regression risk: none.**\n</impact>\n\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"videos_fts DDL (393-401) and triggers (275-290): read-only dependency\">\n**What changes:** nothing.\n\n**What depends on it:** the prefilter depends on `videos_fts` keeping its `tags_json` column under the default `unicode61` tokenizer, and on the AI/AD/AU triggers keeping it in step, including `/api/video/refresh` writes (`video.py:391`).\n\n**Regression risk:** none from this build. A future tokenizer or column change would silently drop tag matches.\n</impact>\n\n<impact path=\"client/backend/server.py\" element=\"PROXY_ALLOWED_QUERY_PARAMS['/api/v1/search/videos'] (104); _sanitize_query (138-154); _handle_engine_read_proxy_get (595-604); _filter_payload (1393-1419)\">\n**What changes:** line 104 becomes `{\"q\", \"page\", \"limit\", \"sort\", \"nsfw\", \"tag\"}`.\n\n**Inherited behaviour**\n- `tag` is stripped, because it is not in `PROXY_UNSTRIPPED_QUERY_PARAMS` (120), and dropped when empty. A repeated `tag` gets the gateway's own 400.\n- The query is re-encoded with `urlencode` (752).\n- The route is in `FILTERED_ROUTES` (83) and `PROXY_READ_GET_ROUTES` (95-97), so keyed tag results get blocks and reaction marks. It is not in `FEED_ROUTES`, so there is no over-fetch and no dislike removal.\n- `_filter_payload` round-trips row dicts, so `tags` passes. It re-encodes with default `ensure_ascii` (1419), so non-ASCII tags arrive `\\u`-escaped, which is equivalent JSON.\n\n**What depends on it:**\n- `client/frontend/src/data/search.ts` (its docstring says \"exactly five\").\n- `test_server.py:1549` pins only the `nsfw` allowlist on `/api/video`.\n- No test asserts that `tag` is unknown.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"client/frontend/src/components/video-card.ts\" element=\"new exports tagSearchUrl / renderTagChips / observeTagRows; renderVideoCard (341-419); new side-effect CSS import; module docstring (1-12)\">\n**What changes**\n- **`tagSearchUrl`:** mirrors `videoPageUrl`'s DEV-only `api` rule (330).\n- **`renderTagChips`:**\n  - Returns `\"\"` for a missing, non-array or empty list. Rows cached before the deploy lack `tags`.\n  - Escapes every value with `escapeHtml` (67-84).\n  - The `+N` marker starts `hidden` and carries an `aria-label`.\n  - It must not emit `style=\"...\"`, because every page's CSP is `style-src 'self'` (`search.html:8`). The precedent comment is at `video.css:62`.\n- **`observeTagRows`:** one `MutationObserver` plus one shared `ResizeObserver`. Neither may be constructed at module level, and calling it where `MutationObserver` is undefined throws, which matters for the node harnesses below.\n- **`renderVideoCard`:** puts the row after `</a>` at 416, beside `actionsMarkup`.\n\n**Gaps the plan does not settle**\n- **Dead chips.** Stored tags can be blank, whitespace-only or longer than 64 characters, since neither writer caps them (see the `video.py` entry):\n  - A chip for `\"\"` or `\"  \"` links to `?tag=` or `?tag=%20`. The gateway drops the value and the Engine answers \"Missing query parameter q\", or the search page sees no tag and shows idle.\n  - A chip for a tag longer than 64 characters links to a guaranteed 400.\n  - The helper should skip blank tags. Whether to skip over-length tags or link them anyway is an open decision.\n- **Existing nested anchor.** The card already nests `<a class=\"channel-link\">` inside `<a class=\"video-link\">` (402). The plan's \"no nested `<a>`\" applies only to the chips.\n\n**What depends on it**\n- `pages/videos/index.ts:36-51`: the home feed and the `/videos.html?id=` similar view.\n- `pages/search/index.ts:14-20`.\n- `pages/likes/index.ts:9`: helpers only, but it now pulls in the CSS chunk.\n- `pages/video-page/index.ts:29`.\n- `test_frontend_video_card.py:39` (with `--loader:.css=empty`).\n- `test_frontend_reactions.py:106-121`, which bundles without a CSS loader flag.\n\n**Regression risk: medium.** The risks are an XSS sink if any interpolation is missed, a `ReferenceError` in harnesses, and the CSP silently dropping inline styles.\n</impact>\n\n<impact path=\"client/frontend/src/tags.css (new file; name to be chosen)\" element=\"new shared sheet: .tag-chip moved from video.css 408-415, plus .card-tags row and +N marker rules\">\n**What changes**\n- `.tag-chip` moves here, using `--line` and `--ink` from `base.css`.\n- Chips become `<a>`, so the sheet needs `text-decoration: none` and an explicit colour. There is no global `a` rule; `.video-link` is scoped (`videos.css:297`).\n- `.card-tags` is a no-wrap flex row with `overflow: hidden` and `min-width: 0`.\n- A `[hidden] { display: none }` override is needed for any element given a display value. The precedents are `video.css:388,486`.\n\n**Build hazard**\n- `video-card` is already its own Vite chunk (`dist/assets/video-card-DWtpz1-l.js`). Vite has no `manualChunks` or `cssCodeSplit` override (`vite.config.ts:82-96`), so a CSS import there emits a separate `video-card-*.css` linked from index, videos, likes, search and video-page.\n- `test_frontend_base_css.py:100` asserts that the linked bundles are exactly `[\"channels\",\"search\",\"video\",\"videos\"]`.\n- 105-115 require every linked bundle to open with the full built base and contain no `@import`.\n- The new bundle fails both checks unless the sheet `@import`s `./base.css`, which duplicates base. Search already loads base twice, through `videos.css` and `search.css`.\n\n**What depends on it:** the `tests/config.json` groups for base-css (355-362) and dist (363-412).\n\n**Regression risk: high** (build and test contract).\n</impact>\n\n<impact path=\"client/frontend/src/video.css\" element=\".tag-list (402-406), .tag-chip (408-415), .similar-card-item (528-539) and :hover (541-544)\">\n**What changes**\n- Remove `.tag-chip`.\n- `.similar-card-item` keeps its padding, border, radius, background, transition, hover, and a flex column so the link and the chip row stack. `text-decoration` and `color` move to a new `.similar-card-link`, which takes `display:flex; flex-direction:column; gap:0.5rem` to keep the inner spacing.\n- The `.similar-thumb`, `.similar-title`, `.similar-channel`, `.similar-meta` (546-602) and `.similar-reaction` selectors still match inside the link.\n- `.tag-list` (the video page's full list) must stay wrapping.\n- `.similar-card` (36) is a different selector (the section panel).\n\n**What depends on it:** `test_frontend_base_css.py`, `test_frontend_dist.py`, and the `test_frontend_video_page.py` group (`tests/config.json:230`).\n\n**Regression risk: low-medium** (visual, on the `.similar-grid` at 522-526).\n</impact>\n\n<impact path=\"client/frontend/src/videos.css\" element=\".video-card (281), .video-link (297), .card-actions (496-502)\">\n**What changes:** probably none, since the new sheet supplies the row. The chip row becomes a direct child of `.video-card`, after `.video-link`.\n\n**What depends on it:** `.cards-grid` (257) on the feed and search pages.\n\n**Regression risk: low.** Cards with tags grow by one line, which is an accepted tradeoff.\n</impact>\n\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"tag chips (290-304); import (29)\">\n**What changes:** `createElement(\"span\")` (295) becomes `createElement(\"a\")`, keeping `className=\"tag-chip\"` and `textContent`, and gaining `href = tagSearchUrl(tag, params.get(\"api\"))`. `params` is at line 82. Add `tagSearchUrl` to the import at 29. The \"No tags\" branch (302) stays.\n\n**What depends on it:** `test_frontend_video_page.py:4-5,189,306-330` reads the children's `textContent` and the `tag-chip` class. The recording element has an `href` accessor (86-87).\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"renderSimilarCard (1688-1721); applySimilarStatsToDom (1610-1617); similarCards render sites 357, 369, 375, 384, 388, 708; local videoPageUrl (1655-1676)\">\n**What changes**\n- The outer `<a class=\"similar-card-item\" href=\u2026${keyAttribute}>` (1710) becomes `<div class=\"similar-card-item\"${keyAttribute}>` wrapping `<a class=\"similar-card-link\" href=\u2026>`, plus `renderTagChips(row.tags, params.get(\"api\"))`.\n- The page keeps its own `escapeHtml` and `videoPageUrl`; the local one adds no `api`.\n- `observeTagRows(similarCards)` is called once. `similarCards` is nullable (61), so the call goes after the null check, for example in `loadSimilarVideos` after 343, guarded so it runs only once.\n- `applySimilarStatsToDom` still finds `[data-video-key]` (now on the div) and `[data-stat=\"views\"]`.\n\n**Render sites:** 375 (`innerHTML`) and 708 (`insertAdjacentHTML`).\n\n**What depends on it:** `test_frontend_video_page_similars.py` (see that entry). Middle-click now targets only the inner link, so the card padding is no longer clickable.\n\n**Regression risk: medium.**\n</impact>\n\n<impact path=\"client/frontend/src/pages/videos/index.ts\" element=\"cards container (55-68); renderCards (390-409); renderFeedCard (414-423); runCardAction outerHTML (457); click delegation (151-157)\">\n**What changes:** call `observeTagRows(cards)` once after the guard at 66-68. `renderFeedCard` already passes `apiParam` (84, 418). The click handler acts only on `[data-card-action]`. `existingCount` counts `.video-card` (403), so the new row does not affect it.\n\n**What depends on it:** `test_frontend_videos_page.py`.\n- The `HOME_RUNNER` harness (33-66) defines `IntersectionObserver` only.\n- The second harness (315-316) defines `IntersectionObserver` and `ResizeObserver`.\n- Neither defines `MutationObserver`.\n\n**Regression risk: medium.** An unguarded observer fails every case at import.\n</impact>\n\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"state (60-73); init (75-76, 139-144); submit (95-103); sort change (105-108); popstate (126-137); startSearch (165-172); loadPage (180-236); showIdle (342-352); pushUrl (357-368); resolveSort (381-384); module docstring (1-10)\">\n**What changes**\n- **State and load:** add `state.tag`. A URL with `tag` and no `q` means tag mode. `q`+`tag` means `q` wins and `pushUrl(true)` drops `tag` with `replaceState`.\n- **The idle path pushes history at load.** 143 \u2192 `showIdle()` \u2192 `pushUrl()` (351) \u2192 `pushState`. Tag mode needs its own branch before that.\n- **Popstate:** it reads only `q` and `sort` and calls `showIdle()` when `q` is empty, which pushes a new entry during `popstate`. Without changes, back-navigation into a tag page becomes idle and destroys forward history.\n- **Sort change:** it returns early on `!state.query` (106).\n- **`resolveSort`:** it defaults to `relevance` (383) and needs a mode-aware default.\n- **Submit:** it clears `tag` and restores the relevance option. Its empty-submit path (98-100) goes through `showIdle`, which must also clear `state.tag`.\n- **`pushUrl`:** writes `tag` in tag mode and omits `sort` at the mode default.\n- **`loadPage`:** passes `tag` or `q` (193-199).\n- **Status lines:** 226 and 233 change for tag mode. The comment at 231-232 (\"fused candidate pool\") is false in tag mode.\n- **Titles:** `document.title` at 140 and 170.\n- **Errors:** an Engine 400 (a hand-made tag over 64 characters) shows \"Search failed. The Engine may be unavailable.\" (210). Any 503, including the deadline 503, shows the no-index message (205).\n- Call `observeTagRows(results)` once. The `outerHTML` re-renders (290, 295), `removeRows` (335) and the reset (185) are covered by the observer.\n- **Docstring:** line 6.\n- **Paging:** `hasMore` (234) uses `loadedRows < total && rows.length > 0`. With blocks removing rows, `loadedRows` never reaches the exact `total`, so paging stops only on an empty page. That costs one extra request at the end and is harmless.\n\n**What depends on it:** no harness bundles this page. `tests/config.json:405` lists it only for dist.\n\n**Regression risk: medium.** It is an untested multi-handler state machine.\n</impact>\n\n<impact path=\"client/frontend/search.html\" element=\"new tag heading in .search-controls (31-56); #search-sort relevance option (47); CSP (8)\">\n**What changes:** a new heading element (`hidden` by default). The relevance option is toggled from script. The CSP stays as it is and rules out inline chip styles.\n\n**What depends on it:** `requireElement` (39-45) throws on a missing id; the dist byte-comparison test.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"client/frontend/src/search.css\" element=\"optional heading rule\">\n**What changes:** optional styling for the tag heading.\n\n**What depends on it:** `test_frontend_base_css.py`: the search bundle must still open with base.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"client/frontend/src/data/search.ts\" element=\"FetchSearchOptions (24-31); fetchSearchResults (57-91); docstring (1-9)\">\n**What changes:** `q` becomes optional and `tag?: string` is added. 60-61 always sets `q` today, and the function must set exactly one of the two. The cache key `search:${url}` (80) separates tag pages from text pages. The docstring's \"exactly five\" becomes six.\n\n**What depends on it:** callers passing `{q}`:\n- `pages/search/index.ts:193`\n- `test_frontend_blocks.py:68`\n- `test_frontend_feed_params.py:329` (checks the built URL)\n- `test_frontend_reactions.py:113`\n\n**Regression risk: low**, provided `q` behaves exactly as before and an empty `tag` is never set.\n</impact>\n\n<impact path=\"client/frontend/src/types/videos.ts\" element=\"VideoRow (5-62); SearchPayload docstring (70-75)\">\n**What changes:** add `tags?: string[] | null`. The `SearchPayload` docstring says `total` is the fused pool; in tag mode it is the exact match count.\n\n**What depends on it:** type-only.\n\n**Regression risk: none.**\n</impact>\n\n<impact path=\"client/frontend/dist/\" element=\"committed build output: seven HTML pages and assets/\">\n**What changes:** regenerate with `vite build` with no local `dev-pages/about.html`, and commit. The new CSS chunk adds a `<link>` to five pages.\n\n**What depends on it:** `test_frontend_dist.py:24-25` compares asset names and page bytes with a fresh build.\n\n**Regression risk: medium.** A stale dist is a certain red.\n</impact>\n\n<impact path=\"tests/active/test_frontend_base_css.py\" element=\"test at 97-115 (control at 100; base-prefix checks 105-115); docstring 1-3\">\n**What changes:** it fails as soon as `video-card.ts` imports a sheet. The two ways out:\n- Amend it to admit exactly one component bundle, and update the docstring.\n- Change the design, for example chip rules in `base.css` or imported from each page sheet. Either needs the operator's approval.\n\n**Regression risk: high.**\n</impact>\n\n<impact path=\"tests/active/test_frontend_dist.py\" element=\"test at 17-25\">\n**What changes:** no code change. It passes only after a rebuilt and committed dist.\n\n**Regression risk: high** if the rebuild is forgotten.\n</impact>\n\n<impact path=\"tests/active/test_frontend_video_page_similars.py\" element=\"_keys regex (140-142); first-batch regex (153); docstring (4-5); RUNNER globals (75-80)\">\n**What changes**\n- Both regexes match `<a \u2026 similar-card-item \u2026>`. Retarget them to the div, or to `similar-card-link` and the key on the div.\n- The docstring says \"anchors\".\n- The harness has `ResizeObserver` (75) but no `MutationObserver`, and its `querySelectorAll` returns `[]`. Add a stub.\n\n**Regression risk: high** (a known, certain break).\n</impact>\n\n<impact path=\"tests/active/test_frontend_video_page.py\" element=\"RUNNER globals (116), PAGE_RUNNER globals (660-661), tag assertions (4-5, 189, 306-330)\">\n**What changes:** add `MutationObserver` stubs to both harnesses, and add an `href` assertion (`/search.html?tag=\u2026`, no `api` with DEV false).\n\n**Regression risk: medium** (an import-time `ReferenceError` fails every case).\n</impact>\n\n<impact path=\"tests/active/test_frontend_translate.py\" element=\"video-page harnesses (globals 158 and 479; bundles 228 and 550)\">\n**What changes:** both bundle `pages/video-page/index.ts` and lack `MutationObserver`, so add stubs.\n\n**Regression risk: medium.**\n</impact>\n\n<impact path=\"tests/active/test_frontend_videos_page.py\" element=\"HOME_RUNNER globals (63-66); second harness globals (315-316)\">\n**What changes:** add `MutationObserver` stubs to both harnesses, and `ResizeObserver` to the first. Optionally assert that one observer watches `video-cards`.\n\n**Regression risk: medium.**\n</impact>\n\n<impact path=\"tests/active/test_frontend_reactions.py\" element=\"_bundle (106-124)\">\n**What changes:** it bundles `video-card.ts` with no `--loader:.css=empty` (115-121). esbuild then writes `bundle.css` beside the JS and the import must resolve. Adding the flag gives parity with the other bundlers.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/active/test_frontend_video_card.py\" element=\"card assertions; bundle (39)\">\n**What changes:** none is required, since its rows carry no tags. It is the natural home for `renderTagChips` and `tagSearchUrl` unit cases: escaping, empty and missing lists, skipped blank tags, the hidden `+N` marker, DEV-only `api`, and no `style=`.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/active/test_search.py\" element=\"_statements fixture (36-54); _CHILD runner (57-83)\">\n**What changes:** this is where the data-layer tag tests go, on `ENGINE_PY` (18). The INSERT (49) sets no `tags_json`, so the fixture needs it or a sibling file is needed. The `server` namespace (68) has no `statement_timeout_seconds`, so the deadline is 0. Cases to cover:\n- the token path and the fallback path\n- malformed, object and NULL `tags_json`\n- trim and case, including `M\u00daSICA`/`m\u00fasica`\n- the NSFW `total`\n- paging past the end\n- the sorts\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/active/test_similar.py\" element=\"_rows (138-153); test_every_row_carries_the_channel_and_account_the_dataset_holds (156-166)\">\n**What changes:** AC1 needs `tags` on every mode. The parametrisation covers home, random, upnext and search; add trending, popular, recent and following (with a `follows` body). Live tag-route cases go here: the four 400s, the sort echo, `vectorSearch` false, the exact `total`, and NSFW.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/active/conftest.py\" element=\"identity_of (305-312)\">\n**What changes:** a per-mode `tags` comparison needs the stored `tags_json`. Every caller (`test_similar.py:161`, `test_frontend_follows.py:86,89`) reads by key, so adding a key or a sibling helper is safe.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/config.json\" element=\"test_groups: test_similar.py (55+), test_search.py (261-264), test_frontend_video_page.py (228-233), test_frontend_video_page_similars.py (238-241), test_frontend_translate.py (427-435), test_frontend_base_css.py (355-362), test_frontend_dist.py (363-412)\">\n**What changes**\n- Add `engine/server/api/handlers/video.py` to `test_similar.py`'s group, since `similar.py` now uses `tags_from_json`.\n- Add `components/video-card.ts` to the video-page, similars and translate groups.\n- Add the new sheet to the base-css and dist groups.\n- Add `server_config.py` to `test_search.py` if the constant is added.\n- Map any new test file.\n\n**Regression risk: low.** A missed mapping only means a test is not reselected on edit.\n</impact>\n\n<impact path=\"docs/project/adr/0007-nsfw-filter-default-at-request-edge.md\" element=\"Decisions 1-2 (8-17)\">\n**What changes:** nothing is required. The ADR constrains the build: the new function defaults `include_nsfw=True`, and `_handle_search` passes the parsed flag. Decision 2 (17) names only `search_videos`; amending it is optional.\n\n**Regression risk:** forgetting the flag serves NSFW tag results to every visitor.\n</impact>\n</impacts>\n\n<docs_checklist>\n<doc path=\"engine/server/README.md\">\n\"What it does\" (6-28) has no bullet for `GET /api/v1/search/videos`; only line 53 mentions it, for `nsfw`. Add one covering:\n- `q` text search.\n- The exclusive `tag` mode: an exact match after trimming and lowercasing both sides.\n- The 400s: both parameters, a blank tag, a tag over 64 characters, and neither.\n- Sort: relevance or none means newest in tag mode; views and popularity reorder; anything else is 400.\n- `page` and `limit` with the `SEARCH_MAX_LIMIT` cap.\n- `total`: exact and pre-moderation in tag mode, against the 200-candidate pool in text mode.\n- `vectorSearch` is false in tag mode.\n- Every listing row now carries `tags`: in the uploader's order, `[]` for NULL, invalid or non-list values.\n\nExtend line 53 so the NSFW filter also covers tag search.\n</doc>\n<doc path=\"client/README.md\">\n- Line 34: `/api/v1/search/videos` also allowlists `tag`, which is stripped and dropped when empty.\n- Line 29: blocks and reaction marks apply to tag results (no dislike removal, no over-fetch).\n</doc>\n<doc path=\"client/frontend/README.md\">\n- Feed, search and up-next cards show tag chips linking to `/search.html?tag=\u2026`, fitted to one line with a `+N` marker. Video-page tags become links.\n- The search page's tag mode:\n  - the heading and the title format\n  - the \"Showing X of Y videos tagged \u2026\" and \"No videos tagged \u2026\" status lines\n  - relevance hidden, with `published_at` as the default\n  - `tag` and `sort` kept in the URL\n  - a submit leaving tag mode\n  - a URL with both `q` and `tag` reduced to `q`\n- Line 18: \"Showing N of M matched videos.\" applies to text search only.\n- Line 8: the gateway routes list is unchanged.\n</doc>\n<doc path=\"client/frontend/src/data/search.ts\">\nThe module docstring (1-9) says the gateway allowlists \"exactly five query parameters\". It becomes six, with `tag`, and the function sends exactly one of `q` and `tag`.\n</doc>\n<doc path=\"CONTEXT.md\">\nAdd a glossary entry for **Tag** / **tag search**:\n- the uploader's tags as stored in `videos.tags_json`\n- two tags are the same after trimming and lowercasing; language variants stay distinct\n- tag search is the exact-tag mode of the search route, distinct from the full-text match on the `tags_json` FTS column\n</doc>\n<doc path=\"docs/project/roadmap.md\">\nAfter delivery, add a DONE line for issue 42's first plan (tags on cards and exact-tag search) pointing at `docs/project/plans/54-53-tags-on-cards-and-tag.md`. Note that multi-tag narrowing, feed and up-next tag filters, and advanced search remain open.\n</doc>\n<doc path=\"docs/project/issues/42-tags-on-cards-and-tag-search.md\">\nRecord what this plan delivered and what stays open. The issue stays open (`Status: enhancement, needs-triage` at line 3), because the operator expects more plans.\n</doc>\n<doc path=\"docs/project/adr/0007-nsfw-filter-default-at-request-edge.md\">\nOptional: in Decision 2 (line 17), name the new tag-search function as a second `include_nsfw` callee of `_handle_search`.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nclient/frontend/src/tags.css (the new stylesheet imported by components/video-card.ts) with tests/active/test_frontend_base_css.py: `video-card` is already its own Vite chunk, so a CSS import emits a fifth `video-card-*.css` bundle linked from five pages. `test_frontend_base_css.py:100` pins the bundle list to exactly channels/search/video/videos, and 105-115 require each bundle to open with the full base, so the plan as written goes red. The fix needs a test amendment or a design change, and also a rebuilt, committed dist.\nengine/server/data/search.py (the new tag-search function): the correctness of its SQL rests on three things. `json_each` must be guarded inside its argument against malformed or non-array `tags_json`. The explicit trim set must be used. And it depends on Unicode `lower()`, which no Engine connection registers (only `ann_id_of` exists) and which SQLite core folds for ASCII only, so it rests entirely on the env's SQLite build. A mistake gives either a 500 on one bad row or silently ASCII-only matching.\nclient/frontend/src/components/video-card.ts observeTagRows, with every node harness that bundles a page (test_frontend_video_page.py, test_frontend_video_page_similars.py, test_frontend_translate.py, test_frontend_videos_page.py): none defines `MutationObserver`. An unguarded construction throws at import and fails every case in four files, and the similars regexes at 141 and 153 break for certain on the `<a>`\u2192`<div>` change. Separately, stored blank or over-64-character tags (neither writer caps them) produce chips that link to an idle page or a guaranteed 400 unless the helper filters them.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the main checkout (`.worktrees/55` is still absent). I opened: `similar.py` (106-136, 420-486), `data/search.py` (18-172), `handlers/video.py` (150-177), the gateway (`server.py` 100-155), the search page (120-384), `renderSimilarCard` and `applySimilarStatsToDom` in the video page, `video-card.ts`'s imports and `escapeHtml`, `test_frontend_base_css.py`, the similars harness (60-159), `test_frontend_reactions._bundle`, and every observer stub and esbuild call under `tests/active`. Every claim I checked holds as written. The bundles in `test_frontend_blocks`, `test_frontend_feed_params`, `test_frontend_follows`, `test_frontend_upnext_pager` and `test_frontend_channels_page` reach neither `video-card.ts` nor a page that calls `observeTagRows`, so the inventory was right to leave them out. Beyond the inventory I found one real defect in the settled design: the SQL trim set does not match the gateway's `strip()`, although the plan says it does. That defect is the conflict below. The other gap is documentation.\n<question id=\"1\">\n    Mostly yes. The Engine projection, the `tag` branch, the gateway allowlist and the frontend helpers all fit the code as it stands. The import direction is safe, every row source already selects `tags_json`, and the FTS join, NSFW clause and sort map can be reused as they are. Three things will not work as written:\n    - **Base-CSS test.** The new stylesheet imported from `video-card.ts` fails `test_frontend_base_css.py:100` and `:105-115` (already in the inventory).\n    - **Harness stubs.** Seven node harnesses have no `MutationObserver` (already in the inventory).\n    - **New: whitespace-padded tags.** The exact match misses stored tags padded with whitespace other than space, tab, CR or LF, such as NBSP, U+3000, `\\v`, `\\f` or U+0085. The gateway (`server.py:151`) and the Engine run `str.strip()` on the requested tag, which removes all of that. The SQL `trim(j.value, set)` removes only the four named characters. So a chip for `\"linux\\u00a0\"` sends `linux`, the stored side compares `\"linux\\u00a0\"`, and the click never returns the video the chip came from. The plan's own rationale says it chose the explicit set because `strip()` removes all whitespace, but the set it names does not match `strip()`.\n</question>\n<question id=\"2\">\n    Ramifications:\n    - Every listing payload now carries remote-controlled `tags` into three HTML-string sinks. This is already in the inventory, and `escapeHtml` (`video-card.ts:67-84`) covers it as long as every interpolation uses it.\n    - A fifth CSS bundle appears on five pages, and the committed dist must be rebuilt.\n    - The up-next card becomes a `div` wrapping a link. The card padding stops being clickable.\n    - Tag search costs two statements per page. A views-sorted search on the fallback path sorts the whole match set.\n    - Tag mode adds a second state machine to the search page. It is untested, and its `popstate` and idle paths push history today (lines 126-137, 342-352).\n    - The README route docs fall behind (new impact).\n</question>\n<question id=\"3\">\n    Everything in the inventory still applies:\n    - `observeTagRows` must not construct anything at module load.\n    - The node harnesses need `MutationObserver` stubs, and `test_frontend_videos_page`'s first harness also needs a `ResizeObserver` stub.\n    - The similars regexes at 141 and 153 must be retargeted.\n    - `test_frontend_reactions._bundle` needs `--loader:.css=empty`.\n    - The base-CSS contract must be amended, or the sheet placed elsewhere.\n    - `dist/` must be rebuilt and committed.\n    - Text mode must keep `relevance` as its default sort, or vector fusion silently turns off.\n    - The tag branch must sit inside the existing `SearchIndexMissing`\u2192503 handler and pass `_parse_include_nsfw`.\n    - `popstate` and `showIdle` must stop pushing history when entering tag mode.\n\n    New on top of that:\n    - The stored-tag trim set must equal Python's `str.isspace` set.\n    - `engine/server/README.md` and `client/README.md` need the new parameter and the new row key.\n</question>\n<question id=\"4\">\n    What changes for existing behaviour:\n    - Every Engine listing row gains a `tags` array. It is additive and no test pins the row's key set.\n    - Up-next cards are a `div` with an inner link, not a link, and only the inner area navigates.\n    - Feed and search cards with tags grow by one line.\n    - Chips on the video page become links instead of inert spans.\n    - `.tag-chip` moves out of `video.css`, and a new CSS chunk is linked from index, videos, likes, search and video-page.\n    - A search URL carrying both `q` and `tag` is rewritten to the text search.\n    - Text search itself is unchanged: same validation, default sort, candidate pool, `total` meaning and `vectorSearch`.\n</question>\n</summary>\n\n<new_impacts>\nengine/server/data/search.py (new tag-search function, exact check): the inventory's trim note covers only the requested side, by binding the Python-stripped value. On the stored side, `trim(j.value, ' \\t\\r\\n')` leaves NBSP, `\\v`, `\\f`, `\\x1c-\\x1f`, U+0085, U+1680, U+2000-U+200A, U+2028/9, U+202F, U+205F and U+3000 in place, all of which `str.strip()` removes from the request (`client/backend/server.py:151`, and the Engine's own strip). A stored tag padded with any of them never matches its own chip. The fix is to make the SQL trim set exactly the characters for which `str.isspace()` is true, held in one module constant built in Python and bound as a parameter for both trims. That way the request and the stored tags are trimmed by the same set. Cost: a few lines. Risk if missed: low-frequency, silent false negatives that break the requirement that a single-use tag returns its own video.\nclient/frontend/src/components/video-card.ts (renderTagChips blank-skip): JS `String.prototype.trim` and Python `str.strip` disagree. JS leaves U+0085 and `\\x1c-\\x1f`, which Python strips, and strips U+FEFF, which Python leaves. A blank-skip written with JS `trim()` therefore still emits a dead chip for a tag made only of `\\x85`, because the gateway strips it to nothing and the Engine answers \"Missing query parameter q\". The skip test should treat a tag as blank when it contains nothing outside the same whitespace set the Engine trims.\nengine/server/README.md (route docs, lines 9 and 53): the file documents `/api/video`'s `tags` and lists search among the NSFW-filtered listings, but nothing says that listing rows now carry `tags` or that `/api/v1/search/videos` takes `tag` (its 400s, `published_at` default, exact `total`, `vectorSearch` false). Cost: a paragraph. Risk: stale docs only.\nclient/README.md (gateway allowlist, lines 29-34): the per-route allowlist description should mention that `tag` is now accepted on `/api/v1/search/videos`, stripped and dropped when empty like every parameter except `nsfw`, and that tag results get block and like/dislike marks but no over-fetch. Cost: one sentence. Risk: stale docs only.\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nSettled high-level plan, \"Exact check (both paths)\": the trim names an explicit whitespace set of space, tab, CR and LF, \"because ... the gateway's `strip()` removes all whitespace\". Against the settled requirement, Scope \"Tag matching\": the same normalisation applies to the requested tag and to every stored tag, and a tag used only once returns the video it came from. The requested tag always arrives stripped by Python `str.strip()` (gateway `server.py:151`, then the Engine), which removes every `str.isspace` character. The stored tags are trimmed only of the four named characters. So the two sides are not normalised alike, and a chip whose stored tag is padded with NBSP, U+3000, `\\v`, `\\f` or U+0085 cannot find its own video. Resolving it means changing the named trim set to the full `str.isspace` set. That is a one-constant change, but it revises a detail the plan settled, so it goes back to the operator.\n</new_conflicts>\n\n<recommendations>\n1. **Trim set (resolves the conflict).** Replace the four-character SQL trim set with one module constant in `data/search.py`, holding every character for which `str.isspace()` is true. Build it once from `range(sys.maxunicode+1)`, or list its 29 characters literally. Bind it as a parameter to both `trim(j.value, ?)` and `trim(?, ?)`. Add a `test_search.py` case with a stored `\"linux\\u00a0\"` tag that matches a request for `linux`. Cost: about five lines and one test; no runtime cost. Not doing it means accepting silent misses on whitespace-padded tags, which the requirement does not allow.\n2. **Chip blank-skip.** `renderTagChips` should skip any tag that is empty after removing that same whitespace set, mirrored as a JS regex, and should not rely on `String.prototype.trim()`. Over-length tags (more than 64 characters after trimming) are still an open choice from the inventory. Skipping them hides a tag the uploader wrote. Linking them gives a guaranteed 400 that the search page shows as \"Search failed. The Engine may be unavailable.\" My recommendation is to render such tags as a non-link chip, which costs one branch. Skipping is the cheaper alternative if the operator prefers it.\n3. **Base-CSS contract.** There are two ways to resolve it, and the operator should pick one:\n   - Keep the planned sheet and amend `test_frontend_base_css.py` to admit exactly one component bundle that does not open with base. Cost: a test-contract change and its docstring. The sheet must not `@import` base, because a duplicated base in a chunk linked before or after a page sheet can re-override page rules depending on link order.\n   - Put `.tag-chip`, `.card-tags` and the `+N` rules in `base.css`. Cost: the plan changes from \"a sheet the helper imports\" to the shared base, and the chip rules also ship on the channels and about pages, a few hundred bytes. In return there is no new bundle, no test amendment and no new `<link>`, and there is still one copy of the style. This is the smaller change, but it revises the settled plan.\n4. **Test doubles.** `observeTagRows` widens what the page modules call on the observer doubles, so the doubles must record the new calls faithfully; filtering the new call out of their assertions is not acceptable.\n   - **`MutationObserver` stubs.** In `test_frontend_video_page.py` (both harnesses), `test_frontend_video_page_similars.py`, `test_frontend_translate.py` (both) and `test_frontend_videos_page.py` (both), add a stub that captures each instance with its callback, observed target and options, the way the similars harness's `IntersectionObserver` already does. Add one assertion per page that exactly one observer watches the grid (`similar-videos`, `video-cards`), with `childList: true, subtree: true`.\n   - **`ResizeObserver` stubs.** In the harnesses where a stub already exists (video page, similars, translate, the second videos-page harness), make it record its observed targets, so a test can show which chip rows get observed. The first videos-page harness has no `ResizeObserver` stub and needs a recording one.\n   - **Retiring instead.** Retiring a double is the alternative only where a harness never needs to show calls. None of these harnesses qualifies.\n   - **Cost:** about two lines per harness, plus one assertion per page.\n5. **Docs.** Update `engine/server/README.md` and `client/README.md` as listed in new_impacts, and amend ADR-0007 decision 2 to name the tag function beside `search_videos`. Cost: three short edits.\n6. **Accept as planned.** Everything else in the inventory stands as written, in particular the similars regex retarget, `--loader:.css=empty` in `test_frontend_reactions`, the rebuilt and committed dist, the per-mode `tags` tests in `test_similar.py`, and the `tests/config.json` group additions.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation: tags on cards and exact-tag search (issue 42, plan 54)\n\nI read these files before drafting: `data/search.py`, `handlers/similar.py` (1-160, 400-500), `handlers/video.py` (`to_tags_json` and `tags_from_json`), `server_config.py` (the SEARCH block), `client/backend/server.py` (the allowlist), `components/video-card.ts`, `pages/search/index.ts`, `search.html`, `data/search.ts`, `types/videos.ts`, `video.css` (380-609), `videos.css` (`.video-card`, `.video-link`, `.card-actions`), `base.css`, `pages/video-page/index.ts` (tags 290-304, `loadSimilarVideos`, `renderSimilarCard`, `applySimilarStatsToDom`), `pages/videos/index.ts` (55-68), `test_frontend_base_css.py`, `test_search.py`, `test_similar.py` (100-170), `test_frontend_video_page_similars.py` (130-169), and `conftest.identity_of`. The harness grep confirmed that no harness defines `MutationObserver`.\n\n### Decisions that differ from the high-level plan (named)\n\n1. **Chip CSS lives in `base.css`, not in a sheet imported by `video-card.ts`.** The operator approved this on 2026-10-04 via AskUser. A sheet imported from the component would make Vite emit a fifth `video-card-*.css` bundle, which breaks the pinned contract in `test_frontend_base_css.py:100,105-115`. Putting the rules in `base.css` still leaves one copy. It needs no new file and no new bundle, and the test needs no change: `base.css` is already inlined at the head of `videos.css`, `video.css` and `search.css`, and so of every page that shows chips. The channels page also carries about 25 unused lines. As a consequence, `video-card.ts` imports no CSS, and `test_frontend_reactions.py` needs no `--loader:.css=empty`.\n2. **`observeTagRows` does nothing when `MutationObserver` or `ResizeObserver` is undefined.** Every supported browser has both, and only the node harnesses lack them. This replaces adding stubs to five harnesses: `test_frontend_video_page.py` (two harnesses), `test_frontend_video_page_similars.py`, `test_frontend_translate.py` (two harnesses) and `test_frontend_videos_page.py` (two harnesses). Ceiling: no harness exercises the fit. The fit is covered by a dedicated unit case in `test_frontend_video_card.py` that stubs both observers. Upgrade path: stub the observers in a page harness if a page-level fit test is ever wanted.\n3. **Unlinkable stored tags.** A tag that is blank after trimming, or longer than 64 code points, would link to a guaranteed 400 (or to idle). `tagSearchUrl` returns `null` for such a tag.\n   - Cards skip it.\n   - The video page still lists it, as a plain `span.tag-chip` with no link, so the video page keeps listing every tag.\n   - Today no stored tag is over 64 characters (the longest is 30), so in practice only blank tags are affected.\n4. **The `total` count statement leaves out the `channels` LEFT JOIN.** That join cannot remove a row. It could only duplicate one if `channels` held duplicate keys, so leaving it out counts distinct matching videos. The page statement keeps the join, exactly as `lexical_candidates` does.\n5. **The FTS phrase is the `_TOKEN_SPLIT` tokens joined with spaces and quoted as one string literal, as the settled route says.** FTS5 re-tokenizes the literal with the table's own `unicode61` tokenizer, so tokens such as `foo_bar` are split again and the gap with the index shrinks. If every Python token turns out to be a separator to `unicode61`, the phrase is empty and matches nothing. That is the accepted Rt1 risk.\n6. **A popstate into the idle state no longer pushes a history entry.** `showIdle` gains a `updateUrl = true` parameter, and `popstate` passes `false`. This is a pre-existing bug, but the tag-mode `popstate` path runs through the same function, and leaving it in would destroy forward history after back-navigation.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/server_config.py` | + `SEARCH_MAX_TAG_LENGTH = 64` |\n| `engine/server/data/search.py` | + `TAG_TRIM_SQL`, `TAG_MATCH_SQL`, `tag_match_expression`, `search_videos_by_tag`; docstrings |\n| `engine/server/api/handlers/similar.py` | `stable_video_row` adds `tags`; `_handle_search` tag branch; imports; docstrings |\n| `engine/server/api/router.py` | docstring line 11 only |\n| `client/backend/server.py` | allowlist line 104 gains `\"tag\"` |\n| `client/frontend/src/base.css` | + `.tag-chip`, `a.tag-chip:hover`, `.card-tags`, `.card-tags > *`, `.tag-more` |\n| `client/frontend/src/video.css` | \u2212 `.tag-chip`; `.similar-card-item` loses link styling; + `.similar-card-link` |\n| `client/frontend/src/videos.css` | + `.video-card > .card-tags` padding |\n| `client/frontend/src/search.css` | + `.search-tag` |\n| `client/frontend/search.html` | + `<h2 id=\"search-tag\" class=\"search-tag\" hidden></h2>` |\n| `client/frontend/src/components/video-card.ts` | + `tagSearchUrl`, `renderTagChips`, `observeTagRows` (private `fitTagRow`); `renderVideoCard` appends the chip row |\n| `client/frontend/src/types/videos.ts` | `VideoRow.tags?: string[] \\| null`; `SearchPayload` docstring |\n| `client/frontend/src/data/search.ts` | `q?`, `tag?`; sends exactly one; docstring says six parameters |\n| `client/frontend/src/pages/search/index.ts` | tag mode |\n| `client/frontend/src/pages/videos/index.ts` | `observeTagRows(cards)` |\n| `client/frontend/src/pages/video-page/index.ts` | linked tag chips; `renderSimilarCard` div + link + chips; `observeTagRows(similarCards)` |\n| `client/frontend/dist/` | rebuilt with `vite build` (no local `dev-pages/about.html`) and committed |\n\nNo new module, table or dependency.\n\n### Engine\n\n**`server_config.py`**, after line 460:\n\n```python\nSEARCH_MAX_TOKEN_LENGTH = 64\n# Longest tag the exact-tag mode accepts, in characters after trimming; the longest stored tag is 30.\nSEARCH_MAX_TAG_LENGTH = 64\n```\n\n**`data/search.py`**, beside `lexical_candidates`:\n\n```python\n# Whitespace both sides of a tag comparison lose. SQLite's one-argument trim() removes only spaces.\nTAG_TRIM_SQL = \"' ' || char(9, 10, 13)\"\n\n# True when the row's tag list holds the bound tag once both are trimmed and lowercased. The same SQL\n# expression normalises both sides, so they cannot disagree. CASE short-circuits, so json_type and\n# json_each never see malformed JSON (json_each would raise and fail the whole query); non-arrays\n# become an empty list, and only string elements compare.\nTAG_MATCH_SQL = f\"\"\"EXISTS (\n  SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) THEN CASE json_type(v.tags_json) WHEN 'array' THEN v.tags_json ELSE '[]' END ELSE '[]' END) j\n  WHERE j.type = 'text' AND lower(trim(j.value, {TAG_TRIM_SQL})) = lower(trim(?, {TAG_TRIM_SQL}))\n)\"\"\"\n\n\ndef tag_match_expression(tag: str) -> str:\n    \"\"\"Build the FTS5 prefilter for one tag: a column filter on tags_json holding one quoted phrase.\n\n    The phrase is a string literal with its quotes doubled, as in :func:`sanitize_query`, so a tag\n    cannot inject operators. Empty when the tag has no word character, which sends the caller to\n    the full-scan fallback.\n    \"\"\"\n    tokens = [token for token in _TOKEN_SPLIT.split(tag) if token]\n    if not tokens:\n        return \"\"\n    return 'tags_json : \"' + \" \".join(tokens).replace('\"', '\"\"') + '\"'\n\n\ndef search_videos_by_tag(\n    server: Any,\n    tag: str,\n    page: int,\n    limit: int,\n    sort: str = \"published_at\",\n    include_nsfw: bool = True,\n) -> tuple[list[dict[str, Any]], int]:\n    \"\"\"Return one page of the videos carrying ``tag`` exactly, plus the exact match count.\n\n    FTS narrows to the rows whose tags_json holds the tag's words, and :data:`TAG_MATCH_SQL` keeps\n    only true tag matches. A tag with no word character has no FTS token, so it scans every row\n    (about 0.7 s on the full dataset). `total` counts every allowed match, so the page can draw\n    exact paging.\n\n    :param tag: Tag as the caller sent it, already stripped.\n    :param sort: A key of :data:`LEXICAL_SORTS`.\n    :param include_nsfw: False leaves NSFW-flagged rows out of the page and the count.\n    :returns: ``(rows_for_page, total_matches)``.\n    \"\"\"\n    match_expression = tag_match_expression(tag)\n    if match_expression:\n        source = \"videos_fts f JOIN videos v ON v.rowid = f.rowid\"\n        where = f\"videos_fts MATCH ? AND {TAG_MATCH_SQL}\"\n        args: list[Any] = [match_expression, tag]\n    else:\n        source = \"videos v\"\n        where = TAG_MATCH_SQL\n        args = [tag]\n    if not include_nsfw:\n        where += f\" AND {NSFW_ALLOWED_SQL}\"\n    order_by = LEXICAL_SORTS[sort]\n    offset = max(0, (page - 1) * limit)\n\n    conn, lock = search_connection(server)\n    with lock:\n        with search_deadline(server):\n            if not fts_available(conn):\n                raise SearchIndexMissing(\n                    \"videos_fts is not present in this database; run the dataset build's \"\n                    \"sync stage to create it.\"\n                )\n            query = conn.execute(\n                f\"\"\"\n                SELECT\n                {VIDEO_ROW_SQL}\n                FROM {source}\n                LEFT JOIN channels c\n                  ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain\n                WHERE {where}\n                ORDER BY {order_by}\n                LIMIT ? OFFSET ?\n                \"\"\",\n                (*args, limit, offset),\n            )\n            rows = [dict(row) for row in query]\n            total = conn.execute(f\"SELECT COUNT(*) FROM {source} WHERE {where}\", args).fetchone()[0]\n\n    logging.info(\"[search] tag prefilter=%s rows=%d total=%d sort=%s\", bool(match_expression), len(rows), total, sort)\n    return rows, int(total)\n```\n\nInvariants:\n- Every caller value is bound as a parameter. Only module constants are formatted into the SQL.\n- The tag is bound already Python-stripped and the SQL trims it again, so NBSP padding on a direct Engine call still matches and stored tags are normalised the same way.\n- `sort` must be a `LEXICAL_SORTS` key; the handler guarantees this.\n- The function defaults to `include_nsfw=True`, as ADR-0007 decision 1 requires.\n\nDocstrings:\n- The module docstring gains one paragraph: \"The exact-tag mode (`search_videos_by_tag`) is not ranked: it filters to one tag and orders by date, views or popularity.\"\n- The `search_videos` docstring says it covers text search only.\n\n**`handlers/similar.py`**\n- Line 27 becomes `from data.search import LEXICAL_SORTS, SearchIndexMissing, search_videos, search_videos_by_tag`.\n- Add `SEARCH_MAX_TAG_LENGTH` to the `server_config` import.\n- Add `from handlers.video import tags_from_json`. There is no cycle: `router` already imports `handlers.video`, and `video.py` imports only `data.*`, `http_utils` and `server_config`.\n- Docstring line 3: \"hybrid video search\" becomes \"video search (hybrid text, or exact tag)\".\n\n```python\ndef stable_video_row(row: dict[str, Any]) -> dict[str, Any]:\n    \"\"\"Project a row to stable fields returned to clients, plus its tags parsed from tags_json.\"\"\"\n    stable = {field: row.get(field) for field in STABLE_VIDEO_FIELDS}\n    stable[\"tags\"] = tags_from_json(row.get(\"tags_json\"))\n    return stable\n```\n\n`_handle_search`. The docstring becomes: \"Answer a video search request: hybrid text search on `q`, or exact-tag search on `tag`; the two never combine.\" After the `SEARCH_ENABLED` gate:\n\n```python\n        raw_query = (params.get(\"q\", [\"\"])[0] or \"\").strip()\n        tag = (params.get(\"tag\", [\"\"])[0] or \"\").strip()\n        tag_mode = \"tag\" in params\n        if tag_mode and \"q\" in params:\n            respond_json(self, 400, {\"error\": \"Use either q or tag, not both\"})\n            return\n        if tag_mode and not tag:\n            respond_json(self, 400, {\"error\": \"Empty tag parameter\"})\n            return\n        if len(tag) > SEARCH_MAX_TAG_LENGTH:\n            respond_json(self, 400, {\"error\": f\"Tag longer than {SEARCH_MAX_TAG_LENGTH} characters\"})\n            return\n        if not tag_mode and not raw_query:\n            respond_json(self, 400, {\"error\": \"Missing query parameter q\"})\n            return\n\n        sort = params.get(\"sort\", [\"relevance\"])[0] or \"relevance\"\n        if sort not in LEXICAL_SORTS and sort != \"relevance\":\n            respond_json(self, 400, {\"error\": \"Unsupported sort\"})\n            return\n        # Tag results have no relevance to rank by; text search keeps relevance, which switches on its vector half.\n        if tag_mode and sort == \"relevance\":\n            sort = \"published_at\"\n\n        # limit / page parsing unchanged\n\n        # Search never enters _handle_similar, so no request context carries the flag here.\n        include_nsfw = _parse_include_nsfw(params.get(\"nsfw\", [None])[0])\n        try:\n            if tag_mode:\n                rows, total = search_videos_by_tag(self.server, tag, page=page, limit=limit, sort=sort, include_nsfw=include_nsfw)\n            else:\n                rows, total = search_videos(\n                    self.server,\n                    raw_query,\n                    # ... the arguments are unchanged ...\n                    include_nsfw=include_nsfw,\n                )\n        except SearchIndexMissing as exc:\n            # unchanged\n        # moderation unchanged\n        encoder = getattr(self.server, \"query_encoder\", None)\n        respond_json(self, 200, {\n            # ...\n            \"sort\": sort,\n            \"vectorSearch\": bool(not tag_mode and encoder is not None and encoder.enabled),\n            \"rows\": stable_video_rows(filtered_rows),\n        })\n```\n\nNotes on the handler:\n- `parse_qs` drops blank values, so `?tag=` is absent and reaches the \"Missing query parameter q\" branch. `?tag=%20` is present, strips to empty, and gets \"Empty tag parameter\".\n- `?q=%20&tag=x` carries both and gets a 400.\n- The length check runs on the stripped value and counts code points (Python `len`).\n- Text mode is byte-for-byte the previous behaviour.\n\n**`router.py` line 11:** `GET /api/v1/search/videos: hybrid text search (q) or exact-tag search (tag). [rate-limit gate]`\n\n### Gateway\n\n`client/backend/server.py:104` becomes `\"/api/v1/search/videos\": {\"q\", \"page\", \"limit\", \"sort\", \"nsfw\", \"tag\"},`. Everything else is inherited:\n- `tag` is stripped, and dropped when empty.\n- Because the route is in `FILTERED_ROUTES`, blocks and reaction marks apply.\n- `_filter_payload` passes `tags` through.\n\n### Frontend\n\n**`base.css`** (appended after `.visually-hidden`):\n\n```css\n/* Tag chips: the video page's full list and every card's one-line row. Chips are links, so the link look is reset here. */\n.tag-chip {\n  padding: 0.12rem 0.55rem;\n  border-radius: 999px;\n  border: 1px solid var(--line);\n  background: rgba(255, 255, 255, 0.6);\n  color: var(--ink);\n  font-size: 0.8rem;\n  text-decoration: none;\n  white-space: nowrap;\n}\n\na.tag-chip:hover {\n  border-color: var(--accent);\n}\n\n/* One line on a card. observeTagRows in components/video-card.ts hides the chips that do not fit, from the end, and counts them in .tag-more. */\n.card-tags {\n  display: flex;\n  gap: 0.35rem;\n  align-items: center;\n  overflow: hidden;\n  min-width: 0;\n}\n\n/* Only flex-shrink, never display, so the hidden attribute still hides a chip. */\n.card-tags > * {\n  flex-shrink: 0;\n}\n\n.tag-more {\n  color: var(--muted);\n  font-size: 0.8rem;\n  white-space: nowrap;\n}\n```\n\nBefore the fit runs, the row is clipped by `overflow: hidden` and never wraps. No `[hidden]` override is needed, because no chip rule sets `display`.\n\n**`video.css`:**\n- Delete `.tag-chip` (408-415).\n- `.tag-list` stays as it is, with `flex-wrap: wrap`.\n- `.similar-card-item` keeps `display:flex; flex-direction:column; gap:0.5rem; padding; border-radius; border; background; transition` and loses `text-decoration` and `color`.\n- `.similar-card-item:hover` is unchanged.\n- New rule:\n  ```css\n  .similar-card-link {\n    display: flex;\n    flex-direction: column;\n    gap: 0.5rem;\n    text-decoration: none;\n    color: inherit;\n  }\n  ```\n\n**`videos.css`**, after `.card-actions`: `.video-card > .card-tags { padding: 0 1.05rem 0.9rem; }`. This matches the inset of `.card-actions`.\n\n**`search.css`:** `.search-tag { margin: 0 0 0.6rem; font-size: 1.2rem; }`. The sheet still opens with `@import \"./base.css\"`.\n\n**`search.html`:** `<h2 id=\"search-tag\" class=\"search-tag\" hidden></h2>` as the first child of `<section class=\"search-controls\">`. The CSP is unchanged, and no inline style is emitted anywhere.\n\n**`types/videos.ts`:**\n- Add `/** The uploader's tags, in their order; absent on rows cached before the Engine sent them. */ tags?: string[] | null;` to `VideoRow`.\n- The `SearchPayload` docstring now says: \"In text search, `total` counts the fused candidate pool; in tag search it is the exact count of matching videos before moderation and profile filters.\"\n\n**`components/video-card.ts`.** The module docstring gains: \"It also renders the tag chip row every card shows, and fits it to one line.\" New code goes after `videoPageUrl`:\n\n```ts\n/** Longest tag the Engine's tag search accepts (SEARCH_MAX_TAG_LENGTH); a longer one would link to a 400. */\nconst TAG_MAX_LENGTH = 64;\n\n/**\n * Build the link to the search page's results for one tag, or null when the tag cannot be searched (blank, or longer than the Engine accepts).\n *\n * `apiParam` is propagated only in a dev build, by the rule of `videoPageUrl`.\n */\nexport function tagSearchUrl(tag: string, apiParam?: string | null) {\n  const value = tag.trim();\n  // Counted in code points, as the Engine's len() counts them.\n  if (!value || Array.from(value).length > TAG_MAX_LENGTH) return null;\n  const params = new URLSearchParams();\n  params.set(\"tag\", value);\n  if (apiParam && import.meta.env.DEV) params.set(\"api\", apiParam);\n  return `/search.html?${params.toString()}`;\n}\n\n/**\n * Render a card's tag row: one link per searchable tag in the uploader's order, then a hidden `+N` marker that observeTagRows fills.\n *\n * Returns \"\" when there is no tag to show, so a card without tags has no tag line. Tags come from remote instances, so every value is escaped.\n */\nexport function renderTagChips(tags: VideoRow[\"tags\"], apiParam?: string | null) {\n  if (!Array.isArray(tags)) return \"\";\n  const chips = tags.flatMap((tag) => {\n    if (typeof tag !== \"string\") return [];\n    const href = tagSearchUrl(tag, apiParam);\n    return href ? [`<a class=\"tag-chip\" href=\"${escapeHtml(href)}\">${escapeHtml(tag)}</a>`] : [];\n  });\n  if (!chips.length) return \"\";\n  return `<div class=\"card-tags\">${chips.join(\"\")}<span class=\"tag-more\" hidden></span></div>`;\n}\n\n/**\n * Show every chip, then hide chips from the end until the rest and the `+N` marker fit the row's width.\n */\nfunction fitTagRow(row: HTMLElement) {\n  const chips = Array.from(row.querySelectorAll<HTMLElement>(\".tag-chip\"));\n  const more = row.querySelector<HTMLElement>(\".tag-more\");\n  if (!more) return;\n  for (const chip of chips) chip.hidden = false;\n  more.hidden = true;\n  let hidden = 0;\n  while (hidden < chips.length && row.scrollWidth > row.clientWidth) {\n    hidden += 1;\n    chips[chips.length - hidden].hidden = true;\n    more.textContent = `+${hidden}`;\n    more.setAttribute(\"aria-label\", `${hidden} more ${hidden === 1 ? \"tag\" : \"tags\"}`);\n    more.hidden = false;\n  }\n}\n\nlet tagRowResizer: ResizeObserver | null = null;\n/** The width each row was last fitted at, so a height-only change does not re-fit it. */\nconst fittedWidths = new WeakMap<Element, number>();\n\n/**\n * Fit every card tag row that enters `container`, now or later, once it has a layout and again whenever its width changes.\n *\n * Cards reach the grids by innerHTML, insertAdjacentHTML and outerHTML from many places, so one observer per container finds them instead of a call after each render. Outside a browser (the node test harnesses) the observers are absent and this does nothing.\n */\nexport function observeTagRows(container: HTMLElement) {\n  if (typeof MutationObserver === \"undefined\" || typeof ResizeObserver === \"undefined\") return;\n  tagRowResizer ??= new ResizeObserver((entries) => {\n    for (const entry of entries) {\n      const width = entry.contentRect.width;\n      if (fittedWidths.get(entry.target) === width) continue;\n      fittedWidths.set(entry.target, width);\n      fitTagRow(entry.target as HTMLElement);\n    }\n  });\n  const resizer = tagRowResizer;\n  const rowsIn = (node: Node) =>\n    node instanceof HTMLElement\n      ? node.matches(\".card-tags\") ? [node] : Array.from(node.querySelectorAll<HTMLElement>(\".card-tags\"))\n      : [];\n  for (const row of rowsIn(container)) resizer.observe(row);\n  new MutationObserver((records) => {\n    for (const record of records) {\n      record.addedNodes.forEach((node) => rowsIn(node).forEach((row) => resizer.observe(row)));\n      record.removedNodes.forEach((node) => rowsIn(node).forEach((row) => resizer.unobserve(row)));\n    }\n  }).observe(container, { childList: true, subtree: true });\n}\n```\n\nWhy the observers cannot loop:\n- `hidden` toggles are attribute mutations, which the `childList` observer ignores.\n- The marker's text-node change yields no `.card-tags` row.\n- The width memo stops a re-fit after the fit's own height change.\n\nObserver lifetime: there is one shared `ResizeObserver` per page, created lazily, never at module level. The `MutationObserver`s are not stored, because their containers live as long as the page.\n\n`renderVideoCard`: line 416 becomes `</a>${renderTagChips(row.tags, options.apiParam)}${actionsMarkup}`. The chip row sits outside the link, as the sibling just before `card-actions`. The card body is unchanged.\n\n**`pages/videos/index.ts`:** add `observeTagRows` to the import. After the guard at 66-68, add `observeTagRows(cards);`. The delegated click handler acts only on `[data-card-action]`, so a chip click is a plain link.\n\n**`pages/video-page/index.ts`:**\n- Import `observeTagRows`, `renderTagChips` and `tagSearchUrl` from `../../components/video-card`.\n- After the `params` declaration (82): `if (similarCards) observeTagRows(similarCards);`\n- Tag chips (290-300):\n\n```ts\n      // Tags come from remote instances, so each chip is built from text, never from markup; a tag the search cannot take stays a plain chip.\n      tagsEl.replaceChildren(\n        ...tags.map((tag) => {\n          const href = tagSearchUrl(tag, params.get(\"api\"));\n          const chip = document.createElement(href ? \"a\" : \"span\");\n          chip.className = \"tag-chip\";\n          chip.textContent = tag;\n          if (href) (chip as HTMLAnchorElement).href = href;\n          return chip;\n        })\n      );\n```\n\n`renderSimilarCard`:\n\n```ts\n  return `\n    <div class=\"similar-card-item\"${keyAttribute}>\n      <a class=\"similar-card-link\" href=\"${escapeHtml(videoPageUrl(row))}\">\n        <div class=\"similar-thumb\">\n          ${thumbMarkup}\n          <span class=\"duration\">${escapeHtml(duration)}</span>\n        </div>\n        <h4 class=\"similar-title\">${escapeHtml(title)}</h4>\n        <p class=\"similar-channel\">${escapeHtml(channel)}</p>\n        <p class=\"similar-meta\"><span data-stat=\"views\">${formatStatValue(views)}</span> views${escapeHtml(timeSuffix)}</p>\n        ${reactionMarkup}\n      </a>\n      ${renderTagChips(row.tags, params.get(\"api\"))}\n    </div>\n  `;\n```\n\n`applySimilarStatsToDom` still finds `[data-video-key]` (now on the div) and the `data-stat=\"views\"` span inside it.\n\n**`data/search.ts`:**\n- Docstring: \"exactly six query parameters (`q`, `tag`, `page`, `limit`, `sort`, `nsfw`)\". It now also says: \"A request carries exactly one of `q` and `tag`.\"\n- `FetchSearchOptions` becomes `q?: string; tag?: string;`.\n- In `fetchSearchResults`:\n\n```ts\n  const tag = (options.tag ?? \"\").trim();\n  // Exactly one of the two: the Engine answers 400 to both. Without a tag, q is sent exactly as before.\n  if (tag) url.searchParams.set(\"tag\", tag);\n  else url.searchParams.set(\"q\", (options.q ?? \"\").trim());\n```\n\nThe cache key `search:${url}` keeps tag pages apart from text pages.\n\n**`pages/search/index.ts`** (tag mode):\n- The module docstring line 6 becomes: \"...until the Engine's candidate pool (text) or match set (tag) is exhausted. A `tag` in the URL, with no `q`, lists the videos carrying that exact tag; submitting the box leaves tag mode.\"\n- New elements and the `TAG_DEFAULT_SORT` constant:\n\n```ts\nconst tagHeading = requireElement<HTMLElement>(\"search-tag\");\nconst relevanceOption = sortSelect.querySelector<HTMLOptionElement>('option[value=\"relevance\"]');\nif (!relevanceOption) throw new Error(\"Missing search page element: relevance sort option\");\nconst TAG_DEFAULT_SORT: SearchSort = \"published_at\";\n```\n\n- `state`:\n  - `query: (params.get(\"q\") ?? \"\").trim()`\n  - new `tag: \"\"`\n  - `sort: \"relevance\" as SearchSort`\n  - After the declaration: `state.tag = state.query ? \"\" : (params.get(\"tag\") ?? \"\").trim(); state.sort = resolveSort(params.get(\"sort\"), Boolean(state.tag));`. A URL carrying both keeps `q`.\n- Remove `input.value = \u2026; sortSelect.value = \u2026;` (75-76). `applyMode()` does both.\n- Submit: `startSearch(next, \"\", state.sort);`. The relevance option comes back through `applyMode`. A tag-mode sort (published_at, views or popularity) is valid in text mode too. An empty submit calls `showIdle()`, which also clears `tag`.\n- Sort change:\n\n```ts\nsortSelect.addEventListener(\"change\", () => {\n  if (!state.query && !state.tag) return;\n  startSearch(state.query, state.tag, resolveSort(sortSelect.value, Boolean(state.tag)));\n});\n```\n\n- After the results click listener: `observeTagRows(results);`. This covers the reset, appends, `outerHTML` re-renders and `removeRows`.\n- `popstate`:\n\n```ts\nwindow.addEventListener(\"popstate\", () => {\n  const current = new URLSearchParams(window.location.search);\n  state.query = (current.get(\"q\") ?? \"\").trim();\n  state.tag = state.query ? \"\" : (current.get(\"tag\") ?? \"\").trim();\n  state.sort = resolveSort(current.get(\"sort\"), Boolean(state.tag));\n  if (!state.query && !state.tag) {\n    // The address bar already holds this entry; pushing would drop the forward history.\n    showIdle(false);\n    return;\n  }\n  applyMode();\n  void loadPage(1, true);\n});\n```\n\n- Initial load:\n\n```ts\nif (state.query || state.tag) {\n  applyMode();\n  // A hand-made URL carrying both keeps q; drop tag so the Engine never sees the pair it refuses.\n  if (state.query && params.has(\"tag\")) pushUrl(true);\n  void loadPage(1, true);\n} else {\n  showIdle();\n}\n```\n\n- `startSearch(query: string, tag: string, sort: SearchSort)` sets `query`, `tag`, `sort` and `page = 1`, then runs `applyMode(); pushUrl(); void loadPage(1, true);`.\n- New `applyMode()`:\n\n```ts\n/**\n * Show the mode the state is in: the tag heading, the sort menu (no relevance for tag results), the box and the title.\n */\nfunction applyMode() {\n  const tagMode = Boolean(state.tag);\n  relevanceOption.hidden = tagMode;\n  relevanceOption.disabled = tagMode;\n  tagHeading.hidden = !tagMode;\n  tagHeading.textContent = tagMode ? `Videos tagged \"${state.tag}\"` : \"\";\n  input.value = state.query;\n  sortSelect.value = state.sort;\n  document.title = tagMode\n    ? `${state.tag} - Tag - Search - PeerTube - Browser`\n    : state.query\n      ? `${state.query} - Search - PeerTube - Browser`\n      : \"Search - PeerTube - Browser\";\n}\n```\n\n- `loadPage`:\n  - Fetch with `fetchSearchResults({ q: state.query, tag: state.tag, page, limit: PAGE_SIZE, sort: state.sort, apiBase: apiParam })`.\n  - Empty result: `setStatus(state.tag ? \\`No videos tagged \"${state.tag}\".\\` : \\`No results for \"${state.query}\".\\`);`.\n  - Results: `setStatus(state.tag ? \\`Showing ${state.loadedRows} of ${state.total} videos tagged \"${state.tag}\".\\` : \\`Showing ${state.loadedRows} of ${state.total} matched videos.\\`);`.\n  - The comment at 231-232 becomes: \"In text search `total` is the fused candidate pool, not a corpus count; in tag search it is the exact match count before moderation and blocks.\"\n  - `hasMore` is unchanged.\n  - All status text goes through `textContent`.\n- `showIdle(updateUrl = true)`:\n  - Also clears `state.tag`.\n  - Calls `applyMode()` in place of the title line. Its `sort` is kept as `state.sort` when valid in text mode, which is always.\n  - Calls `pushUrl()` only when `updateUrl` is true.\n- `pushUrl`:\n\n```ts\n  if (state.query) next.set(\"q\", state.query);\n  else if (state.tag) next.set(\"tag\", state.tag);\n  if (state.sort !== (state.tag ? TAG_DEFAULT_SORT : \"relevance\")) next.set(\"sort\", state.sort);\n```\n\n- `resolveSort(value, tagMode = false)`:\n\n```ts\nfunction resolveSort(value: string | null, tagMode = false): SearchSort {\n  const candidate = (value ?? \"\").trim() as SearchSort;\n  // Tag results have no relevance; it means newest there, as the Engine reads it.\n  if (!SORTS.includes(candidate) || (tagMode && candidate === \"relevance\")) return tagMode ? TAG_DEFAULT_SORT : \"relevance\";\n  return candidate;\n}\n```\n\nLimitation (named): a hand-made tag over 64 characters reaches the Engine, gets a 400, and the page shows the generic \"Search failed\" line.\n\n### What the build must test\n\nEngine data layer: extend `tests/active/test_search.py`, or add a sibling `test_search_tags.py` with its own fixture. Either way the reads run on `ENGINE_PY` through the real `sqlite3`.\n- The fixture holds rows whose `tags_json` is:\n  - `[\"Linux\",\" linux \",\"x\"]`\n  - `[\"LINUX\"]`\n  - `[\"linuxmint\"]`\n  - `[\"M\u00daSICA\"]` against `[\"m\u00fasica\"]`\n  - `[\"???\"]`\n  - `[\"\\t???\\n\"]`\n  - malformed `[`\n  - an object `{\"a\":\"linux\"}`\n  - `[1, \"linux\"]` with a non-text element\n  - NULL\n  - an NSFW row tagged linux\n  - a row whose description says linux but whose tags do not\n- Cases:\n  1. `linux` matches exactly the rows carrying linux under trim and case. `linuxmint`, description-only, malformed, object and NULL rows are absent, and the malformed row raises nothing.\n  2. `m\u00fasica` matches `M\u00daSICA`, which is the Unicode `lower()` check. If it fails, the SQLite build folds ASCII only.\n  3. `???` takes the fallback (assert `tag_match_expression(\"???\") == \"\"`) and matches both stored forms.\n  4. Default order is `published_at DESC, video_id DESC`, and `views` and `popularity` follow `LEXICAL_SORTS`.\n  5. With `include_nsfw=False`, the NSFW row is missing from both the rows and `total`.\n  6. Paging: pages cover the match set with no overlap; a page past the end gives `[]` and the full `total`.\n  7. With no `videos_fts`, the function raises `SearchIndexMissing`.\n  8. `tag_match_expression('a\"b')` quotes safely.\n\nEngine route (`test_similar.py`, live Engine):\n- AC1:\n  - Extend the `route` parametrisation to trending, popular, recent and following (with a `follows` body) as well as home, random, upnext and search.\n  - Every row has `tags` as a list of strings equal to `tags_from_json` of the stored `tags_json`.\n  - Add a `tags_json` read beside `identity_of` in `conftest.py`.\n- AC7: 400 with a JSON `error` for:\n  - `q`+`tag`\n  - `tag=%20`\n  - a 65-character tag\n  - no parameter (`?tag=` included)\n- AC4: a stored tag fetched with `?tag=<Upper-cased>`:\n  - every row carries it\n  - `sort` echoes `published_at` for none and relevance\n  - `views` reorders\n  - `sort=bogus` gives 400\n  - `vectorSearch` is false\n- AC5: `total` equals a direct `COUNT` on `whitelist.db` under `nsfw` off, and text search's `total` stays \u2264 200.\n\nGateway (`test_server.py` or the blocks test): `tag` is forwarded, and a blocked channel's video is missing from tag results.\n\nFrontend unit (`test_frontend_video_card.py`):\n- `tagSearchUrl`:\n  - encoding (`a b&c` gives `tag=a+b%26c`)\n  - `api` present only with DEV\n  - `null` for a blank tag and for a 65-code-point tag\n- `renderTagChips`:\n  - `\"\"` for undefined, null, `[]` and blank-only lists\n  - `<script>` arrives escaped\n  - there is no `style=`\n  - the marker is `hidden`\n  - chip order is the uploader's\n- `renderVideoCard`: the `.card-tags` row sits after `</a>` and never inside `video-link`.\n- Fit (stub `ResizeObserver`/`MutationObserver` and widths): five chips with room for two give two visible chips, `+3` and `aria-label=\"3 more tags\"`; a wider row re-fits.\n\nFrontend pages:\n- `test_frontend_video_page.py`: the chips are `a.tag-chip` with `href=/search.html?tag=\u2026` and no `api` when DEV is false.\n- `test_frontend_video_page_similars.py`:\n  - Retarget both regexes to `<div \u2026 similar-card-item \u2026>`, which still carries `data-video-key`.\n  - The docstring's \"anchors\" becomes \"cards\".\n\nBuild:\n- `test_frontend_base_css.py` and `test_frontend_dist.py` pass unchanged after `dist` is rebuilt.\n- There is no search-page harness. Tag mode is checked by hand: load, sort, back, reload, submit, and a `q`+`tag` URL.\n\n`tests/config.json` mappings:\n- `engine/server/api/handlers/video.py` \u2192 the `test_similar.py` group.\n- `components/video-card.ts` \u2192 the video-page, similars and translate groups.\n- `src/base.css` \u2192 already in base-css and dist; confirm.\n- `server_config.py` \u2192 `test_search.py`.\n- Any new test file gets its own mapping.\n\n### Check against the plan and the requirements\n\n| Item | Met by |\n|---|---|\n| AC1 | `stable_video_row` + `tags_from_json`; both callers (search, `_respond_rows`) |\n| AC2 | `renderTagChips` + `observeTagRows`/`fitTagRow`; escape; `\"\"` on no tags; measured after insertion and on width change |\n| AC3 | `a.tag-chip` outside every video link; `/search.html?tag=` via `URLSearchParams`; DEV-only `api` |\n| AC4 | `TAG_MATCH_SQL` normalises both sides in SQL; relevance/none \u2192 `published_at`; bad sort 400 |\n| AC5 | `LIMIT/OFFSET` + `COUNT(*)` before moderation; text pool untouched |\n| AC6 | `include_nsfw` from `_parse_include_nsfw`; shared moderation; route already in `FILTERED_ROUTES` |\n| AC7 | four 400 branches |\n| AC8 | heading, title, relevance hidden, URL `tag`/`sort` with newest omitted, sort and popstate in tag mode, submit leaves tag mode, allowlist |\n| AC9 | `tag_match_expression` \u2192 `\"\"` \u2192 full scan |\n| Consistency | `escapeHtml` on every interpolation; `textContent` for DOM chips; no new table, dependency or module |\n\nConverged in one pass. The deviations are the six decisions named at the top; only the first changes an approved design, and the operator approved it.\n\n### Documentation the build updates\n\nThese are the settled items. With chips in `base.css`, `client/frontend/README.md` gains a line saying the chip rules live in the shared base.\n- `engine/server/README.md`:\n  - a search route bullet (`q`/`tag`, the 400s, sorts, `total`, `vectorSearch`, `tags` on every row)\n  - line 53 extended to say the NSFW filter covers tag search\n- `client/README.md`, lines 29 and 34.\n- `client/frontend/README.md`:\n  - card chips, linked video-page chips, search tag mode\n  - line 18 scoped to text search\n- `data/search.ts` docstring (above).\n- `CONTEXT.md`: a **Tag** / **tag search** entry.\n- `docs/project/roadmap.md`: a DONE line plus the open items.\n- `docs/project/issues/42-\u2026md`: what was delivered and what stays open; the status is unchanged.\n- ADR-0007 Decision 2 (optional): name `search_videos_by_tag`.\n\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: `search_videos_by_tag` in `engine/server/data/search.py`, called on `ENGINE_PY` through the real `sqlite3` (rung 1). It follows the subprocess harness in `tests/active/test_search.py` (`_statements` + `_CHILD` run via `subprocess.run([ENGINE_PY, \"-c\", ...])`), in a sibling `tests/active/test_search_tags.py` that has its own fixture. The fixture's rows have these `tags_json` values: `[\"Linux\",\" linux \",\"x\"]`, `[\"LINUX\"]`, `[\"linuxmint\"]`, `[\"M\u00daSICA\"]`, `[\"???\"]`, `[\"\\t???\\n\"]`, malformed `[`, the object `{\"a\":\"linux\"}`, `[1,\"linux\"]`, NULL, an NSFW row tagged linux, and a row with linux only in its description. It also has a `videos_fts` built over them.\n\nFor C1:\n- `linux` returns exactly the rows that carry it after trimming and lowercasing, `[1,\"linux\"]` included through its text element. The linuxmint, description-only, malformed, object and NULL rows are absent, and the malformed row raises nothing.\n- `m\u00fasica` returns the `M\u00daSICA` row through the real search connection. If it fails, the SQLite build only folds ASCII.\n- `tag_match_expression(\"???\") == \"\"`, and `???` returns both the `[\"???\"]` row and the `[\"\\t???\\n\"]` row through the full-scan fallback.\n- `tag_match_expression('a\"b')` holds the doubled quote inside one phrase, and the query runs without an FTS syntax error.\n\nFor C2:\n- `total` equals the number of matching rows on page 1, on a later page, and on a page past the end (which returns `[]`).\n- Walking every page covers the match set with no overlap.\n- With `include_nsfw=False`, the NSFW row is missing from both the rows and `total`.\n\nInner unit, by exception: with no `videos_fts`, the function raises `SearchIndexMissing`.</checkpoint>\n<name>Engine exact-tag data layer</name>\n<intent>`engine/server/data/search.py` gains `search_videos_by_tag`. It returns one page of the videos whose `tags_json` holds the requested tag, with the same SQL trim-and-lowercase applied to both the stored tags and the requested one, together with the exact count of the matches the NSFW setting allows.</intent>\n<clause_1>The rows `search_videos_by_tag` returns are exactly the videos that carry the tag once both sides are trimmed and lowercased by the same SQL expression. This holds whether the FTS prefilter or the no-token full scan finds them.</clause_1>\n<clause_2>The `total` that `search_videos_by_tag` returns counts every match the NSFW setting allows, whatever page is requested.</clause_2>\n<files>engine/server/api/server_config.py (EDITED), engine/server/data/search.py (EDITED), tests/active/test_search_tags.py (NEW), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the live Engine over HTTP, through the `engine` and `dataset` fixtures in `tests/active/test_similar.py` (rung 2). It follows `test_every_row_carries_the_channel_and_account_the_dataset_holds` (line 156) and its `identity_of` read in `conftest.py`, which gains a `tags_json` read beside it.\n\nFor C1:\n- The route parametrisation is upnext and search plus every mode in the production `FEED_MODES`, read at run time as the existing `UNORDERED`/`ORDERED` readers do. Following sends a `follows` body.\n- Every row on every route has `tags` as a list of strings equal to `tags_from_json` of that video's stored `tags_json`.\n\nFor C2, the positive half: a stored tag is requested as `?tag=<upper-cased>`.\n- Every row carries the tag after trimming and case-folding.\n- `sort` echoes `published_at` with no sort given and with `sort=relevance`.\n- `sort=views` returns the rows in views order.\n- `vectorSearch` is false.\n- With nsfw off, `total` equals a direct `COUNT` on `whitelist.db`.\n- Text search's `total` stays at or below 200.\n\nFor C2, the negative half: each of these gets a 400 whose JSON body has an `error`: `q`+`tag`, `tag=%20`, a 65-character tag, no parameter, `?tag=` and `sort=bogus` with a tag.\n\nThe existing route tests have to stay green.</checkpoint>\n<name>Engine tags on rows and tag route</name>\n<intent>`stable_video_row` in `handlers/similar.py` gives every row the Engine serves a `tags` list. `_handle_search` answers a lone, well-formed `tag` on `/api/v1/search/videos` from `search_videos_by_tag`, and refuses any other tag request with a 400.</intent>\n<clause_1>Every row that upnext, search and each feed mode serve carries `tags` equal to its stored `tags_json` as parsed by `tags_from_json`.</clause_1>\n<clause_2>`/api/v1/search/videos` answers a lone, non-blank `tag` of at most 64 characters with the videos carrying that tag in the resolved sort, and answers every other tag request with a 400.</clause_2>\n<files>engine/server/api/handlers/similar.py (EDITED), engine/server/api/router.py (EDITED), tests/active/test_similar.py (EDITED), tests/active/conftest.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the read gateway, through the `engine_client` fixture in `tests/active/test_blocks.py` (rung 2). It follows `test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page`, which already runs over the search surface `SEARCH`.\n\nA tag is picked that is carried by at least two channels' videos, read from the dataset at run time.\n- A profile that blocks one of those channels sends `GET /api/v1/search/videos?tag=<tag>` through the gateway. It gets 200 with rows that all carry the tag (taken from each row's `tags`) and none from the blocked channel.\n- A second profile without the block sends the same request and gets the blocked channel's video. This proves that `tag` was forwarded and that the block, not the query, removed the row.\n- Without `tag` in the allowlist, the gateway would drop it and the Engine would answer 400, so the 200 with tagged rows is the forwarding assertion.</checkpoint>\n<name>Gateway forwards tag search</name>\n<intent>The read gateway in `client/backend/server.py` forwards `tag` on `/api/v1/search/videos`, so a profile's tag search reaches the Engine and comes back with that profile's blocks applied.</intent>\n<clause_1>A tag search sent through the read gateway returns the videos carrying the tag, minus those of a channel the profile blocks.</clause_1>\n<files>client/backend/server.py (EDITED), tests/active/test_blocks.py (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>Seam: `components/video-card.ts`, bundled by esbuild and run in node (rung 1). It follows `tests/active/test_frontend_video_card.py` and its `bundle` fixture, which has `--define:import.meta.env.DEV=false`; a second bundle uses `DEV=true`. The page-level placement extends the existing node harnesses `test_frontend_video_page.py` and `test_frontend_video_page_similars.py`.\n\nFor C1:\n- `tagSearchUrl(\"a b&c\")` gives `/search.html?tag=a+b%26c`, and `api` is present only in the DEV bundle.\n- `tagSearchUrl` returns null for a blank tag and for a 65-code-point tag.\n- `renderTagChips` returns `\"\"` for undefined, null, `[]` and a blank-only list.\n- A `<script>` tag arrives escaped, and there is no `style=`.\n- Chips come in the uploader's order, and each `href` equals `tagSearchUrl` of its tag.\n- An unsearchable tag gets no chip on a card.\n- The `+N` marker is present and `hidden`.\n- In `renderVideoCard`, the `.card-tags` row comes after the closing `</a>` of `video-link`, with no chip inside the link.\n- In the similars harness, the `.card-tags` row is a sibling after `a.similar-card-link` inside `div.similar-card-item`, which still carries `data-video-key`. Both regexes are retargeted to the div.\n- In the video-page harness, the tags are `a.tag-chip` elements with `href=/search.html?tag=\u2026` and no `api` when DEV is false. A blank stored tag is a `span.tag-chip`.\n\nFor C2:\n- `ResizeObserver` and `MutationObserver` are stubbed, along with `scrollWidth` and `clientWidth`.\n- A row of five chips with room for two shows two chips and the marker reading `+3`, with `aria-label=\"3 more tags\"`.\n- Widening the row re-fits it to more visible chips with a smaller `+N`.\n- A row where everything fits keeps the marker hidden.</checkpoint>\n<name>Linked tag chips and one-line fit</name>\n<intent>Every tag chip shown on the feed, search, up-next and video pages is an `a.tag-chip` linking to `/search.html?tag=\u2026` outside any video link, and `observeTagRows` fits each card's chip row to one line, hiding chips from the end behind a `+N` marker.</intent>\n<clause_1>Every tag chip shown on feed, search, up-next cards and on the video page is a link to its `tagSearchUrl` and is never inside a video link.</clause_1>\n<clause_2>A card's chip row hides chips from the end until the rest and a `+N` marker fit its width, and it re-fits when that width changes.</clause_2>\n<files>client/frontend/src/components/video-card.ts (EDITED), client/frontend/src/types/videos.ts (EDITED), client/frontend/src/base.css (EDITED), client/frontend/src/video.css (EDITED), client/frontend/src/videos.css (EDITED), client/frontend/src/pages/videos/index.ts (EDITED), client/frontend/src/pages/video-page/index.ts (EDITED), tests/active/test_frontend_video_card.py (EDITED), tests/active/test_frontend_video_page.py (EDITED), tests/active/test_frontend_video_page_similars.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"5\" kind=\"code\">\n<checkpoint>Seam: `pages/search/index.ts`, bundled with `data/search.ts` and run in node on recording elements with a stub `fetch` and a recording `history` (`pushState`/`replaceState`) (rung 1/2). This goes in a NEW `tests/active/test_frontend_search_page.py`, following `HOME_RUNNER` and its element factory in `tests/active/test_frontend_videos_page.py`. It replaces the draft's manual check, which the operator approved.\n\nFor C1, each of three entries into tag mode is checked:\n- the initial load of `?tag=Linux`\n- a sort change to `views` while in tag mode\n- a `popstate` into `?tag=Linux&sort=views` from a text-search entry\n\nFor each entry:\n- The request URL carries `tag=Linux` and no `q`.\n- `#search-tag` is shown and its text names the tag.\n- `document.title` is `Linux - Tag - Search - PeerTube - Browser`.\n- The relevance option is both `hidden` and `disabled`.\n- The pushed URL leaves `sort` out at `published_at` and writes `sort=views` after the change.\n- The status line reads `Showing X of Y videos tagged \"Linux\".`. An empty answer reads `No videos tagged \"Linux\".`.\n- A `popstate` to a bare `/search.html` pushes no history entry.\n\nFor C2:\n- A box submit from tag mode sends a request carrying `q` and no `tag`, pushes a URL with no `tag`, re-enables and shows the relevance option, and hides the heading.\n- A load of `?q=music&tag=Linux` sends `q=music` with no `tag`, and calls `replaceState` with a URL that has no `tag`.\n\nAfter `dist` is rebuilt, `test_frontend_base_css.py` and `test_frontend_dist.py` pass unchanged.</checkpoint>\n<name>Search page tag mode</name>\n<intent>`pages/search/index.ts` runs a URL that carries a `tag` and no `q` in tag mode, through `fetchSearchResults` sending only `tag`, and a `q`, whether submitted from the box or present in the URL, always replaces tag mode with a text search.</intent>\n<clause_1>A load, a sort change or a back-navigation into a tag URL shows that tag's results in tag mode, requested with `tag` and without `q`.</clause_1>\n<clause_2>Whenever a `q` is present, whether submitted from the box or in the URL, the page runs a text search and `tag` leaves both the request and the URL.</clause_2>\n<files>client/frontend/src/pages/search/index.ts (EDITED), client/frontend/src/data/search.ts (EDITED), client/frontend/src/types/videos.ts (EDITED), client/frontend/search.html (EDITED), client/frontend/src/search.css (EDITED), client/frontend/dist/ (REBUILT), tests/active/test_frontend_search_page.py (NEW), tests/config.json (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nThere are five phases where the rule allows four, and the operator approved this through AskUser. The build crosses three layers, and every phase is kept to one seam that an existing harness already enters. The data layer needs its own fixture for the edge cases (malformed, object and non-text `tags_json`, Unicode `lower`, the no-token fallback), and the live dataset cannot provide that, so it is split from the route, which is checked against the live Engine in `test_similar.py`. The gateway's change is one allowlist entry, but its proof (forwarding plus blocks) enters a different boundary, `engine_client` in `test_blocks.py`. Folding it into P2 would have given P2 a third fact and a second seam. The frontend splits on its own seam: the chip helper and card placement (the `video-card.ts` node bundle plus the existing page harnesses) and the search page's tag mode. The draft planned to check the search page by hand. Instead it gets a new node harness following `HOME_RUNNER` in `test_frontend_videos_page.py`, so tag mode becomes an executable checkpoint rather than an unverifiable clause. P1 to P3 go in dependency order (data, then route, then gateway), and P4 only needs P2's `tags`. The `dist` rebuild sits in P5, the last frontend phase, so it is built once. The universal \"every feed mode\" in P2 is parametrised over the production `FEED_MODES` at run time, as the existing readers in `test_similar.py` do. Documentation (READMEs, `CONTEXT.md`, the roadmap, the issue, ADR-0007) gets no phase and is left to Step 9.\n</rationale>"
  },
  "requirements": "### Source issue\n\n`docs/project/issues/42-tags-on-cards-and-tag-search.md` (Status: enhancement, needs-triage). It asks for three things: tags on video cards in the feeds, up-next and search; narrowing a feed or search to one or more tags; and an advanced search that takes tag criteria alongside the text query. The measured catalogue figures (2026-10-02) are in the issue under \"What the catalogue holds\". This plan covers only part of the issue (see Scope), and the operator expects the issue to need more than one plan.\n\n### Purpose\n\nTwo goals, from the operator (2026-10-04):\n\n- **More of the same:** a visitor who sees the tags on a video they like can click one to find more videos like it.\n- **Narrower results:** filtering results by a tag gets the visitor more of what they are looking for.\n\n### Scope\n\nAll set by the operator, 2026-10-04.\n\n- **In this plan:** every video card shows the video's tags. Clicking a tag opens search results narrowed to the videos carrying that exact tag. This needs a new exact-tag filter (`tag` parameter) on the Engine's search route `/api/v1/search/videos`.\n- **Cards that show tags:** feed cards and search cards (`renderVideoCard` in `client/frontend/src/components/video-card.ts`, shared by `pages/videos` and `pages/search`) and up-next cards on the video page (`renderSimilarCard` in `client/frontend/src/pages/video-page/index.ts`). Both renderers change.\n- **Tag matching:** two tags are the same when they are equal after trimming and lowercasing, so 'Linux', ' linux ' and 'LINUX' all match. The same normalisation applies to the requested tag and to every stored tag. Language variants such as 'music' and 'musique' stay distinct, and no variant map is kept.\n- **Which tags show:** every tag on the video, as the uploader wrote it. There is no use-count cutoff and no stoplist, so clicking a tag used only once returns only the video it came from.\n- **Tags per card:** as many chips as fit on one line, in the uploader's order, followed by a `+N` marker counting the tags that did not fit. The video page already lists every tag.\n- **Clickable tags:** a tag chip on a feed card, search card, up-next card or the video page opens the exact-tag results for that tag.\n- **Tag results:** a tag click opens the search page with the tag in its URL and no text query. The page names the tag and lists the videos carrying it, newest first. Its existing sort menu switches the order to views or popularity.\n- **Leaving tag results:** submitting the search box from the tag results runs an ordinary text search and removes the tag from the URL. Text and tag never combine in this plan.\n- **Storage:** route Rt1, the FTS prefilter plus an exact check, with no new table (see Chosen route).\n- **Later plans, not this one:** a filter control for narrowing any search by tags; tag filtering in the home feeds (Trending, Recent, Popular, the Recommendations mix) and in up-next; advanced search.\n- **Out of scope:** category on cards or as a filter; per-tag counts; fetching tags for the 44,100 videos whose `tags_json` is NULL (that belongs to the dataset build's tags stage). A video with NULL tags shows no tags and appears in no tag results.\n\n### Chosen route: Rt1, FTS prefilter plus exact check, no new storage\n\nA tag request runs an FTS5 column match on `videos_fts.tags_json` (`tags_json : \"<tag>\"`, with the tag quoted as a string literal so it cannot inject FTS operators, following `sanitize_query` in `engine/server/data/search.py`) to get candidates. It keeps only the rows whose `tags_json` list holds the tag after trimming and lowercasing (a `json_each` comparison), and orders them by the requested sort. A tag that yields no FTS token (no word character, such as `???`, `:'(` or an emoji) falls back to a full `json_each` scan with no prefilter. That scan was measured at 0.71 s for `linux` with a warm cache, inside the Engine's 5 s statement deadline (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`, `engine/server/api/server_config.py`). The new query sits in the data layer beside `lexical_candidates` in `engine/server/data/search.py`, and it reuses that module's `LEXICAL_SORTS` orderings and its NSFW clause (`NSFW_ALLOWED_SQL`).\n\nRejected alternatives: Rt2, a normalised `video_tags` table, which needs a migration and a second derived copy of `tags_json`, and which this plan's speed target does not need (it may come back with the later facet and filter plans); Rt3, `LIKE` over `tags_json`, which matches JSON escapes and needs a full scan; Rt4, a tag click running `q=<tag>`, which the operator rejected in favour of exact-tag results.\n\nKnown risk: the prefilter depends on how the FTS tokenizer splits tags, which this code does not control. It gives no per-tag counts.\n\n### Measured evidence (2026-10-04, read-only, dev `engine/server/db/whitelist.db`, 909,004 videos, warm cache, scripts in `.scratch/tags-on-cards-and-tag-search/`)\n\n- `tag_match_timing.py`: the prefilter plus the exact check took 0.01\u20130.03 s for `linux` (6,243 videos), `music` (4,525), `pco` (17,464) and `partido da causa oper\u00e1ria` (15,630), including newest-first with `LIMIT 24`. The full `json_each` scan with no prefilter took 0.71 s for `linux`.\n- `fts_miss.py`: for `linux`, every video the full scan finds is among the FTS candidates. The FTS triggers in `engine/server/db/jobs/sync-whitelist.py` keep `videos_fts.tags_json` current on every insert, update or delete of a `videos` row, including the `/api/video` refresh.\n- 24 of 1,731,904 tag uses contain no word character, so the tokenizer gives them no token and the prefilter cannot find them.\n- `sqlite_lower_probe.py`: in the Engine's Python environment, SQLite `lower('M\u00daSICA')` gives `m\u00fasica`, the same as Python. Accented and Cyrillic tags match as FTS tokens.\n- `tag_lengths.py`: the longest stored tag is 30 characters.\n\n### Acceptance criteria\n\n- **AC1:** every video row the Engine returns from search, from every home feed mode and from up-next carries a `tags` field: the video's tags as strings, in the uploader's order. It is `[]` when the stored `tags_json` is NULL, empty, invalid JSON or not a list. The rows go through `stable_video_rows` / `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py`, around line 106), which do not carry tags today, although the data-layer queries (`data/search.py`, `data/random_videos.py`, `data/metadata.py`) already select `tags_json`. The Client gateway passes `tags` through unchanged.\n- **AC2:** feed, search and up-next cards show the tags as chips on one line. Tags that do not fit are dropped from the end and counted in a `+N` marker. A card with no tags shows no tag line. Each chip's text is set as text, never as markup, because tags come from remote instances. How many chips fit depends on the rendered layout, so it is measured after the card is in the DOM and again when the card's width changes.\n- **AC3:** clicking a chip on any card, or on the video page, opens the search page for that tag at `/search.html?tag=<tag>`, with the tag URL-encoded, and does not also open the video. `/search.html` is the path every nav link uses; the client backend does not rewrite `/search`, and only the Vite dev server does. Clicking anywhere else on a card behaves as it does today.\n- **AC4:** `GET /api/v1/search/videos?tag=<tag>` with no `q` returns the videos whose tag list holds `<tag>` once both sides are trimmed and lowercased, newest first (`published_at DESC, video_id DESC`). `sort=views` and `sort=popularity` reorder them using the `LEXICAL_SORTS` orderings. `sort=relevance`, `sort=published_at` or no sort means newest. Any other sort answers 400, as text search does.\n- **AC5:** tag results page through every matching video, using the existing `page` and `limit` parameters and the existing `SEARCH_MAX_LIMIT` cap. `total` is the exact count of matches the `nsfw` setting allows, counted the same way as text search's `total`: before the Engine's `apply_serving_moderation_filters` and the gateway's profile blocks remove rows, so a page can hold fewer rows than `total` implies. Text search stays capped at its 200-candidate pool (`SEARCH_CANDIDATE_POOL`).\n- **AC6:** tag results obey the `nsfw` parameter the same way text search does (ADR-0007: flagged videos are filtered out unless `nsfw=1`), with `include_nsfw` passed from the request edge (`_parse_include_nsfw`). The Engine applies `apply_serving_moderation_filters` to them, as it does for text search. The gateway applies the profile's blocks, dislike marks and like marks to them, as it does for text search (`/api/v1/search/videos` is in `FILTERED_ROUTES` in `client/backend/server.py`).\n- **AC7:** the Engine answers 400 with a JSON `error` to a request carrying both `q` and `tag`, to a `tag` that is empty after trimming, and to a `tag` longer than 64 characters. A request with neither `q` nor `tag` still answers 400, as it does today.\n- **AC8:** the tag results page names the tag and offers the newest, views and popularity sorts (relevance is not offered). It keeps `tag` and `sort` in its URL, so the back button, reload and shared links restore the same results; the newest sort leaves `sort` out of the URL. Changing the sort menu re-runs the tag search (today the menu does nothing when there is no `q`). The page's title and `popstate` handling cover tag mode as well as text mode. Submitting the search box runs an ordinary text search and removes `tag` from the URL. The gateway allowlist (`PROXY_ALLOWED_QUERY_PARAMS[\"/api/v1/search/videos\"]` in `client/backend/server.py`) gains `tag`.\n- **AC9:** a tag with no word character, such as `???` or an emoji, still returns its exact matches, through the full-scan fallback.\n\n### Card structure (operator-approved resolution, 2026-10-04)\n\n- **Feed and search cards (`renderVideoCard`):** the chip row is rendered outside the card's `<a class=\"video-link\">`, inside the `<article class=\"video-card\">`, in the same way the `card-actions` buttons sit outside it today (\"a button inside an <a> would also navigate\"). The card body inside the link is unchanged.\n- **Up-next cards (`renderSimilarCard`):** today the whole card is one `<a class=\"similar-card-item\">`. It becomes a container element holding the existing link and, beside it, a chip row outside the link. The `data-video-key` attribute and the existing click and stats behaviour keep working. CSS for `.similar-card-item` in `client/frontend/src/video.css` is adjusted to match.\n- **Video page:** the existing tag chips (`client/frontend/src/pages/video-page/index.ts`, around line 290: `span.tag-chip` built with `textContent`) become links to `/search.html?tag=<tag>`, still built from text.\n- **Chips:** reuse the video page's `tag-chip` treatment. Each chip is a real link (`<a href=\"/search.html?tag=...\">`), so middle-click and open-in-new-tab work. In string-built card markup every interpolated value passes through `escapeHtml`, the chip href is built with `URLSearchParams`, and the dev-only `?api=` propagation follows `videoPageUrl`'s rule.\n\n### Consistency constraints\n\n- Card markup keeps `renderVideoCard`'s rule that every interpolated value passes through `escapeHtml` (and every external URL through `safeExternalUrl`). DOM-built chips use `textContent`.\n- The new `tag` parameter follows the search route's existing style: the Engine rejects bad input with a 400 and a JSON `error`, and the gateway forwards only allowlisted parameters.\n- A new listing path passes `include_nsfw` from the request edge (ADR-0007, Consequences).\n- New code matches the style of the file it lands in. Smallest change that works: no new table, no new dependency, no new module unless a renderer needs a shared chip helper used by both card renderers.\n\n### Checked in the tree (2026-10-04)\n\n- `renderVideoCard` wraps the whole card body in one `<a class=\"video-link\">`. The like, dislike, block and follow buttons sit outside it. The channel link is an `<a>` nested inside the card link (invalid HTML today, but left as it is in this plan).\n- `renderSimilarCard` renders each up-next card as one `<a class=\"similar-card-item\">`.\n- `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py:106`) has no `tags_json`, `tags` or `category`.\n- `_handle_search` (`similar.py:420`) takes `q` (required), `sort` (`relevance` or a `LEXICAL_SORTS` key), `limit`, `page` and `nsfw`. It has no tag or category parameter.\n- The gateway allowlist for `/api/v1/search/videos` is `q`, `page`, `limit`, `sort`, `nsfw`.\n- The search page (`client/frontend/src/pages/search/index.ts`) keeps `q` and `sort` in its URL. Its sorts are `relevance`, `published_at`, `views` and `popularity`. Its sort-change handler and `popstate` handler do nothing without a `q`.\n- No Engine handler, data-layer query or frontend module filters by tag or category today.\n\n### Baseline suite state\n\nThe pre-build baseline suite run exited with code 0 (all passing, no variant). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`. Record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "3",
    "5"
  ],
  "initial_solution": "### Approach\n\nThe work has three layers: the Engine, the gateway and the frontend. Each layer gets the smallest change that meets the acceptance criteria. There is no new table, no new dependency and no new Python module. The frontend gains a shared chip helper in the existing `components/video-card.ts`, and one small stylesheet that the helper imports.\n\n**Engine: tags on every row (AC1).** `stable_video_row` in `handlers/similar.py` adds a `tags` key to each projected row. The value is the stored `tags_json` parsed by `tags_from_json`, which already exists in `handlers/video.py` and already gives `[]` when the value is NULL, empty, invalid JSON or not a list. It also keeps the uploader's order. `video.py` imports nothing from `similar.py`, so importing it the other way creates no cycle. Search uses this projection (`similar.py:484`), and so do the feed modes and up-next (`similar.py:611`). The row sources (`data/search.py`, `data/random_videos.py`, `data/metadata.py`) already select `tags_json`. The build should still check each feed mode's row source, including Following, and a test per mode should assert `tags` is present. `STABLE_VIDEO_FIELDS` itself does not change: `tags` is derived and does not exist as a stored field. The gateway's `_filter_payload` round-trips each row as a dict, so `tags` passes through it untouched.\n\n**Engine: the `tag` parameter (AC4, AC5, AC6, AC7, AC9).** `_handle_search` keeps its `SEARCH_ENABLED` gate and then branches on which parameter is present:\n- Both `q` and `tag`: 400.\n- A `tag` that is empty after trimming: 400.\n- A `tag` longer than 64 characters after trimming: 400.\n- Neither: the existing \"Missing query parameter q\" 400. `parse_qs` drops a bare `?tag=` and the gateway drops blank values, so `?tag=` reaches this branch and still gets a 400.\n\nEvery 400 uses the existing `respond_json(self, 400, {\"error\": ...})` form. In tag mode the sort is checked the same way as now (relevance or a `LEXICAL_SORTS` key, anything else 400). Relevance and no sort both resolve to `published_at`. `limit`, `page`, `SEARCH_MAX_LIMIT` and `_parse_include_nsfw` are parsed exactly as text search parses them. The tag branch calls a new function in `data/search.py`, placed beside `lexical_candidates`. It returns `(rows, total)` like `search_videos`, so everything after it is shared: `apply_serving_moderation_filters`, `stable_video_rows` and the same response shape. In tag mode the response's `sort` field echoes the resolved sort and `vectorSearch` is false. Text search is untouched and keeps its `SEARCH_CANDIDATE_POOL` cap.\n\n**What the new data-layer function does.** It works under `search_connection`'s lock and `search_deadline`, and raises `SearchIndexMissing` when `videos_fts` is absent, as text search does.\n- **Prefilter.** It splits the tag with the module's `_TOKEN_SPLIT`. If at least one word token survives, it builds an FTS5 column filter on `tags_json` holding one quoted phrase. Quotes are doubled, as in `sanitize_query`, so the tag cannot inject operators. It joins `videos_fts` to `videos` the way `lexical_candidates` does.\n- **Fallback (AC9).** If no token survives, there is no FTS join and the query scans `videos` directly.\n- **Exact check (both paths).** A `json_each` membership test compares `lower(trim(element))` with `lower(trim(?))`. The requested tag is normalised in SQL as well as the stored tags, so both sides go through one function, which is what the requirements ask for. The trim names an explicit whitespace set (space, tab, CR, LF), because SQLite's default `trim` removes only spaces while the gateway's `strip()` removes all whitespace.\n- **Filtering and ordering.** It adds the `NSFW_ALLOWED_SQL` clause when `include_nsfw` is false. It orders by the `LEXICAL_SORTS` entry for the resolved sort, and pages with `LIMIT ? OFFSET ?` from `page` and `limit`.\n- **Total (AC5).** A second `COUNT(*)` statement with the same FROM/WHERE runs under the same lock and deadline. So `total` counts every match the NSFW setting allows, before moderation and before the profile filters, which matches what text search's `total` counts.\n\n**Gateway (AC6, AC8).** `tag` is added to `PROXY_ALLOWED_QUERY_PARAMS[\"/api/v1/search/videos\"]`. That route is already in `FILTERED_ROUTES`, so blocks, dislike marks and like marks apply to tag results with no further change. The gateway strips the value, and the Engine re-trims it anyway.\n\n**Frontend: shared chip helper (AC2, AC3).** `components/video-card.ts` gains three exports, each used by more than one caller:\n- `tagSearchUrl(tag, apiParam)` builds `/search.html?tag=\u2026` with `URLSearchParams`. It adds `api` only in a dev build, by the same rule as `videoPageUrl`.\n- `renderTagChips(tags, apiParam)` returns the chip row as a string: a `.card-tags` container of `<a class=\"tag-chip\">` links, every value through `escapeHtml`, then a hidden `+N` marker. It returns an empty string when there are no tags, so a card with no tags has no tag line.\n- `observeTagRows(container)` is called once per grid container: the feed `cards`, the search `results` and the up-next `similarCards`. It installs one `MutationObserver` that finds `.card-tags` rows as they are added (by `innerHTML`, `insertAdjacentHTML` or `outerHTML` re-renders) and registers them with one shared `ResizeObserver`. The ResizeObserver's first callback runs the fit after layout, and later callbacks re-fit when the card's width changes. Removed rows are unobserved.\n\nThe fit itself: un-hide every chip and the marker, then hide chips from the end until the last visible chip plus the marker fits the row's width. The marker reads `+N` and is shown only when N > 0. The row is a no-wrap flex line with hidden overflow, so before the fit runs the worst case is a clipped chip, never a second line.\n\n**Frontend: the cards (AC2, AC3).**\n- **Feed and search cards.** `renderVideoCard` appends the chip row inside the `<article>`, after the `<a class=\"video-link\">` and beside `card-actions`. Both pages' delegated click handlers only act on `[data-card-action]`, so a chip click is an ordinary link to the tag results and never also opens the video.\n- **Up-next cards.** `renderSimilarCard` changes its outer `<a class=\"similar-card-item\">` to a `<div class=\"similar-card-item\">` that keeps `data-video-key`. Inside it are the existing body as `<a class=\"similar-card-link\">` and, beside it, the chip row. The stats update at `index.ts:1613` finds the card by `[data-video-key]` and the stat spans inside it, so it keeps working.\n- **CSS for up-next.** In `video.css`, the border, background and hover rules stay on `.similar-card-item`. The link takes the flex column, `color: inherit` and no underline.\n- **Chip styles.** `.tag-chip` moves out of `video.css` into a small stylesheet that `video-card.ts` imports, together with the `.card-tags` row rules. That stylesheet loads on the feed, search and video pages, and there is still only one copy of the chip style.\n\n**Frontend: the video page (AC3).** The existing chips stay DOM-built with `textContent` but become `<a class=\"tag-chip\">` elements whose `href` comes from `tagSearchUrl`.\n\n**Frontend: the search page in tag mode (AC8).**\n- **Data module.** `data/search.ts`'s `fetchSearchResults` takes either `q` or `tag` and sets only the one given. The cache key is the URL, so tag pages are cached apart from text pages.\n- **State and loading.** The page's state gains `tag`. When the URL has a `tag` and no `q`, the page runs in tag mode: the input is empty, and a heading (a new element in `search.html`, filled with `textContent`) names the tag. The title becomes \"<tag> - Tag - Search - PeerTube - Browser\". The status line says \"Showing X of Y videos tagged \u2026\" or \"No videos tagged \u2026\".\n- **Sort menu.** In tag mode the relevance option is hidden and disabled, and the default sort is `published_at`. `pushUrl` leaves `sort` out when the sort is the mode's default (relevance for text, `published_at` for tag) and writes `tag` when in tag mode.\n- **Handlers.** The sort-change handler and the `popstate` handler both handle tag mode as well as text mode.\n- **Leaving tag mode.** A form submit clears `tag`, restores the relevance option and runs `startSearch` as now, so `tag` leaves the URL. The chosen sort is carried over (`published_at`, views and popularity are all valid text sorts).\n- **URL with both `q` and `tag`.** Such a URL can only be hand-made. The page prefers `q` and drops `tag` with `replaceState`, so it never sends the combination the Engine would refuse.\n- **Paging.** Infinite scroll keeps its existing `page`/`total` logic. Tag results page through the whole match set because `total` is now exact.\n\n### Alternatives considered\n\n- **Window `COUNT(*) OVER ()` instead of a second count statement.** Rejected. It saves one statement on the cheap path, but a page past the end returns no rows and therefore no total, which breaks AC5. The count costs about 0.01\u20130.03 s on the prefilter path, and about 0.7 s more on the full-scan fallback, which only affects the rare tags with no word character.\n- **Normalising the requested tag in Python and the stored tags in SQL.** Rejected. Python's `lower`/`strip` and SQLite's `lower`/`trim` disagree on whitespace and on a few Unicode cases (for example `\u0130`). Running both sides through the same SQL expression is how the \"same normalisation on both sides\" requirement holds by construction.\n- **Calling a fit function after each render site instead of a `MutationObserver`.** Rejected. The three pages insert cards from about nine places (reset, append, in-place `outerHTML` re-renders after a like, dislike or block, and `removeRows`), and every new insertion path would have to remember to call it. One observer per container covers all of them with three call sites.\n- **CSS-only truncation.** Rejected. CSS can clip the line but cannot count the hidden chips for `+N`.\n- **Putting the chips inside `.video-link` and stopping propagation.** Rejected. It nests an `<a>` inside an `<a>` and breaks middle-click, and the operator approved the outside-the-link structure.\n- **Importing `videos.css` on the video page, or copying `.tag-chip` into it.** Rejected. Importing it would bring in feed styles that could collide; copying it would give two copies to keep in step.\n- **A separate `_handle_tag_search` route or handler.** Rejected. AC4 puts tag search on `/api/v1/search/videos`. Branching inside `_handle_search` shares the moderation, projection and response code instead of duplicating it.\n- **Falling back to a full scan whenever the FTS prefilter returns nothing.** Rejected. It would hide tokenizer mismatches, but every search for a tag nobody uses would cost a 0.7 s scan, which is an easy load amplifier. The fallback stays tied to \"no word token\", as the settled route says.\n\n### Gotchas and risks\n\n- **`json_each` and bad `tags_json`.** `json_each` raises on malformed JSON, which would turn a single bad row into a 500 for the whole tag query. It also iterates an object's values, which would wrongly match a non-list. The exact check therefore feeds `json_each` a CASE that substitutes `'[]'` unless `tags_json` is valid JSON and of type `array`, and it compares only `text` elements. A guard in a separate AND term is not enough, because SQLite does not promise evaluation order.\n- **Tokenizer mismatch (the known risk of Rt1).** The prefilter's phrase comes from Python's `\\w` split, but the index was built by FTS5's `unicode61`. Where the two disagree, matches are missed and the gap is not reported. One example is a tag stored with a JSON escape inside it (`a\\nb` is indexed as `a`, `nb`). Another is a character Python counts as a word character but `unicode61` treats as a separator. `to_tags_json` writes raw UTF-8, and `fts_miss.py` showed no misses for `linux`, so the expected gap is a handful of edge-case rows. Rt2 is the upgrade path if it ever matters.\n- **Superset matches are fine.** `unicode61` removes diacritics and folds case, and a phrase can run across adjacent tags. Both only widen the candidate set, and the exact check discards the extras.\n- **SQLite `lower()` on the search connection.** The probe showed Unicode-aware `lower()` in the Engine's environment. Tests should run an accented tag (`M\u00daSICA` vs `m\u00fasica`) through the real search connection, so a build without that behaviour fails loudly instead of quietly matching ASCII only.\n- **Deep pages.** With an exact `total`, a visitor can scroll deep into `pco` (17,464 rows). `OFFSET` paging gets slower linearly with depth but stayed well inside the deadline at the measured sizes. The fallback scan costs about 1.4 s per page (page plus count), which is also inside the 5 s deadline.\n- **Short pages stop scrolling.** The gateway and moderation can remove every row on a page. The page's existing `rows.length > 0` stop condition then ends scrolling early. Text search already behaves this way, and AC5 accepts short pages.\n- **Rows past the end of a pool.** The `+N` fit needs layout. The ResizeObserver's initial callback provides it, and until that callback runs the row is clipped, not wrapped. Hidden chips leave the accessibility tree, and the marker carries an `aria-label` (\"N more tags\").\n- **Up-next markup change breaks a test.** `tests/active/test_frontend_video_page_similars.py` asserts on `similar-card-item`, so it has to change in this build. The built bundle under `client/frontend/dist` is regenerated output and is not edited by hand.\n\n### Tradeoffs the operator is asked to accept\n\n- A tag search costs two statements per page (rows plus count) in exchange for an exact `total`.\n- Rare tokenizer-mismatch tags can return fewer videos than they carry. This is the accepted Rt1 risk, and Rt2 is the upgrade path.\n- The `+N` marker is plain text, not a control. To see every tag, the visitor opens the video, whose page lists them all.\n- The chip row adds one line of height to every card that has tags. Cards without tags are unchanged, so card heights in a grid can differ.\n- A hand-made URL carrying both `q` and `tag` is silently reduced to the text search.",
  "conflicts": "none",
  "impacts": "Note on the tree: `/home/enduser/code/PeerTube-browser/.worktrees/55` does not exist (rg: \"No such file or directory\"; Glob finds nothing under `.worktrees/`), although `tests/config.json:3` names it as `project_dir`. Every file below was opened in the main checkout `/home/enduser/code/PeerTube-browser`, and paths are relative to the repo root. An earlier pass of this step is already written into `docs/project/plans/54-53-tags-on-cards-and-tag.md`. I re-checked its claims against the source and they hold. Below I add what it lacks: stored blank or over-64 tags producing dead chips, the absence of any custom SQLite `lower()`, `test_similar`'s group missing `handlers/video.py`, the existing nested `channel-link` anchor, and `popstate` pushing history through `showIdle`.\n\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"stable_video_row (129-131) / stable_video_rows (134-136); new import of tags_from_json\">\n**What changes:** `stable_video_row` returns `{field: row.get(field) for field in STABLE_VIDEO_FIELDS}` plus `\"tags\": tags_from_json(row.get(\"tags_json\"))`. `STABLE_VIDEO_FIELDS` (106-126, with the `INCLUDE_DYNAMIC_STATS` tail at 125-126) is unchanged. A new import line is added: `from handlers.video import tags_from_json`.\n\n**What depends on it:**\n- Exactly two callers: `_handle_search` (484) and `_respond_rows` (611). `_respond_rows` serves every feed mode (random, ordered trending/popular/recent, following, home mix and its fallback), up-next, the raw-vector route and seed-random.\n- `maybe_attach_debug` (139) spreads the stable row, so `tags` survives in debug mode.\n- Row sources that carry `tags_json` (verified):\n  - `data/search.py:66` (`VIDEO_ROW_SQL`)\n  - `data/metadata.py:49,91,198` (`fetch_metadata`, which up-next and vector search use)\n  - `data/random_videos.py:59,115,160,204,248`\n  - `_ordered_row` (`random_videos.py:292`), which serves `fetch_ordered_page` and Following's `fetch_followed_page` (417)\n- `apply_serving_moderation_filters` (`data/serving_moderation.py:14-48`) returns the row dicts it was given and does not rebuild them.\n\n**Import cycle:** none. `router.py:44` already imports `handlers.video`, and `similar.py:85` imports `router`, so `handlers.video` is always loaded before `similar.py` finishes importing. `video.py` imports only `data.*`, `http_utils` and `server_config` (9-21).\n\n**Regression risk: low.** The change is additive and `tags_from_json` never raises. No test pins the exact key set of an Engine listing row: `test_random_videos.py:591` checks a subset, and `test_metadata.py:40` and `test_internal_client_reads.py:27` check data-layer rows. `tags` is remote-controlled text that now reaches every listing payload and the `innerHTML`/`insertAdjacentHTML`/`outerHTML` sinks on three pages.\n</impact>\n\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"_handle_search (420-486); import line 27; module docstring (3) and method docstring (421)\">\n**What changes**\n- After the `SEARCH_ENABLED` gate (426-428), read `tag` beside `q` (430). Validation: `q`+`tag` \u2192 400; a tag that strips to empty \u2192 400; a stripped tag longer than 64 \u2192 400; neither \u2192 the existing `\"Missing query parameter q\"` (431-433).\n- The sort check (435-438) stays. In tag mode only, `relevance` or a missing sort resolves to `published_at`. Text mode must keep `relevance` as its default, because `search_videos` branches on `sort == \"relevance\"` for the vector half (`data/search.py:293`).\n- `limit` and `page` (440-446) stay shared.\n- The tag call must sit inside the same `except SearchIndexMissing` \u2192 503 handler (464-467) and pass `include_nsfw=_parse_include_nsfw(...)` (defined at 1089).\n- Moderation and `stable_video_rows` (468-484) stay shared.\n- The response echoes the resolved `sort`, and `vectorSearch` is `False` in tag mode (today 483 derives it from the encoder).\n- Line 27 gains the new function name. The docstrings at 3 and 421 say \"hybrid video search\".\n\n**Detail:** Python `strip()` removes all Unicode whitespace, while the planned SQL trim removes only space, tab, CR and LF. Bind the Python-stripped value, so a direct Engine call with NBSP padding still matches.\n\n**No named constant exists for 64.** `SEARCH_MAX_TOKEN_LENGTH = 64` (`server_config.py:460`) is the per-FTS-token cap, a different limit.\n\n**What depends on it:**\n- `router.py:98-100` (`parse_qs`, no `keep_blank_values`).\n- The rate-limit gate.\n- `_serve` (410-418): an interrupted statement becomes 503 \"Query time limit exceeded\" (400).\n- Live text-search tests: `test_similar.py:140,142`, `test_frontend_follows.py:83`, plus the gateway-driven tests in the blocks, reactions and upnext-pager files.\n\n**Regression risk: medium.** The branch sits in front of the text path. Resolving relevance\u2192published_at outside tag mode silently disables vector fusion for text search, and mis-reading `tag` lets `q`+`tag` through.\n</impact>\n\n<impact path=\"engine/server/data/search.py\" element=\"new tag-search function beside lexical_candidates (134-168); module docstring (1-10); search_videos docstring (271-277)\">\n**What changes:** a new function returning `(rows, total)`.\n- It copies the shape of `search_videos` 283-290: `search_connection` (32-43) \u2192 `with lock:` \u2192 `with search_deadline(server):` (46-49) \u2192 `fts_available` (121-131) \u2192 `SearchIndexMissing`.\n- **Prefilter:** split with `_TOKEN_SPLIT` (25) and build one quoted phrase on the `tags_json` column, doubling quotes as at 112. It joins `videos_fts f JOIN videos v ON v.rowid = f.rowid LEFT JOIN channels c ...` as at 157-160.\n- **Fallback:** `FROM videos v LEFT JOIN channels c`.\n- **Exact check:** `EXISTS(SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) AND json_type(v.tags_json)='array' THEN v.tags_json ELSE '[]' END) j WHERE j.type='text' AND lower(trim(j.value, set)) = lower(trim(?, set)))`.\n- **NSFW:** `AND {NSFW_ALLOWED_SQL}` when the flag is False; it is already imported (20).\n- **Order:** `LEXICAL_SORTS[sort]` (83-87).\n- **Paging:** `LIMIT ? OFFSET ?`.\n- **Total:** a second `COUNT(*)` with the same FROM/WHERE.\n- Rows reuse `VIDEO_ROW_SQL`, as the text path does. There is no `video_embeddings` join and no error threshold, the same as text search (`test_search.py:27`).\n- Default `include_nsfw=True`, per ADR-0007 decision 1.\n- The module docstring (1-10) and the `search_videos` docstring (271-277, \"fused candidate set\") describe only hybrid search.\n\n**Facts checked against files**\n- No custom SQL function is registered on any Engine connection. Grep for `create_function` finds only `ann_id_of` in the jobs (`sync-whitelist.py:510`, `whitelist_migrations.py:407`), and `connect_readonly_db` (`data/db.py:85`) adds none. Unicode-aware `lower()` therefore depends entirely on the SQLite build (ICU) in the Engine's pixi env. SQLite core `lower()` folds ASCII only. I cannot confirm the plan's probe from files; tests must run on `ENGINE_PY`.\n- FTS5 tokenizes the phrase string with the table's own `unicode61` tokenizer. A Python token like `foo_bar` is therefore re-split into the phrase `foo bar`, which narrows the Rt1 gap rather than widening it.\n\n**What depends on it:** `_handle_search`; `tests/active/test_search.py`.\n\n**Regression risk: medium-high, all in SQL semantics**\n- `json_each` raises on malformed JSON, so the guard must sit inside its argument.\n- The trim set and the `lower()` build behaviour must be handled as above.\n- The FTS phrase must stay a quoted literal.\n- `OFFSET` cost grows with depth.\n- The `views` sort has no index (only `idx_videos_published` and `idx_videos_popularity`, `sync-whitelist.py:402-405`), so a views-sorted fallback scan sorts the whole match set.\n</impact>\n\n<impact path=\"engine/server/api/handlers/video.py\" element=\"tags_from_json (164-174); to_tags_json (156-161)\">\n**What changes:** no change to either body. `tags_from_json` gains a second importer.\n\n**What depends on it:**\n- `/api/video`'s `tags` (345), and now every listing row.\n- `to_tags_json` writes `ensure_ascii=False` (160), as does the crawler's `toTagsJson` (`engine/crawler/src/videos-worker.ts:820-824`, `JSON.stringify`). Stored tags are therefore raw UTF-8, which keeps the Rt1 gap small.\n- Neither writer filters empty, whitespace-only or long strings, so stored tags can be `\"\"`, `\"  \"` or longer than 64 characters (see the video-card entry).\n\n**Regression risk: low.** A future change here now changes every listing as well as `/api/video`.\n</impact>\n\n<impact path=\"engine/server/api/server_config.py\" element=\"SEARCH_* block (450-470)\">\n**What changes:** optional. Add `SEARCH_MAX_TAG_LENGTH = 64` beside `SEARCH_MAX_TOKEN_LENGTH` (460) and import it in `similar.py` (37-64). The plan names neither the constant nor a literal.\n\n**What depends on it:** many test groups list this file (for example `test_similar.py`, `test_dislike_profile.py`, `test_internal_translate.py`), and `test_similar.py:130-135` execs it.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"engine/server/api/router.py\" element=\"module docstring route list (11); _search (98-100)\">\n**What changes:** line 11 reads `GET /api/v1/search/videos: hybrid video search. [rate-limit gate]` and should mention the exact-tag mode. `_search` is unchanged, since it forwards every parsed parameter.\n\n**What depends on it:** nothing new.\n\n**Regression risk: none.**\n</impact>\n\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"videos_fts DDL (393-401) and triggers (275-290): read-only dependency\">\n**What changes:** nothing.\n\n**What depends on it:** the prefilter depends on `videos_fts` keeping its `tags_json` column under the default `unicode61` tokenizer, and on the AI/AD/AU triggers keeping it in step, including `/api/video/refresh` writes (`video.py:391`).\n\n**Regression risk:** none from this build. A future tokenizer or column change would silently drop tag matches.\n</impact>\n\n<impact path=\"client/backend/server.py\" element=\"PROXY_ALLOWED_QUERY_PARAMS['/api/v1/search/videos'] (104); _sanitize_query (138-154); _handle_engine_read_proxy_get (595-604); _filter_payload (1393-1419)\">\n**What changes:** line 104 becomes `{\"q\", \"page\", \"limit\", \"sort\", \"nsfw\", \"tag\"}`.\n\n**Inherited behaviour**\n- `tag` is stripped, because it is not in `PROXY_UNSTRIPPED_QUERY_PARAMS` (120), and dropped when empty. A repeated `tag` gets the gateway's own 400.\n- The query is re-encoded with `urlencode` (752).\n- The route is in `FILTERED_ROUTES` (83) and `PROXY_READ_GET_ROUTES` (95-97), so keyed tag results get blocks and reaction marks. It is not in `FEED_ROUTES`, so there is no over-fetch and no dislike removal.\n- `_filter_payload` round-trips row dicts, so `tags` passes. It re-encodes with default `ensure_ascii` (1419), so non-ASCII tags arrive `\\u`-escaped, which is equivalent JSON.\n\n**What depends on it:**\n- `client/frontend/src/data/search.ts` (its docstring says \"exactly five\").\n- `test_server.py:1549` pins only the `nsfw` allowlist on `/api/video`.\n- No test asserts that `tag` is unknown.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"client/frontend/src/components/video-card.ts\" element=\"new exports tagSearchUrl / renderTagChips / observeTagRows; renderVideoCard (341-419); new side-effect CSS import; module docstring (1-12)\">\n**What changes**\n- **`tagSearchUrl`:** mirrors `videoPageUrl`'s DEV-only `api` rule (330).\n- **`renderTagChips`:**\n  - Returns `\"\"` for a missing, non-array or empty list. Rows cached before the deploy lack `tags`.\n  - Escapes every value with `escapeHtml` (67-84).\n  - The `+N` marker starts `hidden` and carries an `aria-label`.\n  - It must not emit `style=\"...\"`, because every page's CSP is `style-src 'self'` (`search.html:8`). The precedent comment is at `video.css:62`.\n- **`observeTagRows`:** one `MutationObserver` plus one shared `ResizeObserver`. Neither may be constructed at module level, and calling it where `MutationObserver` is undefined throws, which matters for the node harnesses below.\n- **`renderVideoCard`:** puts the row after `</a>` at 416, beside `actionsMarkup`.\n\n**Gaps the plan does not settle**\n- **Dead chips.** Stored tags can be blank, whitespace-only or longer than 64 characters, since neither writer caps them (see the `video.py` entry):\n  - A chip for `\"\"` or `\"  \"` links to `?tag=` or `?tag=%20`. The gateway drops the value and the Engine answers \"Missing query parameter q\", or the search page sees no tag and shows idle.\n  - A chip for a tag longer than 64 characters links to a guaranteed 400.\n  - The helper should skip blank tags. Whether to skip over-length tags or link them anyway is an open decision.\n- **Existing nested anchor.** The card already nests `<a class=\"channel-link\">` inside `<a class=\"video-link\">` (402). The plan's \"no nested `<a>`\" applies only to the chips.\n\n**What depends on it**\n- `pages/videos/index.ts:36-51`: the home feed and the `/videos.html?id=` similar view.\n- `pages/search/index.ts:14-20`.\n- `pages/likes/index.ts:9`: helpers only, but it now pulls in the CSS chunk.\n- `pages/video-page/index.ts:29`.\n- `test_frontend_video_card.py:39` (with `--loader:.css=empty`).\n- `test_frontend_reactions.py:106-121`, which bundles without a CSS loader flag.\n\n**Regression risk: medium.** The risks are an XSS sink if any interpolation is missed, a `ReferenceError` in harnesses, and the CSP silently dropping inline styles.\n</impact>\n\n<impact path=\"client/frontend/src/tags.css (new file; name to be chosen)\" element=\"new shared sheet: .tag-chip moved from video.css 408-415, plus .card-tags row and +N marker rules\">\n**What changes**\n- `.tag-chip` moves here, using `--line` and `--ink` from `base.css`.\n- Chips become `<a>`, so the sheet needs `text-decoration: none` and an explicit colour. There is no global `a` rule; `.video-link` is scoped (`videos.css:297`).\n- `.card-tags` is a no-wrap flex row with `overflow: hidden` and `min-width: 0`.\n- A `[hidden] { display: none }` override is needed for any element given a display value. The precedents are `video.css:388,486`.\n\n**Build hazard**\n- `video-card` is already its own Vite chunk (`dist/assets/video-card-DWtpz1-l.js`). Vite has no `manualChunks` or `cssCodeSplit` override (`vite.config.ts:82-96`), so a CSS import there emits a separate `video-card-*.css` linked from index, videos, likes, search and video-page.\n- `test_frontend_base_css.py:100` asserts that the linked bundles are exactly `[\"channels\",\"search\",\"video\",\"videos\"]`.\n- 105-115 require every linked bundle to open with the full built base and contain no `@import`.\n- The new bundle fails both checks unless the sheet `@import`s `./base.css`, which duplicates base. Search already loads base twice, through `videos.css` and `search.css`.\n\n**What depends on it:** the `tests/config.json` groups for base-css (355-362) and dist (363-412).\n\n**Regression risk: high** (build and test contract).\n</impact>\n\n<impact path=\"client/frontend/src/video.css\" element=\".tag-list (402-406), .tag-chip (408-415), .similar-card-item (528-539) and :hover (541-544)\">\n**What changes**\n- Remove `.tag-chip`.\n- `.similar-card-item` keeps its padding, border, radius, background, transition, hover, and a flex column so the link and the chip row stack. `text-decoration` and `color` move to a new `.similar-card-link`, which takes `display:flex; flex-direction:column; gap:0.5rem` to keep the inner spacing.\n- The `.similar-thumb`, `.similar-title`, `.similar-channel`, `.similar-meta` (546-602) and `.similar-reaction` selectors still match inside the link.\n- `.tag-list` (the video page's full list) must stay wrapping.\n- `.similar-card` (36) is a different selector (the section panel).\n\n**What depends on it:** `test_frontend_base_css.py`, `test_frontend_dist.py`, and the `test_frontend_video_page.py` group (`tests/config.json:230`).\n\n**Regression risk: low-medium** (visual, on the `.similar-grid` at 522-526).\n</impact>\n\n<impact path=\"client/frontend/src/videos.css\" element=\".video-card (281), .video-link (297), .card-actions (496-502)\">\n**What changes:** probably none, since the new sheet supplies the row. The chip row becomes a direct child of `.video-card`, after `.video-link`.\n\n**What depends on it:** `.cards-grid` (257) on the feed and search pages.\n\n**Regression risk: low.** Cards with tags grow by one line, which is an accepted tradeoff.\n</impact>\n\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"tag chips (290-304); import (29)\">\n**What changes:** `createElement(\"span\")` (295) becomes `createElement(\"a\")`, keeping `className=\"tag-chip\"` and `textContent`, and gaining `href = tagSearchUrl(tag, params.get(\"api\"))`. `params` is at line 82. Add `tagSearchUrl` to the import at 29. The \"No tags\" branch (302) stays.\n\n**What depends on it:** `test_frontend_video_page.py:4-5,189,306-330` reads the children's `textContent` and the `tag-chip` class. The recording element has an `href` accessor (86-87).\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"renderSimilarCard (1688-1721); applySimilarStatsToDom (1610-1617); similarCards render sites 357, 369, 375, 384, 388, 708; local videoPageUrl (1655-1676)\">\n**What changes**\n- The outer `<a class=\"similar-card-item\" href=\u2026${keyAttribute}>` (1710) becomes `<div class=\"similar-card-item\"${keyAttribute}>` wrapping `<a class=\"similar-card-link\" href=\u2026>`, plus `renderTagChips(row.tags, params.get(\"api\"))`.\n- The page keeps its own `escapeHtml` and `videoPageUrl`; the local one adds no `api`.\n- `observeTagRows(similarCards)` is called once. `similarCards` is nullable (61), so the call goes after the null check, for example in `loadSimilarVideos` after 343, guarded so it runs only once.\n- `applySimilarStatsToDom` still finds `[data-video-key]` (now on the div) and `[data-stat=\"views\"]`.\n\n**Render sites:** 375 (`innerHTML`) and 708 (`insertAdjacentHTML`).\n\n**What depends on it:** `test_frontend_video_page_similars.py` (see that entry). Middle-click now targets only the inner link, so the card padding is no longer clickable.\n\n**Regression risk: medium.**\n</impact>\n\n<impact path=\"client/frontend/src/pages/videos/index.ts\" element=\"cards container (55-68); renderCards (390-409); renderFeedCard (414-423); runCardAction outerHTML (457); click delegation (151-157)\">\n**What changes:** call `observeTagRows(cards)` once after the guard at 66-68. `renderFeedCard` already passes `apiParam` (84, 418). The click handler acts only on `[data-card-action]`. `existingCount` counts `.video-card` (403), so the new row does not affect it.\n\n**What depends on it:** `test_frontend_videos_page.py`.\n- The `HOME_RUNNER` harness (33-66) defines `IntersectionObserver` only.\n- The second harness (315-316) defines `IntersectionObserver` and `ResizeObserver`.\n- Neither defines `MutationObserver`.\n\n**Regression risk: medium.** An unguarded observer fails every case at import.\n</impact>\n\n<impact path=\"client/frontend/src/pages/search/index.ts\" element=\"state (60-73); init (75-76, 139-144); submit (95-103); sort change (105-108); popstate (126-137); startSearch (165-172); loadPage (180-236); showIdle (342-352); pushUrl (357-368); resolveSort (381-384); module docstring (1-10)\">\n**What changes**\n- **State and load:** add `state.tag`. A URL with `tag` and no `q` means tag mode. `q`+`tag` means `q` wins and `pushUrl(true)` drops `tag` with `replaceState`.\n- **The idle path pushes history at load.** 143 \u2192 `showIdle()` \u2192 `pushUrl()` (351) \u2192 `pushState`. Tag mode needs its own branch before that.\n- **Popstate:** it reads only `q` and `sort` and calls `showIdle()` when `q` is empty, which pushes a new entry during `popstate`. Without changes, back-navigation into a tag page becomes idle and destroys forward history.\n- **Sort change:** it returns early on `!state.query` (106).\n- **`resolveSort`:** it defaults to `relevance` (383) and needs a mode-aware default.\n- **Submit:** it clears `tag` and restores the relevance option. Its empty-submit path (98-100) goes through `showIdle`, which must also clear `state.tag`.\n- **`pushUrl`:** writes `tag` in tag mode and omits `sort` at the mode default.\n- **`loadPage`:** passes `tag` or `q` (193-199).\n- **Status lines:** 226 and 233 change for tag mode. The comment at 231-232 (\"fused candidate pool\") is false in tag mode.\n- **Titles:** `document.title` at 140 and 170.\n- **Errors:** an Engine 400 (a hand-made tag over 64 characters) shows \"Search failed. The Engine may be unavailable.\" (210). Any 503, including the deadline 503, shows the no-index message (205).\n- Call `observeTagRows(results)` once. The `outerHTML` re-renders (290, 295), `removeRows` (335) and the reset (185) are covered by the observer.\n- **Docstring:** line 6.\n- **Paging:** `hasMore` (234) uses `loadedRows < total && rows.length > 0`. With blocks removing rows, `loadedRows` never reaches the exact `total`, so paging stops only on an empty page. That costs one extra request at the end and is harmless.\n\n**What depends on it:** no harness bundles this page. `tests/config.json:405` lists it only for dist.\n\n**Regression risk: medium.** It is an untested multi-handler state machine.\n</impact>\n\n<impact path=\"client/frontend/search.html\" element=\"new tag heading in .search-controls (31-56); #search-sort relevance option (47); CSP (8)\">\n**What changes:** a new heading element (`hidden` by default). The relevance option is toggled from script. The CSP stays as it is and rules out inline chip styles.\n\n**What depends on it:** `requireElement` (39-45) throws on a missing id; the dist byte-comparison test.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"client/frontend/src/search.css\" element=\"optional heading rule\">\n**What changes:** optional styling for the tag heading.\n\n**What depends on it:** `test_frontend_base_css.py`: the search bundle must still open with base.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"client/frontend/src/data/search.ts\" element=\"FetchSearchOptions (24-31); fetchSearchResults (57-91); docstring (1-9)\">\n**What changes:** `q` becomes optional and `tag?: string` is added. 60-61 always sets `q` today, and the function must set exactly one of the two. The cache key `search:${url}` (80) separates tag pages from text pages. The docstring's \"exactly five\" becomes six.\n\n**What depends on it:** callers passing `{q}`:\n- `pages/search/index.ts:193`\n- `test_frontend_blocks.py:68`\n- `test_frontend_feed_params.py:329` (checks the built URL)\n- `test_frontend_reactions.py:113`\n\n**Regression risk: low**, provided `q` behaves exactly as before and an empty `tag` is never set.\n</impact>\n\n<impact path=\"client/frontend/src/types/videos.ts\" element=\"VideoRow (5-62); SearchPayload docstring (70-75)\">\n**What changes:** add `tags?: string[] | null`. The `SearchPayload` docstring says `total` is the fused pool; in tag mode it is the exact match count.\n\n**What depends on it:** type-only.\n\n**Regression risk: none.**\n</impact>\n\n<impact path=\"client/frontend/dist/\" element=\"committed build output: seven HTML pages and assets/\">\n**What changes:** regenerate with `vite build` with no local `dev-pages/about.html`, and commit. The new CSS chunk adds a `<link>` to five pages.\n\n**What depends on it:** `test_frontend_dist.py:24-25` compares asset names and page bytes with a fresh build.\n\n**Regression risk: medium.** A stale dist is a certain red.\n</impact>\n\n<impact path=\"tests/active/test_frontend_base_css.py\" element=\"test at 97-115 (control at 100; base-prefix checks 105-115); docstring 1-3\">\n**What changes:** it fails as soon as `video-card.ts` imports a sheet. The two ways out:\n- Amend it to admit exactly one component bundle, and update the docstring.\n- Change the design, for example chip rules in `base.css` or imported from each page sheet. Either needs the operator's approval.\n\n**Regression risk: high.**\n</impact>\n\n<impact path=\"tests/active/test_frontend_dist.py\" element=\"test at 17-25\">\n**What changes:** no code change. It passes only after a rebuilt and committed dist.\n\n**Regression risk: high** if the rebuild is forgotten.\n</impact>\n\n<impact path=\"tests/active/test_frontend_video_page_similars.py\" element=\"_keys regex (140-142); first-batch regex (153); docstring (4-5); RUNNER globals (75-80)\">\n**What changes**\n- Both regexes match `<a \u2026 similar-card-item \u2026>`. Retarget them to the div, or to `similar-card-link` and the key on the div.\n- The docstring says \"anchors\".\n- The harness has `ResizeObserver` (75) but no `MutationObserver`, and its `querySelectorAll` returns `[]`. Add a stub.\n\n**Regression risk: high** (a known, certain break).\n</impact>\n\n<impact path=\"tests/active/test_frontend_video_page.py\" element=\"RUNNER globals (116), PAGE_RUNNER globals (660-661), tag assertions (4-5, 189, 306-330)\">\n**What changes:** add `MutationObserver` stubs to both harnesses, and add an `href` assertion (`/search.html?tag=\u2026`, no `api` with DEV false).\n\n**Regression risk: medium** (an import-time `ReferenceError` fails every case).\n</impact>\n\n<impact path=\"tests/active/test_frontend_translate.py\" element=\"video-page harnesses (globals 158 and 479; bundles 228 and 550)\">\n**What changes:** both bundle `pages/video-page/index.ts` and lack `MutationObserver`, so add stubs.\n\n**Regression risk: medium.**\n</impact>\n\n<impact path=\"tests/active/test_frontend_videos_page.py\" element=\"HOME_RUNNER globals (63-66); second harness globals (315-316)\">\n**What changes:** add `MutationObserver` stubs to both harnesses, and `ResizeObserver` to the first. Optionally assert that one observer watches `video-cards`.\n\n**Regression risk: medium.**\n</impact>\n\n<impact path=\"tests/active/test_frontend_reactions.py\" element=\"_bundle (106-124)\">\n**What changes:** it bundles `video-card.ts` with no `--loader:.css=empty` (115-121). esbuild then writes `bundle.css` beside the JS and the import must resolve. Adding the flag gives parity with the other bundlers.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/active/test_frontend_video_card.py\" element=\"card assertions; bundle (39)\">\n**What changes:** none is required, since its rows carry no tags. It is the natural home for `renderTagChips` and `tagSearchUrl` unit cases: escaping, empty and missing lists, skipped blank tags, the hidden `+N` marker, DEV-only `api`, and no `style=`.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/active/test_search.py\" element=\"_statements fixture (36-54); _CHILD runner (57-83)\">\n**What changes:** this is where the data-layer tag tests go, on `ENGINE_PY` (18). The INSERT (49) sets no `tags_json`, so the fixture needs it or a sibling file is needed. The `server` namespace (68) has no `statement_timeout_seconds`, so the deadline is 0. Cases to cover:\n- the token path and the fallback path\n- malformed, object and NULL `tags_json`\n- trim and case, including `M\u00daSICA`/`m\u00fasica`\n- the NSFW `total`\n- paging past the end\n- the sorts\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/active/test_similar.py\" element=\"_rows (138-153); test_every_row_carries_the_channel_and_account_the_dataset_holds (156-166)\">\n**What changes:** AC1 needs `tags` on every mode. The parametrisation covers home, random, upnext and search; add trending, popular, recent and following (with a `follows` body). Live tag-route cases go here: the four 400s, the sort echo, `vectorSearch` false, the exact `total`, and NSFW.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/active/conftest.py\" element=\"identity_of (305-312)\">\n**What changes:** a per-mode `tags` comparison needs the stored `tags_json`. Every caller (`test_similar.py:161`, `test_frontend_follows.py:86,89`) reads by key, so adding a key or a sibling helper is safe.\n\n**Regression risk: low.**\n</impact>\n\n<impact path=\"tests/config.json\" element=\"test_groups: test_similar.py (55+), test_search.py (261-264), test_frontend_video_page.py (228-233), test_frontend_video_page_similars.py (238-241), test_frontend_translate.py (427-435), test_frontend_base_css.py (355-362), test_frontend_dist.py (363-412)\">\n**What changes**\n- Add `engine/server/api/handlers/video.py` to `test_similar.py`'s group, since `similar.py` now uses `tags_from_json`.\n- Add `components/video-card.ts` to the video-page, similars and translate groups.\n- Add the new sheet to the base-css and dist groups.\n- Add `server_config.py` to `test_search.py` if the constant is added.\n- Map any new test file.\n\n**Regression risk: low.** A missed mapping only means a test is not reselected on edit.\n</impact>\n\n<impact path=\"docs/project/adr/0007-nsfw-filter-default-at-request-edge.md\" element=\"Decisions 1-2 (8-17)\">\n**What changes:** nothing is required. The ADR constrains the build: the new function defaults `include_nsfw=True`, and `_handle_search` passes the parsed flag. Decision 2 (17) names only `search_videos`; amending it is optional.\n\n**Regression risk:** forgetting the flag serves NSFW tag results to every visitor.\n</impact>",
  "docs_checklist": "- [ ] `engine/server/README.md` - \"What it does\" (6-28) has no bullet for `GET /api/v1/search/videos`; only line 53 mentions it, for `nsfw`. Add one covering:\n- `q` text search.\n- The exclusive `tag` mode: an exact match after trimming and lowercasing both sides.\n- The 400s: both parameters, a blank tag, a tag over 64 characters, and neither.\n- Sort: relevance or none means newest in tag mode; views and popularity reorder; anything else is 400.\n- `page` and `limit` with the `SEARCH_MAX_LIMIT` cap.\n- `total`: exact and pre-moderation in tag mode, against the 200-candidate pool in text mode.\n- `vectorSearch` is false in tag mode.\n- Every listing row now carries `tags`: in the uploader's order, `[]` for NULL, invalid or non-list values.\n\nExtend line 53 so the NSFW filter also covers tag search.\n- [ ] `client/README.md` - - Line 34: `/api/v1/search/videos` also allowlists `tag`, which is stripped and dropped when empty.\n- Line 29: blocks and reaction marks apply to tag results (no dislike removal, no over-fetch).\n- [ ] `client/frontend/README.md` - - Feed, search and up-next cards show tag chips linking to `/search.html?tag=\u2026`, fitted to one line with a `+N` marker. Video-page tags become links.\n- The search page's tag mode:\n  - the heading and the title format\n  - the \"Showing X of Y videos tagged \u2026\" and \"No videos tagged \u2026\" status lines\n  - relevance hidden, with `published_at` as the default\n  - `tag` and `sort` kept in the URL\n  - a submit leaving tag mode\n  - a URL with both `q` and `tag` reduced to `q`\n- Line 18: \"Showing N of M matched videos.\" applies to text search only.\n- Line 8: the gateway routes list is unchanged.\n- [ ] `client/frontend/src/data/search.ts` - The module docstring (1-9) says the gateway allowlists \"exactly five query parameters\". It becomes six, with `tag`, and the function sends exactly one of `q` and `tag`.\n- [ ] `CONTEXT.md` - Add a glossary entry for **Tag** / **tag search**:\n- the uploader's tags as stored in `videos.tags_json`\n- two tags are the same after trimming and lowercasing; language variants stay distinct\n- tag search is the exact-tag mode of the search route, distinct from the full-text match on the `tags_json` FTS column\n- [ ] `docs/project/roadmap.md` - After delivery, add a DONE line for issue 42's first plan (tags on cards and exact-tag search) pointing at `docs/project/plans/54-53-tags-on-cards-and-tag.md`. Note that multi-tag narrowing, feed and up-next tag filters, and advanced search remain open.\n- [ ] `docs/project/issues/42-tags-on-cards-and-tag-search.md` - Record what this plan delivered and what stays open. The issue stays open (`Status: enhancement, needs-triage` at line 3), because the operator expects more plans.\n- [ ] `docs/project/adr/0007-nsfw-filter-default-at-request-edge.md` - Optional: in Decision 2 (line 17), name the new tag-search function as a second `include_nsfw` callee of `_handle_search`.",
  "docs": [
    {
      "path": "engine/server/README.md",
      "note": "\"What it does\" (6-28) has no bullet for `GET /api/v1/search/videos`; only line 53 mentions it, for `nsfw`. Add one covering:\n- `q` text search.\n- The exclusive `tag` mode: an exact match after trimming and lowercasing both sides.\n- The 400s: both parameters, a blank tag, a tag over 64 characters, and neither.\n- Sort: relevance or none means newest in tag mode; views and popularity reorder; anything else is 400.\n- `page` and `limit` with the `SEARCH_MAX_LIMIT` cap.\n- `total`: exact and pre-moderation in tag mode, against the 200-candidate pool in text mode.\n- `vectorSearch` is false in tag mode.\n- Every listing row now carries `tags`: in the uploader's order, `[]` for NULL, invalid or non-list values.\n\nExtend line 53 so the NSFW filter also covers tag search."
    },
    {
      "path": "client/README.md",
      "note": "- Line 34: `/api/v1/search/videos` also allowlists `tag`, which is stripped and dropped when empty.\n- Line 29: blocks and reaction marks apply to tag results (no dislike removal, no over-fetch)."
    },
    {
      "path": "client/frontend/README.md",
      "note": "- Feed, search and up-next cards show tag chips linking to `/search.html?tag=\u2026`, fitted to one line with a `+N` marker. Video-page tags become links.\n- The search page's tag mode:\n  - the heading and the title format\n  - the \"Showing X of Y videos tagged \u2026\" and \"No videos tagged \u2026\" status lines\n  - relevance hidden, with `published_at` as the default\n  - `tag` and `sort` kept in the URL\n  - a submit leaving tag mode\n  - a URL with both `q` and `tag` reduced to `q`\n- Line 18: \"Showing N of M matched videos.\" applies to text search only.\n- Line 8: the gateway routes list is unchanged."
    },
    {
      "path": "client/frontend/src/data/search.ts",
      "note": "The module docstring (1-9) says the gateway allowlists \"exactly five query parameters\". It becomes six, with `tag`, and the function sends exactly one of `q` and `tag`."
    },
    {
      "path": "CONTEXT.md",
      "note": "Add a glossary entry for **Tag** / **tag search**:\n- the uploader's tags as stored in `videos.tags_json`\n- two tags are the same after trimming and lowercasing; language variants stay distinct\n- tag search is the exact-tag mode of the search route, distinct from the full-text match on the `tags_json` FTS column"
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "After delivery, add a DONE line for issue 42's first plan (tags on cards and exact-tag search) pointing at `docs/project/plans/54-53-tags-on-cards-and-tag.md`. Note that multi-tag narrowing, feed and up-next tag filters, and advanced search remain open."
    },
    {
      "path": "docs/project/issues/42-tags-on-cards-and-tag-search.md",
      "note": "Record what this plan delivered and what stays open. The issue stays open (`Status: enhancement, needs-triage` at line 3), because the operator expects more plans."
    },
    {
      "path": "docs/project/adr/0007-nsfw-filter-default-at-request-edge.md",
      "note": "Optional: in Decision 2 (line 17), name the new tag-search function as a second `include_nsfw` callee of `_handle_search`."
    }
  ],
  "reassessments": 3,
  "draft": "## Draft implementation: tags on cards and exact-tag search (issue 42, plan 54)\n\nI read these files before drafting: `data/search.py`, `handlers/similar.py` (1-160, 400-500), `handlers/video.py` (`to_tags_json` and `tags_from_json`), `server_config.py` (the SEARCH block), `client/backend/server.py` (the allowlist), `components/video-card.ts`, `pages/search/index.ts`, `search.html`, `data/search.ts`, `types/videos.ts`, `video.css` (380-609), `videos.css` (`.video-card`, `.video-link`, `.card-actions`), `base.css`, `pages/video-page/index.ts` (tags 290-304, `loadSimilarVideos`, `renderSimilarCard`, `applySimilarStatsToDom`), `pages/videos/index.ts` (55-68), `test_frontend_base_css.py`, `test_search.py`, `test_similar.py` (100-170), `test_frontend_video_page_similars.py` (130-169), and `conftest.identity_of`. The harness grep confirmed that no harness defines `MutationObserver`.\n\n### Decisions that differ from the high-level plan (named)\n\n1. **Chip CSS lives in `base.css`, not in a sheet imported by `video-card.ts`.** The operator approved this on 2026-10-04 via AskUser. A sheet imported from the component would make Vite emit a fifth `video-card-*.css` bundle, which breaks the pinned contract in `test_frontend_base_css.py:100,105-115`. Putting the rules in `base.css` still leaves one copy. It needs no new file and no new bundle, and the test needs no change: `base.css` is already inlined at the head of `videos.css`, `video.css` and `search.css`, and so of every page that shows chips. The channels page also carries about 25 unused lines. As a consequence, `video-card.ts` imports no CSS, and `test_frontend_reactions.py` needs no `--loader:.css=empty`.\n2. **`observeTagRows` does nothing when `MutationObserver` or `ResizeObserver` is undefined.** Every supported browser has both, and only the node harnesses lack them. This replaces adding stubs to five harnesses: `test_frontend_video_page.py` (two harnesses), `test_frontend_video_page_similars.py`, `test_frontend_translate.py` (two harnesses) and `test_frontend_videos_page.py` (two harnesses). Ceiling: no harness exercises the fit. The fit is covered by a dedicated unit case in `test_frontend_video_card.py` that stubs both observers. Upgrade path: stub the observers in a page harness if a page-level fit test is ever wanted.\n3. **Unlinkable stored tags.** A tag that is blank after trimming, or longer than 64 code points, would link to a guaranteed 400 (or to idle). `tagSearchUrl` returns `null` for such a tag.\n   - Cards skip it.\n   - The video page still lists it, as a plain `span.tag-chip` with no link, so the video page keeps listing every tag.\n   - Today no stored tag is over 64 characters (the longest is 30), so in practice only blank tags are affected.\n4. **The `total` count statement leaves out the `channels` LEFT JOIN.** That join cannot remove a row. It could only duplicate one if `channels` held duplicate keys, so leaving it out counts distinct matching videos. The page statement keeps the join, exactly as `lexical_candidates` does.\n5. **The FTS phrase is the `_TOKEN_SPLIT` tokens joined with spaces and quoted as one string literal, as the settled route says.** FTS5 re-tokenizes the literal with the table's own `unicode61` tokenizer, so tokens such as `foo_bar` are split again and the gap with the index shrinks. If every Python token turns out to be a separator to `unicode61`, the phrase is empty and matches nothing. That is the accepted Rt1 risk.\n6. **A popstate into the idle state no longer pushes a history entry.** `showIdle` gains a `updateUrl = true` parameter, and `popstate` passes `false`. This is a pre-existing bug, but the tag-mode `popstate` path runs through the same function, and leaving it in would destroy forward history after back-navigation.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/server_config.py` | + `SEARCH_MAX_TAG_LENGTH = 64` |\n| `engine/server/data/search.py` | + `TAG_TRIM_SQL`, `TAG_MATCH_SQL`, `tag_match_expression`, `search_videos_by_tag`; docstrings |\n| `engine/server/api/handlers/similar.py` | `stable_video_row` adds `tags`; `_handle_search` tag branch; imports; docstrings |\n| `engine/server/api/router.py` | docstring line 11 only |\n| `client/backend/server.py` | allowlist line 104 gains `\"tag\"` |\n| `client/frontend/src/base.css` | + `.tag-chip`, `a.tag-chip:hover`, `.card-tags`, `.card-tags > *`, `.tag-more` |\n| `client/frontend/src/video.css` | \u2212 `.tag-chip`; `.similar-card-item` loses link styling; + `.similar-card-link` |\n| `client/frontend/src/videos.css` | + `.video-card > .card-tags` padding |\n| `client/frontend/src/search.css` | + `.search-tag` |\n| `client/frontend/search.html` | + `<h2 id=\"search-tag\" class=\"search-tag\" hidden></h2>` |\n| `client/frontend/src/components/video-card.ts` | + `tagSearchUrl`, `renderTagChips`, `observeTagRows` (private `fitTagRow`); `renderVideoCard` appends the chip row |\n| `client/frontend/src/types/videos.ts` | `VideoRow.tags?: string[] \\| null`; `SearchPayload` docstring |\n| `client/frontend/src/data/search.ts` | `q?`, `tag?`; sends exactly one; docstring says six parameters |\n| `client/frontend/src/pages/search/index.ts` | tag mode |\n| `client/frontend/src/pages/videos/index.ts` | `observeTagRows(cards)` |\n| `client/frontend/src/pages/video-page/index.ts` | linked tag chips; `renderSimilarCard` div + link + chips; `observeTagRows(similarCards)` |\n| `client/frontend/dist/` | rebuilt with `vite build` (no local `dev-pages/about.html`) and committed |\n\nNo new module, table or dependency.\n\n### Engine\n\n**`server_config.py`**, after line 460:\n\n```python\nSEARCH_MAX_TOKEN_LENGTH = 64\n# Longest tag the exact-tag mode accepts, in characters after trimming; the longest stored tag is 30.\nSEARCH_MAX_TAG_LENGTH = 64\n```\n\n**`data/search.py`**, beside `lexical_candidates`:\n\n```python\n# Whitespace both sides of a tag comparison lose. SQLite's one-argument trim() removes only spaces.\nTAG_TRIM_SQL = \"' ' || char(9, 10, 13)\"\n\n# True when the row's tag list holds the bound tag once both are trimmed and lowercased. The same SQL\n# expression normalises both sides, so they cannot disagree. CASE short-circuits, so json_type and\n# json_each never see malformed JSON (json_each would raise and fail the whole query); non-arrays\n# become an empty list, and only string elements compare.\nTAG_MATCH_SQL = f\"\"\"EXISTS (\n  SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) THEN CASE json_type(v.tags_json) WHEN 'array' THEN v.tags_json ELSE '[]' END ELSE '[]' END) j\n  WHERE j.type = 'text' AND lower(trim(j.value, {TAG_TRIM_SQL})) = lower(trim(?, {TAG_TRIM_SQL}))\n)\"\"\"\n\n\ndef tag_match_expression(tag: str) -> str:\n    \"\"\"Build the FTS5 prefilter for one tag: a column filter on tags_json holding one quoted phrase.\n\n    The phrase is a string literal with its quotes doubled, as in :func:`sanitize_query`, so a tag\n    cannot inject operators. Empty when the tag has no word character, which sends the caller to\n    the full-scan fallback.\n    \"\"\"\n    tokens = [token for token in _TOKEN_SPLIT.split(tag) if token]\n    if not tokens:\n        return \"\"\n    return 'tags_json : \"' + \" \".join(tokens).replace('\"', '\"\"') + '\"'\n\n\ndef search_videos_by_tag(\n    server: Any,\n    tag: str,\n    page: int,\n    limit: int,\n    sort: str = \"published_at\",\n    include_nsfw: bool = True,\n) -> tuple[list[dict[str, Any]], int]:\n    \"\"\"Return one page of the videos carrying ``tag`` exactly, plus the exact match count.\n\n    FTS narrows to the rows whose tags_json holds the tag's words, and :data:`TAG_MATCH_SQL` keeps\n    only true tag matches. A tag with no word character has no FTS token, so it scans every row\n    (about 0.7 s on the full dataset). `total` counts every allowed match, so the page can draw\n    exact paging.\n\n    :param tag: Tag as the caller sent it, already stripped.\n    :param sort: A key of :data:`LEXICAL_SORTS`.\n    :param include_nsfw: False leaves NSFW-flagged rows out of the page and the count.\n    :returns: ``(rows_for_page, total_matches)``.\n    \"\"\"\n    match_expression = tag_match_expression(tag)\n    if match_expression:\n        source = \"videos_fts f JOIN videos v ON v.rowid = f.rowid\"\n        where = f\"videos_fts MATCH ? AND {TAG_MATCH_SQL}\"\n        args: list[Any] = [match_expression, tag]\n    else:\n        source = \"videos v\"\n        where = TAG_MATCH_SQL\n        args = [tag]\n    if not include_nsfw:\n        where += f\" AND {NSFW_ALLOWED_SQL}\"\n    order_by = LEXICAL_SORTS[sort]\n    offset = max(0, (page - 1) * limit)\n\n    conn, lock = search_connection(server)\n    with lock:\n        with search_deadline(server):\n            if not fts_available(conn):\n                raise SearchIndexMissing(\n                    \"videos_fts is not present in this database; run the dataset build's \"\n                    \"sync stage to create it.\"\n                )\n            query = conn.execute(\n                f\"\"\"\n                SELECT\n                {VIDEO_ROW_SQL}\n                FROM {source}\n                LEFT JOIN channels c\n                  ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain\n                WHERE {where}\n                ORDER BY {order_by}\n                LIMIT ? OFFSET ?\n                \"\"\",\n                (*args, limit, offset),\n            )\n            rows = [dict(row) for row in query]\n            total = conn.execute(f\"SELECT COUNT(*) FROM {source} WHERE {where}\", args).fetchone()[0]\n\n    logging.info(\"[search] tag prefilter=%s rows=%d total=%d sort=%s\", bool(match_expression), len(rows), total, sort)\n    return rows, int(total)\n```\n\nInvariants:\n- Every caller value is bound as a parameter. Only module constants are formatted into the SQL.\n- The tag is bound already Python-stripped and the SQL trims it again, so NBSP padding on a direct Engine call still matches and stored tags are normalised the same way.\n- `sort` must be a `LEXICAL_SORTS` key; the handler guarantees this.\n- The function defaults to `include_nsfw=True`, as ADR-0007 decision 1 requires.\n\nDocstrings:\n- The module docstring gains one paragraph: \"The exact-tag mode (`search_videos_by_tag`) is not ranked: it filters to one tag and orders by date, views or popularity.\"\n- The `search_videos` docstring says it covers text search only.\n\n**`handlers/similar.py`**\n- Line 27 becomes `from data.search import LEXICAL_SORTS, SearchIndexMissing, search_videos, search_videos_by_tag`.\n- Add `SEARCH_MAX_TAG_LENGTH` to the `server_config` import.\n- Add `from handlers.video import tags_from_json`. There is no cycle: `router` already imports `handlers.video`, and `video.py` imports only `data.*`, `http_utils` and `server_config`.\n- Docstring line 3: \"hybrid video search\" becomes \"video search (hybrid text, or exact tag)\".\n\n```python\ndef stable_video_row(row: dict[str, Any]) -> dict[str, Any]:\n    \"\"\"Project a row to stable fields returned to clients, plus its tags parsed from tags_json.\"\"\"\n    stable = {field: row.get(field) for field in STABLE_VIDEO_FIELDS}\n    stable[\"tags\"] = tags_from_json(row.get(\"tags_json\"))\n    return stable\n```\n\n`_handle_search`. The docstring becomes: \"Answer a video search request: hybrid text search on `q`, or exact-tag search on `tag`; the two never combine.\" After the `SEARCH_ENABLED` gate:\n\n```python\n        raw_query = (params.get(\"q\", [\"\"])[0] or \"\").strip()\n        tag = (params.get(\"tag\", [\"\"])[0] or \"\").strip()\n        tag_mode = \"tag\" in params\n        if tag_mode and \"q\" in params:\n            respond_json(self, 400, {\"error\": \"Use either q or tag, not both\"})\n            return\n        if tag_mode and not tag:\n            respond_json(self, 400, {\"error\": \"Empty tag parameter\"})\n            return\n        if len(tag) > SEARCH_MAX_TAG_LENGTH:\n            respond_json(self, 400, {\"error\": f\"Tag longer than {SEARCH_MAX_TAG_LENGTH} characters\"})\n            return\n        if not tag_mode and not raw_query:\n            respond_json(self, 400, {\"error\": \"Missing query parameter q\"})\n            return\n\n        sort = params.get(\"sort\", [\"relevance\"])[0] or \"relevance\"\n        if sort not in LEXICAL_SORTS and sort != \"relevance\":\n            respond_json(self, 400, {\"error\": \"Unsupported sort\"})\n            return\n        # Tag results have no relevance to rank by; text search keeps relevance, which switches on its vector half.\n        if tag_mode and sort == \"relevance\":\n            sort = \"published_at\"\n\n        # limit / page parsing unchanged\n\n        # Search never enters _handle_similar, so no request context carries the flag here.\n        include_nsfw = _parse_include_nsfw(params.get(\"nsfw\", [None])[0])\n        try:\n            if tag_mode:\n                rows, total = search_videos_by_tag(self.server, tag, page=page, limit=limit, sort=sort, include_nsfw=include_nsfw)\n            else:\n                rows, total = search_videos(\n                    self.server,\n                    raw_query,\n                    # ... the arguments are unchanged ...\n                    include_nsfw=include_nsfw,\n                )\n        except SearchIndexMissing as exc:\n            # unchanged\n        # moderation unchanged\n        encoder = getattr(self.server, \"query_encoder\", None)\n        respond_json(self, 200, {\n            # ...\n            \"sort\": sort,\n            \"vectorSearch\": bool(not tag_mode and encoder is not None and encoder.enabled),\n            \"rows\": stable_video_rows(filtered_rows),\n        })\n```\n\nNotes on the handler:\n- `parse_qs` drops blank values, so `?tag=` is absent and reaches the \"Missing query parameter q\" branch. `?tag=%20` is present, strips to empty, and gets \"Empty tag parameter\".\n- `?q=%20&tag=x` carries both and gets a 400.\n- The length check runs on the stripped value and counts code points (Python `len`).\n- Text mode is byte-for-byte the previous behaviour.\n\n**`router.py` line 11:** `GET /api/v1/search/videos: hybrid text search (q) or exact-tag search (tag). [rate-limit gate]`\n\n### Gateway\n\n`client/backend/server.py:104` becomes `\"/api/v1/search/videos\": {\"q\", \"page\", \"limit\", \"sort\", \"nsfw\", \"tag\"},`. Everything else is inherited:\n- `tag` is stripped, and dropped when empty.\n- Because the route is in `FILTERED_ROUTES`, blocks and reaction marks apply.\n- `_filter_payload` passes `tags` through.\n\n### Frontend\n\n**`base.css`** (appended after `.visually-hidden`):\n\n```css\n/* Tag chips: the video page's full list and every card's one-line row. Chips are links, so the link look is reset here. */\n.tag-chip {\n  padding: 0.12rem 0.55rem;\n  border-radius: 999px;\n  border: 1px solid var(--line);\n  background: rgba(255, 255, 255, 0.6);\n  color: var(--ink);\n  font-size: 0.8rem;\n  text-decoration: none;\n  white-space: nowrap;\n}\n\na.tag-chip:hover {\n  border-color: var(--accent);\n}\n\n/* One line on a card. observeTagRows in components/video-card.ts hides the chips that do not fit, from the end, and counts them in .tag-more. */\n.card-tags {\n  display: flex;\n  gap: 0.35rem;\n  align-items: center;\n  overflow: hidden;\n  min-width: 0;\n}\n\n/* Only flex-shrink, never display, so the hidden attribute still hides a chip. */\n.card-tags > * {\n  flex-shrink: 0;\n}\n\n.tag-more {\n  color: var(--muted);\n  font-size: 0.8rem;\n  white-space: nowrap;\n}\n```\n\nBefore the fit runs, the row is clipped by `overflow: hidden` and never wraps. No `[hidden]` override is needed, because no chip rule sets `display`.\n\n**`video.css`:**\n- Delete `.tag-chip` (408-415).\n- `.tag-list` stays as it is, with `flex-wrap: wrap`.\n- `.similar-card-item` keeps `display:flex; flex-direction:column; gap:0.5rem; padding; border-radius; border; background; transition` and loses `text-decoration` and `color`.\n- `.similar-card-item:hover` is unchanged.\n- New rule:\n  ```css\n  .similar-card-link {\n    display: flex;\n    flex-direction: column;\n    gap: 0.5rem;\n    text-decoration: none;\n    color: inherit;\n  }\n  ```\n\n**`videos.css`**, after `.card-actions`: `.video-card > .card-tags { padding: 0 1.05rem 0.9rem; }`. This matches the inset of `.card-actions`.\n\n**`search.css`:** `.search-tag { margin: 0 0 0.6rem; font-size: 1.2rem; }`. The sheet still opens with `@import \"./base.css\"`.\n\n**`search.html`:** `<h2 id=\"search-tag\" class=\"search-tag\" hidden></h2>` as the first child of `<section class=\"search-controls\">`. The CSP is unchanged, and no inline style is emitted anywhere.\n\n**`types/videos.ts`:**\n- Add `/** The uploader's tags, in their order; absent on rows cached before the Engine sent them. */ tags?: string[] | null;` to `VideoRow`.\n- The `SearchPayload` docstring now says: \"In text search, `total` counts the fused candidate pool; in tag search it is the exact count of matching videos before moderation and profile filters.\"\n\n**`components/video-card.ts`.** The module docstring gains: \"It also renders the tag chip row every card shows, and fits it to one line.\" New code goes after `videoPageUrl`:\n\n```ts\n/** Longest tag the Engine's tag search accepts (SEARCH_MAX_TAG_LENGTH); a longer one would link to a 400. */\nconst TAG_MAX_LENGTH = 64;\n\n/**\n * Build the link to the search page's results for one tag, or null when the tag cannot be searched (blank, or longer than the Engine accepts).\n *\n * `apiParam` is propagated only in a dev build, by the rule of `videoPageUrl`.\n */\nexport function tagSearchUrl(tag: string, apiParam?: string | null) {\n  const value = tag.trim();\n  // Counted in code points, as the Engine's len() counts them.\n  if (!value || Array.from(value).length > TAG_MAX_LENGTH) return null;\n  const params = new URLSearchParams();\n  params.set(\"tag\", value);\n  if (apiParam && import.meta.env.DEV) params.set(\"api\", apiParam);\n  return `/search.html?${params.toString()}`;\n}\n\n/**\n * Render a card's tag row: one link per searchable tag in the uploader's order, then a hidden `+N` marker that observeTagRows fills.\n *\n * Returns \"\" when there is no tag to show, so a card without tags has no tag line. Tags come from remote instances, so every value is escaped.\n */\nexport function renderTagChips(tags: VideoRow[\"tags\"], apiParam?: string | null) {\n  if (!Array.isArray(tags)) return \"\";\n  const chips = tags.flatMap((tag) => {\n    if (typeof tag !== \"string\") return [];\n    const href = tagSearchUrl(tag, apiParam);\n    return href ? [`<a class=\"tag-chip\" href=\"${escapeHtml(href)}\">${escapeHtml(tag)}</a>`] : [];\n  });\n  if (!chips.length) return \"\";\n  return `<div class=\"card-tags\">${chips.join(\"\")}<span class=\"tag-more\" hidden></span></div>`;\n}\n\n/**\n * Show every chip, then hide chips from the end until the rest and the `+N` marker fit the row's width.\n */\nfunction fitTagRow(row: HTMLElement) {\n  const chips = Array.from(row.querySelectorAll<HTMLElement>(\".tag-chip\"));\n  const more = row.querySelector<HTMLElement>(\".tag-more\");\n  if (!more) return;\n  for (const chip of chips) chip.hidden = false;\n  more.hidden = true;\n  let hidden = 0;\n  while (hidden < chips.length && row.scrollWidth > row.clientWidth) {\n    hidden += 1;\n    chips[chips.length - hidden].hidden = true;\n    more.textContent = `+${hidden}`;\n    more.setAttribute(\"aria-label\", `${hidden} more ${hidden === 1 ? \"tag\" : \"tags\"}`);\n    more.hidden = false;\n  }\n}\n\nlet tagRowResizer: ResizeObserver | null = null;\n/** The width each row was last fitted at, so a height-only change does not re-fit it. */\nconst fittedWidths = new WeakMap<Element, number>();\n\n/**\n * Fit every card tag row that enters `container`, now or later, once it has a layout and again whenever its width changes.\n *\n * Cards reach the grids by innerHTML, insertAdjacentHTML and outerHTML from many places, so one observer per container finds them instead of a call after each render. Outside a browser (the node test harnesses) the observers are absent and this does nothing.\n */\nexport function observeTagRows(container: HTMLElement) {\n  if (typeof MutationObserver === \"undefined\" || typeof ResizeObserver === \"undefined\") return;\n  tagRowResizer ??= new ResizeObserver((entries) => {\n    for (const entry of entries) {\n      const width = entry.contentRect.width;\n      if (fittedWidths.get(entry.target) === width) continue;\n      fittedWidths.set(entry.target, width);\n      fitTagRow(entry.target as HTMLElement);\n    }\n  });\n  const resizer = tagRowResizer;\n  const rowsIn = (node: Node) =>\n    node instanceof HTMLElement\n      ? node.matches(\".card-tags\") ? [node] : Array.from(node.querySelectorAll<HTMLElement>(\".card-tags\"))\n      : [];\n  for (const row of rowsIn(container)) resizer.observe(row);\n  new MutationObserver((records) => {\n    for (const record of records) {\n      record.addedNodes.forEach((node) => rowsIn(node).forEach((row) => resizer.observe(row)));\n      record.removedNodes.forEach((node) => rowsIn(node).forEach((row) => resizer.unobserve(row)));\n    }\n  }).observe(container, { childList: true, subtree: true });\n}\n```\n\nWhy the observers cannot loop:\n- `hidden` toggles are attribute mutations, which the `childList` observer ignores.\n- The marker's text-node change yields no `.card-tags` row.\n- The width memo stops a re-fit after the fit's own height change.\n\nObserver lifetime: there is one shared `ResizeObserver` per page, created lazily, never at module level. The `MutationObserver`s are not stored, because their containers live as long as the page.\n\n`renderVideoCard`: line 416 becomes `</a>${renderTagChips(row.tags, options.apiParam)}${actionsMarkup}`. The chip row sits outside the link, as the sibling just before `card-actions`. The card body is unchanged.\n\n**`pages/videos/index.ts`:** add `observeTagRows` to the import. After the guard at 66-68, add `observeTagRows(cards);`. The delegated click handler acts only on `[data-card-action]`, so a chip click is a plain link.\n\n**`pages/video-page/index.ts`:**\n- Import `observeTagRows`, `renderTagChips` and `tagSearchUrl` from `../../components/video-card`.\n- After the `params` declaration (82): `if (similarCards) observeTagRows(similarCards);`\n- Tag chips (290-300):\n\n```ts\n      // Tags come from remote instances, so each chip is built from text, never from markup; a tag the search cannot take stays a plain chip.\n      tagsEl.replaceChildren(\n        ...tags.map((tag) => {\n          const href = tagSearchUrl(tag, params.get(\"api\"));\n          const chip = document.createElement(href ? \"a\" : \"span\");\n          chip.className = \"tag-chip\";\n          chip.textContent = tag;\n          if (href) (chip as HTMLAnchorElement).href = href;\n          return chip;\n        })\n      );\n```\n\n`renderSimilarCard`:\n\n```ts\n  return `\n    <div class=\"similar-card-item\"${keyAttribute}>\n      <a class=\"similar-card-link\" href=\"${escapeHtml(videoPageUrl(row))}\">\n        <div class=\"similar-thumb\">\n          ${thumbMarkup}\n          <span class=\"duration\">${escapeHtml(duration)}</span>\n        </div>\n        <h4 class=\"similar-title\">${escapeHtml(title)}</h4>\n        <p class=\"similar-channel\">${escapeHtml(channel)}</p>\n        <p class=\"similar-meta\"><span data-stat=\"views\">${formatStatValue(views)}</span> views${escapeHtml(timeSuffix)}</p>\n        ${reactionMarkup}\n      </a>\n      ${renderTagChips(row.tags, params.get(\"api\"))}\n    </div>\n  `;\n```\n\n`applySimilarStatsToDom` still finds `[data-video-key]` (now on the div) and the `data-stat=\"views\"` span inside it.\n\n**`data/search.ts`:**\n- Docstring: \"exactly six query parameters (`q`, `tag`, `page`, `limit`, `sort`, `nsfw`)\". It now also says: \"A request carries exactly one of `q` and `tag`.\"\n- `FetchSearchOptions` becomes `q?: string; tag?: string;`.\n- In `fetchSearchResults`:\n\n```ts\n  const tag = (options.tag ?? \"\").trim();\n  // Exactly one of the two: the Engine answers 400 to both. Without a tag, q is sent exactly as before.\n  if (tag) url.searchParams.set(\"tag\", tag);\n  else url.searchParams.set(\"q\", (options.q ?? \"\").trim());\n```\n\nThe cache key `search:${url}` keeps tag pages apart from text pages.\n\n**`pages/search/index.ts`** (tag mode):\n- The module docstring line 6 becomes: \"...until the Engine's candidate pool (text) or match set (tag) is exhausted. A `tag` in the URL, with no `q`, lists the videos carrying that exact tag; submitting the box leaves tag mode.\"\n- New elements and the `TAG_DEFAULT_SORT` constant:\n\n```ts\nconst tagHeading = requireElement<HTMLElement>(\"search-tag\");\nconst relevanceOption = sortSelect.querySelector<HTMLOptionElement>('option[value=\"relevance\"]');\nif (!relevanceOption) throw new Error(\"Missing search page element: relevance sort option\");\nconst TAG_DEFAULT_SORT: SearchSort = \"published_at\";\n```\n\n- `state`:\n  - `query: (params.get(\"q\") ?? \"\").trim()`\n  - new `tag: \"\"`\n  - `sort: \"relevance\" as SearchSort`\n  - After the declaration: `state.tag = state.query ? \"\" : (params.get(\"tag\") ?? \"\").trim(); state.sort = resolveSort(params.get(\"sort\"), Boolean(state.tag));`. A URL carrying both keeps `q`.\n- Remove `input.value = \u2026; sortSelect.value = \u2026;` (75-76). `applyMode()` does both.\n- Submit: `startSearch(next, \"\", state.sort);`. The relevance option comes back through `applyMode`. A tag-mode sort (published_at, views or popularity) is valid in text mode too. An empty submit calls `showIdle()`, which also clears `tag`.\n- Sort change:\n\n```ts\nsortSelect.addEventListener(\"change\", () => {\n  if (!state.query && !state.tag) return;\n  startSearch(state.query, state.tag, resolveSort(sortSelect.value, Boolean(state.tag)));\n});\n```\n\n- After the results click listener: `observeTagRows(results);`. This covers the reset, appends, `outerHTML` re-renders and `removeRows`.\n- `popstate`:\n\n```ts\nwindow.addEventListener(\"popstate\", () => {\n  const current = new URLSearchParams(window.location.search);\n  state.query = (current.get(\"q\") ?? \"\").trim();\n  state.tag = state.query ? \"\" : (current.get(\"tag\") ?? \"\").trim();\n  state.sort = resolveSort(current.get(\"sort\"), Boolean(state.tag));\n  if (!state.query && !state.tag) {\n    // The address bar already holds this entry; pushing would drop the forward history.\n    showIdle(false);\n    return;\n  }\n  applyMode();\n  void loadPage(1, true);\n});\n```\n\n- Initial load:\n\n```ts\nif (state.query || state.tag) {\n  applyMode();\n  // A hand-made URL carrying both keeps q; drop tag so the Engine never sees the pair it refuses.\n  if (state.query && params.has(\"tag\")) pushUrl(true);\n  void loadPage(1, true);\n} else {\n  showIdle();\n}\n```\n\n- `startSearch(query: string, tag: string, sort: SearchSort)` sets `query`, `tag`, `sort` and `page = 1`, then runs `applyMode(); pushUrl(); void loadPage(1, true);`.\n- New `applyMode()`:\n\n```ts\n/**\n * Show the mode the state is in: the tag heading, the sort menu (no relevance for tag results), the box and the title.\n */\nfunction applyMode() {\n  const tagMode = Boolean(state.tag);\n  relevanceOption.hidden = tagMode;\n  relevanceOption.disabled = tagMode;\n  tagHeading.hidden = !tagMode;\n  tagHeading.textContent = tagMode ? `Videos tagged \"${state.tag}\"` : \"\";\n  input.value = state.query;\n  sortSelect.value = state.sort;\n  document.title = tagMode\n    ? `${state.tag} - Tag - Search - PeerTube - Browser`\n    : state.query\n      ? `${state.query} - Search - PeerTube - Browser`\n      : \"Search - PeerTube - Browser\";\n}\n```\n\n- `loadPage`:\n  - Fetch with `fetchSearchResults({ q: state.query, tag: state.tag, page, limit: PAGE_SIZE, sort: state.sort, apiBase: apiParam })`.\n  - Empty result: `setStatus(state.tag ? \\`No videos tagged \"${state.tag}\".\\` : \\`No results for \"${state.query}\".\\`);`.\n  - Results: `setStatus(state.tag ? \\`Showing ${state.loadedRows} of ${state.total} videos tagged \"${state.tag}\".\\` : \\`Showing ${state.loadedRows} of ${state.total} matched videos.\\`);`.\n  - The comment at 231-232 becomes: \"In text search `total` is the fused candidate pool, not a corpus count; in tag search it is the exact match count before moderation and blocks.\"\n  - `hasMore` is unchanged.\n  - All status text goes through `textContent`.\n- `showIdle(updateUrl = true)`:\n  - Also clears `state.tag`.\n  - Calls `applyMode()` in place of the title line. Its `sort` is kept as `state.sort` when valid in text mode, which is always.\n  - Calls `pushUrl()` only when `updateUrl` is true.\n- `pushUrl`:\n\n```ts\n  if (state.query) next.set(\"q\", state.query);\n  else if (state.tag) next.set(\"tag\", state.tag);\n  if (state.sort !== (state.tag ? TAG_DEFAULT_SORT : \"relevance\")) next.set(\"sort\", state.sort);\n```\n\n- `resolveSort(value, tagMode = false)`:\n\n```ts\nfunction resolveSort(value: string | null, tagMode = false): SearchSort {\n  const candidate = (value ?? \"\").trim() as SearchSort;\n  // Tag results have no relevance; it means newest there, as the Engine reads it.\n  if (!SORTS.includes(candidate) || (tagMode && candidate === \"relevance\")) return tagMode ? TAG_DEFAULT_SORT : \"relevance\";\n  return candidate;\n}\n```\n\nLimitation (named): a hand-made tag over 64 characters reaches the Engine, gets a 400, and the page shows the generic \"Search failed\" line.\n\n### What the build must test\n\nEngine data layer: extend `tests/active/test_search.py`, or add a sibling `test_search_tags.py` with its own fixture. Either way the reads run on `ENGINE_PY` through the real `sqlite3`.\n- The fixture holds rows whose `tags_json` is:\n  - `[\"Linux\",\" linux \",\"x\"]`\n  - `[\"LINUX\"]`\n  - `[\"linuxmint\"]`\n  - `[\"M\u00daSICA\"]` against `[\"m\u00fasica\"]`\n  - `[\"???\"]`\n  - `[\"\\t???\\n\"]`\n  - malformed `[`\n  - an object `{\"a\":\"linux\"}`\n  - `[1, \"linux\"]` with a non-text element\n  - NULL\n  - an NSFW row tagged linux\n  - a row whose description says linux but whose tags do not\n- Cases:\n  1. `linux` matches exactly the rows carrying linux under trim and case. `linuxmint`, description-only, malformed, object and NULL rows are absent, and the malformed row raises nothing.\n  2. `m\u00fasica` matches `M\u00daSICA`, which is the Unicode `lower()` check. If it fails, the SQLite build folds ASCII only.\n  3. `???` takes the fallback (assert `tag_match_expression(\"???\") == \"\"`) and matches both stored forms.\n  4. Default order is `published_at DESC, video_id DESC`, and `views` and `popularity` follow `LEXICAL_SORTS`.\n  5. With `include_nsfw=False`, the NSFW row is missing from both the rows and `total`.\n  6. Paging: pages cover the match set with no overlap; a page past the end gives `[]` and the full `total`.\n  7. With no `videos_fts`, the function raises `SearchIndexMissing`.\n  8. `tag_match_expression('a\"b')` quotes safely.\n\nEngine route (`test_similar.py`, live Engine):\n- AC1:\n  - Extend the `route` parametrisation to trending, popular, recent and following (with a `follows` body) as well as home, random, upnext and search.\n  - Every row has `tags` as a list of strings equal to `tags_from_json` of the stored `tags_json`.\n  - Add a `tags_json` read beside `identity_of` in `conftest.py`.\n- AC7: 400 with a JSON `error` for:\n  - `q`+`tag`\n  - `tag=%20`\n  - a 65-character tag\n  - no parameter (`?tag=` included)\n- AC4: a stored tag fetched with `?tag=<Upper-cased>`:\n  - every row carries it\n  - `sort` echoes `published_at` for none and relevance\n  - `views` reorders\n  - `sort=bogus` gives 400\n  - `vectorSearch` is false\n- AC5: `total` equals a direct `COUNT` on `whitelist.db` under `nsfw` off, and text search's `total` stays \u2264 200.\n\nGateway (`test_server.py` or the blocks test): `tag` is forwarded, and a blocked channel's video is missing from tag results.\n\nFrontend unit (`test_frontend_video_card.py`):\n- `tagSearchUrl`:\n  - encoding (`a b&c` gives `tag=a+b%26c`)\n  - `api` present only with DEV\n  - `null` for a blank tag and for a 65-code-point tag\n- `renderTagChips`:\n  - `\"\"` for undefined, null, `[]` and blank-only lists\n  - `<script>` arrives escaped\n  - there is no `style=`\n  - the marker is `hidden`\n  - chip order is the uploader's\n- `renderVideoCard`: the `.card-tags` row sits after `</a>` and never inside `video-link`.\n- Fit (stub `ResizeObserver`/`MutationObserver` and widths): five chips with room for two give two visible chips, `+3` and `aria-label=\"3 more tags\"`; a wider row re-fits.\n\nFrontend pages:\n- `test_frontend_video_page.py`: the chips are `a.tag-chip` with `href=/search.html?tag=\u2026` and no `api` when DEV is false.\n- `test_frontend_video_page_similars.py`:\n  - Retarget both regexes to `<div \u2026 similar-card-item \u2026>`, which still carries `data-video-key`.\n  - The docstring's \"anchors\" becomes \"cards\".\n\nBuild:\n- `test_frontend_base_css.py` and `test_frontend_dist.py` pass unchanged after `dist` is rebuilt.\n- There is no search-page harness. Tag mode is checked by hand: load, sort, back, reload, submit, and a `q`+`tag` URL.\n\n`tests/config.json` mappings:\n- `engine/server/api/handlers/video.py` \u2192 the `test_similar.py` group.\n- `components/video-card.ts` \u2192 the video-page, similars and translate groups.\n- `src/base.css` \u2192 already in base-css and dist; confirm.\n- `server_config.py` \u2192 `test_search.py`.\n- Any new test file gets its own mapping.\n\n### Check against the plan and the requirements\n\n| Item | Met by |\n|---|---|\n| AC1 | `stable_video_row` + `tags_from_json`; both callers (search, `_respond_rows`) |\n| AC2 | `renderTagChips` + `observeTagRows`/`fitTagRow`; escape; `\"\"` on no tags; measured after insertion and on width change |\n| AC3 | `a.tag-chip` outside every video link; `/search.html?tag=` via `URLSearchParams`; DEV-only `api` |\n| AC4 | `TAG_MATCH_SQL` normalises both sides in SQL; relevance/none \u2192 `published_at`; bad sort 400 |\n| AC5 | `LIMIT/OFFSET` + `COUNT(*)` before moderation; text pool untouched |\n| AC6 | `include_nsfw` from `_parse_include_nsfw`; shared moderation; route already in `FILTERED_ROUTES` |\n| AC7 | four 400 branches |\n| AC8 | heading, title, relevance hidden, URL `tag`/`sort` with newest omitted, sort and popstate in tag mode, submit leaves tag mode, allowlist |\n| AC9 | `tag_match_expression` \u2192 `\"\"` \u2192 full scan |\n| Consistency | `escapeHtml` on every interpolation; `textContent` for DOM chips; no new table, dependency or module |\n\nConverged in one pass. The deviations are the six decisions named at the top; only the first changes an approved design, and the operator approved it.\n\n### Documentation the build updates\n\nThese are the settled items. With chips in `base.css`, `client/frontend/README.md` gains a line saying the chip rules live in the shared base.\n- `engine/server/README.md`:\n  - a search route bullet (`q`/`tag`, the 400s, sorts, `total`, `vectorSearch`, `tags` on every row)\n  - line 53 extended to say the NSFW filter covers tag search\n- `client/README.md`, lines 29 and 34.\n- `client/frontend/README.md`:\n  - card chips, linked video-page chips, search tag mode\n  - line 18 scoped to text search\n- `data/search.ts` docstring (above).\n- `CONTEXT.md`: a **Tag** / **tag search** entry.\n- `docs/project/roadmap.md`: a DONE line plus the open items.\n- `docs/project/issues/42-\u2026md`: what was delivered and what stays open; the status is unchanged.\n- ADR-0007 Decision 2 (optional): name `search_videos_by_tag`.\n"
}
```
dev-flow:state -->

## 2026-10-06 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/55",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Start snapshot: tree `735491f39f21a2cc67a11d6825721c977707610b` at 2026-10-06T09:15:51-04:00.

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 68 test groups (67 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-06 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

The operator wants chips clickable on every card (Scope), but `renderVideoCard` wraps the card in one `<a class="video-link">` and its comment rules out controls inside it, and `renderSimilarCard` is a single `<a>`. The operator approved the fix on 2026-10-04: chips go outside the card link, and the up-next card is wrapped in a container.
The draft's tag URL `/search?tag=<tag>` conflicts with the tree: every nav link uses `/search.html`, and only the Vite dev server rewrites `/search`. The operator approved `/search.html?tag=<tag>` on 2026-10-04.
The draft's AC5 says `total` is "the exact count of matches", but `_handle_search` counts `total` before `apply_serving_moderation_filters`, and the gateway removes blocked rows afterwards. The operator approved defining `total` as the count of NSFW-allowed matches before moderation and profile blocks, matching text search, on 2026-10-04.

## 2026-10-06 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-10-06 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

Note on the tree: `/home/enduser/code/PeerTube-browser/.worktrees/55` does not exist. Read gives `FileNotFoundError` and Glob finds nothing under `.worktrees/`. I opened every file below in the main checkout `/home/enduser/code/PeerTube-browser`, and paths are relative to the repo root. `tests/config.json` line 3 names `.worktrees/55` as `project_dir`, so the build is expected to run there once the worktree is created.

<impact path="engine/server/api/handlers/similar.py" element="stable_video_row (129-131) and stable_video_rows (134-136); new import of tags_from_json">
**What changes**
- `stable_video_row` returns `{field: row.get(field) for field in STABLE_VIDEO_FIELDS}` plus `"tags": tags_from_json(row.get("tags_json"))`.
- Add `from handlers.video import tags_from_json`, or whatever import form `similar.py` uses for sibling handler modules. Check how `router.py` imports `handlers.video`: the plan says `video.py` imports nothing from `similar.py`, and that holds (video.py imports `data.*`, `http_utils`, `server_config` only, lines 9-21).
- `STABLE_VIDEO_FIELDS` (106-126) stays as it is.

**What depends on it**
- Callers: `_handle_search` (484) and `_respond_rows` (611). `_respond_rows` serves every `_handle_similar` path: random (640), recommendations mix, ordered feeds trending/popular/recent, following (cursor), up-next, the raw-vector route and the empty-mix fallback (call sites 640, 689, 720, 745, 753, 863, 937, 1057).
- `maybe_attach_debug` → `recommendations/debug.py:attach_debug_info` copies `{**stable, "debug": ...}`, so `tags` survives in debug mode.

**Row sources (verified to carry `tags_json`)**
- `data/metadata.py` `_select_metadata` (198) and `fetch_metadata` (49/91), used by up-next `_build_rows` (`similarity_candidates.py:425-464` spreads `{**meta, "score"}`), the random cache and vector search.
- `data/random_videos.py`: `fetch_random_rows` (115/160), `fetch_recent_videos` (204/248), `_ordered_row` (292), which serves `fetch_ordered_page` (trending/popular/recent) and `fetch_followed_page` (Following, 417).
- `data/search.py` `VIDEO_ROW_SQL` (66).

I found no row source without `tags_json`. The recommendations mixer and scoring should still be checked, to confirm they never rebuild row dicts from a fixed key list.

**Regression risk: low**
- The change is additive: a new key on every row of every listing.
- `tags_from_json` guards against non-str, empty, invalid and non-list values, so a bad row cannot 500.
- Tests that compare whole row dicts would break, but I found none comparing Engine response rows by exact key set. `test_metadata.py:40` and `test_internal_client_reads.py:27` key-check data-layer rows, which are unchanged.
- PeerTube caps tags per video, so the payload grows only slightly. The gateway's `ENGINE_PROXY_MAX_BODY_BYTES = 1_000_000` (`client/backend/server.py:91`) is not at risk even for a 96-row over-fetch.
- `tags` is remote-controlled text now present in every response. The `findings.json` precedent for `channel_url`/`video_url` applies: every frontend sink must escape it (see the `video-card.ts` entry).
</impact>

<impact path="engine/server/api/handlers/similar.py" element="_handle_search (420-486): q/tag branching, validation, dispatch">
**What changes**
- After the `SEARCH_ENABLED` 503 (426-428), read `tag` with `params.get("tag", [None])[0]` next to `q` (430). `parse_qs` drops blank values, so `?tag=` arrives as missing.
- Branches:
  - Both present: 400.
  - A tag that strips to empty: 400.
  - Stripped length > 64: 400.
  - Neither: the existing `"Missing query parameter q"` 400 (432).
  - All use `respond_json(self, 400, {"error": ...})`.
- Sort validation (435-438) is shared. In tag mode `relevance`, or no sort, resolves to `published_at`, and the response `sort` echoes the resolved value.
- `limit`/`page` parsing (440-446) is shared.
- In tag mode, call the new data-layer function with `include_nsfw=_parse_include_nsfw(params.get("nsfw", [None])[0])`. ADR-0007 consequence: forgetting the flag leaks NSFW, because the data layer defaults to True.
- `SearchIndexMissing` → 503 (464-467) must also wrap the tag call.
- `apply_serving_moderation_filters` and `stable_video_rows` stay shared (468-484). `vectorSearch` must be `False` in tag mode, whereas line 483 today derives it from the encoder.
- Add the new function to the `from data.search import ...` line (27).

**The 64-character limit has no constant yet**
- `SEARCH_MAX_TOKEN_LENGTH = 64` (`server_config.py:460`) means something else. Either add a new constant such as `SEARCH_MAX_TAG_LENGTH` (see the `server_config.py` entry) or a literal; the plan does not say which.
- Python's `strip()` (all Unicode whitespace) is used for the empty/length checks, while the SQL side trims only space/tab/CR/LF. A tag padded with NBSP sent straight to the Engine (the gateway strips it) passes validation but never matches, unless the stripped value is the one bound into SQL. Bind the Python-stripped value, and the SQL trim is then a no-op on the request side, still applied to stored tags.

**What depends on it**
- `router.py:98-100` `_search` passes `parse_qs` output.
- `/api/v1/search/videos` keeps its rate-limit gate (`router.py:11`).
- Live Engine tests that drive text search (`test_similar.py:140,142,184,581,804,853,1112`, `test_dislike_profile.py:72`) must keep passing unchanged.

**Regression risk: medium**
- The branching sits in front of the text path. A wrong order (for example checking `tag` before `q` is read, or resolving relevance→published_at for text mode too) changes text search, which has tests across the suite.
- `vectorSearch` and `sort` in the response are part of the contract the search page reads.
</impact>

<impact path="engine/server/api/handlers/similar.py" element="module docstring (1-8)">
**What changes:** line 3 says the handler serves "hybrid video search". Add exact-tag search on the same route.

**Regression risk: none.**
</impact>

<impact path="engine/server/api/router.py" element="module docstring route list (line 11) and _search (98-100)">
**What changes:** line 11 (`GET /api/v1/search/videos: hybrid video search. [rate-limit gate]`) should mention the `tag` mode. `_search` is unchanged: it already forwards every query parameter.

**What depends on it:** `test_router.py` (mapped to `router.py` and `similar.py` in `tests/config.json:456-459`) has no search assertions (grep found none).

**Regression risk: none.**
</impact>

<impact path="engine/server/data/search.py" element="new tag-search function beside lexical_candidates (134-168), its SQL, and the module docstring (1-10)">
**What changes**
- A new function, for example `tag_search_videos(server, tag, page, limit, sort, include_nsfw=True) -> (rows, total)`. Per ADR-0007 decision 1 it must default `include_nsfw` to True.
- It takes `conn, lock = search_connection(server)`, then `with lock:` and `with search_deadline(server):`, then `fts_available(conn)` → `SearchIndexMissing` (as `search_videos` does at 283-290).
- **Prefilter:** `[t for t in _TOKEN_SPLIT.split(tag) if t]`. If any token survives, the MATCH expression is a column filter holding one phrase, `tags_json : "tok1 tok2"`, with quotes doubled as in `sanitize_query` (112). It joins `videos_fts f JOIN videos v ON v.rowid = f.rowid LEFT JOIN channels c ...` as in 157-160.
- **Fallback:** if no token survives, `FROM videos v LEFT JOIN channels c ...` with no FTS join.
- **Exact check:** `EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) AND json_type(v.tags_json) = 'array' THEN v.tags_json ELSE '[]' END) j WHERE j.type = 'text' AND lower(trim(j.value, ' ' || char(9,13,10))) = lower(trim(?, ' ' || char(9,13,10))))`.
- **NSFW:** `AND {NSFW_ALLOWED_SQL}` when `include_nsfw` is False. `NSFW_ALLOWED_SQL` is already imported at line 20.
- **Order and paging:** `ORDER BY LEXICAL_SORTS[sort]`, then `LIMIT ? OFFSET ?`.
- **Total:** a second `SELECT COUNT(*)` with the same FROM/WHERE.
- Reuse `VIDEO_ROW_SQL` (51-81) so the rows carry `tags_json`, `popularity` and the rest of the projection.
- Like `lexical_candidates`, it applies no `error_threshold` and needs no `video_embeddings` join. That matches text search (`test_search.py:27`: "search takes no error threshold") but differs from the feeds, which serve only embedded videos. Keep this parity deliberate.
- The module docstring (1-10) speaks only of hybrid search, so add a line for tag mode.
- The `search_videos` docstring (271-277) on `total` stays true for text search.
- Optionally a `logging.info("[search] tag ...")` line, mirroring 302-309.

**What depends on it**
- `_handle_search` (above).
- `tests/active/test_search.py` runs `data.search` on the Engine interpreter (`ENGINE_PY`, line 18) against an in-memory DB with the same `videos_fts` DDL (line 42). It is the natural place for the new data-layer tests: tokenised, fallback, malformed `tags_json`, object `tags_json`, NSFW total, paging past the end, and accented case.
- `tests/config.json` maps `data/search.py` to `test_similar.py` (69) and two other groups (202, 262).

**Regression risk: medium-high, concentrated in SQL semantics**
- `json_each` raises on malformed JSON and walks object values. The `CASE`/`json_valid`/`json_type` guard must sit inside the `json_each` argument, because a separate AND term has no evaluation-order guarantee.
- SQLite's built-in `lower()` folds ASCII only, unless the library has ICU. The Engine env ships `libsqlite-3.53.4` (`engine/.pixi/envs/default/conda-meta/libsqlite-3.53.4-h13e7031_1.json`) and ICU libs (`lib/libicu*.so.78.3`). The plan says a probe showed Unicode `lower()`, but I could not verify from files that libsqlite is linked with `SQLITE_ENABLE_ICU`. A test run on the system interpreter (other sqlite builds) would behave differently, so a `MÚSICA`/`música` test must use `ENGINE_PY`, as `test_search.py` does.
- The FTS column filter syntax and phrase quoting must not admit operators. `_TOKEN_SPLIT` already removes `"`, and quote doubling is a second guard.
- `OFFSET` paging cost grows with depth. The full-scan fallback is about 0.7 s per statement, about 1.4 s per page with the count.
- Both statements run under one `search_deadline`. It nests inside the request deadline started in `_serve` (`similar.py:413`); see the `data/db.py` restore semantics.
</impact>

<impact path="engine/server/api/handlers/video.py" element="tags_from_json (164-174)">
**What changes:** nothing in the body. It gains a second importer (`similar.py`).

**What depends on it:**
- `/api/video` response `tags` (345).
- The new `stable_video_row` use.
- `to_tags_json` (156-161) writes raw UTF-8 (`ensure_ascii=False`), which is why the FTS prefilter tokenises words rather than `\u` escapes. That is part of why the Rt1 tokenizer gap is small.

**Regression risk: low.** A future edit to `tags_from_json` now changes every listing as well as `/api/video`. Importing `video.py` from `similar.py` pulls `data.source_fetch` and `data.peertube_labels` into the similar handler's import graph; they are already loaded in the Engine process via the router.
</impact>

<impact path="engine/server/api/server_config.py" element="SEARCH_* block (454-470): possible new tag-length constant">
**What changes:** only if the build names the 64-character cap. Add, for example, `SEARCH_MAX_TAG_LENGTH = 64` with a one-line comment beside `SEARCH_MAX_TOKEN_LENGTH` (460). The plan says "64 characters" without naming a home.

**What depends on it:**
- `similar.py`'s import block (37-64).
- `.un/skills/devsecops/config.json` / `tests/config.json`, which map `server_config.py` to `test_dislike_profile`, `test_internal_translate`, `test_translate_worker` and others, so editing it reselects them.

**Regression risk: low.** The module must stay pure Python (test_server_config imports it on `sys.executable`).
</impact>

<impact path="engine/server/db/jobs/sync-whitelist.py" element="videos_fts definition (393-401) and its triggers (276-288): read-only dependency">
**What changes:** nothing.

**What depends on it:**
- The tag prefilter assumes a `tags_json` column in `videos_fts`, under the default `unicode61` tokenizer: case folding, `remove_diacritics 1`, and punctuation as separators.
- The external-content triggers keep the index in step with `videos.tags_json` writes from `/api/video/refresh` (`video.py:391-402`) and the updater merge.

**Regression risk:** none from this build. The Rt1 tokenizer-mismatch risk (Python `\w` vs `unicode61`) lives here: if the tokenizer options ever change, the prefilter silently misses rows.
</impact>

<impact path="client/backend/server.py" element="PROXY_ALLOWED_QUERY_PARAMS['/api/v1/search/videos'] (line 104)">
**What changes:** `{"q", "page", "limit", "sort", "nsfw"}` becomes `{"q", "page", "limit", "sort", "nsfw", "tag"}`.

**Behaviour inherited from existing code**
- `_sanitize_query` (138-154) strips `tag` (not in `PROXY_UNSTRIPPED_QUERY_PARAMS`, 120) and drops it when empty, so `?tag=%20` reaches the Engine as missing → "Missing query parameter q" 400.
- A repeated `tag` gets the gateway's own 400.
- The route is already in `PROXY_READ_GET_ROUTES` (95-97) and `FILTERED_ROUTES` (83), so blocks and like/dislike marks apply through `_profile_filter` (606-640), with no over-fetch since search is not in `FEED_ROUTES`.
- `_filter_payload` (1393-1419) round-trips rows as dicts, so `tags` passes. It re-encodes with `json.dumps` default `ensure_ascii=True`, so non-ASCII tags arrive as `\u` escapes, which is JSON-equivalent.

**What depends on it**
- `client/frontend/src/data/search.ts` (its docstring names the five parameters).
- Keyed-search tests: `test_blocks.py:24`, `test_follows.py:33`, `test_profiles.py:286,305`, `test_server.py:217,1516`.

**Regression risk: low.** No test asserts `Unknown query parameter: tag` (grep found none). `test_server.py:1549` asserts the nsfw allowlist on `/api/video` only.
</impact>

<impact path="client/frontend/src/components/video-card.ts" element="new exports tagSearchUrl, renderTagChips, observeTagRows; renderVideoCard (341-419); stylesheet import; module docstring (1-12)">
**What changes**
- `tagSearchUrl(tag, apiParam)`: `URLSearchParams` with `tag`, plus `api` only when `apiParam && import.meta.env.DEV`, mirroring `videoPageUrl` (330). Returns `/search.html?…`.
- `renderTagChips(tags, apiParam)`:
  - `""` for an empty or missing list. Rows from an older cached payload in sessionStorage (`data/cache.ts:46-66`), or from any source without `tags`, must render as no tag line, not throw.
  - Otherwise `<div class="card-tags">` holding `<a class="tag-chip" href="${escapeHtml(tagSearchUrl(...))}">${escapeHtml(tag)}</a>` per tag, then a hidden `+N` marker with an `aria-label`.
- `observeTagRows(container)`: one `MutationObserver` (childList, subtree) finds `.card-tags` in added nodes (including descendants of added `<article>`s) and registers them with one module-level `ResizeObserver`. Removed nodes are unobserved. The fit hides chips from the end and sets `+N`.
- `renderVideoCard` appends the chip row after `</a>` (416), beside `actionsMarkup`, outside `.video-link`, so there is no nested `<a>`.
- A side-effect `import "../<chips>.css"`.
- The module docstring's "every value passes through `escapeHtml`" discipline extends to tags, which are remote-controlled.

**What depends on it**
- Feed (`pages/videos/index.ts`, imports at 36-51) and search (`pages/search/index.ts:14-20`).
- `pages/likes/index.ts:9` (imports `channelName`, `escapeHtml`, `thumbnailUrl`, `videoPageUrl`). Through it the new stylesheet also loads on `likes.html`, which the plan's "feed, search and video pages" list omits. The likes page renders its own cards and no chips.
- `pages/video-page/index.ts:29` (`followLabel`).
- Tests bundling this module:
  - `test_frontend_video_card.py:39` (with `--loader:.css=empty`; asserts card class names and that `video-title` is absent).
  - `test_frontend_reactions.py:112-120`, which bundles `renderVideoCard` **without** `--loader:.css=empty`. esbuild will then emit a sibling CSS file, and the CSS must resolve under esbuild (an `@import "./base.css"` resolves).

**Regression risk: medium**
- Module-level construction of `MutationObserver`/`ResizeObserver` (rather than inside `observeTagRows`, and guarded) throws `ReferenceError` in every node harness that imports this module (see the test entries).
- An unescaped tag or URL is an XSS sink, because cards go in through `innerHTML`/`insertAdjacentHTML`/`outerHTML`.
- `.video-card`'s `overflow: hidden` and flex column (`videos.css:281-290`) hold the new row.
- The `existingCount` logic in `renderCards` counts `.video-card` only (`pages/videos/index.ts:403`), so it is unaffected.
</impact>

<impact path="client/frontend/src/(new) tag-chip stylesheet, e.g. src/tags.css" element="new file: .tag-chip and .card-tags rules">
**What changes**
- `.tag-chip` moves here from `video.css` (408-415). It uses `var(--line)` and `var(--ink)`, which are defined in `base.css:9-13`, the same light theme on all pages.
- Because chips are now `<a>`, it must add `text-decoration: none` and an explicit colour: no global `a` rule exists in any sheet, so the browser's default blue underline would show.
- `.card-tags` gets: a no-wrap flex row, `overflow: hidden`, `min-width: 0`, padding aligned with `.card-actions` (`videos.css:496-502`, `0 1.05rem 0.9rem`) and with the up-next card's padding.
- A `[hidden]` override if chips use `display: inline-flex`.

**Build output — the main hazard**
`video-card.ts` is already a shared Vite chunk (`dist/assets/video-card-DWtpz1-l.js`, modulepreloaded from `dist/search.html:15`). A CSS import from it makes Vite emit a **fifth linked CSS bundle** (`video-card-*.css`), linked from index, videos, likes, search and video-page. That has three consequences:
- `tests/active/test_frontend_base_css.py:100` asserts the linked bundles are exactly `["channels", "search", "video", "videos"]`.
- Lines 106 and 113 require every linked bundle to open with the built `base.css` rules (`:root` with `--paper`).
- If the new sheet `@import`s `base.css` to satisfy that, base rules are duplicated, and depending on `<link>` order they can re-override page rules. `dist/search.html:19-20` already shows a search bundle followed by a videos bundle that also opens with base.

So either the test changes (an accepted fifth, base-less shared sheet) or the design changes (for example the chip rules live in `base.css`, or are imported by each page sheet). This is a contract test the plan does not mention.

**What depends on it:** `tests/config.json` groups `test_frontend_base_css.py` (355-362) and `test_frontend_dist.py` (363-412) list every stylesheet, so the new file should be added to both.

**Regression risk: high** (build/test contract).
</impact>

<impact path="client/frontend/src/video.css" element=".tag-chip (408-415) removal; .similar-card-item (528-544) split into .similar-card-item + new .similar-card-link; .tag-list (402-406)">
**What changes**
- Remove `.tag-chip` (it moves to the shared sheet).
- `.similar-card-item` keeps padding, border-radius, border, background and the hover transform and border-colour. `display: flex; flex-direction: column; gap: 0.5rem` should stay on the item (so the link and the chip row stack) or move to the link, and `text-decoration`/`color` move to `.similar-card-link`.
- `.similar-title`/`.similar-channel`/`.similar-meta`/`.similar-reaction` (575-610, 309-325) now sit inside the link; their descendant-free selectors still match.
- `.tag-list` (the video-page `#video-tags` `<dd>`, `video-page.html:112`) stays a wrapping flex list. It must not inherit `.card-tags`' no-wrap, because the video page lists every tag.

**What depends on it:** `test_frontend_base_css.py` (the video bundle must still carry page rules after base), `test_frontend_dist.py`, and the up-next markup in `video-page/index.ts:1710`.

**Regression risk: low-medium.** A visual regression is possible on the up-next grid (`.similar-grid`, 522-526). `.tag-chip` ordering relative to `video.css` now depends on chunk link order.
</impact>

<impact path="client/frontend/src/videos.css" element=".video-card / .card-actions (281-302, 496-543)">
**What changes:** probably nothing beyond what the new sheet supplies. The chip row is a new direct child of `<article class="video-card">` after `.video-link`.

**What depends on it:** the feed and search grids (`.cards-grid`, 257-273).

**Regression risk: low.** Cards with tags grow one line, so heights in a grid row differ (an accepted tradeoff). `.video-card:hover { transform }` also applies over chips.
</impact>

<impact path="client/frontend/src/pages/video-page/index.ts" element="tag chips in renderMetadata (290-304)">
**What changes:** `document.createElement("span")` (295) becomes `createElement("a")`, with `className = "tag-chip"`, `textContent = tag` and `href = tagSearchUrl(tag, params.get("api"))`. The page's `params`/`apiBase` are at line 85. Add `tagSearchUrl` to the video-card import (29). The "No tags" text branch (302) stays.

**What depends on it:** `tests/active/test_frontend_video_page.py:4-6,189` reads `#video-tags` children's `textContent` and `classList.contains("tag-chip")`. An `<a>` element in its recording DOM still passes; the test does not check `tagName`. A new assertion on `href` belongs here.

**Regression risk: low.** It stays DOM-built with `textContent`, so no markup injection.
</impact>

<impact path="client/frontend/src/pages/video-page/index.ts" element="renderSimilarCard (1688-1721), applySimilarStatsToDom (1610-1617), similarCards render sites (357, 369, 375, 384, 388, 708)">
**What changes**
- The outer `<a class="similar-card-item" href=… data-video-key>` becomes `<div class="similar-card-item" data-video-key>`, wrapping `<a class="similar-card-link" href="${escapeHtml(videoPageUrl(row))}">…existing body…</a>` plus `renderTagChips(row.tags, apiParam)`.
- `videoPageUrl` here is the page's own copy (1655-1676), with no `api` param. The chips should use the shared `tagSearchUrl`.
- The page has its own `escapeHtml` (1821), separate from video-card's.
- Call `observeTagRows(similarCards)` once after the null check (similarCards is `HTMLElement | null`, line 61). It must be guarded or lazy for the node harnesses.
- `applySimilarStatsToDom` finds the card by `[data-video-key]` and `[data-stat="views"]` inside it, so it still works on the div.

**Render sites the observer must cover:** `innerHTML` at 375 (first batch), `insertAdjacentHTML` at 708 (reveal), plus loading/error/`keyRejectedNotice` writes that contain no chip rows.

**What depends on it**
- `tests/active/test_frontend_video_page_similars.py`:
  - The regex `_keys` (141) and line 153 match `<a\b[^>]*\bclass="[^"]*\bsimilar-card-item…` and must change to the div (or to `similar-card-link`).
  - Docstring lines 4-5 say "anchors".
- Middle-click and open-in-new-tab on up-next now target the inner link only. The padding area of the div is no longer a link.

**Regression risk: medium.** The known test break, plus the observer in three harnesses that bundle `video-page/index.ts` and lack `MutationObserver`.
</impact>

<impact path="client/frontend/src/pages/videos/index.ts" element="cards container (55-68), renderCards (390-409), renderFeedCard (414-423), runCardAction outerHTML (457) and removeRows">
**What changes:** call `observeTagRows(cards)` once after the guard at 66-68. `renderFeedCard` passes `apiParam` (84) already, so `renderVideoCard` can hand it to the chips. Otherwise unchanged: the delegated click handler (151-157) acts only on `[data-card-action]`, so a chip is a plain link.

**What depends on it:** `test_frontend_videos_page.py` bundles this page (130, 384/402). Its first harness (36-71) defines **neither** `ResizeObserver` **nor** `MutationObserver`, and its second (303-324) defines `ResizeObserver` only.

**Regression risk: medium.** If `observeTagRows` constructs observers unguarded, both harnesses throw at import.
</impact>

<impact path="client/frontend/src/pages/search/index.ts" element="state (60-73), init (75-76, 139-144), submit/sort/popstate handlers (95-108, 126-137), startSearch (165-172), loadPage (180-236), showIdle (342-352), pushUrl (357-368), resolveSort (381-384), module docstring (1-10)">
**What changes**
- `state.tag` is added. Initial load: `tag` and no `q` means tag mode. With both, prefer `q` and `pushUrl(true)` (`replaceState`) to drop `tag`.
- The heading element is filled with `textContent`, and the title becomes `"<tag> - Tag - Search - PeerTube - Browser"`.
- `resolveSort` today defaults to `"relevance"`. Tag mode needs a mode-aware default of `published_at` and must refuse `relevance`; the plan hides and disables the relevance `<option>`.
- **Sort change:** `sortSelect` change returns early on `!state.query` (106), which would kill tag-mode sort changes.
- **Popstate:** `popstate` (126-137) reads only `q`/`sort` and calls `showIdle` when `q` is empty, which would drop a back-navigation into tag mode.
- **Submit:** `form` submit (95-103) must clear `tag` and restore relevance. An empty submit calls `showIdle()`, which must also clear `state.tag`, or `pushUrl` re-writes it.
- **pushUrl:** omits `sort` only when it equals the mode default, and writes `tag` in tag mode.
- **loadPage:** passes `tag` or `q` to `fetchSearchResults`. Status strings: "Showing X of Y videos tagged …" and "No videos tagged …", replacing 226/233. The comment at 231-232 ("total is the fused candidate pool") is false in tag mode.
- `observeTagRows(results)` is called once.
- The docstring says paging runs "until the Engine's candidate pool is exhausted"; tag results page through the exact total.

**Unchanged:** the `results` click handler (110-116) acts only on `[data-card-action]`. The `outerHTML` re-renders (290, 295) and `removeRows` `innerHTML` (335) are covered by the observer.

**What depends on it:** no test bundles `pages/search/index.ts` (grep found none). `tests/config.json:405` lists it only under `test_frontend_dist.py`, so tag-mode page behaviour has no harness today and would need a new one.

**Regression risk: medium.** Several handlers each need a tag-mode branch. A missed one silently reverts to text mode or idle.
</impact>

<impact path="client/frontend/search.html" element="new tag heading element (inside .search-controls, near #search-status, 31-56); #search-sort relevance option (47)">
**What changes:** a new element (for example `<h2 id="search-tag-heading" hidden>`) that the page fills with `textContent`. The relevance `<option>` (47) is toggled hidden/disabled from script.

**What depends on it**
- `pages/search/index.ts` `requireElement` (39-45) throws on a missing id. A new id must exist in the HTML, or the page fails loudly.
- `test_frontend_dist.py` compares `dist/search.html` with a fresh build.
- `search.css` may want a heading rule.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/search.css" element="possible heading rule">
**What changes:** optionally style the tag heading.

**What depends on it:** `test_frontend_base_css.py`: the search bundle must still open with base and carry page rules.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/data/search.ts" element="FetchSearchOptions (24-31), fetchSearchResults (57-91), module docstring (1-9)">
**What changes**
- `q` becomes optional and `tag?: string` is added. Set exactly one on the URL (60-61 always sets `q` today).
- Sort and NSFW handling are unchanged. The cache key is `search:${url}` (80), so tag pages cache separately.
- The docstring's "exactly five query parameters (`q`, `page`, `limit`, `sort`, `nsfw`)" becomes six.

**What depends on it:** existing callers pass `{ q }`:
- `pages/search/index.ts:193`
- `test_frontend_feed_params.py:315` (NSFW runner, bundle at 327-331)
- `test_frontend_reactions.py:113`
- `test_frontend_blocks.py:68`

All keep working if `q` stays accepted. The keyed branch (68-76) is unchanged.

**Regression risk: low.** Sending both, or neither, would get an Engine 400. A guard that throws when neither is given is reasonable.
</impact>

<impact path="client/frontend/src/types/videos.ts" element="VideoRow (5-62) and SearchPayload docstring (70-84)">
**What changes:** add `tags?: string[] | null` to `VideoRow`. The `SearchPayload` docstring says `total` "must not be presented as a corpus-wide result count"; that is false for tag mode, where `total` is the exact match count before moderation and profile filters.

**What depends on it:** every page using `VideoRow`. There is no runtime effect (types only), and the build is `vite build` with no `tsc` step (`package.json:9`).

**Regression risk: none at runtime.**
</impact>

<impact path="client/frontend/dist/ (all seven HTML pages and assets/)" element="committed build output">
**What changes:** this has to be regenerated with `vite build` and committed.

**Why:** `tests/active/test_frontend_dist.py` asserts that the committed `dist/assets` names equal a fresh build's (content-hashed) and that each of the seven pages is byte-identical. Any source change in this build (the new sheet, `video-card.ts`, `search.html`, `video.css`, the pages) fails it until `dist` is rebuilt. The plan says dist "is not edited by hand"; it still must be rebuilt, which the plan does not state.

The new shared CSS chunk adds `<link rel="stylesheet">` lines to `index.html`, `videos.html`, `likes.html`, `search.html` and `video-page.html`.

**Regression risk: medium** (stale dist fails CI). A local `dev-pages/about.html` must not exist during the build (test lines 18, 31).
</impact>

<impact path="tests/active/test_frontend_base_css.py" element="test_every_linked_page_css_bundle_opens_with_the_built_base_rules_then_page_rules_and_holds_no_import (97-115)">
**What changes:** this fails as soon as `video-card.ts` imports a stylesheet, unless the design avoids a separate linked bundle.
- The control at line 100 expects exactly `channels, search, video, videos`.
- Lines 106 and 113 require every linked bundle to open with base's `:root`/`--paper` rules and then carry page rules.

Either update the test's contract (and docstring 1-3) to admit a component sheet that does not carry base, or put the chip rules where base already flows.

**Regression risk: high.** This is a certain red if unplanned.
</impact>

<impact path="tests/active/test_frontend_dist.py" element="test_the_committed_dist_holds_exactly_the_assets_a_fresh_build_emits_and_no_about_override (17-25)">
**What changes:** no code change. It passes only after `dist` is rebuilt and committed.

**Regression risk: high** if forgotten.
</impact>

<impact path="tests/active/test_frontend_video_page_similars.py" element="_keys regex (140-142), first-batch regex (153), docstring (4-5), RUNNER globals (75)">
**What changes**
- The anchor regexes for `similar-card-item` must match the new `<div>`, or key off `similar-card-link`.
- The docstring's "anchors" wording.
- The runner defines `ResizeObserver` (75) but no `MutationObserver`, so add a stub or the page must guard.

**Regression risk: high.** This is a known break, named by the plan.
</impact>

<impact path="tests/active/test_frontend_video_page.py" element="RUNNER (68-198) and DOM_JS/PAGE_RUNNER (648-680) globals; tag assertions (4-6, 189)">
**What changes:** both harnesses define `ResizeObserver` (116, 661) but not `MutationObserver`. Add stubs, or rely on a guard in `observeTagRows`. The taxonomy case can assert each chip's `href` is `/search.html?tag=…`.

**Regression risk: medium.** Import-time `ReferenceError` would fail every case in the file.
</impact>

<impact path="tests/active/test_frontend_translate.py" element="video-page harnesses (106-164, 432-485)">
**What changes:** these bundle `pages/video-page/index.ts` (227, 549) and define `ResizeObserver` (158, 479) but no `MutationObserver`. They need a stub, or a guard in the helper. The harness at 733-737 bundles `translate.ts` alone and is unaffected.

**Regression risk: medium**, same reason.
</impact>

<impact path="tests/active/test_frontend_videos_page.py" element="harness 1 (36-71) and harness 2 (303-324) globals">
**What changes:** harness 1 defines neither observer, and harness 2 only `ResizeObserver` (316). `pages/videos/index.ts` calling `observeTagRows(cards)` at load needs stubs or a guard.

**Regression risk: medium.**
</impact>

<impact path="tests/active/test_frontend_reactions.py" element="_bundle (106-124)">
**What changes:** it bundles `renderVideoCard` from `video-card.ts` with no `--loader:.css=empty`. With a CSS import, esbuild writes `bundle.css` next to `bundle.mjs`. The JS still runs, provided the CSS resolves (`@import` paths, no `url()` to missing files).

**Regression risk: low.**
</impact>

<impact path="tests/active/test_frontend_video_card.py" element="card markup assertions (45-62)">
**What changes:** none needed. Its rows have no `tags`, so they exercise the empty case: no `.card-tags` line. It is the natural home for `renderTagChips`/`tagSearchUrl` unit tests: escaping, `+N` marker, empty list, and `api` only in a DEV build. It bundles with `--loader:.css=empty` (39).

**Regression risk: low.**
</impact>

<impact path="tests/active/test_search.py" element="fixture DDL/rows (36-54) and child runner (57-83)">
**What changes:** it is the natural home for data-layer tag tests on the Engine interpreter. The fixture rows insert no `tags_json` today (49), so it needs a fixture extension or a sibling file.

**What depends on it:** `tests/config.json` maps `data/search.py`.

**Regression risk: low.** Existing assertions are untouched by the additive function.
</impact>

<impact path="tests/active/test_similar.py" element="_rows / test_every_row_carries_the_channel_and_account_the_dataset_holds (138-166) and search-route uses">
**What changes:** AC1 needs `tags` on every mode. The existing parametrisation covers home, random, upnext and search; trending, popular, recent and following (which needs a `follows` body) and the `GET /videos/{id}/similar` alias should be added. `identity_of(dataset, …)` can read the stored `tags_json` for comparison. Tag-route tests on the live Engine: 400 cases, sort echo, `vectorSearch` false, exact `total`, NSFW.

**Regression risk: low** for the existing tests.
</impact>

<impact path="tests/config.json" element="test_groups mappings (test_frontend_base_css 355-362, test_frontend_dist 363-412, test_frontend_video_card 348-350, test_frontend_video_page_similars, test_search)">
**What changes:** add the new stylesheet to the `test_frontend_base_css.py` and `test_frontend_dist.py` groups. Add `video-card.ts` and the stylesheet to the video-page/similars/videos-page groups, which now depend on the shared helper. Map any new test files.

**Regression risk: low.** A missing mapping means a test is not reselected on edit.
</impact>

<impact path="docs/project/adr/0007-nsfw-filter-default-at-request-edge.md" element="Decision 1-2 and Consequences (16-27): constraint on the new function">
**What changes:** none required. It constrains the build:
- The new data-layer function takes `include_nsfw: bool = True`.
- `_handle_search` must pass the parsed flag.
- Decision 2 names only `search_videos` as `_handle_search`'s callee. A one-line amendment is optional, since ADRs are records.

**Regression risk:** forgetting the flag serves NSFW rows in tag results to every visitor.
</impact>

### docs_checklist

<doc path="engine/server/README.md">
Document the search route, which this README does not describe today; only line 53 mentions it, for `nsfw`.
- **`tag`:** exact tag match, trimmed and lowercased on both sides, exclusive with `q`. A blank tag, one over 64 characters, or `q`+`tag` together answers 400.
- **Sort:** `relevance` or none means newest. `views` and `popularity` reorder. Anything else is 400.
- **Paging:** `page`/`limit` with the `SEARCH_MAX_LIMIT` cap.
- **`total`:** exact in tag mode (before moderation and gateway filters), while text search's stays the 200-candidate pool.
- **Response:** `vectorSearch` is false in tag mode.
- **Rows:** every listing row (search, every feed mode, up-next) now carries `tags` (list, uploader order, `[]` for NULL/invalid/non-list).
- **Line 53:** extend so the NSFW filter covers tag search too.
</doc>
<doc path="client/README.md">
- Line 34 lists the per-route allowlist through `nsfw`. Note that `/api/v1/search/videos` also allowlists `tag`, which is stripped and dropped when empty.
- Line 29: search filtering (blocks plus reaction marks, no dislike removal, no over-fetch) applies to tag results as well.
</doc>
<doc path="client/frontend/README.md">
Add:
- Feed, search and up-next cards show the video's tags as chips that link to `/search.html?tag=…`, fitted to one line with a `+N` marker. The video page's tag list becomes links too.
- The search page's tag mode: the heading, the title format, the "Showing X of Y videos tagged …" and "No videos tagged …" status lines, the relevance sort hidden with `published_at` as default, `tag` in the URL, a submit leaving tag mode, and a URL with both `q` and `tag` reduced to `q`.
- Line 8: the gateway routes the frontend fetches are unchanged.
- Line 18: the "Showing N of M matched videos." wording applies to text search only.
</doc>
<doc path="CONTEXT.md">
Add a glossary entry for **Tag** / **tag search**:
- the uploader's tags as stored in `videos.tags_json`;
- two tags are the same after trimming and lowercasing;
- language variants stay distinct;
- tag search is the exact-tag mode of the search route, distinct from the full-text match on the `tags_json` FTS column.
</doc>
<doc path="docs/project/roadmap.md">
After delivery, add a DONE line for issue 42's first plan (tags on cards and exact-tag search). It should point at `docs/project/plans/54-53-tags-on-cards-and-tag.md`, and say that issue 42's multi-tag narrowing and advanced search remain open.
</doc>
<doc path="docs/project/issues/42-tags-on-cards-and-tag-search.md">
Record which part of the issue this plan delivered (tags on every card, click a tag to get exact-tag results) and what stays open. The issue stays open under the triage labels, since the operator expects more than one plan.
</doc>

### highest_risk

client/frontend/src/(new chip stylesheet) imported from components/video-card.ts — video-card is already a shared Vite chunk (dist/assets/video-card-*.js), so its CSS becomes a fifth linked bundle on index/videos/likes/search/video-page. tests/active/test_frontend_base_css.py:100 asserts exactly four linked bundles (channels, search, video, videos), and lines 106/113 require every bundle to open with base.css. If the sheet @imports base.css to pass, base rules are duplicated and can re-override page rules by link order. The plan does not mention this test, and client/frontend/dist must also be rebuilt and committed for test_frontend_dist.py.
client/frontend/src/components/video-card.ts observeTagRows (MutationObserver + ResizeObserver) — the node harnesses that import the feed and video pages define no MutationObserver anywhere, and test_frontend_videos_page.py harness 1 has no ResizeObserver either: test_frontend_video_page.py (two harnesses), test_frontend_video_page_similars.py, test_frontend_translate.py (two) and test_frontend_videos_page.py (two). An unguarded or module-level observer throws ReferenceError at import and turns those whole files red, on top of the named similar-card-item regex break.
engine/server/data/search.py new tag-search SQL — correctness rests on SQLite details. json_each must be fed a CASE-guarded array (malformed or object tags_json otherwise 500s or false-matches). lower() is Unicode-aware only if the Engine's libsqlite-3.53.4 build has ICU, which I could not verify from the tree, so accented tags may match ASCII-only. The Python-strip vs SQL-trim(space, tab, CR, LF) mismatch, the FTS phrase quoting, and the include_nsfw default required by ADR-0007 (forgetting the flag leaks NSFW) all sit in the same function.

## 2026-10-06 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

I checked the inventory against the main checkout, because `.worktrees/55` does not exist yet. I read `similar.py`, `router.py`, `data/search.py`, `video.py`'s imports, the `random_videos`/`metadata` row sources, `sync-whitelist.py`'s `videos_fts` DDL, the gateway allowlist and `_sanitize_query`, `video-card.ts`, `pages/search/index.ts`, `data/search.ts`, the up-next renderer and `video.css`, `vite.config.ts`, `dist/search.html`, and the frontend test harnesses. The entries hold up. The engine and gateway parts of the plan work as written. The frontend part works too, provided the build also does the test and contract work the inventory already lists: amend the base-CSS bundle test, rebuild `dist`, fix the up-next regexes, and add a `MutationObserver` stub to each page harness. I found one constraint the inventory does not carry: every page sets a Content-Security-Policy with `style-src 'self'`, so the chip markup cannot use inline style attributes.
<question id="1">
Yes. `stable_video_row` is the one projection behind search (`similar.py:484`) and every `_respond_rows` path. Every row source selects `tags_json`: `metadata.py` 49/198, `random_videos.py` 59/115/204/292, and `search.py` `VIDEO_ROW_SQL` line 66. That includes the random cache, which goes through `fetch_metadata` (`random_videos.py:453`). No module rebuilds rows from a fixed key list, so `tags` reaches every mode. Importing `handlers.video` from `similar.py` creates no cycle: `video.py` imports only `data.*`, `http_utils` and `server_config`, and `router.py:44` already loads it. `videos_fts` has a `tags_json` column (`sync-whitelist.py:393-401`, default tokenizer), so the column-filter prefilter is valid. `parse_qs` drops blank values, and the gateway's `_sanitize_query` strips values and drops empty ones (`server.py:138-154`), so the 400 branches behave as the plan says. On the frontend, `video-card.ts` is already the shared chunk for the feed, search, likes and video pages, and every write to a grid (`innerHTML`, `insertAdjacentHTML`, `outerHTML` re-renders, `removeRows`) happens on the three containers the observer watches. Some things only show up when the code runs: SQLite `lower()` on non-ASCII (needs the `ENGINE_PY` test), and the Rt1 tokenizer gap.
</question>
<question id="2">
1. Importing a stylesheet from `video-card.ts` makes Vite emit a fifth linked CSS bundle on five pages. `test_frontend_base_css.py:100,106,113` rejects that bundle as written: it allows only four bundles, each opening with the base rules.
2. Any source change makes `test_frontend_dist.py` fail until `dist` is rebuilt and committed.
3. Seven node harnesses bundle a page that will call `observeTagRows` at load and have no `MutationObserver`:
   - `test_frontend_video_page.py`: two harnesses.
   - `test_frontend_video_page_similars.py`: one.
   - `test_frontend_translate.py`: two.
   - `test_frontend_videos_page.py`: two. Harness 1 also lacks `ResizeObserver`.
4. The up-next regexes in the similars test break.
5. Every Engine listing response gets slightly bigger. Tags are remote-controlled text, so they now reach three `innerHTML` sinks.
6. Under the page CSP (`style-src 'self'`), the chip and marker markup must hide things with the `hidden` attribute or classes, not inline `style`.
7. Tag search has no `error_threshold` and no embeddings join. This matches text search, not the feeds.
8. `likes.html` also loads the new stylesheet, which the plan does not mention.
</question>
<question id="3">
- **Base-CSS test:** amend `test_frontend_base_css.py` to admit one component bundle that has no base and no `@import`. The other way out is moving the chip rules where base already loads, which changes the plan (see the recommendations).
- **Rebuild:** regenerate and commit `client/frontend/dist`.
- **Similars test:** update the regexes and docstring in `test_frontend_video_page_similars.py`.
- **Harness stubs:** add a `MutationObserver` stub to the seven harnesses, and a `ResizeObserver` stub to `test_frontend_videos_page.py` harness 1.
- **Engine search call sites:** keep `include_nsfw` passed explicitly (ADR-0007), and wrap the tag call in the existing `SearchIndexMissing` 503.
- **Response fields:** set `vectorSearch` to false in tag mode, and keep text mode's relevance default unchanged.
- **Search page:** give the sort-change, `popstate`, submit/`showIdle` and `pushUrl` paths a tag-mode branch, and add the new heading id to `search.html` (`requireElement` throws if it is missing).
- **Chip links:** add `text-decoration: none` and an explicit colour to `.tag-chip`, since no global `a` rule exists.
- **Test mappings:** add the new sheet to the `tests/config.json` groups for `test_frontend_base_css.py` and `test_frontend_dist.py`.
</question>
<question id="4">
- **Engine responses:** every listing gains a `tags` array.
- **`/api/v1/search/videos`:** accepts `tag` as an alternative to `q`. Text search is unchanged.
- **Up-next cards:** each card is now a `<div>` wrapping a link, so the padding and chip area no longer navigates. Middle-click and open-in-new-tab work on the inner link only.
- **Video page:** tag chips become links. `.tag-chip` styling now comes from a shared chunk rather than `video.css`.
- **Feed and search cards:** cards with tags grow one line.
- **Search page:** has a tag mode with its own heading, title, status wording and default sort. A URL carrying both `q` and `tag` is reduced to `q`.
- **Gateway:** accepts `tag` instead of answering "Unknown query parameter".
</question>

New impacts:
client/frontend/search.html (and index.html, videos.html, likes.html, video-page.html, line 8 of each built page): the Content-Security-Policy `style-src 'self'` blocks inline `style="..."` attributes in markup inserted via `innerHTML`/`insertAdjacentHTML`/`outerHTML`. So `renderTagChips` must start the `+N` marker hidden with the `hidden` attribute, and the fit must show or hide chips by toggling `hidden` (or a class), never by emitting inline styles. Setting CSSOM properties from script is still allowed. With `.tag-chip`/the marker at `display: inline-flex`, the `[hidden]` override the inventory mentions becomes mandatory, following the precedent at `video.css:485-488`. Regression risk: low. An inline-style version would fail silently in production (the browser drops the style) and pass every node harness.

Inventory entries that did not hold up:
- **ICU / Unicode `lower()`:** unverifiable from files, as the inventory itself flags. Whether the pixi `libsqlite` gives Unicode `lower()` only shows when the `ENGINE_PY` test runs.
- **Entries not reopened:** I checked these only through grep hits or neighbouring reads, so their exact line numbers are unverified. The claims I did touch matched:
  - `test_similar.py` (parametrisation at 138-166)
  - `test_server.py` / `test_blocks.py` / `test_follows.py` / `test_profiles.py` search line refs
  - ADR-0007 text
  - `server_config.py` 454-470
  - `types/videos.ts`
  - `pages/videos/index.ts` line refs
  - `test_frontend_reactions.py` `_bundle` (only line 112 was confirmed: it bundles `renderVideoCard` with no `--loader:.css=empty` among its flags)

Conflicts: none

Recommendations: 1. **Where the chip CSS lives (pick one).**
   - **(a) Keep the plan's component stylesheet** imported from `video-card.ts`. Amend `test_frontend_base_css.py` so its control admits exactly one extra `video-card` bundle, which must hold no `@import` and must not open with base, while the four page bundles keep the full contract. Also update its docstring and the `tests/config.json` group. Cost: one test edit and a weaker guarantee for that one bundle. The new sheet must not `@import "./base.css"`: `dist/search.html:19-20` shows shared-chunk CSS can be linked after page CSS, so a duplicated base would re-override page rules.
   - **(b) Put `.tag-chip`/`.card-tags` in `base.css`.** Cost: about 20 lines shipped in every bundle, channels included. It needs no test change and no fifth bundle, but it departs from the settled "small stylesheet the helper imports", so it needs the operator's approval.
   - I recommend (a), because it stays inside the plan.

2. **Test doubles the plan widens: the browser-platform stubs in the seven page harnesses.** These are `test_frontend_video_page.py` (two), `test_frontend_video_page_similars.py`, `test_frontend_translate.py` (two) and `test_frontend_videos_page.py` (two).
   - Give each a recording `MutationObserver` class that keeps its `observe(target, options)` calls. Add `ResizeObserver` to videos-page harness 1.
   - In the similars and videos-page tests, assert that exactly one observer watches the grid container (`similar-videos` / `cards`) with `childList` and `subtree`.
   - Do not guard `observeTagRows` with `typeof MutationObserver` to keep the harnesses quiet. The call would vanish from the tests that exist to show page behaviour.
   - Cost: one line per harness plus two assertions. The existing fetch-recording doubles (`requests`) are not widened: the plan adds no new fetches, so their expected sequences are unchanged.

3. **Name the cap.** Add `SEARCH_MAX_TAG_LENGTH = 64` in `server_config.py` beside `SEARCH_MAX_TOKEN_LENGTH`. Cost: editing `server_config.py` reselects the test groups mapped to it, so their run time.

4. **Bind the Python-stripped tag** to the SQL `trim(?)` while keeping the explicit-set SQL trim on both sides. A NBSP-padded tag sent straight to the Engine then cannot pass validation and silently miss. Cost: none, and it stays consistent with the plan's same-function normalisation.

5. **Make the `dist` rebuild an explicit last step** of the build (`vite build`, then commit, with no local `dev-pages/about.html` present). Cost: one step. Without it CI is red for certain.

6. **Add a search-page tag-mode harness.** No test bundles `pages/search/index.ts` today, and four handlers each need a tag branch. Cover: initial load in tag mode, sort change, `popstate` into and out of tag mode, submit leaving tag mode, and the `replaceState` for a URL with both `q` and `tag`. Cost: one new test file of about 150 lines, modelled on `test_frontend_videos_page.py`, plus its `tests/config.json` mapping.

7. **Escaping tests for chips.** Unit tests for `renderTagChips`/`tagSearchUrl` in `test_frontend_video_card.py` should include a tag containing `<`, `"` and `&`, and assert that the markup holds no `style=` attribute (because of the CSP). Cost: a few cases in an existing file.

8. **Optional:** a one-line ADR-0007 amendment naming the new tag-search function as a second `include_nsfw` callee. Cost: a doc edit only.

## 2026-10-06 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

Note on the tree: `/home/enduser/code/PeerTube-browser/.worktrees/55` does not exist. Grep reports "No such file or directory" and Glob finds nothing under `.worktrees/`. `tests/config.json:3` names it as `project_dir`, so the build is expected to run there once the worktree is created. I opened every file below in the main checkout `/home/enduser/code/PeerTube-browser`, and paths are relative to the repo root. An earlier, ungated pass of this step and a step-4 reassessment are in `docs/project/plans/54-53-tags-on-cards-and-tag.record.md`. I re-checked their claims against the files and added what they missed: the search page's idle path pushes history at load; an Engine 400 surfaces as "Engine may be unavailable"; the Engine README has no search-route bullet at all; `conftest.identity_of` is shared; the CSP rules out inline styles.

<impact path="engine/server/api/handlers/similar.py" element="stable_video_row (129-131) / stable_video_rows (134-136), plus a new import of tags_from_json">
**What changes**
- `stable_video_row` returns the existing `{field: row.get(field) for field in STABLE_VIDEO_FIELDS}` plus `"tags": tags_from_json(row.get("tags_json"))`.
- New import: `from handlers.video import tags_from_json`, the same form `router.py:44` and `internal_translate.py:25` already use.
- `STABLE_VIDEO_FIELDS` (106-126) is unchanged, including the `INCLUDE_DYNAMIC_STATS` extension at 125-126.

**What depends on it**
- Exactly two callers (grep): `_handle_search` (484) and `_respond_rows` (611).
- `_respond_rows` serves random (640), ordered trending/popular/recent (689), following (720), the home mix and its empty-mix random fallback (745, 753), up-next (863), the raw-vector route (937) and seed-random (1057).
- `maybe_attach_debug` → `recommendations/debug.py:35` builds `{**stable, "debug": ...}`, so `tags` survives in debug mode.

**Row sources (verified to carry `tags_json`)**
- `data/metadata.py:198` `_select_metadata`, behind `fetch_metadata`/`fetch_metadata_by_ids`. That covers up-next `_build_rows` (`similarity_candidates.py:425-464`, `{**meta, "score"}`), the random cache (`random_videos.py:453`), vector search, and ANN in `data/ann.py`.
- `data/random_videos.py:115/160` (`fetch_random_rows`), `204/248` (`fetch_recent_videos`) and `292` (`_ordered_row`, which serves `fetch_ordered_page` and Following's `fetch_followed_page` at 417).
- `data/search.py:66` (`VIDEO_ROW_SQL`).
- No recommendations module rebuilds row dicts from a fixed key list. Grep for `"video_id":` constructions in `api/` finds only `internal_client_reads.py` and `_resolve_client_likes`, and neither feeds listings.

**Import side effects:** `video.py` imports only `data.*`, `http_utils` and `server_config` (9-21), so there is no cycle. Every test that imports `handlers.similar` (`test_similar.py`, `test_video.py:171,208`, `test_router.py:39`, `test_server.py:1417`, `engine/server/api/tests/test_recommendations_likes_limit.py:19`) puts `server/` and `server/api` on `sys.path`, so `handlers.video` resolves. `test_video.py` monkeypatches `video.respond_json` and `video.fetch_instance_json` on the module object; importing `tags_from_json` by name is unaffected.

**Regression risk: low.** The change is additive. `tags_from_json` (`video.py:164-174`) never raises on bad input. No test compares Engine response rows by exact key set: `test_metadata.py:40` and `test_internal_client_reads.py:27` key-check data-layer rows, which do not change. `tags` is remote-controlled text that now reaches every listing payload and three `innerHTML` sinks, so every frontend sink must escape it.
</impact>

<impact path="engine/server/api/handlers/similar.py" element="_handle_search (420-486): tag branch, validation, dispatch, response; import line 27; docstrings 1-8 and 421">
**What changes**
- After the `SEARCH_ENABLED` 503 (426-428), read `tag` next to `q` (430).
- Validation order:
  - Both present: 400.
  - A tag that strips to empty: 400.
  - A stripped tag longer than 64: 400.
  - Neither: the existing `"Missing query parameter q"` 400 (431-433).
  - Every 400 uses `respond_json(self, 400, {"error": ...})`.
- The sort check (435-438) stays shared. In tag mode only, `relevance` or no sort resolves to `published_at`; text mode must keep `relevance` as its default.
- `limit`/`page` (440-446) stay shared.
- The tag branch calls the new data function with `include_nsfw=_parse_include_nsfw(params.get("nsfw", [None])[0])`.
- That call must sit inside the same `except SearchIndexMissing` → 503 (464-467).
- `apply_serving_moderation_filters` and `stable_video_rows` (468-484) stay shared.
- The response echoes the resolved `sort`, and `vectorSearch` is `False` in tag mode; today line 483 derives it from the encoder.
- Line 27 gains the new function name.
- Docstrings to update: line 3 ("hybrid video search") and 421 ("Answer a hybrid video search request").

**The 64-character cap has no named constant.** `SEARCH_MAX_TOKEN_LENGTH = 64` (`server_config.py:460`) is a different limit (per FTS token). See the `server_config.py` entry.

**The strip/trim mismatch.** Python `strip()` removes all Unicode whitespace; the plan's SQL trim removes space, tab, CR and LF. A direct Engine call with NBSP padding passes the Python validation and then never matches, unless the Python-stripped value is what gets bound. Bind the stripped value.

**What depends on it**
- `router.py:98-100` passes `parse_qs` output, which drops blank values.
- The rate-limit gate (`router.py:24`).
- Live text-search callers in tests: `test_similar.py:140,142`, `test_frontend_follows.py:83`, `test_frontend_upnext_pager.py:79`, `test_frontend_blocks.py:99`, `test_frontend_reactions.py:55`.

**Regression risk: medium.** The new branch sits in front of the text path. Resolving relevance→published_at outside tag mode, or reading `tag` such that `q`+`tag` is not caught, changes text search. `sort` and `vectorSearch` are read by the search page.
</impact>

<impact path="engine/server/api/router.py" element="module docstring route list (line 11); _search (98-100)">
**What changes:** line 11 (`GET /api/v1/search/videos: hybrid video search. [rate-limit gate]`) should mention the exact-tag mode. `_search` itself is unchanged, because it forwards every query parameter.

**What depends on it:** `test_router.py` imports `SimilarHandler` but has no search assertions.

**Regression risk: none.**
</impact>

<impact path="engine/server/data/search.py" element="new tag-search function beside lexical_candidates (134-168), and the module docstring (1-10)">
**What changes**
- A new function returning `(rows, total)`, for example `tag_search_videos(server, tag, page, limit, sort, include_nsfw=True)`. Per ADR-0007 decision 1 it defaults `include_nsfw` to True.
- It takes `conn, lock = search_connection(server)` (32-43), then `with lock:`, `with search_deadline(server):` (46-49), then `fts_available(conn)` → `SearchIndexMissing`, copying `search_videos` 283-290.
- **Prefilter:** `[t for t in _TOKEN_SPLIT.split(tag) if t]` (25). If any token survives, it builds one phrase `tags_json : "tok1 tok2"`, doubling quotes as at 112. `videos_fts` is external-content with a `tags_json` column (`sync-whitelist.py:393`; same DDL in `test_search.py:42`). It joins `videos_fts f JOIN videos v ON v.rowid = f.rowid LEFT JOIN channels c ...` as at 157-160.
- **Fallback:** if no token survives, `FROM videos v LEFT JOIN channels c ...`.
- **Exact check:** `EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(v.tags_json) AND json_type(v.tags_json)='array' THEN v.tags_json ELSE '[]' END) j WHERE j.type='text' AND lower(trim(j.value, <set>)) = lower(trim(?, <set>)))`.
- **NSFW:** `AND {NSFW_ALLOWED_SQL}` (already imported at line 20) when the flag is False.
- **Order and paging:** `ORDER BY LEXICAL_SORTS[sort]` (83-87), `LIMIT ? OFFSET ?`.
- **Total:** a second `SELECT COUNT(*)` with the same FROM/WHERE.
- It reuses `VIDEO_ROW_SQL` (51-81), so rows carry `tags_json` and `popularity`.
- Like the text path, it has no `error_threshold` and no `video_embeddings` join (`test_search.py:27`: "search takes no error threshold"). That differs from the feeds, which serve only embedded videos, and the parity should be kept deliberately.
- The docstrings at 1-10 and 271-277 describe only hybrid search and the pooled `total`, so add a tag-mode line. An optional `[search] tag ...` log line can mirror 302-309.

**What depends on it:** `_handle_search`; `tests/active/test_search.py` (Engine interpreter, in-memory DB); the `tests/config.json` groups at 69, 202 and 262.

**Regression risk: medium-high, all in SQL semantics**
- `json_each` raises on malformed JSON and walks object values, so the guard must sit inside its argument; a separate AND term has no evaluation-order guarantee.
- SQLite core `lower()` folds ASCII only unless ICU is compiled in. The plan's probe says the Engine env's `lower('MÚSICA')` gives `música`, but I cannot verify that from files. Tests must run on `ENGINE_PY` (`test_search.py:18`), not the system Python.
- The trim set must be written so that it does not also strip characters a tag legitimately holds.
- The phrase must stay a quoted literal so that no FTS operator gets in. `_TOKEN_SPLIT` already removes `"`.
- `OFFSET` cost grows with depth. The fallback is about 0.7 s per statement, so about 1.4 s per page with the count, inside the 5 s deadline.
- The Rt1 tokenizer gap (Python `\w` vs `unicode61`) is silent.
</impact>

<impact path="engine/server/api/handlers/video.py" element="tags_from_json (164-174), to_tags_json (156-161)">
**What changes:** no body change. `tags_from_json` gains a second importer.

**What depends on it:**
- `/api/video`'s `tags` (345) and now every listing row.
- `to_tags_json` writes `ensure_ascii=False`. That is why FTS tokenises real words rather than `\u` escapes, which keeps the Rt1 gap small.

**Regression risk: low.** A future change to `tags_from_json` now changes every listing as well as `/api/video`.
</impact>

<impact path="engine/server/api/server_config.py" element="SEARCH_* block (454-470)">
**What changes:** optional, but recommended. Add `SEARCH_MAX_TAG_LENGTH = 64` with a one-line comment beside `SEARCH_MAX_TOKEN_LENGTH` (460), and import it in `similar.py` (37-64). The alternative is a literal in the handler; the plan says neither.

**What depends on it:** the module is imported in pure Python by `test_similar.py:130-135` (`_default_limit`) and many `tests/config.json` groups, so editing it reselects them.

**Regression risk: low.**
</impact>

<impact path="engine/server/db/jobs/sync-whitelist.py" element="videos_fts DDL (393-401) and triggers (276-288): read-only dependency">
**What changes:** nothing.

**What depends on it:** the prefilter's correctness depends on `videos_fts` keeping a `tags_json` column under the default `unicode61` tokenizer, and on the AI/AD/AU triggers keeping it current, including `/api/video/refresh` writes.

**Regression risk:** none from this build. A future tokenizer or column change would silently drop tag matches.
</impact>

<impact path="client/backend/server.py" element="PROXY_ALLOWED_QUERY_PARAMS['/api/v1/search/videos'] (104); _sanitize_query (138-154); _filter_payload (1393-1419)">
**What changes:** line 104 becomes `{"q", "page", "limit", "sort", "nsfw", "tag"}`.

**Behaviour inherited from existing code**
- `_sanitize_query` strips `tag`, since it is not in `PROXY_UNSTRIPPED_QUERY_PARAMS` (120), and drops it when empty. `parse_qs` at 644 has no `keep_blank_values`, so `?tag=` or `?tag=%20` reaches the Engine as missing and gets "Missing query parameter q".
- A repeated `tag` gets the gateway's own 400.
- The route is already in `FILTERED_ROUTES` (83) and `PROXY_READ_GET_ROUTES` (95-97), so keyed tag results get blocks and reaction marks. Search is not in `FEED_ROUTES`, so there is no over-fetch.
- `_filter_payload` round-trips row dicts, so `tags` passes. It re-encodes with default `ensure_ascii`, so non-ASCII tags arrive as `\u` escapes, which is equivalent JSON.

**What depends on it:**
- `client/frontend/src/data/search.ts`, whose docstring names "exactly five" parameters.
- Gateway tests that drive search (`test_frontend_blocks.py:99`, `test_frontend_follows.py:83`, `test_frontend_reactions.py:55`, `test_frontend_upnext_pager.py:79`). No test asserts `Unknown query parameter: tag`.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/components/video-card.ts" element="new exports tagSearchUrl / renderTagChips / observeTagRows; renderVideoCard (341-419); new stylesheet import; module docstring (1-12)">
**What changes**
- **`tagSearchUrl(tag, apiParam)`:** builds `URLSearchParams` with `tag`, and with `api` only when `apiParam && import.meta.env.DEV`, mirroring `videoPageUrl` (330). Returns `/search.html?…`.
- **`renderTagChips(tags, apiParam)`:**
  - Returns `""` for a missing, non-array or empty value. Rows cached before the deploy lack `tags`: `data/cache.ts:46-66` keeps keyless search/feed payloads in sessionStorage (30 s TTL for search).
  - Otherwise returns `<div class="card-tags">` with `<a class="tag-chip" href="${escapeHtml(tagSearchUrl(...))}">${escapeHtml(tag)}</a>` per tag, then a `+N` marker that starts `hidden` and has an `aria-label`.
  - The page CSP (`search.html:8` and every page's line 8: `style-src 'self'`) blocks inline `style="..."` in inserted markup. Hiding must use the `hidden` attribute or classes. Setting CSSOM `el.style.x` from script is still allowed.
- **`observeTagRows(container)`:**
  - One `MutationObserver` (childList + subtree) registers added `.card-tags`, including those inside added `<article>`s, with one shared `ResizeObserver`, and unobserves removed rows.
  - The fit un-hides all chips, then hides from the end and sets `+N`.
  - Neither observer may be constructed at module level, because node harnesses import this module without them.
- **`renderVideoCard`:** puts the chip row after `</a>` (416), beside `actionsMarkup`, inside `<article>`, so there is no nested `<a>`. It passes `options.apiParam`.
- **Stylesheet:** a side-effect CSS import.
- **Docstring:** extend the escaping discipline in 5-8 to tags.

**What depends on it**
- `pages/videos/index.ts:36-51`: the home feed, and the `/videos.html?id=` similar view, which also renders through `renderVideoCard`.
- `pages/search/index.ts:14-20`.
- `pages/likes/index.ts:9`: imports helpers only, but it also pulls in the new CSS.
- `pages/video-page/index.ts:29` (`followLabel`).
- Test bundles: `test_frontend_video_card.py:39` (`--loader:.css=empty`) and `test_frontend_reactions.py:106-121`, which bundles `renderVideoCard` **without** `--loader:.css=empty`. esbuild then emits `bundle.css` beside `bundle.mjs`, and the import must resolve.

**Regression risk: medium.**
- An unescaped tag is an XSS sink through `innerHTML`, `insertAdjacentHTML` and `outerHTML`.
- An eagerly constructed observer throws `ReferenceError` in harnesses.
- `renderCards`' `existingCount` counts `.video-card` (`videos/index.ts:403`), so the new row does not disturb it.
</impact>

<impact path="client/frontend/src/tags.css (new file; name to be chosen)" element="new shared sheet: .tag-chip moved from video.css, plus .card-tags row rules">
**What changes**
- `.tag-chip` moves here from `video.css:408-415`. It uses `--line` and `--ink`, which are defined in `base.css`.
- Chips become `<a>`. No global `a` rule exists (only scoped ones such as `.video-link` in `videos.css:297-302`), so the sheet must add `text-decoration: none` and an explicit colour.
- `.card-tags` is a no-wrap flex row with `overflow: hidden` and `min-width: 0`. Its padding lines up with `.card-actions` (`videos.css:496-502`, `0 1.05rem 0.9rem`) on feed cards; inside an up-next card it sits within that card's own 0.8rem padding.
- A `[hidden] { display: none }` override is mandatory if chips or the marker use a display value. The precedent is `video.css:485-488`.

**Build output — the main hazard**
- `video-card.ts` is a shared Vite chunk (`dist/index.html:14`, `dist/videos.html:14`; `dist/assets/video-JaFxioHf.js` imports `./video-card-DWtpz1-l.js`). A CSS import there makes Vite emit a separate `video-card-*.css`, linked from index, videos, likes, search and video-page.
- `tests/active/test_frontend_base_css.py:100` asserts exactly `["channels","search","video","videos"]`, and 105-115 require every linked bundle to open with the built base rules.
- If the sheet `@import`s `./base.css` (as `videos.css:1` does) to pass, base is duplicated. Link order is not controlled (`dist/search.html:19-20` already links search then videos), so a later duplicate base can re-override page rules.

**What depends on it:** `tests/config.json` groups `test_frontend_base_css.py` (355-362) and `test_frontend_dist.py` (363-412) should list it.

**Regression risk: high** (build/test contract).
</impact>

<impact path="client/frontend/src/video.css" element=".tag-list (402-406), .tag-chip (408-415), .similar-card-item (528-539) and :hover (541-544)">
**What changes**
- Remove `.tag-chip`.
- `.similar-card-item` keeps the padding, radius, border, background, transition and hover. A div needs no `text-decoration`/`color`, so those move to a new `.similar-card-link`, which takes `display: flex; flex-direction: column; gap: 0.5rem` to keep the inner spacing. The item still needs a column/gap so the link and the chip row stack.
- `.similar-thumb`, `.similar-title`, `.similar-channel` and `.similar-meta` (546-602) and `.similar-reaction` (309-325) are class selectors and still match inside the link.
- `.tag-list` stays wrapping (the video page lists every tag) and must not pick up `.card-tags` no-wrap.
- Name check: `.similar-card` (36) is the section panel, a different selector from `.similar-card-link`.

**What depends on it:** `test_frontend_base_css.py` (the video bundle still opens with base and has page rules), `test_frontend_dist.py`, and `test_frontend_video_page.py`, whose group lists `video.css` (`tests/config.json:230`).

**Regression risk: low-medium** (visual only, on the up-next grid `.similar-grid` 522-526).
</impact>

<impact path="client/frontend/src/videos.css" element=".video-card (281-290), .video-card:hover (292-295), .card-actions (496-502)">
**What changes:** probably none, since the new sheet supplies the row. The chip row becomes a direct child of the `.video-card` flex column after `.video-link`. Its order relative to `.card-actions` is the build's choice.

**What depends on it:** `.cards-grid` (257-273) on the feed and search pages.

**Regression risk: low.** Cards with tags grow by one line (an accepted tradeoff). The hover transform moves the chips with the card.
</impact>

<impact path="client/frontend/src/pages/video-page/index.ts" element="tag chips in the metadata render (290-304); import (29)">
**What changes**
- `document.createElement("span")` (295) becomes `createElement("a")`, with `className = "tag-chip"`, `textContent = tag` and `href = tagSearchUrl(tag, params.get("api"))`. The page has no `apiParam` variable; `params` is at line 82.
- Add `tagSearchUrl` to the import at 29.
- The "No tags" branch (302) stays.

**What depends on it:** `test_frontend_video_page.py:189,307-330` reads `#video-tags` children's text and `tag-chip` class. Its recording element supports `href` (86-87), so an `<a>` passes. A new `href` assertion belongs there.

**Regression risk: low.** The chips stay text-built.
</impact>

<impact path="client/frontend/src/pages/video-page/index.ts" element="renderSimilarCard (1688-1721), applySimilarStatsToDom (1610-1617), similarCards render sites (357, 369, 375, 384, 388, 708)">
**What changes**
- The outer `<a class="similar-card-item" href=… ${keyAttribute}>` (1710) becomes `<div class="similar-card-item"${keyAttribute}>` wrapping `<a class="similar-card-link" href="${escapeHtml(videoPageUrl(row))}">…</a>`, plus `renderTagChips(row.tags, params.get("api"))`.
- The page's local `videoPageUrl` (1655-1676) adds no `api`.
- The page has its own `escapeHtml` (1821). `renderTagChips` escapes with video-card's.
- Call `observeTagRows(similarCards)` once. `similarCards` is nullable (61), so call it after a null check, for example in `loadSimilarVideos` after 343 or at module level, guarded.
- `applySimilarStatsToDom` still finds `[data-video-key]` (on the div) and `[data-stat="views"]`.

**Render sites:** 375 (`innerHTML`, first batch) and 708 (`insertAdjacentHTML`, reveal). The loading, error and key-rejected writes hold no chips.

**What depends on it**
- `test_frontend_video_page_similars.py`: the regexes at 141 and 153 match `<a … class="…similar-card-item…">` and must change to the div (or to `-link`); docstring 4-5 says "anchors".
- That runner's `document.getElementById` returns an element for every id (69), so `observeTagRows` runs at load and needs a `MutationObserver` stub; the runner has only `ResizeObserver` (75).
- Behaviour: up-next middle-click and open-in-new-tab now apply to the inner link only. The card padding is no longer a link.

**Regression risk: medium.**
</impact>

<impact path="client/frontend/src/pages/videos/index.ts" element="cards container (55-68), renderCards (390-409), renderFeedCard (414-423), runCardAction outerHTML (457), removeRows">
**What changes:** call `observeTagRows(cards)` once after the guard at 66-68. `renderFeedCard` already passes `apiParam` (84, 418). The delegated click handler (around 151-157) acts only on `[data-card-action]`, so a chip is a plain link. The same container serves the `/videos.html?id=` similar view.

**What depends on it:** `test_frontend_videos_page.py`.
- Harness 1 (36-71) defines neither `ResizeObserver` nor `MutationObserver`.
- Harness 2 (303-324) defines only `ResizeObserver` (316).
- Both bundle this page (130, 402).

**Regression risk: medium.** An unstubbed or eagerly constructed observer fails every case at import.
</impact>

<impact path="client/frontend/src/pages/search/index.ts" element="state (60-73); init (75-76, 139-144); submit (95-103), sort-change (105-108), popstate (126-137) handlers; startSearch (165-172); loadPage (180-236); showIdle (342-352); pushUrl (357-368); resolveSort (381-384); module docstring (1-10)">
**What changes**
- `state.tag` is added. On load, `tag` with no `q` means tag mode; `q` with `tag` means `q` wins and `pushUrl(true)` drops `tag` with `replaceState`.
- **Initial load:** the idle branch (142-143) calls `showIdle()`, which calls `pushUrl()` (351), which calls `pushState`. Tag mode must take its own branch before that, or the load pushes a history entry and drops `tag`.
- **Title:** `"<tag> - Tag - Search - PeerTube - Browser"`. The heading is filled with `textContent`.
- **Sort:** `resolveSort` defaults to `relevance` (383) and needs a mode-aware default (`published_at` in tag mode). The relevance `<option>` is hidden and disabled in tag mode and restored on leaving it.
- **Sort change:** returns early on `!state.query` (106), which would block tag mode.
- **Popstate:** reads only `q`/`sort` and calls `showIdle()` when `q` is empty (126-137), which would turn back-navigation into a tag page into idle.
- **Submit:** clears `tag` and restores relevance. The empty-submit path (98-100) goes through `showIdle`, which must also clear `state.tag`.
- **pushUrl:** writes `tag` in tag mode and omits `sort` when it equals the mode default.
- **loadPage:** passes `tag` or `q` to `fetchSearchResults` (193-199). Status strings 226 and 233 become "No videos tagged …" and "Showing X of Y videos tagged …". The comment at 231-232 ("fused candidate pool") is false in tag mode.
- **Errors:** a hand-made `tag` over 64 characters gets an Engine 400. `fetchSearchResults` throws a generic Error, and 210 shows "Search failed. The Engine may be unavailable." That is misleading but inherited; the page may cap or validate the tag itself.
- Call `observeTagRows(results)` once.
- **Docstring:** line 6 ("until the Engine's candidate pool is exhausted") needs updating for tag mode.

**Unchanged:** the results click handler (110-116). The `outerHTML` re-renders (290, 295) and `removeRows` (335) are covered by the observer.

**What depends on it:** no test bundles this page; `tests/config.json:405` lists it only for `test_frontend_dist.py`. Tag mode has no harness.

**Regression risk: medium.** It is a multi-handler state machine with no tests.
</impact>

<impact path="client/frontend/search.html" element="new tag heading element in .search-controls (31-56); #search-sort relevance option (47); CSP (8)">
**What changes:** a new element, for example `<h2 id="search-tag-heading" hidden>`. The relevance `<option>` (47) is toggled from script. The CSP (8, `style-src 'self'`) stays as it is and constrains the chip markup.

**What depends on it:** `requireElement` (39-45) throws on a missing id. `test_frontend_dist.py` compares `dist/search.html` with a fresh build.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/search.css" element="optional heading rule">
**What changes:** optionally style the tag heading.

**What depends on it:** `test_frontend_base_css.py`: the search bundle keeps base first, then page rules.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/data/search.ts" element="FetchSearchOptions (24-31), fetchSearchResults (57-91), docstring (1-9)">
**What changes**
- `q` becomes optional and `tag?: string` is added. The function sets exactly one of them; 60-61 always sets `q` today.
- The cache key `search:${url}` (80) separates tag pages from text pages.
- The docstring's "exactly five query parameters" becomes six.

**What depends on it:** callers passing `{ q }`: `pages/search/index.ts:193`, `test_frontend_blocks.py:49`, `test_frontend_feed_params.py:315`, `test_frontend_reactions.py:87`. They keep working if `q` keeps its meaning and no empty `tag` is ever set; the feed-params test checks the URL built.

**Regression risk: low.**
</impact>

<impact path="client/frontend/src/types/videos.ts" element="VideoRow (5-62); SearchPayload docstring (70-75)">
**What changes:** add `tags?: string[] | null` to `VideoRow`. The `SearchPayload` docstring says `total` is the fused pool; in tag mode it is the exact pre-moderation match count.

**What depends on it:** type-only, with no runtime effect.

**Regression risk: none.**
</impact>

<impact path="client/frontend/dist/" element="committed build output: the seven HTML pages and assets/">
**What changes:** it must be regenerated with `vite build` and committed. `tests/active/test_frontend_dist.py` compares the committed dist with a fresh build, byte for byte for pages and by name for hashed assets. The new shared CSS chunk adds a `<link rel="stylesheet">` to index, videos, likes, search and video-page. The build must run with no local `dev-pages/about.html` (`vite.config.ts:13-18,91-93`).

**Regression risk: medium.** A stale dist is a certain red.
</impact>

<impact path="tests/active/test_frontend_base_css.py" element="test_every_linked_page_css_bundle_opens_with_the_built_base_rules_then_page_rules_and_holds_no_import (97-115), docstring (1-3)">
**What changes:** this test fails as soon as `video-card.ts` imports a sheet. The control at 100 expects four bundles, and 106/113 require base first in every bundle. Two options:
- Amend it to admit exactly one component bundle that has no base and no `@import`, and update the docstring.
- Change the design: put the chip rules where base already flows, for example in `base.css` (needs operator approval), or import the sheet from each page sheet.

**Regression risk: high.**
</impact>

<impact path="tests/active/test_frontend_dist.py" element="committed-dist-equals-fresh-build test">
**What changes:** no code change. It passes only after `dist` is rebuilt and committed.

**Regression risk: high** if the rebuild is forgotten.
</impact>

<impact path="tests/active/test_frontend_video_page_similars.py" element="_keys regex (140-142), first-batch regex (153), docstring (4-5), RUNNER globals (75-80)">
**What changes**
- Retarget the regexes to the `<div … similar-card-item … data-video-key>` (or to `similar-card-link`).
- Update the docstring wording ("anchors").
- Add a recording `MutationObserver` stub, and optionally assert that one observer watches `similar-videos` with `childList` and `subtree`.

**Regression risk: high.** This break is known and certain.
</impact>

<impact path="tests/active/test_frontend_video_page.py" element="RUNNER globals (109-117), PAGE_RUNNER globals (648-662), tag assertions (4, 189, 307-330)">
**What changes**
- Both harnesses define `ResizeObserver` (116, 661) and no `MutationObserver`. Add stubs, because both bundle the video page.
- Add an `href` assertion on the chips (`/search.html?tag=…`).

**Regression risk: medium.** A `ReferenceError` at import fails every case.
</impact>

<impact path="tests/active/test_frontend_translate.py" element="video-page harnesses (106-164 and 432-485)">
**What changes:** they bundle `pages/video-page/index.ts` (228, 550) and define `ResizeObserver` (158, 479) but no `MutationObserver`, so add stubs. The `translate.ts`-only harness (733-737) is unaffected.

**Regression risk: medium.**
</impact>

<impact path="tests/active/test_frontend_videos_page.py" element="harness 1 globals (36-71) and harness 2 globals (303-324)">
**What changes:** harness 1 needs both `ResizeObserver` and `MutationObserver` stubs; harness 2 needs `MutationObserver`. Optionally assert that one observer watches `video-cards`.

**Regression risk: medium.**
</impact>

<impact path="tests/active/test_frontend_reactions.py" element="_bundle (106-124)">
**What changes:** it bundles `renderVideoCard` with no CSS loader flag (116-120). With a CSS import, esbuild writes `bundle.css` next to `bundle.mjs`, and the JS still runs provided the CSS resolves. Optionally add `--loader:.css=empty` for parity with the other bundlers.

**Regression risk: low.**
</impact>

<impact path="tests/active/test_frontend_video_card.py" element="card assertions (45-62)">
**What changes:** none required. Its rows carry no `tags`, so they exercise the no-tag-line case. It is the home for new unit cases on `renderTagChips` and `tagSearchUrl`:
- escaping of `<`, `"`, `&` and `'`
- an empty or missing list
- the hidden `+N` marker
- `api` only in DEV
- no `style=` attribute anywhere, because of the CSP

**Regression risk: low.**
</impact>

<impact path="tests/active/test_search.py" element="fixture _statements (36-54), _CHILD runner (57-83)">
**What changes:** this is the place for data-layer tag tests on `ENGINE_PY`:
- token and fallback paths
- malformed, object and NULL `tags_json`
- trimming and case, including `MÚSICA`/`música`
- NSFW `total`
- paging past the end
- sort orders

The fixture inserts no `tags_json` today (49), so it needs extending or a sibling file. `server` lacks `statement_timeout_seconds`, so `search_deadline` gets 0.

**Regression risk: low.**
</impact>

<impact path="tests/active/test_similar.py" element="_rows (138-153) and test_every_row_carries_the_channel_and_account_the_dataset_holds (156-166)">
**What changes:** AC1 needs `tags` on every mode. The parametrisation covers home, random, upnext and search; add trending, popular, recent and following (with a `follows` body), and the `GET /videos/{id}/similar` alias. Live tag-route cases go here: the 400s, sort echo, `vectorSearch` false, exact `total`, and NSFW.

**Regression risk: low.**
</impact>

<impact path="tests/active/conftest.py" element="identity_of (305-312), dataset fixture (250-257)">
**What changes:** a per-mode `tags` comparison needs the stored `tags_json`. `identity_of` is shared by several tests and returns exactly `{channel_id, account_url}`, so extend it carefully or add a sibling helper. Tests that compare whole dicts from it would otherwise break.

**Regression risk: low.**
</impact>

<impact path="tests/config.json" element="test_groups: test_frontend_base_css (355-362), test_frontend_dist (363-412), test_frontend_video_page (228-233), test_frontend_video_page_similars (238-241), test_frontend_videos_page (272-278), test_search (261-264)">
**What changes**
- Add the new sheet to the base-css and dist groups.
- Add `components/video-card.ts` to the video-page and similars groups, which now depend on it.
- Add `server_config.py` if the constant is added.
- Map any new test file, for example a search-page harness.

**Regression risk: low.** A missed mapping only means a test is not reselected on edit.
</impact>

<impact path="docs/project/adr/0007-nsfw-filter-default-at-request-edge.md" element="Decision 1-2 and Consequences (14-27)">
**What changes:** nothing is required. It constrains the build: the new function defaults `include_nsfw=True`, and `_handle_search` must pass the parsed flag. Decision 2 names only `search_videos` as `_handle_search`'s callee; a one-line amendment is optional.

**Regression risk:** forgetting the flag serves NSFW tag results to every visitor.
</impact>

### docs_checklist

<doc path="engine/server/README.md">
"What it does" (lines 6-28) has no bullet for `GET /api/v1/search/videos`; only line 53 mentions it, for `nsfw`. Add one covering:
- `q` text search.
- The `tag` mode: exact match after trimming and lowercasing both sides; exclusive with `q`; 400 for both, for blank, for over 64 characters, and for neither.
- Sort: relevance or none means newest in tag mode; views and popularity reorder; anything else is 400.
- `page` and `limit` with the `SEARCH_MAX_LIMIT` cap.
- `total`: the exact pre-moderation match count in tag mode, against the 200-candidate pool in text mode.
- `vectorSearch` is false in tag mode.
- Every listing row (search, every feed mode, up-next) now carries `tags`: a list in the uploader's order, `[]` for NULL, invalid or non-list.

Extend line 53 so the NSFW filter also covers tag search.
</doc>
<doc path="client/README.md">
- Line 34: `/api/v1/search/videos` now also allowlists `tag`, which is stripped and dropped when empty.
- Line 29: block filtering and reaction marks (no dislike removal, no over-fetch) apply to tag results too.
</doc>
<doc path="client/frontend/README.md">
- Feed, search and up-next cards show tag chips linking to `/search.html?tag=…`, fitted to one line with a `+N` marker. The video page's tags become links.
- The search page's tag mode: heading, title format, the "Showing X of Y videos tagged …" and "No videos tagged …" status lines, relevance hidden with `published_at` as the default, `tag` and `sort` in the URL, a submit leaving tag mode, and a URL with both `q` and `tag` reduced to `q`.
- Line 18: the "Showing N of M matched videos." wording applies to text search only.
</doc>
<doc path="CONTEXT.md">
Add a glossary entry for **Tag** / **tag search**:
- the uploader's tags as stored in `videos.tags_json`;
- two tags are the same after trimming and lowercasing;
- language variants stay distinct;
- tag search is the exact-tag mode of the search route, distinct from the full-text match on the `tags_json` FTS column.
</doc>
<doc path="docs/project/roadmap.md">
After delivery, add a DONE line for issue 42's first plan (tags on cards and exact-tag search) pointing at `docs/project/plans/54-53-tags-on-cards-and-tag.md`. It should note that multi-tag narrowing, feed and up-next tag filters, and advanced search remain open.
</doc>
<doc path="docs/project/issues/42-tags-on-cards-and-tag-search.md">
Record what this plan delivered (tags on every card, clicking a tag gives exact-tag results) and what stays open. The issue stays open, since the operator expects more plans.
</doc>
<doc path="docs/project/adr/0007-nsfw-filter-default-at-request-edge.md">
Optional: in Decision 2, name the new tag-search function as a second `include_nsfw` callee of `_handle_search`.
</doc>

### highest_risk

client/frontend/src/components/video-card.ts importing the new chip stylesheet: `video-card` is already a shared Vite chunk, so its CSS becomes a fifth linked bundle on index, videos, likes, search and video-page. `tests/active/test_frontend_base_css.py:100,105-115` accepts exactly four bundles, each opening with base. `@import`ing base to pass that duplicates base, which can re-override page rules depending on link order. On top of that, `client/frontend/dist` must be rebuilt and committed or `test_frontend_dist.py` goes red.
client/frontend/src/components/video-card.ts `observeTagRows` (MutationObserver + ResizeObserver), called from three pages: seven node harnesses that bundle those pages have no `MutationObserver` (`test_frontend_video_page.py` ×2, `test_frontend_video_page_similars.py`, `test_frontend_translate.py` ×2, `test_frontend_videos_page.py` ×2, where harness 1 also lacks `ResizeObserver`), so any eager construction fails whole files. The pages' CSP `style-src 'self'` also silently drops inline style attributes in chip markup; that passes every harness and breaks only in a browser.
engine/server/data/search.py new tag-search SQL: correctness rests on SQLite details. `json_each` needs the CASE/`json_valid`/`json_type` guard inside its argument, or one malformed row 500s the query and object values false-match. `lower()` is Unicode-aware only in the Engine's library build, which I cannot verify from files, so tests must run on `ENGINE_PY`. The Python `strip` vs SQL `trim`-set mismatch, FTS phrase quoting, and the ADR-0007 `include_nsfw` flag (forgetting it leaks NSFW) all sit in this one function.

## 2026-10-06 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: YES.

I checked the inventory against the main checkout, because `.worktrees/55` does not exist yet. I read `similar.py` (the projection, `_handle_search`, `_serve` and its deadline handling), all of `data/search.py`, `data/db.py`'s `statement_deadline`, the import headers and tag helpers in `video.py`, the search-lock wiring in `server.py`, `vite.config.ts`, the stylesheet links in every built `dist/*.html`, `video-card.ts`, all of `pages/search/index.ts` and `data/search.ts`, and the up-next renderer and its stats update. I also opened every frontend test harness that bundles a page or `video-card.ts`. Every entry I checked holds up, including the line numbers. Every stub gap in the inventory is real, and no other harness bundles a page that imports `video-card.ts`: the channels, blocks, follows, profile, feed-params and up-next-pager harnesses import only `data/*` or the channels page. I found two things the inventory does not carry. Both come from shared machinery the tag path now loads harder: the single search lock, and the frontend turning every 503 into "no full-text index". I found no conflict with the requirements or the plan.
<question id="1">
Yes. `stable_video_row` (similar.py:129-131) is the one projection both callers use. `tags_from_json` (video.py:164-174) never raises. `video.py` imports only `data.*`, `http_utils` and `server_config`, so importing it from `similar.py` creates no cycle. `VIDEO_ROW_SQL` already selects `v.tags_json` (search.py:66).

The tag branch fits cleanly into `_handle_search`:
- It goes after the `SEARCH_ENABLED` gate (426-428).
- It reuses `limit`/`page` (440-446), the `SearchIndexMissing` → 503 handler (464-467), moderation (468-472) and the response (474-486).
- `search_connection`, `search_deadline`, `fts_available`, `LEXICAL_SORTS`, `NSFW_ALLOWED_SQL` and `_TOKEN_SPLIT` all exist in the forms the plan uses.
- The prefilter phrase is safe: `_TOKEN_SPLIT` removes `"`, and FTS5 re-tokenises a quoted phrase with `unicode61` itself. A tag like `my_tag` therefore becomes the phrase `my tag`, which still matches. The Rt1 gap is narrower than the plan feared.

On the frontend:
- `video-card.ts` is already the shared chunk for index, videos, search, likes and video-page (dist links confirm this).
- The only click delegations on card containers act on `[data-card-action]` (`videos/index.ts:151`, `search/index.ts:110-116`), so a chip link navigates normally.
- `applySimilarStatsToDom` (1610-1617) looks up `[data-video-key]` and `[data-stat="views"]`, so it survives the `<a>`→`<div>` change.

It works as intended once the contract work the inventory lists is done:
- Amend the base-CSS test or change the stylesheet design.
- Rebuild `dist`.
- Retarget the up-next regexes.
- Add `MutationObserver` stubs to the harnesses.
</question>
<question id="2">
The ramifications:
- Every listing payload grows by a `tags` array, which is remote-controlled text, and three `innerHTML` sinks now render it.
- A fifth CSS bundle is linked from five pages. That breaks the four-bundle contract in `test_frontend_base_css.py:100,106,113`.
- Up-next cards stop being one link. Only the inner link navigates, and the card's padding no longer does.
- Tag search costs two SQL statements per page. On the no-word-token fallback, both are full scans of about 0.7 s each.

Two ramifications are not in the inventory:
- **The search lock.** A fallback tag query holds the single `search_db_lock` (server.py:293) for its whole duration (about 1.4 s). Every concurrent text or tag search queues behind it. The wait is not bounded, because `search_deadline` (search.py:46-49) starts the 5 s budget only once the lock is held.
- **The 503 message.** If a slow or deep tag page hits the deadline, the Engine answers 503 "Query time limit exceeded" (similar.py:400). `fetchSearchResults` turns any 503 into `SearchUnavailableError` (data/search.ts:73,86), so the page says the dataset has no full-text index.
</question>
<question id="3">
Everything the inventory lists. The items it marks as certain reds:
- **Base-CSS test** (`test_frontend_base_css.py:100`): amend it, or keep the chip CSS out of a fifth bundle.
- **Committed `dist`:** rebuild and commit it, with no local `dev-pages/about.html`.
- **Up-next regexes** (`test_frontend_video_page_similars.py:141,153`): retarget them to the new markup.
- **`MutationObserver` stubs:** add them to `test_frontend_video_page.py` (116, 661), `test_frontend_video_page_similars.py` (75), `test_frontend_translate.py` (158, 479) and `test_frontend_videos_page.py` (harness 1, and 316). Harness 1 also needs a `ResizeObserver`.
- **Observers in `observeTagRows`:** construct them lazily inside the function, never at module level.

Beyond those, the build must keep these existing behaviours:
- **Text search:** relevance stays its default; resolving relevance to `published_at` applies only in tag mode.
- **NSFW:** pass `_parse_include_nsfw` to the new function (ADR-0007).
- **Exact check:** bind the Python-stripped tag value.
- **Search page:** take a dedicated tag-mode branch before `showIdle()` (search/index.ts:139-144, 342-352), so loading a tag URL neither pushes history nor drops `tag`. Make the sort-change handler (106) and the popstate handler (126-137) mode-aware.
- **Chip CSS:** use the `hidden` attribute or classes, never inline styles (the CSP).

Nothing extra is needed to keep the two new impacts from breaking existing behaviour. Both are degradations, covered under recommendations.
</question>
<question id="4">
For existing callers:
- Every row from search, feeds, up-next and the similar view carries an additional `tags` key. The key is additive and no test compares exact key sets.
- `/api/v1/search/videos` accepts `tag`. Text-search requests behave as before, and `q` plus `tag` together get a 400.
- Up-next cards change from one `<a class="similar-card-item">` to a `<div>` holding `<a class="similar-card-link">` and a chip row. Middle-click and open-in-new-tab now work only on the link area.
- The video page's chips become links.
- `.tag-chip` styling moves from `video.css` into a shared chunk.
- Cards with tags are one line taller.
- The likes page now loads the chip stylesheet without using it.
- Text search is otherwise unchanged. It does, however, now share the search lock with tag queries that can hold it longer than any text query does today.
</question>

New impacts:
engine/server/api/server.py (search_db_lock, 293) with engine/server/data/search.py (search_connection 32-43, search_deadline 46-49): there is one process-wide lock for all search statements, and the new tag function holds it across both of its statements. On the fallback path that is about 1.4 s per page. Every concurrent text and tag search waits behind it. The wait is unbounded: `threading.Lock` blocks without a timeout, and `search_deadline` starts the budget only after the lock is taken, replacing the request-level deadline that `_serve` set (similar.py:410-418, db.py:60-65). A handful of `?tag=%2B%2B`-style requests therefore stalls search for everyone, inside the per-IP rate limit. Regression risk: medium under load, none at rest.
client/frontend/src/data/search.ts (fetchSearchResults 73 and 86) with client/frontend/src/pages/search/index.ts (204-205): every 503 becomes `SearchUnavailableError`. The page then says "Search is not ready yet: the dataset has no full-text index." That includes the Engine's 503 "Query time limit exceeded" (similar.py:400), which tag search makes more reachable through fallback scans and deep `OFFSET` pages now that `total` is exact. The keyless path cannot read the body, because `fetchJsonWithCache` throws only `HTTP <status> for <url>`. Regression risk: low (wrong message only).

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Base-CSS bundle test.** Amend `test_frontend_base_css.py` so it admits exactly one component bundle (`video-card-*`) that has no base prefix and no `@import`. The other four bundles keep every existing assertion, and the docstring is updated. Cost: a test-contract edit plus one extra stylesheet request on five pages. This keeps the settled plan. The alternatives are putting the chips in `base.css` (about 20 lines in every bundle, needs the operator's approval) or importing the sheet from each page sheet. Both depart from the plan.

2. **Test doubles the plan widens.** These are the `MutationObserver` stubs in `test_frontend_video_page.py` (both harnesses), `test_frontend_video_page_similars.py`, `test_frontend_translate.py` (both video-page harnesses) and `test_frontend_videos_page.py` (both harnesses). Harness 1 of `test_frontend_videos_page.py` also needs a `ResizeObserver`.
   - **What to do:** make each new stub a recording double. It records the `observe(target, options)` calls, and each harness asserts that exactly one observer watches its container (`similar-videos` or `video-cards`) with `childList` and `subtree`.
   - **The up-next test:** retarget its regexes to the `<div … similar-card-item … data-video-key>` and update the "anchors" wording. Do not filter the new markup or the observer calls out of it.
   - **Cost:** a few lines per harness. A harness that does not care about tags can use a silent no-op stub instead, but only one that does not observe calls, and only if the operator prefers less test code.

3. **Search-lock contention (new).**
   - **Cheapest:** accept and document the risk. Add a `[search] tag` log line with the path taken (prefilter or fallback) and the elapsed time, so contention shows up in the Engine log. Cost: one log statement.
   - **Bounded:** acquire `search_db_lock` with a timeout for the tag path, and answer 503 when the wait exceeds the deadline. Cost: about 5 lines and one test. It also changes how text search fails under contention if applied to both paths, so it should apply to the tag path only.

   I recommend the log line now and the bounded acquire only if the log shows fallback queries are common.

4. **Misleading 503 message (new).** Accept it as inherited: text search already maps a deadline 503 to the same message. Optional fix: have the keyed path read the body's `error`, and have the keyless path map 503 to a neutral "Search is unavailable right now" unless the body says the index is missing. That needs `fetchJsonWithCache` to surface the body. Cost: a change in `data/cache.ts` that every cached caller shares, which is larger than this build should take on. I recommend deferring it to an issue.

5. **Tag length constant.** Add `SEARCH_MAX_TAG_LENGTH = 64` to `server_config.py`, beside `SEARCH_MAX_TOKEN_LENGTH`, and add `server_config.py` to the `test_search`/`test_similar` groups in `tests/config.json`. Cost: two lines plus the config mapping. Its 64-character limit is a different cap from `SEARCH_MAX_TOKEN_LENGTH`, and a literal in the handler hides that.

6. **Exact-match binding.** Bind the Python-stripped tag, not the raw parameter, in the SQL exact check, and keep the explicit trim set in SQL for the stored side. This costs nothing. It closes the NBSP gap the inventory names, where a tag passes validation and then never matches.

## 2026-10-06 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

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

### docs_checklist

<doc path="engine/server/README.md">
"What it does" (6-28) has no bullet for `GET /api/v1/search/videos`; only line 53 mentions it, for `nsfw`. Add one covering:
- `q` text search.
- The exclusive `tag` mode: an exact match after trimming and lowercasing both sides.
- The 400s: both parameters, a blank tag, a tag over 64 characters, and neither.
- Sort: relevance or none means newest in tag mode; views and popularity reorder; anything else is 400.
- `page` and `limit` with the `SEARCH_MAX_LIMIT` cap.
- `total`: exact and pre-moderation in tag mode, against the 200-candidate pool in text mode.
- `vectorSearch` is false in tag mode.
- Every listing row now carries `tags`: in the uploader's order, `[]` for NULL, invalid or non-list values.

Extend line 53 so the NSFW filter also covers tag search.
</doc>
<doc path="client/README.md">
- Line 34: `/api/v1/search/videos` also allowlists `tag`, which is stripped and dropped when empty.
- Line 29: blocks and reaction marks apply to tag results (no dislike removal, no over-fetch).
</doc>
<doc path="client/frontend/README.md">
- Feed, search and up-next cards show tag chips linking to `/search.html?tag=…`, fitted to one line with a `+N` marker. Video-page tags become links.
- The search page's tag mode:
  - the heading and the title format
  - the "Showing X of Y videos tagged …" and "No videos tagged …" status lines
  - relevance hidden, with `published_at` as the default
  - `tag` and `sort` kept in the URL
  - a submit leaving tag mode
  - a URL with both `q` and `tag` reduced to `q`
- Line 18: "Showing N of M matched videos." applies to text search only.
- Line 8: the gateway routes list is unchanged.
</doc>
<doc path="client/frontend/src/data/search.ts">
The module docstring (1-9) says the gateway allowlists "exactly five query parameters". It becomes six, with `tag`, and the function sends exactly one of `q` and `tag`.
</doc>
<doc path="CONTEXT.md">
Add a glossary entry for **Tag** / **tag search**:
- the uploader's tags as stored in `videos.tags_json`
- two tags are the same after trimming and lowercasing; language variants stay distinct
- tag search is the exact-tag mode of the search route, distinct from the full-text match on the `tags_json` FTS column
</doc>
<doc path="docs/project/roadmap.md">
After delivery, add a DONE line for issue 42's first plan (tags on cards and exact-tag search) pointing at `docs/project/plans/54-53-tags-on-cards-and-tag.md`. Note that multi-tag narrowing, feed and up-next tag filters, and advanced search remain open.
</doc>
<doc path="docs/project/issues/42-tags-on-cards-and-tag-search.md">
Record what this plan delivered and what stays open. The issue stays open (`Status: enhancement, needs-triage` at line 3), because the operator expects more plans.
</doc>
<doc path="docs/project/adr/0007-nsfw-filter-default-at-request-edge.md">
Optional: in Decision 2 (line 17), name the new tag-search function as a second `include_nsfw` callee of `_handle_search`.
</doc>

### highest_risk

client/frontend/src/tags.css (the new stylesheet imported by components/video-card.ts) with tests/active/test_frontend_base_css.py: `video-card` is already its own Vite chunk, so a CSS import emits a fifth `video-card-*.css` bundle linked from five pages. `test_frontend_base_css.py:100` pins the bundle list to exactly channels/search/video/videos, and 105-115 require each bundle to open with the full base, so the plan as written goes red. The fix needs a test amendment or a design change, and also a rebuilt, committed dist.
engine/server/data/search.py (the new tag-search function): the correctness of its SQL rests on three things. `json_each` must be guarded inside its argument against malformed or non-array `tags_json`. The explicit trim set must be used. And it depends on Unicode `lower()`, which no Engine connection registers (only `ann_id_of` exists) and which SQLite core folds for ASCII only, so it rests entirely on the env's SQLite build. A mistake gives either a 500 on one bad row or silently ASCII-only matching.
client/frontend/src/components/video-card.ts observeTagRows, with every node harness that bundles a page (test_frontend_video_page.py, test_frontend_video_page_similars.py, test_frontend_translate.py, test_frontend_videos_page.py): none defines `MutationObserver`. An unguarded construction throws at import and fails every case in four files, and the similars regexes at 141 and 153 break for certain on the `<a>`→`<div>` change. Separately, stored blank or over-64-character tags (neither writer caps them) produce chips that link to an idle page or a guaranteed 400 unless the helper filters them.

## 2026-10-06 - Step 4 - Reassess the implementation plan (pass 3)

Pass 3. New impacts: YES.

I checked the inventory against the main checkout (`.worktrees/55` is still absent). I opened: `similar.py` (106-136, 420-486), `data/search.py` (18-172), `handlers/video.py` (150-177), the gateway (`server.py` 100-155), the search page (120-384), `renderSimilarCard` and `applySimilarStatsToDom` in the video page, `video-card.ts`'s imports and `escapeHtml`, `test_frontend_base_css.py`, the similars harness (60-159), `test_frontend_reactions._bundle`, and every observer stub and esbuild call under `tests/active`. Every claim I checked holds as written. The bundles in `test_frontend_blocks`, `test_frontend_feed_params`, `test_frontend_follows`, `test_frontend_upnext_pager` and `test_frontend_channels_page` reach neither `video-card.ts` nor a page that calls `observeTagRows`, so the inventory was right to leave them out. Beyond the inventory I found one real defect in the settled design: the SQL trim set does not match the gateway's `strip()`, although the plan says it does. That defect is the conflict below. The other gap is documentation.
<question id="1">
    Mostly yes. The Engine projection, the `tag` branch, the gateway allowlist and the frontend helpers all fit the code as it stands. The import direction is safe, every row source already selects `tags_json`, and the FTS join, NSFW clause and sort map can be reused as they are. Three things will not work as written:
    - **Base-CSS test.** The new stylesheet imported from `video-card.ts` fails `test_frontend_base_css.py:100` and `:105-115` (already in the inventory).
    - **Harness stubs.** Seven node harnesses have no `MutationObserver` (already in the inventory).
    - **New: whitespace-padded tags.** The exact match misses stored tags padded with whitespace other than space, tab, CR or LF, such as NBSP, U+3000, `\v`, `\f` or U+0085. The gateway (`server.py:151`) and the Engine run `str.strip()` on the requested tag, which removes all of that. The SQL `trim(j.value, set)` removes only the four named characters. So a chip for `"linux\u00a0"` sends `linux`, the stored side compares `"linux\u00a0"`, and the click never returns the video the chip came from. The plan's own rationale says it chose the explicit set because `strip()` removes all whitespace, but the set it names does not match `strip()`.
</question>
<question id="2">
    Ramifications:
    - Every listing payload now carries remote-controlled `tags` into three HTML-string sinks. This is already in the inventory, and `escapeHtml` (`video-card.ts:67-84`) covers it as long as every interpolation uses it.
    - A fifth CSS bundle appears on five pages, and the committed dist must be rebuilt.
    - The up-next card becomes a `div` wrapping a link. The card padding stops being clickable.
    - Tag search costs two statements per page. A views-sorted search on the fallback path sorts the whole match set.
    - Tag mode adds a second state machine to the search page. It is untested, and its `popstate` and idle paths push history today (lines 126-137, 342-352).
    - The README route docs fall behind (new impact).
</question>
<question id="3">
    Everything in the inventory still applies:
    - `observeTagRows` must not construct anything at module load.
    - The node harnesses need `MutationObserver` stubs, and `test_frontend_videos_page`'s first harness also needs a `ResizeObserver` stub.
    - The similars regexes at 141 and 153 must be retargeted.
    - `test_frontend_reactions._bundle` needs `--loader:.css=empty`.
    - The base-CSS contract must be amended, or the sheet placed elsewhere.
    - `dist/` must be rebuilt and committed.
    - Text mode must keep `relevance` as its default sort, or vector fusion silently turns off.
    - The tag branch must sit inside the existing `SearchIndexMissing`→503 handler and pass `_parse_include_nsfw`.
    - `popstate` and `showIdle` must stop pushing history when entering tag mode.

    New on top of that:
    - The stored-tag trim set must equal Python's `str.isspace` set.
    - `engine/server/README.md` and `client/README.md` need the new parameter and the new row key.
</question>
<question id="4">
    What changes for existing behaviour:
    - Every Engine listing row gains a `tags` array. It is additive and no test pins the row's key set.
    - Up-next cards are a `div` with an inner link, not a link, and only the inner area navigates.
    - Feed and search cards with tags grow by one line.
    - Chips on the video page become links instead of inert spans.
    - `.tag-chip` moves out of `video.css`, and a new CSS chunk is linked from index, videos, likes, search and video-page.
    - A search URL carrying both `q` and `tag` is rewritten to the text search.
    - Text search itself is unchanged: same validation, default sort, candidate pool, `total` meaning and `vectorSearch`.
</question>

New impacts:
engine/server/data/search.py (new tag-search function, exact check): the inventory's trim note covers only the requested side, by binding the Python-stripped value. On the stored side, `trim(j.value, ' \t\r\n')` leaves NBSP, `\v`, `\f`, `\x1c-\x1f`, U+0085, U+1680, U+2000-U+200A, U+2028/9, U+202F, U+205F and U+3000 in place, all of which `str.strip()` removes from the request (`client/backend/server.py:151`, and the Engine's own strip). A stored tag padded with any of them never matches its own chip. The fix is to make the SQL trim set exactly the characters for which `str.isspace()` is true, held in one module constant built in Python and bound as a parameter for both trims. That way the request and the stored tags are trimmed by the same set. Cost: a few lines. Risk if missed: low-frequency, silent false negatives that break the requirement that a single-use tag returns its own video.
client/frontend/src/components/video-card.ts (renderTagChips blank-skip): JS `String.prototype.trim` and Python `str.strip` disagree. JS leaves U+0085 and `\x1c-\x1f`, which Python strips, and strips U+FEFF, which Python leaves. A blank-skip written with JS `trim()` therefore still emits a dead chip for a tag made only of `\x85`, because the gateway strips it to nothing and the Engine answers "Missing query parameter q". The skip test should treat a tag as blank when it contains nothing outside the same whitespace set the Engine trims.
engine/server/README.md (route docs, lines 9 and 53): the file documents `/api/video`'s `tags` and lists search among the NSFW-filtered listings, but nothing says that listing rows now carry `tags` or that `/api/v1/search/videos` takes `tag` (its 400s, `published_at` default, exact `total`, `vectorSearch` false). Cost: a paragraph. Risk: stale docs only.
client/README.md (gateway allowlist, lines 29-34): the per-route allowlist description should mention that `tag` is now accepted on `/api/v1/search/videos`, stripped and dropped when empty like every parameter except `nsfw`, and that tag results get block and like/dislike marks but no over-fetch. Cost: one sentence. Risk: stale docs only.

Inventory entries that did not hold up:
none

Conflicts: Settled high-level plan, "Exact check (both paths)": the trim names an explicit whitespace set of space, tab, CR and LF, "because ... the gateway's `strip()` removes all whitespace". Against the settled requirement, Scope "Tag matching": the same normalisation applies to the requested tag and to every stored tag, and a tag used only once returns the video it came from. The requested tag always arrives stripped by Python `str.strip()` (gateway `server.py:151`, then the Engine), which removes every `str.isspace` character. The stored tags are trimmed only of the four named characters. So the two sides are not normalised alike, and a chip whose stored tag is padded with NBSP, U+3000, `\v`, `\f` or U+0085 cannot find its own video. Resolving it means changing the named trim set to the full `str.isspace` set. That is a one-constant change, but it revises a detail the plan settled, so it goes back to the operator.

Recommendations: 1. **Trim set (resolves the conflict).** Replace the four-character SQL trim set with one module constant in `data/search.py`, holding every character for which `str.isspace()` is true. Build it once from `range(sys.maxunicode+1)`, or list its 29 characters literally. Bind it as a parameter to both `trim(j.value, ?)` and `trim(?, ?)`. Add a `test_search.py` case with a stored `"linux\u00a0"` tag that matches a request for `linux`. Cost: about five lines and one test; no runtime cost. Not doing it means accepting silent misses on whitespace-padded tags, which the requirement does not allow.
2. **Chip blank-skip.** `renderTagChips` should skip any tag that is empty after removing that same whitespace set, mirrored as a JS regex, and should not rely on `String.prototype.trim()`. Over-length tags (more than 64 characters after trimming) are still an open choice from the inventory. Skipping them hides a tag the uploader wrote. Linking them gives a guaranteed 400 that the search page shows as "Search failed. The Engine may be unavailable." My recommendation is to render such tags as a non-link chip, which costs one branch. Skipping is the cheaper alternative if the operator prefers it.
3. **Base-CSS contract.** There are two ways to resolve it, and the operator should pick one:
   - Keep the planned sheet and amend `test_frontend_base_css.py` to admit exactly one component bundle that does not open with base. Cost: a test-contract change and its docstring. The sheet must not `@import` base, because a duplicated base in a chunk linked before or after a page sheet can re-override page rules depending on link order.
   - Put `.tag-chip`, `.card-tags` and the `+N` rules in `base.css`. Cost: the plan changes from "a sheet the helper imports" to the shared base, and the chip rules also ship on the channels and about pages, a few hundred bytes. In return there is no new bundle, no test amendment and no new `<link>`, and there is still one copy of the style. This is the smaller change, but it revises the settled plan.
4. **Test doubles.** `observeTagRows` widens what the page modules call on the observer doubles, so the doubles must record the new calls faithfully; filtering the new call out of their assertions is not acceptable.
   - **`MutationObserver` stubs.** In `test_frontend_video_page.py` (both harnesses), `test_frontend_video_page_similars.py`, `test_frontend_translate.py` (both) and `test_frontend_videos_page.py` (both), add a stub that captures each instance with its callback, observed target and options, the way the similars harness's `IntersectionObserver` already does. Add one assertion per page that exactly one observer watches the grid (`similar-videos`, `video-cards`), with `childList: true, subtree: true`.
   - **`ResizeObserver` stubs.** In the harnesses where a stub already exists (video page, similars, translate, the second videos-page harness), make it record its observed targets, so a test can show which chip rows get observed. The first videos-page harness has no `ResizeObserver` stub and needs a recording one.
   - **Retiring instead.** Retiring a double is the alternative only where a harness never needs to show calls. None of these harnesses qualifies.
   - **Cost:** about two lines per harness, plus one assertion per page.
5. **Docs.** Update `engine/server/README.md` and `client/README.md` as listed in new_impacts, and amend ADR-0007 decision 2 to name the tag function beside `search_videos`. Cost: three short edits.
6. **Accept as planned.** Everything else in the inventory stands as written, in particular the similars regex retarget, `--loader:.css=empty` in `test_frontend_reactions`, the rebuilt and committed dist, the per-mode `tags` tests in `test_similar.py`, and the `tests/config.json` group additions.

## 2026-10-06 - Step 4 - Reassess the implementation plan - ceiling reached

3 passes each surfaced new impacts and the loop stops here; the build proceeds on the inventory as it stands. What the 3th pass was still finding:

engine/server/data/search.py (new tag-search function, exact check): the inventory's trim note covers only the requested side, by binding the Python-stripped value. On the stored side, `trim(j.value, ' \t\r\n')` leaves NBSP, `\v`, `\f`, `\x1c-\x1f`, U+0085, U+1680, U+2000-U+200A, U+2028/9, U+202F, U+205F and U+3000 in place, all of which `str.strip()` removes from the request (`client/backend/server.py:151`, and the Engine's own strip). A stored tag padded with any of them never matches its own chip. The fix is to make the SQL trim set exactly the characters for which `str.isspace()` is true, held in one module constant built in Python and bound as a parameter for both trims. That way the request and the stored tags are trimmed by the same set. Cost: a few lines. Risk if missed: low-frequency, silent false negatives that break the requirement that a single-use tag returns its own video.
client/frontend/src/components/video-card.ts (renderTagChips blank-skip): JS `String.prototype.trim` and Python `str.strip` disagree. JS leaves U+0085 and `\x1c-\x1f`, which Python strips, and strips U+FEFF, which Python leaves. A blank-skip written with JS `trim()` therefore still emits a dead chip for a tag made only of `\x85`, because the gateway strips it to nothing and the Engine answers "Missing query parameter q". The skip test should treat a tag as blank when it contains nothing outside the same whitespace set the Engine trims.
engine/server/README.md (route docs, lines 9 and 53): the file documents `/api/video`'s `tags` and lists search among the NSFW-filtered listings, but nothing says that listing rows now carry `tags` or that `/api/v1/search/videos` takes `tag` (its 400s, `published_at` default, exact `total`, `vectorSearch` false). Cost: a paragraph. Risk: stale docs only.
client/README.md (gateway allowlist, lines 29-34): the per-route allowlist description should mention that `tag` is now accepted on `/api/v1/search/videos`, stripped and dropped when empty like every parameter except `nsfw`, and that tag results get block and like/dislike marks but no over-fetch. Cost: one sentence. Risk: stale docs only.

## 2026-10-06 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

