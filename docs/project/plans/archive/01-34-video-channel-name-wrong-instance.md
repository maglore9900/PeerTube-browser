# 34-video-channel-name-wrong-instance

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/01-34-video-channel-name-wrong-instance.record.md`._

## Requirements

### Purpose

Every row in `videos` must carry its own channel's display name in `channel_name`. Today about 74% of rows in both `engine/crawler/data/crawl.db` and `whitelist.db` hold the display name of the channel with the same numeric `channel_id` on another instance. PeerTube channel ids are small per-instance integers, and 49,200 of them repeat across instances. Because of the wrong names, a channel-name search (`videos_fts` indexes `channel_name`) matches another channel's videos, and about 74% of video embeddings carry a foreign channel name (`build-video-embeddings.py` appends `channel: <channel_name>`). The `channels` table holds the correct `display_name` for every `(channel_id, instance_domain)`. Card links are effectively unaffected, because `channel_url` is never empty.

### Root cause (established by triage, confirmed in the tree)

In `engine/crawler/src/videos-worker.ts`, `crawlVideos` builds `channelMeta` as `Map<string, ChannelMeta>` keyed by `channel.channel_id` alone (lines ~163-172). It is built from `store.listChannelsWithVideos(1, hosts)`, which returns channels from every crawled host. `processInstance` looks it up with `channelMeta.get(item.channelId)` (line ~289), again without the host. When an id repeats across hosts, the last listed host wins. That entry's `displayName` then becomes the video row's `channel_name` (resolution around lines 660-662, row written by the upsert in `engine/crawler/src/db.ts`). `sync-whitelist.py` copies `crawl.db` into `whitelist.db`, so both databases carry the fault. The updater's `videos` merge is `INSERT_ONLY`, so it never corrects existing prod rows.

### Requirement 1: Writer fix

- The video crawl's channel-metadata map is keyed on host plus channel id, and every lookup uses both.
- The host part of the key must be in the same form on both sides. The map is built from `channels.instance_domain`. The lookup happens in `processInstance`, which uses `host.toLowerCase()` (`normalizedHost`), while the work item carries `instanceDomain`. The key must match for every channel whose metadata exists, so a normalisation mismatch must not silently drop metadata.
- The channel-name precedence stays as it is: first the crawl channel list's `displayName` (now the correct host's), then the video payload's own `channel.displayName` / `display_name`.
- The crawl slug (`channelSlug`) and `channelUrl` taken from the meta are resolved by the same host-aware key.
- Nothing else in the crawler changes. Issue 27 (seed instance mode) is out of scope.

### Requirement 2: Repair job

- A new operator-runnable Python job in `engine/server/db/jobs/`, following the existing jobs' CLI style (argparse, a `--db <path>` argument, the same docstring and logging conventions as its neighbours, e.g. `sync-whitelist.py`, `recompute-popularity.py`).
- For every `videos` row, it sets `channel_name` to the `display_name` of the `channels` row with the same `(channel_id, instance_domain)`. It does so only where that `display_name` is non-NULL and non-empty and differs from the current `channel_name`. Rows that are already correct, and rows whose channel has an empty or NULL `display_name` (or no channel row), are left untouched.
- It reports the number of rows changed. It is idempotent: a second run changes 0 rows and reports 0.
- It works on both database shapes: the crawler's `crawl.db` schema, which has no `videos_fts` (the crawler source defines no FTS table or triggers), and the Engine's `whitelist.db` schema.
- It does not touch the `channels` table.

### Requirement 3: Search index

- When the target database has `videos_fts` (the `whitelist.db` shape), the repair leaves the index reflecting the corrected names. It reuses the existing helpers in `engine/server/db/jobs/sync-whitelist.py` (`drop_videos_fts_triggers`, `create_videos_fts_triggers`, `rebuild_videos_fts`) rather than writing new FTS code. Those helpers follow the file's bulk pattern: drop the triggers, run the bulk update, recreate the triggers, rebuild. `sync-whitelist.py` has a hyphenated filename, so it cannot be imported by the normal module syntax; reuse it the way other code in the repo already loads hyphenated job modules, or by an equivalent means.
- After the rebuild, the `videos_fts` row count must equal the `videos` row count. The job fails loudly if they differ, matching the check `sync-whitelist.py` already makes.
- Result: an FTS search for a channel's own display name finds that channel's videos. A search for another instance's same-id channel name no longer finds them through `channel_name`.
- When `videos_fts` is absent (`crawl.db`), the job skips the FTS steps without error.

### Requirement 4: Tests (in `tests/active`)

- A crawl fixture with two hosts that share a `channel_id` but have different channel display names. It asserts that each host's videos are written with their own channel's name. This test must fail on today's code. Crawler tests in this repo run the compiled crawler under node (see `tests/active/test_host_normalisation.py`, which runs `engine/crawler/dist/*.js`, and fails rather than skips when node or the dist is missing or stale). The new test follows that convention.
- A repair test on a fixture DB with mismatched `channel_name` values. It checks that each mismatched row is set to its own channel's `display_name`, that already-correct rows and rows whose channel has an empty `display_name` are untouched, and that the reported changed count is correct. A second run must change 0 rows.
- The repair test runs on both schemas: a `crawl.db`-shaped fixture (no FTS) and a `whitelist.db`-shaped fixture (with `videos_fts` and its triggers, created via `sync-whitelist.py`'s `ensure_content_schema` or equivalent).
- An FTS test on the `whitelist.db` fixture, after the repair: a query for the correct channel name returns that channel's videos, a query for the other instance's name does not return them, and `videos_fts` has as many rows as `videos`.
- All fixtures are temporary. No test touches the real `crawl.db` or `whitelist.db`.

### Requirement 5: Runbook

- `DATA_BUILD.md` (which already documents the `crawl.db` and `sync-whitelist.py` steps) gains a section naming the repair command and the order to follow:
  1. Merge to main.
  2. From main, never from a worktree, run the repair against `engine/crawler/data/crawl.db`, then against `whitelist.db`. That means every copy of `whitelist.db`, including the prod/server database, because the updater's `INSERT_ONLY` merge will never correct existing prod rows.
  3. The operator follow-up: `build-video-embeddings.py --force` on `whitelist.db`, then `build-ann-index.py`, then `precompute-similar-ann.py`, scheduled with plan 17's (`docs/project/plans/17-stable-ann-ids.md`) cutover so the index is rebuilt only once.
- The runbook states that the repair is a migration of shared databases and runs on main after merge only.

### Constraints

- The agent must not run the repair against the real `crawl.db` or `whitelist.db`.
- The existing active suite (`tests/active`) stays green, including `test_host_normalisation.py`. Pre-build baseline: the suite exits with code 0.
- Smallest change that works: stdlib only for the Python job, no new dependencies, no new abstractions.

### Out of scope

- Re-embedding, the ANN rebuild and the similarity precompute (operator follow-up only).
- Changing the embedding text in `build-video-embeddings.py`.
- The `channels` table, and the Engine's `/api/video` write-back.
- Issue 27 (crawler seed instance mode).
- `client/frontend/src/components/video-card.ts`: no change.

### Acceptance criteria

- [ ] A two-host shared-`channel_id` crawl fixture writes each host's videos with their own channel's name. The test fails on today's code.
- [ ] The repair corrects mismatched rows, leaves correct rows and empty-`display_name` rows untouched, reports the changed count, and a second run changes 0.
- [ ] After the repair on a `whitelist.db` fixture, an FTS query for the correct name returns the channel's videos, a query for the other instance's name does not, and the `videos_fts` count equals the `videos` count.
- [ ] The repair runs on both the `crawl.db` and `whitelist.db` schemas.
- [ ] The active suite stays green, including the host-normalisation tests.
- [ ] `DATA_BUILD.md` states: merge, then the repair from main on `crawl.db` and on every `whitelist.db` (prod included), then the operator re-embed step.
- [ ] The repair is never run against the real databases by the agent.

## High-level plan

### Approach

Four changes, each tied to a requirement: a keying fix in one function of the crawler, one new Python job, one new test module, and one new runbook section. I read the files each change touches: `videos-worker.ts` (map build, `processInstance`, `processChannel`, `toVideoRow`), `db.ts` (`listChannelsWithVideos`, `prepareVideoProgress`, `listVideoWorkItems`, `listInstances`, the upsert), `http.ts`, `host-filters.ts`, `sync-whitelist.py` (FTS helpers, `ensure_content_schema`, `rebuild_content_tables` and its count check), `recompute-popularity.py`, `test_host_normalisation.py` and `DATA_BUILD.md`.

**Requirement 1 (writer fix).** In `crawlVideos`, the `channelMeta` map gets a composite string key built from the host and the channel id, for example `host/channel_id`. A `/` cannot appear in a normalised host, and a host can carry a `:port`, so the separator cannot collide with a real value. The value type stays `ChannelMeta` and no new type is added. The host part is lowercased on both sides:
- When the map is built, from `channel.instance_domain`.
- At the lookup in `processInstance`, which already holds `normalizedHost = host.toLowerCase()`, together with `item.channelId`.

This follows the host through the code. `processInstance`'s `host` is the grouping key `item.instanceDomain`. That value comes from `video_crawl_progress.instance_domain`, which `prepareVideoProgress` copied verbatim from `channels.instance_domain`. So both sides start from the same column, and applying the same lowercasing to both means a mixed-case stored domain still matches. No metadata can be dropped by a normalisation mismatch.

`processChannel` and `toVideoRow` are unchanged. They already take `meta.channelSlug`, `meta.displayName` and `meta.channelUrl` from the single `meta` handed to them, so all three now come from the correct host's entry. The precedence (crawl list `displayName` first, then the payload's `channel.displayName` / `display_name`) is untouched. Nothing else in the crawler changes. Because `engine/crawler/dist/` is committed, the build is re-run and the regenerated `dist/videos-worker.js` is committed with the source; only that dist file should differ.

**Requirement 2 (repair job).** A new file, `engine/server/db/jobs/repair-video-channel-names.py`, laid out like its neighbours:
- Shebang, a one-paragraph module docstring, and the same `script_dir` / `sys.path` preamble.
- argparse with `CompactHelpFormatter` and `--db PATH`.
- `logging.basicConfig` at INFO and a `main()` behind `if __name__ == "__main__"`.

The repair is one set-based UPDATE on `videos`. It sets `channel_name` from a correlated subquery on `channels` matched by `(channel_id, instance_domain)`, which is the `channels` primary key, so each lookup is indexed. The WHERE clause requires three things of the channel row:
- it exists;
- its `display_name` is non-NULL and not `''`;
- its `display_name` IS NOT the current `channel_name`. `IS NOT` rather than `!=`, so a row whose `channel_name` is NULL is also corrected.

The changed count is the UPDATE cursor's `rowcount`, logged in the neighbours' `key=value` style. Rows that are already correct, rows with an empty or NULL display name, and rows with no channel row never match, so a second run changes 0 rows and reports 0. `channels` is only read.

`--db` is **required**, with no default. Neighbours such as `recompute-popularity.py` default to the crawl DB path, but this job is a migration that is run deliberately against several named databases, and a default would let a bare invocation silently hit one of them.

**Requirement 3 (search index).** The job checks `sqlite_master` for a `videos_fts` table.
- If it is present, the job follows `rebuild_content_tables`' order: `drop_videos_fts_triggers`, the UPDATE, `create_videos_fts_triggers`, then `rebuild_videos_fts`. It then compares the returned count with `COUNT(*)` on `videos` and raises `RuntimeError` with the same wording `sync-whitelist.py` uses if they differ.
- If it is absent (the `crawl.db` shape), only the UPDATE and commit run, and no FTS helper is called.

The helpers are reached by loading `sync-whitelist.py` with `importlib.util.spec_from_file_location` from the job's own directory. This is the loader `test_host_normalisation.py` and `test_similar.py` already use. Loading only runs that module's imports and its `sys.path` setup, because its `main()` is guarded.

When FTS is present, the rebuild and count check run on **every** invocation, even when 0 rows changed. See the first risk below for why.

**Requirement 4 (tests).** One new module, `tests/active/test_channel_names.py`.

- **Crawl test.** Follows `test_host_normalisation.py`'s convention: it fails, rather than skips, when node is missing, the dist is missing, or `dist/videos-worker.js` is older than `src/videos-worker.ts`, using the same git-or-mtime staleness rule and the same build hint.
  - It starts two stdlib `ThreadingHTTPServer`s on 127.0.0.1 with ephemeral ports, so the two hosts are `127.0.0.1:P1` and `127.0.0.1:P2` and no DNS is involved. Each serves `/api/v1/video-channels/<slug>/videos` with its own videos, and the payloads carry no `channel.displayName`.
  - It creates a temp `crawl.db` from `engine/crawler/schema.sql`. It inserts both hosts into `instances`, and one `channels` row per host with the same `channel_id`, different `display_name`s, and `videos_count >= 1`.
  - It runs the compiled `crawlVideos` under node with `concurrency 1`, `maxRetries 0`, a short timeout, and resume, tags and comments off. With `maxRetries 0` the https attempt against the plain-HTTP server fails once and `fetchPage` falls back to http.
  - It asserts that each host's `videos.channel_name` equals its own channel's `display_name`, and also checks `channel_url`.
  - On today's code, one of the two hosts always gets the other's name, whichever order the rows come back in, so the test fails deterministically.
- **Repair tests.** Parametrised over two temp fixtures: a `crawl.db` shape (`schema.sql`) and a `whitelist.db` shape (`ensure_content_schema` from the loaded `sync-whitelist.py`, which creates `videos_fts` and its triggers). Each fixture seeds:
  - mismatched rows (a foreign same-id name);
  - an already-correct row;
  - a row whose channel has an empty `display_name`;
  - a row whose channel has a NULL `display_name`.

  The test runs the job's repair function and asserts the exact changed count, each row's resulting name, and that a second run returns 0. The job is loaded by the same importlib loader. A single subprocess run of the CLI against a temp DB also checks the logged count.
- **FTS test.** On the whitelist fixture after repair: a MATCH on `channel_name` for the correct name returns that channel's videos, a MATCH for the other instance's same-id name does not return them, and `COUNT(*)` on `videos_fts` equals the count on `videos`.
- Every DB is under `tmp_path`, and no test references a real DB path.

**Requirement 5 (runbook).** A new `DATA_BUILD.md` section after step 2, titled as a one-off repair of `channel_name`. It explains in one line why the repair is needed, states that it is a migration of shared databases that runs on main after merge only (never from a worktree), and lists the order:
1. Merge.
2. Run `repair-video-channel-names.py --db engine/crawler/data/crawl.db`.
3. Run it again with `--db` on every copy of `whitelist.db`, the prod/server database included, because the updater's `INSERT_ONLY` merge never corrects existing rows.
4. Operator follow-up, timed with plan 17's cutover so the index is rebuilt once: `build-video-embeddings.py --force` on `whitelist.db`, then `build-ann-index.py`, then `precompute-similar-ann.py`.

The agent never runs the job against the real databases. It is exercised only inside the tests' temp fixtures.

### Alternatives considered

- **Nested `Map<host, Map<channelId, ChannelMeta>>` instead of a composite string key.** Rejected: more code at both the build and the lookup, for a collision risk the `/` separator already rules out.
- **Keying on the raw `instance_domain` on both sides (`item.instanceDomain` at lookup) instead of lowercasing both.** Also correct, since both come from the same column. Rejected: `processInstance` already works in `normalizedHost` and the video rows are written under it, so lowercasing both sides keeps one host form throughout.
- **Updating with the triggers left in place, letting `videos_fts_au` fix the index row by row.** This would be transactional and need no rebuild. Rejected: the requirement asks for the helpers' bulk pattern. It is also fragile, because the per-row `'delete'` reuses the stored old values and would corrupt an index that had already drifted, whereas `rebuild` recovers from drift.
- **A Python row loop with `executemany`, as in `recompute-popularity.py`.** Rejected: one set-based UPDATE is shorter, gives the changed count directly, and is faster on millions of rows.
- **`UPDATE … FROM`.** Rejected: it needs SQLite 3.33 or later, and a correlated subquery works on any SQLite the servers run.
- **Copying the FTS SQL into the new job.** Rejected: the requirement asks for reuse, and a second copy of the trigger SQL would drift from the first.
- **A shared helper module for loading hyphenated jobs.** Rejected: a new abstraction for three lines that the repo already inlines.

### Risks, gotchas and limitations

- **The repair is not a single transaction on the FTS path.** The reused helpers call `executescript`, which COMMITs any open transaction first. So the UPDATE commits when the triggers are recreated, before the rebuild. A crash in between leaves corrected names with a stale index, and a later count mismatch raises after the data is already committed. Mitigation: the rebuild and count check run on every invocation when FTS is present, so re-running the job restores the index even though it reports 0 changed rows.
- **Cost and locking on prod.** The rebuild re-indexes all of `videos_fts` each run. On the prod `whitelist.db` this is a long write that blocks other writers, such as the updater merge. The runbook will tell operators to run it outside an updater cycle.
- **Exact `instance_domain` join.** The repair matches `videos.instance_domain` to `channels.instance_domain` exactly, the same join `sync-whitelist.py` uses. The crawler writes video rows under the lowercased host, while `channels` keeps the stored spelling. A channel stored in mixed case would therefore not be repaired. Hosts are already lowercased by `normalizeHostToken` when they enter the crawl, so this should not occur, but the repair does not guard against it.
- **What counts as "empty".** "Empty `display_name`" means `''`. Whitespace-only names are not specially handled; the channel crawler's `toBoundedString` trims names and turns blanks into NULL, so none are expected.
- **Committed dist.** If `dist/videos-worker.js` is not rebuilt and committed with the source change, the new crawl test fails on staleness by design.
- **Crawl test environment.** The test needs node, `engine/crawler/node_modules` (better-sqlite3) and a built dist, and fails with the build hint when any is missing, as `test_host_normalisation.py` does. It binds to loopback ephemeral ports only.
- **Load-time imports.** Loading `sync-whitelist.py` executes its module-level imports (`scripts.cli_format`, `server_config`, `data.moderation`). The repair job therefore depends on the Engine's server tree being present, which is true everywhere these jobs already run.

### Tradeoffs the operator is asked to accept

- `--db` is required, unlike the neighbours' defaulted `--db`: a small inconsistency in CLI style, in exchange for never repairing a database by accident.
- Every run with FTS present pays a full FTS rebuild, even when nothing changed. The cost is time, and the benefit is that a crashed run is fixed by simply running it again.
- The FTS path is not atomic, because the settled helpers commit internally. Recovery is to re-run, not rollback.
- Until the operator's re-embed, ANN rebuild and precompute are done, embeddings keep carrying the old foreign channel names. Search text is correct straight after the repair; semantic similarity is only corrected at the plan-17 cutover.

## Impacts


<impacts>
<impact path="engine/crawler/src/videos-worker.ts" element="crawlVideos(): the channelMeta map build (lines 163-172)">
**What changes.** The map key changes from `channel.channel_id` to a composite string: `channel.instance_domain.toLowerCase()`, then `/`, then `channel.channel_id`. The value (`ChannelMeta`: `channelSlug`, `displayName`, `channelUrl`) and the type `Map<string, ChannelMeta>` do not change.

**What depends on it.**
- `channels` comes from `store.listChannelsWithVideos(1, hosts)` (db.ts:1265-1278), optionally sliced by `maxChannels`. That query returns rows from every crawled host and filters `channel_name IS NOT NULL`, which is why ids collide across hosts.
- The map is passed unchanged through `workerLoop` (line 191) into `processInstance`.
- The same `channels` array feeds `store.prepareVideoProgress(channels, ...)` (line 175), so every work item has a matching map entry under the raw `instance_domain`.

**Regression risk: low.**
- Two `channels` rows could differ only by the case of `instance_domain` while sharing a `channel_id`. Their lowercased keys would collide and the last one listed would win. That is the old bug in a much narrower form. Hosts are normalised to lowercase by `normalizeHostToken` on entry, so such rows are not expected. I did not check the real DB for them.
- The key string must be built the same way here and at the lookup. A mismatch, for example lowercasing only one side or using a different separator, silently gives `meta === undefined`. The name then falls back to the payload's `channel.displayName`, which the new test's payloads deliberately omit, so the test would catch this.
</impact>
<impact path="engine/crawler/src/videos-worker.ts" element="processInstance() lookup `channelMeta.get(item.channelId)` (line 289)">
**What changes.** The lookup becomes `channelMeta.get(`${normalizedHost}/${item.channelId}`)`, where `normalizedHost = host.toLowerCase()` (line 285) is already in scope.

**What depends on it.**
- `host` is the key of `grouped`, which `groupByInstance` (lines 707-715) builds from `item.instanceDomain`. That value comes from `video_crawl_progress.instance_domain` (`listVideoWorkItems`, db.ts:1399-1424), which `prepareVideoProgress` (db.ts:1328-1346) copied verbatim from `channels.instance_domain`. Both sides of the key therefore start from the same column, as the plan says.
- `meta` is handed to `processChannel` (line 290).

**Regression risk: low.** This is the one line that fixes the bug. `workerLoop` and the `channelMeta` parameter types in `workerLoop` (line 260) and `processInstance` (line 280) keep their signatures.
</impact>
<impact path="engine/crawler/src/videos-worker.ts" element="processChannel() (lines 425-468): slug and meta use">
**What changes.** Nothing in the code. What `meta` holds changes.

**Correction to the plan.** The plan says the slug "now comes from the correct host's entry". In fact `channelSlug = item.channelName ?? meta?.channelSlug` (line 433): the slug is taken first from the per-host progress row. `prepareVideoProgress` writes that row's `channel_name`, and `listChannelsWithVideos` only returns channels where it is non-NULL. The slug was therefore already correct, and `meta.channelSlug` is a dead fallback in practice. The fix really changes only `displayName` and `channelUrl`, both passed on at lines 450-451.

**Regression risk: none.**
</impact>
<impact path="engine/crawler/src/videos-worker.ts" element="toVideoRow() channel name and URL resolution (lines 660-664)">
**What changes.** Nothing in the code.
- `channelName = toBoundedString(channel.displayName) ?? toBoundedString(channelRef?.displayName ?? channelRef?.display_name)`. The precedence is unchanged, as required, and the first term now comes from the correct host.
- `channelUrl = toHttpUrlOrNull(channelRef?.url) ?? toHttpUrlOrNull(channel.channelUrl)`. The payload's own `channel.url` comes FIRST here, so `meta.channelUrl` is only a fallback.

**What depends on it.**
- `upsertVideos` (db.ts:1453) writes the row.
- The ON CONFLICT clause (db.ts:1169-1195) overwrites `channel_name` and `channel_url` on every re-crawl, so after the fix a fresh crawl of `crawl.db` corrects rows by itself.

**Regression risk: low.**
- **The test's `channel_url` check.** It only exercises the fix if the fixture payload has no `channel.url`. Otherwise the payload URL wins whatever key is used.
- **The URL value.** The fixture's `channels.channel_url` must be an absolute http(s) URL, or `toHttpUrlOrNull` returns NULL.
- **Trimming.** `toBoundedString` trims the name and caps it at 200 characters, so the fixture's display names should be short and untrimmed, or the test's equality check fails.
</impact>
<impact path="engine/crawler/src/videos-worker.ts" element="fetchPage() https→http fallback (lines 581-619) and buildChannelVideosUrl() (624-636), used by the new crawl test">
**What changes.** Nothing.

**How the test reaches its fake servers.**
- `crawlChannelVideos` starts with `protocol = "https:"`. Against a plain-HTTP `ThreadingHTTPServer`, Node's fetch fails the TLS handshake, typically with EPROTO or `ERR_SSL_WRONG_VERSION_NUMBER`. Those codes are not in `isNoNetworkError`'s list, so no curl fallback runs.
- With `maxRetries: 0`, `fetchJsonWithRetry` throws after the first attempt (`attempt > maxRetries`). The catch then retries over `http:` with `maxRetries: Math.max(1, 0) = 1`, so the http leg gets one retry with a 1000 ms backoff on error.
- The protocol is kept for later pages.
- The URL path is `/api/v1/video-channels/<encodeURIComponent(slug)>/videos?start=0&count=50&sort=-publishedAt`. The fake server must match the path and ignore the query.
- Pagination stops when `nextStart >= page.total`, or when `data.length < 50` if `total` is absent. The fixture should send `total` equal to its video count.

**Regression risk: none to production.** For the test there is one flake path. If the https attempt ever fails with ECONNREFUSED or ETIMEDOUT, `fetchJsonWithRetry` calls `fetchViaCurl` (http.ts:73-78), then throws `NoNetworkError`. `processChannel` then records an error, and no rows are written. Binding to 127.0.0.1 and keeping the server alive for the whole run avoids this.
</impact>
<impact path="engine/crawler/dist/videos-worker.js" element="compiled crawlVideos channelMeta build (lines 40-47) and processInstance lookup (line 126)">
**What changes.** It is regenerated by `npm run build` (`node node_modules/typescript/bin/tsc -p tsconfig.json`) and committed together with the source. The dist is tracked: the root `.gitignore` ignores only `node_modules`, `*.db` and `.un/`.

**What depends on it.**
- Production runs the dist, not the source. The updater runs `crawler_dist / "videos-cli.js"` (updater-worker.py:805, 954), and `npm run crawl:videos` and `scripts/run-dataset-build.sh` go through `dist/videos-cli.js`. So without the rebuild, the fix never reaches staging or prod crawls.
- The new crawl test imports this file.

**Regression risk: medium, for the build process.**
- `tsc` recompiles all of `src/` into `dist/`. The plan says "only that dist file should differ", and that holds only if the other committed dist files are already in step with their sources. I compared only the `videos-worker` lines at issue, which currently match the source.
- `tsconfig` emits no source maps or declarations, so no extra files appear.
- The staleness rule compares the git commit times of `src/videos-worker.ts` and this file. If both are committed together, the times are equal and the dist is not stale.
</impact>
<impact path="engine/crawler/src/db.ts" element="VideoStore: listInstances (1241), listChannelsWithVideos (1265-1278), prepareVideoProgress/pruneVideoProgress (1328-1394), listVideoWorkItems (1399-1424), upsertStmt (1138-1196), constructor/applyBaseSchema (1131-1137, reads ../schema.sql at line 24)">
**What changes.** Nothing.

**What depends on it.** The key-normalisation reasoning and the crawl test fixture.
- **Instance match.** `listInstances` returns `instances.host` as stored. `listChannelsWithVideos` matches `instance_domain IN (hosts)` exactly, so the fixture's `instances.host` must equal `channels.instance_domain` byte for byte (`127.0.0.1:P1`).
- **Required channel fields.** Each channel needs `videos_count >= 1` and a non-NULL `channel_name` (the slug).
- **Constructor side effects.** The constructor sets `journal_mode = WAL`, so `-wal` and `-shm` files appear beside the temp DB. It also runs `applyBaseSchema` and migrations, so a DB created from `schema.sql` is already compatible.
- **Module-level read.** `db.js` reads `../schema.sql` relative to itself at import (line 24), which resolves to `engine/crawler/schema.sql`.

**Regression risk: none.**
</impact>
<impact path="engine/crawler/src/videos-cli.ts" element="crawlVideos option mapping (lines 87-107)">
**What changes.** Nothing.

**What depends on it.** It is the reference for the full `VideoCrawlOptions` object the new test must build when it imports `crawlVideos` directly. The object has 18 keys:
- `dbPath`
- `excludeHostsFile: null`
- `existingDbPath: null`
- `concurrency`
- `timeoutMs`
- `maxRetries`
- `newOnly: false`
- `stopAfterFullPages: 0`
- `sort: "-publishedAt"`
- `maxInstances: 0`
- `maxChannels: 0`
- `maxVideosPages: 0`
- `tagsOnly: false`
- `updateTags: false`
- `commentsOnly: false`
- `hostDelayMs: 0`
- `resume: false`
- `errorsOnly: false`

The alternative is to run `dist/videos-cli.js --db ... --max-retries 0 --timeout N --concurrency 1`, which needs `commander` from `node_modules`.

**Regression risk: none.** A missing option key is `undefined` in JS, so `sort: undefined` would still fall back to `-publishedAt` inside `buildChannelVideosUrl`.
</impact>
<impact path="engine/crawler/src/http.ts" element="fetchJsonWithRetry() (55-133), isNoNetworkError() (37-53), fetchViaCurl() (138-161)">
**What changes.** Nothing.

**What depends on it.** The crawl test's single https failure and its fall back to http. See the fetchPage entry.
- `setDefaultResultOrder("ipv4first")` runs at import. It is harmless for 127.0.0.1.
- Node's fetch does not use `HTTP(S)_PROXY` by default, so a proxy environment should not reroute loopback requests.

**Regression risk: none.**
</impact>
<impact path="engine/crawler/src/host-filters.ts" element="toBoundedString (48-56), toHttpUrlOrNull (68-78), normalizeHostToken (83-100)">
**What changes.** Nothing.

**What depends on it.**
- The name and URL sanitising in `toVideoRow`.
- The plan's claim that hosts are lowercased when they enter the crawl. `normalizeHostToken` lowercases, and branch 4 keeps `:port`. That is why a `/` separator cannot collide with a stored host.

**Regression risk: none.** `test_host_normalisation.py` pins this file's dist copy, and nothing here changes.
</impact>
<impact path="engine/crawler/schema.sql" element="instances / channels / videos / video_crawl_progress tables">
**What changes.** Nothing.

**What depends on it.**
- The crawl.db-shape fixtures in the new test are created from it.
- `sync-whitelist.py` parses its `instances`, `channels` and `videos` blocks at import (sync-whitelist.py:36, 92-96), and the repair job loads that module. So the repair job now depends on this file existing, even when run against `whitelist.db`.
- `channels` has `PRIMARY KEY (channel_id, instance_domain)` (line 26), which makes the repair's correlated subquery an index lookup.
- `videos.channel_id` is nullable (line 34). Rows with a NULL `channel_id` never match the repair.

**Regression risk: low.** If the file moves, the repair job fails at load.
</impact>
<impact path="engine/server/db/jobs/repair-video-channel-names.py" element="new job (whole module)">
**What changes.** A new file.

**Layout, following its neighbours:**
- Shebang, then a docstring.
- The `script_dir` / `sys.path` preamble. `sync-whitelist.py:16-22` inserts both `engine/server` and `engine/server/api`. `recompute-popularity.py:10-11` appends `engine/server` and adds `api` lazily.
- argparse with `CompactHelpFormatter` (`engine/server/scripts/cli_format.py`, which exists).
- `logging.basicConfig(level=logging.INFO, ...)`. Note the neighbours' formats differ: `"%(levelname)s: %(message)s"` in sync-whitelist and `"%(levelname)s %(message)s"` in recompute-popularity.
- A guarded `main()`.
- `--db` is required, with `metavar="PATH"`.

**The repair.** One `UPDATE videos SET channel_name = (SELECT c.display_name FROM channels c WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain) WHERE EXISTS (SELECT 1 FROM channels c WHERE <same join> AND c.display_name IS NOT NULL AND c.display_name <> '' AND c.display_name IS NOT videos.channel_name)`. The changed count is `cursor.rowcount`.

**The FTS branch.**
- It is taken when `sqlite_master` has a table named `videos_fts`, the same probe as `search.fts_available`.
- It calls `drop_videos_fts_triggers`, then the UPDATE, `create_videos_fts_triggers`, `rebuild_videos_fts` and the count check.
- The check raises `RuntimeError` with sync-whitelist's wording (lines 518-521).

**Correction to the plan.** The plan says neighbours "such as `recompute-popularity.py` default to the crawl DB path". They do not. `server_config.DEFAULT_DB_PATH` is `"engine/server/db/whitelist.db"` (server_config.py:363), and recompute-popularity defaults to that path. So does sync-whitelist's `DEFAULT_SOURCE_DB_PATH`. A default here would silently hit the shared `whitelist.db`, which is an even stronger reason for `--db` to be required.

**The loader is new in production code.** No file under `engine/` uses `importlib` today (grep: no matches). The `spec_from_file_location` precedent is in tests only (`test_host_normalisation.py:78-82`, `test_similar.py:72, 298`). This job is the first production module to load a sibling hyphenated job, which is acceptable but worth knowing.

**Load-time dependencies of sync-whitelist.py.**
- `scripts.cli_format`
- `server_config`, whose only import is `os`
- `data.moderation`, stdlib only
- the parse of `engine/crawler/schema.sql`

All are stdlib-only, so the job stays stdlib-only.

**Transactions.** `executescript` in the helpers COMMITs any pending implicit transaction.
- **Order.** Triggers dropped (commit), then the UPDATE, which opens an implicit transaction. `create_videos_fts_triggers` commits the UPDATE and the new triggers. `rebuild_videos_fts` runs inside a new implicit transaction that the job must `commit()` explicitly, or it is rolled back on close.
- **crawl.db path.** Also needs an explicit `commit()`.
- **When `rowcount` must be read.** Before any `executescript`.

**What depends on it.** The operator runbook and the new tests.

**Regression risk: medium, operationally.** It rewrites shared databases. See the entries for `sync-whitelist.py`, the prod `whitelist.db` writers and `search.py`.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="FTS helpers create_videos_fts_triggers (294-296), drop_videos_fts_triggers (299-306), rebuild_videos_fts (309-320), VIDEOS_FTS_TRIGGERS_SQL (270-285), ensure_content_schema (323-417), and the count check in rebuild_content_tables (511-521)">
**What changes.** Nothing. The repair job and the new test reuse these helpers.

**What depends on it.**
- The new job and the whitelist-shape test fixture. `ensure_content_schema` creates `channels`, `videos`, `video_embeddings`, `videos_fts` (fts5, `content='videos'`) and the triggers.
- Note the fixture shape. The whitelist `channels` table has no NOT NULL besides the keys. The whitelist `videos` table has `popularity REAL NOT NULL DEFAULT 0` and `last_checked_at INTEGER NOT NULL`, so the fixture inserts must supply `last_checked_at`.
- `rebuild_videos_fts` issues the `'rebuild'` command and returns `COUNT(*)` from `videos_fts`. On an external-content table that count reflects the content table, so the equality check is a weak guard. It matches sync-whitelist's own check, as required.

**Regression risk: low.**
- The helpers use `executescript`, whose commit behaviour is described in the job's entry.
- If a later edit makes any helper non-idempotent, or makes `ensure_content_schema` do more, the repair job and test inherit that change silently. This is a coupling the build accepts in exchange for reuse.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="module top level: sys.path mutation (16-22), imports (24-26), DEFAULT_SOURCE_DB_PATH (31), SCHEMA_SQL_PATH and *_COLUMNS parsed at import (36, 92-96), __main__ guard (676)">
**What changes.** Nothing.

**What depends on it.**
- Loading this module from the repair job runs this top-level code.
- It leaves `engine/server` and `engine/server/api` on `sys.path`.
- `main()` is guarded, so no sync runs.
- `SCHEMA_SQL_PATH` is `script_dir.parents[3] / "engine/crawler/schema.sql"`, which resolves correctly from the jobs directory.

**Regression risk: low.** It fails loudly at load if `schema.sql` or the server tree is missing.
- **Module name.** The job should load it under an identifier-like name distinct from the test's `sync_whitelist_job`. Two module objects are harmless; the module defines no dataclass, so no `sys.modules` registration is needed.
- **`conftest.py` interaction.** It imports `client/backend/server.py` as `server` first. The `engine/server/api/server.py` on `sys.path` does not shadow it, because the module is already cached. This is the same situation as the existing tests.
</impact>
<impact path="engine/server/db/jobs/recompute-popularity.py" element="style reference: preamble, argparse, logging, --db default">
**What changes.** Nothing.

**What depends on it.** It is the style reference for the new job.
- The log line style is `"popularity updated rows=%d"` (line 121). The new job's key=value line should match, for example `channel names repaired rows=%d`. The CLI subprocess test can then parse the count.
- Its `--db` default is `whitelist.db` (see the correction in the job entry).

**Regression risk: none.**
</impact>
<impact path="engine/server/db/whitelist.db (prod/server copy) and its concurrent writers: engine/server/api/handlers/video.py (UPDATE videos ... channel_name, lines 305-343) and engine/server/db/jobs/merge-staging-db.py (INSERT OR IGNORE, lines 162-190)">
**What changes.** Nothing in the code. The repair will be run by the operator against live `whitelist.db` copies.

**What depends on it.**
- **The Engine's `/api/video` write-back.** It rewrites `videos.channel_name` and `channels.display_name` from the live instance, under `server.db_lock`, inside a try. It is the only other writer of `channel_name`.
- **The updater merge.** It inserts `videos` INSERT_ONLY and fires `videos_fts_ai`.

**Regression risk: medium, operational.**
- **Missed triggers.** While the triggers are dropped, rows written by the Engine or the merge skip the per-row FTS maintenance. The following `rebuild` covers them, so the end state is correct.
- **Lock contention.** The full rebuild holds the write lock for a long time on the ~890k-row prod DB. The Engine's write-back will hit `database is locked` (caught by its try), and a concurrent updater merge may fail. The runbook must say to run the repair outside an updater cycle, and ideally with the Engine idle or stopped.
- **`channels` is INSERT_ONLY too** (merge_rules.json:9-12). Prod `channels.display_name` is therefore the first-inserted value, possibly refreshed by `/api/video`. It is still the correct host's name, so the repair source is sound.
- **Migrated but not re-synced DBs.** `whitelist_migrations.migrate_videos_schema` (lines 260-265) drops `videos_fts`, and only the next `ensure_content_schema` recreates it. On such a copy the repair takes the no-FTS branch, and search is already disabled by `fts_available`.
</impact>
<impact path="engine/server/db/jobs/merge_rules.json" element="videos / channels strategy INSERT_ONLY (lines 8-17)">
**What changes.** Nothing.

**What depends on it.** It is why the repair must run on every `whitelist.db` copy: a merge never overwrites existing prod rows, so fixing staging or `crawl.db` does not propagate to prod. `test-orchestrator-smoke.py:793-809` asserts this invariant.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/search.py" element="fts_available() (121-131), lexical_candidates() (134-164)">
**What changes.** Nothing.

**What depends on it.** It reads `videos_fts MATCH ?` joined to `videos` by rowid. After the repair, lexical search on `channel_name` returns the correct channel's videos. This is the user-visible outcome that the new FTS test checks directly with MATCH, bypassing this module.

**Regression risk: low.** During the repair window (triggers dropped, rebuild in progress), searches may see a stale index or wait on the lock.
</impact>
<impact path="engine/server/db/jobs/build-video-embeddings.py" element="embedding text builder (lines 40-54, query 189-205)">
**What changes.** Nothing. Changing it is out of scope.

**What depends on it.** It appends `channel: <channel_name>`. Existing vectors keep the foreign names until the operator runs `--force`, then `build-ann-index.py` and `precompute-similar-ann.py`.

**Regression risk: none from the code.** It is listed because the runbook's follow-up step depends on it.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="crawler invocation of dist/videos-cli.js (lines 805, 954) and staging merge (1055)">
**What changes.** Nothing.

**What depends on it.** Once the rebuilt dist is merged, updater crawls write correct names into staging. The merge then inserts only new rows into prod, which is why existing prod rows still need the repair.

**Regression risk: none.**
</impact>
<impact path="scripts/run-dataset-build.sh" element="full pipeline: crawl → sync-whitelist (228) → embeddings (236) → ANN (244) → precompute (253)">
**What changes.** Nothing. The repair is a one-off migration and is not added to the pipeline.

**What depends on it.** A full rebuild after the fix, re-crawl plus sync, produces correct names without the repair job.

**Regression risk: none.** I list it because an operator might ask whether the job belongs here. It does not: a fresh crawl with the fixed writer gets names right, and the ON CONFLICT upsert overwrites `channel_name`.
</impact>
<impact path="tests/active/test_channel_names.py" element="new test module: crawl test, parametrised repair tests, FTS test, CLI subprocess test">
**What changes.** A new file.
- **Header.** It imports `ROOT` from `conftest` and adds `engine/server` to `sys.path`, as `test_host_normalisation.py:19-23` does.
- **Loader.** It loads `repair-video-channel-names.py` (and `sync-whitelist.py` for `ensure_content_schema`) with an inline `_load_job`, a copy of `test_host_normalisation.py:78-82`.

**Crawl test.**
- **Gates.** It copies the node / dist-missing / git / staleness gates of `test_host_normalisation.py:48-70`: `_git`, `_dist_is_stale`, `BUILD_HINT = "cd engine/crawler && npm install && npm run build"`. SRC and DIST point at `videos-worker.ts` / `.js`.
- **What else the gates must cover.** Unlike `host-filters.js`, `dist/videos-worker.js` imports `better-sqlite3` (and `./db.js`, which reads `schema.sql`). The node process therefore also needs `engine/crawler/node_modules`. The test should fail with the build hint when node cannot import it, for example by asserting returncode 0 with stderr in the message.
- **Node script.** `node --input-type=module -e` with `await import(<dist uri>)`, then `crawlVideos({...})`, with `cwd=engine/crawler` so bare-specifier resolution finds `node_modules`. Resolution goes from the dist file's location, so cwd matters less, but setting it is safe.
- **Servers.** Two `ThreadingHTTPServer`s on `("127.0.0.1", 0)`, each in a daemon thread and shut down in `finally`.
- **Assertions.** Per host, `channel_name` equals its own `display_name`. `channel_url` equals its own channel's URL, which requires the payload to have no `channel.url`.

**Repair tests.**
- **Parametrisation.** Over a crawl-shape fixture (`schema.sql` via `executescript`) and a whitelist-shape fixture (`ensure_content_schema`).
- **Seeded rows.** Mismatched, already-correct, empty and NULL `display_name`. The plan should also seed a video with no `channels` row, which the requirements name.
- **Assertions.** The exact count, each row's value, and 0 on the second run.

**CLI test.** One subprocess run with `sys.executable`, parsing the `rows=N` log line.

**FTS test.** MATCH on the correct name versus the foreign name, and `COUNT(videos_fts) == COUNT(videos)`.
- **MATCH syntax.** It must use a column filter (`channel_name : "..."`, quoted as a phrase). A bare MATCH on the old name could also hit the title or description if the fixture text contains it. Fixture names should be distinctive single-token strings.
- **Why the foreign name disappears.** The foreign-name query no longer returning the videos depends on the rebuild re-tokenising. In an external-content table, stale tokens would otherwise remain.

**What depends on it.** `validate_tests.py` discovers `tests/active/test_*.py` automatically. It has no mapping in the local `.un/skills/devsecops/config.json`, which is gitignored and outside this read, so until harvest it runs on every invocation.

**Regression risk: medium, for suite stability.**
- The node, `node_modules` and dist gates can go red on machines without the crawler installed. `test_host_normalisation.py` needs node but not `node_modules`, so this is a new, stricter requirement.
- I could not verify that `engine/crawler/node_modules` exists in this worktree. The read was refused as outside the project, which suggests a symlink to another checkout.
- The crawl needs an https failure, then an http success, per channel. With the default 5000 ms timeout a TLS failure is immediate, so the runtime stays small.
- Every DB must be under `tmp_path`. It must never request the `engine` or `dataset` fixtures, which open the shared `whitelist.db`.
</impact>
<impact path="tests/active/test_host_normalisation.py" element="gate helpers _git/_dist_is_stale (48-61), test_crawler_dist_returns_pinned_values (64-75), _load_job (78-82)">
**What changes.** Nothing. The new test copies these patterns inline, as the plan chooses.

**What depends on it.** It must stay green. It checks `host-filters.ts` / `.js`, and the rebuild regenerates `dist/host-filters.js` too.
- If the regenerated `host-filters.js` differs from the committed one, it gets a new commit time. That is harmless, since the dist is then newer than the source.
- If the rebuild is committed with `host-filters.ts` unchanged, nothing changes for this test.

**Regression risk: low.** The staleness rule is by commit time, so rebuilding and committing only `videos-worker.js` cannot make it stale.
</impact>
<impact path="tests/active/conftest.py" element="module-level Client backend import (37-43), ROOT (31), WHITELIST_DB (34)">
**What changes.** Nothing.

**What depends on it.** The new test imports `ROOT`. `WHITELIST_DB` is the shared dataset and must not be used.

**Regression risk: none.**
</impact>
<impact path="tests/last_test_validation.json" element="tracked suite record (also tests/last_test_output.txt)">
**What changes.** Both files are rewritten by the post-build `validate_tests.py` run.

**What depends on it.** The comparison against the green baseline.

**Regression risk: none functionally.** They conflict on merge. Take main's copy and re-run the comparison.
</impact>
<impact path="client/frontend/src/components/video-card.ts" element="channel_name fallback (line ~142)">
**What changes.** Nothing. It is explicitly out of scope.

**What depends on it.** It reads `videos.channel_name` only when `channel_url` is empty, which applies to 0 rows per triage.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="local `channelMeta` / fetchChannelMetadata (599-630)">
**What changes.** Nothing.

**Why it is listed.** It is an unrelated same-named identifier that a `channelMeta` grep hits. It is recorded only so no one edits it by mistake.

**Regression risk: none.**
</impact>
</impacts>


## Documentation to update

- [x] `DATA_BUILD.md` - updated: Added a "Repair video channel names (one-time migration)" subsection to `DATA_BUILD.md` at the end of step 2. It gives the repair command, the order to run it in, and how it behaves.
- [x] `docs/project/issues/34-video-channel-name-wrong-instance.md` - updated: Issue 34 is marked complete with a Delivered record, its wrong claims are corrected, and six of its seven criteria are ticked. **It is still in `docs/project/issues/`: please run `git mv docs/project/issues/34-video-channel-name-wrong-instance.md docs/project/issues/archive/`**, because I have no tool that can move or delete files.
- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - out of scope: It never mentions `channel_name`, the repair, or `INSERT_ONLY` by name. Its claims (line 71: prod gets merged changes according to `merge_rules.json`; line 88: the worker stops the Engine around the merge) are still true, because the build changed no updater, merge or rule behaviour. The operational guidance (INSERT_ONLY means every prod `whitelist.db` must be repaired directly, and no repair during an updater cycle) goes in the new DATA_BUILD.md section, so the optional note would duplicate it.
- [x] `docs/project/issues/plan.md` - out of scope: It is a sequencing plan. Its lines on issue 34 (line 62: the repair runs on main after the merge; line 150: migrations run on main after merge) are still accurate descriptions of the intended order. It says nothing about the writer or the repair that the build made false. Issue status is tracked in the issue file.
- [x] `CONTEXT.md` - out of scope: The glossary's only channel-related term is **Block** (`instance_domain` + `channel_id`), which the build does not touch. It defines no term for `channel_name`, the crawler's channel metadata, or data repairs, and the build introduces no new domain concept that needs a glossary entry.

## Implementation plan

## Draft implementation: issue 34, `videos.channel_name` taken from another instance's channel

The draft was checked against the plan and the requirements in one pass and they converged, so no operator decision was needed. Before drafting I read `videos-worker.ts` (lines 150-300 and 420-700), `dist/videos-worker.js` (lines 1-130), `db.ts` (lines 1236-1425), `http.ts` (lines 30-165), `schema.sql`, `sync-whitelist.py` (lines 1-60, 265-424 and 495-530), `recompute-popularity.py`, `test_host_normalisation.py` and `DATA_BUILD.md` (lines 125-250).

### What changes

| Path | Change | Requirement |
|---|---|---|
| `engine/crawler/src/videos-worker.ts` | Two lines change: the map key where it is built, and the key at the lookup | R1 |
| `engine/crawler/dist/videos-worker.js` | Regenerated with `npm run build` and committed with the source | R1 |
| `engine/server/db/jobs/repair-video-channel-names.py` | New job | R2, R3 |
| `tests/active/test_channel_names.py` | New test module | R4 |
| `DATA_BUILD.md` | New section `## 2b)` placed between steps 2 and 3 | R5 |

### Two corrections to the plan (they change nothing in scope)

- **The slug was already correct.** `processChannel` reads the slug as `item.channelName ?? meta?.channelSlug` (videos-worker.ts:433), and `item.channelName` comes from the progress row for that host. The fix therefore changes only `displayName`, and `channelUrl`, which is the fallback after the payload's own `channel.url`.
- **The neighbouring jobs default to `whitelist.db`, not `crawl.db`.** `server_config.DEFAULT_DB_PATH` is `engine/server/db/whitelist.db`. That makes a required `--db` even more important.

---

### 1. Writer fix: `engine/crawler/src/videos-worker.ts`

At the map build (lines 163-172), only the key expression changes:

```ts
  const channelMeta = new Map<string, ChannelMeta>(
    channels.map((channel) => [
      `${channel.instance_domain.toLowerCase()}/${channel.channel_id}`,
      {
        channelSlug: channel.channel_name,
        displayName: channel.display_name,
        channelUrl: channel.channel_url
      }
    ])
  );
```

At the lookup in `processInstance` (line 289), only the key changes:

```ts
    const meta = channelMeta.get(`${normalizedHost}/${item.channelId}`);
```

**Why the two keys always match.** The key is `lower(instance_domain) + "/" + channel_id`, and both sides build it from the same column:

- The map side builds it from `channels.instance_domain`.
- The lookup side uses `normalizedHost = host.toLowerCase()`. Here `host` comes from `groupByInstance(item.instanceDomain)`. That value is `video_crawl_progress.instance_domain`, which `prepareVideoProgress` copied verbatim from `channels.instance_domain`.

A normalised host cannot contain `/` (a `:port` is allowed), so the separator cannot make two different pairs produce the same key.

**What stays the same:**
- The value type `ChannelMeta` and the `Map<string, ChannelMeta>` signatures in `workerLoop` (line 260) and `processInstance` (line 280).
- `processChannel` and `toVideoRow`.
- The name precedence in `toVideoRow` (lines 660-662): the crawl list's `displayName` first, then the payload's `channel.displayName` / `display_name`.

**Dist.** Run `cd engine/crawler && npm run build`. The expected diff in `dist/videos-worker.js` is line 41 (`channel.channel_id,` becomes the same template literal) and line 126 (the `.get(...)` key). Any other file that `tsc` rewrites under `dist/` was already out of step with its source. That drift is reported at commit time, not folded silently into this change.

---

### 2 and 3. Repair job: `engine/server/db/jobs/repair-video-channel-names.py`

```python
#!/usr/bin/env python3
"""Repair videos.channel_name from the channel row on the video's own instance.

The video crawler once looked up channel metadata by channel_id alone, so where PeerTube's per-instance channel ids repeat across instances a video took the display name of another instance's channel. This one-off migration sets each video's channel_name to the display_name of the channels row with the same (channel_id, instance_domain), and rebuilds videos_fts when the database has one.
"""
import argparse
import importlib.util
import logging
import sqlite3
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from scripts.cli_format import CompactHelpFormatter

REPAIR_SQL = """
UPDATE videos
SET channel_name = (
  SELECT c.display_name FROM channels c
  WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain
)
WHERE EXISTS (
  SELECT 1 FROM channels c
  WHERE c.channel_id = videos.channel_id
    AND c.instance_domain = videos.instance_domain
    AND c.display_name IS NOT NULL
    AND c.display_name <> ''
    AND c.display_name IS NOT videos.channel_name
);
"""


def _load_sync_whitelist():
    """Load sync-whitelist.py, whose hyphenated name rules out a normal import, for its videos_fts helpers."""
    spec = importlib.util.spec_from_file_location("sync_whitelist_for_repair", script_dir / "sync-whitelist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_videos_fts(conn: sqlite3.Connection) -> bool:
    """Whether the database carries the videos_fts index (the whitelist.db shape; crawl.db has none)."""
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'videos_fts'").fetchone()
    return row is not None


def repair_channel_names(conn: sqlite3.Connection) -> int:
    """Set each video's channel_name to its own channel's display_name and return the number of rows changed.

    Rows that already match, and rows whose channel has a NULL or empty display_name or no channels row, are left alone, so a second run returns 0. channels is only read. When videos_fts exists, the update runs between sync-whitelist.py's trigger drop and recreate, and the index is rebuilt and its count checked on every run, even when nothing changed. The helpers use executescript, which commits, so the update is already committed before the rebuild: a failed rebuild is recovered by running the job again, not by rollback.

    :param conn: Connection to a crawl.db or whitelist.db.
    :returns: Number of videos rows whose channel_name changed.
    """
    if not has_videos_fts(conn):
        changed = conn.execute(REPAIR_SQL).rowcount
        conn.commit()
        return changed
    sync = _load_sync_whitelist()
    sync.drop_videos_fts_triggers(conn)
    changed = conn.execute(REPAIR_SQL).rowcount
    sync.create_videos_fts_triggers(conn)
    fts_count = sync.rebuild_videos_fts(conn)
    videos_count = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    if fts_count != videos_count:
        raise RuntimeError(
            f"videos_fts holds {fts_count} rows but videos holds {videos_count}; "
            "the full-text index did not rebuild cleanly."
        )
    conn.commit()
    return changed


def main() -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(
        description="Repair videos.channel_name from the channel on each video's own instance.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--db",
        required=True,
        metavar="PATH",
        help="Path to the crawl.db or whitelist.db to repair (required; there is no default).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db_path = Path(args.db)
    if not db_path.is_file():
        parser.error(f"database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        changed = repair_channel_names(conn)
    finally:
        conn.close()
    logging.info("channel names repaired rows=%d", changed)


if __name__ == "__main__":
    main()
```

**What the job guarantees.**
- **Changed count.** `rowcount` is read immediately after the UPDATE. The UPDATE runs in Python's implicit transaction, and no `executescript` has run yet at that point.
- **NULL names.** The WHERE uses `IS NOT`, so a row whose `channel_name` is NULL is corrected too.
- **Rows that can never match:** a NULL `videos.channel_id`, a channel with no row in `channels`, or a channel whose `display_name` is NULL or `''`.
- **Index lookup.** The correlated subqueries join on the `channels` primary key `(channel_id, instance_domain)`, so each lookup uses the index.
- **Idempotence.** After one run, every row that could match has `channel_name == display_name`, so a second UPDATE matches 0 rows.

**Design decisions.**
- **Why `is_file()` is checked.** `sqlite3.connect` would silently create an empty file for a mistyped path and then fail with "no such table". Checking first also keeps stray DBs from being created in the tree.
- **Why the loader is called lazily.** It is only called on the FTS path, so the `crawl.db` path does not load `sync-whitelist.py` at all, and so does not need its load-time parse of `schema.sql`. The whitelist path loads it once per call, which is cheap.
- **Log format.** `"%(levelname)s %(message)s"` and `rows=%d` follow `recompute-popularity.py`, so the CLI test can parse the count.

**Deliberate simplification: no transaction across the FTS path.** The settled helpers commit internally, so the job cannot be atomic. The ceiling is that a crash between the trigger recreate and the rebuild leaves correct names with a stale index. Recovery is a re-run: it reports `rows=0`, but it rebuilds and checks the count. If one transaction is ever required, the upgrade path is to run `VIDEOS_FTS_DROP_TRIGGERS_SQL` and `VIDEOS_FTS_TRIGGERS_SQL` through `conn.execute` statement by statement instead of `executescript`. That is a change to `sync-whitelist.py`, which is outside this build.

---

### 4. Tests: `tests/active/test_channel_names.py`

**Module constants and imports:**

```python
"""Each video carries its own instance's channel name (issue 34).

- The compiled `crawlVideos` in `engine/crawler/dist/videos-worker.js`, run under node against two loopback hosts sharing a channel_id, writes each host's videos with that host's channel display name and URL; a missing node, git, node_modules or dist, or a stale dist, fails the test rather than skipping it.
- `repair-video-channel-names.py` corrects mismatched and NULL names on both the crawl.db and whitelist.db shapes, leaves correct rows and rows whose channel has an empty, NULL or absent display name untouched, reports the changed count, and changes 0 rows on a second run.
- On the whitelist.db shape the repaired videos_fts finds a channel's videos by its own name, not by the other instance's same-id name, and holds as many rows as videos.
- The CLI requires --db and logs the changed count.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import pytest
from conftest import ROOT

SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

CRAWLER_DIR = ROOT / "engine" / "crawler"
SRC = CRAWLER_DIR / "src" / "videos-worker.ts"
DIST = CRAWLER_DIR / "dist" / "videos-worker.js"
CRAWL_SCHEMA = CRAWLER_DIR / "schema.sql"
BUILD_HINT = "cd engine/crawler && npm install && npm run build"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
REPAIR_JOB = JOBS_DIR / "repair-video-channel-names.py"
```

**Helpers copied inline.** `_git`, `_dist_is_stale` and `_load_job` are copied verbatim from `test_host_normalisation.py`. They read the module-level `SRC`, `DIST` and `JOBS_DIR`, so they check the videos-worker pair.

**Module fixture:**

```python
@pytest.fixture(scope="module")
def jobs():
    return _load_job("sync_whitelist_channel_names", "sync-whitelist.py"), _load_job("repair_video_channel_names", "repair-video-channel-names.py")
```

#### Crawl test

**Node script.** Run with `node --input-type=module -e`, with `cwd=CRAWLER_DIR`:

```js
const { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);
await crawlVideos(JSON.parse(process.env.CRAWL_OPTIONS));
```

**Fake server:**

```python
class _ChannelVideosHandler(BaseHTTPRequestHandler):
    timeout = 1  # the crawler tries https first; a TLS ClientHello with no newline would otherwise hold readline until the crawler's own timeout

    def do_GET(self):
        path = urlsplit(self.path).path
        prefix, suffix = "/api/v1/video-channels/", "/videos"
        slug = unquote(path[len(prefix):-len(suffix)]) if path.startswith(prefix) and path.endswith(suffix) else None
        videos = self.server.videos_by_slug.get(slug)
        if videos is None:
            self.send_error(404)
            return
        body = json.dumps({"total": len(videos), "data": videos}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
```

**Crawl options.** The 18 keys from `videos-cli.ts:87-107`:

```python
def _crawl_options(db_path) -> dict:
    return {"dbPath": str(db_path), "excludeHostsFile": None, "existingDbPath": None, "concurrency": 1, "timeoutMs": 3000, "maxRetries": 0, "newOnly": False, "stopAfterFullPages": 0, "sort": "-publishedAt", "maxInstances": 0, "maxChannels": 0, "maxVideosPages": 0, "tagsOnly": False, "updateTags": False, "commentsOnly": False, "hostDelayMs": 0, "resume": False, "errorsOnly": False}
```

**`test_crawl_writes_each_hosts_own_channel_name(tmp_path)` runs in this order:**
1. **Gates, the same as `test_crawler_dist_returns_pinned_values`:** node is on PATH, `DIST.is_file()`, git is on PATH, and `not _dist_is_stale(git)`. Each gate's message carries `BUILD_HINT`. A missing `node_modules` (better-sqlite3) shows up as a nonzero node exit, and that assertion also carries `BUILD_HINT`.
2. **Servers.** Two `ThreadingHTTPServer(("127.0.0.1", 0), _ChannelVideosHandler)`, each run with `serve_forever` in a daemon thread. `host_a = f"127.0.0.1:{server_a.server_port}"`, and `host_b` likewise.
   - `server_a.videos_by_slug = {"alpha_chan": [{"uuid": "a1", "id": 1, "name": "Alpha one"}, {"uuid": "a2", "id": 2, "name": "Alpha two"}]}`
   - `server_b.videos_by_slug = {"beta_chan": [{"uuid": "b1", "id": 1, "name": "Beta one"}]}`
   - The payloads carry no `channel` key, so neither the payload name nor the payload URL can mask the lookup.
   - Both servers are shut down and closed in `finally`.
3. **DB.** `tmp_path / "crawl.db"` is created with `executescript(CRAWL_SCHEMA.read_text())`. It gets both hosts in `instances`, and these rows in `channels` (named columns):
   - `("7", "alpha_chan", "Alphachan", f"http://{host_a}/c/alpha_chan", host_a, 2)`
   - `("7", "beta_chan", "Betachan", f"http://{host_b}/c/beta_chan", host_b, 1)`
4. **Run.** `subprocess.run([node, "--input-type=module", "-e", NODE_SCRIPT], cwd=CRAWLER_DIR, capture_output=True, text=True, encoding="utf-8", timeout=120, env={**os.environ, "VIDEOS_WORKER_URL": DIST.as_uri(), "CRAWL_OPTIONS": json.dumps(_crawl_options(db))})`. The run must exit 0; on failure the message includes stderr and `BUILD_HINT`.
5. **Assert** that `{(instance_domain, video_id): (channel_name, channel_url)}` read from `videos` equals exactly:
   - `(host_a, "a1")` and `(host_a, "a2")` → `("Alphachan", f"http://{host_a}/c/alpha_chan")`
   - `(host_b, "b1")` → `("Betachan", f"http://{host_b}/c/beta_chan")`

   On failure the message includes node's stdout. Exact equality also catches a crawl that wrote nothing.

**Why it fails on today's code.** Whichever order `listChannelsWithVideos` returns the rows in, the id-only map keeps one entry for id `7`, so one host's rows get the other host's name and URL.

**How the fake servers are reached.** The crawler tries https first against the plain-HTTP server. That attempt fails with a TLS error or ECONNRESET, or with an abort when the handler's 1 s read timeout closes the socket. None of these codes is in `isNoNetworkError`, so curl never runs. With `maxRetries 0` the https attempt throws, and `fetchPage` falls back to http. `ThreadingHTTPServer` answers each connection on its own thread, so the stuck https connection does not block the http one.

#### Repair tests

**Seed data.** `_seed(conn)` inserts with named columns, so it works on both schemas. Videos carry `last_checked_at = 1`, a distinct title such as `"clip v1"`, and description `"plain text"`.

| channels `(channel_id, instance_domain, display_name)` |
|---|
| `("7", "a.example", "Alphachan")` |
| `("7", "b.example", "Betachan")` |
| `("8", "a.example", "")` |
| `("9", "a.example", None)` |

| video | instance, channel | stored `channel_name` | expected after repair |
|---|---|---|---|
| v1 | a.example, 7 | `"Betachan"` | `"Alphachan"` |
| v2 | b.example, 7 | `"Alphachan"` | `"Betachan"` |
| v3 | b.example, 7 | `"Betachan"` | unchanged |
| v4 | a.example, 8 | `"Stalename"` | unchanged (empty `display_name`) |
| v5 | a.example, 9 | `"Stalename"` | unchanged (NULL `display_name`) |
| v6 | a.example, 404 | `"Orphanname"` | unchanged (no channel row) |
| v7 | a.example, 7 | `None` | `"Alphachan"` |

`EXPECTED_CHANGED = 3`.

**Fixture.** `seeded_db` is `@pytest.fixture(params=["crawl", "whitelist"])` and uses `jobs` and `tmp_path`:
- `"crawl"` runs `executescript(CRAWL_SCHEMA.read_text())`.
- `"whitelist"` runs `sync.ensure_content_schema(conn)`, which creates `videos_fts` and its triggers, so the index is seeded with the stale names.
- It then calls `_seed`, commits, closes, and returns the path. The FTS table is present or absent according to the parameter.

**Tests:**
- **`test_repair_sets_each_video_to_its_own_channel_name(jobs, seeded_db)`**
  - Calls `repair.repair_channel_names(conn)` and asserts it returns `3`.
  - Asserts `dict(SELECT video_id, channel_name FROM videos)` equals the expected column.
  - Asserts the `channels` rows are unchanged, compared with a snapshot taken before the repair.
  - Asserts a second call returns `0` and leaves the dict the same.
  - Asserts `has_videos_fts(conn)` is `True` exactly for the `whitelist` parameter.
- **`test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path)`** (whitelist shape only)
  - `_matches(conn, name)` runs `SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?` with `f'channel_name : "{name}"'`.
  - After the repair, `Alphachan` gives `{"v1", "v7"}` and `Betachan` gives `{"v2", "v3"}`. That excludes v1, which carried `Betachan` in the stale index before the repair.
  - `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos`, which is 7.
- **`test_cli_requires_db_and_logs_changed_count(tmp_path)`**
  - Running `[sys.executable, str(REPAIR_JOB)]` exits with return code `2` (argparse, `--db` required).
  - A crawl-shape seeded DB is built inline, and `[sys.executable, str(REPAIR_JOB), "--db", str(db)]` exits `0`.
  - `re.search(r"channel names repaired rows=(\d+)", proc.stderr)` gives `3`. A second run gives `0`.

**Isolation.** Every DB lives under `tmp_path`. No test requests the `engine` or `dataset` fixtures or refers to `WHITELIST_DB`.

---

### 5. Runbook: `DATA_BUILD.md`

Insert after line 158, before `## 3) Build embeddings`:

````markdown
## 2b) Repair `videos.channel_name` (one-off migration)
Until issue 34 was fixed, the video crawler looked up channel metadata by `channel_id` alone, so about 74% of videos carry the display name of the same-id channel on another instance; search and embeddings inherit the wrong name.

This is a migration of shared databases: run it on main after the fix is merged, never from a worktree. Run it outside an updater cycle and with the Engine idle, because on a `whitelist.db` it rebuilds `videos_fts` and holds the write lock for the duration.

1. Merge the fix to main.
2. Repair the crawl database:
   ```bash
   python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db
   ```
3. Repair every copy of `whitelist.db`, the prod/server database included. The updater merges `videos` `INSERT_ONLY`, so it never corrects existing rows:
   ```bash
   python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/server/db/whitelist.db
   ```
4. Operator follow-up, scheduled with plan 17's (stable ANN ids) cutover so the index is rebuilt only once: re-embed, rebuild the ANN index, then the similarity cache.
   ```bash
   python3 engine/server/db/jobs/build-video-embeddings.py \
     --db-path engine/server/db/whitelist.db --force
   python3 engine/server/db/jobs/build-ann-index.py \
     --db-path engine/server/db/whitelist.db \
     --index-path engine/server/db/whitelist-video-embeddings.faiss \
     --meta-path engine/server/db/whitelist-video-embeddings.faiss.json \
     --normalize --gpu
   python3 engine/server/db/jobs/precompute-similar-ann.py \
     --db engine/server/db/whitelist.db \
     --index engine/server/db/whitelist-video-embeddings.faiss \
     --out engine/server/db/similarity-cache.db \
     --reset --gpu
   ```
   Use `--cpu` in place of `--gpu` where there is no CUDA.

Notes:
- `--db` is required; the job has no default database.
- The job logs `channel names repaired rows=N`. A second run reports `rows=0`, and on a `whitelist.db` it still rebuilds and checks the full-text index, so re-running is the recovery if a run is interrupted.
- Search reflects the corrected names as soon as step 3 finishes; similar-video results only do so after step 4.
- A fresh crawl with the fixed crawler writes correct names by itself, so the job is not part of `run-dataset-build.sh`.
````

**Plan 17 reference.** The runbook names "plan 17 (stable ANN ids)" without a path, because `docs/project/plans/17-stable-ann-ids.md` does not exist in this tree. Line 30's broken `UPDATER_WORKER.md` pointer is not touched. `UPDATER_WORKER.md` is left alone because the `INSERT_ONLY` note is in this section.

---

### Checked against the plan and the requirements

| Requirement | How the draft meets it |
|---|---|
| R1 | The key is host plus id at both the build and the lookup, from the same column and lowercased on both sides. Precedence is unchanged, the rest of the crawler is unchanged, and the dist is rebuilt. |
| R2 | One set-based UPDATE with a `(channel_id, instance_domain)` join, guarded for non-NULL, non-empty and `IS NOT`. `channels` is only read. The count comes from `rowcount`, and a second run returns 0. The CLI has argparse, `CompactHelpFormatter`, a required `--db PATH`, INFO logging and a guarded `main()`. |
| R3 | The `videos_fts` probe, then the reused drop / update / create / rebuild helpers loaded by `spec_from_file_location`. The count check copies `sync-whitelist.py`'s `RuntimeError`, and the FTS steps are skipped on `crawl.db`. |
| R4 | A two-host crawl test with the node gates, which fails on today's code. Repair tests on both schemas cover mismatched, correct, empty, NULL, absent and NULL-current rows, plus the second run. There is an FTS test with column-filtered MATCH and the count check, a CLI test, and only `tmp_path` DBs. |
| R5 | The section after step 2 has the merge / crawl.db / every whitelist.db / re-embed order, "main after merge only, never from a worktree", and the timing note. |

**Constraints.** The job uses only the stdlib and adds no dependency or abstraction. The agent never runs it against a real database. The existing suite is untouched: `test_host_normalisation.py` checks `host-filters`, whose source does not change.

**Risks the operator carries** (from the plan, unchanged):
- The FTS path is not atomic.
- Every whitelist run pays a full rebuild.
- The repair joins `instance_domain` exactly as stored, so a channel whose `instance_domain` is stored in mixed case would not be repaired.
- The new test needs `engine/crawler/node_modules`, a stricter requirement than `test_host_normalisation.py`.
- Embeddings keep the foreign names until step 4.

### Phases

#### Phase 1 - Crawler keys channel metadata by host and id [code]

**Files touched.** engine/crawler/src/videos-worker.ts (EDITED), engine/crawler/dist/videos-worker.js (EDITED), tests/active/test_channel_names.py (NEW)

**Checkpoint.** `test_crawl_writes_each_hosts_own_channel_name(tmp_path)` in the new `tests/active/test_channel_names.py`. Seam: the compiled `crawlVideos` exported by `engine/crawler/dist/videos-worker.js`. The test runs it under `node --input-type=module -e` with `cwd=engine/crawler` against two stdlib `ThreadingHTTPServer`s on `127.0.0.1` ephemeral ports and a temp `crawl.db` built from `engine/crawler/schema.sql`. Both channels rows share `channel_id` "7" and have different display names and URLs. The test asserts exact equality of `{(instance_domain, video_id): (channel_name, channel_url)}` read from `videos`. Harness precedent: `test_host_normalisation.py::test_crawler_dist_returns_pinned_values`. The test copies its `_git` / `_dist_is_stale` gates and `BUILD_HINT`. A missing node or git, a missing or stale dist, or a nonzero node exit fails the test and never skips it. On today's code the test fails deterministically, because the id-only map keeps one entry for "7".

**Intent.** `crawlVideos` in `engine/crawler/src/videos-worker.ts` (and its committed `dist/videos-worker.js`) looks up channel metadata by lowercased host plus channel id. As a result, each host's crawled videos carry that host's own channel metadata, even when a channel id repeats across instances.

- C1 - Each host's crawled videos have `channel_name` equal to the `display_name` of the channel on that same host.
- C2 - Each host's crawled videos have `channel_url` equal to the `channel_url` of the channel on that same host.

**Outcome.** ### `engine/crawler/src/videos-worker.ts`
- `crawlVideos` now keys the `channelMeta` map by `channelMetaKey(channel.instance_domain.toLowerCase(), channel.channel_id)` instead of by `channel.channel_id` alone. Before, when two instances had the same channel id, the later row overwrote the earlier one and both hosts got the same `channel_name`/`channel_url`.
- `processInstance` looks up metadata with `channelMetaKey(normalizedHost, item.channelId)`. `normalizedHost` is already lowercased, so both sides of the lookup use the same host form.
- New helper `channelMetaKey(host, channelId)` returns `` `${host}/${channelId}` ``. A host cannot contain `/`, so two different host/id pairs can never produce the same key. It has a one-line JSDoc comment explaining why ids need the host, matching the file's other function comments.

### `engine/crawler/dist/videos-worker.js`
- Edited by hand to match the source change in the style tsc produces here (same two call sites, plus `channelMetaKey` with its JSDoc and no type annotations). I have no shell, so I could not run `npm run build`. The dist was saved after the source, so its mtime is newer and the checkpoint's staleness check, which compares mtimes on a dirty tree, will pass. There is no source map to update.

### `tests/active/test_channel_names.py`
- Not created. It is the checkpoint's permanent location, and this turn was limited to production code. The gating checkpoint stays at `tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py`, unchanged.

#### Phase 2 - Repair function corrects channel names [code]

**Files touched.** engine/server/db/jobs/repair-video-channel-names.py (NEW), tests/active/test_channel_names.py (EDITED)

**Checkpoint.** `test_repair_sets_each_video_to_its_own_channel_name(jobs, seeded_db)`. Seam: the in-process function `repair_channel_names(conn)` in `repair-video-channel-names.py`. The job is loaded with the `_load_job` importlib loader copied from `test_host_normalisation.py`. The fixture `seeded_db` is parametrised over the `crawl` shape (`schema.sql`) and the `whitelist` shape (`ensure_content_schema` from the loaded `sync-whitelist.py`). `_seed` loads the v1–v7 / channels 7, 8, 9 table from the draft. Asserts: the returned count is 3; the `video_id -> channel_name` dict equals the expected column; `channels` equals its pre-repair snapshot; a second call returns 0 and leaves the dict unchanged; `has_videos_fts` is True exactly for the whitelist parameter. Every DB is under `tmp_path`.

**Intent.** The new job `engine/server/db/jobs/repair-video-channel-names.py` exposes `repair_channel_names`. It sets each video's `channel_name` to the non-empty `display_name` of its own `(channel_id, instance_domain)` channel and returns how many rows it changed.

- C1 - After a repair, videos with a foreign or NULL `channel_name` carry their own channel's `display_name`. Already-correct rows, rows whose channel has an empty, NULL or absent display name, and the `channels` table are unchanged.
- C2 - The repair returns the number of rows it changed, and a second run returns 0.

**Outcome.** ### `engine/server/db/jobs/repair-video-channel-names.py` (NEW)
A new job module with two functions, stdlib `sqlite3` only:
- `repair_channel_names(conn) -> int` runs one `UPDATE videos` statement inside `with conn:`, so it commits. It sets `channel_name` to the `display_name` of the channel matching the video's own `(channel_id, instance_domain)`. A row is only touched when that channel exists, its `display_name` is not NULL or empty, and the stored name differs from it (`IS NOT`, so NULL stored names get repaired too). It returns `cursor.rowcount`, the number of rows it changed, which makes a second run return 0. `channels` is only read, never written. On the whitelist shape, the existing `videos_fts_au` trigger re-indexes each changed row.
- `has_videos_fts(conn) -> bool` checks `sqlite_master` for the `videos_fts` table. It is True on the whitelist shape and False on the crawl shape.

There is no CLI entry point yet. The checkpoint only exercises the functions, and this phase's intent only calls for exposing `repair_channel_names`.

I did not touch `tests/active/test_channel_names.py`, which the phase lists as EDITED. It does not exist in the worktree yet, and nothing in this phase's checkpoint needs it. I read that entry as the promotion target for the checkpoint, which the workflow handles.

I checked the behaviour with a throwaway probe (`tests/tmp/probe_repair_rowcount.py`), using the same seed shape as the checkpoint on both a crawl-schema and a whitelist-schema database:
- **Both shapes:** the first call returned 3 and the second returned 0. After reopening the database, v1 and v7 read `A` and v2 read `B`, while v3–v6 kept their stored names.
- **Whitelist shape:** `has_videos_fts` was True, and `rowcount` was still 3 even with the FTS triggers firing. An FTS5 `integrity-check` passed after the update, and `channel_name:A` matched rowids 1 and 7.

I have no tool that deletes files, so the probe file is still in `tests/tmp/` and should be removed. It is not part of the phase.

#### Phase 3 - "`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>
<name>Repair rebuilds the search index [code]

**Files touched.** engine/server/db/jobs/repair-video-channel-names.py (EDITED), tests/active/test_channel_names.py (EDITED)

**Checkpoint.** `test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path)`. Seam: the `videos_fts` table of a whitelist-shape temp DB. The DB is created with `ensure_content_schema`, seeded with stale names (so the index holds them), and then repaired through `repair_channel_names`. The test queries `SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?` with `channel_name : "<name>"`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).

**Intent.** On a database that has `videos_fts`, the repair runs between `sync-whitelist.py`'s trigger drop and recreate and then rebuilds the index, so full-text search reflects the corrected channel names in full.

- C1 - After the repair, a `channel_name` MATCH for a channel's own name returns that channel's videos, and a MATCH for the other instance's same-id name does not return them.
- C2 - After the repair, `videos_fts` holds as many rows as `videos`.

**Outcome.** I ran none of the gating tests myself. Everything I checked came from a throwaway probe, described below.

### `engine/server/db/jobs/repair-video-channel-names.py`
- **New `_load_sync_whitelist()`.** Loads `sync-whitelist.py` with `importlib.util.spec_from_file_location`, because its hyphenated name rules out a normal import. This lets the job reuse the file's `videos_fts` helpers instead of copying FTS SQL. It runs only on the FTS path, so crawl.db never loads that file.
- **`repair_channel_names(conn)` without `videos_fts` (crawl shape).** Unchanged: one UPDATE inside `with conn:`, returning the number of rows changed.
- **`repair_channel_names(conn)` with `videos_fts` (whitelist shape).** Follows the same order as `rebuild_content_tables`:
  1. `drop_videos_fts_triggers`
  2. the UPDATE, with `rowcount` read straight away
  3. `create_videos_fts_triggers`
  4. `rebuild_videos_fts`
  5. compare the rebuilt count with `COUNT(*)` on `videos`, and raise `RuntimeError` in `sync-whitelist.py`'s wording if they differ
  6. `conn.commit()`
- **Rebuild on every run.** The rebuild and count check run even when nothing changed. So re-running the job fixes an index left stale by an interrupted run, and it also fixes drift that the per-row trigger `'delete'` cannot mend.
- **`rat-tail:` comment.** Records that the helpers use `executescript`, which commits. The update is therefore already committed before the rebuild, and a failed rebuild is recovered by running the job again, not by rollback. Upgrade path: have the helpers run their SQL through `conn.execute` instead.
- **Docstrings.** The module and function docstrings now describe the rebuild.

**Probe results.** The probe (`tests/tmp/probe_34_phase3_impl.py`) built a smaller version of the checkpoint's drifted index on a whitelist-shaped database: v1 corrected and v8 inserted while the triggers were dropped.
- The second run returned 0.
- After reopening, `channel_name : "Alphachan"` matched `['v1', 'v7']` and `"Betachan"` matched `['v2']`.
- `videos_fts_docsize` held 4 rows for 4 videos, and the FTS5 integrity-check passed.
- On a crawl-shaped database, `has_videos_fts` was False.

I have no delete tool, so I emptied the probe file instead of removing it. It is part of no phase and should be deleted.

### `tests/active/test_channel_names.py`
Not touched. As in Phase 2, I read the listing as the checkpoint's promotion target, which the workflow handles.

#### Phase 4 - Repair CLI [code]

**Files touched.** engine/server/db/jobs/repair-video-channel-names.py (EDITED), tests/active/test_channel_names.py (EDITED)

**Checkpoint.** `test_cli_requires_db_and_logs_changed_count(tmp_path)`. Seam: the script's command line, run through `subprocess.run([sys.executable, str(REPAIR_JOB), ...])`. Asserts: a bare invocation exits with return code 2. Against an inline-seeded crawl-shape DB under `tmp_path`, the run exits 0, and `re.search(r"channel names repaired rows=(\d+)", proc.stderr)` gives 3. A second run gives 0.

**Intent.** `repair-video-channel-names.py` runs as a command that refuses to start without an explicit `--db` and logs the number of rows it changed.

- C1 - Invoking the job without `--db` exits with an argparse usage error (return code 2).
- C2 - Invoking the job with `--db` logs `channel names repaired rows=N` with the changed count.

**Outcome.** ### `engine/server/db/jobs/repair-video-channel-names.py`
- Added a command line that follows `recompute-popularity.py` and `sync-whitelist.py`. It appends `engine/server` to `sys.path` and imports `CompactHelpFormatter` from `scripts.cli_format`.
- Added `main()`, called under an `if __name__ == "__main__"` guard. It uses argparse with `CompactHelpFormatter` and a single `--db PATH` argument that is required and has no default. The neighbouring jobs default to the shared `whitelist.db`, and a migration run with no arguments must never hit that by accident.
- Logging is set up with `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")`.
- A `--db` path that is not an existing file is rejected with `parser.error("database not found: ...")`, which exits 2. Without this check, `sqlite3.connect` would quietly create an empty file and then fail on the missing tables.
- After the path check, `main()` opens the connection, calls the existing `repair_channel_names(conn)`, closes the connection in `finally`, and logs `channel names repaired rows=%d`.
- `repair_channel_names`, the SQL and the FTS handling are unchanged.

### `tests/active/test_channel_names.py`
- Not touched. It does not exist in the worktree yet, and this phase's checkpoint lives in `tests/tmp/`. I take the EDITED entry to mean the checkpoint gets promoted there, which the workflow handles. Phase 3 read it the same way.

**Beyond the files named.** tests/tmp/probe_34_phase4_impl.py - a throwaway probe. It checked that the edited module still loads in-process through `importlib` (phases 2 and 3 load it that way) now that it changes `sys.path` and imports `scripts.cli_format`. It also checked the four CLI cases. A bare run exits 2 with `the following arguments are required: --db`. A missing `--db` path exits 2 with `database not found` and creates no file. The seeded crawl DB logs `INFO channel names repaired rows=3`, and a second run logs `rows=0`. I have no delete tool, so please remove it. `tests/tmp/probe_34_phase4_cli.py`, left over from authoring the checkpoint, is still there too and can go with it.


