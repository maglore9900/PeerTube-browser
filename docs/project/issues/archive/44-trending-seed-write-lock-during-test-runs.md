# The active suite's trending seed overwrites the dev DB's real Trending and holds its write lock while other lanes serve

Status: bug, complete
Origin: build 45-trending-from-source-instances (plan `docs/project/plans/46-45-trending-from-source-instances.md`), Step 8

## Problem

**It replaces real Trending data in the DB the operator browses.** The seed ranks each host's catalogue videos by all-time `views` and writes them with `fetched_at = 0`. The long-running dev Engine on :7070 (memory `manual-browser-testing-available`) reads the same `engine/server/db/whitelist.db`. So after any test run, the browser's Trending feed shows each host's most-viewed video of all time: years-old videos at the top, not what is trending. Observed 2026-10-03: all 88,648 rows had `fetched_at = 0`, and the head of the feed was a 7.9-year-old video with 209,803 views, a 20.8-year-old VHS upload and a 2.3-year-old tutorial. The operator then ran a real fill with `fetch-trending.py`. The next test run deletes it again (`DELETE FROM trending_ranks`).

**It holds the write lock for about 4.6 s.**

`tests/active/conftest.py` has a session fixture, `trending_seed`, that the `engine` fixture depends on. In every lane that starts an Engine, it runs `DELETE FROM trending_ranks` and then re-inserts every host's top 100 catalogue videos (`TRENDING_SEED_SQL`) into the shared dev `engine/server/db/whitelist.db`. It runs under the Engine start lock, which only serialises Engine starts. Other lanes' Engines are already serving from the same file.

Measured on 2026-10-03 with a throwaway probe (now in `delete_me/probe_step8_seed_timing.py`):
- `PRAGMA journal_mode` is `delete` (rollback journal, not WAL).
- The seed writes 88,648 rows. The delete takes 0.01 s, the insert 4.40 s and the commit 0.23 s, for a total of 4.64 s holding the write lock.
- The Engine's connections (`engine/server/data/db.py`) use sqlite's default 5 s busy timeout.

In rollback mode, readers are blocked once the writer escalates to EXCLUSIVE. That happens at commit, or earlier if the insert spills the page cache. An Engine read or write that waits past 5 s raises `database is locked`, and the recommendations routes turn that into a 500 `Recommendations request failed`. With the seed taking about 4.6 s on its own, a slower disk or a loaded machine can push it past the limit.

This has not been confirmed as a cause. The one 500 seen in this build's `--compare` (`test_similar.py::test_a_mode_outside_the_ordered_set_answers_the_seed_its_pre_build_spelling_did[recommendations]`, on a lane that took 135 s instead of 48 s) had no retained Engine log. It matches the existing intermittent described in memory `upnext-pin-engine-500-intermittent`, which predates this build. The seed adds a new, regular writer to that same file.

The seed is also rewritten on every lane start even though its content is deterministic, so all but the first rewrite in a run are redundant.

## Proposed solution

The fix must leave a real fill (rows with `fetched_at > 0`) in the shared DB untouched. Options, measuring the lock time before and after:
- Give the session Engine a private copy of the ranks, so the suite never writes `trending_ranks` in the shared file. This fixes both problems.
- Seed only when the table holds no real fetch (no row with `fetched_at > 0`), and otherwise let the tests run on the real ranks. This also fixes both, but `test_similar.py`'s Trending NSFW control (a flagged row in the first 96) then depends on live data, the same weakness that got `mode=recent` retired.
- Skip the rewrite when the table already holds exactly the seed, or seed once per run rather than once per lane. This reduces the lock time only, and still overwrites a real fill.

To confirm the cause, run the suite with `PYTEST_DEBUG_TEMPROOT=<project>/tmp/<dir>` so every lane's `engine.log` survives, then look for `database is locked` tracebacks near a lane's seed time.

## Related

- `tests/active/conftest.py` `trending_seed`, `TRENDING_SEED_SQL`, `ENGINE_START_LOCK`.
- Memory `upnext-pin-engine-500-intermittent`.
- `docs/project/issues/43-updater-trending-launch-failure-skips-similarity.md` (the same build).

## Comments

### Triage (2026-10-03)

Verified against the tree and the dev DB:
- The `trending_seed` session fixture deletes and re-inserts `trending_ranks` in the shared `whitelist.db` without any condition, so the first problem is confirmed from the code path.
- A read-only probe found the operator's real fill in place: 86,826 rows, all with `fetched_at > 0`, and `journal_mode` = `delete`. The next active-suite run will wipe it.
- The lock-time 500 is still unconfirmed, as the report says. Removing the suite's write to the shared file takes away the suspected cause either way.
- Nothing in the tree isolates the test Engine already. `server.py` builds every DB path from the repo root with no override, and `whitelist.db` is about 5.3 GB, so copying it per session is not practical. Worktrees symlink the same file, so a run from a worktree writes main's DB as well.
- No prior rejection exists (`docs/project/rejected/` is absent). ADR-0010 does not cover test data.

Decisions taken with the operator:
- Fix option 1: the test Engine reads private ranks, and the suite never writes `trending_ranks` in the shared file.
- The override is an Engine CLI flag, `--trending-db PATH`, in line with how the fixture already passes `--no-random-cache-refresh`.

No CONTEXT.md or ADR change: this is test isolation, and the Trending definition does not change.

### Delivered

Delivered by `docs/project/plans/47-44-trending-seed-write-lock-during.md`.

- **Engine flag.** `engine/server/api/server.py` accepts `--trending-db PATH`, a dev/test override documented in its `--help`. Before `whitelist.db` is opened, `prepare_trending_override` (`engine/server/data/trending.py`) opens PATH `mode=rw`, applies `ensure_trending_schema` to it, and exits non-zero with a message naming PATH if it is missing or not SQLite. After the schema ensures, `attach_trending_override` ATTACHes PATH on `server.db` as `trending_override` and creates a TEMP view `trending_ranks` that shadows `main.trending_ranks`, so the Trending feed and the popular-layer pool read PATH. The Trending page is still planned as a walk of `idx_trending_ranks_order` with no sort. With the flag set, `ensure_trending_schema` does not run on `whitelist.db`.
- **Active suite.** `trending_seed` builds a per-session file under `tmp_path_factory` with `TRENDING_SEED_SQL`, reading the catalogue from `whitelist.db` attached `mode=ro`, and does not take `ENGINE_START_LOCK`. The `engine` fixture passes that file as `--trending-db`, and `dataset` carries the same view, so references computed on it match what the Engine serves. `shared_trending_before` and `shared_trending_fingerprint` read the shared table's fingerprint read-only.
- **Limitations.**
  - ATTACH on the non-URI `connect_db` connection creates a missing file, so a file removed between `prepare_trending_override` and the attach comes back empty and Trending serves empty pages.
  - PATH is not URI-escaped, so a PATH containing `?` or `#` fails validation.
  - The in-suite fingerprint gate goes red if an updater trending run writes the shared table during the suite; its failure message names that cause.

## Agent Brief

**Category:** bug
**Summary:** Give the active suite's Engine a private `trending_ranks` via a new `--trending-db PATH` flag, so test runs never write the shared dev `whitelist.db`.

**Current behavior:**
The active suite's session fixture `trending_seed` runs before every lane's Engine starts. It runs `DELETE FROM trending_ranks` on the repo's shared dev `whitelist.db` and re-inserts `TRENDING_SEED_SQL`: each host's 100 most-viewed catalogue videos, with `fetched_at = 0`. That database is the one the operator's long-running :7070 Engine serves, so every test run:
- replaces a real Trending fill (rows with `fetched_at > 0`) with all-time most-viewed videos;
- holds the write lock for about 4.6 s (88,648 rows, rollback journal) while other lanes' Engines serve from the same file, against the Engine's 5 s busy timeout.

The Engine has no way to read the ranks from anywhere other than `whitelist.db`. Trending and the Recommendations popular layer read `trending_ranks` in the same SQL as `video_embeddings` and `videos` (the `trending` entry of `ORDERED_FEED_SOURCE`, and the popular-layer pool).

**Desired behavior:**
- The Engine accepts an optional `--trending-db PATH`. When given, every query the Engine runs against `trending_ranks` reads that table from the file at PATH. Everything else (`videos`, `video_embeddings`, moderation and interaction tables) still comes from `whitelist.db`. The Engine never writes the shared file's `trending_ranks` while the flag is set, and that includes startup schema creation.
- Without the flag, behaviour and SQL plans are unchanged. The Trending order should still drive from the ranks index and stop early on an OFFSET walk.
- A missing or unreadable PATH fails the Engine start with a clear error. It does not silently fall back to the shared table.
- The active suite's fixture builds the seed in a per-session temporary SQLite file. It uses the same rows `TRENDING_SEED_SQL` produces today, reading `videos` and `video_embeddings` from the shared DB read-only, and starts the Engine with `--trending-db` pointing at that file. The suite opens no write connection to the shared `whitelist.db` for Trending.
- Existing Trending-dependent tests, including `test_similar`'s Trending NSFW control (a flagged row in the first 96), see the same order they see today.

**Key interfaces:**
- Engine CLI: new optional `--trending-db PATH`, shown in `--help`.
- The `trending_ranks` schema (`ensure_trending_schema`) applies to the private file. The table shape is unchanged.
- `ORDERED_FEED_SOURCE["trending"]` and the popular-layer pool query must resolve `trending_ranks` to the override when it is set. One approach is to ATTACH the file on each Engine connection that runs these queries; SQLite resolves temp objects before main. The agent picks the mechanism, but it has to cover every connection the Engine opens on `whitelist.db`, including the read-only search connection if it serves these queries.
- Active-suite fixtures `trending_seed` and `engine`: the seed target moves from the shared DB to a session temp file. `ENGINE_START_LOCK` is no longer needed for the seed write.

**Acceptance criteria:**
- [x] Starting the Engine with `--trending-db` on a seeded temp file serves Trending in that file's merged-rank order, and the shared `whitelist.db`'s `trending_ranks` (row count, and `fetched_at` min, max and count of rows > 0) is identical before and after.
- [x] Without the flag, Trending serves from `whitelist.db`'s `trending_ranks` as before.
- [x] Starting with `--trending-db` on a path that does not exist exits non-zero with an error naming the path.
- [ ] After a full active-suite run, the shared `whitelist.db`'s `trending_ranks` is unchanged. Test with a real fill present (rows with `fetched_at > 0`). (The in-suite gate covers the session Engine; no read-only fingerprint before and after a full suite run was recorded.)
- [x] The active suite passes, including the Trending and popular-layer tests in `test_similar`, with no test expectations changed.

**Out of scope:**
- Other test writes to the shared `whitelist.db`, such as bridge-mode interaction events from `engine_client`. Raise these separately if needed.
- Confirming or fixing the intermittent up-next 500 (memory `upnext-pin-engine-500-intermittent`) beyond removing this writer.
- Changing the seed's content or ranking, `fetch-trending.py`, the updater's trending stage, or the moderation purge of `trending_ranks`.
- A general override for `whitelist.db` or the other DB paths.
