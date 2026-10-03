# Build record - 44-trending-seed-write-lock-during

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/47-44-trending-seed-write-lock-during.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# The active suite's trending seed overwrites the dev DB's real Trending and holds its write lock while other lanes serve\n\nStatus: bug, ready-for-agent\nOrigin: build 45-trending-from-source-instances (plan `docs/project/plans/46-45-trending-from-source-instances.md`), Step 8\n\n## Problem\n\n**It replaces real Trending data in the DB the operator browses.** The seed ranks each host's catalogue videos by all-time `views` and writes them with `fetched_at = 0`. The long-running dev Engine on :7070 (memory `manual-browser-testing-available`) reads the same `engine/server/db/whitelist.db`. So after any test run, the browser's Trending feed shows each host's most-viewed video of all time: years-old videos at the top, not what is trending. Observed 2026-10-03: all 88,648 rows had `fetched_at = 0`, and the head of the feed was a 7.9-year-old video with 209,803 views, a 20.8-year-old VHS upload and a 2.3-year-old tutorial. The operator then ran a real fill with `fetch-trending.py`. The next test run deletes it again (`DELETE FROM trending_ranks`).\n\n**It holds the write lock for about 4.6 s.**\n\n`tests/active/conftest.py` has a session fixture, `trending_seed`, that the `engine` fixture depends on. In every lane that starts an Engine, it runs `DELETE FROM trending_ranks` and then re-inserts every host's top 100 catalogue videos (`TRENDING_SEED_SQL`) into the shared dev `engine/server/db/whitelist.db`. It runs under the Engine start lock, which only serialises Engine starts. Other lanes' Engines are already serving from the same file.\n\nMeasured on 2026-10-03 with a throwaway probe (now in `delete_me/probe_step8_seed_timing.py`):\n- `PRAGMA journal_mode` is `delete` (rollback journal, not WAL).\n- The seed writes 88,648 rows. The delete takes 0.01 s, the insert 4.40 s and the commit 0.23 s, for a total of 4.64 s holding the write lock.\n- The Engine's connections (`engine/server/data/db.py`) use sqlite's default 5 s busy timeout.\n\nIn rollback mode, readers are blocked once the writer escalates to EXCLUSIVE. That happens at commit, or earlier if the insert spills the page cache. An Engine read or write that waits past 5 s raises `database is locked`, and the recommendations routes turn that into a 500 `Recommendations request failed`. With the seed taking about 4.6 s on its own, a slower disk or a loaded machine can push it past the limit.\n\nThis has not been confirmed as a cause. The one 500 seen in this build's `--compare` (`test_similar.py::test_a_mode_outside_the_ordered_set_answers_the_seed_its_pre_build_spelling_did[recommendations]`, on a lane that took 135 s instead of 48 s) had no retained Engine log. It matches the existing intermittent described in memory `upnext-pin-engine-500-intermittent`, which predates this build. The seed adds a new, regular writer to that same file.\n\nThe seed is also rewritten on every lane start even though its content is deterministic, so all but the first rewrite in a run are redundant.\n\n## Proposed solution\n\nThe fix must leave a real fill (rows with `fetched_at > 0`) in the shared DB untouched. Options, measuring the lock time before and after:\n- Give the session Engine a private copy of the ranks, so the suite never writes `trending_ranks` in the shared file. This fixes both problems.\n- Seed only when the table holds no real fetch (no row with `fetched_at > 0`), and otherwise let the tests run on the real ranks. This also fixes both, but `test_similar.py`'s Trending NSFW control (a flagged row in the first 96) then depends on live data, the same weakness that got `mode=recent` retired.\n- Skip the rewrite when the table already holds exactly the seed, or seed once per run rather than once per lane. This reduces the lock time only, and still overwrites a real fill.\n\nTo confirm the cause, run the suite with `PYTEST_DEBUG_TEMPROOT=<project>/tmp/<dir>` so every lane's `engine.log` survives, then look for `database is locked` tracebacks near a lane's seed time.\n\n## Related\n\n- `tests/active/conftest.py` `trending_seed`, `TRENDING_SEED_SQL`, `ENGINE_START_LOCK`.\n- Memory `upnext-pin-engine-500-intermittent`.\n- `docs/project/issues/43-updater-trending-launch-failure-skips-similarity.md` (the same build).\n\n## Comments\n\n### Triage (2026-10-03)\n\nVerified against the tree and the dev DB:\n- The `trending_seed` session fixture deletes and re-inserts `trending_ranks` in the shared `whitelist.db` without any condition, so the first problem is confirmed from the code path.\n- A read-only probe found the operator's real fill in place: 86,826 rows, all with `fetched_at > 0`, and `journal_mode` = `delete`. The next active-suite run will wipe it.\n- The lock-time 500 is still unconfirmed, as the report says. Removing the suite's write to the shared file takes away the suspected cause either way.\n- Nothing in the tree isolates the test Engine already. `server.py` builds every DB path from the repo root with no override, and `whitelist.db` is about 5.3 GB, so copying it per session is not practical. Worktrees symlink the same file, so a run from a worktree writes main's DB as well.\n- No prior rejection exists (`docs/project/rejected/` is absent). ADR-0010 does not cover test data.\n\nDecisions taken with the operator:\n- Fix option 1: the test Engine reads private ranks, and the suite never writes `trending_ranks` in the shared file.\n- The override is an Engine CLI flag, `--trending-db PATH`, in line with how the fixture already passes `--no-random-cache-refresh`.\n\nNo CONTEXT.md or ADR change: this is test isolation, and the Trending definition does not change.\n\n## Agent Brief\n\n**Category:** bug\n**Summary:** Give the active suite's Engine a private `trending_ranks` via a new `--trending-db PATH` flag, so test runs never write the shared dev `whitelist.db`.\n\n**Current behavior:**\nThe active suite's session fixture `trending_seed` runs before every lane's Engine starts. It runs `DELETE FROM trending_ranks` on the repo's shared dev `whitelist.db` and re-inserts `TRENDING_SEED_SQL`: each host's 100 most-viewed catalogue videos, with `fetched_at = 0`. That database is the one the operator's long-running :7070 Engine serves, so every test run:\n- replaces a real Trending fill (rows with `fetched_at > 0`) with all-time most-viewed videos;\n- holds the write lock for about 4.6 s (88,648 rows, rollback journal) while other lanes' Engines serve from the same file, against the Engine's 5 s busy timeout.\n\nThe Engine has no way to read the ranks from anywhere other than `whitelist.db`. Trending and the Recommendations popular layer read `trending_ranks` in the same SQL as `video_embeddings` and `videos` (the `trending` entry of `ORDERED_FEED_SOURCE`, and the popular-layer pool).\n\n**Desired behavior:**\n- The Engine accepts an optional `--trending-db PATH`. When given, every query the Engine runs against `trending_ranks` reads that table from the file at PATH. Everything else (`videos`, `video_embeddings`, moderation and interaction tables) still comes from `whitelist.db`. The Engine never writes the shared file's `trending_ranks` while the flag is set, and that includes startup schema creation.\n- Without the flag, behaviour and SQL plans are unchanged. The Trending order should still drive from the ranks index and stop early on an OFFSET walk.\n- A missing or unreadable PATH fails the Engine start with a clear error. It does not silently fall back to the shared table.\n- The active suite's fixture builds the seed in a per-session temporary SQLite file. It uses the same rows `TRENDING_SEED_SQL` produces today, reading `videos` and `video_embeddings` from the shared DB read-only, and starts the Engine with `--trending-db` pointing at that file. The suite opens no write connection to the shared `whitelist.db` for Trending.\n- Existing Trending-dependent tests, including `test_similar`'s Trending NSFW control (a flagged row in the first 96), see the same order they see today.\n\n**Key interfaces:**\n- Engine CLI: new optional `--trending-db PATH`, shown in `--help`.\n- The `trending_ranks` schema (`ensure_trending_schema`) applies to the private file. The table shape is unchanged.\n- `ORDERED_FEED_SOURCE[\"trending\"]` and the popular-layer pool query must resolve `trending_ranks` to the override when it is set. One approach is to ATTACH the file on each Engine connection that runs these queries; SQLite resolves temp objects before main. The agent picks the mechanism, but it has to cover every connection the Engine opens on `whitelist.db`, including the read-only search connection if it serves these queries.\n- Active-suite fixtures `trending_seed` and `engine`: the seed target moves from the shared DB to a session temp file. `ENGINE_START_LOCK` is no longer needed for the seed write.\n\n**Acceptance criteria:**\n- [ ] Starting the Engine with `--trending-db` on a seeded temp file serves Trending in that file's merged-rank order, and the shared `whitelist.db`'s `trending_ranks` (row count, and `fetched_at` min, max and count of rows > 0) is identical before and after.\n- [ ] Without the flag, Trending serves from `whitelist.db`'s `trending_ranks` as before.\n- [ ] Starting with `--trending-db` on a path that does not exist exits non-zero with an error naming the path.\n- [ ] After a full active-suite run, the shared `whitelist.db`'s `trending_ranks` is unchanged. Test with a real fill present (rows with `fetched_at > 0`).\n- [ ] The active suite passes, including the Trending and popular-layer tests in `test_similar`, with no test expectations changed.\n\n**Out of scope:**\n- Other test writes to the shared `whitelist.db`, such as bridge-mode interaction events from `engine_client`. Raise these separately if needed.\n- Confirming or fixing the intermittent up-next 500 (memory `upnext-pin-engine-500-intermittent`) beyond removing this writer.\n- Changing the seed's content or ranking, `fetch-trending.py`, the updater's trending stage, or the moderation purge of `trending_ranks`.\n- A general override for `whitelist.db` or the other DB paths.",
  "request_source": "read from docs/project/issues/44-trending-seed-write-lock-during-test-runs.md",
  "slug": "44-trending-seed-write-lock-during",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "10": "done",
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Trending override helpers",
      "checkpoint": "Seam: the public functions in `engine/server/data/random_videos.py` (`fetch_ordered_page`, `fetch_popular_videos`) plus `attach_trending_override` and `prepare_trending_override` from `data.trending`. The test calls them in-process, on temp SQLite files (rung 1). It follows the existing harness in `tests/active/test_random_videos.py`: `_schema`, `_ranks_db`, `_plan`, and `test_a_trending_page_walks_the_ranks_index_without_sorting`. Two tests. (a) `test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`: main holds ranks A (`TRENDING_EXPECTED`) and the private file holds the same keys with ranks B, a hand-derived different order (e.g. reversed). A plain connection must serve A from both `fetch_ordered_page(..., \"trending\", ...)` and `fetch_popular_videos`. A second connection on the same main, prepared with `attach_trending_override`, must serve B from both. After both reads, `main.trending_ranks` rows must equal what was written. Control: assert A != B. (b) `test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`: main gets the 30\u00d7100 ranked catalogue plus 1,000 unranked rows, built by a builder factored out of the existing plan test, and its `main.trending_ranks` is left empty. The private file gets `prepare_trending_override` and then the ranks. On the prepared connection, `_plan(conn, \"trending\")` must contain `idx_trending_ranks_order` and no `TEMP B-TREE`. Control: `_plan(conn, \"popular\")` contains `TEMP B-TREE`. The existing unflagged plan test stays as it is.",
      "intent": "`engine/server/data/trending.py` gains `TRENDING_OVERRIDE_SCHEMA`, `prepare_trending_override` and `attach_trending_override`. A connection prepared by `attach_trending_override` takes every unqualified `trending_ranks` read from the attached file, not from main, and its Trending page is still planned as a walk of `idx_trending_ranks_order` with no sort.",
      "clauses": [
        {
          "id": "C1",
          "text": "On a connection prepared by `attach_trending_override`, `fetch_ordered_page` for `trending` and `fetch_popular_videos` serve the attached file's ranks. On an unprepared connection to the same main they serve main's ranks, and main's ranks are left unchanged."
        },
        {
          "id": "C2",
          "text": "On a connection prepared by `attach_trending_override`, the Trending page's query plan uses `idx_trending_ranks_order` and contains no `TEMP B-TREE`."
        }
      ],
      "files": [
        "engine/server/data/trending.py (EDITED)",
        "tests/active/test_random_videos.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/data/trending.py`\n`ensure_trending_schema` is unchanged. Three additions sit next to it, following the plan's draft:\n- `TRENDING_OVERRIDE_SCHEMA = \"trending_override\"`: the schema name the override file is attached under.\n- `prepare_trending_override(path)`: opens `file:{path}?mode=rw` with `uri=True`, so a missing file is never created, runs `ensure_trending_schema` on it, and closes the connection. Any `sqlite3.Error` becomes `SystemExit` with a message that names the path. A `rat-tail:` comment records the limit: the path is not URI-escaped, so a `?` or `#` in it fails here, and the fix is `urllib.parse.quote`.\n- `attach_trending_override(conn, path)`: runs `ATTACH DATABASE ? AS trending_override` with the path as a bound parameter, then `CREATE TEMP VIEW trending_ranks AS SELECT * FROM trending_override.trending_ranks`. One comment explains why the view is needed: SQLite looks up names in temp, then main, then attached databases, and it flattens the view. A `rat-tail:` comment records the race: on a non-URI connection, ATTACH would recreate a file deleted after the prepare step as an empty file.\n\nWhat I saw in a probe (pytest's sqlite 3.53.4, the same version as the Engine's): with the override attached, the Trending query's plan is `SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order` followed by `SEARCH e USING COVERING INDEX ...`, with no `TEMP B-TREE`. `prepare_trending_override` on a missing path raised `SystemExit` naming the path and left no file there.\n\n### `tests/active/test_random_videos.py`\nNot edited. The checkpoint uses the harness (`_schema`, `_ranks_db`, `_plan`, `RANKS`, `TRENDING_EXPECTED`) exactly as it stands. Moving the checkpoint's two tests and docstring bullets into this file is test-side work, not production code.",
      "beyond": "tests/tmp/probe_override_plan.py: a throwaway probe I wrote to check the query plan and the missing-path behaviour before handing in. My tools cannot delete files, so the operator needs to remove it. It fails on purpose with `assert False` so its printed output is shown, and it is not part of the build.\ntests/last_test_output.txt and tests/last_test_validation.json: running that probe through `ValidateTests` overwrote both files with the probe's output. The workflow's checkpoint run will overwrite them again."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Engine --trending-db flag",
      "checkpoint": "Seam: the real Engine entry point `engine/server/api/server.py`, run as a subprocess under the Engine interpreter (rung 2) through `test_server_config._run`. This follows `test_server_config.py`'s existing entry-point tests (e.g. `test_server_py_exits_before_argument_parsing_on_a_bad_value`). There is no start lock, because the start must fail before `connect_db`. Test `test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`. Missing case, `tmp_path / \"absent.db\"`: assert `returncode != 0`, assert `str(missing)` is in stderr, and assert `not missing.exists()`. Non-SQLite case, `tmp_path / \"junk.db\"` holding 4 KB of non-SQLite bytes: assert `returncode != 0`, assert the path is in stderr, and assert the file's bytes are unchanged. The timeout is bounded, so a start that wrongly proceeds to load FAISS or bind goes red, not hung. Control: `server.py --help` exits 0 and its stdout contains `--trending-db PATH`. The `tests/config.json` `test_server_config.py` group gains `engine/server/data/trending.py`.",
      "intent": "`engine/server/api/server.py` accepts `--trending-db PATH`. `main()` validates PATH before it opens `whitelist.db`, so a PATH that is not an existing SQLite file stops the start, with a message naming it, and leaves the path as it was.",
      "clauses": [
        {
          "id": "C1",
          "text": "Starting `server.py` with `--trending-db` on a missing path or a non-SQLite file exits non-zero, with that path in stderr."
        },
        {
          "id": "C2",
          "text": "The failed start leaves the path as it was: a missing path is not created, and a non-SQLite file's bytes are unchanged."
        }
      ],
      "files": [
        "engine/server/api/server.py (EDITED)",
        "tests/active/test_server_config.py (EDITED)",
        "tests/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/api/server.py`\n- The import from `data.trending` now also brings in `attach_trending_override` and `prepare_trending_override`. Phase 1 added both to `trending.py`, so they are reused here as they are.\n- `parse_args` gains `--trending-db` with `metavar=\"PATH\"` and `default=None`, written in the file's `help=(...)` style. It sits after the `refresh_group` block and before `set_defaults`. The help text says four things: it is a dev/test override; only `trending_ranks` is read from PATH; PATH must be an existing SQLite file (an empty file counts) and is never created, though the table and index are created in it if missing; a relative PATH resolves against the working directory.\n- In `main()`, when the flag is set, `prepare_trending_override(args.trending_db)` runs before `connect_db(db_path)`. So a missing path or a non-SQLite file stops the start before `whitelist.db` is opened, the index is loaded or anything binds. It exits non-zero through `SystemExit`, with a message naming the path. The `mode=rw` open creates no file.\n- `ensure_trending_schema(db)` now runs only when the flag is absent. That branch is the original line and comment, unchanged. When the flag is set, `attach_trending_override(db, args.trending_db)` runs in the same place. That is after the two `executescript` ensures, which commit, so the ATTACH never runs inside a transaction. The shared `trending_ranks` is then neither created nor read on `server.db`.\n- The attach is wired in this phase because `server.py` is not in Phase 3's file list, and a flag that validates PATH but is never read would do nothing.\n- The plan's optional `trending_db=` startup log line is left out: no test or requirement needs it.\n\n### `tests/active/test_server_config.py`\nNot edited. Moving the checkpoint test into this file is test-side work for the promotion step, the same split Phase 1 used. Production code alone is enough to turn the checkpoint green.\n\n### `tests/config.json`\nNot edited, for the same reason. Adding `engine/server/data/trending.py` to the `test_server_config.py` group goes with promoting the test into that file. Changing the group mid-build would also change the fingerprint the workflow is gating on."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Active suite on a private Trending seed",
      "checkpoint": "Seam: the real session Engine over HTTP, through the `engine` fixture in `tests/active/conftest.py`, now started with `--trending-db <trending_seed>`. It follows `test_similar.py`'s existing `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` and its `_reference(dataset, ...)`. Test `test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(engine, dataset, shared_trending_before)`. Discrimination control: on a fresh plain `mode=ro` connection, the shared head (`fetch_ordered_page`, first `3 * FEED_PAGE`) differs from `_reference(dataset, \"trending\", threshold)`. If they are equal, the message says the shared table has no real fill. Trending: three `mode=trending` pages, walked with `exclude`, must equal `_reference(dataset, \"trending\", ...)[: 3 * FEED_PAGE]`. Popular layer: an unseeded `POST /recommendations?debug=1` with its own rate-bucket header. Every row with `debug.layer == \"popular\"` must be in `fetch_popular_videos(dataset, POOL)`, with `POOL` read through `_feed_constants` from the Engine's `DEFAULT_POPULAR_POOL_SIZE`. Control: at least one popular row is served. Fingerprint: `shared_trending_fingerprint() == shared_trending_before`, and the failure message names an updater trending-stage run as a possible external cause. The existing ordered-feed and NSFW tests stay green with unchanged expectations.",
      "intent": "The active suite's session Engine reads Trending from a per-session private file. `trending_seed` builds that file from the read-only shared catalogue, `engine` passes it as `--trending-db`, and `dataset` carries it, so the suite serves the seeded order without ever writing the shared `whitelist.db` `trending_ranks`.",
      "clauses": [
        {
          "id": "C1",
          "text": "The session Engine's Trending pages and its popular-layer rows follow the private seed file's ranks, not the shared table's."
        },
        {
          "id": "C2",
          "text": "The shared `whitelist.db` `trending_ranks` fingerprint (row count, `fetched_at` min and max, rows with `fetched_at > 0`) is identical before the seed and after the session Engine has served."
        }
      ],
      "files": [
        "tests/active/conftest.py (EDITED)",
        "tests/active/test_similar.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `tests/active/conftest.py`\n- The trending schema module (`engine/server/data/trending.py`) is now loaded once at module level as `TRENDING`. Before, it was loaded lazily inside `trending_seed`. `trending_seed` and `dataset` both use it.\n- Added `TRENDING_FINGERPRINT_SQL`: `COUNT(*)`, `MIN(fetched_at)`, `MAX(fetched_at)` and the count of rows with `fetched_at > 0`, read from `main.trending_ranks`.\n- Added `shared_trending_fingerprint()`. It runs that query on a fresh `file:\u2026?mode=ro` connection to `WHITELIST_DB` and returns a tuple.\n- Added the session fixture `shared_trending_before`, which returns that fingerprint.\n- `trending_seed(tmp_path_factory, shared_trending_before)` no longer writes the shared DB and no longer takes `ENGINE_START_LOCK`. It works like this:\n  - It creates `tmp_path_factory.mktemp(\"trending\") / \"trending.db\"` on a URI connection and applies `ensure_trending_schema`.\n  - It attaches `file:<WHITELIST_DB>?mode=ro` as `shared` and runs `TRENDING_SEED_SQL` unchanged inside `with conn:`.\n  - It returns the path.\n  - It takes `shared_trending_before` only to make the fingerprint read happen before the seed.\n- `engine` adds `\"--trending-db\", str(trending_seed)` to the Engine argv, plus one comment line. The start lock and the retry loop are unchanged.\n- `dataset(trending_seed)` calls `TRENDING.attach_trending_override(conn, str(trending_seed))` on its read-only connection. `_reference` and `fetch_popular_videos` on `dataset` therefore read the same private ranks the Engine serves.\n- Rewrote the module docstring, the `trending_seed` docstring and the comment above `TRENDING_SEED_SQL` to describe the private seed. `ENGINE_START_LOCK`, `fcntl` and `tempfile` stay, since the engine fixture and other test files still use them.\n\n### `tests/active/test_similar.py`\n- `_FEED_CONSTANTS_CHILD` now also prints `\"popular_pool_size\": server_config.DEFAULT_POPULAR_POOL_SIZE`, and the `_feed_constants` docstring mentions it.\n- The docstring bullet for the ordered-mode test now says the `dataset` connection's Trending ranks are the session's private seed.\n\n### Observed with probes (`tests/tmp/probe_private_seed.py`)\n- A `mode=ro` connection to the shared DB accepts the ATTACH plus TEMP VIEW from `attach_trending_override`.\n- A write to the attached shared DB is refused with \"attempt to write a readonly database\".\n- Running the new fixture bodies gave these results:\n  - The private file held 88,648 rows, all with `fetched_at = 0`.\n  - `dataset`'s view read those same 88,648 rows.\n  - The shared fingerprint was `(86826, 1791035941189, 1791035941189, 86826)` both before and after.",
      "beyond": "tests/tmp/probe_private_seed.py: a probe file I created and then emptied. I have no tool to delete a file, so it remains as an empty, uncollected file and should be deleted."
    }
  ],
  "digests": {
    "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py": "018276aa16c32a903e6a6b5a35665ac325fab704b4d4709647b668d494e81989",
    "tests/tmp/test_44_trending_seed_write_lock_during_phase2.py": "c38249e686c53b7e3421770d0485714f1ecfb00df1690ef3b5868375f3fc13dc",
    "tests/tmp/test_44_trending_seed_write_lock_during_phase3.py": "593a169460cb52698fccf10d0199af38ab7d0cc3ebc4d0564d44f4ee783bdf80"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261003T095937-6134-dev-flow"
  ],
  "snapshot": {
    "tree": "933762268c5f597d611f1416a976e3515d2bde03",
    "at": "2026-10-03T10:06:46-04:00"
  },
  "plan": "docs/project/plans/47-44-trending-seed-write-lock-during.md",
  "record": "docs/project/plans/47-44-trending-seed-write-lock-during.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nRunning the active suite must never change, or hold a write lock on, the shared dev `engine/server/db/whitelist.db` table `trending_ranks`. That file is the one the operator's long-running :7070 dev Engine serves, and worktrees symlink it too. Today the session fixture `trending_seed` (in `tests/active/conftest.py`) runs `DELETE FROM trending_ranks` and re-inserts `TRENDING_SEED_SQL` (each host's 100 most-viewed catalogue videos, `fetched_at = 0`, about 88,648 rows) on every lane start. That wipes any real fill (rows with `fetched_at > 0`) and holds the write lock for about 4.6 s in rollback-journal mode, against the Engine's 5 s busy timeout, while other lanes' Engines serve from the same file. The fix chosen with the operator: the test Engine reads private ranks through a new Engine CLI flag `--trending-db PATH`, and the suite never writes the shared `trending_ranks`. This is test isolation only. The Trending definition, CONTEXT.md and the ADRs do not change.\n\n### Engine: `--trending-db PATH`\n\n- `engine/server/api/server.py` `parse_args` gains an optional `--trending-db PATH`, with help text, so it shows in `--help`. It follows the style of the existing arguments (`--no-random-cache-refresh` and the others).\n- When the flag is set, every query the Engine runs against `trending_ranks` reads the table from the file at PATH. Today those are the `trending` entry of `ORDERED_FEED_SOURCE` in `engine/server/data/random_videos.py`, run through `fetch_ordered_page`, which `engine/server/api/handlers/similar.py` calls on `server.db`, and `fetch_popular_videos` (the Recommendations popular-layer pool), which `candidates/popular_videos.py` calls on `server.db`. `videos`, `video_embeddings`, moderation, interaction and every other table still come from `whitelist.db`.\n- The mechanism is the designer's choice, but it must cover every Engine connection on `whitelist.db` that runs a `trending_ranks` query. Today that is only `server.db` (`connect_db`). `search_db` (`connect_readonly_db`) and the random-cache build's source connection do not run Trending queries. Tree fact for the design: the shared `whitelist.db` already holds a `main.trending_ranks`, and SQLite resolves unqualified names in the order temp, main, then attached databases. A bare `ATTACH` of PATH therefore does NOT shadow the shared table. A TEMP view on the connection, or schema-qualified SQL, would.\n- With the flag set, the Engine never writes the shared file's `trending_ranks`, including at startup. `ensure_trending_schema` (server.py, currently called on `db` right after `ensure_interaction_event_schema`) applies to the private file instead of `whitelist.db`. The table shape and index (`trending_ranks`, `idx_trending_ranks_order`) are unchanged.\n- If PATH does not exist or cannot be opened as SQLite, the Engine start fails: it exits non-zero with an error message that names the path. It never silently falls back to the shared table, and it does not create the file. (Existing precedent: `connect_readonly_db` uses `mode=ro`, which never creates a file.)\n- Without the flag, behaviour and SQL plans are unchanged. The Trending page query still uses `idx_trending_ranks_order` as the driving index (the `CROSS JOIN` order), with no `TEMP B-TREE`, so an OFFSET walk stops early. The same must also hold with the flag set, so the test Engine exercises the same plan shape.\n\n### Active suite: private seed\n\n- `trending_seed` in `tests/active/conftest.py` builds the seed in a per-session temporary SQLite file (for example under `tmp_path_factory`), not in the shared DB. It applies `ensure_trending_schema` to that file and fills it with exactly the rows `TRENDING_SEED_SQL` produces today: same columns, ranks, likes, views and `fetched_at = 0`. It reads `videos` and `video_embeddings` from the shared `whitelist.db` through a read-only connection only, for example by attaching the shared DB read-only to the temp file's connection, or by opening the shared DB `mode=ro` and attaching the temp file. Either way the only file written is the temp file.\n- The `engine` fixture passes `--trending-db <temp file>` alongside `--no-random-cache-refresh`.\n- The seed no longer takes `ENGINE_START_LOCK`, because it no longer writes a shared file. The `engine` fixture keeps the lock for serialising Engine starts. Other tests import `ENGINE_START_LOCK` (`test_random_cache.py`, `test_server_config.py`), so the constant stays.\n- The fixture docstrings and the module docstring (conftest.py line 7 says `trending_seed` \"has rewritten that dataset's `trending_ranks`\") are updated to describe the private seed.\n- The suite opens no write connection to the shared `whitelist.db` for Trending.\n\n### Acceptance criteria\n\n- Starting the Engine with `--trending-db` on a seeded temp file serves Trending (`mode=trending`) in that file's merged-rank order. The shared `whitelist.db`'s `trending_ranks` fingerprint (row count; `fetched_at` min and max; count of rows with `fetched_at > 0`) is identical before and after.\n- Without the flag, Trending serves from `whitelist.db`'s `trending_ranks` as before.\n- Starting with `--trending-db` on a path that does not exist exits non-zero, with an error naming the path, and creates no file at that path.\n- After a full active-suite run, the shared `whitelist.db`'s `trending_ranks` fingerprint is unchanged, tested with a real fill present (rows with `fetched_at > 0`; the triage found 86,826 such rows in place). The suite cannot observe its own end, so this is checked by recording the fingerprint read-only before the build's full suite run and comparing it after. An in-suite test also gates that the session Engine started with the flag leaves the shared fingerprint unchanged.\n- The active suite passes, including the Trending and popular-layer tests in `test_similar.py` and its Trending NSFW control (a flagged row in the first 96 of the seeded order), with no test expectations changed.\n\n### Out of scope\n\n- Other test writes to the shared `whitelist.db`, such as bridge-mode interaction events from `engine_client`, and the other Engines the suite starts without the flag (`test_random_cache.py`, `test_server_config.py`). Those read the shared ranks, and their `ensure_trending_schema` is a `CREATE ... IF NOT EXISTS` that writes nothing when the table exists.\n- Confirming or fixing the intermittent up-next 500 (memory `upnext-pin-engine-500-intermittent`) beyond removing this writer.\n- Changing the seed's content or ranking, `engine/server/db/jobs/fetch-trending.py`, the updater's trending stage, or the moderation purge of `trending_ranks` (`engine/server/data/moderation.py`).\n- A general override for `whitelist.db` or the other DB paths.\n\n### Documentation\n\n- Document `--trending-db` where Engine CLI behaviour is described for developers (its `--help` text at minimum, and `engine/server/README.md` if it lists Engine flags), as a dev/test override that reads only `trending_ranks` from PATH.\n\n### Baseline suite state\n\n- Pre-build baseline: the active suite exits with code 0, no variant run (`variant: false`). The build must end with the suite still green.\n</requirements>\n\n<conflicts>\nThe brief suggests attaching the private file on each Engine connection and relies on \"SQLite resolves temp objects before main\". But the shared `whitelist.db` already holds `main.trending_ranks`, and an ATTACHed schema is searched after main, so a plain ATTACH would leave every unqualified query still reading the shared table. The override has to go through a TEMP object (for example a TEMP view over the attached table) or schema-qualified SQL, and it must keep `idx_trending_ranks_order` as the driving index.\nAcceptance criterion \"after a full active-suite run, the shared trending_ranks is unchanged\" cannot be asserted from inside the suite it covers. It is met by a fingerprint taken before and after the build's suite run, plus an in-suite test on the session Engine.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe change has two halves. The Engine gets a flag that sends its `trending_ranks` reads to a private file. The active suite seeds that private file and passes the flag. No `trending_ranks` SQL changes, and no function signature in `data/random_videos.py`, `handlers/similar.py` or `candidates/popular_videos.py` changes.\n\n**Engine flag.** `parse_args` in `engine/server/api/server.py` gains `--trending-db PATH` with `default=None`. It is written in the same `parser.add_argument(..., help=(...))` style as the other arguments. The help text says it is a dev/test override: only `trending_ranks` is read from PATH, the file must already exist and is never created, and every other table still comes from `whitelist.db`. That puts it in `--help`. `engine/server/README.md` does not list any Engine flags (I checked: none of the existing flags appear there), so `--help` is where this is documented, which is the minimum the requirement asks for.\n\n**How the override works: a TEMP view on `server.db`.** This goes in one small helper next to `ensure_trending_schema` in `engine/server/data/trending.py`. When the flag is set, `main()` does three things:\n\n1. **Validate first.** Before `connect_db(db_path)` and before anything touches `whitelist.db`, it opens PATH read-write with no create (the same URI precedent as `connect_readonly_db`, but `mode=rw`). It then runs `ensure_trending_schema` on that connection and closes it. This one step does three jobs:\n   - A missing path fails, and nothing is created.\n   - A file that is not SQLite fails on the schema statement (\"file is not a database\").\n   - The table and its index `idx_trending_ranks_order` are applied to the private file and not to `whitelist.db`.\n   \n   Any `sqlite3.Error` here becomes `SystemExit` with a message naming the path, so the exit is non-zero and the message goes to stderr. Because this runs before the FAISS load, a bad path fails in well under a second.\n2. **Attach.** After `connect_db`, it runs `ATTACH` of PATH on `db` under a fixed schema name.\n3. **Shadow.** It runs `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`. SQLite looks up unqualified names in the order temp, main, attached. So every unqualified `trending_ranks` on that connection now resolves to the private file. That covers the `trending` entry of `ORDERED_FEED_SOURCE` through `fetch_ordered_page` (the handler path) and `fetch_popular_videos` (the popular-layer path), because both run on `server.db`.\n\nWhen the flag is set, the existing `ensure_trending_schema(db)` call is skipped, because step 1 has already applied it to the private file. Without the flag, that call and everything else stay byte-for-byte as they are.\n\n**Checks against the tree:**\n- `server.db` is assigned once in `SimilarServer.__init__` and never replaced, so a per-connection view lasts the life of the process.\n- The only Engine code that writes `trending_ranks` is the moderation purge, and the only callers of `purge_host_data` are the jobs and job tests, never the API. So with the flag set, the Engine has no write path to the shared `trending_ranks`.\n- `search_db` and the random-cache source connection never mention `trending_ranks`, so they need nothing.\n- A TEMP view lives in the connection's temp schema, so creating it writes nothing to `whitelist.db`.\n\n**Plan shape with the flag.** The view is a plain `SELECT *` with no aggregate, DISTINCT, LIMIT or ORDER BY, and it is the left operand of the `CROSS JOIN`. SQLite's query flattener should therefore inline it as `<schema>.trending_ranks t CROSS JOIN video_embeddings e`. The private table drives the join through `idx_trending_ranks_order` with no `TEMP B-TREE`, the same plan as today. This is an expectation, not something I have verified, so the build gates it with an `EXPLAIN QUERY PLAN` test on a connection prepared by the helper, alongside the existing unflagged plan test in `test_random_videos.py`.\n\n**Active suite.** `trending_seed` in `tests/active/conftest.py`:\n- creates `trending.db` under `tmp_path_factory.mktemp(...)`, opened as a URI connection so that URI filenames work in `ATTACH`;\n- applies `ensure_trending_schema` to it;\n- attaches `whitelist.db` with `mode=ro`;\n- runs the unchanged `TRENDING_SEED_SQL`;\n- returns the path.\n\nThe unqualified names resolve correctly with no SQL edit: the insert target `trending_ranks` resolves to the temp file's main schema, which comes before the attached shared copy, while `videos` and `video_embeddings` exist only in the attached shared DB. The rows are exactly today's: same columns, ranks, likes, views and `fetched_at = 0`. The only file written is the temp file.\n\nThe seed drops `ENGINE_START_LOCK`. The constant stays, because `test_random_cache.py` and `test_server_config.py` import it. The `engine` fixture keeps the lock and adds `--trending-db <path>` next to `--no-random-cache-refresh`. The module docstring (line 7) and both fixture docstrings are rewritten to describe the private seed.\n\nNo session test reads `trending_ranks` through `dataset`. They only observe the Engine, so `test_similar.py`'s Trending, popular-layer and NSFW-control expectations still hold, since the served order is the same seeded order.\n\n**How each acceptance criterion gets gated (detail belongs to the test step):**\n- **Flag serves the private file's order; shared fingerprint unchanged.** A session-scoped fixture reads the shared fingerprint read-only before the seed and the Engine start: row count, `fetched_at` min and max, and the count of rows with `fetched_at > 0`. An in-suite test asks the session Engine for `mode=trending` pages and a popular-layer request, then checks two things. The pages must equal the merged-rank order computed from the temp file joined with the read-only dataset, under the NSFW filter. The shared fingerprint must be unchanged.\n- **Without the flag, Trending reads `whitelist.db`.** This is gated in-process rather than with another Engine start. A temp main DB holding ranks A and a temp private file holding ranks B are set up. `fetch_ordered_page` and `fetch_popular_videos` serve A on a plain connection and B on a helper-prepared connection. Main's ranks are unchanged afterwards. The plan assertions above run on both connections.\n- **Missing path.** A subprocess Engine start with `--trending-db <missing>`, the same way `test_server_config.py` drives the entry point, must exit non-zero, show the path in stderr, and leave no file at that path. The same test covers a non-SQLite file. This start fails before binding or opening `whitelist.db`, so it needs no start lock.\n- **Full-suite run with a real fill.** The build reads the fingerprint read-only before its full suite run and compares it afterwards. The shared DB currently holds a real fill (the triage found 86,826 rows with `fetched_at > 0`).\n\n### Alternatives considered\n\n- **Schema-qualified SQL**, for example a `trending` source string chosen per call or a schema argument passed through `fetch_ordered_page`, `fetch_popular_videos`, the builder deps and the handler. Rejected: it changes signatures and SQL on the default path, and touches several files to support a dev-only override. The requirement asks for unchanged behaviour and SQL without the flag. The view keeps every query untouched.\n- **A bare `ATTACH` with no view.** Rejected: as the requirements note, `main.trending_ranks` already exists in `whitelist.db` and comes before attached databases in name lookup, so it would silently keep serving the shared table.\n- **Opening the private file as `main` and attaching `whitelist.db`.** Rejected: every other table, and every write (moderation, interaction events), would then resolve against the wrong file.\n- **Rebuilding `server.db` with URI handling (`uri=True` in `connect_db`) so that `ATTACH` could use `mode=rw`.** Rejected: it changes `connect_db` for every caller to tighten one race that the validation step already covers.\n- **Seeding by opening the shared DB `mode=ro` and attaching the temp file.** Rejected: unqualified `trending_ranks` would then resolve to the shared, read-only main, so the INSERT would fail or need qualified SQL. Opening the temp file as main and attaching the shared DB keeps `TRENDING_SEED_SQL` verbatim.\n- **Copying `whitelist.db` per session.** Rejected: it is multi-GB and isolates far more than the requirement asks for.\n\n### Gotchas and risks\n\n- **Plain `ATTACH` creates a missing file**, because `server.db` is not a URI connection. The no-create guarantee therefore comes from the `mode=rw` validation that runs just before. If the file is deleted in the gap between validation and attach, an empty file would be created and Trending would serve empty, without falling back to the shared table. I am accepting this as a named limitation. The way up is a URI-enabled `server.db`.\n- **Relying on the query flattener.** If a future SQLite version or a view edit stops flattening, the plan would gain a scan or sort with the flag set, but default-path plans would be untouched. The flagged-plan test catches this.\n- **The seed still reads the shared DB for a few seconds** under a SHARED lock, because the DB is in rollback-journal mode. That can delay, but not block for good, a writer's commit on the shared file, such as the dev Engine's interaction ingest or an updater run. The write lock and the 5 s busy-timeout collision are gone, which is what the requirement is about. The suite's `dataset` reads already behave this way.\n- **External changes to the fingerprint.** If the operator's updater fills `trending_ranks` during a suite run, the in-suite fingerprint gate goes red without the suite being at fault. The failure message should say so.\n- **Relative paths.** A relative PATH resolves against the Engine's working directory, unlike the repo-root-relative default DB paths. The fixture passes an absolute path, and the help text says the path is used as given.\n- **Seed drift.** The private seed is still built from the live catalogue, so the existing caveat about the NSFW control (one flagged row in the first 96) is unchanged.\n\n### Tradeoffs the operator is asked to accept\n\n- **Engine code exists only for tests.** A dev/test flag ships in the production entry point, using a connection-level trick (a TEMP view shadowing a main table) that someone reading the SQL alone would not expect. A comment at the view creation and the help text explain it.\n- **No guarantee that the file cannot be created** (the race above). It is a documented ceiling, not a hard guarantee.\n- **Out of scope, as agreed.** Other suite writes to `whitelist.db` stay: bridge interaction events, and the unflagged Engines in `test_random_cache.py` and `test_server_config.py`.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impact path=\"engine/server/api/server.py\" element=\"parse_args() (lines 153-203): new --trending-db PATH argument\">\n**What changes:** add one `parser.add_argument(\"--trending-db\", default=None, help=(...))`. Put it after the `refresh_group` block and before `parser.set_defaults(random_cache_refresh=None)` / `return parser.parse_args()`. Follow the existing `help=(...)` multi-string style. Argparse derives `dest` as `trending_db`, so `args.trending_db` is `None` when the flag is absent. Per the plan, the help text should say four things: it is a dev/test override; only `trending_ranks` is read from PATH; PATH must exist and is never created; the path is used as given, so a relative one resolves against the working directory. The parser uses `CompactHelpFormatter` (`scripts/cli_format.py`), so the metavar renders as `--trending-db TRENDING_DB` unless `metavar=\"PATH\"` is given. Match whatever the tests assert.\n\n**What depends on it:**\n- `tests/active/test_server_config.py::test_server_py_exits_before_argument_parsing_on_a_bad_value` (line 78) runs `server.py --help` and asserts `\"--port PORT\" in ok.stdout`. A new option does not affect that line.\n- The systemd unit `peertube-engine@.service` (`DEPLOYMENT.md:111`, `ExecStart=... server.py --host 127.0.0.1 --port %i`) does not pass the flag.\n- `scripts/run-services.sh:35` does not pass it either.\n- The test runners pass argv through: `CACHE_VARIANT_RUNNER` in `test_random_cache.py:138` and `VARIANT_RUNNER` in `test_server_config.py:204-216` both set `sys.argv = [server, *sys.argv[3:]]`.\n\n**Regression risk:** low. The flag is optional with a `None` default, and there are no mutually-exclusive interactions.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"main() startup sequence (lines 326-338): validate PATH before connect_db, ATTACH + TEMP VIEW after it, skip ensure_trending_schema(db) when flagged\">\n**What changes:**\n- **Before line 332** (`db = connect_db(db_path)`): when `args.trending_db` is set, call the new helper's validation step. It opens `file:<path>?mode=rw` with `uri=True`, runs `ensure_trending_schema`, closes the connection, and turns any `sqlite3.Error` into `SystemExit(<message naming the path>)`.\n- **After `connect_db`:** ATTACH the file under a fixed schema name and `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`.\n- **Line 337** (`ensure_trending_schema(db)`, with its comment at 336) becomes conditional on the flag being unset.\n\nOrdering matters:\n- ATTACH cannot run inside an open transaction. Right after `connect_db` none is open. Every `ensure_*` uses `executescript`, which commits first, so placing the ATTACH after line 339 is also safe.\n- `ensure_moderation_schema`, `ensure_interaction_event_schema`, `ensure_channels_indexes` and `ensure_video_indexes` use unqualified `CREATE ... IF NOT EXISTS`. An unqualified CREATE targets main, and the private file holds no tables with those names, so these are unaffected whether the attach comes before or after them.\n- `channels.py:46` and `videos.py:11-14` probe `sqlite_master`, which is main only, so they are unaffected.\n\nOther details:\n- A `SystemExit` raised before the `try/finally` at 516 leaves the SIGINT/SIGTERM handlers swapped. This is harmless because the process is exiting. `assert_index_matches_embeddings` (line 368) already exits the same way.\n- The log line at 494 (`db=%s index=%s total=%d`) is the natural place to also log the override path. This is optional. No test parses that line (`test_server_config.py` parses only `upnext_config` and `ann_nprobe_configured`).\n- The new name added to `from data.trending import ensure_trending_schema` (line 110) must exist in `trending.py`. `server.py` is imported in Engine-interpreter children by `tests/active/test_internal_events.py:47` and `tests/active/test_video.py:163,199`, so an `ImportError` there breaks those suites.\n\n**What depends on it:** every unqualified `trending_ranks` read on `server.db` (the handler's ordered feed and the popular layer). `search_db` (line 333, `connect_readonly_db`) and the random-cache worker's own connection (`run_random_cache_worker(db_path, ...)`, line 500) do not read `trending_ranks` (grep for `trending` in `data/search.py` and `data/random_cache.py` finds nothing), so they need no view.\n\n**Regression risk:**\n- **Medium for the flagged path:** step order, the transaction state at ATTACH, and the view name colliding with `main.trending_ranks`. SQLite allows a temp object to shadow a main one; I expect that and have not run it.\n- **Low for the default path,** provided the unflagged branch stays byte-for-byte as it is. The phase test should check that line 337 still runs when the flag is absent: \"without the flag, Trending reads whitelist.db\".\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"SimilarServer.__init__ self.db (line 242) and main()'s finally db.close() (line 533)\">\n**What changes:** nothing.\n\nThe plan's claim checks out. `self.db = db` is the only assignment: a grep for `\\.db\\s*=` under `engine/server` finds only `server.py:242` and an unrelated test double in `db/jobs/tests/test-moderation-integration.py:942`. A per-connection TEMP view and ATTACH therefore last for the life of the process. `db.close()` at 533 releases the attachment along with the connection.\n\n**What depends on it:** every handler that uses `server.db` under `db_lock`. The writers on this connection are ingest (`internal_events.py:66-74`), the video write-back (`video.py:389-432`) and the raw prune (`internal_events.py:111`). They write main tables only, and a transaction that writes only main never needs a lock on the attached file.\n\n**Regression risk:** low. Any write transaction that also read the view holds a SHARED lock on the private file until commit. Nothing else writes that file while the Engine runs, so there is no contention.\n</impact>\n<impact path=\"engine/server/data/trending.py\" element=\"ensure_trending_schema (lines 8-25) unchanged, plus a NEW helper next to it (validate PATH with mode=rw and apply the schema; ATTACH + CREATE TEMP VIEW on a connection)\">\n**What changes:** add one small function, or two. Keep the module's style: `from __future__ import annotations`, `import sqlite3`, a one-line docstring per function, and comments on a single line. One reasonable shape:\n- `prepare_trending_override(path)`: the `mode=rw` open plus `ensure_trending_schema`, raising `SystemExit` or returning.\n- `attach_trending_override(conn, path)`: `ATTACH DATABASE ? AS <schema>` followed by `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`.\n\nA comment at the view should explain the shadowing, as the plan requires. ATTACH accepts a bound parameter for the filename, so the path needs no quoting.\n\nOn a non-URI connection such as `connect_db`, a plain ATTACH creates a missing file. That is the named race; the `mode=rw` check is what guards against it.\n\nA 0-byte existing file passes validation: SQLite treats it as an empty database, and `ensure_trending_schema` creates the table in it. Trending then serves an empty page rather than failing. This is consistent with \"must already exist\", but say so in the help text or a test if it matters.\n\n**What depends on it:**\n- `ensure_trending_schema` is imported by `engine/server/api/server.py:110`, `engine/server/db/jobs/fetch-trending.py:28` and the tests (`test_random_videos.py:78`, `test_similar.py:101`, `test_moderation.py:29`, `test_popular_videos.py:37`).\n- `tests/active/conftest.py:132-134` loads this file by path under the module name `active_trending_schema`.\n- The signature of `ensure_trending_schema(conn)` must not change.\n- The new helper will be used by `server.main()`, the new in-process tests in `test_random_videos.py`, and possibly the `dataset` fixture (see that entry).\n\n**Regression risk:** low for the existing function, which is untouched. The new helper carries the flattening and plan risk; see `random_videos.py`.\n</impact>\n<impact path=\"engine/server/data/db.py\" element=\"connect_db (77-82) and connect_readonly_db (85-94): unchanged, used as precedent\">\n**What changes:** nothing. The plan rejected adding `uri=True` to `connect_db`.\n\nPoints relevant to the build:\n- `connect_db` calls `sqlite3.connect(path.as_posix(), check_same_thread=False)` without `uri=True`. ATTACH on it therefore takes a plain filename, and a `file:...?mode=rw` URI string would be treated as a literal filename.\n- `connect_readonly_db` is the URI precedent (`f\"file:{path.as_posix()}?mode=ro\"`, `uri=True`). Validation should use the same form with `mode=rw`.\n- A path containing `?` or `#` would need URI escaping in the validation open. This is a minor edge case that the fixture's temp path does not hit.\n- The deadline progress handler (`install_deadline_handler`) is per connection, so statements reading the attached file are bounded by `statement_deadline` exactly as before.\n\n**What depends on it:** every Engine connection.\n\n**Regression risk:** none if left untouched.\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"ORDERED_FEED_SOURCE['trending'] (36-42), ORDERED_FEED_ORDER_BY['trending'] (16-22), fetch_ordered_page (241-334), fetch_popular_videos (234-238): unchanged, resolved through the view\">\n**What changes:** no edit. With the flag set, `trending_ranks t CROSS JOIN video_embeddings e ON ...` resolves `trending_ranks` to the TEMP view, because name lookup goes temp, then main, then attached. `t.rank`, `t.likes`, `t.views`, `t.video_id` and `t.instance_domain` in the ORDER BY are view columns, since the view is `SELECT *`.\n\nThe expected flattened plan is `SCAN t USING INDEX idx_trending_ranks_order` (now on the attached schema) with no `USE TEMP B-TREE FOR ORDER BY`. That is an expectation only: SQLite 3.53.4 ships in the engine pixi env (`engine/.pixi/envs/default/lib/libsqlite3.so.3.53.4`), and I could not run EXPLAIN QUERY PLAN to confirm it. The pytest interpreter's sqlite version may differ from the Engine's, which matters if the plan test runs in-process under pytest rather than under `ENGINE_PY`. The existing plan test (`test_random_videos.py:222-240`) runs in-process.\n\n**What depends on it:**\n- `handlers/similar.py:777-784` (`_handle_ordered_feed`, using `self.server.db` under `db_lock`).\n- `recommendations/builder.py:114-116` (`fetch_popular_videos_filtered`) \u2192 `candidates/popular_videos.py:53` (`server.db` under `db_lock`).\n- `tests/active/test_similar.py:764` (`_reference`, run on `dataset`; see the HIGH entry).\n- `test_random_videos.py` (33 uses).\n- `test_popular_videos.py`.\n- `test_video.py:220` (deps wiring).\n\n**Regression risk:**\n- Default path: none, since the SQL is untouched.\n- Flagged path: medium. If flattening does not happen, the order is still correct but the plan gains a scan or sort. The 5 s statement deadline (`DEPLOYMENT.md:453`) could then bite on deep pages with a full 88k-row seed.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"_handle_ordered_feed (759-806) and FEED_MODES/ORDERED_FEED_MODES (105-107)\">\n**What changes:** nothing. It reads `self.server.db`, which is the connection that carries the view, under `db_lock`, then applies serving moderation.\n\n**What depends on it:**\n- `test_similar.py:819` (`test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order...[trending]`).\n- The NSFW listing test (`test_similar.py:1043`, `mode=trending`).\n- The child-process handler test (`test_similar.py:961`), which uses its own temp DB.\n\n**Regression risk:** none in the code. The test-side risk is covered in the `test_similar.py` entries.\n</impact>\n<impact path=\"engine/server/api/recommendations/candidates/popular_videos.py\" element=\"PopularVideosGenerator.get_candidates line 53 (fetch_popular_videos(server.db, ...)); and engine/server/api/recommendations/builder.py fetch_popular_videos_filtered (114-116)\">\n**What changes:** nothing. The plan states that no signature changes. The pool read goes through `server.db`, so it is covered by the view.\n\n**What depends on it:**\n- The Recommendations mix's popular layer.\n- `test_popular_videos.py`, which runs a child on a temp DB and is unaffected.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/api/recommendations/builder.py\" element=\"RecommendationBuilderDeps.fetch_popular_videos (line 60) and fetch_popular_videos_filtered (114-116)\">\n**What changes:** nothing. It is listed because the plan's rejected alternative would have threaded a schema argument through here. Under the chosen approach the deps and settings stay identical, and `test_video.py:220` builds `RecommendationBuilderDeps` by keyword and would break on any added required field.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/data/moderation.py\" element=\"_host_table_column_pairs (308-319), purge_host_data (194-), _count_host_rows (322-338), _table_exists (415-421)\">\n**What changes:** nothing. This is out of scope per the issue.\n\nI verified the plan's claim:\n- `purge_host_data` callers are `instance-denylist-cli.py:190,222,227`, `updater-worker.py:619,642` and `db/jobs/tests/test-moderation-integration.py:874,907,1022`.\n- The test callers are `test_moderation.py` and `test_ann.py`.\n- None is in `engine/server/api`.\n\nWith the flag set, the Engine therefore has no write path to the shared `trending_ranks`.\n\n`_table_exists` queries `sqlite_master`, which covers main only and never sees the TEMP view. If a purge were ever run on a flagged connection, it would count and delete the shared `main.trending_ranks`, not the private file. That is a latent trap, but it is unreachable today.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/db/jobs/fetch-trending.py\" element=\"run() calling ensure_trending_schema (line 102); writes to trending_ranks (117-119)\">\n**What changes:** nothing. It is out of scope per the issue. It depends on `ensure_trending_schema(conn)` keeping its signature and behaviour.\n\n**Regression risk:** none, as long as `trending.py`'s existing function is untouched. `tests/active/test_fetch_trending.py` gates it.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"trending stage (1431-1469) and purge_host_data callers (619, 642)\">\n**What changes:** nothing. It keeps writing the shared `trending_ranks` on the operator's schedule.\n\n**What depends on it:** the new fingerprint gate. An updater run during a suite run changes the shared fingerprint and turns the in-suite gate red without the suite being at fault. The plan names this; the failure message should say so.\n\n**Regression risk:** none in the code. The test-flake risk is acknowledged.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"trending_seed fixture (126-144) and TRENDING_SEED_SQL (107-123)\">\n**What changes:**\n- The fixture becomes `trending_seed(tmp_path_factory)` and returns a path. The seed target is `tmp_path_factory.mktemp(...) / \"trending.db\"`.\n- Open it with `sqlite3.connect(f\"file:{path}\", uri=True)` or equivalent, so that URI ATTACH works. Then run `trending.ensure_trending_schema(conn)`, `ATTACH DATABASE 'file:<WHITELIST_DB>?mode=ro' AS ...`, and `TRENDING_SEED_SQL` verbatim inside `with conn:`.\n- Drop the `DELETE FROM trending_ranks`. The table is fresh, and keeping the delete would be harmless anyway because it resolves to the temp file's main.\n- Drop the `ENGINE_START_LOCK` block.\n\n`TRENDING_SEED_SQL` stays unchanged. Its unqualified `trending_ranks` resolves to the temp file's main (main before attached), and `videos` and `video_embeddings` exist only in the attached shared DB. The comment on line 107 (\"every lane writes the same rows\") should be reworded, because each lane now writes its own file.\n\nThe fixture keeps loading `trending.py` by file spec (lines 132-134). If the new helper is reused here, for example for the `dataset` fix, it is available on the same module object.\n\n**What depends on it:** the `engine` fixture (line 148) and, if the HIGH `dataset` fix is taken, the `dataset` fixture.\n\n**Regression risk:** medium.\n- **Same rows:** the rows must match today's exactly (ranks, likes, views, `fetched_at = 0`) for `test_similar`'s NSFW control. `TRENDING_SEED_SQL` is unchanged, but the ROW_NUMBER tie order is defined by `views DESC, likes DESC, video_id DESC`, which is deterministic, so this should hold.\n- **URI handling:** if the seed connection is not opened with `uri=True`, `ATTACH 'file:...?mode=ro'` silently creates a file literally named `file:...` in the CWD instead of opening the shared DB read-only. The seed would then fail with \"no such table: videos\". That is loud, not silent.\n- **Lock:** the seed now holds a SHARED lock on the shared file for a few seconds, which the plan names as a risk.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"engine fixture (147-186)\">\n**What changes:**\n- Add `\"--trending-db\", str(trending_seed)` next to `\"--no-random-cache-refresh\"` in the Popen argv (lines 162-163). It needs an absolute path, which `tmp_path_factory` provides.\n- Keep the `ENGINE_START_LOCK` loop.\n- Update the comment at 155-156 if it should mention the override.\n\n**What depends on it:** every session-Engine test (`engine_client`, `unpublished_client`, `test_similar`, `test_server_config.py:270`, `test_random_cache`, profiles and so on).\n\nA start that fails validation is retried 5 times by the loop (lines 159-179), each retry sleeping `1 + attempt` seconds, before `assert proc.poll() is None` fails. A seed bug would therefore show up as \"Engine exited on every start\" after about 15 s, with the cause in `engine.log`.\n\n**Regression risk:** medium, because every Engine-backed test depends on this start succeeding.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"module docstring (lines 1-14), ENGINE_START_LOCK constant (104-106), imports fcntl/tempfile (17, 25)\">\n**What changes:** rewrite docstring lines 6-11. \"after `trending_seed` has rewritten that dataset's `trending_ranks`\" becomes a description of the private per-session seed and the `--trending-db` flag. If the `dataset` fixture changes, its description must change as well.\n\n`ENGINE_START_LOCK` stays. Its importers are:\n- `tests/active/test_random_cache.py:44` (used at 297).\n- `tests/active/test_server_config.py:39` (used at 254).\n- `tests/archive/short_similarity_cache/test_similar.py:129` (skipped).\n- `conftest`'s own `engine` fixture.\n\n`fcntl` and `tempfile` stay in use (the engine fixture and `ENGINE_START_LOCK`).\n\n**Regression risk:** low. These are text-only changes, and `ImportError`s are avoided by keeping the constant.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"dataset fixture (228-233): HIGH, the plan's claim that no session test reads trending_ranks through dataset is wrong\">\n**What changes:** the plan says nothing changes here. In fact `tests/active/test_similar.py:759-766` `_reference(dataset, order, threshold)` calls `fetch_ordered_page(dataset, order, REFERENCE_DEPTH, 0, ...)`. For `order == \"trending\"`, that reads `trending_ranks` from the shared `whitelist.db` through `dataset`.\n\nToday this agrees with the Engine because both read the seeded shared table. After the change, the Engine serves the private seed while `dataset` reads the operator's real fill (86,826 rows with `fetched_at > 0` per the triage). The assertion `first + following + last == reference[: 3 * FEED_PAGE]` (`test_similar.py:849`) therefore fails for the `trending` parametrization. That breaks the acceptance criterion \"the active suite passes ... with no test expectations changed\".\n\nOptions, which the build has to choose between:\n- **(a)** Make `dataset` depend on `trending_seed` and, after opening it `mode=ro` (a URI connection, so URI ATTACH works), apply the same ATTACH + TEMP VIEW helper to the private file. The expectation is unchanged and `_reference` is untouched. The cost: every test that uses `dataset` now triggers the seed, which is session-scoped and a few seconds, once per lane. I believe a TEMP view can be created on a `mode=ro` connection because the temp schema stays writable, but I have not verified it. Attaching with `mode=ro` keeps the private file read-only there too.\n- **(b)** A separate session fixture, for example `trending_dataset`, prepared that way and used only by `_reference` for `trending`. This changes test code but not expected values.\n\n`dataset` is used by test_blocks, test_dislike_profile, test_dislikes, test_frontend_* , test_profiles, test_random_cache, test_server and test_similar. With (a), the shared file gets one more read-only reader holding the seed's SHARED lock window. The plan's in-suite \"pages equal merged-rank order computed from the temp file joined with the read-only dataset\" test needs exactly this prepared connection, so the helper is needed in the tests either way.\n\n**Regression risk:** high. Without action, `test_similar.py::test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` goes red whenever the shared table differs from the seed, which is always once a real fill exists.\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"_reference (759-766), test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated (818-849) for order=trending, module docstring line 64\">\n**What changes:** depends on the `dataset` decision above. With option (a), nothing in this file changes. The docstring line 64 says \"read through the read-only `dataset` connection\", which stays true, though it should perhaps mention that `dataset` carries the private Trending ranks. With option (b), `_reference` picks the prepared connection for `trending`, and docstring line 64 must say so.\n\nThe re-read control at line 836 (`_reference(...) == reference`) still holds with either option, because the private file is static for the session. With the unfixed shared read it would also hold, but an updater run mid-test would break it.\n\n**What depends on it:** the `trending` parametrization of `ORDERED`, read from `handlers.similar.ORDERED_FEED_MODES` at collection (`test_similar.py:743-746`).\n\n**Regression risk:** high if missed (see above).\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"NSFW listing control for mode=trending (comment 997-999, test 1043) and nsfw_flagged (1009)\">\n**What changes:** nothing. The comment at 998 says the control \"was rehearsed with exactly one flagged row in the first 96 seeded Trending rows; the seed is derived from the live whitelist.db\". The private seed is built by the same SQL from the same live catalogue, so the Engine serves the same rows. `nsfw_flagged` reads `videos.nsfw` through `dataset`, not `trending_ranks`.\n\n**What depends on it:** the seed producing identical rows.\n\n**Regression risk:** low. The existing seed-drift caveat is unchanged, as the plan says.\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"_ranks_db / _TRENDING_HANDLER_CHILD / test_the_handler_serves_trending_until_the_ranked_rows_run_out... (852-990)\">\n**What changes:** nothing. It runs `SimilarHandler` on a stub server over its own temp DB in an Engine-interpreter child, without the `engine` fixture and without the flag.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_random_videos.py\" element=\"test_a_trending_page_walks_the_ranks_index_without_sorting (222-240), _plan/_Recorder (198-219), _schema (119-128), imports (74-78); NEW flagged-plan and flag-on/flag-off in-process tests\">\n**What changes:**\n- The plan adds an `EXPLAIN QUERY PLAN` test on a helper-prepared connection, beside the existing unflagged one. It also adds an in-process test: main DB with ranks A, private file with ranks B; `fetch_ordered_page` and `fetch_popular_videos` serve A on a plain connection and B on a prepared one; main's ranks are unchanged afterwards.\n- `_plan` can be reused as is. It records the SQL via `_Recorder` and runs `EXPLAIN QUERY PLAN` on the same connection, so the view is in scope.\n- The prepared connection's main must hold `videos`, `video_embeddings`, `channels` and `trending_ranks` (`_schema` already builds all of them). The private file needs `ensure_trending_schema` and rows.\n- The module docstring (lines 1-54) lists every claim, so new tests need new docstring bullets in the same style.\n- The import at line 78 grows the new helper name.\n\n**What depends on it:** `tests/config.json` group `test_random_videos.py` already maps `engine/server/data/trending.py`.\n\n**Regression risk:** low for the existing tests, which are unchanged. The new plan assertion's index-name check (`\"idx_trending_ranks_order\" in detail`) should still match an attached-schema index. That is unverified.\n</impact>\n<impact path=\"tests/active/test_server_config.py\" element=\"subprocess Engine driving pattern (_run 47-52, VARIANT_RUNNER 204-217, _start_variant 252-267), ENGINE_START_LOCK import (39); likely home of the missing-path/non-SQLite subprocess test\">\n**What changes:** the plan's missing-path test copies this file's pattern: `subprocess.run([str(ENGINE_PY), str(ENGINE_SERVER), \"--trending-db\", missing, ...], capture_output=True, ...)`. It asserts a non-zero return code, the path in stderr, and no file at the path. It also covers a non-SQLite file. No start lock is needed, because validation runs before `connect_db` and binding.\n\nThe process still imports `server_config` and initialises logging before validation. A missing `ENGINE_PY` should be handled the way the other tests here handle it.\n\n`_start_variant` (254-258) starts an unflagged Engine on the shared DB. That is out of scope per the plan, but it means `ensure_trending_schema(db)` runs on shared `whitelist.db` during the suite. `CREATE ... IF NOT EXISTS` on an existing table writes nothing, so the fingerprint is unaffected.\n\n**What depends on it:** the `--help` control at 80-82.\n\n**Regression risk:** low.\n</impact>\n<impact path=\"tests/active/test_random_cache.py\" element=\"ENGINE_START_LOCK import (44), _cache_variant (286-323), concurrent unflagged starts (796-811)\">\n**What changes:** nothing. These keep importing `ENGINE_START_LOCK` and start Engines without `--trending-db` on the shared DB. That is out of scope per the plan. Like any unflagged start, they run `ensure_trending_schema(db)` on shared, which is a no-op when the table exists and leaves the fingerprint unchanged.\n\n**Regression risk:** none, provided the constant is kept in conftest.\n</impact>\n<impact path=\"tests/archive/short_similarity_cache/test_similar.py\" element=\"imports ENGINE_START_LOCK etc. from conftest (docstring line 3, use at 129)\">\n**What changes:** nothing. It is skipped, but its docstring says it depends on conftest's `ENGINE_START_LOCK`. Keeping the constant keeps it importable.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_moderation.py\" element=\"ensure_trending_schema import (29) and use (105)\">\n**What changes:** nothing. It depends on `ensure_trending_schema(conn)` being unchanged.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_fetch_trending.py\" element=\"trending_ranks schema check (251-259), job tests\">\n**What changes:** nothing. It depends on `ensure_trending_schema` behaviour. Its missing-`--db` subprocess test (251) is the precedent for the new missing `--trending-db` test (exit non-zero, no file created).\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_popular_videos.py\" element=\"ensure_trending_schema import (37), child-process mix over temp DB (195-255)\">\n**What changes:** nothing. Its temp DB holds `trending_ranks` in main, and no flag is involved.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_internal_events.py\" element=\"Engine-interpreter child that does `import server` (line 47) and builds SimilarServer\">\n**What changes:** nothing directly. However, it imports `engine/server/api/server.py` at module level, so a broken new import line (for example, a helper name that does not exist in `data/trending.py`) fails this suite. It does not call `main()` or `parse_args`, so the flag logic itself is not exercised.\n\n**Regression risk:** low.\n</impact>\n<impact path=\"tests/active/test_video.py\" element=\"Engine-interpreter children that `import server` (163, 199) and build RecommendationBuilderDeps (220)\">\n**What changes:** nothing. As with `test_internal_events.py`, this imports `server.py`, so the module-level imports must resolve. Line 220 constructs `RecommendationBuilderDeps` by keyword, which confirms the plan's choice not to add fields there.\n\n**Regression risk:** low.\n</impact>\n<impact path=\"tests/active (NEW fingerprint gate: session fixture + in-suite test; location TBD, conftest.py plus test_similar.py or a new file)\">\n**What changes:** add a session fixture that reads the shared `trending_ranks` fingerprint read-only before `trending_seed` and `engine` run: `COUNT(*)`, `MIN(fetched_at)`, `MAX(fetched_at)` and the count with `fetched_at > 0`, read via a `file:...?mode=ro` URI, as `dataset` does.\n\nTo guarantee it runs before the seed, `trending_seed` or `engine` should depend on it. Pytest instantiates fixtures in dependency order, but with no dependency two independent session fixtures may run in either order.\n\nThe in-suite test requests `mode=trending` pages and a popular-layer request from the session Engine, then compares them to the merged-rank order computed from the temp file joined with `dataset` under the NSFW filter. It needs the same prepared connection as the HIGH `dataset` entry, then re-reads the fingerprint. Its failure message must name the external-updater possibility.\n\nA popular-layer request shows its source only with `debug=1`; the session Engine runs `RECOMMENDATIONS_DEBUG=1`. Check how the popular rows can be identified, for example from debug layer tags in the response. I did not verify the debug payload shape.\n\n**What depends on it:** `trending_seed`, `engine`, `dataset`.\n\n**Regression risk:** medium: a flaky external-change failure, and fixture ordering.\n</impact>\n<impact path=\"tests/config.json\" element=\"test_groups (14-...)\">\n**What changes:** if a new test file is created, for example for the flag subprocess test or the fingerprint gate, add a `test_groups` entry mapping it to `engine/server/api/server.py` and `engine/server/data/trending.py`. If the tests land in existing files, consider adding `engine/server/data/trending.py` to `test_server_config.py`'s group (130-133), which today lists only `server_config.py` and `server.py`. `test_random_videos.py` (112-118) and `test_similar.py` (54-71) already map `trending.py`. `conftest.py` is mapped nowhere.\n\n**Regression risk:** low. This is metadata for the test runner and validator.\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"referenced by conftest docstring line 7 as how the Engine is started\">\n**What changes:** nothing. The conftest docstring says the engine fixture starts the Engine \"the way `tests/run-arch-split-smoke.sh` does\". After the change the fixture also passes `--trending-db`, so that comparison should be qualified in the docstring rewrite. The script itself (no `trending` match) is untouched.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"scripts/run-services.sh\" element=\"ENGINE_SCRIPT launch (35) and process matching (205, 234)\">\n**What changes:** nothing. The flag is not passed, and the dev Engine on :7070 keeps reading the shared `trending_ranks`, which is the point of the fix.\n\n**Regression risk:** none.\n</impact>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"engine/server/README.md\">\nOptional, uncertain whether wanted. Line 26 says \"Trending serves only videos ranked in `trending_ranks`\". The plan documents the flag only in `--help`, because the README lists no Engine flags; I confirmed it has none. If one sentence is wanted, it would read: \"a dev/test `--trending-db PATH` makes the Engine read `trending_ranks` from PATH instead (see `--help`)\". Otherwise there is no change.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\">\nLine 101 (\"**First fill.** `trending_ranks` is created empty when the Engine starts\") stays true for every production start. With `--trending-db` the Engine applies the schema to PATH, not to `whitelist.db`. This is a dev/test nuance, so a change is optional. I am flagging it only so the doc step can make a deliberate choice.\n</doc>\n<doc path=\"docs/project/issues/44-trending-seed-write-lock-during-test-runs.md\">\nOn delivery, set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md` and `issue-tracker.md`. Tick the acceptance criteria and record the named limitation: the validation-to-ATTACH race can create an empty file.\n</doc>\n<doc path=\"tests/active/conftest.py\">\nModule docstring lines 6-11: describe the per-session private seed file and `--trending-db` instead of \"`trending_seed` has rewritten that dataset's `trending_ranks`\", and update the `dataset` description if that fixture gains the private view. Also update the `trending_seed` docstring (128-130, which today cites the \"operator decision (issue 38 build)\" and the start lock), the `engine` fixture comment, and the comment at line 107 (\"every lane writes the same rows\").\n</doc>\n<doc path=\"tests/active/test_similar.py\">\nDocstring line 64 says the ordered-feed reference is \"read through the read-only `dataset` connection\". Update it if the trending reference moves to a prepared connection, which is option (b). Under option (a), consider noting that `dataset` carries the session's private Trending ranks.\n</doc>\n<doc path=\"tests/active/test_random_videos.py\">\nModule docstring (lines 1-54): add bullets for the new flagged `EXPLAIN QUERY PLAN` test and the flag-on/flag-off in-process test, in the existing claim style.\n</doc>\n\n</docs_checklist>\n\n<highest_risk>\ntests/active/conftest.py `dataset` fixture together with tests/active/test_similar.py `_reference` (759-766): the plan says no session test reads `trending_ranks` through `dataset`, but `_reference(dataset, \"trending\", ...)` does. With the Engine on the private seed and the shared DB holding the real fill, `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` fails at line 849 unless `dataset`, or a trending-specific reference connection, gets the same ATTACH + TEMP VIEW.\nengine/server/api/server.py main() lines 326-338: the startup order of validate \u2192 connect_db \u2192 ATTACH/TEMP VIEW \u2192 skip `ensure_trending_schema(db)` is where the shared file could still be written (if the skip is wrong) or the view could fail (ATTACH inside a transaction, or a name collision with `main.trending_ranks`). A failure here also breaks every Engine-backed test through the `engine` fixture's 5-retry loop, and the new import line is loaded by the `test_internal_events.py` and `test_video.py` children.\nengine/server/data/random_videos.py ORDERED_FEED_SOURCE['trending'] through the new view: correctness does not depend on flattening, but the no-sort plan does, and it is unverified on SQLite 3.53.4 (the Engine env) and possibly a different sqlite under pytest. A non-flattened plan sorts the full seed on each chunk, under the 5 s statement deadline.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the tree. The plan's mechanism holds: one TEMP view on `server.db` covers every Engine read of `trending_ranks`, and none of the paths that need to stay unchanged are touched. There is one real problem, and the inventory already raised it as its HIGH `dataset` entry. The plan says no session test reads `trending_ranks` through `dataset`, and that is wrong. `test_similar.py:764` calls `fetch_ordered_page(dataset, \"trending\", ...)`, and line 849 compares the Engine's pages to that result. With the plan as written, the Engine would serve the private seed while `dataset` reads the operator's real fill, so the `trending` case of that test fails. That breaks acceptance criterion 5 (\"no test expectations changed\"). The plan says nothing changes here, so I report it under conflicts and don't treat the fix as already approved.\n\nWhat I confirmed in the tree:\n- **Only one connection reads `trending_ranks`.** It is named only in `random_videos.py:37`; `fetch_ordered_page` is called only from `similar.py:777`, and `fetch_popular_videos` only from `popular_videos.py:53` with `server.db`. `search_db` and the random-cache worker never read it.\n- **The connection lives for the whole process.** `self.db = db` (`server.py:242`) is the only assignment. `connect_db` (`db.py:77-82`) is a non-URI connection, as the inventory says.\n- **Placement in `main()` is clean.** `connect_db` at line 332 is the first thing that touches `whitelist.db`. `configure_engine_logging` (line 324) logs to a stream only and opens no file, so the missing-path start creates or writes nothing.\n- **The Engine API cannot write the shared table.** `purge_host_data` is called only from moderation, the denylist CLI, the updater and the job tests.\n- **The README claim holds.** `engine/server/README.md` lists no Engine flags; only `LAYER_PARAMS.md:130` mentions any, in passing.\n- **Popular-layer rows can be identified.** Debug rows carry `debug.layer` (`recommendations/debug.py:23`), which settles a point the inventory left unverified.\n- **No other session test depends on `trending_ranks`.** `test_frontend_feed_params.py` is bundle and AST only, and `test_updater_worker.py` is source scans and shims.\n- **The NSFW control is unaffected.** `nsfw_flagged` (`test_similar.py:1009`) reads only `videos.nsfw`.\n\n<question id=\"1\">\nYes for the Engine half. With the flag set, every unqualified `trending_ranks` on `server.db` (the handler at `similar.py:777` and the popular pool at `popular_videos.py:53`) resolves to the TEMP view, because SQLite looks in temp before main. A temp object may share a name with a main table and may reference an attached schema. Nothing else reads the table.\n\nFor the suite half, only partly. The Engine serves the private seed, but `_reference` in `test_similar.py` still reads the shared table through `dataset`. So `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` fails whenever the shared table differs from the seed, which is always once a real fill exists (86,826 rows with `fetched_at > 0` today). It works only once `dataset`, or a connection used in its place for `trending`, also sees the private ranks.\n\nTwo parts stay expectations until tests run: that the query flattener inlines the view (the flagged-plan test gates this), and that a TEMP view can be created on the `mode=ro` `dataset` connection.\n</question>\n<question id=\"2\">\n- **Engine:** a dev/test-only flag ships in the production entry point. With the flag set, the Engine writes to the private file at startup (the schema), and `whitelist.db` never gets `ensure_trending_schema`. Default starts are untouched.\n- **Accepted limits:** the attach race (validation passes, then the file is deleted, and an empty file is created and served) and the 0-byte-file case (passes validation and serves empty) are named limits, not guarantees.\n- **Suite:** the seed no longer writes the shared file. It still holds a SHARED lock on it for the few seconds the INSERT\u2026SELECT reads it.\n- **Fixture dependencies:** if `dataset` is fixed as in option (a), every test that uses `dataset` also builds the seed, once per lane, including tests that never start an Engine (for example `test_server.py:253`).\n- **Fingerprint gate:** it can go red if the operator's updater runs during the suite.\n- **Unflagged Engines** in `test_random_cache.py` and `test_server_config.py` still open the shared DB read-write. `ensure_trending_schema` is a no-op there because the table exists, so the fingerprint is unaffected.\n</question>\n<question id=\"3\">\n- **Fix `dataset`:** the plan's \"no session test reads `trending_ranks` through `dataset`\" must be corrected. Either `dataset` attaches the private file and shadows `trending_ranks` with the same helper (inventory option (a)), or `_reference` uses such a connection for `trending` (option (b)). Without one of these, criterion 5 fails.\n- **Keep the default branch as is:** the existing `ensure_trending_schema(db)` call at `server.py:337` must still run when the flag is absent.\n- **Keep `ENGINE_START_LOCK`:** it is imported by `test_random_cache.py:44`, `test_server_config.py:39` and the archived test.\n- **Keep the new import in `server.py:110` resolvable:** `test_internal_events.py` and `test_video.py` import `server` in Engine-interpreter children.\n- **Keep `ensure_trending_schema(conn)` unchanged:** `fetch-trending.py:28/102` and four test modules depend on its signature and behaviour.\n- **Keep `TRENDING_SEED_SQL` verbatim:** the private seed must hold the same rows, because the NSFW control at `test_similar.py:998` depends on them.\n</question>\n<question id=\"4\">\n- **Without the flag:** nothing changes. Same SQL, same startup order, same schema call.\n- **With the flag:** Trending and the popular layer read ranks from PATH. PATH gets the schema at startup. The Engine refuses to start (non-zero exit, path named on stderr) on a missing or non-SQLite PATH, and never creates `trending_ranks` in `whitelist.db`.\n- **In the suite:** `trending_seed` returns a path instead of writing the shared DB. The `engine` fixture passes `--trending-db`. With option (a), `dataset` also carries the private ranks: for every query except `trending_ranks` it is the same read-only `whitelist.db` connection. The seed no longer takes the start lock.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nSettled plan, Active suite section (\"No session test reads `trending_ranks` through `dataset`. They only observe the Engine, so `test_similar.py`'s Trending ... expectations still hold\") vs the tree and the settled requirement \"The active suite passes, including the Trending and popular-layer tests in `test_similar`, with no test expectations changed\": `tests/active/test_similar.py:759-766` `_reference` calls `fetch_ordered_page(dataset, order, ...)`, which for `order == \"trending\"` reads the shared `whitelist.db` `trending_ranks` through the `dataset` fixture (`tests/active/conftest.py:228-233`), and line 849 asserts the Engine's pages equal it. Under the plan as written, the `[trending]` case fails whenever the shared table holds a real fill. The plan must add a change to `dataset` (option (a)) or to `_reference` (option (b)). It currently says neither changes. The inventory already carries this as an impact; it is reported here because it contradicts a statement in the settled plan.\n</new_conflicts>\n\n<recommendations>\n1. **Amend the plan to take option (a):** `dataset` depends on `trending_seed`, opens `mode=ro` as today, and calls the same attach-and-view helper the Engine uses (`attach_trending_override(conn, path)` in `data/trending.py`, loaded through the `active_trending_schema` module conftest already builds). `_reference`, `test_similar.py` and every expected value stay untouched. The plan's own fingerprint gate needs this connection anyway (\"merged-rank order computed from the temp file joined with the read-only dataset\"), so one prepared connection serves both. Cost: every test that uses `dataset` triggers the session seed (a few seconds, once per lane), including tests with no Engine. The conftest docstring must say `dataset` carries the private ranks. The ro-connection TEMP view must be shown to work; a one-line control in the fingerprint test covers it. Option (b) instead costs a test-code change to `_reference` and to the docstring at `test_similar.py:64`, and leaves `dataset` and its other users alone. Choose (b) if you want `dataset` to stay the shared file exactly as it is.\n\n2. **Run the flagged-plan check in an Engine-interpreter child as well:** the plan's `EXPLAIN QUERY PLAN` test is in-process under pytest's interpreter, whose SQLite may differ from the Engine's 3.53.4 (pytest's interpreter lacks numpy, per `test_server_config.py:79`). The flattening risk matters only in the Engine. `test_similar.py` already has the child-process pattern (`_FEED_CONSTANTS_CHILD`, `_TRENDING_HANDLER_CHILD`). Cost: one subprocess test of about a second. Skipping it leaves the Engine's actual plan with the flag set unverified.\n\n3. **Identify popular-layer rows with `debug.layer`** (`recommendations/debug.py:23`) on a `debug=1` request, since the session Engine runs `RECOMMENDATIONS_DEBUG=1`. Cost: none. This settles the inventory's open question.\n\n4. **Name the 0-byte-file case in the `--trending-db` help text** next to \"must already exist\", or reject it in validation by checking that the table already exists before the schema runs. The help text costs one line. Rejecting costs a slightly larger helper, and the seed fixture must then create the table first, which it already does.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/trending.py` | Two new functions next to the unchanged `ensure_trending_schema`: `prepare_trending_override(path)` and `attach_trending_override(conn, path)`, plus one constant. |\n| `engine/server/api/server.py` | One new argument in `parse_args`. In `main()`: validate before `connect_db`, then either the unchanged `ensure_trending_schema(db)` or the attach. One conditional log line. The import line grows by two names. |\n| `tests/active/conftest.py` | `trending` is loaded once at module level. New fingerprint helper and fixture. `trending_seed` writes a private temp file. `engine` passes the flag. `dataset` carries the private view (option (a) from the HIGH impact entry). Docstrings rewritten. |\n| `tests/active/test_random_videos.py` | New tests: the plan with the flag set, and flag on vs flag off in-process. Docstring bullets for both. |\n| `tests/active/test_server_config.py` | New subprocess test: `--trending-db` on a missing path or a non-SQLite file. `--help` control. |\n| `tests/active/test_similar.py` | New in-suite gate: the session Engine serves the private ranks (Trending pages and the popular layer), and the shared fingerprint is unchanged. Docstring line 64 updated. |\n| `tests/config.json` | Add `engine/server/data/trending.py` to the `test_server_config.py` group. |\n\nNothing else changes. That includes `random_videos.py` and its SQL, `similar.py`, `popular_videos.py`, `builder.py`, `db.py` (`connect_db` stays non-URI), `moderation.py` and `fetch-trending.py`. `engine/server/README.md` gets no edit because it lists no Engine flags, so `--help` is the documentation. That was the plan's call and I kept it.\n\n## Ladder, per piece\n\n- **Shadowing `trending_ranks`:** a native platform feature is enough (rung 4). A SQLite `ATTACH` plus a `TEMP VIEW` on the existing connection means no SQL and no signature changes.\n- **No-create validation:** stdlib `sqlite3` with a `mode=rw` URI (rung 3). It mirrors the `mode=ro` precedent in `connect_readonly_db`.\n- **Schema on the private file:** reuses `ensure_trending_schema` (rung 2).\n- **Seed:** reuses `TRENDING_SEED_SQL` unchanged and attaches the shared DB read-only (rung 2 plus rung 4).\n- **Test reference for Trending:** reuses `attach_trending_override` on `dataset` (rung 2). `_reference` and every expectation stay as they are.\n- **CLI:** argparse, in the file's existing `help=(...)` style.\n\n## `engine/server/data/trending.py` (additions)\n\n```python\nimport sqlite3  # already imported\n\n# The schema name the --trending-db file is attached under.\nTRENDING_OVERRIDE_SCHEMA = \"trending_override\"\n\n\ndef prepare_trending_override(path: str) -> None:\n    \"\"\"Check that an existing SQLite file is at `path` and apply the trending schema to it, exiting with a message naming the path otherwise.\"\"\"\n    # mode=rw never creates the file, as connect_readonly_db's mode=ro does not; a file that is not SQLite fails on the schema statement.\n    try:\n        conn = sqlite3.connect(f\"file:{path}?mode=rw\", uri=True)\n        try:\n            ensure_trending_schema(conn)\n        finally:\n            conn.close()\n    except sqlite3.Error as exc:\n        raise SystemExit(f\"trending ranks file {path} cannot be opened as SQLite: {exc}\") from exc\n\n\ndef attach_trending_override(conn: sqlite3.Connection, path: str) -> None:\n    \"\"\"Make every unqualified trending_ranks read on `conn` read the table in the file at `path`.\"\"\"\n    conn.execute(f\"ATTACH DATABASE ? AS {TRENDING_OVERRIDE_SCHEMA}\", (str(path),))\n    # Names resolve temp, then main, then attached, so a bare ATTACH leaves main.trending_ranks in front; this TEMP view shadows it, and SQLite flattens it so the Trending page still walks idx_trending_ranks_order.\n    conn.execute(f\"CREATE TEMP VIEW trending_ranks AS SELECT * FROM {TRENDING_OVERRIDE_SCHEMA}.trending_ranks\")\n```\n\n**Invariants:**\n- `ensure_trending_schema(conn)` is byte-for-byte unchanged. `fetch-trending.py`, `server.py` and four test files depend on it.\n- `prepare_trending_override` never creates a file and never touches `whitelist.db`. On any `sqlite3.Error` it raises `SystemExit(str)`. Python prints that message to stderr and exits with status 1, and the message contains `path` verbatim.\n- A 0-byte existing file passes validation and gets the table, so Trending serves empty. The help text says so: \"an empty file counts\".\n- `attach_trending_override` must be called outside a transaction, because ATTACH fails inside one. Its two callers both call it on a connection that has no open transaction:\n  - `server.main()`, right after the `executescript`-based ensures, which commit first;\n  - the `dataset` fixture, on a fresh connection.\n- It works on a `mode=ro` URI connection. The attached file inherits the connection's read-only open flags, and the temp schema is opened read-write regardless (SQLite opens the temp DB with its own READWRITE|CREATE flags). I reasoned this from SQLite's behaviour and have not run it. The `dataset` fixture fails loudly if it is wrong.\n- The `path` given to ATTACH is a bound parameter, so it needs no quoting. On a non-URI connection a plain path is taken literally. On a URI connection a plain path that does not begin with `file:` is also taken literally.\n- **Named ceiling: URI escaping.** A PATH containing `?` or `#` is not URI-escaped in the validation open, so it fails validation (loudly) instead of opening. That is the same ceiling as `connect_readonly_db`. The way up is `urllib.parse.quote` on the path.\n\n## `engine/server/api/server.py`\n\nImport at line 110:\n\n```python\nfrom data.trending import attach_trending_override, ensure_trending_schema, prepare_trending_override\n```\n\nIn `parse_args`, after the `refresh_group` block and before `parser.set_defaults(random_cache_refresh=None)`:\n\n```python\n    parser.add_argument(\n        \"--trending-db\",\n        metavar=\"PATH\",\n        default=None,\n        help=(\n            \"Dev/test override: read only the trending_ranks table from PATH; every other \"\n            \"table still comes from whitelist.db. PATH must be an existing SQLite file (an \"\n            \"empty file counts) and is never created; the table and its index are created \"\n            \"in it if missing. A relative PATH resolves against the working directory.\"\n        ),\n    )\n```\n\nWith `metavar=\"PATH\"`, `--help` renders `--trending-db PATH`, and the test asserts that string.\n\nIn `main()`, lines 332-339 become:\n\n```python\n    if args.trending_db is not None:\n        # Before whitelist.db is opened, so a bad path stops the start without touching it or loading the index.\n        prepare_trending_override(args.trending_db)\n    db = connect_db(db_path)\n    search_db = connect_readonly_db(db_path)\n    ensure_moderation_schema(db)\n    ensure_interaction_event_schema(db)\n    if args.trending_db is None:\n        # Created empty before the first fill, so a Trending read is an empty page, never \"no such table\".\n        ensure_trending_schema(db)\n    else:\n        # The shared trending_ranks is neither created nor read on this connection; the file at PATH stands in for it.\n        attach_trending_override(db, args.trending_db)\n    ensure_channels_indexes(db)\n    ensure_video_indexes(db)\n```\n\nAfter the `db=%s index=%s` log line (494), add:\n\n```python\n    if args.trending_db is not None:\n        logging.info(\"[similar-server] trending_db=%s (trending_ranks only)\", args.trending_db)\n```\n\n**Why this order:**\n- Validation runs before `connect_db`, so a bad path exits in under a second. Nothing has opened `whitelist.db` at that point and FAISS has not loaded.\n- The attach goes after the two `executescript` ensures, so no transaction is open.\n- The later `ensure_channels_indexes` and `ensure_video_indexes` create unqualified indexes on main tables and probe `sqlite_master`, which is main-only. The private file holds neither table, so they are unaffected.\n- `search_db` and the random-cache worker's own connection read no `trending_ranks`, so they get no view.\n- `server.db` is assigned once (`SimilarServer.__init__:242`), so the view lasts as long as the process.\n\n**Default path:** the unflagged branch runs the same statements in the same order as today. The only differences are the `if`, which is not taken, and the second `if`, whose true branch is the original line 337. The SQL and the plans are unchanged.\n\n## `tests/active/conftest.py`\n\nModule level, replacing the lazy spec load inside `trending_seed`:\n\n```python\n_TRENDING_SPEC = importlib.util.spec_from_file_location(\"active_trending_schema\", ROOT / \"engine\" / \"server\" / \"data\" / \"trending.py\")\nTRENDING = importlib.util.module_from_spec(_TRENDING_SPEC)\n_TRENDING_SPEC.loader.exec_module(TRENDING)\n# The shared trending_ranks fingerprint: rows, fetched_at bounds and real-fill rows; main. so a connection carrying the private view still reads the shared table.\nTRENDING_FINGERPRINT_SQL = \"SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at), COUNT(CASE WHEN fetched_at > 0 THEN 1 END) FROM main.trending_ranks\"\n\n\ndef shared_trending_fingerprint() -> tuple:\n    \"\"\"The shared whitelist.db trending_ranks fingerprint, read on a fresh read-only connection.\"\"\"\n    conn = sqlite3.connect(f\"file:{WHITELIST_DB}?mode=ro\", uri=True)\n    try:\n        return tuple(conn.execute(TRENDING_FINGERPRINT_SQL).fetchone())\n    finally:\n        conn.close()\n\n\n@pytest.fixture(scope=\"session\")\ndef shared_trending_before():\n    \"\"\"The shared fingerprint before the private seed is built and the session Engine starts.\"\"\"\n    return shared_trending_fingerprint()\n```\n\nThe comment above `TRENDING_SEED_SQL` (line 107) changes its ending to: \"...deterministic, so every lane's private file holds the same rows.\" `TRENDING_SEED_SQL` itself is unchanged.\n\n```python\n@pytest.fixture(scope=\"session\")\ndef trending_seed(tmp_path_factory, shared_trending_before):\n    \"\"\"A per-session private trending_ranks file the session Engine reads through --trending-db, so its Trending order has rows without the network fetch and the shared whitelist.db is never written.\n\n    The catalogue is read from whitelist.db attached read-only; the only file written is this one.\n    \"\"\"\n    path = tmp_path_factory.mktemp(\"trending\") / \"trending.db\"\n    # A URI connection, so the shared DB attaches with mode=ro rather than as a literal filename.\n    conn = sqlite3.connect(f\"file:{path}\", uri=True)\n    try:\n        TRENDING.ensure_trending_schema(conn)\n        conn.execute(\"ATTACH DATABASE ? AS shared\", (f\"file:{WHITELIST_DB}?mode=ro\",))\n        # trending_ranks resolves to this file's main, ahead of the attached copy; videos and video_embeddings exist only in the shared DB.\n        with conn:\n            conn.execute(TRENDING_SEED_SQL)\n    finally:\n        conn.close()\n    return path\n```\n\n`shared_trending_before` appears as a parameter only to order the fixtures: pytest then reads the fingerprint before the seed and the Engine.\n\n`engine` fixture: the argv becomes\n\n```python\n                    [str(ENGINE_PY), str(ENGINE_SERVER), \"--host\", \"127.0.0.1\", \"--port\", str(port),\n                     \"--no-random-cache-refresh\", \"--trending-db\", str(trending_seed)],\n```\n\n`ENGINE_START_LOCK` and the retry loop stay. Comment line 156 gains: \"Trending is read from the private seed file (--trending-db), never the shared table.\"\n\n`dataset` fixture:\n\n```python\n@pytest.fixture(scope=\"session\")\ndef dataset(trending_seed):\n    conn = sqlite3.connect(f\"file:{WHITELIST_DB}?mode=ro\", uri=True)\n    conn.row_factory = sqlite3.Row\n    # Trending reads the session Engine's private ranks here too, so a reference order computed on this connection is the one the Engine serves.\n    TRENDING.attach_trending_override(conn, trending_seed)\n    yield conn\n    conn.close()\n```\n\n**Module docstring, lines 6-11, rewritten:** `engine` starts the real Engine from its pixi env on the repo's dataset, once per session, the way `tests/run-arch-split-smoke.sh` does but with `--trending-db` naming `trending_seed`'s per-session private file, so the suite never writes the shared `trending_ranks`. `engine_client` and `unpublished_client` are as before. `dataset` is `whitelist.db` opened read-only with that private file attached and shadowing `trending_ranks`, so it is the independent source of a video's channel, account and embedding, and of the Trending order the session Engine serves. `shared_trending_fingerprint` reads the shared table's fingerprint.\n\n**Kept:** the `ENGINE_START_LOCK` constant, which three importers use, and the `fcntl` and `tempfile` imports, which are still used.\n\n## Tests: what each one gates\n\n**1. `test_random_videos.py` (in-process, pytest interpreter).** It imports `attach_trending_override` and `prepare_trending_override` from `data.trending`.\n\n- **`test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`**\n  - Setup: `_schema(main.db)` gets the same 30\u00d7100 ranked catalogue plus 1,000 unranked rows as the existing plan test, built by a shared local builder factored from that test. Its `main.trending_ranks` is left empty. The ranks are written into `private.db` after `prepare_trending_override`. `attach_trending_override(conn, private)`.\n  - Assertions: `_plan(conn, \"trending\")` contains `idx_trending_ranks_order` and no `TEMP B-TREE`. The control is that `_plan(conn, \"popular\")` contains `TEMP B-TREE`.\n  - The existing unflagged plan test stays as it is.\n- **`test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`**\n  - Setup: main is `_ranks_db` (ranks A, giving `TRENDING_EXPECTED`). The private file gets the same keys with ranks B, a hand-derived different order, for example `TRENDING_EXPECTED` reversed, written as rank 1..n with equal likes and views.\n  - A plain connection on main serves A through `fetch_ordered_page(..., \"trending\", ...)` and `fetch_popular_videos`. A second connection on the same main file, prepared with `attach_trending_override`, serves B for both.\n  - Afterwards `main.trending_ranks` rows are unchanged, read on the plain connection.\n  - Control: A \u2260 B.\n- **Docstring:** two new bullets in the claim style.\n- **Interpreter note:** this runs under pytest's `sqlite3`, not the Engine's 3.53.4, as the existing plan test also does. The Engine-side plan is covered indirectly by test 3: deep pages on the session Engine succeed within the 5 s deadline.\n\n**2. `test_server_config.py::test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`** (subprocess, no start lock).\n\n- **Missing path:** `_run([str(ENGINE_PY), str(API_DIR / \"server.py\"), \"--port\", str(_free_port()), \"--trending-db\", str(missing)], None)` with `missing = tmp_path / \"absent.db\"`. Expect `returncode != 0`, `str(missing)` in stderr, and `not missing.exists()`.\n- **Non-SQLite file:** the same call on `tmp_path / \"junk.db\"` containing 4 KB of non-SQLite bytes. Expect non-zero, the path in stderr, and the file bytes unchanged.\n- **Control:** `server.py --help` exits 0 and its stdout contains `--trending-db PATH`.\n- **Timing:** a red start would load FAISS and bind. The test bounds `_run`'s timeout and fails if the process is still alive. `_run` already uses `timeout=120`, and validation runs before `connect_db`, so the expected run time is about 1 s.\n\n**3. `test_similar.py::test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(engine, dataset, shared_trending_before)`**\n\n- **Discrimination control:** the shared head (`fetch_ordered_page` on a fresh plain `mode=ro` connection, first `3 * FEED_PAGE`) differs from `_reference(dataset, \"trending\", threshold)`. If they are equal, the failure message says the shared table holds no real fill, so this test cannot tell the two sources apart.\n- **Trending pages:** three `mode=trending` pages, walked with `exclude` as in the existing ordered test, equal `_reference(dataset, \"trending\", ...)[: 3 * FEED_PAGE]`.\n- **Popular layer:** an unseeded home request (`POST /recommendations?limit=<page>&debug=1`, body `{}`, its own rate-bucket header). Every row with `debug.layer == \"popular\"` must lie in `fetch_popular_videos(dataset, POOL)`, the private head. `POOL` is the Engine's `DEFAULT_POPULAR_POOL_SIZE`, read in the Engine-interpreter child that `_feed_constants` already runs (one more key). Control: at least one popular row is served.\n- **Fingerprint:** `shared_trending_fingerprint() == shared_trending_before`. The failure message names an operator updater run (the trending stage) as a possible external cause.\n- **Docstring line 64:** the ordered-feed reference is read through `dataset`, which carries the session's private Trending ranks.\n\n**4. Existing tests, unchanged expectations:**\n- `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` now compares the Engine with `dataset`, and both read the private file.\n- The NSFW control at 1043 reads the same seeded rows.\n\n**5. Build-level, not a test.** Before the build's full suite run, record `shared_trending_fingerprint()` with a one-shot `python -c` against `whitelist.db` `mode=ro`, and compare after. It must be identical, with `count(fetched_at > 0)` > 0.\n\n## Checked against requirements and plan\n\n| Requirement | Met by |\n|---|---|\n| Flag in `--help`, existing style | `parse_args` addition, `metavar=\"PATH\"` |\n| Every `server.db` Trending read uses PATH | TEMP view resolves before main for `fetch_ordered_page` and `fetch_popular_videos`. No other connection reads `trending_ranks`. |\n| No write to shared `trending_ranks`, including at startup | `ensure_trending_schema(db)` is skipped when flagged. The schema goes to PATH in `prepare_trending_override`. The Engine has no purge path. |\n| Missing or non-SQLite PATH: non-zero exit, path in message, no file created | `mode=rw` open plus schema statement \u2192 `SystemExit(...path...)` before `connect_db`. Test 2. |\n| Default unchanged; plan uses the index with no TEMP B-TREE, with and without the flag | Unflagged branch is the original statements. Existing plan test plus test 1. |\n| Private seed with identical rows, shared read-only, only the temp file written | `trending_seed` uses verbatim `TRENDING_SEED_SQL`, shared attached `mode=ro` |\n| Seed drops the lock, `engine` keeps it, constant stays | as drafted |\n| Docstrings updated | module, `trending_seed`, `engine` comment, `dataset` comment, line-107 comment, `test_similar` line 64, `test_random_videos` bullets |\n| In-suite fingerprint gate plus build before/after | test 3, step 5 |\n| Suite green with no expectation changed | option (a): `dataset` carries the view, `_reference` untouched |\n\n## Decisions and deviations\n\n**The settled plan was wrong about `dataset`.** It said no session test reads `trending_ranks` through `dataset`. The impact inventory's HIGH entry showed that `test_similar._reference` does. I took option (a): `dataset` depends on `trending_seed` and carries the same view. It reuses the one helper, changes no test code or expectations, and costs one session seed per lane, which `engine` already pays.\n\n**Named limitations:**\n- **Validation-to-ATTACH race.** If the file vanishes in between, plain ATTACH on non-URI `server.db` creates it empty, and Trending then serves empty, never shared. The way up is a URI-enabled `connect_db`.\n- **Unescaped `?` or `#` in PATH.** These fail validation instead of opening.\n- **Reliance on the query flattener.** This is gated by test 1.\n- **SHARED lock during the seed.** The seed holds a SHARED lock on the shared file for a few seconds, which can delay but not block a writer.\n- **External changes during a run.** The fingerprint gate goes red if the operator's updater changes the shared ranks mid-run. Its message names that cause.\n\n**Not done:**\n- No README edit, because it has no flag list.\n- No `UPDATER_WORKER.md` edit, because line 101 stays true for every production start.\n- No URI escaping helper.\n- No logging change other than one conditional line.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the public functions in `engine/server/data/random_videos.py` (`fetch_ordered_page`, `fetch_popular_videos`) plus `attach_trending_override` and `prepare_trending_override` from `data.trending`. The test calls them in-process, on temp SQLite files (rung 1). It follows the existing harness in `tests/active/test_random_videos.py`: `_schema`, `_ranks_db`, `_plan`, and `test_a_trending_page_walks_the_ranks_index_without_sorting`. Two tests. (a) `test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`: main holds ranks A (`TRENDING_EXPECTED`) and the private file holds the same keys with ranks B, a hand-derived different order (e.g. reversed). A plain connection must serve A from both `fetch_ordered_page(..., \"trending\", ...)` and `fetch_popular_videos`. A second connection on the same main, prepared with `attach_trending_override`, must serve B from both. After both reads, `main.trending_ranks` rows must equal what was written. Control: assert A != B. (b) `test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`: main gets the 30\u00d7100 ranked catalogue plus 1,000 unranked rows, built by a builder factored out of the existing plan test, and its `main.trending_ranks` is left empty. The private file gets `prepare_trending_override` and then the ranks. On the prepared connection, `_plan(conn, \"trending\")` must contain `idx_trending_ranks_order` and no `TEMP B-TREE`. Control: `_plan(conn, \"popular\")` contains `TEMP B-TREE`. The existing unflagged plan test stays as it is.</checkpoint>\n<name>Trending override helpers</name>\n<intent>`engine/server/data/trending.py` gains `TRENDING_OVERRIDE_SCHEMA`, `prepare_trending_override` and `attach_trending_override`. A connection prepared by `attach_trending_override` takes every unqualified `trending_ranks` read from the attached file, not from main, and its Trending page is still planned as a walk of `idx_trending_ranks_order` with no sort.</intent>\n<clause_1>On a connection prepared by `attach_trending_override`, `fetch_ordered_page` for `trending` and `fetch_popular_videos` serve the attached file's ranks. On an unprepared connection to the same main they serve main's ranks, and main's ranks are left unchanged.</clause_1>\n<clause_2>On a connection prepared by `attach_trending_override`, the Trending page's query plan uses `idx_trending_ranks_order` and contains no `TEMP B-TREE`.</clause_2>\n<files>engine/server/data/trending.py (EDITED), tests/active/test_random_videos.py (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the real Engine entry point `engine/server/api/server.py`, run as a subprocess under the Engine interpreter (rung 2) through `test_server_config._run`. This follows `test_server_config.py`'s existing entry-point tests (e.g. `test_server_py_exits_before_argument_parsing_on_a_bad_value`). There is no start lock, because the start must fail before `connect_db`. Test `test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`. Missing case, `tmp_path / \"absent.db\"`: assert `returncode != 0`, assert `str(missing)` is in stderr, and assert `not missing.exists()`. Non-SQLite case, `tmp_path / \"junk.db\"` holding 4 KB of non-SQLite bytes: assert `returncode != 0`, assert the path is in stderr, and assert the file's bytes are unchanged. The timeout is bounded, so a start that wrongly proceeds to load FAISS or bind goes red, not hung. Control: `server.py --help` exits 0 and its stdout contains `--trending-db PATH`. The `tests/config.json` `test_server_config.py` group gains `engine/server/data/trending.py`.</checkpoint>\n<name>Engine --trending-db flag</name>\n<intent>`engine/server/api/server.py` accepts `--trending-db PATH`. `main()` validates PATH before it opens `whitelist.db`, so a PATH that is not an existing SQLite file stops the start, with a message naming it, and leaves the path as it was.</intent>\n<clause_1>Starting `server.py` with `--trending-db` on a missing path or a non-SQLite file exits non-zero, with that path in stderr.</clause_1>\n<clause_2>The failed start leaves the path as it was: a missing path is not created, and a non-SQLite file's bytes are unchanged.</clause_2>\n<files>engine/server/api/server.py (EDITED), tests/active/test_server_config.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the real session Engine over HTTP, through the `engine` fixture in `tests/active/conftest.py`, now started with `--trending-db <trending_seed>`. It follows `test_similar.py`'s existing `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` and its `_reference(dataset, ...)`. Test `test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(engine, dataset, shared_trending_before)`. Discrimination control: on a fresh plain `mode=ro` connection, the shared head (`fetch_ordered_page`, first `3 * FEED_PAGE`) differs from `_reference(dataset, \"trending\", threshold)`. If they are equal, the message says the shared table has no real fill. Trending: three `mode=trending` pages, walked with `exclude`, must equal `_reference(dataset, \"trending\", ...)[: 3 * FEED_PAGE]`. Popular layer: an unseeded `POST /recommendations?debug=1` with its own rate-bucket header. Every row with `debug.layer == \"popular\"` must be in `fetch_popular_videos(dataset, POOL)`, with `POOL` read through `_feed_constants` from the Engine's `DEFAULT_POPULAR_POOL_SIZE`. Control: at least one popular row is served. Fingerprint: `shared_trending_fingerprint() == shared_trending_before`, and the failure message names an updater trending-stage run as a possible external cause. The existing ordered-feed and NSFW tests stay green with unchanged expectations.</checkpoint>\n<name>Active suite on a private Trending seed</name>\n<intent>The active suite's session Engine reads Trending from a per-session private file. `trending_seed` builds that file from the read-only shared catalogue, `engine` passes it as `--trending-db`, and `dataset` carries it, so the suite serves the seeded order without ever writing the shared `whitelist.db` `trending_ranks`.</intent>\n<clause_1>The session Engine's Trending pages and its popular-layer rows follow the private seed file's ranks, not the shared table's.</clause_1>\n<clause_2>The shared `whitelist.db` `trending_ranks` fingerprint (row count, `fetched_at` min and max, rows with `fetched_at > 0`) is identical before the seed and after the session Engine has served.</clause_2>\n<files>tests/active/conftest.py (EDITED), tests/active/test_similar.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nPhase 3 needs no credential or live endpoint. It does depend on local operator state. The local `whitelist.db` must hold a real `trending_ranks` fill (more than 0 rows with `fetched_at > 0`; triage found 86,826), or the discrimination control fails by design. The operator's updater trending stage must not run during the suite run, or the fingerprint gate goes red for a reason outside the suite. The same applies to the build-level before/after fingerprint around the full suite run.\n</needs_coordination>\n\n<rationale>\nThe phases split along the drafted module map's natural layers, bottom-up, so each phase's checkpoint enters at the lowest layer it changes. Phase 1 is the mechanism: the TEMP-view shadowing and the reliance on the query flattener. It is proven in-process at the `random_videos` function seam, where the existing plan and rank harness already lives, so a flattener regression points straight at the helper. Phase 2 is the entry-point contract: validation before `connect_db`, non-zero exit, path in stderr, no file created. That can only be observed through the real CLI, so it is a subprocess test via the existing `_run` harness. The `tests/config.json` group entry goes here because it maps `trending.py` onto that test group. Phase 3 is where the suite switches over: seed, `engine` argv, and `dataset` carrying the view (option (a), the deviation the implementation step recorded). It depends on both earlier phases, and only the real session Engine can show the served order and the untouched shared table. Each Intent cuts into exactly two clauses. The `--help` listing and the A\u2260B or shared\u2260private checks are controls inside the clauses, not clauses of their own. There is no prose phase: the only text changes are code docstrings and comments, which land with their phases, and the README is deliberately not edited. Two things are deliberately not phases. The build-level before/after fingerprint (drafted step 5) is a build action, not a test. The Engine-interpreter flagged plan is covered only indirectly, because test 1 runs under pytest's sqlite3, as the existing plan test does; deep pages on the session Engine must still finish within the deadline. The operator approved the plan as presented.\n</rationale>",
    "author:tests/tmp/test_44_trending_seed_write_lock_during_phase1.py": "<items>\n<item id=\"D15\">\n<disposition>justified</disposition>\n<what>I cut the sentence back to what the helper actually does. The `_private_file` docstring at :29 used to say the file is given the trending schema \"by `prepare_trending_override`, which never creates one\". It now says \"An empty file touched at `path`, then given the trending schema by `prepare_trending_override`.\" Nothing in this file calls prepare on a missing path, so the claim had nothing behind it, and I have not seen how a missing path fails under the real helper. The probe saw that the plan's `mode=rw` body raises OperationalError, but that was the plan's body, not the helper. The new sentence is one line, so no other line moved and every assertion line number in the ledger still holds. The schema half of the sentence is still carried by :98 and :105, the same as D14.</what>\n</item>\n</items>\n\n<findings_addressed>\nThere were no CRITICAL findings from either auditor. Claim recommendation 1 (D15 uncarried): taken. I narrowed the `_private_file` docstring at :29 to what the helper does: it touches the file, then prepares it. Claim recommendations 2 and 3 (failure paths, and a prepared file with no rows): left. Neither the clauses nor the phase say what the helpers should do on a missing path or an empty override file, so any expected value I wrote would be a guess.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1a\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:84 \u2014 on the prepared connection, fetch_ordered_page(prepared, \"trending\", 100, 0) labels equal OVERRIDE_EXPECTED</assertion>\n<expected>[\"B5\", \"A3\", \"E\", \"A2\", \"C2\", \"B2\", \"A1\", \"B1\", \"X\", \"C1\"]</expected>\n<wrong_implementation>A bare ATTACH with no shadowing leaves main.trending_ranks resolved first. It serves TRENDING_EXPECTED (the reverse order), and the probe saw this fail.</wrong_implementation>\n</row>\n<row clause=\"C1b\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:85 \u2014 on the prepared connection, fetch_popular_videos(prepared, 100) labels equal OVERRIDE_EXPECTED</assertion>\n<expected>OVERRIDE_EXPECTED</expected>\n<wrong_implementation>An override that reaches the page read but misses the pool, or a bare ATTACH. Either one serves TRENDING_EXPECTED.</wrong_implementation>\n</row>\n<row clause=\"C1c\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:70 and :86 \u2014 on the plain connection, fetch_ordered_page \"trending\" labels equal TRENDING_EXPECTED, both before the override exists and after the prepared connection has read</assertion>\n<expected>[\"C1\", \"X\", \"B1\", \"A1\", \"B2\", \"C2\", \"A2\", \"E\", \"A3\", \"B5\"]</expected>\n<wrong_implementation>An attach that copies the file's ranks into main.trending_ranks, or that switches the source for every connection. Under it, :86 serves OVERRIDE_EXPECTED; the probe saw it fail with 'B5' != 'C1'.</wrong_implementation>\n</row>\n<row clause=\"C1d\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:71 \u2014 on the plain connection, fetch_popular_videos(plain, 100) labels equal TRENDING_EXPECTED</assertion>\n<expected>TRENDING_EXPECTED</expected>\n<wrong_implementation>A pool that does not read main's trending_ranks order. It serves the catalogue in some other order.</wrong_implementation>\n</row>\n<row clause=\"C1e\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:87 \u2014 sorted rows of main.trending_ranks equal `written`, which line 68 rebuilds from harness.RANKS</assertion>\n<expected>The 12 ranked RANKS rows (GHOST and U included), as (host, video_id, rank, likes, views, 0)</expected>\n<wrong_implementation>A committed copy, delete or rewrite of main.trending_ranks by prepare or attach. Under it, main holds the file's ranks or no rows, which differs from `written`.</wrong_implementation>\n</row>\n<row clause=\"C2a\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:105 \u2014 the prepared connection's Trending EXPLAIN QUERY PLAN names idx_trending_ranks_order. It is armed by :95 (main is empty) and by the full 50-row page check inside _plan at :104</assertion>\n<expected>A detail like 'SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order'</expected>\n<wrong_implementation>A temp copy of the ranks, or a view that loses the index. The plan reads 'SCAN t' with no index name, as the probe saw.</wrong_implementation>\n</row>\n<row clause=\"C2b\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:106 \u2014 the prepared connection's Trending plan has no 'TEMP B-TREE' detail. The Popular plan control at :102 shows the capture can surface a sort</assertion>\n<expected>No detail contains TEMP B-TREE</expected>\n<wrong_implementation>An unindexed shadow table. It plans 'SCAN t' plus 'USE TEMP B-TREE FOR ORDER BY', as the probe saw.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Each negative assertion has a positive control. :106 (no TEMP B-TREE) is paired with :105, which needs the index, with :102, which shows the capture can see a sort, and with _plan's full-page check at :104. If the code under test is deleted, both tests fail with AttributeError at :31.\n2. No. Every expected order and row set is a literal or is rebuilt from RANKS, not computed by the code under test. Deleting the shadowing of trending_ranks in attach_trending_override turns :84 and :85 red. Deleting the index creation in prepare_trending_override turns :105 red.\n3. No. Each read is checked on two connections that should differ, plain and prepared. The two orders are proven to differ by :67, and the plain reads are checked both before and after the override.\n4. No. There are no doubles. The test uses the real data.random_videos and data.trending, real SQLite files, and the project's own harness loaded by path.\n5. Yes, it collects. This round I changed only one docstring line. The run collected 2 tests, and both failed at :31 on the missing helper.\n6. Yes, they come from a run. Every expected order and plan detail was seen in the earlier probe. This round's edit is prose only.\n7. Yes. After the edit, ValidateTests [\"tests/tmp/test_44_trending_seed_write_lock_during_phase1.py\", \"-v\"] gave 2 failed. Both raised `AttributeError: module 'data.trending' has no attribute 'prepare_trending_override'` at :31, reached from :72 and :96. That is the expected red before phase 1 is built.\nNone of the seven answers was a yes, so nothing was rewritten. The only edit is the D15 docstring narrowing.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_44_trending_seed_write_lock_during_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_44_trending_seed_write_lock_during_phase1.py:84 and :85 \u2014 on the connection prepared by `trending.attach_trending_override`, the labels of `fetch_ordered_page(prepared, \"trending\", 100, 0)` and of `fetch_popular_videos(prepared, 100)` each equal `OVERRIDE_EXPECTED`</assertion>\n<expected>`['B5', 'A3', 'E', 'A2', 'C2', 'B2', 'A1', 'B1', 'X', 'C1']` from both reads. I re-ran `tests/tmp/probe_override.py -s` this turn. It hand-rolls the planned ATTACH + `CREATE TEMP VIEW trending_ranks` on the same fixtures, and it printed \"view page\" and \"view pool\" as this exact list.</expected>\n<wrong_implementation>A bare `ATTACH` with no shadowing view leaves `main.trending_ranks` first in name lookup. In the probe, \"bare attach page\" printed `['C1', 'X', 'B1', 'A1', 'B2', 'C2', 'A2', 'E', 'A3', 'B5']`, which is `TRENDING_EXPECTED`, so both assertions go red. An override that reaches only one of the two reads leaves the other one red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_44_trending_seed_write_lock_during_phase1.py:70, :71 and :86 \u2014 on the plain connection to the same main, the Trending page and the popular pool equal `harness.TRENDING_EXPECTED` before the override, and the Trending page still equals it after the prepared connection has read</assertion>\n<expected>`['C1', 'X', 'B1', 'A1', 'B2', 'C2', 'A2', 'E', 'A3', 'B5']` each time. The probe printed it for \"plain page\", \"plain pool\" and \"plain after\", the last read taken after the view connection had served. In this turn's checkpoint run, :70 and :71 passed before the failure at :72.</expected>\n<wrong_implementation>An override that copies the file's ranks into `main.trending_ranks`, or one that changes the Trending source for every connection (for example by rewriting `ORDERED_FEED_SOURCE`), makes the plain read at :86 come back as `OVERRIDE_EXPECTED`.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_44_trending_seed_write_lock_during_phase1.py:87 \u2014 `sorted(SELECT * FROM main.trending_ranks)` on the plain connection equals `written`, which is the ranked RANKS rows `_ranks_db` inserted, restated at :68 from the fixture</assertion>\n<expected>The 12 tuples the probe printed under \"main rows\" after the view connection had read, from `('a.example', 'a1', 1, 50, 100, 0)` through `('f.example', 'g1', 1, 999, 999, 0)`. Its positive control is :84/:85, which show the override actually served from the file first.</expected>\n<wrong_implementation>An override that writes the file's ranks into main (`DELETE` then `INSERT ... SELECT` from the attached schema) leaves main holding ranks 1..10 at likes and views of 10 instead of the written rows, so the comparison fails.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_44_trending_seed_write_lock_during_phase1.py:105 \u2014 some EXPLAIN QUERY PLAN detail of the prepared connection's Trending page statement (`harness._plan(prepared, \"trending\")`, a filtered 50-row page at offset 100 that `_plan` asserts came back full) contains `idx_trending_ranks_order`</assertion>\n<expected>The probe printed this \"view trending plan\" on the same 4,000-row fixture: `['SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order', 'SEARCH v USING INDEX sqlite_autoindex_videos_1 (...)', 'SEARCH e ...', 'SEARCH c ... LEFT-JOIN']`.</expected>\n<wrong_implementation>A shadow that SQLite cannot flatten onto the file's indexed table, such as an unindexed TEMP copy of the file's ranks, planned `SCAN t` with no index name in the probe (\"unindexed temp copy trending plan\"), so :105 goes red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_44_trending_seed_write_lock_during_phase1.py:106 \u2014 no detail of that same Trending plan contains `TEMP B-TREE`. The control at :102 arms it: the same capture for Popular on the prepared connection does contain `TEMP B-TREE`</assertion>\n<expected>The probe's \"view trending plan\" quoted above has no `USE TEMP B-TREE FOR ORDER BY`. Its \"view popular plan\" ends in `USE TEMP B-TREE FOR ORDER BY`, so the capture is able to show a sort.</expected>\n<wrong_implementation>The unindexed temp copy planned `['SCAN t', ..., 'USE TEMP B-TREE FOR ORDER BY']` in the probe. Any override source that loses the ordered index walk sorts, and :106 goes red.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. Each docstring bullet has an assertion behind it. Bullet 1: :70/:71 (plain reads), :84/:85 (prepared reads), :86 (plain read afterwards) and :87 (main as written). Bullet 2: :95 (main's own ranks are empty), `_plan`'s full-50-row-page control, :102 (Popular sorts), :105 (index named) and :106 (no sort). Both clauses are fully carried. No rewrite.\n2. Absence only: no. :106 (no TEMP B-TREE) is armed by :102 on the same prepared connection. :87 (main unchanged) is armed by :84/:85, which show the override actually served from the file before main is read back. :95 (an empty page) is a control and judges no code.\n3. Echoed literal: no. `OVERRIDE_EXPECTED` is the order the test writes to the file, and `TRENDING_EXPECTED` is the harness's hand-derived order; neither is computed by production. `written` is restated from the RANKS fixture. Deleting the `CREATE TEMP VIEW trending_ranks ...` line in `attach_trending_override` turns :84/:85 red: the probe's bare ATTACH served `TRENDING_EXPECTED`. Losing the flattening onto the file's indexed table turns :105/:106 red.\n4. One value: no. Each read is a 10-row order whose rows are the same in both sources, and only the order differs (control :67). The same reads are compared across two sources, two connections, and before and after the override. The plan is read on a 4,000-row DB at offset 100, beside a Popular control.\n5. The double: no. There are no doubles. The test uses real `random_videos`, `data.trending` and SQLite on temp files. The harness's `_Recorder` only wraps the real connection to capture the SQL it runs.\n6. It collects: yes. The run reports \"collected 2 items\", which matches the 2 tests written. `_ranks_db`, `_schema`, `_plan`, `_trending_labels`, `RANKS` and `TRENDING_EXPECTED` exist in tests/active/test_random_videos.py (read at lines 91\u2013219). `compute_ann_id` resolves from `data.ann_ids`. The `--collect-only` summary's \"no tests\" is that runner's display of zero outcomes. The real run collected both.\n7. Observed, not predicted: yes, all observed. This turn I re-ran `tests/tmp/probe_override.py -s`, which emulates the planned ATTACH + TEMP VIEW. It printed TRENDING_EXPECTED for \"plain page\", \"plain pool\", \"plain after\" and \"bare attach page\". It printed OVERRIDE_EXPECTED for \"view page\" and \"view pool\". \"main rows\" was the 12 written tuples, and \"bare attach page len 0\" covered fixture (b). The view Trending plan was `SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order` with no TEMP B-TREE. The view Popular plan ended in `USE TEMP B-TREE FOR ORDER BY`, and an unindexed temp copy gave `SCAN t ... USE TEMP B-TREE FOR ORDER BY`. The previous turn left one premise unobserved: that `_private_file`'s touched 0-byte file accepts the schema through a `mode=rw` open. I added `test_probe_touched_file` and ran it: \"touched file size 16384 tables [('index', 'idx_trending_ranks_order'), ('index', 'sqlite_autoindex_trending_ranks_1'), ('table', 'trending_ranks')]\". Not observable until the phase exists: the real `prepare_trending_override`/`attach_trending_override` bodies. The probe emulates the plan's two statements for them. The probe file `tests/tmp/probe_override.py` is still on disk because I have no delete tool, so it needs removing. It is not named `test_*`, so it is not collected as a checkpoint.\n8. Red, not green: yes, it is red. `ValidateTests` on the checkpoint printed \"2 failed\", \"[exit status 1]\", \"collected 2 items\".\n9. Red for the right reason: yes. In both tests, every control that needs no phase code passed first: :67, :70 and :71 in test 1, and :95 in test 2. Both then failed at tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31, `trending.prepare_trending_override(str(path))`, reached from :72 and :96, with \"E       AttributeError: module 'data.trending' has no attribute 'prepare_trending_override'\". This is not a control assertion and not a typo. `prepare_trending_override` (and `attach_trending_override`) are the functions this phase adds to engine/server/data/trending.py, which currently holds only `ensure_trending_schema`. The test cannot reach C1/C2's judging assertions until they exist.\n10. Observed expected output: every `expected` column states what the probe printed this turn. :70/:71 also passed in the checkpoint run itself. The checkpoint run stopped at :31, so for :84\u2013:87, :102, :105 and :106 the evidence is the probe's emulation of the planned mechanism, not the checkpoint run. Nothing in either run contradicted a row. No rewrite.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/server/data/trending.py`\n`ensure_trending_schema` is unchanged. Three additions sit next to it, following the plan's draft:\n- `TRENDING_OVERRIDE_SCHEMA = \"trending_override\"`: the schema name the override file is attached under.\n- `prepare_trending_override(path)`: opens `file:{path}?mode=rw` with `uri=True`, so a missing file is never created, runs `ensure_trending_schema` on it, and closes the connection. Any `sqlite3.Error` becomes `SystemExit` with a message that names the path. A `rat-tail:` comment records the limit: the path is not URI-escaped, so a `?` or `#` in it fails here, and the fix is `urllib.parse.quote`.\n- `attach_trending_override(conn, path)`: runs `ATTACH DATABASE ? AS trending_override` with the path as a bound parameter, then `CREATE TEMP VIEW trending_ranks AS SELECT * FROM trending_override.trending_ranks`. One comment explains why the view is needed: SQLite looks up names in temp, then main, then attached databases, and it flattens the view. A `rat-tail:` comment records the race: on a non-URI connection, ATTACH would recreate a file deleted after the prepare step as an empty file.\n\nWhat I saw in a probe (pytest's sqlite 3.53.4, the same version as the Engine's): with the override attached, the Trending query's plan is `SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order` followed by `SEARCH e USING COVERING INDEX ...`, with no `TEMP B-TREE`. `prepare_trending_override` on a missing path raised `SystemExit` naming the path and left no file there.\n\n### `tests/active/test_random_videos.py`\nNot edited. The checkpoint uses the harness (`_schema`, `_ranks_db`, `_plan`, `RANKS`, `TRENDING_EXPECTED`) exactly as it stands. Moving the checkpoint's two tests and docstring bullets into this file is test-side work, not production code.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_override_plan.py: a throwaway probe I wrote to check the query plan and the missing-path behaviour before handing in. My tools cannot delete files, so the operator needs to remove it. It fails on purpose with `assert False` so its printed output is shown, and it is not part of the build.\ntests/last_test_output.txt and tests/last_test_validation.json: running that probe through `ValidateTests` overwrote both files with the probe's output. The workflow's checkpoint run will overwrite them again.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_44_trending_seed_write_lock_during_phase2.py": "<items>\nnone\n</items>\n\n<findings_addressed>\nShape CRITICAL 1 (stub question: only rejected inputs, so an always-reject check passes): added a valid-SQLite case at :82\u2013:88. `valid.db` is created with sqlite3 and holds one placeholder table. `_starts_serving` (:41\u2013:55) Popens the real `server.py --trending-db valid.db` under `ENGINE_START_LOCK`, the same way `_start_variant` does. It polls until `harness._has_started` (the `service.lifecycle` start) or 120 s, then terminates. :88 asserts that the start was reached. An unconditional `parser.error(...)` or any check that rejects every PATH exits before the lifecycle start, so :88 goes red. The two rejected inputs and this accepted input now must produce different outcomes.\nClaim recommendation 2 (no normal path): taken. It is the same valid-SQLite case at :88, and the docstring gains a bullet for it.\nClaim recommendations 1 (more boundary inputs) and 3 (module name): left. A zero-byte file is accepted by the planned `mode=rw` + `ensure_trending_schema` check, and it is not in must_prove. The module filename is assigned by the workflow, not by me.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:67, :68, :70: for the missing `absent.db`, `run.returncode != 0`, `str(missing) in run.stderr`, and `\"unrecognized arguments\" not in run.stderr` (armed by the controls at :62\u2013:63)</assertion>\n<expected>A non-zero exit, with stderr naming the absent path through the Engine's own SystemExit message and not through argparse's rejection. This is predicted. Today :67\u2013:68 hold only because argparse rejects the flag; that was observed.</expected>\n<wrong_implementation>With the flag never added (today's code), :70 goes red. Observed: stderr \"server.py: error: unrecognized arguments: --trending-db /tmp/.../absent.db\", and the test currently fails at :70. With the flag added but no check, the server serves and `_run` raises TimeoutExpired at 120 s. With a check whose message leaves out the path, :68 goes red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:76, :77, :78: the same three assertions for the 4096-byte non-SQLite `junk.db`</assertion>\n<expected>A non-zero exit, with the junk path in stderr and no \"unrecognized arguments\". This is predicted, because the run stops at :70 today.</expected>\n<wrong_implementation>A check that only tests `Path.exists()`, or a bare `sqlite3.connect` with no query, lets the junk file through. The server then serves, and `_run` times out and raises. A generic \"file is not a database\" message with no path makes :77 go red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:88: `_starts_serving(valid, log_path)`. An existing SQLite file passed as `--trending-db` reaches the Engine's `service.lifecycle` start within 120 s.</assertion>\n<expected>True: the check passes it and the Engine serves. Observed on today's code without the flag: the same Popen and `_has_started` loop reached the lifecycle start in about 1.1 s, and terminate gave rc 0. Also observed: today, with the flag, this start exits 2 with \"unrecognized arguments: --trending-db .../valid.db\". That the built flag reaches the start on this file is predicted.</expected>\n<wrong_implementation>A check that rejects every PATH, for example an unconditional `parser.error(f\"--trending-db {path}: not a SQLite file\")`. It satisfies :67\u2013:79 but exits before the lifecycle start, so `_has_started` is False and :88 goes red, showing the log tail.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:71: `not missing.exists()` after the failed start</assertion>\n<expected>True: `absent.db` is never created. Today this is true because argparse exits first (observed); after the build it is predicted.</expected>\n<wrong_implementation>A check that runs a plain `sqlite3.connect(path)`, or uses `mode=rwc`, before rejecting. That creates `absent.db`, so :71 goes red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:79: `junk.read_bytes() == JUNK`, the 4096-byte literal that was written</assertion>\n<expected>The file's bytes are exactly the bytes written.</expected>\n<wrong_implementation>An implementation that truncates, re-initialises or replaces a non-SQLite file before or instead of rejecting it, for example by deleting it and recreating the schema. The bytes then differ, so :79 goes red.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The \"unrecognized arguments\" absence checks at :70 and :78 are armed by the positive control at :62\u2013:63. The new :88 is a positive reading, the lifecycle start. If the code under test is deleted (no flag), :70 is red. I observed this: the test fails there now.\n2. No. Nothing compares a value to itself. The JUNK literal at :79 is the input, not something production computes. Deleting the path from the SystemExit message turns :68/:77 red. Deleting the validation lets junk.db through, so the server serves and `_run` raises TimeoutExpired. Making the check unconditional turns :88 red.\n3. Previously yes: only rejected inputs were read. That was the shape CRITICAL. I rewrote the test to add the accepted `valid.db` case at :82\u2013:88, which must produce a different outcome (the lifecycle start) from the two rejected inputs.\n4. No. There are no doubles. The real `server.py` runs as a subprocess under the Engine interpreter.\n5. Yes, it collects. The new imports are fcntl, sqlite3, subprocess and time. `harness.ENGINE_START_LOCK`, `harness.VARIANT_START_SECONDS`, `harness._has_started`, `harness.API_DIR`, `harness._free_port` and `harness.ENGINE_PY` all exist in test_server_config.py; I read them, and the probe used them. The run collected 1 test, which is the count written.\n6. Yes, for what can be seen today. I ran a probe, tests/tmp/probe_valid_start.py. It showed that a sqlite3-created file has the header b'SQLite format 3\\x00'. It showed that the Popen + `_has_started` loop under the start lock reaches the lifecycle start in about 1.1 s and terminates with rc 0. It showed that today `--trending-db valid.db` exits 2 with \"unrecognized arguments\". It cannot show that the built flag reaches the start on valid.db, because that code does not exist yet. That remains a prediction, and the Phase 2 green run will confirm it. Please delete tests/tmp/probe_valid_start.py and the earlier tests/tmp/probe_trending_db_flag.py. I have no tool that removes files, and the checkpoint now carries what they showed.\n7. Yes, it is still red for its own reason. ValidateTests failed at :70 with stderr \"server.py: error: unrecognized arguments: --trending-db /tmp/.../absent.db\", meaning the flag is not built yet. There was no typo, import error or fixture failure.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_44_trending_seed_write_lock_during_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:42, :43, :45 \u2014 for the missing `absent.db`: `run.returncode != 0`, `str(missing) in run.stderr`, and `\"unrecognized arguments\" not in run.stderr`</assertion>\n<expected>Under the right implementation the start exits non-zero, stderr names the absent path, and argparse has accepted `--trending-db`, so its \"unrecognized arguments\" rejection is not in stderr. I could only partly observe this. The run showed :42 and :43 already true today, because argparse rejects the unknown flag with exit 2 and quotes the path. It showed :45 red today, on the stderr text \"server.py: error: unrecognized arguments: --trending-db /tmp/.../absent.db\". How stderr reads once the phase is built is a prediction until the phase runs.</expected>\n<wrong_implementation>If the flag is never added (today's code), :45 goes red with the stderr above. If the flag is added but the path is not checked, the server binds the free port and serves, so `_run` raises TimeoutExpired after 120 s and the test goes red. If the check fails with a message that leaves out the path (for example a bare \"trending db invalid\"), :43 goes red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:51, :52, :53 \u2014 the same three assertions for the 4096-byte non-SQLite `junk.db`</assertion>\n<expected>Non-zero exit, the junk path in stderr, and no \"unrecognized arguments\". This is predicted, not observed: this run stopped at :45 and never got here.</expected>\n<wrong_implementation>A check that only tests `Path.exists()` passes the junk file, so the server starts and `_run` times out after 120 s, raising TimeoutExpired. A check that runs `sqlite3.connect` without a query also gets past, because `connect` does not read the header, so the result is the same. If the \"file is not a database\" error is raised without the path in it, :52 goes red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:46 \u2014 `not missing.exists()` after the failed start on `absent.db`</assertion>\n<expected>False: the path is still absent. This is predicted for the built phase; the run stopped at :45 before reaching :46.</expected>\n<wrong_implementation>A check that calls `sqlite3.connect(path)` (or `ensure_trending_schema`) before validating creates an empty `absent.db`. The start might still exit non-zero, but `missing.exists()` is then True and :46 goes red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_44_trending_seed_write_lock_during_phase2.py:54 \u2014 `junk.read_bytes() == JUNK` after the failed start on `junk.db`</assertion>\n<expected>The file still holds exactly the 4096 bytes written at :49. This is predicted; the run did not reach :54.</expected>\n<wrong_implementation>An implementation that recovers by recreating or initialising the file (unlinking and re-creating it, or writing a schema over it) would leave different bytes or an empty file, so :54 goes red.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, after the rewrite. C1 has non-zero exit, path in stderr, and not argparse's rejection (:42/:43/:45 and :51/:52/:53). C2 has absent stays absent (:46) and junk bytes unchanged (:54). The old docstring line saying the usage lists `--trending-db PATH` described a control that I removed (see 9), so I rewrote that docstring line to describe the new controls.\n2. Absence only: there was a gap, now fixed. The C1 absence checks at :45/:53 had nothing proving the phrase is visible when argparse rejects. I added the positive control at :36-:38: `--no-such-flag` exits 2 with \"unrecognized arguments\" in captured stderr, and the run showed it pass. The C2 absence check at :46 sits after the start ran, proven by :42 and :43.\n3. Echoed literal: no. `JUNK` is the input fixture, and :54 compares the file to it after an independent subprocess has run. The test does not do production's transformation itself. The production line whose deletion turns it red is the `--trending-db` `add_argument` in `parse_args` (server.py:153-203) together with the path check, which does not exist yet.\n4. One value: no. C1 is read at two different bad inputs, a missing path and a non-SQLite file, and each is compared against its own path, not a sibling value.\n5. The double: none. The real `server.py` runs under the Engine interpreter `harness.ENGINE_PY`. `_run` and `_free_port` are the project's own test harness, loaded by path, not a stand-in for production code.\n6. It collects: yes. The ValidateTests run printed \"collected 1 item\". The collect-only summary row reads \"no tests\" because that table counts executed outcomes, and collect-only executes none. Its exit was 0, so every import resolved, including the path-loaded harness and its `from conftest import`. `harness._run(argv, value)`, `harness._free_port()`, `harness.API_DIR` and `harness.ENGINE_PY` all exist (test_server_config.py:39, :41, :47).\n7. Observed, not predicted: the controls are observed. `--help` exits 0, and an unknown flag gives exit 2 with \"unrecognized arguments\", both passing in the run. Today's stderr for `--trending-db` was also observed (quoted in 9). The values for the built phase cannot be observed before it exists, so the rows mark them as predictions. Running this test after the phase is implemented would confirm them.\n8. Red, not green: yes, it fails. The first run was red on the wrong assertion, and that drove the rewrite below. The second run printed \"1 failed \u2026 recorded: tests/last_test_validation.json (exit 1)\" with \"[exit status 1]\".\n9. Red for the right reason: the first run was no. It failed the CONTROL at line 36, `assert \"--trending-db PATH\" in ok.stdout`, on the `--help` usage, which lists only `[-h] [--dev] [--host HOST] [--port PORT] [--random-cache-refresh | --no-random-cache-refresh]`. That control presupposed the phase, so nothing was measured. Rewrite: I removed it and added the controls at :36-:38. Second run: yes. Every control passed (:35, :37, :38), and :42 and :43 passed. It failed at \"tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:45: AssertionError\", the C1 check `\"unrecognized arguments\" not in run.stderr`, on stderr \"server.py: error: unrecognized arguments: --trending-db /tmp/pytest-of-enduser/pytest-9802/test_a_trending_db_that_is_mis0/absent.db\". The flag is not implemented, which is the phase's own claim.\n10. Observed expected output: the run agrees with every row where it reached the assertion. :42 and :43 already hold today through argparse's exit 2 and quoted path, as the C1 row says. :45 is red with the quoted rejection, as the row says. :46 and :51-:54 were not reached, and their rows say so, giving their values as predictions for the built phase rather than observations. No row says something the run contradicted.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `engine/server/api/server.py`\n- The import from `data.trending` now also brings in `attach_trending_override` and `prepare_trending_override`. Phase 1 added both to `trending.py`, so they are reused here as they are.\n- `parse_args` gains `--trending-db` with `metavar=\"PATH\"` and `default=None`, written in the file's `help=(...)` style. It sits after the `refresh_group` block and before `set_defaults`. The help text says four things: it is a dev/test override; only `trending_ranks` is read from PATH; PATH must be an existing SQLite file (an empty file counts) and is never created, though the table and index are created in it if missing; a relative PATH resolves against the working directory.\n- In `main()`, when the flag is set, `prepare_trending_override(args.trending_db)` runs before `connect_db(db_path)`. So a missing path or a non-SQLite file stops the start before `whitelist.db` is opened, the index is loaded or anything binds. It exits non-zero through `SystemExit`, with a message naming the path. The `mode=rw` open creates no file.\n- `ensure_trending_schema(db)` now runs only when the flag is absent. That branch is the original line and comment, unchanged. When the flag is set, `attach_trending_override(db, args.trending_db)` runs in the same place. That is after the two `executescript` ensures, which commit, so the ATTACH never runs inside a transaction. The shared `trending_ranks` is then neither created nor read on `server.db`.\n- The attach is wired in this phase because `server.py` is not in Phase 3's file list, and a flag that validates PATH but is never read would do nothing.\n- The plan's optional `trending_db=` startup log line is left out: no test or requirement needs it.\n\n### `tests/active/test_server_config.py`\nNot edited. Moving the checkpoint test into this file is test-side work for the promotion step, the same split Phase 1 used. Production code alone is enough to turn the checkpoint green.\n\n### `tests/config.json`\nNot edited, for the same reason. Adding `engine/server/data/trending.py` to the `test_server_config.py` group goes with promoting the test into that file. Changing the group mid-build would also change the fingerprint the workflow is gating on.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_44_trending_seed_write_lock_during_phase3.py": "<assertions>\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:55 - setup order, not an assertion: `shared_trending_before` is requested first, by name, through `request.getfixturevalue`. So the fingerprint is read before `engine` builds the seed, whatever scope or order the conftest gives it. A conftest that does not define the fixture stops here, before the old `trending_seed` can rewrite the shared table.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:59 - control: `before[3] > 0`, so the shared `trending_ranks` has a real fill (rows with fetched_at > 0). Without one, a seed written into the table could leave the fingerprint where it was.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:61 - control: `test_similar._feed_constants` ran under the Engine interpreter (`FEED_CONSTANTS is not None`).\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:63 - control: `FEED_CONSTANTS[\"popular_pool_size\"]` is a positive int. It is the Engine's DEFAULT_POPULAR_POOL_SIZE read through `_feed_constants`, as agreed. Phase 3 must add this key to test_similar.py's `_FEED_CONSTANTS_CHILD`, and the failure message names the key.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:67 - control: `_reference(dataset, \"trending\", threshold)` holds at least 3 * FEED_PAGE rows. Excludes a `dataset` or seed that leaves the private order empty.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:70 - discrimination control: `_reference` on a fresh plain `mode=ro` connection (the shared ranks) gives first three pages that differ from the private reference. If they are equal, the message says the shared table has no real fill or the seed was written into it, and prints the fingerprint before and now. Excludes a `dataset` that carries no private view, and a seed still written into the shared table.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:73 - discrimination control for the popular layer: at least a quarter of the shared filtered popular pool lies outside the private filtered pool (observed 3003 of 5000). So an Engine that draws about 20 popular rows from the shared pool fails line 87.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:80 - three `mode=trending` pages, each excluding the rows served before it, equal `reference[: 3 * FEED_PAGE]`, the private order (C1). Excludes an Engine started without `--trending-db` (it serves the shared head, which :70 shows is different), an Engine reading an empty private file (empty pages), and an exclude walk that repeats or skips rows.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:85 - control: an unseeded `POST /recommendations?limit=2*default&debug=1` on its own rate bucket (192.0.2.181) serves at least one row with `debug.layer == \"popular\"`. Excludes an Engine whose ranks table is empty, so that its popular layer serves nothing.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:87 - every popular-layer row is in `fetch_popular_videos(dataset, POOL, error_threshold=threshold, include_nsfw=False)`, the private pool (C1). Excludes an Engine whose popular generator reads the shared `trending_ranks`; about 60% of that pool lies outside the private one.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py:90 - after the Engine has served, `conftest.shared_trending_fingerprint() == before` (C2). The message names the operator's updater trending-stage run as a possible external cause. Excludes the old seed's DELETE+INSERT (88648 rows, all with fetched_at 0, against 86826 real ones) and any Engine start that writes the shared table.\n</assertions>\n\n<probes>\ntests/tmp/probe_phase3_shared_vs_private.py, run with ValidateTests [\"tests/tmp/probe_phase3_shared_vs_private.py\", \"-s\"]. It only reads the shared DB. It builds the private seed the way the plan does (TRENDING_SEED_SQL into a temp file, with shared attached mode=ro). It printed: VIDEO_ERROR_THRESHOLD 3 and DEFAULT_POPULAR_POOL_SIZE 5000. The shared fingerprint was (86826, 1791035941189, 1791035941189, 86826) both before and after, so the table has a real fill and the probe changed nothing. The private seed has 88648 rows. `attach_trending_override` works on a `mode=ro` URI connection, and that connection's `main.trending_ranks` still reads the shared fingerprint. The shared and private filtered heads (36 rows) differ and share 7 keys. 3003 of the shared filtered popular pool's 5000 rows are outside the private filtered pool. The unfiltered private pool (`fetch_popular_videos(dataset, POOL)` with default args, as Step 6 words it) misses 74 of the filtered pool's rows. So the checkpoint uses the filtered call the Engine makes (builder.py:114-118: the error threshold and the request's NSFW flag), because the literal unfiltered call would make a correct Engine flaky.\ntests/tmp/probe_phase3_engine_popular.py, run with ValidateTests [\"tests/tmp/probe_phase3_engine_popular.py\", \"-s\"]. A real Engine started with `--trending-db <private seed>` (Phase 2 wired the flag), under ENGINE_START_LOCK, without the `engine` fixture, because that fixture still rewrites the shared table today. It printed: `mode=trending&limit=12` returned 200 with seed {}, and its rows equal the private head[:12]. Unseeded `POST /recommendations?limit=48&debug=1` returned 48 rows in the fresh/popular/random layers; 10 were popular, all 10 in the private pool and 3-5 in the shared one. limit=96 returned 89 rows, 20 of them popular, all 20 in the private pool and 4-10 in the shared one. The shared fingerprint did not change.\nCollection, with ValidateTests [\"tests/tmp/test_44_trending_seed_write_lock_during_phase3.py\", \"--collect-only\", \"-q\"]: exit 0, \"1 test collected\". The earlier ImportError came from an unguarded `from conftest import shared_trending_before`. That import is now bound only `if hasattr(conftest, \"shared_trending_before\")`, and the test reaches the fixture through `request.getfixturevalue`.\nRed run, with ValidateTests [\"tests/tmp/test_44_trending_seed_write_lock_during_phase3.py\"]: exit 1, 1 failed, with `fixture 'shared_trending_before' not found` at line 55, the first fixture request. `engine` and `trending_seed` never ran, so the current seed did not rewrite the shared table.\nBoth probe files are still in tests/tmp/. My tools cannot delete files, so the operator needs to remove them. Each one fails on purpose with `assert False`.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_44_trending_seed_write_lock_during_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:80 \u2014 the session Engine is asked for three `mode=trending` pages (limit FEED_PAGE, each excluding the rows already served). Together they must equal `harness._reference(dataset, \"trending\", threshold)[: 3 * FEED_PAGE]`, the private seed's order read through `dataset` with its private view. This is armed by :67 (the private order holds three pages) and :70 (the shared head, read on a fresh plain mode=ro connection, differs from the private head).</assertion>\n<expected>The 36 keys of the private seed's Trending head, in order. Observed this turn: an Engine started with `--trending-db` on a private seed built from TRENDING_SEED_SQL served a first `mode=trending&limit=12` page equal to the private head[:12] (probe_phase3_engine_popular.py: \"matches private head[:12] True\"). The checkpoint's own run has not reached :80 yet, because it stops at :55 on the fixture the phase adds.</expected>\n<wrong_implementation>The Engine is started without `--trending-db`, or the flag never shadows `trending_ranks` on `server.db`, so the Engine serves the shared real-fill head. Observed this turn on an unflagged Engine (probe_phase3_unflagged_engine.py): its first page shared 1 of 12 keys with the private head. Across 36 rows the shared and private heads share only 7 keys, so :80 goes red. An empty private file returns empty pages, which also makes :80 red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:87 \u2014 the test sends an unseeded `POST /recommendations?limit=2*BATCH_SIZE&debug=1`. Every row it returns with `debug.layer == \"popular\"` must be in `fetch_popular_videos(dataset, POOL, error_threshold=threshold, include_nsfw=False)`, the private pool. This is armed by :85 (at least one popular row is served) and :73 (at least a quarter of the shared pool lies outside the private pool; observed 3003 of 5000).</assertion>\n<expected>`outside == []`. Observed this turn on an Engine started with `--trending-db`: three limit=96 requests each served 20 popular rows, all 20 in the private pool, and 4, 6 and 7 of them were also in the shared pool. The checkpoint's own run has not reached :87 yet, because it stops at :55.</expected>\n<wrong_implementation>The override reaches `fetch_ordered_page` but not the popular pool's `fetch_popular_videos(server.db, ...)`, or the Engine is started without the flag. Popular rows then come from the shared pool. Observed this turn on an unflagged Engine: 10, 13 and 9 of the 20 popular rows fell outside the private pool, so `outside` is non-empty and :87 goes red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:90 \u2014 `conftest.shared_trending_fingerprint()`, read after the Engine has served, must equal `before`. `before` is `shared_trending_before`, requested first at :55 so that it is read before the seed is built and the Engine starts. This is armed by :59: the shared table holds rows with `fetched_at > 0`.</assertion>\n<expected>The same tuple before and after: (86826, 1791035941189, 1791035941189, 86826). That value was read read-only this turn and stayed unchanged across a flagged Engine start-and-serve, an unflagged one, and the private seed build (all three probes printed it before and after).</expected>\n<wrong_implementation>A `trending_seed` that still writes into the shared `whitelist.db`. The old seed's `DELETE FROM trending_ranks` plus `TRENDING_SEED_SQL` replaces the table with the seed's 88648 rows (count observed this turn in the private copy), all with `fetched_at = 0`. That makes the fingerprint (88648, 0, 0, 0) instead of the real fill, and :90 goes red. :59 shows the last field starts above 0, so a rewrite cannot leave the fingerprint unchanged. An Engine start that writes the shared `trending_ranks` would also show up here.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\nChanges this turn: comments only. The :72 and :79 comments now carry what this turn's non-destructive probe saw on an Engine started without `--trending-db`. The :82 comment now says its figure comes from two probe runs. No assertion changed. I added one probe, tests/tmp/probe_phase3_unflagged_engine.py, and after use cut it down to a docstring-only stub because my tools cannot delete it. The operator should delete it, along with the older probe_phase3_shared_vs_private.py, probe_phase3_engine_popular.py and probe_phase3_fingerprint.py. ValidateTests also rewrote tests/last_test_output.txt and tests/last_test_validation.json.\n\n1. Whole claim: no gap. Each docstring bullet maps to assertions:\n- Controls: :59 (real fill), :61/:63 (feed constants and pool size), :67 (three-page private order), :70 (shared head differs), :73 (pool divergence).\n- Trending pages: :80.\n- Popular layer: control :85, carrying assertion :87.\n- Fingerprint: :90.\n\n2. Absence only: no. `assert not outside` at :87 is armed by :85 (popular rows were served) and :73 (the shared pool diverges). The fingerprint equality at :90 is armed by :59 (a real fill that a seed write would erase).\n\n3. Echoed literal: no. The reference at :80 comes from `fetch_ordered_page` on `dataset`, and the served pages come over HTTP from a separate Engine process. Lines whose deletion turns it red:\n- the `\"--trending-db\", str(trending_seed)` argv entry the phase adds to conftest's `engine`. Without it the Engine is unflagged, and this turn's probe saw :80 diverge (1 of 12 in common) and :87 fail (9\u201313 of 20 outside).\n- the `CREATE TEMP VIEW` line in `attach_trending_override`, which has the same effect.\n- for :90, a seed writing the shared table instead of `tmp_path_factory`.\n\n4. One value: no. :80 compares 36 ordered keys, :87 checks every popular row of the response against an independent pool, and :90 compares the fingerprint at two points in time.\n\n5. The double: none. The test uses the real Engine subprocess, the real conftest fixtures, and the real `_reference` and `fetch_popular_videos`.\n\n6. It collects: yes. The `--collect-only -q` line handed in reads \"no tests\", but that is the runner's summary formatter: `phrase()` at validate_tests.py:1323 prints \"no tests\" when the summary has no outcome counts, which is what a collect-only run produces. The real run shows \"collected 1 item\" and runs one test, the one I wrote. Names bind against test_similar.py: `_default_limit` :108, `_keys` :580, `FEED_PAGE` :707, `FEED_CONSTANTS(_ERROR)` :743, `_post` :749, `_exclude` :755, `_reference` :759. `fetch_popular_videos(conn, pool, error_threshold=, include_nsfw=)` was called with exactly these arguments in this turn's probes. The run lists `dataset`, `engine` and `trending_seed` as available fixtures. `shared_trending_before` and `shared_trending_fingerprint`, plus the `popular_pool_size` key in `_FEED_CONSTANTS_CHILD`, are this phase's deliverables.\n\n7. Observed, not predicted: every figure in the comments was re-observed this turn with read-only probes:\n- the fingerprint (86826, 1791035941189, 1791035941189, 86826), unchanged before and after;\n- threshold 3 and pool 5000;\n- 7 of 36 head keys in common;\n- 3003 of the shared pool's 5000 rows outside the private pool;\n- flagged Engine: first page equals private head[:12], and 20/20 popular rows in the private pool with 4/6/7 also in the shared pool (the earlier run saw up to 10);\n- unflagged Engine: 1 of 12 in common, and 10/13/9 of 20 outside the private pool.\n\n8. Red, not green: yes. ValidateTests [\"tests/tmp/test_44_trending_seed_write_lock_during_phase3.py\"] gave exit status 1: \"1 failed\", \"1 failed in 0.20s\".\n\n9. Red for the right reason: yes. The run names line 53/55: \"E       fixture 'shared_trending_before' not found\". That fixture is what this phase adds to tests/active/conftest.py, so the red is the phase not yet built. No control assertion failed: none ran, and neither the Engine nor the seed started. That is deliberate. Reaching :59\u2013:90 against today's conftest means requesting `engine`, and today's `trending_seed` would DELETE the operator's real fill from the shared whitelist.db. I put this to the operator with AskUser and they answered \"Approve\". The wrong-implementation reds those assertions would give come instead from this turn's non-destructive unflagged-Engine probe (see rows). Once the fixture exists, the next gate is :63, which needs the `popular_pool_size` key the phase adds to `_FEED_CONSTANTS_CHILD`.\n\n10. Observed expected output: the gated run reached none of the row assertions (:80, :87, :90), so it contradicts no row. Each row's `expected` and `wrong_implementation` give what this turn's probes printed for a flagged and an unflagged Engine, which were real Engine starts on the real dataset, and they say so.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `tests/active/conftest.py`\n- The trending schema module (`engine/server/data/trending.py`) is now loaded once at module level as `TRENDING`. Before, it was loaded lazily inside `trending_seed`. `trending_seed` and `dataset` both use it.\n- Added `TRENDING_FINGERPRINT_SQL`: `COUNT(*)`, `MIN(fetched_at)`, `MAX(fetched_at)` and the count of rows with `fetched_at > 0`, read from `main.trending_ranks`.\n- Added `shared_trending_fingerprint()`. It runs that query on a fresh `file:\u2026?mode=ro` connection to `WHITELIST_DB` and returns a tuple.\n- Added the session fixture `shared_trending_before`, which returns that fingerprint.\n- `trending_seed(tmp_path_factory, shared_trending_before)` no longer writes the shared DB and no longer takes `ENGINE_START_LOCK`. It works like this:\n  - It creates `tmp_path_factory.mktemp(\"trending\") / \"trending.db\"` on a URI connection and applies `ensure_trending_schema`.\n  - It attaches `file:<WHITELIST_DB>?mode=ro` as `shared` and runs `TRENDING_SEED_SQL` unchanged inside `with conn:`.\n  - It returns the path.\n  - It takes `shared_trending_before` only to make the fingerprint read happen before the seed.\n- `engine` adds `\"--trending-db\", str(trending_seed)` to the Engine argv, plus one comment line. The start lock and the retry loop are unchanged.\n- `dataset(trending_seed)` calls `TRENDING.attach_trending_override(conn, str(trending_seed))` on its read-only connection. `_reference` and `fetch_popular_videos` on `dataset` therefore read the same private ranks the Engine serves.\n- Rewrote the module docstring, the `trending_seed` docstring and the comment above `TRENDING_SEED_SQL` to describe the private seed. `ENGINE_START_LOCK`, `fcntl` and `tempfile` stay, since the engine fixture and other test files still use them.\n\n### `tests/active/test_similar.py`\n- `_FEED_CONSTANTS_CHILD` now also prints `\"popular_pool_size\": server_config.DEFAULT_POPULAR_POOL_SIZE`, and the `_feed_constants` docstring mentions it.\n- The docstring bullet for the ordered-mode test now says the `dataset` connection's Trending ranks are the session's private seed.\n\n### Observed with probes (`tests/tmp/probe_private_seed.py`)\n- A `mode=ro` connection to the shared DB accepts the ATTACH plus TEMP VIEW from `attach_trending_override`.\n- A write to the attached shared DB is refused with \"attempt to write a readonly database\".\n- Running the new fixture bodies gave these results:\n  - The private file held 88,648 rows, all with `fetched_at = 0`.\n  - `dataset`'s view read those same 88,648 rows.\n  - The shared fingerprint was `(86826, 1791035941189, 1791035941189, 86826)` both before and after.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_private_seed.py: a probe file I created and then emptied. I have no tool to delete a file, so it remains as an empty, uncollected file and should be deleted.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nnone \u2014 `engine/server/data/trending.py` and `engine/server/api/server.py` were already the smallest shape that passes, so I made no edits.\n</refactors>\n\n<left_out>\nRemoving the one-line \"what\" comment above `TRENDING_OVERRIDE_SCHEMA` in `engine/server/data/trending.py`: it is cosmetic, and the approved draft (plan line 472) has the constant in the same form.\nInlining `TRENDING_OVERRIDE_SCHEMA` into the two f-strings of `attach_trending_override`: it is one name used twice in one function, the approved draft defines it, and inlining saves no lines.\nMerging the two `args.trending_db` branches in `server.py` `main()` into one: they cannot merge, because `prepare_trending_override` must run before `connect_db` (so a bad path stops the start before whitelist.db is opened) and the attach must run after it, after the committing `executescript` ensures.\nLogging the plan's optional `trending_db=` line at startup: that would be new behaviour, not a refactor, and no test or requirement asks for it.\nAdding `engine/server/data/trending.py` to the `test_server_config.py` group in `tests/config.json`: this belongs with promoting the Phase 2 checkpoint into that file, not with a production refactor, and changing it mid-build would move the fingerprint being gated.\nTest files (`tests/active/conftest.py`, `tests/active/test_similar.py`, `tests/active/test_random_videos.py`, `tests/active/test_server_config.py`) and the gated `tests/tmp/test_44_*` checkpoints: not production code, and the gated ones are not mine to edit.\nCleanup that needs the operator, since I cannot delete files: tests/tmp/probe_private_seed.py, probe_phase3_unflagged_engine.py, probe_phase3_fingerprint.py, probe_phase3_engine_popular.py, probe_phase3_shared_vs_private.py, probe_valid_start.py, probe_trending_db_flag.py, probe_override_plan.py and probe_override.py are leftover probes from earlier phases.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nI read both production files on disk and searched for every user of the new names. The override is three names in `trending.py`, used only by the guarded branches in `server.py` `main()` and by the `conftest.py` fixtures, with no duplication or dead code, so I made no change and ran nothing.\n</observation>",
    "step_10_plan": "<harvest_file>\ndocs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md\n</harvest_file>\n\n<plan>\n## Harvest plan: build 47-44 (trending seed write lock during)\n\nI've classified the 4 tests in this build's 3 files in `tests/tmp`. All 4 should move into the durable suite (`DURABLE`). Nothing has moved yet and the group map is unchanged.\n\nBefore this, the config check passed with nothing defaulted and no conflicts. A snapshot of `tests/last_test_validation.json` was saved as `.preharvest` and checked byte-identical to the original. All 3 files load in pytest (4 items), checked with `pytest --collect-only`, which records nothing.\n\n### Count per verdict\n| Verdict | Count |\n|---|---|\n| DURABLE | 4 |\n| REPLACES | 0 |\n| COMBINE | 0 |\n| REDUNDANT | 0 |\n| SPENT | 0 |\n\n### Tests that move (DURABLE) and where they go\n1. **`test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`** (phase 1) \u2192 `tests/active/test_random_videos.py`\n   - It checks that a connection prepared by `attach_trending_override` gets the attached file's ranks from both the Trending page and the popular pool.\n   - It also checks that a plain connection to the same database still gets main's ranks, and that main's ranks are not changed.\n   - No test in `tests/active` checks this.\n   - It brings `OVERRIDE_EXPECTED`, `OVERRIDE_UNSERVED`, `_private_file` and `_prepared` with it, and uses the file's own `_ranks_db`, `RANKS`, `TRENDING_EXPECTED` and `_trending_labels`.\n2. **`test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`** (phase 1) \u2192 `tests/active/test_random_videos.py`\n   - The existing query-plan test only looks at main's ranks.\n   - This one checks that a Trending page read through the attached file still uses `idx_trending_ranks_order` and does no sort (no `TEMP B-TREE`).\n   - It brings `_catalogue` and `_catalogue_ranks` with it.\n   - **Optional, needs your OK:** change the existing `test_a_trending_page_walks_the_ranks_index_without_sorting` to call those two helpers instead of keeping its own copy of the same setup code. Its assertions would not change.\n3. **`test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`** (phase 2) \u2192 `tests/active/test_server_config.py`\n   - It checks that `server.py --trending-db` is accepted.\n   - A missing path or a non-SQLite file must stop the start with a non-zero exit, name the path, create nothing and change nothing.\n   - A real SQLite file must get past the check and start.\n   - It uses the file's own `_run`, `_free_port`, `_has_started`, `ENGINE_PY`, `API_DIR`, `ENGINE_START_LOCK` and `VARIANT_START_SECONDS`, and brings `SERVER_PY`, `JUNK`, `_argv`, `_start` and `_starts_serving`.\n   - The workarounds it needed to run from `tests/tmp` (loading its helper by path, editing `sys.path`) are dropped.\n4. **`test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged`** (phase 3) \u2192 `tests/active/test_similar.py`\n   - It overlaps `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` but adds three things no active test checks:\n     - a check that the shared table's first pages differ from the private seed's, so the test can tell which one the Engine served;\n     - that live popular-layer rows come from the private pool;\n     - that the shared `whitelist.db` `trending_ranks` fingerprint is the same after the Engine has served. That is the rule this build exists for.\n   - I classed it as DURABLE rather than COMBINE because the ordered test runs over every ordered mode, and these checks only apply to Trending.\n   - In `tests/active` it takes the fixtures `shared_trending_before`, `engine` and `dataset` as plain arguments. The temporary `hasattr` guard and the `getfixturevalue` ordering are dropped.\n   - It brings `POOL_KEY`, `TRENDING_HEADERS` and `POPULAR_HEADERS` (client IPs 192.0.2.180 and .181, which no other test uses) and `_shared`.\n   - **Risk:** it goes red if the shared table has no real data in it, or if the updater's trending stage runs during the suite. Its failure message names that second cause.\n\n### Active tests that would be retired\nNone. Nothing goes to `tests/archive/` and no active test is renamed.\n\n### `test_groups` changes\n- **`test_server_config.py`**: add `engine/server/data/trending.py`. The refusal and no-create rule the moved test checks live in `prepare_trending_override`. Phase 2 put this addition off until the test was moved.\n- **`test_similar.py`**: add `engine/server/api/recommendations/candidates/popular_videos.py`, because the moved test checks which rows the live popular layer serves. Leave this out if you count that as the mixer's job, and `mixer.py` is already listed.\n- **`test_random_videos.py`**: no change. It already lists `random_videos.py` and `trending.py`.\n- **`conftest.py`**: stays unlisted. It is a shared helper.\n\n### New subject files\nNone.\n\n### Cleanup after the move (Step 7)\n13 entries go to `delete_me/`, and none of the names are already taken there:\n- the 3 `test_44_*` checkpoints;\n- 9 leftover `probe_*.py` files, one of them already empty;\n- `tests/tmp/__pycache__`, renamed to `__pycache__-harvest44`.\n\n`tests/tmp` is empty afterwards.\n\n### Decisions for you\n1. Approve the 4 DURABLE moves and their destinations.\n2. Approve or decline the optional change to the existing query-plan test in `test_random_videos.py`.\n3. Approve or decline adding `popular_videos.py` to the `test_similar.py` group.\n</plan>",
    "step_9_triage": "<docs>\n<doc path=\"engine/server/README.md\" update=\"no\">\nThe README lists no Engine CLI flags. The requirements only ask for the flag to be documented here \"if it lists Engine flags\", and it does not. Its one sentence on the subject (line 26, \"Trending serves only videos ranked in `trending_ranks`, so it answers an empty page until the updater's trending stage ... first fills that table\") is still true. A production Engine never gets the flag (systemd unit, `scripts/run-services.sh`), and a flagged Engine still serves only rows ranked in a `trending_ranks` table, just the one in PATH. The flag is documented where the requirements make it mandatory: the `--trending-db` `help=(...)` text in `server.py` `parse_args` covers the dev/test override, that only `trending_ranks` is read from PATH, that PATH must exist and is never created, and relative-path resolution.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\" update=\"no\">\nLine 101 (\"`trending_ranks` is created empty when the Engine starts\") describes the deployed Engine, which never passes `--trending-db`. On that path the unflagged branch of `server.py` `main()` is the original `ensure_trending_schema(db)` line, unchanged. The flagged case applies the schema to the private file. That is a test-isolation detail outside this document's subject (the updater and its first fill), so mentioning it here would add a dev/test aside to an operator runbook.\n</doc>\n<doc path=\"docs/project/issues/44-trending-seed-write-lock-during-test-runs.md\" update=\"yes\">\nThe issue is delivered, so:\n- Set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md` and `issue-tracker.md`.\n- Tick the acceptance criteria the build met: flagged Trending served from the private file with the shared fingerprint unchanged (phase 3 test); unflagged reads main (phase 1 test); a missing or non-SQLite path exits non-zero, naming the path, and creates no file (phase 2 test); the suite passes with no test expectations changed.\n- Tick the full-suite fingerprint criterion only if the before/after read-only fingerprint around the build's full suite run was recorded. The in-suite gate covers the session Engine.\n- Add a short delivery comment saying what landed: `--trending-db PATH` in `server.py`; `prepare_trending_override` and `attach_trending_override` in `engine/server/data/trending.py` (ATTACH as `trending_override` plus a TEMP view shadowing `main.trending_ranks`, still planned as a walk of `idx_trending_ranks_order`); `trending_seed` building a per-session file from the shared DB attached `mode=ro`, no longer taking `ENGINE_START_LOCK`; `dataset` carrying the same private view.\n- Record the named limitations from the `rat-tail:` comments. The validation-to-ATTACH race means a file removed after `prepare_trending_override` is recreated empty by ATTACH on the non-URI `connect_db` connection. A PATH containing `?` or `#` fails validation because it is not URI-escaped.\n- Also note that the in-suite fingerprint gate goes red if an updater trending run writes the shared table mid-suite.\n</doc>\n<doc path=\"tests/active/conftest.py\" update=\"no\">\nPhase 3 already brought every named passage up to date, and the diff confirms it:\n- The module docstring (lines 6-13) describes `--trending-db` naming `trending_seed`'s per-session private file, `dataset` with that file attached and shadowing `trending_ranks`, and the two fingerprint helpers.\n- The `trending_seed` docstring now describes the private file and no longer cites issue 38 or the start lock.\n- The `engine` fixture has its `--trending-db` comment.\n- The comment above `TRENDING_SEED_SQL` now reads \"every lane's private file holds the same rows\".\n- `dataset` carries its own comment about the private ranks.\n\nNothing left in the file describes a shared-DB write.\n</doc>\n<doc path=\"tests/active/test_similar.py\" update=\"no\">\nPhase 3 took option (a) and already updated the ordered-mode bullet in the module docstring. The `dataset` reference is now described as \"read through the read-only `dataset` connection (whose Trending ranks are the session's private seed, as the Engine's are)\". The `_feed_constants` docstring names the popular pool size it now returns. The NSFW control comment (\"the seed is derived from the live whitelist.db\") is still true, because the private seed is built by the same SQL from the same live catalogue. The docstring bullet for the phase 3 test is added when the harvest moves that test into this file, not by this step.\n</doc>\n<doc path=\"tests/active/test_random_videos.py\" update=\"no\">\nThe build did not edit this file, and no new test is in it yet. Both phase 1 checkpoints are still in `tests/tmp`, and the harvest plan (`docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md`, awaiting approval) moves them here as DURABLE. The module docstring is still accurate for the tests it lists. The two new claim bullets (the flag-on/flag-off order and pool test, and the override plan test) go in with that move, since a bullet for a test not yet in the file would be false.\n</doc>\n<doc path=\"tests/active/test_server_config.py\" update=\"no\">\nNot on the checklist; listed for completeness. Like `test_random_videos.py`, it gains the `--trending-db` missing/non-SQLite start test only when the harvest moves it, and its docstring bullet goes with that move. Its current docstring makes no claim the build changed. Unflagged starts on the shared DB behave as before.\n</doc>\n<doc path=\"CONTEXT.md\" update=\"no\">\nNot on the checklist; checked because line 20 (**Trending**) says the lists \"are stored per host in `whitelist.db` `trending_ranks`\". That is still the domain definition and the production state. `--trending-db` is a dev/test isolation override, and the issue triage and requirements say explicitly that CONTEXT.md does not change.\n</doc>\n<doc path=\"DEPLOYMENT.md\" update=\"no\">\nNot on the checklist; checked because lines 87, 195 and 453 describe `trending_ranks`:\n- Line 87 is the ranking source.\n- Line 195 is the updater's write lock in the served `whitelist.db` and the empty start.\n- Line 453 says the trending order walks `idx_trending_ranks_order` with no sort.\n\nAll three describe the deployed Engine, which never passes the flag, and the plan claim holds with the flag set too (phase 1 plan test). None of them is made false.\n</doc>\n<doc path=\"DATA_BUILD.md\" update=\"no\">\nNot on the checklist; checked because line 329 says Trending and the popular layer are empty until `trending_ranks` is filled. That is still true for every production Engine, and the document covers data builds, not test isolation.\n</doc>\n<doc path=\"docs/project/adr/0010-trending-from-source-instances.md\" update=\"no\">\nThe ADR covers where Trending comes from and how it is stored and refreshed. It says nothing about test data or alternative rank sources, and the issue triage confirmed it \"does not cover test data\". The build leaves the Trending definition, the schema, the job and the production read path unchanged.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:docs/project/issues/44-trending-seed-write-lock-during-test-runs.md": "<changes>\nIssue 44 is now marked `bug, complete` with a Delivered comment, and the archived copy is at `docs/project/issues/archive/`. The old file at `docs/project/issues/` still has to be deleted, because I can't delete files.\n\n- **Status:** `bug, ready-for-agent` became `bug, complete`. I wrote the full file to `docs/project/issues/archive/44-trending-seed-write-lock-during-test-runs.md`. The Problem, Proposed solution, Related, Triage and Agent Brief text is as it was.\n- **Acceptance criteria:** four are ticked: flagged Trending is served from the private file with the shared fingerprint unchanged; without the flag it reads main; a missing path exits non-zero and names the path; the suite passes with no expectations changed.\n- **Full-suite fingerprint criterion:** not ticked. The plan record has no read-only fingerprint taken before and after a full suite run. A note on the criterion says so, and says the in-suite gate covers the session Engine.\n- **Delivered comment** (under Comments, in the same form as other archived issues). I checked each point against `trending.py`, `server.py` lines 343\u2013357 and `conftest.py`:\n  - **Engine flag:** `--trending-db PATH` is a dev/test override, documented in `--help`. `prepare_trending_override` opens PATH `mode=rw` before `whitelist.db` is opened, applies the schema to it, and exits naming PATH if the start fails. `attach_trending_override` attaches it as `trending_override` and adds a TEMP view that shadows `main.trending_ranks`. The Trending query still walks `idx_trending_ranks_order` with no sort. `ensure_trending_schema` does not run on `whitelist.db` when the flag is set.\n  - **Suite:** `trending_seed` builds a per-session file from the shared DB attached `mode=ro`, and no longer takes `ENGINE_START_LOCK`. The `engine` fixture passes the flag, and `dataset` carries the same view. `shared_trending_before` and `shared_trending_fingerprint` read the shared table's fingerprint.\n  - **Limitations:**\n    - If the file is deleted between the check and the ATTACH, ATTACH recreates it empty.\n    - A PATH containing `?` or `#` fails the check, because the path is not URI-escaped.\n    - The fingerprint gate fails if an updater trending run writes the shared table during the suite.\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/44-trending-seed-write-lock-during-test-runs.md \u2014 the original file must be deleted to finish moving it to `docs/project/issues/archive/`. I wrote the archived copy, but my tools cannot delete the original, so the operator has to remove it.\n</not_on_checklist>",
    "step_10": "<moved>\ntests/tmp/test_44_trending_seed_write_lock_during_phase1.py::test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it \u2192 tests/active/test_random_videos.py (group test_random_videos.py), with OVERRIDE_EXPECTED, OVERRIDE_UNSERVED, _private_file and _prepared\ntests/tmp/test_44_trending_seed_write_lock_during_phase1.py::test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting \u2192 tests/active/test_random_videos.py (group test_random_videos.py), with _catalogue and _catalogue_ranks. The approved optional refactor is done: the existing test_a_trending_page_walks_the_ranks_index_without_sorting now calls _catalogue(conn) then _catalogue_ranks(conn), and its assertions are unchanged.\ntests/tmp/test_44_trending_seed_write_lock_during_phase2.py::test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it \u2192 tests/active/test_server_config.py (group test_server_config.py), with SERVER_PY, JUNK, _argv, _start, _starts_serving and `import sqlite3`. The by-path harness load and the sys.path insert were dropped.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py::test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged \u2192 tests/active/test_similar.py (group test_similar.py), with POOL_KEY, TRENDING_HEADERS (192.0.2.180), POPULAR_HEADERS (192.0.2.181) and _shared. It takes shared_trending_before, engine and dataset as plain fixtures, and the hasattr guard and getfixturevalue ordering were dropped. It imports WHITELIST_DB and shared_trending_fingerprint from conftest and fetch_popular_videos from data.random_videos.\nEach destination file's module docstring gained bullets for the new tests, and the clause tags (C1/C2) were replaced by the rule each assertion gates.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\ntest_server_config.py: added engine/server/data/trending.py, where prepare_trending_override holds the refusal and no-create rule the moved test gates.\ntest_similar.py: added engine/server/api/recommendations/candidates/popular_videos.py. The operator approved this optional item through AskUser.\nNo other entry changed. test_random_videos.py was already complete, and conftest.py stays unclaimed.\n`validate_tests.py --audit-map` exit 0. No MISSING finding names a file the moved tests drive. The engine/server/data/time.py and tmp/suite28 findings were there before this harvest.\n</group_map>\n\n<mutations>\nm1, engine/server/data/trending.py: attach_trending_override with its CREATE TEMP VIEW line replaced by `pass`. Red: test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it failed at `_trending_labels(fetch_ordered_page(prepared, \"trending\", 100, 0)) == OVERRIDE_EXPECTED` ('C1' != 'B5' at index 0). Restored from .bak, diff identical. Green: 1 passed.\nm2, engine/server/data/trending.py: the TEMP VIEW as `SELECT DISTINCT *`, so it is not flattened. Red: test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting failed at `any(\"idx_trending_ranks_order\" in detail ...)` with plan [CO-ROUTINE trending_ranks, SCAN trending_override.trending_ranks, SCAN t, ...], after its full-page and Popular TEMP B-TREE controls passed. Restored from .bak, diff identical. Green: 1 passed.\nm3, engine/server/data/trending.py: prepare_trending_override's SystemExit message without {path}. Red: test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it failed at `str(missing) in run.stderr` (stderr \"trending ranks file cannot be opened as SQLite: unable to open database file\"). Restored from .bak, diff identical. Green: 1 passed. I chose this over a mode=rwc mutation, because that start gets through and serves until _run's 120 s timeout, which is the hanging kind.\nm4, engine/server/api/server.py: main() with `attach_trending_override(db, args.trending_db)` replaced by `pass`, so the Engine reads the shared table and writes nothing. Red: test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged failed at `first + second + third == reference[: 3 * FEED_PAGE]` (differs at index 1), after all its controls passed. Restored from .bak, diff identical. Green: 1 passed, the fingerprint assertion included.\nAll four backups (trending.py.bak-harvest44-m1, m2 and m3, server.py.bak-harvest44-m4) were moved to delete_me/. None of this harvest's .bak files is left under engine/. The engine/server/db/whitelist.db.bak-20261002-212806 there was already there before this harvest.\n</mutations>\n\n<cleared>\n17 entries were added to delete_me/ by this harvest:\n- the 3 checkpoints: test_44_trending_seed_write_lock_during_phase1.py, phase2.py and phase3.py;\n- the 9 probes: probe_override.py, probe_override_plan.py, probe_phase3_engine_popular.py, probe_phase3_fingerprint.py, probe_phase3_shared_vs_private.py, probe_phase3_unflagged_engine.py, probe_private_seed.py (empty), probe_trending_db_flag.py and probe_valid_start.py;\n- tests/tmp/__pycache__, renamed to __pycache__-harvest44;\n- the 4 mutation backups: trending.py.bak-harvest44-m1, m2 and m3, and server.py.bak-harvest44-m4.\nNone of the names collided, and each was moved with mv -n. tests/tmp now holds 0 entries. delete_me/ holds 120 entries (103 before). Nothing has been deleted; the operator decides what to remove.\nClosing run: the snapshot was restored from tests/last_test_validation.json.preharvest, then `validate_tests.py --compare` exited 0. It ran 4 of 59 groups (test_random_videos.py, test_server_config.py, test_similar.py, and the unmapped test_search_fusion.py) and carried 55 forward as unchanged. 175 passed, 0 failed.\nAgainst the pre-harvest record: 4 appeared (the 4 harvested tests), 0 departed, no new red, nothing newly green. The steps are recorded in docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md.\n</cleared>"
  },
  "requirements": "### Purpose\n\nRunning the active suite must never change, or hold a write lock on, the shared dev `engine/server/db/whitelist.db` table `trending_ranks`. That file is the one the operator's long-running :7070 dev Engine serves, and worktrees symlink it too. Today the session fixture `trending_seed` (in `tests/active/conftest.py`) runs `DELETE FROM trending_ranks` and re-inserts `TRENDING_SEED_SQL` (each host's 100 most-viewed catalogue videos, `fetched_at = 0`, about 88,648 rows) on every lane start. That wipes any real fill (rows with `fetched_at > 0`) and holds the write lock for about 4.6 s in rollback-journal mode, against the Engine's 5 s busy timeout, while other lanes' Engines serve from the same file. The fix chosen with the operator: the test Engine reads private ranks through a new Engine CLI flag `--trending-db PATH`, and the suite never writes the shared `trending_ranks`. This is test isolation only. The Trending definition, CONTEXT.md and the ADRs do not change.\n\n### Engine: `--trending-db PATH`\n\n- `engine/server/api/server.py` `parse_args` gains an optional `--trending-db PATH`, with help text, so it shows in `--help`. It follows the style of the existing arguments (`--no-random-cache-refresh` and the others).\n- When the flag is set, every query the Engine runs against `trending_ranks` reads the table from the file at PATH. Today those are the `trending` entry of `ORDERED_FEED_SOURCE` in `engine/server/data/random_videos.py`, run through `fetch_ordered_page`, which `engine/server/api/handlers/similar.py` calls on `server.db`, and `fetch_popular_videos` (the Recommendations popular-layer pool), which `candidates/popular_videos.py` calls on `server.db`. `videos`, `video_embeddings`, moderation, interaction and every other table still come from `whitelist.db`.\n- The mechanism is the designer's choice, but it must cover every Engine connection on `whitelist.db` that runs a `trending_ranks` query. Today that is only `server.db` (`connect_db`). `search_db` (`connect_readonly_db`) and the random-cache build's source connection do not run Trending queries. Tree fact for the design: the shared `whitelist.db` already holds a `main.trending_ranks`, and SQLite resolves unqualified names in the order temp, main, then attached databases. A bare `ATTACH` of PATH therefore does NOT shadow the shared table. A TEMP view on the connection, or schema-qualified SQL, would.\n- With the flag set, the Engine never writes the shared file's `trending_ranks`, including at startup. `ensure_trending_schema` (server.py, currently called on `db` right after `ensure_interaction_event_schema`) applies to the private file instead of `whitelist.db`. The table shape and index (`trending_ranks`, `idx_trending_ranks_order`) are unchanged.\n- If PATH does not exist or cannot be opened as SQLite, the Engine start fails: it exits non-zero with an error message that names the path. It never silently falls back to the shared table, and it does not create the file. (Existing precedent: `connect_readonly_db` uses `mode=ro`, which never creates a file.)\n- Without the flag, behaviour and SQL plans are unchanged. The Trending page query still uses `idx_trending_ranks_order` as the driving index (the `CROSS JOIN` order), with no `TEMP B-TREE`, so an OFFSET walk stops early. The same must also hold with the flag set, so the test Engine exercises the same plan shape.\n\n### Active suite: private seed\n\n- `trending_seed` in `tests/active/conftest.py` builds the seed in a per-session temporary SQLite file (for example under `tmp_path_factory`), not in the shared DB. It applies `ensure_trending_schema` to that file and fills it with exactly the rows `TRENDING_SEED_SQL` produces today: same columns, ranks, likes, views and `fetched_at = 0`. It reads `videos` and `video_embeddings` from the shared `whitelist.db` through a read-only connection only, for example by attaching the shared DB read-only to the temp file's connection, or by opening the shared DB `mode=ro` and attaching the temp file. Either way the only file written is the temp file.\n- The `engine` fixture passes `--trending-db <temp file>` alongside `--no-random-cache-refresh`.\n- The seed no longer takes `ENGINE_START_LOCK`, because it no longer writes a shared file. The `engine` fixture keeps the lock for serialising Engine starts. Other tests import `ENGINE_START_LOCK` (`test_random_cache.py`, `test_server_config.py`), so the constant stays.\n- The fixture docstrings and the module docstring (conftest.py line 7 says `trending_seed` \"has rewritten that dataset's `trending_ranks`\") are updated to describe the private seed.\n- The suite opens no write connection to the shared `whitelist.db` for Trending.\n\n### Acceptance criteria\n\n- Starting the Engine with `--trending-db` on a seeded temp file serves Trending (`mode=trending`) in that file's merged-rank order. The shared `whitelist.db`'s `trending_ranks` fingerprint (row count; `fetched_at` min and max; count of rows with `fetched_at > 0`) is identical before and after.\n- Without the flag, Trending serves from `whitelist.db`'s `trending_ranks` as before.\n- Starting with `--trending-db` on a path that does not exist exits non-zero, with an error naming the path, and creates no file at that path.\n- After a full active-suite run, the shared `whitelist.db`'s `trending_ranks` fingerprint is unchanged, tested with a real fill present (rows with `fetched_at > 0`; the triage found 86,826 such rows in place). The suite cannot observe its own end, so this is checked by recording the fingerprint read-only before the build's full suite run and comparing it after. An in-suite test also gates that the session Engine started with the flag leaves the shared fingerprint unchanged.\n- The active suite passes, including the Trending and popular-layer tests in `test_similar.py` and its Trending NSFW control (a flagged row in the first 96 of the seeded order), with no test expectations changed.\n\n### Out of scope\n\n- Other test writes to the shared `whitelist.db`, such as bridge-mode interaction events from `engine_client`, and the other Engines the suite starts without the flag (`test_random_cache.py`, `test_server_config.py`). Those read the shared ranks, and their `ensure_trending_schema` is a `CREATE ... IF NOT EXISTS` that writes nothing when the table exists.\n- Confirming or fixing the intermittent up-next 500 (memory `upnext-pin-engine-500-intermittent`) beyond removing this writer.\n- Changing the seed's content or ranking, `engine/server/db/jobs/fetch-trending.py`, the updater's trending stage, or the moderation purge of `trending_ranks` (`engine/server/data/moderation.py`).\n- A general override for `whitelist.db` or the other DB paths.\n\n### Documentation\n\n- Document `--trending-db` where Engine CLI behaviour is described for developers (its `--help` text at minimum, and `engine/server/README.md` if it lists Engine flags), as a dev/test override that reads only `trending_ranks` from PATH.\n\n### Baseline suite state\n\n- Pre-build baseline: the active suite exits with code 0, no variant run (`variant: false`). The build must end with the suite still green.",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe change has two halves. The Engine gets a flag that sends its `trending_ranks` reads to a private file. The active suite seeds that private file and passes the flag. No `trending_ranks` SQL changes, and no function signature in `data/random_videos.py`, `handlers/similar.py` or `candidates/popular_videos.py` changes.\n\n**Engine flag.** `parse_args` in `engine/server/api/server.py` gains `--trending-db PATH` with `default=None`. It is written in the same `parser.add_argument(..., help=(...))` style as the other arguments. The help text says it is a dev/test override: only `trending_ranks` is read from PATH, the file must already exist and is never created, and every other table still comes from `whitelist.db`. That puts it in `--help`. `engine/server/README.md` does not list any Engine flags (I checked: none of the existing flags appear there), so `--help` is where this is documented, which is the minimum the requirement asks for.\n\n**How the override works: a TEMP view on `server.db`.** This goes in one small helper next to `ensure_trending_schema` in `engine/server/data/trending.py`. When the flag is set, `main()` does three things:\n\n1. **Validate first.** Before `connect_db(db_path)` and before anything touches `whitelist.db`, it opens PATH read-write with no create (the same URI precedent as `connect_readonly_db`, but `mode=rw`). It then runs `ensure_trending_schema` on that connection and closes it. This one step does three jobs:\n   - A missing path fails, and nothing is created.\n   - A file that is not SQLite fails on the schema statement (\"file is not a database\").\n   - The table and its index `idx_trending_ranks_order` are applied to the private file and not to `whitelist.db`.\n   \n   Any `sqlite3.Error` here becomes `SystemExit` with a message naming the path, so the exit is non-zero and the message goes to stderr. Because this runs before the FAISS load, a bad path fails in well under a second.\n2. **Attach.** After `connect_db`, it runs `ATTACH` of PATH on `db` under a fixed schema name.\n3. **Shadow.** It runs `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`. SQLite looks up unqualified names in the order temp, main, attached. So every unqualified `trending_ranks` on that connection now resolves to the private file. That covers the `trending` entry of `ORDERED_FEED_SOURCE` through `fetch_ordered_page` (the handler path) and `fetch_popular_videos` (the popular-layer path), because both run on `server.db`.\n\nWhen the flag is set, the existing `ensure_trending_schema(db)` call is skipped, because step 1 has already applied it to the private file. Without the flag, that call and everything else stay byte-for-byte as they are.\n\n**Checks against the tree:**\n- `server.db` is assigned once in `SimilarServer.__init__` and never replaced, so a per-connection view lasts the life of the process.\n- The only Engine code that writes `trending_ranks` is the moderation purge, and the only callers of `purge_host_data` are the jobs and job tests, never the API. So with the flag set, the Engine has no write path to the shared `trending_ranks`.\n- `search_db` and the random-cache source connection never mention `trending_ranks`, so they need nothing.\n- A TEMP view lives in the connection's temp schema, so creating it writes nothing to `whitelist.db`.\n\n**Plan shape with the flag.** The view is a plain `SELECT *` with no aggregate, DISTINCT, LIMIT or ORDER BY, and it is the left operand of the `CROSS JOIN`. SQLite's query flattener should therefore inline it as `<schema>.trending_ranks t CROSS JOIN video_embeddings e`. The private table drives the join through `idx_trending_ranks_order` with no `TEMP B-TREE`, the same plan as today. This is an expectation, not something I have verified, so the build gates it with an `EXPLAIN QUERY PLAN` test on a connection prepared by the helper, alongside the existing unflagged plan test in `test_random_videos.py`.\n\n**Active suite.** `trending_seed` in `tests/active/conftest.py`:\n- creates `trending.db` under `tmp_path_factory.mktemp(...)`, opened as a URI connection so that URI filenames work in `ATTACH`;\n- applies `ensure_trending_schema` to it;\n- attaches `whitelist.db` with `mode=ro`;\n- runs the unchanged `TRENDING_SEED_SQL`;\n- returns the path.\n\nThe unqualified names resolve correctly with no SQL edit: the insert target `trending_ranks` resolves to the temp file's main schema, which comes before the attached shared copy, while `videos` and `video_embeddings` exist only in the attached shared DB. The rows are exactly today's: same columns, ranks, likes, views and `fetched_at = 0`. The only file written is the temp file.\n\nThe seed drops `ENGINE_START_LOCK`. The constant stays, because `test_random_cache.py` and `test_server_config.py` import it. The `engine` fixture keeps the lock and adds `--trending-db <path>` next to `--no-random-cache-refresh`. The module docstring (line 7) and both fixture docstrings are rewritten to describe the private seed.\n\nNo session test reads `trending_ranks` through `dataset`. They only observe the Engine, so `test_similar.py`'s Trending, popular-layer and NSFW-control expectations still hold, since the served order is the same seeded order.\n\n**How each acceptance criterion gets gated (detail belongs to the test step):**\n- **Flag serves the private file's order; shared fingerprint unchanged.** A session-scoped fixture reads the shared fingerprint read-only before the seed and the Engine start: row count, `fetched_at` min and max, and the count of rows with `fetched_at > 0`. An in-suite test asks the session Engine for `mode=trending` pages and a popular-layer request, then checks two things. The pages must equal the merged-rank order computed from the temp file joined with the read-only dataset, under the NSFW filter. The shared fingerprint must be unchanged.\n- **Without the flag, Trending reads `whitelist.db`.** This is gated in-process rather than with another Engine start. A temp main DB holding ranks A and a temp private file holding ranks B are set up. `fetch_ordered_page` and `fetch_popular_videos` serve A on a plain connection and B on a helper-prepared connection. Main's ranks are unchanged afterwards. The plan assertions above run on both connections.\n- **Missing path.** A subprocess Engine start with `--trending-db <missing>`, the same way `test_server_config.py` drives the entry point, must exit non-zero, show the path in stderr, and leave no file at that path. The same test covers a non-SQLite file. This start fails before binding or opening `whitelist.db`, so it needs no start lock.\n- **Full-suite run with a real fill.** The build reads the fingerprint read-only before its full suite run and compares it afterwards. The shared DB currently holds a real fill (the triage found 86,826 rows with `fetched_at > 0`).\n\n### Alternatives considered\n\n- **Schema-qualified SQL**, for example a `trending` source string chosen per call or a schema argument passed through `fetch_ordered_page`, `fetch_popular_videos`, the builder deps and the handler. Rejected: it changes signatures and SQL on the default path, and touches several files to support a dev-only override. The requirement asks for unchanged behaviour and SQL without the flag. The view keeps every query untouched.\n- **A bare `ATTACH` with no view.** Rejected: as the requirements note, `main.trending_ranks` already exists in `whitelist.db` and comes before attached databases in name lookup, so it would silently keep serving the shared table.\n- **Opening the private file as `main` and attaching `whitelist.db`.** Rejected: every other table, and every write (moderation, interaction events), would then resolve against the wrong file.\n- **Rebuilding `server.db` with URI handling (`uri=True` in `connect_db`) so that `ATTACH` could use `mode=rw`.** Rejected: it changes `connect_db` for every caller to tighten one race that the validation step already covers.\n- **Seeding by opening the shared DB `mode=ro` and attaching the temp file.** Rejected: unqualified `trending_ranks` would then resolve to the shared, read-only main, so the INSERT would fail or need qualified SQL. Opening the temp file as main and attaching the shared DB keeps `TRENDING_SEED_SQL` verbatim.\n- **Copying `whitelist.db` per session.** Rejected: it is multi-GB and isolates far more than the requirement asks for.\n\n### Gotchas and risks\n\n- **Plain `ATTACH` creates a missing file**, because `server.db` is not a URI connection. The no-create guarantee therefore comes from the `mode=rw` validation that runs just before. If the file is deleted in the gap between validation and attach, an empty file would be created and Trending would serve empty, without falling back to the shared table. I am accepting this as a named limitation. The way up is a URI-enabled `server.db`.\n- **Relying on the query flattener.** If a future SQLite version or a view edit stops flattening, the plan would gain a scan or sort with the flag set, but default-path plans would be untouched. The flagged-plan test catches this.\n- **The seed still reads the shared DB for a few seconds** under a SHARED lock, because the DB is in rollback-journal mode. That can delay, but not block for good, a writer's commit on the shared file, such as the dev Engine's interaction ingest or an updater run. The write lock and the 5 s busy-timeout collision are gone, which is what the requirement is about. The suite's `dataset` reads already behave this way.\n- **External changes to the fingerprint.** If the operator's updater fills `trending_ranks` during a suite run, the in-suite fingerprint gate goes red without the suite being at fault. The failure message should say so.\n- **Relative paths.** A relative PATH resolves against the Engine's working directory, unlike the repo-root-relative default DB paths. The fixture passes an absolute path, and the help text says the path is used as given.\n- **Seed drift.** The private seed is still built from the live catalogue, so the existing caveat about the NSFW control (one flagged row in the first 96) is unchanged.\n\n### Tradeoffs the operator is asked to accept\n\n- **Engine code exists only for tests.** A dev/test flag ships in the production entry point, using a connection-level trick (a TEMP view shadowing a main table) that someone reading the SQL alone would not expect. A comment at the view creation and the help text explain it.\n- **No guarantee that the file cannot be created** (the race above). It is a documented ceiling, not a hard guarantee.\n- **Out of scope, as agreed.** Other suite writes to `whitelist.db` stay: bridge interaction events, and the unflagged Engines in `test_random_cache.py` and `test_server_config.py`.",
  "conflicts": "none",
  "impacts": "\n<impact path=\"engine/server/api/server.py\" element=\"parse_args() (lines 153-203): new --trending-db PATH argument\">\n**What changes:** add one `parser.add_argument(\"--trending-db\", default=None, help=(...))`. Put it after the `refresh_group` block and before `parser.set_defaults(random_cache_refresh=None)` / `return parser.parse_args()`. Follow the existing `help=(...)` multi-string style. Argparse derives `dest` as `trending_db`, so `args.trending_db` is `None` when the flag is absent. Per the plan, the help text should say four things: it is a dev/test override; only `trending_ranks` is read from PATH; PATH must exist and is never created; the path is used as given, so a relative one resolves against the working directory. The parser uses `CompactHelpFormatter` (`scripts/cli_format.py`), so the metavar renders as `--trending-db TRENDING_DB` unless `metavar=\"PATH\"` is given. Match whatever the tests assert.\n\n**What depends on it:**\n- `tests/active/test_server_config.py::test_server_py_exits_before_argument_parsing_on_a_bad_value` (line 78) runs `server.py --help` and asserts `\"--port PORT\" in ok.stdout`. A new option does not affect that line.\n- The systemd unit `peertube-engine@.service` (`DEPLOYMENT.md:111`, `ExecStart=... server.py --host 127.0.0.1 --port %i`) does not pass the flag.\n- `scripts/run-services.sh:35` does not pass it either.\n- The test runners pass argv through: `CACHE_VARIANT_RUNNER` in `test_random_cache.py:138` and `VARIANT_RUNNER` in `test_server_config.py:204-216` both set `sys.argv = [server, *sys.argv[3:]]`.\n\n**Regression risk:** low. The flag is optional with a `None` default, and there are no mutually-exclusive interactions.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"main() startup sequence (lines 326-338): validate PATH before connect_db, ATTACH + TEMP VIEW after it, skip ensure_trending_schema(db) when flagged\">\n**What changes:**\n- **Before line 332** (`db = connect_db(db_path)`): when `args.trending_db` is set, call the new helper's validation step. It opens `file:<path>?mode=rw` with `uri=True`, runs `ensure_trending_schema`, closes the connection, and turns any `sqlite3.Error` into `SystemExit(<message naming the path>)`.\n- **After `connect_db`:** ATTACH the file under a fixed schema name and `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`.\n- **Line 337** (`ensure_trending_schema(db)`, with its comment at 336) becomes conditional on the flag being unset.\n\nOrdering matters:\n- ATTACH cannot run inside an open transaction. Right after `connect_db` none is open. Every `ensure_*` uses `executescript`, which commits first, so placing the ATTACH after line 339 is also safe.\n- `ensure_moderation_schema`, `ensure_interaction_event_schema`, `ensure_channels_indexes` and `ensure_video_indexes` use unqualified `CREATE ... IF NOT EXISTS`. An unqualified CREATE targets main, and the private file holds no tables with those names, so these are unaffected whether the attach comes before or after them.\n- `channels.py:46` and `videos.py:11-14` probe `sqlite_master`, which is main only, so they are unaffected.\n\nOther details:\n- A `SystemExit` raised before the `try/finally` at 516 leaves the SIGINT/SIGTERM handlers swapped. This is harmless because the process is exiting. `assert_index_matches_embeddings` (line 368) already exits the same way.\n- The log line at 494 (`db=%s index=%s total=%d`) is the natural place to also log the override path. This is optional. No test parses that line (`test_server_config.py` parses only `upnext_config` and `ann_nprobe_configured`).\n- The new name added to `from data.trending import ensure_trending_schema` (line 110) must exist in `trending.py`. `server.py` is imported in Engine-interpreter children by `tests/active/test_internal_events.py:47` and `tests/active/test_video.py:163,199`, so an `ImportError` there breaks those suites.\n\n**What depends on it:** every unqualified `trending_ranks` read on `server.db` (the handler's ordered feed and the popular layer). `search_db` (line 333, `connect_readonly_db`) and the random-cache worker's own connection (`run_random_cache_worker(db_path, ...)`, line 500) do not read `trending_ranks` (grep for `trending` in `data/search.py` and `data/random_cache.py` finds nothing), so they need no view.\n\n**Regression risk:**\n- **Medium for the flagged path:** step order, the transaction state at ATTACH, and the view name colliding with `main.trending_ranks`. SQLite allows a temp object to shadow a main one; I expect that and have not run it.\n- **Low for the default path,** provided the unflagged branch stays byte-for-byte as it is. The phase test should check that line 337 still runs when the flag is absent: \"without the flag, Trending reads whitelist.db\".\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"SimilarServer.__init__ self.db (line 242) and main()'s finally db.close() (line 533)\">\n**What changes:** nothing.\n\nThe plan's claim checks out. `self.db = db` is the only assignment: a grep for `\\.db\\s*=` under `engine/server` finds only `server.py:242` and an unrelated test double in `db/jobs/tests/test-moderation-integration.py:942`. A per-connection TEMP view and ATTACH therefore last for the life of the process. `db.close()` at 533 releases the attachment along with the connection.\n\n**What depends on it:** every handler that uses `server.db` under `db_lock`. The writers on this connection are ingest (`internal_events.py:66-74`), the video write-back (`video.py:389-432`) and the raw prune (`internal_events.py:111`). They write main tables only, and a transaction that writes only main never needs a lock on the attached file.\n\n**Regression risk:** low. Any write transaction that also read the view holds a SHARED lock on the private file until commit. Nothing else writes that file while the Engine runs, so there is no contention.\n</impact>\n<impact path=\"engine/server/data/trending.py\" element=\"ensure_trending_schema (lines 8-25) unchanged, plus a NEW helper next to it (validate PATH with mode=rw and apply the schema; ATTACH + CREATE TEMP VIEW on a connection)\">\n**What changes:** add one small function, or two. Keep the module's style: `from __future__ import annotations`, `import sqlite3`, a one-line docstring per function, and comments on a single line. One reasonable shape:\n- `prepare_trending_override(path)`: the `mode=rw` open plus `ensure_trending_schema`, raising `SystemExit` or returning.\n- `attach_trending_override(conn, path)`: `ATTACH DATABASE ? AS <schema>` followed by `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`.\n\nA comment at the view should explain the shadowing, as the plan requires. ATTACH accepts a bound parameter for the filename, so the path needs no quoting.\n\nOn a non-URI connection such as `connect_db`, a plain ATTACH creates a missing file. That is the named race; the `mode=rw` check is what guards against it.\n\nA 0-byte existing file passes validation: SQLite treats it as an empty database, and `ensure_trending_schema` creates the table in it. Trending then serves an empty page rather than failing. This is consistent with \"must already exist\", but say so in the help text or a test if it matters.\n\n**What depends on it:**\n- `ensure_trending_schema` is imported by `engine/server/api/server.py:110`, `engine/server/db/jobs/fetch-trending.py:28` and the tests (`test_random_videos.py:78`, `test_similar.py:101`, `test_moderation.py:29`, `test_popular_videos.py:37`).\n- `tests/active/conftest.py:132-134` loads this file by path under the module name `active_trending_schema`.\n- The signature of `ensure_trending_schema(conn)` must not change.\n- The new helper will be used by `server.main()`, the new in-process tests in `test_random_videos.py`, and possibly the `dataset` fixture (see that entry).\n\n**Regression risk:** low for the existing function, which is untouched. The new helper carries the flattening and plan risk; see `random_videos.py`.\n</impact>\n<impact path=\"engine/server/data/db.py\" element=\"connect_db (77-82) and connect_readonly_db (85-94): unchanged, used as precedent\">\n**What changes:** nothing. The plan rejected adding `uri=True` to `connect_db`.\n\nPoints relevant to the build:\n- `connect_db` calls `sqlite3.connect(path.as_posix(), check_same_thread=False)` without `uri=True`. ATTACH on it therefore takes a plain filename, and a `file:...?mode=rw` URI string would be treated as a literal filename.\n- `connect_readonly_db` is the URI precedent (`f\"file:{path.as_posix()}?mode=ro\"`, `uri=True`). Validation should use the same form with `mode=rw`.\n- A path containing `?` or `#` would need URI escaping in the validation open. This is a minor edge case that the fixture's temp path does not hit.\n- The deadline progress handler (`install_deadline_handler`) is per connection, so statements reading the attached file are bounded by `statement_deadline` exactly as before.\n\n**What depends on it:** every Engine connection.\n\n**Regression risk:** none if left untouched.\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"ORDERED_FEED_SOURCE['trending'] (36-42), ORDERED_FEED_ORDER_BY['trending'] (16-22), fetch_ordered_page (241-334), fetch_popular_videos (234-238): unchanged, resolved through the view\">\n**What changes:** no edit. With the flag set, `trending_ranks t CROSS JOIN video_embeddings e ON ...` resolves `trending_ranks` to the TEMP view, because name lookup goes temp, then main, then attached. `t.rank`, `t.likes`, `t.views`, `t.video_id` and `t.instance_domain` in the ORDER BY are view columns, since the view is `SELECT *`.\n\nThe expected flattened plan is `SCAN t USING INDEX idx_trending_ranks_order` (now on the attached schema) with no `USE TEMP B-TREE FOR ORDER BY`. That is an expectation only: SQLite 3.53.4 ships in the engine pixi env (`engine/.pixi/envs/default/lib/libsqlite3.so.3.53.4`), and I could not run EXPLAIN QUERY PLAN to confirm it. The pytest interpreter's sqlite version may differ from the Engine's, which matters if the plan test runs in-process under pytest rather than under `ENGINE_PY`. The existing plan test (`test_random_videos.py:222-240`) runs in-process.\n\n**What depends on it:**\n- `handlers/similar.py:777-784` (`_handle_ordered_feed`, using `self.server.db` under `db_lock`).\n- `recommendations/builder.py:114-116` (`fetch_popular_videos_filtered`) \u2192 `candidates/popular_videos.py:53` (`server.db` under `db_lock`).\n- `tests/active/test_similar.py:764` (`_reference`, run on `dataset`; see the HIGH entry).\n- `test_random_videos.py` (33 uses).\n- `test_popular_videos.py`.\n- `test_video.py:220` (deps wiring).\n\n**Regression risk:**\n- Default path: none, since the SQL is untouched.\n- Flagged path: medium. If flattening does not happen, the order is still correct but the plan gains a scan or sort. The 5 s statement deadline (`DEPLOYMENT.md:453`) could then bite on deep pages with a full 88k-row seed.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"_handle_ordered_feed (759-806) and FEED_MODES/ORDERED_FEED_MODES (105-107)\">\n**What changes:** nothing. It reads `self.server.db`, which is the connection that carries the view, under `db_lock`, then applies serving moderation.\n\n**What depends on it:**\n- `test_similar.py:819` (`test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order...[trending]`).\n- The NSFW listing test (`test_similar.py:1043`, `mode=trending`).\n- The child-process handler test (`test_similar.py:961`), which uses its own temp DB.\n\n**Regression risk:** none in the code. The test-side risk is covered in the `test_similar.py` entries.\n</impact>\n<impact path=\"engine/server/api/recommendations/candidates/popular_videos.py\" element=\"PopularVideosGenerator.get_candidates line 53 (fetch_popular_videos(server.db, ...)); and engine/server/api/recommendations/builder.py fetch_popular_videos_filtered (114-116)\">\n**What changes:** nothing. The plan states that no signature changes. The pool read goes through `server.db`, so it is covered by the view.\n\n**What depends on it:**\n- The Recommendations mix's popular layer.\n- `test_popular_videos.py`, which runs a child on a temp DB and is unaffected.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/api/recommendations/builder.py\" element=\"RecommendationBuilderDeps.fetch_popular_videos (line 60) and fetch_popular_videos_filtered (114-116)\">\n**What changes:** nothing. It is listed because the plan's rejected alternative would have threaded a schema argument through here. Under the chosen approach the deps and settings stay identical, and `test_video.py:220` builds `RecommendationBuilderDeps` by keyword and would break on any added required field.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/data/moderation.py\" element=\"_host_table_column_pairs (308-319), purge_host_data (194-), _count_host_rows (322-338), _table_exists (415-421)\">\n**What changes:** nothing. This is out of scope per the issue.\n\nI verified the plan's claim:\n- `purge_host_data` callers are `instance-denylist-cli.py:190,222,227`, `updater-worker.py:619,642` and `db/jobs/tests/test-moderation-integration.py:874,907,1022`.\n- The test callers are `test_moderation.py` and `test_ann.py`.\n- None is in `engine/server/api`.\n\nWith the flag set, the Engine therefore has no write path to the shared `trending_ranks`.\n\n`_table_exists` queries `sqlite_master`, which covers main only and never sees the TEMP view. If a purge were ever run on a flagged connection, it would count and delete the shared `main.trending_ranks`, not the private file. That is a latent trap, but it is unreachable today.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"engine/server/db/jobs/fetch-trending.py\" element=\"run() calling ensure_trending_schema (line 102); writes to trending_ranks (117-119)\">\n**What changes:** nothing. It is out of scope per the issue. It depends on `ensure_trending_schema(conn)` keeping its signature and behaviour.\n\n**Regression risk:** none, as long as `trending.py`'s existing function is untouched. `tests/active/test_fetch_trending.py` gates it.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"trending stage (1431-1469) and purge_host_data callers (619, 642)\">\n**What changes:** nothing. It keeps writing the shared `trending_ranks` on the operator's schedule.\n\n**What depends on it:** the new fingerprint gate. An updater run during a suite run changes the shared fingerprint and turns the in-suite gate red without the suite being at fault. The plan names this; the failure message should say so.\n\n**Regression risk:** none in the code. The test-flake risk is acknowledged.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"trending_seed fixture (126-144) and TRENDING_SEED_SQL (107-123)\">\n**What changes:**\n- The fixture becomes `trending_seed(tmp_path_factory)` and returns a path. The seed target is `tmp_path_factory.mktemp(...) / \"trending.db\"`.\n- Open it with `sqlite3.connect(f\"file:{path}\", uri=True)` or equivalent, so that URI ATTACH works. Then run `trending.ensure_trending_schema(conn)`, `ATTACH DATABASE 'file:<WHITELIST_DB>?mode=ro' AS ...`, and `TRENDING_SEED_SQL` verbatim inside `with conn:`.\n- Drop the `DELETE FROM trending_ranks`. The table is fresh, and keeping the delete would be harmless anyway because it resolves to the temp file's main.\n- Drop the `ENGINE_START_LOCK` block.\n\n`TRENDING_SEED_SQL` stays unchanged. Its unqualified `trending_ranks` resolves to the temp file's main (main before attached), and `videos` and `video_embeddings` exist only in the attached shared DB. The comment on line 107 (\"every lane writes the same rows\") should be reworded, because each lane now writes its own file.\n\nThe fixture keeps loading `trending.py` by file spec (lines 132-134). If the new helper is reused here, for example for the `dataset` fix, it is available on the same module object.\n\n**What depends on it:** the `engine` fixture (line 148) and, if the HIGH `dataset` fix is taken, the `dataset` fixture.\n\n**Regression risk:** medium.\n- **Same rows:** the rows must match today's exactly (ranks, likes, views, `fetched_at = 0`) for `test_similar`'s NSFW control. `TRENDING_SEED_SQL` is unchanged, but the ROW_NUMBER tie order is defined by `views DESC, likes DESC, video_id DESC`, which is deterministic, so this should hold.\n- **URI handling:** if the seed connection is not opened with `uri=True`, `ATTACH 'file:...?mode=ro'` silently creates a file literally named `file:...` in the CWD instead of opening the shared DB read-only. The seed would then fail with \"no such table: videos\". That is loud, not silent.\n- **Lock:** the seed now holds a SHARED lock on the shared file for a few seconds, which the plan names as a risk.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"engine fixture (147-186)\">\n**What changes:**\n- Add `\"--trending-db\", str(trending_seed)` next to `\"--no-random-cache-refresh\"` in the Popen argv (lines 162-163). It needs an absolute path, which `tmp_path_factory` provides.\n- Keep the `ENGINE_START_LOCK` loop.\n- Update the comment at 155-156 if it should mention the override.\n\n**What depends on it:** every session-Engine test (`engine_client`, `unpublished_client`, `test_similar`, `test_server_config.py:270`, `test_random_cache`, profiles and so on).\n\nA start that fails validation is retried 5 times by the loop (lines 159-179), each retry sleeping `1 + attempt` seconds, before `assert proc.poll() is None` fails. A seed bug would therefore show up as \"Engine exited on every start\" after about 15 s, with the cause in `engine.log`.\n\n**Regression risk:** medium, because every Engine-backed test depends on this start succeeding.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"module docstring (lines 1-14), ENGINE_START_LOCK constant (104-106), imports fcntl/tempfile (17, 25)\">\n**What changes:** rewrite docstring lines 6-11. \"after `trending_seed` has rewritten that dataset's `trending_ranks`\" becomes a description of the private per-session seed and the `--trending-db` flag. If the `dataset` fixture changes, its description must change as well.\n\n`ENGINE_START_LOCK` stays. Its importers are:\n- `tests/active/test_random_cache.py:44` (used at 297).\n- `tests/active/test_server_config.py:39` (used at 254).\n- `tests/archive/short_similarity_cache/test_similar.py:129` (skipped).\n- `conftest`'s own `engine` fixture.\n\n`fcntl` and `tempfile` stay in use (the engine fixture and `ENGINE_START_LOCK`).\n\n**Regression risk:** low. These are text-only changes, and `ImportError`s are avoided by keeping the constant.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"dataset fixture (228-233): HIGH, the plan's claim that no session test reads trending_ranks through dataset is wrong\">\n**What changes:** the plan says nothing changes here. In fact `tests/active/test_similar.py:759-766` `_reference(dataset, order, threshold)` calls `fetch_ordered_page(dataset, order, REFERENCE_DEPTH, 0, ...)`. For `order == \"trending\"`, that reads `trending_ranks` from the shared `whitelist.db` through `dataset`.\n\nToday this agrees with the Engine because both read the seeded shared table. After the change, the Engine serves the private seed while `dataset` reads the operator's real fill (86,826 rows with `fetched_at > 0` per the triage). The assertion `first + following + last == reference[: 3 * FEED_PAGE]` (`test_similar.py:849`) therefore fails for the `trending` parametrization. That breaks the acceptance criterion \"the active suite passes ... with no test expectations changed\".\n\nOptions, which the build has to choose between:\n- **(a)** Make `dataset` depend on `trending_seed` and, after opening it `mode=ro` (a URI connection, so URI ATTACH works), apply the same ATTACH + TEMP VIEW helper to the private file. The expectation is unchanged and `_reference` is untouched. The cost: every test that uses `dataset` now triggers the seed, which is session-scoped and a few seconds, once per lane. I believe a TEMP view can be created on a `mode=ro` connection because the temp schema stays writable, but I have not verified it. Attaching with `mode=ro` keeps the private file read-only there too.\n- **(b)** A separate session fixture, for example `trending_dataset`, prepared that way and used only by `_reference` for `trending`. This changes test code but not expected values.\n\n`dataset` is used by test_blocks, test_dislike_profile, test_dislikes, test_frontend_* , test_profiles, test_random_cache, test_server and test_similar. With (a), the shared file gets one more read-only reader holding the seed's SHARED lock window. The plan's in-suite \"pages equal merged-rank order computed from the temp file joined with the read-only dataset\" test needs exactly this prepared connection, so the helper is needed in the tests either way.\n\n**Regression risk:** high. Without action, `test_similar.py::test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` goes red whenever the shared table differs from the seed, which is always once a real fill exists.\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"_reference (759-766), test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated (818-849) for order=trending, module docstring line 64\">\n**What changes:** depends on the `dataset` decision above. With option (a), nothing in this file changes. The docstring line 64 says \"read through the read-only `dataset` connection\", which stays true, though it should perhaps mention that `dataset` carries the private Trending ranks. With option (b), `_reference` picks the prepared connection for `trending`, and docstring line 64 must say so.\n\nThe re-read control at line 836 (`_reference(...) == reference`) still holds with either option, because the private file is static for the session. With the unfixed shared read it would also hold, but an updater run mid-test would break it.\n\n**What depends on it:** the `trending` parametrization of `ORDERED`, read from `handlers.similar.ORDERED_FEED_MODES` at collection (`test_similar.py:743-746`).\n\n**Regression risk:** high if missed (see above).\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"NSFW listing control for mode=trending (comment 997-999, test 1043) and nsfw_flagged (1009)\">\n**What changes:** nothing. The comment at 998 says the control \"was rehearsed with exactly one flagged row in the first 96 seeded Trending rows; the seed is derived from the live whitelist.db\". The private seed is built by the same SQL from the same live catalogue, so the Engine serves the same rows. `nsfw_flagged` reads `videos.nsfw` through `dataset`, not `trending_ranks`.\n\n**What depends on it:** the seed producing identical rows.\n\n**Regression risk:** low. The existing seed-drift caveat is unchanged, as the plan says.\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"_ranks_db / _TRENDING_HANDLER_CHILD / test_the_handler_serves_trending_until_the_ranked_rows_run_out... (852-990)\">\n**What changes:** nothing. It runs `SimilarHandler` on a stub server over its own temp DB in an Engine-interpreter child, without the `engine` fixture and without the flag.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_random_videos.py\" element=\"test_a_trending_page_walks_the_ranks_index_without_sorting (222-240), _plan/_Recorder (198-219), _schema (119-128), imports (74-78); NEW flagged-plan and flag-on/flag-off in-process tests\">\n**What changes:**\n- The plan adds an `EXPLAIN QUERY PLAN` test on a helper-prepared connection, beside the existing unflagged one. It also adds an in-process test: main DB with ranks A, private file with ranks B; `fetch_ordered_page` and `fetch_popular_videos` serve A on a plain connection and B on a prepared one; main's ranks are unchanged afterwards.\n- `_plan` can be reused as is. It records the SQL via `_Recorder` and runs `EXPLAIN QUERY PLAN` on the same connection, so the view is in scope.\n- The prepared connection's main must hold `videos`, `video_embeddings`, `channels` and `trending_ranks` (`_schema` already builds all of them). The private file needs `ensure_trending_schema` and rows.\n- The module docstring (lines 1-54) lists every claim, so new tests need new docstring bullets in the same style.\n- The import at line 78 grows the new helper name.\n\n**What depends on it:** `tests/config.json` group `test_random_videos.py` already maps `engine/server/data/trending.py`.\n\n**Regression risk:** low for the existing tests, which are unchanged. The new plan assertion's index-name check (`\"idx_trending_ranks_order\" in detail`) should still match an attached-schema index. That is unverified.\n</impact>\n<impact path=\"tests/active/test_server_config.py\" element=\"subprocess Engine driving pattern (_run 47-52, VARIANT_RUNNER 204-217, _start_variant 252-267), ENGINE_START_LOCK import (39); likely home of the missing-path/non-SQLite subprocess test\">\n**What changes:** the plan's missing-path test copies this file's pattern: `subprocess.run([str(ENGINE_PY), str(ENGINE_SERVER), \"--trending-db\", missing, ...], capture_output=True, ...)`. It asserts a non-zero return code, the path in stderr, and no file at the path. It also covers a non-SQLite file. No start lock is needed, because validation runs before `connect_db` and binding.\n\nThe process still imports `server_config` and initialises logging before validation. A missing `ENGINE_PY` should be handled the way the other tests here handle it.\n\n`_start_variant` (254-258) starts an unflagged Engine on the shared DB. That is out of scope per the plan, but it means `ensure_trending_schema(db)` runs on shared `whitelist.db` during the suite. `CREATE ... IF NOT EXISTS` on an existing table writes nothing, so the fingerprint is unaffected.\n\n**What depends on it:** the `--help` control at 80-82.\n\n**Regression risk:** low.\n</impact>\n<impact path=\"tests/active/test_random_cache.py\" element=\"ENGINE_START_LOCK import (44), _cache_variant (286-323), concurrent unflagged starts (796-811)\">\n**What changes:** nothing. These keep importing `ENGINE_START_LOCK` and start Engines without `--trending-db` on the shared DB. That is out of scope per the plan. Like any unflagged start, they run `ensure_trending_schema(db)` on shared, which is a no-op when the table exists and leaves the fingerprint unchanged.\n\n**Regression risk:** none, provided the constant is kept in conftest.\n</impact>\n<impact path=\"tests/archive/short_similarity_cache/test_similar.py\" element=\"imports ENGINE_START_LOCK etc. from conftest (docstring line 3, use at 129)\">\n**What changes:** nothing. It is skipped, but its docstring says it depends on conftest's `ENGINE_START_LOCK`. Keeping the constant keeps it importable.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_moderation.py\" element=\"ensure_trending_schema import (29) and use (105)\">\n**What changes:** nothing. It depends on `ensure_trending_schema(conn)` being unchanged.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_fetch_trending.py\" element=\"trending_ranks schema check (251-259), job tests\">\n**What changes:** nothing. It depends on `ensure_trending_schema` behaviour. Its missing-`--db` subprocess test (251) is the precedent for the new missing `--trending-db` test (exit non-zero, no file created).\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_popular_videos.py\" element=\"ensure_trending_schema import (37), child-process mix over temp DB (195-255)\">\n**What changes:** nothing. Its temp DB holds `trending_ranks` in main, and no flag is involved.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"tests/active/test_internal_events.py\" element=\"Engine-interpreter child that does `import server` (line 47) and builds SimilarServer\">\n**What changes:** nothing directly. However, it imports `engine/server/api/server.py` at module level, so a broken new import line (for example, a helper name that does not exist in `data/trending.py`) fails this suite. It does not call `main()` or `parse_args`, so the flag logic itself is not exercised.\n\n**Regression risk:** low.\n</impact>\n<impact path=\"tests/active/test_video.py\" element=\"Engine-interpreter children that `import server` (163, 199) and build RecommendationBuilderDeps (220)\">\n**What changes:** nothing. As with `test_internal_events.py`, this imports `server.py`, so the module-level imports must resolve. Line 220 constructs `RecommendationBuilderDeps` by keyword, which confirms the plan's choice not to add fields there.\n\n**Regression risk:** low.\n</impact>\n<impact path=\"tests/active (NEW fingerprint gate: session fixture + in-suite test; location TBD, conftest.py plus test_similar.py or a new file)\">\n**What changes:** add a session fixture that reads the shared `trending_ranks` fingerprint read-only before `trending_seed` and `engine` run: `COUNT(*)`, `MIN(fetched_at)`, `MAX(fetched_at)` and the count with `fetched_at > 0`, read via a `file:...?mode=ro` URI, as `dataset` does.\n\nTo guarantee it runs before the seed, `trending_seed` or `engine` should depend on it. Pytest instantiates fixtures in dependency order, but with no dependency two independent session fixtures may run in either order.\n\nThe in-suite test requests `mode=trending` pages and a popular-layer request from the session Engine, then compares them to the merged-rank order computed from the temp file joined with `dataset` under the NSFW filter. It needs the same prepared connection as the HIGH `dataset` entry, then re-reads the fingerprint. Its failure message must name the external-updater possibility.\n\nA popular-layer request shows its source only with `debug=1`; the session Engine runs `RECOMMENDATIONS_DEBUG=1`. Check how the popular rows can be identified, for example from debug layer tags in the response. I did not verify the debug payload shape.\n\n**What depends on it:** `trending_seed`, `engine`, `dataset`.\n\n**Regression risk:** medium: a flaky external-change failure, and fixture ordering.\n</impact>\n<impact path=\"tests/config.json\" element=\"test_groups (14-...)\">\n**What changes:** if a new test file is created, for example for the flag subprocess test or the fingerprint gate, add a `test_groups` entry mapping it to `engine/server/api/server.py` and `engine/server/data/trending.py`. If the tests land in existing files, consider adding `engine/server/data/trending.py` to `test_server_config.py`'s group (130-133), which today lists only `server_config.py` and `server.py`. `test_random_videos.py` (112-118) and `test_similar.py` (54-71) already map `trending.py`. `conftest.py` is mapped nowhere.\n\n**Regression risk:** low. This is metadata for the test runner and validator.\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"referenced by conftest docstring line 7 as how the Engine is started\">\n**What changes:** nothing. The conftest docstring says the engine fixture starts the Engine \"the way `tests/run-arch-split-smoke.sh` does\". After the change the fixture also passes `--trending-db`, so that comparison should be qualified in the docstring rewrite. The script itself (no `trending` match) is untouched.\n\n**Regression risk:** none.\n</impact>\n<impact path=\"scripts/run-services.sh\" element=\"ENGINE_SCRIPT launch (35) and process matching (205, 234)\">\n**What changes:** nothing. The flag is not passed, and the dev Engine on :7070 keeps reading the shared `trending_ranks`, which is the point of the fix.\n\n**Regression risk:** none.\n</impact>\n",
  "docs_checklist": "- [x] `docs/project/issues/44-trending-seed-write-lock-during-test-runs.md` - updated: Issue 44 is now marked `bug, complete` with a Delivered comment, and the archived copy is at `docs/project/issues/archive/`. The old file at `docs/project/issues/` still has to be deleted, because I can't delete files.\n- [x] `engine/server/README.md` - out of scope: The README lists no Engine CLI flags. The requirements only ask for the flag to be documented here \"if it lists Engine flags\", and it does not. Its one sentence on the subject (line 26, \"Trending serves only videos ranked in `trending_ranks`, so it answers an empty page until the updater's trending stage ... first fills that table\") is still true. A production Engine never gets the flag (systemd unit, `scripts/run-services.sh`), and a flagged Engine still serves only rows ranked in a `trending_ranks` table, just the one in PATH. The flag is documented where the requirements make it mandatory: the `--trending-db` `help=(...)` text in `server.py` `parse_args` covers the dev/test override, that only `trending_ranks` is read from PATH, that PATH must exist and is never created, and relative-path resolution.\n- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - out of scope: Line 101 (\"`trending_ranks` is created empty when the Engine starts\") describes the deployed Engine, which never passes `--trending-db`. On that path the unflagged branch of `server.py` `main()` is the original `ensure_trending_schema(db)` line, unchanged. The flagged case applies the schema to the private file. That is a test-isolation detail outside this document's subject (the updater and its first fill), so mentioning it here would add a dev/test aside to an operator runbook.\n- [x] `tests/active/conftest.py` - out of scope: Phase 3 already brought every named passage up to date, and the diff confirms it:\n- [x] `tests/active/test_similar.py` - out of scope: Phase 3 took option (a) and already updated the ordered-mode bullet in the module docstring. The `dataset` reference is now described as \"read through the read-only `dataset` connection (whose Trending ranks are the session's private seed, as the Engine's are)\". The `_feed_constants` docstring names the popular pool size it now returns. The NSFW control comment (\"the seed is derived from the live whitelist.db\") is still true, because the private seed is built by the same SQL from the same live catalogue. The docstring bullet for the phase 3 test is added when the harvest moves that test into this file, not by this step.\n- [x] `tests/active/test_random_videos.py` - out of scope: The build did not edit this file, and no new test is in it yet. Both phase 1 checkpoints are still in `tests/tmp`, and the harvest plan (`docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md`, awaiting approval) moves them here as DURABLE. The module docstring is still accurate for the tests it lists. The two new claim bullets (the flag-on/flag-off order and pool test, and the override plan test) go in with that move, since a bullet for a test not yet in the file would be false.\n- [x] `tests/active/test_server_config.py` - out of scope: Not on the checklist; listed for completeness. Like `test_random_videos.py`, it gains the `--trending-db` missing/non-SQLite start test only when the harvest moves it, and its docstring bullet goes with that move. Its current docstring makes no claim the build changed. Unflagged starts on the shared DB behave as before.\n- [x] `CONTEXT.md` - out of scope: Not on the checklist; checked because line 20 (**Trending**) says the lists \"are stored per host in `whitelist.db` `trending_ranks`\". That is still the domain definition and the production state. `--trending-db` is a dev/test isolation override, and the issue triage and requirements say explicitly that CONTEXT.md does not change.\n- [x] `DEPLOYMENT.md` - out of scope: Not on the checklist; checked because lines 87, 195 and 453 describe `trending_ranks`:\n- [x] `DATA_BUILD.md` - out of scope: Not on the checklist; checked because line 329 says Trending and the popular layer are empty until `trending_ranks` is filled. That is still true for every production Engine, and the document covers data builds, not test isolation.\n- [x] `docs/project/adr/0010-trending-from-source-instances.md` - out of scope: The ADR covers where Trending comes from and how it is stored and refreshed. It says nothing about test data or alternative rank sources, and the issue triage confirmed it \"does not cover test data\". The build leaves the Trending definition, the schema, the job and the production read path unchanged.",
  "docs": [
    {
      "path": "engine/server/README.md",
      "note": "Optional, uncertain whether wanted. Line 26 says \"Trending serves only videos ranked in `trending_ranks`\". The plan documents the flag only in `--help`, because the README lists no Engine flags; I confirmed it has none. If one sentence is wanted, it would read: \"a dev/test `--trending-db PATH` makes the Engine read `trending_ranks` from PATH instead (see `--help`)\". Otherwise there is no change."
    },
    {
      "path": "engine/server/db/jobs/docs/UPDATER_WORKER.md",
      "note": "Line 101 (\"**First fill.** `trending_ranks` is created empty when the Engine starts\") stays true for every production start. With `--trending-db` the Engine applies the schema to PATH, not to `whitelist.db`. This is a dev/test nuance, so a change is optional. I am flagging it only so the doc step can make a deliberate choice."
    },
    {
      "path": "docs/project/issues/44-trending-seed-write-lock-during-test-runs.md",
      "note": "On delivery, set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md` and `issue-tracker.md`. Tick the acceptance criteria and record the named limitation: the validation-to-ATTACH race can create an empty file."
    },
    {
      "path": "tests/active/conftest.py",
      "note": "Module docstring lines 6-11: describe the per-session private seed file and `--trending-db` instead of \"`trending_seed` has rewritten that dataset's `trending_ranks`\", and update the `dataset` description if that fixture gains the private view. Also update the `trending_seed` docstring (128-130, which today cites the \"operator decision (issue 38 build)\" and the start lock), the `engine` fixture comment, and the comment at line 107 (\"every lane writes the same rows\")."
    },
    {
      "path": "tests/active/test_similar.py",
      "note": "Docstring line 64 says the ordered-feed reference is \"read through the read-only `dataset` connection\". Update it if the trending reference moves to a prepared connection, which is option (b). Under option (a), consider noting that `dataset` carries the session's private Trending ranks."
    },
    {
      "path": "tests/active/test_random_videos.py",
      "note": "Module docstring (lines 1-54): add bullets for the new flagged `EXPLAIN QUERY PLAN` test and the flag-on/flag-off in-process test, in the existing claim style."
    }
  ],
  "reassessments": 1,
  "draft": "## Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/trending.py` | Two new functions next to the unchanged `ensure_trending_schema`: `prepare_trending_override(path)` and `attach_trending_override(conn, path)`, plus one constant. |\n| `engine/server/api/server.py` | One new argument in `parse_args`. In `main()`: validate before `connect_db`, then either the unchanged `ensure_trending_schema(db)` or the attach. One conditional log line. The import line grows by two names. |\n| `tests/active/conftest.py` | `trending` is loaded once at module level. New fingerprint helper and fixture. `trending_seed` writes a private temp file. `engine` passes the flag. `dataset` carries the private view (option (a) from the HIGH impact entry). Docstrings rewritten. |\n| `tests/active/test_random_videos.py` | New tests: the plan with the flag set, and flag on vs flag off in-process. Docstring bullets for both. |\n| `tests/active/test_server_config.py` | New subprocess test: `--trending-db` on a missing path or a non-SQLite file. `--help` control. |\n| `tests/active/test_similar.py` | New in-suite gate: the session Engine serves the private ranks (Trending pages and the popular layer), and the shared fingerprint is unchanged. Docstring line 64 updated. |\n| `tests/config.json` | Add `engine/server/data/trending.py` to the `test_server_config.py` group. |\n\nNothing else changes. That includes `random_videos.py` and its SQL, `similar.py`, `popular_videos.py`, `builder.py`, `db.py` (`connect_db` stays non-URI), `moderation.py` and `fetch-trending.py`. `engine/server/README.md` gets no edit because it lists no Engine flags, so `--help` is the documentation. That was the plan's call and I kept it.\n\n## Ladder, per piece\n\n- **Shadowing `trending_ranks`:** a native platform feature is enough (rung 4). A SQLite `ATTACH` plus a `TEMP VIEW` on the existing connection means no SQL and no signature changes.\n- **No-create validation:** stdlib `sqlite3` with a `mode=rw` URI (rung 3). It mirrors the `mode=ro` precedent in `connect_readonly_db`.\n- **Schema on the private file:** reuses `ensure_trending_schema` (rung 2).\n- **Seed:** reuses `TRENDING_SEED_SQL` unchanged and attaches the shared DB read-only (rung 2 plus rung 4).\n- **Test reference for Trending:** reuses `attach_trending_override` on `dataset` (rung 2). `_reference` and every expectation stay as they are.\n- **CLI:** argparse, in the file's existing `help=(...)` style.\n\n## `engine/server/data/trending.py` (additions)\n\n```python\nimport sqlite3  # already imported\n\n# The schema name the --trending-db file is attached under.\nTRENDING_OVERRIDE_SCHEMA = \"trending_override\"\n\n\ndef prepare_trending_override(path: str) -> None:\n    \"\"\"Check that an existing SQLite file is at `path` and apply the trending schema to it, exiting with a message naming the path otherwise.\"\"\"\n    # mode=rw never creates the file, as connect_readonly_db's mode=ro does not; a file that is not SQLite fails on the schema statement.\n    try:\n        conn = sqlite3.connect(f\"file:{path}?mode=rw\", uri=True)\n        try:\n            ensure_trending_schema(conn)\n        finally:\n            conn.close()\n    except sqlite3.Error as exc:\n        raise SystemExit(f\"trending ranks file {path} cannot be opened as SQLite: {exc}\") from exc\n\n\ndef attach_trending_override(conn: sqlite3.Connection, path: str) -> None:\n    \"\"\"Make every unqualified trending_ranks read on `conn` read the table in the file at `path`.\"\"\"\n    conn.execute(f\"ATTACH DATABASE ? AS {TRENDING_OVERRIDE_SCHEMA}\", (str(path),))\n    # Names resolve temp, then main, then attached, so a bare ATTACH leaves main.trending_ranks in front; this TEMP view shadows it, and SQLite flattens it so the Trending page still walks idx_trending_ranks_order.\n    conn.execute(f\"CREATE TEMP VIEW trending_ranks AS SELECT * FROM {TRENDING_OVERRIDE_SCHEMA}.trending_ranks\")\n```\n\n**Invariants:**\n- `ensure_trending_schema(conn)` is byte-for-byte unchanged. `fetch-trending.py`, `server.py` and four test files depend on it.\n- `prepare_trending_override` never creates a file and never touches `whitelist.db`. On any `sqlite3.Error` it raises `SystemExit(str)`. Python prints that message to stderr and exits with status 1, and the message contains `path` verbatim.\n- A 0-byte existing file passes validation and gets the table, so Trending serves empty. The help text says so: \"an empty file counts\".\n- `attach_trending_override` must be called outside a transaction, because ATTACH fails inside one. Its two callers both call it on a connection that has no open transaction:\n  - `server.main()`, right after the `executescript`-based ensures, which commit first;\n  - the `dataset` fixture, on a fresh connection.\n- It works on a `mode=ro` URI connection. The attached file inherits the connection's read-only open flags, and the temp schema is opened read-write regardless (SQLite opens the temp DB with its own READWRITE|CREATE flags). I reasoned this from SQLite's behaviour and have not run it. The `dataset` fixture fails loudly if it is wrong.\n- The `path` given to ATTACH is a bound parameter, so it needs no quoting. On a non-URI connection a plain path is taken literally. On a URI connection a plain path that does not begin with `file:` is also taken literally.\n- **Named ceiling: URI escaping.** A PATH containing `?` or `#` is not URI-escaped in the validation open, so it fails validation (loudly) instead of opening. That is the same ceiling as `connect_readonly_db`. The way up is `urllib.parse.quote` on the path.\n\n## `engine/server/api/server.py`\n\nImport at line 110:\n\n```python\nfrom data.trending import attach_trending_override, ensure_trending_schema, prepare_trending_override\n```\n\nIn `parse_args`, after the `refresh_group` block and before `parser.set_defaults(random_cache_refresh=None)`:\n\n```python\n    parser.add_argument(\n        \"--trending-db\",\n        metavar=\"PATH\",\n        default=None,\n        help=(\n            \"Dev/test override: read only the trending_ranks table from PATH; every other \"\n            \"table still comes from whitelist.db. PATH must be an existing SQLite file (an \"\n            \"empty file counts) and is never created; the table and its index are created \"\n            \"in it if missing. A relative PATH resolves against the working directory.\"\n        ),\n    )\n```\n\nWith `metavar=\"PATH\"`, `--help` renders `--trending-db PATH`, and the test asserts that string.\n\nIn `main()`, lines 332-339 become:\n\n```python\n    if args.trending_db is not None:\n        # Before whitelist.db is opened, so a bad path stops the start without touching it or loading the index.\n        prepare_trending_override(args.trending_db)\n    db = connect_db(db_path)\n    search_db = connect_readonly_db(db_path)\n    ensure_moderation_schema(db)\n    ensure_interaction_event_schema(db)\n    if args.trending_db is None:\n        # Created empty before the first fill, so a Trending read is an empty page, never \"no such table\".\n        ensure_trending_schema(db)\n    else:\n        # The shared trending_ranks is neither created nor read on this connection; the file at PATH stands in for it.\n        attach_trending_override(db, args.trending_db)\n    ensure_channels_indexes(db)\n    ensure_video_indexes(db)\n```\n\nAfter the `db=%s index=%s` log line (494), add:\n\n```python\n    if args.trending_db is not None:\n        logging.info(\"[similar-server] trending_db=%s (trending_ranks only)\", args.trending_db)\n```\n\n**Why this order:**\n- Validation runs before `connect_db`, so a bad path exits in under a second. Nothing has opened `whitelist.db` at that point and FAISS has not loaded.\n- The attach goes after the two `executescript` ensures, so no transaction is open.\n- The later `ensure_channels_indexes` and `ensure_video_indexes` create unqualified indexes on main tables and probe `sqlite_master`, which is main-only. The private file holds neither table, so they are unaffected.\n- `search_db` and the random-cache worker's own connection read no `trending_ranks`, so they get no view.\n- `server.db` is assigned once (`SimilarServer.__init__:242`), so the view lasts as long as the process.\n\n**Default path:** the unflagged branch runs the same statements in the same order as today. The only differences are the `if`, which is not taken, and the second `if`, whose true branch is the original line 337. The SQL and the plans are unchanged.\n\n## `tests/active/conftest.py`\n\nModule level, replacing the lazy spec load inside `trending_seed`:\n\n```python\n_TRENDING_SPEC = importlib.util.spec_from_file_location(\"active_trending_schema\", ROOT / \"engine\" / \"server\" / \"data\" / \"trending.py\")\nTRENDING = importlib.util.module_from_spec(_TRENDING_SPEC)\n_TRENDING_SPEC.loader.exec_module(TRENDING)\n# The shared trending_ranks fingerprint: rows, fetched_at bounds and real-fill rows; main. so a connection carrying the private view still reads the shared table.\nTRENDING_FINGERPRINT_SQL = \"SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at), COUNT(CASE WHEN fetched_at > 0 THEN 1 END) FROM main.trending_ranks\"\n\n\ndef shared_trending_fingerprint() -> tuple:\n    \"\"\"The shared whitelist.db trending_ranks fingerprint, read on a fresh read-only connection.\"\"\"\n    conn = sqlite3.connect(f\"file:{WHITELIST_DB}?mode=ro\", uri=True)\n    try:\n        return tuple(conn.execute(TRENDING_FINGERPRINT_SQL).fetchone())\n    finally:\n        conn.close()\n\n\n@pytest.fixture(scope=\"session\")\ndef shared_trending_before():\n    \"\"\"The shared fingerprint before the private seed is built and the session Engine starts.\"\"\"\n    return shared_trending_fingerprint()\n```\n\nThe comment above `TRENDING_SEED_SQL` (line 107) changes its ending to: \"...deterministic, so every lane's private file holds the same rows.\" `TRENDING_SEED_SQL` itself is unchanged.\n\n```python\n@pytest.fixture(scope=\"session\")\ndef trending_seed(tmp_path_factory, shared_trending_before):\n    \"\"\"A per-session private trending_ranks file the session Engine reads through --trending-db, so its Trending order has rows without the network fetch and the shared whitelist.db is never written.\n\n    The catalogue is read from whitelist.db attached read-only; the only file written is this one.\n    \"\"\"\n    path = tmp_path_factory.mktemp(\"trending\") / \"trending.db\"\n    # A URI connection, so the shared DB attaches with mode=ro rather than as a literal filename.\n    conn = sqlite3.connect(f\"file:{path}\", uri=True)\n    try:\n        TRENDING.ensure_trending_schema(conn)\n        conn.execute(\"ATTACH DATABASE ? AS shared\", (f\"file:{WHITELIST_DB}?mode=ro\",))\n        # trending_ranks resolves to this file's main, ahead of the attached copy; videos and video_embeddings exist only in the shared DB.\n        with conn:\n            conn.execute(TRENDING_SEED_SQL)\n    finally:\n        conn.close()\n    return path\n```\n\n`shared_trending_before` appears as a parameter only to order the fixtures: pytest then reads the fingerprint before the seed and the Engine.\n\n`engine` fixture: the argv becomes\n\n```python\n                    [str(ENGINE_PY), str(ENGINE_SERVER), \"--host\", \"127.0.0.1\", \"--port\", str(port),\n                     \"--no-random-cache-refresh\", \"--trending-db\", str(trending_seed)],\n```\n\n`ENGINE_START_LOCK` and the retry loop stay. Comment line 156 gains: \"Trending is read from the private seed file (--trending-db), never the shared table.\"\n\n`dataset` fixture:\n\n```python\n@pytest.fixture(scope=\"session\")\ndef dataset(trending_seed):\n    conn = sqlite3.connect(f\"file:{WHITELIST_DB}?mode=ro\", uri=True)\n    conn.row_factory = sqlite3.Row\n    # Trending reads the session Engine's private ranks here too, so a reference order computed on this connection is the one the Engine serves.\n    TRENDING.attach_trending_override(conn, trending_seed)\n    yield conn\n    conn.close()\n```\n\n**Module docstring, lines 6-11, rewritten:** `engine` starts the real Engine from its pixi env on the repo's dataset, once per session, the way `tests/run-arch-split-smoke.sh` does but with `--trending-db` naming `trending_seed`'s per-session private file, so the suite never writes the shared `trending_ranks`. `engine_client` and `unpublished_client` are as before. `dataset` is `whitelist.db` opened read-only with that private file attached and shadowing `trending_ranks`, so it is the independent source of a video's channel, account and embedding, and of the Trending order the session Engine serves. `shared_trending_fingerprint` reads the shared table's fingerprint.\n\n**Kept:** the `ENGINE_START_LOCK` constant, which three importers use, and the `fcntl` and `tempfile` imports, which are still used.\n\n## Tests: what each one gates\n\n**1. `test_random_videos.py` (in-process, pytest interpreter).** It imports `attach_trending_override` and `prepare_trending_override` from `data.trending`.\n\n- **`test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`**\n  - Setup: `_schema(main.db)` gets the same 30\u00d7100 ranked catalogue plus 1,000 unranked rows as the existing plan test, built by a shared local builder factored from that test. Its `main.trending_ranks` is left empty. The ranks are written into `private.db` after `prepare_trending_override`. `attach_trending_override(conn, private)`.\n  - Assertions: `_plan(conn, \"trending\")` contains `idx_trending_ranks_order` and no `TEMP B-TREE`. The control is that `_plan(conn, \"popular\")` contains `TEMP B-TREE`.\n  - The existing unflagged plan test stays as it is.\n- **`test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`**\n  - Setup: main is `_ranks_db` (ranks A, giving `TRENDING_EXPECTED`). The private file gets the same keys with ranks B, a hand-derived different order, for example `TRENDING_EXPECTED` reversed, written as rank 1..n with equal likes and views.\n  - A plain connection on main serves A through `fetch_ordered_page(..., \"trending\", ...)` and `fetch_popular_videos`. A second connection on the same main file, prepared with `attach_trending_override`, serves B for both.\n  - Afterwards `main.trending_ranks` rows are unchanged, read on the plain connection.\n  - Control: A \u2260 B.\n- **Docstring:** two new bullets in the claim style.\n- **Interpreter note:** this runs under pytest's `sqlite3`, not the Engine's 3.53.4, as the existing plan test also does. The Engine-side plan is covered indirectly by test 3: deep pages on the session Engine succeed within the 5 s deadline.\n\n**2. `test_server_config.py::test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`** (subprocess, no start lock).\n\n- **Missing path:** `_run([str(ENGINE_PY), str(API_DIR / \"server.py\"), \"--port\", str(_free_port()), \"--trending-db\", str(missing)], None)` with `missing = tmp_path / \"absent.db\"`. Expect `returncode != 0`, `str(missing)` in stderr, and `not missing.exists()`.\n- **Non-SQLite file:** the same call on `tmp_path / \"junk.db\"` containing 4 KB of non-SQLite bytes. Expect non-zero, the path in stderr, and the file bytes unchanged.\n- **Control:** `server.py --help` exits 0 and its stdout contains `--trending-db PATH`.\n- **Timing:** a red start would load FAISS and bind. The test bounds `_run`'s timeout and fails if the process is still alive. `_run` already uses `timeout=120`, and validation runs before `connect_db`, so the expected run time is about 1 s.\n\n**3. `test_similar.py::test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(engine, dataset, shared_trending_before)`**\n\n- **Discrimination control:** the shared head (`fetch_ordered_page` on a fresh plain `mode=ro` connection, first `3 * FEED_PAGE`) differs from `_reference(dataset, \"trending\", threshold)`. If they are equal, the failure message says the shared table holds no real fill, so this test cannot tell the two sources apart.\n- **Trending pages:** three `mode=trending` pages, walked with `exclude` as in the existing ordered test, equal `_reference(dataset, \"trending\", ...)[: 3 * FEED_PAGE]`.\n- **Popular layer:** an unseeded home request (`POST /recommendations?limit=<page>&debug=1`, body `{}`, its own rate-bucket header). Every row with `debug.layer == \"popular\"` must lie in `fetch_popular_videos(dataset, POOL)`, the private head. `POOL` is the Engine's `DEFAULT_POPULAR_POOL_SIZE`, read in the Engine-interpreter child that `_feed_constants` already runs (one more key). Control: at least one popular row is served.\n- **Fingerprint:** `shared_trending_fingerprint() == shared_trending_before`. The failure message names an operator updater run (the trending stage) as a possible external cause.\n- **Docstring line 64:** the ordered-feed reference is read through `dataset`, which carries the session's private Trending ranks.\n\n**4. Existing tests, unchanged expectations:**\n- `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` now compares the Engine with `dataset`, and both read the private file.\n- The NSFW control at 1043 reads the same seeded rows.\n\n**5. Build-level, not a test.** Before the build's full suite run, record `shared_trending_fingerprint()` with a one-shot `python -c` against `whitelist.db` `mode=ro`, and compare after. It must be identical, with `count(fetched_at > 0)` > 0.\n\n## Checked against requirements and plan\n\n| Requirement | Met by |\n|---|---|\n| Flag in `--help`, existing style | `parse_args` addition, `metavar=\"PATH\"` |\n| Every `server.db` Trending read uses PATH | TEMP view resolves before main for `fetch_ordered_page` and `fetch_popular_videos`. No other connection reads `trending_ranks`. |\n| No write to shared `trending_ranks`, including at startup | `ensure_trending_schema(db)` is skipped when flagged. The schema goes to PATH in `prepare_trending_override`. The Engine has no purge path. |\n| Missing or non-SQLite PATH: non-zero exit, path in message, no file created | `mode=rw` open plus schema statement \u2192 `SystemExit(...path...)` before `connect_db`. Test 2. |\n| Default unchanged; plan uses the index with no TEMP B-TREE, with and without the flag | Unflagged branch is the original statements. Existing plan test plus test 1. |\n| Private seed with identical rows, shared read-only, only the temp file written | `trending_seed` uses verbatim `TRENDING_SEED_SQL`, shared attached `mode=ro` |\n| Seed drops the lock, `engine` keeps it, constant stays | as drafted |\n| Docstrings updated | module, `trending_seed`, `engine` comment, `dataset` comment, line-107 comment, `test_similar` line 64, `test_random_videos` bullets |\n| In-suite fingerprint gate plus build before/after | test 3, step 5 |\n| Suite green with no expectation changed | option (a): `dataset` carries the view, `_reference` untouched |\n\n## Decisions and deviations\n\n**The settled plan was wrong about `dataset`.** It said no session test reads `trending_ranks` through `dataset`. The impact inventory's HIGH entry showed that `test_similar._reference` does. I took option (a): `dataset` depends on `trending_seed` and carries the same view. It reuses the one helper, changes no test code or expectations, and costs one session seed per lane, which `engine` already pays.\n\n**Named limitations:**\n- **Validation-to-ATTACH race.** If the file vanishes in between, plain ATTACH on non-URI `server.db` creates it empty, and Trending then serves empty, never shared. The way up is a URI-enabled `connect_db`.\n- **Unescaped `?` or `#` in PATH.** These fail validation instead of opening.\n- **Reliance on the query flattener.** This is gated by test 1.\n- **SHARED lock during the seed.** The seed holds a SHARED lock on the shared file for a few seconds, which can delay but not block a writer.\n- **External changes during a run.** The fingerprint gate goes red if the operator's updater changes the shared ranks mid-run. Its message names that cause.\n\n**Not done:**\n- No README edit, because it has no flag list.\n- No `UPDATER_WORKER.md` edit, because line 101 stays true for every production start.\n- No URI escaping helper.\n- No logging change other than one conditional line.",
  "coordination": "Phase 3 needs no credential or live endpoint. It does depend on local operator state. The local `whitelist.db` must hold a real `trending_ranks` fill (more than 0 rows with `fetched_at > 0`; triage found 86,826), or the discrimination control fails by design. The operator's updater trending stage must not run during the suite run, or the fingerprint gate goes red for a reason outside the suite. The same applies to the build-level before/after fingerprint around the full suite run.",
  "tests": {
    "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py": {
      "rows": [
        {
          "clause": "C1a",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:84 \u2014 on the prepared connection, fetch_ordered_page(prepared, \"trending\", 100, 0) labels equal OVERRIDE_EXPECTED",
          "expected": "[\"B5\", \"A3\", \"E\", \"A2\", \"C2\", \"B2\", \"A1\", \"B1\", \"X\", \"C1\"]",
          "wrong_implementation": "A bare ATTACH with no shadowing leaves main.trending_ranks resolved first. It serves TRENDING_EXPECTED (the reverse order), and the probe saw this fail."
        },
        {
          "clause": "C1b",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:85 \u2014 on the prepared connection, fetch_popular_videos(prepared, 100) labels equal OVERRIDE_EXPECTED",
          "expected": "OVERRIDE_EXPECTED",
          "wrong_implementation": "An override that reaches the page read but misses the pool, or a bare ATTACH. Either one serves TRENDING_EXPECTED."
        },
        {
          "clause": "C1c",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:70 and :86 \u2014 on the plain connection, fetch_ordered_page \"trending\" labels equal TRENDING_EXPECTED, both before the override exists and after the prepared connection has read",
          "expected": "[\"C1\", \"X\", \"B1\", \"A1\", \"B2\", \"C2\", \"A2\", \"E\", \"A3\", \"B5\"]",
          "wrong_implementation": "An attach that copies the file's ranks into main.trending_ranks, or that switches the source for every connection. Under it, :86 serves OVERRIDE_EXPECTED; the probe saw it fail with 'B5' != 'C1'."
        },
        {
          "clause": "C1d",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:71 \u2014 on the plain connection, fetch_popular_videos(plain, 100) labels equal TRENDING_EXPECTED",
          "expected": "TRENDING_EXPECTED",
          "wrong_implementation": "A pool that does not read main's trending_ranks order. It serves the catalogue in some other order."
        },
        {
          "clause": "C1e",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:87 \u2014 sorted rows of main.trending_ranks equal `written`, which line 68 rebuilds from harness.RANKS",
          "expected": "The 12 ranked RANKS rows (GHOST and U included), as (host, video_id, rank, likes, views, 0)",
          "wrong_implementation": "A committed copy, delete or rewrite of main.trending_ranks by prepare or attach. Under it, main holds the file's ranks or no rows, which differs from `written`."
        },
        {
          "clause": "C2a",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:105 \u2014 the prepared connection's Trending EXPLAIN QUERY PLAN names idx_trending_ranks_order. It is armed by :95 (main is empty) and by the full 50-row page check inside _plan at :104",
          "expected": "A detail like 'SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order'",
          "wrong_implementation": "A temp copy of the ranks, or a view that loses the index. The plan reads 'SCAN t' with no index name, as the probe saw."
        },
        {
          "clause": "C2b",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:106 \u2014 the prepared connection's Trending plan has no 'TEMP B-TREE' detail. The Popular plan control at :102 shows the capture can surface a sort",
          "expected": "No detail contains TEMP B-TREE",
          "wrong_implementation": "An unindexed shadow table. It plans 'SCAN t' plus 'USE TEMP B-TREE FOR ORDER BY', as the probe saw."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "On a connection prepared by `attach_trending_override`, `fetch_ordered_page` for `trending` and `fetch_popular_videos` serve the attached file's ranks. On an unprepared connection to the same main they serve main's ranks, and main's ranks are left unchanged."
        },
        {
          "id": "C2",
          "text": "On a connection prepared by `attach_trending_override`, the Trending page's query plan uses `idx_trending_ranks_order` and contains no `TEMP B-TREE`."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_44_trending_seed_write_lock_during_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_44_trending_seed_write_lock_during_phase1.py  2 failed                               0.0s\n  -----------------------------------------------------------\n  total                                                        2 failed                               0.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_44_trending_seed_write_lock_during_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "test_44_trending_seed_write_lock_during_phase2.py:67, :68, :70: for the missing `absent.db`, `run.returncode != 0`, `str(missing) in run.stderr`, and `\"unrecognized arguments\" not in run.stderr` (armed by the controls at :62\u2013:63)",
          "expected": "A non-zero exit, with stderr naming the absent path through the Engine's own SystemExit message and not through argparse's rejection. This is predicted. Today :67\u2013:68 hold only because argparse rejects the flag; that was observed.",
          "wrong_implementation": "With the flag never added (today's code), :70 goes red. Observed: stderr \"server.py: error: unrecognized arguments: --trending-db /tmp/.../absent.db\", and the test currently fails at :70. With the flag added but no check, the server serves and `_run` raises TimeoutExpired at 120 s. With a check whose message leaves out the path, :68 goes red."
        },
        {
          "clause": "C1",
          "assertion": "test_44_trending_seed_write_lock_during_phase2.py:76, :77, :78: the same three assertions for the 4096-byte non-SQLite `junk.db`",
          "expected": "A non-zero exit, with the junk path in stderr and no \"unrecognized arguments\". This is predicted, because the run stops at :70 today.",
          "wrong_implementation": "A check that only tests `Path.exists()`, or a bare `sqlite3.connect` with no query, lets the junk file through. The server then serves, and `_run` times out and raises. A generic \"file is not a database\" message with no path makes :77 go red."
        },
        {
          "clause": "C1",
          "assertion": "test_44_trending_seed_write_lock_during_phase2.py:88: `_starts_serving(valid, log_path)`. An existing SQLite file passed as `--trending-db` reaches the Engine's `service.lifecycle` start within 120 s.",
          "expected": "True: the check passes it and the Engine serves. Observed on today's code without the flag: the same Popen and `_has_started` loop reached the lifecycle start in about 1.1 s, and terminate gave rc 0. Also observed: today, with the flag, this start exits 2 with \"unrecognized arguments: --trending-db .../valid.db\". That the built flag reaches the start on this file is predicted.",
          "wrong_implementation": "A check that rejects every PATH, for example an unconditional `parser.error(f\"--trending-db {path}: not a SQLite file\")`. It satisfies :67\u2013:79 but exits before the lifecycle start, so `_has_started` is False and :88 goes red, showing the log tail."
        },
        {
          "clause": "C2",
          "assertion": "test_44_trending_seed_write_lock_during_phase2.py:71: `not missing.exists()` after the failed start",
          "expected": "True: `absent.db` is never created. Today this is true because argparse exits first (observed); after the build it is predicted.",
          "wrong_implementation": "A check that runs a plain `sqlite3.connect(path)`, or uses `mode=rwc`, before rejecting. That creates `absent.db`, so :71 goes red."
        },
        {
          "clause": "C2",
          "assertion": "test_44_trending_seed_write_lock_during_phase2.py:79: `junk.read_bytes() == JUNK`, the 4096-byte literal that was written",
          "expected": "The file's bytes are exactly the bytes written.",
          "wrong_implementation": "An implementation that truncates, re-initialises or replaces a non-SQLite file before or instead of rejecting it, for example by deleting it and recreating the schema. The bytes then differ, so :79 goes red."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Starting `server.py` with `--trending-db` on a missing path or a non-SQLite file exits non-zero, with that path in stderr."
        },
        {
          "id": "C2",
          "text": "The failed start leaves the path as it was: a missing path is not created, and a non-SQLite file's bytes are unchanged."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_44_trending_seed_write_lock_during_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_44_trending_seed_write_lock_during_phase2.py  1 failed                               0.0s\n  -----------------------------------------------------------\n  total                                                        1 failed                               0.8s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_44_trending_seed_write_lock_during_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:80 \u2014 the session Engine is asked for three `mode=trending` pages (limit FEED_PAGE, each excluding the rows already served). Together they must equal `harness._reference(dataset, \"trending\", threshold)[: 3 * FEED_PAGE]`, the private seed's order read through `dataset` with its private view. This is armed by :67 (the private order holds three pages) and :70 (the shared head, read on a fresh plain mode=ro connection, differs from the private head).",
          "expected": "The 36 keys of the private seed's Trending head, in order. Observed this turn: an Engine started with `--trending-db` on a private seed built from TRENDING_SEED_SQL served a first `mode=trending&limit=12` page equal to the private head[:12] (probe_phase3_engine_popular.py: \"matches private head[:12] True\"). The checkpoint's own run has not reached :80 yet, because it stops at :55 on the fixture the phase adds.",
          "wrong_implementation": "The Engine is started without `--trending-db`, or the flag never shadows `trending_ranks` on `server.db`, so the Engine serves the shared real-fill head. Observed this turn on an unflagged Engine (probe_phase3_unflagged_engine.py): its first page shared 1 of 12 keys with the private head. Across 36 rows the shared and private heads share only 7 keys, so :80 goes red. An empty private file returns empty pages, which also makes :80 red."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:87 \u2014 the test sends an unseeded `POST /recommendations?limit=2*BATCH_SIZE&debug=1`. Every row it returns with `debug.layer == \"popular\"` must be in `fetch_popular_videos(dataset, POOL, error_threshold=threshold, include_nsfw=False)`, the private pool. This is armed by :85 (at least one popular row is served) and :73 (at least a quarter of the shared pool lies outside the private pool; observed 3003 of 5000).",
          "expected": "`outside == []`. Observed this turn on an Engine started with `--trending-db`: three limit=96 requests each served 20 popular rows, all 20 in the private pool, and 4, 6 and 7 of them were also in the shared pool. The checkpoint's own run has not reached :87 yet, because it stops at :55.",
          "wrong_implementation": "The override reaches `fetch_ordered_page` but not the popular pool's `fetch_popular_videos(server.db, ...)`, or the Engine is started without the flag. Popular rows then come from the shared pool. Observed this turn on an unflagged Engine: 10, 13 and 9 of the 20 popular rows fell outside the private pool, so `outside` is non-empty and :87 goes red."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:90 \u2014 `conftest.shared_trending_fingerprint()`, read after the Engine has served, must equal `before`. `before` is `shared_trending_before`, requested first at :55 so that it is read before the seed is built and the Engine starts. This is armed by :59: the shared table holds rows with `fetched_at > 0`.",
          "expected": "The same tuple before and after: (86826, 1791035941189, 1791035941189, 86826). That value was read read-only this turn and stayed unchanged across a flagged Engine start-and-serve, an unflagged one, and the private seed build (all three probes printed it before and after).",
          "wrong_implementation": "A `trending_seed` that still writes into the shared `whitelist.db`. The old seed's `DELETE FROM trending_ranks` plus `TRENDING_SEED_SQL` replaces the table with the seed's 88648 rows (count observed this turn in the private copy), all with `fetched_at = 0`. That makes the fingerprint (88648, 0, 0, 0) instead of the real fill, and :90 goes red. :59 shows the last field starts above 0, so a rewrite cannot leave the fingerprint unchanged. An Engine start that writes the shared `trending_ranks` would also show up here."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "The session Engine's Trending pages and its popular-layer rows follow the private seed file's ranks, not the shared table's."
        },
        {
          "id": "C2",
          "text": "The shared `whitelist.db` `trending_ranks` fingerprint (row count, `fetched_at` min and max, rows with `fetched_at > 0`) is identical before the seed and after the session Engine has served."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_44_trending_seed_write_lock_during_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_44_trending_seed_write_lock_during_phase3.py  1 failed                               0.0s\n  -----------------------------------------------------------\n  total                                                        1 failed                               0.4s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nBoth tests fail when `_private_file` calls `trending.prepare_trending_override(str(path))`\nat line 31. The call raises AttributeError because engine/server/data/trending.py defines\nonly `ensure_trending_schema`. The first test reaches it from line 72, after the\nunprepared-connection assertions at lines 70\u201371 pass. The second reaches it from line 96,\nafter the empty-main control at line 95 passes. No C1 or C2 assertion (lines 84\u201387,\n102\u2013106) runs before the code is in place.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The test uses no pytest fixture apart from\n   `tmp_path`. It loads its harness (`_ranks_db`, `_schema`, `_plan`, `_trending_labels`,\n   `RANKS`, `TRENDING_EXPECTED`) by path from tests/active/test_random_videos.py, and I\n   read those definitions at lines 86\u2013219.\n2. `random_videos.fetch_ordered_page` and `random_videos.fetch_popular_videos` are not in\n   `code_under_test`, so I did not read them. I answered the stub question from the\n   assertion form and the harness.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | prepared conn: `fetch_ordered_page` \"trending\" serves the attached file's ranks | :84 | a plain ATTACH with no shadowing, which leaves `main.trending_ranks` first and serves the reversed list `TRENDING_EXPECTED` | CARRIED |\n| C1b | must_prove | prepared conn: `fetch_popular_videos` serves the attached file's ranks | :85 | an override that reaches the page read and misses the pool | CARRIED |\n| C1c | must_prove | unprepared conn on the same main: Trending page serves main's ranks | :70, :86 | an override that writes main or switches the source for every connection; :86 reads after the prepared connection has read | CARRIED |\n| C1d | must_prove | unprepared conn on the same main: popular pool serves main's ranks | :71 | a pool that does not read main's `trending_ranks` order (the pool is the head of the Trending order, `random_videos.py:237`) | CARRIED |\n| C1e | must_prove | main's ranks are left unchanged | :87 | a committed copy, delete or rewrite of `main.trending_ranks`. The expected rows are rebuilt from `RANKS` at :68, not read back from the code | CARRIED |\n| C2a | must_prove | prepared conn: Trending plan uses `idx_trending_ranks_order` | :105 (with `_plan`'s full-page check at :104 and the empty-main control at :95) | a temp copy or view that loses the index. Main's empty table also has an index by this name, but a full 50-row page can only come from the file | CARRIED |\n| C2b | must_prove | prepared conn: Trending plan has no `TEMP B-TREE` | :106 | an unindexed shadow that plans SCAN plus USE TEMP B-TREE FOR ORDER BY | CARRIED |\n| D1 | docstring | \"a connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file\" | :84, :85 | a plain ATTACH that reads main | CARRIED |\n| D2 | docstring | \"a plain connection on the same main reads main's\" | :70, :71, :86 | an override that leaks to other connections | CARRIED |\n| D3 | docstring | private file holds \"the same keys ranked in `OVERRIDE_EXPECTED`\", a different order | :67 | a fixture where the two orders match, which would make :84 and :85 pass on main's ranks | CARRIED |\n| D4 | docstring | plain serves `TRENDING_EXPECTED` from both `fetch_ordered_page` and `fetch_popular_videos` | :70, :71 | either read ignoring main's ranks | CARRIED |\n| D5 | docstring | prepared serves `OVERRIDE_EXPECTED` \"from both\" | :84, :85 | an override covering only one read | CARRIED |\n| D6 | docstring | \"the plain connection still serves `TRENDING_EXPECTED` afterwards\" | :86 | an override that persists across connections | CARRIED |\n| D7 | docstring | \"`main.trending_ranks` holds exactly the rows written to it\" | :87 | added, removed or rewritten rows in main | CARRIED |\n| D8 | docstring | main DB \"whose own `trending_ranks` is empty\" | :95 | ranks present in main, which would let a plain ATTACH fill the page | CARRIED |\n| D9 | docstring | ranks \"written to a private file after `prepare_trending_override`\" (file gets the schema and index) | :98 / :105 | a prepare that creates no table (the insert at :98 fails) or no index (:105 fails) | CARRIED |\n| D10 | docstring | \"the prepared connection reads a full Trending page from the file\" | :104 (`_plan`, `tests/active/test_random_videos.py:217`) | a plain ATTACH serving 0 rows from main's empty table | CARRIED |\n| D11 | docstring | \"its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order`\" | :105 | a plan that skips the index | CARRIED |\n| D12 | docstring | \"and has no `TEMP B-TREE`\" | :106 | a plan that sorts | CARRIED |\n| D13 | docstring | \"the same capture for Popular shows the temp B-tree (control)\" | :102 | a plan capture that cannot show a sort, which would make :106 pass vacuously | CARRIED |\n| D14 | docstring | `_private_file`: an existing empty file given the trending schema | :98 / :105 | a prepare that leaves the file without schema | CARRIED |\n| D15 | docstring | `_private_file`: `prepare_trending_override` \"never creates one\" | none | nothing. :30 always `touch()`es the file first, so a prepare that creates a missing file passes | UNCARRIED |\n| N1 | name | test 1: \"trending and the popular pool read main ranks without the override\" | :70, :71, :86 | either read on the plain conn not serving main's order | CARRIED |\n| N2 | name | test 1: \"and the file's ranks with it\" | :84, :85 | a plain ATTACH or an override covering one read only | CARRIED |\n| N3 | name | test 2: \"a trending page on the override file\" | :104 with control :95 | a page not served from the file (main is empty) | CARRIED |\n| N4 | name | test 2: \"walks its ranks index\" | :105 | a plan without `idx_trending_ranks_order` | CARRIED |\n| N5 | name | test 2: \"without sorting\" | :106 | a plan with `TEMP B-TREE` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:29\n   `\"\"\"An existing empty file at `path`, given the trending schema by `prepare_trending_override`, which never creates one.\"\"\"`\n   D15 is UNCARRIED. The helper's docstring says `prepare_trending_override` never creates a file, and :30 `path.touch()` always creates the file before the call. No path in this file calls prepare on a missing file and checks that nothing appeared. Either assert it, or cut the sentence back to what the helper does. This is not a `must_prove` clause, so it does not block.\n2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31, :38\n   Only the success path of the two helpers runs. Neither `prepare_trending_override` nor `attach_trending_override` is ever run on a missing or non-SQLite path, so the expected failure mode is untested here.\n3. bounds (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:82\n   Every prepared connection has a populated override file. Nothing covers a prepared connection whose file has the schema and no rows. That case would show whether the Trending page and pool come back empty or fall back to main's ranks, and it is the edge between \"the file's ranks\" and \"main's ranks\" in C1.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/data/trending.py (EDITED). As read, it defines only `ensure_trending_schema`. It has no `prepare_trending_override` or `attach_trending_override`, and no definition exists anywhere outside docs/project/plans. So I could not judge from the code which inputs the helpers accept or how they fail. Recommendations 2 and 3 rest on the test file and on `random_videos.py:37` and `:237` only.\n2. tests/active/test_random_videos.py was read only in part: lines 86\u2013245, which cover `RANKS`, `TRENDING_EXPECTED`, `_schema`, `_ranks_db`, `_trending_labels` and `_plan`. Its module header was not read, so the imports and `sys.path` setup the harness exec at :18 depends on were not checked.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nBoth tests fail when `_private_file` calls `trending.prepare_trending_override(str(path))`\nat line 31. The call raises AttributeError because engine/server/data/trending.py defines\nonly `ensure_trending_schema`. The first test reaches it from line 72, after the\nunprepared-connection assertions at lines 70\u201371 pass. The second reaches it from line 96,\nafter the empty-main control at line 95 passes. No C1 or C2 assertion (lines 84\u201387,\n102\u2013106) runs before the code is in place.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The test uses no pytest fixture apart from\n   `tmp_path`. It loads its harness (`_ranks_db`, `_schema`, `_plan`, `_trending_labels`,\n   `RANKS`, `TRENDING_EXPECTED`) by path from tests/active/test_random_videos.py, and I\n   read those definitions at lines 86\u2013219.\n2. `random_videos.fetch_ordered_page` and `random_videos.fetch_popular_videos` are not in\n   `code_under_test`, so I did not read them. I answered the stub question from the\n   assertion form and the harness.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | prepared conn: `fetch_ordered_page` \"trending\" serves the attached file's ranks | :84 | a plain ATTACH with no shadowing, which leaves `main.trending_ranks` first and serves the reversed list `TRENDING_EXPECTED` | CARRIED |\n| C1b | must_prove | prepared conn: `fetch_popular_videos` serves the attached file's ranks | :85 | an override that reaches the page read and misses the pool | CARRIED |\n| C1c | must_prove | unprepared conn on the same main: Trending page serves main's ranks | :70, :86 | an override that writes main or switches the source for every connection; :86 reads after the prepared connection has read | CARRIED |\n| C1d | must_prove | unprepared conn on the same main: popular pool serves main's ranks | :71 | a pool that does not read main's `trending_ranks` order (the pool is the head of the Trending order, `random_videos.py:237`) | CARRIED |\n| C1e | must_prove | main's ranks are left unchanged | :87 | a committed copy, delete or rewrite of `main.trending_ranks`. The expected rows are rebuilt from `RANKS` at :68, not read back from the code | CARRIED |\n| C2a | must_prove | prepared conn: Trending plan uses `idx_trending_ranks_order` | :105 (with `_plan`'s full-page check at :104 and the empty-main control at :95) | a temp copy or view that loses the index. Main's empty table also has an index by this name, but a full 50-row page can only come from the file | CARRIED |\n| C2b | must_prove | prepared conn: Trending plan has no `TEMP B-TREE` | :106 | an unindexed shadow that plans SCAN plus USE TEMP B-TREE FOR ORDER BY | CARRIED |\n| D1 | docstring | \"a connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file\" | :84, :85 | a plain ATTACH that reads main | CARRIED |\n| D2 | docstring | \"a plain connection on the same main reads main's\" | :70, :71, :86 | an override that leaks to other connections | CARRIED |\n| D3 | docstring | private file holds \"the same keys ranked in `OVERRIDE_EXPECTED`\", a different order | :67 | a fixture where the two orders match, which would make :84 and :85 pass on main's ranks | CARRIED |\n| D4 | docstring | plain serves `TRENDING_EXPECTED` from both `fetch_ordered_page` and `fetch_popular_videos` | :70, :71 | either read ignoring main's ranks | CARRIED |\n| D5 | docstring | prepared serves `OVERRIDE_EXPECTED` \"from both\" | :84, :85 | an override covering only one read | CARRIED |\n| D6 | docstring | \"the plain connection still serves `TRENDING_EXPECTED` afterwards\" | :86 | an override that persists across connections | CARRIED |\n| D7 | docstring | \"`main.trending_ranks` holds exactly the rows written to it\" | :87 | added, removed or rewritten rows in main | CARRIED |\n| D8 | docstring | main DB \"whose own `trending_ranks` is empty\" | :95 | ranks present in main, which would let a plain ATTACH fill the page | CARRIED |\n| D9 | docstring | ranks \"written to a private file after `prepare_trending_override`\" (file gets the schema and index) | :98 / :105 | a prepare that creates no table (the insert at :98 fails) or no index (:105 fails) | CARRIED |\n| D10 | docstring | \"the prepared connection reads a full Trending page from the file\" | :104 (`_plan`, `tests/active/test_random_videos.py:217`) | a plain ATTACH serving 0 rows from main's empty table | CARRIED |\n| D11 | docstring | \"its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order`\" | :105 | a plan that skips the index | CARRIED |\n| D12 | docstring | \"and has no `TEMP B-TREE`\" | :106 | a plan that sorts | CARRIED |\n| D13 | docstring | \"the same capture for Popular shows the temp B-tree (control)\" | :102 | a plan capture that cannot show a sort, which would make :106 pass vacuously | CARRIED |\n| D14 | docstring | `_private_file`: an existing empty file given the trending schema | :98 / :105 | a prepare that leaves the file without schema | CARRIED |\n| D15 | docstring | `_private_file`: `prepare_trending_override` \"never creates one\" | none | nothing. :30 always `touch()`es the file first, so a prepare that creates a missing file passes | UNCARRIED |\n| N1 | name | test 1: \"trending and the popular pool read main ranks without the override\" | :70, :71, :86 | either read on the plain conn not serving main's order | CARRIED |\n| N2 | name | test 1: \"and the file's ranks with it\" | :84, :85 | a plain ATTACH or an override covering one read only | CARRIED |\n| N3 | name | test 2: \"a trending page on the override file\" | :104 with control :95 | a page not served from the file (main is empty) | CARRIED |\n| N4 | name | test 2: \"walks its ranks index\" | :105 | a plan without `idx_trending_ranks_order` | CARRIED |\n| N5 | name | test 2: \"without sorting\" | :106 | a plan with `TEMP B-TREE` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:29\n   `\"\"\"An existing empty file at `path`, given the trending schema by `prepare_trending_override`, which never creates one.\"\"\"`\n   D15 is UNCARRIED. The helper's docstring says `prepare_trending_override` never creates a file, and :30 `path.touch()` always creates the file before the call. No path in this file calls prepare on a missing file and checks that nothing appeared. Either assert it, or cut the sentence back to what the helper does. This is not a `must_prove` clause, so it does not block.\n2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31, :38\n   Only the success path of the two helpers runs. Neither `prepare_trending_override` nor `attach_trending_override` is ever run on a missing or non-SQLite path, so the expected failure mode is untested here.\n3. bounds (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:82\n   Every prepared connection has a populated override file. Nothing covers a prepared connection whose file has the schema and no rows. That case would show whether the Trending page and pool come back empty or fall back to main's ranks, and it is the edge between \"the file's ranks\" and \"main's ranks\" in C1.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/data/trending.py (EDITED). As read, it defines only `ensure_trending_schema`. It has no `prepare_trending_override` or `attach_trending_override`, and no definition exists anywhere outside docs/project/plans. So I could not judge from the code which inputs the helpers accept or how they fail. Recommendations 2 and 3 rest on the test file and on `random_videos.py:37` and `:237` only.\n2. tests/active/test_random_videos.py was read only in part: lines 86\u2013245, which cover `RANKS`, `TRENDING_EXPECTED`, `_schema`, `_ranks_db`, `_trending_labels` and `_plan`. Its module header was not read, so the imports and `sys.path` setup the harness exec at :18 depends on were not checked.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "prepared conn: `fetch_ordered_page` \"trending\" serves the attached file's ranks",
            "assertion": ":84",
            "excludes": "a plain ATTACH with no shadowing, which leaves `main.trending_ranks` first and serves the reversed list `TRENDING_EXPECTED`",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "prepared conn: `fetch_popular_videos` serves the attached file's ranks",
            "assertion": ":85",
            "excludes": "an override that reaches the page read and misses the pool",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "unprepared conn on the same main: Trending page serves main's ranks",
            "assertion": ":70, :86",
            "excludes": "an override that writes main or switches the source for every connection; :86 reads after the prepared connection has read",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "unprepared conn on the same main: popular pool serves main's ranks",
            "assertion": ":71",
            "excludes": "a pool that does not read main's `trending_ranks` order (the pool is the head of the Trending order, `random_videos.py:237`)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "main's ranks are left unchanged",
            "assertion": ":87",
            "excludes": "a committed copy, delete or rewrite of `main.trending_ranks`. The expected rows are rebuilt from `RANKS` at :68, not read back from the code",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "prepared conn: Trending plan uses `idx_trending_ranks_order`",
            "assertion": ":105 (with `_plan`'s full-page check at :104 and the empty-main control at :95)",
            "excludes": "a temp copy or view that loses the index. Main's empty table also has an index by this name, but a full 50-row page can only come from the file",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "prepared conn: Trending plan has no `TEMP B-TREE`",
            "assertion": ":106",
            "excludes": "an unindexed shadow that plans SCAN plus USE TEMP B-TREE FOR ORDER BY",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"a connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file\"",
            "assertion": ":84, :85",
            "excludes": "a plain ATTACH that reads main",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"a plain connection on the same main reads main's\"",
            "assertion": ":70, :71, :86",
            "excludes": "an override that leaks to other connections",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "private file holds \"the same keys ranked in `OVERRIDE_EXPECTED`\", a different order",
            "assertion": ":67",
            "excludes": "a fixture where the two orders match, which would make :84 and :85 pass on main's ranks",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "plain serves `TRENDING_EXPECTED` from both `fetch_ordered_page` and `fetch_popular_videos`",
            "assertion": ":70, :71",
            "excludes": "either read ignoring main's ranks",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "prepared serves `OVERRIDE_EXPECTED` \"from both\"",
            "assertion": ":84, :85",
            "excludes": "an override covering only one read",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"the plain connection still serves `TRENDING_EXPECTED` afterwards\"",
            "assertion": ":86",
            "excludes": "an override that persists across connections",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"`main.trending_ranks` holds exactly the rows written to it\"",
            "assertion": ":87",
            "excludes": "added, removed or rewritten rows in main",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "main DB \"whose own `trending_ranks` is empty\"",
            "assertion": ":95",
            "excludes": "ranks present in main, which would let a plain ATTACH fill the page",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "ranks \"written to a private file after `prepare_trending_override`\" (file gets the schema and index)",
            "assertion": ":98 / :105",
            "excludes": "a prepare that creates no table (the insert at :98 fails) or no index (:105 fails)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"the prepared connection reads a full Trending page from the file\"",
            "assertion": ":104 (`_plan`, `tests/active/test_random_videos.py:217`)",
            "excludes": "a plain ATTACH serving 0 rows from main's empty table",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order`\"",
            "assertion": ":105",
            "excludes": "a plan that skips the index",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"and has no `TEMP B-TREE`\"",
            "assertion": ":106",
            "excludes": "a plan that sorts",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"the same capture for Popular shows the temp B-tree (control)\"",
            "assertion": ":102",
            "excludes": "a plan capture that cannot show a sort, which would make :106 pass vacuously",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "`_private_file`: an existing empty file given the trending schema",
            "assertion": ":98 / :105",
            "excludes": "a prepare that leaves the file without schema",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "`_private_file`: `prepare_trending_override` \"never creates one\"",
            "assertion": "none",
            "excludes": "nothing. :30 always `touch()`es the file first, so a prepare that creates a missing file passes",
            "status": "UNCARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test 1: \"trending and the popular pool read main ranks without the override\"",
            "assertion": ":70, :71, :86",
            "excludes": "either read on the plain conn not serving main's order",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "test 1: \"and the file's ranks with it\"",
            "assertion": ":84, :85",
            "excludes": "a plain ATTACH or an override covering one read only",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test 2: \"a trending page on the override file\"",
            "assertion": ":104 with control :95",
            "excludes": "a page not served from the file (main is empty)",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test 2: \"walks its ranks index\"",
            "assertion": ":105",
            "excludes": "a plan without `idx_trending_ranks_order`",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "test 2: \"without sorting\"",
            "assertion": ":106",
            "excludes": "a plan with `TEMP B-TREE`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nIn both tests the first call to `trending.prepare_trending_override` raises `AttributeError` at tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31 (`trending.prepare_trending_override(str(path))`). `engine/server/data/trending.py` defines only `ensure_trending_schema`. The first test gets there after its line 70 and 71 controls pass. The second gets there after its line 95 control passes. So no C1 or C2 assertion (lines 84\u201387, 105\u2013106) is reached on the code as it stands.\n\nNOT ASSESSED\n1. `fixtures_path` was given as \"none found\". The test uses only the built-in `tmp_path`. Its harness is `tests/active/test_random_videos.py`, loaded by path, and I read it at lines 86\u2013245 (`RANKS`, `TRENDING_EXPECTED`, `_schema`, `_ranks_db`, `_trending_labels`, `_plan`). I did not look for a `conftest.py` covering `tests/tmp/`, because no fixture is used that the test or that harness doesn't define.\n2. `engine/server/data/random_videos.py` is not in `code_under_test`. I read only its `ORDERED_FEED_SOURCE` (lines 35\u201342) for the stub question. I did not check how `fetch_popular_videos` reaches `trending_ranks`.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | prepared conn: `fetch_ordered_page` \"trending\" serves the attached file's ranks | :84 | a plain ATTACH with no shadowing. That leaves `main.trending_ranks` in front, so the page comes back as the reverse order `TRENDING_EXPECTED` | CARRIED |\n| C1b | must_prove | prepared conn: `fetch_popular_videos` serves the attached file's ranks | :85 | an override that reaches the page read but not the pool | CARRIED |\n| C1c | must_prove | unprepared conn on the same main: Trending page serves main's ranks | :70, :86 | an override that writes main or changes the source for every connection. :86 reads after the prepared connection has read | CARRIED |\n| C1d | must_prove | unprepared conn on the same main: popular pool serves main's ranks | :71 | a pool that does not read main's `trending_ranks` order | CARRIED |\n| C1e | must_prove | main's ranks are left unchanged | :87 | a committed copy, delete or rewrite of `main.trending_ranks`. The expected rows are rebuilt from `RANKS` at :68 in the table's column order, not read back from the code | CARRIED |\n| C2a | must_prove | prepared conn: Trending plan uses `idx_trending_ranks_order` | :105 (with `_plan`'s full-page check, `tests/active/test_random_videos.py:217`, at :104 and the empty-main control at :95) | a temp copy or view that loses the index. Main's empty table also has an index by this name, but only the file can supply a full 50-row page at offset 100 | CARRIED |\n| C2b | must_prove | prepared conn: Trending plan has no `TEMP B-TREE` | :106 | an unindexed shadow that plans a SCAN plus USE TEMP B-TREE FOR ORDER BY | CARRIED |\n| D1 | docstring | \"a connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file\" | :84, :85 | a plain ATTACH that reads main | CARRIED |\n| D2 | docstring | \"a plain connection on the same main reads main's\" | :70, :71, :86 | an override that leaks to other connections | CARRIED |\n| D3 | docstring | private file holds \"the same keys ranked in `OVERRIDE_EXPECTED`\", a different order | :67 | a fixture where the two orders match, which would let :84 and :85 pass on main's ranks | CARRIED |\n| D4 | docstring | plain serves `TRENDING_EXPECTED` from both `fetch_ordered_page` and `fetch_popular_videos` | :70, :71 | either read ignoring main's ranks | CARRIED |\n| D5 | docstring | prepared serves `OVERRIDE_EXPECTED` \"from both\" | :84, :85 | an override covering only one read | CARRIED |\n| D6 | docstring | \"the plain connection still serves `TRENDING_EXPECTED` afterwards\" | :86 | an override that persists across connections | CARRIED |\n| D7 | docstring | \"`main.trending_ranks` holds exactly the rows written to it\" | :87 | rows added to, removed from or rewritten in main | CARRIED |\n| D8 | docstring | main DB \"whose own `trending_ranks` is empty\" | :95 | ranks present in main, which would let a plain ATTACH fill the page | CARRIED |\n| D9 | docstring | ranks \"written to a private file after `prepare_trending_override`\" (file gets the schema and index) | :98 / :105 | a prepare that creates no table (the insert at :98 fails) or no index (:105 fails) | CARRIED |\n| D10 | docstring | \"the prepared connection reads a full Trending page from the file\" | :104 (`_plan`, `tests/active/test_random_videos.py:217`) | a plain ATTACH that serves 0 rows from main's empty table | CARRIED |\n| D11 | docstring | \"its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order`\" | :105 | a plan that skips the index | CARRIED |\n| D12 | docstring | \"and has no `TEMP B-TREE`\" | :106 | a plan that sorts | CARRIED |\n| D13 | docstring | \"the same capture for Popular shows the temp B-tree (control)\" | :102 | a plan capture that cannot show a sort, which would let :106 pass without testing anything | CARRIED |\n| D14 | docstring | `_private_file`: \"An empty file touched at `path`, then given the trending schema by `prepare_trending_override`\" | :98 / :105 | a prepare that leaves the file without the schema or the index | CARRIED |\n| D15 | docstring | withdrawn | n/a | n/a | CARRIED |\n| N1 | name | test 1: \"trending and the popular pool read main ranks without the override\" | :70, :71, :86 | either read on the plain conn not serving main's order | CARRIED |\n| N2 | name | test 1: \"and the file's ranks with it\" | :84, :85 | a plain ATTACH, or an override covering only one read | CARRIED |\n| N3 | name | test 2: \"a trending page on the override file\" | :104 with control :95 | a page not served from the file (main is empty) | CARRIED |\n| N4 | name | test 2: \"walks its ranks index\" | :105 | a plan without `idx_trending_ranks_order` | CARRIED |\n| N5 | name | test 2: \"without sorting\" | :106 | a plan with `TEMP B-TREE` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:29\n   D15 was resolved by narrowing the docstring, not by adding an assertion. The clause\n   \"`prepare_trending_override` ... never creates one\" is gone. The docstring now reads\n   \"An empty file touched at `path`, then given the trending schema by\n   `prepare_trending_override`.\" Nothing in the file checks whether prepare creates a\n   missing file. The sentence was cut back to match the test.\n2. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:86\n   After the prepared connection has read, only the plain connection's Trending page is\n   read again. Its popular pool is checked only at :71, before the override exists. An\n   override that leaks into the pool path alone, on every connection, would not be caught\n   after the fact. C1d and D6 are carried as written, so this is outside the ledger.\n3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31, :38\n   The round-one recommendation still stands: only the success path of each helper runs.\n   No test calls `prepare_trending_override` or `attach_trending_override` on a missing,\n   non-SQLite or empty override file. The author's record says this was left out because\n   no clause specifies the failure behaviour.\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/data/trending.py (EDITED). As read, it still\n   defines only `ensure_trending_schema` and has no `prepare_trending_override` or\n   `attach_trending_override`. So the helpers' accepted inputs and failure behaviour could\n   not be judged from the code. This is consistent with the test being red before the\n   phase is implemented.\n2. `fixtures_path` was \"none found\". The test uses no pytest fixture apart from\n   `tmp_path`. Its harness (`_schema`, `_ranks_db`, `_plan`, `_trending_labels`, `RANKS`,\n   `TRENDING_EXPECTED`) was read at tests/active/test_random_videos.py:86\u2013240.\n   `random_videos.fetch_ordered_page` and `fetch_popular_videos` are not in\n   `code_under_test` and were not read.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nIn both tests the first call to `trending.prepare_trending_override` raises `AttributeError` at tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31 (`trending.prepare_trending_override(str(path))`). `engine/server/data/trending.py` defines only `ensure_trending_schema`. The first test gets there after its line 70 and 71 controls pass. The second gets there after its line 95 control passes. So no C1 or C2 assertion (lines 84\u201387, 105\u2013106) is reached on the code as it stands.\n\nNOT ASSESSED\n1. `fixtures_path` was given as \"none found\". The test uses only the built-in `tmp_path`. Its harness is `tests/active/test_random_videos.py`, loaded by path, and I read it at lines 86\u2013245 (`RANKS`, `TRENDING_EXPECTED`, `_schema`, `_ranks_db`, `_trending_labels`, `_plan`). I did not look for a `conftest.py` covering `tests/tmp/`, because no fixture is used that the test or that harness doesn't define.\n2. `engine/server/data/random_videos.py` is not in `code_under_test`. I read only its `ORDERED_FEED_SOURCE` (lines 35\u201342) for the stub question. I did not check how `fetch_popular_videos` reaches `trending_ranks`.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | prepared conn: `fetch_ordered_page` \"trending\" serves the attached file's ranks | :84 | a plain ATTACH with no shadowing. That leaves `main.trending_ranks` in front, so the page comes back as the reverse order `TRENDING_EXPECTED` | CARRIED |\n| C1b | must_prove | prepared conn: `fetch_popular_videos` serves the attached file's ranks | :85 | an override that reaches the page read but not the pool | CARRIED |\n| C1c | must_prove | unprepared conn on the same main: Trending page serves main's ranks | :70, :86 | an override that writes main or changes the source for every connection. :86 reads after the prepared connection has read | CARRIED |\n| C1d | must_prove | unprepared conn on the same main: popular pool serves main's ranks | :71 | a pool that does not read main's `trending_ranks` order | CARRIED |\n| C1e | must_prove | main's ranks are left unchanged | :87 | a committed copy, delete or rewrite of `main.trending_ranks`. The expected rows are rebuilt from `RANKS` at :68 in the table's column order, not read back from the code | CARRIED |\n| C2a | must_prove | prepared conn: Trending plan uses `idx_trending_ranks_order` | :105 (with `_plan`'s full-page check, `tests/active/test_random_videos.py:217`, at :104 and the empty-main control at :95) | a temp copy or view that loses the index. Main's empty table also has an index by this name, but only the file can supply a full 50-row page at offset 100 | CARRIED |\n| C2b | must_prove | prepared conn: Trending plan has no `TEMP B-TREE` | :106 | an unindexed shadow that plans a SCAN plus USE TEMP B-TREE FOR ORDER BY | CARRIED |\n| D1 | docstring | \"a connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file\" | :84, :85 | a plain ATTACH that reads main | CARRIED |\n| D2 | docstring | \"a plain connection on the same main reads main's\" | :70, :71, :86 | an override that leaks to other connections | CARRIED |\n| D3 | docstring | private file holds \"the same keys ranked in `OVERRIDE_EXPECTED`\", a different order | :67 | a fixture where the two orders match, which would let :84 and :85 pass on main's ranks | CARRIED |\n| D4 | docstring | plain serves `TRENDING_EXPECTED` from both `fetch_ordered_page` and `fetch_popular_videos` | :70, :71 | either read ignoring main's ranks | CARRIED |\n| D5 | docstring | prepared serves `OVERRIDE_EXPECTED` \"from both\" | :84, :85 | an override covering only one read | CARRIED |\n| D6 | docstring | \"the plain connection still serves `TRENDING_EXPECTED` afterwards\" | :86 | an override that persists across connections | CARRIED |\n| D7 | docstring | \"`main.trending_ranks` holds exactly the rows written to it\" | :87 | rows added to, removed from or rewritten in main | CARRIED |\n| D8 | docstring | main DB \"whose own `trending_ranks` is empty\" | :95 | ranks present in main, which would let a plain ATTACH fill the page | CARRIED |\n| D9 | docstring | ranks \"written to a private file after `prepare_trending_override`\" (file gets the schema and index) | :98 / :105 | a prepare that creates no table (the insert at :98 fails) or no index (:105 fails) | CARRIED |\n| D10 | docstring | \"the prepared connection reads a full Trending page from the file\" | :104 (`_plan`, `tests/active/test_random_videos.py:217`) | a plain ATTACH that serves 0 rows from main's empty table | CARRIED |\n| D11 | docstring | \"its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order`\" | :105 | a plan that skips the index | CARRIED |\n| D12 | docstring | \"and has no `TEMP B-TREE`\" | :106 | a plan that sorts | CARRIED |\n| D13 | docstring | \"the same capture for Popular shows the temp B-tree (control)\" | :102 | a plan capture that cannot show a sort, which would let :106 pass without testing anything | CARRIED |\n| D14 | docstring | `_private_file`: \"An empty file touched at `path`, then given the trending schema by `prepare_trending_override`\" | :98 / :105 | a prepare that leaves the file without the schema or the index | CARRIED |\n| D15 | docstring | withdrawn | n/a | n/a | CARRIED |\n| N1 | name | test 1: \"trending and the popular pool read main ranks without the override\" | :70, :71, :86 | either read on the plain conn not serving main's order | CARRIED |\n| N2 | name | test 1: \"and the file's ranks with it\" | :84, :85 | a plain ATTACH, or an override covering only one read | CARRIED |\n| N3 | name | test 2: \"a trending page on the override file\" | :104 with control :95 | a page not served from the file (main is empty) | CARRIED |\n| N4 | name | test 2: \"walks its ranks index\" | :105 | a plan without `idx_trending_ranks_order` | CARRIED |\n| N5 | name | test 2: \"without sorting\" | :106 | a plan with `TEMP B-TREE` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:29\n   D15 was resolved by narrowing the docstring, not by adding an assertion. The clause\n   \"`prepare_trending_override` ... never creates one\" is gone. The docstring now reads\n   \"An empty file touched at `path`, then given the trending schema by\n   `prepare_trending_override`.\" Nothing in the file checks whether prepare creates a\n   missing file. The sentence was cut back to match the test.\n2. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:86\n   After the prepared connection has read, only the plain connection's Trending page is\n   read again. Its popular pool is checked only at :71, before the override exists. An\n   override that leaks into the pool path alone, on every connection, would not be caught\n   after the fact. C1d and D6 are carried as written, so this is outside the ledger.\n3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31, :38\n   The round-one recommendation still stands: only the success path of each helper runs.\n   No test calls `prepare_trending_override` or `attach_trending_override` on a missing,\n   non-SQLite or empty override file. The author's record says this was left out because\n   no clause specifies the failure behaviour.\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/data/trending.py (EDITED). As read, it still\n   defines only `ensure_trending_schema` and has no `prepare_trending_override` or\n   `attach_trending_override`. So the helpers' accepted inputs and failure behaviour could\n   not be judged from the code. This is consistent with the test being red before the\n   phase is implemented.\n2. `fixtures_path` was \"none found\". The test uses no pytest fixture apart from\n   `tmp_path`. Its harness (`_schema`, `_ranks_db`, `_plan`, `_trending_labels`, `RANKS`,\n   `TRENDING_EXPECTED`) was read at tests/active/test_random_videos.py:86\u2013240.\n   `random_videos.fetch_ordered_page` and `fetch_popular_videos` are not in\n   `code_under_test` and were not read.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "prepared conn: `fetch_ordered_page` \"trending\" serves the attached file's ranks",
            "assertion": ":84",
            "excludes": "a plain ATTACH with no shadowing. That leaves `main.trending_ranks` in front, so the page comes back as the reverse order `TRENDING_EXPECTED`",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "prepared conn: `fetch_popular_videos` serves the attached file's ranks",
            "assertion": ":85",
            "excludes": "an override that reaches the page read but not the pool",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "unprepared conn on the same main: Trending page serves main's ranks",
            "assertion": ":70, :86",
            "excludes": "an override that writes main or changes the source for every connection. :86 reads after the prepared connection has read",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "unprepared conn on the same main: popular pool serves main's ranks",
            "assertion": ":71",
            "excludes": "a pool that does not read main's `trending_ranks` order",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "main's ranks are left unchanged",
            "assertion": ":87",
            "excludes": "a committed copy, delete or rewrite of `main.trending_ranks`. The expected rows are rebuilt from `RANKS` at :68 in the table's column order, not read back from the code",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "prepared conn: Trending plan uses `idx_trending_ranks_order`",
            "assertion": ":105 (with `_plan`'s full-page check, `tests/active/test_random_videos.py:217`, at :104 and the empty-main control at :95)",
            "excludes": "a temp copy or view that loses the index. Main's empty table also has an index by this name, but only the file can supply a full 50-row page at offset 100",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "prepared conn: Trending plan has no `TEMP B-TREE`",
            "assertion": ":106",
            "excludes": "an unindexed shadow that plans a SCAN plus USE TEMP B-TREE FOR ORDER BY",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"a connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file\"",
            "assertion": ":84, :85",
            "excludes": "a plain ATTACH that reads main",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"a plain connection on the same main reads main's\"",
            "assertion": ":70, :71, :86",
            "excludes": "an override that leaks to other connections",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "private file holds \"the same keys ranked in `OVERRIDE_EXPECTED`\", a different order",
            "assertion": ":67",
            "excludes": "a fixture where the two orders match, which would let :84 and :85 pass on main's ranks",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "plain serves `TRENDING_EXPECTED` from both `fetch_ordered_page` and `fetch_popular_videos`",
            "assertion": ":70, :71",
            "excludes": "either read ignoring main's ranks",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "prepared serves `OVERRIDE_EXPECTED` \"from both\"",
            "assertion": ":84, :85",
            "excludes": "an override covering only one read",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"the plain connection still serves `TRENDING_EXPECTED` afterwards\"",
            "assertion": ":86",
            "excludes": "an override that persists across connections",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"`main.trending_ranks` holds exactly the rows written to it\"",
            "assertion": ":87",
            "excludes": "rows added to, removed from or rewritten in main",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "main DB \"whose own `trending_ranks` is empty\"",
            "assertion": ":95",
            "excludes": "ranks present in main, which would let a plain ATTACH fill the page",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "ranks \"written to a private file after `prepare_trending_override`\" (file gets the schema and index)",
            "assertion": ":98 / :105",
            "excludes": "a prepare that creates no table (the insert at :98 fails) or no index (:105 fails)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"the prepared connection reads a full Trending page from the file\"",
            "assertion": ":104 (`_plan`, `tests/active/test_random_videos.py:217`)",
            "excludes": "a plain ATTACH that serves 0 rows from main's empty table",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order`\"",
            "assertion": ":105",
            "excludes": "a plan that skips the index",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"and has no `TEMP B-TREE`\"",
            "assertion": ":106",
            "excludes": "a plan that sorts",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"the same capture for Popular shows the temp B-tree (control)\"",
            "assertion": ":102",
            "excludes": "a plan capture that cannot show a sort, which would let :106 pass without testing anything",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "`_private_file`: \"An empty file touched at `path`, then given the trending schema by `prepare_trending_override`\"",
            "assertion": ":98 / :105",
            "excludes": "a prepare that leaves the file without the schema or the index",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test 1: \"trending and the popular pool read main ranks without the override\"",
            "assertion": ":70, :71, :86",
            "excludes": "either read on the plain conn not serving main's order",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "test 1: \"and the file's ranks with it\"",
            "assertion": ":84, :85",
            "excludes": "a plain ATTACH, or an override covering only one read",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test 2: \"a trending page on the override file\"",
            "assertion": ":104 with control :95",
            "excludes": "a page not served from the file (main is empty)",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test 2: \"walks its ranks index\"",
            "assertion": ":105",
            "excludes": "a plan without `idx_trending_ranks_order`",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "test 2: \"without sorting\"",
            "assertion": ":106",
            "excludes": "a plan with `TEMP B-TREE`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_44_trending_seed_write_lock_during_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. Stub question (rules/shape.md, answered under `single-value-pin <alternatives>`) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:42-43, 51-52\n   assert run.returncode != 0, run.stderr[-2000:]  # C1\n   assert str(missing) in run.stderr, run.stderr[-2000:]  # C1\n   The test only tries `--trending-db` with inputs that must be rejected: a missing path and a junk file. It never passes a path that must get through the check. So an implementation that adds the flag and always rejects its value passes every assertion. For example, `parser.error(f\"--trending-db {args.trending_db}: not a SQLite file\")` with no condition exits non-zero, puts the path in stderr without \"unrecognized arguments\", and creates or changes no file. The test reads one kind of outcome. The rule requires two inputs that must produce different results, and an assertion on the difference (\"Run the observable twice, at two inputs that must produce different readings\"). One way to add that: start once with a valid SQLite file, and check that the start does not fail with that path in stderr, or that it gets past the check (end it with `Popen` and terminate rather than `_run`'s 120 s timeout). The test would then fail if the check were hard-coded.\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 45 on `assert \"unrecognized arguments\" not in run.stderr`. `parse_args` in engine/server/api/server.py (lines 153-203) has no `--trending-db` argument yet, so argparse exits 2 with \"unrecognized arguments: --trending-db <tmp>/absent.db\" in stderr. That output also satisfies lines 42-43, so 45 is the first assertion to fail.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. I checked by Grep that tests/active/conftest.py defines `ENGINE_PY`, `ROOT` and `_free_port` (the harness imports them), but I did not read `_free_port`'s body.\n2. tests/config.json is listed in `code_under_test` and was not read. Nothing in the test refers to it, so no shape check depends on it.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (17 clauses: 8 must_prove, 6 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | missing path \u2192 start exits non-zero | :42 | a start that accepts a missing path and serves (the `_run` timeout raises), or exits 0 | CARRIED |\n| C1b | must_prove | missing path \u2192 \"that path in stderr\" | :43, :45 | a failure that never names the path; :45 rules out the path appearing only because argparse quoted it while rejecting the flag | CARRIED |\n| C1c | must_prove | non-SQLite file \u2192 start exits non-zero | :51 | a start that opens or accepts a non-SQLite file without complaint | CARRIED |\n| C1d | must_prove | non-SQLite file \u2192 \"that path in stderr\" | :52, :53 | a generic \"file is not a database\" error with no path; argparse quoting the path while rejecting the flag | CARRIED |\n| C2a | must_prove | \"a missing path is not created\" | :46 | a check that runs after `sqlite3.connect` or schema setup has already created the file | CARRIED |\n| C2b | must_prove | \"a non-SQLite file's bytes are unchanged\" | :54 | overwriting, truncating or re-initialising the junk file before rejecting it (exact equality against all 4096 written bytes) | CARRIED |\n| C1-path | must_prove | the flag reaches `server.py --trending-db` (not rejected by argparse) | :45, :53 against controls :37\u2013:38 | treating argparse's exit 2 for an unknown flag as the required failure | CARRIED |\n| C1-entry | must_prove | \"Starting `server.py`\": the real entry point | :41, :50 via :30 | an in-process helper standing in for the CLI start; the real script runs as a subprocess | CARRIED |\n| D1 | docstring | \"`server.py --help` exits 0\" (control) | :35 | an entry point that does not run in this interpreter, which would make every non-zero exit below meaningless | CARRIED |\n| D2 | docstring | \"unknown flag exits 2 with 'unrecognized arguments' in stderr\" | :37, :38 | the absence checks at :45/:53 passing because the wording never reaches the captured stderr | CARRIED |\n| D3 | docstring | \"absent.db and a 4 KB junk.db each \u2026 exit non-zero, with that path in stderr and not as argparse's 'unrecognized arguments'\" | :42\u2013:45, :51\u2013:53 | as C1a\u2013C1d | CARRIED |\n| D4 | docstring | \"absent.db still does not exist\" | :46 | as C2a | CARRIED |\n| D5 | docstring | \"junk.db holds exactly the bytes written to it\" | :54 | as C2b | CARRIED |\n| D6 | docstring | \"A start that wrongly gets past the check \u2026 raises instead of hanging\" | :41, :50 (`_run` timeout=120, test_server_config.py:52) | a start that serves forever: `TimeoutExpired` from `_run` fails the test | CARRIED |\n| N1 | name | \"a trending db that is missing \u2026 stops the start\" | :42 | as C1a | CARRIED |\n| N2 | name | \"\u2026 or not sqlite stops the start\" | :51 | as C1c | CARRIED |\n| N3 | name | \"naming it\" | :43, :52 | as C1b, C1d | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:48\n   The test only uses two rejected inputs: a missing file and a 4 KB file of non-SQLite bytes. It never tests the edges of \"not an existing SQLite file\": a zero-byte file (SQLite opens it as a valid empty database), a directory at the path, a file that starts with the SQLite header but is truncated, or a path whose parent directory is missing. Each of these could be accepted or rejected by mistake, and this test would not show it.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:33\n   Only the failure path runs. Nothing here shows that `--trending-db` pointing at a valid SQLite file gets past the check. A check that rejects every path would pass this test. That success case is not in `must_prove`, so this does not block, but this file alone does not show the behaviour has a normal path.\n3. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:1\n   The function name reads as a correct sentence. The module name, `test_44_trending_seed_write_lock_during_phase2`, describes a different behaviour (a write lock during the seed). The runner prints `file::function` on failure, so the first half of what a reader sees describes something this test does not check.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses only the built-in `tmp_path`, plus `ENGINE_PY`, `ROOT` and `_free_port`. It gets those through `tests/active/test_server_config.py:39`, which imports them from `tests/active/conftest.py`. I did not read that conftest, so I have not checked independence for `_free_port`'s port selection.\n2. `engine/server/api/server.py` has no `--trending-db` argument and no path check in `parse_args` (:153\u2013203) or `main` (:285\u2013). I judged bounds from what `must_prove` and the docstring say should be accepted and rejected, not from the code's own validation, because that validation is not there.\n3. `tests/config.json` (in `code_under_test`) was only searched for references to this test and to trending. It maps test files to the source files they cover and has no bearing on what this test asserts.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. Stub question (rules/shape.md, answered under `single-value-pin <alternatives>`) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:42-43, 51-52\n   assert run.returncode != 0, run.stderr[-2000:]  # C1\n   assert str(missing) in run.stderr, run.stderr[-2000:]  # C1\n   The test only tries `--trending-db` with inputs that must be rejected: a missing path and a junk file. It never passes a path that must get through the check. So an implementation that adds the flag and always rejects its value passes every assertion. For example, `parser.error(f\"--trending-db {args.trending_db}: not a SQLite file\")` with no condition exits non-zero, puts the path in stderr without \"unrecognized arguments\", and creates or changes no file. The test reads one kind of outcome. The rule requires two inputs that must produce different results, and an assertion on the difference (\"Run the observable twice, at two inputs that must produce different readings\"). One way to add that: start once with a valid SQLite file, and check that the start does not fail with that path in stderr, or that it gets past the check (end it with `Popen` and terminate rather than `_run`'s 120 s timeout). The test would then fail if the check were hard-coded.\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 45 on `assert \"unrecognized arguments\" not in run.stderr`. `parse_args` in engine/server/api/server.py (lines 153-203) has no `--trending-db` argument yet, so argparse exits 2 with \"unrecognized arguments: --trending-db <tmp>/absent.db\" in stderr. That output also satisfies lines 42-43, so 45 is the first assertion to fail.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. I checked by Grep that tests/active/conftest.py defines `ENGINE_PY`, `ROOT` and `_free_port` (the harness imports them), but I did not read `_free_port`'s body.\n2. tests/config.json is listed in `code_under_test` and was not read. Nothing in the test refers to it, so no shape check depends on it.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (17 clauses: 8 must_prove, 6 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | missing path \u2192 start exits non-zero | :42 | a start that accepts a missing path and serves (the `_run` timeout raises), or exits 0 | CARRIED |\n| C1b | must_prove | missing path \u2192 \"that path in stderr\" | :43, :45 | a failure that never names the path; :45 rules out the path appearing only because argparse quoted it while rejecting the flag | CARRIED |\n| C1c | must_prove | non-SQLite file \u2192 start exits non-zero | :51 | a start that opens or accepts a non-SQLite file without complaint | CARRIED |\n| C1d | must_prove | non-SQLite file \u2192 \"that path in stderr\" | :52, :53 | a generic \"file is not a database\" error with no path; argparse quoting the path while rejecting the flag | CARRIED |\n| C2a | must_prove | \"a missing path is not created\" | :46 | a check that runs after `sqlite3.connect` or schema setup has already created the file | CARRIED |\n| C2b | must_prove | \"a non-SQLite file's bytes are unchanged\" | :54 | overwriting, truncating or re-initialising the junk file before rejecting it (exact equality against all 4096 written bytes) | CARRIED |\n| C1-path | must_prove | the flag reaches `server.py --trending-db` (not rejected by argparse) | :45, :53 against controls :37\u2013:38 | treating argparse's exit 2 for an unknown flag as the required failure | CARRIED |\n| C1-entry | must_prove | \"Starting `server.py`\": the real entry point | :41, :50 via :30 | an in-process helper standing in for the CLI start; the real script runs as a subprocess | CARRIED |\n| D1 | docstring | \"`server.py --help` exits 0\" (control) | :35 | an entry point that does not run in this interpreter, which would make every non-zero exit below meaningless | CARRIED |\n| D2 | docstring | \"unknown flag exits 2 with 'unrecognized arguments' in stderr\" | :37, :38 | the absence checks at :45/:53 passing because the wording never reaches the captured stderr | CARRIED |\n| D3 | docstring | \"absent.db and a 4 KB junk.db each \u2026 exit non-zero, with that path in stderr and not as argparse's 'unrecognized arguments'\" | :42\u2013:45, :51\u2013:53 | as C1a\u2013C1d | CARRIED |\n| D4 | docstring | \"absent.db still does not exist\" | :46 | as C2a | CARRIED |\n| D5 | docstring | \"junk.db holds exactly the bytes written to it\" | :54 | as C2b | CARRIED |\n| D6 | docstring | \"A start that wrongly gets past the check \u2026 raises instead of hanging\" | :41, :50 (`_run` timeout=120, test_server_config.py:52) | a start that serves forever: `TimeoutExpired` from `_run` fails the test | CARRIED |\n| N1 | name | \"a trending db that is missing \u2026 stops the start\" | :42 | as C1a | CARRIED |\n| N2 | name | \"\u2026 or not sqlite stops the start\" | :51 | as C1c | CARRIED |\n| N3 | name | \"naming it\" | :43, :52 | as C1b, C1d | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:48\n   The test only uses two rejected inputs: a missing file and a 4 KB file of non-SQLite bytes. It never tests the edges of \"not an existing SQLite file\": a zero-byte file (SQLite opens it as a valid empty database), a directory at the path, a file that starts with the SQLite header but is truncated, or a path whose parent directory is missing. Each of these could be accepted or rejected by mistake, and this test would not show it.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:33\n   Only the failure path runs. Nothing here shows that `--trending-db` pointing at a valid SQLite file gets past the check. A check that rejects every path would pass this test. That success case is not in `must_prove`, so this does not block, but this file alone does not show the behaviour has a normal path.\n3. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:1\n   The function name reads as a correct sentence. The module name, `test_44_trending_seed_write_lock_during_phase2`, describes a different behaviour (a write lock during the seed). The runner prints `file::function` on failure, so the first half of what a reader sees describes something this test does not check.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses only the built-in `tmp_path`, plus `ENGINE_PY`, `ROOT` and `_free_port`. It gets those through `tests/active/test_server_config.py:39`, which imports them from `tests/active/conftest.py`. I did not read that conftest, so I have not checked independence for `_free_port`'s port selection.\n2. `engine/server/api/server.py` has no `--trending-db` argument and no path check in `parse_args` (:153\u2013203) or `main` (:285\u2013). I judged bounds from what `must_prove` and the docstring say should be accepted and rejected, not from the code's own validation, because that validation is not there.\n3. `tests/config.json` (in `code_under_test`) was only searched for references to this test and to trending. It maps test files to the source files they cover and has no bearing on what this test asserts.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "missing path \u2192 start exits non-zero",
            "assertion": ":42",
            "excludes": "a start that accepts a missing path and serves (the `_run` timeout raises), or exits 0",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "missing path \u2192 \"that path in stderr\"",
            "assertion": ":43, :45",
            "excludes": "a failure that never names the path; :45 rules out the path appearing only because argparse quoted it while rejecting the flag",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "non-SQLite file \u2192 start exits non-zero",
            "assertion": ":51",
            "excludes": "a start that opens or accepts a non-SQLite file without complaint",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "non-SQLite file \u2192 \"that path in stderr\"",
            "assertion": ":52, :53",
            "excludes": "a generic \"file is not a database\" error with no path; argparse quoting the path while rejecting the flag",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"a missing path is not created\"",
            "assertion": ":46",
            "excludes": "a check that runs after `sqlite3.connect` or schema setup has already created the file",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"a non-SQLite file's bytes are unchanged\"",
            "assertion": ":54",
            "excludes": "overwriting, truncating or re-initialising the junk file before rejecting it (exact equality against all 4096 written bytes)",
            "status": "CARRIED"
          },
          {
            "id": "C1-path",
            "source": "must_prove",
            "clause": "the flag reaches `server.py --trending-db` (not rejected by argparse)",
            "assertion": ":45, :53 against controls :37\u2013:38",
            "excludes": "treating argparse's exit 2 for an unknown flag as the required failure",
            "status": "CARRIED"
          },
          {
            "id": "C1-entry",
            "source": "must_prove",
            "clause": "\"Starting `server.py`\": the real entry point",
            "assertion": ":41, :50 via :30",
            "excludes": "an in-process helper standing in for the CLI start; the real script runs as a subprocess",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"`server.py --help` exits 0\" (control)",
            "assertion": ":35",
            "excludes": "an entry point that does not run in this interpreter, which would make every non-zero exit below meaningless",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"unknown flag exits 2 with 'unrecognized arguments' in stderr\"",
            "assertion": ":37, :38",
            "excludes": "the absence checks at :45/:53 passing because the wording never reaches the captured stderr",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"absent.db and a 4 KB junk.db each \u2026 exit non-zero, with that path in stderr and not as argparse's 'unrecognized arguments'\"",
            "assertion": ":42\u2013:45, :51\u2013:53",
            "excludes": "as C1a\u2013C1d",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"absent.db still does not exist\"",
            "assertion": ":46",
            "excludes": "as C2a",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"junk.db holds exactly the bytes written to it\"",
            "assertion": ":54",
            "excludes": "as C2b",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"A start that wrongly gets past the check \u2026 raises instead of hanging\"",
            "assertion": ":41, :50 (`_run` timeout=120, test_server_config.py:52)",
            "excludes": "a start that serves forever: `TimeoutExpired` from `_run` fails the test",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a trending db that is missing \u2026 stops the start\"",
            "assertion": ":42",
            "excludes": "as C1a",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"\u2026 or not sqlite stops the start\"",
            "assertion": ":51",
            "excludes": "as C1c",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"naming it\"",
            "assertion": ":43, :52",
            "excludes": "as C1b, C1d",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test fails at line 70 (`assert \"unrecognized arguments\" not in run.stderr`) on the missing-path start. `parse_args()` in engine/server/api/server.py (lines 153\u2013203) does not define `--trending-db`, so argparse exits 2 with the error \"unrecognized arguments: --trending-db <tmp>/absent.db\". That output already satisfies lines 67 and 68, so line 70 is the first assertion to fail.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines no pytest fixture beyond the built-in `tmp_path`. It loads its harness by path from tests/active/test_server_config.py, which I read. That module imports `ENGINE_PY`, `ENGINE_SERVER`, `ENGINE_START_LOCK`, `ROOT` and `_free_port` from tests/active/conftest.py. I did not read that conftest. The audit takes those names as resolving to what the harness uses them for.\n2. tests/config.json is listed in `code_under_test`, but the test never references it, so I did not read it. Nothing in the shape assessment depends on it.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (17 clauses: 8 must_prove, 6 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | missing path \u2192 start exits non-zero | :67 | a start that accepts a missing path and serves (the `_run` timeout raises), or exits 0 | CARRIED |\n| C1b | must_prove | missing path \u2192 \"that path in stderr\" | :68, :70 | a failure that never names the path; :70 rules out the path showing up only because argparse quoted it while rejecting the flag | CARRIED |\n| C1c | must_prove | non-SQLite file \u2192 start exits non-zero | :76 | a start that opens or accepts a non-SQLite file without complaint | CARRIED |\n| C1d | must_prove | non-SQLite file \u2192 \"that path in stderr\" | :77, :78 | a generic \"file is not a database\" error with no path; argparse quoting the path while rejecting the flag | CARRIED |\n| C2a | must_prove | \"a missing path is not created\" | :71 | a check that runs after `sqlite3.connect` or schema setup has already created the file | CARRIED |\n| C2b | must_prove | \"a non-SQLite file's bytes are unchanged\" | :79 | overwriting, truncating or re-initialising the junk file before rejecting it (exact equality against all 4096 bytes from :31) | CARRIED |\n| C1-path | must_prove | the flag reaches `server.py --trending-db` (not rejected by argparse) | :70, :78 against controls :62\u2013:63 | treating argparse's exit 2 for an unknown flag as the required failure | CARRIED |\n| C1-entry | must_prove | \"Starting `server.py`\": the real entry point | :67, :76 via :66, :75 and `_argv` :35 | an in-process helper standing in for the CLI start; `ENGINE_PY server.py` runs as a subprocess | CARRIED |\n| D1 | docstring | \"`server.py --help` exits 0\" (control) | :60 | an entry point that does not run in this interpreter, which would make every non-zero exit below meaningless | CARRIED |\n| D2 | docstring | \"unknown flag exits 2 with 'unrecognized arguments' in stderr\" | :62, :63 | the absence checks at :70/:78 passing because the wording never reaches captured stderr | CARRIED |\n| D3 | docstring | \"absent.db and a 4 KB junk.db each \u2026 exit non-zero, with that path in stderr and not as argparse's 'unrecognized arguments'\" | :67\u2013:70, :76\u2013:78 | as C1a\u2013C1d | CARRIED |\n| D4 | docstring | \"absent.db still does not exist\" | :71 | as C2a | CARRIED |\n| D5 | docstring | \"junk.db holds exactly the bytes written to it\" | :79 | as C2b | CARRIED |\n| D6 | docstring | \"A start that wrongly gets past the check \u2026 raises instead of hanging\" | :66, :75 (`_run` timeout=120, test_server_config.py:52) | a start that serves forever: `TimeoutExpired` from `_run` fails the test | CARRIED |\n| N1 | name | \"a trending db that is missing \u2026 stops the start\" | :67 | as C1a | CARRIED |\n| N2 | name | \"\u2026 or not sqlite stops the start\" | :76 | as C1c | CARRIED |\n| N3 | name | \"naming it\" | :68, :77 | as C1b, C1d | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:6, :88\n   The docstring has a new clause since the first audit that no ledger row names: \"An existing SQLite `valid.db` gets past the check: the start, under the Engine start lock, reaches its `service.lifecycle` start within 120 s and is then terminated.\"\n   - `assert _starts_serving(valid, log_path)` at :88 carries it.\n   - The lock is taken at :45\u2013:46, the poll is bounded by `VARIANT_START_SECONDS` (120) at :49\u2013:50, and the process is terminated at :54.\n   - This assertion rules out a check that rejects every path, so it is a real addition, not prose drift. It is the success-path counterpart that `normal-and-abnormal-paths` asks for.\n   - The line comment at :88 tags it `# C1`, but neither C1 nor C2 claims a valid path is accepted. Any later map should give it its own docstring row rather than read it as part of C1.\n2. No rule in testing.md covers this; recorded only \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:1\n   The file name (`trending_seed_write_lock_during_phase2`) describes something other than what the file tests. `name-as-sentence` applies to the test name at :58, which is accurate, so this is outside the criteria.\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/api/server.py, tests/active/test_server_config.py and tests/config.json.\n   - tests/config.json was not read: the test does not reference it.\n   - server.py was searched only for `trending`, so no `--trending-db` behaviour was read. That bears on the implementation, not on the claim audit.\n2. `fixtures_path` was not supplied. The test defines no pytest fixture other than the built-in `tmp_path`.\n   - The harness symbols it uses resolve in two places: `_run`, `_has_started`, `API_DIR` and `VARIANT_START_SECONDS` in tests/active/test_server_config.py, and `ENGINE_PY`, `ENGINE_START_LOCK` and `_free_port` in tests/active/conftest.py.\n   - All seven were confirmed to exist. Only `_run`, `_has_started` and the constants were read in full.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test fails at line 70 (`assert \"unrecognized arguments\" not in run.stderr`) on the missing-path start. `parse_args()` in engine/server/api/server.py (lines 153\u2013203) does not define `--trending-db`, so argparse exits 2 with the error \"unrecognized arguments: --trending-db <tmp>/absent.db\". That output already satisfies lines 67 and 68, so line 70 is the first assertion to fail.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines no pytest fixture beyond the built-in `tmp_path`. It loads its harness by path from tests/active/test_server_config.py, which I read. That module imports `ENGINE_PY`, `ENGINE_SERVER`, `ENGINE_START_LOCK`, `ROOT` and `_free_port` from tests/active/conftest.py. I did not read that conftest. The audit takes those names as resolving to what the harness uses them for.\n2. tests/config.json is listed in `code_under_test`, but the test never references it, so I did not read it. Nothing in the shape assessment depends on it.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (17 clauses: 8 must_prove, 6 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | missing path \u2192 start exits non-zero | :67 | a start that accepts a missing path and serves (the `_run` timeout raises), or exits 0 | CARRIED |\n| C1b | must_prove | missing path \u2192 \"that path in stderr\" | :68, :70 | a failure that never names the path; :70 rules out the path showing up only because argparse quoted it while rejecting the flag | CARRIED |\n| C1c | must_prove | non-SQLite file \u2192 start exits non-zero | :76 | a start that opens or accepts a non-SQLite file without complaint | CARRIED |\n| C1d | must_prove | non-SQLite file \u2192 \"that path in stderr\" | :77, :78 | a generic \"file is not a database\" error with no path; argparse quoting the path while rejecting the flag | CARRIED |\n| C2a | must_prove | \"a missing path is not created\" | :71 | a check that runs after `sqlite3.connect` or schema setup has already created the file | CARRIED |\n| C2b | must_prove | \"a non-SQLite file's bytes are unchanged\" | :79 | overwriting, truncating or re-initialising the junk file before rejecting it (exact equality against all 4096 bytes from :31) | CARRIED |\n| C1-path | must_prove | the flag reaches `server.py --trending-db` (not rejected by argparse) | :70, :78 against controls :62\u2013:63 | treating argparse's exit 2 for an unknown flag as the required failure | CARRIED |\n| C1-entry | must_prove | \"Starting `server.py`\": the real entry point | :67, :76 via :66, :75 and `_argv` :35 | an in-process helper standing in for the CLI start; `ENGINE_PY server.py` runs as a subprocess | CARRIED |\n| D1 | docstring | \"`server.py --help` exits 0\" (control) | :60 | an entry point that does not run in this interpreter, which would make every non-zero exit below meaningless | CARRIED |\n| D2 | docstring | \"unknown flag exits 2 with 'unrecognized arguments' in stderr\" | :62, :63 | the absence checks at :70/:78 passing because the wording never reaches captured stderr | CARRIED |\n| D3 | docstring | \"absent.db and a 4 KB junk.db each \u2026 exit non-zero, with that path in stderr and not as argparse's 'unrecognized arguments'\" | :67\u2013:70, :76\u2013:78 | as C1a\u2013C1d | CARRIED |\n| D4 | docstring | \"absent.db still does not exist\" | :71 | as C2a | CARRIED |\n| D5 | docstring | \"junk.db holds exactly the bytes written to it\" | :79 | as C2b | CARRIED |\n| D6 | docstring | \"A start that wrongly gets past the check \u2026 raises instead of hanging\" | :66, :75 (`_run` timeout=120, test_server_config.py:52) | a start that serves forever: `TimeoutExpired` from `_run` fails the test | CARRIED |\n| N1 | name | \"a trending db that is missing \u2026 stops the start\" | :67 | as C1a | CARRIED |\n| N2 | name | \"\u2026 or not sqlite stops the start\" | :76 | as C1c | CARRIED |\n| N3 | name | \"naming it\" | :68, :77 | as C1b, C1d | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:6, :88\n   The docstring has a new clause since the first audit that no ledger row names: \"An existing SQLite `valid.db` gets past the check: the start, under the Engine start lock, reaches its `service.lifecycle` start within 120 s and is then terminated.\"\n   - `assert _starts_serving(valid, log_path)` at :88 carries it.\n   - The lock is taken at :45\u2013:46, the poll is bounded by `VARIANT_START_SECONDS` (120) at :49\u2013:50, and the process is terminated at :54.\n   - This assertion rules out a check that rejects every path, so it is a real addition, not prose drift. It is the success-path counterpart that `normal-and-abnormal-paths` asks for.\n   - The line comment at :88 tags it `# C1`, but neither C1 nor C2 claims a valid path is accepted. Any later map should give it its own docstring row rather than read it as part of C1.\n2. No rule in testing.md covers this; recorded only \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:1\n   The file name (`trending_seed_write_lock_during_phase2`) describes something other than what the file tests. `name-as-sentence` applies to the test name at :58, which is accurate, so this is outside the criteria.\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/api/server.py, tests/active/test_server_config.py and tests/config.json.\n   - tests/config.json was not read: the test does not reference it.\n   - server.py was searched only for `trending`, so no `--trending-db` behaviour was read. That bears on the implementation, not on the claim audit.\n2. `fixtures_path` was not supplied. The test defines no pytest fixture other than the built-in `tmp_path`.\n   - The harness symbols it uses resolve in two places: `_run`, `_has_started`, `API_DIR` and `VARIANT_START_SECONDS` in tests/active/test_server_config.py, and `ENGINE_PY`, `ENGINE_START_LOCK` and `_free_port` in tests/active/conftest.py.\n   - All seven were confirmed to exist. Only `_run`, `_has_started` and the constants were read in full.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "missing path \u2192 start exits non-zero",
            "assertion": ":67",
            "excludes": "a start that accepts a missing path and serves (the `_run` timeout raises), or exits 0",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "missing path \u2192 \"that path in stderr\"",
            "assertion": ":68, :70",
            "excludes": "a failure that never names the path; :70 rules out the path showing up only because argparse quoted it while rejecting the flag",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "non-SQLite file \u2192 start exits non-zero",
            "assertion": ":76",
            "excludes": "a start that opens or accepts a non-SQLite file without complaint",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "non-SQLite file \u2192 \"that path in stderr\"",
            "assertion": ":77, :78",
            "excludes": "a generic \"file is not a database\" error with no path; argparse quoting the path while rejecting the flag",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"a missing path is not created\"",
            "assertion": ":71",
            "excludes": "a check that runs after `sqlite3.connect` or schema setup has already created the file",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"a non-SQLite file's bytes are unchanged\"",
            "assertion": ":79",
            "excludes": "overwriting, truncating or re-initialising the junk file before rejecting it (exact equality against all 4096 bytes from :31)",
            "status": "CARRIED"
          },
          {
            "id": "C1-path",
            "source": "must_prove",
            "clause": "the flag reaches `server.py --trending-db` (not rejected by argparse)",
            "assertion": ":70, :78 against controls :62\u2013:63",
            "excludes": "treating argparse's exit 2 for an unknown flag as the required failure",
            "status": "CARRIED"
          },
          {
            "id": "C1-entry",
            "source": "must_prove",
            "clause": "\"Starting `server.py`\": the real entry point",
            "assertion": ":67, :76 via :66, :75 and `_argv` :35",
            "excludes": "an in-process helper standing in for the CLI start; `ENGINE_PY server.py` runs as a subprocess",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"`server.py --help` exits 0\" (control)",
            "assertion": ":60",
            "excludes": "an entry point that does not run in this interpreter, which would make every non-zero exit below meaningless",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"unknown flag exits 2 with 'unrecognized arguments' in stderr\"",
            "assertion": ":62, :63",
            "excludes": "the absence checks at :70/:78 passing because the wording never reaches captured stderr",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"absent.db and a 4 KB junk.db each \u2026 exit non-zero, with that path in stderr and not as argparse's 'unrecognized arguments'\"",
            "assertion": ":67\u2013:70, :76\u2013:78",
            "excludes": "as C1a\u2013C1d",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"absent.db still does not exist\"",
            "assertion": ":71",
            "excludes": "as C2a",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"junk.db holds exactly the bytes written to it\"",
            "assertion": ":79",
            "excludes": "as C2b",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"A start that wrongly gets past the check \u2026 raises instead of hanging\"",
            "assertion": ":66, :75 (`_run` timeout=120, test_server_config.py:52)",
            "excludes": "a start that serves forever: `TimeoutExpired` from `_run` fails the test",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a trending db that is missing \u2026 stops the start\"",
            "assertion": ":67",
            "excludes": "as C1a",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"\u2026 or not sqlite stops the start\"",
            "assertion": ":76",
            "excludes": "as C1c",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"naming it\"",
            "assertion": ":68, :77",
            "excludes": "as C1b, C1d",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_44_trending_seed_write_lock_during_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. Considered under `single-value-pin` (rules/shape.md), second `<how_to_spot>` bullet; not met, so not Critical. tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:89\n   after = conftest.shared_trending_fingerprint()\n   The C2 check compares two readings. Both `before` (through the `shared_trending_before` fixture) and `after` come from the conftest fingerprint code, and that code is one of the edited files under test. The control at line 59 (`assert before[3] > 0`) rules out the likely wrong version: a fingerprint that reads the private seed file, where every `fetched_at` is 0. A fingerprint that caches or snapshots its first reading would still make line 90 equal no matter what happened to the table. Reading the `after` value at line 89 independently would remove that gap. One way is a fresh `mode=ro` connection and the test's own `COUNT`/`MIN`/`MAX`/`SUM(fetched_at > 0)` query, as `_shared` already does for ranks. No rule names this remaining gap.\n\nPREDICTED FAILURE\nThe test stops at line 55, `request.getfixturevalue(\"shared_trending_before\")`, with a fixture lookup error, because `tests/active/conftest.py` defines no `shared_trending_before`. This is a setup error, not an assertion failure. The comment at line 25 says the test is meant to stop here. If the fixture existed, the first assertion to fail would be line 63, `isinstance(pool_size, int) and pool_size > 0`, because the `_feed_constants` child (test_similar.py:719-729) outputs only `feed`, `ordered` and `threshold`, with no `popular_pool_size`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/conftest.py and tests/active/test_similar.py as EDITED, but neither file as read contains the phase's changes. Missing are the `shared_trending_before` fixture, `shared_trending_fingerprint`, a private seed file behind `dataset` or the Engine (`trending_seed` still runs `DELETE FROM trending_ranks` on the shared `WHITELIST_DB` at conftest.py:141), and `popular_pool_size` in `_feed_constants`. So I answered the stub question from the assertion form and its controls, not from the fixtures as they will be:\n   - C1 pages (line 80): an Engine reading the shared table should fail here.\n   - C1 popular rows (lines 85-87): the positive control at line 85 plus the 25%-outside control at line 73 should catch the same case.\n   - Previous behaviour (seed written into the shared table): `dataset` and the shared read would then match, so the control at line 70 should catch it.\n   - C2 (line 90): covered as long as the fingerprint reads the live shared table, which I could not verify.\n2. I did not check whether `tmp_path`-free reads of `dataset` actually point at the private ranks. The test relies on that, and the fixture defining it has not been written yet.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (20 clauses: 6 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | Trending pages follow the private seed's ranks | :80 | An Engine serving any order other than `_reference(dataset, \"trending\")[:36]`, including one that ignores `exclude` and repeats page 1 | CARRIED |\n| C1b | must_prove | Trending pages do not follow the shared table's ranks | :80, armed by :70 | An Engine started without `--trending-db`, or a flag that never shadows the table. :70 makes the shared head differ from the private head, so serving the shared head fails :80 | CARRIED |\n| C1c | must_prove | popular-layer rows follow the private seed's ranks | :87 | A popular row drawn from outside `fetch_popular_videos(dataset, POOL)` under the threshold and the NSFW filter | CARRIED |\n| C1d | must_prove | popular-layer rows do not follow the shared table's ranks | :87, armed by :73 and :85 | A popular layer reading the shared pool. :73 puts at least a quarter of that pool outside the private one, and :85 rules out a vacuous empty set | CARRIED |\n| C2a | must_prove | shared fingerprint identical before the seed and after the Engine served | :90 (read at :89 after :76-83 served) | A seed written into the shared table (`fetched_at = 0` drops the fourth field, which :59 requires to be > 0 beforehand), or any Engine-side write to it | CARRIED |\n| C2b | must_prove | fingerprint = row count, `fetched_at` min and max, rows with `fetched_at > 0` | :90 (tuple equality), :59 indexes `[3]` | A change in any member the helper returns. Whether the helper returns all four could not be read (see NOT ASSESSED) | CARRIED |\n| D1 | docstring | \"serves Trending \u2026 from the session's private ranks\" | :80 | An Engine serving the shared head | CARRIED |\n| D2 | docstring | \"and its popular layer from the session's private ranks\" | :87 | A popular row outside the private pool | CARRIED |\n| D3 | docstring | \"the shared whitelist.db `trending_ranks` is left as it was\" | :90 | Any write that moves the fingerprint | CARRIED |\n| D4 | docstring | control: `shared_trending_before` shows a real fill | :59 | A shared table with no `fetched_at > 0` rows, where a write into it could leave the fingerprint unmoved | CARRIED |\n| D5 | docstring | control: `_feed_constants` reads the threshold and `DEFAULT_POPULAR_POOL_SIZE` | :61, :63, :64 | A child that failed to import, or a missing or non-positive `popular_pool_size` key. It does not exclude a hard-coded value under that key | CARRIED |\n| D6 | docstring | control: private Trending order runs past three pages | :67 | An empty or short private seed, or a `dataset` without the private view | CARRIED |\n| D7 | docstring | control: on a fresh plain read-only connection, the shared first three pages differ | :70 | A `dataset` carrying no private view, or a seed written into the shared table | CARRIED |\n| D8 | docstring | control: at least a quarter of the shared pool lies outside the private one | :73 | Shared and private pools so close that :87 cannot tell them apart | CARRIED |\n| D9 | docstring | three `mode=trending` pages, each excluding prior rows, are exactly the first three reference pages | :80 | Wrong order, wrong rows, or `exclude` ignored (a repeated page cannot equal the 36-key reference) | CARRIED |\n| D10 | docstring | an unseeded `debug=1` request serves at least one popular row | :85 | An Engine whose ranks table is empty and serves no popular layer | CARRIED |\n| D11 | docstring | every popular row is in `fetch_popular_videos(dataset, POOL)` under the threshold and the NSFW filter | :87 | A popular row from the shared pool | CARRIED |\n| D12 | docstring | after serving, the fingerprint equals `shared_trending_before`, \"read before the seed was built\" | :90, :59 | A fingerprint move. :59 also fails a `before` read after a seed written into the shared table | CARRIED |\n| N1 | name | \"the session engine serves trending from its private ranks\" | :80, :87 | An Engine serving shared ranks on either the Trending feed or the popular layer | CARRIED |\n| N2 | name | \"and leaves the shared ranks unchanged\" | :90 | Any write to the shared `trending_ranks` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. independence (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:55\n   `before = request.getfixturevalue(\"shared_trending_before\")`\n   - The comment at :54 says this read comes \"before the seed is built and the Engine starts\" because it is requested first. That holds only if no earlier test in the session has already created the session-scoped `engine`.\n   - Once this test sits with other `engine` tests (for example in `tests/active/test_similar.py`), the C2 \"before the seed\" order depends on the conftest's fixture graph, not on this test. That means `trending_seed` would have to depend on `shared_trending_before`, and the conftest supplied does not have that yet.\n   - The order should come from the fixture dependency, not from where the request sits in this test.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:53\n   - The test only proves the success path: a working private seed served correctly.\n   - No failure mode of the private-ranks wiring is exercised here. An example would be an Engine start on a bad `--trending-db` path. That may be covered by another phase's test, but none was supplied.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:67\n   - Only a fully populated private seed is exercised. :67 makes the short or empty private order a precondition, not a case under test.\n   - No edge of the seed is tested, such as an empty private file or one shorter than three pages. No `must_prove` clause requires one.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `shared_trending_fingerprint` and the `shared_trending_before` fixture are not defined in `tests/active/conftest.py` as it reads now. The test binds the fixture only when it exists (:26-27). C2b was therefore judged from :59's `[3]` index and the comment at :58. Whether the helper reads all four named fields (row count, `fetched_at` min, max, and count > 0) could not be checked.\n2. `tests/active/conftest.py`'s `dataset` (:229-233) opens the shared `whitelist.db` read-only with no private view attached. Whether the edited `dataset` will carry the private seed's `trending_ranks`, which C1a and C1c compare against, could not be checked. The control at :70 is what guards it in the test.\n3. `tests/active/test_similar.py`'s `_FEED_CONSTANTS_CHILD` (:719-729) does not yet emit `popular_pool_size`. Whether the edited child reads it from the Engine's `DEFAULT_POPULAR_POOL_SIZE` (D5) could not be checked.\n4. `fixtures_path` was not supplied. The test's fixtures come from `tests/active/conftest.py`, which was read, but as noted above it is in its pre-edit state.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. Considered under `single-value-pin` (rules/shape.md), second `<how_to_spot>` bullet; not met, so not Critical. tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:89\n   after = conftest.shared_trending_fingerprint()\n   The C2 check compares two readings. Both `before` (through the `shared_trending_before` fixture) and `after` come from the conftest fingerprint code, and that code is one of the edited files under test. The control at line 59 (`assert before[3] > 0`) rules out the likely wrong version: a fingerprint that reads the private seed file, where every `fetched_at` is 0. A fingerprint that caches or snapshots its first reading would still make line 90 equal no matter what happened to the table. Reading the `after` value at line 89 independently would remove that gap. One way is a fresh `mode=ro` connection and the test's own `COUNT`/`MIN`/`MAX`/`SUM(fetched_at > 0)` query, as `_shared` already does for ranks. No rule names this remaining gap.\n\nPREDICTED FAILURE\nThe test stops at line 55, `request.getfixturevalue(\"shared_trending_before\")`, with a fixture lookup error, because `tests/active/conftest.py` defines no `shared_trending_before`. This is a setup error, not an assertion failure. The comment at line 25 says the test is meant to stop here. If the fixture existed, the first assertion to fail would be line 63, `isinstance(pool_size, int) and pool_size > 0`, because the `_feed_constants` child (test_similar.py:719-729) outputs only `feed`, `ordered` and `threshold`, with no `popular_pool_size`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/conftest.py and tests/active/test_similar.py as EDITED, but neither file as read contains the phase's changes. Missing are the `shared_trending_before` fixture, `shared_trending_fingerprint`, a private seed file behind `dataset` or the Engine (`trending_seed` still runs `DELETE FROM trending_ranks` on the shared `WHITELIST_DB` at conftest.py:141), and `popular_pool_size` in `_feed_constants`. So I answered the stub question from the assertion form and its controls, not from the fixtures as they will be:\n   - C1 pages (line 80): an Engine reading the shared table should fail here.\n   - C1 popular rows (lines 85-87): the positive control at line 85 plus the 25%-outside control at line 73 should catch the same case.\n   - Previous behaviour (seed written into the shared table): `dataset` and the shared read would then match, so the control at line 70 should catch it.\n   - C2 (line 90): covered as long as the fingerprint reads the live shared table, which I could not verify.\n2. I did not check whether `tmp_path`-free reads of `dataset` actually point at the private ranks. The test relies on that, and the fixture defining it has not been written yet.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (20 clauses: 6 must_prove, 12 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | Trending pages follow the private seed's ranks | :80 | An Engine serving any order other than `_reference(dataset, \"trending\")[:36]`, including one that ignores `exclude` and repeats page 1 | CARRIED |\n| C1b | must_prove | Trending pages do not follow the shared table's ranks | :80, armed by :70 | An Engine started without `--trending-db`, or a flag that never shadows the table. :70 makes the shared head differ from the private head, so serving the shared head fails :80 | CARRIED |\n| C1c | must_prove | popular-layer rows follow the private seed's ranks | :87 | A popular row drawn from outside `fetch_popular_videos(dataset, POOL)` under the threshold and the NSFW filter | CARRIED |\n| C1d | must_prove | popular-layer rows do not follow the shared table's ranks | :87, armed by :73 and :85 | A popular layer reading the shared pool. :73 puts at least a quarter of that pool outside the private one, and :85 rules out a vacuous empty set | CARRIED |\n| C2a | must_prove | shared fingerprint identical before the seed and after the Engine served | :90 (read at :89 after :76-83 served) | A seed written into the shared table (`fetched_at = 0` drops the fourth field, which :59 requires to be > 0 beforehand), or any Engine-side write to it | CARRIED |\n| C2b | must_prove | fingerprint = row count, `fetched_at` min and max, rows with `fetched_at > 0` | :90 (tuple equality), :59 indexes `[3]` | A change in any member the helper returns. Whether the helper returns all four could not be read (see NOT ASSESSED) | CARRIED |\n| D1 | docstring | \"serves Trending \u2026 from the session's private ranks\" | :80 | An Engine serving the shared head | CARRIED |\n| D2 | docstring | \"and its popular layer from the session's private ranks\" | :87 | A popular row outside the private pool | CARRIED |\n| D3 | docstring | \"the shared whitelist.db `trending_ranks` is left as it was\" | :90 | Any write that moves the fingerprint | CARRIED |\n| D4 | docstring | control: `shared_trending_before` shows a real fill | :59 | A shared table with no `fetched_at > 0` rows, where a write into it could leave the fingerprint unmoved | CARRIED |\n| D5 | docstring | control: `_feed_constants` reads the threshold and `DEFAULT_POPULAR_POOL_SIZE` | :61, :63, :64 | A child that failed to import, or a missing or non-positive `popular_pool_size` key. It does not exclude a hard-coded value under that key | CARRIED |\n| D6 | docstring | control: private Trending order runs past three pages | :67 | An empty or short private seed, or a `dataset` without the private view | CARRIED |\n| D7 | docstring | control: on a fresh plain read-only connection, the shared first three pages differ | :70 | A `dataset` carrying no private view, or a seed written into the shared table | CARRIED |\n| D8 | docstring | control: at least a quarter of the shared pool lies outside the private one | :73 | Shared and private pools so close that :87 cannot tell them apart | CARRIED |\n| D9 | docstring | three `mode=trending` pages, each excluding prior rows, are exactly the first three reference pages | :80 | Wrong order, wrong rows, or `exclude` ignored (a repeated page cannot equal the 36-key reference) | CARRIED |\n| D10 | docstring | an unseeded `debug=1` request serves at least one popular row | :85 | An Engine whose ranks table is empty and serves no popular layer | CARRIED |\n| D11 | docstring | every popular row is in `fetch_popular_videos(dataset, POOL)` under the threshold and the NSFW filter | :87 | A popular row from the shared pool | CARRIED |\n| D12 | docstring | after serving, the fingerprint equals `shared_trending_before`, \"read before the seed was built\" | :90, :59 | A fingerprint move. :59 also fails a `before` read after a seed written into the shared table | CARRIED |\n| N1 | name | \"the session engine serves trending from its private ranks\" | :80, :87 | An Engine serving shared ranks on either the Trending feed or the popular layer | CARRIED |\n| N2 | name | \"and leaves the shared ranks unchanged\" | :90 | Any write to the shared `trending_ranks` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. independence (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:55\n   `before = request.getfixturevalue(\"shared_trending_before\")`\n   - The comment at :54 says this read comes \"before the seed is built and the Engine starts\" because it is requested first. That holds only if no earlier test in the session has already created the session-scoped `engine`.\n   - Once this test sits with other `engine` tests (for example in `tests/active/test_similar.py`), the C2 \"before the seed\" order depends on the conftest's fixture graph, not on this test. That means `trending_seed` would have to depend on `shared_trending_before`, and the conftest supplied does not have that yet.\n   - The order should come from the fixture dependency, not from where the request sits in this test.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:53\n   - The test only proves the success path: a working private seed served correctly.\n   - No failure mode of the private-ranks wiring is exercised here. An example would be an Engine start on a bad `--trending-db` path. That may be covered by another phase's test, but none was supplied.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:67\n   - Only a fully populated private seed is exercised. :67 makes the short or empty private order a precondition, not a case under test.\n   - No edge of the seed is tested, such as an empty private file or one shorter than three pages. No `must_prove` clause requires one.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `shared_trending_fingerprint` and the `shared_trending_before` fixture are not defined in `tests/active/conftest.py` as it reads now. The test binds the fixture only when it exists (:26-27). C2b was therefore judged from :59's `[3]` index and the comment at :58. Whether the helper reads all four named fields (row count, `fetched_at` min, max, and count > 0) could not be checked.\n2. `tests/active/conftest.py`'s `dataset` (:229-233) opens the shared `whitelist.db` read-only with no private view attached. Whether the edited `dataset` will carry the private seed's `trending_ranks`, which C1a and C1c compare against, could not be checked. The control at :70 is what guards it in the test.\n3. `tests/active/test_similar.py`'s `_FEED_CONSTANTS_CHILD` (:719-729) does not yet emit `popular_pool_size`. Whether the edited child reads it from the Engine's `DEFAULT_POPULAR_POOL_SIZE` (D5) could not be checked.\n4. `fixtures_path` was not supplied. The test's fixtures come from `tests/active/conftest.py`, which was read, but as noted above it is in its pre-edit state.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "Trending pages follow the private seed's ranks",
            "assertion": ":80",
            "excludes": "An Engine serving any order other than `_reference(dataset, \"trending\")[:36]`, including one that ignores `exclude` and repeats page 1",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "Trending pages do not follow the shared table's ranks",
            "assertion": ":80, armed by :70",
            "excludes": "An Engine started without `--trending-db`, or a flag that never shadows the table. :70 makes the shared head differ from the private head, so serving the shared head fails :80",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "popular-layer rows follow the private seed's ranks",
            "assertion": ":87",
            "excludes": "A popular row drawn from outside `fetch_popular_videos(dataset, POOL)` under the threshold and the NSFW filter",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "popular-layer rows do not follow the shared table's ranks",
            "assertion": ":87, armed by :73 and :85",
            "excludes": "A popular layer reading the shared pool. :73 puts at least a quarter of that pool outside the private one, and :85 rules out a vacuous empty set",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "shared fingerprint identical before the seed and after the Engine served",
            "assertion": ":90 (read at :89 after :76-83 served)",
            "excludes": "A seed written into the shared table (`fetched_at = 0` drops the fourth field, which :59 requires to be > 0 beforehand), or any Engine-side write to it",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "fingerprint = row count, `fetched_at` min and max, rows with `fetched_at > 0`",
            "assertion": ":90 (tuple equality), :59 indexes `[3]`",
            "excludes": "A change in any member the helper returns. Whether the helper returns all four could not be read (see NOT ASSESSED)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"serves Trending \u2026 from the session's private ranks\"",
            "assertion": ":80",
            "excludes": "An Engine serving the shared head",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"and its popular layer from the session's private ranks\"",
            "assertion": ":87",
            "excludes": "A popular row outside the private pool",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"the shared whitelist.db `trending_ranks` is left as it was\"",
            "assertion": ":90",
            "excludes": "Any write that moves the fingerprint",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "control: `shared_trending_before` shows a real fill",
            "assertion": ":59",
            "excludes": "A shared table with no `fetched_at > 0` rows, where a write into it could leave the fingerprint unmoved",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "control: `_feed_constants` reads the threshold and `DEFAULT_POPULAR_POOL_SIZE`",
            "assertion": ":61, :63, :64",
            "excludes": "A child that failed to import, or a missing or non-positive `popular_pool_size` key. It does not exclude a hard-coded value under that key",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "control: private Trending order runs past three pages",
            "assertion": ":67",
            "excludes": "An empty or short private seed, or a `dataset` without the private view",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "control: on a fresh plain read-only connection, the shared first three pages differ",
            "assertion": ":70",
            "excludes": "A `dataset` carrying no private view, or a seed written into the shared table",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "control: at least a quarter of the shared pool lies outside the private one",
            "assertion": ":73",
            "excludes": "Shared and private pools so close that :87 cannot tell them apart",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "three `mode=trending` pages, each excluding prior rows, are exactly the first three reference pages",
            "assertion": ":80",
            "excludes": "Wrong order, wrong rows, or `exclude` ignored (a repeated page cannot equal the 36-key reference)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "an unseeded `debug=1` request serves at least one popular row",
            "assertion": ":85",
            "excludes": "An Engine whose ranks table is empty and serves no popular layer",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "every popular row is in `fetch_popular_videos(dataset, POOL)` under the threshold and the NSFW filter",
            "assertion": ":87",
            "excludes": "A popular row from the shared pool",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "after serving, the fingerprint equals `shared_trending_before`, \"read before the seed was built\"",
            "assertion": ":90, :59",
            "excludes": "A fingerprint move. :59 also fails a `before` read after a seed written into the shared table",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"the session engine serves trending from its private ranks\"",
            "assertion": ":80, :87",
            "excludes": "An Engine serving shared ranks on either the Trending feed or the popular layer",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"and leaves the shared ranks unchanged\"",
            "assertion": ":90",
            "excludes": "Any write to the shared `trending_ranks`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nnone \u2014 `engine/server/data/trending.py` and `engine/server/api/server.py` were already the smallest shape that passes, so I made no edits.\n</refactors>\n\n<left_out>\nRemoving the one-line \"what\" comment above `TRENDING_OVERRIDE_SCHEMA` in `engine/server/data/trending.py`: it is cosmetic, and the approved draft (plan line 472) has the constant in the same form.\nInlining `TRENDING_OVERRIDE_SCHEMA` into the two f-strings of `attach_trending_override`: it is one name used twice in one function, the approved draft defines it, and inlining saves no lines.\nMerging the two `args.trending_db` branches in `server.py` `main()` into one: they cannot merge, because `prepare_trending_override` must run before `connect_db` (so a bad path stops the start before whitelist.db is opened) and the attach must run after it, after the committing `executescript` ensures.\nLogging the plan's optional `trending_db=` line at startup: that would be new behaviour, not a refactor, and no test or requirement asks for it.\nAdding `engine/server/data/trending.py` to the `test_server_config.py` group in `tests/config.json`: this belongs with promoting the Phase 2 checkpoint into that file, not with a production refactor, and changing it mid-build would move the fingerprint being gated.\nTest files (`tests/active/conftest.py`, `tests/active/test_similar.py`, `tests/active/test_random_videos.py`, `tests/active/test_server_config.py`) and the gated `tests/tmp/test_44_*` checkpoints: not production code, and the gated ones are not mine to edit.\nCleanup that needs the operator, since I cannot delete files: tests/tmp/probe_private_seed.py, probe_phase3_unflagged_engine.py, probe_phase3_fingerprint.py, probe_phase3_engine_popular.py, probe_phase3_shared_vs_private.py, probe_valid_start.py, probe_trending_db_flag.py, probe_override_plan.py and probe_override.py are leftover probes from earlier phases.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nI read both production files on disk and searched for every user of the new names. The override is three names in `trending.py`, used only by the guarded branches in `server.py` `main()` and by the `conftest.py` fixtures, with no duplication or dead code, so I made no change and ran nothing.\n</observation>",
  "harvest_plan": {
    "harvest_file": "docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md",
    "plan": "## Harvest plan: build 47-44 (trending seed write lock during)\n\nI've classified the 4 tests in this build's 3 files in `tests/tmp`. All 4 should move into the durable suite (`DURABLE`). Nothing has moved yet and the group map is unchanged.\n\nBefore this, the config check passed with nothing defaulted and no conflicts. A snapshot of `tests/last_test_validation.json` was saved as `.preharvest` and checked byte-identical to the original. All 3 files load in pytest (4 items), checked with `pytest --collect-only`, which records nothing.\n\n### Count per verdict\n| Verdict | Count |\n|---|---|\n| DURABLE | 4 |\n| REPLACES | 0 |\n| COMBINE | 0 |\n| REDUNDANT | 0 |\n| SPENT | 0 |\n\n### Tests that move (DURABLE) and where they go\n1. **`test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`** (phase 1) \u2192 `tests/active/test_random_videos.py`\n   - It checks that a connection prepared by `attach_trending_override` gets the attached file's ranks from both the Trending page and the popular pool.\n   - It also checks that a plain connection to the same database still gets main's ranks, and that main's ranks are not changed.\n   - No test in `tests/active` checks this.\n   - It brings `OVERRIDE_EXPECTED`, `OVERRIDE_UNSERVED`, `_private_file` and `_prepared` with it, and uses the file's own `_ranks_db`, `RANKS`, `TRENDING_EXPECTED` and `_trending_labels`.\n2. **`test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`** (phase 1) \u2192 `tests/active/test_random_videos.py`\n   - The existing query-plan test only looks at main's ranks.\n   - This one checks that a Trending page read through the attached file still uses `idx_trending_ranks_order` and does no sort (no `TEMP B-TREE`).\n   - It brings `_catalogue` and `_catalogue_ranks` with it.\n   - **Optional, needs your OK:** change the existing `test_a_trending_page_walks_the_ranks_index_without_sorting` to call those two helpers instead of keeping its own copy of the same setup code. Its assertions would not change.\n3. **`test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`** (phase 2) \u2192 `tests/active/test_server_config.py`\n   - It checks that `server.py --trending-db` is accepted.\n   - A missing path or a non-SQLite file must stop the start with a non-zero exit, name the path, create nothing and change nothing.\n   - A real SQLite file must get past the check and start.\n   - It uses the file's own `_run`, `_free_port`, `_has_started`, `ENGINE_PY`, `API_DIR`, `ENGINE_START_LOCK` and `VARIANT_START_SECONDS`, and brings `SERVER_PY`, `JUNK`, `_argv`, `_start` and `_starts_serving`.\n   - The workarounds it needed to run from `tests/tmp` (loading its helper by path, editing `sys.path`) are dropped.\n4. **`test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged`** (phase 3) \u2192 `tests/active/test_similar.py`\n   - It overlaps `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` but adds three things no active test checks:\n     - a check that the shared table's first pages differ from the private seed's, so the test can tell which one the Engine served;\n     - that live popular-layer rows come from the private pool;\n     - that the shared `whitelist.db` `trending_ranks` fingerprint is the same after the Engine has served. That is the rule this build exists for.\n   - I classed it as DURABLE rather than COMBINE because the ordered test runs over every ordered mode, and these checks only apply to Trending.\n   - In `tests/active` it takes the fixtures `shared_trending_before`, `engine` and `dataset` as plain arguments. The temporary `hasattr` guard and the `getfixturevalue` ordering are dropped.\n   - It brings `POOL_KEY`, `TRENDING_HEADERS` and `POPULAR_HEADERS` (client IPs 192.0.2.180 and .181, which no other test uses) and `_shared`.\n   - **Risk:** it goes red if the shared table has no real data in it, or if the updater's trending stage runs during the suite. Its failure message names that second cause.\n\n### Active tests that would be retired\nNone. Nothing goes to `tests/archive/` and no active test is renamed.\n\n### `test_groups` changes\n- **`test_server_config.py`**: add `engine/server/data/trending.py`. The refusal and no-create rule the moved test checks live in `prepare_trending_override`. Phase 2 put this addition off until the test was moved.\n- **`test_similar.py`**: add `engine/server/api/recommendations/candidates/popular_videos.py`, because the moved test checks which rows the live popular layer serves. Leave this out if you count that as the mixer's job, and `mixer.py` is already listed.\n- **`test_random_videos.py`**: no change. It already lists `random_videos.py` and `trending.py`.\n- **`conftest.py`**: stays unlisted. It is a shared helper.\n\n### New subject files\nNone.\n\n### Cleanup after the move (Step 7)\n13 entries go to `delete_me/`, and none of the names are already taken there:\n- the 3 `test_44_*` checkpoints;\n- 9 leftover `probe_*.py` files, one of them already empty;\n- `tests/tmp/__pycache__`, renamed to `__pycache__-harvest44`.\n\n`tests/tmp` is empty afterwards.\n\n### Decisions for you\n1. Approve the 4 DURABLE moves and their destinations.\n2. Approve or decline the optional change to the existing query-plan test in `test_random_videos.py`.\n3. Approve or decline adding `popular_videos.py` to the `test_similar.py` group."
  },
  "build_diff": {
    "path": ".scratch/44-trending-seed-write-lock-during/build.diff",
    "files": [
      "docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md",
      "engine/server/api/server.py",
      "engine/server/data/trending.py",
      "tests/active/conftest.py",
      "tests/active/test_similar.py",
      "tests/last_test_output.txt",
      "tests/last_test_validation.json",
      "tests/last_test_validation.json.preharvest",
      "tests/tmp/probe_override.py",
      "tests/tmp/probe_override_plan.py",
      "tests/tmp/probe_phase3_engine_popular.py",
      "tests/tmp/probe_phase3_fingerprint.py",
      "tests/tmp/probe_phase3_shared_vs_private.py",
      "tests/tmp/probe_phase3_unflagged_engine.py",
      "tests/tmp/probe_private_seed.py",
      "tests/tmp/probe_trending_db_flag.py",
      "tests/tmp/probe_valid_start.py",
      "tests/tmp/test_44_trending_seed_write_lock_during_phase1.py",
      "tests/tmp/test_44_trending_seed_write_lock_during_phase2.py",
      "tests/tmp/test_44_trending_seed_write_lock_during_phase3.py"
    ],
    "withheld": 0,
    "end": "6941bc979c3484272b92396a70f399e30ea029e8",
    "moved_to": "delete_me/44-trending-seed-write-lock-during.build.diff"
  },
  "harvest_report": "<moved>\ntests/tmp/test_44_trending_seed_write_lock_during_phase1.py::test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it \u2192 tests/active/test_random_videos.py (group test_random_videos.py), with OVERRIDE_EXPECTED, OVERRIDE_UNSERVED, _private_file and _prepared\ntests/tmp/test_44_trending_seed_write_lock_during_phase1.py::test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting \u2192 tests/active/test_random_videos.py (group test_random_videos.py), with _catalogue and _catalogue_ranks. The approved optional refactor is done: the existing test_a_trending_page_walks_the_ranks_index_without_sorting now calls _catalogue(conn) then _catalogue_ranks(conn), and its assertions are unchanged.\ntests/tmp/test_44_trending_seed_write_lock_during_phase2.py::test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it \u2192 tests/active/test_server_config.py (group test_server_config.py), with SERVER_PY, JUNK, _argv, _start, _starts_serving and `import sqlite3`. The by-path harness load and the sys.path insert were dropped.\ntests/tmp/test_44_trending_seed_write_lock_during_phase3.py::test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged \u2192 tests/active/test_similar.py (group test_similar.py), with POOL_KEY, TRENDING_HEADERS (192.0.2.180), POPULAR_HEADERS (192.0.2.181) and _shared. It takes shared_trending_before, engine and dataset as plain fixtures, and the hasattr guard and getfixturevalue ordering were dropped. It imports WHITELIST_DB and shared_trending_fingerprint from conftest and fetch_popular_videos from data.random_videos.\nEach destination file's module docstring gained bullets for the new tests, and the clause tags (C1/C2) were replaced by the rule each assertion gates.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\ntest_server_config.py: added engine/server/data/trending.py, where prepare_trending_override holds the refusal and no-create rule the moved test gates.\ntest_similar.py: added engine/server/api/recommendations/candidates/popular_videos.py. The operator approved this optional item through AskUser.\nNo other entry changed. test_random_videos.py was already complete, and conftest.py stays unclaimed.\n`validate_tests.py --audit-map` exit 0. No MISSING finding names a file the moved tests drive. The engine/server/data/time.py and tmp/suite28 findings were there before this harvest.\n</group_map>\n\n<mutations>\nm1, engine/server/data/trending.py: attach_trending_override with its CREATE TEMP VIEW line replaced by `pass`. Red: test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it failed at `_trending_labels(fetch_ordered_page(prepared, \"trending\", 100, 0)) == OVERRIDE_EXPECTED` ('C1' != 'B5' at index 0). Restored from .bak, diff identical. Green: 1 passed.\nm2, engine/server/data/trending.py: the TEMP VIEW as `SELECT DISTINCT *`, so it is not flattened. Red: test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting failed at `any(\"idx_trending_ranks_order\" in detail ...)` with plan [CO-ROUTINE trending_ranks, SCAN trending_override.trending_ranks, SCAN t, ...], after its full-page and Popular TEMP B-TREE controls passed. Restored from .bak, diff identical. Green: 1 passed.\nm3, engine/server/data/trending.py: prepare_trending_override's SystemExit message without {path}. Red: test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it failed at `str(missing) in run.stderr` (stderr \"trending ranks file cannot be opened as SQLite: unable to open database file\"). Restored from .bak, diff identical. Green: 1 passed. I chose this over a mode=rwc mutation, because that start gets through and serves until _run's 120 s timeout, which is the hanging kind.\nm4, engine/server/api/server.py: main() with `attach_trending_override(db, args.trending_db)` replaced by `pass`, so the Engine reads the shared table and writes nothing. Red: test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged failed at `first + second + third == reference[: 3 * FEED_PAGE]` (differs at index 1), after all its controls passed. Restored from .bak, diff identical. Green: 1 passed, the fingerprint assertion included.\nAll four backups (trending.py.bak-harvest44-m1, m2 and m3, server.py.bak-harvest44-m4) were moved to delete_me/. None of this harvest's .bak files is left under engine/. The engine/server/db/whitelist.db.bak-20261002-212806 there was already there before this harvest.\n</mutations>\n\n<cleared>\n17 entries were added to delete_me/ by this harvest:\n- the 3 checkpoints: test_44_trending_seed_write_lock_during_phase1.py, phase2.py and phase3.py;\n- the 9 probes: probe_override.py, probe_override_plan.py, probe_phase3_engine_popular.py, probe_phase3_fingerprint.py, probe_phase3_shared_vs_private.py, probe_phase3_unflagged_engine.py, probe_private_seed.py (empty), probe_trending_db_flag.py and probe_valid_start.py;\n- tests/tmp/__pycache__, renamed to __pycache__-harvest44;\n- the 4 mutation backups: trending.py.bak-harvest44-m1, m2 and m3, and server.py.bak-harvest44-m4.\nNone of the names collided, and each was moved with mv -n. tests/tmp now holds 0 entries. delete_me/ holds 120 entries (103 before). Nothing has been deleted; the operator decides what to remove.\nClosing run: the snapshot was restored from tests/last_test_validation.json.preharvest, then `validate_tests.py --compare` exited 0. It ran 4 of 59 groups (test_random_videos.py, test_server_config.py, test_similar.py, and the unmapped test_search_fusion.py) and carried 55 forward as unchanged. 175 passed, 0 failed.\nAgainst the pre-harvest record: 4 appeared (the 4 harvested tests), 0 departed, no new red, nothing newly green. The steps are recorded in docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md.\n</cleared>"
}
```
dev-flow:state -->

## 2026-10-03 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Start snapshot: tree `933762268c5f597d611f1416a976e3515d2bde03` at 2026-10-03T10:06:46-04:00.

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 59 test groups (58 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.2s
  ---------------------
  total                  10 passed                              2.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Purpose

Running the active suite must never change, or hold a write lock on, the shared dev `engine/server/db/whitelist.db` table `trending_ranks`. That file is the one the operator's long-running :7070 dev Engine serves, and worktrees symlink it too. Today the session fixture `trending_seed` (in `tests/active/conftest.py`) runs `DELETE FROM trending_ranks` and re-inserts `TRENDING_SEED_SQL` (each host's 100 most-viewed catalogue videos, `fetched_at = 0`, about 88,648 rows) on every lane start. That wipes any real fill (rows with `fetched_at > 0`) and holds the write lock for about 4.6 s in rollback-journal mode, against the Engine's 5 s busy timeout, while other lanes' Engines serve from the same file. The fix chosen with the operator: the test Engine reads private ranks through a new Engine CLI flag `--trending-db PATH`, and the suite never writes the shared `trending_ranks`. This is test isolation only. The Trending definition, CONTEXT.md and the ADRs do not change.

### Engine: `--trending-db PATH`

- `engine/server/api/server.py` `parse_args` gains an optional `--trending-db PATH`, with help text, so it shows in `--help`. It follows the style of the existing arguments (`--no-random-cache-refresh` and the others).
- When the flag is set, every query the Engine runs against `trending_ranks` reads the table from the file at PATH. Today those are the `trending` entry of `ORDERED_FEED_SOURCE` in `engine/server/data/random_videos.py`, run through `fetch_ordered_page`, which `engine/server/api/handlers/similar.py` calls on `server.db`, and `fetch_popular_videos` (the Recommendations popular-layer pool), which `candidates/popular_videos.py` calls on `server.db`. `videos`, `video_embeddings`, moderation, interaction and every other table still come from `whitelist.db`.
- The mechanism is the designer's choice, but it must cover every Engine connection on `whitelist.db` that runs a `trending_ranks` query. Today that is only `server.db` (`connect_db`). `search_db` (`connect_readonly_db`) and the random-cache build's source connection do not run Trending queries. Tree fact for the design: the shared `whitelist.db` already holds a `main.trending_ranks`, and SQLite resolves unqualified names in the order temp, main, then attached databases. A bare `ATTACH` of PATH therefore does NOT shadow the shared table. A TEMP view on the connection, or schema-qualified SQL, would.
- With the flag set, the Engine never writes the shared file's `trending_ranks`, including at startup. `ensure_trending_schema` (server.py, currently called on `db` right after `ensure_interaction_event_schema`) applies to the private file instead of `whitelist.db`. The table shape and index (`trending_ranks`, `idx_trending_ranks_order`) are unchanged.
- If PATH does not exist or cannot be opened as SQLite, the Engine start fails: it exits non-zero with an error message that names the path. It never silently falls back to the shared table, and it does not create the file. (Existing precedent: `connect_readonly_db` uses `mode=ro`, which never creates a file.)
- Without the flag, behaviour and SQL plans are unchanged. The Trending page query still uses `idx_trending_ranks_order` as the driving index (the `CROSS JOIN` order), with no `TEMP B-TREE`, so an OFFSET walk stops early. The same must also hold with the flag set, so the test Engine exercises the same plan shape.

### Active suite: private seed

- `trending_seed` in `tests/active/conftest.py` builds the seed in a per-session temporary SQLite file (for example under `tmp_path_factory`), not in the shared DB. It applies `ensure_trending_schema` to that file and fills it with exactly the rows `TRENDING_SEED_SQL` produces today: same columns, ranks, likes, views and `fetched_at = 0`. It reads `videos` and `video_embeddings` from the shared `whitelist.db` through a read-only connection only, for example by attaching the shared DB read-only to the temp file's connection, or by opening the shared DB `mode=ro` and attaching the temp file. Either way the only file written is the temp file.
- The `engine` fixture passes `--trending-db <temp file>` alongside `--no-random-cache-refresh`.
- The seed no longer takes `ENGINE_START_LOCK`, because it no longer writes a shared file. The `engine` fixture keeps the lock for serialising Engine starts. Other tests import `ENGINE_START_LOCK` (`test_random_cache.py`, `test_server_config.py`), so the constant stays.
- The fixture docstrings and the module docstring (conftest.py line 7 says `trending_seed` "has rewritten that dataset's `trending_ranks`") are updated to describe the private seed.
- The suite opens no write connection to the shared `whitelist.db` for Trending.

### Acceptance criteria

- Starting the Engine with `--trending-db` on a seeded temp file serves Trending (`mode=trending`) in that file's merged-rank order. The shared `whitelist.db`'s `trending_ranks` fingerprint (row count; `fetched_at` min and max; count of rows with `fetched_at > 0`) is identical before and after.
- Without the flag, Trending serves from `whitelist.db`'s `trending_ranks` as before.
- Starting with `--trending-db` on a path that does not exist exits non-zero, with an error naming the path, and creates no file at that path.
- After a full active-suite run, the shared `whitelist.db`'s `trending_ranks` fingerprint is unchanged, tested with a real fill present (rows with `fetched_at > 0`; the triage found 86,826 such rows in place). The suite cannot observe its own end, so this is checked by recording the fingerprint read-only before the build's full suite run and comparing it after. An in-suite test also gates that the session Engine started with the flag leaves the shared fingerprint unchanged.
- The active suite passes, including the Trending and popular-layer tests in `test_similar.py` and its Trending NSFW control (a flagged row in the first 96 of the seeded order), with no test expectations changed.

### Out of scope

- Other test writes to the shared `whitelist.db`, such as bridge-mode interaction events from `engine_client`, and the other Engines the suite starts without the flag (`test_random_cache.py`, `test_server_config.py`). Those read the shared ranks, and their `ensure_trending_schema` is a `CREATE ... IF NOT EXISTS` that writes nothing when the table exists.
- Confirming or fixing the intermittent up-next 500 (memory `upnext-pin-engine-500-intermittent`) beyond removing this writer.
- Changing the seed's content or ranking, `engine/server/db/jobs/fetch-trending.py`, the updater's trending stage, or the moderation purge of `trending_ranks` (`engine/server/data/moderation.py`).
- A general override for `whitelist.db` or the other DB paths.

### Documentation

- Document `--trending-db` where Engine CLI behaviour is described for developers (its `--help` text at minimum, and `engine/server/README.md` if it lists Engine flags), as a dev/test override that reads only `trending_ranks` from PATH.

### Baseline suite state

- Pre-build baseline: the active suite exits with code 0, no variant run (`variant: false`). The build must end with the suite still green.

### conflicts

The brief suggests attaching the private file on each Engine connection and relies on "SQLite resolves temp objects before main". But the shared `whitelist.db` already holds `main.trending_ranks`, and an ATTACHed schema is searched after main, so a plain ATTACH would leave every unqualified query still reading the shared table. The override has to go through a TEMP object (for example a TEMP view over the attached table) or schema-qualified SQL, and it must keep `idx_trending_ranks_order` as the driving index.
Acceptance criterion "after a full active-suite run, the shared trending_ranks is unchanged" cannot be asserted from inside the suite it covers. It is met by a fingerprint taken before and after the build's suite run, plus an in-suite test on the session Engine.

## 2026-10-03 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

The change has two halves. The Engine gets a flag that sends its `trending_ranks` reads to a private file. The active suite seeds that private file and passes the flag. No `trending_ranks` SQL changes, and no function signature in `data/random_videos.py`, `handlers/similar.py` or `candidates/popular_videos.py` changes.

**Engine flag.** `parse_args` in `engine/server/api/server.py` gains `--trending-db PATH` with `default=None`. It is written in the same `parser.add_argument(..., help=(...))` style as the other arguments. The help text says it is a dev/test override: only `trending_ranks` is read from PATH, the file must already exist and is never created, and every other table still comes from `whitelist.db`. That puts it in `--help`. `engine/server/README.md` does not list any Engine flags (I checked: none of the existing flags appear there), so `--help` is where this is documented, which is the minimum the requirement asks for.

**How the override works: a TEMP view on `server.db`.** This goes in one small helper next to `ensure_trending_schema` in `engine/server/data/trending.py`. When the flag is set, `main()` does three things:

1. **Validate first.** Before `connect_db(db_path)` and before anything touches `whitelist.db`, it opens PATH read-write with no create (the same URI precedent as `connect_readonly_db`, but `mode=rw`). It then runs `ensure_trending_schema` on that connection and closes it. This one step does three jobs:
   - A missing path fails, and nothing is created.
   - A file that is not SQLite fails on the schema statement ("file is not a database").
   - The table and its index `idx_trending_ranks_order` are applied to the private file and not to `whitelist.db`.
   
   Any `sqlite3.Error` here becomes `SystemExit` with a message naming the path, so the exit is non-zero and the message goes to stderr. Because this runs before the FAISS load, a bad path fails in well under a second.
2. **Attach.** After `connect_db`, it runs `ATTACH` of PATH on `db` under a fixed schema name.
3. **Shadow.** It runs `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`. SQLite looks up unqualified names in the order temp, main, attached. So every unqualified `trending_ranks` on that connection now resolves to the private file. That covers the `trending` entry of `ORDERED_FEED_SOURCE` through `fetch_ordered_page` (the handler path) and `fetch_popular_videos` (the popular-layer path), because both run on `server.db`.

When the flag is set, the existing `ensure_trending_schema(db)` call is skipped, because step 1 has already applied it to the private file. Without the flag, that call and everything else stay byte-for-byte as they are.

**Checks against the tree:**
- `server.db` is assigned once in `SimilarServer.__init__` and never replaced, so a per-connection view lasts the life of the process.
- The only Engine code that writes `trending_ranks` is the moderation purge, and the only callers of `purge_host_data` are the jobs and job tests, never the API. So with the flag set, the Engine has no write path to the shared `trending_ranks`.
- `search_db` and the random-cache source connection never mention `trending_ranks`, so they need nothing.
- A TEMP view lives in the connection's temp schema, so creating it writes nothing to `whitelist.db`.

**Plan shape with the flag.** The view is a plain `SELECT *` with no aggregate, DISTINCT, LIMIT or ORDER BY, and it is the left operand of the `CROSS JOIN`. SQLite's query flattener should therefore inline it as `<schema>.trending_ranks t CROSS JOIN video_embeddings e`. The private table drives the join through `idx_trending_ranks_order` with no `TEMP B-TREE`, the same plan as today. This is an expectation, not something I have verified, so the build gates it with an `EXPLAIN QUERY PLAN` test on a connection prepared by the helper, alongside the existing unflagged plan test in `test_random_videos.py`.

**Active suite.** `trending_seed` in `tests/active/conftest.py`:
- creates `trending.db` under `tmp_path_factory.mktemp(...)`, opened as a URI connection so that URI filenames work in `ATTACH`;
- applies `ensure_trending_schema` to it;
- attaches `whitelist.db` with `mode=ro`;
- runs the unchanged `TRENDING_SEED_SQL`;
- returns the path.

The unqualified names resolve correctly with no SQL edit: the insert target `trending_ranks` resolves to the temp file's main schema, which comes before the attached shared copy, while `videos` and `video_embeddings` exist only in the attached shared DB. The rows are exactly today's: same columns, ranks, likes, views and `fetched_at = 0`. The only file written is the temp file.

The seed drops `ENGINE_START_LOCK`. The constant stays, because `test_random_cache.py` and `test_server_config.py` import it. The `engine` fixture keeps the lock and adds `--trending-db <path>` next to `--no-random-cache-refresh`. The module docstring (line 7) and both fixture docstrings are rewritten to describe the private seed.

No session test reads `trending_ranks` through `dataset`. They only observe the Engine, so `test_similar.py`'s Trending, popular-layer and NSFW-control expectations still hold, since the served order is the same seeded order.

**How each acceptance criterion gets gated (detail belongs to the test step):**
- **Flag serves the private file's order; shared fingerprint unchanged.** A session-scoped fixture reads the shared fingerprint read-only before the seed and the Engine start: row count, `fetched_at` min and max, and the count of rows with `fetched_at > 0`. An in-suite test asks the session Engine for `mode=trending` pages and a popular-layer request, then checks two things. The pages must equal the merged-rank order computed from the temp file joined with the read-only dataset, under the NSFW filter. The shared fingerprint must be unchanged.
- **Without the flag, Trending reads `whitelist.db`.** This is gated in-process rather than with another Engine start. A temp main DB holding ranks A and a temp private file holding ranks B are set up. `fetch_ordered_page` and `fetch_popular_videos` serve A on a plain connection and B on a helper-prepared connection. Main's ranks are unchanged afterwards. The plan assertions above run on both connections.
- **Missing path.** A subprocess Engine start with `--trending-db <missing>`, the same way `test_server_config.py` drives the entry point, must exit non-zero, show the path in stderr, and leave no file at that path. The same test covers a non-SQLite file. This start fails before binding or opening `whitelist.db`, so it needs no start lock.
- **Full-suite run with a real fill.** The build reads the fingerprint read-only before its full suite run and compares it afterwards. The shared DB currently holds a real fill (the triage found 86,826 rows with `fetched_at > 0`).

### Alternatives considered

- **Schema-qualified SQL**, for example a `trending` source string chosen per call or a schema argument passed through `fetch_ordered_page`, `fetch_popular_videos`, the builder deps and the handler. Rejected: it changes signatures and SQL on the default path, and touches several files to support a dev-only override. The requirement asks for unchanged behaviour and SQL without the flag. The view keeps every query untouched.
- **A bare `ATTACH` with no view.** Rejected: as the requirements note, `main.trending_ranks` already exists in `whitelist.db` and comes before attached databases in name lookup, so it would silently keep serving the shared table.
- **Opening the private file as `main` and attaching `whitelist.db`.** Rejected: every other table, and every write (moderation, interaction events), would then resolve against the wrong file.
- **Rebuilding `server.db` with URI handling (`uri=True` in `connect_db`) so that `ATTACH` could use `mode=rw`.** Rejected: it changes `connect_db` for every caller to tighten one race that the validation step already covers.
- **Seeding by opening the shared DB `mode=ro` and attaching the temp file.** Rejected: unqualified `trending_ranks` would then resolve to the shared, read-only main, so the INSERT would fail or need qualified SQL. Opening the temp file as main and attaching the shared DB keeps `TRENDING_SEED_SQL` verbatim.
- **Copying `whitelist.db` per session.** Rejected: it is multi-GB and isolates far more than the requirement asks for.

### Gotchas and risks

- **Plain `ATTACH` creates a missing file**, because `server.db` is not a URI connection. The no-create guarantee therefore comes from the `mode=rw` validation that runs just before. If the file is deleted in the gap between validation and attach, an empty file would be created and Trending would serve empty, without falling back to the shared table. I am accepting this as a named limitation. The way up is a URI-enabled `server.db`.
- **Relying on the query flattener.** If a future SQLite version or a view edit stops flattening, the plan would gain a scan or sort with the flag set, but default-path plans would be untouched. The flagged-plan test catches this.
- **The seed still reads the shared DB for a few seconds** under a SHARED lock, because the DB is in rollback-journal mode. That can delay, but not block for good, a writer's commit on the shared file, such as the dev Engine's interaction ingest or an updater run. The write lock and the 5 s busy-timeout collision are gone, which is what the requirement is about. The suite's `dataset` reads already behave this way.
- **External changes to the fingerprint.** If the operator's updater fills `trending_ranks` during a suite run, the in-suite fingerprint gate goes red without the suite being at fault. The failure message should say so.
- **Relative paths.** A relative PATH resolves against the Engine's working directory, unlike the repo-root-relative default DB paths. The fixture passes an absolute path, and the help text says the path is used as given.
- **Seed drift.** The private seed is still built from the live catalogue, so the existing caveat about the NSFW control (one flagged row in the first 96) is unchanged.

### Tradeoffs the operator is asked to accept

- **Engine code exists only for tests.** A dev/test flag ships in the production entry point, using a connection-level trick (a TEMP view shadowing a main table) that someone reading the SQL alone would not expect. A comment at the view creation and the help text explain it.
- **No guarantee that the file cannot be created** (the race above). It is a documented ceiling, not a hard guarantee.
- **Out of scope, as agreed.** Other suite writes to `whitelist.db` stay: bridge interaction events, and the unflagged Engines in `test_random_cache.py` and `test_server_config.py`.

### conflicts

none

## 2026-10-03 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impact path="engine/server/api/server.py" element="parse_args() (lines 153-203): new --trending-db PATH argument">
**What changes:** add one `parser.add_argument("--trending-db", default=None, help=(...))`. Put it after the `refresh_group` block and before `parser.set_defaults(random_cache_refresh=None)` / `return parser.parse_args()`. Follow the existing `help=(...)` multi-string style. Argparse derives `dest` as `trending_db`, so `args.trending_db` is `None` when the flag is absent. Per the plan, the help text should say four things: it is a dev/test override; only `trending_ranks` is read from PATH; PATH must exist and is never created; the path is used as given, so a relative one resolves against the working directory. The parser uses `CompactHelpFormatter` (`scripts/cli_format.py`), so the metavar renders as `--trending-db TRENDING_DB` unless `metavar="PATH"` is given. Match whatever the tests assert.

**What depends on it:**
- `tests/active/test_server_config.py::test_server_py_exits_before_argument_parsing_on_a_bad_value` (line 78) runs `server.py --help` and asserts `"--port PORT" in ok.stdout`. A new option does not affect that line.
- The systemd unit `peertube-engine@.service` (`DEPLOYMENT.md:111`, `ExecStart=... server.py --host 127.0.0.1 --port %i`) does not pass the flag.
- `scripts/run-services.sh:35` does not pass it either.
- The test runners pass argv through: `CACHE_VARIANT_RUNNER` in `test_random_cache.py:138` and `VARIANT_RUNNER` in `test_server_config.py:204-216` both set `sys.argv = [server, *sys.argv[3:]]`.

**Regression risk:** low. The flag is optional with a `None` default, and there are no mutually-exclusive interactions.
</impact>
<impact path="engine/server/api/server.py" element="main() startup sequence (lines 326-338): validate PATH before connect_db, ATTACH + TEMP VIEW after it, skip ensure_trending_schema(db) when flagged">
**What changes:**
- **Before line 332** (`db = connect_db(db_path)`): when `args.trending_db` is set, call the new helper's validation step. It opens `file:<path>?mode=rw` with `uri=True`, runs `ensure_trending_schema`, closes the connection, and turns any `sqlite3.Error` into `SystemExit(<message naming the path>)`.
- **After `connect_db`:** ATTACH the file under a fixed schema name and `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`.
- **Line 337** (`ensure_trending_schema(db)`, with its comment at 336) becomes conditional on the flag being unset.

Ordering matters:
- ATTACH cannot run inside an open transaction. Right after `connect_db` none is open. Every `ensure_*` uses `executescript`, which commits first, so placing the ATTACH after line 339 is also safe.
- `ensure_moderation_schema`, `ensure_interaction_event_schema`, `ensure_channels_indexes` and `ensure_video_indexes` use unqualified `CREATE ... IF NOT EXISTS`. An unqualified CREATE targets main, and the private file holds no tables with those names, so these are unaffected whether the attach comes before or after them.
- `channels.py:46` and `videos.py:11-14` probe `sqlite_master`, which is main only, so they are unaffected.

Other details:
- A `SystemExit` raised before the `try/finally` at 516 leaves the SIGINT/SIGTERM handlers swapped. This is harmless because the process is exiting. `assert_index_matches_embeddings` (line 368) already exits the same way.
- The log line at 494 (`db=%s index=%s total=%d`) is the natural place to also log the override path. This is optional. No test parses that line (`test_server_config.py` parses only `upnext_config` and `ann_nprobe_configured`).
- The new name added to `from data.trending import ensure_trending_schema` (line 110) must exist in `trending.py`. `server.py` is imported in Engine-interpreter children by `tests/active/test_internal_events.py:47` and `tests/active/test_video.py:163,199`, so an `ImportError` there breaks those suites.

**What depends on it:** every unqualified `trending_ranks` read on `server.db` (the handler's ordered feed and the popular layer). `search_db` (line 333, `connect_readonly_db`) and the random-cache worker's own connection (`run_random_cache_worker(db_path, ...)`, line 500) do not read `trending_ranks` (grep for `trending` in `data/search.py` and `data/random_cache.py` finds nothing), so they need no view.

**Regression risk:**
- **Medium for the flagged path:** step order, the transaction state at ATTACH, and the view name colliding with `main.trending_ranks`. SQLite allows a temp object to shadow a main one; I expect that and have not run it.
- **Low for the default path,** provided the unflagged branch stays byte-for-byte as it is. The phase test should check that line 337 still runs when the flag is absent: "without the flag, Trending reads whitelist.db".
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer.__init__ self.db (line 242) and main()'s finally db.close() (line 533)">
**What changes:** nothing.

The plan's claim checks out. `self.db = db` is the only assignment: a grep for `\.db\s*=` under `engine/server` finds only `server.py:242` and an unrelated test double in `db/jobs/tests/test-moderation-integration.py:942`. A per-connection TEMP view and ATTACH therefore last for the life of the process. `db.close()` at 533 releases the attachment along with the connection.

**What depends on it:** every handler that uses `server.db` under `db_lock`. The writers on this connection are ingest (`internal_events.py:66-74`), the video write-back (`video.py:389-432`) and the raw prune (`internal_events.py:111`). They write main tables only, and a transaction that writes only main never needs a lock on the attached file.

**Regression risk:** low. Any write transaction that also read the view holds a SHARED lock on the private file until commit. Nothing else writes that file while the Engine runs, so there is no contention.
</impact>
<impact path="engine/server/data/trending.py" element="ensure_trending_schema (lines 8-25) unchanged, plus a NEW helper next to it (validate PATH with mode=rw and apply the schema; ATTACH + CREATE TEMP VIEW on a connection)">
**What changes:** add one small function, or two. Keep the module's style: `from __future__ import annotations`, `import sqlite3`, a one-line docstring per function, and comments on a single line. One reasonable shape:
- `prepare_trending_override(path)`: the `mode=rw` open plus `ensure_trending_schema`, raising `SystemExit` or returning.
- `attach_trending_override(conn, path)`: `ATTACH DATABASE ? AS <schema>` followed by `CREATE TEMP VIEW trending_ranks AS SELECT * FROM <schema>.trending_ranks`.

A comment at the view should explain the shadowing, as the plan requires. ATTACH accepts a bound parameter for the filename, so the path needs no quoting.

On a non-URI connection such as `connect_db`, a plain ATTACH creates a missing file. That is the named race; the `mode=rw` check is what guards against it.

A 0-byte existing file passes validation: SQLite treats it as an empty database, and `ensure_trending_schema` creates the table in it. Trending then serves an empty page rather than failing. This is consistent with "must already exist", but say so in the help text or a test if it matters.

**What depends on it:**
- `ensure_trending_schema` is imported by `engine/server/api/server.py:110`, `engine/server/db/jobs/fetch-trending.py:28` and the tests (`test_random_videos.py:78`, `test_similar.py:101`, `test_moderation.py:29`, `test_popular_videos.py:37`).
- `tests/active/conftest.py:132-134` loads this file by path under the module name `active_trending_schema`.
- The signature of `ensure_trending_schema(conn)` must not change.
- The new helper will be used by `server.main()`, the new in-process tests in `test_random_videos.py`, and possibly the `dataset` fixture (see that entry).

**Regression risk:** low for the existing function, which is untouched. The new helper carries the flattening and plan risk; see `random_videos.py`.
</impact>
<impact path="engine/server/data/db.py" element="connect_db (77-82) and connect_readonly_db (85-94): unchanged, used as precedent">
**What changes:** nothing. The plan rejected adding `uri=True` to `connect_db`.

Points relevant to the build:
- `connect_db` calls `sqlite3.connect(path.as_posix(), check_same_thread=False)` without `uri=True`. ATTACH on it therefore takes a plain filename, and a `file:...?mode=rw` URI string would be treated as a literal filename.
- `connect_readonly_db` is the URI precedent (`f"file:{path.as_posix()}?mode=ro"`, `uri=True`). Validation should use the same form with `mode=rw`.
- A path containing `?` or `#` would need URI escaping in the validation open. This is a minor edge case that the fixture's temp path does not hit.
- The deadline progress handler (`install_deadline_handler`) is per connection, so statements reading the attached file are bounded by `statement_deadline` exactly as before.

**What depends on it:** every Engine connection.

**Regression risk:** none if left untouched.
</impact>
<impact path="engine/server/data/random_videos.py" element="ORDERED_FEED_SOURCE['trending'] (36-42), ORDERED_FEED_ORDER_BY['trending'] (16-22), fetch_ordered_page (241-334), fetch_popular_videos (234-238): unchanged, resolved through the view">
**What changes:** no edit. With the flag set, `trending_ranks t CROSS JOIN video_embeddings e ON ...` resolves `trending_ranks` to the TEMP view, because name lookup goes temp, then main, then attached. `t.rank`, `t.likes`, `t.views`, `t.video_id` and `t.instance_domain` in the ORDER BY are view columns, since the view is `SELECT *`.

The expected flattened plan is `SCAN t USING INDEX idx_trending_ranks_order` (now on the attached schema) with no `USE TEMP B-TREE FOR ORDER BY`. That is an expectation only: SQLite 3.53.4 ships in the engine pixi env (`engine/.pixi/envs/default/lib/libsqlite3.so.3.53.4`), and I could not run EXPLAIN QUERY PLAN to confirm it. The pytest interpreter's sqlite version may differ from the Engine's, which matters if the plan test runs in-process under pytest rather than under `ENGINE_PY`. The existing plan test (`test_random_videos.py:222-240`) runs in-process.

**What depends on it:**
- `handlers/similar.py:777-784` (`_handle_ordered_feed`, using `self.server.db` under `db_lock`).
- `recommendations/builder.py:114-116` (`fetch_popular_videos_filtered`) → `candidates/popular_videos.py:53` (`server.db` under `db_lock`).
- `tests/active/test_similar.py:764` (`_reference`, run on `dataset`; see the HIGH entry).
- `test_random_videos.py` (33 uses).
- `test_popular_videos.py`.
- `test_video.py:220` (deps wiring).

**Regression risk:**
- Default path: none, since the SQL is untouched.
- Flagged path: medium. If flattening does not happen, the order is still correct but the plan gains a scan or sort. The 5 s statement deadline (`DEPLOYMENT.md:453`) could then bite on deep pages with a full 88k-row seed.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_ordered_feed (759-806) and FEED_MODES/ORDERED_FEED_MODES (105-107)">
**What changes:** nothing. It reads `self.server.db`, which is the connection that carries the view, under `db_lock`, then applies serving moderation.

**What depends on it:**
- `test_similar.py:819` (`test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order...[trending]`).
- The NSFW listing test (`test_similar.py:1043`, `mode=trending`).
- The child-process handler test (`test_similar.py:961`), which uses its own temp DB.

**Regression risk:** none in the code. The test-side risk is covered in the `test_similar.py` entries.
</impact>
<impact path="engine/server/api/recommendations/candidates/popular_videos.py" element="PopularVideosGenerator.get_candidates line 53 (fetch_popular_videos(server.db, ...)); and engine/server/api/recommendations/builder.py fetch_popular_videos_filtered (114-116)">
**What changes:** nothing. The plan states that no signature changes. The pool read goes through `server.db`, so it is covered by the view.

**What depends on it:**
- The Recommendations mix's popular layer.
- `test_popular_videos.py`, which runs a child on a temp DB and is unaffected.

**Regression risk:** none.
</impact>
<impact path="engine/server/api/recommendations/builder.py" element="RecommendationBuilderDeps.fetch_popular_videos (line 60) and fetch_popular_videos_filtered (114-116)">
**What changes:** nothing. It is listed because the plan's rejected alternative would have threaded a schema argument through here. Under the chosen approach the deps and settings stay identical, and `test_video.py:220` builds `RecommendationBuilderDeps` by keyword and would break on any added required field.

**Regression risk:** none.
</impact>
<impact path="engine/server/data/moderation.py" element="_host_table_column_pairs (308-319), purge_host_data (194-), _count_host_rows (322-338), _table_exists (415-421)">
**What changes:** nothing. This is out of scope per the issue.

I verified the plan's claim:
- `purge_host_data` callers are `instance-denylist-cli.py:190,222,227`, `updater-worker.py:619,642` and `db/jobs/tests/test-moderation-integration.py:874,907,1022`.
- The test callers are `test_moderation.py` and `test_ann.py`.
- None is in `engine/server/api`.

With the flag set, the Engine therefore has no write path to the shared `trending_ranks`.

`_table_exists` queries `sqlite_master`, which covers main only and never sees the TEMP view. If a purge were ever run on a flagged connection, it would count and delete the shared `main.trending_ranks`, not the private file. That is a latent trap, but it is unreachable today.

**Regression risk:** none.
</impact>
<impact path="engine/server/db/jobs/fetch-trending.py" element="run() calling ensure_trending_schema (line 102); writes to trending_ranks (117-119)">
**What changes:** nothing. It is out of scope per the issue. It depends on `ensure_trending_schema(conn)` keeping its signature and behaviour.

**Regression risk:** none, as long as `trending.py`'s existing function is untouched. `tests/active/test_fetch_trending.py` gates it.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="trending stage (1431-1469) and purge_host_data callers (619, 642)">
**What changes:** nothing. It keeps writing the shared `trending_ranks` on the operator's schedule.

**What depends on it:** the new fingerprint gate. An updater run during a suite run changes the shared fingerprint and turns the in-suite gate red without the suite being at fault. The plan names this; the failure message should say so.

**Regression risk:** none in the code. The test-flake risk is acknowledged.
</impact>
<impact path="tests/active/conftest.py" element="trending_seed fixture (126-144) and TRENDING_SEED_SQL (107-123)">
**What changes:**
- The fixture becomes `trending_seed(tmp_path_factory)` and returns a path. The seed target is `tmp_path_factory.mktemp(...) / "trending.db"`.
- Open it with `sqlite3.connect(f"file:{path}", uri=True)` or equivalent, so that URI ATTACH works. Then run `trending.ensure_trending_schema(conn)`, `ATTACH DATABASE 'file:<WHITELIST_DB>?mode=ro' AS ...`, and `TRENDING_SEED_SQL` verbatim inside `with conn:`.
- Drop the `DELETE FROM trending_ranks`. The table is fresh, and keeping the delete would be harmless anyway because it resolves to the temp file's main.
- Drop the `ENGINE_START_LOCK` block.

`TRENDING_SEED_SQL` stays unchanged. Its unqualified `trending_ranks` resolves to the temp file's main (main before attached), and `videos` and `video_embeddings` exist only in the attached shared DB. The comment on line 107 ("every lane writes the same rows") should be reworded, because each lane now writes its own file.

The fixture keeps loading `trending.py` by file spec (lines 132-134). If the new helper is reused here, for example for the `dataset` fix, it is available on the same module object.

**What depends on it:** the `engine` fixture (line 148) and, if the HIGH `dataset` fix is taken, the `dataset` fixture.

**Regression risk:** medium.
- **Same rows:** the rows must match today's exactly (ranks, likes, views, `fetched_at = 0`) for `test_similar`'s NSFW control. `TRENDING_SEED_SQL` is unchanged, but the ROW_NUMBER tie order is defined by `views DESC, likes DESC, video_id DESC`, which is deterministic, so this should hold.
- **URI handling:** if the seed connection is not opened with `uri=True`, `ATTACH 'file:...?mode=ro'` silently creates a file literally named `file:...` in the CWD instead of opening the shared DB read-only. The seed would then fail with "no such table: videos". That is loud, not silent.
- **Lock:** the seed now holds a SHARED lock on the shared file for a few seconds, which the plan names as a risk.
</impact>
<impact path="tests/active/conftest.py" element="engine fixture (147-186)">
**What changes:**
- Add `"--trending-db", str(trending_seed)` next to `"--no-random-cache-refresh"` in the Popen argv (lines 162-163). It needs an absolute path, which `tmp_path_factory` provides.
- Keep the `ENGINE_START_LOCK` loop.
- Update the comment at 155-156 if it should mention the override.

**What depends on it:** every session-Engine test (`engine_client`, `unpublished_client`, `test_similar`, `test_server_config.py:270`, `test_random_cache`, profiles and so on).

A start that fails validation is retried 5 times by the loop (lines 159-179), each retry sleeping `1 + attempt` seconds, before `assert proc.poll() is None` fails. A seed bug would therefore show up as "Engine exited on every start" after about 15 s, with the cause in `engine.log`.

**Regression risk:** medium, because every Engine-backed test depends on this start succeeding.
</impact>
<impact path="tests/active/conftest.py" element="module docstring (lines 1-14), ENGINE_START_LOCK constant (104-106), imports fcntl/tempfile (17, 25)">
**What changes:** rewrite docstring lines 6-11. "after `trending_seed` has rewritten that dataset's `trending_ranks`" becomes a description of the private per-session seed and the `--trending-db` flag. If the `dataset` fixture changes, its description must change as well.

`ENGINE_START_LOCK` stays. Its importers are:
- `tests/active/test_random_cache.py:44` (used at 297).
- `tests/active/test_server_config.py:39` (used at 254).
- `tests/archive/short_similarity_cache/test_similar.py:129` (skipped).
- `conftest`'s own `engine` fixture.

`fcntl` and `tempfile` stay in use (the engine fixture and `ENGINE_START_LOCK`).

**Regression risk:** low. These are text-only changes, and `ImportError`s are avoided by keeping the constant.
</impact>
<impact path="tests/active/conftest.py" element="dataset fixture (228-233): HIGH, the plan's claim that no session test reads trending_ranks through dataset is wrong">
**What changes:** the plan says nothing changes here. In fact `tests/active/test_similar.py:759-766` `_reference(dataset, order, threshold)` calls `fetch_ordered_page(dataset, order, REFERENCE_DEPTH, 0, ...)`. For `order == "trending"`, that reads `trending_ranks` from the shared `whitelist.db` through `dataset`.

Today this agrees with the Engine because both read the seeded shared table. After the change, the Engine serves the private seed while `dataset` reads the operator's real fill (86,826 rows with `fetched_at > 0` per the triage). The assertion `first + following + last == reference[: 3 * FEED_PAGE]` (`test_similar.py:849`) therefore fails for the `trending` parametrization. That breaks the acceptance criterion "the active suite passes ... with no test expectations changed".

Options, which the build has to choose between:
- **(a)** Make `dataset` depend on `trending_seed` and, after opening it `mode=ro` (a URI connection, so URI ATTACH works), apply the same ATTACH + TEMP VIEW helper to the private file. The expectation is unchanged and `_reference` is untouched. The cost: every test that uses `dataset` now triggers the seed, which is session-scoped and a few seconds, once per lane. I believe a TEMP view can be created on a `mode=ro` connection because the temp schema stays writable, but I have not verified it. Attaching with `mode=ro` keeps the private file read-only there too.
- **(b)** A separate session fixture, for example `trending_dataset`, prepared that way and used only by `_reference` for `trending`. This changes test code but not expected values.

`dataset` is used by test_blocks, test_dislike_profile, test_dislikes, test_frontend_* , test_profiles, test_random_cache, test_server and test_similar. With (a), the shared file gets one more read-only reader holding the seed's SHARED lock window. The plan's in-suite "pages equal merged-rank order computed from the temp file joined with the read-only dataset" test needs exactly this prepared connection, so the helper is needed in the tests either way.

**Regression risk:** high. Without action, `test_similar.py::test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` goes red whenever the shared table differs from the seed, which is always once a real fill exists.
</impact>
<impact path="tests/active/test_similar.py" element="_reference (759-766), test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated (818-849) for order=trending, module docstring line 64">
**What changes:** depends on the `dataset` decision above. With option (a), nothing in this file changes. The docstring line 64 says "read through the read-only `dataset` connection", which stays true, though it should perhaps mention that `dataset` carries the private Trending ranks. With option (b), `_reference` picks the prepared connection for `trending`, and docstring line 64 must say so.

The re-read control at line 836 (`_reference(...) == reference`) still holds with either option, because the private file is static for the session. With the unfixed shared read it would also hold, but an updater run mid-test would break it.

**What depends on it:** the `trending` parametrization of `ORDERED`, read from `handlers.similar.ORDERED_FEED_MODES` at collection (`test_similar.py:743-746`).

**Regression risk:** high if missed (see above).
</impact>
<impact path="tests/active/test_similar.py" element="NSFW listing control for mode=trending (comment 997-999, test 1043) and nsfw_flagged (1009)">
**What changes:** nothing. The comment at 998 says the control "was rehearsed with exactly one flagged row in the first 96 seeded Trending rows; the seed is derived from the live whitelist.db". The private seed is built by the same SQL from the same live catalogue, so the Engine serves the same rows. `nsfw_flagged` reads `videos.nsfw` through `dataset`, not `trending_ranks`.

**What depends on it:** the seed producing identical rows.

**Regression risk:** low. The existing seed-drift caveat is unchanged, as the plan says.
</impact>
<impact path="tests/active/test_similar.py" element="_ranks_db / _TRENDING_HANDLER_CHILD / test_the_handler_serves_trending_until_the_ranked_rows_run_out... (852-990)">
**What changes:** nothing. It runs `SimilarHandler` on a stub server over its own temp DB in an Engine-interpreter child, without the `engine` fixture and without the flag.

**Regression risk:** none.
</impact>
<impact path="tests/active/test_random_videos.py" element="test_a_trending_page_walks_the_ranks_index_without_sorting (222-240), _plan/_Recorder (198-219), _schema (119-128), imports (74-78); NEW flagged-plan and flag-on/flag-off in-process tests">
**What changes:**
- The plan adds an `EXPLAIN QUERY PLAN` test on a helper-prepared connection, beside the existing unflagged one. It also adds an in-process test: main DB with ranks A, private file with ranks B; `fetch_ordered_page` and `fetch_popular_videos` serve A on a plain connection and B on a prepared one; main's ranks are unchanged afterwards.
- `_plan` can be reused as is. It records the SQL via `_Recorder` and runs `EXPLAIN QUERY PLAN` on the same connection, so the view is in scope.
- The prepared connection's main must hold `videos`, `video_embeddings`, `channels` and `trending_ranks` (`_schema` already builds all of them). The private file needs `ensure_trending_schema` and rows.
- The module docstring (lines 1-54) lists every claim, so new tests need new docstring bullets in the same style.
- The import at line 78 grows the new helper name.

**What depends on it:** `tests/config.json` group `test_random_videos.py` already maps `engine/server/data/trending.py`.

**Regression risk:** low for the existing tests, which are unchanged. The new plan assertion's index-name check (`"idx_trending_ranks_order" in detail`) should still match an attached-schema index. That is unverified.
</impact>
<impact path="tests/active/test_server_config.py" element="subprocess Engine driving pattern (_run 47-52, VARIANT_RUNNER 204-217, _start_variant 252-267), ENGINE_START_LOCK import (39); likely home of the missing-path/non-SQLite subprocess test">
**What changes:** the plan's missing-path test copies this file's pattern: `subprocess.run([str(ENGINE_PY), str(ENGINE_SERVER), "--trending-db", missing, ...], capture_output=True, ...)`. It asserts a non-zero return code, the path in stderr, and no file at the path. It also covers a non-SQLite file. No start lock is needed, because validation runs before `connect_db` and binding.

The process still imports `server_config` and initialises logging before validation. A missing `ENGINE_PY` should be handled the way the other tests here handle it.

`_start_variant` (254-258) starts an unflagged Engine on the shared DB. That is out of scope per the plan, but it means `ensure_trending_schema(db)` runs on shared `whitelist.db` during the suite. `CREATE ... IF NOT EXISTS` on an existing table writes nothing, so the fingerprint is unaffected.

**What depends on it:** the `--help` control at 80-82.

**Regression risk:** low.
</impact>
<impact path="tests/active/test_random_cache.py" element="ENGINE_START_LOCK import (44), _cache_variant (286-323), concurrent unflagged starts (796-811)">
**What changes:** nothing. These keep importing `ENGINE_START_LOCK` and start Engines without `--trending-db` on the shared DB. That is out of scope per the plan. Like any unflagged start, they run `ensure_trending_schema(db)` on shared, which is a no-op when the table exists and leaves the fingerprint unchanged.

**Regression risk:** none, provided the constant is kept in conftest.
</impact>
<impact path="tests/archive/short_similarity_cache/test_similar.py" element="imports ENGINE_START_LOCK etc. from conftest (docstring line 3, use at 129)">
**What changes:** nothing. It is skipped, but its docstring says it depends on conftest's `ENGINE_START_LOCK`. Keeping the constant keeps it importable.

**Regression risk:** none.
</impact>
<impact path="tests/active/test_moderation.py" element="ensure_trending_schema import (29) and use (105)">
**What changes:** nothing. It depends on `ensure_trending_schema(conn)` being unchanged.

**Regression risk:** none.
</impact>
<impact path="tests/active/test_fetch_trending.py" element="trending_ranks schema check (251-259), job tests">
**What changes:** nothing. It depends on `ensure_trending_schema` behaviour. Its missing-`--db` subprocess test (251) is the precedent for the new missing `--trending-db` test (exit non-zero, no file created).

**Regression risk:** none.
</impact>
<impact path="tests/active/test_popular_videos.py" element="ensure_trending_schema import (37), child-process mix over temp DB (195-255)">
**What changes:** nothing. Its temp DB holds `trending_ranks` in main, and no flag is involved.

**Regression risk:** none.
</impact>
<impact path="tests/active/test_internal_events.py" element="Engine-interpreter child that does `import server` (line 47) and builds SimilarServer">
**What changes:** nothing directly. However, it imports `engine/server/api/server.py` at module level, so a broken new import line (for example, a helper name that does not exist in `data/trending.py`) fails this suite. It does not call `main()` or `parse_args`, so the flag logic itself is not exercised.

**Regression risk:** low.
</impact>
<impact path="tests/active/test_video.py" element="Engine-interpreter children that `import server` (163, 199) and build RecommendationBuilderDeps (220)">
**What changes:** nothing. As with `test_internal_events.py`, this imports `server.py`, so the module-level imports must resolve. Line 220 constructs `RecommendationBuilderDeps` by keyword, which confirms the plan's choice not to add fields there.

**Regression risk:** low.
</impact>
<impact path="tests/active (NEW fingerprint gate: session fixture + in-suite test; location TBD, conftest.py plus test_similar.py or a new file)">
**What changes:** add a session fixture that reads the shared `trending_ranks` fingerprint read-only before `trending_seed` and `engine` run: `COUNT(*)`, `MIN(fetched_at)`, `MAX(fetched_at)` and the count with `fetched_at > 0`, read via a `file:...?mode=ro` URI, as `dataset` does.

To guarantee it runs before the seed, `trending_seed` or `engine` should depend on it. Pytest instantiates fixtures in dependency order, but with no dependency two independent session fixtures may run in either order.

The in-suite test requests `mode=trending` pages and a popular-layer request from the session Engine, then compares them to the merged-rank order computed from the temp file joined with `dataset` under the NSFW filter. It needs the same prepared connection as the HIGH `dataset` entry, then re-reads the fingerprint. Its failure message must name the external-updater possibility.

A popular-layer request shows its source only with `debug=1`; the session Engine runs `RECOMMENDATIONS_DEBUG=1`. Check how the popular rows can be identified, for example from debug layer tags in the response. I did not verify the debug payload shape.

**What depends on it:** `trending_seed`, `engine`, `dataset`.

**Regression risk:** medium: a flaky external-change failure, and fixture ordering.
</impact>
<impact path="tests/config.json" element="test_groups (14-...)">
**What changes:** if a new test file is created, for example for the flag subprocess test or the fingerprint gate, add a `test_groups` entry mapping it to `engine/server/api/server.py` and `engine/server/data/trending.py`. If the tests land in existing files, consider adding `engine/server/data/trending.py` to `test_server_config.py`'s group (130-133), which today lists only `server_config.py` and `server.py`. `test_random_videos.py` (112-118) and `test_similar.py` (54-71) already map `trending.py`. `conftest.py` is mapped nowhere.

**Regression risk:** low. This is metadata for the test runner and validator.
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="referenced by conftest docstring line 7 as how the Engine is started">
**What changes:** nothing. The conftest docstring says the engine fixture starts the Engine "the way `tests/run-arch-split-smoke.sh` does". After the change the fixture also passes `--trending-db`, so that comparison should be qualified in the docstring rewrite. The script itself (no `trending` match) is untouched.

**Regression risk:** none.
</impact>
<impact path="scripts/run-services.sh" element="ENGINE_SCRIPT launch (35) and process matching (205, 234)">
**What changes:** nothing. The flag is not passed, and the dev Engine on :7070 keeps reading the shared `trending_ranks`, which is the point of the fix.

**Regression risk:** none.
</impact>


### docs_checklist

<doc path="engine/server/README.md">
Optional, uncertain whether wanted. Line 26 says "Trending serves only videos ranked in `trending_ranks`". The plan documents the flag only in `--help`, because the README lists no Engine flags; I confirmed it has none. If one sentence is wanted, it would read: "a dev/test `--trending-db PATH` makes the Engine read `trending_ranks` from PATH instead (see `--help`)". Otherwise there is no change.
</doc>
<doc path="engine/server/db/jobs/docs/UPDATER_WORKER.md">
Line 101 ("**First fill.** `trending_ranks` is created empty when the Engine starts") stays true for every production start. With `--trending-db` the Engine applies the schema to PATH, not to `whitelist.db`. This is a dev/test nuance, so a change is optional. I am flagging it only so the doc step can make a deliberate choice.
</doc>
<doc path="docs/project/issues/44-trending-seed-write-lock-during-test-runs.md">
On delivery, set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md` and `issue-tracker.md`. Tick the acceptance criteria and record the named limitation: the validation-to-ATTACH race can create an empty file.
</doc>
<doc path="tests/active/conftest.py">
Module docstring lines 6-11: describe the per-session private seed file and `--trending-db` instead of "`trending_seed` has rewritten that dataset's `trending_ranks`", and update the `dataset` description if that fixture gains the private view. Also update the `trending_seed` docstring (128-130, which today cites the "operator decision (issue 38 build)" and the start lock), the `engine` fixture comment, and the comment at line 107 ("every lane writes the same rows").
</doc>
<doc path="tests/active/test_similar.py">
Docstring line 64 says the ordered-feed reference is "read through the read-only `dataset` connection". Update it if the trending reference moves to a prepared connection, which is option (b). Under option (a), consider noting that `dataset` carries the session's private Trending ranks.
</doc>
<doc path="tests/active/test_random_videos.py">
Module docstring (lines 1-54): add bullets for the new flagged `EXPLAIN QUERY PLAN` test and the flag-on/flag-off in-process test, in the existing claim style.
</doc>


### highest_risk

tests/active/conftest.py `dataset` fixture together with tests/active/test_similar.py `_reference` (759-766): the plan says no session test reads `trending_ranks` through `dataset`, but `_reference(dataset, "trending", ...)` does. With the Engine on the private seed and the shared DB holding the real fill, `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` fails at line 849 unless `dataset`, or a trending-specific reference connection, gets the same ATTACH + TEMP VIEW.
engine/server/api/server.py main() lines 326-338: the startup order of validate → connect_db → ATTACH/TEMP VIEW → skip `ensure_trending_schema(db)` is where the shared file could still be written (if the skip is wrong) or the view could fail (ATTACH inside a transaction, or a name collision with `main.trending_ranks`). A failure here also breaks every Engine-backed test through the `engine` fixture's 5-retry loop, and the new import line is loaded by the `test_internal_events.py` and `test_video.py` children.
engine/server/data/random_videos.py ORDERED_FEED_SOURCE['trending'] through the new view: correctness does not depend on flattening, but the no-sort plan does, and it is unverified on SQLite 3.53.4 (the Engine env) and possibly a different sqlite under pytest. A non-flattened plan sorts the full seed on each chunk, under the 5 s statement deadline.

## 2026-10-03 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I checked the inventory against the tree. The plan's mechanism holds: one TEMP view on `server.db` covers every Engine read of `trending_ranks`, and none of the paths that need to stay unchanged are touched. There is one real problem, and the inventory already raised it as its HIGH `dataset` entry. The plan says no session test reads `trending_ranks` through `dataset`, and that is wrong. `test_similar.py:764` calls `fetch_ordered_page(dataset, "trending", ...)`, and line 849 compares the Engine's pages to that result. With the plan as written, the Engine would serve the private seed while `dataset` reads the operator's real fill, so the `trending` case of that test fails. That breaks acceptance criterion 5 ("no test expectations changed"). The plan says nothing changes here, so I report it under conflicts and don't treat the fix as already approved.

What I confirmed in the tree:
- **Only one connection reads `trending_ranks`.** It is named only in `random_videos.py:37`; `fetch_ordered_page` is called only from `similar.py:777`, and `fetch_popular_videos` only from `popular_videos.py:53` with `server.db`. `search_db` and the random-cache worker never read it.
- **The connection lives for the whole process.** `self.db = db` (`server.py:242`) is the only assignment. `connect_db` (`db.py:77-82`) is a non-URI connection, as the inventory says.
- **Placement in `main()` is clean.** `connect_db` at line 332 is the first thing that touches `whitelist.db`. `configure_engine_logging` (line 324) logs to a stream only and opens no file, so the missing-path start creates or writes nothing.
- **The Engine API cannot write the shared table.** `purge_host_data` is called only from moderation, the denylist CLI, the updater and the job tests.
- **The README claim holds.** `engine/server/README.md` lists no Engine flags; only `LAYER_PARAMS.md:130` mentions any, in passing.
- **Popular-layer rows can be identified.** Debug rows carry `debug.layer` (`recommendations/debug.py:23`), which settles a point the inventory left unverified.
- **No other session test depends on `trending_ranks`.** `test_frontend_feed_params.py` is bundle and AST only, and `test_updater_worker.py` is source scans and shims.
- **The NSFW control is unaffected.** `nsfw_flagged` (`test_similar.py:1009`) reads only `videos.nsfw`.

<question id="1">
Yes for the Engine half. With the flag set, every unqualified `trending_ranks` on `server.db` (the handler at `similar.py:777` and the popular pool at `popular_videos.py:53`) resolves to the TEMP view, because SQLite looks in temp before main. A temp object may share a name with a main table and may reference an attached schema. Nothing else reads the table.

For the suite half, only partly. The Engine serves the private seed, but `_reference` in `test_similar.py` still reads the shared table through `dataset`. So `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` fails whenever the shared table differs from the seed, which is always once a real fill exists (86,826 rows with `fetched_at > 0` today). It works only once `dataset`, or a connection used in its place for `trending`, also sees the private ranks.

Two parts stay expectations until tests run: that the query flattener inlines the view (the flagged-plan test gates this), and that a TEMP view can be created on the `mode=ro` `dataset` connection.
</question>
<question id="2">
- **Engine:** a dev/test-only flag ships in the production entry point. With the flag set, the Engine writes to the private file at startup (the schema), and `whitelist.db` never gets `ensure_trending_schema`. Default starts are untouched.
- **Accepted limits:** the attach race (validation passes, then the file is deleted, and an empty file is created and served) and the 0-byte-file case (passes validation and serves empty) are named limits, not guarantees.
- **Suite:** the seed no longer writes the shared file. It still holds a SHARED lock on it for the few seconds the INSERT…SELECT reads it.
- **Fixture dependencies:** if `dataset` is fixed as in option (a), every test that uses `dataset` also builds the seed, once per lane, including tests that never start an Engine (for example `test_server.py:253`).
- **Fingerprint gate:** it can go red if the operator's updater runs during the suite.
- **Unflagged Engines** in `test_random_cache.py` and `test_server_config.py` still open the shared DB read-write. `ensure_trending_schema` is a no-op there because the table exists, so the fingerprint is unaffected.
</question>
<question id="3">
- **Fix `dataset`:** the plan's "no session test reads `trending_ranks` through `dataset`" must be corrected. Either `dataset` attaches the private file and shadows `trending_ranks` with the same helper (inventory option (a)), or `_reference` uses such a connection for `trending` (option (b)). Without one of these, criterion 5 fails.
- **Keep the default branch as is:** the existing `ensure_trending_schema(db)` call at `server.py:337` must still run when the flag is absent.
- **Keep `ENGINE_START_LOCK`:** it is imported by `test_random_cache.py:44`, `test_server_config.py:39` and the archived test.
- **Keep the new import in `server.py:110` resolvable:** `test_internal_events.py` and `test_video.py` import `server` in Engine-interpreter children.
- **Keep `ensure_trending_schema(conn)` unchanged:** `fetch-trending.py:28/102` and four test modules depend on its signature and behaviour.
- **Keep `TRENDING_SEED_SQL` verbatim:** the private seed must hold the same rows, because the NSFW control at `test_similar.py:998` depends on them.
</question>
<question id="4">
- **Without the flag:** nothing changes. Same SQL, same startup order, same schema call.
- **With the flag:** Trending and the popular layer read ranks from PATH. PATH gets the schema at startup. The Engine refuses to start (non-zero exit, path named on stderr) on a missing or non-SQLite PATH, and never creates `trending_ranks` in `whitelist.db`.
- **In the suite:** `trending_seed` returns a path instead of writing the shared DB. The `engine` fixture passes `--trending-db`. With option (a), `dataset` also carries the private ranks: for every query except `trending_ranks` it is the same read-only `whitelist.db` connection. The seed no longer takes the start lock.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: Settled plan, Active suite section ("No session test reads `trending_ranks` through `dataset`. They only observe the Engine, so `test_similar.py`'s Trending ... expectations still hold") vs the tree and the settled requirement "The active suite passes, including the Trending and popular-layer tests in `test_similar`, with no test expectations changed": `tests/active/test_similar.py:759-766` `_reference` calls `fetch_ordered_page(dataset, order, ...)`, which for `order == "trending"` reads the shared `whitelist.db` `trending_ranks` through the `dataset` fixture (`tests/active/conftest.py:228-233`), and line 849 asserts the Engine's pages equal it. Under the plan as written, the `[trending]` case fails whenever the shared table holds a real fill. The plan must add a change to `dataset` (option (a)) or to `_reference` (option (b)). It currently says neither changes. The inventory already carries this as an impact; it is reported here because it contradicts a statement in the settled plan.

Recommendations: 1. **Amend the plan to take option (a):** `dataset` depends on `trending_seed`, opens `mode=ro` as today, and calls the same attach-and-view helper the Engine uses (`attach_trending_override(conn, path)` in `data/trending.py`, loaded through the `active_trending_schema` module conftest already builds). `_reference`, `test_similar.py` and every expected value stay untouched. The plan's own fingerprint gate needs this connection anyway ("merged-rank order computed from the temp file joined with the read-only dataset"), so one prepared connection serves both. Cost: every test that uses `dataset` triggers the session seed (a few seconds, once per lane), including tests with no Engine. The conftest docstring must say `dataset` carries the private ranks. The ro-connection TEMP view must be shown to work; a one-line control in the fingerprint test covers it. Option (b) instead costs a test-code change to `_reference` and to the docstring at `test_similar.py:64`, and leaves `dataset` and its other users alone. Choose (b) if you want `dataset` to stay the shared file exactly as it is.

2. **Run the flagged-plan check in an Engine-interpreter child as well:** the plan's `EXPLAIN QUERY PLAN` test is in-process under pytest's interpreter, whose SQLite may differ from the Engine's 3.53.4 (pytest's interpreter lacks numpy, per `test_server_config.py:79`). The flattening risk matters only in the Engine. `test_similar.py` already has the child-process pattern (`_FEED_CONSTANTS_CHILD`, `_TRENDING_HANDLER_CHILD`). Cost: one subprocess test of about a second. Skipping it leaves the Engine's actual plan with the flag set unverified.

3. **Identify popular-layer rows with `debug.layer`** (`recommendations/debug.py:23`) on a `debug=1` request, since the session Engine runs `RECOMMENDATIONS_DEBUG=1`. Cost: none. This settles the inventory's open question.

4. **Name the 0-byte-file case in the `--trending-db` help text** next to "must already exist", or reject it in validation by checking that the table already exists before the schema runs. The help text costs one line. Rejecting costs a slightly larger helper, and the seed fixture must then create the table first, which it already does.

## 2026-10-03 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Module map

| File | Change |
|---|---|
| `engine/server/data/trending.py` | Two new functions next to the unchanged `ensure_trending_schema`: `prepare_trending_override(path)` and `attach_trending_override(conn, path)`, plus one constant. |
| `engine/server/api/server.py` | One new argument in `parse_args`. In `main()`: validate before `connect_db`, then either the unchanged `ensure_trending_schema(db)` or the attach. One conditional log line. The import line grows by two names. |
| `tests/active/conftest.py` | `trending` is loaded once at module level. New fingerprint helper and fixture. `trending_seed` writes a private temp file. `engine` passes the flag. `dataset` carries the private view (option (a) from the HIGH impact entry). Docstrings rewritten. |
| `tests/active/test_random_videos.py` | New tests: the plan with the flag set, and flag on vs flag off in-process. Docstring bullets for both. |
| `tests/active/test_server_config.py` | New subprocess test: `--trending-db` on a missing path or a non-SQLite file. `--help` control. |
| `tests/active/test_similar.py` | New in-suite gate: the session Engine serves the private ranks (Trending pages and the popular layer), and the shared fingerprint is unchanged. Docstring line 64 updated. |
| `tests/config.json` | Add `engine/server/data/trending.py` to the `test_server_config.py` group. |

Nothing else changes. That includes `random_videos.py` and its SQL, `similar.py`, `popular_videos.py`, `builder.py`, `db.py` (`connect_db` stays non-URI), `moderation.py` and `fetch-trending.py`. `engine/server/README.md` gets no edit because it lists no Engine flags, so `--help` is the documentation. That was the plan's call and I kept it.

## Ladder, per piece

- **Shadowing `trending_ranks`:** a native platform feature is enough (rung 4). A SQLite `ATTACH` plus a `TEMP VIEW` on the existing connection means no SQL and no signature changes.
- **No-create validation:** stdlib `sqlite3` with a `mode=rw` URI (rung 3). It mirrors the `mode=ro` precedent in `connect_readonly_db`.
- **Schema on the private file:** reuses `ensure_trending_schema` (rung 2).
- **Seed:** reuses `TRENDING_SEED_SQL` unchanged and attaches the shared DB read-only (rung 2 plus rung 4).
- **Test reference for Trending:** reuses `attach_trending_override` on `dataset` (rung 2). `_reference` and every expectation stay as they are.
- **CLI:** argparse, in the file's existing `help=(...)` style.

## `engine/server/data/trending.py` (additions)

```python
import sqlite3  # already imported

# The schema name the --trending-db file is attached under.
TRENDING_OVERRIDE_SCHEMA = "trending_override"


def prepare_trending_override(path: str) -> None:
    """Check that an existing SQLite file is at `path` and apply the trending schema to it, exiting with a message naming the path otherwise."""
    # mode=rw never creates the file, as connect_readonly_db's mode=ro does not; a file that is not SQLite fails on the schema statement.
    try:
        conn = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
        try:
            ensure_trending_schema(conn)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise SystemExit(f"trending ranks file {path} cannot be opened as SQLite: {exc}") from exc


def attach_trending_override(conn: sqlite3.Connection, path: str) -> None:
    """Make every unqualified trending_ranks read on `conn` read the table in the file at `path`."""
    conn.execute(f"ATTACH DATABASE ? AS {TRENDING_OVERRIDE_SCHEMA}", (str(path),))
    # Names resolve temp, then main, then attached, so a bare ATTACH leaves main.trending_ranks in front; this TEMP view shadows it, and SQLite flattens it so the Trending page still walks idx_trending_ranks_order.
    conn.execute(f"CREATE TEMP VIEW trending_ranks AS SELECT * FROM {TRENDING_OVERRIDE_SCHEMA}.trending_ranks")
```

**Invariants:**
- `ensure_trending_schema(conn)` is byte-for-byte unchanged. `fetch-trending.py`, `server.py` and four test files depend on it.
- `prepare_trending_override` never creates a file and never touches `whitelist.db`. On any `sqlite3.Error` it raises `SystemExit(str)`. Python prints that message to stderr and exits with status 1, and the message contains `path` verbatim.
- A 0-byte existing file passes validation and gets the table, so Trending serves empty. The help text says so: "an empty file counts".
- `attach_trending_override` must be called outside a transaction, because ATTACH fails inside one. Its two callers both call it on a connection that has no open transaction:
  - `server.main()`, right after the `executescript`-based ensures, which commit first;
  - the `dataset` fixture, on a fresh connection.
- It works on a `mode=ro` URI connection. The attached file inherits the connection's read-only open flags, and the temp schema is opened read-write regardless (SQLite opens the temp DB with its own READWRITE|CREATE flags). I reasoned this from SQLite's behaviour and have not run it. The `dataset` fixture fails loudly if it is wrong.
- The `path` given to ATTACH is a bound parameter, so it needs no quoting. On a non-URI connection a plain path is taken literally. On a URI connection a plain path that does not begin with `file:` is also taken literally.
- **Named ceiling: URI escaping.** A PATH containing `?` or `#` is not URI-escaped in the validation open, so it fails validation (loudly) instead of opening. That is the same ceiling as `connect_readonly_db`. The way up is `urllib.parse.quote` on the path.

## `engine/server/api/server.py`

Import at line 110:

```python
from data.trending import attach_trending_override, ensure_trending_schema, prepare_trending_override
```

In `parse_args`, after the `refresh_group` block and before `parser.set_defaults(random_cache_refresh=None)`:

```python
    parser.add_argument(
        "--trending-db",
        metavar="PATH",
        default=None,
        help=(
            "Dev/test override: read only the trending_ranks table from PATH; every other "
            "table still comes from whitelist.db. PATH must be an existing SQLite file (an "
            "empty file counts) and is never created; the table and its index are created "
            "in it if missing. A relative PATH resolves against the working directory."
        ),
    )
```

With `metavar="PATH"`, `--help` renders `--trending-db PATH`, and the test asserts that string.

In `main()`, lines 332-339 become:

```python
    if args.trending_db is not None:
        # Before whitelist.db is opened, so a bad path stops the start without touching it or loading the index.
        prepare_trending_override(args.trending_db)
    db = connect_db(db_path)
    search_db = connect_readonly_db(db_path)
    ensure_moderation_schema(db)
    ensure_interaction_event_schema(db)
    if args.trending_db is None:
        # Created empty before the first fill, so a Trending read is an empty page, never "no such table".
        ensure_trending_schema(db)
    else:
        # The shared trending_ranks is neither created nor read on this connection; the file at PATH stands in for it.
        attach_trending_override(db, args.trending_db)
    ensure_channels_indexes(db)
    ensure_video_indexes(db)
```

After the `db=%s index=%s` log line (494), add:

```python
    if args.trending_db is not None:
        logging.info("[similar-server] trending_db=%s (trending_ranks only)", args.trending_db)
```

**Why this order:**
- Validation runs before `connect_db`, so a bad path exits in under a second. Nothing has opened `whitelist.db` at that point and FAISS has not loaded.
- The attach goes after the two `executescript` ensures, so no transaction is open.
- The later `ensure_channels_indexes` and `ensure_video_indexes` create unqualified indexes on main tables and probe `sqlite_master`, which is main-only. The private file holds neither table, so they are unaffected.
- `search_db` and the random-cache worker's own connection read no `trending_ranks`, so they get no view.
- `server.db` is assigned once (`SimilarServer.__init__:242`), so the view lasts as long as the process.

**Default path:** the unflagged branch runs the same statements in the same order as today. The only differences are the `if`, which is not taken, and the second `if`, whose true branch is the original line 337. The SQL and the plans are unchanged.

## `tests/active/conftest.py`

Module level, replacing the lazy spec load inside `trending_seed`:

```python
_TRENDING_SPEC = importlib.util.spec_from_file_location("active_trending_schema", ROOT / "engine" / "server" / "data" / "trending.py")
TRENDING = importlib.util.module_from_spec(_TRENDING_SPEC)
_TRENDING_SPEC.loader.exec_module(TRENDING)
# The shared trending_ranks fingerprint: rows, fetched_at bounds and real-fill rows; main. so a connection carrying the private view still reads the shared table.
TRENDING_FINGERPRINT_SQL = "SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at), COUNT(CASE WHEN fetched_at > 0 THEN 1 END) FROM main.trending_ranks"


def shared_trending_fingerprint() -> tuple:
    """The shared whitelist.db trending_ranks fingerprint, read on a fresh read-only connection."""
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    try:
        return tuple(conn.execute(TRENDING_FINGERPRINT_SQL).fetchone())
    finally:
        conn.close()


@pytest.fixture(scope="session")
def shared_trending_before():
    """The shared fingerprint before the private seed is built and the session Engine starts."""
    return shared_trending_fingerprint()
```

The comment above `TRENDING_SEED_SQL` (line 107) changes its ending to: "...deterministic, so every lane's private file holds the same rows." `TRENDING_SEED_SQL` itself is unchanged.

```python
@pytest.fixture(scope="session")
def trending_seed(tmp_path_factory, shared_trending_before):
    """A per-session private trending_ranks file the session Engine reads through --trending-db, so its Trending order has rows without the network fetch and the shared whitelist.db is never written.

    The catalogue is read from whitelist.db attached read-only; the only file written is this one.
    """
    path = tmp_path_factory.mktemp("trending") / "trending.db"
    # A URI connection, so the shared DB attaches with mode=ro rather than as a literal filename.
    conn = sqlite3.connect(f"file:{path}", uri=True)
    try:
        TRENDING.ensure_trending_schema(conn)
        conn.execute("ATTACH DATABASE ? AS shared", (f"file:{WHITELIST_DB}?mode=ro",))
        # trending_ranks resolves to this file's main, ahead of the attached copy; videos and video_embeddings exist only in the shared DB.
        with conn:
            conn.execute(TRENDING_SEED_SQL)
    finally:
        conn.close()
    return path
```

`shared_trending_before` appears as a parameter only to order the fixtures: pytest then reads the fingerprint before the seed and the Engine.

`engine` fixture: the argv becomes

```python
                    [str(ENGINE_PY), str(ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port),
                     "--no-random-cache-refresh", "--trending-db", str(trending_seed)],
```

`ENGINE_START_LOCK` and the retry loop stay. Comment line 156 gains: "Trending is read from the private seed file (--trending-db), never the shared table."

`dataset` fixture:

```python
@pytest.fixture(scope="session")
def dataset(trending_seed):
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # Trending reads the session Engine's private ranks here too, so a reference order computed on this connection is the one the Engine serves.
    TRENDING.attach_trending_override(conn, trending_seed)
    yield conn
    conn.close()
```

**Module docstring, lines 6-11, rewritten:** `engine` starts the real Engine from its pixi env on the repo's dataset, once per session, the way `tests/run-arch-split-smoke.sh` does but with `--trending-db` naming `trending_seed`'s per-session private file, so the suite never writes the shared `trending_ranks`. `engine_client` and `unpublished_client` are as before. `dataset` is `whitelist.db` opened read-only with that private file attached and shadowing `trending_ranks`, so it is the independent source of a video's channel, account and embedding, and of the Trending order the session Engine serves. `shared_trending_fingerprint` reads the shared table's fingerprint.

**Kept:** the `ENGINE_START_LOCK` constant, which three importers use, and the `fcntl` and `tempfile` imports, which are still used.

## Tests: what each one gates

**1. `test_random_videos.py` (in-process, pytest interpreter).** It imports `attach_trending_override` and `prepare_trending_override` from `data.trending`.

- **`test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`**
  - Setup: `_schema(main.db)` gets the same 30×100 ranked catalogue plus 1,000 unranked rows as the existing plan test, built by a shared local builder factored from that test. Its `main.trending_ranks` is left empty. The ranks are written into `private.db` after `prepare_trending_override`. `attach_trending_override(conn, private)`.
  - Assertions: `_plan(conn, "trending")` contains `idx_trending_ranks_order` and no `TEMP B-TREE`. The control is that `_plan(conn, "popular")` contains `TEMP B-TREE`.
  - The existing unflagged plan test stays as it is.
- **`test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`**
  - Setup: main is `_ranks_db` (ranks A, giving `TRENDING_EXPECTED`). The private file gets the same keys with ranks B, a hand-derived different order, for example `TRENDING_EXPECTED` reversed, written as rank 1..n with equal likes and views.
  - A plain connection on main serves A through `fetch_ordered_page(..., "trending", ...)` and `fetch_popular_videos`. A second connection on the same main file, prepared with `attach_trending_override`, serves B for both.
  - Afterwards `main.trending_ranks` rows are unchanged, read on the plain connection.
  - Control: A ≠ B.
- **Docstring:** two new bullets in the claim style.
- **Interpreter note:** this runs under pytest's `sqlite3`, not the Engine's 3.53.4, as the existing plan test also does. The Engine-side plan is covered indirectly by test 3: deep pages on the session Engine succeed within the 5 s deadline.

**2. `test_server_config.py::test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`** (subprocess, no start lock).

- **Missing path:** `_run([str(ENGINE_PY), str(API_DIR / "server.py"), "--port", str(_free_port()), "--trending-db", str(missing)], None)` with `missing = tmp_path / "absent.db"`. Expect `returncode != 0`, `str(missing)` in stderr, and `not missing.exists()`.
- **Non-SQLite file:** the same call on `tmp_path / "junk.db"` containing 4 KB of non-SQLite bytes. Expect non-zero, the path in stderr, and the file bytes unchanged.
- **Control:** `server.py --help` exits 0 and its stdout contains `--trending-db PATH`.
- **Timing:** a red start would load FAISS and bind. The test bounds `_run`'s timeout and fails if the process is still alive. `_run` already uses `timeout=120`, and validation runs before `connect_db`, so the expected run time is about 1 s.

**3. `test_similar.py::test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(engine, dataset, shared_trending_before)`**

- **Discrimination control:** the shared head (`fetch_ordered_page` on a fresh plain `mode=ro` connection, first `3 * FEED_PAGE`) differs from `_reference(dataset, "trending", threshold)`. If they are equal, the failure message says the shared table holds no real fill, so this test cannot tell the two sources apart.
- **Trending pages:** three `mode=trending` pages, walked with `exclude` as in the existing ordered test, equal `_reference(dataset, "trending", ...)[: 3 * FEED_PAGE]`.
- **Popular layer:** an unseeded home request (`POST /recommendations?limit=<page>&debug=1`, body `{}`, its own rate-bucket header). Every row with `debug.layer == "popular"` must lie in `fetch_popular_videos(dataset, POOL)`, the private head. `POOL` is the Engine's `DEFAULT_POPULAR_POOL_SIZE`, read in the Engine-interpreter child that `_feed_constants` already runs (one more key). Control: at least one popular row is served.
- **Fingerprint:** `shared_trending_fingerprint() == shared_trending_before`. The failure message names an operator updater run (the trending stage) as a possible external cause.
- **Docstring line 64:** the ordered-feed reference is read through `dataset`, which carries the session's private Trending ranks.

**4. Existing tests, unchanged expectations:**
- `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` now compares the Engine with `dataset`, and both read the private file.
- The NSFW control at 1043 reads the same seeded rows.

**5. Build-level, not a test.** Before the build's full suite run, record `shared_trending_fingerprint()` with a one-shot `python -c` against `whitelist.db` `mode=ro`, and compare after. It must be identical, with `count(fetched_at > 0)` > 0.

## Checked against requirements and plan

| Requirement | Met by |
|---|---|
| Flag in `--help`, existing style | `parse_args` addition, `metavar="PATH"` |
| Every `server.db` Trending read uses PATH | TEMP view resolves before main for `fetch_ordered_page` and `fetch_popular_videos`. No other connection reads `trending_ranks`. |
| No write to shared `trending_ranks`, including at startup | `ensure_trending_schema(db)` is skipped when flagged. The schema goes to PATH in `prepare_trending_override`. The Engine has no purge path. |
| Missing or non-SQLite PATH: non-zero exit, path in message, no file created | `mode=rw` open plus schema statement → `SystemExit(...path...)` before `connect_db`. Test 2. |
| Default unchanged; plan uses the index with no TEMP B-TREE, with and without the flag | Unflagged branch is the original statements. Existing plan test plus test 1. |
| Private seed with identical rows, shared read-only, only the temp file written | `trending_seed` uses verbatim `TRENDING_SEED_SQL`, shared attached `mode=ro` |
| Seed drops the lock, `engine` keeps it, constant stays | as drafted |
| Docstrings updated | module, `trending_seed`, `engine` comment, `dataset` comment, line-107 comment, `test_similar` line 64, `test_random_videos` bullets |
| In-suite fingerprint gate plus build before/after | test 3, step 5 |
| Suite green with no expectation changed | option (a): `dataset` carries the view, `_reference` untouched |

## Decisions and deviations

**The settled plan was wrong about `dataset`.** It said no session test reads `trending_ranks` through `dataset`. The impact inventory's HIGH entry showed that `test_similar._reference` does. I took option (a): `dataset` depends on `trending_seed` and carries the same view. It reuses the one helper, changes no test code or expectations, and costs one session seed per lane, which `engine` already pays.

**Named limitations:**
- **Validation-to-ATTACH race.** If the file vanishes in between, plain ATTACH on non-URI `server.db` creates it empty, and Trending then serves empty, never shared. The way up is a URI-enabled `connect_db`.
- **Unescaped `?` or `#` in PATH.** These fail validation instead of opening.
- **Reliance on the query flattener.** This is gated by test 1.
- **SHARED lock during the seed.** The seed holds a SHARED lock on the shared file for a few seconds, which can delay but not block a writer.
- **External changes during a run.** The fingerprint gate goes red if the operator's updater changes the shared ranks mid-run. Its message names that cause.

**Not done:**
- No README edit, because it has no flag list.
- No `UPDATER_WORKER.md` edit, because line 101 stays true for every production start.
- No URI escaping helper.
- No logging change other than one conditional line.

## 2026-10-03 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Trending override helpers [code]

**Files touched.** engine/server/data/trending.py (EDITED), tests/active/test_random_videos.py (EDITED)

**Checkpoint.** Seam: the public functions in `engine/server/data/random_videos.py` (`fetch_ordered_page`, `fetch_popular_videos`) plus `attach_trending_override` and `prepare_trending_override` from `data.trending`. The test calls them in-process, on temp SQLite files (rung 1). It follows the existing harness in `tests/active/test_random_videos.py`: `_schema`, `_ranks_db`, `_plan`, and `test_a_trending_page_walks_the_ranks_index_without_sorting`. Two tests. (a) `test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`: main holds ranks A (`TRENDING_EXPECTED`) and the private file holds the same keys with ranks B, a hand-derived different order (e.g. reversed). A plain connection must serve A from both `fetch_ordered_page(..., "trending", ...)` and `fetch_popular_videos`. A second connection on the same main, prepared with `attach_trending_override`, must serve B from both. After both reads, `main.trending_ranks` rows must equal what was written. Control: assert A != B. (b) `test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`: main gets the 30×100 ranked catalogue plus 1,000 unranked rows, built by a builder factored out of the existing plan test, and its `main.trending_ranks` is left empty. The private file gets `prepare_trending_override` and then the ranks. On the prepared connection, `_plan(conn, "trending")` must contain `idx_trending_ranks_order` and no `TEMP B-TREE`. Control: `_plan(conn, "popular")` contains `TEMP B-TREE`. The existing unflagged plan test stays as it is.

**Intent.** `engine/server/data/trending.py` gains `TRENDING_OVERRIDE_SCHEMA`, `prepare_trending_override` and `attach_trending_override`. A connection prepared by `attach_trending_override` takes every unqualified `trending_ranks` read from the attached file, not from main, and its Trending page is still planned as a walk of `idx_trending_ranks_order` with no sort.

- C1 - On a connection prepared by `attach_trending_override`, `fetch_ordered_page` for `trending` and `fetch_popular_videos` serve the attached file's ranks. On an unprepared connection to the same main they serve main's ranks, and main's ranks are left unchanged.
- C2 - On a connection prepared by `attach_trending_override`, the Trending page's query plan uses `idx_trending_ranks_order` and contains no `TEMP B-TREE`.

**Outcome.** _pending_

#### Phase 2 - Engine --trending-db flag [code]

**Files touched.** engine/server/api/server.py (EDITED), tests/active/test_server_config.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the real Engine entry point `engine/server/api/server.py`, run as a subprocess under the Engine interpreter (rung 2) through `test_server_config._run`. This follows `test_server_config.py`'s existing entry-point tests (e.g. `test_server_py_exits_before_argument_parsing_on_a_bad_value`). There is no start lock, because the start must fail before `connect_db`. Test `test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`. Missing case, `tmp_path / "absent.db"`: assert `returncode != 0`, assert `str(missing)` is in stderr, and assert `not missing.exists()`. Non-SQLite case, `tmp_path / "junk.db"` holding 4 KB of non-SQLite bytes: assert `returncode != 0`, assert the path is in stderr, and assert the file's bytes are unchanged. The timeout is bounded, so a start that wrongly proceeds to load FAISS or bind goes red, not hung. Control: `server.py --help` exits 0 and its stdout contains `--trending-db PATH`. The `tests/config.json` `test_server_config.py` group gains `engine/server/data/trending.py`.

**Intent.** `engine/server/api/server.py` accepts `--trending-db PATH`. `main()` validates PATH before it opens `whitelist.db`, so a PATH that is not an existing SQLite file stops the start, with a message naming it, and leaves the path as it was.

- C1 - Starting `server.py` with `--trending-db` on a missing path or a non-SQLite file exits non-zero, with that path in stderr.
- C2 - The failed start leaves the path as it was: a missing path is not created, and a non-SQLite file's bytes are unchanged.

**Outcome.** _pending_

#### Phase 3 - Active suite on a private Trending seed [code]

**Files touched.** tests/active/conftest.py (EDITED), tests/active/test_similar.py (EDITED)

**Checkpoint.** Seam: the real session Engine over HTTP, through the `engine` fixture in `tests/active/conftest.py`, now started with `--trending-db <trending_seed>`. It follows `test_similar.py`'s existing `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` and its `_reference(dataset, ...)`. Test `test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(engine, dataset, shared_trending_before)`. Discrimination control: on a fresh plain `mode=ro` connection, the shared head (`fetch_ordered_page`, first `3 * FEED_PAGE`) differs from `_reference(dataset, "trending", threshold)`. If they are equal, the message says the shared table has no real fill. Trending: three `mode=trending` pages, walked with `exclude`, must equal `_reference(dataset, "trending", ...)[: 3 * FEED_PAGE]`. Popular layer: an unseeded `POST /recommendations?debug=1` with its own rate-bucket header. Every row with `debug.layer == "popular"` must be in `fetch_popular_videos(dataset, POOL)`, with `POOL` read through `_feed_constants` from the Engine's `DEFAULT_POPULAR_POOL_SIZE`. Control: at least one popular row is served. Fingerprint: `shared_trending_fingerprint() == shared_trending_before`, and the failure message names an updater trending-stage run as a possible external cause. The existing ordered-feed and NSFW tests stay green with unchanged expectations.

**Intent.** The active suite's session Engine reads Trending from a per-session private file. `trending_seed` builds that file from the read-only shared catalogue, `engine` passes it as `--trending-db`, and `dataset` carries it, so the suite serves the seeded order without ever writing the shared `whitelist.db` `trending_ranks`.

- C1 - The session Engine's Trending pages and its popular-layer rows follow the private seed file's ranks, not the shared table's.
- C2 - The shared `whitelist.db` `trending_ranks` fingerprint (row count, `fetched_at` min and max, rows with `fetched_at > 0`) is identical before the seed and after the session Engine has served.

**Outcome.** _pending_


Needs coordination: Phase 3 needs no credential or live endpoint. It does depend on local operator state. The local `whitelist.db` must hold a real `trending_ranks` fill (more than 0 rows with `fetched_at > 0`; triage found 86,826), or the discrimination control fails by design. The operator's updater trending stage must not run during the suite run, or the fingerprint gate goes red for a reason outside the suite. The same applies to the build-level before/after fingerprint around the full suite run.

Rationale: The phases split along the drafted module map's natural layers, bottom-up, so each phase's checkpoint enters at the lowest layer it changes. Phase 1 is the mechanism: the TEMP-view shadowing and the reliance on the query flattener. It is proven in-process at the `random_videos` function seam, where the existing plan and rank harness already lives, so a flattener regression points straight at the helper. Phase 2 is the entry-point contract: validation before `connect_db`, non-zero exit, path in stderr, no file created. That can only be observed through the real CLI, so it is a subprocess test via the existing `_run` harness. The `tests/config.json` group entry goes here because it maps `trending.py` onto that test group. Phase 3 is where the suite switches over: seed, `engine` argv, and `dataset` carrying the view (option (a), the deviation the implementation step recorded). It depends on both earlier phases, and only the real session Engine can show the served order and the untouched shared table. Each Intent cuts into exactly two clauses. The `--help` listing and the A≠B or shared≠private checks are controls inside the clauses, not clauses of their own. There is no prose phase: the only text changes are code docstrings and comments, which land with their phases, and the README is deliberately not edited. Two things are deliberately not phases. The build-level before/after fingerprint (drafted step 5) is a build action, not a test. The Engine-interpreter flagged plan is covered only indirectly, because test 1 runs under pytest's sqlite3, as the existing plan test does; deep pages on the session Engine must still finish within the deadline. The operator approved the plan as presented.

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`engine/server/data/trending.py` gains `TRENDING_OVERRIDE_SCHEMA`, `prepare_trending_override` and `attach_trending_override`. A connection prepared by `attach_trending_override` takes every unqualified `trending_ranks` read from the attached file, not from main, and its Trending page is still planned as a walk of `idx_trending_ranks_order` with no sort.

- C1 - On a connection prepared by `attach_trending_override`, `fetch_ordered_page` for `trending` and `fetch_popular_videos` serve the attached file's ranks. On an unprepared connection to the same main they serve main's ranks, and main's ranks are left unchanged.
- C2 - On a connection prepared by `attach_trending_override`, the Trending page's query plan uses `idx_trending_ranks_order` and contains no `TEMP B-TREE`.

must_prove:
- C1 - On a connection prepared by `attach_trending_override`, `fetch_ordered_page` for `trending` and `fetch_popular_videos` serve the attached file's ranks. On an unprepared connection to the same main they serve main's ranks, and main's ranks are left unchanged.
- C2 - On a connection prepared by `attach_trending_override`, the Trending page's query plan uses `idx_trending_ranks_order` and contains no `TEMP B-TREE`.

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - self-check (audit round 1, send-back 0)

`tests/tmp/test_44_trending_seed_write_lock_during_phase1.py`, surface `checkpoint`. Collection exit 2.

- C1 - test_44_trending_seed_write_lock_during_phase1.py:84 and :85: on the connection prepared by `attach_trending_override`, the labels from `fetch_ordered_page(prepared, "trending", 100, 0)` and from `fetch_popular_videos(prepared, 100)` each equal `OVERRIDE_EXPECTED` - expected: `['B5', 'A3', 'E', 'A2', 'C2', 'B2', 'A1', 'B1', 'X', 'C1']` from both reads. I saw this in probe `tests/tmp/probe_override.py`, which hand-rolled the planned ATTACH + TEMP VIEW on the same fixtures: "view page" and "view pool" both printed this list. - excludes: A bare `ATTACH` with no shadowing view leaves `main.trending_ranks` first in name lookup. In the probe, "bare attach page" printed `['C1', 'X', 'B1', 'A1', 'B2', 'C2', 'A2', 'E', 'A3', 'B5']`, which is `TRENDING_EXPECTED`, so both assertions go red. An override wired into only one of the two reads makes the other one red.
- C1 - test_44_trending_seed_write_lock_during_phase1.py:70, :71 and :86: on the plain connection to the same main, the Trending page and the popular pool equal `TRENDING_EXPECTED` before the override, and the Trending page still equals it after the prepared connection has read - expected: `['C1', 'X', 'B1', 'A1', 'B2', 'C2', 'A2', 'E', 'A3', 'B5']` each time. The probe printed it for "plain page", "plain pool" and "plain after" (read after the view connection had served), and the red run passed :70 and :71. - excludes: An override that copies the file's ranks into `main.trending_ranks`, or one that changes what `ORDERED_FEED_SOURCE` resolves to for every connection, makes the plain read at :86 come back as `OVERRIDE_EXPECTED`.
- C1 - test_44_trending_seed_write_lock_during_phase1.py:87: `sorted(SELECT * FROM main.trending_ranks)` on the plain connection equals `written`, the RANKS rows `_ranks_db` inserted - expected: The 12 ranked RANKS rows as `(instance_domain, video_id, rank, likes, views, 0)`, for example `('c.example', 'c1', 1, 70, 10, 0)` and `('f.example', 'g1', 1, 999, 999, 0)`. The probe's "main rows" output printed exactly these 12 tuples after the view connection had read. The prepared reads at :84/:85 are the positive control that shows the override ran first. - excludes: An override that writes the file's ranks into main (`DELETE` then `INSERT ... SELECT` from the attached schema) leaves main holding ranks 1..10 at likes and views of 10, so the comparison fails.
- C2 - test_44_trending_seed_write_lock_during_phase1.py:105: some EXPLAIN QUERY PLAN detail of the prepared connection's Trending page statement (`_plan(prepared, "trending")`, a filtered 50-row page at offset 100) contains `idx_trending_ranks_order` - expected: In the probe, with the view on the same 4,000-row fixture, the plan was `['SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order', 'SEARCH v USING INDEX sqlite_autoindex_videos_1 (...)', 'SEARCH e ...', 'SEARCH c ... LEFT-JOIN']` (pytest's sqlite 3.53.4). - excludes: A shadow that SQLite does not flatten onto the file's indexed table, such as an unindexed TEMP copy of the ranks, gave `SCAN t` with no index name in the probe, so :105 goes red.
- C2 - test_44_trending_seed_write_lock_during_phase1.py:106: no detail of that same Trending plan contains `TEMP B-TREE`. It is armed by the control at :102, where the same capture for Popular on the prepared connection does show `TEMP B-TREE` - expected: No `USE TEMP B-TREE FOR ORDER BY` in the Trending plan: the probe's view plan listed above has none. The probe's "view popular plan" ended in `USE TEMP B-TREE FOR ORDER BY`, so the capture can show a sort. - excludes: An unindexed temp copy of the file's ranks planned `['SCAN t', ..., 'USE TEMP B-TREE FOR ORDER BY']` in the probe. Any override source that loses the ordered index walk sorts, and :106 goes red.

<assertions>
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:73 — control: OVERRIDE_EXPECTED (TRENDING_EXPECTED reversed, a hand-written literal) differs from TRENDING_EXPECTED and holds the same labels, so only the ranks source decides which order is served. Supports C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:75 — on an unprepared connection, fetch_ordered_page(plain, "trending", 100, 0) serves main's order TRENDING_EXPECTED. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:76 — on an unprepared connection, fetch_popular_videos(plain, 100) serves TRENDING_EXPECTED. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:78 — on a second connection to the same main, prepared by attach_trending_override, fetch_ordered_page "trending" serves the file's order OVERRIDE_EXPECTED. Excludes a bare ATTACH with no shadowing, which was observed to fail here. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:79 — on that prepared connection, fetch_popular_videos serves OVERRIDE_EXPECTED. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:80 — after the prepared reads, the plain connection still serves TRENDING_EXPECTED. Excludes an override that writes into main or leaks across connections; observed to fail against an attach that copies the file's ranks into main.trending_ranks. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:81 — main.trending_ranks, read on the plain connection, equals exactly the rows _ranks_db wrote. Those rows are restated from the RANKS fixture, not from the code. C1 (main's ranks left unchanged).
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:90 — control: with main.trending_ranks empty, a plain connection serves an empty Trending page, so the prepared connection's full page can only come from the file. Supports C2.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:93 — control: on the prepared connection, the Popular plan contains TEMP B-TREE, so the plan capture shows sorts. Supports C2.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:95 (inside harness _plan) — control: the prepared connection's Trending query read a full 50-row page at offset 100 in exactly one statement, which proves it read the file's ranks. Supports C2.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:98 — the prepared connection's Trending EXPLAIN QUERY PLAN names idx_trending_ranks_order. C2.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:99 — the prepared connection's Trending plan has no TEMP B-TREE. Excludes an unindexed temp copy of the ranks, which was observed to sort. C2.
</assertions>

<probes>
1. A probe written at the target path, then run with ValidateTests ["tests/tmp/test_44_trending_seed_write_lock_during_phase1.py", "-s"] (output read from tests/last_test_output.txt). It printed:
- sqlite 3.53.4, Python 3.14.7 (pytest interpreter).
- A touched 0-byte file opened as `file:<path>?mode=rw` takes ensure_trending_schema, and its size goes 0 -> 16384. An absent path under mode=rw raises "OperationalError unable to open database file" and creates no file.
- With main's trending_ranks empty, the plain Trending page has 0 rows.
- On a connection with `ATTACH ... AS trending_override` plus `CREATE TEMP VIEW trending_ranks AS SELECT * FROM trending_override.trending_ranks`:
  - Popular plan: ['SCAN v', 'SEARCH e ...', 'SEARCH c ... LEFT-JOIN', 'USE TEMP B-TREE FOR ORDER BY'].
  - Trending plan: ['SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order', 'SEARCH v ...', 'SEARCH e ...', 'SEARCH c ... LEFT-JOIN'].
- A bare ATTACH with no view serves a 0-row Trending page.
- A TEMP TABLE copy of the ranks plans 'SCAN t' plus 'USE TEMP B-TREE FOR ORDER BY'.
- `_ranks_db` Trending labels are ['C1', 'X', 'B1', 'A1', 'B2', 'C2', 'A2', 'E', 'A3', 'B5'], and main.trending_ranks holds the 12 ranked RANKS rows, GHOST and U included.
- The harness module loads by path via importlib and its tests are not collected.
2. A temporary copy of the final test, with the import swapped for the plan's helper bodies (mode=rw prepare; ATTACH plus TEMP VIEW), run with ValidateTests [..., "-v"]: 2 passed.
3. The same, with the attach reduced to a bare ATTACH: 2 failed.
4. The same, with the attach copying the file's ranks into main.trending_ranks: test (a) failed at the plain re-read ('B5' != 'C1' at index 0) and test (b) passed. That is the expected split: the copy is excluded by C1, not C2.
5. The real import restored and run: collection error, ImportError: cannot import name 'attach_trending_override' from 'data.trending'. This is the expected red before phase 1 is implemented.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_44_trending_seed_write_lock_during_phase1.py` - 7226 characters, inlined in full

```
"""A connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file, and a plain connection on the same main reads main's:

- On `_ranks_db` (main ranks giving `TRENDING_EXPECTED`) with a private file holding the same keys ranked in `OVERRIDE_EXPECTED`, the reverse order: a plain connection serves `TRENDING_EXPECTED` from `fetch_ordered_page(conn, "trending", ...)` and `fetch_popular_videos`, a second connection on the same main prepared with `attach_trending_override` serves `OVERRIDE_EXPECTED` from both, the plain connection still serves `TRENDING_EXPECTED` afterwards, and `main.trending_ranks` holds exactly the rows written to it.
- On a 4,000-row main DB whose own `trending_ranks` is empty, with the ranks written to a private file after `prepare_trending_override`, the prepared connection reads a full Trending page from the file (a plain connection reads none), its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order` and has no `TEMP B-TREE`; the same capture for Popular shows the temp B-tree (control).

The fixtures, `TRENDING_EXPECTED` and `_plan` are the harness in `tests/active/test_random_videos.py`, loaded by path so its tests are not collected here.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_HARNESS_SPEC = importlib.util.spec_from_file_location("random_videos_harness", ROOT / "tests" / "active" / "test_random_videos.py")
harness = importlib.util.module_from_spec(_HARNESS_SPEC)
# The harness puts engine/server and its api dir on sys.path, which the data imports below need.
_HARNESS_SPEC.loader.exec_module(harness)

from data import random_videos  # noqa: E402
from data.ann_ids import compute_ann_id  # noqa: E402
from data.trending import attach_trending_override, prepare_trending_override  # noqa: E402

# The override file's order: TRENDING_EXPECTED reversed, written as ranks 1..10 on equal listed likes and views so the rank alone orders them. GHOST and U keep a rank there too and stay unserved.
OVERRIDE_EXPECTED = ["B5", "A3", "E", "A2", "C2", "B2", "A1", "B1", "X", "C1"]
OVERRIDE_UNSERVED = ("GHOST", "U")


def _private_file(path: Path) -> Path:
    """An existing empty file at `path`, given the trending schema by `prepare_trending_override`, which never creates one."""
    path.touch()
    prepare_trending_override(str(path))
    return path


def _prepared(main: Path, private: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(main)
    conn.row_factory = sqlite3.Row
    attach_trending_override(conn, str(private))
    return conn


def _ranked_catalogue(conn: sqlite3.Connection, ranks_conn: sqlite3.Connection) -> None:
    """30 hosts of 100 embedded catalogue rows ranked 1..100 on `ranks_conn`, and 1,000 embedded rows with no rank, on `conn`."""
    for h in range(30):
        host = f"h{h:02d}.example"
        for rank in range(1, 101):
            video_id = f"v{rank:03d}"
            conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, popularity, last_checked_at) VALUES (?, ?, ?, ?, ?, 0)", (video_id, host, rank, 10 * rank, rank))
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
            ranks_conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, video_id, rank, 100 - rank, 1000 - rank))
    for n in range(1000):
        conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, last_checked_at) VALUES (?, 'u.example', 1, 1, 0)", (f"u{n}",))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'u.example', x'00', 1, 'm', 't', ?)", (f"u{n}", compute_ann_id(f"u{n}", "u.example")))
    conn.commit()
    ranks_conn.commit()


def test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it(tmp_path):
    main = tmp_path / "main.db"
    plain = harness._ranks_db(main)
    private = _private_file(tmp_path / "private.db")
    writer = sqlite3.connect(private)
    for rank, label in enumerate(OVERRIDE_EXPECTED, start=1):
        video_id, host = harness.RANKS[label][:2]
        writer.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, 10, 10, 0)", (host, video_id, rank))
    for label in OVERRIDE_UNSERVED:
        video_id, host = harness.RANKS[label][:2]
        writer.execute("INSERT INTO trending_ranks VALUES (?, ?, 1, 999, 999, 0)", (host, video_id))
    writer.commit()
    writer.close()
    assert OVERRIDE_EXPECTED != harness.TRENDING_EXPECTED and sorted(OVERRIDE_EXPECTED) == sorted(harness.TRENDING_EXPECTED)  # control: the same rows in another order, so only the ranks source decides which order is served
    written = sorted((host, video_id, rank, likes, views, 0) for video_id, host, rank, likes, views, *_ in harness.RANKS.values() if rank is not None)

    assert harness._trending_labels(random_videos.fetch_ordered_page(plain, "trending", 100, 0)) == harness.TRENDING_EXPECTED  # C1: unprepared, the Trending page reads main's ranks
    assert harness._trending_labels(random_videos.fetch_popular_videos(plain, 100)) == harness.TRENDING_EXPECTED  # C1: unprepared, the popular pool reads main's ranks
    prepared = _prepared(main, private)
    assert harness._trending_labels(random_videos.fetch_ordered_page(prepared, "trending", 100, 0)) == OVERRIDE_EXPECTED  # C1: prepared, the Trending page reads the file's ranks
    assert harness._trending_labels(random_videos.fetch_popular_videos(prepared, 100)) == OVERRIDE_EXPECTED  # C1: prepared, the popular pool reads the file's ranks
    assert harness._trending_labels(random_videos.fetch_ordered_page(plain, "trending", 100, 0)) == harness.TRENDING_EXPECTED  # C1: the override stays on the prepared connection; the plain one still reads main's ranks
    assert sorted(tuple(row) for row in plain.execute("SELECT * FROM main.trending_ranks")) == written  # C1: main's ranks are left as written


def test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting(tmp_path):
    main = tmp_path / "main.db"
    conn = harness._schema(main)
    private = _private_file(tmp_path / "private.db")
    writer = sqlite3.connect(private)
    _ranked_catalogue(conn, writer)
    writer.close()
    # Control: main's own ranks are empty, so a full page on the prepared connection can only come from the file (observed: a bare ATTACH with no shadowing serves 0 rows).
    assert random_videos.fetch_ordered_page(conn, "trending", 100, 0) == []
    prepared = _prepared(main, private)
    # Control: the plan shows a sort where an order has no index (observed: USE TEMP B-TREE FOR ORDER BY).
    assert any("TEMP B-TREE" in detail for detail in harness._plan(prepared, "popular"))
    # _plan also asserts the prepared connection read a full 50-row page 100 rows in.
    details = harness._plan(prepared, "trending")
    assert any("idx_trending_ranks_order" in detail for detail in details), details  # C2: the Trending page walks the file's ranks index
    assert not any("TEMP B-TREE" in detail for detail in details), details  # C2: and does not sort (observed: an unindexed temp copy of the ranks sorts)

```


Gate: satisfied

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - does not collect (send-back 1)

`validate_tests.py tests/tmp/test_44_trending_seed_write_lock_during_phase1.py --collect-only -q` exited 2.

```

==================================== ERRORS ====================================
_ ERROR collecting tests/tmp/test_44_trending_seed_write_lock_during_phase1.py _
ImportError while importing test module '/home/enduser/code/PeerTube-browser/tests/tmp/test_44_trending_seed_write_lock_during_phase1.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.pixi/envs/default/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:22: in <module>
    from data.trending import attach_trending_override, prepare_trending_override  # noqa: E402
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ImportError: cannot import name 'attach_trending_override' from 'data.trending' (/home/enduser/code/PeerTube-browser/engine/server/data/trending.py)
=========================== short test summary info ============================
ERROR tests/tmp/test_44_trending_seed_write_lock_during_phase1.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
no tests collected, 1 error in 0.07s

the run produced no per-test results, so there is nothing to bucket or compare — its output above says why

recorded: tests/last_test_validation.json (exit 2)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - self-check (audit round 1, send-back 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_44_trending_seed_write_lock_during_phase1.py:84 and :85 — on the connection prepared by `trending.attach_trending_override`, the labels of `fetch_ordered_page(prepared, "trending", 100, 0)` and of `fetch_popular_videos(prepared, 100)` each equal `OVERRIDE_EXPECTED` - expected: `['B5', 'A3', 'E', 'A2', 'C2', 'B2', 'A1', 'B1', 'X', 'C1']` from both reads. I re-ran `tests/tmp/probe_override.py -s` this turn. It hand-rolls the planned ATTACH + `CREATE TEMP VIEW trending_ranks` on the same fixtures, and it printed "view page" and "view pool" as this exact list. - excludes: A bare `ATTACH` with no shadowing view leaves `main.trending_ranks` first in name lookup. In the probe, "bare attach page" printed `['C1', 'X', 'B1', 'A1', 'B2', 'C2', 'A2', 'E', 'A3', 'B5']`, which is `TRENDING_EXPECTED`, so both assertions go red. An override that reaches only one of the two reads leaves the other one red.
- C1 - test_44_trending_seed_write_lock_during_phase1.py:70, :71 and :86 — on the plain connection to the same main, the Trending page and the popular pool equal `harness.TRENDING_EXPECTED` before the override, and the Trending page still equals it after the prepared connection has read - expected: `['C1', 'X', 'B1', 'A1', 'B2', 'C2', 'A2', 'E', 'A3', 'B5']` each time. The probe printed it for "plain page", "plain pool" and "plain after", the last read taken after the view connection had served. In this turn's checkpoint run, :70 and :71 passed before the failure at :72. - excludes: An override that copies the file's ranks into `main.trending_ranks`, or one that changes the Trending source for every connection (for example by rewriting `ORDERED_FEED_SOURCE`), makes the plain read at :86 come back as `OVERRIDE_EXPECTED`.
- C1 - test_44_trending_seed_write_lock_during_phase1.py:87 — `sorted(SELECT * FROM main.trending_ranks)` on the plain connection equals `written`, which is the ranked RANKS rows `_ranks_db` inserted, restated at :68 from the fixture - expected: The 12 tuples the probe printed under "main rows" after the view connection had read, from `('a.example', 'a1', 1, 50, 100, 0)` through `('f.example', 'g1', 1, 999, 999, 0)`. Its positive control is :84/:85, which show the override actually served from the file first. - excludes: An override that writes the file's ranks into main (`DELETE` then `INSERT ... SELECT` from the attached schema) leaves main holding ranks 1..10 at likes and views of 10 instead of the written rows, so the comparison fails.
- C2 - test_44_trending_seed_write_lock_during_phase1.py:105 — some EXPLAIN QUERY PLAN detail of the prepared connection's Trending page statement (`harness._plan(prepared, "trending")`, a filtered 50-row page at offset 100 that `_plan` asserts came back full) contains `idx_trending_ranks_order` - expected: The probe printed this "view trending plan" on the same 4,000-row fixture: `['SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order', 'SEARCH v USING INDEX sqlite_autoindex_videos_1 (...)', 'SEARCH e ...', 'SEARCH c ... LEFT-JOIN']`. - excludes: A shadow that SQLite cannot flatten onto the file's indexed table, such as an unindexed TEMP copy of the file's ranks, planned `SCAN t` with no index name in the probe ("unindexed temp copy trending plan"), so :105 goes red.
- C2 - test_44_trending_seed_write_lock_during_phase1.py:106 — no detail of that same Trending plan contains `TEMP B-TREE`. The control at :102 arms it: the same capture for Popular on the prepared connection does contain `TEMP B-TREE` - expected: The probe's "view trending plan" quoted above has no `USE TEMP B-TREE FOR ORDER BY`. Its "view popular plan" ends in `USE TEMP B-TREE FOR ORDER BY`, so the capture is able to show a sort. - excludes: The unindexed temp copy planned `['SCAN t', ..., 'USE TEMP B-TREE FOR ORDER BY']` in the probe. Any override source that loses the ordered index walk sorts, and :106 goes red.

<assertions>
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:67 — control: OVERRIDE_EXPECTED (TRENDING_EXPECTED reversed, a hand-written literal) differs from TRENDING_EXPECTED and holds the same labels, so only the ranks source decides which order is served. Supports C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:70 — on an unprepared connection, fetch_ordered_page(plain, "trending", 100, 0) serves main's order TRENDING_EXPECTED. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:71 — on an unprepared connection, fetch_popular_videos(plain, 100) serves TRENDING_EXPECTED. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:84 — on a second connection to the same main, prepared by trending.attach_trending_override, fetch_ordered_page "trending" serves the file's order OVERRIDE_EXPECTED. Excludes a bare ATTACH with no shadowing, which was observed to fail here. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:85 — on that prepared connection, fetch_popular_videos serves OVERRIDE_EXPECTED. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:86 — after the prepared reads, the plain connection still serves TRENDING_EXPECTED. Excludes an override that writes into main or leaks across connections; observed to fail against an attach that copies the file's ranks into main.trending_ranks. C1.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:87 — main.trending_ranks, read on the plain connection, equals exactly the rows _ranks_db wrote. Those rows are restated from the RANKS fixture at line 68, not from the code. C1 (main's ranks left unchanged).
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:95 — control: with main.trending_ranks empty, a plain connection serves an empty Trending page, so the prepared connection's full page can only come from the file. Supports C2.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:102 — control: on the prepared connection, the Popular plan contains TEMP B-TREE, so the plan capture shows sorts. Supports C2.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:104 (inside harness _plan) — control: the prepared connection's Trending query read a full 50-row page at offset 100 in exactly one statement, which proves it read the file's ranks. Supports C2.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:105 — the prepared connection's Trending EXPLAIN QUERY PLAN names idx_trending_ranks_order. C2.
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:106 — the prepared connection's Trending plan has no TEMP B-TREE. Excludes an unindexed temp copy of the ranks, which was observed to sort. C2.
</assertions>

<probes>
1. A probe written at the target path, then run with ValidateTests ["tests/tmp/test_44_trending_seed_write_lock_during_phase1.py", "-s"] (output read from tests/last_test_output.txt). It printed:
- sqlite 3.53.4, Python 3.14.7 (pytest interpreter).
- A touched 0-byte file opened as `file:<path>?mode=rw` takes ensure_trending_schema, and its size goes 0 -> 16384. An absent path under mode=rw raises "OperationalError unable to open database file" and creates no file.
- With main's trending_ranks empty, the plain Trending page has 0 rows.
- On a connection with `ATTACH ... AS trending_override` plus `CREATE TEMP VIEW trending_ranks AS SELECT * FROM trending_override.trending_ranks`:
  - Popular plan: ['SCAN v', 'SEARCH e ...', 'SEARCH c ... LEFT-JOIN', 'USE TEMP B-TREE FOR ORDER BY'].
  - Trending plan: ['SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order', 'SEARCH v ...', 'SEARCH e ...', 'SEARCH c ... LEFT-JOIN'].
- A bare ATTACH with no view serves a 0-row Trending page.
- A TEMP TABLE copy of the ranks plans 'SCAN t' plus 'USE TEMP B-TREE FOR ORDER BY'.
- `_ranks_db` Trending labels are ['C1', 'X', 'B1', 'A1', 'B2', 'C2', 'A2', 'E', 'A3', 'B5'], and main.trending_ranks holds the 12 ranked RANKS rows, GHOST and U included.
- The harness module loads by path via importlib and its tests are not collected.
2. A temporary copy of the final test, with the helpers swapped for the plan's bodies (mode=rw prepare; ATTACH plus TEMP VIEW), run with ValidateTests [..., "-v"]: 2 passed.
3. The same, with the attach reduced to a bare ATTACH: 2 failed.
4. The same, with the attach copying the file's ranks into main.trending_ranks: test (a) failed at the plain re-read ('B5' != 'C1' at index 0) and test (b) passed. That split is what I expected: C1 excludes the copy, and C2 does not.
5. Collection fix: the previous version did `from data.trending import attach_trending_override, prepare_trending_override` at module level. That fails at collection (ImportError), so no per-test results came out. The test now imports `from data import random_videos, trending` and looks up `trending.prepare_trending_override` / `trending.attach_trending_override` only when called. ValidateTests ["tests/tmp/test_44_trending_seed_write_lock_during_phase1.py", "-v"]: it collected, with 2 failed. Both failed at line 31 with `AttributeError: module 'data.trending' has no attribute 'prepare_trending_override'`, after the controls and plain-connection asserts that need no helper had passed: lines 67, 70 and 71 in test (a), and line 95 in test (b). That is the expected red before phase 1 is implemented.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_44_trending_seed_write_lock_during_phase1.py` - 7634 characters, inlined in full

```
"""A connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file, and a plain connection on the same main reads main's:

- On `_ranks_db` (main ranks giving `TRENDING_EXPECTED`) with a private file holding the same keys ranked in `OVERRIDE_EXPECTED`, the reverse order: a plain connection serves `TRENDING_EXPECTED` from `fetch_ordered_page(conn, "trending", ...)` and `fetch_popular_videos`, a second connection on the same main prepared with `attach_trending_override` serves `OVERRIDE_EXPECTED` from both, the plain connection still serves `TRENDING_EXPECTED` afterwards, and `main.trending_ranks` holds exactly the rows written to it.
- On a 4,000-row main DB whose own `trending_ranks` is empty, with the ranks written to a private file after `prepare_trending_override`, the prepared connection reads a full Trending page from the file, its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order` and has no `TEMP B-TREE`; the same capture for Popular shows the temp B-tree (control).

The fixtures, `TRENDING_EXPECTED` and `_plan` are the harness in `tests/active/test_random_videos.py`, loaded by path so its tests are not collected here. The override helpers are looked up on `data.trending` when called, so the controls that need none of them run first.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_HARNESS_SPEC = importlib.util.spec_from_file_location("random_videos_harness", ROOT / "tests" / "active" / "test_random_videos.py")
harness = importlib.util.module_from_spec(_HARNESS_SPEC)
# The harness puts engine/server and its api dir on sys.path, which the data imports below need.
_HARNESS_SPEC.loader.exec_module(harness)

from data import random_videos, trending  # noqa: E402
from data.ann_ids import compute_ann_id  # noqa: E402

# The override file's order: TRENDING_EXPECTED reversed, written as ranks 1..10 on equal listed likes and views so the rank alone orders them. GHOST and U keep a rank there too and stay unserved.
OVERRIDE_EXPECTED = ["B5", "A3", "E", "A2", "C2", "B2", "A1", "B1", "X", "C1"]
OVERRIDE_UNSERVED = ("GHOST", "U")


def _private_file(path: Path) -> Path:
    """An existing empty file at `path`, given the trending schema by `prepare_trending_override`, which never creates one."""
    path.touch()
    trending.prepare_trending_override(str(path))
    return path


def _prepared(main: Path, private: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(main)
    conn.row_factory = sqlite3.Row
    trending.attach_trending_override(conn, str(private))
    return conn


def _catalogue(conn: sqlite3.Connection) -> None:
    """30 hosts of 100 embedded catalogue rows, and 1,000 embedded rows `_catalogue_ranks` leaves unranked, on `conn`."""
    for h in range(30):
        host = f"h{h:02d}.example"
        for rank in range(1, 101):
            video_id = f"v{rank:03d}"
            conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, popularity, last_checked_at) VALUES (?, ?, ?, ?, ?, 0)", (video_id, host, rank, 10 * rank, rank))
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
    for n in range(1000):
        conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, last_checked_at) VALUES (?, 'u.example', 1, 1, 0)", (f"u{n}",))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'u.example', x'00', 1, 'm', 't', ?)", (f"u{n}", compute_ann_id(f"u{n}", "u.example")))
    conn.commit()


def _catalogue_ranks(ranks_conn: sqlite3.Connection) -> None:
    """The 30 hosts' catalogue rows ranked 1..100, on `ranks_conn`."""
    for h in range(30):
        for rank in range(1, 101):
            ranks_conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (f"h{h:02d}.example", f"v{rank:03d}", rank, 100 - rank, 1000 - rank))
    ranks_conn.commit()


def test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it(tmp_path):
    main = tmp_path / "main.db"
    plain = harness._ranks_db(main)
    assert OVERRIDE_EXPECTED != harness.TRENDING_EXPECTED and sorted(OVERRIDE_EXPECTED) == sorted(harness.TRENDING_EXPECTED)  # control: the same rows in another order, so only the ranks source decides which order is served
    written = sorted((host, video_id, rank, likes, views, 0) for video_id, host, rank, likes, views, *_ in harness.RANKS.values() if rank is not None)

    assert harness._trending_labels(random_videos.fetch_ordered_page(plain, "trending", 100, 0)) == harness.TRENDING_EXPECTED  # C1: unprepared, the Trending page reads main's ranks
    assert harness._trending_labels(random_videos.fetch_popular_videos(plain, 100)) == harness.TRENDING_EXPECTED  # C1: unprepared, the popular pool reads main's ranks
    private = _private_file(tmp_path / "private.db")
    writer = sqlite3.connect(private)
    for rank, label in enumerate(OVERRIDE_EXPECTED, start=1):
        video_id, host = harness.RANKS[label][:2]
        writer.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, 10, 10, 0)", (host, video_id, rank))
    for label in OVERRIDE_UNSERVED:
        video_id, host = harness.RANKS[label][:2]
        writer.execute("INSERT INTO trending_ranks VALUES (?, ?, 1, 999, 999, 0)", (host, video_id))
    writer.commit()
    writer.close()
    prepared = _prepared(main, private)
    # Observed: a bare ATTACH of this file, which leaves main.trending_ranks in front, still serves TRENDING_EXPECTED from both reads.
    assert harness._trending_labels(random_videos.fetch_ordered_page(prepared, "trending", 100, 0)) == OVERRIDE_EXPECTED  # C1: prepared, the Trending page reads the file's ranks
    assert harness._trending_labels(random_videos.fetch_popular_videos(prepared, 100)) == OVERRIDE_EXPECTED  # C1: prepared, the popular pool reads the file's ranks
    assert harness._trending_labels(random_videos.fetch_ordered_page(plain, "trending", 100, 0)) == harness.TRENDING_EXPECTED  # C1: the override stays on the prepared connection; the plain one still reads main's ranks
    assert sorted(tuple(row) for row in plain.execute("SELECT * FROM main.trending_ranks")) == written  # C1: main's ranks are left as written


def test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting(tmp_path):
    main = tmp_path / "main.db"
    conn = harness._schema(main)
    _catalogue(conn)
    # Control: main's own ranks are empty, so a full page on the prepared connection can only come from the file (observed: a bare ATTACH of it, with main.trending_ranks still in front, serves 0 rows).
    assert random_videos.fetch_ordered_page(conn, "trending", 100, 0) == []
    private = _private_file(tmp_path / "private.db")
    writer = sqlite3.connect(private)
    _catalogue_ranks(writer)
    writer.close()
    prepared = _prepared(main, private)
    # Control: the plan shows a sort where an order has no index (observed: USE TEMP B-TREE FOR ORDER BY).
    assert any("TEMP B-TREE" in detail for detail in harness._plan(prepared, "popular"))
    # _plan also asserts the prepared connection read a full 50-row page 100 rows in.
    details = harness._plan(prepared, "trending")
    assert any("idx_trending_ranks_order" in detail for detail in details), details  # C2: the Trending page walks the file's ranks index
    assert not any("TEMP B-TREE" in detail for detail in details), details  # C2: and does not sort (observed: an unindexed temp copy of the ranks plans SCAN t and USE TEMP B-TREE FOR ORDER BY)

```


Gate: satisfied

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - red (audit round 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase1.py` exited 1.

```
  tests/tmp/test_44_trending_seed_write_lock_during_phase1.py  2 failed                               0.0s
  -----------------------------------------------------------
  total                                                        2 failed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D15

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Both tests fail when `_private_file` calls `trending.prepare_trending_override(str(path))`
at line 31. The call raises AttributeError because engine/server/data/trending.py defines
only `ensure_trending_schema`. The first test reaches it from line 72, after the
unprepared-connection assertions at lines 70–71 pass. The second reaches it from line 96,
after the empty-main control at line 95 passes. No C1 or C2 assertion (lines 84–87,
102–106) runs before the code is in place.

NOT ASSESSED
1. `fixtures_path` was "none found". The test uses no pytest fixture apart from
   `tmp_path`. It loads its harness (`_ranks_db`, `_schema`, `_plan`, `_trending_labels`,
   `RANKS`, `TRENDING_EXPECTED`) by path from tests/active/test_random_videos.py, and I
   read those definitions at lines 86–219.
2. `random_videos.fetch_ordered_page` and `random_videos.fetch_popular_videos` are not in
   `code_under_test`, so I did not read them. I answered the stub question from the
   assertion form and the harness.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | prepared conn: `fetch_ordered_page` "trending" serves the attached file's ranks | :84 | a plain ATTACH with no shadowing, which leaves `main.trending_ranks` first and serves the reversed list `TRENDING_EXPECTED` | CARRIED |
| C1b | must_prove | prepared conn: `fetch_popular_videos` serves the attached file's ranks | :85 | an override that reaches the page read and misses the pool | CARRIED |
| C1c | must_prove | unprepared conn on the same main: Trending page serves main's ranks | :70, :86 | an override that writes main or switches the source for every connection; :86 reads after the prepared connection has read | CARRIED |
| C1d | must_prove | unprepared conn on the same main: popular pool serves main's ranks | :71 | a pool that does not read main's `trending_ranks` order (the pool is the head of the Trending order, `random_videos.py:237`) | CARRIED |
| C1e | must_prove | main's ranks are left unchanged | :87 | a committed copy, delete or rewrite of `main.trending_ranks`. The expected rows are rebuilt from `RANKS` at :68, not read back from the code | CARRIED |
| C2a | must_prove | prepared conn: Trending plan uses `idx_trending_ranks_order` | :105 (with `_plan`'s full-page check at :104 and the empty-main control at :95) | a temp copy or view that loses the index. Main's empty table also has an index by this name, but a full 50-row page can only come from the file | CARRIED |
| C2b | must_prove | prepared conn: Trending plan has no `TEMP B-TREE` | :106 | an unindexed shadow that plans SCAN plus USE TEMP B-TREE FOR ORDER BY | CARRIED |
| D1 | docstring | "a connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file" | :84, :85 | a plain ATTACH that reads main | CARRIED |
| D2 | docstring | "a plain connection on the same main reads main's" | :70, :71, :86 | an override that leaks to other connections | CARRIED |
| D3 | docstring | private file holds "the same keys ranked in `OVERRIDE_EXPECTED`", a different order | :67 | a fixture where the two orders match, which would make :84 and :85 pass on main's ranks | CARRIED |
| D4 | docstring | plain serves `TRENDING_EXPECTED` from both `fetch_ordered_page` and `fetch_popular_videos` | :70, :71 | either read ignoring main's ranks | CARRIED |
| D5 | docstring | prepared serves `OVERRIDE_EXPECTED` "from both" | :84, :85 | an override covering only one read | CARRIED |
| D6 | docstring | "the plain connection still serves `TRENDING_EXPECTED` afterwards" | :86 | an override that persists across connections | CARRIED |
| D7 | docstring | "`main.trending_ranks` holds exactly the rows written to it" | :87 | added, removed or rewritten rows in main | CARRIED |
| D8 | docstring | main DB "whose own `trending_ranks` is empty" | :95 | ranks present in main, which would let a plain ATTACH fill the page | CARRIED |
| D9 | docstring | ranks "written to a private file after `prepare_trending_override`" (file gets the schema and index) | :98 / :105 | a prepare that creates no table (the insert at :98 fails) or no index (:105 fails) | CARRIED |
| D10 | docstring | "the prepared connection reads a full Trending page from the file" | :104 (`_plan`, `tests/active/test_random_videos.py:217`) | a plain ATTACH serving 0 rows from main's empty table | CARRIED |
| D11 | docstring | "its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order`" | :105 | a plan that skips the index | CARRIED |
| D12 | docstring | "and has no `TEMP B-TREE`" | :106 | a plan that sorts | CARRIED |
| D13 | docstring | "the same capture for Popular shows the temp B-tree (control)" | :102 | a plan capture that cannot show a sort, which would make :106 pass vacuously | CARRIED |
| D14 | docstring | `_private_file`: an existing empty file given the trending schema | :98 / :105 | a prepare that leaves the file without schema | CARRIED |
| D15 | docstring | `_private_file`: `prepare_trending_override` "never creates one" | none | nothing. :30 always `touch()`es the file first, so a prepare that creates a missing file passes | UNCARRIED |
| N1 | name | test 1: "trending and the popular pool read main ranks without the override" | :70, :71, :86 | either read on the plain conn not serving main's order | CARRIED |
| N2 | name | test 1: "and the file's ranks with it" | :84, :85 | a plain ATTACH or an override covering one read only | CARRIED |
| N3 | name | test 2: "a trending page on the override file" | :104 with control :95 | a page not served from the file (main is empty) | CARRIED |
| N4 | name | test 2: "walks its ranks index" | :105 | a plan without `idx_trending_ranks_order` | CARRIED |
| N5 | name | test 2: "without sorting" | :106 | a plan with `TEMP B-TREE` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:29
   `"""An existing empty file at `path`, given the trending schema by `prepare_trending_override`, which never creates one."""`
   D15 is UNCARRIED. The helper's docstring says `prepare_trending_override` never creates a file, and :30 `path.touch()` always creates the file before the call. No path in this file calls prepare on a missing file and checks that nothing appeared. Either assert it, or cut the sentence back to what the helper does. This is not a `must_prove` clause, so it does not block.
2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31, :38
   Only the success path of the two helpers runs. Neither `prepare_trending_override` nor `attach_trending_override` is ever run on a missing or non-SQLite path, so the expected failure mode is untested here.
3. bounds (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:82
   Every prepared connection has a populated override file. Nothing covers a prepared connection whose file has the schema and no rows. That case would show whether the Trending page and pool come back empty or fall back to main's ranks, and it is the edge between "the file's ranks" and "main's ranks" in C1.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists engine/server/data/trending.py (EDITED). As read, it defines only `ensure_trending_schema`. It has no `prepare_trending_override` or `attach_trending_override`, and no definition exists anywhere outside docs/project/plans. So I could not judge from the code which inputs the helpers accept or how they fail. Recommendations 2 and 3 rest on the test file and on `random_videos.py:37` and `:237` only.
2. tests/active/test_random_videos.py was read only in part: lines 86–245, which cover `RANKS`, `TRENDING_EXPECTED`, `_schema`, `_ranks_db`, `_trending_labels` and `_plan`. Its module header was not read, so the imports and `sys.path` setup the harness exec at :18 depends on were not checked.

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - self-check (audit round 2, send-back 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1a - tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:84 — on the prepared connection, fetch_ordered_page(prepared, "trending", 100, 0) labels equal OVERRIDE_EXPECTED - expected: ["B5", "A3", "E", "A2", "C2", "B2", "A1", "B1", "X", "C1"] - excludes: A bare ATTACH with no shadowing leaves main.trending_ranks resolved first. It serves TRENDING_EXPECTED (the reverse order), and the probe saw this fail.
- C1b - tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:85 — on the prepared connection, fetch_popular_videos(prepared, 100) labels equal OVERRIDE_EXPECTED - expected: OVERRIDE_EXPECTED - excludes: An override that reaches the page read but misses the pool, or a bare ATTACH. Either one serves TRENDING_EXPECTED.
- C1c - tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:70 and :86 — on the plain connection, fetch_ordered_page "trending" labels equal TRENDING_EXPECTED, both before the override exists and after the prepared connection has read - expected: ["C1", "X", "B1", "A1", "B2", "C2", "A2", "E", "A3", "B5"] - excludes: An attach that copies the file's ranks into main.trending_ranks, or that switches the source for every connection. Under it, :86 serves OVERRIDE_EXPECTED; the probe saw it fail with 'B5' != 'C1'.
- C1d - tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:71 — on the plain connection, fetch_popular_videos(plain, 100) labels equal TRENDING_EXPECTED - expected: TRENDING_EXPECTED - excludes: A pool that does not read main's trending_ranks order. It serves the catalogue in some other order.
- C1e - tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:87 — sorted rows of main.trending_ranks equal `written`, which line 68 rebuilds from harness.RANKS - expected: The 12 ranked RANKS rows (GHOST and U included), as (host, video_id, rank, likes, views, 0) - excludes: A committed copy, delete or rewrite of main.trending_ranks by prepare or attach. Under it, main holds the file's ranks or no rows, which differs from `written`.
- C2a - tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:105 — the prepared connection's Trending EXPLAIN QUERY PLAN names idx_trending_ranks_order. It is armed by :95 (main is empty) and by the full 50-row page check inside _plan at :104 - expected: A detail like 'SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order' - excludes: A temp copy of the ranks, or a view that loses the index. The plan reads 'SCAN t' with no index name, as the probe saw.
- C2b - tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:106 — the prepared connection's Trending plan has no 'TEMP B-TREE' detail. The Popular plan control at :102 shows the capture can surface a sort - expected: No detail contains TEMP B-TREE - excludes: An unindexed shadow table. It plans 'SCAN t' plus 'USE TEMP B-TREE FOR ORDER BY', as the probe saw.

<items>
<item id="D15">
<disposition>justified</disposition>
<what>I cut the sentence back to what the helper actually does. The `_private_file` docstring at :29 used to say the file is given the trending schema "by `prepare_trending_override`, which never creates one". It now says "An empty file touched at `path`, then given the trending schema by `prepare_trending_override`." Nothing in this file calls prepare on a missing path, so the claim had nothing behind it, and I have not seen how a missing path fails under the real helper. The probe saw that the plan's `mode=rw` body raises OperationalError, but that was the plan's body, not the helper. The new sentence is one line, so no other line moved and every assertion line number in the ledger still holds. The schema half of the sentence is still carried by :98 and :105, the same as D14.</what>
</item>
</items>

<findings_addressed>
There were no CRITICAL findings from either auditor. Claim recommendation 1 (D15 uncarried): taken. I narrowed the `_private_file` docstring at :29 to what the helper does: it touches the file, then prepares it. Claim recommendations 2 and 3 (failure paths, and a prepared file with no rows): left. Neither the clauses nor the phase say what the helpers should do on a missing path or an empty override file, so any expected value I wrote would be a guess.
</findings_addressed>

<rows>
<row clause="C1a">
<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:84 — on the prepared connection, fetch_ordered_page(prepared, "trending", 100, 0) labels equal OVERRIDE_EXPECTED</assertion>
<expected>["B5", "A3", "E", "A2", "C2", "B2", "A1", "B1", "X", "C1"]</expected>
<wrong_implementation>A bare ATTACH with no shadowing leaves main.trending_ranks resolved first. It serves TRENDING_EXPECTED (the reverse order), and the probe saw this fail.</wrong_implementation>
</row>
<row clause="C1b">
<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:85 — on the prepared connection, fetch_popular_videos(prepared, 100) labels equal OVERRIDE_EXPECTED</assertion>
<expected>OVERRIDE_EXPECTED</expected>
<wrong_implementation>An override that reaches the page read but misses the pool, or a bare ATTACH. Either one serves TRENDING_EXPECTED.</wrong_implementation>
</row>
<row clause="C1c">
<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:70 and :86 — on the plain connection, fetch_ordered_page "trending" labels equal TRENDING_EXPECTED, both before the override exists and after the prepared connection has read</assertion>
<expected>["C1", "X", "B1", "A1", "B2", "C2", "A2", "E", "A3", "B5"]</expected>
<wrong_implementation>An attach that copies the file's ranks into main.trending_ranks, or that switches the source for every connection. Under it, :86 serves OVERRIDE_EXPECTED; the probe saw it fail with 'B5' != 'C1'.</wrong_implementation>
</row>
<row clause="C1d">
<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:71 — on the plain connection, fetch_popular_videos(plain, 100) labels equal TRENDING_EXPECTED</assertion>
<expected>TRENDING_EXPECTED</expected>
<wrong_implementation>A pool that does not read main's trending_ranks order. It serves the catalogue in some other order.</wrong_implementation>
</row>
<row clause="C1e">
<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:87 — sorted rows of main.trending_ranks equal `written`, which line 68 rebuilds from harness.RANKS</assertion>
<expected>The 12 ranked RANKS rows (GHOST and U included), as (host, video_id, rank, likes, views, 0)</expected>
<wrong_implementation>A committed copy, delete or rewrite of main.trending_ranks by prepare or attach. Under it, main holds the file's ranks or no rows, which differs from `written`.</wrong_implementation>
</row>
<row clause="C2a">
<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:105 — the prepared connection's Trending EXPLAIN QUERY PLAN names idx_trending_ranks_order. It is armed by :95 (main is empty) and by the full 50-row page check inside _plan at :104</assertion>
<expected>A detail like 'SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order'</expected>
<wrong_implementation>A temp copy of the ranks, or a view that loses the index. The plan reads 'SCAN t' with no index name, as the probe saw.</wrong_implementation>
</row>
<row clause="C2b">
<assertion>tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:106 — the prepared connection's Trending plan has no 'TEMP B-TREE' detail. The Popular plan control at :102 shows the capture can surface a sort</assertion>
<expected>No detail contains TEMP B-TREE</expected>
<wrong_implementation>An unindexed shadow table. It plans 'SCAN t' plus 'USE TEMP B-TREE FOR ORDER BY', as the probe saw.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Each negative assertion has a positive control. :106 (no TEMP B-TREE) is paired with :105, which needs the index, with :102, which shows the capture can see a sort, and with _plan's full-page check at :104. If the code under test is deleted, both tests fail with AttributeError at :31.
2. No. Every expected order and row set is a literal or is rebuilt from RANKS, not computed by the code under test. Deleting the shadowing of trending_ranks in attach_trending_override turns :84 and :85 red. Deleting the index creation in prepare_trending_override turns :105 red.
3. No. Each read is checked on two connections that should differ, plain and prepared. The two orders are proven to differ by :67, and the plain reads are checked both before and after the override.
4. No. There are no doubles. The test uses the real data.random_videos and data.trending, real SQLite files, and the project's own harness loaded by path.
5. Yes, it collects. This round I changed only one docstring line. The run collected 2 tests, and both failed at :31 on the missing helper.
6. Yes, they come from a run. Every expected order and plan detail was seen in the earlier probe. This round's edit is prose only.
7. Yes. After the edit, ValidateTests ["tests/tmp/test_44_trending_seed_write_lock_during_phase1.py", "-v"] gave 2 failed. Both raised `AttributeError: module 'data.trending' has no attribute 'prepare_trending_override'` at :31, reached from :72 and :96. That is the expected red before phase 1 is built.
None of the seven answers was a yes, so nothing was rewritten. The only edit is the D15 docstring narrowing.
</answers>

<exemptions>
none
</exemptions>

Gate: NOT SATISFIED - no assertion carries C1, C2

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - self-check table accepted by the operator

The gate on the reply was not satisfied: no assertion carries C1, C2

Accepted by the operator after 2 send-back(s), and the test goes to the auditors on that basis. The audit is NOT waived - both auditors still have to PASS, and the claim auditor enumerates every clause itself, so a clause this table does not carry comes back as an UNCARRIED row.

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - red (audit round 2)

`tests/tmp/test_44_trending_seed_write_lock_during_phase1.py` exited 1.

```
  tests/tmp/test_44_trending_seed_write_lock_during_phase1.py  2 failed                               0.0s
  -----------------------------------------------------------
  total                                                        2 failed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

The operator accepted a self-check shortfall to reach this point: no assertion carries C1, C2

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
In both tests the first call to `trending.prepare_trending_override` raises `AttributeError` at tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31 (`trending.prepare_trending_override(str(path))`). `engine/server/data/trending.py` defines only `ensure_trending_schema`. The first test gets there after its line 70 and 71 controls pass. The second gets there after its line 95 control passes. So no C1 or C2 assertion (lines 84–87, 105–106) is reached on the code as it stands.

NOT ASSESSED
1. `fixtures_path` was given as "none found". The test uses only the built-in `tmp_path`. Its harness is `tests/active/test_random_videos.py`, loaded by path, and I read it at lines 86–245 (`RANKS`, `TRENDING_EXPECTED`, `_schema`, `_ranks_db`, `_trending_labels`, `_plan`). I did not look for a `conftest.py` covering `tests/tmp/`, because no fixture is used that the test or that harness doesn't define.
2. `engine/server/data/random_videos.py` is not in `code_under_test`. I read only its `ORDERED_FEED_SOURCE` (lines 35–42) for the stub question. I did not check how `fetch_popular_videos` reaches `trending_ranks`.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | prepared conn: `fetch_ordered_page` "trending" serves the attached file's ranks | :84 | a plain ATTACH with no shadowing. That leaves `main.trending_ranks` in front, so the page comes back as the reverse order `TRENDING_EXPECTED` | CARRIED |
| C1b | must_prove | prepared conn: `fetch_popular_videos` serves the attached file's ranks | :85 | an override that reaches the page read but not the pool | CARRIED |
| C1c | must_prove | unprepared conn on the same main: Trending page serves main's ranks | :70, :86 | an override that writes main or changes the source for every connection. :86 reads after the prepared connection has read | CARRIED |
| C1d | must_prove | unprepared conn on the same main: popular pool serves main's ranks | :71 | a pool that does not read main's `trending_ranks` order | CARRIED |
| C1e | must_prove | main's ranks are left unchanged | :87 | a committed copy, delete or rewrite of `main.trending_ranks`. The expected rows are rebuilt from `RANKS` at :68 in the table's column order, not read back from the code | CARRIED |
| C2a | must_prove | prepared conn: Trending plan uses `idx_trending_ranks_order` | :105 (with `_plan`'s full-page check, `tests/active/test_random_videos.py:217`, at :104 and the empty-main control at :95) | a temp copy or view that loses the index. Main's empty table also has an index by this name, but only the file can supply a full 50-row page at offset 100 | CARRIED |
| C2b | must_prove | prepared conn: Trending plan has no `TEMP B-TREE` | :106 | an unindexed shadow that plans a SCAN plus USE TEMP B-TREE FOR ORDER BY | CARRIED |
| D1 | docstring | "a connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file" | :84, :85 | a plain ATTACH that reads main | CARRIED |
| D2 | docstring | "a plain connection on the same main reads main's" | :70, :71, :86 | an override that leaks to other connections | CARRIED |
| D3 | docstring | private file holds "the same keys ranked in `OVERRIDE_EXPECTED`", a different order | :67 | a fixture where the two orders match, which would let :84 and :85 pass on main's ranks | CARRIED |
| D4 | docstring | plain serves `TRENDING_EXPECTED` from both `fetch_ordered_page` and `fetch_popular_videos` | :70, :71 | either read ignoring main's ranks | CARRIED |
| D5 | docstring | prepared serves `OVERRIDE_EXPECTED` "from both" | :84, :85 | an override covering only one read | CARRIED |
| D6 | docstring | "the plain connection still serves `TRENDING_EXPECTED` afterwards" | :86 | an override that persists across connections | CARRIED |
| D7 | docstring | "`main.trending_ranks` holds exactly the rows written to it" | :87 | rows added to, removed from or rewritten in main | CARRIED |
| D8 | docstring | main DB "whose own `trending_ranks` is empty" | :95 | ranks present in main, which would let a plain ATTACH fill the page | CARRIED |
| D9 | docstring | ranks "written to a private file after `prepare_trending_override`" (file gets the schema and index) | :98 / :105 | a prepare that creates no table (the insert at :98 fails) or no index (:105 fails) | CARRIED |
| D10 | docstring | "the prepared connection reads a full Trending page from the file" | :104 (`_plan`, `tests/active/test_random_videos.py:217`) | a plain ATTACH that serves 0 rows from main's empty table | CARRIED |
| D11 | docstring | "its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order`" | :105 | a plan that skips the index | CARRIED |
| D12 | docstring | "and has no `TEMP B-TREE`" | :106 | a plan that sorts | CARRIED |
| D13 | docstring | "the same capture for Popular shows the temp B-tree (control)" | :102 | a plan capture that cannot show a sort, which would let :106 pass without testing anything | CARRIED |
| D14 | docstring | `_private_file`: "An empty file touched at `path`, then given the trending schema by `prepare_trending_override`" | :98 / :105 | a prepare that leaves the file without the schema or the index | CARRIED |
| D15 | docstring | withdrawn | n/a | n/a | CARRIED |
| N1 | name | test 1: "trending and the popular pool read main ranks without the override" | :70, :71, :86 | either read on the plain conn not serving main's order | CARRIED |
| N2 | name | test 1: "and the file's ranks with it" | :84, :85 | a plain ATTACH, or an override covering only one read | CARRIED |
| N3 | name | test 2: "a trending page on the override file" | :104 with control :95 | a page not served from the file (main is empty) | CARRIED |
| N4 | name | test 2: "walks its ranks index" | :105 | a plan without `idx_trending_ranks_order` | CARRIED |
| N5 | name | test 2: "without sorting" | :106 | a plan with `TEMP B-TREE` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:29
   D15 was resolved by narrowing the docstring, not by adding an assertion. The clause
   "`prepare_trending_override` ... never creates one" is gone. The docstring now reads
   "An empty file touched at `path`, then given the trending schema by
   `prepare_trending_override`." Nothing in the file checks whether prepare creates a
   missing file. The sentence was cut back to match the test.
2. whole-claim (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:86
   After the prepared connection has read, only the plain connection's Trending page is
   read again. Its popular pool is checked only at :71, before the override exists. An
   override that leaks into the pool path alone, on every connection, would not be caught
   after the fact. C1d and D6 are carried as written, so this is outside the ledger.
3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_44_trending_seed_write_lock_during_phase1.py:31, :38
   The round-one recommendation still stands: only the success path of each helper runs.
   No test calls `prepare_trending_override` or `attach_trending_override` on a missing,
   non-SQLite or empty override file. The author's record says this was left out because
   no clause specifies the failure behaviour.

NOT ASSESSED
1. `code_under_test` lists engine/server/data/trending.py (EDITED). As read, it still
   defines only `ensure_trending_schema` and has no `prepare_trending_override` or
   `attach_trending_override`. So the helpers' accepted inputs and failure behaviour could
   not be judged from the code. This is consistent with the test being red before the
   phase is implemented.
2. `fixtures_path` was "none found". The test uses no pytest fixture apart from
   `tmp_path`. Its harness (`_schema`, `_ranks_db`, `_plan`, `_trending_labels`, `RANKS`,
   `TRENDING_EXPECTED`) was read at tests/active/test_random_videos.py:86–240.
   `random_videos.fetch_ordered_page` and `fetch_popular_videos` are not in
   `code_under_test` and were not read.

## 2026-10-03 - Step 7 - Phase 1 (Trending override helpers) - checkpoint outcome (run 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/server/data/trending.py`
`ensure_trending_schema` is unchanged. Three additions sit next to it, following the plan's draft:
- `TRENDING_OVERRIDE_SCHEMA = "trending_override"`: the schema name the override file is attached under.
- `prepare_trending_override(path)`: opens `file:{path}?mode=rw` with `uri=True`, so a missing file is never created, runs `ensure_trending_schema` on it, and closes the connection. Any `sqlite3.Error` becomes `SystemExit` with a message that names the path. A `rat-tail:` comment records the limit: the path is not URI-escaped, so a `?` or `#` in it fails here, and the fix is `urllib.parse.quote`.
- `attach_trending_override(conn, path)`: runs `ATTACH DATABASE ? AS trending_override` with the path as a bound parameter, then `CREATE TEMP VIEW trending_ranks AS SELECT * FROM trending_override.trending_ranks`. One comment explains why the view is needed: SQLite looks up names in temp, then main, then attached databases, and it flattens the view. A `rat-tail:` comment records the race: on a non-URI connection, ATTACH would recreate a file deleted after the prepare step as an empty file.

What I saw in a probe (pytest's sqlite 3.53.4, the same version as the Engine's): with the override attached, the Trending query's plan is `SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order` followed by `SEARCH e USING COVERING INDEX ...`, with no `TEMP B-TREE`. `prepare_trending_override` on a missing path raised `SystemExit` naming the path and left no file there.

### `tests/active/test_random_videos.py`
Not edited. The checkpoint uses the harness (`_schema`, `_ranks_db`, `_plan`, `RANKS`, `TRENDING_EXPECTED`) exactly as it stands. Moving the checkpoint's two tests and docstring bullets into this file is test-side work, not production code.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_override_plan.py: a throwaway probe I wrote to check the query plan and the missing-path behaviour before handing in. My tools cannot delete files, so the operator needs to remove it. It fails on purpose with `assert False` so its printed output is shown, and it is not part of the build.
tests/last_test_output.txt and tests/last_test_validation.json: running that probe through `ValidateTests` overwrote both files with the probe's output. The workflow's checkpoint run will overwrite them again.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_44_trending_seed_write_lock_during_phase1.py  2 passed                               0.0s
  -----------------------------------------------------------
  total                                                        2 passed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 2 (Engine --trending-db flag) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`engine/server/api/server.py` accepts `--trending-db PATH`. `main()` validates PATH before it opens `whitelist.db`, so a PATH that is not an existing SQLite file stops the start, with a message naming it, and leaves the path as it was.

- C1 - Starting `server.py` with `--trending-db` on a missing path or a non-SQLite file exits non-zero, with that path in stderr.
- C2 - The failed start leaves the path as it was: a missing path is not created, and a non-SQLite file's bytes are unchanged.

must_prove:
- C1 - Starting `server.py` with `--trending-db` on a missing path or a non-SQLite file exits non-zero, with that path in stderr.
- C2 - The failed start leaves the path as it was: a missing path is not created, and a non-SQLite file's bytes are unchanged.

## 2026-10-03 - Step 7 - Phase 2 (Engine --trending-db flag) - self-check (audit round 1, send-back 0)

`tests/tmp/test_44_trending_seed_write_lock_during_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_44_trending_seed_write_lock_during_phase2.py:42, :43, :45 — for the missing `absent.db`: `run.returncode != 0`, `str(missing) in run.stderr`, and `"unrecognized arguments" not in run.stderr` - expected: Under the right implementation the start exits non-zero, stderr names the absent path, and argparse has accepted `--trending-db`, so its "unrecognized arguments" rejection is not in stderr. I could only partly observe this. The run showed :42 and :43 already true today, because argparse rejects the unknown flag with exit 2 and quotes the path. It showed :45 red today, on the stderr text "server.py: error: unrecognized arguments: --trending-db /tmp/.../absent.db". How stderr reads once the phase is built is a prediction until the phase runs. - excludes: If the flag is never added (today's code), :45 goes red with the stderr above. If the flag is added but the path is not checked, the server binds the free port and serves, so `_run` raises TimeoutExpired after 120 s and the test goes red. If the check fails with a message that leaves out the path (for example a bare "trending db invalid"), :43 goes red.
- C1 - test_44_trending_seed_write_lock_during_phase2.py:51, :52, :53 — the same three assertions for the 4096-byte non-SQLite `junk.db` - expected: Non-zero exit, the junk path in stderr, and no "unrecognized arguments". This is predicted, not observed: this run stopped at :45 and never got here. - excludes: A check that only tests `Path.exists()` passes the junk file, so the server starts and `_run` times out after 120 s, raising TimeoutExpired. A check that runs `sqlite3.connect` without a query also gets past, because `connect` does not read the header, so the result is the same. If the "file is not a database" error is raised without the path in it, :52 goes red.
- C2 - test_44_trending_seed_write_lock_during_phase2.py:46 — `not missing.exists()` after the failed start on `absent.db` - expected: False: the path is still absent. This is predicted for the built phase; the run stopped at :45 before reaching :46. - excludes: A check that calls `sqlite3.connect(path)` (or `ensure_trending_schema`) before validating creates an empty `absent.db`. The start might still exit non-zero, but `missing.exists()` is then True and :46 goes red.
- C2 - test_44_trending_seed_write_lock_during_phase2.py:54 — `junk.read_bytes() == JUNK` after the failed start on `junk.db` - expected: The file still holds exactly the 4096 bytes written at :49. This is predicted; the run did not reach :54. - excludes: An implementation that recovers by recreating or initialising the file (unlinking and re-creating it, or writing a schema over it) would leave different bytes or an empty file, so :54 goes red.

<assertions>
test_44_trending_seed_write_lock_during_phase2.py:35 — control: `server.py --help` under the Engine interpreter exits 0, so the entry point runs.
test_44_trending_seed_write_lock_during_phase2.py:36 — control: `--help` stdout contains `--trending-db PATH`, so the flag is parsed. This is the line that is red now, which is correct: before the change the usage has no such flag.
test_44_trending_seed_write_lock_during_phase2.py:40 — missing `tmp_path / "absent.db"`: start exits non-zero. Excludes an implementation that warns and returns 0. One that warns and keeps going binds a free port and raises TimeoutExpired at `_run`'s 120 s, so it goes red rather than hanging. — C1
test_44_trending_seed_write_lock_during_phase2.py:41 — missing case: `str(missing)` is in stderr. Excludes a failure that does not name the path. — C1
test_44_trending_seed_write_lock_during_phase2.py:43 — missing case: "unrecognized arguments" is not in stderr. Excludes the unchanged code, which was observed to exit 2 and put the path in stderr through argparse's rejection, and so would satisfy :40–41 on its own. — C1
test_44_trending_seed_write_lock_during_phase2.py:44 — missing case: `absent.db` does not exist after the start. Excludes a check that opens the path with sqlite3 and so creates it. — C2
test_44_trending_seed_write_lock_during_phase2.py:49 — `junk.db` (4096 literal non-SQLite bytes): start exits non-zero. — C1
test_44_trending_seed_write_lock_during_phase2.py:50 — junk case: `str(junk)` is in stderr. — C1
test_44_trending_seed_write_lock_during_phase2.py:51 — junk case: "unrecognized arguments" is not in stderr. This excludes the unchanged code, the same way as :43. — C1
test_44_trending_seed_write_lock_during_phase2.py:52 — junk case: `junk.read_bytes() == JUNK`, the literal written. Excludes an implementation that re-initialises, truncates or replaces a non-SQLite file. — C2
</assertions>

<probes>
I wrote tests/tmp/probe_trending_db_flag.py, ran it with ValidateTests ["tests/tmp/probe_trending_db_flag.py", "-s"], and read tests/last_test_output.txt.
- Loading tests/active/test_server_config.py by path from tests/tmp works once tests/active is put on sys.path, because it needs `conftest`.
- tmp_path == tmp_path.resolve() was True (/tmp/pytest-of-enduser/...), so `str(path)` is the same string the Engine would print.
- With the current code, `server.py --help` exits 0 and the usage has no `--trending-db PATH`.
- With the current code, `server.py --host 127.0.0.1 --port 1 --trending-db <tmp>/absent.db` gave rc 2, absent.db still missing, and stderr "server.py: error: unrecognized arguments: --trending-db /tmp/pytest-of-enduser/pytest-9799/test_probe0/absent.db".
- The same run on a 4096-byte junk.db gave rc 2, size still 4096, and stderr "unrecognized arguments: --trending-db .../junk.db".
- Conclusion: the unchanged code satisfies the plain C1/C2 assertions. That is why the "unrecognized arguments" negatives at :43 and :51 are there.
I then ran ValidateTests ["tests/tmp/test_44_trending_seed_write_lock_during_phase2.py"]: 1 failed, at :36, with `--trending-db PATH` absent from the `--help` usage. That is the expected red before implementation.
The probe file tests/tmp/probe_trending_db_flag.py still needs deleting, and I have no tool that removes files. Please remove it; the checkpoint now carries everything it showed.
</probes>

<unassertable>
none. C1 and C2 are both carried, in the missing and the non-SQLite cases. Not asserted, because neither is a clause: (a) the intent's "validates before it opens whitelist.db" ordering, which the subprocess cannot observe without coupling to log lines; (b) the tests/config.json `test_server_config.py` group gaining engine/server/data/trending.py, which is a config edit outside this file.
</unassertable>

### `tests/tmp/test_44_trending_seed_write_lock_during_phase2.py` - 2839 characters, inlined in full

```
"""`server.py --trending-db PATH`, run by the Engine's own interpreter, stops the start on a PATH that is not an existing SQLite file:

- Control: `server.py --help` exits 0 and its usage lists `--trending-db PATH`.
- A missing `absent.db` and a 4 KB `junk.db` of non-SQLite bytes each make the start exit non-zero, with that path in stderr and not as argparse's "unrecognized arguments".
- After the failed start `absent.db` still does not exist, and `junk.db` holds exactly the bytes written to it.

`_run` and `_free_port` are the harness in `tests/active/test_server_config.py`, loaded by path so its tests are not collected here. A start that wrongly gets past the check binds a free port and serves until `_run`'s 120 s timeout, which raises instead of hanging.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
# test_server_config does `from conftest import ...`, and tests/active/conftest.py is not on this directory's path.
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
_HARNESS_SPEC = importlib.util.spec_from_file_location("server_config_harness", ACTIVE_DIR / "test_server_config.py")
harness = importlib.util.module_from_spec(_HARNESS_SPEC)
_HARNESS_SPEC.loader.exec_module(harness)

SERVER_PY = harness.API_DIR / "server.py"
# Not the SQLite header ("SQLite format 3\0"), 4096 bytes.
JUNK = (b"not a sqlite database\n" * 200)[:4096]


def _start(trending_db: Path):
    return harness._run([str(harness.ENGINE_PY), str(SERVER_PY), "--host", "127.0.0.1", "--port", str(harness._free_port()), "--no-random-cache-refresh", "--trending-db", str(trending_db)], None)


def test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it(tmp_path):
    ok = harness._run([str(harness.ENGINE_PY), str(SERVER_PY), "--help"], None)
    assert ok.returncode == 0, ok.stderr[-2000:]  # control: the entry point runs in this interpreter
    assert "--trending-db PATH" in ok.stdout, ok.stdout[-2000:]  # control: and parses the flag

    missing = tmp_path / "absent.db"
    run = _start(missing)
    assert run.returncode != 0, run.stderr[-2000:]  # C1
    assert str(missing) in run.stderr, run.stderr[-2000:]  # C1
    # Observed before the flag existed: exit 2 with the path in stderr, quoted by argparse's rejection.
    assert "unrecognized arguments" not in run.stderr, run.stderr[-2000:]  # C1
    assert not missing.exists()  # C2

    junk = tmp_path / "junk.db"
    junk.write_bytes(JUNK)
    run = _start(junk)
    assert run.returncode != 0, run.stderr[-2000:]  # C1
    assert str(junk) in run.stderr, run.stderr[-2000:]  # C1
    assert "unrecognized arguments" not in run.stderr, run.stderr[-2000:]  # C1
    assert junk.read_bytes() == JUNK  # C2

```


Gate: satisfied

## 2026-10-03 - Step 7 - Phase 2 (Engine --trending-db flag) - red (audit round 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase2.py` exited 1.

```
  tests/tmp/test_44_trending_seed_write_lock_during_phase2.py  1 failed                               0.0s
  -----------------------------------------------------------
  total                                                        1 failed                               0.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 2 (Engine --trending-db flag) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - BLOCK
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: devsecops-test-shape-auditor: critical

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: BLOCK

CRITICAL
1. Stub question (rules/shape.md, answered under `single-value-pin <alternatives>`) — tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:42-43, 51-52
   assert run.returncode != 0, run.stderr[-2000:]  # C1
   assert str(missing) in run.stderr, run.stderr[-2000:]  # C1
   The test only tries `--trending-db` with inputs that must be rejected: a missing path and a junk file. It never passes a path that must get through the check. So an implementation that adds the flag and always rejects its value passes every assertion. For example, `parser.error(f"--trending-db {args.trending_db}: not a SQLite file")` with no condition exits non-zero, puts the path in stderr without "unrecognized arguments", and creates or changes no file. The test reads one kind of outcome. The rule requires two inputs that must produce different results, and an assertion on the difference ("Run the observable twice, at two inputs that must produce different readings"). One way to add that: start once with a valid SQLite file, and check that the start does not fail with that path in stderr, or that it gets past the check (end it with `Popen` and terminate rather than `_run`'s 120 s timeout). The test would then fail if the check were hard-coded.

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at line 45 on `assert "unrecognized arguments" not in run.stderr`. `parse_args` in engine/server/api/server.py (lines 153-203) has no `--trending-db` argument yet, so argparse exits 2 with "unrecognized arguments: --trending-db <tmp>/absent.db" in stderr. That output also satisfies lines 42-43, so 45 is the first assertion to fail.

NOT ASSESSED
1. `fixtures_path` was not supplied. I checked by Grep that tests/active/conftest.py defines `ENGINE_PY`, `ROOT` and `_free_port` (the harness imports them), but I did not read `_free_port`'s body.
2. tests/config.json is listed in `code_under_test` and was not read. Nothing in the test refers to it, so no shape check depends on it.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (17 clauses: 8 must_prove, 6 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | missing path → start exits non-zero | :42 | a start that accepts a missing path and serves (the `_run` timeout raises), or exits 0 | CARRIED |
| C1b | must_prove | missing path → "that path in stderr" | :43, :45 | a failure that never names the path; :45 rules out the path appearing only because argparse quoted it while rejecting the flag | CARRIED |
| C1c | must_prove | non-SQLite file → start exits non-zero | :51 | a start that opens or accepts a non-SQLite file without complaint | CARRIED |
| C1d | must_prove | non-SQLite file → "that path in stderr" | :52, :53 | a generic "file is not a database" error with no path; argparse quoting the path while rejecting the flag | CARRIED |
| C2a | must_prove | "a missing path is not created" | :46 | a check that runs after `sqlite3.connect` or schema setup has already created the file | CARRIED |
| C2b | must_prove | "a non-SQLite file's bytes are unchanged" | :54 | overwriting, truncating or re-initialising the junk file before rejecting it (exact equality against all 4096 written bytes) | CARRIED |
| C1-path | must_prove | the flag reaches `server.py --trending-db` (not rejected by argparse) | :45, :53 against controls :37–:38 | treating argparse's exit 2 for an unknown flag as the required failure | CARRIED |
| C1-entry | must_prove | "Starting `server.py`": the real entry point | :41, :50 via :30 | an in-process helper standing in for the CLI start; the real script runs as a subprocess | CARRIED |
| D1 | docstring | "`server.py --help` exits 0" (control) | :35 | an entry point that does not run in this interpreter, which would make every non-zero exit below meaningless | CARRIED |
| D2 | docstring | "unknown flag exits 2 with 'unrecognized arguments' in stderr" | :37, :38 | the absence checks at :45/:53 passing because the wording never reaches the captured stderr | CARRIED |
| D3 | docstring | "absent.db and a 4 KB junk.db each … exit non-zero, with that path in stderr and not as argparse's 'unrecognized arguments'" | :42–:45, :51–:53 | as C1a–C1d | CARRIED |
| D4 | docstring | "absent.db still does not exist" | :46 | as C2a | CARRIED |
| D5 | docstring | "junk.db holds exactly the bytes written to it" | :54 | as C2b | CARRIED |
| D6 | docstring | "A start that wrongly gets past the check … raises instead of hanging" | :41, :50 (`_run` timeout=120, test_server_config.py:52) | a start that serves forever: `TimeoutExpired` from `_run` fails the test | CARRIED |
| N1 | name | "a trending db that is missing … stops the start" | :42 | as C1a | CARRIED |
| N2 | name | "… or not sqlite stops the start" | :51 | as C1c | CARRIED |
| N3 | name | "naming it" | :43, :52 | as C1b, C1d | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:48
   The test only uses two rejected inputs: a missing file and a 4 KB file of non-SQLite bytes. It never tests the edges of "not an existing SQLite file": a zero-byte file (SQLite opens it as a valid empty database), a directory at the path, a file that starts with the SQLite header but is truncated, or a path whose parent directory is missing. Each of these could be accepted or rejected by mistake, and this test would not show it.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:33
   Only the failure path runs. Nothing here shows that `--trending-db` pointing at a valid SQLite file gets past the check. A check that rejects every path would pass this test. That success case is not in `must_prove`, so this does not block, but this file alone does not show the behaviour has a normal path.
3. name-as-sentence (rules/testing.md) — tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:1
   The function name reads as a correct sentence. The module name, `test_44_trending_seed_write_lock_during_phase2`, describes a different behaviour (a write lock during the seed). The runner prints `file::function` on failure, so the first half of what a reader sees describes something this test does not check.

OBSERVATIONS
none

NOT ASSESSED
1. `fixtures_path` was not supplied. The test uses only the built-in `tmp_path`, plus `ENGINE_PY`, `ROOT` and `_free_port`. It gets those through `tests/active/test_server_config.py:39`, which imports them from `tests/active/conftest.py`. I did not read that conftest, so I have not checked independence for `_free_port`'s port selection.
2. `engine/server/api/server.py` has no `--trending-db` argument and no path check in `parse_args` (:153–203) or `main` (:285–). I judged bounds from what `must_prove` and the docstring say should be accepted and rejected, not from the code's own validation, because that validation is not there.
3. `tests/config.json` (in `code_under_test`) was only searched for references to this test and to trending. It maps test files to the source files they cover and has no bearing on what this test asserts.

## 2026-10-03 - Step 7 - Phase 2 (Engine --trending-db flag) - self-check (audit round 2, send-back 0)

`tests/tmp/test_44_trending_seed_write_lock_during_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_44_trending_seed_write_lock_during_phase2.py:67, :68, :70: for the missing `absent.db`, `run.returncode != 0`, `str(missing) in run.stderr`, and `"unrecognized arguments" not in run.stderr` (armed by the controls at :62–:63) - expected: A non-zero exit, with stderr naming the absent path through the Engine's own SystemExit message and not through argparse's rejection. This is predicted. Today :67–:68 hold only because argparse rejects the flag; that was observed. - excludes: With the flag never added (today's code), :70 goes red. Observed: stderr "server.py: error: unrecognized arguments: --trending-db /tmp/.../absent.db", and the test currently fails at :70. With the flag added but no check, the server serves and `_run` raises TimeoutExpired at 120 s. With a check whose message leaves out the path, :68 goes red.
- C1 - test_44_trending_seed_write_lock_during_phase2.py:76, :77, :78: the same three assertions for the 4096-byte non-SQLite `junk.db` - expected: A non-zero exit, with the junk path in stderr and no "unrecognized arguments". This is predicted, because the run stops at :70 today. - excludes: A check that only tests `Path.exists()`, or a bare `sqlite3.connect` with no query, lets the junk file through. The server then serves, and `_run` times out and raises. A generic "file is not a database" message with no path makes :77 go red.
- C1 - test_44_trending_seed_write_lock_during_phase2.py:88: `_starts_serving(valid, log_path)`. An existing SQLite file passed as `--trending-db` reaches the Engine's `service.lifecycle` start within 120 s. - expected: True: the check passes it and the Engine serves. Observed on today's code without the flag: the same Popen and `_has_started` loop reached the lifecycle start in about 1.1 s, and terminate gave rc 0. Also observed: today, with the flag, this start exits 2 with "unrecognized arguments: --trending-db .../valid.db". That the built flag reaches the start on this file is predicted. - excludes: A check that rejects every PATH, for example an unconditional `parser.error(f"--trending-db {path}: not a SQLite file")`. It satisfies :67–:79 but exits before the lifecycle start, so `_has_started` is False and :88 goes red, showing the log tail.
- C2 - test_44_trending_seed_write_lock_during_phase2.py:71: `not missing.exists()` after the failed start - expected: True: `absent.db` is never created. Today this is true because argparse exits first (observed); after the build it is predicted. - excludes: A check that runs a plain `sqlite3.connect(path)`, or uses `mode=rwc`, before rejecting. That creates `absent.db`, so :71 goes red.
- C2 - test_44_trending_seed_write_lock_during_phase2.py:79: `junk.read_bytes() == JUNK`, the 4096-byte literal that was written - expected: The file's bytes are exactly the bytes written. - excludes: An implementation that truncates, re-initialises or replaces a non-SQLite file before or instead of rejecting it, for example by deleting it and recreating the schema. The bytes then differ, so :79 goes red.

<items>
none
</items>

<findings_addressed>
Shape CRITICAL 1 (stub question: only rejected inputs, so an always-reject check passes): added a valid-SQLite case at :82–:88. `valid.db` is created with sqlite3 and holds one placeholder table. `_starts_serving` (:41–:55) Popens the real `server.py --trending-db valid.db` under `ENGINE_START_LOCK`, the same way `_start_variant` does. It polls until `harness._has_started` (the `service.lifecycle` start) or 120 s, then terminates. :88 asserts that the start was reached. An unconditional `parser.error(...)` or any check that rejects every PATH exits before the lifecycle start, so :88 goes red. The two rejected inputs and this accepted input now must produce different outcomes.
Claim recommendation 2 (no normal path): taken. It is the same valid-SQLite case at :88, and the docstring gains a bullet for it.
Claim recommendations 1 (more boundary inputs) and 3 (module name): left. A zero-byte file is accepted by the planned `mode=rw` + `ensure_trending_schema` check, and it is not in must_prove. The module filename is assigned by the workflow, not by me.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>test_44_trending_seed_write_lock_during_phase2.py:67, :68, :70: for the missing `absent.db`, `run.returncode != 0`, `str(missing) in run.stderr`, and `"unrecognized arguments" not in run.stderr` (armed by the controls at :62–:63)</assertion>
<expected>A non-zero exit, with stderr naming the absent path through the Engine's own SystemExit message and not through argparse's rejection. This is predicted. Today :67–:68 hold only because argparse rejects the flag; that was observed.</expected>
<wrong_implementation>With the flag never added (today's code), :70 goes red. Observed: stderr "server.py: error: unrecognized arguments: --trending-db /tmp/.../absent.db", and the test currently fails at :70. With the flag added but no check, the server serves and `_run` raises TimeoutExpired at 120 s. With a check whose message leaves out the path, :68 goes red.</wrong_implementation>
</row>
<row clause="C1">
<assertion>test_44_trending_seed_write_lock_during_phase2.py:76, :77, :78: the same three assertions for the 4096-byte non-SQLite `junk.db`</assertion>
<expected>A non-zero exit, with the junk path in stderr and no "unrecognized arguments". This is predicted, because the run stops at :70 today.</expected>
<wrong_implementation>A check that only tests `Path.exists()`, or a bare `sqlite3.connect` with no query, lets the junk file through. The server then serves, and `_run` times out and raises. A generic "file is not a database" message with no path makes :77 go red.</wrong_implementation>
</row>
<row clause="C1">
<assertion>test_44_trending_seed_write_lock_during_phase2.py:88: `_starts_serving(valid, log_path)`. An existing SQLite file passed as `--trending-db` reaches the Engine's `service.lifecycle` start within 120 s.</assertion>
<expected>True: the check passes it and the Engine serves. Observed on today's code without the flag: the same Popen and `_has_started` loop reached the lifecycle start in about 1.1 s, and terminate gave rc 0. Also observed: today, with the flag, this start exits 2 with "unrecognized arguments: --trending-db .../valid.db". That the built flag reaches the start on this file is predicted.</expected>
<wrong_implementation>A check that rejects every PATH, for example an unconditional `parser.error(f"--trending-db {path}: not a SQLite file")`. It satisfies :67–:79 but exits before the lifecycle start, so `_has_started` is False and :88 goes red, showing the log tail.</wrong_implementation>
</row>
<row clause="C2">
<assertion>test_44_trending_seed_write_lock_during_phase2.py:71: `not missing.exists()` after the failed start</assertion>
<expected>True: `absent.db` is never created. Today this is true because argparse exits first (observed); after the build it is predicted.</expected>
<wrong_implementation>A check that runs a plain `sqlite3.connect(path)`, or uses `mode=rwc`, before rejecting. That creates `absent.db`, so :71 goes red.</wrong_implementation>
</row>
<row clause="C2">
<assertion>test_44_trending_seed_write_lock_during_phase2.py:79: `junk.read_bytes() == JUNK`, the 4096-byte literal that was written</assertion>
<expected>The file's bytes are exactly the bytes written.</expected>
<wrong_implementation>An implementation that truncates, re-initialises or replaces a non-SQLite file before or instead of rejecting it, for example by deleting it and recreating the schema. The bytes then differ, so :79 goes red.</wrong_implementation>
</row>
</rows>

<answers>
1. No. The "unrecognized arguments" absence checks at :70 and :78 are armed by the positive control at :62–:63. The new :88 is a positive reading, the lifecycle start. If the code under test is deleted (no flag), :70 is red. I observed this: the test fails there now.
2. No. Nothing compares a value to itself. The JUNK literal at :79 is the input, not something production computes. Deleting the path from the SystemExit message turns :68/:77 red. Deleting the validation lets junk.db through, so the server serves and `_run` raises TimeoutExpired. Making the check unconditional turns :88 red.
3. Previously yes: only rejected inputs were read. That was the shape CRITICAL. I rewrote the test to add the accepted `valid.db` case at :82–:88, which must produce a different outcome (the lifecycle start) from the two rejected inputs.
4. No. There are no doubles. The real `server.py` runs as a subprocess under the Engine interpreter.
5. Yes, it collects. The new imports are fcntl, sqlite3, subprocess and time. `harness.ENGINE_START_LOCK`, `harness.VARIANT_START_SECONDS`, `harness._has_started`, `harness.API_DIR`, `harness._free_port` and `harness.ENGINE_PY` all exist in test_server_config.py; I read them, and the probe used them. The run collected 1 test, which is the count written.
6. Yes, for what can be seen today. I ran a probe, tests/tmp/probe_valid_start.py. It showed that a sqlite3-created file has the header b'SQLite format 3\x00'. It showed that the Popen + `_has_started` loop under the start lock reaches the lifecycle start in about 1.1 s and terminates with rc 0. It showed that today `--trending-db valid.db` exits 2 with "unrecognized arguments". It cannot show that the built flag reaches the start on valid.db, because that code does not exist yet. That remains a prediction, and the Phase 2 green run will confirm it. Please delete tests/tmp/probe_valid_start.py and the earlier tests/tmp/probe_trending_db_flag.py. I have no tool that removes files, and the checkpoint now carries what they showed.
7. Yes, it is still red for its own reason. ValidateTests failed at :70 with stderr "server.py: error: unrecognized arguments: --trending-db /tmp/.../absent.db", meaning the flag is not built yet. There was no typo, import error or fixture failure.
</answers>

<exemptions>
none
</exemptions>

Gate: satisfied

## 2026-10-03 - Step 7 - Phase 2 (Engine --trending-db flag) - red (audit round 2)

`tests/tmp/test_44_trending_seed_write_lock_during_phase2.py` exited 1.

```
  tests/tmp/test_44_trending_seed_write_lock_during_phase2.py  1 failed                               0.0s
  -----------------------------------------------------------
  total                                                        1 failed                               0.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 2 (Engine --trending-db flag) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
The test fails at line 70 (`assert "unrecognized arguments" not in run.stderr`) on the missing-path start. `parse_args()` in engine/server/api/server.py (lines 153–203) does not define `--trending-db`, so argparse exits 2 with the error "unrecognized arguments: --trending-db <tmp>/absent.db". That output already satisfies lines 67 and 68, so line 70 is the first assertion to fail.

NOT ASSESSED
1. `fixtures_path` was not supplied. The test defines no pytest fixture beyond the built-in `tmp_path`. It loads its harness by path from tests/active/test_server_config.py, which I read. That module imports `ENGINE_PY`, `ENGINE_SERVER`, `ENGINE_START_LOCK`, `ROOT` and `_free_port` from tests/active/conftest.py. I did not read that conftest. The audit takes those names as resolving to what the harness uses them for.
2. tests/config.json is listed in `code_under_test`, but the test never references it, so I did not read it. Nothing in the shape assessment depends on it.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (17 clauses: 8 must_prove, 6 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | missing path → start exits non-zero | :67 | a start that accepts a missing path and serves (the `_run` timeout raises), or exits 0 | CARRIED |
| C1b | must_prove | missing path → "that path in stderr" | :68, :70 | a failure that never names the path; :70 rules out the path showing up only because argparse quoted it while rejecting the flag | CARRIED |
| C1c | must_prove | non-SQLite file → start exits non-zero | :76 | a start that opens or accepts a non-SQLite file without complaint | CARRIED |
| C1d | must_prove | non-SQLite file → "that path in stderr" | :77, :78 | a generic "file is not a database" error with no path; argparse quoting the path while rejecting the flag | CARRIED |
| C2a | must_prove | "a missing path is not created" | :71 | a check that runs after `sqlite3.connect` or schema setup has already created the file | CARRIED |
| C2b | must_prove | "a non-SQLite file's bytes are unchanged" | :79 | overwriting, truncating or re-initialising the junk file before rejecting it (exact equality against all 4096 bytes from :31) | CARRIED |
| C1-path | must_prove | the flag reaches `server.py --trending-db` (not rejected by argparse) | :70, :78 against controls :62–:63 | treating argparse's exit 2 for an unknown flag as the required failure | CARRIED |
| C1-entry | must_prove | "Starting `server.py`": the real entry point | :67, :76 via :66, :75 and `_argv` :35 | an in-process helper standing in for the CLI start; `ENGINE_PY server.py` runs as a subprocess | CARRIED |
| D1 | docstring | "`server.py --help` exits 0" (control) | :60 | an entry point that does not run in this interpreter, which would make every non-zero exit below meaningless | CARRIED |
| D2 | docstring | "unknown flag exits 2 with 'unrecognized arguments' in stderr" | :62, :63 | the absence checks at :70/:78 passing because the wording never reaches captured stderr | CARRIED |
| D3 | docstring | "absent.db and a 4 KB junk.db each … exit non-zero, with that path in stderr and not as argparse's 'unrecognized arguments'" | :67–:70, :76–:78 | as C1a–C1d | CARRIED |
| D4 | docstring | "absent.db still does not exist" | :71 | as C2a | CARRIED |
| D5 | docstring | "junk.db holds exactly the bytes written to it" | :79 | as C2b | CARRIED |
| D6 | docstring | "A start that wrongly gets past the check … raises instead of hanging" | :66, :75 (`_run` timeout=120, test_server_config.py:52) | a start that serves forever: `TimeoutExpired` from `_run` fails the test | CARRIED |
| N1 | name | "a trending db that is missing … stops the start" | :67 | as C1a | CARRIED |
| N2 | name | "… or not sqlite stops the start" | :76 | as C1c | CARRIED |
| N3 | name | "naming it" | :68, :77 | as C1b, C1d | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:6, :88
   The docstring has a new clause since the first audit that no ledger row names: "An existing SQLite `valid.db` gets past the check: the start, under the Engine start lock, reaches its `service.lifecycle` start within 120 s and is then terminated."
   - `assert _starts_serving(valid, log_path)` at :88 carries it.
   - The lock is taken at :45–:46, the poll is bounded by `VARIANT_START_SECONDS` (120) at :49–:50, and the process is terminated at :54.
   - This assertion rules out a check that rejects every path, so it is a real addition, not prose drift. It is the success-path counterpart that `normal-and-abnormal-paths` asks for.
   - The line comment at :88 tags it `# C1`, but neither C1 nor C2 claims a valid path is accepted. Any later map should give it its own docstring row rather than read it as part of C1.
2. No rule in testing.md covers this; recorded only — tests/tmp/test_44_trending_seed_write_lock_during_phase2.py:1
   The file name (`trending_seed_write_lock_during_phase2`) describes something other than what the file tests. `name-as-sentence` applies to the test name at :58, which is accurate, so this is outside the criteria.

NOT ASSESSED
1. `code_under_test` lists engine/server/api/server.py, tests/active/test_server_config.py and tests/config.json.
   - tests/config.json was not read: the test does not reference it.
   - server.py was searched only for `trending`, so no `--trending-db` behaviour was read. That bears on the implementation, not on the claim audit.
2. `fixtures_path` was not supplied. The test defines no pytest fixture other than the built-in `tmp_path`.
   - The harness symbols it uses resolve in two places: `_run`, `_has_started`, `API_DIR` and `VARIANT_START_SECONDS` in tests/active/test_server_config.py, and `ENGINE_PY`, `ENGINE_START_LOCK` and `_free_port` in tests/active/conftest.py.
   - All seven were confirmed to exist. Only `_run`, `_has_started` and the constants were read in full.

## 2026-10-03 - Step 7 - Phase 2 (Engine --trending-db flag) - checkpoint outcome (run 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase2.py` exited 0 after the phase landed.

<changes>
### `engine/server/api/server.py`
- The import from `data.trending` now also brings in `attach_trending_override` and `prepare_trending_override`. Phase 1 added both to `trending.py`, so they are reused here as they are.
- `parse_args` gains `--trending-db` with `metavar="PATH"` and `default=None`, written in the file's `help=(...)` style. It sits after the `refresh_group` block and before `set_defaults`. The help text says four things: it is a dev/test override; only `trending_ranks` is read from PATH; PATH must be an existing SQLite file (an empty file counts) and is never created, though the table and index are created in it if missing; a relative PATH resolves against the working directory.
- In `main()`, when the flag is set, `prepare_trending_override(args.trending_db)` runs before `connect_db(db_path)`. So a missing path or a non-SQLite file stops the start before `whitelist.db` is opened, the index is loaded or anything binds. It exits non-zero through `SystemExit`, with a message naming the path. The `mode=rw` open creates no file.
- `ensure_trending_schema(db)` now runs only when the flag is absent. That branch is the original line and comment, unchanged. When the flag is set, `attach_trending_override(db, args.trending_db)` runs in the same place. That is after the two `executescript` ensures, which commit, so the ATTACH never runs inside a transaction. The shared `trending_ranks` is then neither created nor read on `server.db`.
- The attach is wired in this phase because `server.py` is not in Phase 3's file list, and a flag that validates PATH but is never read would do nothing.
- The plan's optional `trending_db=` startup log line is left out: no test or requirement needs it.

### `tests/active/test_server_config.py`
Not edited. Moving the checkpoint test into this file is test-side work for the promotion step, the same split Phase 1 used. Production code alone is enough to turn the checkpoint green.

### `tests/config.json`
Not edited, for the same reason. Adding `engine/server/data/trending.py` to the `test_server_config.py` group goes with promoting the test into that file. Changing the group mid-build would also change the fingerprint the workflow is gating on.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_44_trending_seed_write_lock_during_phase2.py  1 passed                               0.0s
  -----------------------------------------------------------
  total                                                        1 passed                               2.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 3 (Active suite on a private Trending seed) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The active suite's session Engine reads Trending from a per-session private file. `trending_seed` builds that file from the read-only shared catalogue, `engine` passes it as `--trending-db`, and `dataset` carries it, so the suite serves the seeded order without ever writing the shared `whitelist.db` `trending_ranks`.

- C1 - The session Engine's Trending pages and its popular-layer rows follow the private seed file's ranks, not the shared table's.
- C2 - The shared `whitelist.db` `trending_ranks` fingerprint (row count, `fetched_at` min and max, rows with `fetched_at > 0`) is identical before the seed and after the session Engine has served.

must_prove:
- C1 - The session Engine's Trending pages and its popular-layer rows follow the private seed file's ranks, not the shared table's.
- C2 - The shared `whitelist.db` `trending_ranks` fingerprint (row count, `fetched_at` min and max, rows with `fetched_at > 0`) is identical before the seed and after the session Engine has served.

## 2026-10-03 - Step 7 - Phase 3 (Active suite on a private Trending seed) - self-check (audit round 1, send-back 0)

`tests/tmp/test_44_trending_seed_write_lock_during_phase3.py`, surface `checkpoint`. Collection exit 2.

- C1 - tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:80 — three `mode=trending` pages from the session Engine (limit FEED_PAGE, each page excluding the rows served before it) concatenate to `_reference(dataset, "trending", threshold)[: 3 * FEED_PAGE]`, the private seed's order read through `dataset` with its private view. Armed by :67 (the private order holds three pages) and :70 (the shared head differs from the private head). - expected: The 36 keys of the private seed's Trending head, in order. Predicted, not observed: the run stopped at :55 on the missing fixture. The comment's figure of 7 of 36 head keys shared between the shared and private orders comes from the authoring turn's probe. I did not re-run it this turn. - excludes: An Engine started without `--trending-db`, or with a flag that never shadows `trending_ranks` on `server.db`, serves the shared table's real-fill head. Under that, the three pages are the shared order, which :70 shows differs from the reference, so :80 goes red. If the seed file is empty, the pages come back empty and :80 also goes red.
- C1 - tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:87 — every `debug.layer == "popular"` row of an unseeded `POST /recommendations?limit=2*BATCH_SIZE&debug=1` is in `fetch_popular_videos(dataset, POOL)`, the private pool under the Engine's threshold and the default NSFW filter. Armed by :85 (at least one popular row is served) and :73 (at least a quarter of the shared pool lies outside the private pool). - expected: `outside == []`: each of the roughly 20 popular rows is in the private pool. Predicted, not observed this turn; the run stopped at :55. The comment's figures (3003 of the shared pool's 5000 rows outside the private pool, and 4 to 10 popular rows a request also in the shared pool) are from the authoring turn's probes. - excludes: If the override reaches `fetch_ordered_page` but not the popular pool's `fetch_popular_videos(server.db, ...)`, or the Engine is started without the flag, popular rows are drawn from the shared pool. With 3003 of 5000 shared-pool rows outside the private pool, about 20 rows almost surely include some outside it, so `outside` is non-empty and :87 goes red.
- C2 - tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:90 — `conftest.shared_trending_fingerprint()`, read after the Engine has served, equals `before`. `before` is `shared_trending_before`, requested first at :55 so it is read before the seed and the Engine start. Armed by :59: the shared table holds rows with `fetched_at > 0`. - expected: The same tuple before and after. The shared table read this turn, read-only with the plan's fingerprint SQL, was (86826, 1791035941189, 1791035941189, 86826). That `after` equals it once the phase is built is predicted. - excludes: A `trending_seed` that still writes into the shared `whitelist.db`, or an Engine that runs `ensure_trending_schema` or any write on the shared `trending_ranks`. The old seed's DELETE plus `TRENDING_SEED_SQL` would make the fingerprint about (88648, 0, 0, 0), so :90 goes red. :59 shows the last field starts above 0, so that rewrite cannot leave the fingerprint unchanged.

<assertions>
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:51 - control: `test_similar._feed_constants` ran under the Engine interpreter (FEED_CONSTANTS is not None).
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:53 - control: `FEED_CONSTANTS["popular_pool_size"]` is a positive int, the Engine's DEFAULT_POPULAR_POOL_SIZE read through `_feed_constants` as agreed. Phase 3 must add this key to `_FEED_CONSTANTS_CHILD` in test_similar.py; the message names the key.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:57 - control: `_reference(dataset, "trending", threshold)` holds at least 3 * FEED_PAGE rows. Excludes a `dataset` or seed that leaves the private order empty.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:60 - discrimination control: `_reference` on a fresh plain `mode=ro` connection (shared ranks) gives first three pages that differ from the private reference. If they are equal, the message says the shared table has no real fill, or the seed was written into it, and prints the fingerprint before and now. Excludes a `dataset` that carries no private view, and a seed still written into the shared table.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:63 - discrimination control for the popular layer: at least a quarter of the shared filtered popular pool lies outside the private filtered pool (observed 3003 of 5000). So an Engine drawing ~20 popular rows from the shared pool would fail line 77.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:70 - three `mode=trending` pages, each excluding the rows served before it, equal `reference[: 3 * FEED_PAGE]`, the private order (C1). Excludes an Engine started without `--trending-db` (it serves the shared head, shown different at :60), an Engine reading an empty private file (empty pages), and an exclude walk that repeats or skips rows.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:75 - control: an unseeded `POST /recommendations?limit=96&debug=1` on its own bucket (192.0.2.181) serves at least one row with `debug.layer == "popular"`. Excludes an Engine whose ranks table is empty, where the popular layer serves nothing.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:77 - every popular-layer row is in `fetch_popular_videos(dataset, POOL, error_threshold=threshold, include_nsfw=False)`, the private pool (C1). Excludes an Engine whose popular generator reads the shared `trending_ranks`, about 60% of whose rows fall outside the private pool.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:80 - after the Engine has served, `shared_trending_fingerprint() == shared_trending_before` (C2). The message names an operator updater trending-stage run as a possible external cause. `shared_trending_before` is the first parameter, so it is read before `engine` builds the seed whatever order the conftest declares. Excludes the old seed's DELETE+INSERT (88648 rows with fetched_at 0 against 86826 real ones) and any Engine start that writes the shared table.
</assertions>

<probes>
tests/tmp/probe_phase3_shared_vs_private.py, via ValidateTests ["tests/tmp/probe_phase3_shared_vs_private.py", "-s"]. Read-only on the shared DB. It builds the private seed the way the plan does (TRENDING_SEED_SQL into a temp file, shared attached mode=ro) and printed: VIDEO_ERROR_THRESHOLD 3, DEFAULT_POPULAR_POOL_SIZE 5000; shared fingerprint (86826, 1791035941189, 1791035941189, 86826) before and after, so there is a real fill and the probe changed nothing; private seed 88648 rows; `attach_trending_override` works on a `mode=ro` URI connection, and that connection's `main.trending_ranks` still reads the shared fingerprint; the shared and private filtered heads (36 rows) differ, with 7 keys in common; of the shared filtered popular pool, 3003 of 5000 rows are outside the private filtered pool; and the unfiltered private pool (`fetch_popular_videos(dataset, POOL)` with default args, as the Step 6 wording reads) misses 74 of the filtered pool's rows. The checkpoint therefore uses the filtered call the Engine makes (builder.py:114-118: the error threshold and the request's NSFW flag), because the literal unfiltered call would make a correct Engine flaky.
tests/tmp/probe_phase3_engine_popular.py, via ValidateTests ["tests/tmp/probe_phase3_engine_popular.py", "-s"]. A real Engine started with `--trending-db <private seed>` (Phase 2 wired the flag), under ENGINE_START_LOCK, without the `engine` fixture, which today still rewrites the shared table. It printed: `mode=trending&limit=12` gives status 200, seed {}, rows equal to the private head[:12]. Unseeded `POST /recommendations?limit=48&debug=1` gives 48 rows, layers fresh/popular/random, 10 popular rows, all 10 in the private pool and 3-5 in the shared one. limit=96 gives 89 rows and 20 popular, all 20 in the private pool and 4-10 in the shared one. Shared fingerprint unchanged.
Red run of the checkpoint, via ValidateTests ["tests/tmp/test_44_trending_seed_write_lock_during_phase3.py"]: a collection error, ImportError: cannot import name 'shared_trending_before' from 'conftest'. No fixture ran, so the current trending_seed did not rewrite the shared table.
Both probe files are still in tests/tmp/. My tools cannot delete files, so the operator needs to remove them. Each fails on purpose with `assert False`.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_44_trending_seed_write_lock_during_phase3.py` - 6871 characters, inlined in full

```
"""The session Engine, started by `tests/active/conftest.py`'s `engine` fixture, serves Trending and its popular layer from the session's private ranks, and the shared whitelist.db `trending_ranks` is left as it was:

- Controls: `_feed_constants` reads the Engine's error threshold and its `DEFAULT_POPULAR_POOL_SIZE`; the private Trending order through `dataset` runs past three pages; on a fresh plain read-only connection the shared order's first three pages differ from it, and at least a quarter of the shared popular pool lies outside the private one.
- Three `mode=trending` pages, each excluding the rows served before it, are exactly the first three pages of `_reference(dataset, "trending", threshold)`.
- An unseeded `POST /recommendations?debug=1` serves at least one `debug.layer == "popular"` row, and every such row is in `fetch_popular_videos(dataset, POOL)` under the threshold and the default NSFW filter.
- After the Engine has served, `shared_trending_fingerprint()` (row count, `fetched_at` min and max, rows with `fetched_at > 0`) equals `shared_trending_before`, read before the seed was built.

The fixtures come from `tests/active/conftest.py` and `_reference`, `_post`, `_exclude`, `_keys` and `FEED_CONSTANTS` from `tests/active/test_similar.py`, loaded by path so its tests are not collected here.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
# Imported so pytest serves the session fixtures outside tests/active. Until the conftest builds a private seed, shared_trending_* do not exist and this fails at collection, before the old trending_seed can rewrite the shared table.
from conftest import WHITELIST_DB, dataset, engine, shared_trending_before, shared_trending_fingerprint, trending_seed  # noqa: E402, F401

_HARNESS_SPEC = importlib.util.spec_from_file_location("similar_harness", ACTIVE_DIR / "test_similar.py")
harness = importlib.util.module_from_spec(_HARNESS_SPEC)
# The harness puts engine/server on sys.path, which the data import below needs.
_HARNESS_SPEC.loader.exec_module(harness)

from data.random_videos import fetch_popular_videos  # noqa: E402

# The key `_feed_constants` carries the Engine's DEFAULT_POPULAR_POOL_SIZE under.
POOL_KEY = "popular_pool_size"
# Their own rate-limit buckets, clear of every 192.0.2.x address tests/active uses.
TRENDING_HEADERS = {"X-Client-IP": "192.0.2.180"}
POPULAR_HEADERS = {"X-Client-IP": "192.0.2.181"}


def _shared(threshold: int, pool_size: int) -> tuple[list[tuple[str, str]], set[tuple[str, str]]]:
    """The shared table's Trending reference and popular pool, read on a fresh plain read-only connection that carries no private ranks."""
    plain = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    plain.row_factory = sqlite3.Row
    try:
        return harness._reference(plain, "trending", threshold), set(harness._keys(fetch_popular_videos(plain, pool_size, error_threshold=threshold, include_nsfw=False)))
    finally:
        plain.close()


# shared_trending_before is requested first, so its fingerprint is read before the seed and the Engine start whatever order the conftest declares.
def test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(shared_trending_before, engine, dataset):  # noqa: F811
    constants = harness.FEED_CONSTANTS
    assert constants is not None, harness.FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    pool_size = constants.get(POOL_KEY)
    assert isinstance(pool_size, int) and pool_size > 0, f"control: _feed_constants carries no {POOL_KEY!r} read from the Engine's DEFAULT_POPULAR_POOL_SIZE: {constants}"
    threshold = constants["threshold"]
    page = harness.FEED_PAGE
    reference = harness._reference(dataset, "trending", threshold)
    assert len(reference) >= 3 * page, len(reference)  # control: the private order holds three pages
    shared_reference, shared_pool = _shared(threshold, pool_size)
    # Observed with the real fill: 7 of the 36 head keys in common, and 3003 of the shared pool's 5000 outside the private pool.
    assert shared_reference[: 3 * page] != reference[: 3 * page], f"control: the shared trending_ranks gives the same first three pages as the private seed, so it has no real fill (or the seed was written into it) and this test cannot tell the two apart; shared fingerprint {shared_trending_before} -> {shared_trending_fingerprint()}"
    private_pool = set(harness._keys(fetch_popular_videos(dataset, pool_size, error_threshold=threshold, include_nsfw=False)))
    # Popular rows drawn from the shared pool then land outside the private one about once in four or more each, so an Engine reading the shared table fails below on its ~20 rows.
    assert 4 * len(shared_pool - private_pool) >= len(shared_pool), f"control: only {len(shared_pool - private_pool)} of the shared popular pool's {len(shared_pool)} rows are outside the private pool"

    path = f"/recommendations?mode=trending&limit={page}"
    first = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {})["rows"])
    second = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {"exclude": harness._exclude(first)})["rows"])
    third = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {"exclude": harness._exclude(first + second)})["rows"])
    # An Engine reading the shared table serves its head here, which the control above shows differs.
    assert first + second + third == reference[: 3 * page], (first + second + third, reference[: 3 * page])  # C1

    # Twice the default page: 20 popular rows a request, all in the private pool and 4 to 10 in the shared one (observed on an Engine started with --trending-db on the seed).
    served = harness._post(engine, f"/recommendations?limit={2 * harness._default_limit()}&debug=1", POPULAR_HEADERS, {})
    popular = harness._keys([row for row in served["rows"] if row["debug"]["layer"] == "popular"])
    assert popular, f"control: no popular-layer row served, layers {sorted({str(row['debug']['layer']) for row in served['rows']})}"  # an Engine whose ranks table is empty serves none
    outside = [key for key in popular if key not in private_pool]
    assert not outside, f"{len(outside)} of {len(popular)} popular rows are outside the private pool, {sum(key in shared_pool for key in outside)} of them in the shared one: {outside[:5]}"  # C1

    after = shared_trending_fingerprint()
    assert after == shared_trending_before, f"the shared whitelist.db trending_ranks fingerprint moved {shared_trending_before} -> {after}: the suite wrote it, or the operator's updater ran its trending stage during this run"  # C2

```


Gate: satisfied

## 2026-10-03 - Step 7 - Phase 3 (Active suite on a private Trending seed) - does not collect (send-back 1)

`validate_tests.py tests/tmp/test_44_trending_seed_write_lock_during_phase3.py --collect-only -q` exited 2.

```

==================================== ERRORS ====================================
_ ERROR collecting tests/tmp/test_44_trending_seed_write_lock_during_phase3.py _
ImportError while importing test module '/home/enduser/code/PeerTube-browser/tests/tmp/test_44_trending_seed_write_lock_during_phase3.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.pixi/envs/default/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:22: in <module>
    from conftest import WHITELIST_DB, dataset, engine, shared_trending_before, shared_trending_fingerprint, trending_seed  # noqa: E402, F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ImportError: cannot import name 'shared_trending_before' from 'conftest' (/home/enduser/code/PeerTube-browser/tests/active/conftest.py)
=========================== short test summary info ============================
ERROR tests/tmp/test_44_trending_seed_write_lock_during_phase3.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
no tests collected, 1 error in 0.07s

the run produced no per-test results, so there is nothing to bucket or compare — its output above says why

recorded: tests/last_test_validation.json (exit 2)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 3 (Active suite on a private Trending seed) - self-check (audit round 1, send-back 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:80 — the session Engine is asked for three `mode=trending` pages (limit FEED_PAGE, each excluding the rows already served). Together they must equal `harness._reference(dataset, "trending", threshold)[: 3 * FEED_PAGE]`, the private seed's order read through `dataset` with its private view. This is armed by :67 (the private order holds three pages) and :70 (the shared head, read on a fresh plain mode=ro connection, differs from the private head). - expected: The 36 keys of the private seed's Trending head, in order. Observed this turn: an Engine started with `--trending-db` on a private seed built from TRENDING_SEED_SQL served a first `mode=trending&limit=12` page equal to the private head[:12] (probe_phase3_engine_popular.py: "matches private head[:12] True"). The checkpoint's own run has not reached :80 yet, because it stops at :55 on the fixture the phase adds. - excludes: The Engine is started without `--trending-db`, or the flag never shadows `trending_ranks` on `server.db`, so the Engine serves the shared real-fill head. Observed this turn on an unflagged Engine (probe_phase3_unflagged_engine.py): its first page shared 1 of 12 keys with the private head. Across 36 rows the shared and private heads share only 7 keys, so :80 goes red. An empty private file returns empty pages, which also makes :80 red.
- C1 - tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:87 — the test sends an unseeded `POST /recommendations?limit=2*BATCH_SIZE&debug=1`. Every row it returns with `debug.layer == "popular"` must be in `fetch_popular_videos(dataset, POOL, error_threshold=threshold, include_nsfw=False)`, the private pool. This is armed by :85 (at least one popular row is served) and :73 (at least a quarter of the shared pool lies outside the private pool; observed 3003 of 5000). - expected: `outside == []`. Observed this turn on an Engine started with `--trending-db`: three limit=96 requests each served 20 popular rows, all 20 in the private pool, and 4, 6 and 7 of them were also in the shared pool. The checkpoint's own run has not reached :87 yet, because it stops at :55. - excludes: The override reaches `fetch_ordered_page` but not the popular pool's `fetch_popular_videos(server.db, ...)`, or the Engine is started without the flag. Popular rows then come from the shared pool. Observed this turn on an unflagged Engine: 10, 13 and 9 of the 20 popular rows fell outside the private pool, so `outside` is non-empty and :87 goes red.
- C2 - tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:90 — `conftest.shared_trending_fingerprint()`, read after the Engine has served, must equal `before`. `before` is `shared_trending_before`, requested first at :55 so that it is read before the seed is built and the Engine starts. This is armed by :59: the shared table holds rows with `fetched_at > 0`. - expected: The same tuple before and after: (86826, 1791035941189, 1791035941189, 86826). That value was read read-only this turn and stayed unchanged across a flagged Engine start-and-serve, an unflagged one, and the private seed build (all three probes printed it before and after). - excludes: A `trending_seed` that still writes into the shared `whitelist.db`. The old seed's `DELETE FROM trending_ranks` plus `TRENDING_SEED_SQL` replaces the table with the seed's 88648 rows (count observed this turn in the private copy), all with `fetched_at = 0`. That makes the fingerprint (88648, 0, 0, 0) instead of the real fill, and :90 goes red. :59 shows the last field starts above 0, so a rewrite cannot leave the fingerprint unchanged. An Engine start that writes the shared `trending_ranks` would also show up here.

<assertions>
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:55 - setup order, not an assertion: `shared_trending_before` is requested first, by name, through `request.getfixturevalue`. So the fingerprint is read before `engine` builds the seed, whatever scope or order the conftest gives it. A conftest that does not define the fixture stops here, before the old `trending_seed` can rewrite the shared table.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:59 - control: `before[3] > 0`, so the shared `trending_ranks` has a real fill (rows with fetched_at > 0). Without one, a seed written into the table could leave the fingerprint where it was.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:61 - control: `test_similar._feed_constants` ran under the Engine interpreter (`FEED_CONSTANTS is not None`).
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:63 - control: `FEED_CONSTANTS["popular_pool_size"]` is a positive int. It is the Engine's DEFAULT_POPULAR_POOL_SIZE read through `_feed_constants`, as agreed. Phase 3 must add this key to test_similar.py's `_FEED_CONSTANTS_CHILD`, and the failure message names the key.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:67 - control: `_reference(dataset, "trending", threshold)` holds at least 3 * FEED_PAGE rows. Excludes a `dataset` or seed that leaves the private order empty.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:70 - discrimination control: `_reference` on a fresh plain `mode=ro` connection (the shared ranks) gives first three pages that differ from the private reference. If they are equal, the message says the shared table has no real fill or the seed was written into it, and prints the fingerprint before and now. Excludes a `dataset` that carries no private view, and a seed still written into the shared table.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:73 - discrimination control for the popular layer: at least a quarter of the shared filtered popular pool lies outside the private filtered pool (observed 3003 of 5000). So an Engine that draws about 20 popular rows from the shared pool fails line 87.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:80 - three `mode=trending` pages, each excluding the rows served before it, equal `reference[: 3 * FEED_PAGE]`, the private order (C1). Excludes an Engine started without `--trending-db` (it serves the shared head, which :70 shows is different), an Engine reading an empty private file (empty pages), and an exclude walk that repeats or skips rows.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:85 - control: an unseeded `POST /recommendations?limit=2*default&debug=1` on its own rate bucket (192.0.2.181) serves at least one row with `debug.layer == "popular"`. Excludes an Engine whose ranks table is empty, so that its popular layer serves nothing.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:87 - every popular-layer row is in `fetch_popular_videos(dataset, POOL, error_threshold=threshold, include_nsfw=False)`, the private pool (C1). Excludes an Engine whose popular generator reads the shared `trending_ranks`; about 60% of that pool lies outside the private one.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:90 - after the Engine has served, `conftest.shared_trending_fingerprint() == before` (C2). The message names the operator's updater trending-stage run as a possible external cause. Excludes the old seed's DELETE+INSERT (88648 rows, all with fetched_at 0, against 86826 real ones) and any Engine start that writes the shared table.
</assertions>

<probes>
tests/tmp/probe_phase3_shared_vs_private.py, run with ValidateTests ["tests/tmp/probe_phase3_shared_vs_private.py", "-s"]. It only reads the shared DB. It builds the private seed the way the plan does (TRENDING_SEED_SQL into a temp file, with shared attached mode=ro). It printed: VIDEO_ERROR_THRESHOLD 3 and DEFAULT_POPULAR_POOL_SIZE 5000. The shared fingerprint was (86826, 1791035941189, 1791035941189, 86826) both before and after, so the table has a real fill and the probe changed nothing. The private seed has 88648 rows. `attach_trending_override` works on a `mode=ro` URI connection, and that connection's `main.trending_ranks` still reads the shared fingerprint. The shared and private filtered heads (36 rows) differ and share 7 keys. 3003 of the shared filtered popular pool's 5000 rows are outside the private filtered pool. The unfiltered private pool (`fetch_popular_videos(dataset, POOL)` with default args, as Step 6 words it) misses 74 of the filtered pool's rows. So the checkpoint uses the filtered call the Engine makes (builder.py:114-118: the error threshold and the request's NSFW flag), because the literal unfiltered call would make a correct Engine flaky.
tests/tmp/probe_phase3_engine_popular.py, run with ValidateTests ["tests/tmp/probe_phase3_engine_popular.py", "-s"]. A real Engine started with `--trending-db <private seed>` (Phase 2 wired the flag), under ENGINE_START_LOCK, without the `engine` fixture, because that fixture still rewrites the shared table today. It printed: `mode=trending&limit=12` returned 200 with seed {}, and its rows equal the private head[:12]. Unseeded `POST /recommendations?limit=48&debug=1` returned 48 rows in the fresh/popular/random layers; 10 were popular, all 10 in the private pool and 3-5 in the shared one. limit=96 returned 89 rows, 20 of them popular, all 20 in the private pool and 4-10 in the shared one. The shared fingerprint did not change.
Collection, with ValidateTests ["tests/tmp/test_44_trending_seed_write_lock_during_phase3.py", "--collect-only", "-q"]: exit 0, "1 test collected". The earlier ImportError came from an unguarded `from conftest import shared_trending_before`. That import is now bound only `if hasattr(conftest, "shared_trending_before")`, and the test reaches the fixture through `request.getfixturevalue`.
Red run, with ValidateTests ["tests/tmp/test_44_trending_seed_write_lock_during_phase3.py"]: exit 1, 1 failed, with `fixture 'shared_trending_before' not found` at line 55, the first fixture request. `engine` and `trending_seed` never ran, so the current seed did not rewrite the shared table.
Both probe files are still in tests/tmp/. My tools cannot delete files, so the operator needs to remove them. Each one fails on purpose with `assert False`.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_44_trending_seed_write_lock_during_phase3.py` - 7544 characters, inlined in full

```
"""The session Engine, started by `tests/active/conftest.py`'s `engine` fixture, serves Trending and its popular layer from the session's private ranks, and the shared whitelist.db `trending_ranks` is left as it was:

- Controls: `shared_trending_before` shows a real fill in the shared table (rows with `fetched_at > 0`); `_feed_constants` reads the Engine's error threshold and its `DEFAULT_POPULAR_POOL_SIZE`; the private Trending order through `dataset` runs past three pages; on a fresh plain read-only connection the shared order's first three pages differ from it, and at least a quarter of the shared popular pool lies outside the private one.
- Three `mode=trending` pages, each excluding the rows served before it, are exactly the first three pages of `_reference(dataset, "trending", threshold)`.
- An unseeded `POST /recommendations?debug=1` serves at least one `debug.layer == "popular"` row, and every such row is in `fetch_popular_videos(dataset, POOL)` under the threshold and the default NSFW filter.
- After the Engine has served, `shared_trending_fingerprint()` (row count, `fetched_at` min and max, rows with `fetched_at > 0`) equals `shared_trending_before`, read before the seed was built.

The fixtures and `shared_trending_fingerprint` come from `tests/active/conftest.py` and `_reference`, `_post`, `_exclude`, `_keys` and `FEED_CONSTANTS` from `tests/active/test_similar.py`, loaded by path so its tests are not collected here.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
import conftest  # noqa: E402
# Imported so pytest serves the session fixtures outside tests/active.
from conftest import WHITELIST_DB, dataset, engine, trending_seed  # noqa: E402, F401

# Bound only once the conftest defines it; until then the test stops on its lookup, before the old trending_seed can rewrite the shared table's real fill.
if hasattr(conftest, "shared_trending_before"):
    from conftest import shared_trending_before  # noqa: E402, F401

_HARNESS_SPEC = importlib.util.spec_from_file_location("similar_harness", ACTIVE_DIR / "test_similar.py")
harness = importlib.util.module_from_spec(_HARNESS_SPEC)
# The harness puts engine/server on sys.path, which the data import below needs.
_HARNESS_SPEC.loader.exec_module(harness)

from data.random_videos import fetch_popular_videos  # noqa: E402

# The key `_feed_constants` carries the Engine's DEFAULT_POPULAR_POOL_SIZE under.
POOL_KEY = "popular_pool_size"
# Their own rate-limit buckets, clear of every 192.0.2.x address tests/active uses.
TRENDING_HEADERS = {"X-Client-IP": "192.0.2.180"}
POPULAR_HEADERS = {"X-Client-IP": "192.0.2.181"}


def _shared(threshold: int, pool_size: int) -> tuple[list[tuple[str, str]], set[tuple[str, str]]]:
    """The shared table's Trending reference and popular pool, read on a fresh plain read-only connection that carries no private ranks."""
    plain = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    plain.row_factory = sqlite3.Row
    try:
        return harness._reference(plain, "trending", threshold), set(harness._keys(fetch_popular_videos(plain, pool_size, error_threshold=threshold, include_nsfw=False)))
    finally:
        plain.close()


def test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(request):
    # Requested first and by name, so the fingerprint is read before the seed is built and the Engine starts, and a conftest without it never reaches the Engine.
    before = request.getfixturevalue("shared_trending_before")
    engine = request.getfixturevalue("engine")  # noqa: F811
    dataset = request.getfixturevalue("dataset")  # noqa: F811
    # Observed read-only: (86826, 1791035941189, 1791035941189, 86826). A seed written into the table sets fetched_at = 0 throughout, so the last field drops to 0.
    assert before[3] > 0, f"control: the shared trending_ranks holds no rows with fetched_at > 0, so a seed written into it may leave the fingerprint unmoved: {before}"
    constants = harness.FEED_CONSTANTS
    assert constants is not None, harness.FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    pool_size = constants.get(POOL_KEY)
    assert isinstance(pool_size, int) and pool_size > 0, f"control: _feed_constants carries no {POOL_KEY!r} read from the Engine's DEFAULT_POPULAR_POOL_SIZE: {constants}"
    threshold = constants["threshold"]
    page = harness.FEED_PAGE
    reference = harness._reference(dataset, "trending", threshold)
    assert len(reference) >= 3 * page, len(reference)  # control: the private order holds three pages
    shared_reference, shared_pool = _shared(threshold, pool_size)
    # Observed with the real fill: 7 of the 36 head keys in common, and 3003 of the shared pool's 5000 outside the private pool.
    assert shared_reference[: 3 * page] != reference[: 3 * page], f"control: the shared trending_ranks gives the same first three pages as the private seed, so it has no real fill (or the seed was written into it) and this test cannot tell the two apart; shared fingerprint {before} -> {conftest.shared_trending_fingerprint()}"
    private_pool = set(harness._keys(fetch_popular_videos(dataset, pool_size, error_threshold=threshold, include_nsfw=False)))
    # Popular rows drawn from the shared pool then land outside the private one about once in four or more each, so an Engine reading the shared table fails below on its ~20 rows.
    assert 4 * len(shared_pool - private_pool) >= len(shared_pool), f"control: only {len(shared_pool - private_pool)} of the shared popular pool's {len(shared_pool)} rows are outside the private pool"

    path = f"/recommendations?mode=trending&limit={page}"
    first = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {})["rows"])
    second = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {"exclude": harness._exclude(first)})["rows"])
    third = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {"exclude": harness._exclude(first + second)})["rows"])
    # An Engine reading the shared table serves its head here, which the control above shows differs.
    assert first + second + third == reference[: 3 * page], (first + second + third, reference[: 3 * page])  # C1

    # Twice the default page: 20 popular rows a request, all in the private pool and 4 to 10 in the shared one (observed on an Engine started with --trending-db on the seed).
    served = harness._post(engine, f"/recommendations?limit={2 * harness._default_limit()}&debug=1", POPULAR_HEADERS, {})
    popular = harness._keys([row for row in served["rows"] if row["debug"]["layer"] == "popular"])
    assert popular, f"control: no popular-layer row served, layers {sorted({str(row['debug']['layer']) for row in served['rows']})}"  # an Engine whose ranks table is empty serves none
    outside = [key for key in popular if key not in private_pool]
    assert not outside, f"{len(outside)} of {len(popular)} popular rows are outside the private pool, {sum(key in shared_pool for key in outside)} of them in the shared one: {outside[:5]}"  # C1

    after = conftest.shared_trending_fingerprint()
    assert after == before, f"the shared whitelist.db trending_ranks fingerprint moved {before} -> {after}: the suite wrote it, or the operator's updater ran its trending stage during this run"  # C2

```


Gate: satisfied

## 2026-10-03 - Step 7 - Phase 3 (Active suite on a private Trending seed) - red (audit round 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase3.py` exited 1.

```
  tests/tmp/test_44_trending_seed_write_lock_during_phase3.py  1 failed                               0.0s
  -----------------------------------------------------------
  total                                                        1 failed                               0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 7 - Phase 3 (Active suite on a private Trending seed) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. Considered under `single-value-pin` (rules/shape.md), second `<how_to_spot>` bullet; not met, so not Critical. tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:89
   after = conftest.shared_trending_fingerprint()
   The C2 check compares two readings. Both `before` (through the `shared_trending_before` fixture) and `after` come from the conftest fingerprint code, and that code is one of the edited files under test. The control at line 59 (`assert before[3] > 0`) rules out the likely wrong version: a fingerprint that reads the private seed file, where every `fetched_at` is 0. A fingerprint that caches or snapshots its first reading would still make line 90 equal no matter what happened to the table. Reading the `after` value at line 89 independently would remove that gap. One way is a fresh `mode=ro` connection and the test's own `COUNT`/`MIN`/`MAX`/`SUM(fetched_at > 0)` query, as `_shared` already does for ranks. No rule names this remaining gap.

PREDICTED FAILURE
The test stops at line 55, `request.getfixturevalue("shared_trending_before")`, with a fixture lookup error, because `tests/active/conftest.py` defines no `shared_trending_before`. This is a setup error, not an assertion failure. The comment at line 25 says the test is meant to stop here. If the fixture existed, the first assertion to fail would be line 63, `isinstance(pool_size, int) and pool_size > 0`, because the `_feed_constants` child (test_similar.py:719-729) outputs only `feed`, `ordered` and `threshold`, with no `popular_pool_size`.

NOT ASSESSED
1. `code_under_test` lists tests/active/conftest.py and tests/active/test_similar.py as EDITED, but neither file as read contains the phase's changes. Missing are the `shared_trending_before` fixture, `shared_trending_fingerprint`, a private seed file behind `dataset` or the Engine (`trending_seed` still runs `DELETE FROM trending_ranks` on the shared `WHITELIST_DB` at conftest.py:141), and `popular_pool_size` in `_feed_constants`. So I answered the stub question from the assertion form and its controls, not from the fixtures as they will be:
   - C1 pages (line 80): an Engine reading the shared table should fail here.
   - C1 popular rows (lines 85-87): the positive control at line 85 plus the 25%-outside control at line 73 should catch the same case.
   - Previous behaviour (seed written into the shared table): `dataset` and the shared read would then match, so the control at line 70 should catch it.
   - C2 (line 90): covered as long as the fingerprint reads the live shared table, which I could not verify.
2. I did not check whether `tmp_path`-free reads of `dataset` actually point at the private ranks. The test relies on that, and the fixture defining it has not been written yet.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (20 clauses: 6 must_prove, 12 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | Trending pages follow the private seed's ranks | :80 | An Engine serving any order other than `_reference(dataset, "trending")[:36]`, including one that ignores `exclude` and repeats page 1 | CARRIED |
| C1b | must_prove | Trending pages do not follow the shared table's ranks | :80, armed by :70 | An Engine started without `--trending-db`, or a flag that never shadows the table. :70 makes the shared head differ from the private head, so serving the shared head fails :80 | CARRIED |
| C1c | must_prove | popular-layer rows follow the private seed's ranks | :87 | A popular row drawn from outside `fetch_popular_videos(dataset, POOL)` under the threshold and the NSFW filter | CARRIED |
| C1d | must_prove | popular-layer rows do not follow the shared table's ranks | :87, armed by :73 and :85 | A popular layer reading the shared pool. :73 puts at least a quarter of that pool outside the private one, and :85 rules out a vacuous empty set | CARRIED |
| C2a | must_prove | shared fingerprint identical before the seed and after the Engine served | :90 (read at :89 after :76-83 served) | A seed written into the shared table (`fetched_at = 0` drops the fourth field, which :59 requires to be > 0 beforehand), or any Engine-side write to it | CARRIED |
| C2b | must_prove | fingerprint = row count, `fetched_at` min and max, rows with `fetched_at > 0` | :90 (tuple equality), :59 indexes `[3]` | A change in any member the helper returns. Whether the helper returns all four could not be read (see NOT ASSESSED) | CARRIED |
| D1 | docstring | "serves Trending … from the session's private ranks" | :80 | An Engine serving the shared head | CARRIED |
| D2 | docstring | "and its popular layer from the session's private ranks" | :87 | A popular row outside the private pool | CARRIED |
| D3 | docstring | "the shared whitelist.db `trending_ranks` is left as it was" | :90 | Any write that moves the fingerprint | CARRIED |
| D4 | docstring | control: `shared_trending_before` shows a real fill | :59 | A shared table with no `fetched_at > 0` rows, where a write into it could leave the fingerprint unmoved | CARRIED |
| D5 | docstring | control: `_feed_constants` reads the threshold and `DEFAULT_POPULAR_POOL_SIZE` | :61, :63, :64 | A child that failed to import, or a missing or non-positive `popular_pool_size` key. It does not exclude a hard-coded value under that key | CARRIED |
| D6 | docstring | control: private Trending order runs past three pages | :67 | An empty or short private seed, or a `dataset` without the private view | CARRIED |
| D7 | docstring | control: on a fresh plain read-only connection, the shared first three pages differ | :70 | A `dataset` carrying no private view, or a seed written into the shared table | CARRIED |
| D8 | docstring | control: at least a quarter of the shared pool lies outside the private one | :73 | Shared and private pools so close that :87 cannot tell them apart | CARRIED |
| D9 | docstring | three `mode=trending` pages, each excluding prior rows, are exactly the first three reference pages | :80 | Wrong order, wrong rows, or `exclude` ignored (a repeated page cannot equal the 36-key reference) | CARRIED |
| D10 | docstring | an unseeded `debug=1` request serves at least one popular row | :85 | An Engine whose ranks table is empty and serves no popular layer | CARRIED |
| D11 | docstring | every popular row is in `fetch_popular_videos(dataset, POOL)` under the threshold and the NSFW filter | :87 | A popular row from the shared pool | CARRIED |
| D12 | docstring | after serving, the fingerprint equals `shared_trending_before`, "read before the seed was built" | :90, :59 | A fingerprint move. :59 also fails a `before` read after a seed written into the shared table | CARRIED |
| N1 | name | "the session engine serves trending from its private ranks" | :80, :87 | An Engine serving shared ranks on either the Trending feed or the popular layer | CARRIED |
| N2 | name | "and leaves the shared ranks unchanged" | :90 | Any write to the shared `trending_ranks` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. independence (rules/testing.md) — tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:55
   `before = request.getfixturevalue("shared_trending_before")`
   - The comment at :54 says this read comes "before the seed is built and the Engine starts" because it is requested first. That holds only if no earlier test in the session has already created the session-scoped `engine`.
   - Once this test sits with other `engine` tests (for example in `tests/active/test_similar.py`), the C2 "before the seed" order depends on the conftest's fixture graph, not on this test. That means `trending_seed` would have to depend on `shared_trending_before`, and the conftest supplied does not have that yet.
   - The order should come from the fixture dependency, not from where the request sits in this test.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:53
   - The test only proves the success path: a working private seed served correctly.
   - No failure mode of the private-ranks wiring is exercised here. An example would be an Engine start on a bad `--trending-db` path. That may be covered by another phase's test, but none was supplied.
3. bounds (rules/testing.md) — tests/tmp/test_44_trending_seed_write_lock_during_phase3.py:67
   - Only a fully populated private seed is exercised. :67 makes the short or empty private order a precondition, not a case under test.
   - No edge of the seed is tested, such as an empty private file or one shorter than three pages. No `must_prove` clause requires one.

OBSERVATIONS
none

NOT ASSESSED
1. `shared_trending_fingerprint` and the `shared_trending_before` fixture are not defined in `tests/active/conftest.py` as it reads now. The test binds the fixture only when it exists (:26-27). C2b was therefore judged from :59's `[3]` index and the comment at :58. Whether the helper reads all four named fields (row count, `fetched_at` min, max, and count > 0) could not be checked.
2. `tests/active/conftest.py`'s `dataset` (:229-233) opens the shared `whitelist.db` read-only with no private view attached. Whether the edited `dataset` will carry the private seed's `trending_ranks`, which C1a and C1c compare against, could not be checked. The control at :70 is what guards it in the test.
3. `tests/active/test_similar.py`'s `_FEED_CONSTANTS_CHILD` (:719-729) does not yet emit `popular_pool_size`. Whether the edited child reads it from the Engine's `DEFAULT_POPULAR_POOL_SIZE` (D5) could not be checked.
4. `fixtures_path` was not supplied. The test's fixtures come from `tests/active/conftest.py`, which was read, but as noted above it is in its pre-edit state.

## 2026-10-03 - Step 7 - Phase 3 (Active suite on a private Trending seed) - checkpoint outcome (run 1)

`tests/tmp/test_44_trending_seed_write_lock_during_phase3.py` exited 0 after the phase landed.

<changes>
### `tests/active/conftest.py`
- The trending schema module (`engine/server/data/trending.py`) is now loaded once at module level as `TRENDING`. Before, it was loaded lazily inside `trending_seed`. `trending_seed` and `dataset` both use it.
- Added `TRENDING_FINGERPRINT_SQL`: `COUNT(*)`, `MIN(fetched_at)`, `MAX(fetched_at)` and the count of rows with `fetched_at > 0`, read from `main.trending_ranks`.
- Added `shared_trending_fingerprint()`. It runs that query on a fresh `file:…?mode=ro` connection to `WHITELIST_DB` and returns a tuple.
- Added the session fixture `shared_trending_before`, which returns that fingerprint.
- `trending_seed(tmp_path_factory, shared_trending_before)` no longer writes the shared DB and no longer takes `ENGINE_START_LOCK`. It works like this:
  - It creates `tmp_path_factory.mktemp("trending") / "trending.db"` on a URI connection and applies `ensure_trending_schema`.
  - It attaches `file:<WHITELIST_DB>?mode=ro` as `shared` and runs `TRENDING_SEED_SQL` unchanged inside `with conn:`.
  - It returns the path.
  - It takes `shared_trending_before` only to make the fingerprint read happen before the seed.
- `engine` adds `"--trending-db", str(trending_seed)` to the Engine argv, plus one comment line. The start lock and the retry loop are unchanged.
- `dataset(trending_seed)` calls `TRENDING.attach_trending_override(conn, str(trending_seed))` on its read-only connection. `_reference` and `fetch_popular_videos` on `dataset` therefore read the same private ranks the Engine serves.
- Rewrote the module docstring, the `trending_seed` docstring and the comment above `TRENDING_SEED_SQL` to describe the private seed. `ENGINE_START_LOCK`, `fcntl` and `tempfile` stay, since the engine fixture and other test files still use them.

### `tests/active/test_similar.py`
- `_FEED_CONSTANTS_CHILD` now also prints `"popular_pool_size": server_config.DEFAULT_POPULAR_POOL_SIZE`, and the `_feed_constants` docstring mentions it.
- The docstring bullet for the ordered-mode test now says the `dataset` connection's Trending ranks are the session's private seed.

### Observed with probes (`tests/tmp/probe_private_seed.py`)
- A `mode=ro` connection to the shared DB accepts the ATTACH plus TEMP VIEW from `attach_trending_override`.
- A write to the attached shared DB is refused with "attempt to write a readonly database".
- Running the new fixture bodies gave these results:
  - The private file held 88,648 rows, all with `fetched_at = 0`.
  - `dataset`'s view read those same 88,648 rows.
  - The shared fingerprint was `(86826, 1791035941189, 1791035941189, 86826)` both before and after.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_private_seed.py: a probe file I created and then emptied. I have no tool to delete a file, so it remains as an empty, uncollected file and should be deleted.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_44_trending_seed_write_lock_during_phase3.py  1 passed                               0.0s
  -----------------------------------------------------------
  total                                                        1 passed                               6.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_44_trending_seed_write_lock_during_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_44_trending_seed_write_lock_during_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_44_trending_seed_write_lock_during_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_44_trending_seed_write_lock_during_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_44_trending_seed_write_lock_during_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_44_trending_seed_write_lock_during_phase3.py`

## 2026-10-03 - Step 8 - refactor pass

<refactors>
none — `engine/server/data/trending.py` and `engine/server/api/server.py` were already the smallest shape that passes, so I made no edits.
</refactors>

<left_out>
Removing the one-line "what" comment above `TRENDING_OVERRIDE_SCHEMA` in `engine/server/data/trending.py`: it is cosmetic, and the approved draft (plan line 472) has the constant in the same form.
Inlining `TRENDING_OVERRIDE_SCHEMA` into the two f-strings of `attach_trending_override`: it is one name used twice in one function, the approved draft defines it, and inlining saves no lines.
Merging the two `args.trending_db` branches in `server.py` `main()` into one: they cannot merge, because `prepare_trending_override` must run before `connect_db` (so a bad path stops the start before whitelist.db is opened) and the attach must run after it, after the committing `executescript` ensures.
Logging the plan's optional `trending_db=` line at startup: that would be new behaviour, not a refactor, and no test or requirement asks for it.
Adding `engine/server/data/trending.py` to the `test_server_config.py` group in `tests/config.json`: this belongs with promoting the Phase 2 checkpoint into that file, not with a production refactor, and changing it mid-build would move the fingerprint being gated.
Test files (`tests/active/conftest.py`, `tests/active/test_similar.py`, `tests/active/test_random_videos.py`, `tests/active/test_server_config.py`) and the gated `tests/tmp/test_44_*` checkpoints: not production code, and the gated ones are not mine to edit.
Cleanup that needs the operator, since I cannot delete files: tests/tmp/probe_private_seed.py, probe_phase3_unflagged_engine.py, probe_phase3_fingerprint.py, probe_phase3_engine_popular.py, probe_phase3_shared_vs_private.py, probe_valid_start.py, probe_trending_db_flag.py, probe_override_plan.py and probe_override.py are leftover probes from earlier phases.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
I read both production files on disk and searched for every user of the new names. The override is three names in `trending.py`, used only by the guarded branches in `server.py` `main()` and by the `conftest.py` fixtures, with no duplication or dead code, so I made no change and ran nothing.
</observation>

## 2026-10-03 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 7 of 59 test groups (52 unchanged):
  test_fetch_trending.py — changed
  test_internal_events.py — changed
  test_random_cache.py — changed
  test_random_videos.py — changed
  test_search_fusion.py — no map entry
  test_server_config.py — changed
  test_similar.py — changed
  test_fetch_trending.py   14 passed                              0.5s
  test_internal_events.py  9 passed                               0.7s
  test_random_cache.py     28 passed                             57.2s
  test_random_videos.py    47 passed                              0.2s
  test_search_fusion.py    10 passed                              2.6s
  test_server_config.py    32 passed                              8.7s
  test_similar.py          82 passed                             48.9s
  -----------------------
  total                    222 passed                            57.5s wall, 7 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-03 - Step 10 - Harvest tests - plan approved

Approved by the operator.

<harvest_file>
docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md
</harvest_file>

<plan>
## Harvest plan: build 47-44 (trending seed write lock during)

I've classified the 4 tests in this build's 3 files in `tests/tmp`. All 4 should move into the durable suite (`DURABLE`). Nothing has moved yet and the group map is unchanged.

Before this, the config check passed with nothing defaulted and no conflicts. A snapshot of `tests/last_test_validation.json` was saved as `.preharvest` and checked byte-identical to the original. All 3 files load in pytest (4 items), checked with `pytest --collect-only`, which records nothing.

### Count per verdict
| Verdict | Count |
|---|---|
| DURABLE | 4 |
| REPLACES | 0 |
| COMBINE | 0 |
| REDUNDANT | 0 |
| SPENT | 0 |

### Tests that move (DURABLE) and where they go
1. **`test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`** (phase 1) → `tests/active/test_random_videos.py`
   - It checks that a connection prepared by `attach_trending_override` gets the attached file's ranks from both the Trending page and the popular pool.
   - It also checks that a plain connection to the same database still gets main's ranks, and that main's ranks are not changed.
   - No test in `tests/active` checks this.
   - It brings `OVERRIDE_EXPECTED`, `OVERRIDE_UNSERVED`, `_private_file` and `_prepared` with it, and uses the file's own `_ranks_db`, `RANKS`, `TRENDING_EXPECTED` and `_trending_labels`.
2. **`test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`** (phase 1) → `tests/active/test_random_videos.py`
   - The existing query-plan test only looks at main's ranks.
   - This one checks that a Trending page read through the attached file still uses `idx_trending_ranks_order` and does no sort (no `TEMP B-TREE`).
   - It brings `_catalogue` and `_catalogue_ranks` with it.
   - **Optional, needs your OK:** change the existing `test_a_trending_page_walks_the_ranks_index_without_sorting` to call those two helpers instead of keeping its own copy of the same setup code. Its assertions would not change.
3. **`test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`** (phase 2) → `tests/active/test_server_config.py`
   - It checks that `server.py --trending-db` is accepted.
   - A missing path or a non-SQLite file must stop the start with a non-zero exit, name the path, create nothing and change nothing.
   - A real SQLite file must get past the check and start.
   - It uses the file's own `_run`, `_free_port`, `_has_started`, `ENGINE_PY`, `API_DIR`, `ENGINE_START_LOCK` and `VARIANT_START_SECONDS`, and brings `SERVER_PY`, `JUNK`, `_argv`, `_start` and `_starts_serving`.
   - The workarounds it needed to run from `tests/tmp` (loading its helper by path, editing `sys.path`) are dropped.
4. **`test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged`** (phase 3) → `tests/active/test_similar.py`
   - It overlaps `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` but adds three things no active test checks:
     - a check that the shared table's first pages differ from the private seed's, so the test can tell which one the Engine served;
     - that live popular-layer rows come from the private pool;
     - that the shared `whitelist.db` `trending_ranks` fingerprint is the same after the Engine has served. That is the rule this build exists for.
   - I classed it as DURABLE rather than COMBINE because the ordered test runs over every ordered mode, and these checks only apply to Trending.
   - In `tests/active` it takes the fixtures `shared_trending_before`, `engine` and `dataset` as plain arguments. The temporary `hasattr` guard and the `getfixturevalue` ordering are dropped.
   - It brings `POOL_KEY`, `TRENDING_HEADERS` and `POPULAR_HEADERS` (client IPs 192.0.2.180 and .181, which no other test uses) and `_shared`.
   - **Risk:** it goes red if the shared table has no real data in it, or if the updater's trending stage runs during the suite. Its failure message names that second cause.

### Active tests that would be retired
None. Nothing goes to `tests/archive/` and no active test is renamed.

### `test_groups` changes
- **`test_server_config.py`**: add `engine/server/data/trending.py`. The refusal and no-create rule the moved test checks live in `prepare_trending_override`. Phase 2 put this addition off until the test was moved.
- **`test_similar.py`**: add `engine/server/api/recommendations/candidates/popular_videos.py`, because the moved test checks which rows the live popular layer serves. Leave this out if you count that as the mixer's job, and `mixer.py` is already listed.
- **`test_random_videos.py`**: no change. It already lists `random_videos.py` and `trending.py`.
- **`conftest.py`**: stays unlisted. It is a shared helper.

### New subject files
None.

### Cleanup after the move (Step 7)
13 entries go to `delete_me/`, and none of the names are already taken there:
- the 3 `test_44_*` checkpoints;
- 9 leftover `probe_*.py` files, one of them already empty;
- `tests/tmp/__pycache__`, renamed to `__pycache__-harvest44`.

`tests/tmp` is empty afterwards.

### Decisions for you
1. Approve the 4 DURABLE moves and their destinations.
2. Approve or decline the optional change to the existing query-plan test in `test_random_videos.py`.
3. Approve or decline adding `popular_videos.py` to the `test_similar.py` group.
</plan>

## 2026-10-03 - Step 9 - build diff

`.scratch/44-trending-seed-write-lock-during/build.diff`: 20 changed file(s) between the Step 0 snapshot `933762268c5f597d611f1416a976e3515d2bde03` (2026-10-03T10:06:46-04:00) and `6941bc979c3484272b92396a70f399e30ea029e8`. Withheld by the permission table: 0.

## 2026-10-03 - Step 9 - document triage

- [ ] `docs/project/issues/44-trending-seed-write-lock-during-test-runs.md` - The issue is delivered, so:
- Set `Status:` to `bug, complete` and move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md` and `issue-tracker.md`.
- Tick the acceptance criteria the build met: flagged Trending served from the private file with the shared fingerprint unchanged (phase 3 test); unflagged reads main (phase 1 test); a missing or non-SQLite path exits non-zero, naming the path, and creates no file (phase 2 test); the suite passes with no test expectations changed.
- Tick the full-suite fingerprint criterion only if the before/after read-only fingerprint around the build's full suite run was recorded. The in-suite gate covers the session Engine.
- Add a short delivery comment saying what landed: `--trending-db PATH` in `server.py`; `prepare_trending_override` and `attach_trending_override` in `engine/server/data/trending.py` (ATTACH as `trending_override` plus a TEMP view shadowing `main.trending_ranks`, still planned as a walk of `idx_trending_ranks_order`); `trending_seed` building a per-session file from the shared DB attached `mode=ro`, no longer taking `ENGINE_START_LOCK`; `dataset` carrying the same private view.
- Record the named limitations from the `rat-tail:` comments. The validation-to-ATTACH race means a file removed after `prepare_trending_override` is recreated empty by ATTACH on the non-URI `connect_db` connection. A PATH containing `?` or `#` fails validation because it is not URI-escaped.
- Also note that the in-suite fingerprint gate goes red if an updater trending run writes the shared table mid-suite.

Out of scope:
- [ ] `engine/server/README.md` - The README lists no Engine CLI flags. The requirements only ask for the flag to be documented here "if it lists Engine flags", and it does not. Its one sentence on the subject (line 26, "Trending serves only videos ranked in `trending_ranks`, so it answers an empty page until the updater's trending stage ... first fills that table") is still true. A production Engine never gets the flag (systemd unit, `scripts/run-services.sh`), and a flagged Engine still serves only rows ranked in a `trending_ranks` table, just the one in PATH. The flag is documented where the requirements make it mandatory: the `--trending-db` `help=(...)` text in `server.py` `parse_args` covers the dev/test override, that only `trending_ranks` is read from PATH, that PATH must exist and is never created, and relative-path resolution.
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - Line 101 ("`trending_ranks` is created empty when the Engine starts") describes the deployed Engine, which never passes `--trending-db`. On that path the unflagged branch of `server.py` `main()` is the original `ensure_trending_schema(db)` line, unchanged. The flagged case applies the schema to the private file. That is a test-isolation detail outside this document's subject (the updater and its first fill), so mentioning it here would add a dev/test aside to an operator runbook.
- [ ] `tests/active/conftest.py` - Phase 3 already brought every named passage up to date, and the diff confirms it:
- The module docstring (lines 6-13) describes `--trending-db` naming `trending_seed`'s per-session private file, `dataset` with that file attached and shadowing `trending_ranks`, and the two fingerprint helpers.
- The `trending_seed` docstring now describes the private file and no longer cites issue 38 or the start lock.
- The `engine` fixture has its `--trending-db` comment.
- The comment above `TRENDING_SEED_SQL` now reads "every lane's private file holds the same rows".
- `dataset` carries its own comment about the private ranks.

Nothing left in the file describes a shared-DB write.
- [ ] `tests/active/test_similar.py` - Phase 3 took option (a) and already updated the ordered-mode bullet in the module docstring. The `dataset` reference is now described as "read through the read-only `dataset` connection (whose Trending ranks are the session's private seed, as the Engine's are)". The `_feed_constants` docstring names the popular pool size it now returns. The NSFW control comment ("the seed is derived from the live whitelist.db") is still true, because the private seed is built by the same SQL from the same live catalogue. The docstring bullet for the phase 3 test is added when the harvest moves that test into this file, not by this step.
- [ ] `tests/active/test_random_videos.py` - The build did not edit this file, and no new test is in it yet. Both phase 1 checkpoints are still in `tests/tmp`, and the harvest plan (`docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md`, awaiting approval) moves them here as DURABLE. The module docstring is still accurate for the tests it lists. The two new claim bullets (the flag-on/flag-off order and pool test, and the override plan test) go in with that move, since a bullet for a test not yet in the file would be false.
- [ ] `tests/active/test_server_config.py` - Not on the checklist; listed for completeness. Like `test_random_videos.py`, it gains the `--trending-db` missing/non-SQLite start test only when the harvest moves it, and its docstring bullet goes with that move. Its current docstring makes no claim the build changed. Unflagged starts on the shared DB behave as before.
- [ ] `CONTEXT.md` - Not on the checklist; checked because line 20 (**Trending**) says the lists "are stored per host in `whitelist.db` `trending_ranks`". That is still the domain definition and the production state. `--trending-db` is a dev/test isolation override, and the issue triage and requirements say explicitly that CONTEXT.md does not change.
- [ ] `DEPLOYMENT.md` - Not on the checklist; checked because lines 87, 195 and 453 describe `trending_ranks`:
- Line 87 is the ranking source.
- Line 195 is the updater's write lock in the served `whitelist.db` and the empty start.
- Line 453 says the trending order walks `idx_trending_ranks_order` with no sort.

All three describe the deployed Engine, which never passes the flag, and the plan claim holds with the flag set too (phase 1 plan test). None of them is made false.
- [ ] `DATA_BUILD.md` - Not on the checklist; checked because line 329 says Trending and the popular layer are empty until `trending_ranks` is filled. That is still true for every production Engine, and the document covers data builds, not test isolation.
- [ ] `docs/project/adr/0010-trending-from-source-instances.md` - The ADR covers where Trending comes from and how it is stored and refreshed. It says nothing about test data or alternative rank sources, and the issue triage confirmed it "does not cover test data". The build leaves the Trending definition, the schema, the job and the production read path unchanged.

ADR conflicts: none

## 2026-10-03 - Step 9 - Update documentation

- [x] `docs/project/issues/44-trending-seed-write-lock-during-test-runs.md` - updated: Issue 44 is now marked `bug, complete` with a Delivered comment, and the archived copy is at `docs/project/issues/archive/`. The old file at `docs/project/issues/` still has to be deleted, because I can't delete files.
- [x] `engine/server/README.md` - out of scope: The README lists no Engine CLI flags. The requirements only ask for the flag to be documented here "if it lists Engine flags", and it does not. Its one sentence on the subject (line 26, "Trending serves only videos ranked in `trending_ranks`, so it answers an empty page until the updater's trending stage ... first fills that table") is still true. A production Engine never gets the flag (systemd unit, `scripts/run-services.sh`), and a flagged Engine still serves only rows ranked in a `trending_ranks` table, just the one in PATH. The flag is documented where the requirements make it mandatory: the `--trending-db` `help=(...)` text in `server.py` `parse_args` covers the dev/test override, that only `trending_ranks` is read from PATH, that PATH must exist and is never created, and relative-path resolution.
- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - out of scope: Line 101 ("`trending_ranks` is created empty when the Engine starts") describes the deployed Engine, which never passes `--trending-db`. On that path the unflagged branch of `server.py` `main()` is the original `ensure_trending_schema(db)` line, unchanged. The flagged case applies the schema to the private file. That is a test-isolation detail outside this document's subject (the updater and its first fill), so mentioning it here would add a dev/test aside to an operator runbook.
- [x] `tests/active/conftest.py` - out of scope: Phase 3 already brought every named passage up to date, and the diff confirms it:
- [x] `tests/active/test_similar.py` - out of scope: Phase 3 took option (a) and already updated the ordered-mode bullet in the module docstring. The `dataset` reference is now described as "read through the read-only `dataset` connection (whose Trending ranks are the session's private seed, as the Engine's are)". The `_feed_constants` docstring names the popular pool size it now returns. The NSFW control comment ("the seed is derived from the live whitelist.db") is still true, because the private seed is built by the same SQL from the same live catalogue. The docstring bullet for the phase 3 test is added when the harvest moves that test into this file, not by this step.
- [x] `tests/active/test_random_videos.py` - out of scope: The build did not edit this file, and no new test is in it yet. Both phase 1 checkpoints are still in `tests/tmp`, and the harvest plan (`docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md`, awaiting approval) moves them here as DURABLE. The module docstring is still accurate for the tests it lists. The two new claim bullets (the flag-on/flag-off order and pool test, and the override plan test) go in with that move, since a bullet for a test not yet in the file would be false.
- [x] `tests/active/test_server_config.py` - out of scope: Not on the checklist; listed for completeness. Like `test_random_videos.py`, it gains the `--trending-db` missing/non-SQLite start test only when the harvest moves it, and its docstring bullet goes with that move. Its current docstring makes no claim the build changed. Unflagged starts on the shared DB behave as before.
- [x] `CONTEXT.md` - out of scope: Not on the checklist; checked because line 20 (**Trending**) says the lists "are stored per host in `whitelist.db` `trending_ranks`". That is still the domain definition and the production state. `--trending-db` is a dev/test isolation override, and the issue triage and requirements say explicitly that CONTEXT.md does not change.
- [x] `DEPLOYMENT.md` - out of scope: Not on the checklist; checked because lines 87, 195 and 453 describe `trending_ranks`:
- [x] `DATA_BUILD.md` - out of scope: Not on the checklist; checked because line 329 says Trending and the popular layer are empty until `trending_ranks` is filled. That is still true for every production Engine, and the document covers data builds, not test isolation.
- [x] `docs/project/adr/0010-trending-from-source-instances.md` - out of scope: The ADR covers where Trending comes from and how it is stored and refreshed. It says nothing about test data or alternative rank sources, and the issue triage confirmed it "does not cover test data". The build leaves the Trending definition, the schema, the job and the production read path unchanged.

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** - while updating `docs/project/issues/44-trending-seed-write-lock-during-test-runs.md`: docs/project/issues/44-trending-seed-write-lock-during-test-runs.md — the original file must be deleted to finish moving it to `docs/project/issues/archive/`. I wrote the archived copy, but my tools cannot delete the original, so the operator has to remove it.

**ADR conflicts.** none

### `docs/project/issues/44-trending-seed-write-lock-during-test-runs.md`

<changes>
Issue 44 is now marked `bug, complete` with a Delivered comment, and the archived copy is at `docs/project/issues/archive/`. The old file at `docs/project/issues/` still has to be deleted, because I can't delete files.

- **Status:** `bug, ready-for-agent` became `bug, complete`. I wrote the full file to `docs/project/issues/archive/44-trending-seed-write-lock-during-test-runs.md`. The Problem, Proposed solution, Related, Triage and Agent Brief text is as it was.
- **Acceptance criteria:** four are ticked: flagged Trending is served from the private file with the shared fingerprint unchanged; without the flag it reads main; a missing path exits non-zero and names the path; the suite passes with no expectations changed.
- **Full-suite fingerprint criterion:** not ticked. The plan record has no read-only fingerprint taken before and after a full suite run. A note on the criterion says so, and says the in-suite gate covers the session Engine.
- **Delivered comment** (under Comments, in the same form as other archived issues). I checked each point against `trending.py`, `server.py` lines 343–357 and `conftest.py`:
  - **Engine flag:** `--trending-db PATH` is a dev/test override, documented in `--help`. `prepare_trending_override` opens PATH `mode=rw` before `whitelist.db` is opened, applies the schema to it, and exits naming PATH if the start fails. `attach_trending_override` attaches it as `trending_override` and adds a TEMP view that shadows `main.trending_ranks`. The Trending query still walks `idx_trending_ranks_order` with no sort. `ensure_trending_schema` does not run on `whitelist.db` when the flag is set.
  - **Suite:** `trending_seed` builds a per-session file from the shared DB attached `mode=ro`, and no longer takes `ENGINE_START_LOCK`. The `engine` fixture passes the flag, and `dataset` carries the same view. `shared_trending_before` and `shared_trending_fingerprint` read the shared table's fingerprint.
  - **Limitations:**
    - If the file is deleted between the check and the ATTACH, ATTACH recreates it empty.
    - A PATH containing `?` or `#` fails the check, because the path is not URI-escaped.
    - The fingerprint gate fails if an updater trending run writes the shared table during the suite.
</changes>

<not_on_checklist>
docs/project/issues/44-trending-seed-write-lock-during-test-runs.md — the original file must be deleted to finish moving it to `docs/project/issues/archive/`. I wrote the archived copy, but my tools cannot delete the original, so the operator has to remove it.
</not_on_checklist>

## 2026-10-03 - Step 10 - Harvest tests

<moved>
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py::test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it → tests/active/test_random_videos.py (group test_random_videos.py), with OVERRIDE_EXPECTED, OVERRIDE_UNSERVED, _private_file and _prepared
tests/tmp/test_44_trending_seed_write_lock_during_phase1.py::test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting → tests/active/test_random_videos.py (group test_random_videos.py), with _catalogue and _catalogue_ranks. The approved optional refactor is done: the existing test_a_trending_page_walks_the_ranks_index_without_sorting now calls _catalogue(conn) then _catalogue_ranks(conn), and its assertions are unchanged.
tests/tmp/test_44_trending_seed_write_lock_during_phase2.py::test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it → tests/active/test_server_config.py (group test_server_config.py), with SERVER_PY, JUNK, _argv, _start, _starts_serving and `import sqlite3`. The by-path harness load and the sys.path insert were dropped.
tests/tmp/test_44_trending_seed_write_lock_during_phase3.py::test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged → tests/active/test_similar.py (group test_similar.py), with POOL_KEY, TRENDING_HEADERS (192.0.2.180), POPULAR_HEADERS (192.0.2.181) and _shared. It takes shared_trending_before, engine and dataset as plain fixtures, and the hasattr guard and getfixturevalue ordering were dropped. It imports WHITELIST_DB and shared_trending_fingerprint from conftest and fetch_popular_videos from data.random_videos.
Each destination file's module docstring gained bullets for the new tests, and the clause tags (C1/C2) were replaced by the rule each assertion gates.
</moved>

<retired>
none
</retired>

<group_map>
test_server_config.py: added engine/server/data/trending.py, where prepare_trending_override holds the refusal and no-create rule the moved test gates.
test_similar.py: added engine/server/api/recommendations/candidates/popular_videos.py. The operator approved this optional item through AskUser.
No other entry changed. test_random_videos.py was already complete, and conftest.py stays unclaimed.
`validate_tests.py --audit-map` exit 0. No MISSING finding names a file the moved tests drive. The engine/server/data/time.py and tmp/suite28 findings were there before this harvest.
</group_map>

<mutations>
m1, engine/server/data/trending.py: attach_trending_override with its CREATE TEMP VIEW line replaced by `pass`. Red: test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it failed at `_trending_labels(fetch_ordered_page(prepared, "trending", 100, 0)) == OVERRIDE_EXPECTED` ('C1' != 'B5' at index 0). Restored from .bak, diff identical. Green: 1 passed.
m2, engine/server/data/trending.py: the TEMP VIEW as `SELECT DISTINCT *`, so it is not flattened. Red: test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting failed at `any("idx_trending_ranks_order" in detail ...)` with plan [CO-ROUTINE trending_ranks, SCAN trending_override.trending_ranks, SCAN t, ...], after its full-page and Popular TEMP B-TREE controls passed. Restored from .bak, diff identical. Green: 1 passed.
m3, engine/server/data/trending.py: prepare_trending_override's SystemExit message without {path}. Red: test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it failed at `str(missing) in run.stderr` (stderr "trending ranks file cannot be opened as SQLite: unable to open database file"). Restored from .bak, diff identical. Green: 1 passed. I chose this over a mode=rwc mutation, because that start gets through and serves until _run's 120 s timeout, which is the hanging kind.
m4, engine/server/api/server.py: main() with `attach_trending_override(db, args.trending_db)` replaced by `pass`, so the Engine reads the shared table and writes nothing. Red: test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged failed at `first + second + third == reference[: 3 * FEED_PAGE]` (differs at index 1), after all its controls passed. Restored from .bak, diff identical. Green: 1 passed, the fingerprint assertion included.
All four backups (trending.py.bak-harvest44-m1, m2 and m3, server.py.bak-harvest44-m4) were moved to delete_me/. None of this harvest's .bak files is left under engine/. The engine/server/db/whitelist.db.bak-20261002-212806 there was already there before this harvest.
</mutations>

<cleared>
17 entries were added to delete_me/ by this harvest:
- the 3 checkpoints: test_44_trending_seed_write_lock_during_phase1.py, phase2.py and phase3.py;
- the 9 probes: probe_override.py, probe_override_plan.py, probe_phase3_engine_popular.py, probe_phase3_fingerprint.py, probe_phase3_shared_vs_private.py, probe_phase3_unflagged_engine.py, probe_private_seed.py (empty), probe_trending_db_flag.py and probe_valid_start.py;
- tests/tmp/__pycache__, renamed to __pycache__-harvest44;
- the 4 mutation backups: trending.py.bak-harvest44-m1, m2 and m3, and server.py.bak-harvest44-m4.
None of the names collided, and each was moved with mv -n. tests/tmp now holds 0 entries. delete_me/ holds 120 entries (103 before). Nothing has been deleted; the operator decides what to remove.
Closing run: the snapshot was restored from tests/last_test_validation.json.preharvest, then `validate_tests.py --compare` exited 0. It ran 4 of 59 groups (test_random_videos.py, test_server_config.py, test_similar.py, and the unmapped test_search_fusion.py) and carried 55 forward as unchanged. 175 passed, 0 failed.
Against the pre-harvest record: 4 appeared (the 4 harvested tests), 0 departed, no new red, nothing newly green. The steps are recorded in docs/project/plans/harvest-44-trending-seed-write-lock-during-plan.md.
</cleared>

`--audit-map` exited 0.
Files still in tests/tmp: none

`--compare` exited 0.

```
selected 1 of 59 test groups (58 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.0s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

