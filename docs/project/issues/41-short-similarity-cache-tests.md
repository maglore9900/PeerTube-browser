# Rewrite the short-similarity-cache tests and the home exclude test

Status: enhancement, needs-triage
Origin: build 35-upnext-tests-retired-by-random-draw (plan `docs/project/plans/20-35-upnext-tests-retired-by-random.md`), step 8

## Problem

Five tests were retired from `tests/active/test_similar.py` to `tests/archive/short_similarity_cache/test_similar.py`, skip-marked, because each one fails on its own control before it reaches the code it checks. Their behaviour is not covered anywhere else in `tests/active`.

- **The short-similarity-cache tests.** Each control expects the shared `engine/server/db/similarity-cache.db` to hold a short entry (at most 20 rows) for the linux and cooking seeds, so that up-next runs the floored ANN fallback. That cache was rebuilt in one `--top-k 1000` run and now holds 542 rows for linux and 260 for cooking, so both up-next routes are served from the cache with `steps=none` and the fallback never runs. The retired tests are:
  - `test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged`: a short-cached seed fills a 48-row and a 30-row page with distinct rows at or above `SIMILAR_VIDEO_TAIL_MIN_SCORE`, and its cache entry is unchanged.
  - `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`: the fallback restores the index's nprobe to `DEFAULT_NPROBE`, so the raw-vector page, search and home are unchanged after it.
  - `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default`: each `upnext_pool` log line records the fallback searches its own request ran and the restored nprobe.
  - `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored`: on an Engine started at nprobe 16, the `upnext_pool` line reports the read-back value, not `DEFAULT_NPROBE`.
- **The home exclude test.** `test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page` is the Engine's only test of `exclude` on a home page; the ordered modes keep theirs in the active file. Its control needs two plain home pages carrying the same five likes to share a row. On the rebuilt cache that overlap is chance: over 14 observed pairs per seed, music's pages shared nothing in 7, and the suite run still drew a linux pair sharing nothing. Home ignores the `seed` parameter, which only the up-next draw reads, so a fixed draw seed cannot pin it.

## Proposed solution

- **Cache tests.** Make the fallback run on purpose instead of relying on whatever the shared cache holds. For example, point the test Engine at a similarity cache of its own with a short entry for the seed, or choose a seed whose entry is short of the page at test time and skip with a reason when none exists.
- **Home exclude test.** Replace the overlap control with one that does not depend on two random home pages meeting, such as checking that the excluded rows are candidates the home page can serve, or excluding a page large enough that the unexcluded request is certain to repeat some of it.

The archived file keeps the original tests and their docstring sections readable as a starting point.

## Related

- `docs/project/issues/35-upnext-tests-retired-by-random-draw.md`, the build whose step 8 retired these tests.

## Comments
