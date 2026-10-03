# Make Hot rank by recent growth in source-instance views and likes

Status: enhancement, superceded by 45-trending
Origin: operator request (discussion of how Hot is scored)

## Problem

Hot is not "what is taking off now". It ranks by `videos.popularity` (`engine/server/data/popularity.py`):

```
(views + 2 × likes) / (1 + age_days / 30)
```

- **Totals, not change.** A one-year-old video with 1M views scores about 77,000, while a week-old one with 1,000 views scores about 810. Hot is mostly the largest videos in the catalogue.
- **Frozen age.** `age_days` is measured when the score is written: by `engine/server/db/jobs/recompute-popularity.py` (DATA_BUILD.md §7, "one-time after dataset build"), or for one video when its page is opened (`/api/video`). Between writes, nothing decays.
- **No history.** `videos` holds one current `views`/`likes` value per video, so growth cannot be computed today.

## Proposed solution

- **Snapshots.** Record `(video_id, instance_domain, views, likes, observed_at)` whenever source counts are read. Sources include the crawler, the sync into `whitelist.db`, and `/api/video` refreshes. This could be a new table, pruned past the trending window.
- **Trending score.** Rank by growth over a window, e.g. `Δviews + 2 × Δlikes` over the last N days, optionally normalised by elapsed time. Only PeerTube's counts are used, never this site's likes (see issue 37).
- **Hot feed.** `ORDERED_FEED_ORDER_BY["hot"]` orders by the trending score, with the existing tie-breaks. Videos without two snapshots in the window either fall back to the current order or are left out (Q3).

## Open questions

- Q1. **Refresh coverage.** Growth needs repeated observations of the same videos. How often do the crawler and the dataset build re-read counts for videos already crawled, and for how many of the ~890k? The sync reloads `videos` from `crawl.db` (DATA_BUILD.md:174), which discards `/api/video` refreshes. `merge_rules.json` merges `videos` into prod as `INSERT_ONLY` (DATA_BUILD.md:187), which means prod counts never update. A trending score is only as fresh as this cycle, so it may need its own periodic stats refresh job against source instances (rate limits, instance errors).
- Q2. **Window and formula:** absolute or relative growth, window length, and the like weight.
- Q3. **Cold start:** what Hot shows before enough snapshots exist.
- Q4. **Storage:** snapshot volume at ~890k videos per refresh, and the pruning policy.
- Q5. **Scope:** does the recommendation mix's popular layer switch to trending as well?

## Related

- `37-hot-popular-drop-local-signal`: the smaller step. It removes this site's likes from Hot and Popular, and can land first.
- `17-feed-modes` (archive): the Hot feed and the ordered-feed paging.
- `10-video-metadata-completeness` (archive): the `/api/video` refresh that reads source counts.

## Comments

### Triage (in progress): source-side Hot instead of computed growth

Status stays `enhancement, needs-triage`. No trending or snapshot code exists, and no `docs/project/rejected/` entry or ADR covers this. Issue 37 is delivered.

**Why computing growth here is expensive (checked against the tree):**

- Nothing re-reads counts for videos already in prod. The updater's video crawl runs with `--new-videos --existing-db <prod> --stop-after-full-pages`, and `merge_rules.json` merges `videos` as `INSERT_ONLY`.
- `recompute-popularity.py --incremental` scores only rows whose `popularity` is NULL or 0, so existing rows never decay further.
- The only refresh of an existing video is `/api/video` when its page is opened, and a dataset rebuild overwrites it.
- Growth would therefore need a new count-refresh job. The cheapest form is each instance's `/api/v1/videos?isLocal=true` paged at the maximum `count=100`. That is about 9,000 requests per full refresh of ~900k videos (an estimate, not measured), plus the snapshot table, pruning and scoring the issue describes.

**PeerTube already computes Hot and Trending (probed on live instances, 2026-10-02):**

- `GET /api/v1/videos?sort=-trending` orders by views over the instance's last `trending.videos.intervalDays`, which is 7 on every instance probed. `sort=-hot` orders by an engagement-with-recency algorithm. `/api/v1/config` → `trending.videos.algorithms` lists what each instance enables and its default (`hot` on framatube.org and tilvids.com, `most-viewed` on peertube.tv and video.blender.org). Exactly how `hot` is computed was not checked in PeerTube's source.
- **Neither sort returns a score.** A video object has the same keys under every sort (`views`, `likes`, `comments`, `publishedAt`, and so on). Each instance gives an order, not a number that can be compared across instances.
- `-trending` worked on every version probed, 2.3.0 included. `-hot` worked on 3.2.0 and later. On 2.3.0 it returns 400 "Should have correct sortable column". Of the 1,764 healthy joinpeertube hosts, 1,301 run v8, 267 v7, 83 v6, 51 v5, 35 v4, 20 v3, 6 v2 and 1 v1. So `-hot` is unavailable on at most 27 hosts (v1-v3; not every v3 host was checked), and those would fall back to `-trending`.
- `isLocal=true` restricts the list to the instance's own videos, so each video is ranked only by its origin. `count` is capped at 100. The list hides NSFW videos according to the instance's settings unless `nsfw=both` is passed (not probed).
- Sample `-hot` results are recent: framatube's top items were published within 2026-06, tilvids' and peertube.tv's within the last month. `-trending` on framatube.org is dominated by evergreen videos from 2018-2022 that still draw views every week.
- Cost: one request per host for the top 100, about 1,764 per refresh. That is a fraction of the growth approach, and the responses also carry fresh `views` and `likes` for exactly the videos that matter.

**Decided (operator):** use PeerTube's own Hot/Trending ordering if it is usable. It is, so issue 38's own-snapshot design is replaced by fetching each instance's list. Recorded in ADR-0010, and `CONTEXT.md` defines **Trending**.

- **Sort:** `-trending` alone on every host (views over the instance's last 7 days). `-hot` is not used.
- **Merge:** interleave by rank. Every host's #1 comes first, then every #2, and so on. Ties within a round are broken by the listed video's fresh likes, then views, then `video_id` and `instance_domain` so paging stays stable.
- **Depth and end:** the top 100 per host (one `count=100` page). The feed ends when the ranked rows run out, with no fallback to the old popularity order.
- **Missing videos:** a listed video that is not yet in the catalogue (crawled and embedded) is skipped until the normal crawl adds it. The fetch ingests nothing.
- **Refresh:** a daily updater stage, after the merge and outside the stopped window.
- **Everywhere:** trending replaces Hot. The home feed mode Hot becomes **Trending**, and the Recommendations mix's popular layer draws from the trending-ranked set instead of the popularity order. The Popular mode (all-time likes) is unchanged.
- The issue's Q1-Q4 (refresh coverage, formula, cold start, snapshot storage) no longer apply. Q5 is answered by "everywhere".

**Route: plan, not brief.** The change spans:

- a fetch job and its storage;
- an updater stage with its failure handling;
- the Engine's Hot order and popular layer;
- the frontend feed mode and its URL/`localStorage` value;
- documentation (`OVERVIEW.md`, `LAYER_PARAMS.md`, `UPDATER_WORKER.md`, `DATA_BUILD.md`).

That is more than one agent session. Plan it with `/devsecops:plan` (roadmap F3-M3). Status stays `enhancement, needs-triage` until the plan exists, and the plan closes this issue when it delivers.

**Left for planning:**

- **Where the ranks live:** a table in `whitelist.db` written while the Engine serves, or a separate file handed over the way ADR-0008 does.
- **What a failed or partial fetch does:** keep the previous ranks, or replace them with whatever hosts answered.
- **Which hosts are asked:** presumably the catalogue's hosts minus the Engine's denylist.
- **What a stored `mode=hot` URL or `localStorage` value does after the rename.**
- **Whether `videos.popularity` and `recompute-popularity.py` still have a reader afterwards.**
- **NSFW in the fetched lists:** fetch with `nsfw=both`, so flagged videos are ranked and the Engine's own filter decides. This is not probed.

**Overlap with issue 08:** both change `engine/server/data/random_videos.py` (08 changes its random-cache reads) and the updater's documentation. Plan this now, but start the build after 08 merges, or expect conflicts there.

2026-10-02: planned in docs/project/plans/45-trending-from-source-instances.md.
