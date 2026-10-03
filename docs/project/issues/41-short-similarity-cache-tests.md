# Rewrite the short-similarity-cache tests and the home exclude test

Status: enhancement, ready
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

Triage (2026-10-03): `enhancement, ready`. Not already covered: the active `test_similar.py` has no `ann_fallback`, nprobe-restore or home-exclude test. Up-next and ordered-mode exclude keep their tests there, and `test_server.py` checks only the Client's 500-entry exclude cap. A `_short_cached_seeds` helper that a worktree-19 fix is recorded as adding is not in the repo, so that fix never reached main. No prior rejection (`docs/project/rejected/` does not exist). The cause matches the archived module's docstring. Measured at triage with a throwaway read-only script (`delete_me/cache_entry_sizes_issue41.py`): the cache holds 890,052 sources from one `computed_at`, averaging 355 rows (max 1000). By entry size: 8 empty, 471 with 1-9 rows, 3,854 with 10-29, 7,679 with 30-47, and 878,040 with 48 or more. The lowest-keyed 10-29-row sources (key 629 on) hold 29 rows. A full scan of the 3.4 GB file took about 60 s. The Engine opens `similarity-cache.db` at a path fixed relative to the repo root, with no flag or env var to change it.

Decided with the maintainer:
- The fallback tests pick short-cached seeds from the shared cache at run time (read-only) and skip with a reason when none qualifies. No private cache and no Engine path option.
- The home exclude test excludes the union of 5 plain home pages. Its control is that a 6th plain page shares a row with that union. Its row floor is set from measured draws, not carried over from 45.

## Agent Brief

**Category:** enhancement
**Summary:** Bring back the four up-next ANN-fallback tests and the home `exclude` test retired to the short-similarity-cache test archive, with controls that do not depend on what the shared cache or a random home draw happens to hold

**Current behavior:**
Five tests sit skip-marked in the short-similarity-cache folder of the test archive, a copy of the old `test_similar.py` tests with the original module-docstring sections. Each fails on its own control before it reaches the code under test:
- The four fallback tests search "linux" / "cooking" for their seed and expect its similarity-cache entry to be shorter than a page, so that up-next runs the floored ANN fallback (`[similar-server] ann_fallback` lines, an nprobe raise then restore). Since the cache was rebuilt with `--top-k 1000`, those seeds' entries hold hundreds of rows, up-next is served from the cache with `steps=none`, and the fallback never runs.
- The home exclude test expects two plain home pages with the same five likes to share a row. On the rebuilt cache that is chance (no shared row in 7 of 14 observed music pairs). `seed` does not affect home, so it cannot pin the draw.

Nothing in the active suite covers the fallback, the nprobe restore after it, the `upnext_pool` line's `steps` / `restored_nprobe` fields, or `exclude` on a home page.

**Desired behavior:**
The five tests are back in the active `test_similar.py`, asserting what their archived docstring sections state, with these changed controls:

*Seed selection (all four fallback tests):* a helper reads the Engine's similarity cache read-only (the cache is shared with main; never write it) and returns seeds whose source entry holds fewer rows than the page the test requests. The fill test needs fewer than its 30-row short page, so choose entries of roughly 10-29 rows. Each seed must be servable by up-next: present in the dataset with a `video_uuid`, not NSFW-flagged, not on a denylisted host or blocked channel. The fill test is parametrised over two distinct such seeds, replacing linux and cooking. The pool-line and off-default tests use one. When no qualifying seed exists, the test calls `pytest.skip` with a reason naming the cache and the row range. Selection is deterministic for a given cache (for example, ordered by key), so a red can be re-run on the same seed. Keep it cheap: walk `similarity_sources` in key order and stop at the first qualifying seeds (3,854 entries hold 10-29 rows; the first appears at key 629) instead of scanning or aggregating the whole 890k-row, 3.4 GB table, which took about 60 s at triage. Select once per module.

*The four fallback tests, otherwise as archived:*
- A short-cached seed fills a 48-row and a 30-row up-next page with distinct rows at or above `SIMILAR_VIDEO_TAIL_MIN_SCORE`, and its cache entry (source row with `computed_at`, plus neighbours) is identical before and after.
- After a fallback, every `ann_fallback` line reports `restored_nprobe` equal to `DEFAULT_NPROBE` (also the startup `ann_nprobe_configured` value), each at an nprobe on the ladder above it. The music raw-vector page at limit 96 with `nsfw=1`, the `q=music&limit=20` search, and home's shape (`BATCH_SIZE` rows, mode `home`, not random) are unchanged. A child search of the index reproduces the raw-vector page at `DEFAULT_NPROBE` and differs at 1 and at every ladder value.
- One request on each up-next route (`POST /recommendations`, `POST /videos/similar`) writes one `upnext_pool` line whose `steps` are exactly the `ann_fallback` searches its own request ran, and whose `restored_nprobe` equals the last search's read-back. Every pool line in the session log meets the same rule.
- On a second Engine started at nprobe 16 through the archived runpy launcher (real `server.py`, `DEFAULT_NPROBE` left shipped), both routes' pool lines report `restored_nprobe=16`, the read-back, not `DEFAULT_NPROBE`.

*Home exclude test:* for each of the linux, cooking and music like sets (five search hits each), draw 5 plain home pages with those likes and take the union of their `(video_id, instance_domain)` keys (at most 240 entries, under the 500-entry cap). Control: a 6th plain page shares at least one key with the union, so a request ignoring `exclude` would repeat some of it. Then a home request with those likes and the union as `exclude` returns mode `home` (not random), none of the union's keys, and at least a floor of rows. **Measure before setting the floor:** run the excluded request repeatedly per like set (at least 20 draws each) and set the floor at or below the fewest rows observed, recording the observed range in a comment next to the constant. Do not carry 45 over unchecked. If the excluded page comes back random or near-empty, stop and report rather than lowering the floor to fit.

**Key interfaces:**
- `similarity_cache.fetch_cached_similarities()` and the cache's `similarity_sources` / `video_keys` tables, read through a `mode=ro` connection
- `server_config`: `SIMILAR_VIDEO_TAIL_MIN_SCORE`, `DEFAULT_NPROBE`, `SIMILAR_VIDEO_NPROBE`, `SIMILAR_VIDEO_MAX_NPROBE`, `BATCH_SIZE`, `DEFAULT_SIMILARITY_DB_PATH`
- Engine log lines: `[similar-server] ann_fallback` (`nprobe`, `search_limit`, `restored_nprobe`), `upnext_pool` (`steps`, `restored_nprobe`), `ann_nprobe_configured=`
- `POST /recommendations` home body `{"likes": [...], "exclude": [{"id", "host"}...]}`; response `seed.mode` / `seed.random`
- The active suite's `engine` / `dataset` fixtures, the Engine start lock, and the helpers the archived module lists as dependencies

**Acceptance criteria:**
- [ ] The five tests (the fill test with two seed params, the home exclude test with three like sets) run unskipped in the active `test_similar.py` against the current shared cache, and pass.
- [ ] No fallback test chooses its seed by search query. Each reads it from the cache at run time and skips with a reason when none qualifies.
- [ ] With a fake cache that has no qualifying entry (or with the helper's row range made impossible), the fallback tests report skipped, not failed.
- [ ] The home exclude test's control uses the 5-page union, and its floor constant carries a comment giving the measured range it was set from.
- [ ] Each restored test fails when its property is broken. Mutation examples: skipping the nprobe restore in the fallback fails the restore and pool-line tests; recording a fixed `restored_nprobe` fails the off-default test; ignoring home `exclude` fails the home exclude test.
- [ ] `test_similar.py` passes in full in its own lane, run three times. Engine-backed files stay in their own lanes because of the 60/min rate limit.
- [ ] The active module docstring describes the restored tests; the archived module is left as is.

**Out of scope:**
- Any Engine code change, including a similarity-cache path option or changes to the fallback or nprobe handling.
- Writing to or rebuilding the shared `similarity-cache.db`.
- The up-next exclude, ordered-mode exclude and Client exclude-cap tests already active.
- The known intermittents in `test_similar` (home 48-row count, nsfw random control).
