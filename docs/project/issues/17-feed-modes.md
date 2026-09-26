# Switchable feed modes: recommendations / hot / recent / random / popular

Status: enhancement, needs-triage
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
- The feed parameter panel plan (`docs/project/plans/04-feed-parameter-panel.md`) adds parameters to the same surface; there must be one feed-parameter mechanism, not two.

## Comments
