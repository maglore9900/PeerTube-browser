# Switchable feed modes: recommendations / hot / recent / random / popular

Status: enhancement, complete
Origin: task 8b, [M3][F2] (roadmap feature F3-M3 "feed modes" is the same intent)

## Problem

The home feed offers only recommendations and random; there are no quick modes like only recent, only hot, only popular.

## Proposed solution

Feed modes on the home page and a mode switch.

- UI: mode switcher (recommendations, hot, recent, random, popular).
- API: a `mode` parameter (or separate endpoints); it needs a gateway allowlist entry in `client/backend/server.py`.
- Hot: its own formula (e.g. likes/views with age decay).
- Recent: only fresh items by `published_at`.
- Popular: top by likes/views.
- Random: random feed.

## Related

- After `16-popular-weighted-random`.
- The feed parameter panel plan (`docs/project/plans/archive/04-feed-parameter-panel.md`) adds parameters to the same surface; there must be one feed-parameter mechanism, not two.

## Comments

### Delivered

Delivered by `docs/project/plans/19-17-feed-modes.md`, commit `<pending>`.

- **Hot.** No new formula. Hot is the existing age-decayed popular order: popularity plus the interaction signal capped at `POPULAR_SIGNAL_CAP`, the same `POPULAR_ORDER_BY` the recommendation mix's popular layer uses.
- **Popular.** All-time crawled likes plus interaction `likes_count`, then views, with no age decay and no signal cap.
- **Recent.** Newest `published_at` first, with no time window. Rows whose `published_at` is NULL or in the future are left out.
- **Tie-breaks.** Every order ends on `video_id` then `instance_domain`, so pages never repeat or skip a row. The `instance_domain` key also applies to the mix's popular layer.
- **Gateway.** `mode` was already on the allowlist in `client/backend/server.py`, so no new entry was added.
- **Validation.** An unknown `mode` on an unseeded request answers 400. The check runs before the random branch, so an unseeded `random=1&mode=bogus` answers 400 instead of random.
- **Paging ceiling.** Hot, recent and popular continue past the request's `exclude` list, and the pager sends at most the last 500 shown rows, so these feeds end after about 500 rows.
- **Keyed visitors.** Rows the gateway removes for blocks and dislikes never enter the browser's `exclude`, so in the ordered feeds they come back at the head of every later page. A profile with many such rows near the top of an order gets short pages and an early end.
- **Behaviour.** For the API contract see `engine/server/README.md`. For the orders and their paging see `engine/server/api/recommendations/docs/OVERVIEW.md`. For the switcher see `client/frontend/README.md`.
