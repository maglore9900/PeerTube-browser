# Tags on cards and tag search

_Status: DRAFT_

## Requirements

### Source issue

`docs/project/issues/42-tags-on-cards-and-tag-search.md`. It asks for three things: tags on video cards in the feeds, up-next and search; narrowing a feed or search to one or more tags; and an advanced search that takes tag criteria alongside the text query. Its measured catalogue figures (2026-10-02) are not repeated here. Read them from the issue.

### Purpose

Two goals, from the operator (2026-10-04):

- **More of the same:** a visitor who sees the tags on a video they like can use a tag to find more videos like it.
- **Narrower results:** filtering results by a tag gets the visitor more of what they are looking for.

The operator expects issue 42 to need more than one plan. What this plan covers is set under Scope.

### Scope

Set by the operator (2026-10-04):

- **In this plan:** each video card shows the video's tags, and clicking a tag opens search results narrowed to videos carrying that exact tag. This means a new exact-tag filter on the Engine's search route.
- **Cards that show tags:** feed cards, search cards and up-next cards on the video page, so both `renderVideoCard` and `renderSimilarCard` change (operator, 2026-10-04).
- **Tag matching:** two tags are the same when they are equal after trimming and lowercasing ('Linux', ' linux ' and 'LINUX' match each other). Language variants such as 'music' and 'musique' stay distinct, and no variant map is kept (operator, 2026-10-04).
- **Which tags show:** every tag on the video, as the uploader wrote it. There is no use-count cutoff and no stoplist, so clicking a tag used only once returns only the video it came from (operator, 2026-10-04).
- **Tags per card:** as many chips as fit on one line, in the uploader's order, followed by a `+N` marker counting the tags that did not fit. Opening the video shows all of them: the video page already lists every tag (operator, 2026-10-04).
- **Clickable tags:** a tag chip on a feed card, a search card, an up-next card or the video page opens the exact-tag results for that tag (operator, 2026-10-04).
- **Tag results:** a tag click opens the search page with the tag in its URL and no text query. The page names the tag and lists the videos carrying it, newest first. Its existing sort menu switches the order to views or popularity (operator, 2026-10-04).
- **Leaving tag results:** submitting the search box from the tag results runs an ordinary text search and removes the tag from the URL. Text and tag never combine in this plan (operator, 2026-10-04).
- **Storage:** Rt1, the FTS prefilter plus an exact check, with no new table (operator, 2026-10-04; see Routes).
- **Later plans:** a filter control for narrowing any search by tags, filtering in the home feeds (Trending, Recent, Popular, the Recommendations mix) and up-next, and advanced search.
- **Out of scope:** category on cards or as a filter; per-tag counts; fetching tags for the 44,100 videos whose `tags_json` is NULL (the dataset build's tags stage). A NULL-tag video shows no tags and appears in no tag results.

### Acceptance criteria

- **AC1:** every video row the Engine returns from search, every home feed mode and up-next carries `tags`: the video's tags as strings, in the uploader's order. It is `[]` when the stored `tags_json` is NULL, empty, invalid JSON or not a list. The Client gateway passes it through unchanged.
- **AC2:** feed, search and up-next cards show the tags as chips on one line. Tags that do not fit are dropped from the end and counted in a `+N` marker. A card with no tags shows no tag line. Each chip's text is set as text, never as markup, because tags come from remote instances.
- **AC3:** clicking a chip on any card, or on the video page, opens the search page for that tag (`/search?tag=<tag>`) and does not also open the video. Clicking anywhere else on a card behaves as it does today.
- **AC4:** `GET /api/v1/search/videos?tag=<tag>` with no `q` returns the videos whose tag list holds `<tag>` once both are trimmed and lowercased, newest first. `sort=views` and `sort=popularity` reorder them. `sort=relevance` or no sort reads as newest.
- **AC5:** tag results page through every matching video, and `total` is the exact count of matches. Text search stays capped at its 200-candidate pool.
- **AC6:** tag results obey the `nsfw` parameter in the same way as text search (ADR-0007: filtered unless `nsfw=1`). The gateway applies the profile's blocks, dislikes and reaction marks to them, as it does for text search.
- **AC7:** the Engine answers 400 to a request carrying both `q` and `tag`, to a `tag` that is empty after trimming, and to a `tag` longer than 64 characters. The longest stored tag is 30 characters (`tag_lengths.py`).
- **AC8:** the tag results page names the tag, offers newest, views and popularity sorts (relevance is not offered), and keeps `tag` and `sort` in its URL so the back button and links work. Submitting the search box runs an ordinary text search and removes `tag` from the URL.
- **AC9:** a tag with no word character (for example `???` or an emoji) still returns its exact matches.

### Consistency constraints

- Tag chips reuse the video page's chip treatment (`tag-chip`, built with `textContent`), and card markup keeps `renderVideoCard`'s rule that every interpolated value passes through `escapeHtml`.
- The new parameter follows the search route's existing style: the Engine rejects bad input with a 400 and a JSON `error`, and the gateway forwards only allowlisted parameters.
- A new listing path passes `include_nsfw` from the request edge (ADR-0007, Consequences).

### Conflicts

- **A clickable chip inside the card link:** the operator wants chips clickable on every card, but each card is a single `<a>` to the video page, and the existing comment rules out controls inside it. Proposed resolution, for the operator to confirm: put the chips outside the card's link, as the action buttons already are.

### Checked in the tree (2026-10-04)

- Feed and search cards come from one renderer, `renderVideoCard` in `client/frontend/src/components/video-card.ts`, which `pages/videos` and `pages/search` share. The whole card body sits inside one `<a class="video-link">` pointing at the video page. The like, dislike and block buttons sit outside it for that reason ("a button inside an <a> would also navigate"). The channel link is the exception: it is an `<a>` nested inside the card link today.
- Up-next cards on the video page come from a separate renderer, `renderSimilarCard` in `client/frontend/src/pages/video-page/index.ts`. The whole of each card is one `<a class="similar-card-item">`.
- Every row the Engine returns from search, the feeds and up-next is reduced by `stable_video_rows` to `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py:101`). That tuple has no `tags_json` or `category`, although the data-layer queries (`data/search.py`, `data/random_videos.py`, `data/metadata.py`) already select `tags_json`.
- `_handle_search` takes `q`, `sort`, `limit`, `page` and `nsfw`. It has no tag or category parameter.
- The frontend reaches search through the Client gateway at `/api/v1/search/videos`. The gateway forwards only the query parameters listed for that route in `PROXY_ALLOWED_QUERY_PARAMS` (`client/backend/server.py`): `q`, `page`, `limit`, `sort`, `nsfw`. It also applies the profile's blocks, dislikes and reaction marks to search rows (`FILTERED_ROUTES`).
- The search page keeps `q` and `sort` in its URL. Its sorts are `relevance`, `published_at`, `views` and `popularity` (`LEXICAL_SORTS` plus relevance).
- No Engine handler, data-layer query or frontend module filters by tag or category.
- The video page renders tags as text-built chips and category and language as taxonomy items.

### Measured for the storage question (2026-10-04)

These were run read-only against the dev `engine/server/db/whitelist.db` (909,004 videos) with the scripts in `.scratch/tags-on-cards-and-tag-search/`. The cache was warm, and I did not measure cold timings.

- **FTS prefilter plus an exact check** (`tag_match_timing.py`): `videos_fts MATCH 'tags_json : "<tag>"'` narrows the candidates, and a `json_each` comparison after trim and lowercase keeps exact matches only. This took 0.01–0.03 s for `linux` (6,243 videos), `music` (4,525), `pco` (17,464) and `partido da causa operária` (15,630), including newest-first with `LIMIT 24`.
- **Full scan with `json_each`, no prefilter:** 0.71 s for `linux`.
- **The prefilter misses nothing for `linux`** (`fts_miss.py`): every video the full scan finds is in the FTS candidates. The FTS triggers in `sync-whitelist.py` keep `videos_fts.tags_json` current whenever a `videos` row is inserted, updated or deleted, including by the `/api/video` refresh.
- **Tags FTS cannot prefilter:** 24 of 1,731,904 tag uses contain no word character (`???`, `:'(`, emoji). The tokenizer gives them no token.
- **Case folding** (`sqlite_lower_probe.py`): in the Engine's Python environment, SQLite `lower('MÚSICA')` gives `música`, the same as Python. Accented and Cyrillic tags match as FTS tokens.

## Routes

### Rt1: FTS prefilter plus exact check, no new storage (recommended)

A tag request runs the FTS column match on `tags_json` to get candidates, keeps the rows whose tag list holds the tag after trim and lowercase, and orders them by the requested sort. A tag with no word character falls back to the full `json_each` scan under the statement deadline.

- **Evidence:** measured above at 0.01–0.05 s. The existing triggers keep it current.
- **Cost:** one new data-layer query beside `lexical_candidates`, a `tag` parameter on `/api/v1/search/videos` in the Engine and in the gateway allowlist, and the two tag fields added to returned rows.
- **Risk:** it depends on how the FTS tokenizer splits tags, which nothing controls. It gives no per-tag counts, which the later facet and filter plans will probably want.

### Rt2: a normalised `video_tags` table

A `video_tags(tag, video rowid)` table indexed on the tag, filled by the sync stage and a migration, and kept current by triggers like those on `videos_fts`.

- **Evidence:** not prototyped. About 1.7 M rows.
- **Cost:** a whitelist migration, changes to the sync stage and the triggers, and tests on the build path.
- **Risk:** a second derived copy of `tags_json` to keep in step. It is not needed for the speed this plan wants. Its benefit is reuse by later plans (per-tag counts, facets, feed filtering).

### Rt3: `LIKE` over `tags_json` (rejected)

This would match JSON text with escapes in it (`\u00e9`, `\"`) and needs the same full scan as the slowest case of Rt1.

### Rt4: clicking a tag runs `q=<tag>` (rejected by scope)

The operator chose exact-tag results.

## High-level plan

_Not started: waiting for the route to be chosen._
