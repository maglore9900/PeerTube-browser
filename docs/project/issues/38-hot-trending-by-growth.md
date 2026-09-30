# Make Hot rank by recent growth in source-instance views and likes

Status: enhancement, needs-triage
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
