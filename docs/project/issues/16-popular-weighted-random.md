# Popular feed: weighted random by similarity

Status: enhancement, needs-triage
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
