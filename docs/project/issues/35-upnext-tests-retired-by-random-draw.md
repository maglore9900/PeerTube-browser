# Replace the up-next tests retired when up-next became a random draw

Status: enhancement, needs-triage
Origin: build 09-similars-diversity (plan `docs/project/plans/19-09-similars-diversity.md`), step 8 triage

## Problem

Build 09 made every up-next page (`POST /recommendations?id=…&host=…`, `POST /videos/similar`) a random score-weighted draw from the top 4 x limit rows of a pool that the fallback fills past one 48-row batch (phase 2 C1, phase 3 C1). Eight durable tests assumed a plain up-next page repeats, or that a target taken from one unseeded draw reappears on the next. At step 8 they were retired to `tests/archive/upnext_random_draw/` rather than repointed. Plan §7 drafted pinned or seeded rewrites for all of them, but no phase wrote them.

Coverage now missing from `tests/active`:

- **test_similar**: an up-next request excluding a previous page, or every other row of it, returns a full page with none of the excluded rows.
- **test_dislike_profile**: an up-next page carrying a dislike centroid moves away from that video, and home pages carrying it place similar videos lower.
- **test_dislikes**: a disliked video is absent from the profile's full up-next page and present for others, and the profile's up-next page leans away from it.
- **test_blocks**: up-next pages leave out a profile's blocked channel and account while keyless and bystander requests keep them, and an up-next page with blocks is refilled to full from the Client's over-fetch. The search case of the surfaces test is still active.
- **test_frontend_blocks**: a channel blocked through `blocks.ts` leaves the up-next and search rows the frontend modules fetch.
- **test_frontend_videos** (the whole file): the frontend pager never repeats a row and stops asking after an empty batch.

## Proposed solution

Start from plan §7a-§7h: conftest's `upnext_pool` and `pin_upnext` pin a gateway page with `exclude`, and the Engine-direct tests use a fixed `seed`. Two corrections found at step 8 apply:

- **§7c is wrong about the home dislike test.** It says the home test "works with any draw". A probe (`tests/tmp/probe_09_step8_home_pair.py`) saw cooking d1/d2 pairs with no clearly similar (cosine >= 0.6) row on any plain home page, even with `seed=7`, because the cooking pool now reaches down to scores of about 0.5. The pair needs choosing from the pool's head, or by checking home coverage, not from one draw's least similar pair.
- **A stays-full blocks test must make sure the blocked rows would otherwise be served.** A probe saw the three blocked channels absent from the blocker's over-fetched draw in 6 of 12 trials per route, and in those runs the old test passed vacuously. Pinning the page (§7e) fixes this.

Also map `handlers/similar.py` and `data/similarity_candidates.py` to `test_blocks`, `test_dislikes` and `test_frontend_blocks` in `.un/skills/devsecops/config.json` (plan §7i), and drop the `test_frontend_videos.py` entry until a replacement exists.

## Related

- `docs/project/issues/09-similars-diversity.md`, the build that retired them.
- `11-fast-similars-response` and `12-similars-on-scroll` change the same up-next surface, and the pager test matters most for 12.

## Comments
