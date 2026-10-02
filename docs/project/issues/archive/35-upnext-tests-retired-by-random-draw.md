# Replace the up-next tests retired when up-next became a random draw

Status: enhancement, complete
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

### Delivered by build 35 (plan `docs/project/plans/20-35-upnext-tests-retired-by-random.md`)

The retired up-next coverage is active again in `tests/active` and passes, with no assertion resting on the unseeded draw.

- **Pinning helpers.** `tests/active/conftest.py` holds `exclude_entries`, `upnext_pool` and `pin_upnext`. `upnext_pool` lists a seed's whole pool on the Engine with seeded 96-row requests and caches it per process, sorted by debug `similarity_score`, so "the pool's first n" means the n highest-scoring rows. `pin_upnext` returns the `exclude` entries that leave exactly the chosen rows, checked on the Engine on the helpers' own rate bucket (`X-Client-IP` 192.0.2.150). Both raise an `AssertionError` naming what they could not do and never return a partial pin.
- **Seed or pin.** The Engine-direct tests (test_similar, test_dislike_profile) use a fixed draw `seed`. The Client tests (test_dislikes, test_blocks, test_frontend_blocks) pin with `exclude`, because the Client does not forward `seed`.
- **Restored tests.**
  - test_similar: an up-next page excluding a previous page, or every other row of it, is a full page of other pool rows.
  - test_dislike_profile: the up-next centroid test and the home centroid test.
  - test_dislikes: the absent-and-present test and the lean-away test, on both routes.
  - test_blocks: the surfaces test on both up-next routes as well as search, and the stays-full test.
  - test_frontend_blocks: the module block test, its node runner taking the pin through the `EXCLUDE` environment variable.
- **The home dislike test compares means.** It asserts mean shaped position > mean plain position and mean d1 lean > mean d2 lean, rather than plan §7c's min/max form, which flaked on unseeded home pages; the operator chose means.
- **The home test's pair is chosen by coverage**, as the first correction above asks: the least similar pair (cosine < 0.7) on the seeded up-next page whose members each have a clearly similar row on every plain home page, asserted as a control before the comparison.
- **The stays-full test is pinned**, as the second correction asks, to the pool's first 11 rows, with a control that the keyless page is exactly those 11 before the blocks remove three channels.
- **Selector mappings.** `.un/skills/devsecops/config.json` maps `engine/server/api/handlers/similar.py` and `engine/server/data/similarity_candidates.py` to test_blocks, test_dislikes and test_frontend_blocks, and `engine/server/data/ann.py` and `engine/server/data/similarity_candidates.py` to test_dislike_profile.
- **No `test_frontend_videos.py` entry to drop.** None existed; the pager coverage this issue lists is `tests/active/test_frontend_upnext_pager.py`, from build 12.
- **Archive removed.** The six files of `tests/archive/upnext_random_draw/` went to `delete_me/`, and the directory is gone.
- **Tests retired at this build's step 8.** By the operator's decision, the short-similarity-cache up-next tests and `test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page` left `tests/active/test_similar.py` for `tests/archive/short_similarity_cache/test_similar.py`. Issue 41 (`docs/project/issues/41-short-similarity-cache-tests.md`) tracks their rewrite.

### Triage (2026-10-02): verified delivered; closed as complete

The delivery comment above was checked against the tree:

- `tests/active/conftest.py` defines `exclude_entries`, `upnext_pool` and `pin_upnext`.
- `test_similar`, `test_blocks`, `test_dislikes` and `test_frontend_blocks` use the pinning helpers. `test_dislike_profile` uses a fixed `seed`.
- `tests/archive/upnext_random_draw/` is gone, and `tests/active/test_frontend_upnext_pager.py` exists.
- The build's plan is archived at `docs/project/plans/archive/20-35-upnext-tests-retired-by-random.md`.

**One delivered item is no longer on disk: the selector mappings.** `.un/skills/devsecops/config.json` holds no Engine or Client entries at all. On 2026-10-02 at 07:13 it was rewritten as un's own config: `project_dir` is `unstable_number_dev`, and its `test_groups` list un's tests (test_cli_a, test_repl_a, ...), none of which exist in this repo's `tests/active`. This loss affects every active test's mapping, not just this issue's, so it is not grounds to reopen 35. Restoring this repo's `test_groups` is separate work.
