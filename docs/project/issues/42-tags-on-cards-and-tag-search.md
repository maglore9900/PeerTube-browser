# Show tags on video cards and filter and search by tag

Status: enhancement, needs-triage
Origin: operator request (discussion of PeerTube tags, 2026-10-02)

## Problem

Tags show only on the video page. Cards in the feeds, up-next and search carry no tags, and there is no way to filter a feed or a search by tag or category. For tags to be worth showing or filtering on, they have to be common enough and mean something, so the request starts from what the catalogue actually holds.

## Proposed solution

- **Cards:** show a video's tags on its card in the feeds, up-next and search results.
- **Filtering:** narrow a feed or search to one or more tags.
- **Advanced search:** search with tag criteria alongside the text query.

## Delivered by plan 54

`docs/project/plans/54-53-tags-on-cards-and-tag.md`, the first plan on this issue. The operator settled Q1, Q2, Q5 and Q6 for it on 2026-10-04.

- **Tags on cards:** every row the Engine serves to search, the feed modes and up-next carries `tags`. Feed, search and up-next cards show every tag as the uploader wrote it, with no cutoff and no stoplist, as one line of chips in the uploader's order with a `+N` marker for the ones that do not fit (Q2, Q6).
- **Clicking a tag:** every chip, on the cards and on the video page, opens `/search.html?tag=<tag>`, the search page's tag mode, which lists the videos carrying that tag, newest first, with views and popularity as the other sorts (Q6).
- **Exact-tag match:** the Engine's search route takes one `tag` in place of `q`. Two tags match when equal after trimming and lowercasing; language variants stay distinct and no variant map is kept (Q1). It runs over `videos_fts` and `tags_json` with no new table (Q5). Tag results follow the NSFW filter, serving moderation and the profile's blocks as text search does.

For the behaviour see `engine/server/README.md` and `client/frontend/README.md`.

## Still open

- Narrowing a search by more than one tag, and a filter control for it.
- Tag filtering in the home feeds (Trending, Recent, Popular, the Recommendations mix) and in up-next (Q4).
- Advanced search: tag criteria alongside a text query. Tag search and text search do not combine.
- Category on cards or as a filter (Q3).
- Per-tag counts.
- Q7 in part: tag results follow the NSFW filter, but the tags of a video are shown whatever they are.
- Q8: missing tags.

## What the catalogue holds (measured 2026-10-02)

Measured over the 897,889 embedded videos in `engine/server/db/whitelist.db` with `.scratch/tags/tag_stats.py` and `.scratch/tags/category_stats.py`.

**Tags** are free text chosen by the uploader, at most 5 per video. The cap comes from PeerTube; 68 videos in the catalogue have 6.

- **Coverage:** 436,467 videos (49%) have at least one tag, and 238,771 have five. 417,322 have an empty list. 44,100 are `NULL` (never fetched; see the memory on the dataset build's tags stage). In the dev dataset the newest 2,000+ videos are `NULL` too, the tags stage's backlog (measured 2026-10-06), so the Recent feed's first pages show no tag chips until that stage catches up.
- **Spread:** 272,394 distinct tags after lowercasing, of which about 184,000 are used once. The 2,092 tags used 100 times or more carry 52% of all tag uses. The 128 tags used 1,000 times or more carry 23%.
- **Noise at the top:**
  - Bulk uploaders: `pco`, `partido da causa operária`, `cotv`, `causa operária tv` (one channel family, ~15k each); `periscope film` and `stock footage` (~10k each); `serialai`, `zrm`.
  - Formats and qualities: `mod`, `xm`, `s3m` (demoscene), `hd`, `4k`, `2k`, `online`.
  - Adult tags: `有碼`, `美乳`, `巨乳`.
- **Topics** a little further down: `linux` 6,247, `music` 4,532, `gaming` 4,014, `debian`, `podcast`, `bitcoin`, `art`, `blender`, `education`, `diy`.
- **Language variants** of one topic are separate tags (`music` / `musique`; `politique`).

**Category** is a fixed list per instance.

- Every video has a value. 'Unknown' accounts for 317,746 (35%), plus 22,400 'Sem Categoria'.
- PeerTube's standard categories hold about 490,000 (55%): Science & Technology 87,518, Education 65,403, Gaming 65,293, Music 64,338, News & Politics 55,963, Entertainment 39,152, and so on.
- The remaining ~7% is several hundred instance-specific categories, such as the French education subjects ('Mathématiques', 'Enseigner') and Georgian film categories.

**Language** is set on 8 videos, so it is not usable as a filter today. Why was not checked.

## Checked in the tree (2026-10-02, before plan 54)

- The video page already renders tags as chips built from text (`client/frontend/src/pages/video-page/index.ts:266-277`).
- Feed and search rows sent to clients carry no tags. `STABLE_VIDEO_FIELDS` (`engine/server/api/handlers/similar.py:122`) has no `tags_json` or `category`.
- The search index already covers tags and category: `videos_fts` indexes `title, description, tags_json, category, channel_name` (`engine/server/db/jobs/sync-whitelist.py:277`). Free-text search already matches tag words, but nothing filters on a tag exactly.

## Open questions

- Q1. **Which tags count:** lowercase and trim only, or merge variants? Set a minimum-use cutoff before a tag can be shown or offered as a filter?
- Q2. **Noise:** hide format/quality tags and bulk-uploader tags (a stoplist), or show tags as they are?
- Q3. **Category as a facet:** offer category filtering as well, perhaps first, given its full coverage? How do 'Unknown' and instance-specific categories appear?
- Q4. **Where filtering applies:** search only, or the ordered home feeds too (Trending, Recent, Popular)? The recommendation mix and up-next?
- Q5. **Storage for exact-tag filtering:** a normalised `video_tags` table with an index, or matching against `tags_json` and `videos_fts`?
- Q6. **Cards:** how many tags fit on a card, and does clicking a tag open a tag search?
- Q7. **NSFW:** adult tags appear in the top 40. Should tags of flagged videos, or a tag list, follow the NSFW filter?
- Q8. **Missing tags:** should the 44,100 never-fetched videos be fetched first? The dataset build's tags stage does not converge on videos with genuinely empty tags.

## Related

- `38-hot-trending-by-growth` (archive) / plan `docs/project/plans/45-trending-from-source-instances.md`: if filtering reaches the ordered feeds, it touches the same `random_videos.py` orders.
- `40-search-card-actions` (archive): search result cards.
- `36-nsfw-filter` (archive): the per-request NSFW filter.
