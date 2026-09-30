# Rank Hot and Popular on source-instance counts only, without this site's likes

Status: enhancement, complete
Origin: operator request (discussion of how Hot is scored)

## Problem

Hot and Popular are meant to show what is popular on PeerTube. Both also count likes clicked on this site, and those come from the operator's own profile, which already drives Recommendations. `engine/server/data/random_videos.py`:

- `POPULAR_ORDER_BY` (line 15), used by the Hot feed and the recommendation mix's popular layer: `v.popularity + MIN(COALESCE(sig.signal_score, 0), 25)`, then `v.likes + COALESCE(sig.likes_count, 0)`.
- `ORDERED_FEED_ORDER_BY["popular"]` (line 25): `v.likes + COALESCE(sig.likes_count, 0)`.

`sig` is `interaction_signals` (`engine/server/data/interaction_events.py`). The Client backend fills it: +1 per Like, −1 per UndoLike, and +0.25 per Comment, which nothing currently sends (`client/backend/server.py:807-844`). All anonymous likes on one video share a single event id, so together they count once.

## Proposed solution

- Remove the `sig` terms from both orders, so Hot ranks by `v.popularity` then `v.likes`, and Popular by `v.likes` then `v.views`. Keep the `video_id`, `instance_domain` tie-breaks.
- Drop `POPULAR_SIGNAL_CAP` and the `interaction_signals` join from the order queries if nothing else reads them.

## Open questions

- Q1. `POPULAR_ORDER_BY` also feeds the popular layer of the Recommendations mix. Should that layer drop the signal too, or keep it as a personal nudge?
- Q2. The `likes` value returned on rows (`random_videos.py:72` and `:368`) is `v.likes + sig.likes_count`, so cards show PeerTube's likes plus this site's likes. Should cards show PeerTube's count only?
- Q3. Keep `interaction_signals` ingestion as it is? It still feeds whatever else reads it, and issue 38's trending design may or may not use it.

## Related

- `38-hot-trending-by-growth`: replaces Hot's ordering altogether. This issue is the small, independent step.
- `17-feed-modes` (archive): introduced the Hot, Popular and Recent orders.
- Docs to update: `engine/server/api/recommendations/docs/OVERVIEW.md` §1 and §3, and `LAYER_PARAMS.md` (popular layer).

## Comments

### Delivered

Delivered by `docs/project/plans/21-37-hot-popular-drop-local-signal.md`, harvest `docs/project/plans/harvest-37-hot-popular-drop-local-signal-plan.md`. Not yet committed.

- **Q1:** the Recommendations popular layer drops the signal too. It keeps sharing Hot's order (`POPULAR_ORDER_BY`: `popularity`, then crawled likes, views, `published_at`, `video_id`, `instance_domain`).
- **Q2:** every row from `fetch_random_rows`, `fetch_popular_videos` and `fetch_ordered_page` reports the crawled `videos.likes`. The `interaction_signal_score` row key is gone.
- **Q3:** ingestion into `interaction_signals` is unchanged, and nothing reads the table. `POPULAR_SIGNAL_CAP` is removed.
- **ADR-0001:** decision 4 is marked superseded in an amendment section.
- **Running Engine:** it serves the new orders after `bash scripts/run-services.sh restart`.
