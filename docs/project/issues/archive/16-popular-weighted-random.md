# Popular feed: weighted random by similarity

Status: enhancement, complete
Origin: task 12a, [M3][F2] (marker was wrong in the old tracker: this is feed work, not API versioning)

## Problem

When likes exist, popular is sorted by similarity, but then a random sample is taken from the whole pool, so the sorting barely affects the result.

## Proposed solution

Replace `random.sample` with weighted random using similarity as the weight.

- After scoring, compute weights (e.g. `max(similarity, 0.0)` or `similarity ** alpha`).
- Pick candidates by weighted sampling without replacement (optionally with a small epsilon for diversity).
- Config parameter `popular.weighted_random_alpha` (0 = disabled).
- Empty/zero weights fall back to plain random.

## Related

- Land before `17-feed-modes`, which exposes popular as a user-facing mode.

## Comments

### Delivered

Delivered by `docs/project/plans/20-16-popular-weighted-random.md`, commit `<pending>`.

- **No epsilon.** The optional diversity term was left out on purpose. With likes, popular videos with zero similarity only fill a shortfall when too few have positive similarity. Variety comes from the random, fresh and explore layers.
- **Key.** The config parameter is `generators.popular.weighted_random_alpha`, set to 1.0 in the `home` and `upnext` profiles. It only has an effect in `home`, because up-next does not run the layers.
- **Behaviour.** For the draw and its fallbacks, see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`, "popular Layer".
