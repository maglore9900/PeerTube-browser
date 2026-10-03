# ADR-0010: Trending is each source instance's own ranking, merged by rank

Status: accepted
Date: decided while triaging issue 38 (Hot by recent growth), `docs/project/issues/38-hot-trending-by-growth.md`
Related: ADR-0008 (similarity cache handoff), issue 37 (Hot without this site's likes)

## Context

Hot ranks by `videos.popularity`, an age-decayed total of crawled views and likes. It mostly surfaces the largest videos in the catalogue, not what is taking off now. Issue 38 proposed computing growth from count snapshots. Nothing in the pipeline re-reads counts for videos already in prod:

- The updater crawls only new videos.
- The updater merges `videos` as `INSERT_ONLY`.
- `recompute-popularity.py --incremental` scores only unscored rows.

Snapshots would need a new full count-refresh job (about 9,000 paged requests per refresh), a snapshot table, pruning and a scoring formula.

Every PeerTube instance already ranks its own videos. A probe of live instances on 2026-10-02 found:

- `GET /api/v1/videos?sort=-trending&isLocal=true&count=100` orders an instance's videos by views over its last `trending.videos.intervalDays` (7 on every instance probed).
- It works on every version probed, 2.3.0 through 8.3.1.
- The response carries no score, only the order.

## Decision

1. **Trending is fetched, not computed.** Once a day, a stage of the updater asks each catalogue host for its top 100 videos under `sort=-trending&isLocal=true`, about 1,764 requests. The stage runs after the merge, outside the stopped window. `-hot` and the instance's configured default algorithm are not used.
2. **Lists are merged by rank.** The global order is every host's #1, then every #2, and so on. Within a round, ties break on the listed video's likes, then views, then `video_id` and `instance_domain`. Small instances get the same exposure per round as large ones.
3. **The order is finite.** It holds only ranked videos that are in the catalogue (crawled and embedded), and the feed ends when they run out. Listed videos not yet in the catalogue are skipped until the normal crawl adds them. The fetch ingests nothing.
4. **Trending replaces Hot everywhere.** The home feed mode Hot becomes Trending, and the Recommendations mix's popular layer draws from the trending-ranked set. The Popular mode (all-time likes) is unchanged.

## Alternatives rejected

- **Growth from our own snapshots** (issue 38 as written): a new full count-refresh job and snapshot storage, to reproduce what each instance already computes from its own view records.
- **`-hot` with a `-trending` fallback:**
  - `-hot` is missing before PeerTube 3.2.
  - Its algorithm was not checked.
  - The operator preferred one behaviour on every host.
- **Each instance's configured default:** this mixes hot and most-viewed lists in one feed.
- **Ordering the union of lists by fresh counts, or weighting rank by instance size:** large instances would dominate the top. The operator chose equal exposure per rank.
- **Falling back to the popularity order after the ranked rows:** Trending would quietly turn back into the old Hot.

## Consequences

- Trending is as fresh as the last updater run, at most a day old on top of the instances' own 7-day windows.
- A 25-view #1 on a small instance sits in the first round beside a 400-view #1 on a large one. This is intended.
- Trending depends on source instances answering. Planning decides what a failed or partial fetch keeps.
- `videos.popularity` and `recompute-popularity.py` may lose their last reader. Planning decides whether they go.
