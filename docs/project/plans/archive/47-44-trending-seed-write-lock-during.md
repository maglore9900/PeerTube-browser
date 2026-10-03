# 44-trending-seed-write-lock-during

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/47-44-trending-seed-write-lock-during.record.md`._

## Requirements

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

## High-level plan

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

## Impacts


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


## Documentation to update

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

## Implementation plan

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

### Phases

#### Phase 1 - Trending override helpers [code]

**Files touched.** engine/server/data/trending.py (EDITED), tests/active/test_random_videos.py (EDITED)

**Checkpoint.** Seam: the public functions in `engine/server/data/random_videos.py` (`fetch_ordered_page`, `fetch_popular_videos`) plus `attach_trending_override` and `prepare_trending_override` from `data.trending`. The test calls them in-process, on temp SQLite files (rung 1). It follows the existing harness in `tests/active/test_random_videos.py`: `_schema`, `_ranks_db`, `_plan`, and `test_a_trending_page_walks_the_ranks_index_without_sorting`. Two tests. (a) `test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it`: main holds ranks A (`TRENDING_EXPECTED`) and the private file holds the same keys with ranks B, a hand-derived different order (e.g. reversed). A plain connection must serve A from both `fetch_ordered_page(..., "trending", ...)` and `fetch_popular_videos`. A second connection on the same main, prepared with `attach_trending_override`, must serve B from both. After both reads, `main.trending_ranks` rows must equal what was written. Control: assert A != B. (b) `test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting`: main gets the 30×100 ranked catalogue plus 1,000 unranked rows, built by a builder factored out of the existing plan test, and its `main.trending_ranks` is left empty. The private file gets `prepare_trending_override` and then the ranks. On the prepared connection, `_plan(conn, "trending")` must contain `idx_trending_ranks_order` and no `TEMP B-TREE`. Control: `_plan(conn, "popular")` contains `TEMP B-TREE`. The existing unflagged plan test stays as it is.

**Intent.** `engine/server/data/trending.py` gains `TRENDING_OVERRIDE_SCHEMA`, `prepare_trending_override` and `attach_trending_override`. A connection prepared by `attach_trending_override` takes every unqualified `trending_ranks` read from the attached file, not from main, and its Trending page is still planned as a walk of `idx_trending_ranks_order` with no sort.

- C1 - On a connection prepared by `attach_trending_override`, `fetch_ordered_page` for `trending` and `fetch_popular_videos` serve the attached file's ranks. On an unprepared connection to the same main they serve main's ranks, and main's ranks are left unchanged.
- C2 - On a connection prepared by `attach_trending_override`, the Trending page's query plan uses `idx_trending_ranks_order` and contains no `TEMP B-TREE`.

**Outcome.** ### `engine/server/data/trending.py`
`ensure_trending_schema` is unchanged. Three additions sit next to it, following the plan's draft:
- `TRENDING_OVERRIDE_SCHEMA = "trending_override"`: the schema name the override file is attached under.
- `prepare_trending_override(path)`: opens `file:{path}?mode=rw` with `uri=True`, so a missing file is never created, runs `ensure_trending_schema` on it, and closes the connection. Any `sqlite3.Error` becomes `SystemExit` with a message that names the path. A `rat-tail:` comment records the limit: the path is not URI-escaped, so a `?` or `#` in it fails here, and the fix is `urllib.parse.quote`.
- `attach_trending_override(conn, path)`: runs `ATTACH DATABASE ? AS trending_override` with the path as a bound parameter, then `CREATE TEMP VIEW trending_ranks AS SELECT * FROM trending_override.trending_ranks`. One comment explains why the view is needed: SQLite looks up names in temp, then main, then attached databases, and it flattens the view. A `rat-tail:` comment records the race: on a non-URI connection, ATTACH would recreate a file deleted after the prepare step as an empty file.

What I saw in a probe (pytest's sqlite 3.53.4, the same version as the Engine's): with the override attached, the Trending query's plan is `SCAN trending_override.trending_ranks USING COVERING INDEX idx_trending_ranks_order` followed by `SEARCH e USING COVERING INDEX ...`, with no `TEMP B-TREE`. `prepare_trending_override` on a missing path raised `SystemExit` naming the path and left no file there.

### `tests/active/test_random_videos.py`
Not edited. The checkpoint uses the harness (`_schema`, `_ranks_db`, `_plan`, `RANKS`, `TRENDING_EXPECTED`) exactly as it stands. Moving the checkpoint's two tests and docstring bullets into this file is test-side work, not production code.

**Beyond the files named.** tests/tmp/probe_override_plan.py: a throwaway probe I wrote to check the query plan and the missing-path behaviour before handing in. My tools cannot delete files, so the operator needs to remove it. It fails on purpose with `assert False` so its printed output is shown, and it is not part of the build.
tests/last_test_output.txt and tests/last_test_validation.json: running that probe through `ValidateTests` overwrote both files with the probe's output. The workflow's checkpoint run will overwrite them again.

#### Phase 2 - Engine --trending-db flag [code]

**Files touched.** engine/server/api/server.py (EDITED), tests/active/test_server_config.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the real Engine entry point `engine/server/api/server.py`, run as a subprocess under the Engine interpreter (rung 2) through `test_server_config._run`. This follows `test_server_config.py`'s existing entry-point tests (e.g. `test_server_py_exits_before_argument_parsing_on_a_bad_value`). There is no start lock, because the start must fail before `connect_db`. Test `test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it`. Missing case, `tmp_path / "absent.db"`: assert `returncode != 0`, assert `str(missing)` is in stderr, and assert `not missing.exists()`. Non-SQLite case, `tmp_path / "junk.db"` holding 4 KB of non-SQLite bytes: assert `returncode != 0`, assert the path is in stderr, and assert the file's bytes are unchanged. The timeout is bounded, so a start that wrongly proceeds to load FAISS or bind goes red, not hung. Control: `server.py --help` exits 0 and its stdout contains `--trending-db PATH`. The `tests/config.json` `test_server_config.py` group gains `engine/server/data/trending.py`.

**Intent.** `engine/server/api/server.py` accepts `--trending-db PATH`. `main()` validates PATH before it opens `whitelist.db`, so a PATH that is not an existing SQLite file stops the start, with a message naming it, and leaves the path as it was.

- C1 - Starting `server.py` with `--trending-db` on a missing path or a non-SQLite file exits non-zero, with that path in stderr.
- C2 - The failed start leaves the path as it was: a missing path is not created, and a non-SQLite file's bytes are unchanged.

**Outcome.** ### `engine/server/api/server.py`
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

#### Phase 3 - Active suite on a private Trending seed [code]

**Files touched.** tests/active/conftest.py (EDITED), tests/active/test_similar.py (EDITED)

**Checkpoint.** Seam: the real session Engine over HTTP, through the `engine` fixture in `tests/active/conftest.py`, now started with `--trending-db <trending_seed>`. It follows `test_similar.py`'s existing `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated[trending]` and its `_reference(dataset, ...)`. Test `test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(engine, dataset, shared_trending_before)`. Discrimination control: on a fresh plain `mode=ro` connection, the shared head (`fetch_ordered_page`, first `3 * FEED_PAGE`) differs from `_reference(dataset, "trending", threshold)`. If they are equal, the message says the shared table has no real fill. Trending: three `mode=trending` pages, walked with `exclude`, must equal `_reference(dataset, "trending", ...)[: 3 * FEED_PAGE]`. Popular layer: an unseeded `POST /recommendations?debug=1` with its own rate-bucket header. Every row with `debug.layer == "popular"` must be in `fetch_popular_videos(dataset, POOL)`, with `POOL` read through `_feed_constants` from the Engine's `DEFAULT_POPULAR_POOL_SIZE`. Control: at least one popular row is served. Fingerprint: `shared_trending_fingerprint() == shared_trending_before`, and the failure message names an updater trending-stage run as a possible external cause. The existing ordered-feed and NSFW tests stay green with unchanged expectations.

**Intent.** The active suite's session Engine reads Trending from a per-session private file. `trending_seed` builds that file from the read-only shared catalogue, `engine` passes it as `--trending-db`, and `dataset` carries it, so the suite serves the seeded order without ever writing the shared `whitelist.db` `trending_ranks`.

- C1 - The session Engine's Trending pages and its popular-layer rows follow the private seed file's ranks, not the shared table's.
- C2 - The shared `whitelist.db` `trending_ranks` fingerprint (row count, `fetched_at` min and max, rows with `fetched_at > 0`) is identical before the seed and after the session Engine has served.

**Outcome.** ### `tests/active/conftest.py`
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

**Beyond the files named.** tests/tmp/probe_private_seed.py: a probe file I created and then emptied. I have no tool to delete a file, so it remains as an empty, uncollected file and should be deleted.


